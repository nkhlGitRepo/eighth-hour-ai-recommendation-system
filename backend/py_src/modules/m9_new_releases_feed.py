"""
M9 — Personalized New Releases Feed

Responsibility: Surface newly launched products matched to each customer's
stored profile. Event-driven: when a new product launches, score it against
all customer profiles and surface high-match items in their feed.

Guardrails applied:
- ConsentTracker: verify measurement consent before processing (same check M3/M5/M7 use)
- CatalogKB: retrieve real, in-stock, actually-recent products only
- FitChecker (M7): deterministic validation that items are available in recommended size
- AuditLogger: log all feed operations
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.utils.sizing import infer_size_from_bust, validate_measurements, extract_physical_measurements
from py_src.constants import NEW_RELEASES_MATCH_THRESHOLD, NEW_RELEASES_WINDOW_DAYS
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.modules.m6_catalog_kb import CatalogKB, shape_affinity_score
from py_src.modules.m7_fit_checker import FitChecker


class NewReleasesFeed:
    """Generate and manage personalized new releases feeds for users."""

    # Match score threshold for surfacing (0-1) - configurable
    MATCH_THRESHOLD = NEW_RELEASES_MATCH_THRESHOLD

    def __init__(
        self,
        catalog: Optional[CatalogKB] = None,
        fit_checker: Optional[FitChecker] = None,
        consent_tracker: Optional[ConsentTracker] = None,
        match_threshold: float = NEW_RELEASES_MATCH_THRESHOLD,
    ):
        """
        Initialize new releases feed manager.

        Args:
            catalog: Catalog knowledge base for product retrieval
            fit_checker: Fit checker for product availability validation
            consent_tracker: Consent tracker for measurement consent verification
            match_threshold: Minimum match score to include in feed (0-1, default 0.65)
        """
        self.catalog = catalog or CatalogKB([])
        self.consent_tracker = consent_tracker or ConsentTracker()
        # Ensure fit_checker uses same consent_tracker instance
        if fit_checker:
            self.fit_checker = fit_checker
        else:
            self.fit_checker = FitChecker(consent_tracker=self.consent_tracker)

        # Validate threshold
        if not (0 <= match_threshold <= 1):
            raise ModuleError("match_threshold must be 0-1", "M9")
        self.match_threshold = match_threshold

        logger.info("M9 NewReleasesFeed initialized", {"threshold": match_threshold})

    def score_product_for_profile(
        self,
        product: Dict[str, Any],
        body_shape_profile: Optional[Dict[str, Any]] = None,
        style_profile: Optional[Dict[str, Any]] = None,
        measurements: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Score how well a product matches a user's profiles.

        Scoring logic:
        1. Shape matching: does product fit user's shape class? (0-1)
        2. Style matching: colors, silhouettes, occasions (0-1)
        3. Availability: is product in user's recommended size? (0 or 1)
        4. Average these components

        Args:
            product: Product dict from catalog
            body_shape_profile: User's shape profile (shape_class, ratios, etc.)
            style_profile: User's style profile (colors, silhouettes, etc.)
            measurements: User's measurements (for fit validation)

        Returns:
            Match score 0-1 (0 = no match, 1 = perfect match)
        """
        scores = []

        # Shape matching
        if body_shape_profile:
            shape_score = self._score_shape_match(product, body_shape_profile)
            scores.append(shape_score)

        # Style matching
        if style_profile:
            style_score = self._score_style_match(product, style_profile)
            scores.append(style_score)

        # Availability matching
        if measurements and "sizes" in product:
            availability_score = self._score_availability(product, measurements)
            scores.append(availability_score)

        # Average scores
        if scores:
            return sum(scores) / len(scores)
        return 0.5  # Neutral score if no profiles provided

    def generate_feed(
        self,
        user_id: str,
        body_shape_profile: Optional[Dict[str, Any]],
        style_profile: Optional[Dict[str, Any]],
        measurements: Optional[Dict[str, float]],
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Generate personalized new releases feed for a user.

        Retrieves recent products from catalog and scores them against user profiles.
        Only returns products above match threshold.

        Args:
            user_id: User identifier
            body_shape_profile: User's body shape profile
            style_profile: User's style preferences
            measurements: User's body measurements (required if fit checking enabled)
            limit: Maximum number of items to return (default 20)

        Returns:
            List of new release items with match scores, sorted by relevance
            Each item: {
              "sku": "...",
              "name": "...",
              "match_score": 0.85,
              "matched_attributes": ["color match", "silhouette", "fits your shape"],
              "reason": "Flatters your shape and matches your color preferences",
              "availability": {"recommended_size": "M", "available_sizes": ["XS", "S", "M", "L"]}
            }

        Raises:
            GuardrailError: If user has not consented to measurement processing
            ModuleError: If inputs invalid
        """
        # Verify measurement consent BEFORE any processing
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement processing for new releases feed",
                "M9"
            )

        # Callers may pass a full Measurements.to_dict() payload (unit,
        # confidence_scores, provider, ...) rather than a clean measurements
        # dict -- strip it down before validating/using it.
        if measurements:
            measurements = extract_physical_measurements(measurements)
            try:
                validate_measurements(measurements)
            except ModuleError as err:
                raise ModuleError(err.message, "M9")

        # Validate inputs
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ModuleError("Limit must be integer 1-100", "M9")

        if not body_shape_profile and not style_profile:
            raise ModuleError(
                "At least one profile (shape or style) required",
                "M9"
            )

        # CatalogKB.items is a dict keyed by sku, not a list of items.
        all_products = list(self.catalog.items.values()) if hasattr(self.catalog, 'items') else []

        # Only products actually launched within the recency window count as
        # "new releases" -- otherwise this is just the recommendation engine
        # again under a different name.
        recent_products = [p for p in all_products if self._is_recent(p)]

        if not recent_products:
            return []

        # Score each product
        scored_products = []
        for product in recent_products:
            score = self.score_product_for_profile(
                product,
                body_shape_profile,
                style_profile,
                measurements,
            )

            # Only include if above threshold
            if score >= self.match_threshold:
                matched_attrs = self._identify_match_attributes(
                    product,
                    body_shape_profile,
                    style_profile,
                )
                reason = self._generate_match_reason(
                    product,
                    matched_attrs,
                    body_shape_profile,
                )

                # Get availability in user's size
                availability = None
                if measurements:
                    try:
                        fit_result = self.fit_checker.check_fit(
                            user_id,
                            measurements,
                            product,
                        )
                        rec_size = fit_result.get("recommended_size")
                        availability = {
                            "recommended_size": rec_size,
                            "available_sizes": product.get("sizes", []),
                        }
                    except (ModuleError, GuardrailError) as err:
                        logger.warn(
                            f"Fit check failed for {product.get('sku')}: {str(err)}",
                            {"product_sku": product.get("sku")}
                        )
                        availability = {"available_sizes": product.get("sizes", [])}
                    except Exception as err:
                        logger.error(
                            f"Unexpected error checking fit for {product.get('sku')}",
                            err
                        )
                        availability = {"available_sizes": product.get("sizes", [])}

                scored_products.append({
                    "sku": product.get("sku"),
                    "name": product.get("name"),
                    "category": product.get("category"),
                    "match_score": round(score, 2),
                    "matched_attributes": matched_attrs,
                    "reason": reason,
                    "availability": availability,
                })

        # Sort by score (highest first)
        scored_products.sort(key=lambda x: x["match_score"], reverse=True)

        # Apply limit
        feed = scored_products[:limit]

        # Audit log
        AuditLogger.log_event(
            "NEW_RELEASES_FEED_GENERATED",
            user_id,
            {
                "feed_size": len(feed),
                "total_scored": len(scored_products),
                "threshold": self.match_threshold,
            },
        )

        logger.debug(
            "New releases feed generated",
            {"user_id": user_id, "items": len(feed)},
        )

        return feed

    def _is_recent(self, product: Dict[str, Any]) -> bool:
        """
        A product counts as a "new release" only if it actually launched
        within the recency window. Products with no launched_at are treated
        as legacy catalog items, not new -- otherwise every item with
        missing metadata would incorrectly show up as "new".
        """
        launched_at = product.get("launched_at")
        if not launched_at:
            return False
        try:
            launch_date = datetime.fromisoformat(launched_at)
        except (ValueError, TypeError):
            return False
        return datetime.now() - launch_date <= timedelta(days=NEW_RELEASES_WINDOW_DAYS)

    def _score_shape_match(
        self,
        product: Dict[str, Any],
        body_shape_profile: Dict[str, Any],
    ) -> float:
        """Score how well product flatters user's shape."""
        user_shape = body_shape_profile.get("shape_class")
        if not user_shape:
            return 0.5

        # Shared with M6's ranking -- see shape_affinity_score() for why a
        # single float already produces the same "specific match beats
        # general category affinity" ordering M9 and M6 both rely on.
        return shape_affinity_score(user_shape, product)

    def _score_style_match(
        self,
        product: Dict[str, Any],
        style_profile: Dict[str, Any],
    ) -> float:
        """Score how well product matches user's style preferences."""
        scores = []

        # Color matching
        user_colors = style_profile.get("preferred_colors", [])
        product_colors = product.get("colors", [])
        if user_colors and product_colors:
            matching_colors = set(user_colors) & set(product_colors)
            color_score = len(matching_colors) / len(user_colors) if user_colors else 0
            scores.append(color_score)

        # Silhouette matching. The catalog stores a single silhouette_class
        # string per product (not a list called "silhouettes"), so this is
        # a membership check, not a set intersection.
        user_silhouettes = style_profile.get("preferred_silhouettes", [])
        product_silhouette = product.get("silhouette_class")
        if user_silhouettes and product_silhouette:
            sil_score = 1.0 if product_silhouette in user_silhouettes else 0.0
            scores.append(sil_score)

        # Occasion matching
        user_occasions = style_profile.get("occasions", [])
        product_occasions = product.get("occasions", [])
        if user_occasions and product_occasions:
            matching_occasions = set(user_occasions) & set(product_occasions)
            occasion_score = len(matching_occasions) / len(user_occasions)
            scores.append(occasion_score)

        # Average style scores
        if scores:
            return sum(scores) / len(scores)
        return 0.5

    def _score_availability(
        self,
        product: Dict[str, Any],
        measurements: Dict[str, float],
    ) -> float:
        """Score product availability in user's size (binary: 1.0 or 0.0)."""
        try:
            # Check if product has any size options
            available_sizes = product.get("sizes", [])
            if not available_sizes:
                return 0.0

            # Infer user's size from measurements
            user_size = self._infer_size_from_measurements(measurements)
            if user_size in available_sizes:
                return 1.0
            return 0.0
        except Exception as err:
            logger.debug("Availability scoring failed", err)
            return 0.5

    def _identify_match_attributes(
        self,
        product: Dict[str, Any],
        body_shape_profile: Optional[Dict[str, Any]],
        style_profile: Optional[Dict[str, Any]],
    ) -> List[str]:
        """Identify which attributes led to match."""
        attrs = []

        if body_shape_profile:
            shape = body_shape_profile.get("shape_class")
            if shape in product.get("flatters_shapes", []):
                attrs.append(f"Flatters {shape} shapes")

        if style_profile:
            colors = style_profile.get("preferred_colors", [])
            product_colors = product.get("colors", [])
            if colors and product_colors:
                matches = set(colors) & set(product_colors)
                if matches:
                    attrs.append(f"Available in your colors ({', '.join(list(matches)[:2])})")

            silhouettes = style_profile.get("preferred_silhouettes", [])
            product_silhouette = product.get("silhouette_class")
            if silhouettes and product_silhouette and product_silhouette in silhouettes:
                attrs.append("Your silhouette style")

        if not attrs:
            attrs.append("Matches your profile")

        return attrs

    def _generate_match_reason(
        self,
        product: Dict[str, Any],
        matched_attributes: List[str],
        body_shape_profile: Optional[Dict[str, Any]],
    ) -> str:
        """Generate customer-facing explanation of match."""
        reasons = []

        if matched_attributes:
            reasons.append(f"We think you'll like this because {matched_attributes[0].lower()}")

        if body_shape_profile:
            reasons.append(f"and it's selected for {body_shape_profile.get('shape_class')} shapes")

        reason = " ".join(reasons) if reasons else "This item matches your style"
        return reason + "."

    def _infer_size_from_measurements(self, measurements: Dict[str, float]) -> str:
        """Infer size from measurements using shared utility."""
        bust = measurements.get("bust", 0)
        return infer_size_from_bust(bust)
