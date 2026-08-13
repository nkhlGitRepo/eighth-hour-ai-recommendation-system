"""
User account persistence layer: accounts, auth tokens, login-attempt lockout.

Same SQLite-file-sharing pattern as SQLiteSessionRepository/ConsentTracker --
defaults to its own db, but production wiring (main.py) passes
session_repo.db_path so everything lives in one file.
"""

import secrets
import sqlite3
import time
from typing import Optional

from py_src.constants import AUTH_TOKEN_EXPIRY_DAYS
from py_src.utils.errors import ModuleError
from py_src.utils.logger import logger


class UserRepository:
    """SQLite-backed user account, token, and login-attempt storage."""

    def __init__(self, db_path: str = "intake_sessions.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS login_attempts (
                    username TEXT PRIMARY KEY,
                    failed_count INTEGER NOT NULL,
                    window_start REAL NOT NULL
                )
                """
            )
            conn.commit()
        logger.info("User database initialized", {"path": self.db_path})

    # -- Accounts ---------------------------------------------------------

    def create_user(self, user_id: str, username: str, email: str, password_hash: str) -> None:
        """Create a new user account. Raises ModuleError on duplicate username/email."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO users (user_id, username, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, username, email, password_hash, time.time()),
                )
                conn.commit()
        except sqlite3.IntegrityError as err:
            # UNIQUE constraint is the real backstop; message here is generic
            # since the caller (AuthManager) already pre-checked which field
            # collided and raises its own specific message before this point.
            raise ModuleError(f"Account creation failed: {err}", "AUTH")

    def get_user_by_username(self, username: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE user_id = ?",
                (password_hash, user_id),
            )
            conn.commit()

    # -- Tokens -------------------------------------------------------------

    def create_token(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + AUTH_TOKEN_EXPIRY_DAYS * 86400
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, user_id, now, expires_at),
            )
            conn.commit()
        return token

    def get_user_id_for_token(self, token: str) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT user_id, expires_at FROM auth_tokens WHERE token = ?", (token,)
            ).fetchone()
        if not row:
            return None
        if row["expires_at"] < time.time():
            return None
        return row["user_id"]

    def delete_token(self, token: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
            conn.commit()

    def delete_all_tokens_for_user(self, user_id: str, except_token: Optional[str] = None) -> None:
        with sqlite3.connect(self.db_path) as conn:
            if except_token:
                conn.execute(
                    "DELETE FROM auth_tokens WHERE user_id = ? AND token != ?",
                    (user_id, except_token),
                )
            else:
                conn.execute("DELETE FROM auth_tokens WHERE user_id = ?", (user_id,))
            conn.commit()

    # -- Login lockout --------------------------------------------------------

    def record_failed_login(self, username: str, window_seconds: int) -> None:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT failed_count, window_start FROM login_attempts WHERE username = ?",
                (username,),
            ).fetchone()

            if row is None or (now - row["window_start"]) > window_seconds:
                conn.execute(
                    "INSERT OR REPLACE INTO login_attempts (username, failed_count, window_start) VALUES (?, ?, ?)",
                    (username, 1, now),
                )
            else:
                conn.execute(
                    "UPDATE login_attempts SET failed_count = failed_count + 1 WHERE username = ?",
                    (username,),
                )
            conn.commit()

    def is_locked_out(self, username: str, max_attempts: int, window_seconds: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT failed_count, window_start FROM login_attempts WHERE username = ?",
                (username,),
            ).fetchone()
        if not row:
            return False
        if (time.time() - row["window_start"]) > window_seconds:
            return False
        return row["failed_count"] >= max_attempts

    def clear_failed_logins(self, username: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM login_attempts WHERE username = ?", (username,))
            conn.commit()
