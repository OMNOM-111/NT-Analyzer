# Agent World — scoped foundation, stages 0–1

Release summary: Зафиксирована принятая Local beta.96 и начат отдельный фундамент Agent World: контракты, статусы, tenant scope, совместимые проекции и флаги. Текущие пользовательские сценарии не переключаются.

Release PRs: separate stacked PR pending creation; depends on #280.
Accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`.
Branch: `codex/agent-world-foundation`.
Affected subsystems: Agent World contracts, documentation and contract tests.
Release impact: Development only, no version change, migration, runtime activation, merge or deployment.
Verification result: PENDING implementation; inherited Preview evidence is not a new-slice PASS.

## Baseline and history

The accepted source matches Unified Local beta.96 exactly and was clean when the
separate worktree was created. Preview closed with `173 passed` focused,
`2680 passed, 44 skipped` full and the manual provider/device/exit walkthrough.
PR #280 remains open. Its code and real owner runtime are separate from this
branch. The earlier `c9b2883` dirty snapshot and isolated-branch descriptions
are preserved in [historical context](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md).

## Scope

- [ADR-0009](../adr/0009-agent-world-foundation.md) specifies entities, states,
  authority/capability/risk boundaries, event and repository contracts.
- [Current status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) tracks exact
  base, ownership, flags, evidence, rollback and next safe action.
- Current external context distinguishes Local beta.96 from the separately
  recorded beta.87 deployment and corrects the five-hour active-use/two-minute
  pending-device contracts without removing historical evidence.
- Definitions and pure adapters are additive. Existing permissions, budgets,
  jobs and trusted-device mechanisms remain authoritative. All new flags are
  off and no new runtime path is connected.

## Verification and remaining gates

Implementation and test evidence will be recorded at the slice checkpoint.
Contract review precedes stage-2 storage migrations. Full Agent World, new UI,
Court, execution, Router changes and release remain later stages. The next beta
number is intentionally unassigned.
