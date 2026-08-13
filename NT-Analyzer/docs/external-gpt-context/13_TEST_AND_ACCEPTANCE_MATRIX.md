# 13. Test and Acceptance Matrix

- Context Pack document: 13_TEST_AND_ACCEPTANCE_MATRIX.md
- Last verified UTC: 2026-08-13T09:49:37Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
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
| Operational release closeout | accepted deployment/build/browser/readiness evidence | current Canary: [2026-08-13 snapshot](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md); current Production: [2026-08-12 snapshot](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) | required to answer “what is live now” per environment |

Current clean-branch closeout result: targeted acceptance `259 passed`; full
pytest `1303 passed, 31 skipped, 0 failed`; repository harness `13/13` suites;
static/context/compile/JS/shell/diff gates PASS. The skips are the live
PostgreSQL groups `test_production_storage.py` (`11`),
`test_production_workers.py` (`12`) and `test_stage8_postgresql.py` (`8`), gated
by `STRATFORGE_TEST_POSTGRES_ADMIN_URL` and `STRATFORGE_TEST_POSTGRES_URL`.

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
| Market-data visual and higher-load acceptance | DEV PASS on `7ebda6fa`: 619.899-second independent in-app/Chrome MNQ/MES marker proof and prior 100-client fanout baseline. Authenticated Canary/Production provider smoke remains external | [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |
| Canary / Production release acceptance | Canary core PASS WITH EXTERNAL BLOCKERS for `7ebda6fa`; Production unchanged on accepted `6b6dc458` pending separate owner approval | [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |

Operationally accepted does **not** mean every adjacent provider is ready:
Canary Telegram remains `PARTIAL` until the owner-login hotfix is redeployed and
verified, and Google/email auth remain `EXTERNAL BLOCKED`
in Production.

## Browser E2E note

The workspace `AGENTS.md` explicitly avoids automatic in-app browser testing for
local pages unless the owner asks for it. Treat authenticated browser E2E and
visual QA as targeted manual or explicit-owner actions, not a default automated
gate.
