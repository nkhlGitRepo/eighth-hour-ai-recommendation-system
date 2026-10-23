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

import math
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
    TOP_SIZE_DIMENSION_BY_SHAPE,
    DEFAULT_TOP_SIZE_DIMENSION,
    FIT_SCORE_DEFAULT_WEIGHTS,
    FIT_NOTE_RELEVANT_DIMENSIONS,
    FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE,
    FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM,
    SIZE_BOUNDARIES,
    WAIST_SIZE_BOUNDARIES,
    HIP_SIZE_BOUNDARIES,
    GARMENT_LENGTH_CHART_IN,
    COORD_LENGTH_CHART_ORDER,
    LENGTH_CHART_REFERENCE_HEIGHT_CM,
    LENGTH_NOTE_SAME_AS_SHOWN_CM,
    SIZE_CHART_SOURCE,
    CATEGORY_ZONE,
    SILHOUETTE_TIP_ORDER,
    STYLING_TIPS,
    LOW_GIVE_FABRICS,
    STRETCH_FABRICS,
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
        shape_class: Optional[str] = None,
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
            shape_class: M3's shape class. Some shapes are sized on a
                different measurement for the top half (apple: the waist);
                passing it scores those categories on the same measurement
                M3 sized them on, so the highest "% fit" can't contradict
                known_size.

        Returns:
            Dict with:
              - fit_scores: {size: confidence (0-1)} for each available size
              - recommended_size: Size with highest confidence (or
                known_size, when given and available)
              - fit_notes: List of specific fit guidance, led by the
                closest-available line when that applies
              - confidence: Confidence in recommendation (0-1)
              - customer_size, closest_available: see size_advice

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

        advice = self.size_advice(measurements, product, known_size, shape_class)
        size_chart = advice["size_chart"]
        fit_scores = advice["fit_scores"]
        recommended_size = advice["recommended_size"]

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
        if advice["closest_available"]:
            fit_notes.insert(0, self.closest_available_note(
                advice["customer_size"], list(fit_scores), recommended_size
            ))

        # Where the hem will actually land on this customer. Sized on
        # circumference, so it is independent of everything above -- a garment
        # can be a flawless fit through the body and still sit at a different
        # point on the leg than the photograph shows.
        length_note = self._generate_length_note(measurements.get("height"), product)
        if length_note:
            fit_notes.append(length_note)

        fit_by_area, tips = self._fit_advice(
            measurements, product, recommended_size, note_dimensions, shape_class, advice["closest_available"]
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
            "customer_size": advice["customer_size"],
            "closest_available": advice["closest_available"],
            "fit_by_area": fit_by_area,
            "tips": tips,
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

    def size_advice(
        self,
        measurements: Dict[str, float],
        product: Dict[str, Any],
        known_size: Optional[str] = None,
        shape_class: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Which size of this product to recommend -- the sizing half of
        check_fit, without its consent check, audit entry or fit notes, so a
        caller that has already cleared consent (M5's recommendation cards)
        gets exactly the answer the product page will give.

        Args: as check_fit.

        Returns:
            Dict with:
              - fit_scores, recommended_size: as check_fit
              - customer_size: her own size for this product's category
                (known_size, or the best size on the full standard chart);
                None with a custom per-product chart, whose labels needn't
                be the standard sizes
              - closest_available: True when the product doesn't come in
                customer_size, so recommended_size is only the closest fit
              - size_chart: the chart the scores were computed against
        """
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
        # Top-half categories are scored on whatever M3 sized them on for
        # this shape (see TOP_SIZE_DIMENSION_BY_SHAPE).
        top_dimension = TOP_SIZE_DIMENSION_BY_SHAPE.get(shape_class, DEFAULT_TOP_SIZE_DIMENSION)
        if dimension_weights.get(DEFAULT_TOP_SIZE_DIMENSION) == 1.0 and top_dimension != DEFAULT_TOP_SIZE_DIMENSION:
            dimension_weights = {"bust": 0.0, "waist": 0.0, "hips": 0.0, top_dimension: 1.0}
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
        #
        # When the product doesn't come in her size at all (an XXS customer,
        # an XS-L piece), the recommendation is the stocked size that fits
        # best, and closest_available tells the caller to say so rather than
        # present it as her size.
        customer_size = self._customer_size(
            measurements, dimension_weights, known_size, use_boundaries
        )
        closest_available = customer_size is not None and customer_size not in fit_scores
        if known_size and use_boundaries and known_size in fit_scores:
            recommended_size = known_size
        elif closest_available:
            recommended_size = self._closest_stocked_size(fit_scores, customer_size)
        else:
            recommended_size = max(
                fit_scores.items(),
                key=lambda x: x[1]
            )[0]

        return {
            "fit_scores": fit_scores,
            "recommended_size": recommended_size,
            "customer_size": customer_size,
            "closest_available": closest_available,
            "size_chart": size_chart,
        }

    def _customer_size(self, measurements, dimension_weights, known_size, use_boundaries):
        """
        Her size for a category, on the standard chart: M3's answer when the
        caller passes it, otherwise the best-scoring size across the WHOLE
        chart (not just the sizes this product comes in) -- which is what
        reveals that a product doesn't come in her size.
        """
        if not use_boundaries:
            return None
        if known_size in self.SIZE_ORDER:
            return known_size
        every_size = self._calculate_fit_scores(
            measurements, self.STANDARD_SIZE_CHART, list(self.SIZE_ORDER),
            dimension_weights, True,
        )
        return max(every_size.items(), key=lambda x: x[1])[0]

    def _closest_stocked_size(self, fit_scores, customer_size):
        """
        The best-fitting size the product comes in. Ties (two stocked sizes
        scoring the same) go to the one nearer her own size on the chart.
        """
        order = {size: index for index, size in enumerate(self.SIZE_ORDER)}
        target = order[customer_size]
        return max(
            fit_scores,
            key=lambda size: (fit_scores[size], -abs(order.get(size, target) - target)),
        )

    def closest_available_note(self, customer_size, stocked_sizes, recommended_size):
        """
        What to tell a customer whose size this piece doesn't come in: her
        actual size, the sizes it does come in, and that the recommendation
        is the closest available -- not her size.
        """
        return (
            f"Your size is {customer_size}. This piece comes in "
            f"{self._describe_sizes(stocked_sizes)}, so {recommended_size} is "
            f"the closest fit available."
        )

    def _describe_sizes(self, sizes):
        """'XS–L' for an unbroken run, 'XS, S and L' with a gap, 'M only' for one."""
        ordered = sorted(sizes, key=lambda s: self.SIZE_ORDER.index(s) if s in self.SIZE_ORDER else len(self.SIZE_ORDER))
        if len(ordered) == 1:
            return f"{ordered[0]} only"
        positions = [self.SIZE_ORDER.index(s) for s in ordered if s in self.SIZE_ORDER]
        if len(positions) == len(ordered) and positions == list(range(positions[0], positions[-1] + 1)):
            return f"{ordered[0]}–{ordered[-1]}"
        return ", ".join(ordered[:-1]) + f" and {ordered[-1]}"


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

    # Where each length class puts a hem on the body, in words. Keyed by
    # category because the same class name means different things depending on
    # the garment: "Cropped" is a midriff-length top but an above-the-ankle
    # trouser, and "Short" is a waist-length vest but a pair of shorts. A single
    # shared table produced "this will sit cropped above the waist on you" about
    # a pair of trousers.
    # Bare landmarks, with no leading preposition: the sentence supplies "at",
    # "between ... and ...", "above" or "below" depending on where the hem lands.
    # Baking "at" into the phrase produced "sit between at mid-calf and at full
    # length".
    _LANDMARK_PHRASES = {
        "Skirts": {
            "Mini": "the upper thigh", "Short": "the upper thigh",
            "Knee": "the knee",
            "Midi": "mid-calf", "Calf": "mid-calf",
            "Maxi": "full length", "Full": "full length",
        },
        "Trousers": {
            "Short": "the upper thigh",
            "Capri": "mid-calf",
            # "mid-shin", not "the lower calf": the sentence also uses "lower"
            # as a direction, and "Cut to sit at the lower calf ... expect it
            # about 3cm higher" makes a reader parse the same word two ways.
            "Cropped": "mid-shin",
            "Ankle": "the ankle",
            "Full": "full length",
        },
        "Dresses": {
            "Mini": "the upper thigh", "Short": "the upper thigh",
            "Knee": "the knee",
            "Midi": "mid-calf", "Calf": "mid-calf",
            "Maxi": "full length", "Full": "full length",
        },
        "Tops": {
            "Cropped": "the midriff",
            "Short": "the waist",
            "Regular": "the hip",
            "Long": "the upper thigh",
            "Thigh": "mid-thigh",
            "Knee Length": "the knee", "Knee": "the knee",
            "Calf Length": "mid-calf", "Calf": "mid-calf",
            "Full Length": "full length", "Full": "full length",
        },
    }
    _LANDMARK_PHRASES["Vests"] = _LANDMARK_PHRASES["Tops"]

    @classmethod
    def _length_reference_for(cls, category, length_class=None):
        """
        (inch chart, landmark phrasing) for a category, or ({}, {}).

        Kept as one lookup so the two can never be fetched from different
        categories -- reading a trouser length against a top's wording was a
        real bug here.

        A co-ord set carries one length tag describing whichever half has it:
        "Calf" for the skirt of a vest-and-skirt set, "Cropped" for the
        trousers. `length_class` picks the half, by choosing the first chart
        that defines that name. The vocabularies barely overlap, so this is
        unambiguous.

        This used to MERGE the skirt and trouser charts instead, and that
        quietly produced different advice for identical garments: trousers name
        33-36" "mid-calf" (Capri) and skirts name 28-32" "mid-calf" (Calf), so
        merging fused them into one 28-36" region. A 30" hem on a 152cm customer
        then read as "still sits at mid-calf" for a vest-and-skirt set while an
        otherwise identical skirt correctly said "about 7cm lower".
        """
        if category in GARMENT_LENGTH_CHART_IN:
            return GARMENT_LENGTH_CHART_IN[category], cls._LANDMARK_PHRASES.get(category, {})
        if category == "Co-ord Sets":
            for source in COORD_LENGTH_CHART_ORDER:
                if length_class is None or length_class in GARMENT_LENGTH_CHART_IN[source]:
                    return (GARMENT_LENGTH_CHART_IN[source],
                            cls._LANDMARK_PHRASES.get(source, {}))
        return {}, {}

    def _generate_length_note(self, height_cm, product):
        """
        Where this hem will fall on *this* customer, said on every garment whose
        length is known.

        The garment is a fixed number of inches long; the body it hangs on is
        not. Eighth Hour's length guide states, for each class, the inches at
        which the hem reaches a named landmark on their fit model -- so those
        numbers are that model's own waist-to-knee, waist-to-calf and
        waist-to-floor distances. Scaling them by the customer's height over the
        model's gives the same landmarks on the customer, while the garment stays
        the length it was cut. Whichever band it now falls in is where it will
        actually sit. No new body ratios are introduced: every distance used is
        one the published chart already states.

        Two things this deliberately does NOT do any more:

        * It no longer stays silent when the difference is small. The advice
          appears on every recommendation, so absence would read as missing
          information rather than as reassurance -- "falls as shown" is itself
          worth saying. Silence is now reserved for genuine unknowns: no length
          recorded, no height, an unrecognised category.
        * It no longer decides whether to speak by comparing the shift against
          the length class's chart range. Those ranges run from 0.5" to 2", so
          that rule made a vest speak up at 3.8cm taller while a skirt waited
          until 12cm -- despite the skirt's hem moving further, being longer.
          The magnitude is now reported in centimetres on the customer's own
          body, which is the thing she can actually perceive.

        Returns a single sentence, or None if the answer isn't knowable.
        """
        length_class = product.get("length")
        chart, phrases = self._length_reference_for(product.get("category"), length_class)
        if not length_class or length_class not in chart:
            return None
        # isfinite, not just > 0: every comparison against NaN is False, so a
        # NaN height slipped past a bare `<= 0` guard, divided through, and came
        # out the far end as a confidently worded sentence about a hem landing
        # "below full length".
        if (not isinstance(height_cm, (int, float)) or isinstance(height_cm, bool)
                or not math.isfinite(height_cm) or height_cm <= 0):
            return None

        reference_height = product.get("model_height_cm") or LENGTH_CHART_REFERENCE_HEIGHT_CM
        if not reference_height:
            return None

        low, high = chart[length_class]
        garment_inches = (low + high) / 2

        # Convert to the equivalent length on the reference body: a taller
        # customer's landmarks are further apart, so the same garment behaves
        # like a shorter one relative to her frame.
        equivalent = garment_inches * (reference_height / height_cm)

        # How far the hem sits from where it is pictured, in centimetres on this
        # customer's body. Her landmark is at garment_inches * (height/reference)
        # while the garment is still garment_inches long, so the gap between them
        # is what she sees. Positive means higher up her leg.
        shift_cm = garment_inches * (height_cm / reference_height - 1) * 2.54

        # Where it now lands, described with this chart's own landmarks. Ordered
        # by inches; duplicate ranges (Midi and Calf are the same measurement)
        # collapse to a single entry.
        def phrase(name):
            return phrases.get(name, name.lower())

        # Bands ordered by length and reduced to distinct *places*. Two things
        # make that necessary: a chart names the same measurement twice (Midi
        # and Calf are both 28-32"), and a merged co-ord chart can carry two
        # different classes that land in the same spot (a skirt's Calf at 28-32"
        # beside a trouser's Capri at 33-36"). Left unmerged, a hem between them
        # was described as sitting "between mid-calf and mid-calf".
        places = []
        for span, name in sorted({span: name for name, span in chart.items()}.items()):
            where = phrase(name)
            if places and places[-1][1] == where:
                (previous_low, _), _ = places[-1]
                places[-1] = ((previous_low, span[1]), where)
            else:
                places.append((span, where))

        # Describe the landing point against the NEAREST landmark, not as a range
        # between two of them. The chart's bands don't touch, and some gaps are
        # enormous -- the trouser chart jumps from Short (12-16") straight to
        # Capri (33-36") because nothing in between is published. "Between the
        # upper thigh and mid-calf" spans most of a leg and tells a customer
        # almost nothing, whereas "just above mid-calf" is both accurate and
        # usable. The centimetre figure in the sentence supplies the precision.
        inside = next(
            (where for (band_low, band_high), where in places
             if band_low <= equivalent <= band_high),
            None,
        )

        def gap(place):
            (band_low, band_high), _ = place
            return band_low - equivalent if equivalent < band_low else equivalent - band_high

        nearest = inside or min(places, key=gap)[1]

        cut_for = phrase(length_class)

        # Name the reference instead of alluding to it. "Our fit model" is an
        # anonymous benchmark the customer cannot check; her height is recorded
        # per product, and stating it makes the claim verifiable. Centimetres
        # throughout, matching every other measurement on the site.
        shown_on = f"Cut to sit at {cut_for} on our {round(reference_height)}cm fit model"
        her_height = f"{round(height_cm)}cm"

        # Still reaching the same landmark it was cut for. Say that, rather than
        # "much the same": the hem may genuinely have moved a couple of
        # centimetres, and the useful fact is that it lands in the same place.
        if inside == cut_for:
            return f"{shown_on}, and at {her_height} it should still sit at {cut_for} on you."

        # Too small a move to put a number on, and never "about 0cm".
        if abs(shift_cm) < LENGTH_NOTE_SAME_AS_SHOWN_CM:
            return f"{shown_on}, and at {her_height} it should fall much the same on you."

        direction = "higher" if shift_cm > 0 else "lower"
        moved = f"{shown_on}, so at {her_height} expect it about {abs(shift_cm):.0f}cm {direction}"

        # Name where it ends up only when that is a DIFFERENT landmark. Saying
        # "10cm lower -- below mid-calf" about a mid-calf skirt restates itself;
        # saying "10cm lower -- closer to full length" tells her something the
        # number alone doesn't.
        if nearest == cut_for:
            return f"{moved}."
        return f"{moved} — {'at' if inside else 'closer to'} {nearest}."

    # ----------------------------------------------- advice beyond the size

    def _fit_advice(self, measurements, product, recommended_size, note_dimensions, shape_class, closest_available):
        """
        Advice beyond the headline size, for every customer, from the brand's
        published ranges and the piece's own data:

          - fit_by_area: where she sits in her size's published range at each
            area the garment is sized on -- roomy, relaxed, true to size,
            close or snug;
          - tips: when she measures a different size at one of those areas,
            which to choose (weighing the piece's cut and fabric); and a
            styling tip for her shape and the piece's silhouette.

        With a custom per-product chart (no published ranges) only the styling
        tip applies; when her size isn't stocked, the closest-available note
        already says what the size comparison would.
        """
        areas = [a for a in ("bust", "waist", "hips") if a in note_dimensions]
        if CATEGORY_ZONE.get(product.get("category")) == "top":
            # Tops are sized on the bust -- or, for some shapes, the waist.
            sized_on = TOP_SIZE_DIMENSION_BY_SHAPE.get(shape_class, DEFAULT_TOP_SIZE_DIMENSION)
            if sized_on not in areas:
                areas.append(sized_on)
        areas = [a for a in ("bust", "waist", "hips") if a in areas and measurements.get(a)]

        fit_by_area, tips = [], []
        if not product.get("size_chart") and recommended_size in SIZE_CHART_SOURCE:
            for area in areas:
                low, high = SIZE_CHART_SOURCE[recommended_size][area]
                fit_by_area.append({"area": area, "fit": self._describe_area_fit(measurements[area], low, high)})
            if not closest_available:
                tip = self._between_sizes_tip(measurements, product, recommended_size, areas)
                if tip:
                    tips.append(tip)
        styling = self._styling_tip(product, shape_class)
        if styling:
            tips.append(styling)
        return fit_by_area, tips

    @staticmethod
    def _describe_area_fit(value, low, high):
        """Where a measurement sits in a size's published range, in the words
        a customer uses. The thirds split the range for description; they are
        not a fitted threshold."""
        if value < low:
            return "roomy"
        if value > high:
            return "snug"
        third = (high - low) / 3
        if value < low + third:
            return "relaxed"
        if value > high - third:
            return "close"
        return "true to size"

    @staticmethod
    def _sizes_at(area, value):
        """(smaller, larger) published sizes around a measurement: the same
        size twice when its range holds the measurement, the two neighbours
        when it falls in the gap between them, None past an end of the chart."""
        previous = None
        for size in STANDARD_SIZES:
            low, high = SIZE_CHART_SOURCE[size][area]
            if value < low:
                return (previous, size)
            if value <= high:
                return (size, size)
            previous = size
        return (previous, None)

    def _between_sizes_tip(self, measurements, product, recommended_size, areas):
        """When she measures a different size at one of the garment's areas
        than the one recommended -- most often in the gap between two sizes --
        say so, and which to choose. Larger first: a tight fit matters more
        than a little room."""
        order = {size: i for i, size in enumerate(STANDARD_SIZES)}
        stocked = [s for s in STANDARD_SIZES if s in (product.get("sizes") or [])]
        rec = order[recommended_size]
        larger = smaller = None
        for area in areas:
            low_size, high_size = self._sizes_at(area, measurements[area])
            if high_size is not None and order[high_size] > rec and larger is None:
                larger = (area, low_size, high_size)
            elif low_size is not None and order[low_size] < rec and smaller is None:
                smaller = (area, low_size, high_size)

        def measured(low_size, high_size):
            if low_size == high_size:
                return low_size
            if low_size is None:
                return f"under {high_size}"
            if high_size is None:
                return f"over {low_size}"
            return f"between {low_size} and {high_size}"

        if larger:
            area, low_size, high_size = larger
            said = f"At the {area} you measure {measured(low_size, high_size)}"
            bigger = [s for s in stocked if order[s] > rec]
            if not bigger:
                return f"{said}, so {recommended_size} may feel close there."
            # The stocked size that gives her room there, or the largest there is.
            up = next((s for s in bigger if order[s] >= order[high_size]), bigger[-1])
            if order[up] < order[high_size]:
                return f"{said}; the largest size here is {up}, which may still feel snug there."
            one_step = order[high_size] - rec == 1
            fabric = str(product.get("fabric") or "").strip()
            words = set(fabric.lower().replace("-", " ").split())
            cut = str(product.get("fit") or "").lower()
            if cut == "relaxed" and one_step:
                return f"{said}, but this piece is cut relaxed, so {recommended_size} should still be comfortable there."
            if cut in ("slim", "snug"):
                return f"{said}, and this piece is cut close to the body, so {up} will feel easier there."
            if words & set(STRETCH_FABRICS) and one_step:
                return f"{said}; the fabric has some stretch, so {recommended_size} should be comfortable there."
            if words & set(LOW_GIVE_FABRICS):
                return f"{said}. {fabric} has little give, so choose {up} if you'd like more room through the {area}."
            return f"{said}. Choose {up} if you'd like more room through the {area}."
        if smaller:
            area, low_size, high_size = smaller
            room = "a little extra room" if rec - order[low_size] == 1 else "extra room"
            return f"At the {area} you measure {measured(low_size, high_size)}, so {recommended_size} will have {room} there."
        return None

    @staticmethod
    def _styling_tip(product, shape_class):
        """A styling tip for her shape and this piece's silhouette
        (STYLING_TIPS), or None."""
        tips = STYLING_TIPS.get(shape_class)
        if not tips:
            return None
        silhouettes = product.get("silhouette_classes") or (
            [product["silhouette_class"]] if product.get("silhouette_class") else []
        )
        zone = CATEGORY_ZONE.get(product.get("category"), "full")
        for silhouette in SILHOUETTE_TIP_ORDER:
            if silhouette in silhouettes:
                tip = tips[silhouette]
                return tip[zone] if isinstance(tip, dict) else tip
        return None

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

        # Measurement-specific guidance first, because whether any of it fires
        # changes what the headline below is allowed to claim. Only dimensions
        # that actually matter for this category (see docstring above).
        caveats = []
        if "bust" in note_dimensions:
            if bust_diff < -2:
                caveats.append("Recommended size runs large in the bust.")
            elif bust_diff > 2:
                caveats.append("Recommended size runs small in the bust.")

        if "waist" in note_dimensions:
            if waist_diff < -2:
                caveats.append("Recommended size is loose in the waist.")
            elif waist_diff > 2:
                caveats.append("Recommended size is snug in the waist.")

        if "hips" in note_dimensions:
            if hips_diff < -2:
                caveats.append("Recommended size is loose in the hips.")
            elif hips_diff > 2:
                caveats.append("Recommended size is snug in the hips.")

        # Headline. Under boundary-aware scoring (see
        # _dimension_confidence_from_boundary), the recommended size's own score
        # can never fall below FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE (0.85) --
        # that's the whole point of the guarantee it provides. The thresholds
        # below are calibrated to that: 0.95 splits the boundary-edge ramp
        # roughly in half, so "is a good fit" actually triggers for a meaningful
        # stretch near a boundary (not just the last sliver right at the edge),
        # rather than the top tier dominating almost the entire size. The bottom
        # two tiers stay reachable for the rarer paths without that guarantee (a
        # custom per-product size chart, or a category with no single driving
        # measurement, like Co-ord Sets' original blended fallback).
        #
        # The top tier is gated on there being no caveats. rec_score measures
        # only the dimension that drives this category's size (bust for a dress,
        # hips for a skirt -- see FIT_SCORE_DIMENSION_WEIGHTS), while the caveats
        # above cover everything the garment touches. So a dress could score a
        # flawless 1.0 on the bust and still be loose through the hips, and the
        # customer was told "Size M fits perfectly." immediately followed by
        # "Recommended size is loose in the hips." Both statements were true of
        # what they each measured, and together they read as the system
        # contradicting itself in consecutive sentences. "Your best fit" claims
        # exactly what the score supports -- this is the size to buy -- without
        # claiming the fit is flawless everywhere.
        rec_score = fit_scores[recommended_size]
        if rec_score >= 0.95:
            headline = (
                f"Size {recommended_size} is your best fit." if caveats
                else f"Size {recommended_size} fits perfectly."
            )
        elif rec_score >= 0.85:
            headline = f"Size {recommended_size} is a good fit."
        elif rec_score >= 0.65:
            headline = f"Size {recommended_size} is acceptable with possible minor adjustments."
        else:
            headline = f"Size {recommended_size} may require alterations for optimal fit."

        notes.append(headline)
        notes.extend(caveats)

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
