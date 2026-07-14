@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install-vitek-background.ps1"
if errorlevel 1 (
  echo.
  echo Vitek installation failed.
  pause
  exit /b 1
)
echo.
echo Vitek background monitoring is installed.
pause
