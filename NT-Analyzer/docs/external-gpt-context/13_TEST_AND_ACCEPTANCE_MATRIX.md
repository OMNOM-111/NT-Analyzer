# 13. Test and Acceptance Matrix

- Context Pack document: 13_TEST_AND_ACCEPTANCE_MATRIX.md
- Last verified UTC: 2026-09-05T04:22:06Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 93bb1298f86f71ad950e2f7d737e6fe4bd421e3e (clean beta.96 runtime; Azure and single-dispatch recovery verified; result presentation/format follow-up under verification)
- Active Local 8765: clean `93bb1298f86f71ad950e2f7d737e6fe4bd421e3e`, build `dev-0.10.0-beta.96-93bb1298f86f`, original owner data, Preview=false
- Scope: Canonical test layers, release gates, acceptance and rollback expectations
- Status: IN DEVELOPMENT

## Current Local checkpoint — 93bb1298

Azure compatibility bd239e76 is preserved in the current clean Local 93bb1298.
Full **3925 passed / 44 skipped**, 187 focused, legacy 13/13 and staged/runtime
533-file bundles passed. Exact-SHA
[CI 33958551325](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33958551325)
passed Linux, Windows and static jobs. Anna's original owner Azure binding
returned CONNECTION_OK (2,235 ms; recorded cost $0.00005025); no key was copied.
Backtest/chat (5 messages) and genuine chart/chat (13 messages) survived restart.

The former synchronous/worker collision is fixed: original DeepSeek task
8d256003 resumed from its immutable receipt, without another provider call, and
case 86a650ab has one vote. Gemini task 484a0ad9 returned fenced JSON and failed
strict verification; its failed evidence is retained and no verdict is claimed.
Active 93bb1298 passed 3936 tests / 44 skips, 274 focused, legacy 13/13,
staged/runtime 533-file bundles and exact-SHA CI 33960694698 (3/3).
New result presentation/format work is under verification: stored Outcome DTO,
safe Inspector/SF Chat report links, MIME-aware files, legacy read-only rendering,
and explicit net/PF commission basis. New Court requests seal their plain-JSON
format instruction; old request identities/receipts and validators are unchanged.
The actual SF Social snapshot was reviewed without creating a post. Ordinary
registration/key and permanent publication remain owner actions. API, SQL,
permissions, budgets, Router and Execution V2 remain unchanged.
Presentation checkpoint: 610 focused and 3972 full PASS / 44 skips. A subsequent
manual Consensus check exposed incorrect candidate filtering; no proposal was
created from rejected tasks. The corrected owned/successful/same-input grouping
passed 319 focused tests; final full regression 3977 PASS / 44 skips, 954.04 s.
Static/context and exact 533-file staged bundle PASS; activation/browser and
new-SHA CI remain separate. Original rejection and source history are preserved.
See [canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

## Earlier scoped checkpoint verification

Historical ef4006eb: **3914 passed / 44 skipped**, 759.73 s, 218 focused, legacy
13/13, Python/23-JS/root/context/staged and runtime 533-file bundles PASS.
Exact-SHA [CI 33956017912](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33956017912)
passed all three jobs. Narrow Azure owner-binding follow-up: **3925 passed /
44 skipped**, 759.35 s, plus **187 focused**; exact-bundle/activation and actual Azure subsequently passed.
The 44 skips remain explicit; 41 have separate actual isolated PG evidence.
Three real comparisons passed, n=3/OBSERVED/low confidence, no routing effect.
Actual NT/chat/restart, project version, private Memory promotion, manual routine/
calendar and System checks passed. Actual PNG, saved failure recovery and corrected
ratings/calendar also passed on ef4006eb. Full Court, shared Memory/Social,
own-key and final owner acceptance remain open.

## Main gates

| Gate | Scope | Canonical command / source | Current expectation |
| --- | --- | --- | --- |
| Static scan | CSP, secrets, markdown links | from repository root: `python NT-Analyzer/tools/release_static_scan.py --scan all` | repository-wide scope must pass for code/docs closeout |
| External context validation | pack completeness, metadata, links, secrets, local-path leaks | `python tools/validate_external_gpt_context.py` | must pass when pack exists |
| Release smoke suite | repository-specific broad smoke runner | `python -m tests` | canonical short release gate |
| Full pytest | functional regression across repo | `python -m pytest -q` | canonical full automated suite |
| Python compile check | syntax-level regression | `python -m compileall -q app tests` | required in CI |
| JS syntax check | Aurora assets syntax | CI `node --check` over `app/static/aurora/assets/**/*.js` | required in CI |
| Exact artifact preflight | staged production bundle, runtime document reads, Python/JS syntax and bundle static scan | from `NT-Analyzer/`: `python tools/pre_release_check.py` | required before Git closeout; checkout-only PASS is insufficient |
| Operational release closeout | accepted deployment/build/browser/readiness evidence | historical beta.29 example: [2026-08-22](../changelog/2026-08-22-market-data-responsive-release-beta29.md); last recorded identity in [current system state](02_CURRENT_SYSTEM_STATE.md) | required to answer “what is live now” per environment |

Historical beta.29 closeout result (not current Agent World evidence): targeted market/chart/Operations/responsive
`251 passed`; full pytest `1924 passed, 32 skipped, 0 failed`;
static/context/compile/32-JS/CSP/secret/Markdown/link/diff gates PASS. PR #142
passed all five mandatory jobs. Expected skips: 31 real-PostgreSQL checks
without their explicit test DSNs and one Windows bash-syntax check.

## Agent World integrated Local verification

Current slice results, explicit skips, browser evidence and source/PR identity
are maintained in [the canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
and [integrated change record](../changelog/2026-09-05-agent-world-integrated-local.md).
They supersede neither historical release evidence nor the owner's design review.
Tests include SQLite isolation/CAS/replay, independent fixture checks, bounded
per-owner reads/runs, real Handler/CSRF/control admission, static page routing,
private artifacts, SF Chat replay recovery and Reset coordination.
Real-adapter tests additionally cover catalog/spec validation, actual report
schema/hash/count checks, foreign/manual job exclusion, actor/flag revocation,
queued-versus-terminal chat updates and no Telegram side effects. Desktop tests
cover current-view PNG capture, source/scope/command matching, parallel retry,
persist-before-publish recovery, missing artifacts and failed/expired states.
The integrated delta additionally tests fresh session leases/revocation and
read-only post-trial history; private model origin/DNS/TLS/DPAPI and budget
admission; actual model/application lineage and independent rubrics; scoped
Persona, Memory sharing/TTL/revoke, project revisions, manual follow-ups,
Consensus/Court isolation and explicit immutable Social snapshots. No mock
transport, contract assertion or HTTP 200 is actual provider/browser acceptance.

| Current delta check | Result | Limit |
| --- | --- | --- |
| Historical 34deb827 | **3906 passed, 44 skipped**, 770.01 s; exact-SHA CI 3/3 PASS | Superseded by ef4006eb; not a release |
| Historical ef4006eb | **3914 passed, 44 skipped**, 759.73 s; **218 focused PASS**, staged/runtime bundles and CI 3/3 PASS | Earlier counts and interrupted run remain historical |
| Azure owner binding bd239e76 | **3925 passed, 44 skipped**, 759.35 s; **187 focused PASS** | Staged/runtime bundle, activation, CI 3/3 and actual CONNECTION_OK PASS |
| Court dispatch 93bb1298 | **3936 passed, 44 skipped**, 1035.64 s; **274 focused PASS** | Staged/runtime bundle, activation, CI 3/3 and actual original-receipt recovery PASS; Gemini's fenced vote remained FAIL |
| Rejected-result delivery and rating | **134 and 147 focused PASS** | Includes wrong plan/wrapper/trading-action rejection, claimed-worker recovery with one provider call and retired/suspended/ambiguous active model cases |
| Actual isolated PostgreSQL 17.10 | **41 passed, zero skipped**, 122.71 s | TLS, non-superuser/NOBYPASSRLS roles, existing migrations 1–22 only; not an Agent World PostgreSQL adapter |
| Agent World domain/storage/social | **348 passed** | Disposable-data service/contract scope; no live model/publication claim |
| Session authority/history | **17 passed** | Disposable auth/device stores; final browser recheck remains separate |
| SF Chat delivery recovery | **NT RESULT / RESTART / SEALED REJECTION PASS** | Five backtest messages preserved; Gemini failure delivered once without a new provider call or evaluation change |
| Live ordinary-user provider | **PENDING OWNER REGISTRATION / KEY** | Final Terms waiting on localhost; then own confirmed workspace and OpenRouter wizard; no copied owner credentials |
| Actual owner providers / NT | **PARTIAL** | DeepSeek + Gemini CONNECTION_OK and three comparisons PASS; SF Chat/model/NT original report PASS, Z.AI unavailable and Gemini's noncanonical chart plan rejected |
| Domain/browser acceptance | **PARTIAL** | Projects, private Memory, routines/calendar, System, restart, ratings/local times, real Desktop PNG and Azure PASS; fresh Court/shared Memory/permanent Social remain pending |
| Static/context/bundle/CI | **93bb1298 PASS; FOLLOW-UP PENDING** | Historical ef4006eb/bd239e76 and active 93bb1298 exact-SHA gates PASS; result presentation/format delta has separate checks |

The 41 generic PostgreSQL skips are covered by the separate real isolated DB run.
Two shell checks and one POSIX permissions check remain unavailable on Windows;
those three are not Windows PASS. No Production DB or secrets are test fixtures.
Agent World domain storage itself is Development SQLite only and fails closed
outside Development; no new numbered migration or production repository is claimed.

Initial switch and clean ca505d83/34deb827/ef4006eb/bd239e76/93bb1298 activations passed
owner-data/copy/integrity checks. Presentation/format delta is not active yet. The manual NinjaTrader proof
`ui_20260905T003301149Z` contains 1,273 bars and 64 trades and remains excluded
from Agent World statistics. Fresh SF Chat/model job 62182839 passed with original
NT report and survived restart without duplicate messages. Three actual model
comparisons and initial domain actions passed. The first Gemini chart plan failed
strict verification, then a subsequent cold chart timed out. Another explicit
command produced the real PNG: 140/800 historical bars, same-chat report, OFFLINE.
Failures were not overwritten. Remaining Court/shared Memory/Social/private-key
checks are separate. See
[ADR-0012](../adr/0012-agent-world-integrated-local.md).

## Historical pre-model evidence

The [pre-model checkpoint archive](../archive/AGENT_WORLD_PRE_MODEL_CHECKPOINT_486DB834.md)
retains the earlier scope and browser/test evidence. For code
`fc78677dfa258fb56042866a6764e8c8a45c42e6`, the final Windows full run was
**3369 passed, 44 skipped** in 428.67 s; legacy **13/13** suites; exact bundle
**517 files**, static/runtime reads/Python/JavaScript PASS. Root-configured
repository scan and context validator PASS. Synthetic browser checks observed
12 completed tasks, n=3/low-confidence per persona, rendered PNG in SF Chat and
Exit restoring the then-unchanged owner Local. That beta.93 runtime was later
replaced by the approved clean beta.96 Local switch; this historical browser
evidence does not certify the new model/domain implementation or a release.

Dispatched [branch CI 33937601902](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33937601902)
was **3/3 PASS** at exact SHA `b05ee124caf652c77689fd749cd9eadc8265d564`:
Linux **3372 passed, 41 skipped**, Windows **3369 passed, 44 skipped**, static PASS.
This is historical CI, not final-delta evidence. Main-target workflow checks
are absent on this stacked PR and are not green.

## Targeted acceptance areas

| Area | What must be true |
| --- | --- |
| Auth / permissions | identity, capabilities and owner/global governance gates stay fail-closed |
| Agent World real application | stored SF Chat request → selected real model → independently checked exact plan → existing NT/Desktop authority → original verified receipt → same chat; a valid plan is waiting, not completed |
| Model/domain isolation | fresh confirmed session/membership/capabilities/budget, exact workspace flags, private models/artifacts and explicit live Memory grants; Preview cannot invoke real domain effects |
| Evaluations / Court / publication | independent observed rubrics, n < 3 NEW, three isolated advisory judges and 2-of-3 immutable verdict; exact snapshot/permanence approval before existing SF Social write |
| Recovery | persisted model/application result survives restart and failed chat delivery without another provider request; source cancellation is terminal only when its original executor confirms |
| Environment isolation | DEV/CANARY/PRODUCTION do not share writable state or browser namespace by accident |
| Legacy isolation | current UI has no legacy/Mini App link, retired routes return HTTP 410, Legacy Viewer is loopback/read-only and leaves no background process after exit |
| Connector | protocol v1 signatures, nonces, capabilities and command/result safety remain intact |
| Market data | TopstepX-first read-only charts, provenance labels and fallback behavior stay honest |
| Release Center | immutable artifact identity, approval binding and blue-green step logic remain coherent |
| Rollback | rollback is explicit and evidence-backed; no destructive drop of current identity/release state |
| Documents/governance | markdown links, governance boundaries and this pack validator stay green |

## Manual / external acceptance that still matters

The beta.29 PASS rows below are historical acceptance of those named release
surfaces, not acceptance of the current Agent World delta. Current Local gates
and remaining provider/browser work are recorded above.

| Area | Current status | Canonical evidence |
| --- | --- | --- |
| Backtest parity vs Strategy Analyzer | baseline passed; rerun after result-contract or execution-setting changes | [../operations/manual-validation.md](../operations/manual-validation.md) |
| Real Windows Connector acceptance | still required for Production-grade Connector confidence | [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md), [../../ANTIGRAVITY_STAGE9_HANDOFF.md](../../ANTIGRAVITY_STAGE9_HANDOFF.md) |
| Market-data visual and higher-load acceptance | PASS: 12-page/24-chart Development load with one upstream, authenticated Canary 36-chart + second client, authenticated Production two-client MES/MNQ + MNQ 15m. Closed-market heartbeat was used honestly; no moving raw-trade claim | [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md) |
| Responsive UI acceptance | PASS: 84/84 page/viewport checks, real mobile pointer journeys, and byte-identical Canary/Production smoke with zero whole-document overflow | [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md) |
| Canary / Production release acceptance | PASS: beta.29 merge `4d15f1d`, runtime `CBA4FA70…2379`, one signed artifact, Canary `dep_de0615…`, Production `dep_8716b7…`, no rebuild | [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md) |

Operationally accepted does **not** mean every adjacent provider is ready:
physical Windows Connector enrollment remains separate, cross-user market-data
redistribution remains `EXTERNAL BLOCKED`, and Google/email auth keep their
existing external gates.

## Browser E2E note

The workspace `AGENTS.md` explicitly avoids automatic in-app browser testing for
local pages unless the owner asks for it. Treat authenticated browser E2E and
visual QA as targeted manual or explicit-owner actions, not a default automated
gate.
The owner explicitly requested visual testing for this Agent World task; that
authorizes targeted browser checks, but does not make unperformed checks PASS.
