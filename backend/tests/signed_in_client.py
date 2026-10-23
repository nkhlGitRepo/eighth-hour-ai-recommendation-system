"""
A TestClient that signs each request as the demo account it acts for.

The demo endpoints that take a user id only act for that user's own signed-in
account (main.require_own_account). Tests that drive them for several accounts
would otherwise thread a bearer token through every call; this remembers the
token each /auth/login returns and attaches it whenever a request names that
user -- in its JSON body, its query string or its path. A request that already
carries an Authorization header is left alone, and one naming nobody it knows
is sent unsigned, so tests can still check what a stranger or a guest gets.
"""

import uuid

from fastapi.testclient import TestClient


class SignedInClient(TestClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tokens = {}

    def new_account(self, prefix="acct"):
        """Register and sign in a fresh demo account; returns its user id."""
        name = f"{prefix}{uuid.uuid4().hex}"[:32]
        password = "TestPassw0rd!"
        self.post("/auth/register", json={"username": name, "email": f"{name}@example.test", "password": password})
        return self.post("/auth/login", json={"username": name, "password": password}).json()["user_id"]

    def _named_user(self, url, kwargs):
        for source in (kwargs.get("json"), kwargs.get("params")):
            if isinstance(source, dict) and source.get("user_id") in self.tokens:
                return source["user_id"]
        path = str(url).split("?")[0]
        query = str(url).split("?")[1] if "?" in str(url) else ""
        for part in path.split("/") + [kv.split("=", 1)[-1] for kv in query.split("&")]:
            if part in self.tokens:
                return part
        return None

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        if not any(name.lower() == "authorization" for name in headers):
            user = self._named_user(url, kwargs)
            if user:
                headers["Authorization"] = f"Bearer {self.tokens[user]}"
        response = super().request(method, url, headers=headers or None, **kwargs)
        if str(url).rstrip("/").endswith("/auth/login") and response.status_code == 200:
            body = response.json()
            self.tokens[body["user_id"]] = body["token"]
        return response
