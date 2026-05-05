# Phase 21 Task for Claude — довести «Торговля онлайн» до запуска стратегий из платформы как из NinjaTrader

Дата: 2026-05-02.

## Контекст

Phase 19/20 уже оживили runtime telemetry и account balance:

- `data/runtime/accounts.json` приходит от bridge `exporter_version=1.1.0`.
- Правый блок «Настройки торговли» корректно показывает активный DEMO или LIVE аккаунт, режим, connection и cash/net liquidation.
- Live `1267509` определяется как `live` и должен оставаться read-only / locked.
- Demo `DEMO3369390` является единственным разрешенным account для управления.
- System accounts `Backtest`, `Sim101`, `Playback101` не должны быть обычными accounts пользователя.

Пользователь подтвердил, что при переключении NinjaTrader между demo и live баланс и режим в правой панели отображаются правильно.

## Hotfix после пользовательского ревью уже сделан

Изменены:

- `NT-Analyzer/app/static/trading.js`
- `NT-Analyzer/app/static/trading.html`

Сделано:

1. Верхний status chip `Аккаунт: ...` больше не берет старый selected dropdown. Он отображает активный account из bridge:
   - `Аккаунт: NT offline`, если NinjaTrader/bridge offline.
   - `Аккаунт: DEMO DEMO3369390`, если активен demo.
   - `Аккаунт: LIVE 1267509`, если активен live.
   - `offline` suffix, если account disconnected.
2. Accounts telemetry теперь переопрашивается вместе с runtime каждые ~5 секунд, а не только при загрузке страницы.
3. `selection_diff` больше не красный hard blocker для выбранной runtime-строки. Выбранная runtime-строка сама является целью команды; account/instrument/timeframe mismatch показываются только как informational warning.
4. `trading.html` cache bust обновлен до `trading.js?v=20260502-phase19-hotfix4`.

Проверить после этого:

- Переключить NinjaTrader demo/live/offline и убедиться, что верхний chip меняется без F5.
- Выбрать runtime strategy row и убедиться, что account/instrument mismatch больше не превращается в красное «нельзя».

## Что пользователь сейчас считает главными проблемами

1. Верхний header раньше писал `Аккаунт: demo/paper` даже когда NinjaTrader был выключен или активен live. Hotfix должен закрыть это, но нужно добавить тесты/health coverage.
2. В таблице active strategies / right panel появляются непонятные красные сообщения про real-time instrument / selected instrument / MNQ0626 / MES JUN26. Они не должны выглядеть как авария, если пользователь просто выбрал строку runtime или другой инструмент в selector.
3. UI видит стратегию, включенную вручную в NinjaTrader, но не умеет полноценно запускать новую стратегию из платформы.
4. В dropdown `Аккаунт NinjaTrader` сейчас только `DEMO3369390`. Это правильно для controllable accounts, но UI должен понятнее показывать live account рядом как read-only. Нельзя давать live выбрать для запуска, но пользователь должен видеть, что live обнаружен.
5. При выборе strategy class в правой панели параметры этой стратегии почти не доступны. Нужно полноценное отображение/редактирование параметров из catalog metadata.
6. Start должен работать из нашей платформы максимально похоже на NinjaTrader Strategies window: выбрать account, instrument, timeframe, strategy class, params, quantity/profile, затем создать или включить instance.

## Главная цель Phase 21

Сделать вкладку `Торговля онлайн` полноценной рабочей платформой управления strategy instances:

- Видеть все реальные accounts, но управлять только demo/paper.
- Видеть все реальные NinjaTrader strategy instances.
- Выбирать strategy class и параметры из catalog.
- Создавать новый strategy instance из UI, если NinjaTrader AddOn API позволяет это безопасно.
- Если AddOn API не позволяет создание, сделать честный режим existing-instance-only с понятным UI и без fake start.
- Stop/Start existing instance должны работать по конкретному `runtime_instance_id`.
- Live всегда locked на UI/backend/bridge.

## Non-negotiable safety

1. Live trading remains forbidden.
2. `1267509` may be shown as live/read-only only. No enable/create/disable on live.
3. Commands may target only `DEMO3369390` or other explicitly paper/demo accounts.
4. Never submit orders directly from AddOn. Only create/enable/disable NinjaScript strategy instances if NinjaTrader API supports it safely.
5. Do not touch the backtesting tab behavior.

## Required architecture decisions

### Decision A — Can AddOn create a new strategy instance?

Investigate NinjaTrader 8 AddOn API and implement one of two modes.

#### Mode A1: Full create-from-platform

If supported safely, implement:

- UI sends `create_strategy_instance` command with:
  - `command_id`
  - `strategy_class`
  - `account_name`
  - `instrument`
  - `bars_period_type`
  - `bars_period_value`
  - `quantity` / position sizing profile if supported by strategy params
  - `params`
  - `paper_only=true`
- Bridge validates:
  - account exists and is demo/paper/playback.
  - account is not live.
  - instrument exists.
  - strategy class exists and is not rejected/archived.
  - params are valid for this strategy.
- Bridge creates the strategy instance using NinjaTrader-supported APIs, returns native/runtime identity, then exporter writes it in `strategies.json`.
- UI considers success only after fresh telemetry shows the new instance.

#### Mode A2: Existing-instance-only

If NinjaTrader API cannot safely create strategy instances from AddOn:

- Keep creation disabled.
- UI text must be explicit:
  `Создание нового instance из приложения недоступно: NinjaTrader AddOn API не дает безопасного создания. Добавьте стратегию один раз в NinjaTrader Strategies, затем управляйте Start/Stop здесь.`
- Start is enabled only for selected stopped runtime instance if it remains visible in telemetry.
- Stop is enabled only for selected running demo/paper runtime instance.
- No command is sent when no runtime instance exists.

Document the limitation in UI and docs, not only in Markdown.

## UI requirements

### Header status chips

Header chips must always reflect live state:

- Backend status.
- NT runtime online/offline.
- LIVE locked always visible.
- Active account chip from bridge, not from selector:
  - `NT offline`
  - `DEMO DEMO3369390 connected/disconnected`
  - `LIVE 1267509 connected/read-only`
  - `unknown locked`

Add a small feature check:

- `/api/health` must expose `trading_online_api_version` and feature flags.
- If old backend is running, UI shows `Backend устарел. Перезапустите NT-Analyzer.`

### Accounts panel

- `Аккаунт NinjaTrader` dropdown is for controllable accounts only.
- It should normally contain `DEMO3369390`.
- Live `1267509` must be visible next to/below it as a read-only locked row with balance and connection, not as a selectable launch target.
- System accounts hidden from normal UI; optional diagnostics block can list hidden accounts and reasons.

### Strategy parameters panel

Use catalog strategy metadata to render editable params:

- For selected strategy class, show all public NinjaScript properties with type-aware controls:
  - bool checkbox.
  - numeric input with min/max/step if available.
  - string input/select when values known.
- Support loading defaults from catalog.
- Support applying profiles (B1 ShortOnly locked profile, custom profile, last used profile).
- On command, send actual `params` JSON, not a hardcoded partial dict.
- Show validation errors before sending.

### Runtime table and selection diff

- Runtime table is authoritative for existing instances.
- Selecting a runtime row syncs right panel:
  - strategy class
  - account
  - instrument
  - timeframe
  - enabled/state
  - params
- `selection_diff` is informational only when a runtime row is selected.
- Do not show raw technical English mismatch as a red action blocker.
- Rename `Parameters diff` tab to `Параметры`.

### Commands

Commands must have user-facing statuses:

- `Создаю instance...`
- `Команда отправлена в NinjaTrader...`
- `Bridge подтвердил, жду telemetry...`
- `Запущено и подтверждено runtime telemetry.`
- `Остановлено и подтверждено runtime telemetry.`
- `В NinjaTrader нет такого instance. Добавьте его в Strategies.`
- `Live account заблокирован.`
- `Backend устарел.`
- `Bridge устарел.`
- `Создание instance не поддерживается NinjaTrader AddOn API.`

Success only when runtime telemetry confirms state change.

## Backend/API requirements

Add or finalize:

- `GET /api/health` with:
  - `trading_online_api_version: 3`
  - `features: [...]`
  - backend process/build marker.
- `GET /api/ops/runtime/accounts`:
  - `accounts`, `online_accounts`, hidden/system diagnostics.
  - `active_account` computed from connected non-system account priority.
  - `balance_available` true/false.
- `GET /api/catalog` or strategy metadata endpoint:
  - strategy class names.
  - parameter metadata: name, type, default, min, max, display/group if available.
- `POST /api/ops/runtime/command` must support current existing-instance commands and, if implemented, `create_strategy_instance`.
- Command status endpoint must classify failures into stable machine states, not only `failed_other`.

## Bridge requirements

Investigate and implement if possible:

- Export native strategy instance ID if available.
- Export stopped/disabled strategy instances if NinjaTrader exposes them.
- Existing instance Start/Stop by native/runtime ID, not only class/account/instrument loose match.
- Optional safe create instance flow, paper/demo only.
- `RuntimeCommandProcessor` must report `processor_version` and capabilities:
  - `can_enable_existing_instance`
  - `can_disable_existing_instance`
  - `can_create_instance`
  - `can_export_disabled_instances`

If create/export disabled is impossible with NT8 AddOn API, write exact reason and surface it in UI.

## Tests and acceptance

Add tests for:

1. Header active account changes when accounts endpoint changes demo/live/offline.
2. `online_accounts` only contains demo/paper; live appears read-only diagnostics.
3. `active_account` reports connected live when live is connected, connected demo when demo is connected, offline when heartbeat stale.
4. `selection_diff` does not block selected runtime row commands.
5. Start without existing instance does not send fake command in existing-instance-only mode.
6. Stop selected running demo instance sends `runtime_instance_id` and succeeds.
7. Live command rejected by backend and bridge.
8. Strategy parameter metadata renders in UI and command includes edited params.
9. Old backend/old bridge feature warning appears.
10. Backtest page unchanged.

Manual acceptance:

1. Open NinjaTrader connected to demo.
2. Open `/ui/trading.html`.
3. Header says DEMO and balance panel says DEMO.
4. Switch NinjaTrader to live.
5. Header says LIVE/read-only and live card shows broker balance, but launch controls remain blocked for live.
6. Switch NinjaTrader offline/close NT.
7. Header says NT offline within one polling interval.
8. Select a strategy class and see editable params.
9. Add/enable a strategy in NinjaTrader manually; it appears in active strategies.
10. Stop it from platform; runtime confirms stopped.
11. If create is supported, create and start a new demo instance from platform; runtime confirms. If not supported, UI clearly explains the limitation and never fakes success.
12. All tests pass.