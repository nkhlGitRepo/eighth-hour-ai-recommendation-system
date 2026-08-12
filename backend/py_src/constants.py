"""Shared constants across modules."""

BODY_SHAPE_CLASSES = ["balanced", "pear", "apple", "hourglass", "straight", "athletic"]

# General category affinity per shape class, grounded in the same guidance
# M3's _generate_fit_notes already gives customers (e.g. "A-line skirts...
# will complement your curves" for pear; "Wrap dresses... are made for you"
# for hourglass). Categories match the real catalog taxonomy (Tops, Skirts,
# Dresses, Trousers, Vests, Co-ord Sets). Used as:
#   - M6's tiebreaker when ranking candidates that all flatter a shape
#   - M9's fallback score when a product isn't a specific flatters_shapes match
SHAPE_CATEGORY_AFFINITY = {
    "pear": {"Skirts": 0.85, "Dresses": 0.75, "Trousers": 0.7, "Tops": 0.6, "Vests": 0.6, "Co-ord Sets": 0.65},
    "apple": {"Tops": 0.75, "Vests": 0.75, "Trousers": 0.7, "Dresses": 0.6, "Skirts": 0.55, "Co-ord Sets": 0.6},
    "hourglass": {"Dresses": 0.85, "Vests": 0.7, "Tops": 0.7, "Skirts": 0.6, "Trousers": 0.6, "Co-ord Sets": 0.65},
    "athletic": {"Dresses": 0.7, "Tops": 0.65, "Skirts": 0.65, "Vests": 0.6, "Trousers": 0.6, "Co-ord Sets": 0.6},
    "straight": {"Tops": 0.7, "Dresses": 0.7, "Skirts": 0.7, "Trousers": 0.7, "Vests": 0.7, "Co-ord Sets": 0.7},
    "balanced": {"Tops": 0.75, "Dresses": 0.75, "Skirts": 0.75, "Trousers": 0.75, "Vests": 0.75, "Co-ord Sets": 0.75},
}

# Standard size ordering (XS to XXL)
STANDARD_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]

# Size boundaries for measurement-based inference (cm).
# Single source of truth for bust/waist/hip-based sizing -- shared by M3
# (body shape profiler, computes the size shown to the customer), M5
# (recommendation engine), M9 (new releases), and STANDARD_SIZE_CHART below,
# so that a customer's size is calculated the same way everywhere.
SIZE_BOUNDARIES = {
    "XXS": (70, 76),
    "XS": (76, 84),
    "S": (84, 92),
    "M": (92, 100),
    "L": (100, 108),
    "XL": (108, 117),
    "XXL": (117, 150),
}

WAIST_SIZE_BOUNDARIES = {
    "XXS": (60, 66),
    "XS": (66, 72),
    "S": (72, 78),
    "M": (78, 84),
    "L": (84, 90),
    "XL": (90, 96),
    "XXL": (96, 150),
}

# Hip boundaries per standard sizing guidelines:
# XS: 83-89cm, S: 89-95cm, M: 95-101cm, L: 101-107cm, XL: 107-114cm, XXL: 114+cm
HIP_SIZE_BOUNDARIES = {
    "XXS": (70, 83),
    "XS": (83, 89),
    "S": (89, 95),
    "M": (95, 101),
    "L": (101, 107),
    "XL": (107, 114),
    "XXL": (114, 150),
}


def _bucket_center(low, high, cap=10):
    """
    Midpoint of a boundary bucket, capping how much an open-ended top
    bucket (e.g. XXL's upper bound is an arbitrary ceiling, not a real
    distribution) can pull the center away from its lower edge.
    """
    return low + min(high - low, cap) / 2


# Standard size chart: bust, waist, hips measurements in cm, one entry per
# size in STANDARD_SIZES. Derived from the *_SIZE_BOUNDARIES tables above
# (each size's bucket center) rather than hardcoded, so the size M7's fit
# checker recommends for a garment can never drift out of sync with the
# size M3 computes and shows the customer on their Shape Profile.
STANDARD_SIZE_CHART = {
    size: {
        "bust": _bucket_center(*SIZE_BOUNDARIES[size]),
        "waist": _bucket_center(*WAIST_SIZE_BOUNDARIES[size]),
        "hips": _bucket_center(*HIP_SIZE_BOUNDARIES[size]),
    }
    for size in STANDARD_SIZES
}

# Typical measurement change (cm) between adjacent sizes, one per dimension
# -- derived from STANDARD_SIZE_CHART's own span so it can never drift from
# the chart it describes. M7's fit checker uses this as a FIXED unit to
# convert "how far off is this measurement" into "how many sizes off",
# instead of dividing by the candidate size's own reference value (which
# made the exact same cm miss score as a smaller error against bigger
# sizes purely because it divided by a bigger number).
SIZE_STEP_CM = {
    dimension: (
        STANDARD_SIZE_CHART[STANDARD_SIZES[-1]][dimension]
        - STANDARD_SIZE_CHART[STANDARD_SIZES[0]][dimension]
    ) / (len(STANDARD_SIZES) - 1)
    for dimension in ("bust", "waist", "hips")
}

# How many "sizes off" (see SIZE_STEP_CM) a single measurement can be
# before that dimension's fit confidence hits 0. Linear decay in between:
# 1 size off -> ~67% confidence (a real but minor mismatch), 2 sizes off
# -> ~33% (a real problem), 3+ sizes off -> 0 (the wrong size).
FIT_SCORE_TOLERANCE_SIZE_STEPS = 3.0

# Confidence floor for a measurement sitting exactly at the edge of its
# own (correct) size boundary. Being inside your size's range always
# scores somewhere in [FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE, 1.0] -- 1.0 at
# the center, ramping down to this floor right at the edge, so a customer
# on the fence between two sizes sees that reflected in the number rather
# than every in-range measurement flatly reading 100%. Every OTHER size's
# "outside my range" score also starts at this same floor (at distance 0
# from its own edge) and decays further from there -- never higher. That
# shared floor is what keeps the guarantee intact: the correct size's
# score can never drop below it, and no other size's score can ever rise
# above it, so the correct size can never be strictly outscored.
FIT_SCORE_BOUNDARY_EDGE_CONFIDENCE = 0.85

# How close to a size's boundary edge (in cm) the ramp above applies.
# Beyond this cushion from both edges, a measurement is "solidly" in that
# size and scores a flat 1.0 -- this is what stops a wide, open-ended
# bucket (e.g. XXL's hip range spans 114-150cm) from reading as a
# lower-confidence fit just because it's far from an arbitrary center
# point; only measurements actually near a real boundary get the reduced
# score. Derived from SIZE_STEP_CM so it scales sensibly per dimension.
FIT_SCORE_BOUNDARY_EDGE_CUSHION_CM = {
    dimension: step / 4 for dimension, step in SIZE_STEP_CM.items()
}

# Per-category measurement weights for M7's displayed "% fit" per size.
# A vest doesn't cover the hips -- blending hips in at equal weight (as if
# it were a dress) let a body with a bust-driven XL but much smaller hips
# score a *different* size HIGHER than XL, directly contradicting the
# recommendation displayed right next to it.
#
# Weighted to exactly match the single measurement M3's _recommend_sizes
# already uses to pick that category's size (bust for tops/dresses/vests/
# Co-ord Sets, hips for skirts/trousers -- M3 doesn't consider the other
# two measurements for sizing purposes either). Using the SAME
# measurement, at full weight, guarantees the highest "% fit" can never
# disagree with the recommendation -- not just usually, always, because
# they're now the same calculation.
#
# Co-ord Sets is sized like a Top (bust-driven) rather than blending in
# hips too: a two-piece set only has ONE size selector for the customer to
# pick from (there's no separate top-size/bottom-size field to fill), and
# a two-piece outfit genuinely can need different sizes for each half, so
# any attempt to blend bust+hips into one number lands on an arbitrary
# compromise that doesn't clearly reflect either half (e.g. a customer
# whose top needs XL and bottom needs S could see a confusing "M").
# Defaulting to the top half's size matches the same convention M5's
# recommendation engine already uses elsewhere (shape_profile's "tops"
# size is the general default across the whole system) -- at least it's
# then a single, traceable, explainable number rather than an unexplained
# average.
FIT_SCORE_DIMENSION_WEIGHTS = {
    "Tops": {"bust": 1.0, "waist": 0.0, "hips": 0.0},
    "Dresses": {"bust": 1.0, "waist": 0.0, "hips": 0.0},
    "Vests": {"bust": 1.0, "waist": 0.0, "hips": 0.0},
    "Co-ord Sets": {"bust": 1.0, "waist": 0.0, "hips": 0.0},
    "Skirts": {"hips": 1.0, "waist": 0.0, "bust": 0.0},
    "Trousers": {"hips": 1.0, "waist": 0.0, "bust": 0.0},
}
FIT_SCORE_DEFAULT_WEIGHTS = {"bust": 1 / 3, "waist": 1 / 3, "hips": 1 / 3}

# Measurement validation ranges (cm) -- must match InputValidator's
# enforced ranges (py_src/guardrails/input_validation.py) so size
# inference never rejects/accepts a measurement the API itself allows.
MEASUREMENT_RANGES = {
    "height": (140, 210),      # cm
    "bust": (70, 150),         # cm
    "waist": (55, 130),        # cm
    "hips": (80, 160),         # cm
    "shoulder": (30, 60),      # cm (optional)
    "inseam": (50, 120),       # cm (optional)
}

# New releases feed configuration
NEW_RELEASES_MATCH_THRESHOLD = 0.65  # Minimum match score to include in feed
NEW_RELEASES_WINDOW_DAYS = 30  # Products launched within this many days count as "new"

# Maps catalog category names to the corresponding key in M3's
# size_recommendation_by_category, so M7's fit checker can look up the same
# category-specific size M3 already computed and showed the customer.
# "Co-ord Sets" maps to "tops" -- M3 itself represents it as a combined
# "top/bottom" string (e.g. "L/S"), but the shop only has one size
# selector per product, so it's sized like a Top (see the matching
# comment on FIT_SCORE_DIMENSION_WEIGHTS for why).
CATEGORY_TO_SIZE_PROFILE_KEY = {
    "Tops": "tops",
    "Dresses": "dresses",
    "Vests": "vests",
    "Co-ord Sets": "tops",
    "Skirts": "skirts",
    "Trousers": "trousers",
}

# Recommendation engine: minimum recommendations M6 guarantees via
# progressive filter relaxation (see M6CatalogKB.retrieve()) when the
# customer's full preference set is narrow enough to otherwise return
# fewer than this many matches.
MIN_RECOMMENDATIONS = 2

# Order in which hard filters are relaxed (dropped one at a time) when the
# fully-strict filter set doesn't yield MIN_RECOMMENDATIONS candidates.
# Softer, more subjective preference signals relax first; concrete
# functional constraints relax last, since a wrong occasion/silhouette/color
# is a minor mismatch but a wrong size is close to unusable. Shape is never
# in this list -- it only ever affects ranking, never exclusion.
FILTER_RELAXATION_ORDER = [
    "occasions",
    "preferred_silhouettes",
    "preferred_colors",
    "fabrics",
    "categories",
    "size",
]

# Learning loop feedback types (M10)
FIT_FEEDBACK_TYPES = ["too_tight", "perfect", "too_loose"]
PRODUCT_FEEDBACK_TYPES = ["liked", "disliked", "neutral"]
