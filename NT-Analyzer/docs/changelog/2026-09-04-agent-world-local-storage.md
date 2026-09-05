# Agent World: durable local storage foundation

- Change status: `IN DEVELOPMENT`; bounded storage component for the owner-review task.
- Local version: `0.10.0-beta.96`, unchanged.
- Source base: `d5d07ac6817cd10f57d916dab0ce655347a8cbde`.
- Work branch: `codex/agent-world-storage`; integration branch: `codex/agent-world-owner-preview`.
- Business requester: project owner. Implementation: AI-assisted change.
- Integration commit/PR and final task evidence are recorded by the parent
  owner-preview task; this component is not a separate release candidate.

## Change summary

Added development-only SQLite WAL persistence for the reviewed Agent World
contracts. A single transaction commits the current entity, immutable revision,
reference-only event, outbox entry and exact idempotent replay result. Concurrent
updates use compare-and-swap; failed commits leave none of those writes behind.
Stable signed cursors bind the database, environment, workspace, user and filter,
preserve the original revision snapshot and report a gap after an earlier restore.

Immutable JSON, inert SVG and PNG artifacts are content-addressed within tenant
and owner scope, bounded to 256 KiB, and hash-verified on read. Record writes
reject missing or inaccessible artifact/entity revisions. Private Memory,
artifact lookup, original replay and event delivery cannot cross the owner
boundary. Other record reads may be workspace-visible only after the existing
service admission checks; this module does not authenticate a request.

The new module does not create another job queue, permission engine, budget
ledger, router, execution engine or background dispatcher. Stored external
budget/command/credential references remain owned by their existing services.
The caller still validates membership, capabilities, feature flags and access.

## Verification

- `python -m pytest -q tests/test_agent_world_storage.py`: **57 passed**.
- Python compilation of the two new modules and storage tests: **PASS**.
- Combined initial storage/foundation run: 269 passed; the stage-1-only
  no-runtime-IO assertion rejected the newly authorized SQLite adapter. The
  shared assertion is intentionally left to the integration owner to narrow
  to the pure contract modules while adding runtime boundary checks.
- Full regression, context/bundle gates, browser acceptance and final Git/CI
  closeout belong to the integrated owner-preview checkpoint; not claimed here.

## Release impact and limitations

The additive storage/codec modules are intended for the same current Local
build. No existing database is migrated, no runtime starts at import, no feature
flag is changed by this component and no prior subsystem is rewritten. The
constructor rejects Canary/Production before touching the filesystem and
rejects an unrelated SQLite database. PostgreSQL/RLS acceptance remains an
implementation gap, not a claimed passing scenario.

Revisions, events and inbox/outbox evidence are append-only through the public
interface. Outbox delivery scheduling, retention/garbage collection, online
backup administration and PostgreSQL implementation are outside this bounded
slice. Artifacts written before a failed graph commit may remain unreferenced;
there is no unsafe automatic deletion. Owner Preview must pass its existing
isolated path; this repository never selects or copies owner data itself.

No Canary/Production deployment, release, merge, version bump or production
secrets/database operation was performed. Shared current documents and the
External GPT Context Pack are updated by the integration owner in the same
owner-preview task.

## Test-isolation follow-up

The new gateway tests exposed an existing order dependency in the shared
`preview_env` test fixture. Dataset seeding directly sets
`STRATFORGE_PREVIEW_PROMO_CODE`, but the fixture previously did not register that
environment variable for restoration. A seeded synthetic scenario followed by
the fresh-runtime identity test reproduced the failure without any gateway code.

The shared fixture now starts that variable empty through `monkeypatch.setenv`,
which also restores its caller's environment at teardown. A two-fixture
regression checks both empty initialization and restoration after a direct
synthetic assignment. The original empty-promo assertion is unchanged. No
application/runtime code or user data was changed by this follow-up.

Verification: reproduction order plus new regression **3 passed**; full Preview
sandbox module **23 passed**; root owner-preview gateway module followed by the
fresh-runtime identity test **17 passed** with the same fixture fix applied
in-memory through a pytest hook (root files remained read-only).
