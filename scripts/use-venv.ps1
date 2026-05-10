param(
  [switch]$InstallRequirements,
  [switch]$RunDatasetUpdate
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot 'venv'
$legacyVenvPath = Join-Path $repoRoot '.venv'
$pythonExe = Join-Path $venvPath 'Scripts\python.exe'
$pipExe = Join-Path $venvPath 'Scripts\pip.exe'
$activateScript = Join-Path $venvPath 'Scripts\Activate.ps1'
$requirementsFile = Join-Path $repoRoot 'requirements.txt'
$datasetUpdater = Join-Path $repoRoot 'scripts\check_and_update_datasets.py'

$pythonCandidates = @()
$pythonFromPath = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source
if ($pythonFromPath) {
  $pythonCandidates += $pythonFromPath
}

$pythonInstallRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
if (Test-Path $pythonInstallRoot -PathType Container) {
  $pythonCandidates += Get-ChildItem $pythonInstallRoot -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName 'python.exe' }
}

$resolvedPython = $pythonCandidates |
  Where-Object { (Test-Path $_ -PathType Leaf) -and ($_ -notlike '*WindowsApps*') } |
  Select-Object -First 1

if ((-not (Test-Path $venvPath -PathType Container)) -and (Test-Path $legacyVenvPath -PathType Container)) {
  Write-Host '[venv] Migrating legacy .venv to venv...'
  Rename-Item $legacyVenvPath $venvPath
}

if (-not (Test-Path $pythonExe)) {
  Write-Host '[venv] venv not found. Creating a reusable virtual environment...'
  if (-not $resolvedPython) {
    throw '[venv] Python interpreter not found. Install Python 3.10+ and retry.'
  }
  & $resolvedPython -m venv $venvPath
  if ($LASTEXITCODE -ne 0) {
    throw '[venv] Failed to create venv'
  }
}

if ($InstallRequirements) {
  if (Test-Path $requirementsFile) {
    Write-Host '[venv] Installing requirements into venv...'
    & $pipExe install -r $requirementsFile
    if ($LASTEXITCODE -ne 0) {
      throw '[venv] Failed to install requirements'
    }
  } else {
    Write-Warning '[venv] requirements.txt not found; skipping package install.'
  }
}

if ($RunDatasetUpdate) {
  if (Test-Path $datasetUpdater) {
    Write-Host '[venv] Running dataset update script...'
    & $pythonExe $datasetUpdater
    if ($LASTEXITCODE -ne 0) {
      throw '[venv] Dataset update script failed'
    }
  } else {
    Write-Warning '[venv] dataset updater script not found; skipping.'
  }
}

Write-Host ''
Write-Host '[venv] Ready. Reusing venv at:' $venvPath
Write-Host '[venv] To activate in this shell run:'
Write-Host "        & '$activateScript'"
