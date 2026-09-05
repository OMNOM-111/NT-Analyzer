# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-05T04:22:06Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: ef4006ebbdd95764636931d70fa7a742ceab756c (clean beta.96 runtime; native Azure binding compatibility under verification)
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Active branch: `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282) above foundation PR #281 and integration PR #280; both dependencies remain open
- Version: `0.10.0-beta.96`, `pre_release`; clean `ef4006eb` is active on Local 8765, no Canary/Production promotion
- Integration state: ef4006eb includes delivery, roles, private containers and rejection/rating/calendar corrections; narrow Azure compatibility is under verification
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
detached `agent-world-local-runtime` at `ef4006ebbdd95764636931d70fa7a742ceab756c`
now serves beta.96, build `dev-0.10.0-beta.96-ef4006ebbdd9`, with the original
owner data, account, workspace, history and NT heartbeat. No active job was lost.
Delivery, roles, private containers, sealed-rejection recovery, active-model
ratings, local calendar and new-version timestamps are active. The current
follow-up accepts only canonical api-version on resolved Azure owner bindings;
private transport, secrets, native adapter and existing budgets do not change.

The manual NinjaTrader proof `ui_20260905T003301149Z` has 1,273 actual bars and
64 trades, but is not Agent World-originated and remains excluded from statistics.
Fresh SF Chat/model-created backtest `62182839-1c4c-563d-8186-bcef081ec599`
passed on ca505d83: 64 trades, net -969.70, PF 0.725188, original report and hashes.
Three real DeepSeek/Gemini comparisons passed, n=3/OBSERVED/low confidence. The
verified backtest and five messages survived restart without duplication. Real
project versioning, private Memory promotion, manual routine/calendar acceptance
and System flags were exercised; Court/shared Memory/Social remain pending.
A Gemini Desktop plan was rejected for a noncanonical JSON wrapper, without
dispatch. Its saved failure reached the original chat once on ef4006eb without another
provider call. After an initial no-bars timeout, a new explicit command completed
task c691534b: real Desktop PNG, 140/800 historical bars, rendered in the same chat.
Both earlier failures stay failures; OFFLINE provenance remains explicit.
No second worker may share the owner data root. The ordinary
development profile resets data root to the code checkout; the verified Local
wrapper reapplies the original data root after profile load. Original task XML,
backups and manifests remain outside Git. Code rollback and data rollback are
separate; preserve new owner writes before restoring a cold snapshot.

Historical 34deb827 passed 3906/44. Active ef4006eb passed **3914 tests,
44 skipped**, 759.73 s, **218 focused**, legacy/static/context/staged and runtime
533-file bundles, plus exact-SHA CI 3/3. The narrow Azure follow-up passed
**3925 tests, 44 skipped**, 759.35 s, plus **187 focused**; exact-bundle and
activation gates remain separate. Saved completion uses one claimed existing
worker, not another provider call. Actual isolated PostgreSQL 17.10 separately
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
static PASS. Later 34deb827 run 33951941036 passed three jobs. Active ef4006eb
[run 33956017912](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33956017912)
also passed all three jobs. The Azure follow-up needs exact-SHA checks. PR #282 stays
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
- DeepSeek and Gemini connections and three actual comparisons passed; fresh
  model/chat/NT report passed on ca505d83 and survived 34deb827 restart. Z.AI
  unavailability and initial chart failures are not PASS. New actual PNG, saved
  failure recovery and corrected ratings/calendar passed on ef4006eb. Azure/Court,
  shared Memory/Social and own-key acceptance remain.
- Agent World is `IN DEVELOPMENT`: domain mechanisms are implemented, but the
  full local owner acceptance, Git/CI closeout and stages 0–13 are not closed.
- Ordinary test signup `aw_model_review_0905` reached final Terms on localhost;
  owner confirmation and separate OpenRouter key (`openrouter/free`) are pending.
  The new personal-container CTA grants no NT/key/budget/flag permissions;
  actual private-provider acceptance is `PENDING OWNER KEY`, not a reason to stop
  other acceptance work or copy owner keys into a test account.
- General Router/Execution V2 replacement and autonomous routine scheduling are
  unimplemented/OFF; actual observed evaluations do not change Router weights.
- Shared owner-feed distribution remains `EXTERNAL BLOCKED` without authority.
- Public Connector installer remains `EXTERNAL BLOCKED` on authorized signing.
- Preserve market data, Charts, Connector, trading, Auth, devices and SF stores.
- Version assignment, merge, signed artifact, Canary and Production are separate
  owner-controlled stages. Local/CI completion never implies release approval.

## Latest scoped checkpoint verification

Active ef4006eb: full 3914/44 (759.73 s), 218 focused, legacy 13/13,
Python/23-JS/root/context/staged and runtime 533-file bundles PASS; exact-SHA
CI 33956017912 all three jobs PASS. Azure follow-up: 3925/44 (759.35 s),
187 focused PASS. The 44 skips stay explicit; 41 have separate isolated PG proof.
Three real comparisons, NT/chat/restart, actual Desktop PNG, failure recovery,
ratings/calendar and initial domain actions passed. Azure/Court, shared
Memory/Social, own-key and final owner acceptance remain open.

## Next safe step

Finish exact-index bundle checks and commit the tested Azure compatibility delta,
then activate only Local after exact-PID/no-active-work checks. Bind Anna to the
approved Azure connection without copying its key; exercise bounded provider/Court
and remaining shared Memory/Social scenarios. Ordinary registration consent,
device trust and a separate private-provider key stay with the owner. Preserve
original owner data and rollback evidence. Record exact-SHA CI and owner visual
acceptance separately. Do not mark completion from a mock transport, historical report or successful HTTP
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
