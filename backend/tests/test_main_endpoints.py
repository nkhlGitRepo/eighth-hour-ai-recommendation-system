"""
API-level integration tests for main.py's learning-loop endpoints
(fit-check -> feedback -> summary), using FastAPI's TestClient.

main.py previously had ZERO direct test coverage -- every other test file
constructs modules directly with hand-built inputs, bypassing the actual
endpoint wiring entirely. That gap is exactly why several real bugs only
ever surfaced through live manual testing rather than the "comprehensive"
unit suite: a GET/POST mismatch in the frontend widget, validate_measurements()
choking on a full to_dict() payload, and the check_id correlation gap this
file specifically guards against.

These tests exercise the real running app (same process-global catalog,
session store, and consent tracker main.py itself constructs) via
TestClient, so they share the on-disk intake_sessions.db with normal dev
use. Every test generates a fresh, unique user_id/session_id to avoid
collisions, and assertions are scoped to that test's own data rather than
absolute counts against shared tables.
"""

import uuid
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _complete_intake(client, user_id):
    """Run a full intake to a completed session, returning (session_id, real_user_id)."""
    s = client.post("/intake/session", params={"user_id": user_id}).json()
    session_id = s["session_id"]
    real_user_id = s["user_id"]

    client.post("/intake/consent", json={
        "session_id": session_id, "photo_consent": True, "measurement_consent": True,
    })
    client.post("/consent", json={
        "user_id": real_user_id, "photo_consent": True, "measurement_consent": True,
    })
    client.post("/intake/confirm", json={
        "session_id": session_id,
        "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
    })
    client.post("/intake/preferences", json={
        "session_id": session_id,
        "preferred_colors": ["Ebony"],
        "preferred_silhouettes": ["fitted"],
        "occasions": ["work"],
    })
    return session_id, real_user_id


class TestHealth:
    def test_health_check(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestFitCheckReturnsCorrelationId:
    """Regression coverage for the check_id gap: /fit-check must return the
    SAME check_id that gets saved to /history, not a synthetic placeholder."""

    def test_fit_check_response_includes_check_id(self, client):
        user_id = f"e2e-{uuid.uuid4().hex[:8]}"
        session_id, real_user_id = _complete_intake(client, user_id)

        recs = client.get(
            f"/recommendations/{session_id}", params={"k": 1, "user_id": real_user_id}
        ).json()
        sku = recs["recommendations"][0]["sku"]

        fc = client.post(f"/fit-check/{session_id}/{sku}")
        assert fc.status_code == 200
        body = fc.json()
        assert "check_id" in body
        assert body["check_id"] is not None
        assert isinstance(body["check_id"], str)

    def test_fit_check_id_matches_the_id_saved_to_history(self, client):
        """The check_id returned to the caller must be the actual primary key
        of the row saved to fit_check_history -- not a lookalike string."""
        user_id = f"e2e-{uuid.uuid4().hex[:8]}"
        session_id, real_user_id = _complete_intake(client, user_id)

        recs = client.get(
            f"/recommendations/{session_id}", params={"k": 1, "user_id": real_user_id}
        ).json()
        sku = recs["recommendations"][0]["sku"]

        fc = client.post(f"/fit-check/{session_id}/{sku}")
        returned_check_id = fc.json()["check_id"]

        history = client.get(f"/history/session/{session_id}", params={"user_id": real_user_id})
        assert history.status_code == 200
        history_check_ids = {row["check_id"] for row in history.json()}

        assert returned_check_id in history_check_ids


class TestLearningLoopEndToEnd:
    """The full loop: fit-check -> submit feedback referencing the real
    check_id -> feedback summary reflects it."""

    def test_full_feedback_loop(self, client):
        user_id = f"e2e-{uuid.uuid4().hex[:8]}"
        session_id, real_user_id = _complete_intake(client, user_id)

        recs = client.get(
            f"/recommendations/{session_id}", params={"k": 1, "user_id": real_user_id}
        ).json()
        sku = recs["recommendations"][0]["sku"]

        fc = client.post(f"/fit-check/{session_id}/{sku}")
        check_id = fc.json()["check_id"]

        fit_fb = client.post("/feedback/fit", json={
            "user_id": real_user_id,
            "fit_check_id": check_id,
            "product_sku": sku,
            "feedback_type": "perfect",
            "notes": "Fit as expected",
        })
        assert fit_fb.status_code == 200
        assert fit_fb.json()["saved"] is True
        assert fit_fb.json()["fit_check_id"] == check_id

        product_fb = client.post("/feedback/product", json={
            "user_id": real_user_id,
            "product_sku": sku,
            "feedback_type": "liked",
            "purchased": True,
            "rating": 4.5,
        })
        assert product_fb.status_code == 200
        assert product_fb.json()["saved"] is True

        summary = client.get(f"/feedback/summary/{real_user_id}")
        assert summary.status_code == 200
        body = summary.json()
        assert body["fit_feedback_stats"]["total"] == 1
        assert body["fit_feedback_stats"]["perfect"] == 1
        assert body["product_feedback_stats"]["liked"] == 1
        assert body["total_feedback_records"] == 2

    def test_feedback_rejected_without_consent(self, client):
        """A user_id that never went through intake has no consent on record."""
        user_id = f"no-consent-{uuid.uuid4().hex[:8]}"

        r = client.post("/feedback/fit", json={
            "user_id": user_id,
            "fit_check_id": "check-doesnt-matter",
            "product_sku": "some-sku",
            "feedback_type": "perfect",
        })
        assert r.status_code == 403

    def test_feedback_rejected_for_invalid_type(self, client):
        user_id = f"e2e-{uuid.uuid4().hex[:8]}"
        _, real_user_id = _complete_intake(client, user_id)

        r = client.post("/feedback/fit", json={
            "user_id": real_user_id,
            "fit_check_id": "check-1",
            "product_sku": "some-sku",
            "feedback_type": "not_a_real_type",
        })
        assert r.status_code == 400

    def test_summary_for_user_with_no_feedback(self, client):
        user_id = f"e2e-{uuid.uuid4().hex[:8]}"
        _, real_user_id = _complete_intake(client, user_id)

        summary = client.get(f"/feedback/summary/{real_user_id}")
        assert summary.status_code == 200
        body = summary.json()
        assert body["fit_feedback_stats"]["total"] == 0
        assert body["total_feedback_records"] == 0
