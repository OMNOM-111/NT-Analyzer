# Legacy Viewer

Status: `AVAILABLE` as a temporary local historical-report viewer.

## Boundary

The current StratForge server serves Aurora only. Classic UI and the retired
Telegram Mini App are not current-product fallbacks. `/ui/legacy/*`, Mini App
registration, remote-access and tunnel routes return HTTP 410.

Legacy Viewer is a separate process:

- loopback only (`127.0.0.1`, port 8876 by default);
- frozen static root at `legacy_viewer/static/`;
- separate cookie, browser-storage, signing-key, queue, database and data root;
- no Telegram bot, tunnel, current workers, automation, release or trading;
- POST and DELETE are rejected with HTTP 405;
- owner/admin/auth/Connector/Telegram/worker/WebSocket route families are blocked.

## Start

Run `Start StratForge Legacy.cmd`. The PowerShell launcher creates an isolated
snapshot under `%LOCALAPPDATA%\StratForge\LegacyViewer\data` on first launch,
then starts the viewer. Source data is copied without mirror/delete semantics;
the current data root is never used as the viewer's writable root.

For a controlled check without opening a browser:

```powershell
.\start-legacy-viewer.ps1 -NoBrowser
```

Close the console with Ctrl+C. The viewer has no background child services and
must leave no listener or `app.legacy_viewer` process after exit.

## Retirement

Keep historical report/audit data until owner review is complete. Final removal
of viewer assets or snapshots is a separate destructive action requiring an
explicit owner decision.
