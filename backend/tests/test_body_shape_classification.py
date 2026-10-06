"""
Body shape classification (M3) against the FFIT-based definitions.

Reported by a tester: bust 107, waist 90, hips 107 was classified "pear" and
told "Your hips are fuller than your bust". The rules compared bust with waist
and waist with hips but never bust with hips -- the comparison that defines
pear. These tests sweep the whole supported measurement range rather than a
handful of fixtures, and check each answer against the definition it claims,
using the thresholds from constants.py rather than transcribed numbers.
"""

import itertools
import json
import re

import pytest

from py_src.constants import MEASUREMENT_RANGES, SHAPE_THRESHOLDS, BODY_SHAPE_CLASSES
from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler, SHAPE_MEANINGS
from py_src.persistence.session_repository import SQLiteSessionRepository

classify = BodyShapeProfiler._classify_shape
T = SHAPE_THRESHOLDS


def _grid(step=2):
    """Every bust/waist/hips combination in the supported range, every `step` cm."""
    def axis(name):
        low, high = MEASUREMENT_RANGES[name]
        return range(int(low), int(high) + 1, step)
    return itertools.product(axis("bust"), axis("waist"), axis("hips"))


def _relative(bust, waist, hips):
    frame = (bust + hips) / 2
    return {
        "bust_over_hips": (bust - hips) / frame,
        "bust_over_waist": (bust - waist) / frame,
        "hips_over_waist": (hips - waist) / frame,
        "waist_gap": (max(bust, hips) - waist) / frame,
    }


ALL = [(b, w, h, classify(b, w, h)) for b, w, h in _grid()]


class TestTheReportedCase:
    def test_equal_bust_and_hips_is_not_pear(self):
        profile = BodyShapeProfiler().profile(
            {"bust": 107, "waist": 90, "hips": 107, "height": 165})
        assert profile["shape_class"] == "balanced"
        assert "fuller than your bust" not in profile["shape_summary"]
        assert profile["shape_summary"].startswith("Your bust and hips are the same")
        assert "17 cm smaller than both" in profile["shape_summary"]

    def test_no_invented_shoulder_ratio(self):
        profile = BodyShapeProfiler().profile(
            {"bust": 107, "waist": 90, "hips": 107, "height": 165})
        assert "shoulder_hip" not in profile["ratios"]
        assert profile["ratios"]["bust_hip"] == 1.0
        assert profile["comparisons_cm"] == {
            "bust_minus_hips": 0.0, "bust_minus_waist": 17.0, "hips_minus_waist": 17.0}


class TestDefinitionsHoldEverywhere:
    """Each class, wherever it is returned, satisfies its definition."""

    def test_pear_only_when_hips_distinctly_fuller(self):
        for b, w, h, shape in ALL:
            if shape == "pear":
                assert -_relative(b, w, h)["bust_over_hips"] >= T["bust_hips_distinct"], (b, w, h)

    def test_athletic_only_when_bust_distinctly_fuller(self):
        for b, w, h, shape in ALL:
            if shape == "athletic":
                r = _relative(b, w, h)
                assert r["bust_over_hips"] >= T["bust_hips_distinct"], (b, w, h)
                assert r["bust_over_waist"] < T["bust_waist_defined"], (b, w, h)

    def test_even_bust_and_hips_is_never_pear_or_athletic(self):
        """The reported bug, over the whole range."""
        for b, w, h, shape in ALL:
            if abs(_relative(b, w, h)["bust_over_hips"]) <= T["bust_hips_even"]:
                assert shape not in ("pear", "athletic"), (b, w, h, shape)

    def test_bust_at_least_hips_is_never_pear(self):
        for b, w, h, shape in ALL:
            if b >= h:
                assert shape != "pear", (b, w, h)
            if h >= b:
                assert shape != "athletic", (b, w, h)

    def test_hourglass_has_a_defined_waist(self):
        for b, w, h, shape in ALL:
            if shape == "hourglass":
                r = _relative(b, w, h)
                assert (r["bust_over_waist"] >= T["bust_waist_defined"]
                        or r["hips_over_waist"] >= T["hips_waist_defined"]), (b, w, h)

    def test_apple_exactly_when_the_waist_is_nearly_the_fullest_point(self):
        for b, w, h, shape in ALL:
            assert (shape == "apple") == (_relative(b, w, h)["waist_gap"] <= T["apple_waist_gap"]), (b, w, h)

    def test_straight_and_balanced_have_no_distinct_difference(self):
        for b, w, h, shape in ALL:
            if shape in ("straight", "balanced"):
                r = _relative(b, w, h)
                assert abs(r["bust_over_hips"]) < T["bust_hips_distinct"], (b, w, h)
                assert r["bust_over_waist"] < T["bust_waist_defined"], (b, w, h)
                assert r["hips_over_waist"] < T["hips_waist_defined"], (b, w, h)
                expected = "straight" if r["waist_gap"] < T["balanced_waist_gap"] else "balanced"
                assert shape == expected, (b, w, h)

    def test_every_class_is_reachable(self):
        assert {shape for *_, shape in ALL} == set(BODY_SHAPE_CLASSES)


class TestScaleInvariance:
    def test_same_proportions_same_shape_at_any_size(self):
        """A size-XXS hourglass is still an hourglass: thresholds are proportional."""
        checked = 0
        for b, w, h, shape in ALL[::7]:
            for k in (0.9, 1.1):
                sb, sw, sh = b * k, w * k, h * k
                if not all(MEASUREMENT_RANGES[n][0] <= v <= MEASUREMENT_RANGES[n][1]
                           for n, v in (("bust", sb), ("waist", sw), ("hips", sh))):
                    continue
                assert classify(sb, sw, sh) == shape, (b, w, h, k)
                checked += 1
        assert checked > 1000


class TestSummaryNeverContradictsTheNumbers:
    """The text is generated from the measurements, and must agree with them."""

    def test_over_the_grid(self):
        for b, w, h in list(_grid(step=3))[::5]:
            shape = classify(b, w, h)
            text = BodyShapeProfiler._explain_shape(shape, b, w, h)
            assert text.endswith(SHAPE_MEANINGS[shape] + "."), text

            fuller = re.match(r"Your (bust|hips) (?:is|are) (\d+) cm fuller than your (bust|hips)", text)
            if fuller:
                larger, amount = fuller.group(1), int(fuller.group(2))
                diff = (b - h) if larger == "bust" else (h - b)
                assert diff > 0 and round(diff) == amount, (b, w, h, text)
            elif text.startswith("Your bust and hips are the same"):
                assert round(b - h) == 0, (b, w, h, text)
            else:
                within = re.match(r"Your bust and hips are within (\d+) cm", text)
                assert within and round(abs(b - h)) == int(within.group(1)), (b, w, h, text)

            for amount, direction, name in re.findall(r"(\d+) cm (smaller|larger) than (?:your )?(bust|hips|both)", text):
                others = {"bust": [b], "hips": [h], "both": [b, h]}[name]
                for other in others:
                    gap = other - w
                    assert round(abs(gap)) == int(amount), (b, w, h, text)
                    assert (gap > 0) == (direction == "smaller"), (b, w, h, text)


class TestSizesUnchangedByTheNewRules:
    def test_tops_by_bust_and_bottoms_by_hips_except_apple(self):
        """Classification changed; the size rules (incl. apple tops by waist) did not."""
        from py_src.constants import SIZE_BOUNDARIES, WAIST_SIZE_BOUNDARIES, HIP_SIZE_BOUNDARIES

        def size(value, table):
            # The top band is half-open, so the very top of the supported range
            # falls past it; M3 deliberately resolves that to the largest size.
            return next((s for s, (lo, hi) in table.items() if lo <= value < hi),
                        list(table)[-1])

        profiler = BodyShapeProfiler()
        for b, w, h, shape in ALL[::997]:
            sizes = profiler._recommend_sizes(shape, b, w, h)
            top = size(w, WAIST_SIZE_BOUNDARIES) if shape == "apple" else size(b, SIZE_BOUNDARIES)
            assert sizes["tops"] == top
            assert sizes["skirts"] == size(h, HIP_SIZE_BOUNDARIES)


class TestStoredProfilesAreRefreshed:
    TESTER = {"bust": 107, "waist": 90, "hips": 107, "height": 165}

    def _old_pear_profile(self):
        return {"shape_class": "pear", "ratios": {"bust_waist": 1.19, "waist_hip": 0.84, "shoulder_hip": 1.0},
                "size_recommendation_by_category": {"tops": "L"}, "fit_notes": [],
                "profile_version": "1.0.0"}

    def test_outdated_profile_is_rebuilt_from_the_measurements(self):
        fresh = BodyShapeProfiler.refresh_if_outdated(self._old_pear_profile(), dict(self.TESTER))
        assert fresh["shape_class"] == "balanced"
        assert fresh["profile_version"] == BodyShapeProfiler.PROFILE_VERSION
        assert "shoulder_hip" not in fresh["ratios"]

    def test_current_profile_is_left_alone(self):
        current = BodyShapeProfiler().profile(dict(self.TESTER))
        assert BodyShapeProfiler.refresh_if_outdated(current, dict(self.TESTER)) is current

    @pytest.mark.parametrize("measurements", [None, {}, {"bust": 107}, {"bust": 5, "waist": 5, "hips": 5, "height": 5}])
    def test_unrecomputable_profile_is_left_alone(self, measurements):
        old = self._old_pear_profile()
        assert BodyShapeProfiler.refresh_if_outdated(old, measurements) is old

    def test_a_session_loaded_from_the_database_gets_the_current_profile(self, tmp_path):
        """End to end through the one function every read path uses."""
        from py_src.modules.m1_intake_orchestrator import IntakeOrchestrator
        from py_src.modules.m2_sizing_integration import SizingIntegration, MockSizingProvider
        from py_src.guardrails.consent_tracker import ConsentTracker

        db = str(tmp_path / "sessions.db")
        repo = SQLiteSessionRepository(db_path=db)
        consent = ConsentTracker(db_path=db)
        orchestrator = IntakeOrchestrator(session_repo=repo, consent_tracker=consent,
                                          sizing=SizingIntegration(provider=MockSizingProvider()))
        session = orchestrator.create_session(user_id="refresh_user")
        orchestrator.record_consent(session.session_id, photo_consent=True, measurement_consent=True)
        consent.record_consent(user_id="refresh_user", photo_consent=True, measurement_consent=True)
        orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
        orchestrator.extract_measurements(session.session_id)

        # Rewrite the stored row as the old classifier left it for the tester.
        import sqlite3
        stored = json.loads(sqlite3.connect(db).execute(
            "select body_measurements from intake_sessions where session_id = ?",
            (session.session_id,)).fetchone()[0])
        stored.update(self.TESTER)
        with sqlite3.connect(db) as conn:
            conn.execute("update intake_sessions set body_measurements = ?, shape_profile = ? where session_id = ?",
                         (json.dumps(stored), json.dumps(self._old_pear_profile()), session.session_id))

        for loaded in (repo.get(session.session_id), repo.get_by_user("refresh_user")):
            if loaded is None:
                continue
            assert loaded.shape_profile["shape_class"] == "balanced"
            assert loaded.shape_profile["profile_version"] == BodyShapeProfiler.PROFILE_VERSION
