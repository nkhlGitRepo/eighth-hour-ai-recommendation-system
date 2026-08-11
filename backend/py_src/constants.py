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

# Standard size chart: bust, waist, hips measurements in cm
STANDARD_SIZE_CHART = {
    "XS": {"bust": 78, "waist": 60, "hips": 85},
    "S": {"bust": 84, "waist": 66, "hips": 91},
    "M": {"bust": 90, "waist": 72, "hips": 97},
    "L": {"bust": 96, "waist": 78, "hips": 103},
    "XL": {"bust": 102, "waist": 84, "hips": 109},
    "XXL": {"bust": 108, "waist": 90, "hips": 115},
}

# Size boundaries for measurement-based inference (bust in cm).
# Single source of truth for bust-based sizing -- must match M3's own
# size_by_bust chart exactly, since M3 computes the size shown to the
# customer and this chart is used to filter/rank what gets recommended.
# Used by M3 (body shape profiler), M5 (recommendation engine), M9 (new releases)
SIZE_BOUNDARIES = {
    "XXS": (70, 76),
    "XS": (76, 84),
    "S": (84, 92),
    "M": (92, 100),
    "L": (100, 108),
    "XL": (108, 117),
    "XXL": (117, 150),
}

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

# Learning loop feedback types (M10)
FIT_FEEDBACK_TYPES = ["too_tight", "perfect", "too_loose"]
PRODUCT_FEEDBACK_TYPES = ["liked", "disliked", "neutral"]
