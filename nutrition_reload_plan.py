"""Pure, allowlisted change planning; never writes to a database."""

import hashlib
import json
import math
import re
import unicodedata

FIELDS = ("energy_kj", "energy_kcal", "fat_total", "fat_saturated",
          "carbs_total", "carbs_sugars", "protein", "salt", "fiber")
REQUIRED = FIELDS[2:8]
PRODUCT_WRITES = {"name", "name_norm", "needs_enrichment", "nutrition_source"}
NUTRITION_WRITES = set(FIELDS) | {
    "nutri_score_grade", "nutri_score_points", "usda_fdc_id", "is_fiber_correct"
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def normalize_name(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", text).strip()


def _propose(row, candidate, calculator):
    p, old = row["product"], row["nutrition"] or {}
    result = {"product_changes": {}, "nutrition_changes": {}, "notes": [],
              "nutrition_status": "unresolved", "name_changed": False}
    if candidate["sku"] != p["sku"]:
        raise ValueError("identity_mismatch")
    if candidate["name"] and candidate["name"] != p["name"]:
        result["name_changed"] = True
        if p.get("name_manual_edit"):
            result["notes"].append("name_manual_edit_protected")
        else:
            result["product_changes"].update(
                name=candidate["name"], name_norm=normalize_name(candidate["name"])
            )
    if old.get("nutrition_manual_edit"):
        result["nutrition_status"] = "protected"
        result["notes"].append("nutrition_manual_edit_protected")
        return result
    nutrition = dict(candidate.get("nutrition", {}))
    issue = candidate.get("nutrition_issue")
    if issue:
        result["nutrition_status"] = issue
        return result
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
           for v in nutrition.values()):
        result["nutrition_status"] = "invalid_nutrition"
        return result
    if not nutrition:
        result["nutrition_status"] = "absent_nutrition"
        return result
    if not all(k in nutrition for k in REQUIRED) or not (
            "energy_kj" in nutrition or "energy_kcal" in nutrition):
        result["nutrition_status"] = "incomplete_nutrition"
        return result
    if "energy_kj" not in nutrition:
        nutrition["energy_kj"] = nutrition["energy_kcal"] * 4.184
    if "energy_kcal" not in nutrition:
        nutrition["energy_kcal"] = nutrition["energy_kj"] / 4.184
    # These source columns are INTEGER. Round explicitly, before scoring/apply.
    nutrition["energy_kj"] = int(nutrition["energy_kj"] + 0.5)
    nutrition["energy_kcal"] = int(nutrition["energy_kcal"] + 0.5)
    if max(nutrition["energy_kj"], nutrition["energy_kcal"]) > 2147483647:
        result["nutrition_status"] = "invalid_energy"
        return result
    fiber = nutrition.get("fiber")
    proposed = {k: nutrition.get(k) for k in FIELDS}
    proposed.update(usda_fdc_id=None, is_fiber_correct=fiber is not None,
                    nutri_score_grade=None, nutri_score_points=None)
    if fiber is not None:
        score = calculator.calculate_single_product(
            energy_kj=nutrition["energy_kj"], sugars=nutrition["carbs_sugars"],
            saturated_fat=nutrition["fat_saturated"], salt=nutrition["salt"],
            protein=nutrition["protein"], fiber=fiber, total_fat=nutrition["fat_total"],
            category_id=p["category_id"],
            product_name=result["product_changes"].get("name", p["name"]),
            ingredients_text=p.get("ingredients") or old.get("ingredients_text"),
        )
        if not score.get("success"):
            result["notes"].append("score_calculation_failed")
        else:
            proposed.update(nutri_score_grade=score["grade"], nutri_score_points=score["score"])
    else:
        result["notes"].append("fiber_unknown_score_cleared")
        if old.get("fiber") is not None:
            result["notes"].append("previous_fiber_cleared_to_avoid_mixed_provenance")
    result["nutrition_status"] = "complete"
    result["product_changes"].update(needs_enrichment=False, nutrition_source="barbora_scraped")
    result["nutrition_changes"] = proposed
    return result


def assert_allowlist(proposal):
    if (set(proposal["product_changes"]) - PRODUCT_WRITES
            or set(proposal["nutrition_changes"]) - NUTRITION_WRITES):
        raise ValueError("Non-allowlisted update")


def propose(row, candidate, calculator):
    result = _propose(row, candidate, calculator)
    old = row["nutrition"] or {}
    # A renamed beverage may change sweetener detection. Do not leave an old
    # name-dependent score behind, but never touch protected nutrition.
    if ("name" in result["product_changes"] and not result["nutrition_changes"]
            and old and not old.get("nutrition_manual_edit")):
        changes = {"nutri_score_grade": None, "nutri_score_points": None}
        if all(old.get(k) is not None for k in ("energy_kj", "carbs_sugars",
                                              "fat_saturated", "salt", "protein", "fiber")):
            score = calculator.calculate_single_product(
                energy_kj=old["energy_kj"], sugars=old["carbs_sugars"],
                saturated_fat=old["fat_saturated"], salt=old["salt"],
                protein=old["protein"], fiber=old["fiber"], total_fat=old.get("fat_total"),
                category_id=row["product"]["category_id"],
                product_name=result["product_changes"]["name"],
                ingredients_text=row["product"].get("ingredients") or old.get("ingredients_text"),
            )
            if score.get("success"):
                changes.update(nutri_score_grade=score["grade"], nutri_score_points=score["score"])
        if any(old.get(k) != v for k, v in changes.items()):
            result["nutrition_changes"] = changes
            result["notes"].append("name_dependent_score_refreshed_or_cleared")
    assert_allowlist(result)
    return result
