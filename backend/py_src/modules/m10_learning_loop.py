"""
M10 — Learning Loop & Recommendation Refinement

Responsibility: Collect user feedback on fit checks and recommendations,
analyze patterns, and refine future recommendations based on feedback.

Guardrails applied:
- ConsentTracker: verify measurement consent for feedback operations
- AuditLogger: log all feedback operations
- Input validation: feedback types, confidence scores, format
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
import json
import uuid
import sqlite3
from py_src.persistence.session_repository import SessionRepository, SQLiteSessionRepository
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.constants import FIT_FEEDBACK_TYPES, PRODUCT_FEEDBACK_TYPES, STANDARD_SIZES
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.utils.logger import logger


class LearningLoop:
    """Collect and analyze feedback to refine recommendations."""

    def __init__(self, session_repo: Optional[SessionRepository] = None, consent_tracker: Optional[ConsentTracker] = None):
        """
        Initialize learning loop manager.

        Args:
            session_repo: Session repository for persistence
            consent_tracker: Consent tracker for verification
        """
        # SessionRepository is an abstract base (its methods raise
        # NotImplementedError) -- it has no feedback tables at all, so
        # defaulting to it would make every feedback call fail. Default to
        # the real SQLite-backed implementation instead, matching M1's
        # own default.
        self.session_repo = session_repo or SQLiteSessionRepository()
        self.consent_tracker = consent_tracker or ConsentTracker()
        logger.info("M10 LearningLoop initialized")

    # ========== Helper Methods (Internal) ==========

    def _verify_consent(self, user_id: str) -> None:
        """
        Verify user has measurement consent.

        Raises:
            GuardrailError: If user lacks measurement consent
        """
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement processing for feedback",
                "M10"
            )

    def _validate_fit_feedback_type(self, feedback_type: str) -> None:
        """
        Validate fit feedback type.

        Raises:
            ModuleError: If feedback_type is invalid
        """
        if feedback_type not in FIT_FEEDBACK_TYPES:
            raise ModuleError(
                f"Invalid fit feedback type: {feedback_type}. Must be one of: {', '.join(FIT_FEEDBACK_TYPES)}",
                "M10"
            )

    def _validate_product_feedback_type(self, feedback_type: str) -> None:
        """
        Validate product feedback type.

        Raises:
            ModuleError: If feedback_type is invalid
        """
        if feedback_type not in PRODUCT_FEEDBACK_TYPES:
            raise ModuleError(
                f"Invalid product feedback type: {feedback_type}. Must be one of: {', '.join(PRODUCT_FEEDBACK_TYPES)}",
                "M10"
            )

    def _validate_size(self, size: Optional[str]) -> None:
        """
        Validate size if provided.

        Raises:
            ModuleError: If size is invalid
        """
        if size and size not in STANDARD_SIZES:
            raise ModuleError(f"Invalid size: {size}", "M10")

    def _validate_rating(self, rating: Optional[float]) -> None:
        """
        Validate rating if provided.

        Raises:
            ModuleError: If rating is invalid
        """
        if rating is not None:
            if not (0 <= rating <= 5):
                raise ModuleError("Rating must be 0-5", "M10")

    def _generate_feedback_id(self, prefix: str) -> str:
        """Generate unique feedback ID using UUID."""
        return f"{prefix}-{uuid.uuid4().hex[:12]}"

    def _save_with_error_handling(self, save_fn, operation_name: str) -> None:
        """
        Execute save operation with specific error handling.

        Raises:
            ModuleError: On save failure
        """
        try:
            save_fn()
        except sqlite3.IntegrityError as err:
            logger.error(f"{operation_name} - data integrity violation", err)
            raise ModuleError(f"{operation_name} failed - duplicate or constraint violation: {str(err)}", "M10")
        except sqlite3.OperationalError as err:
            logger.error(f"{operation_name} - database operation error", err)
            raise ModuleError(f"{operation_name} failed - database error: {str(err)}", "M10")
        except Exception as err:
            logger.error(f"{operation_name} - unexpected error", err)
            raise ModuleError(f"{operation_name} failed - {type(err).__name__}: {str(err)}", "M10")

    def submit_fit_feedback(
        self,
        user_id: str,
        fit_check_id: str,
        product_sku: str,
        feedback_type: str,
        actual_size: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record user feedback on how a recommended fit actually fit.

        Args:
            user_id: User identifier
            fit_check_id: ID of the fit check being evaluated
            product_sku: Product SKU
            feedback_type: One of: too_tight, perfect, too_loose
            actual_size: Size user actually ordered (optional, XS-XXL)
            notes: Optional user notes

        Returns:
            {
              "feedback_id": "feedback-xxx",
              "user_id": user_id,
              "fit_check_id": fit_check_id,
              "feedback_type": feedback_type,
              "submitted_at": timestamp,
              "saved": True
            }

        Raises:
            ModuleError: If inputs invalid
            GuardrailError: If user lacks measurement consent
        """
        # 1. Validate inputs first (fail fast, no I/O)
        self._validate_fit_feedback_type(feedback_type)
        self._validate_size(actual_size)

        # 2. Check permissions (slower, may do I/O)
        self._verify_consent(user_id)

        # 3. Generate ID and prepare record
        feedback_id = self._generate_feedback_id("feedback")
        feedback_record = {
            "feedback_id": feedback_id,
            "user_id": user_id,
            "fit_check_id": fit_check_id,
            "product_sku": product_sku,
            "feedback_type": feedback_type,
            "actual_size": actual_size,
            "notes": notes,
            "submitted_at": datetime.now().timestamp(),
        }

        # 4. Save and audit log
        self._save_with_error_handling(
            lambda: self.session_repo.save_feedback(user_id, feedback_record),
            "Fit feedback save"
        )

        AuditLogger.log_event(
            "FIT_FEEDBACK_SUBMITTED",
            user_id,
            {
                "feedback_id": feedback_id,
                "product_sku": product_sku,
                "feedback_type": feedback_type,
                "size_mismatch": actual_size is not None,
            },
        )

        logger.info(
            "Fit feedback submitted",
            {"user_id": user_id, "product_sku": product_sku, "feedback_type": feedback_type}
        )

        return {
            "feedback_id": feedback_id,
            "user_id": user_id,
            "fit_check_id": fit_check_id,
            "feedback_type": feedback_type,
            "submitted_at": feedback_record["submitted_at"],
            "saved": True,
        }

    def submit_product_feedback(
        self,
        user_id: str,
        product_sku: str,
        feedback_type: str,
        purchased: bool = False,
        rating: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record user feedback on a product (satisfaction).

        Args:
            user_id: User identifier
            product_sku: Product SKU
            feedback_type: One of: liked, disliked, neutral
            purchased: Whether user purchased this product (optional)
            rating: Optional satisfaction rating (0-5)
            notes: Optional user notes

        Returns:
            {
              "feedback_id": "product-feedback-xxx",
              "product_sku": product_sku,
              "feedback_type": feedback_type,
              "submitted_at": timestamp,
              "saved": True
            }

        Raises:
            ModuleError: If inputs invalid
            GuardrailError: If user lacks measurement consent
        """
        # 1. Validate inputs first (fail fast, no I/O)
        self._validate_product_feedback_type(feedback_type)
        self._validate_rating(rating)

        # 2. Check permissions (slower, may do I/O)
        self._verify_consent(user_id)

        # 3. Generate ID and prepare record
        feedback_id = self._generate_feedback_id("product-feedback")
        feedback_record = {
            "feedback_id": feedback_id,
            "user_id": user_id,
            "product_sku": product_sku,
            "feedback_type": feedback_type,
            "purchased": purchased,
            "rating": rating,
            "notes": notes,
            "submitted_at": datetime.now().timestamp(),
        }

        # 4. Save and audit log
        self._save_with_error_handling(
            lambda: self.session_repo.save_product_feedback(user_id, feedback_record),
            "Product feedback save"
        )

        AuditLogger.log_event(
            "PRODUCT_FEEDBACK_SUBMITTED",
            user_id,
            {
                "feedback_id": feedback_id,
                "product_sku": product_sku,
                "feedback_type": feedback_type,
                "purchased": purchased,
            },
        )

        logger.info(
            "Product feedback submitted",
            {"user_id": user_id, "product_sku": product_sku, "feedback_type": feedback_type}
        )

        return {
            "feedback_id": feedback_id,
            "product_sku": product_sku,
            "feedback_type": feedback_type,
            "submitted_at": feedback_record["submitted_at"],
            "saved": True,
        }

    def get_user_feedback_summary(self, user_id: str) -> Dict[str, Any]:
        """
        Get aggregate feedback statistics for a user.

        Args:
            user_id: User identifier

        Returns:
            {
              "user_id": user_id,
              "fit_feedback_stats": {
                "total": 5,
                "perfect": 3,
                "tight": 1,
                "loose": 1,
                "perfect_percentage": 0.6
              },
              "product_feedback_stats": {
                "liked": 3,
                "disliked": 1,
                "neutral": 2
              },
              "total_feedback_records": 8
            }

        Raises:
            GuardrailError: If user lacks measurement consent
            ModuleError: If retrieval fails
        """
        # Verify consent first
        self._verify_consent(user_id)

        try:
            # Retrieve all feedback from repo
            fit_feedback = self.session_repo.get_user_fit_feedback(user_id) or []
            product_feedback = self.session_repo.get_user_product_feedback(user_id) or []

            # Calculate fit feedback statistics
            fit_stats = {
                "total": len(fit_feedback),
                "perfect": len([f for f in fit_feedback if f.get("feedback_type") == "perfect"]),
                "tight": len([f for f in fit_feedback if f.get("feedback_type") == "too_tight"]),
                "loose": len([f for f in fit_feedback if f.get("feedback_type") == "too_loose"]),
            }

            fit_stats["perfect_percentage"] = (
                fit_stats["perfect"] / fit_stats["total"] if fit_stats["total"] > 0 else 0
            )

            # Calculate product feedback statistics
            product_stats = {
                "liked": len([f for f in product_feedback if f.get("feedback_type") == "liked"]),
                "disliked": len([f for f in product_feedback if f.get("feedback_type") == "disliked"]),
                "neutral": len([f for f in product_feedback if f.get("feedback_type") == "neutral"]),
            }

            # Audit log
            AuditLogger.log_event(
                "FEEDBACK_SUMMARY_RETRIEVED",
                user_id,
                {"total_fit_feedback": fit_stats["total"], "product_feedback_count": len(product_feedback)},
            )

            return {
                "user_id": user_id,
                "fit_feedback_stats": fit_stats,
                "product_feedback_stats": product_stats,
                "total_feedback_records": len(fit_feedback) + len(product_feedback),
            }
        except GuardrailError:
            raise
        except Exception as err:
            logger.error("Failed to get feedback summary", err)
            raise ModuleError(f"Failed to retrieve feedback summary: {str(err)}", "M10")

    def get_size_adjustment_factors(self, shape_class: str, size: str) -> Dict[str, float]:
        """
        Get adjustment factors for size recommendations based on feedback patterns.

        FUTURE FEATURE (Phase 5): Will analyze feedback for all users with same
        shape_class/size and compute confidence adjustments if systematic bias exists.

        Example: If pear-shaped users getting size M fit perfectly 80% of the time
        but M7's data showed 0.75 confidence, will return adjustment factor of 1.07x.

        Args:
            shape_class: Body shape class (e.g., "pear", "hourglass")
            size: Size to analyze (e.g., "M")

        Returns:
            (Not yet implemented)

        Raises:
            NotImplementedError: Feature not yet implemented (planned for Phase 5)
        """
        raise NotImplementedError(
            "Size adjustment factors calculation is not yet implemented. "
            "This feature is planned for Phase 5. Currently, M7 uses fixed confidence scores. "
            "See: GitHub Issue #M10-SIZE-ADJUSTMENT"
        )
