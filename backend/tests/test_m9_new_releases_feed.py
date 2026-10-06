"""Comprehensive tests for M9 — Personalized New Releases Feed."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
from py_src.modules.m9_new_releases_feed import NewReleasesFeed
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.modules.m7_fit_checker import FitChecker
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.audit_logger import AuditLogger
from py_src.constants import SHAPE_CATEGORY_AFFINITY, SIZE_BOUNDARIES, STANDARD_SIZES
from py_src.utils.sizing import infer_size_from_bust
from py_src.utils.errors import ModuleError


def days_ago(n):
    """ISO date string N days before now -- keeps "recent" test fixtures
    from going stale as real time passes, unlike a hardcoded date literal."""
    return (datetime.now() - timedelta(days=n)).date().isoformat()


# Raw product definitions (products.json shape) used to build a real
# CatalogKB, so tests exercise the actual normalization pipeline
# (flatters_shapes/silhouette_class/occasions inference) instead of a
# hand-faked shape that doesn't match what CatalogKB really produces.
RAW_PRODUCTS = [
    {
        "slug": "wrap-dress-navy",
        "name": "Wrap Dress",
        "category": "Dresses",
        "fabric": "Jersey",
        "price": 99.99,
        "colors": ["navy", "black", "cream"],
        "sizes": ["XS", "S", "M", "L", "XL"],
        "description": "A versatile wrap dress.",
        "silhouette": "flowing",
        "launched_at": days_ago(5),
    },
    {
        "slug": "fitted-vest-navy",
        "name": "Fitted Vest",
        "category": "Vests",
        "fabric": "Cotton",
        "price": 59.99,
        "colors": ["navy", "cream"],
        "sizes": ["XS", "S", "M", "L"],
        "description": "A fitted vest that emphasizes the waist.",
        "silhouette": "fitted",
        "launched_at": days_ago(10),
    },
    {
        "slug": "aline-skirt-black",
        "name": "A-Line Skirt",
        "category": "Skirts",
        "fabric": "Wool",
        "price": 79.99,
        "colors": ["black", "navy"],
        "sizes": ["XS", "S", "M", "L"],
        "description": "A classic a-line skirt.",
        "silhouette": "a_line",
        "launched_at": days_ago(15),
    },
    {
        "slug": "old-straight-top",
        "name": "Straight Top",
        "category": "Tops",
        "fabric": "Cotton",
        "price": 49.99,
        "colors": ["navy", "red"],
        "sizes": ["XS", "S", "M", "L", "XL"],
        "description": "A structured straight-cut top.",
        "silhouette": "straight",
        "launched_at": days_ago(400),  # well outside the recency window
    },
]


@pytest.fixture
def consent_tracker():
    """Consent tracker with measurement consent granted."""
    tracker = ConsentTracker()
    tracker.record_consent(user_id="test_user", photo_consent=True, measurement_consent=True)
    return tracker


@pytest.fixture
def catalog():
    """Real catalog built from realistic product data via CatalogKB's actual
    normalization pipeline (not a hand-faked .items shape)."""
    return CatalogKB(RAW_PRODUCTS)


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
        "preferred_silhouettes": ["fitted", "flowing"],
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
    """Test product scoring logic against real catalog-item shapes."""

    def test_scores_perfect_match(self, feed_manager, hourglass_profile, style_profile):
        """Strong match (shape + colors + silhouette) should score high."""
        product = {
            "sku": "dress-wrap",
            "colors": ["navy", "black", "cream"],  # All user colors available
            "silhouette_class": "flowing",          # In user's preferred_silhouettes
            "flatters_shapes": ["hourglass", "balanced"],  # Exact shape match
            "occasions": ["work", "casual"],
            "sizes": ["M"],
        }
        score = feed_manager.score_product_for_profile(product, hourglass_profile, style_profile)
        assert score > 0.9, f"Strong match should score > 0.9, got {score}"

    def test_scores_no_match(self, feed_manager, hourglass_profile):
        """No match (shape mismatch) should score low, below threshold."""
        product = {
            "sku": "jeans",
            "colors": ["indigo"],
            "flatters_shapes": ["straight", "balanced"],  # Doesn't include hourglass
            "sizes": ["M"],
        }
        score = feed_manager.score_product_for_profile(product, hourglass_profile, None)
        assert score < 0.6, f"No match should score < 0.6, got {score}"
        assert score < feed_manager.match_threshold

    def test_shape_match_exact(self, feed_manager, hourglass_profile):
        """Product that flatters user's shape should match."""
        product = {"flatters_shapes": ["hourglass", "balanced"]}
        score = feed_manager._score_shape_match(product, hourglass_profile)
        assert score == 1.0

    def test_shape_match_falls_back_to_category_affinity(self, feed_manager, hourglass_profile):
        """When flatters_shapes doesn't include the user's shape, fall back to category affinity."""
        product = {"flatters_shapes": ["straight"], "category": "Dresses"}
        score = feed_manager._score_shape_match(product, hourglass_profile)
        assert score == SHAPE_CATEGORY_AFFINITY["hourglass"]["Dresses"]

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
        """Product silhouette_class matching preference should score high."""
        product = {"silhouette_class": "fitted"}
        profile = {"preferred_silhouettes": ["fitted", "flowing"]}
        score = feed_manager._score_style_match(product, profile)
        assert score > 0.7

    def test_silhouette_mismatch_scores_zero_for_that_component(self, feed_manager):
        """Product silhouette_class not in preferences should score that component 0."""
        product = {"silhouette_class": "oversized"}
        profile = {"preferred_silhouettes": ["fitted", "flowing"]}
        score = feed_manager._score_style_match(product, profile)
        assert score == 0.0

    def test_availability_in_size(self, feed_manager, measurements):
        """Product stocked in the customer's size should score 1.0."""
        # Ask the shared inference what size this body is rather than asserting
        # a band from memory -- the previous comment ("bust=90 maps to S, 84-92")
        # described a chart revision ago and quietly stopped being true.
        size = infer_size_from_bust(measurements["bust"])
        product = {"sizes": [size]}
        assert feed_manager._score_availability(product, measurements) == 1.0

    def test_availability_out_of_size(self, feed_manager):
        """Product not stocked in the customer's size should score 0.0."""
        measurements = {"bust": 95}
        size = infer_size_from_bust(measurements["bust"])
        other = next(s for s in STANDARD_SIZES if s != size)
        assert feed_manager._score_availability({"sizes": [other]}, measurements) == 0.0

    def test_no_products_given(self, feed_manager):
        """If no products provided, score should reflect that."""
        product = {}
        score = feed_manager.score_product_for_profile(product)
        assert score == 0.5  # Neutral when no profiles


class TestM9GenerateFeed:
    """Test feed generation end-to-end against a real catalog."""

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

        for item in feed:
            assert "sku" in item and "match_score" in item and "matched_attributes" in item
            assert item["match_score"] >= feed_manager.match_threshold, \
                f"Item {item['sku']} scored {item['match_score']} below threshold {feed_manager.match_threshold}"
            assert 0 <= item["match_score"] <= 1, f"Invalid score {item['match_score']}"
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
        low_profile = {"shape_class": "athletic"}
        feed = feed_manager.generate_feed("test_user", low_profile, None, None)
        for item in feed:
            assert item["match_score"] >= feed_manager.MATCH_THRESHOLD

    def test_respects_limit(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Should respect limit parameter."""
        feed_1 = feed_manager.generate_feed(
            "test_user", hourglass_profile, style_profile, measurements, limit=1,
        )
        feed_50 = feed_manager.generate_feed(
            "test_user", hourglass_profile, style_profile, measurements, limit=50,
        )
        assert len(feed_1) <= 1
        assert len(feed_50) <= 50
        assert len(feed_1) <= len(feed_50)

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
            "test_user", hourglass_profile, style_profile, measurements,
        )
        for item in feed:
            assert "matched_attributes" in item
            assert isinstance(item["matched_attributes"], list)
            assert len(item["matched_attributes"]) > 0

    def test_includes_reason(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Feed items should include customer-facing reason."""
        feed = feed_manager.generate_feed(
            "test_user", hourglass_profile, style_profile, measurements,
        )
        for item in feed:
            assert "reason" in item
            assert isinstance(item["reason"], str)
            assert len(item["reason"]) > 0

    def test_includes_availability(self, feed_manager, hourglass_profile, measurements):
        """Feed items should include availability info."""
        feed = feed_manager.generate_feed("test_user", hourglass_profile, None, measurements)
        for item in feed:
            assert "availability" in item

    def test_accepts_full_measurements_to_dict_payload(self, feed_manager, hourglass_profile):
        """
        Regression test: main.py passes session.body_measurements.to_dict()
        directly, which includes non-numeric metadata (unit, provider,
        confidence_scores) and often a None shoulder/inseam. This used to
        make validate_measurements() reject every request unconditionally.
        """
        full_payload = {
            "bust": 90.0,
            "waist": 72.0,
            "hips": 97.0,
            "height": 165.0,
            "shoulder": None,
            "inseam": None,
            "unit": "cm",
            "confidence_scores": {"bust": 0.95},
            "provider": "manual_entry",
            "provider_version": "1.0",
            "extracted_at": 1234567890.0,
        }
        feed = feed_manager.generate_feed("test_user", hourglass_profile, None, full_payload)
        assert isinstance(feed, list)

    def test_empty_catalog_returns_empty_feed(self, fit_checker, consent_tracker):
        """Empty catalog should return empty feed."""
        empty_catalog = CatalogKB([])
        feed_mgr = NewReleasesFeed(
            catalog=empty_catalog,
            fit_checker=fit_checker,
            consent_tracker=consent_tracker,
        )
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "hourglass"}, None, None)
        assert feed == []


class TestM9RecencyFiltering:
    """A 'new release' must actually have launched within the recency window."""

    def test_old_product_excluded_even_with_perfect_match(self, feed_manager, style_profile):
        """
        old-straight-top launched 400 days ago and would otherwise be a
        great match -- it must not appear in the feed regardless of score.
        """
        profile = {"shape_class": "straight"}
        feed = feed_manager.generate_feed("test_user", profile, style_profile, None, limit=50)
        skus = {item["sku"] for item in feed}
        assert "old-straight-top" not in skus

    def test_recent_products_are_eligible(self, feed_manager, hourglass_profile):
        """Products launched within the window should be scoreable (not silently excluded)."""
        feed = feed_manager.generate_feed("test_user", hourglass_profile, None, None, limit=50)
        skus = {item["sku"] for item in feed}
        # At least one of the recently-launched products should be present.
        assert skus & {"wrap-dress-navy", "fitted-vest-navy", "aline-skirt-black"}

    def test_product_with_no_launched_at_is_excluded(self, fit_checker, consent_tracker):
        """A product with no launch date is treated as legacy, not new --
        checked with min_items=0 so the minimum-items guarantee (which
        would otherwise fall back to this same item as a last resort)
        doesn't mask the recency exclusion this test is actually about."""
        catalog = CatalogKB([{
            "slug": "no-date-item",
            "name": "No Date Item",
            "category": "Tops",
            "fabric": "Cotton",
            "price": 40.0,
            "colors": ["navy"],
            "sizes": ["M"],
            # No launched_at field at all.
        }])
        feed_mgr = NewReleasesFeed(catalog=catalog, fit_checker=fit_checker, consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "balanced"}, None, None, limit=50, min_items=0)
        assert feed == []

    def test_is_recent_handles_malformed_date_gracefully(self, feed_manager):
        """A garbage launched_at value should be treated as not-recent, not crash."""
        assert feed_manager._is_recent({"launched_at": "not-a-date"}) is False
        assert feed_manager._is_recent({"launched_at": None}) is False
        assert feed_manager._is_recent({}) is False

    def test_is_recent_true_within_window(self, feed_manager):
        assert feed_manager._is_recent({"launched_at": days_ago(1)}) is True
        assert feed_manager._is_recent({"launched_at": days_ago(29)}) is True

    def test_is_recent_false_outside_window(self, feed_manager):
        assert feed_manager._is_recent({"launched_at": days_ago(31)}) is False
        assert feed_manager._is_recent({"launched_at": days_ago(400)}) is False


class TestM9ShapeMatching:
    """Test shape-based matching."""

    def test_hourglass_prefers_wrap_dresses(self, feed_manager):
        """Hourglass shapes should match wrap-flatters items high."""
        wrap_dress = {
            "sku": "wrap",
            "flatters_shapes": ["hourglass", "pear", "balanced"],
            "colors": ["navy"],
            "silhouette_class": "flowing",
        }
        hourglass = {"shape_class": "hourglass"}
        score = feed_manager.score_product_for_profile(wrap_dress, hourglass, None)
        assert score > 0.7

    def test_pear_prefers_a_line_skirts(self, feed_manager):
        """Pear shapes should score a-line-flattering items high."""
        aline = {
            "sku": "aline",
            "flatters_shapes": ["pear", "athletic", "balanced"],
            "colors": ["black"],
            "silhouette_class": "a_line",
        }
        pear = {"shape_class": "pear"}
        score = feed_manager.score_product_for_profile(aline, pear, None)
        assert score > 0.7

    def test_wrong_shape_scores_lower(self, feed_manager):
        """Product not flattering user's shape should score lower via category fallback."""
        product = {"flatters_shapes": ["straight"], "category": "Vests"}
        hourglass = {"shape_class": "hourglass"}
        score = feed_manager._score_shape_match(product, hourglass)
        assert score < 1.0


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
            "silhouette_class": "fitted",
            "occasions": ["work"],
        }
        style = {
            "preferred_colors": ["navy", "black"],
            "preferred_silhouettes": ["fitted", "flowing"],
            "occasions": ["work", "casual"],
        }
        score = feed_manager._score_style_match(product, style)
        assert score >= 0.5


class TestM9ScoringFormula:
    """Test score component combination formula."""

    def test_score_averages_components(self, feed_manager, hourglass_profile, style_profile):
        """Verify that score combines shape, style, and availability components."""
        product_high_shape = {
            "sku": "test-high-shape",
            "colors": ["red", "orange"],           # No match with user colors
            "silhouette_class": "oversized",        # No match with user silhouettes
            "flatters_shapes": ["hourglass"],       # Shape match = 1.0
            "occasions": ["evening"],
            "sizes": ["M"],
        }

        product_high_style = {
            "sku": "test-high-style",
            "colors": ["navy", "black", "cream"],   # All user colors
            "silhouette_class": "fitted",            # User's preferred silhouette
            "flatters_shapes": ["straight"],         # No shape match for hourglass
            "occasions": ["work"],
            "sizes": ["M"],
            "category": "Tops",
        }

        measurements = {"bust": 90, "waist": 72, "hips": 97, "height": 165}

        score_high_shape = feed_manager.score_product_for_profile(
            product_high_shape, hourglass_profile, style_profile, measurements
        )
        score_high_style = feed_manager.score_product_for_profile(
            product_high_style, hourglass_profile, style_profile, measurements
        )

        assert 0.3 <= score_high_shape <= 1.0, f"High-shape score should be reasonable, got {score_high_shape}"
        assert 0.3 <= score_high_style <= 1.0, f"High-style score should be reasonable, got {score_high_style}"
        assert abs(score_high_shape - score_high_style) > 0.05, \
            f"Different component strengths should yield different scores: {score_high_shape} vs {score_high_style}"


class TestM9MatchAttributeIdentification:
    """Test identification of match reasons."""

    def test_identifies_shape_match(self, feed_manager, hourglass_profile):
        """Should identify shape matching as reason."""
        product = {"flatters_shapes": ["hourglass"]}
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
        product = {"silhouette_class": "fitted"}
        style = {"preferred_silhouettes": ["fitted"]}
        attrs = feed_manager._identify_match_attributes(product, None, style)
        assert any("silhouette" in attr.lower() for attr in attrs)

    def test_no_silhouette_match_does_not_falsely_claim_one(self, feed_manager):
        """A non-matching silhouette must not be reported as a match reason."""
        product = {"silhouette_class": "oversized"}
        style = {"preferred_silhouettes": ["fitted"]}
        attrs = feed_manager._identify_match_attributes(product, None, style)
        assert not any("silhouette" in attr.lower() for attr in attrs)

    def test_identifies_occasion_match(self, feed_manager):
        """Should identify occasion overlap as a match reason."""
        product = {"occasions": ["work", "evening"]}
        style = {"occasions": ["work"]}
        attrs = feed_manager._identify_match_attributes(product, None, style)
        assert any("occasion" in attr.lower() for attr in attrs)


class TestM9MatchReasonGeneration:
    """
    Regression coverage for the reported bug: every product showed the
    identical "We think you'll like this because flatters X shapes and
    it's selected for X shapes" sentence, because the old
    _generate_match_reason only ever used matched_attributes[0] and then
    unconditionally appended a second, redundant restatement of the same
    shape fact. The rewrite combines every signal that actually matched
    into one sentence (never repeating a fact) and folds in the product's
    own category, so two products only produce the same reason when they
    genuinely matched on the exact same signals.
    """

    def test_shape_match_is_not_stated_twice(self, feed_manager, hourglass_profile):
        """The old bug verbatim: a shape match must appear exactly once,
        not "flatters X shapes ... selected for X shapes"."""
        product = {"category": "Tops", "flatters_shapes": ["hourglass"], "colors": [], "occasions": []}
        reason = feed_manager._generate_match_reason(product, hourglass_profile, None)
        assert reason.lower().count("hourglass") == 1

    def test_products_with_different_matches_get_different_reasons(self, feed_manager, hourglass_profile):
        """Two products matching on different signals must not produce
        the same explanation."""
        shape_only = {"category": "Tops", "flatters_shapes": ["hourglass"], "colors": [], "occasions": []}
        color_only = {"category": "Tops", "flatters_shapes": [], "colors": ["Sky Captain"], "occasions": []}
        style = {"preferred_colors": ["Sky Captain"], "preferred_silhouettes": [], "occasions": []}

        reason_shape = feed_manager._generate_match_reason(shape_only, hourglass_profile, style)
        reason_color = feed_manager._generate_match_reason(color_only, hourglass_profile, style)
        assert reason_shape != reason_color
        assert "sky captain" in reason_color.lower()

    def test_reason_mentions_product_category(self, feed_manager, hourglass_profile):
        """The category should flow naturally into the sentence (e.g.
        'this top', not the raw catalog string 'this Tops')."""
        product = {"category": "Skirts", "flatters_shapes": ["hourglass"], "colors": [], "occasions": []}
        reason = feed_manager._generate_match_reason(product, hourglass_profile, None)
        assert "this skirt" in reason.lower()
        assert "tops" not in reason.lower()

    def test_multiple_matches_are_combined_not_truncated_to_one(self, feed_manager, hourglass_profile):
        """A product matching on shape AND color should mention both,
        not just whichever was checked first."""
        product = {
            "category": "Dresses", "flatters_shapes": ["hourglass"],
            "colors": ["Sky Captain"], "silhouette_class": "fitted", "occasions": [],
        }
        style = {"preferred_colors": ["Sky Captain"], "preferred_silhouettes": ["fitted"], "occasions": []}
        reason = feed_manager._generate_match_reason(product, hourglass_profile, style)
        assert "hourglass" in reason.lower()
        assert "sky captain" in reason.lower()
        assert "fitted" in reason.lower()

    def test_fallback_reason_when_nothing_specific_matched_still_mentions_shape_and_category(
        self, feed_manager, hourglass_profile
    ):
        """When an item cleared the threshold without any single specific
        signal matching (e.g. via the category-level shape affinity
        fallback), the reason should still be true and product-specific,
        not a generic string identical for every category."""
        product = {"category": "Trousers", "flatters_shapes": [], "colors": [], "occasions": []}
        reason = feed_manager._generate_match_reason(product, hourglass_profile, None)
        assert "trousers" in reason.lower()
        assert "hourglass" in reason.lower()

    def test_no_profiles_at_all_still_returns_a_sensible_string(self, feed_manager):
        product = {"category": "Vests", "flatters_shapes": [], "colors": [], "occasions": []}
        reason = feed_manager._generate_match_reason(product, None, None)
        assert "vest" in reason.lower()
        assert reason.endswith(".")


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
    """
    Test size inference from measurements.

    Boundaries match constants.SIZE_BOUNDARIES, which is shared with M3
    (the size shown to the customer) and M5 (the size used to filter their
    recommendations) so all three modules can never disagree on a customer's
    size.
    """

    def test_infers_xs_for_small_bust(self, feed_manager):
        """A bust below the smallest size's upper edge should be XS."""
        measurements = {"bust": SIZE_BOUNDARIES["XS"][1] - 1}
        size = feed_manager._infer_size_from_measurements(measurements)
        assert size == "XS"

    @pytest.mark.parametrize("size", ["S", "M", "L"])
    def test_infers_each_mid_size_across_its_whole_band(self, feed_manager, size):
        """
        Every bust value inside a size's band must infer that size -- checked
        across the band rather than at a few transcribed points, so a chart
        revision can't leave this asserting the wrong range.
        """
        low, high = SIZE_BOUNDARIES[size]
        span = high - low
        for bust in (low, low + span / 4, low + span / 2, high - 0.01):
            measurements = {"bust": bust}
            inferred = feed_manager._infer_size_from_measurements(measurements)
            assert inferred == size, f"bust={bust} should be {size}, got {inferred}"

    def test_infers_xxl_for_large_bust(self, feed_manager):
        """A bust at or above the largest size's lower edge should be XXL."""
        measurements = {"bust": SIZE_BOUNDARIES["XXL"][0] + 3}
        size = feed_manager._infer_size_from_measurements(measurements)
        assert size == "XXL"

    def test_size_boundary_transitions_exact(self, feed_manager):
        """Verify exact boundary transitions (off-by-one bug detection)."""
        # Derived from the shared table rather than transcribed, so this keeps
        # catching off-by-one errors after a chart revision instead of just
        # failing because the numbers moved.
        test_cases = [
            (edge, size)
            for size, (low, high) in SIZE_BOUNDARIES.items()
            for edge in (low, high - 0.1)
        ]

        for bust, expected_size in test_cases:
            measurements = {"bust": bust}
            actual_size = feed_manager._infer_size_from_measurements(measurements)
            assert actual_size == expected_size, \
                f"bust={bust}: expected {expected_size}, got {actual_size}"


class TestM9ErrorHandling:
    """Test graceful handling of invalid/corrupt data."""

    def test_handles_malformed_product_gracefully(self, fit_checker, consent_tracker, hourglass_profile):
        """
        A malformed product (missing required fields) should be dropped
        during catalog normalization -- same as production behavior -- not
        crash feed generation.
        """
        corrupted_catalog = CatalogKB([
            {"slug": "bad-product"},  # Missing name/category/fabric/price
            *RAW_PRODUCTS,
        ])
        corrupted_feed_mgr = NewReleasesFeed(
            catalog=corrupted_catalog,
            fit_checker=fit_checker,
            consent_tracker=consent_tracker,
        )
        measurements = {"bust": 90, "waist": 72, "hips": 97, "height": 165}

        feed = corrupted_feed_mgr.generate_feed(
            "test_user", hourglass_profile, None, measurements,
        )
        assert isinstance(feed, list)
        assert "bad-product" not in {item["sku"] for item in feed}

    def test_handles_invalid_measurements(self, feed_manager, hourglass_profile):
        """Invalid measurements should raise error early, not during generation."""
        bad_measurements = {"bust": -100, "waist": 72, "hips": 97, "height": 165}

        with pytest.raises(ModuleError, match="must be positive"):
            feed_manager.generate_feed(
                "test_user", hourglass_profile, None, bad_measurements,
            )


class TestM9ResponseStructure:
    """Test feed response structure."""

    def test_feed_item_has_required_fields(self, feed_manager, hourglass_profile, style_profile, measurements):
        """Each feed item should have required fields."""
        feed = feed_manager.generate_feed(
            "test_user", hourglass_profile, style_profile, measurements,
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


class TestM9AvailabilityMatchesShapeProfile:
    """
    Regression coverage: availability.recommended_size in the New Releases
    feed must always match the size shown on the customer's Shape Profile
    for that product's category -- otherwise a customer sees "Recommended
    size: M" on the New Releases card, then "L" (correctly) on the product
    page when they click through.

    Root cause: unlike main.py's /fit-check endpoint, generate_feed() never
    passed known_size to FitChecker.check_fit(), so it fell back to the
    argmax of fit_scores. That argmax agrees with M3's Shape Profile in the
    common case (boundary-aware scoring guarantees the correct size scores
    highest), but right at a size boundary two sizes can tie on score, and
    the argmax's tie-break (first size in STANDARD_SIZES order) can
    disagree with M3's own boundary convention.
    """

    def test_availability_recommended_size_matches_shape_profile_at_a_boundary_tie(self, fit_checker, consent_tracker):
        from py_src.constants import STANDARD_SIZES, SIZE_BOUNDARIES

        catalog = CatalogKB([{
            "slug": "boundary-top",
            "name": "Boundary Top", "category": "Tops", "fabric": "Cotton",
            "price": 60.0, "colors": ["Ebony"], "sizes": STANDARD_SIZES,
            "launched_at": days_ago(5),
        }])
        feed_mgr = NewReleasesFeed(catalog=catalog, fit_checker=fit_checker, consent_tracker=consent_tracker)

        # bust right at the L boundary edge -- M and L tie on the blended
        # argmax, but M3's own boundary convention says L.
        lo, _hi = SIZE_BOUNDARIES["L"]
        measurements = {"bust": lo + 0.01, "waist": 87.0, "hips": 104.0, "height": 165.0}
        shape_profile = {
            "shape_class": "balanced",
            "size_recommendation_by_category": {"tops": "L", "skirts": "L"},
        }

        feed = feed_mgr.generate_feed("test_user", shape_profile, None, measurements)

        assert len(feed) == 1
        assert feed[0]["availability"]["recommended_size"] == "L"


class TestM9IndependentOfM6FilterRelaxation:
    """
    M6's retrieve() (used by the main recommendation engine) guarantees a
    minimum result count via progressive filter relaxation. M9 must be
    completely unaffected by that -- it scores products by threshold, not
    hard AND-filters, and reads self.catalog.items directly rather than
    going through retrieve() at all. Proven directly (not just "M9's tests
    still pass", which wouldn't rule out coincidental agreement) by
    spying on CatalogKB.retrieve and asserting it's never called.
    """

    def test_generate_feed_never_calls_catalog_retrieve(self, feed_manager, hourglass_profile, style_profile, measurements):
        with patch.object(CatalogKB, "retrieve") as mock_retrieve:
            feed_manager.generate_feed("test_user", hourglass_profile, style_profile, measurements)
            mock_retrieve.assert_not_called()

    def test_new_releases_can_legitimately_return_zero(self, fit_checker, consent_tracker):
        """
        Without the minimum-items guarantee (min_items=0), an empty feed
        (nothing new happens to match this customer right now) is a valid,
        honest result, not a bug -- unlike M6/M5's recommendations, which
        always guarantee a minimum. With the default guarantee active,
        this same scenario instead falls back to the catalog's best-scoring
        item regardless of age (see the relaxation tests below) -- min_items=0
        is what verifies the strict, unrelaxed scoring/recency logic in
        isolation from that fallback.
        """
        nothing_new_matches = CatalogKB([
            # Launched this week, but in a colour the customer didn't pick.
            {"slug": "recent-no-match", "name": "Recent No Match", "category": "Tops",
             "fabric": "Cotton", "price": 40.0, "colors": ["Chartreuse"], "sizes": ["M"],
             "launched_at": days_ago(5)},
            # A perfect match, but from long before the latest drop.
            {"slug": "old-item", "name": "Old Item", "category": "Tops", "fabric": "Cotton",
             "price": 40.0, "colors": ["Ebony"], "sizes": ["M"],
             "launched_at": days_ago(400)},
        ])
        feed_mgr = NewReleasesFeed(
            catalog=nothing_new_matches,
            fit_checker=fit_checker,
            consent_tracker=consent_tracker,
        )
        feed = feed_mgr.generate_feed("test_user", None, {"preferred_colors": ["Ebony"], "preferred_silhouettes": [], "occasions": []}, None, min_items=0)
        assert feed == []


class TestM9MinimumItemsGuarantee:
    """
    New Releases guarantees at least min_items (default 1) via a two-tier
    relaxation, mirroring M6's filter relaxation for the main
    recommendations engine but adapted to what's actually relaxable here:
    the match_threshold (a personalization quality bar) relaxes before the
    recency window (the actual definition of "new"), since dropping
    recency is a much bigger compromise to the feature's core promise.
    """

    def test_backfills_below_threshold_items_within_recency_window_first(self, fit_checker, consent_tracker):
        """Two recent items, both below the match threshold -- the
        best-scoring one should still surface rather than returning
        empty, and it should stay within the recency window (no need to
        reach for the whole-catalog fallback when the window itself has
        enough candidates)."""
        catalog = CatalogKB([
            {
                "slug": "recent-partial-match",
                "name": "Recent Partial Match", "category": "Tops", "fabric": "Cotton",
                "price": 40.0, "colors": ["Ebony"], "sizes": ["M"],  # matches 1 of 2 preferred colors
                "launched_at": days_ago(5),
            },
            {
                "slug": "recent-no-match",
                "name": "Recent No Match", "category": "Tops", "fabric": "Cotton",
                "price": 40.0, "colors": ["Chartreuse"], "sizes": ["M"],  # matches neither
                "launched_at": days_ago(6),
            },
        ])
        feed_mgr = NewReleasesFeed(catalog=catalog, fit_checker=fit_checker, consent_tracker=consent_tracker)
        # A style profile with 2 preferred colors, only one of which either
        # item stocks -- both score well below the 0.65 threshold on style
        # (0.5 and 0.0 respectively), and there's no shape profile to pull
        # the average up, but they're NOT tied, so the backfill pick is
        # genuinely the better match, not an artifact of list order.
        feed = feed_mgr.generate_feed(
            "test_user", None,
            {"preferred_colors": ["Ebony", "Sky Captain"], "preferred_silhouettes": [], "occasions": []},
            None,
        )
        assert len(feed) == 1
        assert feed[0]["sku"] == "recent-partial-match"
        assert feed[0]["match_score"] < 0.65

    def test_falls_back_to_whole_catalog_only_when_recency_window_is_insufficient(self, fit_checker, consent_tracker):
        """Nothing launched recently at all -- the only way to satisfy
        min_items is to reach past the recency window."""
        catalog = CatalogKB([{
            "slug": "old-item",
            "name": "Old Item", "category": "Tops", "fabric": "Cotton",
            "price": 40.0, "colors": ["Ebony"], "sizes": ["M"],
            "launched_at": days_ago(400),
        }])
        feed_mgr = NewReleasesFeed(catalog=catalog, fit_checker=fit_checker, consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "balanced"}, None, None)
        assert len(feed) == 1
        assert feed[0]["sku"] == "old-item"

    def test_already_sufficient_recent_matches_are_never_relaxed(self, feed_manager, hourglass_profile, style_profile, measurements):
        """When the strict, unrelaxed feed already has >= min_items,
        relaxation must not fire (result should be identical to the
        min_items=0 result)."""
        strict = feed_manager.generate_feed("test_user", hourglass_profile, style_profile, measurements, min_items=0)
        guaranteed = feed_manager.generate_feed("test_user", hourglass_profile, style_profile, measurements)
        assert len(strict) >= 1
        assert strict == guaranteed

    def test_min_items_zero_disables_the_guarantee(self, fit_checker, consent_tracker):
        """Explicit opt-out: min_items=0 preserves the old exact-scoring
        behavior, including a legitimately empty result."""
        catalog = CatalogKB([
            # Launched this week, but in a colour the customer didn't pick.
            {"slug": "recent-no-match", "name": "Recent No Match", "category": "Tops",
             "fabric": "Cotton", "price": 40.0, "colors": ["Chartreuse"], "sizes": ["M"],
             "launched_at": days_ago(5)},
            # A perfect match, but from long before the latest drop.
            {"slug": "old-item", "name": "Old Item", "category": "Tops", "fabric": "Cotton",
             "price": 40.0, "colors": ["Ebony"], "sizes": ["M"],
             "launched_at": days_ago(400)},
        ])
        feed_mgr = NewReleasesFeed(catalog=catalog, fit_checker=fit_checker, consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", None, {"preferred_colors": ["Ebony"], "preferred_silhouettes": [], "occasions": []}, None, min_items=0)
        assert feed == []

    def test_empty_catalog_returns_empty_without_erroring(self, fit_checker, consent_tracker):
        """The one case that can still legitimately return fewer than
        min_items even with the guarantee active: there's nothing in the
        catalog at all, so there's nothing to fall back to."""
        feed_mgr = NewReleasesFeed(catalog=CatalogKB([]), fit_checker=fit_checker, consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "balanced"}, None, None)
        assert feed == []

    def test_relaxation_is_never_disclosed_on_the_item_itself(self, fit_checker, consent_tracker):
        """A relaxed item's response shape must be indistinguishable from
        a normal one -- no special flag, no altered fields."""
        catalog = CatalogKB([{
            "slug": "old-item",
            "name": "Old Item", "category": "Tops", "fabric": "Cotton",
            "price": 40.0, "colors": ["Ebony"], "sizes": ["M"],
            "launched_at": days_ago(400),
        }])
        feed_mgr = NewReleasesFeed(catalog=catalog, fit_checker=fit_checker, consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "balanced"}, None, None)
        assert set(feed[0].keys()) == {
            "sku", "name", "category", "match_score", "matched_attributes", "reason", "availability"
        }

    def test_respects_limit_smaller_than_min_items(self, fit_checker, consent_tracker):
        """limit acts as a hard cap even when it's below min_items --
        target = min(min_items, limit), so relaxation never overshoots
        what was actually requested."""
        catalog = CatalogKB([{
            "slug": "old-item",
            "name": "Old Item", "category": "Tops", "fabric": "Cotton",
            "price": 40.0, "colors": ["Ebony"], "sizes": ["M"],
            "launched_at": days_ago(400),
        }])
        feed_mgr = NewReleasesFeed(catalog=catalog, fit_checker=fit_checker, consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "balanced"}, None, None, limit=1, min_items=1)
        assert len(feed) <= 1


class TestM9BetweenDrops:
    """
    "New" used to be measured only against today, so the feed decayed by
    itself: a month after the last launch nothing counted as new, and it fell
    back to a single item from the whole catalog -- what the live site was
    showing. When nothing has launched within the window, the latest drop is
    still the newest thing in the shop.
    """

    def _stale_catalog(self):
        def item(slug, days):
            return {"slug": slug, "name": slug, "category": "Tops", "fabric": "Cotton",
                    "price": 40.0, "colors": ["Ebony"], "sizes": ["M"], "launched_at": days_ago(days)}
        return CatalogKB([item("latest-drop-a", 60), item("latest-drop-b", 75),
                          item("previous-drop", 120), item("legacy", 400)])

    def test_the_latest_drop_is_still_shown_as_new(self, fit_checker, consent_tracker):
        feed_mgr = NewReleasesFeed(catalog=self._stale_catalog(), fit_checker=fit_checker,
                                   consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "balanced"}, None, None, min_items=0)
        assert sorted(item["sku"] for item in feed) == ["latest-drop-a", "latest-drop-b"]

    def test_a_fresh_catalog_is_measured_from_today_as_before(self, fit_checker, consent_tracker):
        catalog = CatalogKB([
            {"slug": "this-week", "name": "This Week", "category": "Tops", "fabric": "Cotton",
             "price": 40.0, "colors": ["Ebony"], "sizes": ["M"], "launched_at": days_ago(3)},
            {"slug": "two-months", "name": "Two Months", "category": "Tops", "fabric": "Cotton",
             "price": 40.0, "colors": ["Ebony"], "sizes": ["M"], "launched_at": days_ago(60)},
        ])
        feed_mgr = NewReleasesFeed(catalog=catalog, fit_checker=fit_checker, consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "balanced"}, None, None, min_items=0)
        assert [item["sku"] for item in feed] == ["this-week"]

    def test_the_real_catalog_has_new_releases_whatever_the_date(self, fit_checker, consent_tracker):
        import json
        from pathlib import Path
        products = json.loads((Path(__file__).resolve().parent.parent / "products.json").read_text())
        feed_mgr = NewReleasesFeed(catalog=CatalogKB(products), fit_checker=fit_checker,
                                   consent_tracker=consent_tracker)
        feed = feed_mgr.generate_feed("test_user", {"shape_class": "balanced"}, None, None, min_items=0)
        assert len(feed) >= 3
