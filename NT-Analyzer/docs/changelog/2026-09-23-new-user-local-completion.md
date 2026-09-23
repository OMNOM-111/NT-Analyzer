# New-user Local completion

Status: IN DEVELOPMENT. Verification: PENDING. No release or deployment approval.

## Preserved source

Continue Shared Models WIP after f5cb49d5, through 77eda536 and the active Local
chart gateway correction d9c538605e8e6cade81524fc1b41850b7f500980. Work proceeds in
`codex/shared-model-local-completion`, an isolated checkout of that exact ancestry.
The original branch and all dirty runtime/governance/cache files remain intact.

## Changes under verification

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

Final owner Chat QA exposed an unresponsive renderer when opening the default history. Its API responds in 0.06 seconds but the 181 assistant messages instantiate 181 video decoders. History avatars now use first-frame PNG posters from the existing checked-in WebM assets and attach video only during explicit speech, releasing it on stop. Other animated agent cards retain their current behavior. Chat/Persona/result focused tests: 132 passed. Browser confirmation and final regression are pending at this checkpoint.

## Owner history follow-up

The poster change alone did not resolve browser control timeouts. Read-only localhost tracing confirmed that rendering completed and polling continued; the failure was associated with the large rendered history, not a slow history API or stopped JavaScript loop. SF Chat now displays 30 AI messages per history page with explicit Older/Newer controls. All 181 existing messages were traversed through seven pages in the browser without a timeout; one active page stays bounded and the persisted conversation is unchanged. Human-chat cursor pagination remains unchanged. Reply submission returns to the newest AI page. This supplements the inert avatar posters and keeps the approved faces and layout.

Manual Memory verification on 687b7b0: fresh Preview showed zero memory/lessons/strategies/sources and only the still-shared Gemini model. Its disposable directory was removed by Exit Preview. Owner Memory retained 160 fragments, 24 lessons, 22 strategies and 117 sources; owner Desktop retained TopstepX charts, Social retained existing posts, Documents retained owner editing, and Tasks retained its historical records.
