"""Validated adapters for Barbora's public Remix data (no database operations)."""
import json
import math
import re
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from photo_sources import product_photos, unsupported_only


class SiteDataError(ValueError):
    """A page is not a complete, understood retailer observation."""

    def __init__(self, code, details=None):
        super().__init__(code)
        self.details = details or {}


# User-supplied recovery hints, not replacement database category identities.
RECOVERY_CATEGORY_PATHS = {
    "bakaleja/saldumi/sveramie-cepumi": "L0BE",
    "bakaleja/uzkodas/kukuruzas-nujinas-un-popkorns": "ATB9",
    "maize-un-konditorejas-izstradajumi/svaigi-cepts/svaigi-ceptas-smalkmaizites": "8ZA0",
}


def canonical_category_path(path):
    """Use the supplied canonical routes; each response must still verify its tree."""
    path = path.strip("/")
    short = RECOVERY_CATEGORY_PATHS.get(path)
    return f"c/{short}/{path}" if short else path


def query_data(html, operation, include_key=False):
    match = re.search(r"window\.__remixContext\s*=\s*", html)
    if not match:
        return None
    try:
        context, _ = json.JSONDecoder().raw_decode(html[match.end():].lstrip())
        loaders = context["state"]["loaderData"]
        matches = []
        for loader in loaders.values():
            if not isinstance(loader, dict):
                continue
            for query in loader.get("dehydratedState", {}).get("queries", []):
                key = query.get("queryKey", [])
                if key and isinstance(key[0], dict) and key[0].get("_id") == operation:
                    value = query["state"]["data"]
                    if include_key:
                        value = (value, {"path": key[0].get("path"), "query": key[0].get("query")})
                    if value not in matches:
                        matches.append(value)
        if len(matches) > 1:
            raise SiteDataError("ambiguous_" + operation)
        return matches[0] if matches else None
    except (KeyError, TypeError, json.JSONDecodeError):
        raise SiteDataError("invalid_remix_data") from None


def amount(value, required=False):
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SiteDataError("invalid_number")
    if not math.isfinite(value) or value < 0:
        raise SiteDataError("invalid_number")
    return float(value)


def identity(product):
    sku = product.get("id")
    if not isinstance(sku, str) or not re.fullmatch(r"\d+", sku):
        raise SiteDataError("invalid_sku")
    if not isinstance(product.get("title"), str) or not product["title"].strip():
        raise SiteDataError("missing_title")
    slug = product.get("url")
    if not isinstance(slug, str) or not re.fullmatch(r"[\w-]+", slug):
        raise SiteDataError("invalid_product_slug")
    return sku


def categories(html):
    data = query_data(html, "categoriesGet")
    result = {}
    def walk(node):
        short = node.get("shortId")
        if short:
            if short in result and result[short] != node:
                raise SiteDataError("ambiguous_category")
            result[short] = node
        for child in node.get("children", []):
            walk(child)
    if data:
        for root in data.get("categories", []):
            walk(root)
    return result


def market(product):
    status = product.get("status")
    availability = {"active": True, "outOfStock": False}
    if status not in availability:
        raise SiteDataError("unknown_availability")
    current = amount(product.get("price"), required=True)
    promo = product.get("promotion")
    if promo is not None and not isinstance(promo, dict):
        raise SiteDataError("invalid_promotion")
    promo = promo or {}
    old = amount(promo.get("oldPrice"))
    comparative = product.get("comparativeUnit")
    if not isinstance(comparative, dict) or not isinstance(comparative.get("type"), str):
        raise SiteDataError("missing_comparative_unit")
    rate = amount(comparative.get("price"), required=True)
    old_rate = amount(promo.get("oldComparativeRateGross"))
    if old is not None and old < current:
        raise SiteDataError("invalid_discount")
    return dict(price=old if old is not None and old > current else current,
                discount_price=current if old is not None and old > current else None,
                price_per_unit=old_rate if old_rate is not None and old_rate > rate else rate,
                discount_price_per_unit=rate if old_rate is not None and old_rate > rate else None,
                price_per_unit_type=comparative["type"],
                is_available=availability[status])


def normalized_product(product, registry, html=None):
    identity(product)
    market(product)
    node = registry.get(product.get("categoryShortId"), {})
    category_id = node.get("categoryId")
    # The redesigned inventory's categoryId is often an all-zero placeholder.
    if not category_id:
        category_id = product.get("categoryId")
    if category_id == "00000000-0000-0000-0000-000000000000":
        category_id = None
    promotion = dict(product.get("promotion") or {})
    if promotion.get("oldPrice") is None or promotion["oldPrice"] <= product["price"]:
        promotion.pop("oldPrice", None)
    if promotion.get("oldComparativeRateGross") is not None:
        promotion["oldComparativeRate"] = promotion["oldComparativeRateGross"]
    photos = product_photos(product, html)
    return dict(product, Url="p/" + product["url"], promotion=promotion,
                category_id=category_id,
                category_path_url=product.get("categoryPathUrl"),
                brand_name=product.get("brand"),
                big_image=photos[0] if photos else None,
                image=photos[0] if photos else None, gallery=photos,
                photo_issue="unsupported_format_only" if not photos and unsupported_only(product) else None,
                retail_price=(product.get("promotion") or {}).get("oldPrice"),
                comparative_unit=product["comparativeUnit"]["type"],
                comparative_unit_price=product["comparativeUnit"]["price"],
                comparative_unit_price_brutto=(product.get("promotion") or {}).get("oldComparativeRateGross"),
                status="active" if product["status"] == "active" else "inactive")


def category_page(html, page=1, expected_short=None, expected_path=None):
    record = query_data(html, "inventoryCategoryInventory", include_key=True)
    if record is None:
        raise SiteDataError("category_listing_unrecognized")
    data, query_key = record
    if not isinstance(data, dict):
        raise SiteDataError("invalid_category_listing")
    offset, limit, count = (data.get(k) for k in ("offset", "limit", "count"))
    if any(type(v) is not int for v in (offset, limit, count)) or limit <= 0 or count < 0:
        raise SiteDataError("invalid_pagination")
    if offset != (page - 1) * limit:
        raise SiteDataError("unexpected_page_offset")
    key_path, key_query = query_key.get("path") or {}, query_key.get("query") or {}
    query_short = key_path.get("shortId")
    if key_query and (key_query.get("Offset") != offset or key_query.get("Limit") != limit):
        raise SiteDataError("query_pagination_mismatch")
    registry = categories(html)
    items = data.get("inventories")
    path = (data.get("categoryMetadata") or {}).get("url", "")
    evidence = "category_metadata"
    if not path and count == 0 and offset == 0 and items == [] and query_short:
        node = registry.get(query_short, {})
        tree_path = node.get("fullUrl")
        if (isinstance(tree_path, str) and tree_path.startswith(f"c/{query_short}/")
                and key_query.get("Offset") == 0 and key_query.get("Limit") == limit):
            path = tree_path
            evidence = "inventory_query_and_current_tree"
    if not isinstance(path, str):
        raise SiteDataError("missing_category_identity")
    parts = path.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "c" or (expected_short and parts[1] != expected_short):
        raise SiteDataError("category_identity_mismatch")
    if query_short is not None and query_short != parts[1]:
        raise SiteDataError("query_category_mismatch")
    tree_path = registry.get(parts[1], {}).get("fullUrl")
    if tree_path is not None and tree_path.strip("/") != path.strip("/"):
        raise SiteDataError("tree_category_mismatch")
    relative = "/".join(parts[2:])
    hint = RECOVERY_CATEGORY_PATHS.get(relative)
    if hint and (parts[1] != hint or not tree_path):
        raise SiteDataError("recovery_category_identity_mismatch")
    if expected_path is not None:
        verify_category_path({"path": path}, expected_path)
    if not isinstance(items, list) or len(items) != max(0, min(limit, count - offset)):
        raise SiteDataError("incomplete_category_page", dict(
            advertised_count=count, returned_count=len(items) if isinstance(items, list) else None,
            offset=offset, limit=limit))
    soup = BeautifulSoup(html, "html.parser")
    normalized = [normalized_product(p, registry, soup) for p in items]
    if len({p["id"] for p in normalized}) != len(normalized):
        raise SiteDataError("duplicate_page_sku")
    return dict(products=normalized, count=count, offset=offset, limit=limit,
                short_id=parts[1], path=path,
                category_id=registry.get(parts[1], {}).get("categoryId"),
                identity_evidence=evidence)


def verify_category_path(data, requested):
    """Reconcile redesign UUIDs by exact full hierarchy, never by category name."""
    def path(value):
        value = urlsplit(value).path.strip("/")
        parts = value.split("/")
        return "/".join(parts[2:]) if parts[0] == "c" else value
    if path(data["path"]) != path(requested):
        raise SiteDataError("category_path_mismatch")


def product_data(html):
    product = query_data(html, "productProductByUrl")
    if product is not None:
        identity(product)
    return product


def nutrition(product, html):
    nutrients = product.get("nutrients")
    if not nutrients:
        return {}, "absent_nutrition"
    # This specific productProductByUrl schema is displayed under nutrition.per_100g
    # by Barbora's product route. Verified against the public LV route and translation
    # on 2026-10-30. The accordion content is client-rendered, absent from SSR text.
    if product.get("nutritionBasis", "100g") not in ("100g", "100 g", "100ml", "100 ml"):
        return {}, "unsupported_nutrition_basis"
    mapping = dict(calories="energy_kcal", kj="energy_kj", fat="fat_total",
                   saturatedFat="fat_saturated", carbohydrates="carbs_total",
                   sugar="carbs_sugars", protein="protein", salt="salt", fiber="fiber")
    result = {}
    try:
        for key, field in mapping.items():
            item = nutrients.get(key)
            if item is not None:
                value = amount(item.get("value"), required=True)
                if field not in {"energy_kj", "energy_kcal"} and value > 100:
                    raise SiteDataError("invalid_nutrient")
                result[field] = value
        return result, None
    except (SiteDataError, AttributeError):
        return {}, "invalid_nutrition"


def detail_values(product, html):
    values, issue = nutrition(product, html)
    return dict(sku=product["id"], name=product["title"],
                description=product.get("description"), ingredients=product.get("ingredients"),
                allergens=product.get("allergens"), country_of_origin=product.get("countryOfOrigin"),
                manufacturer=product.get("manufacturer"), producer=product.get("manufacturer"),
                producer_name=product.get("manufacturer"), brand=product.get("brand"),
                brand_name=product.get("brand"), distributor_name=product.get("supplierContacts"),
                storage_conditions=product.get("storageConditions"),
                weight=str(product["netAmount"]) if product.get("netAmount") is not None else None,
                photo_urls=product_photos(product, html),
                nutrition=values, nutrition_issue=issue)
