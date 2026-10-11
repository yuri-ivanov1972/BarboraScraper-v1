"""Bounded reads and narrow compare-and-swap transactions; no schema/cache writes."""

import os
from pathlib import Path

from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import parse_dsn

from nutrition_reload_plan import digest
from nutrition_reload_store import connect, database_target, utcnow, write_json
from rimi_nutrition_import_plan import allowlist, eligible, same_data


def connections():
    """Production only, with distinct source and destination database identities."""
    dsn, fingerprint = database_target(True, True)
    source = os.environ.get("RIMI_DATABASE_URL")
    if not source:
        raise ValueError("Rimi connection unavailable")
    def identity(value):
        info = parse_dsn(value)
        return [info.get("host", "").lower().rstrip("."), info.get("port", "5432"), info.get("dbname")]
    try:
        source_hash = digest(identity(source))
        if identity(source) == identity(dsn):
            raise ValueError()
    except Exception:
        raise ValueError("Source and production target must be distinct valid databases") from None
    return dsn, source, fingerprint, source_hash


def read_rows(conn, ids, lock=False):
    if not ids or len(ids) > 190 or len(set(ids)) != len(ids):
        raise ValueError("Read requires 1–190 distinct approved IDs")
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if lock:
            cur.execute("SELECT product_id FROM public.products WHERE product_id=ANY(%s) ORDER BY product_id FOR UPDATE", (ids,))
            cur.execute("SELECT product_id FROM public.nutritionfacts WHERE product_id=ANY(%s) ORDER BY product_id FOR UPDATE", (ids,))
        cur.execute("""
            SELECT to_jsonb(p) AS product,to_jsonb(n) AS nutrition,
                   h.is_available AS available
            FROM public.products p
            LEFT JOIN public.nutritionfacts n ON n.product_id=p.product_id
            LEFT JOIN LATERAL (
                SELECT is_available FROM public.product_price_history
                WHERE product_id=p.product_id
                ORDER BY recorded_at DESC,price_history_id DESC LIMIT 1
            ) h ON TRUE
            WHERE p.product_id=ANY(%s) ORDER BY p.product_id
        """, (ids,))
        rows = [dict(r) for r in cur.fetchall()]
    if len(rows) != len({r["product"]["product_id"] for r in rows}):
        raise ValueError("Duplicate nutrition rows")
    return {str(r["product"]["product_id"]): r for r in rows}


def category_state(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_jsonb(c) FROM public.normalized_categories c ORDER BY category_id")
        return digest([r[0] for r in cur.fetchall()])


def update(cur, table, pid, values):
    """Identifiers are static/allowlisted by caller; parameterized values only."""
    if not values:
        return
    fields = list(values)
    query = sql.SQL("UPDATE public.{} SET {} WHERE product_id=%s").format(
        sql.Identifier(table),
        sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(k)) for k in fields))
    cur.execute(query, [values[k] for k in fields] + [pid])
    if cur.rowcount != 1:
        raise ValueError("Expected exactly one updated row")


def after_matches(current, before, proposal):
    """Crash/retry detection includes every non-timestamp field, not just nutrients."""
    if not current or not before:
        return False
    for role, changes, timestamp in (
        ("product", proposal["product_changes"], "updated_at"),
        ("nutrition", proposal["nutrition_changes"], "data_source_date"),
    ):
        expected = dict(before[role], **changes)
        actual = dict(current[role] or {})
        expected.pop(timestamp, None)
        actual.pop(timestamp, None)
        if expected != actual:
            return False
    return True


def apply_one(conn, source_conn, entry, receipt_path, expected_categories):
    proposal = entry["proposal"]
    allowlist(proposal)
    if proposal["status"] != "ready":
        return {"status": proposal["status"], "reason": proposal.get("reason")}
    pid = int(entry["approved"]["target_product_id"])
    sid = int(entry["approved"]["source_product_id"])
    try:
        # New read-only source transaction for each product; no stale long-lived snapshot.
        source_conn.rollback()
        source = read_rows(source_conn, [sid]).get(str(sid))
        source_conn.rollback()
        if not same_data(source, entry["baseline"]["source"]):
            return {"status": "skipped", "reason": "source_changed_since_preview"}
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='30s'")
            cur.execute("SET LOCAL lock_timeout='5s'")
        current = read_rows(conn, [pid], lock=True).get(str(pid))
        if current and after_matches(current, entry["baseline"]["target"], proposal):
            conn.rollback()
            return {"status": "already_applied"}
        reason = eligible(current)
        if reason or not same_data(current, entry["baseline"]["target"]):
            conn.rollback()
            return {"status": "skipped", "reason": reason or "target_changed_since_preview"}
        if category_state(conn) != expected_categories:
            conn.rollback()
            return {"status": "skipped", "reason": "category_configuration_changed"}
        timestamp = utcnow()
        with conn.cursor() as cur:
            pvalues = dict(proposal["product_changes"])
            nvalues = dict(proposal["nutrition_changes"])
            if pvalues:
                pvalues["updated_at"] = timestamp
            if nvalues:
                nvalues["data_source_date"] = timestamp
            update(cur, "products", pid, pvalues)
            update(cur, "nutritionfacts", pid, nvalues)
        after = read_rows(conn, [pid]).get(str(pid))
        if not after_matches(after, current, proposal):
            raise ValueError("Post-write state mismatch")
        if after.get("available") is not True:
            raise ValueError("Availability changed during transaction")
        # Durable receipt BEFORE commit: an interrupted commit can be reconciled by CAS.
        receipt = {"product_id": pid, "before": current, "after": after, "state": "prepared",
                   "source_product_id": sid, "complete": proposal["complete"]}
        write_json(receipt_path, receipt)
        conn.commit()
        receipt["state"] = "committed"
        write_json(receipt_path, receipt)
        return {"status": "updated" if proposal["complete"] else "partial"}
    except Exception as exc:
        conn.rollback()
        # Connection exceptions may contain secrets. Only log a class, never exception text.
        return {"status": "failed", "reason": type(exc).__name__}


def restore_one(conn, receipt):
    """Restore only our fields and timestamps, and only if the full row is unchanged."""
    pid = receipt["product_id"]
    try:
        conn.rollback()
        current = read_rows(conn, [pid], lock=True).get(str(pid))
        if same_data(current, receipt["before"]):
            conn.rollback()
            return {"status": "already_restored"}
        if not same_data(current, receipt["after"]):
            conn.rollback()
            return {"status": "skipped", "reason": "later_edits_or_missing_row"}
        changes = {}
        for role, timestamp in (("product", "updated_at"), ("nutrition", "data_source_date")):
            before, after = receipt["before"][role], receipt["after"][role]
            changes[role] = {k: before[k] for k in before if before[k] != after.get(k) and k != timestamp}
        proposal = {"product_changes": changes["product"], "nutrition_changes": changes["nutrition"]}
        allowlist(proposal)
        with conn.cursor() as cur:
            for role, table, timestamp in (("product", "products", "updated_at"),
                                            ("nutrition", "nutritionfacts", "data_source_date")):
                if changes[role]:
                    changes[role][timestamp] = receipt["before"][role][timestamp]
                    update(cur, table, pid, changes[role])
        if not same_data(read_rows(conn, [pid]).get(str(pid)), receipt["before"]):
            raise ValueError("Restore verification failed")
        conn.commit()
        return {"status": "restored"}
    except Exception as exc:
        conn.rollback()
        return {"status": "failed", "reason": type(exc).__name__}
