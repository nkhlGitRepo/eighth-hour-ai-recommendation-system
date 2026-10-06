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


# Minimal valid JPEG bytes for the upload path (mock ignores content).
UPLOAD_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 128


class TestMeasurementExtractionFromUpload:
    """
    Test the uploaded-image extraction path used by POST /intake/photo-measure.
    """

    def _consented_session(self, orchestrator):
        session = orchestrator.create_session(user_id="upload_user")
        orchestrator.record_consent(
            session.session_id, photo_consent=True, measurement_consent=True
        )
        return session

    def test_populates_measurements_and_generates_profile(self, orchestrator):
        session = self._consented_session(orchestrator)

        updated = orchestrator.extract_measurements_from_upload(
            session_id=session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=172.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )

        assert updated.body_measurements is not None
        assert updated.measurement_confidence  # confidence recorded
        assert updated.shape_profile is not None  # M3 ran
        assert updated.status == IntakeState.PROFILE_GENERATION.value

    def test_uses_submitted_height_as_scale_reference(self, orchestrator):
        session = self._consented_session(orchestrator)

        updated = orchestrator.extract_measurements_from_upload(
            session_id=session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=181.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )

        assert updated.body_measurements.height == 181.0

    def test_does_not_record_the_image_on_the_session(self, orchestrator):
        """
        The privacy guarantee: nothing about the uploaded image is stored --
        no photo_refs entry, no photo_metadata, no bytes anywhere.
        """
        session = self._consented_session(orchestrator)

        updated = orchestrator.extract_measurements_from_upload(
            session_id=session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=170.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )

        assert updated.photo_refs == []
        assert updated.photo_metadata == {}
        serialized = str(updated.to_dict())
        assert "\\xff\\xd8" not in serialized

    def test_survives_a_reload(self, orchestrator):
        """Extracted measurements persist, so the customer can log back in."""
        session = self._consented_session(orchestrator)
        orchestrator.extract_measurements_from_upload(
            session_id=session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=176.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )

        reloaded = orchestrator.get_session(session.session_id)
        assert reloaded.body_measurements.height == 176.0
        assert reloaded.shape_profile is not None

    def test_empty_upload_raises_rather_than_soft_failing(self, orchestrator):
        """
        Unlike the photo_ref path (which routes to manual_entry on error),
        this path must surface failures so the UI can show a real error.
        """
        session = self._consented_session(orchestrator)

        with pytest.raises(ModuleError):
            orchestrator.extract_measurements_from_upload(
                session_id=session.session_id,
                image_bytes=b"",
                content_type="image/jpeg",
                height_cm=170.0,
                usual_top_size="M",
                usual_bottom_size="M",
            )

    def test_failed_extraction_leaves_the_session_untouched(self, orchestrator):
        session = self._consented_session(orchestrator)
        status_before = orchestrator.get_session(session.session_id).status

        with pytest.raises(ModuleError):
            orchestrator.extract_measurements_from_upload(
                session_id=session.session_id,
                image_bytes=b"",
                content_type="image/jpeg",
                height_cm=170.0,
                usual_top_size="M",
                usual_bottom_size="M",
            )

        after = orchestrator.get_session(session.session_id)
        assert after.status == status_before
        assert after.body_measurements is None

    def test_unknown_session_rejected(self, orchestrator):
        with pytest.raises(ModuleError):
            orchestrator.extract_measurements_from_upload(
                session_id="no-such-session",
                image_bytes=UPLOAD_JPEG,
                content_type="image/jpeg",
                height_cm=170.0,
                usual_top_size="M",
                usual_bottom_size="M",
            )

    def test_matches_the_photo_ref_path_state(self, orchestrator):
        """
        Both extraction entry points share _apply_extracted_measurements, so
        for the same height they must land in the same status with the same
        measurements. This is the regression guard against the two paths
        drifting apart.
        """
        ref_session = self._consented_session(orchestrator)
        orchestrator.upload_photo(ref_session.session_id, "s3://bucket/p.jpg", height_cm=174.0)
        via_ref = orchestrator.extract_measurements(ref_session.session_id)

        upload_session = self._consented_session(orchestrator)
        via_upload = orchestrator.extract_measurements_from_upload(
            session_id=upload_session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=174.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )

        assert via_ref.status == via_upload.status
        assert via_ref.body_measurements.to_dict()["bust"] == via_upload.body_measurements.to_dict()["bust"]
        assert via_ref.body_measurements.height == via_upload.body_measurements.height == 174.0
        assert (via_ref.shape_profile is None) == (via_upload.shape_profile is None)

    def test_completes_intake_like_manual_entry(self, orchestrator):
        """Photo path must reach `complete` through preferences, same as typing."""
        session = self._consented_session(orchestrator)
        orchestrator.extract_measurements_from_upload(
            session_id=session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=170.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )

        final = orchestrator.capture_preferences(
            session_id=session.session_id, preferred_colors=["black"]
        )
        assert final.status == IntakeState.COMPLETE.value
        assert final.shape_profile is not None


class TestPhotoHeightIsHonored:
    """
    Regression: extract_measurements() used to ignore the height stored by
    upload_photo() and always assume 165cm, so someone who uploaded at 180cm
    was measured as though they were 165cm.
    """

    def test_uses_height_recorded_at_upload(self, orchestrator):
        session = orchestrator.create_session(user_id="height_user")
        orchestrator.record_consent(
            session.session_id, photo_consent=True, measurement_consent=True
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/tall.jpg", height_cm=188.0)

        updated = orchestrator.extract_measurements(session.session_id)

        assert updated.body_measurements.height == 188.0

    def test_explicit_argument_still_wins(self, orchestrator):
        session = orchestrator.create_session(user_id="height_user2")
        orchestrator.record_consent(
            session.session_id, photo_consent=True, measurement_consent=True
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/p.jpg", height_cm=188.0)

        updated = orchestrator.extract_measurements(session.session_id, height_cm=150.0)

        assert updated.body_measurements.height == 150.0

    def test_falls_back_to_default_when_no_height_recorded(self, orchestrator):
        session = orchestrator.create_session(user_id="height_user3")
        orchestrator.record_consent(
            session.session_id, photo_consent=True, measurement_consent=True
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/p.jpg")

        updated = orchestrator.extract_measurements(session.session_id)

        assert updated.body_measurements.height == 165.0


class TestMeasurementProvenancePersists:
    """
    A real sizing vendor's identity and timing must survive a reload --
    otherwise debugging a live integration (or answering "when was this
    measured?") is impossible. extracted_at used to be re-stamped with "now"
    on every load.
    """

    def test_extracted_at_survives_a_reload(self, orchestrator):
        session = orchestrator.create_session(user_id="provenance_user")
        orchestrator.record_consent(
            session.session_id, photo_consent=True, measurement_consent=True
        )
        orchestrator.extract_measurements_from_upload(
            session_id=session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=170.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )
        original_extracted_at = orchestrator.get_session(
            session.session_id
        ).body_measurements.extracted_at

        reloaded = orchestrator.get_session(session.session_id)

        assert reloaded.body_measurements.extracted_at == original_extracted_at

    def test_provider_name_survives_a_reload(self, orchestrator):
        """The authoritative provider lives on the measurements themselves."""
        session = orchestrator.create_session(user_id="provenance_user2")
        orchestrator.record_consent(
            session.session_id, photo_consent=True, measurement_consent=True
        )
        orchestrator.extract_measurements_from_upload(
            session_id=session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=170.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )

        reloaded = orchestrator.get_session(session.session_id)

        assert reloaded.body_measurements.provider == "mock"
        assert reloaded.body_measurements.provider_version == "1.0"


class TestConfirmPreservesExtractionProvenance:
    """
    Photo measurement sends the customer back to the measurements screen to
    review the estimates, so every scan is followed by a confirm resubmitting
    those numbers. Provenance must only flip to manual_entry when the values
    genuinely changed -- otherwise a real vendor's name would be erased on
    every scan and the audit trail would claim the customer typed them.
    """

    def _scanned_session(self, orchestrator, user_id):
        session = orchestrator.create_session(user_id=user_id)
        orchestrator.record_consent(
            session.session_id, photo_consent=True, measurement_consent=True
        )
        orchestrator.extract_measurements_from_upload(
            session_id=session.session_id,
            image_bytes=UPLOAD_JPEG,
            content_type="image/jpeg",
            height_cm=181.0,
            usual_top_size="M",
            usual_bottom_size="M",
        )
        return orchestrator.get_session(session.session_id)

    def test_confirming_unchanged_values_keeps_the_scan_provider(self, orchestrator):
        scanned = self._scanned_session(orchestrator, "prov_unchanged")
        m = scanned.body_measurements

        confirmed = orchestrator.confirm_measurements(
            scanned.session_id,
            manual_overrides={
                "bust": m.bust, "waist": m.waist, "hips": m.hips, "height": m.height,
            },
        )

        assert confirmed.body_measurements.provider == "mock"
        assert confirmed.status == IntakeState.PREFERENCES_CAPTURE.value

    def test_confidence_scores_survive_an_unchanged_confirm(self, orchestrator):
        scanned = self._scanned_session(orchestrator, "prov_conf")
        m = scanned.body_measurements
        original_confidence = dict(m.confidence_scores)

        confirmed = orchestrator.confirm_measurements(
            scanned.session_id,
            manual_overrides={
                "bust": m.bust, "waist": m.waist, "hips": m.hips, "height": m.height,
            },
        )

        assert confirmed.body_measurements.confidence_scores == original_confidence

    def test_editing_a_value_does_flip_to_manual_entry(self, orchestrator):
        """An actual human override should be recorded as such."""
        scanned = self._scanned_session(orchestrator, "prov_edited")
        m = scanned.body_measurements

        confirmed = orchestrator.confirm_measurements(
            scanned.session_id,
            manual_overrides={
                "bust": m.bust, "waist": m.waist - 6, "hips": m.hips, "height": m.height,
            },
        )

        assert confirmed.body_measurements.provider == "manual_entry"
        assert confirmed.body_measurements.waist == m.waist - 6

    def test_pure_manual_entry_is_still_manual_entry(self, orchestrator):
        """No prior extraction -> nothing to preserve, so it's manual entry."""
        session = orchestrator.create_session(user_id="prov_pure_manual")
        orchestrator.record_consent(
            session.session_id, photo_consent=True, measurement_consent=True
        )

        confirmed = orchestrator.confirm_measurements(
            session.session_id,
            manual_overrides={"bust": 91, "waist": 76, "hips": 95, "height": 165},
        )

        assert confirmed.body_measurements.provider == "manual_entry"

    def test_provenance_survives_reload_after_unchanged_confirm(self, orchestrator):
        scanned = self._scanned_session(orchestrator, "prov_reload")
        m = scanned.body_measurements
        orchestrator.confirm_measurements(
            scanned.session_id,
            manual_overrides={
                "bust": m.bust, "waist": m.waist, "hips": m.hips, "height": m.height,
            },
        )

        reloaded = orchestrator.get_session(scanned.session_id)
        assert reloaded.body_measurements.provider == "mock"
        assert reloaded.body_measurements.height == 181.0
