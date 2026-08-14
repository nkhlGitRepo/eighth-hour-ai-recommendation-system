"""
M2 — Sizing Integration

Responsibility: Wrap third-party sizing provider. Extract body measurements from photos.
Adapter pattern allows vendor swaps without touching downstream modules.

Guardrails applied:
- InputValidator: validate measurements after extraction
- AuditLogger: log measurement events
"""

from abc import ABC, abstractmethod
from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.audit_logger import AuditLogger
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError
import time


class Measurements:
    """Normalized body measurements from photo or manual entry."""

    def __init__(
        self,
        bust: float,
        waist: float,
        hips: float,
        height: float,
        shoulder: float = None,
        inseam: float = None,
        unit: str = "cm",
        confidence_scores: dict = None,
        provider: str = "mock",
        provider_version: str = "1.0",
    ):
        self.bust = bust
        self.waist = waist
        self.hips = hips
        self.height = height
        self.shoulder = shoulder
        self.inseam = inseam
        self.unit = unit
        self.confidence_scores = confidence_scores or {
            "bust": 1.0,
            "waist": 1.0,
            "hips": 1.0,
            "shoulder": 0.9,
        }
        self.provider = provider
        self.provider_version = provider_version
        self.extracted_at = time.time()

    def to_dict(self):
        """Convert to dict for API responses."""
        return {
            "bust": self.bust,
            "waist": self.waist,
            "hips": self.hips,
            "height": self.height,
            "shoulder": self.shoulder,
            "inseam": self.inseam,
            "unit": self.unit,
            "confidence_scores": self.confidence_scores,
            "provider": self.provider,
            "provider_version": self.provider_version,
            "extracted_at": self.extracted_at,
        }

    def min_confidence(self):
        """Return minimum confidence score across all measurements."""
        if not self.confidence_scores:
            return 1.0
        return min(self.confidence_scores.values())

    def low_confidence_fields(self, threshold: float = 0.75):
        """Return list of fields below confidence threshold."""
        return [
            field
            for field, score in self.confidence_scores.items()
            if score < threshold
        ]


class SizingProvider(ABC):
    """Abstract adapter for any third-party sizing vendor."""

    @abstractmethod
    def extract_measurements(
        self, photo_ref: str, height_cm: float = None
    ) -> Measurements:
        """
        Extract measurements from a photo reference.

        Args:
            photo_ref: Secure reference (URI/object ID, not raw bytes)
            height_cm: Height in cm if available (optional)

        Returns:
            Measurements object with confidence scores

        Raises:
            ModuleError: If extraction fails or timeout
        """
        pass

    def extract_from_image(
        self, image_bytes: bytes, content_type: str, height_cm: float = None,
        usual_top_size: str = None, usual_bottom_size: str = None,
    ) -> Measurements:
        """
        Extract measurements from raw uploaded image bytes.

        This is the path used by POST /intake/photo-measure, where the
        customer uploads a photo that is never persisted -- the bytes are
        held in memory, measured, and discarded. Deliberately NOT an
        @abstractmethod: a provider that only supports the photo_ref flow
        above stays valid, and existing implementations don't break.

        Args:
            image_bytes: Raw image data (already validated by the caller)
            content_type: Validated MIME type, e.g. "image/jpeg"
            height_cm: Customer-supplied height, used as the scale reference
            usual_top_size: Optional size the customer normally wears on top
                (e.g. "M"). Anchors the bust.
            usual_bottom_size: Optional size they normally wear on the bottom.
                Anchors the waist and hips. Kept separate from the top size
                because many people are genuinely different sizes above and
                below, and measured against real ground truth splitting them cut
                the hip error from 4.2cm to 1.8cm.

                Both are strong population anchors -- far more accurate than the
                image alone -- so providers should use them to steady an
                estimate. Ignore them if your provider is accurate without.

        Returns:
            Measurements object with confidence scores

        Raises:
            ModuleError: If this provider has no direct-upload support, or
                extraction fails.
        """
        raise ModuleError(
            f"{type(self).__name__} does not support direct image upload",
            "M2",
        )

    @property
    def disclosure(self) -> dict:
        """
        Facts about how THIS provider handles a customer's photo, used to
        render the legal notice on the upload screen.

        The notice is generated from this rather than hardcoded in the HTML
        so it can never drift from what the code actually does -- e.g.
        claiming a third party processes the image while the mock provider
        is active would be a false statement to the customer, and a real
        vendor must not go live without disclosing that images leave the
        machine.

        Required keys (enforced by tests/test_sizing_provider_contract.py):
            processor_name: Who actually processes the image, in customer-
                facing language.
            sends_image_offsite: True if the image leaves this server.
            stores_image: True if the image is retained anywhere.
            derives_from_image: True if the returned measurements are actually
                computed from the uploaded image. MockSizingProvider sets this
                False -- it returns fixed sample values and ignores the photo
                entirely, so any image (a person, a car, a blank square)
                produces identical numbers. The UI uses this to decide whether
                to present the result as a real measurement or as clearly
                labelled placeholder data; a provider that returns invented
                numbers while claiming True would be actively misleading
                customers about their own body.
            retention: Plain-language retention/destruction statement.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must declare a disclosure dict"
        )


class MockSizingProvider(SizingProvider):
    """Mock provider for development/testing. Returns deterministic measurements."""

    def __init__(self):
        logger.info("MockSizingProvider initialized")

    def _deterministic_measurements(self, height_cm: float) -> Measurements:
        """
        The single definition of this provider's fixed output, shared by both
        entry points so the photo_ref path and the image-upload path can
        never drift apart. height_cm is passed through as the scale
        reference (it's the one input the mock actually honors).
        """
        return Measurements(
            bust=88.0,
            waist=70.0,
            hips=102.0,
            shoulder=39.0,
            height=height_cm,
            inseam=78.0,
            unit="cm",
            confidence_scores={
                "bust": 0.95,
                "waist": 0.92,
                "hips": 0.90,
                "shoulder": 0.85,
                "inseam": 0.88,
            },
            provider="mock",
            provider_version="1.0",
        )

    def extract_measurements(
        self, photo_ref: str, height_cm: float = 165.0
    ) -> Measurements:
        """
        Return deterministic measurements for testing.
        In Phase 2: swap for real vendor (SizeStream, MySize, etc.)
        """
        if not isinstance(photo_ref, str) or len(photo_ref) == 0:
            raise ModuleError("Invalid photo reference", "M2")

        logger.debug(
            "M2 mock extraction",
            {"photo_ref": photo_ref, "height_cm": height_cm},
        )

        return self._deterministic_measurements(height_cm)

    def extract_from_image(
        self, image_bytes: bytes, content_type: str, height_cm: float = 165.0,
        usual_top_size: str = None, usual_bottom_size: str = None,
    ) -> Measurements:
        """
        Deterministic stand-in for a real vendor's image analysis. The image
        content is deliberately NOT inspected -- this provider exists so the
        whole flow (upload, validation, consent, profile generation, UI) can
        be built and tested without a vendor account. Bytes are still checked
        for presence so the plumbing is genuinely exercised.
        """
        if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
            raise ModuleError("Empty image upload", "M2")

        if height_cm is None:
            height_cm = 165.0

        logger.debug(
            "M2 mock extraction from uploaded image",
            {"content_type": content_type, "bytes": len(image_bytes), "height_cm": height_cm},
        )

        return self._deterministic_measurements(height_cm)

    @property
    def disclosure(self) -> dict:
        """No third party, no retention, and -- critically -- no analysis."""
        return {
            "processor_name": "Eighth Hour demo estimator (runs on this server)",
            "sends_image_offsite": False,
            "stores_image": False,
            # THE important one for this provider. It does not look at the
            # image at all, so every photo yields the same numbers. Claiming
            # otherwise in the UI would be a straightforwardly false statement
            # to the customer, so the UI reads this flag and labels the values
            # as samples instead of measurements. A real vendor sets it True
            # and the demo warning disappears on its own.
            "derives_from_image": False,
            # Worded to be precisely true rather than maximally reassuring:
            # a web server unavoidably buffers an upload while the request is
            # being handled, so this claims non-retention (which we control
            # and enforce) rather than "never touches disk" (which we don't).
            "retention": (
                "Your photo is not saved to your account or our database. It exists "
                "only for the few seconds it is handled, and is discarded as soon as "
                "the request finishes. Only the resulting measurements are kept."
            ),
        }


class SizingIntegration:
    """Unified interface to sizing providers."""

    def __init__(self, provider: SizingProvider = None):
        self.provider = provider or MockSizingProvider()

    @property
    def disclosure(self) -> dict:
        """Pass through the active provider's photo-handling disclosure."""
        return self.provider.disclosure

    def extract_from_image(
        self,
        image_bytes: bytes,
        content_type: str,
        height_cm: float = None,
        user_id: str = None,
        usual_top_size: str = None,
        usual_bottom_size: str = None,
    ) -> Measurements:
        """
        Extract measurements from raw uploaded image bytes, with the same
        guardrails the photo_ref path applies (validate the result, audit-log
        the event). Mirrors extract_measurements() deliberately so both paths
        enforce identical invariants.

        The bytes are never persisted or logged -- only their length and
        content type appear in logs.

        Args:
            image_bytes: Raw image data (caller must have validated it)
            content_type: Validated MIME type
            height_cm: Height in cm, used as the scale reference
            user_id: User ID for audit logging

        Returns:
            Measurements object

        Raises:
            ModuleError: If extraction fails or the result is invalid
        """
        try:
            if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
                raise ModuleError("Empty image upload", "M2")

            measurements = self.provider.extract_from_image(
                image_bytes, content_type, height_cm,
                usual_top_size, usual_bottom_size,
            )

            validation = InputValidator.validate_measurements(measurements.to_dict())
            if not validation["valid"]:
                raise ModuleError(
                    f"Extracted measurements invalid: {', '.join(validation['errors'])}",
                    "M2",
                )

            logger.debug(
                "M2 extraction from upload successful",
                {
                    "provider": measurements.provider,
                    "min_confidence": measurements.min_confidence(),
                },
            )

            if user_id:
                AuditLogger.log_event(
                    "MEASUREMENTS_EXTRACTED",
                    user_id,
                    {
                        "provider": measurements.provider,
                        "source": "image_upload",
                        "content_type": content_type,
                        "image_bytes": len(image_bytes),
                        "min_confidence": round(measurements.min_confidence(), 2),
                        "low_confidence_fields": measurements.low_confidence_fields(),
                    },
                )

            return measurements

        except Exception as err:
            logger.error("M2 extraction from upload failed", err)
            raise

    def extract_measurements(
        self,
        photo_ref: str,
        height_cm: float = None,
        user_id: str = None,
    ) -> Measurements:
        """
        Extract measurements from photo with guardrails.

        Args:
            photo_ref: Secure reference to photo
            height_cm: Height in cm (optional)
            user_id: User ID for audit logging

        Returns:
            Measurements object

        Raises:
            ModuleError: If extraction fails
        """
        try:
            if not isinstance(photo_ref, str) or len(photo_ref) == 0:
                raise ModuleError("Invalid photo reference", "M2")

            measurements = self.provider.extract_measurements(photo_ref, height_cm)

            # Validate extracted measurements
            validation = InputValidator.validate_measurements(measurements.to_dict())
            if not validation["valid"]:
                raise ModuleError(
                    f"Extracted measurements invalid: {', '.join(validation['errors'])}",
                    "M2",
                )

            logger.debug(
                "M2 extraction successful",
                {
                    "provider": measurements.provider,
                    "min_confidence": measurements.min_confidence(),
                },
            )

            # Audit: Log measurement extraction if user context provided
            if user_id:
                AuditLogger.log_event(
                    "MEASUREMENTS_EXTRACTED",
                    user_id,
                    {
                        "provider": measurements.provider,
                        "min_confidence": round(measurements.min_confidence(), 2),
                        "low_confidence_fields": measurements.low_confidence_fields(),
                    },
                )

            return measurements

        except Exception as err:
            logger.error("M2 extraction failed", err)
            raise


# =========================================================================
# Provider registry -- the entire swap surface for a real vendor
# =========================================================================
#
# To plug in a real sizing API:
#   1. Write a class implementing SizingProvider (extract_from_image is the
#      method the upload flow calls; declare the `disclosure` property so the
#      UI can tell customers truthfully how their photo is handled).
#   2. Add one entry to SIZING_PROVIDERS below.
#   3. Set SIZING_PROVIDER=<your key> in the environment.
# Nothing else in the app changes -- see README_PYTHON.md for the full
# walkthrough, and tests/test_sizing_provider_contract.py to verify your
# implementation satisfies the invariants this codebase relies on
# (centimetres, valid ranges, populated provenance, declared disclosure).

def _mediapipe_provider():
    """
    Imported lazily so the mock path never pays mediapipe's import cost (and
    so the app still starts if mediapipe isn't installed).
    """
    from py_src.providers.mediapipe_sizing_provider import MediaPipeSizingProvider

    return MediaPipeSizingProvider()


SIZING_PROVIDERS = {
    "mock": MockSizingProvider,
    # Free, local, genuinely analyses the photo. See
    # py_src/providers/mediapipe_sizing_provider.py.
    "mediapipe": _mediapipe_provider,
}

DEFAULT_SIZING_PROVIDER = "mock"


def build_sizing_provider(name: str = None) -> SizingProvider:
    """
    Construct the configured sizing provider.

    Reads SIZING_PROVIDER from the environment when `name` isn't given,
    defaulting to the mock so a machine with no configuration behaves
    exactly as it always has. An unrecognized name raises immediately at
    startup rather than silently falling back -- a typo that quietly served
    mock measurements in production would be far worse than a hard failure.
    """
    import os

    key = (name or os.environ.get("SIZING_PROVIDER") or DEFAULT_SIZING_PROVIDER).strip().lower()

    if key not in SIZING_PROVIDERS:
        raise ModuleError(
            f"Unknown SIZING_PROVIDER '{key}'. Available: {sorted(SIZING_PROVIDERS)}",
            "M2",
        )

    logger.info("Sizing provider selected", {"provider": key})
    return SIZING_PROVIDERS[key]()
