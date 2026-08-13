# 0.10.0-beta.1 — final acceptance Canary snapshot

Дата проверки: `2026-08-13` UTC. Этот снимок фиксирует фактический результат
финального hardening/acceptance без Production promotion. Production не
изменялась.

## Release identity

| Поле | Значение |
| --- | --- |
| Version / channel | `0.10.0-beta.1` / `beta` |
| Artifact Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` |
| Build ID | `sf-0.10.0-beta.1-7ebda6faf2e7-20260813T093530Z` |
| Archive SHA256 | `AFBCEADF571A925AED91D959B5AE9AF8E8B14207E4A27FACE5C6CE73386E4782` |
| Manifest/runtime artifact SHA256 | `CE09030A2050CBF7D2BCE985D90E36D0C0294F298178B862F4AFBDB0C3D351D3` |
| Signature | `verified`, `ECDSA_P256_SHA256_RAW`, trust tier `production` |
| Candidate / artifact | `rc_3be66a74f97d4c62b491ac071bd981ed` / `art_4ef7bbcc95c34fd7a80b184a441e6bc1` |

## Canary result

- Release Center выполнил реальную server-side сборку из чистого выбранного
  commit, повторную проверку подписи и immutable deployment через adapter
  `stage9_ssh`.
- Canary `https://canary.stratforges.com` показывает `[CANARY]`, exact Git SHA и
  build ID выше; `/api/health/live` и `/api/health/ready` возвращают `200`.
- Blue-green stages `prepare_green`, `expand_migrate`, `start_green`,
  `green_readiness`, `drain_blue`, `switch_traffic`, `verify_live` и
  `contract_migrate` завершились `pass`.
- Реальная rollback-репетиция переключила Canary на previous
  `de7acaedd9301b0b1f9a88ccf6f320316a68d881`, проверила его и вернула Canary на
  `7ebda6fa`; `rollback_verified=true`, `re_promoted=true`,
  `online_safe=true`.
- После репетиции `canary-current` указывает на
  `0.10.0-beta.1-7ebda6faf2e7`, `canary-previous` — на
  `0.10.0-beta.1-de7acaed`.
- Безопасная Canary HTTP-нагрузка: 10/50/100 клиентов, соответственно
  30/150/300 запросов к `/live`, `/ready` и UI; `0 failed`. Для 100 клиентов:
  p95 `/live` `1258.94 ms`, `/ready` `1115.79 ms`, UI `1260.17 ms`.
- Live DB ACL audit: `stratforge_app -> stratforge_canary CONNECT=false`,
  `stratforge_canary_app -> stratforge_production CONNECT=false`; обе роли
  сохраняют доступ к своему окружению.

## Automated closeout gates

- Targeted market-data/chart, governance/docs and release/rollback suite:
  `259 passed`, `0 failed`.
- Full `python -m pytest -q`: `1303 passed`, `31 skipped`, `0 failed`.
- `python -m tests`: `13/13` repository suites passed.
- `release_static_scan --scan all`, External GPT Context validator,
  `compileall`, explicit `py_compile` for all `382` tracked Python files,
  `node --check` for all `32` tracked JavaScript files, `bash -n` for all `6`
  tracked shell scripts and
  `git diff --check`: PASS.
- The `31` skips are the explicitly environment-gated live PostgreSQL groups:
  `test_production_storage.py` (`11`), `test_production_workers.py` (`12`) and
  `test_stage8_postgresql.py` (`8`); they require
  `STRATFORGE_TEST_POSTGRES_ADMIN_URL` and `STRATFORGE_TEST_POSTGRES_URL` and
  were not redirected to Canary or Production databases.

Canary core acceptance: **PASS WITH EXTERNAL BLOCKERS**. В Release Center
отдельно записаны `blocked`:

- Canary Telegram — `disabled_pending_canary_bot_provisioning`;
- authenticated Canary TopstepX/chart session — требует реальной Canary owner
  authentication; сессия не фабриковалась.

## Development chart and market-data evidence

NinjaTrader оставался `OFF`. На clean artifact commit независимые in-app и
Chrome клиенты одновременно показывали MNQ 5m и MES 5m в течение `619.899 s`:
`44` chart observations, `0` non-live/OFF/grey states.

- Provider: `topstepx`; connection was `LIVE` throughout the moving-price
  samples. At the final unchanged-price sample the provider summary briefly
  reported `AUTHENTICATED`, while the quote heartbeat stayed fresh,
  `external_live=true`, `price_marker_live=true` and both rendered labels
  remained colored/live rather than grey or `OFF`.
- Stable two-browser sample `2026-08-13T09:31:15.956Z`: MES
  `raw=ws=bar=7780.75`, rendered `7,780.75`; MNQ
  `raw=ws=bar=29843.00`, rendered `29,843.00`.
- Реально загружены cache-busted `api.js?v=20260812-final-acceptance2`,
  `chart-engine.js?v=20260811-live-marker-reconnect1` и
  `desktop.js?v=20260813-live-marker-freshness1`; service-worker controller
  отсутствовал.
- Большой layout и shared upstream fanout были проверены до release cut;
  exact-artifact soak повторно подтвердил независимый второй браузер. Ни один
  из hardening fixes не менял TopstepX auth/session,
  SignalR, rollover, cache/failover или backend chart rendering architecture.

## Production boundary

Production не развёртывалась, не переключалась и не откатывалась. Она остаётся
на Git `6b6dc4589407855526cf6cc345376d64cf95200e`, build
`sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256
`272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`;
Production previous — `0.10.0-beta.1-795db0c1`.

Promotion `7ebda6fa` в Production требует отдельного явного ответа владельца.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-13T09:49:37Z | GPT-5.5 через Codex по запросу owner | Recorded exact mission-led Documents artifact, 619.899-second market-data soak, Canary load/rollback acceptance, external blockers and unchanged Production boundary.
-->
