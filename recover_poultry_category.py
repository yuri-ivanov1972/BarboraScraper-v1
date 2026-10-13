#!/usr/bin/env python3
"""Production-only CLI. Preview is read-only; Apply requires its approved checksum."""

import argparse
import json
import os
from pathlib import Path

from poultry_category_recovery import preview_recovery, apply_recovery
from product_refresh_store import RefreshError


def product_summary(item):
    plan = item["plan"]
    product = dict(item["snapshot"]["product"], **plan["product_changes"])
    nutrition = dict(item["snapshot"].get("nutrition") or {}, **plan["nutrition_changes"])
    return {"sku": item["sku"], "name": item["candidate"]["name"], "new": item["new"],
            "nutrition_complete": plan["nutrition_complete"], "fiber": nutrition.get("fiber"),
            "nutri_score_grade": nutrition.get("nutri_score_grade"), "nova_score": product.get("nova_score"),
            "photos": len(plan["photos"] or item["snapshot"]["photos"]), "notes": plan["notes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preview", "apply"))
    parser.add_argument("--production", action="store_true", required=True)
    parser.add_argument("--preview-file", default="generated-artifacts/poultry-recovery-preview.json")
    parser.add_argument("--approve-sha")
    args = parser.parse_args()
    if args.mode == "apply" and not args.approve_sha:
        parser.error("Apply requires --approve-sha for the preview explicitly approved by the user.")
    if args.mode == "preview" and args.approve_sha:
        parser.error("A preview cannot approve itself.")
    try:
        dsn = os.environ["PROD_DATABASE_URL"]
        path = Path(args.preview_file)
        if args.mode == "preview":
            preview = preview_recovery(dsn)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"category": preview["category"], "create_category": preview["create_category"],
                              "products": [product_summary(i) for i in preview["items"]],
                              "approval_sha256": preview["sha256"], "preview_file": str(path)}, ensure_ascii=False))
        else:
            preview = json.loads(path.read_text(encoding="utf-8"))
            result = apply_recovery(preview, dsn, args.approve_sha)
            path.with_suffix(".result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False))
    except RefreshError as exc:
        if args.mode == "apply" and "preview" in locals():
            failed_sku = getattr(exc, "failed_sku", None)
            report = {"status": "not_applied", "production_changes_saved": False,
                      "error": str(exc), "failed_sku": failed_sku,
                      "products": [{"sku": i["sku"], "status": "failed_and_rolled_back"
                                    if i["sku"] == failed_sku else "not_applied"}
                                   for i in preview.get("items", [])]}
            path.with_suffix(".result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        parser.exit(1, str(exc) + "\n")
    except Exception:
        parser.exit(1, "Recovery could not run. Check the configuration or website availability; no unsafe fallback was used.\n")


if __name__ == "__main__":
    main()
