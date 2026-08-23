# Beta.29 — market-data fan-out and responsive acceptance

Дата Development-проверки: `2026-08-23T01:29:45Z`.

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

Implementation acceptance: PASS. Git/CI/Canary/Production identity записывается
после прохождения штатной цепочки из clean merged commit и одного signed
immutable artifact. До этого live Canary/Production остаются beta.28.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-23T01:29:45Z | GPT-5.5 через Codex по запросу owner | Создан технический acceptance snapshot beta.29: воспроизводимые fixes, 12-page fan-out evidence, responsive matrix и неизменённая entitlement boundary.
-->
