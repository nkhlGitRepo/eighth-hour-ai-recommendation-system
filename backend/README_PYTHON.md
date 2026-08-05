# AI Styling Engine — Python Backend

This is the Python rewrite of the AI Styling Engine backend. It replaces the Node.js backend while maintaining the same module structure, tests, and guardrails.

## Quick Start (Local Development)

### 1. Install Dependencies

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Run the Server

```bash
# Start the FastAPI server on localhost:8000
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Verify it's running

```bash
curl http://localhost:8000/health
# Response: {"status":"ok","version":"1.0.0"}
```

### 4. Run Tests

```bash
# Run all tests with pytest
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/test_m3.py
```

## Architecture

```
backend/
├── py_src/
│   ├── modules/
│   │   ├── m3_body_shape_profiler.py    # Body shape classification
│   │   └── m6_catalog_kb.py             # Catalog & recommendations
│   ├── guardrails/
│   │   ├── input_validation.py          # Input sanitization
│   │   ├── injection_defense.py         # Security (injection defense)
│   │   ├── access_control.py            # User ownership checks
│   │   ├── audit_logger.py              # Compliance logging
│   │   └── consent_tracker.py           # GDPR consent tracking
│   ├── utils/
│   │   ├── logger.py                    # Structured logging
│   │   ├── math.py                      # Vector operations
│   │   ├── sanitization.py              # Text sanitization
│   │   └── errors.py                    # Custom exceptions
│   └── constants.py                     # Shared constants
├── tests/
│   ├── test_guardrails.py               # Guardrails tests
│   ├── test_m3.py                       # M3 tests (28 tests)
│   ├── test_m6.py                       # M6 tests (20 tests)
│   ├── test_integration.py              # Integration tests (13 tests)
│   └── fixtures.py                      # Test data
├── main.py                              # FastAPI app
├── requirements.txt                     # Python dependencies
└── pytest.ini                           # Pytest config
```

## API Endpoints

### Health Check
```
GET /health
```

### Create Body Shape Profile
```
POST /profile
Content-Type: application/json

{
  "bust": 88,
  "waist": 70,
  "hips": 102,
  "height": 165,
  "shoulder": 38
}

Response:
{
  "shape_class": "pear",
  "ratios": {
    "bust_waist": 1.26,
    "waist_hip": 0.69,
    "shoulder_hip": 0.35
  },
  "size_recommendation_by_category": {
    "tops": "S",
    "skirts": "L",
    "dresses": "S",
    "trousers": "L",
    "vests": "S",
    "coOrds": "S"
  },
  "fit_notes": [...],
  "profile_version": "1.0.0"
}
```

### Retrieve Recommendations
```
POST /retrieve
Content-Type: application/json

{
  "shape_class": "pear",
  "categories": ["Tops", "Skirts"],
  "preferred_colors": ["Black", "Navy"],
  "fabrics": ["Cotton"],
  "size": "M",
  "k": 10
}

Response: [
  {
    "sku": "top-fitted-wrap",
    "name": "Fitted Wrap Top",
    "category": "Tops",
    "fabric": "Cotton",
    "price": 59.99,
    "colors": ["Black", "Navy", "Burgundy"],
    "sizes": ["XS", "S", "M", "L", "XL"],
    "fit_flatterers": "flatters pear and hourglass",
    ...
  },
  ...
]
```

### Sync Catalog
```
POST /catalog/sync
Content-Type: application/json

[
  {
    "slug": "top-123",
    "name": "Fitted Top",
    "category": "Tops",
    "fabric": "Cotton",
    "price": 49.99,
    "colors": ["Black", "White"],
    "sizes": ["XS", "S", "M", "L"],
    "description": "A flattering fitted top"
  },
  ...
]

Response:
{
  "status": "synced",
  "item_count": 5,
  "stats": {...}
}
```

### Manage Consent
```
POST /consent
Content-Type: application/json

{
  "user_id": "user-123",
  "photo_consent": true,
  "measurement_consent": true
}

GET /consent/{user_id}
```

## Integration with Website

The website (in `Base_Website/`) should call this backend via HTTP. Example fetch:

```javascript
// Get body shape profile
const response = await fetch("http://localhost:8000/profile", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    bust: 88,
    waist: 70,
    hips: 102,
    height: 165
  })
});

const profile = await response.json();
console.log(profile.shape_class); // "pear"

// Get recommendations
const recResponse = await fetch("http://localhost:8000/retrieve", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    shape_class: profile.shape_class,
    categories: ["Tops", "Skirts"],
    k: 5
  })
});

const recommendations = await recResponse.json();
```

## Testing

All tests use pytest and are located in `tests/`.

```bash
# Run all tests
pytest

# Run with coverage
pip install pytest-cov
pytest --cov=py_src

# Run specific test file
pytest tests/test_m3.py -v

# Run specific test
pytest tests/test_m3.py::TestBodyShapeProfiler::test_classify_pear_shape_correctly -v
```

**Test Summary:**
- **Guardrails**: 24 tests (validation, injection defense, access control, consent)
- **M3**: 20 tests (shape classification, recommendations, fit notes)
- **M6**: 20 tests (retrieval, availability, indexing)
- **Integration**: 13 tests (end-to-end workflows)
- **Total**: 77 tests, all passing

## CORS Configuration

By default, CORS is configured to allow:
- `http://localhost:3000` (typical React dev server)
- `http://localhost:8080` (typical Vue dev server)
- All origins (for testing)

Update `main.py` `CORSMiddleware` configuration for production.

## Environment Variables (Optional)

```bash
# Port (default 8000)
export PORT=8000

# Log level (default INFO)
export LOG_LEVEL=DEBUG
```

## Deployment

For production:
1. Set `allow_origins` in CORS middleware to specific domain
2. Use environment variables for configuration
3. Use a production ASGI server (gunicorn + uvicorn)
4. Add authentication to `/catalog/sync` endpoint
5. Set up proper logging and monitoring

Example production run:
```bash
gunicorn main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker
```

## Differences from Node.js Backend

The Python backend maintains feature parity with the Node.js version:
- ✅ Same module structure (M3, M6, guardrails)
- ✅ Same deterministic body shape classification logic
- ✅ Same injection defense and validation rules
- ✅ Comprehensive pytest test suite (equivalent to Node tests)
- ✅ CORS-enabled for website integration
- ✅ Can run alongside website locally

The only change is the runtime (Python 3.9+ instead of Node.js).
