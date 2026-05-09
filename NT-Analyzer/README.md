# NT-Analyzer

Рабочая локальная платформа для разработки и проверки NinjaTrader-стратегий
совместно с AI.

Главная инструкция по текущему состоянию проекта находится в
`../ПОДРОБНАЯ_ИНСТРУКЦИЯ.txt`.

## Что делает система

- Запускает backtest-задания через NinjaTrader runtime.
- Показывает web UI для backtesting, strategy profiles, coverage и online runtime.
- Хранит историю jobs локально в `jobs/`.
- Читает каталог стратегий, инструментов и шаблонов из NinjaTrader через bridge.
- Экспортирует runtime telemetry из NinjaTrader в `data/runtime/`.
- Позволяет отправлять enable/disable команды уже загруженным strategy instances.

NinjaTrader остается источником истины по исполнению стратегии, сделкам,
метрикам и runtime-состоянию.

## Запуск

1. Открой NinjaTrader 8 вручную.
2. Дождись загрузки Control Center и bridge AddOn.
3. Запусти `00_START_NT_ANALYZER.cmd`.
4. Открой web UI: `http://127.0.0.1:8765/ui/`.

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
python -m tests.test_ops
python -m tests.test_runtime
python -m tests.test_scc
python -m tests.test_trading
dotnet build bridge\NTAnalyzerBridge.csproj -c Debug
```

Тесты запускаются как Python-модули, а не через `pytest`.

## Основные папки

- `app/` — backend API и static UI server.
- `app/static/` — web UI.
- `bridge/` — NinjaTrader AddOn.
- `data/profiles/` — активные Strategy Profiles и coverage.
- `docs/` — технические контракты.
- `jobs/` — локальная очередь и история запусков, не для Git.
- `ninjatrader/strategies/` — исходники стратегий проекта.
- `tests/` — runner-тесты.
- `tools/` — установочные и служебные скрипты.
