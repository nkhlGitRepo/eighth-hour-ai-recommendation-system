"""Integration tests for M3 + M6 workflow."""

import pytest
from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
from py_src.modules.m6_catalog_kb import CatalogKB
from tests.fixtures import MEASUREMENTS, PRODUCTS


class TestIntegration:
    """Integration tests for complete styling workflow."""

    def setup_method(self):
        """Set up test fixtures."""
        self.profiler = BodyShapeProfiler()
        self.catalog = CatalogKB(PRODUCTS)

    def test_workflow_pear_shape_retrieve_recommendations(self):
        """PEAR shape should retrieve relevant recommendations."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        shape_class = profile["shape_class"]
        results = self.catalog.retrieve({"shape_class": shape_class, "categories": ["Tops", "Skirts"]})
        assert len(results) > 0
        assert profile["shape_class"] == "pear"

    def test_workflow_hourglass_shape_retrieve_recommendations(self):
        """HOURGLASS shape should retrieve relevant recommendations."""
        profile = self.profiler.profile(MEASUREMENTS["hourglass"])
        shape_class = profile["shape_class"]
        results = self.catalog.retrieve({"shape_class": shape_class, "categories": ["Dresses"]})
        assert len(results) > 0
        assert profile["shape_class"] == "hourglass"

    def test_workflow_apple_shape_retrieve_recommendations(self):
        """APPLE shape should retrieve relevant recommendations."""
        profile = self.profiler.profile(MEASUREMENTS["apple"])
        shape_class = profile["shape_class"]
        results = self.catalog.retrieve({"shape_class": shape_class})
        assert len(results) > 0
        assert profile["shape_class"] == "apple"

    def test_workflow_athletic_shape_retrieve_recommendations(self):
        """ATHLETIC shape should retrieve relevant recommendations."""
        profile = self.profiler.profile(MEASUREMENTS["athletic"])
        shape_class = profile["shape_class"]
        results = self.catalog.retrieve({"shape_class": shape_class})
        assert len(results) > 0
        assert profile["shape_class"] == "athletic"

    def test_workflow_straight_shape_retrieve_recommendations(self):
        """STRAIGHT shape should retrieve relevant recommendations."""
        profile = self.profiler.profile(MEASUREMENTS["straight"])
        shape_class = profile["shape_class"]
        results = self.catalog.retrieve({"shape_class": shape_class})
        assert len(results) > 0
        assert profile["shape_class"] == "straight"

    def test_workflow_balanced_shape_retrieve_recommendations(self):
        """BALANCED shape should retrieve relevant recommendations."""
        profile = self.profiler.profile(MEASUREMENTS["balanced"])
        shape_class = profile["shape_class"]
        results = self.catalog.retrieve({"shape_class": shape_class})
        assert len(results) > 0
        assert profile["shape_class"] == "balanced"

    def test_workflow_build_complete_outfit(self):
        """Should build outfit across multiple categories."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        tops = self.catalog.retrieve({"shape_class": profile["shape_class"], "categories": ["Tops"], "k": 2})
        skirts = self.catalog.retrieve({"shape_class": profile["shape_class"], "categories": ["Skirts"], "k": 2})
        assert len(tops) > 0
        assert len(skirts) > 0

    def test_workflow_integrate_color_preferences(self):
        """Should integrate color preferences."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        results = self.catalog.retrieve({"shape_class": profile["shape_class"], "preferred_colors": ["Black", "Navy"], "k": 5})
        for result in results:
            assert any(color in result["colors"] for color in ["Black", "Navy"])

    def test_workflow_integrate_fabric_preferences(self):
        """Should integrate fabric preferences."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        results = self.catalog.retrieve({"shape_class": profile["shape_class"], "fabrics": ["Cotton"], "k": 5})
        for result in results:
            assert result["fabric"] == "Cotton"

    def test_workflow_validate_size_availability(self):
        """Should check size availability before recommending."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        size_rec = profile["size_recommendation_by_category"]
        top_size = size_rec["tops"]
        results = self.catalog.retrieve({"shape_class": profile["shape_class"], "size": top_size})
        for result in results:
            assert top_size in result["sizes_in_stock"]

    def test_workflow_recommendations_have_complete_data(self):
        """Recommendations should have all required fields."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        results = self.catalog.retrieve({"shape_class": profile["shape_class"]})
        required_fields = ["sku", "name", "category", "price", "colors", "sizes"]
        for result in results:
            for field in required_fields:
                assert field in result, f"Missing field: {field}"

    def test_workflow_handles_invalid_measurements_gracefully(self):
        """Invalid measurements should raise error gracefully."""
        from py_src.utils.errors import ModuleError
        with pytest.raises(ModuleError):
            self.profiler.profile(MEASUREMENTS["invalid_too_small"])

    def test_workflow_produces_consistent_results(self):
        """Same inputs should produce same outputs."""
        profile1 = self.profiler.profile(MEASUREMENTS["balanced"])
        profile2 = self.profiler.profile(MEASUREMENTS["balanced"])
        assert profile1["shape_class"] == profile2["shape_class"]
        results1 = self.catalog.retrieve({"shape_class": profile1["shape_class"], "k": 5})
        results2 = self.catalog.retrieve({"shape_class": profile2["shape_class"], "k": 5})
        assert len(results1) == len(results2)

    def test_workflow_all_shapes_have_recommendations(self):
        """Every shape should have at least one recommendation."""
        valid_shapes = ["pear", "hourglass", "apple", "athletic", "straight", "balanced"]
        for shape in valid_shapes:
            measurements = MEASUREMENTS[shape]
            profile = self.profiler.profile(measurements)
            results = self.catalog.retrieve({"shape_class": profile["shape_class"]})
            assert len(results) > 0, f"{shape} should have recommendations"

    def test_workflow_recommendations_match_size(self):
        """Size recommendations from M3 should match available sizes."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        top_size = profile["size_recommendation_by_category"]["tops"]
        results = self.catalog.retrieve({"shape_class": profile["shape_class"], "size": top_size})
        for result in results:
            assert top_size in result["sizes"], f"Size {top_size} not in {result['sizes']}"

    def test_workflow_profile_data_completeness(self):
        """Profile should have all expected fields."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        required_fields = ["shape_class", "ratios", "size_recommendation_by_category", "fit_notes", "profile_version"]
        for field in required_fields:
            assert field in profile, f"Missing field: {field}"
            assert profile[field] is not None

    def test_workflow_different_shapes_get_different_profiles(self):
        """Different measurements should produce different shapes."""
        pear_profile = self.profiler.profile(MEASUREMENTS["pear"])
        hourglass_profile = self.profiler.profile(MEASUREMENTS["hourglass"])
        apple_profile = self.profiler.profile(MEASUREMENTS["apple"])
        shapes = {pear_profile["shape_class"], hourglass_profile["shape_class"], apple_profile["shape_class"]}
        assert len(shapes) >= 3

    def test_workflow_mixed_filters_work_together(self):
        """Multiple filters should all apply."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        results = self.catalog.retrieve({
            "shape_class": profile["shape_class"],
            "categories": ["Tops"],
            "preferred_colors": ["Black"],
            "fabrics": ["Cotton"],
            "k": 5,
        })
        for result in results:
            assert result["category"] == "Tops"
            assert "Black" in result["colors"]
            assert result["fabric"] == "Cotton"

    def test_workflow_recommendations_are_diverse(self):
        """Should retrieve different items, not duplicates."""
        profile = self.profiler.profile(MEASUREMENTS["balanced"])
        results = self.catalog.retrieve({"shape_class": profile["shape_class"], "k": 10})
        skus = [item["sku"] for item in results]
        assert len(skus) == len(set(skus)), "Duplicate items in results"

    def test_workflow_handles_empty_preferences(self):
        """Should handle empty/minimal preferences."""
        profile = self.profiler.profile(MEASUREMENTS["pear"])
        results = self.catalog.retrieve({"shape_class": profile["shape_class"]})
        assert len(results) > 0
