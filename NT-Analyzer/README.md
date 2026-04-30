# NT-Analyzer

Новый отдельный проект — «Анализатор стратегий NinjaTrader».
Архитектурная основа и правила: см. `../ГЛАВНЫЙ_ПЛАН.txt`.

## Текущая стадия

**MVP-1 — validated baseline / рабочий инструмент для разработки стратегий.**

Bridge, backend, UI, launcher, каталог стратегий/инструментов, одиночные
запуски и batch-запуски работают через NinjaTrader runtime. NinjaTrader
остаётся источником истины: платформа только ставит задания, читает результат,
показывает отчёты и хранит историю.

Risk Profile в UI пока работает как информационный профиль счёта: стартовый
капитал, intraday/overnight режим и данные маржи из локального Margin Catalog
сохраняются в job/result и показываются в отчёте, но не ограничивают сделки до добавления общего
RiskManager в конкретные стратегии.

## Status

- **Phase A (AddOn loads, file queue works):** PASSED.
- **Phase B PoC backtest (Variant 1):** PASSED.
  - Smoke job `smoke_20260427T053651448Z`:
    `metrics.trade_count=9232`, `result.trades.length=9232`,
    `trades.json=9232 entries`.
  - Working path: **PathA2 = `StrategyBase.RunBacktest()`** (public
    parameterless instance method).
  - **Optimizer.RunBacktest** (private static, "PathA") is **R&D opt-in only**
    via `enable_path_a_optimizer_runbacktest=true` in
    `NTAnalyzerBridge.config.json`. In NT 8.1.6.3 it reliably throws NRE
    outside the Strategy Analyzer host.
  - Required for trade history extraction:
    `StrategyBase.IncludeTradeHistoryInBacktest = true` (set automatically by
    the bridge before backtest start).
- **MVP-1 (CLI + local backend + minimal UI + launcher):** functional PASSED.
  - End-to-end verified job `ui_20260427T063706266Z` via launcher
    (`00_START_NT_ANALYZER.cmd` → `start.ps1` → `app.server` →
    bridge AddOn → `done`):
    `trade_count=9232`, `winning_pct=33.6763`, `net_profit=-7118.75`,
    `gross_profit=95887.5`, `gross_loss=-103006.25`,
    `profit_factor=0.9309`, `max_drawdown=-8938.75`.
  - Backend bound to **127.0.0.1 only**; mutating `POST /api/jobs` requires
    `Content-Type: application/json` and rejects browser cross-site Origins.
  - UI status badge / job-table cells rendered via DOM builders
    (no innerHTML for API-supplied values).
- **Manual cross-check vs NinjaTrader Strategy Analyzer UI:** PASSED.
  Bridge baseline is accepted as matching NinjaTrader Strategy Analyzer for
  further strategy-development work. Keep validation records in
  `docs/manual-validation.md` when the bridge/execution settings change.

## Запуск

Обычный сценарий (NinjaTrader уже установлен и bridge развёрнут):

1. Открыть NinjaTrader 8 вручную (дождаться Control Center).
2. Двойной клик по `00_START_NT_ANALYZER.cmd`.
3. Браузер откроется на `http://127.0.0.1:8765/ui/` (или ближайшем
   свободном порту 8766..8774).
4. Tab **Run** → заполнить параметры → Submit → переключиться на **Jobs**
   (auto-refresh каждые 2 с) → клик по строке когда `status=done` →
   tab **Result** покажет метрики и список сделок.

Обновление bridge AddOn после изменений в `bridge/src/`:

1. Полностью закрыть NinjaTrader 8.
2. Запустить `01_INSTALL_BRIDGE.cmd` (rebuild + copy DLL в
   `Documents\NinjaTrader 8\bin\Custom\`).
3. Снова открыть NinjaTrader, дождаться загрузки AddOn (см.
   `Documents\NinjaTrader 8\log\NTAnalyzerBridge.log`).

## Известные ограничения

- `read_trades` парсит `trades.json` целиком, потом slice'ит по
  `offset/limit`. Для текущих ~10k сделок норм; при сильно больших
  прогонах позже перейти на JSONL/SQLite.
- Manual cross-check против Strategy Analyzer UI выполнен и принят как
  baseline. Повторная сверка обязательна после изменений в bridge execution
  path, commission/trading-hours применении или контракте результата.

## Структура папок

```
NT-Analyzer/
├── README.md                 — этот файл
├── jobs/                     — файловая очередь заданий (см. план, раздел 8)
│   ├── pending/              — новые задания от backend/CLI
│   ├── running/              — задания, которые сейчас исполняет AddOn
│   ├── done/                 — успешно завершённые задания + result.json
│   ├── failed/               — упавшие задания + error.json
│   └── cancelled/            — отменённые через cancel.flag
├── docs/
│   └── job-schema.md         — описание контракта job.json / result.json (v0)
├── examples/
│   ├── job.example.json      — пример минимального задания для MVP-0
│   └── result.example.json   — пример минимального результата
├── bridge/                   — C# NinjaScript AddOn (.NET Framework 4.8)
│   └── README.md             — план PoC AddOn
└── runs/                     — артефакты прогонов (создаётся позже)
```

## Цель MVP-0

Один критерий успеха:
**реальный исторический прогон одной заранее выбранной стратегии
(например, `@SampleMACrossOver.cs`) на одном инструменте, одном timeframe,
одном периоде через NinjaTrader runtime, с возвратом нормализованного
`result.json` со сделками и базовыми метриками.**

CLI или минимальный backend endpoint показывает результат.
Никакого frontend.

## Правила работы с файловой очередью

См. `../ГЛАВНЫЙ_ПЛАН.txt`, раздел 8, и подробный протокол в
`docs/job-schema.md` (раздел «State machine очереди»).

- каждый job — это **папка** `<job_id>/`, а не одиночный файл; внутри лежат
  `job.json`, `heartbeat.json`, `result.json`/`error.json`, артефакты;
- создание задания — двухшаговое: сначала `pending/.staging/<job_id>/` со всеми
  файлами через write-temp-then-rename, потом атомарный `Directory.Move`
  staging → `pending/<job_id>/`;
- переходы `pending → running → done/failed/cancelled` — только через
  атомарный `Directory.Move` всей папки job;
- запись отдельных файлов внутри папки (`job.json`, `result.json`, `heartbeat.json`,
  артефакты) — только write-temp-then-rename (`*.tmp` → `File.Move` → финальное имя)
  на одном томе;
- bridge регулярно обновляет `heartbeat.json` рядом с running job;
- если heartbeat устарел дольше TTL — backend помечает job как failed с причиной "bridge timeout";
- отмена — через `cancel.flag` рядом с job, AddOn периодически проверяет;
- запрещено отменять прогон через kill процесса NinjaTrader.

## Стек

- bridge / AddOn: C# на .NET Framework 4.8 (требование NinjaTrader 8), внутри NT runtime.
- backend: выбирается на этапе MVP-0 после успешного PoC и фиксируется в `docs/`.
- транспорт: файловая очередь на локальном диске (HTTP/gRPC — позже).
