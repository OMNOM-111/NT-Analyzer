# Persona identity, aliases and scoped SF Chat selection

## Change record

- Date: 2026-09-08.
- Change title: Persistent Persona identity and explicit assistant selection.
- Source baseline: `376b400dc3c8ab3a008f1e45800d401dd02c4b6f`.
- Branch: `codex/agent-world-unified-acceptance`.
- Implementation identity: AI-assisted change; no inferred model attribution.
- Request: continue Agent World owner acceptance, preserving existing profiles,
  avatars, voice, history, Local data and the already working execution paths.
- Source commit / PR of this slice: recorded by the root integrator at the next
  checkpoint; this bounded worker did not stage, commit, push, merge or deploy.
- Release impact: additive Local/Development contract, no version assignment,
  schema migration, permissions grant, new queue or live flag activation.

## Implemented scope

Persona profiles now accept up to five optional aliases and an optional strict
`main_assistant` boolean. Their identity remains the existing owned Persona UUID,
not the model name or legacy avatar ID. Old-client updates preserve omitted
aliases, main choice, avatar, voice and style. Previous revisions are retained.

Alias/name comparisons use Unicode normalization without renaming persisted
profiles. Alias conflicts and the single main-assistant slot are checked inside
the existing serialized repository transaction (`BEGIN IMMEDIATE` for SQLite;
existing advisory transaction lock for PostgreSQL). Active and suspended
profiles reserve their identity; retirement releases it. To change the main
assistant the user explicitly clears the former selection, then saves the new
one. No hidden multi-record update is performed.

Duplicate display names alone remain legal for compatibility. Name-addressing
then fails closed as ambiguous; the UUID selector remains usable. A name,
alias, display avatar or main choice never grants a role or capability.

SF Chat reuses its existing composer container for a Persona selector. It loads
the authenticated, paginated Persona catalog, does not persist a second
preference store, and is absent from human DMs. Explicit unavailable, suspended
or revoked selections block sending before clearing the user's input. Original
message text is retained; a canonical `persona_id` travels separately through
the existing message and stream transports. No automatic dispatch occurs on
selection. Display fallback is the selected Persona's asset or neutral initials,
never a different legacy agent's face.

Named addressing and the current main assistant resolve through the same owned
records. The frozen selected revision is rechecked before the existing
application task constructor; its `EntityRef` is passed into the existing model
task path for current binding/revision checks at enqueue and transmission.
Unknown explicit `@alias`, conflicting UUID/name, wrong role, multiple bound
connections, missing binding or inactive Persona do not fall back to an owner
connection or the legacy assistant. Built-in control commands retain their
existing route.

The root-owned bounded `assistant_response` contract is offered only for a
single task, labelled “Ответ помощника · ручная проверка”. This UI slice does not
add it to experiment or autonomous-schedule forms. SF Chat, task details and
evaluation labels distinguish a transport receipt from semantic correctness;
this class has no professional score or routing/rating effect, even if an old or
malformed supplied score is 100. Historical nested `verification.scope` remains
readable without turning it into current human acceptance.

Model cards/details show the server's explicit `chat_completions_v1` text-only
protocol and limitations read-only. They do not claim remote tools, remote tasks,
MCP, A2A or artifact execution, and contain no editable capability grant.

The shared drawer now links its accessible name to the current visible heading.
Reusing a model-connect drawer for Developer Preview or Security no longer
retains the previous panel's `aria-label`. No page composition was changed.

## Verification evidence

All data below is isolated fixture evidence, not real model-quality evidence or
owner visual acceptance. No provider/TTS call, browser, NinjaTrader, live Local
port or owner secret was used by this worker.

- Persona identity and actual disposable chat/queue integration:
  `test_agent_world_persona_identity.py` +
  `test_agent_world_persona_identity_chat.py`: **53 PASS** (10.38 s).
  Covers UUID/alias/main dispatch, exact persisted user text and assistant UUID,
  idempotent replay, forbidden-role isolation, stale revision and rename/suspend/
  disconnect races with no provider execution or fallback. Failed requests are
  retained, not deleted.
- Executable shipped UI/transport handlers plus result presentation and existing
  SF Chat dialogs: `test_agent_world_persona_identity_ui.py` +
  `test_agent_world_result_presentation.py` + `test_sf_chat_dialogs.py`:
  **121 PASS** (11.76 s). Includes revoked/incomplete catalog, selection, real
  stream payload construction, human DM isolation, escaped labels, neutral avatar
  fallback, transport-only notes and reused drawer accessible-name linkage.
- Persona UI + Aurora contracts after removing accidental reuse of the legacy
  model-menu CSS class: **96 PASS** (6.60 s).
- Earlier broader affected regression: **781 PASS / 1 FAIL** (142.62 s).
  The single failure was the preserved “no legacy model menu” contract. The
  selector was changed to existing generic button styling; the complete affected
  Aurora suite then passed as recorded above. A new full immutable-checkpoint
  regression is the root integrator's next gate; the earlier run is not silently
  relabelled all-PASS.
- New `test_agent_world_persona_identity_postgres.py`: **7 SKIPPED** (0.52 s),
  because separate disposable PostgreSQL opt-in was absent for this invocation.
  It reuses only the approved loopback `aw_disposable_*`, non-BYPASSRLS fixture.
  The cases cover concurrent main/alias allocation, private user/workspace scope,
  explicit main replacement, ambiguous names, inactive/foreign/nonhuman denial,
  and profile/voice/avatar revision persistence across repository restart.
  These cases are **not** covered by previously reported PostgreSQL PASS results;
  actual fresh execution is pending the next source-frozen integration gate.
- `py_compile` for the five changed Python application modules and four new
  Python test files: **PASS**.
- `node --check` for shared `ui.js`, `api.js`, AI Center page and the new isolated
  handler harness: **PASS**.
- Repository-root `git diff --check`: **PASS** before handoff.

## Boundaries and handoff

Backend Chief/server ingress, model worker and the new bounded response evaluator
are owned by the root integrator. The optional Persona API fields and selected
`EntityRef` contract are coordinated with those changes. Current system status,
owner acceptance guide and External GPT Context Pack (`02` and `11`) must be
updated by the integrator in the same final checkpoint; this record does not
replace them.

The protected Local `8765`, existing results and owner data were untouched. No
flag was enabled, no registration completed, no user key copied, no publication
approved, and no merge/deploy performed. Visual/layout acceptance, actual new
PostgreSQL acceptance and credentialed model/voice acceptance remain distinct
from this fixture PASS. The earlier checkpoint is preserved; reverting this
slice requires no data migration or deletion.

Status: **bounded implementation ready for integration verification**;
**Git closeout and whole-program stage closure are not asserted here**.
