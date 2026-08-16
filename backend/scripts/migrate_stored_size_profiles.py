#!/usr/bin/env python3
"""
Recompute the sizes stored on saved shape profiles against the current chart.

Why this is needed: `size_recommendation_by_category` is computed once, when a
customer finishes intake, and then read back verbatim -- /account/profile shows
it, and /fit-check passes it to M7 as `known_size`, which *forces* it as the
recommended size. So after a chart revision a returning customer sees the size
the old chart gave them, scored against the new one. Concretely, a bust of 90cm
saved as "S" now renders as:

    recommended : S    confidence 0.84
    fit_scores  : {... "XS": 0.88, "S": 0.84 ...}
    notes       : ["Recommended size runs large in the bust."]

-- a panel that recommends a size, shows a different size scoring higher, and
then tells the customer its own recommendation doesn't fit. Their measurements
haven't changed and neither has the right answer for them; only the stored
label is wrong.

This rewrites that label from the measurements already on the row, using the
same M3 code path that would run if they redid intake today. It does not touch
measurements, consent, credentials, or anything else.

    python3 scripts/migrate_stored_size_profiles.py --dry-run   # report only
    python3 scripts/migrate_stored_size_profiles.py             # apply

Back the database up first -- it holds the auth tables too.
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler  # noqa: E402

DB = Path(__file__).resolve().parent.parent / "intake_sessions.db"

# Recompute through M3 itself rather than reimplementing its mapping here.
# The first draft of this script kept its own copy and got it wrong within
# minutes -- it missed that co-ord sets are stored as a composite "M/L" string
# and that apple shapes are sized on the waist for tops. A migration whose
# answer differs from the engine's just replaces one wrong stored size with
# another, so there must be exactly one implementation and this is not it.
_profiler = BodyShapeProfiler()


def recomputed(profile, measurements):
    """
    The size map M3 would produce for these measurements today, or None if the
    row can't be recomputed honestly.
    """
    stored = profile.get("size_recommendation_by_category")
    if not isinstance(stored, dict) or not stored:
        return None
    try:
        bust = float(measurements["bust"])
        waist = float(measurements["waist"])
        hips = float(measurements["hips"])
    except (KeyError, TypeError, ValueError):
        return None

    shape_class = profile.get("shape_class")
    if not shape_class:
        return None

    fresh = _profiler._recommend_sizes(shape_class, bust, waist, hips)
    # Only rewrite keys the row already had. Adding or removing categories would
    # change what the profile claims, which is beyond fixing a stale label.
    return {category: fresh.get(category, old) for category, old in stored.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report, change nothing")
    parser.add_argument("--db", default=str(DB), help="database path")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select session_id, user_id, body_measurements, shape_profile from intake_sessions "
        "where shape_profile is not null and body_measurements is not null"
    ).fetchall()

    updates, moves, skipped, unchanged = [], Counter(), 0, 0
    for row in rows:
        try:
            measurements = json.loads(row["body_measurements"])
            profile = json.loads(row["shape_profile"])
        except (json.JSONDecodeError, TypeError):
            skipped += 1
            continue
        if not isinstance(profile, dict) or not isinstance(measurements, dict):
            skipped += 1
            continue

        fixed = recomputed(profile, measurements)
        if fixed is None:
            skipped += 1
            continue
        old = profile["size_recommendation_by_category"]
        if fixed == old:
            unchanged += 1
            continue
        for category, new_size in fixed.items():
            if old.get(category) != new_size:
                moves[f"{old.get(category)} -> {new_size}"] += 1
        profile["size_recommendation_by_category"] = fixed
        updates.append((json.dumps(profile), row["session_id"]))

    print(f"  rows with a stored profile : {len(rows)}")
    print(f"    already correct          : {unchanged}")
    print(f"    to rewrite               : {len(updates)}")
    print(f"    skipped (unreadable)     : {skipped}")
    if moves:
        print("\n  size changes:")
        for move, count in moves.most_common():
            print(f"    {move:16} {count}")

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return 0
    if not updates:
        print("\n  nothing to do")
        return 0

    with conn:
        conn.executemany(
            "update intake_sessions set shape_profile = ? where session_id = ?", updates
        )
    print(f"\n  rewrote {len(updates)} stored profiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
