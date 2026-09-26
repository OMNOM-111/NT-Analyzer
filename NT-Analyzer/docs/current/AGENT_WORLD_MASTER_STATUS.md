# Agent World — master status

> **This file is the single operational status of the Agent World / AI Center
> program.** Every executor — Claude, Codex or any later agent — reads it before
> starting and updates it before finishing a session or running out of budget.
> Do not create a competing "current status" file. The existing handoffs,
> receipts and changelogs stay as evidence and history, not as current state.
>
> If a session is cut off, this file plus Git must be enough for the next agent
> to continue without re-investigating anything.

```text
PROGRAM: Agent World / AI Center
STATUS: IN DEVELOPMENT

HANDOFF: P1-3 accepted and closed by the owner at f1fe393f.
  ACTIVE OWNER OF THE SHARED AGENT WORLD FILES: Codex, until P1-5 is integrated.
  That is contracts.py, model_contracts.py, states.py, storage_codec.py, both
  repositories, domain_gateway.py, model_service.py and the Aurora page. Three
  of them — states.py, storage_codec.py, model_contracts.py — are what the P1-5
  atomic commit rewrites, so an edit there is a merge conflict by construction.
  Anything else in the programme may proceed; these wait for Codex to land.

CURRENT IMPLEMENTATION COVERAGE: 93%
CURRENT OWNER ACCEPTANCE READINESS: 68%

CURRENT INTEGRATION BRANCH: codex/agent-world-unified-acceptance
CURRENT INTEGRATION SHA: fb2c472b — P1-3 complete, including the decision producer.
  At fb2c472b: CI run 34658942542 SUCCESS on all three jobs — Static gates;
  Tests (ubuntu-latest) 5515 passed / 0 failed / 116 skipped, 18:54;
  Tests (windows-self-hosted) 5512 passed / 0 failed / 119 skipped, 1:37:59.
  Locally: 228 passed across the completion, handoff, shared-security and
  reputation suites, plus 13 new decision-path cases.
  Previous checkpoint 84ddb2e7 — P1-3 scopes. Full regression at b06c5f55 (the commit
  before the honesty fix): 5493 passed / 0 failed / 117 skipped, 1:31:06.
  At 84ddb2e7: CI run 34641854998 SUCCESS on all three jobs — Static gates;
  Tests (ubuntu-latest) 5502 passed / 0 failed / 116 skipped, 17:32;
  Tests (windows-self-hosted) 5499 passed / 0 failed / 119 skipped, 1:40:53.
  A local full run at 84ddb2e7 was started and then STOPPED ON PURPOSE at 10%: the
  self-hosted Windows runner is this same machine, so the two were competing for it and
  both crawled. CI's Windows leg IS the full suite on this box. Its log,
  scratchpad/full_84ddb2e7.txt, ends mid-run with zero failures — that is a kill, not a
  red result.
CURRENT WIP: clean
CURRENT LOCAL 8765 SHA: 2b6d0112bef88c5bfb73970de64ec5518443e56b (not switched, not restarted)
CURRENT ACCEPTANCE INSTANCE: http://127.0.0.1:8809/ui/ai-command-center.html — SHA 84ddb2e7,
  disposable data root, zero external calls. :8808 serves b06c5f55 and holds the evidence of
  the reputation headline defect; :8806 serves 4d9ff737 (P0 acceptance); :8804 serves 92d873e3
  and still holds the historical stuck task. All superseded, none deleted.
CURRENT VERSION: 0.10.0-beta.96 (pre_release)

LAST VERIFIED: 2026-09-11
UPDATED BY: Claude (P1-1, P1-2, P1-3)
```

## Percentage method — identical for every executor

Applied to the 36 rows of the matrix below. **Never** raise a percentage
because more tests exist.

| Metric | 1.0 | 0.5 | 0 |
| --- | --- | --- | --- |
| Implementation Coverage | implemented in the agreed scope | partial | absent |
| Owner Acceptance Readiness | full E2E confirmed in the running application | automated / integration verification only | not verified |

A percentage that **falls** after a defect is found is correct and must be
recorded as such.

```text
IMPLEMENTATION COVERAGE: 93%   (33.5 / 36)
OWNER ACCEPTANCE READINESS: 68%   (24.5 / 36)

P0 REMAINING: 0

CHANGE SINCE PREVIOUS CHECKPOINT (87 / 65 at 7f54d6ea):
Implementation: +6 pp  — two rows move 0.5 to 1.0. Intent: the commitment a task
                         was created from is now on the task, in the API and on
                         the page. Reputation: three separate scopes over one
                         typed subject, with provenance and basis.
Acceptance:     +3 pp  — Intent (+0.5) once both panels were read from the live
                         DOM on :8809, and Reputation (+0.5) once the third scope
                         got a producer. All three scopes now fill from the
                         application's own completion path, confirmed on :8810
                         through the API and in the browser: «Решение · Класс
                         задачи: Исход одобренного решения · Наблюдений 1 · из
                         них диагностических 1 · Доказательства 1 запись».
```

> The independent audit of 2026-09-10 reported 84% / 54% on a 34-row basis.
> This file uses the canonical 36-row basis, which re-bins the *same* evidence
> to 85% / 56%. That difference is arithmetic, not progress. The next session
> measures its change against 85 / 56.

## Status vocabulary

`DONE + VERIFIED` · `IMPLEMENTED` · `PARTIAL` · `CODE ONLY` ·
`NOT IMPLEMENTED` · `BLOCKED` · `REGRESSION` · `OWNER ACTION REQUIRED`

Marks: `Y` yes · `P` partial · `N` no.

## Matrix

| Область | Code | Wired | UI/API | Automated | E2E | Status | Evidence | Что осталось |
| --- | :-: | :-: | :-: | :-: | :-: | --- | --- | --- |
| Foundation | Y | Y | Y | Y | Y | DONE + VERIFIED | Live on Local 8765 | — |
| Contracts / flags | Y | Y | Y | Y | Y | DONE + VERIFIED | 13 flags default-off with dependency ordering; observed live on 8765 and 8804 | — |
| SQLite | Y | Y | Y | Y | Y | DONE + VERIFIED | Default backend on every instance | — |
| PostgreSQL / RLS | Y | Y | Y | Y | Y | DONE + VERIFIED | e45 runtime harness: API → worker → SQL → replay → restart → RLS; 69+41+7 suite PASS; 10 FORCE RLS tables; no SQLite fallback | Never run as Local's backend |
| Event ledger / outbox / idempotency | Y | Y | Y | Y | Y | DONE + VERIFIED | Idempotent replay and restart in the same harness | — |
| Intent | Y | Y | Y | Y | Y | DONE + VERIFIED | «Поручение» read from the live DOM on :8809: goal, approval mode «только совет, исполнение не разрешено», risk, deadline, workspace, required evidence and verifier, with the request behind a disclosure. Six rendering cases over the shipped page code | Cancel was not caught in the browser: the local executor finishes a task within seconds of creation, so the control had already gone by the time the page opened. It is the task's pre-existing action, offered by the panel (`actions: ["cancel"]` observed on the unstarted task) and covered by the task suites. Amendment is refused by design, not missing: `EDITABLE_STATES[INTENT] == {"draft"}` and a started task has already left it, so an editable Intent would mean widening the immutability rule that binds request, receipt and evidence. The panel says so and points to «Отменить задачу» or a new request |
| Coordinator | Y | Y | Y | Y | P | PARTIAL | `coordinator.commission`; 202 PASS across coordinator, delegation, handoff, integration, review and UI | Two closed operation classes, caller-named rather than inferred from the goal; still not a general planner |
| Task Graph | Y | Y | Y | Y | P | IMPLEMENTED | Real parent → subtasks → contributions → aggregate, depth ≤3, typed deps. Two operation classes: `verify_fact_transfer` restates and is graded on exactness, `numeric_breakdown` gives each child its own slice and a different answer | Live browser route for the second operation |
| Delegation | Y | Y | Y | Y | P | PARTIAL | Grant-bound, depth-bounded, cycle- and restart-safe; 61 handoff/delegation PASS | Roots only on Coordinator task or verified application result |
| Persona | Y | Y | Y | Y | Y | DONE + VERIFIED | Identity survives restart and model change; the selected-Persona chat path walked live on 8806 to a completed, accepted result with the identity intact | Audible voice check — P2-5 |
| Voice / TTS / lip-sync | Y | Y | Y | Y | N | PARTIAL | 8 TTS profiles, 6 reused `speaking.webm`, browser speech default, owner TTS opt-in | Audio never heard; phoneme lip-sync absent by design — P2 |
| Model Registry | Y | Y | Y | Y | P | IMPLEMENTED | Persona / account / model separate; own-key wizard; capabilities, cost, latency | Only ever exercised with the named local test executor |
| Router | Y | Y | Y | Y | P | IMPLEMENTED | Candidates, exclusions, reason codes, shadow vs active, apply pinned to the exact preview; test-executor observations disqualified from real routing | No comparison between two real providers |
| Outcomes | Y | Y | Y | Y | Y | DONE + VERIFIED | Outcome and evaluation produced, displayed and accepted on the live route | — |
| Evaluation | Y | Y | Y | Y | Y | DONE + VERIFIED | Independent verifier; per-check pass/fail in the inspector; rejects wrong and corrupted answers | — |
| Reputation | Y | Y | Y | Y | Y | DONE + VERIFIED | Three scopes over one typed `Evaluation.subject` — model, agent role, decision — never summed, never relabelled, each with its own sample, confidence, evidence and window. `basis` names what was measured on: diagnostic, mixed or field. Read from the live DOM on :8809: «Модель · диагностика · 4 из 4», «Наблюдений 4 · из них диагностических 4», «Рабочая роль · NEW · недостаточно данных», neither card carrying the observed-performance style. All three scopes now fill from the application's own completion path: an approved Decision, the Execution naming it, the Outcome bound to that Execution, then the observation. Read from the live DOM on :8810: «Решение · Класс задачи: Исход одобренного решения · Наблюдений 1 · из них диагностических 1» | Nothing outstanding. The decision observation is deliberately narrow — whether what ran was what was approved, and whether the outcome was verified, never whether the call was wise — and a failed execution writes nothing at all rather than a zero |
| Consensus | Y | Y | Y | Y | P | IMPLEMENTED | Independent same-input contributions, then a separate Court | Synthetic only |
| Court | Y | Y | Y | Y | P | IMPLEMENTED | 3 isolated sessions from one sealed packet, unweighted 2-of-3, failure-domain diversity, provenance-checked votes, revocation re-checked after the call, judges cannot execute | Never three genuinely different providers — P2 |
| Execution | Y | Y | Y | Y | Y | DONE + VERIFIED | Immutable approved decision, capability/device re-check, budget, idempotency, cancel, restart. V2 enabled path walked live: prepare → queue → worker → receipt → completion | — |
| Deviation | Y | Y | Y | Y | P | IMPLEMENTED | Provider and application deviations recorded; material deviation returns to review | Live route |
| Memory | Y | Y | Y | Y | P | IMPLEMENTED | 10 HTTP E2E cases, two real cookie sessions: share, revoke, expire, foreign-workspace refusal, per-request re-check | No visual two-user route; not on PostgreSQL |
| Strategy Projects | Y | Y | Y | Y | P | IMPLEMENTED | Versioned records, comparison jobs | Real comparisons need permitted connections |
| Process Intelligence | Y | Y | Y | Y | P | IMPLEMENTED | Read-only pattern detection with cooldown → explicit proposals; no transcript reader, no model call, no auto-enable | Live route |
| Routines | Y | Y | Y | Y | P | IMPLEMENTED | Per-routine consent separate from automation permission and budget | Live route |
| Scheduler | Y | Y | Y | Y | P | IMPLEMENTED | Scanner has a real worker producer; grant, capability, budget, device re-checked per occurrence | Self-starting run shown once, on older code |
| Calendar | Y | Y | Y | Y | P | IMPLEMENTED | Workspace events, local input stored UTC | Live route |
| SF Chat | Y | Y | Y | Y | Y | DONE + VERIFIED | Message addressed to a Persona → task → real worker result → review → completed, walked live on 8806; refused requests now carry their reason | — |
| SF Social | Y | Y | Y | Y | P | IMPLEMENTED | Prepare → explicit publish; verified sources only; corrupted receipts never attested; private memory never publishable | One real publication is an owner decision |
| Owner Preview | Y | Y | Y | Y | P | IMPLEMENTED | Isolated synthetic operator with its own domains; deliberately no provider, worker, Router, Court, publication or routine execution | Manual route not re-run on final code |
| Ordinary-user model onboarding | Y | P | Y | P | N | PARTIAL | Wizard driven in a browser with a placeholder key against the local executor | Real key, real endpoint, real BYOK E2E — P1-4 |
| External-agent onboarding | N | N | N | N | N | NOT IMPLEMENTED | — | No remote tools/tasks, MCP or A2A — P1-5, needs an owner product decision |
| UI / UX | Y | Y | Y | Y | N | PARTIAL | All eight expected sections exist as drawer panels behind three tabs | Header counter lag, narrow-column wrapping, structure vs mockups — P3 |
| Security / tenant isolation | Y | Y | Y | Y | Y | DONE + VERIFIED | FORCE RLS; foreign workspace reads 0 and inserts fail `42501`; device and session re-checked per request; SSRF guard; no secret in Git | — |
| Restart / idempotency | Y | Y | Y | Y | Y | DONE + VERIFIED | Stop/restart/re-read against PostgreSQL; duplicate dispatch and replay refused | — |
| Documentation | Y | Y | Y | Y | Y | DONE + VERIFIED | Per-SHA receipts, file hashes, explicit withdrawn-claims section, skips never counted as passes | — |
| Git / CI | Y | Y | Y | Y | Y | DONE + VERIFIED | Run 34516120281 at 437febf4 **success on all three jobs**: static gates, Linux **5466/0/116**, Windows self-hosted **5463/0/119**. Immutable per-SHA worktrees, preserved originals, no force pushes | PR base is still not `main`, so nothing triggers automatically — owner decision |

## Active remainder

### P0 — BLOCKS OWNER ACCEPTANCE

```text
ID: P0-1
Problem: The saved branch tip is red; the fix exists only in the working tree.
Current state: 92d873e3 full run = 14 failed / 5435 passed / 119 skipped.
               9 uncommitted files carry the fix; targeted suites pass.
Target truth: A saved SHA whose full regression is 0 failed.
Files/modules: ai-command-center.js, ui.js, domain_gateway.py, model_service.py,
               4 test files, tests/test_agent_world_pre_enqueue_rejection.py (new)
Evidence required: immutable regression worktree receipt at the new SHA
Owner action required: NO
Assigned to: Claude
Status: DONE — saved as 1afce6e8. Full regression at c3a79675:
        5463 passed / 0 failed / 117 skipped, 4709.32 s.
```

```text
ID: P0-2
Problem: A request refused before the job is created stayed «В очереди» forever.
Current state: Live proof — task ef1b1052 on :8804, created 2026-09-09 19:56 UTC,
               still stage awaiting_provider, error_code null, only «Отменить».
               Fix and 5 regression cases exist uncommitted.
Target truth: The task reaches a terminal state carrying its real reason code,
              the user sees the reason, and no task can look queued when no job
              was ever created.
Files/modules: domain_gateway.enqueue_model, model_service._fail_locked
Evidence required: test_agent_world_pre_enqueue_rejection.py + live isolated repeat
Owner action required: NO
Assigned to: Claude
Status: DONE — server side in 1afce6e8, the reason a person reads in 2a49e0b9,
        page-level proof in 2a2e402e. 11 + 1 cases.
        Known limit: the historical stuck task ef1b1052 on :8804 was written by
        the old code and has no `enqueue_rejected`, so it still reads «В очереди».
        The fix applies to requests refused from now on; that row is not healed
        retroactively and must not be presented as if it were.
```

```text
ID: P0-3
Problem: A message sent through an explicitly selected Persona fails Execution V2
         approved-scope reconstruction instead of returning a result.
Current state: Reproduced in a browser on e45; regression test reproduces it.
Target truth: Select Persona → SF Chat message → Intent → execution → result →
              review → decision, with Persona identity preserved and no bypass
              of Execution V2.
Files/modules: execution_v2._request / approved digest, persona_identity
Evidence required: regression test with Execution V2 actually enabled, plus an
                   exact-code browser repeat
Owner action required: NO
Assigned to: Claude
Status: DONE. The scope guard itself was already correct — `persona_selection`
        entered the approved request in Codex's 92d873e3. What was missing was
        proof the path ends anywhere: coverage stopped at `awaiting_review`.
        4d9ff737 carries it to `completed`. Walked live on :8806: Persona
        84268b97 created and activated, connection eebb3c00 verified, chat
        addressed to that Persona, task 5ce6310c executed by the named local
        executor with external_call=false, reviewed and accepted →
        «Проверка завершена», attention list empty.
```

```text
ID: P0-4
Problem: CI has never run on this work.
Current state: PR #285 reports zero checks. Root cause found: ci.yml and
               next-architecture-ci.yml both trigger only on pull requests whose
               base is main (or release/**). PR #285's base is
               codex/agent-world-owner-preview, so no workflow ever fires.
               next-architecture-ci.yml also accepts workflow_dispatch, and the
               self-hosted runner stratforge-dev-DIMONCHECK is online and idle.
Target truth: A real run id exists and is green for the saved SHA.
Files/modules: .github/workflows/next-architecture-ci.yml
Evidence required: the run id and conclusion, recorded here — a local pytest is
                   not a substitute
Owner action required: NO for workflow_dispatch. YES if the PR base is to be
                       changed to main.
Assigned to: Claude
Status: DONE.

        Run 34510366536 on c3a79675 — static gates PASS (17 s),
        Tests (ubuntu-latest) PASS (16 m 59 s), Tests (windows-self-hosted)
        CANCELLED at exactly 30 m 33 s. The cap, not the code.

        Root cause and fix: `timeout-minutes: 30` was set when the suite was
        around 4235 cases; it is now 5580 and takes 78 minutes on that runner
        against 17 on hosted Linux. `ci.yml` carried the same cap on the same
        runner, so a pull request into main would have been cancelled too — its
        last green run was 2026-09-04, before the suite grew. Both raised to 120
        in 437febf4, kept finite so a real hang still ends the job.

        Run 34516120281 on 437febf4 (the final SHA) — **conclusion: success**,
        all three jobs green: static gates PASS (18 s),
        Tests (ubuntu-latest) **5466 passed / 0 failed / 116 skipped** (18 m 23 s),
        Tests (windows-self-hosted) **5463 passed / 0 failed / 119 skipped**
        (1 h 49 m 12 s). The Windows leg needed 109 minutes, so the old 30-minute
        cap was out by more than 3x and even 90 would not have been enough.
        The platform skip difference (116 vs 119) is the three Windows-only
        cases: two shell-syntax tests and one POSIX permission test.
        https://github.com/OMNOM-111/NT-Analyzer/actions/runs/34516120281
```

```text
ID: P0-5
Problem: There is no owner acceptance build to click through.
Current state: :8804 serves the red 92d873e3 with a stale synthetic dataset and
               one screenshot in total.
Target truth: An isolated instance on the exact green SHA, with a documented
              URL, SHA, data mode, flags, rollback point, screenshots and a
              click-by-click route.
Files/modules: .artifacts/acceptance-*/run_aurora.py
Evidence required: the route walked with captures at every step
Owner action required: YES to switch Local 8765 — not to be done otherwise
Assigned to: Claude
Status: DONE for the build and the captures; Local switch remains the owner's.
        URL: http://127.0.0.1:8806/ui/ai-command-center.html
        SHA: 4d9ff737 (runtime code identical to head 2a2e402e — the later
             commit adds a test only, verified by an empty app/ diff)
        Data: disposable root under .artifacts/acceptance-4d9ff737/aurora-data
        Flags: AI_ROUTER_V2, AI_ROUTER_SHADOW_V2, AI_EXECUTION_V2,
               AI_DELEGATION_V2, AI_SCHEDULER_V1 for this workspace only
        External calls: not authorized. Named local executor only.
        Rollback: stop the process; nothing outside that directory is written.
        Screenshots: .artifacts/acceptance-4d9ff737/screenshots (7 files)
```

### Click-by-click route on the acceptance build

```text
1. Open http://127.0.0.1:8806/ui/ai-command-center.html
   Three tabs: Обзор · Работа · Агенты. Counters read from one projection.
2. Drawer «Persona» → «Создать персону» → name, style → «Активировать».
   The record becomes active at revision 2; identity is separate from any model.
3. Drawer «Модели и подключения» → «Подключить модель» → pick that Persona.
   Then «Проверить соединение»: the receipt names
   agent-world-local-test-executor-v1, not the provider, and says so.
4. «Открыть SF Chat» → address the Persona by name: «@<имя>: <вопрос>».
   A task card appears in Работа with that Persona as coordinator.
5. Open the task. It shows «Ожидает вашей проверки», the answer, and the
   per-check verification. Cost reads 0,00 $ and the note states the content
   was not automatically scored.
6. «Проверить полученный результат» → accept. The task becomes
   «Проверка завершена», leaves the attention list, and the decision is
   recorded as a human fact with quality_claim false.
```

### P1 — REQUIRED FUNCTIONAL REMAINDER

```text
ID: P1-1  Coordinator is not a general planner
Current state: commission hard-codes a json_arithmetic root and forces every
               child to verify_fact_transfer; no descendant produces new analysis.
Target truth: At least one more real operation class whose child roles produce
              new analysis, selected by role rather than supplied by the caller.
Files/modules: coordinator.commission, delegation
Evidence required: a second lifecycle integration test of the same shape
Owner action required: NO
Assigned to: unassigned
Status: OPEN — designed, not implemented. The design below was traced through
        the actual code on 2026-09-10; start from it rather than re-deriving.
```

**The one constraint that makes children fact-transfer-only.** It is not the
graph machinery, which already supports more. It is a single expected spec in
`delegation.validate_constructor`:

```python
spec != prepare("extract_facts", "
".join(k + "=" + v for k, v in packet["facts"].items()))
```

plus `_verified`, which requires the parent's `rubric_key == "extract_facts"`.
Note `result_handoff.verified_model_data` **already** accepts both
`json_arithmetic` and `extract_facts`; only delegation narrows it.

**Proposed operation `numeric_breakdown`.** Every node runs `json_arithmetic`
over a server-computed contiguous segment of its parent's array — genuinely new
numbers, graded by the same independent verifier, which can reject a wrong one.
Uniform rule, no special case per depth:

  node array = parent array split into (sibling count) contiguous parts,
  take the part at this node's ordinal among its siblings.

For a node whose parent is the root, the parent array is the re-verified root
task's `spec["input"]`, not `plan["root_source"]["facts"]`.

**Keep `facts` a dict.** Six other places iterate `facts.items()` —
`coordinator` line 242, `task_review` 174, `domain_gateway` 708, `model_service`
1006 and two in `result_handoff`. Carrying a list there would ripple into the
review and publication surfaces. Use `{"values": "<json array>"}` instead, so
the sealed shape and `facts_sha256` are unchanged.

**The six places to change**

1. `coordinator.commission` — accept `operation` in the payload allowlist
   (`verify_fact_transfer` default, `numeric_breakdown` new); validate the array
   actually splits, because the rubric needs 3–20 integers per node and a plan
   that cannot split must be refused at commission, not at the first child;
   set `produces_new_analysis=True` and a real role label on the nodes.
2. `delegation._verified` — take the plan (or its operation) and require the
   rubric that operation implies. Every other check stays exactly as it is.
3. `delegation._seal_node` — derive the child's facts by operation.
4. `delegation.validate_constructor` — build the expected spec by operation.
5. `delegation._queue` (line ~493) — enqueue with the right rubric and input.
6. `_verified`'s other two call sites (lines ~416 and ~475, reconcile and
   projection) need the same operation, so thread it rather than defaulting.

**What must not move:** grant binding, depth and fan-out limits, cycle and
repeated-ancestor refusal, the immutable plan digest, one provider call per
node, the parent-verified-before-child rule, and the fact that the server
computes every segment and re-validates the answer. If any of these has to bend
to make the operation fit, stop and report instead.

```text
ID: P1-2  Intent is invisible to the user
Target truth: A chat message produces a named goal with constraints, evidence and
              approval mode, which the user can amend or cancel before execution.
Files/modules: model_service.intent_view, domain_gateway, ai-command-center.js
Evidence required: UI test plus one browser pass
Owner action required: NO
Assigned to: Claude
Status: DONE for display and cancel - 7b2a5c37, f80c6856, panel tests at 84ddb2e7.
        AMENDMENT WITHDRAWN, and this is the part to read before re-opening it.
        It was written, reported as working, and was not: a -k "intent" filter
        excluded the one case that would have failed. The live call returned
        409 finalized_record_immutable. EDITABLE_STATES[INTENT] == {"draft"}
        and start_task walks the Intent to ready at once, so there is no
        amendable window. Making one means widening the rule that binds request,
        receipt and evidence together - which is the rule P0-2 rests on. The
        amendment was removed instead, and the panel says plainly that a
        different request is a new request. Do not re-add it without deciding
        that immutability question first, in the open.
```

```text
ID: P1-3  One reputation scope where three are required
Target truth: Model Performance, Agent Role Performance and Decision/Outcome
              Performance stored and displayed separately, each with its own
              sample size, confidence and evidence.
Files/modules: model_contracts.Evaluation, storage_codec, reputation.py (new),
               model_service.reputation, domain_gateway, ai-command-center.js
Evidence required: presentation tests that fail if one score is reused elsewhere
Owner action required: NO
Assigned to: Claude
Status: DONE - fddc6bf7 (subject seam), 49b20b71 (read models, API, UI),
        b06c5f55 (measurement made a function of its evidence),
        84ddb2e7 (basis, and the panels moved where tests can reach them).
        One Evaluation with a typed subject; no per-kind evaluation shape.
        Nothing stored was rewritten - legacy rows say "model" and the decoder
        maps that name to a MODEL subject on the way in. Evaluation.model
        still exists and now raises for any other subject, deliberately, so a
        reader written when only models could be evaluated fails loudly instead
        of quietly returning the wrong thing. Every generic iteration over
        EVALUATION that leads to a model judgement filters subject.kind first:
        router_v2._observations and both model_service loops.
        The decision producer landed separately at fb2c472b, after the scopes:
        `decision_evaluation.py` observes the decision an execution was approved
        under, at the one point a real outcome is settled. Two things about it
        are deliberate and should not be "simplified" later. It measures only
        whether what ran was what was approved and whether the outcome was
        verified - never whether the call was wise - because nothing in the
        system can observe the latter. And when an execution fails on its own
        account it writes NOTHING, rather than a failed observation: a queue
        that lost its claim is not a decision that was wrong. Every deviation
        reason is attributed to one side or the other on purpose, and
        `test_every_deviation_reason_is_attributed_on_purpose` fails if a new
        reason is added without being classified.
```

```text
ID: P1-4  Ordinary-user BYOK never completed
Target truth: A non-owner user connects their own key and receives a real answer
              under their own budget.
Files/modules: model_service, model_transport, the connection wizard
Evidence required: a receipt naming a real provider with a non-zero measured cost
Owner action required: YES — a real key and a permitted endpoint
Assigned to: unassigned
Status: BLOCKED — must not block other work
```

```text
ID: P1-5  External-agent onboarding
Current state: A separate branch, codex/... external-agent-onboarding, draft
               PR #286, carries four unimported modules and 64 tests. Nothing is
               wired into storage, the queue or any UI; the integration branch
               is unchanged by it.
Target truth: An ordinary user connects an external agent, it does bounded work,
              and its results are evaluated without pretending to be a Model.
Evidence required: the native end-to-end route below
Owner action required: YES for accepting the protocol into scope
Assigned to: P1-5 executor (contracts), integrator (shared seams)
Status: UNBLOCKED at 84ddb2e7 — the typed Evaluation subject is delivered,
        and CI 34641854998 is green on all three jobs at that SHA.
        Integration SHA for the executor: 84ddb2e7.
        `EXTERNAL_AGENT_CONNECTION` добавляется атомарно при интеграции P1-5:
        enum + record + states + codec + Evaluation subject allowlist.
        That kind is NOT registered today, and registering it alone breaks the
        suite: test_codec_roundtrips_every_reviewed_record_and_event walks every
        EntityKind, because a kind means a storable record. It was tried and
        backed out — 9 failures. So SUBJECT_KINDS is scoped to the three kinds
        that exist, and the fourth arrives with its record, in one commit.
```

### Integration answer to the P1-5 checkpoint

Reviewed at `97095b0010a278e8f917a00e9661d77e93fadf0e`. Reviewed, not merged:
the branch stays unintegrated until the two seams below exist, which is what its
own rollback note proposes.

**1. Accepted SHA.** `97095b00` as the reviewed code checkpoint. The integration
branch does not carry it and no shared file was copied from it.

**2. `ExternalAgentConnection` — accepted as its own record kind.** It must not
be a Model wearing a different label, and this type is not. Its state machine
(`draft → verifying → active | degraded | disabled | revoked`), its capability
negotiation (allowed ⊆ requested ∩ advertised), its credential as an
`ExternalRef`, and the Development-only `synthetic` gate are all right. Becoming
a native record additionally needs, in files the integrator owns:
`states.py` — an `EntityKind` member, a transition graph, an initial state and
an `EDITABLE_STATES` entry; and `storage_codec.py` — codec registration. Those
are small and are the integrator's to write, not the P1-5 executor's.

**3. Evaluation subject without a Model ID — delivered at 84ddb2e7.**
`model_contracts.Evaluation` now declares `subject: EntityRef` validated against
`SUBJECT_KINDS`, and `model` is a property that returns the subject while it is
a Model and raises `evaluation_subject_not_a_model` otherwise. Stored rows were
not rewritten: `storage_codec` maps the legacy `model` field onto `subject` when
it decodes. `reputation.py` reads three scopes off that one contract and never
pools them. What follows is the original analysis, kept as the record of why.

**3. Evaluation subject without a Model ID — the real blocker, and it is mine.**
`model_contracts.Evaluation` declares `model: EntityRef` with
`require_entity(..., EntityKind.MODEL)`. An external agent therefore cannot be
evaluated at all today, and inventing a Model ID for one is exactly the
falsification this programme exists to prevent.

The fix is a typed subject on `Evaluation` — `subject: EntityRef` plus the kind
it points at — with `model` kept as a compatibility accessor while the subject
is a Model, so existing readers do not move. This is the same seam P1-3 needs
for Agent Role and Decision/Outcome performance, so it will be defined once, by
the integrator, as part of P1-3. **Do not define a second evaluation shape for
external agents.** If P1-5 lands first it should keep producing no Evaluation
rather than produce one with a fabricated subject.

**4. Shared-file ownership — no transfer.** The integrator keeps `contracts.py`,
`model_contracts.py`, `states.py`, `storage_codec.py`, both repositories,
`domain_gateway.py`, `model_service.py` and the page. The P1-5 executor keeps
`external_agent_contracts.py`, `external_agent_protocol.py`,
`external_agent_adapter.py`, `external_agent_onboarding.py` and their tests.
Nothing in that list is handed over by this answer.

**5. Next executor and dependencies.** P1-5 wiring is blocked on (a) the typed
Evaluation subject and (b) the record-kind registration, both owed by the
integrator. Until both exist the branch stays as it is. The 64 existing tests
are unit coverage of the contracts and do not stand in for the native route:
ordinary user creates a connection → real handshake → ACTIVE → compatible
Task/Intent → Contribution → its own Evaluation → history and statistics →
revoke → the next task refused; plus a second workspace, a duplicate, a timeout,
a revoke during execution, and the error preserved.

Percentages are unchanged by this answer: reviewing a contract implements
nothing. P1-5 stays NOT IMPLEMENTED in the matrix, and stayed so through P1-3 —
a seam that makes work possible is not that work.

### P2 — ACCEPTANCE / HARDENING

```text
P2-1  Court and Router with genuinely different providers — needs real connections.
      Evidence: three distinct provider_key values in the vote provenance.
P2-2  One permitted NinjaTrader result for the application handoff.
      Evidence: verification.passed with source_confirmed true. Never by relabelling.
      Owner action required: YES.
P2-3  The screenshot set that does not exist — one PNG covers the whole route today.
P2-4  Two-user Memory visually, and one real SF Social publication (owner decision).
P2-5  Audible verification of Persona voice on a real device.
```

### P3 — VISUAL / PRODUCT POLISH

```text
P3-1  Header counters lag the Work table.
P3-2  Stage column wraps letter-by-letter at 1136 px.
P3-3  Eight expected sections live behind three tabs as drawers — owner design call.
```

## COMPLETED SINCE LAST OWNER REVIEW

| Item | SHA | Evidence |
| --- | --- | --- |
| P0-1 · saved branch tip made green | `1afce6e8` | full regression at `c3a79675`: **5463 passed / 0 failed / 117 skipped**, 4709.32 s |
| P0-2 · refused request no longer looks queued | `1afce6e8` | `test_agent_world_pre_enqueue_rejection.py` — 5 cases: terminal `blocked`, real reason code, intent blocked, execution cancelled, no job, immutable old revision, replay refused, new request gets a new task |
| P0-2 · the person is told why | `2a49e0b9` | `presentation.refusal_reason`; 6 more cases incl. every code family; attention row no longer says «подтвердите или отклоните» |
| P0-2 · the page shows it | `2a2e402e` | refusal rendered through the shipped page code; asserts the queue label and decision wording are absent |
| P0-3 · Persona → chat → result → decision | `4d9ff737` | completion case on the enabled V2 path, plus the live walk on :8806 ending «Проверка завершена» |
| Master status introduced | `c3a79675` | this file |
| P1-1 · a child that produces new analysis | `7f54d6ea` | `numeric_breakdown`: disjoint slices, different answers, each independently verified; unsplittable plans refused at commission; unknown operations rejected; default unchanged. 202 passed across the six delegation suites |
| P0-4 · CI runs, and can finish | `437febf4` | run 34516120281 green on all three jobs; the 30-minute Windows cap that cancelled run 34510366536 was raised to 120 in both workflows, `ci.yml` included, where it would have cancelled main PRs too |
| P0-5 · owner acceptance build | `4d9ff737` | :8806 on an immutable SHA, disposable data, zero external calls, 10 screenshots, click-by-click route |
| P1-2 - the commitment is visible on the task | `7b2a5c37`, `f80c6856` | «Поручение»: goal, approval mode, risk, deadline, workspace, required evidence, reviewer; live on :8809. Amendment withdrawn rather than widening `finalized_record_immutable` - see P1-2 |
| P1-3 - three reputation scopes over one typed subject | `84ddb2e7` | 9 scope cases on real Model/AgentRole/Decision records + 6 rendering cases over the shipped page code; live on :8809 - model `measured` at 4, role `NEW` at 0 for the same class, no shared evidence |
| P1-3 - a measurement is a function of its evidence | `b06c5f55` | The window was stamped with the wall clock, so two reads of the same rows disagreed. Caught by two regressions that compare one task's detail twice |
| P1-3 - a diagnostic is not an observed score | `84ddb2e7` | Found on the running build, not in a test: 4 synthetic runs headlined as a green «100%». `basis` now names diagnostic / mixed / field and the headline follows it |
| P1-3 - the decision scope gets a producer | `fb2c472b` | Approved Decision -> Execution -> observed Outcome -> Evaluation, written by the application's own completion path. 13 cases: the model score and the decision score cannot reach each other's rows, a decision fails on scope while the model that answered passed, a role scope reads no decision row, a failed execution writes nothing rather than a zero, and a synthetic-only decision measures as diagnostic. Live on :8810 through the API and the browser |

## NEXT AGENT START HERE

### Parallel P1-5 handoff (2026-09-10; does not replace integrator's status below)

PARALLEL WORKSTREAM: External Agent Onboarding

- Base SHA: `9ae183f65149c9cc7253490810667fc75cbf9cf6`.
- Branch: `codex/agent-world-external-agent-onboarding`.
- Head (code checkpoint): `97095b0010a278e8f917a00e9661d77e93fadf0e`, pushed, clean.
- PR: [draft #286](https://github.com/OMNOM-111/NT-Analyzer/pull/286), base
  `codex/agent-world-unified-acceptance`; PR #285 base unchanged.
- Code: **IN DEVELOPMENT**, four isolated external_agent modules, no shared edits.
- Wired: NO — native codec/repository, worker and Evaluation integration pending.
- API: service ports implemented; authenticated HTTP routes NOT mounted.
- Automated: protocol/onboarding/adapter checks with test-only host ports.
- E2E: actual HTTP synthetic protocol path checked; full ordinary-user app E2E NOT checked.
- Tests: final focused **64 passed / 0 failed / 0 skipped**, 11.40 s, including malformed-card cases.
- Gates: root static scan CSP/secrets/Markdown PASS; Context Pack PASS (historical
  pack-SHA warning retained); 600-file pre-release bundle PASS, Python/JS included.
- Full regression, native PostgreSQL/RLS and application/UI E2E: NOT RUN.
- At code checkpoint: no uncommitted files; ignored Python caches only. No known
  focused test failures. Later handoff-only commit does not change executable code.
- Known limitations: native Contribution/Evaluation/history/statistics not persisted;
  native budget settlement/audit, RLS, UI and cancellation cleanup not wired.
- Integration files needed: states/codec/events, Evaluation subject contract,
  existing gateway/server/worker/Coordinator/Router; exact seams in change record.
- Conflicts with Claude: no shared files changed; requested shared contract review
  and ownership handoff are the next dependency, not a user-key blocker.
- Flags: no changes, no route activated; Development-only service/adapter guards.
- Recommended master-status delta: external onboarding 0 -> isolated backend
  contract/protocol tested, NOT a completed product flow. Integrator alone updates
  global percentages and original P1-5 matrix after reconciliation.

Next P1-5 operation: integrator reviews draft #286 and the native
connection kind and external Evaluation subject before assigning shared wiring.
No work on P1-1/P1-2/P1-3, UI, PR #285 base or Local 8765.
See [P1-5 change record](../changelog/2026-09-10-external-agent-onboarding.md).
Owner requested file-based coordination: the change record contains the explicit
message to Claude, requested contract/ownership decisions and native E2E checklist.
Integrator response received in `61ff7a3822f7306e3b60dd5fc342e06c9c31a8fd`,
section "Integration answer to the P1-5 checkpoint": `97095b00` reviewed, not merged.
No ownership transfer. Typed Evaluation subject and record-kind/codec registration
remain with the integrator; no parallel Evaluation implementation permitted.
2026-09-11 P1-5-only hardening checks role ownership and per-skill JSON compatibility,
rejecting duplicate/malformed skills. Native wiring still blocked on integration SHA.
Latest focused rerun: **70 passed / 0 failed / 0 skipped**, 10.32 s; previous 64-case
evidence above belongs to the reviewed checkpoint, not the subsequent changes.
Next independent checkpoint: bound adapter cancellation (same authority/spec/remote-ID
checks as polling), no fabricated cancellation success, test agent terminal-state
preservation. Native cleanup after revoke remains unwired; no shared ownership changed.
Cancellation checkpoint focused result: **75 passed / 0 failed / 0 skipped**, 13.37 s.
Next independent cleanup checkpoint: failed local credential deletion leaves the
connection revoked; repeated revoke retries deletion without another revision or
remote call. Dispatch rechecks authority after claim/secret access. Native atomic
dispatch/revoke ordering remains an integrator-owned requirement, not proven by
port tests. Credential rotation and native cleanup scheduling remain unwired.
Cleanup checkpoint focused result: **79 passed / 0 failed / 0 skipped**, 15.37 s.
Native registration continuation: integration base `3c62465d` includes `84ddb2e7`.
Atomically added external record kind/states/codec/events/shared Evaluation subject;
generic repositories reused. Native SQLite replay/history/isolation tests added.
New ownership blocker: integrator worktree at `3c62465d` has dirty model_service,
presentation, page, reputation tests and untracked decision_evaluation/path tests.
Those unsaved execution/evaluation/UI changes are not imported or overwritten.
Await their saved SHA or explicit file-level handoff before overlapping native wiring.
Full application E2E, new PostgreSQL/RLS, full regression and CI not claimed.
See change record for exact files and first registration test failures.
Native registration focused result: **372 passed / 0 failed / 0 skipped**, 22.96 s.
Connections are private in the shared visibility helper; foreign-owner reads denied.
No runtime registration/worker/API feature enabled; no global percentage raised.

```text
Last safe commit: fb2c472b - P1-3 complete, decision producer included.
  CI 34658942542 green on all three jobs at fb2c472b: Static gates;
  ubuntu 5515 / 0 / 116; windows self-hosted 5512 / 0 / 119.
  Locally at fb2c472b: 228 passed across the completion, handoff,
  shared-security and reputation suites, plus 13 decision-path cases.
  P1-3 is closed on every count.

Uncommitted files: none. Re-check `git status` before assuming that.

Active processes (re-checked at the handoff, not carried over):
  PID 7412 - Local 8765, `python -m app.server 8765`, code 2b6d0112, owner data
             root. DO NOT switch or restart. The PID changed from 20328: the
             machine restarted between sessions and Local came back on its own.
             Nothing in this programme switched or restarted it, and the
             worktree it serves is still at 2b6d0112.

  No acceptance instance is running. :8804, :8806, :8808, :8809 and :8810 all
  ended with that restart. Their launchers survive under
  .artifacts/acceptance-<sha>/run_aurora.py, so any of them comes back with one
  command, and a build at any other SHA comes from
  scratchpad/owner_acceptance_build.py <sha> <port>. Each uses a disposable data
  root and makes no external call. The evidence they were raised for is already
  recorded here and in Git; none of it depends on a live process.

Tests currently running: none.

Known failures: none at fb2c472b in any suite run so far.

Do not touch:
  - Local 8765 and the owner data root under NT-Analyzer/data
  - The bases of PR #280-#285; PR #285 is not to be moved onto `main`
  - states.py, storage_codec.py and model_contracts.py while Codex integrates
    P1-5: those three are what its atomic commit rewrites
  - Any Codex branch other than codex/agent-world-unified-acceptance
  - deploy/testing/acceptance.env or any generated DSN - never into Git

Exact next action:
  1. DONE - CI 34658942542 green at fb2c472b. P1-3 is closed and the
     Reputation row's evidence is complete.
  2. P1-4 (BYOK) is the next owner-blocking item and needs a real key and a
     permitted endpoint - owner action, not an executor's.
  3. P1-5 is unblocked and belongs to Codex. Do not pre-empt its three files.

Three notes for anyone changing this area:

Three places re-derive the same work and compare - `reconcile` stores the
aggregate proof, `task_review` rebuilds it, `propose` rebuilds the node labels.
They are meant to disagree loudly. If one is changed, change all three, and
never relax a comparison to make them agree.

A panel written inside the page's runtime closure cannot be tested. Everything
that renders sits above the `module.exports` line; that is the boundary the UI
suite loads. `reputationPanel` and `intentPanel` were written below it, which is
exactly why a green «100%» over four synthetic runs reached a running build with
a full green suite behind it. Put new render functions above the line.

Each reputation scope has its own task class as well as its own subject kind.
That is not decoration: it is the second lock that stops a model's rows and a
decision's rows ever pooling, whatever happens to the subject filter later.
Do not give two scopes the same class.
```
