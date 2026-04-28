Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
  throw 'Not inside a Git repository.'
}

$refsPath = Join-Path $repoRoot '.git/refs'
if (-not (Test-Path $refsPath)) {
  throw "Git refs path not found: $refsPath"
}

$badRefFiles = Get-ChildItem -Path $refsPath -Recurse -Force -File |
  Where-Object { $_.Name -match '^(?i)desktop\.ini$' }

if (-not $badRefFiles -or $badRefFiles.Count -eq 0) {
  Write-Host 'No bad desktop.ini ref files found in .git/refs.'
  exit 0
}

Write-Host 'Removing invalid desktop.ini ref files:'
$badRefFiles | ForEach-Object {
  Write-Host (" - " + $_.FullName)
  Remove-Item -LiteralPath $_.FullName -Force
}

# Verify repository references are readable after cleanup.
$null = git show-ref
Write-Host "Cleanup complete. Removed $($badRefFiles.Count) file(s)."
