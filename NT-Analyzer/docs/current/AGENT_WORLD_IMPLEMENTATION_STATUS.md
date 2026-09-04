# Agent World — implementation status

Canonical program status: `IN DEVELOPMENT`. This document is the current handoff
for stages 0–1; the broader Agent World product is not available yet.

## Checkpoint and scope

| Field | Current value |
| --- | --- |
| Verified UTC | 2026-09-04T21:50:16Z |
| Accepted base / rollback source | `4ae766ea0c3258a8bb049644ac2afbba6cb89330` |
| Base branch / dependency | `integration/stratforge-unified-local`, open [PR #280](https://github.com/OMNOM-111/NT-Analyzer/pull/280) |
| Base comparison | exact match; clean tracked/untracked state; no rollback or reset |
| Task branch | `codex/agent-world-foundation` |
| Worktree | `StratForge-worktrees/agent-world-foundation` (separate checkout) |
| Version / environment | `0.10.0-beta.96`, `pre_release`, Development; no version bump |
| Implementation checkpoint | Base SHA above; first slice in progress; use `git rev-parse HEAD` for the current checkout |
| PR strategy | stacked PR targeting `integration/stratforge-unified-local`; no merge of #280 |
| Active workstream | Foundation: contracts, pure adapters, feature-flag definitions, tests, documentation |
| Storage migrations | none; current last migration is `0022`, next number deliberately unassigned |
| Runtime connections | none; no new route, worker, scheduler, router selection or UI |
| Feature flags | all ten flags OFF by default; no configuration installed |
| Stage 0 | baseline verified; documentation reconciliation in progress |
| Stage 1 | implementation in progress; contract review required before stage 2 |
| Release status | not a Canary or Production release; deployment identity below is historical evidence |

Source documents supplied by the owner remain unchanged on the Desktop. Their
`c9b2883` snapshot describes unfinished Preview work before this baseline.
[Archived pre-foundation context](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md)
preserves that history and the old isolated-branch handoff. This file and the
actual Git checkout supersede those current-state claims.

## Accepted Local baseline

Auth, registration, Device Confirmation, SF Social, SF Chat and Owner Preview
are `BETA` in Unified Local. Registration uses the shared human identity and
handle. Starting access is five hours of active use. Device Confirmation uses a
two-minute pending window, `permanent/session` trust and the narrow single-use
fresh login proof for a first device. External-provider availability is separate
from synthetic Preview acceptance.

Preview implementation `42a99a85f164f69c6ddd0edf46859ef005e787e2` and closeout
`4ae766ea0c3258a8bb049644ac2afbba6cb89330` passed focused `173` tests and full
`2680 passed, 44 skipped`. The existing record contains manual Telegram, Google,
email/OTP, QR, final registration, Device Confirmation, both trust modes and
Exit Preview restoring the original owner Local. Python/JS/static/context/bundle
gates passed; PR #280 had five successful CI checks. This is inherited baseline
evidence, not a claim that these runs were repeated for the new slice.

The 44 baseline skips are unverified credential/platform scenarios, not PASS.
New slice evidence and skip reasons will be recorded separately below.

Canonical evidence: [beta.96 Preview closeout](../changelog/2026-09-04-beta96-visual-audit-and-first-device.md).
The last recorded deployed identity is beta.87; this task does not inspect or
change Canary/Production, their DB, secrets or signed artifacts.

## Baselines preserved

SHA256 of critical files at the accepted base (checkout bytes):

| File | SHA256 |
| --- | --- |
| `app/market_data.py` | `c96e0025b46501f21e6fe346f627c049cfbe3509e4634698c1f69f587a8a6fb0` |
| `app/static/aurora/assets/chart-engine.js` | `74b5777f11bbad36bcbd759baa364d0767e41a980be598078d92314e98f90519` |
| `app/static/aurora/assets/pages/desktop.js` | `bf18102c5f13ba6a7c0dba9898524954b8c7dabf46ee76007d7c10116a9a336a` |
| `app/connector_protocol.py` | `9dc177b7673fe729d88b23c7623673a8843640ca0afb0c84587b223011fa0139` |
| `app/jobqueue.py` | `bfaa4140776803560d813eb5ea1af96b281247e8b9536eae7f59ae4dea511e66` |

The slice adds `app/ai_control_center/`, its contract tests and documentation.
All existing application files, UI and migrations retain their base contents.
The social-page rename to SF Social belongs to the later navigation stage;
`community*` names and current labels remain compatible in this slice.

## Ownership and handoff

| Files / boundary | Active owner |
| --- | --- |
| `app/ai_control_center/`, new foundation tests, ADR-0009, this status and scoped docs | current Foundation workstream in `codex/agent-world-foundation`; AI-assisted change under owner instruction |
| `server.py`, `permissions.py`, `api.js`, `ui.js`, `theme.css` | no Agent World writer in stages 0–1; reserve one owner when the integration stage starts |
| migration sequence, storage router, jobs, budgets, commands | no writer in this slice; stage-2 owner assigned after contract review |
| Auth, devices, Social, Chat, Preview | accepted PR #280 baseline; regression contract |
| market data, Charts, Connector, trading | out of scope |

Every successor records branch/base/current SHA, owned files, contract changes,
flags, test evidence, remaining gates and one next safe step here. Git supplies
the commit containing a checkpoint; a file cannot embed its own future hash.
No actor/model identity is inferred from a previous document or persona name.

## Verification and closeout

New-slice checks: pending implementation. `IMPLEMENTATION COMPLETE`,
`GIT CLOSEOUT COMPLETE` and `STAGE CLOSED` are not yet claimed.

Rollback is to keep every Agent World flag disabled and continue the unchanged
legacy runtime at the accepted base. There are no schema/data changes to undo.
Any eventual code revert is a separate reviewed commit, never a reset of user
work or deletion of the Unified Local checkout.

## Next safe step

Finish the pure contracts, explicit legacy projections, repository protocols and
server-side scoped flag registry described in [ADR-0009](../adr/0009-agent-world-foundation.md).
Run characterization/isolation and regression gates, then submit this isolated
slice for contract review. Stage 2 introduces SQLite/PostgreSQL implementations
and migrations only after that review. Court, new execution, Router switching
and UI remain outside this checkpoint.
