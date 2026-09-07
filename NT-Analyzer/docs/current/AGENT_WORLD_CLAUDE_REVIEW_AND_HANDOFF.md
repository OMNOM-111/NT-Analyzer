# Agent World — independent review, fixes and handoff to GPT/Codex

Companion to [AGENT_WORLD_IMPLEMENTATION_STATUS.md](AGENT_WORLD_IMPLEMENTATION_STATUS.md),
which remains the single canonical program status. This document records one
review pass: what was checked, what was found, what was changed, what was not,
and the exact next operation. It does not restate program scope and is not a
second status.

Reviewer: Claude (Opus 5), 2026-09-06. Scope: the eight owner-reported screen
findings first, then the checks and unfinished items named in the same
instruction. No merge, no deploy, no release, no flag was enabled, no budget
was raised and no provider was called.

## 1. Source and runtime identity

| Field | Start | End |
| --- | --- | --- |
| Review branch | — | `claude/agent-world-review-and-hardening` |
| Base | `codex/agent-world-owner-preview` @ `45ab4361d5ab9b8422ec049c0c689953d548a318` | unchanged |
| Worktree | — | `C:\Users\dimon\Documents\StratForge-worktrees\claude-agent-world-review` |
| HEAD | `45ab4361` | `c865db2248a12f6927d077dc31efe8b05c02426e` |
| Owner Local 8765 | `2b6d0112bef88c5bfb73970de64ec5518443e56b`, beta.96 | **unchanged — not restarted, not switched** |
| Version | `0.10.0-beta.96` | unchanged; no new beta assigned |
| Migrations | 1–22 | unchanged; no new migration |

**The runtime/HEAD difference is explained, not a fault.** `45ab4361` is
`2b6d0112` plus one documentation-only commit
(`docs(agent-world): record integrated Local review evidence`, 8 files, all
under `docs/`). `git merge-base --is-ancestor 2b6d0112 45ab4361` is true. The
Local process is `C:\Python312\python.exe -m app.server 8765`, launched by
`agent-world-owner-preview\.artifacts\local-switch-20260905\launch_local.py`,
serving the clean detached checkout `StratForge-worktrees\agent-world-local-runtime`
against the original owner data root and workspace
`ws_owner_training_c1fe3f2f8a52`. `/api/health` confirms
`build_id=dev-0.10.0-beta.96-2b6d0112bef8`, `dirty=false`, `preview_sandbox.enabled=false`,
`live_trading_allowed=false`.

Working trees of `agent-world-owner-preview` and `agent-world-local-runtime`
were clean at the start of this pass and were not touched. `45ab4361` is the
newest commit on every local and remote branch; nothing newer was found to
preserve.

Commits added, in application order:

1. `72f7fc88` — separate the states a single status number conflated
2. `42b60a2b` — return keyboard focus and demote raw evidence to details
3. `c865db22` — Persona face, connection identity, PostgreSQL scope guards

`git diff --stat 45ab4361..HEAD`: 12 files, +1099 / −53. Six source files
(`presentation.py` new, `domain_gateway.py`, `domain_service.py`,
`live_gateway.py`, `model_service.py`, `ai-command-center.js`,
`ai-command-center.css`), six test files (three new).

## 2. The eight reported findings

Every one was reproduced against the running owner Local **before** any change,
from the live `/api/ai-control-center/overview` payload and the rendered DOM.
Reproduction data: `tasks_total:20`, `active_tasks:0`, `completed:16`,
`failed:4`, `attention:4`, three Personas all `status:"active"`, every one of
the twenty tasks carrying `progress_pct:100`.

| # | Area | Verdict | Cause | Fix | Test |
| --- | --- | --- | --- | --- | --- |
| 1 | «В работе 0» over a panel headed «Сейчас в работе» | **confirmed** | Two definitions of "in progress": the server counted `{ready,queued,running}`, the panel heading widened that set with `review,blocked,planned`. Two `review` tasks satisfied the second and not the first. | One shared phase split — executing / awaiting_review / awaiting_decision / done / failed / cancelled — in `presentation.py`, mirrored in the page. Metric and heading now read the same field. | `test_metric_and_panel_heading_cannot_contradict_each_other`, `test_phase_split_never_folds_review_or_blocked_into_execution` |
| 2 | Results count presented as task count | **confirmed** | «Завершено 16» was captioned «Сохранённые результаты» while holding a task count. | Caption corrected to «Задачи с принятым результатом»; `stats.results_total` added as the separate count of stored outcomes (19 against 20 tasks on live data). | covered by the metric render tests |
| 3 | Agent occupancy | **confirmed** | `status` carried the Persona lifecycle value; `active` rendered as a green «Активен» for all three agents whether idle or busy, and no "free" state was ever emitted. | `availability` and `occupancy` are separate DTO fields and two separate chips: «Включён» + «Свободен» / «Выполняет задачу». | `test_enabled_idle_agent_is_not_presented_as_working`, `test_executing_agent_is_shown_as_enabled_and_busy`, `test_suspended_agent_is_not_rendered_with_the_success_style` |
| 4 | «Требуют внимания 4», three cards | **confirmed** | `alerts.slice(0, 3)` with no overflow affordance; the fourth (a failed `connection_exact`) was unreachable. Cards carried no reason, no time and no action. | Kept at three, added «Показать все (N) →» into the Работа tab pre-filtered to a new `attention` filter. Each item now carries `reason`, `action_hint`, `since` and `phase_label` from the server. | `test_truncated_attention_list_offers_a_route_to_the_remaining_items`, `test_attention_card_shows_why_and_what_to_do`, `test_each_attention_phase_states_a_reason_and_a_next_action` |
| 5 | 100 % beside «Нужна проверка» | **confirmed** | `progress_pct = 100 if status not in _ACTIVE else 0` — every terminal status, failures included, rendered a full bar. | `presentation.progress_pct`: 100 only for a finished task, 0 while executing, `None` otherwise, and the card then shows its phase instead of a bar. | `test_unfinished_task_reports_no_completion_percentage`, `test_unfinished_task_card_shows_its_phase_instead_of_a_full_bar`, `test_finished_task_card_still_shows_measured_progress` |
| 6 | Rating reads as proven quality | **confirmed** | A large «100%» with `n = 3`; the class of check (`json_arithmetic`), the origin and the confidence were in the payload but not on the card. The server's own `label: "OBSERVED"` was discarded. | Every score now carries its class («Арифметика · JSON»), observation count, confidence and origin, on the mini card, the agent card and the rating table. | `test_score_always_carries_the_class_of_check_it_was_measured_on` |
| 7 | Raw enum keys and evidence as prose | **confirmed** | Titles were `f"{persona} · {rubric_key}"`; stage printed `provider_receipt` / `awaiting_provider`; summaries inlined 64-character digests, a full JSON payload and a bare report path next to a button that already linked it. | Human labels for every rubric and stage; digests, JSON and links move into a details block beside the text. Nothing is deleted — the digests, the JSON, the link and the chart artifact are all still reachable, and machine values are kept together under technical identifiers in the inspector. | `test_raw_enum_keys_do_not_reach_the_owner_facing_card`, `test_long_hash_moves_out_of_the_sentence_but_is_still_available`, `test_embedded_json_payload_moves_into_technical_details`, `test_inline_report_link_moves_to_details_without_a_dangling_label`, `test_unparseable_brace_text_is_not_silently_swallowed` |
| 8 | Accessibility | **partly confirmed** | Escape closed the Task Inspector but left focus on the closed panel. No clipped controls or horizontal overflow were reproduced at 1590 px, 1170 px or in the narrow layout — the metric row is now `auto-fit` and both chips wrap. | Focus target is captured only when no inspector is open and never from inside the drawer, and restored through one path shared by Escape and the back control, falling back to the active tab if the original control was re-rendered away. | `test_escape_returns_focus_to_the_control_that_opened_the_inspector`, `test_inspector_rerender_does_not_overwrite_the_saved_focus_target`, `test_focus_falls_back_to_the_active_tab_when_the_invoker_is_gone` |

Two further findings from the same pass:

- **System conflated four different facts.** «Исполнение · Активен» described
  the legacy worker, while Execution V2 was absent from the panel entirely, so
  a green card could be read as engine readiness. Each component now reports
  `implemented`, `enabled`, `mode` and `available` separately, and Execution
  Engine V2, Router and autonomous scheduling are listed explicitly as not
  implemented. No flag was enabled to produce a green card.
  Tests: `test_system_reports_implementation_and_availability_separately`,
  `test_implemented_but_switched_off_component_is_not_reported_as_missing`,
  `test_readiness_grid_states_each_axis_for_the_owner`.
- **Connection labels read as permanent bindings.** Stored labels are
  «Толик · DeepSeek Flash», «Иван · Gemini Flash», «Анна · Azure Mini» — free
  text the owner typed into one field. Иван holds two connections (Z.AI
  retired, Gemini active). The card now names the Persona, provider account,
  model and connection kind separately and says the label is a name for the
  link. Stored labels were **not** rewritten. Test:
  `test_connection_reports_the_persona_it_points_at_beside_its_own_label`.

### Root causes, by file

- `model_service.task_detail` — title from the raw rubric key; `progress_pct`
  from terminal-status membership. Both replaced; `phase`, `phase_label`,
  `stage_label`, `task_class_label` added. `stage`, `status`, `task_class` and
  `rubric_key` keep their machine values, and four existing tests that assert
  those machine values still pass unchanged.
- `domain_gateway.overview` — the agent `status` fallback to the Persona
  lifecycle; `attention` as bare task rows; `activity` printing the raw status.
- `ai-command-center.js` — the widened `active` set behind the panel heading;
  `alerts.slice(0, 3)`; `evaluationMeta` discarding class and origin; the
  drawer re-render overwriting the focus target.

## 3. What was verified without changing anything

- **Court.** Correct as implemented. Tally is `approve >= 2` over unweighted
  verdicts; `confidence` is stored on the vote and never enters the count
  (`court_quorum: "2-of-3-unweighted"`). `execution_allowed: False` and
  `human_execution_approval_required: True` are recorded on the approval. Each
  vote is rebound-checked against owner, session, packet and model. A decision
  whose evidence packet changed after the case was opened raises
  `court_decision_changed` rather than executing on the old approval. Critical
  risk additionally requires two distinct failure domains.
- **Isolation.** Cross-scope coverage already exists at the repository level
  (`test_cross_scope_read_write_and_artifact_isolation`), the gateway level
  (`test_existing_foreign_user_model_and_task_are_not_visible`,
  `test_task_chat_body_cannot_select_foreign_conversation`,
  `test_expired_entitlement_can_open_own_existing_chat_but_not_foreign_chat`,
  `test_publication_prepare_cannot_read_foreign_or_missing_outcome`) and over
  HTTP (`test_foreign_workspace_cannot_read_known_shared_ids_or_artifacts`).
  All pass on this branch. A second live human account was not created: that
  needs owner registration, and no account was finalised on the owner's behalf.
- **Interrupted delivery and repeat execution.** Correct as implemented and
  already covered by `tests/test_agent_world_model_delivery.py` (15 cases, all
  passing here). The exact scenario named in the instruction — the model
  answered but the SF Chat append failed — is
  `test_transient_chat_failure_retries_persisted_result_without_second_call`:
  the persisted result is redelivered and no second provider call is made.
  Alongside it: restart after completion but before the delivery enqueue, an
  append repaired idempotently before the inbox ack, competing monitor and
  worker claims publishing exactly once, a replaced or unclaimed claim unable
  to publish, bounded retries, and no retry enqueued while the provider is
  still pending. An unsealed `review` result is explicitly not deliverable.
- **A model response cannot widen what may be executed.** `finish_dispatch`
  re-checks `model_plan_verified` inside its lock, re-runs `admit()`, rejects a
  scope mismatch, and dispatches only one of two fixed kinds — a backtest or a
  desktop snapshot. The chart command string is constructed server-side from the
  validated spec rather than taken from the model's text, and the idempotency
  key is derived from the task id, so a repeat cannot create a second source
  job. Model text therefore fills a pre-approved spec; it never names the
  action.
- **Layout.** No clipped control and no horizontal page overflow at 1590 px or
  1170 px with real data.

## 4. PostgreSQL: what the 41 actually are

The record carried a historical "41 PASS" beside a current "41 skipped" without
saying what either covered. Settled:

| Module | Cases | Covers |
| --- | --- | --- |
| `test_production_storage.py` | 12 | Stage 8 storage core |
| `test_production_workers.py` | 12 | production worker scaling |
| `test_sf_chat_relational_postgres.py` | 9 | SF Chat relational read path, index use, FORCE RLS |
| `test_stage8_postgresql.py` | 8 | Stage 8 control/data plane acceptance |

All four are gated on `STRATFORGE_TEST_POSTGRES_ADMIN_URL` +
`STRATFORGE_TEST_POSTGRES_URL` and skip — never silently pass — when the DSNs
are absent. **None imports `ai_control_center`.** No shipped migration (1–22)
creates an Agent World table. `SQLiteAgentWorldRepository` is the only Agent
World repository.

So: the historical 41 PASS proves the Stage 8 plane and the SF Chat read path
and says nothing about Agent World; the current 41 skips are not lost Agent
World coverage, because that coverage never existed. There is nothing for a
PostgreSQL run to exercise in Agent World until an adapter and a schema exist.
`tests/test_agent_world_storage_scope.py` (15 cases) pins each of those facts,
including the migration count and the case count per suite, so a future adapter
must update the claim rather than inherit an unrelated green run.

An isolated real-PostgreSQL run of migrations, atomicity, outbox, idempotency
and RLS **for the Agent World schema was not performed, because that schema
does not exist.** This is a prerequisite ordering fact, not a skipped check.

## 5. Verification

Commands run from `NT-Analyzer/`, Windows, Python 3.12, Node v23.2.0.

| Check | Result |
| --- | --- |
| `pytest tests/test_agent_world_status_presentation.py` | 38 passed (new) |
| `pytest tests/test_agent_world_inspector_focus.py` | 3 passed (new) |
| `pytest tests/test_agent_world_storage_scope.py` | 15 passed (new) |
| `pytest` over the six Agent World suites touched | 482 passed |
| `node --check` on `ai-command-center.js` | pass after every edit |
| `pytest` over delivery, session authority and storage | 118 passed |
| `python -m compileall app tools tests` | pass |
| `node --check` over all 23 shipped Aurora JS files | pass |
| `python tools/pre_release_check.py` | PASS — 543-file bundle, static scan in bundle, runtime reads, Python compile, JavaScript syntax |
| `python NT-Analyzer/tools/release_static_scan.py --scan all` from the repository root | CSP OK, SECRETS OK, MARKDOWN OK |
| `python tools/validate_external_gpt_context.py` | EXTERNAL GPT CONTEXT OK |
| Full regression on `6b111590` | **4296 passed, 42 skipped, 0 failed, 0 errors**, 1007.59 s, `.artifacts/claude-review/full-regression-6b111590.xml` |

**Every new presentation and focus regression was verified to fail on the
pre-fix code** by stashing only the source file and re-running: 10 of the
presentation cases and all 3 focus cases failed before the change and pass
after. The focus tests only reproduce the defect because the DOM shim models
the shell adding the drawer's `open` class inside `requestAnimationFrame`; with
a synchronous shim the old code passes and the test proves nothing.

One existing test was changed rather than the code:
`test_canonical_ready_tasks_remain_visible_as_queued_in_active_and_waiting_views`
asserted the literal string `['running', 'working', 'active', 'ready',
'queued', 'review', 'blocked', 'planned']` — the conflated set that *is*
finding #1. Its real intent (a queued task stays visible) is preserved and now
asserted through the phase mapping. Two persona payload tests were widened by
the new `avatar_key` field, with an added assertion that credentials, scope,
model and authority still cannot enter that payload.

The 42 skips are 41 PostgreSQL cases — exactly the four suites enumerated in
section 4, each reporting its missing DSN — plus one POSIX-permission-bits case
in `test_platform_secrets`. **The earlier records say 44.** The difference is
not lost coverage and is not caused by this branch: two shell cases gated on
`shutil.which("bash")` (in `test_secret_containment.py` and
`test_phase9_blue_green.py`) skipped on the earlier runner and **ran and passed
here**, because Git Bash is on PATH in this environment. So this run has two
more genuine passes and two fewer skips than the recorded baseline. A runner
without bash will show 44 again, and that is correct rather than a regression.

The "legacy 13/13 suites" step from earlier records was **not** reproduced: no
runner for it exists in the repository under that name, and the legacy tests it
appears to refer to (`tests/test_legacy_isolation.py` among them) run inside the
full suite. If GPT knows the intended invocation, it should be run before
integration rather than inherited from an earlier record.

CI was **not** run for these commits. The branch is local and unpushed.

## 6. Browser verification and its limits

Browser checking was explicitly required and was done, with one honest caveat.

Reading the live owner Local worked and produced the reproduction data above.
Rendering the *fixed* page needed the new server contract, so an isolated
instance was run on port 8799 from this branch against a copied data root
(`scratchpad/iso-data`) whose job queue was cancelled before launch, so it
could not dispatch to NinjaTrader or a provider. The owner's Local, its data
root and its worker were never touched.

That instance authenticates the owner at the API level (`/api/auth/status`
returns owner, founder, agent_world enabled) but its Aurora shell renders a
reduced rail, so the full page would not boot there. The page module, the real
CSS and the real API were therefore driven through a temporary harness served
from the same origin. The harness was deleted before commit and is not in any
commit. Through it, against the owner's real data and the new server:

- metrics read Выполняется 0 / Ожидают проверки 2 / Завершено 16 / Команда 3 /
  Требуют внимания 4, with the panel headed «Ожидают вашего решения»;
- no `<progress>` element rendered for the two review tasks;
- three alert cards plus «Показать все (4) →»;
- three agents each showing «Включён» + «Свободен»;
- ratings showing «Арифметика · JSON», `n = 3 · низкая`;
- no 64-hex digest anywhere in the visible text, with digests, JSON and the
  report link present in details blocks, and the 718×424 chart PNG still
  loading from its authenticated artifact route.

**Not covered by a browser this pass:** the fixed page inside the full Aurora
shell with the owner's own session. That needs the branch activated on a Local,
which is an owner decision and was not taken.

**Separate finding, not caused by these changes and not fixed here:**
`ui.js` schedules the whole shell boot through `requestAnimationFrame`
(`buildShell` → `requestAnimationFrame(() => authenticateAndStart(...))`).
`requestAnimationFrame` does not fire while a tab is hidden, so any Aurora page
loaded in a background or hidden tab stays on its loading skeleton — no error,
no console message, `CURRENT_AUTH` null — until it becomes visible, at which
point it boots normally. Reproduced on 8765 and 8799; it self-heals on focus.
A `setTimeout` fallback beside the `requestAnimationFrame` would close it.
`ui.js` is shared, so it was left to a single owner rather than edited here.

## 7. Not implemented, not verified, or waiting on the owner

Unchanged from the program record unless noted.

- **Agent World PostgreSQL/RLS adapter** — not implemented. Section 4 explains
  why no PostgreSQL acceptance was possible for it.
- **Router** — not implemented for Agent World; not switched to shadow.
  Observed scores still carry `routing_effect: "none"`. Now stated as such in
  the System panel. **Before building one, read `app/ai_lab/agent_router.py`.**
  A router already exists and is 240 lines: `candidates()` filters the owner's
  global registry by configured key, endpoint type, enablement, cooldown and
  billing mode, orders by role and complexity, and then re-ranks through
  `ai_ratings.rank_agents(role, rows, explore=True, workspace_id=...)` — that is
  already learned, workspace-scoped, exploring routing that never bypasses
  key/budget/cooldown gates, and it already documents that it grants no
  execution authority. The genuine gap is scope, not mechanism: the existing
  router routes StratForge staff roles over the owner's global registry using
  star ratings, whereas Agent World needs to route a *user's own* connections
  for a *task class* using Agent World's own bounded evaluations. Those
  evaluations are a deliberately separate evidence class. Reuse the ranking and
  exploration mechanism rather than writing a second one; a duplicate here is
  exactly the second implementation the instruction rules out.
- **Execution Engine V2 with Deviation Control** — not implemented. Now a
  separate System row so the working legacy worker cannot imply it.
- **Multi-level delegation** — one explicit typed hand-off exists and is
  verified; general recursive delegation with depth, budget and cycle limits is
  not implemented.
- **Autonomous schedule** — not implemented; accepted routines deliver one
  manual discussion message and nothing runs at a due time. Now a separate
  System row.
- **Persona voice** — a real gap, newly stated. The Агенты tab describes a
  Persona as "имя, лицо и голос". The face now exists as an explicit stored
  choice; **voice does not**: the Persona record has no voice field and Agent
  World does not call the existing `agent_tts` stack or the browser speech
  fallback in `ui.js`. The form now says so rather than implying otherwise.
  The owner's requirement that an unavailable voice must fall back instead of
  breaking the chat cannot be tested until the path exists.
- **Ordinary-user registration, own key, live connection wizard** — unchanged
  and still owner-dependent. The draft account `aw_model_review_0905` was left
  alone; no duplicate was created, no terms were accepted, no owner key was
  copied.
- **Multi-human sharing and revocation, permanent SF Social publication** —
  unchanged; still owner-dependent.
- **CI for these commits** — not run; branch unpushed.
- **Full owner visual acceptance of the reworked screens** — not given. The
  larger deviation from the mockups was deliberately not addressed: only
  functional defects in the eight reported areas were fixed, and no
  recomposition of the layout was attempted.

## 8. Rollback, ownership and the next operation

- **Rollback.** Drop to `45ab4361`. The three commits are additive and confined
  to `app/ai_control_center/*`, `app/static/aurora/assets/pages/ai-command-center.{js,css}`
  and `tests/`. No migration, no API route, no flag, no stored record and no
  authority changed, so a revert needs no data repair. Stored persona profiles
  written before this change simply have no `avatar_key` and fall back to the
  name initial.
- **Processes.** The isolated instance on port 8799 and its copied data root
  under the session scratchpad are test-only and can be killed and deleted at
  any time. The owner Local on 8765 is untouched and still serving `2b6d0112`.
- **Shared files.** `domain_gateway.py`, `domain_service.py`, `model_service.py`,
  `live_gateway.py`, `presentation.py`, `ai-command-center.js` and
  `ai-command-center.css` were changed by this pass and are now free. `ui.js`,
  `server.py` and `permissions.py` were **not** modified.
- **Next operation for GPT/Codex**, in order:
  1. Read `git diff 45ab4361..c865db22` — it is the whole change.
  2. Decide whether to carry these three commits onto
     `codex/agent-world-owner-preview` or take them as a separate PR. They were
     deliberately not pushed to the Codex branch and PR #282's base was not
     touched.
  3. Run the full regression and exact-SHA CI for whichever SHA results. The
     runs recorded here certify `c865db22` only.
  4. Then continue the canonical order: Router in shadow before it influences
     anything, then the Execution Engine, then bounded delegation, then the
     schedule behind an explicit opt-in with entitlement recheck, run history
     and a kill switch.
  5. Before claiming any PostgreSQL result for Agent World, add the schema and
     adapter first, then update `tests/test_agent_world_storage_scope.py` — it
     will fail until the statement it pins is corrected.

Secrets, cookies, personal data, working databases and raw runtime archives
were not added to Git. The copied data root, the isolated launcher and the
deleted harness live only under the session scratchpad.

## 9. Commits, in application order

| SHA | What it does |
| --- | --- |
| `72f7fc88` | Separate the states a single status number conflated: phase split, occupancy, warning reasons, score provenance, System readiness axes |
| `42b60a2b` | Return keyboard focus after Escape; move digests, JSON and links into details |
| `c865db22` | Persona face, connection identity, PostgreSQL scope guards |
| `ed60fb83` | This handoff, the change record, the status link and the two Context Pack files |
| `6092ab33` | Report a completion percentage only where one is measured; correct the Router row |
| `3bb4af0f` | Do not replace stage text the legacy adapters already wrote for a reader |
| `6a1b1b52` | Drop the empty date placeholder on records that carry no date |

`git diff --stat 45ab4361..6a1b1b52`: 17 files, +1611 / −55.

Two of these came from reading rather than from a failing test, and both were
regressions this branch would otherwise have introduced: `3bb4af0f` (the
NinjaTrader and Desktop adapters already send written stages, which the new
label lookup would have replaced with a placeholder) and `6092ab33` (the
earlier fix still emitted an invented 0 % for executing tasks). Both now have
regression tests.

## 10. Contract changes

Every change is **additive**. No field was removed or renamed, no HTTP route was
added or changed, no flag, no SQL migration, no state-machine transition and no
authority check was modified.

| Where | Added | Changed |
| --- | --- | --- |
| Task DTO (`model_service.task_detail`) | `phase`, `phase_label`, `stage_label`, `task_class_label` | `title` uses the human rubric label (the key stays in `task_class`); `progress_pct` is 100 only for a finished task and `null` otherwise, replacing `100`-for-any-terminal and the invented `40`/`0` |
| Connection DTO (`model_service.model_detail`) | `persona_name` | — |
| Agent DTO (`domain_gateway.overview`) | `availability`, `occupancy`, `open_items`, `avatar_key` | `status` kept for compatibility |
| `stats` (`domain_gateway.overview`) | `executing`, `awaiting_review`, `awaiting_decision`, `done`, `cancelled`, `failed_tasks`, `results_total` | `active_tasks`, `completed_tasks`, `attention`, `failed` unchanged |
| Attention items | `phase`, `phase_label`, `reason`, `action_hint`, `since`, `task_class_label` | previously bare task rows |
| Activity items | `status`, `phase` | `summary` ends with the phase label instead of the raw status |
| System items (`domain_gateway.system`) | `implemented`, `enabled`, `mode`, `available`, `note`, plus rows `execution_v2`, `router`, `schedule` | `status` is derived from those four; `budgets` moves from the unrendered `guarded` to `active` |
| Persona create/update payload | optional `avatar_key`, validated server-side against the six shipped faces | — |

A consumer reading only the previous fields sees no behaviour change except
`progress_pct`, which is the defect being fixed.

## 11. Severity

| Finding | Severity | Why |
| --- | --- | --- |
| Counters contradicting their own panel | high | The owner cannot tell whether anything is running; the number and the card disagree about the same task |
| 100 % on failed and awaiting-review tasks | high | A full green bar next to «Ошибка» actively misreports the outcome |
| Warning counter unreachable beyond three | high | An item needing a decision is invisible with no affordance to reach it |
| Score without its class of check | high | A bare 100 % reads as proven professional quality from three arithmetic inputs |
| System conflating implemented / enabled / available | high | A green legacy worker could be read as Execution V2 readiness |
| One badge for enabled, free and executing | medium | Occupancy is unreadable, but nothing is misreported as complete |
| Connection label implying a permanent binding | medium | Misleads about the model, but the underlying records are correct |
| Raw enum keys and inline digests/JSON | medium | Unreadable rather than wrong; evidence was present |
| Escape not returning focus | medium | Keyboard users lose their place; mouse users unaffected |
| Warning cards without reason, time or action | medium | Actionable information was missing, not wrong |
| Empty date placeholder on undated records | low | Cosmetic |
| Aurora shell booting only via `requestAnimationFrame` | low, **not fixed** | Self-heals on focus; shared `ui.js` left to a single owner |

## 12. A release blocker caught in this pass

The changelog for this work initially linked to this document as
`[...](../current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md)`. `docs/changelog`
is a shipped tree and `docs/current` is not, so that link resolves in a checkout
and dangles inside the release bundle — the beta.81 signer failure that
`tests/test_pre_release_check.py::test_catches_a_link_that_leaves_the_bundle`
exists to reproduce. It is the only such link that has ever appeared in
`docs/changelog`. The changelog now names the path in plain text instead, and
`python tools/pre_release_check.py` passes with a 544-file bundle. This is why
that check has to run from `NT-Analyzer/` after the documentation is written,
not before it.

---

# Part B — second pass: Git/CI closeout, Codex WIP review, isolated Aurora

Everything above describes this branch. This part is kept separate because it
covers two different things: **B1–B3** are still this branch; **B4** is a
read-only review of somebody else's uncommitted work and certifies nothing
about it beyond what is stated there.

## B1. Git and CI

| Item | Value |
| --- | --- |
| Branch | `claude/agent-world-review-and-hardening`, pushed to `origin` |
| Draft PR | [#283](https://github.com/OMNOM-111/NT-Analyzer/pull/283), base `codex/agent-world-owner-preview` **for review only** |
| CI dispatched | [run 34067167959](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/34067167959) — **3/3 success** (static gates, windows-self-hosted, ubuntu-latest) |
| SHA that CI certifies | **`84115efc`** |
| Final SHA of this pass | **`7b7a4a65`** |

**The CI result covers `84115efc` only.** Commits landed after it
(`c468b14f`, `f589cba2`, `7b7a4a65`, plus this document), so a fresh exact-SHA
run is required before integration and is not claimed here. The secret scan
before the push was clean: every hit was the existing redaction helper,
documentation text, or the fixture that asserts `api_key` is stripped from a
persona payload. `main`, PR #282's base and the Codex branch were not touched.

## B2. Isolated full-Aurora verification

Run in the real Aurora shell, not a harness.

| Property | Value |
| --- | --- |
| Instance | `http://localhost:8801` — `localhost`, so its cookie jar cannot touch the owner's `127.0.0.1:8765` session |
| Code | this branch |
| Data root | fresh, created for this run; **the owner's data root was never opened** |
| Owner identity | synthetic id `990000001`, its own `ws_owner_training_cc4a3af5ad8c`; no owner key or cookie copied, Auth and Device Confirmation not bypassed |
| Data | synthetic records created through the real API and the real `ModelService` with a stubbed executor; **no provider was called** |
| Queue | its own; empty at start, so its worker had nothing to execute |
| Local 8765 | untouched and not restarted |

The seed deliberately produced phases the owner's live workspace does not
contain, because those are the ones the counters have to tell apart: 4 done,
1 awaiting-review, 1 cancelled, across 3 personas and 2 connections.

Verified in the shell: Обзор reading Выполняется 0 / Ожидают проверки 1 /
Завершено 4 / Команда 3 / Требуют внимания 1 above a panel headed **«Ожидают
проверки»**; Работа showing human stages, the phase in place of a bar for
unfinished work, 100 % only for completed, and the new «Требуют внимания»
filter; Агенты showing two chips, the class of check on every score and NEW
where the sample is short; System showing eight components across four
readiness axes with Execution V2, Router and scheduling as «Запланировано /
Реализовано: Нет»; refresh re-reading without losing the view; 0 clipped
elements at 1490 px; and Escape closing the inspector **after a re-render** and
returning focus to the card that opened it.

Two defects were found by doing this in the real shell rather than a harness,
and both are fixed in `7b7a4a65`: the agent chip called a review «ждут
решения», and the compatibility agent row carried neither availability nor
occupancy. Both now have regressions.

**Not covered:** this verifies *this branch*, not a merged build. SF Chat was
reachable but its end-to-end flow was not re-driven, because that needs a
provider call.

## B3. The hidden-tab boot defect

Reproduced on 8765 and 8801: `buildShell` schedules the authenticated start
only through `requestAnimationFrame`, which a browser does not run for a hidden
document, so a page opened in a background tab sits on its skeleton with
`CURRENT_AUTH` null until the tab is focused. It self-heals on focus.

**Not fixed here.** `ui.js` currently has uncommitted changes in the
`codex/agent-world-mechanisms` worktree, so it already has an active editor and
the single-owner condition is not met by this reviewer. Handed over in
`tests/test_aurora_shell_boot_visibility.py` with the reproduction, the expected
one-line change, an xfail that flips when it lands, and a standing test that a
frame and a timeout racing to start the shell must start it exactly once — so
the fix cannot arrive as a double boot that runs the auth exchange twice.

## B4. Review of the Codex work-in-progress — read-only

**Nothing was committed, stashed, reset, cleaned, renamed, moved or edited in
`agent-world-mechanisms`.** The findings below are bound to the hashes in the
snapshot record and describe that content only; the worktree was not re-read
afterwards and this section is not refreshed as it changes.

Snapshot: `scratchpad/codex-wip-review/SNAPSHOT.json`, taken 2026-09-06T23:58:24Z,
branch `codex/agent-world-mechanisms`, HEAD `45ab4361` — the same base as this
branch. 0 staged, 15 unstaged, 18 untracked; 33 files copied and hash-verified,
0 excluded. Re-hashing after the copy showed **no file changed during the
snapshot**, so it is stable. Untracked files are listed explicitly because a
`git diff` would not contain them, and only source, tests, docs and migrations
were copied — no database, cookie, secret or runtime artefact.

Tests ran against a separate tree built by extracting `45ab4361` with
`git archive` and overlaying the snapshot, so no git state was created anywhere.

### The snapshot now binds to a real commit

After the review, Codex checkpointed its own work — `f9b94445`
(`wip(agent-world): preserve isolated mechanisms checkpoint`) and `db85773f`
(`docs(agent-world): record exact WIP continuation point`) on
`codex/agent-world-mechanisms`.

Comparing the 33 reviewed files against `db85773f` by content hash:
**31 identical, 2 differ, 0 missing.** Both differences are changelog documents
Codex updated while checkpointing
(`2026-09-05-agent-world-execution-v2-deviations.md`,
`2026-09-05-agent-world-router-delegation-scheduler.md`). **Every source file,
test file and the migration are byte-identical**, so the findings in this
section apply to commit `db85773f` directly and not only to a working state
that no longer exists.

One file appeared after the snapshot and is therefore **outside this review**:
`NT-Analyzer/tests/test_agent_world_mechanism_flags.py`, still untracked at the
time of writing. The snapshot was deliberately not retaken to chase it —
findings stay bound to verified hashes rather than to a moving worktree.

### Readiness, one row per mechanism

These five states are deliberately not collapsed into "ready".

| Mechanism | Code exists | Wired to call sites | Covered by tests | End-to-end verified | Enabled in runtime |
| --- | --- | --- | --- | --- | --- |
| Execution V2 + Deviation Control | yes | yes — `execution_v2.enabled/is_managed/prepare` on task actions | **46 passed** | not attempted | no — `AI_EXECUTION_V2` default off |
| Router V2 | yes | yes — reads Agent World evaluations | **20 passed** | not attempted | no — `AI_ROUTER_V2` default off |
| Delegation | yes | yes — via `automation_authority` | **21 passed** | not attempted | no — `AI_DELEGATION_V2` default off |
| Scheduler | yes | yes — `schedule_create/queue/tick/step` | **25 passed** | not attempted | no — `AI_SCHEDULER_V1` default off |
| PostgreSQL/RLS repository | yes | yes — repository selection in `domain_gateway` | **1 passed, 68 skipped** | **no** | no |
| `task_presentation` / `task_review` | yes | server yes; page partially | **no dedicated tests** | no | reached through the overview projection |

Totals in isolation: **113 passed, 68 skipped**. Every one of the 68 skips is
the PostgreSQL suite.

### Findings

1. **The PostgreSQL adapter is the least-verified mechanism and cannot be
   verified on this machine.** 68 of its 69 cases need a real server. There is
   no PostgreSQL, Docker or Podman here — only the `psycopg` driver — so the
   migration, the RLS policies and the outbox/idempotency behaviour have never
   executed. This is the largest open risk in that delta and needs either a
   local server or an isolated DSN.
2. **Its RLS coverage reads as complete on inspection.** Migration 0023 creates
   ten `sf_aw_*` tables and applies `ENABLE` + `FORCE ROW LEVEL SECURITY` and
   `REVOKE ALL … FROM PUBLIC, stratforge_app` to all ten by name in a loop, with
   twelve explicit policies plus a looped owned-row policy. An earlier count of
   "2 RLS statements" was mine and was wrong — it counted the loop lines, not
   their effect.
3. **Flags are ordered and default off**: `AI_ROUTER_V2 → AI_TASK_GRAPH_V2`,
   `AI_DELEGATION_V2 → AI_EXECUTION_V2`, `AI_SCHEDULER_V1 → AI_EXECUTION_V2`,
   `AI_EXECUTION_V2 → AI_TASK_GRAPH_V2`, every flag `default: False`.
4. **Delegation carries real limits**: bounded depth, per-parent fan-out, a
   cycle/forward-reference guard, a repeated-ancestor-identity guard, and a
   budget authority reference.
5. **The scheduler rechecks authority per step** (`schedule_fresh_authority_required`,
   then a named authority call for create/queue/tick/step) with bounded attempts
   and timeout. `automation_authority` fails closed on a disabled workspace,
   an inactive subject, a revoked session, a revoked or expired device, and a
   revoked approval.
6. **Router V2 is not a duplicate of the AI Lab router, and my earlier note
   overstated it.** Absence of an import proves nothing; the actual path is what
   matters. `router_v2._observations` reads Agent World's own
   `EntityKind.EVALUATION` records for one exact task class, guards
   `self_scored is not False`, and counts a retry of the same input as one
   observation. `ai_lab/agent_router.py` ranks the owner's global registry for
   staff roles through `ai_ratings.rank_agents`. **Different data, different
   scope — genuinely different mechanisms.** What overlaps is the algorithm
   shape: gate candidates, rank, explore. Reusing that shape is worth
   considering; recorded as a suggestion, not a defect.
7. **`task_presentation.py` and `task_review.py` are the newest and least
   covered** — written the same morning, no dedicated tests, and the page
   consumes only `display_status`, `display_title` and `human_review` while the
   server also offers `status_label`, `needs_attention`, `result_received`,
   `verified_automatically` and `acceptance_not_recorded`. The UI integration is
   incomplete relative to the model behind it.

### The overlap, and which state logic should survive

Both branches independently built a task state projection. They must not both
land.

| Concern | This branch (`presentation.py`) | Codex (`task_presentation.py`) |
| --- | --- | --- |
| States | 6 phases | 12 display states |
| Result received vs accepted | **absent** — `succeeded` becomes «Завершено» | `result_received` «приёмка не зафиксирована», distinct from `completed` |
| Automatic verification | absent | `verified_automatically`, and `human_review: not_required` for `connection_exact` / `court_vote` |
| Human acceptance record | absent | `task_review.py`: immutable, bound to task revision and a source fingerprint, `quality_claim: False`, never execution authority |
| Waiting for a result vs running | folded into `executing` | `waiting_result` separate |
| Waiting for a decision | `awaiting_decision` | `blocked` «Приостановлено: нужно решение» |
| Counters | 6 disjoint plus attention | richer, plus `results_received` / `provider_results_received` / `application_results_received` / `acceptance_not_recorded` |

**Recommendation: keep Codex's state model and retire this branch's phase
logic.** It is a strict superset, and it already answers the question raised in
review — an automatic format check must not mean the whole result is accepted
or that execution is permitted. `presentation.py` has no such distinction and
would regress it.

What should be **ported from this branch onto that model**, because Codex's
does not cover it:

- human stage labels, plus the machine-key-versus-written-text rule that stops
  the NinjaTrader and Desktop written stages being replaced by a placeholder;
- honest `progress_pct` — a number only where one was measured;
- attention `reason` / `action_hint` / `since`, and the route to the items a
  truncated list hides;
- agent `availability` / `occupancy` / `open_review` / `open_decision`, on both
  the domain and the compatibility rows;
- the System four-axis readiness component;
- `technicalSplit` — digests, JSON and bare links into details, evidence kept;
- the Inspector focus restore and its regressions;
- the Persona face, and the connection stating the Persona it points at;
- the boot-visibility hand-over in B3.

Already covered by Codex, so **do not port**: the task phase/status vocabulary
itself, and the counters derived from it.

### Baseline statements that must be re-scoped on merge

`tests/test_agent_world_storage_scope.py` describes the reviewed baseline —
41 PostgreSQL cases in four suites, 22 migrations, one SQLite repository. Two of
its assertions **fail against the Codex tree**, by design, each carrying the
instruction to replace the expectation with checks of the new contract rather
than revert the implementation. Verified both ways: 16 pass at this baseline;
2 fail with that message against a tree that has the adapter. The migration
count and the "no Agent World PostgreSQL" statement are a dated snapshot, never
a prohibition.

## B5. Recommended merge order

1. Codex checkpoints its own WIP so it stops being uncommitted.
2. One integrator is named — GPT/Codex — and owns `ui.js`, `domain_gateway.py`,
   `live_gateway.py`, `model_service.py` and `ai-command-center.js` for the merge.
3. An integration branch takes the mechanisms first, then this branch's
   presentation, focus and identity fixes ported onto Codex's state model per
   the table above.
4. Re-scope the baseline storage statements to the new contract.
5. Apply the boot-visibility fix with its latch test.
6. Full regression plus a browser pass on the merged build.
7. Only then update Local 8765.

Not done and not authorised in this pass: merge to main, changing PR #282's
base, pushing to a Codex branch, switching or restarting Local 8765, Canary or
Production deployment, real orders, budget increases.

# Part C — integration branch: the merged build, its mechanisms, and what it leaves open

Part A reviewed the pre-merge branch. Part B reviewed Codex's checkpoint
read-only and recommended a merge order. Part C is the result of carrying that
order out as sole integrator: the merge itself, the defects the merged build
turned out to have, the mechanism scenarios that were finished, and the four
statuses this leaves behind.

## C1. Exactly what was tested, and where

| | |
| --- | --- |
| Integration branch | `claude/agent-world-integration` |
| Branch HEAD | `15cf6d761a4ec8a379853791c1c4c28e8696684b` |
| Merge commit | `922c5d52bf5d467608f4e5d9bfc0ab3622ee1b93` |
| Codex checkpoint merged | `f9b9444524aa497781fe3de7254d1bfb0e3b062c` (+ `db85773f5d2c50386744d63972d467b5a60af244`) |
| Review branch state merged in | `7d347d204ea99103e33abdd2a011eee500028fff` |
| Isolated instance | `http://localhost:8802` |
| Its data root | `…/scratchpad/aurora-integration-data` (fresh, not a copy of the owner's) |
| Its identity | synthetic owner id `990000001`, workspace `ws_owner_training_cc4a3af5ad8c` |
| Its queue | its own; no provider key, no NinjaTrader, no socket to the owner's runtime |

Never touched in this pass: Local 8765, the owner's data root, Canary,
Production, `main`, PR #282/#283/#284 and their bases, Codex's worktrees, any
real provider call, any trading action.

Local 8765: no command in this pass started, stopped, reconfigured or pointed
it anywhere. Every process this pass stopped was resolved by asking which PID
listened on **8802**, and the isolated instance was the only thing restarted.

What can be checked rather than asserted is what 8765 serves. It reports
`git_commit_sha 2b6d0112bef88c5bfb73970de64ec5518443e56b`, the same build it
served before this work began -- it was not switched to this branch. Its process
id did change during the pass (a new pid appeared at 11:30 on 2026-09-07), so
uptime is **not** evidence here and is not claimed as such; the served commit
is. An earlier draft of this section asserted continuous uptime since
2026-09-05, which was wrong.

Every result below is pinned to a SHA. Where a number came from a run, the run
is named.

## C2. Four statuses, kept apart

| Subject | Pinned at | Status |
| --- | --- | --- |
| Claude review branch | `7d347d20` | Verified in Part A/B. Presentation, focus, identity and boot fixes, each with a regression. |
| Codex mechanisms checkpoint | `f9b94445` / `db85773f` | Reviewed read-only in Part B. **Carried 30 test failures** and one module that does not exist. Both dealt with here — see C3, C4. |
| Merged build | `15cf6d76`, carried to `d30439e4` | Full suite **4521 passed, 110 skipped, 0 failed** at `d30439e4` (C7, D6). Mechanisms exercised end to end (C5). Browser-verified on the isolated instance (C6). |
| Owner Local 8765 | — | **NO.** Not switched, not restarted, not verified. Nothing here changes it. |

The fourth row is the one that matters operationally: none of this has been
applied to the machine the owner actually uses.

## C3. The 30 failures the checkpoint carried in

Fixed in `ee3252b5187529003f4397e4c8957a1ef96b55e2`. Every one of them was
traced to Codex's checkpoint alone by running the suite at `f9b94445` before
the merge — the merge introduced none of them. Two were real defects rather
than stale expectations:

* the mechanism config parser kept the last value for a repeated JSON key, so a
  document that said both `{"AI_EXECUTION_V2": ["*"]}` and a narrow list
  resolved to whichever came last; an ambiguous document now disables every new
  mechanism instead;
* the compatibility agent row lacked `availability`/`occupancy`/`open_review`/
  `open_decision`, so it could not answer the two questions every other agent
  card answers.

The remaining 28 were expectation updates the merge required, listed in the
commit.

## C4. Defects found in the merged build

Each was found on the running isolated instance, not by reading code, and each
has a regression that fails without its fix.

### C4.1 Two live endpoints answered 500 — `6126dc10`

`domain_gateway` dispatches the `automation` and `router` domains to a module
called `mechanism_gateway`. That module exists in no branch and in no worktree:
the checkpoint wired three call sites to code it never contained. On the merged
build, `GET /api/ai-control-center/domains/automation` and `.../router` both
answered:

```
500 {"error": "internal server error"}
```

with no code at all, because the `ModuleNotFoundError` escaped the handler. The
third call site is the `automation_watch` worker phase, which nothing enqueues
yet and which would have failed the same way.

The call sites are unchanged, so the module drops in unmodified when its author
lands it. Only the import is guarded, and it raises the project's own error
type, which the live layer already maps to a 409 carrying the code. After the
fix, on the same instance:

```
automation  409 {"code": "mechanism_domain_unavailable"}
router      409 {"code": "mechanism_domain_unavailable"}
```

The Aurora page's own `DOMAINS` map contains neither domain, so no screen was
reaching this; it was reachable by direct API call only. **`mechanism_gateway`
is Codex's to write — this is a fail-closed guard, not an implementation.**

### C4.2 A full progress bar on work that is not finished — `15cf6d76`

`live_backtests` derives `progress_pct` from the *source* status, so a report
that reached `done` but failed verification arrived carrying `100` while the
projection put it in `awaiting_review`. The page renders a `<progress>` element
whenever the number is present, so a completed bar sat under a card that says
the work still needs a check. Failed and cancelled rows drew one too.

This is the same defect class as finding #6 of Part A ("report a completion
percentage only where one is measured", `6092ab33`) surviving in the adapter
path, which the earlier fix did not reach.

### C4.3 The inspector and the card disagreed about the same task — `15cf6d76`

The single-task route returned an adapter row unprojected: `display_status` was
`null`, so the inspector rendered from `status`/`stage` while the list rendered
from the computed state. Same task, two bases — exactly the presentation
overlap this work exists to remove.

`projected_task` is now the one seam both paths go through. It re-derives
nothing: it projects a row that has no computed state yet, then makes progress
agree with that state instead of with the source status.

### C4.4 An adapter row completed on the strength of its type — `203eed18`

Recorded in Part B and fixed before this pass, repeated here because C6 tests it
live: a finished adapter row counted as carrying a result merely by not being a
model task. It now requires its executor's own evidence — source checksums for a
NinjaTrader report, a verified snapshot for a Desktop capture — and a finished
row with none is reported as `awaiting_review`, not completed.

## C5. The mechanism scenarios, finished

### C5.1 Permission revocation, in a live process — `9e1fb7ad`

`tests/test_agent_world_automation_revocation.py`, 6 cases, on the real stack:
the real owner row, workspace, capability override, permission resolver, feature
flags, budget check, durable job payload and Agent World records, on a
disposable data root. No provider, no socket.

Three sides, because passing only one of them would be a defect in the other
direction:

| | Result |
| --- | --- |
| No `ai_automation` grant | Neither the human approval nor worker ingress is admitted (`automation_entitlement_required`). Being the owner grants every other capability and still withholds this one. |
| Live grant + mechanism flag + approved plan + budget head room | The run **is** admitted. The worker receives a SERVICE actor derived from the human's identity, bound to the controller and the grant. |
| After withdrawal | The open worker handle, the next mechanism step, and a restarted worker replaying the same durable payload are all refused. |

Also pinned: withdrawal is not a one-way latch — restoring the grant resumes the
same approved plan under the same grant, so the fix is not a blanket automation
ban. The flag, the per-call ceiling, the approved operation kind and the plan
digest each gate a step on their own, so a grant alone is never authority.
Explicit `revoke()` supersedes the Decision without erasing it: the approval,
its human author and the completed records stay readable through a read-only
handle, and a read-only worker can still deliver what the run already produced.

Mutation-checked: granting `ai_automation` to the owner unconditionally, and
dropping the capability from the per-step check, each fail 3 of the 6 cases;
freezing the worker's authority after creation fails the restart case.

### C5.2 A Router decision that is actually used — `a223ef08`

Every pre-existing Router case ended at a denial or at shadow advice, so nothing
showed a decision being followed. The new scenario prices two connected
candidates, has the caller arrive on the expensive one, and runs the task
through normal ingress at the model the active decision points to. The provider
call lands on the routed model, not the caller's. Shadow mode over identical
evidence keeps the caller where it was — which is what separates "the router had
an opinion" from "the opinion changed which model answered". The ranking is
checked to rest on this workspace's own verified observations of that exact
class, and the decision is confirmed to grant nothing by itself
(`dispatch_performed` and `permission_granted` both stay false).

### C5.3 A scheduled run with no tick and no chat request — `a223ef08`

Every pre-existing scheduler case advances the occurrence with an explicit
`tick`, which is the path a person watching the panel takes. The new scenario
never calls it: the ordinary recovery scan finds the due controller, the
existing worker claims and executes it, and the collected result is what the
next scan reports. One provider call; the accepted manual source untouched and
still `automation_enabled: false`; the transcript only appended to by the
delivery that was already in flight; a drained queue that cannot produce a
second run.

### C5.4 Execution / Deviation on damaged evidence — `68021953`

The application path was pinned for a source that reports `failed`, and for one
that reports `done` with an intact report. The case in between was uncovered: a
run that reaches its terminal `done` folder while the evidence it left behind
does not hold up. Three kinds of damage are now applied to a real terminal
folder after the fact — the historical-data fingerprint no longer describes the
bars it was computed from, the referenced trades file is gone, the report names
a different job. Each records a deviation and stays unaccepted. The damaged
folder is read without being repaired or rewritten to make the controller
finish.

### C5.5 A harness trap worth knowing

`observed()` in the Router suite installs its arithmetic executor and leaves it
there, so a second model's connection test never returns `CONNECTION_OK` and
that candidate silently stays unverified — it appears in the result as
`routing_connection_not_verified` rather than as a fixture error. Both new cases
restore the fixture executor between models.

### C5.6 A completed external action is never reported as cancelled

Checked, not changed: this was already correct and is recorded here because it
was asked for explicitly. `cancel_dispatch` refuses at three separate points
once the external action has reached a terminal state — the source's own status,
the cancel receipt returned by the queue, and a chart receipt that has already
been saved — each raising `application_cancel_too_late`.

`test_cancel_verified_chart_receipt_is_too_late_and_never_overwrites` pins the
Desktop side: the saved receipt and its PNG bytes are unchanged after the
refused cancel, and reconcile still completes the task.
`test_cancel_running_nt_remains_pending_until_actual_terminal` pins the
NinjaTrader side, which is the harder case because a running Strategy Analyzer
is not preemptible: the request stays `waiting` with stage
`application_cancel_requested` until the source itself reaches a terminal state,
and if that state is `done` the task becomes **succeeded**, not cancelled. A
cancel that did not happen is never reported as one, and the result it would
have discarded is kept.

## C6. What the merged interface actually shows

Verified in a browser against `http://localhost:8802` at `15cf6d76`, in a
profile with no owner cookie.

Two backtests were seeded into the isolated instance that differ **only** in
their evidence. Both reach the terminal `done` folder exactly as a real run
would; one keeps an intact fingerprint, the other's no longer describes the bars
it was computed from. Neither starts NinjaTrader; nothing is written outside the
disposable root.

The Работа table, read from the live DOM:

| Task | Progress column | Status |
| --- | --- | --- |
| Бэктест · AWRegisteredStrategy · MNQ 09-26 (damaged evidence) | *no bar* — «Ожидает вашей проверки» | Ожидает вашей проверки |
| Бэктест · AWRegisteredStrategy · MNQ 09-26 (intact evidence) | **100%** bar | Автоматическая проверка завершена |
| model task, cancelled | *no bar* — «Отменено» | Отменено |
| model task, failed | *no bar* — «Ошибка» | Ошибка |
| model task, accepted by the owner | **100%** bar | Проверка завершена |
| model task, rejected by the owner | *no bar* — «Результат отклонён» | Результат отклонён |
| 2 × model task awaiting review | *no bar* — «Ожидает вашей проверки» | Ожидает вашей проверки |

Same type, same source status, different outcome — decided by evidence, not by
being a backtest.

The overview at the same moment: **zero** `<progress>` elements on the whole
page; counters «В работе 0 · Очередь, выполнение и ожидание результата»,
«Результаты 7 · Получены, но не обязательно приняты», «Ждут проверки 3 · Ответ
есть, проверка не пройдена»; panel headings «ОЖИДАЮТ ПРОВЕРКИ» and «ТРЕБУЕТ
ВНИМАНИЯ» kept apart; no raw enum key rendered as a sentence.

Transitions driven through the API with `expected_revision` CAS, not by editing
storage: `a7f917b3 awaiting_review → completed` (owner accepted),
`fa34f6da awaiting_review → rejected` (owner rejected). Replaying the same
decision with the same idempotency key does not double-apply.

Four states stay distinct throughout, which was the point of the exercise:

| State | Where it comes from | What it does **not** mean |
| --- | --- | --- |
| execution finished | the task's own status | not verified |
| automatically verified | the executor's evidence | not accepted |
| awaiting manual review | evidence present, no human decision | not done |
| owner decision | `human_review: accepted / rejected` | not a quality claim (`quality_claim: False`) |

## C7. Regression and gates

Run at `15cf6d76` unless stated.

| Gate | Command | Result |
| --- | --- | --- |
| Full suite | `python -m pytest -q` | at `d30439e4`: **4521 passed, 110 skipped, 0 failed** (28m16s), tagged `checkpoint/agent-world-integration-regression` |
| Compile | `python -m compileall -q app tests` | pass |
| Aurora JS | `node --check` over `app/static/aurora/assets/**/*.js` | pass, 0 failures |
| External GPT context pack | `python tools/validate_external_gpt_context.py` | `EXTERNAL GPT CONTEXT OK`, with the standing warning that the pack's verification SHA differs from HEAD |
| Agent World PostgreSQL | `python -m pytest tests/test_agent_world_postgres.py` against a disposable TLS cluster | **69 passed**, migrations 1–23 applied, `migration_set_sha256 3e5a1ccf5c1e1fa75ef9ba66e8e9926ceebc3aac97adc7bea470c3f534ee38e3` |
| Mechanism flag suite | `python -m pytest tests/test_agent_world_mechanism_flags.py` | **73 passed** |

### Why 69 and not 68

They are the same suite counted in two situations, not two suites. The file has
not changed since `f9b94445`: 27 test functions expanding to 69 cases —
17 contract kinds, 10 repository behaviours, 6 payload identity bindings,
5 immutability cases, 4 missing-context RLS cases, 3 TLS environment-separation
cases, 3 cross-workspace RLS cases, 2 memory-grant cases and 20 singletons.

With no PostgreSQL DSN, **68 skip and 1 passes** — the one that asserts the
constructor performs no database IO, DDL or fallback, which needs no server.
That is the "68" in Part B's readiness table, and it is a skip count. With the
disposable cluster present, all **69 pass**. Nothing was added, removed or
re-parametrised to get there.

### The disposable PostgreSQL, reproducibly — `0386621d`

`deploy/testing/provision-disposable-agent-world-postgres.py` brings up a
throwaway TLS-enabled cluster from the official Windows zip: its own directory,
its own free loopback port, no Windows service, no elevation, no PATH, firewall
or existing-PostgreSQL change, no Docker or Podman. `--teardown` removes it.

Passwords are generated per run into `<workdir>/acceptance.env`, which is
git-ignored; nothing prints a secret and no DSN is committed. The administrative
role is used **only** to create and later drop the throwaway database. The suite
itself connects as `stratforge_app`, created `NOSUPERUSER NOCREATEDB
NOBYPASSRLS`, so workspace isolation is proven with runtime-like rights rather
than around them. No ALLOW gate, DSN restriction or database protection was
weakened to obtain the green run.

## C8. The 21 ported flag tests — `69875444`

All 21 residual cases were ported, expanding to **73** with parametrisation, and
carry a provenance header recording the sha256 of the file they came from. They
exposed three further enforcement gaps, all fixed in the same commit:

1. `flags.current_snapshot()` — a caller-supplied snapshot was authority, so a
   handle created before a revocation kept resolving against it. `delegation.gate`
   and `router_v2._gate` now re-read through the refreshable authority.
2. the local-owner bootstrap in `server.py` granted every capability by loop,
   including `ai_automation`; it is now excluded by name, and C5.1 proves the
   exclusion did not make legitimate automation impossible.
3. duplicate JSON keys in the mechanism configuration (see C3).

## C9. Open, deferred, and not done

Listed separately from the results above, on purpose.

**Owned by Codex, not written here**

* `mechanism_gateway` — `read`, `mutate`, `execute_watch`. Three call sites are
  wired and guarded; the module is missing. Until it lands, the `automation` and
  `router` domains answer 409 `mechanism_domain_unavailable`, and the
  `automation_watch` worker phase cannot run. Nothing enqueues that phase today.

**Not verified, and why**

* Local 8765 — untouched by instruction; nothing here has been applied to it.
* PostgreSQL as the *runtime* backend for Agent World — the suite passes against
  a disposable cluster, but no instance was ever started with
  `STRATFORGE_AGENT_WORLD_STORAGE=postgres`. SQLite remains the only backend any
  running build has used.
* Adapter rows on a real NinjaTrader or a real Desktop capture — the isolated
  instance has neither, so every adapter row in C6 is synthetic, written into
  the disposable root and kept out of real history and ratings.
* The external GPT context pack's own facts — the gate passes, but its
  verification SHA still points at an earlier HEAD. Re-pinning it is a
  governance action for the owner, and it should follow a merge, not precede it.
* Cross-user isolation beyond the workspace scope tests, and Court, were
  reviewed in Part A and not re-run against the merged build in this pass.

**Deliberately not done**

Merge to `main`; any change to PR #282/#283/#284 or their bases; any push to a
Codex branch; force push; switching or restarting Local 8765; Canary or
Production deployment; registering a Windows service; requesting elevation;
touching the global PATH, firewall or an existing PostgreSQL configuration;
installing Docker or Podman; using an owner, Canary or Production DSN,
credential or cookie; any real provider call, paid call or trading action.

## C10. What a reader should do next

1. Read C4 first: two of those defects were only visible on a running build, and
   one of them (C4.1) is a missing module that its author still has to write.
2. Take the branch as a whole or not at all — the merge resolved overlapping
   state logic, and cherry-picking a presentation fix without the projection it
   reads from will reintroduce the conflation this work removed.
3. Before Local 8765 is switched, decide who owns `mechanism_gateway` and
   whether the `automation`/`router` domains should be registered at all while
   it is absent. A registered domain that always answers 409 is honest but
   pointless; removing it from `DOMAINS` is the alternative and is a
   one-line change either way.

# Part D — the mechanism domains, the review boundary, and what is genuinely usable

Part C reported the merged build with the mechanism domains failing closed. That
was a fixed crash, not a working capability, and this part says so plainly and
then closes it. It also finishes the review boundary between a human accepting a
result and the evidence holding up, and settles the background-load check that
Part C left implicit.

## D1. What the 409 actually cost, and what now answers instead

**Confirmed again, read-only:** `mechanism_gateway` exists in **no branch and no
worktree**. Every local ref was searched (`git ls-tree` over all of `refs/heads`)
and every checkout under `StratForge-worktrees` was scanned; the newest Codex
branch is still `codex/agent-world-mechanisms` at `db85773f` with no file of that
name and nothing newer than the checkpoint in its working tree.

### What depended on it

| Entry | Depends on | Before | Now |
| --- | --- | --- | --- |
| `GET /api/ai-control-center/domains/automation` | `mechanism_gateway.read` | 500, then 409 | 200 — grants, schedules, capability state, flags |
| `GET /api/ai-control-center/domains/automation/{controller}` | `mechanism_gateway.read` | 500, then 409 | 200 — one grant |
| `POST /api/ai-control-center/domains/automation/{id}/{action}` | `mechanism_gateway.mutate` | 500, then 409 | `propose`, `enable`, `cancel`, `revoke` |
| `GET /api/ai-control-center/domains/router` | `mechanism_gateway.read` | 500, then 409 | 200 — policy, flags, task classes |
| `GET /api/ai-control-center/domains/router/{task}` | `mechanism_gateway.read` | 500, then 409 | 200 — the model that actually ran it, and the candidate evidence |
| `POST /api/ai-control-center/domains/router/{task}/preview` | `mechanism_gateway.mutate` | 500, then 409 | a real shadow decision |
| worker phase `automation_watch` | `mechanism_gateway.execute_watch` | would crash | runs the scheduler's own `scan_due` |

**User-facing elements that depended on them: none.** The Aurora page's `DOMAINS`
map contains neither domain, so no screen reached these routes. The cost was to
any client using the documented API, and to the `automation_watch` phase. That is
the honest scope of the 409 — it was never a broken screen.

### The adapter

`app/ai_control_center/mechanism_domains.py` is an adapter, not a mechanism. It
creates no second router, no second scheduler and no second authority: every
ranking, grant, device check, flag check and budget check is made by
`automation_authority`, `scheduler` or `router_v2`. A request it cannot forward
is refused by name — `mechanism_action_unsupported`,
`mechanism_payload_incomplete`, `mechanism_source_request_required` — never
guessed at, and a test asserts that a forwarded request's refusal code never
starts with `mechanism_`.

`domain_gateway._mechanism_gateway()` resolves `mechanism_gateway` first and this
adapter only while that module is absent, so the checkpoint's own module replaces
this file rather than being merged with it. With neither importable, both routes
still fail closed with `mechanism_domain_unavailable`.

**Temporarily unsupported, named rather than answered:** delegation has no action
on this domain, and the router's active mode is not applied from here — both are
listed in the `limitations` each read returns, so a caller sees what is absent
instead of inferring completeness. Those two remain a permanent 409 in the sense
that matters: they are not offered at all.

## D2. The user path, walked over the normal API

On the isolated instance, over HTTP only, with no process access. The run below
is the one against the committed code at `92436698`; an identical walk on the
working tree before the commit produced the same outcomes.

| Step | Result |
| --- | --- |
| `GET domains/automation`, `GET domains/router` | 200; task count **9 → 9**. Reading starts nothing. |
| `POST domains/routines/new/create` + `/accept` | accepted, `automation_enabled: false` |
| `POST domains/automation/{routine}/propose` | 200, returns `controller_id` and `approved: false`; task count **9 → 9** |
| `POST .../enable` **without** the capability | **403 `automation_entitlement_required`** |
| `POST /api/auth/users/{id}/permission` `{ai_automation: true}` | 200; the domain read then shows `ai_automation: true` |
| `POST .../enable` **with** it | 200 — schedule `ready`, `approved: true`, actions `["cancel", "revoke"]` |
| worker's own periodic scan | started the due occurrence unattended after 17s: `task_id` present, `coordination_job_status: succeeded`, panel **9 → 10 tasks**. No tick, no panel, no chat request. |
| the run itself | the provider call is refused by the budget authority — `model_private_budget_not_configured`, because this synthetic connection has no approved paid allowance, so **no provider call is made**. The task is visible in the panel with that state. |
| `POST .../cancel` | 200, schedule `cancelled` — including while an occurrence was still queued |
| `POST .../revoke` | 200; the grant reads `status: superseded`, `operational: false` |

The scheduler had no producer at all before this: `create` leaves a controller
and queues nothing, and `scan_due` was called only by tests, so an approved
schedule never started unless a person opened the panel and advanced it.
`domain_gateway.reconcile_schedules` adds that producer beside the
model-delivery recovery already in `local_worker.run_once` — same throttle, same
bounded keyset read, same rule that a scope is reused from a job the workspace
already produced rather than assembled. It decides nothing.

### The permission itself

The route that grants and revokes `ai_automation` already existed:
`POST /api/auth/users/{user_id}/permission`, owner-only, with
`{"capability": "ai_automation", "enabled": true | false | null}`. It is used in
the walk above and it works. The `automation` domain reports the capability state
and names that route rather than duplicating the authority. **No Aurora screen
exposes it yet** — that is the remaining user-facing gap, and it is a control on
an existing page, not a redesign.

### Router: the task, the choice, the explanation

`GET domains/router/{task}` returns the task's class, the model that **actually**
ran it, and `actual_choice: {decided_by: "request", routing_applied: false}` —
it never claims a routing decision was applied to a task that never had one —
beside each candidate's same-class evidence (one connection with 3 verified
observations, another with 2 and not all passing).

`POST .../preview` returns a real shadow decision: `decision_sha256`,
`dispatch_performed: false`, `permission_granted: false`, `quality_ranking:
false`, and a reason code per candidate. On this instance both candidates were
excluded as `routing_connection_not_verified`.

**This is not a comparison of real external models.** No external model was
called, no paid call was made, and the candidates were excluded before any
provider boundary. What is demonstrated is the link between a task, a decision
and its stated reasons — not model quality.

## D3. Human acceptance against evidence integrity

`tests/test_agent_world_manual_review.py` (7 cases) walks the boundary
separately, and one further case sits with the deviation machinery in
`test_agent_world_execution_v2.py`:

| Case | Result |
| --- | --- |
| A correct result | accepted; `display_status` becomes `completed` |
| A stale revision | `task_review_stale`, nothing written |
| A hash that does not match the shown result | `task_review_result_required`, nothing written |
| A result whose automatic check never happened | `not_required` — no acceptance is offered at all |
| A deviated result | `not_required`, no `review_result` action, and forcing a submit is refused; the deviation and its reason survive unchanged |
| The opposite decision afterwards | `task_review_already_recorded`; the same decision replayed is deduplicated, not a second record |

What acceptance may not do is pinned directly:

* **it cannot rewrite the hash it is bound to** — the stored proof carries the
  server's own fingerprint of the task, and the caller's value is only checked
  against it;
* **it cannot erase a deviation** — a deviated task is never offered for
  sign-off, and a forced submit leaves `status: deviated`, `human_accepted:
  false` and the same reason codes;
* **it cannot declare a damaged result technically verified** — the automatic
  `evaluation_id` and `application_evaluation_id` are unchanged by a decision.

The record keeps the two facts apart: the machine's verdict stays in its own
evaluation, and the human decision is a separate `EVALUATION` record with
`rubric_key: human_review`, `origin: explicit_human_review`,
`quality_claim: false`, the reviewer's uuid, the task revision and the source
hash. The panel shows them apart too — «Автоматическая проверка завершена» for a
machine verdict, «Проверка завершена» only after an owner accepted.

### A state with no exit, closed

An adapter row whose evidence failed verification is projected as awaiting
review — correctly, since being a backtest is not a result — but it carries no
review record, so no accept or reject action exists for it. It rendered with no
action, no link and no reason: the panel asked for a check and offered nothing to
do. It now states why acceptance is unavailable and links to the source report it
came from. Verified in the browser: the inspector shows

> Автоматическая проверка исходных файлов не пройдена, поэтому принять этот
> результат нельзя. Откройте исходный отчёт и при необходимости запустите новый
> расчёт.

with «Открыть исходный отчёт» pointing at the job's own report page. The verified
adapter row and the model row that has its own `review_result` action are not
annotated, and an off-site link is never surfaced.

## D4. Background load — verified, not deferred

The browser pane does mark a tab hidden, provided another tab is fronted first
and the target is navigated while in the background. With that, a **confirmed
hidden initial load**:

| Observation | Value |
| --- | --- |
| `document.visibilityState` throughout | `hidden` |
| `document.hidden` / `document.hasFocus()` | `true` / `false` |
| `document.readyState` | `complete` |
| Shell rendered | 13 Agent World panels, 14 rail links, 6733 characters |
| `/api/auth/status` requests for that load | **exactly 1** — no double shell start |
| Served `ui.js` | sha256 `ae6936740d69fbb2b119cc07cc19075c47c27c2149b47fb88d7b0c070cba28e4`, byte-identical to the repository file, containing the `shellStarted` latch and `setTimeout(startShell, 0)` |
| Build stamp on the served assets | `6802195` |

The tab was never fronted before or during the measurement. The mechanism was
**not** changed for this check — the fix and its latch test are unchanged from
`f589cba2`/the merge, and this is the browser confirmation Part B could not
obtain.

## D5. Where each mechanism actually stands

Four separate columns, because collapsing them is what this work exists to
prevent. "API подключён" means a normal HTTP entry exists and was exercised;
"пользовательский сценарий проверен" means it was walked end to end on the
isolated instance, not that a test passed.

| Mechanism | Реализован | API подключён | Пользовательский сценарий проверен | Остаётся blocker |
| --- | --- | --- | --- | --- |
| Task lifecycle projection | yes | yes | yes — browser, six states, one basis | — |
| Manual human review | yes | yes | yes — accept and reject driven over the API | — |
| Evidence integrity on acceptance | yes | yes | yes — refusals walked separately | — |
| Automation authority | yes | **yes (new)** — read + revoke | yes — grant → enable → revoke | no Aurora control for the capability itself |
| Scheduler | yes | **yes (new)** — propose/enable/cancel, and a producer for the scan | yes — the scan started it unattended | no successful scheduled provider result: this instance has no approved connection |
| Router V2 | yes | **yes (new)** — task view + shadow preview | partly — the task↔choice↔reason link, no active routed dispatch | an applied active route has never run; no real external comparison was made or claimed |
| Execution V2 / Deviation | yes | yes | partly — deviations by test and by damaged synthetic evidence | no live provider execution on this instance |
| Delegation | yes | **no** — no action on this domain, named as a limitation | no | needs a domain surface; not added here |
| PostgreSQL / RLS repository | yes | selection exists | no — 69 tests against a disposable cluster, but no instance ever ran on it | never run with `STRATFORGE_AGENT_WORLD_STORAGE=postgres` |
| `mechanism_gateway` | **no — exists nowhere** | adapter stands in | n/a | **yes — owned by GPT/Codex** |
| Hidden-tab boot | yes | n/a | yes — confirmed hidden initial load | — |

### Programme items this set does not close

Nothing here touches the open programme-level items, and they stay open: separate
ordinary-user registration and key, multi-user sharing and revocation, permanent
Social publication, and owner acceptance of the whole programme. `OWNER
ACCEPTANCE READY` remains **NO**, and Local 8765 remains untouched, not switched
and not restarted.

## D6. Gates, at the SHA each was run on

Results are not carried forward across commits. Two full runs were made, one per
code state; the docs commit that records them changes no executable code,
configuration, migration or test.

| SHA | What it is | Full suite | Release runner | compileall | Aurora JS | Context pack |
| --- | --- | --- | --- | --- | --- | --- |
| `d30439e439ceaca3a4748285c9a52331cb91e75c` | integration checkpoint, tagged `checkpoint/agent-world-integration-regression` | **4521 passed, 110 skipped, 0 failed** (28m16s) | — | pass | pass | OK |
| `92436698c279fa41530b96fc9ad5509cc56596ad` | mechanism domains connected, review boundary closed | **4537 passed, 110 skipped, 0 failed** (28m44s) | **13/13 suites** | pass | pass, 0 failures | `EXTERNAL GPT CONTEXT OK` |

The delta is exactly the 16 cases this pass added: 6 in
`test_agent_world_mechanism_domains`, 7 in `test_agent_world_manual_review`, 1 in
`test_agent_world_execution_v2`, 2 in `test_agent_world_status_presentation`.
Nothing else changed count.

The 110 skips are identical in both runs and are all PostgreSQL-gated: 68 in the
Agent World suite (its 69th case needs no server), 12 + 12 + 9 + 8 in the four
baseline suites, and 1 in `test_platform_secrets`. Against a disposable TLS
cluster the Agent World suite is **69 passed** — see C7.

The context pack still carries its standing warning that its verification SHA
differs from HEAD. Re-pinning it is a governance action for the owner and should
follow a merge, not precede one.

### Commit pairing

| Kind | Commit | Contents |
| --- | --- | --- |
| Code + tests | `92436698c279fa41530b96fc9ad5509cc56596ad` | `mechanism_domains`, the module preference in `domain_gateway`, `reconcile_schedules`, the worker scan hook, the adapter-row exit, the inspector rendering, and 16 tests |
| Docs | the commit that adds this section | Part D, the status-document section, and the changelog record. No executable change. |

## D7. What a reader should do next

Take the branch whole. The presentation, the projection and the adapter read
each other, and lifting one fix without the computation it reads from
reintroduces the conflation this work removed.

Before Local 8765 is switched, three decisions are the owner's, not mine:
whether `mechanism_gateway` is still Codex's to write now that an adapter
answers those routes; whether delegation should gain a domain surface or stay
out of the API; and whether the `ai_automation` capability deserves a control in
the panel rather than only an owner route. None of them blocks the branch; all
three change what a user can reach.
