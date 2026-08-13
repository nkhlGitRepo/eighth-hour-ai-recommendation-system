"""
M7 — Fit Checker

Responsibility: Assess product sizing fit for user based on body measurements.
Compares user measurements against product sizing, generates fit confidence scores
per available size, and provides personalized fit guidance.

Guardrails applied:
- Shared sizing validation (validate_measurements): validate measurements and product data
- AuditLogger: log all fit checks for audit trail
- ConsentTracker: verify measurement consent before fit checking
"""

from typing import Optional, Dict, List, Any
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.utils.sizing import validate_measurements, extract_physical_measurements
from py_src.constants import (
    STANDARD_SIZE_CHART,
    STANDARD_SIZES,
    SIZE_STEP_CM,
    FIT_SCORE_TOLERANCE_SIZE_STEPS,
    FIT_SCORE_DIMENSION_WEIGHTS,
    FIT_SCORE_DEFAULT_WEIGHTS,
    FIT_NOTE_RELEVANT_DIMENSIONS,
    FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE,
    FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM,
    SIZE_BOUNDARIES,
    WAIST_SIZE_BOUNDARIES,
    HIP_SIZE_BOUNDARIES,
)
from py_src.guardrails.audit_logger import AuditLogger
from py_src.guardrails.consent_tracker import ConsentTracker


class FitChecker:
    """Assess product sizing fit for a user."""

    # Reference to shared constants (imported at module level)
    SIZE_ORDER = STANDARD_SIZES
    STANDARD_SIZE_CHART = STANDARD_SIZE_CHART
    DIMENSION_BOUNDARIES = {
        "bust": SIZE_BOUNDARIES,
        "waist": WAIST_SIZE_BOUNDARIES,
        "hips": HIP_SIZE_BOUNDARIES,
    }

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
        known_size: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Check product fit for user based on measurements.

        Args:
            user_id: User identifier
            measurements: Dict with bust, waist, hips, height (cm)
            product: Product dict with sku, sizes, and optional size_chart
            session_id: Optional session ID for audit logging
            known_size: When given, this size is used as recommended_size
                instead of the argmax of fit_scores -- pass M3's own
                size_recommendation_by_category value for this product's
                category here so the two modules can never disagree on
                which size to show the customer (M3 picks the category size
                off a single measurement -- bust for tops, hips for
                bottoms -- while fit_scores below blends bust+waist+hips
                equally for every category, so its argmax can legitimately
                point at a different size). Ignored if not one of this
                product's available sizes.

        Returns:
            Dict with:
              - fit_scores: {size: confidence (0-1)} for each available size
              - recommended_size: Size with highest confidence (or
                known_size, when given and available)
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

        # Callers may pass a full Measurements.to_dict() payload (unit,
        # confidence_scores, provider, ...) rather than a clean measurements
        # dict -- strip it down before validating/using it.
        measurements = extract_physical_measurements(measurements)

        # Validate inputs
        self._validate_measurements(measurements)
        self._validate_product(product)

        # Get size chart for product (or use standard). A custom chart only
        # gives a single reference point per size, not the real boundary
        # ranges (those are only defined for the standard chart, in
        # constants.py) -- boundary-aware scoring below is only possible
        # when using the standard chart.
        custom_chart = product.get("size_chart")
        size_chart = custom_chart or self.STANDARD_SIZE_CHART
        use_boundaries = not custom_chart

        # Calculate fit scores
        dimension_weights = FIT_SCORE_DIMENSION_WEIGHTS.get(
            product.get("category"), FIT_SCORE_DEFAULT_WEIGHTS
        )
        fit_scores = self._calculate_fit_scores(
            measurements,
            size_chart,
            product.get("sizes", list(self.SIZE_ORDER)),
            dimension_weights,
            use_boundaries,
        )

        # Determine recommended size. Prefer known_size (M3's own
        # category-specific answer) when it's actually one of this
        # product's sizes; otherwise fall back to the argmax of fit_scores.
        #
        # Only trust known_size when use_boundaries is True: it's M3's
        # answer from the STANDARD body-measurement boundaries
        # (constants.SIZE_BOUNDARIES etc.), which is exactly what
        # guarantees it can never be outscored under boundary-aware
        # scoring. A custom per-product size_chart has no relationship to
        # those boundaries at all -- trusting known_size there would
        # reintroduce the exact bug this whole scoring model fixes
        # (recommending a size that a completely unrelated size scores
        # higher than), just for a different reason.
        if known_size and use_boundaries and known_size in fit_scores:
            recommended_size = known_size
        else:
            recommended_size = max(
                fit_scores.items(),
                key=lambda x: x[1]
            )[0]

        # Generate fit notes. Deliberately NOT dimension_weights (that's
        # the SIZE/SCORE calculation above, unaffected by this) -- see
        # FIT_NOTE_RELEVANT_DIMENSIONS for why note guidance uses a wider
        # set of relevant dimensions for whole-body categories.
        note_dimensions = FIT_NOTE_RELEVANT_DIMENSIONS.get(
            product.get("category"), {"bust", "waist", "hips"}
        )
        fit_notes = self._generate_fit_notes(
            measurements,
            size_chart,
            fit_scores,
            recommended_size,
            note_dimensions,
        )

        # Calculate overall confidence -- already rounded to 2 decimals in
        # _calculate_fit_scores, so this is guaranteed to equal
        # fit_scores[recommended_size] exactly.
        confidence = fit_scores[recommended_size]

        result = {
            "product_sku": product["sku"],
            "fit_scores": fit_scores,
            "recommended_size": recommended_size,
            "fit_notes": fit_notes,
            "confidence": confidence,
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

    def _dimension_confidence(self, actual: float, reference: float, step_cm: float) -> float:
        """
        Confidence (0-1) that a single measurement matches a candidate
        size's single reference POINT for one dimension. Used only as a
        fallback for custom per-product size charts, which give a single
        cm value per size rather than a real boundary range -- there's no
        "inside this size's range" to check against, just distance from a
        point. See _dimension_confidence_from_boundary for the standard
        chart's more accurate range-aware version.

        Expresses the raw cm difference in units of "how many sizes off"
        (scaled by step_cm, the typical cm change between adjacent sizes
        for this dimension -- see constants.SIZE_STEP_CM) rather than as a
        fraction of the candidate size's own reference value. That older
        approach divided by whichever size was currently being scored, so
        the exact same real-world miss scored as a SMALLER error against a
        bigger size purely because it divided by a bigger number --
        mechanically biasing every comparison toward larger sizes.

        Decays linearly to 0 at FIT_SCORE_TOLERANCE_SIZE_STEPS sizes off.
        """
        if step_cm <= 0:
            return 1.0 if actual == reference else 0.0
        sizes_off = abs(actual - reference) / step_cm
        return max(0.0, 1.0 - sizes_off / FIT_SCORE_TOLERANCE_SIZE_STEPS)

    def _dimension_confidence_from_boundary(
        self, actual: float, lo: float, hi: float, step_cm: float, cushion_cm: float
    ) -> float:
        """
        Confidence (0-1) that a single measurement falls within a
        candidate size's real boundary range [lo, hi) for one dimension.

        Whichever size's range actually contains the measurement is
        guaranteed to score >= FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE, and
        every OTHER size (whose range, by definition, does NOT contain it,
        since ranges never overlap) scores <= that same floor -- so the
        correct size can never be strictly outscored, only tied at an
        exact boundary crossing (a measurement exactly on a boundary
        really is an equally good fit for both neighboring sizes).

        Within that guarantee, the score still varies meaningfully instead
        of reading a flat 100% everywhere in range:
          - More than `cushion_cm` from BOTH edges ("solidly" in this
            size): flat 1.0. This is what stops a wide, open-ended bucket
            like XXL (e.g. hips 114-150cm) from reading as a lower-
            confidence fit just because it's far from an arbitrary center
            point -- only measurements actually near a real boundary are
            affected.
          - Within `cushion_cm` of an edge: ramps from 1.0 down to
            FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE right at the edge, so a
            customer on the fence between two sizes sees that reflected in
            the number.
          - Outside the range: decays from FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE
            at the boundary (matching the in-range formula's value there,
            so the two meet continuously) down to 0 at
            FIT_SCORE_TOLERANCE_SIZE_STEPS sizes off.
        """
        floor = FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE

        if lo <= actual < hi:
            distance_from_nearest_edge = min(actual - lo, hi - actual)
            if cushion_cm <= 0 or distance_from_nearest_edge >= cushion_cm:
                return 1.0
            return floor + (1.0 - floor) * (distance_from_nearest_edge / cushion_cm)

        distance = (lo - actual) if actual < lo else (actual - hi)
        if step_cm <= 0:
            return 0.0
        sizes_off = distance / step_cm
        return floor * max(0.0, 1.0 - sizes_off / FIT_SCORE_TOLERANCE_SIZE_STEPS)

    def _calculate_fit_scores(
        self,
        measurements: Dict[str, float],
        size_chart: Dict[str, Dict[str, float]],
        available_sizes: List[str],
        dimension_weights: Dict[str, float],
        use_boundaries: bool,
    ) -> Dict[str, float]:
        """
        Calculate fit confidence score (0-1) for each available size.

        Algorithm:
        1. For each size, score each measurement against that size's real
           boundary range (use_boundaries=True, the standard chart -- see
           _dimension_confidence_from_boundary) or against a single
           reference point (use_boundaries=False, a custom per-product
           chart -- see _dimension_confidence)
        2. Combine across dimensions using dimension_weights -- e.g. bust
           alone for a Vest, since that's the only measurement that
           actually determines how a vest fits (see
           constants.FIT_SCORE_DIMENSION_WEIGHTS)
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

            if use_boundaries and all(size in self.DIMENSION_BOUNDARIES[d] for d in ("bust", "waist", "hips")):
                bust_conf = self._dimension_confidence_from_boundary(
                    user_bust, *self.DIMENSION_BOUNDARIES["bust"][size],
                    SIZE_STEP_CM["bust"], FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM["bust"]
                )
                waist_conf = self._dimension_confidence_from_boundary(
                    user_waist, *self.DIMENSION_BOUNDARIES["waist"][size],
                    SIZE_STEP_CM["waist"], FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM["waist"]
                )
                hips_conf = self._dimension_confidence_from_boundary(
                    user_hips, *self.DIMENSION_BOUNDARIES["hips"][size],
                    SIZE_STEP_CM["hips"], FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM["hips"]
                )
            else:
                bust_conf = self._dimension_confidence(user_bust, size_measurements["bust"], SIZE_STEP_CM["bust"])
                waist_conf = self._dimension_confidence(user_waist, size_measurements["waist"], SIZE_STEP_CM["waist"])
                hips_conf = self._dimension_confidence(user_hips, size_measurements["hips"], SIZE_STEP_CM["hips"])

            # Weighted combination across dimensions. Rounded to 2 decimals
            # (not 3) so this always matches check_fit()'s "confidence"
            # field, which is this same value re-exposed at the top level --
            # a 3-vs-2-decimal mismatch would make them silently disagree.
            weighted_confidence = (
                bust_conf * dimension_weights["bust"]
                + waist_conf * dimension_weights["waist"]
                + hips_conf * dimension_weights["hips"]
            )
            fit_scores[size] = round(weighted_confidence, 2)

        return fit_scores

    def _generate_fit_notes(
        self,
        measurements: Dict[str, float],
        size_chart: Dict[str, Dict[str, float]],
        fit_scores: Dict[str, float],
        recommended_size: str,
        note_dimensions: set,
    ) -> List[str]:
        """
        Generate specific fit guidance notes.

        note_dimensions (see FIT_NOTE_RELEVANT_DIMENSIONS) gates which
        measurement-specific notes below can fire, based on which part of
        the body this category actually covers -- upper-body-only for
        Tops/Vests (bust), lower-body-only for Skirts/Trousers (waist,
        hips), and everything for whole-body categories like Dresses/
        Co-ord Sets. A note about a dimension the garment doesn't even
        cover (e.g. "runs small in the bust" for a skirt) would be
        actively misleading, not just noise.
        """
        notes = []

        # Get recommended size measurements
        rec_measurements = size_chart.get(recommended_size, {})
        if not rec_measurements:
            return notes

        # Compare measurements to recommended size
        bust_diff = measurements["bust"] - rec_measurements["bust"]
        waist_diff = measurements["waist"] - rec_measurements["waist"]
        hips_diff = measurements["hips"] - rec_measurements["hips"]

        # Generate primary recommendation. Under boundary-aware scoring
        # (see _dimension_confidence_from_boundary), the recommended size's
        # own score can never fall below FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE
        # (0.85) -- that's the whole point of the guarantee it provides.
        # The thresholds below are calibrated to that: 0.95 splits the
        # boundary-edge ramp roughly in half, so "is a good fit" actually
        # triggers for a meaningful stretch near a boundary (not just the
        # last sliver right at the edge), rather than "fits perfectly"
        # dominating almost the entire size. The bottom two tiers stay
        # reachable for the rarer paths without that guarantee (a custom
        # per-product size chart, or a category with no single driving
        # measurement, like Co-ord Sets' original blended fallback).
        rec_score = fit_scores[recommended_size]
        if rec_score >= 0.95:
            notes.append(f"Size {recommended_size} fits perfectly.")
        elif rec_score >= 0.85:
            notes.append(f"Size {recommended_size} is a good fit.")
        elif rec_score >= 0.65:
            notes.append(f"Size {recommended_size} is acceptable with possible minor adjustments.")
        else:
            notes.append(f"Size {recommended_size} may require alterations for optimal fit.")

        # Add measurement-specific guidance -- only for dimensions that
        # actually matter for this category (see docstring above).
        if "bust" in note_dimensions:
            if bust_diff < -2:
                notes.append("Recommended size runs large in the bust.")
            elif bust_diff > 2:
                notes.append("Recommended size runs small in the bust.")

        if "waist" in note_dimensions:
            if waist_diff < -2:
                notes.append("Recommended size is loose in the waist.")
            elif waist_diff > 2:
                notes.append("Recommended size is snug in the waist.")

        if "hips" in note_dimensions:
            if hips_diff < -2:
                notes.append("Recommended size is loose in the hips.")
            elif hips_diff > 2:
                notes.append("Recommended size is snug in the hips.")

        # Alternative size suggestion: the best-scoring size other than
        # recommended_size, capped at recommended_size's own score (a
        # neighbor scoring HIGHER than the recommendation would read as
        # self-contradictory -- why recommend the lower-scored size at
        # all? -- this can still happen when recommended_size came from
        # known_size rather than the argmax; see check_fit). No explicit
        # adjacency restriction: with _dimension_confidence's fixed
        # per-size-step scaling, confidence now decays consistently as you
        # move away from the true best match, so for a body whose
        # proportions are roughly consistent across bust/waist/hips, the
        # next-best size is naturally the adjacent one anyway. For a body
        # whose proportions genuinely don't agree across dimensions, the
        # honest answer really can be a non-adjacent size, and hiding that
        # wouldn't help the customer.
        other_scores = sorted(
            (
                item for item in fit_scores.items()
                if item[0] != recommended_size and item[1] <= rec_score
            ),
            key=lambda x: x[1],
            reverse=True,
        )
        if other_scores:
            alternative_size, alt_score = other_scores[0]
            if alt_score >= 0.7 and alt_score >= rec_score - 0.1:
                notes.append(f"Size {alternative_size} is also a good option ({alt_score:.0%} fit).")

        return notes
