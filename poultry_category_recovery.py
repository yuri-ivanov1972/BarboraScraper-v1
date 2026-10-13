"""Approved, atomic recovery of one category using the existing full-refresh pipeline."""

from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import Json

from fiber_estimator import FiberEstimator
from nutrition_reload_plan import digest
from nutriscore_calculator import NutriscoreCalculator
from poultry_recovery_source import CODE, PATH, URL, NAME, PARENT_CODE, ROOT_CODE, fetch_candidates
from product_refresh_plan import build_plan
from product_refresh_store import (
    RefreshError, connect, database_identity, capture, context_for, policy_hash, persist_refresh_plan,
)


class RecoveryApplyError(RefreshError):
    """Safe failure attribution; never include raw SQL/connection diagnostics."""

    def __init__(self, message, failed_sku=None):
        self.failed_sku = failed_sku
        super().__init__(message + (f" Failed SKU: {failed_sku}." if failed_sku else ""))


def recovery_policy():
    return digest([policy_hash(), Path(__file__).read_text(),
                   Path("poultry_recovery_source.py").read_text(),
                   Path("product_refresh_store.py").read_text()])


def state(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_jsonb(c) FROM public.normalized_categories c ORDER BY category_id")
        categories = [r[0] for r in cur.fetchall()]
        cur.execute("""
            SELECT to_jsonb(j) FROM public.category_processing_jobs j
            WHERE category_code=%s ORDER BY id
        """, (CODE,))
        jobs = [r[0] for r in cur.fetchall()]
    return {"categories": categories, "jobs": jobs}


def planned_category(baseline):
    categories = baseline["categories"]
    roots = [c for c in categories if c["barbora_category_code"] == ROOT_CODE]
    parents = [c for c in categories if c["barbora_category_code"] == PARENT_CODE]
    if len(roots) != 1 or len(parents) != 1:
        raise RefreshError("The verified root or poultry parent is missing/ambiguous.")
    root, parent = roots[0], parents[0]
    parts = PATH.split("/")
    if (root["level"] != 1 or root["parent_category_id"] is not None
            or parent["level"] != 2 or parent["parent_category_id"] != root["category_id"]
            or [root["normalized_category"], parent["normalized_category"]] != parts[:2]):
        raise RefreshError("The category hierarchy no longer matches the approved website path.")
    existing = [c for c in categories if c["barbora_category_code"] == CODE]
    same_path = [c for c in categories if c["parent_category_id"] == parent["category_id"]
                 and c["normalized_category"] == parts[2]]
    if len(existing) > 1 or (same_path and same_path != existing):
        raise RefreshError("Conflicting category UUID/path. No category was replaced.")
    if existing:
        category = existing[0]
        if (category["level"] != 3 or category["parent_category_id"] != parent["category_id"]
                or category["normalized_category"] != parts[2] or category["name_lv"] != NAME):
            raise RefreshError("Existing category metadata conflicts with the recovery.")
    else:
        category = {"category_id": max(c["category_id"] for c in categories) + 1,
                    "barbora_category_code": CODE, "name_lv": NAME, "name_en": "Minced Poultry",
                    "level": 3, "parent_category_id": parent["category_id"], "normalized_category": parts[2]}
    if any(j["status"] in {"queued", "processing", "in_progress"} for j in baseline["jobs"]):
        raise RefreshError("An active job already exists for this category. Wait for it to finish.")
    return category, not bool(existing)


def empty_snapshot(candidate, category_id, product_id=0):
    return {"product": {"product_id": product_id, "sku": candidate["sku"], "name": "",
                       "barbora_url": candidate["fetched_url"], "category_id": category_id,
                       "rimi_category_code": None, "needs_enrichment": True,
                       "name_manual_edit": False, "is_hidden": False, "country_of_origin": None},
            "nutrition": None, "brand": None, "producer": None, "photos": [], "market": None,
            "ingredient_mapping": [], "validation": None, "category_path": PATH}


def snapshot_for(conn, candidate, category_id, lock=False):
    with conn.cursor() as cur:
        cur.execute("SELECT product_id FROM public.products WHERE sku=%s", (candidate["sku"],))
        row = cur.fetchone()
    return (capture(conn, row[0], lock=lock), False) if row else (empty_snapshot(candidate, category_id), True)


def planned_context(conn, snapshot, candidate, category, create):
    context = context_for(conn, snapshot, candidate)
    if create:
        context["categories"].append(category)
    return context


def preview_recovery(dsn, source=None):
    candidates = fetch_candidates(source)
    conn = connect(dsn, True)
    try:
        baseline = state(conn)
        category, create = planned_category(baseline)
        calculator, estimator = NutriscoreCalculator(conn), FiberEstimator()
        items = []
        for candidate in candidates:
            snapshot, new = snapshot_for(conn, candidate, category["category_id"])
            context = planned_context(conn, snapshot, candidate, category, create)
            plan = build_plan(snapshot, candidate, context, calculator, estimator)
            items.append({"sku": candidate["sku"], "new": new, "candidate": candidate,
                          "snapshot": snapshot, "context": context, "plan": plan})
        preview = {"website_url": URL, "category": category, "create_category": create,
                   "baseline": baseline, "items": items, "database": database_identity(dsn),
                   "policy": recovery_policy(), "fetched_at": datetime.now(timezone.utc).isoformat()}
        preview["sha256"] = digest(preview)
        return preview
    except RefreshError:
        raise
    except Exception:
        raise RefreshError("Could not prepare the recovery preview. No database data was changed.") from None
    finally:
        conn.rollback()
        conn.close()


def changed(plan):
    return any(plan[k] for k in ("product_changes", "nutrition_changes", "links", "photos", "market"))


def apply_recovery(preview, dsn, approval_sha256=None):
    checksum = digest({k: v for k, v in preview.items() if k != "sha256"})
    if not approval_sha256 or approval_sha256 != preview.get("sha256") or checksum != approval_sha256:
        raise RefreshError("Explicit approval of this exact, unchanged preview is required.")
    if preview["database"] != database_identity(dsn) or preview["policy"] != recovery_policy():
        raise RefreshError("Database or recovery rules changed. Prepare a fresh preview.")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(preview["fetched_at"])).total_seconds()
    if not 0 <= age <= 3600:
        raise RefreshError("Recovery preview expired. Prepare a fresh preview for approval.")
    if preview["website_url"] != URL or preview["category"]["barbora_category_code"] != CODE:
        raise RefreshError("Only the approved minced-poultry category can be recovered.")
    conn = connect(dsn, False)
    current_sku = None
    try:
        with conn.cursor() as cur:
            # This table uses manually allocated IDs, not a sequence. This short lock
            # makes MAX+1 collision-safe even against writers not using advisory locks.
            cur.execute("LOCK TABLE public.normalized_categories IN SHARE ROW EXCLUSIVE MODE")
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("category-recovery:" + CODE,))
        if state(conn) != preview["baseline"]:
            raise RefreshError("Categories or category jobs changed. Prepare a fresh preview.")
        category, create = planned_category(preview["baseline"])
        if category != preview["category"] or create != preview["create_category"]:
            raise RefreshError("Category proposal changed. Prepare a fresh preview.")
        calculator, estimator = NutriscoreCalculator(conn), FiberEstimator()
        # Validate ALL baselines before any writes, including shared ingredient frequency
        # changes that processing the first product would otherwise cause itself.
        approved = []
        seen = set()
        for item in preview["items"]:
            candidate = item["candidate"]
            if (item["sku"] in seen or candidate["sku"] != item["sku"]
                    or candidate.get("category_code") != CODE or candidate.get("category_path") != PATH):
                raise RefreshError("Recovery product identity/scope is invalid.")
            seen.add(item["sku"])
            snapshot, new = snapshot_for(conn, candidate, category["category_id"], lock=True)
            if new != item["new"] or snapshot != item["snapshot"]:
                raise RefreshError("A target product changed since the preview. Prepare a fresh preview.")
            context = planned_context(conn, snapshot, candidate, category, create)
            if context != item["context"]:
                raise RefreshError("Ingredient/category context changed. Prepare a fresh preview.")
            plan = build_plan(snapshot, candidate, context, calculator, estimator)
            if plan != item["plan"]:
                raise RefreshError("A product proposal changed. Prepare a fresh preview.")
            approved.append((item, snapshot))
        if not approved:
            raise RefreshError("An empty product recovery cannot be applied.")
        if not create and not any(i["new"] or changed(i["plan"]) for i, _ in approved):
            conn.rollback()
            return {"status": "no_changes", "category_id": category["category_id"],
                    "products": [{"sku": i["sku"], "status": "unchanged"} for i, _ in approved]}
        with conn.cursor() as cur:
            if create:
                cur.execute("""
                    INSERT INTO public.normalized_categories
                    (category_id,barbora_category_code,name_lv,name_en,parent_category_id,level,normalized_category)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                """, tuple(category[k] for k in ("category_id", "barbora_category_code", "name_lv", "name_en",
                                                "parent_category_id", "level", "normalized_category")))
            outcomes = []
            for item, snapshot in approved:
                current_sku = item["sku"]
                if item["new"]:
                    cur.execute("""
                        INSERT INTO public.products(sku,name,barbora_url,category_id,needs_enrichment,country_of_origin)
                        VALUES (%s,'',%s,%s,TRUE,NULL) RETURNING product_id
                    """, (item["sku"], item["candidate"]["fetched_url"], category["category_id"]))
                    snapshot["product"]["product_id"] = cur.fetchone()[0]
                if item["new"] or changed(item["plan"]):
                    persist_refresh_plan(conn, snapshot, item["plan"])
                outcomes.append({"sku": item["sku"], "product_id": snapshot["product"]["product_id"],
                                 "status": "created" if item["new"] else "updated" if changed(item["plan"]) else "unchanged"})
            current_sku = None
            # A completed audit job, never an executable queue job. No broad worker
            # initialization/claiming, schema setup, or unrelated queue processing.
            cur.execute("""
                INSERT INTO public.category_processing_jobs
                (category_code,category_id,total_products,processed_count,status,completed_at,
                 requested_by,update_mode,notes)
                VALUES (%s,%s,%s,%s,'completed',CURRENT_TIMESTAMP,'category_recovery','full',%s) RETURNING id
            """, (CODE, category["category_id"], len(outcomes), len(outcomes),
                  "Atomic full-information recovery approved with preview " + approval_sha256))
            job_id = cur.fetchone()[0]
            for item, _ in approved:
                cur.execute("""
                    INSERT INTO public.product_processing_log(job_id,sku,status,product_url)
                    VALUES (%s,%s,'completed',%s)
                """, (job_id, item["sku"], item["candidate"]["fetched_url"]))
            cur.execute("""
                INSERT INTO public.job_events(job_id,event_type,message,metadata)
                VALUES (%s,'job_completed',%s,%s)
            """, (job_id, "Full-information category recovery completed",
                  Json({"approval_sha256": approval_sha256, "products": outcomes})))
        conn.commit()
        return {"status": "completed", "category_id": category["category_id"], "job_id": job_id,
                "category_created": create, "products": outcomes}
    except RefreshError:
        conn.rollback()
        raise
    except (psycopg2.errors.SerializationFailure, psycopg2.errors.LockNotAvailable,
            psycopg2.errors.DeadlockDetected, psycopg2.IntegrityError):
        conn.rollback()
        raise RecoveryApplyError("Concurrent recovery/update detected. Everything rolled back; prepare a fresh preview.",
                                 current_sku) from None
    except Exception:
        conn.rollback()
        raise RecoveryApplyError("Recovery failed. All category and product changes rolled back.", current_sku) from None
    finally:
        conn.close()
