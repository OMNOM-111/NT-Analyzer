# Agent World — stable Persona voice and honest visual fallback

- Release title: Persona presentation identity and local voice fallback.
- Change summary: preserve existing Persona face/style/role settings on partial
  edits; store voice preferences separately from Model/Provider Account; add an
  opt-in audio controller over the existing TTS and shipped face clips.
- Canonical status: **IN DEVELOPMENT**, pending shared UI/API integration and
  audible/visual acceptance. This record does not close the entire Persona layer.
- Source / rollback point: `1409553a` on `codex/agent-world-unified-acceptance`.
  Root records the final integrated commit/PR; this subtask does not stage or
  commit shared work. beta.96 is unchanged.
- Release impact: additive Persona JSON profile fields and an additional static
  module; no database migration, new credentials store, queue, permissions system,
  owner-data mutation, Local8765 restart, external TTS call, merge or deployment.

## User-visible behavior and preserved identity

Persona supports a shipped voice profile, browser/existing-owner-TTS preference,
speed, language, static/automatic face behavior and expression/lip-sync preferences.
Defaults are read-only projections for old records, not automatic migrations.
An older client that submits only a new name no longer clears the existing
avatar, style, description, explicit application role or voice configuration.
Explicit empty values still clear supported fields. Immutable revisions remain.
Model changes do not change the Persona ID, displayed name, face, voice settings
or historical task snapshots. Persona, role, connection and model remain distinct.

The static catalog reuses eight existing `agent_tts` staff profiles. Six existing
`speaking.webm` assets are reused without generating or replacing faces. A
missing/unknown face is not guessed from a person's name. A speaking clip is a
generic activity animation, **not phoneme/viseme lip-sync**. The API and controller
explicitly report lip-sync unavailable and do not claim tested audio from a
stored preference. True lip-sync and expressive asset timelines remain a gap.

Ordinary-user speech uses the existing `agent_tts.synthesize` browser override
without loading custom owner voice files, provider keys or a global audio cache.
The browser controller accepts only installed local voices for the requested
language. It reports the actual selected device voice, not the requested
provider voice as though identical. Missing voice/device support or failed
playback leaves the static face and text. Reduced-motion/static preferences
prevent the talking loop. No page-load/hover/autonomous speech is introduced.

Existing owner server TTS is optional and requires the persisted explicit mode,
authenticated owner-runtime scope and a separate fresh authorization callback.
Owner booleans or a request-body override alone cannot select it. Scope, Persona
revision/activity and owner authorization are rechecked before synthesis. Server
denial or stale revision does not silently fall back to unauthorized local speech.

## Integration contract for the root-owned shared files

- `persona_voice.catalog()` is safe static data; it does not discover keys.
- `persona_voice.speak(service, context=..., admit=..., persona_id=..., text=...,
  scope=..., expected_revision=..., authorize_server_tts=...)` returns the existing
  `_respond_tts` audio/browser-fallback contract. Context/scope and the owner
  callback must come from existing server admission, not a request payload.
- Persona DTOs contain `presentation` and `voice_label`; old ID/title/history
  fields retain their meaning. The new profile fields are additive.
- Load `assets/persona-audio.js`; create `PersonaAudio.create` with the existing
  scoped TTS transport, face play/pause, legacy-audio stop, reduced-motion and
  state-label hooks. Call `play({persona,text,face,userInitiated:true})` only from
  an explicit control. Stop/dispose on close, navigation or Persona replacement.
- Add voice controls to the existing Persona form/details and SF Chat result
  controls without a new page or large layout redesign. Integration hooks remain
  root-owned; this module does not modify existing UI behavior on its own.

## Verification and limits

Isolated SQLite records and Node fake-device lifecycle tests cover stable IDs,
partial-edit compatibility, immutable history across model switches, six actual
shipped asset paths, invalid fields, foreign scope, stale/revoked authority,
existing-owner adapter guards, ordinary-user no-key fallback, local-voice
selection, asynchronous voice discovery, playback cancellation, static/reduced
motion, object-URL cleanup, late errors and stale request isolation.

The shared regression run before the final concurrent-revision guard passed
**234 tests**: Persona voice/audio, domain service, Persona roles and models.
The final scoped run, including the concurrent Persona revision guard, passed
**57 tests** (35 Python + 22 Node lifecycle scenarios). `node --check`, Python
compilation of the changed modules/tests and root `git diff --check` passed.
All TTS/device/model transport fixtures in this record are test evidence,
not real audible output, provider availability, professional model quality or
owner visual acceptance. No paid/provider TTS or audible browser QA was run here.
The full integrated regression, runtime/browser route wiring, Context Pack 02/11,
final SHA and program-wide acceptance remain the root integrator's closeout.
