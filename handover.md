# Crompton TIA — Project Handover

Captured: 2026-07-02
Repo: `Cromton-Traffic-Impact-Asssessment` (Firebase project: `crompton-apps`)

## What this is

Crompton Traffic Impact Assessment (TIA) is a proprietary web tool that generates Traffic Impact Assessment reports for Australian development applications, using traffic count/volume datasets across QLD, NSW, VIC, SA, WA, NT, TAS and state road authorities (e.g. TMR).

## Architecture

- **Frontend**: static HTML/JS/CSS on Firebase Hosting. `index.html` (main app, beta features hidden), `index_formulas.html` (public formulas view, kept in sync with `index.html`), `index_developer.html` (isolated dev/beta copy), plus `admin.html`, `manual.html`, `auth-action.html`. `app.js` (~1.25MB) holds the core logic. Uses Leaflet, Chart.js, html2pdf, Font Awesome via CDN.
- **New TypeScript layer**: `src/` (`api-client.ts`, `index.ts`, `types.ts`, `ui-utils.ts`), built via esbuild into `dist/tia-bundle.js`. This is an in-progress migration toward typed frontend modules — not yet the primary code path.
- **Backend**: `report_service.py` — a FastAPI service handling report generation, PDF/AI endpoints (`/verify-formulas`, using `ANTHROPIC_API_KEY`/`GEMINI_API_KEY`), draft persistence, and rate limiting. `report_service_persistence.py` provides the pluggable draft-store/rate-limiter abstraction. Runs locally on port 8060/8000; deployed to Cloud Run as `tia-report-service`.
- **Firebase Cloud Functions**: `functions/index.js` — `/api/google-address-search` and `/api/reconcile-auth-users` (hosting rewrites), auth reconciliation.
- **Calc/formula engine**: `calc/tia-calc.js`, tested via `calc/tia-calc.test.js` (Node's built-in test runner, `npm test`).
- **Reference spreadsheets**: `excel calculations/` — validation workbooks for Brisbane, Gold Coast, Ipswich, Logan, TMR, Toowoomba.
- **Firebase project**: single project `crompton-apps` — Hosting, Realtime Database (`database.rules.json`), Storage (`storage.rules`), Functions. No separate dev/staging Firebase project.

Docs worth reading first: `docs/operations/DEPLOYMENT.md`, `docs/operations/LAUNCH_CHECKLIST.md`, `docs/analysis/BRISBANE_DISTRIBUTION_FIX.md`, `docs/analysis/IMPROVEMENTS_SUMMARY.md`, `docs/design/design.md`, `TIA/ANALYSIS.md`.

## Current state (as of 2026-07-02)

- Local `main` is **13 commits behind `origin/main`** — pull before starting work.
- **Uncommitted changes** to `ctmp-integration.js` and `firebase-config.js`.
- **Untracked** `pnpm-lock.yaml` / `pnpm-workspace.yaml` — looks like a pnpm migration was started alongside the existing npm/`package-lock.json` setup but not finished or decided on. Worth clarifying before adding more dependencies.
- Commit history is dominated by automated `chore(data): refresh dataset releases` commits from `github-actions[bot]` (the scheduled dataset-update workflow), with occasional real feature work — most recent substantive commit is `a93da01 ctmp-integration`, which added `auth-action.html`, the `src/` TypeScript layer, `report_service_persistence.py`, `tests/`, `PASSWORD_RESET_SETUP.md`, and `styles-enhanced.css`.
- There are dozens of stale remote branches (`bolt-*`, `palette-*`, `perf-*`) from what looks like an automated code-improvement bot — none appear merged. Worth pruning or reviewing.
- `docs/operations/LAUNCH_CHECKLIST.md` is dated 2026-04-01 and marked "READY FOR LAUNCH", but functionality testing, performance testing, and several post-launch items are still unchecked — treat this checklist as stale/aspirational rather than current status.

## Environments & deployment

- Firebase project: `crompton-apps` (`.firebaserc`). `firebase.json` configures Hosting (public = repo root, ignores `.py`, `.md`, `docs/**`, `functions/**`, `scripts/**`), Database rules, Storage rules, and the two Function rewrites.
- Deploy via `deploy.ps1` (PowerShell, supports `-Functions` and `-Message` flags, syncs the Cloud Run URL via `gcloud`) or `deploy.bat`.
- Backend is containerized (`Dockerfile`, `Dockerfile.report-service` — `python:3.11-slim`, non-root `appuser`, uvicorn on port 8080) and deployed to Cloud Run as `tia-report-service`.
- Required secrets (see `.env.example`): `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, rate-limit settings, `FIREBASE_API_KEY`/`STORAGE_BUCKET`/`UPLOAD_EMAIL`, `TFNSW_API_KEY`.
- GitHub Actions: `dataset-update.yml` (every 6h, auto-commits refreshed datasets to `main`), `state-dataset-build.yml`, `upstream-freshness.yml`, `code-checks.yml`.

## Datasets & pipelines

`datasets/` holds per-state GeoJSON traffic data: NSW, QLD (Brisbane/Gold Coast/Ipswich/Logan/Tewantin/Toowoomba/TMR/census), SA, VIC, WA, NT, TAS, plus `datasets/TIA-dataset-builder/` (per-state builder scripts, also duplicated in `scripts/`). `dataset_manifest.json` tracks SHA-256/version info consumed by the auto-update workflow.

Typical pipeline order:
1. `correct_goldcoast.py` / `correct_volume_profiles.py` — replace flat Austroads-template hourly profiles with real TMR-band-derived distributions (`tmr_profiles.pkl`), preserving AADT via largest-remainder rounding.
2. `enrich_qld_hv.py`, `enrich_nsw_hv.py`, `enrich_sa_roadnames.py` — add heavy-vehicle % or real road names from state government sources.
3. `upload_to_firebase.py` / `upload_enriched.py` — gzip and upload to Firebase Storage (`crompton-apps.firebasestorage.app`), updating `dataset_manifest.json`. Requires an authenticated `firebase`/`gcloud` CLI session.

**Flag**: `correct_goldcoast.py` has a hardcoded Windows path to an old Claude session's output folder — dead if run as-is, needs updating. `goldcoast.geojson` at repo root (112MB) looks like a stray raw/working artifact, not something that should be committed long-term.

## Tests

- Python: `tests/test_report_service.py` (pytest + FastAPI `TestClient`, covers `report_service.py` endpoints, middleware, and the persistence layer). Run with `pytest tests/ -v`. Deps in `requirements-test.txt`. No `pytest.ini`/config — defaults only.
- JS: `calc/tia-calc.test.js` via `npm test` (Node's built-in test runner).

## Known issues & gotchas

- `docs/analysis/BRISBANE_DISTRIBUTION_FIX.md` (2026-04-01): Brisbane's hourly traffic distribution previously used unrealistic flat/cliff-edge values (e.g. constant 350 vph off-peak, 2547 vph AM peak), violating Austroads guidance. Fixed in `buildHourlyDirectionProfile()` in `index.html` (~line 15015) with a proper diurnal curve. Good reference if similar distribution bugs show up for other cities.
- `PASSWORD_RESET_SETUP.md` documents the Firebase Auth password-reset flow (`auth-action.html`, email templates) — read this before touching auth.
- `sendgrid/api.txt` is an empty placeholder — SendGrid isn't currently configured with a key.
- No TODO/FIXME/HACK comments found in the `.py`/`.js`/`.ts` source — code is clean in that respect, so undocumented issues are more likely to surface as data/config problems than inline warnings.

## Folder map (things that look important but are actually empty or near-empty)

- `tia (1)/` — **empty**, no files at all. Stray duplicate-named folder, safe to remove.
- `Apps/Crompton/`, `Labs/APPS/.../functions/`, `drives/Crompton/` — empty nested placeholder paths.
- `TIA/ANALYSIS.md` — a substantive 468-line analysis doc added in the `ctmp-integration` commit, worth reading for deeper context.
- `scripts/` — operational tooling: git hook/sync PowerShell scripts, dataset builders (mirrors `datasets/TIA-dataset-builder/`), `check_and_update_datasets.py` and `check_upstream_freshness.py` (used by the scheduled GitHub Actions), `audit_datasets.py`, `build_html_variants.py`.

## Suggested next steps for whoever picks this up

1. `git pull` to get the 13 commits from `origin/main`, then decide what to do with the uncommitted `ctmp-integration.js`/`firebase-config.js` changes.
2. Resolve the npm vs pnpm question (`package-lock.json` and `pnpm-lock.yaml` both present) before installing anything new.
3. Review and prune the stale `bolt-*`/`palette-*`/`perf-*` remote branches.
4. Treat `docs/operations/LAUNCH_CHECKLIST.md` as a checklist to re-verify, not a confirmed status.
5. Fix or remove the hardcoded path in `correct_goldcoast.py`, and consider removing the 112MB `goldcoast.geojson` from repo root if it's a stray artifact.
6. Delete the empty `tia (1)/` folder.
