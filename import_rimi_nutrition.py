"""Explicit one-time production import. Default command is a read-only preview."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from fiber_estimator import FiberEstimator
from nutrition_reload_plan import digest
from nutrition_reload_store import connect, utcnow, write_json
from nutriscore_calculator import NutriscoreCalculator
from produce_nutrition_matches import safe_cell
from rimi_nutrition_import_plan import (
    load_approved, plan, seal, validate_manifest, same_data,
)
from rimi_nutrition_import_store import (
    apply_one, category_state, connections, read_rows, restore_one, after_matches,
)

POLICY_FILES = ("fiber_estimation_config.json", "fiber_estimator.py",
                "nutriscore_calculator.py", "rimi_nutrition_import_plan.py",
                "nutrition_reload_plan.py")


def policy_hash():
    return digest({p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in POLICY_FILES})


def write_csv(path, rows, fields=None):
    rows = list(rows)
    if fields is None:
        fields = list(dict.fromkeys(key for row in rows for key in row))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows({k: safe_cell(v) for k, v in row.items()} for row in rows)


def untouched_fingerprints(conn, ids):
    """All out-of-scope product/nutrition rows, computed server-side, no secrets."""
    result = {}
    with conn.cursor() as cur:
        for table in ("products", "nutritionfacts"):
            # Identifiers come solely from this fixed tuple.
            cur.execute(f"""
                SELECT COUNT(*),md5(COALESCE(string_agg(md5(to_jsonb(t)::text), ''
                    ORDER BY product_id),''))
                FROM public.{table} t WHERE NOT product_id=ANY(%s)
            """, (ids,))
            count, checksum = cur.fetchone()
            result[table] = {"count": count, "checksum": checksum}
    return result


def preview(args, output, dsn, source_dsn, target_hash, source_hash):
    if not args.basis_per_100g_confirmed:
        raise ValueError("Preview requires confirmed per-100-g source basis")
    entries, report_hash = load_approved(
        args.report, args.summary, args.target_baseline, args.source_baseline)
    tids = [int(e["approved"]["target_product_id"]) for e in entries]
    sids = sorted({int(e["approved"]["source_product_id"]) for e in entries})
    tconn, sconn = connect(dsn, True), connect(source_dsn, True)
    try:
        targets, sources = read_rows(tconn, tids), read_rows(sconn, sids)
        calculator, estimator = NutriscoreCalculator(tconn), FiberEstimator()
        rows = []
        for entry in entries:
            target = targets.get(entry["approved"]["target_product_id"])
            source = sources.get(entry["approved"]["source_product_id"])
            rows.append(dict(entry, baseline={"target": target, "source": source},
                             proposal=plan(entry, target, source, calculator, estimator)))
        manifest = seal({
            "version": 1, "created_at": utcnow(), "target": "production",
            "basis": "user_confirmed_per_100g_edible_food",
            "target_hash": target_hash, "source_hash": source_hash,
            "report_sha256": report_hash, "policy_sha256": policy_hash(),
            "categories_sha256": category_state(tconn),
            "untouched_before": untouched_fingerprints(tconn, tids), "rows": rows,
        })
        validate_manifest(manifest)
        write_json(output / "manifest.json", manifest)
        write_json(output / "before-images.json", {
            "manifest_sha256": manifest["sha256"],
            "target_hash": target_hash,
            "rows": [{"target_product_id": e["approved"]["target_product_id"],
                      "before": e["baseline"]["target"]} for e in rows],
        })
        changes = []
        for e in rows:
            for role, key in (("product", "product_changes"), ("nutrition", "nutrition_changes")):
                for field, value in e["proposal"][key].items():
                    changes.append({
                        "target_product_id": e["approved"]["target_product_id"],
                        "target_sku": e["approved"]["target_sku"],
                        "target_name": e["approved"]["target_name"],
                        "rimi_product_id": e["approved"]["source_product_id"],
                        "rimi_sku": e["approved"]["source_sku"],
                        "table": role, "field": field,
                        "before": e["baseline"]["target"][role].get(field), "after": value,
                        "source_warnings": e["approved"]["source_warnings"],
                    })
        write_csv(output / "field-preview.csv", changes)
        counts = dict(Counter(e["proposal"]["status"] for e in rows))
        print(json.dumps({"preview": counts, "complete_sources": sum(
            e["proposal"]["complete"] for e in rows), "manifest": str(output / "manifest.json")}))
    finally:
        tconn.rollback(); tconn.close()
        sconn.rollback(); sconn.close()


def load_manifest(path, target_hash, source_hash=None):
    manifest = json.loads(Path(path).read_text())
    validate_manifest(manifest)
    if manifest["target_hash"] != target_hash or (
            source_hash is not None and manifest["source_hash"] != source_hash):
        raise ValueError("Database target fingerprint mismatch")
    if manifest["policy_sha256"] != policy_hash():
        raise ValueError("Scoring/import policy changed; create a new preview")
    return manifest


def apply(args, output, dsn, source_dsn, target_hash, source_hash):
    manifest = load_manifest(args.manifest, target_hash, source_hash)
    tconn, sconn = connect(dsn, False), connect(source_dsn, True)
    receipts = output / "receipts"
    receipts.mkdir(parents=True, exist_ok=True)
    try:
        if category_state(tconn) != manifest["categories_sha256"]:
            raise ValueError("Categories changed since preview")
        # Do not trust hand-edited write dictionaries: recompute the frozen proposal.
        calculator, estimator = NutriscoreCalculator(tconn), FiberEstimator()
        for e in manifest["rows"]:
            recalculated = plan(e, e["baseline"]["target"], e["baseline"]["source"],
                               calculator, estimator)
            if recalculated != e["proposal"]:
                raise ValueError("Proposal does not match frozen reviewed data")
        tconn.rollback()
        results = []
        for e in manifest["rows"]:
            pid = int(e["approved"]["target_product_id"])
            result = apply_one(tconn, sconn, e, receipts / f"{pid}.json",
                               manifest["categories_sha256"])
            results.append({"target_product_id": pid, **result})
            write_json(output / "apply-results.json", {
                "manifest_sha256": manifest["sha256"], "results": results})
        verify(manifest, results, output, dsn, source_dsn)
    finally:
        tconn.rollback(); tconn.close()
        sconn.rollback(); sconn.close()


def verify(manifest, results, output, dsn, source_dsn):
    tids = [int(e["approved"]["target_product_id"]) for e in manifest["rows"]]
    sids = sorted({int(e["approved"]["source_product_id"]) for e in manifest["rows"]})
    tconn, sconn = connect(dsn, True), connect(source_dsn, True)
    try:
        targets, sources = read_rows(tconn, tids), read_rows(sconn, sids)
        outcomes = {str(r["target_product_id"]): r for r in results}
        errors, audit, remaining = [], [], []
        for entry in manifest["rows"]:
            pair, proposal = entry["approved"], entry["proposal"]
            pid, sid = pair["target_product_id"], pair["source_product_id"]
            target = targets.get(pid)
            result = outcomes[pid]
            source_same = same_data(sources.get(sid), entry["baseline"]["source"])
            if not source_same:
                errors.append(pid + ":source_changed")
            if result["status"] in {"updated", "partial", "already_applied"}:
                if not after_matches(target, entry["baseline"]["target"], proposal):
                    errors.append(pid + ":target_verification_failed")
                receipt_path = output / "receipts" / f"{pid}.json"
                if receipt_path.exists():
                    receipt = json.loads(receipt_path.read_text())
                    if not same_data(target, receipt["after"]):
                        errors.append(pid + ":receipt_verification_failed")
            elif result["status"] == "unchanged" and not same_data(target, entry["baseline"]["target"]):
                errors.append(pid + ":unchanged_target_changed")
            n = (target or {}).get("nutrition") or {}
            p = (target or {}).get("product") or {}
            item = {
                "target_product_id": pid, "target_sku": pair["target_sku"],
                "target_name": pair["target_name"], "target_url": pair["target_url"],
                "rimi_product_id": sid, "rimi_sku": pair["source_sku"],
                "rimi_name": pair["source_name"], "status": result["status"],
                "reason": result.get("reason"), "needs_enrichment": p.get("needs_enrichment"),
                "nutrition_source": p.get("nutrition_source"), "usda_fdc_id": n.get("usda_fdc_id"),
                "nutri_score_grade": n.get("nutri_score_grade"),
                "fiber_unchanged": n.get("fiber") == (entry["baseline"]["target"]["nutrition"] or {}).get("fiber"),
                "missing_source_fields": ";".join(proposal.get("missing_source_fields", [])),
                "source_warnings_accepted": pair["source_warnings"],
                "basis": manifest["basis"],
            }
            audit.append(item)
            if p.get("needs_enrichment"):
                remaining.append(item)
        untouched_after = untouched_fingerprints(tconn, tids)
        if untouched_after != manifest["untouched_before"]:
            errors.append("out_of_scope_product_or_nutrition_rows_changed")
        counts = dict(Counter(r["status"] for r in results))
        report = {"verified_at": utcnow(), "approved": len(results), "outcomes": counts,
                  "remaining_needs_enrichment": len(remaining), "verification_errors": errors,
                  "untouched_after": untouched_after,
                  "target_fiber_and_flags_preserved": not any(
                      e.endswith(":target_verification_failed") for e in errors)}
        write_csv(output / "import-audit.csv", audit)
        write_csv(output / "remaining-enrichment.csv", remaining, list(audit[0]))
        write_json(output / "verification.json", report)
        print(json.dumps(report))
        if errors or counts.get("failed"):
            raise ValueError("Post-apply verification reported discrepancies; inspect audit")
    finally:
        tconn.rollback(); tconn.close()
        sconn.rollback(); sconn.close()


def restore(args, output, dsn, target_hash):
    manifest = load_manifest(args.manifest, target_hash)
    conn = connect(dsn, False)
    try:
        results = []
        for entry in manifest["rows"]:
            pid = int(entry["approved"]["target_product_id"])
            path = output / "receipts" / f"{pid}.json"
            if not path.exists():
                continue
            receipt = json.loads(path.read_text())
            if receipt["product_id"] != pid or not same_data(
                    receipt["before"], entry["baseline"]["target"]):
                raise ValueError("Restore receipt identity/baseline mismatch")
            if not after_matches(receipt["after"], receipt["before"], entry["proposal"]):
                raise ValueError("Restore receipt does not match allowed proposal")
            results.append({"target_product_id": pid, **restore_one(conn, receipt)})
            write_json(output / "restore-results.json", results)
        print(json.dumps(dict(Counter(r["status"] for r in results))))
    finally:
        conn.rollback(); conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "apply", "restore"), default="preview", nargs="?")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    parser.add_argument("--basis-per-100g-confirmed", action="store_true")
    parser.add_argument("--report", default="generated-artifacts/rimi-produce-2026-10-11/matches.csv")
    parser.add_argument("--summary", default="generated-artifacts/rimi-produce-2026-10-11/summary.json")
    parser.add_argument("--target-baseline")
    parser.add_argument("--source-baseline")
    parser.add_argument("--manifest")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if not args.production or (args.command != "preview" and not args.confirm_production):
            raise ValueError("Require --production; writes also require --confirm-production")
        if args.command == "preview" and not (args.target_baseline and args.source_baseline):
            raise ValueError("Preview requires the original reviewed snapshot files")
        if args.command != "preview" and not args.manifest:
            raise ValueError("Apply/restore requires --manifest")
        output = Path(args.output)
        if not output.resolve().is_relative_to(Path("generated-artifacts").resolve()):
            raise ValueError("Outputs must be under generated-artifacts/")
        output.mkdir(parents=True, exist_ok=True)
        if args.command == "preview" and (output / "manifest.json").exists():
            raise ValueError("Do not overwrite an existing preview/backup; choose a new output")
        if args.command != "preview" and Path(args.manifest).resolve() != (output / "manifest.json").resolve():
            raise ValueError("Apply/restore must use the manifest and receipts in the same output directory")
        dsn, source_dsn, target_hash, source_hash = connections()
        if args.command == "preview":
            preview(args, output, dsn, source_dsn, target_hash, source_hash)
        elif args.command == "apply":
            apply(args, output, dsn, source_dsn, target_hash, source_hash)
        else:
            restore(args, output, dsn, target_hash)
    except Exception as exc:
        # Known validation messages are safe; database errors may expose credentials.
        print("Stopped: " + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
