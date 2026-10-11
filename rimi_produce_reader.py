"""Bounded, repeatable, SELECT-only production/reference catalogue snapshots."""

import hashlib
import json
import os
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

from enrichment_availability import QUEUE_ELIGIBLE_SQL

ROOTS = {"barbora": 1, "rimi": 6}
KEYS = {"barbora": "PROD_DATABASE_URL", "rimi": "RIMI_DATABASE_URL"}


def capture(role, env=None):
    """No configurable write mode, schema setup, cache access, or API clients."""
    if role not in ROOTS:
        raise ValueError("Unknown catalogue role")
    env = os.environ if env is None else env
    if not env.get(KEYS[role]):
        raise RuntimeError(f"{KEYS[role]} is unavailable to runtime")
    conn = None
    try:
        conn = psycopg2.connect(env[KEYS[role]], connect_timeout=15)
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SHOW transaction_read_only")
            if cur.fetchone()["transaction_read_only"] != "on":
                raise RuntimeError("Read-only session not established")
            cur.execute("""
                SELECT category_id,name_lv,name_en,parent_category_id,level
                FROM public.normalized_categories ORDER BY category_id
            """)
            categories = [dict(row) for row in cur.fetchall()]
            root = next((c for c in categories if c["category_id"] == ROOTS[role]), None)
            if not root or root["name_lv"].casefold() != "augļi un dārzeņi":
                raise RuntimeError("Expected produce category root was not verified")
            predicate = QUEUE_ELIGIBLE_SQL if role == "barbora" else "TRUE"
            cur.execute(f"""
                WITH RECURSIVE scope AS (
                    SELECT category_id, name_lv::text AS category_path,
                           ARRAY[category_id] AS ancestry
                    FROM public.normalized_categories WHERE category_id=%s
                    UNION ALL
                    SELECT c.category_id, s.category_path || ' / ' || c.name_lv,
                           s.ancestry || c.category_id
                    FROM public.normalized_categories c
                    JOIN scope s ON c.parent_category_id=s.category_id
                    WHERE NOT c.category_id=ANY(s.ancestry)
                )
                SELECT to_jsonb(p) AS product, to_jsonb(nf) AS nutrition,
                       s.category_path, s.ancestry,
                       h.is_available AS available, h.recorded_at AS availability_at
                FROM public.products p JOIN scope s ON p.category_id=s.category_id
                LEFT JOIN public.nutritionfacts nf ON nf.product_id=p.product_id
                LEFT JOIN LATERAL (
                    SELECT is_available,recorded_at FROM public.product_price_history ph
                    WHERE ph.product_id=p.product_id
                    ORDER BY recorded_at DESC,price_history_id DESC LIMIT 1
                ) h ON TRUE
                WHERE {predicate}
                ORDER BY p.product_id LIMIT 10001
            """, (ROOTS[role],))
            rows = [dict(row) for row in cur.fetchall()]
            if len(rows) > 10000:
                raise RuntimeError("Catalogue exceeds bounded snapshot limit")
            if len({r["product"]["product_id"] for r in rows}) != len(rows):
                raise RuntimeError("Duplicate product rows; report would be ambiguous")
            for row in rows:
                if row["availability_at"] is not None:
                    row["availability_at"] = row["availability_at"].isoformat()
            # Server-enforced read-only transaction protects every catalogue field,
            # including flags, fiber, manual edits, scores, dates and cache tables.
            return {
                "role": role, "root_id": ROOTS[role], "read_only": True,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "categories": categories, "rows": rows,
                "rows_sha256": hashlib.sha256(
                    json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
            }
    except Exception:
        # Connection failures can contain credentials; do not propagate their text.
        raise RuntimeError(f"{role} read-only snapshot failed; no sensitive diagnostics logged") from None
    finally:
        if conn is not None:
            conn.rollback()
            conn.close()
