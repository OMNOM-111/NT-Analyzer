@echo off
:: Wrapper around `py -3 -m app.cli` so users can run `nta create-job ...`
:: from anywhere inside NT-Analyzer.
setlocal
cd /d "%~dp0\.."
py -3 -m app.cli %*
