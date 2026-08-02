@echo off
title StratForge AI - SERVER
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-server.ps1"
if errorlevel 1 pause
