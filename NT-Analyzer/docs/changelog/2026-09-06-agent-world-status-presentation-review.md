# Agent World — independent review: status presentation, identity and focus

- Release title: Agent World — separate the states one status number conflated
- Change summary: an independent review pass over the owner-reported screen
  findings. Execution, waiting for a review, waiting for an owner decision and
  finishing become four separately counted phases shared by the server and the
  page, so a metric can no longer contradict the panel beside it. Progress is
  reported only where it is measured. Persona availability and occupancy become
  two facts. Warnings gain a reason, a time, a next action and a route to the
  ones the list truncates. Every score names the class of check it was measured
  on. System components report implementation, enablement, working mode and
  current availability separately. Raw enum keys, digests and JSON payloads move
  out of the sentences the owner reads and into details blocks beside them —
  relocated, never removed. Escape returns keyboard focus to the control that
  opened the Task Inspector. A Persona gains an explicit face; a connection
  states the Persona it currently points at instead of implying a permanent
  binding through its label.
- Canonical status: `IN DEVELOPMENT` unchanged. This is a review pass, not
  program acceptance and not owner visual acceptance.
- Branch: `claude/agent-world-review-and-hardening`, local and unpushed. No PR
  opened; PR #282 and its base were not touched.
- Source baseline: `45ab4361d5ab9b8422ec049c0c689953d548a318`. Commits applied
  in order: `72f7fc88ae13476ef4c3052d66ddf3af518a3dae`,
  `42b60a2b156b2dc11ab567ad6f9fc60f33c14e0e`,
  `c865db2248a12f6927d077dc31efe8b05c02426e`.
- Version: `0.10.0-beta.96` unchanged. No merge, deploy, signing, SQL migration,
  new API route, flag change, owner-key copying, budget increase or trading
  order. Migrations remain 1–22. The owner Local on 8765 was not restarted and
  still serves `2b6d0112bef88c5bfb73970de64ec5518443e56b`.

## Why

The owner reported eight areas from screenshots of the integrated Local review.
All eight were reproduced against the running Local before anything changed:
`active_tasks:0` beneath a panel headed «Сейчас в работе» holding two `review`
tasks; `attention:4` rendering three cards with no way to reach the fourth;
`progress_pct:100` on all twenty tasks including the failures; one green
«Активен» standing for enabled, free and executing across all three Personas; a
bare «100%» measured over three `json_arithmetic` inputs; and `court_vote`,
`chart_spec`, `provider_receipt` printed as user-facing text.

## Affected subsystems

`app/ai_control_center/presentation.py` (new shared vocabulary),
`domain_gateway.py`, `domain_service.py`, `model_service.py`, `live_gateway.py`,
`app/static/aurora/assets/pages/ai-command-center.js` and its stylesheet.
`ui.js`, `server.py` and `permissions.py` were not modified. Machine identifiers
(`status`, `stage`, `task_class`, `rubric_key`) keep their values and remain
available for technical detail; the four existing tests that assert them pass
unchanged.

## User-visible changes

The Overview rollup now reads Выполняется / Ожидают проверки / Завершено /
Команда / Требуют внимания, and the work panel is headed «Сейчас в работе»,
«Ожидают вашего решения» or «Последняя работа» from the same phase split. A
task that has not finished shows its phase instead of a full progress bar.
Warning cards state why the item is waiting and what unblocks it, and a
truncated list links into the Работа tab pre-filtered to everything still
needing the owner. Agents show two chips. Scores show the class of check, the
number of observations, the confidence and the origin. The System drawer lists
Execution Engine V2, Router and autonomous scheduling explicitly as not
implemented so a working legacy worker cannot imply they are ready — no flag
was enabled to produce a green card. A Persona can be given one of the six
faces that ship as assets, chosen explicitly rather than inferred from its
name.

## Verification

New: `tests/test_agent_world_status_presentation.py` (38),
`tests/test_agent_world_inspector_focus.py` (3),
`tests/test_agent_world_storage_scope.py` (15). Every presentation and focus
regression was confirmed to fail on the pre-fix source and pass after. 482
passed across the six Agent World suites touched. `node --check` passes.

One existing test was corrected rather than the code:
`test_canonical_ready_tasks_remain_visible_as_queued_in_active_and_waiting_views`
pinned the literal conflated status list that is the first reported defect; its
intent is preserved through the phase mapping. Two persona payload tests were
widened by the new `avatar_key`, with an added assertion that credentials,
scope, model and authority still cannot enter that payload.

Full regression on the final `6b111590`: **4296 passed, 42 skipped, 0 failed**,
1007.59 s. The 42 are the 41 unconfigured PostgreSQL cases plus one POSIX
permission case; earlier records say 44 because two bash-gated shell cases
skipped there and ran and passed here. `python tools/pre_release_check.py`
PASS with a 544-file bundle, root-level CSP/secrets/Markdown scan OK, and
`python tools/validate_external_gpt_context.py` OK.

Branch pushed; draft PR #283 opened against `codex/agent-world-owner-preview`
for review only, with #282's base untouched. Exact-SHA CI run 34067167959 is
3/3 PASS on `84115efc`; commits after it are **not** covered and need a fresh
run before integration.

## Release impact

None. Nothing is published, promoted or deployed by this change. Full findings,
what was deliberately not changed, and the exact next operation are in
`NT-Analyzer/docs/current/AGENT_WORLD_CLAUDE_REVIEW_AND_HANDOFF.md`, which also
settles what the 41 PostgreSQL cases cover and records that Agent World has no
PostgreSQL schema or adapter for them to exercise. That path is named rather
than linked: `docs/current` is not one of the shipped trees, so a relative link
from a changelog resolves in a checkout and breaks inside the release bundle —
the beta.81 signer failure `tests/test_pre_release_check.py` exists to catch.
