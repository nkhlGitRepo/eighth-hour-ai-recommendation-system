"""
Shared sizing utilities for measurement-based size inference.

Centralized logic to ensure consistency across M5, M7, M9, and other modules.
"""

from py_src.constants import SIZE_BOUNDARIES, MEASUREMENT_RANGES
from py_src.utils.errors import ModuleError

PHYSICAL_MEASUREMENT_FIELDS = {"bust", "waist", "hips", "height", "shoulder", "inseam"}


def infer_size_from_bust(bust: float) -> str:
    """
    Infer garment size from bust measurement (cm).

    Args:
        bust: Bust measurement in cm

    Returns:
        Size string (XS, S, M, L, XL, XXL)

    Raises:
        ModuleError: If bust outside valid range
    """
    # Validate range
    min_bust, max_bust = MEASUREMENT_RANGES["bust"]
    if not isinstance(bust, (int, float)) or bust < min_bust or bust > max_bust:
        raise ModuleError(
            f"Bust {bust}cm outside valid range {min_bust}-{max_bust}cm",
            "Sizing"
        )

    # Find matching size
    for size, (lower, upper) in SIZE_BOUNDARIES.items():
        if lower <= bust < upper:
            return size

    # Fallback (should not reach with valid range check above)
    return "XXL"


def extract_physical_measurements(measurements: dict) -> dict:
    """
    Strip a measurements dict down to just the physical fields
    validate_measurements()/infer_size_from_bust() understand, dropping
    both unrelated metadata (unit, confidence_scores, provider, ...) and
    any physical field the customer never provided.

    Callers that receive a full Measurements.to_dict() payload (which
    always includes non-numeric metadata like unit="cm") must pass it
    through this before validating -- otherwise validate_measurements()
    unconditionally rejects every request, since it checks that EVERY
    key in the dict it's given is numeric.

    Args:
        measurements: Raw measurements dict, possibly with extra metadata
            keys and/or None values for unprovided optional fields

    Returns:
        Dict containing only physical measurement fields with non-None values
    """
    if not isinstance(measurements, dict):
        return {}
    return {
        field: value
        for field, value in measurements.items()
        if field in PHYSICAL_MEASUREMENT_FIELDS and value is not None
    }


def validate_measurements(measurements: dict) -> None:
    """
    Validate all measurements are within acceptable ranges.

    Filters to PHYSICAL_MEASUREMENT_FIELDS internally, so it's safe to call
    directly with a full Measurements.to_dict() payload (unit,
    confidence_scores, provider, ...) -- this function used to loop over
    every key in whatever dict it was given and demand each one be numeric,
    so passing it a to_dict() payload unconditionally rejected every
    request (unit="cm" always failed the numeric check). Named the same as
    the unrelated InputValidator.validate_measurements (which IS already
    safe with extra keys, since it reads named fields explicitly) -- that
    naming collision is exactly what let the bug hide for so long.

    Args:
        measurements: Dict with optional bust, waist, hips, height, shoulder,
            inseam, possibly alongside unrelated metadata keys

    Raises:
        ModuleError: If any required measurement is missing, or any provided
            measurement is invalid or out of range
    """
    measurements = extract_physical_measurements(measurements)

    required = {"bust", "waist", "hips", "height"}
    missing = required - set(measurements.keys())
    if missing:
        raise ModuleError(f"Missing required measurements: {missing}", "Sizing")

    for field, value in measurements.items():
        # Check type
        if not isinstance(value, (int, float)):
            raise ModuleError(f"Measurement {field} must be numeric", "Sizing")

        # Check value > 0
        if value <= 0:
            raise ModuleError(f"Measurement {field}={value} must be positive", "Sizing")

        # Check range if defined
        if field in MEASUREMENT_RANGES:
            min_val, max_val = MEASUREMENT_RANGES[field]
            if value < min_val or value > max_val:
                raise ModuleError(
                    f"Invalid {field} {value}cm: expected {min_val}-{max_val}cm",
                    "Sizing"
                )
