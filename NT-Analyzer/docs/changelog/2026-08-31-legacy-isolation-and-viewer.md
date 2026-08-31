# Legacy isolation and viewer - 2026-08-31

Development status: implementation complete; no Canary/Production deployment.

- Aurora is the only current static UI and has no link or transport for classic
  UI or Telegram Mini App.
- Retired legacy UI, Mini App registration, remote-access and tunnel surfaces
  fail closed with HTTP 410 before normal route authorization.
- Classic assets moved to `legacy_viewer/static/` and run only through the
  localhost-only read-only Legacy Viewer with an isolated data snapshot.
- The Mini App tunnel launcher was removed. Current Telegram login, identity,
  bot and notifications were preserved.
- Stale `remote_enabled` data no longer controls current desktop authentication;
  desktop auth remains fail-closed by default.
- No user, historical report, audit record or Production state was deleted.
- Market data, Connector and trading execution code was not changed.
