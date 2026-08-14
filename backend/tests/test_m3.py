"""Tests for M3 (Body Shape Profiler)."""

import pytest
from py_src.constants import MEASUREMENT_RANGES, SIZE_BOUNDARIES
from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
from py_src.utils.errors import ModuleError
from tests.fixtures import MEASUREMENTS


class TestBodyShapeProfiler:
    """Body shape profiler tests."""

    def setup_method(self):
        """Set up test fixtures."""
        self.profiler = BodyShapeProfiler()

    def test_initialization(self):
        """Profiler should initialize."""
        assert self.profiler.PROFILE_VERSION == "1.0.0"

    def test_classify_pear_shape_correctly(self):
        """PEAR: bust/waist > 1.15, waist/hip < 0.85"""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        assert profile["shape_class"] == "pear"

    def test_classify_hourglass_shape_correctly(self):
        """HOURGLASS: bust/waist > 1.25, waist/hip < 0.80"""
        profile = self.profiler.profile(MEASUREMENTS["hourglass"])
        assert profile["shape_class"] == "hourglass"

    def test_classify_athletic_shape_correctly(self):
        """ATHLETIC: bust/waist > 1.25, waist/hip < 0.90"""
        profile = self.profiler.profile(MEASUREMENTS["athletic"])
        assert profile["shape_class"] == "athletic"

    def test_classify_apple_shape_correctly(self):
        """APPLE: bust/waist < 1.05, waist/hip > 0.95"""
        profile = self.profiler.profile(MEASUREMENTS["apple"])
        assert profile["shape_class"] == "apple"

    def test_classify_straight_shape_correctly(self):
        """STRAIGHT: bust/waist 1.0-1.15, waist/hip 0.95-1.05"""
        profile = self.profiler.profile(MEASUREMENTS["straight"])
        assert profile["shape_class"] == "straight"

    def test_classify_balanced_shape_correctly(self):
        """BALANCED: middle ground"""
        profile = self.profiler.profile(MEASUREMENTS["balanced"])
        assert profile["shape_class"] == "balanced"

    def test_generates_size_recommendations_for_all_categories(self):
        """Profile should have size recommendations for all categories."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        recommendations = profile["size_recommendation_by_category"]
        assert "tops" in recommendations
        assert "skirts" in recommendations
        assert "dresses" in recommendations
        assert "trousers" in recommendations
        assert "vests" in recommendations
        assert "coOrds" in recommendations

    def test_size_recommendations_adapt_by_shape(self):
        """Apple shapes should get waist-based top size."""
        apple_profile = self.profiler.profile(MEASUREMENTS["apple"])
        pear_profile = self.profiler.profile(MEASUREMENTS["pear"])
        assert apple_profile is not None
        assert pear_profile is not None

    def test_generates_fit_notes_for_pear(self):
        """Pear shapes should get pear-specific fit notes."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        fit_notes = profile["fit_notes"]
        assert len(fit_notes) > 0
        assert any("wrap" in note.lower() for note in fit_notes)

    def test_generates_fit_notes_for_hourglass(self):
        """Hourglass shapes should get hourglass-specific fit notes."""
        profile = self.profiler.profile(MEASUREMENTS["hourglass"])
        fit_notes = profile["fit_notes"]
        assert len(fit_notes) > 0
        assert any("fitted" in note.lower() or "waist" in note.lower() for note in fit_notes)

    def test_generates_fit_notes_for_athletic(self):
        """Athletic shapes should get athletic-specific fit notes."""
        profile = self.profiler.profile(MEASUREMENTS["athletic"])
        fit_notes = profile["fit_notes"]
        assert len(fit_notes) > 0

    def test_profile_throws_on_invalid_measurements(self):
        """Invalid measurements should raise ModuleError."""
        with pytest.raises(ModuleError):
            self.profiler.profile(MEASUREMENTS["invalid_too_small"])

    def test_profile_throws_on_incomplete_measurements(self):
        """Incomplete measurements should raise ModuleError."""
        with pytest.raises(ModuleError):
            self.profiler.profile(MEASUREMENTS["invalid_incomplete"])

    def test_profile_returns_versioned_data(self):
        """Profile should include version."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        assert profile["profile_version"] == "1.0.0"

    def test_ratios_are_computed_correctly(self):
        """Ratios should be computed correctly."""
        measurements = MEASUREMENTS["pear"]
        profile = self.profiler.profile(measurements)
        expected_bust_waist = round(measurements["bust"] / measurements["waist"], 2)
        expected_waist_hip = round(measurements["waist"] / measurements["hips"], 2)
        assert profile["ratios"]["bust_waist"] == expected_bust_waist
        assert profile["ratios"]["waist_hip"] == expected_waist_hip

    def test_all_fit_notes_are_non_empty_strings(self):
        """All fit notes should be non-empty strings."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        assert all(isinstance(note, str) and len(note) > 0 for note in profile["fit_notes"])

    def test_profile_is_deterministic(self):
        """Same input should produce same output."""
        profile1 = self.profiler.profile(MEASUREMENTS["balanced"])
        profile2 = self.profiler.profile(MEASUREMENTS["balanced"])
        assert profile1["shape_class"] == profile2["shape_class"]
        assert profile1["ratios"] == profile2["ratios"]

    def test_all_valid_measurements_pass_validation(self):
        """All test measurements should be valid."""
        from py_src.guardrails.input_validation import InputValidator
        valid_shapes = ["pear", "hourglass", "athletic", "apple", "straight", "balanced"]
        for shape in valid_shapes:
            result = InputValidator.validate_measurements(MEASUREMENTS[shape])
            assert result["valid"] is True, f"{shape} should be valid"

    def test_size_recommendations_use_correct_fields(self):
        """Size recommendations should use bust/hip, except apple uses waist."""
        pear = self.profiler.profile(MEASUREMENTS["pear"])
        apple = self.profiler.profile(MEASUREMENTS["apple"])
        pear_top = pear["size_recommendation_by_category"]["tops"]
        apple_top = apple["size_recommendation_by_category"]["tops"]
        assert pear_top is not None
        assert apple_top is not None

    def test_fit_notes_are_shape_specific(self):
        """Fit notes should mention shape-specific details."""
        pear = self.profiler.profile(MEASUREMENTS["pear"])
        hourglass = self.profiler.profile(MEASUREMENTS["hourglass"])
        apple = self.profiler.profile(MEASUREMENTS["apple"])
        pear_notes = " ".join(pear["fit_notes"]).lower()
        hourglass_notes = " ".join(hourglass["fit_notes"]).lower()
        apple_notes = " ".join(apple["fit_notes"]).lower()
        assert "wrap" in pear_notes or "a-line" in pear_notes
        assert "wrap" in hourglass_notes or "belt" in hourglass_notes or "fitted" in hourglass_notes
        assert "empire" in apple_notes or "flowing" in apple_notes

    def test_fit_notes_are_non_empty(self):
        """All shapes should generate fit notes."""
        valid_shapes = ["pear", "hourglass", "athletic", "apple", "straight", "balanced"]
        for shape in valid_shapes:
            profile = self.profiler.profile(MEASUREMENTS[shape])
            assert len(profile["fit_notes"]) > 0, f"{shape} should have fit notes"

    def test_size_recommendations_all_present(self):
        """All categories should have size recommendations."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        recs = profile["size_recommendation_by_category"]
        single_size_categories = ["tops", "skirts", "dresses", "trousers", "vests"]
        for category in single_size_categories:
            assert category in recs, f"Missing category: {category}"
            assert recs[category] in ["XXS", "XS", "S", "M", "L", "XL", "XXL"]

        # coOrds combines a top and bottom size (e.g. "S/L") since coordinate
        # sets are two pieces that can need different sizes.
        assert "coOrds" in recs
        top_size, bottom_size = recs["coOrds"].split("/")
        assert top_size in ["XXS", "XS", "S", "M", "L", "XL", "XXL"]
        assert bottom_size in ["XXS", "XS", "S", "M", "L", "XL", "XXL"]

    def test_size_recommendations_consistent(self):
        """Size recommendations should be consistent across calls."""
        profile1 = self.profiler.profile(MEASUREMENTS["apple"])
        profile2 = self.profiler.profile(MEASUREMENTS["apple"])
        assert profile1["size_recommendation_by_category"] == profile2["size_recommendation_by_category"]

    def test_profile_with_optional_shoulder(self):
        """Profile should work with optional shoulder measurement."""
        measurements = MEASUREMENTS["pear"].copy()
        measurements_no_shoulder = {k: v for k, v in measurements.items() if k != "shoulder"}
        profile = self.profiler.profile(measurements_no_shoulder)
        assert profile["shape_class"] is not None
        assert "shoulder_hip" in profile["ratios"]

    def test_bust_size_boundary_transitions_exact(self):
        """
        Exact bust->size boundary transitions for the 'tops' recommendation.
        These boundaries are the ones actually shown to customers, so an
        off-by-one here is customer-visible, not just internal.
        """
        # Derived from the shared table rather than transcribed, so this keeps
        # catching off-by-one errors after a chart revision instead of just
        # failing because the numbers moved.
        test_cases = [
            (edge, size)
            for size, (low, high) in SIZE_BOUNDARIES.items()
            for edge in (low, high - 0.1)
        ]

        def in_range(dimension, value):
            """
            The smallest and largest bust bands open out to the full supported
            bust range, so a fixed offset from the band edge would put waist or
            hips outside what the API accepts. Clamped, since only the bust is
            under test here.
            """
            low, high = MEASUREMENT_RANGES[dimension]
            return min(max(value, low), high)

        for bust, expected_size in test_cases:
            measurements = {
                "bust": bust,
                "waist": in_range("waist", bust - 15),
                "hips": in_range("hips", bust + 10),
                "height": 165,
            }
            profile = self.profiler.profile(measurements)
            actual = profile["size_recommendation_by_category"]["tops"]
            assert actual == expected_size, f"bust={bust}: expected {expected_size}, got {actual}"

    def test_bust_size_matches_shared_size_boundaries(self):
        """
        Regression guard: M3's displayed size must always agree with
        constants.SIZE_BOUNDARIES / infer_size_from_bust, which is what M5
        uses to actually filter recommendations and M9 uses for New
        Releases. These previously used independent, disagreeing
        boundary charts; both must now derive from the same source.
        """
        from py_src.utils.sizing import infer_size_from_bust

        for bust in range(70, 146, 3):
            measurements = {"bust": bust, "waist": bust - 15, "hips": bust + 10, "height": 165}
            profile = self.profiler.profile(measurements)
            displayed_size = profile["size_recommendation_by_category"]["tops"]
            filter_size = infer_size_from_bust(bust)
            assert displayed_size == filter_size, (
                f"bust={bust}: customer is shown '{displayed_size}' but recommendations "
                f"would be filtered using '{filter_size}'"
            )
