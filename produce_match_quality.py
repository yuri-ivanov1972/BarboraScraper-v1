"""Quality checks on recorded values; never generate/correct nutrient amounts."""

import math
from collections import defaultdict

from produce_identity import HERBS, MUSHROOMS, fold, hits

NUTRIENTS = ("energy_kj", "energy_kcal", "fat_total", "fat_saturated",
             "carbs_total", "carbs_sugars", "protein", "salt", "fiber")
CORE = NUTRIENTS[:-1]
BASIS_URL = "https://fdc.nal.usda.gov/Foundation_Foods_Documentation"
BASIS = "Expected USDA convention: per 100 g edible food; stored row has no explicit basis metadata"


def fdc_conflicts(rows, identities):
    """Find reference reuse across different identities/stages/explicit variants."""
    groups = defaultdict(list)
    for row, identity in zip(rows, identities):
        fdc = (row.get("nutrition") or {}).get("usda_fdc_id")
        if fdc and identity.family and identity.family != "mixture" and identity.scope == "eligible":
            groups[fdc].append((row, identity))
    conflicts = {}
    for fdc, entries in groups.items():
        families = {f"{i.family}/{i.stage}" for _, i in entries}
        variants = defaultdict(set)
        for _, identity in entries:
            for key, value in identity.attributes.items():
                if value:
                    variants[key].add(value)
        keys = sorted(k for k, values in variants.items() if len(values) > 1)
        if len(families) > 1 or keys:
            conflicts[fdc] = (
                "Stored USDA identifier is reused across "
                + ("different produce types/stages: " + ", ".join(sorted(families))
                   if len(families) > 1 else "conflicting explicit " + ", ".join(keys))
                + "; original USDA food match requires verification"
            )
    return conflicts


def assess(row, identity, conflicts=None):
    nutrition = row.get("nutrition") or {}
    source = row["product"].get("nutrition_source")
    warnings, invalid = [], []
    missing = [key for key in CORE if nutrition.get(key) is None]
    if missing:
        warnings.append("Missing core nutrients: " + ", ".join(missing))
    for key in NUTRIENTS:
        value = nutrition.get(key)
        if value is not None:
            try:
                if not math.isfinite(float(value)) or float(value) < 0:
                    invalid.append("Invalid/negative " + key)
                if key not in {"energy_kj", "energy_kcal"} and float(value) > 100:
                    invalid.append(key + " exceeds 100 g")
            except (ValueError, TypeError):
                invalid.append("Non-numeric " + key)
    if not invalid:
        def exceeds(part, total):
            return (nutrition.get(part) is not None and nutrition.get(total) is not None
                    and nutrition[part] > nutrition[total] + 0.05)
        if exceeds("fat_saturated", "fat_total"):
            invalid.append("Saturated fat exceeds total fat")
        if exceeds("carbs_sugars", "carbs_total"):
            invalid.append("Sugars exceed carbohydrates")
        if all(nutrition.get(key) == 0 for key in ("energy_kcal", "energy_kj", "fat_total", "carbs_total", "protein")):
            invalid.append("Suspicious all-zero produce nutrition")
        mass_keys = ("fat_total", "carbs_total", "protein", "salt")
        if all(nutrition.get(key) is not None for key in mass_keys) and sum(nutrition[key] for key in mass_keys) > 102:
            invalid.append("Combined macronutrients/salt exceed 100 g food (allowing rounding)")
        kcal, kj = nutrition.get("energy_kcal"), nutrition.get("energy_kj")
        if kcal is not None and kj is not None and abs(kj - kcal * 4.184) > max(10, abs(kj) * 0.12):
            warnings.append("Energy kJ/kcal inconsistent")
        macro_keys = ("fat_total", "carbs_total", "protein")
        if kcal is not None and all(nutrition.get(k) is not None for k in macro_keys):
            approx = 9 * nutrition["fat_total"] + 4 * nutrition["carbs_total"] + 4 * nutrition["protein"]
            if abs(kcal - approx) > max(25, abs(kcal) * 0.35):
                warnings.append("Energy inconsistent with approximate macronutrient energy")
        ceiling = 160 if identity.family in MUSHROOMS | HERBS | {"turmeric"} else 250 if identity.family in {
            "green_bean", "butter_bean", "pea", "sugar_pea", "bean", "fava", "corn"
        } else None
        if kcal is not None and ceiling and kcal > ceiling:
            warnings.append("Unusually concentrated nutrition for fresh produce; dried/cooked USDA reference possible")
        if identity.family and kcal == 0 and kj == 0:
            invalid.append("Zero energy for identified fresh produce needs source verification")
    if nutrition.get("fiber") is None:
        warnings.append("Fiber missing; existing target fiber/estimation must not be cleared")
    if nutrition.get("nutrition_manual_edit"):
        warnings.append("Rimi nutrition was manually edited; recorded source/basis may be incomplete")
    ingredients = fold(nutrition.get("ingredients_text") or row["product"].get("ingredients"))
    if hits(r"gala|meat|zivs|fish|cukurs|sals|rapsu ella|saulespuku ella|merce|e\d{3}\b", ingredients):
        warnings.append("Recorded ingredients conflict with single fresh produce or indicate additives; source metadata needs verification")
    if source == "usda_api":
        if not nutrition.get("usda_fdc_id"):
            warnings.append("USDA identifier missing")
        if (conflicts or {}).get(nutrition.get("usda_fdc_id")):
            warnings.append(conflicts[nutrition["usda_fdc_id"]])
        basis = BASIS
    else:
        warnings.append("Nutrition origin and per-100-g basis unverified")
        basis = "Unverified; not eligible as a recommended replacement"
    return {
        "state": "invalid" if invalid else "unknown_origin" if source != "usda_api"
                 else "review" if any(not w.startswith("Fiber missing") for w in warnings)
                 else "usable",
        "warnings": invalid + warnings,
        "complete": not missing,
        "basis": basis,
    }
