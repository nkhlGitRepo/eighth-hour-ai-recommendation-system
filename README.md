# Eighth Hour — AI Styling & Fit Engine

A personal-styling and fit-recommendation system for the Eighth Hour womenswear label, built as a
FastAPI backend with a static storefront front end that mirrors [eighth-hour.com](https://www.eighth-hour.com/).

The problem it solves is the one that makes online clothes shopping frustrating: *what size do I
order, and which pieces will actually suit me?* A customer completes a short guided intake — consent,
body measurements (typed, or estimated from a photo), and style preferences — and the engine turns
that into a body-shape classification, a recommended size for every product category, a ranked list
of catalog pieces chosen for that shape, and a per-garment fit assessment explaining how each size
will sit on them.

Everything runs locally. There are no paid APIs, no external calls at runtime, and no customer data
leaves the machine. Photo measurement uses a pose model that runs on your own CPU, and the uploaded
image is held in memory and discarded — never written to disk.

**Status:** 1,062 tests — 1,058 passing, 4 skipped by design (they need the real pose model, which
deadlocks under pytest; see [Testing](#testing)). The recommendation, sizing, fit-checking and
history modules are complete. Photo measurement works but is deliberately weighted low — see
[Photo-based measurement](#5-photo-based-measurement-m2--providers) for the honest accuracy numbers.

---

## Contents

- [Running it](#running-it)
- [Sample inputs and outputs](#sample-inputs-and-outputs)
- [Backend features](#backend-features)
- [Frontend features](#frontend-features)
- [Plugging in a photo-measurement API](#plugging-in-a-photo-measurement-api)
- [Deployment](#deployment)
- [Testing](#testing)
- [Project layout](#project-layout)

---

## Running it

### Requirements

- **Python 3.11+** (developed and tested on 3.13; the pinned dependencies are what was verified)
- **Node.js** — only if you want to run the front-end integration tests; not needed to use the site
- No database server: persistence is SQLite, created automatically on first run

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`mediapipe` is the largest dependency (~200 MB installed) and is only needed for photo measurement.
If you don't want it, remove that line from `requirements.txt` before installing — everything else
works, and the app falls back to the mock sizing provider.

Start the API:

```bash
# From backend/, with the venv active:
python -m uvicorn main:app --port 8000

# With real photo measurement enabled:
SIZING_PROVIDER=mediapipe python -m uvicorn main:app --port 8000
```

The API is now on `http://localhost:8000`. FastAPI serves interactive docs at
`http://localhost:8000/docs`.

On first use with `SIZING_PROVIDER=mediapipe`, the pose model (~5.5 MB) downloads automatically to
`backend/models/`. That directory is gitignored — it's a build artifact, not source. This is the only
outbound network request the project ever makes, and it happens once.

### 2. Front end

```bash
cd Base_Website
python3 serve.py                  # http://localhost:8080
```

Use `serve.py` rather than `python3 -m http.server`. It serves the same files but sends
`Cache-Control: no-store`, which matters during development: the plain module sends no cache headers
at all, so a browser can mix a freshly-fetched script with a stale cached one and produce failures
that look like application bugs.

Open **http://localhost:8080**. Create an account, then follow **My Style** in the header.

### Is the server running your code?

**Restart the API after editing anything under `backend/`.** Python reads
`constants.py` and `products.json` once at import, so a process started before a
change keeps serving the old size chart, the old catalog and the old logic
indefinitely — with a completely healthy `/health`. This has caused two separate
false diagnoses during development, including half an hour spent investigating a
browser that showed six sizes and the wrong recommended size, against a backend
nobody had restarted.

`/health` now reports a fingerprint of what the process actually loaded — a hash
of every Python source file, plus the size chart and catalog — and one command
compares it against the working copy:

```bash
python scripts/check_running_server.py                        # exit 0 current, 1 stale, 2 nothing listening
python scripts/check_running_server.py --url http://127.0.0.1:8199
```

It also reports which sizing provider the process started with. That setting
comes from an env var rather than the source, so it can't be checked — but it is
the easiest thing to lose across a restart, and losing it silently swaps real
photo analysis for the demo estimator, which returns the **same fixed
measurements for every photo** and shows the customer a "Demo mode" warning:

```
sizing provider: MockSizingProvider  <-- demo estimator: every photo returns the same
fixed numbers. Start with SIZING_PROVIDER=mediapipe for real analysis.
```

`./run.sh` now defaults to `SIZING_PROVIDER=mediapipe` for that reason; pass
`SIZING_PROVIDER=mock ./run.sh` if you want the demo estimator (and no MediaPipe
install).

```
STALE: http://127.0.0.1:8000 is not running the current source. Restart it.
   * source         serving 'a41c9e02bb7d'  source says '7913f0fe01b3'
     size_chart     serving '1b4fc0868e97'  source says '1b4fc0868e97'
```

The exit status is meaningful, so it can gate a verification run rather than
being read by eye. Running `uvicorn` with `--reload` avoids the problem during
active development; the check is what catches it when you forget.

The front end has the same failure mode for a different reason, which `serve.py`
already handles — see [Front end](#2-front-end).

### Troubleshooting a profile that seems to have vanished

If New Releases or the product page's fit-check widget insist you have no style profile when you
plainly do, open **http://localhost:8080/diagnose.html**. It reports which keys are in local storage,
whether the token is valid, what the server thinks your session is, and — the case that is easy to
miss — whether the stored session id actually *matches* the server's. A stale id from an abandoned
earlier attempt looks entirely valid and passes every presence check, while every profile endpoint
rejects it. The page changes nothing unless you press its repair button.

Note that `localhost:8080` and `127.0.0.1:8080` are separate origins with separate local storage:
logging in on one does not log you in on the other. Pick one and stay on it.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SIZING_PROVIDER` | `mock` (but `run.sh` sets `mediapipe`) | Which sizing backend to use. `mediapipe` analyses the photo; `mock` returns the same fixed measurements for every image and tells the customer so. An unknown name fails loudly at startup rather than silently falling back. |
| `MEDIAPIPE_POSE_MODEL` | auto-downloaded | Path to a `.task` pose model, if you'd rather supply your own than let it fetch one. |

---

## Sample inputs and outputs

These are real responses from a running instance, not illustrations.

### Submitting measurements

```bash
curl -X POST http://localhost:8000/intake/confirm \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"<id>","manual_overrides":{"bust":93,"waist":73,"hips":98,"height":168}}'
```

```json
{
  "status": "preferences_capture",
  "shape_profile": {
    "shape_class": "hourglass",
    "ratios": { "bust_waist": 1.27, "waist_hip": 0.74, "shoulder_hip": 1.0 },
    "size_recommendation_by_category": {
      "tops": "S", "skirts": "S", "dresses": "S",
      "trousers": "S", "vests": "S", "coOrds": "S/S"
    },
    "fit_notes": [
      "Fitted styles will emphasize your balanced proportions.",
      "Wrap dresses and belted silhouettes are made for you.",
      "Look for pieces that define the waist."
    ],
    "profile_version": "1.0.0"
  }
}
```

### Getting recommendations

```bash
curl "http://localhost:8000/recommendations/<session_id>?k=3"
```

```json
{
  "sku": "crepe-silk-vest",
  "name": "Crepe Silk Vest",
  "category": "Vests",
  "price": 225.0,
  "fit_flatterers": "emphasizes waist",
  "flatters_shapes": ["apple", "athletic", "balanced", "hourglass", "pear"],
  "silhouette_class": "fitted"
}
```

### Checking fit on a specific garment

```bash
curl -X POST http://localhost:8000/fit-check/<session_id>/crepe-silk-pleated-dress
```

```json
{
  "recommended_size": "M",
  "confidence": 1.0,
  "fit_scores": {
    "XXS": 0.22, "XS": 0.48, "S": 0.73, "M": 1.0, "L": 0.69, "XL": 0.35, "XXL": 0.06
  },
  "fit_notes": ["Size M fits perfectly."]
}
```

Note that every size is scored, not just the winner — the neighbouring sizes score highest, and the
scores fall away in both directions. That property is enforced by a test.

### Photo measurement

```bash
curl -X POST http://localhost:8000/intake/photo-measure \
  -H "Authorization: Bearer <token>" \
  -F session_id=<id> -F height_cm=180 \
  -F usual_top_size=S -F usual_bottom_size=XS \
  -F photo=@full_body_photo.jpg
```

```json
{ "measurements": { "bust": 93.8, "waist": 69.4, "hips": 95.1, "height": 180 },
  "low_confidence_fields": [] }
```

Note where those numbers land: bust 93.8 is inside S's band and hips 95.1 inside XS's, matching the
two sizes that were stated. The photo moved the estimate within each band — it did not choose the
band.

A photo with no person in it is refused rather than measured:

```json
{ "detail": "We couldn't find a person in that photo. Please upload a clear, full-body photo of yourself facing the camera." }
```

---

## Backend features

Ten numbered modules under `backend/py_src/modules/`, plus a guardrail layer that every one of them
passes through.

### 1. Guided intake orchestration (M1)

**What it does.** Walks a customer through the profile in order — consent, then measurements, then
style preferences — and remembers where they are. Close the tab and come back, and you resume at the
same step with the same answers. If a scan produces numbers the engine isn't confident about, it
routes you to check them by hand instead of quietly accepting them.

**How it works.** `IntakeOrchestrator` is a state machine over an `IntakeSession` persisted in
SQLite. Each transition validates the current status before advancing, so steps can't be skipped or
replayed out of order. Measurements arrive by two routes — a stored photo reference and a direct
byte upload — that converge on one private helper, `_apply_extracted_measurements()`, so the two
paths cannot drift apart in how they store values, compute confidence, or decide what happens next.
That helper compares each field's confidence against a threshold and forks: below it, the session is
routed to manual entry; above it, the shape profile is generated immediately. A session ID that the
backend no longer recognises (a stale bookmark, a dev database reset) is detected client-side and
recovered by restarting the flow, rather than leaving the customer retrying a call that can never
succeed.

### 2. Body shape profiling (M3)

**What it does.** Turns three measurements into a shape — hourglass, pear, apple, athletic, straight
or balanced — a recommended size in every category, and a few sentences of genuinely useful styling
advice ("wrap dresses and belted silhouettes are made for you").

**How it works.** A deterministic rules classifier over bust-to-waist, waist-to-hip and
shoulder-to-hip ratios. No model, no training data, no randomness: the same measurements always
produce the same profile, which is what makes it testable and explainable to a customer. Sizes come
from the shared boundary tables rather than a local formula, so the size shown here is by
construction the same size the recommendation engine filters on and the fit checker scores against.
Category sizing follows how garments are actually cut — tops and dresses from the bust, skirts and
trousers from the hips — with apple shapes sized on the waist for tops, since that's the measurement
that determines whether a top fits them.

### 3. Size chart and boundary tables (`constants.py`)

**What it does.** Defines what each size means, in centimetres. It's the single reference every other
part of the system consults, so the size you're told on your profile is the same size used to filter
your recommendations and to score how a garment will fit.

**How it works.** `SIZE_CHART_SOURCE` holds Eighth Hour's official published chart — the measurement
*range* each size is cut for, XXS through XXL — and everything else is derived from it.
`STANDARD_SIZE_CHART` takes each row's midpoint; the three `*_SIZE_BOUNDARIES` tables build contiguous
lookup bands by meeting adjacent sizes at the midpoint of the gap between them, opening the outermost
bands out to the supported measurement range so every body maps somewhere. Nothing else in the
codebase writes a size range down.

The published rows are narrow — the bust steps about 5.7 cm per size, against the 8 cm of the uniform
grid this replaced — so the derived bands are correspondingly tight:

| | XXS | XS | S | M | L | XL | XXL |
|---|---|---|---|---|---|---|---|
| **bust** | 70–85.05 | 85.05–90.25 | 90.25–95.25 | 95.25–100.9 | 100.9–107.9 | 107.9–113.6 | 113.6–150 |
| **waist** | 55–64.75 | 64.75–69.75 | 69.75–74.85 | 74.85–80 | 80–88.3 | 88.3–94.6 | 94.6–130 |
| **hips** | 80–90.25 | 90.25–95.25 | 95.25–100.3 | 100.3–107.3 | 107.3–114.9 | 114.9–120 | 120–160 |

XXS and XXL open out to the validator's limits rather than stopping where the chart does, so a body
outside the published range still maps to the nearest size the shop actually stocks instead of failing
to map at all.

`tests/test_size_chart_integrity.py` locks in the structural invariants: bands are contiguous with no
gaps or overlaps, every published range maps entirely to its own size, and — the one the photo
estimator depends on — **every chart value looks up to its own size**. If that last one broke, a
customer stating "M" could be recommended S even with the photo contributing nothing.

**The Size Guide page is generated, not transcribed.** `Base_Website/size-guide.html` used to carry
the same numbers typed out by hand under a comment promising they matched the engine. They stopped
matching the first time the chart was revised and nothing noticed. The three tables are now written by
`backend/scripts/render_size_guide.py` from `SIZE_CHART_SOURCE`, and `tests/test_size_guide_page.py`
fails if the page and the chart ever disagree:

```bash
python scripts/render_size_guide.py            # rewrite the page from the chart
python scripts/render_size_guide.py --check     # exit 1 if it is stale
```

**Revising the chart also means migrating saved profiles.** `size_recommendation_by_category` is
computed once at the end of intake and then read back verbatim — `/account/profile` displays it, and
`/fit-check` passes it to M7 as `known_size`, which *forces* it as the recommended size. So a chart
revision leaves returning customers holding the old chart's answer scored against the new one: the
panel recommends S, shows XS scoring higher, and then reports that its own recommendation "runs large
in the bust". Their body hasn't changed; only the stored label is wrong. After any edit to
`SIZE_CHART_SOURCE`, run:

```bash
python scripts/migrate_stored_size_profiles.py --dry-run   # report what would change
python scripts/migrate_stored_size_profiles.py             # apply
```

It recomputes each saved profile by calling M3, rather than reimplementing the mapping — a migration
whose answer differs from the engine's only replaces one wrong stored size with another.
`tests/test_stored_profile_migration.py` pins both halves of that: the result matches M3 exactly
(including apple shapes being sized on the waist, and co-ord sets staying a `"M/L"` pair), and every
other column — measurements, consent, credentials — comes out byte-identical.

**On the trade-off of a finer chart.** Narrower bands mean the size you are told is a more precise
claim, but they also leave less room for measurement error. A stated size still pins the result
exactly — see [Photo-based measurement](#5-photo-based-measurement-m2--providers) — but an unanchored
photo estimate now has roughly 5.7 cm of bust to land in rather than 8, so the same cm of error is
about a third more likely to cross a boundary. That is the chart being more precise than the
measurement, not a regression in the measurement; it is also why the photo screen recommends stating
your usual sizes.

### 4. Garment length and height advice

**What it does.** Tells you where a hem will actually fall on *you*. The
photograph shows a midi skirt at mid-calf on a 5′6″ model; at 6′2″ the same skirt
lands just below the knee, and the product page now says so.

**How it works.** The garment is a fixed number of inches; the body it hangs on
isn't. Eighth Hour's published length guide states, per class, the inches at
which a hem reaches a named landmark on their fit model — which means those
numbers *are* that model's own waist-to-knee, waist-to-calf and waist-to-floor
distances. Scaling them by (customer height ÷ model height) puts the same
landmarks on the customer while the garment stays the length it was cut, and
whichever band it now falls in is where it will sit. No new body ratios are
introduced: every distance used is one the chart already states.

`GARMENT_LENGTH_CHART_IN` holds the guide, per category, because the same class
name means different things across them — "Knee" is 21–23″ on a skirt and 38–40″
on a dress, and "Cropped" is a midriff-length top but an above-the-ankle trouser.
Each chart is used only within its own category and never compared across them:
the dress and skirt charts imply a shoulder-to-waist distance of 17″ at the knee
but 12″ at full length, so they aren't mutually consistent (different models),
though each is internally sound.

The catalog data came from the live store, which publishes it in two places
nobody would look. Length and fit are Shopify **tags**, mixed among colour and
collection tags — `"Calf"`, `"Cropped"` next to `"Fig"`, `"Best Sellers"`. The
model's height and size are prose in the description: *"Model: Lori is 5.6 ft and
wears a size XXS."* All 31 live products carry exactly one length tag, so the
coverage is complete rather than best-effort.
`scripts/enrich_catalog_from_source.py` reads both out of a cached copy of the
store response and writes `length`, `fit`, `model_name`, `model_height_cm` and
`model_size` into `products.json`. Note that adding fields to the catalog means
adding them in **two** other places, both of which drop unlisted fields
silently: `CatalogKB._normalize_product`, which builds an explicit dict, and
`CatalogProduct` in `main.py`, which is the shape `/catalog/sync` replaces the
catalog with. `model_height_cm` was missed in the first, so the per-product fit
model looked wired up while every garment fell back to the default reference:

```bash
python scripts/enrich_catalog_from_source.py            # from the cache
python scripts/enrich_catalog_from_source.py --fetch    # refresh the cache first
```

It never touches the network without `--fetch`. Two catalog products have since
been delisted upstream, so their length is set to `null` rather than left at the
old `"Regular"` placeholder — `"Regular"` is a real class on the tops chart, so
leaving it would look like verified data and generate confident advice from a
value nobody set. The note stays silent instead, which is the only honest output.

Silence is in fact the common case: the note only appears when the hem moves
further than the length class's own range, so a 3cm height difference says
nothing rather than manufacturing precision the chart doesn't have.

### 5. Photo-based measurement (M2 + providers)

**What it does.** Upload a full-body photo, give your height, and it estimates your bust, waist and
hips. Optionally tell it the sizes you usually wear in tops and bottoms, which improves the result
substantially. The photo is analysed on your own machine and never stored.

**How it works, and what it's actually worth.** `SizingProvider` is an abstract base with a registry
(`SIZING_PROVIDERS`) and an env var, so swapping in a commercial vendor is one class, one registry
line and one environment variable — proven end-to-end, twice, with throwaway providers. The bundled
`MediaPipeSizingProvider` runs Google's BlazePose model locally, converts landmark geometry to
measurements via `anthropometry.py` (pixel→cm scale from the shoulder-to-ankle span, breadth→
circumference via a Ramanujan ellipse), and validates the pose before trusting any of it — rejecting
rotated torsos, uneven shoulders, wide stances and cropped bodies rather than reporting distorted
numbers.

When a customer states their usual sizes, the chart becomes the anchor and the photo is blended in at
25%, **squashed inside the stated size's own band with tanh**. That last detail matters: a plain clip
at the band edge looks equivalent and passes the same tests, but it destroys the photo's contribution
for exactly the customers whose photo reads worst — several photos of one subject all clipped to an
identical value. tanh is monotonic, so distinct photos stay distinct, and it saturates asymptotically
so the band is approached but never crossed.

Every field the provider returns is clamped into the supported range before being stored, including
the optional ones. `shoulder` originally wasn't, which is how an out-of-range value reached the
database (see the invariant note under [Guardrails](#10-guardrails)).

**Measured honestly** against 8 people who were not used in any calibration (65 Wikimedia Commons
photos):

| condition | mean absolute error |
|---|---|
| chart + stated size, no photo | **3.1 cm** |
| as shipped (photo at 25%) | 4.1 cm |
| photo only | 17.3 cm |

The photo made the estimate *worse* on 16 of 19 photos, and only 29% of real photos were usable at
all (39 of 46 rejections were framing). The raw estimate varies by up to 35 cm across photos of the
same person. **All 19 recommended sizes were still correct**, because the band-holding contains the
noise. The weight is kept at 25% by explicit decision, so the on-screen claim that measurements were
estimated from your photo stays true. Treat this as a plausibility and engagement feature, not an
accuracy one.

### 6. Recommendation engine (M5 + M6)

**What it does.** Produces a ranked list of pieces suited to your shape and stated taste, and never
recommends something that isn't in stock in your size.

**How it works.** M6 is the catalog knowledge base — a structured attribute store that normalises
every product and infers silhouette, occasions and which shapes it flatters from its own attributes,
so recommendations are grounded in catalog facts rather than generated prose. M5 converts the shape
profile and preferences into a query, applies hard filters (stock, size availability, explicit
exclusions) before any scoring, then ranks what survives by shape affinity, silhouette and colour
match. Hard filters run first on purpose: a beautifully-ranked item nobody can buy is worse than no
recommendation. A `min_results` floor relaxes soft preferences rather than returning an empty page.

**Size is filtered per category**, using the same size M3 already showed the customer for that
category — skirts against her skirt size, tops against her top size. This is worth stating because it
used to send only the *tops* size and apply it to the whole catalog, which for anyone whose top and
bottom sizes differ was exactly backwards: a customer who is M on top and S below had S-only skirts
excluded as unavailable and M-only skirts recommended instead. It was invisible in production because
every product in the live catalog stocks every size, so the filter had nothing to exclude; it would
have appeared the first time something sold out.

**Colour preferences are canonicalised once, by M4**, to the catalog's own spelling. M6 filters with
an exact string comparison against `"Ebony"`, `"Sky Captain"`, so a stored `"ebony"` matches nothing —
the colour filter would then exclude the whole catalog, get relaxed away, and the customer's colour
choice would silently stop affecting anything with no error raised. M4 matches case-insensitively and
stores the catalog spelling; everything downstream uses it verbatim.

### 7. Fit checker (M7)

**What it does.** For any single garment, tells you which size to order, how confident that is, and
what to expect — "runs small in the bust" — scoring every available size rather than just naming one.

**How it works.** Each measurement is scored against the candidate size's real boundary range. Inside
the range it scores a flat 1.0 unless it sits within a cushion of an edge, where it ramps down to a
floor — so someone on the fence between two sizes sees that in the number instead of a flat 100%.
Outside the range it decays from that same floor, which is what guarantees the containing size can
never be strictly outscored. Distance is expressed in "sizes off" using a fixed cm-per-size unit
rather than as a fraction of the candidate's own reference value; the older approach divided by
whichever size was being scored, so an identical real-world miss scored better against larger sizes
purely because the denominator was bigger.

Dimensions are weighted per category, which fixed a real complaint: a skirt was advising "runs small
in the bust". Skirts and trousers score on hips, tops and vests on bust, dresses and co-ord sets on
bust with waist and hips still reported as guidance.

### 8. New releases feed (M9)

**What it does.** Shows newly launched pieces filtered to the customer's stored profile, so a launch
email isn't a catalog dump.

**How it works.** Filters the catalog by launch date within a configurable window, then scores each
item against the saved profile, keeping only those above a match threshold. Size inference uses the
same shared boundary tables as everything else, so the feed can't disagree with the profile page
about what size someone is.

### 9. History and the learning loop (M8 + M10)

**What it does.** Remembers every fit check and lets customers say whether a garment actually fitted,
building a picture of where the sizing advice is right and where it drifts.

**How it works.** M8 persists fit assessments per user, session and product. M10 aggregates that
feedback into per-user and per-product trends — systematic "runs small" signals surface as patterns
rather than one-off complaints. Feedback is stored, aggregated and exposed via `/trends/{user_id}`
and `/feedback/summary/{user_id}`; it does not silently mutate the sizing tables.

### 10. Guardrails

**What it does.** Authentication, consent enforcement, input validation and audit logging — applied
consistently rather than per-endpoint.

**How it works.** Each guardrail is a separate module under `py_src/guardrails/`:

- **`auth_manager`** — bcrypt password hashing, bearer session tokens, login-attempt throttling.
- **`access_control`** — ownership checks, so one account cannot read or modify another's session.
- **`consent_tracker`** — GDPR/BIPA-oriented consent records, with withdrawal supported. The
  photo-measurement endpoint hard-gates on `has_photo_consent()`.
- **`input_validation`** — range and type validation on every measurement.
- **`injection_defense`** — sanitisation of free-text input.
- **`image_validation`** — the upload surface. A MIME allowlist *plus* magic-byte sniffing, because
  the declared content type is attacker-controlled and never trusted alone. Handles the HEIC/MP4
  problem specifically: both are ISO-BMFF containers, so accepting iPhone photos must not wave
  through video. 10 MB cap enforced before bytes go anywhere.
- **`audit_logger`** — structured audit events. Photo scans log byte size and content type only,
  never image data.

**One invariant worth calling out**, because breaking it produced a genuinely confusing bug: the
write-side validator (`InputValidator`) and the read-side one (`utils.sizing.validate_measurements`,
used by M7 and M9) must agree. They didn't. `shoulder` was unchecked on write but required to be
30–60 cm on read, so a session could be stored happily and then be permanently unreadable by the fit
checker and the new-releases feed — which answered 400 while the recommendation engine, which
doesn't validate shoulder, carried on working. The asymmetry made it look like a bug in those two
features rather than in the data. Both validators now derive their ranges from
`constants.MEASUREMENT_RANGES`, so anything accepted on write is by construction readable afterwards,
and `tests/test_validator_agreement.py` asserts that as a general property across every field rather
than testing shoulder specifically.

### 11. Persistence

**What it does.** Keeps accounts, sessions, consent records and history across restarts.

**How it works.** SQLite via `SessionRepository` and `UserRepository`, created on first run. No
migration tooling — the schema is created idempotently at startup.

> **Note:** `backend/intake_sessions.db` is currently tracked in git and contains password hashes and
> auth tokens. It should be untracked (`git rm --cached backend/intake_sessions.db` plus a
> `.gitignore` entry) before this is deployed anywhere real.

---

## Frontend features

This section covers only how the backend capabilities above are surfaced in the UI. The storefront
design itself (layout, typography, product pages) is a separate concern and isn't documented here.

### 1. The intake flow

**What it does.** A five-step guided flow — consent, measurements, shape profile, style preferences,
done — with a progress indicator, and it survives a page reload.

**How it works.** `frontend/pages/intake-flow.js` is a single class mirroring M1's state machine.
Each screen is a `.intake-screen` div toggled by `goToStep()`; step state and answers persist to
`localStorage` and are restored on load. Photo measurement is deliberately an *alternate view of
step 2* rather than a sixth step — the progress bar still reads "Measurements", because photo
measurement is that step, done differently. After a scan the customer lands back on step 2 with the
fields pre-filled and an explanatory note, so they see and can correct the numbers before continuing;
pressing Continue re-submits whatever is in the fields, so an edit is honoured rather than
overwritten.

### 2. Photo upload

**What it does.** Upload a photo, see a preview, add your height and (optionally) your usual sizes,
and get measurements back — with a legal notice shown before any upload control is usable.

**How it works.** The privacy notice is rendered from `GET /intake/photo-disclosure` rather than
hardcoded, so it always describes what the *configured provider* actually does with the image; the
upload controls stay hidden until it loads, so a body photo is never collected under a notice that
couldn't be displayed. The Scan button unlocks only when file, valid height and an explicit
acknowledgment are all present. Upload guidance sits *above* the file picker rather than below it,
ordered by the failure reasons actually measured across 65 photographs — framing first, because that
alone accounted for 39 of 46 rejections. An `AbortController` timeout prevents a hung request leaving
the customer watching a spinner forever.

### 3. Error handling

**What it does.** Every failure produces one clear panel with two ways forward — try another photo,
or type measurements in — never a dead end, and never raw server text.

**How it works.** All failures funnel through `showPhotoError()`, which renders a fixed
customer-facing message and logs the technical reason to the console. Vendor error strings and
internal details cannot reach the page.

**One caveat worth reading.** That single-panel design initially swallowed a failure it had no
business claiming: when the session was missing, the scan aborted *before sending anything* and the
customer was told their photo wasn't framed correctly. The photo was fine. Errors that funnel into
one message must be errors of one kind, so a missing session is now caught when the photo screen
opens — before the customer picks a file — and reported honestly instead. It deliberately does not
quietly create a session and re-record consent on the customer's behalf.

### 4. Auth and conditional navigation

**What it does.** The person icon in the header goes to login when logged out, and becomes an account
menu when logged in. Profile-dependent links appear only once there's a profile to link to.

**How it works.** `js/site-chrome.js` renders the shared header and footer once for all pages;
`auth-nav-link.js` swaps the person icon between a plain link and a menu trigger based on the stored
token. `recommendations-nav-link.js` reveals **My Recommendations** only when a completed style
profile exists, and `style-profile-link.js` relabels **My Style** to **Update Style** using the same
completion signal — so the two links can never disagree about whether you have a profile.

### 5. Recommendations, new releases and fit checking

**What it does.** Recommendations and new releases render as product cards with real photography;
product pages show a size recommendation drawn from your profile.

**How it works.** All three read from the API and reuse the storefront's own `.product-card` markup,
so a recommended item looks like any other product rather than a bolted-on widget. Each card carries
one extra line explaining *why* it was picked. The fit-checker widget on the product page calls
`/fit-check/{session}/{sku}` and pre-selects the recommended size.

Both pages repair a stale session rather than reporting it as an absent profile. If the API rejects
the stored session id, they re-resolve it from `/account/profile` and retry once. This matters
because the failure is silent and misleading: an id left over from an abandoned attempt looks
perfectly valid, so every "do we have a session?" check passes, and then the profile endpoints answer
400 — leaving New Releases telling a customer with a complete profile to go and complete one, and the
fit-check widget (which fails silently by design) simply never appearing.

### 6. Colour-aware product imagery

**What it does.** Every colour a garment comes in has its own photographs, so clicking a swatch shows
the garment in that colour. And if you picked colour preferences in your style profile, you see the
garment in one of those colours *throughout* — on the recommendation and new-release thumbnails, on
the style profile's completion screen, in the collection grid, and on the product page you open from
them. The card and the page it leads to always agree.

**How it works.** Shopify associates each product photo with the colour variant it depicts: an image
tagged with variant ids opens a colour group, and untagged images following it belong to that group.
`data.js` stores the result as `imagesByColor`, 203 photographs covering 75 of the catalog's 76
colourways (one variant has no photography on the real site either, and falls back to the default
set). `productImage()` takes an optional colour, and the product page rebuilds its gallery whenever
the selection changes — sizing the thumbnail strip to however many photographs that colour actually
has, rather than a fixed count.

The swatch colours themselves are the brand's own values, read from eighth-hour.com. They are
Pantone-style marketing names ("Fudge", "Sky Captain") that can't be inferred from the words; an
earlier hand-written map covered 3 of the 17 and invented eight that don't exist, so every product
rendered its variants as the same fallback grey. `colorHex()` now warns on an unmapped name instead
of silently returning that grey.

**Choosing which colour to show.** `preferredColorFor()` intersects the customer's `preferred_colors`
with the product's colours; where several match, the product's own first matching colour wins. That is
deliberately independent of the order the preference checkboxes were ticked in — they are a set, not a
ranking — so a given product always resolves the same way. No preferences, or no overlap, falls back
to the product's first colour, exactly as it does for a visitor with no profile.

`productImage()` applies that rule **by default** when no colour is passed, which is what keeps every
thumbnail across the site consistent with the product page without each of the eight call sites
needing to know preferences exist — threading a colour through each of them by hand is exactly how
they would drift apart. The single deliberate exception is the cart, which passes the colour that was
actually added: that is a record of a decision, not a suggestion.

---

## Plugging in a photo-measurement API

The bundled MediaPipe provider is free and runs locally, but it is not accurate enough to be the
basis of a size guarantee (see the numbers in
[Photo-based measurement](#5-photo-based-measurement-m2--providers)). The system was built so a
commercial vendor can replace it without touching the intake flow, the shape profiler, the fit
checker or the UI.

**The entire swap surface is one class, one registry line, and one environment variable.** That claim
has been proven end to end twice with throwaway providers, including verifying that the on-screen
privacy notice updates itself to name the new processor.

### Step 1 — write the provider class

Create `backend/py_src/providers/your_vendor_provider.py`. Two methods and one property:

```python
import os
import requests                       # add to requirements.txt if you need it

from py_src.modules.m2_sizing_integration import Measurements, SizingProvider
from py_src.utils.errors import ModuleError


class YourVendorProvider(SizingProvider):
    """Body measurement via <vendor>."""

    def __init__(self):
        # Read your own credentials. There is no shared config module to thread
        # through -- each provider owns its own configuration.
        self.api_key = os.environ["YOUR_VENDOR_API_KEY"]

    def extract_measurements(self, photo_ref: str, height_cm: float = None) -> Measurements:
        """Required. Measure from a stored reference (URI / object ID)."""
        ...

    def extract_from_image(
        self,
        image_bytes: bytes,
        content_type: str,
        height_cm: float = None,
        usual_top_size: str = None,
        usual_bottom_size: str = None,
    ) -> Measurements:
        """
        Optional but used by the live upload endpoint. The bytes have already
        been validated (MIME allowlist, magic-byte sniff, 10 MB cap) before
        reaching you. Raise ModuleError with a customer-safe message on failure.
        """
        response = requests.post(
            "https://api.yourvendor.com/v1/measure",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"image": ("photo", image_bytes, content_type)},
            data={"height_cm": height_cm},
            timeout=30,
        )
        if not response.ok:
            raise ModuleError("We couldn't measure that photo. Please try another.", "M2")

        body = response.json()
        return Measurements(
            # CONVERT TO CENTIMETRES HERE. This codebase is cm end to end.
            bust=body["chest_cm"],
            waist=body["waist_cm"],
            hips=body["hip_cm"],
            height=height_cm,
            unit="cm",
            confidence_scores={"bust": 0.9, "waist": 0.9, "hips": 0.9},
            provider="yourvendor",
            provider_version="v1",
        )

    @property
    def disclosure(self) -> dict:
        """
        Drives the privacy notice the customer sees before uploading. It must
        describe what this provider ACTUALLY does -- the notice is rendered
        from here rather than hardcoded in the page precisely so it cannot go
        stale after a vendor swap.
        """
        return {
            "processor_name": "YourVendor, Inc. (third-party processor)",
            "sends_image_offsite": True,
            "stores_image": False,
            "derives_from_image": True,
            "retention": "Your photo is sent to YourVendor to estimate measurements "
                         "and is deleted immediately after processing. Only the "
                         "resulting measurements are saved to your account.",
        }
```

### Step 2 — register it

In `backend/py_src/modules/m2_sizing_integration.py`:

```python
SIZING_PROVIDERS = {
    "mock": MockSizingProvider,
    "mediapipe": _mediapipe_provider,
    "yourvendor": YourVendorProvider,      # <- add this line
}
```

### Step 3 — run the contract suite

This is the point of the exercise. `tests/test_sizing_provider_contract.py` encodes every assumption
the rest of the application makes about a sizing provider. Add your class to `PROVIDERS_UNDER_TEST`
at the top of that file and run:

```bash
pytest tests/test_sizing_provider_contract.py -v
```

It checks that you return a `Measurements` object with all four required fields numeric and inside
the supported ranges; that **units are centimetres** (by far the most common real-world integration
bug — many vendors return inches); that the supplied height is honoured; that provenance and
confidence scores are populated; that empty uploads are rejected; and that your `disclosure` declares
all five required keys.

Two of those tests deserve specific mention, because they enforce honesty rather than correctness:

- `test_offsite_provider_says_so_in_plain_language` — if you set `sends_image_offsite: True`, your
  retention text must actually say the image leaves the server.
- `test_analysing_provider_actually_varies_with_the_image` — if you set `derives_from_image: True`,
  feeding two different images must produce different measurements. This exists because the mock
  provider once returned identical numbers for a photo of a woman and a photo of a car while the UI
  claimed the measurements were "estimated from your photo". A provider cannot claim to analyse an
  image it ignores.

If it passes, the intake flow, shape profiler, fit checker and recommendation engine all work with it
unchanged.

### Step 4 — switch it on

```bash
YOUR_VENDOR_API_KEY=... SIZING_PROVIDER=yourvendor python -m uvicorn main:app --port 8000
```

An unrecognised `SIZING_PROVIDER` raises at startup rather than silently falling back to the mock — a
typo that quietly served fake measurements in production would be far worse than a hard failure.

### What you should also change

The photo weighting in `mediapipe_sizing_provider.py` (`PHOTO_WEIGHT_WITH_STATED_SIZE = 0.25`, with
the estimate held inside the customer's stated size band) exists because the local model is weak. A
vendor that genuinely measures well should not be damped that way — reconsider both the weight and
the band-holding rather than inheriting settings tuned for a different problem.

Two things to confirm before going live: that the image is transmitted over TLS, and that you have a
data-processing agreement with the vendor covering biometric-adjacent data. The disclosure block
makes the customer-facing statement automatic; it does not make the contract exist.

---

## Deployment

Nothing here is deployed. This section is a checklist of what must change first — every item below
was verified against the current code, not assumed.

### Blockers

**1. The API URL is hardcoded in nine places.** Every front-end file contains
`const API_BASE = 'http://localhost:8000'` (also `AUTH_API_BASE` and `PRODUCT_API_BASE`). Replace
these with a single shared value — e.g. a `js/config.js` loaded first that sets
`window.API_BASE`, or a build-time substitution:

```bash
grep -rn "localhost:8000" Base_Website/ --include=*.js     # find all of them
```

**2. CORS currently accepts any origin with credentials.** `main.py` has
`allow_origins=[..., "*"]` together with `allow_credentials=True`. Verified behaviour:

```
$ curl -i -X OPTIONS http://localhost:8000/intake/session -H "Origin: https://evil.example.com" ...
access-control-allow-origin: https://evil.example.com
access-control-allow-credentials: true
```

The API echoes back whatever origin asks. That is fine for a local-only tool, and the practical risk
today is limited because auth tokens live in `localStorage` (which a cross-origin page cannot read)
rather than in cookies — but it must be locked to the real domain before deploying, and it becomes an
outright vulnerability the moment anything moves to cookie auth:

```python
allow_origins=["https://yourdomain.com"],   # no wildcard alongside credentials
```

**3. The SQLite database is tracked in git and contains password hashes and auth tokens.**

```bash
git rm --cached backend/intake_sessions.db
echo "backend/intake_sessions.db" >> .gitignore
```

Rotate any credentials that were ever committed. This also removes a real operational hazard: a
`git checkout` of that file while the server is running wipes the live auth tables.

**4. The database path is relative.** Both repositories default to `"intake_sessions.db"`, resolved
against the process working directory — so the app silently uses a different database depending on
where it was started. Make it an absolute path or an environment variable before running under a
process manager.

### Serving it

The back end is a standard ASGI app:

```bash
pip install gunicorn
gunicorn main:app -k uvicorn.workers.UvicornWorker -w 4 -b 127.0.0.1:8000
```

Put nginx (or your platform's load balancer) in front to terminate TLS and serve `Base_Website/` as
static files. TLS is not optional here: the app transmits body measurements and, on the photo route,
a full-body photograph.

**Worker count and the pose model.** If you deploy with `SIZING_PROVIDER=mediapipe`, each worker
loads its own copy of the model (~200 MB RAM) on first use. Four workers is roughly 800 MB before any
traffic. Either size the instance accordingly, keep the worker count low, or move photo measurement
to a hosted provider — which is the better answer for other reasons anyway. Bake the model into the
image at build time rather than letting the first request download it.

### Configuration to set

| Variable | Why |
|---|---|
| `SIZING_PROVIDER` | `mock` in production means fabricated measurements. Set it deliberately. |
| `MEDIAPIPE_POSE_MODEL` | Point at a model baked into the image so there is no first-request download. |
| Vendor API keys | Whatever your provider needs; never commit them. |

### Before you take real customers' photos

The photo route handles biometric-adjacent data, and the compliance posture is only as good as the
statements attached to it:

- The wording throughout — the consent screen, the privacy notice, the FAQ retention policy — was
  written to be *accurate to what the code does*, not to be legally sufficient. **Have a lawyer review
  it.** Requirements differ by jurisdiction (Illinois BIPA, Texas CUBI, GDPR Art. 9, CCPA/CPRA).
- BIPA specifically requires a publicly available written retention and destruction policy. There is
  one in the FAQ; confirm it says what you actually do once a vendor is involved.
- There is a known unresolved issue: step 1 requires photo consent *and* measurement consent together
  to proceed. Someone who only wants to type their measurements is still made to consent to photo
  processing. That is bundled consent, which is the pattern GDPR's "freely given" requirement targets.
  Unbundling it means changing a backend guardrail and its test — a deliberate decision, flagged here
  rather than quietly fixed.
- There is currently no "delete my measurements" control in the UI. `ConsentTracker.withdraw_consent()`
  exists in the backend but nothing calls it. Since photos are never retained, the only stored
  derivative is the measurements themselves — but a withdrawal path should exist before launch.

---

## Testing

```bash
cd backend
source venv/bin/activate
python -m pytest tests/ -q                    # all 1,062
python -m pytest tests/test_m7_fit_checker.py -q
```

Four tests skip by default: they need the real MediaPipe model, which deadlocks inside pytest (it
works standalone). They're covered instead by a script you can run directly:

```bash
python scripts/verify_pose_provider.py                        # rejection checks
python scripts/verify_pose_provider.py photo.jpg 172          # measure a real photo
python scripts/verify_pose_provider.py --diagnose photo.jpg 172   # landmark-level diagnostics
```

Notable suites: `test_validator_agreement.py` (the write-side and read-side measurement validators
must agree — see the invariant note under [Guardrails](#10-guardrails)),
`test_size_chart_integrity.py` (structural invariants of the size chart),
`test_size_guide_page.py` (the published Size Guide page must still match the chart the engine sizes
on — a cross-boundary check nothing else would catch),
`test_stored_profile_migration.py` (the saved-profile migration agrees with M3 and touches nothing
else),
`test_per_category_size_filter.py` (recommendations are filtered by the size the customer wears in
*that* category, and colour preferences survive any casing),
`test_sizing_provider_contract.py` (a reusable suite any new sizing vendor must pass, including
declaring how it handles images), `test_image_validation.py` (the upload surface, including the
HEIC-vs-MP4 container case), and `test_mediapipe_provider.py` (pose validation and the stated-size
round-trip, driven by synthetic landmarks so it needs no model or photograph).

---

## Project layout

```
backend/
  main.py                     FastAPI app; all HTTP endpoints
  products.json               Catalog, loaded at startup
  catalog_source.json         Cached copy of the live store's products.json.
                              Source for garment length, fit and fit-model
                              height -- refreshed only on demand, never per run.
  run.sh                      Start the API (defaults to real photo analysis)
  py_src/
    constants.py              Size chart, boundary tables, garment length
                              chart, tunables
    modules/                  M1-M10
    guardrails/               auth, consent, validation, audit, image checks
    providers/                sizing providers + anthropometry math
    persistence/              SQLite repositories
    utils/                    shared sizing, math, errors, logging
  scripts/
    check_running_server.py   Is the API running this working copy?
    render_size_guide.py      Rewrite the Size Guide page from the size chart
    enrich_catalog_from_source.py  Pull length/fit/model data out of the cache
    migrate_stored_size_profiles.py  Recompute saved sizes after a chart change
    verify_pose_provider.py   Exercise the pose model outside pytest
  tests/                      1,062 tests
Base_Website/
  serve.py                    no-cache dev server
  diagnose.html               session troubleshooting page
  index.html, collection.html, product.html, size-guide.html, about.html, ...
  js/                         storefront + shared chrome
    data.js                   catalog, per-colour images, brand colour values
    site-chrome.js            shared header/footer + session reconciliation
    placeholder.js            colour-aware image resolution
  frontend/pages/             intake flow, recommendations, new releases, account, auth
  images/products/            203 photographs, keyed by product and colourway
  images/brand/               logo, hero and banner assets
planning_documents/           design notes
```
