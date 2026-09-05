# 13. Test and Acceptance Matrix

- Context Pack document: 13_TEST_AND_ACCEPTANCE_MATRIX.md
- Last verified UTC: 2026-09-05T02:03:44Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: fc78677dfa258fb56042866a6764e8c8a45c42e6
- Scope: Canonical test layers, release gates, acceptance and rollback expectations
- Status: DONE

## Main gates

| Gate | Scope | Canonical command / source | Current expectation |
| --- | --- | --- | --- |
| Static scan | CSP, secrets, markdown links | `python tools/release_static_scan.py --scan all` | must pass for code/docs closeout |
| External context validation | pack completeness, metadata, links, secrets, local-path leaks | `python tools/validate_external_gpt_context.py` | must pass when pack exists |
| Release smoke suite | repository-specific broad smoke runner | `python -m tests` | canonical short release gate |
| Full pytest | functional regression across repo | `python -m pytest -q` | canonical full automated suite |
| Python compile check | syntax-level regression | `python -m compileall -q app tests` | required in CI |
| JS syntax check | Aurora assets syntax | CI `node --check` over `app/static/aurora/assets/**/*.js` | required in CI |
| Operational release closeout | accepted deployment/build/browser/readiness evidence | historical beta.29 example: [2026-08-22](../changelog/2026-08-22-market-data-responsive-release-beta29.md); last recorded identity in [current system state](02_CURRENT_SYSTEM_STATE.md) | required to answer “what is live now” per environment |

Historical beta.29 closeout result (not current Agent World evidence): targeted market/chart/Operations/responsive
`251 passed`; full pytest `1924 passed, 32 skipped, 0 failed`;
static/context/compile/32-JS/CSP/secret/Markdown/link/diff gates PASS. PR #142
passed all five mandatory jobs. Expected skips: 31 real-PostgreSQL checks
without their explicit test DSNs and one Windows bash-syntax check.

## Agent World owner-review verification

Current slice results, explicit skips, browser evidence and source/PR identity
are maintained in [the canonical status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md)
and [change record](../changelog/2026-09-04-agent-world-owner-review.md).
They supersede neither historical release evidence nor the owner's design review.
Tests include SQLite isolation/CAS/replay, independent fixture checks, bounded
per-owner reads/runs, real Handler/CSRF/control admission, static page routing,
private artifacts, SF Chat replay recovery and Reset coordination.
Real-adapter tests additionally cover catalog/spec validation, actual report
schema/hash/count checks, foreign/manual job exclusion, actor/flag revocation,
queued-versus-terminal chat updates and no Telegram side effects. Desktop tests
cover current-view PNG capture, source/scope/command matching, parallel retry,
persist-before-publish recovery, missing artifacts and failed/expired states.
These disposable-data tests do not certify the live HTTP-to-NinjaTrader-to-chat
pipeline. The manual actual NT proof is separate; new live chat-created job and
Desktop canvas browser acceptance remain pending the approved Local switch.
Forty-one credentialed PostgreSQL tests and Windows shell/POSIX skips are not PASS.

Code `fc78677dfa258fb56042866a6764e8c8a45c42e6`: final Windows full run
**3369 passed, 44 skipped** in 428.67 s; legacy **13/13** suites; exact bundle
**517 files**, static/runtime reads/Python/JavaScript PASS. Root-configured
repository scan and context validator PASS. Synthetic browser checks observed
12 completed tasks, n=3/low-confidence per persona, rendered PNG in SF Chat and
Exit restoring the unchanged owner Local. No real Agent World E2E or release claim.

Dispatched [branch CI 33937601902](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/33937601902)
is **3/3 PASS** at exact SHA `b05ee124caf652c77689fd749cd9eadc8265d564`:
Linux **3372 passed, 41 skipped**, Windows **3369 passed, 44 skipped**, static PASS.
Main-target workflow checks are absent on this stacked PR and are not green.

## Targeted acceptance areas

| Area | What must be true |
| --- | --- |
| Auth / permissions | identity, capabilities and owner/global governance gates stay fail-closed |
| Environment isolation | DEV/CANARY/PRODUCTION do not share writable state or browser namespace by accident |
| Legacy isolation | current UI has no legacy/Mini App link, retired routes return HTTP 410, Legacy Viewer is loopback/read-only and leaves no background process after exit |
| Connector | protocol v1 signatures, nonces, capabilities and command/result safety remain intact |
| Market data | TopstepX-first read-only charts, provenance labels and fallback behavior stay honest |
| Release Center | immutable artifact identity, approval binding and blue-green step logic remain coherent |
| Rollback | rollback is explicit and evidence-backed; no destructive drop of current identity/release state |
| Documents/governance | markdown links, governance boundaries and this pack validator stay green |

## Manual / external acceptance that still matters

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
