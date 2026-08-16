"""
M5 — Recommendation Engine

Responsibility: Orchestrate personalized recommendations using intake session data.
Converts body shape + style preferences into retrieval queries for M6.

Guardrails applied:
- ConsentTracker: Verify user has photo consent before recommending
- AuditLogger: Log all recommendation requests
- InputValidator: Validate session data completeness
"""

from typing import Optional, List, Dict, Any
from py_src.modules.m1_intake_orchestrator import IntakeSession
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.constants import CATEGORY_TO_SIZE_PROFILE_KEY


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
        session: IntakeSession,
        k: int = 10,
        category_filter: Optional[List[str]] = None,
        occasion_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
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
        # Validate session is complete (session status = complete means consent was already verified during intake)
        self._validate_session(session)

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
        - preferred_colors, preferred_silhouettes: from style_profile
        - occasions: from style_profile.occasions (or explicit override)
        - size: from shape_profile (same value already shown to the customer
          on the Shape Profile screen -- must stay in sync with M3)

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

        # Colours come out of M4 already canonicalised to the catalog's own
        # spelling, so they are passed through untouched. The previous
        # title-casing here was dead defence -- M4 rejects an unrecognised
        # spelling before this code ever sees it -- and actively wrong for the
        # generic buckets, turning "earth_tones" into "Earth_Tones".
        preferred_colors = list(style_profile.preferred_colors or [])

        # Size: use the SAME sizes M3 already computed and showed the customer
        # on the Shape Profile screen, so what's displayed and what's filtered
        # never disagree.
        #
        # Per category, not one size for the whole catalog. This used to send
        # only the *tops* size and apply it to everything, which for anyone
        # whose top and bottom sizes differ filtered bottoms by a size they
        # don't wear -- getting it exactly backwards. A customer who is M on top
        # and S below had an S-only skirt excluded as unavailable and an M-only
        # skirt recommended to her. It never surfaced because every product in
        # the live catalog stocks every size, so the filter had nothing to
        # exclude; it would have appeared the first time anything sold out.
        sizes_by_category = {}
        by_category = shape_profile.get("size_recommendation_by_category", {}) or {}
        for category, profile_key in CATEGORY_TO_SIZE_PROFILE_KEY.items():
            category_size = by_category.get(profile_key)
            if category_size:
                sizes_by_category[category] = category_size
        # Retained for the fallback in M6 (items in a category M3 has no size
        # for) and for callers that still read a single size off the query.
        size = by_category.get("tops")

        # Build base query
        query = {
            "shape_class": shape_profile.get("shape_class"),
            "preferred_colors": preferred_colors,
            "preferred_silhouettes": style_profile.preferred_silhouettes or [],
            "k": k,
        }

        # Add categories only if explicitly provided (avoid breaking with M3's non-standard categories)
        if category_filter:
            query["categories"] = category_filter

        # Add size if available
        if size:
            query["size"] = size
        if sizes_by_category:
            query["sizes_by_category"] = sizes_by_category

        # Occasions: explicit single-occasion override takes precedence,
        # otherwise pass through everything the customer selected.
        if occasion_filter:
            query["occasions"] = [occasion_filter]
        elif style_profile.occasions:
            query["occasions"] = style_profile.occasions

        logger.debug("Retrieval query built", {"query_keys": list(query.keys())})
        return query
