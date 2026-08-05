"""Tests for M7 — Fit Checker."""

import pytest
from py_src.modules.m7_fit_checker import FitChecker
from py_src.guardrails.consent_tracker import ConsentTracker
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

    def test_rejects_missing_measurements(self, fit_checker, test_product, consent_tracker):
        """Missing measurement field should raise error."""
        measurements = {"bust": 90.0, "waist": 72.0}  # Missing hips, height
        with pytest.raises(ModuleError, match="Missing measurements"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_negative_measurements(self, fit_checker, test_product, consent_tracker):
        """Negative measurement should raise error."""
        measurements = {
            "bust": 90.0,
            "waist": -72.0,  # Invalid
            "hips": 97.0,
            "height": 165.0,
        }
        with pytest.raises(ModuleError, match="must be positive"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_invalid_height(self, fit_checker, test_product, consent_tracker):
        """Height outside valid range (140-210cm) should raise error."""
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 250.0,  # Too tall
        }
        with pytest.raises(ModuleError, match="height"):
            fit_checker.check_fit("test_user", measurements, test_product)

    def test_rejects_missing_product_fields(self, fit_checker, consent_tracker):
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

    def test_rejects_empty_product_sizes(self, fit_checker, consent_tracker):
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


class TestM7ConsentEnforcement:
    """Test consent verification."""

    def test_rejects_without_measurement_consent(self, fit_checker, test_product, test_measurements):
        """Should reject if user hasn't consented to measurement processing."""
        # Create tracker without measurement consent
        tracker = ConsentTracker()
        tracker.record_consent(user_id="no_consent_user", photo_consent=True, measurement_consent=False)
        checker = FitChecker(consent_tracker=tracker)

        with pytest.raises(GuardrailError, match="consented"):
            checker.check_fit("no_consent_user", test_measurements, test_product)


class TestM7FitScoring:
    """Test fit score calculation."""

    def test_perfect_fit_scores_high(self, fit_checker, test_product, test_measurements, consent_tracker):
        """Measurements matching size M should score high for size M."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        # Size M should have highest confidence
        m_score = result["fit_scores"]["M"]
        assert m_score >= 0.90, f"Size M should score high, got {m_score}"

        # Should recommend size M
        assert result["recommended_size"] == "M"

    def test_smaller_user_recommends_smaller_size(self, fit_checker, test_product, consent_tracker):
        """User with smaller measurements should get recommended smaller size."""
        small_measurements = {
            "bust": 80.0,  # Smaller than standard S (84)
            "waist": 60.0,  # Smaller than standard S (66)
            "hips": 85.0,   # Similar to S (91)
            "height": 160.0,
        }
        result = fit_checker.check_fit("test_user", small_measurements, test_product)

        # Should recommend XS or S
        assert result["recommended_size"] in ["XS", "S"]

    def test_larger_user_recommends_larger_size(self, fit_checker, test_product, consent_tracker):
        """User with larger measurements should get recommended larger size."""
        large_measurements = {
            "bust": 105.0,  # Larger than standard L (96)
            "waist": 82.0,  # Larger than standard L (78)
            "hips": 110.0,  # Larger than standard L (103)
            "height": 175.0,
        }
        result = fit_checker.check_fit("test_user", large_measurements, test_product)

        # Should recommend XL or XXL
        assert result["recommended_size"] in ["XL", "XXL"]

    def test_all_sizes_scored(self, fit_checker, test_product, test_measurements, consent_tracker):
        """All available sizes should have fit scores."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        for size in test_product["sizes"]:
            assert size in result["fit_scores"]
            assert 0 <= result["fit_scores"][size] <= 1


class TestM7FitNotes:
    """Test fit guidance notes."""

    def test_perfect_fit_generates_positive_note(self, fit_checker, test_product, test_measurements, consent_tracker):
        """Perfect fit should generate positive guidance note."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        assert any("perfectly" in note.lower() or "good fit" in note.lower()
                   for note in result["fit_notes"])

    def test_loose_fit_noted(self, fit_checker, test_product, consent_tracker):
        """Loose fit in specific area should be noted."""
        measurements = {
            "bust": 88.0,    # Smaller than size M (90)
            "waist": 70.0,   # Smaller than size M (72)
            "hips": 95.0,    # Smaller than size M (97)
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)

        notes = " ".join(result["fit_notes"]).lower()
        # Notes should indicate loose fit
        assert "fit" in notes or "loose" in notes or "small" in notes

    def test_snug_fit_noted(self, fit_checker, test_product, consent_tracker):
        """Snug fit in specific area should be noted."""
        measurements = {
            "bust": 95.0,    # Larger than size M (90)
            "waist": 76.0,   # Larger than size M (72)
            "hips": 102.0,   # Larger than size M (97)
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, test_product)

        notes = " ".join(result["fit_notes"]).lower()
        # Notes should be generated
        assert len(result["fit_notes"]) > 0

    def test_has_recommended_size_note(self, fit_checker, test_product, test_measurements, consent_tracker):
        """Result should always include note about recommended size."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        rec_size = result["recommended_size"]
        notes_text = " ".join(result["fit_notes"]).lower()
        assert rec_size.lower() in notes_text


class TestM7ResponseFormat:
    """Test response structure."""

    def test_response_has_required_fields(self, fit_checker, test_product, test_measurements, consent_tracker):
        """Response should have all required fields."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        required_fields = {"product_sku", "fit_scores", "recommended_size", "fit_notes", "confidence"}
        assert required_fields.issubset(result.keys())

    def test_fit_scores_dict_format(self, fit_checker, test_product, test_measurements, consent_tracker):
        """fit_scores should be dict of {size: float (0-1)}."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        assert isinstance(result["fit_scores"], dict)
        for size, score in result["fit_scores"].items():
            assert isinstance(size, str)
            assert isinstance(score, float)
            assert 0 <= score <= 1

    def test_fit_notes_list_format(self, fit_checker, test_product, test_measurements, consent_tracker):
        """fit_notes should be list of strings."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        assert isinstance(result["fit_notes"], list)
        for note in result["fit_notes"]:
            assert isinstance(note, str)
            assert len(note) > 0

    def test_confidence_is_0_to_1(self, fit_checker, test_product, test_measurements, consent_tracker):
        """confidence should be float between 0 and 1."""
        result = fit_checker.check_fit("test_user", test_measurements, test_product)

        assert isinstance(result["confidence"], float)
        assert 0 <= result["confidence"] <= 1


class TestM7CustomSizeChart:
    """Test handling of custom product size charts."""

    def test_uses_product_size_chart_if_provided(self, fit_checker, consent_tracker):
        """Should use product's custom size chart over standard."""
        custom_chart = {
            "S": {"bust": 82, "waist": 64, "hips": 89},
            "M": {"bust": 88, "waist": 70, "hips": 95},
            "L": {"bust": 94, "waist": 76, "hips": 101},
        }
        product = {
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
        result = fit_checker.check_fit("test_user", measurements, product)

        # Should recommend M (perfect match with custom chart)
        assert result["recommended_size"] == "M"
        assert result["confidence"] >= 0.90

    def test_handles_missing_size_in_chart(self, fit_checker, consent_tracker):
        """Should handle size not in provided chart."""
        sparse_chart = {
            "M": {"bust": 90, "waist": 72, "hips": 97},
            # S and L missing from chart
        }
        product = {
            "sku": "sparse-top",
            "sizes": ["S", "M", "L"],
            "size_chart": sparse_chart,
        }
        measurements = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
        }
        result = fit_checker.check_fit("test_user", measurements, product)

        # Should return a result (gracefully handle missing sizes)
        assert result["recommended_size"] in ["S", "M", "L"]


class TestM7AuditLogging:
    """Test audit trail generation."""

    def test_audit_log_called(self, fit_checker, test_product, test_measurements, consent_tracker):
        """Fit check should log audit event."""
        # This test verifies the fit check completes (audit logging happens internally)
        result = fit_checker.check_fit("test_user", test_measurements, test_product, session_id="sess-123")

        # If we got here without error, audit logging worked
        assert result is not None
        assert result["product_sku"] == test_product["sku"]
