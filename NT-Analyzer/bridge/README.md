# NTAnalyzerBridge

C# NinjaTrader 8 AddOn, который работает внутри NinjaTrader runtime и связывает
NinjaTrader с локальным NT-Analyzer.

## Назначение

Bridge выполняет четыре рабочие задачи:

- читает файловую очередь `NT-Analyzer/jobs/pending`;
- запускает исторические backtest-задания через NinjaTrader runtime;
- пишет результаты в `jobs/done`, `jobs/failed` или `jobs/cancelled`;
- экспортирует catalog/runtime telemetry для web UI.

Bridge не принимает произвольный C# код из job. Исполняются только стратегии,
которые уже скомпилированы в `NinjaTrader.Custom.dll` и найдены через whitelist.

## Сборка

```powershell
dotnet build bridge\NTAnalyzerBridge.csproj -c Debug
```

Проект target'ит `.NET Framework 4.8`, как требует NinjaTrader 8.

По умолчанию ссылки ищутся здесь:

- `C:\Program Files\NinjaTrader 8\bin`
- `%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom`

Если NinjaTrader установлен в другом месте, передай MSBuild properties:

```powershell
dotnet build bridge\NTAnalyzerBridge.csproj -c Debug `
  -p:NinjaTraderInstallDir="D:\NinjaTrader 8\bin" `
  -p:NinjaTraderUserDir="D:\NinjaTraderUser"
```

## Установка

Обычный способ:

```powershell
.\tools\install-bridge.ps1
```

Скрипт:

- проверяет, что NinjaTrader закрыт;
- собирает `NTAnalyzerBridge.csproj`;
- копирует `NTAnalyzerBridge.dll` в
  `%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom`;
- создает конфиг, если его еще нет;
- создает структуру очереди `jobs/`.

После установки нужно открыть NinjaTrader заново.

## Конфиг

Файл:

`%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.config.json`

Пример:

`bridge/NTAnalyzerBridge.config.example.json`

Ключевые поля:

- `project_root` — путь к `NT-Analyzer`;
- `ninjatrader_user_dir` — путь к `%USERPROFILE%\Documents\NinjaTrader 8`;
- `poll_interval_ms` — частота проверки очереди;
- `heartbeat_interval_ms` — частота heartbeat running job.

## Runtime outputs

Bridge пишет локальные runtime-файлы в:

`NT-Analyzer/data/runtime/`

Основные файлы:

- `heartbeat.json`;
- `accounts.json`;
- `strategies.json`;
- `positions.json`;
- `orders.jsonl`;
- `executions.jsonl`;
- `errors.jsonl`;
- `commands.jsonl`;
- `command_results.jsonl`;
- `strategy_history.jsonl`.

Эти файлы являются локальным состоянием и не предназначены для Git.

## Queue contract

Задание — это папка job:

- `pending/<job_id>/job.json`;
- `running/<job_id>/heartbeat.json`;
- `done/<job_id>/result.json`;
- `failed/<job_id>/error.json`;
- `cancelled/<job_id>/`.

Все переходы выполняются атомарным перемещением папки.

Подробный контракт: `../docs/job-schema.md`.
