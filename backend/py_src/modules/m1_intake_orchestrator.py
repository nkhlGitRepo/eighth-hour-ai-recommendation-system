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
from py_src.persistence.session_repository import SessionRepository, SQLiteSessionRepository
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

    def __init__(self, session_repo: SessionRepository = None, consent_tracker: ConsentTracker = None, catalog=None, sizing: SizingIntegration = None):
        # Session persistence layer (defaults to SQLite)
        self.session_repo = session_repo or SQLiteSessionRepository()
        # An explicitly-provided integration (production wiring in main.py,
        # which selects the provider from SIZING_PROVIDER) always wins;
        # defaulting to SizingIntegration() keeps every existing caller and
        # test on the mock provider exactly as before.
        self.sizing = sizing or SizingIntegration()
        self.profiler = BodyShapeProfiler()
        # Passing the live catalog lets M4 validate colors against whatever
        # products actually exist right now, instead of a hand-maintained
        # list that has to be manually updated every time a new color is
        # added to the catalog.
        self.preferences = PreferenceCapture(catalog=catalog)
        # Share the session repo's db file by default, so a session and its
        # consent record live in (and survive restarts from) the same
        # database -- an explicitly-provided tracker (production wiring in
        # main.py) always wins.
        self.consent_tracker = consent_tracker or ConsentTracker(
            db_path=getattr(self.session_repo, "db_path", None)
        )
        logger.info("M1 IntakeOrchestrator initialized")

    def create_session(self, user_id: str) -> IntakeSession:
        """Create a new intake session."""
        if not isinstance(user_id, str) or len(user_id) == 0:
            raise ModuleError("Invalid user_id", "M1")

        session = IntakeSession(user_id)
        self.session_repo.save(session)

        AuditLogger.log_event(
            "INTAKE_STARTED",
            user_id,
            {"session_id": session.session_id},
        )

        logger.info("Intake session created", {"session_id": session.session_id, "user_id": user_id})
        return session

    def get_session(self, session_id: str) -> IntakeSession:
        """Retrieve an intake session."""
        session = self.session_repo.get(session_id)
        if not session:
            raise ModuleError(f"Session {session_id} not found", "M1")
        return session

    def resume_session(self, user_id: str) -> IntakeSession:
        """Resume the most recent incomplete session for a user."""
        session = self.session_repo.get_by_user(user_id)
        if not session:
            raise ModuleError(f"No resumable session found for user {user_id}", "M1")
        logger.info("Resuming intake session", {"user_id": user_id, "session_id": session.session_id})
        return session

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
        self.session_repo.save(session)
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
        self.session_repo.save(session)
        return session

    def _apply_extracted_measurements(
        self,
        session: IntakeSession,
        measurements,
        confidence_threshold: float = 0.75,
    ) -> list:
        """
        Store freshly-extracted measurements on the session and route based
        on confidence. Shared by BOTH extraction entry points (the photo_ref
        path in extract_measurements and the uploaded-bytes path in
        extract_measurements_from_upload) so the two can never drift apart
        in what they record or where they leave the session.

        Covers the success path only -- each entry point keeps its own error
        handling, deliberately: the photo_ref path soft-fails to manual_entry,
        while the upload path must surface the failure so the HTTP layer can
        tell the customer their photo couldn't be read.

        Returns:
            List of low-confidence field names (empty when all cleared the
            threshold), so callers can report it without recomputing.
        """
        session.body_measurements = measurements
        session.measurement_provider = measurements.provider
        session.measurement_confidence = measurements.confidence_scores

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
                    "session_id": session.session_id,
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

        return low_confidence_fields

    def _resolve_photo_height(self, session: IntakeSession, photo_ref: str) -> float:
        """
        Height to use as the extraction scale reference.

        upload_photo() already stores the customer's height per photo in
        photo_metadata, but extraction used to ignore it and always assume
        165cm -- so someone who uploaded at 180cm was measured as though
        they were 165cm. Prefer the stored value, falling back to 165 only
        when nothing was recorded.
        """
        stored = (session.photo_metadata.get(photo_ref) or {}).get("height_cm")
        return stored if stored else 165.0

    def extract_measurements(
        self,
        session_id: str,
        height_cm: float = None,
        confidence_threshold: float = 0.75,
    ) -> IntakeSession:
        """
        Extract measurements from uploaded photo(s). Route to manual_entry if low confidence.

        Args:
            session_id: Intake session ID
            height_cm: Height in cm. When omitted, falls back to the height
                recorded for this photo by upload_photo(), then to 165.
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

        if height_cm is None:
            height_cm = self._resolve_photo_height(session, photo_ref)

        try:
            # Call M2 to extract measurements
            measurements = self.sizing.extract_measurements(
                photo_ref=photo_ref,
                height_cm=height_cm,
                user_id=session.user_id,
            )

            self._apply_extracted_measurements(
                session, measurements, confidence_threshold
            )

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

        self.session_repo.save(session)
        return session

    def extract_measurements_from_upload(
        self,
        session_id: str,
        image_bytes: bytes,
        content_type: str,
        height_cm: float = None,
        confidence_threshold: float = 0.75,
        usual_top_size: str = None,
        usual_bottom_size: str = None,
    ) -> IntakeSession:
        """
        Extract measurements from a directly-uploaded image.

        The image bytes are never persisted -- they're passed to the provider,
        used, and dropped when this call returns. Nothing about the image is
        written to the session; only the resulting measurements are.

        Unlike extract_measurements(), extraction failures propagate rather
        than silently routing to manual_entry: this path is driven by a
        customer action in the UI, which needs to show a real error (and its
        "enter measurements manually instead" fallback) rather than appearing
        to succeed. The session is left untouched when extraction fails.

        Args:
            session_id: Intake session ID
            image_bytes: Raw image data (caller must have validated it)
            content_type: Validated MIME type
            height_cm: Customer-supplied height, the scale reference
            confidence_threshold: Minimum confidence to proceed (default 0.75)

        Returns:
            Updated IntakeSession (status = profile_generation or manual_entry)

        Raises:
            ModuleError: If the provider can't extract usable measurements
        """
        session = self.get_session(session_id)

        measurements = self.sizing.extract_from_image(
            image_bytes=image_bytes,
            content_type=content_type,
            height_cm=height_cm,
            user_id=session.user_id,
            usual_top_size=usual_top_size,
            usual_bottom_size=usual_bottom_size,
        )

        self._apply_extracted_measurements(
            session, measurements, confidence_threshold
        )

        self.session_repo.save(session)
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

            # Photo measurement returns the customer to the measurements screen
            # to review the estimates, so a scan is always followed by a
            # confirm submitting those same numbers back. Blindly relabelling
            # them "manual_entry" would erase the real provenance on every
            # single scan (and, with a real vendor configured, would make the
            # audit trail claim the customer typed values the vendor produced).
            # So provenance is only reassigned when the values actually differ
            # from what was extracted -- i.e. when the human really did
            # override something.
            existing = session.body_measurements
            unchanged_from_extraction = existing is not None and all(
                manual_overrides.get(field) == getattr(existing, field)
                for field in ("bust", "waist", "hips", "height")
            )

            if unchanged_from_extraction:
                logger.debug(
                    "Measurements confirmed unchanged; keeping extraction provenance",
                    {"session_id": session_id, "provider": existing.provider},
                )
            else:
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
                session.measurement_provider = "manual_entry"
                session.measurement_confidence = (
                    session.body_measurements.confidence_scores
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

        self.session_repo.save(session)
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
        self.session_repo.save(session)
        return session
