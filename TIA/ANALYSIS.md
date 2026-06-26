# Traffic Impact Assessment (TIA) Application — Comprehensive Analysis

> **Note:** The `TIA/` subdirectory is empty. The entire application resides in the parent directory `Cromton-Traffic-Impact-Asssessment/`.

---

## 1. Executive Summary

The **Cromton Traffic Impact Assessment (TIA)** is a sophisticated, Australia-focused web application for professional traffic engineering analysis. It enables engineers to assess traffic impacts, calculate queue lengths, Volume-to-Capacity Ratios (VCR), Level of Service (LOS), detour delays, and generate professional PDF reports compliant with Austroads, TMR (Queensland), and RMS (NSW) standards.

The application is a **multi-tier architecture** comprising:
- A **browser-first frontend SPA** (vanilla JavaScript + HTML/CSS)
- A **Python FastAPI report service** for AI-enhanced report generation and draft editing
- **Firebase Cloud Functions** for geocoding proxy and user management
- **Firebase Realtime Database & Storage** for user sync and GeoJSON dataset hosting
- **Extensive GeoJSON datasets** covering traffic counters across Australian states

---

## 2. Directory & File Structure

### 2.1 Root-Level Files (Configuration & Entry Points)

| File | Purpose |
|------|---------|
| `index.html` | Main production SPA (~2,559 lines). Contains all UI, inline scripts, and CDN dependencies. The authoritative frontend. |
| `index_formulas.html` | Formula-detailed view synced from `index.html` via PowerShell script. For users who need formulas visible in outputs. |
| `index_developer.html` | Isolated developer/beta editing file. Changes here do not affect production until explicitly synced. |
| `admin.html` | Admin portal for user management (~1,338 lines). Firebase Auth + RTDB integration. |
| `manual.html` | In-app user manual. |
| `app.js` | Extracted reference copy of frontend logic (~26,690 lines). Edited separately; inline in `index.html` is authoritative. |
| `styles.css` | Main stylesheet (~4,520 lines). Custom CSS variables, loading animations, print styles, responsive design. |
| `firebase-config.js` | Firebase project configuration (API keys, RTDB URL, Storage bucket). Safe for public exposure (access controlled by Security Rules). |
| `user-sync.js` | Firebase RTDB ↔ localStorage sync module (~295 lines). Enables cross-device state persistence and offline resilience. |
| `tia-shared-sync.js` | AGTTM geometry calculators and formula annotations (~183 lines). |
| `formula-agent.js` | Formula verification harness (~458 lines). Tests engineering formulas against Austroads/TMR/RTA reference values. |
| `report_service.py` | FastAPI backend (~3,706 lines). Report draft generation, AI summary enrichment, rate limiting, CORS protection. |
| `package.json` | Minimal npm config. Only test scripts (uses Node.js built-in test runner). |
| `requirements.txt` | Python dependencies: FastAPI, Uvicorn, Pydantic, python-multipart. |
| `requirements-scripts.txt` | Python dependencies for dataset build/upload scripts. |
| `.env.example` | Template for environment variables (API keys, rate limits, Firebase config). |
| `firebase.json` | Firebase Hosting/Functions configuration. Defines hosting rules, CORS headers, cache policies, and Cloud Function rewrites. |
| `database.rules.json` | Firebase Realtime Database security rules. |
| `storage.rules` | Firebase Storage security rules. |
| `cors.json` | CORS configuration for Firebase Storage buckets. |
| `dataset_manifest.json` | Dataset inventory tracking SHA-256 hashes, feature counts, versions, and Firebase Storage URLs for all GeoJSON datasets. |
| `Dockerfile` / `Dockerfile.report-service` | Identical Dockerfiles for containerizing the Python report service (Python 3.11 slim, non-root user). |
| `deploy.ps1` / `deploy.bat` | Deployment scripts for Firebase Hosting. |
| `LICENSE` / `COPYRIGHT.md` | Proprietary license terms. Copyright 2026 Crompton Concepts. |
| `README.md` | Comprehensive project documentation with quick start, deployment, and workflow instructions. |
| `.gitignore` | Git ignore patterns. |

### 2.2 Key Subdirectories

| Directory | Contents | Purpose |
|-----------|----------|---------|
| `calc/` | `tia-calc.js` (241 lines), `tia-calc.test.js` (203 lines) | Canonical engineering formula library. Single source of truth for all traffic calculations. Tested against Austroads/TMR reference values. |
| `functions/` | `index.js` (459 lines), `package.json` | Firebase Cloud Functions (v2 HTTP + v1 auth/callable). Google Geocoding proxy, auth user provisioning, admin password management. |
| `scripts/` | ~15 PowerShell/Python scripts | Git hooks, index sync, dataset update pipeline, venv management, deployment helpers. |
| `datasets/` | `QLD/`, `NSW/`, `VIC/`, `WA/`, `SA/`, `TAS/`, `NT/`, `ACT/` | GeoJSON traffic counter datasets organized by state. Raw data from TMR, TfNSW, councils, ATR logs. |
| `docs/` | `operations/`, `design/`, `analysis/` | Deployment guides, launch checklists, design docs, improvement summaries, dataset correction notes. |
| `excel calculations/` | ~6 Excel workbooks | Reference validation workbooks for engineering calculations. |
| `.githooks/` / `.claude/` / `.codex/` | Git hooks, Claude/Codex IDE configs | Workflow automation, IDE settings, formula standard checks. |
| `.github/workflows/` | `dataset-update.yml`, `code-checks.yml`, `state-dataset-build.yml`, `upstream-freshness.yml` | GitHub Actions workflows. |
| `.firebase/` | Hosting cache files | Firebase deployment metadata. |

---

## 3. Technology Stack

### 3.1 Frontend (Browser)

| Technology | Version | Usage |
|------------|---------|-------|
| **Vanilla JavaScript** | ES6+ | Single-page application. No frontend framework (React/Vue/Angular). |
| **Leaflet** | 1.9.4 | Interactive mapping for site selection, detour routes, traffic counter visualization. |
| **Chart.js** | 4.4.0 | Queue length, VCR/LOS, traffic volume charts and tables. |
| **html2pdf.js** | 0.10.1 | Client-side PDF generation from report DOM. |
| **html2canvas** | 1.4.1 | Screenshot/capture of DOM elements for PDF export. |
| **Font Awesome** | 6.5.2 | UI icons. |
| **Google Fonts** | — | JetBrains Mono, Merriweather, Source Sans 3, Space Grotesk. |
| **Firebase JS SDK** | CDN | Auth, Realtime Database, Storage (loaded via CDN script tags). |

### 3.2 Backend / Services

| Technology | Version | Usage |
|------------|---------|-------|
| **Python** | 3.11 | Report service and dataset processing scripts. |
| **FastAPI** | 0.104.1 | Report draft API, AI summary endpoints, editor interface. |
| **Uvicorn** | 0.24.0 | ASGI server for FastAPI. |
| **Pydantic** | 2.5.0 | Request/response validation and serialization. |
| **Node.js** | 22 (Cloud Functions) | Firebase Cloud Functions runtime. |
| **Firebase Admin SDK** | — | Cloud Functions for Auth, RTDB, and geocoding proxy. |
| **Docker** | — | Containerization of Python report service. |

### 3.3 Data & Infrastructure

| Technology | Usage |
|------------|-------|
| **Firebase Realtime Database** | User records (`tia_users`), cross-device sync, admin portal data. |
| **Firebase Storage** | GeoJSON dataset hosting with CDN delivery and SHA-256 integrity tracking. |
| **Firebase Hosting** | Static frontend hosting with rewrite rules to Cloud Functions. |
| **Firebase Cloud Functions** | Google Geocoding proxy (CORS-protected), auth user provisioning, admin password resets. |
| **Firebase Auth** | Email/password authentication with tier-based feature gating. |
| **GitHub Actions** | Automated dataset update pipeline (`.github/workflows/dataset-update.yml`). |
| **Google Cloud Run** | Hosted Python report service (referenced in README as fallback URL). |

---

## 4. Architecture Overview

### 4.1 Three-Layer Runtime Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: Frontend (Browser)                                │
│  ├─ index.html — Single-Page Application                    │
│  ├─ app.js — Core logic (calculations, UI state, reports)   │
│  ├─ calc/tia-calc.js — Canonical math library (browser +  │
│  │                      Node dual-mode)                     │
│  ├─ user-sync.js — Firebase RTDB ↔ localStorage bridge    │
│  ├─ tia-shared-sync.js — AGTTM geometry & formulas        │
│  ├─ formula-agent.js — Formula verification agent         │
│  └─ firebase-config.js — Project config (public-safe)     │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2: Python Report Service (FastAPI)                 │
│  ├─ report_service.py — Draft creation & editor endpoints │
│  ├─ Rate limiting (in-memory, per-IP)                    │
│  ├─ CORS with origin regex allow-listing                  │
│  ├─ Optional AI enrichment (Gemini/Anthropic APIs)      │
│  └─ Docker container (Python 3.11 slim, non-root)       │
├─────────────────────────────────────────────────────────────┤
│  LAYER 3: Firebase Cloud Platform                         │
│  ├─ Cloud Functions (Node.js 22):                         │
│  │   • googleAddressSearch — Geocoding proxy              │
│  │   • provisionAuthUser — Auto-provision RTDB stubs      │
│  │   • adminSetUserPassword — Admin password management   │
│  │   • reconcileAuthUsers — Auth/RTDB sync repair         │
│  ├─ Realtime Database — tia_users, shared sessions         │
│  ├─ Storage — GeoJSON datasets with CDN caching           │
│  ├─ Hosting — Static frontend + function rewrites          │
│  └─ Auth — Email/password with custom claims              │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Data Pipeline

```
Raw State Traffic Data (TMR, TfNSW, Councils, ATR logs)
          ↓
Python Enrichment Scripts (enrich_*.py, correct_*.py)
          ↓
Standardized GeoJSON FeatureCollections
          ↓
SHA-256 Hashing + Feature Count Validation
          ↓
dataset_manifest.json (version tracking)
          ↓
Firebase Storage (CDN-hosted with cache headers)
          ↓
Frontend fetches on load (with cache-busting via manifest)
```

### 4.3 Report Generation Pipeline

```
User inputs (site, parameters, growth rates, lane configs)
          ↓
Browser calculations (tia-calc.js — deterministic, client-side)
          ↓
Report Mode UI (editable commentary, section toggles)
          ↓
Optional: Send to Python Report Service (/drafts)
          ↓
FastAPI generates HTML draft → AI enrichment (optional)
          ↓
Report Editor (/report/editor/{draft_id}) → Print/PDF
```

---

## 5. Core Features & Capabilities

### 5.1 Traffic Analysis & Calculations

| Feature | Standard | Description |
|---------|----------|-------------|
| **Base Volume Calculation** | Mean rounded up | `calculateBaseVolume()` — weekly average, ROUNDUP to prevent underestimation. |
| **CAGR Growth Projection** | Compound annual | `calculateProjectedVolume()` — horizon-clamped, rounds up. |
| **V/C Ratio (Degree of Saturation)** | Austroads AGTM Part 3 | `calculateVCR()` — hourly volume per lane ÷ design capacity. |
| **Queue Length** | Austroads spacing models | `calculateQueueLength()` — net-overflow with speed-aware LV spacing (6.0 m city / 7.0 m highway) and 20.0 m HV spacing. |
| **PCE Volume** | Austroads grade bands | `calculatePCEVolume()` — 5 vehicle classes × 5 grade bands (0-9%+). |
| **Intersection Absorption** | Gap-acceptance theory | `calculateIntersectionAbsorption()` — HCM-style minor-movement capacity. |
| **Sight Distance** | Austroads Part 3 | `approachSightDistance()` — reaction + braking distance with grade-adjusted friction. |
| **Detour Delay** | Travel time differential | `calculateDelay()` — vehicle-units of delay from speed reduction. |
| **Free-Flow Speed** | HCM adjustments | `calculateAdjustedFFS()` — lane width, lateral clearance, median, access density adjustments. |
| **Reference Severance Guard** | Custom heuristic | `isSameRoadReferenceSevered()` — prevents wrong counter selection when roads are physically disconnected by arterials. |

### 5.2 Multi-State Dataset Coverage

| State | Datasets | Sources |
|-------|----------|---------|
| **QLD** | TMR (67,368 counters), Gold Coast (249,792), Brisbane (48,528), Ipswich (80,880), Logan (134,448), Toowoomba (48,000), Tewantin (1), QLD Census (2,411) | TMR, Council traffic counts, Census data |
| **NSW** | TfNSW (1,783), NSW 2026 projections (31,041) | TfNSW, RMS, ATR logs |
| **VIC** | 72,990 counters | VicRoads / state sources |
| **WA** | 2,936 counters | Main Roads WA |
| **SA** | 2,720 counters | DPTI |
| **TAS** | 523 counters | DSG |
| **NT** | 256 counters | DIPL |

### 5.3 User Management & Subscription Tiers

| Tier | Price | Features |
|------|-------|----------|
| **Free** | $0/mo | Traffic volume map only |
| **Basic** | $29/mo | Preloaded data + calculations |
| **Pro** | $79/mo | Basic + address search |
| **Pro+** | $149/mo | Pro + Python reports (AI-enhanced) |

### 5.4 Report Generation Features

- **Editable Report View**: Click-to-edit commentary boxes before printing
- **Section Toggle**: Remove/restore sections from final output
- **AI Summary Generator**: Executive, Technical, Key Findings, Recommendations, Comprehensive
- **Print Preview**: Toggle before final PDF export
- **Share Options**: Email, Microsoft Teams, System Share, Copy Link, Copy Summary
- **PDF Export**: Client-side via html2pdf.js + print-optimized CSS
- **Draft Persistence**: Save/load report drafts via FastAPI backend

### 5.5 Address Search & Geocoding

- **State Database Selector**: QLD, NSW, SA, VIC, WA, TAS, NT
- **Quick Address Search**: Google Geocoding API via Firebase Cloud Function proxy
- **Exact Match**: Direct counter lookup when road name matches dataset
- **Multiple Reference Points**: Weighted average of 3+ nearest counters within 5 km
- **Manual Traffic Generation**: Trip generation calculator or direct AADT entry
- **Road Mode Detection**: Auto-detects ONE-WAY vs TWO-WAY operation
- **Nearby Roads Explorer**: Adjustable radius (0.2–3.0 km) for context

---

## 6. Security & Hardening

### 6.1 Authentication & Authorization

- **Firebase Auth** with email/password (no social login currently)
- **Admin Portal** (`admin.html`) with role-based access control (`isAdmin` flag in RTDB)
- **Tier-based feature gating** — Free users cannot access Pro+ features (address search, Python reports)
- **Password requirements**: Minimum 8 characters
- **Password reset flow**: Email-based via Firebase Auth

### 6.2 CORS & Origin Protection

- **FastAPI**: Regex-based origin allow-listing (`REPORT_ALLOWED_ORIGIN_REGEX` env var)
- **Cloud Functions**: Explicit `ALLOWED_ORIGINS` array with origin validation
- **Firebase Hosting**: `cors.json` for Storage bucket access

### 6.3 Rate Limiting

- **In-memory rate limiter** in `report_service.py` (per client IP)
- Configurable via `REPORT_VERIFY_RATE_MAX` and `REPORT_VERIFY_RATE_WINDOW_S`
- Opportunistic cleanup of stale buckets (>5,000 IPs)
- Returns `429` with `Retry-After` and `X-RateLimit-*` headers

### 6.4 Request Size Limits

- **Content-Length validation** middleware in FastAPI
- Default max: 12 MB (`REPORT_MAX_REQUEST_BYTES`)
- Returns `413` with human-readable MB explanation

### 6.5 Security Headers

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`
- CSP for HTML responses (restricts remote execution vectors)
- `Access-Control-Allow-Private-Network: true` for localhost calls from HTTPS origins

### 6.6 Container Security

- **Non-root user** (`appuser` in `appgroup`) in Docker container
- **Python 3.11 slim** base image (minimal attack surface)
- `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`

### 6.7 Data Integrity

- **SHA-256 hashing** of all GeoJSON datasets in `dataset_manifest.json`
- **Feature count validation** with >30% drop rejection
- **Cache versioning** — frontend auto-clears cached datasets when manifest changes

---

## 7. Developer Workflow & Automation

### 7.1 Three-Index Model

| File | Role | Sync Direction |
|------|------|----------------|
| `index.html` | **Production** — main user interface | Source of truth |
| `index_formulas.html` | **User-facing formula view** | Synced FROM `index.html` |
| `index_developer.html` | **Beta/developer editing** | Isolated; manual sync only |

### 7.2 Git Hooks (Pre-commit)

- **Auto-sync**: When `index.html` is staged, `index_formulas.html` is automatically regenerated and staged
- **Formula standards check**: Claude/Codex hooks validate formula consistency
- **Installation**: `powershell -ExecutionPolicy Bypass -File scripts/install-hooks.ps1`

### 7.3 Automated Dataset Pipeline

- **GitHub Actions**: `.github/workflows/dataset-update.yml`
- **Schedule**: Every 6 hours + manual trigger
- **Script**: `scripts/check_and_update_datasets.py`
- **Validation**: GeoJSON shape validation, SHA-256 comparison, row-drop guardrails (>30% threshold)
- **Output**: Auto-updates local files and regenerates `dataset_manifest.json`

### 7.4 Testing

- **Node.js built-in test runner**: `node --test calc/tia-calc.test.js`
- **Watch mode**: `node --test --watch calc/tia-calc.test.js`
- **Reference value tests**: All formulas pinned to Austroads/TMR/RTA expected values
- **No npm dependencies**: Tests run with zero `npm install` (pure Node.js)

---

## 8. Notable Engineering Patterns

### 8.1 Canonical Formula Library (Single Source of Truth)

The `calc/tia-calc.js` module is the **only** place engineering formulas live. It is:
- Imported by the production frontend (`app.js`)
- Tested by the test suite (`calc/tia-calc.test.js`)
- Verified by the Formula Agent (`formula-agent.js`)
- Dual-mode: attaches to `window.TIACalc` in browser, exports via `module.exports` in Node

### 8.2 Offline-First Resilience

- **localStorage-first**: All user data persists in browser localStorage
- **Firebase RTDB sync**: Syncs to cloud when online; falls back to local when offline
- **Graceful degradation**: If Firebase is unconfigured, app runs in local-only mode
- **Dataset caching**: GeoJSON datasets cached locally; auto-refreshed when manifest version changes

### 8.3 Loading UX Sophistication

The loading overlay is a **mini-application** with:
- Staged progress bar with randomized pulse animation (non-linear, human-feeling)
- Rotating technical hints (engineering facts, recommendations, funny comments)
- Context-aware hints based on user search query (highway vs street vs Queensland vs NSW)
- Three-panel layout: top metadata cards, center spinner, bottom facts/recommendations
- Compact mode for quick searches vs full mode for initial app load

### 8.4 Report Customization

- **Editable headings**: Each section heading becomes `contenteditable` in report mode
- **Narrative overrides**: Top and bottom commentary per section, persisted to localStorage
- **Section removal/restore**: Toggle individual cards from report output
- **AI Summary**: Gemini-powered (optional) report summary generation

### 8.5 Volume Adjustment Model

A sophisticated modal for manual traffic volume refinement:
1. Base Volume (from DB)
2. Growth Projection (% p.a. × years)
3. Seasonal Factor (0.70–1.30, summer/shoulder/winter presets)
4. Day-of-Week Factor (0.50–1.20, weekday/weekend presets)
5. Directional Split Override (0–100% slider)
6. Peak Hour Factor (0.80–1.00)
7. Construction Traffic (additive D1/D2)
- Visual waterfall chart and step-by-step bar chart

---

## 9. Deployment Architecture

### 9.1 Local Development

```bash
# Terminal 1: Python report service
python report_service.py
# → http://127.0.0.1:8060

# Terminal 2: Static file server (optional)
python -m http.server 8080
# → http://localhost:8080/index.html
```

### 9.2 Hosted (Production)

| Component | Hosting | URL Pattern |
|-----------|---------|-------------|
| Frontend | Firebase Hosting | `https://crompton-apps.web.app` / `https://tia.cromptonapps.com` |
| Cloud Functions | Firebase Functions | `https://<region>-crompton-apps.cloudfunctions.net` |
| Report Service | Google Cloud Run | `https://tia-report-service-2nfbbli7oq-ts.a.run.app` |
| Datasets | Firebase Storage | `https://firebasestorage.googleapis.com/v0/b/crompton-apps...` |
| Database | Firebase RTDB | `https://crompton-apps-default-rtdb.firebaseio.com` |

### 9.3 Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `HOST` | `127.0.0.1` | FastAPI bind address |
| `PORT` | `8000` | FastAPI port |
| `REPORT_ALLOWED_ORIGINS` | `[]` | Explicit CORS origins |
| `REPORT_ALLOWED_ORIGIN_REGEX` | Multi-pattern | Regex CORS allow-list |
| `REPORT_MAX_REQUEST_BYTES` | `12,000,000` | Max request body size |
| `REPORT_MAX_DRAFTS` | `200` | Max in-memory drafts |
| `REPORT_DRAFT_TTL_HOURS` | `12` | Draft expiration time |
| `REPORT_VERIFY_RATE_MAX` | `20` | Rate limit max hits |
| `REPORT_VERIFY_RATE_WINDOW_S` | `600` | Rate limit window (seconds) |
| `ANTHROPIC_API_KEY` | — | Formula verification AI |
| `GEMINI_API_KEY` | — | Report summary AI |
| `GOOGLE_MAPS_API_KEY` | (Secret) | Geocoding proxy |

---

## 10. Strengths & Quality Indicators

1. **Engineering Rigor**: Formulas are extracted to a canonical library, tested against reference values, and documented with Austroads/TMR citations.
2. **Multi-State Coverage**: Comprehensive GeoJSON datasets spanning all Australian states with automated update pipelines.
3. **Security Conscious**: CORS allow-listing, rate limiting, non-root Docker containers, CSP headers, request size limits.
4. **Offline Resilience**: localStorage-first with Firebase sync fallback; app works without internet after initial load.
5. **Professional UX**: Loading animations, progress bars, context-aware hints, editable reports, print-optimized CSS.
6. **Developer Experience**: Three-index model, Git hooks, formula verification agent, automated testing with no npm dependencies.
7. **AI Integration**: Optional Gemini/Anthropic enrichment for report summaries and formula verification.
8. **Subscription Model**: Tiered SaaS with feature gating (Free → Basic → Pro → Pro+).

---

## 11. Potential Areas for Improvement

1. **Frontend Framework**: The ~2,559-line `index.html` and ~26,690-line `app.js` are monolithic. Consider migrating to a component-based framework (React/Vue/Svelte) for maintainability.
2. **State Management**: Currently uses global variables and DOM state. A formal state management library (Redux, Pinia, Zustand) could improve predictability.
3. **TypeScript**: The entire frontend is vanilla JS. TypeScript would catch type errors early, especially in the calculation library.
4. **Backend Persistence**: Drafts are stored in-memory (`DRAFTS` dict) with TTL. For production scale, migrate to Redis or Firestore.
5. **Rate Limiter Scaling**: The in-memory rate limiter is per-instance. For multi-instance deployments, use Redis or a shared store.
6. **Test Coverage**: The test suite covers `calc/tia-calc.js` well but the frontend (`app.js`) and backend (`report_service.py`) have no visible test coverage.
7. **CI/CD**: No visible GitHub Actions for testing or linting. The dataset update workflow is present but not a full CI/CD pipeline.
8. **Accessibility**: While ARIA attributes are present (`role`, `aria-label`, `aria-live`), a full WCAG audit would be beneficial.
9. **Mobile Responsiveness**: The complex map and multi-column grid layouts may need additional mobile optimization.
10. **Database Migrations**: No visible migration system for RTDB schema changes.

---

## 12. File Size Summary

| File | Lines | Role |
|------|-------|------|
| `app.js` | ~26,690 | Extracted frontend logic (reference) |
| `index.html` | ~2,559 | Main production SPA (authoritative) |
| `report_service.py` | ~3,706 | FastAPI report service |
| `styles.css` | ~4,520 | Main stylesheet |
| `admin.html` | ~1,338 | Admin portal |
| `functions/index.js` | ~459 | Firebase Cloud Functions |
| `calc/tia-calc.js` | ~241 | Canonical formula library |
| `calc/tia-calc.test.js` | ~203 | Reference value tests |
| `user-sync.js` | ~295 | RTDB sync module |
| `formula-agent.js` | ~458 | Formula verification harness |
| `tia-shared-sync.js` | ~183 | AGTTM geometry sync |
| `dataset_manifest.json` | 133 | Dataset inventory |

**Total estimated code**: ~40,000+ lines of JavaScript, ~3,700 lines of Python, ~4,500 lines of CSS, ~2,500 lines of HTML.

---

*Analysis compiled on: 2026-06-22*
*Application: Cromton Traffic Impact Assessment (TIA)*
*Copyright: Crompton Concepts 2026*
