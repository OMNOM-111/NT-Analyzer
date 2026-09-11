# External Agent Onboarding — isolated P1-5 checkpoint

Status: **IN DEVELOPMENT**. No release, merge, deployment, runtime switch or database migration.
Base SHA: `9ae183f65149c9cc7253490810667fc75cbf9cf6`.
Branch: `codex/agent-world-external-agent-onboarding`.
Code checkpoint: `97095b0010a278e8f917a00e9661d77e93fadf0e`, pushed, clean.
PR: [draft #286](https://github.com/OMNOM-111/NT-Analyzer/pull/286), based on
`codex/agent-world-unified-acceptance`; no change to PR #285 base.
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
Root static scan: CSP/secrets/Markdown PASS. Context Pack PASS (historical pack-SHA
warning remains). Pre-release: 600 files, static scan inside bundle, runtime reads,
Python compilation and JavaScript syntax PASS. Full regression, native RLS and UI
E2E not run. Initial sandbox-denied setup and test-ID Windows path-length errors
were corrected before the final run; final 64 cases all executed, none skipped.
Context metadata placement failure was corrected before checkpoint.
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

### Native registration on the delivered integration base

Fetched integration code `84ddb2e7` / documentation `3c62465d`; code is an ancestor
of the documentation commit. Common ancestor with P1-5 was `9ae183f6`. Integrated
that saved base into the P1-5 task branch without rewriting either history; no PR,
main, deploy or Local merge/promotion. Claude's saved code is preserved.

Atomic registration adds EXTERNAL_AGENT_CONNECTION, Record inheritance/ref, native
state graph/initial/editable states, strict codec, event type and shared Evaluation
subject allowlist. No new repository/table: the existing generic SQLite/PostgreSQL
record interfaces receive the registered kind. Native SQLite tests cover creation,
replay, restart, immutable revision history and two-owner/workspace isolation; shared
Evaluation roundtrip refuses the Model accessor for external subjects. PostgreSQL
RLS and full native dispatch/E2E are not inferred from these SQLite tests.

First registration run: 365 passed / 5 failed, generic transition fixtures omitted
required handshake proof for active connections. Added explicit proof to fixtures;
did not weaken production verification or codec validation.
Second run: 371 passed / 1 failed caught default workspace visibility for the new
connection. Added private visibility using the existing shared SQLite/PostgreSQL
visibility helper and an owner check in record validation. Final focused native
registration/storage/protocol suite: **372 passed / 0 failed / 0 skipped**, 22.96 s.

Concrete ownership blocker discovered by read-only status of the integrator worktree
at `3c62465daa023bd85af0f2e28cf17a13ea604a8d`: new dirty `model_service.py`,
`presentation.py`, `ai-command-center.js`, `test_agent_world_reputation_scopes.py`,
untracked `decision_evaluation.py` and `test_agent_world_decision_outcome_path.py`.
These subsequent edits are not in the delivered SHA and overlap native execution,
result presentation and acceptance. Do not copy or overwrite them. Integrator must
save/publish that work and identify the ownership boundary, or explicitly hand off
the overlapping files, before this executor wires into them. This is NOT the old
typed-Evaluation blocker: that contract is now present and used.

Native API/Coordinator dispatch, Contribution/Outcome closeout, statistics, credential
rotation, background cleanup and interprocess dispatch/revoke remain incomplete.
No E2E PASS, no new full pytest or workflow_dispatch result claimed. Local 8765 and
all acceptance instances unchanged. Next operation: reconcile the newly active
integrator files, then continue the existing worker path; never create a bypass.

### Revocation cleanup / uncertain dispatch checkpoint

Retrying revoke now retries failed secure-store deletion while preserving the
terminal revoked record. Secret-store errors become a safe cleanup-pending code,
never raw provider/OS text. Cleanup makes no remote calls and cannot reactivate.
Dispatch refreshes current authority and approved binding after durable claim and
credential access. Added injected races at claim/secret access and timeout retry
test: an uncertain first dispatch remains claimed and is not sent twice.
Focused result: **79 passed / 0 failed / 0 skipped**, 15.37 s.

Important boundary: host ports are still test doubles. An absolute cross-process
dispatch/revoke linearization guarantee requires native atomic claim/lease ordering
in the integrator-owned queue/repository. A last-moment recheck alone cannot make
that guarantee. Remote work already transmitted is not claimed to have stopped.
Credential rotation, background cleanup scheduling and native composition remain
unwired; no temporary Evaluation, Model or second reputation format introduced.

### Bound cancellation checkpoint

Added `ExternalAgentAdapter.cancel` using the same current admission, owner,
connection revision, approved spec and remote-task binding as polling. Foreign IDs,
revoked connections and withdrawn admission refuse before network access. Cancel
does not create verification/Evaluation; it returns the actual remote state, including
completion winning the race. No credential resurrection or auto-retry after revoke.
The Development HTTP agent now preserves terminal canceled/completed states. Initial
test run: 74 passed / 1 failed exposed its terminal-state overwrite; corrected fixture
and added subsequent polling assertions. No shared service/repository/codec changes.
Final focused tests: **75 passed / 0 failed / 0 skipped**, 13.37 s.

Host integration prerequisite remains explicit: cancel must be requested while the
task/connection is still admitted, before revoke/local terminalization. Cleanup after
authority expiry is NOT enabled by this adapter; an integrator-owned cleanup policy
and native budget/audit/queue composition are still required. Consequently the four
requested final integration milestones also include native API/worker composition;
these ports are not a claim that only enum edits remain. No second evaluation format.

### 2026-09-11 — integrator answer and non-overlapping hardening

Fetched `origin/codex/agent-world-unified-acceptance` at
`61ff7a3822f7306e3b60dd5fc342e06c9c31a8fd`; read its master section
"Integration answer to the P1-5 checkpoint". The integrator reviewed/accepted
`97095b00` as an isolated contract, NOT merged or native-wired. Shared-file
ownership explicitly remains with the integrator. Typed Evaluation subject and
native kind/codec registration are owed by the integrator; no alternative
Evaluation, fake Model ID or repository introduced here.

Subsequent P1-5-only changes: candidate rejects another user's role even in the
same workspace; negotiation rejects duplicate/non-object skills and respects
per-skill input/output modes instead of trusting a matching skill ID. Added six
negative cases. No onboarding service, gateway, UI or shared contract edits.
Focused rerun: **70 passed / 0 failed / 0 skipped**, 10.32 s.
Hardening gates rerun: root CSP/secrets/Markdown PASS, Context Pack PASS with
historical SHA warning, 600-file pre-release bundle PASS (Python/JS included),
git diff --check PASS. Full regression and native E2E remain not run.
These tests remain synthetic contract/port tests, not native application E2E.
Next: await the integration SHA containing both shared seams, inspect compatibility
and then continue authorized wiring. The prior file-based request below is historical;
its answer is now the explicit decision at `61ff7a38`.

### Сообщение Claude — согласование через файл

Владелец попросил передать согласование через файл. Это сообщение передано на
review, но **ответ Claude ещё не получен**. Единственный статус программы остаётся
в `AGENT_WORLD_MASTER_STATUS.md`; этот раздел — техническая передача, не новый план.

Получатель: текущий интегратор, владеющий Coordinator / Intent / Reputation.
Передаваемый код: checkpoint `97095b0010a278e8f917a00e9661d77e93fadf0e`;
handoff `6b2895e0970614c29222977bef61c1085604addb`, draft PR #286.

Пожалуйста, проверь контракты и запиши ответ в своей integration-ветке, в разделе
P1-5 master status: принятый SHA, согласованный тип ExternalAgentConnection,
тип subject для Evaluation без Model ID, владельцы конкретных shared-файлов,
следующий исполнитель и зависимости. Не нужно менять рабочую P1-5 ветку параллельно.
Если контракт уже изменён твоей работой, укажи фактический модуль/интерфейс вместо
автоматического переноса старого снимка. Отсутствие ответа не передаёт владение.

Нужное решение: ты интегрируешь перечисленные выше shared seams сам либо явно
передаёшь ограниченный список файлов исполнителю P1-5. До такого ответа они остаются
у тебя. Не переносить все master/context документы поверх более свежего статуса:
сопоставить только раздел P1-5, сохранив твои изменения и глобальные проценты.

После подключения к native storage/queue нужны доказательства: обычный пользователь
создаёт connection -> настоящий synthetic handshake -> ACTIVE -> совместимая
Task/Intent -> Contribution -> отдельный Evaluation -> история/статистика -> revoke
-> следующая задача отказана. Отдельно другой workspace, дубль, timeout, отзыв во
время выполнения и сохранность ошибки. Текущие 64 теста этого полного E2E не заменяют.
Никаких выдуманных Model ID, второго реестра, копирования owner keys или автоматической
приёмки результата. Local 8765, базы PR, merge/deploy и защитные flags не затрагивать.

Integrator reviews separate connection/Evaluation contracts and assigns shared-file
ownership before wiring. Then prove ordinary-user native E2E including persistence,
revoke, two-workspace isolation and history/statistics. No shared ownership transfer
is implied by this checkpoint. Keep original master percentages unchanged.
Rollback: this branch adds unimported modules and tests only; leave it unintegrated.
No runtime rollback or data restore required. Full regression and native E2E are
not run/accepted; implementation complete, Git closeout and stage closed are distinct.
