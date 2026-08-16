"""
Recommendations must be filtered by the size the customer wears in THAT
category, not by one size for the whole catalog.

The bug this pins was invisible in production and exactly backwards. M5 sent
only the *tops* size and M6 applied it to everything, so a customer who is M on
top and S below had S-only skirts excluded as "not available in your size" and
M-only skirts recommended to her instead. Every product in the live catalog
stocks every size, so the filter had nothing to exclude and nothing ever looked
wrong -- it would have appeared the first time a product sold out of one size.

The fixture therefore has to do what the real catalog doesn't: vary the stock.
"""

import os
import tempfile

import pytest

from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.modules.m1_intake_orchestrator import IntakeOrchestrator
from py_src.modules.m5_recommendation_engine import RecommendationEngine
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.persistence.session_repository import SQLiteSessionRepository
from py_src.constants import STANDARD_SIZE_CHART


def item(slug, category, sizes, silhouette="straight", length="Calf"):
    return {
        "slug": slug, "name": slug, "category": category, "fabric": "Wool",
        "price": 10.0, "colors": ["Ebony"], "sizes": sizes, "description": slug,
        "length": length, "silhouette": silhouette, "launched_at": "2025-01-01",
    }


@pytest.fixture
def divergent_session():
    """
    A body whose bust and hips genuinely disagree: bust at M's centre, hips at
    S's, taken from the chart so it can't go stale. Yields (session, tracker).
    """
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    handle.close()
    orchestrator = IntakeOrchestrator(session_repo=SQLiteSessionRepository(db_path=handle.name))
    tracker = ConsentTracker()
    session = orchestrator.create_session(user_id="divergent")
    orchestrator.record_consent(session.session_id, photo_consent=True, measurement_consent=True)
    tracker.record_consent(user_id=session.user_id, photo_consent=True, measurement_consent=True)
    orchestrator.confirm_measurements(session.session_id, manual_overrides={
        "bust": STANDARD_SIZE_CHART["M"]["bust"],
        "waist": STANDARD_SIZE_CHART["M"]["waist"],
        "hips": STANDARD_SIZE_CHART["S"]["hips"],
        "height": 165,
    })
    session = orchestrator.capture_preferences(
        session.session_id, preferred_colors=[], preferred_silhouettes=[], occasions=[]
    )
    yield session, tracker
    try:
        os.unlink(handle.name)
    except OSError:
        pass


def test_the_body_actually_diverges(divergent_session):
    """Guards the fixture: if top and bottom sizes ever coincide, every other
    test in this file passes for the wrong reason."""
    session, _ = divergent_session
    sizes = session.shape_profile["size_recommendation_by_category"]
    assert sizes["tops"] != sizes["skirts"], sizes


def test_bottoms_are_filtered_by_the_bottom_size(divergent_session):
    session, tracker = divergent_session
    sizes = session.shape_profile["size_recommendation_by_category"]
    top_size, skirt_size = sizes["tops"], sizes["skirts"]

    # Enough stock in her own size that the strict pass already meets
    # MIN_RECOMMENDATIONS. With a two-item catalog M6 correctly relaxes the size
    # filter to fill the page, which would mask the very thing under test.
    catalog = CatalogKB([
        item("skirt-her-size", "Skirts", [skirt_size]),
        item("skirt-her-size-2", "Skirts", [skirt_size]),
        item("skirt-wrong-size", "Skirts", [top_size]),
    ])
    engine = RecommendationEngine(catalog, tracker)
    returned = {r["sku"] for r in engine.generate_recommendations(session, k=20)}

    assert "skirt-her-size" in returned, (
        f"a skirt stocked in {skirt_size}, the size she wears, was excluded"
    )
    assert "skirt-wrong-size" not in returned, (
        f"a skirt stocked only in {top_size} -- her TOP size -- was recommended"
    )


def test_tops_are_still_filtered_by_the_top_size(divergent_session):
    session, tracker = divergent_session
    sizes = session.shape_profile["size_recommendation_by_category"]
    top_size, skirt_size = sizes["tops"], sizes["skirts"]

    catalog = CatalogKB([
        item("top-her-size", "Tops", [top_size], silhouette="fitted", length="Short"),
        item("top-her-size-2", "Tops", [top_size], silhouette="fitted", length="Short"),
        item("top-wrong-size", "Tops", [skirt_size], silhouette="fitted", length="Short"),
    ])
    engine = RecommendationEngine(catalog, tracker)
    returned = {r["sku"] for r in engine.generate_recommendations(session, k=20)}
    assert "top-her-size" in returned
    assert "top-wrong-size" not in returned


def test_every_recommendation_is_stocked_in_the_size_shown_for_it(divergent_session):
    """
    The property that matters, over a catalog where each product stocks exactly
    one size: nothing may be recommended that she cannot buy.
    """
    session, tracker = divergent_session
    sizes = session.shape_profile["size_recommendation_by_category"]
    from py_src.constants import CATEGORY_TO_SIZE_PROFILE_KEY, STANDARD_SIZES

    products = [
        item(f"{category}-{size}", category, [size],
             silhouette="fitted" if category in ("Tops", "Vests") else "straight",
             length="Short" if category in ("Tops", "Vests") else "Calf")
        for category in CATEGORY_TO_SIZE_PROFILE_KEY
        for size in STANDARD_SIZES
    ]
    engine = RecommendationEngine(CatalogKB(products), tracker)
    recommendations = engine.generate_recommendations(session, k=100)
    assert recommendations

    for recommendation in recommendations:
        expected = sizes[CATEGORY_TO_SIZE_PROFILE_KEY[recommendation["category"]]]
        assert expected in recommendation["sizes"], (
            f"{recommendation['sku']} ({recommendation['category']}) was recommended "
            f"but isn't stocked in {expected}, the size her profile shows for it"
        )


def test_a_single_size_query_still_works(divergent_session):
    """
    Back-compatibility: callers that pass only `size` (and categories the
    profile has no entry for) must behave exactly as before.
    """
    session, tracker = divergent_session
    catalog = CatalogKB([
        item("m-only", "Skirts", ["M"]),
        item("m-only-2", "Skirts", ["M"]),
        item("s-only", "Skirts", ["S"]),
    ])
    # min_results=0 turns relaxation off, so this asserts the strict filter
    # itself rather than whatever relaxation happens to fall back to.
    results = catalog.retrieve(
        {"shape_class": "balanced", "size": "M", "k": 10}, min_results=0
    )
    assert {r["sku"] for r in results} == {"m-only", "m-only-2"}


def test_unknown_category_is_not_excluded(divergent_session):
    """A category the profile has no size for must not be silently dropped."""
    session, tracker = divergent_session
    catalog = CatalogKB([item("mystery", "Scarves", ["XXS"])])
    results = catalog.retrieve({
        "shape_class": "balanced",
        "sizes_by_category": {"Skirts": "S"},
        "k": 10,
    }, min_results=0)
    assert {r["sku"] for r in results} == {"mystery"}


class TestColourCanonicalisation:
    """
    M6 filters products with an exact string comparison against the catalog's
    spelling ("Ebony", "Sky Captain"), so a stored "ebony" matches nothing --
    the colour filter then excludes everything, M6 relaxes it away, and the
    customer's colour choice silently stops affecting her recommendations with
    no error anywhere. M4 is the one layer that decides the spelling.
    """

    def _capture(self, colors):
        from py_src.modules.m4_style_preference import PreferenceCapture
        catalog = CatalogKB([
            item("a", "Skirts", ["M"]), item("b", "Tops", ["M"], "fitted", "Short"),
        ])
        catalog.items["a"]["colors"] = ["Ebony"]
        return PreferenceCapture(catalog=catalog)._validate_colors(colors)

    def test_accepts_any_casing_and_stores_the_catalog_spelling(self):
        for spelling in ("Ebony", "ebony", "EBONY", "eBoNy"):
            assert self._capture([spelling]) == ["Ebony"], spelling

    def test_generic_buckets_keep_their_own_lowercase_spelling(self):
        """They are lowercase by definition; title-casing them matched nothing."""
        assert self._capture(["black", "Black", "BLACK"]) == ["black"]

    def test_still_rejects_a_colour_that_is_not_a_colour(self):
        from py_src.utils.errors import ModuleError
        with pytest.raises(ModuleError, match="No valid colors"):
            self._capture(["chartreuse", "banana"])

    def test_duplicates_collapse(self):
        assert self._capture(["Ebony", "ebony", "EBONY"]) == ["Ebony"]

    def test_non_strings_are_ignored_not_crashed_on(self):
        assert self._capture(["Ebony", None, 42, ["nested"]]) == ["Ebony"]
