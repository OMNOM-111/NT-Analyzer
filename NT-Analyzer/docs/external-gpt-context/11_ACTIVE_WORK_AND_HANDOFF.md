# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-05T04:22:06Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 486db834850d465006a3983d2d83ee809202df60
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Active branch: `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282) above foundation PR #281 and integration PR #280; both dependencies remain open
- Version: `0.10.0-beta.96`, `pre_release`; clean `486db834` is active on Local 8765, no Canary/Production promotion
- Integration state: new model/domain/social delta is dirty and uncommitted in the task worktree, not yet active on 8765
- Current Production version/build/artifact when known: recorded beta.87, build `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; not re-verified here
- Scope: Agent World integrated Local implementation and pending full owner acceptance; Production deployment facts are inherited evidence
- Status: IN DEVELOPMENT

## Current implementation checkpoint

[AGENT_WORLD_IMPLEMENTATION_STATUS.md](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
is the canonical current program handoff. It records base/current checkpoint,
file ownership, flag state, tests and skips, rollback and the next safe step.
The task worktree is isolated from the clean active runtime and does not modify
PR #280. Its new delta is not yet committed. The owner authorized completing
integrated Local functionality, not stopping at two isolated E2E demonstrations.
`OWNER ACCEPTANCE READY: NO`; stages 0–13 and final program closure remain open.

[ADR-0012](../adr/0012-agent-world-integrated-local.md) now defines the integrated
scope: Personas, private user-owned model connections and guarded owner bindings,
actual model/application tasks and evaluations, comparisons, Consensus/Court,
controlled Memory, projects, manual routine/calendar follow-ups, System and
explicit SF Social publication. Three primary tabs remain Overview/Work/Agents;
these tools and Task Inspector are drawers on the same page. Existing SF Chat,
worker/jobqueue, permissions, secret store and paid-budget ledger remain the
authorities. No general Router or Execution V2 replacement, autonomous scheduler,
trading authority, budget increase or numbered SQL migration is introduced.

All ten flags default OFF. The exact server-side Development workspace allowlist
`STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES`, with fresh account/device/membership
admission, enables eight reviewed paths: read/UI/tasks/evaluation/memory/
consensus/Court/social. Router shadow and Execution V2 remain OFF. Preview
continues with its separate four synthetic flags and cannot invoke real models,
domain workflows or external publication. Reads after trial/budget expiry may
retain the user's existing evidence; they do not grant new work or model calls.

Real SF Chat work requires an actual stored user message and selected model.
An independently checked Tolik/Ivan plan starts only the existing NinjaTrader
or Desktop mechanism. A valid plan stays waiting until the original source
produces a verified report or authentic PNG receipt. Separate immutable
application outcomes and evaluations drive status and SF Chat recovery. Distinct
real observations, not self-ratings or synthetic fixtures, populate reputation;
n < 3 stays NEW. Court uses three isolated judges and an immutable 2-of-3
advisory verdict, never execution. Memory sharing has an explicit live TTL/
source-revision grant; Social publishing requires the exact prepared hash and
explicit permanent confirmation. Routines/calendar acceptance creates manual
follow-ups through the existing queue; automation stays OFF.

The original Local at 8765 served dirty beta.93 / `7062f749` because its scheduled
task still pointed at that checkout. This is historical, not the current runtime.
After owner authorization, copy/cold backups, SQLite integrity and isolated-copy
startup checks, only the matched Local process/task chain was replaced. Clean
detached `agent-world-local-runtime` at `486db834850d465006a3983d2d83ee809202df60`
now serves beta.96, build `dev-0.10.0-beta.96-486db834850d`, with the original
owner data, account, workspace, history and NT heartbeat. No active job was lost.
The newer dirty integration delta has not yet been activated there.

The manual NinjaTrader proof `ui_20260905T003301149Z` has 1,273 actual bars and
64 trades, but is not Agent World-originated and remains excluded from statistics.
Fresh model/chat-created backtest, Desktop-to-SF-Chat capture, real model ratings,
domain actions and restart acceptance are still required after clean delta
activation. No second worker may share the owner data root. The ordinary
development profile resets data root to the code checkout; the verified Local
wrapper reapplies the original data root after profile load. Original task XML,
backups and manifests remain outside Git. Code rollback and data rollback are
separate; preserve new owner writes before restoring a cold snapshot.

The pre-delivery-repair delta full run passed **3803 passed, 44 skipped**,
578.02 s, after correcting the two stale cache-token expectations from the earlier
3763/44/2 run. Later focused domain gateway checks passed **96 tests**. A gap in
retrying a persisted final model result after failed SF Chat publication is now
being repaired through the existing worker/inbox, without a second provider call.
Final regression after that repair remains pending; 3803 PASS is not final-delta
acceptance. Actual isolated PostgreSQL 17.10 regression separately
passed **41 tests, zero skips**, 122.71 s, on existing migrations 1–22 with TLS
and non-superuser/NOBYPASSRLS roles. The remaining two shell and one POSIX
permissions tests are unavailable on Windows. There is no Agent World PG adapter:
its domain repository remains Development SQLite only, fail-closed elsewhere.
Final provider/browser/CI acceptance remains pending. See the
[integrated change record](../changelog/2026-09-05-agent-world-integrated-local.md).

The earlier code `fc78677df` full **3369 passed, 44 skipped**, legacy **13/13**,
**517-file** bundle checks and synthetic browser results are preserved in the
[pre-model checkpoint archive](../archive/AGENT_WORLD_PRE_MODEL_CHECKPOINT_486DB834.md).
[ADR-0010](../adr/0010-agent-world-owner-review.md) and
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md) remain historical scope and
safety records; their switch-pending/three-flag limitations do not describe this
new integrated implementation. Earlier PASS does not certify the current delta.

## Accepted Unified Local — beta.96

- Auth/registration, Device Confirmation, SF Social, SF Chat and Owner Preview
  coexist in one build. Human identity and StratForge handle are shared.
- Starting access is five hours of active use. Pending device confirmation is
  two minutes, with permanent or current-session-only trust. The first device
  can consume fresh single-use login proof; subsequent unknown clients use OTP.
- Contextual Preview buttons replace credentials on the actual provider screen.
  Terms, final registration and trust choices remain manual. Preview has
  separate data/cookies and blocked external effects. Exit restores full owner
  Local; no private owner values belong in this context pack.
- Inherited evidence: Preview implementation `42a99a85f164f69c6ddd0edf46859ef005e787e2`,
  closeout `4ae766ea0c3258a8bb049644ac2afbba6cb89330`; focused `173 passed`,
  full `2680 passed, 44 skipped`, static/context/bundle PASS, manual provider,
  QR/device/exit walkthrough PASS, PR #280 CI `5/5` success.
- Skipped scenarios are unverified. New Agent World checks are reported
  separately in the canonical status/change record.
- SF Social owns profiles, feed, privacy, moderation and approved result posts.
  SF Chat owns human conversations; the AI conversation authority is projected
  through the same shell. Strategy/Chart/Live publishing adapters remain
  `IN DEVELOPMENT`. The navigation-stage SF Social label is now applied;
  compatible `community*` APIs remain.

## Dependency, review and CI

The owner-review PR targets the foundation branch so its diff contains only
this slice. PR #281 and PR #280 follow their own owner-approved merge process.
After that, retarget/rebase the stack as appropriate and rerun applicable
checks; do not infer that baseline CI certifies later commits.

The existing Next Architecture CI supports manual dispatch on the task branch.
The separate `ci` workflow runs only for main-targeting PRs. Record dispatched
checks and merge-required checks separately; never describe absent checks as
green. No workflow or branch-protection changes are part of this slice.

[Branch run 33937601902](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33937601902)
historically passed **3/3** on `b05ee124caf652c77689fd749cd9eadc8265d564` (documentation after
code `fc78677df`): Linux **3372 passed/41 skipped**, Windows **3369 passed/44 skipped**,
static PASS. It does not certify the later `486db834` checkpoint or dirty
model/domain/social delta. Final-SHA checks still have to run. PR #282 stays
draft for owner review; program stages remain open.

## Historical deployment identity

The pack-wide `Verified against Git SHA` remains its shared deployment anchor;
`Local source verified SHA` and the canonical status identify the separate
Local implementation and accepted base. The validator's legacy `Current Git SHA` field below refers only
to that deployment anchor, not to the Agent World branch.

| Deployment metadata | Recorded value |
| --- | --- |
| Current Git SHA | `8f42158661e8247832c90bea8fc4d9f0071e647b` (pack-wide deployment anchor) |
| Local accepted base SHA | `4ae766ea0c3258a8bb049644ac2afbba6cb89330` |

This task did not access Canary/Production. The last recorded operational
snapshot remains beta.87:
`8f42158661e8247832c90bea8fc4d9f0071e647b`,
build `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`,
artifact `art_9ce9dbcb9a7a4fee9df6a54d40f29806`.
Canary acceptance and same-artifact Production promotion are recorded in
[the canonical beta.87 closeout](../changelog/2026-08-31-beta85-forward-only-promotion.md).
These inherited facts are not a live re-verification or a release of beta.96.

The former isolated PR #270/#278 descriptions, earlier test counts, operational
metrics, and `c9b2883` Preview snapshot are preserved in
[pre-foundation historical context](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md).
They no longer define the current Local baseline.

## Remaining boundaries

- Development SQLite implements the Agent World repository; non-Development
  use fails closed. Actual PostgreSQL 41/41 covers existing relational/RLS
  migrations 1–22, not a missing Agent World PostgreSQL adapter.
- Actual model/provider delivery, application receipts, runtime restart/lease
  and visual acceptance remain pending for the integrated delta; contract tests
  and the already completed initial Local switch do not certify those paths.
- Agent World is `IN DEVELOPMENT`: domain mechanisms are implemented, but the
  full local owner acceptance, Git/CI closeout and stages 0–13 are not closed.
- Ordinary users require their own compatible connection/allowance. Prepare the
  ordinary-test-account wizard while the owner supplies a separate Gemini key;
  actual private-provider acceptance is `PENDING OWNER KEY`, not a reason to stop
  other acceptance work or copy owner keys into a test account.
- General Router/Execution V2 replacement and autonomous routine scheduling are
  unimplemented/OFF; actual observed evaluations do not change Router weights.
- Shared owner-feed distribution remains `EXTERNAL BLOCKED` without authority.
- Public Connector installer remains `EXTERNAL BLOCKED` on authorized signing.
- Preserve market data, Charts, Connector, trading, Auth, devices and SF stores.
- Version assignment, merge, signed artifact, Canary and Production are separate
  owner-controlled stages. Local/CI completion never implies release approval.

## Next safe step

Finish delivery-only recovery, its regression rerun, static/context/exact-bundle
checks and a clean scoped commit. Prepare the ordinary-user wizard without
inventing credentials; exercise its real provider path when the owner enters
the separate key.
Activate that tested commit on Local only after another exact-PID/no-active-work
check, preserving the verified original data-root binding and rollback evidence.
Then complete actual model-to-NT/Desktop-to-SF-Chat browser flows, measured model
comparisons/ratings, domain/Court/Memory/Social actions and restart/revocation
checks. Record final-SHA CI and the owner's visual acceptance separately. Do not
mark completion from a mock transport, historical report or successful HTTP
response, and do not infer any merge or Canary/Production authorization.

## Canonical evidence

- [Foundation change record](../changelog/2026-09-04-agent-world-foundation.md)
- [Preview closeout](../changelog/2026-09-04-beta96-visual-audit-and-first-device.md)
- [Current status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
- [Integrated Local ADR](../adr/0012-agent-world-integrated-local.md)
- [Integrated change and verification record](../changelog/2026-09-05-agent-world-integrated-local.md)
- [Environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and automation](07_AI_AGENTS_AND_AUTOMATION.md)
- [Market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)
