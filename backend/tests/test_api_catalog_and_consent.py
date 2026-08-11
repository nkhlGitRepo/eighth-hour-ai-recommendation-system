"""
API-level tests for main.py's catalog and consent endpoints:
/profile, /retrieve, /catalog/sync, /catalog/stats, /consent, /consent/{user_id}.
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
    return f"api-catalog-{uuid.uuid4().hex[:8]}"


class TestCatalogStats:
    def test_returns_real_catalog_stats(self, client):
        r = client.get("/catalog/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["total_items"] > 0
        assert "categories" in body and isinstance(body["categories"], list)
        assert "colors" in body and isinstance(body["colors"], list)


class TestCatalogSync:
    def test_sync_replaces_catalog(self, client):
        products = [{
            "slug": "sync-test-item",
            "name": "Sync Test Item",
            "category": "Tops",
            "fabric": "Cotton",
            "price": 50.0,
            "colors": ["Ebony"],
            "sizes": ["M"],
        }]
        r = client.post("/catalog/sync", json=products)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "synced"
        assert body["item_count"] == 1
        assert body["stats"]["total_items"] == 1

        stats = client.get("/catalog/stats").json()
        assert stats["total_items"] == 1

    def test_sync_rejects_missing_required_field(self, client):
        # 'price' omitted -- pydantic should reject at the request-validation layer
        bad_products = [{
            "slug": "bad-item",
            "name": "Bad Item",
            "category": "Tops",
            "fabric": "Cotton",
        }]
        r = client.post("/catalog/sync", json=bad_products)
        assert r.status_code == 422

    def test_sync_does_not_carry_silhouette_or_launched_at(self, client):
        """
        CatalogProduct (the pydantic model this endpoint accepts) has no
        'silhouette' or 'launched_at' fields at all. A product synced
        through this endpoint can never be a real New Releases candidate
        (no launched_at means _is_recent() always returns False) and its
        silhouette always falls back to name-keyword inference rather than
        an explicit, authoritative value. Documenting this as a known API
        surface gap, not fixing it here (products.json + startup load is
        the actual path the live site uses; this endpoint is unused by the
        current frontend).
        """
        products = [{
            "slug": "sync-no-metadata",
            "name": "Sync No Metadata Item",
            "category": "Dresses",
            "fabric": "Silk",
            "price": 100.0,
            "colors": ["Ebony"],
            "sizes": ["M"],
        }]
        client.post("/catalog/sync", json=products)

        r = client.post("/retrieve", json={"shape_class": "balanced", "k": 10})
        item = next(p for p in r.json() if p["sku"] == "sync-no-metadata")
        assert item["launched_at"] is None

    def test_sync_empty_list_clears_catalog(self, client):
        r = client.post("/catalog/sync", json=[])
        assert r.status_code == 200
        assert r.json()["item_count"] == 0

        stats = client.get("/catalog/stats").json()
        assert stats["total_items"] == 0

    @pytest.fixture(autouse=True)
    def _restore_real_catalog(self, client):
        """These tests mutate the shared process-global catalog via /catalog/sync.
        Restore the real products.json afterward so later test files (which
        assume the real catalog is loaded) aren't affected."""
        yield
        import json
        import os
        products_file = os.path.join(os.path.dirname(__file__), "..", "products.json")
        with open(products_file) as f:
            products = json.load(f)
        client.post("/catalog/sync", json=products)


class TestRetrieve:
    """POST /retrieve -- direct catalog access, bypassing the intake flow entirely."""

    def test_retrieve_with_shape_class_only(self, client):
        r = client.post("/retrieve", json={"shape_class": "pear", "k": 5})
        assert r.status_code == 200
        results = r.json()
        assert isinstance(results, list)
        assert len(results) <= 5

    def test_retrieve_with_no_body_uses_defaults(self, client):
        r = client.post("/retrieve", json={})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_retrieve_filters_by_category(self, client):
        r = client.post("/retrieve", json={"categories": ["Vests"], "k": 50})
        assert r.status_code == 200
        results = r.json()
        assert len(results) > 0
        assert all(item["category"] == "Vests" for item in results)

    def test_retrieve_filters_by_color(self, client):
        r = client.post("/retrieve", json={"preferred_colors": ["Ebony"], "k": 50})
        assert r.status_code == 200
        results = r.json()
        assert len(results) > 0
        assert all("Ebony" in item["colors"] for item in results)

    def test_retrieve_respects_k(self, client):
        r = client.post("/retrieve", json={"k": 2})
        assert len(r.json()) <= 2

    def test_retrieve_does_not_require_consent(self, client):
        """This endpoint bypasses the session/consent system entirely by design."""
        r = client.post("/retrieve", json={"shape_class": "hourglass"})
        assert r.status_code == 200


class TestProfile:
    """POST /profile -- standalone profiling, bypassing the intake session entirely."""

    def test_profile_from_measurements(self, client):
        r = client.post("/profile", json={
            "bust": 91, "waist": 76, "hips": 95, "height": 165,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["shape_class"] in ["pear", "apple", "hourglass", "straight", "athletic", "balanced"]
        assert "ratios" in body
        assert "size_recommendation_by_category" in body

    def test_profile_does_not_require_consent(self, client):
        """No user_id is passed at all, so M3's consent check is skipped entirely."""
        r = client.post("/profile", json={
            "bust": 88, "waist": 70, "hips": 100, "height": 165,
        })
        assert r.status_code == 200

    def test_profile_rejects_invalid_measurements(self, client):
        r = client.post("/profile", json={
            "bust": 9999, "waist": 70, "hips": 100, "height": 165,
        })
        assert r.status_code == 400

    def test_profile_rejects_missing_field(self, client):
        r = client.post("/profile", json={"bust": 88, "waist": 70, "hips": 100})
        assert r.status_code == 422

    def test_profile_size_matches_shared_boundaries(self, client):
        """
        Regression guard: this standalone endpoint must use the same
        SIZE_BOUNDARIES-derived chart as the intake flow, not a
        third, independently-drifted formula.
        """
        r = client.post("/profile", json={
            "bust": 91, "waist": 76, "hips": 95, "height": 165,
        })
        assert r.json()["size_recommendation_by_category"]["tops"] == "S"


class TestConsentEndpoints:
    def test_record_and_retrieve_consent(self, client):
        user_id = unique_user()
        r = client.post("/consent", json={
            "user_id": user_id, "photo_consent": True, "measurement_consent": True,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["user_id"] == user_id
        assert body["has_any_consent"] is True
        assert body["photo_consent"] is True
        assert body["measurement_consent"] is True

        get_r = client.get(f"/consent/{user_id}")
        assert get_r.status_code == 200
        assert get_r.json()["measurement_consent"] is True

    def test_unknown_user_has_no_consent(self, client):
        user_id = unique_user()
        r = client.get(f"/consent/{user_id}")
        assert r.status_code == 200
        assert r.json()["has_any_consent"] is False

    def test_consent_can_be_updated_to_withdraw(self, client):
        user_id = unique_user()
        client.post("/consent", json={
            "user_id": user_id, "photo_consent": True, "measurement_consent": True,
        })
        r = client.post("/consent", json={
            "user_id": user_id, "photo_consent": False, "measurement_consent": False,
        })
        assert r.status_code == 200
        assert r.json()["has_any_consent"] is False

        # Latest record wins -- previously-granted consent must not linger.
        get_r = client.get(f"/consent/{user_id}")
        assert get_r.json()["measurement_consent"] is False

    def test_consent_survives_across_requests(self, client):
        """Consent recorded via POST /consent must be visible to endpoints
        that gate on ConsentTracker.has_measurement_consent (e.g. /intake/confirm)."""
        user_id = unique_user()
        client.post("/consent", json={
            "user_id": user_id, "photo_consent": True, "measurement_consent": True,
        })

        session_id = client.post("/intake/session", params={"user_id": user_id}).json()["session_id"]
        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        r = client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 91, "waist": 76, "hips": 95, "height": 165},
        })
        assert r.status_code == 200
