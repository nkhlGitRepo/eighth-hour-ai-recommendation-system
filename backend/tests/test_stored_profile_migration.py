"""
The stored-profile migration must agree with M3 and touch nothing else.

A migration that rewrites saved customer data gets one chance to be right, and
it runs against a database that also holds credentials. These tests pin the two
properties that matter: the size it writes is the size the engine would compute
today, and every other column comes out byte-identical.
"""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_stored_size_profiles.py"
_spec = importlib.util.spec_from_file_location("migrate_stored_size_profiles", _SCRIPT)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def build_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "create table intake_sessions ("
        "  session_id text primary key, user_id text,"
        "  body_measurements text, shape_profile text, status text)"
    )
    conn.executemany("insert into intake_sessions values (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def row(session_id, bust, waist, hips, shape_class, stored_sizes, status="complete"):
    return (
        session_id,
        f"user-{session_id}",
        json.dumps({"bust": bust, "waist": waist, "hips": hips, "height": 165.0}),
        json.dumps({"shape_class": shape_class, "size_recommendation_by_category": stored_sizes}),
        status,
    )


def read(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    out = {r["session_id"]: dict(r) for r in conn.execute("select * from intake_sessions")}
    conn.close()
    return out


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "sessions.db"
    build_db(path, [
        # A stale row: bust 90 was "S" under the previous chart.
        row("stale", 90.0, 72.0, 97.0, "balanced",
            {"tops": "S", "skirts": "M", "dresses": "S", "trousers": "M",
             "vests": "S", "coOrds": "S/M"}),
        # Apple: tops are sized on the waist, which the migration must respect.
        row("apple", 90.0, 95.0, 97.0, "apple",
            {"tops": "S", "skirts": "M", "dresses": "S", "trousers": "M",
             "vests": "S", "coOrds": "S/M"}),
        # Unreadable rows must be left exactly as found, not corrupted.
        ("broken-json", "u", "{not json", '{"shape_class": "balanced"}', "complete"),
        ("no-sizes", "u", json.dumps({"bust": 90.0, "waist": 72.0, "hips": 97.0}),
         json.dumps({"shape_class": "balanced"}), "complete"),
        ("null-profile", "u", json.dumps({"bust": 90.0}), None, "complete"),
    ])
    return path


def invoke(db, dry_run=False):
    import sys
    argv = sys.argv
    sys.argv = ["migrate", "--db", str(db)] + (["--dry-run"] if dry_run else [])
    try:
        return migration.main()
    finally:
        sys.argv = argv


class TestMigrationCorrectness:
    def test_rewrites_to_exactly_what_m3_computes(self, db):
        invoke(db)
        after = read(db)
        profiler = BodyShapeProfiler()
        for session_id, bust, waist, hips, shape in (
            ("stale", 90.0, 72.0, 97.0, "balanced"),
            ("apple", 90.0, 95.0, 97.0, "apple"),
        ):
            stored = json.loads(after[session_id]["shape_profile"])
            assert stored["size_recommendation_by_category"] == \
                profiler._recommend_sizes(shape, bust, waist, hips), (
                    f"{session_id} disagrees with M3 -- the migration would replace one "
                    f"wrong stored size with another"
                )

    def test_apple_tops_still_sized_on_the_waist(self, db):
        """The rule that made a hand-written mapping wrong the first time."""
        invoke(db)
        after = json.loads(read(db)["apple"]["shape_profile"])
        sizes = after["size_recommendation_by_category"]
        assert sizes["tops"] == migration._profiler._recommend_sizes(
            "apple", 90.0, 95.0, 97.0)["tops"]
        # ...and differs from the balanced row, which has the same bust.
        balanced = json.loads(read(db)["stale"]["shape_profile"])
        assert sizes["tops"] != balanced["size_recommendation_by_category"]["tops"]

    def test_coord_sets_keep_their_composite_form(self, db):
        invoke(db)
        value = json.loads(read(db)["stale"]["shape_profile"])[
            "size_recommendation_by_category"]["coOrds"]
        assert "/" in value, f"co-ord sets must stay a top/bottom pair, got {value!r}"


class TestMigrationSafety:
    def test_leaves_every_other_column_untouched(self, db):
        before = read(db)
        invoke(db)
        after = read(db)
        assert set(before) == set(after)
        for session_id, original in before.items():
            for column, value in original.items():
                if column == "shape_profile":
                    continue
                assert after[session_id][column] == value, (
                    f"{session_id}.{column} was modified -- the migration must only "
                    f"touch stored sizes"
                )

    @pytest.mark.parametrize("session_id", ["broken-json", "no-sizes", "null-profile"])
    def test_unreadable_rows_are_left_exactly_as_found(self, db, session_id):
        before = read(db)[session_id]
        invoke(db)
        assert read(db)[session_id] == before

    def test_dry_run_writes_nothing(self, db):
        before = read(db)
        invoke(db, dry_run=True)
        assert read(db) == before

    def test_is_idempotent(self, db):
        invoke(db)
        once = read(db)
        invoke(db)
        assert read(db) == once, "running the migration twice must be a no-op"

    def test_measurements_are_never_rewritten(self, db):
        """
        The stored numbers are the customer's own body. A chart revision changes
        what we call them, never what they are.
        """
        before = {k: v["body_measurements"] for k, v in read(db).items()}
        invoke(db)
        assert {k: v["body_measurements"] for k, v in read(db).items()} == before
