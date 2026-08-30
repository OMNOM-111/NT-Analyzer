# Beta.29 — market-data fan-out and responsive acceptance

Дата Development-проверки: `2026-08-23T01:29:45Z`.
Дата release closeout: `2026-08-23T02:27:02Z`.

## Scope

Release-кандидат `0.10.0-beta.29` не меняет TopstepX authentication,
ProjectX SignalR protocol, rollover, history/cache/failover order или candle
rendering. Исправлены только воспроизведённые closeout-дефекты вокруг
существующего baseline:

- normal TCP reset при закрытии browser WebSocket теперь тихо освобождает
  ref-counted upstream lease, а не пишет server 500 traceback;
- consumer gateway не сохраняет поздний HTTP bootstrap ref, если реальный
  browser ref уже существует; после закрытия layout logical refcount возвращается
  к исходному значению;
- успешный gateway reconnect очищает исторический transport error;
- Production Telegram lease timestamps сериализуются в Operations JSON, а
  Worker/Telegram/Connector probes ограничены по времени и деградируют
  независимо вместо зависания всей панели;
- topbar, chart workspace, Admin navigation, Connector onboarding, Documents/
  Cabinet drawers, notices и Strategies kanban получили измеримые responsive
  границы без изменения пользовательских данных или desktop layout geometry.

## Development acceptance evidence

### Market data / charts

- NinjaTrader: OFF; TopstepX/gateway freshness: live.
- Load: три изолированных browser profile, по четыре страницы, 24 charts total.
- Instruments/timeframes: MES 5m и MNQ 15m.
- Peak: `browser_ws=14`, `logical=22`, `wire=2`, `signalr=1`.
- After close: `browser_ws=2`, `logical=4`, `wire=2`, `signalr=1` — точное
  возвращение к pre-load baseline.
- Development consumer throughout: `direct_provider_connections=0`,
  `authentication_sessions=0`, `login_key_calls=0`, `last_error=""`.
- Browser network hosts: только `127.0.0.1:8765`; WebSocket endpoint только
  `/ws/market-data`; direct browser TopstepX/ProjectX requests: 0.
- Все 12 завершившие history-load клиенты совпали: MES close `7687.5` →
  rendered `7,687.50` green; MNQ close `29370` → rendered `29,370.00` red;
  `external_live=true`, `price_marker_live=true`, provider state `LIVE`.
- Рынок был закрыт, поэтому новый raw trade/WS payload не создавался. PASS не
  подменяет это искусственным движением: свежесть подтверждалась receive/
  heartbeat, а неизменившаяся цена оставалась цветной и live.

### Responsive UI

- 84/84 page/viewport checks passed: 12 основных страниц × 7 размеров от
  2560×1440 до 360×800, whole-document horizontal overflow: 0.
- 390×844, device scale factor 2: Add Chart, Cabinet и Admin открывались
  обычными pointer clicks; Users, Connectors, Operations и Environments modules
  были кликабельны, drawer/body width matched, console/HTTP errors: 0.
- Two-chart reflow: 1024×768, 768×1024 и 390×844 — overlap 0; сохранённая
  desktop free-position geometry применяется только выше compact breakpoint.
- Operations LOCAL: Worker `running`, Telegram `connected`, Connector `ok`;
  панель ответила без прежнего 500/12-second blank state.

### Automated gates

- Targeted market-data/chart/Operations/responsive: `251 passed`, `0 failed`.
- Full regression: `1924 passed`, `32 skipped`, `0 failed`.
- py_compile + compileall, 32 JavaScript syntax checks, CSP, committed-secret,
  Markdown/link, External GPT Context and `git diff --check`: PASS.

## Authorization boundary

Этот PASS относится к безопасному fan-out внутри подтверждённого owner scope и
изолированных окружений StratForge. Глобальная раздача owner feed unrelated
users не включена: `redistribution_authorized=false` остаётся
`EXTERNAL BLOCKED` до письменного разрешения провайдера/CME и реализации
per-user entitlement mapping.

## Release state

Release cycle: PASS.

- implementation commit `93b357d73a3dcb8db294df6eb3d1dc301a83af9a`;
- [PR #142](https://github.com/OMNOM-111/NT-Analyzer/pull/142), все пять
  обязательных GitHub checks зелёные;
- merge SHA `4d15f1d2250e2c52bde02b902d88ec7aad043543`;
- candidate `rc_a7c6c0afb95d410f92474614efeb1b35`;
- artifact `art_ccaadc3a536e4272809d32073f072918`;
- build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`;
- archive SHA256
  `882FF3520DDD43BF65925F3DFA5AA95DA56107336DA98EFDC64146A81981195B`;
- runtime/manifest SHA256
  `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`.

Canary deployment `dep_de061542f96641e1a10b7bb4456c2df0` получил тот
же artifact, прошёл authenticated owner UI/Documents/charts acceptance и был
зафиксирован как `canary_passed` в `2026-08-23T02:08:54Z`. Production
deployment `dep_8716b7cf463f4cf8af092ba6a4e5bdae` затем продвинул этот
же artifact без rebuild и завершился `production_live` / external PASS в
`2026-08-23T02:16:30Z`. Expand migrations корректно пропущены: pending `0`.

Детерминированный executor ref и активный release-directory suffix для обоих
окружений: `0.10.0-beta.29-4d15f1d2250e`; previous/rollback slot после
promotion — принятый beta.28 `0.10.0-beta.28-36600dba3d73`. Executor на обоих
переключениях проверил current symlink, manifest identity, signature,
readiness и `same_immutable_artifact=true`.

## Canary and Production live smoke

- `/api/runtime/env` и `/api/health/ready` на обоих origins: beta.29, exact
  merge SHA/build/runtime digest, `dirty=false`, ready PASS.
- `theme.css`, `api.js`, `chart-engine.js` и `pages/desktop.js`: byte-identical
  Canary ↔ Production и соответствуют принятому artifact.
- Production owner login: `DMYTRO CHEREVKO`; два одновременных browser clients
  получили MES 5m `7687.5` → `7,687.50` green и MNQ 5m `29370` →
  `29,370.00` red, `external_live=true`, `price_marker_live=true`. MNQ 15m
  повторил тот же live contract и был возвращён на 5m.
- Production Admin: gateway `hub/direct_hub`, TopstepX `LIVE`; Canary и LOCAL:
  `consumer/owner_gateway_consumer`. Browser resource inventory содержит
  только same-origin StratForge bars/batch endpoints; direct TopstepX/ProjectX
  browser requests и provider credentials: `0`.
- Production responsive smoke на 390×844 и 768×1024: whole-document
  horizontal overflow `0`; два chart windows сохранены. Полная 84/84 matrix
  доказана тем же byte-identical artifact в Development.
- CME был закрыт: новый raw trade не утверждается. Fresh quote/SignalR
  heartbeat честно удерживал неизменившуюся цену в live green/red состоянии.
