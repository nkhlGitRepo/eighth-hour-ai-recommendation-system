"""
Tests for MediaPipeSizingProvider.

Two layers, deliberately separated:

  * Landmarks + outline -> measurements. Driven by SYNTHETIC landmarks and a
    synthetic person mask of known widths, so the scale math, pose validation,
    outline measurement, plausibility bounds and Measurements construction are
    all covered deterministically without a 190 MB model or a photograph of a
    real person. This is where the success path is proven.

  * Real image handling. Runs the actual model against generated images to
    confirm non-people are rejected. Skipped automatically if mediapipe isn't
    installed, so the suite still passes on a machine without it.

Why no "real photo produces good measurements" test: MediaPipe will not detect
a drawn or synthesised figure (verified -- stick figures and noise both yield
zero poses), so such a test would need a licensed photograph of a real person
committed to the repo. The synthetic-landmark tests below cover the same code
path, and a human confirms the end-to-end result with their own photo.
"""

import io
import os
import types

import pytest

import numpy as np

import py_src.providers.anthropometry as A
from py_src.providers.mediapipe_sizing_provider import (
    MediaPipeSizingProvider,
    LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP, LEFT_ANKLE, RIGHT_ANKLE,
    LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST,
    LEFT_INDEX, RIGHT_INDEX, LEFT_PINKY, RIGHT_PINKY,
    BREADTH_LANDMARKS, SCALE_LANDMARKS,
)
from py_src.constants import BODY_SHAPE_CLASSES, MEASUREMENT_RANGES, STANDARD_SIZES
from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
from py_src.utils.errors import ModuleError


IMAGE_W, IMAGE_H = 800, 1400

# A well-framed standing pose in pixels, matching what MediaPipe actually
# emits for a real photo: shoulder span ~27% of the shoulder-to-ankle span
# (36cm of 132cm), and pelvis landmarks ~0.60 of the shoulder span. That 0.60
# is measured from real photos -- the hip landmarks are joint centres, so they
# sit well inside the body surface. Using a surface-anthropometry figure (~0.78)
# here is what let a too-strict ratio check ship and reject genuine photos.
# The hips sit at the anthropometric 0.385 of the shoulder-to-ankle span, and
# the arms hang a little away from the body, as the photo guidance asks.
STANDING = {
    LEFT_SHOULDER:  (509, 300),
    RIGHT_SHOULDER: (291, 300),
    LEFT_HIP:       (466, 608),
    RIGHT_HIP:      (334, 608),
    LEFT_ANKLE:     (462, 1100),
    RIGHT_ANKLE:    (338, 1100),
    LEFT_ELBOW:     (590, 470),
    RIGHT_ELBOW:    (210, 470),
    LEFT_WRIST:     (610, 640),
    RIGHT_WRIST:    (190, 640),
    LEFT_INDEX:     (615, 700),
    RIGHT_INDEX:    (185, 700),
    LEFT_PINKY:     (620, 690),
    RIGHT_PINKY:    (180, 690),
}

# Half-widths (px) of the synthetic body's outline at the bust, waist and hip
# lines. With STANDING at 170 cm (~0.166 cm/px) this is ~88/67/96 cm.
AVERAGE_BODY = (75, 70, 100)


def body_mask(points=None, body=AVERAGE_BODY):
    """
    A person mask for the given landmarks: torso half-widths step from bust to
    waist to hips at the anthropometric tape lines, legs below. Arms are not
    drawn -- they hang clear of the body, so they don't touch the outline.
    """
    points = points or STANDING
    bust, waist, hips = body
    shoulder_y = (points[LEFT_SHOULDER][1] + points[RIGHT_SHOULDER][1]) / 2
    hip_y = (points[LEFT_HIP][1] + points[RIGHT_HIP][1]) / 2
    mid_x = int(round(sum(points[i][0] for i in BREADTH_LANDMARKS) / 4))
    mask = np.zeros((IMAGE_H, IMAGE_W), dtype=bool)
    for y in range(int(shoulder_y), IMAGE_H):
        t = (y - shoulder_y) / (hip_y - shoulder_y) if hip_y != shoulder_y else 0
        half = bust if t < (A.BUST_LINE_T + A.NAVEL_LINE_T) / 2 else (
            waist if t < (A.NAVEL_LINE_T + A.SEAT_LINE_T) / 2 else hips)
        mask[y, max(0, mid_x - half):min(IMAGE_W, mid_x + half + 1)] = True
    return mask


def make_landmarks(points, visibility=0.99):
    """
    Build a 33-slot landmark list with normalized coords, matching what
    MediaPipe returns. Unspecified joints get a neutral centre position.
    """
    landmarks = []
    for index in range(33):
        x_px, y_px = points.get(index, (IMAGE_W / 2, IMAGE_H / 2))
        landmarks.append(
            types.SimpleNamespace(
                x=x_px / IMAGE_W,
                y=y_px / IMAGE_H,
                z=0.0,
                visibility=visibility,
                presence=visibility,
            )
        )
    return landmarks


def provider_with_landmarks(points, visibility=0.99, body=AVERAGE_BODY, landmarks=None):
    """
    Provider whose detection step is replaced by fixed landmarks and a
    synthetic outline, so everything downstream of the model is exercised for
    real.
    """
    provider = MediaPipeSizingProvider()
    landmarks = landmarks or make_landmarks(points, visibility)
    try:
        mask = body_mask(points, body)
    except (KeyError, ZeroDivisionError):
        mask = body_mask(STANDING, body)
    provider._detect_landmarks = lambda image_array: (landmarks, mask)
    provider._decode = lambda image_bytes: (None, IMAGE_W, IMAGE_H)
    return provider


def shifted(overrides):
    """STANDING with specific joints moved. Takes a dict because the landmark
    keys are integers, which ** can't accept."""
    points = dict(STANDING)
    points.update(overrides)
    return points


class TestStandingPoseProducesRealMeasurements:
    """The success path: a good standing pose yields plausible measurements."""

    def test_returns_plausible_measurements(self):
        provider = provider_with_landmarks(STANDING)
        m = provider.extract_from_image(b"fake-image-bytes", "image/jpeg", 170.0)

        assert 80 <= m.bust <= 95, m.bust
        assert 62 <= m.waist <= 78, m.waist
        assert 92 <= m.hips <= 108, m.hips
        assert m.hips > m.waist

    def test_output_passes_the_apps_validation_ranges(self):
        provider = provider_with_landmarks(STANDING)
        m = provider.extract_from_image(b"x", "image/jpeg", 170.0)
        for field in ("bust", "waist", "hips", "height"):
            low, high = MEASUREMENT_RANGES[field]
            assert low <= getattr(m, field) <= high

    def test_units_and_provenance(self):
        provider = provider_with_landmarks(STANDING)
        m = provider.extract_from_image(b"x", "image/jpeg", 170.0)
        assert m.unit == "cm"
        assert m.provider == "mediapipe_pose"
        assert "mediapipe" in m.provider_version

    def test_height_is_passed_through_untouched(self):
        provider = provider_with_landmarks(STANDING)
        assert provider.extract_from_image(b"x", "image/jpeg", 176.0).height == 176.0

    def test_stated_height_scales_the_measurements(self):
        """
        Same pixels, different stated height -> different measurements. This is
        the scale reference genuinely being used, not decoration.
        """
        provider = provider_with_landmarks(STANDING)
        short = provider.extract_from_image(b"x", "image/jpeg", 155.0)
        tall = provider.extract_from_image(b"x", "image/jpeg", 185.0)
        assert tall.bust > short.bust
        assert tall.hips > short.hips

    def test_different_bodies_give_different_measurements(self):
        """The core difference from the placeholder provider."""
        slim = provider_with_landmarks(STANDING, body=(65, 55, 85))
        full = provider_with_landmarks(STANDING, body=(95, 90, 115))

        a = slim.extract_from_image(b"x", "image/jpeg", 170.0)
        b = full.extract_from_image(b"x", "image/jpeg", 170.0)
        assert b.bust > a.bust and b.waist > a.waist and b.hips > a.hips

    def test_same_skeleton_fuller_body_reads_fuller(self):
        """
        The reported failure. The old estimator read only the skeleton, so two
        people with the same joints got the same numbers however full their
        figure -- a tester measuring 107/90/107 was told 82/66/92. The outline
        is what is measured now: identical landmarks, fuller outline, larger
        measurements, and a waist-to-hip ratio that follows the body.
        """
        slim = provider_with_landmarks(STANDING, body=(70, 55, 95))
        full = provider_with_landmarks(STANDING, body=(95, 85, 100))
        a = slim.extract_from_image(b"x", "image/jpeg", 165.0)
        b = full.extract_from_image(b"x", "image/jpeg", 165.0)
        assert b.bust > a.bust + 15
        assert b.waist > a.waist + 15
        assert a.waist / a.hips < 0.65 < 0.8 < b.waist / b.hips

    def test_confidence_reflects_landmark_visibility(self):
        clear = provider_with_landmarks(STANDING, visibility=0.99)
        hazy = provider_with_landmarks(STANDING, visibility=0.62)

        assert clear.extract_from_image(b"x", "image/jpeg", 170.0).min_confidence() > 0.9
        assert hazy.extract_from_image(b"x", "image/jpeg", 170.0).min_confidence() < 0.75

    def test_low_visibility_surfaces_as_low_confidence_fields(self):
        """So the UI routes the customer to double-check rather than trusting it."""
        hazy = provider_with_landmarks(STANDING, visibility=0.62)
        m = hazy.extract_from_image(b"x", "image/jpeg", 170.0)
        assert m.low_confidence_fields()


class TestRequiredInputs:
    def test_height_is_required(self):
        provider = provider_with_landmarks(STANDING)
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(b"x", "image/jpeg", None)
        assert "height" in exc.value.message.lower()

    def test_empty_image_rejected(self):
        provider = provider_with_landmarks(STANDING)
        with pytest.raises(ModuleError):
            provider.extract_from_image(b"", "image/jpeg", 170.0)

    def test_photo_ref_path_is_not_supported(self):
        """This provider needs pixels, not a reference -- and says so."""
        provider = MediaPipeSizingProvider()
        with pytest.raises(ModuleError) as exc:
            provider.extract_measurements("s3://bucket/photo.jpg", 170.0)
        assert "requires the uploaded image" in exc.value.message


class TestPoseValidation:
    """
    Detecting a body isn't enough -- the pose has to be one the anthropometry
    is valid for. Each of these produces confident landmarks that would yield
    silently wrong measurements.
    """

    def _expect_pose_rejection(self, points):
        provider = provider_with_landmarks(points)
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(b"x", "image/jpeg", 170.0)
        assert "stand upright" in exc.value.message
        return exc.value

    def test_rejects_wide_legged_stance(self):
        """MediaPipe's own sample pose.jpg is exactly this case."""
        self._expect_pose_rejection(shifted({LEFT_ANKLE: (740, 1100), RIGHT_ANKLE: (60, 1100)}))

    def test_rejects_rotated_torso(self):
        """A turned body collapses pelvis breadth relative to the shoulders."""
        self._expect_pose_rejection(shifted({LEFT_HIP: (440, 608), RIGHT_HIP: (360, 608)}))

    def test_rejects_tilted_shoulders(self):
        self._expect_pose_rejection(shifted({LEFT_SHOULDER: (509, 300), RIGHT_SHOULDER: (291, 420)}))

    def test_rejects_tilted_hips(self):
        self._expect_pose_rejection(shifted({LEFT_HIP: (485, 608), RIGHT_HIP: (315, 708)}))

    def test_rejects_upside_down_or_lying_body(self):
        """Ankles above hips means the person isn't standing."""
        self._expect_pose_rejection(shifted({LEFT_ANKLE: (480, 200), RIGHT_ANKLE: (320, 200)}))

    def test_rejects_partially_visible_body(self):
        provider = provider_with_landmarks(STANDING, visibility=0.2)
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(b"x", "image/jpeg", 170.0)
        assert "full-body" in exc.value.message

    def test_rejects_an_implausible_vertical_scale(self):
        """
        Ankles collapsed up toward the knees shrink the span, inflating every
        measurement. This is the check that replaced gating on ankle
        visibility -- it catches a wrong scale directly.
        """
        self._expect_pose_rejection(shifted({
            LEFT_ANKLE: (462, 700), RIGHT_ANKLE: (338, 700)}))

    def test_accepts_a_slight_natural_lean(self):
        """Validation must not be so strict that normal photos fail."""
        provider = provider_with_landmarks(shifted({LEFT_SHOULDER: (509, 300), RIGHT_SHOULDER: (291, 325)}))
        assert provider.extract_from_image(b"x", "image/jpeg", 170.0).bust > 0


class TestAnkleVisibilityDoesNotBlockMeasurement:
    """
    Regression: ankles are only used for the vertical scale, and MediaPipe
    extrapolates their position well even when the feet are cropped, shadowed or
    hidden by long clothing. Measured across six real photos the shoulder:span
    ratio stayed within 0.24-0.30 whether ankle visibility was 0.05 or 0.54 --
    so gating on it rejected ordinary full-body photos whose measurements were
    perfectly plausible.
    """

    def _low_ankle_visibility(self, ankle_visibility):
        landmarks = make_landmarks(STANDING, visibility=0.99)
        for index in SCALE_LANDMARKS:
            landmarks[index].visibility = ankle_visibility
        provider = provider_with_landmarks(STANDING, landmarks=landmarks)
        return provider

    @pytest.mark.parametrize("ankle_visibility", [0.54, 0.41, 0.11, 0.05, 0.0])
    def test_barely_visible_ankles_still_measure(self, ankle_visibility):
        m = self._low_ankle_visibility(ankle_visibility).extract_from_image(
            b"x", "image/jpeg", 170.0)
        assert m.bust > 0 and m.waist > 0 and m.hips > 0

    def test_but_the_result_is_flagged_for_review(self):
        """Accepted is not the same as trusted -- uncertainty is surfaced."""
        m = self._low_ankle_visibility(0.2).extract_from_image(b"x", "image/jpeg", 170.0)
        assert m.low_confidence_fields()

    def test_breadth_landmarks_are_still_strictly_required(self):
        """Shoulders and hips supply the actual widths, so they must be seen."""
        landmarks = make_landmarks(STANDING, visibility=0.99)
        for index in BREADTH_LANDMARKS:
            landmarks[index].visibility = 0.2
        provider = provider_with_landmarks(STANDING, landmarks=landmarks)
        with pytest.raises(ModuleError):
            provider.extract_from_image(b"x", "image/jpeg", 170.0)


class TestEstimatesOutsideRangeAreClampedNotRejected:
    """
    A single frontal photo cannot pin down circumferences: hip landmarks are
    joint centres, so estimates often land just under the app's floor. Refusing
    those photos outright meant refusing ordinary full-body shots. They are now
    nudged into range and flagged for the customer to check.
    """

    def _narrow_pelvis(self):
        # An outline narrow enough that waist/hips fall under the app's floor,
        # but not so far that the scale is judged broken, so we actually reach
        # the clamping code.
        return provider_with_landmarks(STANDING, body=(70, 45, 60))

    def test_slightly_low_estimate_is_accepted(self):
        m = self._narrow_pelvis().extract_from_image(b"x", "image/jpeg", 170.0)
        assert m.waist > 0 and m.hips > 0

    def test_clamped_values_land_inside_the_supported_range(self):
        m = self._narrow_pelvis().extract_from_image(b"x", "image/jpeg", 170.0)
        for field in ("bust", "waist", "hips"):
            low, high = MEASUREMENT_RANGES[field]
            assert low <= getattr(m, field) <= high

    def test_clamped_fields_are_flagged_for_review(self):
        """
        This is what routes the customer to the measurements screen with the
        "double-check these" note instead of silently trusting the estimate.
        """
        m = self._narrow_pelvis().extract_from_image(b"x", "image/jpeg", 170.0)
        flagged = m.low_confidence_fields()
        assert "hips" in flagged or "waist" in flagged

    def test_a_good_estimate_is_not_flagged(self):
        """Clamping must not fire for a photo that measures plausibly."""
        m = provider_with_landmarks(STANDING).extract_from_image(b"x", "image/jpeg", 170.0)
        assert m.low_confidence_fields() == []


class TestImplausibleResultsRejected:
    def test_absurd_proportions_are_refused_with_guidance(self):
        """
        A wildly-off estimate means the scale is broken, not merely imprecise --
        that still fails rather than being clamped into looking reasonable.
        """
        # Shoulders/pelvis enormous relative to the vertical span.
        provider = provider_with_landmarks({
            LEFT_SHOULDER: (780, 600), RIGHT_SHOULDER: (20, 600),
            LEFT_HIP: (700, 700), RIGHT_HIP: (100, 700),
            LEFT_ANKLE: (620, 760), RIGHT_ANKLE: (180, 760),
        })
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(b"x", "image/jpeg", 170.0)
        assert "don't look right" in exc.value.message or "stand upright" in exc.value.message


class TestDisclosure:
    def test_declares_that_it_really_analyses_the_image(self):
        d = MediaPipeSizingProvider().disclosure
        assert d["derives_from_image"] is True

    def test_declares_local_processing_and_no_retention(self):
        d = MediaPipeSizingProvider().disclosure
        assert d["sends_image_offsite"] is False
        assert d["stores_image"] is False
        assert d["retention"].strip()

    def test_names_the_underlying_model_for_transparency(self):
        assert "mediapipe" in MediaPipeSizingProvider().disclosure["processor_name"].lower()


class TestModelIsLazilyLoaded:
    def test_constructing_does_not_load_the_model(self):
        """
        ~200 MB of RAM must not be paid for at import/boot, only on first real
        use -- otherwise the mock path and the test suite carry the cost too.
        """
        assert MediaPipeSizingProvider()._landmarker is None


# --- Real-model tests (need mediapipe installed) --------------------------

mediapipe = pytest.importorskip("mediapipe", reason="mediapipe not installed")

# MediaPipe inference deadlocks when run inside pytest on this setup (verified:
# the identical calls complete in ~1s in a standalone interpreter, but hang
# indefinitely under pytest regardless of -s / -p no:faulthandler). Rather than
# hang CI, these are skipped by default and the same assertions are executed by
# scripts/verify_pose_provider.py, which runs the real model in its own process.
# Set RUN_MEDIAPIPE_MODEL_TESTS=1 to attempt them here anyway.
_MODEL_TESTS_ENABLED = os.environ.get("RUN_MEDIAPIPE_MODEL_TESTS") == "1"
pytestmark_model = pytest.mark.skipif(
    not _MODEL_TESTS_ENABLED,
    reason="MediaPipe inference deadlocks under pytest; use scripts/verify_pose_provider.py",
)


def _jpeg(image):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


@pytestmark_model
class TestRealModelRejectsNonPeople:
    """
    The behaviour that motivated this provider: a photo with no person in it
    must fail loudly instead of returning fixed numbers.
    """

    @pytest.fixture(scope="class")
    def provider(self):
        return MediaPipeSizingProvider()

    def test_rejects_random_noise(self, provider):
        import numpy as np
        from PIL import Image

        rng = np.random.default_rng(1234)
        noise = Image.fromarray(rng.integers(0, 255, (480, 320, 3), dtype=np.uint8))
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(_jpeg(noise), "image/jpeg", 170.0)
        assert "couldn't find a person" in exc.value.message.lower()

    def test_rejects_a_flat_colour_image(self, provider):
        from PIL import Image

        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(
                _jpeg(Image.new("RGB", (400, 600), (120, 140, 200))), "image/jpeg", 170.0
            )
        assert "couldn't find a person" in exc.value.message.lower()

    def test_rejects_undecodable_bytes(self, provider):
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(b"\xff\xd8\xff\xe0 not really a jpeg", "image/jpeg", 170.0)
        assert "couldn't read" in exc.value.message.lower()


class TestEveryStoredFieldIsWithinTheSupportedRange:
    """
    Regression: `shoulder` was computed and stored but never clamped, so a photo
    could persist a value outside MEASUREMENT_RANGES. Nothing sizes on shoulder,
    so the scan looked fine -- and then M9 (new releases) and M7 (fit check),
    which validate every field they are given, refused that customer's session
    with a 400 while M5 (recommendations), which does not validate shoulder,
    carried on working. The customer saw "complete your style profile" on a
    profile they had plainly completed.
    """

    @pytest.mark.parametrize("height", [140.0, 150.0, 170.0, 190.0, 210.0])
    def test_no_field_is_ever_stored_outside_its_supported_range(self, height):
        provider = provider_with_landmarks(STANDING)
        m = provider.extract_from_image(b"x", "image/jpeg", height)
        for field in ("bust", "waist", "hips", "shoulder"):
            value = getattr(m, field)
            if value is None:
                continue
            low, high = MEASUREMENT_RANGES[field]
            assert low <= value <= high, (
                f"{field}={value} is outside {low}-{high}; every module that "
                f"validates its input will reject this session"
            )

    def test_a_short_subject_still_yields_a_valid_shoulder(self):
        """The case that broke in production: a small frame put the shoulder
        estimate under the 30cm floor."""
        provider = provider_with_landmarks(STANDING)
        m = provider.extract_from_image(b"x", "image/jpeg", 140.0)
        low, high = MEASUREMENT_RANGES["shoulder"]
        assert low <= m.shoulder <= high

    def test_a_poor_shoulder_estimate_does_not_reject_the_whole_photo(self):
        """Shoulder is optional and nothing sizes on it, so it is clamped rather
        than being grounds for refusing an otherwise usable photo."""
        provider = provider_with_landmarks(STANDING)
        assert provider.extract_from_image(b"x", "image/jpeg", 140.0) is not None


class TestStatedSizesSteadyTheEstimate:
    """
    The customer's usual sizes are a much stronger signal than the photo.
    Measured against real ground truth (two subjects, six photos), mean absolute
    error was:

        photo alone        bust 15.7  waist  8.7  hips 16.9  overall 13.8 cm
        single size         bust  5.7  waist  8.7  hips 16.9  overall 10.5 cm
        top + bottom size   bust  5.7  waist 11.9  hips  4.2  overall  7.3 cm

    Top and bottom are separate because people are commonly different sizes
    above and below the waist -- both ground-truth subjects were.
    """

    def test_top_size_anchors_the_bust(self):
        from py_src.constants import STANDARD_SIZE_CHART

        provider = provider_with_landmarks(STANDING)
        without = provider.extract_from_image(b"x", "image/jpeg", 170.0)
        with_top = provider.extract_from_image(b"x", "image/jpeg", 170.0, "L")
        chart = STANDARD_SIZE_CHART["L"]
        assert abs(with_top.bust - chart["bust"]) < abs(without.bust - chart["bust"])

    def test_top_size_alone_leaves_waist_and_hips_to_the_photo(self):
        """A customer who knows only their top size still benefits, without
        waist/hips being invented from an unrelated size."""
        provider = provider_with_landmarks(STANDING)
        photo_only = provider.extract_from_image(b"x", "image/jpeg", 170.0)
        top_only = provider.extract_from_image(b"x", "image/jpeg", 170.0, "L")
        assert top_only.bust != photo_only.bust
        assert top_only.waist == photo_only.waist
        assert top_only.hips == photo_only.hips

    def test_bottom_size_anchors_waist_and_hips_only(self):
        provider = provider_with_landmarks(STANDING)
        photo_only = provider.extract_from_image(b"x", "image/jpeg", 170.0)
        bottom_only = provider.extract_from_image(
            b"x", "image/jpeg", 170.0, None, "XL")
        assert bottom_only.bust == photo_only.bust
        assert bottom_only.waist != photo_only.waist
        assert bottom_only.hips != photo_only.hips

    def test_different_top_and_bottom_sizes_are_both_honoured(self):
        """The whole point of splitting them: a top-S/bottom-L body must not be
        forced onto one chart row."""
        from py_src.constants import STANDARD_SIZE_CHART

        provider = provider_with_landmarks(STANDING)
        m = provider.extract_from_image(b"x", "image/jpeg", 170.0, "S", "XL")
        assert abs(m.bust - STANDARD_SIZE_CHART["S"]["bust"]) < 12
        assert abs(m.hips - STANDARD_SIZE_CHART["XL"]["hips"]) < 12

    def test_photo_still_influences_the_result(self):
        """Two different bodies with identical stated sizes must not collapse to
        the same numbers -- otherwise the photo is decoration."""
        narrow = provider_with_landmarks(STANDING, body=(70, 70, 100))
        broad = provider_with_landmarks(STANDING, body=(85, 70, 100))
        a = narrow.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")
        b = broad.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")
        assert a.bust != b.bust

    def test_photo_still_influences_waist_and_hips(self):
        wide_pelvis = provider_with_landmarks(STANDING, body=(75, 75, 110))
        narrow_pelvis = provider_with_landmarks(STANDING)
        a = wide_pelvis.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")
        b = narrow_pelvis.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")
        assert a.hips != b.hips

    @pytest.mark.parametrize("stated", STANDARD_SIZES)
    def test_stated_size_survives_the_round_trip(self, stated):
        """
        The reported bug: selecting "M tops" and being recommended S.

        Asserted through M3's REAL recommender rather than by re-deriving the
        lookup here, because the guarantee that matters is about the size the
        customer is actually shown. The photo may refine the estimate inside the
        stated band, but it must never move it into a neighbouring size.
        """
        profiler = BodyShapeProfiler()

        # Height is swept rather than the landmarks, because every measurement
        # scales linearly with it -- so this spans a photo reading far smaller
        # than stated (the direction this estimator is biased, and the case that
        # produced the bug) through to far larger, while the pose stays a valid
        # one the provider will actually accept.
        for height in (140.0, 170.0, 210.0):
            label = f"height {height:.0f}"
            m = provider_with_landmarks(STANDING).extract_from_image(
                b"x", "image/jpeg", height, stated, stated)
            # Every shape class, because "apple" deliberately sizes tops from
            # the waist instead of the bust -- the guarantee has to hold there
            # too, not just on the common path.
            for shape_class in BODY_SHAPE_CLASSES:
                sizes = profiler._recommend_sizes(
                    shape_class, m.bust, m.waist, m.hips)
                assert sizes["tops"] == stated, (
                    f"{label}/{shape_class}: stated top {stated} but recommender "
                    f"said {sizes['tops']} (bust {m.bust}, waist {m.waist})")
                assert sizes["trousers"] == stated, (
                    f"{label}/{shape_class}: stated bottom {stated} but "
                    f"recommender said {sizes['trousers']} (hips {m.hips})")

    @pytest.mark.parametrize("stated", STANDARD_SIZES)
    def test_photo_still_moves_the_number_even_when_it_reads_far_off(self, stated):
        """
        The trap in holding the value inside the stated band: if it CLIPS at the
        edge, then every photo that reads far outside the band lands on the same
        edge value, and the photo silently stops mattering for exactly the people
        it reads worst. Verified against real photos -- one subject's three
        photos all clipped to an identical result before this was squashed
        instead. Distinct photos must stay distinct.
        """
        from py_src.constants import STANDARD_SIZE_CHART

        # A body proportioned to the stated size: a customer stating XXL whose
        # photo reads like an average M is a contradiction the blend rightly
        # saturates on, and that's not what this test is about.
        scale = STANDARD_SIZE_CHART[stated]["waist"] / STANDARD_SIZE_CHART["M"]["waist"]
        provider = provider_with_landmarks(
            STANDING, body=tuple(int(round(h * scale)) for h in AVERAGE_BODY))
        # Spread across the accepted height range, so each reading differs by
        # more than the 0.1cm the result is rounded to. The lower heights all
        # read well BELOW the larger bands and the upper heights well above, so
        # every size has several inputs sitting in the saturating region -- which
        # is precisely where clipping erased the difference.
        results = [
            provider.extract_from_image(b"x", "image/jpeg", h, stated, stated)
            for h in (140.0, 155.0, 170.0, 185.0, 200.0)
        ]
        for field in ("bust", "waist", "hips"):
            values = [getattr(m, field) for m in results]
            assert values == sorted(values), (
                f"stated {stated}: {field} not monotonic in the photo estimate "
                f"({values})")
            assert values[-1] - values[0] > 0.5, (
                f"stated {stated}: {field} barely moved across the whole height "
                f"range ({values}) -- the photo has stopped affecting the result")

    @pytest.mark.parametrize("stated", STANDARD_SIZES)
    @pytest.mark.parametrize("field", ["bust", "waist", "hips"])
    def test_band_blend_is_strictly_monotonic(self, stated, field):
        """
        The exact property that stops the collapse above, asserted on the blend
        itself rather than on the rounded output: no two photo estimates, however
        far outside the band they fall, may map to the same value. A clip fails
        this immediately; a squash cannot fail it at any distance.
        """
        blend = MediaPipeSizingProvider._blend_within_stated_band
        previous = None
        for photo_value in range(40, 181, 5):
            value = blend(float(photo_value), field, stated)
            if previous is not None:
                assert value > previous, (
                    f"{field}/{stated}: photo {photo_value}cm mapped to "
                    f"{value}, not above the previous {previous}")
            previous = value

    def test_unanchored_fields_are_not_held_to_any_band(self):
        """Holding applies only where the customer stated something. Waist/hips
        with no bottom size given must stay exactly what the photo said."""
        provider = provider_with_landmarks(STANDING)
        photo_only = provider.extract_from_image(b"x", "image/jpeg", 170.0)
        top_only = provider.extract_from_image(b"x", "image/jpeg", 170.0, "M")
        assert top_only.waist == photo_only.waist
        assert top_only.hips == photo_only.hips

    @pytest.mark.parametrize("size", ["m", " M ", "xl"])
    def test_size_input_is_normalised(self, size):
        provider = provider_with_landmarks(STANDING)
        assert provider.extract_from_image(b"x", "image/jpeg", 170.0, size, size).bust > 0

    @pytest.mark.parametrize("bad", [None, "", "not-a-size", "42"])
    def test_unusable_sizes_fall_back_to_photo_only(self, bad):
        provider = provider_with_landmarks(STANDING)
        photo_only = provider.extract_from_image(b"x", "image/jpeg", 170.0)
        result = provider.extract_from_image(b"x", "image/jpeg", 170.0, bad, bad)
        assert result.bust == photo_only.bust
        assert result.hips == photo_only.hips

    def test_only_anchored_fields_get_the_confidence_lift(self):
        """
        An unanchored field still rests on the photo, so it must stay flagged --
        otherwise a top-size-only customer would be told their hips are reliable.
        """
        landmarks = make_landmarks(STANDING, visibility=0.99)
        for index in SCALE_LANDMARKS:
            landmarks[index].visibility = 0.2
        provider = provider_with_landmarks(STANDING, landmarks=landmarks)

        top_only = provider.extract_from_image(b"x", "image/jpeg", 170.0, "M")
        flagged = top_only.low_confidence_fields()
        assert "bust" not in flagged
        assert "waist" in flagged and "hips" in flagged

        both = provider.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")
        assert both.low_confidence_fields() == []


class TestOutlineIsForgivingOfOrdinaryPhotos:
    """
    Most people stand with their arms by their sides, and many photos stop
    above the feet. Refusing those would make the feature unusable, so neither
    is a reason to refuse -- only a photo with nothing usable in it is.
    """

    def test_feet_out_of_frame_still_measures(self):
        """Ankles guessed below the bottom edge: scale comes from the torso."""
        points = shifted({LEFT_ANKLE: (462, 1450), RIGHT_ANKLE: (338, 1450)})
        landmarks = make_landmarks(points)
        provider = provider_with_landmarks(STANDING, landmarks=landmarks)
        framed = provider_with_landmarks(STANDING).extract_from_image(b"x", "image/jpeg", 170.0)
        cropped = provider.extract_from_image(b"x", "image/jpeg", 170.0)
        for field in ("bust", "waist", "hips"):
            assert getattr(cropped, field) == pytest.approx(getattr(framed, field), rel=0.05)

    def test_arms_against_the_sides_still_measure(self):
        """Arms drawn touching the torso at every row: cut away, not refused."""
        mask = body_mask()
        for y in range(300, IMAGE_H):
            for centre in (400 - 75 - 25, 400 + 75 + 25):     # touching the bust edge
                mask[y, centre - 25:centre + 26] = True
        landmarks = make_landmarks(shifted({
            LEFT_ELBOW: (500, 470), RIGHT_ELBOW: (300, 470),
            LEFT_WRIST: (500, 640), RIGHT_WRIST: (300, 640),
            LEFT_INDEX: (500, 700), RIGHT_INDEX: (300, 700),
            LEFT_PINKY: (500, 690), RIGHT_PINKY: (300, 690)}))
        provider = MediaPipeSizingProvider()
        provider._detect_landmarks = lambda image_array: (landmarks, mask)
        provider._decode = lambda image_bytes: (None, IMAGE_W, IMAGE_H)
        m = provider.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")
        assert m.bust > 0 and m.waist > 0 and m.hips > 0


class TestWhenTheOutlineIsHidden:
    """Hands across the body hide the waist and hips."""

    def _hands_on_hips(self):
        return provider_with_landmarks(shifted({
            LEFT_ELBOW: (560, 470), RIGHT_ELBOW: (240, 470),
            LEFT_WRIST: (420, 520), RIGHT_WRIST: (380, 520),
            LEFT_INDEX: (405, 760), RIGHT_INDEX: (395, 760),
            LEFT_PINKY: (405, 750), RIGHT_PINKY: (395, 750)}))

    def test_hidden_fields_take_the_stated_size(self):
        from py_src.constants import STANDARD_SIZE_CHART
        m = self._hands_on_hips().extract_from_image(b"x", "image/jpeg", 170.0, "M", "L")
        assert m.hips == pytest.approx(STANDARD_SIZE_CHART["L"]["hips"], abs=0.1)

    def test_without_a_stated_size_the_photo_is_refused_with_guidance(self):
        with pytest.raises(ModuleError) as exc:
            self._hands_on_hips().extract_from_image(b"x", "image/jpeg", 170.0)
        assert "arms held slightly away" in exc.value.message

    def test_nothing_readable_is_refused(self):
        provider = MediaPipeSizingProvider()
        landmarks = make_landmarks(STANDING)
        empty = np.zeros((IMAGE_H, IMAGE_W), dtype=bool)
        provider._detect_landmarks = lambda image_array: (landmarks, empty)
        provider._decode = lambda image_bytes: (None, IMAGE_W, IMAGE_H)
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")
        assert "arms" in exc.value.message


class TestImagesAreAnalysedAtASafeSize:
    """
    A phone photo can be 4000 x 6000 (its float mask alone ~100 MB on a 512 MB
    server), and MediaPipe aborts the whole process copying out the mask of an
    image whose width needs row padding -- seen on an ordinary 475-px JPEG.
    """

    @pytest.mark.parametrize("size", [(475, 723), (3695, 5542), (1281, 640), (17, 40)])
    def test_decoded_width_is_aligned_and_bounded(self, size):
        from PIL import Image
        from py_src.providers.mediapipe_sizing_provider import (
            ANALYSIS_LONGEST_SIDE_PX, ANALYSIS_WIDTH_MULTIPLE)
        buffer = io.BytesIO()
        Image.new("RGB", size, (120, 140, 200)).save(buffer, format="JPEG")
        array, width, height = MediaPipeSizingProvider()._decode(buffer.getvalue())
        assert width % ANALYSIS_WIDTH_MULTIPLE == 0
        assert max(width, height) <= ANALYSIS_LONGEST_SIDE_PX + ANALYSIS_WIDTH_MULTIPLE
        assert array.shape[:2] == (height, width)
        assert array.flags["C_CONTIGUOUS"]
        # Proportions kept to within the alignment rounding.
        assert height / width == pytest.approx(size[1] / size[0], rel=0.15)


class TestHeadMustBeInTheFrame:
    """
    A photo cropped at the chest still gets a confident nose landmark --
    invented at the very top edge -- and shoulders placed wherever the model
    guesses. Seen on real catalog detail shots, which both the old estimator and
    the outline one were measuring.
    """

    def test_nose_on_the_top_edge_is_refused(self):
        from py_src.providers.mediapipe_sizing_provider import NOSE
        provider = provider_with_landmarks(shifted({NOSE: (400, 8)}))
        with pytest.raises(ModuleError) as exc:
            provider.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")
        assert "head down" in exc.value.message

    def test_nose_outside_the_frame_is_refused(self):
        from py_src.providers.mediapipe_sizing_provider import NOSE
        provider = provider_with_landmarks(shifted({NOSE: (400, -40)}))
        with pytest.raises(ModuleError):
            provider.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M")

    def test_a_normally_framed_head_is_fine(self):
        from py_src.providers.mediapipe_sizing_provider import NOSE
        provider = provider_with_landmarks(shifted({NOSE: (400, 200)}))
        assert provider.extract_from_image(b"x", "image/jpeg", 170.0, "M", "M").bust > 0
