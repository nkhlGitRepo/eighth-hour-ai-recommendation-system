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
from py_src.persistence.session_repository import SessionRepository
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.utils.logger import logger


class LearningLoop:
    """Collect and analyze feedback to refine recommendations."""

    # Valid feedback types for fit assessments
    VALID_FIT_FEEDBACK = ["too_tight", "perfect", "too_loose"]

    # Valid feedback types for products
    VALID_PRODUCT_FEEDBACK = ["liked", "disliked", "neutral"]

    def __init__(self, session_repo: Optional[SessionRepository] = None, consent_tracker: Optional[ConsentTracker] = None):
        """
        Initialize learning loop manager.

        Args:
            session_repo: Session repository for persistence
            consent_tracker: Consent tracker for verification
        """
        self.session_repo = session_repo or SessionRepository()
        self.consent_tracker = consent_tracker or ConsentTracker()
        logger.info("M10 LearningLoop initialized")

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
            feedback_type: "too_tight", "perfect", or "too_loose"
            actual_size: Size user actually ordered (if different from recommended)
            notes: Optional user notes

        Returns:
            {
              "feedback_id": "uuid-...",
              "user_id": "...",
              "fit_check_id": "...",
              "feedback_type": "perfect",
              "submitted_at": 1691111111.0,
              "saved": true
            }

        Raises:
            GuardrailError: If user lacks measurement consent
            ModuleError: If inputs invalid
        """
        # Verify consent
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement processing for feedback",
                "M10"
            )

        # Validate feedback type
        if feedback_type not in self.VALID_FIT_FEEDBACK:
            raise ModuleError(
                f"Invalid feedback type: {feedback_type}. Must be one of: {', '.join(self.VALID_FIT_FEEDBACK)}",
                "M10"
            )

        # Validate actual_size if provided
        valid_sizes = ["XS", "S", "M", "L", "XL", "XXL"]
        if actual_size and actual_size not in valid_sizes:
            raise ModuleError(f"Invalid size: {actual_size}", "M10")

        # Generate unique feedback ID (use UUID to prevent collisions)
        feedback_id = f"feedback-{uuid.uuid4().hex[:12]}"

        # Prepare feedback record
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

        # Save feedback
        try:
            # Store in session repository's feedback table
            self.session_repo.save_feedback(user_id, feedback_record)

            # Audit log
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
        except Exception as err:
            logger.error("Failed to save fit feedback", err)
            raise ModuleError(f"Failed to save feedback: {str(err)}", "M10")

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
        Record user feedback on a product (satisfaction, would recommend).

        Args:
            user_id: User identifier
            product_sku: Product SKU
            feedback_type: "liked", "disliked", or "neutral"
            purchased: Whether user purchased this product
            rating: Optional satisfaction rating (0-5)
            notes: Optional user notes

        Returns:
            {
              "feedback_id": "uuid-...",
              "product_sku": "...",
              "feedback_type": "liked",
              "submitted_at": 1691111111.0,
              "saved": true
            }

        Raises:
            GuardrailError: If user lacks consent
            ModuleError: If inputs invalid
        """
        # Verify consent
        if not self.consent_tracker.has_measurement_consent(user_id):
            raise GuardrailError(
                "User has not consented to measurement processing for feedback",
                "M10"
            )

        # Validate feedback type
        if feedback_type not in self.VALID_PRODUCT_FEEDBACK:
            raise ModuleError(
                f"Invalid feedback type: {feedback_type}. Must be one of: {', '.join(self.VALID_PRODUCT_FEEDBACK)}",
                "M10"
            )

        # Validate rating if provided
        if rating is not None:
            if not (0 <= rating <= 5):
                raise ModuleError("Rating must be 0-5", "M10")

        # Generate unique feedback ID (use UUID to prevent collisions)
        feedback_id = f"product-feedback-{uuid.uuid4().hex[:12]}"

        # Prepare feedback record
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

        # Save feedback
        try:
            self.session_repo.save_product_feedback(user_id, feedback_record)

            # Audit log
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
        except Exception as err:
            logger.error("Failed to save product feedback", err)
            raise ModuleError(f"Failed to save feedback: {str(err)}", "M10")

    def get_user_feedback_summary(self, user_id: str) -> Dict[str, Any]:
        """
        Get aggregate feedback statistics for a user.

        Returns:
        {
          "user_id": "...",
          "total_fit_feedback": 5,
          "perfect_fit_percentage": 0.6,
          "size_accuracy": {
            "recommended_size": "M",
            "correct_count": 3,
            "tight_count": 1,
            "loose_count": 1,
            "accuracy_percentage": 0.6
          },
          "most_liked_categories": ["Dresses", "Tops"],
          "product_feedback_summary": {
            "liked_count": 3,
            "disliked_count": 1,
            "neutral_count": 2
          }
        }
        """
        try:
            # Verify consent
            if not self.consent_tracker.has_measurement_consent(user_id):
                raise GuardrailError("User lacks measurement consent", "M10")

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

        This would be used to refine M7 fit recommendations by:
        1. Analyzing feedback for all users with same shape_class/size
        2. Computing "confidence adjustment" if feedback shows systematic bias
        3. Example: if pear-shaped users getting size M fit perfectly 80% of the time
                    but data showed 0.75 confidence, adjust factor to 1.07x

        Args:
            shape_class: Body shape class (e.g., "pear", "hourglass")
            size: Size to analyze (e.g., "M")

        Returns:
            {
              "shape_class": "pear",
              "size": "M",
              "confidence_adjustment": 1.05,  # Increase future confidence by 5%
              "size_shift_probability": {"tight": 0.1, "perfect": 0.8, "loose": 0.1},
              "samples": 15,  # Number of feedback records analyzed
              "recommendation": "Recommended size is reliable"
            }
        """
        try:
            # In production, this would:
            # 1. Query feedback table for all records matching shape_class/size
            # 2. Group by feedback_type (perfect/tight/loose)
            # 3. Calculate probabilities and confidence adjustment
            # 4. Return factors to M7 for refined scoring

            # For now, return default (no adjustment)
            return {
                "shape_class": shape_class,
                "size": size,
                "confidence_adjustment": 1.0,
                "samples": 0,
                "recommendation": "Insufficient feedback data",
            }
        except Exception as err:
            logger.error("Failed to calculate size adjustment factors", err)
            raise ModuleError(f"Failed to calculate adjustment factors: {str(err)}", "M10")
