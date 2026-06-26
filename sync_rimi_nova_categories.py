#!/usr/bin/env python3
"""
Step 2 — Sync Rimi category NOVA scores into the Barbora DB.

Creates (if needed) a local rimi_nova_categories table in the Barbora DB,
then reads nova_score values from the Rimi DB's normalized_categories table
and upserts them locally. Re-run whenever NOVA scores change in the Rimi project.

Usage:
    python sync_rimi_nova_categories.py --dry-run   # preview counts
    python sync_rimi_nova_categories.py             # apply

Environment variables:
    DATABASE_URL        Barbora DB — Replit injects automatically.
    RIMI_DATABASE_URL   Rimi DB — read-only source for NOVA scores.
"""

import argparse
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rimi_nova_categories (
    rimi_category_code  INTEGER     PRIMARY KEY,
    nova_score          INTEGER,
    synced_at           TIMESTAMPTZ DEFAULT NOW()
)
"""


def get_conn(env_var: str, label: str):
    url = os.environ.get(env_var)
    if not url:
        print(f"✗ {env_var} is not set ({label}).", file=sys.stderr)
        sys.exit(1)
    try:
        conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
        print(f"✓ Connected to {label} ({env_var})")
        return conn
    except Exception as exc:
        print(f"✗ Failed to connect to {label}: {exc}", file=sys.stderr)
        sys.exit(1)


def discover_id_column(rimi_conn) -> str:
    """
    Find which column in Rimi's normalized_categories holds the integer
    category ID that maps to Barbora's products.rimi_category_code.
    Tries common names in order.
    """
    candidates = ["category_id", "id", "rimi_category_id"]
    with rimi_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'normalized_categories' "
            "ORDER BY ordinal_position"
        )
        existing = {row["column_name"] for row in cur.fetchall()}

    for col in candidates:
        if col in existing:
            return col

    # Fall back to the first integer-type primary key column
    with rimi_conn.cursor() as cur:
        cur.execute(
            "SELECT kcu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON kcu.constraint_name = tc.constraint_name "
            "JOIN information_schema.columns c "
            "  ON c.column_name = kcu.column_name AND c.table_name = tc.table_name "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "  AND tc.table_schema = 'public' "
            "  AND tc.table_name = 'normalized_categories' "
            "  AND c.data_type IN ('integer','bigint','smallint')"
        )
        row = cur.fetchone()
        if row:
            return row["column_name"]

    print(
        "✗ Could not find a suitable integer ID column in Rimi's normalized_categories.\n"
        f"  Columns found: {sorted(existing)}",
        file=sys.stderr,
    )
    sys.exit(1)


def fetch_rimi_nova_scores(rimi_conn, id_col: str) -> list[dict]:
    """Read all category_id + nova_score rows from Rimi DB where nova_score is set."""
    with rimi_conn.cursor() as cur:
        cur.execute(
            f'SELECT "{id_col}" AS rimi_category_code, nova_score '
            f"FROM normalized_categories "
            f"WHERE nova_score IS NOT NULL"
        )
        return list(cur.fetchall())


def ensure_table(barbora_conn):
    with barbora_conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL)
    barbora_conn.commit()
    print("✓ rimi_nova_categories table ready")


def upsert_rows(barbora_conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with barbora_conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO rimi_nova_categories (rimi_category_code, nova_score, synced_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (rimi_category_code)
                DO UPDATE SET
                    nova_score = EXCLUDED.nova_score,
                    synced_at  = NOW()
                """,
                (row["rimi_category_code"], row["nova_score"]),
            )
    barbora_conn.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(
        description="Sync Rimi category NOVA scores into the Barbora DB"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only — no writes")
    args = parser.parse_args()

    rimi_conn = get_conn("RIMI_DATABASE_URL", "Rimi DB (read-only source)")
    barbora_conn = get_conn("DATABASE_URL", "Barbora DB (destination)")

    try:
        id_col = discover_id_column(rimi_conn)
        print(f"ℹ Using column '{id_col}' as category ID in Rimi's normalized_categories")

        rows = fetch_rimi_nova_scores(rimi_conn, id_col)
        print(f"ℹ Found {len(rows)} categories with nova_score in Rimi DB")

        if not rows:
            print("⚠ No categories with nova_score found — nothing to sync.")
            return

        # Show sample
        for row in rows[:5]:
            print(f"    rimi_category_code={row['rimi_category_code']:>5}  nova_score={row['nova_score']}")
        if len(rows) > 5:
            print(f"    ... and {len(rows) - 5} more")
        print()

        if args.dry_run:
            print(f"DRY-RUN — would upsert {len(rows)} rows into rimi_nova_categories.")
            print("Re-run without --dry-run to apply.")
            return

        ensure_table(barbora_conn)
        count = upsert_rows(barbora_conn, rows)
        print(f"✓ Upserted {count} rows into rimi_nova_categories")

        # How many Barbora products now have a matching category?
        with barbora_conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS matched FROM products p "
                "JOIN rimi_nova_categories rnc ON rnc.rimi_category_code = p.rimi_category_code"
            )
            matched = cur.fetchone()["matched"]
        print(f"✓ {matched} Barbora products now have a matching NOVA category")
        print()
        print("✓ Done. Run populate_nova.py to apply scores to all products.")

    finally:
        rimi_conn.close()
        barbora_conn.close()


if __name__ == "__main__":
    main()
