#!/usr/bin/env python3
"""
Step 1 — Add NOVA columns to the products table.

Usage:
    python add_nova_columns.py --dry-run   # preview only
    python add_nova_columns.py             # apply

Environment variables:
    DATABASE_URL    Barbora database (Replit injects automatically).
"""

import argparse
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("✗ DATABASE_URL is not set.", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s)",
        (table, column),
    )
    return cur.fetchone()["exists"]


def main():
    parser = argparse.ArgumentParser(description="Add nova_score / nova_source columns to products table")
    parser.add_argument("--dry-run", action="store_true", help="Preview only — no changes made")
    args = parser.parse_args()

    conn = get_conn()

    try:
        with conn.cursor() as cur:
            has_score  = column_exists(cur, "products", "nova_score")
            has_source = column_exists(cur, "products", "nova_source")

        print("Current state:")
        print(f"  nova_score  column: {'EXISTS' if has_score  else 'MISSING'}")
        print(f"  nova_source column: {'EXISTS' if has_source else 'MISSING'}")
        print()

        if has_score and has_source:
            print("✓ Both columns already exist — nothing to do.")
            return

        if args.dry_run:
            print("DRY-RUN — would apply:")
            if not has_score:
                print("  ALTER TABLE products ADD COLUMN nova_score  INTEGER;")
            if not has_source:
                print("  ALTER TABLE products ADD COLUMN nova_source VARCHAR(30);")
            print()
            print("Re-run without --dry-run to apply.")
            return

        with conn.cursor() as cur:
            if not has_score:
                cur.execute("ALTER TABLE products ADD COLUMN nova_score INTEGER")
                print("✓ Added nova_score INTEGER")
            if not has_source:
                cur.execute("ALTER TABLE products ADD COLUMN nova_source VARCHAR(30)")
                print("✓ Added nova_source VARCHAR(30)")

        conn.commit()

        # Show current null counts
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total, COUNT(nova_score) AS scored FROM products")
            row = cur.fetchone()
        print()
        print(f"Products total:             {row['total']}")
        print(f"Products with nova_score:   {row['scored']}")
        print(f"Products needing scoring:   {row['total'] - row['scored']}")
        print()
        print("✓ Done. Run populate_nova.py to fill scores for existing products.")

    except Exception as exc:
        conn.rollback()
        print(f"✗ Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
