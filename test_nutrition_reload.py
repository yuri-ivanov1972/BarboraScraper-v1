"""Isolated tests. No external requests or application databases."""

import copy
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock, patch

from nutrition_reload_source import BarboraSource, SourceError, parse_page, trusted_url
from nutrition_reload_plan import propose, assert_allowlist, digest
from nutrition_reload_store import database_target, apply_one, capture
from reload_barbora_nutrition import main, preview, apply, summary


SKU = "000000000001234567"


def page(name="New name", rows=None, sku=SKU, basis="100 g/ml"):
    rows = rows if rows is not None else [
        ("Enerģētiskā vērtība", "100 kJ / 24 kcal"), ("Tauki", "1 g"),
        ("Piesātinātas taukskābes", "0,1 g"), ("Ogļhidrāti", "2 g"),
        ("Cukuri", "1 g"), ("Olbaltumvielas", "0 g"), ("Sāls", "0 g"),
        ("Šķiedrvielas", "0 g"),
    ]
    return (f'<h1>{name}</h1><script>window.reportUserActionToGa4(window.ga4EventTypes.viewItem,'
            + '{items: [' + json.dumps({"item_id": sku}) + ']});</script>'
            + f'<h3>Uzturvērtība ({basis})</h3><table>'
            + "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in rows) + "</table>")


def baseline():
    return {"product": {
        "product_id": 7, "sku": SKU, "name": "Old name", "name_norm": "old name",
        "category_id": 1, "ingredients": "saldinātājs",
        "barbora_url": "https://barbora.lv/produkti/test", "needs_enrichment": True,
        "enrichment_reviewed": False, "enrichment_skipped": True, "updated_at": "original",
        "name_manual_edit": False, "nutrition_source": "usda_api",
    }, "nutrition": {"product_id": 7, "nutrition_manual_edit": False,
                     "fiber": 4, "usda_fdc_id": 123, "nutri_score_grade": "C",
                     "nutri_score_points": 5, "data_source_date": "original"},
       "category_path": "bakaleja/teja"}


class ReloadTests(unittest.TestCase):
    def calculator(self):
        calc = Mock()
        calc.calculate_single_product.return_value = {"success": True, "grade": "B", "score": 2}
        return calc

    def test_production_guards(self):
        env = {"DATABASE_URL": "postgresql://u:p@dev/db",
               "PROD_DATABASE_URL": "postgresql://u:p@prod/db"}
        with self.assertRaises(ValueError):
            database_target(True, False, env)
        with self.assertRaises(ValueError):
            database_target(False, True, env)
        selected, _ = database_target(True, True, env)
        self.assertEqual(selected, env["PROD_DATABASE_URL"])
        with self.assertRaises(ValueError):
            database_target(True, True, {"DATABASE_URL": selected, "PROD_DATABASE_URL": selected})
        with self.assertRaises(ValueError):
            database_target(True, True, {"DATABASE_URL": env["DATABASE_URL"]})

    def test_untrusted_hosts_and_credentials(self):
        for url in ["http://barbora.lv/a", "https://evil.com/a", "https://barbora.lv.evil.com",
                    "https://u:p@barbora.lv/a", "https://barbora.lv:444/a"]:
            with self.assertRaises(SourceError):
                trusted_url(url)

    def test_manual_protections_independent(self):
        row = baseline()
        row["product"]["name_manual_edit"] = True
        result = propose(row, parse_page(page()), self.calculator())
        self.assertNotIn("name", result["product_changes"])
        self.assertEqual(result["nutrition_status"], "complete")
        row = baseline()
        row["nutrition"]["nutrition_manual_edit"] = True
        result = propose(row, parse_page(page()), self.calculator())
        self.assertEqual(result["product_changes"]["name"], "New name")
        self.assertFalse(result["nutrition_changes"])

    def test_same_sku_renames_and_mismatch(self):
        result = propose(baseline(), parse_page(page()), self.calculator())
        self.assertEqual(result["product_changes"]["name"], "New name")
        with self.assertRaises(ValueError):
            propose(baseline(), parse_page(page(sku="different")), self.calculator())

    def test_zero_and_unit_conversion(self):
        zero = [("Enerģētiskā vērtība", "0 kcal")] + [
            (label, "0 g") for label in ["Tauki", "Piesātinātas taukskābes", "Ogļhidrāti",
                                      "Cukuri", "Olbaltumvielas", "Sāls", "Šķiedrvielas"]]
        result = propose(baseline(), parse_page(page(rows=zero)), self.calculator())
        self.assertEqual(result["nutrition_status"], "complete")
        self.assertEqual(result["nutrition_changes"]["energy_kj"], 0)
        self.assertFalse(result["product_changes"]["needs_enrichment"])
        zero[0] = ("Enerģētiskā vērtība", "25 kcal")
        result = propose(baseline(), parse_page(page(rows=zero)), self.calculator())
        self.assertEqual(result["nutrition_changes"]["energy_kj"], 105)

    def test_absent_partial_invalid_nutrition(self):
        calc = self.calculator()
        for rows, basis in [
            ([], "100 g"), ([("Enerģētiskā vērtība", "1 kJ")], "100 g"),
            ([("Enerģētiskā vērtība", "-5 kJ")], "100 g"),
            ([("Tauki", "<0.1 g")], "100 g"), ([("Tauki", "1 mg")], "100 g"),
            ([("Tauki", "NaN g")], "100 g"), ([("Tauki", "Infinity g")], "100 g"),
            ([("Tauki", "5 g")], "1 serving"),
        ]:
            result = propose(baseline(), parse_page(page(rows=rows, basis=basis)), calc)
            self.assertNotIn("needs_enrichment", result["product_changes"])
            self.assertNotEqual(result["nutrition_status"], "complete")
            self.assertNotIn("energy_kj", result["nutrition_changes"])
        calc.calculate_single_product.assert_not_called()

    def test_unknown_fiber_is_not_zero_or_old_estimate(self):
        candidate = parse_page(page())
        del candidate["nutrition"]["fiber"]
        calc = self.calculator()
        result = propose(baseline(), candidate, calc)
        self.assertIsNone(result["nutrition_changes"]["fiber"])
        self.assertFalse(result["nutrition_changes"]["is_fiber_correct"])
        self.assertIsNone(result["nutrition_changes"]["usda_fdc_id"])
        self.assertIsNone(result["nutrition_changes"]["nutri_score_grade"])
        calc.calculate_single_product.assert_not_called()

    def test_score_uses_stored_category_ingredients_and_new_name(self):
        calc = self.calculator()
        propose(baseline(), parse_page(page()), calc)
        args = calc.calculate_single_product.call_args.kwargs
        self.assertEqual(args["category_id"], 1)
        self.assertEqual(args["ingredients_text"], "saldinātājs")
        self.assertEqual(args["product_name"], "New name")

    def test_score_failure_clears_obsolete_grade(self):
        calc = self.calculator()
        calc.calculate_single_product.return_value = {"success": False}
        result = propose(baseline(), parse_page(page()), calc)
        self.assertIsNone(result["nutrition_changes"]["nutri_score_grade"])
        self.assertIn("score_calculation_failed", result["notes"])

    def test_allowlist(self):
        result = propose(baseline(), parse_page(page()), self.calculator())
        assert_allowlist(result)
        result["product_changes"]["ingredients"] = "bad"
        with self.assertRaises(ValueError):
            assert_allowlist(result)

    def test_fallback_requires_exact_sku_and_unique_url(self):
        source = BarboraSource()
        source.fetch = Mock(side_effect=[SourceError("page_not_found"),
                                        (page(), "https://barbora.lv/produkti/new")])
        source.category_urls = Mock(return_value={SKU: {"https://barbora.lv/produkti/new"}})
        result = source.product(baseline())
        self.assertTrue(result["recovered_url"])
        source.fetch = Mock(side_effect=SourceError("page_not_found"))
        source.category_urls.return_value = {SKU: {"https://barbora.lv/produkti/a",
                                                  "https://barbora.lv/produkti/b"}}
        with self.assertRaisesRegex(SourceError, "ambiguous_listing_match"):
            source.product(baseline())

    def test_missing_url_uses_same_sku_listing(self):
        source = BarboraSource()
        source.category_urls = Mock(return_value={SKU: {"https://barbora.lv/produkti/new"}})
        source.fetch = Mock(return_value=(page(), "https://barbora.lv/produkti/new"))
        row = baseline()
        row["product"]["barbora_url"] = None
        self.assertTrue(source.product(row)["recovered_url"])

    def test_untrusted_redirect_not_fetched(self):
        source = BarboraSource(delay=0.25)
        session = Mock()
        response = Mock(status_code=302, headers={"Location": "https://evil.com/steal"})
        session.get.return_value = response
        source.local.session = session
        with self.assertRaises(SourceError):
            source.fetch("https://barbora.lv/produkti/test")
        self.assertEqual(session.get.call_count, 1)

    def test_bounded_retry(self):
        import requests
        source = BarboraSource(delay=0.25, retries=1)
        source.local.session = Mock()
        source.local.session.get.side_effect = requests.Timeout()
        with patch("nutrition_reload_source.time.sleep"):
            with self.assertRaisesRegex(SourceError, "request_failed"):
                source.fetch("https://barbora.lv/produkti/test")
        self.assertEqual(source.local.session.get.call_count, 2)

    def test_concurrent_edit_skips_and_no_updates(self):
        row = baseline()
        row["proposal"] = propose(row, parse_page(page()), self.calculator())
        changed = dict(row["product"], name="Human correction", name_manual_edit=True)
        cur = Mock()
        cur.fetchone.side_effect = [{"value": changed}, {"value": row["nutrition"]}]
        conn = Mock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        self.assertEqual(apply_one(conn, row), "baseline_changed")
        conn.commit.assert_not_called()
        conn.rollback.assert_called()
        self.assertFalse(any(str(call.args[0]).lstrip().startswith("UPDATE")
                             for call in cur.execute.call_args_list))

    def test_failed_commit_does_not_report_updated(self):
        row = baseline()
        row["proposal"] = propose(row, parse_page(page()), self.calculator())
        cur = Mock(rowcount=1)
        cur.fetchone.side_effect = [{"value": row["product"]}, {"value": row["nutrition"]}]
        conn = Mock()
        conn.cursor.return_value.__enter__ = Mock(return_value=cur)
        conn.cursor.return_value.__exit__ = Mock(return_value=False)
        conn.commit.side_effect = RuntimeError("private diagnostics")
        self.assertEqual(apply_one(conn, row), "apply_failed")
        conn.rollback.assert_called()

    def test_digest_detects_manifest_modification(self):
        original = baseline()
        changed = copy.deepcopy(original)
        changed["product"]["name"] = "altered"
        self.assertNotEqual(digest(original), digest(changed))

    def test_unapproved_apply_blocked_before_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            manifest = {"version": 1, "target": "production", "target_hash": "hash",
                        "preview_complete": True, "rows": []}
            path.write_text(json.dumps(manifest))
            args = Namespace(manifest=str(path), production=True, approved_sha256=None)
            with patch("reload_barbora_nutrition.connect") as connect:
                with self.assertRaisesRegex(ValueError, "approval SHA-256"):
                    apply(args, "dsn", "hash")
                connect.assert_not_called()
                args.approved_sha256 = digest(manifest)
                manifest["rows"] = [{"altered": True}]
                path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, "approval SHA-256"):
                    apply(args, "dsn", "hash")
                connect.assert_not_called()

    def test_preview_is_readonly_and_resume_retains_frozen_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            row = dict(baseline(), candidate=None, proposal=None, outcome=None)
            frozen = {"version": 1, "target": "production", "target_hash": "hash",
                      "preview_complete": False, "rows": [row]}
            args = Namespace(manifest=str(path), production=True, limit=None,
                             delay=0.5, retries=1, timeout=10, workers=1,
                             max_category_pages=2, retry_source_errors=False)
            conn = Mock()
            source = Mock()
            source.product.return_value = parse_page(page())
            with patch("reload_barbora_nutrition.connect", return_value=conn) as connect, \
                 patch("reload_barbora_nutrition.verify_schema"), \
                 patch("reload_barbora_nutrition.capture", return_value=frozen) as capture, \
                 patch("reload_barbora_nutrition.NutriscoreCalculator", return_value=self.calculator()), \
                 patch("reload_barbora_nutrition.BarboraSource", return_value=source):
                result = preview(args, "dsn", "hash")
                self.assertTrue(result["preview_complete"])
                connect.assert_called_with("dsn", readonly=True)
                conn.commit.assert_not_called()
                conn.rollback.assert_called()
                self.assertEqual(source.product.call_count, 1)
                self.assertEqual(capture.call_count, 1)
                second = preview(args, "dsn", "hash")
                self.assertEqual(second["approval_sha256"], result["approval_sha256"])
                self.assertEqual(source.product.call_count, 1)
                self.assertEqual(capture.call_count, 1)

    def test_retry_only_failed_members_of_original_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "manifest.json"
            row = dict(baseline(), candidate=None, proposal=None,
                       outcome="source_failed", error="request_failed")
            frozen = {"version": 1, "target": "production", "target_hash": "hash",
                      "preview_complete": True, "rows": [row]}
            path.write_text(json.dumps(frozen))
            args = Namespace(manifest=str(path), production=True, limit=None,
                             delay=0.5, retries=1, timeout=10, workers=1,
                             max_category_pages=2, retry_source_errors=True)
            source = Mock()
            source.product.return_value = parse_page(page())
            with patch("reload_barbora_nutrition.connect", return_value=Mock()), \
                 patch("reload_barbora_nutrition.verify_schema"), \
                 patch("reload_barbora_nutrition.capture") as capture, \
                 patch("reload_barbora_nutrition.NutriscoreCalculator", return_value=self.calculator()), \
                 patch("reload_barbora_nutrition.BarboraSource", return_value=source):
                result = preview(args, "dsn", "hash")
                self.assertEqual(result["selected"], 1)
                self.assertEqual(source.product.call_count, 1)
                capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
