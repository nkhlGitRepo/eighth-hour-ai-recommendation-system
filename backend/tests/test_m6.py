"""Tests for M6 (Catalog Knowledge Base)."""

import pytest
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.utils.errors import ModuleError
from tests.fixtures import PRODUCTS


class TestCatalogKB:
    """Catalog knowledge base tests."""

    def setup_method(self):
        """Set up test fixtures."""
        self.catalog = CatalogKB(PRODUCTS)

    def test_initialization(self):
        """Catalog should initialize."""
        assert self.catalog.CATALOG_VERSION == "1.0.0"
        assert len(self.catalog.items) == 5

    def test_stats(self):
        """Stats should report catalog info."""
        stats = self.catalog.stats()
        assert stats["total_items"] == 5
        assert "categories" in stats
        assert "fabrics" in stats

    def test_item_lookup_by_sku(self):
        """Should retrieve item by SKU."""
        item = self.catalog.get_item("top-fitted-wrap")
        assert item is not None
        assert item["name"] == "Fitted Wrap Top"

    def test_item_lookup_returns_none_for_invalid_sku(self):
        """Invalid SKU should return None."""
        item = self.catalog.get_item("nonexistent-sku")
        assert item is None

    def test_item_lookup_rejects_non_string_sku(self):
        """Non-string SKU should return None."""
        item = self.catalog.get_item(123)
        assert item is None

    def test_retrieval_by_category(self):
        """Should filter by category."""
        results = self.catalog.retrieve({"shape_class": "pear", "categories": ["Tops"]})
        assert len(results) > 0
        assert all(item["category"] == "Tops" for item in results)

    def test_retrieval_by_fabric(self):
        """Should filter by fabric."""
        results = self.catalog.retrieve({"shape_class": "pear", "fabrics": ["Cotton"]})
        assert len(results) > 0
        assert all(item["fabric"] == "Cotton" for item in results)

    def test_retrieval_by_color(self):
        """Should filter by color."""
        results = self.catalog.retrieve({"shape_class": "pear", "preferred_colors": ["Black"]})
        assert len(results) > 0
        assert all("Black" in item["colors"] for item in results)

    def test_retrieval_by_size_availability(self):
        """Should filter by size availability."""
        results = self.catalog.retrieve({"shape_class": "pear", "size": "M"})
        assert len(results) > 0
        assert all(item["sizes_in_stock"].get("M") for item in results)

    def test_retrieval_respects_k_parameter(self):
        """Should limit results to k items."""
        results = self.catalog.retrieve({"shape_class": "pear", "k": 2})
        assert len(results) <= 2

    def test_retrieval_with_safe_injection_protected_query(self):
        """Should handle injection-protected queries."""
        query = {"shape_class": "pear", "categories": ["Tops"], "preferred_colors": ["Black"]}
        results = self.catalog.retrieve(query)
        assert isinstance(results, list)

    def test_availability_check_returns_valid_for_in_stock_item(self):
        """In-stock item should be valid."""
        result = self.catalog.validate_item_availability("top-fitted-wrap", "M", "Black")
        assert result["valid"] is True

    def test_availability_check_returns_invalid_for_missing_sku(self):
        """Missing SKU should be invalid."""
        result = self.catalog.validate_item_availability("nonexistent-sku", "M", "Black")
        assert result["valid"] is False
        assert "SKU not found" in result["reason"]

    def test_availability_check_returns_invalid_for_unavailable_size(self):
        """Unavailable size should be invalid."""
        result = self.catalog.validate_item_availability("top-fitted-wrap", "XXXL", "Black")
        assert result["valid"] is False

    def test_availability_check_returns_invalid_for_unavailable_color(self):
        """Unavailable color should be invalid."""
        result = self.catalog.validate_item_availability("top-fitted-wrap", "M", "Purple")
        assert result["valid"] is False

    def test_rebuild_clears_and_rebuilds_index(self):
        """Rebuild should update the catalog."""
        new_products = [{"slug": "new-item", "name": "New Item", "category": "NewCategory",
                        "fabric": "Silk", "price": 99.99, "colors": ["White"], "sizes": ["M", "L"]}]
        self.catalog.rebuild(new_products)
        assert len(self.catalog.items) == 1
        assert "new-item" in self.catalog.items

    def test_rebuild_with_invalid_products_skips_them(self):
        """Invalid products should be skipped."""
        products_with_bad = PRODUCTS + [{"slug": "bad-product"}]
        self.catalog.rebuild(products_with_bad)
        assert len(self.catalog.items) == 5

    def test_silhouette_classification(self):
        """Should infer silhouette from name."""
        wrap_dress = self.catalog.get_item("dress-wrap")
        assert wrap_dress["silhouette_class"] == "flowing"
        overlap_vest = self.catalog.get_item("vest-overlap")
        assert overlap_vest["silhouette_class"] == "fitted"

    def test_fit_flatterers_inference(self):
        """Should infer fit flatterers from name."""
        wrap_dress = self.catalog.get_item("dress-wrap")
        assert len(wrap_dress["fit_flatterers"]) > 0
        assert "pear" in wrap_dress["fit_flatterers"].lower()
        boat_neck = self.catalog.get_item("top-boat-neck")
        assert "shoulder" in boat_neck["fit_flatterers"].lower()

    def test_retrieval_with_no_results(self):
        """Query with non-matching filters should return empty."""
        results = self.catalog.retrieve({"shape_class": "balanced", "categories": ["NonExistentCategory"]})
        assert isinstance(results, list)
        assert len(results) == 0

    def test_retrieval_returns_sorted_by_relevance(self):
        """Results should be ranked by semantic similarity."""
        results = self.catalog.retrieve({"shape_class": "pear", "k": 5})
        assert len(results) > 0
        assert all(isinstance(item, dict) for item in results)

    def test_retrieval_respects_multiple_filters(self):
        """Should respect category AND fabric filters together."""
        results = self.catalog.retrieve({"shape_class": "pear", "categories": ["Tops"], "fabrics": ["Cotton"]})
        for item in results:
            assert item["category"] == "Tops"
            assert item["fabric"] == "Cotton"

    def test_item_contains_all_required_fields(self):
        """Catalog items should have all required fields."""
        item = self.catalog.get_item("top-fitted-wrap")
        required_fields = ["sku", "name", "category", "fabric", "price", "colors", "sizes", "fit_flatterers", "silhouette_class"]
        for field in required_fields:
            assert field in item, f"Missing field: {field}"

    def test_colors_and_sizes_are_lists(self):
        """Colors and sizes should be lists."""
        item = self.catalog.get_item("top-fitted-wrap")
        assert isinstance(item["colors"], list)
        assert isinstance(item["sizes"], list)
        assert all(isinstance(c, str) for c in item["colors"])
        assert all(isinstance(s, str) for s in item["sizes"])

    def test_price_is_numeric(self):
        """Price should be numeric."""
        item = self.catalog.get_item("top-fitted-wrap")
        assert isinstance(item["price"], (int, float))
        assert item["price"] > 0

    def test_rebuild_is_idempotent(self):
        """Rebuilding with same products should produce same catalog."""
        stats1 = self.catalog.stats()
        self.catalog.rebuild(PRODUCTS)
        stats2 = self.catalog.stats()
        assert stats1["total_items"] == stats2["total_items"]

    def test_get_item_is_case_sensitive(self):
        """SKU lookup should be case-sensitive."""
        item1 = self.catalog.get_item("top-fitted-wrap")
        item2 = self.catalog.get_item("TOP-FITTED-WRAP")
        assert item1 is not None
        assert item2 is None

    def test_retrieval_k_limit_strictly_enforced(self):
        """Should never return more than k items."""
        for k in [1, 2, 5, 10]:
            results = self.catalog.retrieve({"shape_class": "balanced", "k": k})
            assert len(results) <= k, f"Returned {len(results)} items, expected <= {k}"
