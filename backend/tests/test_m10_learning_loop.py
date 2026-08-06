"""
Comprehensive tests for M10 — Learning Loop & Recommendation Refinement
"""

import pytest
import json
import tempfile
import os
from datetime import datetime
from py_src.modules.m10_learning_loop import LearningLoop
from py_src.persistence.session_repository import SQLiteSessionRepository
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.utils.errors import ModuleError, GuardrailError


@pytest.fixture
def learning_loop():
    """Initialize learning loop with fresh repo and consent tracker."""
    # Use a temporary file-based database for each test (avoids in-memory isolation issues)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    session_repo = SQLiteSessionRepository(db_path)
    consent_tracker = ConsentTracker()
    loop = LearningLoop(session_repo=session_repo, consent_tracker=consent_tracker), consent_tracker

    yield loop

    # Cleanup
    try:
        os.unlink(db_path)
    except:
        pass


class TestFitFeedbackSubmission:
    """Test fit feedback collection."""

    def test_submit_valid_fit_feedback_perfect(self, learning_loop):
        """User submits feedback that recommended size fit perfectly."""
        loop, consent = learning_loop
        user_id = "user-1"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_fit_feedback(
            user_id=user_id,
            fit_check_id="check-123",
            product_sku="top-456",
            feedback_type="perfect",
            notes="Fit as expected",
        )

        assert result["feedback_id"].startswith("feedback-")
        assert result["user_id"] == user_id
        assert result["feedback_type"] == "perfect"
        assert result["saved"] is True
        assert "submitted_at" in result

    def test_submit_fit_feedback_too_tight(self, learning_loop):
        """User submits feedback that size was too tight."""
        loop, consent = learning_loop
        user_id = "user-2"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_fit_feedback(
            user_id=user_id,
            fit_check_id="check-124",
            product_sku="top-457",
            feedback_type="too_tight",
            actual_size="L",
        )

        assert result["feedback_type"] == "too_tight"
        assert result["saved"] is True

    def test_submit_fit_feedback_too_loose(self, learning_loop):
        """User submits feedback that size was too loose."""
        loop, consent = learning_loop
        user_id = "user-3"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_fit_feedback(
            user_id=user_id,
            fit_check_id="check-125",
            product_sku="top-458",
            feedback_type="too_loose",
            actual_size="S",
        )

        assert result["feedback_type"] == "too_loose"

    def test_rejects_invalid_feedback_type(self, learning_loop):
        """Invalid feedback type raises ModuleError."""
        loop, consent = learning_loop
        user_id = "user-4"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        with pytest.raises(ModuleError) as exc_info:
            loop.submit_fit_feedback(
                user_id=user_id,
                fit_check_id="check-126",
                product_sku="top-459",
                feedback_type="maybe_fit",  # Invalid
            )
        assert "Invalid feedback type" in str(exc_info.value)

    def test_rejects_invalid_size(self, learning_loop):
        """Invalid actual_size raises ModuleError."""
        loop, consent = learning_loop
        user_id = "user-5"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        with pytest.raises(ModuleError) as exc_info:
            loop.submit_fit_feedback(
                user_id=user_id,
                fit_check_id="check-127",
                product_sku="top-460",
                feedback_type="perfect",
                actual_size="XXXL",  # Invalid
            )
        assert "Invalid size" in str(exc_info.value)

    def test_requires_measurement_consent(self, learning_loop):
        """Submitting feedback without measurement consent raises GuardrailError."""
        loop, consent = learning_loop
        user_id = "user-6"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=False)

        with pytest.raises(GuardrailError) as exc_info:
            loop.submit_fit_feedback(
                user_id=user_id,
                fit_check_id="check-128",
                product_sku="top-461",
                feedback_type="perfect",
            )
        assert "consented" in str(exc_info.value).lower()

    def test_all_valid_sizes_accepted(self, learning_loop):
        """All standard sizes (XS-XXL) are accepted."""
        loop, consent = learning_loop
        user_id = "user-7"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        valid_sizes = ["XS", "S", "M", "L", "XL", "XXL"]
        for size in valid_sizes:
            result = loop.submit_fit_feedback(
                user_id=user_id,
                fit_check_id=f"check-{size}",
                product_sku="top-462",
                feedback_type="perfect",
                actual_size=size,
            )
            assert result["saved"] is True

    def test_actual_size_optional(self, learning_loop):
        """actual_size is optional when not needed."""
        loop, consent = learning_loop
        user_id = "user-8"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_fit_feedback(
            user_id=user_id,
            fit_check_id="check-129",
            product_sku="top-463",
            feedback_type="perfect",
            # No actual_size provided
        )
        assert result["saved"] is True


class TestProductFeedback:
    """Test product satisfaction feedback."""

    def test_submit_product_feedback_liked(self, learning_loop):
        """User submits positive product feedback."""
        loop, consent = learning_loop
        user_id = "user-9"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_product_feedback(
            user_id=user_id,
            product_sku="top-464",
            feedback_type="liked",
            purchased=True,
            rating=4.5,
            notes="Great quality",
        )

        assert result["feedback_id"].startswith("product-feedback-")
        assert result["feedback_type"] == "liked"
        assert result["saved"] is True

    def test_submit_product_feedback_disliked(self, learning_loop):
        """User submits negative product feedback."""
        loop, consent = learning_loop
        user_id = "user-10"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_product_feedback(
            user_id=user_id,
            product_sku="top-465",
            feedback_type="disliked",
            purchased=True,
            rating=2.0,
        )

        assert result["feedback_type"] == "disliked"

    def test_submit_product_feedback_neutral(self, learning_loop):
        """User submits neutral product feedback."""
        loop, consent = learning_loop
        user_id = "user-11"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_product_feedback(
            user_id=user_id,
            product_sku="top-466",
            feedback_type="neutral",
        )

        assert result["feedback_type"] == "neutral"

    def test_rating_validated_0_to_5(self, learning_loop):
        """Rating must be between 0-5."""
        loop, consent = learning_loop
        user_id = "user-12"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # Valid rating
        result = loop.submit_product_feedback(
            user_id=user_id,
            product_sku="top-467",
            feedback_type="liked",
            rating=5.0,
        )
        assert result["saved"] is True

        # Invalid rating (too high)
        with pytest.raises(ModuleError) as exc_info:
            loop.submit_product_feedback(
                user_id=user_id,
                product_sku="top-468",
                feedback_type="liked",
                rating=6.0,
            )
        assert "must be 0-5" in str(exc_info.value)

        # Invalid rating (negative)
        with pytest.raises(ModuleError):
            loop.submit_product_feedback(
                user_id=user_id,
                product_sku="top-469",
                feedback_type="liked",
                rating=-1.0,
            )

    def test_purchased_flag_optional(self, learning_loop):
        """purchased flag defaults to False."""
        loop, consent = learning_loop
        user_id = "user-13"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_product_feedback(
            user_id=user_id,
            product_sku="top-470",
            feedback_type="liked",
            # No purchased flag
        )
        assert result["saved"] is True

    def test_rejects_invalid_product_feedback_type(self, learning_loop):
        """Invalid product feedback type raises ModuleError."""
        loop, consent = learning_loop
        user_id = "user-14"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        with pytest.raises(ModuleError) as exc_info:
            loop.submit_product_feedback(
                user_id=user_id,
                product_sku="top-471",
                feedback_type="love_it",  # Invalid
            )
        assert "Invalid feedback type" in str(exc_info.value)

    def test_product_feedback_requires_consent(self, learning_loop):
        """Product feedback requires measurement consent."""
        loop, consent = learning_loop
        user_id = "user-15"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=False)

        with pytest.raises(GuardrailError):
            loop.submit_product_feedback(
                user_id=user_id,
                product_sku="top-472",
                feedback_type="liked",
            )


class TestFeedbackSummary:
    """Test feedback aggregation and summary."""

    def test_feedback_summary_empty_user(self, learning_loop):
        """User with no feedback returns zero counts."""
        loop, consent = learning_loop
        user_id = "user-16"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        summary = loop.get_user_feedback_summary(user_id)

        assert summary["user_id"] == user_id
        assert summary["fit_feedback_stats"]["total"] == 0
        assert summary["product_feedback_stats"]["liked"] == 0

    def test_feedback_summary_with_fit_feedback(self, learning_loop):
        """Summary includes fit feedback statistics."""
        loop, consent = learning_loop
        user_id = "user-17"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # Submit multiple feedback
        loop.submit_fit_feedback(user_id, "check-1", "top-1", "perfect")
        loop.submit_fit_feedback(user_id, "check-2", "top-2", "perfect")
        loop.submit_fit_feedback(user_id, "check-3", "top-3", "too_tight")

        summary = loop.get_user_feedback_summary(user_id)

        fit_stats = summary["fit_feedback_stats"]
        assert fit_stats["total"] == 3
        assert fit_stats["perfect"] == 2
        assert fit_stats["tight"] == 1
        assert fit_stats["perfect_percentage"] == pytest.approx(2 / 3, rel=0.01)

    def test_feedback_summary_with_product_feedback(self, learning_loop):
        """Summary includes product feedback statistics."""
        loop, consent = learning_loop
        user_id = "user-18"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        loop.submit_product_feedback(user_id, "top-10", "liked", purchased=True)
        loop.submit_product_feedback(user_id, "top-11", "liked", purchased=True)
        loop.submit_product_feedback(user_id, "top-12", "disliked", purchased=True)
        loop.submit_product_feedback(user_id, "top-13", "neutral", purchased=False)

        summary = loop.get_user_feedback_summary(user_id)

        product_stats = summary["product_feedback_stats"]
        assert product_stats["liked"] == 2
        assert product_stats["disliked"] == 1
        assert product_stats["neutral"] == 1

    def test_feedback_summary_combined(self, learning_loop):
        """Summary combines fit and product feedback counts."""
        loop, consent = learning_loop
        user_id = "user-19"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        loop.submit_fit_feedback(user_id, "check-1", "top-1", "perfect")
        loop.submit_fit_feedback(user_id, "check-2", "top-2", "perfect")
        loop.submit_product_feedback(user_id, "top-1", "liked", purchased=True)

        summary = loop.get_user_feedback_summary(user_id)

        assert summary["fit_feedback_stats"]["total"] == 2
        assert summary["product_feedback_stats"]["liked"] == 1
        assert summary["total_feedback_records"] == 3

    def test_summary_requires_consent(self, learning_loop):
        """Requesting summary without measurement consent raises GuardrailError."""
        loop, consent = learning_loop
        user_id = "user-20"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=False)

        with pytest.raises(GuardrailError):
            loop.get_user_feedback_summary(user_id)


class TestSizeAdjustmentFactors:
    """Test recommendation refinement factors."""

    def test_size_adjustment_factors_default(self, learning_loop):
        """Without feedback data, returns default adjustment (1.0x)."""
        loop, _ = learning_loop

        factors = loop.get_size_adjustment_factors("pear", "M")

        assert factors["shape_class"] == "pear"
        assert factors["size"] == "M"
        assert factors["confidence_adjustment"] == 1.0
        assert factors["samples"] == 0


class TestIntegration:
    """Integration tests across feedback submission and summary."""

    def test_multiple_users_independent_feedback(self, learning_loop):
        """Feedback from multiple users stored independently."""
        loop, consent = learning_loop

        user1_id = "user-100"
        user2_id = "user-101"
        consent.record_consent(user1_id, photo_consent=True, measurement_consent=True)
        consent.record_consent(user2_id, photo_consent=True, measurement_consent=True)

        # User 1 submits feedback
        loop.submit_fit_feedback(user1_id, "check-1", "top-1", "perfect")
        loop.submit_product_feedback(user1_id, "top-1", "liked", purchased=True)

        # User 2 submits different feedback
        loop.submit_fit_feedback(user2_id, "check-2", "top-2", "too_tight")
        loop.submit_product_feedback(user2_id, "top-2", "disliked", purchased=True)

        # Verify user 1 summary
        summary1 = loop.get_user_feedback_summary(user1_id)
        assert summary1["fit_feedback_stats"]["perfect"] == 1
        assert summary1["product_feedback_stats"]["liked"] == 1

        # Verify user 2 summary (independent)
        summary2 = loop.get_user_feedback_summary(user2_id)
        assert summary2["fit_feedback_stats"]["tight"] == 1
        assert summary2["product_feedback_stats"]["disliked"] == 1

    def test_feedback_timeline(self, learning_loop):
        """Feedback timestamps increase as expected."""
        loop, consent = learning_loop
        user_id = "user-102"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        import time

        result1 = loop.submit_fit_feedback(user_id, "check-1", "top-1", "perfect")
        time.sleep(0.01)  # Small delay
        result2 = loop.submit_fit_feedback(user_id, "check-2", "top-2", "perfect")

        assert result2["submitted_at"] >= result1["submitted_at"]
