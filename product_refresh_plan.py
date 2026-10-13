"""Pure refresh planning; only validated present values may replace stored fields."""

import math
import re

from brand_producer import clean_label, normalize_entity_name
from ingredient_processor import extract_ingredient_tokens
from nutrition_reload_plan import FIELDS, REQUIRED, normalize_name, resolve_fiber
from nutrition_validation import validate_product

PRODUCT_FIELDS = {"name", "name_norm", "barbora_url", "description", "allergens", "ingredients",
                  "country_of_origin", "quantity_value", "quantity_unit", "category_id",
                  "rimi_category_code", "nutrition_source", "needs_enrichment", "nova_score", "nova_source"}
NUTRITION_FIELDS = set(FIELDS) | {"ingredients_text", "usda_fdc_id", "is_fiber_correct",
                                "nutri_score_grade", "nutri_score_points"}
MARKET_FIELDS = {"price", "discount_price", "price_per_unit", "price_per_unit_type",
                 "discount_price_per_unit", "is_available"}


def quantity(name, raw):
    """Existing pack-size rules without importing/initializing the broad worker."""
    from decimal import Decimal, InvalidOperation
    if re.search(r"sver\.\s*$", name, re.I):
        return None, None
    multi = re.search(r"(\d+)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b", name, re.I)
    if multi:
        return float(Decimal(multi[1]) * Decimal(multi[2].replace(",", "."))), multi[3].lower()
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l)\b", name, re.I)
    if match:
        value, unit = float(match[1].replace(",", ".")), match[2].lower()
        if raw:
            try:
                net = float(Decimal(raw.strip().replace(",", ".")))
                if math.isfinite(net) and net > 0:
                    value = net / 1000 if unit in {"kg", "l"} else net
            except (ValueError, InvalidOperation):
                pass
        return value, unit
    pieces = re.search(r"(\d+)\s*gab\.?\b", name, re.I)
    if pieces:
        return float(pieces[1]), "gab"
    if re.search(r"\bkg\s*$", name, re.I):
        return None, "kg"
    return None, None


def valid_nutrition(values):
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(v) or v < 0 or (k not in {"energy_kj", "energy_kcal"} and v > 100)
           for k, v in values.items()):
        return False
    for part, total in (("fat_saturated", "fat_total"), ("carbs_sugars", "carbs_total")):
        if part in values and total in values and values[part] > values[total] + .05:
            return False
    mass = ("fat_total", "carbs_total", "protein", "salt", "fiber")
    return not all(k in values for k in mass) or sum(values[k] for k in mass) <= 102


def build_plan(snapshot, candidate, context, calculator, estimator):
    p, old = snapshot["product"], snapshot.get("nutrition") or {}
    if candidate["sku"] != p["sku"]:
        raise ValueError("The website SKU does not match this product.")
    pc, nc, notes, rows = {}, {}, list(candidate.get("notes", [])), []

    def present(group, field, before, after, protected=False, reason=None):
        if protected:
            status = "Protected"
        elif after is None or after == "":
            status = "Unavailable — retained"
        elif before == after:
            status = "Unchanged"
        else:
            status = "Changed"
        rows.append({"Section": group, "Field": field, "Before": before, "Website / after": after,
                     "Status": status, "Note": reason or ""})
        return status == "Changed"

    manual_name = bool(p.get("name_manual_edit"))
    manual_nutrition = bool(old.get("nutrition_manual_edit"))
    for field in ("name", "description", "allergens", "country_of_origin"):
        value = clean_label(candidate.get(field))
        protected = manual_name and field == "name"
        if present("Product", field, p.get(field), value, protected):
            pc[field] = value
    if "name" in pc:
        pc["name_norm"] = normalize_name(pc["name"])
    url = candidate["fetched_url"]
    if present("Product", "barbora_url", p.get("barbora_url"), url):
        pc["barbora_url"] = url
    text = clean_label(candidate.get("ingredients"))
    current_text = old.get("ingredients_text") or p.get("ingredients")
    protected_ingredients = manual_name or manual_nutrition
    if present("Product", "ingredients", current_text, text, protected_ingredients):
        pc["ingredients"] = text
        nc["ingredients_text"] = text
    elif text and not protected_ingredients:
        # Keep the two existing ingredient copies consistent even if one was absent.
        if p.get("ingredients") != text:
            pc["ingredients"] = text
        if old.get("ingredients_text") != text:
            nc["ingredients_text"] = text
    value, unit = quantity(pc.get("name", p["name"]), candidate.get("weight"))
    if present("Product", "quantity_value", p.get("quantity_value"), value):
        pc["quantity_value"] = value
    if present("Product", "quantity_unit", p.get("quantity_unit"), unit):
        pc["quantity_unit"] = unit
    code = candidate.get("category_code")
    categories = [c for c in context["categories"] if c.get("barbora_category_code") == code] if code else []
    category = categories[0] if len(categories) == 1 else None
    category_id = category["category_id"] if category else None
    if present("Product", "category_id", p.get("category_id"), category_id,
               reason=None if category else "Website category absent or not uniquely mapped."):
        pc["category_id"] = category_id
        codes = context["rimi_codes"].get(str(category_id), [])
        mapped = codes[0] if len(codes) == 1 else None
        pc["rimi_category_code"] = mapped
        rows.append({"Section": "Product", "Field": "rimi_category_code", "Before": p.get("rimi_category_code"),
                     "Website / after": mapped, "Status": "Changed",
                     "Note": "Derived from existing unique category mapping." if mapped is not None else
                     "No unique mapping: cleared stale old-category code; no guessed fiber/NOVA category."})
    links = {}
    for kind in ("brand", "producer"):
        value = clean_label(candidate.get(kind + "_name") or candidate.get(kind))
        before = snapshot.get(kind)
        before_name = before.get("name") if before else None
        changed = value and normalize_entity_name(before_name) != normalize_entity_name(value)
        present("Product", kind, before_name, value)
        if value and before_name and not changed:
            rows[-1].update(Status="Unchanged", Note="Same normalized entity; existing name and manual website retained.")
        if changed:
            links[kind] = value
    photos = candidate.get("photo_urls") or []
    previous_photos = [r["photo_url"] for r in snapshot["photos"]]
    primary_mismatch = any(bool(r.get("is_primary")) != (index == 0)
                           for index, r in enumerate(snapshot["photos"]))
    photo_changes = photos if photos and (photos != previous_photos or primary_mismatch) else None
    present("Photos", "photo_urls", previous_photos, photos or None)
    market = candidate.get("market", {})
    last = snapshot.get("market") or {}
    desired_market = {k: last.get(k) for k in MARKET_FIELDS}
    for field in sorted(MARKET_FIELDS):
        if field not in market:
            present("Price / availability", field, last.get(field), None)
            continue
        value = market[field]
        if field == "is_available" and p.get("is_hidden"):
            value = False
        # Explicit null discounts mean no current discount, not missing information.
        changed = value != last.get(field)
        rows.append({"Section": "Price / availability", "Field": field, "Before": last.get(field),
                     "Website / after": value, "Status": "Changed" if changed else "Unchanged",
                     "Note": "Hidden products remain unavailable." if field == "is_available" and p.get("is_hidden") else ""})
        desired_market[field] = value
    if p.get("is_hidden") and last.get("is_available") is True:
        desired_market["is_available"] = False
    market_changes = desired_market if desired_market != {k: last.get(k) for k in MARKET_FIELDS} else None
    if candidate.get("promotion"):
        rows.append({"Section": "Price / availability", "Field": "promotion details",
                     "Before": None, "Website / after": candidate["promotion"], "Status": "Information",
                     "Note": "Promotion prices are saved in history. Card requirements/type are shown here only; existing schema has no promotion-metadata field."})
    rows.append({"Section": "Product", "Field": "storage_conditions",
                 "Before": None, "Website / after": candidate.get("storage_conditions"), "Status": "Unavailable — retained",
                 "Note": "No storage-conditions field exists in current product storage."})
    nutrition = dict(candidate.get("nutrition") or {})
    complete = (not candidate.get("nutrition_issue") and valid_nutrition(nutrition)
                and all(k in nutrition for k in REQUIRED)
                and ("energy_kj" in nutrition or "energy_kcal" in nutrition))
    if complete:
        if "energy_kj" not in nutrition:
            nutrition["energy_kj"] = nutrition["energy_kcal"] * 4.184
        if "energy_kcal" not in nutrition:
            nutrition["energy_kcal"] = nutrition["energy_kj"] / 4.184
        for k in ("energy_kj", "energy_kcal"):
            nutrition[k] = int(nutrition[k] + .5)
        if max(nutrition["energy_kj"], nutrition["energy_kcal"]) > 2147483647:
            complete = False
    for field in FIELDS:
        reason = None if complete else "Incomplete/invalid/absent website nutrition: existing values retained."
        if field != "fiber" and present("Nutrition", field, old.get(field), nutrition.get(field),
                                        manual_nutrition, reason) and complete and not manual_nutrition:
            nc[field] = nutrition[field]
        if not complete and not manual_nutrition and rows and rows[-1]["Section"] == "Nutrition":
            rows[-1]["Status"] = "Unavailable — retained"
    if complete and not manual_nutrition:
        pc.update(nutrition_source="barbora_scraped", needs_enrichment=False)
        nc["usda_fdc_id"] = None
    elif not complete:
        notes.append("Website nutrition is incomplete or absent; existing nutrient values and source are retained.")
        stored_values = {k: old[k] for k in FIELDS if old.get(k) is not None}
        stored_complete = (all(k in stored_values for k in REQUIRED)
                           and any(k in stored_values for k in ("energy_kj", "energy_kcal"))
                           and valid_nutrition(stored_values))
        if not manual_nutrition and not stored_complete:
            pc["needs_enrichment"] = True
            notes.append("Stored nutrition is also incomplete; Needs Enrichment remains/set true.")
    effective_p, effective_n = dict(p, **pc), dict(old, **nc)
    score_inputs_changed = bool(old or nc) or any(k in pc for k in ("name", "category_id", "rimi_category_code"))
    if score_inputs_changed:
        score = {"nutri_score_grade": None, "nutri_score_points": None}
        fiber, correct, origin = resolve_fiber(
            effective_p, old, nutrition.get("fiber") if complete and not manual_nutrition else None,
            effective_p["name"], estimator)
        if not manual_nutrition and fiber is not None and origin["kind"] in {"barbora", "category", "exception"}:
            nc.update(fiber=fiber, is_fiber_correct=correct)
            effective_n.update(fiber=fiber)
        required = ("energy_kj", "carbs_sugars", "fat_saturated", "salt", "protein", "fat_total")
        if (fiber is not None and all(effective_n.get(k) is not None for k in required)
                and valid_nutrition({k: effective_n[k] for k in FIELDS if effective_n.get(k) is not None})):
            result = calculator.calculate_single_product(
                energy_kj=effective_n["energy_kj"], sugars=effective_n["carbs_sugars"],
                saturated_fat=effective_n["fat_saturated"], salt=effective_n["salt"],
                protein=effective_n["protein"], fiber=fiber, total_fat=effective_n["fat_total"],
                category_id=effective_p.get("category_id"), product_name=effective_p["name"],
                ingredients_text=effective_n.get("ingredients_text") or effective_p.get("ingredients"),
            )
            if not result.get("success"):
                raise ValueError("Nutri-Score calculation failed; no refresh changes have been saved.")
            score.update(nutri_score_grade=result["grade"], nutri_score_points=result["score"])
        nc.update(score)
        present("Derived", "fiber for scoring", old.get("fiber"), fiber, reason=origin["reason"])
        for k, v in score.items():
            rows.append({"Section": "Derived", "Field": k, "Before": old.get(k),
                         "Website / after": v, "Status": "Changed" if old.get(k) != v else "Unchanged", "Note": ""})
    accepted_text = nc.get("ingredients_text", current_text) or ""
    tokens = sorted(set(extract_ingredient_tokens(accepted_text)))
    if not accepted_text and snapshot.get("ingredient_mapping"):
        tokens = sorted(i["ingredient"] for i in context["ingredients"]
                        if i["id"] in snapshot["ingredient_mapping"])
    ingredients_changed = bool(text and not protected_ingredients and accepted_text != (current_text or ""))
    if effective_p.get("nova_source") != "manual_override":
        known = {i["ingredient"]: i for i in context["ingredients"]}
        unknown = [t for t in tokens if t not in known or known[t].get("suspicion_level") is None
                   or known[t].get("is_processed") is False]
        if any(known.get(t, {}).get("suspicion_level") in {"avoid", "limit"} for t in tokens):
            pc.update(nova_score=4, nova_source="additive_override")
        elif unknown:
            pc.update(nova_score=None, nova_source=None)
            notes.append("NOVA awaits usable analysis of the accepted ingredients; stale automatic score cleared.")
        else:
            value = context["nova_categories"].get(str(effective_p.get("rimi_category_code")))
            pc.update(nova_score=value, nova_source="category_inherited" if value is not None else None)
        for k in ("nova_score", "nova_source"):
            rows.append({"Section": "Derived", "Field": k, "Before": p.get(k), "Website / after": pc[k],
                         "Status": "Changed" if p.get(k) != pc[k] else "Unchanged", "Note": ""})
    pc = {k: v for k, v in pc.items() if p.get(k) != v}
    nc = {k: v for k, v in nc.items() if old.get(k) != v}
    validation = validate_product(dict(p, **pc, **dict(old, **nc)))
    previous_validation = snapshot.get("validation") or {}
    rows.append({"Section": "Derived", "Field": "nutrition validation",
                 "Before": previous_validation.get("suspicion_level"),
                 "Website / after": validation["suspicion_level"],
                 "Status": "Changed" if previous_validation.get("suspicion_level") != validation["suspicion_level"] else "Unchanged",
                 "Note": "Existing nutrition-consistency rules evaluated on the accepted post-update values."})
    for field in ("nutrition_source", "needs_enrichment", "usda_fdc_id", "is_fiber_correct"):
        group, changes, before = ("Product", pc, p) if field in PRODUCT_FIELDS else ("Nutrition", nc, old)
        if field in changes:
            rows.append({"Section": group, "Field": field, "Before": before.get(field),
                         "Website / after": changes[field], "Status": "Changed", "Note": ""})
    return {"product_changes": pc, "nutrition_changes": nc, "links": links, "photos": photo_changes,
            "market": market_changes, "ingredient_tokens": tokens if ingredients_changed else None,
            "rows": rows, "notes": notes, "nutrition_complete": complete and not manual_nutrition,
            "validation": {k: validation[k] for k in ("suspicion_level", "suspicion_score", "reasons")}}


def validate_changes(plan):
    if set(plan["product_changes"]) - PRODUCT_FIELDS or set(plan["nutrition_changes"]) - NUTRITION_FIELDS:
        raise ValueError("Refresh contains an unsupported field.")
    if plan["market"] and set(plan["market"]) - MARKET_FIELDS:
        raise ValueError("Refresh contains an unsupported price field.")
