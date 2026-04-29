@echo off
setlocal
cd /d "%~dp0"
echo [NT-Analyzer] Phase B: install bridge DLL and config
echo.
echo IMPORTANT: close NinjaTrader completely before running this.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install-bridge.ps1"
echo.
echo Exit code: %ERRORLEVEL%
echo.
pause
