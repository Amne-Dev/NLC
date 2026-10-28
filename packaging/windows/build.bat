@echo off
setlocal
cd /d "%~dp0..\.."

echo ========================================================
echo   Building Ny-Luna Core v4.0.0 (Rust UI + Python Agent)
echo ========================================================

python packaging\windows\build_installers.py --all %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [-] Build failed with exit code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

if not exist installer mkdir installer
if exist dist\installers\NLCSetup.exe copy /Y dist\installers\NLCSetup.exe installer\NLCSetup.exe >nul
if exist dist\installers\NLCSetup-Offline.exe copy /Y dist\installers\NLCSetup-Offline.exe installer\NLCSetup-Offline.exe >nul

echo.
echo ========================================================
echo   Build Complete!
echo   Installers available in:
echo     - dist\installers\NLCSetup.exe (Web / Update Gateway)
echo     - dist\installers\NLCSetup-Offline.exe (Offline)
echo ========================================================
pause
