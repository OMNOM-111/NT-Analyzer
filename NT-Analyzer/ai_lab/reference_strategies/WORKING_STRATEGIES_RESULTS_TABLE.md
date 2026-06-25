# Working Reference Strategies Results Table

**Period tested:** 2025-12-01 to 2026-06-06 (~6 months)
**Instrument:** MNQ 06-26
**Timeframe:** 15m bars
**Fill resolution:** High
**Slippage:** 1 tick
**Commission:** $1.90 per round turn (adjusted from strategy internals)
**Date generated:** 2026-06-07

---

## Results Table

| ID | Strategy | Source | Kind | Compile | Trades | Gross P&L | Net Before Comm | PF Before | Net After Comm | PF After Comm | Max DD After | Win% | Verdict |
|----|----------|--------|------|---------|--------|-----------|-----------------|-----------|----------------|----------------|--------------|------|---------|
| WEX-001 | SMA 9/21 Crossover | kodalli/NT8-PAT-Strategy (MIT) | adapted | ✅ OK | 605 | $2,796 | -$352 | 0.888 | **-$1,502** | 0.610 | -$1,562 | 38.5% | working_losing |
| WEX-002 | EMA Trend Pullback | kodalli/NT8-PAT-Strategy (MIT) | adapted | ✅ OK | 569 | $1,240 | -$614 | 0.669 | **-$1,695** | 0.358 | -$1,701 | 27.2% | working_losing |
| WEX-003 | Inside Bar Breakout | ayb/ninjatrader (MIT) | adapted | ✅ OK | 511 | $2,328 | -$356 | 0.868 | **-$1,326** | 0.596 | -$1,347 | 38.0% | working_losing |
| WEX-004 | BB + EMA + RSI | diogenesmonteiro (no license) | adapted | ✅ OK | 241 | $648 | -$68 | 0.905 | **-$526** | 0.484 | -$526 | 33.6% | working_losing |
| WEX-005 | RSI + ADX Trend | diogenesmonteiro (no license) | adapted | ✅ OK | 6 | $0 | -$27 | 0.000 | **-$38** | 0.000 | -$38 | 0.0% | working_losing (≈zero trades) |
| WEX-006 | MACD + RSI Trend | njmathews/AlgoTrading (MIT) | adapted | ✅ OK | 3,814 | $25,258 | -$1,129 | 0.957 | **-$8,375** | 0.732 | -$8,387 | 33.7% | working_losing (overtrading) |
| WEX-007 | Donchian Breakout | public domain (Turtle rules) | fresh NT8 | ✅ OK | 496 | $5,370 | +$467 | 1.095 | **-$475** | 0.914 | -$928 | 36.1% | working_losing (near-break-even before comm) |
| WEX-008 | ORB AI Sandbox | AI Strategy Lab AI-CELL-001 | existing | ✅ already | 333 | $1,995 | -$103 | 0.951 | **-$736** | 0.703 | -$736 | 39.9% | working_losing |
| WEX-009 | RSI EMA Pullback AI | AI Strategy Lab AI-CELL-017 | existing | ✅ already | **0** | $0 | $0 | — | $0 | — | $0 | — | working_zero_trade |
| WEX-010 | Volatility AI | AI Strategy Lab AI-CELL-011 | existing | ✅ already | **0** | $0 | $0 | — | $0 | — | $0 | — | working_zero_trade |
| WEX-011 | Price Direction AI | AI Strategy Lab AI-CELL-012 | existing | ✅ already | 321 | $1,965 | -$29 | 0.986 | **-$638** | 0.729 | -$653 | 40.8% | working_losing |
| WEX-012 | Price Movement AI | AI Strategy Lab AI-CELL-013 | existing | ✅ already | 308 | $1,845 | -$96 | 0.951 | **-$681** | 0.703 | -$681 | 39.9% | working_losing |

---

## Compile Results

| ID | Class Name | Compile Status | Errors | Notes |
|----|-----------|----------------|--------|-------|
| WEX-001 | NTARefLibSmaCrossoverW001 | ✅ SUCCESS | 0 | Currency→Ticks adapted |
| WEX-002 | NTARefLibEmaPullbackW002 | ✅ SUCCESS | 0 | Multi-instrument removed |
| WEX-003 | NTARefLibInsideBarW003 | ✅ SUCCESS | 0 | Sandbox-safe rewrite |
| WEX-004 | NTARefLibBbEmaStochW004 | ✅ SUCCESS | 0 | StochRSI → RSI proxy |
| WEX-005 | NTARefLibRsiAdxW005 | ✅ SUCCESS | 0 | BarSpeed removed, ATR proxy |
| WEX-006 | NTARefLibMacdRsiTrendW006 | ✅ SUCCESS | 0 | SuperTrend → EMA slope |
| WEX-007 | NTARefLibDonchianBreakoutW007 | ✅ SUCCESS | 0 | Fresh NT8 implementation |

**Build command:** `dotnet build NinjaTrader.Custom.csproj -c Debug`
**Result:** 0 errors, 1050 warnings (all pre-existing, not from new strategies)

---

## Commission Impact Summary

| ID | Trades | Commission Cost | Net Before | Net After | Commission Destroyed Edge? |
|----|--------|----------------|------------|-----------|---------------------------|
| WEX-001 | 605 | -$1,150 | -$352 | -$1,502 | Yes — added $1,150 drag |
| WEX-002 | 569 | -$1,081 | -$614 | -$1,695 | Yes — amplified loss |
| WEX-003 | 511 | -$971 | -$356 | -$1,326 | Yes — added $970 drag |
| WEX-004 | 241 | -$458 | -$68 | -$526 | Yes — turned near-break-even to loss |
| WEX-005 | 6 | -$11 | -$27 | -$38 | Negligible (almost no trades) |
| WEX-006 | 3,814 | -$7,247 | -$1,129 | -$8,375 | **CATASTROPHIC** — 3814 trades × $1.90 |
| WEX-007 | 496 | -$942 | +$467 | -$475 | Yes — turned profitable to losing |
| WEX-008 | 333 | -$633 | -$103 | -$736 | Yes — amplified loss |

**Key insight:** Commission ($1.90 RT) is the #1 killer. WEX-007 Donchian was the ONLY strategy profitable before commission. Even a PF of 1.095 before commission becomes 0.914 after.

---

## Verdict Legend

| Status | Meaning |
|--------|---------|
| `working_profitable` | Compiles, runs, PF > 1 after commission |
| `working_losing` | Compiles, runs, has trades, but losing after commission |
| `working_zero_trade` | Compiles, runs, but 0 trades (parameter or logic issue) |
| `compile_failed` | Did not compile |

---

*Generated: 2026-06-07*
