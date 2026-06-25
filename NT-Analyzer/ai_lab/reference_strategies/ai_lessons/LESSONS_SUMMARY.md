# AI Lessons Summary — Reference Strategy Library

## CRITICAL READ BEFORE ANY AI-CELL GENERATION

This document summarizes what AI must know before generating a new strategy.
Read ALL sections. Do not skip.

---

## 1. The Commission Economics Law

**RULE:** Any strategy for $2k MNQ account MUST have gross_per_trade >= $5.00

Math:
- Commission: $1.90 per round turn
- Break-even: $1.90 commission
- Practical minimum: $5.00/trade (to have margin for slippage)

**Violation examples from CELL-019:**
- VWAP Fade 5m: 518 trades, gross $756 = $1.46/trade → REJECTED (below commission)
- Post-Cluster VWAP Fade: near-zero/negative on all variants

**How to verify before building:**
1. Estimate timeframe ATR in dollars: 15m MNQ ATR ≈ $15-40
2. Target = ATR * 2.0 = $30-80 per trade → well above $5 minimum ✓
3. 5m MNQ ATR ≈ $5-10 per target = marginal → risk commission drag

---

## 2. The Position Sizing Trap

**RULE:** Always verify ComputeQuantity produces qty >= 1 before trusting backtest results.

The silent qty=0 bug:
- With StartingCapital=$2000, RiskPerTradePct=0.5-0.75%: riskBudget = $10-15
- ATR stop: 20 ticks * $0.50 = $10 + $1.90 commission + slippage = $12+ contractRisk
- byRisk = floor($12 / $12) = 1 → barely OK
- But ATR=30 ticks: contractRisk=$17 → byRisk=0 → silent no-trade

**Fix (required in all NT8 strategies for $2k account):**
```csharp
if (byMargin >= 1 && byUser >= 1 && contractRisk <= MaxDailyLossUsd)
    qty = Math.Max(1, (int)byRisk);
```

**Diagnostic:** Run ONE wide-open job (window 0000-2359, all filters off).
If trade_count = 0 → check qty computation first.

---

## 3. The Stale Assembly Trap

**RULE:** After ANY code change, FULLY RESTART NinjaTrader before running backtest.

F5 (NinjaScript recompile in NT8 GUI) does NOT update the bridge's executing assembly.
The bridge runs the assembly loaded at NT startup.

Symptom: "0 trades regardless of edits" = STALE ASSEMBLY (not a logic bug).

Checklist:
1. Edit .cs file
2. Build: `dotnet build %USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NinjaTrader.Custom.csproj`
3. Exit NinjaTrader completely (File → Exit)
4. Verify old PID gone: `Get-Process NinjaTrader`
5. Restart NinjaTrader
6. Verify new PID is different
7. POST /api/catalog/refresh
8. Run smoke job

---

## 4. The Same-Bar% Warning

**RULE:** If same_bar_percentage > 50%, stops are too tight for the timeframe's ATR.

Meaning: the strategy enters AND is stopped out within the same bar.
The entry bar's range already exceeds the stop → instant loss.

Observed values from CELL-019:
- Post-Cluster VWAP Fade: same-bar 76-93% → stops too tight
- Post-Cluster Squeeze: same-bar 50-63% → borderline

Fix options:
1. Increase MinStopTicks (widen stop)
2. Use larger timeframe (15m instead of 5m)
3. Switch from stop-at-entry to stop-at-prior-swing

---

## 5. The [Range] Attribute Law

**RULE:** Every NT8 strategy parameter with [Range(min, max)] MUST respect its range.

Violation: Sending a job with param value OUTSIDE its [Range] silently aborts the backtest.
Symptoms: trade_count=0, duration_ms=8-14ms, raw.json shows "BarsArray[0] not found".

Examples:
- MaxConsecutiveLosses=50 vs [Range(0,20)] → kills all C020 jobs
- PauseAfterConsecutiveLosses>480 for [Range(0,480)] → kills all trades

Fix: ALWAYS verify each parameter override is within its declared [Range].

---

## 6. The Regime Stability Warning

**RULE:** A strategy profitable in 2024 is NOT guaranteed to work in 2025 on MNQ.

Evidence:
- Engine #6 RTH Trend-Day H1: 2024 PF 1.44 → 2025 PF 1.07 (regime shift)
- Settlement Reversion: deeply negative in 2024-2025 both
- Post-Cluster: near-pass in 2024, fails 2025

2024-2025 MNQ characteristics:
- 2024: strong bull trend (NQ 16k → 21k)
- 2025: more choppy/reversing
- Strategy that worked in 2020-2022 bull may not work in 2025

Required cross-year testing: always run IS (2024) + OOS (2025) in pipeline.

---

## 7. The Directional Filter Requirement

**RULE:** Any breakout strategy MUST have a directional bias filter.

Without directional filter:
- Compression breakout CELL-019: both directions tried randomly → negative
- Gap fade CELL-019: fade wrong direction on trend days → large losses

Effective directional filters:
1. VWAP: above = bullish bias, below = bearish bias
2. EMA20/EMA50 alignment: EMA20 > EMA50 = uptrend
3. Prior day bias: PDH held = bullish, PDL held = bearish
4. ADX + EMA slope: ADX>25 + rising EMA20 = trend up

---

## 8. The Max Trades/Day Rule (from CELL-005 Overtrading Lesson)

**RULE:** Max 2-3 trades per direction per day. Never unlimited.

CELL-005 showed that unlimited entries in mean-reversion context led to overtrading
during trending days, where each reversion entry became a successive loser.

Implementation:
```csharp
[Range(1, 10)]
private int maxTradesPerDay = 2;
// Track dailyTradeCount, reset on new session
if (dailyTradeCount >= maxTradesPerDay) return; // skip entry
```

---

## 9. The Smoke Mirage Warning

**RULE:** Positive smoke does NOT mean the strategy is viable. Always run Full/IS/OOS.

Known smoke mirages:
- M2K Overnight Settlement Breakout smoke +446.7 → Full -31.6 (collapse)
- MNG Post-Cluster smoke PF 5.73 → Full PF 0.97 (collapse)
- MES Post-Cluster smoke PF 2.8 → Full PF 0.39 (collapse)

Smoke mirage pattern: strategy does well in specific sub-period but fails on full data.
Fix: smoke is ONLY a filter to find candidates; Full/IS/OOS gates are the real test.

---

## 11. NT8 Standard Indicator Library (from Phase 2 Source Acquisition)

Before generating any strategy, verify every indicator is standard in NT8.
Using non-standard indicators = compile failure = wasted CELL cycle.

**✅ Standard NT8 indicators (safe to use):**
- SMA, EMA, WMA — standard
- ATR — standard
- RSI (use: `RSI(period, RSIType.Wilder)[0]`) — standard
- MACD — standard
- Bollinger — standard
- ADX — standard
- VWAP — standard (session-anchored)
- CrossAbove, CrossBelow — built-in NT8 functions (not indicators)
- PriorDayOHLC — standard NT8

**❌ NON-standard (do NOT use without verifying custom indicator exists):**
- `BarSpeed` — NOT in NT8 standard library (REPO-008 lesson)
- `StochRSI` — verify; may not be in standard NT8
- `SuperTrend` — NOT standard; requires custom indicator download
- Any indicator not listed in NT8 Help Guide

**Rule:** Only use indicators from the ✅ list above in AI-generated strategies.
If a pattern requires a non-standard indicator, REPLACE it with a standard equivalent.

---

## 12. Inside Bar Pattern (New — from Phase 2)

Inside Bar = a bar whose HIGH and LOW are contained within the prior bar's range.
This is a compression/consolidation signal. Breakout from the inside bar = momentum signal.

```csharp
// Detect inside bar (bar[1] is inside bar[2])
bool insideBar = (High[1] < High[2]) && (Low[1] > Low[2]);

// Long entry: price breaks above inside bar high (High[2])
if (insideBar && CrossAbove(Close, High[2], 1))
    EnterLong(qty, "IB_Long");

// Short entry: price breaks below inside bar low (Low[2])
if (insideBar && CrossBelow(Close, Low[2], 1))
    EnterShort(qty, "IB_Short");
```

**When to add to AI-CELL:**
- Combine with ADX > 20 (trend present) for directional filter
- Use on 15m to avoid commission drag
- ATR trailing stop is appropriate (see entry_patterns.md Pattern 9)

---

## 13. Real Backtest Results from Reference Library (2026-06-07)

**12 strategies backtested on MNQ 06-26, 15m, Dec 2025 – Jun 2026. ALL losing after commission.**

### Commission Reality Check (CONFIRMED BY REAL DATA):

| Strategy | Trades/6mo | Gross/Trade | PF Before Comm | PF After $1.90 | Verdict |
|----------|-----------|-------------|----------------|----------------|---------|
| SMA 9/21 Crossover | 605 | $4.62 | 0.888 | 0.610 | losing |
| EMA Pullback | 569 | $2.18 | 0.669 | 0.358 | losing |
| Inside Bar | 511 | $4.56 | 0.868 | 0.596 | losing |
| BB + EMA | 241 | $2.69 | 0.905 | 0.484 | losing |
| MACD+RSI (no limit) | 3,814 | $6.62 | 0.957 | 0.732 | losing (OVERTRADING) |
| **Donchian 20-bar** | **496** | **$10.83** | **1.095** | **0.914** | **BEST — near-break-even** |

**Critical insight:** Donchian breakout is the ONLY pattern that showed positive net before commission.
After $1.90/RT, even PF 1.095 becomes 0.914. The solution: higher timeframe (1H/4H) = fewer trades = less commission drag.

### Lesson 13: Minimum gross/trade for commission viability

For $1.90 RT commission:
- Minimum to break even: $3.80 gross/trade
- Minimum for PF > 1.1 after comm: $10+ gross/trade (3 ATR move on 15m)
- 15m MNQ ATR avg $15-20 → target 2 ATR = $30-40 gross would work
- BUT win rate must be > 45% for 1:2 R:R

**Why most strategies fail:**
- Win rate 27-40% is too low for 1:1.5 or 1:2 R:R with $1.90 commission
- Commission amplifies every losing trade by $1.90 more
- 600 trades at $1.90 = $1,140 drag regardless of strategy quality

### Lesson 14: Donchian 20-bar is the best reference pattern

Adapt Donchian to 1H bars for AI-CELL-007/008:
- 15m: 496 trades/6mo → commission $942 → wipes edge
- 1H: ~124 trades/6mo → commission $236 → edge preserved
- Expected: same PF 1.095 gross → net after comm ~$231 positive
- This is a viable path to first profitable reference strategy

### Lesson 15: MACD+RSI without MaxTradesPerDay is catastrophic

WEX-006 generated 3,814 trades in 6 months (20+ trades/day).
Commission: $7,247 on 3,814 trades.
Net loss: -$8,375.

This PROVES MaxTradesPerDay=2 rule is not arbitrary — it prevents commission annihilation.
Any AI-generated strategy without MaxTradesPerDay is structurally broken.

---

## 10. Pre-AI-CELL Strategy Generation Checklist

Before AI generates any new strategy:

**Step 1: Choose reference**
- [ ] Identify 1 reference pattern from REF-001 to REF-025
- [ ] Read its normalized_spec.md
- [ ] Read its ai_lesson.md

**Step 2: Apply failed-CELL lessons**
- [ ] Read FAILED_CELL_LESSONS.md
- [ ] Identify which CELL-019 engines match the proposed strategy
- [ ] Apply their lessons (directional filter, stop width, etc.)

**Step 3: Formulate hypothesis**
- [ ] "We use [REF-XXX] pattern, modified by [CELL-019 lesson], adding [improvement]"
- [ ] Verify gross_per_trade economics (TF ATR * target_mult vs $1.90 commission)
- [ ] Verify position sizing feasibility (stop_ticks * tickValue vs riskBudget)

**Step 4: Choose instrument and timeframe**
- [ ] Prefer 15m over 5m for economics
- [ ] Verify instrument has sufficient volume for backtest
- [ ] Plan IS and OOS test windows (2024 and 2025)

**Step 5: Define exit rules FIRST, then entries**
- [ ] Stop must be calculable from NT8 data
- [ ] Target must exceed 2 * commission ($3.80) minimum
- [ ] Time stop must prevent overnight hold

---

*Last updated: 2026-06-06*
