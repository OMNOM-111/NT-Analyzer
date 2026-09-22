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
