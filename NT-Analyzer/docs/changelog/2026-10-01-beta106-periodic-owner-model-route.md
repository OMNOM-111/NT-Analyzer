# beta.106 — server route for periodic owner reports

Release title: Periodic owner report server route.
Release summary: Monthly, quarterly and weekly SF Chat reports use the existing
owner-scoped Agent World model and ServerSecrets on Canary and Production,
while daily remains deterministic and Local keeps its legacy route.
Release PRs: pending.
Affected subsystems: SF Chat periodic reporting, Agent World model execution,
PostgreSQL owner records, ServerSecrets, provider budget and usage accounting.
Release impact: Narrow correction of the beta.105 Production reporting blocker;
no new secrets, permissions, schema, provider, product feature or sender.

## What changes

- Server-only non-daily reports resolve the one active general owner model from
  the existing PostgreSQL Agent World store and decrypt its existing credential
  through the existing ServerSecrets path.
- Every read and provider transmission revalidates the exact owner runtime,
  active account, workspace membership, capabilities and workspace budget.
- Daily reports remain deterministic; Development/Local keeps the legacy
  orchestrator registry; the scheduler, delivery idempotency and sender gates
  remain unchanged.

## Root cause and boundaries

Production beta.105 successfully delivered `daily:2026-09-30`, but
`monthly:2026-09` and `quarterly:2026-Q3` failed before provider dispatch.
The Linux periodic path still called the legacy `agent_router`, whose DPAPI-only
Local registry is intentionally empty on the server. The already verified
owner Gemini connection lived in PostgreSQL and ServerSecrets, but this route
did not consume it.

This change does not add or copy credentials, change sharing, grant access,
change schedules, add a model fallback, or enable another sender. Selection
fails closed unless there is exactly one active owner general Persona model.
Production beta.105, its beta.104 previous slot and all durable failed events
remain the rollback/evidence boundary until beta.106 passes Canary.

## Development verification

- Python compilation: PASS for both application files and both changed test
  files.
- New route/cache/deterministic tests: 8 PASS.
- Related aggregate regression (`chief_agent`, periodic route, Agent World
  models/server parity, owner-model migration and Vitek delivery): 336 PASS.
- Full repository collection with a repository-local `--basetemp`: 6,131 PASS,
  140 skipped and 13 intentional isolation failures because the temporary root
  was inside the repository. The complete affected isolation/preflight subset
  was repeated with an external temporary root: 91 PASS, 1 skipped, 0 failed.
  The remaining release proof is the clean PR/final-main CI run.
- `NT-Analyzer/.pytest-tmp/` contains local pytest runtime output only and is
  excluded from the release commit.

PR/source SHA/CI/artifact: pending.
Verification result: **Development PASS; PR/CI, immutable artifact, Canary and
Production pending.**
