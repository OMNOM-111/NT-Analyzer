# Documentation structure and migration map (Phase 10)

This document is the **canonical docs-tree specification and migration map** for
the NT-Analyzer / StratForge repository. It is the owner-reviewable map required
by the Phase 10 dependency ("owner-approved migration map"): it defines the
target home for every documentation file so the physical relocation can be
executed (via `git mv` + reference rewrites) in owner-approved steps without
breaking inbound links.

История поправки: 2026-08-03T15:40:00Z; внёс `GitHub Copilot`; scope: Phase 10 — создать канонический docs-tree и migration map (структура каталогов + целевые адреса документов; массовое перемещение выполняется после owner-approval этой карты).

## Canonical tree

```
docs/
  current/       Active next-architecture program: status, phase evidence, master plan.
  architecture/  System/design docs (data platform, market data, UI, connector, mini app).
  operations/    Runbooks, deployment, hygiene, git workflow, manual validation.
  security/      Security posture, isolation, auth/identity, step-up, trusted devices.
  product/       Product modes/contours, UI parity/verification, acceptance matrices.
  agents/        AI agent roles, personas, dialogue contracts, orchestrator.
  strategies/    Strategy lifecycle, quality, recovery, run controls, risk profile.
  governance/    Rendered governance (source of truth = data/governance/*).
  changelog/     Release/change history and running integration logs.
  adr/           Architecture Decision Records (0001+).
  archive/       Superseded, dated snapshots and audits (historical only).
    audits/      Dated point-in-time audits.
  schemas/       Machine schemas (e.g. connector protocol).
```

`current/`, `architecture/`, `operations/`, `governance/`, `adr/`, `schemas/`
already exist. Phase 10 additionally creates `security/`, `product/`, `agents/`,
`strategies/`, `changelog/`, `archive/` and `archive/audits/`.

## Separation rule (acceptance criterion)

`docs/current/` holds **only** the active next-architecture program (program
status, phase evidence, the master audit/implementation plan). Superseded,
dated, point-in-time material belongs in `docs/archive/`. New documents are
created directly in their canonical directory. This gives a clean "current vs
target" separation.

## Migration map — loose files under `docs/` → target home

> Relocation of already-referenced files is executed in owner-approved steps
> because these files have inbound links from repo-root `README.md`,
> `STRATFORGE_ГЕНЕРАЛЬНЫЙ_ПЛАН.md`, `docs/AGENTS.md` and each other. Each move is
> a `git mv` plus a reference rewrite in every referrer, verified by the
> markdown link audit (`tools/release_static_scan.py --scan markdown` and
> `tests/test_phase10_docs_governance.py`). No move lands with a broken link.

### → docs/agents/
`AGENTS.md`, `AGENT_PERSONAS.md`, `AI_ACCOUNTANT.md`, `AI_CHART_OPERATOR.md`,
`AI_DIALOGUE_CONTRACT.md`, `AI_LAB_CLOUD_AGENTS.md`, `AI_MANAGEMENT.md`,
`AI_NEWS_AGENT.md`, `AI_STRATEGY_ANALYST.md`, `CHIEF_AI_AGENT.md`, `VITEK.md`

### → docs/architecture/
`CONNECTOR_PROTOCOL_V1.md`, `DATA_PLATFORM_ARCHITECTURE.md`, `job-schema.md`,
`MARKET_DATA_CACHE_AND_FANOUT.md`, `MARKET_DATA_IPC.md`,
`MARKET_DATA_RESILIENCE_PLAN.md`, `MARKET_DATA_USER_ENTITLEMENT_STRATEGY.md`,
`MULTI_USER_ACCOUNT_ARCHITECTURE.md`, `TELEGRAM_MINI_APP.md`, `UI_API_MAP.md`,
`UI_ARCHITECTURE.md`, `UI_ROUTES_AND_ROLLBACK.md`

### → docs/operations/
`CONNECTOR_INSTALL_GUIDE.md`, `manual-validation.md`, `MARKET_DATA_BACKUP_MATRIX.md`,
`MARKET_DATA_PRODUCTION_RUNBOOK.md`, `POSTGRESQL_REDIS_MIGRATION_PLAN.md`,
`PRODUCTION_BLUE_GREEN_RUNBOOK.md`, `PRODUCTION_DEPLOYMENT_RUNBOOK.md`,
`PRODUCTION_OPERATIONS_RUNBOOK.md`, `PRODUCTION_STORAGE_RUNBOOK.md`,
`PRODUCTION_TELEGRAM_RUNBOOK.md`, `PRODUCTION_WORKER_RUNBOOK.md`, `STAGING_QA.md`,
`UI_OPERATIONS.md` (and remove the duplicate root `repository-hygiene.md`; the
canonical copy is `docs/operations/repository-hygiene.md`)

### → docs/strategies/
`AI_STRATEGY_LAB_QUALITY.md`, `AI_STRATEGY_LAB_RUN_CONTROLS.md`,
`STRATEGY_LIFECYCLE.md`, `STRATEGY_RECOVERY.md`, `simple-validation-strategy.md`,
`risk-profile.md`

### → docs/product/
`MARKET_DATA_VISUAL_ACCEPTANCE.md`, `UI_PARITY_MATRIX.md`, `UI_VERIFICATION.md`

### → docs/security/
`RESILIENCE_SECURITY_BACKLOG_2026-07-10.md` (after extracting still-current items;
the dated snapshot itself is archived — see below)

### → docs/changelog/
`UI_INTEGRATION_LOG.md` (running integration log)

### → docs/archive/ (superseded, historical only)
`AI_AGENT_STACK_RESEARCH_2026-07-01.md`, `c015_c016_failure_audit_20260527.md`,
`CODEX_CRASH_INVESTIGATION_2026-07-16.md`, `CODEX_RUN_STATE_2026-07-16.md`,
`LAST_CHANGE_AUDIT_2026-07-17.md`, `MARKET_DATA_BASELINE_2026-07-16.md`,
`MARKET_DATA_ENGINEERING_STATUS_2026-07-16.md`,
`MARKET_DATA_RUNTIME_FAILURE_2026-07-16.md`, `PRODUCTION_READINESS_2026-07-13.md`,
`RESILIENCE_SECURITY_BACKLOG_2026-07-10.md`, `STAGE7_LOAD_REPORT_2026-07-21.md`,
`STRATFORGE_ORCHESTRATOR_BACKLOG_AUDIT_2026-07-17.md`,
`STRATFORGE_ORCHESTRATOR_BACKLOG_ISSUES_1-210_SOURCE.md`,
`STRATFORGE_RELEASE_AUDIT_2026-07-15.md`

### → docs/archive/audits/
`PRODUCT_MODES_AND_CONTOURS_AUDIT_2026-07-18.md` →
`docs/archive/audits/2026-07-18-product-contours.md` (per master plan §9.2)

## Governance docs

`docs/governance/*.md` are the **rendered** human layer. The editable source of
truth is `data/governance/*` (`laws.json`, `documents.json`, `change_log.jsonl`,
`goals.json`). Rendered files (`README/OVERVIEW/LAWS/LOCAL_AI_LAWS/SYNC_MAP`) are
regenerated on backend start and must not be hand-edited. Global governance is a
single global store; there is no workspace-scoped governance and no strategy
override may mutate it (enforced server-side — see the Phase 10 evidence).

## Amendment workflow

Every owner-requested change to governance/global docs records model, tool,
requester, UTC date and scope in the changed document and in
`data/governance/change_log.jsonl`. Global governance mutations
(`POST /api/governance/laws|documents`) require the owner or an explicitly
delegated `docs.manage_global` capability; read access stays at the `documents`
capability.
