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


class TestFitCheckAgreesWithShapeProfile:
    """
    Regression coverage: /fit-check's recommended_size must always match
    the size already shown on the customer's Shape Profile
    (size_recommendation_by_category) for that product's category --
    otherwise a customer sees e.g. "S" for skirts on their profile, then
    "M" pre-selected (and called a "perfect fit") the moment they click
    into an actual skirt recommendation.
    """

    CATEGORY_TO_SIZE_PROFILE_KEY = {
        "Tops": "tops",
        "Dresses": "dresses",
        "Vests": "vests",
        "Skirts": "skirts",
        "Trousers": "trousers",
    }

    def test_fit_check_matches_shape_profile_across_recommended_categories(self, client):
        user_id = f"e2e-{uuid.uuid4().hex[:8]}"
        s = client.post("/intake/session", params={"user_id": user_id}).json()
        session_id, real_user_id = s["session_id"], s["user_id"]

        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/consent", json={
            "user_id": real_user_id, "photo_consent": True, "measurement_consent": True,
        })
        # bust=96 -> M3 classifies tops as "M"; hips=92 -> M3 classifies
        # skirts as "S" -- a body where the bust-driven and hips-driven
        # category sizes genuinely differ, which is exactly what exposes
        # the bug (a single bust+waist+hips-blended fit-check average
        # disagreeing with M3's single-measurement, category-specific size).
        confirm = client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 96, "waist": 84, "hips": 92, "height": 165},
        }).json()
        size_by_category = confirm["shape_profile"]["size_recommendation_by_category"]
        assert size_by_category["tops"] == "M"
        assert size_by_category["skirts"] == "S"

        client.post("/intake/preferences", json={
            "session_id": session_id,
            "preferred_colors": [],
            "preferred_silhouettes": [],
            "occasions": [],
        })

        recs = client.get(
            f"/recommendations/{session_id}", params={"k": 30, "user_id": real_user_id}
        ).json()["recommendations"]

        checked_categories = set()
        for rec in recs:
            size_key = self.CATEGORY_TO_SIZE_PROFILE_KEY.get(rec["category"])
            if not size_key or rec["category"] in checked_categories:
                continue
            expected_size = size_by_category[size_key]
            if expected_size not in rec["sizes"]:
                continue  # known_size only applies when the product stocks it

            fc = client.post(f"/fit-check/{session_id}/{rec['sku']}")
            assert fc.status_code == 200
            assert fc.json()["recommended_size"] == expected_size, (
                f"{rec['category']} product {rec['sku']} should recommend "
                f"{expected_size} (this session's shape profile size for "
                f"{size_key}), got {fc.json()['recommended_size']}"
            )
            checked_categories.add(rec["category"])

        # Sanity check: the test actually exercised at least one of the
        # bust-driven and one of the hips-driven categories, not zero.
        assert checked_categories & {"Tops", "Dresses", "Vests"}
        assert checked_categories & {"Skirts", "Trousers"}


class TestFitCheckCoordSetsSizedLikeATop:
    """
    API-level regression coverage: a Co-ord Set only has one size field
    for the customer to fill in, so /fit-check must return a single
    recommended_size for it -- sized like a Top (bust-driven), matching
    the "tops" value already shown on the customer's Shape Profile,
    rather than an unexplained blended compromise between the top and
    bottom halves' separate sizes.
    """

    def test_coord_set_fit_check_matches_the_tops_shape_profile_size(self, client):
        user_id = f"e2e-coord-{uuid.uuid4().hex[:8]}"
        s = client.post("/intake/session", params={"user_id": user_id}).json()
        session_id, real_user_id = s["session_id"], s["user_id"]

        client.post("/intake/consent", json={
            "session_id": session_id, "photo_consent": True, "measurement_consent": True,
        })
        client.post("/consent", json={
            "user_id": real_user_id, "photo_consent": True, "measurement_consent": True,
        })
        # bust -> XL, hips -> S: a genuinely mismatched body, where the old
        # equal blend used to land on an unrelated third size (e.g. "M").
        confirm = client.post("/intake/confirm", json={
            "session_id": session_id,
            "manual_overrides": {"bust": 111, "waist": 78, "hips": 90, "height": 165},
        }).json()
        size_by_category = confirm["shape_profile"]["size_recommendation_by_category"]
        assert size_by_category["tops"] == "XL"
        assert size_by_category["skirts"] == "S"

        client.post("/intake/preferences", json={
            "session_id": session_id,
            "preferred_colors": [],
            "preferred_silhouettes": [],
            "occasions": [],
        })

        recs = client.get(
            f"/recommendations/{session_id}", params={"k": 30, "user_id": real_user_id}
        ).json()["recommendations"]
        coord_product = next((r for r in recs if r["category"] == "Co-ord Sets"), None)
        assert coord_product is not None, "Test catalog should include at least one Co-ord Sets item"

        fc = client.post(f"/fit-check/{session_id}/{coord_product['sku']}")
        assert fc.status_code == 200
        body = fc.json()

        assert "top_size" not in body and "bottom_size" not in body
        assert body["recommended_size"] == "XL"
        assert body["fit_scores"][body["recommended_size"]] == max(body["fit_scores"].values())


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
