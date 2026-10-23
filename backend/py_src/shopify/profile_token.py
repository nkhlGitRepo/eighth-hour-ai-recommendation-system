"""
An encrypted copy of a customer's style profile, kept in her own browser.

On Render's free plan the API's database is wiped whenever the service
restarts or wakes from sleep, which on a quiet store is every 15 minutes -- so
every saved profile would vanish. The theme keeps this token and hands it back
when the API no longer knows her; the API decrypts it and rebuilds the profile.

It is encrypted and authenticated (Fernet) with a key derived from the
server-only key, so neither she, nor anyone holding the theme's secret, can read
her measurements out of it or alter it -- and it names the store and customer it
was issued to, so it can't be replayed for someone else. On a paid plan with a
persistent disk it simply goes unused.
"""

import base64
import json

from cryptography.fernet import Fernet, InvalidToken

from py_src.shopify.theme_auth import derive
from py_src.utils.errors import AuthError

VERSION = 1


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(derive("profile-encryption")))


def issue(store: str, customer_id: str, measurements: dict, preferences: dict) -> str:
    payload = {
        "v": VERSION,
        "store": store,
        "customer": customer_id,
        "measurements": {k: measurements[k] for k in ("bust", "waist", "hips", "height")
                         if measurements.get(k) is not None},
        "preferences": {
            "colors": list(preferences.get("preferred_colors") or []),
            "silhouettes": list(preferences.get("preferred_silhouettes") or []),
            "occasions": list(preferences.get("occasions") or []),
        },
    }
    return _fernet().encrypt(json.dumps(payload, separators=(",", ":")).encode()).decode()


def read(token: str, store: str, customer_id: str) -> dict:
    """The payload, if the token is genuine and was issued to this customer."""
    try:
        payload = json.loads(_fernet().decrypt((token or "").encode()))
    except (InvalidToken, ValueError):
        raise AuthError("Invalid profile token")
    if payload.get("v") != VERSION or payload.get("store") != store or payload.get("customer") != customer_id:
        raise AuthError("Profile token belongs to a different customer")
    return payload
