"""
Session persistence layer for intake sessions.

Provides database abstraction so sessions persist across server restarts.
Swappable backend: SQLite (dev) or PostgreSQL (prod).
"""

import json
import sqlite3
from typing import Optional, Dict, TYPE_CHECKING
from py_src.utils.logger import logger

if TYPE_CHECKING:
    from py_src.modules.m1_intake_orchestrator import IntakeSession


class SessionRepository:
    """Abstract base for session persistence."""

    def save(self, session: "IntakeSession") -> None:
        """Persist a session to database."""
        raise NotImplementedError

    def get(self, session_id: str) -> Optional["IntakeSession"]:
        """Retrieve a session from database."""
        raise NotImplementedError

    def get_by_user(self, user_id: str) -> Optional["IntakeSession"]:
        """Get the most recent incomplete session for a user."""
        raise NotImplementedError

    def delete(self, session_id: str) -> None:
        """Delete a session."""
        raise NotImplementedError


class SQLiteSessionRepository(SessionRepository):
    """SQLite-backed session repository for development."""

    def __init__(self, db_path: str = "intake_sessions.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intake_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    consent_record TEXT,
                    photo_refs TEXT,
                    photo_metadata TEXT,
                    body_measurements TEXT,
                    measurement_confidence TEXT,
                    shape_profile TEXT,
                    style_profile TEXT,
                    manual_overrides TEXT,
                    event_log TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_id ON intake_sessions(user_id)"
            )
            conn.commit()
        logger.info("Session database initialized", {"path": self.db_path})

    def save(self, session: "IntakeSession") -> None:
        """Save session to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO intake_sessions
                    (session_id, user_id, status, consent_record, photo_refs, photo_metadata,
                     body_measurements, measurement_confidence, shape_profile, style_profile,
                     manual_overrides, event_log, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.user_id,
                        session.status,
                        json.dumps(session.consent_record) if session.consent_record else None,
                        json.dumps(session.photo_refs) if session.photo_refs else None,
                        json.dumps(session.photo_metadata) if session.photo_metadata else None,
                        json.dumps(session.body_measurements.to_dict())
                        if session.body_measurements
                        else None,
                        json.dumps(session.measurement_confidence)
                        if session.measurement_confidence
                        else None,
                        json.dumps(session.shape_profile)
                        if session.shape_profile
                        else None,
                        json.dumps(session.style_profile.to_dict())
                        if session.style_profile
                        else None,
                        json.dumps(session.manual_overrides)
                        if session.manual_overrides
                        else None,
                        json.dumps(session.event_log),
                        session.created_at,
                        session.updated_at,
                    ),
                )
                conn.commit()
            logger.debug("Session saved", {"session_id": session.session_id})
        except Exception as err:
            logger.error("Session save failed", err)
            raise

    def get(self, session_id: str) -> Optional["IntakeSession"]:
        """Retrieve session from database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM intake_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()

            if not row:
                return None

            # Reconstruct session from database row
            session = self._row_to_session(row)
            logger.debug("Session retrieved", {"session_id": session_id})
            return session

        except Exception as err:
            logger.error("Session retrieval failed", err)
            raise

    def get_by_user(self, user_id: str) -> Optional["IntakeSession"]:
        """Get the most recent incomplete session for a user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT * FROM intake_sessions
                    WHERE user_id = ? AND status != 'complete'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()

            if not row:
                return None

            session = self._row_to_session(row)
            logger.debug("User session retrieved", {"user_id": user_id})
            return session

        except Exception as err:
            logger.error("User session retrieval failed", err)
            raise

    def delete(self, session_id: str) -> None:
        """Delete session from database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "DELETE FROM intake_sessions WHERE session_id = ?",
                    (session_id,),
                )
                conn.commit()
            logger.debug("Session deleted", {"session_id": session_id})
        except Exception as err:
            logger.error("Session deletion failed", err)
            raise

    def _row_to_session(self, row) -> "IntakeSession":
        """Convert database row to IntakeSession object."""
        from py_src.modules.m1_intake_orchestrator import IntakeSession
        from py_src.modules.m2_sizing_integration import Measurements
        from py_src.modules.m4_style_preference import StyleProfile

        session = IntakeSession(user_id=row["user_id"])
        session.session_id = row["session_id"]
        session.status = row["status"]
        session.consent_record = (
            json.loads(row["consent_record"]) if row["consent_record"] else {}
        )
        session.photo_refs = (
            json.loads(row["photo_refs"]) if row["photo_refs"] else []
        )
        session.photo_metadata = (
            json.loads(row["photo_metadata"]) if row["photo_metadata"] else {}
        )
        session.measurement_confidence = (
            json.loads(row["measurement_confidence"])
            if row["measurement_confidence"]
            else {}
        )
        session.manual_overrides = (
            json.loads(row["manual_overrides"]) if row["manual_overrides"] else {}
        )
        session.shape_profile = (
            json.loads(row["shape_profile"]) if row["shape_profile"] else None
        )
        session.event_log = json.loads(row["event_log"]) if row["event_log"] else []
        session.created_at = row["created_at"]
        session.updated_at = row["updated_at"]

        # Reconstruct measurements object
        if row["body_measurements"]:
            m_dict = json.loads(row["body_measurements"])
            session.body_measurements = Measurements(
                bust=m_dict["bust"],
                waist=m_dict["waist"],
                hips=m_dict["hips"],
                height=m_dict["height"],
                shoulder=m_dict.get("shoulder"),
                inseam=m_dict.get("inseam"),
                unit=m_dict.get("unit", "cm"),
                confidence_scores=m_dict.get("confidence_scores"),
                provider=m_dict.get("provider", "mock"),
                provider_version=m_dict.get("provider_version", "1.0"),
            )

        # Reconstruct style profile object
        if row["style_profile"]:
            sp_dict = json.loads(row["style_profile"])
            session.style_profile = StyleProfile(
                user_id=row["user_id"],
                preferred_colors=sp_dict.get("preferred_colors", []),
                preferred_silhouettes=sp_dict.get("preferred_silhouettes", []),
                occasions=sp_dict.get("occasions", []),
                coverage_prefs=sp_dict.get("coverage_prefs", {}),
                lifestyle_context=sp_dict.get("lifestyle_context", {}),
                free_text_notes=sp_dict.get("free_text_notes", ""),
            )

        return session
