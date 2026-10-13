"""Recovered preparation fixtures, tested without any environment databases."""

import copy
import unittest
from unittest.mock import patch

import psycopg2

import test_nova_analysis_completion as completion
import test_product_refresh as refresh
from fiber_estimator import FiberEstimator
from ingredient_processor import extract_ingredient_tokens
from nutriscore_calculator import NutriscoreCalculator
from nutrition_reload_plan import FIELDS
from poultry_scoring import apply, prepare, scoring_plan
from product_refresh_store import RefreshError


def fixture(pid=12984):
    chicken = pid == 12984
    text = ("cāļa krūtiņas fileja 68%, cāļa ādas, ūdens, sāls, aromatizētāji, biešu ekstrakts"
            if chicken else
            "tītara gaļa 98%, sāls, skābuma regulētājs nātrija acetāti, aromatizētāji, "
            "garšvielu ekstrakti, augu ekstrakti, garšvielas. Var saturēt lipekli saturošus "
            "graudaugus, soju, pienu (tostarp laktozi), selerijas, sinepes.")
    return {
        "product": {"product_id": pid,
                    "sku": "000000000001315297" if chicken else "000000000001286881",
                    "name": "Cāļa filejas maltās gaļas masa ĶEKAVA 450g" if chicken else
                            "Tītara maltās gaļas masa WELL DONE 400g",
                    "category_id": 352, "rimi_category_code": None, "ingredients": text,
                    "nova_score": None, "nova_source": None, "name_manual_edit": False},
        "nutrition": {"energy_kj": 706 if chicken else 628,
                      "energy_kcal": 169 if chicken else 150, "fat_total": 11.5 if chicken else 8.8,
                      "fat_saturated": 3.2 if chicken else 2.7, "carbs_total": .8 if chicken else 0,
                      "carbs_sugars": .1 if chicken else 0, "protein": 16.1 if chicken else 18,
                      "salt": 1.2 if chicken else 1.6, "fiber": None, "is_fiber_correct": False,
                      "ingredients_text": text, "nutrition_manual_edit": False},
        "ingredient_mapping": [],
    }


def context(snapshot):
    rows = [dict(completion.analysis(index), ingredient=token)
            for index, token in enumerate(extract_ingredient_tokens(snapshot["product"]["ingredients"]), 1)]
    for row in rows:
        if row["ingredient"] == "aromatizētāji":
            row.update(category="processed", is_processed=True, suspicion_level="caution",
                       suspicion_category="flavor_enhancer")
    return {"ingredients": rows, "category_nova": 1}


class PoultryRuleTests(unittest.TestCase):
    def plan(self, snapshot, ctx=None, estimator=None):
        return scoring_plan(snapshot, ctx or context(snapshot), NutriscoreCalculator(),
                            estimator or FiberEstimator())

    def test_verified_defaults_and_poultry_not_red_meat(self):
        for pid in (12984, 12985):
            plan = self.plan(fixture(pid))
            self.assertEqual(plan["product_changes"]["rimi_category_code"], 78)
            self.assertEqual(plan["product_changes"]["nova_score"], 4)
            self.assertEqual(plan["nutrition_changes"]["fiber"], 0)
            self.assertIs(dict(fixture(pid)["nutrition"], **plan["nutrition_changes"])["is_fiber_correct"], False)
            self.assertEqual(plan["nutrition_changes"]["nutri_score_grade"], "C")
            self.assertEqual(plan["pending"], [])

    def test_absent_source_fiber_is_not_zero_without_estimator_match(self):
        estimator = FiberEstimator()
        estimator.category_defaults.pop(78)
        plan = self.plan(fixture(), estimator=estimator)
        self.assertNotIn("fiber", plan["nutrition_changes"])
        self.assertIsNone(plan["nutrition_changes"].get("nutri_score_grade"))

    def test_no_raw_default_when_preparation_marker_missing_or_pending(self):
        snapshot = fixture()
        ctx = context(snapshot)
        ctx["ingredients"] = [row for row in ctx["ingredients"] if row["ingredient"] != "aromatizētāji"]
        plan = self.plan(snapshot, ctx)
        self.assertIsNone(plan["product_changes"].get("nova_score"))
        self.assertIn("aromatizētāji", plan["pending"])
        for row in context(snapshot)["ingredients"]:
            if row["ingredient"] == "aromatizētāji":
                row.update(category="natural", is_processed=False, suspicion_level=None)
            ctx["ingredients"].append(row)
        plan = self.plan(snapshot, ctx)
        self.assertEqual(plan["nova_reason"], "unsupported_preparation_default")
        self.assertIsNone(plan["product_changes"].get("nova_score"))

    def test_manual_fiber_nutrition_and_nova_protection(self):
        snapshot = fixture()
        snapshot["nutrition"].update(nutrition_manual_edit=True, fiber=5,
                                     nutri_score_grade="A", nutri_score_points=-4)
        snapshot["product"].update(nova_source="manual_override", nova_score=2)
        plan = self.plan(snapshot)
        self.assertEqual(plan["nutrition_changes"], {})
        self.assertNotIn("nova_score", plan["product_changes"])
        self.assertIsNone(plan["ingredient_tokens"])
        snapshot["nutrition"]["nutrition_manual_edit"] = False
        self.assertNotIn("fiber", self.plan(snapshot)["nutrition_changes"])

    def test_allergen_warning_not_an_accepted_ingredient(self):
        tokens = extract_ingredient_tokens(fixture(12985)["product"]["ingredients"])
        self.assertIn("garšvielas", tokens)
        for token in ("soju", "pienu", "selerijas", "sinepes"):
            self.assertNotIn(token, tokens)
        self.assertFalse(any("var saturēt" in t for t in tokens))


class StoredSource:
    def product(self, snapshot):
        return {"sku": snapshot["product"]["sku"],
                "ingredients": snapshot["nutrition"]["ingredients_text"],
                "nutrition": {k: v for k, v in snapshot["nutrition"].items()
                              if k in FIELDS and k != "fiber"}}


class PoultryDatabaseTests(unittest.TestCase):
    """Real transactions, but only on a private disposable PostgreSQL cluster."""
    setUpClass = classmethod(completion.CompletionTests.setUpClass.__func__)
    tearDownClass = classmethod(completion.CompletionTests.tearDownClass.__func__)
    execute = refresh.DatabaseTests.execute

    def setUp(self):
        completion.CompletionTests.setUp(self)
        self.execute("""
            UPDATE products SET category_id=352,rimi_category_code=NULL;
            UPDATE ingredient_analysis SET category='natural',is_processed=FALSE;
            INSERT INTO nutritionfacts(product_id,energy_kj,energy_kcal,fat_total,fat_saturated,
                carbs_total,carbs_sugars,protein,salt,fiber,is_fiber_correct,ingredients_text)
            SELECT 2,energy_kj,energy_kcal,fat_total,fat_saturated,carbs_total,carbs_sugars,
                protein,salt,NULL,FALSE,'piens' FROM nutritionfacts WHERE product_id=1;
            UPDATE nutritionfacts SET fiber=NULL,is_fiber_correct=FALSE;
            INSERT INTO rimi_nova_categories VALUES (78,1);
        """)
        self.targets = patch("poultry_scoring.TARGETS", {1: refresh.SKU, 2: "untouched"})
        self.references = patch("poultry_scoring.reference_snapshot", return_value={"verified": "fixture"})
        self.targets.start()
        self.references.start()
        self.addCleanup(self.targets.stop)
        self.addCleanup(self.references.stop)

    def preview(self):
        return prepare(self.dsn, "unused-fixture-reference", StoredSource())

    def test_scoped_atomic_apply_and_manual_protection(self):
        self.execute("""
            UPDATE products SET nova_score=2,nova_source='manual_override' WHERE product_id=1;
            UPDATE nutritionfacts SET nutrition_manual_edit=TRUE,fiber=5,
                nutri_score_grade='A',nutri_score_points=-4 WHERE product_id=1;
        """)
        preview = self.preview()
        apply(preview, preview["sha256"], self.dsn, "unused-fixture-reference")
        self.assertEqual(self.execute("""
            SELECT n.fiber,n.nutri_score_grade,n.nutri_score_points,p.nova_score,p.nova_source
            FROM products p JOIN nutritionfacts n USING(product_id) WHERE product_id=1
        """), [(5, "A", -4, 2, "manual_override")])
        self.assertEqual(self.execute("SELECT nova_score FROM products WHERE product_id=2"), [(None,)])

    def test_stale_protection_analysis_or_checksum_reject_without_writes(self):
        for mutation in (
            "UPDATE nutritionfacts SET nutrition_manual_edit=TRUE WHERE product_id=1",
            "UPDATE ingredient_analysis SET category='uncategorized' WHERE id=1",
        ):
            preview = self.preview()
            self.execute(mutation)
            before = self.execute("SELECT rimi_category_code,nova_score FROM products ORDER BY product_id")
            with self.assertRaises(RefreshError):
                apply(preview, preview["sha256"], self.dsn, "unused-fixture-reference")
            self.assertEqual(before, self.execute(
                "SELECT rimi_category_code,nova_score FROM products ORDER BY product_id"))
        preview = self.preview()
        bad = copy.deepcopy(preview)
        bad["plans"][0]["product_changes"]["nova_score"] = 1
        with self.assertRaises(RefreshError):
            apply(bad, bad["sha256"], self.dsn, "unused-fixture-reference")

    def test_failing_completion_rolls_back_mapping_fiber_and_score(self):
        preview = self.preview()
        before = self.execute("SELECT fiber,nutri_score_grade FROM nutritionfacts ORDER BY product_id")
        with patch("poultry_scoring._assign_nova_score", side_effect=RuntimeError("fixture failure")):
            # Force the completion path even though these fixtures have no marker.
            with patch("poultry_scoring.calculate_nova", return_value=(4, "additive_override", "additive")):
                preview = self.preview()
                with self.assertRaises(RuntimeError):
                    apply(preview, preview["sha256"], self.dsn, "unused-fixture-reference")
        self.assertEqual(before, self.execute(
            "SELECT fiber,nutri_score_grade FROM nutritionfacts ORDER BY product_id"))
        self.assertEqual(self.execute("SELECT rimi_category_code FROM products"), [(None,), (None,)])


if __name__ == "__main__":
    unittest.main()
