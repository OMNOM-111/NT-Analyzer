# ADR-0012 — integrated Local Agent World and owner acceptance

Status: implemented in the Development integration delta; live browser/provider
acceptance remains a separate gate in the [canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).
Business requester: project owner. Technical attribution: AI-assisted change.

## Scope and predecessor

The owner explicitly authorized the Local-only switch of port 8765 and continued
implementation through a complete clickable owner review. This supersedes the
unanswered-switch boundary and three-section-only limitation in
[ADR-0011](0011-agent-world-real-local-jobs.md); its historical job/capture safety
contracts remain. [ADR-0009](0009-agent-world-foundation.md) entities and
[ADR-0010](0010-agent-world-owner-review.md) synthetic isolation remain separate.
No merge, Canary/Production, trading order, budget increase or destructive data
migration is authorized. Backtesting redesign is not part of this change.

## Composition, not replacement

Three primary tabs remain Overview / Work / Agents. Persona, Models, Decisions,
Court, Memory, Experiments, Strategy Projects, routines/calendar, System and
explicit SF Social publication are drawers on the same page. Task Inspector
opens original evidence and the existing SF Chat conversation. No second chat,
permissions, paid-budget, scheduler or execution engine is introduced.

The existing Local worker accepts typed `agent_world_model` and manual
`agent_world_followup` jobs. ModelService records Intent/Task/Contribution/
Execution/Outcome/Evaluation in Development SQLite revisions and artifacts.
`universal_llm` remains the provider authority through a narrow ContextVar
registry adapter. New private keys stay in the existing encrypted secret store;
ordinary users cannot enumerate or bind the owner registry. Existing owner
connections may be bound only after fresh owner/runtime/pricing admission, using
their existing caps. New private paid connections fail closed without a prior
approved allowance. Managed free endpoints do not create a paid entitlement.

Private compatible endpoints require an approved origin, public-address DNS
validation, HTTPS certificate/SNI verification, an IP-pinned connection, bounded
payloads, no redirects and no proxy/local-address fallback. Provider errors and
echoed credentials cannot become UI artifacts. Agent World calls do not inherit
the legacy hidden DeepSeek retry; uncertain requests require explicit new work.

## Real application chain

An actual stored SF Chat user message starts a model task for the configured
Tolik or Ivan persona. The model returns the exact bounded, explicitly authorized
backtest/chart specification. An independent deterministic checker verifies the
plan before the existing NinjaTrader or Desktop queue receives it. A valid model
plan is **waiting**, not a completed application result.

The original job/report or authenticated Desktop PNG receipt is verified against
its source ID, owner/workspace/conversation and specification. A separate actual
application Execution/Outcome/Evaluation references the original receipt and
immutable artifact hashes. The existing Chief monitor recovers final delivery
through the existing event inbox; task IDs and source IDs are preserved. A source
cancel request is not cancellation until the original executor confirms it.
Neither generated text nor an old manual job is accepted as this E2E evidence.

Connection tests, arithmetic and structured extraction use deterministic public
rubrics. Comparison tasks use identical inputs. Distinct-input counts, failures,
latency and available cost are measured automatically; n < 3 stays NEW, and n >= 3
is low-confidence observed capability evidence. Self-rating, synthetic runs,
strategy profitability and provider marketing are not substituted for quality.
Router weights remain unchanged. Actual model attribution comes from provider
receipts; persona names are not model provenance.

## Decisions, memory and publication

Consensus proposals use two or three accepted same-input contributions from
different model identities. Court seals one evidence packet and uses three
isolated judge contexts, immutable votes and an unweighted 2-of-3 rule. Conflicts,
missing/diversity evidence or insufficient votes remain review/abstention; a
verdict never dispatches execution. Judge confidence does not multiply a vote.

Memory keeps content/provenance/purpose/TTL and immutable revisions. Promotion
and publication require explicit human action. Sharing creates a separate
workspace-visible publication of exact content; it does not make the private
artifact API public. The shared artifact reader checks the live grant, source
revision, hashes and expiry. Revoke immediately ends further retrieval.

Strategy Projects keep versioned definitions and evidence. Routines/calendar
store explicit proposals; acceptance enqueues a manual follow-up in the existing
worker. Automation is OFF, no trade or external command is inferred from a date.

SF Social publishing is two-step: prepare a verified allowlisted public snapshot,
then explicitly approve that exact hash/revision and permanence. Only scalar
results/verdicts/evidence hashes are copied to the existing Community store.
Prompts, raw model answers, private memory, judge rationale and credentials are
excluded. Existing social idempotency plus private approval evidence handle
replay; completion/GET never publishes a post.

## Authority, flags and storage

Every route/worker/provider call uses the existing confirmed account/device,
active membership and permissions. Workers carry a non-secret session reference
and recheck revocation/expiry before transmission. Trusted Local owner entry is
preserved. Reads may retain existing evidence after entitlement/budget expiry;
new work remains denied. Read-only workspace members can retrieve only records
they own or explicitly published active Memory. Mutation remains own-workspace.

All ten registry flags default OFF. Exact Development workspace opt-in activates
eight reviewed flags: read/UI/tasks/evaluation/memory/consensus/Court/social.
Router shadow and Execution V2 remain OFF. Preview activates only its separate
four fixture flags; real domain tools fail closed there and explain the Local
boundary. Browser values cannot enable any flag.

There is no new numbered PostgreSQL migration. Development SQLite is not a
Canary/Production fallback. Actual isolated PostgreSQL regression exercises the
existing migrations 1–22, non-superuser/NOBYPASSRLS roles and TLS; it is not proof
of a new Agent World PostgreSQL adapter. SQLite read mode creates no absent DB
or schema, reads committed WAL and denies mutation. Operational WAL/SHM sidecars
are distinguished from semantic state.

## Acceptance and rollback

Port 8765 was beta.93 because its scheduled task still used the original dirty
checkout, not because Preview replaced owner data. A clean detached runtime
checkout at verified `486db834` was started against the preserved real data root
after isolated-copy checks, coherent/cold backups and exact process retirement.
The version remains beta.96. New delta activation requires its own clean tested
commit. Original task XML, manifests and copy/restore instructions remain in the
ignored Local operator artifact directory; no secret or runtime dump is shipped.

Code rollback and data rollback are distinct. Preserve any new owner work before
restoring a cold snapshot; never overwrite owner data with Preview. Full tests,
actual browser/provider flows, restart persistence, final-SHA CI, owner design
acceptance and release gates are recorded separately, not inferred from HTTP 200.
