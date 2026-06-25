# Normalized Spec: REF-009 — VWAP Mean Reversion (Bounce)

## Strategy Family
`vwap_mean_reversion`

## Hypothesis
When price deviates significantly from VWAP (e.g., price is 2+ standard deviations
above/below VWAP), it is statistically likely to revert toward VWAP. This is a pure
mean reversion strategy: enter AGAINST the prevailing direction when price is extreme,
targeting reversion to VWAP.

## CRITICAL WARNING (from CELL-019)
**This strategy has structural commission drag on $2k MNQ.**
CELL-019 VWAP Fade results:
- 518 trades, gross $756, average $1.46/trade
- Commission floor: $1.90/trade
- Net NEGATIVE by $490+ (commission exceeds gross by 65%)

This strategy was REJECTED in CELL-019 for structural reasons, not parameter issues.
It remains in the library as a reference for what NOT to do, and for instruments/
timeframes where it MAY work.

## Instrument Candidates
- MNQ: NOT VIABLE at current commission ($1.90/RT) on 5m
- Potential: MGC, MCL on 15m+ (less commission drag)
- Better: large-cap futures on broker with lower per-contract fee

## Timeframe
- 5m: proven commission-drag problem on micros
- 15m: potentially viable (lower frequency, larger moves per trade)
- 1H: too infrequent for VWAP deviation strategy

## Session
- RTH: 09:30–14:00 ET (VWAP deviations are largest in morning)

## Indicators
1. VWAP (session)
2. VWAP Standard Deviation bands (±1σ, ±2σ)
3. RSI(14) — confirm extreme reading
4. ATR(14) — stop sizing

## Entry Rules
**Long mean reversion:**
1. Price < VWAP - 2σ (at or beyond 2 standard deviations below)
2. RSI(14) < 30 (oversold confirmation)
3. Entry bar: show signs of reversal (close > open, tail below)
4. Enter at next bar open

**Short mean reversion:**
1. Price > VWAP + 2σ
2. RSI(14) > 70
3. Enter at next bar open

## Exit Rules
- **Target:** VWAP midline (primary) or VWAP ± 1σ (conservative)
- **Stop:** price continues beyond entry by ATR * 1.5
- **Time stop:** session end

## Stop Loss Logic
- Stop below VWAP - 2σ (below band entry point)
- For longs: entry at VWAP-2σ, stop at VWAP-3σ
- MinStopTicks: 8

## Why This Strategy Has Commission Drag on Micros
- Gross per trade on 5m VWAP reversion = ~$1-3 (small moves)
- Commission = $1.90 per round turn
- At 500 trades/year: $950 commission drag vs $750 gross = -$200 net
- Solution: LARGER TF (15m), FEWER trades, BIGGER targets

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| VwapStdDevBands | 2.0 | [1.5, 3.0] |
| RsiOversold | 30.0 | [20.0, 40.0] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| MaxDailyTrades | 2 | [1, 4] |

## Expected Signal Frequency
- 5m RTH: 3–8 signals/day (proven commission-drag level)
- 15m RTH: 1–3 signals/day (potentially viable)

## Failure Modes
1. **Commission drag** — proven in CELL-019 (primary failure)
2. **Trending days:** VWAP deviations keep growing → multiple losing entries
3. **Same-bar% > 70%** observed in CELL-019 with tight stops
4. **VWAP bands inaccurate** early in session with low volume

## Reference Value for AI
This strategy teaches what DOESN'T work:
- High-frequency mean reversion on micros at $1.90/RT = structural loser
- Same-bar% > 70% = stops too tight for the timeframe ATR
- Lesson: always check gross_per_trade vs commission FIRST

## Market Regimes
- Ranging markets (low VIX): potentially viable on 15m
- Trending markets: poor

## Do Not Use As
- Standalone production strategy without fixing commission economics
- 5m or smaller timeframe with current commission structure
