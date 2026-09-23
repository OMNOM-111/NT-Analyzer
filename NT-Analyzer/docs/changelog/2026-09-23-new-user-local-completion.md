# New-user Local completion

Status: BETA (Local). Verification: PASS for the scoped new-user/Shared Models workflow. No merge, release or deployment approval.

Final runtime code: `0a9bcf095382cabe0783620e503768188957ede5`. Task branch: `codex/shared-model-local-completion`; continuation PR: [#291](https://github.com/OMNOM-111/NT-Analyzer/pull/291), head branch `feat/shared-model-access`. Earlier checkpoints below are historical; the final evidence section supersedes their pending checks.

## Preserved source

Continue Shared Models WIP after f5cb49d5, through 77eda536 and the active Local
chart gateway correction d9c538605e8e6cade81524fc1b41850b7f500980. Work proceeds in
`codex/shared-model-local-completion`, an isolated checkout of that exact ancestry.
The original branch and all dirty runtime/governance/cache files remain intact.

## Implemented changes

- Ordinary Preview registration gets the existing initial trial and its own empty
  personal workspace. The shared-model bridge serves ordinary Preview scenarios;
  an explicit AI-denied profile retains the negative authorization check.
- Actual registry cards gain a short connection test and explicit binding for
  sharing. Shared descriptors render alongside the registry, including when empty.
- Shared connection tests use the same grant, budget and usage accounting.
- Chat can recover a saved reply by exact request identity through a scoped GET,
  with no provider retry. Preview task detail uses the same persisted task store.
- TopStep strategy tab opens under the existing live-read trial capability and
  honestly reports IN DEVELOPMENT. It does not display owner chart credentials
  or alter market-data policy, chart routing, or trading authorization.

## Verification and cleanup

Initial browser reproduction on d9c53860: GitHub/phi-4 card had neither test nor
share control; shared Preview chat returned a real saved answer but its task
state was unavailable. Models tab then failed to load. Browser checks continue.
The embedded browser timed out; hands-on QA uses Chrome through computer-use.
Owner access baseline: 2 users, 1 workspace, 3 memberships; projected access
SHA256 dfcdf0b471112eb88388f3651350b5a5efb6082c172935de1209658af3011ccd.
Disposable Preview was closed through Exit Preview. DeepSeek sharing was
temporarily enabled for QA and restored to off through the owner card.
The final access snapshot has the exact same hash and counts as the baseline.

Server, Canary and Production remain untouched. PR and final evidence pending.

## Local browser follow-up

Ordinary registration was completed in the disposable UI (email fixture, agreement, temporary device, cabinet). Shared DeepSeek and Gemini appeared without owner settings. A real connection test exposed an overview crash: the Preview demo projection assumed `persona_key` on real task checkpoints. The HTTP overview now reads the real scoped domain projection; regression covers a completed shared chat followed by overview/tasks reads. Desktop navigation retains the trial entitlement independently of market-data admission. The internal model chooser includes shared entries. Preview manifest writes retry transient Windows reader locks without truncating existing state.

Verification: 67 focused tests passed before fixing a test-only permissions field typo; the complete Preview module then passed 27 tests. Browser delivery recovery asserts one POST and one history GET, never a repeated model invocation. Manual acceptance and full regression remain pending.

The follow-up real DeepSeek test returned `CONNECTION_OK`, provider model `deepseek-flash`, cost $0.00000546. UI uncovered two additional defects: task-to-chat still selected the synthetic handler, and the fixed Preview banner covered the drawer close button. Real task chat now returns its existing scoped conversation without publishing/executing again; drawer offset includes Preview's actual height. Overview includes shared model entries. SQLite durability transaction handles now close deterministically, so Windows can delete disposable databases on Exit. Bounded bridge requests consume their body before auth rejection to deliver a stable 403 on Windows. Forty focused tests passed, including unchanged durability/worker contracts and task history. Full regression and final manual pass continue.

## Hands-on evidence on a06db104

- One-click shared-user profile: own empty workspace, full existing 5-hour trial. DeepSeek and Gemini visible. DeepSeek test returns CONNECTION_OK ($0.00000546); separate Agent World arithmetic task returns count 3, sum 10, min 2, max 5, mean 3.3333333333333335 ($0.0000161).
- Task-to-chat opens persisted conversation. Chat request returns LOCAL-SHARED-CHAT-OK through Gemini; no delivery error or repeated provider invocation.
- Caller DeepSeek usage: 2 calls, 90 input / 32 output tokens. Owner card has the same caller row and cost, separate from own requests. Owner share-off rejects a call from the already-open caller form; count stays 2 and all three saved tasks remain.
- Previously incomplete Phi-4 registry card has Test and Share. Its real short test reports the provider's invalid JSON response instead of pretending availability. No credential or model configuration was changed.
- Trial navigation: Desktop, TopStep, SF Social, Documents, Backtest, Trading, Finance, Strategies and News opened. No owner reports/trades/accounts/chats appeared. Desktop starts empty; adding a chart reports the existing missing redistribution/source entitlement. TopStep is a separate IN DEVELOPMENT strategy tab. Documents has no Edit control for this user. Back/forward, task close, Chat collapse and reopen checked.
- Explicit AI-denied profile retains the trial but locks AI Lab/Agents and has no AI Center grant. No automatic admin or automation permission.
- Browser error/warning log: empty during the final page pass. Both final shared and denied Preview sessions exited through UI and their complete disposable containers disappeared. An earlier Windows-locked disposable container was removed after its verified process stopped. Owner access before/after identical: 2 users, 1 workspace, 3 memberships, hash above.
- Remaining verification: final Memory-summary fix, full native Windows regression completion and Git closeout. Server/Canary/Production untouched.

## Regression follow-up checkpoint

Native Windows regression completed all 6172 collected cases: 6034 passed, 134 skipped, one outdated TopStep route assertion (corrected), and three transient Windows sharing-violation failures in the encrypted account-store atomic replacement. The affected account writer now uses a unique temporary name and bounded PermissionError retries; persistent refusal preserves the previous encrypted file/cache and cleans its temporary file. Account tests: 80 passed.

Final owner Chat QA exposed an unresponsive renderer when opening the default history. Its API responds in 0.06 seconds and its 181 assistant messages each mounted a video element. Decoder allocation was not measured. History avatars now use first-frame PNG posters from the existing checked-in WebM assets and attach video only during explicit speech, releasing it on stop. Other animated agent cards retain their current behavior. Chat/Persona/result focused tests: 132 passed. Browser confirmation and final regression are pending at this checkpoint.

## Owner history follow-up

The poster change alone did not resolve browser control timeouts. Read-only localhost tracing confirmed that rendering completed and polling continued; the failure was associated with the large rendered history, not a slow history API or stopped JavaScript loop. SF Chat now displays 30 AI messages per history page with explicit Older/Newer controls. All 181 existing messages were traversed through seven pages in the browser without a timeout; one active page stays bounded and the persisted conversation is unchanged. Human-chat cursor pagination remains unchanged. Reply submission returns to the newest AI page. This supplements the inert avatar posters and keeps the approved faces and layout.

Manual Memory verification on 687b7b0: fresh Preview showed zero memory/lessons/strategies/sources and only the still-shared Gemini model. Its disposable directory was removed by Exit Preview. Owner Memory retained 160 fragments, 24 lessons, 22 strategies and 117 sources; owner Desktop retained TopstepX charts, Social retained existing posts, Documents retained owner editing, and Tasks retained its historical records.


## Final runtime browser verification

Active Local: `0a9bcf095382cabe0783620e503768188957ede5`, build
`dev-0.10.0-beta.96-0a9bcf095382`, clean detached runtime; Preview=false.
On the actual http://127.0.0.1:8765 origin, owner Chat opens the newest 30 of
181 saved messages, goes to the preceding page and back, collapses and reopens.
Browser warning/error log is empty. The read-only diagnostic localhost proxy
was stopped after verification; no diagnostic tracing is part of shipped code.
Pre-activation bundle checks passed all four gates for 639 files. Final native
Windows regression runs against this exact runtime code; results pending.


Final disposable UI repeat on `0a9bcf09`: owner Preview picker -> new user with
shared models -> Professional -> ordinary 5-hour trial -> Models. Only the
still-shared Gemini appeared; revoked DeepSeek did not. A real Gemini connection
test returned CONNECTION_OK; Open in SF Chat showed that saved reply. Memory
showed zero fragments, lessons, strategies and sources. Browser warning/error
log was empty. Exit returned to owner Local and removed all 36 disposable files
in Preview `6ef22e4b18408dd4bcf3c663` and its process (48472). No owner sharing or
permission setting was changed during this final repeat.


## Final verification and Local closeout

- Full native Windows regression on runtime code `0a9bcf09`: **6044 passed,
  134 skipped, 0 failed, 0 errors**. All 288 test files were covered exactly
  once across four disjoint whole-file groups; no module was split or excluded.
  Parts: 1474/29, 1285/11, 1718/93 and 1567/1 (passed/skipped).
  Longest part: 3154 seconds. Skipped cases remain skipped, not counted as PASS.
- Related Chat/router/models/Preview suite: 270 passed. Latest focused Chat
  checks: 41 passed. Earlier relevant checkpoint suites are recorded above.
- Exact production-content bundle: 639 files; static scan inside bundle,
  shipped runtime document reads, Python compilation and JavaScript syntax PASS.
  Root-level secret scan: zero findings. External GPT Context validator PASS;
  its historical deployment-anchor warning is not a new Production assertion.
- Actual Local runtime checkout is clean and stays at the tested runtime SHA.
  Final documentation-only changes do not activate or rebuild Local.
- Final one-click Preview cleanup and the full prior manual route are documented
  above. After the last Preview, the owner access projection again matched
  before exactly: 2 users, 1 workspace, 3 memberships, SHA256
  `dfcdf0b471112eb88388f3651350b5a5efb6082c172935de1209658af3011ccd`.
- Existing original checkout remains on `feat/shared-model-access` at 77eda536
  with its pre-existing runtime/governance/cache data preserved outside staging.
  Only the isolated task checkout supplies the source/documentation commits.

Local implementation and verification are complete. Git closeout continues the
existing draft PR #291; no merge or whole-program Agent World acceptance is
implied. Remote CI is separate from these exact-code Local receipts.
Server, Canary and Production were not touched.
