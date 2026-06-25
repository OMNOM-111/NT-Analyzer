# Normalized Spec: REF-010 — RSI Extremes Mean Reversion

## Strategy Family
`mean_reversion`

## Hypothesis
RSI(14) at extremes (>70 overbought, <30 oversold) represents price momentum exhaustion.
Unlike RSI(2) which fires frequently, RSI(14) extremes are less common and represent
stronger mean reversion signals when combined with price structure (failed breakout,
rejection wick, support/resistance level touch).

## Instrument Candidates
- MNQ (15m, 1H)
- MES (similar)
- MGC (useful as commodity mean reversion)

## Timeframe
- Primary: 15m, 1H
- Note: RSI(14) on 5m is too noisy; on daily too infrequent

## Session
- RTH: 09:30–15:30 ET

## Indicators
1. RSI(14) — standard Wilder RSI
2. BB(20, 2.0) — optional context (RSI extreme + BB touch = stronger signal)
3. ATR(14) — stop sizing
4. Candlestick: rejection wick (optional but improves quality)

## Entry Rules
**Long (oversold reversion):**
1. RSI(14) < 30 (oversold)
2. Price shows rejection wick (low below prior low, but closes above it)
3. OR: price at/near support level (round number, prior day low, VWAP)
4. Enter at next bar open

**Short (overbought reversion):**
1. RSI(14) > 70
2. Price shows rejection wick (high above prior high, closes below it)
3. OR: price at/near resistance level
4. Enter at next bar open

## Exit Rules
- **Target:** RSI returns to 50 level (midpoint) = typically 1.5-2.0 ATR move
- **Trailing:** trail by ATR * 0.75 once in profit
- **Stop:** ATR(14) * 1.5 from entry
- **Time stop:** session end

## Stop Loss Logic
- ATR-based hard stop (no dynamic trailing until target half-reached)
- MinStopTicks: 10 (slightly wider than crossover strategies)
- MaxStopTicks: 24

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| RsiPeriod | 14 | [10, 20] |
| RsiOversold | 30.0 | [20.0, 40.0] |
| RsiOverbought | 70.0 | [60.0, 80.0] |
| RsiExitLevel | 50.0 | [45.0, 60.0] |
| AtrPeriod | 14 | [10, 20] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| MaxDailyTrades | 4 | [2, 8] |

## Expected Signal Frequency
- 15m RTH: 0–2 signals/day
- Monthly: 10–35 trades

## Failure Modes
1. RSI can stay extreme for multiple bars in trending markets (false reversal)
2. Without price structure filter (rejection wick), false signals high
3. Entry bar timing: entering immediately on RSI extreme without bounce confirmation

## RSI as Filter vs Sole Signal
**Key lesson:** RSI(14) extreme works better as a FILTER (confirming another signal)
than as a sole entry trigger. Example:
- ORB breakout + RSI < 50 for longs = better than RSI alone
- VWAP pullback + RSI < 45 = stronger pullback confirmation

## Market Regimes
- Ranging/cycling markets: excellent
- Strong trending markets: poor (RSI stays extreme)

## Overfit Risk
**LOW** — RSI(14) with standard 70/30 thresholds is well-tested.
Exit at RSI=50 is logical and not overfitted.

## Reference Value for AI
- Shows how RSI can be used as a filter in combined strategies
- REF-024 (VWAP + RSI) builds on this
- Demonstrates value of candlestick confirmation for mean reversion
