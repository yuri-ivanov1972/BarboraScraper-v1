"""Shared predicates for the available-only enrichment queue (products alias p)."""

LATEST_AVAILABLE_SQL = """(
    SELECT history.is_available
    FROM product_price_history history
    WHERE history.product_id = p.product_id
    ORDER BY history.recorded_at DESC, history.price_history_id DESC
    LIMIT 1
) IS TRUE"""

QUEUE_ELIGIBLE_SQL = f"""p.needs_enrichment IS TRUE
    AND COALESCE(p.enrichment_reviewed, FALSE) = FALSE
    AND {LATEST_AVAILABLE_SQL}"""
