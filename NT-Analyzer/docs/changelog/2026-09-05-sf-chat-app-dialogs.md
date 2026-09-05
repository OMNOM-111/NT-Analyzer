# SF Chat — confirmations inside the application

Release title: SF Chat application-local confirmations.
Change summary: replace browser-blocking conversation prompts with styled,
asynchronous application dialogs while preserving explicit consent and history.
Business requester: project owner. Technical attribution: AI-assisted change.
Version: `0.10.0-beta.96`, unchanged. Local-only correction, not a release.
Branch: `codex/agent-world-owner-preview`, draft
[PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282).
Source base SHA: `dc5cd1115c69d7a76a4f963e07658f1135512a18`.
Exact source commit and Local activation receipt are recorded at closeout below.

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
Exact staged 534-file bundle: PASS (static scan, shipped runtime reads, Python
compile and JavaScript syntax). Local browser activation is the remaining gate.
Verification result: PASS for automated regression; Local visual check pending.

Active Local rollback code at start: `aa54c2940150e540d8b594dbf1d6254e172adbfd`.
There is no data migration or data rollback; never restore the old data backup
over newer owner history. No merge, signing, Canary/Production or real orders.
The wider Agent World owner-key/multi-user/Social/design holds are unchanged.
