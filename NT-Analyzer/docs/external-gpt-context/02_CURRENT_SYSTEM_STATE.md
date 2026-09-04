# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-09-04T19:05:50Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Unified Local implementation SHA: `42a99a85f164f69c6ddd0edf46859ef005e787e2`
- Unified Local branch: `integration/stratforge-unified-local` (PR #280), version `0.10.0-beta.96`, not deployed
- Development branch implementation SHA: `27b4de3d65eb4e1d753302b90fec45c90a51765a` (PR #270; final SF Chat messenger presentation pass; not deployed)
- Device-confirmation Development implementation SHA: `19e0f43a35bee5a2e396538962e8f24e92bed6ef` (PR #278; isolated branch; not deployed)
- Verified deployed artifact Git SHA: `8f42158661e8247832c90bea8fc4d9f0071e647b`
- Current Production version/build/artifact when known: `0.10.0-beta.87`; `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; exact hashes are in the beta.87 changelog
- Current live release: `0.10.0-beta.87`, accepted Canary and Production
- Scope: Current factual subsystem snapshot: Unified Local Development plus the separately identified live Production baseline
- Status: PARTIAL

## Evidence modes

- Repository evidence: legacy isolation PR #254 and Telegram URL-flow PR #255
  merged with mandatory CI GREEN on `main`.
- Development evidence: isolated branch `codex/community-social-network`,
  implementation `27b4de3d65eb4e1d753302b90fec45c90a51765a` in PR #270;
  full regression is `2503 passed, 35 skipped`; isolated browser QA covers
  desktop, tablet and mobile geometry without document-level overflow, with
  independent center/wall scrolling and no console warnings/errors.
- Device-confirmation Development evidence: isolated branch
  `codex/device-confirmation-trusted-access`; automated verification is tracked
  in its canonical changelog. It does not modify Community or SF Chat.
- Unified Local evidence: auth/onboarding, Device Confirmation, SF Social,
  SF Chat and isolated Owner Preview coexist in `0.10.0-beta.96`. Contextual
  Preview registration verification is `173 passed` focused and `2680 passed,
  44 skipped` full, plus a manual browser walkthrough of Telegram, Google,
  e-mail/OTP, QR, permanent/session-only trust and Owner Local restore.
- Operational evidence: Release Center closeout, server symlinks and read-only
  Production audit/acceptance evidence in the current handoff.
- Canonical live release snapshot:
  [2026-08-31-beta85-forward-only-promotion.md](../changelog/2026-08-31-beta85-forward-only-promotion.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Auth / owner identity | `BETA` in Unified Local | `0.10.0-beta.96` has one three-step registration contract for Telegram, Google and e-mail, a stable StratForge handle shared by profile/SF Social/SF Chat, final clickwrap consent and the existing shared environment-routed provider architecture. Owner Preview uses the same state transitions with sandbox-only synthetic credentials | Not present in the deployed beta.87 artifact; live real-provider acceptance and immutable Canary/Production promotion remain separate gates |
| Device confirmation / trusted access | `BETA` in Unified Local | Every new unknown human browser/app access starts as a two-minute pending session. The first freshly authenticated device can choose permanent trust or current-session-only without a redundant second OTP; later unknown clients still use confirmed Telegram or verified e-mail. Machine → Client → Session grouping remains proof-based | Integrated and browser-verified in Local beta.96, but not present in deployed beta.87; real-provider acceptance and release promotion remain separate gates |
| Legacy UI / Telegram Mini App | `DEPRECATED` | Merged main serves Aurora only; legacy UI, Mini App, remote-access and tunnel routes fail with HTTP 410. Classic assets are available only in a separate localhost read-only Legacy Viewer. Telegram `/start` uses a normal URL button | beta.87 is live in Canary and Production; historical snapshots remain until owner review |
| User entry and trial access | `BETA` in Unified Local | Anonymous product access is removed. Every verified account receives the same full product with a default five-hour active-use starting grant; idle time is not charged. Profile/security remain available after exhaustion | Not present in deployed beta.87; product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | A versioned release/change record is visible with title, summary, PRs, SHA, build/artifact, stage, checks, duration and environment identity. Production approval/promotion fails closed without title, summary, source SHA and verification PASS | beta.87 acceptance is recorded; any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Unified Local contextual Preview regression passed `2680 passed, 44 skipped`; live owner data stayed outside the sandbox and synthetic endpoints return `404` in ordinary Local | real-PostgreSQL groups require their explicit test DSNs |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was not changed by PR #254/#255 or the beta.86 release-record work | cross-user owner-feed redistribution remains `EXTERNAL BLOCKED` without written authority |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | Production Connector on VMNINJA is `0.4.2-dev.20`; SERVER BACKTEST, cancel state machine, device catalog, account snapshot and Connector LIVE/GRACE/OFFLINE presentation are accepted | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material |
| Production worker queue | `AVAILABLE` | Eleven worker slots remain 4/4/2/1; empty workers use adaptive jittered backoff and one 30-second stale sweeper. Later auth hot-spot work reduced `/api/auth/status` latency but did not claim CPU improvement outside noise | DB tx/s still lacks a safe first-class diagnostics path |
| SF Social / SF Chat | `BETA` in Unified Local | The former Community tab is the integrated SF Social network: profiles, privacy/social graph, feed/search/interactions, moderation and server-attested Demo/Backtest posts. SF Chat is the single human/AI conversation surface and keeps existing Orchestrator storage/routing. Registration handle and identity are shared across auth, profile, SF Social and SF Chat | Not present in deployed beta.87. Strategy/Chart/Live object adapters, credentialed PostgreSQL acceptance, owner-approved merge and Canary/Production remain separate gates |
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
