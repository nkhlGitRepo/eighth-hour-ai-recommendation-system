"""
M7 — Fit Checker

Responsibility: Assess product sizing fit for user based on body measurements.
Compares user measurements against product sizing, generates fit confidence scores
per available size, and provides personalized fit guidance.

Guardrails applied:
- InputValidator: validate measurements and product data
- AuditLogger: log all fit checks for audit trail
- ConsentTracker: verify measurement consent before fit checking
"""

from typing import Optional, Dict, List, Any
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.utils.sizing import validate_measurements
from py_src.constants import STANDARD_SIZE_CHART, STANDARD_SIZES
from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.audit_logger import AuditLogger
from py_src.guardrails.consent_tracker import ConsentTracker


class FitChecker:
    """Assess product sizing fit for a user."""

    # Reference to shared constants (imported at module level)
    SIZE_ORDER = STANDARD_SIZES
    STANDARD_SIZE_CHART = STANDARD_SIZE_CHART

    def __init__(self, consent_tracker: Optional[ConsentTracker] = None):
        """
        Initialize fit checker.

        Args:
            consent_tracker: Optional ConsentTracker for consent verification
        """
        self.consent_tracker = consent_tracker or ConsentTracker()
        logger.info("M7 FitChecker initialized")

    def check_fit(
        self,
        user_id: str,
        measurements: Dict[str, float],
        product: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check product fit for user based on measurements.

        Args:
            user_id: User identifier
            measurements: Dict with bust, waist, hips, height (cm)
            product: Product dict with sku, sizes, and optional size_chart
            session_id: Optional session ID for audit logging

        Returns:
            Dict with:
              - fit_scores: {size: confidence (0-1)} for each available size
              - recommended_size: Size with highest confidence
              - fit_notes: List of specific fit guidance
              - confidence: Confidence in recommendation (0-1)

        Raises:
            GuardrailError: If user has not consented to measurements
            ModuleError: If measurements or product data invalid
        """
        # Verify consent
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement processing for fit checking",
                "M7"
            )

        # Validate inputs
        self._validate_measurements(measurements)
        self._validate_product(product)

        # Get size chart for product (or use standard)
        size_chart = product.get("size_chart") or self.STANDARD_SIZE_CHART

        # Calculate fit scores
        fit_scores = self._calculate_fit_scores(
            measurements,
            size_chart,
            product.get("sizes", list(self.SIZE_ORDER))
        )

        # Determine recommended size
        recommended_size = max(
            fit_scores.items(),
            key=lambda x: x[1]
        )[0]

        # Generate fit notes
        fit_notes = self._generate_fit_notes(
            measurements,
            size_chart,
            fit_scores,
            recommended_size
        )

        # Calculate overall confidence
        confidence = fit_scores[recommended_size]

        result = {
            "product_sku": product["sku"],
            "fit_scores": fit_scores,
            "recommended_size": recommended_size,
            "fit_notes": fit_notes,
            "confidence": round(confidence, 2),
        }

        # Audit log
        AuditLogger.log_event(
            "FIT_CHECK_COMPLETED",
            user_id,
            {
                "product_sku": product["sku"],
                "recommended_size": recommended_size,
                "confidence": confidence,
                "session_id": session_id,
            },
        )

        logger.debug(
            "Fit check completed",
            {
                "user_id": user_id,
                "product_sku": product["sku"],
                "recommended_size": recommended_size,
            },
        )

        return result

    def _validate_measurements(self, measurements: Dict[str, float]) -> None:
        """Validate measurement dict has required fields with valid values."""
        try:
            validate_measurements(measurements)
        except ModuleError as err:
            # Re-raise with M7 context
            raise ModuleError(err.message, "M7")

    def _validate_product(self, product: Dict[str, Any]) -> None:
        """Validate product dict has required fields."""
        required = {"sku", "sizes"}
        if not required.issubset(product.keys()):
            missing = required - set(product.keys())
            raise ModuleError(
                f"Product missing required fields: {missing}",
                "M7"
            )

        if not isinstance(product["sizes"], list) or not product["sizes"]:
            raise ModuleError(
                "Product must have non-empty sizes list",
                "M7"
            )

    def _calculate_fit_scores(
        self,
        measurements: Dict[str, float],
        size_chart: Dict[str, Dict[str, float]],
        available_sizes: List[str],
    ) -> Dict[str, float]:
        """
        Calculate fit confidence score (0-1) for each available size.

        Algorithm:
        1. For each size, calculate measurement delta (user vs. standard)
        2. Convert delta to confidence score (closer to 0 = higher confidence)
        3. Average across all measurement dimensions
        """
        fit_scores = {}
        user_bust = measurements["bust"]
        user_waist = measurements["waist"]
        user_hips = measurements["hips"]

        for size in available_sizes:
            if size not in size_chart:
                # Size not in chart, estimate based on neighbors
                fit_scores[size] = 0.5
                continue

            size_measurements = size_chart[size]

            # Calculate deltas (as percentage of standard size)
            bust_delta = abs(user_bust - size_measurements["bust"]) / size_measurements["bust"]
            waist_delta = abs(user_waist - size_measurements["waist"]) / size_measurements["waist"]
            hips_delta = abs(user_hips - size_measurements["hips"]) / size_measurements["hips"]

            # Convert deltas to confidence (0-1)
            # 0 delta = 1.0 confidence; larger deltas = lower confidence
            bust_conf = max(0, 1.0 - bust_delta)
            waist_conf = max(0, 1.0 - waist_delta)
            hips_conf = max(0, 1.0 - hips_delta)

            # Average confidence across dimensions
            avg_confidence = (bust_conf + waist_conf + hips_conf) / 3
            fit_scores[size] = round(avg_confidence, 3)

        return fit_scores

    def _generate_fit_notes(
        self,
        measurements: Dict[str, float],
        size_chart: Dict[str, Dict[str, float]],
        fit_scores: Dict[str, float],
        recommended_size: str,
    ) -> List[str]:
        """Generate specific fit guidance notes."""
        notes = []

        # Get recommended size measurements
        rec_measurements = size_chart.get(recommended_size, {})
        if not rec_measurements:
            return notes

        # Compare measurements to recommended size
        bust_diff = measurements["bust"] - rec_measurements["bust"]
        waist_diff = measurements["waist"] - rec_measurements["waist"]
        hips_diff = measurements["hips"] - rec_measurements["hips"]

        # Generate primary recommendation
        rec_score = fit_scores[recommended_size]
        if rec_score >= 0.9:
            notes.append(f"Size {recommended_size} fits perfectly.")
        elif rec_score >= 0.75:
            notes.append(f"Size {recommended_size} is a good fit.")
        elif rec_score >= 0.6:
            notes.append(f"Size {recommended_size} is acceptable with possible minor adjustments.")
        else:
            notes.append(f"Size {recommended_size} may require alterations for optimal fit.")

        # Add measurement-specific guidance
        if bust_diff < -2:
            notes.append("Recommended size runs large in the bust.")
        elif bust_diff > 2:
            notes.append("Recommended size runs small in the bust.")

        if waist_diff < -2:
            notes.append("Recommended size is loose in the waist.")
        elif waist_diff > 2:
            notes.append("Recommended size is snug in the waist.")

        if hips_diff < -2:
            notes.append("Recommended size is loose in the hips.")
        elif hips_diff > 2:
            notes.append("Recommended size is snug in the hips.")

        # Alternative size suggestions
        # Find next best size
        all_scores = sorted(fit_scores.items(), key=lambda x: x[1], reverse=True)
        if len(all_scores) > 1:
            alternative_size = all_scores[1][0]
            alt_score = all_scores[1][1]
            if alt_score >= 0.7 and alt_score >= rec_score - 0.1:
                notes.append(f"Size {alternative_size} is also a good option ({alt_score:.0%} fit).")

        return notes
