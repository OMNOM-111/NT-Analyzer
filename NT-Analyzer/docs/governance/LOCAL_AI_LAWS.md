# LOCAL_AI_LAWS

Дата актуализации: 2026-06-29

Короткий свод законов только для локального ИИ / AI Lab sandbox.

## Локальный ИИ и AI Lab sandbox

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
