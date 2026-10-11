"""One-time read-only Rimi reference report. There is intentionally no apply mode."""

import argparse
import csv
import io
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from produce_identity import FAMILIES, compatible, fold, hits, identify
from produce_match_quality import BASIS_URL, NUTRIENTS, assess, fdc_conflicts
from rimi_produce_reader import capture


def safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, str):
        position = 0
        while position < len(value) and (value[position].isspace() or ord(value[position]) < 32):
            position += 1
        if value[position:position+1] in ("=", "+", "-", "@"):
            return "'" + value
    return value


def record_columns(prefix, row):
    p, n = row["product"], row.get("nutrition") or {}
    result = {
        prefix + "product_id": p["product_id"], prefix + "sku": str(p["sku"]),
        prefix + "name": p["name"], prefix + "category": row["category_path"],
        prefix + "url": p.get("barbora_url") or p.get("rimi_url") or "",
        prefix + "source": p.get("nutrition_source") or "unknown",
        prefix + "available": row["available"], prefix + "availability_at": row["availability_at"],
        prefix + "nutrition_date": n.get("data_source_date"),
        prefix + "product_updated_at": p.get("updated_at"),
        prefix + "usda_fdc_id": n.get("usda_fdc_id"),
        prefix + "usda_reference_url": (
            f"https://fdc.nal.usda.gov/food-details/{n['usda_fdc_id']}/nutrients"
            if isinstance(n.get("usda_fdc_id"), int) and n["usda_fdc_id"] > 0 else ""),
        prefix + "manual_edit": n.get("nutrition_manual_edit") is True,
        prefix + "is_fiber_correct_recorded": n.get("is_fiber_correct"),
        prefix + "quantity_value": p.get("quantity_value"),
        prefix + "quantity_unit": p.get("quantity_unit"),
        prefix + "ingredients_recorded": n.get("ingredients_text") or p.get("ingredients"),
        prefix + "needs_enrichment": p.get("needs_enrichment"),
        prefix + "enrichment_reviewed": p.get("enrichment_reviewed"),
    }
    for key in NUTRIENTS:
        unit = "kJ" if key == "energy_kj" else "kcal" if key == "energy_kcal" else "g"
        result[prefix + key + "_" + unit] = n.get(key)
    return result


def build_report(targets, sources):
    """Pure/offline matching; the only inputs are recorded catalogue snapshots."""
    if not targets.get("read_only") or not sources.get("read_only"):
        raise ValueError("Report requires explicitly read-only catalogue snapshots")
    source_rows = sources["rows"]
    identities = [identify(row) for row in source_rows]
    conflicts = fdc_conflicts(source_rows, identities)
    references, audit = [], []
    for row, identity in zip(source_rows, identities):
        quality = assess(row, identity, conflicts)
        audit.append(dict(record_columns("source_", row),
                          scope=identity.scope, scope_reason=identity.reason,
                          family=identity.family, stage=identity.stage,
                          attributes=json.dumps(identity.attributes, ensure_ascii=False),
                          quality=quality["state"], core_complete=quality["complete"],
                          nutrition_basis=quality["basis"],
                          warnings="; ".join(quality["warnings"])))
        if identity.family and identity.scope != "excluded" and quality["state"] not in {"unknown_origin", "invalid"}:
            references.append((row, identity, quality))

    report, counts = [], Counter()
    category_counts = {}
    for row in targets["rows"]:
        identity = identify(row)
        p, n = row["product"], row.get("nutrition") or {}
        base = dict(record_columns("target_", row),
                    target_family=identity.family, target_stage=identity.stage,
                    target_attributes=json.dumps(identity.attributes, ensure_ascii=False),
                    target_basis="As recorded; no replacement, rescaling, fiber estimation or score calculation",
                    target_snapshot_at=targets["captured_at"], source_snapshot_at=sources["captured_at"])
        candidates = []
        if identity.scope != "excluded" and identity.family and not n.get("nutrition_manual_edit"):
            for reference, other, quality in references:
                differences = compatible(identity, other)
                if differences is None:
                    continue
                if identity.family == "mixture":
                    # Different known ingredient sets are not comparable blends.
                    left_text = fold(n.get("ingredients_text") or p.get("ingredients"))
                    right_text = fold((reference.get("nutrition") or {}).get("ingredients_text"))
                    left = {f for f, pattern in FAMILIES.items() if hits(pattern, left_text)}
                    right = {f for f, pattern in FAMILIES.items() if hits(pattern, right_text)}
                    if left and right and left != right:
                        continue
                warnings = list(quality["warnings"])
                if identity.scope == "review" or other.scope == "review":
                    warnings.append(identity.reason or other.reason)
                # Completeness and safe identity outrank pack size/brand/availability.
                close = not differences and identity.scope == other.scope == "eligible"
                band = "closer_candidate" if close and quality["state"] == "usable" else "needs_review"
                score = (100 if band == "closer_candidate" else 75) - min(15, 3 * len(differences))
                score += 1 if reference["available"] else 0
                pack_diff = (p.get("quantity_value"), p.get("quantity_unit")) != (
                    reference["product"].get("quantity_value"), reference["product"].get("quantity_unit"))
                explanation = f"Same identified produce: {identity.family}, {identity.stage}"
                if not differences:
                    explanation += "; no conflicting observed variety/form attributes"
                candidates.append(dict(
                    record_columns("source_", reference),
                    candidate_rank=0, confidence=band, ranking_score=score,
                    match_explanation=explanation,
                    differences="; ".join(differences + (["Retail quantity/unit differs; no nutrient rescaling"] if pack_diff else [])),
                    source_core_complete=quality["complete"], source_quality=quality["state"],
                    source_basis=quality["basis"],
                    source_attributes=json.dumps(other.attributes, ensure_ascii=False),
                    source_warnings="; ".join(dict.fromkeys(warnings)),
                ))
        candidates.sort(key=lambda c: (
            c["confidence"] != "closer_candidate", -c["ranking_score"],
            not c["source_core_complete"], c["source_product_id"]))
        if n.get("nutrition_manual_edit"):
            outcome, reason = "manual_protected", "Target nutrition manually edited; no replacement suggested"
            candidates = []
        elif identity.scope == "excluded":
            outcome, reason = "excluded", identity.reason
        elif candidates:
            outcome = "suggested" if candidates[0]["confidence"] == "closer_candidate" else "review_only"
            reason = "Review-only suggestions; no import" if outcome == "review_only" else "Closer, quality-checked candidates; no import"
        elif identity.scope == "review":
            outcome, reason = "unresolved", identity.reason
        else:
            outcome, reason = "unmatched", "No compatible known-origin Rimi nutrition with acceptable quality"
        counts[outcome] += 1
        category_counts.setdefault(row["category_path"], Counter())[outcome] += 1
        if candidates:
            for rank, candidate in enumerate(candidates[:3], 1):
                report.append(dict(base, outcome=outcome, outcome_reason=reason,
                                   **dict(candidate, candidate_rank=rank)))
        else:
            report.append(dict(base, outcome=outcome, outcome_reason=reason))
    counts = {key: counts[key] for key in ("suggested", "review_only", "unmatched",
                                         "unresolved", "excluded", "manual_protected")}
    assert sum(counts.values()) == len(targets["rows"])
    assert len({r["target_product_id"] for r in report}) == len(targets["rows"])
    summary = {
        "target_snapshot_at": targets["captured_at"], "source_snapshot_at": sources["captured_at"],
        "target_read_only": targets["read_only"], "source_read_only": sources["read_only"],
        "target_rows_sha256": targets["rows_sha256"], "source_rows_sha256": sources["rows_sha256"],
        "starting_targets": len(targets["rows"]), "outcomes": counts,
        "fresh_identified_targets": sum(identify(r).scope == "eligible" for r in targets["rows"]),
        "report_rows": len(report), "source_rows": len(source_rows),
        "source_scopes": dict(Counter(a["scope"] for a in audit)),
        "source_quality": dict(Counter(a["quality"] for a in audit)),
        "source_origins": dict(Counter(a["source_source"] for a in audit)),
        "source_nonexcluded_origins": dict(Counter(a["source_source"] for a in audit if a["scope"] != "excluded")),
        "source_usda_ids_with_conflicts": len(conflicts),
        "categories": {key: dict(value) for key, value in category_counts.items()},
        "basis_documentation": BASIS_URL,
        "important_limitations": [
            "No database data, flags, dates, fiber or scores were changed.",
            "Closer candidate means observed produce compatibility and basic quality checks, not independent validation of the original USDA match.",
            "Values are shown as stored, with expected USDA per-100-g edible-food basis; no retail-weight scaling. Row-level basis metadata is absent, and the external Rimi importer has not been inspected.",
            "FDC reuse across different produce identities or conflicting explicit variants requires manual verification.",
            "Unknown-source records are listed in source audit only, never recommended.",
            "Missing fiber does not permit clearing existing target fiber or changing the existing estimation policy.",
            "Ranking scores are not calibrated probabilities. All matches need human review before any future import.",
            "Each database has its own read-only repeatable-read snapshot; these are not a distributed atomic snapshot.",
            "Import SKU columns as text in spreadsheet applications to retain leading zeros.",
        ],
    }
    return report, audit, summary


def to_csv(rows):
    columns = list(dict.fromkeys(key for row in rows for key in row))
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: safe_cell(value) for key, value in row.items()})
    return output.getvalue()


def summary_markdown(summary, rows):
    text = ["# Rimi produce nutrition suggestions", "",
            "Report only. Neither database was modified.", "",
            f"Barbora snapshot: {summary['target_snapshot_at']}",
            f"Rimi snapshot: {summary['source_snapshot_at']}",
            f"Local report date: {datetime.now(ZoneInfo('Europe/Riga')).isoformat()}", "",
            f"Starting available, flagged, unreviewed targets: **{summary['starting_targets']}**.",
            f"Fresh single-produce identities resolved: **{summary['fresh_identified_targets']}**.", "",
            "| Outcome | Products |", "|---|---:|"]
    text += [f"| {key} | {value} |" for key, value in summary["outcomes"].items()]
    text += ["", "Up to three candidates per target; outcome counts count products, not candidate rows.",
             "", "## Source audit", "",
             f"Catalogue records: {summary['source_rows']}",
             f"Provenance: {summary['source_origins']}",
             f"Provenance after non-fresh exclusions: {summary['source_nonexcluded_origins']}",
             f"Scope screening: {summary['source_scopes']}",
             f"Quality screening: {summary['source_quality']}",
             f"USDA reference IDs with identity/variant conflicts: {summary['source_usda_ids_with_conflicts']}",
             "", "## Example closer candidates", ""]
    examples = [r for r in rows if r["outcome"] == "suggested" and r.get("candidate_rank") == 1][:12]
    text += [f"- {r['target_name']} → {r['source_name']} (Rimi SKU {r['source_sku']}; "
             f"recorded origin {r['source_source']}; stored {r['source_energy_kcal_kcal']} kcal, expected per 100 g)" for r in examples]
    text += ["", "## Category reconciliation", "", "| Category | Outcomes |", "|---|---|"]
    text += [f"| {category} | {outcomes} |" for category, outcomes in summary["categories"].items()]
    text += ["", "## Limits and safeguards", ""] + ["- " + s for s in summary["important_limitations"]]
    text += ["", f"USDA basis documentation: {BASIS_URL}", "",
             "This project's existing importer stores FoodData Central nutrient amounts without retail-pack scaling, "
             "and converts sodium mg to salt g. USDA documents nutrient amounts per 100 g edible food. "
             "This verifies USDA's convention and the local importer, not the external Rimi importer, "
             "a laboratory measurement or original food-match verification for each Rimi row. "
             "The source table has no explicit per-row nutrition-basis field; confirm that convention before any future import."]
    return "\n".join(text) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-read-only", action="store_true", required=True)
    parser.add_argument("--output", default="generated-artifacts/rimi-produce-matches")
    args = parser.parse_args(argv)
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        parser.error("Output directory must be empty; existing reports will not be overwritten")
    targets, sources = capture("barbora"), capture("rimi")
    report, audit, summary = build_report(targets, sources)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("matches.csv", report), ("source-audit.csv", audit)):
        (output / name).write_text(to_csv(rows), encoding="utf-8-sig")
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (output / "summary.md").write_text(summary_markdown(summary, report))
    print(json.dumps({key: summary[key] for key in (
        "starting_targets", "outcomes", "report_rows", "source_rows", "source_usda_ids_with_conflicts")}))
    return summary


if __name__ == "__main__":
    main()
