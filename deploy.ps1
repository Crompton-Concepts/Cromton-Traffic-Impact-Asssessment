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

$required = @('firebase.json','.firebaserc','index.html','app.js','user-sync.js','firebase-config.js','dataset_manifest.json')
$missing  = $required | Where-Object { -not (Test-Path $_) }
if ($missing.Count -gt 0) {
    Write-Fail "Missing files: $($missing -join ', ')"
    exit 1
}
Write-Ok "All required files present"

if ((Test-Path 'index_developer.html') -and (Test-Path 'index.html')) {
    if ((Get-Item 'index_developer.html').LastWriteTime -gt (Get-Item 'index.html').LastWriteTime) {
        Write-Warn "index_developer.html is newer than index.html - consider promoting changes"
    }
}

Write-Step "File count"
$html = (Get-ChildItem -Filter "*.html"    | Measure-Object).Count
$js   = (Get-ChildItem -Filter "*.js"      | Measure-Object).Count
$geo  = (Get-ChildItem -Filter "*.geojson" | Measure-Object).Count
Write-Ok "HTML: $html  JS: $js  GeoJSON: $geo"

Write-Step "Deploying"
$target = if ($Functions) { "hosting,functions" } else { "hosting" }
if ($Functions) { Write-Warn "Including functions - ensure GCP service account exists" }

try {
    & firebase deploy --only $target
    Write-Ok "Deploy complete"
} catch {
    Write-Fail "Deploy failed: $_"
    exit 1
}

Write-Host ""
Write-Host "+--------------------------------------------------+" -ForegroundColor Green
Write-Host "|  Deploy Successful                               |" -ForegroundColor Green
Write-Host "+--------------------------------------------------+" -ForegroundColor Green
Write-Host "  App:    https://traffic-impact-assessment.web.app" -ForegroundColor White
Write-Host "  Admin:  https://traffic-impact-assessment.web.app/admin.html" -ForegroundColor White
Write-Host ""
