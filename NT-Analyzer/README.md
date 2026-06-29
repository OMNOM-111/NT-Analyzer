# NT-Analyzer

Рабочая локальная платформа для разработки, проверки и операционного контроля
NinjaTrader-стратегий совместно с AI.

Главная инструкция по текущему состоянию проекта находится в
`../ПОДРОБНАЯ_ИНСТРУКЦИЯ.txt`.

## Что делает система

- Запускает backtest-задания через NinjaTrader runtime.
- Показывает web UI для backtesting, strategy profiles, coverage и online runtime.
- Хранит историю jobs локально в `jobs/`.
- Читает каталог стратегий, инструментов и шаблонов из NinjaTrader через bridge.
- Экспортирует runtime telemetry из NinjaTrader в `data/runtime/`.
- Позволяет отправлять enable/disable команды уже загруженным strategy instances.
- Запускает AI Strategy Lab для локального цикла idea -> code -> compile ->
  backtest -> arbitration, с sandbox-ограничениями и LM Studio как
  опциональным локальным LLM endpoint.

NinjaTrader остается источником истины по исполнению стратегии, сделкам,
метрикам и runtime-состоянию.

## Запуск

1. Открой NinjaTrader 8 вручную.
2. Дождись загрузки Control Center и bridge AddOn.
3. Запусти `00_START_NT_ANALYZER.cmd`.
4. Открой web UI: `http://127.0.0.1:8765/ui/`.

Для AI Strategy Lab есть отдельный best-effort launcher:

```powershell
.\00_START_AI_LAB.cmd
```

Он пытается запустить NinjaTrader, LM Studio и `lms server start`, затем
открыть `/ui/ai-lab.html`. Модели не грузятся заранее: нужная модель
поднимается только перед конкретным LLM-запросом и выгружается после run.
Если пути отличаются, задайте `NINJATRADER_EXE`, `LM_STUDIO_EXE`, `LMS_CLI`
или создайте `ai_lab/bootstrap.json`.

Прямой запуск backend:

```powershell
python -m app.server 8765
```

## Обновление bridge

1. Полностью закрой NinjaTrader 8.
2. Запусти `01_INSTALL_BRIDGE.cmd`.
3. Снова открой NinjaTrader 8.
4. Проверь `%USERPROFILE%\Documents\NinjaTrader 8\log\NTAnalyzerBridge.log`.

## Проверки

```powershell
python -m tests
dotnet build bridge\NTAnalyzerBridge.csproj -c Debug
```

Тесты можно запускать единым runner'ом `python -m tests`. Отдельные модули
также остаются запускаемыми напрямую.

## Основные папки

- `app/` — backend API и static UI server.
- `app/ai_lab/` — AI Strategy Lab orchestration, validation, LM Studio client,
  compile/backtest pipeline and read models.
- `app/static/` — web UI.
- `ai_lab/prompts/`, `ai_lab/schemas/`, `ai_lab/reference_strategies/` —
  curated AI assets safe for Git.
- `bridge/` — NinjaTrader AddOn.
- `data/profiles/` — локальные Strategy Profiles и coverage; не коммитятся,
  если не подготовлена отдельная sanitized seed/demo version.
- `docs/` — технические контракты.
- `jobs/` — локальная очередь и история запусков, не для Git.
- `ninjatrader/strategies/` — исходники стратегий проекта.
- `tests/` — runner-тесты.
- `tools/` — установочные и служебные скрипты.

## Git hygiene

В Git попадают исходники, тесты, документация, examples, safe static catalog
sources, AI prompts/schemas/reference docs. В Git не попадают runtime queues,
backtest results, reports, local profiles, runtime telemetry, AI experiment
registry, model-call logs, screenshots, caches, bridge build output и личные
research dumps. Подробно: `docs/repository-hygiene.md`.
