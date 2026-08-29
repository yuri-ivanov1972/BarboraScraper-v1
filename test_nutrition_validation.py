import unittest

from nutrition_validation import (
    CURRENT_AVAILABILITY_JOIN,
    extract_ingredient_evidence,
    is_safe_barbora_url,
    validate_product,
)


def product(ingredients="", **overrides):
    values = {
        "product_id": 1,
        "ingredients_text": ingredients,
        "fat_total": 5,
        "fat_saturated": 2,
        "carbs_total": 40,
        "carbs_sugars": 10,
        "protein": 10,
        "salt": 0.5,
        "fiber": 2,
    }
    values.update(overrides)
    if "energy_kcal" not in values:
        values["energy_kcal"] = (
            values["protein"] * 4
            + values["carbs_total"] * 4
            + values["fat_total"] * 9
        )
    return values


def rules(result):
    return {reason["rule"] for reason in result["reasons"]}


class IngredientNormalizationTests(unittest.TestCase):
    def test_latvian_characters_and_percentages(self):
        evidence = extract_ingredient_evidence("Piens (35%), rapšu eļļa, cukurs")
        self.assertEqual(evidence["dairy"][0]["term"], "piens")
        self.assertEqual(evidence["dairy"][0]["percentage"], 35.0)
        self.assertIn("fat", evidence)
        self.assertIn("sugar", evidence)

    def test_may_contain_is_not_definite_evidence(self):
        evidence = extract_ingredient_evidence(
            "Kviešu milti. Var saturēt pienu, olas un zemesriekstus."
        )
        self.assertIn("carbohydrate", evidence)
        self.assertNotIn("dairy", evidence)
        self.assertNotIn("protein", evidence)
        self.assertNotIn("nuts", evidence)

    def test_token_boundaries_prevent_substring_matches(self):
        evidence = extract_ingredient_evidence("saltedcaramelword")
        self.assertNotIn("salt", evidence)


class BarboraLinkTests(unittest.TestCase):
    def test_accepts_barbora_http_and_https_urls(self):
        self.assertTrue(is_safe_barbora_url("https://barbora.lv/produkti/test"))
        self.assertTrue(is_safe_barbora_url("http://www.barbora.lv/produkti/test"))

    def test_rejects_non_barbora_or_script_urls(self):
        self.assertFalse(is_safe_barbora_url("https://example.com/product"))
        self.assertFalse(is_safe_barbora_url("javascript:alert(1)"))
        self.assertFalse(is_safe_barbora_url("javascript://barbora.lv/product"))
        self.assertFalse(is_safe_barbora_url(None))


class AvailabilityReviewTests(unittest.TestCase):
    def test_review_scope_uses_latest_available_price_row(self):
        self.assertIn("ORDER BY ph.recorded_at DESC, ph.price_history_id DESC",
                      CURRENT_AVAILABILITY_JOIN)
        self.assertIn("ON current_availability.is_available IS TRUE",
                      CURRENT_AVAILABILITY_JOIN)


class NutritionRuleTests(unittest.TestCase):
    def assert_rule(self, expected_rule, ingredients="", **overrides):
        result = validate_product(product(ingredients, **overrides))
        self.assertIn(expected_rule, rules(result), result)
        return result

    def test_dairy_saturated_fat_zero(self):
        self.assert_rule(
            "milk_present_but_saturated_fat_zero",
            "piens", fat_saturated=0,
        )

    def test_fat_ingredient_total_fat_zero(self):
        self.assert_rule(
            "fat_ingredient_present_but_fat_zero",
            "saulespuķu eļļa", fat_total=0,
        )

    def test_saturated_fat_rich_ingredient_zero(self):
        self.assert_rule(
            "high_saturated_fat_ingredient_but_saturated_fat_zero",
            "kokosriekstu eļļa", fat_saturated=0,
        )

    def test_direct_sugar_zero(self):
        self.assert_rule(
            "sugar_ingredient_present_but_sugars_zero",
            "glikozes sīrups", carbs_sugars=0,
        )

    def test_unknown_sugar_quantity_is_medium_suspicion(self):
        result = validate_product(product("cukurs", carbs_sugars=0))
        reason = next(
            r for r in result["reasons"]
            if r["rule"] == "sugar_ingredient_present_but_sugars_zero"
        )
        self.assertEqual(reason["severity"], "medium")
        self.assertEqual(result["suspicion_level"], "medium")

    def test_strong_declared_percentage_is_high_suspicion(self):
        result = validate_product(product("cukurs (10%)", carbs_sugars=0))
        reason = next(
            r for r in result["reasons"]
            if r["rule"] == "sugar_ingredient_present_but_sugars_zero"
        )
        self.assertEqual(reason["severity"], "high")
        self.assertEqual(result["suspicion_level"], "high")
        self.assertEqual(reason["ingredient_percentages"]["cukurs"], 10.0)

    def test_trace_percentage_is_not_flagged(self):
        result = validate_product(product("cukurs (0,01%)", carbs_sugars=0))
        self.assertNotIn(
            "sugar_ingredient_present_but_sugars_zero", rules(result)
        )

    def test_trace_match_does_not_hide_unknown_match_in_same_group(self):
        result = validate_product(product(
            "cukurs 0,01%, glikozes sīrups", carbs_sugars=0,
        ))
        reason = next(
            r for r in result["reasons"]
            if r["rule"] == "sugar_ingredient_present_but_sugars_zero"
        )
        self.assertEqual(reason["severity"], "medium")

    def test_unparenthesized_trace_percentage_is_not_flagged(self):
        result = validate_product(product("cukurs 0,01%", carbs_sugars=0))
        self.assertNotIn(
            "sugar_ingredient_present_but_sugars_zero", rules(result)
        )

    def test_trace_cocoa_cannot_escalate_through_zero_cluster(self):
        result = validate_product(product(
            "kakao 0,01%", fat_total=0, fat_saturated=0, carbs_sugars=0,
        ))
        self.assertFalse(
            any(rule.startswith("cocoa_present_but_") for rule in rules(result))
        )
        self.assertNotIn(
            "multiple_nutrition_values_inconsistent_with_ingredients",
            rules(result),
        )

    def test_trace_fruit_and_salty_ingredients_are_not_flagged(self):
        fruit = validate_product(product("ābols 0,01%", carbs_sugars=0))
        salty = validate_product(product("sojas mērce 0,01%", salt=0.05))
        self.assertNotIn("fruit_present_but_sugars_zero", rules(fruit))
        self.assertNotIn("salty_ingredient_but_low_salt", rules(salty))

    def test_carbohydrate_ingredient_zero(self):
        self.assert_rule(
            "carbohydrate_ingredient_present_but_carbohydrates_zero",
            "kviešu milti", carbs_total=0, carbs_sugars=0,
        )

    def test_fruit_sugars_zero_is_low_confidence(self):
        result = self.assert_rule(
            "fruit_present_but_sugars_zero", "ābols", carbs_sugars=0,
        )
        reason = next(
            r for r in result["reasons"]
            if r["rule"] == "fruit_present_but_sugars_zero"
        )
        self.assertEqual(reason["severity"], "low")

    def test_salt_zero(self):
        self.assert_rule("salt_present_but_salt_zero", "jūras sāls", salt=0)

    def test_salty_ingredient_low_salt(self):
        self.assert_rule(
            "salty_ingredient_but_low_salt", "sojas mērce", salt=0.05,
        )

    def test_protein_ingredient_zero(self):
        self.assert_rule(
            "protein_ingredient_present_but_protein_zero", "vistas gaļa",
            protein=0,
        )

    def test_nuts_or_seeds_fat_zero(self):
        self.assert_rule(
            "nuts_or_seeds_present_but_fat_zero", "zemesrieksti",
            fat_total=0,
        )

    def test_cocoa_checks_each_zero_nutrient(self):
        result = validate_product(product(
            "kakao", fat_total=0, fat_saturated=0, carbs_sugars=0,
        ))
        self.assertTrue({
            "cocoa_present_but_fat_total_zero",
            "cocoa_present_but_fat_saturated_zero",
            "cocoa_present_but_carbs_sugars_zero",
        }.issubset(rules(result)))

    def test_impossible_mathematical_relationships(self):
        saturated = validate_product(product(
            "", fat_total=5, fat_saturated=8,
        ))
        sugars = validate_product(product(
            "", carbs_total=10, carbs_sugars=15,
        ))
        self.assertIn("saturated_fat_exceeds_total_fat", rules(saturated))
        self.assertIn("sugars_exceed_carbohydrates", rules(sugars))
        self.assertEqual(saturated["suspicion_level"], "high")

    def test_missing_parent_nutrient_is_not_mathematical_contradiction(self):
        saturated = validate_product(product(
            "", fat_total=None, fat_saturated=2, energy_kcal=None,
        ))
        sugars = validate_product(product(
            "", carbs_total=None, carbs_sugars=2, energy_kcal=None,
        ))
        self.assertNotIn("saturated_fat_exceeds_total_fat", rules(saturated))
        self.assertNotIn("sugars_exceed_carbohydrates", rules(sugars))

    def test_energy_inconsistency(self):
        self.assert_rule(
            "energy_inconsistent_with_macronutrients",
            "", fat_total=20, carbs_total=50, protein=20, energy_kcal=100,
        )

    def test_fiber_energy_is_included(self):
        result = validate_product(product(
            "", fat_total=5, carbs_total=40, protein=10, fiber=35,
            energy_kcal=315,
        ))
        self.assertNotIn(
            "energy_inconsistent_with_macronutrients", rules(result)
        )

    def test_unstored_energy_sources_do_not_create_false_positive(self):
        alcohol_like = validate_product(product(
            "vīns, cukurs", fat_total=0, carbs_total=10, protein=0,
            fiber=0, energy_kcal=150,
        ))
        polyol_like = validate_product(product(
            "maltīts, saldinātājs", fat_total=0, carbs_total=20, protein=0,
            fiber=0, energy_kcal=140,
        ))
        self.assertNotIn(
            "energy_inconsistent_with_macronutrients", rules(alcohol_like)
        )
        self.assertNotIn(
            "energy_inconsistent_with_macronutrients", rules(polyol_like)
        )

    def test_polyol_carbohydrates_use_different_energy_factor(self):
        result = validate_product(product(
            "saldinātājs maltīts", fat_total=0, carbs_total=60, protein=0,
            fiber=0, energy_kcal=144,
        ))
        self.assertNotIn(
            "energy_inconsistent_with_macronutrients", rules(result)
        )

    def test_zero_cluster_increases_suspicion(self):
        result = validate_product(product(
            "piens, krējums, cukurs",
            fat_total=0, fat_saturated=0, carbs_sugars=0,
        ))
        self.assertIn(
            "multiple_nutrition_values_inconsistent_with_ingredients",
            rules(result),
        )

    def test_repeated_ingredient_terms_do_not_duplicate_rule(self):
        result = validate_product(product(
            "piens, piena pulveris, krējums", fat_saturated=0,
        ))
        occurrences = [
            reason for reason in result["reasons"]
            if reason["rule"] == "milk_present_but_saturated_fat_zero"
        ]
        self.assertEqual(len(occurrences), 1)


class FalsePositiveTests(unittest.TestCase):
    def test_skimmed_milk_zero_saturated_fat_is_not_flagged(self):
        result = validate_product(product(
            "skimmed milk", fat_total=0.1, fat_saturated=0,
        ))
        self.assertNotIn(
            "milk_present_but_saturated_fat_zero", rules(result)
        )

    def test_small_nonzero_sugar_value_is_not_flagged(self):
        result = validate_product(product("sugar", carbs_sugars=0.1))
        self.assertNotIn(
            "sugar_ingredient_present_but_sugars_zero", rules(result)
        )

    def test_advisory_milk_is_not_flagged(self):
        result = validate_product(product(
            "may contain milk.", fat_saturated=0,
        ))
        self.assertNotIn(
            "milk_present_but_saturated_fat_zero", rules(result)
        )

    def test_validation_is_reproducible(self):
        item = product("cukurs", carbs_sugars=0)
        first = validate_product(item)
        second = validate_product(item)
        self.assertEqual(first["suspicion_score"], second["suspicion_score"])
        self.assertEqual(first["suspicion_level"], second["suspicion_level"])
        self.assertEqual(first["reasons"], second["reasons"])


if __name__ == "__main__":
    unittest.main()