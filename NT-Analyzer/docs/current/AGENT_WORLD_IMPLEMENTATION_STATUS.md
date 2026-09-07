# Agent World — implementation status

Canonical program status: `IN DEVELOPMENT`. This is the single current handoff.
The owner authorized continued implementation through an integrated clickable
Local review, not only two E2E demonstrations. `LOCAL VISUAL REVIEW AVAILABLE: YES`
for the integrated checkpoint below. Full `OWNER ACCEPTANCE READY: NO`: separate
ordinary-user registration/key, multi-user sharing/revocation and permanent Social
publication remain unverified owner-dependent scenarios. The full program is not closed.
No merge, Canary/Production, real orders or budget increase is authorized.

## Active mechanisms WIP — 2026-09-06

Saved WIP source: `f9b9444524aa497781fe3de7254d1bfb0e3b062c` (37 files;
clean worktree after commit). Short static/secret/context/diff and 556-file
bundle gates PASS; exact-checkpoint full pytest NOT RUN. All further backend
work is a separate commit; frozen UI remains exactly as in this checkpoint.

Canonical status for PostgreSQL/RLS, Router V2, Execution/Deviation, bounded
delegation and autonomous scheduling: **IN DEVELOPMENT**, with implementation
and integration gaps. Their additive code is saved on
`codex/agent-world-mechanisms` from `45ab4361`; it is not active on Local.
The exact checkpoint, retained mechanisms, test failures/skips, ownership,
review coordination and next operation are recorded in the
[WIP change record](../changelog/2026-09-06-agent-world-mechanisms-wip.md).
This is preservation of unfinished work, not release readiness or owner acceptance.

Protected Local remains clean `2b6d0112` / beta.96 on port 8765, without
restart, new migrations, flags or data changes. UI/presentation integration is
frozen pending reconciliation with independent draft PR #283. No automatic
transfer of that PR, no merge/deploy, no paid external calls or trading.
Owner registration, separate key and exact permanent Social approval remain
separate pending actions and do not block non-overlapping backend work.

**Reading the sections below:** they describe the retained, reviewable Local
`2b6d0112`, including its historical tests and then-missing mechanisms.
They do not claim that new mechanisms code is absent from the WIP branch or
that its incomplete integration is already available on Local.

## Protected Local source and historical acceptance identity

| Field | Current fact |
| --- | --- |
| Accepted Unified Local | `4ae766ea0c3258a8bb049644ac2afbba6cb89330`, beta.96; open [PR #280](https://github.com/OMNOM-111/NT-Analyzer/pull/280) |
| Foundation dependency | `d5d07ac6817cd10f57d916dab0ce655347a8cbde`; open [PR #281](https://github.com/OMNOM-111/NT-Analyzer/pull/281) |
| Integration branch | `codex/agent-world-owner-preview`, draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282), base `codex/agent-world-foundation` |
| Starting checkpoint | `486db834850d465006a3983d2d83ee809202df60`; integrated model/domain delta `ca505d83a25356df5de2fb468f5bc20666a436d5`; delivery/role/workspace checkpoint `34deb827e4ed0e6a29d5693650b575e86e0f33d6` committed, pushed and activated |
| Active Local 8765 | Clean detached runtime checkout `StratForge-worktrees/agent-world-local-runtime`, SHA `2b6d0112bef88c5bfb73970de64ec5518443e56b`, beta.96 |
| Preserved real state | Original Development data root; actual owner identity/workspace, account/balance/history/configuration and authenticated NinjaTrader preserved |
| Build identity | `dev-0.10.0-beta.96-2b6d0112bef8`, dirty=false; original report/PNG, typed handoff, manual discussion and separate application observations verified |
| Current exact-code CI | [33984524477](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33984524477), 3/3 PASS at `2b6d0112`: Windows 4235/44 skipped, Ubuntu 4238/41 skipped, static |
| Preview | Separate loopback synthetic child/data/cookies; never the real Local data root |
| Version / release | `0.10.0-beta.96` unchanged; no next beta assigned, merge/deploy/signing not performed |
| Shared numbered migrations | Still 1–22; no new Production/Canary schema migration |

The earlier beta.93 discrepancy was a checkout/launcher mismatch: the scheduled
task served the original dirty `7062f749ee92299356c774d01dc0c7b59cdcbba3` checkout.
It was not the accepted Unified beta.96 code. The explicitly authorized switch
used a clean runtime checkout and retained the original real data root. A normal
development-profile launch would reset data to the code checkout, so the Local
wrapper reapplies the verified data root after loading that profile.

The previous source/test/CI snapshot is preserved in
[the pre-model archive](../archive/AGENT_WORLD_PRE_MODEL_CHECKPOINT_486DB834.md).
Desktop plans/images, historical `c9b2883`, foundation records and
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md) are not erased.
[ADR-0012](../adr/0012-agent-world-integrated-local.md) records the current scope.

## Integrated program continuation — owner review

SF Chat in-app dialog correction is **complete** and is not being reimplemented.
The next scoped program delta is documented in the
[integrated review change record](../changelog/2026-09-05-agent-world-program-review.md).
It adds separate genuine application-result observations, explicit typed fact
handoff to another Persona in the same SF Chat, and manual routine/calendar
discussion delivery. Root owns gateway/UI/current docs; delegated scopes own
application/handoff, follow-up, and isolated HTTP/contract tests respectively.

The delta from `f80d67f7` is committed/pushed as `2b6d0112` and active on the
clean Local runtime. Code rollback is `95912cbf`; original owner data was retained.
Frozen full suite is **4235 PASS / 44 skipped**, 1129.40 s; 542-file staged and
clean runtime bundles, isolated-copy integrity/startup and root static/context/diff
checks PASS. Skips are 41 unconfigured PostgreSQL
acceptance cases and three Windows-inapplicable shell/POSIX cases, not PASS.
New live flow acceptance must not be inferred from focused fixture PASS.
Memory now has 26 actual HTTP/SQLite synthetic-session cases (190 combined PASS);
live multi-human browser sharing remains a separate pending scenario.

### Current real execution and browser receipts — 2b6d0112

- The retained real NT result `62182839` and original JSON/report links were
  reverified, not rerun: 64 trades, net after commission -969.70, PF 0.725188.
  The actual Desktop PNG `c691534b` remains 718×424 / 31,541 bytes, SHA256
  `45ba864f7ccb06c9fba8655a4839378e1e9fd049d0d5f3d350567ae3081e9c40`.
  Browser image loading and a screenshot of the PNG inside SF Chat passed.
  It shows 140/800 historical bars, not a live market-data claim.
- **New real handoff PASS:** task `bf665c7e-bdc4-5652-8c22-c2bfcdbc5df1`
  depends on parent `62182839-1c4c-563d-8186-bcef081ec599` revision 9,
  with the same correlation. Anna's separate Azure model returned the eight
  source facts; actual response and `extract_facts` evaluation agree. Estimated
  cost USD 0.000355. This is fact transfer, not strategy or image analysis.
  Original SF Chat `C-1322EA65B646` now contains eight messages, exactly one
  final child result `MSG-235DD76B5F2C`; the original report is preserved.
- **Manual routine/calendar delivery PASS:** the existing accepted revision-2
  records created `AW-FU-df856682d5195c3f69a61d4bbc6e` and
  `AW-FU-8bdfc131d0dcd300d6d04d46db34`, each with one neutral system message.
  Reopening the calendar creates no duplicate. Receipt/message hashes match;
  model/provider are empty, no rating event, automation/execution/scheduled
  delivery=false. This is explicit immediate discussion, not a due-time scheduler.
- Agents display separate application observations: Tolik backtest n=1 NEW,
  Ivan chart n=1 NEW, independently of their n=3 arithmetic observations.
  Anna's fact-transfer evaluation is visible in task/history; no fabricated
  arithmetic score or pooled rating is assigned.
- Post-action read-only check: 12 GET, exact runtime SHA stable before/after,
  `2026-09-05T19:05:43Z`. Evidence under `.artifacts/program-review-20260905/`
  is local/non-shipped. Real receipts and synthetic HTTP/contract tests are
  separate evidence classes. No new backtest was needed for this read check.

### Coverage against all canonical stages

| Stage | Implemented scope available for Local review | Not closed / missing target work |
| --- | --- | --- |
| 0 Baseline / isolation | Separate branch/runtime, preserved real data and rollback | No merge of dependencies or release |
| 1 ADR / contracts | Typed entities, state transitions, authority/event/repository contracts | Later general engine contracts require their review |
| 2 Repository / ledger | Development SQLite revisions, artifacts, inbox/outbox, tenant isolation | Agent World PostgreSQL/RLS adapter not implemented |
| 3 Facade / adapters | Authenticated scoped APIs and existing NT/Desktop/Chat adapters | Production transport/storage acceptance not performed |
| 4 Command Center | Three main tabs with same-page drawers and source receipts | Owner visual acceptance pending |
| 5 Intent / task graph | Real bounded app tasks, exact dependent fact handoff and correlation | General autonomous decomposition/recursive delegation not implemented |
| 6 Models / Router | Own connections and explicit approved owner bindings | Separate ordinary/external key live tests pending; Router shadow not switched |
| 7 Roles / Persona | Create/edit/activate, explicit backtest/chart roles, separate model account | No inferred rights or automatic role assignment |
| 8 Outcomes / evaluation | Independent rubric + application receipts, distinct-input observations | No general calibrated reputation or automatic routing influence |
| 9 Consensus / Court | Same-input contributions, isolated three-model votes, advisory verdict | Verdict does not execute actions or replace human approval |
| 10 Execution / deviations | Existing worker/NT/Desktop lease, cancellation and delivery authorities | New Execution Engine/Deviation Control not implemented |
| 11 Memory / projects / schedule | Source-bound Memory/grants, versioned projects, accepted events and manual discussion | Autonomous due-time execution not implemented; live multi-user Memory acceptance pending |
| 12 SF Chat / SF Social | Same-chat report/PNG and handoff, explicit sanitized publication preview | Permanent SF Social write awaits exact owner approval |
| 13 Cutover / release | Isolated Local review and scoped Git/CI evidence | No merge, legacy removal, Canary/Production or release acceptance |

Ordinary-account draft currently reports an expired/used email challenge.
Registration and user-supplied key must be completed by the user; no ordinary
live connection or finished wizard session is falsely claimed. The connection
form itself is implemented with an exact key-field guide and no owner-key copy.
This limitation does not stop the other review paths.

## SF Chat application-local decisions

Canonical feature status: `BETA` (browser-verified on 95912cbf, retained on 2b6d0112).
Conversation create/switch/close/delete confirmations and rename/folder inputs
now use styled asynchronous in-app dialogs. Inbox clear uses the same helper.
Cancel preserves history/cursors; Escape closes only the decision window, not
the chat/inspector. Repeated actions and changed conversation/auth context cannot
reuse consent. Existing Chat APIs/stores and Auth/device/Preview gates are unchanged.
Release/trading/security administrative native prompts outside this slice are
not claimed migrated. See the
[scoped change record](../changelog/2026-09-05-sf-chat-app-dialogs.md)
for verification, exact source/activation and rollback evidence.

The actual browser check covered create/switch/close/delete, rename, folder create/
move, Escape and inbox clear cancellation. The original 13-dialogue list and
selected history were preserved. Confirmed read-only navigation returned to the
original Ivan chart thread. No provider request, deletion, rename or folder write
was made against real user data. Owner Local remains authenticated; runtime
ui.js hash matches the task source. Full 4032 PASS/44 skipped plus the final
62-case matrix and 352 focused regression, staged/runtime 534-file bundle PASS.
Exact-code CI [33970324754](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33970324754)
is 3/3 PASS: Windows 4039/44, Linux 4042/41 and static. This is not a full-program
or release closeout; skipped PostgreSQL/platform cases are not new live PASS.

## One-page product contract and requirements matrix

Exactly three primary tabs: **Обзор / Работа / Агенты**. All additional domains
open as drawers on the same AI Center page. Existing SF Social and SF Chat retain
their design and stores; compatible `community*` APIs remain unchanged.
The state column uses the owner's acceptance categories, not a percentage.
Automated fixture checks are distinct from actual browser/provider verification.

| Requirement | Where / action | Existing backend and additive adapter | Evidence / current acceptance state |
| --- | --- | --- | --- |
| Safe Local switch | Local 8765, runtime identity/account/status | Existing scheduled task/supervisor; clean code + original data root | **готово и проверено** through clean `2b6d0112`: isolated-copy integrity/identity checks, exact runtime bundle PASS, same owner/runtime retained, NinjaTrader untouched |
| Auth, registration, device permanent/session | Entry, account → Security | Existing account_auth / security_devices | Baseline retained; new read-only worker session checks: 17 PASS. Current full regression PASS; a fresh complete auth/device browser walkthrough was not repeated for this presentation correction |
| Preview registration and Exit | Owner Preview → New User, Reset, Exit | Existing sandbox credentials/state/backend flow | Baseline preserved; new real domain actions fail closed in Preview. Accepted baseline Telegram/Google/email/OTP/QR/permanent/session/Exit walkthrough PASS; current regression PASS, no new complete walkthrough claimed |
| Persona | Toolbar → Persona; create/edit/activate/suspend | DomainService + immutable Persona profile; explicit application-role association | **готово и проверено**: Tolik backtest / Ivan chart roles; separate Anna review Persona without application role, three actual records; retired model history preserved |
| Own models / supported compatible agent | Toolbar → Models; connect/test/task/disconnect | ModelService → existing secret store, universal client and worker | Scoped transport/authority/idempotency tests PASS; ordinary live credentials: **внешний blocker** until a user-owned connection is available; no owner key copying |
| Existing owner connections | Models → bind existing approved connection | Fresh owner/runtime authority, exact existing registry ID/caps | DeepSeek Flash, Gemini Flash and Anna's Azure Mini **готово и проверено**: real CONNECTION_OK; Z.AI **внешний blocker**: model_endpoint_unavailable; only its new binding retired, original registry preserved |
| SF Chat → model → real backtest | Tolik command with explicit catalog strategy/instrument/period | application_chat → model plan → existing jobqueue/NT → verified source report | **готово и проверено**: model task 62182839, source awnt_7ed6…, 64 trades, -969.70 after commission; five same-chat messages survived 34deb827 restart without duplication, one folded source workflow |
| SF Chat → model → actual Desktop screenshot | Ivan command; open Desktop matching instrument/timeframe | Existing Desktop command queue/canvas/snapshot store | **готово и проверено** on ef4006eb and rechecked on aa54c294: task c691534b, actual Gemini → Desktop PNG, 140/800 historical bars, same-chat report. Earlier rejected plan and initial no-bars timeout remain failures, not relabelled success |
| Task Inspector / trace / history | Work row or task card → drawer → SF Chat/evidence | Intent/Task/Contribution/model Execution + application Execution/Outcome/Evaluation | **готово и проверено** on aa54c294: stored application Outcome/verification, original report link and correct file/PNG rendering; both original chats preserved |
| Automatic observed rating | Agents → profile/rating | Independent versioned deterministic rubric plus separate application receipt observations, distinct-input dedupe | **готово и проверено** on 2b6d0112: DeepSeek/Gemini n=3 arithmetic inputs each, low confidence; Tolik backtest n=1 and Ivan chart n=1 NEW in separate columns. Anna fact-transfer evaluation is in history, not invented arithmetic. No pooled score or routing effect |
| Explicit agent delegation | Verified application task → transfer facts → another active Persona | Existing ModelService/worker/SF Chat, typed dependency and sealed source facts | **готово и проверено** on 2b6d0112: real Azure child bf665c7e, extract_facts PASS, same conversation/correlation, exact parent revision. General recursive delegation is **не реализовано** |
| Experiments / comparisons | Toolbar → Experiments → same-input comparison | ModelService + existing worker; separate actual responses | **готово и проверено**: three same-input comparisons, six actual verified model outputs; aa54c294 shows n=3 arithmetic observations for Tolik/Ivan and NEW for Anna |
| Decisions / Consensus / Court | Toolbar → Decisions/Court; proposal, three isolated judges | DomainService + ModelService.judge; sealed packet, immutable votes, 2-of-3 | **готово и проверено** on aa54c294: same-input Consensus proposal cf1464ab; fresh Court ae0e5e45 has three valid independent votes and approve verdict. Old 86a650ab still has one vote; its rejected Gemini response remains a failure. No execution authority |
| Memory / lessons / sharing | Toolbar → Memory; edit/promote/publish/revoke | Existing private artifacts + active TTL/purpose/source-revision grant | Private create/source binding/promote/read **готово и проверено** in browser; 26 actual HTTP/SQLite synthetic-session checks PASS for sharing/revoke/TTL/authority. Separate multi-user visual acceptance **не проверено** |
| Strategy Projects | Toolbar → Projects; definition/version/history | DomainService immutable StrategyProject revisions | Browser create/version/history **готово и проверено**; actual version 2 on bd239e76 shows 02:35 local time; old version 1 remains undated |
| Routines / calendar | Toolbar → routines/calendar; propose/accept/open manual discussion | DomainService → existing worker follow-up receipt | **готово и проверено** on 2b6d0112: accepted definitions/dates preserved, each manual action delivered exactly one system SF Chat message; repeated calendar action deduplicated. Autonomous scheduling is **не реализовано**; automation stays OFF |
| System | Toolbar → System | Existing runtime/capabilities/registry flags, no secrets | **готово и проверено**: eight exact-workspace paths active, Router/Execution V2 and external actions OFF, existing worker and budget authorities visible |
| SF Social publication | Toolbar → В SF Social; select source → exact preview → explicit permanent confirmation | SocialPublicationService → existing Community store/idempotency | **Предпросмотр готов и проверен** on aa54c294: net -969.70 / PF 0.7252 explicitly after commission, immutable source revision 2. No post created; permanent publication awaits owner's confirmation |
| Restart / cancel / retry / isolation | Existing Local worker, task status and same conversation | Existing queues/leases/inbox; fresh authority before transmission | Contract PASS; actual restart retained backtest chat and recovered one sealed rejected-model report without a second provider job. Other-user/live revocation remains pending |
| Existing PostgreSQL regression | Disposable loopback test DB only | Existing migrations 1–22 and RLS-enabled app role, TLS | Historical actual DB run: 41 PASS, zero skips, 122.71 s. Current full regression skips these 41 cases without isolated DSNs; no fresh PG PASS or new Agent World adapter claimed |
| General Router / new Execution Engine / Agent World PostgreSQL adapter | Not switched into runtime | Existing Router/executors remain authorities | **не реализовано** for new replacement systems; no new PG adapter or Production fallback is claimed |
| Full suite / final SHA CI / owner design | Verification and draft PR | Existing test/static/context/bundle/CI gates | Active 2b6d0112: full 4235/44 skipped, 267 integrated focused, staged/runtime 542-file bundles PASS; exact-code CI 33984524477 3/3 PASS (Windows 4235/44, Linux 4238/41). Earlier evidence preserved below. Owner design acceptance remains separate |

The manual historical job `ui_20260905T003301149Z` (1273 bars, 64 trades) remains
excluded from Agent World statistics. It proves the original executor can return
real reports, not the new chain. The fresh scoped task below supplies distinct
model/chat-chain evidence. Backtesting page redesign remains outside this task.

### Actual model-to-NinjaTrader receipt

The browser SF Chat command requested SampleMACrossOver / MNQ 09-26 / 5m /
2026-08-24 through 2026-08-29, Fast=10, Slow=25. Actual model response:
`deepseek-v4-flash`, 1256 ms, reported cost USD 0.00006776.
Model task `62182839-1c4c-563d-8186-bcef081ec599`, SF Chat `C-1322EA65B646`,
source task `b316f454-662f-5791-9808-322bd00f92f4`, original NT job
`awnt_7ed6b329cead8eac1391f5c8a0f3b59ad6d2d073baca9a6f` all match.
64 actual historical trades, net after commission -969.70, PF 0.725188.
Original `result.json` SHA256:
`202e31d6775e7e08cb3e4300110cc7ec3878f2023ead080944e119db2251bc6f`.
Immutable verified summary artifact `f1dae944-aaed-5afb-bd38-06dd5e362fdc`, SHA256
`7c9e8d550e1f161a81ac59f8139a041f400ccd62f3f4435954be708f839c51be`.
Execution-conformance PASS is not strategy profitability or general model quality.

Actual connection task `b7114186-079b-58be-98dc-e38c552c65d2` returned Gemini
`CONNECTION_OK` at 611 ms. Three browser comparisons used JSON inputs
`[13,-5,22,10]`, `[7,-11,23,9,12]`, `[101,-24,38,7,12,-8]` for both models.
Comparison IDs: `fe17dc14-2944-51c6-b125-7ea3065d7852`,
`c55cf8c8-e31d-5862-a12d-038df10414fe`, `5d749d7b-e4fa-564d-8f69-7626d0cd4333`.
All six outputs independently passed; n=3 per model is only low-confidence
bounded arithmetic evidence. Failed Z.AI connection remains visible in history.

### 34deb827 browser continuation

- Project `9f89fa8d-6018-52f7-aa2c-13982d21385e`: real backtest parameters,
  immutable version 1, revision 2, history reopened in the same drawer.
- Private Memory `58dc952d-16ff-5ea1-a96b-34036bb7f65d`: original verified
  summary artifact, 30-day retention, explicit promotion to active revision 2.
- Manual routine `a590f088-8ac5-59e1-ac62-b44142b66f9d`: accepted revision 2,
  source artifact retained; no automatic model, backtest or order execution.
- Calendar `4901ad4b-d44c-5f28-86c7-5d40543fcd62`: test-only historical interval
  2026-09-05 00:00–00:30 America/Los_Angeles saved as 07:00–07:30 UTC;
  explicit acceptance verified in the list. System drawer confirmed eight
  scoped active flags, Router/Execution V2 and external actions OFF.
- Decision `6fb853a7-cdfd-5739-8623-b1c2c352b2c8`: proposed review of the
  actual negative NT report using the exact verified summary artifact. No
  Court verdict or approval is claimed before three real judge responses.
- Chart model task `4d1d5b2f-61e9-57d6-90fa-cbd0e2cb611d`, conversation
  `C-9D163439293C`: actual Gemini response at 1355 ms wrapped the required JSON
  in another object/code fence. Independent verification FAIL; no chart command
  was sent. The saved failed evaluation is retained, never relabelled PASS.
- Desktop displayed actual cached historical candles with LIVE unavailable,
  then its browser renderer stopped responding. One reload did not recover it;
  repeated control attempts stopped. A separate lightweight AI Center tab works.
  Neither a blank screenshot nor a source timeout counts as chart acceptance.

Activated ef4006eb corrections: one claimed delivery of sealed rejected responses,
stronger exact-JSON planning instructions (verification remains strict), active
model-only persona rating with retired history retained, local calendar time
display, neutral accepted label and timestamps for new project versions.

### ef4006eb actual Desktop and recovery

The old rejected Gemini plan now has a single failure report in its original
chat, unchanged evaluation `cb36b176-4f1d-502d-8401-bdd55f3faa10`, no Desktop
dispatch and no replacement provider task. The browser recovered after the Local
restart and showed that failure explicitly. A new correct model plan initially
timed out waiting for chart bars (task `c5442d2e-bd79-5270-9476-87d4ed3392a5`).
After real bars loaded, a fresh user-command test succeeded:

- Model task `c691534b-0670-5313-af39-491b46564248`, actual Gemini 724 ms.
- Desktop command `cc_b739f32e686c4c33982c927c87901e46`, source task
  `6f3a28a2-6234-579a-b7ed-4abb0da1c400`, original SF Chat `C-9D163439293C`.
- PNG artifact `42edb20c-eeea-54cd-87cd-6ef9f51d2e4a`, SHA256
  `45ba864f7ccb06c9fba8655a4839378e1e9fd049d0d5f3d350567ae3081e9c40`.
- 140 visible bars / 800 total; MNQ 09-26, 5m, range
  2026-09-04 09:25–21:00 UTC; current view preserved. Historical OFFLINE
  provenance and price_marker_live=false remain explicit. PNG rendered in chat.
- Chat now contains 13 messages for three distinct attempts, not three successes.

Anna `66d0522d-5d81-56f5-8c23-443ddc9cf220` is an active independent review
Persona without an application role or fabricated rating. Its existing Azure
owner binding revealed a compatibility error: the approved native endpoint's
sole api-version query was rejected. The narrow fix permits only the canonical
HTTPS Azure version selector on server-resolved owner bindings; credentials,
fragments, other queries, private transports and budgets remain unchanged.
No failed binding created a connection or copied a key. Focused 187 PASS; full
regression passed 3925/44; subsequent exact bundle, activation and actual Azure PASS are recorded below.

## Authority and flags

All ten flags default OFF. Trusted server configuration requires exact
`STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES` entries, Development environment and
fresh user/workspace admission; malformed/wildcard settings fail closed.

| Scope | Enabled flags |
| --- | --- |
| Admitted Development workspace | Read model, UI, task graph, evaluation shadow, memory, consensus, Court, explicit social publishing |
| Controlled synthetic Preview | Read model, UI, task graph, synthetic evaluation only |
| Unconfigured Local / Canary / Production | None |
| Every scope in this checkpoint | Router shadow and Execution V2 remain OFF |

Model/provider identity, Role and Persona remain distinct. Global owner registry
access is never an ordinary-user permission. New private paid connections fail
closed without approved allowances; no budget is raised by connection or testing.
Compatible private transport uses approved HTTPS origins, public IP pinning,
bounded responses and no redirects/hidden retries.

Workers retain only a non-secret session reference and recheck active confirmed
session, owner UUID, membership, capabilities and budget before calls. Expired
trial/budget blocks new work but not existing own history. Read-only members see
only their own records and explicitly published active Memory. Raw provider
secrets and private prompts do not enter public DTOs or social snapshots.

Preview remains credential-free and externally blocked. Its new domain drawers
explain the Local-only boundary instead of calling live providers. Reset/Exit
cannot replace, trim or reseed real Local data.

## Verification checkpoint

- Broad checkpoint before final claim/role/workspace changes: **3852 passed,
  44 skipped**, 622.61 s; not acceptance of subsequent changes.
- Scoped follow-up: **270 passed** (private workspace, application chat, domains,
  gateway, SQLite); **28 delivery** and **18 explicit-role/projection** tests PASS.
  Single claimed delivery jobs recover saved results through the existing
  worker/inbox; no repeat provider call or budget charge.
- Historical 34deb827 scoped full rerun: **3906 passed, 44 skipped**, 770.01 s.
  Legacy **13/13 suites**, Python compile, **23 JS files**, root-level secret/
  Markdown/CSP scans, context validator and **533-file bundle** gates PASS.
  Forty-four skipped scenarios are not represented as generic Windows PASS.
- Final corrective full rerun: **3914 passed, 44 skipped**, 759.73 s, XML
  `.artifacts/verification-20260905/full-regression-final-domain-ui-v2.xml`.
  Focused UI/domain **218 PASS**; legacy **13/13**, Python compile, **23 JS**,
  root scan and context validator rerun PASS. Staged and clean runtime 533-file
  bundles PASS; ef4006eb CI 33956017912 passed all three jobs. The first new UI test
  used an incorrect fixture shape and failed (217 passed/1 failed); the fixture
  was corrected to the real top-level DTO. An early concurrent full run was
  interrupted and is not evidence; the final complete run above supersedes it.
- Native Azure binding follow-up: **3925 passed, 44 skipped**, 759.35 s,
  XML `.artifacts/verification-20260905/full-regression-azure-native-binding.xml`,
  plus **187 focused PASS**. Python/root/diff, staged/runtime bundle and activation
  subsequently PASS on bd239e76.
- Actual isolated PostgreSQL rerun: **41 passed**, 122.71 s, zero skipped;
  migrations 1–22, app/admin roles non-superuser and NOBYPASSRLS, TLS.
- Forty-one of the 44 generic Windows skips are the separately executed PG
  cases. The other three are two shell tests and one POSIX permissions test,
  unavailable on this Windows runner; they are not Windows PASS.
- UI/domain/application/service focused evidence is in the
  [integrated change record](../changelog/2026-09-05-agent-world-integrated-local.md)
  and delegated scoped records. Fixture provider tests are not live model tests.
- Exact 34deb827 [CI run 33951941036](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33951941036)
  passed Windows, Ubuntu and static jobs. Active ef4006eb
  [CI 33956017912](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33956017912)
  also passed all three jobs. Later bd239e76 and 93bb1298 exact-SHA CI passed 3/3;
  each historical run certifies only its own code.
  Stacked draft PR dependencies
  remain unmerged; main-target mandatory release checks are not inferred.
- Ordinary test registration `aw_model_review_0905` reached final Terms on
  localhost:8765, separate from the owner's 127.0.0.1 cookies. No account has
  been finalized on the owner's behalf. **PENDING OWNER REGISTRATION / KEY**.
  The prepared private-workspace route requires a real confirmed human session,
  creates only that user's container, and grants no NT/key/budget access. Exact
  workspace opt-in is still server-side. OpenRouter / `openrouter/free` is the
  supported test choice; owner types the key into **Ключ подключения** personally.
  Native Gemini is supported for existing owner bindings, not this private wizard.

### bd239e76 actual Azure and Court continuation

Native Azure binding `bd80b782-1c31-5036-bd9b-1808fe994599` belongs to Anna,
using only the existing approved owner registry. Task
`d916ccc4-5149-5e12-afd6-e8eacabd2e79`: actual CONNECTION_OK, 2,235 ms,
recorded cost $0.00005025. No new key or budget. Full 3925/44, focused 187,
legacy 13/13, staged/runtime 533-file bundles and exact bd239e76
[CI 33958551325](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33958551325)
PASS. Original backtest and chart remained succeeded, chats retained 5 and 13
messages after activation. Project version 2 / revision 3 displays actual
02:35 local creation time; original version 1 stays undated.

Historical bd239e76 Court case `86a650ab-0e70-54da-b859-21280af8fef9` exposed a collision:
judge() synchronously executed a task that start_task() also sent to the worker.
DeepSeek task `8d256003-6513-5369-a204-89538c5fb402` has an authentic schema-PASS
receipt (1,988 ms, $0.00025634), but was blocked with no attached vote.
The original UI request was subsequently resumed on 93bb1298; see below.

Corrective scope: sealed Court calls have one synchronous dispatch owner, no
duplicate worker enqueue. Freshly authorized replay may finish the original
immutable receipt through existing states; missing/wrong receipt, invalid vote,
revoked access and unknown in-flight execution are not converted to approval.
Eleven focused fault cases PASS (including five interruption points).
Final focused **274 PASS**, 253.84 s. Full **3936 passed / 44 skipped**,
1035.64 s, XML `.artifacts/verification-20260905/full-regression-court-single-dispatch.xml`.
Legacy 13/13, Python compile, root scan, context/diff, staged/runtime 533-file
bundles and corrected-code activation PASS. Exact 93bb1298
[CI 33960694698](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33960694698)
passed Linux, Windows and static jobs.
No new API, SQL migration, queue engine, budget or authority is introduced.

### 93bb1298 actual continuation and next verified delta

The original Court request reused DeepSeek task 8d256003 and its unchanged
receipt/cost. Vote `e6a60b52-1881-5824-a761-d25a00a666d3` was attached to the
same case (revision 3, one vote). Gemini task `484a0ad9-33ef-5843-85cd-4662c0e322e1`
returned fenced JSON at 1,702 ms and failed strict vote_schema verification.
It remains review, with its immutable response/evaluation intact; Anna was not
called in that case and no Court verdict or execution was granted.

Follow-up implemented in aa54c294: new sealed Court requests add a versioned
`response_format_version=plain-json-v1` instruction; old requests retain their
identity, prompt format and failures. No JSON coercion or weaker validator.
The inspected model/application DTO now projects its stored Outcome instead
of an empty list. Safe original-report links are added to the same Inspector
and SF Chat; new JSON attachments are files, and read-time compatibility renders
old report JSON as a link without rewriting a message or rerunning its provider.
The real PNG renderer and human chat are preserved.

The read-only SF Social preview exposed gross PF 0.7541 beside net-after-commission
-969.7. The existing public metric sanitizer now prefers available valid
profit_factor_after_commission, and Agent World labels both metric bases.
Expected rounded public PF is 0.7252 from the unchanged source 0.725188; original
reports and existing permanent publications are not rewritten. No post was created.
Presentation checkpoint: **610 focused PASS**, 442.96 s; full **3972 passed /
44 skipped**, 1064.11 s. This is before the subsequent Consensus picker fix.
Legacy 13/13, Python/JS/root/context/diff PASS.

Manual Consensus selection exposed a read projection defect: the global artifact
dedupe hid successful contributions behind their Outcome evidence. The form
offered only failed/review model tasks; the server correctly refused them and
created no proposal or vote. A route-level regression reproduced the empty valid
candidate list on old code. The new projection reads owned accepted contributions
directly, filters successful real non-Court tasks, and labels independent models
by the same sealed input hash. No authority or source state changes. Targeted
domain/gateway/UI rerun: **319 PASS**, 101.21 s. Final full: **3977 passed /
44 skipped**, 954.04 s, XML
`.artifacts/verification-20260905/full-regression-consensus-result-final.xml`.
Legacy 13/13, Python/JS, root CSP/secrets/Markdown, context/diff and exact staged
533-file bundle PASS. Commit, Local activation and exact-SHA CI subsequently
passed on aa54c294; see the operational acceptance below.

## Historical aa54c294 Local acceptance — 2026-09-05

Code `aa54c2940150e540d8b594dbf1d6254e172adbfd` is committed and pushed.
Clean runtime 8765 serves that exact code and original owner data; Preview=false,
live orders=false. Isolated-copy startup and actual 533-file runtime bundle PASS.
Copy before/after counts describe the frozen rehearsal, not today's owner totals.
Operational documentation may advance the task branch beyond the active code SHA;
that is not another runtime activation.

[Exact-code CI 33965039490](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33965039490)
completed successfully: Windows 3977 passed / 44 skipped (815.61 s), Ubuntu
3980 passed / 41 skipped (255.41 s), static; 3/3 jobs. Local final full suite:
3977 passed / 44 skipped, 954.04 s; final focused 319 PASS, presentation focused
610 PASS; legacy 13/13 suites, root/static/context/diff and staged/runtime bundle
PASS. The separate 41-case PG evidence and three Windows-unavailable scenarios
remain distinct. Main-target mandatory checks are not inferred from this workflow.
Context validation passes with its known historical pack-anchor warning: the
uniform header SHA still names the recorded beta.87 deployment; exact active
Local verification is separately identified by aa54c294. No Production refresh
or cosmetic rewrite of unrelated Context Pack documents is implied.

Actual browser checks after activation:

- Tolik's Inspector shows the stored verified application Outcome. SF Chat opens
  the exact original NT report without rerunning it: 64 trades, net -969.70,
  after-commission PF 0.725188 (modal rounds to 0.73), charts and trade table.
  Summary JSON is a file link, not a broken image. The pre-existing backtest
  list uses gross PF; its redesign is outside this correction. The source modal
  and new Agent World/Social projection explicitly use the net basis.
- Ivan's Inspector and original SF Chat render the same genuine historical PNG,
  140/800 bars, unchanged SHA256 45ba864f… and 13 messages. Tolik retains five
  messages. No new backtest or chart/model retry was needed for these read checks.
  Earlier failed attempts remain visible.
- Agents: three Personas, Tolik/Ivan n=3 and 100% for the explicitly named
  arithmetic rubric, low confidence; Anna NEW/n=0. A connection or Court vote
  does not manufacture a quality rating.
- Consensus `cf1464ab-e423-5903-8848-f0e49ece6027`, proposed revision 1:
  input group `69a4d7af`, [101,-24,38,7,12,-8], sum 126; accepted contributions
  `5c41f39f-69cb-52a3-a9d7-658d53e2ef3d` and
  `9e4eede3-fb28-56fa-ae0b-33a162f30d09`. Assembly created no calls, votes or work.
- Fresh Court `ae0e5e45-83fb-5938-b0c5-37c67afc6abf`, decided/approve revision 6;
  decision `6fb853a7-cdfd-5739-8623-b1c2c352b2c8` approved revision 4.
  Three real isolated model tasks succeeded: DeepSeek
  `50ad602d-b885-5e87-bc87-2d4a3c0e50e9`, Gemini
  `571af8ab-55ea-51f2-866c-349bbbc76bac`, Azure
  `26883752-0800-5c80-8166-5b54e136747b`.
  Votes `505e0871-c45d-5ed5-9632-d087f96bafae`,
  `e57be5b1-e888-50ab-a125-4cd1b9bcbb88`,
  `5e81c13b-6f52-5c19-b72a-bc72c61a8af3` all approve, confidence 92/90/92
  (not vote weights), unchanged evidence packet SHA256 b5c19b04….
  Old 86a650ab stays voting/revision 3 with one vote and its invalid Gemini
  response preserved. Reporting approval is not profitability or trading authority.
- SF Social read-only snapshot SHA256
  `e4853566df3b4091b276f21503c64956b02a4502087e47a8af6362db6507eaee`:
  outcome 7d5bbecf… revision 2, net -969.7 and PF 0.7252 after commission,
  64 trades. Visibility stayed private, permanent confirmation unchecked,
  no post created.
- Screenshots remain local non-shipped evidence in
  `.artifacts/verification-20260905/`: source-report-aa54c294.png,
  sf-chat-desktop-aa54c294.png, court-aa54c294.png and
  social-preview-aa54c294.png. No provider secret is included.

## Owner visual review route

Open [Local review](http://127.0.0.1:8765/ui/ai-command-center.html?review=2b6d0112#tab=overview). Three primary tabs remain
Обзор / Работа / Агенты; all secondary tools and task evidence open in drawers.
Work → **Толик · backtest_spec** contains the original 64-trade report and its
same SF Chat. **Иван · chart_spec**, succeeded/application_verified, contains
the real historical Desktop PNG; earlier failed attempts are intentionally visible.
The backtest task also opens the completed **Передать факты агенту** child from
Anna in the same SF Chat. Agents shows three Personas, measured n=3 arithmetic
observations for Tolik/Ivan and separate n=1 backtest/chart NEW observations.
Anna's fact-transfer result is in task history. Court decisions never authorize
execution or trading. Toolbar drawers give Memory, Projects, Decisions/Court,
Routines/Calendar and the explicit private SF Social preview without leaving
the page. The accepted routine/calendar **Открыть ручной разбор в SF Chat**
actions reopen their delivered discussions without automatic task execution.

Ordinary review identity `aw_model_review_0905` is a registration draft, not yet
a created account. Its separate `localhost` browser tab awaits personal Terms
and device-trust choices. After that, create the personal workspace and open
**Агенты → Подключить свою модель**: OpenRouter, model `openrouter/free`, Endpoint
blank, separate key in **Ключ подключения** (password field). Obtain a normal
inference key from [OpenRouter keys](https://openrouter.ai/settings/keys), not a
management key; the [free router documentation](https://openrouter.ai/docs/guides/routing/routers/free-router)
describes the test model. Never copy an owner key, accept the owner's clickwrap
or call this live scenario PASS before the separate connection is verified.

## Shared-file ownership

| Area | Single writer / review responsibility |
| --- | --- |
| Server, permissions, auth session lease, live/domain/Preview HTTP, model chat, Local launcher and final evidence | Root integration |
| Domain records/service, SQLite read/receipt/grant methods and social publisher | Storage workstream; root integration review |
| Model transport/execution/evaluation/service, application bridge and named-source chart read | Workflows workstream; root integration review |
| AI Center HTML/CSS/JS and gateway/UI/publication contracts | UI workstream; root integration review |
| Canonical status, ADR-0012, integrated changelog, final matrix/Git/CI | Root |
| Market data/chart engine/Connector/jobqueue/trading | No refactor; original authorities retained |
| Auth/devices/SF stores | Preserved regression contracts; only named integration boundaries change |

## Backup, rollback and next safe action

Operator evidence is outside version control in
`.artifacts/local-switch-20260905/`: original scheduled-task XML/runtime identity,
preflight/cold manifests, isolated-copy verifier, Local bootstrap and ROLLBACK.md.
Cold manifest SHA256:
`8de8d943b0dcbd543085f56730551843f2af48c1e8b2ca9b09d6e5f92023fde9`.
No private data, keys, database dump or full task XML is shipped in Git.

Before another Local restart, recheck no active execution and exact owned PID
tree; stop only that scheduled task/server/worker. Update only the clean detached
runtime checkout to the next tested commit. Retain original data and avoid two
queue writers. Code rollback restores the original launcher; full-state rollback
also requires preserving later owner writes before restoring the checked copy.
Never use a Preview root as an owner-data source.

Next safe step: owner click-through of active Local, then the separate ordinary
registration/device/key path and real multi-user Memory sharing/revocation.
Permanent Social publishing requires the owner's exact preview confirmation.
These do not block inspection of the working integrated checkpoint.
New Router/Execution V2, autonomous routines and an Agent World PostgreSQL adapter
are not implemented; their reviewed slices and stages 0–13 remain open.
No merge or release follows from Local PASS.

`IMPLEMENTATION COMPLETE: YES` for the completed SF Chat dialogs and integrated
2b6d0112 owner-review slice described above;
`IMPLEMENTATION COMPLETE: NO` for the full Agent World program/acceptance.
`GIT CLOSEOUT COMPLETE: YES` for code 2b6d0112 (pushed, draft PR, exact-code CI PASS);
this operational evidence is a documentation-only follow-up in the same PR.
`STAGE CLOSED: NO`; owner visual acceptance and release stages remain distinct.
