#!/usr/bin/env python3
"""Bounded, restart-safe brand/producer backfill from stored Barbora URLs."""

import argparse
import json
import logging
import os
import random
import time
from typing import Dict, Optional

import psycopg2
from psycopg2.extensions import parse_dsn
from psycopg2.extras import RealDictCursor

from barbora_parser import BarboraParser
from brand_producer import (
    ensure_brand_producer_schema,
    persist_brand_producer_links,
    verify_brand_producer_schema,
)


logger = logging.getLogger("brand_producer_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class BackfillFatalError(RuntimeError):
    """Fatal operational error with a machine-readable recovery summary."""

    def __init__(self, message: str, result: Dict[str, object]):
        super().__init__(message)
        self.result = result


def _database_identity(database_url: str):
    """Return a credential-independent PostgreSQL server/database identity."""
    try:
        parsed = parse_dsn(database_url)
    except Exception as exc:
        raise ValueError("Database URL could not be validated.") from exc
    host = (parsed.get("host") or "").rstrip(".").casefold()
    port = str(parsed.get("port") or "5432")
    database = parsed.get("dbname") or ""
    return host, port, database


def get_database_url(
    *,
    production: bool,
    confirm_production: bool = False,
    environment: Optional[Dict[str, str]] = None,
) -> str:
    """Resolve an explicitly selected database target with production guards."""
    env = environment if environment is not None else os.environ
    if confirm_production and not production:
        raise ValueError("--confirm-production requires --production.")
    if production and not confirm_production:
        raise ValueError(
            "Production backfill requires --production and --confirm-production."
        )

    if production:
        production_url = env.get("PROD_DATABASE_URL")
        if not production_url:
            raise ValueError("PROD_DATABASE_URL is required for production.")
        development_url = env.get("DATABASE_URL") or env.get("NEON_DATABASE_URL")
        if (
            development_url
            and _database_identity(development_url)
            == _database_identity(production_url)
        ):
            raise ValueError("Development and production database URLs must differ.")
        return production_url

    development_url = env.get("DATABASE_URL") or env.get("NEON_DATABASE_URL")
    if not development_url:
        raise ValueError("DATABASE_URL or NEON_DATABASE_URL is required.")
    return development_url


def run_backfill(
    db_url: Optional[str] = None,
    parser=None,
    limit: int = None,
    offset: int = 0,
    after_product_id: int = 0,
    delay: float = 0.75,
    retries: int = 2,
    batch_size: int = 25,
    production: bool = False,
    confirm_production: bool = False,
    dry_run: bool = False,
    environment: Optional[Dict[str, str]] = None,
    sleep_fn=time.sleep,
    connection_factory=psycopg2.connect,
) -> Dict[str, object]:
    """Process products in stable batches with per-product failure isolation."""
    if (
        offset < 0
        or after_product_id < 0
        or (limit is not None and limit < 0)
        or batch_size < 1
        or delay < 0
        or retries < 0
    ):
        raise ValueError(
            "limit, offset, after_product_id, delay, and retries must be non-negative; "
            "batch_size must be at least 1"
        )
    if confirm_production and not production:
        raise ValueError("--confirm-production requires --production.")
    if production and not confirm_production:
        raise ValueError(
            "Production backfill requires --production and --confirm-production."
        )
    if production:
        selected_url = get_database_url(
            production=True,
            confirm_production=True,
            environment=environment,
        )
        if (
            db_url is not None
            and _database_identity(db_url) != _database_identity(selected_url)
        ):
            raise ValueError(
                "Production execution requires the validated PROD_DATABASE_URL target."
            )
        db_url = selected_url
    elif db_url is None:
        db_url = get_database_url(production=False, environment=environment)

    parser = parser or BarboraParser(status_callback=logger.info)
    result = {
        "selected": 0,
        "attempted": 0,
        "processed": 0,
        "updated": 0,
        "missing": 0,
        "errors": 0,
        "last_product_id": after_product_id,
        "resume_after_product_id": after_product_id,
        "simulated_resume_after_product_id": after_product_id,
        "failed_product_ids": [],
        "dry_run": dry_run,
        "status": "running",
    }
    conn = None
    try:
        conn = connection_factory(db_url)
        conn.autocommit = False
        if production or dry_run:
            verify_brand_producer_schema(conn)
        else:
            ensure_brand_producer_schema(conn)

        checkpoint_blocked = False
        resume_candidate = after_product_id
        next_product_id = after_product_id
        remaining_offset = offset

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            while limit is None or result["attempted"] < limit:
                remaining = (
                    batch_size
                    if limit is None
                    else min(batch_size, limit - result["attempted"])
                )
                query = """
                    SELECT product_id, sku, barbora_url
                    FROM products
                    WHERE barbora_url IS NOT NULL AND BTRIM(barbora_url) <> ''
                      AND product_id > %s
                    ORDER BY product_id
                    LIMIT %s
                """
                params = [next_product_id, remaining]
                if remaining_offset:
                    query = query.replace("LIMIT %s", "OFFSET %s LIMIT %s")
                    params = [next_product_id, remaining_offset, remaining]
                    remaining_offset = 0
                cur.execute(query, params)
                # The SQL LIMIT is authoritative in PostgreSQL; slicing also
                # keeps custom/test connection factories within the same bound.
                products = list(cur.fetchall())[:remaining]
                if not products:
                    break
                result["selected"] += len(products)
                counts_before_batch = {
                    key: result[key] for key in ("processed", "updated", "missing")
                }

                for index, row in enumerate(products, start=1):
                    product_id = row["product_id"]
                    result["last_product_id"] = product_id
                    next_product_id = product_id
                    result["attempted"] += 1
                    product = None
                    last_error = None
                    item_succeeded = False
                    cur.execute("SAVEPOINT brand_producer_product")
                    try:
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
                            raise RuntimeError(last_error or "no details returned")

                        persist_brand_producer_links(
                            cur,
                            product_id,
                            getattr(product, "brand", None)
                            or getattr(product, "brand_name", None),
                            getattr(product, "producer", None)
                            or getattr(product, "producer_name", None)
                            or getattr(product, "distributor_name", None)
                            or getattr(product, "manufacturer", None),
                        )
                        cur.execute("RELEASE SAVEPOINT brand_producer_product")
                        item_succeeded = True
                        result["processed"] += 1
                        if (
                            getattr(product, "brand", None)
                            or getattr(product, "brand_name", None)
                            or getattr(product, "producer", None)
                            or getattr(product, "distributor_name", None)
                            or getattr(product, "producer_name", None)
                            or getattr(product, "manufacturer", None)
                        ):
                            result["updated"] += 1
                        else:
                            result["missing"] += 1
                    except Exception as exc:
                        cur.execute("ROLLBACK TO SAVEPOINT brand_producer_product")
                        cur.execute("RELEASE SAVEPOINT brand_producer_product")
                        result["errors"] += 1
                        logger.warning("Failed SKU %s: %s", row["sku"], exc)

                    if not item_succeeded:
                        result["failed_product_ids"].append(product_id)
                        checkpoint_blocked = True
                    elif not checkpoint_blocked:
                        resume_candidate = product_id
                        result["simulated_resume_after_product_id"] = product_id

                    logger.info(
                        "Progress %d/%d | SKU %s | brand=%s | producer=%s",
                        result["attempted"],
                        result["selected"],
                        row["sku"],
                        getattr(product, "brand", None) if product else None,
                        getattr(product, "producer", None) if product else None,
                    )
                    if index < len(products):
                        sleep_fn(random.uniform(delay * 0.8, delay * 1.2))

                if dry_run:
                    conn.rollback()
                else:
                    try:
                        conn.commit()
                    except Exception:
                        for key, value in counts_before_batch.items():
                            result[key] = value
                        raise
                    result["resume_after_product_id"] = resume_candidate
                logger.info(
                    "Batch complete: attempted=%d, updated=%d, errors=%d; "
                    "safe resume cursor: --start-id %d",
                    result["attempted"],
                    result["updated"],
                    result["errors"],
                    result["resume_after_product_id"],
                )

                if len(products) < remaining:
                    break
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        result["status"] = "failed"
        result["fatal_error"] = str(exc)
        raise BackfillFatalError(str(exc), result) from exc
    finally:
        if conn is not None:
            conn.close()

    result["status"] = "completed_with_errors" if result["errors"] else "completed"
    logger.info(
        "Backfill complete: %d processed, %d with data, %d missing, %d errors; "
        "safe resume cursor: --start-id %d; failed IDs: %s",
        result["processed"],
        result["updated"],
        result["missing"],
        result["errors"],
        result["resume_after_product_id"],
        result["failed_product_ids"],
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Backfill Barbora brands and producers")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--start-id",
        "--after-product-id",
        dest="start_id",
        type=int,
        default=0,
        help="Stable resume cursor; process only product IDs greater than this value",
    )
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--delay", type=float, default=0.75, help="Base delay between requests")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_backfill(
            limit=args.limit,
            offset=args.offset,
            after_product_id=args.start_id,
            delay=args.delay,
            retries=args.retries,
            batch_size=args.batch_size,
            production=args.production,
            confirm_production=args.confirm_production,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["errors"] else 0
    except BackfillFatalError as exc:
        print(json.dumps(exc.result, ensure_ascii=False, indent=2))
        return 2
    except Exception as exc:
        result = {
            "status": "failed",
            "fatal_error": str(exc),
            "resume_after_product_id": args.start_id,
            "dry_run": args.dry_run,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())