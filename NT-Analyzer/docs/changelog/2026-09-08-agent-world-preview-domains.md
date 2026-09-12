# Agent World — isolated Preview domains and explicit operator dataset

- Release title: Manual Agent World domains inside Owner Preview.
- Change summary: replace the blanket disabled domain API with the existing
  DomainService/SQLite ledger for synthetic Persona, memory, projects and
  routine/calendar proposals. Add a separate synthetic operator scenario and
  one explicit, repeatable six-record fixture action. Never upgrade the ordinary
  Preview user, import owner data/keys or activate external execution.
- Canonical status: **IN DEVELOPMENT** — bounded API implementation and isolated
  automated checks complete; integrated browser review belongs to the root
  acceptance pass. This does not close Agent World or its visual acceptance.
- Source / rollback checkpoint: `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`, branch
  `codex/agent-world-unified-acceptance`. Final commit and PR identity are recorded
  by the root integrator. This subtask did not stage, commit, merge or deploy.
- Release impact: Preview composition/API, a new Preview domain wrapper and a
  narrowly additive scenario in the existing Preview sandbox. No schema migration,
  new permission engine, queue, provider or version change. Protected Local8765,
  owner state and real results were not changed by this subtask.

## Actual supported behavior

`GET /api/ai-control-center/domains/{personas|memory|projects|routines|calendar}`
and existing entity-detail/mutation envelopes use the same DomainService and
repository as the product, but only `isolated_root()/agent-world.sqlite3`.
The wrapper grants no rights: current synthetic session, confirmed device,
Development Preview, exact sandbox root, owner-issued control cookie, existing
workspace membership, professional/ai_lab capability, trial and existing budget
checks remain mandatory. Every service checkpoint refreshes admission; revoked
sessions, changed scope/root/control and disabled flags invalidate cached service
objects. Client payloads cannot supply owner/workspace/permission authority.

Supported actions are the existing owned Persona create/update/activate/suspend/
archive, memory create/update/explicit review/revoke/expiry and explicit workspace
sharing, project create/update/version/archive, proposal create/dismiss. Stale
revisions and changed same-key payloads retain the existing CAS/idempotency rules.
Sharing synthetic memory is restricted to the current synthetic workspace; the
existing content-grant reader checks the published record, source, TTL and
revocation. Private artifacts are not globally exposed. History is not deleted.

Persona fields and shipped face assets survive partial rename updates. The
catalog advertises browser voice only. Explicit `personas/{id}/speak` returns the
existing browser-fallback contract, exact Persona revision and synthetic origin.
An old saved `existing_tts` preference is preserved, but never authorizes server
TTS in Preview. Owner voice profiles/provider resolution are not read. This is
not audible-browser or paid-provider acceptance; no audio file is fabricated.

All domain responses clearly identify synthetic provenance and explicitly deny
professional model-quality evidence. Manual memory review does not become an
agent evaluation. Persona fixture rows do not become completed task counts.

## Separate operator and fixture action

The existing scenario catalog adds `agent_world_operator`. It registers a new
non-owner synthetic identity and writes a private `is_preview_operator` marker
only to that new identity. The marker is not accepted from the public auth
payload. The ordinary user is not upgraded; `is_owner` remains false. The helper
checks the current scenario, exact synthetic user/session, active device and
live persisted marker. Existing New User registration and its manual decisions
are unchanged; Reset keeps the existing isolated lifecycle.

`GET domains/system` exposes `preview_dataset` and
`capabilities.can_seed_preview_dataset`. Only the current operator receives the
`seed_preview` action. The owner must explicitly invoke:

`POST domains/system/agent-world-domains-v1/seed_preview`

using `{payload:{}, expected_revision:0, idempotency_key:...}`. The fixed recipe
creates two draft Personas, one draft private Memory, one draft Project and two
proposed Routine/Calendar records. Calendar dates are labelled historical
examples, not a real schedule. An immutable synthetic manifest is returned by
artifact URL. Fixed per-user creation keys resume a partial failed seed without
duplication and never overwrite later manual edits. Current revisions are
returned on replay. GET does not seed records or accept any review.

The root frontend consumes the catalog, adds the operator banner label and
System action. The API returns `created_count`, `replayed_count`, `items` with
domain and current DTO, plus `manifest_artifact_url`. No hidden seed-on-open is
required or implemented.

## Explicit remaining limitations

- Routine/calendar `accept` is blocked: no real queue adapter is provided.
  Proposals do not create a hidden job, simulated acceptance or automatic schedule.
- Process Intelligence excludes synthetic outcomes; Preview does not pretend
  synthetic samples are verified real working habits.
- Models/connections, model tasks, Court/decisions, Router, Execution V2, workers,
  external TTS, NinjaTrader experiments and SF Social publication are disabled
  in this Preview composition. Unsupported direct mutations fail closed.
- System reports actual modes: isolated SQLite/manual domains; other mechanisms
  disabled, blocked or not started. The existing four Preview flags remain
  unchanged; no protective flag was enabled to make a status card green.
- SQLite Preview checks are **not** PostgreSQL/RLS tests. Earlier PG evidence,
  current PG skips and separate Agent World PG runtime acceptance retain their
  own status; this change does not claim or replace any of them.

## Verification

Combined isolated regression: **153 PASS, 0 skipped, 92.00 seconds** across
`test_agent_world_preview_domains.py`, `test_agent_world_gateway.py`,
`test_preview_sandbox.py`, `test_agent_world_domain_service.py` and
`test_agent_world_persona_voice.py`. The new suite covers real ephemeral HTTP
Handler calls, existing authenticated synthetic sessions/control/CSRF, same
DomainService lifecycle, CAS/retry, old avatar/voice preservation, two synthetic
users' private/shared memory and revocation, explicit operator-only seed,
partial-failure recovery, no executor injection, flag/session/root revocation,
non-Preview/Canary/Production and foreign-scope denial, unchanged manual New User
registration and browser-only speech without reading owner TTS configuration.

Final new-scope rerun: **30 PASS, 0 skipped, 45.24 seconds** after adding test-only
malformed-envelope/pagination coverage and coexistence of the six manual fixture
records with the existing four demo tasks. Seed-only overview has zero tasks;
after the real synthetic demo workflow it has four, zero paid calls and no
professional model-quality claim. No app code changed between the combined pass
and this final test-only extension.

Python compilation of all four changed app files and the new test passed.
Scoped `git diff --check` passed. The only existing test adjustment is the exact
scenario-catalog assertion adding the explicitly authorized operator scenario.
No browser, audible output, external provider, Production database or paid call
was used. Temporary test databases/sessions are disposable fixture data, not
real multi-user production acceptance. Browser UI integration, overall program
regression, current implementation status and External GPT Context Pack 02/11
are the root integrator's same-checkpoint responsibilities.
