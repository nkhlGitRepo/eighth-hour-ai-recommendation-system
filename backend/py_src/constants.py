"""Shared constants across modules."""

BODY_SHAPE_CLASSES = ["balanced", "pear", "apple", "hourglass", "straight", "athletic"]

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

# Size boundaries for measurement-based inference (bust in cm)
# Used by M5 (recommendation engine), M7 (fit checker), M9 (new releases)
SIZE_BOUNDARIES = {
    "XS": (0, 80),      # < 80
    "S": (80, 84),      # >= 80 and < 84
    "M": (84, 90),      # >= 84 and < 90
    "L": (90, 96),      # >= 90 and < 96
    "XL": (96, 102),    # >= 96 and < 102
    "XXL": (102, 999),  # >= 102
}

# Measurement validation ranges (cm)
MEASUREMENT_RANGES = {
    "height": (140, 210),      # cm
    "bust": (60, 140),         # cm
    "waist": (60, 140),        # cm
    "hips": (60, 140),         # cm
    "shoulder": (30, 60),      # cm (optional)
    "inseam": (50, 120),       # cm (optional)
}

# New releases feed configuration
NEW_RELEASES_MATCH_THRESHOLD = 0.65  # Minimum match score to include in feed

# Learning loop feedback types (M10)
FIT_FEEDBACK_TYPES = ["too_tight", "perfect", "too_loose"]
PRODUCT_FEEDBACK_TYPES = ["liked", "disliked", "neutral"]
