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

- Preview ID: `03c9a0aa418c5e0af4141646`.
- Disposable caller UUID: `0f1f5a04-6dad-4949-9960-4f7bc6c64591`.
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
