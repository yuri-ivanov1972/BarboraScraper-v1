"""Database target guards, read-only snapshots and transactional CAS apply."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extensions import parse_dsn
from psycopg2.extras import RealDictCursor
from psycopg2 import sql

from nutrition_reload_plan import assert_allowlist, digest


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def database_target(production, confirm_production=False, env=None):
    env = os.environ if env is None else env
    if confirm_production and not production:
        raise ValueError("Production confirmation requires --production")
    key = "PROD_DATABASE_URL" if production else "DATABASE_URL"
    if production and not confirm_production:
        raise ValueError("Production requires --production --confirm-production")
    if not env.get(key):
        raise ValueError("Required database secret is not configured")
    def identity(dsn):
        try:
            values = parse_dsn(dsn)
            return [values.get("host", "").rstrip(".").lower(),
                    str(values.get("port", "5432")), values.get("dbname", "")]
        except Exception:
            raise ValueError("Invalid database target configuration") from None
    target = identity(env[key])
    if production and env.get("DATABASE_URL") and target == identity(env["DATABASE_URL"]):
        raise ValueError("Development and production targets must differ")
    return env[key], digest(target)


def connect(dsn, readonly):
    try:
        conn = psycopg2.connect(dsn, connect_timeout=15)
        conn.set_session(readonly=readonly, isolation_level="REPEATABLE READ" if readonly else "READ COMMITTED")
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute("SET LOCAL lock_timeout = '5s'")
        return conn
    except Exception:
        raise RuntimeError("Database connection unavailable; no sensitive diagnostics logged") from None


def verify_schema(conn):
    required = {
        "products": {"product_id", "sku", "name", "name_norm", "barbora_url", "category_id",
                     "name_manual_edit", "needs_enrichment", "nutrition_source",
                     "enrichment_reviewed", "enrichment_skipped", "updated_at", "ingredients",
                     "rimi_category_code"},
        "nutritionfacts": {"product_id", "nutrition_manual_edit", "energy_kj", "energy_kcal",
                           "fat_total", "fat_saturated", "carbs_total", "carbs_sugars",
                           "protein", "salt", "fiber", "ingredients_text", "usda_fdc_id",
                           "is_fiber_correct", "data_source_date",
                           "nutri_score_grade", "nutri_score_points"},
        "normalized_categories": {"category_id", "normalized_category", "parent_category_id",
                                 "barbora_category_code"},
    }
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name=ANY(%s)
        """, (list(required),))
        found = {}
        for table, column in cur.fetchall():
            found.setdefault(table, set()).add(column)
        if any(columns - found.get(table, set()) for table, columns in required.items()):
            raise ValueError("Target schema does not support the reload; no migrations were attempted")


def capture(conn, target_hash, production, limit=None):
    verify_schema(conn)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            WITH RECURSIVE paths AS (
                SELECT category_id, normalized_category::text AS path,
                       ARRAY[category_id] AS ancestry
                FROM public.normalized_categories WHERE parent_category_id IS NULL
                UNION ALL
                SELECT nc.category_id, paths.path || '/' || nc.normalized_category,
                       paths.ancestry || nc.category_id
                FROM public.normalized_categories nc
                JOIN paths ON nc.parent_category_id=paths.category_id
                WHERE NOT nc.category_id=ANY(paths.ancestry)
            )
            SELECT to_jsonb(p) AS product, to_jsonb(nf) AS nutrition,
                   paths.path AS category_path
            FROM public.products p
            LEFT JOIN public.nutritionfacts nf ON nf.product_id=p.product_id
            LEFT JOIN paths ON paths.category_id=p.category_id
            WHERE p.needs_enrichment IS TRUE
              AND COALESCE(p.enrichment_reviewed,FALSE)=FALSE
            ORDER BY COALESCE(p.enrichment_skipped,FALSE), p.product_id
            LIMIT %s
        """, (limit,))
        rows = [dict(row, candidate=None, proposal=None, outcome=None) for row in cur.fetchall()]
    return {"version": 1, "target": "production" if production else "development",
            "target_hash": target_hash, "captured_at": utcnow(), "preview_complete": False,
            "rows": rows}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(data, out, ensure_ascii=False, allow_nan=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def update_values(cur, table, product_id, changes, timestamp=None):
    assignments = [sql.SQL("{}=%s").format(sql.Identifier(field)) for field in changes]
    if timestamp:
        assignments.append(sql.SQL("{}=CURRENT_TIMESTAMP").format(sql.Identifier(timestamp)))
    query = sql.SQL("UPDATE public.{} SET {} WHERE product_id=%s").format(
        sql.Identifier(table), sql.SQL(", ").join(assignments)
    )
    cur.execute(query, list(changes.values()) + [product_id])
    if cur.rowcount != 1:
        raise ValueError("Unexpected update count")


def apply_one(conn, row):
    """No network requests, allowlisted writes and baseline rechecks under locks."""
    proposal = row["proposal"]
    if not proposal or not (proposal["product_changes"] or proposal["nutrition_changes"]):
        return "no_changes"
    assert_allowlist(proposal)
    product_id = row["product"]["product_id"]
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL lock_timeout='5s'")
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SELECT to_jsonb(p) AS value FROM public.products p WHERE product_id=%s FOR UPDATE",
                        (product_id,))
            current = cur.fetchone()
            if current is None:
                conn.rollback()
                return "product_removed"
            cur.execute("SELECT to_jsonb(nf) AS value FROM public.nutritionfacts nf WHERE product_id=%s FOR UPDATE",
                        (product_id,))
            nutrition = cur.fetchone()
            current_nutrition = nutrition["value"] if nutrition else None
            p = current["value"]
            pc, nc = proposal["product_changes"], proposal["nutrition_changes"]
            expected_product = dict(row["product"], **pc)
            expected_nutrition = dict(row["nutrition"] or {}, **nc) if nc else row["nutrition"]
            if row["nutrition"] is None and nc:
                # New nutrition rows have schema defaults as well as assigned
                # fields. Compare just the insert fields plus identity below.
                expected_nutrition = dict(nc, product_id=product_id)
            def comparable(value, ignored):
                return {k: v for k, v in (value or {}).items() if k not in ignored}
            expected_p = comparable(expected_product, {"updated_at"})
            current_p = comparable(p, {"updated_at"})
            if row["nutrition"] is None and nc and current_nutrition:
                current_n = {k: current_nutrition.get(k) for k in expected_nutrition}
                expected_n = expected_nutrition
                if current_nutrition.get("nutrition_manual_edit"):
                    current_n = None
            else:
                current_n = comparable(current_nutrition, {"data_source_date"})
                expected_n = comparable(expected_nutrition, {"data_source_date"})
            if digest(expected_p) == digest(current_p) and digest(expected_n) == digest(current_n):
                conn.rollback()
                return "already_applied_or_matches_approved_state"
            # Reject any edits since approval, even changes outside our write scope.
            if digest(p) != digest(row["product"]) or digest(current_nutrition) != digest(row["nutrition"]):
                conn.rollback()
                return "baseline_changed"
            if not p["needs_enrichment"] or p.get("enrichment_reviewed"):
                conn.rollback()
                return "no_longer_eligible"
            if ("name" in pc and p.get("name_manual_edit")) or (
                    nc and (current_nutrition or {}).get("nutrition_manual_edit")):
                conn.rollback()
                return "manual_edit_protected"
            if pc:
                update_values(cur, "products", product_id, pc, "updated_at")
            if nc:
                full_refresh = proposal["nutrition_status"] == "complete"
                if current_nutrition is None:
                    columns = ["product_id"] + list(nc) + ["data_source_date"]
                    cur.execute(
                        sql.SQL("INSERT INTO public.nutritionfacts ({}) VALUES ({},CURRENT_TIMESTAMP)").format(
                            sql.SQL(",").join(map(sql.Identifier, columns)),
                            sql.SQL(",").join(sql.Placeholder() for _ in range(len(columns)-1))
                        ), [product_id] + list(nc.values())
                    )
                else:
                    update_values(cur, "nutritionfacts", product_id, nc,
                                  "data_source_date" if full_refresh else None)
        conn.commit()
        return "updated"
    except Exception:
        conn.rollback()
        # Exception text may include DSNs, SQL parameters or connection metadata.
        return "apply_failed"
