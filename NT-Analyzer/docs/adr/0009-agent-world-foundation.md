# ADR-0009: Agent World contracts and staged integration

- Status: Proposed for contract review; implementation authorized for stages 0–1.
- Decision date: 2026-09-04.
- Business requester: project owner. Implementation attribution: AI-assisted change.
- Accepted source: `4ae766ea0c3258a8bb049644ac2afbba6cb89330`, Local beta.96.
- Dependency: open PR #280; separate stacked branch, no merge or release here.
- Current checkpoint: [Agent World status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

## Decision and implementation boundary

One future AI Center presents several separate domains. The first slice adds
pure Python contracts, transition validation, read-only compatibility projections,
repository protocols and an immutable server-side feature-flag configuration.
Existing application modules do not import this package. No HTTP route, database,
queue, router, execution engine, Court, UI or background activity is activated.

The owner's canonical integration plan and starter document are external inputs.
This ADR records their stages 0–1 in version control and resolves implementation
details against the accepted checkout. The source plan's `c9b2883` was a historical
dirty Preview snapshot, not the implementation base. Historical records are
preserved in [the archive](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md).

## Current-to-target map and single-writer authority

| Current source | Target boundary | Authority / action in this slice |
| --- | --- | --- |
| `auth_identity`, `account_auth`, workspace memberships | human requester, tenant, service/agent actor and delegation | reuse identity; no AI login or user-account cloning |
| `security_devices`, `personal_nt_security` | approval proof and risk gate | preserve permanent/session and first-device proof; no new OTP system |
| `permissions`, `subscriptions`, `agent_allocation` | capabilities, access and role allocation | existing authorities; matrix below is a contract, not a second grant engine |
| `ai_lab/domain_agents` | Persona + Agent Role | project static roster through explicit stable IDs; do not mutate the roster |
| `ai_lab/agent_registry` | Provider Account + Model | only a server-authorized, explicitly bound sanitized row can be projected; no global registry reads or credentials in projections |
| `ai_lab/agent_router`, `ai_budgets` | future routing policy and reserved cost | preserve selection and accounting; no shadow calls yet; Development budget bypass is not evidence of enforced limits |
| `ai_lab/chief_agent` | conversation adapter, then Intent/Task services | retain conversation authority; replace use cases incrementally, not a whole-file rewrite |
| `ai_lab/registry`, `orchestrator` | experiments and workflow adapter | preserve detailed legacy status and expose a separate normalized phase |
| `durable`, `production_workers`, `sf_jobs` | worker attempts, leases, cancellation and retries | reuse transport; a domain Task is not a second worker queue |
| `sf_commands`, `connector_protocol` | execution receipt / bounded command | reuse authority; declarations do not authorize or dispatch commands |
| `sf_audit_events`, operational events, idempotency repository | audit, provenance and delivery | extend through transactional domain events/outbox at stage 2; telemetry is not a task ledger |
| `community` | SF Social publication | approved server-attested snapshot only; preserve permanent record and correction links |
| `sf_chat`, AI conversation store | human/AI dialogue facade | separate authorities; future intents and approvals use deep-links/references |
| NinjaTrader, market data and Charts | execution evidence / source data | preserve accepted implementations and hashes |

Every entity has one authoritative writer. Shadow projections cannot approve,
execute, grant capabilities or replace evidence. No dual writes are introduced.

## Contract vocabulary

Use stable UUIDs for new records and typed entity references containing kind,
ID, revision and tenant scope. Tenant scope is `(environment, workspace_id)`;
it is never inferred from a hostname, provider, persona, request body or global
fallback. A separate authenticated request context carries `user_uuid` and an
actor reference. Agent/service actor and `on_behalf_of` human remain distinct.
Creating a Python scope object is validation of shape, not authentication.

| Entity | Required meaning / references | Forbidden conflation |
| --- | --- | --- |
| Persona | display name, style/profile reference, optional voice/avatar reference | credentials, model selection or permissions |
| Agent Role | role key, responsibilities reference, capability ceiling, autonomy ceiling | a named model or a human account |
| Provider Account | provider key and opaque credential reference under explicit scope | API key value, endpoint token or public persona |
| Model | provider/model key, model profile reference, supported modalities | provider account credentials or Agent Role |
| Intent | requester goal artifact, acceptance artifact, scope, risk/autonomy, policy, budget reference, deadline | approval or execution |
| Task | intent, dependency references, assigned role, state and checkpoint reference | a browser session or a worker attempt |
| Contribution | task, producing role/actor, immutable evidence and result references | self-certified outcome |
| Decision | intent, contributions, evidence packet, policy and approval references | a command or a Court implementation |
| Execution | approved decision snapshot, existing command reference, receipt and status | model text claiming successful execution |
| Outcome | task/execution evidence and independent verification reference | chat thumbs-up or model confidence alone |
| Memory | typed class, origin/evidence, sensitivity, verification, retention, visibility and owner | full raw transcripts or cross-workspace global memory |

Every record header carries schema version, UUID, tenant, owner user UUID,
revision, created/updated UTC timestamps, created-by actor, correlation UUID,
optional causation UUID and immutable policy reference. Typed references make
cross-tenant edges invalid before persistence. Record payloads use immutable
artifact references; large prompts, secrets and hidden reasoning do not belong
in domain events or summary DTOs. The repository, not the DTO, verifies actual
artifact contents, memberships and capability authorization.

UUID user identity is the new contract. Existing numeric `user_id` remains a
compatibility key resolved through auth; it must not be guessed from Telegram.
Legacy record UUIDs derive deterministically from tenant + source namespace +
legacy ID using UUIDv5. A projection preserves the legacy source ID separately.
Global records require an explicit trusted binding; absent scope is rejected.

## State machines and legacy projections

New state transitions are validated independently per entity. A valid edge is
necessary, never sufficient, for execution: authorization, evidence, budgets,
revision and idempotency checks are separate preconditions. Terminal records
are immutable; retry creates a new attempt, revised decision or successor task.
There is no automatic legacy state rewrite or implicit resume.

| Domain | Allowed lifecycle (branches shown explicitly) |
| --- | --- |
| Profile (Persona/Role/Account/Model) | draft → active/retired; active → suspended/retired; suspended → active/retired |
| Intent | draft → ready/cancelled; ready → running/blocked/cancelled; running → waiting/blocked/completed/failed/cancelled; waiting or blocked → ready/cancelled/failed |
| Task | planned → ready/blocked/cancelled; ready → running/blocked/cancelled; running → waiting/review/blocked/succeeded/failed/cancelled; waiting/review/blocked → ready/cancelled/failed, review may finish succeeded |
| Contribution | draft → submitted/withdrawn; submitted → accepted/rejected/withdrawn |
| Decision | proposed → review/rejected/withdrawn; review → approved/rejected/expired; approved → superseded/expired |
| Execution | requested → queued/rejected/cancelled; queued → running/cancelled/expired; running → succeeded/failed/deviated/review; review → succeeded/failed/cancelled/deviated |
| Outcome | pending → verified/disputed; verified → disputed/superseded; disputed → verified/rejected/superseded |
| Memory | draft → active/revoked/expired; active → superseded/revoked/expired |

Legacy projections carry both `legacy_status` and a display/work phase:

| Source statuses | New phase | Meaning preserved |
| --- | --- | --- |
| local worker `queued/running/succeeded/failed/cancelled/stale` | ready/running/succeeded/failed/cancelled/review | stale needs review; not silently retried |
| PostgreSQL job `queued/running/completed/failed/cancelled/dead_letter/review` | ready/running/succeeded/failed/cancelled/review/review | completed becomes display success, not verified Outcome |
| command `queued/leased/completed/failed/rejected/expired/cancelled/review` | ready/running/succeeded/failed/failed/failed/cancelled/review | command type and receipt remain authoritative |
| research mission `active/paused/finishing/completed/stopped/idle` | running/blocked/running/succeeded/cancelled/planned | paused never becomes active by projection |
| experiment `draft/draft_ready` | planned/ready | no execution implied |
| experiment `designing/generating/backtesting` | running | phase only |
| experiment `generated/catalog_visible/backtest_done/analysis_ready` | review | intermediate success is not task completion |
| experiment `awaiting_compile` | waiting | retain dependency |
| experiment validation/compile/backtest/pipeline failure | failed | retain precise failure code |
| experiment timeout/environment/LM Studio blocked | blocked | preserve blocker |
| experiment candidate statuses / `portfolio_contributor` | review | candidate and portfolio membership do not grant live authority |
| experiment `rejected/archived/cancelled` | failed/archived/cancelled | archived is historical; no inferred result |
| unknown source or status | unknown + review required | fail closed for automatic transition; do not guess |

Full source mapping lives in the pure legacy adapter and is characterized
against `registry.VALID_STATUSES`, queue contracts and the current roster.

## Authority, capabilities and risk

This table specifies future admission requirements. No new grant API or
permission engine is implemented, and no current `permissions.py` entry changes.

| Action | Authority and existing gate to reuse | Risk / autonomy / evidence |
| --- | --- | --- |
| view own tasks/experiments | authenticated workspace, `ai_lab`, source ownership | read; scoped read model |
| create/cancel/retry intent | membership + `ai_lab` + current access | low/moderate; bounded by role, cancellation cooperative |
| premium model use | `ai_pro_models` + allowed provider binding + atomic `ai_budgets.reserve` | budget rechecked on claim and every paid step |
| provider credentials/routing config | current owner-only API guard; future delegated capability needs explicit registry change | high; fresh step-up, secret reference only |
| change roles/personas | membership plus future explicit capability in existing catalog | persona presentation low; capability ceiling changes high |
| approve decision | authorized human/service policy + immutable decision/evidence/policy digest | high/critical; fresh device/step-up as applicable |
| dispatch execution | existing command service and action capability; trusted device/step-up; approved decision | explicit autonomy ceiling, timeout, idempotency and expected receipt |
| read/publish memory | tenant and record-owner visibility plus future catalog capability for promotion | no broad shared-memory fallback; retention and provenance required |
| publish SF Social result | `community`, source ownership, `publish_as`/AI allowlist, approved snapshot | explicit publication and correction policy |
| system observation | `operations.view` / existing owner guard | redacted read-only diagnostics |

Risk classes: low, moderate, high, critical. Autonomy classes: advice, draft,
reversible_execution, approval_required, forbidden. These are constraints from
server policy; prompt text cannot raise them. Agent Role ceilings never grant
permissions. Critical effects need immutable approval bound to scope, decision,
policy, evidence and expiry; a revision invalidates that approval. Court never
becomes the executor. Always-on work needs an automation entitlement and revoke
policy independent of a browser session.

## Events, correlation and idempotency

Envelope v1 contains `specversion=1.0`, UUID `id`, `source`, `type`, UTC `time`,
typed `subject`, tenant, actor, `correlationid`, optional `causationid`, payload
schema version, immutable policy ref and a bounded reference-only data object.
It follows CloudEvents field naming; it is an internal contract, not a claim of
transport/conformance certification. New event types use `stratforge.ai.*`.

Correlation groups one workflow; causation names the immediate prior event.
An event ID is stable across delivery retries. Domain record revision and event
revision are explicit. Delivery is at-least-once. The future transaction commits
entity revision + event + outbox atomically; consumer inbox deduplicates by
tenant + consumer + event ID. Payload, scope or revision changes require a new
event. UI consumers use snapshot plus cursor and detect gaps; no transport is
implemented here.

Mutation identity is `(environment, workspace_id, operation, key_hash)` with
canonical request SHA256 including actor/user, entity revision and reference
payload. Same key + same hash replays the original result; same key + different
hash conflicts. Use the existing idempotency/command facilities at integration,
not an in-memory cache. Raw keys are excluded from repr/events; commands and
leases retain existing fencing tokens. Hashing is not a secret scrubber: input
must already be a validated reference-only contract.

## Repository interfaces for stage 2

The slice declares protocols only: scoped `get`, bounded cursor `list`, a
unit-of-work committing record + expected revision + event + idempotency claim,
and an event reader. There is no generic public SQL or unscoped `list_all`.
Every call requires authenticated user/actor context and tenant scope. Unknown
record types, missing scope, cross-tenant references and stale revisions fail
closed. Private memory additionally requires matching owner user UUID; workspace
memory still requires server capability/membership admission.

Development implementations will reuse SQLite WAL under an isolated data root;
Canary/Production implementations use the existing PostgreSQL client/Scope with
ENABLE and FORCE RLS. The latter never fall back to files. No repository document
allowlist entry, table or migration number is added now. Choose normalized
domain tables deliberately in stage 2; do not copy an entire global JSON
document into the compatibility document repository by default.

## One server-side feature-flag registry

All flags below default to false. Resolution requires explicit environment and
workspace scope. A trusted immutable configuration snapshot contains per-
environment gates, exact workspace opt-ins, a revision and audit reference.
An environment false/missing gate is a kill switch and cannot be overridden by
a workspace. An environment true gate still requires that exact workspace's
true opt-in; no wildcard, owner bypass or cross-environment inheritance exists.
Dependencies are checked within the same scope. Unknown flag names, malformed
booleans or duplicate rules are rejected. No browser/localStorage/query-string
value and no per-flag environment variable enables a path.

| Flag | Dependencies |
| --- | --- |
| `AI_CONTROL_CENTER_READ_MODEL` | none |
| `AI_COMMAND_CENTER_UI` | read model |
| `AI_TASK_GRAPH_V2` | read model |
| `AI_ROUTER_SHADOW_V2` | task graph |
| `AI_EVALUATION_SHADOW` | task graph |
| `AI_CONSENSUS_V2` | task graph |
| `AI_COURT_V1` | consensus |
| `AI_EXECUTION_V2` | task graph |
| `AI_MEMORY_V2` | task graph |
| `AI_SOCIAL_PUBLISH_V1` | evaluation |

The registry describes staged availability, not authorization. Flags never
grant access, unmask credentials or bypass Preview's external-effects block.
No config loader/mutation endpoint/audit writer is wired in stages 0–1. Future
configuration changes use the existing owner/admin authorization and audit,
and the configuration audit reference must be verified by the loader.

## Acceptance and next gate

Contract tests cover separation of identities, tenant/user/environment mismatch,
immutable snapshots, transition rejection, deterministic source projections,
secret-free allowlisted DTOs, idempotency conflicts and flag dependency/kill
switch behavior. Characterization protects the accepted provider registry,
roster, legacy statuses and existing auth/device/Social/Chat/Preview behavior.
Run full regression, Python compile, JS/bundle/static and context gates; report
credential/platform skips explicitly. Browser QA is not repeated for a slice
with no UI changes.

Stage 0 closes on a precise clean base and reconciled current documentation.
Stage 1 local implementation and Git/CI closeout are separate from architecture
review. Stage 2 remains gated on review of these concrete contracts. No claim
of Agent World readiness, PostgreSQL isolation acceptance, new runtime behavior,
Canary acceptance or Production readiness follows from pure contract tests.
