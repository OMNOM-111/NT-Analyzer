# Reference Strategy Library Report

**Date:** 2026-06-06
**Version:** 1.0
**Status:** Initial population complete

---

## Executive Summary

The AI Strategy Reference Library has been successfully created and populated.
The library provides 25 cataloged strategy archetypes from public sources to serve
as a reference base for AI Strategy Lab, so models no longer generate strategies
from empty context.

**Key outcome:** AI-CELL-007 and beyond now have a structured reference foundation
instead of generating trading ideas from scratch.

---

## 1. Sources Found

| Category | Count | Source Type |
|----------|-------|------------|
| Academic / public domain concepts | 15 | Books, Investopedia, StockCharts |
| Published trading systems | 3 | Connors, Crabel, Turtle rules |
| Educational content | 4 | BabyPips, ICT concepts |
| NinjaTrader ecosystem | 3 | Forum, NT8 documentation |
| **Total sources** | **25** | |

---

## 2. Strategies Added to Registry

**Total: 25 strategies**

| ID | Name | Family | License |
|----|------|--------|---------|
| REF-001 | SMA 9/21 Crossover | crossover_trend | permissive |
| REF-002 | EMA 8/21 Crossover | crossover_trend | permissive |
| REF-003 | EMA Trend Pullback | trend_pullback | permissive |
| REF-004 | MACD Histogram Trend | crossover_trend | permissive |
| REF-005 | SuperTrend | trend_following | permissive |
| REF-006 | RSI(2) Mean Reversion | mean_reversion | reference_only |
| REF-007 | Bollinger Bands Mean Reversion | mean_reversion | permissive |
| REF-008 | VWAP Pullback | vwap_pullback | permissive |
| REF-009 | VWAP Mean Reversion | vwap_mean_reversion | permissive |
| REF-010 | RSI Extremes Mean Reversion | mean_reversion | permissive |
| REF-011 | Opening Range Breakout | breakout_orb | reference_only |
| REF-012 | Opening Range Retest | breakout_orb | permissive |
| REF-013 | Donchian Channel Breakout | breakout_channel | permissive |
| REF-014 | Previous Day H/L Breakout | breakout_level | permissive |
| REF-015 | Range Compression Breakout | breakout_compression | reference_only |
| REF-016 | Previous Day H/L Reclaim | breakout_level | permissive |
| REF-017 | Liquidity Sweep Reversal | reversal_sweep | license_unknown_reference_only |
| REF-018 | ATR Breakout Momentum | breakout_momentum | permissive |
| REF-019 | Gap Fill / Gap Fade | gap_fade | permissive |
| REF-020 | Trend Continuation Pullback | trend_pullback | permissive |
| REF-021 | ORB + VWAP Filter | breakout_filtered | permissive |
| REF-022 | Breakout + Volume Filter | breakout_filtered | permissive |
| REF-023 | EMA Stack (3 EMA) | trend_following | permissive |
| REF-024 | VWAP + RSI Combined | mean_reversion_filtered | permissive |
| REF-025 | MACD + RSI Confirmation | trend_following | permissive |

---

## 3. NT8-Ready Strategies

All 25 strategies are classified as `reference_spec_only`.
None have been compiled or ported to NT8 in this initial population.

**Reason:** These are concept-level references.
NT8 ports happen only when AI-CELL selects a reference to adapt.

**Status breakdown:**

| Status | Count |
|--------|-------|
| reference_spec_only | 25 |
| nt8_ready_reference | 0 |
| compile_ok | 0 |
| compile_failed | 0 |
| backtest_run | 0 |

---

## 4. Compile Status

Not applicable at this stage. Backtest execution will occur when AI-CELL-007/008
selects a reference to adapt and generates NT8 code.

---

## 5. Backtest Status

Not applicable at this stage. No NT8 code has been generated from references yet.

**Note:** CELL-019 results for similar patterns ARE documented in individual strategy
files and ai_lessons, providing proxy backtest data for strategy selection.

**Proxy data from CELL-019 (applicable references):**

| Reference | Closest CELL-019 Engine | Result |
|-----------|------------------------|--------|
| REF-008 (VWAP Pullback) | E5 RTH VWAP Pullback | Full PF 1.171 DD -$298 (near-pass on MGC) |
| REF-009 (VWAP Fade) | E2 VWAP Fade 5m | 518 trades gross $756=$1.46/trade (REJECTED) |
| REF-011/012 (ORB) | E7/E8 ORB Retest | REJECTED — OOS PF < 1.25 |
| REF-015 (Compression) | PreCash Compression | REJECTED — near-zero |
| REF-017 (Liquidity Sweep) | CELL-015 production | ACCEPTED — active in demo |
| REF-019 (Gap Fade) | E3/E4 Settlement | REJECTED — deeply negative |
| REF-020 (Trend Pullback) | E6 RTH Trend H1 | REJECTED — 2025 regime shift |

---

## 6. Pattern Analysis

### Patterns That Showed Promise (Reference)

1. **VWAP Pullback (REF-008)** — MGC near-pass (PF 1.171 Full) in CELL-019
   - Needs: stronger OOS filter, additional direction confirmation
   - Candidate for: AI-CELL-007 adaptation

2. **Liquidity Sweep Reversal (REF-017)** — Foundation of only ACCEPTED strategy
   - CELL-015 is active production reference
   - Candidate for: variations (different window, different instrument)

3. **ORB + VWAP (REF-021)** — Composite of two robust concepts
   - Not yet tested in NT-Analyzer; strong theoretical basis
   - Candidate for: AI-CELL-007 or AI-CELL-008

4. **EMA Trend Pullback (REF-003)** — Classic R:R improvement over crossover
   - Not yet tested in NT-Analyzer
   - Candidate for: AI-CELL-007 or AI-CELL-008

5. **PDH/PDL Breakout (REF-014)** — Clean levels, proven institutional reference
   - Not yet tested; simple enough for reliable NT8 implementation
   - Candidate for: AI-CELL-008

### Patterns That Are Risky (Reference: Do Not Use Standalone)

1. **Gap Fade (REF-019)** — Structurally negative on 2024-2025 equity index micros
   - Settlement reversion and settlement breakout both rejected in CELL-019
   - May work on MGC/MCL; needs regime filter

2. **VWAP Mean Reversion 5m (REF-009)** — Commission drag structural
   - $1.46/trade gross < $1.90 commission = guaranteed losses at scale
   - Not viable on micros at $1.90/RT unless TF >= 15m and larger targets

3. **Compression Without Direction (REF-015)** — Random direction = 0 edge
   - PreCash Compression CELL-019 rejected
   - Viable only WITH directional filter (EMA + VWAP combined)

4. **RSI(2) Connors (REF-006)** — Daily TF system, no stop, not suited for pipeline
   - Educational reference only; RSI(2) as filter in other strategies is useful

---

## 7. Patterns Useful for Future AI-CELL

### Top 10 Reference Patterns for AI-CELL-007/008/009

**Priority 1 — Highest Recommendation:**
1. **REF-021: ORB + VWAP Filter**
   - Why: Two robust concepts combined; VWAP reduces false ORB breakouts
   - Suggested use: "Берём ORB, max 2 trades/day, VWAP alignment required"
   - Target: MNQ 15m RTH

2. **REF-003: EMA Trend Pullback**
   - Why: Higher R:R than crossovers; natural stop at EMA
   - Suggested use: ADX>25, EMA20/EMA50 stack, max 2 trades/day
   - Target: MNQ 15m or MGC 1H

3. **REF-017: Liquidity Sweep Reversal (variant)**
   - Why: CELL-015 accepted = pattern works on pre-RTH MNQ
   - Suggested use: Vary window (RTH morning) or instrument (MES)
   - Target: MNQ or MES pre-RTH or early RTH

**Priority 2 — Good Candidates:**
4. **REF-014: PDH/PDL Breakout**
   - Clean institutional levels; simple to code correctly

5. **REF-008: VWAP Pullback** (with additional filter)
   - Near-passed gates on MGC; needs stronger OOS confirmation

6. **REF-020: Trend Continuation Pullback** (with regime filter)
   - Needs prior-day range filter to handle 2025 regime

**Priority 3 — Filter Patterns (use as components, not standalone):**
7. **REF-022: Volume Expansion Filter** — add to any breakout
8. **REF-010: RSI Extremes** — use as confirmation filter, not sole signal
9. **REF-023: EMA Stack** — use as trend regime filter
10. **REF-025: MACD + RSI** — prevents chasing extended moves

---

## 8. Patterns That Cannot Be Used (Standalone)

| Pattern | Reason |
|---------|--------|
| REF-009 (VWAP Fade 5m) | Commission drag structural at $1.90/RT |
| REF-019 (Gap Fade) | Regime mismatch 2024-2025 equity index |
| REF-015 (Compression no direction) | No edge without directional filter |
| REF-006 (RSI(2) Connors) | No stop, daily TF, not suitable for pipeline |
| Any martingale/grid | Absolute prohibition |

---

## 9. License Risks

| License Status | Count | Action |
|----------------|-------|--------|
| `permissive` | 21 | Can adapt to NT8 from scratch |
| `reference_only` | 3 | Use rules only; no book code reproduction |
| `license_unknown_reference_only` | 1 | Study/concept only (REF-017) |
| `not_usable` | 0 | None in library |

### Specific License Risks

**REF-006 (Connors RSI):** Book concepts are published but system is proprietary.
Use the entry/exit RULES (publicly described), not any code from Connors' tools.

**REF-011/REF-015 (Crabel ORB/NR7):** Published in 1990 book. General concept is
public domain. Specific optimized parameters are Crabel's research. Use standard
parameters only (30-min ORB, 7-bar NR7).

**REF-017 (Liquidity Sweep / ICT):** ICT terminology and specific patterns are
associated with Michael Huddleston who has been involved in disputes.
Use the GENERAL CONCEPT (stop hunt reversal) in NT8 code without ICT attribution.

---

## 10. Educational and Reference-Only Strategies

All 25 strategies are currently educational/reference-only:
- No NT8 code has been generated from these references yet
- No strategies have been added to Portfolio
- All are in `ai_lab/reference_strategies/` — separate from production

---

## 11. Strategies to Remove or Not Use

None of the 25 cataloged strategies require removal.
The rejected patterns are documented in `rejected/REJECTED_LIST.md`.

Specifically NOT in this library (by design):
- Martingale systems
- Grid averaging systems
- Systems requiring live account API
- Strategies with unclear/dangerous logic
- Strategies with unrealistic fill assumptions only

---

## 12. What AI Must Read Before Creating New Strategy

### Mandatory Pre-Generation Reading List

**Always read (for any new AI-CELL):**
1. `ai_lab/reference_strategies/ai_lessons/LESSONS_SUMMARY.md`
   - 10 critical rules including commission economics, position sizing trap, stale assembly
2. `ai_lab/reference_strategies/ai_lessons/FAILED_CELL_LESSONS.md`
   - Detailed CELL-019 engine results and NT8 API bad list
3. `ai_lab/reference_strategies/ai_lessons/PATTERN_EFFECTIVENESS.md`
   - Tier 1/2/3 pattern rankings with evidence

**Then read (based on chosen reference):**
4. Chosen reference `normalized_spec.md` (e.g., `REF-021/normalized_spec.md`)
5. `useful_patterns/entry_patterns.md` — NT8 code snippets for entry
6. `useful_patterns/exit_patterns.md` — NT8 code snippets for exit
7. `useful_patterns/risk_patterns.md` — Risk management template

**Before code generation:**
8. `rejected/REJECTED_LIST.md` — Anti-patterns to exclude

### Required Format for AI Strategy Hypothesis

AI must state before generating any code:
```
Reference Pattern: [REF-XXX name]
Failed CELL Lesson Applied: [e.g., "CELL-019 Engine #2: commission drag on 5m"]
Modification Hypothesis: [e.g., "Add VWAP filter to reduce false breakouts"]
Gross/Trade Economics: [e.g., "15m ATR ≈ $25, target 2 ATR = $50 >> $1.90 commission"]
Position Sizing Check: [e.g., "Stop 12 ticks = $6 + $1.90 = $7.90 contractRisk, byRisk=1"]
Instrument/TF: [e.g., "MNQ 15m RTH"]
Max Trades/Day: [e.g., "2 per direction, 4 total"]
```

---

## 13. Summary Statistics

| Metric | Value |
|--------|-------|
| Total strategies cataloged | 25 |
| Sources documented | 25 |
| NT8-ready reference code | 0 (all reference_spec_only) |
| Compile attempts | 0 |
| Backtest attempts | 0 |
| Proxy backtest data (from CELL-019) | 7 patterns |
| Strategies with permissive license | 21 |
| Strategies with reference_only license | 3 |
| Strategies with unknown license | 1 |
| Top recommended for AI-CELL-007 | 3 (REF-021, REF-003, REF-017 variant) |
| Anti-patterns documented in rejected/ | 10 |
| NT8 code snippets in useful_patterns/ | 15+ |
| Critical rules in LESSONS_SUMMARY.md | 10 |

---

## 14. Next Steps

### Immediate (AI-CELL-007)
1. AI reads mandatory pre-generation list above
2. AI selects REF-021 (ORB + VWAP) as primary reference
3. AI states modification hypothesis: "ORB + VWAP, max 2 trades/day, ATR stop"
4. AI generates NT8 C# code from scratch (not copied)
5. Compile and iterate (max 2 autofix attempts)
6. Run Smoke → Full → IS → OOS → Stress pipeline
7. Verdict: accept or reject with lessons documented

### Library Maintenance
- After each AI-CELL completion: add ai_lesson.md to corresponding REF folder
- After each CELL run: update PATTERN_EFFECTIVENESS.md with new evidence
- After regime changes: update FAILED_CELL_LESSONS.md

---

*Generated: 2026-06-06*
*Library path:* `NT-Analyzer/ai_lab/reference_strategies/`
*Registry:* `NT-Analyzer/ai_lab/reference_strategies/reference_registry.json`
