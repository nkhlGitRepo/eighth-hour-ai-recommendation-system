"""
Session persistence layer for intake sessions.

Provides database abstraction so sessions persist across server restarts.
Swappable backend: SQLite (dev) or PostgreSQL (prod).
"""

import json
import os
import sqlite3
import time
from typing import Optional, Dict, TYPE_CHECKING
from py_src.utils.logger import logger
from py_src.utils.errors import ModuleError

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

    def __init__(self, db_path: str = None):
        # DATABASE_PATH lets a deployment put the file somewhere stable (e.g. a
        # mounted disk) instead of wherever the process happened to start.
        self.db_path = db_path or os.environ.get("DATABASE_PATH", "intake_sessions.db")
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fit_check_history (
                    check_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT,
                    product_sku TEXT NOT NULL,
                    fit_scores TEXT NOT NULL,
                    recommended_size TEXT NOT NULL,
                    fit_notes TEXT,
                    confidence REAL NOT NULL,
                    checked_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fit_user_id ON fit_check_history(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fit_session_id ON fit_check_history(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fit_product_sku ON fit_check_history(product_sku)"
            )
            conn.commit()

        # Initialize feedback tables for M10
        self._init_feedback_tables()

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

    def get_latest_completed_session_by_user(self, user_id: str) -> Optional["IntakeSession"]:
        """Get the most recently completed session for a user (for account login hydration)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT * FROM intake_sessions
                    WHERE user_id = ? AND status = 'complete'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (user_id,),
                ).fetchone()

            if not row:
                return None

            return self._row_to_session(row)

        except Exception as err:
            logger.error("Latest completed session retrieval failed", err)
            raise

    def save_fit_check(self, user_id: str, session_id: str, product_sku: str, fit_result: dict) -> str:
        """Save a fit check result to history. Returns check_id."""
        import uuid
        check_id = f"check_{uuid.uuid4().hex[:12]}"
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO fit_check_history
                    (check_id, user_id, session_id, product_sku, fit_scores, recommended_size, fit_notes, confidence, checked_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        check_id,
                        user_id,
                        session_id,
                        product_sku,
                        json.dumps(fit_result.get("fit_scores", {})),
                        fit_result.get("recommended_size"),
                        json.dumps(fit_result.get("fit_notes", [])),
                        fit_result.get("confidence", 0),
                        time.time(),
                    ),
                )
                conn.commit()
            logger.debug("Fit check saved", {"check_id": check_id, "product_sku": product_sku})
            return check_id
        except Exception as err:
            logger.error("Fit check save failed", err)
            raise

    def get_fit_check_history(self, user_id: str, limit: int = 20) -> list:
        """Get most recent fit checks for a user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT * FROM fit_check_history
                    WHERE user_id = ?
                    ORDER BY checked_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()

            return [self._row_to_fit_check(row) for row in rows]
        except Exception as err:
            logger.error("Fit check history retrieval failed", err)
            raise

    def get_fit_check_by_session(self, session_id: str) -> list:
        """Get all fit checks for a specific session."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT * FROM fit_check_history
                    WHERE session_id = ?
                    ORDER BY checked_at DESC
                    """,
                    (session_id,),
                ).fetchall()

            return [self._row_to_fit_check(row) for row in rows]
        except Exception as err:
            logger.error("Session fit check retrieval failed", err)
            raise

    def get_fit_check_trend(self, user_id: str, product_sku: str, limit: int = 10) -> list:
        """Get fit check history for a specific product across all sessions (trend analysis)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT * FROM fit_check_history
                    WHERE user_id = ? AND product_sku = ?
                    ORDER BY checked_at DESC
                    LIMIT ?
                    """,
                    (user_id, product_sku, limit),
                ).fetchall()

            return [self._row_to_fit_check(row) for row in rows]
        except Exception as err:
            logger.error("Fit check trend retrieval failed", err)
            raise

    def _row_to_fit_check(self, row) -> dict:
        """Convert database row to fit check dict."""
        return {
            "check_id": row["check_id"],
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "product_sku": row["product_sku"],
            "fit_scores": json.loads(row["fit_scores"]) if row["fit_scores"] else {},
            "recommended_size": row["recommended_size"],
            "fit_notes": json.loads(row["fit_notes"]) if row["fit_notes"] else [],
            "confidence": row["confidence"],
            "checked_at": row["checked_at"],
        }

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
            try:
                m_dict = json.loads(row["body_measurements"])
                # Validate required measurement fields
                required = {"bust", "waist", "hips", "height"}
                missing = required - set(m_dict.keys())
                if missing:
                    raise ModuleError(
                        f"Session data corrupted: measurements missing {missing}",
                        "SessionRepository"
                    )
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
                # Measurements.__init__ stamps extracted_at with "now", which
                # would make every reload look like the measurements were
                # just taken. The real value is already persisted inside the
                # JSON above (to_dict includes it) -- restore it so "when was
                # this measured" survives a round-trip.
                if m_dict.get("extracted_at"):
                    session.body_measurements.extracted_at = m_dict["extracted_at"]
            except (json.JSONDecodeError, KeyError, ValueError) as err:
                logger.error("Session reconstruction failed", {"error": str(err), "session_id": row["session_id"]})
                raise ModuleError(
                    f"Failed to deserialize session measurements: {str(err)}",
                    "SessionRepository"
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

    def _init_feedback_tables(self):
        """Initialize feedback tables for M10 learning loop."""
        with sqlite3.connect(self.db_path) as conn:
            # Fit feedback table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS fit_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    fit_check_id TEXT,
                    product_sku TEXT NOT NULL,
                    feedback_type TEXT NOT NULL,
                    actual_size TEXT,
                    notes TEXT,
                    submitted_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON fit_feedback(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_product_sku ON fit_feedback(product_sku)"
            )

            # Product feedback table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS product_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    product_sku TEXT NOT NULL,
                    feedback_type TEXT NOT NULL,
                    purchased BOOLEAN,
                    rating REAL,
                    notes TEXT,
                    submitted_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_feedback_user_id ON product_feedback(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_product_feedback_sku ON product_feedback(product_sku)"
            )
            conn.commit()

    def save_feedback(self, user_id: str, feedback_record: Dict) -> None:
        """Save fit check feedback."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO fit_feedback
                (feedback_id, user_id, fit_check_id, product_sku, feedback_type, actual_size, notes, submitted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_record["feedback_id"],
                    user_id,
                    feedback_record.get("fit_check_id"),
                    feedback_record["product_sku"],
                    feedback_record["feedback_type"],
                    feedback_record.get("actual_size"),
                    feedback_record.get("notes"),
                    feedback_record["submitted_at"],
                ),
            )
            conn.commit()

    def save_product_feedback(self, user_id: str, feedback_record: Dict) -> None:
        """Save product satisfaction feedback."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO product_feedback
                (feedback_id, user_id, product_sku, feedback_type, purchased, rating, notes, submitted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_record["feedback_id"],
                    user_id,
                    feedback_record["product_sku"],
                    feedback_record["feedback_type"],
                    feedback_record.get("purchased", False),
                    feedback_record.get("rating"),
                    feedback_record.get("notes"),
                    feedback_record["submitted_at"],
                ),
            )
            conn.commit()

    def get_user_fit_feedback(self, user_id: str) -> Optional[list]:
        """Get all fit feedback for a user."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM fit_feedback WHERE user_id = ?
                ORDER BY submitted_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows] if rows else None

    def get_user_product_feedback(self, user_id: str) -> Optional[list]:
        """Get all product feedback for a user."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM product_feedback WHERE user_id = ?
                ORDER BY submitted_at DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows] if rows else None
