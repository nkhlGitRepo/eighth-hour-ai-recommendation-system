"""Tests for M1 — Intake Orchestrator (state machine)."""

import pytest
import tempfile
import os
from py_src.modules.m1_intake_orchestrator import (
    IntakeOrchestrator,
    IntakeSession,
    IntakeState,
)
from py_src.persistence.session_repository import SQLiteSessionRepository
from py_src.utils.errors import GuardrailError, ModuleError


@pytest.fixture
def orchestrator():
    """Fresh orchestrator instance with isolated database for each test."""
    # Create a temporary database file for this test
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = temp_db.name
    temp_db.close()

    # Create orchestrator with temp database
    repo = SQLiteSessionRepository(db_path=db_path)
    orch = IntakeOrchestrator(session_repo=repo)

    yield orch

    # Clean up the temp database after test
    try:
        os.unlink(db_path)
    except:
        pass


class TestIntakeSessionCreation:
    """Test creating and retrieving intake sessions."""

    def test_create_session(self, orchestrator):
        """Create a new intake session and verify persistence."""
        session = orchestrator.create_session(user_id="test_user")
        assert session.user_id == "test_user"
        assert session.status == IntakeState.INITIATED.value
        assert len(session.photo_refs) == 0
        assert session.body_measurements is None
        assert session.shape_profile is None

        # Verify persistence: retrieve from database
        retrieved = orchestrator.get_session(session.session_id)
        assert retrieved.user_id == "test_user"
        assert retrieved.status == IntakeState.INITIATED.value
        assert retrieved.session_id == session.session_id

    def test_create_session_invalid_user_id(self, orchestrator):
        """Reject invalid user_id."""
        with pytest.raises(ModuleError):
            orchestrator.create_session(user_id="")

    def test_get_session(self, orchestrator):
        """Retrieve an existing session."""
        session = orchestrator.create_session(user_id="test_user")
        retrieved = orchestrator.get_session(session.session_id)
        assert retrieved.session_id == session.session_id

    def test_get_session_not_found(self, orchestrator):
        """Raise error if session doesn't exist."""
        with pytest.raises(ModuleError, match="not found"):
            orchestrator.get_session("nonexistent_id")


class TestConsentFlow:
    """Test consent recording and state transitions."""

    def test_record_consent_success(self, orchestrator):
        """Record consent and verify persistence."""
        session = orchestrator.create_session(user_id="test_user")
        updated = orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        assert updated.status == IntakeState.PHOTO_CAPTURE.value
        assert updated.consent_record["photo"] is True
        assert updated.consent_record["measurements"] is True
        assert "timestamp" in updated.consent_record

        # Verify persistence: retrieve from database
        retrieved = orchestrator.get_session(session.session_id)
        assert retrieved.consent_record["photo"] is True
        assert retrieved.consent_record["measurements"] is True
        # Verify state transition persisted
        assert retrieved.status == IntakeState.PHOTO_CAPTURE.value

    def test_record_consent_photo_only(self, orchestrator):
        """Reject consent if only photo accepted."""
        session = orchestrator.create_session(user_id="test_user")
        with pytest.raises(GuardrailError):
            orchestrator.record_consent(
                session.session_id,
                photo_consent=True,
                measurement_consent=False,
            )

    def test_record_consent_measurement_only(self, orchestrator):
        """Reject consent if only measurement accepted."""
        session = orchestrator.create_session(user_id="test_user")
        with pytest.raises(GuardrailError):
            orchestrator.record_consent(
                session.session_id,
                photo_consent=False,
                measurement_consent=True,
            )

    def test_consent_recorded_in_tracker(self, orchestrator):
        """Verify consent is recorded in ConsentTracker."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        assert orchestrator.consent_tracker.has_photo_consent("test_user")
        assert orchestrator.consent_tracker.has_measurement_consent("test_user")


class TestPhotoUpload:
    """Test photo upload and state transitions."""

    def test_upload_photo(self, orchestrator):
        """Upload a photo and transition to measurement_extraction."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        updated = orchestrator.upload_photo(
            session.session_id,
            photo_ref="s3://bucket/photo_1.jpg",
            height_cm=165.0,
        )
        assert updated.status == IntakeState.MEASUREMENT_EXTRACTION.value
        assert len(updated.photo_refs) == 1
        assert updated.photo_refs[0] == "s3://bucket/photo_1.jpg"

    def test_upload_multiple_photos(self, orchestrator):
        """Upload multiple photos."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo_1.jpg")
        updated = orchestrator.upload_photo(
            session.session_id,
            "s3://bucket/photo_2.jpg",
        )
        assert len(updated.photo_refs) == 2

    def test_upload_photo_invalid_ref(self, orchestrator):
        """Reject invalid photo reference."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        with pytest.raises(ModuleError):
            orchestrator.upload_photo(session.session_id, photo_ref="")


class TestMeasurementExtraction:
    """Test measurement extraction and confidence-based routing."""

    def test_extract_measurements_high_confidence(self, orchestrator):
        """Extract measurements with high confidence → proceed to profile_generation."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg", height_cm=165)
        updated = orchestrator.extract_measurements(session.session_id, height_cm=165)

        # With mock provider, confidence is high
        assert updated.status == IntakeState.PROFILE_GENERATION.value
        assert updated.body_measurements is not None
        assert updated.shape_profile is not None  # M3 already called

    def test_extract_measurements_low_confidence_routing(self, orchestrator):
        """Extract measurements with low confidence → route to manual_entry."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg", height_cm=165)

        # Manually set low confidence to simulate low-confidence extraction
        updated = orchestrator.extract_measurements(session.session_id, height_cm=165, confidence_threshold=0.99)

        # Mock provider returns 0.95 confidence, so threshold 0.99 triggers manual_entry
        assert updated.status == IntakeState.MANUAL_ENTRY.value

    def test_extract_measurements_no_photos(self, orchestrator):
        """Reject measurement extraction if no photos uploaded."""
        session = orchestrator.create_session(user_id="test_user")
        with pytest.raises(ModuleError, match="No photos"):
            orchestrator.extract_measurements(session.session_id)


class TestManualMeasurementEntry:
    """Test manual measurement confirmation and overrides."""

    def test_confirm_measurements_auto_extracted(self, orchestrator):
        """Confirm auto-extracted measurements → proceed to preferences."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg", height_cm=165)
        orchestrator.extract_measurements(session.session_id)

        # Set session to manual_entry state to test confirm flow
        session.status = IntakeState.MANUAL_ENTRY.value
        updated = orchestrator.confirm_measurements(session.session_id)

        assert updated.status == IntakeState.PREFERENCES_CAPTURE.value
        assert updated.shape_profile is not None

    def test_confirm_measurements_manual_override(self, orchestrator):
        """Submit manual measurement overrides."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        session.status = IntakeState.MANUAL_ENTRY.value

        updated = orchestrator.confirm_measurements(
            session.session_id,
            manual_overrides={
                "bust": 90.0,
                "waist": 72.0,
                "hips": 100.0,
                "height": 170.0,
            },
        )

        assert updated.status == IntakeState.PREFERENCES_CAPTURE.value
        assert updated.body_measurements.bust == 90.0
        assert updated.manual_overrides["bust"] == 90.0
        assert updated.shape_profile is not None

    def test_confirm_measurements_invalid_overrides(self, orchestrator):
        """Reject invalid measurement overrides."""
        session = orchestrator.create_session(user_id="test_user")
        session.status = IntakeState.MANUAL_ENTRY.value

        with pytest.raises(ModuleError):
            orchestrator.confirm_measurements(
                session.session_id,
                manual_overrides={"bust": -10.0, "waist": 72.0, "hips": 100.0},
            )


class TestPreferenceCapture:
    """Test capturing user style preferences and completing intake."""

    def test_capture_preferences_complete(self, orchestrator):
        """Capture complete preferences → complete intake."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        orchestrator.extract_measurements(session.session_id)

        # Set to preferences_capture manually for this test
        session.status = IntakeState.PREFERENCES_CAPTURE.value

        updated = orchestrator.capture_preferences(
            session.session_id,
            preferred_colors=["black", "navy"],
            preferred_silhouettes=["fitted", "flowing"],
            occasions=["work", "casual"],
            coverage_prefs={"neckline": "moderate"},
            free_text_notes="Minimalist aesthetic",
        )

        assert updated.status == IntakeState.COMPLETE.value
        assert updated.style_profile is not None
        assert len(updated.style_profile.preferred_colors) == 2

    def test_capture_preferences_minimal(self, orchestrator):
        """Capture minimal preferences (allowed)."""
        session = orchestrator.create_session(user_id="test_user")
        session.status = IntakeState.PREFERENCES_CAPTURE.value

        updated = orchestrator.capture_preferences(
            session.session_id,
            preferred_colors=[],
            preferred_silhouettes=[],
        )

        assert updated.status == IntakeState.COMPLETE.value


class TestEventLogging:
    """Test intake event log for replay/debug."""

    def test_event_log_state_transitions(self, orchestrator):
        """Record all state transitions in event log."""
        session = orchestrator.create_session(user_id="test_user")
        assert len(session.event_log) == 0

        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        session = orchestrator.get_session(session.session_id)
        assert len(session.event_log) == 1
        assert session.event_log[0]["from_state"] == IntakeState.INITIATED.value
        assert session.event_log[0]["to_state"] == IntakeState.PHOTO_CAPTURE.value

        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        session = orchestrator.get_session(session.session_id)
        assert len(session.event_log) == 2

    def test_event_log_replay_scenario(self, orchestrator):
        """Verify event log allows replaying intake flow."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(session.session_id, photo_consent=True, measurement_consent=True)
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")

        session = orchestrator.get_session(session.session_id)
        events = session.event_log

        # Verify chronological order
        assert events[0]["from_state"] == IntakeState.INITIATED.value
        assert events[1]["from_state"] == IntakeState.PHOTO_CAPTURE.value


class TestResume:
    """Test resuming interrupted sessions."""

    def test_resume_incomplete_session(self, orchestrator):
        """Resume the most recent incomplete session."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        # User closes browser mid-flow

        # Next day: resume
        resumed = orchestrator.resume_session(user_id="test_user")
        assert resumed.user_id == "test_user"
        assert resumed.status == IntakeState.PHOTO_CAPTURE.value

    def test_resume_no_incomplete_sessions(self, orchestrator):
        """Raise error if no resumable sessions exist."""
        with pytest.raises(ModuleError, match="No resumable session"):
            orchestrator.resume_session(user_id="nonexistent_user")

    def test_resume_completed_session_not_resumed(self, orchestrator):
        """Don't resume completed sessions."""
        # Create and complete a session
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        orchestrator.extract_measurements(session.session_id)
        session = orchestrator.get_session(session.session_id)
        session.status = IntakeState.PREFERENCES_CAPTURE.value
        orchestrator.capture_preferences(session.session_id)

        # Try to resume completed session
        with pytest.raises(ModuleError):
            orchestrator.resume_session(user_id="test_user")


class TestFullIntakeFlow:
    """Test complete intake flow end-to-end."""

    def test_happy_path_full_intake(self, orchestrator):
        """Customer completes entire intake flow successfully."""
        user_id = "happy_path_user"

        # 1. Create session
        session = orchestrator.create_session(user_id=user_id)
        assert session.status == IntakeState.INITIATED.value

        # 2. Consent
        session = orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        assert session.status == IntakeState.PHOTO_CAPTURE.value

        # 3. Upload photo
        session = orchestrator.upload_photo(
            session.session_id,
            photo_ref="s3://bucket/photo.jpg",
            height_cm=165.0,
        )
        assert session.status == IntakeState.MEASUREMENT_EXTRACTION.value

        # 4. Extract measurements
        session = orchestrator.extract_measurements(session.session_id)
        assert session.status == IntakeState.PROFILE_GENERATION.value
        assert session.body_measurements is not None
        assert session.shape_profile is not None

        # 5. Capture preferences
        session = orchestrator.capture_preferences(
            session.session_id,
            preferred_colors=["black", "navy"],
            preferred_silhouettes=["fitted"],
            occasions=["work"],
        )
        assert session.status == IntakeState.COMPLETE.value
        assert session.style_profile is not None

        # Verify final session state
        assert session.consent_record["photo"] is True
        assert session.consent_record["measurements"] is True
        assert len(session.photo_refs) == 1
        assert len(session.event_log) >= 5  # Multiple transitions

    def test_manual_fallback_flow(self, orchestrator):
        """Customer uses manual entry when confident extraction unavailable."""
        user_id = "manual_fallback_user"

        session = orchestrator.create_session(user_id=user_id)
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")

        # Low confidence threshold triggers manual entry
        session = orchestrator.extract_measurements(
            session.session_id,
            confidence_threshold=0.99,  # Mock returns 0.95
        )
        assert session.status == IntakeState.MANUAL_ENTRY.value

        # User provides manual measurements
        session = orchestrator.confirm_measurements(
            session.session_id,
            manual_overrides={
                "bust": 88.0,
                "waist": 70.0,
                "hips": 102.0,
                "height": 165.0,
            },
        )
        assert session.status == IntakeState.PREFERENCES_CAPTURE.value
        assert session.manual_overrides["bust"] == 88.0
        assert session.shape_profile is not None
