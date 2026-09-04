# Agent World — implementation status

Canonical program status: `IN DEVELOPMENT`. This document is the current handoff
for stages 0–1; the broader Agent World product is not available yet.

## Checkpoint and scope

| Field | Current value |
| --- | --- |
| Local/Git checkpoint UTC | 2026-09-04T22:37:13Z |
| Accepted base / rollback source | `4ae766ea0c3258a8bb049644ac2afbba6cb89330` |
| Base branch / dependency | `integration/stratforge-unified-local`, open [PR #280](https://github.com/OMNOM-111/NT-Analyzer/pull/280) |
| Base comparison | exact match; clean tracked/untracked state; no rollback or reset |
| Task branch | `codex/agent-world-foundation` |
| Worktree | `StratForge-worktrees/agent-world-foundation` (separate checkout) |
| Version / environment | `0.10.0-beta.96`, `pre_release`, Development; no version bump |
| Implementation checkpoint | `3afb75c5c2d02aa07703eadf274a1c1006ae8ada`; later checkpoint commits update documentation only |
| Task PR | [PR #281](https://github.com/OMNOM-111/NT-Analyzer/pull/281), stacked on `integration/stratforge-unified-local`; #280 remains open |
| Active workstream | Foundation: contracts, pure adapters, feature-flag definitions, tests, documentation |
| Storage migrations | none; current last migration is `0022`, next number deliberately unassigned |
| Runtime connections | none; no new route, worker, scheduler, router selection or UI |
| Feature flags | all ten flags OFF by default; no configuration installed |
| Stage 0 | baseline, isolation and documentation reconciliation complete |
| Stage 1 | local implementation verified; contract review required before stage 2 |
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

`IMPLEMENTATION COMPLETE`: YES for the bounded stages 0–1 code slice only.
`GIT CLOSEOUT COMPLETE`: branch committed, pushed and separate PR #281 created;
source `3afb75c5c2d02aa07703eadf274a1c1006ae8ada` was clean and synchronized.
This document's later checkpoint commit does not change code or test contents.
CI is a separate per-commit result, not inferred from these local counts.
`STAGE CLOSED`: NO for stage 1; ADR-0009 review and the dependency/merge gates
remain open. Stage 0's baseline/documentation checkpoint is complete.

| Check | Current-slice evidence |
| --- | --- |
| New contract/characterization tests | 221 passed, included in both runs below; no new skips |
| Focused regression | 654 passed, 0 skipped, 69.22 s; new contracts plus auth/onboarding, Preview, first-device/device confirmation, Community permanence, SF Chat, AI agents/personas/chief/routing/lab, permissions, NT queue, workers and docs governance |
| Full `python -m pytest -q -ra` | 2901 passed, 44 skipped, 335.66 s; no failures |
| Legacy `python -m tests` | 13/13 suites passed |
| Python `compileall -q app tools tests` | PASS |
| Root repository secrets/platform-secret values/Markdown | PASS; scan root explicitly includes files above `NT-Analyzer/` |
| Root tracked Markdown hidden amendment scan | PASS, 299 Markdown files |
| Application CSP/secrets/Markdown | PASS |
| External GPT Context validator | PASS; shared historical deployment-SHA warning is explained in Context Pack 11, not suppressed |
| `tools/pre_release_check.py` | PASS, 496 bundle files: static scan, runtime reads, Python compilation and shipped JavaScript syntax; no signing/archive/upload |
| `git diff --check` / cached check | PASS |
| Behavior/wiring isolation | no existing application/UI/migration file changed; no runtime importer of `ai_control_center`; all five critical hashes above match |

The first bundle run found three dangling relative changelog links to
repository-only documents. They now use repository URLs and the changelog
lists accepted exclusions. The normal bundle selection was not broadened.

Skipped full-suite scenarios (unverified, not PASS):

- 12 production storage + 12 production worker + 9 SF Chat relational + 8
  Stage 8 PostgreSQL tests: separate test PostgreSQL DSNs were not provided.
  No Production DB or credentials were used to satisfy this gate.
- 2 bash/shell tests and 1 POSIX permission-bit test: unavailable in this
  Windows toolchain. The dispatched Linux CI is a separate platform result.
- Browser walkthrough, real providers and market-data/Connector hardware
  acceptance were not repeated: no relevant runtime/UI changes in this slice.
  Inherited Preview manual acceptance is identified above, not counted again.
- No new PostgreSQL RLS/atomicity, migrations or outbox delivery can be
  certified by these pure DTO/protocol tests. Those are stage-2 implementation
  and real test-database gates, after contract review.

The existing [Next Architecture CI branch runs](https://github.com/OMNOM-111/NT-Analyzer/actions/workflows/next-architecture-ci.yml?query=branch%3Acodex%2Fagent-world-foundation)
are the authority for dispatched Linux/Windows/static results on the PR head.
The separate main-only `ci` Python and bridge gates cannot run on this stacked
base and have no manual dispatch. They are deferred, not green; after #280 is
owner-approved and integrated, retarget the stack and rerun applicable checks.
No workflow/branch protection changes, merge or deployment are authorized here.

Ignored local outputs are Python/pytest caches and generated local AI registry
scaffolding in this isolated worktree. They are not staged or shipped as data.
No owner Local data, runtime logs, keys, rollback bundle or signed artifact is
part of this diff.

Rollback is to keep every Agent World flag disabled and continue the unchanged
legacy runtime at the accepted base. There are no schema/data changes to undo.
Any eventual code revert is a separate reviewed commit, never a reset of user
work or deletion of the Unified Local checkout.

## Next safe step

Review the concrete contracts, explicit legacy projections, repository protocols
and server-side scoped flag registry in [ADR-0009](../adr/0009-agent-world-foundation.md).
Read the exact-head CI result on PR #281 without merging #280. After review,
stage 2 introduces SQLite/PostgreSQL implementations
and migrations only after that review. Court, new execution, Router switching
and UI remain outside this checkpoint.
