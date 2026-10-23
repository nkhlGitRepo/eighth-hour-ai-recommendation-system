"""
Customers whose size a piece doesn't come in.

The launch capsule is cut XS-L (two pieces XS-M), while the size guide runs
XXS-XXL, so an XXS, XL or XXL customer -- or an L customer looking at the XS-M
trousers -- must still get a recommendation: the best-fitting size the piece
does come in, with her actual size and the fact that this is the closest
available stated plainly. The same answer has to reach the product page (M7),
the recommendation cards (M5) and New Releases (M9).

Bodies are taken from the published chart rather than typed in, so these keep
testing the same situations if the size guide is revised again.
"""

from datetime import datetime, timedelta, timezone

import pytest

from py_src.constants import STANDARD_SIZE_CHART, STANDARD_SIZES
from py_src.modules.m5_recommendation_engine import RecommendationEngine
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.modules.m7_fit_checker import FitChecker
from py_src.modules.m9_new_releases_feed import NewReleasesFeed


class _Consented:
    def has_measurement_consent(self, user_id):
        return True


def body(size, height=165.0):
    """A body at the middle of the chart's band for `size`."""
    measurements = {d: STANDARD_SIZE_CHART[size][d] for d in ("bust", "waist", "hips")}
    measurements["height"] = height
    return measurements


XS_TO_L = ["XS", "S", "M", "L"]
XS_TO_M = ["XS", "S", "M"]


def product(sku, category, sizes):
    return {"sku": sku, "slug": sku, "name": sku, "category": category, "sizes": sizes,
            "fabric": "Silk", "price": 250.0, "colors": ["Black"]}


@pytest.fixture
def checker():
    return FitChecker(consent_tracker=_Consented())


class TestFitCheckOutsideThePiecesSizes:
    @pytest.mark.parametrize("size, sizes, expected", [
        ("XXS", XS_TO_L, "XS"),
        ("XXL", XS_TO_L, "L"),
        ("XL", XS_TO_L, "L"),
        ("L", XS_TO_M, "M"),
    ])
    def test_recommends_the_closest_stocked_size_and_says_so(self, checker, size, sizes, expected):
        category = "Trousers" if sizes == XS_TO_M else "Tops"
        result = checker.check_fit("u", body(size), product("piece", category, sizes), known_size=size)

        assert result["recommended_size"] == expected
        assert result["customer_size"] == size
        assert result["closest_available"] is True
        assert result["fit_notes"][0] == (
            f"Your size is {size}. This piece comes in {sizes[0]}–{sizes[-1]}, "
            f"so {expected} is the closest fit available."
        )

    def test_her_size_is_worked_out_when_the_caller_has_no_profile(self, checker):
        result = checker.check_fit("u", body("XXS"), product("top", "Tops", XS_TO_L))
        assert result["customer_size"] == "XXS"
        assert result["closest_available"] is True
        assert result["recommended_size"] == "XS"

    def test_her_own_size_is_never_flagged(self, checker):
        result = checker.check_fit("u", body("M"), product("top", "Tops", XS_TO_L), known_size="M")
        assert result["recommended_size"] == "M"
        assert result["closest_available"] is False
        assert not any(note.startswith("Your size is") for note in result["fit_notes"])

    def test_the_closest_size_is_the_best_fitting_one(self, checker):
        """Not merely the nearest label: the stocked size that scores highest."""
        result = checker.check_fit("u", body("XXL"), product("top", "Tops", XS_TO_L), known_size="XXL")
        scores = result["fit_scores"]
        assert scores[result["recommended_size"]] == max(scores.values())

    def test_the_fit_notes_for_that_size_still_follow(self, checker):
        """She is told what to expect of the closest size, not just that it's the closest."""
        result = checker.check_fit("u", body("XXS"), product("top", "Tops", XS_TO_L), known_size="XXS")
        assert any("runs large in the bust" in note for note in result["fit_notes"][1:])

    def test_custom_chart_products_are_left_alone(self, checker):
        """A per-product chart's labels needn't be the standard sizes, so there's no
        'your size' to compare against."""
        custom = product("custom", "Tops", ["S", "M"])
        custom["size_chart"] = {s: dict(STANDARD_SIZE_CHART[s]) for s in ("S", "M")}
        result = checker.check_fit("u", body("XXS"), custom)
        assert result["customer_size"] is None
        assert result["closest_available"] is False

    def test_size_advice_matches_check_fit(self, checker):
        """M5's cards use size_advice; the product page uses check_fit. They must agree."""
        for size in STANDARD_SIZES:
            for sizes in (XS_TO_L, XS_TO_M, STANDARD_SIZES):
                piece = product("piece", "Tops", list(sizes))
                advice = checker.size_advice(body(size), piece, known_size=size)
                checked = checker.check_fit("u", body(size), piece, known_size=size)
                assert advice["recommended_size"] == checked["recommended_size"]
                assert advice["closest_available"] == checked["closest_available"]


class TestClosestStockedSizeTieBreak:
    def test_ties_go_to_the_size_nearer_hers(self, checker):
        assert checker._closest_stocked_size({"S": 0.5, "L": 0.5}, "XL") == "L"
        assert checker._closest_stocked_size({"S": 0.5, "L": 0.5}, "XXS") == "S"


class TestDescribeSizes:
    @pytest.mark.parametrize("sizes, text", [
        (["XS", "S", "M", "L"], "XS–L"),
        (["L", "XS", "M", "S"], "XS–L"),
        (["XS", "S", "L"], "XS, S and L"),
        (["M"], "M only"),
    ])
    def test_reads_naturally(self, checker, sizes, text):
        assert checker._describe_sizes(sizes) == text


class _Measurements:
    def __init__(self, values):
        self.values = values

    def to_dict(self):
        return dict(self.values)


class _Session:
    """Just what M5 reads off a completed session."""

    def __init__(self, size):
        self.body_measurements = _Measurements(body(size))
        self.shape_profile = {
            "shape_class": "balanced",
            "size_recommendation_by_category": {
                "tops": size, "skirts": size, "dresses": size,
                "trousers": size, "vests": size, "coOrds": f"{size}/{size}",
            },
        }


class TestRecommendationCards:
    def _engine(self, products):
        catalog = CatalogKB(products)
        return RecommendationEngine(catalog, _Consented(), FitChecker(consent_tracker=_Consented())), catalog

    def test_cards_outside_her_size_carry_the_closest_size_and_note(self):
        engine, catalog = self._engine([
            product("top-a", "Tops", XS_TO_L), product("top-b", "Tops", XS_TO_L),
        ])
        cards = engine._advise_sizes(_Session("XXS"), catalog.retrieve({"shape_class": "balanced"}))
        assert cards and all(card["closest_available"] for card in cards)
        for card in cards:
            assert card["recommended_size"] == "XS"
            assert card["customer_size"] == "XXS"
            assert card["size_note"] == (
                "Your size is XXS. This piece comes in XS–L, so XS is the closest fit available."
            )

    def test_pieces_in_her_size_come_first_and_carry_no_note(self):
        engine, catalog = self._engine([
            product("narrow", "Tops", XS_TO_L), product("full", "Tops", list(STANDARD_SIZES)),
        ])
        cards = engine._advise_sizes(_Session("XXS"), catalog.retrieve({"shape_class": "balanced"}))
        assert [c["sku"] for c in cards] == ["full", "narrow"]
        assert cards[0]["closest_available"] is False and "size_note" not in cards[0]
        assert cards[0]["recommended_size"] == "XXS"

    def test_catalog_entries_are_not_modified(self):
        engine, catalog = self._engine([product("top-a", "Tops", XS_TO_L)])
        engine._advise_sizes(_Session("XXS"), catalog.retrieve({"shape_class": "balanced"}))
        assert "size_note" not in catalog.get_item("top-a")


class TestRelaxedSizeFilterKeepsHerSizeFirst:
    def test_in_size_piece_survives_the_cut_to_k(self):
        """
        One piece in her size, many outside it: the size filter is relaxed to
        reach the minimum, and the in-size piece must not be cut by k even when
        the others rank above it on shape.
        """
        flattering = [dict(product(f"wrap-{i}", "Dresses", XS_TO_L), name=f"Wrap Dress {i}") for i in range(6)]
        plain = product("plain-top", "Tops", list(STANDARD_SIZES))
        catalog = CatalogKB(flattering + [plain])
        results = catalog.retrieve(
            {"shape_class": "hourglass", "size": "XXS",
             "sizes_by_category": {"Dresses": "XXS", "Tops": "XXS"}, "k": 3}
        )
        assert results[0]["sku"] == "plain-top"
        assert len(results) == 3


class TestNewReleases:
    def test_feed_items_carry_the_closest_size_and_note(self):
        launched = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
        pieces = [dict(product(f"new-{i}", "Tops", XS_TO_L), launched_at=launched) for i in range(3)]
        feed = NewReleasesFeed(catalog=CatalogKB(pieces), consent_tracker=_Consented())
        items = feed.generate_feed(
            "u",
            {"shape_class": "balanced", "size_recommendation_by_category": {"tops": "XXS"}},
            {"preferred_colors": [], "preferred_silhouettes": [], "occasions": []},
            body("XXS"),
        )
        assert items
        for item in items:
            availability = item["availability"]
            assert availability["recommended_size"] == "XS"
            assert availability["closest_available"] is True
            assert availability["size_note"].startswith("Your size is XXS.")
