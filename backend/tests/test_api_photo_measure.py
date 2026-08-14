"""
API-level tests for the photo-measurement endpoints:
POST /intake/photo-measure and GET /intake/photo-disclosure.
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from main import app
from py_src.guardrails.image_validation import MAX_IMAGE_BYTES


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# Minimal valid image payloads. The mock provider never inspects content, so
# these only need to satisfy ImageValidator's magic-byte check.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 512
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 512


def unique_username():
    return f"photomeas{uuid.uuid4().hex[:10]}"


def register_and_login(client, password="PhotoMeasPass1"):
    username = unique_username()
    client.post("/auth/register", json={
        "username": username, "email": f"{username}@example.test", "password": password,
    })
    return client.post("/auth/login", json={"username": username, "password": password}).json()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def consented_session(client, account, photo_consent=True):
    """Create an intake session with consent on record for this account."""
    headers = auth_headers(account["token"])
    session_id = client.post("/intake/session", headers=headers).json()["session_id"]
    client.post("/intake/consent", json={
        "session_id": session_id,
        "photo_consent": photo_consent,
        "measurement_consent": True,
    })
    return session_id


def scan(client, token, session_id, height_cm=170.0, image=JPEG,
         filename="photo.jpg", content_type="image/jpeg"):
    return client.post(
        "/intake/photo-measure",
        headers=auth_headers(token),
        data={"session_id": session_id, "height_cm": str(height_cm)},
        files={"photo": (filename, image, content_type)},
    )


class TestPhotoDisclosure:
    """
    The upload screen renders its legal notice from this endpoint, so it must
    describe what the active provider actually does.
    """

    def test_returns_the_required_disclosure_fields(self, client):
        r = client.get("/intake/photo-disclosure")
        assert r.status_code == 200
        body = r.json()
        for key in ("processor_name", "sends_image_offsite", "stores_image",
                    "derives_from_image", "retention"):
            assert key in body

    def test_mock_provider_declares_no_offsite_transmission(self, client):
        """With the mock active nothing leaves this machine, and the notice
        must say so rather than implying a third-party AI is involved."""
        body = client.get("/intake/photo-disclosure").json()
        assert body["sends_image_offsite"] is False
        assert body["stores_image"] is False

    def test_mock_provider_declares_it_does_not_analyse_the_photo(self, client):
        """
        The UI relies on this to label results as samples rather than claiming
        they were measured from the customer's photo.
        """
        assert client.get("/intake/photo-disclosure").json()["derives_from_image"] is False

    def test_is_readable_without_auth(self, client):
        """Policy text is public; customers shouldn't need an account to read it."""
        assert client.get("/intake/photo-disclosure").status_code == 200


class TestPhotoMeasureHappyPath:
    def test_returns_profile_and_measurements(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = scan(client, account["token"], session_id, height_cm=170.0)

        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == session_id
        assert body["shape_profile"]["shape_class"] in [
            "pear", "apple", "hourglass", "straight", "athletic", "balanced",
        ]
        assert body["measurements"]["bust"] > 0
        assert body["measurements"]["unit"] == "cm"
        assert body["provider"] == "mock"
        assert body["low_confidence_fields"] == []

    def test_submitted_height_is_used_not_a_hardcoded_default(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = scan(client, account["token"], session_id, height_cm=183.0)

        assert r.json()["measurements"]["height"] == 183.0

    def test_accepts_png(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = scan(client, account["token"], session_id, image=PNG,
                 filename="photo.png", content_type="image/png")

        assert r.status_code == 200

    def test_measurements_reach_account_profile_after_completing_intake(self, client):
        """End-to-end: the photo path completes intake exactly like manual entry."""
        account = register_and_login(client)
        headers = auth_headers(account["token"])
        session_id = consented_session(client, account)

        scan(client, account["token"], session_id, height_cm=175.0)
        prefs = client.post("/intake/preferences", json={
            "session_id": session_id, "preferred_colors": ["Ebony"],
        })
        assert prefs.status_code == 200
        assert prefs.json()["status"] == "complete"

        profile = client.get("/account/profile", headers=headers)
        assert profile.status_code == 200
        assert profile.json()["measurements"]["height"] == 175.0


class TestPhotoMeasureAuth:
    def test_missing_token_rejected(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = client.post(
            "/intake/photo-measure",
            data={"session_id": session_id, "height_cm": "170"},
            files={"photo": ("photo.jpg", JPEG, "image/jpeg")},
        )
        assert r.status_code == 401

    def test_malformed_token_rejected(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = client.post(
            "/intake/photo-measure",
            headers={"Authorization": "garbage"},
            data={"session_id": session_id, "height_cm": "170"},
            files={"photo": ("photo.jpg", JPEG, "image/jpeg")},
        )
        assert r.status_code == 401

    def test_cannot_measure_another_users_session(self, client):
        """Biometric data must not be attachable to someone else's session."""
        owner = register_and_login(client)
        session_id = consented_session(client, owner)

        attacker = register_and_login(client)
        r = scan(client, attacker["token"], session_id)

        assert r.status_code == 403


class TestPhotoMeasureConsent:
    def test_rejected_without_photo_consent(self, client):
        """
        Photo consent was previously collected but never enforced anywhere.
        A body photo must not be processed without it.
        """
        account = register_and_login(client)
        headers = auth_headers(account["token"])
        session_id = client.post("/intake/session", headers=headers).json()["session_id"]
        # Deliberately never record consent for this account.

        r = scan(client, account["token"], session_id)

        assert r.status_code == 403
        assert "consent" in r.json()["detail"].lower()


class TestPhotoMeasureUploadValidation:
    def test_rejects_text_file_renamed_as_jpeg(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = scan(client, account["token"], session_id,
                 image=b"I am definitely not an image")

        assert r.status_code == 400
        assert "image" in r.json()["detail"].lower()

    def test_rejects_disallowed_content_type(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = scan(client, account["token"], session_id,
                 image=b"%PDF-1.4 ...", filename="doc.pdf",
                 content_type="application/pdf")

        assert r.status_code == 400

    def test_rejects_oversized_upload_with_413(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        oversized = JPEG + b"\x00" * (MAX_IMAGE_BYTES + 1)
        r = scan(client, account["token"], session_id, image=oversized)

        assert r.status_code == 413

    def test_rejects_empty_upload(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = scan(client, account["token"], session_id, image=b"")

        assert r.status_code == 400

    def test_unknown_session_rejected(self, client):
        account = register_and_login(client)
        r = scan(client, account["token"], "no-such-session-id")
        assert r.status_code == 400

    def test_missing_height_rejected(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = client.post(
            "/intake/photo-measure",
            headers=auth_headers(account["token"]),
            data={"session_id": session_id},
            files={"photo": ("photo.jpg", JPEG, "image/jpeg")},
        )
        assert r.status_code == 422  # pydantic/form validation

    def test_missing_photo_rejected(self, client):
        account = register_and_login(client)
        session_id = consented_session(client, account)

        r = client.post(
            "/intake/photo-measure",
            headers=auth_headers(account["token"]),
            data={"session_id": session_id, "height_cm": "170"},
        )
        assert r.status_code == 422


class TestPhotoIsNotRetained:
    def test_image_is_not_recorded_on_the_session(self, client):
        """
        The privacy promise the UI makes: only the numbers persist. Verified
        against the real HTTP path, not just the orchestrator unit test.
        """
        account = register_and_login(client)
        session_id = consented_session(client, account)

        scan(client, account["token"], session_id, height_cm=170.0)

        # /intake/resume exposes the stored session; nothing image-shaped
        # should be recoverable from it.
        resumed = client.post("/intake/resume", json={"user_id": account["user_id"]})
        body = str(resumed.json())
        assert "\\xff\\xd8" not in body
        assert "photo_refs" not in body or "s3://" not in body
