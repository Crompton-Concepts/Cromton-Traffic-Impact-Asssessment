---
name: Cromton TIA Design System
colors:
  surface: '#fbf8fa'
  surface-dim: '#dcd9db'
  surface-bright: '#fbf8fa'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f3f4'
  surface-container: '#f0edef'
  surface-container-high: '#eae7e9'
  surface-container-highest: '#e4e2e3'
  on-surface: '#1b1b1d'
  on-surface-variant: '#45474c'
  inverse-surface: '#303032'
  inverse-on-surface: '#f3f0f2'
  outline: '#75777d'
  outline-variant: '#c5c6cd'
  surface-tint: '#545f73'
  primary: '#091426'
  on-primary: '#ffffff'
  primary-container: '#1e293b'
  on-primary-container: '#8590a6'
  inverse-primary: '#bcc7de'
  secondary: '#0058be'
  on-secondary: '#ffffff'
  secondary-container: '#2170e4'
  on-secondary-container: '#fefcff'
  tertiary: '#1e1200'
  on-tertiary: '#ffffff'
  tertiary-container: '#35260c'
  on-tertiary-container: '#a38c6a'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d8e3fb'
  primary-fixed-dim: '#bcc7de'
  on-primary-fixed: '#111c2d'
  on-primary-fixed-variant: '#3c475a'
  secondary-fixed: '#d8e2ff'
  secondary-fixed-dim: '#adc6ff'
  on-secondary-fixed: '#001a42'
  on-secondary-fixed-variant: '#004395'
  tertiary-fixed: '#fadfb8'
  tertiary-fixed-dim: '#ddc39d'
  on-tertiary-fixed: '#271902'
  on-tertiary-fixed-variant: '#564427'
  background: '#fbf8fa'
  on-background: '#1b1b1d'
  surface-variant: '#e4e2e3'
  surface-background: '#F8FAFC'
  surface-card: '#FFFFFF'
  border-subtle: '#E2E8F0'
  engineering-blue: '#0369A1'
  status-success: '#10B981'
  status-warning: '#F59E0B'
  status-danger: '#EF4444'
  status-info: '#6366F1'
  vcr-low: '#22C55E'
  vcr-medium: '#EAB308'
  vcr-high: '#F97316'
  vcr-critical: '#DC2626'
  beta-accent: '#8B5CF6'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '700'
    lineHeight: '1.2'
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.3'
  title-sm:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: '1.4'
  body-base:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: '1.4'
  data-mono:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: '1.5'
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: 0.05em
  formula-ref:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.4'
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  container-padding: 24px
  sidebar-width: 320px
  gutter: 16px
  input-gap: 12px
  table-cell-padding: 8px 12px
---

# Traffic Impact Assessment (TIA) Application Design

## 1. Purpose

This document describes the technical design of the Cromton Traffic Impact Assessment application, including:
- System architecture
- Frontend and backend responsibilities
- Data model and dataset lifecycle
- Core user and processing workflows
- Security and operational considerations

The application is a browser-based traffic engineering tool used to assess work-zone and detour impacts, calculate queue and VCR/LOS outcomes, and generate professional report outputs.

## 2. Product Scope

### In scope
- Interactive traffic impact analysis in browser (single-page UI)
- Map-based site and detour analysis
- Formula-driven queue and capacity calculations
- Report generation and editable report drafting via Python service
- Multi-user account synchronization via Firebase Realtime Database
- Regional dataset ingestion and cache invalidation driven by dataset manifest

### Out of scope
- Full GIS server infrastructure
- Real-time traffic feed ingestion from live sensors
- Identity federation (OAuth/SSO)
- Multi-tenant backend persistence for report drafts (current draft storage is in-memory)

## 3. High-Level Architecture

The system is composed of three runtime layers:

1. Frontend application (primary runtime)
- Main entry page: index.html
- Core logic is an inline monolithic script in index.html
- app.js exists as a read-only extracted reference copy, not an executable module
- Uses CDN-delivered libraries: Leaflet, Chart.js, html2pdf

2. Client-side support modules
- user-sync.js: Firebase-backed user sync with local fallback
- tia-shared-sync.js: shared formula sync and AGTTM geometry helpers
- formula-agent.js: formula verification harness against reference implementations
- firebase-config.js: public Firebase project configuration consumed by user-sync.js

3. Python report service
- report_service.py (FastAPI)
- Provides draft creation and report editor endpoint
- Generates report context, table analyses, and fallback narrative content
- Optionally enriches narrative using Gemini API when key is configured

## 4. Key Design Principles

- Browser-first calculations: Core engineering logic executes in client UI for immediate feedback.
- Resilience by fallback: Features degrade gracefully when remote services are unavailable (for example, Firebase sync).
- Deterministic report pipeline: Structured payloads and table metadata are used to create reproducible report drafts.
- Data freshness with guardrails: Dataset updates are hash-validated and protected against suspicious feature-count drops.
- Portable deployment: Frontend can run from file://, static hosting, or local HTTP server; backend is optional for advanced report flow.

## 5. Frontend Design

## 5.1 UI and interaction model

The primary interface is a single, dense analysis workspace with:
- Project and analysis parameter inputs
- Queue tables/charts (directional and hourly)
- VCR/LOS tables/charts (directional and hourly)
- Detour route capacity modeling with map interactions
- Report-mode and print/preview pathways
- Formula verification utilities

The page includes production/developer behavior toggles, where beta-oriented sections are hidden in production view.

## 5.2 Core frontend responsibilities

- Initialize and validate UI dependencies and datasets
- Manage user session and local state
- Load GeoJSON and associated manifest metadata
- Run domain calculations (queue, VCR, LOS, detour overlays)
- Build chart/table outputs for interpretation and report export
- Produce normalized payloads for Python report editing/generation

## 5.3 State and storage strategy

State is primarily in browser memory and localStorage:
- Auth/session keys for current user and tier
- Cached datasets and manifest signature
- User database fallback store
- Temporary report and profile snapshots

The state model prioritizes fast local responsiveness, with selective sync to remote services.

## 6. User and Account Synchronization Design

user-sync.js encapsulates cross-device account sync via Firebase Realtime Database.

### Behavior
- Initializes sync only when Firebase config is valid
- Pulls remote users with timeout protection
- Merges remote and local data, with remote precedence for conflicts
- Supports save/delete/restore/purge operations
- Falls back to local-only behavior on Firebase failure

### Rationale
- Allows app continuity offline or during Firebase outages
- Keeps account persistence simple without requiring a dedicated backend auth service

## 7. Dataset and Geospatial Design

## 7.1 Datasets

The app consumes regional GeoJSON datasets (for example QLD and NSW variants) and tracks versions in dataset_manifest.json.

Manifest entries include:
- version
- sha256
- feature_count
- source_url
- local_file
- updated_at

## 7.2 Update pipeline

scripts/check_and_update_datasets.py performs automated update checks:
- Fetches upstream source blobs
- Validates JSON/GeoJSON structure
- Computes SHA-256 hashes
- Enforces feature-drop guard threshold (default 30%)
- Updates local dataset files and manifest

## 7.3 Cache invalidation

On application load, index.html reads dataset_manifest.json.
If the manifest signature has changed, stale dataset cache entries are cleared from localStorage to force refresh.

## 8. Calculation and Formula Design

Calculations are implemented in frontend logic and shared helpers.
Major calculation domains include:
- Queue estimates (including AGTTM and SWT variants)
- VCR and LOS by direction and period
- Hourly profile interpretation
- Detour route stress and capacity overlays

formula-agent.js provides a test harness with:
- Reference implementations for critical formulas
- Live mode validation against app calculation bridge
- Standalone mode fallback when live bridge is absent

This supports regression detection and formula confidence during ongoing iteration.

## 9. Report Generation Design

## 9.1 Frontend report preparation

Frontend assembles a structured payload containing:
- Project metadata
- Inputs and results
- Selected site details
- Computed tables and chart captures
- Optional editor profile settings

## 9.2 Backend processing (FastAPI)

report_service.py performs:
- Payload validation and request-size checks
- Draft creation with ID and TTL-based pruning
- Report context extraction and normalization
- Table analysis and fallback narrative generation
- Optional Gemini enrichment for executive sections

Primary endpoints:
- GET /health
- POST /report/draft
- GET /report/editor/{draft_id}

## 9.3 Draft lifecycle

Drafts are held in an in-memory store with:
- Max draft cap
- Time-based expiry (TTL)
- Oldest-first trimming when cap is exceeded

This is suitable for local/single-instance operation and can be replaced by persistent storage if required.

## 10. Security Design

## 10.1 Frontend
- Firebase credentials are public by design; access control depends on Firebase rules.
- User data defaults to local-only if remote sync cannot be trusted/initialized.

## 10.2 Backend
report_service.py applies:
- CORS allowlist/regex controls via environment variables
- Content-Length enforcement (request size guard)
- Security headers (nosniff, frame deny, referrer policy, permissions policy)
- CSP for HTML responses compatible with inline editor behavior

## 10.3 Operational concerns
- Gemini API use is optional and key-driven
- No sensitive credentials should be embedded in static frontend assets beyond standard public Firebase identifiers

## 11. Deployment and Runtime Model

## 11.1 Local/developer
- Start Python service: python report_service.py
- Open index.html directly or serve via python -m http.server
- Optional script tooling for sync hooks and dataset updates

## 11.2 Production-oriented
- Static hosting for frontend (including GitHub Pages-compatible behavior)
- Python service hosted behind reverse proxy for report endpoints
- Environment-configured origin controls and request limits

## 11.3 Build and sync workflow

The repository uses synchronized variants of the main UI:
- index.html: primary production source
- index_formulas.html: formula-facing synchronized variant
- index_developer.html: isolated developer/beta editing surface

PowerShell scripts and git hooks automate sync/staging behavior.

## 12. Non-Functional Requirements

- Performance
  - Fast interactive updates for input changes and chart regeneration
  - Efficient local cache usage for large GeoJSON loads

- Reliability
  - Local fallback operation for user persistence
  - Defensive checks on remote dataset updates

- Maintainability
  - Current monolithic frontend script enables rapid feature iteration but raises complexity
  - Auxiliary modules isolate critical concerns (sync, formulas, report backend)

- Portability
  - Works on Windows-centric workflow with browser-first execution
  - Minimal backend dependency for core analysis usage

## 13. Current Constraints and Risks

- Frontend complexity concentration in single large HTML/script file may increase regression risk.
- In-memory backend draft store is not durable across process restart.
- Heavy reliance on global window state can make modular testing harder.
- Multiple hosted third-party CDN dependencies require network availability and external uptime.

## 14. Recommended Evolution Path

1. Refactor frontend into modular ES modules while preserving current behavior.
2. Introduce typed domain models for payloads and calculation state transitions.
3. Add persistent draft storage (SQLite/PostgreSQL) for multi-session reliability.
4. Add automated end-to-end tests for major calculation and report workflows.
5. Add formal API schema versioning between frontend and report service.

## 15. File Responsibility Map

- index.html: Main SPA UI, domain logic, runtime orchestration
- app.js: Extracted read-only copy of index script (reference)
- user-sync.js: Firebase account sync wrapper and local fallback
- tia-shared-sync.js: Shared geometry and formula-sync utilities
- formula-agent.js: Formula verification runner
- firebase-config.js: Firebase project config
- report_service.py: FastAPI report draft/editor backend
- dataset_manifest.json: Dataset version/hash metadata
- scripts/check_and_update_datasets.py: Dataset update and integrity workflow
- DEPLOYMENT.md: Environment and operational setup guidance
