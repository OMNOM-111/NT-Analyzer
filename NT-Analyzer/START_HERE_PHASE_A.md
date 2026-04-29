# Историческая памятка: Phase A

Этот файл оставлен как история ранней проверки bridge skeleton. Текущий
статус проекта см. в `README.md` и `../ГЛАВНЫЙ_ПЛАН.txt`: MVP-1 работает,
bridge baseline вручную сверён с NinjaTrader Strategy Analyzer и принят для
дальнейшей разработки стратегий.

# Что делали на Phase A

Сейчас проект НЕ находится на этапе готового приложения с браузером, backend и frontend.

Текущий этап: **Phase A / MVP-0 Bridge skeleton**.

Цель текущего этапа:
- проверить, что NinjaTrader загружает `NTAnalyzerBridge.dll`;
- проверить, что AddOn читает файловую очередь;
- проверить, что job переезжает `pending -> running -> failed`;
- ожидаемая ошибка сейчас: `error_type = "not_implemented"`, потому что реальный Strategy Analyzer runner еще не написан.

Что уже сделано:
- создан проект `NT-Analyzer`;
- создана файловая очередь `jobs/`;
- создан C# AddOn skeleton;
- AddOn собирается через `dotnet build`;
- есть scripts для установки bridge и создания smoke job.

Что еще НЕ сделано:
- backend API;
- frontend UI;
- браузерное приложение;
- AI workflow;
- финальный ярлык "запустить всю платформу";
- реальный запуск Strategy Analyzer.

## Как запускать текущую проверку без PowerShell-команд

Используй `.cmd` файлы в корне `NT-Analyzer`:

1. Полностью закрой NinjaTrader.
2. Двойной клик по `01_INSTALL_BRIDGE.cmd`.
3. Запусти NinjaTrader вручную.
4. Подожди 5-10 секунд.
5. Двойной клик по `03_CHECK_PHASE_A_STATUS.cmd`.

Если smoke job еще не создан:

6. Двойной клик по `02_CREATE_SMOKE_JOB.cmd`.
7. Через 5-10 секунд снова запусти `03_CHECK_PHASE_A_STATUS.cmd`.

## Что считается успехом Phase A

В логе должно быть примерно:
- `config loaded`
- `whitelisted strategies: N`
- `SampleMACrossOver found in whitelist`
- `Queue watcher started`

В очереди smoke job должен уйти в:

`jobs/failed/<job_id>/error.json`

И внутри должно быть:

`"error_type": "not_implemented"`

Это нормальный успех текущего этапа. Это значит: AddOn живет внутри NinjaTrader и очередь работает.

Только после этого можно давать задачу на реальный Variant 1 Strategy Analyzer.
