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
# Jackets (the first Shopify drop includes one) cover the same half of the body
# as tops and are chosen on the same terms, so they take the Tops affinity
# rather than a separately invented number.
for _affinity in SHAPE_CATEGORY_AFFINITY.values():
    _affinity["Jackets"] = _affinity["Tops"]

# Standard size ordering (XXS to XXL), matching the published size guide.
#
# XXS was briefly removed because an older version of this file carried it in
# the boundary tables ONLY -- no chart row, no measurements -- so a small body
# could be told to buy a size that was never defined. The official guide does
# define it, and the storefront already offered it, so it is a real size here
# with real measurements rather than a gap in a lookup table.
STANDARD_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL"]

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
# Transcribed from Eighth Hour's size guide, revised October 2026 (the brand's
# "0. Size Guide" sheet, tab "updated oct '26", centimetre tables). Tops,
# bottoms and dresses give each size the same bust, waist and hips, and the
# sheet's inch tables convert to these figures. It replaced the earlier guide
# (XXS bust 81.2-83.8, waist 61-63.5, hips 86.3-89, ...), which the storefront
# still showed when this was written -- so until the site's own size drawer is
# updated, a customer can read one range there and be sized on another.
#
# Every band leaves a gap before the next size; the lookup bands below meet at
# the middle of each gap.
SIZE_CHART_SOURCE = {
    "XXS": {"bust": (83.8, 86.3),   "waist": (64.7, 67.3),  "hips": (88.9, 91.4)},
    "XS":  {"bust": (88.9, 91.4),   "waist": (69.8, 72.3),  "hips": (93.9, 96.5)},
    "S":   {"bust": (93.9, 96.5),   "waist": (74.9, 77.4),  "hips": (99, 101.6)},
    "M":   {"bust": (99, 101.6),    "waist": (80, 82.5),    "hips": (104.1, 106.6)},
    "L":   {"bust": (104.1, 107.9), "waist": (85, 88.9),    "hips": (109.2, 113)},
    "XL":  {"bust": (109.2, 113),   "waist": (90.1, 93.9),  "hips": (114.3, 119.3)},
    "XXL": {"bust": (114.3, 120.6), "waist": (95.2, 101.6), "hips": (120.6, 127)},
}

_CHART_DIMENSIONS = ("bust", "waist", "hips")

# Every size in STANDARD_SIZES is published, so the chart is used as-is. The
# outermost LOOKUP bands still open out to the supported measurement range (see
# _boundaries_from_chart) -- a body smaller than XS or larger than XXL must
# still map to a size rather than falling off the end.
_FULL_CHART_SOURCE = dict(SIZE_CHART_SOURCE)

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

# --- Body shape classification (M3) -----------------------------------------
#
# Based on FFIT for Apparel (Simmons, Istook & Devarajan, 2004), the standard
# measurement-based shape classification in apparel research. Its rules compare
# bust, waist and hips by their DIFFERENCES: which of bust and hips is fuller
# decides pear versus top-heavy, and how much smaller the waist is decides how
# defined it is.
#
# The previous rules used bust/waist and waist/hip ratios only and never
# compared bust with hips, so equal bust and hips (107/90/107) came out "pear"
# -- the one shape defined by hips being fuller than the bust.
#
# FFIT states its thresholds in inches at an average body. Applied verbatim
# they would grade bodies by size as well as shape: a proportionally identical
# figure has smaller differences at XXS than at XXL, so petite hourglass figures
# would read as rectangles. Each threshold is therefore expressed as a fraction
# of the body's "frame" -- the mean of bust and hips -- calibrated at the
# middle size of the published chart, which is where FFIT's inches apply as
# written. Nothing here is fitted to any particular customer.
_SHAPE_REFERENCE_SIZE = STANDARD_SIZES[len(STANDARD_SIZES) // 2]
_SHAPE_REFERENCE_FRAME_CM = (
    STANDARD_SIZE_CHART[_SHAPE_REFERENCE_SIZE]["bust"]
    + STANDARD_SIZE_CHART[_SHAPE_REFERENCE_SIZE]["hips"]
) / 2


def _ffit_fraction(inches):
    """An FFIT inch threshold as a fraction of the body's frame."""
    return inches * 2.54 / _SHAPE_REFERENCE_FRAME_CM


SHAPE_THRESHOLDS = {
    # FFIT: bust and hips within 1" of each other count as even.
    "bust_hips_even": _ffit_fraction(1.0),
    # FFIT: 3.6" or more and one of them is distinctly fuller -- the line
    # between hourglass/rectangle and triangle (pear) or inverted triangle.
    "bust_hips_distinct": _ffit_fraction(3.6),
    # FFIT: a waist 9" smaller than the bust, or 10" smaller than the hips, is
    # a defined (hourglass) waist.
    "bust_waist_defined": _ffit_fraction(9.0),
    "hips_waist_defined": _ffit_fraction(10.0),
    # Not FFIT, which has no apple class. Apple is the figure whose waist is
    # about as full as its fullest point: within 2" of the fuller of bust and
    # hips, FFIT's own smallest step after "even".
    "apple_waist_gap": _ffit_fraction(2.0),
    # Not FFIT either: it calls everything between apple and hourglass a
    # rectangle. This splits that span at its midpoint (5.5", halfway between
    # the 2" apple line and the 9" hourglass line) into "straight" -- little
    # waist definition -- and "balanced", a moderately defined waist.
    "balanced_waist_gap": _ffit_fraction(5.5),
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
FIT_SCORE_DIMENSION_WEIGHTS["Jackets"] = dict(FIT_SCORE_DIMENSION_WEIGHTS["Tops"])
FIT_SCORE_DEFAULT_WEIGHTS = {"bust": 1 / 3, "waist": 1 / 3, "hips": 1 / 3}

# Which measurement sizes the top half of the body (tops, dresses, vests,
# co-ord sets), by shape. M3 picks those sizes off it and M7 scores those
# categories on it, so the size on the profile and the size with the highest
# "% fit" stay the same calculation for every shape. Apple shapes are sized on
# the waist -- the measurement that decides whether a top closes on them.
# (M7 used to score these categories on the bust regardless, so an apple
# customer was recommended one size while another showed the higher % fit.)
TOP_SIZE_DIMENSION_BY_SHAPE = {"apple": "waist"}
DEFAULT_TOP_SIZE_DIMENSION = "bust"

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
# --- Garment length ------------------------------------------------------
#
# Eighth Hour's published length guide, transcribed per category. Each entry is
# the garment's own length in INCHES for that length class -- not a body
# measurement -- and the class name says where that length lands *on the fit
# model*: a 21-23" skirt is the "Knee" class because it reaches her knee.
#
# That is what makes height advice possible without inventing anything. The
# chart states the model's own waist-to-knee, waist-to-calf and waist-to-floor
# distances directly, so scaling them by (customer height / model height) gives
# the same landmarks on the customer, while the garment stays the length it was
# cut. See m7_fit_checker._generate_length_note.
#
# Measured from the natural waist for Skirts and Trousers, and from the high
# point of the shoulder for Tops, Vests and Dresses -- which is why the same
# class name spans very different numbers across categories ("Knee" is 21-23"
# on a skirt and 38-40" on a dress).
#
# Each category's chart is used ONLY within that category, never compared
# across them. The dress and skirt charts imply a shoulder-to-waist distance of
# 17" at the knee but 12" at full length, so they are not mutually consistent --
# they were shot on different models (see MODEL_HEIGHTS_CM). Kept apart, each is
# internally sound: the classes ascend and the landmarks are that chart's own.
GARMENT_LENGTH_CHART_IN = {
    "Skirts": {          # from the natural waist
        "Mini": (15, 17), "Short": (15, 17),
        "Knee": (21, 23),
        "Midi": (28, 32), "Calf": (28, 32),
        "Maxi": (38, 42), "Full": (38, 42),
    },
    "Trousers": {        # from the natural waist
        "Short": (12, 16),
        "Capri": (33, 36),
        "Cropped": (36, 38),
        "Ankle": (38, 41),
        "Full": (42, 45),
    },
    "Dresses": {         # from the high point of the shoulder
        "Mini": (32, 35), "Short": (32, 35),
        "Knee": (38, 40),
        "Midi": (44, 48), "Calf": (44, 48),
        "Maxi": (50, 54), "Full": (50, 54),
    },
    "Tops": {            # from the high point of the shoulder
        "Cropped": (18, 21.5),
        "Short": (22, 23),
        "Regular": (24, 26.5),
        "Long": (27, 31.5),
        "Thigh": (31, 34.5),
        "Knee Length": (36, 41), "Knee": (36, 41),
        "Calf Length": (42, 44), "Calf": (42, 44),
        "Full Length": (48, 50), "Full": (48, 50),
    },
}
# Vests are cut and measured like tops, and the catalog tags them from the same
# vocabulary ("Short", "Regular"), so they share that chart rather than
# duplicating it.
GARMENT_LENGTH_CHART_IN["Vests"] = GARMENT_LENGTH_CHART_IN["Tops"]

# A co-ord set is tagged with one length, describing whichever half carries it
# ("Calf" for the skirt of a vest-and-skirt set, "Cropped" for the trousers).
# Resolved by trying these charts in order and taking the first that defines the
# class -- the vocabularies barely overlap, so this is unambiguous in practice.
COORD_LENGTH_CHART_ORDER = ("Skirts", "Trousers")

# The models the length guide was shot on, from each product's own description
# ("Model: Lori is 5.6 ft and wears a size XXS.").
#
# "5.6 ft" is read as 5 feet 6 inches, not 5.6 decimal feet -- the convention
# this label writes heights in. Both readings are within ~3cm and the advice
# below is a coarse "sits higher / lower" judgement, so the choice is not
# load-bearing; it is isolated here so it takes one edit if that is ever wrong.
MODEL_HEIGHTS_CM = {"Lori": 167.6, "Beatriz": 172.7}   # 5'6", 5'8"

# Height at which a garment lands exactly where the guide says it does. Every
# product but four is shot on Lori, and the length guide's own numbers are
# consistent with her, so she is the reference the chart describes.
LENGTH_CHART_REFERENCE_HEIGHT_CM = MODEL_HEIGHTS_CM["Lori"]

# How far a hem must move before the note says so rather than "much the same".
# In CENTIMETRES on the customer's own body, deliberately: this replaced a
# threshold expressed as a fraction of the length class's chart range, which
# made the note's behaviour depend on how precisely Eighth Hour happened to
# write that row of their guide rather than on anything a customer experiences.
# The ranges run from 0.5" to 2", so a vest spoke up once you were 3.8cm taller
# than the fit model while a skirt stayed silent until 12cm -- even though the
# skirt's hem physically moves further, being the longer garment.
#
# 1.5cm is about the point where a hem sits visibly off where it is pictured.
# Below it the note says the length falls as shown, which is still worth
# saying -- the advice appears on every recommendation, so silence would read
# as missing information rather than as reassurance.
LENGTH_NOTE_SAME_AS_SHOWN_CM = 1.5

FIT_NOTE_RELEVANT_DIMENSIONS = {
    "Tops": {"bust"},
    "Vests": {"bust"},
    "Dresses": {"bust", "waist", "hips"},
    "Co-ord Sets": {"bust", "waist", "hips"},
    "Skirts": {"waist", "hips"},
    "Trousers": {"waist", "hips"},
}
FIT_NOTE_RELEVANT_DIMENSIONS["Jackets"] = set(FIT_NOTE_RELEVANT_DIMENSIONS["Tops"])

# Styling advice on the product page, for her shape (M3's classes) and the
# piece's silhouette -- standard styling guidance for each figure: show a
# defined waist (hourglass); balance fuller hips (pear); skim the middle
# (apple); add volume below to balance the shoulders (athletic); create or
# enjoy clean lines (straight); most things work (balanced). An entry is one
# sentence, or one per garment type ("top": tops, vests, jackets; "bottom":
# skirts, trousers; "full": dresses, co-ord sets) where the advice differs.
# Copy, not a model: the brand can rewrite any of it.
CATEGORY_ZONE = {
    "Tops": "top", "Vests": "top", "Jackets": "top",
    "Skirts": "bottom", "Trousers": "bottom",
    "Dresses": "full", "Co-ord Sets": "full",
}
# Which of a piece's silhouettes the tip speaks to, most telling first.
SILHOUETTE_TIP_ORDER = ["a_line", "fitted", "oversized", "straight", "flowing"]
STYLING_TIPS = {
    "hourglass": {
        "fitted": "Fitted pieces follow your defined waist, the line that suits you best.",
        "a_line": "The A-line shape marks your waist and flares gently from it, keeping your curves balanced.",
        "flowing": "Flowing fabric can soften your waist; a belt or a front tuck keeps your shape defined.",
        "straight": "A straight cut skims past your waist; tuck it in or add a belt to show your shape.",
        "oversized": "Balance the extra volume by defining your waist; a belt works well.",
    },
    "pear": {
        "fitted": {
            "top": "Fitted through the top, it shows off your shoulders and waist and balances fuller hips.",
            "bottom": "A close fit through the hips draws the eye there; pair it with a structured or detailed top for balance.",
            "full": "The fitted shape shows your waist; one with a little ease through the skirt will skim your hips.",
        },
        "a_line": "The A-line flares past your hips without clinging, one of the most balancing shapes for you.",
        "flowing": "Flowing fabric falls softly past your hips rather than clinging to them.",
        "straight": {
            "top": "A straight cut skims past your hips; a defined shoulder or neckline balances your shape.",
            "bottom": "A straight line from hip to hem balances fuller hips and lengthens your legs.",
            "full": "A straight cut skims past your hips; draw the eye up with a defined shoulder or neckline.",
        },
        "oversized": "Keep the volume on top and a cleaner line below to balance your hips.",
    },
    "apple": {
        "fitted": "A close fit at the waist can cling; choose your size for the middle, or wear it open or layered.",
        "a_line": "The A-line falls away from your waist, skimming your middle and lengthening your shape.",
        "flowing": "Flowing lines skim your middle rather than clinging to it, easy and flattering on you.",
        "straight": "A straight cut skims your middle and gives you a long, clean line.",
        "oversized": "Easy through the middle; balance the volume with a slimmer line below.",
    },
    "athletic": {
        "fitted": {
            "top": "A fitted top highlights your shoulders; an open or V neck softens them.",
            "bottom": "A close fit through the hips adds shape below your waist, balancing your shoulders.",
            "full": "The fitted shape defines your waist; a fuller skirt balances your shoulders.",
        },
        "a_line": "The A-line adds volume below your waist to balance your shoulders.",
        "flowing": "Flowing pieces soften your shoulders and add movement below.",
        "straight": {
            "top": "A clean, straight top keeps your shoulders understated.",
            "bottom": "A straight line keeps you long; a wider leg or fuller hem adds balance to your shoulders.",
            "full": "A straight cut keeps a clean line; a belt adds definition at your waist.",
        },
        "oversized": "Keep the volume away from your shoulders, with a defined waist or a slimmer top.",
    },
    "straight": {
        "fitted": "A fitted cut creates shape at your waist.",
        "a_line": "The A-line flare adds curve at your hips and definition at your waist.",
        "flowing": "Flowing fabric adds movement and softness to your straight frame.",
        "straight": "Clean, straight lines suit your frame; a belt adds waist definition when you want it.",
        "oversized": "Relaxed volume suits your frame; a belt or a tuck adds shape when you want it.",
    },
    "balanced": {
        "fitted": "With your balanced proportions, a fitted cut simply follows your shape.",
        "a_line": "Your balanced proportions suit the A-line's gentle flare.",
        "flowing": "Flowing pieces drape easily on your balanced frame.",
        "straight": "A straight cut keeps a clean line on your balanced frame.",
        "oversized": "Relaxed volume works on your balanced frame; define the waist for more shape.",
    },
}

# Fabrics by give, for advice on choosing between two sizes. Matched as words
# in the piece's fabric; anything unrecognised gets advice that doesn't assume.
LOW_GIVE_FABRICS = ("silk", "satin", "linen", "cotton", "crepe", "wool", "chiffon", "georgette", "organza", "taffeta")
STRETCH_FABRICS = ("stretch", "jersey", "knit", "elastane", "spandex", "lycra")

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
    # Sized on the bust like a top, so it shows the profile's tops size.
    "Jackets": "tops",
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
