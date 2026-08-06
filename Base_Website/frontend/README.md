# Frontend - AI Styling Engine UI

This directory contains all frontend code for the AI Styling Engine integration with the Eighth Hour website.

## Directory Structure

```
frontend/
├── pages/              # Full-page components (standalone HTML/CSS/JS)
│   ├── intake-flow.html       # 5-step intake wizard UI
│   ├── intake-flow.js         # Intake orchestration logic
│   ├── intake-flow.css        # Intake flow styling
│   ├── recommendations.html   # Personalized recommendations display
│   ├── recommendations.js     # Recommendations loading & filtering
│   └── recommendations.css    # Recommendations styling
│
├── components/         # Reusable components (embeddable in other pages)
│   ├── fit-checker-widget.js  # Fit checker for product pages
│   └── fit-checker.css        # Fit checker styling
│
├── js/                # Shared utilities & loaders
│   └── recommendations-loader.js  # Auto-load recommendations on home page
│
└── README.md          # This file

## Features

### Intake Flow (`pages/intake-flow.html`)
- 5-step guided wizard for users to complete style profile
- Consent collection
- Body measurements input
- Body shape profile display
- Style preferences selection
- Session persistence (localStorage)
- Links to recommendations after completion

**Entry Point:** `frontend/pages/intake-flow.html`
**Referenced from:** Home page header "My Style" link

### Recommendations (`pages/recommendations.html`)
- Display personalized product recommendations
- Category filtering
- User profile summary
- Responsive grid layout

**Entry Point:** `frontend/pages/recommendations.html`
**Referenced from:** Intake flow completion screen

### Fit Checker Widget (`components/fit-checker-widget.js`)
- Embeds on product detail pages
- Shows recommended size with confidence %
- Displays fit scoring across all sizes
- Collects fit feedback (too tight/perfect/too loose)
- Submits feedback to M10 backend

**Embedded in:** `product.html`

### Recommendations Loader (`js/recommendations-loader.js`)
- Auto-loads on home page if user has active session
- Fetches personalized recommendations from backend
- Displays 6 featured recommendations in hero section

**Embedded in:** `index.html`

## API Integration

All frontend components connect to the AI Styling Engine backend at `http://localhost:8000`

### Intake Flow Endpoints
- `POST /intake/session` - Create new intake session
- `POST /intake/consent` - Record user consent
- `POST /intake/confirm` - Confirm measurements
- `POST /intake/preferences` - Submit style preferences
- `POST /consent` - Record global consent

### Recommendations Endpoints
- `GET /recommendations/{session_id}` - Get personalized products
- `GET /new-releases/{session_id}` - Get new releases feed
- `POST /fit-check/{session_id}/{product_sku}` - Check product fit
- `POST /feedback/fit` - Submit fit feedback (M10)

## LocalStorage Keys

- `userId` - Unique user identifier
- `intakeSession` - Current intake session data (JSON)
- `currentSessionId` - Most recent completed session ID
- `fitFeedback` - Collected fit feedback (array of feedback objects)

## Browser Compatibility

- Chrome/Edge: ✅ Full support
- Firefox: ✅ Full support
- Safari: ✅ Full support
- Mobile browsers: ✅ Responsive design

## Session Lifecycle

```
1. User clicks "My Style" → intake-flow.html
2. Completes 5-step intake process
3. Session saved to backend
4. Session ID stored in localStorage
5. Redirected to recommendations.html
6. User can browse products with fit checker
7. Fit feedback collected on product pages
8. Feedback sent to M10 backend
9. Next visit: auto-load recommendations from home page
```

## Development Notes

### Relative Paths
- From `pages/`: Use `../` to reach root (e.g., `../index.html`, `../css/style.css`)
- From `components/`: Use `../../` to reach root
- From `js/`: Use `../` to reach root

### Styling
- Base styles imported from `../css/style.css`
- Component-specific styles in co-located `.css` files
- Responsive design with mobile-first approach

### State Management
- Session state: localStorage
- User profile: localStorage (intake session data)
- Recommendations: fetched fresh from API
- Feedback: collected locally, sent to backend

## Testing

### Manual Testing Checklist
- [ ] Intake flow: All 5 steps complete
- [ ] Measurements: Validation works (60-140cm range)
- [ ] Shape profile: Displays correctly based on measurements
- [ ] Preferences: Multi-select works for colors/silhouettes
- [ ] Recommendations: Load and display after intake
- [ ] Fit checker: Embeds on product pages, shows scoring
- [ ] Feedback modal: Collects fit feedback
- [ ] Cross-browser: Test in Chrome, Firefox, Safari
- [ ] Mobile: Test responsive design on devices

## Future Enhancements (Phase 5+)

- [ ] Persist recommendations to backend (not just API fetch)
- [ ] Implement rating system for products
- [ ] Add reorder history integration
- [ ] Implement A/B testing for recommendation variants
- [ ] Add animation transitions between intake steps
- [ ] Implement offline mode with service worker
- [ ] Add accessibility improvements (ARIA labels, keyboard nav)

