"""
API-level tests for main.py's account endpoints:
/auth/register, /auth/login, /auth/logout, /auth/logout-all,
/auth/change-password, /auth/me, /account/profile, and the
account-gating of /intake/session.
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def unique_username():
    return f"apiauth{uuid.uuid4().hex[:10]}"


def register_and_login(client, username=None, password="TestPassw0rd!"):
    username = username or unique_username()
    email = f"{username}@example.test"
    client.post("/auth/register", json={"username": username, "email": email, "password": password})
    resp = client.post("/auth/login", json={"username": username, "password": password})
    return resp.json()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


class TestRegister:
    def test_register_creates_account_without_a_token(self, client):
        username = unique_username()
        r = client.post("/auth/register", json={
            "username": username, "email": f"{username}@example.test", "password": "TestPassw0rd!",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["username"] == username
        assert "token" not in body

    def test_duplicate_username_rejected(self, client):
        username = unique_username()
        client.post("/auth/register", json={
            "username": username, "email": f"{username}@example.test", "password": "TestPassw0rd!",
        })
        r = client.post("/auth/register", json={
            "username": username, "email": "different@example.test", "password": "TestPassw0rd!",
        })
        assert r.status_code == 400
        assert "username" in r.json()["detail"].lower()

    def test_duplicate_email_rejected(self, client):
        username_a = unique_username()
        username_b = unique_username()
        email = f"{username_a}@example.test"
        client.post("/auth/register", json={"username": username_a, "email": email, "password": "TestPassw0rd!"})
        r = client.post("/auth/register", json={"username": username_b, "email": email, "password": "TestPassw0rd!"})
        assert r.status_code == 400
        assert "email" in r.json()["detail"].lower()

    def test_password_too_short_rejected(self, client):
        username = unique_username()
        r = client.post("/auth/register", json={
            "username": username, "email": f"{username}@example.test", "password": "short",
        })
        assert r.status_code == 400

    def test_missing_fields_rejected(self, client):
        r = client.post("/auth/register", json={"username": "onlyusername"})
        assert r.status_code == 422  # pydantic validation


class TestLogin:
    def test_login_returns_token(self, client):
        username = unique_username()
        client.post("/auth/register", json={
            "username": username, "email": f"{username}@example.test", "password": "TestPassw0rd!",
        })
        r = client.post("/auth/login", json={"username": username, "password": "TestPassw0rd!"})
        assert r.status_code == 200
        body = r.json()
        assert "token" in body
        assert body["username"] == username

    def test_wrong_password_rejected(self, client):
        username = unique_username()
        client.post("/auth/register", json={
            "username": username, "email": f"{username}@example.test", "password": "TestPassw0rd!",
        })
        r = client.post("/auth/login", json={"username": username, "password": "WrongPassword!"})
        assert r.status_code == 401

    def test_unknown_username_rejected_with_generic_message(self, client):
        r = client.post("/auth/login", json={"username": "no_such_user_at_all", "password": "whatever123"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid username or password"

    def test_registering_does_not_log_you_in(self, client):
        """The decided flow: registration only creates the account -- no
        session is authenticated until the user explicitly logs in."""
        username = unique_username()
        client.post("/auth/register", json={
            "username": username, "email": f"{username}@example.test", "password": "TestPassw0rd!",
        })
        r = client.post("/intake/session")  # no Authorization header at all
        assert r.status_code == 401


class TestMe:
    def test_returns_own_identity(self, client):
        account = register_and_login(client)
        r = client.get("/auth/me", headers=auth_headers(account["token"]))
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == account["user_id"]
        assert body["username"] == account["username"]
        assert "email" in body

    def test_missing_token_rejected(self, client):
        r = client.get("/auth/me")
        assert r.status_code == 401

    def test_malformed_authorization_header_rejected(self, client):
        r = client.get("/auth/me", headers={"Authorization": "not-a-bearer-token"})
        assert r.status_code == 401

    def test_garbage_token_rejected(self, client):
        r = client.get("/auth/me", headers=auth_headers("this-token-does-not-exist"))
        assert r.status_code == 401


class TestLogout:
    def test_logout_revokes_the_token(self, client):
        account = register_and_login(client)
        headers = auth_headers(account["token"])

        r = client.post("/auth/logout", headers=headers)
        assert r.status_code == 200

        r2 = client.get("/auth/me", headers=headers)
        assert r2.status_code == 401

    def test_logout_all_revokes_every_token(self, client):
        username = unique_username()
        register_and_login(client, username)
        login_a = register_and_login(client, username)
        login_b = register_and_login(client, username)

        r = client.post("/auth/logout-all", headers=auth_headers(login_a["token"]))
        assert r.status_code == 200

        assert client.get("/auth/me", headers=auth_headers(login_a["token"])).status_code == 401
        assert client.get("/auth/me", headers=auth_headers(login_b["token"])).status_code == 401


class TestChangePassword:
    def test_change_password_requires_current_password(self, client):
        account = register_and_login(client)
        r = client.post(
            "/auth/change-password",
            json={"current_password": "WrongOne!", "new_password": "BrandNewPass1"},
            headers=auth_headers(account["token"]),
        )
        assert r.status_code == 401

    def test_change_password_succeeds_and_old_token_still_works(self, client):
        username = unique_username()
        account = register_and_login(client, username, password="OriginalPass1")

        r = client.post(
            "/auth/change-password",
            json={"current_password": "OriginalPass1", "new_password": "BrandNewPass1"},
            headers=auth_headers(account["token"]),
        )
        assert r.status_code == 200

        # The token used to make the change stays valid (only OTHER tokens are revoked).
        assert client.get("/auth/me", headers=auth_headers(account["token"])).status_code == 200

        # Old password no longer works; new one does.
        assert client.post("/auth/login", json={"username": username, "password": "OriginalPass1"}).status_code == 401
        assert client.post("/auth/login", json={"username": username, "password": "BrandNewPass1"}).status_code == 200

    def test_change_password_revokes_other_tokens(self, client):
        username = unique_username()
        account = register_and_login(client, username, password="OriginalPass1")
        other_login = register_and_login(client, username, password="OriginalPass1")

        client.post(
            "/auth/change-password",
            json={"current_password": "OriginalPass1", "new_password": "BrandNewPass1"},
            headers=auth_headers(account["token"]),
        )

        assert client.get("/auth/me", headers=auth_headers(other_login["token"])).status_code == 401


class TestAccountProfile:
    def test_returns_null_when_no_completed_intake(self, client):
        account = register_and_login(client)
        r = client.get("/account/profile", headers=auth_headers(account["token"]))
        assert r.status_code == 200
        assert r.json() is None

    def test_requires_authentication(self, client):
        r = client.get("/account/profile")
        assert r.status_code == 401

    def test_returns_completed_profile_after_intake(self, client):
        account = register_and_login(client)
        headers = auth_headers(account["token"])

        session = client.post("/intake/session", headers=headers).json()
        session_id = session["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })
        client.post("/intake/preferences", json={
            "session_id": session_id, "preferred_colors": ["Ebony"],
        })

        r = client.get("/account/profile", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == session_id
        assert body["shape_profile"]["shape_class"] in [
            "pear", "apple", "hourglass", "straight", "athletic", "balanced",
        ]
        assert body["style_profile"]["preferred_colors"] == ["Ebony"]
        assert body["measurements"]["bust"] == 91
        assert body["measurements"]["waist"] == 76
        assert body["measurements"]["hips"] == 95
        assert body["measurements"]["height"] == 165

    def test_measurements_survive_relogin(self, client):
        """
        Regression coverage: logging out and back in must not blank out
        the bust/waist/hips/height shown on the "Update Style" screen --
        /account/profile has to actually return the raw measurements, not
        just the derived shape/style profile, for the frontend's login-time
        hydration to have real numbers to restore into localStorage.
        """
        username = unique_username()
        account = register_and_login(client, username)
        headers = auth_headers(account["token"])

        session_id = client.post("/intake/session", headers=headers).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 93, "waist": 74, "hips": 99, "height": 168},
        })
        client.post("/intake/preferences", json={"session_id": session_id})

        client.post("/auth/logout", headers=headers)
        relogin = client.post("/auth/login", json={"username": username, "password": "TestPassw0rd!"}).json()

        r = client.get("/account/profile", headers=auth_headers(relogin["token"]))
        assert r.status_code == 200
        measurements = r.json()["measurements"]
        assert measurements["bust"] == 93
        assert measurements["waist"] == 74
        assert measurements["hips"] == 99
        assert measurements["height"] == 168

    def test_profile_survives_relogin(self, client):
        """The core account-persistence promise: log in again (e.g. a
        different device/browser) and the saved profile is still there."""
        username = unique_username()
        account = register_and_login(client, username)
        headers = auth_headers(account["token"])

        session_id = client.post("/intake/session", headers=headers).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })
        client.post("/intake/preferences", json={"session_id": session_id})

        # Fresh login, as if from a different device/browser entirely.
        relogin = client.post("/auth/login", json={"username": username, "password": "TestPassw0rd!"}).json()
        r = client.get("/account/profile", headers=auth_headers(relogin["token"]))
        assert r.status_code == 200
        assert r.json()["session_id"] == session_id


class TestIntakeSessionGating:
    def test_missing_authorization_rejected(self, client):
        r = client.post("/intake/session")
        assert r.status_code == 401

    def test_malformed_authorization_rejected(self, client):
        r = client.post("/intake/session", headers={"Authorization": "garbage"})
        assert r.status_code == 401

    def test_valid_token_creates_a_session_for_that_account(self, client):
        account = register_and_login(client)
        r = client.post("/intake/session", headers=auth_headers(account["token"]))
        assert r.status_code == 200
        assert r.json()["user_id"] == account["user_id"]
