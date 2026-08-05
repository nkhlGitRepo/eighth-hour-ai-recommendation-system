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
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.consent_tracker import ConsentTracker
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
intake_orchestrator = IntakeOrchestrator()  # Shares consent_tracker with orchestrator


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
