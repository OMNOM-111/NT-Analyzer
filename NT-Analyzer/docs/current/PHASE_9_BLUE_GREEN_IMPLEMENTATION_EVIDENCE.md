# Phase 9 — Blue-green Production deployment tooling — Implementation Evidence

**Status: Phase 9 — IMPLEMENTATION CLOSED; GIT CLOSEOUT COMPLETE; EXTERNAL BLUE-GREEN / PRODUCTION DEPLOYMENT ACCEPTANCE PENDING OWNER APPROVAL.**
This is explicitly **NOT STAGE CLOSED**: no real Canary deployment, no real
exact-artifact Production promotion and no real blue-green traffic switch were
executed against real infrastructure.

This document contains no secrets, signing keys, tokens, real DSNs or absolute
host paths.

## 1. Source state

- Repository: `OMNOM-111/NT-Analyzer`.
- Integration branch: `release/0.10.0-next-architecture` at `34db249a` (Phase 8 closeout).
- Phase branch: `phase/9-blue-green`, created from `34db249a`.
- Baseline `origin/main` (`72f46a1a`) untouched.

## 2. Files created / changed

Created:
- `app/blue_green.py` — the blue-green deployment engine (fail-closed dry-run).
- `app/production_storage/migrations/0010_blue_green_deploy_steps.sql` — additive expand-only migration.
- `deploy/production/blue-green/README.md` — blue-green symlink-switch deployment model (template-only, secret-free).
- `deploy/production/blue-green/switch-release.sh.example` — reference symlink-switch script (refuses to run without explicit confirm; secret-free).
- `deploy/production/blue-green/stratforge-release@.service.example` — templated per-slot API systemd unit.
- `docs/PRODUCTION_BLUE_GREEN_RUNBOOK.md` — the blue-green deployment runbook.
- `tests/test_phase9_blue_green.py` — focused Phase 9 tests.
- `docs/current/PHASE_9_BLUE_GREEN_IMPLEMENTATION_EVIDENCE.md` — this evidence.

Changed:
- `app/release_center.py` — imported `blue_green`; added `deploy_steps`/`maintenance`/`rehearsals` to the release document (`_default_doc`/`_normalize`); `_run_deploy_adapter` now delegates to the blue-green engine (unchanged `status`/`external_result` contract); new `_record_deploy_plan` persists the deploy step log + maintenance window during Canary and Production deployment; `get_release`/`list_releases` surface `deploy_steps`/`maintenance`/`rehearsals`/`blue_green`; `rollback_production` records the rollback traffic-switch plan as evidence; new `rehearse_blue_green` operation.
- `app/server.py` — wired `POST /api/admin/releases/{id}/rehearse-bluegreen` (capability `releases.deploy_canary`).
- `app/static/aurora/assets/api.js` — `adminReleaseRehearse`.
- `app/static/aurora/assets/ui.js` — Release Center detail drawer «Blue-green деплой» section (steps, maintenance windows, rehearsals) + rehearsal buttons.
- `tests/test_production_storage.py`, `tests/test_production_workers.py`, `tests/test_stage8_postgresql.py` — bumped the live-PostgreSQL migration count to 10 (skipped without a real DB; updated for correctness).
- `docs/current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md` — Phase 9 status + evidence.

## 3. Data model and migration

`0010_blue_green_deploy_steps.sql` is additive expand-only (no `DROP TABLE`, no
`DROP COLUMN`, no destructive contract, no data migration). It creates two
initially empty tables:

- `sf_release_deploy_steps` — the per-stage blue-green deployment step log
  (step_id UUID, deployment_id/candidate_id FKs, environment, strategy, stage,
  ordinal, status, active_slot, target_slot, redacted evidence JSON).
- `sf_maintenance_windows` — maintenance-window records (window_id UUID,
  candidate_id FK, environment, kind, state, reason, scheduled/opened/closed
  timestamps, redacted document JSON).

Both tables are a global administrative control plane, so each enables and forces
row level security with a global-scope-only policy (`sf_scope_global()`), never
workspace/user readable. The migration is auto-discovered by `MigrationRunner`;
`latest_version` becomes 10. No signing key, token, raw credential or absolute
host path is stored — only public build identity, slot names, stage status and
redacted evidence.

The Development runtime keeps the deploy step log and maintenance windows inside
the encrypted Release Center document (`deploy_steps`/`maintenance`/`rehearsals`
lists); Production uses the same PostgreSQL document/repository path as the rest
of the Release Center.

## 4. API and permissions

- `POST /api/admin/releases/{id}/rehearse-bluegreen` — `releases.deploy_canary`.
  Runs a dry-run blue-green rehearsal (no state change) and records it.
- `GET /api/admin/releases` and `GET /api/admin/releases/{id}` now also return
  `blue_green` (strategy status), `deploy_steps`, `maintenance` and `rehearsals`.

The owner always has every capability; a delegated admin needs the explicit
`releases.deploy_canary` grant; an ordinary user is denied server-side. No new
capability was introduced — Phase 9 reuses the existing `releases.*` catalog.

## 5. UI states and actions

The Release Center detail drawer gains a «Blue-green деплой» section that shows
the strategy (symlink model, dry-run mode, slots), the ordered deployment step
log with per-stage status badges (`dry_run`/`pending`/`blocked`/`skipped`),
maintenance windows and recent rehearsals. Owners and delegated release admins
get «Репетиция blue-green (production/canary)» buttons that call the rehearsal
endpoint. The UI never claims a real deployment occurred; every stage is shown as
a dry-run/pending plan and the external result stays PENDING.

## 6. Blue-green mechanism (owner decision #7 — symlink/current-release switch)

Two release slots (`blue`/`green`) with one atomic `current` symlink. The ordered
deployment plan is:

1. `prepare_green` — stage the promoted immutable artifact into the idle slot.
2. `expand_migrate` — run only online-safe expand (additive) migrations.
3. `start_green` — start the green instance beside blue.
4. `green_readiness` — gate on the full `service_readiness` contract.
5. `drain_blue` — stop intake and drain in-flight NinjaTrader leases/jobs within
   `worker_shutdown_grace_sec` (never force-terminated in a dry-run).
6. `switch_traffic` — atomically repoint `current` to green inside a recorded
   maintenance window; webhook/outbox deliveries are de-duplicated by idempotency
   key so neither slot double-processes.
7. `verify_live` — confirm green is serving.
8. `contract_migrate` — deferred destructive contract migrations, only after
   green is stable.

Rollback is the reverse symlink switch to a previous, known-compatible slot,
preserving persistent data.

## 7. Expand → migrate → contract compatibility

`blue_green.classify_migrations` splits migrations into online-safe **expand**
(additive) and offline **contract** (destructive) phases. A migration is contract
if it drops a table/column/constraint, rewrites a column type, sets `NOT NULL`,
renames, truncates or deletes rows; guarded idempotent `DROP POLICY/INDEX/TRIGGER/
FUNCTION IF EXISTS` are online-safe. In a dry-run without a live target DB the
*pending* migration set is unknown, so the expand stage is honestly reported as
`pending` (never fabricated as safe or blocked); the whole historical migration
set is deliberately **not** treated as pending. When an explicit pending set
contains a contract migration, the online expand stage is `blocked` and the
contract migration is deferred behind green stability.

## 8. Worker drain, webhook/outbox de-duplication, readiness, rollback

- `plan_worker_drain` — stops intake and waits for active NinjaTrader leases +
  in-flight jobs within the grace deadline; `forced` is always False in a
  dry-run.
- `dedupe_events` — idempotency keys for replayed Telegram webhook updates and
  outbox messages so a blue-green overlap never double-processes a delivery.
- `green_readiness` — reports the readiness contract as `pending` (never a real
  `pass`, because the green instance is not actually started here).
- `plan_traffic_switch` / `plan_rollback_switch` — atomic, reversible symlink
  switches; the rollback switch preserves persistent data and uses a
  release-relative reference only (never an absolute host path).

## 9. Fail-closed dry-run + no real deployment

`blue_green.deployment_strategy` reports `real_available: False` regardless of
configuration; a named real executor (`STRATFORGE_BLUEGREEN_EXECUTOR`) makes
`execute_deployment` return `blocked` with a PENDING external result, and an
unset executor returns a local `dry_run` with a PENDING external result. The
Release Center therefore leaves Production in `production_deploying`; only the
separate owner-confirmed `mark-production-live` advances to `production_live`, so
a dry-run can never fabricate a real live deployment.

## 10. Commands run and results

- Focused: `tests/test_phase9_blue_green.py` → **43 passed**.
- Phase 8 + migration-count suites (`test_phase8_release_center`,
  `test_production_storage`, `test_production_workers`, `test_stage8_postgresql`,
  `test_deployment_config`) → **54 passed, 31 skipped**.
- Full regression: `python -m pytest -q -p no:cacheprovider` → **1136 passed, 31 skipped**.
- `python -m compileall -q app tools tests` → PASS.
- `node --check app/static/aurora/assets/ui.js` and `.../api.js` → PASS.
- `python tools/release_static_scan.py` → CSP OK, SECRETS OK, MARKDOWN OK.
- `git diff --check` → clean (only pre-existing CRLF/LF notices on unrelated stray files).

## 11. Exact passed/skipped totals

- Focused Phase 9: 43 passed.
- Full repository: 1136 passed, 31 skipped (the 31 skips are the live-PostgreSQL
  and other environment-gated suites that require external services not present
  locally/CI).

## 12. Errors encountered and root cause

1. `test_rollback_records_traffic_switch_evidence` initially rolled back directly
   from `production_deploying`, which the Phase 8 transition map does not allow
   (rollback is valid from `production_live`/`production_failed`). Root cause:
   test path, not product code. Fixed by advancing through the owner-confirmed
   `mark-production-live` before rolling back. The pre-existing Phase 8 rollback
   guard was intentionally left unchanged (no scope creep).
2. `test_migration_0010_is_additive` initially failed because the migration
   comment literally contained "DROP TABLE"/"DROP COLUMN". Root cause: comment
   wording, not schema. Fixed by rewording the comment to "no destructive
   contract, no DROP, no data migration" (mirroring migration 0009). The schema
   remains additive expand-only.

## 13. Fix and added regression coverage

Both fixes are covered by the focused suite (rollback evidence test and
`test_migration_0010_is_additive` / `test_migration_set_still_starts_at_one_and_is_contiguous`).
The conservative contract classification of the real migration set (0004
`SET NOT NULL`) is asserted by `test_classify_real_migration_set_flags_set_not_null`.
No product assertion was weakened.

## 14. Dry-run-only actions

- Every deployment stage (prepare/expand/start/readiness/drain/switch/verify/
  contract) is a planning dry-run; nothing is deployed, migrated, drained or
  switched, and the external result is always PENDING.
- Rehearsals have no side effects beyond recording the rehearsal plan.

## 15. Real external checks NOT performed

- No real Canary deployment, no real exact-artifact Production promotion and no
  real blue-green traffic switch.
- No SSH, systemd, symlink switch, DNS, Cloudflare or database command.
- No real signing key, Production credential, Telegram credential or Connector
  session was used.
- No migration was applied to any real database (the live-PostgreSQL migration
  tests are skipped without `STRATFORGE_TEST_POSTGRES_*`).
- Browser QA was not run per the workspace stability policy; the UI was validated
  via `node --check`, source/DOM review and the static scan.

## 16. Rollback procedure

Revert the Phase 9 implementation commit on `phase/9-blue-green` (or the
integration merge commit). Migration 0010 is additive expand-only; its two tables
start empty, so no data rollback is required and they can be dropped in an
isolated environment if ever needed. `app/blue_green.py` is pure and inert unless
the Release Center drives a deployment/rehearsal; the deploy templates and runbook
are inert without an explicit real executor and operator action.

## 17. Known risks and owner decisions

- The real blue-green executor is intentionally not wired; the engine interface
  is designed so a later phase can add a real blue-green/symlink executor without
  rewriting the Release Center. Until then, deployment is dry-run only.
- Owner decision #7 (symlink/current-release switch first) is implemented as the
  deployment model. Containerization remains a separate future ADR.
- The conservative migration classifier flags `SET NOT NULL` (and column type
  rewrites, drops, renames, truncates, deletes) as contract-phase; deployments
  with such pending migrations are held for the deferred contract stage.
- Real Canary/Production acceptance (a real separate Canary deployment and an
  exact-artifact Production blue-green promotion against real infrastructure)
  remains an owner-gated external step.

## 18. Commit / PR / CI / merge evidence

- Implementation commit: `86b0ed4e` on `phase/9-blue-green` (from integration `34db249a`).
- PR: [#15](https://github.com/OMNOM-111/NT-Analyzer/pull/15) → base `release/0.10.0-next-architecture`.
- CI ([Actions run 30825143931](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30825143931)): Static gates PASS; Tests (ubuntu-latest) PASS; Tests (windows-latest) PASS. The Node.js 20 deprecation annotation on `actions/checkout@v4`/`actions/setup-python@v5` is non-blocking (checks SUCCESS).
- Merge commit: `3a787c6a`; task branch `phase/9-blue-green` deleted locally and on origin; integration `release/0.10.0-next-architecture` in sync with origin after merge.
- Extraneous dirty/untracked files (`data/catalog/margins.json`, `data/development/durable/nt_analyzer.sqlite3`, `data/development/audit/`, `data/development/integrations/`, `data/governance-rendered/*`, `docs/AGENT_PERSONAS.md`, `docs/governance/*`) were preserved on disk and remained outside the Phase 9 delivery.
- Real blue-green/Production acceptance (a real separate Canary deployment and a real exact-artifact Production blue-green promotion against real infrastructure) remains an owner-gated external step; the stage is not STAGE CLOSED.
