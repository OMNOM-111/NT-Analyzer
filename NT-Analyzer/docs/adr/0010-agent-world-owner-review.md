# ADR-0010 — isolated Agent World owner-review checkpoint

Status: implemented for bounded Local owner review; broader production adoption
and design acceptance are pending. This supplements proposed
[ADR-0009](0009-agent-world-foundation.md), not a silent rewrite of its contracts.

## Context and decision

The owner authorized continuation through a clickable UI with real test tasks,
visible scores and a chart returned through SF Chat. Production-grade rollout of
every stage cannot be inferred from that visual checkpoint. Keep one current
[status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md), separate branch and PR
stack above beta.96/PR #280 and foundation/PR #281. Do not update the owner's
running older Local process.

Use the foundation types and state machines with a local-only SQLite repository.
Commit entity revision, immutable history, event and idempotency result atomically;
CAS conflicts fail closed. Artifacts are immutable, hash checked and scoped.
Outbox retention is implemented, external delivery is not. Never route Canary or
Production into this SQLite implementation. No global SQL migration is assigned.

A short synchronous deterministic benchmark executes three distinct fixed inputs
through four existing persona presentations. It is not a replacement job queue or
Execution Engine. Repeat keys replay stored results; interrupted admitted tasks
resume from committed states. No task is marked successful or sent to Chat unless
its immutable evidence has passed independent checks. Actor metadata distinguishes
the deterministic executor from verifier, without inventing a paid model identity.

## Authority and transport

The existing server remains the sole HTTP admission authority: authenticated
human session, confirmed permanent/session device, active workspace membership,
existing ai_lab capability and write role, professional contour, active trial,
origin/CSRF and existing zero-cost budget check. New code revalidates these
constraints before each write. The synthetic role never inherits owner/admin.
Provider secrets, broker resources, paid budget reservations and jobs are not
copied or synthesized as authority.

The existing default-off server flag registry remains the only flag source.
Four flags are opt-in only after trusted Preview-control admission plus exact
environment/workspace context. It does not grant new permissions. Six flags for
Router/consensus/Court/execution/memory/social publication remain OFF.

A child-local lifecycle lock serializes new database operations against the
existing Reset operation, especially Windows WAL handles. It is not an application
scheduler, distributed lock or a new permissions system.

## Read model and compatibility

Persona, Agent Role, Provider Account and Model remain separate entities.
Legacy adapters retain original IDs/statuses and do not rewrite legacy states.
UI uses only the shared API transport. Its single conditional rail entry leaves
legacy research accessible. SF Social is a product label; community APIs remain.

Tasks and benchmark artifacts are owner-private projections within workspace
scope. Scores are shadow metrics per task class: n<3 stays NEW; three distinct
fixtures yield a low-confidence score, never automatic Router authority.
Fixed-input replay is not an additional independent evaluation.

Result publication is an explicit user action into the existing scoped AI
conversation authority projected by SF Chat. Stable request IDs and recovery
prevent duplicate messages after interrupted writes. Browser-rendered chart PNG
is bounded, validated and stored as a private artifact; it is evidence of the
synthetic chart, not an external page or a live exchange screenshot.

## Consequences and deferred gates

This gives an inspectable vertical slice with real local persistence and results,
while normal Local and remote environments retain their behavior. It does not
satisfy PostgreSQL/RLS, multi-process leases, general natural-language tasking,
provider execution, Court, routing rollout, automatic memory, social publication
or trading acceptance. Models/System tabs do not appear without their existing
privilege boundary. Owner visual acceptance is required before a design closeout.

Rollback is disabling/closing the scoped Preview, not replacing owner state or
deleting a migrated shared database. Any release follows clean commit -> signed
immutable artifact -> Canary acceptance -> same exact artifact Production, with
separate owner authority.
