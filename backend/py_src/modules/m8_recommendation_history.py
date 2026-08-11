"""
M8 — Recommendation History

Responsibility: Save and retrieve fit check history. Track product fit assessments
over time to enable trend analysis, help users understand their preferences, and
inform future recommendations.

Guardrails applied:
- ConsentTracker: verify user has consented to data processing
- AuditLogger: log all history operations for audit trail
- InputValidator: validate queries and data access
"""

from typing import Optional, List, Dict, Any
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.guardrails.access_control import AccessControl
from py_src.persistence.session_repository import SessionRepository, SQLiteSessionRepository


class RecommendationHistory:
    """Track and retrieve fit check history for users."""

    def __init__(
        self,
        session_repository: Optional[SessionRepository] = None,
        consent_tracker: Optional[ConsentTracker] = None,
    ):
        """
        Initialize history tracker.

        Args:
            session_repository: Repository for persisting fit checks
            consent_tracker: Consent tracker for data access verification
        """
        self.session_repository = session_repository or SQLiteSessionRepository()
        self.consent_tracker = consent_tracker or ConsentTracker()
        logger.info("M8 RecommendationHistory initialized")

    def save_fit_check(
        self,
        user_id: str,
        session_id: str,
        product_sku: str,
        fit_result: Dict[str, Any],
    ) -> str:
        """
        Save a fit check result to history.

        Args:
            user_id: User identifier
            session_id: Session where fit check occurred
            product_sku: Product SKU checked
            fit_result: Result dict from M7 FitChecker with fit_scores, recommended_size, etc.

        Returns:
            check_id: Unique identifier for this fit check record

        Raises:
            GuardrailError: If user has not consented to data processing
            ModuleError: If fit_result is malformed
        """
        # Verify consent
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement data processing for history tracking",
                "M8"
            )

        # Validate fit_result structure
        self._validate_fit_result(fit_result)

        # Save to repository
        check_id = self.session_repository.save_fit_check(
            user_id,
            session_id,
            product_sku,
            fit_result,
        )

        # Audit log
        AuditLogger.log_event(
            "FIT_CHECK_SAVED_TO_HISTORY",
            user_id,
            {
                "check_id": check_id,
                "session_id": session_id,
                "product_sku": product_sku,
                "recommended_size": fit_result.get("recommended_size"),
                "confidence": fit_result.get("confidence"),
            },
        )

        logger.debug(
            "Fit check saved to history",
            {
                "user_id": user_id,
                "check_id": check_id,
                "product_sku": product_sku,
            },
        )

        return check_id

    def get_user_history(
        self,
        user_id: str,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Get most recent fit checks for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of records to return (default 20)

        Returns:
            List of fit check records, most recent first

        Raises:
            GuardrailError: If user has not consented to data access
        """
        # Verify consent
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement data access",
                "M8"
            )

        # Validate limit
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ModuleError(
                "Limit must be integer 1-100",
                "M8"
            )

        records = self.session_repository.get_fit_check_history(user_id, limit)

        # Audit log
        AuditLogger.log_event(
            "HISTORY_RETRIEVED",
            user_id,
            {
                "record_count": len(records),
                "limit": limit,
            },
        )

        logger.debug(
            "User history retrieved",
            {"user_id": user_id, "count": len(records)},
        )

        return records

    def get_session_checks(
        self,
        user_id: str,
        session_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Get all fit checks from a specific session.

        Args:
            user_id: User identifier (for access control)
            session_id: Session to retrieve checks for

        Returns:
            List of fit checks from that session, chronologically ordered

        Raises:
            GuardrailError: If user doesn't own the session
        """
        # Verify consent
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement data access",
                "M8"
            )

        # Verify ownership. get_fit_check_by_session() filters only by
        # session_id (fit_check_history has no per-row access rule of its
        # own), so without this any consented user could read any other
        # user's private fit-check results just by knowing a session_id.
        session = self.session_repository.get(session_id)
        if session and not AccessControl.user_owns_resource(user_id, session.user_id):
            raise GuardrailError(
                "User does not have access to this session's history",
                "M8"
            )

        records = self.session_repository.get_fit_check_by_session(session_id)

        # Audit log
        AuditLogger.log_event(
            "SESSION_CHECKS_RETRIEVED",
            user_id,
            {
                "session_id": session_id,
                "check_count": len(records),
            },
        )

        logger.debug(
            "Session checks retrieved",
            {"session_id": session_id, "count": len(records)},
        )

        return records

    def get_product_trend(
        self,
        user_id: str,
        product_sku: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get fit check history for a specific product (trend analysis).

        Shows how a user's fit assessment of a product has changed over time.
        Useful for understanding if sizing/preferences have shifted.

        Args:
            user_id: User identifier
            product_sku: Product to analyze
            limit: Maximum records to return (default 10)

        Returns:
            List of fit checks for this product, most recent first

        Raises:
            GuardrailError: If user has not consented
            ModuleError: If inputs invalid
        """
        # Verify consent
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement data access",
                "M8"
            )

        # Validate inputs
        if not isinstance(product_sku, str) or not product_sku.strip():
            raise ModuleError(
                "Product SKU must be non-empty string",
                "M8"
            )

        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise ModuleError(
                "Limit must be integer 1-100",
                "M8"
            )

        records = self.session_repository.get_fit_check_trend(
            user_id,
            product_sku,
            limit,
        )

        logger.debug(
            "Product trend retrieved",
            {"user_id": user_id, "product_sku": product_sku, "count": len(records)},
        )

        return records

    def delete_user_history(self, user_id: str) -> int:
        """
        Delete all fit check history for a user (GDPR right-to-be-forgotten).

        Args:
            user_id: User identifier

        Returns:
            Number of records deleted

        Raises:
            GuardrailError: If user has not consented to data processing
            ModuleError: If deletion fails
        """
        # Verify consent (user must have had measurement consent to generate history)
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement data processing",
                "M8"
            )

        try:
            # Get count before deletion for audit log
            records = self.session_repository.get_fit_check_history(user_id, limit=1000)
            count = len(records)

            # Delete all records for this user
            # Using a raw delete since repository doesn't expose delete_fit_checks
            import sqlite3
            with sqlite3.connect(self.session_repository.db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM fit_check_history WHERE user_id = ?",
                    (user_id,)
                )
                conn.commit()
                deleted_count = cursor.rowcount

            # Audit log
            AuditLogger.log_event(
                "HISTORY_DELETED",
                user_id,
                {
                    "records_deleted": deleted_count,
                    "reason": "GDPR right-to-be-forgotten request",
                },
            )

            logger.info(
                "User history deleted",
                {"user_id": user_id, "count": deleted_count},
            )

            return deleted_count
        except Exception as err:
            logger.error("History deletion failed", err)
            raise ModuleError(f"Failed to delete user history: {str(err)}", "M8")

    def analyze_user_trends(self, user_id: str) -> Dict[str, Any]:
        """
        Analyze fit preferences and trends for a user.

        Computes aggregate statistics from fit check history to identify:
        - Most frequently checked products
        - Average confidence per size
        - Product categories with highest/lowest fit confidence
        - Change in confidence over time (improvement/degradation)

        Args:
            user_id: User identifier

        Returns:
            Dict with trend analysis: {
                most_checked_products: [(sku, count), ...],
                avg_confidence_by_size: {size: avg_confidence},
                preferred_sizes: [(size, frequency), ...],
                total_checks: int,
                date_range: (earliest, latest),
            }

        Raises:
            GuardrailError: If user has not consented
        """
        # Verify consent
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement data access",
                "M8"
            )

        # Get all history (no limit for aggregate analysis)
        all_records = self.session_repository.get_fit_check_history(user_id, limit=1000)

        if not all_records:
            return {
                "most_checked_products": [],
                "avg_confidence_by_size": {},
                "preferred_sizes": [],
                "total_checks": 0,
                "date_range": None,
            }

        # Aggregate analysis
        product_counts = {}
        size_confidence = {}
        size_frequency = {}

        for record in all_records:
            # Count products
            sku = record["product_sku"]
            product_counts[sku] = product_counts.get(sku, 0) + 1

            # Aggregate size data
            size = record["recommended_size"]
            confidence = record["confidence"]

            if size not in size_confidence:
                size_confidence[size] = []
            size_confidence[size].append(confidence)

            size_frequency[size] = size_frequency.get(size, 0) + 1

        # Calculate averages
        avg_confidence = {
            size: sum(confs) / len(confs)
            for size, confs in size_confidence.items()
        }

        # Sort by frequency
        most_checked = sorted(
            product_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]

        preferred_sizes = sorted(
            size_frequency.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Date range
        earliest = min(record["checked_at"] for record in all_records)
        latest = max(record["checked_at"] for record in all_records)

        result = {
            "most_checked_products": most_checked,
            "avg_confidence_by_size": avg_confidence,
            "preferred_sizes": preferred_sizes,
            "total_checks": len(all_records),
            "date_range": {
                "earliest": earliest,
                "latest": latest,
            },
        }

        AuditLogger.log_event(
            "TREND_ANALYSIS_COMPLETED",
            user_id,
            {
                "total_checks": len(all_records),
                "unique_products": len(product_counts),
                "unique_sizes": len(size_confidence),
            },
        )

        logger.debug(
            "Trend analysis completed",
            {"user_id": user_id, "checks": len(all_records)},
        )

        return result

    def _validate_fit_result(self, fit_result: Dict[str, Any]) -> None:
        """Validate fit result structure before saving."""
        required_fields = {"fit_scores", "recommended_size", "confidence"}
        missing = required_fields - set(fit_result.keys())
        if missing:
            raise ModuleError(
                f"Fit result missing required fields: {missing}",
                "M8"
            )

        if not isinstance(fit_result["fit_scores"], dict):
            raise ModuleError(
                "fit_scores must be dict",
                "M8"
            )

        if not isinstance(fit_result["recommended_size"], str):
            raise ModuleError(
                "recommended_size must be string",
                "M8"
            )

        if not isinstance(fit_result["confidence"], (int, float)):
            raise ModuleError(
                "confidence must be numeric",
                "M8"
            )

        if not (0 <= fit_result["confidence"] <= 1):
            raise ModuleError(
                "confidence must be 0-1",
                "M8"
            )
