"""
Tests for py_src.utils.sizing -- shared measurement utilities used directly
by M3, M5, M7, and M9. Previously only exercised indirectly through those
modules' own test suites; this covers the utility functions in isolation.
"""

import pytest
from py_src.utils.sizing import (
    extract_physical_measurements,
    validate_measurements,
    infer_size_from_bust,
    PHYSICAL_MEASUREMENT_FIELDS,
)
from py_src.utils.errors import ModuleError


class TestExtractPhysicalMeasurements:
    def test_keeps_only_physical_fields(self):
        raw = {
            "bust": 88.0, "waist": 70.0, "hips": 102.0, "height": 165.0,
            "shoulder": None, "inseam": None,
            "unit": "cm", "confidence_scores": {"bust": 0.95},
            "provider": "manual_entry", "provider_version": "1.0",
            "extracted_at": 1234567890.0,
        }
        cleaned = extract_physical_measurements(raw)
        assert set(cleaned.keys()) == {"bust", "waist", "hips", "height"}
        assert cleaned["bust"] == 88.0

    def test_drops_none_valued_optional_fields(self):
        cleaned = extract_physical_measurements({"bust": 88.0, "shoulder": None})
        assert "shoulder" not in cleaned
        assert cleaned["bust"] == 88.0

    def test_keeps_non_none_optional_fields(self):
        cleaned = extract_physical_measurements({"bust": 88.0, "shoulder": 40.0})
        assert cleaned["shoulder"] == 40.0

    def test_non_dict_input_returns_empty_dict(self):
        assert extract_physical_measurements(None) == {}
        assert extract_physical_measurements("not a dict") == {}
        assert extract_physical_measurements([1, 2, 3]) == {}

    def test_empty_dict_returns_empty_dict(self):
        assert extract_physical_measurements({}) == {}

    def test_covers_all_physical_fields(self):
        """Sanity check that the field set matches what validate_measurements checks."""
        assert PHYSICAL_MEASUREMENT_FIELDS == {"bust", "waist", "hips", "height", "shoulder", "inseam"}


class TestValidateMeasurements:
    def test_accepts_clean_measurements(self):
        validate_measurements({"bust": 88.0, "waist": 70.0, "hips": 102.0, "height": 165.0})
        # No exception = success

    def test_accepts_full_to_dict_style_payload(self):
        """
        Regression test: this function used to loop over EVERY key in
        whatever dict it was given and demand each be numeric. A full
        Measurements.to_dict() payload always includes unit="cm" (a
        string), so it unconditionally rejected every request -- this is
        exactly what made M7's "Check Fit" and M9's "New Releases" crash
        on every single call in production.
        """
        full_payload = {
            "bust": 88.0, "waist": 70.0, "hips": 102.0, "height": 165.0,
            "shoulder": None, "inseam": None,
            "unit": "cm", "confidence_scores": {"bust": 0.95},
            "provider": "manual_entry", "provider_version": "1.0",
            "extracted_at": 1234567890.0,
        }
        validate_measurements(full_payload)  # Must not raise

    def test_rejects_missing_required_field(self):
        with pytest.raises(ModuleError, match="Missing required measurements"):
            validate_measurements({"bust": 88.0, "waist": 70.0, "height": 165.0})

    def test_rejects_non_numeric_value(self):
        with pytest.raises(ModuleError, match="must be numeric"):
            validate_measurements({"bust": "not a number", "waist": 70.0, "hips": 102.0, "height": 165.0})

    def test_rejects_negative_or_zero_value(self):
        with pytest.raises(ModuleError, match="must be positive"):
            validate_measurements({"bust": 0, "waist": 70.0, "hips": 102.0, "height": 165.0})

    def test_rejects_out_of_range_value(self):
        with pytest.raises(ModuleError, match="Invalid bust"):
            validate_measurements({"bust": 500.0, "waist": 70.0, "hips": 102.0, "height": 165.0})

    def test_optional_shoulder_out_of_range_still_rejected(self):
        """Optional fields are still range-checked when actually provided."""
        with pytest.raises(ModuleError, match="Invalid shoulder"):
            validate_measurements({
                "bust": 88.0, "waist": 70.0, "hips": 102.0, "height": 165.0,
                "shoulder": 200.0,
            })

    def test_optional_shoulder_none_is_not_validated(self):
        """A None shoulder must be dropped before range-checking, not rejected as non-numeric."""
        validate_measurements({
            "bust": 88.0, "waist": 70.0, "hips": 102.0, "height": 165.0,
            "shoulder": None,
        })  # Must not raise


class TestInferSizeFromBust:
    def test_returns_valid_size_string(self):
        assert infer_size_from_bust(90) in ["XXS", "XS", "S", "M", "L", "XL", "XXL"]

    def test_raises_on_out_of_range_bust(self):
        with pytest.raises(ModuleError, match="outside valid range"):
            infer_size_from_bust(9999)

    def test_raises_on_non_numeric_bust(self):
        with pytest.raises(ModuleError):
            infer_size_from_bust("not a number")
