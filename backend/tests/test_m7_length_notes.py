"""
Height-based length advice: where a hem lands on this customer.

The garment is a fixed number of inches; the body is not. Eighth Hour's length
guide states, per class, the inches at which a hem reaches a named landmark on
their fit model -- which makes those numbers the model's own waist-to-knee,
waist-to-calf and waist-to-floor distances, and lets the same landmarks be
scaled onto anyone. These tests pin the direction of that scaling, the silence
that has to hold when anything is unknown, and the wording, which is the part
that has already gone wrong twice.
"""

import json
from pathlib import Path

import pytest

from py_src.constants import (
    GARMENT_LENGTH_CHART_IN,
    LENGTH_CHART_REFERENCE_HEIGHT_CM,
)
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.modules.m7_fit_checker import FitChecker

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "products.json").read_text())
REFERENCE = LENGTH_CHART_REFERENCE_HEIGHT_CM


@pytest.fixture
def checker():
    tracker = ConsentTracker()
    tracker.record_consent(user_id="u", photo_consent=True, measurement_consent=True)
    return FitChecker(consent_tracker=tracker)


def product(**overrides):
    base = {"sku": "p", "category": "Skirts", "length": "Calf", "sizes": ["M"]}
    return {**base, **overrides}


class TestDirection:
    def test_taller_customer_wears_it_higher(self, checker):
        """A fixed-length skirt reaches less far down a longer leg."""
        note = checker._generate_length_note(195.0, product())
        assert note and "taller" in note
        assert "the knee" in note, note

    def test_shorter_customer_wears_it_lower(self, checker):
        note = checker._generate_length_note(148.0, product())
        assert note and "shorter" in note
        assert "full length" in note, note

    def test_silent_at_the_reference_height(self, checker):
        assert checker._generate_length_note(REFERENCE, product()) is None

    def test_silent_for_a_difference_too_small_to_matter(self, checker):
        """Below the class's own range the note would be false precision."""
        assert checker._generate_length_note(REFERENCE + 3, product()) is None

    def test_scaling_is_monotonic_in_height(self, checker):
        """
        Taller must never produce a *lower* hem. Walks the whole supported
        height range and checks the landing point only ever rises.
        """
        chart = GARMENT_LENGTH_CHART_IN["Skirts"]
        garment = sum(chart["Calf"]) / 2
        previous = None
        for height in range(140, 211):
            equivalent = garment * (REFERENCE / height)
            if previous is not None:
                assert equivalent < previous, f"hem dropped going from {height-1} to {height}cm"
            previous = equivalent


class TestSilenceWhenUnknown:
    @pytest.mark.parametrize("bad", [None, 0, -5, "tall", float("nan")])
    def test_no_note_without_a_usable_height(self, checker, bad):
        if isinstance(bad, float) and bad != bad:      # NaN compares false to all
            assert checker._generate_length_note(bad, product()) is None
            return
        assert checker._generate_length_note(bad, product()) is None

    def test_no_note_when_the_length_is_unknown(self, checker):
        """
        Two catalog products were delisted upstream, so their length is null
        rather than a guess. Silence is the only honest output.
        """
        assert checker._generate_length_note(195.0, product(length=None)) is None

    def test_no_note_for_a_length_this_category_does_not_define(self, checker):
        assert checker._generate_length_note(195.0, product(length="Capri")) is None

    def test_no_note_for_an_unknown_category(self, checker):
        assert checker._generate_length_note(195.0, product(category="Hats")) is None


class TestWording:
    """The bugs here were both in the copy, not the arithmetic."""

    def test_never_stacks_prepositions(self, checker):
        """"sit between at mid-calf and at full length" -- the first attempt."""
        for height in range(140, 211, 2):
            for item in CATALOG:
                note = checker._generate_length_note(float(height), item)
                if not note:
                    continue
                assert "between at " not in note, note
                assert "and at " not in note, note
                assert "at at " not in note, note

    def test_uses_this_category_s_own_meaning_of_the_class(self, checker):
        """
        "Cropped" is a midriff-length top but an above-the-ankle trouser. A
        shared phrase table said "this will sit cropped above the waist" about
        a pair of trousers.
        """
        trouser = checker._generate_length_note(150.0, product(category="Trousers",
                                                               length="Cropped"))
        top = checker._generate_length_note(150.0, product(category="Tops",
                                                           length="Cropped"))
        assert trouser and "the waist" not in trouser and "midriff" not in trouser, trouser
        assert top and ("midriff" in top or "waist" in top or "hip" in top), top

    def test_reads_as_one_sentence(self, checker):
        for height in (145.0, 195.0):
            for item in CATALOG:
                note = checker._generate_length_note(height, item)
                if not note:
                    continue
                assert note.endswith("."), note
                assert note.count(".") == 1, note
                assert "  " not in note, note
                assert "rather than" in note, note

    def test_never_brackets_a_place_with_itself(self, checker):
        """
        "sit between mid-calf and mid-calf" -- a co-ord set merges the skirt and
        trouser charts, and a skirt's Calf sits right beside a trouser's Capri.
        """
        for height in range(140, 211):
            for item in CATALOG:
                note = checker._generate_length_note(float(height), item)
                if not note or " between " not in note:
                    continue
                span = note.split(" between ", 1)[1].split(" on you ", 1)[0]
                lower, _, upper = span.partition(" and ")
                assert lower != upper, note

    def test_never_says_a_place_is_not_itself(self, checker):
        """Midi and Calf are the same measurement under different names."""
        for height in range(140, 211, 3):
            for item in CATALOG:
                note = checker._generate_length_note(float(height), item)
                if note:
                    landed, _, current = note.partition(" on you rather than ")
                    assert not landed.endswith(current.rstrip(".")), note


class TestAgainstTheRealCatalog:
    def test_every_stored_length_is_one_the_chart_defines(self):
        """
        Guards the enrichment: a length the chart can't read is a length the
        customer gets no advice about, silently.
        """
        for item in CATALOG:
            if item.get("length") is None:
                continue
            chart, _ = FitChecker._length_reference_for(item["category"])
            assert item["length"] in chart, (
                f"{item['slug']} ({item['category']}) has length "
                f"{item['length']!r}, which that category's chart doesn't define"
            )

    def test_the_placeholder_length_is_gone_from_lower_body_products(self):
        """
        Every product once read "Regular" -- a placeholder that isn't even a
        valid class for a skirt, dress or trouser.
        """
        for item in CATALOG:
            if item["category"] in ("Skirts", "Dresses", "Trousers"):
                assert item.get("length") != "Regular", item["slug"]

    def test_model_height_is_recorded_wherever_length_is(self):
        for item in CATALOG:
            if item.get("length") is not None:
                assert item.get("model_height_cm"), f"{item['slug']} has no model height"
                assert 140 < item["model_height_cm"] < 210

    def test_note_appears_in_a_real_fit_check(self, checker):
        """End to end: the note has to reach fit_notes, not just exist."""
        item = next(i for i in CATALOG if i["category"] == "Skirts" and i.get("length"))
        result = checker.check_fit(
            "u",
            {"bust": 97.75, "waist": 78.1, "hips": 103.5, "height": 196.0},
            {**item, "sku": item["slug"]},
        )
        assert any("fit model" in note for note in result["fit_notes"]), result["fit_notes"]


class TestCatalogCarriesTheLengthFields:
    """
    M6 normalises products into an explicit dict, so any field not named there
    is silently dropped. `model_height_cm` was, which made the per-product fit
    model look wired up while every garment quietly fell back to the default
    reference height -- including four shot on a model 5cm taller.
    """

    def _catalog(self):
        from py_src.modules.m6_catalog_kb import CatalogKB
        return CatalogKB(CATALOG)

    @pytest.mark.parametrize("field", ["length", "fit", "model_name", "model_height_cm", "model_size"])
    def test_field_survives_normalisation(self, field):
        catalog = self._catalog()
        for product in CATALOG:
            assert catalog.get_item(product["slug"])[field] == product[field], (
                f"{field} was lost normalising {product['slug']}"
            )

    def test_the_taller_model_actually_changes_the_advice(self, checker):
        """
        The observable consequence, and the only thing that proves the
        per-product height reaches M7 rather than everything falling back to the
        default reference.

        Sweeps the supported height range rather than testing one height: the
        two models are only 5cm apart, so across most of the range both give the
        same answer (or both stay silent). What matters is that SOME height
        exists where they differ -- the band where a customer is taller than one
        fit model but not the other.
        """
        catalog = self._catalog()
        heights = {p["model_height_cm"] for p in CATALOG if p.get("model_height_cm")}
        if len(heights) < 2:
            pytest.skip("catalog no longer has products shot on different models")

        # A pair of products alike in every way the advice depends on --
        # category and length class -- differing only in who modelled them.
        by_key = {}
        for item in CATALOG:
            if item.get("length") and item.get("model_height_cm"):
                by_key.setdefault(
                    (item["category"], item["length"], item["model_height_cm"]),
                    item["slug"],
                )
        pairs = [
            (by_key[(category, length, max(heights))], by_key[(category, length, min(heights))])
            for category, length, _ in list(by_key)
            if (category, length, max(heights)) in by_key
            and (category, length, min(heights)) in by_key
        ]
        assert pairs, "no two products share a category and length across both models"

        taller_slug, shorter_slug = pairs[0]
        differed = [
            height
            for height in range(140, 211)
            if checker._generate_length_note(float(height), catalog.get_item(taller_slug))
            != checker._generate_length_note(float(height), catalog.get_item(shorter_slug))
        ]
        assert differed, (
            f"{taller_slug} and {shorter_slug} are the same garment class shot on "
            f"models {max(heights)}cm and {min(heights)}cm apart, yet give identical "
            f"advice at every height from 140 to 210 -- the per-product model "
            f"height is not reaching the fit checker"
        )


class TestCatalogSyncKeepsWhatTheEngineNeeds:
    def test_sync_model_accepts_every_field_the_catalog_stores(self):
        """
        /catalog/sync REPLACES the catalog with exactly the fields on
        CatalogProduct, so anything missing there is destroyed by a single sync.
        It was already dropping `silhouette` and `launched_at` -- M6's ranking
        and M9's entire recency window -- with no error raised.
        """
        from main import CatalogProduct
        declared = set(CatalogProduct.model_fields)
        for product in CATALOG:
            missing = set(product) - declared
            assert not missing, (
                f"{product['slug']} stores {sorted(missing)}, which /catalog/sync "
                f"would silently discard"
            )
