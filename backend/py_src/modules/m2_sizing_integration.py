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
        self.shoulder = shoulder or hips
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


class MockSizingProvider(SizingProvider):
    """Mock provider for development/testing. Returns deterministic measurements."""

    def __init__(self):
        logger.info("MockSizingProvider initialized")

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


class SizingIntegration:
    """Unified interface to sizing providers."""

    def __init__(self, provider: SizingProvider = None):
        self.provider = provider or MockSizingProvider()

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
