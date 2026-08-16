"""
The write-side and read-side measurement validators must agree.

This file exists because of a real, hard-to-diagnose failure. A photo scan
produced a shoulder of 26.5cm. `InputValidator.validate_measurements` -- which
guards every write -- did not check shoulder at all, so the session was stored
happily. `utils.sizing.validate_measurements` -- which M7 (fit checker) and M9
(new releases) run when they READ a session -- requires 30-60cm, so both
answered 400 forever after. M5 (recommendations) does not validate shoulder, so
it kept working, and the customer saw two features insist they had no style
profile while a third served them recommendations from the same session.

The lesson generalises past shoulder: anything accepted on write must be
readable afterwards. A field validated in only one direction is a latent trap,
so these tests compare the two validators directly rather than checking any
particular field.
"""

import pytest

from py_src.constants import MEASUREMENT_RANGES
from py_src.guardrails.input_validation import InputValidator
from py_src.utils.errors import ModuleError
from py_src.utils.sizing import validate_measurements as validate_on_read

# A body that every validator should be happy with.
BASE = {"bust": 93.0, "waist": 73.0, "hips": 98.0, "height": 168.0}

OPTIONAL_FIELDS = ("shoulder", "inseam")


def accepted_on_write(measurements):
    return InputValidator.validate_measurements(measurements)["valid"]


def accepted_on_read(measurements):
    try:
        validate_on_read(dict(measurements))
        return True
    except ModuleError:
        return False


class TestAnythingWritableIsReadable:
    """The invariant that was violated."""

    @pytest.mark.parametrize("field", MEASUREMENT_RANGES)
    def test_a_value_just_outside_the_range_is_refused_on_write(self, field):
        """
        If write accepts an out-of-range value, it becomes a stored session that
        the fit checker and new-releases feed can never read.
        """
        low, high = MEASUREMENT_RANGES[field]
        for bad in (low - 1, high + 1):
            payload = {**BASE, field: bad}
            assert not accepted_on_write(payload), (
                f"{field}={bad} is outside {low}-{high} but was accepted on write; "
                f"it would be stored and then rejected on read"
            )

    @pytest.mark.parametrize("field", MEASUREMENT_RANGES)
    def test_the_two_validators_agree_at_the_boundaries(self, field):
        low, high = MEASUREMENT_RANGES[field]
        for value in (low, high, (low + high) / 2):
            payload = {**BASE, field: value}
            assert accepted_on_write(payload) == accepted_on_read(payload), (
                f"{field}={value}: write and read disagree — this is the exact "
                f"shape of the shoulder bug"
            )

    @pytest.mark.parametrize("field", OPTIONAL_FIELDS)
    def test_optional_fields_are_range_checked_on_write(self, field):
        """
        shoulder and inseam are optional, which is why they were overlooked.
        Optional means "may be absent", not "may be any value".
        """
        low, high = MEASUREMENT_RANGES[field]
        assert accepted_on_write({**BASE, field: (low + high) / 2})
        assert not accepted_on_write({**BASE, field: high + 50})

    @pytest.mark.parametrize("field", OPTIONAL_FIELDS)
    def test_omitting_an_optional_field_is_still_fine(self, field):
        payload = {k: v for k, v in BASE.items() if k != field}
        assert accepted_on_write(payload)
        assert accepted_on_read(payload)


class TestRangesComeFromOneSource:
    def test_the_write_validator_uses_the_shared_ranges(self):
        """
        Hardcoded copies are how the two drifted apart: inseam was 60-100 on
        write and 50-120 on read, so a legitimate inseam was refused on entry.
        """
        for field, (low, high) in MEASUREMENT_RANGES.items():
            just_inside = {**BASE, field: low}
            just_outside = {**BASE, field: low - 0.5}
            assert accepted_on_write(just_inside), f"{field}={low} should be valid"
            assert not accepted_on_write(just_outside), f"{field}={low - 0.5} should be invalid"
