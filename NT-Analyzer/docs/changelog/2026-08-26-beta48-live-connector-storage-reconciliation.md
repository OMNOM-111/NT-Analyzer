# beta.48 — Production LIVE Connector storage reconciliation

Дата closeout: `2026-08-26T18:48:02Z`.

Статус: **ACCEPTED / PRODUCTION LIVE**.

## Release identity

| Field | Value |
| --- | --- |
| Version | `0.10.0-beta.48` |
| Artifact Git SHA | `ae9c5c913e4a3250dd978ce2bf682e52590e82ef` |
| Build ID | `sf-0.10.0-beta.48-ae9c5c913e4a-20260826T181306Z` |
| Candidate | `rc_f4554de031954dca87bff3b2c54cfa0e` |
| Artifact | `art_dba8625e0b3b427896f8d1ead2382fa2` |
| Archive SHA256 | `B9C56184222AE4DADF6C979949A7FEC6A31F23D6048663425DD0BBCD69894E97` |
| Runtime/manifest SHA256 | `F7856E1EFEEEC6CDACECA48DB4851FFEA9F59CE31F90BEFE6BCAD6ABF6787ED6` |
| Signature | `verified`, production trust tier |
| Canary deployment | `dep_a5abb0353395450889ff3d1013dc9050` |
| Canary acceptance | `chk_4e9892b9c99d464ea3b8560217269aa5`, final PASS |
| Production deployment | `dep_e955efac5b1a4d189ba3b6b521aa8bd4`, `production_live` |

Canary и Production указывают на один release directory:
`production_data/releases/0.10.0-beta.48-ae9c5c913e4a`. Оба окружения
сообщают один Git SHA, build ID и runtime artifact SHA256. Production previous
и rollback slot — `0.10.0-beta.47-a40367fe8027`. Пересборки между Canary и
Production не было; pending migrations — `0`.

## Reproduced Production failure

Существующий Connector на VMNINJA доходил до
`POST /api/connector/v1/challenge`, но beta.47 возвращала
`503 storage_constraint`. Расширенный refusal audit назвал точное ограничение:
`sf_connector_installations_workspace_id_fkey`.

Production schema была полностью применена через migration 18. Причиной была
не отсутствующая миграция и не устройство. Авторитетный Connector JSON
намеренно сохранял terminal history: revoked test installation с уже удалённым
workspace/user/membership, 51 завершённую session и 8 завершённых command с
удалённым actor. Каждый обычный challenge перепроецировал весь документ в
таблицы с FK, поэтому один исторический orphan блокировал запись действующей
installation.

## Root-cause correction

PR [#182](https://github.com/OMNOM-111/NT-Analyzer/pull/182), merge
`51bf8705ea213940f046b888be371fb476cc0229`, изменил только relational mirror
reconciliation:

- авторитетный JSON и terminal audit/history не удаляются;
- из constrained mirror не проецируются только revoked installation и
  expired/revoked/superseded session либо terminal command, ссылки которых уже
  отсутствуют;
- любой orphan в non-terminal состоянии по-прежнему блокирует write
  fail-closed;
- enrollment, device key, TopstepX, SignalR, chart history/realtime,
  cache/failover и rendering не менялись.

Regression воспроизводит Production shape вместе с первым реальным FK и
доказывает, что валидные live rows сохраняются, а non-terminal orphan не
разрешается. PR #182 и release identity PR
[#183](https://github.com/OMNOM-111/NT-Analyzer/pull/183) прошли обязательный
CI `5/5`.

## Live acceptance

Существующая installation `inst_9rVbadz0rNu0xlbbfsVSnkvY` восстановилась без
нового enrollment:

- `18:17:20Z` — `challenge_issued`;
- `18:17:21Z` — `signed_hello_accepted`;
- `18:17:22Z` — `market_data_ingested`;
- первая активная session последовательно выросла `24 → 34 → 38`, затем до
  sequence `114`; heartbeat и last-seen оставались свежими;
- installation и normalized mirror имеют `status=online`, Connector
  `0.4.2-dev.6`, NinjaTrader `8.1.8.2`, environment `production`;
- после штатного 15-минутного TTL сервер дважды ответил ожидаемым
  `session_expired`; Connector за три секунды автоматически выполнял новый
  challenge/hello. Вторая session достигла sequence `113`, третья была active
  с sequence `5` и heartbeat `18:48:01Z`;
- новых `storage_constraint` или иных unexpected refusals после beta.48
  `production_live` — `0`.

Последний beta.47 refusal в `18:16:20Z` предшествует переключению Production
на beta.48 в `18:16:37Z`. Connector market-data ingest сохранил MES 09-26 1m
snapshot; его source timestamp был старым, поэтому stale state остался честным
и не был искусственно помечен live.

## Verification

- full regression: `2033 passed`, `32 skipped`, `0 failed`;
- targeted storage/Connector: `131 passed`, `19 skipped`, `0 failed`;
- project runner: `13/13` suites;
- release/static, Python compile, 22 Aurora JavaScript syntax checks, CSP,
  secrets, Markdown, Context Pack and `git diff --check`: PASS;
- известные skips: real-PostgreSQL integration без test DSN и Windows
  bash-syntax check;
- Canary readiness и Production readiness: all reported checks PASS;
- Canary static JS assets byte-for-byte совпали с LOCAL beta.48; различие HTML
  ограничено внешней Cloudflare beacon injection.

Четыре Google/Resend secrets не изменялись. Public Connector distribution
остаётся отдельно `EXTERNAL BLOCKED` до появления разрешённого Authenticode
tool/material.
