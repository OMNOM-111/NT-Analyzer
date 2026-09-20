# Agent World — implementation status

Canonical program status: `IN DEVELOPMENT`. This is the single current handoff.
The checkpoint contains separate **synthetic Preview** and **explicit real Local
owner** integration paths. It is not completion of all stages 0–13 and not a
Canary/Production release. Local automated verification and synthetic browser
checks passed; real chat/NT/Desktop end-to-end and owner visual acceptance remain open.

## Source, runtime and dependencies

| Field | Fact |
| --- | --- |
| Accepted Unified Local | `4ae766ea0c3258a8bb049644ac2afbba6cb89330`, beta.96; open [PR #280](https://github.com/OMNOM-111/NT-Analyzer/pull/280) |
| Foundation dependency | `d5d07ac6817cd10f57d916dab0ce655347a8cbde`; open [PR #281](https://github.com/OMNOM-111/NT-Analyzer/pull/281) |
| Current branch / worktree | `codex/agent-world-owner-preview` / `StratForge-worktrees/agent-world-owner-preview` |
| Implementation source | Code commit `fc78677dfa258fb56042866a6764e8c8a45c42e6`; subsequent documentation-only closeout records the checks; draft [PR #282](https://github.com/OMNOM-111/NT-Analyzer/pull/282), base `codex/agent-world-foundation` |
| Local version | `0.10.0-beta.96`, unchanged; no release version assigned |
| Existing owner runtime | Read-only observation: port 8765 serves beta.93, SHA `7062f749ee92299356c774d01dc0c7b59cdcbba3`, dirty Development, authenticated owner |
| Synthetic review runtime | Separate loopback Preview child from this checkout; synthetic data root, cookies and external-effect guard; does not replace port 8765 |
| Real Local runtime handoff | New checkout path implemented but not switched onto 8765; owner answer permitting that switch is pending |
| Repository migrations | No new numbered migration; sequence still ends at `0022` |
| Release | No merge, signing, Canary/Production access, deployment or secrets/DB changes |

The running owner server is **not** the beta.96 accepted checkout. It was not
restarted or silently upgraded. Exit Preview returns to that unchanged full
owner Local. Its observed identity must not be reported as beta.96 acceptance.

The owner authorized a clickable checkpoint and then explicitly requested real
historical NinjaTrader tasks and a Desktop chart snapshot through the existing
chat. [ADR-0010](../adr/0010-agent-world-owner-review.md) remains the decision
record for the isolated synthetic slice. The additive
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md) defines the real-owner path;
it does not relax Preview isolation or approve a Local process switch, broader
production contracts or migration rollout. Work does not enter PR #280 or #281;
neither dependency is merged by this task.

Desktop source plans/images are unchanged. Their `c9b2883` snapshot is
historical. See the [pre-foundation archive](../archive/AGENT_WORLD_PRE_FOUNDATION_CONTEXT_2026-09-04.md)
and [completed foundation checkpoint](../archive/AGENT_WORLD_FOUNDATION_CHECKPOINT_2026-09-04.md).
Neither archive is a second current status.

## Current product contract

The implemented AI Center has exactly three tabs: **Overview / Work / Agents**
(«Обзор / Работа / Агенты») and a task-detail drawer. Decisions, Memory,
Experiments, Models and System are not additional active tabs in this checkpoint.
One conditional rail entry replaces AI Lab / AI Agents only after admission to
one of the two paths below. Existing research links and legacy URLs remain;
there is no new research UI or general natural-language coordinator.

### Real Local owner path — IN DEVELOPMENT

- An explicitly enabled Development owner workspace can submit a registered
  historical backtest through SF Chat or the narrow AI Center API. Tolik is its
  visible persona; **NinjaTrader Strategy Analyzer is the executor**, not an LLM.
- `live_backtests.py` calls the existing `jobqueue` authority. Stable task UUIDs
  project the original job IDs/statuses; no second job engine or live-task SQLite
  ledger is introduced. Only server-marked Agent World jobs belonging to the
  exact workspace, numeric compatibility user ID and fresh owner UUID are shown.
- The strategy, instrument, timeframe, date interval and parameters must be
  explicit and valid against existing catalogs/validators. Negative parameters
  and loss-making results are preserved. Queue admission is not success.
- The existing Chief monitor rechecks admission, verifies completed canonical
  reports and sends a replay-safe update into the originating SF Chat transcript.
  Missing, mismatched or changed evidence requires review; no synthetic fallback.
- Ivan can request a snapshot through the existing Desktop command queue. The
  real Desktop must be open, have bars and return a bounded PNG receipt for that
  command/conversation. The current chart view is preserved; there is no
  headless substitute or alternate market-data source.
- PNG structure, hash, scope, command correlation and bounded capture metadata
  are validated. This is an **authenticated Desktop canvas receipt**, not an
  independent visual attestation, proof of live quote freshness or LLM quality.
- Real task/report counts and evidence can be displayed. Model quality remains
  **NEW / unassessed**, with no invented score: `AI_EVALUATION_SHADOW` is OFF.
  Result verification is not strategy profitability certification or a rating.

This path is implemented in the new checkout but has not completed its real
chat/browser end-to-end acceptance. The running 8765 owner is still beta.93;
its existing manual reports must not be relabeled as Agent World activity.

### Synthetic Preview path — IN DEVELOPMENT

Three distinct fixed fixtures each execute four deterministic tasks: Marina
reconciles financial values, Tolik computes OHLC statistics, Nikita checks event
ordering and Ivan constructs an SVG from checked bars. Foundation
Intent/Task/Contribution/Outcome records, immutable artifacts, replay/resume and
independent deterministic checks are stored only in the disposable SQLite root.
Three distinct inputs yield n=3, low-confidence per-class shadow scores; replay
does not add samples. These scores never mix with real Local report counts or
become LLM rankings, market performance or Router weights.

Verified results and explicit browser-rendered chart PNGs can project into the
existing scoped AI conversation. The benchmark remains finite and synchronous;
it is not an autonomous workforce. Synthetic identity and external-effect
blocking remain intact, including Reset and Exit to full owner Local.

Both paths reuse existing zero-cost budget admission; neither implements paid
reservation/settlement or invokes a model provider. Neither sends Telegram or
publishes social posts. SF Social remains the user-visible social label, SF Chat
the messenger; compatible `community*` APIs and existing human/AI conversation
authorities are preserved.

## Stage coverage and remaining implementation gaps

| Plan area | Current implementation / limit |
| --- | --- |
| 0–1 baseline/contracts | Foundation preserved; Persona, Role, Provider Account and Model stay distinct; explicit legacy projections |
| 2 persistence | Preview SQLite CAS/history/events/idempotency/outbox and private hash-checked artifacts; real Local reuses original jobs, Desktop receipts and SF Chat; PostgreSQL/RLS/migrations and outbox delivery worker remain gaps |
| 3 server facade | Separate Preview and exact-opt-in real Local owner composition over existing auth/device/permission/CSRF/budget gates; not general multi-user API rollout |
| 4 navigation/UI | Exactly Overview/Work/Agents plus task drawer; legacy links retained; owner design acceptance pending |
| 5 task graph | Bounded fixture state machines and projections of explicit real backtest/desktop requests; no general natural-language coordinator |
| 6 routing | Existing Router unchanged; new Router flag OFF |
| 7 personas | Four fixture personas; Tolik/NinjaTrader and Ivan/Desktop in real Local; no custom editor or provider-identity conflation |
| 8 evaluation | Synthetic-only n/low-confidence shadow scores; real execution evidence with quality NEW/unassessed, evaluation flag OFF; no production learning |
| 9 consensus/Court | OFF; no invented decisions/verdicts |
| 10 execution | `AI_EXECUTION_V2` OFF; existing historical NT jobs and Desktop command queue reused by explicit owner request; no trades, terminal execution, Connector refactor or new engine |
| 11 memory/routines/calendar | OFF/unimplemented; task evidence is not promoted to shared memory |
| 12 integrations | Real/synthetic result and PNG projections remain separate in existing SF Chat; real end-to-end acceptance pending, social publishing OFF |
| 13 cutover/release | Not closed; owner review, broader implementation, Git/CI and release gates remain distinct |

Backtesting page/engine redesign remains a separate workstream. The real Local
slice integrates its existing historical job/report pipeline; it does not claim
to finish that redesign. The overall program stages 0–13 are **NOT CLOSED**.

## Isolation, flags and shared ownership

All ten flags default OFF in the single `flags.py` registry. Trusted server
composition creates audited environment **and exact workspace** snapshots;
browser/localStorage/query values do not grant flags or authority.

| Flag group | Ordinary Local / remote | Admitted real Local owner | Controlled synthetic Preview |
| --- | --- | --- | --- |
| Read model, AI Center UI, task graph | OFF | ON | ON |
| Evaluation shadow | OFF | OFF | ON |
| Router shadow, consensus, Court, execution V2, memory, social publishing | OFF | OFF | OFF |

Real Local requires the explicit server environment setting
`STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES` with exact `ws_*` identifiers. Empty,
malformed or wildcard configuration fails closed. It applies only to Development
and is rejected inside Preview. Each action uses the existing authenticated
owner context, confirmed browser device or established trusted `source=local`
entry, current active owner UUID, active owner workspace and owner membership,
existing `ai_lab`/`backtesting` capabilities, permissions and budget admission.
Longer operations and monitor delivery recheck these authorities; no master code,
new login or second permissions/budget system is added.

Preview separately requires its owner-issued control cookie, confirmed current
synthetic session, active membership, professional ai_lab access, role, trial and
zero-cost budget. Private artifacts/projections are scoped to environment,
workspace and user. Reset holds the existing child lifecycle lock until SQLite
operations close and then clears only synthetic data. Exit never replaces or
reduces the owner runtime. Uncontrolled Preview, non-owner Local, Canary and
Production cannot use either new action path.

| Shared files / area | Writer / handoff |
| --- | --- |
| `server.py`, `permissions.py`, `api.js`, `ui.js`, `chief_agent.py`, `preview_sandbox.py`, live/Preview gateway/facade and integration tests | Root integration workstream, single writer |
| This status, main owner-review changelog, ADR-0011 and ADR index | All delegated handoffs received; root owns integration/final evidence and External GPT Context Pack |
| SQLite repository / codec / storage contracts | Storage workstream; integrated commit `7d2400b9`; reviewed by root |
| AI Center HTML/CSS/JS / presentation contracts | UI workstream; integrated commit `289675b7`; root owns integration follow-ups |
| Local benchmark / evaluation / real-backtest adapters and workflow tests | Workflows workstream; initial integrated commit `06c711ec`; bounded live follow-ups reviewed by root |
| Auth/devices/Social/Chat/Preview | Accepted beta.96 behavior remains regression contract; changes only at named integration boundaries |
| Market-data engine, chart engine, Connector, jobqueue, trading | No refactor; verify unchanged against accepted base |
| `assets/pages/desktop.js` | Explicit additive exception: PNG capture metadata/receipt and ACK integration only; baseline hash changes, rendering/provider/view behavior is not redesigned |
| PostgreSQL migrations, permissions catalogs, paid budget ledger and job engine | No new implementation or numbering in this checkpoint |

Do not use a persona name as model provenance. Runtime/model identity is omitted
unless authenticated infrastructure supplies it.

## Verification and closeout

Local automated integration verification is **PASS**, with 44 explicit skips.
Real chat/NT/Desktop and owner visual acceptance are not included in that PASS.
The [main change record](../changelog/2026-09-04-agent-world-owner-review.md)
retains earlier debugging evidence rather than treating an older green subset
as verification of the latest live integration. Scoped gateway checks passed
77 tests; with live backtests/Preview identity/subscription retry, 136 passed;
with existing Chief/Router/SF Chat, 205 passed. These are intermediate focused
results, not the final combined regression.

| Evidence | Observed result / limit |
| --- | --- |
| Existing owner manual historical job `ui_20260905T003301149Z` | Actual NinjaTrader result, 1273 bars and 64 trades; service-level verification passed with `reasons=[]` |
| Agent World ownership of that job | Not an Agent World origin; deliberately excluded from new task/agent statistics; no metadata backfill to make a demo look live |
| Fresh SF Chat → Agent World → NinjaTrader → same SF Chat | PENDING; requires a new chat-created, scoped real job after approved Local handoff |
| Real Desktop command → browser PNG receipt → SF Chat/drawer | PENDING; contract tests do not replace the live browser pipeline |
| Synthetic browser checkpoint | PASS: three explicit fixture runs, 12 completed tasks, four personas with n=3/low-confidence synthetic checks; profile/task drawer, rendered PNG in SF Chat and all three main tabs inspected |
| Exit Preview → existing owner Local | PASS in browser: returned to unchanged beta.93 / 8765, owner account and balance, online NinjaTrader state and original reports; no synthetic data substituted |
| Full regression | `3369 passed, 44 skipped`, 428.67 s; legacy runner `13/13` suites PASS |
| Static/context/bundle | Python app/tools/tests compilation, repository-root-configured secrets/platform-values/Markdown, context validation and diff checks PASS; exact 517-file bundle passes static/runtime-read/Python/JavaScript gates |
| Dispatched branch CI | [Run 33937601902](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33937601902), tested SHA `b05ee124caf652c77689fd749cd9eadc8265d564`: 3/3 PASS; Linux 3372 passed/41 skipped, Windows 3369 passed/44 skipped; static gates PASS |
| Independent bounded final review | No actionable findings in Local gateway/facade and server/Chief authority boundaries; read-only, no runtime changes |
| Owner visual/design acceptance | PENDING |

Inherited (not re-run claims): accepted Preview focused 173/full 2680 + 44 skipped;
foundation focused 654/full 2901 + 44 skipped, legacy 13/13, bundle 496.
See [Preview closeout](../changelog/2026-09-04-beta96-visual-audit-and-first-device.md)
and the archived foundation checkpoint.

`IMPLEMENTATION COMPLETE`: YES for the bounded synthetic owner-review checkpoint;
real adapters are implemented and automated-tested, but real end-to-end acceptance remains PENDING.
`GIT CLOSEOUT COMPLETE`: YES for this draft review checkpoint: code committed and
pushed, PR #282, branch CI 3/3 PASS on `b05ee124`, clean worktree verified. This
documentation-only evidence follow-up is not misrepresented as the CI-tested SHA.
Main-target checks are absent on this stacked base, not PASS; no merge approval.
`STAGE CLOSED`: NO for the overall program; owner visual acceptance remains open.

The latest 44 full-suite skips are not PASS: 41 credentialed PostgreSQL cases
without separate test DSNs, 2 shell cases and 1 POSIX permissions case on Windows.
The actual skip summary was inspected after the final run. No Production
database is used to satisfy tests. Paid-model/quality, remote Connector/exchange
and trading acceptance are not established by a local historical report.

## Rollback and next safe step

Until an approved switch, 8765 continues serving the old owner checkout. Exit the
disposable Preview and leave Local opt-in absent to retain current behavior.
Preserve existing owner data, reports, secrets and settings in place; never use
the Preview launcher/root as a substitute for owner Local.

A future approved handoff must independently bind the new code root and existing
owner data root, retire only the exact old Local supervisor/backend/worker, avoid
a second writer and retain the original launcher for rollback. The standard
supervisor `--development-profile` currently derives data from the code checkout;
merely exporting an older root before that command does not preserve it. No
ready one-command rollback or backward-data migration is claimed here. Returning
to beta.93 code after beta.96 writes is a separate compatibility check, not proof
that restoring a process also restores data.

The accepted code rollback references remain `4ae766ea` and foundation
`d5d07ac6`; the running-owner reference is separately `7062f749`. No numbered
shared schema migration is added. Any code rollback is a reviewed commit or
launcher operation, never a destructive reset of user work; preserve synthetic
evidence unless the owner explicitly resets that Preview.

Next safe step: only after explicit owner approval switch
Local, run a fresh real SF Chat backtest and Desktop capture, then obtain visual
acceptance of the populated three-tab UI. Dependency merge, broader stages,
Canary and Production remain separately authorized gates.

Canonical verification/change record:
[Agent World owner review](../changelog/2026-09-04-agent-world-owner-review.md).
