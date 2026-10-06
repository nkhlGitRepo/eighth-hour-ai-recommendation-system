"""
Anthropometric conversions: a person's outline in a photo -> body measurements.

Kept separate from the MediaPipe provider so this math is unit-testable
without loading a 190 MB ML model (every function here takes plain numbers and
a boolean mask), and so a different pose source can reuse it unchanged.

WHAT THIS IS AND ISN'T
----------------------
A frontal photo shows how WIDE the body is at each height. Tape measurements
go all the way AROUND. This module measures the width of the person's actual
outline (MediaPipe's segmentation mask) at the bust, waist and hip lines, and
converts each width to a circumference with the ratio real bodies show between
the two.

It replaces an estimator that never looked at the body at all. That one took
the distance between the shoulder JOINTS and between the hip JOINTS and scaled
them by fixed multipliers -- so it saw the skeleton, not the person. Two
people with the same frame got the same measurements however different their
bodies were; fuller figures always came out too small (a tester measuring
107/90/107 was told 82/66/92); and waist and hips both came from the one hip
breadth, so every photo produced the same waist-to-hip ratio, 0.717.

Every constant below comes from ANSUR II, the 2012 US Army anthropometric
survey (1,986 women, summary statistics in Gordon et al., NATICK/TR-15/007).
None is fitted to test photos. What remains approximate, stated plainly:

  - Depth is invisible head-on. The breadth-to-circumference ratio is the
    population's; a body much deeper or shallower than average for its width
    reads correspondingly low or high.
  - Scale comes from the customer's stated height and the body's proportions,
    which vary between people by a few percent.
  - Clothing is measured as part of the outline, so loose garments read large.

That is why the customer's usual sizes are required alongside a photo: the size
chart anchors the estimate and the photo adjusts it within that size.
"""

import math

# --- ANSUR II female means (cm) ---------------------------------------------
_STATURE = 162.85
_ACROMIAL_HEIGHT = 133.51      # top of the shoulder
_CHEST_HEIGHT = 117.16         # bust point
_WAIST_HEIGHT = 98.01          # omphalion (navel)
_TROCHANTERION_HEIGHT = 84.54  # top of the femur, ~ MediaPipe's hip landmark
_BUTTOCK_HEIGHT = 83.37        # fullest point of the seat

# --- Vertical scale ------------------------------------------------------
#
# Converting pixels to centimetres needs a known real length. We have the
# customer's height, but the top of the head and the soles of the feet are both
# unreliable in a photo (hair, shoes, cropping), so the scale is read from two
# spans whose share of stature is known:
#   - shoulder to ankle (long, so least sensitive to landmark jitter, but only
#     usable when the feet are actually in the photo), and
#   - shoulder to hip (visible in nearly every photo).
ACROMION_HEIGHT_RATIO = _ACROMIAL_HEIGHT / _STATURE          # 0.820
ANKLE_HEIGHT_RATIO = 0.039                                   # lateral malleolus
HIP_LANDMARK_HEIGHT_RATIO = _TROCHANTERION_HEIGHT / _STATURE  # 0.519
SHOULDER_TO_ANKLE_RATIO = ACROMION_HEIGHT_RATIO - ANKLE_HEIGHT_RATIO      # 0.781
SHOULDER_TO_HIP_RATIO = ACROMION_HEIGHT_RATIO - HIP_LANDMARK_HEIGHT_RATIO  # 0.301

# The two spans must agree. Their ratio is ~0.385 for real standing bodies; a
# photo with the feet cropped off still gets ankle landmarks -- MediaPipe
# extrapolates them -- and those land too high, pushing the ratio up and the
# scale (and every measurement) up with it. Measured on real photos: feet in
# frame 0.365-0.40; feet cropped or guessed 0.43-0.50. The tolerance is wide on
# purpose -- people's proportions genuinely differ -- and exists to catch the
# broken case, not to police anyone's build.
EXPECTED_TORSO_TO_SPAN = SHOULDER_TO_HIP_RATIO / SHOULDER_TO_ANKLE_RATIO
TORSO_TO_SPAN_TOLERANCE = 0.05

# The top of the head is ~12.65 cm above the ear (ANSUR II tragion-to-top-of-
# head), and the nose sits at about ear height. A photo cropped at the chest
# still gets a confident nose landmark from MediaPipe -- invented at the very
# top edge -- so a nose with less than half this much room above it means the
# head isn't really in the photo. Half, to allow for hair or a crown that is
# only just cut off.
HEAD_TOP_ABOVE_NOSE_CM = 12.65
MIN_HEAD_ROOM_SHARE = 0.5

# --- Where the tape lines sit ---------------------------------------------
#
# Heights on the torso are expressed as a fraction t of the way from the
# shoulder landmarks (t=0) to the hip landmarks (t=1), from the ANSUR heights.
def _t(height_cm):
    return (_ACROMIAL_HEIGHT - height_cm) / (_ACROMIAL_HEIGHT - _TROCHANTERION_HEIGHT)


BUST_LINE_T = _t(_CHEST_HEIGHT)      # 0.34
NAVEL_LINE_T = _t(_WAIST_HEIGHT)     # 0.72
SEAT_LINE_T = _t(_BUTTOCK_HEIGHT)    # 1.02

# A tailor measures the bust at its fullest, the waist at its narrowest and the
# hips at their fullest -- points defined by the body, not by a fixed height.
# So the waist is searched between the midpoints to the neighbouring tape lines,
# and the hips over the same span either side of the seat line. The bust is
# read close to its line: just above it the arms join the shoulders.
BUST_BAND = (BUST_LINE_T - 0.06, BUST_LINE_T + 0.06)
WAIST_BAND = ((BUST_LINE_T + NAVEL_LINE_T) / 2, (NAVEL_LINE_T + SEAT_LINE_T) / 2)
HIP_BAND = (WAIST_BAND[1], SEAT_LINE_T + (SEAT_LINE_T - WAIST_BAND[1]))

# Narrowest / fullest are read as low / high percentiles of the band rather than
# its extremes, so a single row where the mask frays doesn't decide the answer.
WAIST_PERCENTILE = 15
HIP_PERCENTILE = 85

# A band needs at least this share of its rows readable (see torso_width) for
# its figure to be used. Below it the arms cover that part of the body, and the
# field falls back to the customer's stated size.
MIN_MEASURABLE_ROW_SHARE = 0.25

# Typical half-widths of the arm (ANSUR II: flexed biceps and forearm
# circumferences taken as round, and hand breadth), for cutting an arm that
# rests against the body away from the torso.
UPPER_ARM_HALF_WIDTH_CM = 30.56 / math.pi / 2   # 4.9
FOREARM_HALF_WIDTH_CM = 26.41 / math.pi / 2     # 4.2
HAND_HALF_WIDTH_CM = 7.82 / 2                   # 3.9

# --- Width -> circumference --------------------------------------------------
#
# The ratio of mean circumference to mean breadth in ANSUR II. It carries the
# body's depth and its not-quite-elliptical cross-section in one number.
BUST_CIRCUMFERENCE_PER_BREADTH = 94.69 / 26.93    # chest circumference / breadth
WAIST_CIRCUMFERENCE_PER_BREADTH = 86.09 / 29.99   # waist circumference / breadth
HIP_CIRCUMFERENCE_PER_BREADTH = 102.12 / 35.38    # buttock circumference / hip breadth


def pixels_to_cm_scale(shoulder_to_ankle_px: float, height_cm: float) -> float:
    """
    Centimetres per pixel from the shoulder-to-ankle span alone.

    Raises:
        ValueError: if the span is unusable (zero/negative), which means the
            landmarks were too degenerate to scale from.
    """
    if shoulder_to_ankle_px <= 0:
        raise ValueError("shoulder-to-ankle span must be positive")
    if height_cm <= 0:
        raise ValueError("height must be positive")
    return SHOULDER_TO_ANKLE_RATIO * height_cm / shoulder_to_ankle_px


def combined_scale(shoulder_to_ankle_px, shoulder_to_hip_px, height_cm,
                   ankles_in_frame=True):
    """
    Centimetres per pixel, and which spans it came from.

    Both spans are averaged when the feet are in the photo and the two agree.
    Otherwise -- feet cropped, so the ankle landmarks are extrapolated -- the
    shoulder-to-hip span is used alone. That is less precise, but refusing every
    photo cut off above the feet would refuse a large share of ordinary photos,
    and the estimate is anchored on the customer's stated sizes anyway.

    Returns:
        (cm_per_px, "both" | "torso")

    Raises:
        ValueError: if the torso span itself is unusable.
    """
    if shoulder_to_hip_px <= 0:
        raise ValueError("shoulder-to-hip span must be positive")
    if height_cm <= 0:
        raise ValueError("height must be positive")
    from_torso = SHOULDER_TO_HIP_RATIO * height_cm / shoulder_to_hip_px
    if ankles_in_frame and shoulder_to_ankle_px and shoulder_to_ankle_px > 0:
        ratio = shoulder_to_hip_px / shoulder_to_ankle_px
        if abs(ratio - EXPECTED_TORSO_TO_SPAN) <= TORSO_TO_SPAN_TOLERANCE:
            from_ankles = pixels_to_cm_scale(shoulder_to_ankle_px, height_cm)
            return (from_ankles + from_torso) / 2, "both"
    return from_torso, "torso"


def _torso_run(row, mid_x):
    """The unbroken stretch of body pixels containing mid_x, or None."""
    width = len(row)
    x = int(round(mid_x))
    if not (0 <= x < width) or not row[x]:
        return None
    left = x
    while left > 0 and row[left - 1]:
        left -= 1
    right = x
    while right < width - 1 and row[right + 1]:
        right += 1
    return left, right


def torso_width(row, mid_x, arms):
    """
    Width in pixels of the torso in one row of the mask, and how it was read --
    or (None, None) if this row can't be measured.

    The torso is the run of body pixels through the body's midline. Each arm
    crossing the row is one of three cases:
      - visibly separate (background between it and the torso): ignored;
      - resting beside the torso, so the two join in the mask: nothing in a
        mask says where the arm ends, so the torso is cut at the arm's inner
        edge, using a typical arm width. The row is still used -- arms by the
        sides are how most people stand -- but it is marked "estimated";
      - in front of the torso (its centre more than one arm-width inside the
        outline, e.g. hands on hips): the row is skipped.

    Args:
        row: one row of the person mask (sequence of bools)
        mid_x: x of the body's midline
        arms: [(centre_x, half_width_px), ...] for each arm segment in this row

    Returns:
        (width_px, "clear" | "estimated") or (None, None)
    """
    run = _torso_run(row, mid_x)
    if run is None:
        return None, None
    left, right = run
    quality = "clear"
    for arm_x, half in arms:
        x = int(round(arm_x))
        if x < left or x > right:
            low, high = (x, left) if x < left else (right, x)
            low, high = max(low, 0), min(high, len(row) - 1)
            if not all(row[low:high + 1]):
                continue                    # background between: separate
            # Joined at the edge: the arm's centre is just outside the torso
            # run's measured edge, which is really the arm's outer edge.
        if x <= mid_x:
            if x - left > 2 * half:
                return None, None           # in front of the torso
            left = max(left, int(round(arm_x + half)))
        else:
            if right - x > 2 * half:
                return None, None
            right = min(right, int(round(arm_x - half)))
        quality = "estimated"
        if right <= left:
            return None, None
    return right - left, quality


def _percentile(values, q):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q / 100
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def silhouette_breadths(mask, shoulder_y, hip_y, mid_x, arm_segments, cm_per_px):
    """
    Bust, waist and hip breadths (cm) measured from the person mask.

    Args:
        mask: 2D boolean array-like, True where the person is
        shoulder_y, hip_y: y of the shoulder and hip landmark midpoints (px)
        mid_x: x of the body's midline (px)
        arm_segments: [((x0, y0), (x1, y1), half_width_cm), ...] -- each arm's
            bones and hand, with the typical half-width of that part
        cm_per_px: scale

    Returns:
        {"bust": cm|None, "waist": cm|None, "hips": cm|None,
         "quality": {field: "clear"|"estimated"|None}}

        Rows where the arms are visibly clear of the body are used when there
        are enough of them; otherwise rows where an arm rests beside the body
        are included too. A breadth is None only when too few rows could be
        read at all -- the arms covered that part of the body.
    """
    height = len(mask)
    span = hip_y - shoulder_y

    def arms_at(y):
        found = []
        for (x0, y0), (x1, y1), half_cm in arm_segments:
            if y0 != y1 and min(y0, y1) <= y <= max(y0, y1):
                found.append((x0 + (x1 - x0) * (y - y0) / (y1 - y0), half_cm / cm_per_px))
        return found

    def band_rows(band):
        top = int(math.ceil(shoulder_y + span * band[0]))
        bottom = int(math.floor(shoulder_y + span * band[1]))
        rows = [y for y in range(top, bottom + 1) if 0 <= y < height]
        read = [torso_width(mask[y], mid_x, arms_at(y)) for y in rows]
        return len(rows), [w for w, q in read if q == "clear"], [w for w, q in read if q]

    result, quality = {}, {}
    for field, band, q in (("bust", BUST_BAND, 50), ("waist", WAIST_BAND, WAIST_PERCENTILE),
                           ("hips", HIP_BAND, HIP_PERCENTILE)):
        total, clear, usable = band_rows(band)
        minimum = max(1, MIN_MEASURABLE_ROW_SHARE * total)
        if len(clear) >= minimum:
            widths, quality[field] = clear, "clear"
        elif len(usable) >= minimum:
            widths, quality[field] = usable, "estimated"
        else:
            widths, quality[field] = None, None
        result[field] = round(_percentile(widths, q) * cm_per_px, 1) if widths else None
    result["quality"] = quality
    return result


def circumferences_from_breadths(breadths: dict) -> dict:
    """Bust, waist and hip circumferences (cm) from outline breadths (cm)."""
    return {
        "bust": round(breadths["bust"] * BUST_CIRCUMFERENCE_PER_BREADTH, 1),
        "waist": round(breadths["waist"] * WAIST_CIRCUMFERENCE_PER_BREADTH, 1),
        "hips": round(breadths["hips"] * HIP_CIRCUMFERENCE_PER_BREADTH, 1),
    }
