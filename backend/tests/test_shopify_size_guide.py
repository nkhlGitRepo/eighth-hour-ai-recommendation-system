"""
The size drawer in the store's MyStyle theme is generated from the engine's
size chart (shopify/build_theme.py), so the two can never disagree. These pin
the generated tables to the chart, and the inch figures to the ones Eighth
Hour publishes in its October 2026 guide.
"""

import importlib.util
from pathlib import Path

import pytest

from py_src.constants import SIZE_CHART_SOURCE, STANDARD_SIZES

_SCRIPT = Path(__file__).resolve().parents[2] / "shopify" / "build_theme.py"
if not _SCRIPT.exists():
    pytest.skip("shopify/build_theme.py not present in this checkout", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("build_theme", _SCRIPT)
build_theme = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_theme)


@pytest.fixture(scope="module")
def snippet():
    return build_theme.size_guide_snippet()


def table(snippet, kind):
    start = snippet.index(f"mystyle_kind == '{kind}'")
    end = snippet.index("{%- ", start + 1)
    return snippet[start:end]


def test_every_size_and_centimetre_range_comes_from_the_chart(snippet):
    full = table(snippet, "all")
    for size in STANDARD_SIZES:
        for dimension in ("bust", "waist", "hips"):
            low, high = SIZE_CHART_SOURCE[size][dimension]
            assert f"{low:g}–{high:g}" in full, (size, dimension)


@pytest.mark.parametrize("kind, row", [
    # The brand's own inch tables (updated Oct '26).
    ("tops", "<td>XXS</td><td>0-2</td><td>4-6</td><td>33–34</td><td>25½–26½</td>"),
    ("tops", "<td>XXL</td><td>24-26</td><td>28-30</td><td>45–47½</td><td>37½–40</td>"),
    ("bottoms", "<td>M</td><td>12-14</td><td>16-18</td><td>31½–32½</td><td>41–42</td>"),
    ("bottoms", "<td>XXL</td><td>24-26</td><td>28-30</td><td>37½–40</td><td>47½–50</td>"),
    ("all", "<td>L</td><td>16-18</td><td>20-22</td><td>41–42½</td><td>33½–35</td><td>43–44½</td>"),
])
def test_inch_figures_match_the_published_guide(snippet, kind, row):
    assert row in table(snippet, kind)


def test_tables_show_the_measurements_each_garment_is_sized_on(snippet):
    assert "<th>Bust</th><th>Waist</th></tr>" in table(snippet, "tops")
    assert "<th>Waist</th><th>Hips</th></tr>" in table(snippet, "bottoms")
    assert "<th>Bust</th><th>Waist</th><th>Hips</th></tr>" in table(snippet, "all")
