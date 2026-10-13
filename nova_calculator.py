"""NOVA rules shared by refresh previews and analysis-completion writes."""

import logging

from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def calculate_nova(ingredients, category_score):
    """Return (score, source, reason); unknown is not evidence of clean food."""
    if any(i.get("suspicion_level") in {"avoid", "limit"} for i in ingredients):
        return 4, "additive_override", "additive"
    for ingredient in ingredients:
        natural = (ingredient.get("category") == "natural"
                   and ingredient.get("is_processed") is False)
        classified = (ingredient.get("is_processed") is True
                      and ingredient.get("suspicion_level") in {"clean", "caution", "none"})
        if not (natural or classified):
            return None, None, "pending_analysis"
    if category_score in {1, 2, 3, 4}:
        return category_score, "category_inherited", "category"
    return None, None, "no_category"


def _assign_nova_score(conn, product_id, changed_ingredient_ids=None):
    """Caller owns commit/rollback. Lock before reading current mappings/category."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT product_id,sku,nova_score,nova_source,rimi_category_code
            FROM products WHERE product_id=%s FOR UPDATE
        """, (product_id,))
        product = cur.fetchone()
        if product is None:
            return {"nova_score": None, "nova_source": None, "updated": False,
                    "reason": "missing_product"}
        result = {"nova_score": product["nova_score"], "nova_source": product["nova_source"],
                  "updated": False}
        # Discovery can precede a concurrent refresh removing a mapping. Recheck
        # after acquiring the product lock; never act on the captured old list.
        if changed_ingredient_ids is not None:
            cur.execute("""
                SELECT 1 FROM ingredient_product_mapping
                WHERE product_sku=%s AND ingredient_id=ANY(%s) LIMIT 1
            """, (product["sku"], changed_ingredient_ids))
            if cur.fetchone() is None:
                return dict(result, reason="mapping_removed")
        if product["nova_source"] == "manual_override":
            return dict(result, reason="manual_override")
        cur.execute("""
            SELECT ia.* FROM ingredient_product_mapping ipm
            LEFT JOIN ingredient_analysis ia ON ia.id=ipm.ingredient_id
            WHERE ipm.product_sku=%s
        """, (product["sku"],))
        ingredients = list(cur.fetchall())
        cur.execute("SELECT nova_score FROM rimi_nova_categories WHERE rimi_category_code=%s",
                    (product["rimi_category_code"],))
        category = cur.fetchone()
        score, source, reason = calculate_nova(
            ingredients, category["nova_score"] if category else None)
        # NULL-safe comparison makes repeated completion events true no-ops.
        cur.execute("""
            UPDATE products SET nova_score=%s,nova_source=%s
            WHERE product_id=%s AND nova_source IS DISTINCT FROM 'manual_override'
              AND (nova_score IS DISTINCT FROM %s OR nova_source IS DISTINCT FROM %s)
        """, (score, source, product_id, score, source))
        return {"nova_score": score, "nova_source": source,
                "updated": cur.rowcount > 0, "reason": reason}


def recalculate_linked_products(conn, ingredient_ids):
    """Target current links only; errors propagate so analysis and NOVA roll back."""
    ids = sorted(set(ingredient_ids))
    if not ids:
        return []
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT p.product_id FROM products p
            WHERE EXISTS (
                SELECT 1 FROM ingredient_product_mapping ipm
                WHERE ipm.product_sku=p.sku AND ipm.ingredient_id=ANY(%s)
            ) ORDER BY p.product_id
        """, (ids,))
        product_ids = [p["product_id"] for p in cur.fetchall()]
    return [_assign_nova_score(conn, pid, ids) for pid in product_ids]


def assign_nova_score(conn, product_id: int, sku: str) -> dict:
    """Compatibility entry point for scraping/UI: owns commit, never raises."""
    try:
        result = _assign_nova_score(conn, product_id)
        conn.commit()  # Also releases locks on no-op/manual paths.
        return result
    except Exception:
        logger.error("NOVA assignment failed for product_id=%s", product_id)
        conn.rollback()
        return {"nova_score": None, "nova_source": None, "updated": False, "reason": "error"}
