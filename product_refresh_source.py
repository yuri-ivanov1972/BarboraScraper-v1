"""Bounded, identity-checked single-product website reads, with no database writes."""

import json
import math
import re
from dataclasses import asdict
from urllib.parse import urlsplit

from barbora_parser import BarboraParser
from nutrition_reload_source import BarboraSource, SourceError, parse_page, trusted_url
from barbora_site_data import product_data, normalized_product
from photo_sources import image_url, product_photos, select_urls


def product_json(html):
    modern = product_data(html)
    if modern is not None:
        from barbora_site_data import categories
        return normalized_product(modern, categories(html), html)
    match = re.search(r"\bwindow\.product\s*=\s*", html)
    if not match:
        return {}
    try:
        value, _ = json.JSONDecoder().raw_decode(html[match.end():].lstrip())
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except ValueError:
        raise SourceError("invalid_product_json") from None


def photo_url(value):
    return bool(image_url(value))


def number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise SourceError("invalid_price")
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise SourceError("invalid_price") from None
    if not math.isfinite(value) or value < 0:
        raise SourceError("invalid_price")
    return value


def parse_full_page(html, fetched_url, expected_sku):
    trusted_url(fetched_url)
    structured = product_json(html)
    candidate = parse_page(html)
    if candidate["sku"] != expected_sku or (
            structured.get("id") is not None and str(structured["id"]) != expected_sku):
        raise SourceError("identity_mismatch")
    details = BarboraParser().parse_product_details(html)
    if not details or details.sku != expected_sku:
        raise SourceError("missing_product_identity")
    data = asdict(details)
    # Page labels are preferred; structured values are only same-SKU supplements.
    for key in ("description", "ingredients", "allergens", "brand_name"):
        if not data.get(key) and isinstance(structured.get(key), str):
            data[key] = structured[key].strip() or None
    photos = select_urls([data.get("photo_urls"), product_photos(structured, html)])
    data.update(candidate, fetched_url=fetched_url,
                photo_urls=list(dict.fromkeys(p for p in photos if photo_url(p))),
                category_code=structured.get("category_id"),
                category_path=structured.get("category_path_url"),
                notes=["Photo deferred: unsupported_format_only; existing photos retained."]
                if not photos and structured.get("photo_issue") else [])
    market = {}
    try:
        current, retail = number(structured.get("price")), number(structured.get("retail_price"))
        promo = structured.get("promotion")
        if promo is not None and not isinstance(promo, dict):
            raise SourceError("invalid_promotion")
        promo = promo or {}
        old_price = number(promo.get("oldPrice"))
        if current is not None:
            base = old_price if old_price is not None else retail
            market.update(price=base if base is not None and base > current else current,
                          discount_price=current if base is not None and base > current else None)
        comparative = number(structured.get("comparative_unit_price"))
        old_rate = number(promo.get("oldComparativeRate", structured.get("comparative_unit_price_brutto")))
        if comparative is not None:
            market.update(price_per_unit=old_rate if old_rate is not None and old_rate > comparative else comparative,
                          discount_price_per_unit=comparative if old_rate is not None and old_rate > comparative else None)
        if structured.get("comparative_unit"):
            market["price_per_unit_type"] = structured["comparative_unit"]
        status = str(structured.get("status", "")).casefold()
        if status in {"active", "inactive", "unavailable", "outofstock", "out_of_stock", "soldout"}:
            market["is_available"] = status == "active"
        data["promotion"] = promo
    except SourceError:
        market = {}
        data["notes"].append("Invalid website price/promotion data: retained existing price history.")
    data["market"] = market
    return data


class ProductRefreshSource(BarboraSource):
    def __init__(self, delay=.2, retries=1, timeout=12, max_pages=6):
        super().__init__(delay=delay, retries=retries, timeout=timeout, max_pages=max_pages)

    def product(self, snapshot):
        p = snapshot["product"]
        try:
            html, resolved = self.fetch(p.get("barbora_url") or "")
            return parse_full_page(html, resolved, p["sku"])
        except SourceError as exc:
            if str(exc) == "untrusted_url":
                raise
            original_error = str(exc)
        # Recovery is by exact SKU in a bounded current-category listing, never by name.
        path = snapshot.get("category_path")
        if not path:
            raise SourceError(original_error)
        urls = self.category_urls(path).get(p["sku"], set())
        if len(urls) != 1:
            raise SourceError("ambiguous_listing_match" if urls else original_error)
        html, resolved = self.fetch(next(iter(urls)))
        return parse_full_page(html, resolved, p["sku"])
