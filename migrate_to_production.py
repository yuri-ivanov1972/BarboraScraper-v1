#!/usr/bin/env python3
"""
Database Migration Script: Development → Production

Copies all tables from a source (dev) database to the destination (production)
database identified by DATABASE_URL.

Usage:
    python migrate_to_production.py

Environment variables:
    DATABASE_URL        Destination (production) DB — Replit injects this automatically.
    SOURCE_DATABASE_URL Source (development) DB connection string.
                        If not set, the script will prompt for it interactively.
"""

import os
import sys
import time
import psycopg2
from psycopg2 import sql


# ---------------------------------------------------------------------------
# Tables in migration order (parents before children to respect FK constraints)
# ---------------------------------------------------------------------------
TABLES_IN_ORDER = [
    "normalized_categories",
    "ingredient_analysis",
    "products",
    "category_processing_jobs",
    "processing_workers",
    "nutritionfacts",
    "productphotos",
    "product_price_history",
    "job_events",
    "product_processing_log",
    "update_statistics",
    "ingredient_product_mapping",
]

BATCH_SIZE = 1000

# ---------------------------------------------------------------------------
# Console helpers
# ---------------------------------------------------------------------------

def info(msg):
    print(f"\u2139 {msg}")

def ok(msg):
    print(f"\u2713 {msg}")

def err(msg):
    print(f"\u2717 {msg}", file=sys.stderr)

def header(title):
    line = "=" * 62
    print(f"\n{line}")
    print(f"{title:^62}")
    print(f"{line}\n")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_connection(url: str, label: str):
    info(f"Connecting to {label} database...")
    try:
        conn = psycopg2.connect(url)
        conn.autocommit = False
        ok(f"Connected to {label} database")
        return conn
    except Exception as exc:
        err(f"Failed to connect to {label} database: {exc}")
        sys.exit(1)


def table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = %s)",
            (table_name,),
        )
        return cur.fetchone()[0]


def get_columns(conn, table_name: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (table_name,),
        )
        return [row[0] for row in cur.fetchall()]


def get_row_count(conn, table_name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table_name))
        )
        return cur.fetchone()[0]


def migrate_table(src_conn, dst_conn, table_name: str) -> dict:
    info(f"Migrating table: {table_name}")

    if not table_exists(src_conn, table_name):
        info(f"  Table {table_name!r} does not exist in source — skipping")
        return {"table": table_name, "status": "skipped", "rows": 0}

    if not table_exists(dst_conn, table_name):
        info(f"  Table {table_name!r} does not exist in destination — skipping")
        return {"table": table_name, "status": "skipped", "rows": 0}

    columns = get_columns(src_conn, table_name)
    src_count = get_row_count(src_conn, table_name)
    info(f"  Source records: {src_count}")

    col_identifiers = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    placeholders = sql.SQL(", ").join(sql.Placeholder() * len(columns))
    insert_query = sql.SQL(
        "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING"
    ).format(sql.Identifier(table_name), col_identifiers, placeholders)

    try:
        with dst_conn.cursor() as dst_cur:
            info(f"  Truncating destination table...")
            dst_cur.execute(
                sql.SQL("TRUNCATE TABLE {} CASCADE").format(sql.Identifier(table_name))
            )

        with src_conn.cursor("migration_cursor") as src_cur:
            src_cur.execute(
                sql.SQL("SELECT {} FROM {}").format(
                    col_identifiers, sql.Identifier(table_name)
                )
            )

            inserted = 0
            with dst_conn.cursor() as dst_cur:
                while True:
                    rows = src_cur.fetchmany(BATCH_SIZE)
                    if not rows:
                        break
                    dst_cur.executemany(insert_query, rows)
                    inserted += len(rows)
                    info(f"  Inserted {inserted}/{src_count} records...")

        dst_conn.commit()
        final_count = get_row_count(dst_conn, table_name)
        ok(f"  Migration complete: {final_count} records")
        return {"table": table_name, "status": "ok", "src": src_count, "dst": final_count}

    except Exception as exc:
        dst_conn.rollback()
        err(f"  Failed to migrate {table_name}: {exc}")
        return {"table": table_name, "status": "error", "error": str(exc)}


def reset_sequences(conn, table_name: str):
    """Reset auto-increment sequences to max ID value in the table."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "AND column_default LIKE 'nextval%%'",
                (table_name,),
            )
            serial_cols = [row[0] for row in cur.fetchall()]
            for col in serial_cols:
                cur.execute(
                    sql.SQL(
                        "SELECT setval(pg_get_serial_sequence(%s, %s), "
                        "COALESCE(MAX({}), 1)) FROM {}"
                    ).format(sql.Identifier(col), sql.Identifier(table_name)),
                    (table_name, col),
                )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        info(f"  Could not reset sequence for {table_name}: {exc}")


def disable_triggers(conn):
    with conn.cursor() as cur:
        cur.execute("SET session_replication_role = 'replica'")
    conn.commit()


def enable_triggers(conn):
    with conn.cursor() as cur:
        cur.execute("SET session_replication_role = 'DEFAULT'")
    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    header("DATABASE MIGRATION: DEV → PROD")

    # Destination: production — Replit injects DATABASE_URL automatically
    dst_url = os.environ.get("DATABASE_URL")
    if not dst_url:
        err(
            "DATABASE_URL is not set. Replit injects this automatically when "
            "running inside a deployment. If running locally, export it:\n"
            "  export DATABASE_URL='your_production_connection_string'"
        )
        sys.exit(1)

    # Source: development database
    src_url = os.environ.get("SOURCE_DATABASE_URL")
    if not src_url:
        print(
            "SOURCE_DATABASE_URL is not set.\n"
            "Enter the source (development) database connection string:"
        )
        src_url = input("  Source DB URL: ").strip()
        if not src_url:
            err("No source database URL provided. Aborting.")
            sys.exit(1)

    src_conn = get_connection(src_url, "source (dev)")
    dst_conn = get_connection(dst_url, "destination (prod)")

    header("STARTING MIGRATION")

    start_time = time.time()
    results = []

    try:
        disable_triggers(dst_conn)

        for table in TABLES_IN_ORDER:
            result = migrate_table(src_conn, dst_conn, table)
            results.append(result)
            if result["status"] == "ok":
                reset_sequences(dst_conn, table)

    finally:
        enable_triggers(dst_conn)
        src_conn.close()
        dst_conn.close()

    elapsed = time.time() - start_time

    header("MIGRATION SUMMARY")

    total_rows = 0
    all_ok = True
    for r in results:
        if r["status"] == "ok":
            label = f"\u2713 {r['table']:<40} {r['src']:>8} \u2192 {r['dst']:>8}"
            total_rows += r["dst"]
        elif r["status"] == "skipped":
            label = f"- {r['table']:<40} (skipped — table not found)"
        else:
            label = f"\u2717 {r['table']:<40} ERROR: {r.get('error', 'unknown')}"
            all_ok = False
        print(label)

    print()
    info(f"Total records migrated: {total_rows}")
    info(f"Total tables processed: {len(results)}")
    info(f"Migration completed in {elapsed:.2f} seconds")

    if all_ok:
        ok("All tables migrated successfully!")
    else:
        err("Some tables had errors — check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
