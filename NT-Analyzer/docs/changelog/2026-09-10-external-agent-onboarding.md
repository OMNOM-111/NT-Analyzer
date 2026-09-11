# External Agent Onboarding — isolated P1-5 checkpoint

Status: **IN DEVELOPMENT**. No release, merge, deployment, runtime switch or database migration.
Base SHA: `9ae183f65149c9cc7253490810667fc75cbf9cf6`.
Branch: `codex/agent-world-external-agent-onboarding`.
Change source: the commit containing this record; exact checkpoint SHA is recorded in the subsequent handoff.
Requester: owner. Implementation: AI-assisted change; no inferred model identity.

## Change summary

Separate ExternalAgentConnection value contract, bounded authenticated A2A client,
onboarding service and admitted-task adapter. Reuses RequestContext, RecordHeader,
Task, Intent, AgentRole, credential references, secure_store, public-IP pinned TLS
transport and existing independent arithmetic verifier. Does not create a second
identity, permissions system, queue, Router or registry. No shared integration/UI
files changed. No changes to Local 8765, owner keys/data, version or PR #285 base.

The pinned protocol is a restricted [A2A 0.3 JSON-RPC profile](https://a2a-protocol.org/v0.3.0/specification/),
not full A2A or 1.0 support. Authenticated extended card, message/send, tasks/get and
tasks/cancel only; bearer HTTPS on public port 443. One safe capability:
`stratforge.json_arithmetic.v1`. No arbitrary code, tools, SSE, push, OAuth or file
downloads. MCP tools/context are not represented as an agent.

## Contract and isolation

Connection keeps scoped header/provenance, name, protocol/endpoint, opaque credential
reference, requested/advertised/allowed capabilities, state, verification digest/time,
latency and safe error code. Public projection omits credential reference and value.
Model remains `unknown / externally managed`, Model ID null. No model quality claim.

Lifecycle: draft -> verifying -> active; verification failure -> degraded;
disabled/revoked remove allowed capabilities; revoked is terminal. Active requires
handshake proof; request cannot set status or verified. Each adapter step refreshes
existing admission, owner/scope, role/task/intent binding and connection revision.
Host must supply existing budget reservation, durable dispatch claim and approved
checkpoint. A timeout means outcome unknown, never automatic resend. Cancellation
returns observed remote state, not an assumption that the agent stopped.

Ordinary transport rejects loopback/private/metadata/mixed DNS, URL credentials,
query/fragment and redirects; pinned TLS reuses model transport. Credentials echoed
by the remote response are refused. Agent-advertised admin/trading capabilities
cannot become allowed. Test transport is constructor-injected by test code only;
there is no request flag allowing loopback. Development-only composition.

## Evidence boundary

Final focused tests: **64 passed / 0 failed / 0 skipped**, 11.40 s,
including two added malformed-card regression cases.
`tests/test_external_agent_protocol.py`: real ephemeral HTTP test server, actual
credential handshake, send/poll/cancel, duplicate binding, verifier, protocol/SSRF/
tenant/credential/timeout negatives. `tests/test_external_agent_ports.py`: service
and worker ports use explicitly test-only CAS/history/budget/admission doubles.
These are NOT native storage, authenticated UI/API, Coordinator or reputation E2E.
All test agent results are synthetic, never real external-provider benchmarks or
professional model ratings. Human result review is not auto-accepted.

## Exact integration blocker and ownership handoff

Native records have a closed EntityKind/codec registry; Evaluation currently
requires a Model ref. ExternalAgentConnection is intentionally NOT inserted by
inventing a Model, packing it into another entity or making a second store.
Claude owns shared integration and P1-3. Needed coordinated edits:

- `app/ai_control_center/states.py`, `storage_codec.py`, `events.py`: register the
  separate kind/codec/events and use native UnitOfWork CAS, immutable revision,
  idempotency receipt and outbox. Implement repository `get_external_connection`
  and `commit_external_connection` ports; list through existing scoped registry.
- `model_contracts.py` / P1-3 Evaluation: accept a typed external-agent subject
  without Model ID; retain Task/Contribution lineage and separate statistics.
- `domain_gateway.py`, `server.py`: compose service behind existing authenticated
  session/device/workspace/capability admission and server-side flag policy.
  Proposed actions: create, verify, get/list, disable/revoke. No routes mounted yet.
- Existing worker/Coordinator/Router: bind approved task spec + connection revision
  and remote task ID, supply native budget/dispatch claim, persist Contribution,
  scoped Evaluation and history atomically; bounded polling/cancellation cleanup.
- Existing presentation/UI integration owner: Add External Agent form (name,
  protocol, endpoint, password credential, allowlisted capabilities); show safe
  public connection status. Never reuse the model wizard's Model creation path.

API service ports exist, but HTTP/authenticated ordinary-user flow, native audit,
budget settlement, crash reconciliation, cleanup after revoke, native PostgreSQL/
RLS, Evaluation/history/statistics and visible registry remain **unwired**.
No protective flag enabled. This is an internal implementation dependency, not a
missing user key. Existing PostgreSQL/CI/full-suite results do not cover this code.

## Next operation / rollback

Integrator reviews separate connection/Evaluation contracts and assigns shared-file
ownership before wiring. Then prove ordinary-user native E2E including persistence,
revoke, two-workspace isolation and history/statistics. No shared ownership transfer
is implied by this checkpoint. Keep original master percentages unchanged.
Rollback: this branch adds unimported modules and tests only; leave it unintegrated.
No runtime rollback or data restore required. Full regression and native E2E are
not run/accepted; implementation complete, Git closeout and stage closed are distinct.
