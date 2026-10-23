"""
The demo endpoints that take a user id act only for that user's own signed-in
account (main.require_own_account). They used to trust the id they were given,
so anyone could read or write another person's consent, history and feedback
by naming them. Plain TestClient here, headers spelled out, so nothing is
signed behind the test's back.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def account(client):
    name = f"access{uuid.uuid4().hex}"[:32]
    password = "TestPassw0rd!"
    client.post("/auth/register", json={"username": name, "email": f"{name}@example.test", "password": password})
    body = client.post("/auth/login", json={"username": name, "password": password}).json()
    return body["user_id"], {"Authorization": f"Bearer {body['token']}"}


def requests_for(user_id):
    """Every user-id endpoint, as (method, path, kwargs), acting for user_id."""
    return [
        ("get", f"/consent/{user_id}", {}),
        ("post", "/consent", {"json": {"user_id": user_id, "photo_consent": True, "measurement_consent": True}}),
        ("post", "/intake/resume", {"json": {"user_id": user_id}}),
        ("get", f"/history/{user_id}", {}),
        ("get", "/history/session/some-session", {"params": {"user_id": user_id}}),
        ("get", "/history/product/some-sku", {"params": {"user_id": user_id}}),
        ("get", f"/trends/{user_id}", {}),
        ("post", "/feedback/fit", {"json": {"user_id": user_id, "fit_check_id": "c", "product_sku": "s", "feedback_type": "perfect"}}),
        ("post", "/feedback/product", {"json": {"user_id": user_id, "product_sku": "s", "feedback_type": "liked"}}),
        ("get", f"/feedback/summary/{user_id}", {}),
        ("get", "/recommendations/some-session", {"params": {"user_id": user_id}}),
    ]


ENDPOINTS = [f"{m.upper()} {p.split('/')[1]}/{p.split('/')[2] if p.count('/') > 1 else ''}" for m, p, _ in requests_for("u")]


@pytest.mark.parametrize("index", range(len(ENDPOINTS)), ids=ENDPOINTS)
def test_signed_out_is_refused(client, index):
    victim, _ = account(client)
    method, path, kwargs = requests_for(victim)[index]
    assert getattr(client, method)(path, **kwargs).status_code == 401


@pytest.mark.parametrize("index", range(len(ENDPOINTS)), ids=ENDPOINTS)
def test_another_account_is_refused(client, index):
    victim, theirs = account(client)
    # With her consent on file, nothing but the ownership check stands in the way.
    client.post("/consent", headers=theirs, json={"user_id": victim, "photo_consent": True, "measurement_consent": True})
    _, intruder = account(client)
    method, path, kwargs = requests_for(victim)[index]
    response = getattr(client, method)(path, headers=intruder, **kwargs)
    assert response.status_code == 403
    assert response.json()["detail"] == "You can only see or change your own profile"


@pytest.mark.parametrize("index", range(len(ENDPOINTS)), ids=ENDPOINTS)
def test_own_account_gets_past_the_check(client, index):
    me, mine = account(client)
    method, path, kwargs = requests_for(me)[index]
    response = getattr(client, method)(path, headers=mine, **kwargs)
    # What happens next is each endpoint's own business (no consent yet, no
    # such session...), but it is never refused for who is asking.
    assert response.status_code != 401
    assert response.json().get("detail") != "You can only see or change your own profile"


def test_recommendations_without_a_user_id_still_need_no_sign_in(client):
    """The demo's homepage strip asks for a session's picks without naming
    anyone; that stays open (the session id itself is the key)."""
    assert client.get("/recommendations/no-such-session").status_code != 401
