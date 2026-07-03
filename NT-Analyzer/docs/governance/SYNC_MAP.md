# SYNC_MAP

Дата актуализации: 2026-07-03

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
