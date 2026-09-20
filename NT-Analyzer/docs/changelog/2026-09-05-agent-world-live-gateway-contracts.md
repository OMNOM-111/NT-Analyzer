# Agent World Local owner gateway and SF Chat contract checks

## Change summary

Add isolated contract tests for the explicit Development-owner Agent World
composition and its existing SF Chat projection. These tests use temporary
runtime roots and mocked existing auth, workspace, permission, budget and audit
authorities. No real owner store, network provider, NinjaTrader job, Telegram
message, runtime process or live configuration is changed by this test slice.

Initiator: owner request for verifiable Agent World behavior through the existing
chat and real-result integration. Technical attribution: AI-assisted change.

## Scope and identity

- Branch: `codex/agent-world-owner-preview`.
- Base at test integration: `c62c5547ef6f82c561bb12b474ee6f3aa21d7c28`.
- Local source version: `0.10.0-beta.96`, unchanged Development, not a release.
- Owned files: `tests/test_agent_world_live_gateway.py` and this change record.
- Final source commit and separate PR are assigned by the integration owner;
  no stage, commit, push, merge or deployment is performed by this test slice.

## Contracts covered

- Default-OFF exact workspace opt-in; invalid/wildcard entries fail closed;
  Canary, Production and synthetic Preview cannot use the live-owner gateway.
- Fresh owner UUID, active owner workspace, writer membership, product
  capabilities, existing permissions and zero-cost budget admission are checked
  again before work. Revoked state cannot reuse an earlier admission result.
- Only read model, UI and task graph flags activate. Evaluation, Court,
  execution/router replacements and the remaining registry entries stay OFF.
- Handler admission retains the established Local entry and requires confirmed
  device state for other owner sessions. Service calls carry exact workspace
  and user scope, with legacy-source fallback disabled.
- Explicit backtest parsing retains negative numeric parameters and requires
  strategy, instrument, timeframe and dates. Existing canonical specification
  validation still rejects invalid, reversed or excessive periods.
- Overview and the existing monitor preserve authorized scope; pending work is
  not projected as a verified outcome and synthetic demo ratings are not used.
- SF Chat hashes the complete request identity before its existing 120-character
  storage limit; deduplication scans the whole transcript. Both direct result
  delivery and ingress retries recover an interrupted message/index projection.
- Queued/running work remains pending; completed reports require verification;
  invalid/non-owner scope cannot execute a callback. No Telegram send or topic
  update is scheduled, even when the pre-existing owner mirror is enabled.

Two strict new tests reproduced application defects during integration: ingress
replay did not repair conversation work state after an assistant append crash,
and initial title metadata could schedule a Telegram topic update. The
integration owner corrected these in the shared chat adapter. Neither assertion
was weakened or marked skipped/xfail; both now pass.

## Verification

- New gateway/SF Chat contract module: **77 passed**.
- New module followed by Preview identity, Windows subscription retry and the
  canonical live-backtest service module: **136 passed**. This also checks the
  order-sensitive fixture boundaries without touching real owner data.
- Python compilation of the new test module: **PASS**.
- Working-tree `git diff --check`: **PASS** at this checkpoint.
- New module plus existing `test_chief_agent.py`, `test_orchestrator_routing.py`
  and `test_sf_chat.py`: **205 passed**.
- Full regression, static/context/artifact gates, real-provider/browser
  acceptance and final
  Git/CI closeout remain the parent integration task's gates, not inferred PASS.

## Documentation and release impact

This is test evidence, not an operational release or an unrestricted agent
rollout. Existing runtime authorities and storage are reused. The integration
owner maintains the shared current status and External GPT Context Pack in the
same task, including the distinct live-owner opt-in versus synthetic Preview
boundaries. The required `02_CURRENT_SYSTEM_STATE.md` and
`11_ACTIVE_WORK_AND_HANDOFF.md` were inspected; their integrated live-owner
update belongs to that coordinated documentation change.

No version bump, Production/Canary action, secret operation, database migration,
owner-data edit or local server replacement is included here.
