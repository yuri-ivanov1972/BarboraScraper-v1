"""Offline image-policy, caller and isolated PostgreSQL regression tests."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup

import test_photo_maintenance as database_fixture
import test_barbora_redesign as site_fixture
from barbora_parser import BarboraParser
from barbora_site_data import normalized_product
from fix_broken_photos import _check_url, _insert_missing_photos, _scrape_photos
from photo_format_preview import preview, write_reports
from photo_maintenance import check_image
from photo_sources import asset_key, image_url, is_avif, product_photos, select_urls
from product_refresh_source import ProductRefreshSource, parse_full_page, photo_url
from robust_web_client import RobustWebClient

BASE = "https://cdn.barbora.lv/products/01b7e377-82ab-49f4-b7e7-df33ab931766"
PNG, AVIF = BASE + "_xxl.png", BASE + "_xl.avif"
SECOND = "https://cdn.barbora.lv/products/another-view.png"
PICTURE = Path("fixtures/barbora_product_picture.html").read_text()


class SelectionTests(unittest.TestCase):
    def test_zero_match_report_still_has_csv_headers(self):
        with TemporaryDirectory() as directory:
            write_reports({"products": [], "read_only": True}, directory)
            self.assertTrue((Path(directory) / "links.csv").read_text(encoding="utf-8-sig").startswith("product_id,sku,name"))

    def test_preview_source_accepts_bounded_network_settings(self):
        source = ProductRefreshSource(delay=.5, retries=0, timeout=8, max_pages=1)
        self.assertEqual(source.timeout, 8)
        self.assertEqual(source.retries, 0)

    def test_supplied_picture_prefers_largest_advertised_png(self):
        self.assertEqual(product_photos(html=PICTURE), [PNG])
        self.assertEqual(asset_key(PNG), asset_key(AVIF))

    def test_structured_avif_does_not_hide_png_and_views_survive(self):
        value = dict(imagesOriginal=[AVIF, SECOND], images=[BASE + "_l.png"])
        self.assertEqual(product_photos(value, PICTURE), [PNG, SECOND])
        self.assertEqual(product_photos(value), [BASE + "_l.png", SECOND])

    def test_original_is_preferred_over_known_size_suffix(self):
        self.assertEqual(select_urls([BASE + "_l.png", BASE + ".png", PNG]), [BASE + ".png"])

    def test_responsive_descriptors_and_dict_variants(self):
        self.assertEqual(select_urls([{"srcSet": BASE + "_s.png 400w, " + PNG + " 1200w"}]), [PNG])
        self.assertEqual(select_urls([{"variants": [{"url": PNG, "width": 1200}, {"url": AVIF}]}]), [PNG])

    def test_format_preference_does_not_merge_distinct_views(self):
        self.assertEqual(select_urls([BASE + "_l.jpg", SECOND, PNG, BASE + "_l.png"]), [PNG, SECOND])
        self.assertEqual(select_urls([BASE + "_1.png", BASE + "_2.png"]), [BASE + "_1.png", BASE + "_2.png"])

    def test_unsupported_only_never_fabricates_png(self):
        self.assertEqual(product_photos(dict(imagesOriginal=[AVIF])), [])
        self.assertEqual(product_photos(html=f"<picture><source type='image/avif' srcset='{AVIF}'></picture>"), [])

    def test_unrelated_pictures_and_icons_excluded(self):
        unrelated = f"<a href='/p/other'><picture><img src='{SECOND}'></picture></a>"
        icons = "<picture><img src='https://cdn.barbora.lv/icons/logo.png'></picture>"
        self.assertEqual(product_photos(html=unrelated + icons + PICTURE), [PNG])
        self.assertEqual(product_photos(dict(imagesOriginal=[AVIF]),
                                       "<main><picture><img src='" + SECOND + "'></picture></main>"), [])

    def test_invalid_hosts_placeholders_and_malformed_inputs(self):
        for value in ("https://evil.test/products/x.png", "https://cdn.barbora.lv.evil.test/products/x.png",
                      "https://user@cdn.barbora.lv/products/x.png", "http://cdn.barbora.lv/products/x.png",
                      "https://cdn.barbora.lv/products/no-image.png", "https://[broken"):
            self.assertIsNone(image_url(value))
            self.assertEqual(product_photos({"imagesOriginal": [value]}), [])

    def test_query_format_and_uppercase_avif_rejected(self):
        for url in (AVIF.upper(), BASE + ".png?format=avif", BASE + ".png?fm=avif"):
            self.assertTrue(is_avif(url))
            self.assertFalse(photo_url(url))
            self.assertIsNone(image_url(url))
        self.assertEqual(image_url(PNG + "?v=2#fragment"), PNG + "?v=2")

    def test_legacy_cloudinary_commas_preserved(self):
        url = "https://res.cloudinary.com/rimibaltic/image/upload/f_auto,w_480/photo.jpg"
        self.assertEqual(select_urls([url], retailer_only=False), [url])

    def test_modern_adapter_and_listing_parser(self):
        raw = dict(site_fixture.PRODUCT, imagesOriginal=[AVIF], images=[PNG])
        record = normalized_product(raw, {})
        self.assertEqual(record["big_image"], PNG)
        self.assertEqual(BarboraParser()._parse_product_from_json(record).big_image_url, PNG)

    def test_listing_card_picture_is_joined_by_asset_not_global_order(self):
        raw = dict(site_fixture.PRODUCT, imagesOriginal=[AVIF])
        html = (f"<a href='/p/unrelated'><div class='product-image'><picture><img src='{SECOND}'></picture></div></a>"
                f"<a href='/p/correct'><div class='product-image'>{PICTURE}</div></a>")
        self.assertEqual(normalized_product(raw, {}, html)["big_image"], PNG)

    def test_price_listing_survives_unsupported_images(self):
        callback = Mock()
        raw = dict(site_fixture.PRODUCT, imagesOriginal=[AVIF])
        record = normalized_product(raw, {})
        parsed = BarboraParser(callback)._parse_product_from_json(record)
        self.assertEqual(parsed.price, raw["price"])
        self.assertIsNone(parsed.big_image_url)
        self.assertTrue(any("unsupported_format_only" in c.args[0] for c in callback.call_args_list))

    def test_modern_details_and_full_refresh_use_png_gallery(self):
        raw = dict(site_fixture.PRODUCT, imagesOriginal=[AVIF], images=[BASE + "_l.png"])
        html = site_fixture.html(product=raw) + PICTURE
        self.assertEqual(BarboraParser().parse_product_details(html).photo_urls, [PNG])
        full = parse_full_page(html, "https://barbora.lv/p/" + raw["url"], raw["id"])
        self.assertEqual(full["photo_urls"], [PNG])

    def test_legacy_gallery_and_robust_extractor_use_shared_rule(self):
        html = f"<div class='b-block-slider--slide'><picture><source srcset='{AVIF}'><img src='{PNG}'></picture></div>"
        parser = BarboraParser()
        self.assertEqual(parser.parse_product_details(html).photo_urls, [PNG])
        client = RobustWebClient(lambda msg: None)
        self.assertEqual(client._extract_photos(BeautifulSoup(PICTURE, "html.parser")), [PNG])
        self.assertFalse(client._is_valid_product_image(AVIF))
        client.close()

    def test_plain_product_image_fallback_is_preserved(self):
        self.assertEqual(product_photos(html=f"<img class='product-image' src='{PNG}'>"), [PNG])
        self.assertEqual(product_photos(html=f"<img itemprop='image' src='{PNG}'>"), [PNG])

    def test_unrelated_selector_root_cannot_disable_picture_fallback(self):
        unrelated = f"<div class='product-image'><img src='{SECOND}'></div>"
        self.assertEqual(product_photos({"imagesOriginal": [AVIF]}, unrelated + PICTURE), [PNG])
        self.assertEqual(product_photos(html=unrelated + PICTURE), [PNG])
        self.assertEqual(product_photos(html="<a href='/p/other'>" + unrelated + "</a>" + PICTURE), [PNG])
        self.assertEqual(product_photos(html="<aside>" + unrelated + "</aside>" + PICTURE), [PNG])
        small = f"<img class='product-image' src='{BASE}_l.png'>"
        self.assertEqual(product_photos({"imagesOriginal": [AVIF]}, small + PICTURE), [PNG])

    def test_standalone_scraper_uses_shared_rule_and_exact_sku(self):
        raw = dict(site_fixture.PRODUCT, imagesOriginal=[AVIF])
        html = site_fixture.html(product=raw) + PICTURE
        with patch("nutrition_reload_source.BarboraSource.fetch",
                   return_value=(html, "https://barbora.lv/p/" + raw["url"])):
            self.assertEqual(_scrape_photos("https://barbora.lv/p/test", Mock(), raw["id"]), [PNG])
            self.assertEqual(_scrape_photos("https://barbora.lv/p/test", Mock(), "wrong-sku"), [])

    def test_http_avif_and_content_mismatch_are_not_working(self):
        response = database_fixture.HTTPTests().response
        avif_bytes = b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00mif1avif"
        self.assertEqual(check_image(PNG, response(200, avif_bytes, "image/avif"))[0], "unsupported_format")
        self.assertEqual(check_image(PNG, response(200, avif_bytes, "image/png"))[0], "unsupported_format")
        self.assertEqual(check_image(PNG, response(200, b"\xff\xd8\xffabc", "image/png"))[0], "invalid_content")
        session = Mock()
        self.assertEqual(check_image(AVIF, session)[0], "unsupported_format")
        session.get.assert_not_called()
        self.assertEqual(_check_url((1, 1, AVIF, session)), (1, 1, False))
        self.assertEqual(check_image(PNG, response(403))[0], "access_blocked")


class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database_fixture.DatabaseTests.setUpClass.__func__(cls)
        cls.sql(cls, "ALTER TABLE product_price_history ADD COLUMN price_history_id serial")

    tearDownClass = classmethod(database_fixture.DatabaseTests.tearDownClass.__func__)
    setUp = database_fixture.DatabaseTests.setUp
    sql = database_fixture.DatabaseTests.sql

    def test_empty_gallery_writer_filters_and_preserves_primary_order(self):
        self.sql("DELETE FROM productphotos WHERE product_id=1")
        with self.service.connect() as conn, conn.cursor() as cur:
            self.assertFalse(_insert_missing_photos(cur, 1, [AVIF]))
            self.assertTrue(_insert_missing_photos(cur, 1, [AVIF, PNG, SECOND]))
        conn.close()
        rows = self.sql("SELECT photo_url,is_primary FROM productphotos WHERE product_id=1 ORDER BY photo_id")
        self.assertEqual([(r["photo_url"], r["is_primary"]) for r in rows], [(PNG, True), (SECOND, False)])

    def test_manual_and_unknown_galleries_never_overwritten(self):
        for ownership in ("manual", "unknown"):
            self.sql("UPDATE photo_maintenance SET ownership=%s WHERE product_id=1", (ownership,))
            with self.service.connect() as conn, conn.cursor() as cur:
                self.assertFalse(_insert_missing_photos(cur, 1, [PNG]))
            conn.close()
        self.assertEqual(len(self.sql("SELECT * FROM productphotos WHERE product_id=1")), 2)
        self.service.set_ownership(1, "manual")
        self.sql("DELETE FROM productphotos WHERE product_id=1")
        with self.service.connect() as conn, conn.cursor() as cur:
            self.assertFalse(_insert_missing_photos(cur, 1, [PNG]))
        conn.close()

    def test_candidate_observation_rejects_avif(self):
        before = self.sql("SELECT candidate_url FROM photo_maintenance WHERE product_id=1")
        with self.service.connect() as conn, conn.cursor() as cur:
            self.service.observe(cur, 1, AVIF)
        conn.close()
        self.assertEqual(self.sql("SELECT candidate_url FROM photo_maintenance WHERE product_id=1"), before)

    def test_save_boundary_rejects_even_forged_working_avif(self):
        self.service.set_ownership(1, "retailer")
        self.sql("UPDATE photo_maintenance SET candidate_url=%s WHERE product_id=1", (AVIF,))
        row = next(r for r in self.service.rows() if r["kind"] == "candidate")
        self.service.save_result(row, AVIF, "working", 200)
        self.assertEqual(self.sql("SELECT photo_url FROM productphotos WHERE product_id=1 AND is_primary")[0]["photo_url"], database_fixture.OLD)
        self.assertEqual(self.sql("SELECT status FROM photo_url_verification WHERE url=%s", (AVIF,))[0]["status"], "unsupported_format")

    def test_legacy_database_writers_share_safe_fill_only_policy(self):
        from database_updater import DatabaseUpdater
        from enhanced_database_updater import EnhancedDatabaseUpdater
        for cls in (DatabaseUpdater, EnhancedDatabaseUpdater):
            writer = cls.__new__(cls)
            writer.conn = self.service.connect()
            writer.status_callback = lambda msg: None
            writer._ensure_connection = lambda: None
            try:
                self.assertFalse(writer.add_product_photos(1, [AVIF]))
                self.assertTrue(writer.add_product_photos(1, [PNG]))
            finally:
                writer.conn.close()
        self.assertEqual(self.sql("SELECT photo_url FROM productphotos WHERE product_id=1 AND is_primary")[0]["photo_url"], database_fixture.OLD)

    def test_old_avif_is_reported_despite_cached_working_status(self):
        self.sql("UPDATE productphotos SET photo_url=%s WHERE product_id=1 AND is_primary", (AVIF,))
        self.sql("""INSERT INTO photo_url_verification(url,status,last_attempt,next_due)
                    VALUES(%s,'working',now(),now()+interval '7 days')""", (AVIF,))
        row = next(r for r in self.service.rows() if r["check_url"] == AVIF)
        self.assertEqual(row["status"], "unsupported_format")
        with patch("photo_maintenance.check_image", return_value=("unsupported_format", 200)):
            self.assertTrue(any(r["checked_url"] == AVIF for r in self.service.run()))

    def test_replacement_does_not_duplicate_or_remove_secondary_photo(self):
        self.service.set_ownership(1, "retailer")
        self.sql("UPDATE productphotos SET photo_url=%s WHERE product_id=1 AND NOT is_primary", (database_fixture.NEW,))
        before = self.sql("SELECT * FROM productphotos ORDER BY photo_id")
        row = next(r for r in self.service.rows() if r["kind"] == "candidate")
        outcome = self.service.save_result(row, database_fixture.NEW, "working", 200)
        self.assertIn("Review existing gallery", outcome)
        self.assertEqual(self.sql("SELECT * FROM productphotos ORDER BY photo_id"), before)

    def prepare_preview(self, ownership="retailer"):
        self.sql("UPDATE productphotos SET photo_url=%s WHERE product_id=1 AND is_primary", (AVIF,))
        self.service.set_ownership(1, ownership)
        source = Mock()
        source.product.return_value = {"photo_urls": [PNG]}
        return source

    def test_production_style_preview_is_bounded_and_strictly_readonly(self):
        source = self.prepare_preview()
        before = self.sql("SELECT * FROM productphotos ORDER BY photo_id")
        state = self.sql("SELECT * FROM photo_maintenance ORDER BY product_id")
        with patch("photo_format_preview.check_image", return_value=("working", 200)):
            result = preview(self.service.database_url, "fixture", limit=1, source=source)
        self.assertEqual(result["summary"]["verified_eligible_links"], 2)  # primary and managed reference
        self.assertEqual(result["summary"]["production_writes"], 0)
        self.assertEqual(self.sql("SELECT * FROM productphotos ORDER BY photo_id"), before)
        self.assertEqual(self.sql("SELECT * FROM photo_maintenance ORDER BY product_id"), state)
        self.assertFalse(self.sql("SELECT * FROM photo_url_verification"))
        self.assertIsNone(self.sql("SELECT leased_until FROM photo_maintenance_config")[0]["leased_until"])

    def test_preview_does_not_adopt_unknown_or_manual_ownership(self):
        source = self.prepare_preview("manual")
        result = preview(self.service.database_url, "fixture", limit=1, source=source)
        source.product.assert_not_called()
        self.assertEqual(result["products"][0]["outcome"], "manual_photo_protected")
        self.sql("UPDATE photo_maintenance SET ownership='unknown' WHERE product_id=1")
        with patch("photo_format_preview.check_image", return_value=("working", 200)):
            result = preview(self.service.database_url, "fixture", limit=1, source=source)
        self.assertEqual(result["products"][0]["outcome"], "ownership_review_required")
        self.assertEqual(result["summary"]["verified_eligible_links"], 0)

    def test_preview_blocked_host_stays_unverified(self):
        source = self.prepare_preview()
        with patch("photo_format_preview.check_image", return_value=("access_blocked", 403)) as check:
            result = preview(self.service.database_url, "fixture", limit=1, source=source)
        self.assertEqual(check.call_count, 1)
        self.assertEqual(result["summary"]["verified_eligible_links"], 0)

    def test_preview_uses_real_verifier_with_fake_http_session(self):
        source = self.prepare_preview()
        cases = [(200, b"\x89PNG\r\n\x1a\nabc", "image/png", "working"),
                 (200, b"\x00\x00\x00\x20ftypavif\x00\x00\x00\x00mif1avif", "image/avif", "unsupported_format"),
                 (200, b"<html>blocked</html>", "text/html", "invalid_content"),
                 (403, b"", "text/html", "access_blocked")]
        for code, body, mime, expected in cases:
            with self.subTest(expected=expected):
                session = database_fixture.HTTPTests().response(code, body, mime)
                # Keep preview.check_image and its real HTTP/content logic intact.
                with patch("photo_maintenance.requests.get", new=session.get):
                    result = preview(self.service.database_url, "fixture", limit=1, source=source)
                link = result["products"][0]["links"][0]
                self.assertEqual(link["verification"], expected)
                self.assertEqual(link["eligible"], expected == "working")
                session.get.assert_called_once()
                self.assertEqual(session.get.call_args.kwargs["timeout"], (3, 5))

    def test_preview_never_substitutes_a_different_image(self):
        source = self.prepare_preview()
        source.product.return_value = {"photo_urls": [SECOND]}
        with patch("photo_format_preview.check_image") as check:
            result = preview(self.service.database_url, "fixture", limit=1, source=source)
        check.assert_not_called()
        self.assertEqual(result["summary"]["proposed_same_image_links"], 0)


if __name__ == "__main__":
    unittest.main()
