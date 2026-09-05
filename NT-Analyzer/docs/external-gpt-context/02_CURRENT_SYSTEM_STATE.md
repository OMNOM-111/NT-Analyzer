# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-09-05T04:22:06Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 486db834850d465006a3983d2d83ee809202df60
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Unified Local branch: `integration/stratforge-unified-local` (PR #280), version `0.10.0-beta.96`; not released to Canary/Production
- Active Local 8765: clean detached `agent-world-local-runtime` at `486db834850d465006a3983d2d83ee809202df60`, build `dev-0.10.0-beta.96-486db834850d`, original owner data root, Preview=false
- Agent World branch: `codex/agent-world-owner-preview`, stacked above open PR #281 / #280; integrated model/domain/social delta is dirty, uncommitted and not yet active on 8765
- Verified deployed artifact Git SHA: `8f42158661e8247832c90bea8fc4d9f0071e647b`
- Current Production version/build/artifact when known: `0.10.0-beta.87`; `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; exact hashes are in the beta.87 changelog
- Current live release: `0.10.0-beta.87`, accepted Canary and Production
- Scope: Current factual subsystem snapshot: Unified Local Development plus the separately identified live Production baseline
- Status: PARTIAL

## Evidence modes

- Repository evidence: legacy isolation PR #254 and Telegram URL-flow PR #255
  merged with mandatory CI GREEN on `main`.
- Earlier isolated PR #270/#278 implementation and test snapshots are
  [historical context](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md);
  they are integrated into the accepted Unified Local base.
- Unified Local evidence: auth/onboarding, Device Confirmation, SF Social,
  SF Chat and isolated Owner Preview coexist in `0.10.0-beta.96`. Contextual
  Preview registration verification is `173 passed` focused and `2680 passed,
  44 skipped` full, plus a manual browser walkthrough of Telegram, Google,
  e-mail/OTP, QR, permanent/session-only trust and Owner Local restore.
- Accepted Preview closeout is `4ae766ea0c3258a8bb049644ac2afbba6cb89330`,
  clean and synchronized, PR #280 CI five checks successful. The 44 skipped
  tests are unverified scenarios; this evidence belongs to the baseline.
- Agent World integrated code now includes scoped Personas/models, verified
  model-to-NinjaTrader/Desktop work, independent evaluations, Consensus/Court,
  controlled Memory, projects, manual routine/calendar follow-ups and explicit
  SF Social publication inside the same three-tab AI Center. Existing SF Chat,
  worker, permissions and paid-budget authorities remain in use. This delta is
  implemented but still `IN DEVELOPMENT`, not a finished owner acceptance.
  [Canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) and
  [ADR-0012](../adr/0012-agent-world-integrated-local.md) identify exact scope.
- All ten flags default OFF. Exact Development workspace opt-in through
  `STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES` enables eight reviewed paths:
  read/UI/tasks/evaluation/memory/consensus/Court/social. Router shadow and
  Execution V2 remain OFF. Controlled Preview has its separate four fixture
  flags and rejects real model/domain side effects; browser input enables none.
- The old owner process served dirty beta.93 / `7062f749` because its scheduled
  task still targeted the old checkout. After explicit owner approval, isolated
  copy checks, coherent/cold backups and exact process retirement, Local 8765
  now runs clean `486db834` beta.96 against the original real owner data root.
  This completed Local switch is distinct from activating the newer dirty delta.
  New model/chat/NT/Desktop browser acceptance remains pending that delta's
  tested clean commit and controlled Local activation; no second worker may
  share the owner data root.
- The pre-delivery-repair full delta run passed `3803 passed, 44 skipped`
  in 578.02 s after stale cache-token expectations were corrected. Later focused
  domain gateway checks passed 96 tests. A discovered final-message delivery gap
  is being repaired using the existing worker/inbox without a second provider
  call; final regression after that repair is still pending. Separate actual isolated
  PostgreSQL 17.10 regression passed `41 passed, 0 skipped` against existing
  migrations 1–22, TLS and non-superuser/NOBYPASSRLS roles. This does not provide
  a new Agent World PostgreSQL adapter: domain storage is Development SQLite
  only and fails closed outside Development. See the
  [integrated verification ledger](../changelog/2026-09-05-agent-world-integrated-local.md).

- Operational evidence: Release Center closeout, server symlinks and read-only
  Production audit/acceptance evidence in the current handoff.
- Canonical live release snapshot:
  [2026-08-31-beta85-forward-only-promotion.md](../changelog/2026-08-31-beta85-forward-only-promotion.md).

## Current-only snapshot

| Subsystem | Status | Current fact | Remaining limit |
| --- | --- | --- | --- |
| Agent World | `IN DEVELOPMENT` | Three primary tabs plus domain drawers; dirty integration implements scoped model/application evidence, evaluations, Consensus/Court, Memory, projects, manual follow-ups and two-step SF Social snapshots; clean `486db834` is the older active Local checkpoint | New delta activation, live provider/model/chat/NT/Desktop/domain/restart acceptance, final full regression and owner design review pending. No Agent World PostgreSQL adapter, general Router/Execution V2 replacement or autonomous routine scheduler |
| Auth / owner identity | `BETA` in Unified Local | `0.10.0-beta.96` has one three-step registration contract for Telegram, Google and e-mail, a stable StratForge handle shared by profile/SF Social/SF Chat, final clickwrap consent and the existing shared environment-routed provider architecture. Owner Preview uses the same state transitions with sandbox-only synthetic credentials | Not present in the deployed beta.87 artifact; live real-provider acceptance and immutable Canary/Production promotion remain separate gates |
| Device confirmation / trusted access | `BETA` in Unified Local | Every new unknown human browser/app access starts as a two-minute pending session. The first freshly authenticated device can choose permanent trust or current-session-only without a redundant second OTP; later unknown clients still use confirmed Telegram or verified e-mail. Machine → Client → Session grouping remains proof-based | Integrated and browser-verified in Local beta.96, but not present in deployed beta.87; real-provider acceptance and release promotion remain separate gates |
| Legacy UI / Telegram Mini App | `DEPRECATED` | Merged main serves Aurora only; legacy UI, Mini App, remote-access and tunnel routes fail with HTTP 410. Classic assets are available only in a separate localhost read-only Legacy Viewer. Telegram `/start` uses a normal URL button | beta.87 is live in Canary and Production; historical snapshots remain until owner review |
| User entry and trial access | `BETA` in Unified Local | Anonymous product access is removed. Every verified account receives the same full product with a default five-hour active-use starting grant; idle time is not charged. Profile/security remain available after exhaustion | Not present in deployed beta.87; product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | A versioned release/change record is visible with title, summary, PRs, SHA, build/artifact, stage, checks, duration and environment identity. Production approval/promotion fails closed without title, summary, source SHA and verification PASS | beta.87 acceptance is recorded; any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Pre-delivery-repair delta full run passed `3803 passed, 44 skipped`; actual isolated PostgreSQL 17.10 regression separately covers 41 existing relational tests with zero skips and no owner/Production data | Final regression after delivery repair remains pending. Two shell tests and one POSIX permissions test remain unverified on Windows; fixture tests do not certify live browser/provider acceptance |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was not changed by PR #254/#255 or the beta.86 release-record work | cross-user owner-feed redistribution remains `EXTERNAL BLOCKED` without written authority |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | Production Connector on VMNINJA is `0.4.2-dev.20`; SERVER BACKTEST, cancel state machine, device catalog, account snapshot and Connector LIVE/GRACE/OFFLINE presentation are accepted | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material |
| Production worker queue | `AVAILABLE` | Eleven worker slots remain 4/4/2/1; empty workers use adaptive jittered backoff and one 30-second stale sweeper. Later auth hot-spot work reduced `/api/auth/status` latency but did not claim CPU improvement outside noise | DB tx/s still lacks a safe first-class diagnostics path |
| SF Social / SF Chat | `BETA` in Unified Local | The former Community tab is SF Social; existing profile/privacy/feed/moderation and human/AI SF Chat stores stay authoritative. Dirty Agent World adds explicit verified result/verdict snapshots to the existing Community store and model/application evidence to the existing chat | New Agent World publication/chat browser acceptance is pending; broader Strategy/Chart/Live object adapters remain separate. Existing relational PG tests passed, not an Agent World PG release. Neither beta.96 nor its new delta is promoted to Canary/Production |
| Documents | `BETA` | Current handoff and Context Pack identify beta.87 as live; hidden Markdown amendment blocks are removed and AI provenance is infrastructure-only or absent | beta.87 exact operational identity is recorded in its changelog closeout |
| Legal | `AVAILABLE` | One official onboarding agreement `2026-08-30-v2` is the sole versioned clickwrap; related official policies are readable informational documents; owner configuration is absent from both document API namespaces | Live Trading remains unavailable pending separate release and legal requirements |

## Last recorded operational identity (not re-verified in this task)

| Environment | Version | Git SHA | Build ID | Runtime artifact SHA256 | Status |
| --- | --- | --- | --- | --- | --- |
| Canary | `0.10.0-beta.87` | `8f42158661e8247832c90bea8fc4d9f0071e647b` | `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z` | same accepted beta.87 artifact | accepted / ready |
| Production | `0.10.0-beta.87` | same | same | same | live / ready |

The last deployment record identifies the same accepted beta.87 immutable artifact in both environments:
`art_9ce9dbcb9a7a4fee9df6a54d40f29806`, promoted to Production without a
rebuild. The exact archive and manifest SHA256 are recorded in the canonical
beta.87 changelog closeout.

## Deprecated current-state claims

- beta.29-beta.78 release identities are history, not current live state.
- The target Production installation is no longer offline or blocked by
  `sf_connector_installations_workspace_id_fkey`.
- Earlier draft legal labels are obsolete; the current package is official product documentation.
- A StratForge product trial is not a provider/exchange redistribution grant.
