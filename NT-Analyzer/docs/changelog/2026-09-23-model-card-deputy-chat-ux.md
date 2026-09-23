# Local: in-card model check and conversational Deputy

Status: IN DEVELOPMENT — implementation checkpoint, manual acceptance pending.
Branch: codex/shared-model-local-completion; existing draft PR #291.
Base: 88da89041073116a45c52abd4267c9a085489bfa (runtime 0a9bcf09).

## Change

Registry checks previously announced results outside the open model card;
shared checks opened a separate generic action/task flow. Both now show progress
and a real response verdict in place. Diagnostics are collapsed; pending result
refresh reads the existing task instead of issuing another model call. The
redundant Connect another model button is removed from the card.

Preview previously created an assistant_response task for every utterance and
published its delivery/quality/review report as the answer. Ordinary dialogue
now uses a scoped Deputy prompt/history with the same shared grant, provider,
budget and accounting. It persists an idempotent chat reply without creating a
Task. Explicit text deliverables retain tasks and show the actual result. The
model identifier is moved into collapsed details for ordinary conversation.
No new entitlements, model secrets, owner-data copies or trading tools are added.

## Verification checkpoint

- Focused new/updated checks: 14 passed (conversation intent, ambiguity/replay,
  foreign workspace sentinel exclusion, grant revoke, usage, inline progress,
  one POST plus polling, cache/empty response rejection, error and refresh).
- Persona Chat UI suite and shared-model suite: 54 passed in the preceding run;
  its only failure was a fixture reusing one provider request ID for four calls.
  The fixture now uses unique IDs and its usage assertion passes.
- Manual browser acceptance and broader related tests pending at checkpoint.

Local-only change; Server/Canary/Production untouched. Existing full regression
6044 passed / 134 skipped applies to the previous runtime code, not this diff.
Release impact: ordinary Python/static/doc bundle update; no data migration.
