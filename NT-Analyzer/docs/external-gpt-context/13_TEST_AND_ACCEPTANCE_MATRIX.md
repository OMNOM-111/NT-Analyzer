# 13. Test and Acceptance Matrix

- Context Pack document: 13_TEST_AND_ACCEPTANCE_MATRIX.md
- Last verified UTC: 2026-08-13T04:59:15Z
- Verified against Git SHA: cad53f682e413db86bc3a77e57f8942baf4d4bc3
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
| Operational release closeout | accepted deployment/build/browser/readiness evidence | [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) | required to answer “what is live now” |

## Targeted acceptance areas

| Area | What must be true |
| --- | --- |
| Auth / permissions | identity, capabilities and owner/global governance gates stay fail-closed |
| Environment isolation | DEV/CANARY/PRODUCTION do not share writable state or browser namespace by accident |
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
| Market-data visual and higher-load acceptance | still pending beyond current owner-accepted baseline | [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md) |
| Canary / Production release acceptance | PASS for the accepted `6b6dc458` / `0.10.0-beta.1` snapshot; future releases still require their own closeout | [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |

Operationally accepted does **not** mean every adjacent provider is ready:
Canary Telegram remains `PARTIAL`, and Google/email auth remain `EXTERNAL BLOCKED`
in Production.

## Browser E2E note

The workspace `AGENTS.md` explicitly avoids automatic in-app browser testing for
local pages unless the owner asks for it. Treat authenticated browser E2E and
visual QA as targeted manual or explicit-owner actions, not a default automated
gate.