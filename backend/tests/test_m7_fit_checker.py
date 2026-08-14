"""Comprehensive tests for M7 — Fit Checker."""

import pytest
from unittest.mock import MagicMock, patch
from py_src.constants import STANDARD_SIZE_CHART, SIZE_STEP_CM
from py_src.modules.m7_fit_checker import FitChecker
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.utils.errors import ModuleError, GuardrailError


@pytest.fixture
def consent_tracker():
    """Consent tracker with measurement consent granted."""
    tracker = ConsentTracker()
    tracker.record_consent(user_id="test_user", photo_consent=True, measurement_consent=True)
    return tracker


@pytest.fixture
def fit_checker(consent_tracker):
    """Fit checker instance."""
    return FitChecker(consent_tracker=consent_tracker)


@pytest.fixture
def test_product():
    """Test product with standard sizing."""
    return {
        "sku": "top-123",
        "name": "Test Top",
        "sizes": ["XS", "S", "M", "L", "XL"],
        "category": "Tops",
    }


@pytest.fixture
def test_measurements():
    """Standard test measurements (size M)."""
    return {
        "bust": 90.0,
        "waist": 72.0,
        "hips": 97.0,
        "height": 165.0,
    }


class TestM7FitValidation:
    """Test input validation."""

    def test_rejects_missing_measurements(self, fit_checker, test_product):
        """Missing measurement field should raise error."""
        measurements = {"bust": 90.0, "waist": 72.0}  # Missing hips, height
        with pytest.raises(ModuleError, match="Missing required measurements"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_negative_measurements(self, fit_checker, test_product):
        """Negative measurement should raise error."""
        measurements = {
            "bust": 90.0,
            "waist": -72.0,  # Invalid
            "hips": 97.0,
            "height": 165.0,
        }
        with pytest.raises(ModuleError, match="must be positive"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_zero_measurements(self, fit_checker, test_product):
        """Zero measurement should raise error."""
        measurements = {
            "bust": 0.0,  # Invalid
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        with pytest.raises(ModuleError, match="must be positive"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_height_below_range(self, fit_checker, test_product):
        """Height below 140cm should raise error."""
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 139.0,  # Too short
        }
        with pytest.raises(ModuleError, match="height"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_height_above_range(self, fit_checker, test_product):
        """Height above 210cm should raise error."""
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 211.0,  # Too tall
        }
        with pytest.raises(ModuleError, match="height"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_accepts_height_at_exact_boundaries(self, fit_checker, test_product):
        """Height at exact boundaries (140, 210) should be accepted."""
        for height in [140.0, 210.0]:
            measurements = {
                "bust": 90.0,
                "waist": 72.0,
                "hips": 97.0,
                "height": height,
            }
            result = fit_checker.check_fit("test_user", measurements, test_product)
            assert result is not None
            assert result["recommended_size"] in test_product["sizes"]

    def test_accepts_measurement_at_exact_min_boundaries(self, fit_checker, test_product):
        """Measurements at exact minimum boundaries should be accepted."""
        measurements = {
            "bust": 70.0,    # Exact minimum
            "waist": 55.0,
            "hips": 80.0,
            "height": 140.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)
        assert result is not None
        assert result["recommended_size"] in test_product["sizes"]

    def test_accepts_measurement_at_exact_max_boundaries(self, fit_checker, test_product):
        """Measurements at exact maximum boundaries should be accepted."""
        measurements = {
            "bust": 150.0,   # Exact maximum
            "waist": 130.0,
            "hips": 160.0,
            "height": 210.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)
        assert result is not None
        assert result["recommended_size"] in test_product["sizes"]

    def test_rejects_bust_below_range(self, fit_checker, test_product):
        """Bust below 70cm should raise error."""
        measurements = {
            "bust": 69.0,  # Too small
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        with pytest.raises(ModuleError, match="bust"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_bust_above_range(self, fit_checker, test_product):
        """Bust above 150cm should raise error."""
        measurements = {
            "bust": 151.0,  # Too large
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        with pytest.raises(ModuleError, match="bust"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_missing_product_fields(self, fit_checker):
        """Product missing sku or sizes should raise error."""
        incomplete_product = {"name": "Test", "category": "Tops"}
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        with pytest.raises(ModuleError, match="required fields"):
            fit_checker.check_fit("test_user", measurements, incomplete_product)

    def test_rejects_empty_product_sizes(self, fit_checker):
        """Product with empty sizes list should raise error."""
        bad_product = {"sku": "bad-123", "sizes": []}
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        with pytest.raises(ModuleError, match="non-empty sizes"):
            fit_checker.check_fit("test_user", measurements, bad_product)

    def test_rejects_non_list_sizes(self, fit_checker):
        """Product with sizes as string instead of list should raise error."""
        bad_product = {"sku": "bad-123", "sizes": "M"}
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        with pytest.raises(ModuleError, match="non-empty sizes"):
            fit_checker.check_fit("test_user", measurements, bad_product)


class TestM7ConsentEnforcement:
    """Test consent verification."""

    def test_rejects_without_measurement_consent(self, fit_checker, test_product, test_measurements):
        """Should reject if user hasn't consented to measurement processing."""
        tracker = ConsentTracker()
        tracker.record_consent(user_id="no_consent_user", photo_consent=True, measurement_consent=False)
        checker = FitChecker(consent_tracker=tracker)

        with pytest.raises(GuardrailError, match="consented"):
            checker.check_fit("no_consent_user", test_measurements, test_product)

    def test_rejects_unrecorded_user(self, fit_checker, test_product, test_measurements):
        """Should reject user with no consent record at all."""
        unrecorded_tracker = ConsentTracker()
        checker = FitChecker(consent_tracker=unrecorded_tracker)

        with pytest.raises(GuardrailError, match="consented"):
            checker.check_fit("never_recorded_user", test_measurements, test_product)


class TestM7AlgorithmAccuracy:
    """Test fit score calculation correctness."""

    def test_perfect_fit_scores_exactly_1(self, fit_checker, test_product):
        """Measurements exactly matching size M should score 1.0."""
        # Taken from the chart rather than transcribed -- these numbers moved
        # when the uniform-grid tables were replaced with the published chart,
        # and a hardcoded copy silently stopped being "exactly M".
        measurements = {**STANDARD_SIZE_CHART["M"], "height": 165.0}
        result = fit_checker.check_fit("test_user", measurements, test_product)

        m_score = result["fit_scores"]["M"]
        # Perfect match: all deltas = 0, all confidences = 1.0, average = 1.0
        assert m_score == 1.0, f"Perfect fit should score 1.0, got {m_score}"
        assert result["recommended_size"] == "M"

    def test_recommended_size_always_has_highest_score(self, fit_checker, test_product):
        """Recommended size must have the highest fit_score."""
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)

        rec_score = result["fit_scores"][result["recommended_size"]]
        for size, score in result["fit_scores"].items():
            assert score <= rec_score, f"Size {size} scored {score} > recommended {result['recommended_size']} ({rec_score})"

    def test_confidence_equals_recommended_size_score(self, fit_checker, test_product):
        """Confidence must equal the recommended size's fit_score."""
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)

        rec_score = result["fit_scores"][result["recommended_size"]]
        assert result["confidence"] == rec_score, f"Confidence {result['confidence']} != score {rec_score}"

    def test_smaller_user_recommends_smaller_size(self, fit_checker, test_product):
        """User with smaller measurements should recommend smaller sizes with higher scores."""
        small_measurements = {
            "bust": 80.0,  # Smaller than S (84)
            "waist": 60.0,
            "hips": 85.0,
            "height": 160.0,
        }
        result = fit_checker.check_fit("test_user", small_measurements, test_product)

        # XS and S should score higher than M, L, XL
        xs_score = result["fit_scores"]["XS"]
        s_score = result["fit_scores"]["S"]
        m_score = result["fit_scores"]["M"]
        assert xs_score > m_score, f"XS {xs_score} should score higher than M {m_score}"
        assert s_score > m_score, f"S {s_score} should score higher than M {m_score}"
        # Recommendation should be XS or S
        assert result["recommended_size"] in ["XS", "S"]

    def test_larger_user_recommends_larger_size(self, fit_checker, test_product):
        """User with larger measurements should recommend larger sizes with higher scores."""
        large_measurements = {
            "bust": 105.0,  # Larger than L (96)
            "waist": 82.0,
            "hips": 110.0,
            "height": 175.0,
        }
        result = fit_checker.check_fit("test_user", large_measurements, test_product)

        # XL should score higher than M (both available in test_product)
        xl_score = result["fit_scores"]["XL"]
        m_score = result["fit_scores"]["M"]
        assert xl_score > m_score, f"XL {xl_score} should score higher than M {m_score}"
        # Recommendation must be from available sizes
        assert result["recommended_size"] in test_product["sizes"]
        # And should be one of the larger sizes
        assert result["recommended_size"] in ["L", "XL"]

    def test_all_sizes_scored_correctly(self, fit_checker, test_product):
        """All available sizes should have fit scores between 0 and 1."""
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)

        for size in test_product["sizes"]:
            assert size in result["fit_scores"], f"Size {size} missing from fit_scores"
            score = result["fit_scores"][size]
            assert 0 <= score <= 1, f"Score for {size} is {score}, must be 0-1"

    def test_fit_check_is_idempotent(self, fit_checker, test_product, test_measurements):
        """Same input should always produce same output."""
        result1 = fit_checker.check_fit("test_user", test_measurements, test_product)
        result2 = fit_checker.check_fit("test_user", test_measurements, test_product)

        assert result1 == result2, "Results should be identical for same input"


class TestM7FitNotes:
    """Test fit guidance note generation."""

    def test_perfect_fit_generates_perfect_note(self, fit_checker, test_product):
        """Perfect fit should generate specific 'fits perfectly' note."""
        measurements = {**STANDARD_SIZE_CHART["M"], "height": 165.0}
        result = fit_checker.check_fit("test_user", measurements, test_product)

        notes_text = " ".join(result["fit_notes"]).lower()
        assert "fits perfectly" in notes_text, "Perfect fit should mention 'fits perfectly'"

    def test_loose_bust_generates_specific_note(self, fit_checker, test_product):
        """Loose bust should generate specific note about bust, not other measurements."""
        # A full size step below what M is cut for, with waist and hips left at
        # M exactly, so the bust is unambiguously the dimension that misfits.
        measurements = {
            **STANDARD_SIZE_CHART["M"],
            "bust": STANDARD_SIZE_CHART["M"]["bust"] - SIZE_STEP_CM["bust"],
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)

        # Verify note exists and mentions the specific issue
        notes_text = " ".join(result["fit_notes"]).lower()
        # Should mention bust specifically OR loose/large in context of fit
        found_bust_note = "bust" in notes_text and ("large" in notes_text or "loose" in notes_text)
        assert found_bust_note, \
            f"Should have specific note about loose bust. Notes: {result['fit_notes']}"

    def test_snug_waist_generates_specific_note(self, fit_checker, test_product):
        """
        Snug waist should generate specific note about waist, not other
        measurements. Uses a category outside FIT_SCORE_DIMENSION_WEIGHTS
        (falls back to FIT_SCORE_DEFAULT_WEIGHTS, which weights waist)
        rather than test_product's "Tops" category -- Tops are sized by
        bust alone, so a waist note there would now be correctly
        suppressed as irrelevant to how the size was actually chosen.
        """
        waist_driven_product = {**test_product, "category": "Test Waist-Driven Category"}
        measurements = {
            "bust": 96.0,    # Exact match to M
            "waist": 85.0,   # Larger than size M (81), will be snug
            "hips": 98.0,    # Exact match to M
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, waist_driven_product)

        # Verify note exists and mentions the specific issue
        notes_text = " ".join(result["fit_notes"]).lower()
        # Should mention waist AND snug/small
        found_waist_note = "waist" in notes_text and ("snug" in notes_text or "small" in notes_text)
        assert found_waist_note, \
            f"Should have specific note about snug waist. Notes: {result['fit_notes']}"

    def test_skirt_bust_mismatch_generates_no_bust_note(self, fit_checker):
        """
        Regression coverage: a Skirt is sized by hips alone (see
        FIT_SCORE_DIMENSION_WEIGHTS), so an off bust measurement never
        drove the size choice and must not generate a "runs small/large in
        the bust" note -- that would be actively misleading, not just
        irrelevant, for a garment bust has no bearing on.
        """
        skirt = {
            "sku": "skirt-123",
            "name": "Test Skirt",
            "sizes": ["XS", "S", "M", "L", "XL"],
            "category": "Skirts",
        }
        measurements = {
            "bust": 130.0,   # wildly off -- would trigger a bust note if bust were checked
            "waist": 72.0,
            "hips": 97.0,    # exact match to M
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, skirt)

        notes_text = " ".join(result["fit_notes"]).lower()
        assert "bust" not in notes_text, f"Skirt fit notes must never mention bust. Notes: {result['fit_notes']}"

    def test_vest_hips_mismatch_generates_no_hips_note(self, fit_checker):
        """
        Regression coverage: a Vest is sized by bust alone (see
        FIT_SCORE_DIMENSION_WEIGHTS), so an off hips measurement must not
        generate a "loose/snug in the hips" note.
        """
        vest = {
            "sku": "vest-123",
            "name": "Test Vest",
            "sizes": ["XS", "S", "M", "L", "XL"],
            "category": "Vests",
        }
        measurements = {
            "bust": 90.0,    # exact match to M
            "waist": 72.0,
            "hips": 130.0,   # wildly off -- would trigger a hips note if hips were checked
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, vest)

        notes_text = " ".join(result["fit_notes"]).lower()
        assert "hips" not in notes_text, f"Vest fit notes must never mention hips. Notes: {result['fit_notes']}"

    def test_trousers_bust_mismatch_generates_no_bust_note(self, fit_checker):
        """Trousers are lower-body-only -- an off bust measurement must not generate a bust note."""
        trousers = {
            "sku": "trousers-123",
            "name": "Test Trousers",
            "sizes": ["XS", "S", "M", "L", "XL"],
            "category": "Trousers",
        }
        measurements = {
            "bust": 130.0,   # wildly off -- would trigger a bust note if bust were checked
            "waist": 72.0,
            "hips": 97.0,    # exact match to M
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, trousers)

        notes_text = " ".join(result["fit_notes"]).lower()
        assert "bust" not in notes_text, f"Trousers fit notes must never mention bust. Notes: {result['fit_notes']}"

    def test_dress_can_show_waist_and_hips_notes_alongside_bust(self, fit_checker):
        """
        A Dress is whole-body: even though its recommended size is chosen
        from bust alone (FIT_SCORE_DIMENSION_WEIGHTS), a real waist/hips
        mismatch is still useful guidance and must be allowed to appear --
        unlike Tops/Vests, which only cover the upper body.
        """
        dress = {
            "sku": "dress-123",
            "name": "Test Dress",
            "sizes": ["XS", "S", "M", "L", "XL"],
            "category": "Dresses",
        }
        measurements = {
            "bust": 90.0,    # exact match to M -- drives the M recommendation
            "waist": 85.0,   # larger than M (81) -- snug
            "hips": 110.0,   # larger than M (97) -- snug
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, dress)

        notes_text = " ".join(result["fit_notes"]).lower()
        assert "waist" in notes_text, f"Dress fit notes should mention waist. Notes: {result['fit_notes']}"
        assert "hips" in notes_text, f"Dress fit notes should mention hips. Notes: {result['fit_notes']}"

    def test_coord_set_can_show_waist_and_hips_notes_alongside_bust(self, fit_checker):
        """Co-ord Sets get the same whole-body note treatment as Dresses."""
        coord_set = {
            "sku": "coord-123",
            "name": "Test Co-ord Set",
            "sizes": ["XS", "S", "M", "L", "XL"],
            "category": "Co-ord Sets",
        }
        measurements = {
            "bust": 90.0,    # exact match to M -- drives the M recommendation
            "waist": 85.0,   # larger than M (81) -- snug
            "hips": 110.0,   # larger than M (97) -- snug
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, coord_set)

        notes_text = " ".join(result["fit_notes"]).lower()
        assert "waist" in notes_text, f"Co-ord Set fit notes should mention waist. Notes: {result['fit_notes']}"
        assert "hips" in notes_text, f"Co-ord Set fit notes should mention hips. Notes: {result['fit_notes']}"

    def test_all_notes_are_non_empty_strings(self, fit_checker, test_product, test_measurements):
        """All fit notes should be non-empty strings."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        assert len(result["fit_notes"]) > 0, "Should generate at least one note"
        for note in result["fit_notes"]:
            assert isinstance(note, str), "Each note must be a string"
            assert len(note) > 0, "Each note must be non-empty"


class TestM7ResponseFormat:
    """Test response structure and correctness."""

    def test_response_has_all_required_fields(self, fit_checker, test_product, test_measurements):
        """Response must have all required fields."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        required_fields = {"product_sku", "fit_scores", "recommended_size", "fit_notes", "confidence"}
        assert required_fields.issubset(result.keys()), f"Missing fields: {required_fields - set(result.keys())}"

    def test_fit_scores_covers_all_product_sizes(self, fit_checker, test_product, test_measurements):
        """fit_scores must have an entry for every product size."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        assert set(result["fit_scores"].keys()) == set(test_product["sizes"]), \
            "fit_scores must cover exactly the product's sizes"

    def test_fit_scores_values_are_valid(self, fit_checker, test_product, test_measurements):
        """fit_scores values must be floats between 0 and 1."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        for size, score in result["fit_scores"].items():
            assert isinstance(score, float), f"Score for {size} must be float, got {type(score)}"
            assert 0 <= score <= 1, f"Score for {size} is {score}, must be 0-1"

    def test_recommended_size_is_valid(self, fit_checker, test_product, test_measurements):
        """Recommended size must be one of the product's available sizes."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        assert result["recommended_size"] in test_product["sizes"], \
            f"Recommended size {result['recommended_size']} not in {test_product['sizes']}"

    def test_confidence_is_rounded_to_2_decimals(self, fit_checker, test_product):
        """Confidence should be rounded to 2 decimal places."""
        measurements = {"bust": 90.0, "waist": 72.0, "hips": 97.0, "height": 165.0}
        result = fit_checker.check_fit("test_user", measurements, test_product)

        # Check it's a float with max 2 decimal places
        assert isinstance(result["confidence"], float)
        # Multiply by 100 to check decimal places
        assert result["confidence"] == round(result["confidence"], 2), \
            "Confidence should be rounded to 2 decimal places"


class TestM7CustomSizeChart:
    """Test handling of custom product size charts."""

    def test_uses_product_custom_chart_over_standard(self, fit_checker):
        """Should use product's custom size chart when provided."""
        custom_chart = {
            "S": {"bust": 82, "waist": 64, "hips": 89},
            "M": {"bust": 88, "waist": 70, "hips": 95},
            "L": {"bust": 94, "waist": 76, "hips": 101},
        }
        product_with_chart = {
            "sku": "custom-top",
            "sizes": ["S", "M", "L"],
            "size_chart": custom_chart,
        }
        measurements = {
            "bust": 88.0,
            "waist": 70.0,
            "hips": 95.0,
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, product_with_chart)

        # Should recommend M (perfect match with custom chart)
        assert result["recommended_size"] == "M"
        assert result["confidence"] == 1.0, "Perfect match should have confidence 1.0"

    def test_custom_chart_produces_different_results_than_standard(self, fit_checker):
        """Custom chart should produce different scores than standard chart."""
        custom_chart = {
            "XS": {"bust": 70, "waist": 55, "hips": 80},
            "S": {"bust": 76, "waist": 61, "hips": 86},
            "M": {"bust": 82, "waist": 67, "hips": 92},
        }
        product_custom = {
            "sku": "custom",
            "sizes": ["XS", "S", "M"],
            "size_chart": custom_chart,
        }
        product_standard = {
            "sku": "standard",
            "sizes": ["XS", "S", "M"],
            # No size_chart, will use standard
        }
        measurements = {"bust": 80, "waist": 68, "hips": 93, "height": 165}

        result_custom = fit_checker.check_fit("test_user", measurements, product_custom)
        result_standard = fit_checker.check_fit("test_user", measurements, product_standard)

        # Results should differ
        assert result_custom["fit_scores"] != result_standard["fit_scores"], \
            "Custom and standard charts should produce different scores"

    def test_missing_size_in_custom_chart_gets_default_score(self, fit_checker):
        """Size not in custom chart should get default score of 0.5."""
        sparse_chart = {
            "M": {"bust": 88, "waist": 70, "hips": 95},
        }
        product = {
            "sku": "sparse",
            "sizes": ["S", "M", "L"],
            "size_chart": sparse_chart,
        }
        measurements = {"bust": 88, "waist": 70, "hips": 95, "height": 165}

        result = fit_checker.check_fit("test_user", measurements, product)

        # S and L not in chart, should be 0.5
        assert result["fit_scores"]["S"] == 0.5, "Missing size should get default 0.5"
        assert result["fit_scores"]["L"] == 0.5, "Missing size should get default 0.5"
        # M in chart, should be 1.0 (perfect match)
        assert result["fit_scores"]["M"] == 1.0

    def test_known_size_is_ignored_for_custom_charts(self, fit_checker):
        """
        known_size (M3's boundary classification) is only guaranteed
        consistent under boundary-aware scoring, which only applies to the
        STANDARD chart -- a custom chart has no relationship to those
        boundaries. Blindly trusting known_size for a custom chart would
        reintroduce the exact "recommended size scores lower than another"
        bug this whole model exists to prevent, just via a different path.
        known_size must be ignored (falling back to this chart's own
        argmax) whenever a custom chart is in play.
        """
        custom_chart = {
            "S": {"bust": 85, "waist": 70, "hips": 90},
            "M": {"bust": 95, "waist": 78, "hips": 96},
            "L": {"bust": 130, "waist": 110, "hips": 130},
        }
        product = {
            "sku": "custom-chart-vest", "category": "Vests",
            "sizes": ["S", "M", "L"], "size_chart": custom_chart,
        }
        # bust=110 -> M3's own boundary classification would say a much
        # larger size, but this custom chart's own numbers say M fits best.
        measurements = {"bust": 110.0, "waist": 90.0, "hips": 95.0, "height": 165.0}

        result = fit_checker.check_fit("test_user", measurements, product, known_size="L")

        assert result["recommended_size"] == "M"
        assert result["fit_scores"][result["recommended_size"]] == max(result["fit_scores"].values())


class TestM7AuditLogging:
    """Test audit trail generation."""

    def test_audit_log_is_created(self, fit_checker, test_product, test_measurements):
        """Fit check should create an audit log entry."""
        with patch.object(AuditLogger, "log_event") as mock_log:
            result = fit_checker.check_fit(
                "test_user",
                test_measurements,
                test_product,
                session_id="sess-123"
            )

            # Verify log_event was called
            mock_log.assert_called_once()
            call_args = mock_log.call_args

            # Verify arguments
            assert call_args[0][0] == "FIT_CHECK_COMPLETED", "Event type must be FIT_CHECK_COMPLETED"
            assert call_args[0][1] == "test_user", "User ID must be logged"

            # Verify context contains required fields
            context = call_args[0][2]
            assert context["product_sku"] == test_product["sku"]
            assert context["recommended_size"] == result["recommended_size"]
            assert context["confidence"] == result["confidence"]
            assert context["session_id"] == "sess-123"

    def test_audit_log_without_session_id(self, fit_checker, test_product, test_measurements):
        """Audit log should work without session_id."""
        with patch.object(AuditLogger, "log_event") as mock_log:
            fit_checker.check_fit("test_user", test_measurements, test_product)

            mock_log.assert_called_once()
            context = mock_log.call_args[0][2]
            assert "product_sku" in context
            assert "recommended_size" in context


class TestM7Integration:
    """Test M7 integration with other modules (M8 history)."""

    def test_fit_result_compatible_with_m8_history(self, fit_checker, test_product, test_measurements):
        """M7 fit result should be compatible with M8's save_fit_check() format."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        # Verify all fields that M8 expects are present and correctly formatted
        required_fields = {"product_sku", "fit_scores", "recommended_size", "confidence"}
        assert required_fields.issubset(set(result.keys())), \
            f"Missing fields for M8: {required_fields - set(result.keys())}"

        # Verify field types match what M8 expects
        assert isinstance(result["product_sku"], str), "product_sku must be string"
        assert isinstance(result["fit_scores"], dict), "fit_scores must be dict"
        assert isinstance(result["recommended_size"], str), "recommended_size must be string"
        assert isinstance(result["confidence"], float), "confidence must be float"
        assert isinstance(result["fit_notes"], list), "fit_notes must be list"

        # Verify all fit_scores are floats 0-1
        for size, score in result["fit_scores"].items():
            assert isinstance(score, float), f"fit_score for {size} must be float"
            assert 0 <= score <= 1, f"fit_score for {size} must be 0-1"

        # Verify confidence matches recommended size's score
        assert result["confidence"] == result["fit_scores"][result["recommended_size"]], \
            "Confidence must equal recommended size's fit_score"


class TestM7AgreesWithM3Sizing:
    """
    Regression coverage: the size M3 shows the customer on their Shape
    Profile (size_recommendation_by_category) must always agree with the
    size M7's fit checker recommends for the same body -- otherwise a
    customer sees e.g. "L" on their profile but "XL" pre-selected when they
    click into a product. This previously broke because STANDARD_SIZE_CHART
    (M7) used arbitrary reference points that didn't align with
    SIZE_BOUNDARIES/WAIST_SIZE_BOUNDARIES/HIP_SIZE_BOUNDARIES (M3) -- see
    constants.py, where STANDARD_SIZE_CHART is now derived from those same
    boundaries so they can't drift apart again.
    """

    def test_size_chart_center_measurements_agree_across_all_sizes(self, fit_checker):
        from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
        from py_src.constants import STANDARD_SIZE_CHART, STANDARD_SIZES

        profiler = BodyShapeProfiler()
        product = {"sku": "agreement-check", "sizes": STANDARD_SIZES}

        for size in STANDARD_SIZES:
            chart_entry = STANDARD_SIZE_CHART[size]
            measurements = {**chart_entry, "height": 165.0}

            profile = profiler.profile(measurements)
            m3_top_size = profile["size_recommendation_by_category"]["tops"]
            m3_bottom_size = profile["size_recommendation_by_category"]["skirts"]

            fit_result = fit_checker.check_fit("test_user", measurements, product)
            m7_size = fit_result["recommended_size"]

            assert m3_top_size == size, (
                f"M3 should classify its own {size} chart center as {size} for tops, got {m3_top_size}"
            )
            assert m3_bottom_size == size, (
                f"M3 should classify its own {size} chart center as {size} for skirts, got {m3_bottom_size}"
            )
            assert m7_size == size, (
                f"M7 should recommend {size} for measurements at the {size} chart center, got {m7_size}"
            )

    def test_known_size_overrides_blended_argmax_when_they_disagree(self, fit_checker, test_product):
        """
        A body whose bust and hips point at different sizes (e.g. a pear
        shape) is exactly the case where blending bust+waist+hips equally
        (fit_scores) can legitimately pick a different size than M3's
        single-measurement, category-specific answer (hips alone, for a
        Skirts/Trousers category) -- this is the real bug the user hit:
        Shape Profile said "S" for skirts, but the fit-checker's blended
        average argmax'd to "M". known_size must win.
        """
        measurements = {"bust": 96.0, "waist": 84.0, "hips": 92.0, "height": 165.0}

        unblended = fit_checker.check_fit("test_user", measurements, test_product)
        assert unblended["recommended_size"] == "M", (
            "Sanity check: blended argmax should pick M for this body "
            f"(got {unblended['recommended_size']}) -- otherwise this test isn't "
            "exercising the disagreement it's meant to cover"
        )

        result = fit_checker.check_fit(
            "test_user", measurements, test_product, known_size="S"
        )
        assert result["recommended_size"] == "S"
        assert result["confidence"] == result["fit_scores"]["S"]

    def test_known_size_ignored_when_not_a_stocked_size(self, fit_checker, test_product):
        """A category size M3 computed is meaningless if this specific
        product doesn't even carry that size -- fall back to the blended
        argmax rather than recommending an unavailable size."""
        measurements = {"bust": 96.0, "waist": 84.0, "hips": 92.0, "height": 165.0}

        result = fit_checker.check_fit(
            "test_user", measurements, test_product, known_size="XXL"
        )
        assert result["recommended_size"] != "XXL"
        assert result["recommended_size"] == max(
            result["fit_scores"].items(), key=lambda x: x[1]
        )[0]

    def test_known_size_alternative_note_never_repeats_recommended_size(self, fit_checker, test_product):
        """
        When known_size overrides the blended argmax, recommended_size may
        no longer be fit_scores' own top entry -- the "alternative size"
        note must still pick the best OTHER size, not redundantly re-list
        recommended_size as an "alternative" to itself.
        """
        measurements = {"bust": 96.0, "waist": 84.0, "hips": 92.0, "height": 165.0}

        result = fit_checker.check_fit(
            "test_user", measurements, test_product, known_size="S"
        )
        assert result["recommended_size"] == "S"
        for note in result["fit_notes"]:
            assert "Size S is also a good option" not in note, (
                f"Alternative note should never re-list the recommended size itself: {note}"
            )

    def test_alternative_note_never_outranks_the_recommendation(self, fit_checker, test_product):
        """
        Regression coverage: a body whose bust is far larger than its hips
        (bust=111, waist=90, hips=85) gets recommended XS via a hips-based
        known_size (e.g. for a Skirts/Trousers category), but the blended
        bust+waist+hips fit_scores favor L/XL much more strongly. The
        alternative-size note must never surface one of those higher-scoring
        sizes -- "recommended: XS (77%)" alongside "alternative: L (91%)" is
        self-contradictory and erodes trust in the primary recommendation.
        """
        measurements = {"bust": 111.0, "waist": 90.0, "hips": 85.0, "height": 180.0}

        result = fit_checker.check_fit(
            "test_user", measurements, test_product, known_size="XS"
        )
        assert result["recommended_size"] == "XS"
        rec_score = result["fit_scores"]["XS"]
        assert rec_score < result["fit_scores"]["L"], (
            "Sanity check: L should genuinely outscore XS on the blended "
            "metric, otherwise this test isn't exercising the disagreement "
            "it's meant to cover"
        )

        notes_text = " ".join(result["fit_notes"])
        for size, score in result["fit_scores"].items():
            if size == "XS" or score <= rec_score:
                continue
            assert f"Size {size} is also a good option" not in notes_text, (
                f"Size {size} ({score}) should not be suggested as an alternative to "
                f"XS ({rec_score}) since it scores higher"
            )

    def test_known_size_none_preserves_default_behavior(self, fit_checker, test_measurements, test_product):
        """Omitting known_size (the default) must behave exactly as before."""
        with_default = fit_checker.check_fit("test_user", test_measurements, test_product)
        explicit_none = fit_checker.check_fit(
            "test_user", test_measurements, test_product, known_size=None
        )
        assert with_default["recommended_size"] == explicit_none["recommended_size"]


class TestM7ScoringFormulaMakesRationalSense:
    """
    Regression coverage for the scoring formula itself, not just the
    alternative-size note built on top of it.

    The old formula divided each dimension's cm delta by the CANDIDATE
    size's own reference value (e.g. |actual - 96| / 96 for M, but
    |actual - 122| / 122 for XXL). That's mathematically inconsistent: the
    same real-world cm miss scores as a smaller relative error against a
    bigger size purely because the denominator is bigger -- a mechanical
    bias toward larger sizes that had nothing to do with actual fit. That's
    what let a distant size (e.g. M) out-score a closer one (e.g. XL) when
    XXL was recommended.

    The fix (_dimension_confidence) divides by a FIXED per-dimension
    constant (the typical cm change between adjacent sizes, SIZE_STEP_CM)
    instead, so the same cm miss always costs the same confidence no
    matter which size it's measured against. These tests verify the
    result actually behaves the way a customer would expect: confidence
    decays consistently and predictably, not just "doesn't crash."
    """

    def test_same_cm_miss_past_the_edge_costs_the_same_confidence_at_any_size(self, fit_checker):
        """
        The exact original bug: dividing by the candidate's own reference
        meant the same real-world cm miss scored worse against a small
        size (denominator ~88) than against a large one (denominator
        ~122). Boundary-aware scoring's invariant isn't "same distance
        from the center" (sizes have different bucket widths on purpose,
        e.g. XXL is intentionally wide-open) -- it's "the same distance
        PAST a size's edge costs the same", since anything still inside
        the boundary scores a flat 1.0 regardless of the size's width.
        """
        from py_src.constants import SIZE_BOUNDARIES

        small_size, big_size = "S", "XL"
        small_hi = SIZE_BOUNDARIES[small_size][1]
        big_hi = SIZE_BOUNDARIES[big_size][1]

        # Scored as Vests, which weights bust at 1.0 and ignores waist and hips
        # entirely -- so this measures the bust miss and nothing else. Blending
        # all three cannot express the invariant: the published chart's bands
        # have different widths, so an in-band waist sits a different distance
        # from its edges at S than at XL and contributes its own unequal
        # penalty. (This previously passed only because the boundary tables were
        # a uniform grid, where that could not happen.)
        product_small = {"sku": "p1", "category": "Vests", "sizes": [small_size]}
        product_big = {"sku": "p2", "category": "Vests", "sizes": [big_size]}

        miss_past_edge_cm = 4.0
        measurements_small = {
            **STANDARD_SIZE_CHART[small_size],
            "bust": small_hi + miss_past_edge_cm,
            "height": 165.0,
        }
        measurements_big = {
            **STANDARD_SIZE_CHART[big_size],
            "bust": big_hi + miss_past_edge_cm,
            "height": 165.0,
        }

        result_small = fit_checker.check_fit("test_user", measurements_small, product_small)
        result_big = fit_checker.check_fit("test_user", measurements_big, product_big)

        assert result_small["fit_scores"][small_size] == result_big["fit_scores"][big_size], (
            "An identical 4cm miss past the boundary edge should cost identical confidence "
            f"whether measured against {small_size} ({result_small['fit_scores'][small_size]}) "
            f"or {big_size} ({result_big['fit_scores'][big_size]})"
        )

    def test_any_measurement_inside_a_sizes_boundary_scores_a_perfect_1(self, fit_checker):
        """
        The dead-zone bug this fix closes: XXL's real range is wide and
        open-ended (hips 114-150cm). Scoring by distance from a single
        capped 'center' point meant someone at the far end of that range
        (e.g. hips=145cm, still legitimately XXL) could decay all the way
        to 0% confidence. Anywhere inside the actual boundary must score
        a flat 1.0, no matter how far from the middle of the range.
        """
        from py_src.constants import STANDARD_SIZES

        product = {"sku": "boundary-check", "category": "Skirts", "sizes": STANDARD_SIZES}
        # hips=145 is deep in XXL's (114, 150) range, far from any "center".
        measurements = {"bust": 90.0, "waist": 75.0, "hips": 145.0, "height": 165.0}

        result = fit_checker.check_fit("test_user", measurements, product)
        assert result["fit_scores"]["XXL"] == 1.0
        assert result["recommended_size"] == "XXL"

    def test_confidence_ramps_down_near_a_boundary_instead_of_reading_flat_100_everywhere(self, fit_checker):
        """
        A customer whose measurement sits right at the edge of their size
        should see that reflected in the percentage -- not the exact same
        100% as someone dead-center in the range. Confidence ramps from
        FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE at the edge up to 1.0 once
        you're comfortably inside the size (more than the cushion distance
        from both edges).
        """
        from py_src.constants import (
            STANDARD_SIZES, SIZE_BOUNDARIES,
            FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE, FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM,
        )

        product = {"sku": "ramp-check", "category": "Vests", "sizes": STANDARD_SIZES}
        lo, hi = SIZE_BOUNDARIES["XL"]
        cushion = FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM["bust"]

        def confidence_at(bust):
            measurements = {"bust": bust, "waist": 80.0, "hips": 95.0, "height": 165.0}
            return fit_checker.check_fit("test_user", measurements, product, known_size="XL")["confidence"]

        at_lower_edge = confidence_at(lo + 0.001)
        at_center = confidence_at((lo + hi) / 2)
        at_upper_edge = confidence_at(hi - 0.001)
        just_past_cushion = confidence_at(lo + cushion + 0.5)

        assert at_lower_edge == FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE
        assert at_upper_edge == FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE
        assert at_center == 1.0
        assert just_past_cushion == 1.0, "Comfortably past the cushion zone should already read 100%"
        assert at_lower_edge < confidence_at(lo + cushion / 2) < just_past_cushion, (
            "Confidence should ramp monotonically from the edge floor up to 100%"
        )

    def test_wide_bucket_still_reads_100_percent_deep_inside_its_own_range(self, fit_checker):
        """
        Companion to the dead-zone regression test above, at a value much
        closer to XXL's edge than 145cm was: even fairly close to the
        boundary (but past the cushion), a wide bucket like XXL should
        still read 100%, not ramp down across its whole (very wide) range.
        """
        from py_src.constants import STANDARD_SIZES, HIP_SIZE_BOUNDARIES, FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM

        product = {"sku": "wide-bucket-check", "category": "Skirts", "sizes": STANDARD_SIZES}
        lo, _hi = HIP_SIZE_BOUNDARIES["XXL"]
        cushion = FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM["hips"]
        just_inside = lo + cushion + 1.0  # just past the cushion from the lower edge

        measurements = {"bust": 90.0, "waist": 75.0, "hips": just_inside, "height": 165.0}
        result = fit_checker.check_fit("test_user", measurements, product, known_size="XXL")
        assert result["fit_scores"]["XXL"] == 1.0

    def test_fit_details_says_more_than_just_fits_perfectly_near_a_boundary(self, fit_checker):
        """
        Under boundary-aware scoring, the recommended size's own score can
        never drop below FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE (0.85) -- so
        "acceptable with minor adjustments" and "may require alterations"
        can never appear for it in these categories anymore (that's
        correct: the recommended size, by construction, always fits
        reasonably on the one measurement that determines this garment's
        size). But "fits perfectly" shouldn't be the ONLY other thing a
        customer ever sees either -- close to a boundary should
        meaningfully read as "a good fit" rather than an identical
        "perfectly" for someone dead-center and someone one cm from the
        edge of their size.
        """
        from py_src.constants import STANDARD_SIZES, SIZE_BOUNDARIES

        product = {"sku": "fit-details-check", "category": "Vests", "sizes": STANDARD_SIZES}
        lo, hi = SIZE_BOUNDARIES["XL"]

        right_at_edge = fit_checker.check_fit(
            "test_user", {"bust": lo + 0.5, "waist": 87.0, "hips": 104.0, "height": 165.0},
            product, known_size="XL",
        )
        dead_center = fit_checker.check_fit(
            "test_user", {"bust": (lo + hi) / 2, "waist": 87.0, "hips": 104.0, "height": 165.0},
            product, known_size="XL",
        )

        assert right_at_edge["fit_notes"][0] == "Size XL is a good fit."
        assert dead_center["fit_notes"][0] == "Size XL fits perfectly."
        assert right_at_edge["fit_notes"][0] != dead_center["fit_notes"][0]

    def test_dimension_confidence_decays_linearly_by_size_steps_off(self, fit_checker):
        """0/1/2/3 sizes off should map to 1.0/~0.67/~0.33/0.0 confidence --
        a concrete, human-checkable interpretation of the score."""
        step = 10.0
        assert fit_checker._dimension_confidence(100.0, 100.0, step) == 1.0
        assert round(fit_checker._dimension_confidence(110.0, 100.0, step), 2) == 0.67
        assert round(fit_checker._dimension_confidence(120.0, 100.0, step), 2) == 0.33
        assert fit_checker._dimension_confidence(130.0, 100.0, step) == 0.0
        assert fit_checker._dimension_confidence(150.0, 100.0, step) == 0.0, (
            "Confidence must floor at 0, never go negative, for a size way off"
        )

    def test_confidence_strictly_decreases_moving_away_from_true_size_in_either_direction(self, fit_checker):
        """
        For a body sitting exactly at one size's chart values (a 'textbook'
        proportioned body), that size must score strictly highest, and
        confidence must fall monotonically as candidate sizes get further away
        -- walking DOWN the size range and walking UP it. This is the property
        that makes "next best size" suggestions intuitive without hardcoding
        adjacency.

        Deliberately NOT asserted: that the two directions interleave into one
        ranking by size-index distance (i.e. that one size down always beats two
        sizes up). That held only while the boundary tables were a uniform grid.
        The published chart's gaps between adjacent sizes are genuinely uneven --
        bust XS->S and S->M are 2cm, M->L is 4cm, L->XL is 5cm -- so from XL's
        cut, XXL really is nearer than L, and scoring it marginally higher is the
        honest answer rather than a defect to be normalised away.
        """
        from py_src.constants import STANDARD_SIZE_CHART, STANDARD_SIZES

        product = {"sku": "monotonic-check", "sizes": STANDARD_SIZES}

        for true_size in STANDARD_SIZES:
            index = STANDARD_SIZES.index(true_size)
            measurements = {**STANDARD_SIZE_CHART[true_size], "height": 165.0}
            scores = fit_checker.check_fit("test_user", measurements, product)["fit_scores"]

            best = max(scores, key=scores.get)
            assert best == true_size and list(scores.values()).count(scores[true_size]) == 1, (
                f"A body at {true_size}'s exact chart values should score "
                f"{true_size} uniquely highest, got {scores}"
            )

            downward = [scores[s] for s in STANDARD_SIZES[:index + 1]][::-1]
            upward = [scores[s] for s in STANDARD_SIZES[index:]]
            for direction, series in (("downward", downward), ("upward", upward)):
                assert series == sorted(series, reverse=True), (
                    f"For a body at {true_size}'s exact chart values, scores "
                    f"{direction} from {true_size} ({series}) should be non-increasing"
                )

    def test_pear_shaped_body_gets_no_self_contradictory_alternative(self, fit_checker):
        """
        The exact real-world case that motivated this fix: hips alone
        (known_size, for a Skirts/Trousers category) recommend XXL, but
        bust/waist are proportioned like a much smaller body. The fixed
        formula should score the recommendation honestly low (it really
        is a poor overall match) rather than spuriously letting a
        non-adjacent size like M look "also good".
        """
        from py_src.constants import STANDARD_SIZES

        product = {"sku": "pear-check", "sizes": STANDARD_SIZES}
        measurements = {"bust": 96.0, "waist": 81.0, "hips": 119.0, "height": 165.0}
        result = fit_checker.check_fit(
            "test_user", measurements, product, known_size="XXL"
        )
        assert result["recommended_size"] == "XXL"

        rec_score = result["fit_scores"]["XXL"]
        notes_text = " ".join(result["fit_notes"])
        for size, score in result["fit_scores"].items():
            if size == "XXL" or score <= rec_score:
                continue
            assert f"Size {size} is also a good option" not in notes_text, (
                f"Size {size} ({score}) outscores the recommendation XXL ({rec_score}) "
                "and should never be offered as a supporting 'alternative'"
            )


class TestM7CategoryAwareDimensionWeights:
    """
    Regression coverage for the exact real-world report: a customer with
    bust=110, waist=81, hips=91, height=180 got "Recommended Size: XL
    (43%)" for a Vest, with the breakdown showing M at 70% and L at 60% --
    both HIGHER than the recommended XL. The displayed ranking directly
    contradicted the recommendation it was supposed to support.

    Root cause: a vest doesn't cover the hips, but _calculate_fit_scores
    blended bust+waist+hips at equal weight for every category, so this
    customer's much-smaller hips (91cm, nowhere near XL's ~110.5cm
    reference) dragged XL's blended score down even though bust -- the
    only measurement that actually determines a vest's fit -- put them
    solidly in XL (108-117cm, per M3's own SIZE_BOUNDARIES). Fixed by
    weighting each category's score by the same single measurement M3
    uses to size it (FIT_SCORE_DIMENSION_WEIGHTS), which guarantees the
    highest-scoring size and the recommendation can never disagree for
    these categories.
    """

    def test_reported_vest_scenario_recommendation_matches_highest_score(self, fit_checker):
        from py_src.constants import STANDARD_SIZES

        product = {"sku": "vest-check", "category": "Vests", "sizes": STANDARD_SIZES}
        measurements = {"bust": 110.0, "waist": 81.0, "hips": 91.0, "height": 180.0}

        result = fit_checker.check_fit("test_user", measurements, product)

        assert result["recommended_size"] == "XL", (
            f"Expected XL (bust=110 falls in M3's 108-117 bust range), got {result['recommended_size']}"
        )
        top_scored = max(result["fit_scores"].items(), key=lambda x: x[1])[0]
        assert top_scored == "XL", (
            f"The highest-scoring size ({top_scored}: {result['fit_scores'][top_scored]}) must be the "
            f"recommended size (XL: {result['fit_scores']['XL']}) -- a customer should never see a "
            "size other than the recommendation scoring higher"
        )

    def test_vest_score_ignores_hips_entirely(self, fit_checker):
        """Two bodies with identical bust/waist but wildly different hips
        must score identically for a Vest -- hips don't affect how a vest
        fits, so they shouldn't affect its score."""
        from py_src.constants import STANDARD_SIZES

        product = {"sku": "vest-check", "category": "Vests", "sizes": STANDARD_SIZES}
        result_a = fit_checker.check_fit(
            "test_user", {"bust": 110.0, "waist": 81.0, "hips": 85.0, "height": 165.0}, product
        )
        result_b = fit_checker.check_fit(
            "test_user", {"bust": 110.0, "waist": 81.0, "hips": 140.0, "height": 165.0}, product
        )
        assert result_a["fit_scores"] == result_b["fit_scores"]

    def test_skirt_score_ignores_bust_entirely(self, fit_checker):
        """Same principle for the bottom-half categories: a skirt doesn't
        care about bust."""
        from py_src.constants import STANDARD_SIZES

        product = {"sku": "skirt-check", "category": "Skirts", "sizes": STANDARD_SIZES}
        measurements = {"bust": 130.0, "waist": 87.0, "hips": 104.0, "height": 165.0}
        result = fit_checker.check_fit("test_user", measurements, product)

        assert result["recommended_size"] == "L", (
            f"Expected L (hips=104 is L's own chart center), got {result['recommended_size']}"
        )
        top_scored = max(result["fit_scores"].items(), key=lambda x: x[1])[0]
        assert top_scored == "L"

    def test_unmapped_categories_keep_the_equal_blend(self, fit_checker):
        """Any category not in FIT_SCORE_DIMENSION_WEIGHTS (or no category
        at all) has no defined 'correct' single measurement, so it should
        still blend all three evenly."""
        from py_src.constants import STANDARD_SIZES

        measurements = {**STANDARD_SIZE_CHART["M"], "height": 165.0}
        unmapped_product = {"sku": "unmapped-check", "category": "Something Else", "sizes": STANDARD_SIZES}
        no_category_product = {"sku": "no-cat-check", "sizes": STANDARD_SIZES}

        for product in (unmapped_product, no_category_product):
            result = fit_checker.check_fit("test_user", measurements, product)
            # These measurements are M's exact chart center in all three
            # dimensions, so an equal blend scores M at a perfect 1.0.
            assert result["fit_scores"]["M"] == 1.0
            assert result["recommended_size"] == "M"

    def test_coord_sets_is_sized_like_a_top(self, fit_checker):
        """
        A Co-ord Set only has one size field to fill (there's no separate
        top/bottom selector), and a two-piece outfit genuinely can need
        different sizes for each half -- blending bust+waist+hips equally
        just produces an unexplained compromise (e.g. bust says XL, hips
        say S, but the customer sees "M"). Sized like a Top instead
        (bust-driven only), matching the same "tops" convention M5's
        recommendation engine already uses as the general default size
        elsewhere in this system -- at least it's then a single,
        traceable, explainable number.
        """
        from py_src.constants import STANDARD_SIZES

        product = {"sku": "coord-check", "category": "Co-ord Sets", "sizes": STANDARD_SIZES}
        # bust -> XL, hips -> S: a genuinely mismatched body.
        measurements = {"bust": 111.0, "waist": 78.0, "hips": 85.0, "height": 165.0}

        result = fit_checker.check_fit("test_user", measurements, product, known_size="XL")

        assert result["recommended_size"] == "XL"
        assert result["fit_scores"]["XL"] == max(result["fit_scores"].values())
        # Hips must have zero influence, the same as any other bust-driven category.
        result_different_hips = fit_checker.check_fit(
            "test_user", {**measurements, "hips": 145.0}, product, known_size="XL"
        )
        assert result["fit_scores"] == result_different_hips["fit_scores"]


class TestM7EdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_size_product(self, fit_checker):
        """Product with only one size should still work."""
        product = {
            "sku": "one-size",
            "sizes": ["M"],
        }
        measurements = {
            "bust": 100.0,
            "waist": 80.0,
            "hips": 105.0,
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, product)

        assert result["recommended_size"] == "M"
        assert "M" in result["fit_scores"]
        assert len(result["fit_scores"]) == 1

    def test_measurements_as_integers(self, fit_checker, test_product):
        """Measurements provided as integers should be accepted."""
        int_measurements = {
            # Integers rather than floats, at M's chart values.
            **{d: int(v) for d, v in STANDARD_SIZE_CHART["M"].items()},
            "height": 165,
        }
        result = fit_checker.check_fit("test_user", int_measurements, test_product)

        assert result["recommended_size"] == "M"
        assert result["confidence"] == 1.0

    def test_measurements_at_size_boundary(self, fit_checker, test_product):
        """Measurements exactly at standard size should score high."""
        for size in ["XS", "S", "M", "L", "XL"]:
            standard_chart = FitChecker.STANDARD_SIZE_CHART[size]
            measurements = {
                "bust": standard_chart["bust"],
                "waist": standard_chart["waist"],
                "hips": standard_chart["hips"],
                "height": 165.0,
            }
            result = fit_checker.check_fit("test_user", measurements, test_product)

            # Should recommend this size with high confidence
            assert result["recommended_size"] == size, f"Should recommend {size} for exact match"
            assert result["confidence"] == 1.0, f"Perfect match should have confidence 1.0"
