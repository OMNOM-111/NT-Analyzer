# Agent World — controlled Process Intelligence suggestions

- Release title: Structured work-pattern suggestions.
- Change summary: extend the existing manual verified-outcome routine proposal
  with read-only event analysis, explicit routine/calendar suggestion creation,
  durable suppression/deduplication and source revalidation before acceptance.
- Canonical status: **IN DEVELOPMENT**. Shared route/UI hooks and runtime
  acceptance are root-owned and are not implied by isolated contracts.
- Source / rollback: `1409553a`, `codex/agent-world-unified-acceptance`; beta.96
  unchanged. Root records the final integrated SHA/PR.
- Scope: a new `process_intelligence.py`, isolated contract tests and this record.
  No change to DomainService, domain gateway, UI, permissions, queues, scheduler,
  grants, schema or protected Local8765. No external calls or real owner data.

## Existing mechanism retained

`DomainService.suggest_routine` already accepts 2–32 explicitly selected verified
Outcomes and creates an ordinary proposed Routine. Routine/CalendarItem already
have immutable provenance, `proposed → accepted/dismissed`, and separate
acceptance into the existing manual-followup queue with automation disabled.
These mechanisms are reused, not rewritten or replaced.

The gap being closed is pattern analysis and generation of a derived Calendar
proposal, plus durable cooldown/dedup across separate requests. Process
Intelligence is not permission to enable a recurring execution schedule.

## Contract and evidence boundaries

The analyzer consumes only caller-scoped, allowed structured outcome events and
their current verified records. Existing strict immutable outcome verification
and model-task projections are reused; personal message stores are never read.
Only whitelisted task-class/time/source-reference metadata reaches a candidate.
Prompts, raw model replies, personal chats, memory, credentials and arbitrary
event payloads do not become process descriptions or executable commands.

Real application-receipt workflow occurrences are not model-quality evidence.
Diagnostics (`json_arithmetic`, bounded extraction, connection tests and Court
votes), unverified plans, synthetic sources, rejected reviews and V2 deviations
do not become professional-work patterns. Pending human source reviews remain
pending and are explicitly counted; the analyzer never accepts or closes them.

Analysis is read-only. Explicit proposal creation stores existing Routine or
CalendarItem plus a small provenance artifact. Deterministic pattern/domain
sequence identity reuses the repository's atomic idempotency/CAS: concurrent
proposal requests cannot create two records for one sequence. Existing records,
including dismissed proposals, are the durable cooldown history; there is no
new scheduler, permission, job, event inbox or side database. Repeating the same
observations does not generate new suggestions when the cooldown expires.
Shrinking the lookback window is not new work either: at least one genuinely
new source-kind/source-ID pair relative to prior proposals is needed.

Default policy requires three verified workflow occurrences on at least two UTC
dates, a thirty-day observation window and a twenty-four-hour cooldown. Cadence
is the median spacing of observations with explicitly low confidence, not a model
quality score. Calendar proposals use a visible thirty-minute review slot at the
estimated next occurrence. These are server-side defaults, never automatic
scheduler settings or hidden permission grants.

## Shared integration hooks

`ProcessIntelligence(domain_service, model_service)` requires both services to
share the same scoped repository. `analyze(context, admit)` returns candidates,
suppression/exclusion reasons and explicit incomplete-scan state. Bounded scans
that do not reach the end of their snapshot cannot produce candidates.

`propose(context, admit, domain, candidate_id, source_sha256)` accepts only the
exact currently reviewed candidate and creates the ordinary proposed record.
It does not accept that record, enqueue work, enable automation or grant rights.

Before existing acceptance, root must call `validate_suggestion(context, admit,
domain, entity_id, expected_revision)`. Non-Process-Intelligence manual records
retain the old path; managed records must still reference the same valid sources.
Changed/disputed/unavailable sources block acceptance but do not delete history,
rewrite prior errors or silently dismiss the suggestion.

## Verification

The final scoped command passed **28 tests / 0 skipped** in 135.79 seconds:
`python -m pytest tests/test_agent_world_process_intelligence.py -q --disable-warnings`.
Python compilation of the module/test file and root `git diff --check` passed.
Coverage includes read-only analysis, source/tenant isolation, existing manual
path characterization, routine/calendar proposal and separate acceptance,
concurrent exact replay, stale snapshots, durable cooldown/restart, shrinking
windows, duplicate receipts, synthetic/diagnostic exclusion, actual persisted
manual review decisions, V2 deviations and incomplete-scan fail-closed behavior.

All generated PNG/model transports in the test file are explicit disposable protocol fixtures,
not real charts/backtests/provider or audible results. Real program acceptance,
UI route wiring, full regression, current status and Context Pack 02/11 updates
remain root-owned. No merge/deploy is authorized or performed by this subtask.
