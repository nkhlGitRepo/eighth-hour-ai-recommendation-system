"""Comprehensive tests for M9 — Personalized New Releases Feed."""

import pytest
from unittest.mock import MagicMock, patch
from py_src.modules.m9_new_releases_feed import NewReleasesFeed
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.modules.m7_fit_checker import FitChecker
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.utils.errors import ModuleError


@pytest.fixture
def consent_tracker():
    """Consent tracker with measurement consent granted."""
    tracker = ConsentTracker()
    tracker.record_consent(user_id="test_user", photo_consent=True, measurement_consent=True)
    return tracker


@pytest.fixture
def catalog():
    """Catalog with test products."""
    catalog = CatalogKB([])
    catalog.items = [
        {
            "sku": "top-navy-fitted",
            "name": "Navy Fitted Top",
            "category": "Tops",
            "colors": ["navy", "cream"],
            "sizes": ["XS", "S", "M", "L", "XL"],
            "silhouettes": ["fitted", "classic"],
            "occasions": ["work", "casual"],
            "fit_flatterers": ["hourglass", "pear"],
            "price": 59.99,
        },
        {
            "sku": "skirt-flare",
            "name": "Flare Skirt",
            "category": "Skirts",
            "colors": ["black", "navy"],
            "sizes": ["XS", "S", "M", "L"],
            "silhouettes": ["flare"],
            "occasions": ["work", "evening"],
            "fit_flatterers": ["pear", "apple"],
            "price": 79.99,
        },
        {
            "sku": "dress-wrap",
            "name": "Wrap Dress",
            "category": "Dresses",
            "colors": ["red", "navy", "black"],
            "sizes": ["XS", "S", "M", "L", "XL", "XXL"],
            "silhouettes": ["wrap", "fitted"],
            "occasions": ["work", "casual", "evening"],
            "fit_flatterers": ["hourglass", "pear", "apple"],
            "price": 99.99,
        },
    ]
    return catalog


@pytest.fixture
def fit_checker(consent_tracker):
    """Fit checker instance."""
    return FitChecker(consent_tracker=consent_tracker)


@pytest.fixture
def feed_manager(catalog, fit_checker, consent_tracker):
    """New releases feed manager."""
    return NewReleasesFeed(
        catalog=catalog,
        fit_checker=fit_checker,
        consent_tracker=consent_tracker,
    )


@pytest.fixture
def hourglass_profile():
    """Hourglass body shape profile."""
    return {
        "shape_class": "hourglass",
        "ratios": {"bust_waist": 1.2, "waist_hip": 1.0},
    }


@pytest.fixture
def pear_profile():
    """Pear body shape profile."""
    return {
        "shape_class": "pear",
        "ratios": {"bust_waist": 0.95, "waist_hip": 1.1},
    }


@pytest.fixture
def style_profile():
    """Style preference profile."""
    return {
        "preferred_colors": ["navy", "black", "cream"],
        "preferred_silhouettes": ["fitted", "wrap"],
        "occasions": ["work", "casual"],
    }


@pytest.fixture
def measurements():
    """Test measurements."""
    return {
        "bust": 90.0,
        "waist": 72.0,
        "hips": 97.0,
        "height": 165.0,
    }


class TestM9ScoreProductForProfile:
    """Test product scoring logic."""

    def test_scores_perfect_match(self, feed_manager, hourglass_profile, style_profile):
        """Strong match (shape + colors + silhouettes) should score high."""
        product = {
            "sku": "dress-wrap",
            "colors": ["navy", "black", "cream"],             # All user colors available
            "silhouettes": ["wrap", "fitted"],                # Exact match
            "fit_flatterers": ["hourglass"],                  # Exact match
            "sizes": ["M"],
        }
        score = feed_manager.score_product_for_profile(product, hourglass_profile, style_profile)
        # With all components matching, score should be very high (close to 1.0)
        assert score > 0.9, f"Strong match should score > 0.9, got {score}"

    def test_scores_no_match(self, feed_manager, hourglass_profile):
        """No match (shape mismatch) should score low, below threshold."""
        product = {
            "sku": "jeans",
            "colors": ["indigo"],
            "fit_flatterers": ["rectangle"],  # Doesn't flatter hourglass
            "sizes": ["M"],
        }
        score = feed_manager.score_product_for_profile(product, hourglass_profile, None)
        # No style profile and mismatched shape should score low
        assert score < 0.6, f"No match should score < 0.6, got {score}"
        # And definitely below the feed threshold
        assert score < feed_manager.match_threshold, \
            f"No-match score {score} should be below threshold {feed_manager.match_threshold}"

    def test_shape_match_exact(self, feed_manager, hourglass_profile):
        """Product that flatters user's shape should match."""
        product = {"fit_flatterers": ["hourglass"]}
        score = feed_manager._score_shape_match(product, hourglass_profile)
        assert score == 1.0

    def test_shape_match_no_data(self, feed_manager):
        """Product without shape data should get neutral score."""
        product = {}
        profile = {"shape_class": "hourglass"}
        score = feed_manager._score_shape_match(product, profile)
        assert 0.4 <= score <= 0.6

    def test_color_match_exact(self, feed_manager):
        """All user colors in product should match well."""
        product = {"colors": ["navy", "black", "cream"]}
        profile = {"preferred_colors": ["navy", "black", "cream"]}
        score = feed_manager._score_style_match(product, profile)
        assert score > 0.8

    def test_color_match_partial(self, feed_manager):
        """Some colors matching should score medium."""
        product = {"colors": ["navy", "red"]}
        profile = {"preferred_colors": ["navy", "black", "cream"]}
        score = feed_manager._score_style_match(product, profile)
        assert 0.2 < score < 0.8

    def test_silhouette_match(self, feed_manager):
        """Product silhouettes matching preference should score high."""
        product = {"silhouettes": ["fitted", "wrap"]}
        profile = {"preferred_silhouettes": ["fitted", "wrap"]}
        score = feed_manager._score_style_match(product, profile)
        assert score > 0.7

    def test_availability_in_size(self, feed_manager, measurements):
        """Product with user's size should score 1.0."""
        product = {"sizes": ["M", "L"]}
        score = feed_manager._score_availability(product, measurements)
        assert score == 1.0

    def test_availability_out_of_size(self, feed_manager):
        """Product without user's size should score 0.0."""
        product = {"sizes": ["XS"]}
        measurements = {"bust": 95}  # Would be L
        score = feed_manager._score_availability(product, measurements)
        assert score == 0.0

    def test_no_products_given(self, feed_manager):
        """If no products provided, score should reflect that."""
        product = {}
        score = feed_manager.score_product_for_profile(product)
        assert score == 0.5  # Neutral when no profiles


class TestM9GenerateFeed:
    """Test feed generation."""

    def test_generates_feed(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Should generate feed with matched products meeting quality standards."""
        feed = feed_manager.generate_feed(
            "test_user",
            hourglass_profile,
            style_profile,
            measurements,
            limit=10,
        )
        assert len(feed) > 0, "Feed should contain products"

        # Verify all items meet quality standards
        for item in feed:
            # All items must have required fields
            assert "sku" in item and "match_score" in item and "matched_attributes" in item
            # All items must be above threshold (default 0.65)
            assert item["match_score"] >= feed_manager.match_threshold, \
                f"Item {item['sku']} scored {item['match_score']} below threshold {feed_manager.match_threshold}"
            # Match score must be valid
            assert 0 <= item["match_score"] <= 1, f"Invalid score {item['match_score']}"
            # Must have explanation
            assert len(item["matched_attributes"]) > 0, f"Item {item['sku']} missing matched_attributes"

    def test_feed_sorted_by_score(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Feed should be sorted by match score (highest first)."""
        feed = feed_manager.generate_feed(
            "test_user",
            hourglass_profile,
            style_profile,
            measurements,
        )
        if len(feed) > 1:
            for i in range(len(feed) - 1):
                assert feed[i]["match_score"] >= feed[i + 1]["match_score"]

    def test_respects_threshold(self, feed_manager):
        """Only products above threshold should be included."""
        low_profile = {
            "shape_class": "rectangle",
        }
        # Rectangle shape probably won't match most products
        feed = feed_manager.generate_feed(
            "test_user",
            low_profile,
            None,
            None,
        )
        # All items in feed should be above threshold
        for item in feed:
            assert item["match_score"] >= feed_manager.MATCH_THRESHOLD

    def test_respects_limit(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Should respect limit parameter."""
        feed_5 = feed_manager.generate_feed(
            "test_user",
            hourglass_profile,
            style_profile,
            measurements,
            limit=5,
        )
        feed_50 = feed_manager.generate_feed(
            "test_user",
            hourglass_profile,
            style_profile,
            measurements,
            limit=50,
        )
        assert len(feed_5) <= 5
        assert len(feed_50) <= 50
        assert len(feed_5) <= len(feed_50)

    def test_rejects_invalid_limit(self, feed_manager, hourglass_profile):
        """Invalid limit should raise error."""
        with pytest.raises(ModuleError, match="1-100"):
            feed_manager.generate_feed("test_user", hourglass_profile, None, None, limit=0)

        with pytest.raises(ModuleError, match="1-100"):
            feed_manager.generate_feed("test_user", hourglass_profile, None, None, limit=101)

    def test_requires_at_least_one_profile(self, feed_manager):
        """At least shape or style profile required."""
        with pytest.raises(ModuleError, match="profile"):
            feed_manager.generate_feed("test_user", None, None, None)

    def test_includes_match_attributes(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Feed items should include explanation of match."""
        feed = feed_manager.generate_feed(
            "test_user",
            hourglass_profile,
            style_profile,
            measurements,
        )
        for item in feed:
            assert "matched_attributes" in item
            assert isinstance(item["matched_attributes"], list)
            assert len(item["matched_attributes"]) > 0

    def test_includes_reason(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Feed items should include customer-facing reason."""
        feed = feed_manager.generate_feed(
            "test_user",
            hourglass_profile,
            style_profile,
            measurements,
        )
        for item in feed:
            assert "reason" in item
            assert isinstance(item["reason"], str)
            assert len(item["reason"]) > 0

    def test_includes_availability(self, feed_manager, hourglass_profile, measurements):
        """Feed items should include availability info."""
        feed = feed_manager.generate_feed(
            "test_user",
            hourglass_profile,
            None,
            measurements,
        )
        for item in feed:
            assert "availability" in item

    def test_empty_catalog_returns_empty_feed(self, fit_checker, consent_tracker):
        """Empty catalog should return empty feed."""
        empty_catalog = CatalogKB([])
        empty_catalog.items = []
        feed_mgr = NewReleasesFeed(
            catalog=empty_catalog,
            fit_checker=fit_checker,
            consent_tracker=consent_tracker,
        )
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "hourglass"}, None, None)
        assert feed == []


class TestM9ShapeMatching:
    """Test shape-based matching."""

    def test_hourglass_prefers_wrap_dresses(self, feed_manager):
        """Hourglass shapes should match wrap dresses high."""
        wrap_dress = {
            "sku": "wrap",
            "fit_flatterers": ["hourglass"],
            "colors": ["navy"],
            "silhouettes": ["wrap"],
        }
        hourglass = {"shape_class": "hourglass"}
        score = feed_manager.score_product_for_profile(wrap_dress, hourglass, None)
        assert score > 0.7

    def test_pear_prefers_flare_skirts(self, feed_manager):
        """Pear shapes should score flare skirts high."""
        flare = {
            "sku": "flare",
            "fit_flatterers": ["pear"],
            "colors": ["black"],
            "silhouettes": ["flare"],
        }
        pear = {"shape_class": "pear"}
        score = feed_manager.score_product_for_profile(flare, pear, None)
        assert score > 0.7

    def test_wrong_shape_scores_lower(self, feed_manager):
        """Product flattering different shape should score lower for user."""
        product = {"fit_flatterers": ["rectangle"]}  # Not hourglass
        hourglass = {"shape_class": "hourglass"}
        score = feed_manager._score_shape_match(product, hourglass)
        assert score < 0.7


class TestM9StyleMatching:
    """Test style-based matching."""

    def test_navy_lover_matches_navy_product(self, feed_manager):
        """User who loves navy should match navy products."""
        product = {"colors": ["navy", "white"]}
        style = {"preferred_colors": ["navy", "black"]}
        score = feed_manager._score_style_match(product, style)
        assert score >= 0.5

    def test_color_mismatch_scores_low(self, feed_manager):
        """Product with no matching colors should score low."""
        product = {"colors": ["red", "orange"]}
        style = {"preferred_colors": ["navy", "black", "cream"]}
        score = feed_manager._score_style_match(product, style)
        assert score == 0.0

    def test_multiple_style_factors_combine(self, feed_manager):
        """Multiple matching style factors should improve score."""
        product = {
            "colors": ["navy"],
            "silhouettes": ["fitted"],
            "occasions": ["work"],
        }
        style = {
            "preferred_colors": ["navy", "black"],
            "preferred_silhouettes": ["fitted", "wrap"],
            "occasions": ["work", "casual"],
        }
        score = feed_manager._score_style_match(product, style)
        assert score >= 0.5


class TestM9ScoringFormula:
    """Test score component combination formula."""

    def test_score_averages_components(self, feed_manager, hourglass_profile, style_profile):
        """Verify that score combines shape, style, and availability components."""
        # Product that matches on shape but not style
        product_high_shape = {
            "sku": "test-high-shape",
            "colors": ["red", "orange"],          # No match with user colors
            "silhouettes": ["A-line"],            # No match with user silhouettes
            "fit_flatterers": ["hourglass"],      # Shape match = 1.0
            "sizes": ["M"],
        }

        # Product that matches on style but not shape
        product_high_style = {
            "sku": "test-high-style",
            "colors": ["navy", "black", "cream"], # All user colors
            "silhouettes": ["wrap", "fitted"],    # User silhouettes
            "fit_flatterers": ["rectangle"],      # No shape match
            "sizes": ["M"],
        }

        measurements = {"bust": 90, "waist": 72, "hips": 97, "height": 165}

        score_high_shape = feed_manager.score_product_for_profile(
            product_high_shape, hourglass_profile, style_profile, measurements
        )
        score_high_style = feed_manager.score_product_for_profile(
            product_high_style, hourglass_profile, style_profile, measurements
        )

        # Both should score reasonably well (not 0 or 1)
        assert 0.3 <= score_high_shape <= 1.0, f"High-shape score should be reasonable, got {score_high_shape}"
        assert 0.3 <= score_high_style <= 1.0, f"High-style score should be reasonable, got {score_high_style}"
        # High-shape should score differently than high-style (different component strengths)
        assert abs(score_high_shape - score_high_style) > 0.1, \
            f"Different component strengths should yield different scores: {score_high_shape} vs {score_high_style}"


class TestM9MatchAttributeIdentification:
    """Test identification of match reasons."""

    def test_identifies_shape_match(self, feed_manager, hourglass_profile):
        """Should identify shape matching as reason."""
        product = {"fit_flatterers": ["hourglass"]}
        attrs = feed_manager._identify_match_attributes(product, hourglass_profile, None)
        assert any("shape" in attr.lower() or "hourglass" in attr.lower() for attr in attrs)

    def test_identifies_color_match(self, feed_manager):
        """Should identify color match as reason."""
        product = {"colors": ["navy"]}
        style = {"preferred_colors": ["navy", "black"]}
        attrs = feed_manager._identify_match_attributes(product, None, style)
        assert any("color" in attr.lower() for attr in attrs)

    def test_identifies_silhouette_match(self, feed_manager):
        """Should identify silhouette match as reason."""
        product = {"silhouettes": ["fitted"]}
        style = {"preferred_silhouettes": ["fitted"]}
        attrs = feed_manager._identify_match_attributes(product, None, style)
        assert any("silhouette" in attr.lower() for attr in attrs)


class TestM9AuditLogging:
    """Test audit trail logging."""

    def test_logs_feed_generation(self, feed_manager, hourglass_profile):
        """Should log when feed is generated."""
        with patch.object(AuditLogger, "log_event") as mock_log:
            feed_manager.generate_feed("test_user", hourglass_profile, None, None)

            mock_log.assert_called()
            call_args = mock_log.call_args[0]
            assert call_args[0] == "NEW_RELEASES_FEED_GENERATED"
            assert call_args[1] == "test_user"


class TestM9SizeInference:
    """Test size inference from measurements."""

    def test_infers_xs_for_small_bust(self, feed_manager):
        """Bust < 80 should be XS."""
        measurements = {"bust": 75}
        size = feed_manager._infer_size_from_measurements(measurements)
        assert size == "XS"

    def test_infers_s_for_80_84(self, feed_manager):
        """Bust 80-83 should be S."""
        for bust in [80, 81, 82]:
            measurements = {"bust": bust}
            size = feed_manager._infer_size_from_measurements(measurements)
            assert size == "S", f"bust={bust} should be S, got {size}"

    def test_infers_m_for_84_90(self, feed_manager):
        """Bust 84.0-89.99 should be M (boundary [84, 90))."""
        for bust in [84.0, 85, 87, 89.0, 89.99]:
            measurements = {"bust": bust}
            size = feed_manager._infer_size_from_measurements(measurements)
            assert size == "M", f"bust={bust} should be M, got {size}"

    def test_infers_l_for_90_96(self, feed_manager):
        """Bust 90-95 should be L."""
        for bust in [90, 92, 94]:
            measurements = {"bust": bust}
            size = feed_manager._infer_size_from_measurements(measurements)
            assert size == "L", f"bust={bust} should be L, got {size}"

    def test_infers_xxl_for_large_bust(self, feed_manager):
        """Bust >= 102 should be XXL."""
        measurements = {"bust": 110}
        size = feed_manager._infer_size_from_measurements(measurements)
        assert size == "XXL"

    def test_size_boundary_transitions_exact(self, feed_manager):
        """Verify exact boundary transitions (off-by-one bug detection)."""
        # Test exact boundary values and just below/above
        test_cases = [
            (79.9, "XS"),   # Just below 80
            (80.0, "S"),    # Exact boundary
            (83.9, "S"),    # Just below 84
            (84.0, "M"),    # Exact boundary
            (89.9, "M"),    # Just below 90
            (90.0, "L"),    # Exact boundary
            (95.9, "L"),    # Just below 96
            (96.0, "XL"),   # Exact boundary
            (101.9, "XL"),  # Just below 102
            (102.0, "XXL"), # Exact boundary
        ]

        for bust, expected_size in test_cases:
            measurements = {"bust": bust}
            actual_size = feed_manager._infer_size_from_measurements(measurements)
            assert actual_size == expected_size, \
                f"bust={bust}: expected {expected_size}, got {actual_size}"


class TestM9ErrorHandling:
    """Test graceful handling of invalid/corrupt data."""

    def test_handles_product_missing_sizes_field(self, feed_manager, hourglass_profile):
        """Product missing 'sizes' field should be handled gracefully without crashing."""
        # Add a malformed product (missing 'sizes' key)
        corrupted_catalog = CatalogKB([])
        corrupted_catalog.items = [
            {"sku": "bad-product", "name": "Bad", "fit_flatterers": ["hourglass"]},
            # Missing 'sizes' field - will fail validation
        ]
        corrupted_feed_mgr = NewReleasesFeed(
            catalog=corrupted_catalog,
            fit_checker=feed_manager.fit_checker,
            consent_tracker=feed_manager.consent_tracker,
        )

        measurements = {"bust": 90, "waist": 72, "hips": 97, "height": 165}

        # Should not crash - error from bad product is caught and logged
        # The generation should complete even if all products fail fit checks
        feed = corrupted_feed_mgr.generate_feed(
            "test_user",
            hourglass_profile,
            None,
            measurements,
        )

        # Feed should be a list (may be empty if products don't match threshold)
        assert isinstance(feed, list), "Should return list, not crash"

    def test_handles_invalid_measurements(self, feed_manager, hourglass_profile):
        """Invalid measurements should raise error early, not during generation."""
        bad_measurements = {"bust": -100, "waist": 72, "hips": 97, "height": 165}

        with pytest.raises(ModuleError, match="must be positive"):
            feed_manager.generate_feed(
                "test_user",
                hourglass_profile,
                None,
                bad_measurements,
            )


class TestM9ResponseStructure:
    """Test feed response structure."""

    def test_feed_item_has_required_fields(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Each feed item should have required fields."""
        feed = feed_manager.generate_feed(
            "test_user",
            hourglass_profile,
            style_profile,
            measurements,
        )
        required_fields = {"sku", "name", "match_score", "matched_attributes", "reason"}
        for item in feed:
            assert required_fields.issubset(set(item.keys()))

    def test_match_score_is_numeric(self, feed_manager, hourglass_profile):
        """Match score should be numeric 0-1."""
        feed = feed_manager.generate_feed("test_user", hourglass_profile, None, None)
        for item in feed:
            assert isinstance(item["match_score"], float)
            assert 0 <= item["match_score"] <= 1

    def test_name_is_string(self, feed_manager, hourglass_profile):
        """Product name should be string."""
        feed = feed_manager.generate_feed("test_user", hourglass_profile, None, None)
        for item in feed:
            assert isinstance(item["name"], str)
            assert len(item["name"]) > 0
