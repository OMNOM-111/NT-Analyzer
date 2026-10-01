# 13. Test and Acceptance Matrix

- Context Pack document: 13_TEST_AND_ACCEPTANCE_MATRIX.md
- Last verified UTC: 2026-10-01T01:27:27Z
- Verified against Git SHA: 91d8a4c1ac25f988b643ff71e119502a1df3d3f7
- Local source verified SHA: 2b6d0112bef88c5bfb73970de64ec5518443e56b (clean beta.96 runtime; real handoff/manual delivery and original report/PNG verified, exact-code CI PASS)
- Local verification UTC: 2026-09-05T19:05:43Z; pack-wide deployment anchor above remains historical, not a claim of new Production verification
- Current UI correction: [SF Chat dialog receipt](../changelog/2026-09-05-sf-chat-app-dialogs.md); existing backend/data/flags unchanged, no release
- Current program delta: [integrated review record](../changelog/2026-09-05-agent-world-program-review.md) — clean 2b6d0112 active; genuine report/PNG observations, real fact handoff and deduplicated manual SF Chat delivery verified; 4235/44 skipped full suite, 542-file bundles and CI 33984524477 3/3 PASS. Full-program/owner acceptance remains open.
- Active Local 8765: clean `2b6d0112bef88c5bfb73970de64ec5518443e56b`, build `dev-0.10.0-beta.96-2b6d0112bef8`, original owner data, Preview=false
- Scope: Canonical test layers, release gates, acceptance and rollback expectations
- Status: IN DEVELOPMENT

## Current program delta evidence

Final integrated focused gateway/model/follow-up/presentation subset: 267 PASS,
zero skipped, 278.92 s. Memory has 26 actual HTTP/SQLite tests with synthetic
ordinary cookie sessions (190 combined PASS); private/granted artifact access,
revocation/TTL/source supersession, foreign membership, device/session and CSRF
checks are not replaced by an owner fallback. This is not multi-human browser
acceptance. Real Azure handoff bf665c7e and both manual discussion receipts
passed on active 2b6d0112; repeated calendar delivery did not duplicate its
single message. The retained original report/PNG were reverified, not rerun.
Full Local suite: 4235 passed / 44 skipped; exact-code CI 33984524477: Windows
4235/44, Ubuntu 4238/41, static, 3/3 PASS. Exact staged/runtime bundles: 542 files,
PASS. Details belong to the linked integrated review operational closeout.
The interrupted pre-freeze full run is not PASS. Existing real historical NT/PNG
proof, synthetic provider fixtures and fresh live execution are separate layers.

## Previous verified model/domain checkpoint — aa54c294

At that previous checkpoint, clean Local 8765 ran `aa54c2940150e540d8b594dbf1d6254e172adbfd`, beta.96,
build `dev-0.10.0-beta.96-aa54c2940150`, original owner data, Preview=false,
live orders=false. The code is committed/pushed to draft PR #282; #280/#281
remain unmerged. Operational documentation may be newer than active runtime code.

Final full **3977 passed / 44 skipped**, 954.04 s; final focused **319 PASS**,
presentation focused **610 PASS**, legacy **13/13 suites**, root/static/context/
diff and exact staged/runtime **533-file bundles PASS**.
[Exact-code CI 33965039490](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33965039490)
passed Windows, Ubuntu and static, 3/3. No main-target or release PASS is inferred.

Actual browser acceptance on this SHA: stored application Outcome and original
report links in Inspector/SF Chat; same 64-trade NT report; genuine Desktop PNG
140/800 historical bars; preserved chats (5/13 messages); three Personas and
n=3 arithmetic observations for Tolik/Ivan, NEW for Anna. Consensus proposal
cf1464ab uses two accepted same-input contributions. Fresh Court ae0e5e45
received three real valid isolated votes (DeepSeek/Gemini/Azure) and approve;
old case 86a650ab retains its one vote and invalid Gemini response. No validator
was weakened and a verdict does not execute actions.
SF Social read-only preview e4853566… has net -969.7 and PF 0.7252 explicitly
after commission; no post or permanent confirmation was created.

`LOCAL VISUAL REVIEW AVAILABLE: YES`; the full program stays IN DEVELOPMENT.
Ordinary registration/device/key, real multi-user sharing/revocation, permanent
Social publication and owner design acceptance remain separate. New Router,
Execution V2, autonomous routines and an Agent World PG adapter are not implemented.
All ten flags default OFF; exact admitted Local workspace has eight paths ON,
Router/Execution V2 OFF. Preview has separate synthetic flags, no real side effects.
The earlier 93bb1298/other-SHA test and provider history is preserved in the
[canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md) and
[integrated changelog](../changelog/2026-09-05-agent-world-integrated-local.md).

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
| Integrated review 2b6d0112 | **Local and exact-code CI PASS** | Full 4235/44 skipped, 267 integrated focused, 542-file bundles, CI 33984524477 3/3; actual original NT/PNG, real Azure handoff, separate application observations and manual delivery/deduplication verified. Full-program/owner acceptance remains open |
| SF Chat in-app dialogs 95912cbf | **Local and exact-code CI PASS** | Full 4032/44 + final 62 dialog tests (seven added after collection), 352 focused, 534-file bundles and actual cancellation/navigation/focus browser checks PASS; CI 33970324754 3/3 PASS, fresh Windows 4039/44 and Linux 4042/41 |
| Historical 34deb827 | **3906 passed, 44 skipped**, 770.01 s; exact-SHA CI 3/3 PASS | Superseded by ef4006eb; not a release |
| Historical ef4006eb | **3914 passed, 44 skipped**, 759.73 s; **218 focused PASS**, staged/runtime bundles and CI 3/3 PASS | Earlier counts and interrupted run remain historical |
| Azure owner binding bd239e76 | **3925 passed, 44 skipped**, 759.35 s; **187 focused PASS** | Staged/runtime bundle, activation, CI 3/3 and actual CONNECTION_OK PASS |
| Court dispatch 93bb1298 | **3936 passed, 44 skipped**, 1035.64 s; **274 focused PASS** | Staged/runtime bundle, activation, CI 3/3 and actual original-receipt recovery PASS; Gemini's fenced vote remained FAIL |
| Rejected-result delivery and rating | **134 and 147 focused PASS** | Includes wrong plan/wrapper/trading-action rejection, claimed-worker recovery with one provider call and retired/suspended/ambiguous active model cases |
| Actual isolated PostgreSQL 17.10 | **41 passed, zero skipped**, 122.71 s | TLS, non-superuser/NOBYPASSRLS roles, existing migrations 1–22 only; not an Agent World PostgreSQL adapter |
| Agent World domain/storage/social | **348 passed** | Disposable-data service/contract scope; no live model/publication claim |
| Session authority/history | **17 passed** | Disposable auth/device stores; final browser recheck remains separate |
| SF Chat delivery recovery | **NT RESULT / RESTART / SEALED REJECTION PASS** | Five backtest messages preserved; Gemini failure delivered once without a new provider call or evaluation change |
| Live ordinary-user provider | **PENDING OWNER REGISTRATION / KEY** | Draft registration has expired/used email challenge; no completed ordinary account. Complete proof/consent/device/workspace before separate OpenRouter key. The empty owner wizard was inspected/cancelled without reading or copying credentials |
| Actual owner providers / NT | **PARTIAL** | DeepSeek + Gemini CONNECTION_OK and three comparisons PASS; SF Chat/model/NT original report PASS, Z.AI unavailable and Gemini's noncanonical chart plan rejected |
| Domain/browser acceptance | **PARTIAL** | Projects/private Memory/manual routines/calendar/System, restart, NT/PNG, ratings, Azure, same-input Consensus, three-model Court and read-only Social preview PASS; real multi-user Memory/permanent Social/own-key/owner acceptance pending |
| Static/context/bundle/CI | **aa54c294 PASS** | Full 3977/44, 319 final focused, 610 presentation focused, legacy 13/13 suites, root/static/context/diff, staged/runtime 533-file bundles and exact-SHA CI 33965039490 3/3 PASS |

The 41 generic PostgreSQL skips have separate historical isolated DB evidence;
they were not rerun against an actual DB for 2b6d0112 and are not fresh PASS.
Two shell checks and one POSIX permissions check remain unavailable on Windows;
those three are not Windows PASS. No Production DB or secrets are test fixtures.
Agent World domain storage itself is Development SQLite only and fails closed
outside Development; no new numbered migration or production repository is claimed.

Initial switch and clean ca505d83/34deb827/ef4006eb/bd239e76/93bb1298/aa54c294
activations passed owner-data/copy/integrity checks. Presentation/format and
Consensus corrections are active and browser-verified on aa54c294. The manual NinjaTrader proof
`ui_20260905T003301149Z` contains 1,273 bars and 64 trades and remains excluded
from Agent World statistics. Fresh SF Chat/model job 62182839 passed with original
NT report and survived restart without duplicate messages. Three actual model
comparisons and initial domain actions passed. The first Gemini chart plan failed
strict verification, then a subsequent cold chart timed out. Another explicit
command produced the real PNG: 140/800 historical bars, same-chat report, OFFLINE.
Failures were not overwritten. Fresh Court and read-only Social preview PASS;
real multi-user Memory, permanent Social and private-key checks remain separate. See
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
