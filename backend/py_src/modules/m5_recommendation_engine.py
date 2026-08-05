"""
M5 — Recommendation Engine

Responsibility: Orchestrate personalized recommendations using intake session data.
Converts body shape + style preferences into retrieval queries for M6.

Guardrails applied:
- ConsentTracker: Verify user has photo consent before recommending
- AuditLogger: Log all recommendation requests
- InputValidator: Validate session data completeness
"""

from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.guardrails.input_validation import InputValidator
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError


class RecommendationEngine:
    """Generates personalized recommendations from completed intake sessions."""

    def __init__(self, catalog: CatalogKB, consent_tracker: ConsentTracker = None):
        """
        Initialize recommendation engine.

        Args:
            catalog: CatalogKB instance for product retrieval
            consent_tracker: Optional ConsentTracker for consent verification
        """
        self.catalog = catalog
        self.consent_tracker = consent_tracker or ConsentTracker()
        logger.info("M5 RecommendationEngine initialized")

    def generate_recommendations(
        self,
        session,
        k: int = 10,
        category_filter: list = None,
        occasion_filter: str = None,
    ) -> list:
        """
        Generate personalized recommendations from an intake session.

        Args:
            session: Completed IntakeSession with shape_profile and style_profile
            k: Number of recommendations to return (default 10)
            category_filter: Optional list of categories to restrict to
            occasion_filter: Optional occasion to filter recommendations by

        Returns:
            List of ranked product recommendations (dicts from M6)

        Raises:
            ModuleError: If session is incomplete or missing required data
            GuardrailError: If user has not consented to photo processing
        """
        # Validate session is complete
        self._validate_session(session)

        # Check consent
        if not self.consent_tracker.has_photo_consent(session.user_id):
            raise GuardrailError(
                "User has not consented to photo processing for recommendations",
                "M5"
            )

        # Build retrieval query from session data
        query = self._build_retrieval_query(
            session,
            category_filter=category_filter,
            occasion_filter=occasion_filter,
            k=k,
        )

        # Log retrieval
        AuditLogger.log_event(
            "RECOMMENDATIONS_REQUESTED",
            session.user_id,
            {
                "session_id": session.session_id,
                "shape_class": session.shape_profile.get("shape_class"),
                "categories": query.get("categories", []),
                "k": k,
            },
        )

        logger.debug(
            "Generating recommendations",
            {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "shape_class": session.shape_profile.get("shape_class"),
            },
        )

        # Retrieve recommendations from M6
        recommendations = self.catalog.retrieve(
            query,
            user_id=session.user_id,
            consent_tracker=self.consent_tracker,
        )

        # Log results
        AuditLogger.log_event(
            "RECOMMENDATIONS_GENERATED",
            session.user_id,
            {
                "session_id": session.session_id,
                "count": len(recommendations),
                "top_3": [r.get("sku") for r in recommendations[:3]],
            },
        )

        logger.info(
            "Recommendations generated",
            {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "count": len(recommendations),
            },
        )

        return recommendations

    def _validate_session(self, session) -> None:
        """Validate that session is complete and has required data."""
        # Check status
        if session.status != "complete":
            raise ModuleError(
                f"Session must be complete (status='complete'), got status='{session.status}'",
                "M5"
            )

        # Check body measurements
        if not session.body_measurements:
            raise ModuleError("Session missing body measurements", "M5")

        # Check shape profile
        if not session.shape_profile or "shape_class" not in session.shape_profile:
            raise ModuleError("Session missing shape profile", "M5")

        # Check style profile
        if not session.style_profile:
            raise ModuleError("Session missing style profile", "M5")

        logger.debug("Session validation passed", {"session_id": session.session_id})

    def _build_retrieval_query(
        self,
        session,
        category_filter: list = None,
        occasion_filter: str = None,
        k: int = 10,
    ) -> dict:
        """
        Build M6 retrieval query from session data.

        Maps intake data to M6 query parameters:
        - shape_class: from shape_profile
        - categories: from shape_profile's size recommendations (or override)
        - preferred_colors: from style_profile
        - occasion-based filtering: from style_profile.occasions

        Args:
            session: IntakeSession with complete profile data
            category_filter: Optional override for categories
            occasion_filter: Optional specific occasion to filter by
            k: Number of results to retrieve

        Returns:
            Dict query parameters for M6.retrieve()
        """
        shape_profile = session.shape_profile
        style_profile = session.style_profile
        measurements = session.body_measurements.to_dict()

        # Colors from style profile (capitalize to match catalog format)
        raw_colors = style_profile.preferred_colors or []
        preferred_colors = [color.capitalize() for color in raw_colors]

        # Size: derive from measurements (could be more sophisticated)
        size = self._infer_size_from_measurements(measurements)

        # Build base query
        query = {
            "shape_class": shape_profile.get("shape_class"),
            "preferred_colors": preferred_colors,
            "k": k,
        }

        # Add categories only if explicitly provided (avoid breaking with M3's non-standard categories)
        if category_filter:
            query["categories"] = category_filter

        # Add size if available
        if size:
            query["size"] = size

        # Optional: filter by occasion if specified
        # (This could be extended in M6 to support occasion-based filtering)
        if occasion_filter:
            # Store for M6 to use if supported
            query["occasion"] = occasion_filter
        elif style_profile.occasions:
            # Use first occasion as default if not specified
            query["occasion"] = style_profile.occasions[0]

        logger.debug("Retrieval query built", {"query_keys": list(query.keys())})
        return query

    def _infer_size_from_measurements(self, measurements: dict) -> str:
        """
        Infer standard size (XS, S, M, L, XL) from measurements.

        Uses Eighth Hour's sizing scale.
        Simplified: could use more sophisticated size matrix.

        Args:
            measurements: Dict with bust, waist, hips, height

        Returns:
            Size string (XS, S, M, L, XL, XXL) or None
        """
        bust = measurements.get("bust", 0)
        waist = measurements.get("waist", 0)

        # Rough mapping based on standard sizing
        # (This is simplified; a real system would use a detailed size matrix)
        if bust < 80:
            return "XS"
        elif bust < 84:
            return "S"
        elif bust < 90:
            return "M"
        elif bust < 96:
            return "L"
        elif bust < 102:
            return "XL"
        else:
            return "XXL"
