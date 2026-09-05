# SF Chat — confirmations inside the application

Release title: SF Chat application-local confirmations.
Change summary: replace browser-blocking conversation prompts with styled,
asynchronous application dialogs while preserving explicit consent and history.
Business requester: project owner. Technical attribution: AI-assisted change.
Version: `0.10.0-beta.96`, unchanged. Local-only correction, not a release.
Branch: `codex/agent-world-owner-preview`, draft
[PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282).
Source base SHA: `dc5cd1115c69d7a76a4f963e07658f1135512a18`.
Source SHA: `95912cbff8152905966e6bb7bfc2a45d3db15f80` (active clean Local code).

## User-visible change and scope

- New/switch/close/delete SF Chat conversations ask inside the application,
  with meaningful action/cancel labels. Delete remains an explicit destructive
  confirmation; dismissing it never deletes history.
- Rename, create folder and move-to-folder use the same in-app input dialog.
  Blank folder means remove its folder association, not cancel.
- Clearing the notification inbox also uses the in-app confirmation; human
  messages remain untouched. Focus returns to the enabled trigger on cancellation.
- Native functions are not monkey-patched. Existing release/trading/security
  administrative prompts outside this slice are unchanged, not claimed migrated.
  AI Center has no direct native confirm/prompt/alert calls.

The shared helper uses a styled DOM `dialog`, theme tokens and the existing
focus-trap helper. Escape dismisses only this dialog; cancel is the default focus.
Input/title/message text is escaped; close/hash navigation/page exit cancel.
Unsupported dialog clients fail closed without browser-prompt fallback.
The event loop, polling and browser tabs remain usable. SF Chat actions are
serialized until their backend operation finishes; consent is never shared with
a second action and is rejected if the conversation/auth context changed.
The same existing APIs, permissions, owner identity/data and Chat stores remain.
No Auth/Device/Preview/model/Connector/trading backend, flags or schemas changed.

Shipped composition: shared `ui.js`, additive `theme.css` rules and matching
cache markers in Aurora HTML. Tests and this change/current/context record are
version-controlled; local screenshots/runtime evidence are not shipped.

## Verification / closeout

Initial focused dialog tests: 53 PASS. Extended focused checks initially found
only two expected cache-version contract mismatches; both now require the new
shared cache value (the assertions were not removed). The disabled-trigger
focus issue found in independent review was fixed and given a regression test.
Focused Aurora/SF Chat/result/responsive regression: 352 PASS (49.38 s).
Final dialog lifecycle/action matrix: 62 PASS (9.33 s), including seven additional
auth-context-change cases. Root CSP/secrets/Markdown scan, JS/Python syntax,
diff and External GPT Context validation PASS. The context validator retains its
known historical deployment-anchor warning, not a new release verification.
Full pytest: **4032 passed / 44 skipped**, 966.68 s. The run collected before
seven additional auth-context parameters were added; all seven are included in
the final 62-case matrix above. Skips are not live-scenario PASS. No credentialed
provider, PostgreSQL or full registration browser scenario was rerun for this UI fix.
Exact staged and runtime 534-file bundles: PASS (static scan, shipped runtime
reads, Python compile and JavaScript syntax).
Verification result: **PASS** for this scoped UI correction, including Local
activation, actual browser cancellation/navigation/focus checks and exact-code CI.

## Actual Local and Git/CI receipt

Only authorized Local 8765 was switched to clean detached source
`95912cbff8152905966e6bb7bfc2a45d3db15f80`:
`dev-0.10.0-beta.96-95912cbff815`, Development, dirty=false, Preview=false.
No active canonical NT/Chief/worker job was interrupted. Original owner data and
session stayed valid (`authenticated=true`, `is_owner=true`); NinjaTrader was not
stopped. The isolated copy passed SQLite integrity and unchanged job/worker/chat
counts with outgoing traffic denied; that copy is not the live owner database.
Task/runtime ui.js SHA256 matches:
`8e922279f7f04443016c6afb0e799cd7c62e7955b2bc18609187b71bb4f16d50`.

Browser evidence on this source:

- Existing unfinished Z.AI thread opened a styled DOM confirmation for New Chat.
  Escape closed only the confirmation and returned focus to New Chat. Current
  conversation, its complete displayed history and 13-conversation count matched
  before/after. The old provider failure was not retried or changed.
- Cancelled create/switch/close/delete, rename with edited input, add folder and
  move-to-folder. No real conversation mutation or model request was submitted.
- Explicitly confirmed read-only navigation returned to the original Ivan chart
  thread; its 13 messages and real PNG remained visible.
- Inbox clear cancellation preserved the inbox, kept its drawer open and
  returned focus to the re-enabled Clear button. No notifications were deleted.
- Screenshot: local non-shipped evidence
  `.artifacts/verification-20260905/sf-chat-dialog-95912cbf.png`.
  Only cancellation and read-only navigation were exercised against owner data;
  creation/deletion/rename/folder acceptance is covered by disposable JS tests.

[Exact-code CI 33970324754](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33970324754)
is **3/3 PASS**: Windows **4039 passed / 44 skipped**, 934.12 s; Linux
**4042 passed / 41 skipped**, 258.02 s; static gates PASS. The fresh CI collection
includes all seven final auth-context cases. The 41 PostgreSQL cases require
explicit isolated-test DSNs; Windows also skips two shell cases and one POSIX
permissions case. Neither those skips nor earlier credentialed acceptance is
counted as a new live-scenario PASS. Main-target mandatory CI/release is not inferred.

Code is committed/pushed to the same draft PR #282, with documentation-only
operational follow-up. `IMPLEMENTATION COMPLETE: YES` and `GIT CLOSEOUT COMPLETE:
YES` for this corrective slice; `STAGE CLOSED: NO` for the wider Agent World
program and owner acceptance. No additional feature stage was implemented here.

Active Local rollback code at start: `aa54c2940150e540d8b594dbf1d6254e172adbfd`.
There is no data migration or data rollback; never restore the old data backup
over newer owner history. No merge, signing, Canary/Production or real orders.
The wider Agent World owner-key/multi-user/Social/design holds are unchanged.
