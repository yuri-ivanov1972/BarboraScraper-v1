"""Bounded, strictly read-only inventory of incompatible production photo links.

No Apply command: a fresh preview and explicit approval are required before repair.
"""
import argparse
import csv
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from psycopg2.extras import RealDictCursor

from nutrition_reload_store import database_target, connect
from nutrition_reload_plan import digest
from nutrition_reload_source import SourceError
from photo_maintenance import check_image
from photo_sources import asset_key, is_avif
from product_refresh_source import ProductRefreshSource


def now():
    return datetime.now(timezone.utc).isoformat()


def inventory(dsn, limit):
    """No initialization, lease, verification cache or ownership writes."""
    conn = connect(dsn, readonly=True)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT to_regclass('public.photo_maintenance') AS tracking")
            tracking = bool(cur.fetchone()["tracking"])
            maintenance = ("LEFT JOIN photo_maintenance m USING(product_id)" if tracking else
                           "LEFT JOIN (SELECT NULL::integer product_id,NULL::text ownership,"
                           "NULL::text candidate_url,NULL::text managed_url) m USING(product_id)")
            cte = f"""
                WITH affected AS (
                    SELECT p.product_id,p.sku,p.name,p.barbora_url,
                           COALESCE(m.ownership,'unknown') ownership,
                           m.candidate_url,m.managed_url,
                           COALESCE(a.is_available,false) is_available,
                           COALESCE(ph.photos,'[]'::jsonb) photos
                    FROM products p {maintenance}
                    LEFT JOIN LATERAL (
                        SELECT jsonb_agg(to_jsonb(pp) ORDER BY is_primary DESC NULLS LAST,photo_id) photos
                        FROM productphotos pp WHERE pp.product_id=p.product_id
                    ) ph ON true
                    LEFT JOIN LATERAL (
                        SELECT is_available FROM product_price_history
                        WHERE product_id=p.product_id ORDER BY recorded_at DESC,price_history_id DESC LIMIT 1
                    ) a ON true
                    WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(ph.photos) image
                                  WHERE image->>'photo_url' ~* %(pattern)s)
                       OR COALESCE(m.candidate_url,'') ~* %(pattern)s
                       OR COALESCE(m.managed_url,'') ~* %(pattern)s
                )
            """
            params = dict(limit=limit, pattern=r"\.avif([?#]|$)|[?&](format|fm|f)=(avif|image%2favif)(&|$)")
            cur.execute(cte + """SELECT count(*) total,
                count(*) FILTER(WHERE is_available) available,
                count(*) FILTER(WHERE ownership='retailer') retailer,
                count(*) FILTER(WHERE ownership='manual') manual,
                count(*) FILTER(WHERE ownership='unknown') unknown FROM affected""", params)
            totals = dict(cur.fetchone())
            cur.execute(cte + """SELECT * FROM affected
                ORDER BY (ownership='retailer') DESC,is_available DESC,product_id LIMIT %(limit)s""", params)
            return totals, [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def targets(row):
    result = []
    for i, photo in enumerate(row["photos"]):
        if is_avif(photo["photo_url"]):
            result.append(dict(kind="primary" if i == 0 else "gallery",
                               photo_id=photo["photo_id"], old_url=photo["photo_url"]))
    for key in ("candidate_url", "managed_url"):
        if is_avif(row.get(key)):
            result.append(dict(kind=key, photo_id=None, old_url=row[key]))
    return result


def preview(dsn, target, limit=20, seconds=120, source=None):
    if not 1 <= limit <= 100 or not 10 <= seconds <= 300:
        raise ValueError("Preview requires 1–100 products and a 10–300 second budget")
    started, clock = now(), time.monotonic()
    totals, rows = inventory(dsn, limit)
    source = source or ProductRefreshSource(delay=.5, retries=0, timeout=8, max_pages=1)
    results, check_cache = [], {}
    cdn_blocked = page_blocked = False
    for row in rows:
        choices = targets(row)
        if not choices:
            continue
        entry = dict(snapshot=row, links=choices, outcome="not_processed")
        results.append(entry)
        if not row["is_available"]:
            entry["outcome"] = "unavailable_product"
            continue
        if row["ownership"] == "manual":
            entry["outcome"] = "manual_photo_protected"
            continue
        if time.monotonic() - clock >= seconds - 10 or page_blocked:
            entry["outcome"] = "deferred_budget_or_page_host"
            continue
        try:
            candidate = source.product({"product": row})
            alternatives = {asset_key(url): url for url in candidate["photo_urls"]}
        except Exception as exc:
            error = str(exc) if isinstance(exc, SourceError) else type(exc).__name__
            entry["outcome"] = "page_unavailable_or_unreadable"
            entry["source_error"] = error
            if any(code in error for code in ("403", "429", "401")):
                page_blocked = True
            continue
        for link in choices:
            url = alternatives.get(asset_key(link["old_url"]))
            link.update(new_url=url, verification="no_same_image_alternative", eligible=False)
            if not url:
                continue
            if cdn_blocked or time.monotonic() - clock >= seconds - 7:
                link["verification"] = "deferred_host_or_budget"
                continue
            if url not in check_cache:
                if check_cache:
                    time.sleep(.5)
                check_cache[url] = check_image(url)
            status, code = check_cache[url]
            link.update(verification=status, http_status=code)
            if status == "access_blocked":
                cdn_blocked = True
            primary = row["photos"][0]["photo_url"] if row["photos"] else None
            already_in_gallery = any(p["photo_url"] == url for p in row["photos"])
            if already_in_gallery:
                link["protection"] = "existing_gallery_variant"
            # Primary ownership does not establish secondary-gallery ownership.
            link["eligible"] = (status == "working" and row["ownership"] == "retailer"
                                and row["managed_url"] == primary and link["kind"] != "gallery"
                                and not already_in_gallery)
        if row["ownership"] != "retailer":
            entry["outcome"] = "ownership_review_required"
        elif row["photos"] and row["managed_url"] != row["photos"][0]["photo_url"]:
            entry["outcome"] = "external_photo_edit_protected"
        else:
            entry["outcome"] = "preview_only"
    summary = dict(products_in_preview=len(results),
                   affected_links=sum(len(r["links"]) for r in results),
                   verified_eligible_links=sum(bool(l.get("eligible")) for r in results for l in r["links"]),
                   proposed_same_image_links=sum(bool(l.get("new_url")) for r in results for l in r["links"]),
                   outcomes=dict(Counter(r["outcome"] for r in results)), production_writes=0)
    result = dict(version=1, read_only=True, target=target, started_at=started, finished_at=now(),
                  limit=limit, seconds=seconds, inventory_totals=totals, summary=summary, products=results)
    result["checksum"] = digest(result)
    return result


def write_reports(result, directory):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / "preview.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    rows = []
    for product in result["products"]:
        p = product["snapshot"]
        for link in product["links"]:
            rows.append(dict(product_id=p["product_id"], sku=p["sku"], name=p["name"],
                             ownership=p["ownership"], is_available=p["is_available"],
                             outcome=product["outcome"], kind=link["kind"],
                             old_url=link["old_url"], proposed_url=link.get("new_url"),
                             verification=link.get("verification"), eligible=link.get("eligible", False)))
    with (root / "links.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["product_id", "sku", "name", "ownership", "is_available", "outcome",
                  "kind", "old_url", "proposed_url", "verification", "eligible"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        if rows:
            writer.writerows(rows)
    return root / "preview.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--output", default="generated-artifacts/photo-format-preview")
    args = parser.parse_args()
    dsn, target = database_target(args.production, args.confirm_production)
    result = preview(dsn, target, args.limit, args.seconds)
    path = write_reports(result, args.output)
    print(json.dumps(dict(inventory=result["inventory_totals"], summary=result["summary"])))
    print("Read-only preview:", path)


if __name__ == "__main__":
    main()
