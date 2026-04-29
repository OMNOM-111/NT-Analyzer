@echo off
setlocal
cd /d "%~dp0"
echo [NT-Analyzer] Phase B: create Variant 1 smoke job
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\enqueue-smoke-job.ps1"
echo.
echo Exit code: %ERRORLEVEL%
echo.
pause
