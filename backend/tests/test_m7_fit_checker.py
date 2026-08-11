"""Comprehensive tests for M7 — Fit Checker."""

import pytest
from unittest.mock import MagicMock, patch
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
        measurements = {
            "bust": 90.0,  # Exactly matches size M
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
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
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)

        notes_text = " ".join(result["fit_notes"]).lower()
        assert "fits perfectly" in notes_text, "Perfect fit should mention 'fits perfectly'"

    def test_loose_bust_generates_specific_note(self, fit_checker, test_product):
        """Loose bust should generate specific note about bust, not other measurements."""
        measurements = {
            "bust": 85.0,    # Smaller than size M (90), will be loose
            "waist": 72.0,   # Exact match to M
            "hips": 97.0,    # Exact match to M
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
        """Snug waist should generate specific note about waist, not other measurements."""
        measurements = {
            "bust": 90.0,    # Exact match to M
            "waist": 76.0,   # Larger than size M (72), will be snug
            "hips": 97.0,    # Exact match to M
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)

        # Verify note exists and mentions the specific issue
        notes_text = " ".join(result["fit_notes"]).lower()
        # Should mention waist AND snug/small
        found_waist_note = "waist" in notes_text and ("snug" in notes_text or "small" in notes_text)
        assert found_waist_note, \
            f"Should have specific note about snug waist. Notes: {result['fit_notes']}"

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
            "bust": 90,  # Integer, not float
            "waist": 72,
            "hips": 97,
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
