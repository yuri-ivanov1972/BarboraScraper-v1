"""Strict read-only Barbora fetching/parsing for the one-time reload."""

import json
import math
import re
import threading
import time
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from barbora_parser import BarboraParser


class SourceError(ValueError):
    """Safe, public error code, never raw HTTP/connection diagnostics."""


def trusted_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {"barbora.lv", "www.barbora.lv"}
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise SourceError("untrusted_url")
    return url


def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    match = re.search(
        r"window\.reportUserActionToGa4\(window\.ga4EventTypes\.viewItem,\s*"
        r"\{[^}]*items:\s*\[(\{[^}]+\})\]", html, re.S
    )
    sku = str(json.loads(match.group(1)).get("item_id", "")) if match else ""
    name = soup.h1.get_text(" ", strip=True) if soup.h1 else ""
    if not sku or not name:
        raise SourceError("missing_product_identity")
    title = next((h for h in soup.find_all(["h3", "h4"])
                  if "uzturvērtība" in h.get_text(" ", strip=True).lower()), None)
    candidate = {"sku": sku, "name": name, "nutrition": {}, "nutrition_issue": None}
    if title is None:
        candidate["nutrition_issue"] = "absent_nutrition"
        return candidate
    if not re.search(r"\b100\s*(?:g|ml)\b", title.get_text(" ", strip=True), re.I):
        candidate["nutrition_issue"] = "unsupported_nutrition_basis"
        return candidate
    table = title.find_next("table")
    if table is None:
        candidate["nutrition_issue"] = "absent_nutrition"
        return candidate
    labels = {
        "tauki": "fat_total", "piesātinātas taukskābes": "fat_saturated",
        "ogļhidrāti": "carbs_total", "cukuri": "carbs_sugars",
        "olbaltumvielas": "protein", "sāls": "salt",
        "šķiedrvielas": "fiber",
    }
    def put(field, number):
        value = float(number.replace(",", "."))
        if not math.isfinite(value) or value < 0 or (
                field not in {"energy_kj", "energy_kcal"} and value > 100):
            raise SourceError("invalid_nutrition_value")
        if field in candidate["nutrition"] and candidate["nutrition"][field] != value:
            raise SourceError("conflicting_nutrition_rows")
        candidate["nutrition"][field] = value
    try:
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            label = cells[0].get_text(" ", strip=True).lower().strip(": ")
            value = cells[1].get_text(" ", strip=True)
            if "enerģētiskā" in label:
                parts = re.fullmatch(
                    r"\s*([+-]?\d+(?:[.,]\d+)?)\s*(kJ|kcal)"
                    r"(?:\s*/\s*([+-]?\d+(?:[.,]\d+)?)\s*(kJ|kcal))?\s*",
                    value, re.I
                )
                if not parts:
                    raise SourceError("invalid_energy_units_or_value")
                put("energy_" + parts[2].lower(), parts[1])
                if parts[3]:
                    put("energy_" + parts[4].lower(), parts[3])
            elif label in labels:
                part = re.fullmatch(r"\s*([+-]?\d+(?:[.,]\d+)?)\s*g\s*", value, re.I)
                if not part:
                    raise SourceError("invalid_nutrient_units_or_value")
                put(labels[label], part[1])
    except (ValueError, OverflowError) as exc:
        candidate["nutrition_issue"] = str(exc) if isinstance(exc, SourceError) else "invalid_nutrition"
    return candidate


class BarboraSource:
    """Rate-limit all requests, validate redirects before following them."""

    def __init__(self, delay=0.75, retries=2, timeout=20, max_pages=30):
        self.delay, self.retries, self.timeout = delay, retries, timeout
        self.max_pages = max_pages
        self.lock = threading.Lock()
        self.next_request = 0
        self.local = threading.local()
        self.category_lock = threading.Lock()
        self.category_cache = {}
        self.helper = BarboraParser()

    def fetch(self, url):
        trusted_url(url)
        if not hasattr(self.local, "session"):
            self.local.session = self.helper._create_session()
        for attempt in range(self.retries + 1):
            try:
                target = url
                for _ in range(6):
                    with self.lock:
                        time.sleep(max(0, self.next_request - time.monotonic()))
                        self.next_request = time.monotonic() + self.delay
                    response = self.local.session.get(
                        trusted_url(target), timeout=self.timeout, allow_redirects=False
                    )
                    if response.status_code in {301, 302, 303, 307, 308}:
                        target = trusted_url(urljoin(target, response.headers.get("Location", "")))
                        continue
                    if response.status_code in {404, 410}:
                        raise SourceError("page_not_found")
                    if response.status_code == 429 or response.status_code >= 500:
                        raise requests.RequestException("retryable")
                    if response.status_code != 200:
                        raise SourceError("http_" + str(response.status_code))
                    return response.text, target
                raise SourceError("too_many_redirects")
            except requests.RequestException:
                if attempt == self.retries:
                    raise SourceError("request_failed") from None
                time.sleep(min(30, 2 ** (attempt + 1)))

    def category_urls(self, path):
        # A cache entry is recorded only after a completely successful listing.
        with self.category_lock:
            if path in self.category_cache:
                return self.category_cache[path]
            found = {}
            for page in range(1, self.max_pages + 1):
                html, _ = self.fetch(self.helper.build_category_url(path, page))
                products = self.helper._extract_product_list_json(html)
                if not products and "window.b_productList" not in html:
                    raise SourceError("category_listing_unresolved")
                for product in products:
                    sku, slug = str(product.get("id", "")), product.get("Url", "")
                    if sku and slug:
                        found.setdefault(sku, set()).add(
                            trusted_url(self.helper.build_product_url(slug))
                        )
                if len(products) < self.helper.PRODUCTS_PER_PAGE:
                    self.category_cache[path] = found
                    return found
            raise SourceError("category_page_limit")

    def product(self, row):
        original_issue = "missing_url"
        url = row["product"].get("barbora_url")
        if url:
            try:
                html, resolved = self.fetch(url)
                candidate = parse_page(html)
                if candidate["sku"] == row["product"]["sku"]:
                    return dict(candidate, fetched_url=resolved, recovered_url=False)
                original_issue = "identity_mismatch"
            except SourceError as exc:
                original_issue = str(exc)
        # Never fetch a name-matched substitute or an untrusted redirect destination.
        if original_issue == "untrusted_url":
            raise SourceError(original_issue)
        path = row.get("category_path")
        if not path:
            raise SourceError(original_issue)
        urls = self.category_urls(path).get(row["product"]["sku"], set())
        if len(urls) != 1:
            raise SourceError("ambiguous_listing_match" if urls else original_issue)
        html, resolved = self.fetch(next(iter(urls)))
        candidate = parse_page(html)
        if candidate["sku"] != row["product"]["sku"]:
            raise SourceError("identity_mismatch")
        return dict(candidate, fetched_url=resolved, recovered_url=True)
