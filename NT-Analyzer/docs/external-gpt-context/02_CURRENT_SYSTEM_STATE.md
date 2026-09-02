# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-09-01T00:00:00Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Development branch implementation SHA: `a2cc5e72a610d22605a1af0aaacfcb03341456d5` (PR #270; not deployed)
- Verified deployed artifact Git SHA: `8f42158661e8247832c90bea8fc4d9f0071e647b`
- Current Production version/build/artifact when known: `0.10.0-beta.87`; `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; exact hashes are in the beta.87 changelog
- Current live release: `0.10.0-beta.87`, accepted Canary and Production
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL

## Evidence modes

- Repository evidence: legacy isolation PR #254 and Telegram URL-flow PR #255
  merged with mandatory CI GREEN on `main`.
- Development evidence: isolated branch `codex/community-social-network`,
  implementation `a2cc5e72a610d22605a1af0aaacfcb03341456d5` in PR #270;
  full regression is `2501 passed, 35 skipped`.
- Operational evidence: Release Center closeout, server symlinks and read-only
  Production audit/acceptance evidence in the current handoff.
- Canonical live release snapshot:
  [2026-08-31-beta85-forward-only-promotion.md](../changelog/2026-08-31-beta85-forward-only-promotion.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` | One canonical owner UUID is preserved across isolated environments; Telegram QR/one-tap confirmation uses the shared environment-routed bot flow. Post-revoke Google OAuth and Resend smoke passed on Canary and Production | Platform secrets have a canonical external storage contract; three older platform secrets still legally remain in `production-app.env` until separately migrated |
| Legacy UI / Telegram Mini App | `DEPRECATED` | Merged main serves Aurora only; legacy UI, Mini App, remote-access and tunnel routes fail with HTTP 410. Classic assets are available only in a separate localhost read-only Legacy Viewer. Telegram `/start` uses a normal URL button | beta.87 is live in Canary and Production; historical snapshots remain until owner review |
| User entry and trial access | `BETA` | Anonymous preview access is removed. A verified new account receives one full seven-day product trial; owner extension records actor, reason and before/after history | Product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | A versioned release/change record is visible with title, summary, PRs, SHA, build/artifact, stage, checks, duration and environment identity. Production approval/promotion fails closed without title, summary, source SHA and verification PASS | beta.87 acceptance is recorded; any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Legacy-isolation full regression passed `2430 passed, 34 skipped`; live data roots are excluded from test fixtures | real-PostgreSQL groups require their explicit test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was not changed by PR #254/#255 or the beta.86 release-record work | cross-user owner-feed redistribution remains `EXTERNAL BLOCKED` without written authority |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | Production Connector on VMNINJA is `0.4.2-dev.20`; SERVER BACKTEST, cancel state machine, device catalog, account snapshot and Connector LIVE/GRACE/OFFLINE presentation are accepted | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material |
| Production worker queue | `AVAILABLE` | Eleven worker slots remain 4/4/2/1; empty workers use adaptive jittered backoff and one 30-second stale sweeper. Later auth hot-spot work reduced `/api/auth/status` latency but did not claim CPU improvement outside noise | DB tx/s still lacks a safe first-class diagnostics path |
| Community / SF Chat | `BETA` in Development | Isolated branch has real profiles/privacy/social feed/search/follows/interactions, Channels compatibility, moderation/soft delete, server-attested Demo/Backtest result posts and one human SF Chat store shared by Community profiles and the global launcher. Existing AI Orchestrator storage remains authoritative behind the same SF Chat shell. PostgreSQL documents fail closed and migrations `0020`/`0021` add allowlist plus FK/index/FORCE-RLS mirrors | Not present in the deployed artifact. Strategy/Chart/Live object adapters, credentialed PostgreSQL acceptance, manual visual acceptance, PR #270 CI/merge and Canary/Production remain separate gates |
| Documents | `BETA` | Current handoff and Context Pack identify beta.87 as live; hidden Markdown amendment blocks are removed and AI provenance is infrastructure-only or absent | beta.87 exact operational identity is recorded in its changelog closeout |
| Legal | `AVAILABLE` | One official onboarding agreement `2026-08-30-v2` is the sole versioned clickwrap; related official policies are readable informational documents; owner configuration is absent from both document API namespaces | Live Trading remains unavailable pending separate release and legal requirements |

## Current operational identity

| Environment | Version | Git SHA | Build ID | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- | --- |
| Canary | `0.10.0-beta.87` | `8f42158661e8247832c90bea8fc4d9f0071e647b` | `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z` | same accepted beta.87 artifact | accepted / ready |
| Production | `0.10.0-beta.87` | same | same | same | live / ready |

Both environments run the same accepted beta.87 immutable artifact
`art_9ce9dbcb9a7a4fee9df6a54d40f29806`, promoted to Production without a
rebuild. The exact archive and manifest SHA256 are recorded in the canonical
beta.87 changelog closeout.

## Deprecated current-state claims

- beta.29-beta.78 release identities are history, not current live state.
- The target Production installation is no longer offline or blocked by
  `sf_connector_installations_workspace_id_fkey`.
- Earlier draft legal labels are obsolete; the current package is official product documentation.
- A StratForge product trial is not a provider/exchange redistribution grant.
