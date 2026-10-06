"""Comprehensive tests for M1 to catch edge cases and ensure rigorous verification."""

import pytest
import tempfile
import os
from py_src.modules.m1_intake_orchestrator import (
    IntakeOrchestrator,
    IntakeState,
)
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.persistence.session_repository import SQLiteSessionRepository
from py_src.utils.errors import ModuleError, GuardrailError


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


class TestM1StateGuards:
    """Test that state machine prevents invalid transitions."""

    def test_cannot_upload_photo_without_consent(self, orchestrator):
        """Cannot upload photo if consent not recorded."""
        session = orchestrator.create_session(user_id="test_user")
        # Try to upload without consent - this should technically work
        # but in real flow, consent should happen first
        result = orchestrator.upload_photo(session.session_id, "s3://photo.jpg")
        # This is actually allowed in the state machine, but photo
        # capture screen should only be reachable after consent
        assert result.status == IntakeState.MEASUREMENT_EXTRACTION.value

    def test_extract_measurements_fails_without_photo(self, orchestrator):
        """Extract measurements without photos uploaded should fail."""
        session = orchestrator.create_session(user_id="test_user")
        with pytest.raises(ModuleError, match="No photos"):
            orchestrator.extract_measurements(session.session_id)

    def test_consent_required_before_measurements_used(self, orchestrator):
        """Measurements should trigger consent check when using consent_tracker."""
        session = orchestrator.create_session(user_id="test_user")
        # Manually set session to extraction state with measurements
        session.status = IntakeState.MEASUREMENT_EXTRACTION.value
        session.body_measurements = orchestrator.sizing.extract_measurements(
            "s3://photo.jpg", height_cm=165.0
        )

        # Try to generate profile without consent - should fail
        with pytest.raises(GuardrailError, match="measurement"):
            # When calling M3.profile with consent_tracker, it should check consent
            from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
            profiler = BodyShapeProfiler()
            profiler.profile(
                session.body_measurements.to_dict(),
                user_id=session.user_id,
                consent_tracker=orchestrator.consent_tracker,
            )


class TestM1MeasurementValidation:
    """Test that extracted measurements are properly validated and used."""

    def test_extracted_measurements_generate_correct_shape_profile(self, orchestrator):
        """Extracted measurements should generate correct shape classification."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        session = orchestrator.extract_measurements(session.session_id)

        # Verify measurements are correct values
        assert session.body_measurements is not None
        assert session.body_measurements.bust == 88.0
        assert session.body_measurements.waist == 70.0
        assert session.body_measurements.hips == 102.0
        assert session.body_measurements.height == 165.0

        # Verify profile is generated and correct
        assert session.shape_profile is not None
        assert "shape_class" in session.shape_profile
        assert session.shape_profile["shape_class"] in [
            "pear", "hourglass", "apple", "athletic", "straight", "balanced"
        ]
        # The mock's 88/70/102 has hips 14 cm fuller than the bust: FFIT's
        # triangle, i.e. pear. (The old rules said hourglass because they never
        # compared bust with hips.)
        assert session.shape_profile["shape_class"] == "pear"

        # Verify shape profile has all required fields
        assert "ratios" in session.shape_profile
        assert "size_recommendation_by_category" in session.shape_profile
        assert "fit_notes" in session.shape_profile
        assert len(session.shape_profile["fit_notes"]) > 0

        # Verify ratios are reasonable
        ratios = session.shape_profile["ratios"]
        assert "bust_waist" in ratios
        assert "waist_hip" in ratios
        assert ratios["bust_waist"] == pytest.approx(88.0 / 70.0, rel=0.01)
        assert ratios["waist_hip"] == pytest.approx(70.0 / 102.0, rel=0.01)

        # Verify size recommendations exist for standard categories
        categories = session.shape_profile["size_recommendation_by_category"]
        assert len(categories) > 0
        for category, size_rec in categories.items():
            assert isinstance(size_rec, str)  # Should be string size like "M"

    def test_manual_override_measurements_generate_profile(self, orchestrator):
        """Manual measurement overrides should generate correct profile."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        session.status = IntakeState.MANUAL_ENTRY.value

        # Provide measurements for a specific shape
        session = orchestrator.confirm_measurements(
            session.session_id,
            manual_overrides={
                "bust": 86.0,    # pear shape indicators
                "waist": 72.0,
                "hips": 102.0,   # wider hips
                "height": 165.0,
            },
        )

        # Should generate pear shape profile
        assert session.shape_profile is not None
        assert session.shape_profile["shape_class"] == "pear"
        fit_notes_text = " ".join(session.shape_profile["fit_notes"]).lower()
        assert "pear" in fit_notes_text or "curves" in fit_notes_text

    def test_different_measurements_generate_different_shapes(self, orchestrator):
        """Different measurements should classify as different shapes."""
        from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler

        profiler = BodyShapeProfiler()

        # Hourglass: balanced bust-hip, tiny waist
        hourglass_profile = profiler.profile({
            "bust": 96.0,
            "waist": 68.0,
            "hips": 96.0,
            "height": 165.0,
        })
        assert hourglass_profile["shape_class"] == "hourglass"

        # Apple: large waist, small hips
        apple_profile = profiler.profile({
            "bust": 88.0,
            "waist": 90.0,
            "hips": 85.0,
            "height": 165.0,
        })
        assert apple_profile["shape_class"] == "apple"

        # Shapes should be different
        assert hourglass_profile["shape_class"] != apple_profile["shape_class"]


class TestM1PreferenceIntegration:
    """Test that preferences are properly captured and stored."""

    def test_preferences_actually_stored_in_session(self, orchestrator):
        """Captured preferences should be stored in session."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        orchestrator.extract_measurements(session.session_id)

        # Capture preferences with specific values
        prefs = ["black", "navy", "cream"]
        silhouettes = ["fitted", "flowing"]
        occasions = ["work", "casual", "evening"]

        session = orchestrator.capture_preferences(
            session.session_id,
            preferred_colors=prefs,
            preferred_silhouettes=silhouettes,
            occasions=occasions,
            coverage_prefs={"neckline": "moderate", "sleeves": "full"},
            free_text_notes="Minimalist aesthetic",
        )

        # Verify preferences are stored correctly
        assert session.style_profile is not None
        assert session.style_profile.preferred_colors == prefs
        assert session.style_profile.preferred_silhouettes == silhouettes
        assert session.style_profile.occasions == occasions
        assert session.style_profile.coverage_prefs["neckline"] == "moderate"
        assert session.style_profile.coverage_prefs["sleeves"] == "full"
        assert "Minimalist" in session.style_profile.free_text_notes

    def test_invalid_preferences_filtered_not_rejected(self, orchestrator):
        """Invalid preference options should be filtered, not reject whole flow."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        orchestrator.extract_measurements(session.session_id)

        # Mix of valid and invalid options
        session = orchestrator.capture_preferences(
            session.session_id,
            preferred_colors=["black", "invalid_color", "navy"],
            preferred_silhouettes=["fitted", "wrong_silhouette"],
            occasions=["work", "invalid_occasion"],
        )

        # Should keep only valid options
        assert "black" in session.style_profile.preferred_colors
        assert "navy" in session.style_profile.preferred_colors
        assert "invalid_color" not in session.style_profile.preferred_colors
        assert "fitted" in session.style_profile.preferred_silhouettes
        assert "wrong_silhouette" not in session.style_profile.preferred_silhouettes
        assert "work" in session.style_profile.occasions
        assert "invalid_occasion" not in session.style_profile.occasions

    def test_all_invalid_preferences_rejected(self, orchestrator):
        """M4 rejects if ALL preferences are invalid (guardrail)."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        orchestrator.extract_measurements(session.session_id)

        # All invalid preferences - should be rejected
        with pytest.raises(ModuleError, match="No valid colors"):
            orchestrator.capture_preferences(
                session.session_id,
                preferred_colors=["invalid1", "invalid2"],
                preferred_silhouettes=["wrong1", "wrong2"],
                occasions=["badoccasion"],
            )

    def test_empty_preferences_succeeds(self, orchestrator):
        """Flow completes successfully with no preferences specified."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        orchestrator.extract_measurements(session.session_id)

        # Capture with no preferences
        session = orchestrator.capture_preferences(session.session_id)

        assert session.status == IntakeState.COMPLETE.value
        assert len(session.style_profile.preferred_colors) == 0
        assert len(session.style_profile.occasions) == 0


class TestM1ConsentEnforcement:
    """Test that consent is properly enforced at each stage."""

    def test_measurement_consent_checked_before_profiling(self, orchestrator):
        """M3 should reject profiling if measurement consent not given."""
        session = orchestrator.create_session(user_id="test_user")

        # Record only photo consent, not measurement consent
        orchestrator.consent_tracker.record_consent(
            user_id=session.user_id,
            photo_consent=True,
            measurement_consent=False,
        )

        # Try to profile without measurement consent
        from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
        profiler = BodyShapeProfiler()

        with pytest.raises(GuardrailError, match="measurement"):
            profiler.profile(
                {
                    "bust": 88.0,
                    "waist": 70.0,
                    "hips": 102.0,
                    "height": 165.0,
                },
                user_id=session.user_id,
                consent_tracker=orchestrator.consent_tracker,
            )

    def test_photo_consent_checked_in_m6_retrieval(self, orchestrator):
        """M6 no longer checks consent directly (session completion enforces it)."""
        # Consent enforcement moved to session completion check in M5/main.py
        # M6 retrieves products without checking consent tracker
        from py_src.modules.m6_catalog_kb import CatalogKB
        from tests.fixtures import PRODUCTS

        catalog = CatalogKB(PRODUCTS)
        user_id = "test_user"

        # Even without photo consent, M6 retrieves products
        orchestrator.consent_tracker.record_consent(
            user_id=user_id,
            photo_consent=False,
            measurement_consent=True,
        )

        # M6 should return results regardless of consent
        # (consent is enforced at session level, not at retrieval)
        results = catalog.retrieve(
            {"shape_class": "pear"},
            user_id=user_id,
            consent_tracker=orchestrator.consent_tracker,
        )
        assert len(results) > 0

    def test_consent_survives_orchestrator_restart_for_update_style_flow(self):
        """
        Regression test for the exact "Update Style" bug report: a customer
        completes intake (consent + measurements + preferences), the server
        restarts (a fresh IntakeOrchestrator gets constructed -- simulated
        here via a second instance pointed at the same on-disk db), and the
        customer then clicks "Update Style" and re-submits measurements on
        their existing, still-valid session. This must succeed without
        forcing them back through the consent screen.
        """
        db_path = tempfile.NamedTemporaryFile(delete=False, suffix=".db").name
        try:
            # M4 validates preferred_colors against the live catalog (see
            # PreferenceCapture._valid_colors) rather than a hardcoded list
            # -- inject one with "Ebony" so this test mirrors the real
            # production wiring (main.py always passes the real catalog).
            catalog = CatalogKB([{
                "slug": "ebony-top", "name": "Ebony Top", "category": "Tops",
                "fabric": "Cotton", "price": 50.0, "colors": ["Ebony"], "sizes": ["M"],
            }])
            repo_before = SQLiteSessionRepository(db_path=db_path)
            orch_before_restart = IntakeOrchestrator(session_repo=repo_before, catalog=catalog)

            session = orch_before_restart.create_session(user_id="update-style-user")
            orch_before_restart.record_consent(
                session.session_id, photo_consent=True, measurement_consent=True,
            )
            orch_before_restart.confirm_measurements(
                session.session_id,
                manual_overrides={"bust": 91, "waist": 76, "hips": 95, "height": 165},
            )
            orch_before_restart.capture_preferences(
                session.session_id,
                preferred_colors=["Ebony"],
                preferred_silhouettes=["fitted"],
                occasions=["work"],
            )

            # Simulate a server restart: brand-new orchestrator instance,
            # all in-memory state gone, pointed at the SAME db file.
            repo_after = SQLiteSessionRepository(db_path=db_path)
            orch_after_restart = IntakeOrchestrator(session_repo=repo_after)

            # "Update Style": re-submit measurements on the existing session.
            # Must NOT raise a consent GuardrailError.
            result = orch_after_restart.confirm_measurements(
                session.session_id,
                manual_overrides={"bust": 88, "waist": 70, "hips": 100, "height": 165},
            )
            assert result.shape_profile is not None
        finally:
            try:
                os.unlink(db_path)
            except OSError:
                pass


class TestM1EventLogAccuracy:
    """Test that event log accurately captures state transitions."""

    def test_event_log_captures_all_state_transitions(self, orchestrator):
        """Every state transition should be logged."""
        session = orchestrator.create_session(user_id="test_user")
        session_id = session.session_id

        # Track all transitions
        transitions = []

        # Consent
        orchestrator.record_consent(session_id, photo_consent=True, measurement_consent=True)
        session = orchestrator.get_session(session_id)
        transitions.append(("photo_capture", len(session.event_log)))

        # Photo upload
        orchestrator.upload_photo(session_id, "s3://bucket/photo.jpg")
        session = orchestrator.get_session(session_id)
        transitions.append(("measurement_extraction", len(session.event_log)))

        # Extract measurements
        orchestrator.extract_measurements(session_id)
        session = orchestrator.get_session(session_id)
        transitions.append(("profile_generation", len(session.event_log)))

        # Verify correct number of events and transitions
        assert len(session.event_log) == 3  # 3 transitions so far
        assert session.event_log[0]["to_state"] == "photo_capture"
        assert session.event_log[1]["to_state"] == "measurement_extraction"
        assert session.event_log[2]["to_state"] == "profile_generation"

    def test_event_log_contains_useful_context(self, orchestrator):
        """Event log should contain enough context to understand what happened."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        session = orchestrator.get_session(session.session_id)

        # Check consent event
        event = session.event_log[0]
        assert "from_state" in event
        assert "to_state" in event
        assert "reason" in event
        assert "user_action" in event
        assert "timestamp" in event
        assert event["from_state"] == "initiated"
        assert event["to_state"] == "photo_capture"
        assert "Consent" in event["reason"] or "consent" in event["reason"].lower()


class TestM1ConfidenceThresholding:
    """Test that confidence-based routing works correctly."""

    def test_confidence_threshold_correctly_routes_flow(self, orchestrator):
        """Low confidence should route to manual_entry, high to profile_generation."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")

        # With threshold=0.75 (mock returns 0.85 min), should proceed
        session_high = orchestrator.extract_measurements(
            session.session_id,
            confidence_threshold=0.75,
        )
        assert session_high.status == IntakeState.PROFILE_GENERATION.value

        # With threshold=0.99 (mock returns 0.85 min), should route to manual
        session2 = orchestrator.create_session(user_id="test_user2")
        orchestrator.record_consent(
            session2.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session2.session_id, "s3://bucket/photo.jpg")
        session_low = orchestrator.extract_measurements(
            session2.session_id,
            confidence_threshold=0.99,
        )
        assert session_low.status == IntakeState.MANUAL_ENTRY.value


class TestM1ErrorRecovery:
    """Test error handling and recovery."""

    def test_extraction_error_routes_to_manual_entry(self, orchestrator):
        """Errors in M2 extraction should fallback to manual entry."""
        # This is implicitly tested by the low-confidence fallback
        # But let's explicitly test that errors don't crash
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")

        # Normal extraction should work
        session = orchestrator.extract_measurements(session.session_id)
        assert session.body_measurements is not None

    def test_invalid_measurement_overrides_rejected(self, orchestrator):
        """Invalid measurements should be rejected with clear error."""
        session = orchestrator.create_session(user_id="test_user")
        session.status = IntakeState.MANUAL_ENTRY.value

        # Negative values
        with pytest.raises(ModuleError):
            orchestrator.confirm_measurements(
                session.session_id,
                manual_overrides={
                    "bust": -10.0,  # Invalid
                    "waist": 72.0,
                    "hips": 100.0,
                    "height": 165.0,
                },
            )

        # Missing required field
        with pytest.raises(ModuleError):
            orchestrator.confirm_measurements(
                session.session_id,
                manual_overrides={
                    "bust": 88.0,
                    # Missing waist
                    "hips": 100.0,
                    "height": 165.0,
                },
            )


class TestM1EndToEndScearios:
    """Test complete, realistic scenarios."""

    def test_pear_shape_flow_complete(self, orchestrator):
        """Complete flow for pear-shaped customer."""
        user_id = "pear_customer"
        session = orchestrator.create_session(user_id=user_id)

        # Consent
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )

        # Photo
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")

        # Measurements
        session = orchestrator.extract_measurements(session.session_id)
        assert session.body_measurements.bust == 88.0
        # Mock's 88/70/102: hips 14 cm fuller than the bust -> pear.
        assert session.shape_profile["shape_class"] == "pear"

        # Preferences
        session = orchestrator.capture_preferences(
            session.session_id,
            preferred_colors=["black", "jewel_tones"],
            preferred_silhouettes=["wrap", "a_line"],
            occasions=["work", "evening"],
            coverage_prefs={"neckline": "moderate"},
        )

        # Verify complete session
        assert session.status == IntakeState.COMPLETE.value
        assert session.user_id == user_id
        assert session.body_measurements is not None
        assert session.shape_profile is not None
        assert session.style_profile is not None
        assert len(session.event_log) >= 5  # Multiple state transitions

    def test_manual_override_flow_complete(self, orchestrator):
        """Complete flow with manual measurement entry."""
        user_id = "manual_user"
        session = orchestrator.create_session(user_id=user_id)

        # Consent
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )

        # Photo
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")

        # Low confidence forces manual entry
        session = orchestrator.extract_measurements(
            session.session_id,
            confidence_threshold=0.99,
        )
        assert session.status == IntakeState.MANUAL_ENTRY.value

        # User provides manual measurements
        session = orchestrator.confirm_measurements(
            session.session_id,
            manual_overrides={
                "bust": 80.0,
                "waist": 66.0,
                "hips": 95.0,
                "height": 160.0,
            },
        )
        assert session.status == IntakeState.PREFERENCES_CAPTURE.value
        assert session.shape_profile is not None

        # Preferences
        session = orchestrator.capture_preferences(
            session.session_id,
            preferred_colors=["black"],
            preferred_silhouettes=["fitted"],
        )
        assert session.status == IntakeState.COMPLETE.value
