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


# Minimal valid image payloads for the upload path. Content is never
# inspected by the mock provider -- these just need to be real bytes.
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class TestExtractFromImage:
    """Test the uploaded-bytes extraction path (POST /intake/photo-measure)."""

    def test_returns_measurements_from_bytes(self, sizing):
        m = sizing.extract_from_image(JPEG_BYTES, "image/jpeg", height_cm=170.0)
        assert m.bust == 88.0
        assert m.waist == 70.0
        assert m.hips == 102.0
        assert m.provider == "mock"

    def test_height_is_passed_through_as_scale_reference(self, sizing):
        m = sizing.extract_from_image(JPEG_BYTES, "image/jpeg", height_cm=182.0)
        assert m.height == 182.0

    def test_defaults_height_when_omitted(self, sizing):
        m = sizing.extract_from_image(JPEG_BYTES, "image/jpeg")
        assert m.height == 165.0

    def test_matches_the_photo_ref_path(self, sizing):
        """
        Both entry points must produce identical measurements for the same
        height -- they share one definition inside the provider, and this is
        the test that keeps them from drifting.
        """
        from_ref = sizing.extract_measurements("photo.jpg", height_cm=171.0)
        from_bytes = sizing.extract_from_image(PNG_BYTES, "image/png", height_cm=171.0)

        ref_dict = from_ref.to_dict()
        bytes_dict = from_bytes.to_dict()
        # extracted_at is a wall-clock stamp, so compare everything else.
        ref_dict.pop("extracted_at")
        bytes_dict.pop("extracted_at")
        assert ref_dict == bytes_dict

    def test_empty_bytes_rejected(self, sizing):
        with pytest.raises(ModuleError):
            sizing.extract_from_image(b"", "image/jpeg", height_cm=165.0)

    def test_non_bytes_rejected(self, sizing):
        with pytest.raises(ModuleError):
            sizing.extract_from_image("not-bytes", "image/jpeg", height_cm=165.0)

    def test_result_passes_measurement_validation(self, sizing):
        """SizingIntegration validates provider output the same way both paths do."""
        m = sizing.extract_from_image(JPEG_BYTES, "image/jpeg", height_cm=165.0)
        assert m.unit == "cm"
        assert m.min_confidence() > 0.75

    def test_base_provider_rejects_direct_upload_by_default(self):
        """
        extract_from_image is concrete-but-unsupported on the ABC, so a
        provider that only implements the photo_ref flow stays valid rather
        than failing to instantiate.
        """
        from py_src.modules.m2_sizing_integration import SizingProvider

        class RefOnlyProvider(SizingProvider):
            def extract_measurements(self, photo_ref, height_cm=None):
                return Measurements(bust=88, waist=70, hips=102, height=165)

        provider = RefOnlyProvider()
        assert isinstance(provider, SizingProvider)  # instantiable
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(JPEG_BYTES, "image/jpeg", 165.0)
        assert "does not support direct image upload" in str(exc.value)


class TestProviderRegistry:
    """Test the swap surface for a real vendor integration."""

    def test_defaults_to_real_photo_analysis(self, monkeypatch):
        """
        With no configuration at all, photos must be genuinely analysed.

        This used to default to the mock, which meant every way of starting the
        server except run.sh -- `python main.py`, `uvicorn main:app`, a systemd
        unit, a container missing the env var -- served the same fixed fake
        measurements to real customers.
        """
        from py_src.modules.m2_sizing_integration import build_sizing_provider
        from py_src.providers.mediapipe_sizing_provider import MediaPipeSizingProvider

        monkeypatch.delenv("SIZING_PROVIDER", raising=False)
        assert isinstance(build_sizing_provider(), MediaPipeSizingProvider)

    def test_mock_requires_asking_for_it(self, monkeypatch):
        """The demo estimator must never be reachable by omission."""
        from py_src.modules.m2_sizing_integration import (
            DEFAULT_SIZING_PROVIDER, build_sizing_provider,
        )

        assert DEFAULT_SIZING_PROVIDER != "mock"
        monkeypatch.delenv("SIZING_PROVIDER", raising=False)
        assert not isinstance(build_sizing_provider(), MockSizingProvider)

    def test_missing_mediapipe_fails_at_startup_not_on_first_photo(self, monkeypatch):
        """
        The provider loads its model lazily, so an absent dependency would
        otherwise let the server start and fail on the first customer upload.

        sys.modules is poisoned with None rather than patching __import__:
        Python treats a None entry as "this module is known to be unimportable"
        and raises ImportError on the spot, which is precisely the condition
        being simulated, and it survives mediapipe already being imported by an
        earlier test in the same process.
        """
        import sys

        from py_src.modules.m2_sizing_integration import build_sizing_provider

        monkeypatch.setenv("SIZING_PROVIDER", "mediapipe")
        monkeypatch.setitem(sys.modules, "mediapipe", None)
        with pytest.raises(ModuleError, match="mediapipe is not installed"):
            build_sizing_provider()

    def test_that_failure_names_both_ways_out(self, monkeypatch):
        """An error telling you what broke but not what to do is half an error."""
        import sys

        from py_src.modules.m2_sizing_integration import build_sizing_provider

        monkeypatch.setenv("SIZING_PROVIDER", "mediapipe")
        monkeypatch.setitem(sys.modules, "mediapipe", None)
        try:
            build_sizing_provider()
            pytest.fail("expected ModuleError")
        except ModuleError as err:
            assert "pip install" in str(err)
            assert "SIZING_PROVIDER=mock" in str(err)

    def test_honors_env_var(self, monkeypatch):
        from py_src.modules.m2_sizing_integration import build_sizing_provider

        monkeypatch.setenv("SIZING_PROVIDER", "mock")
        assert isinstance(build_sizing_provider(), MockSizingProvider)

    def test_explicit_name_beats_env(self, monkeypatch):
        from py_src.modules.m2_sizing_integration import build_sizing_provider

        monkeypatch.setenv("SIZING_PROVIDER", "nonexistent")
        assert isinstance(build_sizing_provider("mock"), MockSizingProvider)

    def test_unknown_provider_fails_loudly(self, monkeypatch):
        """
        A typo must not silently serve mock measurements -- that would be far
        worse in production than refusing to start.
        """
        from py_src.modules.m2_sizing_integration import build_sizing_provider

        monkeypatch.setenv("SIZING_PROVIDER", "typo-vendor")
        with pytest.raises(ModuleError) as exc:
            build_sizing_provider()
        assert "typo-vendor" in str(exc.value)

    def test_name_is_case_and_whitespace_insensitive(self, monkeypatch):
        from py_src.modules.m2_sizing_integration import build_sizing_provider

        monkeypatch.setenv("SIZING_PROVIDER", "  MOCK  ")
        assert isinstance(build_sizing_provider(), MockSizingProvider)


class TestProviderDisclosure:
    """
    The upload screen's legal notice is rendered from the provider's own
    disclosure, so these are the tests that keep the UI from telling a
    customer something untrue about their photo.
    """

    def test_mock_declares_no_offsite_transmission(self):
        d = MockSizingProvider().disclosure
        assert d["sends_image_offsite"] is False
        assert d["stores_image"] is False

    def test_mock_declares_that_it_does_not_analyse_the_image(self):
        """
        The mock returns fixed values regardless of input, so it must say so --
        this flag is what makes the UI label them as samples instead of
        claiming they were measured from the customer's photo.
        """
        assert MockSizingProvider().disclosure["derives_from_image"] is False

    def test_mock_returns_identical_values_for_different_images(self):
        """Documents the limitation explicitly: a person and a car match."""
        p = MockSizingProvider()
        person = p.extract_from_image(JPEG_BYTES, "image/jpeg", 170.0)
        car = p.extract_from_image(PNG_BYTES + b"\x42" * 2048, "image/png", 170.0)
        assert (person.bust, person.waist, person.hips) == (car.bust, car.waist, car.hips)

    def test_mock_does_not_claim_a_third_party(self):
        """With the mock active, nothing leaves the machine -- the notice
        must not imply a third-party processor is involved."""
        d = MockSizingProvider().disclosure
        assert "third party" not in d["processor_name"].lower()
        assert "third-party" not in d["processor_name"].lower()

    def test_integration_passes_provider_disclosure_through(self, sizing):
        assert sizing.disclosure == MockSizingProvider().disclosure

    def test_provider_without_disclosure_raises(self):
        """A vendor cannot be plugged in without declaring photo handling."""
        from py_src.modules.m2_sizing_integration import SizingProvider

        class Undeclared(SizingProvider):
            def extract_measurements(self, photo_ref, height_cm=None):
                return Measurements(bust=88, waist=70, hips=102, height=165)

        with pytest.raises(NotImplementedError):
            Undeclared().disclosure
