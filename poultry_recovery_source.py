"""Bounded, strict website discovery for this one missing category."""

import json
import re

from barbora_parser import BarboraParser
from nutrition_reload_source import SourceError
from product_refresh_source import ProductRefreshSource, parse_full_page

CODE = "8a626638-f481-4299-a438-eb24495c3fb1"
PATH = "gala-zivs-un-gatava-kulinarija/svaiga-putnu-gala/malta-putnu-gala"
URL = "https://barbora.lv/" + PATH
NAME = "Malta putnu gaļa"
ROOT_CODE = "1271e464-f471-4dc6-b286-7ea771a218a8"
PARENT_CODE = "46eb6b9e-9fc8-4096-a0fc-84df8d1b9107"


def fetch_candidates(source=None):
    source = source or ProductRefreshSource()
    parser = BarboraParser()
    seen, candidates = set(), []
    for page in range(1, 7):
        html, final_url = source.fetch(URL + (f"?page={page}" if page > 1 else ""))
        if final_url.split("?")[0].rstrip("/") != URL:
            raise SourceError("category_redirect_mismatch")
        match = re.search(r"window\.b_productList\s*=\s*", html)
        if not match:
            raise SourceError("missing_category_product_list")
        try:
            listing = json.JSONDecoder().raw_decode(html[match.end():])[0]
        except (ValueError, TypeError):
            raise SourceError("invalid_category_product_list") from None
        if not isinstance(listing, list):
            raise SourceError("invalid_category_product_list")
        for record in listing:
            if (not isinstance(record, dict) or record.get("category_id") != CODE
                    or record.get("category_path_url") != PATH):
                raise SourceError("category_identity_mismatch")
            sku = record.get("id")
            if not isinstance(sku, str) or not re.fullmatch(r"\d{18}", sku) or sku in seen:
                raise SourceError("invalid_or_duplicate_sku")
            seen.add(sku)
            info = parser._parse_product_from_json(record)
            if not info.url:
                raise SourceError("missing_product_url")
            product_html, product_url = source.fetch(info.url)
            candidate = parse_full_page(product_html, product_url, sku)
            if candidate.get("category_code") != CODE or candidate.get("category_path") != PATH:
                raise SourceError("product_category_mismatch")
            candidates.append(candidate)
        if len(listing) < parser.PRODUCTS_PER_PAGE:
            if not candidates:
                raise SourceError("empty_category")
            return candidates
    raise SourceError("category_page_limit")
