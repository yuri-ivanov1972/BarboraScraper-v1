"""Shared, side-effect-free product image selection. Never invent rendition URLs."""
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup

SUPPORTED = {".png": 4, ".jpg": 3, ".jpeg": 3, ".webp": 2, ".gif": 1}
IMAGE_ACCEPT = "image/png,image/jpeg,image/webp,image/gif;q=0.8"
SIZES = {"xs": 1, "s": 2, "m": 3, "l": 4, "xl": 5, "xxl": 6}


def is_avif(value):
    if not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        query = parse_qs(p.query)
        return p.path.lower().endswith(".avif") or any(
            v.lower() in {"avif", "image/avif"} for k in ("format", "fm", "f")
            for v in query.get(k, []))
    except ValueError:
        return False


def image_url(value, retailer_only=True):
    """Validate an advertised image; queries are preserved, not rewritten."""
    if (not isinstance(value, str) or is_avif(value)
            or any(c.isspace() or ord(c) < 32 for c in value.strip())):
        return None
    try:
        p = urlsplit(value.strip())
        if (p.scheme != "https" or not p.hostname or p.username or p.password
                or p.port not in (None, 443)):
            return None
        if retailer_only and (p.hostname != "cdn.barbora.lv" or not p.path.startswith("/products/")):
            return None
        if any(token in p.path.lower() for token in ("placeholder", "no-image", "noimage", "/logo", "/banner", "/icon")):
            return None
        suffix = "." + p.path.rsplit(".", 1)[-1].lower()
        if suffix not in SUPPORTED:
            return None
        return urlunsplit(("https", p.hostname, p.path, p.query, ""))
    except ValueError:
        return None


def asset_key(value):
    """Only collapse known Barbora format/size variants, not distinct gallery views."""
    try:
        p = urlsplit(value)
    except ValueError:
        return None
    stem = re.sub(r"\.(?:png|jpe?g|webp|gif|avif)$", "", p.path, flags=re.I)
    if p.hostname == "cdn.barbora.lv":
        stem = re.sub(r"_(?:xxl|xl|xs|l|m|s)$", "", stem, flags=re.I)
        return p.hostname, stem, p.query
    return p.hostname, p.path, p.query


def _candidates(value, width=0):
    if isinstance(value, str):
        # Actual srcset descriptors are sizing evidence, never part of a URL.
        # Do not split commas inside Cloudinary transforms or query parameters.
        for item in re.split(r",\s*(?=https?://|//)", value):
            parts = item.strip().split()
            if parts:
                size = re.fullmatch(r"(\d+(?:\.\d+)?)(w|x)", parts[1]) if len(parts) > 1 else None
                yield parts[0], float(size[1]) if size else width
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _candidates(item, width)
    elif isinstance(value, dict):
        w = value.get("width")
        w = w if isinstance(w, (int, float)) and not isinstance(w, bool) else width
        for key in ("url", "src", "srcset", "srcSet", "original", "variants", "sources"):
            if key in value:
                yield from _candidates(value[key], w)


def select_urls(values, retailer_only=True):
    chosen = {}
    for raw, width in _candidates(values):
        if is_avif(raw) and (key := _retailer_asset(raw)) and key not in chosen:
            chosen[key] = None  # Preserve its gallery position if a PNG variant appears later.
        url = image_url(raw, retailer_only)
        if not url:
            continue
        p = urlsplit(url)
        suffix = "." + p.path.rsplit(".", 1)[-1].lower()
        size = re.search(r"_(xxl|xl|xs|l|m|s)\.[^.]+$", p.path, re.I)
        # An advertised original with no size suffix beats guessed size assumptions.
        quality = width or (SIZES[size[1].lower()] if size else 7)
        rank = SUPPORTED[suffix], quality
        key = asset_key(url)
        if key not in chosen or chosen[key] is None or rank > chosen[key][0]:
            chosen[key] = rank, url
    return [item[1] for item in chosen.values() if item is not None]


def structured_photos(product):
    return [product.get(k) for k in ("imagesOriginal", "images", "gallery", "big_image", "image")]


def _retailer_asset(value):
    try:
        p = urlsplit(value)
        if (p.scheme == "https" and p.hostname == "cdn.barbora.lv"
                and p.path.startswith("/products/") and not p.username and not p.password
                and p.port in (None, 443)):
            return asset_key(value)
    except ValueError:
        pass
    return None


def product_photos(product=None, html=None):
    """Read only product-gallery DOM and product-specific structured values."""
    values = structured_photos(product or {})
    seeds = {key for raw, _ in _candidates(values) if (key := _retailer_asset(raw))}
    if html is not None:
        soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "html.parser")
        roots = soup.select(".b-block-slider--slide, .product-gallery, .product__gallery, "
                            "[data-testid='product-gallery'], .product-image, .product__image, "
                            "img[itemprop='image']")
        entries, pictures = [], []
        for root in roots:
            if (root.find_parent(["nav", "header", "footer", "aside"])
                    or (not seeds and root.find_parent("a"))):
                continue
            images = [root] if root.name in ("source", "img") else root.find_all(["source", "img"])
            keys = {key for node in images for attr in ("srcset", "src", "data-src", "data-original")
                    for raw, _ in _candidates(node.get(attr)) if (key := _retailer_asset(raw))}
            gallery = (root.get("data-testid") == "product-gallery" or
                       bool(set(root.get("class", [])) &
                            {"b-block-slider--slide", "product-gallery", "product__gallery"}))
            if keys:
                entries.append((images, keys, gallery))
        for picture in (soup.find("main") or soup).find_all("picture"):
            if (picture.find_parent(["nav", "header", "footer", "aside"])
                    or (not seeds and picture.find_parent("a"))):
                continue
            candidates = [node.get(k) for node in picture.find_all(["source", "img"])
                          for k in ("srcset", "src", "data-src")]
            keys = {key for raw, _ in _candidates(candidates) if (key := _retailer_asset(raw))}
            if keys:
                pictures.append((picture.find_all(["source", "img"]), keys))
        if not seeds:
            # Explicit galleries outrank unclassed pictures; weak image-class
            # selectors must not hide a real gallery picture elsewhere.
            for images, keys, gallery in entries:
                if gallery:
                    seeds.update(keys)
            if not seeds and pictures:
                seeds.update(pictures[0][1])
            if not seeds and entries:
                seeds.update(entries[0][1])
        nodes = [node for images, keys, _ in entries if keys & seeds for node in images]
        nodes.extend(node for images, keys in pictures if keys & seeds for node in images)
        for node in nodes:
            for key in ("srcset", "src", "data-src", "data-original"):
                values.append(node.get(key))
    return select_urls(values)


def unsupported_only(product):
    values = structured_photos(product)
    return not select_urls(values) and any(is_avif(raw) for raw, _ in _candidates(values))
