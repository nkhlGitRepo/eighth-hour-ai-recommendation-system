"""Consent tracking for GDPR and BIPA compliance."""

import os
import sqlite3
import tempfile
import time


class ConsentTracker:
    """
    Tracks user consent for data processing.

    Persisted to SQLite so consent survives server restarts. Previously
    this was a plain in-memory dict: intake sessions persist to disk and
    correctly restore their own consent_record field, but the actual gate
    every module checks (has_measurement_consent) read from this in-memory
    history instead -- so a server restart would silently "revoke" consent
    for every still-valid session, forcing customers to re-consent for no
    reason.

    db_path defaults to a fresh, private file per instance (not a shared
    production path) so the many call sites across the app and test suite
    that construct ConsentTracker() with no arguments -- expecting a clean
    slate, the same guarantee the old in-memory dict gave them for free --
    keep working without cross-instance pollution. Callers that need
    consent to actually survive a restart (production: main.py, and
    IntakeOrchestrator deriving its path from its session_repo) must pass
    an explicit, stable db_path.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or self._new_isolated_db_path()
        self._init_db()

    @staticmethod
    def _new_isolated_db_path() -> str:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="consent_")
        os.close(fd)
        return path

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS consent_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    photo_consent INTEGER NOT NULL,
                    measurement_consent INTEGER NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_consent_user_id ON consent_records(user_id)"
            )
            conn.commit()

    def record_consent(self, user_id, photo_consent, measurement_consent):
        """
        Record a consent decision.

        Args:
            user_id: User ID
            photo_consent: Boolean
            measurement_consent: Boolean

        Returns:
            Consent record dict
        """
        timestamp = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO consent_records (user_id, photo_consent, measurement_consent, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, int(bool(photo_consent)), int(bool(measurement_consent)), timestamp),
            )
            conn.commit()

        return {
            "timestamp": timestamp,
            "photo_consent": photo_consent,
            "measurement_consent": measurement_consent,
        }

    def get_latest_consent(self, user_id):
        """
        Get the most recent consent record for a user.

        Args:
            user_id: User ID

        Returns:
            Consent dict or None
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT photo_consent, measurement_consent, timestamp
                FROM consent_records
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

        if not row:
            return None

        return {
            "timestamp": row["timestamp"],
            "photo_consent": bool(row["photo_consent"]),
            "measurement_consent": bool(row["measurement_consent"]),
        }

    def has_photo_consent(self, user_id):
        """Check if user has consented to photo processing."""
        consent = self.get_latest_consent(user_id)
        return consent.get("photo_consent", False) if consent else False

    def has_measurement_consent(self, user_id):
        """Check if user has consented to measurement processing."""
        consent = self.get_latest_consent(user_id)
        return consent.get("measurement_consent", False) if consent else False

    def withdraw_consent(self, user_id, consent_type=None):
        """
        Withdraw consent (photo, measurement, or both).

        Args:
            user_id: User ID
            consent_type: 'photo', 'measurement', or None for both

        Returns:
            New consent record with withdrawn consent
        """
        latest = self.get_latest_consent(user_id)
        if not latest:
            return None

        photo_consent = latest["photo_consent"]
        measurement_consent = latest["measurement_consent"]

        if consent_type == "photo" or consent_type is None:
            photo_consent = False
        if consent_type == "measurement" or consent_type is None:
            measurement_consent = False

        return self.record_consent(user_id, photo_consent, measurement_consent)

    def get_consent_summary(self, user_id):
        """Get a summary of user's current consent state."""
        consent = self.get_latest_consent(user_id)
        if not consent:
            return {
                "user_id": user_id,
                "has_any_consent": False,
                "photo_consent": False,
                "measurement_consent": False,
            }

        return {
            "user_id": user_id,
            "has_any_consent": (
                consent.get("photo_consent", False)
                or consent.get("measurement_consent", False)
            ),
            "photo_consent": consent.get("photo_consent", False),
            "measurement_consent": consent.get("measurement_consent", False),
            "last_updated": consent.get("timestamp"),
        }
