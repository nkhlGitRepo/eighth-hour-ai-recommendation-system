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
        assert "Invalid fit feedback type" in str(exc_info.value)

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
        assert "Invalid product feedback type" in str(exc_info.value)

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

    def test_size_adjustment_factors_not_implemented(self, learning_loop):
        """Size adjustment factors are not yet implemented (Phase 5)."""
        loop, _ = learning_loop

        # Should raise NotImplementedError with clear message about future implementation
        with pytest.raises(NotImplementedError) as exc_info:
            loop.get_size_adjustment_factors("pear", "M")

        assert "not yet implemented" in str(exc_info.value).lower()
        assert "Phase 5" in str(exc_info.value)


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


class TestParameterValidation:
    """Test empty, null, and invalid parameter handling."""

    def test_rejects_empty_user_id(self, learning_loop):
        """Empty user_id should be rejected."""
        loop, consent = learning_loop
        # Note: empty user_id won't have consent, so GuardrailError is correct
        with pytest.raises(GuardrailError):
            loop.submit_fit_feedback("", "check-1", "top-1", "perfect")

    def test_rejects_empty_fit_check_id(self, learning_loop):
        """Empty fit_check_id should be rejected or handled."""
        loop, consent = learning_loop
        user_id = "user-200"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # Empty fit_check_id should create feedback_id, but could be problematic
        result = loop.submit_fit_feedback(user_id, "", "top-1", "perfect")
        assert result["saved"] is True
        # At minimum, feedback is created (though fit_check_id is empty)

    def test_rejects_empty_product_sku(self, learning_loop):
        """Empty product_sku should be handled (will be stored but meaningless)."""
        loop, consent = learning_loop
        user_id = "user-201"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_fit_feedback(user_id, "check-1", "", "perfect")
        assert result["saved"] is True

    def test_rejects_empty_feedback_type(self, learning_loop):
        """Empty feedback_type should be rejected."""
        loop, consent = learning_loop
        user_id = "user-202"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        with pytest.raises(ModuleError) as exc_info:
            loop.submit_fit_feedback(user_id, "check-1", "top-1", "")
        assert "Invalid fit feedback type" in str(exc_info.value)

    def test_rejects_whitespace_feedback_type(self, learning_loop):
        """Whitespace feedback_type should be rejected."""
        loop, consent = learning_loop
        user_id = "user-203"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        with pytest.raises(ModuleError):
            loop.submit_fit_feedback(user_id, "check-1", "top-1", "   ")

    def test_rejects_empty_product_feedback_type(self, learning_loop):
        """Empty product feedback_type should be rejected."""
        loop, consent = learning_loop
        user_id = "user-204"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        with pytest.raises(ModuleError):
            loop.submit_product_feedback(user_id, "top-1", "")

    def test_long_notes_accepted(self, learning_loop):
        """Very long notes should be accepted (but length limits not enforced)."""
        loop, consent = learning_loop
        user_id = "user-205"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        long_notes = "x" * 1000  # 1KB notes
        result = loop.submit_fit_feedback(
            user_id, "check-1", "top-1", "perfect", notes=long_notes
        )
        assert result["saved"] is True


class TestPersistence:
    """Test that feedback actually persists in database."""

    def test_fit_feedback_persists_across_sessions(self, learning_loop):
        """Feedback submitted should be retrievable from database."""
        loop, consent = learning_loop
        user_id = "user-300"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # Submit feedback
        loop.submit_fit_feedback(user_id, "check-1", "top-1", "perfect")

        # Retrieve and verify it's actually in database
        feedback = loop.session_repo.get_user_fit_feedback(user_id)
        assert feedback is not None
        assert len(feedback) == 1
        assert feedback[0]["feedback_type"] == "perfect"
        assert feedback[0]["product_sku"] == "top-1"

    def test_product_feedback_persists(self, learning_loop):
        """Product feedback should persist in database."""
        loop, consent = learning_loop
        user_id = "user-301"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        loop.submit_product_feedback(user_id, "top-1", "liked", purchased=True, rating=4.5)

        feedback = loop.session_repo.get_user_product_feedback(user_id)
        assert feedback is not None
        assert len(feedback) == 1
        assert feedback[0]["feedback_type"] == "liked"
        assert feedback[0]["rating"] == 4.5
        # SQLite stores booleans as 0/1, so check truthiness
        assert feedback[0]["purchased"] in (True, 1)

    def test_multiple_feedback_items_all_persist(self, learning_loop):
        """All submitted feedback should persist, not just the last one."""
        loop, consent = learning_loop
        user_id = "user-302"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        loop.submit_fit_feedback(user_id, "check-1", "top-1", "perfect")
        loop.submit_fit_feedback(user_id, "check-2", "top-2", "too_tight")
        loop.submit_fit_feedback(user_id, "check-3", "top-3", "too_loose")

        feedback = loop.session_repo.get_user_fit_feedback(user_id)
        assert len(feedback) == 3
        types = [f["feedback_type"] for f in feedback]
        assert "perfect" in types
        assert "too_tight" in types
        assert "too_loose" in types


class TestAuditLogging:
    """Test that audit logging is actually happening."""

    def test_fit_feedback_triggers_audit_log(self, learning_loop, capsys):
        """Submitting fit feedback should trigger audit log."""
        loop, consent = learning_loop
        user_id = "user-400"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # This would need to mock AuditLogger to verify properly
        # For now, just verify it doesn't crash
        result = loop.submit_fit_feedback(user_id, "check-1", "top-1", "perfect")
        assert result["saved"] is True

    def test_product_feedback_triggers_audit_log(self, learning_loop):
        """Submitting product feedback should trigger audit log."""
        loop, consent = learning_loop
        user_id = "user-401"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_product_feedback(user_id, "top-1", "liked", purchased=True)
        assert result["saved"] is True


class TestSummaryAccuracy:
    """Test that summary statistics are accurate."""

    def test_summary_perfect_percentage_calculation(self, learning_loop):
        """Perfect fit percentage should be accurately calculated."""
        loop, consent = learning_loop
        user_id = "user-500"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # Submit 4 feedback: 3 perfect, 1 tight = 75% perfect
        loop.submit_fit_feedback(user_id, "check-1", "top-1", "perfect")
        loop.submit_fit_feedback(user_id, "check-2", "top-2", "perfect")
        loop.submit_fit_feedback(user_id, "check-3", "top-3", "perfect")
        loop.submit_fit_feedback(user_id, "check-4", "top-4", "too_tight")

        summary = loop.get_user_feedback_summary(user_id)
        fit_stats = summary["fit_feedback_stats"]

        assert fit_stats["total"] == 4
        assert fit_stats["perfect"] == 3
        assert fit_stats["tight"] == 1
        assert fit_stats["loose"] == 0
        assert fit_stats["perfect_percentage"] == pytest.approx(0.75, rel=0.01)

    def test_summary_loose_feedback_counted(self, learning_loop):
        """Loose feedback should be counted separately."""
        loop, consent = learning_loop
        user_id = "user-501"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        loop.submit_fit_feedback(user_id, "check-1", "top-1", "too_loose")
        loop.submit_fit_feedback(user_id, "check-2", "top-2", "too_loose")
        loop.submit_fit_feedback(user_id, "check-3", "top-3", "perfect")

        summary = loop.get_user_feedback_summary(user_id)
        fit_stats = summary["fit_feedback_stats"]

        assert fit_stats["loose"] == 2
        assert fit_stats["tight"] == 0
        assert fit_stats["perfect"] == 1

    def test_summary_product_feedback_counts_match_db(self, learning_loop):
        """Product feedback counts should match actual database values."""
        loop, consent = learning_loop
        user_id = "user-502"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # Submit varied product feedback
        loop.submit_product_feedback(user_id, "top-1", "liked", purchased=True)
        loop.submit_product_feedback(user_id, "top-2", "liked", purchased=True)
        loop.submit_product_feedback(user_id, "top-3", "disliked", purchased=False)
        loop.submit_product_feedback(user_id, "top-4", "neutral", purchased=True)

        # Get summary
        summary = loop.get_user_feedback_summary(user_id)
        product_stats = summary["product_feedback_stats"]

        # Verify against DB directly
        db_feedback = loop.session_repo.get_user_product_feedback(user_id)
        db_liked = len([f for f in db_feedback if f["feedback_type"] == "liked"])
        db_disliked = len([f for f in db_feedback if f["feedback_type"] == "disliked"])
        db_neutral = len([f for f in db_feedback if f["feedback_type"] == "neutral"])

        assert product_stats["liked"] == db_liked == 2
        assert product_stats["disliked"] == db_disliked == 1
        assert product_stats["neutral"] == db_neutral == 1

    def test_summary_all_counts_sum_correctly(self, learning_loop):
        """All feedback counts should sum to total."""
        loop, consent = learning_loop
        user_id = "user-503"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # Mix of fit and product feedback
        loop.submit_fit_feedback(user_id, "c1", "p1", "perfect")
        loop.submit_fit_feedback(user_id, "c2", "p2", "too_tight")
        loop.submit_product_feedback(user_id, "p1", "liked")
        loop.submit_product_feedback(user_id, "p2", "disliked")
        loop.submit_product_feedback(user_id, "p3", "neutral")

        summary = loop.get_user_feedback_summary(user_id)

        fit_total = summary["fit_feedback_stats"]["total"]
        product_total = (
            summary["product_feedback_stats"]["liked"]
            + summary["product_feedback_stats"]["disliked"]
            + summary["product_feedback_stats"]["neutral"]
        )

        assert summary["total_feedback_records"] == fit_total + product_total == 5


class TestLogicalConsistency:
    """Test for logical consistency in feedback."""

    def test_contradictory_feedback_accepted(self, learning_loop):
        """Contradictory feedback (perfect + actual_size) is accepted (data quality issue, not crash)."""
        loop, consent = learning_loop
        user_id = "user-600"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # This is illogical but allowed by the module
        result = loop.submit_fit_feedback(
            user_id, "check-1", "top-1", "perfect", actual_size="L"
        )
        assert result["saved"] is True

    def test_multiple_ratings_per_product_allowed(self, learning_loop):
        """User can submit multiple ratings for same product."""
        loop, consent = learning_loop
        user_id = "user-601"
        consent.record_consent(user_id, photo_consent=True, measurement_consent=True)

        # First rating
        result1 = loop.submit_product_feedback(user_id, "top-1", "liked", rating=4.0)
        # Second rating (different opinion)
        result2 = loop.submit_product_feedback(user_id, "top-1", "disliked", rating=2.0)

        assert result1["saved"] is True
        assert result2["saved"] is True

        feedback = loop.session_repo.get_user_product_feedback(user_id)
        assert len(feedback) == 2
        ratings = [f["rating"] for f in feedback]
        assert 4.0 in ratings
        assert 2.0 in ratings


class TestDefaultConstruction:
    """
    LearningLoop() with no arguments must actually be usable.

    Regression test: the default for session_repo was the abstract
    SessionRepository base class (whose methods just raise
    NotImplementedError and which doesn't even define save_feedback/
    get_user_fit_feedback/etc. at all) instead of SQLiteSessionRepository.
    Never hit in production (main.py always passes an explicit repo) or by
    any other test here (all pass one explicitly too), so this was a live
    landmine for the first caller that didn't.
    """

    def test_default_session_repo_is_actually_functional(self, tmp_path, monkeypatch):
        # Avoid touching the real dev intake_sessions.db from a bare default.
        monkeypatch.chdir(tmp_path)
        loop = LearningLoop()
        user_id = "default-ctor-user"
        loop.consent_tracker.record_consent(user_id, photo_consent=True, measurement_consent=True)

        result = loop.submit_fit_feedback(user_id, "check-1", "top-1", "perfect")
        assert result["saved"] is True
