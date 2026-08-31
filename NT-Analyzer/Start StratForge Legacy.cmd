@echo off
chcp 65001 >nul
title StratForge Legacy Viewer - READ ONLY
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\start-legacy-viewer.ps1"
exit /b %ERRORLEVEL%
