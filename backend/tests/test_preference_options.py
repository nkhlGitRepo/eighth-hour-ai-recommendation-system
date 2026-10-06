"""
The options the style-preference form offers must be ones the engine can act on.

Gym/Active was offered on the form and accepted by the API, but the label makes
no activewear, so no product ever carried that occasion: choosing it could only
make the recommender drop the occasion filter. These tests pin the general rule
rather than the one value -- every occasion on the form must be accepted by M4
and must match at least one product in the real catalog.
"""

import json
import re
from pathlib import Path

import pytest

from py_src.modules.m4_style_preference import PreferenceCapture, StyleProfile
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.utils.errors import ModuleError

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
# The storefront lives in Base_Website/ on main and at the repo root on the
# gh-pages branch, which GitHub Pages serves from.
FORM = next(
    (p for p in (REPO / "Base_Website" / "frontend" / "pages" / "intake-flow.html",
                 REPO / "frontend" / "pages" / "intake-flow.html") if p.exists()),
    None,
)


@pytest.fixture(scope="module")
def form_occasions():
    if FORM is None:
        pytest.skip("intake-flow.html not present in this checkout")
    values = re.findall(r'name="occasion"\s+value="([^"]+)"', FORM.read_text(encoding="utf-8"))
    assert values, "found no occasion checkboxes -- has the markup changed?"
    return values


@pytest.fixture(scope="module")
def catalog_occasions():
    products = json.loads((BACKEND / "products.json").read_text(encoding="utf-8"))
    kb = CatalogKB(products)
    return {occasion for item in kb.items.values() for occasion in item["occasions"]}


def test_every_offered_occasion_is_accepted_by_the_api(form_occasions):
    for occasion in form_occasions:
        assert occasion in StyleProfile.VALID_OCCASIONS, occasion


def test_every_offered_occasion_matches_some_product(form_occasions, catalog_occasions):
    unmatched = [o for o in form_occasions if o not in catalog_occasions]
    assert not unmatched, f"the form offers occasions no product suits: {unmatched}"


def test_gym_is_no_longer_offered_or_accepted(form_occasions):
    assert "gym" not in form_occasions
    assert "gym" not in StyleProfile.VALID_OCCASIONS


class TestRetiredOccasionFromAnOldPage:
    """A page loaded before the change can still submit "gym"."""

    def test_alone_is_dropped_not_rejected(self):
        assert PreferenceCapture()._validate_occasions(["gym"]) == []

    def test_alongside_others_is_dropped(self):
        assert PreferenceCapture()._validate_occasions(["gym", "work"]) == ["work"]

    def test_genuinely_unknown_occasions_are_still_rejected(self):
        with pytest.raises(ModuleError):
            PreferenceCapture()._validate_occasions(["skydiving"])
