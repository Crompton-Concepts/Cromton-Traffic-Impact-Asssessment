param(
  [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$indexPath = Join-Path $repoRoot 'index.html'
$developerPath = Join-Path $repoRoot 'index_developer.html'

if (-not (Test-Path $indexPath)) {
  throw "index.html not found at $indexPath"
}

$indexContent = Get-Content -Path $indexPath -Raw
$outputContent = $indexContent

# Keep developer page title distinct while mirroring logic/content from index.html.
$outputContent = [regex]::Replace(
  $outputContent,
  '(?is)<title>.*?</title>',
  '<title>Traffic Impact Assessment - Developer</title>',
  1
)

$existingOutput = if (Test-Path $developerPath) { Get-Content -Path $developerPath -Raw } else { '' }

if ($existingOutput -ne $outputContent) {
  Set-Content -Path $developerPath -Value $outputContent -Encoding UTF8
  if (-not $Quiet) {
    Write-Host 'Synced index_developer.html from index.html (developer title preserved).'
  }
} elseif (-not $Quiet) {
  Write-Host 'index_developer.html is already in sync.'
}
