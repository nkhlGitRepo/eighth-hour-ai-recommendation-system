"""Comprehensive tests for M8 — Recommendation History."""

import pytest
import tempfile
import os
from unittest.mock import MagicMock, patch
from py_src.modules.m8_recommendation_history import RecommendationHistory
from py_src.modules.m1_intake_orchestrator import IntakeSession
from py_src.persistence.session_repository import SQLiteSessionRepository
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.utils.errors import ModuleError, GuardrailError


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def session_repository(temp_db):
    """Session repository with temporary database."""
    return SQLiteSessionRepository(db_path=temp_db)


@pytest.fixture
def consent_tracker():
    """Consent tracker with measurement consent granted."""
    tracker = ConsentTracker()
    tracker.record_consent(user_id="test_user", photo_consent=True, measurement_consent=True)
    return tracker


@pytest.fixture
def history_tracker(session_repository, consent_tracker):
    """Recommendation history tracker."""
    return RecommendationHistory(
        session_repository=session_repository,
        consent_tracker=consent_tracker,
    )


@pytest.fixture
def sample_fit_result():
    """Sample fit check result."""
    return {
        "product_sku": "top-123",
        "fit_scores": {"XS": 0.6, "S": 0.8, "M": 1.0, "L": 0.7},
        "recommended_size": "M",
        "fit_notes": ["Fits perfectly.", "Size M is a good fit."],
        "confidence": 1.0,
    }


class TestM8SaveFitCheck:
    """Test saving fit checks to history."""

    def test_saves_fit_check_successfully(self, history_tracker, sample_fit_result):
        """Should save fit check and return check_id."""
        check_id = history_tracker.save_fit_check(
            "test_user",
            "sess-123",
            "top-123",
            sample_fit_result,
        )

        assert check_id is not None
        assert check_id.startswith("check_")

    def test_check_id_is_unique(self, history_tracker, sample_fit_result):
        """Each save should produce a unique check_id."""
        id1 = history_tracker.save_fit_check(
            "test_user", "sess-123", "top-123", sample_fit_result
        )
        id2 = history_tracker.save_fit_check(
            "test_user", "sess-456", "top-456", sample_fit_result
        )

        assert id1 != id2

    def test_saves_all_fit_result_data(self, history_tracker, sample_fit_result):
        """All fields from fit_result should be persisted."""
        check_id = history_tracker.save_fit_check(
            "test_user", "sess-123", "top-123", sample_fit_result
        )

        history = history_tracker.get_user_history("test_user", limit=1)
        assert len(history) == 1

        record = history[0]
        assert record["check_id"] == check_id
        assert record["product_sku"] == "top-123"
        assert record["recommended_size"] == "M"
        assert record["confidence"] == 1.0
        assert record["fit_scores"] == sample_fit_result["fit_scores"]
        assert record["fit_notes"] == sample_fit_result["fit_notes"]

    def test_rejects_without_measurement_consent(self, session_repository):
        """Should reject save if user hasn't consented to measurements."""
        tracker_no_consent = ConsentTracker()
        tracker_no_consent.record_consent(
            user_id="no_consent",
            photo_consent=True,
            measurement_consent=False,
        )
        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=tracker_no_consent,
        )

        fit_result = {"fit_scores": {}, "recommended_size": "M", "confidence": 1.0}
        with pytest.raises(GuardrailError, match="consented"):
            history.save_fit_check("no_consent", "sess-123", "sku", fit_result)

    def test_rejects_unrecorded_user(self, session_repository):
        """Should reject if user has no consent record at all."""
        empty_tracker = ConsentTracker()
        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=empty_tracker,
        )

        fit_result = {"fit_scores": {}, "recommended_size": "M", "confidence": 1.0}
        with pytest.raises(GuardrailError):
            history.save_fit_check("unknown_user", "sess-123", "sku", fit_result)

    def test_rejects_missing_fit_result_fields(self, history_tracker):
        """Should reject fit_result missing required fields."""
        incomplete = {"fit_scores": {}, "recommended_size": "M"}  # Missing confidence
        with pytest.raises(ModuleError, match="required fields"):
            history_tracker.save_fit_check(
                "test_user", "sess-123", "sku", incomplete
            )

    def test_rejects_invalid_fit_scores_type(self, history_tracker):
        """fit_scores must be dict."""
        bad_result = {
            "fit_scores": "not a dict",
            "recommended_size": "M",
            "confidence": 1.0,
        }
        with pytest.raises(ModuleError, match="dict"):
            history_tracker.save_fit_check(
                "test_user", "sess-123", "sku", bad_result
            )

    def test_rejects_invalid_recommended_size_type(self, history_tracker):
        """recommended_size must be string."""
        bad_result = {
            "fit_scores": {},
            "recommended_size": 42,
            "confidence": 1.0,
        }
        with pytest.raises(ModuleError, match="string"):
            history_tracker.save_fit_check(
                "test_user", "sess-123", "sku", bad_result
            )

    def test_rejects_invalid_confidence_type(self, history_tracker):
        """confidence must be numeric."""
        bad_result = {
            "fit_scores": {},
            "recommended_size": "M",
            "confidence": "high",
        }
        with pytest.raises(ModuleError, match="numeric"):
            history_tracker.save_fit_check(
                "test_user", "sess-123", "sku", bad_result
            )

    def test_rejects_confidence_out_of_range(self, history_tracker):
        """confidence must be 0-1."""
        bad_result = {
            "fit_scores": {},
            "recommended_size": "M",
            "confidence": 1.5,
        }
        with pytest.raises(ModuleError, match="0-1"):
            history_tracker.save_fit_check(
                "test_user", "sess-123", "sku", bad_result
            )


class TestM8UserHistory:
    """Test retrieving user fit check history."""

    def test_retrieves_user_history(self, history_tracker, sample_fit_result):
        """Should retrieve all fit checks for a user."""
        history_tracker.save_fit_check("test_user", "sess-1", "top-1", sample_fit_result)
        history_tracker.save_fit_check("test_user", "sess-2", "top-2", sample_fit_result)
        history_tracker.save_fit_check("test_user", "sess-3", "top-3", sample_fit_result)

        history = history_tracker.get_user_history("test_user")
        assert len(history) == 3

    def test_history_ordered_newest_first(self, history_tracker, sample_fit_result):
        """History should be ordered most recent first - ALL items, not just first 3."""
        # Save with slight delays to ensure timestamp ordering
        import time
        ids = []
        for i in range(10):
            check_id = history_tracker.save_fit_check("test_user", f"sess-{i}", f"top-{i}", sample_fit_result)
            ids.append(check_id)
            time.sleep(0.001)

        history = history_tracker.get_user_history("test_user", limit=10)

        # Verify ALL items are in correct order (newest first)
        returned_ids = [record["check_id"] for record in history]
        expected_order = list(reversed(ids))  # Reverse since we saved in ascending order
        assert returned_ids == expected_order, \
            f"History ordering broken. Expected {expected_order}, got {returned_ids}"

    def test_respects_limit_parameter(self, history_tracker, sample_fit_result):
        """Should limit results based on limit parameter."""
        for i in range(30):
            history_tracker.save_fit_check(
                "test_user", f"sess-{i}", f"top-{i}", sample_fit_result
            )

        history_10 = history_tracker.get_user_history("test_user", limit=10)
        history_50 = history_tracker.get_user_history("test_user", limit=50)

        assert len(history_10) == 10
        assert len(history_50) == 30  # Only 30 saved, so max is 30

    def test_rejects_invalid_limit(self, history_tracker):
        """Limit must be integer 1-100."""
        with pytest.raises(ModuleError, match="1-100"):
            history_tracker.get_user_history("test_user", limit=0)

        with pytest.raises(ModuleError, match="1-100"):
            history_tracker.get_user_history("test_user", limit=101)

        with pytest.raises(ModuleError, match="1-100"):
            history_tracker.get_user_history("test_user", limit="ten")

    def test_rejects_without_measurement_consent(self, session_repository):
        """Should reject retrieval if user hasn't consented."""
        tracker = ConsentTracker()
        tracker.record_consent(user_id="test_user", photo_consent=True, measurement_consent=False)
        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=tracker,
        )

        with pytest.raises(GuardrailError, match="consented"):
            history.get_user_history("test_user")

    def test_empty_history_returns_empty_list(self, session_repository):
        """User with consent but no fit checks should return empty list."""
        tracker = ConsentTracker()
        tracker.record_consent(user_id="new_user", photo_consent=True, measurement_consent=True)
        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=tracker,
        )
        result = history.get_user_history("new_user")
        assert result == []


class TestM8SessionChecks:
    """Test retrieving fit checks by session."""

    def test_retrieves_session_checks(self, history_tracker, sample_fit_result):
        """Should retrieve all checks from a specific session."""
        history_tracker.save_fit_check("test_user", "sess-123", "top-1", sample_fit_result)
        history_tracker.save_fit_check("test_user", "sess-123", "top-2", sample_fit_result)
        history_tracker.save_fit_check("test_user", "sess-456", "top-3", sample_fit_result)

        sess_123_checks = history_tracker.get_session_checks("test_user", "sess-123")
        sess_456_checks = history_tracker.get_session_checks("test_user", "sess-456")

        assert len(sess_123_checks) == 2
        assert len(sess_456_checks) == 1

    def test_session_checks_ordered_chronologically(self, history_tracker, sample_fit_result):
        """Session checks should be ordered most recent first."""
        import time
        id1 = history_tracker.save_fit_check("test_user", "sess-123", "top-1", sample_fit_result)
        time.sleep(0.01)
        id2 = history_tracker.save_fit_check("test_user", "sess-123", "top-2", sample_fit_result)

        checks = history_tracker.get_session_checks("test_user", "sess-123")
        assert checks[0]["check_id"] == id2
        assert checks[1]["check_id"] == id1

    def test_rejects_without_consent(self, session_repository):
        """Should reject session check retrieval without consent."""
        tracker = ConsentTracker()
        tracker.record_consent(user_id="test_user", photo_consent=True, measurement_consent=False)
        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=tracker,
        )

        with pytest.raises(GuardrailError):
            history.get_session_checks("test_user", "sess-123")

    def test_empty_session_returns_empty_list(self, history_tracker):
        """Session with no checks should return empty list."""
        checks = history_tracker.get_session_checks("test_user", "nonexistent-session")
        assert checks == []


class TestM8SessionOwnership:
    """
    Regression tests for a real, live cross-user data leak: get_fit_check_by_session()
    filters only by session_id (no user_id constraint at all), so without an
    explicit ownership check, any consented user could read any other user's
    private fit-check results just by knowing (or guessing) a session_id.
    """

    def test_non_owner_cannot_read_another_users_session(self, session_repository):
        owner_tracker = ConsentTracker(db_path=session_repository.db_path)
        owner_tracker.record_consent("owner-user", photo_consent=True, measurement_consent=True)
        owner_tracker.record_consent("attacker-user", photo_consent=True, measurement_consent=True)

        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=owner_tracker,
        )

        # A real intake session actually owned by "owner-user".
        session = IntakeSession(user_id="owner-user")
        session_repository.save(session)

        history.save_fit_check("owner-user", session.session_id, "top-private", {
            "fit_scores": {"M": 1.0},
            "recommended_size": "M",
            "confidence": 1.0,
        })

        # A consented, but otherwise unrelated, second user must not be able
        # to read the first user's session history.
        with pytest.raises(GuardrailError, match="does not have access"):
            history.get_session_checks("attacker-user", session.session_id)

    def test_owner_can_still_read_their_own_session(self, session_repository):
        tracker = ConsentTracker(db_path=session_repository.db_path)
        tracker.record_consent("owner-user", photo_consent=True, measurement_consent=True)

        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=tracker,
        )

        session = IntakeSession(user_id="owner-user")
        session_repository.save(session)
        history.save_fit_check("owner-user", session.session_id, "top-1", {
            "fit_scores": {"M": 1.0},
            "recommended_size": "M",
            "confidence": 1.0,
        })

        checks = history.get_session_checks("owner-user", session.session_id)
        assert len(checks) == 1

    def test_session_with_no_matching_intake_record_is_not_blocked(self, history_tracker, sample_fit_result):
        """
        Fit checks saved against a session_id with no corresponding row in
        the intake_sessions table (e.g. legacy data, or a session_id from a
        different system) should not be blocked -- there's no real owner to
        compare against, so the ownership check must no-op rather than deny
        everyone.
        """
        history_tracker.save_fit_check("test_user", "orphan-session", "top-1", sample_fit_result)
        checks = history_tracker.get_session_checks("test_user", "orphan-session")
        assert len(checks) == 1


class TestM8ProductTrend:
    """Test product-specific trend analysis."""

    def test_retrieves_product_trend(self, history_tracker, sample_fit_result):
        """Should get fit check history for a specific product."""
        history_tracker.save_fit_check("test_user", "sess-1", "top-123", sample_fit_result)
        history_tracker.save_fit_check("test_user", "sess-2", "top-456", sample_fit_result)
        history_tracker.save_fit_check("test_user", "sess-3", "top-123", sample_fit_result)

        trend = history_tracker.get_product_trend("test_user", "top-123")
        assert len(trend) == 2
        for record in trend:
            assert record["product_sku"] == "top-123"

    def test_product_trend_ordered_newest_first(self, history_tracker, sample_fit_result):
        """Product trend should be most recent first."""
        import time
        id1 = history_tracker.save_fit_check("test_user", "sess-1", "top-123", sample_fit_result)
        time.sleep(0.01)
        id2 = history_tracker.save_fit_check("test_user", "sess-2", "top-123", sample_fit_result)

        trend = history_tracker.get_product_trend("test_user", "top-123")
        assert trend[0]["check_id"] == id2
        assert trend[1]["check_id"] == id1

    def test_respects_trend_limit(self, history_tracker, sample_fit_result):
        """Should respect limit parameter for trends."""
        for i in range(15):
            history_tracker.save_fit_check("test_user", f"sess-{i}", "top-123", sample_fit_result)

        trend_5 = history_tracker.get_product_trend("test_user", "top-123", limit=5)
        trend_20 = history_tracker.get_product_trend("test_user", "top-123", limit=20)

        assert len(trend_5) == 5
        assert len(trend_20) == 15  # Only 15 saved

    def test_rejects_invalid_sku(self, history_tracker):
        """Product SKU must be non-empty string."""
        with pytest.raises(ModuleError, match="non-empty string"):
            history_tracker.get_product_trend("test_user", "")

        with pytest.raises(ModuleError, match="non-empty string"):
            history_tracker.get_product_trend("test_user", 123)

    def test_rejects_invalid_limit(self, history_tracker):
        """Limit must be 1-100."""
        with pytest.raises(ModuleError, match="1-100"):
            history_tracker.get_product_trend("test_user", "top-123", limit=0)

    def test_rejects_without_consent(self, session_repository):
        """Should reject without measurement consent."""
        tracker = ConsentTracker()
        tracker.record_consent(user_id="test_user", photo_consent=True, measurement_consent=False)
        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=tracker,
        )

        with pytest.raises(GuardrailError):
            history.get_product_trend("test_user", "top-123")


class TestM8TrendAnalysis:
    """Test aggregate trend analysis."""

    def test_analyzes_user_trends(self, history_tracker, sample_fit_result):
        """Should compute aggregate statistics from fit history."""
        # Save diverse fit checks
        fit_m = {**sample_fit_result, "recommended_size": "M", "confidence": 1.0}
        fit_l = {**sample_fit_result, "recommended_size": "L", "confidence": 0.9}
        fit_s = {**sample_fit_result, "recommended_size": "S", "confidence": 0.7}

        history_tracker.save_fit_check("test_user", "sess-1", "top-123", fit_m)
        history_tracker.save_fit_check("test_user", "sess-2", "top-123", fit_m)
        history_tracker.save_fit_check("test_user", "sess-3", "top-456", fit_l)
        history_tracker.save_fit_check("test_user", "sess-4", "top-789", fit_s)

        analysis = history_tracker.analyze_user_trends("test_user")

        assert analysis["total_checks"] == 4
        assert len(analysis["most_checked_products"]) > 0
        assert len(analysis["preferred_sizes"]) > 0
        assert len(analysis["avg_confidence_by_size"]) > 0

    def test_identifies_most_checked_products(self, history_tracker, sample_fit_result):
        """Should identify which products checked most frequently, in correct order."""
        for i in range(5):
            history_tracker.save_fit_check("test_user", f"sess-{i}", "top-123", sample_fit_result)
        for i in range(3):
            history_tracker.save_fit_check("test_user", f"sess-{i+10}", "top-456", sample_fit_result)
        for i in range(2):
            history_tracker.save_fit_check("test_user", f"sess-{i+20}", "top-789", sample_fit_result)

        analysis = history_tracker.analyze_user_trends("test_user")

        # Verify COMPLETE ordering: [5, 3, 2]
        most_checked = analysis["most_checked_products"]
        assert len(most_checked) >= 3, f"Expected at least 3 products, got {len(most_checked)}"
        assert most_checked[0] == ("top-123", 5), f"1st: expected ('top-123', 5), got {most_checked[0]}"
        assert most_checked[1] == ("top-456", 3), f"2nd: expected ('top-456', 3), got {most_checked[1]}"
        assert most_checked[2] == ("top-789", 2), f"3rd: expected ('top-789', 2), got {most_checked[2]}"

    def test_calculates_average_confidence_per_size(self, history_tracker):
        """Should calculate average confidence by size with correct divisor."""
        # Test with multiple sample counts to catch divisor off-by-one bugs
        # Single sample: avg of 1.0 should be 1.0
        result_1 = {
            "product_sku": "top",
            "fit_scores": {},
            "recommended_size": "M",
            "confidence": 1.0,
            "fit_notes": [],
        }
        # Two samples: (1.0 + 0.8) / 2 = 0.9
        result_2 = {
            "product_sku": "top",
            "fit_scores": {},
            "recommended_size": "M",
            "confidence": 0.8,
            "fit_notes": [],
        }
        # Three samples: (1.0 + 0.8 + 0.6) / 3 = 0.8 (catches divisor=2 bugs)
        result_3 = {
            "product_sku": "top",
            "fit_scores": {},
            "recommended_size": "M",
            "confidence": 0.6,
            "fit_notes": [],
        }

        history_tracker.save_fit_check("test_user", "sess-1", "top-1", result_1)
        history_tracker.save_fit_check("test_user", "sess-2", "top-2", result_2)
        history_tracker.save_fit_check("test_user", "sess-3", "top-3", result_3)

        analysis = history_tracker.analyze_user_trends("test_user")

        # Verify exact average calculations
        m_avg = analysis["avg_confidence_by_size"]["M"]
        expected_avg = (1.0 + 0.8 + 0.6) / 3
        assert m_avg == expected_avg, \
            f"Average confidence wrong: expected {expected_avg}, got {m_avg}"

    def test_includes_date_range(self, history_tracker, sample_fit_result):
        """Should include earliest and latest check timestamps."""
        import time
        history_tracker.save_fit_check("test_user", "sess-1", "top-1", sample_fit_result)
        time.sleep(0.01)
        history_tracker.save_fit_check("test_user", "sess-2", "top-2", sample_fit_result)

        analysis = history_tracker.analyze_user_trends("test_user")

        assert "date_range" in analysis
        assert analysis["date_range"]["earliest"] < analysis["date_range"]["latest"]

    def test_empty_history_returns_empty_analysis(self, session_repository):
        """User with consent but no history should return empty analysis."""
        tracker = ConsentTracker()
        tracker.record_consent(user_id="new_user", photo_consent=True, measurement_consent=True)
        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=tracker,
        )
        analysis = history.analyze_user_trends("new_user")

        assert analysis["total_checks"] == 0
        assert analysis["most_checked_products"] == []
        assert analysis["avg_confidence_by_size"] == {}
        assert analysis["preferred_sizes"] == []

    def test_rejects_without_consent(self, session_repository):
        """Should reject analysis without consent."""
        tracker = ConsentTracker()
        tracker.record_consent(user_id="test_user", photo_consent=True, measurement_consent=False)
        history = RecommendationHistory(
            session_repository=session_repository,
            consent_tracker=tracker,
        )

        with pytest.raises(GuardrailError):
            history.analyze_user_trends("test_user")


class TestM8Integration:
    """Test M8 integration with M7 (fit checker results)."""

    def test_m7_result_format_compatible_with_save(self, history_tracker):
        """M7 fit result format should be fully compatible with M8 save_fit_check()."""
        # Simulate real M7 output structure
        m7_result = {
            "product_sku": "top-123",
            "fit_scores": {"XS": 0.6, "S": 0.8, "M": 1.0, "L": 0.7},
            "recommended_size": "M",
            "fit_notes": ["Size M fits perfectly.", "Recommended for hourglass shapes."],
            "confidence": 1.0,
        }

        # Should successfully save without errors
        check_id = history_tracker.save_fit_check(
            "test_user",
            "sess-123",
            "top-123",
            m7_result
        )

        # Should successfully retrieve with exact structure
        history = history_tracker.get_user_history("test_user", limit=1)
        assert len(history) == 1

        record = history[0]
        assert record["check_id"] == check_id
        assert record["product_sku"] == "top-123"
        assert record["recommended_size"] == "M"
        assert record["confidence"] == 1.0

        # Verify complex fields are preserved
        assert record["fit_scores"] == {"XS": 0.6, "S": 0.8, "M": 1.0, "L": 0.7}
        assert record["fit_notes"] == ["Size M fits perfectly.", "Recommended for hourglass shapes."]


class TestM8AuditLogging:
    """Test audit trail logging."""

    def test_logs_fit_check_save(self, history_tracker, sample_fit_result):
        """Should log when fit check is saved."""
        with patch.object(AuditLogger, "log_event") as mock_log:
            history_tracker.save_fit_check("test_user", "sess-123", "top-123", sample_fit_result)

            # Verify log_event was called
            assert mock_log.called
            call_args = mock_log.call_args[0]
            assert call_args[0] == "FIT_CHECK_SAVED_TO_HISTORY"
            assert call_args[1] == "test_user"

    def test_logs_history_retrieval(self, history_tracker, sample_fit_result):
        """Should log when history is retrieved."""
        history_tracker.save_fit_check("test_user", "sess-123", "top-123", sample_fit_result)

        with patch.object(AuditLogger, "log_event") as mock_log:
            history_tracker.get_user_history("test_user")

            call_args = mock_log.call_args[0]
            assert call_args[0] == "HISTORY_RETRIEVED"

    def test_logs_trend_analysis(self, history_tracker, sample_fit_result):
        """Should log when trend analysis is performed."""
        history_tracker.save_fit_check("test_user", "sess-123", "top-123", sample_fit_result)

        with patch.object(AuditLogger, "log_event") as mock_log:
            history_tracker.analyze_user_trends("test_user")

            call_args = mock_log.call_args[0]
            assert call_args[0] == "TREND_ANALYSIS_COMPLETED"
