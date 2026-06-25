# Normalized Spec: REF-008 — VWAP Pullback

## Strategy Family
`vwap_pullback`

## Hypothesis
VWAP (Volume-Weighted Average Price) represents the average price at which the market
has traded throughout the session, weighted by volume. Institutional buyers tend to
use VWAP as a benchmark. When price pulls back toward VWAP in an established intraday
trend, it offers a higher-probability entry in the trend direction because:
1. Institutions defend VWAP as a fair value level
2. Price below VWAP after a bullish open = oversold relative to daily average

## Instrument Candidates
- MNQ (primary — institutional VWAP use is high)
- MES (secondary)
- MYM (tertiary)

## Timeframe
- Primary: 5m, 15m
- VWAP resets at RTH open (09:30 ET) or use anchored VWAP

## Session
- RTH only: 09:30–15:00 ET
- Avoid: 14:30–16:00 ET (VWAP convergence as day ends, signal weakens)

## Indicators
1. VWAP (session VWAP, daily reset)
2. EMA(20) — trend bias
3. ATR(14) — stop sizing
4. Optional: ADX(14) > 20 (trend must be present)

## Entry Rules
**Long pullback to VWAP:**
1. Post-open (10:00+ ET): price established ABOVE VWAP
2. EMA(20) is bullishly sloped (EMA20 > EMA20[3])
3. Price pulls BACK to VWAP (within 1 ATR tolerance)
4. Entry bar: price touches/approaches VWAP and shows reversal (close > VWAP)
5. Enter at next bar open

**Short pullback to VWAP:**
1. Price established BELOW VWAP post-open
2. EMA(20) bearishly sloped
3. Price rallies BACK to VWAP
4. Entry bar: price touches VWAP and closes below it
5. Enter at next bar open

## Exit Rules
- **Target:** Prior high (for longs) or ATR(14) * 2.0 above VWAP
- **Stop:** ATR(14) * 1.0 below VWAP (for longs)
- **Session end:** exit all

## Stop Loss Logic
- VWAP ± ATR as natural stop zone
- MinStopTicks: 8, MaxStopTicks: 20
- VWAP is dynamic — stop must be recalculated each bar

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| VwapToleranceATR | 0.5 | [0.25, 1.0] |
| EmaSlope | 20 | [10, 30] |
| AdxThreshold | 20.0 | [15.0, 30.0] |
| AtrStopMult | 1.0 | [0.5, 1.5] |
| AtrTargetMult | 2.0 | [1.5, 3.0] |
| MaxDailyTrades | 3 | [1, 6] |
| SessionStartBuffer | 30 | [15, 60] |

## Expected Signal Frequency
- 5m RTH: 1–4 signals/day (with filters: 0–2)
- Monthly: 20–50 trades

## CELL-019 Reference Results (RTH VWAP Pullback)
- MGC: Full PF 1.171 DD -$298 — closest to passing gates
- IS PF 1.281, OOS PF 1.052 — OOS below 1.25 gate
- Full PF < 1.35 gate
- **Near-pass candidate:** Most promising mean-reversion/pullback seen in CELL-019

## Failure Modes
1. **VWAP convergence** late in session: VWAP approaches price always → false signals
2. **ADX filter blocks** valid pullbacks on slow-trend days
3. **Gap-and-go days:** price never returns to VWAP → 0 trades
4. **OOS regime:** 2025 MNQ more reversal-prone → VWAP pullbacks sometimes continue away

## Why This Strategy May Work
- Institutional VWAP use creates real support/resistance
- Volume-weighted level is mathematically meaningful
- RTH context filters eliminate overnight noise

## Why It May Fail for NT-Analyzer
- CELL-019 MGC attempt PF 1.171 < 1.35 gate — close but not there
- OOS PF 1.052 < 1.25 gate
- Needs additional filter: volume expansion, candlestick confirmation

## Market Regimes
- Trending with regular pullbacks: excellent
- GAP-AND-GO trend days: poor (no pullback to VWAP)
- Choppy/narrow range: poor

## Overfit Risk
**MEDIUM** — VwapToleranceATR can be overfit.
Mitigation: don't optimize tolerance per year; use ATR * 0.5 as fixed rule.
