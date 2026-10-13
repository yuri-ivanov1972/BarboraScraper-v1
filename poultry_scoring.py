"""Approval-gated scoring of the two recovered preparations; no broad backfill.

CLI preview is read-only. Apply requires the exact reviewed manifest checksum.
Source evidence and limitations are documented in docs/poultry-scoring-result.md.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fiber_estimator import FiberEstimator
from ingredient_processor import extract_ingredient_tokens
from nutrition_reload_plan import FIELDS, digest, resolve_fiber
from nutriscore_calculator import NutriscoreCalculator
from nova_calculator import _assign_nova_score, calculate_nova, usable_analysis
from product_refresh_source import ProductRefreshSource
from product_refresh_store import (
    RefreshError, _update, capture, connect, database_identity, policy_hash,
    persist_ingredients,
)

TARGETS = {12984: "000000000001315297", 12985: "000000000001286881"}
REFERENCE_SKUS = ("987816", "813665")
RIMI_CATEGORY = 78
MAX_AGE_SECONDS = 1800


def reference_snapshot(dsn):
    """Verify actual Rimi IDs, defaults and preparation examples, SELECT-only."""
    conn = connect(dsn, True)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT to_jsonb(c) FROM normalized_categories c
                WHERE category_id=%s
            """, (RIMI_CATEGORY,))
            row = cur.fetchone()
            category = row[0] if row else {}
            if (category.get("rimi_category_code") != "SH-6-11"
                    or category.get("name_lv") != "Dažādu veidu maltā gaļa"
                    or category.get("nova_score") != 1):
                raise RefreshError("Rimi reference category changed; re-investigate before approval.")
            cur.execute("""
                SELECT p.sku,p.category_id,n.ingredients_text,n.fiber,n.is_fiber_correct
                FROM products p JOIN nutritionfacts n USING(product_id)
                WHERE p.sku=ANY(%s) ORDER BY p.sku
            """, (list(REFERENCE_SKUS),))
            preparations = [list(r) for r in cur.fetchall()]
            if (len(preparations) != 2
                    or any(r[1] != RIMI_CATEGORY or r[3] != 0 or r[4] is not False
                           for r in preparations)
                    or any("aromatizētāji" not in (r[2] or "") for r in preparations)):
                raise RefreshError("Rimi preparation evidence changed; no mapping proposed.")
            # JSON-safe numeric conversion; no connection information in manifest.
            for row in preparations:
                row[3] = float(row[3])
            return {"category": category, "preparations": preparations}
    finally:
        conn.rollback()
        conn.close()


def analysis_context(conn, snapshots):
    tokens = sorted({token for s in snapshots for token in extract_ingredient_tokens(
        (s.get("nutrition") or {}).get("ingredients_text") or s["product"].get("ingredients") or "")})
    with conn.cursor() as cur:
        cur.execute("SELECT to_jsonb(i) FROM ingredient_analysis i WHERE ingredient=ANY(%s) ORDER BY id",
                    (tokens,))
        ingredients = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT nova_score FROM rimi_nova_categories WHERE rimi_category_code=%s",
                    (RIMI_CATEGORY,))
        row = cur.fetchone()
        if not row or row[0] != 1:
            raise RefreshError("Local Rimi default differs from verified source; no changes saved.")
    return {"ingredients": ingredients, "category_nova": row[0]}


def scoring_plan(snapshot, context, calculator, estimator):
    p, n = snapshot["product"], snapshot.get("nutrition") or {}
    if TARGETS.get(p["product_id"]) != p["sku"] or p["category_id"] != 352:
        raise RefreshError("Recovered product identity/category changed.")
    text = n.get("ingredients_text") or p.get("ingredients") or ""
    tokens = sorted(set(extract_ingredient_tokens(text)))
    known = {r["ingredient"]: r for r in context["ingredients"]}
    analysis = [known.get(t, {}) for t in tokens]
    changes, nutrition = {}, {}
    # This category mapping is supported by the checked product/preparation
    # evidence, not inferred from the broad parent "fresh poultry".
    if p.get("rimi_category_code") not in {None, RIMI_CATEGORY}:
        raise RefreshError("Existing Rimi mapping differs; explicit re-review required.")
    changes["rimi_category_code"] = RIMI_CATEGORY
    if not n.get("nutrition_manual_edit"):
        fiber, correct, origin = resolve_fiber(
            dict(p, rimi_category_code=RIMI_CATEGORY), n, None, p["name"], estimator)
        if fiber is not None and origin["kind"] in {"category", "exception"}:
            nutrition.update(fiber=fiber, is_fiber_correct=correct)
        score = {"nutri_score_grade": None, "nutri_score_points": None}
        if fiber is not None and all(n.get(k) is not None for k in FIELDS if k != "fiber"):
            result = calculator.calculate_single_product(
                energy_kj=n["energy_kj"], sugars=n["carbs_sugars"],
                saturated_fat=n["fat_saturated"], salt=n["salt"], protein=n["protein"],
                fiber=fiber, total_fat=n["fat_total"], category_id=p["category_id"],
                product_name=p["name"], ingredients_text=text)
            if not result.get("success"):
                raise RefreshError("Nutri-Score calculation failed.")
            score.update(nutri_score_grade=result["grade"], nutri_score_points=result["score"])
        nutrition.update(score)
    if p.get("nova_source") != "manual_override":
        score, source, reason = calculate_nova(analysis, context["category_nova"])
        # Do not inherit the raw-meat group-1 default for these preparations.
        if source == "category_inherited":
            score, source, reason = None, None, "unsupported_preparation_default"
        changes.update(nova_score=score, nova_source=source)
    else:
        reason = "manual_override"
    protected_text = p.get("name_manual_edit") or n.get("nutrition_manual_edit")
    return {
        "product_changes": {k: v for k, v in changes.items() if p.get(k) != v},
        "nutrition_changes": {k: v for k, v in nutrition.items() if n.get(k) != v},
        "ingredient_tokens": tokens if not protected_text else None,
        "pending": [t for t in tokens if not usable_analysis(known.get(t, {}))],
        "nova_reason": reason,
        "manual_ingredients_protected": bool(protected_text),
    }


def scoring_policy():
    return digest([policy_hash(), Path(__file__).read_text(),
                   Path("combined_ingredient_analyzer.py").read_text()])


def prepare(dsn, rimi_dsn, source=None):
    reference = reference_snapshot(rimi_dsn)
    conn = connect(dsn, True)
    try:
        snapshots = [capture(conn, pid) for pid in sorted(TARGETS)]
        candidates = [(source or ProductRefreshSource()).product(s) for s in snapshots]
        for s, candidate in zip(snapshots, candidates):
            n = s["nutrition"] or {}
            if (candidate["sku"] != s["product"]["sku"]
                    or candidate.get("ingredients") != n.get("ingredients_text")
                    or any(candidate.get("nutrition", {}).get(k) != n.get(k)
                           for k in FIELDS if k != "fiber")):
                raise RefreshError("Accepted inputs differ from fresh Barbora source; review a product refresh first.")
        context = analysis_context(conn, snapshots)
        estimator = FiberEstimator()
        if estimator.category_defaults.get(RIMI_CATEGORY) != 0:
            raise RefreshError("Verified fiber default changed; re-review required.")
        preview = {"database": database_identity(dsn), "reference": reference,
                   "snapshots": snapshots, "context": context, "candidates": candidates,
                   "plans": [scoring_plan(s, context, NutriscoreCalculator(conn), estimator)
                             for s in snapshots],
                   "policy": scoring_policy(), "fetched_at": datetime.now(timezone.utc).isoformat()}
        preview["sha256"] = digest(preview)
        return preview
    finally:
        conn.rollback()
        conn.close()


def apply(preview, approved_sha256, dsn, rimi_dsn):
    payload = {k: v for k, v in preview.items() if k != "sha256"}
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(preview["fetched_at"])).total_seconds()
    if (digest(payload) != preview["sha256"] or approved_sha256 != preview["sha256"]
            or preview["database"] != database_identity(dsn)
            or preview["policy"] != scoring_policy() or not 0 <= age <= MAX_AGE_SECONDS):
        raise RefreshError("Approval manifest is changed or expired; generate a fresh preview.")
    if reference_snapshot(rimi_dsn) != preview["reference"]:
        raise RefreshError("Reference data changed; generate a fresh preview.")
    conn = connect(dsn, False)
    try:
        snapshots = [capture(conn, pid, lock=True) for pid in sorted(TARGETS)]
        context = analysis_context(conn, snapshots)
        plans = [scoring_plan(s, context, NutriscoreCalculator(conn), FiberEstimator()) for s in snapshots]
        if snapshots != preview["snapshots"] or context != preview["context"] or plans != preview["plans"]:
            raise RefreshError("Product, manual protection or ingredient analysis changed; re-preview.")
        for snapshot, plan in zip(snapshots, plans):
            p = snapshot["product"]
            with conn.cursor() as cur:
                _update(cur, "products", p["product_id"], plan["product_changes"])
                _update(cur, "nutritionfacts", p["product_id"], plan["nutrition_changes"])
                if plan["ingredient_tokens"] is not None:
                    persist_ingredients(cur, p["sku"], plan["ingredient_tokens"])
            # Use the actual existing completion scoring path, in this same
            # transaction. Do not overwrite a protected NOVA result.
            if plan["nova_reason"] != "unsupported_preparation_default":
                result = _assign_nova_score(conn, p["product_id"])
                expected = dict(p, **plan["product_changes"])
                if (result["nova_score"], result["nova_source"]) != (
                        expected["nova_score"], expected["nova_source"]):
                    raise RefreshError("Completion result differs from approved preview.")
        conn.commit()
        return {"updated_products": list(sorted(TARGETS)), "approved_sha256": approved_sha256}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", required=True, help="Manifest path (use generated-artifacts/)")
    parser.add_argument("--apply-approved-sha256")
    args = parser.parse_args()
    try:
        dsn, rimi = os.environ["PROD_DATABASE_URL"], os.environ["RIMI_DATABASE_URL"]
        path = Path(args.preview)
        if args.apply_approved_sha256:
            print(json.dumps(apply(json.loads(path.read_text()), args.apply_approved_sha256, dsn, rimi)))
        else:
            preview = prepare(dsn, rimi)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(preview, ensure_ascii=False, indent=2))
            print(json.dumps({"sha256": preview["sha256"], "plans": preview["plans"]}, ensure_ascii=False))
    except Exception:
        raise SystemExit("Scoring stopped. No partial changes saved; check inputs and generate a new preview.") from None


if __name__ == "__main__":
    main()
