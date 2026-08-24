# SYNC_MAP

Дата актуализации: 2026-08-24T04:22:21Z

Этот файл показывает, что именно меняется автоматически после редактирования закона, а что остаётся на ручную проверку.

## GOV-RISK-001 — Базовый StartingCapital на одну deploy-ячейку

- Текущее значение: `2000.00 USD`
- Автоматически обновляется: app/jobqueue.py research gate, app/ai_lab/backtest.py, app/ai_lab/generator.py, app/ai_lab/knowledge.py, tools/research/python/research_lib.py, ui backtest defaults, ui AI Lab capital presets
- Нужно проверить вручную: existing ready/paper profiles with locked StartingCapital, data/ops/registry.json and trading runtime cards, historical research bundles and legacy strategy registry docs

## GOV-RISK-002 — Promotion gate по MaxDD

- Текущее значение: `15%`
- Автоматически обновляется: tools/research/python/research_lib.py drawdown gate, ui docs sync
- Нужно проверить вручную: legacy reports that mention fixed -$300 drawdown budget

## GOV-RISK-003 — Минимальная честная комиссия backtest

- Текущее значение: `1.90 USD`
- Автоматически обновляется: app/jobqueue.py research gate, app/ai_lab/backtest.py, app/ai_lab/generator.py, app/ai_lab/knowledge.py, tools/research/python/research_lib.py
- Нужно проверить вручную: ops metrics that depend on per-strategy locked params, legacy paper/demo profiles with older fee assumptions

## GOV-RISK-004 — Минимальный slippage для research

- Текущее значение: `1 ticks`
- Автоматически обновляется: app/jobqueue.py research gate, app/ai_lab/backtest.py, app/ai_lab/generator.py, app/ai_lab/knowledge.py, tools/research/python/research_lib.py
- Нужно проверить вручную: legacy reports with slip=1/slip=2 commentary

## GOV-RISK-005 — Базовый fill mode

- Текущее значение: `High`
- Автоматически обновляется: app/jobqueue.py validation, tools/research/python/research_lib.py build_job_body
- Нужно проверить вручную: —

## GOV-PROC-001 — Канонический цикл разработки

- Текущее значение: `Research Hub -> Deploy wrapper`
- Автоматически обновляется: governance docs only
- Нужно проверить вручную: legacy references to missing transition documents

## GOV-PROC-002 — IntradayOnly по умолчанию

- Текущее значение: `Да`
- Автоматически обновляется: ui backtest risk profile defaults, tools/research/python/research_lib.py
- Нужно проверить вручную: existing profiles with explicit IntradayOnly=false

## GOV-PROC-003 — Paper forward обязателен до live

- Текущее значение: `Да`
- Автоматически обновляется: governance docs, ui docs sync
- Нужно проверить вручную: manual operating procedures

## GOV-PROC-004 — Runtime instance должен совпадать с locked params

- Текущее значение: `Да`
- Автоматически обновляется: governance docs
- Нужно проверить вручную: —

## GOV-PROC-005 — NinjaTrader — источник истины по backtest

- Текущее значение: `Да`
- Автоматически обновляется: governance docs
- Нужно проверить вручную: —

## GOV-AI-001 — Локальный ИИ пишет только в sandbox

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/knowledge.py, app/ai_lab/generator.py, app/ai_lab/guards.py
- Нужно проверить вручную: —

## GOV-AI-002 — Локальный ИИ не запускает live/paper/demo/account actions

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/knowledge.py, app/ai_lab/goal_parser.py
- Нужно проверить вручную: —

## GOV-AI-003 — Локальный ИИ не использует AddDataSeries

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/knowledge.py, app/ai_lab/validator.py
- Нужно проверить вручную: —

## GOV-AI-004 — Локальный ИИ обязан задавать явное PT-окно входа

- Текущее значение: `06:30-12:30 PT`
- Автоматически обновляется: app/ai_lab/generator.py, app/ai_lab/knowledge.py
- Нужно проверить вручную: —

## GOV-AI-005 — Локальный ИИ обязан задавать stop/target/daily loss/force-flat

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/generator.py, app/ai_lab/knowledge.py, app/ai_lab/validator.py
- Нужно проверить вручную: —

## GOV-AI-006 — Локальный ИИ обязан опираться на reference library

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/knowledge.py, app/ai_lab/prompts/system_coder.txt
- Нужно проверить вручную: —

## GOV-AI-007 — Облачный API работает только как local-first fallback

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/cloud_agents.py, app/ai_lab/orchestrator.py, app/ai_lab/generator.py
- Нужно проверить вручную: —

## GOV-AI-008 — Бюджет облачного API имеет жёсткие потолки

- Текущее значение: `20.00 USD/month; 0.50 USD/run`
- Автоматически обновляется: app/ai_lab/cloud_agents.py, ui AI Lab cloud-agent settings
- Нужно проверить вручную: provider invoice versus local cost audit

## GOV-AI-009 — API output не является verdict

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/cloud_agents.py, app/ai_lab/orchestrator.py
- Нужно проверить вручную: —

## GOV-AI-010 — Облачные ключи и prompts не раскрываются

- Текущее значение: `Да`
- Автоматически обновляется: app/local_secrets.py, app/ai_lab/cloud_agents.py
- Нужно проверить вручную: —

## GOV-AI-011 — Вопрос об исследовании не является командой запуска

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/chief_agent.py
- Нужно проверить вручную: —

## GOV-AI-012 — LM Studio обязательна до начала research

- Текущее значение: `3 bounded self-heal attempts`
- Автоматически обновляется: app/ai_lab/chief_agent.py, app/ai_lab/bootstrap.py
- Нужно проверить вручную: —

## GOV-AI-013 — Уведомления владельцу только по изменению фактов

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/chief_agent.py, app/telegram_service.py
- Нужно проверить вручную: —

## GOV-AI-014 — Одна стратегия до исчерпания гипотез

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/chief_agent.py, app/ai_lab/runner.py
- Нужно проверить вручную: —

## GOV-AI-015 — Содержательное обсуждение использует strongest reasoning lane

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/chief_agent.py, app/ai_lab/agent_router.py
- Нужно проверить вручную: —

## GOV-AI-016 — Ответ менеджера обязан быть контекстным и завершённым

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/chief_agent.py, app/ai_lab/knowledge.py, app/ai_lab/universal_llm.py
- Нужно проверить вручную: —

## GOV-AI-017 — ИИ-роли улучшаются через конкурентную обратную связь

- Текущее значение: `Да`
- Автоматически обновляется: governance docs, docs/AI_LAB_COMPETITIVE_FEEDBACK.md
- Нужно проверить вручную: app/ai_lab/agent_router.py role ranking, agent usage/feedback ledger, AI Lab UI feedback report

## GOV-AI-018 — Переподключение NinjaTrader не подменяет торговое соединение Datafeed

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/chief_agent.py, app/runtime.py, bridge/src/Runtime/RuntimeCommandProcessor.cs
- Нужно проверить вручную: —

## GOV-AI-019 — Оркестратор не вправе отказать в выполнимой задаче

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/intent_classifier.py, app/ai_lab/capability_map.py, app/ai_lab/chief_agent.py
- Нужно проверить вручную: —

## GOV-AI-020 — Команды понимаются по смыслу, а подтверждение следует факту

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/command_language.py, app/ai_lab/intent_classifier.py, app/ai_lab/capability_map.py, app/telegram_service.py
- Нужно проверить вручную: —

## GOV-AI-021 — Владелец видит исполнителя и ход работы, но не скрытые рассуждения

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/chief_agent.py, app/server.py, app/static/aurora/assets/ui.js, app/telegram_service.py
- Нужно проверить вручную: —

## GOV-AI-022 — Capability закрепляет исполнителя, а завершение подтверждает целевая система

- Текущее значение: `Да`
- Автоматически обновляется: app/vitek.py, app/ai_lab/capability_map.py, app/ai_lab/chief_agent.py
- Нужно проверить вручную: —

## GOV-AI-023 — Один диалог Aurora соответствует одной теме Telegram

- Текущее значение: `Да`
- Автоматически обновляется: app/telegram_service.py, app/ai_lab/chief_agent.py, app/durable.py
- Нужно проверить вручную: —

## GOV-AI-024 — Отрицание запрещает действие, а пояснение возвращается тому же исполнителю

- Текущее значение: `Да`
- Автоматически обновляется: app/ai_lab/intent_classifier.py, app/ai_lab/chief_agent.py, app/vitek.py
- Нужно проверить вручную: —


<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-24T04:22:21Z | GPT-5.5 через Codex по запросу owner | Зафиксировать отклонение beta.30 Canary после воспроизводимого saturation и минимальное исправление consumer viewport history range без изменения принятого TopstepX/SignalR baseline.
-->
