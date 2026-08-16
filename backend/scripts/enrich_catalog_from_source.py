#!/usr/bin/env python3
"""
Fill in the catalog fields that only the live store knows: garment length, fit,
and who modelled it.

`products.json` carried `"length": "Regular"` on all 29 products -- a
placeholder, not data. "Regular" isn't even a valid length for a skirt or a
dress under Eighth Hour's own guide; it exists only on the tops chart. So there
was no way to tell a customer where a hem would fall on them, which is what
height-based advice needs.

The live store publishes all of it, just not where you'd expect:

  * length and fit are Shopify **tags**, mixed in among colour and collection
    tags -- "Calf", "Cropped", "Short" alongside "Fig", "Best Sellers"
  * the model's height and size are prose in the product description:
    "Model: Lori is 5.6 ft and wears a size XXS."

Every one of the 31 live products carries exactly one length tag, so this is
complete rather than best-effort.

    python3 scripts/enrich_catalog_from_source.py             # from the cache
    python3 scripts/enrich_catalog_from_source.py --fetch     # refresh first
    python3 scripts/enrich_catalog_from_source.py --dry-run

Reads catalog_source.json, the cached response, and does NOT touch the network
unless asked. Refetching is a deliberate act, not something that happens every
run.
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from py_src.constants import (  # noqa: E402
    COORD_LENGTH_CHART_ORDER,
    GARMENT_LENGTH_CHART_IN,
    MODEL_HEIGHTS_CM,
)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "catalog_source.json"
CATALOG = ROOT / "products.json"
SOURCE_URL = "https://www.eighth-hour.com/products.json?limit=250"

# Tag vocabulary. Length names come straight from the charts; anything a chart
# defines for some category is a candidate, so this can't drift from them.
LENGTH_TAGS = {name for chart in GARMENT_LENGTH_CHART_IN.values() for name in chart}
FIT_TAGS = {"Relaxed", "Slim", "Snug"}

MODEL_RE = re.compile(r"Model:\s*(?P<name>\w+)\s+is\s+(?P<feet>\d+)\.(?P<inches>\d+)\s*ft", re.I)


def fetch_source():
    """Deliberate, explicit refresh of the cached store response."""
    import urllib.request

    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request) as response:
        payload = response.read()
    SOURCE.write_bytes(payload)
    print(f"  refreshed {SOURCE.name} ({len(payload)} bytes)")


def plain_text(markup):
    return html.unescape(re.sub(r"<[^>]+>", " ", markup or ""))


def model_from(product):
    """(name, height_cm) from the description prose, or (None, None)."""
    match = MODEL_RE.search(plain_text(product.get("body_html")))
    if not match:
        return None, None
    name = match.group("name")
    if name in MODEL_HEIGHTS_CM:
        return name, MODEL_HEIGHTS_CM[name]
    # A model the constants don't list: read the height off the prose rather
    # than dropping the product, using the same feet-inches convention.
    inches = int(match.group("feet")) * 12 + int(match.group("inches"))
    return name, round(inches * 2.54, 1)


def length_chart_for(category):
    """The chart a category's length tag should be read against."""
    if category in GARMENT_LENGTH_CHART_IN:
        return GARMENT_LENGTH_CHART_IN[category]
    if category == "Co-ord Sets":
        merged = {}
        for source in reversed(COORD_LENGTH_CHART_ORDER):
            merged.update(GARMENT_LENGTH_CHART_IN[source])
        return merged
    return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="refresh the cache first")
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = parser.parse_args()

    if args.fetch:
        fetch_source()
    if not SOURCE.exists():
        raise SystemExit(f"{SOURCE} missing -- run once with --fetch")

    live = {p["handle"]: p for p in json.loads(SOURCE.read_text())["products"]}
    catalog = json.loads(CATALOG.read_text())

    updated, unmatched, no_length, changes = 0, [], [], []
    for product in catalog:
        source = live.get(product["slug"])
        if source is None:
            # Delisted since the catalog was captured, so its real length is
            # unknowable from here. Clear the placeholder rather than leave it:
            # "Regular" is a genuine class on the tops chart, so leaving it
            # would look like verified data and produce confident length advice
            # from a value nobody ever set. None makes the gap visible, and
            # _generate_length_note stays silent instead of guessing.
            # Explicit nulls rather than absent keys, so every product carries
            # the same schema. Missing keys read the same through .get(), but a
            # ragged catalog invites a future consumer to assume a field exists
            # because 27 of 29 have it.
            product["length"] = None
            for field in ("fit", "model_name", "model_height_cm", "model_size"):
                product.setdefault(field, None)
            unmatched.append(product["slug"])
            continue

        tags = set(source.get("tags", []))
        lengths = sorted(tags & LENGTH_TAGS)
        model_name, model_height = model_from(source)

        chart = length_chart_for(product["category"])
        usable = [name for name in lengths if name in chart]
        if not usable:
            no_length.append((product["slug"], product["category"], lengths))
        else:
            # Prefer the most specific name the chart knows ("Calf Length" over
            # "Calf") so the stored value reads the way the guide prints it.
            new_length = max(usable, key=len)
            if product.get("length") != new_length:
                changes.append((product["slug"], product.get("length"), new_length))
            product["length"] = new_length

        fits = sorted(tags & FIT_TAGS)
        if fits:
            product["fit"] = fits[0]
        if model_name:
            product["model_name"] = model_name
            product["model_height_cm"] = model_height
        size_match = re.search(r"wears a size (\w+)", plain_text(source.get("body_html")))
        if size_match:
            product["model_size"] = size_match.group(1).upper()
        updated += 1

    print(f"  products in catalog        : {len(catalog)}")
    print(f"  matched against live store : {updated}")
    if unmatched:
        print(f"  NOT on the live store      : {unmatched}")
    if no_length:
        print("  no usable length tag:")
        for slug, category, tags in no_length:
            print(f"    {slug} ({category}) had {tags or 'no length tags'}")
    print(f"  length changed             : {len(changes)}")
    for slug, before, after in changes[:40]:
        print(f"    {slug:46} {before} -> {after}")

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return 0
    CATALOG.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"\n  wrote {CATALOG.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
