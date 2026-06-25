# Normalized Spec: REF-024 — VWAP + RSI Combined Intraday

## Strategy Family
`mean_reversion_filtered`

## Hypothesis
Combining VWAP and RSI creates a dual-confirmation mean reversion system:
1. VWAP provides the dynamic fair value level (price deviating from VWAP)
2. RSI confirms the momentum direction is extreme (RSI < 40 for oversold)
Entry occurs when BOTH signals agree, reducing false entries significantly.

## Instrument Candidates
- MNQ (primary)
- MES (secondary)
- Note: must use 15m+ to avoid commission drag (CELL-019 lesson from REF-009)

## Timeframe
- Primary: 15m (VWAP mean reversion on 15m avoids commission drag)
- Avoid: 5m (proven commission drag on micros)

## Session
- RTH: 09:30–14:30 ET
- Avoid: last 90 min (VWAP becomes less predictive)

## Indicators
1. VWAP (session daily)
2. RSI(14)
3. ATR(14) — stop sizing

## Entry Rules
**Long (oversold + below VWAP but near it):**
1. Price is below VWAP but within ATR * 1.0 of VWAP
2. RSI(14) < 40 (mild oversold — not extreme like RSI<30)
3. Prior bar shows pullback (close < prior close)
4. Current bar: recovery sign (close > open — bullish bar)
5. Enter at next bar open targeting VWAP return

**Short (overbought + above VWAP):**
1. Price is above VWAP but within ATR * 1.0 of VWAP
2. RSI(14) > 60
3. Recovery fade: close < open (bearish bar after rally)
4. Enter at next bar open

## Exit Rules
- **Target:** VWAP (primary mean reversion target)
- **Stop:** ATR * 1.5 from entry
- **Time stop:** 14:00 ET
- **Exit if:** RSI reaches 50 (momentum neutral = mean reversion complete)

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| RsiOversold | 40.0 | [30.0, 45.0] |
| RsiOverbought | 60.0 | [55.0, 70.0] |
| VwapAtrDistance | 1.0 | [0.5, 2.0] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| MaxDailyTrades | 3 | [1, 6] |

## Expected Signal Frequency
- 15m RTH: 1–3 signals/day
- Monthly: 20–50 trades

## Why RSI 40/60 (Not 30/70)?
- RSI < 30 on 15m MNQ is RARE → too few trades (CELL-019 lesson)
- RSI < 40 fires more often while still indicating pullback
- Combines with VWAP proximity for dual confirmation

## Failure Modes
1. Price below VWAP + RSI < 40 + strong trend = multiple losing entries
2. VWAP target may be 5-20 ticks away on 15m → needs to be > commission * 2
3. Late-day VWAP: VWAP tracks close to price → smaller deviation, smaller target

## Commission Viability Check
VWAP to price distance must be > $3.80 (2 * $1.90 commission).
On 15m MNQ: 1 ATR ≈ 15-25 points = $15-25 = well above commission ✓
On 5m MNQ: 1 ATR ≈ 5-8 points = $5-8 = borderline → avoid 5m

## Market Regimes
- Ranging/oscillating markets: excellent (dual-confirmation works)
- Strong trending: poor (VWAP deviation keeps growing)

## Overfit Risk
**LOW-MEDIUM** — RSI thresholds (40/60 vs 30/70) can be adjusted.
Keep at 40/60 for mild confirmation; don't optimize per year.
