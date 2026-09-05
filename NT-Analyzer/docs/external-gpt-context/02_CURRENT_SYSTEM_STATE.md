# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-09-05T12:45:49Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 95912cbff8152905966e6bb7bfc2a45d3db15f80 (clean beta.96 runtime; SF Chat in-app dialogs browser-verified; prior provider evidence is separately recorded on aa54c294)
- Current UI correction: [SF Chat dialog receipt](../changelog/2026-09-05-sf-chat-app-dialogs.md); existing backend/data/flags unchanged, no release
- Current program delta: [integrated review record](../changelog/2026-09-05-agent-world-program-review.md) — application receipt observations, explicit typed fact handoff, manual follow-up delivery and ordinary-session Memory HTTP evidence; final activation/acceptance is separately recorded there.
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Unified Local branch: `integration/stratforge-unified-local` (PR #280), version `0.10.0-beta.96`; not released to Canary/Production
- Active Local 8765: clean `95912cbff8152905966e6bb7bfc2a45d3db15f80`, build `dev-0.10.0-beta.96-95912cbff815`, original owner data, Preview=false
- Agent World branch: `codex/agent-world-owner-preview`, stacked draft PR #282 above open #281/#280; clean 95912cbf active and dialog-browser verified, not a release
- Verified deployed artifact Git SHA: `8f42158661e8247832c90bea8fc4d9f0071e647b`
- Current Production version/build/artifact when known: `0.10.0-beta.87`; `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; exact hashes are in the beta.87 changelog
- Current live release: `0.10.0-beta.87`, accepted Canary and Production
- Scope: Current factual subsystem snapshot: Unified Local Development plus the separately identified live Production baseline
- Status: PARTIAL

## SF Chat dialog correction — Local verified

The task branch replaces native conversation confirmations and rename/folder
prompts with styled asynchronous in-app dialogs, plus notification-inbox clear.
Cancellation, keyboard focus, stale context and duplicate actions are guarded;
existing backend, permissions, stores and Auth/device/Preview remain unchanged.
This does not migrate unrelated release/trading/security administration dialogs.
Active Local is clean 95912cbf; styled dialogs, Escape/cancel, preserved history,
safe navigation and inbox focus passed in the actual browser. Full regression:
4032 PASS / 44 skipped, supplemented by final 62 dialog checks (seven auth-context
cases added after collection); 352 focused regression, root/static/context and
534-file staged/runtime bundles PASS. Exact-code CI 33970324754 is 3/3 PASS:
Windows 4039/44, Linux 4042/41 and static, including all final auth-context cases.
Skipped DB/platform cases are not new live PASS; this is no program/release closeout.
Canonical status/evidence: [dialog change record](../changelog/2026-09-05-sf-chat-app-dialogs.md)
and [program status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

## Previous verified model/domain checkpoint — aa54c294

At that previous checkpoint, clean Local 8765 ran `aa54c2940150e540d8b594dbf1d6254e172adbfd`, beta.96,
build `dev-0.10.0-beta.96-aa54c2940150`, original owner data, Preview=false,
live orders=false. The code is committed/pushed to draft PR #282; #280/#281
remain unmerged. Operational documentation may be newer than active runtime code.

Final full **3977 passed / 44 skipped**, 954.04 s; final focused **319 PASS**,
presentation focused **610 PASS**, legacy **13/13 suites**, root/static/context/
diff and exact staged/runtime **533-file bundles PASS**.
[Exact-code CI 33965039490](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33965039490)
passed Windows, Ubuntu and static, 3/3. No main-target or release PASS is inferred.

Actual browser acceptance on this SHA: stored application Outcome and original
report links in Inspector/SF Chat; same 64-trade NT report; genuine Desktop PNG
140/800 historical bars; preserved chats (5/13 messages); three Personas and
n=3 arithmetic observations for Tolik/Ivan, NEW for Anna. Consensus proposal
cf1464ab uses two accepted same-input contributions. Fresh Court ae0e5e45
received three real valid isolated votes (DeepSeek/Gemini/Azure) and approve;
old case 86a650ab retains its one vote and invalid Gemini response. No validator
was weakened and a verdict does not execute actions.
SF Social read-only preview e4853566… has net -969.7 and PF 0.7252 explicitly
after commission; no post or permanent confirmation was created.

`LOCAL VISUAL REVIEW AVAILABLE: YES`; the full program stays IN DEVELOPMENT.
Ordinary registration/device/key, real multi-user sharing/revocation, permanent
Social publication and owner design acceptance remain separate. New Router,
Execution V2, autonomous routines and an Agent World PG adapter are not implemented.
All ten flags default OFF; exact admitted Local workspace has eight paths ON,
Router/Execution V2 OFF. Preview has separate synthetic flags, no real side effects.
The earlier 93bb1298/other-SHA test and provider history is preserved in the
[canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) and
[integrated changelog](../changelog/2026-09-05-agent-world-integrated-local.md).

## Earlier scoped checkpoint verification

Historical ef4006eb: **3914 passed / 44 skipped**, 759.73 s, 218 focused PASS,
legacy 13/13, Python/23-JS/root/context and staged/runtime 533-file bundles PASS.
Exact-SHA [CI 33956017912](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33956017912)
passed all three jobs; absent main-target checks are not counted as green.
Narrow Azure owner-binding follow-up: **3925 passed / 44 skipped**, 759.35 s,
plus 187 focused PASS; its exact-bundle/commit/activation subsequently passed on bd239e76.
The 44 skips remain explicit; 41 have separate actual isolated PG evidence.
Three real DeepSeek/Gemini comparisons passed: n=3, OBSERVED, low confidence,
no routing effect. Project versioning, private Memory promotion, manual routine,
calendar forms and System flags were exercised in Local. Full Court/shared
Memory/Social/own-key and owner design acceptance remain open. Actual Desktop PNG,
saved rejection recovery, active-model rating and local calendar display passed
on ef4006eb; actual historical bars are not labelled LIVE.

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
  initially ran clean `486db834`, then `ca505d83`, `34deb827`, `ef4006eb`, `bd239e76` and `93bb1298`; now `aa54c294` beta.96
  against the same original owner data root. The original verified backtest
  and its five chat messages survived restart without duplication. The narrow
  Azure owner binding is active and verified; no second worker may share
  the owner data root.
- Live ca505d83 SF Chat → DeepSeek → NinjaTrader → original report passed:
  model task `62182839-1c4c-563d-8186-bcef081ec599`, 64 historical trades,
  net -969.70, PF 0.725188. Independent source verification is not profitability.
  DeepSeek connection test passed; Z.AI endpoint was unavailable. Ordinary-user
  signup awaits owner Terms confirmation and separate OpenRouter key, not copied credentials.
- Claimed delivery, roles, private containers, sealed-failure recovery and
  rating/calendar fixes are active at ef4006eb with exact-SHA CI. Older results
  remain historical. The noncanonical Gemini plan stayed rejected, without
  Desktop dispatch; its saved failure reached the original chat once without
  another provider call. A new command produced a genuine Desktop PNG, 140/800
  historical bars, in the same chat. Earlier failures remain failures.
  Separate actual isolated
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
| Agent World | `IN DEVELOPMENT` | Three tabs plus drawers, clean aa54c294 active; real NT/PNG, original report links, Consensus, three-model Court, ratings and read-only Social snapshot verified | Multi-user Memory, permanent Social publication, ordinary own-key and owner acceptance pending. New Agent World PG adapter, Router/Execution V2 and autonomous routine scheduler not implemented |
| Auth / owner identity | `BETA` in Unified Local | `0.10.0-beta.96` has one three-step registration contract for Telegram, Google and e-mail, a stable StratForge handle shared by profile/SF Social/SF Chat, final clickwrap consent and the existing shared environment-routed provider architecture. Owner Preview uses the same state transitions with sandbox-only synthetic credentials | Not present in the deployed beta.87 artifact; live real-provider acceptance and immutable Canary/Production promotion remain separate gates |
| Device confirmation / trusted access | `BETA` in Unified Local | Every new unknown human browser/app access starts as a two-minute pending session. The first freshly authenticated device can choose permanent trust or current-session-only without a redundant second OTP; later unknown clients still use confirmed Telegram or verified e-mail. Machine → Client → Session grouping remains proof-based | Integrated and browser-verified in Local beta.96, but not present in deployed beta.87; real-provider acceptance and release promotion remain separate gates |
| Legacy UI / Telegram Mini App | `DEPRECATED` | Merged main serves Aurora only; legacy UI, Mini App, remote-access and tunnel routes fail with HTTP 410. Classic assets are available only in a separate localhost read-only Legacy Viewer. Telegram `/start` uses a normal URL button | beta.87 is live in Canary and Production; historical snapshots remain until owner review |
| User entry and trial access | `BETA` in Unified Local | Anonymous product access is removed. Every verified account receives the same full product with a default five-hour active-use starting grant; idle time is not charged. Profile/security remain available after exhaustion | Not present in deployed beta.87; product access does not grant third-party market-data redistribution rights |
| Admin / Release Center | `BETA` | A versioned release/change record is visible with title, summary, PRs, SHA, build/artifact, stage, checks, duration and environment identity. Production approval/promotion fails closed without title, summary, source SHA and verification PASS | beta.87 acceptance is recorded; any application change starts a new artifact cycle |
| Test isolation | `AVAILABLE` | Active aa54c294 full 3977/44, 319 final focused, 610 presentation focused, legacy 13/13 and exact-code CI 3/3 PASS; isolated PostgreSQL separately passed 41 existing relational tests | Two shell tests and one POSIX check are not Windows PASS; fixtures do not certify live provider/browser acceptance |
| Market data / TopstepX | `BETA` | TopstepX remains the primary independent read-only history/realtime chart source; the accepted gateway/SignalR/cache/failover/rendering baseline was not changed by PR #254/#255 or the beta.86 release-record work | cross-user owner-feed redistribution remains `EXTERNAL BLOCKED` without written authority |
| Charts / fan-out | `BETA` | Browser clients consume same-origin StratForge market-data WebSockets; provider credentials are not delivered to browsers and consumers do not create their own TopstepX loginKey/SignalR sessions | broader design acceptance is separate from this Connector closeout |
| NinjaTrader / Connector | `BETA` | Production Connector on VMNINJA is `0.4.2-dev.20`; SERVER BACKTEST, cancel state machine, device catalog, account snapshot and Connector LIVE/GRACE/OFFLINE presentation are accepted | public installer distribution remains `EXTERNAL BLOCKED` on authorized Authenticode material |
| Production worker queue | `AVAILABLE` | Eleven worker slots remain 4/4/2/1; empty workers use adaptive jittered backoff and one 30-second stale sweeper. Later auth hot-spot work reduced `/api/auth/status` latency but did not claim CPU improvement outside noise | DB tx/s still lacks a safe first-class diagnostics path |
| SF Social / SF Chat | `BETA` in Unified Local | The former Community tab is SF Social; existing profile/privacy/feed/moderation and human/AI SF Chat stores stay authoritative. Agent World adds explicit verified snapshots to the existing Community store and model/application evidence to the same chat; real backtest delivery survived restart | Agent World Social publication remains pending; rejected-plan recovery and actual PNG chat delivery passed; broader Strategy/Chart/Live adapters remain separate. Existing relational PG tests passed, not an Agent World PG release. beta.96 is not promoted to Canary/Production |
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
