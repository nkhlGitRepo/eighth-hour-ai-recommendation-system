"""
Anthropometric conversions: pose landmarks -> body measurements.

Kept separate from the MediaPipe provider so this math is unit-testable
without loading a 190 MB ML model, and so a different pose source (a hosted
API, a different model) can reuse it unchanged.

WHAT THIS IS AND ISN'T
----------------------
A frontal photo gives *breadths* (how wide you are). Tape measurements are
*circumferences* (all the way around). Bridging that gap needs two things a
single 2D image cannot supply:

  1. Where the tape actually sits. MediaPipe returns joints -- shoulders,
     hip sockets, knees -- not the bust/waist/hip lines a tailor uses. The
     hip landmarks in particular sit at the pelvis, which is materially
     narrower than the widest part of the hips.
  2. Body depth. Front-to-back thickness is invisible head-on.

Both are therefore estimated from population-average ratios below. That
makes these numbers genuinely derived from the customer's photo -- they
change with real proportions and scale -- but approximate, and less accurate
than a tape measure or a true 3D scan. The constants are grouped and named
so they can be tuned in one place, and so nobody mistakes them for
per-person measurements.
"""

import math

# --- Vertical scale ------------------------------------------------------
#
# Converting pixels to centimetres needs one known real-world length. We ask
# the customer for their height, but the top of the head and the soles of the
# feet are both unreliable in a photo (hair, shoes, cropping). Shoulders and
# ankles are the most consistently well-detected landmarks, so we use the
# shoulder-to-ankle span and the standard proportion of stature it represents.
ACROMION_HEIGHT_RATIO = 0.818   # shoulder height as a fraction of stature
ANKLE_HEIGHT_RATIO = 0.039      # ankle height as a fraction of stature
SHOULDER_TO_ANKLE_RATIO = ACROMION_HEIGHT_RATIO - ANKLE_HEIGHT_RATIO  # ~0.779

# --- Landmark breadth -> tape-line breadth -------------------------------
#
# CALIBRATED AGAINST MEDIAPIPE OUTPUT, NOT ANTHROPOMETRIC TABLES. This
# distinction caused a real bug: MediaPipe's hip landmarks (23/24) are
# estimated hip *joint centres*, which sit well inside the body surface.
# Measured on real photos, the pelvis landmark span is only ~0.57-0.62 of the
# shoulder landmark span -- whereas surface-measured tables put hip width at
# roughly 0.9-1.0 of shoulder width. Multipliers derived from those tables were
# therefore far too small, producing waists around 56 cm and hips narrower than
# the bust for ordinary photos.
#
# These values map the observed landmark spans onto realistic tape lines:
# for a ~36 cm shoulder span (pelvis landmarks ~22 cm) they yield roughly a
# 26 cm waist breadth and 37 cm hip breadth.
CHEST_BREADTH_FROM_SHOULDER = 0.85
WAIST_BREADTH_FROM_PELVIS = 1.18
HIP_BREADTH_FROM_PELVIS = 1.68

# --- Depth as a fraction of breadth --------------------------------------
#
# Torsos are roughly elliptical in cross-section, flatter front-to-back than
# side-to-side. These are the depth:breadth ratios used to close the ellipse.
CHEST_DEPTH_RATIO = 0.80
WAIST_DEPTH_RATIO = 0.77
HIP_DEPTH_RATIO = 0.73


def ellipse_circumference(breadth_cm: float, depth_cm: float) -> float:
    """
    Circumference of an ellipse with the given full width and full depth,
    via Ramanujan's approximation (accurate to well under 1% for body-shaped
    ellipses, far below the error introduced by the ratios above).
    """
    a = breadth_cm / 2.0
    b = depth_cm / 2.0
    if a <= 0 or b <= 0:
        return 0.0
    return math.pi * (3 * (a + b) - math.sqrt((3 * a + b) * (a + 3 * b)))


def pixels_to_cm_scale(shoulder_to_ankle_px: float, height_cm: float) -> float:
    """
    Centimetres per pixel, derived from the customer's stated height and the
    measured shoulder-to-ankle pixel span.

    Raises:
        ValueError: if the span is unusable (zero/negative), which means the
            landmarks were too degenerate to scale from.
    """
    if shoulder_to_ankle_px <= 0:
        raise ValueError("shoulder-to-ankle span must be positive")
    if height_cm <= 0:
        raise ValueError("height must be positive")
    real_span_cm = SHOULDER_TO_ANKLE_RATIO * height_cm
    return real_span_cm / shoulder_to_ankle_px


def measurements_from_breadths(
    shoulder_breadth_cm: float,
    pelvis_breadth_cm: float,
) -> dict:
    """
    Convert the two breadths we can actually measure from a frontal photo
    into bust / waist / hip circumferences.

    Args:
        shoulder_breadth_cm: distance between the shoulder landmarks
        pelvis_breadth_cm: distance between the hip landmarks

    Returns:
        {"bust": cm, "waist": cm, "hips": cm} plus the intermediate
        "shoulder_cm" for diagnostics.
    """
    chest_breadth = shoulder_breadth_cm * CHEST_BREADTH_FROM_SHOULDER
    waist_breadth = pelvis_breadth_cm * WAIST_BREADTH_FROM_PELVIS
    hip_breadth = pelvis_breadth_cm * HIP_BREADTH_FROM_PELVIS

    return {
        "bust": round(
            ellipse_circumference(chest_breadth, chest_breadth * CHEST_DEPTH_RATIO), 1
        ),
        "waist": round(
            ellipse_circumference(waist_breadth, waist_breadth * WAIST_DEPTH_RATIO), 1
        ),
        "hips": round(
            ellipse_circumference(hip_breadth, hip_breadth * HIP_DEPTH_RATIO), 1
        ),
        "shoulder_cm": round(shoulder_breadth_cm, 1),
    }
