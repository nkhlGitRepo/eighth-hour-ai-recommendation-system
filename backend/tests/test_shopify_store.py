"""
The Shopify store integration (py_src/shopify + the /shopify/* endpoints).

The theme signs the signed-in customer in Liquid, sends the live product list
from the shopper's browser, and keeps an encrypted profile backup there. These
tests mint tokens exactly as the theme's Liquid does and send products shaped
like the store's /products.json, using the brand's first-drop launch data.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

import main
from main import app
from py_src.shopify import profile_token, theme_auth
from py_src.shopify.catalog import LaunchData, to_engine_product, to_engine_products
from py_src.shopify.rate_limit import ClientLimiter, RateLimited
from py_src.utils.errors import AuthError
from py_src.constants import STANDARD_SIZE_CHART

THEME_SECRET = "test-theme-secret"
SERVER_KEY = "test-server-key"
STORE = "eighth-hour-us"

LAUNCH = {
    "styles": [
        {"name": "Silk Band Collar Shirt", "category": "Tops",
         "skus": ["TS99-TOP-T901-SLK-BLK"], "silhouettes": ["Straight"],
         "occasions": ["Work", "Casual", "Evening", "Weekend"]},
        {"name": "Silk Tucked Yoke Dress", "category": "Dresses",
         "skus": ["TS99-DRS-D901-SLK-BRN", "TS99-DRS-D901-STN-BRN"], "silhouettes": ["Flowing", "A-Line"],
         "occasions": ["Work", "Evening", "Casual", "Weekend"]},
        {"name": "Silk Panel Wrap Dress", "category": "Dresses",
         "skus": ["TS99-DRS-D902-STN-BEI"], "silhouettes": ["Flowing", "A-Line"],
         "occasions": ["Work", "Evening", "Casual", "Weekend"]},
        {"name": "Silk Notch Collar Jacket", "category": "Jackets",
         "skus": ["TS99-JKT-J901-SLK-BRN"], "silhouettes": ["Fitted", "Straight"],
         "occasions": ["Work", "Evening", "Casual", "Weekend"]},
        {"name": "Silk Pleated Midi Skirt", "category": "Skirts",
         "skus": ["TS99-SKR-S901-SLK-BLK"], "silhouettes": ["Flowing", "Straight"],
         "occasions": ["Work", "Evening", "Casual", "Weekend"]},
    ],
    "colors": [
        {"name": "Ink Black", "hex": "#272727"}, {"name": "Bark Brown", "hex": "#493B39"},
        {"name": "Chalk White", "hex": "#E2E2DA"}, {"name": "Fawn", "hex": "#BDAB9B"},
    ],
}


def shopify_product(handle, title, colors_skus, sizes=("XS", "S", "M", "L"), unavailable=(),
                    body="", tags=(), published="2026-10-20T10:00:00-05:00"):
    """A product as the store's /products.json returns it."""
    return {
        "handle": handle, "title": title, "tags": list(tags), "body_html": body,
        "published_at": published,
        "options": [{"name": "Color", "values": [c for c, _ in colors_skus]},
                    {"name": "Size", "values": list(sizes)}],
        "variants": [
            {"sku": sku, "option1": color, "option2": size,
             "available": (color, size) not in unavailable}
            for color, sku in colors_skus for size in sizes
        ],
    }


PRODUCTS = [
    shopify_product("silk-band-collar-shirt", "Silk Band Collar Shirt",
                    [("Ink Black", "TS99-TOP-T901-SLK-BLK")], body="<p>A tailored silk shirt. Relaxed fit.</p>"),
    shopify_product("silk-tucked-yoke-dress", "Silk Tucked Yoke Dress",
                    [("Bark brown", "TS99-DRS-D901-SLK-BRN")],
                    body="Model: Ana is 5.6 ft and wears a size XS.", tags=["Calf"]),
    shopify_product("silk-panel-wrap-dress", "Silk Panel Wrap Dress",
                    [("Chalk White", "TS99-DRS-D902-STN-BEI"), ("Fawn", "TS99-DRS-D902-STN-BEI")],
                    unavailable={("Fawn", "L")}),
    shopify_product("silk-notch-collar-jacket", "Silk Notch Collar Jacket",
                    [("Bark brown", "TS99-JKT-J901-SLK-BRN")]),
    shopify_product("silk-pleated-midi-skirt", "Silk Pleated Midi Skirt",
                    [("Ink Black", "TS99-SKR-S901-SLK-BLK")]),
    # Retired Essentials: not first-drop pieces, so never used.
    shopify_product("silk-midi-dress", "Silk Midi Dress",
                    [("Slate Grey", "TS99-DRS-D903-SLK-GRY"), ("Deep Earth", "TS99-DRS-D901-STN-BRN")]),
    shopify_product("silk-cowl-neck-top-fawn", "Silk Cowl Neck Top", [("Fawn", "TS99-TOP-T903-SLK-BEI")]),
]


def token(customer_id="1001", issued_at=None, store=STORE, secret=THEME_SECRET):
    issued = str(int(time.time()) if issued_at is None else issued_at)
    return f"{store}.{customer_id}.{issued}.{theme_auth.sign(store, customer_id, issued, secret)}"


def headers(customer_id="1001"):
    return {theme_auth.HEADER: token(customer_id)}


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("MYSTYLE_THEME_SECRET", THEME_SECRET)
    monkeypatch.setenv("MYSTYLE_SERVER_KEY", SERVER_KEY)
    monkeypatch.setattr(main, "store_customer_limiter", ClientLimiter())


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def build_profile(client, customer_id, size="M", colors=("bark brown",)):
    h = headers(customer_id)
    session_id = client.post("/shopify/session", json={"photo_consent": True, "measurement_consent": True},
                             headers=h).json()["session_id"]
    body = {d: STANDARD_SIZE_CHART[size][d] for d in ("bust", "waist", "hips")}
    r = client.post("/shopify/measurements", json={"session_id": session_id, "height": 165, **body}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/shopify/preferences", headers=h, json={
        "session_id": session_id, "preferred_colors": list(colors),
        "preferred_silhouettes": ["a_line"], "occasions": ["work"],
        "products": PRODUCTS, "launch": LAUNCH,
    })
    assert r.status_code == 200, r.text
    return session_id, r.json()["profile"]


class TestCustomerToken:
    def test_a_token_minted_like_the_theme_verifies(self):
        assert theme_auth.verify_customer_token(token("42")) == (STORE, "42")

    @pytest.mark.parametrize("bad", [
        lambda: token("42", secret="wrong"),
        lambda: token("42", issued_at=int(time.time()) - theme_auth.TOKEN_MAX_AGE_S - 5),
        lambda: token("42", issued_at=int(time.time()) + theme_auth.FUTURE_SKEW_S + 60),
        lambda: token("42", store="some-other-store"),
        lambda: token("42")[:-1] + "0",
        lambda: "garbage",
        lambda: "",
    ])
    def test_forged_expired_or_malformed_tokens_are_refused(self, bad):
        with pytest.raises(AuthError):
            theme_auth.verify_customer_token(bad())

    def test_no_secret_means_the_integration_is_off(self, monkeypatch):
        monkeypatch.delenv("MYSTYLE_THEME_SECRET")
        with pytest.raises(AuthError):
            theme_auth.verify_customer_token(token("42"))

    def test_user_ids_are_stable_distinct_and_reveal_no_customer_id(self):
        a = theme_auth.user_id_for(STORE, "123456789")
        assert a == theme_auth.user_id_for(STORE, "123456789")
        assert a != theme_auth.user_id_for(STORE, "123456790")
        assert "123456789" not in a

    def test_user_ids_need_the_server_key(self, monkeypatch):
        monkeypatch.delenv("MYSTYLE_SERVER_KEY")
        with pytest.raises(AuthError):
            theme_auth.user_id_for(STORE, "1")


class TestProfileToken:
    MEASUREMENTS = {"bust": 99.7, "waist": 81.2, "hips": 105.3, "height": 165}
    PREFERENCES = {"preferred_colors": ["Bark Brown"], "preferred_silhouettes": ["a_line"], "occasions": ["work"]}

    def test_round_trip_for_its_own_customer(self):
        t = profile_token.issue(STORE, "7", self.MEASUREMENTS, self.PREFERENCES)
        payload = profile_token.read(t, STORE, "7")
        assert payload["measurements"] == self.MEASUREMENTS
        assert payload["preferences"]["colors"] == ["Bark Brown"]

    def test_measurements_cannot_be_read_out_of_it(self):
        t = profile_token.issue(STORE, "7", self.MEASUREMENTS, self.PREFERENCES)
        assert "99.7" not in t and "bust" not in t

    def test_another_customer_or_a_tampered_token_is_refused(self):
        t = profile_token.issue(STORE, "7", self.MEASUREMENTS, self.PREFERENCES)
        with pytest.raises(AuthError):
            profile_token.read(t, STORE, "8")
        with pytest.raises(AuthError):
            profile_token.read(t[:-4] + "AAAA", STORE, "7")

    def test_the_theme_secret_alone_cannot_open_it(self, monkeypatch):
        t = profile_token.issue(STORE, "7", self.MEASUREMENTS, self.PREFERENCES)
        monkeypatch.setenv("MYSTYLE_SERVER_KEY", THEME_SECRET)
        with pytest.raises(AuthError):
            profile_token.read(t, STORE, "7")


class TestCatalogMapping:
    def test_only_first_drop_pieces_are_used(self):
        handles = [p["slug"] for p in to_engine_products(PRODUCTS, LaunchData(LAUNCH))]
        assert handles == ["silk-band-collar-shirt", "silk-tucked-yoke-dress",
                           "silk-panel-wrap-dress", "silk-notch-collar-jacket",
                           "silk-pleated-midi-skirt"]

    def test_live_stock_colours_and_sizes_come_from_shopify(self):
        wrap = to_engine_product(PRODUCTS[2], LaunchData(LAUNCH))
        assert wrap["colors"] == ["Chalk White", "Fawn"]      # one SKU, two colours
        assert wrap["sizes"] == ["XS", "S", "M", "L"]
        assert wrap["sizes_in_stock"]["L"] is True               # Chalk White L still in stock
        assert wrap["category"] == "Dresses"

    def test_store_colours_take_the_brand_spelling(self):
        """The store says "Bark brown" where the brand's colour list says
        "Bark Brown"; customers see the brand's."""
        assert to_engine_product(PRODUCTS[1], LaunchData(LAUNCH))["colors"] == ["Bark Brown"]

    def test_brand_style_tags_become_quiz_values(self):
        yoke = to_engine_product(PRODUCTS[1], LaunchData(LAUNCH))
        assert yoke["silhouettes"] == ["flowing", "a_line"]
        assert yoke["occasions"] == ["work", "evening", "casual", "weekend"]
        assert yoke["length"] == "Calf"
        assert (yoke["model_name"], yoke["model_size"]) == ("Ana", "XS")

    def test_fit_is_read_from_the_description(self):
        assert to_engine_product(PRODUCTS[0], LaunchData(LAUNCH))["fit"] == "Relaxed"

    def test_a_sold_out_size_is_out_of_stock(self):
        product = shopify_product("p", "P", [("Ink Black", "TS99-TOP-T901-SLK-BLK")], unavailable={("Ink Black", "S")})
        assert to_engine_product(product, LaunchData(LAUNCH))["sizes_in_stock"]["S"] is False

    def test_malformed_input_is_ignored_not_fatal(self):
        assert to_engine_products([None, {}, {"handle": "Bad Handle!"}, "x"], LaunchData(LAUNCH)) == []
        assert LaunchData({"styles": [{"category": "Hats", "skus": ["X"]}]}).styles == []


class TestStoreEndpoints:
    ENDPOINTS = [
        ("post", "/shopify/session", {"photo_consent": True, "measurement_consent": True}),
        ("get", "/shopify/profile", None),
        ("post", "/shopify/recommendations", {"session_id": "x"}),
        ("post", "/shopify/fit-check", {"session_id": "x", "product": {}}),
        ("delete", "/shopify/profile", None),
    ]

    @pytest.mark.parametrize("method, path, body", ENDPOINTS)
    def test_guests_are_refused(self, client, method, path, body):
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(path, **kwargs).status_code == 401

    def test_full_journey(self, client):
        session_id, profile = build_profile(client, "2001")
        assert profile["shape_profile"]["size_recommendation_by_category"]["tops"] == "M"
        assert profile["style_profile"]["preferred_colors"] == ["Bark Brown"]   # brand spelling
        assert "user_id" not in profile["style_profile"]
        assert profile["profile_token"]

        h = headers("2001")
        recs = client.post("/shopify/recommendations", headers=h, json={
            "session_id": session_id, "products": PRODUCTS, "launch": LAUNCH}).json()["recommendations"]
        assert recs and {r["handle"] for r in recs} <= {p["slug"] for p in to_engine_products(PRODUCTS, LaunchData(LAUNCH))}
        assert all(r["recommended_size"] == "M" and not r["closest_available"] for r in recs)

        fit = client.post("/shopify/fit-check", headers=h, json={
            "session_id": session_id, "product": PRODUCTS[3], "launch": LAUNCH}).json()
        assert fit["recommended_size"] == "M" and fit["check_id"] and fit["in_stock_in_size"] is True

        feedback = client.post("/shopify/feedback", headers=h, json={
            "fit_check_id": fit["check_id"], "product_handle": "silk-notch-collar-jacket",
            "feedback_type": "perfect"})
        assert feedback.status_code == 200, feedback.text

        items = client.post("/shopify/new-releases", headers=h, json={
            "session_id": session_id, "products": PRODUCTS, "launch": LAUNCH}).json()["items"]
        assert items and items[0]["reason"] and items[0]["in_stock_in_size"] is True

        loaded = client.get("/shopify/profile", headers=h).json()["profile"]
        assert loaded["session_id"] == session_id
        assert loaded["profile_token"]      # any browser she signs in on keeps a backup

    def test_measurements_are_never_sent_back(self, client):
        session_id, profile = build_profile(client, "2002", size="L")
        bust = str(STANDARD_SIZE_CHART["L"]["bust"])
        later = client.get("/shopify/profile", headers=headers("2002")).json()
        for payload in (profile, later):
            text = json.dumps(payload)
            assert "measurements" not in text and bust not in text

    def test_outside_a_pieces_sizes_she_gets_the_closest(self, client):
        session_id, _ = build_profile(client, "2003", size="XXS")
        fit = client.post("/shopify/fit-check", headers=headers("2003"), json={
            "session_id": session_id, "product": PRODUCTS[0], "launch": LAUNCH}).json()
        assert fit["recommended_size"] == "XS" and fit["closest_available"] is True
        assert fit["fit_notes"][0].startswith("Your size is XXS.")

    def test_a_piece_outside_the_first_drop_has_no_size_advice(self, client):
        session_id, _ = build_profile(client, "2004")
        r = client.post("/shopify/fit-check", headers=headers("2004"), json={
            "session_id": session_id, "product": PRODUCTS[6], "launch": LAUNCH})
        assert r.status_code == 404

    def test_another_customers_session_is_not_found(self, client):
        session_id, _ = build_profile(client, "2005")
        r = client.post("/shopify/recommendations", headers=headers("2006"), json={
            "session_id": session_id, "products": PRODUCTS, "launch": LAUNCH})
        assert r.status_code == 404

    def test_unknown_colours_are_rejected(self, client):
        h = headers("2007")
        session_id = client.post("/shopify/session", json={"photo_consent": True, "measurement_consent": True},
                                 headers=h).json()["session_id"]
        client.post("/shopify/measurements", headers=h, json={
            "session_id": session_id, "bust": 95, "waist": 76, "hips": 100, "height": 165})
        r = client.post("/shopify/preferences", headers=h, json={
            "session_id": session_id, "preferred_colors": ["Neon Pink"], "products": PRODUCTS, "launch": LAUNCH})
        assert r.status_code == 400

    def test_consent_is_required(self, client):
        r = client.post("/shopify/session", json={"photo_consent": False, "measurement_consent": True},
                        headers=headers("2008"))
        assert r.status_code == 400

    def test_restore_after_the_database_is_lost(self, client):
        _, profile = build_profile(client, "2009", size="S")
        main.session_repo.delete_user_data(theme_auth.user_id_for(STORE, "2009"))   # the wipe
        h = headers("2009")
        assert client.get("/shopify/profile", headers=h).json()["profile"] is None
        r = client.post("/shopify/restore", headers=h, json={"profile_token": profile["profile_token"]})
        assert r.status_code == 200 and r.json()["restored"] is True
        restored = r.json()["profile"]
        assert restored["shape_profile"]["size_recommendation_by_category"]["tops"] == "S"
        assert restored["style_profile"]["preferred_colors"] == ["Bark Brown"]

    def test_restore_refuses_someone_elses_backup(self, client):
        _, profile = build_profile(client, "2010")
        r = client.post("/shopify/restore", headers=headers("2011"), json={"profile_token": profile["profile_token"]})
        assert r.status_code == 401

    def test_delete_my_profile_removes_everything(self, client):
        build_profile(client, "2012")
        h = headers("2012")
        assert client.delete("/shopify/profile", headers=h).json() == {"deleted": True}
        assert client.get("/shopify/profile", headers=h).json()["profile"] is None

    def test_owner_deletion_needs_the_admin_token(self, client):
        build_profile(client, "2013")
        body = {"store": STORE, "customer_id": "2013"}
        assert client.post("/shopify/admin/delete-customer", json=body,
                           headers={"X-MyStyle-Admin": "guess"}).status_code == 401
        r = client.post("/shopify/admin/delete-customer", json=body,
                        headers={"X-MyStyle-Admin": theme_auth.admin_token()})
        assert r.status_code == 200 and r.json()["removed"]["intake_sessions"] >= 1
        assert client.get("/shopify/profile", headers=headers("2013")).json()["profile"] is None

    def test_one_client_acting_as_many_customers_is_stopped(self, client):
        statuses = [client.get("/shopify/profile", headers=headers(str(3000 + i))).status_code
                    for i in range(main.store_customer_limiter.customers_per_hour + 3)]
        assert statuses.count(200) == main.store_customer_limiter.customers_per_hour
        assert statuses[-1] == 429

    def test_the_store_is_an_allowed_browser_origin(self, client):
        r = client.options("/shopify/profile", headers={
            "Origin": "https://www.eighth-hour.com", "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": theme_auth.HEADER})
        assert r.headers.get("access-control-allow-origin") == "https://www.eighth-hour.com"


class TestClientLimiter:
    def test_request_rate(self):
        limiter = ClientLimiter(requests_per_minute=3, customers_per_hour=10)
        for _ in range(3):
            limiter.check("ip", "a", now=100)
        with pytest.raises(RateLimited):
            limiter.check("ip", "a", now=101)
        limiter.check("ip", "a", now=170)          # a minute later it clears

    def test_customers_per_hour(self):
        limiter = ClientLimiter(requests_per_minute=100, customers_per_hour=2)
        limiter.check("ip", "a", now=0)
        limiter.check("ip", "b", now=1)
        limiter.check("ip", "a", now=2)            # a known customer is fine
        with pytest.raises(RateLimited):
            limiter.check("ip", "c", now=3)
        limiter.check("other-ip", "c", now=3)      # limits are per client
        limiter.check("ip", "c", now=3700)         # an hour later it clears
