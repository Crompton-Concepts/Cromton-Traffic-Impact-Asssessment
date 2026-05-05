# Sanitize-Git.ps1 - Deep clean desktop.ini and protect .git folder
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$repoRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
    Write-Error "Not inside a Git repository."
    exit 1
}

Write-Host "--- Sanitizing Repository at $repoRoot ---" -ForegroundColor Cyan

# 1. Remove all desktop.ini files recursively in the project (including hidden ones)
Write-Host "Searching for all desktop.ini files..."
$allDesktopInis = Get-ChildItem -Path $repoRoot -Recurse -Force -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(?i)desktop\.ini$' }

if ($allDesktopInis) {
    Write-Host "Removing $($allDesktopInis.Count) desktop.ini file(s):" -ForegroundColor Yellow
    $allDesktopInis | ForEach-Object {
        Write-Host " - $($_.FullName)"
        Remove-Item -LiteralPath $_.FullName -Force
    }
} else {
    Write-Host "No desktop.ini files found." -ForegroundColor Green
}

# 2. Ensure they are removed from the Git index (if any were tracked)
Write-Host "Ensuring desktop.ini is removed from Git index..."
git rm --cached -r "**/*desktop.ini" 2>$null
git rm --cached "desktop.ini" 2>$null

# 3. Protect the .git folder
$gitDir = Join-Path $repoRoot ".git"
if (Test-Path $gitDir) {
    Write-Host "Protecting .git folder (setting System+Hidden attributes)..."
    # Setting +S +H (System and Hidden) makes Windows treat it as a critical system folder,
    # which often prevents automated tool interference like desktop.ini creation.
    attrib +s +h $gitDir /d
    
    # Also try to protect subfolders in .git
    Get-ChildItem -Path $gitDir -Directory -Force | ForEach-Object {
        attrib +s +h $_.FullName /d
    }
}

# 4. Verify Git health
Write-Host "Verifying Git health..."
$healthCheck = git show-ref 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "Git repository is healthy." -ForegroundColor Green
} else {
    Write-Warning "Git health check failed. You may need to manual fix refs."
    Write-Host $healthCheck
}

Write-Host "--- Sanitization Complete ---" -ForegroundColor Cyan
