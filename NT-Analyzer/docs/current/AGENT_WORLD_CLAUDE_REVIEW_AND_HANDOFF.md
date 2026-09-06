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
| Full regression | see below |

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
