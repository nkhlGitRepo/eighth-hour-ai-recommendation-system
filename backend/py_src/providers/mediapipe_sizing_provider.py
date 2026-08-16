"""
MediaPipe Pose sizing provider.

A free, local SizingProvider that genuinely analyses the uploaded photo:
Google's MediaPipe pose model finds body landmarks, those are scaled to real
centimetres using the customer's stated height, and converted to bust/waist/
hip circumferences by py_src/providers/anthropometry.py.

Unlike MockSizingProvider, output depends on the actual image -- two different
people produce different measurements, and a photo with no recognisable person
in it (a car, a landscape) is rejected rather than silently measured.

Trade-offs, stated plainly:
  - Free and runs entirely on this server: no API key, no rate limit, no
    third-party transmission. Costs ~350 MB of dependencies and ~200 MB RAM.
  - Accuracy is approximate. Circumference from a single frontal photo relies
    on population-average ratios (see anthropometry.py). It is better than a
    guess and genuinely responsive to the customer's proportions, but it is
    not a tape measure or a 3D scan. A paid vendor doing real 3D
    reconstruction would be materially more accurate -- swapping one in is a
    single registry entry (see README_PYTHON.md).
"""

import math
import os
import threading
import urllib.request

from py_src.modules.m2_sizing_integration import Measurements, SizingProvider
from py_src.providers.anthropometry import (
    measurements_from_breadths,
    pixels_to_cm_scale,
)
from py_src.constants import (
    HIP_SIZE_BOUNDARIES,
    MEASUREMENT_RANGES,
    SIZE_BOUNDARIES,
    STANDARD_SIZE_CHART,
    WAIST_SIZE_BOUNDARIES,
)
from py_src.utils.errors import ModuleError
from py_src.utils.logger import logger


# MediaPipe pose landmark indices (33-point BlazePose topology).
NOSE = 0
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_ANKLE, RIGHT_ANKLE = 27, 28

# Visibility requirements differ by what a landmark is used FOR.
#
# Shoulders and hips supply the horizontal breadths that become measurements,
# so they genuinely have to be seen -- a guessed position here corrupts the
# result directly.
BREADTH_LANDMARKS = (LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP)
MIN_LANDMARK_VISIBILITY = 0.5

# Ankles are used only for the VERTICAL scale reference, and MediaPipe
# extrapolates their position well even when the feet are cropped, shadowed or
# hidden by long clothing. Measured across six real photos, the
# shoulder:span ratio stayed within 0.24-0.30 whether ankle visibility was 0.05
# or 0.54 -- so a low visibility score here means "I can't see the feet", not
# "my estimate is wrong". Gating on it at 0.5 rejected ordinary full-body
# fashion photos whose measurements were perfectly plausible. The scale is
# instead validated directly, by the ratio band below.
# No visibility floor at all: the ratio band below checks the scale directly and
# catches both failure directions (ankles collapsed upward toward the knees
# pushes the ratio above the band; ankles thrown off-frame pushes it below), so
# a confidence score adds nothing except false rejections. Low ankle visibility
# still flows into the per-measurement confidence, so such a result is flagged
# for the customer to check rather than silently trusted.
SCALE_LANDMARKS = (LEFT_ANKLE, RIGHT_ANKLE)

# Plausible band for shoulder breadth as a fraction of the shoulder-to-ankle
# span. A real standing body sits near 0.27 (measured: 0.24-0.30 across six
# photos). Well outside this means the ankle estimate is genuinely wrong -- e.g.
# landmarks collapsed onto the knees, or placed far off-frame -- which is the
# failure that actually matters for scale, and this catches it directly instead
# of inferring it from a confidence score.
MIN_SHOULDER_TO_SPAN_RATIO = 0.18
MAX_SHOULDER_TO_SPAN_RATIO = 0.40

# --- Pose plausibility -----------------------------------------------------
#
# The anthropometry only holds for someone standing upright and square to the
# camera. Detecting a person is not enough: a lunge, a yoga pose, a seated or
# rotated body all produce landmarks that are individually confident but
# geometrically wrong for this math. MediaPipe's own sample pose.jpg is a
# wide-legged stance, and it yields hips *narrower* than the bust because the
# splayed legs foreshorten the vertical span and the turned pelvis collapses
# its breadth -- numbers that look real and aren't. These bounds refuse such
# photos rather than quietly reporting distorted measurements.

# Each ankle should sit roughly under its hip. Normalised by SHOULDER breadth,
# not pelvis breadth: the pelvis landmark span is small and noisy, so dividing
# by it amplified jitter and rejected ordinary photos. Measured references:
# feet together ~0.0, feet at shoulder width ~0.19, a deliberately wide stance
# ~0.4, and MediaPipe's wide-legged sample pose.jpg 2.1.
MAX_ANKLE_OFFSET_OVER_SHOULDER_BREADTH = 0.8

# Shoulders and hips should be near-level. Both tilts are measured against
# shoulder breadth (the most reliably-detected span) for the same reason.
MAX_TILT_OVER_BREADTH = 0.35

# Pelvis-landmark breadth relative to shoulder breadth. Because the hip
# landmarks are joint centres, real standing photos measure ~0.55-0.65 here --
# NOT the 0.75-0.9 that surface anthropometry suggests. A 0.60 floor rejected
# perfectly good photos. The band below still catches a torso rotated far
# enough to collapse the pelvis span, while the ankle-splay check above is what
# actually identifies an unusable stance.
MIN_PELVIS_SHOULDER_RATIO = 0.42
MAX_PELVIS_SHOULDER_RATIO = 0.95

# How far outside the app's supported measurement range an estimate may fall
# before it's treated as a broken scale rather than ordinary imprecision,
# expressed as a fraction of the range's width.
OUT_OF_RANGE_SLACK = 0.45

# Confidence assigned to a field that had to be clamped into range. Must sit
# below the 0.75 low-confidence threshold so the customer is prompted to check
# it rather than trusting it.
ADJUSTED_FIELD_CONFIDENCE = 0.4

# --- Steadying the estimate with stated sizes -------------------------------
#
# When the customer tells us the sizes they usually wear, the standard size
# chart becomes a far better anchor than the photo. Measured against real
# ground truth for two subjects across six photos:
#
#                      bust    waist   hips   overall
#   photo alone        15.7      8.7   16.9    13.8 cm mean absolute error
#   single size         2.2     15.8    4.2     7.4 cm
#   top + bottom size   2.2     15.8    1.8     6.6 cm
#
# Top and bottom are taken separately because many people are genuinely
# different sizes above and below the waist -- both ground-truth subjects were
# (top S/bottom XS and top M/bottom L). Forcing one chart row to describe the
# whole body is what cost 2.4cm of hip accuracy.
#
# The photo is weighted LOW, not high. It individualises the estimate a
# little without letting its noise (30% within-person variance across photos of
# the same body) undo a much better prior.
#
# Deliberately a single conservative weight rather than per-field weights fitted
# to the data: the waist figure above suggests a heavy photo weight would help
# waist specifically, but both subjects happen to be unusually slim-waisted AND
# this estimator is biased low, so that "improvement" may be coincidence rather
# than signal. Fitting 0.70 to two people would be overfitting, and would drag
# an average-waisted customer's estimate downward.
PHOTO_WEIGHT_WITH_STATED_SIZE = 0.25

# The blend is then held inside the size band the customer actually named.
#
# Without this, the feature contradicted its own input. A size band is only
# 6-8cm wide, so at a 0.25 weight the photo needs to disagree by just 12-16cm to
# push the blend across a boundary -- and this estimator is biased low by about
# that much on bust. The observable result was a customer selecting "M tops" and
# being recommended S: the anchor by itself round-trips correctly for every
# size, so the blend alone caused it.
#
# A stated size is evidence from garments the customer has actually worn. The
# photo is an estimate from a 5.5MB pose model. So the stated size decides WHICH
# size, and the photo still moves the number around inside it -- which is what
# feeds shape classification and per-garment fit scoring, where centimetres
# inside a band genuinely matter.
#
# The adjustment is SQUASHED into the band with tanh rather than clipped at its
# edge. A plain clip looked equivalent but quietly destroyed the photo's
# contribution for exactly the customers whose photo reads worst: all three test
# photos of one subject sat far enough below her stated band that every one
# clipped to the same edge value, making her result identical regardless of the
# photo. tanh is monotonic, so every distinct photo still yields a distinct
# number, and it only saturates asymptotically -- so the band is approached but
# never crossed. For ordinary disagreements tanh(x) ~ x, meaning this leaves the
# straightforward linear blend intact and only engages where clipping would have.
#
# No fitted constants: the squash scale is the band's own remaining width.
#
# The margin keeps the value below the band's exclusive upper edge, since size
# lookup tests `low <= value < high`.
STATED_SIZE_BAND_MARGIN_CM = 0.1

# Which boundary table governs each anchored field. Same tables M3/M5/M7/M9 use,
# so "held inside the stated band" means the same band the recommender reads.
BOUNDARIES_BY_FIELD = {
    "bust": SIZE_BOUNDARIES,
    "waist": WAIST_SIZE_BOUNDARIES,
    "hips": HIP_SIZE_BOUNDARIES,
}

# Floor on confidence once the estimate is anchored on a stated size. Above the
# 0.75 review threshold, because a chart-anchored figure is genuinely more
# reliable than a photo-only one -- but not 1.0, since it is still an estimate.
ANCHORED_FIELD_CONFIDENCE = 0.8

# The lite model is 5.5 MB and plenty for still photos ("full" is 9 MB,
# "heavy" 29 MB, both slower for marginal gain on a single frame).
DEFAULT_MODEL_VARIANT = "lite"
MODEL_URL_TEMPLATE = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_{variant}/float16/1/pose_landmarker_{variant}.task"
)


def default_model_path(variant: str = DEFAULT_MODEL_VARIANT) -> str:
    """Where the .task model is cached (backend/models/), overridable by env."""
    override = os.environ.get("MEDIAPIPE_POSE_MODEL")
    if override:
        return override
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(backend_root, "models", f"pose_landmarker_{variant}.task")


def ensure_model(path: str = None, variant: str = DEFAULT_MODEL_VARIANT) -> str:
    """
    Return a local path to the pose model, downloading it once if absent.

    The model is a build artifact, not source: it's fetched from Google's CDN
    on first use and cached. For a reproducible/offline deploy, commit or bake
    the file in and point MEDIAPIPE_POSE_MODEL at it.
    """
    path = path or default_model_path(variant)
    if os.path.exists(path):
        return path

    os.makedirs(os.path.dirname(path), exist_ok=True)
    url = MODEL_URL_TEMPLATE.format(variant=variant)
    logger.info("Downloading MediaPipe pose model", {"variant": variant, "path": path})
    try:
        # Download to a temp name first so an interrupted fetch can't leave a
        # truncated model that then fails confusingly on every later request.
        tmp = f"{path}.partial"
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, path)
    except Exception as err:
        raise ModuleError(
            f"Could not download the pose model ({err}). Set MEDIAPIPE_POSE_MODEL "
            f"to a local copy of pose_landmarker_{variant}.task.",
            "M2",
        )
    return path


class MediaPipeSizingProvider(SizingProvider):
    """Estimates measurements from a photo using local MediaPipe pose detection."""

    def __init__(self, model_path: str = None, variant: str = DEFAULT_MODEL_VARIANT):
        self._model_path = model_path
        self._variant = variant
        self._landmarker = None
        # The model costs ~200 MB resident, so it is loaded on first real use
        # rather than at construction: importing this module, running the test
        # suite, or booting with a different provider selected must not pay
        # for it. The lock keeps two concurrent requests from loading twice.
        self._lock = threading.Lock()
        logger.info("MediaPipeSizingProvider initialized (model loads on first use)")

    # -- model lifecycle --------------------------------------------------

    def _get_landmarker(self):
        if self._landmarker is not None:
            return self._landmarker

        with self._lock:
            if self._landmarker is not None:
                return self._landmarker
            try:
                import mediapipe as mp
                from mediapipe.tasks import python as mp_python
                from mediapipe.tasks.python import vision
            except ImportError as err:
                raise ModuleError(
                    f"mediapipe is not installed ({err}). Run: pip install mediapipe",
                    "M2",
                )

            path = ensure_model(self._model_path, self._variant)
            options = vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=path),
                running_mode=vision.RunningMode.IMAGE,
                num_poses=1,
            )
            self._landmarker = vision.PoseLandmarker.create_from_options(options)
            logger.info("MediaPipe pose model loaded", {"path": path})
            return self._landmarker

    # -- SizingProvider ---------------------------------------------------

    def extract_measurements(self, photo_ref: str, height_cm: float = None) -> Measurements:
        """Not supported: this provider needs the image itself, not a reference."""
        raise ModuleError(
            "MediaPipeSizingProvider requires the uploaded image; "
            "use extract_from_image (POST /intake/photo-measure)",
            "M2",
        )

    def extract_from_image(
        self, image_bytes: bytes, content_type: str = None, height_cm: float = None,
        usual_top_size: str = None, usual_bottom_size: str = None,
    ) -> Measurements:
        if not isinstance(image_bytes, (bytes, bytearray)) or len(image_bytes) == 0:
            raise ModuleError("Empty image upload", "M2")
        if not height_cm or height_cm <= 0:
            raise ModuleError(
                "Your height is needed to scale measurements from the photo", "M2"
            )

        image_array, width_px, height_px = self._decode(image_bytes)
        landmarks = self._detect_landmarks(image_array)
        # Kept out of _detect_landmarks so it applies to any landmark source
        # (and stays testable without running the model).
        self._validate_landmark_visibility(landmarks)

        # Normalized landmark coords are each relative to their own axis, so
        # convert with the matching dimension.
        def px(index):
            lm = landmarks[index]
            return lm.x * width_px, lm.y * height_px

        lsx, lsy = px(LEFT_SHOULDER)
        rsx, rsy = px(RIGHT_SHOULDER)
        lhx, lhy = px(LEFT_HIP)
        rhx, rhy = px(RIGHT_HIP)
        _, lay = px(LEFT_ANKLE)
        _, ray = px(RIGHT_ANKLE)

        shoulder_mid_y = (lsy + rsy) / 2.0
        ankle_mid_y = (lay + ray) / 2.0
        span_px = abs(ankle_mid_y - shoulder_mid_y)

        try:
            cm_per_px = pixels_to_cm_scale(span_px, height_cm)
        except ValueError as err:
            raise ModuleError(
                "Couldn't work out your proportions from that photo. Please use a "
                f"full-body photo taken straight on. ({err})",
                "M2",
            )

        shoulder_breadth_px = abs(lsx - rsx)
        pelvis_breadth_px = abs(lhx - rhx)

        if shoulder_breadth_px <= 0 or pelvis_breadth_px <= 0:
            raise ModuleError(
                "Couldn't measure your shoulders and hips in that photo. Please use "
                "a full-body photo, facing the camera.",
                "M2",
            )

        # Detecting a body isn't enough -- the pose has to be one this math is
        # valid for. See the constants above for why.
        self._validate_pose(
            shoulder_breadth_px=shoulder_breadth_px,
            pelvis_breadth_px=pelvis_breadth_px,
            span_px=span_px,
            shoulder_tilt_px=abs(lsy - rsy),
            hip_tilt_px=abs(lhy - rhy),
            left_ankle_offset_px=abs(px(LEFT_ANKLE)[0] - lhx),
            right_ankle_offset_px=abs(px(RIGHT_ANKLE)[0] - rhx),
            shoulder_mid_y=shoulder_mid_y,
            hip_mid_y=(lhy + rhy) / 2.0,
            ankle_mid_y=ankle_mid_y,
        )

        shoulder_breadth_cm = shoulder_breadth_px * cm_per_px
        pelvis_breadth_cm = pelvis_breadth_px * cm_per_px

        derived = measurements_from_breadths(shoulder_breadth_cm, pelvis_breadth_cm)
        anchored_fields = self._steady_with_stated_sizes(
            derived, usual_top_size, usual_bottom_size)
        adjusted_fields = self._fit_to_supported_range(derived)

        confidences = self._confidence_scores(landmarks)
        # Only the anchored fields get the confidence lift: an unanchored field
        # still rests mainly on the photo, so it keeps its visibility-derived
        # score and stays flagged for review.
        for field in anchored_fields:
            if field in confidences:
                confidences[field] = max(confidences[field], ANCHORED_FIELD_CONFIDENCE)
        # An adjusted field is by definition not trustworthy, regardless of how
        # clearly the landmarks were seen. Dropping it below the low-confidence
        # threshold is what makes the UI ask the customer to check it.
        for field in adjusted_fields:
            confidences[field] = ADJUSTED_FIELD_CONFIDENCE

        logger.debug(
            "MediaPipe extraction complete",
            {
                "shoulder_cm": derived["shoulder_cm"],
                "span_px": round(span_px, 1),
                "min_visibility": round(min(confidences.values()), 2),
            },
        )

        return Measurements(
            bust=derived["bust"],
            waist=derived["waist"],
            hips=derived["hips"],
            height=height_cm,
            shoulder=derived["shoulder_cm"],
            inseam=None,
            unit="cm",
            confidence_scores=confidences,
            provider="mediapipe_pose",
            provider_version=f"mediapipe-1.x/{self._variant}",
        )

    @property
    def disclosure(self) -> dict:
        return {
            "processor_name": "Eighth Hour on-server pose analysis (Google MediaPipe)",
            "sends_image_offsite": False,
            "stores_image": False,
            "derives_from_image": True,
            "retention": (
                "Your photo is analysed on our own server and is never sent anywhere "
                "else. It is not saved to your account or our database -- it exists "
                "only for the few seconds the analysis takes, then is discarded. Only "
                "the resulting measurements are kept."
            ),
        }

    # -- internals ---------------------------------------------------------

    def _decode(self, image_bytes: bytes):
        """Decode upload bytes to an RGB array, honouring EXIF rotation."""
        import io
        import numpy as np
        from PIL import Image, ImageOps

        # HEIC/HEIF (the default iPhone camera format) needs an extra opener
        # registered before Pillow can read it. Optional: if pillow-heif isn't
        # installed the other formats still work and HEIC fails with the normal
        # "couldn't read that image" message.
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass

        try:
            image = Image.open(io.BytesIO(bytes(image_bytes)))
            # Phone photos are commonly stored rotated with an EXIF flag; without
            # this a portrait shot arrives sideways and no pose is found.
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")
        except Exception as err:
            raise ModuleError(f"Couldn't read that image file ({err})", "M2")

        array = np.asarray(image)
        return array, image.width, image.height

    def _detect_landmarks(self, image_array):
        import mediapipe as mp

        landmarker = self._get_landmarker()
        result = landmarker.detect(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=image_array)
        )

        if not result.pose_landmarks:
            raise ModuleError(
                "We couldn't find a person in that photo. Please upload a clear, "
                "full-body photo of yourself facing the camera.",
                "M2",
            )

        return result.pose_landmarks[0]

    def _validate_landmark_visibility(self, landmarks) -> None:
        """
        Refuse photos where the joints we measure BREADTHS from aren't clearly
        visible. Ankles are held to a much lower bar -- see SCALE_LANDMARKS for
        why, and _validate_pose for the scale check that replaces it.
        """
        too_faint = [
            index for index in BREADTH_LANDMARKS
            if float(getattr(landmarks[index], "visibility", 1.0)) < MIN_LANDMARK_VISIBILITY
        ]
        if too_faint:
            logger.info("Rejected photo: landmarks not clearly visible",
                        {"landmark_indices": too_faint})
            raise ModuleError(
                "We could only partly see your body in that photo. Please upload a "
                "full-body photo, standing straight and facing the camera, with your "
                "shoulders, hips and feet all in frame.",
                "M2",
            )

    # A single message for every pose failure: the customer's fix is the same
    # in all cases, and enumerating which geometric check tripped would be
    # noise to them (the specifics go to the log instead).
    POSE_GUIDANCE = (
        "That photo isn't quite usable for measuring. Please stand upright and "
        "square to the camera, with your feet roughly together and your whole body "
        "in frame -- or enter your measurements manually."
    )

    def _validate_pose(
        self,
        shoulder_breadth_px,
        pelvis_breadth_px,
        span_px,
        shoulder_tilt_px,
        hip_tilt_px,
        left_ankle_offset_px,
        right_ankle_offset_px,
        shoulder_mid_y,
        hip_mid_y,
        ankle_mid_y,
    ) -> None:
        """Reject poses the anthropometry isn't valid for (see constants above)."""
        reasons = []

        # Upright: shoulders above hips above ankles (y grows downward).
        if not (shoulder_mid_y < hip_mid_y < ankle_mid_y):
            reasons.append("body is not upright")

        if shoulder_tilt_px / shoulder_breadth_px > MAX_TILT_OVER_BREADTH:
            reasons.append("shoulders are not level")

        if hip_tilt_px / shoulder_breadth_px > MAX_TILT_OVER_BREADTH:
            reasons.append("hips are not level")

        splay = max(left_ankle_offset_px, right_ankle_offset_px) / shoulder_breadth_px
        if splay > MAX_ANKLE_OFFSET_OVER_SHOULDER_BREADTH:
            reasons.append(f"feet are too far apart (splay {splay:.1f})")

        ratio = pelvis_breadth_px / shoulder_breadth_px
        if not (MIN_PELVIS_SHOULDER_RATIO <= ratio <= MAX_PELVIS_SHOULDER_RATIO):
            reasons.append(f"torso looks rotated (hip/shoulder {ratio:.2f})")

        # Validates the vertical scale directly, replacing the old reliance on
        # ankle visibility (see SCALE_LANDMARKS).
        span_ratio = shoulder_breadth_px / span_px if span_px else 0
        if not (MIN_SHOULDER_TO_SPAN_RATIO <= span_ratio <= MAX_SHOULDER_TO_SPAN_RATIO):
            reasons.append(f"body proportions implausible (shoulder/span {span_ratio:.2f})")

        if reasons:
            logger.info("Rejected photo: pose unsuitable", {"reasons": reasons})
            raise ModuleError(self.POSE_GUIDANCE, "M2")

    def _confidence_scores(self, landmarks) -> dict:
        """
        Per-measurement confidence from how clearly the contributing landmarks
        were seen. This is a real signal about photo quality (framing, pose,
        occlusion) rather than a fixed number, so a poor photo genuinely surfaces
        as low confidence and routes the customer to check the values by hand.
        """
        def visibility(index):
            return float(getattr(landmarks[index], "visibility", 1.0))

        shoulder_v = min(visibility(LEFT_SHOULDER), visibility(RIGHT_SHOULDER))
        hip_v = min(visibility(LEFT_HIP), visibility(RIGHT_HIP))
        ankle_v = min(visibility(LEFT_ANKLE), visibility(RIGHT_ANKLE))

        # Every measurement also depends on the vertical scale, which comes from
        # the shoulder and ankle landmarks -- so those bound all three.
        scale_v = min(shoulder_v, ankle_v)

        return {
            "bust": round(min(shoulder_v, scale_v), 2),
            "waist": round(min(hip_v, scale_v), 2),
            "hips": round(min(hip_v, scale_v), 2),
            "shoulder": round(shoulder_v, 2),
        }

    @staticmethod
    def _stated_size(size: str):
        """
        Normalised size label for a stated size, or None if unusable. The label
        rather than the chart row, because the anchor value and the band that
        holds the blend are both keyed by it.
        """
        if not size:
            return None
        key = str(size).strip().upper()
        if key not in STANDARD_SIZE_CHART:
            logger.info("Ignoring unrecognised stated size", {"size": size})
            return None
        return key

    @staticmethod
    def _blend_within_stated_band(photo_value: float, field: str, size: str) -> float:
        """
        Move the chart anchor toward the photo estimate, but only as far as the
        band for the size the customer named allows -- so the recommender can
        never hand back a size they didn't say they wear, while every distinct
        photo still produces a distinct number.

        See STATED_SIZE_BAND_MARGIN_CM for why this squashes rather than clips.
        """
        anchor = STANDARD_SIZE_CHART[size][field]
        adjustment = PHOTO_WEIGHT_WITH_STATED_SIZE * (photo_value - anchor)

        band = BOUNDARIES_BY_FIELD[field].get(size)
        if band is None:
            return anchor + adjustment

        low, high = band
        # Room in the direction we're actually moving, so a wide open-ended
        # bucket isn't limited by its narrow side.
        headroom = (
            high - STATED_SIZE_BAND_MARGIN_CM - anchor if adjustment > 0
            else anchor - low
        )
        if headroom <= 0:
            return anchor
        return anchor + headroom * math.tanh(adjustment / headroom)

    def _steady_with_stated_sizes(
        self, derived: dict, usual_top_size: str, usual_bottom_size: str
    ) -> list:
        """
        Blend the photo estimate toward the size chart, editing `derived` in
        place. Bust is anchored by the TOP size; waist and hips by the BOTTOM
        size (see the constants above for why they're separate, and for the
        measured accuracy of each option).

        Either size may be given on its own -- a customer who knows only their
        top size still gets a better bust estimate, with waist and hips left to
        the photo.

        Returns:
            The fields that ended up anchored (empty if neither size was usable).
        """
        top = self._stated_size(usual_top_size)
        bottom = self._stated_size(usual_bottom_size)

        anchors = {}
        if top:
            anchors["bust"] = top
        if bottom:
            anchors["waist"] = bottom
            anchors["hips"] = bottom

        if not anchors:
            return []

        for field, size in anchors.items():
            derived[field] = round(
                self._blend_within_stated_band(derived[field], field, size), 1
            )

        logger.debug("Estimate steadied with stated sizes", {
            "top": usual_top_size, "bottom": usual_bottom_size,
            "anchored": sorted(anchors),
            "photo_weight": PHOTO_WEIGHT_WITH_STATED_SIZE,
        })
        return sorted(anchors)

    def _fit_to_supported_range(self, derived: dict) -> list:
        """
        Bring an estimate inside the range the rest of the app accepts, and
        report which fields had to be adjusted.

        Why clamp instead of reject: a single frontal photo genuinely cannot
        pin down circumferences. MediaPipe's hip landmarks are joint centres,
        and across very different real bodies the pelvis:shoulder ratio only
        moved between 0.54 and 0.60 -- so hip estimates barely respond to how
        curvy someone actually is and often land low. Refusing every photo
        whose estimate fell a few centimetres under the floor meant refusing
        ordinary, perfectly good full-body photos.

        Instead the estimate is nudged to the nearest supported value and the
        affected fields are flagged as low confidence, which routes the
        customer to the measurements screen with a "double-check these" note.
        They review and correct -- which is the right end state for an
        approximate estimate, and much better than a dead end.

        A wildly-off estimate still fails outright: that indicates a broken
        scale (bad pose, extreme perspective) rather than ordinary imprecision,
        and a number that far out is not worth showing anyone.

        Returns:
            List of field names that were adjusted (empty if the estimate was
            already inside the supported range).
        """
        adjusted = []
        # "shoulder" is stored under a different key because anthropometry.py
        # returns it as a breadth diagnostic; it is mapped here so it gets the
        # same treatment. It was previously left unclamped and passed straight
        # into Measurements, so a photo could persist a shoulder outside the
        # supported 30-60cm range -- which M9 (new releases) and M7 (fit check)
        # then refused with a 400, breaking both features for that customer
        # while recommendations, which does not validate shoulder, kept working.
        FIELD_KEYS = {"bust": "bust", "waist": "waist", "hips": "hips",
                      "shoulder": "shoulder_cm"}
        for field, key in FIELD_KEYS.items():
            low, high = MEASUREMENT_RANGES[field]
            value = derived[key]

            # Beyond this margin outside the range, the scale itself is wrong.
            # Shoulder is exempt from the hard rejection: it is an optional
            # field that nothing sizes on, so a poor shoulder estimate is not
            # reason enough to refuse a photo whose bust/waist/hips are sound.
            slack = (high - low) * OUT_OF_RANGE_SLACK
            if field != "shoulder" and (value < low - slack or value > high + slack):
                raise ModuleError(
                    "The measurements we worked out from that photo don't look "
                    f"right ({field} came to {value:.0f} cm). Please try a "
                    "full-body photo taken straight on, or enter your measurements "
                    "manually.",
                    "M2",
                )

            if value < low:
                derived[key] = float(low)
                adjusted.append(field)
            elif value > high:
                derived[key] = float(high)
                adjusted.append(field)

        if adjusted:
            logger.info("Photo estimate adjusted to supported range",
                        {"fields": adjusted})
        return adjusted
