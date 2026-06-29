#!/usr/bin/env python3
"""
fix_broken_photos.py — Verify stored photo URLs and re-scrape broken/missing ones.

Phase 1:  HEAD-check every row in productphotos concurrently.
Phase 1b: Find products with no photo rows at all.
Phase 2:  Re-scrape barbora_url for each broken / photo-less product.
Phase 3:  Update the DB (delete old broken rows + insert fresh ones).
          If re-scrape finds nothing, existing rows are left untouched.

Usage:
    python fix_broken_photos.py --dry-run          # preview only
    python fix_broken_photos.py --limit 200        # test on first 200 photos
    python fix_broken_photos.py                    # full run
    python fix_broken_photos.py --concurrency 20   # faster HEAD phase

Environment:
    DATABASE_URL    Replit-injected Postgres connection string.
"""

import argparse
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import psycopg2
import requests
from bs4 import BeautifulSoup
from psycopg2.extras import RealDictCursor


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "lv,en-US;q=0.7,en;q=0.3",
    })
    return s


def _check_url(args: tuple) -> tuple:
    """Thread worker: returns (photo_id, product_id, is_ok)."""
    photo_id, product_id, url, session = args
    try:
        resp = session.head(url, timeout=10, allow_redirects=True)
        ok = resp.status_code == 200 and "no-image-placeholder" not in resp.url
        return photo_id, product_id, ok
    except Exception:
        return photo_id, product_id, False


def _scrape_photos(barbora_url: str, session: requests.Session) -> list:
    """Fetch the Barbora product page and extract cdn.barbora.lv image URLs."""
    try:
        resp = session.get(barbora_url, timeout=15)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.content, "html.parser")
        photos = []
        for slide in soup.find_all("div", class_="b-block-slider--slide"):
            img = slide.find("img", src=True)
            if img:
                src = img.get("src", "")
                if src and "cdn.barbora.lv" in src and "no-image-placeholder" not in src:
                    if src not in photos:
                        photos.append(src)
        return photos
    except Exception:
        return []


# ── DB helpers ────────────────────────────────────────────────────────────────

def _save_photos(conn, product_id: int, urls: list, dry_run: bool) -> bool:
    """Delete old photo rows and insert fresh ones. Returns True on success."""
    if dry_run:
        return True
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM productphotos WHERE product_id = %s", (product_id,))
            for i, url in enumerate(urls):
                cur.execute(
                    "INSERT INTO productphotos (product_id, photo_url, is_primary) "
                    "VALUES (%s, %s, %s)",
                    (product_id, url.strip(), i == 0),
                )
        conn.commit()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


# ── core logic ────────────────────────────────────────────────────────────────

def run(
    dry_run: bool = False,
    limit: Optional[int] = None,
    concurrency: int = 10,
    log: Callable = print,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Run the full three-phase photo fix.

    Args:
        dry_run:           If True, no DB writes.
        limit:             Max number of photos to verify (None = all).
        concurrency:       Thread count for HEAD requests.
        log:               Callable for status messages.
        progress_callback: Optional fn(done, total) for UI progress bars.

    Returns dict with keys:
        total_checked, broken_found, affected_products,
        no_photo_products, fixed, missing_scraped, unresolvable
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log("✗ DATABASE_URL not set")
        sys.exit(1)

    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    session = _make_session()

    # ── Phase 1: load + HEAD-check existing photos ───────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "SELECT photo_id, product_id, photo_url FROM productphotos ORDER BY photo_id"
        )
        all_photos = list(cur.fetchall())

    if limit:
        all_photos = all_photos[:limit]

    total = len(all_photos)
    log(f"Phase 1: Verifying {total} stored photo URLs ({concurrency} threads)…")

    broken_photo_ids: set = set()
    broken_product_ids: set = set()

    args_list = [
        (row["photo_id"], row["product_id"], row["photo_url"], session)
        for row in all_photos
    ]

    checked = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_check_url, a): a[0] for a in args_list}
        for fut in as_completed(futures):
            photo_id, product_id, ok = fut.result()
            checked += 1
            if not ok:
                broken_photo_ids.add(photo_id)
                broken_product_ids.add(product_id)
            if progress_callback:
                progress_callback(checked, total, phase=1)
            if checked % 500 == 0:
                log(f"  … checked {checked}/{total}, broken so far: {len(broken_photo_ids)}")

    log(
        f"Phase 1 done: {len(broken_photo_ids)} broken photos across "
        f"{len(broken_product_ids)} products"
    )

    # ── Phase 1b: products with zero photo rows ───────────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.product_id, p.barbora_url
            FROM products p
            WHERE p.barbora_url IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM productphotos ph WHERE ph.product_id = p.product_id
              )
            ORDER BY p.product_id
            """
        )
        no_photo_rows = list(cur.fetchall())

    if limit:
        remaining = max(0, limit - len(broken_product_ids))
        no_photo_rows = no_photo_rows[:remaining]

    log(f"Phase 1b: {len(no_photo_rows)} products have no photo at all")

    # ── Build combined re-scrape list ─────────────────────────────────────────
    if broken_product_ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT product_id, barbora_url FROM products "
                "WHERE product_id = ANY(%s) AND barbora_url IS NOT NULL",
                (list(broken_product_ids),),
            )
            broken_rows = [dict(r) for r in cur.fetchall()]
    else:
        broken_rows = []

    to_scrape = broken_rows + [dict(r) for r in no_photo_rows]
    missing_pids = {r["product_id"] for r in no_photo_rows}

    log(f"Phase 2: Re-scraping {len(to_scrape)} products from Barbora…")

    # ── Phase 2: re-scrape ────────────────────────────────────────────────────
    fixed = 0
    unresolvable = 0
    missing_scraped = 0

    for i, row in enumerate(to_scrape):
        pid = row["product_id"]
        burl = row["barbora_url"]

        if i > 0 and i % 20 == 0:
            log(f"  … {i}/{len(to_scrape)}: fixed={fixed}, unresolvable={unresolvable}")

        if progress_callback:
            progress_callback(i + 1, len(to_scrape), phase=2)

        time.sleep(random.uniform(0.6, 1.3))
        new_urls = _scrape_photos(burl, session)

        if new_urls:
            if dry_run:
                log(f"  [DRY-RUN] product_id={pid}: would save {len(new_urls)} photo(s)")
            else:
                _save_photos(conn, pid, new_urls, dry_run=False)
            fixed += 1
            if pid in missing_pids:
                missing_scraped += 1
        else:
            unresolvable += 1

    # ── summary ───────────────────────────────────────────────────────────────
    log("")
    log("=== Photo Fix Summary ===")
    log(f"  Photos checked:            {total}")
    log(f"  Broken photos found:       {len(broken_photo_ids)}")
    log(f"  Affected products:         {len(broken_product_ids)}")
    log(f"  Products with no photo:    {len(no_photo_rows)}")
    log(f"  Fixed (re-scraped OK):     {fixed}")
    log(f"    incl. previously missing:{missing_scraped}")
    log(f"  Unresolvable (left as-is): {unresolvable}")
    if dry_run:
        log("  [DRY-RUN] — no changes written to DB")

    conn.close()

    return {
        "total_checked": total,
        "broken_found": len(broken_photo_ids),
        "affected_products": len(broken_product_ids),
        "no_photo_products": len(no_photo_rows),
        "fixed": fixed,
        "missing_scraped": missing_scraped,
        "unresolvable": unresolvable,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fix broken product photo URLs")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview only — no DB writes"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Check only the first N photo rows"
    )
    parser.add_argument(
        "--concurrency", type=int, default=10, help="Thread count for HEAD requests"
    )
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, limit=args.limit, concurrency=args.concurrency)

    print()
    if result["broken_found"] == 0 and result["no_photo_products"] == 0:
        print("✓ All photos look healthy — nothing to fix.")
    else:
        status = "would fix" if args.dry_run else "fixed"
        print(
            f"✓ Done — {status} {result['fixed']} product(s), "
            f"{result['unresolvable']} unresolvable."
        )
