# Agent World — Chat does not replace task review

Status: IN DEVELOPMENT. AI-assisted change. Version `0.10.0-beta.96`.
Branch `codex/agent-world-unified-acceptance`, draft PR #285, preceding checkpoint
`a03ec82b686a9f6f05c056fe5a500ecbdb3babac`. No release or Local activation.

## Change and reason

The legacy SF Chat quiet-period helper could mark an old Agent World message
done without a Task review event. Its rating and fulfillment endpoints also
accepted projections independently of the task ledger. This was not human
acceptance and could contaminate legacy model statistics.

Agent World messages are now excluded from those timers, manual legacy marks,
rating, automatic penalty and informational-rating side effects. Both backend
and UI use the persisted `agent_world_` source/action marker. Ordinary legacy
chat behavior remains unchanged. `awaiting_review` is an open state in inference.
Reviewing a result continues through the existing canonical Task/Evaluation
card, not a second rating or permission system. The UI keeps previous marks in
historical details; no error, rating, comment or message is deleted or rewritten.

## Evidence and limits

Disposable boundary plus the whole existing Chief test module: **132 passed**,
18.93 s. New tests cover old pending/completed/failed messages, manual attempts,
timer and background side effects, prior history and unchanged legacy behavior.
Speech/UI tests independently cover suppression of legacy controls and access
to historic marks. Final browser and full integrated regression are still pending.

This correction does not establish professional model quality, accept a task,
grant execution authority or send anything to external providers. Original
owner Local on 8765, its data and keys remain unchanged. Rollback is the saved
preceding checkpoint; migration/merge/deploy were not performed.
