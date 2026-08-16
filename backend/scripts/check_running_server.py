#!/usr/bin/env python3
"""
Is the API you're talking to actually running the code in this working copy?

"The server is up" and "the server is running your code" are different
questions, and only the first one was ever answerable. Python reads constants.py
and products.json once at import, so a process started before an edit keeps
serving the old size chart and old catalog forever, with a completely healthy
/health. That has produced two false diagnoses already -- most memorably half an
hour spent investigating a browser showing six sizes and the wrong recommended
size, against a backend nobody had restarted.

This asks the server for the fingerprint of what it loaded and compares it to
what the current source produces.

    python3 scripts/check_running_server.py                 # localhost:8000
    python3 scripts/check_running_server.py --url http://127.0.0.1:8199

Exit status is 0 when current, 1 when stale, 2 when nothing is listening -- so
it can gate a verification run rather than being read by eye.
"""

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from py_src.constants import SIZE_CHART_SOURCE, STANDARD_SIZES  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
CATALOG = BACKEND / "products.json"


def source_digest():
    """Must match main._source_digest exactly."""
    accumulator = hashlib.sha256()
    for path in sorted((BACKEND / "py_src").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        accumulator.update(path.read_bytes())
    accumulator.update((BACKEND / "main.py").read_bytes())
    return accumulator.hexdigest()[:12]


def digest(payload):
    """Must match main.runtime_fingerprint's hashing exactly."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]


def expected_fingerprint():
    products = json.loads(CATALOG.read_text())
    catalog_state = sorted(
        (p["slug"], p.get("length"), tuple(p.get("sizes") or ())) for p in products
    )
    return {
        "source": source_digest(),
        "size_chart": digest(SIZE_CHART_SOURCE),
        "sizes": list(STANDARD_SIZES),
        "catalog": digest(catalog_state),
        "product_count": len(catalog_state),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    try:
        with urllib.request.urlopen(args.url.rstrip("/") + "/health", timeout=5) as response:
            health = json.load(response)
    except (urllib.error.URLError, TimeoutError) as error:
        print(f"  no server answering at {args.url} ({error})")
        return 2

    live = health.get("fingerprint")
    if live is None:
        print("  server is running a build from before /health reported a fingerprint.")
        print("  That is itself proof it is stale -- restart it.")
        return 1

    # Provider is environment, not source, so it is reported rather than
    # compared -- but a backend quietly running the demo estimator returns the
    # same fixed measurements for every photo, which is worth saying out loud.
    provider = live.pop("sizing_provider", None)
    if provider:
        note = ""
        if "Mock" in provider:
            note = ("  <-- demo estimator: every photo returns the same fixed "
                    "numbers. Start with SIZING_PROVIDER=mediapipe for real analysis.")
        print(f"  sizing provider: {provider}{note}")

    expected = expected_fingerprint()
    if live == expected:
        print(f"  {args.url} is running the current source")
        print(f"    size chart {live['size_chart']}  "
              f"catalog {live['catalog']}  ({live['product_count']} products)")
        return 0

    print(f"  STALE: {args.url} is not running the current source. Restart it.")
    for key in sorted(set(expected) | set(live)):
        mark = " " if live.get(key) == expected.get(key) else "*"
        print(f"   {mark} {key:14} serving {live.get(key)!r}  source says {expected.get(key)!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
