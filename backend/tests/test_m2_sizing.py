"""Tests for M2 — Sizing Integration."""

import pytest
from py_src.modules.m2_sizing_integration import (
    Measurements,
    MockSizingProvider,
    SizingIntegration,
)
from py_src.utils.errors import ModuleError


@pytest.fixture
def sizing():
    """Fresh SizingIntegration instance."""
    return SizingIntegration()


class TestMeasurements:
    """Test Measurements data model."""

    def test_measurements_creation(self):
        """Create a Measurements object."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
            shoulder=39.0,
        )
        assert m.bust == 88.0
        assert m.waist == 70.0
        assert m.height == 165.0

    def test_measurements_shoulder_left_none_if_not_provided(self):
        """
        Shoulder must NOT silently default to hips -- hips (~80-160cm) and
        shoulder width (~30-60cm) are different physical measurements, and
        defaulting one to the other produces an anatomically invalid value
        that then fails downstream range validation (M7/M9 both do this).
        Leave it None, matching how inseam already behaves.
        """
        m = Measurements(bust=88.0, waist=70.0, hips=102.0, height=165.0)
        assert m.shoulder is None

    def test_measurements_confidence_scores(self):
        """Measurements include per-field confidence scores."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
            confidence_scores={
                "bust": 0.95,
                "waist": 0.92,
                "hips": 0.90,
            },
        )
        assert m.confidence_scores["bust"] == 0.95

    def test_measurements_min_confidence(self):
        """min_confidence() returns lowest score."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
            confidence_scores={
                "bust": 0.95,
                "waist": 0.70,
                "hips": 0.90,
            },
        )
        assert m.min_confidence() == 0.70

    def test_measurements_low_confidence_fields(self):
        """low_confidence_fields() returns list of fields below threshold."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
            confidence_scores={
                "bust": 0.95,
                "waist": 0.65,
                "hips": 0.90,
            },
        )
        low = m.low_confidence_fields(threshold=0.75)
        assert "waist" in low
        assert len(low) == 1

    def test_measurements_to_dict(self):
        """Convert Measurements to dict."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
        )
        d = m.to_dict()
        assert d["bust"] == 88.0
        assert d["provider"] == "mock"


class TestMockSizingProvider:
    """Test mock sizing provider."""

    def test_mock_provider_deterministic(self):
        """Mock provider returns same measurements for same photo_ref."""
        provider = MockSizingProvider()
        m1 = provider.extract_measurements("photo_1.jpg", height_cm=165.0)
        m2 = provider.extract_measurements("photo_1.jpg", height_cm=165.0)

        assert m1.bust == m2.bust
        assert m1.waist == m2.waist
        assert m1.confidence_scores == m2.confidence_scores

    def test_mock_provider_respects_height(self):
        """Mock provider respects provided height."""
        provider = MockSizingProvider()
        m = provider.extract_measurements("photo.jpg", height_cm=175.0)
        assert m.height == 175.0

    def test_mock_provider_default_height(self):
        """Mock provider uses default height if not provided."""
        provider = MockSizingProvider()
        m = provider.extract_measurements("photo.jpg")
        assert m.height == 165.0

    def test_mock_provider_high_confidence(self):
        """Mock provider returns high confidence scores."""
        provider = MockSizingProvider()
        m = provider.extract_measurements("photo.jpg")
        assert m.min_confidence() > 0.80
        assert m.confidence_scores["bust"] == 0.95

    def test_mock_provider_invalid_photo_ref(self):
        """Reject invalid photo references."""
        provider = MockSizingProvider()
        with pytest.raises(ModuleError):
            provider.extract_measurements("")


class TestSizingIntegration:
    """Test SizingIntegration wrapper."""

    def test_integration_extract_measurements(self, sizing):
        """Extract measurements through integration layer."""
        m = sizing.extract_measurements(
            photo_ref="s3://bucket/photo.jpg",
            height_cm=165.0,
        )
        assert m.bust == 88.0
        assert m.waist == 70.0

    def test_integration_validates_extracted_measurements(self, sizing):
        """Integration layer validates extracted measurements."""
        m = sizing.extract_measurements(
            photo_ref="s3://bucket/photo.jpg",
            height_cm=165.0,
        )
        # Measurements should pass validation
        assert m.bust > 0
        assert m.waist > 0

    def test_integration_audit_logging(self, sizing):
        """Integration layer logs extraction with user_id."""
        m = sizing.extract_measurements(
            photo_ref="s3://bucket/photo.jpg",
            height_cm=165.0,
            user_id="test_user",
        )
        # Should complete without error; audit logged
        assert m is not None

    def test_integration_invalid_photo_ref(self, sizing):
        """Reject invalid photo references."""
        with pytest.raises(ModuleError):
            sizing.extract_measurements(photo_ref="")

    def test_integration_invalid_photo_ref_type(self, sizing):
        """Reject non-string photo references."""
        with pytest.raises(ModuleError):
            sizing.extract_measurements(photo_ref=123)


class TestConfidenceThresholding:
    """Test confidence-based routing logic."""

    def test_measurements_below_threshold(self):
        """Identify measurements below confidence threshold."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
            confidence_scores={
                "bust": 0.95,
                "waist": 0.60,
                "hips": 0.70,
            },
        )
        low = m.low_confidence_fields(threshold=0.75)
        assert "waist" in low
        assert "hips" in low
        assert "bust" not in low

    def test_measurements_all_above_threshold(self):
        """No low-confidence fields if all above threshold."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
            confidence_scores={
                "bust": 0.95,
                "waist": 0.92,
                "hips": 0.90,
            },
        )
        low = m.low_confidence_fields(threshold=0.75)
        assert len(low) == 0

    def test_measurements_exactly_at_threshold(self):
        """Include fields exactly at threshold."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
            confidence_scores={
                "bust": 0.75,
                "waist": 0.74,
            },
        )
        low = m.low_confidence_fields(threshold=0.75)
        assert "bust" not in low
        assert "waist" in low


class TestProviderInterface:
    """Test SizingProvider abstraction."""

    def test_mock_provider_implements_interface(self):
        """MockSizingProvider implements SizingProvider."""
        from py_src.modules.m2_sizing_integration import SizingProvider

        provider = MockSizingProvider()
        assert isinstance(provider, SizingProvider)

    def test_custom_provider_swap(self):
        """Can swap providers without changing interface."""

        class CustomProvider(MockSizingProvider):
            def extract_measurements(self, photo_ref, height_cm=None):
                # Custom implementation
                m = super().extract_measurements(photo_ref, height_cm or 165.0)
                m.provider = "custom"
                return m

        sizing = SizingIntegration(provider=CustomProvider())
        m = sizing.extract_measurements("photo.jpg", height_cm=165.0)
        assert m.provider == "custom"


class TestMeasurementEdgeCases:
    """Test edge cases in measurement extraction."""

    def test_measurements_very_small_values(self):
        """Handle very small but valid measurements."""
        m = Measurements(
            bust=70.0,
            waist=60.0,
            hips=85.0,
            height=150.0,
        )
        assert m.bust == 70.0
        assert m.waist == 60.0

    def test_measurements_very_large_values(self):
        """Handle very large but valid measurements."""
        m = Measurements(
            bust=120.0,
            waist=110.0,
            hips=130.0,
            height=190.0,
        )
        assert m.bust == 120.0

    def test_measurements_ratio_computation_safe(self):
        """Measurements don't allow division by zero."""
        m = Measurements(
            bust=88.0,
            waist=0.01,  # Near zero but not zero
            hips=102.0,
            height=165.0,
        )
        # Should not raise division by zero
        assert m.waist == 0.01

    def test_measurements_optional_fields(self):
        """Inseam and shoulder are optional."""
        m = Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            height=165.0,
            inseam=None,
            shoulder=None,
        )
        assert m.inseam is None
        assert m.shoulder is None


class TestMeasurementValidation:
    """Test measurement validation through integration."""

    def test_extracted_measurements_pass_validation(self, sizing):
        """Extracted measurements pass upstream validation."""
        m = sizing.extract_measurements("photo.jpg", height_cm=165.0)
        # If we got here, measurements are valid
        assert m.bust > 0
        assert m.waist > 0
        assert m.hips > 0

    def test_measurements_provider_versioning(self, sizing):
        """Measurements include provider version."""
        m = sizing.extract_measurements("photo.jpg", height_cm=165.0)
        assert m.provider_version is not None
        assert m.provider == "mock"

    def test_measurements_timestamp(self, sizing):
        """Measurements include extraction timestamp."""
        m = sizing.extract_measurements("photo.jpg", height_cm=165.0)
        assert m.extracted_at is not None
        assert m.extracted_at > 0
