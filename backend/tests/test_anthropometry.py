"""
Tests for the outline -> body-measurement math.

Deliberately model-free: every function takes plain numbers and a boolean mask,
so these run in milliseconds on synthetic bodies whose true widths are known --
which is what lets them assert exact answers rather than "plausible" ones.
"""

import numpy as np
import pytest

import py_src.providers.anthropometry as A
from py_src.providers.anthropometry import (
    SHOULDER_TO_ANKLE_RATIO,
    circumferences_from_breadths,
    combined_scale,
    pixels_to_cm_scale,
    silhouette_breadths,
    torso_width,
)

SHOULDER_Y, HIP_Y, MID_X, SIZE = 200, 500, 500, 1000


def body_mask(half_width_at, arms=None):
    """
    A synthetic person: for each row between the shoulders and below the hips,
    the torso spans MID_X +/- half_width_at(t), t = 0 at shoulders, 1 at hips.

    arms: optional (offset_from_midline_px, half_width_px) -- two vertical arms.
    """
    mask = np.zeros((SIZE, SIZE), dtype=bool)
    for y in range(SHOULDER_Y, int(SHOULDER_Y + 1.4 * (HIP_Y - SHOULDER_Y))):
        t = (y - SHOULDER_Y) / (HIP_Y - SHOULDER_Y)
        h = int(round(half_width_at(t)))
        mask[y, MID_X - h:MID_X + h + 1] = True
        if arms:
            offset, half = arms
            for centre in (MID_X - offset, MID_X + offset):
                mask[y, centre - half:centre + half + 1] = True
    return mask


def arm_segments(offset, half_cm):
    """Two vertical arms from the shoulders to below the hips."""
    bottom = SHOULDER_Y + 1.4 * (HIP_Y - SHOULDER_Y)
    return [((MID_X - offset, SHOULDER_Y), (MID_X - offset, bottom), half_cm),
            ((MID_X + offset, SHOULDER_Y), (MID_X + offset, bottom), half_cm)]


def hourglass(bust=100, waist=70, hips=105):
    """Half-widths (px) peaking at the bust line, narrowest at the navel line, fullest at the seat."""
    def half(t):
        if t <= A.BUST_LINE_T:
            return bust
        if t <= A.NAVEL_LINE_T:
            f = (t - A.BUST_LINE_T) / (A.NAVEL_LINE_T - A.BUST_LINE_T)
            return bust + (waist - bust) * f
        if t <= A.SEAT_LINE_T:
            f = (t - A.NAVEL_LINE_T) / (A.SEAT_LINE_T - A.NAVEL_LINE_T)
            return waist + (hips - waist) * f
        return hips
    return half


class TestPixelScale:
    def test_scale_uses_the_anthropometric_span(self):
        assert pixels_to_cm_scale(780.0, 165.0) == pytest.approx(
            SHOULDER_TO_ANKLE_RATIO * 165.0 / 780.0)

    def test_taller_person_same_pixels_means_bigger_scale(self):
        assert pixels_to_cm_scale(800, 180) > pixels_to_cm_scale(800, 160)

    @pytest.mark.parametrize("span,height", [(0, 165), (-5, 165), (800, 0)])
    def test_rejects_unusable_inputs(self, span, height):
        with pytest.raises(ValueError):
            pixels_to_cm_scale(span, height)


class TestCombinedScale:
    def _spans(self, ratio, span=800.0):
        return span, span * ratio

    def test_agreeing_spans_are_averaged(self):
        span, torso = self._spans(A.EXPECTED_TORSO_TO_SPAN)
        scale, source = combined_scale(span, torso, 165)
        assert source == "both"
        assert scale == pytest.approx(pixels_to_cm_scale(span, 165))

    def test_feet_out_of_frame_uses_the_torso(self):
        span, torso = self._spans(A.EXPECTED_TORSO_TO_SPAN)
        scale, source = combined_scale(span, torso, 165, ankles_in_frame=False)
        assert source == "torso"
        assert scale == pytest.approx(A.SHOULDER_TO_HIP_RATIO * 165 / torso)

    def test_ankles_guessed_too_high_falls_back_to_the_torso(self):
        """Cropped feet push the ratio up; the photo is still usable."""
        span, torso = self._spans(A.EXPECTED_TORSO_TO_SPAN + 2 * A.TORSO_TO_SPAN_TOLERANCE)
        _, source = combined_scale(span, torso, 165)
        assert source == "torso"

    @pytest.mark.parametrize("torso,height", [(0, 165), (-3, 165), (300, 0)])
    def test_unusable_torso_raises(self, torso, height):
        with pytest.raises(ValueError):
            combined_scale(800, torso, height)


class TestTapeLines:
    def test_lines_in_body_order(self):
        assert 0 < A.BUST_LINE_T < A.NAVEL_LINE_T < A.SEAT_LINE_T

    def test_bands_contain_their_lines_and_meet(self):
        assert A.BUST_BAND[0] < A.BUST_LINE_T < A.BUST_BAND[1] <= A.WAIST_BAND[0]
        assert A.WAIST_BAND[0] < A.NAVEL_LINE_T < A.WAIST_BAND[1] == A.HIP_BAND[0]
        assert A.HIP_BAND[0] < A.SEAT_LINE_T < A.HIP_BAND[1]


class TestTorsoWidth:
    def row(self, torso_half=100, arm=None):
        r = np.zeros(SIZE, dtype=bool)
        r[MID_X - torso_half:MID_X + torso_half + 1] = True
        if arm:
            centre, half = arm
            r[centre - half:centre + half + 1] = True
        return r

    def test_no_arms(self):
        assert torso_width(self.row(), MID_X, []) == (200, "clear")

    def test_separate_arm_is_ignored(self):
        r = self.row(arm=(MID_X + 140, 20))
        assert torso_width(r, MID_X, [(MID_X + 140, 20)]) == (200, "clear")

    def test_arm_resting_beside_is_cut_at_its_inner_edge(self):
        # Arm 40 px wide touching the torso's right edge (torso ends at +100).
        r = self.row(arm=(MID_X + 120, 20))
        width, quality = torso_width(r, MID_X, [(MID_X + 120, 20)])
        assert quality == "estimated"
        assert width == 200

    def test_arm_in_front_skips_the_row(self):
        r = self.row()
        assert torso_width(r, MID_X, [(MID_X + 30, 20)]) == (None, None)

    def test_no_body_at_the_midline(self):
        assert torso_width(np.zeros(SIZE, dtype=bool), MID_X, []) == (None, None)


class TestSilhouetteBreadths:
    CM_PER_PX = 0.15

    def measure(self, mask, arms=()):
        return silhouette_breadths(mask, SHOULDER_Y, HIP_Y, MID_X, list(arms), self.CM_PER_PX)

    def test_reads_bust_waist_and_hips_from_the_outline(self):
        b = self.measure(body_mask(hourglass(100, 70, 105)))
        assert b["bust"] == pytest.approx(200 * self.CM_PER_PX, abs=0.5)
        # Waist and hips are read as percentiles of their bands, so they sit just
        # inside the narrowest and fullest widths.
        assert 140 * self.CM_PER_PX <= b["waist"] <= 160 * self.CM_PER_PX
        assert 200 * self.CM_PER_PX <= b["hips"] <= 211 * self.CM_PER_PX
        assert b["quality"] == {"bust": "clear", "waist": "clear", "hips": "clear"}

    def test_fuller_body_reads_fuller(self):
        """The reported failure: a fuller body came out far too small."""
        slim = circumferences_from_breadths(self.measure(body_mask(hourglass(90, 70, 95))))
        full = circumferences_from_breadths(self.measure(body_mask(hourglass(120, 105, 120))))
        for field in ("bust", "waist", "hips"):
            assert full[field] > slim[field] * 1.15, field

    def test_waist_to_hip_ratio_follows_the_body(self):
        """The old estimator gave every photo the same 0.717."""
        defined = self.measure(body_mask(hourglass(100, 65, 105)))
        straight = self.measure(body_mask(hourglass(100, 95, 100)))
        assert defined["waist"] / defined["hips"] < 0.7
        assert straight["waist"] / straight["hips"] > 0.9

    def test_separate_arms_change_nothing(self):
        plain = self.measure(body_mask(hourglass()))
        half_px = 15
        with_arms = self.measure(body_mask(hourglass(), arms=(160, half_px)),
                                 arm_segments(160, half_px * self.CM_PER_PX))
        assert with_arms["quality"] == plain["quality"]
        for field in ("bust", "waist", "hips"):
            assert with_arms[field] == plain[field]

    def test_arms_resting_against_the_body_are_cut_away(self):
        """Arms touching at every row: still measured, from the arm's inner edge."""
        torso = hourglass(100, 100, 100)          # a straight torso, edge at +/-100
        half_px = 15
        offset = 100 + half_px                    # arm's inner edge on the torso edge
        b = self.measure(body_mask(torso, arms=(offset, half_px)),
                         arm_segments(offset, half_px * self.CM_PER_PX))
        assert b["quality"] == {"bust": "estimated", "waist": "estimated", "hips": "estimated"}
        for field in ("bust", "waist", "hips"):
            assert b[field] == pytest.approx(200 * self.CM_PER_PX, abs=0.3)

    def test_arms_across_the_body_leave_the_field_unread(self):
        """Hands over the waist: nothing honest to measure there."""
        b = self.measure(body_mask(hourglass()), arm_segments(20, 2.0))
        assert b["waist"] is None and b["quality"]["waist"] is None


class TestCircumferences:
    def test_population_mean_breadths_give_population_mean_circumferences(self):
        c = circumferences_from_breadths({"bust": 26.93, "waist": 29.99, "hips": 35.38})
        assert c == {"bust": 94.7, "waist": 86.1, "hips": 102.1}

    def test_scales_linearly(self):
        one = circumferences_from_breadths({"bust": 30, "waist": 25, "hips": 35})
        two = circumferences_from_breadths({"bust": 60, "waist": 50, "hips": 70})
        for field in one:
            assert two[field] == pytest.approx(2 * one[field], abs=0.1)
