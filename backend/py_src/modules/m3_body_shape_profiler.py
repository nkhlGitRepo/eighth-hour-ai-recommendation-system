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


class BodyShapeProfiler:
    """Deterministic body shape classifier based on measurement ratios."""

    PROFILE_VERSION = "1.0.0"

    def __init__(self):
        logger.info("M3 initialized", {"version": self.PROFILE_VERSION})

    def profile(self, measurements, user_id=None, consent_tracker=None):
        """
        Create a BodyShapeProfile from Measurements.

        Args:
            measurements: Dict with bust, waist, hips, shoulder, height
            user_id: Optional user ID for consent checking and audit logging
            consent_tracker: Optional ConsentTracker to verify measurement consent

        Returns:
            Profile dict with shape_class, ratios, recommendations, fit_notes

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
            shoulder = measurements.get("shoulder", hips)
            height = measurements["height"]

            # Compute ratios
            bust_waist = bust / waist
            waist_hip = waist / hips
            shoulder_hip = shoulder / hips

            # Classify shape
            shape_class = self._classify_shape(bust_waist, waist_hip, shoulder_hip)

            # Generate recommendations
            size_recommendations = self._recommend_sizes(
                shape_class, bust, waist, hips
            )

            fit_notes = self._generate_fit_notes(shape_class, bust_waist, waist_hip)

            profile = {
                "shape_class": shape_class,
                "ratios": {
                    "bust_waist": round(bust_waist, 2),
                    "waist_hip": round(waist_hip, 2),
                    "shoulder_hip": round(shoulder_hip, 2),
                },
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

    def _classify_shape(self, bust_waist, waist_hip, shoulder_hip):
        """
        Classify shape from ratios using deterministic rules.

        Ratios:
        - bust_waist: bust / waist (how defined the waist is)
        - waist_hip: waist / hips (hip/waist balance)
        - shoulder_hip: shoulder / hips (frame breadth)

        Returns:
            Shape class string
        """
        # HOURGLASS: curvy, balanced bust-hip with VERY small waist (MOST extreme)
        if bust_waist > 1.25 and waist_hip < 0.80:
            return "hourglass"

        # ATHLETIC: muscular, broad frame, minimal waist (also very extreme)
        if bust_waist > 1.25 and waist_hip < 0.90 and waist_hip >= 0.80:
            return "athletic"

        # PEAR: wider at hips, curvy at bottom (less extreme than hourglass/athletic)
        if bust_waist > 1.15 and waist_hip < 0.85:
            return "pear"

        # APPLE: larger waist/torso
        if bust_waist < 1.05 and waist_hip > 0.95:
            return "apple"

        # STRAIGHT: minimal curves, balanced throughout
        if 1.0 <= bust_waist <= 1.15 and 0.95 <= waist_hip <= 1.05:
            return "straight"

        # BALANCED: middle ground (catches everything else)
        return "balanced"

    def _recommend_sizes(self, shape_class, bust, waist, hips):
        """Generate size recommendations per category."""
        # Use consistent sizing based on bust/chest (standard for all sizes)
        size_by_bust = {
            "XXS": (78, 85),
            "XS": (85, 91),
            "S": (91, 97),
            "M": (97, 103),
            "L": (103, 109),
            "XL": (109, 115),
            "XXL": (115, 150),
        }

        size_by_waist = {
            "XXS": (60, 66),
            "XS": (66, 72),
            "S": (72, 78),
            "M": (78, 84),
            "L": (84, 90),
            "XL": (90, 96),
            "XXL": (96, 150),
        }

        # Hip boundaries per standard sizing guidelines
        # XS: 83-89cm, S: 89-95cm, M: 95-101cm, L: 101-107cm, XL: 107-114cm, XXL: 114+cm
        size_by_hip = {
            "XXS": (70, 83),
            "XS": (83, 89),
            "S": (89, 95),
            "M": (95, 101),
            "L": (101, 107),
            "XL": (107, 114),
            "XXL": (114, 150),
        }

        def find_size(measurement, chart):
            for size, (min_val, max_val) in chart.items():
                if min_val <= measurement < max_val:
                    return size
            return "XXL" if measurement >= 115 else "XS"

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
            "coOrds": top_size,
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
