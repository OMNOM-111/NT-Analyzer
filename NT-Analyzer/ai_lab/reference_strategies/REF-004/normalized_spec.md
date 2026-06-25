# Normalized Spec: REF-004 — MACD Histogram Trend

## Strategy Family
`crossover_trend`

## Hypothesis
The MACD histogram (MACD line minus signal line) leads the MACD line crossover by one
phase. When the histogram transitions from negative to positive (first bar above zero),
the trend shift is confirmed with less lag than a MACD line crossover. Using histogram
turning points as entries gives earlier, higher R:R signals.

## Instrument Candidates
- MNQ (primary)
- MES (secondary)
- MYM (tertiary)

## Timeframe
- Primary: 15m, 1H
- Note: MACD on 5m produces too many false signals on micros

## Session
- RTH: 09:30–15:30 ET

## Indicators
1. MACD(12, 26, 9) — standard parameters
   - MACD Line = EMA(12) - EMA(26)
   - Signal Line = EMA(9) of MACD Line
   - Histogram = MACD Line - Signal Line
2. EMA(50) — trend bias filter
3. ATR(14) — stop sizing

## Entry Rules
**Long:**
1. MACD histogram crosses from negative to positive (first bar > 0)
2. MACD histogram > histogram[1] (histogram expanding = momentum building)
3. Price > EMA(50) (trend bias)
4. Enter at next bar open

**Short:**
1. MACD histogram crosses from positive to negative (first bar < 0)
2. Histogram < histogram[1] (expanding negative)
3. Price < EMA(50)
4. Enter at next bar open

## Exit Rules
- Stop: ATR(14) * 1.5 from entry
- Target: ATR(14) * 2.0 from entry
- OR exit when histogram returns toward zero (momentum fading)
- Session end

## Stop Loss Logic
- ATR-based, min 8 ticks, max 24 ticks
- Same position sizing considerations as REF-001/002

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| MacdFast | 12 | [8, 20] |
| MacdSlow | 26 | [20, 40] |
| MacdSignal | 9 | [6, 15] |
| TrendEmaPeriod | 50 | [30, 100] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| AtrTargetMult | 2.0 | [1.5, 3.5] |

## Expected Signal Frequency
- 15m RTH: 1–3 signals/day

## Failure Modes
1. MACD lagging: all EMA-based, inherently behind price
2. Histogram can re-cross zero quickly on volatile days
3. EMA(50) trend bias may filter out valid counter-trend moves

## Why MACD Histogram Better Than MACD Line Crossover
- Histogram first-bar-positive is ~1-2 bars earlier than MACD line crossover
- Earlier entry = smaller stop (price closer to entry support)

## Market Regimes
- Strong trending: excellent
- Mean-reverting: poor
- High volatility with trend: good

## Overfit Risk
**LOW** — standard MACD parameters (12, 26, 9) are industry default.
Avoid optimizing MACD periods to specific years.
