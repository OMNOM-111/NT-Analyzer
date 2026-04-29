@echo off
setlocal
cd /d "%~dp0"
echo [NT-Analyzer] Phase B: check bridge status
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\check-phase-a-status.ps1"
echo.
echo Exit code: %ERRORLEVEL%
echo.
pause
