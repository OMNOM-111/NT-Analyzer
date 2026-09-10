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

CURRENT IMPLEMENTATION COVERAGE: 85%
CURRENT OWNER ACCEPTANCE READINESS: 56%

CURRENT INTEGRATION BRANCH: codex/agent-world-unified-acceptance
CURRENT INTEGRATION SHA: 92d873e3364d9bea5a6c49fc82f08b9bfc629de2
CURRENT WIP: dirty — 9 files, the render + pre-enqueue fix (being saved now)
CURRENT LOCAL 8765 SHA: 2b6d0112bef88c5bfb73970de64ec5518443e56b (44 commits behind)
CURRENT ACCEPTANCE INSTANCE: http://127.0.0.1:8804 — serves 92d873e3, disposable data root
CURRENT VERSION: 0.10.0-beta.96 (pre_release)

LAST VERIFIED: 2026-09-10
UPDATED BY: Claude (independent audit + P0 continuation)
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
IMPLEMENTATION COVERAGE: 85%   (30.5 / 36)
OWNER ACCEPTANCE READINESS: 56%   (20.0 / 36)

CHANGE SINCE PREVIOUS CHECKPOINT:
Implementation: +0 pp
Acceptance:     +0 pp
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
| Persona | Y | Y | Y | Y | P | IMPLEMENTED | Identity, aliases, main assistant, style, face, role, voice prefs survive restart and model change — browser-confirmed on e45 | Selected-Persona chat path — P0-3 |
| Voice / TTS / lip-sync | Y | Y | Y | Y | N | PARTIAL | 8 TTS profiles, 6 reused `speaking.webm`, browser speech default, owner TTS opt-in | Audio never heard; phoneme lip-sync absent by design — P2 |
| Model Registry | Y | Y | Y | Y | P | IMPLEMENTED | Persona / account / model separate; own-key wizard; capabilities, cost, latency | Only ever exercised with the named local test executor |
| Router | Y | Y | Y | Y | P | IMPLEMENTED | Candidates, exclusions, reason codes, shadow vs active, apply pinned to the exact preview; test-executor observations disqualified from real routing | No comparison between two real providers |
| Outcomes | Y | Y | Y | Y | P | IMPLEMENTED | Outcome records drive the aggregate and the chat report | Live route |
| Evaluation | Y | Y | Y | Y | Y | DONE + VERIFIED | Independent verifier; per-check pass/fail in the inspector; rejects wrong and corrupted answers | — |
| Reputation | Y | Y | Y | Y | P | PARTIAL | Honest labelling: <3 observations → `NEW`; diagnostics → «3 из 3 · диагностика»; manual → «без рейтинга» | Model / agent-role / decision-outcome not three separate scopes — P1-3 |
| Consensus | Y | Y | Y | Y | P | IMPLEMENTED | Independent same-input contributions, then a separate Court | Synthetic only |
| Court | Y | Y | Y | Y | P | IMPLEMENTED | 3 isolated sessions from one sealed packet, unweighted 2-of-3, failure-domain diversity, provenance-checked votes, revocation re-checked after the call, judges cannot execute | Never three genuinely different providers — P2 |
| Execution | Y | Y | Y | Y | P | IMPLEMENTED | Immutable approved decision, capability/device re-check, budget, idempotency, cancel, restart | Approved-scope reconstruction — P0-3 |
| Deviation | Y | Y | Y | Y | P | IMPLEMENTED | Provider and application deviations recorded; material deviation returns to review | Live route |
| Memory | Y | Y | Y | Y | P | IMPLEMENTED | 10 HTTP E2E cases, two real cookie sessions: share, revoke, expire, foreign-workspace refusal, per-request re-check | No visual two-user route; not on PostgreSQL |
| Strategy Projects | Y | Y | Y | Y | P | IMPLEMENTED | Versioned records, comparison jobs | Real comparisons need permitted connections |
| Process Intelligence | Y | Y | Y | Y | P | IMPLEMENTED | Read-only pattern detection with cooldown → explicit proposals; no transcript reader, no model call, no auto-enable | Live route |
| Routines | Y | Y | Y | Y | P | IMPLEMENTED | Per-routine consent separate from automation permission and budget | Live route |
| Scheduler | Y | Y | Y | Y | P | IMPLEMENTED | Scanner has a real worker producer; grant, capability, budget, device re-checked per occurrence | Self-starting run shown once, on older code |
| Calendar | Y | Y | Y | Y | P | IMPLEMENTED | Workspace events, local input stored UTC | Live route |
| SF Chat | Y | Y | Y | Y | P | IMPLEMENTED | Task cards, deep links, delivery recovery without a second model call, human and AI stores separate | Live request path — P0-2, P0-3 |
| SF Social | Y | Y | Y | Y | P | IMPLEMENTED | Prepare → explicit publish; verified sources only; corrupted receipts never attested; private memory never publishable | One real publication is an owner decision |
| Owner Preview | Y | Y | Y | Y | P | IMPLEMENTED | Isolated synthetic operator with its own domains; deliberately no provider, worker, Router, Court, publication or routine execution | Manual route not re-run on final code |
| Ordinary-user model onboarding | Y | P | Y | P | N | PARTIAL | Wizard driven in a browser with a placeholder key against the local executor | Real key, real endpoint, real BYOK E2E — P1-4 |
| External-agent onboarding | N | N | N | N | N | NOT IMPLEMENTED | — | No remote tools/tasks, MCP or A2A — P1-5, needs an owner product decision |
| UI / UX | Y | Y | Y | Y | N | PARTIAL | All eight expected sections exist as drawer panels behind three tabs | Header counter lag, narrow-column wrapping, structure vs mockups — P3 |
| Security / tenant isolation | Y | Y | Y | Y | Y | DONE + VERIFIED | FORCE RLS; foreign workspace reads 0 and inserts fail `42501`; device and session re-checked per request; SSRF guard; no secret in Git | — |
| Restart / idempotency | Y | Y | Y | Y | Y | DONE + VERIFIED | Stop/restart/re-read against PostgreSQL; duplicate dispatch and replay refused | — |
| Documentation | Y | Y | Y | Y | Y | DONE + VERIFIED | Per-SHA receipts, file hashes, explicit withdrawn-claims section, skips never counted as passes | — |
| Git / CI | Y | Y | Y | P | N | PARTIAL | Immutable per-SHA worktrees, preserved originals, no force pushes | **No workflow triggers on this PR's base** — P0-4 |

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
Status: IN PROGRESS — targeted suites green, checkpoint being saved
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
Status: IN PROGRESS — folded into the P0-1 checkpoint
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
Status: OPEN
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
Status: OPEN
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
Status: OPEN
```

### P1 — REQUIRED FUNCTIONAL REMAINDER

```text
ID: P1-1  Coordinator is not a general planner
Current state: commission hard-codes a json_arithmetic root and forces every
               child to verify_fact_transfer; no descendant produces new analysis.
Target truth: At least one more real operation class whose child roles produce
              new analysis, selected by role rather than supplied by the caller.
Files/modules: coordinator.commission, delegation._graph
Evidence required: a second lifecycle integration test of the same shape
Owner action required: NO
Assigned to: unassigned
Status: OPEN
```

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
| _(nothing yet in this cycle)_ | — | — |

## NEXT AGENT START HERE

```text
Last safe commit: 92d873e3364d9bea5a6c49fc82f08b9bfc629de2
                  WARNING: its full regression is 14 failed. Do not treat it as green.
                  The last fully green saved SHA is e45b64b0121014c5d796553ae8b512d98a5782ae.

Uncommitted files: (being saved by the current session — re-check `git status` first)
  NT-Analyzer/app/ai_control_center/domain_gateway.py
  NT-Analyzer/app/ai_control_center/model_service.py
  NT-Analyzer/app/static/aurora/assets/pages/ai-command-center.js
  NT-Analyzer/app/static/aurora/assets/ui.js
  NT-Analyzer/tests/agent_world_refresh_ui_harness.cjs
  NT-Analyzer/tests/test_agent_world_live_refresh_ui.py
  NT-Analyzer/tests/test_agent_world_status_presentation.py
  NT-Analyzer/tests/test_agent_world_ui.py
  NT-Analyzer/tests/test_agent_world_pre_enqueue_rejection.py  (new file)

Active processes:
  PID 20328 — Local 8765, code 2b6d0112, owner data root. DO NOT switch or restart.
  PID 8852  — acceptance instance :8804, code 92d873e3, disposable data root.

Tests currently running: none

Known failures:
  92d873e3 full run: 14 failed — 13 in test_agent_world_status_presentation.py,
  1 in test_agent_world_ui.py. Cause: the disposable DOM harness returned the tab
  list for every querySelectorAll selector, so the page fell back to its error
  state and negative copy assertions passed against the wrong HTML. Fixed in the
  uncommitted work above.

Do not touch:
  - Local 8765 and the owner data root under NT-Analyzer/data
  - The bases of PR #280–#284
  - Any Codex branch other than codex/agent-world-unified-acceptance
  - deploy/testing/acceptance.env or any generated DSN — never into Git

Exact next action:
  P0-3 — make a selected-Persona SF Chat request reach a result. Start from
  tests/test_agent_world_pre_enqueue_rejection.py::_reject_selected_scope, which
  already reproduces the failure by removing persona_selection from the approved
  request; the product fix is to keep that field in the approved digest without
  relaxing the tamper guard.
```
