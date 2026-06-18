@echo off
title Crompton TIA - Firebase Deploy
cd /d "%~dp0"

echo.
echo +--------------------------------------------------+
echo ^|  Crompton TIA -- Firebase Deploy                 ^|
echo +--------------------------------------------------+
echo.

REM --- Pre-flight: Firebase CLI ---
where firebase >nul 2>&1
if errorlevel 1 (
    echo   FAIL  Firebase CLI not found.
    echo         Run:  npm install -g firebase-tools
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('firebase --version 2^>^&1') do set FB_VER=%%v
echo   OK    Firebase CLI: %FB_VER%

REM --- Pre-flight: required files ---
set MISSING=
for %%f in (firebase.json .firebaserc index.html app.js user-sync.js firebase-config.js dataset_manifest.json) do (
    if not exist "%%f" set MISSING=%%f !MISSING!
)
if defined MISSING (
    echo   FAIL  Missing files: %MISSING%
    echo.
    pause
    exit /b 1
)
echo   OK    All required files present

REM --- File count ---
set /a HTML=0
set /a JS=0
set /a GEO=0
for %%f in (*.html)       do set /a HTML+=1
for %%f in (*.js)         do set /a JS+=1
for /r %%f in (*.geojson) do set /a GEO+=1
echo   OK    HTML: %HTML%  JS: %JS%  GeoJSON: %GEO% (incl. datasets/)

REM --- Deploy ---
echo.
echo >> Syncing report service URL and deploying to Firebase Hosting...
echo.
call powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" %*
if errorlevel 1 (
    echo.
    echo   FAIL  Deploy failed.
    echo.
    pause
    exit /b 1
)

echo.
echo +--------------------------------------------------+
echo ^|  Deploy Successful                               ^|
echo +--------------------------------------------------+
echo   App:    https://traffic-impact-assessment.web.app
echo   Admin:  https://traffic-impact-assessment.web.app/admin.html
echo.
pause
