# Agent World — scoped foundation, stages 0–1

Release summary: Подготовлен и локально проверен отдельный фундамент Agent World на принятой Local beta.96: контракты, статусы, tenant scope, совместимые проекции и флаги. Текущие пользовательские сценарии не переключаются.

Release PRs: [#281](https://github.com/OMNOM-111/NT-Analyzer/pull/281), stacked on and dependent on open #280.
Accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`.
Implementation source SHA: `3afb75c5c2d02aa07703eadf274a1c1006ae8ada`.
Branch: `codex/agent-world-foundation`.
Affected subsystems: Agent World contracts, documentation and contract tests.
Release impact: Development only, no version change, migration, runtime activation, merge or deployment.
Verification result: PASS for the local bounded foundation; Git/CI and stage review are separate gates.

## Baseline and history

The accepted source matches Unified Local beta.96 exactly and was clean when the
separate worktree was created. Preview closed with `173 passed` focused,
`2680 passed, 44 skipped` full and the manual provider/device/exit walkthrough.
PR #280 remains open. Its code and real owner runtime are separate from this
branch. The earlier `c9b2883` dirty snapshot and isolated-branch descriptions
are preserved in [historical context](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-foundation/NT-Analyzer/docs/archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md).

## Scope

- [ADR-0009](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-foundation/NT-Analyzer/docs/adr/0009-agent-world-foundation.md) specifies entities, states,
  authority/capability/risk boundaries, event and repository contracts.
- [Current status](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/agent-world-foundation/NT-Analyzer/docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) tracks exact
  base, ownership, flags, evidence, rollback and next safe action.
- Current external context distinguishes Local beta.96 from the separately
  recorded beta.87 deployment and corrects the five-hour active-use/two-minute
  pending-device contracts without removing historical evidence.
- Definitions and pure adapters are additive. Existing permissions, budgets,
  jobs and trusted-device mechanisms remain authoritative. All new flags are
  off and no new runtime path is connected.

Accepted bundle exclusions: ADR/current program status, archived context and
External GPT Context Pack remain repository-only developer handoff documents,
not public runtime documents. This shipped changelog uses repository links for
them, so the bundle has no dangling relative references. The bundle contains
the additive Python definitions; no runtime consumer or migration is added.

## Verification and remaining gates

New-slice local evidence: 221 new tests; focused regression 654 passed with no
skips; full pytest 2901 passed, 44 skipped in 335.66 s; legacy runner 13/13
suites passed. Python compilation, shipped JavaScript syntax, root-level
secrets/Markdown/amendment checks, application CSP/static, Context Pack and
496-file bundle checks passed. All existing application/UI/migration files and
critical market-data/Charts/Connector/queue hashes are unchanged.

The 44 skips are 41 real PostgreSQL acceptance tests without separate test DSNs,
two shell tests and one POSIX permissions test. They are not PASS. Browser,
real-provider and hardware acceptance were not repeated for this non-UI,
non-runtime slice. This does not certify new storage, RLS or event delivery.
The Context validator retains its documented shared deployment-anchor warning.

Git checkpoint: implementation committed and pushed, separate PR #281 created;
the closeout documentation does not change the tested application tree. Exact-
head Linux/Windows/static CI is tracked by the existing Next Architecture CI
branch runs and the PR. Main-only Python/bridge merge checks are deferred until
the dependency is integrated and the stack retargeted; absent checks are not PASS.
Stage 0 is complete. Stage 1 implementation is locally complete, but stage
closure remains pending contract review; no merge/release is claimed.

The first bundle check caught three links to non-shipped developer documents;
repository URLs and explicit exclusions fixed them without changing the
production file selector. Full bundle recheck passed.

Contract review precedes stage-2 storage migrations. Full Agent World, new UI,
Court, execution, Router changes and release remain later stages. The next beta
number is intentionally unassigned.
