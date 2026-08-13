# 0.10.0-beta.1 — final acceptance Canary snapshot

Дата проверки: `2026-08-13` UTC. Этот снимок фиксирует фактический результат
финального hardening/acceptance без Production promotion. Production не
изменялась.

## Release identity

| Поле | Значение |
| --- | --- |
| Version / channel | `0.10.0-beta.1` / `beta` |
| Artifact Git SHA | `de7acaedd9301b0b1f9a88ccf6f320316a68d881` |
| Build ID | `sf-0.10.0-beta.1-de7acaedd930-20260813T081638Z` |
| Archive SHA256 | `E26747873949633C9CC6A66CEECD400CC035DF0F1CD71A079FA45EDCC541D867` |
| Manifest/runtime artifact SHA256 | `A2D17E51D4403C272A1F7A05DB1F2C346AE72B1459B7B8C9CC816836A29EF95F` |
| Signature | `verified`, `ECDSA_P256_SHA256_RAW`, trust tier `production` |
| Candidate / artifact | `rc_8c0369f31dff4cd689de596d32623987` / `art_f2a45e910229474587ee10d645b54879` |

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
  `6b6dc4589407855526cf6cc345376d64cf95200e`, проверила его и вернула Canary на
  `de7acaed`; `rollback_verified=true`, `re_promoted=true`,
  `online_safe=true`.
- После репетиции `canary-current` указывает на
  `0.10.0-beta.1-de7acaedd930`, `canary-previous` — на
  `0.10.0-beta.1-6b6dc458`.
- Безопасная Canary HTTP-нагрузка: 10/50/100 клиентов, соответственно
  30/150/300 запросов к `/live`, `/ready` и UI; `0 failed`. Для 100 клиентов:
  p95 `/live` `1288.37 ms`, `/ready` `837.39 ms`, UI `1005.53 ms`.
- Live DB ACL audit: `stratforge_app -> stratforge_canary CONNECT=false`,
  `stratforge_canary_app -> stratforge_production CONNECT=false`; обе роли
  сохраняют доступ к своему окружению.

## Automated closeout gates

- Targeted market-data/chart, governance/docs and release/rollback suite:
  `259 passed`, `0 failed`.
- Full `python -m pytest -q`: `1302 passed`, `31 skipped`, `0 failed`.
- `python -m tests`: `13/13` repository suites passed.
- `release_static_scan --scan all`, External GPT Context validator,
  `compileall`, explicit `py_compile` for `249` files, `node --check` for `32`
  JavaScript files, `bash -n` for four deployment scripts and
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

NinjaTrader оставался `OFF`. На clean artifact commit три браузерных клиента
(два in-app и отдельный Chrome) одновременно показывали MNQ 5m и MES 5m в
течение `689 s`: `32` chart observations, `0` non-live/OFF/grey states.

- Provider: `topstepx`; connection: `LIVE`; `external_live=true`;
  `price_marker_live=true`.
- MNQ raw range: `29838.25..29862.75`; MES raw range:
  `7778.50..7782.00`; для обоих были зелёные и красные live labels.
- Stable Chrome sample `2026-08-13T08:27:12.831Z`: MES
  `raw=ws=bar=7781.75`, rendered `7,781.75`; MNQ
  `raw=ws=bar=29861.50`, rendered `29,861.50`.
- Реально загружены cache-busted `api.js?v=20260812-final-acceptance2`,
  `chart-engine.js?v=20260811-live-marker-reconnect1` и
  `desktop.js?v=20260813-live-marker-freshness1`; service-worker controller
  отсутствовал.
- Большой layout, второй браузер и shared upstream fanout были проверены до
  release cut. Ни один из hardening fixes не менял TopstepX auth/session,
  SignalR, rollover, cache/failover или backend chart rendering architecture.

## Production boundary

Production не развёртывалась, не переключалась и не откатывалась. Она остаётся
на Git `6b6dc4589407855526cf6cc345376d64cf95200e`, build
`sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256
`272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`;
Production previous — `0.10.0-beta.1-795db0c1`.

Promotion `de7acaed` в Production требует отдельного явного ответа владельца.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-13T08:31:00Z | GPT-5.5 через Codex по запросу owner | Recorded immutable Canary artifact, browser/load/isolation acceptance, real rollback rehearsal, external blockers and unchanged Production boundary.
-->
