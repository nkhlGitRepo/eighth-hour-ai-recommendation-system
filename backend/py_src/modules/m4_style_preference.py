"""
M4 — Style Preference Capture

Responsibility: Collect taste dimension (colors, silhouettes, occasions, coverage).
Keep intake short; depth comes from behavior over time (M8 in Phase 4).

Guardrails applied:
- InputValidator: sanitize free-text preferences
- AuditLogger: log preference capture
- InjectionDefense: prevent prompt injection in free text
"""

from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.audit_logger import AuditLogger
from py_src.guardrails.injection_defense import InjectionDefense
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError
import time


class StyleProfile:
    """User's stated style preferences."""

    # Valid options for each preference dimension
    VALID_COLORS = [
        # Generic preference colors
        "black",
        "navy",
        "cream",
        "white",
        "gray",
        "earth_tones",
        "jewel_tones",
        "pastels",
        "bright",
        "monochrome",
        # Actual product colors (from catalog)
        "Ebony",
        "Moonless Night",
        "Chocolate Truffle",
        "Sky Captain",
        "Forest Night",
        "Pageant Blue",
        "Pure Cashmere",
        "Potent Purple",
        "Purple Potion",
        "Kombu Green",
        "Burnt Russet",
        "Duffel Bag",
        "Fig",
        "Fudge",
        "Nomad",
        "Sepia Tint",
        "White Alyssum",
    ]

    VALID_SILHOUETTES = [
        "fitted",
        "flowing",
        "straight",
        "a_line",
        "oversized",
        "tailored",
        "relaxed",
        "structured",
    ]

    VALID_OCCASIONS = [
        "work",
        "casual",
        "evening",
        "weekend",
        "gym",
        "travel",
        "date_night",
        "vacation",
    ]

    VALID_COVERAGE = {
        "neckline": ["conservative", "moderate", "open"],
        "sleeves": ["full", "three_quarter", "short", "sleeveless"],
        "fit": ["tight", "fitted", "relaxed", "oversized"],
    }

    VALID_LIFESTYLE = {
        "pace": ["slow", "moderate", "fast"],
        "climate": ["hot", "temperate", "cold", "mixed"],
    }

    def __init__(
        self,
        user_id: str,
        preferred_colors: list = None,
        preferred_silhouettes: list = None,
        occasions: list = None,
        coverage_prefs: dict = None,
        lifestyle_context: dict = None,
        free_text_notes: str = "",
    ):
        self.user_id = user_id
        self.preferred_colors = preferred_colors or []
        self.preferred_silhouettes = preferred_silhouettes or []
        self.occasions = occasions or []
        self.coverage_prefs = coverage_prefs or {}
        self.lifestyle_context = lifestyle_context or {}
        self.free_text_notes = free_text_notes
        self.profile_version = "1.0.0"
        self.created_at = time.time()
        self.updated_at = time.time()

    def to_dict(self):
        """Convert to dict for API responses."""
        return {
            "user_id": self.user_id,
            "preferred_colors": self.preferred_colors,
            "preferred_silhouettes": self.preferred_silhouettes,
            "occasions": self.occasions,
            "coverage_prefs": self.coverage_prefs,
            "lifestyle_context": self.lifestyle_context,
            "free_text_notes": self.free_text_notes,
            "profile_version": self.profile_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PreferenceCapture:
    """Capture and validate user style preferences."""

    def __init__(self):
        logger.info("M4 PreferenceCapture initialized")

    def capture_preferences(
        self,
        user_id: str,
        preferred_colors: list = None,
        preferred_silhouettes: list = None,
        occasions: list = None,
        coverage_prefs: dict = None,
        lifestyle_context: dict = None,
        free_text_notes: str = "",
    ) -> StyleProfile:
        """
        Capture and validate user style preferences.

        Args:
            user_id: User ID
            preferred_colors: List of color preferences
            preferred_silhouettes: List of silhouette preferences
            occasions: List of occasions
            coverage_prefs: Dict of coverage preferences {neckline, sleeves, fit}
            lifestyle_context: Dict of lifestyle {pace, climate}
            free_text_notes: Optional free-text notes (sanitized)

        Returns:
            StyleProfile object

        Raises:
            ModuleError: If preferences invalid
        """
        try:
            # Validate and sanitize colors
            colors = self._validate_colors(preferred_colors or [])

            # Validate silhouettes
            silhouettes = self._validate_silhouettes(preferred_silhouettes or [])

            # Validate occasions
            occs = self._validate_occasions(occasions or [])

            # Validate coverage preferences
            coverage = self._validate_coverage(coverage_prefs or {})

            # Validate lifestyle
            lifestyle = self._validate_lifestyle(lifestyle_context or {})

            # Sanitize and validate free text
            notes = self._sanitize_free_text(free_text_notes)

            # Create profile
            profile = StyleProfile(
                user_id=user_id,
                preferred_colors=colors,
                preferred_silhouettes=silhouettes,
                occasions=occs,
                coverage_prefs=coverage,
                lifestyle_context=lifestyle,
                free_text_notes=notes,
            )

            logger.debug(
                "M4 preference capture",
                {
                    "user_id": user_id,
                    "colors": len(colors),
                    "silhouettes": len(silhouettes),
                    "occasions": len(occs),
                },
            )

            # Audit: Log preference capture
            AuditLogger.log_event(
                "PREFERENCES_CAPTURED",
                user_id,
                {
                    "colors_count": len(colors),
                    "silhouettes_count": len(silhouettes),
                    "occasions_count": len(occs),
                    "has_free_text": len(notes) > 0,
                },
            )

            return profile

        except Exception as err:
            logger.error("M4 preference capture failed", err)
            raise

    def _validate_colors(self, colors: list) -> list:
        """Validate and filter color preferences."""
        if not isinstance(colors, list):
            raise ModuleError("Colors must be a list", "M4")

        valid = [c for c in colors if c in StyleProfile.VALID_COLORS]
        if len(valid) == 0 and len(colors) > 0:
            raise ModuleError(
                f"No valid colors. Valid options: {StyleProfile.VALID_COLORS}", "M4"
            )

        return valid

    def _validate_silhouettes(self, silhouettes: list) -> list:
        """Validate and filter silhouette preferences."""
        if not isinstance(silhouettes, list):
            raise ModuleError("Silhouettes must be a list", "M4")

        valid = [s for s in silhouettes if s in StyleProfile.VALID_SILHOUETTES]
        if len(valid) == 0 and len(silhouettes) > 0:
            raise ModuleError(
                f"No valid silhouettes. Valid options: {StyleProfile.VALID_SILHOUETTES}",
                "M4",
            )

        return valid

    def _validate_occasions(self, occasions: list) -> list:
        """Validate and filter occasion preferences."""
        if not isinstance(occasions, list):
            raise ModuleError("Occasions must be a list", "M4")

        valid = [o for o in occasions if o in StyleProfile.VALID_OCCASIONS]
        if len(valid) == 0 and len(occasions) > 0:
            raise ModuleError(
                f"No valid occasions. Valid options: {StyleProfile.VALID_OCCASIONS}",
                "M4",
            )

        return valid

    def _validate_coverage(self, coverage_prefs: dict) -> dict:
        """Validate coverage preferences (neckline, sleeves, fit)."""
        if not isinstance(coverage_prefs, dict):
            raise ModuleError("Coverage preferences must be a dict", "M4")

        validated = {}
        for key, value in coverage_prefs.items():
            if key not in StyleProfile.VALID_COVERAGE:
                continue

            valid_options = StyleProfile.VALID_COVERAGE[key]
            if value in valid_options:
                validated[key] = value

        return validated

    def _validate_lifestyle(self, lifestyle_context: dict) -> dict:
        """Validate lifestyle preferences (pace, climate)."""
        if not isinstance(lifestyle_context, dict):
            raise ModuleError("Lifestyle context must be a dict", "M4")

        validated = {}
        for key, value in lifestyle_context.items():
            if key not in StyleProfile.VALID_LIFESTYLE:
                continue

            valid_options = StyleProfile.VALID_LIFESTYLE[key]
            if value in valid_options:
                validated[key] = value

        return validated

    def _sanitize_free_text(self, notes: str) -> str:
        """Sanitize free-text notes (remove injections, control chars)."""
        if not isinstance(notes, str):
            return ""

        # Sanitize text: remove control chars, collapse whitespace, limit length
        sanitized = InputValidator.sanitize_text(notes)

        # Additional: sanitize for LLM prompt injection prevention
        safe = InjectionDefense.sanitize_for_llm(sanitized)

        return safe
