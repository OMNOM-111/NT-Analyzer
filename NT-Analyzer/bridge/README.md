# NinjaTrader Bridge — PoC AddOn

Цель: один C# NinjaScript AddOn, работающий **внутри NinjaTrader 8 runtime**,
который читает один `job.json` из файловой очереди и возвращает `result.json`.

Стек: C#, .NET Framework 4.8 (требование NinjaTrader 8).

## Что делает PoC AddOn (минимум)

1. При запуске NinjaTrader регистрируется как `AddOnBase` и стартует фоновый поллер.
2. Поллер раз в 1–2 секунды сканирует `<projectRoot>/jobs/pending/<job_id>/`
   (только директории, у которых внутри лежит `job.json`).
3. Точный протокол перемещений (claim, running, finalize, cancel, recovery) —
   см. `../docs/job-schema.md`, раздел **«State machine очереди»**.
   Bridge обязан следовать ему буквально, никакой собственной интерпретации.
4. Для найденного job:
   - claim через атомарный `Directory.Move` `pending/<job_id>` → `running/<job_id>`;
   - читает `job.json` (`strategy.class_name`, `instrument`, `timeframe`, `period`, `execution`);
   - **selects strategy ONLY through reflected whitelist of `NinjaTrader.Custom.dll`**
     (см. ниже «Whitelist стратегий»). `source_file_hint` из job НИКОГДА не используется
     для загрузки кода;
   - применяет параметры из `strategy.parameters` к экземпляру (через `NinjaScriptProperty`);
   - запускает исторический прогон одним из R&D-вариантов (см. ниже);
   - собирает сделки и базовые метрики;
   - пишет артефакты и `result.json` через write-temp-then-rename;
   - финализирует через `Directory.Move` `running/<job_id>` → `done/<job_id>`.
5. На любой ошибке — пишет `error.json` и переносит в `failed/<job_id>`.
6. При появлении `cancel.flag` — корректно прерывает прогон, переносит в `cancelled/<job_id>`.
7. Heartbeat (с PID/process_name) обновляется каждые 5 сек внутри `running/<job_id>/`.

## Whitelist стратегий

Bridge принимает к исполнению только классы, которые удовлетворяют ВСЕМ условиям:

- класс физически загружен из `NinjaTrader.Custom.dll`
  (путь к DLL — фиксированный, `<NinjaTraderUserDir>/bin/Custom/NinjaTrader.Custom.dll`);
- класс наследник `NinjaTrader.NinjaScript.Strategies.Strategy`;
- имя класса (`Type.Name`) совпадает с `job.strategy.class_name`;
- `[NinjaScriptProperty]` доступны через reflection.

Любые другие способы получить тип (Assembly.LoadFrom произвольного пути,
CSharpCodeProvider, Roslyn-компиляция строки из job) **запрещены**.

## R&D-варианты запуска (порядок проверки)

Порядок строго фиксированный — нельзя «начать с того, что проще закодировать».
Главный принцип проекта: **NinjaTrader считает**, а не bridge.

### Вариант 1 (ОСНОВНОЙ для PoC) — внутренний механизм Strategy Analyzer

AddOn использует штатный исторический backtest NinjaTrader через доступные
внутренние API (Strategy Analyzer / `OptimizerOptions` / `BacktestOptions` /
`Strategy.SetUp` + историческая сессия). Цель — чтобы order/fill/lifecycle
семантика была **точно той же**, что у ручного запуска в Strategy Analyzer.

Если выбранный API окажется нестабильным или приватным настолько, что
поломки между версиями NT 8 неизбежны — это явно фиксируется в
`verification_warnings` и обсуждается переход к Варианту 2.

### Вариант 2 (FALLBACK / отдельный spike) — ручной historical run внутри NT runtime

`BarsRequest` для запрошенного инструмента/периода/таймфрейма + инстанцирование
Strategy + прогон через NT-овский lifecycle. Допустим **только** при условиях:

- доказано, что используются NT-овские order/fill/lifecycle классы
  (`OrderEntry`, `IOrder`, `Strategy.GenerateOrder`, и т.п.), а не самодельная эмуляция fills;
- в `result.json -> verification_warnings` добавляется явное предупреждение
  `"rd_variant_used=2_manual_bars_request: order/fill semantics may differ from Strategy Analyzer"`;
- проводится сверка с ручным Strategy Analyzer на той же стратегии/инструменте/периоде;
- расхождения по количеству сделок, ценам входа/выхода и PnL фиксируются в
  `verification_warnings` и обсуждаются до закрытия MVP-0.

Вариант 2 — это **исследовательский spike**, не основной путь. Он не должен
становиться «своим backtest engine».

### Вариант 3 — ОТВЕРГНУТ

UI automation Strategy Analyzer через клики/SendKeys. Не реализуется.

## Ограничения MVP-0

- одна стратегия за запуск (`@SampleMACrossOver.cs` для первой проверки);
- один инструмент;
- один timeframe;
- один период;
- параллельные прогоны запрещены (один активный job на один экземпляр NT).

## Что НЕ делает PoC

- не слушает HTTP/gRPC;
- не работает с UI/frontend;
- не вызывает AI;
- не компилирует произвольный C# из job;
- не отправляет ничего наружу localhost'а.

## Структура исходников

Фаза A (queue lifecycle, без backtest API) — уже реализована:

```
bridge/
├── README.md                           — этот файл
├── NTAnalyzerBridge.csproj             — .NET Framework 4.8, ссылки на
│                                         NinjaTrader.Core / .Gui / .Custom + Newtonsoft.Json
├── NTAnalyzerBridge.config.example.json
└── src/
    ├── BridgeAddOn.cs                  — точка входа (наследует NinjaTrader.NinjaScript.AddOnBase)
    ├── Config/
    │   └── BridgeConfig.cs             — загрузка/валидация config.json
    ├── JobQueue/
    │   ├── JobQueueWatcher.cs          — поллер pending/, claim/finalize через Directory.Move,
    │   │                                 recovery зависших running/
    │   ├── HeartbeatWriter.cs          — heartbeat.json раз в HeartbeatIntervalMs
    │   └── CancelFlagChecker.cs        — мониторинг cancel.flag
    ├── Execution/
    │   ├── StrategyLoader.cs           — reflection whitelist NinjaTrader.Custom.dll
    │   └── HistoricalRunner.cs         — IHistoricalRunner + Phase-A заглушка
    │                                     (возвращает failed/not_implemented)
    └── Util/
        ├── AtomicFile.cs               — write-temp-then-rename
        └── BridgeLog.cs                — файловый лог в <ninjatrader_user_dir>\log\NTAnalyzerBridge.log
```

Фаза B добавит к Execution/: Variant 1 Strategy Analyzer hookup, TradeCollector,
к Reporting/: ResultBuilder, RunHashCalculator, ErrorReporter, и к Util/: Sha256.

## Сборка и установка DLL (Phase A)

Сборка из корня проекта (никакого admin не нужно):

```powershell
dotnet build "C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer\bridge\NTAnalyzerBridge.csproj" -c Debug
```

По умолчанию csproj ищет engine-DLL в `C:\Program Files\NinjaTrader 8\bin`
и `NinjaTrader.Custom.dll` в `%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom`.
Переопределить можно через `-p:NinjaTraderInstallDir=...` и `-p:NinjaTraderUserDir=...`.

Развернуть собранный DLL в NinjaTrader.
Согласно официальной документации NinjaTrader (Visual Studio AddOn workflow:
[AddOn Development Overview](https://ninjatrader.com/support/helpGuides/nt8/addon_development_overview.htm),
[Developing Add Ons](https://ninjatrader.com/support/helpguides/nt8/developing_add_ons.htm))
внешние DLL с AddOn-классами кладутся в `NinjaTrader 8\bin\Custom\`,
а **не** во вложенную `bin\Custom\AddOns\` (там лежат только исходники
NinjaScript-AddOn-ов, скомпилированные внутри NT). Используй готовый скрипт:

```powershell
& "C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer\tools\install-bridge.ps1"
```

Скрипт собирает проект, копирует `NTAnalyzerBridge.dll` в
`%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\` и кладёт `config.json`
(если ещё нет) рядом с примером.

После этого перезапустить NinjaTrader. AddOn должен:

- появиться в `Tools → New → ...` (если в текущем NT8 build виден),
- создать `<ninjatrader_user_dir>\log\NTAnalyzerBridge.log` с записью «config loaded …»
  и «whitelisted strategies: N»,
- начать сканировать `<projectRoot>/jobs/pending/`.

Контрольный smoke-test: положить в очередь job-папку (двухшаговый протокол через
`pending/.staging/<id>/` → `Directory.Move` → `pending/<id>/`); ожидаемый исход —
job уезжает в `failed/<id>/` с `error_type=not_implemented`. Это и есть критерий
успеха Phase A: AddOn реально живёт внутри NinjaTrader и двигает state machine.

## Конфигурация AddOn

Путь до корня проекта (`<projectRoot>/jobs/...`) AddOn читает из конфигурационного
файла `%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.config.json`
(рядом с собранным DLL, как и сам DLL).

См. готовый пример: [`NTAnalyzerBridge.config.example.json`](NTAnalyzerBridge.config.example.json).

Если файл отсутствует — AddOn пишет предупреждение в `NTAnalyzerBridge.log` и
не запускает поллер. Никаких задач без явного конфига.

Установка конфига выполняется автоматически скриптом
[`tools/install-bridge.ps1`](../tools/install-bridge.ps1) (см. выше).
Если нужно вручную:

```powershell
$src = "C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer\bridge\NTAnalyzerBridge.config.example.json"
$dst = "$env:USERPROFILE\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.config.json"
Copy-Item -Path $src -Destination $dst
```

После этого открой `$dst` и при необходимости поправь `project_root` /
`ninjatrader_user_dir` под свою машину.
