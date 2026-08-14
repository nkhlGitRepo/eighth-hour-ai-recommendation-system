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
#
# There is deliberately no XXS. It previously existed in the boundary tables
# only -- never in STANDARD_SIZES, never in the size chart, and never offered in
# the UI -- so a body below XS could be told "XXS", a size with no defined
# measurements that the catalog does not stock. The smallest band now opens out
# to cover everything down to the supported minimum instead.
STANDARD_SIZES = ["XS", "S", "M", "L", "XL", "XXL"]

# Measurement validation ranges (cm) -- must match InputValidator's enforced
# ranges (py_src/guardrails/input_validation.py) so size inference never
# rejects/accepts a measurement the API itself allows. Defined this early
# because the size boundary tables below open their smallest and largest bands
# out to these limits.
MEASUREMENT_RANGES = {
    "height": (140, 210),      # cm
    "bust": (70, 150),         # cm
    "waist": (55, 130),        # cm
    "hips": (80, 160),         # cm
    "shoulder": (30, 60),      # cm (optional)
    "inseam": (50, 120),       # cm (optional)
}

# The published women's size chart this app sizes against: the measurement
# RANGE each size is cut for, in cm. This is the single source of truth --
# STANDARD_SIZE_CHART and all three *_SIZE_BOUNDARIES tables below are derived
# from it, so the measurements a size is cut for and the range of bodies that
# maps to that size can never drift apart.
#
# Why this replaced the previous tables: those were uniform grids (bust stepping
# 8/8/8/8, waist 6/6/6/6/6, hips 6/6/6/6) -- even spacing rather than any real
# chart, despite a comment claiming "standard sizing guidelines". The waist was
# a full size high throughout: it placed XS at 69cm against a real 61-66cm and M
# at 81cm against 71-75cm, so every customer's waist read about 6cm larger than
# the size they actually wear. Real charts have uneven bands that widen with
# size, as below.
#
# One deliberate edit to the source: the S hip row was published as 93-94cm, a
# 1cm band where every other row spans 5-6cm. Taken literally it left S a 2.5cm
# sliver of the hip scale that almost nobody would land in, so it is widened to
# sit evenly between XS and M. Its midpoint moves only 0.5cm (93.5 -> 94), so
# this changes which bodies reach S without restating what S measures.
SIZE_CHART_SOURCE = {
    "XS": {"bust": (81, 84), "waist": (61, 66), "hips": (86, 92)},
    "S":  {"bust": (86, 89), "waist": (66, 69), "hips": (92, 96)},
    "M":  {"bust": (91, 95), "waist": (71, 75), "hips": (96, 101)},
    "L":  {"bust": (99, 103), "waist": (79, 83), "hips": (105, 109)},
    "XL": {"bust": (108, 114), "waist": (89, 95), "hips": (114, 120)},
}

_CHART_DIMENSIONS = ("bust", "waist", "hips")


def _extrapolate_top_size(source, sizes):
    """
    The published chart stops at XL, but the catalog sells XXL. Continue the
    chart's own final step rather than inventing a row, so XXL stays consistent
    with the curve the rest of the chart describes.
    """
    second_last, last = sizes[-2], sizes[-1]
    return {
        dimension: tuple(
            source[last][dimension][edge]
            + (source[last][dimension][edge] - source[second_last][dimension][edge])
            for edge in (0, 1)
        )
        for dimension in _CHART_DIMENSIONS
    }


_SOURCE_SIZES = ["XS", "S", "M", "L", "XL"]
_FULL_CHART_SOURCE = dict(SIZE_CHART_SOURCE)
_FULL_CHART_SOURCE["XXL"] = _extrapolate_top_size(SIZE_CHART_SOURCE, _SOURCE_SIZES)

# Standard size chart: the measurement each size is cut for, in cm -- the
# midpoint of that size's published range. Used by M7's fit checker to score how
# well a garment size suits a body, and as the anchor the photo estimator blends
# toward when a customer states the sizes they usually wear.
#
# Taken from the source range's own midpoint rather than from the derived
# boundary bands below, because the first and last bands are open-ended (they
# have to absorb everything down to and up to the supported measurement range),
# and their centres would therefore describe a measurement no garment is cut for.
STANDARD_SIZE_CHART = {
    size: {
        dimension: (
            _FULL_CHART_SOURCE[size][dimension][0]
            + _FULL_CHART_SOURCE[size][dimension][1]
        ) / 2
        for dimension in _CHART_DIMENSIONS
    }
    for size in STANDARD_SIZES
}


def _boundaries_from_chart(dimension):
    """
    Contiguous lookup bands for one dimension, derived from the chart above.

    Published charts leave gaps between sizes (bust XS ends at 84, S starts at
    86), but a lookup has to answer for every body, so adjacent sizes meet at the
    midpoint of the gap. The smallest and largest sizes then open out to the
    supported measurement range so nothing falls off either end.
    """
    floor, ceiling = MEASUREMENT_RANGES[dimension]
    edges = [floor]
    for smaller, larger in zip(STANDARD_SIZES, STANDARD_SIZES[1:]):
        edges.append(
            (
                _FULL_CHART_SOURCE[smaller][dimension][1]
                + _FULL_CHART_SOURCE[larger][dimension][0]
            ) / 2
        )
    edges.append(ceiling)
    return {
        size: (edges[index], edges[index + 1])
        for index, size in enumerate(STANDARD_SIZES)
    }


# Size boundaries for measurement-based inference (cm). Shared by M3 (body shape
# profiler, computes the size shown to the customer), M5 (recommendation engine),
# M7 (fit checker) and M9 (new releases), so a customer's size is calculated the
# same way everywhere -- and, being derived from the chart above, always agrees
# with what that size is cut for.
SIZE_BOUNDARIES = _boundaries_from_chart("bust")
WAIST_SIZE_BOUNDARIES = _boundaries_from_chart("waist")
HIP_SIZE_BOUNDARIES = _boundaries_from_chart("hips")

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

# Which measurement dimensions are relevant for M7's *fit-note guidance
# text* ("runs small in the bust", "snug in the hips", ...) per category --
# deliberately separate from FIT_SCORE_DIMENSION_WEIGHTS above, which
# governs the SIZE/SCORE and stays bust-only for Dresses/Co-ord Sets (see
# that constant's comment for why). A garment covering the whole body can
# still owe the customer advice about a dimension that didn't drive which
# size got picked -- e.g. a dress fits the whole torso, so a waist or hips
# mismatch is real, useful guidance even though the recommended size itself
# is chosen from bust alone. Tops/Vests only ever cover the upper body, so
# a waist/hips note there would describe fit for a part of the body the
# garment doesn't touch; Skirts/Trousers are the mirror case for the lower
# body. Categories not listed here fall back to all three (see check_fit).
FIT_NOTE_RELEVANT_DIMENSIONS = {
    "Tops": {"bust"},
    "Vests": {"bust"},
    "Dresses": {"bust", "waist", "hips"},
    "Co-ord Sets": {"bust", "waist", "hips"},
    "Skirts": {"waist", "hips"},
    "Trousers": {"waist", "hips"},
}

# New releases feed configuration
NEW_RELEASES_MATCH_THRESHOLD = 0.65  # Minimum match score to include in feed
NEW_RELEASES_WINDOW_DAYS = 30  # Products launched within this many days count as "new"

# Minimum items NewReleasesFeed.generate_feed() guarantees via relaxation
# (see its own docstring for the relaxation order) when strict scoring
# would otherwise return fewer than this. Pass min_items=0 to disable and
# get the exact, unrelaxed result (including possibly empty).
MIN_NEW_RELEASES_ITEMS = 1

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

# User accounts / authentication
AUTH_TOKEN_EXPIRY_DAYS = 30
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128  # bcrypt silently truncates at 72 bytes -- cap input rather than let it lie
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 32
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
