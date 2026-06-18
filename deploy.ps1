<#
.SYNOPSIS
    Deploy Crompton TIA App to Firebase Hosting.
.PARAMETER Functions
    Also deploy Cloud Functions.
.PARAMETER Message
    Optional deployment note.
.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -Functions
    .\deploy.ps1 -Message "Fix admin login"
#>
param(
    [switch]$Functions,
    [string]$Message = ""
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Write-Step { param([string]$Text) Write-Host "`n>> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "  OK   $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "  WARN $Text" -ForegroundColor Yellow }
function Write-Fail { param([string]$Text) Write-Host "  FAIL $Text" -ForegroundColor Red }

function Sync-ReportServiceUrl {
    Write-Step "Syncing report service URL"

    if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
        Write-Warn "gcloud CLI not found; skipping report service URL sync"
        return
    }

    try {
        $reportServiceUrl = (& gcloud run services describe tia-report-service --project crompton-apps --format "value(status.url)" 2>&1 | Out-String).Trim()
    } catch {
        Write-Warn "Could not read tia-report-service URL from Cloud Run; skipping sync"
        return
    }

    if (-not $reportServiceUrl -or $reportServiceUrl -match '^ERROR:') {
        Write-Warn "Cloud Run did not return a report service URL; skipping sync"
        return
    }

    $appJsPath = Join-Path $PSScriptRoot 'app.js'
    if (-not (Test-Path $appJsPath)) {
        Write-Warn "app.js not found; skipping report service URL sync"
        return
    }

    $appJs = Get-Content $appJsPath -Raw
    $pattern = "const REPORT_SERVICE_PROD_DEFAULT_URL = 'https://[^']+';"
    $replacement = "const REPORT_SERVICE_PROD_DEFAULT_URL = '$reportServiceUrl';"

    if ($appJs -notmatch $pattern) {
        Write-Warn "Could not find REPORT_SERVICE_PROD_DEFAULT_URL in app.js; skipping sync"
        return
    }

    $updatedAppJs = [regex]::Replace($appJs, $pattern, $replacement, 1)
    if ($updatedAppJs -ne $appJs) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($appJsPath, $updatedAppJs, $utf8NoBom)
        Write-Ok "Updated app.js report service URL to $reportServiceUrl"
    } else {
        Write-Ok "app.js report service URL already current"
    }
}

Write-Host ""
Write-Host "+--------------------------------------------------+" -ForegroundColor Blue
Write-Host "|  Crompton TIA -- Firebase Deploy                 |" -ForegroundColor Blue
Write-Host "+--------------------------------------------------+" -ForegroundColor Blue
if ($Message) { Write-Host "  Note: $Message" -ForegroundColor DarkGray }
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray

Write-Step "Pre-flight checks"

try {
    $v = & firebase --version 2>&1
    Write-Ok "Firebase CLI: $v"
} catch {
    Write-Fail "Firebase CLI not found. Run: npm install -g firebase-tools"
    exit 1
}

$required = @('firebase.json','.firebaserc','index.html','app.js','user-sync.js','firebase-config.js','dataset_manifest.json','storage.rules')
$missing  = $required | Where-Object { -not (Test-Path $_) }
if ($missing.Count -gt 0) {
    Write-Fail "Missing files: $($missing -join ', ')"
    exit 1
}
Write-Ok "All required files present"

# --- Auth check: local-only (no network, cannot hang) ---
Write-Step "Checking Firebase authentication"
$authOutput = (& firebase login:list --non-interactive 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $authOutput -match 'No authorized accounts' -or $authOutput -notmatch '@') {
    Write-Fail "No Firebase login found."
    Write-Host "        Run:  firebase login --reauth" -ForegroundColor Yellow
    exit 1
}
$authLine = (($authOutput -split "`n") | Where-Object { $_ -match '@' } | Select-Object -First 1)
if ($authLine) { $authLine = $authLine.Trim() }
Write-Ok "Firebase login: $authLine"

# index.html is the single source of truth. Regenerate the Developer and
# Formula variants from it so the three entry points can never drift.
Write-Step "Regenerating HTML variants from index.html"
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) { $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue }
if ($pythonCmd) {
    & $pythonCmd.Source 'scripts/build_html_variants.py'
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "HTML variant generation failed."
        exit 1
    }
    Write-Ok "index_developer.html and index_formulas.html regenerated"
} else {
    Write-Warn "python not found; skipping HTML variant regeneration (edit index.html and run scripts/build_html_variants.py manually)"
}

Write-Step "File count"
$html = (Get-ChildItem -Filter "*.html"    | Measure-Object).Count
$js   = (Get-ChildItem -Filter "*.js"      | Measure-Object).Count
$geo  = ((Get-ChildItem -Filter "*.geojson") + (Get-ChildItem -Path 'datasets' -Recurse -Filter "*.geojson" -ErrorAction SilentlyContinue) | Measure-Object).Count
Write-Ok "HTML: $html  JS: $js  GeoJSON: $geo (incl. datasets/)"

# Dataset files the app expects on hosting (used as Firebase Storage fallback)
$expectedDatasets = @(
    'datasets/QLD/tmr.geojson','datasets/QLD/goldcoast.geojson','datasets/QLD/brisbane.geojson',
    'datasets/QLD/ipswich.geojson','datasets/QLD/logan.geojson','datasets/QLD/toowoomba.geojson',
    'datasets/QLD/tewantin.geojson','datasets/QLD/qld_census.geojson',
    'datasets/NSW/nsw_2026.geojson','datasets/NSW/nsw.geojson','datasets/NSW/tnsw.geojson',
    'datasets/SA/sa.geojson','datasets/VIC/vic.geojson','datasets/WA/wa.geojson','datasets/TAS/tas.geojson',
    'datasets/NT/nt.geojson'
)
$missingDatasets = $expectedDatasets | Where-Object { -not (Test-Path $_) }
if ($missingDatasets.Count -gt 0) {
    Write-Warn "Missing dataset files (app will rely on Firebase Storage for these): $($missingDatasets -join ', ')"
} else {
    Write-Ok "All state dataset files present"
}

Sync-ReportServiceUrl

Write-Step "Deploying"
# storage = storage.rules (public read for datasets/**); hosting = app + local dataset fallback
$target = if ($Functions) { "hosting,storage,functions" } else { "hosting,storage" }
if ($Functions) { Write-Warn "Including functions - ensure GCP service account exists" }

# NOTE: external commands do not throw in PowerShell - check $LASTEXITCODE,
# otherwise auth failures still print a success banner.
# --non-interactive: fail instead of waiting on a hidden prompt.
& firebase deploy --only $target --non-interactive
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Deploy failed (firebase exited with code $LASTEXITCODE)."
    Write-Host "        If you saw 'Authentication Error', run:  firebase login --reauth" -ForegroundColor Yellow
    exit 1
}
Write-Ok "Deploy complete"

Write-Host ""
Write-Host "+--------------------------------------------------+" -ForegroundColor Green
Write-Host "|  Deploy Successful                               |" -ForegroundColor Green
Write-Host "+--------------------------------------------------+" -ForegroundColor Green
Write-Host "  App:    https://crompton-apps.web.app" -ForegroundColor White
Write-Host "  Admin:  https://crompton-apps.web.app/admin.html" -ForegroundColor White
Write-Host ""
