# Unified Agent World memory service

- Date: 2026-09-21
- Status: `IN DEVELOPMENT`; implementation present, all new runtime gates OFF.
- Source: branch `codex/unified-memory-service`; implementation commit
  `2a0c08de225beb8b902f060b54ddeaaf0b1089a5`; [PR #290](https://github.com/OMNOM-111/NT-Analyzer/pull/290).
- Release impact: code and documentation only. No release, Local restart,
  working-data migration, Canary/Production action or server change.

## Why

Chief chat JSONL and Agent World `Memory` previously formed two independent
memory paths. Chat selected recent rows under an 8000-character budget, while
Agent World records were not part of agent execution context. Source fragments
also lacked rename-stable identities.

## User-visible and architectural change

- A single `MemoryService` now composes scoped legacy and canonical reads.
  Chief chat and the existing specialist-agent scope consume its context packet.
- The `Memory` contract was not rewritten. Additive `KnowledgeEntity`,
  `Relationship` and `KnowledgeSource` records use the existing SQLite and
  PostgreSQL Agent World repositories and evidence artifacts.
- Sources use stable first-read IDs, content-addressed versions and stable
  section-anchor fragment IDs. A simultaneous rename/content change is supported
  when the persisted source ID is supplied.
- `ContextBuilder` performs relevance scoring, graph distance, task/verification/
  recency weighting, access filtering, deduplication and token budgeting.
- Retention and validity windows are enforced; `SUPERSEDES` removes obsolete
  facts and `CONTRADICTS` is exposed in the returned context.
- Legacy migration has an explicit no-loss reconciliation and a reversible
  legacy → dual → canonical write state machine. The old JSONL remains a
  read-only archive after cutover and is never deleted.
- Retrieval metrics cover tokens per task, irrelevant/stale selections,
  conflicts and success with/without memory. No vector or graph database was
  added.

## Safety and activation state

`AI_MEMORY_UNIFIED_READ`, `AI_MEMORY_EXTERNAL_CONTEXT`,
`AI_MEMORY_CANONICAL_WRITE` and `AI_MEMORY_LEGACY_ARCHIVE_ONLY` are trusted
server-side flags with dependencies and default OFF. The protected Local owner
chat therefore keeps its current read/write behavior. Canonical memory is not
sent to external model prompts without the separate egress flag. User/workspace
and owner-only isolation remains enforced by repository scope and record checks.

## Verification

The implementation has focused contract, SQLite repository, Context Builder,
migration, metrics and Chief-agent regression coverage:

- final focused memory/migration/graph/metrics/Chief suite after code review:
  **127 passed**;
- exact-final-tree `test_agent_world_*` suite: **2944 passed, 79 skipped,
  0 failed** in 3390.63 s;
- AI Lab knowledge/domain-agent/Orchestrator regression: **46 passed**;
- changed Python modules compile: **PASS**;
- External GPT Context validator: **PASS** (the pack-wide deployment SHA remains
  the documented historical deployment anchor, not this undeployed branch);
- production bundle: **623 files, 4/4 gates PASS** (static scan in bundle,
  runtime reads shipped, Python compile, shipped JavaScript syntax);
- `git diff --check`: **PASS**.

Focused and complete counts overlap and are not added together. An earlier full
run before the last fail-closed source-ID/temporal hardening was also green
(2942 passed, 79 skipped), but is not used as final-tree evidence. The 79 skips are
reported, not treated as success. PostgreSQL behavior shares the generic record
codec/repository, but a live disposable PostgreSQL run is not claimed by this
Local-only task.

## Canonical design

See [ADR-0013](https://github.com/OMNOM-111/NT-Analyzer/blob/codex/unified-memory-service/NT-Analyzer/docs/adr/0013-unified-agent-world-memory.md).
`docs/adr/` is an accepted developer-only bundle exclusion; the shipped
changelog therefore uses the immutable repository path instead of a broken
artifact-local link. The protected Local server and its database were not touched.
