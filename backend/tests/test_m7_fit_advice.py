"""
M7's advice beyond the headline size (FitChecker._fit_advice): how her size
fits at each area the garment is sized on, what to choose when she measures a
different size at one of them, and a styling tip for her shape and the piece.

Measurements come from the published chart (SIZE_CHART_SOURCE) -- a range's
middle, its edges, the gap between two sizes -- so these follow the chart if
it changes.
"""

from unittest.mock import MagicMock

import pytest

from py_src.constants import CATEGORY_ZONE, SIZE_CHART_SOURCE, SILHOUETTE_TIP_ORDER, STYLING_TIPS
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.modules.m7_fit_checker import FitChecker


@pytest.fixture
def checker():
    return FitChecker(consent_tracker=MagicMock(has_measurement_consent=MagicMock(return_value=True)))


def piece(category="Dresses", silhouettes=("a_line",), sizes=("XS", "S", "M", "L"), fabric="Silk", fit=None, **extra):
    raw = {"sku": "p", "slug": "p", "name": "Piece", "category": category, "sizes": list(sizes), "fabric": fabric,
           "price": 1, "colors": ["Black"], "silhouettes": list(silhouettes), "fit": fit, **extra}
    return CatalogKB([raw]).get_item("p")


def mid(size, area):
    low, high = SIZE_CHART_SOURCE[size][area]
    return (low + high) / 2


def gap(smaller, larger, area):
    """A measurement in the published gap between two sizes."""
    return (SIZE_CHART_SOURCE[smaller][area][1] + SIZE_CHART_SOURCE[larger][area][0]) / 2


def body(size="XS", height=165, **overrides):
    m = {area: mid(size, area) for area in ("bust", "waist", "hips")}
    m["height"] = height
    m.update(overrides)
    return m


class TestFitByArea:
    @pytest.mark.parametrize("category, areas", [
        ("Tops", ["bust"]), ("Vests", ["bust"]), ("Jackets", ["bust"]),
        ("Skirts", ["waist", "hips"]), ("Trousers", ["waist", "hips"]),
        ("Dresses", ["bust", "waist", "hips"]), ("Co-ord Sets", ["bust", "waist", "hips"]),
    ])
    def test_covers_the_areas_the_garment_is_sized_on(self, checker, category, areas):
        result = checker.check_fit("u", body(), piece(category=category), shape_class="hourglass")
        assert [a["area"] for a in result["fit_by_area"]] == areas

    def test_apple_tops_include_the_waist_they_are_sized_on(self, checker):
        result = checker.check_fit("u", body(), piece(category="Tops"), shape_class="apple")
        assert [a["area"] for a in result["fit_by_area"]] == ["bust", "waist"]

    def test_describes_where_she_sits_in_the_published_range(self, checker):
        low, high = SIZE_CHART_SOURCE["S"]["bust"]
        third = (high - low) / 3
        for value, word in [(low - 0.5, "roomy"), (low + third / 2, "relaxed"), ((low + high) / 2, "true to size"),
                            (high - third / 2, "close"), (high + 0.5, "snug")]:
            assert checker._describe_area_fit(value, low, high) == word

    def test_middle_of_her_size_reads_true_to_size_everywhere(self, checker):
        result = checker.check_fit("u", body("M"), piece(), shape_class="hourglass")
        assert result["recommended_size"] == "M"
        assert {a["fit"] for a in result["fit_by_area"]} == {"true to size"}

    def test_a_custom_size_chart_has_no_published_ranges_to_compare(self, checker):
        chart = {s: {"bust": mid(s, "bust"), "waist": mid(s, "waist"), "hips": mid(s, "hips")} for s in ("XS", "S", "M", "L")}
        product = dict(piece(), size_chart=chart)     # handed to M7 directly; the catalog keeps no per-product chart
        result = checker.check_fit("u", body(), product, shape_class="hourglass")
        assert result["fit_by_area"] == []


class TestBetweenSizes:
    def test_in_the_gap_she_is_told_which_to_choose(self, checker):
        result = checker.check_fit("u", body("XS", hips=gap("XS", "S", "hips")), piece(), shape_class="hourglass")
        assert result["recommended_size"] == "XS"
        tip = result["tips"][0]
        assert tip.startswith("At the hips you measure between XS and S.")
        assert "Silk has little give, so choose S" in tip

    def test_a_relaxed_cut_one_size_up_still_fits(self, checker):
        result = checker.check_fit("u", body("XS", hips=gap("XS", "S", "hips")), piece(fit="Relaxed"), shape_class="hourglass")
        assert "cut relaxed, so XS should still be comfortable" in result["tips"][0]

    def test_a_close_cut_points_her_up(self, checker):
        result = checker.check_fit("u", body("XS", hips=gap("XS", "S", "hips")), piece(fit="Slim"), shape_class="hourglass")
        assert "cut close to the body, so S will feel easier" in result["tips"][0]

    def test_stretch_fabric_one_size_up_still_fits(self, checker):
        result = checker.check_fit("u", body("XS", hips=gap("XS", "S", "hips")), piece(fabric="Stretch jersey"), shape_class="hourglass")
        assert "the fabric has some stretch, so XS should be comfortable" in result["tips"][0]

    def test_points_at_the_size_she_measures_not_just_the_next(self, checker):
        result = checker.check_fit("u", body("XS", hips=mid("M", "hips")), piece(), shape_class="hourglass")
        assert result["tips"][0].startswith("At the hips you measure M. Silk has little give, so choose M")

    def test_says_so_when_no_stocked_size_is_big_enough(self, checker):
        result = checker.check_fit("u", body("XS", hips=mid("L", "hips")), piece(sizes=("XS", "S")), shape_class="hourglass")
        assert result["tips"][0] == "At the hips you measure L; the largest size here is S, which may still feel snug there."

    def test_a_smaller_area_gets_room_not_a_change(self, checker):
        result = checker.check_fit("u", body("M", waist=mid("S", "waist")), piece(), shape_class="hourglass")
        assert result["recommended_size"] == "M"
        assert result["tips"][0] == "At the waist you measure S, so M will have a little extra room there."

    def test_only_areas_the_garment_covers_count(self, checker):
        """A top doesn't care about the hips."""
        result = checker.check_fit("u", body("XS", hips=mid("L", "hips")), piece(category="Tops"), shape_class="hourglass")
        assert not any("hips" in t for t in result["tips"])

    def test_no_size_comparison_when_her_size_is_not_stocked(self, checker):
        """The closest-available note already says it."""
        result = checker.check_fit("u", body("XXS", hips=gap("XXS", "XS", "hips")), piece(), shape_class="hourglass")
        assert result["closest_available"]
        assert not any(t.startswith("At the") for t in result["tips"])


class TestStylingTip:
    @pytest.mark.parametrize("shape", sorted(STYLING_TIPS))
    @pytest.mark.parametrize("category", sorted(CATEGORY_ZONE))
    def test_every_shape_and_garment_type_gets_its_tip(self, checker, shape, category):
        product = piece(category=category, silhouettes=("flowing", "a_line"))
        tip = STYLING_TIPS[shape]["a_line"]          # a_line ranks above flowing
        expected = tip[CATEGORY_ZONE[category]] if isinstance(tip, dict) else tip
        assert checker._styling_tip(product, shape) == expected

    def test_the_most_telling_silhouette_speaks(self, checker):
        assert SILHOUETTE_TIP_ORDER.index("fitted") < SILHOUETTE_TIP_ORDER.index("straight")
        product = piece(category="Jackets", silhouettes=("straight", "fitted"))
        assert checker._styling_tip(product, "pear") == STYLING_TIPS["pear"]["fitted"]["top"]

    def test_no_shape_no_tip(self, checker):
        assert checker._styling_tip(piece(), None) is None

    def test_it_is_the_last_tip_on_the_product_page(self, checker):
        result = checker.check_fit("u", body("XS", hips=gap("XS", "S", "hips")), piece(), shape_class="pear")
        assert result["tips"][-1] == STYLING_TIPS["pear"]["a_line"]
