# Normalized Spec: REF-006 — RSI(2) Mean Reversion (Connors)

## Strategy Family
`mean_reversion`

## Hypothesis
RSI with a 2-period lookback creates a very sensitive oscillator that reaches extreme
readings (>90 or <10) frequently on daily charts. These extremes represent short-term
overbought/oversold conditions that tend to revert to the mean. Larry Connors backtested
this on S&P equities and found high win rates.

## Instrument Candidates
- MES (closest to S&P500 — original backtest instrument)
- MNQ (similar behavior on daily)
- NOT recommended for 5m/15m intraday without significant modification

## Timeframe
- **Original design:** DAILY chart
- **Adaptation for intraday:** 1H (with caution — results not as robust)
- **Do NOT use:** 5m, 15m (RSI(2) is too noisy at these timeframes)

## Session
- Original: daily close-to-close (not session-aware)
- Intraday adaptation: RTH only, avoid overnight gap risk

## Indicators
1. RSI(2) — ultra-short RSI
2. SMA(200) — long-term trend filter (only trade in direction of SMA200)
3. RSI(2) thresholds: Buy < 10, Sell > 90

## Entry Rules
**Long (from Connors book):**
1. Price > SMA(200) (long-term uptrend)
2. RSI(2) closes < 10 (extreme oversold)
3. Enter at next open

**Short:**
1. Price < SMA(200)
2. RSI(2) closes > 90
3. Enter at next open

**IMPORTANT — no stop in original Connors system:**
The original system uses NO stop loss. This is DANGEROUS for futures.
Any adaptation for NT8 MUST add an explicit ATR stop.

## Exit Rules (Connors original)
- Exit when RSI(2) closes > 65 (for longs)
- Exit when RSI(2) closes < 35 (for shorts)
- No time stop in original

**Adaptation for futures — MANDATORY ADDITIONS:**
- Hard stop: ATR(14) * 2.0 from entry
- Time stop: exit at session close
- MaxDailyLossUsd cap

## Stop Loss Logic
**DANGER — ORIGINAL HAS NO STOP LOSS.**
- Flag: `no_stop_in_original`
- Any NT8 adaptation MUST add: ATR(14) * 2.0 hard stop minimum
- This changes the statistical profile vs Connors' original results

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| RsiPeriod | 2 | [2, 5] |
| SmaLongTrend | 200 | [100, 200] |
| RsiOversold | 10.0 | [5.0, 20.0] |
| RsiOverbought | 90.0 | [80.0, 95.0] |
| RsiExitLevel | 65.0 | [50.0, 80.0] |
| AtrStopMult | 2.0 | [1.5, 3.0] |

## Expected Signal Frequency
- Daily: 2–5 signals/month
- Too infrequent for intraday adaptation

## Failure Modes
1. **No stop = catastrophic loss risk** in trending market
2. Original designed for ETFs, not leveraged futures
3. RSI(2) < 10 on MNQ 15m → often means breakdown, not reversion
4. SMA(200) on daily doesn't translate to intraday timeframes

## Why This Strategy May Work (on daily ETFs/stocks)
- Mean reversion is statistically valid on daily equity indices
- High win rate (>60%) documented in Connors' research
- Simple, few parameters, low overfit

## Why This Strategy May NOT Work for Our System
- **No stop** = disqualified for NinjaTrader futures without modification
- Works on large liquid markets (SPY) not micro futures
- Daily frequency too low for NT-Analyzer intraday pipeline
- 2024-2025 regime: MNQ is trending more than mean-reverting

## Risk Flags
- `no_stop_in_original`
- `designed_for_daily_TF`

## Reference Value for AI
- Shows that RSI(2) < 10 as FILTER (not sole signal) can be useful
- Demonstrates mean reversion timing concept
- Teaches: always add stop to any mean reversion system
