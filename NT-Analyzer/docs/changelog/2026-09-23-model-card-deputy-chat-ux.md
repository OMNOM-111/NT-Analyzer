# Local: in-card model check and conversational Deputy

Status: AVAILABLE on Local — implementation and manual acceptance complete.
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

## Manual findings and follow-up checkpoint

On 4d0b0156, both owner Gemini and new Preview shared Gemini displayed inline
progress followed by a live CONNECTION_OK success. The card stayed open and
technical details expanded in place. Three conversational messages produced
natural saved replies with no tasks; one work request produced exactly one
work item plus the earlier connection check. Console was clean during these
scenarios. Shared requests were actually sent to gemini-2.5-flash.

Manual review also found stale composer/header labels and a collapsed long text
result. The composer now invites messages, names the Deputy, and keeps the
natural work result visible. The task title includes the actual request;
technical verification remains in collapsed details, with review controls intact.

Exit uncovered a Windows read-only SQLite handle that could not be closed when
its finalizer ran on the cleanup thread. Reader slots remain per-thread, but
allow finalizer closure from that thread after the owning request ends. A real
cross-thread reader/GC test verifies the connection is closed and the file can
be deleted. No transaction or admission semantics change.
The failing disposable Preview 3b3d40ff1d55ac429ae2bb17 (PID 42528, port 59107)
was explicitly stopped and its verified isolated 39-file root removed. No owner
settings changed. Fresh UI Exit on the corrected checkpoint is pending.

Checks: related model/Chat/Preview 307 passed; Aurora/new dialogue 111 passed;
updated work/review presentation 58 passed; Preview lifecycle and cross-thread
reader cleanup 31 passed. Root secret scan zero findings. The activated 4d0b0156
bundle contained 641 files and passed all four pre-release gates.


## Final Local acceptance — 9bf69e3d878fd0ec44c0c8084e062c289744c143

Fresh Preview b08e58fa96218b87b342bc45, own workspace, port 50382, created through
Developer Preview → new user/shared models. The final browser walkthrough:

- Open shared Gemini card → Check model: immediate progress, then inline success;
  card remains open, diagnostics collapsed, no duplicate Connect button.
- Open Deputy Chat → Привет: «Привет! Чем могу помочь?».
- Что ты умеешь?: normal concise explanation of strategy research and text work.
- Почему небо голубое?: ordinary short explanation, no task/review/model header.
- Explicit three-point strategy-check plan: visible natural-language result and
  one task named after the request, Deputy as speaker/lead, awaiting human review.
  Pending model marker is hidden; verification details are collapsed.
- Tasks contains exactly one real work item and one separate system connection
  check. The three conversational turns do not create tasks.
- Caller usage: exactly 5 calls, 1513 input + 186 output tokens, $0 known free
  Gemini usage; purposes: 3 assistant_conversation, 1 connection_test, 1 work.
- Browser warning/error log for this final Preview is empty. Standard Exit
  returns to owner Local and removes its entire 37-file disposable root.
- Before/after owner projection identical: 2 users, 1 workspace, 3 memberships,
  SHA256 dfcdf0b471112eb88388f3651350b5a5efb6082c172935de1209658af3011ccd.
  Sharing, owner permissions and production configuration were not changed.

Final-code focused/related suite: **368 passed** (storage/scope, models/delivery,
reader cleanup, Preview sharing, chat review, persona UI, dialogue, inline model
checks and Aurora contracts). Earlier related suite: 307 passed; router suite:
73 passed on the preceding checkpoint. Native full regression 6044/134 belongs
to the previous baseline; a new full regression is not claimed for this UX diff.
Final-code exact-content bundle: 641 files, all four pre-release gates PASS.
Root-level secret scan: zero findings; Context Pack validation PASS.

Local stays clean at 9bf69e3d; final documentation-only closeout does not restart
it. IMPLEMENTATION COMPLETE for this scoped UX request. Draft PR #291 is retained;
no merge, Server, Canary or Production action, or whole-program acceptance.

Owner browser verification after Exit: Gemini's separate «Использование другими»
table retains Preview b08e58fa with 5 calls, 1513/186 tokens and $0.00, exactly
matching caller accounting. No Preview chat, memory or task content appears in
that table. Gemini sharing remained ON throughout this follow-up.
