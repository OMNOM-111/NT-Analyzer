# Agent World — Coordinator, Router and System UI contract verification

- Release title: Explicit plan approval, source-bound Router and truthful System controls.
- Change summary: add 101 test-only contracts against the integrator-owned
  `ai-command-center.js`, reusing the existing Node/minimal-DOM real-handler
  harness. No alternative UI, page composition or application implementation
  is introduced by this subtask. A separately authorized follow-up synchronizes
  only shared `ui.js`/`api.js` cache query strings in shipped Aurora pages.
- Canonical status: **IN DEVELOPMENT** pending integrated browser/program
  acceptance. Automated UI contracts do not accept the owner's visual design.
- Branch: `codex/agent-world-unified-acceptance`; source checkpoint
  `13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`. Root owns the page changes,
  final integration SHA/PR and same-checkpoint current/Context Pack updates.
- Initial scope: `tests/test_agent_world_coordinator_ui.py` and this change record.
  Expanded cache-only scope is enumerated below; application JavaScript remains
  integrator-owned and was not changed by this subtask.
  No stage/commit, browser, runtime, Local8765, external model, paid call, queue,
  schema, secrets, merge, deploy or version change by this test-only subtask.

## Contracts covered

- A valid Coordinator preview is tied to its source ID, unapproved, has zero
  dispatches, a canonical plan hash and a bounded nonempty graph. Missing,
  malformed, forward-linked or excessive nodes cannot open an approval form.
- Commission forms separate coordinator and target connections, require the
  initial explicit user gesture and send only the narrow graph payload.
  Parallel topology supports one or two targets; chain supports up to three.
  Depth and parent indices are computed, never accepted from hidden authority
  or extra form fields. The same coordinator connection cannot be a target.
- Connection labels distinguish real verified connectivity, a currently allowed
  synthetic executor and a recorded local test that did not verify a real
  connection. Truthy strings are not treated as confirmed boolean evidence.
- Opening a plan performs no approval or child dispatch. Its confirmation box
  starts unchecked. Approval sends the displayed hash, exact source revision,
  fixed expiry and zero-cost ceiling; it does not send credentials, owner roles,
  workspace authority or an increased budget.
- An uncertain response retry preserves the idempotency key, approved hash and
  first-attempt expiry. Changing approval duration after an attempt is blocked
  until the plan is opened again. A forged approval click cannot bypass preview.
- Rejected, changed-source or `ok:false` preview/approval responses do not open
  a granted state, refresh a success result or invoke apply/enable. Transport
  errors do not expose raw secrets in the form.
- System independently displays implementation, feature flag, observed mode
  and availability. A running legacy worker does not activate Execution V2.
  Large technical fields stay in details and secret fields remain redacted.
- Preview dataset creation is absent on GET/open. Only an enabled server-supplied
  item action exposes `seed_preview`; a client capability hint alone is not a
  grant. Its explicit submission sends the selected dataset ID, empty payload,
  revision zero and one idempotency key, not an owner impersonation request.
- Router listing reads supported source tasks, without computing a preview or
  dispatching. The drawer separates the original explicit connection from a
  Router-originated choice and keeps candidate evidence in expandable details.
  A mismatched task, malformed preview reference/revision or changed source
  cannot offer apply. Unsupported/no-candidate replies remain read-only.
- A Router preview requires a second, initially unchecked consent. Apply sends
  exactly the displayed immutable reference, revision and one idempotency key;
  uncertain retries reuse that envelope. Only the returned new task is opened,
  not a mutated original task. Rejected replies neither refresh a success state
  nor open a claimed new result. Direct apply clicks cannot skip preview.
- The schedule source field loads `model_tasks`, not personas. Choices require
  a stored conversation and model and exclude aggregate delegation records.
  An empty source list explains that a model connection does not replace an
  actual SF Chat request. Loading the form never enables a schedule.
- An aggregate result links every required review and distinguishes accepted,
  pending, rejected and stale contributions. It does not claim that a fact
  transfer check constitutes acceptance of all contributions.

## Findings and evidence

The tests exposed two integration defects, fixed by the root page owner:

1. The outer `validCoordinatorPreview` helper called `recordId`, defined inside
   the page initializer. Valid plan display raised `ReferenceError`. Source ID
   resolution is now available in the helper's own scope.
2. Three parallel children were offered although the existing backend fanout
   ceiling is two. The UI now rejects that shape; three children remain possible
   in a bounded chain. Backend limits were not weakened.

Malformed null nodes are also rejected before rendering their parent/depth.
Initial bounded-scope run: **65 PASS, 0 skipped, 6.66 seconds**. The production page
source was not edited by this test subtask. Runtime/connection data is entirely
in-memory fixture data; fake transport acknowledgements are not real model work
or evidence that child processes ran. Browser, actual budget/worker behavior and
whole-program end-to-end acceptance remain separate root-integrator checks.

Initial combined page regression: **303 PASS, 0 skipped, 33.43 seconds**.
The integrator then explicitly expanded this test-only scope to Router,
the scheduling source-task selector and aggregate review links. Those additions
add **36 PASS, 0 skipped, 5.67 seconds**. Malformed Router preview references and
nonpositive revisions are now rejected by the page owner before offering apply.

Final expanded page regression: **339 PASS, 0 skipped, 35.89 seconds** across the
existing page suite (173), Persona/process UI suite (65) and this new Coordinator/
Router/System suite (101). Python compilation of the new test and JavaScript
syntax checks passed.

Additional first PersonaAudio/SF Chat-dialog regression: **83 PASS, 1 FAIL,
0 skipped, 8.55 seconds**. All dialog lifecycle behavior passes. The remaining
failure is the exact shared-shell cache contract in `test_sf_chat_dialogs.py:74`:
the Agent World page now loads `20260908-persona-hooks1`, while that assertion
and other shared-shell pages still require `20260905-agent-world-followup`.
The integrator authorized the following narrow cache repair. The initial failure
is retained here rather than silently counted as a passing scenario.

## Authorized shared-cache synchronization

Shared version `20260908-agent-world-unified1` now appears on every shipped
Aurora `assets/ui.js` and `assets/api.js` script consumer: **29 URL replacements
across 15 HTML files**. No theme, page-specific script, markup, design or inline
behavior changed. SHA256 of each page after normalizing only these two script
query strings matched its pre-patch SHA256 (15/15). This also preserves the root
integrator's pre-existing Persona script and other Agent World HTML changes.

Exact HTML scope, under `app/static/aurora/`:

| File | Replaced shared URL count |
|---|---:|
| `ai-agents.html` | 2 |
| `ai-command-center.html` | 2 |
| `ai-lab.html` | 2 |
| `backtesting.html` | 2 |
| `community.html` | 2 |
| `desktop.html` | 2 |
| `documents.html` | 2 |
| `index.html` | 2 |
| `mode-entry.html` | 1 (API only) |
| `news.html` | 2 |
| `performance.html` | 2 |
| `practice-trading.html` | 2 |
| `strategies.html` | 2 |
| `topstep.html` | 2 |
| `trading.html` | 2 |

Existing exact cache assertions were updated in `tests/test_aurora_contracts.py`
for both API and UI. `tests/test_sf_chat_dialogs.py` now requires the same shared
API/UI version together with the unchanged dialog stylesheet. No behavioral
assertion was removed or weakened. New files remain this record and
`tests/test_agent_world_coordinator_ui.py`.

After repair, the full PersonaAudio + SF Chat dialog + Aurora contract suites:
**150 PASS, 0 skipped, 11.93 seconds**. `node --check` passed for `ui.js`,
`api.js`, `ai-command-center.js` and `persona-audio.js`; Python compilation
passed for the three changed/new tests. Scoped tracked/untracked whitespace
checks pass. These are isolated automated checks, not visual owner acceptance,
actual provider execution, PostgreSQL/RLS evidence or deployment readiness.

Post-cache rerun of the three Agent World UI suites: **339 PASS, 0 skipped,
35.61 seconds**. Together with the separate 150-case run, **489 automated cases
pass, 0 skipped** after the repair. No test process started or modified Local8765;
remaining browser and full-program checkpoints are owned by the integrator.
