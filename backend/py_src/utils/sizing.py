"""
Shared sizing utilities for measurement-based size inference.

Centralized logic to ensure consistency across M5, M7, M9, and other modules.
"""

from py_src.constants import SIZE_BOUNDARIES, MEASUREMENT_RANGES
from py_src.utils.errors import ModuleError


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


def validate_measurements(measurements: dict) -> None:
    """
    Validate all measurements are within acceptable ranges.

    Args:
        measurements: Dict with optional bust, waist, hips, height, shoulder, inseam

    Raises:
        ModuleError: If any measurement is invalid or out of range
    """
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
