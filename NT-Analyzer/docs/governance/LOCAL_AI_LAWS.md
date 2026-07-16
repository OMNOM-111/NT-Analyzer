# LOCAL_AI_LAWS

Дата актуализации: 2026-07-15

Короткий свод законов для локального ИИ и узкого облачного fallback в AI Lab sandbox.

## Локальный ИИ и cloud fallback в AI Lab sandbox

### GOV-AI-001 — Локальный ИИ пишет только в sandbox

- Значение: `Да`
- Суть: AI Lab не пишет production class, production CELL и не трогает рабочие стратегии напрямую.
- Источники: `NT-Analyzer/docs/AI_STRATEGY_LAB_RUN_CONTROLS.md`, `NT-Analyzer/docs/AI_STRATEGY_LAB_QUALITY.md`, `NT-Analyzer/ai_lab/prompts/system_coder.txt`
- Автосинхронизация: app/ai_lab/knowledge.py, app/ai_lab/generator.py, app/ai_lab/guards.py

### GOV-AI-002 — Локальный ИИ не запускает live/paper/demo/account actions

- Значение: `Да`
- Суть: AI Lab делает только историческое исследование и не имеет права на runtime/account операции.
- Источники: `NT-Analyzer/docs/AI_STRATEGY_LAB_RUN_CONTROLS.md`, `NT-Analyzer/ai_lab/prompts/system_coder.txt`
- Автосинхронизация: app/ai_lab/knowledge.py, app/ai_lab/goal_parser.py

### GOV-AI-003 — Локальный ИИ не использует AddDataSeries

- Значение: `Да`
- Суть: Sandbox-стратегии только single instrument / single timeframe.
- Источники: `NT-Analyzer/docs/AI_STRATEGY_LAB_QUALITY.md`, `NT-Analyzer/ai_lab/prompts/system_coder.txt`
- Автосинхронизация: app/ai_lab/knowledge.py, app/ai_lab/validator.py

### GOV-AI-004 — Локальный ИИ обязан задавать явное PT-окно входа

- Значение: `06:30-12:30 PT`
- Суть: По умолчанию sandbox shell использует фиксированное PT entry window и force-flat на конце окна.
- Источники: `NT-Analyzer/ai_lab/prompts/system_coder.txt`
- Автосинхронизация: app/ai_lab/generator.py, app/ai_lab/knowledge.py

### GOV-AI-005 — Локальный ИИ обязан задавать stop/target/daily loss/force-flat

- Значение: `Да`
- Суть: Без явной risk shell стратегия считается невалидной.
- Источники: `NT-Analyzer/ai_lab/prompts/system_coder.txt`, `NT-Analyzer/docs/AI_STRATEGY_LAB_QUALITY.md`
- Автосинхронизация: app/ai_lab/generator.py, app/ai_lab/knowledge.py, app/ai_lab/validator.py

### GOV-AI-006 — Локальный ИИ обязан опираться на reference library

- Значение: `Да`
- Суть: Новая стратегия не генерируется из пустого контекста; сначала reference + lessons + rejected patterns.
- Источники: `NT-Analyzer/ai_lab/prompts/system_coder.txt`, `NT-Analyzer/app/ai_lab/knowledge.py`
- Автосинхронизация: app/ai_lab/knowledge.py, app/ai_lab/prompts/system_coder.txt

### GOV-AI-007 — Облачный API работает только как local-first fallback

- Значение: `Да`
- Суть: Платная модель вызывается только после зафиксированной неудачи разрешённой локальной роли; API не является основным двигателем run.
- Источники: `NT-Analyzer/docs/AI_LAB_CLOUD_AGENTS.md`
- Автосинхронизация: app/ai_lab/cloud_agents.py, app/ai_lab/orchestrator.py, app/ai_lab/generator.py

### GOV-AI-008 — Бюджет облачного API имеет жёсткие потолки

- Значение: `20.00 USD/month; 0.50 USD/run`
- Суть: Вызов блокируется до обращения к провайдеру, если reservation превышает месячный или per-run остаток.
- Источники: `NT-Analyzer/docs/AI_LAB_CLOUD_AGENTS.md`
- Автосинхронизация: app/ai_lab/cloud_agents.py, ui AI Lab cloud-agent settings
- Ручная проверка: provider invoice versus local cost audit

### GOV-AI-009 — API output не является verdict

- Значение: `Да`
- Суть: Cloud-ответ не может обойти validator, compile, backtest, arbitration, governance или ручное promotion-решение.
- Источники: `NT-Analyzer/docs/AI_LAB_CLOUD_AGENTS.md`, `NT-Analyzer/docs/AI_STRATEGY_LAB_QUALITY.md`
- Автосинхронизация: app/ai_lab/cloud_agents.py, app/ai_lab/orchestrator.py

### GOV-AI-010 — Облачные ключи и prompts не раскрываются

- Значение: `Да`
- Суть: Ключи хранятся только локально; status API возвращает флаги. Cloud usage audit хранит prompt hash и usage, но не prompt/response text.
- Источники: `NT-Analyzer/docs/AI_LAB_CLOUD_AGENTS.md`
- Автосинхронизация: app/local_secrets.py, app/ai_lab/cloud_agents.py

### GOV-AI-011 — Вопрос об исследовании не является командой запуска

- Значение: `Да`
- Суть: Вопросы о выборе стратегии и обсуждение гипотез дают содержательный ответ без изменения mission state; запуск разрешён только явной командой владельца в текущем сообщении.
- Автосинхронизация: app/ai_lab/chief_agent.py

### GOV-AI-012 — LM Studio обязательна до начала research

- Значение: `3 bounded self-heal attempts`
- Суть: До создания эксперимента Orchestrator самостоятельно запускает LM Studio и model server; fallback разрешён только после трёх зафиксированных неудач либо по явной команде владельца.
- Автосинхронизация: app/ai_lab/chief_agent.py, app/ai_lab/bootstrap.py

### GOV-AI-013 — Уведомления владельцу только по изменению фактов

- Значение: `Да`
- Суть: Нормальный ход работы не отправляется; один experiment и одно завершение mission дают не более одного отчёта, а полностью одинаковое Telegram-сообщение подавляется на 24 часа.
- Автосинхронизация: app/ai_lab/chief_agent.py, app/telegram_service.py

### GOV-AI-014 — Одна стратегия до исчерпания гипотез

- Значение: `Да`
- Суть: Orchestrator меняет фильтры, входы, выходы и режимы внутри одной основы и переходит к следующей только после кандидата либо доказанного исчерпания содержательно разных вариантов.
- Автосинхронизация: app/ai_lab/chief_agent.py, app/ai_lab/runner.py

### GOV-AI-015 — Содержательное обсуждение использует strongest reasoning lane

- Значение: `Да`
- Суть: Обсуждение, диагностика, выбор стратегии и планирование идут через critical-маршрут к самой сильной доступной модели; простые операционные команды остаются в быстром маршруте.
- Автосинхронизация: app/ai_lab/chief_agent.py, app/ai_lab/agent_router.py

### GOV-AI-016 — Ответ менеджера обязан быть контекстным и завершённым

- Значение: `Да`
- Суть: Перед стратегическим ответом читаются project docs, reference library, lessons, user research и фактические эксперименты; короткий, обещающий или оборванный ответ автоматически заменяется полным, а команда «начинай» продолжает согласованный план этого чата.
- Автосинхронизация: app/ai_lab/chief_agent.py, app/ai_lab/knowledge.py, app/ai_lab/universal_llm.py

### GOV-AI-017 — ИИ-роли улучшаются через конкурентную обратную связь

- Значение: `Да`
- Суть: Роли Analyst/Coder/Judge/Reviewer сравниваются по проверяемому результату; слабый ответ не наказывается, а получает детальный feedback и временно меньший приоритет следующего вызова, пока не восстановит качество.
- Источники: `NT-Analyzer/docs/AI_LAB_COMPETITIVE_FEEDBACK.md`
- Автосинхронизация: governance docs, docs/AI_LAB_COMPETITIVE_FEEDBACK.md
- Ручная проверка: app/ai_lab/agent_router.py role ranking, agent usage/feedback ledger, AI Lab UI feedback report

### GOV-AI-018 — Переподключение NinjaTrader не подменяет торговое соединение Datafeed

- Значение: `Да`
- Суть: Автоматический reconnect разрешён только для фактически активной Realtime-стратегии на paper/demo-счёте; системные Backtest/Sim/Playback-счета, исторические экземпляры, live-счета и Datafeed исключены. Bridge не выбирает неоднозначное соединение и не отключает другие соединения автоматически.
- Автосинхронизация: app/ai_lab/chief_agent.py, app/runtime.py, bridge/src/Runtime/RuntimeCommandProcessor.cs

### GOV-AI-019 — Оркестратор не вправе отказать в выполнимой задаче

- Значение: `Да`
- Суть: До ответа «не могу» Orchestrator обязан проверить детерминированный intent и все штатные обработчики capability_map. Если действие доступно внутри приложения, оно передаётся профильному исполнителю независимо от выбранной версии модели и без требования назвать персону. Отказ допустим только вне карты возможностей либо при фактической ошибке инфраструктуры; причина и доступный следующий шаг указываются явно.
- Автосинхронизация: app/ai_lab/intent_classifier.py, app/ai_lab/capability_map.py, app/ai_lab/chief_agent.py

### GOV-AI-020 — Команды понимаются по смыслу, а подтверждение следует факту

- Значение: `Да`
- Суть: Перед маршрутизацией Orchestrator нормализует речь, раскладку и однозначные тикеры; уверенные команды исполняются детерминированно, неоднозначные короткие команды проверяет быстрая модель только в пределах capability allowlist. Контекст не подменяет явно введённый инструмент, а Telegram не теряет ответ и не подтверждает невыполненное действие.
- Автосинхронизация: app/ai_lab/command_language.py, app/ai_lab/intent_classifier.py, app/ai_lab/capability_map.py, app/telegram_service.py

### GOV-AI-021 — Владелец видит исполнителя и ход работы, но не скрытые рассуждения

- Значение: `Да`
- Суть: Aurora и Telegram показывают фактического агента, модель/provider и проверяемый статус действия. Provider chain-of-thought не сохраняется и не выводится; вместо него используются короткие публичные стадии работы.
- Автосинхронизация: app/ai_lab/chief_agent.py, app/server.py, app/static/aurora/assets/ui.js, app/telegram_service.py

### GOV-AI-022 — Capability закрепляет исполнителя, а завершение подтверждает целевая система

- Значение: `Да`
- Суть: Финансовая capability всегда принадлежит Марине, lifecycle стратегии — Толику, графики — Ивану, runtime connection — Виктору. Модель не может разорвать эту связь. Поручение не становится completed по обещанию или пустому actions: требуется verified completed action либо подтверждение целевой подсистемы.
- Автосинхронизация: app/vitek.py, app/ai_lab/capability_map.py, app/ai_lab/chief_agent.py

### GOV-AI-023 — Один диалог Aurora соответствует одной теме Telegram

- Значение: `Да`
- Суть: Исходная реплика, уточнение, действие и итог сохраняют один conversation_id. При ошибке topic mapping сообщение остаётся в долговечной очереди и не отправляется в General; неизвестная входящая тема не подменяется default-диалогом.
- Автосинхронизация: app/telegram_service.py, app/ai_lab/chief_agent.py, app/durable.py

### GOV-AI-024 — Отрицание запрещает действие, а пояснение возвращается тому же исполнителю

- Значение: `Да`
- Суть: Фразы «не запускай», «ничего не восстанавливай» и вопросы о причине не превращаются в команды. Ответ владельца на needs_input передаётся в том же диалоге и тому же профильному агенту; подтверждение не подписывается именем другого специалиста.
- Автосинхронизация: app/ai_lab/intent_classifier.py, app/ai_lab/chief_agent.py, app/vitek.py
