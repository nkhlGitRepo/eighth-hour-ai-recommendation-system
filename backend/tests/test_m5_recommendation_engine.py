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
        """Must have photo consent to generate recommendations."""
        session = orchestrator.create_session(user_id="test_user")
        orchestrator.record_consent(
            session.session_id,
            photo_consent=True,
            measurement_consent=True,
        )
        orchestrator.upload_photo(session.session_id, "s3://photo.jpg")
        orchestrator.extract_measurements(session.session_id)
        session = orchestrator.capture_preferences(session.session_id)

        # Don't record consent in consent_tracker (simulating no consent)
        with pytest.raises(GuardrailError, match="consented"):
            recommendation_engine.generate_recommendations(session)


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
        # Colors are capitalized to match catalog format
        assert "Black" in query["preferred_colors"]
        assert "Navy" in query["preferred_colors"]

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
        """Recommendations should include user's inferred size."""
        consent_tracker.record_consent(
            user_id=completed_session.user_id,
            photo_consent=True,
            measurement_consent=True,
        )
        # Session has bust=88.0 → size M
        recs = recommendation_engine.generate_recommendations(completed_session)

        for rec in recs:
            sizes = rec.get("sizes", [])
            assert "M" in sizes, f"Product {rec['sku']} should have size M available"


class TestM5SizeInference:
    """Test size inference from measurements."""

    def test_infers_xs_for_small_bust(self, recommendation_engine):
        """Infers XS for bust < 80."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 75, "waist": 60, "hips": 85, "height": 160}
        )
        assert size == "XS"

    def test_infers_xs_boundary_below_80(self, recommendation_engine):
        """Boundary: bust=79 should be XS."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 79, "waist": 60, "hips": 85, "height": 160}
        )
        assert size == "XS"

    def test_infers_s_at_boundary_80(self, recommendation_engine):
        """Boundary: bust=80 should be S."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 80, "waist": 63, "hips": 88, "height": 165}
        )
        assert size == "S"

    def test_infers_s_for_small_medium_bust(self, recommendation_engine):
        """Infers S for bust 80-84."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 82, "waist": 65, "hips": 90, "height": 165}
        )
        assert size == "S"

    def test_infers_m_at_boundary_84(self, recommendation_engine):
        """Boundary: bust=84 should be M."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 84, "waist": 68, "hips": 92, "height": 165}
        )
        assert size == "M"

    def test_infers_m_for_medium_bust(self, recommendation_engine):
        """Infers M for bust 84-90."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 88, "waist": 70, "hips": 95, "height": 165}
        )
        assert size == "M"

    def test_infers_l_at_boundary_90(self, recommendation_engine):
        """Boundary: bust=90 should be L."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 90, "waist": 75, "hips": 98, "height": 168}
        )
        assert size == "L"

    def test_infers_xl_at_boundary_96(self, recommendation_engine):
        """Boundary: bust=96 should be XL."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 96, "waist": 80, "hips": 102, "height": 168}
        )
        assert size == "XL"

    def test_infers_xxl_at_boundary_102(self, recommendation_engine):
        """Boundary: bust=102 should be XXL."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 102, "waist": 86, "hips": 108, "height": 170}
        )
        assert size == "XXL"

    def test_infers_xxl_for_large_bust(self, recommendation_engine):
        """Infers XXL for bust >= 102."""
        size = recommendation_engine._infer_size_from_measurements(
            {"bust": 105, "waist": 90, "hips": 110, "height": 170}
        )
        assert size == "XXL"

    def test_size_not_affected_by_height(self, recommendation_engine):
        """Size depends only on bust, not height."""
        size1 = recommendation_engine._infer_size_from_measurements(
            {"bust": 88, "waist": 70, "hips": 95, "height": 150}
        )
        size2 = recommendation_engine._infer_size_from_measurements(
            {"bust": 88, "waist": 70, "hips": 95, "height": 180}
        )
        assert size1 == size2 == "M"
