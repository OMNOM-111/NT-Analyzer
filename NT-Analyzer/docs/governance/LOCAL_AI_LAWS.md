# LOCAL_AI_LAWS

Дата актуализации: 2026-07-10

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
