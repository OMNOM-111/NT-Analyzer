# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-04T21:50:16Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 4ae766ea0c3258a8bb049644ac2afbba6cb89330
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Active branch: `codex/agent-world-foundation`, stacked on `integration/stratforge-unified-local` (open PR #280)
- Version: `0.10.0-beta.96`, `pre_release`, not deployed
- Current Production version/build/artifact when known: recorded beta.87, build `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; not re-verified here
- Scope: Agent World stages 0–1 and the accepted Unified Local baseline; deployment facts are inherited evidence
- Status: IN DEVELOPMENT

## Current implementation checkpoint

[AGENT_WORLD_IMPLEMENTATION_STATUS.md](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
is the canonical current program handoff. It records base/current checkpoint,
file ownership, flag state, tests and skips, rollback and the next safe step.
The new slice uses a separate clean worktree and does not modify PR #280.

Stage 0 verified an exact match to the accepted base. Stage 1 adds contracts,
state machines, pure legacy projections, repository interfaces and scoped
server-side flags. [ADR-0009](../adr/0009-agent-world-foundation.md) is proposed
for review before stage-2 persistence. No new API, storage migration, Court,
execution engine, Router selection or UI is activated. All ten flags default
OFF; no enabled configuration is installed.

Local slice implementation is complete: 221 new contract/characterization
tests, focused regression 654 passed, full pytest 2901 passed / 44 skipped,
legacy runner 13/13 and Python/JS/static/context/496-file bundle gates PASS.
The 44 skips are 41 PostgreSQL acceptance scenarios without test DSNs and
three shell/POSIX scenarios; no skipped scenario is certified. The canonical
status separates local implementation, Git/CI closeout and stage review.

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
  `IN DEVELOPMENT`. The user-visible SF Social rename belongs to the later
  navigation stage; compatible `community*` APIs remain.

## Dependency, review and CI

The Agent World PR targets the open integration branch so its review contains
only this slice. PR #280 must follow its own owner-approved merge process.
After that, retarget/rebase the stack as appropriate and rerun applicable
checks; do not infer that baseline CI certifies later commits.

The existing Next Architecture CI supports manual dispatch on the task branch.
The separate `ci` workflow runs only for main-targeting PRs. Record dispatched
checks and merge-required checks separately; never describe absent checks as
green. No workflow or branch-protection changes are part of this slice.

## Historical deployment identity

The pack-wide `Verified against Git SHA` remains its shared deployment anchor;
`Local source verified SHA` and the canonical status identify the separate
Local base. The validator's legacy `Current Git SHA` field below refers only
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

- Stage-2 SQL/SQLite implementation and migrations wait for contract review.
- Credentialed PostgreSQL, external-provider delivery, runtime restart/lease
  acceptance and visual acceptance must be proved when those paths change;
  pure contract tests do not certify them.
- New AI features are `IN DEVELOPMENT`, not a usable Agent World product.
- Shared owner-feed distribution remains `EXTERNAL BLOCKED` without authority.
- Public Connector installer remains `EXTERNAL BLOCKED` on authorized signing.
- Preserve market data, Charts, Connector, trading, Auth, devices and SF stores.
- Version assignment, merge, signed artifact, Canary and Production are separate
  owner-controlled stages. Local/CI completion never implies release approval.

## Next safe step

Review the verified foundation checkpoint and ADR-0009. After review,
stage 2 implements scoped repositories and transactional events using the
existing PostgreSQL/SQLite, idempotency, audit and worker foundations. Assign
one writer to shared files and migration numbering in the canonical status.

## Canonical evidence

- [Foundation change record](../changelog/2026-09-04-agent-world-foundation.md)
- [Preview closeout](../changelog/2026-09-04-beta96-visual-audit-and-first-device.md)
- [Current status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
- [Environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and automation](07_AI_AGENTS_AND_AUTOMATION.md)
- [Market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)
