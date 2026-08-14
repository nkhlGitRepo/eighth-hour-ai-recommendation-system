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

# Which sizing provider powers photo measurement (default "mock")
export SIZING_PROVIDER=mock
```

## Adding a Real Sizing Provider (Photo Measurement)

Photo measurement (`POST /intake/photo-measure`) ships against
`MockSizingProvider`, which returns fixed measurements so the whole flow —
upload, validation, consent, profile generation, UI — works without a vendor
account. Swapping in a real API is intended to be **one class, one registry
line, and one environment variable**. Nothing in the endpoint, orchestrator,
or frontend should need to change.

### 1. Write the provider

Subclass `SizingProvider` in `py_src/modules/m2_sizing_integration.py` (or its
own module). Implement `extract_from_image` — that's the method the upload flow
calls — and declare `disclosure`:

```python
class AcmeSizingProvider(SizingProvider):
    def extract_measurements(self, photo_ref, height_cm=None):
        # Only needed if you support the URI/object-ref flow. Otherwise
        # raise ModuleError("not supported", "M2").
        ...

    def extract_from_image(self, image_bytes, content_type, height_cm=None):
        api_key = os.environ["ACME_API_KEY"]      # read your own credentials
        # POST the bytes to the vendor, poll if the job is async, then map
        # their response onto Measurements. IMPORTANT: convert to CENTIMETRES
        # if the vendor returns inches -- this codebase is cm end to end.
        return Measurements(
            bust=..., waist=..., hips=..., height=...,
            unit="cm",
            confidence_scores={"bust": 0.9, "waist": 0.9, "hips": 0.9},
            provider="acme",
            provider_version="v2",
        )

    @property
    def disclosure(self):
        # This is rendered verbatim into the notice shown to the customer
        # BEFORE they upload. If images leave this server, say so plainly --
        # the contract tests enforce that.
        return {
            "processor_name": "Acme Body Scan (third-party processor)",
            "sends_image_offsite": True,
            "stores_image": False,
            "retention": "Your photo is sent to Acme to produce the estimate "
                         "and is not retained by us afterwards.",
        }
```

Raise `ModuleError(message, "M2")` for failures (bad image, auth failure,
timeout, rate limit). The message reaches the customer as inline error text on
the upload screen, so make it human-readable.

### 2. Register it

```python
SIZING_PROVIDERS = {
    "mock": MockSizingProvider,
    "mediapipe": _mediapipe_provider,
    "acme": AcmeSizingProvider,   # <-- one line
}
```

### Already available: `mediapipe` (free, local, real analysis)

`SIZING_PROVIDER=mediapipe` uses Google's MediaPipe pose model running on this
server -- no API key, no rate limit, nothing transmitted off the machine. It
genuinely analyses the photo: different bodies give different measurements, and
a photo with no recognisable standing person (a car, a landscape, a yoga pose)
is refused rather than measured.

```bash
pip install mediapipe            # ~350 MB installed, ~200 MB RAM at inference
export SIZING_PROVIDER=mediapipe
```

The pose model (`pose_landmarker_lite.task`, 5.5 MB) is downloaded from Google's
CDN into `backend/models/` on first use and cached; it's gitignored as a build
artifact. For an offline or reproducible deploy, bake the file in and set
`MEDIAPIPE_POSE_MODEL=/path/to/pose_landmarker_lite.task`.

Accuracy: landmarks give *breadths*, while tape measurements are
*circumferences*, so `py_src/providers/anthropometry.py` bridges the gap with
population-average ratios (documented in that file). Results genuinely track the
customer's proportions and stated height, but are approximate -- materially less
accurate than a paid vendor doing 3D reconstruction. Treat it as a working,
honest stand-in that proves the whole pipeline, not as a final answer.

Verifying it:

```bash
# rejection behaviour (no photo needed)
python scripts/verify_pose_provider.py

# the happy path, with a real standing photo of a person
python scripts/verify_pose_provider.py /path/to/photo.jpg 172
```

That script exists because MediaPipe's inference deadlocks inside pytest on
macOS/Python 3.13 (identical calls finish in ~1s standalone). The model-free
logic -- scale math, pose validation, plausibility bounds -- is fully covered by
`tests/test_anthropometry.py` and `tests/test_mediapipe_provider.py` using
synthetic landmarks; only the real-model checks live in the script.

### 3. Configure it

```bash
export SIZING_PROVIDER=acme
export ACME_API_KEY=...   # your provider's own credentials
```

An unrecognized `SIZING_PROVIDER` fails at startup rather than silently
falling back to mock measurements.

### 4. Verify it against the contract suite

```bash
# Add your class to PROVIDERS_UNDER_TEST at the top of the file, then:
pytest tests/test_sizing_provider_contract.py -v
```

`tests/test_sizing_provider_contract.py` encodes every assumption the rest of
the app makes about a provider: centimetres, values inside
`constants.MEASUREMENT_RANGES`, the supplied height honored as the scale
reference, populated `provider`/`provider_version`, confidence scores in 0-1,
empty uploads rejected, and a complete `disclosure`. **Units are the most
common real integration bug** — a vendor returning inches will fail
`test_units_are_centimetres` and `test_values_within_supported_ranges` rather
than silently producing wrong dress sizes.

### Before going live with a real vendor

- Images will leave this machine, so serve over **HTTPS** and put a
  data-processing agreement in place with the vendor.
- The customer-facing notice comes from your `disclosure` — it is not legal
  advice and should be reviewed by a lawyer, along with the retention policy
  in the site FAQ (`Base_Website/js/faq.js`, "Photo & Measurement Data").
- Photo consent is enforced at the endpoint via
  `ConsentTracker.has_photo_consent`. Note that step 1 of the intake flow
  currently requires photo consent together with measurement consent; if you
  need unbundled consent (GDPR "freely given"), that's a separate change to
  `record_consent` and its tests.

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
