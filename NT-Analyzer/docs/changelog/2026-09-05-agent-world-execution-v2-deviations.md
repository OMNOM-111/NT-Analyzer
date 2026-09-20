# Agent World: bounded Execution V2 and Deviation Control

Status: IN DEVELOPMENT, Development only, default OFF. AI-assisted change.

## Change and scope

The mechanisms worktree builds on `45ab4361` (`codex/agent-world-mechanisms`).
The final combined source SHA/PR and release identity are recorded by the
integrating owner of this branch; this scoped record does not claim a release.

- Added a distinct durable Execution V2 controller, using the existing
  SQLite Execution history, immutable artifacts, CAS/idempotency and event
  ledger. Existing model Tasks, model Executions, budgets and workers remain
  their original authorities; this is not a relabelling of a legacy worker.
- Sealed the exact approved request, Decision/approval, role, intent policy,
  model/provider/persona binding, credential-reference hash, session binding,
  deadline, optional application spec and typed delegation/schedule origin.
  Credentials and raw browser session identifiers are not copied into these
  new snapshots or deviation records.
- Kept the existing `agent_world_model` job ID and payload. Managed jobs use
  its existing bounded retries; no queue, permission, budget or job schema was
  added. Current lease, worker attempt, user and workspace are fenced before
  each model step. A provider-in-flight checkpoint without a persisted receipt
  is held for review and can never silently retransmit.
- Revalidated the existing authorization/device/workspace/capability/budget
  authorities and gate at each step. SERVICE continuation uses a trusted
  refresh callback and the separately approved automation grant, not a fake
  Human login. Typed delegation/schedule source validation is repeated.
- Guarded application dispatch and monitor reconciliation, including the
  source adapters' final pre-enqueue admission. The existing chart-command
  and backtest queues, verifiers, cancellation and idempotency remain intact.
- Added immutable deviation evidence (reason codes and hashes, never provider
  error bodies) for scope changes, uncertain responses, limits, rejected
  results and application receipt mismatches. A verified execution is not
  human acceptance and creates no model reputation or additional rating.

New modules: `execution_v2.py`, `deviation_control.py`. The narrowly coordinated
integration in `application_chat.py` wraps existing admission and records
receipt-only closeout before terminal delivery. Shared gateway, server,
automation entitlement, flags and UI integration remain the root workstream.

## Verified checkpoint

- Execution V2 + existing application-chat/domain-gateway/model-service
  regression: **272 passed**, 302.32 seconds, zero skips at that checkpoint.
  This combined run preceded the two additional receipt-only admission cases.
- Final focused Execution V2 suite: **46 passed**, 123.77 seconds, zero skips.
  It includes successful receipt-only audit after paid entitlement/budget expiry
  and denial after explicit session revocation; neither case sends another
  provider request. SERVICE receipt-only admission uses the trusted refresh
  callback; real automation-authority integration remains a separate pending
  check at the 2026-09-06 WIP checkpoint.
- Python compilation of `execution_v2.py`, `deviation_control.py`, the scoped
  `application_chat.py` integration and the focused test module: **PASS**.
- Focused tests use real disposable SQLite, the real durable queue/claims,
  `local_worker.run_once`, existing model records and existing application
  command/report verifiers. Synthetic test identities, in-memory test secrets,
  synthetic provider transport and synthetic source receipts are explicit.
- The tests demonstrate isolation and state transitions, **not** a credentialed
  provider or live NinjaTrader acceptance. No browser, external provider,
  trading order, owner runtime, Local 8765, Canary or Production was touched.
- Repository-wide regression/static/context gates and Git closeout belong to
  the integrating workstream. CI, owner visual acceptance, high-risk acceptance
  and stage closure are not inferred from these local test results.

## Limits and release impact

`AI_EXECUTION_V2` remains disabled by default. It must be enabled by the
existing trusted environment/workspace registry. A managed job never falls
back to legacy dispatch when this switch is revoked. Court is not an executor;
this bounded implementation denies Court votes and high/critical-risk intent
execution. No new trade execution, automatic compensation or rollback claim
is made. Cancellation uses only the existing authoritative source.

Unknown external replies require investigation/new explicit approval, not a
reset of the existing job or an automatic second paid request. Persisted
receipts may finish domain verification without another provider call.
Automatic task/chain scheduling still needs the separate runtime entitlement
workstream and its acceptance evidence. No version is assigned here.

Rollback: disable the gate to prevent new managed steps while preserving
controller/queue evidence; do not re-route those jobs through legacy execution.
Code rollback is to the integrating branch's recorded checkpoint, with no
deletion of runtime evidence or owner data. No migrations were introduced.

The root workstream updates the canonical current status and External GPT
Context Pack in the same combined change; they are not competing sources of
truth with this scoped change record.
