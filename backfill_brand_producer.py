#!/usr/bin/env python3
"""Bounded, restart-safe brand/producer backfill from stored Barbora URLs."""

import argparse
import logging
import os
import random
import time
from typing import Dict

import psycopg2
from psycopg2.extras import RealDictCursor

from barbora_parser import BarboraParser
from brand_producer import ensure_brand_producer_schema, persist_brand_producer_links


logger = logging.getLogger("brand_producer_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def run_backfill(
    db_url: str,
    parser=None,
    limit: int = None,
    offset: int = 0,
    after_product_id: int = 0,
    delay: float = 0.75,
    retries: int = 2,
    sleep_fn=time.sleep,
    connection_factory=psycopg2.connect,
) -> Dict[str, object]:
    """Process products in stable ID order and continue after per-product failures."""
    if offset < 0 or after_product_id < 0 or (limit is not None and limit < 0):
        raise ValueError("limit, offset, and after_product_id must be non-negative")

    parser = parser or BarboraParser(status_callback=logger.info)
    conn = connection_factory(db_url)
    try:
        ensure_brand_producer_schema(conn)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = """
                SELECT product_id, sku, barbora_url
                FROM products
                WHERE barbora_url IS NOT NULL AND BTRIM(barbora_url) <> ''
                  AND product_id > %s
                ORDER BY product_id
                OFFSET %s
            """
            params = [after_product_id, offset]
            if limit is not None:
                query += " LIMIT %s"
                params.append(limit)
            cur.execute(query, params)
            products = list(cur.fetchall())
    finally:
        conn.close()

    result = {
        "selected": len(products), "processed": 0, "updated": 0,
        "missing": 0, "errors": 0, "last_product_id": after_product_id,
        "resume_after_product_id": after_product_id, "failed_product_ids": [],
    }
    checkpoint_blocked = False
    for index, row in enumerate(products, start=1):
        result["last_product_id"] = row["product_id"]
        product = None
        last_error = None
        item_succeeded = False
        for attempt in range(retries + 1):
            try:
                product = parser.extract_product_details(row["barbora_url"])
                if product:
                    break
            except Exception as exc:
                last_error = exc
            if attempt < retries:
                sleep_fn(delay * (attempt + 1))

        if product is None:
            result["errors"] += 1
            logger.warning("Failed SKU %s: %s", row["sku"], last_error or "no details returned")
        else:
            try:
                conn = connection_factory(db_url)
                try:
                    with conn.cursor() as cur:
                        persist_brand_producer_links(
                            cur,
                            row["product_id"],
                            getattr(product, "brand", None)
                            or getattr(product, "brand_name", None),
                            getattr(product, "producer", None)
                            or getattr(product, "producer_name", None)
                            or getattr(product, "manufacturer", None),
                        )
                    conn.commit()
                finally:
                    conn.close()
                result["processed"] += 1
                item_succeeded = True
                if (
                    getattr(product, "brand", None)
                    or getattr(product, "brand_name", None)
                    or getattr(product, "producer", None)
                    or getattr(product, "producer_name", None)
                    or getattr(product, "manufacturer", None)
                ):
                    result["updated"] += 1
                else:
                    result["missing"] += 1
            except Exception as exc:
                result["errors"] += 1
                logger.warning("Failed to save SKU %s: %s", row["sku"], exc)
                try:
                    conn.rollback()
                except Exception:
                    pass

        if not item_succeeded:
            result["failed_product_ids"].append(row["product_id"])
            checkpoint_blocked = True
        elif not checkpoint_blocked:
            result["resume_after_product_id"] = row["product_id"]

        logger.info(
            "Progress %d/%d | SKU %s | brand=%s | producer=%s",
            index, len(products), row["sku"],
            getattr(product, "brand", None) if product else None,
            getattr(product, "producer", None) if product else None,
        )
        if index < len(products):
            sleep_fn(random.uniform(delay * 0.8, delay * 1.2))

    logger.info(
        "Backfill complete: %d processed, %d with data, %d missing, %d errors; "
        "safe resume cursor: --after-product-id %d; failed IDs: %s",
        result["processed"], result["updated"], result["missing"], result["errors"],
        result["resume_after_product_id"], result["failed_product_ids"],
    )
    return result


def main():
    parser = argparse.ArgumentParser(description="Backfill Barbora brands and producers")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--after-product-id", type=int, default=0,
        help="Stable resume cursor; process only product IDs greater than this value",
    )
    parser.add_argument("--delay", type=float, default=0.75, help="Base delay between requests")
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()
    run_backfill(os.environ["DATABASE_URL"], limit=args.limit, offset=args.offset,
                 after_product_id=args.after_product_id,
                 delay=args.delay, retries=args.retries)


if __name__ == "__main__":
    main()