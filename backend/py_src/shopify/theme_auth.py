"""
Who is signed in, for requests from the Shopify theme.

A theme has no Shopify session the API could check, so the theme vouches for
the customer itself. Its Liquid -- which runs on Shopify's servers, never in the
browser -- renders

    {store}.{customer_id}.{issued_at}.{signature}

where signature = hex HMAC-SHA256(MYSTYLE_THEME_SECRET,
"{store}:{customer_id}:{issued_at}"), exactly what Liquid's hmac_sha256 filter
produces. The browser sends it back in the X-MyStyle-Customer header and this
module recomputes it. Only something holding the secret can mint one, and the
secret exists only in the theme's Liquid and in the API's environment.

Trade-off, recorded in the integration plan: anyone who can read the theme's
code can read the secret, and so could pose as any customer. What that would
expose is kept small on purpose:

  * her measurements never leave the server after she enters them (the API's
    store-customer endpoints don't return them, and the backup copy kept in her
    browser is encrypted with a server-only key -- see profile_token);
  * her engine user id is derived with that server-only key, so it can't be
    guessed from a Shopify customer id to reach the older demo endpoints that
    look things up by user id;
  * rate_limit throttles anyone working through many customers.

A Shopify app's App Proxy signature removes the secret from the theme entirely;
the identity this returns is the same either way, so moving to an app later
replaces only verify_customer_token.
"""

import hashlib
import hmac
import os
import time

from py_src.utils.errors import AuthError

HEADER = "X-MyStyle-Customer"

# The stores the theme integration serves, and the browser origins each one's
# pages are served from (added to CORS). Not secret.
STORES = {
    "eighth-hour-us": {
        # The store's domains, plus its myshopify address, which theme previews
        # and the theme editor can be served from.
        "origins": ("https://www.eighth-hour.com", "https://eighth-hour.com",
                    "https://eighth-hour-us.myshopify.com"),
    },
}

# A token is minted on every page render, so a day comfortably covers a long
# browsing session; past that the theme asks for a fresh one.
TOKEN_MAX_AGE_S = 24 * 3600
# Tolerate the theme's clock running a little ahead of the API's.
FUTURE_SKEW_S = 300

USER_ID_PREFIX = "shopify"


def theme_secret() -> str:
    """Shared with the theme's Liquid. Read per call, so rotating it needs a
    restart, not a deploy."""
    return os.environ.get("MYSTYLE_THEME_SECRET", "").strip()


def server_key() -> str:
    """
    Known only to the API, never to the theme. Derives customers' user ids, the
    profile backup's encryption key and the owner's admin token. Unlike the
    theme secret it must not be rotated: every saved profile is keyed by it.
    """
    return os.environ.get("MYSTYLE_SERVER_KEY", "").strip()


def derive(purpose: str) -> bytes:
    """A key for one purpose, from the server key."""
    key = server_key()
    if not key:
        raise AuthError("Store sign-in is not configured on this server")
    return hmac.new(key.encode(), f"mystyle:{purpose}".encode(), hashlib.sha256).digest()


def store_origins():
    return [origin for store in STORES.values() for origin in store["origins"]]


def sign(store: str, customer_id: str, issued_at: str, secret: str) -> str:
    message = f"{store}:{customer_id}:{issued_at}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_customer_token(token: str, now: float = None):
    """
    Returns (store, customer_id) for a valid token, or raises AuthError (401).
    With no secret configured the integration is off, and every token fails.
    """
    secret = theme_secret()
    if not secret:
        raise AuthError("Store sign-in is not configured on this server")

    parts = (token or "").strip().split(".")
    if len(parts) != 4:
        raise AuthError("Malformed customer token")
    store, customer_id, issued_at, signature = parts
    if store not in STORES or not customer_id.isdigit() or not issued_at.isdigit():
        raise AuthError("Malformed customer token")

    age = (time.time() if now is None else now) - int(issued_at)
    if age > TOKEN_MAX_AGE_S or age < -FUTURE_SKEW_S:
        raise AuthError("Customer token expired -- reload the page")

    expected = sign(store, customer_id, issued_at, secret)
    if not hmac.compare_digest(expected, signature.lower()):
        raise AuthError("Invalid customer token")
    return store, customer_id


def user_id_for(store: str, customer_id: str) -> str:
    """
    The engine's user id for a store customer: one profile per store account.
    Keyed with the server key, so it reveals nothing about -- and can't be
    worked out from -- her Shopify customer id.
    """
    digest = hmac.new(derive("user-id"), f"{store}:{customer_id}".encode(), hashlib.sha256)
    return f"{USER_ID_PREFIX}_{digest.hexdigest()[:32]}"


def admin_token() -> str:
    """What the owner sends (X-MyStyle-Admin) to delete a customer's data on a
    privacy request. Derived, so it needs no extra setting."""
    return derive("admin").hex()


def verify_admin_token(supplied: str) -> None:
    if not supplied or not hmac.compare_digest(admin_token(), supplied.strip().lower()):
        raise AuthError("Missing or invalid admin token")
