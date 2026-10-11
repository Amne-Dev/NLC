@echo off
echo Building Agent...
pyinstaller --clean agent.spec
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo Building Patch Runner...
pyinstaller --clean patch_runner.spec
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo Building Launcher...
pyinstaller --clean alt.spec
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo Building Custom Installer...
pyinstaller --clean installer_app.spec
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

if not exist installer mkdir installer
copy /Y dist\NLCSetup.exe installer\NLCSetup.exe >nul

echo.
echo Build Complete.
echo Custom installer created at installer\NLCSetup.exe
pause
