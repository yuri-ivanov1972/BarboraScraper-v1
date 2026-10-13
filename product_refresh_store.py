"""SELECT-only preview and single-product atomic Apply on the Browser's DB target."""

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, Json
from psycopg2.extensions import parse_dsn

from brand_producer import _get_or_create_entity
from fiber_estimator import FiberEstimator
from ingredient_processor import extract_ingredient_tokens
from nutrition_reload_plan import digest
from nutriscore_calculator import NutriscoreCalculator
from product_refresh_plan import build_plan, validate_changes
from product_refresh_source import ProductRefreshSource


class RefreshError(ValueError):
    """Messages safe to show to the user; raw DB/connection errors stay private."""


def database_identity(dsn):
    try:
        info = parse_dsn(dsn)
        return digest([info.get("host"), info.get("port", "5432"), info.get("dbname")])
    except Exception:
        raise RefreshError("The Product Browser database connection is not configured correctly.") from None


def connect(dsn, readonly):
    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=15)
        conn.set_session(readonly=readonly, isolation_level="REPEATABLE READ" if readonly else "SERIALIZABLE")
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='25s'")
            cur.execute("SET LOCAL lock_timeout='5s'")
        return conn
    except Exception:
        if conn:
            conn.close()
        raise RefreshError("Could not connect to the Product Browser database. Please retry.") from None


def capture(conn, product_id, lock=False):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if lock:
            for table in ("products", "nutritionfacts", "productphotos", "product_price_history"):
                cur.execute(sql.SQL("SELECT product_id FROM public.{} WHERE product_id=%s FOR UPDATE").format(
                    sql.Identifier(table)), (product_id,))
        cur.execute("""
            SELECT to_jsonb(p) AS product,to_jsonb(n) AS nutrition,
                   to_jsonb(b) AS brand,to_jsonb(pr) AS producer
            FROM public.products p LEFT JOIN public.nutritionfacts n USING(product_id)
            LEFT JOIN public.brands b ON b.id=p.brand_id
            LEFT JOIN public.producers pr ON pr.id=p.producer_id WHERE p.product_id=%s
        """, (product_id,))
        rows = cur.fetchall()
        if len(rows) != 1:
            raise RefreshError("Product is missing or has duplicate nutrition rows. Refresh was not applied.")
        snapshot = dict(rows[0])
        cur.execute("SELECT to_jsonb(pp) AS row FROM public.productphotos pp WHERE product_id=%s ORDER BY is_primary DESC,photo_id", (product_id,))
        snapshot["photos"] = [r["row"] for r in cur.fetchall()]
        cur.execute("""
            SELECT to_jsonb(h) AS row FROM public.product_price_history h
            WHERE product_id=%s ORDER BY recorded_at DESC,price_history_id DESC LIMIT 1
        """, (product_id,))
        row = cur.fetchone()
        snapshot["market"] = row["row"] if row else None
        cur.execute("""
            SELECT ingredient_id FROM public.ingredient_product_mapping WHERE product_sku=%s
            ORDER BY ingredient_id
        """, (snapshot["product"]["sku"],))
        snapshot["ingredient_mapping"] = [r["ingredient_id"] for r in cur.fetchall()]
        cur.execute("SELECT to_jsonb(v) AS row FROM public.nutrition_validation v WHERE product_id=%s", (product_id,))
        row = cur.fetchone()
        snapshot["validation"] = row["row"] if row else None
        cur.execute("""
            WITH RECURSIVE path AS (
                SELECT category_id,parent_category_id,normalized_category::text AS path,ARRAY[category_id] AS ids
                FROM public.normalized_categories WHERE category_id=%s
                UNION ALL
                SELECT c.category_id,c.parent_category_id,c.normalized_category||'/'||p.path,p.ids||c.category_id
                FROM public.normalized_categories c JOIN path p ON c.category_id=p.parent_category_id
                WHERE NOT c.category_id=ANY(p.ids)
            ) SELECT path FROM path WHERE parent_category_id IS NULL
        """, (snapshot["product"]["category_id"],))
        row = cur.fetchone()
        snapshot["category_path"] = row["path"] if row else None
        return snapshot


def context_for(conn, snapshot, candidate):
    old = snapshot.get("nutrition") or {}
    accepted = old.get("ingredients_text") or snapshot["product"].get("ingredients") or ""
    tokens = sorted(set(extract_ingredient_tokens(accepted) +
                        extract_ingredient_tokens(candidate.get("ingredients") or "")))
    with conn.cursor() as cur:
        cur.execute("SELECT to_jsonb(c) FROM public.normalized_categories c ORDER BY category_id")
        categories = [r[0] for r in cur.fetchall()]
        cur.execute("""
            SELECT category_id,array_agg(DISTINCT rimi_category_code ORDER BY rimi_category_code)
            FROM public.products WHERE rimi_category_code IS NOT NULL
            GROUP BY category_id ORDER BY category_id
        """)
        codes = {str(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("SELECT rimi_category_code,nova_score FROM public.rimi_nova_categories ORDER BY rimi_category_code")
        nova = {str(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("""
            SELECT to_jsonb(i) FROM public.ingredient_analysis i
            WHERE ingredient=ANY(%s) OR id=ANY(%s) ORDER BY id
        """, (tokens, snapshot["ingredient_mapping"]))
        ingredients = [r[0] for r in cur.fetchall()]
    return {"categories": categories, "rimi_codes": codes, "nova_categories": nova, "ingredients": ingredients}


def policy_hash():
    files = ("fiber_estimation_config.json", "fiber_estimator.py", "nutriscore_calculator.py",
             "nutrition_reload_plan.py", "product_refresh_plan.py", "ingredient_processor.py",
             "nutrition_validation.py", "nova_calculator.py")
    return digest({p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files})


def prepare_preview(product_id, dsn=None, source=None):
    dsn = dsn or os.environ["DATABASE_URL"]
    conn = connect(dsn, True)
    try:
        snapshot = capture(conn, product_id)
        # Website fetch does not initialize workers, caches, migrations or DB writers.
        candidate = (source or ProductRefreshSource()).product(snapshot)
        context = context_for(conn, snapshot, candidate)
        plan = build_plan(snapshot, candidate, context, NutriscoreCalculator(conn), FiberEstimator())
        validate_changes(plan)
        preview = {"product_id": product_id, "snapshot": snapshot, "candidate": candidate,
                   "context": context, "plan": plan, "policy": policy_hash(),
                   "database": database_identity(dsn), "fetched_at": datetime.now(timezone.utc).isoformat()}
        preview["sha256"] = digest(preview)
        return preview
    except ValueError:
        raise
    except Exception:
        raise RefreshError("Could not prepare the refresh preview. No data was changed; please retry.") from None
    finally:
        conn.rollback()
        conn.close()


def _update(cur, table, pid, values, timestamp=None):
    if not values:
        return
    fields = list(values)
    assignments = [sql.SQL("{}=%s").format(sql.Identifier(f)) for f in fields]
    if timestamp:
        assignments.append(sql.SQL("{}=CURRENT_TIMESTAMP").format(sql.Identifier(timestamp)))
    cur.execute(sql.SQL("UPDATE public.{} SET {} WHERE product_id=%s").format(
        sql.Identifier(table), sql.SQL(",").join(assignments)), [values[f] for f in fields] + [pid])
    if cur.rowcount != 1:
        raise RefreshError("Product changed or was removed. Fetch a fresh preview.")


def persist_ingredients(cur, sku, tokens):
    """Replace this SKU's mappings, retain shared analyses, recompute affected frequencies."""
    cur.execute("SELECT ingredient_id FROM public.ingredient_product_mapping WHERE product_sku=%s", (sku,))
    affected = {r[0] for r in cur.fetchall()}
    cur.execute("DELETE FROM public.ingredient_product_mapping WHERE product_sku=%s", (sku,))
    for token in tokens:
        cur.execute("""
            INSERT INTO public.ingredient_analysis(ingredient,frequency,is_processed)
            VALUES (%s,0,FALSE) ON CONFLICT(ingredient) DO UPDATE SET ingredient=EXCLUDED.ingredient
            RETURNING id
        """, (token,))
        ingredient_id = cur.fetchone()[0]
        affected.add(ingredient_id)
        cur.execute("""
            INSERT INTO public.ingredient_product_mapping(ingredient_id,product_sku)
            VALUES (%s,%s) ON CONFLICT DO NOTHING
        """, (ingredient_id, sku))
    if affected:
        cur.execute("""
            UPDATE public.ingredient_analysis i SET frequency=(
                SELECT COUNT(*) FROM public.ingredient_product_mapping m WHERE m.ingredient_id=i.id)
            WHERE i.id=ANY(%s)
        """, (sorted(affected),))


def persist_refresh_plan(conn, snapshot, plan):
    """Write a validated full-information plan inside the caller's transaction.

    Does not commit, initialize schema, fetch pages or process other products.
    Both the card refresh and scoped category recovery use this same pipeline.
    """
    validate_changes(plan)
    pid = snapshot["product"]["product_id"]
    with conn.cursor() as cur:
        _update(cur, "products", pid, plan["product_changes"], "updated_at")
        changes = plan["nutrition_changes"]
        if changes:
            timestamp = "data_source_date" if plan["nutrition_complete"] else None
            if snapshot["nutrition"] is None:
                fields = ["product_id"] + list(changes)
                values = [pid] + list(changes.values())
                cur.execute(sql.SQL("INSERT INTO public.nutritionfacts ({}) VALUES ({})").format(
                    sql.SQL(",").join(map(sql.Identifier, fields)),
                    sql.SQL(",").join(sql.Placeholder() for _ in fields)), values)
                if timestamp:
                    cur.execute("UPDATE public.nutritionfacts SET data_source_date=CURRENT_TIMESTAMP WHERE product_id=%s", (pid,))
            else:
                _update(cur, "nutritionfacts", pid, changes, timestamp)
        elif plan["nutrition_complete"] and snapshot["nutrition"] is not None:
            cur.execute("UPDATE public.nutritionfacts SET data_source_date=CURRENT_TIMESTAMP WHERE product_id=%s", (pid,))
        for kind, value in plan["links"].items():
            entity_id = _get_or_create_entity(cur, "brands" if kind == "brand" else "producers", value)
            _update(cur, "products", pid, {kind + "_id": entity_id}, "updated_at")
        if plan["links"]:
            cur.execute("""
                INSERT INTO public.brand_producers(brand_id,producer_id)
                SELECT brand_id,producer_id FROM public.products
                WHERE product_id=%s AND brand_id IS NOT NULL AND producer_id IS NOT NULL
                ON CONFLICT DO NOTHING
            """, (pid,))
        if plan["photos"]:
            alt_texts = {r["photo_url"]: r.get("alt_text") for r in snapshot["photos"]}
            cur.execute("DELETE FROM public.productphotos WHERE product_id=%s", (pid,))
            for index, url in enumerate(plan["photos"]):
                cur.execute("INSERT INTO public.productphotos(product_id,photo_url,is_primary,alt_text) VALUES (%s,%s,%s,%s)",
                            (pid, url, index == 0, alt_texts.get(url)))
        if plan["market"]:
            fields = sorted(plan["market"])
            cur.execute(sql.SQL("""
                INSERT INTO public.product_price_history(product_id,{},data_source,recorded_at)
                VALUES (%s,{},'barbora_scraped',CURRENT_TIMESTAMP)
            """).format(sql.SQL(",").join(map(sql.Identifier, fields)),
                        sql.SQL(",").join(sql.Placeholder() for _ in fields)),
                        [pid] + [plan["market"][f] for f in fields])
        if plan["ingredient_tokens"] is not None:
            persist_ingredients(cur, snapshot["product"]["sku"], plan["ingredient_tokens"])
        cur.execute("UPDATE public.products SET updated_at=CURRENT_TIMESTAMP WHERE product_id=%s", (pid,))
        validation = plan["validation"]
        cur.execute("""
            INSERT INTO public.nutrition_validation(product_id,suspicion_level,suspicion_score,reasons,checked_at)
            VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP) ON CONFLICT(product_id) DO UPDATE SET
                suspicion_level=EXCLUDED.suspicion_level,suspicion_score=EXCLUDED.suspicion_score,
                reasons=EXCLUDED.reasons,checked_at=EXCLUDED.checked_at
        """, (pid, validation["suspicion_level"], validation["suspicion_score"], Json(validation["reasons"])))


def apply_preview(preview, dsn=None):
    dsn = dsn or os.environ["DATABASE_URL"]
    if preview.get("sha256") != digest({k: v for k, v in preview.items() if k != "sha256"}):
        raise RefreshError("Preview was altered. Fetch a fresh preview.")
    if preview["database"] != database_identity(dsn) or preview["policy"] != policy_hash():
        raise RefreshError("Database or refresh rules changed. Fetch a fresh preview.")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(preview["fetched_at"])).total_seconds()
    if not 0 <= age <= 600:
        raise RefreshError("This preview expired. Fetch a fresh preview before applying.")
    plan, pid = preview["plan"], preview["product_id"]
    validate_changes(plan)
    conn = connect(dsn, False)
    try:
        snapshot = capture(conn, pid, lock=True)
        if snapshot != preview["snapshot"]:
            raise RefreshError("Product or related data changed since the preview. Fetch a fresh preview.")
        context = context_for(conn, snapshot, preview["candidate"])
        if context != preview["context"]:
            raise RefreshError("Category or ingredient analysis changed. Fetch a fresh preview.")
        expected = build_plan(snapshot, preview["candidate"], context, NutriscoreCalculator(conn), FiberEstimator())
        if expected != plan:
            raise RefreshError("Refresh proposal no longer matches. Fetch a fresh preview.")
        if not any(plan[k] for k in ("product_changes", "nutrition_changes", "links", "photos", "market")):
            conn.rollback()
            return {"status": "no_changes"}
        persist_refresh_plan(conn, snapshot, plan)
        conn.commit()
        return {"status": "updated", "product_id": pid}
    except RefreshError:
        conn.rollback()
        raise
    except (psycopg2.errors.SerializationFailure, psycopg2.errors.LockNotAvailable):
        conn.rollback()
        raise RefreshError("Another update is in progress. Fetch a fresh preview and try again.") from None
    except Exception:
        conn.rollback()
        raise RefreshError("Refresh could not be saved. All changes were rolled back; fetch a fresh preview and retry.") from None
    finally:
        conn.close()
