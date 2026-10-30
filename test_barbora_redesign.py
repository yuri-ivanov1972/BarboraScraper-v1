"""Sanitized retailer fixtures and isolated PostgreSQL recovery regression tests."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psycopg2
from psycopg2.extras import RealDictCursor

import test_product_refresh as fixtures
from barbora_site_data import (SiteDataError, category_page, market, normalized_product,
                               product_data, verify_category_path)
from barbora_parser import BarboraParser
from barbora_catchup import FIELDS, apply, digest, observation, preview, timestamp, retry_failed
from product_refresh_source import parse_full_page
from nutrition_reload_source import BarboraSource, parse_page
from barbora_lightweight_updater import BarboraLightweightUpdater
from barbora_worker import BarboraWorker


SKU = fixtures.SKU
PRODUCT = dict(id=SKU, title="Jogurts LAKTO 200g", url="jogurts-lakto-200g",
               status="active", price=.99, categoryShortId="ABC",
               categoryId="00000000-0000-0000-0000-000000000000",
               categoryPathUrl="c/ABC/yogurt", brand="LAKTO",
               comparativeUnit=dict(type="kg", price=4.95),
               promotion=dict(oldPrice=1.39, oldComparativeRateGross=6.95,
                              loyaltyCardRequired=True),
               ingredients="piens", imagesOriginal=["https://cdn.barbora.lv/products/new.png"],
               nutrients={k: dict(value=v, gdaPercent=99) for k, v in dict(
                   calories=73, kj=310, fat=.2, saturatedFat=0, carbohydrates=8.9,
                   sugar=8.6, protein=8.9, salt=.09).items()})


def html(product=None, items=None, count=1, offset=0, limit=60, path="yogurt"):
    queries = [dict(queryKey=[dict(_id="categoriesGet")], state=dict(data=dict(categories=[
        dict(shortId="ABC", categoryId="new-uuid", fullUrl="c/ABC/" + path)
    ])))]
    if product is not None:
        queries.append(dict(queryKey=[dict(_id="productProductByUrl")], state=dict(data=product)))
    if items is not None:
        queries.append(dict(queryKey=[dict(_id="inventoryCategoryInventory")], state=dict(data=dict(
            inventories=items, count=count, offset=offset, limit=limit,
            categoryMetadata=dict(url="c/ABC/" + path)))))
    context = dict(state=dict(loaderData={"route": dict(dehydratedState=dict(queries=queries))}))
    return "<script>window.__remixContext = " + json.dumps(context) + ";</script>"


class AdapterTests(unittest.TestCase):
    def test_exact_string_identity_and_new_url(self):
        page = html(product=PRODUCT)
        result = parse_full_page(page, "https://barbora.lv/p/jogurts-lakto-200g", SKU)
        self.assertEqual(result["sku"], SKU)
        self.assertEqual(result["market"]["discount_price"], .99)
        self.assertEqual(result["market"]["price_per_unit"], 6.95)
        self.assertEqual(result["market"]["discount_price_per_unit"], 4.95)
        self.assertEqual(result["nutrition"]["energy_kcal"], 73)
        self.assertEqual(result["nutrition"]["fat_saturated"], 0)
        self.assertNotIn("fiber", result["nutrition"])
        self.assertEqual(BarboraParser().build_product_url("p/test"), "https://barbora.lv/p/test")

    def test_unavailable_is_explicit(self):
        self.assertFalse(market(dict(PRODUCT, status="outOfStock"))["is_available"])
        for status in (None, "", "unexpected"):
            with self.assertRaises(SiteDataError):
                market(dict(PRODUCT, status=status))

    def test_invalid_prices_and_nutrition_are_not_zero_filled(self):
        for value in (None, True, "1.2", -1, float("inf")):
            with self.assertRaises(SiteDataError):
                market(dict(PRODUCT, price=value))
        p = dict(PRODUCT, nutrients={"salt": dict(value=-1)})
        self.assertEqual(parse_page(html(product=p))["nutrition_issue"], "invalid_nutrition")
        self.assertIsNone(BarboraParser().parse_product_details(html(product=p)).nutrition)

    def test_integer_sku_and_mismatch_rejected(self):
        with self.assertRaises(SiteDataError):
            product_data(html(product=dict(PRODUCT, id=940284)))
        with self.assertRaises(ValueError):
            parse_full_page(html(product=PRODUCT), fixtures.URL, "000000000000000001")

    def test_empty_distinct_from_unrecognized(self):
        self.assertEqual(category_page(html(items=[], count=0))["count"], 0)
        with self.assertRaises(SiteDataError):
            category_page("<html>Access denied</html>")
        with self.assertRaises(SiteDataError):
            category_page(html(items=[], count=1))

    def test_page_offset_duplicate_and_category_guard(self):
        with self.assertRaises(SiteDataError):
            category_page(html(items=[PRODUCT]), page=2)
        with self.assertRaises(SiteDataError):
            category_page(html(items=[PRODUCT, PRODUCT], count=2))
        with self.assertRaises(SiteDataError):
            verify_category_path(category_page(html(items=[PRODUCT])), "other/yogurt")
        verify_category_path(category_page(html(items=[PRODUCT])), "yogurt")

    def test_pagination_metadata_not_old_fixed_size(self):
        p2 = dict(PRODUCT, id="000000000000000002")
        parser = BarboraParser()
        responses = [SimpleNamespace(text=html(items=[PRODUCT], count=2, limit=1),
                                     raise_for_status=lambda: None),
                     SimpleNamespace(text=html(items=[p2], count=2, offset=1, limit=1),
                                     raise_for_status=lambda: None)]
        with patch.object(parser.session, "get", side_effect=responses), patch("barbora_parser.time.sleep"):
            self.assertEqual(len(parser.extract_products_from_category("yogurt")), 2)
        responses[1].text = responses[0].text
        with patch.object(parser.session, "get", side_effect=responses), patch("barbora_parser.time.sleep"):
            with self.assertRaises(SiteDataError):
                parser.extract_products_from_category("yogurt")

    def test_http_failure_does_not_return_partial_category(self):
        import requests
        parser = BarboraParser()
        first = SimpleNamespace(text=html(items=[PRODUCT], count=2, limit=1),
                                raise_for_status=lambda: None)
        with patch.object(parser.session, "get", side_effect=[first, requests.RequestException()]), \
                patch("barbora_parser.time.sleep"):
            with self.assertRaises(SiteDataError):
                parser.extract_products_from_category("yogurt")

    def test_category_recovery_cache_requires_all_pages(self):
        source = BarboraSource(delay=0)
        with patch.object(source, "fetch", return_value=(html(items=[PRODUCT], count=2, limit=1), fixtures.URL)):
            with self.assertRaises(SiteDataError):
                source.category_urls("yogurt")
        self.assertFalse(source.category_cache)

    def test_redesign_promotion_legacy_normalization(self):
        normalized = normalized_product(PRODUCT, {})
        self.assertEqual(normalized["promotion"]["oldComparativeRate"], 6.95)
        self.assertEqual(observation(normalized)["discount_price_per_unit"], 4.95)

    def test_failed_run_not_successful_zero(self):
        updater = BarboraLightweightUpdater()
        with patch.object(updater, "get_all_level3_categories", return_value=[dict(name_lv="test")]), \
                patch.object(updater, "get_existing_skus", return_value=set()), \
                patch.object(updater, "process_category", side_effect=ValueError("unrecognized")), \
                patch.object(updater, "apply_hidden_overrides") as hidden, \
                patch("photo_maintenance.PhotoMaintenance.initialize"), \
                patch("barbora_lightweight_updater.time.sleep"):
            summary = updater.run_full_update()
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["categories_with_errors"], 1)
        hidden.assert_not_called()

    def test_preview_excludes_partial_category(self):
        source = BarboraSource(delay=0, retries=0)
        source.fetch = Mock(side_effect=[
            (html(items=[PRODUCT], count=2, limit=1), fixtures.URL),
            ("<html>Access denied</html>", fixtures.URL)])
        with patch("barbora_catchup.snapshot", return_value=(
                [dict(category_id="1", name_lv="Yogurt", path="yogurt", barbora_category_code="old")],
                {SKU: dict(sku=SKU, name="Test")})):
            result = preview("unused", "fixture", source=source)
        self.assertFalse(result["complete"])
        self.assertFalse(result["products"])
        self.assertEqual(result["summary"]["failed_categories"], 1)

    def test_missing_category_identity_is_a_safe_failure(self):
        page = html(items=[], count=0)
        page = page.replace('"url": "c/ABC/yogurt"', '"url": null')
        with self.assertRaisesRegex(SiteDataError, "missing_category_identity"):
            category_page(page)

    def test_readonly_retry_merges_without_losing_completed_coverage(self):
        prior = dict(target="fixture", scope="prices_availability_only", bounded=False,
                     started_at=timestamp(), categories_total=2,
                     coverage=[dict(path="one", status="complete"), dict(path="two", status="failed")],
                     products=[dict(sku="1", observed={"price": 1}, changed=True)],
                     excluded_new=[], not_seen=[dict(sku="2")])
        prior["checksum"] = digest(prior)
        fresh = dict(coverage=[dict(path="two", status="complete")],
                     products=[dict(sku="2", observed={"price": 2}, changed=False)],
                     excluded_new=[], not_seen=[dict(sku="1")])
        with patch("barbora_catchup.preview", return_value=fresh) as fetch:
            result = retry_failed("unused", "fixture", prior)
        self.assertTrue(result["complete"])
        self.assertEqual(result["summary"]["existing_observed"], 2)
        self.assertEqual(result["summary"]["changes"], 1)
        self.assertFalse(result["not_seen"])
        self.assertFalse("complete" in prior)
        fetch.assert_called_once_with("unused", "fixture", source=None, only_paths={"two"})

    def test_scheduler_does_not_process_failed_zero_run(self):
        from lightweight_scheduler import run_lightweight_update
        updater = Mock()
        updater.run_full_update.return_value = dict(status="failed", products_checked=0)
        with patch("barbora_lightweight_updater.BarboraLightweightUpdater", return_value=updater), \
                patch("barbora_worker.BarboraWorker") as worker, \
                patch("photo_maintenance.PhotoMaintenance") as photos:
            result = run_lightweight_update()
        self.assertEqual(result["status"], "failed")
        worker.assert_not_called()
        photos.assert_not_called()

    def test_scheduler_processes_successful_category_jobs_in_partial_run(self):
        from lightweight_scheduler import run_lightweight_update
        updater = Mock()
        updater.run_full_update.return_value = dict(
            status="incomplete", products_checked=10, new_products_found=2)
        with patch("barbora_lightweight_updater.BarboraLightweightUpdater", return_value=updater), \
                patch("barbora_worker.BarboraWorker") as worker, \
                patch("photo_maintenance.PhotoMaintenance") as photos:
            photos.return_value.run_scheduled.return_value = []
            result = run_lightweight_update()
        self.assertEqual(result["status"], "incomplete")
        worker.return_value.run.assert_called_once_with(exit_when_empty=True)


class RecoveryDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.DatabaseTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.DatabaseTests.tearDownClass.__func__)
    setUp = fixtures.DatabaseTests.setUp

    def manifest(self):
        with psycopg2.connect(self.dsn) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM product_price_history WHERE product_id=1 ORDER BY recorded_at DESC LIMIT 1")
            old = cur.fetchone()
        baseline = {k: float(old[k]) if old[k] is not None and k not in (
            "price_per_unit_type", "is_available") else old[k] for k in FIELDS}
        observation = dict(baseline, price=1.39, discount_price=.99, price_per_unit=6.95,
                           discount_price_per_unit=4.95, is_available=True)
        result = dict(version=1, target="fixture", complete=True, bounded=False,
                      scope="prices_availability_only", started_at=timestamp(), finished_at=timestamp(),
                      products=[dict(sku=SKU, product_id="1", baseline=baseline,
                                     baseline_history_id=str(old["price_history_id"]),
                                     observed=observation)])
        result["checksum"] = digest(result)
        return result

    def test_apply_prices_only_and_idempotent(self):
        manifest = self.manifest()
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT row_to_json(p) FROM products p WHERE product_id=1")
            before = cur.fetchone()[0]
        self.assertEqual(apply(self.dsn, "fixture", manifest), 1)
        self.assertEqual(apply(self.dsn, "fixture", manifest), 0)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT row_to_json(p) FROM products p WHERE product_id=1")
            self.assertEqual(cur.fetchone()[0], before)
            cur.execute("SELECT count(*) FROM product_price_history WHERE data_source='redesign_catchup'")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_stale_conflict_rolls_back(self):
        manifest = self.manifest()
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("UPDATE product_price_history SET price=12 WHERE product_id=1")
        with self.assertRaisesRegex(ValueError, "baseline changed"):
            apply(self.dsn, "fixture", manifest)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM product_price_history WHERE data_source='redesign_catchup'")
            self.assertEqual(cur.fetchone()[0], 0)

    def test_failed_category_exclusion_requires_separate_approval(self):
        manifest = self.manifest()
        manifest.update(complete=False, categories_total=2,
                        coverage=[dict(path="yogurt", status="complete"),
                                  dict(path="unresolved", status="failed")])
        manifest.pop("checksum")
        manifest["checksum"] = digest(manifest)
        with self.assertRaises(ValueError):
            apply(self.dsn, "fixture", manifest)
        self.assertEqual(apply(self.dsn, "fixture", manifest, accept_exclusions=True), 1)

    def test_tampered_incomplete_expired_or_wrong_database_rejected(self):
        for field, value in (("bounded", True), ("complete", False),
                             ("finished_at", "2026-01-01T00:00:00+00:00")):
            manifest = self.manifest()
            manifest[field] = value
            manifest.pop("checksum")
            manifest["checksum"] = digest(manifest)
            with self.assertRaises(ValueError):
                apply(self.dsn, "fixture", manifest)
        with self.assertRaises(ValueError):
            apply(self.dsn, "other", self.manifest())
        tampered = self.manifest()
        tampered["products"][0]["observed"]["price"] = 999
        with self.assertRaises(ValueError):
            apply(self.dsn, "fixture", tampered)

    def worker(self):
        worker = BarboraWorker.__new__(BarboraWorker)
        worker._get_connection = lambda: psycopg2.connect(self.dsn)
        worker.nutriscore_calculator = Mock()
        worker.nutriscore_calculator.is_beverage_category.return_value = False
        worker.nutriscore_calculator.calculate_single_product.return_value = dict(success=True, score=1, grade="B")
        worker.fiber_estimator = None
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS created_at timestamptz")
            cur.execute("ALTER TABLE products ALTER COLUMN product_id SET DEFAULT 99999")
        return worker

    def test_worker_preserves_manual_names_and_nutrition(self):
        worker = self.worker()
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("UPDATE products SET name_manual_edit=TRUE WHERE product_id=1")
            cur.execute("UPDATE nutritionfacts SET nutrition_manual_edit=TRUE WHERE product_id=1")
        details = BarboraParser().parse_product_details(html(product=PRODUCT))
        with patch("barbora_worker.persist_brand_producer_links"), patch("barbora_worker._insert_missing_photos"):
            worker.save_product(details, 1, fixtures.URL)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT name,ingredients,nutrition_source FROM products WHERE product_id=1")
            row = cur.fetchone()
            self.assertEqual(row[0], "Jogurts GRIEĶU bez piedevām 400g")
            self.assertEqual(row[1], "piens, cukurs")
            self.assertEqual(row[2], "usda_api")
            cur.execute("SELECT energy_kj FROM nutritionfacts WHERE product_id=1")
            self.assertEqual(cur.fetchone()[0], 240)

    def test_worker_complete_source_keeps_existing_fiber(self):
        worker = self.worker()
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("UPDATE nutritionfacts SET fiber=2.4 WHERE product_id=1")
        details = BarboraParser().parse_product_details(html(product=PRODUCT))
        with patch("barbora_worker.persist_brand_producer_links"), patch("barbora_worker._insert_missing_photos"):
            worker.save_product(details, 1, fixtures.URL)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT energy_kj,fiber FROM nutritionfacts WHERE product_id=1")
            row = cur.fetchone()
            self.assertEqual(row[0], 310)
            self.assertEqual(float(row[1]), 2.4)
            cur.execute("SELECT needs_enrichment,nutrition_source FROM products WHERE product_id=1")
            self.assertEqual(cur.fetchone(), (False, "barbora"))

    def test_worker_partial_source_keeps_enrichment(self):
        worker = self.worker()
        details = BarboraParser().parse_product_details(html(product=dict(
            PRODUCT, nutrients={"kj": dict(value=310)})))
        with patch("barbora_worker.persist_brand_producer_links"), patch("barbora_worker._insert_missing_photos"):
            worker.save_product(details, 1, fixtures.URL)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT energy_kj FROM nutritionfacts WHERE product_id=1")
            self.assertEqual(cur.fetchone()[0], 240)

    def test_daily_price_discounts_hidden_and_idempotence(self):
        updater = BarboraLightweightUpdater()
        product = BarboraParser()._parse_product_from_json(normalized_product(PRODUCT, {}))
        with psycopg2.connect(self.dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE products SET is_hidden=TRUE WHERE product_id=1")
        with psycopg2.connect(self.dsn, cursor_factory=RealDictCursor) as conn:
            updater.update_product_price(conn, product)
            updater.update_product_price(conn, product)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("""SELECT price,discount_price,price_per_unit,discount_price_per_unit,is_available
                           FROM product_price_history WHERE data_source='lightweight_update'""")
            rows = cur.fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual([float(v) for v in rows[0][:4]], [1.39, .99, 6.95, 4.95])
            self.assertFalse(rows[0][4])

    def test_daily_category_rollback_on_failed_product(self):
        updater = BarboraLightweightUpdater()
        updater._get_connection = lambda: psycopg2.connect(self.dsn, cursor_factory=RealDictCursor)
        first = BarboraParser()._parse_product_from_json(normalized_product(PRODUCT, {}))
        second = copy.copy(first)
        second.sku = "000000000000000009"
        skus = {first.sku, second.sku}
        with patch.object(updater, "get_category_path_for_url", return_value="yogurt"), \
                patch.object(updater.parser, "extract_products_from_category", return_value=[first, second]):
            with self.assertRaises(ValueError):
                updater.process_category(dict(category_id=1, name_lv="Yogurt",
                                              barbora_category_code="old"), skus)
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM product_price_history WHERE data_source='lightweight_update'")
            self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
