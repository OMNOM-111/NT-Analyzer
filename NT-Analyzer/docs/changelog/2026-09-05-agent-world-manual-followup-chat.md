# Agent World — explicit manual follow-up in SF Chat

Canonical feature status: `IN DEVELOPMENT` until the root integration and its
Local verification are recorded in repository-only
`docs/current/AGENT_WORLD_IMPLEMENTATION_STATUS.md` (not shipped in the runtime bundle).
Business requester: project owner. Technical attribution: AI-assisted change.
Task branch: `codex/agent-world-owner-preview`; [draft PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282).
Starting source: `f80d67f730bcd4734893ee7f83643f580138be9a`. Final integrated
source SHA, release identity and program verification belong to the root closeout.

## Change summary

An accepted Routine or Calendar record can be opened for manual discussion in
the existing SF Chat. This is an explicit action after acceptance, not automatic
execution of a schedule. The original acceptance receipt and source revision
remain unchanged. One deterministic follow-up conversation contains the exact
record/revision, definition hash, source link, actual request time and the
recorded due date or proposed interval.

The message states that it was recorded immediately because the user requested
it, not delivered on schedule. Automation remains OFF; no model, NinjaTrader,
Desktop, trading, external notification, budget or rating action is performed.
The neutral system message does not pretend to be an AI model's response.
This is coordinator-to-human follow-up, not model-to-model delegation.

## Implementation boundary

- `app/ai_control_center/followup_chat.py` reuses `agent_world_followup` in the
  existing worker queue with `phase=chat_delivery` and three bounded delivery
  attempts. No new scheduler, queue schema or conversation store is introduced.
- The accepted source, immutable definition and original acceptance job/scope
  are reread before writes. The executing worker's exact claim, attempt, lease,
  deadline and cancellation state fence delivery. Fresh session, membership,
  capability and server-side flags remain authoritative.
- The request manifest and delivery receipt use existing private artifacts.
  The existing accepted-revision event and inbox consumer acknowledge delivery
  only after the idempotent SF Chat append and index update.
- Repeated clicks and restarts converge on one source-revision job, thread and
  message. Interrupted append/index/inbox steps repair metadata without a new
  source or external execution. Later conversation work is not downgraded.
- Source acceptance still has its original enqueue-before-commit behavior. The
  separate open-discussion action intentionally avoids adding a worker race to
  that existing transaction.

The root owns gateway action/worker routing, same-page source links and the
neutral non-ratable SF Chat presentation. The backend gateway integration is
included in the contract verification below; visual and live user acceptance
remain separate checks owned by the program closeout.

## Verification

The final matrix has **60 follow-up tests**; together with existing
domain-service and model-delivery tests it passed **140 tests**, 188.18 s:

`python -m pytest tests/test_agent_world_followup_chat.py tests/test_agent_world_domain_service.py tests/test_agent_world_model_delivery.py -q --disable-warnings --maxfail=3`

The temporary worker-route fixture override was removed before this final run.
Delivery uses the actual `domain_gateway.execute_worker`. The HTTP tests use
the actual generic mutation/list/detail routes and the existing Handler
origin/CSRF checks: create, accept, explicit open, durable worker delivery and
read-only projection. Invalid payload, stale revision, missing CSRF and foreign
origin cannot enqueue follow-up delivery.

Additional coverage includes ordinary and owner fixtures, Routine/Calendar,
real disposable SQLite/worker/chat, exact source and claim checks,
cancellation/revocation, bounded retries, idempotency, append-before-index/inbox
interruption, new-session read replay, injected manifest/authority rejection,
and existing chat redaction replay. Python compilation of the new adapter and
focused test module passed. No live credentials or runtime data were used.

Full-program regression, exact staged artifact gates, CI and live Local
acceptance are separate integration gates; none is inferred from this scoped
suite. No merge, deployment, version change or Production migration is included.

## Rollback

Disable the root's additive open-discussion action/worker route or revert the
tested code commit. Do not delete accepted records, existing chat history,
durable receipts or owner data. Previously accepted routines and calendar
records retain their original interpretation; no data migration is required.
