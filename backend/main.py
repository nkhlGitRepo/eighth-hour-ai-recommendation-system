"""
FastAPI server for the AI Styling Engine.

Runs on localhost:8000 by default.
Website calls this API to get styling recommendations.
"""

from fastapi import FastAPI, HTTPException, Query, Header, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import hashlib
import json
import os
import time

from py_src.modules.m1_intake_orchestrator import IntakeOrchestrator, IntakeState
from py_src.modules.m2_sizing_integration import SizingIntegration, build_sizing_provider
from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
from py_src.modules.m5_recommendation_engine import RecommendationEngine
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.modules.m7_fit_checker import FitChecker
from py_src.modules.m8_recommendation_history import RecommendationHistory
from py_src.modules.m9_new_releases_feed import NewReleasesFeed
from py_src.modules.m10_learning_loop import LearningLoop
from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.guardrails.access_control import AccessControl
from py_src.guardrails.auth_manager import AuthManager
from py_src.guardrails.image_validation import (
    ImageValidator,
    ImageTooLargeError,
    MAX_IMAGE_BYTES,
)
from py_src.persistence.session_repository import SQLiteSessionRepository
from py_src.persistence.user_repository import UserRepository
from py_src.utils.errors import ModuleError, GuardrailError, AuthError
from py_src.utils.logger import logger
from py_src.constants import (
    CATEGORY_TO_SIZE_PROFILE_KEY,
    SIZE_CHART_SOURCE,
    STANDARD_SIZES,
)

# Initialize FastAPI app
app = FastAPI(title="AI Styling Engine", version="1.0.0")

# Which sites may call the API from a browser. Defaults to the local storefront;
# a deployment names its real site(s) in ALLOWED_ORIGINS, comma-separated. No
# wildcard: with allow_credentials, "*" makes the API echo back any origin that
# asks, so every website on the internet could call it as the visitor.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080,http://localhost:3000",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AuthError)
async def handle_auth_error(request, exc: AuthError):
    """
    AuthError -> 401 ("we don't know who you are"), kept distinct from
    GuardrailError -> 403 ("we know who you are but you lack permission").
    Registered globally because AuthError can be raised inside a FastAPI
    dependency (get_current_user_id below), before an endpoint's own
    try/except body ever runs.
    """
    return JSONResponse(status_code=401, content={"detail": exc.message})


# When this process started, and a hash of the reference data it loaded. Both
# are reported by /health so a stale process can be spotted without guessing --
# see that endpoint for why. Computed lazily so the catalog hash reflects what
# was actually loaded at startup rather than what is on disk right now.
PROCESS_STARTED_AT = time.time()


def _source_digest():
    """
    Hash of every Python source file the app is built from.

    The data hashes below catch an edited size chart or catalog, but they would
    happily report "current" for a process running a month-old M5 -- which is
    the more common way this goes wrong, since logic changes far more often than
    the chart does. Read once at import, so it describes the code this process
    actually loaded rather than what is on disk now.
    """
    root = os.path.dirname(os.path.abspath(__file__))
    accumulator = hashlib.sha256()
    for directory, _, filenames in sorted(os.walk(os.path.join(root, "py_src"))):
        if "__pycache__" in directory:
            continue
        for filename in sorted(filenames):
            if filename.endswith(".py"):
                accumulator.update(
                    open(os.path.join(directory, filename), "rb").read()
                )
    accumulator.update(open(os.path.join(root, "main.py"), "rb").read())
    return accumulator.hexdigest()[:12]


SOURCE_DIGEST = _source_digest()


def runtime_fingerprint():
    """
    Short hashes of the size chart and catalog this process is serving.

    Deliberately derived from the in-memory objects, not by re-reading the
    files: re-reading would report what the source says today and hide exactly
    the drift this is meant to expose.
    """
    def digest(payload):
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:12]

    items = getattr(catalog, "items", None) or {}
    catalog_state = sorted(
        (slug, item.get("length"), tuple(item.get("sizes") or ()))
        for slug, item in (items.items() if isinstance(items, dict) else [])
    )
    return {
        "source": SOURCE_DIGEST,
        # Which sizing provider this process started with. Comes from an env
        # var, so unlike everything else here it cannot be checked against the
        # source -- but it is the setting most easily lost across a restart, and
        # losing it silently swaps real photo analysis for fixed demo numbers.
        "sizing_provider": sizing_integration.provider.__class__.__name__,
        "size_chart": digest(SIZE_CHART_SOURCE),
        "sizes": list(STANDARD_SIZES),
        "catalog": digest(catalog_state),
        "product_count": len(catalog_state),
    }


# Initialize modules
profiler = BodyShapeProfiler()
catalog = CatalogKB([])  # Will be populated from website
session_repo = SQLiteSessionRepository()
# Explicit, stable path (matching session_repo's) so consent survives
# server restarts instead of silently reverting to "not consented" for
# customers whose sessions are still valid on disk.
consent_tracker = ConsentTracker(db_path=session_repo.db_path)
# Same db-file-sharing pattern as consent_tracker above.
user_repository = UserRepository(db_path=session_repo.db_path)
auth_manager = AuthManager(user_repository)
# Sizing provider comes from the SIZING_PROVIDER env var (defaults to the
# mock estimator). This is the only wiring a real vendor integration needs --
# see py_src/modules/m2_sizing_integration.py's registry, and the README's
# "Plugging in a photo-measurement API" section.
sizing_integration = SizingIntegration(provider=build_sizing_provider())
intake_orchestrator = IntakeOrchestrator(
    session_repo=session_repo,
    consent_tracker=consent_tracker,
    catalog=catalog,
    sizing=sizing_integration,
)
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
# STARTUP: Load products from catalog file
# =========================================================================

@app.on_event("startup")
async def load_products():
    """Automatically load products from products.json on startup."""
    products_file = os.path.join(os.path.dirname(__file__), 'products.json')
    if os.path.exists(products_file):
        try:
            with open(products_file, 'r') as f:
                products = json.load(f)
            catalog.rebuild(products)
            logger.info(f"Loaded {len(products)} products from products.json", {})
        except Exception as e:
            logger.error(f"Failed to load products.json: {str(e)}", {})


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
    """
    A product pushed through /catalog/sync.

    Every field the engine reads has to appear here, because the endpoint
    REPLACES the catalog with exactly these fields and anything absent is
    silently dropped. It was already losing `silhouette` and `launched_at` --
    which drive M6's ranking and M9's whole recency window -- so a single sync
    would have degraded recommendations with no error anywhere. The
    length/model fields would have joined them.

    `length` defaults to None, not "Regular": two catalog products are delisted
    upstream and deliberately carry no length, and a default would have quietly
    reinstated the placeholder that made the length advice guess.
    """

    slug: str
    name: str
    category: str
    fabric: str
    price: float
    colors: Optional[List[str]] = []
    sizes: Optional[List[str]] = []
    description: Optional[str] = ""
    length: Optional[str] = None
    silhouette: Optional[str] = None
    launched_at: Optional[str] = None
    fit: Optional[str] = None
    model_name: Optional[str] = None
    model_height_cm: Optional[float] = None
    model_size: Optional[str] = None


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
# ACCOUNT AUTHENTICATION MODELS + DEPENDENCY
# =========================================================================


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def get_bearer_token(authorization: Optional[str] = Header(None)) -> str:
    """Defensive header parsing -- malformed/missing Authorization always
    raises a clean AuthError (-> 401), never a 500."""
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Missing or malformed Authorization header")
    token = authorization[len("Bearer "):].strip()
    if not token:
        raise AuthError("Missing or malformed Authorization header")
    return token


def get_current_user_id(token: str = Depends(get_bearer_token)) -> str:
    """FastAPI dependency: resolves the bearer token to a user_id, or
    raises AuthError (-> 401) if it's missing, malformed, or expired."""
    return auth_manager.get_current_user_id(token)


# =========================================================================
# ENDPOINTS
# =========================================================================


@app.get("/health")
async def health_check():
    """
    Health check, plus a fingerprint of the data this process actually loaded.

    The fingerprint exists because "the server is up" and "the server is running
    your code" are different questions, and only the first one used to be
    answerable. Python reads constants.py and products.json once at import, so a
    process started before an edit keeps serving the old size chart and the old
    catalog indefinitely, with a perfectly healthy /health. That has now caused
    two separate false diagnoses -- a browser check that showed six sizes and a
    wrong recommendation for half an hour, against a backend nobody had
    restarted.

    Comparing these hashes against the ones the current source produces makes
    the mismatch a one-line check instead of an archaeology exercise:

        python3 scripts/check_running_server.py
    """
    return {
        "status": "ok",
        "version": "1.0.0",
        "started_at": PROCESS_STARTED_AT,
        "fingerprint": runtime_fingerprint(),
    }


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
# ACCOUNT AUTHENTICATION ENDPOINTS
# =========================================================================


@app.post("/auth/register")
async def register(request: RegisterRequest):
    """
    Create a new account. Does NOT log the user in -- registration only
    creates the account; the user logs in separately afterward.

    Request body:
    {
      "username": "alice",
      "email": "alice@example.com",
      "password": "correct horse battery staple"
    }

    Returns:
    {
      "user_id": "user_...",
      "username": "alice"
    }
    """
    try:
        return auth_manager.register(request.username, request.email, request.password)
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err.message))
    except Exception as err:
        logger.error("Registration failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/auth/login")
async def login(request: LoginRequest):
    """
    Log in with username + password.

    Request body:
    {
      "username": "alice",
      "password": "correct horse battery staple"
    }

    Returns:
    {
      "user_id": "user_...",
      "username": "alice",
      "token": "..."
    }
    """
    try:
        return auth_manager.login(request.username, request.password)
    except AuthError as err:
        raise HTTPException(status_code=401, detail=err.message)
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err.message))
    except Exception as err:
        logger.error("Login failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/auth/logout")
async def logout(user_id: str = Depends(get_current_user_id), token: str = Depends(get_bearer_token)):
    """Revoke the current token only (other devices/sessions stay logged in)."""
    try:
        auth_manager.logout(token)
        return {"logged_out": True}
    except Exception as err:
        logger.error("Logout failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/auth/logout-all")
async def logout_all(user_id: str = Depends(get_current_user_id)):
    """Revoke every token for this account (all devices/sessions)."""
    try:
        auth_manager.logout_all(user_id)
        return {"logged_out_all": True}
    except Exception as err:
        logger.error("Logout-all failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/auth/change-password")
async def change_password(
    request: ChangePasswordRequest,
    user_id: str = Depends(get_current_user_id),
    token: str = Depends(get_bearer_token),
):
    """Change password. Requires the current password. Revokes every other token."""
    try:
        auth_manager.change_password(user_id, request.current_password, request.new_password, token)
        return {"password_changed": True}
    except AuthError as err:
        raise HTTPException(status_code=401, detail=err.message)
    except ModuleError as err:
        raise HTTPException(status_code=400, detail=str(err.message))
    except Exception as err:
        logger.error("Password change failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/auth/me")
async def get_me(user_id: str = Depends(get_current_user_id)):
    """Get the current account's own identity."""
    try:
        user = user_repository.get_user_by_id(user_id)
        if not user:
            raise AuthError("Invalid or expired token")
        return {"user_id": user["user_id"], "username": user["username"], "email": user["email"]}
    except AuthError as err:
        raise HTTPException(status_code=401, detail=err.message)
    except Exception as err:
        logger.error("Get current user failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/account/profile")
async def get_account_profile(user_id: str = Depends(get_current_user_id)):
    """
    Get the account's most recently completed style profile, or null if
    the account hasn't completed the intake quiz yet.

    Returns:
    {
      "session_id": "uuid-...",
      "shape_profile": {...},
      "style_profile": {...},
      "measurements": {"bust": ..., "waist": ..., "hips": ..., "height": ...}
    } or null
    """
    try:
        session = session_repo.get_latest_completed_session_by_user(user_id)
        if not session:
            return None
        return {
            "session_id": session.session_id,
            "shape_profile": session.shape_profile,
            "style_profile": session.style_profile.to_dict() if session.style_profile else None,
            "measurements": session.body_measurements.to_dict() if session.body_measurements else None,
        }
    except Exception as err:
        logger.error("Account profile retrieval failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


# =========================================================================
# PHASE 1: INTAKE ORCHESTRATION ENDPOINTS
# =========================================================================


@app.post("/intake/session")
async def create_intake_session(user_id: str = Depends(get_current_user_id)):
    """
    Create a new intake session for the authenticated user.

    Requires: Authorization: Bearer <token>

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


@app.get("/intake/photo-disclosure")
async def get_photo_disclosure():
    """
    How the currently-configured sizing provider handles a customer's photo.

    The upload screen renders its legal notice from this rather than from
    hardcoded copy, so the disclosure can't silently go stale: with the mock
    provider nothing leaves this server, and the day a real vendor is
    configured the notice starts naming it automatically.

    Returns:
    {
      "processor_name": "...",
      "sends_image_offsite": false,
      "stores_image": false,
      "retention": "..."
    }
    """
    try:
        return sizing_integration.disclosure
    except NotImplementedError as err:
        # Fail closed. The frontend refuses to show upload controls without a
        # valid disclosure, which is the correct outcome: better to disable
        # the feature than to collect a body photo under a notice we can't
        # actually stand behind.
        logger.error("Sizing provider does not declare a disclosure", err)
        raise HTTPException(
            status_code=500,
            detail="Photo measurement is unavailable: provider disclosure missing",
        )


@app.post("/intake/photo-measure")
async def measure_from_photo(
    session_id: str = Form(...),
    height_cm: float = Form(...),
    photo: UploadFile = File(...),
    usual_top_size: Optional[str] = Form(None),
    usual_bottom_size: Optional[str] = Form(None),
    user_id: str = Depends(get_current_user_id),
):
    """
    Estimate body measurements from an uploaded photo, then generate the
    shape profile -- the backing call for "Use photo measurement" on the
    intake flow's measurements step.

    Multipart form fields:
    - session_id: the caller's intake session
    - height_cm: the customer's height, used as the scale reference
    - photo: JPEG/PNG/WEBP image

    Requires: Authorization: Bearer <token>, and photo consent on record.

    The image is never persisted: it is not stored in the database, not
    recorded on the session, and not logged. Like any upload it is buffered
    for the life of the request (Starlette spools bodies over 1 MB to a temp
    file), and that buffer is released in the `finally` below -- so the
    customer-facing claim is non-retention, not "never touches disk".

    Returns:
    {
      "session_id": "...",
      "status": "profile_generation",
      "shape_profile": {...},
      "measurements": {...},
      "low_confidence_fields": [],
      "provider": "mock"
    }
    """
    try:
        # Ownership: the session must belong to the authenticated caller.
        session = intake_orchestrator.get_session(session_id)
        if not AccessControl.user_owns_resource(user_id, session.user_id):
            raise GuardrailError(
                "User does not have access to this intake session",
                "AccessControl",
            )

        # Biometric data needs explicit photo consent. Until now this app
        # collected photo consent but never actually enforced it anywhere.
        if not consent_tracker.has_photo_consent(user_id):
            raise GuardrailError(
                "User has not consented to photo processing",
                "ConsentTracker",
            )

        # Read with a hard bound, then validate before the bytes go anywhere.
        # Reading one byte past the cap is enough to detect an over-size
        # upload without buffering the whole thing.
        image_bytes = await photo.read(MAX_IMAGE_BYTES + 1)
        content_type = ImageValidator.validate(image_bytes, photo.content_type)

        session = intake_orchestrator.extract_measurements_from_upload(
            session_id=session_id,
            image_bytes=image_bytes,
            content_type=content_type,
            height_cm=height_cm,
            usual_top_size=usual_top_size,
            usual_bottom_size=usual_bottom_size,
        )

        measurements = session.body_measurements
        return {
            "session_id": session.session_id,
            "status": session.status,
            "shape_profile": session.shape_profile,
            "measurements": measurements.to_dict() if measurements else None,
            "low_confidence_fields": measurements.low_confidence_fields() if measurements else [],
            # Read from the measurements themselves rather than the session's
            # redundant mirror field, which doesn't survive a reload.
            "provider": measurements.provider if measurements else None,
        }

    except ImageTooLargeError as err:
        logger.info("Photo measurement rejected: too large", {
            "content_type": photo.content_type, "filename": photo.filename,
        })
        raise HTTPException(status_code=413, detail=err.message)
    except GuardrailError as err:
        logger.info("Photo measurement rejected: not permitted", {"reason": str(err)})
        raise HTTPException(status_code=403, detail=str(err))
    except ModuleError as err:
        # Log every rejection with the format details. Without this, a photo
        # refused by the image validator produced a silent 400 -- which is
        # exactly how unsupported iPhone HEIC uploads went unnoticed.
        logger.info("Photo measurement rejected", {
            "reason": err.message,
            "content_type": photo.content_type,
            "filename": photo.filename,
        })
        raise HTTPException(status_code=400, detail=err.message)
    except Exception as err:
        logger.error("Photo measurement failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        # Drop the upload's handle explicitly; nothing retains the bytes.
        await photo.close()


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
    user_id: Optional[str] = None,
    category_filter: Optional[List[str]] = Query(None),
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

        # Verify session has a finished profile (see has_completed_profile)
        if not session.has_completed_profile():
            raise ModuleError(
                f"Session must be complete to get recommendations (status={session.status})",
                "M5"
            )

        # If the caller asserts a user_id, it must match this session's real
        # owner -- otherwise the parameter would silently accept any value
        # (previously computed into an unused "check_user_id" and never
        # actually checked against anything).
        if user_id and not AccessControl.user_owns_resource(user_id, session.user_id):
            raise GuardrailError(
                "User does not have access to this session's recommendations",
                "AccessControl"
            )

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
      "confidence": 0.92,
      "check_id": "check_abc123..."
    }

    check_id identifies this specific fit-check event in history. Pass it
    back as fit_check_id in POST /feedback/fit so the feedback can be
    correlated to this exact check (null if the check couldn't be saved
    to history, e.g. due to a consent issue).

    A "Co-ord Sets" product (a two-piece outfit) only has one size field
    to fill, so it's sized like a Top -- recommended_size reflects the
    customer's bust-driven size, matching the "tops" size already shown
    on their Shape Profile.
    """
    try:
        # Retrieve the completed session
        session = intake_orchestrator.get_session(session_id)

        # Verify session has a finished profile (see has_completed_profile)
        if not session.has_completed_profile():
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

        # Look up the size M3 already computed for this product's category
        # (e.g. hips-based for Skirts/Trousers, bust-based for Tops/
        # Dresses/Vests/Co-ord Sets) so the fit checker's recommended_size
        # can never disagree with what's already shown on the customer's
        # Shape Profile.
        known_size = None
        category = product.get("category")
        size_by_category = (session.shape_profile or {}).get("size_recommendation_by_category", {})
        size_profile_key = CATEGORY_TO_SIZE_PROFILE_KEY.get(category)
        if size_profile_key:
            known_size = size_by_category.get(size_profile_key)

        # Check fit
        fit_assessment = fit_checker.check_fit(
            user_id=session.user_id,
            measurements=session.body_measurements.to_dict(),
            product=product,
            session_id=session_id,
            known_size=known_size,
        )

        # Save to history (M8) - non-critical, don't fail the fit check if save fails.
        # check_id is the real key that later feedback (POST /feedback/fit) must
        # reference to correlate a specific fit-check event with what the
        # customer actually reported -- without it, feedback can only ever be
        # aggregated per-user, never joined back to the specific check that
        # prompted it.
        check_id = None
        try:
            check_id = recommendation_history.save_fit_check(
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

        return {**fit_assessment, "check_id": check_id}
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

        # Verify session has a finished profile (see has_completed_profile)
        if not session.has_completed_profile():
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
    except Exception as err:
        logger.error("Session checks retrieval failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


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
    except Exception as err:
        logger.error("Product trend retrieval failed", err)
        raise HTTPException(status_code=500, detail="Internal server error")


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

    # PORT is read here as well as by run.sh's already-in-use guard. If only the
    # guard honoured it, run.sh would check one port and the server would bind
    # another -- reintroducing the silent "started on top of an old process"
    # failure that guard exists to prevent.
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8000")))
