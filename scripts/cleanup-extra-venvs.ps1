param(
  [switch]$Apply
)

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$keepName = 'venv'
$candidateNames = @('.venv', 'venv-1', '.venv-1', '.env', 'env', '.virtualenv', 'virtualenv')

$foldersToRemove = @()
foreach ($name in $candidateNames) {
  if (Test-Path $name -PathType Container) {
    $foldersToRemove += (Resolve-Path $name).Path
  }
}

if (-not $foldersToRemove.Count) {
  Write-Host '[cleanup-venv] No duplicate environment folders found.'
  Write-Host "[cleanup-venv] Keeping: $keepName"
  exit 0
}

Write-Host "[cleanup-venv] Keeping: $keepName"
Write-Host '[cleanup-venv] Duplicate environment folders detected:'
$foldersToRemove | ForEach-Object { Write-Host " - $_" }

if (-not $Apply) {
  Write-Host ''
  Write-Host '[cleanup-venv] Dry run only. Nothing deleted.'
  Write-Host '[cleanup-venv] Run with -Apply to remove these folders.'
  exit 0
}

foreach ($folder in $foldersToRemove) {
  try {
    Remove-Item -Recurse -Force $folder
    Write-Host "[cleanup-venv] Removed: $folder"
  } catch {
    Write-Error "[cleanup-venv] Failed to remove $folder. $($_.Exception.Message)"
    exit 1
  }
}

Write-Host '[cleanup-venv] Cleanup complete.'
