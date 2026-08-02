@echo off
:: Double-click launcher: starts backend + opens browser. Does not start NinjaTrader.
:: If backend is already running, just opens the browser tab.
chcp 65001 >nul
title StratForge AI
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\start.ps1"
:: Exit immediately – no "Press any key" needed since the launcher handles everything.
exit /b
