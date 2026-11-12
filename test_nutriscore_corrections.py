"""Pure regression matrix: no credentials, project database or recalculation."""
import copy
import math
import unittest
from decimal import Decimal
from fractions import Fraction
from unittest.mock import MagicMock, patch

from nutriscore_calculator import (
    NutriscoreCalculator, calculate_nutriscore, calculate_nutriscore_2024, get_points,
)
from nutriscore_standalone import ProductCategory, calculate, _pts

BASE = dict(energy_kj=0, sugars_g=0, sat_fat_g=0, salt_g=0, protein_g=0,
            fiber_g=0, fvl_pct=0, total_fat_g=100, has_sweeteners=False)
RATIOS = (10, 16, 22, 28, 34, 40, 46, 52, 58, 64)
COMPONENTS = {
    "energy_points": "energy_pts", "sugar_points": "sugars_pts",
    "satfat_points": "saturated_fat_pts", "salt_points": "salt_pts",
    "sweetener_points": "sweetener_pts", "protein_points": "protein_pts",
    "fiber_points": "fiber_pts", "fvl_points": "fvl_pts",
    "negative_total": "total_negative", "positive_total": "total_positive",
}


def standalone(category, data):
    return calculate(
        category=ProductCategory(category), energy_kj=data["energy_kj"],
        sugars_g=data["sugars_g"], saturated_fat_g=data["sat_fat_g"],
        salt_g=data["salt_g"], protein_g=data["protein_g"], fiber_g=data["fiber_g"],
        fvl_percent=data["fvl_pct"], total_fat_g=data["total_fat_g"],
        has_sweeteners=data["has_sweeteners"])


def category_connection():
    """Resolve genuine existing UUIDs to fixture IDs through the actual loader."""
    conn = MagicMock()
    conn.cursor.return_value.fetchall.return_value = [
        (11, "0e665244-fbd5-4377-87b2-90dca75126ad"),  # oil
        (12, "60a69a0d-7313-4d4d-858f-f1014830d3a7"),  # cheese
        (13, "abd4343d-fe64-44a2-a71e-1f92bc3184ae"),  # red meat
        (14, "84e6b16a-6acf-4e72-a248-925d35c2ef0d"),  # juice
        (15, "c5c7b6b4-ef9a-4aff-bd22-e2bfcc0becd7"),  # full FVL
        (16, "138145ac-f69d-44b2-8fc4-79f8c984c08f"),  # half FVL
    ]
    return conn


def single_inputs(data):
    return dict(energy_kj=data["energy_kj"], sugars=data["sugars_g"],
                saturated_fat=data["sat_fat_g"], salt=data["salt_g"],
                protein=data["protein_g"], fiber=data["fiber_g"],
                fruits_veg_nuts=data["fvl_pct"], total_fat=data["total_fat_g"],
                has_sweeteners=data["has_sweeteners"])


class ScoringTests(unittest.TestCase):
    def assert_parity(self, category, **changes):
        data = dict(BASE, **changes)
        result = calculate_nutriscore_2024(category, **data)
        other = standalone(category, data)
        self.assertEqual((result["grade"], result["score"]), (other.grade, other.score))
        self.assertEqual(result["score"], result["n_points"] - result["p_points"])
        for main_key, standalone_key in COMPONENTS.items():
            self.assertEqual(result["components"][main_key], getattr(other.components, standalone_key),
                             main_key)
        if category == "fats_oils_nuts":
            components = result["components"]
            self.assertEqual(result["p_points"], components["protein_points"] +
                             components["fiber_points"] + components["fvl_points"])
            self.assertEqual(result["protein_status"], other.components.protein_status)
        return result, other

    def test_general_food_grade_minus_one_zero_one(self):
        for category in ("general", "cheese", "red_meat"):
            for inputs, score, grade in (({"protein_g": 3}, -1, "A"),
                                         ({}, 0, "A"), ({"sugars_g": 4}, 1, "B")):
                with self.subTest(category=category, score=score):
                    result, _ = self.assert_parity(category, **inputs)
                    self.assertEqual((result["score"], result["grade"]), (score, grade))

    def test_zero_boundary_is_not_applied_to_fats_or_beverages(self):
        for category, inputs in (("fats_oils_nuts", {}), ("beverage", {"energy_kj": 1})):
            result, _ = self.assert_parity(category, **inputs)
            self.assertEqual((result["score"], result["grade"]), (0, "B"))

    def test_fats_cutoff_matrix_and_effective_explanation(self):
        for n in (6, 7, 8, 10, 11):
            for fvl, fvl_points in ((0, 0), (100, 5)):
                with self.subTest(n=n, fvl=fvl):
                    salt = float(Decimal(n) / 5 + Decimal(".1"))
                    result, other = self.assert_parity(
                        "fats_oils_nuts", salt_g=salt, protein_g=20, fiber_g=8,
                        fvl_pct=fvl, energy_kj=3700)
                    effective = 7 if n < 7 else 0
                    self.assertEqual(result["n_points"], n)
                    self.assertEqual(result["components"]["protein_points"], effective)
                    self.assertEqual(result["p_points"], effective + 5 + fvl_points)
                    self.assertEqual(result["score"], n - effective - 5 - fvl_points)
                    self.assertEqual(other.components.protein_blocked, n >= 7)
                    if n >= 7:
                        self.assertIn(f"N={n} >= 7", result["protein_status"])
                        self.assertIn(f"FVL={fvl_points}", result["protein_status"])
                        self.assertIn("Protein         : 0 pts", other.summary)
                    else:
                        self.assertEqual(result["protein_status"], "included")
                    self.assertIn(f"{n} - {result['p_points']} = {result['score']}", other.summary)

    def test_fats_cutoff_uses_full_category_negative_total(self):
        result, _ = self.assert_parity("fats_oils_nuts", energy_kj=0, sat_fat_g=3.6,
                                       total_fat_g=40, salt_g=1.3, protein_g=20, fvl_pct=100)
        self.assertEqual(result["n_points"], 7)  # 1 saturate-energy + 0 ratio + 6 salt
        self.assertEqual(result["p_points"], 5)
        self.assertEqual(result["components"]["protein_points"], 0)

    def test_every_strict_ratio_boundary_at_decimal_scales(self):
        for fat in map(Decimal, ("100", "37.5", "7", "3.3", "0.07", "99.99")):
            for points, threshold in enumerate(RATIOS, 1):
                exact = fat * threshold / 100
                for delta, expected in ((Decimal("-0.000000000001"), points - 1),
                                        (Decimal(0), points),
                                        (Decimal("0.000000000001"), points)):
                    with self.subTest(fat=fat, threshold=threshold, delta=delta):
                        result, _ = self.assert_parity("fats_oils_nuts", sat_fat_g=exact + delta,
                                                       total_fat_g=fat)
                        self.assertEqual(result["components"]["satfat_points"], expected)

    def test_adjacent_float_values_are_not_absorbed_by_a_tolerance(self):
        for fat in (100., 37.5, 7., 3.3, .07, 99.99):
            for points, threshold in enumerate(RATIOS, 1):
                exact = float(Decimal(str(fat)) * threshold / 100)
                for sat, expected in ((math.nextafter(exact, -math.inf), points - 1),
                                      (exact, points),
                                      (math.nextafter(exact, math.inf), points)):
                    with self.subTest(fat=fat, threshold=threshold, saturated=sat):
                        result, _ = self.assert_parity("fats_oils_nuts", sat_fat_g=sat, total_fat_g=fat)
                        self.assertEqual(result["components"]["satfat_points"], expected)

    def test_missing_or_nonpositive_total_fat_fallback_is_unchanged(self):
        for total in (None, 0, -1):
            result, _ = self.assert_parity("fats_oils_nuts", sat_fat_g=12, total_fat_g=total)
            self.assertEqual(result["components"]["satfat_points"], 0)

    def test_energy_uses_saturates_and_unchanged_inclusive_120kj_intervals(self):
        for index, kj in enumerate(range(120, 1201, 120)):
            for delta, expected in ((Fraction(-1, 1000000), index),
                                    (0, index), (Fraction(1, 1000000), index + 1)):
                # Rational inputs make exact 120-kJ boundaries representable.
                saturates = (Fraction(kj) + delta) / 37
                with self.subTest(kj=kj, delta=delta):
                    for declared_energy in (0, 3700):
                        result, _ = self.assert_parity("fats_oils_nuts", energy_kj=declared_energy,
                                                       sat_fat_g=saturates, total_fat_g=100)
                        self.assertEqual(result["components"]["energy_points"], expected)

    def test_fats_grades_keep_their_own_boundaries(self):
        for score, grade in ((-7, "A"), (-6, "A"), (-5, "B"), (0, "B"),
                             (2, "B"), (3, "C"), (10, "C"), (11, "D"),
                             (18, "D"), (19, "E")):
            data = ({"protein_g": {-7: 20, -6: 15, -5: 13}[score]} if score < 0 else
                    {"salt_g": float(Decimal(score) / 5 + Decimal(".1"))})
            with self.subTest(score=score):
                result, _ = self.assert_parity("fats_oils_nuts", **data)
                self.assertEqual((result["score"], result["grade"]), (score, grade))

    def test_general_other_grade_boundaries_are_preserved(self):
        for score, grade in ((1, "B"), (2, "B"), (3, "C"), (10, "C"),
                             (11, "D"), (18, "D"), (19, "E")):
            result, _ = self.assert_parity("general", salt_g=float(Decimal(score) / 5 + Decimal(".1")))
            self.assertEqual((result["score"], result["grade"]), (score, grade))

    def test_unrelated_threshold_helpers_stay_inclusive(self):
        for thresholds in ([335, 670, 1005], [3.4, 6.8, 10], [.2, .4, .6],
                           [3., 4.1, 5.2], [2.4, 4.8, 7.2]):
            for i, value in enumerate(thresholds):
                for helper in (get_points, _pts):
                    self.assertEqual(helper(value, thresholds), i)
                    self.assertEqual(helper(math.nextafter(value, math.inf), thresholds), i + 1)
                    self.assertEqual(helper(math.nextafter(value, -math.inf), thresholds), i)

    def test_general_block_and_five_fvl_exemption_are_unchanged(self):
        for fvl, positive, score in ((0, 5, 7), (100, 17, -5)):
            result, _ = self.assert_parity("general", energy_kj=3700, salt_g=.5,
                                           protein_g=20, fiber_g=8, fvl_pct=fvl)
            self.assertEqual((result["n_points"], result["p_points"], result["score"]), (12, positive, score))
            self.assertEqual(result["components"]["protein_points"], 7)  # Legacy raw field unchanged.
            self.assertEqual(result["protein_status"] == "included", fvl == 100)

    def test_cheese_and_red_meat_exceptions_are_unchanged(self):
        cheese, _ = self.assert_parity("cheese", energy_kj=1200, sugars_g=.5,
                                       sat_fat_g=18, salt_g=1.5, protein_g=20)
        self.assertEqual((cheese["n_points"], cheese["p_points"], cheese["score"], cheese["grade"]),
                         (20, 7, 13, "D"))
        meat, _ = self.assert_parity("red_meat", energy_kj=800, sat_fat_g=5, salt_g=.2, protein_g=25)
        self.assertEqual((meat["n_points"], meat["p_points"], meat["score"], meat["grade"]), (6, 2, 4, "C"))
        meat, _ = self.assert_parity("red_meat", energy_kj=3700, salt_g=.5,
                                     protein_g=20, fiber_g=8, fvl_pct=100)
        self.assertEqual((meat["components"]["protein_points"], meat["p_points"], meat["score"]), (2, 12, 0))

    def test_beverage_grading_water_and_sweetener_rules_are_unchanged(self):
        for energy, expected in ((0, "A"), (1, "B"), (100, "B"), (151, "C"),
                                 (271, "C"), (301, "D"), (361, "D"), (391, "E")):
            result, _ = self.assert_parity("beverage", energy_kj=energy)
            self.assertEqual(result["grade"], expected)
        diet, _ = self.assert_parity("beverage", energy_kj=4, has_sweeteners=True)
        self.assertEqual((diet["score"], diet["grade"], diet["components"]["sweetener_points"]), (4, "C", 4))
        milk, _ = self.assert_parity("beverage", energy_kj=250, sugars_g=5,
                                     salt_g=.1, protein_g=4, fiber_g=5, fvl_pct=100)
        self.assertEqual((milk["n_points"], milk["p_points"], milk["score"], milk["grade"]), (8, 15, -7, "B"))

    def test_legacy_wrapper_preserves_its_interface_and_uses_corrected_core(self):
        for category, flags in (("general", {}), ("fats_oils_nuts", {"is_fat": True}),
                                ("red_meat", {"is_red_meat": True}), ("cheese", {"is_cheese": True}),
                                ("beverage", {"is_beverage": True})):
            for n in (0, 6, 7, 11):
                data = dict(BASE, energy_kj=3700, salt_g=float(Decimal(n) / 5 + Decimal(".1")),
                            protein_g=20, fiber_g=8, fvl_pct=100, total_fat_g=None)
                expected, _ = self.assert_parity(category, **data)
                # The old signature has no total-fat argument; preserve that fallback.
                score, grade, components = calculate_nutriscore(
                    energy_kj=data["energy_kj"], sugars=0, saturated_fat=0,
                    sodium=data["salt_g"] * 400, protein=20, fiber=8, fruits_veg_nuts=100, **flags)
                self.assertEqual((score, grade), (expected["score"], expected["grade"]))
                self.assertEqual(components["positive_points"], expected["p_points"])
                self.assertEqual(components["protein_points"], expected["components"]["protein_points"])


class CalculationPathTests(unittest.TestCase):
    def setUp(self):
        self.conn = category_connection()
        with patch("nutriscore_calculator.logger.warning"):
            self.calculator = NutriscoreCalculator(self.conn)

    def test_individual_batch_and_standalone_share_the_full_fats_matrix(self):
        products = []
        for n in (6, 7, 8, 10, 11):
            for fvl in (0, 100):
                products.append(dict(product_id=f"{n}-{fvl}", category_id=11,
                                     **single_inputs(dict(BASE, protein_g=20, fiber_g=8, fvl_pct=fvl,
                                                          salt_g=float(Decimal(n) / 5 + Decimal(".1"))))))
        for ratio in RATIOS:
            products.append(dict(product_id=f"ratio-{ratio}", category_id=11,
                                 **single_inputs(dict(BASE, sat_fat_g=ratio * .075, total_fat_g=7.5))))
        before = copy.deepcopy(products)
        batch = self.calculator.batch_calculate(products)
        for product, result in zip(products, batch):
            inputs = {k: v for k, v in product.items() if k != "product_id"}
            single = self.calculator.calculate_single_product(**inputs)
            self.assertTrue(single["success"])
            self.assertEqual(result, dict(single, product_id=product["product_id"]))
            direct = calculate_nutriscore_2024(
                "fats_oils_nuts", energy_kj=product["energy_kj"], sugars_g=product["sugars"],
                sat_fat_g=product["saturated_fat"], salt_g=product["salt"],
                protein_g=product["protein"], fiber_g=product["fiber"],
                fvl_pct=product["fruits_veg_nuts"], total_fat_g=product["total_fat"])
            self.assertEqual((result["score"], result["grade"], result["components"]),
                             (direct["score"], direct["grade"], direct["components"]))
            standalone_result = standalone("fats_oils_nuts", dict(
                BASE, energy_kj=product["energy_kj"], sugars_g=product["sugars"],
                sat_fat_g=product["saturated_fat"], salt_g=product["salt"],
                protein_g=product["protein"], fiber_g=product["fiber"],
                fvl_pct=product["fruits_veg_nuts"], total_fat_g=product["total_fat"]))
            self.assertEqual((result["score"], result["grade"]), (standalone_result.score, standalone_result.grade))
        self.assertEqual(products, before)

    def test_saved_category_mapping_not_product_names_controls_classification(self):
        for category_id, category in ((11, "fats_oils_nuts"), (12, "cheese"), (13, "red_meat"),
                                       (14, "beverage"), (999, "general")):
            result = self.calculator.calculate_single_product(
                **single_inputs(BASE), category_id=category_id,
                product_name="Olive avocado soybean oil, milk and cheese", ingredients_text="nuts")
            self.assertEqual(result["classification"]["nutriscore_category"], category)
            self.assertEqual(result["classification"]["fruits_veg_nuts_percent"], 0)
        queries = self.conn.cursor.return_value.execute.call_args_list
        self.assertEqual(len(queries), 1)
        self.assertTrue(queries[0].args[0].strip().startswith("SELECT"))

    def test_existing_fvl_defaults_and_explicit_nonzero_percentages_are_preserved(self):
        for category_id, default in ((15, 100), (16, 50), (11, 0)):
            for supplied, expected in ((0, default), (37, 37), (100, 100)):
                product = dict(single_inputs(dict(BASE, fvl_pct=supplied)), category_id=category_id)
                before = copy.deepcopy(product)
                single = self.calculator.calculate_single_product(**product)
                batch = self.calculator.batch_calculate([dict(product, product_id=1)])[0]
                self.assertEqual(single["classification"]["fruits_veg_nuts_percent"], expected)
                self.assertEqual(batch, dict(single, product_id=1))
                self.assertEqual(product, before)

    def test_all_category_zero_scores_match_individual_and_batch_paths(self):
        products = [dict(single_inputs(dict(BASE, energy_kj=1)), category_id=cat, product_id=cat)
                    for cat in (11, 12, 13, 14, 999)]
        for product, result in zip(products, self.calculator.batch_calculate(products)):
            expected = "B" if product["category_id"] in (11, 14) else "A"
            self.assertEqual((result["score"], result["grade"]), (0, expected))


if __name__ == "__main__":
    unittest.main()
