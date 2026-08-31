# NT-Analyzer — ядро StratForge AI

**StratForge AI** — торгово-аналитическая платформа для анализа рынков и
стратегий. Она объединяет realtime-графики и market data из нескольких
источников, интеграцию с NinjaTrader 8 через StratForge Connector, команду
AI-агентов, бэктестинг и управление жизненным циклом стратегий в одном
локальном приложении: веб-интерфейс **Aurora** поверх Python-backend.
Режим Simulation/Live определяется подключённым аккаунтом NinjaTrader; paper/demo
команды доступны, а отправка live-команд остаётся `IN DEVELOPMENT — release-gated`
до отдельного owner/regulatory решения.

> `NT-Analyzer` — это репозиторий и технический идентификатор (исходное имя
> проекта). Продукт, который он собирает и запускает, называется StratForge AI.

Актуальные сведения о запуске и структуре ведутся в этом README и в
`docs/DOCS_STRUCTURE.md`. Ранняя историческая подробная инструкция
(NinjaTrader-центричный контур) перенесена в архив:
`docs/archive/ПОДРОБНАЯ_ИНСТРУКЦИЯ.txt`.

## Что делает система

- Показывает Aurora — веб-интерфейс для обзора, бэктестинга, торговли/контроля
  runtime, производительности, стратегий, AI Lab и market-data графиков.
- Строит realtime-графики через **TopstepX как основной независимый read-only
  источник history + realtime** (opt-in по credentials пользователя). При его
  недоступности используется свежий NinjaTrader Connector runtime, затем другой
  разрешённый credentialed provider; delayed/history источник не выдаётся за live.
- NinjaTrader остаётся единственным путём исполнения и источником истины по
  сделкам/runtime. Futures root автоматически разрешается в текущий контракт;
  синтетические свечи не создаются, внешний chart feed не авторизует ордера.
- Запускает backtest-задания через NinjaTrader runtime и хранит историю jobs
  локально в `jobs/`.
- Читает каталог стратегий, инструментов и шаблонов из NinjaTrader через bridge
  и экспортирует runtime telemetry (heartbeat, accounts, positions, orders,
  executions, errors) в `data/runtime/`.
- Позволяет отправлять enable/disable команды уже загруженным strategy instances
  (paper/demo контур; live-исполнение остаётся отдельным gate).
- Запускает AI Strategy Lab для локального цикла idea -> code -> compile ->
  backtest -> arbitration, с sandbox-ограничениями и LM Studio как
  опциональным локальным LLM endpoint.
- Работает в изолированных окружениях Development / Canary / Production с
  продвижением одного immutable-artifact через Release Center.

NinjaTrader остаётся источником истины по исполнению стратегии, сделкам,
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
важные новости и сводки за день/неделю/месяц. Telegram Mini App и mirrored web
UI имеют статус `DEPRECATED`: их маршруты возвращают HTTP 410 и не запускают
туннели, workers или фоновые задачи. Это не отключает Telegram-вход,
идентичность, bot-функции и уведомления текущего продукта.

Дежурный контролёр **Витёк** ведёт инциденты и задачи, принимает решения из
Telegram или приложения, показывает временные окна стратегий и продолжает
контроль без открытого браузера. Он отвечает по умолчанию, но Управляющего,
Секретаря, Заместителя, Марину, Толика, Никиту и Ивана можно вызвать напрямую
по имени в том же чате. Закрытые темы попадают в изолированный общий архив
памяти рабочей области. Для постоянной работы один раз запустите
`00_INSTALL_VITEK_BACKGROUND.cmd`. Инструкция: `docs/VITEK.md`.

Aurora и Telegram показывают одну scoped-историю. Каждое входящее сообщение
Telegram привязывается к активному аккаунту/workspace, а недоставленная копия
из Aurora остаётся в очереди до успешной отправки. Запись production-диалога в
старый общий unscoped-файл запрещена. Webhook и long-poll сначала сохраняют
update в одной долговечной очереди: точные update ID защищают от дублей без
потери сообщений, пришедших не по порядку; разные темы исполняются параллельно,
а сообщения одной темы — последовательно. После трёх ошибок повреждённый update
остаётся в диагностическом карантине и больше не блокирует следующие сообщения.

Если Telegram Desktop или смена браузера открыли бота без параметра входа,
экран авторизации показывает ручную команду `/login КОД`. Её можно отправить
боту вместо ссылки.

Исторический classic UI временно сохранён как отдельный localhost-only Legacy
Viewer. Запуск: `Start StratForge Legacy.cmd`. Viewer использует отдельный
snapshot данных, cookie/storage namespace, не запускает Telegram, trading,
release automation или текущие workers и отклоняет записи. Контракт и границы:
`docs/architecture/LEGACY_VIEWER.md`.

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
`docs/architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md`.
Текущий технический backlog по отказоустойчивости, безопасности и
производительности: `docs/archive/RESILIENCE_SECURITY_BACKLOG_2026-07-10.md`.
Фактический статус последнего полного аудита, команды проверки и оставшиеся
неблокирующие ограничения: `docs/archive/PRODUCTION_READINESS_2026-07-13.md`.

## Облачный fallback AI Lab

На странице AI Lab есть блок **Облачные AI-агенты**: безопасное добавление
DeepSeek/Gemini ключей, назначения «роль → модель», актуальная сравнительная
таблица цен и жёсткие лимиты `$20/месяц`, `$0.50/run`. Контур по умолчанию
выключен и вызывается только после локальной неудачи; API не может изменить
arbitration verdict или получить доступ к paper/live. Инструкция:
`docs/agents/AI_LAB_CLOUD_AGENTS.md`. Актуальная role-aware production-схема,
benchmark, стоимость и результаты historical-only циклов:
`docs/archive/AI_AGENT_STACK_RESEARCH_2026-07-01.md`.

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
