# Phase 8 — Release Center Implementation Evidence

История поправки: 2026-08-03T06:58:46Z; внёс `GitHub Copilot`; scope: Phase 8 — зафиксировать реализацию Release Center (immutable-artifact promotion state machine, data model, API, UI, dry-run adapter, тесты, ограничения и внешние acceptance gates).

**Status: Phase 8 — IMPLEMENTATION COMPLETE; REAL CANARY DEPLOYMENT / PRODUCTION PROMOTION ACCEPTANCE PENDING OWNER APPROVAL.**
This is explicitly **NOT STAGE CLOSED**: no real Canary deployment and no
exact-artifact Production promotion were executed against real infrastructure.

This document contains no secrets, signing keys, tokens or real DSNs.

## 1. Source state

- Repository: `OMNOM-111/NT-Analyzer`.
- Integration branch: `release/0.10.0-next-architecture` at `66ae6c7a` (Phase 7 closeout).
- Phase branch: `phase/8-release-center`, created from `66ae6c7a`.
- Baseline `origin/main` (`72f46a1a`) untouched.

## 2. Files created / changed

Created:
- `app/production_storage/migrations/0009_release_center.sql` — additive expand-only migration.
- `app/release_center.py` — the Release Center core (state machine, invariants, store, adapter, scheduling, notifications, step-up).
- `tests/test_phase8_release_center.py` — focused Phase 8 tests.
- `docs/current/PHASE_8_RELEASE_CENTER_IMPLEMENTATION_EVIDENCE.md` — this evidence.

Changed:
- `app/permissions.py` — added `("/api/admin/releases", "releases.view")` to `ADMIN_ROUTE_CAPABILITY` (the `releases.*` capabilities already existed in the catalog).
- `app/server.py` — imported `release_center`; added `_releases_get`, `_releases_post`, `_release_action`, `_release_context`, `_require_release_capability`; wired the GET and POST routes.
- `app/static/aurora/assets/api.js` — `adminReleases`, `adminRelease`, `adminReleaseCreate`, `adminReleaseAction`.
- `app/static/aurora/assets/ui.js` — the `releases` admin module: `renderReleaseCenterInto`, `openReleaseDetail`, `runReleaseAction`, action gating and a critical-action confirmation.
- `tests/test_production_storage.py`, `tests/test_production_workers.py`, `tests/test_stage8_postgresql.py` — bumped the live-PostgreSQL migration count to 9 (these are skipped without a real DB; updated for correctness).

## 3. Data model and migration

`0009_release_center.sql` is additive expand-only (no `DROP`, no destructive
contract, no data migration). It creates eight initially empty tables:
`sf_release_artifacts`, `sf_release_candidates`, `sf_release_deployments`,
`sf_release_checks`, `sf_release_approvals`, `sf_release_rollbacks`,
`sf_release_notifications`, `sf_release_events`. Required fields include
artifact UUID, app_version, release_channel, build_id, git_commit_sha,
artifact_sha256, manifest_sha256, signature algorithm/status, built_at_utc,
dirty, storage URI, environment, state, requested/approved/deployed actor UUID,
evidence JSON, failure reason, timestamps and idempotency identifiers. The
Release Center is a global administrative control plane, so every table is
global-scope only under row level security (`sf_scope_global()`), never workspace
or user readable. Unique indexes enforce idempotency and one active deployment
per candidate/environment; a unique `(artifact_sha256, manifest_sha256,
git_commit_sha, build_id)` constraint anchors exact-artifact identity. No signing
key, token or raw credential is stored. The migration is auto-discovered by
`MigrationRunner`; `latest_version` becomes 9.

Runtime storage in Development uses an encrypted document store
(`data/integrations/releases.dpapi` via `secure_store`); Production uses the
PostgreSQL document repository through `storage_router` — mirroring the Connector
module. Audit is a redacted JSONL in Development and `storage_router.append_audit`
in Production.

## 4. API and permissions

Base route gate `/api/admin/releases` → `releases.view`; each mutating action
additionally enforces its specific capability in the handler:
- `GET /api/admin/releases`, `GET /api/admin/releases/{id}` — `releases.view`.
- `POST /api/admin/releases/candidates` — `releases.create`.
- `POST /api/admin/releases/{id}/build`, `/verify`, `/cancel` — `releases.create`.
- `POST /api/admin/releases/{id}/deploy-canary`, `/record-canary-check` — `releases.deploy_canary`.
- `POST /api/admin/releases/{id}/approve-production`, `/schedule-production`, `/promote-production`, `/mark-production-live` — `releases.promote_production`.
- `POST /api/admin/releases/{id}/rollback-production` — `releases.rollback_production`.
- `POST /api/admin/releases/{id}/step-up` — begins a step-up challenge.

The owner always has every capability. A delegated admin receives only explicit
grants. An ordinary user cannot see the Release Center and is denied server-side.
Critical actions (deploy-canary, approve-production, promote-production,
rollback-production) require a fresh step-up grant (Phase 4–5 machinery); the
owner is exempt, and a delegated admin without a matching grant is rejected with
`step_up_required`.

## 5. UI states and actions

The `Центр релизов` admin module lists candidates with state, version/channel,
commit, build id, artifact SHA, manifest SHA, signature status, Canary and
Production status and failure reason. The detail drawer shows the artifact,
deployments, Canary checks, approvals, rollbacks and event history. Action
buttons appear only for transitions allowed by the current state and the actor's
capabilities. A critical action shows a confirmation listing the exact artifact,
version, commit, checksums, signature, environment and that no real deployment is
performed. The UI never claims a real deployment occurred; the dry-run adapter is
shown explicitly and the external result stays PENDING.

## 6. State machine

`draft → building → built → signed → canary_deploying → canary_checking →
canary_passed → approved_for_production → production_scheduled →
production_deploying → production_live`, with failure/terminal states
`build_failed`, `canary_failed`, `production_failed`, `rolled_back`,
`superseded`, `cancelled`. Every transition is validated server-side against an
explicit allow-map (skipped and reverse transitions are rejected), carries an
idempotency key, records an event with actor UUID and timestamp, and is audited.
A repeated request returns the remembered result without a second transition,
approval or deployment.

## 7. Artifact / signature / checksum invariants

Enforced in code and tests: a dirty worktree cannot create a publishable
candidate or a build (`dirty_worktree`); an artifact is immutable after build
(`artifact_immutable`); verification requires a `verified` signature
(`signature_invalid`) and then freezes the exact-artifact fingerprint; any drift
of artifact/manifest/commit/build after signing is rejected (`artifact_mismatch`);
Canary and Production reference the same frozen fingerprint; Production promotion
requires the matching Canary pass, a live owner approval bound to the same
fingerprint (`approval_required`, `approval_artifact_mismatch`) and a fresh
step-up; rollback only targets a previously Production-deployed artifact
(`rollback_target_unknown`, `rollback_incompatible`).

## 8. Deployment adapter (dry-run) and scheduling

The deployment adapter is a fail-closed dry-run. A real adapter is never executed
in this phase: if a real adapter name is configured it returns `blocked` with a
PENDING external result; otherwise it returns `dry_run` with a PENDING external
result and contacts no external infrastructure. `promote_production` therefore
leaves the candidate in `production_deploying` with a PENDING external result;
`production_live` is only reached by a separate owner-confirmed
`mark-production-live`, so a dry-run can never fabricate a live Production
deployment. Scheduling supports `now`, `in_5m`, `in_15m` and an explicit ISO-8601
time. The "after market close" option is disabled and returns
`market_calendar_unavailable` because no approved market-calendar provider
(timezone, holidays, early-close policy) exists yet — this is recorded as an
owner decision rather than emulated with a hard-coded time.

## 9. Commands run and results

- Focused: `tests/test_phase8_release_center.py` → **34 passed**.
- Full regression: `python -B -m pytest -q -p no:cacheprovider` → **1093 passed, 31 skipped**.
- `python -m compileall -q app tools tests` → PASS.
- `node --check app/static/aurora/assets/ui.js` and `.../api.js` → PASS.
- `python tools/release_static_scan.py` → CSP OK, SECRETS OK, MARKDOWN OK.
- `git diff --check` → clean.

## 10. Exact passed/skipped totals

- Focused Phase 8: 34 passed.
- Full repository: 1093 passed, 31 skipped (the 31 skips are the live-PostgreSQL
  and other environment-gated suites that require external services not present
  in local/CI runs).

## 11. Errors encountered

- Twenty focused tests initially failed because several test idempotency keys
  were shorter than the 8-character minimum enforced by
  `_validate_idempotency_key` (and the migration `CHECK`).

## 12. Root cause of significant errors

- The idempotency-key minimum (8 chars) is a deliberate invariant shared with the
  PostgreSQL `CHECK` constraint. The test helpers used short literals (e.g.
  `"dc-1"`). Root cause: test data, not product code.

## 13. Fix and added regression coverage

- The test idempotency keys were lengthened to satisfy the 8-character minimum.
  The minimum itself is asserted implicitly by every operation and by
  `test_migration_0009_is_additive`. No product assertion was weakened.

## 14. Dry-run-only actions

- Every Canary and Production deployment in this phase is a dry-run: the adapter
  contacts no external infrastructure, and the external result is always PENDING.
- `promote_production` records the Production deployment request and transition
  but never marks the candidate live; `mark-production-live` is a separate,
  owner-only, evidence-gated step.

## 15. Real external checks NOT performed

- No real Canary deployment and no real Production promotion.
- No SSH, Cloudflare, DNS, systemd or real database command.
- No real signing key, Production credential, Telegram credential or Connector
  session was used.
- No migration was applied to any real database (the live-PostgreSQL migration
  tests are skipped without `STRATFORGE_TEST_POSTGRES_*`).
- Browser QA was not run per the workspace stability policy; the UI was validated
  via `node --check`, source/DOM review and the static scan.

## 16. Rollback procedure

Revert the Phase 8 implementation commit on `phase/8-release-center` (or the
integration merge commit). Migration 0009 is additive expand-only; because it is
new and its tables start empty, no data rollback is required and the tables can
be dropped in an isolated environment if ever needed. `app/release_center.py`
and its routes are inert unless the Release Center is used.

## 17. Known risks and owner decisions

- The real blue-green deployment executor does not exist yet (Phase 9); the
  adapter interface is designed so Phase 9 can add it without rewriting the
  Release Center. Until then Production promotion is dry-run only.
- The "after market close" scheduling option is intentionally disabled pending an
  owner-approved market-calendar provider (owner decision recorded here).
- Real Canary/Production acceptance (a real separate Canary deployment and an
  exact-artifact Production promotion against real infrastructure) remains an
  owner-gated external step.

## 18. Commit / PR / CI / merge evidence

- Implementation commit, PR, CI (Static / Ubuntu / Windows) and merge commit are
  recorded at closeout.
