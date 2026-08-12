"""
API-level tests for main.py's /recommendations/{session_id} and
/new-releases/{session_id} endpoints.
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
    return f"api-recs-{uuid.uuid4().hex[:8]}"


def complete_intake(client, user_id, colors=None, silhouettes=None, occasions=None):
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
        "preferred_colors": colors or ["Ebony"],
        "preferred_silhouettes": silhouettes or ["fitted"],
        "occasions": occasions or ["work"],
    })
    return session_id, real_user_id


class TestRecommendationsEndpoint:
    def test_returns_recommendations_for_completed_session(self, client):
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id)

        r = client.get(f"/recommendations/{session_id}", params={"k": 5, "user_id": real_user_id})
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == session_id
        assert isinstance(body["recommendations"], list)

    def test_rejects_incomplete_session(self, client):
        user_id = unique_user()
        session_id = client.post("/intake/session", params={"user_id": user_id}).json()["session_id"]

        r = client.get(f"/recommendations/{session_id}")
        assert r.status_code == 400

    def test_rejects_unknown_session(self, client):
        r = client.get("/recommendations/nonexistent-session-id")
        assert r.status_code in (400, 500)  # get_session raises ModuleError -> 400

    def test_respects_k(self, client):
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id)

        r = client.get(f"/recommendations/{session_id}", params={"k": 2, "user_id": real_user_id})
        assert len(r.json()["recommendations"]) <= 2

    def test_category_filter(self, client):
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id)

        r = client.get(f"/recommendations/{session_id}", params={
            "k": 20, "user_id": real_user_id, "category_filter": ["Vests"],
        })
        assert r.status_code == 200
        recs = r.json()["recommendations"]
        assert all(item["category"] == "Vests" for item in recs)

    def test_color_preference_is_honored(self, client):
        """Regression coverage: recommendations must actually reflect stated color preference."""
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id, colors=["Ebony"])

        r = client.get(f"/recommendations/{session_id}", params={"k": 20, "user_id": real_user_id})
        recs = r.json()["recommendations"]
        assert len(recs) > 0
        assert all("Ebony" in item["colors"] for item in recs)

    def test_multiword_color_preference_is_honored(self, client):
        """Regression coverage for the str.capitalize() color-matching bug."""
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id, colors=["Pageant Blue"])

        r = client.get(f"/recommendations/{session_id}", params={"k": 20, "user_id": real_user_id})
        recs = r.json()["recommendations"]
        assert len(recs) > 0
        assert all("Pageant Blue" in item["colors"] for item in recs)

    def test_silhouette_preference_changes_results(self, client):
        """Regression coverage: silhouette preference must not be a no-op."""
        user_a = unique_user()
        session_fitted, real_a = complete_intake(client, user_a, silhouettes=["fitted"])
        recs_fitted = client.get(
            f"/recommendations/{session_fitted}", params={"k": 20, "user_id": real_a}
        ).json()["recommendations"]

        user_b = unique_user()
        session_flowing, real_b = complete_intake(client, user_b, silhouettes=["flowing"])
        recs_flowing = client.get(
            f"/recommendations/{session_flowing}", params={"k": 20, "user_id": real_b}
        ).json()["recommendations"]

        fitted_skus = {item["sku"] for item in recs_fitted}
        flowing_skus = {item["sku"] for item in recs_flowing}
        assert fitted_skus != flowing_skus

    def test_occasion_preference_changes_results(self, client):
        """
        Regression coverage: occasion preference must not be a no-op.

        Uses a broad color list (rather than the single-color default) so
        both "work" and "evening" independently have well over
        MIN_RECOMMENDATIONS matches -- otherwise filter relaxation (a
        separate, intentional feature -- see TestFilterRelaxation-style
        coverage) could drop the narrower occasion and mask the very
        difference this test exists to catch.
        """
        broad_colors = ["Ebony", "Pageant Blue", "Sky Captain", "Chocolate Truffle", "Pure Cashmere"]

        user_a = unique_user()
        session_work, real_a = complete_intake(client, user_a, colors=broad_colors, occasions=["work"])
        recs_work = client.get(
            f"/recommendations/{session_work}", params={"k": 20, "user_id": real_a}
        ).json()["recommendations"]

        user_b = unique_user()
        session_evening, real_b = complete_intake(client, user_b, colors=broad_colors, occasions=["evening"])
        recs_evening = client.get(
            f"/recommendations/{session_evening}", params={"k": 20, "user_id": real_b}
        ).json()["recommendations"]

        work_skus = {item["sku"] for item in recs_work}
        evening_skus = {item["sku"] for item in recs_evening}
        assert work_skus != evening_skus

    def test_non_owner_user_id_is_rejected(self, client):
        """Regression coverage for the session-ownership fix."""
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id)

        r = client.get(f"/recommendations/{session_id}", params={"user_id": "someone-else-entirely"})
        assert r.status_code == 403

    def test_omitting_user_id_is_still_allowed(self, client):
        """Backward compatible: user_id remains optional."""
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id)

        r = client.get(f"/recommendations/{session_id}")
        assert r.status_code == 200


class TestNewReleasesEndpoint:
    def test_returns_feed_for_completed_session(self, client):
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id)

        r = client.get(f"/new-releases/{session_id}")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_rejects_incomplete_session(self, client):
        user_id = unique_user()
        session_id = client.post("/intake/session", params={"user_id": user_id}).json()["session_id"]

        r = client.get(f"/new-releases/{session_id}")
        assert r.status_code == 400

    def test_rejects_unknown_session(self, client):
        r = client.get("/new-releases/nonexistent-session-id")
        assert r.status_code in (400, 500)

    def test_respects_limit(self, client):
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id)

        r = client.get(f"/new-releases/{session_id}", params={"limit": 2})
        assert r.status_code == 200
        assert len(r.json()) <= 2

    def test_invalid_limit_rejected(self, client):
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id)

        r = client.get(f"/new-releases/{session_id}", params={"limit": 0})
        assert r.status_code == 400

        r2 = client.get(f"/new-releases/{session_id}", params={"limit": 101})
        assert r2.status_code == 400

    def test_only_recently_launched_products_appear(self, client):
        """
        Regression coverage: New Releases must only surface products
        launched within the recency window, not the whole catalog.
        """
        user_id = unique_user()
        session_id, real_user_id = complete_intake(client, user_id, colors=[], silhouettes=[], occasions=[])

        r = client.get(f"/new-releases/{session_id}", params={"limit": 50})
        assert r.status_code == 200
        feed = r.json()
        # The real catalog has exactly 6 products launched within the last
        # 30 days (see products.json) -- everything else is legacy stock.
        assert len(feed) <= 6
        for item in feed:
            assert "match_score" in item
            assert "reason" in item
