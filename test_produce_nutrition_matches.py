"""Offline matching/report regression tests; no production credentials or APIs."""

import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from produce_identity import compatible, identify
from produce_match_quality import assess, fdc_conflicts
from produce_nutrition_matches import build_report, main, safe_cell, to_csv


def product(name="Kivi kg", product_id=1, available=True, source="usda_api", **nutrients):
    values = dict(energy_kcal=50, energy_kj=209, fat_total=0.2, fat_saturated=0,
                  carbs_total=11, carbs_sugars=5, protein=1, salt=0, fiber=2,
                  usda_fdc_id=product_id + 1000, nutrition_manual_edit=False)
    values.update(nutrients)
    return {
        "product": dict(product_id=product_id, sku="000000000000012345", name=name,
                        quantity_value=1, quantity_unit="kg", nutrition_source=source,
                        needs_enrichment=True, enrichment_reviewed=False),
        "nutrition": values, "category_path": "Augļi un dārzeņi / Augļi",
        "ancestry": [1, 2], "available": available,
        "availability_at": "2026-10-11T10:00:00+00:00",
    }


def snapshot(rows):
    return dict(rows=rows, read_only=True, captured_at="2026-10-11T10:00:00+00:00",
                rows_sha256="offline-fixture")


class MatchingTests(unittest.TestCase):
    def match(self, target, source):
        return compatible(identify(product(target)), identify(product(source)))

    def test_aliases_and_diacritics(self):
        self.assertEqual(self.match("Melones CANTA LOUPE kg", "Melone Kantalupe kg"), [])
        self.assertEqual(self.match("Pipari asie Halapenjo kg", "Čili pipars Jalapeno kg"), [])
        self.assertEqual(self.match("Ķirbis Hokaido kg", "Ķirbis Hokkaido kg"), [])

    def test_brands_and_pack_sizes_not_identity(self):
        self.assertEqual(self.match("Pētersīļi WELL DONE 30g", "Pētersīļi Rimi 100g"), [])

    def test_conflicting_colors_and_species_rejected(self):
        for left, right in [("Kivi dzeltenie", "Kivi sarkanie"),
                            ("Baklažāni Japāņu", "Baklažāns Graffiti"),
                            ("Šampinjoni", "Sēnes SHIMEJI"),
                            ("Āboli GRANNY SMITH", "Āboli Golden Delicious"),
                            ("Āboli Rubis Gold", "Āboli Golden"),
                            ("Sīpoli ŠALOTES", "Sīpoli saldie"),
                            ("Arbūzi bez sēklām", "Arbūzi ar sēklām")]:
            with self.subTest(left=left):
                self.assertIsNone(self.match(left, right))

    def test_missing_specificity_reviewed(self):
        self.assertTrue(self.match("Āboli GRANNY SMITH", "Āboli Latvijas"))
        self.assertTrue(self.match("Sparģeļi", "Sparģeļi baltie"))

    def test_specific_names_do_not_collide_with_other_fruit(self):
        self.assertEqual(identify(product("Sīpoli Shallots Banana")).family, "onion")
        self.assertEqual(identify(product("Piparmētra")).family, "mint")
        self.assertEqual(identify(product("Tomāti plūmju")).family, "tomato")
        self.assertEqual(identify(product("Kaktusvīģes")).family, "cactus_fig")
        self.assertEqual(identify(product("Kivi ogas")).family, "kiwiberry")
        self.assertIsNone(self.match("Bumbieri Nashi", "Bumbieri Conference"))

    def test_microgreens_sprouts_mature_separate(self):
        self.assertIsNone(self.match("Brokoļu mikrozaļumi", "Brokoļi"))
        self.assertIsNone(self.match("Mikrozaļumi Lucernas asni", "Lucernas dīgsti"))
        self.assertEqual(self.match("Mikrozaļumi Brokoļu", "Brokoļu mikrozaļumi"), [])

    def test_processed_nonfood_and_unknown(self):
        for name in ("Zirņi vārīti", "Mango žāvēts", "Dzērvenes maltas",
                     "Kāposts sagriezts", "Ķirbis dekoratīvais", "Čiekurs gab."):
            with self.subTest(name=name):
                self.assertEqual(identify(product(name)).scope, "excluded")
        self.assertEqual(identify(product("Mystery 300g")).scope, "review")
        row = product()
        row["category_path"] = "Augļi un dārzeņi / Pārstrādātie dārzeņi"
        self.assertEqual(identify(row).scope, "excluded")

    def test_mixture_not_single_ingredient(self):
        self.assertIsNone(self.match("Salātu maisījums Family", "Spināti"))
        self.assertIsNone(self.match("Salātu maisījums Family", "Salātu maisījums Oriental"))
        self.assertTrue(self.match("Salātu maisījums Family", "Salātu maisījums Family"))

    def test_mixture_known_composition_conflict_rejected(self):
        t = product("Salātu maisījums Family", ingredients_text="Spināti, salāti")
        s = product("Salātu maisījums Family", 2, ingredients_text="Burkāni, salāti")
        rows, _, _ = build_report(snapshot([t]), snapshot([s]))
        self.assertEqual(rows[0]["outcome"], "unresolved")

    def test_zero_preservation_and_csv_safety(self):
        row = product()
        rows, _, _ = build_report(snapshot([row]), snapshot([product(product_id=2)]))
        csv_rows = list(csv.DictReader(io.StringIO(to_csv(rows))))
        self.assertEqual(csv_rows[0]["target_sku"], "000000000000012345")
        self.assertEqual(csv_rows[0]["source_salt_g"], "0")
        self.assertEqual(csv_rows[0]["source_fat_saturated_g"], "0")
        self.assertEqual(safe_cell("\x01 \t=HYPERLINK(\"bad\")")[0], "'")
        self.assertEqual(safe_cell(0), 0)
        self.assertEqual(safe_cell(None), "")

    def test_all_zero_negative_nonfinite_impossible_invalid(self):
        cases = [
            dict(energy_kcal=0, energy_kj=0, fat_total=0, carbs_total=0, protein=0),
            dict(salt=-1), dict(fiber=float("nan")), dict(fat_total=float("inf")),
            dict(fat_total=101), dict(carbs_sugars=50),
            dict(fat_total=0.2, fat_saturated=10),
            dict(fat_total=60, fat_saturated=30, carbs_total=60, protein=10,
                 energy_kcal=820, energy_kj=3431),
        ]
        for values in cases:
            with self.subTest(values=values):
                row = product(**values)
                self.assertEqual(assess(row, identify(row))["state"], "invalid")

    def test_incomplete_energy_consistency_concentration_reviewed(self):
        for row in (product(carbs_sugars=None), product(energy_kj=2000),
                    product(energy_kcal=250, energy_kj=1046),
                    product("Sēnes Šitake", energy_kcal=296, energy_kj=1238, carbs_total=75)):
            with self.subTest(row=row["product"]["name"]):
                self.assertEqual(assess(row, identify(row))["state"], "review")
        coconut = product("Kokosrieksts", energy_kcal=354, energy_kj=1481, fat_total=33,
                          fat_saturated=29, carbs_total=15, carbs_sugars=6, protein=3)
        self.assertEqual(assess(coconut, identify(coconut))["state"], "usable")

    def test_fdc_reuse_across_incompatible_species_and_stages(self):
        rows = [product("Šampinjoni", usda_fdc_id=99), product("SHIMEJI sēnes", 2, usda_fdc_id=99)]
        conflicts = fdc_conflicts(rows, [identify(r) for r in rows])
        self.assertIn(99, conflicts)
        self.assertEqual(assess(rows[0], identify(rows[0]), conflicts)["state"], "review")

    def test_unknown_source_audit_only(self):
        rows, audit, summary = build_report(snapshot([product()]), snapshot([product(product_id=2, source=None)]))
        self.assertEqual(rows[0]["outcome"], "unmatched")
        self.assertEqual(audit[0]["quality"], "unknown_origin")
        self.assertEqual(summary["source_origins"]["unknown"], 1)

    def test_protected_target_and_source_manual_edit(self):
        rows, _, _ = build_report(snapshot([product(nutrition_manual_edit=True)]), snapshot([product(product_id=2)]))
        self.assertEqual(rows[0]["outcome"], "manual_protected")
        self.assertNotIn("source_name", rows[0])
        s = product(product_id=2, nutrition_manual_edit=True)
        self.assertEqual(assess(s, identify(s))["state"], "review")

    def test_unavailable_reference_not_silently_dropped(self):
        target, source = product(), product(product_id=2, available=False)
        rows, _, _ = build_report(snapshot([target]), snapshot([source]))
        self.assertEqual(rows[0]["outcome"], "suggested")
        self.assertFalse(rows[0]["source_available"])

    def test_availability_tie_preference_and_limit_three(self):
        sources = [product(product_id=i, available=i == 6) for i in range(2, 7)]
        rows, _, _ = build_report(snapshot([product()]), snapshot(sources))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["source_product_id"], 6)
        self.assertEqual([r["candidate_rank"] for r in rows], [1, 2, 3])

    def test_empty_reference_and_no_mutation(self):
        target = snapshot([product(fiber=None)])
        before = copy.deepcopy(target)
        rows, _, summary = build_report(target, snapshot([]))
        self.assertEqual(rows[0]["outcome"], "unmatched")
        self.assertIsNone(rows[0]["target_fiber_g"])
        self.assertEqual(before, target)
        self.assertEqual(sum(summary["outcomes"].values()), 1)

    def test_no_false_high_confidence_missing_metadata(self):
        for source in (product(product_id=2, usda_fdc_id=None), product(product_id=2, protein=None),
                       product(product_id=2, ingredients_text="gaļa")):
            rows, _, _ = build_report(snapshot([product()]), snapshot([source]))
            self.assertEqual(rows[0]["outcome"], "review_only")

    def test_fiber_warning_never_generates_or_clears_fiber(self):
        target = product(fiber=7, is_fiber_correct=True)
        source = product(product_id=2, fiber=None)
        before = copy.deepcopy((target, source))
        rows, _, _ = build_report(snapshot([target]), snapshot([source]))
        self.assertIn("Fiber missing", rows[0]["source_warnings"])
        self.assertEqual(rows[0]["target_fiber_g"], 7)
        self.assertEqual((target, source), before)

    def test_read_only_metadata_required(self):
        a = snapshot([product()])
        a["read_only"] = False
        with self.assertRaises(ValueError):
            build_report(a, snapshot([]))

    def test_cli_outputs_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("produce_nutrition_matches.capture", side_effect=[snapshot([product()]), snapshot([product(product_id=2)])]):
                main(["--production-read-only", "--output", folder])
            self.assertTrue((Path(folder) / "matches.csv").read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(json.loads((Path(folder) / "summary.json").read_text())["starting_targets"], 1)
            with self.assertRaises(SystemExit):
                main(["--production-read-only", "--output", folder])

    def test_no_apply_option_or_implicit_production_access(self):
        with patch("produce_nutrition_matches.capture") as reader:
            for args in ([], ["--production-read-only", "--apply"]):
                with self.assertRaises(SystemExit):
                    main(args)
            reader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
