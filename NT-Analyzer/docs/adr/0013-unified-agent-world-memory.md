# ADR-0013: Unified Agent World memory service and context graph

- Status: Accepted for disabled-by-default Development implementation.
- Decision date: 2026-09-21.
- Business requester: project owner. Implementation attribution: AI-assisted change.
- Runtime and release impact: none until separately enabled; no Local restart,
  database migration, Canary, Production or server change is authorized here.

## Decision

Agent World has one application boundary for memory: `MemoryService`. The Chief
Agent, chat and specialist agents receive memory context through that boundary.
During migration it reads the existing scoped Chief JSONL history and canonical
Agent World records together. JSONL remains read-only input to the service and
continues to be the default writer until a loss-accounted reconciliation passes.

The existing `contracts.Memory` record is unchanged and remains the fact unit.
Its provenance, verification, retention, sensitivity, visibility and scope
rules stay authoritative. Three additive record kinds use the existing generic
Agent World ledger and artifact store:

- `KnowledgeEntity` is a resolved graph node;
- `Relationship` is an evidenced, time-bounded typed edge;
- `KnowledgeSource` keeps a stable first-ingest identity and content versions.

SQLite and PostgreSQL already store typed Agent World records through the same
generic `kind + revision + artifact + event` contract, so these kinds need no
parallel database and no schema-specific table. PostgreSQL continues to use its
existing FORCE RLS policies; SQLite continues to use the same scoped repository.
The relationship registry is closed and currently includes `USED_MODEL`,
`DERIVED_FROM`, `VERIFIED_BY`, `SUPERSEDES`, `CONTRADICTS`, `ABOUT` and the other
declared types. Unknown types fail closed.

## Stable identity and retrieval

A source receives `source_id` at first ingestion. Later readers persist and
submit that ID, so a simultaneous rename and content change does not create a
new source. `source_version_id` is content-addressed, while logical
`fragment_id` is derived only from `source_id + normalized section anchor`.
Each changed source version creates a new fact for the stable fragment and an
evidenced `DERIVED_FROM` edge; history is not overwritten.

`ContextBuilder` replaces the old latest-N/character-only selection. It performs
candidate collection, relevance scoring (lexical/entity/graph/task/verified/
recency), authorization, duplicate removal and an explicit token budget.
Expired/revoked/superseded facts are excluded. `CONTRADICTS` is returned as a
visible conflict instead of silently selecting one assertion.

## Migration and cutover

The required order is read → identifiers → relationships → retrieval → migration
→ write. `LegacyMemoryMigration` normalizes content, deduplicates, resolves named
entities and emits a reconciliation with source total, migrated history,
deduplicated rows, intentional exclusions and losses. Cutover is rejected unless
all source rows are accounted for, all planned history is applied, losses are
empty, and the archive is declared read-only and not deleted.

Writing is controlled by server flags. The safe default remains legacy JSONL.
After reconciliation, canonical-write enables dual write. A second dependent
flag makes JSONL an archive and selects canonical-only write. Disabling the
flags is the rollback. Existing files are never deleted or rewritten by this
change.

## Privacy and external-model boundary

All graph records are owner-private, repository-scoped and tenant-bound.
Canonical memory is not added to external model prompts by default. That path
has its own disabled flag because sending confidential memory to an external
provider is a separate data-egress decision. Enabling memory storage does not
grant provider access, permissions or cross-user visibility.

No vector or graph database is introduced. The implementation records token
use, irrelevant/stale selections, conflicts and task success cohorts. A new
database is considered only after these measurements demonstrate a PostgreSQL
limit.
