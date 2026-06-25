# Normalized Spec: REF-023 — EMA Stack Trend Following (3 EMA Alignment)

## Strategy Family
`trend_following`

## Hypothesis
When three EMAs of different periods are ordered correctly (EMA8 > EMA21 > EMA50 for
longs), the market is in a confirmed uptrend across multiple timeframes. This "EMA stack"
alignment acts as a powerful trend filter. Entry is on any pullback to EMA8 or EMA21
while the stack is aligned, catching continuation moves in high-probability trend conditions.

## Instrument Candidates
- MNQ (primary — trends consistently on RTH)
- MES (secondary)
- MGC (excellent — strong trends in commodities)

## Timeframe
- Primary: 15m, 1H
- 5m: EMA stack too reactive on micros

## Session
- RTH: 09:30–15:00 ET
- ETH 1H: possible if overnight trend established

## Indicators
1. EMA(8) — fastest EMA
2. EMA(21) — medium EMA
3. EMA(50) — slowest EMA, trend direction
4. ATR(14) — stop sizing

## Entry Rules
**Long (bullish stack):**
1. EMA8 > EMA21 > EMA50 (all three aligned bullish)
2. Price pulls back to EMA8 or EMA21 level
3. Price bounces (bar closes above the EMA it touched)
4. ADX(14) > 20 (trend present — optional but recommended)
5. Enter at next bar open

**Short (bearish stack):**
1. EMA8 < EMA21 < EMA50 (all three aligned bearish)
2. Price rallies to EMA8 or EMA21
3. Price closes below the EMA it touched
4. Enter at next bar open

## Exit Rules
- **Stop:** EMA50 as dynamic stop (for longs: below EMA50)
- **Target:** ATR * 2.5 from entry or prior swing high
- **Stack break exit:** if EMA8 crosses below EMA21, exit long
- **Session end:** exit all positions

## Stop Loss Logic
- EMA50 as stop level provides dynamic trailing
- For 15m: EMA50 often 20-40 ticks from price during trend
- MinStopTicks: 12, MaxStopTicks: 30
- Wide stop compensated by R:R target (ATR * 2.5)

**$2k Account concern:** EMA50 stop can be 20-40 ticks → position sizing risk.
Floor qty=1 with MaxDailyLossUsd cap required.

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| EmaFast | 8 | [5, 15] |
| EmaMed | 21 | [15, 30] |
| EmaSlow | 50 | [40, 100] |
| AdxThreshold | 20.0 | [15.0, 30.0] |
| AtrTargetMult | 2.5 | [2.0, 4.0] |
| MaxDailyTrades | 3 | [1, 6] |

## Expected Signal Frequency
- 15m RTH with stack filter: 0–2 signals/day
- Stack alignment required → 0 signals on choppy days (correct)

## Failure Modes
1. **Wide stops** on 15m: EMA50 often far → position sizing to 0
2. **Stack takes time to align** → entry is late in the trend
3. **2025 regime:** frequent stack inversions on intraday reversals

## Why EMA Stack Is a Strong Trend Filter
- Three EMAs must align = three confirmation timeframes agree
- Very few false trend signals when all three agree
- Natural hierarchy: EMA8 fastest (price), EMA50 slowest (trend)

## Market Regimes
- Strong trending: excellent (stack aligns clearly)
- Choppy: 0 signals (stack oscillates) — this is correct behavior
- Transitioning: mixed (stack aligns briefly then breaks)

## Overfit Risk
**LOW** — standard EMA periods (8, 21, 50) are well-known. Don't optimize.
