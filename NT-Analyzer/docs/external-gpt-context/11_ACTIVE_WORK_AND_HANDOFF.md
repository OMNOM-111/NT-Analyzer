# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-05T12:45:49Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 2b6d0112bef88c5bfb73970de64ec5518443e56b (clean beta.96 runtime; real handoff/manual delivery and original report/PNG verified, exact-code CI PASS)
- Local verification UTC: 2026-09-05T19:05:43Z; pack-wide deployment anchor above remains historical, not a claim of new Production verification
- Current UI correction: [SF Chat dialog receipt](../changelog/2026-09-05-sf-chat-app-dialogs.md); existing backend/data/flags unchanged, no release
- Current program delta: [integrated review record](../changelog/2026-09-05-agent-world-program-review.md) — clean 2b6d0112 active; genuine report/PNG observations, real fact handoff and deduplicated manual SF Chat delivery verified; 4235/44 skipped full suite, 542-file bundles and CI 33984524477 3/3 PASS. Full-program/owner acceptance remains open.
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Protected Local branch snapshot: `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282) above foundation PR #281 and integration PR #280; active unified source is PR #285 below
- Version: `0.10.0-beta.96`, `pre_release`; clean `2b6d0112` active on Local 8765, no Canary/Production promotion
- Integration state: scoped model/domain/Chat/NT/Desktop, real fact handoff, manual discussion, separate application observations, Consensus and Court verified; owner-dependent and full-program work remain
- Current Production version/build/artifact when known: recorded beta.87, build `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; not re-verified here
- Scope: Agent World integrated Local implementation and pending full owner acceptance; Production deployment facts are inherited evidence
- Status: IN DEVELOPMENT
- Latest preserved source: `376b400dc3c8ab3a008f1e45800d401dd02c4b6f`,
  588-file bundle/static/context PASS. Immutable full: 5262 PASS / 1 FAIL /
  112 SKIP; legacy 13/13 PASS. Later bounded Persona chat/transport changes and
  the stale cancel-command fixture correction are separate from that snapshot.
  [Next checkpoint](../changelog/2026-09-08-agent-world-persona-chat-checkpoint.md)
  adds main/alias/UUID selection and receipt-only assistant responses, no
  professional score or model/tool authority. Fresh full/PG/browser pending.
  [Exact 376 PG evidence](../changelog/2026-09-08-agent-world-postgres-376-acceptance.md):
  69 AW + 41 legacy PASS, separate TLS/NOBYPASSRLS API/worker/restart PASS;
  seven later Persona PG cases remain outside those counts. Isolated 8804 now
  runs clean376 after its checked 41-file backup; protected8765 unchanged.
- Next operation: preserve the Persona checkpoint, launch immutable full and
  new disposable PG including seven Persona cases, then complete the
  [owner browser route](../current/AGENT_WORLD_OWNER_ACCEPTANCE_GUIDE.md).
  Owner key/real consent/permanent publication/design remain distinct holds.
- Shared checkpoint: `a03ec82b686a9f6f05c056fe5a500ecbdb3babac`, pushed to PR #285,
  clean at preservation; mandatory static/context/artifact checks passed.
  Subsequent scoped work covers canonical Connector result binding, rejected
  origin correction, Persona voice in saved SF Chat messages and preservation
  of the speaking Persona across Router executor changes. See the
  [boundary record](../changelog/2026-09-08-agent-world-trusted-report-boundary.md).
  Detached exact-a03 full: 5124 PASS / 12 FAIL / 112 SKIP; legacy 13/13 PASS.
  Skips separate 68 Agent World PostgreSQL, 41 legacy PostgreSQL and 3 platform
  cases. Later fixes preserve scoped provenance/isolation assertions; final
  integrated full/browser remains pending. The
  [Chat review boundary](../changelog/2026-09-08-agent-world-chat-review-boundary.md)
  prevents timer/message stars from accepting a Task; the
  [Router identity contract](../changelog/2026-09-08-agent-world-router-persona-preservation.md)
  preserves speaking Persona separately from executor. No flag/Local/Production
  activation occurred.
- Current preserved core: `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`, draft
  PR #285 on `codex/agent-world-unified-acceptance`. The subsequent shared
  API/worker/Chat/UI delta and remaining gates are in the
  [shared checkpoint](../changelog/2026-09-08-agent-world-shared-integration-checkpoint.md)
  and single [program matrix](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).
  New isolated PostgreSQL evidence is 69 Agent World
  plus 41 legacy PASS and separately hash-bound API/worker/restart/RLS acceptance,
  not a new full-regression PASS. See the
  [takeover record](../changelog/2026-09-08-agent-world-integration-takeover.md).
  Local 8765 and original worktrees are unchanged; localhost:8804 is isolated QA.
- Historical independent review snapshot (already included in the unified source): `claude/agent-world-review-and-hardening`,
  local and unpushed, base `45ab4361`, HEAD `c865db2248a12f6927d077dc31efe8b05c02426e`.
  Findings, deliberate non-changes and the exact next operation are in
  [AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md](../current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md)
  with its [change record](../changelog/2026-09-06-agent-world-status-presentation-review.md).
  It reworks status counters, Persona occupancy, warning actionability, score
  provenance, System readiness axes, evidence placement and Inspector focus; it
  changes no flag, migration, route or authority. Pushed as draft
  [PR #283](https://github.com/OMNOM-111/NT-Analyzer/pull/283) (base
  `codex/agent-world-owner-preview`, review only — #282's base untouched);
  exact-SHA CI 3/3 PASS on `84115efc`, later commits not yet certified.
- Historical intake receipt: separate uncommitted work existed in the `agent-world-mechanisms`
  worktree (base `45ab4361`): PostgreSQL/RLS repository with migration 0023,
  Router V2, Execution V2 + Deviation Control, delegation, scheduler and a task
  lifecycle projection. It was reviewed read-only from a stable hash-verified
  snapshot and left untouched: 113 passed / 68 skipped in isolation, the 68
  being the PostgreSQL suite, unrunnable here for want of a server. Its
  `task_presentation.py` supersedes this branch's phase logic; the merge order
  and the port list are in the handoff. Codex has since checkpointed that work
  as `f9b94445`/`db85773f`; 31 of the 33 reviewed files are byte-identical to
  `db85773f` and the two that differ are changelogs, so the review binds to
  that commit.

## Resume point — 2026-09-08

Continue in `codex/agent-world-unified-acceptance` from combined source
`f0bafe8ea46653827bc836afcb2197964390cf08`, not from the old mechanisms branch.
The [intake manifest](../changelog/2026-09-08-agent-world-integration-takeover.md)
accounts for both executors, the stable five-file documentation delta, excluded
runtime state and the already ported 73 flag cases. Root owns shared integration
files. Original worktrees, PR bases and Local 8765 are unchanged.
Next: freeze/save shared integration after short mandatory gates, restart only
isolated 8804, then exact-code full-Aurora/browser/regression/PG acceptance.
The new numeric-summary/delegation root already has normal-queue/Chat evidence;
do not implement it again. Close current remaining gates from the matrix.
Keep real/synthetic evidence separate and Part E's withdrawn claims visible.
The dated snapshot is historical; its old missing-mechanism/UI-freeze
instructions do not override the owner's new sole-integrator mandate.

## New mechanisms WIP checkpoint — 2026-09-06

Saved WIP source: `f9b9444524aa497781fe3de7254d1bfb0e3b062c` (37 files;
clean worktree after commit). Short static/secret/context/diff and 556-file
bundle gates PASS; exact-checkpoint full pytest NOT RUN. All further backend
work is a separate commit; frozen UI remains exactly as in this checkpoint.

Separate branch `codex/agent-world-mechanisms` preserves additive PostgreSQL
repository/RLS migration 0023, Router V2, Execution/Deviation, finite delegation,
schedule, automation authority and unfinished status/UI work from `45ab4361`.
Canonical status: **IN DEVELOPMENT**, with integration gaps; not active on
protected Local 8765 (`2b6d0112`, beta.96). No new flags or migrations applied.
New disposable AW PostgreSQL evidence: 69 PASS/0 skipped; existing PG suites:
41 PASS/0 skipped separately. Without DSNs, the new suite has 68 skips, not PASS.
Latest UI subset has 3 FAIL/88 PASS; exact-checkpoint full regression not run.
Do not inherit prior Local/CI PASS. Details, known defects, ownership and resume
operation: [mechanisms WIP record](../changelog/2026-09-06-agent-world-mechanisms-wip.md).

Independent PR #283 remains separate; no UI/presentation consolidation until
review reconciliation, and no edits to its branch/tests. Preserve existing
WIP UI only; continue non-overlapping backend in later commits. No merge/deploy
or paid external calls. Owner visual acceptance, registration, separate key and
exact permanent Social publication remain pending.

## Completed SF Chat dialog correction — historical 95912cbf verification

The task branch replaces native conversation confirmations and rename/folder
prompts with styled asynchronous in-app dialogs, plus notification-inbox clear.
Cancellation, keyboard focus, stale context and duplicate actions are guarded;
existing backend, permissions, stores and Auth/device/Preview remain unchanged.
This does not migrate unrelated release/trading/security administration dialogs.
At the completed 95912cbf checkpoint, styled dialogs, Escape/cancel, preserved history,
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

## Current implementation checkpoint

[AGENT_WORLD_IMPLEMENTATION_STATUS.md](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
is the canonical current program handoff. It records base/current checkpoint,
file ownership, flag state, tests and skips, rollback and the next safe step.
The task worktree is isolated from the clean active runtime and does not modify
PR #280. Code aa54c294 is committed/pushed with exact-code CI PASS and a separate
operational documentation closeout. The integrated page is ready for visual review,
not only two isolated demonstrations. `LOCAL VISUAL REVIEW AVAILABLE: YES`;
full `OWNER ACCEPTANCE READY: NO`, because the ordinary-user own-key,
real multi-user sharing/revocation and permanent Social scenarios are still open.
Stages 0–13 and final program/release closure are not claimed.

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
detached `agent-world-local-runtime` at `2b6d0112bef88c5bfb73970de64ec5518443e56b`
now serves beta.96, build `dev-0.10.0-beta.96-2b6d0112bef8`, with the original
owner data, account, workspace, history and NT heartbeat. No active job was lost.
Delivery, roles, private containers, sealed-rejection recovery, active-model
ratings, local calendar and new-version timestamps are active. Azure compatibility
accepts only canonical api-version on resolved Azure owner bindings;
private transport, secrets, native adapter and existing budgets do not change.
The current explicit Anna handoff retains the original report and adds one
child result to the same chat (eight total messages). Two manual follow-up
discussions each have one neutral system message; no autonomous scheduler runs.

The manual NinjaTrader proof `ui_20260905T003301149Z` has 1,273 actual bars and
64 trades, but is not Agent World-originated and remains excluded from statistics.
Fresh SF Chat/model-created backtest `62182839-1c4c-563d-8186-bcef081ec599`
passed on ca505d83: 64 trades, net -969.70, PF 0.725188, original report and hashes.
Three real DeepSeek/Gemini comparisons passed, n=3/OBSERVED/low confidence. The
verified backtest and five messages survived restart without duplication. Real
project versioning, private Memory promotion, manual routine/calendar acceptance
and System flags were exercised. Fresh three-model Court and read-only Social
preview now pass; shared Memory/permanent Social remain pending.
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

Historical 34deb827 passed 3906/44. Historical ef4006eb passed **3914 tests,
44 skipped**, 759.73 s, **218 focused**, legacy/static/context/staged and runtime
533-file bundles, plus exact-SHA CI 3/3. The narrow Azure follow-up passed
**3925 tests, 44 skipped**, 759.35 s, plus **187 focused**; exact-bundle,
activation and actual Azure checks subsequently passed. Saved completion uses one claimed existing
worker, not another provider call. Actual isolated PostgreSQL 17.10 separately
passed **41 tests, zero skips**, 122.71 s, on existing migrations 1–22 with TLS
and non-superuser/NOBYPASSRLS roles. The remaining two shell and one POSIX
permissions tests are unavailable on Windows. There is no Agent World PG adapter:
its domain repository remains Development SQLite only, fail-closed elsewhere.
Exact-code CI and the documented aa54c294 provider/browser scenarios pass;
owner-dependent scenarios and full program acceptance remain open. See the
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
static PASS. Later 34deb827 run 33951941036 passed three jobs. Historical ef4006eb
[run 33956017912](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33956017912)
also passed all three jobs. Azure CI 33958551325 and Court CI 33960694698 passed 3/3. PR #282 stays
draft for owner review; program stages remain open.

Current exact-code [run 33984524477](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33984524477)
passed 3/3 at `2b6d0112bef88c5bfb73970de64ec5518443e56b`: Windows 4235/44,
Ubuntu 4238/41 and static. Local full 4235/44 and staged/runtime 542-file bundles
PASS. Clean Local activation, real Anna fact handoff and two deduplicated manual
discussion receipts passed. Code rollback is 95912cbf with later owner writes
preserved; no data rollback, merge or deploy is authorized. Operational docs
may advance branch HEAD without another runtime switch. Full-program closure
and owner design acceptance are not inferred from this code closeout.

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
  migrations 1–22, not a missing Agent World PostgreSQL adapter. The 41 are
  `test_production_storage` (12), `test_production_workers` (12),
  `test_sf_chat_relational_postgres` (9) and `test_stage8_postgresql` (8); none
  imports `ai_control_center` and no shipped migration creates an Agent World
  table, so neither the historical PASS nor the current skips describe Agent
  World coverage. `tests/test_agent_world_storage_scope.py` pins this.
- DeepSeek and Gemini connections and three actual comparisons passed; fresh
  model/chat/NT report passed on ca505d83 and survived 34deb827 restart. Z.AI
  unavailability and initial chart failures are not PASS. New actual PNG, saved
  failure recovery and corrected ratings/calendar passed on ef4006eb; Azure passed
  on bd239e76. Court format/result presentation, shared Memory/Social and own-key acceptance remain.
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

## Earlier scoped checkpoint verification

Historical ef4006eb: full 3914/44 (759.73 s), 218 focused, legacy 13/13,
Python/23-JS/root/context/staged and runtime 533-file bundles PASS; exact-SHA
CI 33956017912 all three jobs PASS. Azure follow-up: 3925/44 (759.35 s),
187 focused PASS. The 44 skips stay explicit; 41 have separate isolated PG proof.
Three real comparisons, NT/chat/restart, actual Desktop PNG, failure recovery,
ratings/calendar, Azure and initial domain actions passed. Full Court, shared
Memory/Social, own-key and final owner acceptance remain open.

## Next safe step

Finish the result presentation/format regression, exact-index bundle and scoped
commit; activate only Local after exact-PID/no-active-work checks. Verify original
NT report links/JSON file rendering, commission labels and a fresh independent
Court case without changing the failed old case. Ordinary registration consent,
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
