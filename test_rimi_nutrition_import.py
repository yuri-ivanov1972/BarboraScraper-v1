"""Pure and real isolated PostgreSQL tests; never reads project credentials."""

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import psycopg2

from fiber_estimator import FiberEstimator
from nutrition_reload_store import connect
from nutriscore_calculator import NutriscoreCalculator, calculate_nutriscore_2024
from rimi_nutrition_import_plan import allowlist, eligible, invalid_nutrients, plan, seal, validate_manifest
from rimi_nutrition_import_store import apply_one, category_state, read_rows, restore_one


class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rimi-import-test-")
        root = Path(cls.temp.name)
        cls.root, cls.data = root, root / "pg"
        subprocess.run(["initdb", "-D", str(cls.data), "-U", "fixture", "-A", "trust",
                        "--no-locale", "-E", "UTF8"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-l", str(root / "pg.log"),
                        "-o", f"-k {root} -h '' -p 6544", "-w", "start"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.dsn = f"host={root} port=6544 dbname=postgres user=fixture"
        with psycopg2.connect(cls.dsn) as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE normalized_categories(category_id int PRIMARY KEY,
                    barbora_category_code text);
                INSERT INTO normalized_categories VALUES
                    (1,'c5c7b6b4-ef9a-4aff-bd22-e2bfcc0becd7'),
                    (2,'84e6b16a-6acf-4e72-a248-925d35c2ef0d');
                CREATE TABLE products(product_id int PRIMARY KEY,sku text,name text,
                    category_id int,rimi_category_code int,needs_enrichment bool,
                    enrichment_reviewed bool,enrichment_skipped bool,
                    nutrition_source text,updated_at timestamptz,brand_id int);
                CREATE TABLE nutritionfacts(product_id int UNIQUE,energy_kj int,
                    energy_kcal int,fat_total numeric,fat_saturated numeric,
                    carbs_total numeric,carbs_sugars numeric,protein numeric,salt numeric,
                    fiber numeric,is_fiber_correct bool,nutrition_manual_edit bool,
                    usda_fdc_id int,nutri_score_grade text,nutri_score_points int,
                    data_source_date timestamptz,ingredients_text text);
                CREATE TABLE product_price_history(price_history_id int PRIMARY KEY,
                    product_id int,is_available bool,recorded_at timestamptz);
            """)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-m", "immediate", "-w", "stop"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.temp.cleanup()

    def setUp(self):
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("""
                TRUNCATE products,nutritionfacts,product_price_history;
                INSERT INTO products VALUES
                    (1,'00001','Āboli kg',1,197,TRUE,FALSE,FALSE,NULL,'2026-01-01',55),
                    (2,'rimi2','Āboli Rimi kg',1,197,FALSE,FALSE,FALSE,'usda_api','2026-01-01',66),
                    (3,'untouched','Other',1,NULL,FALSE,FALSE,FALSE,NULL,'2026-01-01',77);
                INSERT INTO nutritionfacts(product_id,fiber,is_fiber_correct,nutrition_manual_edit,
                    usda_fdc_id,nutri_score_grade,nutri_score_points,ingredients_text)
                    VALUES (1,2.8,FALSE,FALSE,999,'E',20,'old ingredients');
                INSERT INTO nutritionfacts VALUES
                    (2,218,52,.17,.028,13.81,10.39,.26,0,9.9,TRUE,FALSE,
                     123,'A',-2,'2026-01-01','source ingredients');
                INSERT INTO product_price_history VALUES (1,1,TRUE,'2026-01-01');
            """)
        self.conn, self.source = connect(self.dsn, False), connect(self.dsn, True)
        self.receipt = self.root / "receipt.json"
        self.receipt.unlink(missing_ok=True)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.source.close)
        self.entry = self.make_entry()

    def make_entry(self):
        rows = read_rows(self.conn, [1, 2])
        calculator = NutriscoreCalculator(self.conn)
        target, source = rows["1"], rows["2"]
        entry = {"approved": {"target_product_id": "1", "source_product_id": "2"},
                 "original": {"target": copy.deepcopy(target), "source": copy.deepcopy(source)},
                 "baseline": {"target": target, "source": source}}
        entry["proposal"] = plan(entry, target, source, calculator, FiberEstimator())
        self.categories = category_state(self.conn)
        self.conn.rollback()
        return entry

    def mutate(self, query):
        self.conn.rollback()
        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(query)

    def apply(self):
        return apply_one(self.conn, self.source, self.entry, self.receipt, self.categories)

    def test_complete_import_preserves_all_unrelated_fields_and_zero(self):
        self.assertEqual(self.apply()["status"], "updated")
        after = read_rows(self.conn, [1])["1"]
        p, n = after["product"], after["nutrition"]
        self.assertFalse(p["needs_enrichment"])
        self.assertEqual(p["nutrition_source"], "usda_api")
        self.assertEqual(n["salt"], 0)
        self.assertEqual(n["fiber"], 2.8)
        self.assertFalse(n["is_fiber_correct"])
        self.assertFalse(n["nutrition_manual_edit"])
        self.assertEqual(n["ingredients_text"], "old ingredients")
        self.assertEqual(p["brand_id"], 55)
        self.assertEqual(p["sku"], "00001")
        self.assertEqual(n["usda_fdc_id"], 123)
        expected = calculate_nutriscore_2024("general",218,10.39,.028,0,.26,2.8,100,.17)
        self.assertEqual(n["nutri_score_grade"], expected["grade"])
        self.assertEqual(n["nutri_score_points"], expected["score"])

    def test_partial_keeps_flag_and_known_target_value_without_guessing(self):
        self.mutate("UPDATE nutritionfacts SET carbs_total=NULL,protein=NULL WHERE product_id=2; "
                    "UPDATE nutritionfacts SET carbs_total=14 WHERE product_id=1")
        self.entry = self.make_entry()
        self.assertEqual(self.apply()["status"], "partial")
        n = read_rows(self.conn, [1])["1"]["nutrition"]
        self.assertEqual(n["carbs_total"], 14)
        self.assertIsNone(n["protein"])
        self.assertIsNone(n["nutri_score_grade"])
        self.assertTrue(read_rows(self.conn, [1])["1"]["product"]["needs_enrichment"])

    def test_missing_fdc_does_not_retain_old_target_id(self):
        self.mutate("UPDATE nutritionfacts SET usda_fdc_id=NULL WHERE product_id=2")
        self.entry = self.make_entry()
        self.assertEqual(self.apply()["status"], "updated")
        self.assertIsNone(read_rows(self.conn, [1])["1"]["nutrition"]["usda_fdc_id"])

    def test_missing_fiber_uses_estimator_only_for_scoring(self):
        self.mutate("UPDATE nutritionfacts SET fiber=NULL WHERE product_id=1")
        self.entry = self.make_entry()
        self.assertEqual(self.entry["proposal"]["fiber_for_scoring"]["kind"], "category")
        self.assertEqual(self.apply()["status"], "updated")
        n = read_rows(self.conn, [1])["1"]["nutrition"]
        self.assertIsNone(n["fiber"])
        self.assertIsNotNone(n["nutri_score_grade"])

    def test_no_fiber_match_clears_stale_score_not_stored_fiber(self):
        self.mutate("UPDATE nutritionfacts SET fiber=NULL WHERE product_id=1; "
                    "UPDATE products SET rimi_category_code=NULL WHERE product_id=1")
        self.entry = self.make_entry()
        self.assertEqual(self.apply()["status"], "updated")
        self.assertIsNone(read_rows(self.conn, [1])["1"]["nutrition"]["nutri_score_grade"])

    def test_protected_manual_edit_and_review_are_not_overwritten(self):
        for query in (
            "UPDATE nutritionfacts SET nutrition_manual_edit=TRUE WHERE product_id=1",
            "UPDATE products SET enrichment_reviewed=TRUE WHERE product_id=1",
        ):
            self.mutate(query)
            self.assertEqual(self.apply()["status"], "skipped")

    def test_source_stale_and_target_stale_skip(self):
        self.mutate("UPDATE nutritionfacts SET protein=20 WHERE product_id=2")
        self.assertEqual(self.apply()["reason"], "source_changed_since_preview")
        self.entry = self.make_entry()
        self.mutate("UPDATE products SET name='New name' WHERE product_id=1")
        self.assertEqual(self.apply()["reason"], "target_changed_since_preview")

    def test_latest_availability_tie_breaker(self):
        self.mutate("INSERT INTO product_price_history VALUES (2,1,FALSE,'2026-01-01')")
        self.assertEqual(self.apply()["reason"], "latest_scraped_availability_not_true")

    def test_categories_changed_skip(self):
        self.mutate("UPDATE normalized_categories SET barbora_category_code='changed' WHERE category_id=2")
        try:
            self.assertEqual(self.apply()["reason"], "category_configuration_changed")
        finally:
            self.mutate("UPDATE normalized_categories SET barbora_category_code='84e6b16a-6acf-4e72-a248-925d35c2ef0d' WHERE category_id=2")

    def test_repeat_and_guarded_restore(self):
        self.assertEqual(self.apply()["status"], "updated")
        self.assertEqual(self.apply()["status"], "already_applied")
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(restore_one(self.conn, receipt)["status"], "restored")
        self.assertEqual(restore_one(self.conn, receipt)["status"], "already_restored")
        self.assertEqual(read_rows(self.conn, [1])["1"]["nutrition"]["usda_fdc_id"],999)

    def test_restore_refuses_later_edits(self):
        self.apply()
        receipt = json.loads(self.receipt.read_text())
        self.mutate("UPDATE nutritionfacts SET salt=1 WHERE product_id=1")
        self.assertEqual(restore_one(self.conn, receipt)["reason"], "later_edits_or_missing_row")

    def test_write_receipt_failure_rolls_back_entire_product(self):
        with patch("rimi_nutrition_import_store.write_json", side_effect=OSError("fixture")):
            self.assertEqual(self.apply()["status"], "failed")
        self.assertTrue(read_rows(self.conn, [1])["1"]["product"]["needs_enrichment"])
        self.assertIsNone(read_rows(self.conn, [1])["1"]["nutrition"]["energy_kj"])

    def test_source_session_enforces_readonly(self):
        with self.source.cursor() as cur:
            with self.assertRaises(psycopg2.errors.ReadOnlySqlTransaction):
                cur.execute("UPDATE products SET name='bad' WHERE product_id=2")
        self.source.rollback()

    def test_allowlist_rejects_fiber_names_and_manual_flags(self):
        for role, field in (("product_changes", "name"), ("nutrition_changes", "fiber"),
                            ("nutrition_changes", "is_fiber_correct"),
                            ("nutrition_changes", "nutrition_manual_edit")):
            p = {"product_changes": {}, "nutrition_changes": {}}
            p[role][field] = 1
            with self.assertRaises(ValueError):
                allowlist(p)

    def test_invalid_negative_nonfinite_and_impossible_values(self):
        for n in ({"salt": -1}, {"protein": float("nan")}, {"energy_kj": 2.4},
                  {"fat_total": 3, "fat_saturated": 9}, {"carbs_total": 1,"carbs_sugars": 5}):
            self.assertTrue(invalid_nutrients(n))
        self.assertEqual(invalid_nutrients({"salt":0, "protein":None}), [])

    def test_manifest_rejects_missing_approved_targets_or_unconfirmed_basis(self):
        for manifest in ({"basis":"user_confirmed_per_100g_edible_food","rows":[]},
                         {"basis":"unknown","rows":[]}):
            with self.assertRaises(ValueError):
                validate_manifest(seal(manifest))

    def test_planner_skips_changed_original_identity(self):
        original = copy.deepcopy(self.entry)
        original["original"]["source"]["product"]["sku"] = "different"
        p = plan(original, original["baseline"]["target"], original["baseline"]["source"],
                 NutriscoreCalculator(self.conn), FiberEstimator())
        self.assertEqual(p["reason"], "source_changed_since_review")


if __name__ == "__main__":
    unittest.main()
