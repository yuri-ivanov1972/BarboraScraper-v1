"""
nova_calculator.py — Automatic NOVA score assignment for individual products.

Called automatically after ingredient analysis completes for a newly scraped product.
Implements the same two-pass logic as populate_nova.py but for a single product.

Usage (from other modules):
    from nova_calculator import assign_nova_score
    result = assign_nova_score(conn, product_id, sku)
    # result = {'nova_score': 4, 'nova_source': 'additive_override', 'updated': True}
"""

import logging

logger = logging.getLogger(__name__)


def assign_nova_score(conn, product_id: int, sku: str) -> dict:
    """
    Assign a NOVA score to a single product using the two-pass rule.

    Pass 1 — Additive override:
        If the product has any ingredient with suspicion_level IN ('avoid', 'limit'),
        set nova_score=4, nova_source='additive_override'.

    Pass 2 — Category fallback:
        Otherwise, look up nova_score from rimi_nova_categories via
        products.rimi_category_code → nova_source='category_inherited'.

    Rules:
        - Skips products where nova_source = 'manual_override'.
        - Catches all exceptions — never raises.
        - Commits its own changes (does NOT rely on caller to commit).

    Args:
        conn:       Active psycopg2 connection to the Barbora database.
        product_id: products.product_id of the target product.
        sku:        products.sku (used for logging only).

    Returns:
        dict with keys:
            nova_score  (int | None)
            nova_source (str | None)
            updated     (bool) — False if skipped or no score found
    """
    try:
        with conn.cursor() as cur:
            # Skip manual overrides
            cur.execute(
                "SELECT nova_source FROM products WHERE product_id = %s",
                (product_id,),
            )
            row = cur.fetchone()
            if row is None:
                logger.warning("assign_nova_score: product_id=%s not found", product_id)
                return {"nova_score": None, "nova_source": None, "updated": False}

            # Support both dict-like (RealDictCursor) and tuple cursors
            current_source = row["nova_source"] if hasattr(row, "__getitem__") and "nova_source" in row else row[0]
            if current_source == "manual_override":
                logger.debug("assign_nova_score: SKU %s is manual_override — skipping", sku)
                return {"nova_score": None, "nova_source": "manual_override", "updated": False}

            # Pass 1 — Additive override
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM ingredient_product_mapping ipm
                    JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
                    WHERE ipm.product_sku = %s
                      AND ia.suspicion_level IN ('avoid', 'limit')
                )
                """,
                (sku,),
            )
            has_bad_additive = cur.fetchone()
            has_bad_additive = (
                has_bad_additive["exists"]
                if hasattr(has_bad_additive, "__getitem__") and "exists" in has_bad_additive
                else has_bad_additive[0]
            )

            if has_bad_additive:
                cur.execute(
                    "UPDATE products SET nova_score = 4, nova_source = 'additive_override' "
                    "WHERE product_id = %s",
                    (product_id,),
                )
                conn.commit()
                logger.info("assign_nova_score: SKU %s → NOVA 4 (additive_override)", sku)
                return {"nova_score": 4, "nova_source": "additive_override", "updated": True}

            # Pass 2 — Category fallback
            cur.execute(
                """
                SELECT rnc.nova_score
                FROM products p
                JOIN rimi_nova_categories rnc
                  ON rnc.rimi_category_code = p.rimi_category_code
                WHERE p.product_id = %s
                """,
                (product_id,),
            )
            cat_row = cur.fetchone()
            if cat_row is not None:
                cat_score = cat_row["nova_score"] if hasattr(cat_row, "__getitem__") and "nova_score" in cat_row else cat_row[0]
                if cat_score is not None:
                    cur.execute(
                        "UPDATE products SET nova_score = %s, nova_source = 'category_inherited' "
                        "WHERE product_id = %s",
                        (cat_score, product_id),
                    )
                    conn.commit()
                    logger.info(
                        "assign_nova_score: SKU %s → NOVA %s (category_inherited)", sku, cat_score
                    )
                    return {"nova_score": cat_score, "nova_source": "category_inherited", "updated": True}

        logger.debug("assign_nova_score: SKU %s — no NOVA score found (no category match)", sku)
        return {"nova_score": None, "nova_source": None, "updated": False}

    except Exception as exc:
        logger.error("assign_nova_score: SKU %s — error: %s", sku, exc)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"nova_score": None, "nova_source": None, "updated": False}
