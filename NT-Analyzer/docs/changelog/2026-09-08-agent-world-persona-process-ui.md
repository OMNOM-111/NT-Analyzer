# Agent World — Persona audio and process suggestions on the existing page

- Release title: Persona presentation controls and reviewed process suggestions.
- Change summary: connect the prepared PersonaAudio and Process Intelligence
  modules to existing Agent World drawers, without a new page or composition
  redesign. Explicit playback and suggestion saving remain separate from task
  execution, result acceptance, professional quality and autonomous scheduling.
- Canonical status: **IN DEVELOPMENT** pending integrated browser/audio acceptance.
  This is a bounded UI integration, not closure or visual acceptance of Agent World.
- Branch: `codex/agent-world-unified-acceptance`; integration checkpoint / rollback
  source `13573bf7` (earlier accepted base `1409553a`). The root integrator records
  the final commit and PR. No stage, commit, merge, deploy or version change was
  performed by this UI subtask.
- Release impact: two existing static files and a new test file. No new store,
  route, credential, permissions, background job or scheduler. Local8765 and its
  data/results remain untouched by this subtask.

## Persona and preserved identity

The existing Persona form now exposes voice profile, browser/existing-TTS mode,
speed, language, animation preference, expression preference and lip-sync mode.
The server catalog supplies profile labels; only known shipped profiles are
accepted. Browser speech is the default. Older narrow clients can omit the new
fields, and the current edit form loads persisted values without resetting the
avatar or voice settings. Model credentials and authority are not form fields.

Persona details provide an explicit **Прочитать описание** control for the shown
name/description and a stop button. Audio uses the existing same-origin transport
with Persona ID, exact revision and an idempotency key. The request does not send
workspace, owner status, keys, arbitrary voice mode or authority. A stale/denied
request does not bypass the server decision by speaking locally.

The UI distinguishes the requested voice profile, actual device voice and actual
server audio. Persisted settings are not labelled verified audio. Static/text
fallback, missing installed voices and absent phoneme/viseme timing are explicit.
The shipped talking clip is not true lip-sync. Independent emotional expressions
and phoneme-synchronised animation are not claimed as implemented by this change.

Existing face assets/crop helpers are reused. Persona detail faces do not acquire
legacy hover playback that would override a saved static preference. Audio and
face activity stop on explicit stop, drawer replacement/close, Escape, tab or
page navigation, visibility loss and page leave. Late audio responses and late
face-media events cannot restart a stopped Persona. Playback does not write a
task, result review, model evaluation or history record.

## Process Intelligence in routines/calendar

The existing routines and calendar drawers show server-supplied candidates with
origin, class of real application work, sample size, pending human reviews,
observation window and low-confidence estimated interval. Calendar suggestions
display local time. Structured provenance and fingerprints remain available in
details rather than long primary payloads. Excluded observations and cooldown
are not shown as task failures, and error history is not deleted.

Choosing a candidate opens a review form. **Сохранить предложение** sends only
the source snapshot hash through the existing generic mutation envelope. A
repeat after a failed response uses the same idempotency key and snapshot.
Saving never calls accept, enable, grant or review-result. The saved record's
normal accept/dismiss actions remain separate. Read-only candidate projection
does not offer mutation or mislabel valid evidence as corrupt. Incomplete scan,
unsupported snapshot or changed source is not treated as successful completion.

## Shared hooks and verification scope

The root integrator owns the API/server/gateway and shared `ui.js` hooks:

- Persona list `presentation_catalog`, Persona item `presentation`;
- `API.http.aiControlCenterPersonaSpeak(id, envelope)` returning audio Blob or
  browser-fallback JSON with HTTP error status retained;
- existing `UI.agentFacePlay/Pause` and explicit `UI.agentSpeakStop`;
- routines/calendar list `process_intelligence` and candidate action filtering
  for the currently authenticated writer/read-only context;
- `propose` with candidate ID and `payload.source_sha256`, followed by a separate
  guarded accept on the saved Routine/Calendar record.

The added suite reuses real page click/submit handlers and the actual PersonaAudio
controller with isolated in-memory API data and fake device callbacks. It covers
65 cases: additive fields, preserved edit values, narrow envelopes, malformed
input, source snapshots, readonly/disabled proposals, retry identity, independent
acceptance, explicit playback, denial handling, stop/finish and late responses.
Fake voice callbacks are not audible output or proof of provider availability.

Final combined regression: **260 PASS, 0 skipped** in 30.03 seconds —
65 new Persona/PI contracts, 173 existing page contracts and 22 PersonaAudio
controller scenarios. Python compilation of the new test, `node --check` for
the page script and repository-root `git diff --check` all passed. The page's
API/UI cache identifiers were advanced for the new shared hooks; the application
version was not changed.
No browser, real TTS provider, paid request, Local data write or publication was
performed here. Browser/audio/device acceptance and the complete program's
regression remain the root integrator's work. Current status and External GPT
Context Pack 02/11 require the same integrated checkpoint update; those shared
documents are root-owned. Coordinator projection is not rewritten by this slice.
