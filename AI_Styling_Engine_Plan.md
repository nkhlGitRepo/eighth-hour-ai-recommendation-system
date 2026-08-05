# Eighth Hour — AI Styling & Recommendation Engine

**Planning document · v1.3**

*v1.3 revisions: closed a spec gap — the brief calls for recommendations built around garments **and accessories**; the plan now treats accessories as first-class catalog items in M6, has the M5 outfit-builder complete looks with accessories, and clarifies "garment" as shorthand for any product type.*
*v1.2 revisions: added §8 "Legal Messages & Required Disclosures" (AI transparency, biometric/sizing consent, third-party sharing, privacy/data rights, marketing, minors, e-commerce disclosures, governance), grounded in 2025–2026 law; renumbered the summary to §9.*
*v1.1 revisions: added query-injection defense (parameterized KB retrieval), access-control / ownership enforcement, and standard web-layer protections; simplified M8 (removed undefined ranking model); clarified M7's matching mechanism to avoid per-customer LLM runs at launch; aligned M1's description with its state-machine design.*

A modular architecture plan for an AI-guided styling and recommendation engine layered onto the existing Eighth Hour e-commerce site. This document is written to be read section by section — each module is independently understandable, testable, and debuggable.

---

## 1. Purpose & Scope

### 1.1 What we're building

After a customer registers, an AI-guided flow walks her through a short series of screens that produce **personalized style recommendations** built specifically around Eighth Hour garments and accessories. The same underlying engine also powers a personalized **"New Releases"** feed that surfaces newly launched styles matched to each customer's shape and style profile.

> **Catalog note:** "garment" is used throughout as shorthand for any recommendable Eighth Hour product. The brief calls for recommendations built around garments **and accessories**; the engine treats accessories as first-class catalog items (see M6), so wherever this document says "garment" it means any product type — garments today, accessories as the catalog adds them.

The customer journey, at a glance:

```
Register → Guided intake (photos + preferences)
        → Third-party sizing → body measurements
        → Body shape profile
        → Curated styling recommendations (RAG over EH catalog)
        → Ongoing: personalized New Releases feed
```

### 1.2 Explicit design constraints (from the brief)

- **Integrate, don't rebuild.** Sizing and core vision/measurement capability come from **third-party providers**, not in-house models. Our job is orchestration, mapping, retrieval, and guardrails — not training a body-measurement model.
- **Layered, not foundational.** This ships *after* the core e-commerce and marketing launch. It must attach to the existing site without requiring a rebuild of checkout, catalog, or auth.
- **Modular & debuggable.** Every stage is a separate module with a clear input/output contract so failures are isolatable.
- **Security-first.** Body photos and measurements are highly sensitive personal data. Guardrails and privacy controls are treated as first-class modules, not afterthoughts.

### 1.3 Out of scope (v1)

- Building a proprietary body-measurement or pose-estimation model.
- Virtual try-on / garment simulation rendering (candidate for a later phase).
- In-house training of a foundation vision model.
- Physical tailoring workflow integration (the existing custom-sizing email flow remains as-is for now).

---

## 2. Architecture Overview

The engine is decomposed into **nine modules** plus a **cross-cutting guardrail layer**. Data flows left to right; the guardrail layer wraps every module.

```
┌─────────────────────────────────────────────────────────────────────┐
│                       GUARDRAIL & SECURITY LAYER                       │
│  input validation · consent · PII handling · access control (owns-own)│
│  injection defense (prompt + query) · output filtering · audit        │
└─────────────────────────────────────────────────────────────────────┘
      │            │            │            │            │
   [M1]         [M2]         [M3]         [M4]         [M5]
 Onboarding → Sizing      → Body Shape → Style       → Recommendation
 & Intake     Integration   Profiling    Preference    Engine (RAG +
                                          Capture       Agentic)
                                                            │
                                          ┌─────────────────┼───────────────┐
                                        [M6]              [M7]            [M8]
                                     Catalog            New Releases    Feedback &
                                     Knowledge Base     Feed            Learning Loop
                                     (Vector store)     (event-driven)
                                                            │
                                                          [M9]
                                                     Serving / API layer
                                                     (site integration)
```

Each module below is documented with: **Responsibility · Inputs · Outputs · Key decisions · Debug/observability · Failure handling.**

---

## 3. Module Specifications

### M1 — Onboarding & Intake Orchestration

**Responsibility.** Own the guided, multi-screen flow shown after registration. It orchestrates intake — deciding which screen comes next, handling skips/retries, and assembling a complete intake package before handing off downstream. (This is deliberately a *state machine with adaptive routing*, not a full LLM agent; the term "agentic" in the strong sense is reserved for M5.)

**Inputs**
- Authenticated user session (from existing site auth).
- Screen-by-screen responses: consent, uploaded photo(s), self-reported preferences, optional manual measurements.

**Outputs**
- A validated `IntakeSession` object: `{ user_id, consent_record, photo_refs[], preferences{}, manual_overrides{}, status }`.

**Key decisions**
- Implemented as a **state machine** (screens = states, user actions = transitions). This keeps the flow readable and each transition unit-testable in isolation.
- The orchestrator adapts the path (e.g., if the photo fails quality checks, it routes to a re-capture screen or offers a manual-measurement fallback) rather than following a rigid linear script — but this is deterministic routing, not open-ended LLM planning.
- **No photo leaves the device or secure upload endpoint without an explicit, logged consent transition.**

**Debug/observability**
- Every state transition emits a structured event (`session_id`, `from_state`, `to_state`, `reason`). A failed session can be replayed from its event log.

**Failure handling**
- Any downstream module failure returns the user to a graceful "we'll finish this later" state; a partial `IntakeSession` is persisted so she can resume.

---

### M2 — Sizing Integration (Third-Party)

**Responsibility.** Wrap the third-party sizing/measurement provider behind a stable internal interface. Turn a customer photo into structured body measurements.

**Inputs**
- `photo_ref` (a pointer to the securely stored image, never the raw bytes passed around casually).
- Optional metadata the provider needs (height, declared units).

**Outputs**
- A normalized `Measurements` object: `{ bust, waist, hips, inseam, shoulder, height, unit, confidence_scores{}, provider, provider_version }`.

**Key decisions**
- **Adapter pattern.** The provider is accessed only through an internal `SizingProvider` interface with one implementation per vendor. Swapping or A/B-testing vendors touches only the adapter, never downstream modules.
- **Normalization boundary.** Every vendor returns a different schema; M2 is the *only* place that knows vendor-specific formats. Everything downstream sees our normalized schema.
- **Confidence-aware.** We store per-measurement confidence. Low-confidence measurements trigger a manual-confirmation screen (M1) rather than silently propagating bad data.
- **Data minimization at the boundary.** Send the provider only what their contract requires; prefer providers that support on-device or ephemeral processing and that contractually commit to not retaining images.

**Debug/observability**
- Log request/response *metadata* (latency, status, confidence, provider version) — **never** the image or raw biometric payload in application logs.
- A "golden set" of test inputs with known expected measurement ranges runs against each provider version to catch regressions.

**Failure handling**
- Timeout / provider error → retry policy with backoff, then fall back to **manual measurement entry** so the customer is never hard-blocked.
- Confidence below threshold → route to confirmation, don't fail.

---

### M3 — Body Shape Profiling

**Responsibility.** Translate raw measurements into an interpretable **body shape profile** — the abstraction the recommendation logic actually reasons over.

**Inputs**
- `Measurements` object from M2 (or manual entry).

**Outputs**
- A `BodyShapeProfile`: `{ shape_class, ratios{ bust_waist, waist_hip, shoulder_hip }, size_recommendation_by_category{}, fit_notes[], profile_version }`.

**Key decisions**
- **Deterministic and rules-based first.** Shape classification (e.g., balanced, hip-dominant, shoulder-dominant, straight, curvy) is computed from measurement *ratios* using documented, versioned rules — not an opaque model. This is auditable, explainable to the customer, and trivially debuggable.
- The profile maps to **Eighth Hour's own size chart** (XXS–XXL) per category, since fit differs across tops, skirts, trousers, etc.
- `profile_version` is stamped so we can re-evaluate historical recommendations when the ruleset evolves.

**Debug/observability**
- Given a `Measurements` object, the output is fully reproducible. A single function with a truth table of test cases covers the classifier.

**Failure handling**
- Ambiguous ratios (near a boundary) produce a *blended* profile with multiple candidate shapes rather than forcing one, and downstream retrieval handles the ambiguity gracefully.

---

### M4 — Style Preference Capture

**Responsibility.** Capture the *taste* dimension that measurements can't: color preferences, silhouettes she likes, occasions she dresses for, coverage preferences, and lifestyle context (the "boardroom to airport to dinner" persona).

**Inputs**
- Preference screens from M1 (structured multiple-choice + optional free text).
- Implicit signals over time (browsing, wishlist, purchases) — added in the learning loop (M8).

**Outputs**
- A `StyleProfile`: `{ preferred_colors[], preferred_silhouettes[], occasions[], coverage_prefs{}, disliked_attributes[], free_text_notes, profile_version }`.

**Key decisions**
- Keep the explicit intake **short** (the brief emphasizes "a short series of screens"). Depth comes over time from behavior, not an exhausting quiz.
- Free-text notes are passed through the guardrail layer before being embedded or sent to any LLM (prompt-injection defense — see §4).

**Debug/observability**
- Profiles are versioned and diff-able so we can see exactly how a customer's stated taste changed over time.

---

### M5 — Recommendation Engine (RAG + Agentic Workflow)

**Responsibility.** The core. Combine the `BodyShapeProfile` and `StyleProfile` into a ranked, *explained* set of Eighth Hour product recommendations — garments and accessories — including how to style them together into complete looks.

This module is where **RAG** and an **agentic workflow** are genuinely warranted, so it's worth being precise about why.

#### 5.1 Why RAG here

The recommendation must be grounded in the **actual, current Eighth Hour catalog** — real garments, real fabrics, real available sizes and colors. We do **not** want a language model inventing garments that don't exist or recommending sold-out pieces. RAG solves exactly this: retrieve real catalog items relevant to the profile, then let the LLM reason *only over retrieved, grounded facts*.

```
BodyShapeProfile + StyleProfile
        │
        ▼
  Build a structured query  ──►  Retrieve top-K garments from the
  (shape + taste + rules)         Catalog Knowledge Base (M6 vector store)
        │                                     │
        │        ┌────────────────────────────┘
        ▼        ▼
  LLM reasons over ONLY the retrieved, in-stock, on-brand items
        │
        ▼
  Ranked outfits + human-readable styling rationale
```

#### 5.2 Why an agentic workflow here

A good stylist doesn't answer in one shot — she reasons in steps: *understand the client → shortlist pieces → build coordinated outfits → sanity-check fit and availability → explain choices.* We mirror that with a small, bounded set of cooperating agents/steps, each with a single job. This makes the pipeline debuggable (you can inspect the output of each step) and safer (each step has a narrow mandate).

**The agentic pipeline (bounded — no open-ended autonomy):**

1. **Stylist agent** — reads the profiles and decides *what kinds* of pieces to look for. It emits a **structured set of parameters** (categories, colors, silhouette hints, size) that are passed to M6's parameterized query methods — it never writes a raw query string, so it cannot alter query structure (see §4.4).
2. **Retrieval step** — returns candidate garments (grounded, in-stock, size-available).
3. **Outfit-builder agent** — assembles retrieved pieces into coordinated looks (e.g., pairs a recommended vest with compatible trousers, then finishes the look with a complementary accessory), respecting fabric/color harmony rules.
4. **Fit-checker step** — a deterministic validator that confirms every recommended item actually exists, is in the customer's recommended size range, and is currently purchasable. **This step is not an LLM** — it's hard code, so it can't be "talked out of" a correctness rule.
5. **Rationale agent** — produces the customer-facing explanation ("recommended because…"), constrained to reference only the validated items.

**Guardrails on the agentic layer (critical):**
- Agents operate within a **fixed, finite step budget** — no unbounded loops, no self-directed tool discovery.
- Agents can call **only an allow-listed set of internal tools** (retrieve-from-catalog, check-inventory, check-size-availability). They cannot browse the web, execute code, call external APIs, or take any write/side-effecting action.
- Every inter-agent handoff passes through validation; a malformed or out-of-contract message aborts the run rather than propagating.
- The **fit-checker (step 4) is authoritative**: if it rejects an item, no downstream agent can reintroduce it.

**Inputs**
- `BodyShapeProfile`, `StyleProfile`, and a live handle to M6 + inventory.

**Outputs**
- A `RecommendationSet`: `{ outfits[], per_item_rationale[], confidence, generated_at, catalog_version }`, where every item is a real, validated catalog SKU.

**Debug/observability**
- Each agent/step logs its input and output as a discrete artifact. A single recommendation run can be opened up and inspected stage by stage ("the stylist asked for X, retrieval returned Y, the fit-checker removed Z because sold out").
- Deterministic steps (retrieval query construction, fit-check) have unit tests; the LLM steps have **evaluation sets** with rubric-based scoring.

**Failure handling**
- If retrieval returns too few grounded items, the engine degrades to a **rules-based recommendation** (shape → category mapping) rather than letting the LLM improvise.
- If the LLM output fails validation against retrieved items, the run is rejected and retried once, then falls back to rules-based.

---

### M6 — Catalog Knowledge Base (Vector Store + Structured Index)

**Responsibility.** Be the single grounded source of truth the recommendation engine retrieves from. Hybrid store: **structured attributes** (product type, category, fabric, color, size availability, price) + **vector embeddings** (product descriptions, styling notes, silhouette language) for semantic retrieval. It holds **all recommendable product types as first-class items — garments *and* accessories** — so the engine can complete a look, not just suggest a single piece.

**Inputs**
- The live Eighth Hour catalog (garments and accessories; the same product data modeled on the site), plus curated styling metadata (e.g., "pairs well with," "flatters shoulder-dominant shapes," "completes this look").

**Outputs**
- Retrieval responses: ranked products (garments and/or accessories) matching a structured + semantic query.

**Key decisions**
- A `product_type` attribute (garment vs. accessory, plus sub-type) is a first-class filter, so the outfit-builder can deliberately pull an accessory to finish a look. Accessories carry their own relevant attributes (e.g., a scarf has no dress size), and the shape-based size logic in M3 simply doesn't apply to size-agnostic accessories — the fit-checker treats them accordingly.
- **Hybrid retrieval**: hard filters (in stock, size available where applicable, category/type) applied *before or alongside* semantic similarity, so the LLM never even sees ineligible items.
- **Parameterized queries only.** Retrieval is exposed as a fixed set of typed query methods (e.g., `retrieve(shape_class, product_types[], categories[], color_prefs[], size, k)`) that bind values as parameters. Filter values are never concatenated into a raw query string — the same principle as parameterized SQL, applied to whichever store backs the KB. This closes the injection surface where an agent- or user-derived value could otherwise alter query structure (see §4.4).
- **Freshness by design.** The KB is rebuilt/updated whenever the catalog changes (new release, price change, sell-out). Stale grounding is a correctness bug, so catalog sync is a monitored pipeline (ties into M7).
- Styling metadata is **human-curated** by the brand team — this is where Eighth Hour's actual point of view lives, and it keeps recommendations on-brand rather than generic.

**Debug/observability**
- Every retrievable item carries a `catalog_version` and `last_synced` timestamp. A "grounding check" job periodically confirms the KB matches the live catalog.

**Failure handling**
- If the KB is stale beyond a threshold, recommendations are served with a "refreshing" flag and the New Releases feed pauses new-item injection until sync completes.

---

### M7 — Personalized New Releases Feed

**Responsibility.** Reuse the same engine to surface **newly launched styles** matched to each customer's stored shape + style profile, as they launch.

**Inputs**
- New-product launch events (from the catalog/PIM).
- Stored `BodyShapeProfile` + `StyleProfile` per customer.

**Outputs**
- A per-customer ranked feed of new arrivals with match rationale.

**Key decisions**
- **Event-driven, not on-demand recompute.** When a new garment launches: (1) it's added to M6, (2) a matching job scores it against existing customer profiles, (3) high-match customers get it surfaced in their New Releases section (and optionally a notification, subject to marketing-consent).
- **Reuses M6's retrieval + M5's deterministic fit-check — not the full LLM agentic flow.** Matching a single new garment to customers is a scoring problem: compute the new item's compatibility against each stored profile using the same structured/semantic attributes and the same authoritative fit-check (size available, in stock). Running M5's multi-step LLM stylist pipeline per customer for every launch would be needlessly expensive and is explicitly *not* what happens here. The optional per-customer styling rationale (why it matched) is generated lazily — only when the customer actually opens the item — so the launch-time job stays cheap.
- Respects a **separate, explicit marketing/notification consent** distinct from the styling consent.

**Debug/observability**
- Each surfaced item records *why* it matched (which profile attributes), so the feed is explainable and tunable.

**Failure handling**
- Matching job failures degrade to a non-personalized "New Arrivals" list (already a standard e-commerce feature), so the customer always sees *something*.

---

### M8 — Feedback & Learning Loop

**Responsibility.** Improve profiles and rankings over time from real behavior — without ever silently degrading privacy or introducing bias.

**Inputs**
- Explicit feedback ("love it / not for me / saved / wrong fit").
- Implicit signals (views, wishlist, purchases, returns — especially fit-related returns).

**Outputs**
- Updated `StyleProfile` weights (which stated preferences to emphasize in retrieval); flagged fit-mismatch cases for M3 rule review.

**Key decisions**
- **Scope is deliberately narrow in v1.** This module adjusts the *inputs* the recommendation engine already consumes (profile preference weights) and surfaces review candidates for humans — it does **not** introduce a separate ranking model or any automated retraining. This keeps M5 the single place ranking happens and avoids adding an undefined component.
- Learning is **incremental and reversible** — profiles are versioned so a bad update can be rolled back.
- **Fit-related returns are gold**: a return flagged "too tight in the shoulders" feeds directly back into M3's shape-to-size mapping review (a human-reviewed rule change, not an automatic one).

**Debug/observability**
- Every profile change is attributable to a specific signal, so drift is traceable.

---

### M9 — Serving / Site Integration Layer

**Responsibility.** Expose the engine to the existing website cleanly, so it "layers on" without disturbing core commerce.

**Inputs**
- Requests from the site frontend (start intake, get recommendations, get New Releases feed).

**Outputs**
- JSON responses consumed by new frontend screens (the guided flow) and by the personalized sections on existing pages.

**Key decisions**
- **Thin, versioned API** in front of the modules; the site never calls modules directly.
- **Async where needed.** Photo → measurement → profile can take seconds; the flow is designed to handle async processing with a "your recommendations are being prepared" state rather than blocking.
- **Graceful absence.** If the engine is unavailable, the site falls back to its normal, non-personalized experience — the AI layer is strictly additive.

---

## 4. Guardrail & Security Layer (Cross-Cutting)

Because the engine handles **body photos and biometric-adjacent measurements**, security and privacy are not a single module — they wrap everything. This section is intentionally detailed.

### 4.1 Data classification & minimization

| Data | Classification | Handling rule |
|---|---|---|
| Body photo | **Highly sensitive / biometric-adjacent** | Encrypted in transit and at rest; shortest viable retention; never in logs; deleted after measurements are derived (or per explicit retention consent). |
| Measurements | **Sensitive PII** | Encrypted at rest; access-controlled; not shared with third parties beyond the sizing provider contractually bound to protect it. |
| Body shape profile | **Sensitive (derived)** | Stored with the account; customer can view and delete. |
| Style profile | Personal preference | Standard PII handling. |
| Recommendations / feed | Derived, low sensitivity | Standard handling. |

**Principle:** collect the minimum, keep it the shortest time, expose it to the fewest systems.

### 4.2 Consent & customer control

- **Explicit, granular, logged consent** before any photo capture or third-party processing — separate from general account terms.
- **Separate consent** for (a) measurement processing, (b) image retention, (c) marketing/notifications on New Releases. Declining one doesn't force declining others.
- **Full data rights**: the customer can view her measurements, shape profile, and style profile, and can **delete** them, which cascades to the New Releases matching.
- Clear disclosure of *which* third-party providers process her data and for what.

### 4.3 Third-party provider security

- Access the sizing provider only through the M2 adapter with **scoped, rotating credentials** stored in a secrets manager (never in code or client).
- Contractually require: no image retention beyond processing, no use of customer data for the vendor's own model training, and breach notification obligations.
- Prefer providers offering on-device or ephemeral processing.
- Pin and monitor provider versions; validate their outputs against the golden set (M2) before trusting them.

### 4.4 Input guardrails (defense against abuse & injection)

- **Image validation** before it ever reaches the provider: file type, size, that it's plausibly a photo, malware scan. Reject anything anomalous.
- **Free-text sanitization**: any customer free-text (style notes) that will touch an LLM or embedding step is treated as **untrusted input**. It is never allowed to act as instructions to the model. The recommendation agents are built so that retrieved catalog data and user text are clearly delimited as *data*, not *commands* — the standard defense against prompt injection.
- **Query injection defense.** All retrieval against the Catalog KB (M6) goes through parameterized, typed query methods — filter values are bound as parameters, never concatenated into query strings. This is the SQL-injection defense generalized to whichever store backs the KB (vector DB / document store), and it means neither a user-supplied value nor an agent-generated parameter can change query structure.
- **Standard web-layer protections** on the serving API (M9): parameterized/ORM-bound database access everywhere, output encoding to prevent stored/reflected XSS in any rendered rationale text, strict request schema validation, and CSRF protection on state-changing endpoints. These are inherited from the existing site's stack where possible rather than reinvented.
- **Rate limiting** on intake and recommendation endpoints to prevent scraping/abuse.

### 4.5 Access control & tenancy isolation

- **Ownership enforcement.** Every profile, measurement, recommendation, and feed is scoped to a single `user_id`. Every read/write checks that the authenticated session owns the requested resource — a customer can never retrieve another customer's data by guessing an ID (IDOR / broken-object-level-authorization defense). This check lives in M9 and is applied uniformly, not per-endpoint.
- **Least privilege.** Internal services get only the data access they need: the recommendation engine reads the catalog KB and the requesting customer's profile, nothing more. No module has blanket access to all customer records.
- **Sensitive-data access is logged** (who/what accessed measurements or photos, when) for audit.

### 4.6 Agentic-workflow guardrails (from §5.2, consolidated)

- Fixed, finite step budget — no unbounded loops or open-ended planning.
- Strict **tool allow-list** (retrieve-catalog, check-inventory, check-size) — no web access, no code execution, no external calls, no write actions.
- Deterministic **fit-checker is authoritative** and cannot be overridden by any LLM step.
- Every handoff validated against a schema; malformed messages abort the run.
- No agent can perform a side-effecting or purchasing action on the customer's behalf.

### 4.7 Output guardrails

- **Grounding enforcement**: every recommended item must exist in M6 and pass the fit-check. Non-grounded output is discarded, never shown.
- **Brand-safety filter**: rationale text is checked to stay on-brand, factual, and free of inappropriate content, body-shaming language, or health/medical claims. The engine describes *fit and style*, never makes judgments about the customer's body.
- **No overreach**: the engine never diagnoses, never comments on weight/health, and frames everything as styling suggestion, not prescription.

### 4.8 Auditability & monitoring

- Structured, PII-safe audit log for every stage (metadata only — never images or raw biometrics).
- Anomaly alerts (spikes in provider errors, low-confidence rates, validation-rejection rates).
- Reproducible runs: any recommendation can be traced from intake to output for debugging and for responding to customer questions.

### 4.9 Bias & fairness

- The engine must work across the **full XXS–XXL range and diverse body shapes**. Recommendation quality is monitored across shape classes so no group receives systematically worse results.
- Fit-related returns are monitored by shape class to catch mapping bias in M3.

---

## 5. Data Contracts (Summary)

The clean boundaries between modules are enforced by these object contracts. Each is versioned.

```
IntakeSession      { user_id, consent_record, photo_refs[], preferences, manual_overrides, status }
Measurements       { bust, waist, hips, inseam, shoulder, height, unit, confidence_scores, provider, provider_version }
BodyShapeProfile   { shape_class, ratios, size_recommendation_by_category, fit_notes[], profile_version }
StyleProfile       { preferred_colors[], preferred_silhouettes[], occasions[], coverage_prefs, disliked_attributes[], free_text_notes, profile_version }
RecommendationSet  { outfits[], per_item_rationale[], confidence, generated_at, catalog_version }
NewReleaseMatch    { user_id, sku, match_score, matched_attributes[], surfaced_at }
```

Because every module speaks only in these contracts, any module can be developed, tested, mocked, or replaced independently — which is the core of the "easy to understand and debug" requirement.

---

## 6. Phased Delivery Plan

The brief is explicit that this is layered on **after** the core e-commerce and marketing launch. Suggested sequencing:

**Phase 0 — Foundations (parallel-safe with launch)**
- Build M6 (Catalog KB) from existing product data — low risk, no customer data involved.
- Draft data contracts (§5) and the guardrail policies (§4).
- Select and contract the third-party sizing provider; complete security/privacy review.

**Phase 1 — Intake & profiling (no recommendations yet)**
- M1 (intake orchestration) + M2 (sizing adapter) + M3 (shape profiling) + M4 (preferences).
- Full consent/privacy layer (§4.1–4.3) live before any photo is captured.
- Deliverable: a customer can complete the flow and see her measurements + shape profile. Builds trust before recommendations exist.

**Phase 2 — Recommendations (RAG + agentic)**
- M5 recommendation engine + agentic guardrails (§4.6) + output guardrails (§4.7).
- Deliverable: personalized styling recommendations grounded in the real catalog.

**Phase 3 — New Releases feed**
- M7 event-driven matching, reusing M5/M6.
- Deliverable: personalized New Releases section.

**Phase 4 — Learning loop & optimization**
- M8 feedback loop; ranking refinement; bias monitoring dashboards.

Each phase is shippable and useful on its own, and each adds one clearly-bounded capability.

---

## 7. Open Questions / Decisions to Confirm

1. **Sizing provider choice** — which vendor(s), and do they support ephemeral/on-device processing and no-retention contracts?
2. **Photo retention** — default to delete-after-measurement, or offer opt-in retention for re-profiling convenience?
3. **LLM hosting** — provider-hosted vs. self-hosted for the M5 reasoning steps, factoring in that customer profile data is the sensitive input (measurements themselves need not be sent to the LLM — only the derived, less-identifying profile).
4. **Human-in-the-loop** — should a brand stylist review/curate a sample of AI recommendations initially to validate on-brand quality before full automation?
5. **New Releases notification channel** — in-site only, or email/push (each needs its own consent)?

---

## 8. Legal Messages & Required Disclosures

> **Important:** This section is an engineering/product planning reference, not legal advice. Data-protection and AI law is changing quickly and varies by jurisdiction; several items below reference laws that took effect or changed in 2025–2026. Eighth Hour must have this reviewed by qualified privacy/AI counsel before launch, and should re-check currency at implementation time. Because the brand ships worldwide, the safe default is to design to the **strictest applicable standard** and apply it broadly.

This section catalogs the legal notices, disclosures, and consent messages the engine must surface. It is organized by *where in the flow* each one appears, so it maps cleanly onto the modules in §3. Each item lists **what to say · when/where · why (legal driver)**.

### 8.1 Why this system attracts heightened obligations

Three properties of the engine raise its legal profile above an ordinary shop:

1. **It captures a body photo and derives body measurements.** Whether this counts as regulated "biometric" data is nuanced. Under GDPR, biometric data is a *special category* only when processed *for the purpose of uniquely identifying a person*; measurements used purely for garment sizing may fall outside that, but the photo and the purpose test still demand care, and a Data Protection Impact Assessment is expected for this kind of large-scale sensitive processing. Under US state law it's more variable: most comprehensive state privacy laws tie "biometric" to unique identification, but **Connecticut treats biometric data as sensitive regardless of identification purpose**, and Illinois's BIPA is uniquely aggressive (private right of action, statutory damages per violation). The safe posture is to **treat photos and measurements as sensitive personal data everywhere.**
2. **It's an AI system that interacts with the customer and profiles her.** This triggers AI-transparency and automated-profiling disclosure rules.
3. **It shares data with third-party providers** (the sizing/AI vendors). That sharing must be disclosed, and consent for it kept separate from consent for core functionality.

### 8.2 AI transparency disclosures (the guided flow — M1/M9)

- **"You're interacting with AI."** The guided styling flow must clearly tell the customer she is interacting with an AI system, at the first point of interaction — not buried in terms. This reflects the **EU AI Act Article 50** transparency obligations (in effect **August 2, 2026**), which require interactive AI systems to disclose their non-human nature clearly and where it isn't already obvious. Place it visibly at the start of the flow.
- **How the recommendations are produced.** A plain-language explanation that recommendations are generated by an automated system based on her photo-derived measurements and stated preferences, with a high-level sense of the logic. This supports both the AI Act and US state **automated decision-making / profiling** transparency expectations (e.g., California CCPA/CPRA profiling rules and the CPPA's ADMT regulations; Colorado's revised ADMT framework). *Note:* a styling/product recommendation is generally **not** a "consequential/significant decision" (like credit, housing, employment) that triggers the heaviest opt-out-and-appeal machinery — but transparency and a profiling opt-out are still the prudent baseline.
- **Right not to be profiled / opt-out.** Offer a way to decline the AI styling and still use the normal site. Under several US state laws consumers can opt out of profiling; making the whole feature optional satisfies this cleanly and matches the "strictly additive" design in M9.
- **AI can be wrong.** A brief accuracy/limitations note: measurements and recommendations are estimates, not guarantees of fit — steering the customer to the size guide and custom-sizing option. This manages expectations and supports FTC "unfair/deceptive practices" avoidance.

### 8.3 Biometric / sizing consent (before photo capture — M1 → M2)

This is the single most important consent gate. It must be **explicit, specific, informed, unbundled, and logged** — a dedicated screen, not a pre-checked box or a line in the general terms (courts have repeatedly found bundled ToS consent insufficient for biometric data).

The consent screen must state, before any photo is taken or sent:

- **What is collected** — a photo, from which body measurements are derived.
- **The specific purpose** — to estimate measurements, build a body-shape profile, and generate styling recommendations. No use beyond that without fresh consent.
- **Who processes it** — that the photo is sent to a named third-party sizing/measurement provider, and that provider's role. (Disclosing the specific provider supports GDPR transparency and US "sharing" disclosure.)
- **Retention & deletion** — how long the photo and measurements are kept, and that the photo is deleted after measurements are derived (the recommended default), or the terms if the customer opts into retention. "As long as necessary" is not an adequate statement of a retention period — give a concrete period or criteria.
- **How to withdraw consent and delete the data** — and that withdrawal is as easy as giving consent.
- **A clear affirmative action** — an explicit "I consent" action, separate from account creation.

Legal drivers: **GDPR Art. 9 explicit consent + Art. 6 lawful basis (two cumulative layers) and Art. 13 information-at-collection**; **Illinois BIPA / Texas CUBI / Washington** biometric statutes (written notice, purpose, retention schedule, consent before collection); **Connecticut and other state** sensitive-data opt-in consent.

### 8.4 Third-party data-sharing disclosure (M2, and any analytics)

- **Named sub-processors / providers.** Disclose the sizing/AI vendors and any other processors, and keep this list current. Under GDPR these are processors/sub-processors bound by data-processing agreements; under US state laws this is "sharing" that must be disclosed.
- **Separate, unbundled consent for non-essential sharing.** Consent to share the photo with the *sizing provider* (essential to the feature she asked for) is distinct from any consent to share data for *advertising or analytics* (non-essential). These must not be bundled. If ad/marketing pixels transmit browsing behavior, that is "sale or sharing" under CCPA and needs its own opt-out.
- **International transfer notice.** If a provider processes data outside the customer's region (e.g., an EU customer's data processed in the US), disclose the transfer and the safeguard mechanism (GDPR Art. 13 transfer disclosure).

### 8.5 Standard privacy & data-rights disclosures (site-wide, reinforced in-flow)

The engine inherits and extends the site's existing privacy obligations:

- **Privacy Policy** covering the engine's data: categories collected (photo, measurements, shape/style profile, behavioral signals), purposes, retention, sharing, and rights. Must be easy to find and understand, not buried.
- **Data-subject / consumer rights**: access, correction, deletion, portability (GDPR), and the US-state analogues — plus the practical mechanisms to exercise them. Deletion must reach **derived data and embeddings**, not just the source photo: if a vector/embedding derived from the customer persists in the knowledge store or backups, deleting the photo alone is not sufficient.
- **"Do Not Sell or Share My Personal Information"** and **Global Privacy Control (GPC)** browser-signal honoring, where applicable (CCPA/CPRA; GPC now mandatory in a growing number of US states).
- **Sensitive-data handling notice**: the profile/measurement data is sensitive PII; some states give a right to limit its use.
- **Cookie/tracking consent** consistent with the rest of the site (out of scope to redesign here, but the styling flow must not introduce new trackers without consent).

### 8.6 Marketing & the personalized New Releases feed (M7)

- **Separate marketing/notification consent.** Surfacing personalized new releases in-site is part of the requested service; **push/email notifications about them require their own opt-in**, distinct from the styling consent (already noted in M7).
- **Commercial email compliance.** Any New Releases emails must follow **CAN-SPAM** (US): accurate sender/subject, a physical postal address, and a working unsubscribe honored promptly — and GDPR/ePrivacy consent for EU recipients.
- **"Why am I seeing this?"** Because the feed is profiling-driven, a short explanation of why an item was surfaced (which profile attributes matched) supports profiling-transparency expectations and doubles as good UX (already in M7's design).

### 8.7 Age / minors (registration gate — precedes M1)

- **Age gate + minimum age.** Because the system collects photos and sensitive data, restrict the styling feature to adults (or the age of majority in the customer's region) via the terms and a registration age check. This sharply reduces exposure.
- **COPPA (US, under-13).** If the brand ever has actual knowledge it's collecting from a child under 13, COPPA applies — and the **2025 amendments (compliance deadline April 22, 2026)** expanded "personal information" to include **biometric data**, require **separate opt-in consent for third-party sharing**, and tighten retention/deletion. The clean answer for a fashion styling tool is to **exclude minors from the photo/measurement flow** and say so.
- **Teen considerations.** Some states impose additional protections for minors above 13; if the brand markets to older teens, counsel should confirm treatment. Default recommendation: adults only for the AI styling feature.

### 8.8 E-commerce disclosures the engine must respect (M5/M9 outputs)

These are ordinary commerce disclosures that the recommendation surfaces must not undermine:

- **Accurate pricing and availability** on recommended items — the fit-checker's grounding guarantee (M5) supports this; never recommend or price an item inconsistently with the live catalog.
- **Return/refund policy visibility.** The FTC expects the refund/return policy to be clearly disclosed before purchase; recommendation and New Releases surfaces should link to it, especially given Eighth Hour's made-to-order, limited-return model.
- **No dark patterns.** Consent choices (styling opt-in, marketing opt-in, retention) must be presented neutrally — no pre-checked boxes, no "confirm-shaming," equal prominence for decline. The FTC and several state laws specifically target manipulative consent UX.
- **Material-connection / advertising honesty.** Recommendations are Eighth Hour's own products; keep them presented as such, and if any third-party or sponsored content ever enters the feed, disclose it (FTC endorsement rules).

### 8.9 Governance & record-keeping (supports all of the above)

- **Consent records.** Store, per customer, exactly what she consented to and when, with the version of the notice shown — biometric statutes and GDPR both expect demonstrable consent.
- **Retention/destruction schedule.** A written, followed schedule for photos, measurements, and derived embeddings (BIPA and the COPPA amendments both require published retention and actual deletion).
- **Data Protection Impact Assessment (DPIA) / risk assessment.** Expected under GDPR for large-scale sensitive processing, and under California's CPPA risk-assessment rules for profiling/sensitive-data processing. Do this before launch (fits Phase 0/1 in §6).
- **Vendor due diligence & written assurances.** Contractually bind the sizing/AI providers to confidentiality, security, no-secondary-use/no-training-on-customer-data, breach notification, and deletion — and keep the documentation.
- **Breach notification readiness.** Know the notification obligations (GDPR 72-hour authority notice; US state breach-notification laws) and have a plan, since this data is high-sensitivity.
- **Accessibility of notices.** Disclosures must meet accessibility standards (WCAG / the EU Accessibility Act) so they're not effectively hidden from some users.

### 8.10 Quick placement map

| Disclosure / consent | Where it appears | Primary legal driver(s) |
|---|---|---|
| "You're talking to AI" | Start of guided flow (M1) | EU AI Act Art. 50 |
| How recommendations work + opt-out | Guided flow / privacy notice (M1, M9) | AI Act; CCPA/CPRA & state profiling rules |
| Biometric/sizing explicit consent | Dedicated screen before photo (M1→M2) | GDPR Art. 9/6/13; BIPA/CUBI/WA; CT |
| Third-party sharing + transfer notice | Same consent screen + privacy policy (M2) | GDPR Art. 13/28; CCPA sharing |
| Retention & deletion terms | Consent screen + privacy policy | GDPR; BIPA; COPPA amendments |
| Data-rights mechanisms (incl. embedding deletion) | Account + privacy policy | GDPR; US state laws |
| Do-Not-Sell/Share + GPC | Site-wide | CCPA/CPRA; state GPC mandates |
| Marketing opt-in + email compliance | New Releases notifications (M7) | CAN-SPAM; GDPR/ePrivacy |
| Age gate / minors exclusion | Registration (pre-M1) | COPPA (2025 amendments); state minor laws |
| Return policy + accurate pricing | Recommendation & checkout surfaces (M5/M9) | FTC |
| No dark patterns in consent UX | Every consent point | FTC; state privacy laws |

---

## 9. Why This Design Satisfies the Requirements

| Requirement | How it's met |
|---|---|
| Guided post-registration flow | **M1** intake orchestrator — a state machine over the screens, with light adaptive routing (retry/fallback) |
| Photo → accurate measurements via 3rd-party sizing | **M2** adapter wrapping the sizing provider, with confidence handling |
| Measurements → body shape profile | **M3** deterministic, auditable ratio-based classifier |
| Profile → curated EH-specific recommendations (garments & accessories) | **M5** RAG grounded in **M6** catalog KB (both product types as first-class items) + agentic stylist pipeline that completes looks |
| Same engine powers personalized New Releases | **M7** reuses M5/M6 via event-driven matching |
| Integrate 3rd-party AI/sizing, not fully in-house | Adapter boundaries (M2), provider-agnostic design, no in-house measurement model |
| Layered onto existing site post-launch | **M9** thin additive API + phased plan; site degrades gracefully without it |
| RAG where necessary | **M5/M6** — grounding recommendations in the real catalog |
| Agentic workflow where necessary | **M5** bounded stylist → build → fit-check → rationale pipeline |
| Modular, understandable, debuggable | Nine single-responsibility modules + versioned data contracts (§5) |
| Rigorous security guardrails | Cross-cutting **§4** guardrail layer: consent, data minimization, prompt- and query-injection defense, access control / ownership enforcement, standard web-layer protections, bounded agents, grounding enforcement, audit |

---

*End of planning document.*
