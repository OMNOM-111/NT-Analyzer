@echo off
:: Double-click launcher for the full AI Strategy Lab stack.
:: Starts/checks NinjaTrader, LM Studio, required local models, backend + AI UI.
chcp 65001 >nul
title NT-Analyzer AI Lab
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\start-ai-lab.ps1"
exit /b
