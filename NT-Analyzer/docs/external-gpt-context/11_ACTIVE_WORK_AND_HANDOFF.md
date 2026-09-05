# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-05T01:43:39Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: fc78677dfa258fb56042866a6764e8c8a45c42e6
- Unified Local accepted base SHA: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`
- Active branch: `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282) above foundation PR #281 and integration PR #280; both dependencies remain open
- Version: `0.10.0-beta.96`, `pre_release`, not deployed
- Current Production version/build/artifact when known: recorded beta.87, build `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; not re-verified here
- Scope: Agent World bounded owner-review implementation and accepted Unified Local baseline; deployment facts are inherited evidence
- Status: IN DEVELOPMENT

## Current implementation checkpoint

[AGENT_WORLD_IMPLEMENTATION_STATUS.md](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
is the canonical current program handoff. It records base/current checkpoint,
file ownership, flag state, tests and skips, rollback and the next safe step.
The new slice uses a separate clean worktree and does not modify PR #280.

The owner authorized continuing to a clickable review checkpoint. Local SQLite
persistence, Preview-only server facade, a single AI Center, deterministic task
fixtures, independent shadow evaluation and verified result/PNG projection to SF
Chat are implemented. [ADR-0010](../adr/0010-agent-world-owner-review.md) defines
this limited scope, not a production acceptance of every foundation contract.

All flags default OFF. Four can activate in a controlled synthetic workspace.
After the owner's request for real data, the separate Local adapter adds only
read/UI/tasks opt-in for exact owner Development workspaces. SF Chat can submit
registered NinjaTrader historical jobs and receive actual verified reports via
the existing chief monitor. Desktop snapshots require real canvas bars, a bounded
PNG and saved command receipt; never a headless substitute. Evaluation stays OFF
for real tasks. The UI is one page with exactly Overview/Work/Agents and drawers.
No Court, Router switch, trading execution, automatic memory/routines or social
publisher. No new queue, permissions catalog, paid-budget ledger or numbered SQL
migration. Source and final checks are tracked in the canonical status and
[owner-review change record](../changelog/2026-09-04-agent-world-owner-review.md).

The running owner Local at port 8765 was observed as beta.93 / `7062f749` / dirty,
not the accepted beta.96 checkout. It is unchanged. Owner review starts a separate
beta.96 Preview child with isolated data and normal external-effect blocking.
Exit returns to the unchanged owner Local, not to a silently upgraded server.

Read-only validation of the manually requested NinjaTrader proof job
`ui_20260905T003301149Z` confirms an actual report, 1,273 bars and 64 trades;
it is unmarked/manual and is excluded from Agent World statistics. The new
chat-created real job and Desktop-to-SF-Chat browser flow remain pending an
approved switch of Local to this beta.96 checkout. Do not start a second worker
against the owner data root or assume the supervisor preserves an overridden
root: its ordinary development profile resets the root to its code checkout.
See [ADR-0011](../adr/0011-agent-world-real-local-jobs.md) and canonical status
for the safe handoff and remaining acceptance gates.

Local verification of code `fc78677df`: **3369 passed, 44 skipped**, legacy
**13/13** suites, **517-file** bundle/static/runtime reads/Python/JS PASS.
Synthetic browser task/profile/rating/chart-to-SF-Chat and Exit checks passed.
The 44 skips and real chat/NT/Desktop acceptance are explicitly not PASS.

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

- Local SQLite is implemented for review. PostgreSQL/RLS, delivery workers and
  numbered migrations still require review and their own acceptance evidence.
- Credentialed PostgreSQL, external-provider delivery, runtime restart/lease
  acceptance and visual acceptance must be proved when those paths change;
  pure contract tests do not certify them.
- Agent World is `IN DEVELOPMENT`: a usable bounded owner-review surface is
  present, not a completed general autonomous-agent product.
- Shared owner-feed distribution remains `EXTERNAL BLOCKED` without authority.
- Public Connector installer remains `EXTERNAL BLOCKED` on authorized signing.
- Preserve market data, Charts, Connector, trading, Auth, devices and SF stores.
- Version assignment, merge, signed artifact, Canary and Production are separate
  owner-controlled stages. Local/CI completion never implies release approval.

## Next safe step

Finish final local/Git/CI checks, then have the owner inspect the populated Preview
and task/score/chart/chat results. Record design acceptance and feedback before a
general rollout. Choose the next bounded production contract implementation only
after that review; preserve the shared-file ownership table in canonical status.

## Canonical evidence

- [Foundation change record](../changelog/2026-09-04-agent-world-foundation.md)
- [Preview closeout](../changelog/2026-09-04-beta96-visual-audit-and-first-device.md)
- [Current status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
- [Environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and automation](07_AI_AGENTS_AND_AUTOMATION.md)
- [Market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)
