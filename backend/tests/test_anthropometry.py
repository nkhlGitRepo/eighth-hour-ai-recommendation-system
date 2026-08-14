"""
Tests for the pose-landmark -> body-measurement math.

Deliberately model-free: this is pure geometry, so it runs in milliseconds
without loading MediaPipe, and a different pose source could reuse it.
"""

import math
import pytest

from py_src.constants import MEASUREMENT_RANGES
from py_src.providers.anthropometry import (
    ellipse_circumference,
    pixels_to_cm_scale,
    measurements_from_breadths,
    SHOULDER_TO_ANKLE_RATIO,
)


class TestEllipseCircumference:
    def test_circle_matches_known_formula(self):
        """A circle is the degenerate ellipse -- must equal pi*d."""
        assert ellipse_circumference(28.0, 28.0) == pytest.approx(math.pi * 28.0, rel=1e-3)

    def test_flatter_ellipse_has_smaller_circumference(self):
        """Same breadth, less depth -> smaller way around."""
        assert ellipse_circumference(30.0, 24.0) < ellipse_circumference(30.0, 30.0)

    def test_scales_linearly(self):
        """Doubling both axes doubles the perimeter."""
        assert ellipse_circumference(60.0, 48.0) == pytest.approx(
            2 * ellipse_circumference(30.0, 24.0), rel=1e-6
        )

    def test_degenerate_inputs_return_zero(self):
        assert ellipse_circumference(0, 10) == 0.0
        assert ellipse_circumference(10, 0) == 0.0
        assert ellipse_circumference(-5, 10) == 0.0


class TestPixelScale:
    def test_scale_uses_the_anthropometric_span(self):
        """500px spanning shoulder->ankle on a 170cm body."""
        scale = pixels_to_cm_scale(500, 170)
        assert scale == pytest.approx(SHOULDER_TO_ANKLE_RATIO * 170 / 500)

    def test_taller_person_same_pixels_means_bigger_scale(self):
        """Identical framing but a taller stated height -> every cm value grows."""
        assert pixels_to_cm_scale(500, 190) > pixels_to_cm_scale(500, 155)

    def test_more_pixels_same_height_means_smaller_scale(self):
        """A closer/larger photo of the same person -> fewer cm per pixel."""
        assert pixels_to_cm_scale(1000, 170) < pixels_to_cm_scale(500, 170)

    @pytest.mark.parametrize("span,height", [(0, 170), (-10, 170), (500, 0), (500, -5)])
    def test_rejects_unusable_inputs(self, span, height):
        with pytest.raises(ValueError):
            pixels_to_cm_scale(span, height)


class TestMeasurementsFromBreadths:
    def test_average_body_produces_plausible_measurements(self):
        """
        Inputs are MEDIAPIPE LANDMARK SPANS, not tape measurements: a 36cm
        shoulder span with a 22cm pelvis span (the ~0.60 ratio real photos
        show) is close to an average adult woman. Output should look like a
        real size-chart entry.
        """
        m = measurements_from_breadths(36.0, 22.0)
        assert 80 <= m["bust"] <= 95
        assert 62 <= m["waist"] <= 78
        assert 92 <= m["hips"] <= 108

    def test_output_is_within_the_ranges_the_app_accepts(self):
        """Otherwise SizingIntegration would reject the extraction downstream."""
        m = measurements_from_breadths(36.0, 22.0)
        for field in ("bust", "waist", "hips"):
            low, high = MEASUREMENT_RANGES[field]
            assert low <= m[field] <= high

    def test_hips_exceed_waist_for_a_typical_body(self):
        m = measurements_from_breadths(36.0, 22.0)
        assert m["hips"] > m["waist"]

    def test_broader_shoulders_increase_bust_only(self):
        """Bust comes from the shoulders; waist/hips come from the pelvis."""
        narrow = measurements_from_breadths(33.0, 22.0)
        broad = measurements_from_breadths(40.0, 22.0)
        assert broad["bust"] > narrow["bust"]
        assert broad["waist"] == narrow["waist"]
        assert broad["hips"] == narrow["hips"]

    def test_wider_pelvis_increases_waist_and_hips_only(self):
        narrow = measurements_from_breadths(36.0, 19.0)
        wide = measurements_from_breadths(36.0, 25.0)
        assert wide["waist"] > narrow["waist"]
        assert wide["hips"] > narrow["hips"]
        assert wide["bust"] == narrow["bust"]

    def test_shoulder_breadth_is_reported_unchanged(self):
        assert measurements_from_breadths(36.4, 22.0)["shoulder_cm"] == 36.4

    def test_different_bodies_give_different_numbers(self):
        """
        The property that separates this from the placeholder provider: output
        actually varies with the input body.
        """
        a = measurements_from_breadths(33.0, 19.0)
        b = measurements_from_breadths(40.0, 25.0)
        assert (a["bust"], a["waist"], a["hips"]) != (b["bust"], b["waist"], b["hips"])


class TestCalibratedToRealMediaPipeOutput:
    """
    Regression guard for a real bug: the multipliers were originally derived
    from surface-anthropometry tables, but MediaPipe's hip landmarks are joint
    centres and measure only ~0.57-0.62 of the shoulder span. That mismatch
    produced waists near 56cm and hips NARROWER than the bust, and a
    ratio-based pose check that rejected ordinary photos.

    The two cases below are the actual geometry measured off real photographs.
    """

    # (label, shoulder_span_cm, pelvis_span_cm) as MediaPipe reported them
    REAL_OBSERVATIONS = [
        ("standing torso photo", 37.0, 22.3),
        ("wide-stance photo", 39.9, 22.9),
    ]

    @pytest.mark.parametrize("label,shoulder,pelvis", REAL_OBSERVATIONS)
    def test_real_geometry_yields_a_plausible_female_figure(self, label, shoulder, pelvis):
        m = measurements_from_breadths(shoulder, pelvis)
        assert 80 <= m["bust"] <= 105, f"{label}: bust {m['bust']}"
        assert 62 <= m["waist"] <= 85, f"{label}: waist {m['waist']}"
        assert 92 <= m["hips"] <= 115, f"{label}: hips {m['hips']}"

    @pytest.mark.parametrize("label,shoulder,pelvis", REAL_OBSERVATIONS)
    def test_hips_are_not_narrower_than_the_bust(self, label, shoulder, pelvis):
        """
        The clearest symptom of the old miscalibration. For the overwhelming
        majority of women hips are at least as large as the bust, so hips well
        below bust means the pelvis multiplier is wrong again.
        """
        m = measurements_from_breadths(shoulder, pelvis)
        assert m["hips"] >= m["bust"] * 0.95, f"{label}: hips {m['hips']} vs bust {m['bust']}"

    @pytest.mark.parametrize("label,shoulder,pelvis", REAL_OBSERVATIONS)
    def test_waist_is_not_implausibly_small(self, label, shoulder, pelvis):
        """The old constants produced ~56cm here, below the app's 55cm floor."""
        m = measurements_from_breadths(shoulder, pelvis)
        assert m["waist"] >= 62, f"{label}: waist {m['waist']}"
