# Agent World: test-only pin and grant-bound history delivery

## Change record

- Date: 2026-09-08.
- Source baseline: `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`, branch `codex/agent-world-unified-acceptance` plus the explicitly classified integration delta. Final source SHA is assigned by the root integration checkpoint; this record does not claim a release.
- Status: `IN DEVELOPMENT` until the root's frozen integration regression and user acceptance. Implementation evidence below is scoped, not programme acceptance.
- Scope: model request origin, Model DTO execution availability, immutable review delivery, existing worker ingress/claim fencing and SF Chat result projection. No new permission, grant, budget, queue, chat store or browser authentication exemption.
- Local `8765`, owner credentials/data and external transports were not used. No version change, merge, deploy or production operation.

## Verified defects and fixes

1. A request created under the exact-workspace local test executor could be taken by a fresh ordinary executor after the test switch was disabled. A test-only connection check could also be mistaken for provider verification. `ModelService` now pins `test_executor_request` server-side in the Intent and Task, preserves it across interrupted creation/replay, rechecks before transmission and inside the admission callback, and refuses the mode change. Old saved receipts remain readable. A new, explicit `connection_exact` request after switching off the test executor remains independently subject to normal authority/budget/provider checks.
2. `connected` is reserved for a real provider check. `test_executor_verified` is historical evidence; `can_execute_test_only` additionally requires today's exact workspace opt-in. `execution_available` is a separate UI capability. No owner key is copied and a synthetic reply contributes no professional model-quality score.
3. Ordinary background automation loses the browser session field when normalized to its SERVICE-on-behalf-of actor. Calling HUMAN browser admission from history delivery incorrectly blocked legitimate permanent-grant work. Coordinator completion jobs now carry the exact persisted controller/grant reference, bound back to the original root task and plan. Existing `worker_authority(read_only=True)` and a current durable claim govern the internal Chief delivery ingress. Browser `access()` remains unchanged and still rejects expired or absent sessions.
4. The internal history ingress is not supplied by an envelope or HTTP body: Chief receives an exact claimed delivery job, rereads current authority, verifies the saved completion/event/checkpoint and original scoped user message, and admits again before Chat writes. It cannot execute a provider. NaN/infinite/malformed lease/deadline values are rejected.
5. The new security tests also reproduced integration projection defects fixed by the root: a committed review becoming an error when notification enqueue raised an I/O exception; aggregate tasks omitted from `total`; and System incorrectly describing implemented PostgreSQL/Execution/Router/scheduler mechanisms as missing. Those fixes are root-owned and remain covered by this suite.

## Evidence

- Before the test-origin fix: 5 failed / 1 passed in the initial six-case regression; both queued task variants invoked the injected ordinary-provider callback after the switch was off. This was a disposable callback, not an external provider call.
- After the test-origin fix: those six cases passed in 5.27 s.
- Downstream model/executor/provenance/delivery/deviation/Execution V2 regression after the pin and initial routing hook: **310 passed, 0 skipped**, 225.62 s. This run predates the new SERVICE delivery ingress and is not represented as its final verification.
- Shared negative/projection block after root integration fixes: **41 passed, 1 deselected**, 12.06 s. The deselected case was the separately run ordinary-user runtime case, not a skipped acceptance claim.
- Actual ordinary-user scoped runtime: **1 passed, 41 deselected**, 36.32 s. The test creates its own registered-user/device fixture and real Persona/model records, submits a Coordinator root through SF Chat, approves one exact finite graph, expires the browser session, then uses the real worker to execute one child and deliver three persisted reports (root, child, aggregate). No manual `after_model` call is used. Browser admission correctly remains denied; SERVICE actor remains on behalf of the same human/workspace; all replies are named local-test-executor, zero external calls; the aggregate remains awaiting human review.
- Combined security + provenance + model-delivery verification after the new SERVICE ingress: **118 passed, 0 skipped**, 160.00 s. This includes the ordinary-user scenario with foreign task/event/controller/grant and forged `human_accepted` rejections, claim replacement/expiry/cancellation, and accepted-review delivery after entitlement expiry and test-switch shutdown without a second executor call.
- Shared security + ordinary/owner Coordinator + shared HTTP/domain regression: **165 passed, 0 skipped**, 332.11 s. This includes the real existing owner worker/Chat pipeline and all scoped domain HTTP checks, not just a service callback.
- Final security suite after adding the independent job-header/authorized-subject binding: **54 passed, 0 skipped**, 56.62 s. The ordinary-user runtime and its negative grant/event/envelope checks were repeated on this final helper. Browser auth remains unchanged.
- Python compilation and scoped `git diff --check`: PASS. Root-owned whole-program frozen regression, context-pack validation and release-bundle gates remain separate required closeout evidence.

## Boundaries and remaining acceptance

- The ordinary-user fixture starts with a registered user and confirmed permanent device. It does not replace the owner's pending registration acceptance, separate BYOK secret entry or permanent-publication confirmation.
- Synthetic local arithmetic/fact-transfer is infrastructure evidence, not a real model evaluation, real backtest/chart proof or quality rating. Unit cases using an injected ordinary-provider callback are contract tests only.
- PostgreSQL evidence is kept in its separate acceptance record: these security/runtime tests use disposable SQLite and the existing local worker. They do not rerun the 69 Agent World or 41 legacy PostgreSQL suites.
- Root owns the canonical implementation-status/current-doc/context-pack reconciliation and final Git/PR closeout. This record and its tests must remain in the same integration checkpoint as the code. No independent release or programme completion is claimed here.
