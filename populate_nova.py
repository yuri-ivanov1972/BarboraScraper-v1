#!/usr/bin/env python3
"""
Step 3 — Bulk-populate NOVA scores for all existing products.

Two-pass logic:
  Pass 1 (additive override): products with any ingredient whose suspicion_level
          is 'avoid' or 'limit' → nova_score=4, nova_source='additive_override'
  Pass 2 (category fallback): remaining products → look up nova_score from
          rimi_nova_categories via products.rimi_category_code → nova_source='category_inherited'

Skips products where nova_source = 'manual_override'.

Usage:
    python populate_nova.py --dry-run   # preview counts, no writes
    python populate_nova.py             # apply

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


def check_prerequisites(cur) -> list[str]:
    """Return list of problems that would prevent scoring."""
    problems = []

    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='products' AND column_name='nova_score')"
    )
    if not cur.fetchone()["exists"]:
        problems.append("Column products.nova_score is missing — run add_nova_columns.py first.")

    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='rimi_nova_categories')"
    )
    if not cur.fetchone()["exists"]:
        problems.append("Table rimi_nova_categories is missing — run sync_rimi_nova_categories.py first.")

    return problems


def count_pass1(cur) -> int:
    """Products eligible for additive_override (not yet manual_override)."""
    cur.execute("""
        SELECT COUNT(DISTINCT p.product_id)
        FROM products p
        JOIN ingredient_product_mapping ipm ON ipm.product_sku = p.sku
        JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
        WHERE ia.suspicion_level IN ('avoid', 'limit')
          AND (p.nova_source IS DISTINCT FROM 'manual_override')
    """)
    return cur.fetchone()["count"]


def count_pass2(cur) -> int:
    """Products eligible for category_inherited (not override, not additive)."""
    cur.execute("""
        SELECT COUNT(*)
        FROM products p
        JOIN rimi_nova_categories rnc
          ON rnc.rimi_category_code = p.rimi_category_code
        WHERE (p.nova_source IS DISTINCT FROM 'manual_override')
          AND p.product_id NOT IN (
              SELECT DISTINCT p2.product_id
              FROM products p2
              JOIN ingredient_product_mapping ipm ON ipm.product_sku = p2.sku
              JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
              WHERE ia.suspicion_level IN ('avoid', 'limit')
                AND (p2.nova_source IS DISTINCT FROM 'manual_override')
          )
    """)
    return cur.fetchone()["count"]


def apply_pass1(cur) -> int:
    """Set nova_score=4 for products with avoid/limit ingredients."""
    cur.execute("""
        UPDATE products
        SET nova_score  = 4,
            nova_source = 'additive_override'
        WHERE product_id IN (
            SELECT DISTINCT p.product_id
            FROM products p
            JOIN ingredient_product_mapping ipm ON ipm.product_sku = p.sku
            JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
            WHERE ia.suspicion_level IN ('avoid', 'limit')
              AND (p.nova_source IS DISTINCT FROM 'manual_override')
        )
    """)
    return cur.rowcount


def apply_pass2(cur) -> int:
    """Set nova_score from rimi_nova_categories for remaining products."""
    cur.execute("""
        UPDATE products p
        SET nova_score  = rnc.nova_score,
            nova_source = 'category_inherited'
        FROM rimi_nova_categories rnc
        WHERE rnc.rimi_category_code = p.rimi_category_code
          AND (p.nova_source IS DISTINCT FROM 'manual_override')
          AND (p.nova_score IS NULL OR p.nova_source = 'category_inherited')
          AND p.product_id NOT IN (
              SELECT DISTINCT p2.product_id
              FROM products p2
              JOIN ingredient_product_mapping ipm ON ipm.product_sku = p2.sku
              JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
              WHERE ia.suspicion_level IN ('avoid', 'limit')
                AND (p2.nova_source IS DISTINCT FROM 'manual_override')
          )
    """)
    return cur.rowcount


def main():
    parser = argparse.ArgumentParser(description="Bulk-populate NOVA scores for all products")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts only — no writes")
    args = parser.parse_args()

    conn = get_conn()

    try:
        with conn.cursor() as cur:
            problems = check_prerequisites(cur)
            if problems:
                for p in problems:
                    print(f"✗ {p}", file=sys.stderr)
                sys.exit(1)

            # Current state
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(nova_score) AS already_scored,
                    COUNT(*) FILTER (WHERE nova_source = 'manual_override') AS manual
                FROM products
            """)
            state = cur.fetchone()
            print(f"Total products:         {state['total']}")
            print(f"Already scored:         {state['already_scored']}")
            print(f"Manual overrides:       {state['manual']}")
            print()

            p1_count = count_pass1(cur)
            p2_count = count_pass2(cur)

            print(f"Pass 1 (additive override):   {p1_count} products → nova_score=4")
            print(f"Pass 2 (category inherited):  {p2_count} products → from category")
            print()

            cur.execute("""
                SELECT COUNT(*) FROM products
                WHERE rimi_category_code IS NULL
                  AND (nova_source IS DISTINCT FROM 'manual_override')
                  AND nova_score IS NULL
                  AND product_id NOT IN (
                      SELECT DISTINCT p.product_id
                      FROM products p
                      JOIN ingredient_product_mapping ipm ON ipm.product_sku = p.sku
                      JOIN ingredient_analysis ia ON ia.id = ipm.ingredient_id
                      WHERE ia.suspicion_level IN ('avoid','limit')
                  )
            """)
            unscored = cur.fetchone()["count"]
            if unscored:
                print(f"ℹ {unscored} products have no rimi_category_code and no additive flag — will remain unscored.")
                print()

        if args.dry_run:
            print("DRY-RUN — no changes made. Re-run without --dry-run to apply.")
            return

        with conn.cursor() as cur:
            p1_updated = apply_pass1(cur)
            print(f"✓ Pass 1: updated {p1_updated} products with nova_score=4 (additive_override)")

            p2_updated = apply_pass2(cur)
            print(f"✓ Pass 2: updated {p2_updated} products with category NOVA score (category_inherited)")

        conn.commit()

        # Final summary
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    nova_score,
                    nova_source,
                    COUNT(*) AS count
                FROM products
                WHERE nova_score IS NOT NULL
                GROUP BY nova_score, nova_source
                ORDER BY nova_score, nova_source
            """)
            rows = cur.fetchall()

        print()
        print("=== NOVA Score Distribution ===")
        for row in rows:
            print(f"  NOVA {row['nova_score']} ({row['nova_source']}): {row['count']} products")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM products WHERE nova_score IS NULL")
            still_null = cur.fetchone()["count"]
        print(f"  Still unscored: {still_null} products")
        print()
        print("✓ Done.")

    except Exception as exc:
        conn.rollback()
        print(f"✗ Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
