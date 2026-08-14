"""
API-level tests for main.py's intake endpoints:
/intake/session, /intake/screen, /intake/consent, /intake/photo,
/intake/confirm, /intake/preferences, /intake/resume.

Uses FastAPI's TestClient against the real app (shared process-global
catalog/session store/consent tracker, same as test_main_endpoints.py) --
every test uses a freshly generated user_id/session_id to avoid collisions
with other tests or normal dev use of the same on-disk database.
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def unique_user():
    return f"api-intake-{uuid.uuid4().hex[:8]}"


def create_session(client, name_hint):
    """
    /intake/session is account-gated: registers a fresh account (derived
    from name_hint, sanitized to fit the username charset) and logs in,
    then creates the session with that account's bearer token. Returns
    the /intake/session response -- same shape as the old direct call,
    just with a server-assigned user_id instead of the caller's name_hint.
    """
    username = "".join(c for c in name_hint.lower() if c.isalnum() or c == "_")[:32]
    password = "TestPassw0rd!"
    client.post("/auth/register", json={
        "username": username, "email": f"{username}@example.test", "password": password,
    })
    token = client.post("/auth/login", json={"username": username, "password": password}).json()["token"]
    return client.post("/intake/session", headers={"Authorization": f"Bearer {token}"})


class TestCreateSession:
    def test_creates_session_for_the_authenticated_account(self, client):
        user_id = unique_user()
        r = create_session(client, user_id)
        assert r.status_code == 200
        body = r.json()
        assert "user_id" in body
        assert "session_id" in body
        assert body["status"] == "initiated"
        assert "created_at" in body and "updated_at" in body

    def test_missing_authorization_is_rejected(self, client):
        r = client.post("/intake/session")
        assert r.status_code == 401

    def test_each_call_creates_a_distinct_session(self, client):
        user_id = unique_user()
        r1 = create_session(client, user_id).json()
        r2 = create_session(client, user_id).json()
        assert r1["session_id"] != r2["session_id"]


class TestIntakeScreen:
    """
    /intake/screen is a static config lookup (not a resource), and returns
    200 with an "error" key in the body for unknown states rather than a
    4xx status -- documenting that as the actual, intentional contract.
    """

    @pytest.mark.parametrize("state", [
        "consent", "photo_capture", "measurement_extraction",
        "manual_entry", "profile_generation", "preferences_capture",
    ])
    def test_known_states_return_schema(self, client, state):
        r = client.get("/intake/screen", params={"state": state})
        assert r.status_code == 200
        body = r.json()
        assert body["state"] == state
        assert "title" in body
        assert "fields" in body and isinstance(body["fields"], list)

    def test_unknown_state_returns_200_with_error_key(self, client):
        """Documented current behavior: NOT a 404 -- an error key in a 200 body."""
        r = client.get("/intake/screen", params={"state": "not_a_real_state"})
        assert r.status_code == 200
        assert "error" in r.json()

    def test_missing_state_param_rejected(self, client):
        r = client.get("/intake/screen")
        assert r.status_code == 422


class TestIntakeConsent:
    def test_consent_transitions_to_photo_capture(self, client):
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]

        r = client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "photo_capture"
        assert body["consent_recorded"] is True

    def test_partial_consent_rejected(self, client):
        """Both consents are required together (all-or-nothing)."""
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]

        r = client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": False,
        })
        assert r.status_code == 403

    def test_unknown_session_id_rejected(self, client):
        r = client.post("/intake/consent", json={
            "session_id": "nonexistent-session-id", "photo_consent": True, "measurement_consent": True,
        })
        assert r.status_code == 400

    def test_consent_also_recorded_for_downstream_consent_tracker_checks(self, client):
        """
        /intake/consent must actually satisfy has_measurement_consent for
        this user_id -- otherwise every subsequent step (confirm,
        recommendations, fit-check) would incorrectly reject them.
        """
        user_id = unique_user()
        s = create_session(client, user_id).json()
        session_id = s["session_id"]

        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })

        consent_status = client.get(f"/consent/{s['user_id']}")
        assert consent_status.status_code == 200
        assert consent_status.json()["measurement_consent"] is True


class TestIntakePhoto:
    def test_upload_photo_transitions_state(self, client):
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })

        r = client.post("/intake/photo", json={
            "session_id": session_id, "photo_ref": "s3://bucket/photo.jpg", "height_cm": 165.0,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["photo_uploaded"] is True
        assert body["status"] == "measurement_extraction"

    def test_empty_photo_ref_rejected(self, client):
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]

        r = client.post("/intake/photo", json={"session_id": session_id, "photo_ref": ""})
        assert r.status_code == 400

    def test_unknown_session_rejected(self, client):
        r = client.post("/intake/photo", json={
            "session_id": "nonexistent-session", "photo_ref": "s3://bucket/photo.jpg",
        })
        assert r.status_code == 400

    def test_auto_confirm_after_photo_upload_currently_fails(self, client):
        """
        Documents the behavior of the *photo-ref* endpoint specifically:
        POST /intake/photo only records a reference string, it never calls
        extraction, so confirming afterwards with no manual_overrides still
        has no measurements to build a profile from.

        This is not a gap in photo measurement overall -- the working photo
        path is POST /intake/photo-measure, which accepts the actual image
        bytes, runs extraction, and generates the shape profile (see
        tests/test_api_photo_measure.py). This ref-based endpoint is kept for
        a future vendor flow where the image is uploaded out-of-band and
        referenced by URI, and it is deliberately left un-wired until such a
        provider exists.
        """
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/photo", json={
            "session_id": session_id, "photo_ref": "s3://bucket/photo.jpg", "height_cm": 165.0,
        })

        r = client.post("/intake/confirm", json={"session_id": session_id})
        assert r.status_code == 400
        assert "No measurements" in r.json()["detail"]


class TestIntakeConfirm:
    def test_manual_measurements_generate_profile(self, client):
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })

        r = client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "preferences_capture"
        assert body["shape_profile"]["shape_class"] in [
            "pear", "apple", "hourglass", "straight", "athletic", "balanced",
        ]

    def test_confirm_without_consent_rejected(self, client):
        """Confirming measurements before consent must not silently succeed."""
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]

        r = client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })
        assert r.status_code == 403

    def test_invalid_measurements_rejected(self, client):
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })

        r = client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 9999, "waist": 76, "hips": 95, "height": 165},
        })
        assert r.status_code == 400

    def test_unknown_session_rejected(self, client):
        r = client.post("/intake/confirm", json={
            "session_id": "nonexistent-session",
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })
        assert r.status_code == 400

    def test_resubmitting_measurements_on_completed_session_still_works(self, client):
        """Regression coverage for the 'Update Style' consent-survival fix."""
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })
        client.post("/intake/preferences", json={
            "session_id": session_id, "preferred_colors": ["Ebony"],
            "preferred_silhouettes": ["fitted"], "occasions": ["work"],
        })

        r = client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 88, "waist": 70, "hips": 100, "height": 165},
        })
        assert r.status_code == 200


class TestIntakePreferences:
    def test_preferences_completes_intake(self, client):
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })

        r = client.post("/intake/preferences", json={
            "session_id": session_id,
            "preferred_colors": ["Ebony"],
            "preferred_silhouettes": ["fitted"],
            "occasions": ["work"],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "complete"
        assert body["intake_complete"] is True
        assert body["style_profile"]["preferred_colors"] == ["Ebony"]

    def test_empty_preferences_still_completes_intake(self, client):
        """Preferences are optional; the flow must not require any of them."""
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })

        r = client.post("/intake/preferences", json={"session_id": session_id})
        assert r.status_code == 200
        assert r.json()["status"] == "complete"

    def test_invalid_silhouette_rejected(self, client):
        user_id = unique_user()
        session_id = create_session(client, user_id).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })

        r = client.post("/intake/preferences", json={
            "session_id": session_id,
            "preferred_silhouettes": ["not_a_real_silhouette"],
        })
        assert r.status_code == 400

    def test_unknown_session_rejected(self, client):
        r = client.post("/intake/preferences", json={"session_id": "nonexistent-session"})
        assert r.status_code == 400


class TestIntakeResume:
    def test_resumes_most_recent_incomplete_session(self, client):
        user_id = unique_user()
        created = create_session(client, user_id).json()
        real_user_id = created["user_id"]  # server-assigned, not the name_hint

        r = client.post("/intake/resume", json={"user_id": real_user_id})
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == created["session_id"]
        assert body["user_id"] == real_user_id

    def test_no_resumable_session_returns_404(self, client):
        user_id = unique_user()  # never created any session
        r = client.post("/intake/resume", json={"user_id": user_id})
        assert r.status_code == 404

    def test_does_not_resume_a_completed_session(self, client):
        """A finished intake shouldn't be offered as 'resume' -- the user
        should go through /intake/session again (or 'Update Style') instead."""
        user_id = unique_user()
        created = create_session(client, user_id).json()
        real_user_id = created["user_id"]
        session_id = created["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })
        client.post("/intake/preferences", json={"session_id": session_id})

        r = client.post("/intake/resume", json={"user_id": real_user_id})
        assert r.status_code == 404
