# Persona speech on saved SF Chat replies

Date: 2026-09-08. AI-assisted change. Development only; no merge, release or deployment.

## Change and source

This bounded continuation starts from checkpoint `a03ec82b686a9f6f05c056fe5a500ecbdb3babac`
on `codex/agent-world-unified-acceptance`. The integrating commit/PR is recorded by
the main Agent World closeout; this working note does not invent a final SHA.

SF Chat now resolves the persisted Persona UUID independently of the executor's
model/provider label. It keeps saved message names and existing face assets;
unavailable or deleted Persona data produces a neutral static fallback, not an
invented Vitek identity. Existing Persona voice settings are reused, not copied
from an owner model/credential. Historical staff messages without a Persona UUID
offer an explicitly local device preset, not an owner provider connection.

Speech starts only from a message's **Озвучить** button. Hover no longer starts
speech. **Остановить**, conversation change, auth loss, hash/page navigation,
hidden page and changed message rendering stop playback. The existing PersonaAudio
module is reused by both the description preview and SF Chat; starting one stops
the other. Prepared or failed audio does not animate a speaking face or claim
successful playback. A shipped WEBM is an activity loop, not phoneme/viseme lip-sync.
Missing audio, access or a matching local browser voice leaves text and a static
avatar. Browser fallback excludes remote/unidentified speech voices.

The existing Persona endpoint accepts either its prior sample `{text}` payload
or `{conversation_id, message_id}`, retaining the same `expected_revision` and
`idempotency_key` envelope and existing auth/device/CSRF/authority checks. In the
message variant the server reads one exact scoped saved assistant message and
requires its `agent_id` to match the owned Persona UUID. It never accepts a caller
replacement text, model ID, scope or credential. Current Persona revision,
admission and a source-text fingerprint are checked again before synthesis.
The read-only Chief lookup does not migrate, acknowledge, rate or rewrite history.
The integrating Chief UUID-first identity fix also preserves a UUID when its
display name happens to equal a legacy name such as «Виктор» or «Марина».

A related review-boundary correction removes legacy rating, fulfillment and
comment-edit controls from all Agent World messages (not only model-response
messages). Old marks/comments remain readable as historical SF Chat feedback,
explicitly not task acceptance or professional quality. Only the canonical task
review controls can record a new Agent World decision; ordinary legacy/human
chat behavior is unchanged.

## Affected files and caches

- `app/ai_control_center/persona_voice.py` and the narrow `domain_gateway.speak_persona` dispatch.
- `app/static/aurora/assets/ui.js` and existing `persona-audio.js`; no new design/layout or speech engine.
- Tests: `test_agent_world_persona_chat.py`, `persona_chat_ui_harness.cjs`,
  `test_agent_world_persona_chat_ui.py`; exact cache assertions in existing Aurora/SF Chat suites.
- A mechanical cache-only update in 15 Aurora HTML consumers: `ai-agents`,
  `ai-command-center`, `ai-lab`, `backtesting`, `community`, `desktop`, `documents`,
  `index`, `mode-entry`, `news`, `performance`, `practice-trading`, `strategies`,
  `topstep`, `trading`. Shared `api.js`/`ui.js` URLs use
  `20260908-agent-world-unified2` (29 URLs); the AI Center PersonaAudio URL and
  shared lazy loader use `20260908-agent-world-persona-chat1`.

## Verification and honest limits

Disposable SQLite and actual disposable scoped JSONL checks cover UUID/name
collisions, two executor labels on one Persona, retained historic name/content,
current revision, foreign user/workspace, private/shared-default conversations,
permission revocation, suspension, changed source fingerprint, source-message
binding, HTTP envelope and CSRF. The shipped JavaScript handlers run against a
minimal DOM/device port to verify explicit click, transport metadata, device-only
fallback, denied/mismatched receipts, late module/transport cancellation, mutual
playback exclusion and stop/navigation lifecycles.

These are automated contracts, not audible audio, real browser rendering,
real-model quality or provider-key acceptance. No external model/TTS calls,
owner credentials, Local `8765` runtime/data, queues or trading state are changed
by this work. Preview's domain facade remains sample-speech-only until a synthetic
saved reply is bound to an actual Preview Persona and authenticated numeric user
scope; it is not marked as a verified saved-message voice flow.

The broader canonical gaps are not relabelled as finished by this speech slice:
main/personal assistant selection and arbitrary Persona address-by-name require
their own workflow; an `external_agent` connection currently means a bounded
text-compatible HTTPS endpoint, not MCP/A2A, remote tools or a remote task lifecycle.
True viseme/phoneme and full emotional-avatar rendering remain unavailable with
honest static/activity-loop fallbacks. Design acceptance remains owner-pending.

Final focused verification on the completed speech/UI source:

- The combined eight Persona, SF Chat and Aurora suites: **413 passed, 0 skipped**
  in 60.22 seconds. The new saved-message backend and actual-handler JavaScript
  contracts contribute 31 cases each; the remaining cases preserve existing
  Persona voice/audio, UI and shared-dialog behavior.
- The separately rerun `test_agent_world_result_presentation.py`: **27 passed,
  0 skipped** in 3.17 seconds. Its render-only Node port now accepts inert
  lifecycle listener registration and explicitly rejects speech execution. No
  report-link, PNG provenance, escaping or history-immutability assertions were
  removed or weakened. Together these are **440 distinct automated PASS**.
- `node --check` passed for `ui.js`, `persona-audio.js`, `api.js` and the new
  `persona_chat_ui_harness.cjs`.
- Python compilation passed for `persona_voice.py`, `domain_gateway.py` and the
  two new Python test modules; `git diff --check` passed.
- A full-file comparison after normalizing only the approved cache tokens and
  line endings matched HEAD for **15/15** shipped HTML consumers. The 30 script
  URL changes are mechanical; there is no markup or design delta in those files.

These results are a scoped implementation checkpoint, not the whole-program
regression, Git/CI closeout, audible speech acceptance or release acceptance.
Application source is frozen for the main agent's immutable checkpoint and
independent browser/runtime validation. No commit, stage, merge or deployment
was performed by this subtask.
