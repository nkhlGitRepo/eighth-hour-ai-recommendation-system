#!/usr/bin/env python3
"""
Print a customer token for a TEST customer id, signed exactly as the theme's
Liquid signs real ones, for trying the signed-in experience in a theme preview
(where you are staff, not a signed-in customer):

    python3 shopify/mint_test_token.py            # test customer 990000000001
    python3 shopify/mint_test_token.py 990000000002

Then, on the preview page, run in the browser console:

    MyStyle.setToken('<the printed token>')

Test customer ids should not be real customers' ids: the profile it builds is
stored against that id in the styling engine (never in Shopify). Delete it from
the My Style page when done. Reads the theme secret from shopify/private/secrets.env.
"""

import hashlib
import hmac
import sys
import time
from pathlib import Path

STORE = "eighth-hour-us"
ENV = Path(__file__).resolve().parent / "private" / "secrets.env"


def main():
    customer_id = sys.argv[1] if len(sys.argv) > 1 else "990000000001"
    if not customer_id.isdigit():
        raise SystemExit("customer id must be digits")
    secret = next((line.split("=", 1)[1].strip() for line in ENV.read_text().splitlines()
                   if line.startswith("MYSTYLE_THEME_SECRET=")), "")
    if not secret:
        raise SystemExit(f"{ENV}: no MYSTYLE_THEME_SECRET")
    issued = str(int(time.time()))
    signature = hmac.new(secret.encode(), f"{STORE}:{customer_id}:{issued}".encode(), hashlib.sha256).hexdigest()
    print(f"{STORE}.{customer_id}.{issued}.{signature}")


if __name__ == "__main__":
    main()
