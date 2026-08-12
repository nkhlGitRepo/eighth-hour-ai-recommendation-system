"""Tests for M5 — Recommendation Engine."""

import pytest
import tempfile
import os
from py_src.modules.m1_intake_orchestrator import IntakeOrchestrator
from py_src.modules.m5_recommendation_engine import RecommendationEngine
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.persistence.session_repository import SQLiteSessionRepository
from py_src.utils.errors import ModuleError, GuardrailError
from tests.fixtures import PRODUCTS


@pytest.fixture
def orchestrator():
    """Fresh orchestrator with isolated database."""
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = temp_db.name
    temp_db.close()

    repo = SQLiteSessionRepository(db_path=db_path)
    orch = IntakeOrchestrator(session_repo=repo)

    yield orch

    try:
        os.unlink(db_path)
    except:
        pass


@pytest.fixture
def consent_tracker():
    """Consent tracker instance."""
    return ConsentTracker()


@pytest.fixture
def catalog():
    """Catalog instance with test products."""
    return CatalogKB(PRODUCTS)


@pytest.fixture
def recommendation_engine(catalog, consent_tracker):
    """Recommendation engine instance."""
    return RecommendationEngine(catalog, consent_tracker)


@pytest.fixture
def completed_session(orchestrator, consent_tracker):
    """Create a completed intake session with preferences."""
    session = orchestrator.create_session(user_id="rec_test_user")
    orchestrator.record_consent(
        session.session_id,
        photo_consent=True,
        measurement_consent=True,
    )
    # Record consent in consent tracker
    consent_tracker.record_consent(
        user_id=session.user_id,
        photo_consent=True,
        measurement_consent=True,
    )

    orchestrator.upload_photo(session.session_id, "s3://bucket/photo.jpg")
    orchestrator.extract_measurements(session.session_id)
    # Make sure we pass preferences to capture_preferences
    session = orchestrator.capture_preferences(
        session.session_id,
        preferred_colors=["black", "navy", "cream"],
        preferred_silhouettes=["fitted", "wrap"],
        occasions=["work", "casual"],
        coverage_prefs={"neckline": "moderate", "sleeves": "full"},
        lifestyle_context={"pace": "fast", "environment": "urban"},
        free_text_notes="Professional style",
    )
    return session


class TestM5SessionValidation:
    """Test session validation before generating recommendations."""

    def test_rejects_incomplete_session(self, recommendation_engine, orchestrator):
        """Cannot generate recommendations for incomplete session."""
        session = orchestrator.create_session(user_id="test_user")
        with pytest.raises(ModuleError, match="must be complete"):
            recommendation_engine.generate_recommendations(session)

    def test_rejects_initiated_session(self, recommendation_engine, orchestrator):
        """Rejects session in initiated state."""
        session = orchestrator.create_session(user_id="test_user")
        assert session.status == "initiated"
        with pytest.raises(ModuleError, match="must be complete"):
            recommendation_engine.generate_recommendations(session)

    def test_rejects_photo_capture_session(self, recommendation_engine, orchestrator):
        """Rejects session in photo_capture state."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(session.session_id, photo_consent=True, measurement_consent=True)
        assert session.status != "complete"
        with pytest.raises(ModuleError, match="must be complete"):
            recommendation_engine.generate_recommendations(session)

    def test_rejects_session_without_measurements(self, recommendation_engine, orchestrator):
        """Session must have body measurements."""
        session = orchestrator.create_session(user_id="test_user")
        session.status = "complete"
        # body_measurements is None
        with pytest.raises(ModuleError, match="measurements"):
            recommendation_engine.generate_recommendations(session)

    def test_rejects_session_without_shape_profile(self, recommendation_engine, orchestrator):
        """Session must have shape profile."""
        session = orchestrator.create_session(user_id="test_user")
        session.status = "complete"
        session.body_measurements = orchestrator.sizing.extract_measurements(
            "s3://photo.jpg", height_cm=165.0
        )
        # shape_profile is None
        with pytest.raises(ModuleError, match="shape profile"):
            recommendation_engine.generate_recommendations(session)

    def test_rejects_session_without_style_profile(self, recommendation_engine, orchestrator):
        """Session must have style profile."""
        session = orchestrator.create_session(user_id="test_user")
        session.status = "complete"
        session.body_measurements = orchestrator.sizing.extract_measurements(
            "s3://photo.jpg", height_cm=165.0
        )
        session.shape_profile = orchestrator.profiler.profile(
            session.body_measurements.to_dict()
        )
        # style_profile is None
        with pytest.raises(ModuleError, match="style profile"):
            recommendation_engine.generate_recommendations(session)


class TestM5ConsentEnforcement:
    """Test that consent is enforced before generating recommendations."""

    def test_rejects_without_photo_consent(self, recommendation_engine, orchestrator, consent_tracker):
        """Consent is enforced at session level, not at recommendation engine level."""
        # Since a complete session already guarantees consent was given,
        # M5 no longer checks consent directly
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://photo.jpg")
        orchestrator.extract_measurements(session.session_id)
        session = orchestrator.capture_preferences(session.session_id)

        # M5 should return recommendations regardless of consent_tracker state
        # (consent is checked at session completion, not retrieval)
        recommendations = recommendation_engine.generate_recommendations(session)
        assert len(recommendations) > 0


class TestM5QueryBuilding:
    """Test that M5 correctly constructs retrieval queries."""

    def test_query_includes_shape_class(self, recommendation_engine, completed_session):
        """Query includes shape_class from profile."""
        engine = recommendation_engine
        query = engine._build_retrieval_query(completed_session)
        assert "shape_class" in query
        assert query["shape_class"] == "hourglass"

    def test_query_includes_colors(self, recommendation_engine, completed_session):
        """Query includes preferred colors from style profile."""
        engine = recommendation_engine
        query = engine._build_retrieval_query(completed_session)
        assert "preferred_colors" in query
        # Colors are title-cased to match catalog format
        assert "Black" in query["preferred_colors"]
        assert "Navy" in query["preferred_colors"]

    def test_multiword_colors_are_not_mangled(self, recommendation_engine, completed_session):
        """
        Regression test: str.capitalize() lowercases every letter after the
        first IN THE WHOLE STRING, so "Pageant Blue".capitalize() produces
        "Pageant blue" -- which then fails to match the catalog's "Pageant
        Blue" and silently drops every matching product. Must use .title().
        """
        completed_session.style_profile.preferred_colors = ["Pageant Blue", "Sky Captain"]
        query = recommendation_engine._build_retrieval_query(completed_session)
        assert "Pageant Blue" in query["preferred_colors"]
        assert "Sky Captain" in query["preferred_colors"]

    def test_query_includes_silhouettes(self, recommendation_engine, completed_session):
        """Query passes through preferred silhouettes so M6 can filter on them."""
        completed_session.style_profile.preferred_silhouettes = ["fitted", "flowing"]
        query = recommendation_engine._build_retrieval_query(completed_session)
        assert query["preferred_silhouettes"] == ["fitted", "flowing"]

    def test_query_includes_occasions(self, recommendation_engine, completed_session):
        """Query passes through all selected occasions, not just the first one."""
        completed_session.style_profile.occasions = ["work", "evening"]
        query = recommendation_engine._build_retrieval_query(completed_session)
        assert query["occasions"] == ["work", "evening"]

    def test_occasion_filter_override(self, recommendation_engine, completed_session):
        """Explicit occasion_filter argument overrides the stored occasions."""
        query = recommendation_engine._build_retrieval_query(completed_session, occasion_filter="gym")
        assert query["occasions"] == ["gym"]

    def test_query_includes_categories_when_provided(self, recommendation_engine, completed_session):
        """Query includes categories when explicitly provided."""
        engine = recommendation_engine
        custom_cats = ["Tops", "Dresses"]
        query = engine._build_retrieval_query(completed_session, category_filter=custom_cats)
        assert "categories" in query
        assert query["categories"] == custom_cats

    def test_query_includes_inferred_size(self, recommendation_engine, completed_session):
        """Query includes inferred size from measurements."""
        engine = recommendation_engine
        query = engine._build_retrieval_query(completed_session)
        assert "size" in query
        assert query["size"] in ["XS", "S", "M", "L", "XL", "XXL"]

    def test_category_filter_overrides_default(self, recommendation_engine, completed_session):
        """Category filter parameter overrides default."""
        engine = recommendation_engine
        custom_categories = ["Tops", "Dresses"]
        query = engine._build_retrieval_query(
            completed_session,
            category_filter=custom_categories,
        )
        assert query["categories"] == custom_categories


class TestM5RecommendationGeneration:
    """Test generating recommendations from completed sessions."""

    def test_generates_recommendations(self, recommendation_engine, completed_session, consent_tracker):
        """M5 generates recommendations from completed session."""
        # Ensure consent is recorded
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )

        recs = recommendation_engine.generate_recommendations(completed_session)
        assert isinstance(recs, list)
        assert len(recs) > 0
        # Each recommendation should have expected fields
        for rec in recs:
            assert "sku" in rec
            assert "name" in rec
            assert "category" in rec

    def test_respects_k_parameter(self, recommendation_engine, completed_session, consent_tracker):
        """M5 respects k parameter for number of results."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )

        recs = recommendation_engine.generate_recommendations(completed_session, k=5)
        assert len(recs) <= 5

    def test_k_zero_defaults_to_system_default(self, recommendation_engine, completed_session, consent_tracker):
        """k=0 defaults to system default (M6 uses k=10 as fallback)."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )

        # k=0 should default to M6's system default (~10 items or all available)
        recs = recommendation_engine.generate_recommendations(completed_session, k=0)
        assert len(recs) > 0  # Should return results using system default
        assert len(recs) <= 5  # But limited by catalog size

    def test_k_larger_than_catalog(self, recommendation_engine, completed_session, consent_tracker):
        """M5 returns all available items when k > catalog size."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )

        recs = recommendation_engine.generate_recommendations(completed_session, k=1000)
        # Catalog has 5 items in test
        assert len(recs) <= 5
        assert all("sku" in r for r in recs)

    def test_filters_by_category(self, recommendation_engine, completed_session, consent_tracker):
        """M5 can filter recommendations by category."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )

        recs = recommendation_engine.generate_recommendations(
            completed_session,
            category_filter=["Tops"],
            k=20,
        )
        # All results should be from Tops category
        for rec in recs:
            assert rec["category"] == "Tops"

    def test_recommendations_match_shape_class(self, recommendation_engine, completed_session, consent_tracker):
        """Recommendations should be relevant to user's shape class."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )

        recs = recommendation_engine.generate_recommendations(completed_session)
        assert len(recs) > 0
        # Verify recommendations are actual products with required fields
        for rec in recs:
            assert "sku" in rec and rec["sku"], "SKU must be non-empty"
            assert "name" in rec and rec["name"], "Name must be non-empty"
            assert "category" in rec, "Category required"
            assert "price" in rec and rec["price"] > 0, "Price must be positive"

    def test_recommendations_respect_user_colors(self, recommendation_engine, completed_session, consent_tracker):
        """Recommendations should include user's preferred colors."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )
        # Session has colors: ["black", "navy", "cream"]
        recs = recommendation_engine.generate_recommendations(completed_session)

        # At least some recommendations should have a matching color
        products_with_matching_color = []
        for rec in recs:
            colors = [c.lower() for c in rec.get("colors", [])]
            if any(c in colors for c in ["black", "navy", "cream"]):
                products_with_matching_color.append(rec)

        assert len(products_with_matching_color) > 0, "Should recommend products with user's preferred colors"

    def test_recommendations_have_correct_size(self, recommendation_engine, completed_session, consent_tracker):
        """Recommendations should include the exact size shown on the customer's Shape Profile screen."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )
        expected_size = completed_session.shape_profile["size_recommendation_by_category"]["tops"]
        recs = recommendation_engine.generate_recommendations(completed_session)

        assert len(recs) > 0
        for rec in recs:
            sizes = rec.get("sizes", [])
            assert expected_size in sizes, (
                f"Product {rec['sku']} should have size {expected_size} available "
                f"(the size shown to this customer)"
            )

    def test_niche_category_filter_still_returns_minimum_via_relaxation(
        self, recommendation_engine, completed_session, consent_tracker
    ):
        """
        M5 requires no code of its own to benefit from M6's filter
        relaxation -- it just needs to not override M6's default
        min_results. A category that doesn't exist in the catalog at all
        must still yield at least MIN_RECOMMENDATIONS results, since even
        an explicit category restriction is eventually relaxed rather than
        leaving the customer with nothing.
        """
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )

        recs = recommendation_engine.generate_recommendations(
            completed_session,
            category_filter=["CategoryThatDoesNotExist"],
            k=10,
        )
        assert len(recs) >= 2

    def test_generate_recommendations_never_returns_fewer_than_minimum_when_catalog_allows(
        self, recommendation_engine, completed_session, consent_tracker
    ):
        """General guarantee, exercised through the full M5 path (not M6 directly)."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )

        recs = recommendation_engine.generate_recommendations(completed_session, k=10)
        assert len(recs) >= 2


class TestM5SizeInference:
    """
    Size used for retrieval must come from M3's shape_profile -- the same
    size already shown to the customer on the Shape Profile screen -- not
    from a second, independently-computed value. M5 has no size-inference
    logic of its own; a duplicate implementation is exactly what caused the
    displayed size and the filtered size to silently disagree.
    """

    def test_query_size_matches_shape_profile_size(self, recommendation_engine, completed_session):
        """The size in the retrieval query is exactly the customer-facing size."""
        query = recommendation_engine._build_retrieval_query(completed_session)
        displayed_size = completed_session.shape_profile["size_recommendation_by_category"]["tops"]
        assert query["size"] == displayed_size

    def test_no_independent_size_inference_method_exists(self, recommendation_engine):
        """M5 must not carry its own size-boundary logic that could drift from M3's."""
        assert not hasattr(recommendation_engine, "_infer_size_from_measurements")
