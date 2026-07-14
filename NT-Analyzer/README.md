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

## Telegram

1. В BotFather отзови любой токен, который когда-либо публиковался, и создай новый.
2. В web UI открой `Системные действия -> Telegram`.
3. Вставь новый токен. Он сохраняется только в gitignored-файле
   `data/integrations/secrets.local.json` и не возвращается через API.
4. Нажми `Создать ссылку`, открой бота, нажми Start и затем
   `Проверить подключение` в приложении.
5. Включи главный переключатель и нужные типы уведомлений, после чего отправь тест.

Поддерживаются состояния приложения и стратегий, связь с NinjaTrader, ошибки,
важные новости и сводки за день/неделю/месяц. Aurora также работает как
Telegram Mini App через HTTPS-туннель: доступ выдаётся по одноразовому коду,
проверке Telegram-контакта и явному подтверждению владельца. Whitelist,
роли и мгновенный отзыв находятся в том же экране Telegram. Live-торговля
из Mini App запрещена, а paper/demo сохраняет backend-подтверждения.
Полная настройка: `docs/TELEGRAM_MINI_APP.md`.

Дежурный контролёр **Витёк** ведёт инциденты и задачи, принимает решения из
Telegram или приложения, показывает временные окна стратегий и продолжает
контроль без открытого браузера. Он отвечает по умолчанию, но Управляющего,
Секретаря, Заместителя, Марину, Толика, Никиту и Ивана можно вызвать напрямую
по имени в том же чате. Закрытые темы попадают в изолированный общий архив
памяти рабочей области. Для постоянной работы один раз запустите
`00_INSTALL_VITEK_BACKGROUND.cmd`. Инструкция: `docs/VITEK.md`.

Если Telegram Desktop или смена браузера открыли бота без параметра входа,
экран авторизации показывает ручную команду `/login КОД`. Её можно отправить
боту вместо ссылки. Для переносимой Mini App установки `cloudflared.exe` можно
положить прямо в `tools/cloudflared/cloudflared.exe`; этот путь проверяется
раньше системного PATH.

Доступ к API, включая localhost desktop UI, требует персонального Telegram-
аккаунта. Вход выполняется через одноразовую ссылку в бота и `requestContact`;
для нового пользователя обязательны имя, фамилия, e-mail и принятие условий.
Владелец получает уведомление и может заблокировать доступ. Профили и сессии
хранятся в Windows DPAPI CurrentUser.
`accounts.dpapi` нельзя переносить между Windows-компьютерами как общий файл:
при копировании папки на новый ПК приложение изолирует чужой DPAPI-файл как
backup и создаёт новый локальный store после повторной Telegram-проверки.

План перехода от одного владельческого контура к отдельным пользователям,
подпискам, промокодам и личным NinjaTrader-подключениям описан в
`docs/MULTI_USER_ACCOUNT_ARCHITECTURE.md`.
Текущий технический backlog по отказоустойчивости, безопасности и
производительности: `docs/RESILIENCE_SECURITY_BACKLOG_2026-07-10.md`.
Фактический статус последнего полного аудита, команды проверки и оставшиеся
неблокирующие ограничения: `docs/PRODUCTION_READINESS_2026-07-13.md`.

## Облачный fallback AI Lab

На странице AI Lab есть блок **Облачные AI-агенты**: безопасное добавление
DeepSeek/Gemini ключей, назначения «роль → модель», актуальная сравнительная
таблица цен и жёсткие лимиты `$20/месяц`, `$0.50/run`. Контур по умолчанию
выключен и вызывается только после локальной неудачи; API не может изменить
arbitration verdict или получить доступ к paper/live. Инструкция:
`docs/AI_LAB_CLOUD_AGENTS.md`. Актуальная role-aware production-схема,
benchmark, стоимость и результаты historical-only циклов:
`docs/AI_AGENT_STACK_RESEARCH_2026-07-01.md`.

## Обновление bridge

1. Полностью закрой NinjaTrader 8.
2. Запусти `01_INSTALL_BRIDGE.cmd`.
3. Снова открой NinjaTrader 8.
4. Проверь `%USERPROFILE%\Documents\NinjaTrader 8\log\NTAnalyzerBridge.log`.

## Проверки

```powershell
python -m pytest -q
python -m tests
dotnet build bridge\NTAnalyzerBridge.csproj -c Debug
```

`pytest` является полным регрессионным комплектом, а `python -m tests` —
коротким release-runner из 13 крупных наборов. Перед выпуском запускаются оба.

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
