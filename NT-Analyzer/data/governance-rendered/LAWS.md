# LAWS

Дата актуализации: 2026-08-24T16:33:38Z

Короткий свод действующих проектных законов для пользователей и системы StratForge AI.

## Капитал и риск

### GOV-RISK-001 — Базовый StartingCapital на одну deploy-ячейку

- Значение: `2000.00 USD`
- Суть: Новые исследования и новые профили стартуют от одного общего allocated capital.
- Важно: Смена capital меняет только общий дефолт. Исторические результаты и существующие locked profiles требуют ручной ревалидации.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `NT-Analyzer/docs/strategies/risk-profile.md`
- Автосинхронизация: app/jobqueue.py research gate, app/ai_lab/backtest.py, app/ai_lab/generator.py, app/ai_lab/knowledge.py, tools/research/python/research_lib.py, ui backtest defaults, ui AI Lab capital presets
- Ручная проверка: existing ready/paper profiles with locked StartingCapital, data/ops/registry.json and trading runtime cards, historical research bundles and legacy strategy registry docs

### GOV-RISK-002 — Promotion gate по MaxDD

- Значение: `15%`
- Суть: Абсолютный drawdown не должен превышать долю от зафиксированного StartingCapital.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `tools/research/python/research_lib.py`
- Автосинхронизация: tools/research/python/research_lib.py drawdown gate, ui docs sync
- Ручная проверка: legacy reports that mention fixed -$300 drawdown budget


## Комиссии, slippage и fill

### GOV-RISK-003 — Минимальная честная комиссия backtest

- Значение: `1.90 USD`
- Суть: Research и AI Lab не используют значение ниже project floor за round turn на контракт.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md`, `NT-Analyzer/ai_lab/prompts/system_coder.txt`
- Автосинхронизация: app/jobqueue.py research gate, app/ai_lab/backtest.py, app/ai_lab/generator.py, app/ai_lab/knowledge.py, tools/research/python/research_lib.py
- Ручная проверка: ops metrics that depend on per-strategy locked params, legacy paper/demo profiles with older fee assumptions

### GOV-RISK-004 — Минимальный slippage для research

- Значение: `1 ticks`
- Суть: Рабочие проверки не используют slippage ниже project floor.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md`, `NT-Analyzer/ai_lab/prompts/system_coder.txt`
- Автосинхронизация: app/jobqueue.py research gate, app/ai_lab/backtest.py, app/ai_lab/generator.py, app/ai_lab/knowledge.py, tools/research/python/research_lib.py
- Ручная проверка: legacy reports with slip=1/slip=2 commentary

### GOV-RISK-005 — Базовый fill mode

- Значение: `High`
- Суть: Research-grade проверки идут только через High fill.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `NT-Analyzer/docs/strategies/AI_STRATEGY_LAB_QUALITY.md`
- Автосинхронизация: app/jobqueue.py validation, tools/research/python/research_lib.py build_job_body


## Процесс разработки

### GOV-PROC-001 — Канонический цикл разработки

- Значение: `Research Hub -> Deploy wrapper`
- Суть: Новые стратегии проходят путь Research Hub -> Deploy wrapper.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `РАЗРАБОТКА СТРАТЕГИЙ/Реестр стратегий.md`
- Автосинхронизация: governance docs only
- Ручная проверка: legacy references to missing transition documents

### GOV-PROC-002 — IntradayOnly по умолчанию

- Значение: `Да`
- Суть: Новые исследования и новые профили по умолчанию считаются без overnight-hold.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `NT-Analyzer/docs/strategies/risk-profile.md`
- Автосинхронизация: ui backtest risk profile defaults, tools/research/python/research_lib.py
- Ручная проверка: existing profiles with explicit IntradayOnly=false


## Promotion и runtime-контроль

### GOV-PROC-003 — Paper forward обязателен до live

- Значение: `Да`
- Суть: Live запрещён без paper_ready, журнала и отдельного ручного решения владельца.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `NT-Analyzer/app/ops.py`
- Автосинхронизация: governance docs, ui docs sync
- Ручная проверка: manual operating procedures

### GOV-PROC-004 — Runtime instance должен совпадать с locked params

- Значение: `Да`
- Суть: Перед paper/demo запуском runtime-параметры не должны расходиться с утвержденным профилем.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`, `NT-Analyzer/app/static/trading.js`
- Автосинхронизация: governance docs

### GOV-PROC-005 — NinjaTrader — источник истины по backtest

- Значение: `Да`
- Суть: Результаты принимаются только из канонического пути NT-Analyzer bridge -> NinjaTrader.
- Источники: `РАЗРАБОТКА СТРАТЕГИЙ/Общие правила разработки стратегий.md`
- Автосинхронизация: governance docs
