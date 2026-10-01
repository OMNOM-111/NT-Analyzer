# beta.106 — server route for periodic owner reports

Release title: Periodic owner report server route.
Release summary: Monthly, quarterly and weekly SF Chat reports use the existing
owner-scoped Agent World model and ServerSecrets on Canary and Production,
while daily remains deterministic and Local keeps its legacy route.
Release PRs: [#311](https://github.com/OMNOM-111/NT-Analyzer/pull/311).
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
Production beta.105 remains the previous/rollback boundary. The durable failed
beta.105 events remain evidence of the original route failure.

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
  Clean PR and final-main CI are PASS.
- `NT-Analyzer/.pytest-tmp/` contains local pytest runtime output only and is
  excluded from the release commit.

## Release evidence

- PR #311 merged to exact `main`
  `e7ecd2133c65f7ec6ce2bf8dc02eb797819ea885`; mandatory final-main CI
  [36857075970](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/36857075970)
  PASS.
- Candidate `rc_2243013e617841c3864dee1a09c77dc4` produced one signed immutable
  artifact `art_7aebf504ae354ce7981c58359a1ff546`, build
  `sf-0.10.0-beta.106-e7ecd2133c65-20261001T150927Z`, archive SHA256
  `6BD446E5ACB60D74425765550DDA09F2059481822586F24EB78579544128EA25`
  and manifest/runtime SHA256
  `0579C9C3FFD089EC91426D6F75B4E7ED257C612D9FBDD1F958561A50BEB0929C`.
- Canary deployment `dep_5e468f9b9cb04df68aec4e9184882dc4` passed public
  `/live`, `/ready`, identity and non-sender checks. Acceptance check
  `chk_8da170bf754e47f3aa03dd0e1e666642` recorded PASS.
- The same artifact reached Production as deployment
  `dep_bf86528c36c944d1a5906f0586126b93`; Release Center recorded
  `production_live`, `same_immutable_artifact=true`, signature/readiness PASS.
  Public Production `/live` and `/ready` return beta.106, the exact source SHA,
  build and runtime artifact; all readiness checks are green.

## Remaining acceptance

The authenticated Production status after promotion reports no queued/running
events, no event error, and `last_event_type=startup_audit` at
`2026-10-01T15:26:23Z`. Attempts to submit the three owner-only report events
through browser automation did not reach the API, so no duplicate or unknown
report execution exists. Real `monthly:2026-09`, `quarterly:2026-Q3` and
`daily:2026-10-01` SF Chat/Telegram message and outbox IDs are not yet recorded.
The code release is live, but periodic delivery acceptance and the product-card
closeout remain **PARTIAL**; do not mark `STAGE CLOSED` until those receipts PASS.

Verification result: **PR/CI, immutable artifact, Canary and same-artifact
Production PASS; real month/quarter/daily delivery acceptance PENDING.**
