# Final product acceptance — 0.10.0-beta.28

Дата начала closeout: `2026-08-20T23:00:44Z`.

## Release scope

Это финальный hardening текущего продукта, а не новый feature cycle.
Market-data, TopstepX, SignalR, chart realtime, rollover, cache/failover и
rendering остаются принятым baseline и не рефакторились.

Подтверждённые исправления:

- LOCAL release-control отклоняет неавторитетный responder, другой
  `candidate_id`, другой artifact, отсутствующий/некорректный срок и stale
  decision. Решение действительно не более 120 секунд.
- Production и Development test roots создаются отдельно для каждого теста;
  tracked governance baselines копируются в disposable root. Любое изменение
  живого `data/` делает suite красным.
- Удалена зависимость корректности двух GitHub Actions workflows от общего
  concurrency group.
- DEV sync-banner больше не утверждает, что незакоммиченные изменения точно не
  загружены процессом: это невозможно установить по Git. Перед release он
  требует clean commit и restart, не подменяя наблюдение догадкой.
- Обычный abort незавершённых browser requests при переходе между страницами
  больше не попадает в console как ложная UI-ошибка, включая Chromium-обёртку
  `signal is aborted without reason`.
- HTTP observability фиксирует фактически отправленный status. Второй
  `send_response` hook раньше оставлял fail-safe `500`, поэтому Operations
  ошибочно подписывал успешные `200` запросы как `5xx`.
- Большой chart layout теперь масштабирует единую виртуальную сетку под
  viewport. CSS minimum-размеры больше не заставляют соседние окна физически
  перекрывать меню timeframe, настройки и resize grips при 36 графиках.
- Legacy CI entrypoint `python -m tests` устанавливает две disposable roots до
  импорта suite/app modules. Его 13 custom suites больше не зависят от pytest
  `conftest` и не могут писать в live Production/Development data roots.

## LOCAL acceptance evidence

- `1910 passed`, `32 skipped`, `0 failed`; независимый SHA256 digest всего
  live `data/` совпал до и после полного suite:
  `B6AAB05A0B5F4ECC146E8B9364141737B505DC579D8C4AD5E2BD203AD8C65902`.
  Известные skips: 31 integration test без предоставленных real PostgreSQL
  acceptance DSN и 1 shell-syntax test при отсутствии `bash` на Windows.
- Отдельный release runner: `13/13 suites passed` (включая `93/93` AI Lab),
  тот же live-data digest до/после.
- В браузере загружены 12 основных пользовательских экранов и все 13 Admin
  modules; полезный DOM появлялся за `1.1–1.6 s`, console оставалась чистой
  после regression-перехода.
- Canonical owner: `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f`; live store содержит
  одного active owner и одну уникальную Telegram identity.
- При NinjaTrader OFF два одновременных browser WebSocket clients показывают
  MNQ/MES 5m из TopstepX; `lastPrice == last bar close == rendered marker`,
  `external_live=true`, marker остаётся green/red, browser WS `dropped=0`.
- Непрерывное наблюдение на clean `9e1e41769bb4` длилось `610.473 s`
  (`00:00:58.533Z` → `00:11:09.006Z`) и прошло границы 5m candles `00:05`
  и `00:10`; финальные raw/close/rendered значения были MNQ
  `29336.5 / 29336.5 / 29,336.50` и MES
  `7670.75 / 7670.75 / 7,670.75`.
- Большой layout реально смонтировал 36 charts с тремя browser clients:
  `dropped=0`, один upstream SignalR session, `loginKeyCalls=0`; геометрия на
  clean commit дала `overlaps=[]`, settings/timeframe hit-targets `36/36`.
  Реальные controls открыли settings drawer и переключили один chart 5m→1m.

## Operational state before beta.28

| Environment | Version | Git SHA | Build | Runtime artifact SHA256 |
| --- | --- | --- | --- | --- |
| Canary | `0.10.0-beta.27` | `1f3e2ce7198fec5a90e85d9b49e7a086103e4b62` | `sf-0.10.0-beta.27-1f3e2ce7198f-20260818T215207Z` | `A905E784BD2794F8ACC1760D1697A1B410FC96C24A5BCD25223B8D48FD2EC270` |
| Production | `0.10.0-beta.26` | `3353e3836306dca4628c759064139cdac94517e0` | `sf-0.10.0-beta.26-3353e3836306-20260817T230438Z` | `27B6316E934F0D727B9D158B34EE601A0A59EF78F0D71B484DD29ADD37617AAB` |

Обе среды отвечали `200` на `/api/live` и `/api/ready`; все readiness checks
были `ok/ready`. Это начальная точка, а не acceptance beta.28.

## Acceptance contract

Финальный operational блок добавляется только после реального прохождения:

`clean main SHA → mandatory CI → signed immutable artifact → Canary PASS →
same exact artifact Production → live recheck`.

До появления этого блока документ не является утверждением Production PASS.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Редакция №1: создан canonical pre-release snapshot для final acceptance beta.28; финальные artifact и live evidence намеренно не предсказаны до deployment.
-->
