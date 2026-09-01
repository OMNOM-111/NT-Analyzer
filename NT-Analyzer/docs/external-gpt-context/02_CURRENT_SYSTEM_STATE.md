# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-31T00:00:00Z
- Verified against Git SHA: dd0bdd0164713a88c3e87b4514637e848b831a8b
- Verified deployed artifact Git SHA: `b923e7b2b4e034c4f890e89b33992d469c84b779`
- Current Production version/build/artifact when known: `0.10.0-beta.85`; `sf-0.10.0-beta.85-b923e7b2b4e0-20260831T173711Z`; exact hashes are in the beta.85 changelog
- Current live release: `0.10.0-beta.85`, accepted Canary and Production
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL

## Evidence modes

- Repository evidence: legacy isolation PR #254 and Telegram URL-flow PR #255
  merged with mandatory CI GREEN on `main`.
- Operational evidence: Release Center closeout, server symlinks and read-only
  Production audit/acceptance evidence in the current handoff.
- Canonical live release snapshot:
  [2026-08-31-beta85-forward-only-promotion.md](../changelog/2026-08-31-beta85-forward-only-promotion.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` | One canonical owner UUID is preserved across isolated environments; Telegram QR/one-tap confirmation uses the shared environment-routed bot flow. Post-revoke Google OAuth and Resend smoke passed on Canary and Production | Platform secrets have a canonical external storage contract; three older platform secrets still legally remain in `production-app.env` until separately migrated |
| Legacy UI / Telegram Mini App | `DEPRECATED` | Merged main serves Aurora only; legacy UI, Mini App, remote-access and tunnel routes fail with HTTP 410. Classic assets are available only in a separate localhost read-only Legacy Viewer. Telegram `/start` uses a normal URL button | beta.86 Canary/Production promotion pending; historical snapshots remain until owner review |
| User entry and trial access | `BETA` | Anonymous preview access is removed. A verified new account receives one full seven-day product trial; owner extension records actor, reason and before/after history | Product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | A versioned release/change record is visible with title, summary, PRs, SHA, build/artifact, stage, checks, duration and environment identity. Production approval/promotion fails closed without title, summary, source SHA and verification PASS | beta.86 live acceptance pending; any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Legacy-isolation full regression passed `2430 passed, 34 skipped`; live data roots are excluded from test fixtures | real-PostgreSQL groups require their explicit test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was not changed by PR #254/#255 or the beta.86 release-record work | cross-user owner-feed redistribution remains `EXTERNAL BLOCKED` without written authority |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | Production Connector on VMNINJA is `0.4.2-dev.20`; SERVER BACKTEST, cancel state machine, device catalog, account snapshot and Connector LIVE/GRACE/OFFLINE presentation are accepted | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material |
| Production worker queue | `AVAILABLE` | Eleven worker slots remain 4/4/2/1; empty workers use adaptive jittered backoff and one 30-second stale sweeper. Later auth hot-spot work reduced `/api/auth/status` latency but did not claim CPU improvement outside noise | DB tx/s still lacks a safe first-class diagnostics path |
| Documents | `BETA` | Current handoff and Context Pack identify beta.85 as live and beta.86 as pending; hidden Markdown amendment blocks are removed and AI provenance is infrastructure-only or absent | beta.86 exact operational identity is recorded only after Canary/Production closeout |
| Legal | `AVAILABLE` | One official onboarding agreement `2026-08-30-v2` is the sole versioned clickwrap; related official policies are readable informational documents; owner configuration is absent from both document API namespaces | Live Trading remains unavailable pending separate release and legal requirements |

## Current operational identity

| Environment | Version | Git SHA | Build ID | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- | --- |
| Canary | `0.10.0-beta.85` | `b923e7b2b4e034c4f890e89b33992d469c84b779` | `sf-0.10.0-beta.85-b923e7b2b4e0-20260831T173711Z` | same accepted beta.85 artifact | accepted / ready |
| Production | `0.10.0-beta.85` | same | same | same | live / ready |

Both environments run the same accepted beta.85 immutable artifact. The exact
archive SHA256 is recorded in the canonical beta.85 changelog; beta.86 has not
yet changed either live environment.

## Deprecated current-state claims

- beta.29-beta.78 release identities are history, not current live state.
- The target Production installation is no longer offline or blocked by
  `sf_connector_installations_workspace_id_fkey`.
- Earlier draft legal labels are obsolete; the current package is official product documentation.
- A StratForge product trial is not a provider/exchange redistribution grant.
