"""Canonical category, empty-response and scoped-preview regression coverage."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from barbora_site_data import (RECOVERY_CATEGORY_PATHS, SiteDataError, category_page,
                               canonical_category_path)
from barbora_parser import BarboraParser
from nutrition_reload_source import BarboraSource
from barbora_lightweight_updater import BarboraLightweightUpdater
from barbora_catchup import FIELDS, apply, digest, preview, retry_failed, unobserved_products
import test_barbora_redesign as baseline

PRODUCT, SKU, html = baseline.PRODUCT, baseline.SKU, baseline.html


BISCUITS, POPCORN, PASTRIES = RECOVERY_CATEGORY_PATHS


def page(path, items, count=None, metadata=True, short=None, tree_path=None,
         query_short=None, query_offset=0):
    short = short or RECOVERY_CATEGORY_PATHS[path]
    canonical = f"c/{short}/{path}"
    data = dict(count=len(items) if count is None else count, offset=0, limit=60,
                inventories=items,
                categoryMetadata=dict(url=canonical if metadata else None))
    queries = [
        dict(queryKey=[dict(_id="categoriesGet")], state=dict(data=dict(categories=[
            dict(shortId=short, categoryId="current-uuid",
                 fullUrl=canonical if tree_path is None else tree_path)]))),
        dict(queryKey=[dict(_id="inventoryCategoryInventory",
                            path=dict(shortId=query_short or short),
                            query=dict(Offset=query_offset, Limit=60))],
             state=dict(data=data))]
    return "<script>window.__remixContext = " + json.dumps(dict(
        state=dict(loaderData={"route": dict(dehydratedState=dict(queries=queries))}))) + ";</script>"


class CategoryRecoveryTests(unittest.TestCase):
    def test_known_canonical_routes_only(self):
        parser = BarboraParser()
        for path, short in RECOVERY_CATEGORY_PATHS.items():
            url = f"https://barbora.lv/c/{short}/{path}"
            self.assertEqual(parser.build_category_url(path), url)
            self.assertEqual(parser.build_category_url(path, 2), url + "?page=2")
            self.assertEqual(parser.build_category_url(f"c/{short}/{path}"), url)
        self.assertEqual(canonical_category_path("other/category"), "other/category")

    def test_empty_listing_requires_tree_and_query_agreement(self):
        result = category_page(page(BISCUITS, [], metadata=False), expected_path=BISCUITS)
        self.assertEqual(result["products"], [])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["short_id"], "L0BE")
        self.assertEqual(result["identity_evidence"], "inventory_query_and_current_tree")

    def test_empty_identity_conflicts_are_rejected(self):
        for value in (
            page(BISCUITS, [], metadata=False, query_short="OTHER"),
            page(BISCUITS, [], metadata=False, tree_path=""),
            page(BISCUITS, [], metadata=False, query_offset=60),
            page(BISCUITS, [], metadata=False, tree_path="c/L0BE/wrong/category"),
        ):
            with self.assertRaises(SiteDataError):
                category_page(value, expected_path=BISCUITS)

    def test_nonempty_cannot_borrow_blank_metadata(self):
        with self.assertRaises(SiteDataError):
            category_page(page(BISCUITS, [PRODUCT], metadata=False), expected_path=BISCUITS)

    def test_metadata_cannot_disagree_with_query_or_tree(self):
        for value in (
            page(POPCORN, [PRODUCT], query_short="OTHER"),
            page(POPCORN, [PRODUCT], tree_path="c/ATB9/wrong/category"),
        ):
            with self.assertRaises(SiteDataError):
                category_page(value, expected_path=POPCORN)

    def test_unknown_or_missing_inventory_is_not_empty(self):
        with self.assertRaises(SiteDataError):
            category_page(html(product=PRODUCT), expected_path=BISCUITS)
        with self.assertRaises(SiteDataError):
            category_page("<html>Access denied</html>", expected_path=BISCUITS)

    def test_pastry_count_stays_incomplete_with_safe_diagnostics(self):
        items = [dict(PRODUCT, id=f"{i:018d}") for i in range(49)]
        with self.assertRaisesRegex(SiteDataError, "incomplete_category_page") as caught:
            category_page(page(PASTRIES, items, count=50), expected_path=PASTRIES)
        self.assertEqual(caught.exception.details["advertised_count"], 50)
        self.assertEqual(caught.exception.details["returned_count"], 49)

    def test_normal_daily_parser_uses_canonical_popcorn_url(self):
        parser = BarboraParser()
        response = SimpleNamespace(text=page(POPCORN, [PRODUCT]), raise_for_status=lambda: None)
        with patch.object(parser.session, "get", return_value=response) as fetch:
            products = parser.extract_products_from_category(POPCORN)
        self.assertEqual([p.sku for p in products], [SKU])
        self.assertEqual(fetch.call_args.args[0], f"https://barbora.lv/c/ATB9/{POPCORN}")

    def test_daily_empty_does_not_write_or_mark_absent_products_unavailable(self):
        updater = BarboraLightweightUpdater()
        response = SimpleNamespace(text=page(BISCUITS, [], metadata=False),
                                   raise_for_status=lambda: None)
        with patch.object(updater, "get_category_path_for_url", return_value=BISCUITS), \
                patch.object(updater.parser.session, "get", return_value=response), \
                patch.object(updater, "_get_connection") as connect:
            result = updater.process_category(dict(category_id=1, name_lv="Biscuits",
                                                   barbora_category_code="old"), {SKU})
        self.assertEqual(result["products_found"], 0)
        connect.assert_not_called()

    def test_nutrition_url_recovery_uses_same_verified_empty_policy(self):
        source = BarboraSource(delay=0)
        with patch.object(source, "fetch", return_value=(
                page(BISCUITS, [], metadata=False), f"https://barbora.lv/c/L0BE/{BISCUITS}")) as fetch:
            self.assertEqual(source.category_urls(BISCUITS), {})
            self.assertEqual(source.category_urls(BISCUITS), {})
        self.assertEqual(fetch.call_count, 1)
        self.assertIn("/c/L0BE/", fetch.call_args.args[0])

    def test_scoped_preview_excludes_failed_category_and_new_products(self):
        cats = [dict(category_id=str(i), name_lv=path, path=path, barbora_category_code="old")
                for i, path in enumerate(RECOVERY_CATEGORY_PATHS, 1)]
        product = dict(sku=SKU, product_id="10", name="Existing", is_hidden=False,
                       category_id="2", price_history_id="1", **{k: None for k in FIELDS})
        source = BarboraSource(delay=0)
        new = dict(PRODUCT, id="000000000000000099")
        source.fetch = Mock(side_effect=[
            (page(BISCUITS, [], metadata=False), "https://barbora.lv/"),
            (page(POPCORN, [PRODUCT, new]), "https://barbora.lv/"),
            (page(PASTRIES, [PRODUCT], count=2), "https://barbora.lv/")])
        with patch("barbora_catchup.snapshot", return_value=(cats, {SKU: product})):
            result = preview("unused", "target", source=source,
                             category_paths=set(RECOVERY_CATEGORY_PATHS))
        self.assertFalse(result["complete"])
        self.assertFalse(result["bounded"])
        self.assertEqual(result["categories_total"], 3)
        self.assertEqual(result["selection"]["paths"], sorted(RECOVERY_CATEGORY_PATHS))
        self.assertEqual(result["summary"]["existing_observed"], 1)
        self.assertEqual(result["summary"]["new_excluded"], 1)
        self.assertEqual(result["summary"]["failed_categories"], 1)
        self.assertEqual(result["products"][0]["category_path"], POPCORN)
        self.assertEqual(result["coverage"][2]["returned_count"], 1)

    def test_scoped_preview_requires_every_requested_database_category(self):
        with patch("barbora_catchup.snapshot", return_value=([], {})):
            with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
                preview("unused", "target", category_paths=set(RECOVERY_CATEGORY_PATHS))

    def test_unobserved_report_distinguishes_empty_failed_complete_and_outside(self):
        coverage = [
            dict(category_id="1", path=BISCUITS, status="complete", products=0),
            dict(category_id="2", path=POPCORN, status="complete", products=58),
            dict(category_id="3", path=PASTRIES, status="failed", products=0),
        ]
        products = {str(i): dict(name=f"Stored {i}", category_id=str(i)) for i in range(1, 5)}
        reasons = {p["category_id"]: p["reason"]
                   for p in unobserved_products(products, {}, coverage)}
        self.assertEqual(reasons, {
            "1": "verified_empty_listing_no_absence_inference",
            "2": "not_observed_in_complete_listing_no_absence_inference",
            "3": "category_listing_incomplete",
            "4": "category_outside_preview_scope",
        })
        scoped = unobserved_products(products, {}, coverage, {"1", "2", "3"})
        self.assertEqual(len(scoped), 3)
        self.assertFalse(any(p["category_id"] == "4" for p in scoped))
        self.assertEqual(len(unobserved_products(products, {"2": {}}, coverage)), 3)

    def test_unobserved_retry_uses_merged_coverage(self):
        products = {"old": dict(name="Old", category_id="2")}
        failed = [dict(category_id="2", path=POPCORN, status="failed", products=0)]
        initial = unobserved_products(products, {}, failed)
        complete = [dict(category_id="2", path=POPCORN, status="complete", products=58)]
        refreshed = unobserved_products({p["sku"]: p for p in initial}, {}, complete)
        self.assertEqual(refreshed[0]["reason"],
                         "not_observed_in_complete_listing_no_absence_inference")


class ScopedApplyTests(unittest.TestCase):
    setUpClass = classmethod(baseline.RecoveryDatabaseTests.setUpClass.__func__)
    tearDownClass = classmethod(baseline.RecoveryDatabaseTests.tearDownClass.__func__)
    setUp = baseline.RecoveryDatabaseTests.setUp
    manifest = baseline.RecoveryDatabaseTests.manifest

    def scoped(self):
        result = self.manifest()
        result.update(complete=False, categories_total=3,
                      selection=dict(type="confirmed_category_paths",
                                     paths=sorted(RECOVERY_CATEGORY_PATHS)),
                      coverage=[dict(path=p, status="complete" if p != PASTRIES else "failed")
                                for p in RECOVERY_CATEGORY_PATHS])
        result["products"][0]["category_path"] = POPCORN
        result.pop("checksum")
        result["checksum"] = digest(result)
        return result

    def test_explicit_scoped_apply_needs_exclusion_approval(self):
        result = self.scoped()
        with self.assertRaises(ValueError):
            apply(self.dsn, "fixture", result)
        self.assertEqual(apply(self.dsn, "fixture", result, accept_exclusions=True), 1)
        self.assertEqual(apply(self.dsn, "fixture", result, accept_exclusions=True), 0)

    def test_scoped_apply_rejects_records_from_incomplete_or_unselected_category(self):
        for path in (PASTRIES, "some/other/category"):
            result = self.scoped()
            result["products"][0]["category_path"] = path
            result.pop("checksum")
            result["checksum"] = digest(result)
            with self.assertRaisesRegex(ValueError, "outside"):
                apply(self.dsn, "fixture", result, accept_exclusions=True)

    def test_scoped_apply_requires_exact_coverage(self):
        result = self.scoped()
        result["coverage"].pop()
        result.pop("checksum")
        result["checksum"] = digest(result)
        with self.assertRaisesRegex(ValueError, "scope"):
            apply(self.dsn, "fixture", result, accept_exclusions=True)

    def test_scoped_preview_is_not_merged_as_full_retry(self):
        with self.assertRaisesRegex(ValueError, "fresh scoped"):
            retry_failed(self.dsn, "fixture", self.scoped())


if __name__ == "__main__":
    unittest.main()
