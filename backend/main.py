"""
FastAPI server for the AI Styling Engine.

Runs on localhost:8000 by default.
Website calls this API to get styling recommendations.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

from py_src.modules.m1_intake_orchestrator import IntakeOrchestrator, IntakeState
from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
from py_src.modules.m5_recommendation_engine import RecommendationEngine
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.modules.m7_fit_checker import FitChecker
from py_src.modules.m8_recommendation_history import RecommendationHistory
from py_src.modules.m9_new_releases_feed import NewReleasesFeed
from py_src.modules.m10_learning_loop import LearningLoop
from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.persistence.session_repository import SQLiteSessionRepository
from py_src.utils.errors import ModuleError, GuardrailError
from py_src.utils.logger import logger

# Initialize FastAPI app
app = FastAPI(title="AI Styling Engine", version="1.0.0")

# Enable CORS for website integration (adjust origins as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize modules
profiler = BodyShapeProfiler()
catalog = CatalogKB([])  # Will be populated from website
consent_tracker = ConsentTracker()
session_repo = SQLiteSessionRepository()
intake_orchestrator = IntakeOrchestrator()
recommendation_engine = RecommendationEngine(catalog, consent_tracker)
fit_checker = FitChecker(consent_tracker)
recommendation_history = RecommendationHistory(consent_tracker=consent_tracker)
new_releases_feed = NewReleasesFeed(
    catalog=catalog,
    fit_checker=fit_checker,
    consent_tracker=consent_tracker,
)
learning_loop = LearningLoop(session_repo=session_repo, consent_tracker=consent_tracker)


# =========================================================================
# REQUEST/RESPONSE MODELS
# =========================================================================


class Measurements(BaseModel):
    bust: float
    waist: float
    hips: float
    height: float
    shoulder: Optional[float] = None
    inseam: Optional[float] = None


class RetrievalQuery(BaseModel):
    shape_class: Optional[str] = None
    categories: Optional[List[str]] = None
    preferred_colors: Optional[List[str]] = None
    fabrics: Optional[List[str]] = None
    size: Optional[str] = None
    k: Optional[int] = 10


class ConsentRecord(BaseModel):
    user_id: str
    photo_consent: bool
    measurement_consent: bool


class CatalogProduct(BaseModel):
    slug: str
    name: str
    category: str
    fabric: str
    price: float
    colors: Optional[List[str]] = []
    sizes: Optional[List[str]] = []
    description: Optional[str] = ""
    length: Optional[str] = "Regular"


# =========================================================================
# PHASE 1: INTAKE ORCHESTRATION MODELS
# =========================================================================


class IntakeSessionResponse(BaseModel):
    user_id: str
    session_id: str
    status: str
    created_at: float
    updated_at: float


class IntakeConsentRequest(BaseModel):
    session_id: str
    photo_consent: bool
    measurement_consent: bool


class IntakePhotoRequest(BaseModel):
    session_id: str
    photo_ref: str
    height_cm: Optional[float] = None


class IntakeMeasurementConfirm(BaseModel):
    session_id: str
    manual_overrides: Optional[dict] = None


class IntakePreferencesRequest(BaseModel):
    session_id: str
    preferred_colors: Optional[List[str]] = None
    preferred_silhouettes: Optional[List[str]] = None
    occasions: Optional[List[str]] = None
    coverage_prefs: Optional[dict] = None
    lifestyle_context: Optional[dict] = None
    free_text_notes: Optional[str] = ""


class IntakeResumeRequest(BaseModel):
    user_id: str


# =========================================================================
# ENDPOINTS
# =========================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@app.post("/profile")
async def create_profile(measurements: Measurements):
    """
    Create a body shape profile from measurements.

    Request body:
    {
      "bust": 88,
      "waist": 70,
      "hips": 102,
      "height": 165,
      "shoulder": 38
    }

    Returns:
    {
      "shape_class": "pear",
      "ratios": {...},
      "size_recommendation_by_category": {...},
      "fit_notes": [...],
      "profile_version": "1.0.0"
    }
    """
    try:
        profile = profiler.profile(measurements.dict())
        return profile
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Profile creation failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/retrieve")
async def retrieve_recommendations(query: RetrievalQuery):
    """
    Retrieve product recommendations based on shape and preferences.

    Request body:
    {
      "shape_class": "pear",
      "categories": ["Tops", "Skirts"],
      "preferred_colors": ["Blue", "Black"],
      "fabrics": ["Cotton"],
      "size": "M",
      "k": 10
    }

    Returns:
    [
      {
        "sku": "top-123",
        "name": "Fitted Wrap Top",
        "category": "Tops",
        ...
      },
      ...
    ]
    """
    try:
        results = catalog.retrieve(query.dict(exclude_unset=True))
        return results
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Retrieval failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/catalog/sync")
async def sync_catalog(products: List[CatalogProduct]):
    """
    Sync catalog products from the website.

    This endpoint allows the website to push product updates to the backend.
    """
    try:
        product_dicts = [p.dict() for p in products]
        catalog.rebuild(product_dicts)
        return {
            "status": "synced",
            "item_count": len(catalog.items),
            "stats": catalog.stats(),
        }
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Catalog sync failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/catalog/stats")
async def get_catalog_stats():
    """Get catalog statistics."""
    return catalog.stats()


@app.post("/consent")
async def record_consent(consent: ConsentRecord):
    """
    Record user consent for data processing.

    Request body:
    {
      "user_id": "user-123",
      "photo_consent": true,
      "measurement_consent": true
    }

    Returns:
    {
      "user_id": "user-123",
      "has_any_consent": true,
      "photo_consent": true,
      "measurement_consent": true,
      "last_updated": 1691111111
    }
    """
    try:
        consent_tracker.record_consent(
            consent.user_id,
            consent.photo_consent,
            consent.measurement_consent,
        )
        return consent_tracker.get_consent_summary(consent.user_id)
    except Exception as err:
        logger.error("Consent recording failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/consent/{user_id}")
async def get_consent(user_id: str):
    """Get user's current consent status."""
    return consent_tracker.get_consent_summary(user_id)


# =========================================================================
# PHASE 1: INTAKE ORCHESTRATION ENDPOINTS
# =========================================================================


@app.post("/intake/session")
async def create_intake_session(user_id: str):
    """
    Create a new intake session for a user.

    Query param:
    - user_id: unique user identifier

    Returns:
    {
      "user_id": "user-123",
      "session_id": "uuid-...",
      "status": "initiated",
      "created_at": 1691111111.0,
      "updated_at": 1691111111.0
    }
    """
    try:
        session = intake_orchestrator.create_session(user_id=user_id)
        return {
            "user_id": session.user_id,
            "session_id": session.session_id,
            "status": session.status,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Intake session creation failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/intake/screen")
async def get_intake_screen(state: str):
    """
    Get UI schema for a specific intake state.

    Query param:
    - state: intake state (consent, photo_capture, measurement_extraction, manual_entry, preferences_capture)

    Returns:
    {
      "state": "consent",
      "title": "Accept Terms",
      "fields": [...]
    }
    """
    # Return schema for frontend to render appropriate screen
    screens = {
        "consent": {
            "state": "consent",
            "title": "Accept Terms",
            "fields": [
                {"name": "photo_consent", "type": "checkbox", "label": "I consent to photo capture"},
                {"name": "measurement_consent", "type": "checkbox", "label": "I consent to measurement extraction"},
            ],
        },
        "photo_capture": {
            "state": "photo_capture",
            "title": "Upload Photo",
            "fields": [
                {"name": "photo", "type": "file", "label": "Upload your photo"},
                {"name": "height_cm", "type": "number", "label": "Height (cm)", "optional": True},
            ],
        },
        "measurement_extraction": {
            "state": "measurement_extraction",
            "title": "Extracting Measurements",
            "fields": [{"name": "status", "type": "text", "label": "Processing your photo..."}],
        },
        "manual_entry": {
            "state": "manual_entry",
            "title": "Enter Measurements",
            "fields": [
                {"name": "bust", "type": "number", "label": "Bust (cm)"},
                {"name": "waist", "type": "number", "label": "Waist (cm)"},
                {"name": "hips", "type": "number", "label": "Hips (cm)"},
                {"name": "height", "type": "number", "label": "Height (cm)"},
            ],
        },
        "profile_generation": {
            "state": "profile_generation",
            "title": "Your Shape Profile",
            "fields": [{"name": "profile", "type": "text", "label": "Your body shape and sizing recommendations"}],
        },
        "preferences_capture": {
            "state": "preferences_capture",
            "title": "Style Preferences",
            "fields": [
                {"name": "colors", "type": "multiselect", "label": "Preferred colors"},
                {"name": "silhouettes", "type": "multiselect", "label": "Preferred silhouettes"},
                {"name": "occasions", "type": "multiselect", "label": "Occasions"},
            ],
        },
    }
    return screens.get(state, {"error": f"Unknown state: {state}"})


@app.post("/intake/consent")
async def record_intake_consent(request: IntakeConsentRequest):
    """
    Record user consent and transition to photo capture.

    Request body:
    {
      "session_id": "uuid-...",
      "photo_consent": true,
      "measurement_consent": true
    }
    """
    try:
        session = intake_orchestrator.record_consent(
            session_id=request.session_id,
            photo_consent=request.photo_consent,
            measurement_consent=request.measurement_consent,
        )
        return {
            "session_id": session.session_id,
            "status": session.status,
            "consent_recorded": True,
        }
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Intake consent recording failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/intake/photo")
async def upload_intake_photo(request: IntakePhotoRequest):
    """
    Upload photo for measurement extraction.

    Request body:
    {
      "session_id": "uuid-...",
      "photo_ref": "s3://bucket/photo.jpg",
      "height_cm": 165.0
    }
    """
    try:
        session = intake_orchestrator.upload_photo(
            session_id=request.session_id,
            photo_ref=request.photo_ref,
            height_cm=request.height_cm,
        )
        return {
            "session_id": session.session_id,
            "status": session.status,
            "photo_uploaded": True,
        }
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Intake photo upload failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/intake/confirm")
async def confirm_intake_measurements(request: IntakeMeasurementConfirm):
    """
    Confirm extracted measurements or submit manual overrides.

    Request body (auto-confirm):
    {
      "session_id": "uuid-..."
    }

    Request body (manual override):
    {
      "session_id": "uuid-...",
      "manual_overrides": {
        "bust": 88.0,
        "waist": 70.0,
        "hips": 102.0,
        "height": 165.0
      }
    }
    """
    try:
        session = intake_orchestrator.confirm_measurements(
            session_id=request.session_id,
            manual_overrides=request.manual_overrides,
        )
        return {
            "session_id": session.session_id,
            "status": session.status,
            "shape_profile": session.shape_profile,
        }
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Intake measurement confirmation failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/intake/preferences")
async def submit_intake_preferences(request: IntakePreferencesRequest):
    """
    Submit style preferences and complete intake flow.

    Request body:
    {
      "session_id": "uuid-...",
      "preferred_colors": ["black", "navy"],
      "preferred_silhouettes": ["fitted", "flowing"],
      "occasions": ["work", "casual"],
      "coverage_prefs": {"neckline": "moderate"},
      "lifestyle_context": {"pace": "fast"},
      "free_text_notes": "Minimalist style"
    }
    """
    try:
        session = intake_orchestrator.capture_preferences(
            session_id=request.session_id,
            preferred_colors=request.preferred_colors,
            preferred_silhouettes=request.preferred_silhouettes,
            occasions=request.occasions,
            coverage_prefs=request.coverage_prefs,
            lifestyle_context=request.lifestyle_context,
            free_text_notes=request.free_text_notes,
        )
        return {
            "session_id": session.session_id,
            "status": session.status,
            "intake_complete": True,
            "shape_profile": session.shape_profile,
            "style_profile": session.style_profile.to_dict() if session.style_profile else None,
        }
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Intake preferences submission failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/intake/resume")
async def resume_intake_session(request: IntakeResumeRequest):
    """
    Resume an incomplete intake session.

    Request body:
    {
      "user_id": "user-123"
    }

    Returns:
    {
      "session_id": "uuid-...",
      "user_id": "user-123",
      "status": "photo_capture",
      "created_at": 1691111111.0
    }
    """
    try:
        session = intake_orchestrator.resume_session(user_id=request.user_id)
        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "status": session.status,
            "created_at": session.created_at,
        }
    except ModuleError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except Exception as err:
        logger.error("Intake session resume failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================================================================
# PHASE 2: RECOMMENDATION ENGINE ENDPOINTS
# =========================================================================


@app.get("/recommendations/{session_id}")
async def get_session_recommendations(
    session_id: str,
    k: int = 10,
    category_filter: Optional[List[str]] = None,
    occasion_filter: Optional[str] = None,
):
    """
    Get personalized recommendations for a completed intake session.

    Query params:
    - session_id: ID of completed intake session
    - k: Number of recommendations to return (default 10)
    - category_filter: Optional list of categories to restrict to (e.g., ["Tops", "Dresses"])
    - occasion_filter: Optional occasion to filter by (e.g., "work", "casual")

    Returns:
    {
      "session_id": "uuid-...",
      "recommendations": [
        {
          "sku": "top-123",
          "name": "Fitted Top",
          "category": "Tops",
          "price": 59.99,
          ...
        },
        ...
      ]
    }
    """
    try:
        # Retrieve the completed session
        session = intake_orchestrator.get_session(session_id)

        # Verify session is complete
        if session.status != "complete":
            raise ModuleError(
                f"Session must be complete to get recommendations (status={session.status})",
                "M5"
            )

        # Generate recommendations
        recommendations = recommendation_engine.generate_recommendations(
            session,
            k=k,
            category_filter=category_filter,
            occasion_filter=occasion_filter,
        )

        return {
            "session_id": session_id,
            "recommendations": recommendations,
        }
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except Exception as err:
        logger.error("Recommendation retrieval failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================================================================
# PHASE 3: FIT CHECKING ENDPOINTS
# =========================================================================


@app.post("/fit-check/{session_id}/{product_sku}")
async def check_product_fit(session_id: str, product_sku: str):
    """
    Get fit assessment for a specific product based on user measurements.

    Path params:
    - session_id: ID of completed intake session
    - product_sku: SKU of product to check fit for

    Returns:
    {
      "product_sku": "top-123",
      "fit_scores": { "XS": 0.65, "S": 0.92, "M": 0.88, "L": 0.45 },
      "recommended_size": "S",
      "fit_notes": [
        "Size S fits perfectly.",
        "Size M is slightly loose in waist."
      ],
      "confidence": 0.92
    }
    """
    try:
        # Retrieve the completed session
        session = intake_orchestrator.get_session(session_id)

        # Verify session is complete
        if session.status != "complete":
            raise ModuleError(
                "Session must be complete to check fit",
                "M7"
            )

        # Verify user has measurements
        if not session.body_measurements:
            raise ModuleError(
                "Session missing body measurements",
                "M7"
            )

        # Get product from catalog
        product = catalog.get_item(product_sku)
        if not product:
            raise ModuleError(
                f"Product {product_sku} not found in catalog",
                "M7"
            )

        # Check fit
        fit_assessment = fit_checker.check_fit(
            user_id=session.user_id,
            measurements=session.body_measurements.to_dict(),
            product=product,
            session_id=session_id,
        )

        # Save to history (M8) - non-critical, don't fail the fit check if save fails
        try:
            recommendation_history.save_fit_check(
                user_id=session.user_id,
                session_id=session_id,
                product_sku=product_sku,
                fit_result=fit_assessment,
            )
        except GuardrailError as err:
            logger.warn(
                "Fit check result not saved to history (guardrail): consent verification failed",
                {"error": str(err), "product_sku": product_sku}
            )
        except Exception as err:
            logger.warn(
                "Fit check result not saved to history (unexpected error)",
                {"error": str(err), "product_sku": product_sku, "type": type(err).__name__}
            )

        return fit_assessment
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except Exception as err:
        logger.error("Fit check failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================================================================
# M9 — NEW RELEASES FEED ENDPOINT
# =========================================================================


@app.get("/new-releases/{session_id}")
async def get_new_releases(session_id: str, limit: int = 20):
    """
    Get personalized new releases feed for a user based on their profiles.

    Path params:
    - session_id: ID of completed intake session

    Query params:
    - limit: Maximum number of items (1-100, default 20)

    Returns:
    [
      {
        "sku": "top-123",
        "name": "Navy Fitted Top",
        "category": "Tops",
        "match_score": 0.92,
        "matched_attributes": ["Flatters hourglass shapes", "Available in your colors (navy)"],
        "reason": "We think you'll like this because it flatters hourglass shapes.",
        "availability": {
          "recommended_size": "M",
          "available_sizes": ["XS", "S", "M", "L", "XL"]
        }
      },
      ...
    ]
    """
    try:
        # Retrieve the completed session
        session = intake_orchestrator.get_session(session_id)

        # Verify session is complete
        if session.status != "complete":
            raise ModuleError(
                "Session must be complete to view new releases",
                "M9"
            )

        # Verify user has profiles
        if not session.body_measurements or not session.shape_profile:
            raise ModuleError(
                "Session missing measurements or shape profile",
                "M9"
            )

        # Generate personalized feed
        feed = new_releases_feed.generate_feed(
            user_id=session.user_id,
            body_shape_profile=session.shape_profile,
            style_profile=session.style_profile.to_dict() if session.style_profile else None,
            measurements=session.body_measurements.to_dict(),
            limit=limit,
        )

        return feed
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except Exception as err:
        logger.error("New releases feed failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================================================================
# M8 — RECOMMENDATION HISTORY ENDPOINTS
# =========================================================================


@app.get("/history/{user_id}")
async def get_user_history(user_id: str, limit: int = 20):
    """
    Get fit check history for a user.

    Path params:
    - user_id: User identifier

    Query params:
    - limit: Maximum records to return (1-100, default 20)

    Returns:
    [
      {
        "check_id": "check_abc123",
        "product_sku": "top-123",
        "recommended_size": "M",
        "confidence": 1.0,
        "fit_scores": {"XS": 0.6, "S": 0.8, "M": 1.0, "L": 0.7},
        "fit_notes": ["Fits perfectly."],
        "checked_at": 1234567890.5
      },
      ...
    ]
    """
    try:
        history = recommendation_history.get_user_history(user_id, limit=limit)
        return history
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("History retrieval failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/history/session/{session_id}")
async def get_session_checks(user_id: str, session_id: str):
    """
    Get fit checks from a specific session.

    Path params:
    - session_id: Session identifier

    Query params:
    - user_id: User identifier (for access control)

    Returns:
    [
      {
        "check_id": "check_abc123",
        "product_sku": "top-123",
        "recommended_size": "M",
        "confidence": 1.0,
        "fit_scores": {...},
        "fit_notes": [...],
        "checked_at": 1234567890.5
      },
      ...
    ]
    """
    try:
        checks = recommendation_history.get_session_checks(user_id, session_id)
        return checks
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))


@app.get("/history/product/{product_sku}")
async def get_product_trend(user_id: str, product_sku: str, limit: int = 10):
    """
    Get fit check history for a specific product (trend analysis).

    Path params:
    - product_sku: Product to analyze

    Query params:
    - user_id: User identifier
    - limit: Maximum records to return (1-100, default 10)

    Returns fit checks for this product over time, showing how assessment changes.
    """
    try:
        trend = recommendation_history.get_product_trend(user_id, product_sku, limit=limit)
        return trend
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))


@app.get("/trends/{user_id}")
async def get_user_trends(user_id: str):
    """
    Get aggregate trend analysis for a user's fit preferences.

    Path params:
    - user_id: User identifier

    Returns:
    {
      "most_checked_products": [("top-123", 15), ("top-456", 10), ...],
      "avg_confidence_by_size": {"M": 0.92, "L": 0.87, ...},
      "preferred_sizes": [("M", 20), ("L", 15), ...],
      "total_checks": 50,
      "date_range": {
        "earliest": 1234567890.0,
        "latest": 1234567950.0
      }
    }
    """
    try:
        analysis = recommendation_history.analyze_user_trends(user_id)
        return analysis
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except Exception as err:
        logger.error("Trend analysis failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================================================================
# M10 — LEARNING LOOP FEEDBACK ENDPOINTS
# =========================================================================


class FitFeedbackRequest(BaseModel):
    user_id: str
    fit_check_id: str
    product_sku: str
    feedback_type: str  # "too_tight", "perfect", or "too_loose"
    actual_size: Optional[str] = None
    notes: Optional[str] = None


class ProductFeedbackRequest(BaseModel):
    user_id: str
    product_sku: str
    feedback_type: str  # "liked", "disliked", or "neutral"
    purchased: bool = False
    rating: Optional[float] = None
    notes: Optional[str] = None


@app.post("/feedback/fit")
async def submit_fit_feedback(request: FitFeedbackRequest):
    """
    Submit feedback on how a recommended fit actually fit.

    Request body:
    {
      "user_id": "user-123",
      "fit_check_id": "check-456",
      "product_sku": "top-123",
      "feedback_type": "perfect",
      "actual_size": "M",
      "notes": "Fit perfectly as recommended"
    }

    Returns:
    {
      "feedback_id": "feedback-...",
      "user_id": "user-123",
      "product_sku": "top-123",
      "feedback_type": "perfect",
      "submitted_at": 1691111111.0,
      "saved": true
    }
    """
    try:
        feedback = learning_loop.submit_fit_feedback(
            user_id=request.user_id,
            fit_check_id=request.fit_check_id,
            product_sku=request.product_sku,
            feedback_type=request.feedback_type,
            actual_size=request.actual_size,
            notes=request.notes,
        )
        return feedback
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Fit feedback submission failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/feedback/product")
async def submit_product_feedback(request: ProductFeedbackRequest):
    """
    Submit feedback on product satisfaction.

    Request body:
    {
      "user_id": "user-123",
      "product_sku": "top-123",
      "feedback_type": "liked",
      "purchased": true,
      "rating": 4.5,
      "notes": "Love the color and fit"
    }

    Returns:
    {
      "feedback_id": "feedback-...",
      "product_sku": "top-123",
      "feedback_type": "liked",
      "submitted_at": 1691111111.0,
      "saved": true
    }
    """
    try:
        feedback = learning_loop.submit_product_feedback(
            user_id=request.user_id,
            product_sku=request.product_sku,
            feedback_type=request.feedback_type,
            purchased=request.purchased,
            rating=request.rating,
            notes=request.notes,
        )
        return feedback
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Product feedback submission failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/feedback/summary/{user_id}")
async def get_feedback_summary(user_id: str):
    """
    Get aggregate feedback summary for a user.

    Path params:
    - user_id: User identifier

    Returns:
    {
      "user_id": "user-123",
      "fit_feedback_stats": {
        "total": 10,
        "perfect": 7,
        "tight": 2,
        "loose": 1,
        "perfect_percentage": 0.7
      },
      "product_feedback_stats": {
        "liked": 5,
        "disliked": 1,
        "neutral": 2
      },
      "total_feedback_records": 13
    }
    """
    try:
        summary = learning_loop.get_user_feedback_summary(user_id)
        return summary
    except GuardrailError as err:
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err))
    except Exception as err:
        logger.error("Feedback summary retrieval failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
