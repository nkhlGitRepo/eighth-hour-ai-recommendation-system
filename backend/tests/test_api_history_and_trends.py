"""
API-level tests for main.py's history/trend endpoints:
/history/{user_id}, /history/session/{session_id}, /history/product/{product_sku},
/trends/{user_id}.
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
    return f"api-hist-{uuid.uuid4().hex[:8]}"


def complete_intake_and_check_fit(client, user_id, sku=None):
    """Full intake + one fit-check, returning (session_id, real_user_id, sku, check_id)."""
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
        "session_id": session_id, "preferred_colors": ["Ebony"],
        "preferred_silhouettes": ["fitted"], "occasions": ["work"],
    })
    if sku is None:
        recs = client.get(
            f"/recommendations/{session_id}", params={"k": 1, "user_id": real_user_id}
        ).json()
        sku = recs["recommendations"][0]["sku"]
    fc = client.post(f"/fit-check/{session_id}/{sku}")
    check_id = fc.json()["check_id"]
    return session_id, real_user_id, sku, check_id


class TestUserHistory:
    def test_returns_own_fit_check_history(self, client):
        user_id = unique_user()
        _, real_user_id, sku, check_id = complete_intake_and_check_fit(client, user_id)

        r = client.get(f"/history/{real_user_id}")
        assert r.status_code == 200
        records = r.json()
        assert len(records) == 1
        assert records[0]["check_id"] == check_id
        assert records[0]["product_sku"] == sku

    def test_scoped_to_the_requested_user_only(self, client):
        """A user's history must never include another user's checks."""
        user_a = unique_user()
        _, real_a, _, _ = complete_intake_and_check_fit(client, user_a)
        user_b = unique_user()
        _, real_b, _, _ = complete_intake_and_check_fit(client, user_b)

        history_a = client.get(f"/history/{real_a}").json()
        assert all(rec["user_id"] == real_a for rec in history_a)

    def test_respects_limit(self, client):
        user_id = unique_user()
        session_id, real_user_id, _, _ = complete_intake_and_check_fit(client, user_id)

        # Fit-check a second product to have >1 record.
        recs = client.get(
            f"/recommendations/{session_id}", params={"k": 2, "user_id": real_user_id}
        ).json()["recommendations"]
        if len(recs) > 1:
            client.post(f"/fit-check/{session_id}/{recs[1]['sku']}")

        r = client.get(f"/history/{real_user_id}", params={"limit": 1})
        assert len(r.json()) <= 1

    def test_invalid_limit_rejected(self, client):
        user_id = unique_user()
        client.post("/consent", json={
            "user_id": user_id, "photo_consent": True, "measurement_consent": True,
        })

        r = client.get(f"/history/{user_id}", params={"limit": 0})
        assert r.status_code == 400

        r2 = client.get(f"/history/{user_id}", params={"limit": 101})
        assert r2.status_code == 400

    def test_user_with_no_history_returns_empty_list(self, client):
        user_id = unique_user()
        client.post("/consent", json={
            "user_id": user_id, "photo_consent": True, "measurement_consent": True,
        })

        r = client.get(f"/history/{user_id}")
        assert r.status_code == 200
        assert r.json() == []

    def test_without_consent_rejected(self, client):
        user_id = unique_user()  # never consented
        r = client.get(f"/history/{user_id}")
        assert r.status_code == 403


class TestSessionChecks:
    def test_returns_checks_for_owning_user(self, client):
        session_id, real_user_id, sku, check_id = complete_intake_and_check_fit(client, unique_user())

        r = client.get(f"/history/session/{session_id}", params={"user_id": real_user_id})
        assert r.status_code == 200
        records = r.json()
        assert len(records) == 1
        assert records[0]["check_id"] == check_id

    def test_non_owner_cannot_read_session_history(self, client):
        """Regression coverage for the cross-user data leak fix."""
        session_id, real_owner, _, _ = complete_intake_and_check_fit(client, unique_user())
        attacker_id = unique_user()
        # Attacker needs their own consent on file to get past the consent gate.
        client.post("/consent", json={
            "user_id": attacker_id, "photo_consent": True, "measurement_consent": True,
        })

        r = client.get(f"/history/session/{session_id}", params={"user_id": attacker_id})
        assert r.status_code == 403

    def test_requester_without_consent_is_rejected(self, client):
        session_id, real_owner, _, _ = complete_intake_and_check_fit(client, unique_user())

        r = client.get(f"/history/session/{session_id}", params={"user_id": "no-consent-user"})
        assert r.status_code == 403

    def test_nonexistent_session_returns_empty_list_not_a_leak(self, client):
        """A session_id with no matching intake_sessions row (and thus no
        real owner to check) should just return no records, not error."""
        user_id = unique_user()
        client.post("/consent", json={
            "user_id": user_id, "photo_consent": True, "measurement_consent": True,
        })
        r = client.get("/history/session/totally-made-up-session-id", params={"user_id": user_id})
        assert r.status_code == 200
        assert r.json() == []


class TestProductTrend:
    def test_returns_trend_for_own_checks(self, client):
        session_id, real_user_id, sku, _ = complete_intake_and_check_fit(client, unique_user())

        r = client.get(f"/history/product/{sku}", params={"user_id": real_user_id})
        assert r.status_code == 200
        records = r.json()
        assert len(records) == 1
        assert records[0]["product_sku"] == sku

    def test_scoped_to_requesting_user_naturally(self, client):
        """get_fit_check_trend filters by user_id at the query level already."""
        session_a, real_a, sku, _ = complete_intake_and_check_fit(client, unique_user())
        # A second user who never checked this product.
        other_user = unique_user()
        client.post("/consent", json={
            "user_id": other_user, "photo_consent": True, "measurement_consent": True,
        })

        r = client.get(f"/history/product/{sku}", params={"user_id": other_user})
        assert r.status_code == 200
        assert r.json() == []

    def test_respects_limit(self, client):
        session_id, real_user_id, sku, _ = complete_intake_and_check_fit(client, unique_user())
        r = client.get(f"/history/product/{sku}", params={"user_id": real_user_id, "limit": 0})
        assert r.status_code == 400


class TestUserTrends:
    def test_analyzes_trends_after_fit_checks(self, client):
        session_id, real_user_id, sku, _ = complete_intake_and_check_fit(client, unique_user())

        r = client.get(f"/trends/{real_user_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["total_checks"] == 1
        assert sku in dict(body["most_checked_products"])
        assert body["date_range"] is not None

    def test_user_with_no_checks_returns_empty_analysis(self, client):
        user_id = unique_user()
        client.post("/consent", json={
            "user_id": user_id, "photo_consent": True, "measurement_consent": True,
        })

        r = client.get(f"/trends/{user_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["total_checks"] == 0
        assert body["most_checked_products"] == []
        assert body["date_range"] is None

    def test_requires_consent(self, client):
        user_id = unique_user()  # never consented
        r = client.get(f"/trends/{user_id}")
        assert r.status_code == 403


class TestHistoryFitCheckCorrelation:
    """
    End-to-end: the check_id from /fit-check must be the SAME identifier
    that shows up consistently across /history/{user_id}, /history/session,
    and /history/product -- confirming the correlation fix holds across
    every read path, not just the one it was originally verified against.
    """

    def test_check_id_consistent_across_all_history_views(self, client):
        session_id, real_user_id, sku, check_id = complete_intake_and_check_fit(client, unique_user())

        by_user = client.get(f"/history/{real_user_id}").json()
        by_session = client.get(f"/history/session/{session_id}", params={"user_id": real_user_id}).json()
        by_product = client.get(f"/history/product/{sku}", params={"user_id": real_user_id}).json()

        assert {r["check_id"] for r in by_user} == {check_id}
        assert {r["check_id"] for r in by_session} == {check_id}
        assert {r["check_id"] for r in by_product} == {check_id}
