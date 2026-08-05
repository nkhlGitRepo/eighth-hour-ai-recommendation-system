"""
M1 — Onboarding & Intake Orchestration

Responsibility: Own the guided, multi-screen intake flow. State machine that
orchestrates photo capture → measurement extraction → preferences collection.

Guardrails applied:
- InputValidator: validate measurements and preferences
- ConsentTracker: enforce photo/measurement consent
- AuditLogger: log state transitions and events
"""

from enum import Enum
from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.audit_logger import AuditLogger
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.modules.m2_sizing_integration import SizingIntegration, Measurements
from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
from py_src.modules.m4_style_preference import PreferenceCapture, StyleProfile
import time
import uuid


class IntakeState(Enum):
    """Intake flow states."""

    INITIATED = "initiated"
    CONSENT = "consent"
    PHOTO_CAPTURE = "photo_capture"
    MEASUREMENT_EXTRACTION = "measurement_extraction"
    MANUAL_ENTRY = "manual_entry"
    PROFILE_GENERATION = "profile_generation"
    PREFERENCES_CAPTURE = "preferences_capture"
    COMPLETE = "complete"


class IntakeSession:
    """Represents one customer's intake flow (multi-screen progress)."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.session_id = str(uuid.uuid4())
        self.status = IntakeState.INITIATED.value

        # Consent
        self.consent_record = {}

        # Photos
        self.photo_refs = []
        self.photo_metadata = {}

        # Measurements (from M2)
        self.body_measurements = None
        self.measurement_confidence = {}
        self.measurement_provider = "mock"

        # Manual overrides
        self.manual_overrides = {}

        # Shape profile (from M3)
        self.shape_profile = None

        # Style preferences (from M4)
        self.style_profile = None

        # Metadata
        self.created_at = time.time()
        self.updated_at = time.time()

        # Event log (for replay/debug)
        self.event_log = []

    def to_dict(self):
        """Convert to dict for API responses."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "consent_record": self.consent_record,
            "photo_refs": self.photo_refs,
            "body_measurements": self.body_measurements.to_dict() if self.body_measurements else None,
            "shape_profile": self.shape_profile,
            "style_profile": self.style_profile.to_dict() if self.style_profile else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def record_event(self, from_state: str, to_state: str, reason: str, user_action: str = None):
        """Record a state transition event for replay/debug."""
        event = {
            "timestamp": time.time(),
            "from_state": from_state,
            "to_state": to_state,
            "reason": reason,
            "user_action": user_action,
        }
        self.event_log.append(event)
        logger.debug("Intake event", event)


class IntakeOrchestrator:
    """Orchestrates the multi-screen intake flow."""

    def __init__(self):
        # In-memory session store (Phase 1 only; Phase 2 uses DB)
        self._sessions = {}
        self.sizing = SizingIntegration()
        self.profiler = BodyShapeProfiler()
        self.preferences = PreferenceCapture()
        self.consent_tracker = ConsentTracker()
        logger.info("M1 IntakeOrchestrator initialized")

    def create_session(self, user_id: str) -> IntakeSession:
        """Create a new intake session."""
        if not isinstance(user_id, str) or len(user_id) == 0:
            raise ModuleError("Invalid user_id", "M1")

        session = IntakeSession(user_id)
        self._sessions[session.session_id] = session

        AuditLogger.log_event(
            "INTAKE_STARTED",
            user_id,
            {"session_id": session.session_id},
        )

        logger.info("Intake session created", {"session_id": session.session_id, "user_id": user_id})
        return session

    def get_session(self, session_id: str) -> IntakeSession:
        """Retrieve an intake session."""
        if session_id not in self._sessions:
            raise ModuleError(f"Session {session_id} not found", "M1")
        return self._sessions[session_id]

    def resume_session(self, user_id: str) -> IntakeSession:
        """Resume the most recent incomplete session for a user."""
        for session_id, session in self._sessions.items():
            if session.user_id == user_id and session.status != IntakeState.COMPLETE.value:
                logger.info("Resuming intake session", {"user_id": user_id, "session_id": session_id})
                return session

        raise ModuleError(f"No resumable session found for user {user_id}", "M1")

    def record_consent(
        self,
        session_id: str,
        photo_consent: bool = False,
        measurement_consent: bool = False,
    ) -> IntakeSession:
        """
        Record user consent decision and transition to photo capture.

        Args:
            session_id: Intake session ID
            photo_consent: User accepts photo capture
            measurement_consent: User accepts measurement extraction

        Returns:
            Updated IntakeSession

        Raises:
            GuardrailError: If user doesn't consent to both
        """
        session = self.get_session(session_id)

        if not photo_consent or not measurement_consent:
            raise GuardrailError(
                "User must consent to both photo and measurement capture",
                "M1"
            )

        # Record in ConsentTracker
        self.consent_tracker.record_consent(
            user_id=session.user_id,
            photo_consent=photo_consent,
            measurement_consent=measurement_consent,
        )

        session.consent_record = {
            "photo": photo_consent,
            "measurements": measurement_consent,
            "timestamp": time.time(),
        }

        # Transition to photo_capture
        old_status = session.status
        session.status = IntakeState.PHOTO_CAPTURE.value
        session.updated_at = time.time()
        session.record_event(old_status, session.status, "Consent accepted", "user_accepted_consent")

        AuditLogger.log_event(
            "CONSENT_RECORDED",
            session.user_id,
            {"photo": photo_consent, "measurements": measurement_consent},
        )

        logger.debug("Consent recorded", {"session_id": session_id, "user_id": session.user_id})
        return session

    def upload_photo(
        self,
        session_id: str,
        photo_ref: str,
        height_cm: float = None,
    ) -> IntakeSession:
        """
        Upload photo and optionally start measurement extraction.

        Args:
            session_id: Intake session ID
            photo_ref: Secure reference to uploaded photo
            height_cm: User's height in cm (optional)

        Returns:
            Updated IntakeSession

        Raises:
            ModuleError: If photo_ref invalid
        """
        session = self.get_session(session_id)

        if not isinstance(photo_ref, str) or len(photo_ref) == 0:
            raise ModuleError("Invalid photo reference", "M1")

        session.photo_refs.append(photo_ref)
        session.photo_metadata[photo_ref] = {
            "upload_timestamp": time.time(),
            "height_cm": height_cm,
        }

        # Transition to measurement_extraction
        old_status = session.status
        session.status = IntakeState.MEASUREMENT_EXTRACTION.value
        session.updated_at = time.time()
        session.record_event(old_status, session.status, "Photo uploaded", "photo_uploaded")

        AuditLogger.log_event(
            "PHOTO_UPLOADED",
            session.user_id,
            {"photo_ref": photo_ref, "num_photos": len(session.photo_refs)},
        )

        logger.debug("Photo uploaded", {"session_id": session_id, "photo_ref": photo_ref})
        return session

    def extract_measurements(
        self,
        session_id: str,
        height_cm: float = 165.0,
        confidence_threshold: float = 0.75,
    ) -> IntakeSession:
        """
        Extract measurements from uploaded photo(s). Route to manual_entry if low confidence.

        Args:
            session_id: Intake session ID
            height_cm: Height in cm
            confidence_threshold: Minimum confidence to proceed (default 0.75)

        Returns:
            Updated IntakeSession (status = profile_generation or manual_entry)

        Raises:
            ModuleError: If no photos uploaded
        """
        session = self.get_session(session_id)

        if len(session.photo_refs) == 0:
            raise ModuleError("No photos uploaded", "M1")

        # Use first photo for extraction (Phase 1)
        photo_ref = session.photo_refs[0]

        try:
            # Call M2 to extract measurements
            measurements = self.sizing.extract_measurements(
                photo_ref=photo_ref,
                height_cm=height_cm,
                user_id=session.user_id,
            )

            session.body_measurements = measurements
            session.measurement_provider = measurements.provider
            session.measurement_confidence = measurements.confidence_scores

            # Check confidence
            low_confidence_fields = measurements.low_confidence_fields(confidence_threshold)

            if low_confidence_fields:
                # Route to manual_entry for user confirmation
                old_status = session.status
                session.status = IntakeState.MANUAL_ENTRY.value
                session.updated_at = time.time()
                session.record_event(
                    old_status,
                    session.status,
                    f"Low confidence: {low_confidence_fields}",
                    "auto_route_low_confidence"
                )

                logger.info(
                    "Routing to manual entry (low confidence)",
                    {
                        "session_id": session_id,
                        "low_fields": low_confidence_fields,
                        "min_confidence": measurements.min_confidence(),
                    },
                )
            else:
                # Proceed to profile generation
                old_status = session.status
                session.status = IntakeState.PROFILE_GENERATION.value
                session.updated_at = time.time()
                session.record_event(
                    old_status,
                    session.status,
                    "Measurements extracted with high confidence",
                    "auto_proceed_high_confidence"
                )

                # Call M3 to generate shape profile
                self._generate_profile(session)

        except Exception as err:
            logger.error("M2 extraction failed", err)
            # Route to manual entry on error
            old_status = session.status
            session.status = IntakeState.MANUAL_ENTRY.value
            session.updated_at = time.time()
            session.record_event(
                old_status,
                session.status,
                f"Extraction error: {str(err)}",
                "error_fallback"
            )

        return session

    def confirm_measurements(
        self,
        session_id: str,
        manual_overrides: dict = None,
    ) -> IntakeSession:
        """
        User confirms auto-extracted measurements or submits manual corrections.

        Args:
            session_id: Intake session ID
            manual_overrides: Dict of manually entered/corrected measurements

        Returns:
            Updated IntakeSession
        """
        session = self.get_session(session_id)

        if manual_overrides:
            # Validate overrides
            validation = InputValidator.validate_measurements(manual_overrides)
            if not validation["valid"]:
                raise ModuleError(
                    f"Invalid measurement overrides: {', '.join(validation['errors'])}",
                    "M1"
                )

            session.manual_overrides = manual_overrides

            # Create Measurements from overrides
            session.body_measurements = Measurements(
                bust=manual_overrides["bust"],
                waist=manual_overrides["waist"],
                hips=manual_overrides["hips"],
                height=manual_overrides.get("height", 165),
                shoulder=manual_overrides.get("shoulder"),
                inseam=manual_overrides.get("inseam"),
                provider="manual_entry",
                provider_version="1.0",
            )

            logger.debug("Measurements manually corrected", {"session_id": session_id})

        # Generate profile
        self._generate_profile(session)

        # Transition to preferences_capture
        old_status = session.status
        session.status = IntakeState.PREFERENCES_CAPTURE.value
        session.record_event(
            old_status,
            session.status,
            "Measurements confirmed, profile generated",
            "user_confirmed_measurements"
        )

        return session

    def _generate_profile(self, session: IntakeSession):
        """Generate body shape profile from measurements (does not transition state)."""
        if not session.body_measurements:
            raise ModuleError("No measurements to profile", "M1")

        # Call M3 to classify body shape
        profile = self.profiler.profile(
            measurements=session.body_measurements.to_dict(),
            user_id=session.user_id,
            consent_tracker=self.consent_tracker,
        )

        session.shape_profile = profile
        session.updated_at = time.time()

        logger.debug(
            "Shape profile generated",
            {"session_id": session.session_id, "shape_class": profile["shape_class"]},
        )

    def capture_preferences(
        self,
        session_id: str,
        preferred_colors: list = None,
        preferred_silhouettes: list = None,
        occasions: list = None,
        coverage_prefs: dict = None,
        lifestyle_context: dict = None,
        free_text_notes: str = "",
    ) -> IntakeSession:
        """
        Capture user style preferences and complete intake flow.

        Args:
            session_id: Intake session ID
            preferred_colors: List of color preferences
            preferred_silhouettes: List of silhouette preferences
            occasions: List of occasions
            coverage_prefs: Dict of coverage preferences
            lifestyle_context: Dict of lifestyle preferences
            free_text_notes: Optional free-text notes

        Returns:
            Updated IntakeSession (status = complete)
        """
        session = self.get_session(session_id)

        # Transition to preferences_capture if not already there
        if session.status != IntakeState.PREFERENCES_CAPTURE.value:
            old_status = session.status
            session.status = IntakeState.PREFERENCES_CAPTURE.value
            session.record_event(
                old_status,
                session.status,
                "Entering preferences capture",
                "auto_proceed"
            )

        # Call M4 to capture and validate preferences
        profile = self.preferences.capture_preferences(
            user_id=session.user_id,
            preferred_colors=preferred_colors,
            preferred_silhouettes=preferred_silhouettes,
            occasions=occasions,
            coverage_prefs=coverage_prefs,
            lifestyle_context=lifestyle_context,
            free_text_notes=free_text_notes,
        )

        session.style_profile = profile

        # Transition to complete
        old_status = session.status
        session.status = IntakeState.COMPLETE.value
        session.updated_at = time.time()
        session.record_event(
            old_status,
            session.status,
            "Preferences captured, intake complete",
            "user_completed_preferences"
        )

        AuditLogger.log_event(
            "INTAKE_COMPLETED",
            session.user_id,
            {
                "session_id": session.session_id,
                "shape_class": session.shape_profile.get("shape_class") if session.shape_profile else None,
                "preferences_count": len(session.style_profile.preferred_colors),
            },
        )

        logger.info("Intake completed", {"session_id": session.session_id, "user_id": session.user_id})
        return session
