@echo off
setlocal
set SRC=%~dp0bridge\bin\Release\NTAnalyzerBridge.dll
set DST=%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.dll

if not exist "%SRC%" (
  echo [deploy] BUILD MISSING: %SRC%
  echo [deploy] Run:  dotnet build bridge\NTAnalyzerBridge.csproj -c Release
  exit /b 1
)

echo [deploy] SRC : %SRC%
echo [deploy] DST : %DST%
echo.

:waitloop
tasklist /FI "IMAGENAME eq NinjaTrader.exe" 2>nul | find /I "NinjaTrader.exe" >nul
if %ERRORLEVEL%==0 (
  echo [deploy] NinjaTrader is RUNNING - close it, then press any key to retry...
  pause >nul
  goto waitloop
)

copy /Y "%SRC%" "%DST%"
if errorlevel 1 (
  echo [deploy] COPY FAILED.
  exit /b 1
)
echo.
echo [deploy] OK. Now start NinjaTrader. After it loads the AddOn, bridge will
echo [deploy] rewrite data\catalog\templates.json with supported=true for all
echo [deploy] commission templates.
endlocal
