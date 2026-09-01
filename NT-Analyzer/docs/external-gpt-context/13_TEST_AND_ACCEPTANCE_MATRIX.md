# 13. Test and Acceptance Matrix

- Context Pack document: 13_TEST_AND_ACCEPTANCE_MATRIX.md
- Last verified UTC: 2026-08-23T02:27:02Z
- Verified against Git SHA: 22ed7097b4ac9e863304197e118b1d3ce5109e8a
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
| Operational release closeout | accepted deployment/build/browser/readiness evidence | current beta.29 Canary+Production: [2026-08-22](../changelog/2026-08-22-market-data-responsive-release-beta29.md) | required to answer “what is live now” per environment |

Current beta.29 closeout result: targeted market/chart/Operations/responsive
`251 passed`; full pytest `1924 passed, 32 skipped, 0 failed`;
static/context/compile/32-JS/CSP/secret/Markdown/link/diff gates PASS. PR #142
passed all five mandatory jobs. Expected skips: 31 real-PostgreSQL checks
without their explicit test DSNs and one Windows bash-syntax check.

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
