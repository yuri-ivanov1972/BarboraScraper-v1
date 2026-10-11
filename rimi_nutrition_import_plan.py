"""Pure planning for the explicitly approved, frozen rank-one produce pairs."""

import csv
import hashlib
import json
import math
from pathlib import Path

from nutrition_reload_plan import digest, resolve_fiber
from produce_nutrition_matches import record_columns, safe_cell

CORE = ("energy_kj", "energy_kcal", "fat_total", "fat_saturated",
        "carbs_total", "carbs_sugars", "protein", "salt")
PRODUCT_WRITES = {"nutrition_source", "needs_enrichment"}
NUTRITION_WRITES = set(CORE) | {
    "usda_fdc_id", "nutri_score_grade", "nutri_score_points"
}


def allowlist(proposal):
    if set(proposal["product_changes"]) - PRODUCT_WRITES:
        raise ValueError("Forbidden product write")
    if set(proposal["nutrition_changes"]) - NUTRITION_WRITES:
        raise ValueError("Forbidden nutrition write")


def load_approved(report, summary, target_baseline, source_baseline):
    """Require the original report snapshots, not a new ranking or mapping."""
    info = json.loads(Path(summary).read_text())
    originals = {}
    for role, filename, prefix in (
        ("barbora", target_baseline, "target"), ("rimi", source_baseline, "source")
    ):
        data = json.loads(Path(filename).read_text())
        raw_hash = hashlib.sha256(json.dumps(
            data["rows"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if raw_hash != info[prefix + "_rows_sha256"]:
            raise ValueError("Reviewed baseline fingerprint mismatch")
        originals[role] = {str(r["product"]["product_id"]): r for r in data["rows"]}
    with open(report, encoding="utf-8-sig", newline="") as f:
        pairs = [r for r in csv.DictReader(f) if r["candidate_rank"] == "1"]
    if len(pairs) != 190 or len({r["target_product_id"] for r in pairs}) != 190:
        raise ValueError("Expected exactly 190 unique approved rank-one pairs")
    entries = []
    for pair in pairs:
        if pair["outcome"] not in {"suggested", "review_only"}:
            raise ValueError("Pair was not an approved candidate")
        rows = {}
        for role, prefix in (("barbora", "target"), ("rimi", "source")):
            row = originals[role].get(pair[prefix + "_product_id"])
            if row is None:
                raise ValueError("Approved identity missing from original snapshot")
            recorded = record_columns(prefix + "_", row)
            if any(str(safe_cell(value)) != pair[key] for key, value in recorded.items()):
                raise ValueError("Reviewed CSV disagrees with original snapshot")
            rows[prefix] = row
        entries.append({"approved": pair, "original": rows})
    return entries, hashlib.sha256(Path(report).read_bytes()).hexdigest()


def invalid_nutrients(n):
    errors = []
    for key in CORE:
        value = n.get(key)
        if value is None:
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            errors.append("invalid_" + key)
        elif key.startswith("energy_"):
            if value != int(value) or value > 2147483647:
                errors.append("invalid_" + key)
        elif value > 100:
            errors.append("invalid_" + key)
    if errors:
        return errors
    for part, total in (("fat_saturated", "fat_total"), ("carbs_sugars", "carbs_total")):
        if n.get(part) is not None and n.get(total) is not None and n[part] > n[total] + .05:
            errors.append(part + "_exceeds_total")
    if all(n.get(k) == 0 for k in ("energy_kj", "energy_kcal", "fat_total", "carbs_total", "protein")):
        errors.append("all_zero_produce_nutrition")
    mass = ("fat_total", "carbs_total", "protein", "salt")
    if all(n.get(k) is not None for k in mass) and sum(n[k] for k in mass) > 102:
        errors.append("macronutrient_mass_exceeds_food")
    return errors


def same_data(left, right):
    return bool(left and right) and all(left[k] == right[k] for k in ("product", "nutrition"))


def eligible(row):
    if not row or not row.get("nutrition"):
        return "missing_target_or_nutrition"
    p, n = row["product"], row["nutrition"]
    if n.get("nutrition_manual_edit"):
        return "manual_nutrition_protected"
    if p.get("needs_enrichment") is not True or p.get("enrichment_reviewed"):
        return "no_longer_in_enrichment_queue"
    if row.get("available") is not True:
        return "latest_scraped_availability_not_true"
    return None


def plan(entry, target, source, calculator, estimator):
    result = {"product_changes": {}, "nutrition_changes": {}, "status": "skipped",
              "reason": None, "complete": False}
    reason = eligible(target)
    if reason:
        result["reason"] = reason
        return result
    for role, current in (("target", target), ("source", source)):
        if not same_data(current, entry["original"][role]):
            result["reason"] = role + "_changed_since_review"
            return result
    n, old, p = source["nutrition"] or {}, target["nutrition"], target["product"]
    if source["product"].get("nutrition_source") != "usda_api":
        result["reason"] = "source_origin_not_usda"
        return result
    errors = invalid_nutrients(n)
    if errors:
        result["reason"] = ";".join(errors)
        return result
    available = {k: n[k] for k in CORE if n.get(k) is not None}
    if not available:
        result["reason"] = "no_valid_source_nutrients"
        return result
    complete = all(n.get(k) is not None for k in CORE)
    merged = dict(old, **available)
    if invalid_nutrients(merged):
        result["reason"] = "source_and_retained_target_values_conflict"
        return result
    # Missing Rimi nutrients never clear a target value. Partial data stays flagged.
    fiber, _, fiber_origin = resolve_fiber(p, old, None, p["name"], estimator)
    scores = {"nutri_score_grade": None, "nutri_score_points": None}
    score_inputs = ("energy_kj", "carbs_sugars", "fat_saturated", "salt", "protein", "fat_total")
    valid_fiber = (isinstance(fiber, (int, float)) and math.isfinite(fiber) and 0 <= fiber <= 100)
    if valid_fiber and all(merged.get(k) is not None for k in score_inputs):
        score = calculator.calculate_single_product(
            energy_kj=merged["energy_kj"], sugars=merged["carbs_sugars"],
            saturated_fat=merged["fat_saturated"], salt=merged["salt"],
            protein=merged["protein"], fiber=fiber, total_fat=merged["fat_total"],
            category_id=p["category_id"], product_name=p["name"],
            ingredients_text=p.get("ingredients") or old.get("ingredients_text"),
        )
        if not score or not score.get("success"):
            result["reason"] = "nutriscore_calculation_failed"
            return result
        scores = {"nutri_score_grade": score["grade"], "nutri_score_points": score["score"]}
    desired = dict(available, **scores, usda_fdc_id=n.get("usda_fdc_id"))
    result.update(
        status="ready", complete=complete,
        fiber_for_scoring={"value": fiber, **fiber_origin},
        product_changes={k: v for k, v in {
            "nutrition_source": "usda_api", "needs_enrichment": not complete
        }.items() if p.get(k) != v},
        nutrition_changes={k: v for k, v in desired.items() if old.get(k) != v},
        missing_source_fields=[k for k in CORE if n.get(k) is None],
        score_unavailable=scores["nutri_score_grade"] is None,
    )
    allowlist(result)
    if not result["product_changes"] and not result["nutrition_changes"]:
        result["status"] = "unchanged"
    return result


def seal(manifest):
    manifest["sha256"] = digest({k: v for k, v in manifest.items() if k != "sha256"})
    return manifest


def validate_manifest(manifest):
    if manifest.get("sha256") != digest({k: v for k, v in manifest.items() if k != "sha256"}):
        raise ValueError("Manifest fingerprint mismatch")
    if manifest.get("basis") != "user_confirmed_per_100g_edible_food":
        raise ValueError("Unconfirmed nutrition basis")
    rows = manifest["rows"]
    if len(rows) != 190 or len({r["approved"]["target_product_id"] for r in rows}) != 190:
        raise ValueError("Manifest must contain all 190 approved targets")
    for row in rows:
        allowlist(row["proposal"])
        for role in ("target", "source"):
            if row["baseline"][role] and str(row["baseline"][role]["product"]["product_id"]) != row["approved"][role + "_product_id"]:
                raise ValueError("Manifest identity mismatch")
