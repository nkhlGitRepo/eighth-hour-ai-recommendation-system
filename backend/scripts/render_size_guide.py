#!/usr/bin/env python3
"""
Regenerate the Size Guide tables in Base_Website/size-guide.html from the chart
the recommendation engine actually uses.

Why this exists: the page used to carry the same numbers typed out by hand,
under a comment promising they matched SIZE_CHART_SOURCE. They stopped matching
the first time the chart was revised, and nothing noticed -- a customer could
read one range on the Size Guide and be recommended a size derived from another.
Generating the rows means the page cannot drift, and
tests/test_size_guide_page.py fails the build if someone edits them by hand.

    python3 scripts/render_size_guide.py            # rewrite the page
    python3 scripts/render_size_guide.py --check    # exit 1 if it's stale

The three tables mirror how M3 actually sizes each category: tops on the bust,
bottoms on the hips, dresses on the bust with waist and hips shown alongside.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from py_src.constants import SIZE_CHART_SOURCE, STANDARD_SIZES  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
# The storefront lives in Base_Website/ on main and at the repo root on the
# gh-pages branch, which GitHub Pages serves from.
PAGE = next(
    (p for p in (_REPO / "Base_Website" / "size-guide.html", _REPO / "size-guide.html") if p.exists()),
    _REPO / "Base_Website" / "size-guide.html",
)

# Which dimensions each table shows, keyed by the id on its <table>.
TABLES = {
    "size-table-tops": ("bust", "waist"),
    "size-table-dresses": ("bust", "waist", "hips"),
    "size-table-bottoms": ("waist", "hips"),
}


def _cm(value: float) -> str:
    """Trim the trailing '.0' so whole centimetres read as '91', not '91.0'."""
    return f"{value:g}"


def _range(size: str, dimension: str) -> str:
    low, high = SIZE_CHART_SOURCE[size][dimension]
    return f"{_cm(low)}–{_cm(high)}"  # en dash, matching the site's copy


def render_rows(dimensions, indent="        ") -> str:
    return "\n".join(
        f"{indent}<tr><th scope=\"row\">{size}</th>"
        + "".join(f"<td>{_range(size, d)}</td>" for d in dimensions)
        + "</tr>"
        for size in STANDARD_SIZES
    )


def render_page(html: str) -> str:
    """Replace each table's <tbody> with rows built from the chart."""
    for table_id, dimensions in TABLES.items():
        pattern = re.compile(
            r'(<table class="size-table" id="' + re.escape(table_id) + r'">.*?<tbody>\n)'
            r".*?"
            r"(\n\s*</tbody>)",
            re.DOTALL,
        )
        if not pattern.search(html):
            raise SystemExit(
                f"{PAGE.name}: no <table class=\"size-table\" id=\"{table_id}\"> with a "
                f"<tbody> to fill. The page markup changed -- update TABLES here."
            )
        html = pattern.sub(
            lambda m: m.group(1) + render_rows(dimensions) + m.group(2), html, count=1
        )
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="don't write; exit 1 if the page no longer matches the chart",
    )
    args = parser.parse_args()

    current = PAGE.read_text(encoding="utf-8")
    updated = render_page(current)

    if args.check:
        if current != updated:
            print(f"{PAGE} is out of date -- run scripts/render_size_guide.py")
            return 1
        print(f"{PAGE.name} matches SIZE_CHART_SOURCE")
        return 0

    if current == updated:
        print(f"{PAGE.name} already matches SIZE_CHART_SOURCE")
        return 0
    PAGE.write_text(updated, encoding="utf-8")
    print(f"Rewrote {len(TABLES)} tables in {PAGE.name} from SIZE_CHART_SOURCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
