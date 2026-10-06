"""
M3 — Body Shape Profiler

Responsibility: Translate raw measurements into body shape profile.
Deterministic rules-based classifier.

Guardrails applied:
- InputValidator: validate measurements before processing
- AuditLogger: log profile operations
"""

from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.audit_logger import AuditLogger
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.constants import (SIZE_BOUNDARIES, WAIST_SIZE_BOUNDARIES,
                              HIP_SIZE_BOUNDARIES, STANDARD_SIZES,
                              SHAPE_THRESHOLDS)


# What each shape means, in the customer's terms. Shown after the sentence that
# says how their own measurements led there (see _explain_shape).
SHAPE_MEANINGS = {
    "pear": "a pear shape: fuller through the hips than the bust",
    "athletic": "an athletic shape: fuller through the bust than the hips, "
                "with a straighter waist",
    "hourglass": "an hourglass shape: a clearly defined waist",
    "apple": "an apple shape: fullest through the middle",
    "straight": "a straight shape: neither bust nor hips distinctly fuller, "
                "and little waist definition",
    "balanced": "a balanced shape: neither bust nor hips distinctly fuller, "
                "with a moderately defined waist",
}


# Created on first use by refresh_if_outdated, rather than once per stored
# profile loaded.
_refresh_profiler = None


class BodyShapeProfiler:
    """Deterministic body shape classifier based on measurement ratios."""

    # Bump whenever the classification or size rules change. Stored profiles
    # from an older version are recomputed when loaded (refresh_if_outdated),
    # so a customer is never left with a label the current rules would not give.
    PROFILE_VERSION = "2.0.0"

    def __init__(self):
        logger.info("M3 initialized", {"version": self.PROFILE_VERSION})

    def profile(self, measurements, user_id=None, consent_tracker=None):
        """
        Create a BodyShapeProfile from Measurements.

        Args:
            measurements: Dict with bust, waist, hips, height (shoulder and
                inseam may be present but don't affect the shape)
            user_id: Optional user ID for consent checking and audit logging
            consent_tracker: Optional ConsentTracker to verify measurement consent

        Returns:
            Profile dict with shape_class, shape_summary, comparisons_cm,
            ratios, size_recommendation_by_category, fit_notes

        Raises:
            ModuleError: If measurements are invalid
            GuardrailError: If consent not given for measurement processing
        """
        try:
            # Guardrail 0: Check consent if user context provided
            if user_id and consent_tracker:
                if not consent_tracker.has_measurement_consent(user_id):
                    AuditLogger.log_event(
                        "INVALID_INPUT",
                        user_id,
                        {"reason": "No measurement consent"}
                    )
                    raise GuardrailError(
                        "User has not consented to measurement processing",
                        "M3"
                    )

            # Guardrail 1: Validate input
            validation = InputValidator.validate_measurements(measurements)
            if not validation["valid"]:
                if user_id:
                    AuditLogger.log_invalid_input(user_id, validation["errors"][0])
                raise ModuleError(
                    f"Invalid measurements: {', '.join(validation['errors'])}",
                    "M3",
                )

            bust = measurements["bust"]
            waist = measurements["waist"]
            hips = measurements["hips"]
            # measurements.get("shoulder", hips) would NOT fall back to hips
            # when the key is present but None (e.g. from Measurements.to_dict()
            # when the customer never provided a shoulder measurement) --
            # only when the key is absent entirely. Use `or` so both cases fall
            # back the same way.
            bust_waist = bust / waist
            waist_hip = waist / hips

            shape_class = self._classify_shape(bust, waist, hips)

            # Generate recommendations
            size_recommendations = self._recommend_sizes(
                shape_class, bust, waist, hips
            )

            fit_notes = self._generate_fit_notes(shape_class, bust_waist, waist_hip)

            # No shoulder ratio. It was shoulder / hips, but the shoulder is a
            # breadth (30-60 cm across) and the hips a circumference, so the
            # ratio meant nothing -- and when no shoulder was given it fell back
            # to the hips, so most customers were shown exactly 1.00.
            ratios = {
                "bust_waist": round(bust_waist, 2),
                "waist_hip": round(waist_hip, 2),
                "bust_hip": round(bust / hips, 2),
            }

            profile = {
                "shape_class": shape_class,
                "shape_summary": self._explain_shape(shape_class, bust, waist, hips),
                # Signed differences in cm (positive: the first is larger), the
                # quantities the classification is decided on.
                "comparisons_cm": {
                    "bust_minus_hips": round(bust - hips, 1),
                    "bust_minus_waist": round(bust - waist, 1),
                    "hips_minus_waist": round(hips - waist, 1),
                },
                "ratios": ratios,
                "size_recommendation_by_category": size_recommendations,
                "fit_notes": fit_notes,
                "profile_version": self.PROFILE_VERSION,
            }

            logger.debug(
                "M3 profile generated",
                {
                    "shape_class": shape_class,
                    "bust_waist": round(bust_waist, 2),
                    "waist_hip": round(waist_hip, 2),
                },
            )

            # Audit: Log successful profile creation if user context provided
            if user_id:
                AuditLogger.log_event(
                    "PROFILE_CREATED",
                    user_id,
                    {
                        "shape_class": shape_class,
                        "ratios_bust_waist": round(bust_waist, 2),
                        "ratios_waist_hip": round(waist_hip, 2),
                    }
                )

            return profile

        except Exception as err:
            logger.error("M3 profiling failed", err)
            raise

    @staticmethod
    def _classify_shape(bust, waist, hips):
        """
        Classify shape from bust, waist and hips (cm). See SHAPE_THRESHOLDS in
        constants.py for where each line comes from.

        Every comparison is a difference divided by the body's frame (mean of
        bust and hips), so the same proportions give the same shape at any size.
        """
        frame = (bust + hips) / 2
        bust_over_hips = (bust - hips) / frame
        bust_over_waist = (bust - waist) / frame
        hips_over_waist = (hips - waist) / frame
        # How much smaller the waist is than the fuller of bust and hips.
        waist_gap = (max(bust, hips) - waist) / frame
        t = SHAPE_THRESHOLDS

        # Waist about as full as the fullest point. Checked first: a figure that
        # is fullest through the middle is an apple whichever of bust and hips
        # happens to be larger.
        if waist_gap <= t["apple_waist_gap"]:
            return "apple"

        # FFIT triangle (and its spoon / bottom-hourglass variants): hips
        # distinctly fuller than the bust.
        if -bust_over_hips >= t["bust_hips_distinct"]:
            return "pear"

        # FFIT inverted triangle: bust distinctly fuller, waist not defined.
        if bust_over_hips >= t["bust_hips_distinct"] and bust_over_waist < t["bust_waist_defined"]:
            return "athletic"

        # FFIT top hourglass: bust somewhat fuller, with a defined waist.
        if bust_over_hips > t["bust_hips_even"] and bust_over_waist >= t["bust_waist_defined"]:
            return "hourglass"

        # FFIT hourglass: bust and hips even (or hips only slightly fuller --
        # the distinct case returned above), with a defined waist.
        if bust_over_hips <= t["bust_hips_even"] and (
            bust_over_waist >= t["bust_waist_defined"]
            or hips_over_waist >= t["hips_waist_defined"]
        ):
            return "hourglass"

        # FFIT rectangle: no distinct difference anywhere. Split by how defined
        # the waist is.
        if waist_gap < t["balanced_waist_gap"]:
            return "straight"
        return "balanced"

    @staticmethod
    def _explain_shape(shape_class, bust, waist, hips):
        """
        One or two sentences describing the customer's own measurements and the
        shape they add up to.

        Built from the same numbers the classification used, so it cannot claim
        something about the customer's body that their measurements contradict.
        The fixed per-shape descriptions it replaces did exactly that: everyone
        classified pear was told their hips were fuller than their bust.
        """
        def cm(value):
            return f"{abs(value):.0f} cm" if abs(value) >= 0.5 else "less than 1 cm"

        frame = (bust + hips) / 2
        difference = bust - hips
        if abs(difference) / frame <= SHAPE_THRESHOLDS["bust_hips_even"]:
            if round(difference) == 0:
                balance = "Your bust and hips are the same"
            else:
                balance = f"Your bust and hips are within {cm(difference)} of each other"
        elif difference > 0:
            balance = f"Your bust is {cm(difference)} fuller than your hips"
        else:
            balance = f"Your hips are {cm(difference)} fuller than your bust"

        if round(bust - waist) == round(hips - waist):
            gap = bust - waist
            waist_part = (
                f"your waist is {cm(gap)} smaller than both" if gap > 0
                else f"your waist is {cm(gap)} larger than both" if gap < 0
                else "your waist measures the same as both"
            )
        else:
            def against(other, name):
                gap = other - waist
                if round(gap) == 0:
                    return f"the same as your {name}"
                return f"{cm(gap)} {'smaller' if gap > 0 else 'larger'} than your {name}"
            waist_part = f"your waist is {against(bust, 'bust')} and {against(hips, 'hips')}"

        return f"{balance}, and {waist_part}. That makes {SHAPE_MEANINGS[shape_class]}."

    @classmethod
    def refresh_if_outdated(cls, profile, measurements):
        """
        Recompute a stored profile that was made by an older PROFILE_VERSION.

        Profiles are computed once, when intake finishes, and read back from the
        database afterwards -- so a change to these rules would otherwise never
        reach a returning customer: someone told "pear" by the old classifier
        would keep seeing "pear" on their account. Their measurements are the
        source of truth, so the profile is rebuilt from them exactly as if they
        had redone intake today.

        Returns the stored profile unchanged when it is current, or when it can't
        be recomputed honestly (missing or invalid measurements).
        """
        if not isinstance(profile, dict) or profile.get("profile_version") == cls.PROFILE_VERSION:
            return profile
        if not isinstance(measurements, dict):
            return profile
        if not InputValidator.validate_measurements(measurements)["valid"]:
            return profile
        try:
            # No user context: consent was checked when the profile was first
            # made, and this processes nothing beyond what is already stored.
            global _refresh_profiler
            if _refresh_profiler is None:
                _refresh_profiler = cls()
            return _refresh_profiler.profile(measurements)
        except Exception as err:
            logger.warn("Could not refresh stored shape profile", {"error": str(err)})
            return profile

    def _recommend_sizes(self, shape_class, bust, waist, hips):
        """Generate size recommendations per category."""
        # Bust/waist/hip boundaries: shared with M5/M7/M9 via constants.py so
        # the size shown to the customer here always matches what's used to
        # filter their recommendations and to score garment fit.
        size_by_bust = SIZE_BOUNDARIES
        size_by_waist = WAIST_SIZE_BOUNDARIES
        size_by_hip = HIP_SIZE_BOUNDARIES

        def find_size(measurement, chart):
            for size, (min_val, max_val) in chart.items():
                if min_val <= measurement < max_val:
                    return size
            # Unreachable while the bands span the whole validated range, which
            # test_size_chart_integrity asserts -- but the fallback has to be
            # right anyway, because it is the thing that runs if that invariant
            # ever breaks. Fall off whichever end the measurement went past,
            # read off this chart rather than a fixed number: a literal
            # threshold means the wrong thing the moment the chart moves, and
            # a single one can't be right for bust, waist and hips at once.
            below_smallest = next(iter(chart.values()))[0]
            return STANDARD_SIZES[0] if measurement < below_smallest else STANDARD_SIZES[-1]

        bust_size = find_size(bust, size_by_bust)
        waist_size = find_size(waist, size_by_waist)
        hip_size = find_size(hips, size_by_hip)

        logger.info(f"M3 size calculation: bust={bust}→{bust_size}, waist={waist}→{waist_size}, hips={hips}→{hip_size}")

        # Standard sizing approach:
        # Tops/Dresses/Outerwear: use bust
        # Skirts/Trousers: use hip (primary) and waist (secondary)
        top_size = bust_size
        bottom_size = hip_size

        # Apple shape: waist is prominent, use waist for tops
        if shape_class == "apple":
            top_size = waist_size

        return {
            "tops": top_size,
            "skirts": bottom_size,
            "dresses": top_size,
            "trousers": bottom_size,
            "vests": top_size,
            "coOrds": f"{top_size}/{bottom_size}",  # Shows both top/bottom sizes for coordinated sets
        }

    def _generate_fit_notes(self, shape_class, bust_waist, waist_hip):
        """Generate personalized fit guidance."""
        notes = []

        if shape_class == "pear":
            notes.append(
                "Fitted tops will showcase your shoulders and balance proportions."
            )
            notes.append(
                "A-line skirts and wider-leg trousers will complement your curves."
            )
            notes.append("Wrap silhouettes work beautifully on you.")

        elif shape_class == "apple":
            notes.append("Empire-waist and flowing silhouettes will be your friends.")
            notes.append("Straight-cut bottoms will elongate your frame.")
            notes.append("Layering pieces like vests add polish without bulk.")

        elif shape_class == "hourglass":
            notes.append("Fitted styles will emphasize your balanced proportions.")
            notes.append("Wrap dresses and belted silhouettes are made for you.")
            notes.append("Look for pieces that define the waist.")

        elif shape_class == "straight":
            notes.append("You can wear virtually any silhouette.")
            notes.append("Ruching, ruffle, and layered pieces add dimension.")
            notes.append("Structured fabrics create interesting lines on you.")

        elif shape_class == "athletic":
            notes.append("Peplum and flared silhouettes will enhance curves.")
            notes.append("Boat necks and wide necklines balance strong shoulders.")
            notes.append("Lighter fabrics soften your athletic frame.")

        else:  # balanced
            notes.append("Your balanced proportions mean most silhouettes work well.")
            notes.append("You can play with both classic and trendy cuts.")

        return notes
