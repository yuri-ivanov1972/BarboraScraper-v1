"""Read-only prices/availability recovery previews; apply requires an approved manifest.

Preview: python barbora_catchup.py --production --confirm-production --limit 3
Full:    python barbora_catchup.py --production --confirm-production
Apply:   python barbora_catchup.py --production --confirm-production --apply FILE

No schema setup, photo maintenance, new-product jobs or enrichment runs here.
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from psycopg2.extras import RealDictCursor, execute_values

from nutrition_reload_store import database_target, connect, digest
from nutrition_reload_source import BarboraSource, SourceError
from barbora_site_data import (category_page, verify_category_path, SiteDataError,
                               RECOVERY_CATEGORY_PATHS)


FIELDS = ("price", "discount_price", "price_per_unit", "discount_price_per_unit",
          "price_per_unit_type", "is_available")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def scalar(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return float(value)


def observation(product, hidden=False):
    # Category adapter has already validated the original market fields.
    price, old = product["price"], product.get("retail_price")
    rate = product["comparative_unit_price"]
    old_rate = product.get("comparative_unit_price_brutto")
    return dict(price=old if old is not None and old > price else price,
                discount_price=price if old is not None and old > price else None,
                price_per_unit=old_rate if old_rate is not None and old_rate > rate else rate,
                discount_price_per_unit=rate if old_rate is not None and old_rate > rate else None,
                price_per_unit_type=product["comparative_unit"],
                is_available=product["status"] == "active" and not hidden)


def snapshot(dsn):
    conn = connect(dsn, readonly=True)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                WITH RECURSIVE paths AS (
                    SELECT category_id, parent_category_id, name_lv, level,
                           normalized_category::text AS path, barbora_category_code
                    FROM normalized_categories WHERE parent_category_id IS NULL
                    UNION ALL
                    SELECT n.category_id,n.parent_category_id,n.name_lv,n.level,
                           p.path || '/' || n.normalized_category,n.barbora_category_code
                    FROM normalized_categories n JOIN paths p ON p.category_id=n.parent_category_id
                )
                SELECT category_id::text, barbora_category_code, name_lv, path FROM paths
                WHERE level=3 AND barbora_category_code IS NOT NULL ORDER BY path
            """)
            cats = [dict(r) for r in cur.fetchall()]
            cur.execute("""
                SELECT p.product_id::text, p.sku, p.name, p.is_hidden,
                       p.category_id::text, h.price_history_id::text,
                       h.price,h.discount_price,h.price_per_unit,h.discount_price_per_unit,
                       h.price_per_unit_type,h.is_available
                FROM products p LEFT JOIN LATERAL (
                    SELECT * FROM product_price_history WHERE product_id=p.product_id
                    ORDER BY recorded_at DESC,price_history_id DESC LIMIT 1
                ) h ON TRUE
            """)
            products = {r["sku"]: {k: scalar(v) for k, v in dict(r).items()} for r in cur.fetchall()}
        return cats, products
    finally:
        conn.close()


def preview(dsn, target, limit=None, source=None, only_paths=None, category_paths=None):
    started = timestamp()
    cats, products = snapshot(dsn)
    source = source or BarboraSource(delay=.35, retries=1, max_pages=30)
    selected = cats[:limit] if limit is not None else cats
    if category_paths is not None:
        if limit is not None or only_paths is not None:
            raise ValueError("Explicit category scope cannot be combined with sampling or retry")
        requested = set(category_paths)
        if not requested or not requested.issubset(RECOVERY_CATEGORY_PATHS):
            raise ValueError("Recovery scope must use the confirmed category paths")
        selected = [c for c in cats if c["path"] in requested]
        if len(selected) != len(requested) or {c["path"] for c in selected} != requested:
            raise ValueError("Recovery category scope is missing or ambiguous in the database")
    if only_paths is not None:
        selected = [c for c in selected if c["path"] in only_paths]
    coverage, sightings, new = [], {}, {}
    for i, cat in enumerate(selected, 1):
        report = dict(cat, status="failed", products=0, warning="",
                      advertised_count=None, returned_count=0, identity_evidence=None)
        try:
            collected, count, short = {}, None, None
            for page in range(1, source.max_pages + 1):
                html, url = source.fetch(source.helper.build_category_url(cat["path"], page))
                data = category_page(html, page, short, cat["path"])
                report.update(advertised_count=data["count"],
                              identity_evidence=data["identity_evidence"])
                short = data["short_id"]
                verify_category_path(data, cat["path"])
                if data["category_id"] != cat["barbora_category_code"]:
                    report["warning"] = "New retailer UUID; verified by exact full category path"
                if count is not None and count != data["count"]:
                    raise ValueError("category_count_changed")
                count = data["count"]
                for p in data["products"]:
                    if p["id"] in collected:
                        raise ValueError("repeated_pagination_sku")
                    collected[p["id"]] = p
                report["returned_count"] = len(collected)
                if len(collected) == count:
                    break
            if len(collected) != count:
                raise ValueError("category_page_limit")
            # Add observations only after every page of the category succeeds.
            for sku, p in collected.items():
                if sku not in products:
                    new[sku] = dict(sku=sku, name=p["title"], reason="new_product_excluded")
                    continue
                current = observation(p, bool(products[sku]["is_hidden"]))
                entry = dict(sku=sku, name=products[sku]["name"],
                             product_id=products[sku]["product_id"],
                             baseline={k: products[sku][k] for k in FIELDS},
                             baseline_history_id=products[sku]["price_history_id"],
                             observed=current, observed_at=timestamp(),
                             category_path=cat["path"])
                entry["changed"] = entry["baseline"] != current
                if sku in sightings and sightings[sku]["observed"] != current:
                    sightings[sku]["conflict"] = True
                else:
                    entry["conflict"] = sightings.get(sku, {}).get("conflict", False)
                    sightings[sku] = entry
            report.update(status="complete", products=len(collected),
                          warning="Verified empty category" if count == 0 else report["warning"])
        except Exception as exc:
            # Never include raw request/connection diagnostics or tokens in reports.
            report["warning"] = str(exc) if isinstance(exc, (SourceError, SiteDataError)) or type(exc) is ValueError else type(exc).__name__
            if isinstance(exc, SiteDataError):
                for field in ("advertised_count", "returned_count"):
                    if field in exc.details:
                        report[field] = exc.details[field]
        coverage.append(report)
        print(f"[{i}/{len(selected)}] {cat['path']}: {report['status']} "
              f"({report['products']}) {report['warning']}", flush=True)
    entries = list(sightings.values())
    selected_ids = {c["category_id"] for c in selected}
    missing = [dict(sku=p["sku"], name=p["name"], reason="not_seen_in_complete_category")
               for sku, p in products.items() if sku not in sightings and (
                   category_paths is None or p.get("category_id") in selected_ids)]
    conflicts = sum(bool(p.get("conflict")) for p in entries)
    complete = (limit is None and only_paths is None and
                all(c["status"] == "complete" for c in coverage) and bool(entries) and not conflicts)
    result = dict(version=1, target=target, started_at=started, finished_at=timestamp(),
                  scope="prices_availability_only", bounded=limit is not None,
                  complete=complete, categories_total=len(selected) if category_paths is not None else len(cats),
                  coverage=coverage,
                  products=entries, excluded_new=list(new.values()), not_seen=missing,
                  summary=dict(categories_checked=len(coverage),
                               failed_categories=sum(c["status"] != "complete" for c in coverage),
                               existing_observed=len(entries), changes=sum(p["changed"] for p in entries),
                               conflicts=conflicts, new_excluded=len(new), not_seen=len(missing)))
    if category_paths is not None:
        result["selection"] = dict(type="confirmed_category_paths", paths=sorted(set(category_paths)))
    result["checksum"] = digest(result)
    return result


def retry_failed(dsn, target, prior, source=None):
    """One bounded retry of failed categories; still entirely read-only."""
    original = dict(prior)
    checksum = original.pop("checksum", None)
    if (digest(original) != checksum or prior["target"] != target or prior["bounded"]
            or prior["scope"] != "prices_availability_only"):
        raise ValueError("A valid full preview for this database is required")
    if prior.get("selection"):
        raise ValueError("Generate a fresh scoped preview instead of merging a partial retry")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(prior["started_at"])).total_seconds()
    if age > 3600:
        raise ValueError("Preview observations expired; restart the full preview")
    paths = {c["path"] for c in prior["coverage"] if c["status"] != "complete"}
    if not paths:
        raise ValueError("No failed categories to retry")
    fresh = preview(dsn, target, source=source, only_paths=paths)
    reports = {c["path"]: c for c in fresh["coverage"]}
    result = json.loads(json.dumps(prior))
    result.pop("checksum", None)
    result["coverage"] = [reports.get(c["path"], c) for c in prior["coverage"]]
    products = {p["sku"]: p for p in prior["products"]}
    for p in fresh["products"]:
        if p["sku"] in products and products[p["sku"]]["observed"] != p["observed"]:
            products[p["sku"]]["conflict"] = True
        else:
            products[p["sku"]] = p
    result["products"] = list(products.values())
    new = {p["sku"]: p for p in prior["excluded_new"] + fresh["excluded_new"]}
    result["excluded_new"] = list(new.values())
    result["not_seen"] = [p for p in fresh["not_seen"] if p["sku"] not in products]
    result["finished_at"] = timestamp()
    failed = sum(c["status"] != "complete" for c in result["coverage"])
    conflicts = sum(bool(p.get("conflict")) for p in products.values())
    result["complete"] = (not failed and not conflicts and bool(products) and
                          len(result["coverage"]) == result["categories_total"])
    result["summary"] = dict(categories_checked=len(result["coverage"]), failed_categories=failed,
                             existing_observed=len(products), changes=sum(p["changed"] for p in products.values()),
                             conflicts=conflicts, new_excluded=len(new), not_seen=len(result["not_seen"]))
    result["checksum"] = digest(result)
    return result


def write_reports(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "preview.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    rows = []
    for p in result["products"]:
        if p["changed"] or p.get("conflict"):
            row = dict(sku=p["sku"], name=p["name"], conflict=p.get("conflict", False))
            for k in FIELDS:
                row["old_" + k] = p["baseline"][k]
                row["new_" + k] = p["observed"][k]
            rows.append(row)
    for filename, values in (("changes.csv", rows), ("coverage.csv", result["coverage"]),
                             ("new-products-excluded.csv", result["excluded_new"]),
                             ("not-seen.csv", result["not_seen"])):
        with (directory / filename).open("w", newline="", encoding="utf-8-sig") as f:
            if values:
                writer = csv.DictWriter(f, fieldnames=list(values[0]))
                writer.writeheader()
                writer.writerows(values)
    return path


def apply(dsn, target, approved, accept_exclusions=False):
    manifest = dict(approved)
    checksum = manifest.pop("checksum", None)
    if digest(manifest) != checksum or manifest["target"] != target:
        raise ValueError("Preview checksum or database target changed")
    coverage = manifest.get("coverage", [])
    selection = manifest.get("selection")
    if selection is not None:
        paths = selection.get("paths", [])
        if (selection.get("type") != "confirmed_category_paths" or not paths
                or len(set(paths)) != len(paths) or not set(paths).issubset(RECOVERY_CATEGORY_PATHS)
                or len(coverage) != len(paths) or manifest.get("categories_total") != len(paths)
                or {c["path"] for c in coverage} != set(paths)):
            raise ValueError("Approved recovery category scope does not match its coverage")
        complete_paths = {c["path"] for c in coverage if c["status"] == "complete"}
        if any(p.get("category_path") not in complete_paths for p in manifest["products"]):
            raise ValueError("Observation is outside the approved complete categories")
    all_attempted = (bool(coverage) and len(coverage) == manifest.get("categories_total")
                     and len({c["path"] for c in coverage}) == len(coverage)
                     and all(c["status"] in {"complete", "failed"} for c in coverage))
    if (manifest["bounded"] or manifest["scope"] != "prices_availability_only"
            or not manifest["products"] or any(p.get("conflict") for p in manifest["products"])
            or (not manifest["complete"] and not (accept_exclusions and all_attempted))):
        raise ValueError("Full preview required; unresolved exclusions need explicit approval")
    now = datetime.now(timezone.utc)
    if (now - datetime.fromisoformat(manifest["finished_at"])).total_seconds() > 600:
        raise ValueError("Preview expired: generate and approve a fresh preview")
    if (now - datetime.fromisoformat(manifest["started_at"])).total_seconds() > 3600:
        raise ValueError("Observations expired: generate and approve a fresh preview")
    conn = connect(dsn, readonly=False)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            ids = [int(p["product_id"]) for p in manifest["products"]]
            cur.execute("""SELECT product_id::text,sku,is_hidden FROM products
                           WHERE product_id=ANY(%s) ORDER BY product_id FOR UPDATE""", (ids,))
            identities = {p["product_id"]: p for p in cur.fetchall()}
            cur.execute("""SELECT p.product_id::text,h.price_history_id::text,
                                  h.price,h.discount_price,h.price_per_unit,
                                  h.discount_price_per_unit,h.price_per_unit_type,h.is_available
                           FROM products p LEFT JOIN LATERAL (
                               SELECT * FROM product_price_history WHERE product_id=p.product_id
                               ORDER BY recorded_at DESC,price_history_id DESC LIMIT 1
                           ) h ON TRUE WHERE p.product_id=ANY(%s)""", (ids,))
            latest = {p["product_id"]: p for p in cur.fetchall()}
            changes = []
            # Validate every observed baseline, not only the rows with changes.
            for p in sorted(manifest["products"], key=lambda x: x["product_id"]):
                current = identities.get(p["product_id"])
                if not current or current["sku"] != p["sku"] or (
                        current["is_hidden"] and p["observed"]["is_available"]):
                    raise ValueError("Product identity or visibility changed; new preview required")
                row = latest.get(p["product_id"])
                baseline = {k: scalar(row[k]) if row else None for k in FIELDS}
                # Idempotence: an exact observation already saved requires no new row.
                if baseline == p["observed"]:
                    continue
                if baseline != p["baseline"] or (
                        (row["price_history_id"] if row else None) != p["baseline_history_id"]):
                    raise ValueError("Price baseline changed; new preview required")
                changes.append([p["product_id"]] + [p["observed"][k] for k in FIELDS])
            if changes:
                fields = ",".join(FIELDS)
                execute_values(cur, f"""INSERT INTO product_price_history
                               (product_id,{fields},data_source,recorded_at) VALUES %s""",
                               changes,
                               template="(%s,%s,%s,%s,%s,%s,%s,'redesign_catchup',CURRENT_TIMESTAMP)",
                               page_size=500)
            conn.commit()
            return len(changes)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--recover-three", action="store_true",
                        help="Preview only the three user-confirmed recovery categories")
    parser.add_argument("--output", default="generated-artifacts/barbora-catchup")
    parser.add_argument("--apply", help="Explicitly approved full preview JSON")
    parser.add_argument("--retry-failed", help="Read-only retry of failed categories in a full preview")
    parser.add_argument("--accept-exclusions", action="store_true",
                        help="Only with explicit approval: apply verified observations, exclude failed categories")
    args = parser.parse_args()
    if args.apply and args.retry_failed:
        parser.error("Choose apply or read-only retry, not both")
    if args.recover_three and (args.limit is not None or args.retry_failed or args.apply):
        parser.error("--recover-three is an explicit preview scope, not a sample, retry or apply option")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    dsn, target = database_target(args.production, args.confirm_production)
    if args.apply:
        result = apply(dsn, target, json.loads(Path(args.apply).read_text()),
                       accept_exclusions=args.accept_exclusions)
        print(f"Applied {result} current observations; no historical prices invented")
    else:
        result = (retry_failed(dsn, target, json.loads(Path(args.retry_failed).read_text()))
                  if args.retry_failed else preview(
                      dsn, target, args.limit,
                      category_paths=set(RECOVERY_CATEGORY_PATHS) if args.recover_three else None))
        path = write_reports(result, args.output)
        print(json.dumps(result["summary"]), "Complete:", result["complete"], "Manifest:", path)


if __name__ == "__main__":
    main()
