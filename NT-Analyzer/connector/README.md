# StratForge Connector release package

Build a locally signed development release:

```powershell
python tools\build_connector_release.py --version 0.4.0-dev.1 --channel stable
```

The output under `.artifacts/connector/releases/<version>` contains one ZIP,
its SHA-256 sidecar, an extracted verified bundle and a build report. The bundle
contains the Release AddOn, standalone .NET Framework Setup, compatibility
matrix, strict config template, signed manifest and every-file SHA-256.

Development signing keys are generated once and stored only in a DPAPI-protected
ignored artifact. A Production build is fail-closed and requires an external
P-256 release key plus an Authenticode certificate and `signtool`; it cannot
silently fall back to the development trust tier.

Setup supports GUI installation and non-interactive `--install`, `--repair`,
`--uninstall`, `--verify`, `--detect` and `--diagnostics`. It refuses to modify a
loaded AddOn while NinjaTrader is running, backs up the previous DLL/config,
uses atomic replacement and preserves local keys/state on uninstall.
