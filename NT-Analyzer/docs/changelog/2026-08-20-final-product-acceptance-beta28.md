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

## First candidate stopped before acceptance

Первый merged candidate `rc_a69b6a24334a4373b3c21723a1bc1cf7` был
собран из `9ffbfb933c79b7661d5d38aed55f7a776f781422` и развернут только в
Canary. Live control-plane подтвердил Canary `live`, но корректно заблокировал
promotion: Release Center отправлял SHA transport ZIP
`5269426FDC98E23197B5E93BA742B0197E2DC3F81266A489BA0DC99CDCF0E588`,
тогда как запущенная среда сообщает signed runtime/manifest SHA
`1DB26A32F99F151F8FF654683D00886B7148020AB72E7FD4415060A54CC0F126`.

Candidate не принят и не продвигался в Production. Scoped correction сохраняет
оба digest, но сравнивает Environment Registry именно с runtime/manifest SHA;
новый commit требует новой сборки и повторного полного Canary cycle.

## Later Canary candidates stopped before acceptance

Runtime-digest correction из PR #137 прошёл CI и был слит как
`127619ac00fc984072aafa86bec548aeadae8c67`. Его Canary visual journey выявил
не runtime/auth/chart defect, а устаревшую формулировку CHARTER про обязательный
отдельный Canary bot. Формулировка исправлена в PR #138 без изменения auth или
market-data architecture; merge SHA —
`8865fad03fc48f520edc5fb8f6dcb816621cd5d9`.

Artifact этого SHA развернут только в Canary:

| Field | Value |
| --- | --- |
| Candidate / artifact | `rc_588fb3a60f6f4b1db73cd01b67979464` / `art_f16a697ac82a40ab8a9847b64db5dd98` |
| Build | `sf-0.10.0-beta.28-8865fad03fc4-20260821T015240Z` |
| Archive SHA256 | `8E2F55A85D731F35DE86FE80561F0511FD85DE8876F1BD24414460D1E921FE73` |
| Runtime/manifest SHA256 | `AD34896864941FFF472B5A910766E77592AF2612CABF4068A97F5FB2F001245C` |
| Canary state | `live`, `NOT ACCEPTED` |
| Production | unchanged beta.26 |

CHARTER body на Canary уже соответствовал artifact, но revision panel показывал
только synthetic `Редакция №1`: изолированный persistent data-root создавал
пустой `change_log.jsonl` и не подхватывал version-controlled ledger, хотя он
входил в тот же archive. Scoped correction идемпотентно добавляет только
отсутствующие canonical revisions по `version_id`/digest, сохраняет все
environment-local записи и не меняет auth, charts, TopstepX или release model.
Текущий Canary candidate не принят; после merge нужен новый immutable artifact
и полный Canary acceptance с последующим same-artifact Production promotion.

## Server-authoritative promotion blocker found in the real flow

Исправленный governance artifact из main merge
`2790fb43992d29439aa939dea9e972862592c652` был собран и развёрнут в Canary:

| Field | Value |
| --- | --- |
| Candidate / artifact | `rc_8ccdf242647f4230aa05ecb2343f6af0` / `art_523a1930527e4726b98baa4431ef56d0` |
| Build | `sf-0.10.0-beta.28-2790fb43992d-20260821T022511Z` |
| Archive SHA256 | `9944AC348F48F84E3B3D8E53473ADD338D3F2A7EB5B9FDFA1E849B96D7C01DE5` |
| Runtime/manifest SHA256 | `CFBE5BDE78E0AC755673706289C56CF6FD08D1BF7FE1D3DAE41C925A90E63398` |
| Canary acceptance | browser/Documents PASS; `release.canary_passed` записан |
| Production | unchanged beta.26 |

Canary chart soak длился `616 s` (`02:34:08Z` → `02:44:25Z`), 12 явных
срезов MES/MNQ дали 0 visual/live-contract нарушений. Raw TopstepX price,
последний bar close и rendered marker совпадали; marker оставался green/red и
при движущейся, и при неизменной цене. Краткий transport state
`AUTHENTICATED` сохранил свежие heartbeat/live-флаги и цветной marker, затем
вернулся в `LIVE`; history/watchdog/reconnect не сбросили отображение в OFF.

Реальный штатный шаг `approve-production → promote-production` выявил
state-machine defect: approval корректно переводит ledger из `canary_passed`
в `approved_for_production`, но authoritative server принимал только буквальное
`canary_passed` и поэтому блокировал следующий шаг. Scoped correction трактует
Canary acceptance как достигнутый milestone для последующих/retryable states;
ранние состояния по-прежнему fail closed. Добавлена регрессия для
`approved_for_production`, `production_scheduled` и `production_failed`.
Поскольку код изменён после Canary acceptance, этот artifact не продвигается:
после merge требуется новый immutable artifact и новый Canary cycle.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Редакция №1: создан canonical pre-release snapshot для final acceptance beta.28; финальные artifact и live evidence намеренно не предсказаны до deployment.
2026-08-21T00:53:04Z | GPT-5.5 через Codex по запросу owner | Редакция №2: зафиксирован fail-closed stop первого beta.28 candidate и scoped correction archive/runtime identity; Production не менялся.
2026-08-21T02:03:00Z | GPT-5.5 через Codex по запросу owner | Редакция №3: зафиксированы PR #137/#138, не принятый Canary artifact 8865fad0 и найденное расхождение isolated revision ledger; Production оставлен beta.26.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Редакция №4: зафиксированы Canary artifact 2790fb43, 616-секундный chart PASS и реальный blocker approved_for_production в authoritative gate; Production оставлен beta.26, требуется новый цикл.
-->
