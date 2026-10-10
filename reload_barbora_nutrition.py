#!/usr/bin/env python3
"""One-time reload. Preview by default; apply only an explicitly approved digest."""

import argparse
import csv
import fcntl
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from nutriscore_calculator import NutriscoreCalculator
from fiber_estimator import FiberEstimator
from nutrition_reload_plan import PROPOSAL_POLICY, digest, propose
from nutrition_reload_source import BarboraSource, SourceError
from nutrition_reload_store import (
    apply_one, capture, connect, database_target, utcnow, verify_schema, write_json,
)


def summary(manifest, applied=None):
    rows = manifest["rows"]
    attempted = [r for r in rows if r["outcome"] is not None]
    proposals = [r for r in attempted if r["proposal"]]
    names = sum("name" in r["proposal"]["product_changes"] for r in proposals)
    nutrition = sum(r["proposal"]["nutrition_status"] == "complete" for r in proposals)
    actionable = sum(bool(r["proposal"]["product_changes"] or r["proposal"]["nutrition_changes"])
                     for r in proposals)
    return {
        "selected": len(rows), "attempted": len(attempted), "proposed_updates": actionable,
        "nutrition_recovered": nutrition, "names_to_update": names,
        "name_only_changes": sum("name" in r["proposal"]["product_changes"]
                                 and r["proposal"]["nutrition_status"] != "complete" for r in proposals),
        "manual_protected": sum(any("manual_edit_protected" in n for n in r["proposal"]["notes"])
                                for r in proposals),
        "unchanged": len(proposals) - actionable,
        "still_needing_enrichment_after_proposed_apply": len(rows) - nutrition,
        "failed": sum(r["outcome"] == "source_failed" for r in attempted),
        "nutrition_outcomes": dict(Counter(r["proposal"]["nutrition_status"] for r in proposals)),
        "fiber_outcomes": dict(Counter(r["proposal"].get("fiber_origin", {}).get("kind")
                                      for r in proposals if r["proposal"].get("fiber_origin"))),
        "nutrition_scores_calculated": sum(
            r["proposal"]["nutrition_status"] == "complete"
            and r["proposal"]["nutrition_changes"].get("nutri_score_grade") is not None
            for r in proposals),
        "source_errors": dict(Counter(r.get("error") for r in attempted if r["outcome"] == "source_failed")),
        "apply_outcomes": dict(Counter((applied or {}).values())),
        "updated": sum(v == "updated" for v in (applied or {}).values()),
        "preview_complete": manifest["preview_complete"],
        "approval_sha256": digest(manifest) if manifest["preview_complete"] else None,
    }


def report(path, manifest, applied=None):
    write_json(str(path) + ".summary.json", summary(manifest, applied))
    with open(str(path) + ".csv", "w", newline="") as out:
        columns = ["product_id", "sku", "old_name", "barbora_name", "name_update",
                   "nutrition_status", "old_nutrition", "candidate_nutrition",
                   "proposed_nutrition", "proposed_product_changes", "notes", "fiber_origin",
                   "fetched_url", "recovered_url", "outcome", "error", "apply_outcome"]
        writer = csv.DictWriter(out, fieldnames=columns)
        writer.writeheader()
        for row in manifest["rows"]:
            candidate, proposal = row["candidate"] or {}, row["proposal"] or {}
            values = {
                "product_id": row["product"]["product_id"], "sku": row["product"]["sku"],
                "old_name": row["product"]["name"], "barbora_name": candidate.get("name", ""),
                "name_update": "name" in proposal.get("product_changes", {}),
                "nutrition_status": proposal.get("nutrition_status", ""),
                "old_nutrition": json.dumps(row["nutrition"], ensure_ascii=False),
                "candidate_nutrition": json.dumps(candidate.get("nutrition"), ensure_ascii=False),
                "proposed_nutrition": json.dumps(proposal.get("nutrition_changes"), ensure_ascii=False),
                "proposed_product_changes": json.dumps(proposal.get("product_changes"), ensure_ascii=False),
                "notes": "; ".join(proposal.get("notes", [])),
                "fiber_origin": json.dumps(proposal.get("fiber_origin"), ensure_ascii=False),
                "fetched_url": candidate.get("fetched_url", ""),
                "recovered_url": candidate.get("recovered_url", False),
                "outcome": row["outcome"], "error": row.get("error", ""),
                "apply_outcome": (applied or {}).get(str(row["product"]["product_id"]), ""),
            }
            # Product names are untrusted spreadsheet input.
            for key in ("sku", "old_name", "barbora_name", "fetched_url"):
                if str(values[key]).startswith(("=", "+", "-", "@", "\t", "\r")):
                    values[key] = "'" + str(values[key])
            writer.writerow(values)


def preview(args, dsn, target_hash):
    path = Path(args.manifest)
    rebuild = getattr(args, "rebuild_from", None)
    if rebuild and (path.exists() or Path(rebuild).resolve() == path.resolve()):
        raise ValueError("Rebuild requires a new output manifest; the original must be preserved")
    if rebuild and Path(str(rebuild) + ".apply.json").exists():
        raise ValueError("Cannot rebuild a manifest with an apply checkpoint")
    config = Path(__file__).with_name("fiber_estimation_config.json")
    estimator = FiberEstimator(config)
    conn = connect(dsn, readonly=True)
    try:
        verify_schema(conn)
        if rebuild:
            manifest = json.loads(Path(rebuild).read_text())
            validate_target(manifest, target_hash, args.production)
            if not manifest["preview_complete"]:
                raise ValueError("Rebuild requires a completed source preview")
            manifest["rebuilt_from_sha256"] = digest(manifest)
        elif path.exists():
            manifest = json.loads(path.read_text())
            validate_target(manifest, target_hash, args.production)
            if (manifest.get("proposal_policy") != PROPOSAL_POLICY
                    and any(row.get("proposal") for row in manifest["rows"])):
                raise ValueError("Saved proposals use an obsolete fiber policy; use --rebuild-from with a new output")
        else:
            manifest = capture(conn, target_hash, args.production, args.limit)
            write_json(path, manifest)
        if args.retry_source_errors:
            for row in manifest["rows"]:
                if row["outcome"] == "source_failed":
                    row.update(outcome=None, candidate=None, proposal=None, error=None)
            manifest["preview_complete"] = False
            write_json(path, manifest)
        calculator = NutriscoreCalculator(conn)
        conn.rollback()
    finally:
        conn.close()
    if rebuild:
        for row in manifest["rows"]:
            if row["outcome"] == "previewed":
                row["proposal"] = propose(row, row["candidate"], calculator, estimator)
        manifest["proposals_rebuilt_at"] = utcnow()
    manifest["proposal_policy"] = PROPOSAL_POLICY
    manifest["fiber_estimation_config_sha256"] = digest(json.loads(config.read_text()))
    if rebuild:
        write_json(path, manifest)
        report(path, manifest)
        return summary(manifest)
    source = BarboraSource(delay=args.delay, retries=args.retries, timeout=args.timeout,
                           max_pages=args.max_category_pages)
    pending = [r for r in manifest["rows"] if r["outcome"] is None]
    def fetch(row):
        try:
            return source.product(row), None
        except SourceError as exc:
            return None, str(exc)
        except Exception:
            return None, "parser_failed"
    # Only this small batch of requests is in flight; interruption never extends scope.
    for start in range(0, len(pending), 25):
        batch = pending[start:start+25]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for row, (candidate, error) in zip(batch, pool.map(fetch, batch)):
                row["candidate"], row["error"] = candidate, error
                if error:
                    row["outcome"] = "source_failed"
                else:
                    row["proposal"] = propose(row, candidate, calculator, estimator)
                    row["outcome"] = "previewed"
        write_json(path, manifest)
        report(path, manifest)
        print(json.dumps(summary(manifest)), flush=True)
    manifest["preview_complete"] = all(r["outcome"] is not None for r in manifest["rows"])
    write_json(path, manifest)
    report(path, manifest)
    return summary(manifest)


def validate_target(manifest, target_hash, production):
    if (manifest.get("version") != 1 or manifest.get("target_hash") != target_hash
            or manifest.get("target") != ("production" if production else "development")):
        raise ValueError("Manifest does not match the explicitly selected database")


def apply(args, dsn, target_hash):
    manifest = json.loads(Path(args.manifest).read_text())
    validate_target(manifest, target_hash, args.production)
    if (not manifest["preview_complete"] or not args.approved_sha256
            or args.approved_sha256 != digest(manifest)):
        raise ValueError("Apply requires the exact completed preview approval SHA-256")
    if manifest.get("proposal_policy") != PROPOSAL_POLICY:
        raise ValueError("Obsolete fiber proposals cannot be applied; rebuild and approve the revised preview")
    ids = [r["product"]["product_id"] for r in manifest["rows"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate products in manifest")
    checkpoint_path = args.manifest + ".apply.json"
    state = json.loads(Path(checkpoint_path).read_text()) if Path(checkpoint_path).exists() else {
        "approval_sha256": args.approved_sha256, "started_at": utcnow(), "outcomes": {}
    }
    if state["approval_sha256"] != args.approved_sha256:
        raise ValueError("Apply checkpoint belongs to a different preview")
    conn = connect(dsn, readonly=False)
    try:
        verify_schema(conn)
        conn.rollback()
        for row in manifest["rows"]:
            key = str(row["product"]["product_id"])
            if key in state["outcomes"] and state["outcomes"][key] != "apply_failed":
                continue
            result = apply_one(conn, row)
            state["outcomes"][key] = result
            # Saved only after commit/rollback. On a commit/checkpoint crash,
            # baseline mismatch prevents a repeat write; report for reconciliation.
            write_json(checkpoint_path, state)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FILTER (WHERE needs_enrichment IS TRUE),
                       COUNT(*) FROM public.products WHERE product_id=ANY(%s)
            """, (ids,))
            remaining, existing = cur.fetchone()
        conn.rollback()
        state["still_needing_enrichment_actual"] = remaining
        state["existing_manifest_products"] = existing
        state["finished_at"] = utcnow()
        write_json(checkpoint_path, state)
        report(args.manifest, manifest, state["outcomes"])
    finally:
        conn.close()
    result = summary(manifest, state["outcomes"])
    result["still_needing_enrichment_actual"] = remaining
    result["existing_manifest_products"] = existing
    write_json(args.manifest + ".summary.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--confirm-production", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-sha256")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--delay", type=float, default=0.75)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--max-category-pages", type=int, default=30)
    parser.add_argument("--retry-source-errors", action="store_true",
                        help="Retry only failed source checks in the same frozen scope; produces a new approval digest")
    parser.add_argument("--rebuild-from",
                        help="Recalculate completed saved candidates into a NEW preview manifest, without HTTP requests")
    args = parser.parse_args(argv)
    try:
        if (args.delay < 0.25 or args.retries not in range(4) or args.timeout <= 0
                or args.workers not in range(1, 5) or args.max_category_pages < 1
                or args.limit is not None and args.limit < 1):
            raise ValueError("Invalid bounds: delay >=0.25, workers 1-4, retries 0-3, positive limits")
        if args.approved_sha256 and not args.apply:
            raise ValueError("Approval digest is only accepted with --apply")
        if args.apply and args.limit is not None:
            raise ValueError("Apply cannot change the frozen preview scope with --limit")
        if args.apply and args.retry_source_errors:
            raise ValueError("Source retries are preview-only")
        if args.rebuild_from and (args.apply or args.retry_source_errors or args.limit is not None):
            raise ValueError("Rebuild is preview-only and cannot retry sources or change scope")
        dsn, fingerprint = database_target(args.production, args.confirm_production)
        path = Path(args.manifest)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(path) + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = apply(args, dsn, fingerprint) if args.apply else preview(args, dsn, fingerprint)
        print(json.dumps(result, indent=2), flush=True)
        return 0
    except ValueError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), flush=True)
        return 2
    except Exception:
        print(json.dumps({"status": "failed", "reason": "Operation interrupted or unavailable; resume using the same manifest. Sensitive diagnostics suppressed."}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
