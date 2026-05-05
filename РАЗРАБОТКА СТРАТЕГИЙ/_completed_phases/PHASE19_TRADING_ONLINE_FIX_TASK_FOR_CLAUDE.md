# Phase 19 Task for Claude — исправить вкладку «Торговля онлайн» end-to-end

Дата: 2026-05-02.

## Главная цель

Исправить вкладку `Торговля онлайн` в NT-Analyzer так, чтобы она показывала реальное состояние NinjaTrader и давала рабочее, понятное управление стратегиями.

Важно: вкладку `Бэктестирование` не трогать. Она считается рабочей и должна остаться стабильной. Можно брать оттуда архитектурный пример: аккуратная загрузка каталога, чистый UI, понятная валидация, но нельзя ломать исторический запуск, job schema, backtest bridge, Strategy Analyzer runner и существующие backtest endpoints.

## Что должно быть в результате

1. В `Торговля онлайн` отображаются только реальные аккаунты пользователя:
   - Live: `1267509` — виден как live/read-only, запуск/остановка через приложение заблокированы.
   - Simulation Demo: `DEMO3369390` / `Simulation Demo 3369390` — основной разрешенный sim/demo account для онлайн-проверки.
2. Не должны показываться как пользовательские счета:
   - `Backtest`
   - `Sim101`, если его нет у пользователя как рабочей учетной записи
   - `Playback101`
   - любые synthetic/playback/backtest/system accounts
   - любые `unknown`/заблокированные строки, если они не входят в реальные аккаунты пользователя.
3. Если NinjaTrader сообщает live-счет, он может быть показан, но только как read-only / live locked. Не выбирать его по умолчанию для запуска.
4. В центре должны быть только реальные strategy instances из NinjaTrader runtime, без выдуманных registry fallback-строк.
5. Если в NinjaTrader включено две копии одной стратегии, вкладка должна показывать две строки, а не одну.
6. Если включена одна стратегия, должна быть одна строка.
7. Если стратегия запущена с другими параметрами, это не должно превращаться в красную ошибку `not locked B1`. На этом экране важен факт runtime-связки: class/account/instrument/timeframe/state/position/orders/executions. Параметры B1 можно показывать в отдельной информационной панели, но не мешать управлению и не писать, что стратегия «не та», если пользователь просто запустил ее с другой конфигурацией.
8. Слева список инструментов должен показывать только актуальные контракты по каждому root, а устаревшие контракты скрывать по умолчанию.
9. Справа должны быть корректные параметры запуска новой strategy instance: account, strategy class, актуальный instrument contract, timeframe, quantity, optional params.
10. Запуск/остановка должны работать честно:
    - если bridge может управлять существующим strategy instance, команда должна реально доходить до NinjaTrader и подтверждаться runtime telemetry;
    - если AddOn не может создать новый instance из UI, показать понятное действие: «добавьте instance в NinjaTrader один раз, затем включайте/выключайте здесь»;
    - нельзя показывать успех, пока runtime telemetry не подтвердила состояние или command_result не объяснил, почему это невозможно.

## Текущее состояние, найденное в коде и данных

### 1. Установленный NinjaTrader bridge старее исходников

В исходниках `bridge/src/Runtime/RuntimeTelemetryExporter.cs` указан `ExporterVersion = "1.1.0"` и есть метод `WriteAccounts()`, который должен писать `data/runtime/accounts.json`.

Но текущий `data/runtime/heartbeat.json` содержит:

```json
{"exporter_version":"1.0.0"}
```

И в `data/runtime/` нет `accounts.json`. Значит в NinjaTrader установлен старый DLL/AddOn или NinjaTrader еще не перезапущен после установки нового bridge.

Последствие: backend падает в fallback и берет аккаунты из `positions.json`.

### 2. Лишние аккаунты приходят из `positions.json`, а не из реального accounts catalog

Текущий `data/runtime/positions.json`:

```json
{"Backtest":[],"Playback101":[],"Sim101":[],"DEMO3369390":[],"1267509":[]}
```

Backend `app/runtime.py::read_accounts_with_source()` при отсутствии `accounts.json` строит аккаунты из ключей `positions.json`. Поэтому UI видит `Backtest`, `Playback101`, `Sim101`, `DEMO3369390`, `1267509`.

Это неправильно для пользовательского экрана. `positions.json` можно использовать для диагностики, но нельзя напрямую превращать все его ключи в selectable accounts.

### 3. Python и C# по-разному классифицируют аккаунты

В Python `app/runtime.py::_classify_account_mode()`:

- `demo` сейчас попадает в `paper` из-за `PAPER_ACCOUNT_HINTS`.
- `1267509` без declared mode становится `unknown`.

В C# `RuntimeCommandProcessor.ClassifyAccountMode()` любой non-empty account, который не sim/demo/playback, становится `live`.

Нужно привести backend и bridge к одной политике:

- `DEMO3369390` = `demo` или `paper`/`sim`, controllable.
- `1267509` = `live`, read-only, locked.
- `Backtest`, `Playback101`, synthetic `Sim101` = system/test accounts, hidden by default.

### 4. UI сам добавляет заблокированные аккаунты в dropdown

В `app/static/trading.js::loadAccounts()` сейчас логика такая:

- controllable: `paper`, `playback`, `demo`
- blocked: все остальные
- UI добавляет и controllable, и blocked в один `<select>`
- blocked опции disabled и с подписью `[unknown/live, заблокирован]`

Пользователь просит не видеть лишние заблокированные/странные аккаунты. Нужно разделить:

- selectable dropdown: только реальные разрешенные sim/demo accounts;
- live account: отдельный read-only badge/card, если найден;
- diagnostics: отдельный свернутый блок «служебные счета/скрыто», если нужно.

### 5. Runtime strategy сейчас одна, но UI может терять дубли

Текущий `data/runtime/strategies.json` показывает одну активную строку:

```json
{
  "account_name":"DEMO3369390",
  "account_mode":"paper",
  "strategy_id":"b1_shortonly",
  "strategy_class":"NTAMicroVwapRiskPilot",
  "instrument":"MES JUN26",
  "enabled":true,
  "state":"Realtime"
}
```

Пользователь видел в NinjaTrader задвоение стратегии, но экран показал одну. Возможные причины:

1. `RuntimeTelemetryExporter.SafeStrategies(acc)` реально получает только один strategy object из `Account.Strategies`.
2. `InferStrategyId(strat)` для всех `NTAMicroVwapRiskPilot` возвращает один и тот же `b1_shortonly`, поэтому backend/UI выбирают/перезаписывают/выделяют по неуникальному `strategy_id`.
3. `app/runtime.py::_find_runtime_for()` возвращает первый match по `strategy_id` или class и не умеет различать несколько instances одного class.
4. UI selection использует `data-sid` = `strategy_id`, что не уникально при двух копиях.

Нужно ввести стабильный runtime instance id, например:

```text
runtime_instance_id = sha256(account_name + strategy_class + strategy_name + instrument + timeframe + instance_index_or_native_id)
```

Если NinjaTrader exposes native ID/Name/Uid, использовать его. Если нет, backend должен сохранять все строки и добавлять индекс в пределах snapshot. UI должен выбирать строки по `runtime_instance_id`, не по `strategy_id`.

### 6. Params mismatch сейчас мешает смыслу вкладки

`app/runtime.py::validate_params()` и `trading.js::renderRuntimeTable()` делают `PARAM_MISMATCH` красной ошибкой для `NTAMicroVwapRiskPilot`, сравнивая runtime params с locked B1 ShortOnly.

Пользователь явно сказал: если в NinjaTrader запущена эта стратегия с другими параметрами, это отдельная история. В `Торговля онлайн` не надо писать, что она «не locked B1» и не надо блокировать обычную связь/отображение только из-за параметров.

Нужно изменить UX:

- В таблице: `Параметры: custom` / `locked profile: не применен` как neutral/warn info, не hard error.
- Не показывать большой красный banner «это НЕ locked B1 ShortOnly конфигурация».
- Не блокировать stop command из-за params mismatch.
- Start command может требовать выбранный profile, но это должно быть явно «запуск по профилю», а не проверка уже запущенного instance.

### 7. Stop command не должен зависеть от params mismatch

Сейчас `computeGate()` добавляет причину `PARAM MISMATCH` и блокирует общий gate. Это блокирует `start`, а stop включается только по bridge online, но command processor C# при `disable_strategy` params не проверяет. UI должен явно позволять остановить mismatched/custom strategy instance на demo account.

Требование:

- stop разрешен для selected runtime instance на demo/paper/playback account даже при params mismatch;
- stop запрещен для live;
- start валидируется отдельно.

### 8. Инструменты фильтруются эвристикой по `data_last`, а не по expiry/current contract

В `trading.js::isInstrumentCurrent()` сейчас `current = data_last >= today - 30 days OR blank`. Это опасно:

- контракты без minute data считаются current;
- фронт-месяц выбирается по максимальному `data_last`, а не по актуальной expiry/month cycle;
- `instruments.json` содержит 1456 контрактов, включая старые и будущие monthly rows.

Backend уже имеет `_resolve_group_instruments()` и `instrument_groups.current_instruments`, но UI напрямую использует `cat.instruments`, а не готовый список current contracts.

Нужно сделать один backend contract для online instruments:

- `GET /api/ops/runtime/instruments` или расширить `/api/catalog` блоком `online_instruments`.
- По умолчанию вернуть ровно актуальный контракт на root: `MES`, `MNQ`, `MYM`, `M2K/RTY`, `MGC`, `MCL`, `MNG`, `RB`, `HO`, `MBT`, `MET`, etc.
- Правило должно учитывать `expiry`, root month cycle и сегодняшнюю дату. Если невозможно надежно по expiry, выбрать nearest non-expired with data/metadata и пометить confidence.
- UI слева показывает только `online_instruments.current` по умолчанию. История/expired доступна только через diagnostics toggle.

### 9. Orders/executions плохо привязаны к strategy instance

Текущие `orders.jsonl` и `executions.jsonl` содержат строки, где `strategy_id` часто пустой:

```json
{"strategy_id":"","strategy_class":"","account_name":"DEMO3369390","instrument":"MES JUN26"}
```

Из-за этого `/api/ops/runtime/executions?strategy_id=b1_shortonly` может возвращать пусто, а статистика «сделки сегодня / PnL сегодня» будет неверной.

Нужно улучшить bridge export:

- в `AppendExecution()` получать strategy через `Execution.Order.Strategy`, если доступно;
- писать `runtime_instance_id`, `strategy_id`, `strategy_class`, `strategy_name`;
- если прямой связи нет, backend может best-effort match по account+instrument+time window, но помечать `attribution_confidence`.

### 10. Atomic writes иногда падают из-за Windows file lock

В `data/runtime/errors.jsonl` есть ошибки:

```text
System.IO.IOException: Не удается удалить заменяемый файл.
AtomicFile.WriteAllText -> RuntimeTelemetryExporter.WriteHeartbeat / WriteStrategiesAndPositions
```

Это может приводить к пропускам heartbeat/strategies/accounts snapshots. Нужно проверить `bridge/src/Util/AtomicFile.cs`: если fallback уже добавлен, убедиться, что installed DLL содержит этот fix. Если нет, обновить и переустановить bridge.

## Обязательные изменения

### A. Bridge deployment / version health

1. Добиться, чтобы NinjaTrader runtime писал:
   - `data/runtime/accounts.json`
   - `heartbeat.exporter_version = "1.1.0"` или выше
   - `accounts.summary.total`, `live`, `paper/demo`, `playback`, `unknown`
2. Добавить в UI явный banner, если исходники bridge новее установленного exporter:
   - `Установлен старый NTAnalyzerBridge: exporter 1.0.0, нужен 1.1.0+. Закройте NinjaTrader -> 01_INSTALL_BRIDGE.cmd -> откройте NinjaTrader.`
3. Не использовать `positions_fallback` как нормальный источник selectable accounts.

### B. Account model

В backend добавить нормализованную модель account:

```json
{
  "account_name": "DEMO3369390",
  "display_name": "Simulation Demo 3369390",
  "account_mode": "demo",
  "is_live": false,
  "is_system": false,
  "is_selectable_for_online": true,
  "control_allowed": true,
  "source": "accounts_json"
}
```

Для `1267509`:

```json
{
  "account_name": "1267509",
  "display_name": "Live 1267509",
  "account_mode": "live",
  "is_live": true,
  "is_system": false,
  "is_selectable_for_online": false,
  "control_allowed": false
}
```

Для `Backtest`, `Sim101`, `Playback101`:

```json
{
  "is_system": true,
  "is_selectable_for_online": false,
  "hidden_reason": "system/backtest/playback account"
}
```

Allowlist/denylist можно держать в backend config, например `data/runtime/account_policy.json` или `data/ops/account_policy.json`:

```json
{
  "visible_accounts": ["1267509", "DEMO3369390"],
  "demo_accounts": ["DEMO3369390"],
  "live_accounts": ["1267509"],
  "hide_accounts": ["Backtest", "Sim101", "Playback101"]
}
```

Если `accounts.json` появился и содержит больше реальных accounts, policy должна явно показывать, что скрыто и почему.

### C. Runtime strategy identity and duplicates

1. Bridge `strategies.json` должен содержать уникальный `runtime_instance_id` для каждой строки.
2. Backend не должен дедуплицировать runtime rows по `strategy_id` или class.
3. UI должен выбирать/останавливать конкретную строку по `runtime_instance_id`.
4. Если в NinjaTrader две копии `NTAMicroVwapRiskPilot` на одном account/instrument, обе видны.
5. Команда stop должна передавать `runtime_instance_id` плюс fallback fields.

### D. Trading Online UI redesign, без маркетинговых карточек

Оставить рабочий трехколоночный формат:

```text
LEFT: Инструменты
  - группы
  - только актуальные контракты по умолчанию
  - поиск

CENTER: Runtime strategy instances
  - class/name
  - account
  - account mode
  - instrument
  - timeframe
  - enabled/state
  - position
  - PnL today
  - last update

BOTTOM CENTER: Details tabs
  - Обзор
  - Сделки
  - Ордера
  - Позиция
  - Параметры
  - События

RIGHT: Launch/Control
  - selected account
  - selected strategy class
  - selected actual contract
  - timeframe
  - quantity
  - Start / Stop selected instance
  - command status
```

Убрать или снизить роль:

- `Paper status — B1 ShortOnly` как центральный блок. Это может быть отдельная свернутая панель, но не должно мешать онлайн-управлению.
- красный `not locked B1` banner.
- `Parameters diff` как hard blocker.

### E. Command behavior

Start:

- доступен только для demo/paper account;
- live всегда blocked;
- если нужно создать новый strategy instance, честно сказать, поддерживает ли bridge создание;
- если bridge умеет только enable existing instance, UI должен требовать выбрать существующий stopped instance или показать инструкцию добавить instance в NinjaTrader.

Stop:

- работает для selected runtime instance на demo/paper/playback;
- не требует locked params;
- не требует selection_diff по выбранному instrument, если уже выбрана конкретная runtime строка;
- live blocked.

Command status:

- ждать `command_results.jsonl`;
- затем ждать свежий `strategies.json` snapshot;
- успех только если runtime state реально changed;
- при failure показывать конкретную причину (`account not found`, `no instance`, `live locked`, `SetState failed`, `old bridge`).

### F. Reports / analytics correctness

1. Overview должен брать данные из selected runtime instance.
2. Trades/orders должны фильтроваться по `runtime_instance_id`, а при его отсутствии по account+instrument+strategy attribution.
3. `today.pnl` должен быть честным: если execution attribution missing, показать `недостаточно данных`, а не ноль как будто сделок не было.
4. Position должна совпадать с NinjaTrader selected strategy/account/instrument.
5. Events tab должен показывать bridge errors, включая AtomicFile IO errors and command failures.

## Файлы, которые скорее всего придется менять

- `NT-Analyzer/app/static/trading.html`
- `NT-Analyzer/app/static/trading.js`
- `NT-Analyzer/app/runtime.py`
- `NT-Analyzer/app/server.py`
- `NT-Analyzer/bridge/src/Runtime/RuntimeTelemetryExporter.cs`
- `NT-Analyzer/bridge/src/Runtime/RuntimeCommandProcessor.cs`
- `NT-Analyzer/bridge/src/Util/AtomicFile.cs`
- `NT-Analyzer/tests/test_trading.py`
- `NT-Analyzer/tests/test_runtime.py`

Не менять без крайней необходимости:

- `NT-Analyzer/app/jobqueue.py` backtest creation/validation flow
- `NT-Analyzer/bridge/src/Execution/StrategyAnalyzerRunner.cs`
- `NT-Analyzer/app/static/app.js`, кроме если нужен только shared UI helper без изменения поведения backtest вкладки

## Regression tests / acceptance checks

### Backend tests

Добавить/обновить тесты:

1. `positions_fallback` with `Backtest`, `Playback101`, `Sim101`, `DEMO3369390`, `1267509` returns only visible real accounts in online account list.
2. `DEMO3369390` classified as demo/paper and controllable.
3. `1267509` classified as live and not controllable.
4. Missing `accounts.json` produces warning `old bridge / accounts unavailable`, but does not show system accounts as normal accounts.
5. Runtime strategies with duplicate class/account produce two rows with unique `runtime_instance_id`.
6. Stop command allowed for custom/mismatched params on demo account.
7. Stop command blocked for live account.
8. Execution/order attribution returns honest `unknown attribution` when strategy id is empty.
9. Current instruments endpoint returns only one current contract per root by default.
10. Existing backtest tests still pass.

### Manual checks in NinjaTrader

1. Close NinjaTrader.
2. Run `NT-Analyzer/01_INSTALL_BRIDGE.cmd`.
3. Open NinjaTrader.
4. Confirm `data/runtime/heartbeat.json` has exporter `1.1.0+`.
5. Confirm `data/runtime/accounts.json` exists.
6. Open `http://127.0.0.1:8765/ui/trading.html`.
7. Account selector shows only `DEMO3369390` as startable. Live `1267509` visible only as locked/read-only.
8. No `Backtest`, `Sim101`, `Playback101` in normal dropdown.
9. Enable one strategy in NinjaTrader: exactly one row appears.
10. Enable two copies: exactly two rows appear.
11. Stop selected demo strategy from app: NinjaTrader disables that exact instance and UI confirms.
12. Start selected existing demo strategy from app: NinjaTrader enables it and UI confirms.
13. Try live account: UI and backend reject.
14. Backtest page still runs historical jobs exactly as before.

## Definition of done

Phase 19 is done only when:

- `Торговля онлайн` no longer shows fake/system accounts as normal choices.
- The page reflects real NinjaTrader runtime, including duplicate strategy instances.
- Start/stop behavior is honest and confirmed by runtime telemetry.
- Strategy parameter mismatches are informational, not a false red failure for the online screen.
- Current contracts are the default instrument list.
- Trades/orders/statistics are either correctly attributed or explicitly marked as not attributable.
- Installed bridge version matches source expectations and writes `accounts.json`.
- No behavior regression on `Бэктестирование`.