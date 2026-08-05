"""
FastAPI server for the AI Styling Engine.

Runs on localhost:8000 by default.
Website calls this API to get styling recommendations.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

from py_src.modules.m3_body_shape_profiler import BodyShapeProfiler
from py_src.modules.m6_catalog_kb import CatalogKB
from py_src.guardrails.input_validation import InputValidator
from py_src.guardrails.consent_tracker import ConsentTracker
from py_src.utils.errors import ModuleError
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
