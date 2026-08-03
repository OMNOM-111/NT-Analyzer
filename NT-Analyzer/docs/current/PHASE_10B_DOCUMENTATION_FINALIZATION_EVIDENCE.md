# Phase 10B — Documentation finalization — Implementation Evidence

История поправки: 2026-08-03T16:53:14Z; внёс `GitHub Copilot`; scope: Phase 10B — зафиксировать фактический перенос документации (git mv + обновление ссылок), политику языка, changelog, requirements matrix, strategy-spec verification и version readiness; честно отметить незакрытые требования.

**Status: Phase 10 — NOT fully closed; Phase 10B GIT CLOSEOUT COMPLETE.** Phase 10A delivered the canonical tree
spec + migration map + governance hardening. Phase 10B performs the actual
document relocation and the honest completeness audit. One concrete requirement
(the workspace/strategy specification revision module) remains **NOT
IMPLEMENTED**, so Phase 10 is explicitly not declared fully closed. This document
contains no secrets, keys, tokens or real DSNs.

## 1. Source state

- Integration branch: `release/0.10.0-next-architecture` at `f0028ace` (Phase 10A closeout).
- Phase branch: `phase/10b-documentation-finalization`, created from `f0028ace`.
- Baseline `origin/main` (`72f46a1a`) untouched.

## 2. Documentation move (git mv, not copy)

~55 documents were relocated with `git mv` into their canonical directories per
`docs/DOCS_STRUCTURE.md`:
- `docs/agents/` — 11 agent docs (AGENTS, AI_ACCOUNTANT, AI_CHART_OPERATOR, AI_LAB_CLOUD_AGENTS, AI_LAB_COMPETITIVE_FEEDBACK, AI_MANAGEMENT, AI_NEWS_AGENT, AI_STRATEGY_ANALYST, CHIEF_AI_AGENT + AGENTS index).
- `docs/architecture/` — 14 docs (CONNECTOR_PROTOCOL_V1, DATA_PLATFORM_ARCHITECTURE, job-schema, MARKET_DATA_*, MULTI_USER_ACCOUNT_ARCHITECTURE, TELEGRAM_MINI_APP, UI_API_MAP, UI_ARCHITECTURE, UI_ROUTES_AND_ROLLBACK).
- `docs/operations/` — 13 docs (CONNECTOR_INSTALL_GUIDE, manual-validation, MARKET_DATA_BACKUP_MATRIX, MARKET_DATA_PRODUCTION_RUNBOOK, POSTGRESQL_REDIS_MIGRATION_PLAN, PRODUCTION_*_RUNBOOK, STAGING_QA, UI_OPERATIONS).
- `docs/strategies/` — 6 docs (AI_STRATEGY_LAB_QUALITY, AI_STRATEGY_LAB_RUN_CONTROLS, STRATEGY_LIFECYCLE, STRATEGY_RECOVERY, simple-validation-strategy, risk-profile).
- `docs/product/` — 3 docs (MARKET_DATA_VISUAL_ACCEPTANCE, UI_PARITY_MATRIX, UI_VERIFICATION).
- `docs/changelog/` — UI_INTEGRATION_LOG.
- `docs/archive/` — 14 dated audit snapshots; `docs/archive/audits/2026-07-18-product-contours.md` (renamed from PRODUCT_MODES_AND_CONTOURS_AUDIT_2026-07-18.md).

Not moved (owner-gated) — see `docs/REQUIRES_OWNER_CLASSIFICATION.md`:
`AGENT_PERSONAS.md` (stray dirty), `VITEK.md` and `AI_DIALOGUE_CONTRACT.md`
(referenced as siblings by the dirty AGENT_PERSONAS.md, cannot be edited),
`repository-hygiene.md` (root vs operations/ content diverged, different SHA-256).

## 3. Reference updates (same change)

- **Markdown links:** all 35 links broken by the move were fixed;
  `release_static_scan.py --scan markdown` → MARKDOWN OK.
- **Governance registry:** `data/governance/documents.json` paths updated for the
  15 moved registered docs.
- **Release build manifest (CI-critical):** `tools/build_server_release.py`
  `_INCLUDED_FILES`/`_EXCLUDED_FILES` and `tests/test_server_release.py` updated
  to the new paths.
- **Tests reading runbooks:** `tests/test_production_infrastructure.py`,
  `tests/test_stage8_operations.py` (2) updated to `docs/operations/…`.
- **Operational config:** 5 systemd unit `Documentation=` paths,
  `deploy/production/README.md`, root `.gitattributes`.
- **Code comments/docstrings:** `app/agent_allocation.py`, `app/ai_lab/agent_tts.py`,
  `app/ai_lab/orchestrator.py`, `app/jobqueue.py`, `app/static/aurora/assets/api.js`,
  `app/static/aurora/assets/agents/README.md`, `bridge/README.md`, three bridge C#
  files.
- **Repo/user docs:** `NT-Analyzer/README.md`, workspace `README.md`,
  `Agents/README.md` (x2), `STRATFORGE_MARKET_DATA_FAILOVER_TASK_RU.md`, and all
  canonical doc cross-references.

### Residual references (honest, non-CI-breaking)

- Governance law `source_refs` in `app/governance.py` `DEFAULT_LAWS` and
  `data/governance/laws.json` still cite pre-move `docs/<file>.md` paths
  (provenance metadata; many identical repeated strings; substring-validated by
  `tests/test_governance.py`). Generated rendered files
  (`data/*/governance-rendered/*`, `docs/governance/{LAWS,LOCAL_AI_LAWS,SYNC_MAP}.md`)
  regenerate from these when the backend re-renders. A dedicated source_ref
  refresh is a follow-up.
- Archive-internal historical cross-references and the point-in-time
  `...AUDIT_AND_IMPLEMENTATION_PLAN...` evidence citations are left as authored
  (historical snapshots).

## 4. Language / localization

`docs/LOCALIZATION.md` records Russian as the canonical source for user/product/
governance docs, the do-not-translate list (API/class/field/command/path/id/code),
the rule that law/safety-limit meaning is never changed for translation, and a
single-canonical-source structure with no hand-maintained diverging English copy.
Governance and agent docs are already Russian; a full normalization pass over
mixed architecture/operations/product docs is a documented follow-up (matrix §D).

## 5. Changelog

`docs/changelog/NEXT_ARCHITECTURE_CHANGELOG.md` separates User / Admin / Security /
Infrastructure & Releases / Externally-blocked / Not-yet-in-Production / Not
implemented, and does not present dry-run/mock/test/unconnected-provider work as
operational.

## 6. Requirements matrix

`docs/current/NEXT_ARCHITECTURE_FINAL_REQUIREMENTS_MATRIX.md` maps every program
requirement (Phases 0–10 + test/acceptance matrix + strategy specs + version) to
IMPLEMENTED / PARTIALLY IMPLEMENTED / EXTERNAL DEPENDENCY / NOT IMPLEMENTED with
concrete files/endpoints/migrations/tests/commits. A plan/doc is never counted as
implementation.

## 7. Strategy specifications (verification)

- Safety invariant (global governance / safety limits / laws / other workspace
  cannot be changed by a workspace or strategy override): **IMPLEMENTED + tested**
  (`tests/test_phase10_docs_governance.py`, disjoint stores, allowlist, governance
  gate).
- Workspace-scoped fork: **PARTIALLY IMPLEMENTED** — `app/community.py`
  `copy_strategy(workspace_id=)` creates a workspace-scoped `pending_import` copy.
- Full workspace/strategy specification revision model (`strategy.spec.manage`,
  `sf_document_revisions` with `scope_type`): **NOT IMPLEMENTED** — a larger
  product module (plan §Phase 10 / ADR-0007). Recorded as a concrete incomplete
  requirement; Phase 10 is not fully closed.

## 8. Version readiness

`VERSION.json` = `0.10.0-dev.1` (channel `dev`, `in_development`); latest tag
`stratforge-server-v0.9.0-dev.15`. Next dev suffix `0.10.0-dev.2`.
`0.10.0-beta.1` is **NOT READY** (an incomplete requirement + external gates).
`VERSION.json` is not changed in Phase 10B. Environment / release channel / SemVer
remain distinct fields.

## 9. Commands run and results

- Full regression `python -m pytest -q -p no:cacheprovider` → **1148 passed, 31 skipped**.
- `python -m compileall` (edited modules) → PASS; `node --check api.js` → PASS.
- `python tools/release_static_scan.py` → CSP OK, SECRETS OK, MARKDOWN OK.
- Clean-checkout verification: see §11 (added at closeout).

## 10. Rollback

All moves are `git mv` (reversible via revert). New docs are additive. No schema/
migration change in Phase 10B.

## 11. Commit / PR / CI / merge / clean-checkout evidence

- Implementation commit: `d1087f59` on `phase/10b-documentation-finalization` (from integration `f0028ace`).
- PR: [#17](https://github.com/OMNOM-111/NT-Analyzer/pull/17) → base `release/0.10.0-next-architecture`.
- CI ([Actions run 30834935279](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30834935279)): Static gates PASS; Tests (ubuntu-latest) PASS; Tests (windows-latest) PASS.
- Merge commit: `753d2271`; task branch deleted locally and on origin; integration in sync with origin after merge.
- **Clean-checkout verification** (detached worktree from `origin/release/0.10.0-next-architecture` at `753d2271`, no local stray files):
  - full `pytest -q` → **1148 passed, 31 skipped**;
  - `compileall app tools tests` → PASS; `node --check` ui.js + api.js → PASS;
  - `release_static_scan.py` → CSP OK, SECRETS OK, MARKDOWN OK;
  - `git diff --check` → clean (only CRLF notices on app-regenerated governance renders);
  - the checked-out tree was clean before the run; the 8 files modified after the run are governance/runtime files the app regenerates on import (not committed-content issues).
  - SKIPPED / EXTERNAL (not counted as PASS): the 31 skips are live-PostgreSQL migration/acceptance suites (need `STRATFORGE_TEST_POSTGRES_*`) and other environment-gated suites; real Canary/Production deployment, real blue-green switch, real Telegram/Connector/email provider and browser QA were **not run** (owner-gated / policy).
- Extraneous dirty/untracked files (`data/catalog/margins.json`, `data/development/*`, `data/governance-rendered/*`, `data/ai_lab/registry/orchestrator_*`, `docs/AGENT_PERSONAS.md`, `docs/governance/{LAWS,LOCAL_AI_LAWS,OVERVIEW,SYNC_MAP}.md`) were preserved on disk and kept outside the Phase 10B delivery.
