"""
Engine products from what the Shopify theme sends.

The theme fetches the store's live product list in the shopper's own browser
(so it sees exactly what she can buy, in her market, with real stock) and
sends it with each request, together with the brand's launch data -- the first
drop's styles, their SKUs and style tags, and the launch colours -- which lives
in the theme. Nothing here is stored: each request builds its own small catalog.

Only first-drop products are used. A product counts when every SKU on it is one
the launch data lists for a single style; that keeps out the Essentials being
retired, including the two that reuse a launch SKU on another product. Pieces
the developer hasn't uploaded yet simply aren't in the list until they are.
"""

import html
import re

from py_src.constants import (
    CATEGORY_TO_SIZE_PROFILE_KEY,
    GARMENT_LENGTH_CHART_IN,
    MODEL_HEIGHTS_CM,
    STANDARD_SIZES,
)
from py_src.modules.m4_style_preference import StyleProfile

MAX_PRODUCTS = 250
MAX_STYLES = 60
MAX_COLORS = 40
MAX_TEXT = 2000

CATEGORIES = set(CATEGORY_TO_SIZE_PROFILE_KEY)
LENGTH_TAGS = {name for chart in GARMENT_LENGTH_CHART_IN.values() for name in chart}
FIT_RE = re.compile(r"\b(relaxed|slim|snug)\b(?:[\s,]+[a-z-]+)?\s+fit\b", re.I)
MODEL_RE = re.compile(
    r"Model:\s*(?P<name>\w+)\s+is\s+(?P<feet>\d+)\.(?P<inches>\d+)\s*ft"
    r"(?:.*?wears\s+a\s+size\s+(?P<size>XXS|XS|S|M|L|XL|XXL)\b)?",
    re.I,
)
HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,254}$")


def _text(value, limit=200):
    return value.strip()[:limit] if isinstance(value, str) else ""


def _vocab(values, vocabulary):
    """Brand spellings ("A-Line", "Work") to the quiz's values ("a_line", "work")."""
    out = []
    for value in values if isinstance(values, list) else []:
        key = _text(value, 40).casefold().replace("-", "_").replace(" ", "_")
        if key in vocabulary and key not in out:
            out.append(key)
    return out


class LaunchData:
    """The brand's first-drop data, as the theme supplies it."""

    def __init__(self, raw):
        raw = raw if isinstance(raw, dict) else {}
        self.styles = []
        self.style_by_sku = {}
        for style in (raw.get("styles") or [])[:MAX_STYLES]:
            if not isinstance(style, dict):
                continue
            category = _text(style.get("category"), 40)
            skus = {_text(s, 80).upper() for s in style.get("skus") or [] if _text(s, 80)}
            if category not in CATEGORIES or not skus:
                continue
            parsed = {
                "name": _text(style.get("name")),
                "category": category,
                "fabric": _text(style.get("fabric"), 80) or "Silk",
                "skus": skus,
                "silhouettes": _vocab(style.get("silhouettes"), StyleProfile.VALID_SILHOUETTES),
                "occasions": _vocab(style.get("occasions"), StyleProfile.VALID_OCCASIONS),
            }
            self.styles.append(parsed)
            for sku in skus:
                self.style_by_sku[sku] = parsed

        self.colors = []
        for color in (raw.get("colors") or [])[:MAX_COLORS]:
            if isinstance(color, dict) and _text(color.get("name"), 60):
                hex_value = _text(color.get("hex"), 9)
                self.colors.append({
                    "name": _text(color.get("name"), 60),
                    "hex": hex_value if re.fullmatch(r"#[0-9a-fA-F]{6}", hex_value) else None,
                })

    def color_names(self):
        return [c["name"] for c in self.colors]

    def brand_spelling(self, color):
        """A store colour in the brand's spelling ("Forest green" -> "Forest Green")."""
        return next((c["name"] for c in self.colors if c["name"].casefold() == color.casefold()), color)


def _option_index(options, *names):
    for index, option in enumerate(options[:3]):
        name = option.get("name") if isinstance(option, dict) else option
        if isinstance(name, str) and name.strip().casefold() in names:
            return index
    return None


def _plain(markup):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))).strip()


def to_engine_product(raw, launch: LaunchData):
    """One theme-supplied product as an engine product, or None if it isn't a
    first-drop piece (or is malformed)."""
    if not isinstance(raw, dict):
        return None
    handle = _text(raw.get("handle"), 255)
    if not HANDLE_RE.match(handle):
        return None

    variants = [v for v in (raw.get("variants") or []) if isinstance(v, dict)][:200]
    skus = {_text(v.get("sku"), 80).upper() for v in variants if _text(v.get("sku"), 80)}
    styles = {id(launch.style_by_sku.get(sku)): launch.style_by_sku.get(sku) for sku in skus}
    if not skus or None in styles.values() or len(styles) != 1:
        return None
    style = next(iter(styles.values()))

    options = raw.get("options") or []
    color_at = _option_index(options, "color", "colour")
    size_at = _option_index(options, "size")

    def option_value(variant, index):
        values = variant.get("options")
        if isinstance(values, list) and index is not None and index < len(values):
            return _text(values[index], 60)
        return _text(variant.get(f"option{index + 1}"), 60) if index is not None else ""

    colors, sizes, stocked = [], [], {}
    for variant in variants:
        color, size = option_value(variant, color_at), option_value(variant, size_at)
        color = launch.brand_spelling(color) if color else color
        if color and color not in colors:
            colors.append(color)
        if size:
            if size not in sizes:
                sizes.append(size)
            stocked[size] = stocked.get(size, False) or bool(variant.get("available"))
    order = {size: i for i, size in enumerate(STANDARD_SIZES)}
    sizes.sort(key=lambda s: order.get(s, len(order)))
    if not sizes:
        return None

    body = _plain(raw.get("body") or raw.get("body_html") or raw.get("description"))[:MAX_TEXT]
    fit_match = FIT_RE.search(body)
    model = MODEL_RE.search(body)
    tags = raw.get("tags") or []
    tags = tags if isinstance(tags, list) else str(tags).split(",")
    length = next((t.strip() for t in tags if isinstance(t, str) and t.strip() in LENGTH_TAGS), None)
    published = _text(raw.get("published_at"), 40)

    model_name = model_height = model_size = None
    if model:
        model_name = model.group("name")
        model_height = MODEL_HEIGHTS_CM.get(model_name) or round(
            (int(model.group("feet")) * 12 + int(model.group("inches"))) * 2.54, 1)
        model_size = (model.group("size") or "").upper() or None

    return {
        "slug": handle,
        "name": _text(raw.get("title")) or style["name"] or handle,
        "category": style["category"],
        "fabric": style["fabric"],
        "price": 0.0,          # never shown: the theme shows Shopify's own price
        "colors": colors,
        "sizes": sizes,
        "sizes_in_stock": {size: stocked.get(size, False) for size in sizes},
        "in_stock": any(stocked.values()),
        "description": body[:600],
        "length": length,
        "fit": fit_match.group(1).capitalize() if fit_match else None,
        "silhouettes": style["silhouettes"],
        "occasions": style["occasions"],
        "launched_at": published[:10] if re.match(r"\d{4}-\d{2}-\d{2}", published) else None,
        "model_name": model_name,
        "model_height_cm": model_height,
        "model_size": model_size,
    }


def to_engine_products(raw_products, launch: LaunchData):
    products = []
    seen = set()
    for raw in (raw_products if isinstance(raw_products, list) else [])[:MAX_PRODUCTS]:
        product = to_engine_product(raw, launch)
        if product and product["slug"] not in seen:
            seen.add(product["slug"])
            products.append(product)
    return products
