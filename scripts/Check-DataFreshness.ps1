<#
.SYNOPSIS
    Check whether any upstream government traffic-data source has published newer
    data than what we last built from, then (optionally) run the local quality audit.

.DESCRIPTION
    Thin Windows wrapper around:
        scripts/check_upstream_freshness.py   (are the SOURCES updated?)
        scripts/audit_datasets.py             (are our LOCAL datasets sane?)

    Double-click this file, or run it from PowerShell:
        ./scripts/Check-DataFreshness.ps1            # freshness + audit
        ./scripts/Check-DataFreshness.ps1 -NoAudit   # freshness only
        ./scripts/Check-DataFreshness.ps1 nsw_2026 logan   # subset

.NOTES
    Exit code 3 from the freshness check means "new data available upstream".
#>

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Datasets,
    [switch]$NoAudit
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
$env:PYTHONIOENCODING = 'utf-8'

# Resolve a python launcher (py -3 preferred on Windows, else python).
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pyExe = 'py'; $pyPrefix = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pyExe = 'python'; $pyPrefix = @()
} else {
    throw 'Python not found on PATH. Install Python 3 or add it to PATH.'
}

Write-Host "== Upstream freshness check ==" -ForegroundColor Cyan
& $pyExe @pyPrefix 'scripts/check_upstream_freshness.py' @Datasets
$freshExit = $LASTEXITCODE

if (-not $NoAudit) {
    Write-Host "`n== Local dataset quality audit ==" -ForegroundColor Cyan
    & $pyExe @pyPrefix 'scripts/audit_datasets.py'
}

if ($freshExit -eq 3) {
    Write-Host "`nUpstream changes detected -- see 'ACTION NEEDED' above." -ForegroundColor Yellow
} elseif ($freshExit -eq 4) {
    Write-Host "`nAll sources were unreachable -- check your network/VPN." -ForegroundColor Red
} else {
    Write-Host "`nAll sources up to date." -ForegroundColor Green
}

exit $freshExit
