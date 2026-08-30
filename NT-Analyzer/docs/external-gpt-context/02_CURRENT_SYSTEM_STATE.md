# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-30T02:05:00Z
- Verified against Git SHA: 1279645e48e32000978364b38fb20d3dcd303843
- Verified deployed artifact Git SHA: `1a1d54aa728d487203bb8342ecf142752610f4cd`
- Current Production version/build/artifact when known: `0.10.0-beta.79`; `sf-0.10.0-beta.79-1a1d54aa728d-20260829T234541Z`; live release dir `0.10.0-beta.79-1a1d54aa728d`
- Current live release: `0.10.0-beta.79`, accepted Canary and Production
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL

## Evidence modes

- Repository evidence: merged beta.70-beta.79 closeout PRs through #230 with
  mandatory CI GREEN on current `main`.
- Operational evidence: Release Center closeout, server symlinks and read-only
  Production audit/acceptance evidence in the current handoff.
- Canonical release snapshot:
  [2026-08-29-beta79-secret-management-and-cancel-closeout.md](../changelog/2026-08-29-beta79-secret-management-and-cancel-closeout.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` | One canonical owner UUID is preserved across isolated environments; Telegram QR/one-tap confirmation uses the shared environment-routed bot flow. Post-revoke Google OAuth and Resend smoke passed on Canary and Production | Platform secrets have a canonical external storage contract; three older platform secrets still legally remain in `production-app.env` until separately migrated |
| User entry and trial access | `BETA` | Anonymous preview access is removed. A verified new account receives one full seven-day product trial; owner extension records actor, reason and before/after history | Product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | Development creates one signed immutable artifact, Canary records acceptance and Production promotes the same artifact through the server-authoritative control plane | any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Full beta.79 closeout regression passed `2327 passed, 32 skipped, 0 failed`; live data roots are excluded from test fixtures | real-PostgreSQL groups require their explicit test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was preserved through beta.79 | cross-user owner-feed redistribution remains `EXTERNAL BLOCKED` without written authority |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | Production Connector on VMNINJA is `0.4.2-dev.20`; SERVER BACKTEST, cancel state machine, device catalog, account snapshot and Connector LIVE/GRACE/OFFLINE presentation are accepted | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material |
| Production worker queue | `AVAILABLE` | Eleven worker slots remain 4/4/2/1; empty workers use adaptive jittered backoff and one 30-second stale sweeper. Later auth hot-spot work reduced `/api/auth/status` latency but did not claim CPU improvement outside noise | DB tx/s still lacks a safe first-class diagnostics path |
| Documents | `BETA` | Current handoff and Context Pack reflect beta.79; hidden Markdown amendment blocks are removed and AI provenance is infrastructure-only or absent | the new legal package remains a Development change until immutable release promotion |
| Legal | `AVAILABLE` | One official onboarding agreement `2026-08-30-v2` is the sole versioned clickwrap; related official policies are readable informational documents; owner configuration is absent from both document API namespaces | Live Trading remains unavailable pending separate release and legal requirements |

## Current operational identity

| Environment | Version | Git SHA | Build ID | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- | --- |
| Canary | `0.10.0-beta.79` | `1a1d54aa728d487203bb8342ecf142752610f4cd` | `sf-0.10.0-beta.79-1a1d54aa728d-20260829T234541Z` | current runtime artifact in live release dir | accepted / ready |
| Production | `0.10.0-beta.79` | same | same | same | live / ready |

Both environments use release-directory suffix
`0.10.0-beta.79-1a1d54aa728d`; previous/rollback is
`0.10.0-beta.78-bb50168cbe79`.

## Deprecated current-state claims

- beta.29-beta.78 release identities are history, not current live state.
- The target Production installation is no longer offline or blocked by
  `sf_connector_installations_workspace_id_fkey`.
- Earlier draft legal labels are obsolete; the current package is official product documentation.
- A StratForge product trial is not a provider/exchange redistribution grant.
