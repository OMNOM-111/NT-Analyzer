# Shared Models — Local continuation checkpoint

Status: IN DEVELOPMENT. Verification: PENDING; not release acceptance.

## Recovered source

- Working tree: `C:/Users/dimon/Documents/Анализатор стратегий NinjaTrader`.
- Branch: `feat/shared-model-access`.
- Base implementation: `f5cb49d514e5e7a894391e7a1658450a80635130`.
- Recovered HEAD: `548c995ac82489bdcb4916ca07ca4e4ce9fc59da`.
- Since the base, the committed change adds the sharing switch to the actual
  model card and exposes its registry binding. No uncommitted source changes
  were found on recovery.
- Local runtime checkout: `C:/Users/dimon/Documents/StratForge-worktrees/agent-world-local-runtime`,
  detached at the same HEAD; clean at initial inspection.

## Preserved dirty state

Excluded from source staging: tracked `data/ai_lab/registry/star_ratings.json`,
`data/catalog/margins.json`, four `data/governance-rendered/` documents and
`data/governance/documents.json`. Untracked `.claude/`, AI Control Center data,
Agent World SQLite/WAL/SHM files, cache, governance backup and legacy archive
are local settings/runtime/archive data. They are preserved, not checkpoint code.

## Remaining acceptance

Verify owner sharing in the real model card, invocation from a new user with
their own workspace in AI Chat and Agent World, caller/model/task/agent/token/cost
accounting, private data isolation, budgets and immediate revocation with history
retention. The previous observer account in the owner's workspace is not a valid
new-user E2E fixture. Capture temporary permission/workspace settings before and
after and restore them. Run focused, related and full regression tests.

Release impact: Local only; no server, Canary or Production changes authorized.
No merge or release acceptance is claimed by this checkpoint.

## Continuation changes under verification

- Registry calls recheck shared access at transmission, including retry/stream
  transport. The admitted share remains attached to accounting if its owner
  revokes sharing while the response is in flight.
- Unknown or inactive attributed users fail closed instead of being classified
  as unrestricted platform jobs. Sharing-ledger reads use read-only SQLite.
- The registration trial outbox provisions a personal workspace using normal
  entitlement admission. Preview email registration follows this same path.
- Preview no longer grants every feature/capability override when marking a
  synthetic identity. Selectable `shared_models_user` and `ai_denied_user`
  profiles restrict real registration permissions and start with empty data.
  Neither profile grants model ownership, automation or administrative rights.
- Focused validation: Preview 25 passed; sharing plus registration/device
  lifecycle 44 passed. Related pre-bridge regression: 910 passed / 7 skipped.
  Latest Preview/shared/gateway focused suite: 98 passed. Full regression pending.

## Previous QA permission restored

Observer QA user `8260799865320459` had saved pre-test
`permission_overrides = {}` and `ai_lab = false`. Recovery found
`permission_overrides = {"ai_lab": true}`. Restored through the Local user
permission API with `enabled: null`; subsequent GET confirmed exactly `{}` and
`ai_lab = false`. No role, workspace membership or owner setting was changed.
This observer is not the new-user acceptance fixture.

## Live Local acceptance, 2026-09-22

The same `dev_preview.launch_sandbox` mechanism used by the Preview picker was
called against Local with the `shared_models_user` profile. The new account went
through email registration, confirmed device, initial trial and its own personal
workspace. Provider transport was real, not the test executor.

- Preview ID: `c565debd62396a279afb062c`.
- Disposable caller UUID: `6f7deaed-458a-4d88-a031-00a0440c851b`.
- Connection: `9a3b3c33-7d75-500b-9f6e-82fcbec3381e`, DeepSeek Flash.
- One direct Agent World task and one AI Chat request completed.
- Owner and caller usage both reported 2 calls, 203 input / 9 output tokens,
  cost USD 0.000031, no unknown-cost calls.
- Owner connection ID, API key and endpoint were absent from the shared catalog;
  direct foreign connection read was refused and new-user memory was empty.
- Sharing off refused a new chat call with HTTP 403; both prior tasks remained.
- Exit acknowledged cleanup and the entire disposable container was removed.
- Sharing before/after: false/false. Owner roles/workspaces were not modified.

The parent bridge is authenticated, call-only, loopback-only and scoped to one
Preview lifetime: 32 calls, USD 0.25 and 30 minutes maximum; existing model caps
also apply. Keys/settings stay in Local. Minimal owner billing usage survives
Preview cleanup; caller chats, memory, tasks, sessions and private stores do not.
No server, Canary or Production deployment took place. Live integration was
tested from current source; Local 8765 runtime switching is still pending.

## Permission denial and reset acceptance

Real HTTP testing caught an older server-side Preview blanket capability grant.
Only the explicitly selected synthetic Agent World operator retains fixture
access; identity validation alone no longer grants product permissions. Ordinary
profiles use the same entitlement and permission resolution as real users.
After this fix, the full live shared-only flow above passed again.

The `ai_denied_user` profile returned HTTP 403 for both model catalog and chat.
Reset to `shared_models_user` created a new UUID and a new personal workspace,
with AI chat allowed and model ownership/automation still denied. Exit removed
the disposable container. This negative/reset check made no provider calls and
changed no owner permissions or memberships.

Additional real HTTP isolation checks passed: a known owner conversation yielded
no messages to the disposable caller; a known owner task was refused. The new
account had only its normal empty default chat, no model tasks and no memory.
The persistent Preview banner now distinguishes paid shared calls (USD 0.25
ceiling) from profiles with blocked external actions.

Local access before-switch snapshot: 2 users, 1 workspace, 3 memberships;
SHA256 of selected roles/status/permission overrides/workspace memberships:
`dfcdf0b471112eb88388f3651350b5a5efb6082c172935de1209658af3011ccd`.
Credentials and sessions are excluded from the snapshot. Comparison after
switching is pending.

Implementation checkpoint: `780aae65`; draft PR:
https://github.com/OMNOM-111/NT-Analyzer/pull/291.
Post-correction focused Preview/shared/gateway/compatibility suite: 182 passed.
Full regression is in progress. Its architecture-import allowlist now names the
explicit Preview composition adapter, without relaxing pure core IO checks.

Linux CI on `de98a799`: 6033 passed, 131 skipped, 2 failed because the gateway
scenario fixture used the host Windows-only secret store. The fixture now uses
the existing in-memory test secret store on every platform; production key
storage is unchanged. The complete CI suite is being rerun after that correction.
