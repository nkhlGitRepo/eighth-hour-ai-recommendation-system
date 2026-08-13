"""
Unit tests for UserRepository (py_src/persistence/user_repository.py) and
AuthManager (py_src/guardrails/auth_manager.py), constructed directly as
plain Python objects -- no HTTP layer involved (see test_api_auth.py for
the endpoint-level tests).
"""

import os
import tempfile
import time

import bcrypt
import pytest

from py_src.persistence.user_repository import UserRepository
from py_src.guardrails.auth_manager import AuthManager
from py_src.utils.errors import AuthError, ModuleError
from py_src.constants import MAX_LOGIN_ATTEMPTS


@pytest.fixture
def user_repo():
    fd, path = tempfile.mkstemp(suffix=".db", prefix="test_users_")
    os.close(fd)
    repo = UserRepository(db_path=path)
    yield repo
    os.remove(path)


@pytest.fixture
def auth_manager(user_repo):
    return AuthManager(user_repo)


class TestUserRepository:
    def test_create_and_get_user_by_username(self, user_repo):
        user_repo.create_user("user_1", "alice", "alice@example.test", "hashed")
        user = user_repo.get_user_by_username("alice")
        assert user["user_id"] == "user_1"
        assert user["email"] == "alice@example.test"

    def test_duplicate_username_rejected(self, user_repo):
        user_repo.create_user("user_1", "alice", "alice@example.test", "hashed")
        with pytest.raises(ModuleError):
            user_repo.create_user("user_2", "alice", "different@example.test", "hashed")

    def test_duplicate_email_rejected(self, user_repo):
        user_repo.create_user("user_1", "alice", "alice@example.test", "hashed")
        with pytest.raises(ModuleError):
            user_repo.create_user("user_2", "someoneelse", "alice@example.test", "hashed")

    def test_get_unknown_username_returns_none(self, user_repo):
        assert user_repo.get_user_by_username("nobody") is None

    def test_token_create_lookup_and_delete(self, user_repo):
        user_repo.create_user("user_1", "alice", "alice@example.test", "hashed")
        token = user_repo.create_token("user_1")
        assert user_repo.get_user_id_for_token(token) == "user_1"

        user_repo.delete_token(token)
        assert user_repo.get_user_id_for_token(token) is None

    def test_expired_token_is_not_returned(self, user_repo):
        user_repo.create_user("user_1", "alice", "alice@example.test", "hashed")
        token = user_repo.create_token("user_1")

        # Force expiry directly rather than waiting real days.
        import sqlite3
        with sqlite3.connect(user_repo.db_path) as conn:
            conn.execute("UPDATE auth_tokens SET expires_at = ? WHERE token = ?", (time.time() - 1, token))
            conn.commit()

        assert user_repo.get_user_id_for_token(token) is None

    def test_delete_all_tokens_for_user(self, user_repo):
        user_repo.create_user("user_1", "alice", "alice@example.test", "hashed")
        t1 = user_repo.create_token("user_1")
        t2 = user_repo.create_token("user_1")

        user_repo.delete_all_tokens_for_user("user_1")
        assert user_repo.get_user_id_for_token(t1) is None
        assert user_repo.get_user_id_for_token(t2) is None

    def test_delete_all_tokens_except_one(self, user_repo):
        user_repo.create_user("user_1", "alice", "alice@example.test", "hashed")
        keep = user_repo.create_token("user_1")
        revoke = user_repo.create_token("user_1")

        user_repo.delete_all_tokens_for_user("user_1", except_token=keep)
        assert user_repo.get_user_id_for_token(keep) == "user_1"
        assert user_repo.get_user_id_for_token(revoke) is None

    def test_lockout_counting(self, user_repo):
        for _ in range(MAX_LOGIN_ATTEMPTS):
            assert user_repo.is_locked_out("alice", MAX_LOGIN_ATTEMPTS, 900) is False
            user_repo.record_failed_login("alice", 900)
        assert user_repo.is_locked_out("alice", MAX_LOGIN_ATTEMPTS, 900) is True

    def test_clear_failed_logins_resets_lockout(self, user_repo):
        for _ in range(MAX_LOGIN_ATTEMPTS):
            user_repo.record_failed_login("alice", 900)
        assert user_repo.is_locked_out("alice", MAX_LOGIN_ATTEMPTS, 900) is True

        user_repo.clear_failed_logins("alice")
        assert user_repo.is_locked_out("alice", MAX_LOGIN_ATTEMPTS, 900) is False

    def test_lockout_window_expires(self, user_repo):
        for _ in range(MAX_LOGIN_ATTEMPTS):
            user_repo.record_failed_login("alice", 900)

        import sqlite3
        with sqlite3.connect(user_repo.db_path) as conn:
            conn.execute("UPDATE login_attempts SET window_start = ? WHERE username = ?", (time.time() - 1000, "alice"))
            conn.commit()

        assert user_repo.is_locked_out("alice", MAX_LOGIN_ATTEMPTS, 900) is False


class TestAuthManagerRegister:
    def test_register_creates_account_without_a_token(self, auth_manager):
        result = auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        assert "user_id" in result
        assert result["username"] == "alice"
        assert "token" not in result

    def test_register_normalizes_username_and_email(self, auth_manager, user_repo):
        auth_manager.register("Alice", "  Alice@Example.TEST  ", "correcthorsebattery")
        assert user_repo.get_user_by_username("alice") is not None
        assert user_repo.get_user_by_email("alice@example.test") is not None

    def test_duplicate_username_rejected_with_clear_message(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        with pytest.raises(ModuleError) as exc:
            auth_manager.register("alice", "different@example.test", "correcthorsebattery")
        assert "username" in exc.value.message.lower()

    def test_duplicate_email_rejected_with_clear_message(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        with pytest.raises(ModuleError) as exc:
            auth_manager.register("bob", "alice@example.test", "correcthorsebattery")
        assert "email" in exc.value.message.lower()

    def test_password_too_short_rejected(self, auth_manager):
        with pytest.raises(ModuleError):
            auth_manager.register("alice", "alice@example.test", "short1")

    def test_password_too_long_rejected(self, auth_manager):
        with pytest.raises(ModuleError):
            auth_manager.register("alice", "alice@example.test", "x" * 200)

    def test_invalid_username_characters_rejected(self, auth_manager):
        with pytest.raises(ModuleError):
            auth_manager.register("alice!!", "alice@example.test", "correcthorsebattery")

    def test_invalid_email_rejected(self, auth_manager):
        with pytest.raises(ModuleError):
            auth_manager.register("alice", "not-an-email", "correcthorsebattery")

    def test_password_never_stored_in_plaintext(self, auth_manager, user_repo):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        user = user_repo.get_user_by_username("alice")
        assert user["password_hash"] != "correcthorsebattery"
        assert bcrypt.checkpw(b"correcthorsebattery", user["password_hash"].encode("utf-8"))


class TestAuthManagerLogin:
    def test_login_succeeds_with_correct_password(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        result = auth_manager.login("alice", "correcthorsebattery")
        assert result["username"] == "alice"
        assert "token" in result

    def test_login_fails_with_wrong_password(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        with pytest.raises(AuthError):
            auth_manager.login("alice", "wrongpassword")

    def test_login_fails_for_unknown_username(self, auth_manager):
        with pytest.raises(AuthError):
            auth_manager.login("nobody", "whatever123")

    def test_bad_username_and_bad_password_give_the_identical_message(self, auth_manager):
        """No username enumeration: both failure modes must be indistinguishable."""
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")

        try:
            auth_manager.login("alice", "wrongpassword")
            assert False, "expected AuthError"
        except AuthError as wrong_password_err:
            wrong_password_message = wrong_password_err.message

        try:
            auth_manager.login("nobody", "whatever123")
            assert False, "expected AuthError"
        except AuthError as unknown_user_err:
            unknown_user_message = unknown_user_err.message

        assert wrong_password_message == unknown_user_message

    def test_lockout_after_max_attempts(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        for _ in range(MAX_LOGIN_ATTEMPTS):
            with pytest.raises(AuthError):
                auth_manager.login("alice", "wrongpassword")

        # Even the CORRECT password is now rejected -- locked out, not just failed.
        with pytest.raises(AuthError):
            auth_manager.login("alice", "correcthorsebattery")

    def test_successful_login_clears_previous_failed_attempts(self, auth_manager, user_repo):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        for _ in range(MAX_LOGIN_ATTEMPTS - 1):
            with pytest.raises(AuthError):
                auth_manager.login("alice", "wrongpassword")

        auth_manager.login("alice", "correcthorsebattery")
        assert user_repo.is_locked_out("alice", MAX_LOGIN_ATTEMPTS, 900) is False


class TestAuthManagerLogoutAndTokens:
    def test_get_current_user_id_resolves_a_valid_token(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        token = auth_manager.login("alice", "correcthorsebattery")["token"]
        user_id = auth_manager.get_current_user_id(token)
        assert user_id is not None

    def test_get_current_user_id_rejects_invalid_token(self, auth_manager):
        with pytest.raises(AuthError):
            auth_manager.get_current_user_id("not-a-real-token")

    def test_logout_revokes_only_the_current_token(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        token_a = auth_manager.login("alice", "correcthorsebattery")["token"]
        token_b = auth_manager.login("alice", "correcthorsebattery")["token"]

        auth_manager.logout(token_a)
        with pytest.raises(AuthError):
            auth_manager.get_current_user_id(token_a)
        assert auth_manager.get_current_user_id(token_b) is not None

    def test_logout_all_revokes_every_token(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        login = auth_manager.login("alice", "correcthorsebattery")
        token_a = login["token"]
        token_b = auth_manager.login("alice", "correcthorsebattery")["token"]

        auth_manager.logout_all(login["user_id"])
        with pytest.raises(AuthError):
            auth_manager.get_current_user_id(token_a)
        with pytest.raises(AuthError):
            auth_manager.get_current_user_id(token_b)


class TestAuthManagerChangePassword:
    def test_change_password_requires_correct_current_password(self, auth_manager):
        login = auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        login = auth_manager.login("alice", "correcthorsebattery")
        with pytest.raises(AuthError):
            auth_manager.change_password(login["user_id"], "wrongcurrent", "newpassword123", login["token"])

    def test_change_password_updates_hash_and_allows_new_login(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        login = auth_manager.login("alice", "correcthorsebattery")
        auth_manager.change_password(login["user_id"], "correcthorsebattery", "newpassword123", login["token"])

        with pytest.raises(AuthError):
            auth_manager.login("alice", "correcthorsebattery")
        assert auth_manager.login("alice", "newpassword123")["token"]

    def test_change_password_revokes_other_tokens_but_keeps_current(self, auth_manager):
        auth_manager.register("alice", "alice@example.test", "correcthorsebattery")
        login = auth_manager.login("alice", "correcthorsebattery")
        other_token = auth_manager.login("alice", "correcthorsebattery")["token"]

        auth_manager.change_password(login["user_id"], "correcthorsebattery", "newpassword123", login["token"])

        assert auth_manager.get_current_user_id(login["token"]) is not None
        with pytest.raises(AuthError):
            auth_manager.get_current_user_id(other_token)
