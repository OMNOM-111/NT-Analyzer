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

CURRENT IMPLEMENTATION COVERAGE: 86%
CURRENT OWNER ACCEPTANCE READINESS: 64%

CURRENT INTEGRATION BRANCH: codex/agent-world-unified-acceptance
CURRENT INTEGRATION SHA: 437febf4 — CI green on all three jobs. Tip is 1059bc99+ (docs only).
CURRENT WIP: clean
CURRENT LOCAL 8765 SHA: 2b6d0112bef88c5bfb73970de64ec5518443e56b (48 commits behind, not switched)
CURRENT ACCEPTANCE INSTANCE: http://127.0.0.1:8806/ui/ai-command-center.html — SHA 4d9ff737,
  runtime code identical to head (the later commit adds a test only), disposable data root,
  zero external calls. The older :8804 still serves 92d873e3 and is superseded.
CURRENT VERSION: 0.10.0-beta.96 (pre_release)

LAST VERIFIED: 2026-09-10
UPDATED BY: Claude (independent audit + P0 closure)
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
IMPLEMENTATION COVERAGE: 86%   (31.0 / 36)
OWNER ACCEPTANCE READINESS: 64%   (23.0 / 36)

P0 REMAINING: 0

CHANGE SINCE PREVIOUS CHECKPOINT:
Implementation: +1 pp  — CI is configured and actually runs; no new capability
Acceptance:     +8 pp  — Persona, SF Chat, Execution and Outcomes walked live on
                         the acceptance build, and CI verifies the exact SHA
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
| Intent | Y | Y | N | Y | P | PARTIAL | Record created per task and per decision, correlated end to end | No user-visible goal capture, amend or cancel — P1-2 |
| Coordinator | Y | Y | Y | Y | P | PARTIAL | `coordinator.commission`; 40 focused PASS; full lifecycle integration test | Hard-coded to one `json_arithmetic` goal; not a planner — P1-1 |
| Task Graph | Y | Y | Y | Y | P | PARTIAL | Real parent → subtasks → contributions → aggregate, depth ≤3, typed deps | No descendant produces new analysis — P1-1 |
| Delegation | Y | Y | Y | Y | P | PARTIAL | Grant-bound, depth-bounded, cycle- and restart-safe; 61 handoff/delegation PASS | Roots only on Coordinator task or verified application result |
| Persona | Y | Y | Y | Y | Y | DONE + VERIFIED | Identity survives restart and model change; the selected-Persona chat path walked live on 8806 to a completed, accepted result with the identity intact | Audible voice check — P2-5 |
| Voice / TTS / lip-sync | Y | Y | Y | Y | N | PARTIAL | 8 TTS profiles, 6 reused `speaking.webm`, browser speech default, owner TTS opt-in | Audio never heard; phoneme lip-sync absent by design — P2 |
| Model Registry | Y | Y | Y | Y | P | IMPLEMENTED | Persona / account / model separate; own-key wizard; capabilities, cost, latency | Only ever exercised with the named local test executor |
| Router | Y | Y | Y | Y | P | IMPLEMENTED | Candidates, exclusions, reason codes, shadow vs active, apply pinned to the exact preview; test-executor observations disqualified from real routing | No comparison between two real providers |
| Outcomes | Y | Y | Y | Y | Y | DONE + VERIFIED | Outcome and evaluation produced, displayed and accepted on the live route | — |
| Evaluation | Y | Y | Y | Y | Y | DONE + VERIFIED | Independent verifier; per-check pass/fail in the inspector; rejects wrong and corrupted answers | — |
| Reputation | Y | Y | Y | Y | P | PARTIAL | Honest labelling: <3 observations → `NEW`; diagnostics → «3 из 3 · диагностика»; manual → «без рейтинга» | Model / agent-role / decision-outcome not three separate scopes — P1-3 |
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
Files/modules: application_chat, coordinator, ai-command-center.js
Evidence required: UI test plus one browser pass
Owner action required: NO
Assigned to: unassigned
Status: OPEN
```

```text
ID: P1-3  One reputation scope where three are required
Target truth: Model Performance, Agent Role Performance and Decision/Outcome
              Performance stored and displayed separately, each with its own
              sample size, confidence and evidence.
Files/modules: model_evaluation, presentation, ai-command-center.js
Evidence required: presentation tests that fail if one score is reused elsewhere
Owner action required: NO
Assigned to: unassigned
Status: OPEN
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
ID: P1-5  External-agent onboarding does not exist
Current state: No remote tools or tasks, no MCP, no A2A, no general protocol.
Target truth: Either a minimal agreed supported protocol, or an explicit removal
              from the acceptance scope.
Evidence required: implementation with tests, or a recorded product decision
Owner action required: YES — an executor may not drop this unilaterally
Assigned to: unassigned
Status: OWNER ACTION REQUIRED
```

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
| P0-4 · CI runs, and can finish | `437febf4` | run 34516120281 green on all three jobs; the 30-minute Windows cap that cancelled run 34510366536 was raised to 120 in both workflows, `ci.yml` included, where it would have cancelled main PRs too |
| P0-5 · owner acceptance build | `4d9ff737` | :8806 on an immutable SHA, disposable data, zero external calls, 10 screenshots, click-by-click route |

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

```text
Last safe commit: 437febf4 — pushed, CI green on all three jobs. Later commits
                  are documentation only. Local full regression was also green
                  at c3a79675 (5463 / 0 / 117).

Uncommitted files: none. Re-check `git status` before assuming that.

Active processes:
  PID 20328 — Local 8765, code 2b6d0112, owner data root. DO NOT switch or restart.
  PID 8852  — old acceptance instance :8804, code 92d873e3. Superseded by :8806;
              it still holds the historical stuck task ef1b1052 as evidence of
              the behaviour P0-2 replaced. Stop it only deliberately.
  :8806      — current acceptance build, SHA 4d9ff737, disposable data root.

Tests currently running:
  None. CI run 34516120281 on 437febf4 finished green on all three jobs.

Known failures: none at the current head.

Do not touch:
  - Local 8765 and the owner data root under NT-Analyzer/data
  - The bases of PR #280–#284
  - Any Codex branch other than codex/agent-world-unified-acceptance
  - deploy/testing/acceptance.env or any generated DSN — never into Git

Exact next action:
  P1-1 — give the Coordinator a second operation class whose children produce
  new analysis rather than another fact-transfer check. `coordinator.commission`
  currently hard-codes `prepare("json_arithmetic", ...)` as the root and
  overwrites every node with `operation="verify_fact_transfer",
  produces_new_analysis=False`. The graph machinery underneath already supports
  more; the constraint is in that one function. Prove it the way the existing
  lifecycle test does, in tests/test_agent_world_coordinator_integration.py.
```
