# AI Strategy Reference Library

## Purpose

This is a **research and reference** library of public trading strategies, concepts,
and archetypes for use by AI Strategy Lab when generating new strategy candidates.

**This library is NOT a Portfolio. It is a research/reference base.**

Even if a strategy here compiles or produces trades in backtest,
it does NOT become a production strategy without separate human approval.

## What is here

25 cataloged strategies/archetypes from public sources, covering:

- Crossover / Trend following
- Mean reversion
- Breakout
- Pattern / Level
- Combined / Filtered

Each strategy has:
- `source.md` — source URL, author, license
- `normalized_spec.md` — standardized spec AI can read
- `ai_lesson.md` — what AI should learn from this strategy
- `verdict.md` — usability verdict, risks, do-not-use reasons

## Mandatory rules

1. **No live trading.** Nothing here is approved for live execution.
2. **No paper/demo auto-start.** Do not configure any strategy here for paper/demo.
3. **No real orders.** No broker API usage.
4. **No production strategy changes.** These are reference-only.
5. **No locked strategy changes.** Do not modify production strategies.
6. **No portfolio addition.** Do not add any reference strategy to Portfolio.
7. **Source URL required.** All strategies must have a source URL.
8. **License note required.** All strategies must have a license note.
9. **Unknown license = `license_unknown_reference_only`.** Use as reference, not production code.
10. **No foreign code as production strategy** without human approval.
11. **Historical backtest only.**
12. **Backtest parameters (if run):**
    - `OrderFillResolution = High`
    - `slippage_ticks >= 1`
    - `RoundTurnCommission >= 1.90`
    - Metrics reported after commission

## How AI uses this library

Before generating any new AI-CELL strategy, the AI MUST:

1. Read `ai_lessons/LESSONS_SUMMARY.md`
2. Read lessons from AI-CELL-004, AI-CELL-005, AI-CELL-006
3. Find the closest matching reference strategy family
4. Read its `normalized_spec.md` and `ai_lesson.md`
5. Choose:
   - 1 reference strategy/pattern
   - 1 lesson from failed AI-CELL
   - 1 modification hypothesis

**Example usage:**
> "Берём ORB reference (REF-011), но после AI-CELL-005 избегаем overtrading,
> добавляем VWAP direction filter и max 2 trades/day."

## Directory structure

```
reference_strategies/
  README.md                        ← this file
  SOURCES.md                       ← all source URLs by category
  LICENSE_NOTES.md                 ← license analysis
  reference_registry.json          ← machine-readable registry of all strategies
  REFERENCE_STRATEGY_LIBRARY_REPORT.md  ← final summary report

  REF-001/                         ← SMA Crossover
  REF-002/                         ← EMA Crossover
  REF-003/                         ← EMA Trend Pullback
  REF-004/                         ← MACD Histogram Trend
  REF-005/                         ← SuperTrend
  REF-006/                         ← RSI(2) Mean Reversion
  REF-007/                         ← Bollinger Bands Mean Reversion
  REF-008/                         ← VWAP Pullback
  REF-009/                         ← VWAP Mean Reversion
  REF-010/                         ← RSI Extremes Mean Reversion
  REF-011/                         ← Opening Range Breakout
  REF-012/                         ← Opening Range Retest
  REF-013/                         ← Donchian Channel Breakout
  REF-014/                         ← Previous Day High/Low Breakout
  REF-015/                         ← Range Compression Breakout
  REF-016/                         ← Previous Day High/Low Reclaim
  REF-017/                         ← Liquidity Sweep Reversal
  REF-018/                         ← ATR Breakout Momentum
  REF-019/                         ← Gap Fill / Gap Fade
  REF-020/                         ← Trend Continuation Pullback
  REF-021/                         ← ORB + VWAP Filter
  REF-022/                         ← Breakout + Volume Expansion Filter
  REF-023/                         ← EMA Stack (3 EMA)
  REF-024/                         ← VWAP + RSI Combined
  REF-025/                         ← MACD + RSI Confirmation

  ai_lessons/                      ← aggregate lessons for AI
    LESSONS_SUMMARY.md
    FAILED_CELL_LESSONS.md
    PATTERN_EFFECTIVENESS.md

  useful_patterns/                 ← curated pattern snippets
    entry_patterns.md
    exit_patterns.md
    filter_patterns.md
    risk_patterns.md

  rejected/                        ← rejected strategies
    REJECTED_LIST.md

  raw_sources/                     ← raw source code copies (if applicable)
  normalized_specs/                ← normalized spec index
  nt8_ports/                       ← NT8 port sandbox (reference only)
  compile_reports/                 ← compile attempt reports
  backtest_reports/                ← backtest result reports
```

## Status legend

| status | meaning |
|--------|---------|
| `reference_spec_only` | Concept-level spec, no NT8 code |
| `nt8_ready_reference` | NT8 code exists in reference sandbox |
| `compile_ok` | Compiled successfully (reference sandbox only) |
| `compile_failed` | Compile failed, errors saved |
| `backtest_run` | Backtest executed |
| `rejected` | Not suitable for use |

## Created

Date: 2026-06-06
Version: 1.0
