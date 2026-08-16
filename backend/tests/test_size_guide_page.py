"""
The published Size Guide page must agree with the chart the engine sizes on.

This is a cross-boundary check rather than a unit test: the page is static HTML
in a different tree, so nothing else in the suite would notice it going stale.
It did go stale once -- the page still showed a six-size chart with different
ranges after the official seven-size chart landed, under a comment claiming the
two matched. A customer reading one range and being recommended a size derived
from another is exactly the kind of quiet inconsistency the whole
single-source-of-truth arrangement exists to prevent.
"""

import re
from pathlib import Path

import pytest

from py_src.constants import SIZE_CHART_SOURCE, STANDARD_SIZES

import importlib.util

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_size_guide.py"
_spec = importlib.util.spec_from_file_location("render_size_guide", _SCRIPT)
render_size_guide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_size_guide)

PAGE = render_size_guide.PAGE


@pytest.fixture(scope="module")
def html():
    if not PAGE.exists():
        pytest.skip(f"{PAGE} not present in this checkout")
    return PAGE.read_text(encoding="utf-8")


def test_page_is_what_the_generator_would_write(html):
    """
    The strongest form of the check: regenerating from the chart must be a
    no-op. Catches a hand-edited row, a missing size, and a chart change that
    was never pushed to the page, all at once.
    """
    assert render_size_guide.render_page(html) == html, (
        "Base_Website/size-guide.html no longer matches SIZE_CHART_SOURCE -- "
        "run backend/scripts/render_size_guide.py"
    )


@pytest.mark.parametrize("size", STANDARD_SIZES)
def test_every_size_is_listed(html, size):
    """A size the engine can recommend but the guide never mentions leaves a
    customer with no way to check the recommendation against anything."""
    assert f'<th scope="row">{size}</th>' in html, f"{size} is missing from the Size Guide"


@pytest.mark.parametrize("table_id,dimensions", render_size_guide.TABLES.items())
def test_table_shows_the_dimensions_that_size_that_category(html, table_id, dimensions):
    """
    Each table must show exactly the measurements M3 sizes that category on --
    hips for bottoms, bust for tops -- so the guide explains the recommendation
    rather than showing numbers that had no part in it.
    """
    body = re.search(
        r'<table class="size-table" id="' + re.escape(table_id) + r'">(.*?)</table>',
        html,
        re.DOTALL,
    )
    assert body, f"no table with id {table_id}"
    rows = re.findall(r'<th scope="row">(\w+)</th>((?:<td>[^<]*</td>)+)', body.group(1))
    assert [size for size, _ in rows] == STANDARD_SIZES

    for size, cells in rows:
        values = re.findall(r"<td>([^<]*)</td>", cells)
        assert len(values) == len(dimensions), (
            f"{table_id}/{size} has {len(values)} columns, expected {len(dimensions)}"
        )
        for value, dimension in zip(values, dimensions):
            low, high = SIZE_CHART_SOURCE[size][dimension]
            assert value == f"{low:g}–{high:g}", (
                f"{table_id}/{size} {dimension} reads {value}, chart says {low:g}–{high:g}"
            )
