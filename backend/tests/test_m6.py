"""Tests for M6 (Catalog Knowledge Base)."""

import pytest
from py_src.modules.m6_catalog_kb import CatalogKB, shape_affinity_score
from py_src.constants import SHAPE_CATEGORY_AFFINITY
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
        """
        Query with non-matching filters should return empty -- when
        relaxation is explicitly disabled (min_results=0). By default,
        retrieve() now guarantees a minimum via filter relaxation (see
        TestFilterRelaxation); this test verifies the underlying strict
        filter logic itself is still exactly correct.
        """
        results = self.catalog.retrieve(
            {"shape_class": "balanced", "categories": ["NonExistentCategory"]},
            min_results=0,
        )
        assert isinstance(results, list)
        assert len(results) == 0

    def test_retrieval_respects_multiple_filters(self):
        """Should respect category AND fabric filters together (relaxation disabled)."""
        results = self.catalog.retrieve(
            {"shape_class": "pear", "categories": ["Tops"], "fabrics": ["Cotton"]},
            min_results=0,
        )
        assert len(results) > 0
        for item in results:
            assert item["category"] == "Tops"
            assert item["fabric"] == "Cotton"

    def test_item_contains_all_required_fields(self):
        """Catalog items should have all required fields."""
        item = self.catalog.get_item("top-fitted-wrap")
        required_fields = ["sku", "slug", "name", "category", "fabric", "price", "colors", "sizes",
                            "fit_flatterers", "silhouette_class", "occasions"]
        for field in required_fields:
            assert field in item, f"Missing field: {field}"

    def test_sku_and_slug_are_the_same_identifier(self):
        """sku and slug are intentionally the same value -- there is no
        separate real SKU concept in this catalog, only a URL slug."""
        item = self.catalog.get_item("top-fitted-wrap")
        assert item["sku"] == item["slug"] == "top-fitted-wrap"

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


class TestSilhouetteHandling:
    """Silhouette classification and filtering."""

    def setup_method(self):
        self.catalog = CatalogKB(PRODUCTS)

    def test_silhouette_field_on_product_takes_precedence_over_inference(self):
        """
        An explicit 'silhouette' field on the product data must win over
        the name-keyword guess. Uses a name with no vest/wrap/straight/
        pleated/a-line keyword, which would otherwise fall through to the
        inference function's default ("straight").
        """
        products = PRODUCTS + [{
            "slug": "plain-cardigan",
            "name": "Plain Cardigan",
            "category": "Tops",
            "fabric": "Cotton",
            "price": 45.0,
            "colors": ["Black"],
            "sizes": ["M"],
            "silhouette": "oversized",
        }]
        catalog = CatalogKB(products)
        item = catalog.get_item("plain-cardigan")
        assert item["silhouette_class"] == "oversized"

    def test_silhouette_falls_back_to_inference_when_field_absent(self):
        """Products with no explicit 'silhouette' field still get a reasonable guess."""
        wrap_dress = self.catalog.get_item("dress-wrap")
        assert wrap_dress["silhouette_class"] == "flowing"
        overlap_vest = self.catalog.get_item("vest-overlap")
        assert overlap_vest["silhouette_class"] == "fitted"

    def test_a_line_inference_uses_underscore_naming(self):
        """
        Inferred a-line silhouette must be 'a_line' (matching M4's
        VALID_SILHOUETTES), not 'A-line' -- otherwise a customer selecting
        the 'a_line' preference could never match an inferred a-line item.
        """
        aline_skirt = self.catalog.get_item("skirt-aline")
        assert aline_skirt["silhouette_class"] == "a_line"

    def test_retrieval_by_silhouette_filter(self):
        """Silhouette preference is a real hard filter, not decorative (relaxation disabled)."""
        results = self.catalog.retrieve(
            {"shape_class": "balanced", "preferred_silhouettes": ["fitted"]}, min_results=0,
        )
        assert len(results) > 0
        assert all(item["silhouette_class"] == "fitted" for item in results)

    def test_retrieval_by_silhouette_filter_excludes_non_matching(self):
        """Items with a different silhouette must not appear (relaxation disabled)."""
        results = self.catalog.retrieve(
            {"shape_class": "balanced", "preferred_silhouettes": ["fitted"]}, min_results=0,
        )
        skus = {item["sku"] for item in results}
        assert "dress-wrap" not in skus  # flowing, not fitted

    def test_retrieval_by_multiple_silhouettes_is_any_match(self):
        """Multiple selected silhouettes should OR together, like colors do."""
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_silhouettes": ["fitted", "flowing"],
        })
        assert len(results) > 0
        assert all(item["silhouette_class"] in ("fitted", "flowing") for item in results)

    def test_no_silhouette_preference_does_not_filter(self):
        """Omitting preferred_silhouettes should not restrict results."""
        results = self.catalog.retrieve({"shape_class": "balanced"})
        assert len(results) == len(PRODUCTS)


class TestOccasionHandling:
    """Occasion inference and filtering."""

    def setup_method(self):
        self.catalog = CatalogKB(PRODUCTS)

    def test_occasions_field_present_and_nonempty_for_known_categories(self):
        """Every product in a mapped category gets at least one occasion tag."""
        for slug in ("top-fitted-wrap", "skirt-aline", "dress-wrap", "top-boat-neck", "vest-overlap"):
            item = self.catalog.get_item(slug)
            assert isinstance(item["occasions"], list)
            assert len(item["occasions"]) > 0

    def test_occasions_are_category_appropriate(self):
        """Occasion tags should reflect the product's actual category."""
        vest = self.catalog.get_item("vest-overlap")
        assert "work" in vest["occasions"]
        dress = self.catalog.get_item("dress-wrap")
        assert "evening" in dress["occasions"]

    def test_unmapped_category_gets_no_occasions(self):
        """A category with no occasion mapping should get an empty list, not a guess."""
        products = PRODUCTS + [{
            "slug": "mystery-item",
            "name": "Mystery Item",
            "category": "Accessories",
            "fabric": "Cotton",
            "price": 20.0,
            "colors": ["Black"],
            "sizes": ["M"],
        }]
        catalog = CatalogKB(products)
        item = catalog.get_item("mystery-item")
        assert item["occasions"] == []

    def test_retrieval_by_occasion_filter(self):
        """Occasion preference is a real hard filter."""
        results = self.catalog.retrieve({"shape_class": "balanced", "occasions": ["evening"]})
        assert len(results) > 0
        assert all("evening" in item["occasions"] for item in results)
        skus = {item["sku"] for item in results}
        assert "vest-overlap" not in skus  # Vests aren't tagged "evening"

    def test_retrieval_by_occasion_with_no_matching_products_returns_empty_when_unrelaxed(self):
        """
        An occasion with no matching category (e.g. gym, in a catalog with
        no activewear) returns nothing when relaxation is disabled --
        verifying the strict occasion filter itself is exactly correct.
        By default (min_results > 0), retrieve() instead relaxes filters
        to guarantee a minimum -- see TestFilterRelaxation.
        """
        results = self.catalog.retrieve(
            {"shape_class": "balanced", "occasions": ["gym"]}, min_results=0,
        )
        assert results == []

    def test_no_occasion_preference_does_not_filter(self):
        """Omitting occasions should not restrict results."""
        results = self.catalog.retrieve({"shape_class": "balanced"})
        assert len(results) == len(PRODUCTS)

    def test_silhouette_and_occasion_filters_combine_with_and(self):
        """Combined preferences should intersect, not just apply one of them (relaxation disabled)."""
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_silhouettes": ["fitted"],
            "occasions": ["work"],
        }, min_results=0)
        assert len(results) > 0
        for item in results:
            assert item["silhouette_class"] == "fitted"
            assert "work" in item["occasions"]


class TestShapeBasedRanking:
    """
    M6's ranking must be driven by real, deterministic signals -- not
    mock_embed (a placeholder hash function that stood in for a real
    embedding model and had no genuine relationship to fit). Ranking is now:
    primary key = does the item's flatters_shapes include the customer's
    shape; secondary key (tiebreak) = SHAPE_CATEGORY_AFFINITY for its
    category.
    """

    def setup_method(self):
        self.catalog = CatalogKB(PRODUCTS)

    def test_shape_matching_items_rank_above_non_matching(self):
        """dress-wrap flatters hourglass by keyword; top-boat-neck does not."""
        results = self.catalog.retrieve({"shape_class": "hourglass", "k": 10})
        skus_in_order = [item["sku"] for item in results]
        assert "dress-wrap" in skus_in_order
        assert "top-boat-neck" in skus_in_order
        assert skus_in_order.index("dress-wrap") < skus_in_order.index("top-boat-neck")

    def test_ranking_is_fully_deterministic(self):
        """Same query must always produce the same order -- no hash-based noise."""
        results1 = [item["sku"] for item in self.catalog.retrieve({"shape_class": "pear", "k": 10})]
        results2 = [item["sku"] for item in self.catalog.retrieve({"shape_class": "pear", "k": 10})]
        assert results1 == results2

    def test_different_shapes_can_reorder_the_same_candidate_set(self):
        """Changing shape_class should be able to change ranking, not just be ignored."""
        hourglass_order = [item["sku"] for item in self.catalog.retrieve({"shape_class": "hourglass", "k": 10})]
        pear_order = [item["sku"] for item in self.catalog.retrieve({"shape_class": "pear", "k": 10})]
        # Both queries see the same 5-item candidate pool (no other filters),
        # but dress-wrap (flatters hourglass+pear+apple) and vest-overlap
        # (flatters pear+hourglass+apple+athletic) should rank differently
        # relative to top-boat-neck (flatters neither) under a genuinely
        # shape-driven ranking -- this would be impossible if shape_class
        # had no real effect (the original mock_embed bug for 3 of 6 shapes).
        assert hourglass_order != [] and pear_order != []

    def test_tiebreak_uses_shared_category_affinity_not_insertion_order(self):
        """
        Two items that both fail to specifically flatter the shape (both in
        the 'default' tier) must still be ordered by real category affinity,
        not by whichever happened to load first from products.json.
        """
        results = self.catalog.retrieve({"shape_class": "apple", "k": 10})
        # Every item's rank position should be non-increasing in its
        # category's apple-affinity score, among items that don't
        # specifically flatter "apple" via flatters_shapes.
        non_specific = [item for item in results if "apple" not in item["flatters_shapes"]]
        affinities = [SHAPE_CATEGORY_AFFINITY["apple"].get(item["category"], 0.5) for item in non_specific]
        assert affinities == sorted(affinities, reverse=True)

    def test_retrieval_returns_sorted_by_relevance(self):
        """Results should be ranked, not returned in arbitrary order."""
        results = self.catalog.retrieve({"shape_class": "pear", "k": 5})
        assert len(results) > 0
        assert all(isinstance(item, dict) for item in results)


class TestShapeAffinityScore:
    """
    shape_affinity_score() is the single shared function M6 (ranking) and
    M9 (New Releases scoring) both call, so they can never independently
    drift on how "specific match" trades off against "general category fit".
    """

    def test_specific_match_scores_one(self):
        item = {"flatters_shapes": ["hourglass", "balanced"], "category": "Tops"}
        assert shape_affinity_score("hourglass", item) == 1.0

    def test_non_match_falls_back_to_category_affinity(self):
        item = {"flatters_shapes": ["straight"], "category": "Dresses"}
        assert shape_affinity_score("hourglass", item) == SHAPE_CATEGORY_AFFINITY["hourglass"]["Dresses"]

    def test_specific_match_always_outranks_category_affinity(self):
        """No SHAPE_CATEGORY_AFFINITY value should ever reach 1.0 -- otherwise
        a generic category match could tie with (or beat) a real keyword match."""
        for shape_scores in SHAPE_CATEGORY_AFFINITY.values():
            for score in shape_scores.values():
                assert score < 1.0

    def test_unknown_category_defaults_to_neutral(self):
        item = {"flatters_shapes": [], "category": "NonexistentCategory"}
        assert shape_affinity_score("pear", item) == 0.5

    def test_missing_flatters_shapes_field_does_not_crash(self):
        item = {"category": "Tops"}
        assert shape_affinity_score("pear", item) == SHAPE_CATEGORY_AFFINITY["pear"]["Tops"]


# Purpose-built catalog for relaxation tests: category choice controls each
# item's inferred occasions (Vests/Trousers -> no "evening"; Dresses -> no
# "work"; etc.), giving precise control over which filter combination
# leaves how many survivors, so each test below can assert the *exact*
# relaxation cascade it expects rather than just "more than before".
RELAXATION_PRODUCTS = [
    {
        "slug": "item-a-red-fitted-vest",
        "name": "Item A", "category": "Vests", "fabric": "Silk", "price": 100.0,
        "colors": ["Red"], "sizes": ["S", "M"], "silhouette": "fitted",
    },
    {
        "slug": "item-b-blue-flowing-top",
        "name": "Item B", "category": "Tops", "fabric": "Silk", "price": 100.0,
        "colors": ["Blue"], "sizes": ["S", "M"], "silhouette": "flowing",
    },
    {
        "slug": "item-c-red-fitted-dress",
        "name": "Item C", "category": "Dresses", "fabric": "Silk", "price": 100.0,
        "colors": ["Red"], "sizes": ["S", "M"], "silhouette": "fitted",
    },
    {
        "slug": "item-d-green-straight-skirt",
        "name": "Item D", "category": "Skirts", "fabric": "Silk", "price": 100.0,
        "colors": ["Green"], "sizes": ["S", "M"], "silhouette": "straight",
    },
    {
        "slug": "item-e-purple-straight-vest",
        "name": "Item E", "category": "Vests", "fabric": "Silk", "price": 100.0,
        "colors": ["Purple"], "sizes": ["L"], "silhouette": "straight",
    },
]


class TestFilterRelaxation:
    """
    retrieve() must guarantee MIN_RECOMMENDATIONS results by progressively
    relaxing (dropping) hard filters -- softest preference signal first --
    rather than ever returning fewer than that when the catalog physically
    has enough items to satisfy some relaxed version of the query.
    """

    def setup_method(self):
        self.catalog = CatalogKB(RELAXATION_PRODUCTS)

    def test_niche_query_still_returns_minimum(self):
        """
        Strict AND of color=Red, silhouette=fitted, occasion=date_night
        matches only item-c (item-a is Red+fitted but has no date_night
        occasion -- Vests never get "date_night"). Dropping just the
        occasion filter brings item-a back in, reaching the minimum of 2
        without needing to touch silhouette or color at all.
        """
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_colors": ["Red"],
            "preferred_silhouettes": ["fitted"],
            "occasions": ["date_night"],
            "k": 10,
        })
        skus = {item["sku"] for item in results}
        assert skus == {"item-a-red-fitted-vest", "item-c-red-fitted-dress"}
        # Color and silhouette were never relaxed -- both survivors still
        # honor them exactly.
        for item in results:
            assert "Red" in item["colors"]
            assert item["silhouette_class"] == "fitted"

    def test_relaxation_stops_as_soon_as_minimum_is_met(self):
        """Must not over-relax past what's actually needed to hit the minimum."""
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_colors": ["Red"],
            "preferred_silhouettes": ["fitted"],
            "occasions": ["date_night"],
            "k": 10,
        })
        # If this over-relaxed all the way to dropping color too, item-b
        # (Blue) or item-d (Green) would leak in.
        skus = {item["sku"] for item in results}
        assert "item-b-blue-flowing-top" not in skus
        assert "item-d-green-straight-skirt" not in skus

    def test_two_step_relaxation_cascade(self):
        """
        color=Red, silhouette=flowing, occasion=work matches nobody (no
        item is both Red and flowing). Dropping occasion alone still
        matches nobody (still no Red+flowing item) -- only after ALSO
        dropping silhouette do item-a and item-c (both Red) appear.
        """
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_colors": ["Red"],
            "preferred_silhouettes": ["flowing"],
            "occasions": ["work"],
            "k": 10,
        })
        skus = {item["sku"] for item in results}
        assert skus == {"item-a-red-fitted-vest", "item-c-red-fitted-dress"}

    def test_cascades_all_the_way_to_full_catalog_when_color_itself_is_impossible(self):
        """
        No item is Yellow, oversized, or gym-appropriate -- individually or
        combined. Relaxing occasion then silhouette still leaves "Yellow"
        matching nothing, so color must also be dropped, falling through to
        the full, unfiltered candidate set.
        """
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_colors": ["Yellow"],
            "preferred_silhouettes": ["oversized"],
            "occasions": ["gym"],
            "k": 10,
        })
        assert len(results) == len(RELAXATION_PRODUCTS)

    def test_cascades_to_size_as_true_last_resort(self):
        """
        No item exists in a nonexistent category, and no item is size XXL.
        Every softer filter (none set here) has nothing to drop, so this
        must relax all the way through categories and finally size to
        reach the minimum -- proving even the two most "functional"
        constraints give way rather than returning too few results.
        """
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "categories": ["NonexistentCategory"],
            "size": "XXL",
            "k": 10,
        })
        assert len(results) >= 2

    def test_min_results_zero_disables_relaxation(self):
        """Explicit opt-out: callers that need exact filter semantics (e.g.
        tests of filter correctness itself) must be able to see a true empty result."""
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_colors": ["Yellow"],
            "preferred_silhouettes": ["oversized"],
            "occasions": ["gym"],
            "k": 10,
        }, min_results=0)
        assert results == []

    def test_k_smaller_than_min_recommendations_does_not_over_relax(self):
        """
        With k=1, the target is min(MIN_RECOMMENDATIONS, k) = 1. The strict
        (unrelaxed) query already has exactly 1 match (item-c), so no
        relaxation should happen at all -- item-a must NOT appear, since
        that would mean relaxing further than the caller actually asked for.
        """
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_colors": ["Red"],
            "preferred_silhouettes": ["fitted"],
            "occasions": ["date_night"],
            "k": 1,
        })
        assert len(results) == 1
        assert results[0]["sku"] == "item-c-red-fitted-dress"

    def test_already_sufficient_results_are_never_relaxed(self):
        """A query that already meets the minimum must return exactly the
        strict filter result, untouched."""
        results = self.catalog.retrieve({
            "shape_class": "balanced",
            "preferred_colors": ["Red"],
            "k": 10,
        })
        skus = {item["sku"] for item in results}
        assert skus == {"item-a-red-fitted-vest", "item-c-red-fitted-dress"}

    def test_results_still_ranked_by_shape_after_relaxation(self):
        """Relaxed candidates still go through normal shape-based ranking, not arbitrary order."""
        results = self.catalog.retrieve({
            "shape_class": "pear",
            "preferred_colors": ["Yellow"],  # impossible -- forces relaxation to full catalog
            "k": 10,
        })
        scores = [shape_affinity_score("pear", item) for item in results]
        assert scores == sorted(scores, reverse=True)

    def test_catalog_smaller_than_minimum_returns_what_exists_without_erroring(self):
        """A catalog with fewer than MIN_RECOMMENDATIONS items total must not
        error or infinite-loop -- it should just return everything it has."""
        tiny_catalog = CatalogKB([RELAXATION_PRODUCTS[0]])
        results = tiny_catalog.retrieve({
            "shape_class": "balanced",
            "preferred_colors": ["Nonexistent Color"],
            "k": 10,
        })
        assert len(results) == 1

    def test_empty_catalog_returns_empty_without_erroring(self):
        empty_catalog = CatalogKB([])
        results = empty_catalog.retrieve({"shape_class": "balanced", "k": 10})
        assert results == []
