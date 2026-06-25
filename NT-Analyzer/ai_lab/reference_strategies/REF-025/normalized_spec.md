# Normalized Spec: REF-025 — MACD + RSI Confirmation Trend

## Strategy Family
`trend_following`

## Hypothesis
MACD provides trend direction and momentum, while RSI confirms the entry timing is
not in an extended overbought/oversold condition within the trend. Together:
- MACD histogram positive + RSI not overbought (< 70) = quality long entry
- MACD histogram negative + RSI not oversold (> 30) = quality short entry

This combination reduces late entries (high RSI chasing already-extended moves).

## Instrument Candidates
- MNQ (primary)
- MES (secondary)
- MGC (good for trend confirmation on commodities)

## Timeframe
- Primary: 15m, 1H
- 5m: MACD on 5m is very reactive — too many signals

## Session
- RTH: 09:30–15:00 ET

## Indicators
1. MACD(12, 26, 9) — standard MACD
2. RSI(14) — momentum oscillator
3. EMA(50) — trend bias
4. ATR(14) — stop sizing

## Entry Rules
**Long:**
1. EMA(50) is rising (uptrend context)
2. MACD histogram > 0 (positive = bullish momentum)
3. MACD histogram > histogram[1] (expanding = accelerating)
4. RSI(14) < 65 (not overbought — avoid chasing extended moves)
5. Price > EMA(50)
6. Enter at next bar open

**Short:**
1. EMA(50) is falling
2. MACD histogram < 0 (negative = bearish)
3. Histogram < histogram[1] (accelerating negative)
4. RSI(14) > 35 (not oversold)
5. Price < EMA(50)
6. Enter at next bar open

## Exit Rules
- **Stop:** ATR(14) * 1.5 from entry
- **Target:** ATR(14) * 2.5 from entry
- **MACD deterioration exit:** if MACD histogram turns against position
- **RSI exit:** if RSI reaches overbought/oversold extreme (momentum exhaustion)
- **Session end**

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| MacdFast | 12 | [8, 20] |
| MacdSlow | 26 | [20, 40] |
| MacdSignal | 9 | [6, 15] |
| EmaTrend | 50 | [30, 100] |
| RsiMaxForLong | 65.0 | [55.0, 75.0] |
| RsiMinForShort | 35.0 | [25.0, 45.0] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| AtrTargetMult | 2.5 | [2.0, 4.0] |
| MaxDailyTrades | 4 | [2, 8] |

## Expected Signal Frequency
- 15m RTH: 1–3 signals/day
- Monthly: 20–55 trades

## Why RSI Improves MACD Entry
- MACD alone: fires on first crossover regardless of price extension
- MACD + RSI < 65: rejects late entries after extended moves
- Example: MACD turns positive but RSI is 78 → skip entry (already extended)
- This improves R:R by avoiding entries at tops

## Failure Modes
1. RSI filter too strict (< 65 rarely met) → too few trades
2. MACD histogram can whipsaw quickly on 15m
3. EMA(50) lag means trend filter is ~8 bars behind actual trend change

## Market Regimes
- Trending with momentum: excellent
- Choppy: poor (frequent MACD whipsaw)
- High volatility: MACD signals fire too frequently

## Overfit Risk
**LOW** — standard MACD (12, 26, 9) and RSI(14) parameters. Don't optimize.
RSI threshold (65/35) is approximate and should not be optimized per year.

## Reference Value for AI-CELL
This is a good "confirmation combo" pattern:
- Any trend-following strategy can benefit from RSI confirmation
- Prevents chasing extended moves (a common AI generation mistake)
- Simple to add to any existing trend engine
