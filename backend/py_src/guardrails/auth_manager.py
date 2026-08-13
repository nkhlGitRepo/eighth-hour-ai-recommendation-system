"""
Account registration, login, and session-token management.

Guardrails applied:
- bcrypt password hashing (never store/log/echo a raw password)
- Per-username brute-force lockout
- Timing/response-indistinguishable login failures (no username enumeration)
- AuditLogger: log auth events (hashed user id only, never credentials)
"""

import re
import secrets

import bcrypt

from py_src.constants import (
    MIN_PASSWORD_LENGTH,
    MAX_PASSWORD_LENGTH,
    MIN_USERNAME_LENGTH,
    MAX_USERNAME_LENGTH,
    MAX_LOGIN_ATTEMPTS,
    LOGIN_LOCKOUT_MINUTES,
)
from py_src.guardrails.audit_logger import AuditLogger
from py_src.utils.errors import AuthError, ModuleError
from py_src.utils.logger import logger

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]+$")
EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+$")

# Precomputed dummy hash checked when a username doesn't exist, so a
# missing-user login takes the same bcrypt.checkpw path (and roughly the
# same time) as a wrong-password login for a real user -- the response
# and timing are otherwise the only way to tell the two cases apart.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing-safety", bcrypt.gensalt(rounds=12))


class AuthManager:
    """Registers accounts, authenticates logins, and manages tokens."""

    def __init__(self, user_repository):
        self.user_repository = user_repository
        logger.info("AuthManager initialized")

    def register(self, username: str, email: str, password: str) -> dict:
        """
        Create a new account. Does NOT issue a token -- the user logs in
        separately afterward, per the decided registration flow.

        Returns: {"user_id": ..., "username": ...}
        Raises: ModuleError on invalid/duplicate username, email, or password.
        """
        username = self._normalize_username(username)
        email = self._normalize_email(email)
        self._validate_password(password)

        if self.user_repository.get_user_by_username(username):
            raise ModuleError("This username is already taken", "AUTH")
        if self.user_repository.get_user_by_email(email):
            raise ModuleError("This email is already registered", "AUTH")

        user_id = f"user_{secrets.token_hex(8)}"
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        self.user_repository.create_user(user_id, username, email, password_hash)

        AuditLogger.log_event("ACCOUNT_REGISTERED", user_id, {})
        return {"user_id": user_id, "username": username}

    def login(self, username: str, password: str) -> dict:
        """
        Authenticate a login. Returns {"user_id", "username", "token"}.
        Raises AuthError("Invalid username or password") on any failure
        (no such user, wrong password, or locked out) -- deliberately the
        same message/shape in every failure case.
        """
        username = self._normalize_username(username)

        if self.user_repository.is_locked_out(username, MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_MINUTES * 60):
            raise AuthError("Too many failed login attempts. Try again in a few minutes.")

        user = self.user_repository.get_user_by_username(username)
        password_hash = user["password_hash"].encode("utf-8") if user else _DUMMY_HASH
        password_ok = bcrypt.checkpw(password.encode("utf-8"), password_hash)

        if not user or not password_ok:
            self.user_repository.record_failed_login(username, LOGIN_LOCKOUT_MINUTES * 60)
            raise AuthError("Invalid username or password")

        self.user_repository.clear_failed_logins(username)
        token = self.user_repository.create_token(user["user_id"])

        AuditLogger.log_event("LOGIN_SUCCEEDED", user["user_id"], {})
        return {"user_id": user["user_id"], "username": user["username"], "token": token}

    def logout(self, token: str) -> None:
        self.user_repository.delete_token(token)

    def logout_all(self, user_id: str) -> None:
        self.user_repository.delete_all_tokens_for_user(user_id)
        AuditLogger.log_event("LOGOUT_ALL", user_id, {})

    def change_password(self, user_id: str, current_password: str, new_password: str, current_token: str) -> None:
        """Verify current_password, set new_password, and revoke every other token."""
        user = self.user_repository.get_user_by_id(user_id)
        if not user or not bcrypt.checkpw(current_password.encode("utf-8"), user["password_hash"].encode("utf-8")):
            raise AuthError("Current password is incorrect")

        self._validate_password(new_password)
        new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        self.user_repository.update_password_hash(user_id, new_hash)
        self.user_repository.delete_all_tokens_for_user(user_id, except_token=current_token)

        AuditLogger.log_event("PASSWORD_CHANGED", user_id, {})

    def get_current_user_id(self, token: str) -> str:
        """Look up the account for a bearer token. Raises AuthError if missing/expired."""
        user_id = self.user_repository.get_user_id_for_token(token)
        if not user_id:
            raise AuthError("Invalid or expired token")
        return user_id

    # -- Validation -------------------------------------------------------

    def _normalize_username(self, username: str) -> str:
        if not isinstance(username, str):
            raise ModuleError("Username is required", "AUTH")
        username = username.strip().lower()
        if not (MIN_USERNAME_LENGTH <= len(username) <= MAX_USERNAME_LENGTH):
            raise ModuleError(
                f"Username must be {MIN_USERNAME_LENGTH}-{MAX_USERNAME_LENGTH} characters", "AUTH"
            )
        if not USERNAME_PATTERN.match(username):
            raise ModuleError("Username may only contain letters, numbers, and underscores", "AUTH")
        return username

    def _normalize_email(self, email: str) -> str:
        if not isinstance(email, str):
            raise ModuleError("Email is required", "AUTH")
        email = email.strip().lower()
        if not EMAIL_PATTERN.match(email) or len(email) > 254:
            raise ModuleError("Enter a valid email address", "AUTH")
        return email

    def _validate_password(self, password: str) -> None:
        if not isinstance(password, str) or not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
            raise ModuleError(
                f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters", "AUTH"
            )
