# Phase 20 Task for Claude — довести «Торговля онлайн» до полностью управляемой версии после ревью

Дата: 2026-05-02.

## Контекст ревью

После Phase 19 часть исправлений была внесена, но пользователь на скрине увидел две реальные проблемы:

1. UI показывал ошибку `Не удалось опросить status: no route: /api/ops/runtime/command-status`.
2. В аккаунтах/балансах было непонятно, откуда берутся `Backtest`, `Sim101`, `Playback101`, и подтягивается ли реальная сумма счета.

Ревью показало:

- Запущенный backend был старым процессом: файл `server.py` уже содержал `/api/ops/runtime/command-status`, но процесс на `127.0.0.1:8765` отдавал старую версию без этого route и без `online_accounts`.
- После перезапуска backend `/api/ops/runtime/accounts` корректно отдаёт:
  - `online_accounts`: только `DEMO3369390`.
  - полный diagnostic list: `Backtest`, `Playback101`, `Sim101`, `DEMO3369390`, `1267509`.
- `DEMO3369390` баланс уже подтягивается из bridge: `cash_value=50173.5`, `net_liquidation=50173.5`, `connection_status=Connected`.
- Live `1267509` виден как `live/read-only`, но баланс `0`, потому что `connection_status=Disconnected`. Если live account не подключен в NinjaTrader, bridge не может получить актуальный cash/net liquidation.
- Последняя command failure была не из-за command-status, а из-за отсутствия strategy instance:
  `no 'NTAnalyzerEveryNBarLong' instance found on account 'DEMO3369390'. Add it once via NinjaTrader Strategies window, then re-issue the command.`
- На экране была runtime-строка `StrategiyaUrovney`, а справа в selector была выбрана стратегия `NTAnalyzerEveryNBarLong`. Старый UI отправлял команду по правому selector, а не по выбранной runtime-строке.

## Hotfix уже сделан

Изменены:

- `NT-Analyzer/app/static/trading.js`
- `NT-Analyzer/app/static/trading.html`

Сделано:

- Dropdown аккаунта теперь защитно фильтрует `Backtest`, `Sim101`, `Playback101` даже если backend ещё старый и не прислал `online_accounts`.
- Default account выбирается `DEMO3369390`.
- Live account card показывает `Cash`, `NetLiq`, `Connection`, но остаётся locked/read-only.
- `sendCommand()` теперь использует выбранную runtime-строку (`runtime_instance_id`, runtime class/account/instrument/timeframe), а не только правый strategy selector.
- Если пользователь пытается `Start` без выбранного existing runtime instance, UI честно сообщает, что bridge сейчас не подтверждает создание нового instance из приложения.
- Если `/command-status` отсутствует из-за старого backend, UI пробует fallback `/command-results` и показывает реальную причину bridge failure.
- `trading.html` получил новый cache-busting query: `trading.js?v=20260502-phase19-hotfix1`.
- Backend был перезапущен.

Проверено:

- Browser DOM: account dropdown содержит только `DEMO3369390`.
- Live card показывает `1267509 LIVE LOCKED Cash +0.00 NetLiq +0.00 Disconnected`.
- Demo account info показывает `Cash value +50173.50`, `Net liquidation +50173.50`, `Connection Connected`.
- Runtime table показывает одну строку: `StrategiyaUrovney`, `DEMO3369390`, `MES JUN26`, `5 Minute`, `running`.
- Tests pass:
  - `python -m tests.test_runtime`: 44 passed.
  - `python -m tests.test_trading`: 31 passed.
  - `python -m tests.test_ops`: 12 passed.

## Что всё ещё нужно сделать крупно

### 1. Честная модель управления strategy instances

Сейчас bridge/processor умеет только включать/выключать существующий NinjaTrader strategy instance, если он найден. Он не создает новый instance из UI.

Нужно явно выбрать одну из двух архитектур:

#### Вариант A — existing instance only

UI должен быть построен вокруг существующих runtime instances:

- `Start` доступен только для выбранной stopped runtime-строки.
- `Stop` доступен только для выбранной running runtime-строки.
- Если пользователь выбрал class/account/instrument справа, но instance ещё нет, кнопка `Start` disabled и текст:
  `Добавьте strategy instance в NinjaTrader → Strategies один раз, затем управляйте им здесь.`
- Правый selector не должен отправлять команду на class, которого нет в runtime table.
- При выборе строки в runtime table правая панель должна синхронизироваться с этой строкой: class/account/instrument/timeframe/state.

#### Вариант B — UI умеет создать новый instance

Исследовать NinjaTrader AddOn API:

- Можно ли безопасно создать strategy instance из AddOn с выбранным account/instrument/timeframe/params?
- Можно ли это сделать без прямой отправки ордеров и без live риска?
- Можно ли гарантировать paper/demo only?
- Как получить native instance id после создания?

Если API не позволяет это безопасно, не имитировать запуск. Оставить Вариант A.

### 2. Runtime должен показывать stopped/disabled instances, если NinjaTrader их видит

Сейчас `strategies.json` может показывать только реально видимые в `Account.Strategies` строки. Нужно проверить, включает ли `Account.Strategies` disabled/stopped strategies. Если нет, UI не сможет включить stopped instance, потому что не будет знать его identity.

Нужно:

- Проверить, какие strategy objects доступны через NinjaTrader AddOn для enabled и disabled states.
- Если disabled instances доступны, экспортировать их в `strategies.json` с `enabled=false`, `state=Terminated/Disabled`.
- Если disabled instances недоступны, документировать ограничение: app can stop running instances but cannot start stopped instances unless they remain visible in runtime.

### 3. Account balance semantics

В `accounts.json` есть реальные поля, но live `1267509` сейчас disconnected и поэтому показывает нули.

Нужно:

- В UI подписать disconnected live balance как `not available while disconnected`, а не просто `+0.00`.
- Для demo `DEMO3369390` показывать `cash_value/net_liquidation` как основной доступный баланс.
- В backend добавить `balance_available: true/false`, чтобы стратегия/analytics не путали реальный ноль и недоступность данных.
- Для strategy sizing использовать только account с `balance_available=true`; если false — блокировать запуск профиля, которому нужен капитал.

### 4. Backend process/version health

Проблема `no route: /command-status` возникла из-за старого backend процесса.

Нужно добавить health/version marker:

- `/api/health` должен отдавать backend build/version/features, например:
  - `trading_online_api_version: 2`
  - `features: ["runtime_accounts_online", "command_status", "runtime_instance_id"]`
- `trading.js` при загрузке проверяет эти features и показывает banner:
  `Backend запущен старой версией. Перезапустите NT-Analyzer.`
- `start.ps1` если порт занят, должен проверить `/api/health` features. Если backend старый, предложить остановить старый процесс или открыть понятную инструкцию, а не молча открывать браузер.

### 5. Command result UX

UI должен показывать не технический `failed_other`, а нормальные операционные статусы:

- `no instance found`: `В NinjaTrader нет такой стратегии на выбранном счёте. Добавьте её один раз в Strategies.`
- `live locked`: `Live account заблокирован.`
- `old backend`: `Перезапустите NT-Analyzer backend.`
- `old bridge`: `Закройте NinjaTrader → 01_INSTALL_BRIDGE.cmd → откройте NinjaTrader.`
- `completed but runtime not changed`: показать как warning, не success.

### 6. Clean UI after Phase 19

Скрин показал, что old B1/Paper status блок всё ещё занимает центральное место. Для `Торговля онлайн` он должен быть свернут или вынесен в diagnostics.

Нужно:

- Свернуть `Paper status — B1 ShortOnly` по умолчанию или перенести ниже/в отдельную вкладку.
- Переименовать `Parameters diff` в `Параметры` и сделать mismatch informational.
- Убрать визуальную конкуренцию с основными runtime controls.

## Acceptance checks

1. После перезапуска backend `/api/health` явно показывает Phase 20 features.
2. Если старый backend уже висит на 8765, launcher не молчит, а предупреждает.
3. В account dropdown только `DEMO3369390`.
4. `1267509` виден как live locked/read-only, с понятным статусом баланса.
5. Системные accounts видны только в diagnostics, не в normal selector.
6. Выбор runtime row синхронизирует right panel.
7. Stop selected running demo instance работает по `runtime_instance_id`.
8. Start без existing instance не отправляет команду, а объясняет ограничение.
9. Если stopped instance виден runtime bridge, Start включает именно его.
10. Если stopped instance не виден runtime bridge, это явно документировано как NinjaTrader API limitation.
11. Backtest page unchanged.
12. Все tests проходят.