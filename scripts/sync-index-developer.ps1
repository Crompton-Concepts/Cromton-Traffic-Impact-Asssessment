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

# Keep developer title distinct while mirroring baseline content from index.html.
$outputContent = [regex]::Replace(
  $outputContent,
  '(?is)<title>.*?</title>',
  '<title>Traffic Impact Assessment - Developer</title>',
  1
)

# Developer build should keep beta features visible.
$outputContent = [regex]::Replace(
  $outputContent,
  '(?is)/\*\s*Production build: beta panel and formula trace are developer-only\.\s*\*/\s*#optionalFeaturesSection,\s*#betaFeaturesCard,\s*#formulaTraceSection\s*\{\s*display:\s*none\s*!important;\s*\}',
  ''
)

# Inject developer auth bypass block.
# In the production build (index.html) the login gate is active. In the developer
# build we bypass it entirely: the auth session key is pre-set AND the blur/gate
# are synchronously cleared so a failing async data-load can never leave the UI
# permanently blurred.
$devBypassMarker  = '/* DEV-BYPASS-BLOCK */'
$devBypassBlock   = @'
  /* DEV-BYPASS-BLOCK */
  // Developer build only: bypass login gate entirely.
  // Pre-set auth session key and synchronously remove the app-locked blur so
  // the UI is immediately usable regardless of async data-loading failures.
  sessionStorage.setItem(AUTH_SESSION_KEY, 'true');
  (function() {
    document.body.classList.remove('app-locked');
    var _g = document.getElementById('loginGate');
    if (_g) _g.style.display = 'none';
  })();

'@
$setupLoginGateCall = '  setupLoginGate();'
# Only inject if the bypass is not already present (idempotent).
if ($outputContent -notmatch [regex]::Escape($devBypassMarker)) {
  $outputContent = $outputContent.Replace(
    $setupLoginGateCall,
    $devBypassBlock + $setupLoginGateCall
  )
}

$existingOutput = if (Test-Path $developerPath) { Get-Content -Path $developerPath -Raw } else { '' }

if ($existingOutput -ne $outputContent) {
  Set-Content -Path $developerPath -Value $outputContent -Encoding UTF8
  if (-not $Quiet) {
    Write-Host 'Synced index_developer.html from index.html (developer title preserved).'
  }
} elseif (-not $Quiet) {
  Write-Host 'index_developer.html is already in sync with index.html.'
}
