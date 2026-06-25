# Normalized Spec: REF-015 — Range Compression Breakout (NR7-style)

## Strategy Family
`breakout_compression`

## Hypothesis
When the daily (or N-bar) range is the smallest in the last 7 bars (NR7 = Narrow Range 7),
volatility compression creates energy that often releases as a directional breakout.
A narrow range day signals institutional consolidation; the following session often has
expanded range and clear direction.

## CELL-019 REFERENCE RESULT
**This pattern was TESTED in CELL-019 as "PreCash Compression Breakout".**

Result: REJECTED across all variants.
- Near-zero/negative trades across all window/parameter combinations
- Best result: Full +47.3 PF 1.232 DD -124.5 on MGC (not MNQ)
- OOS: -57.2 PF 0.659 — strongly negative OOS

Key lesson: **Compression alone is NOT sufficient signal.**
Must add DIRECTIONAL CONFIRMATION to avoid random direction entries.

## Instrument Candidates
- MNQ (5m, pre-RTH session tried in CELL-019 — failed)
- MGC (slight near-pass on Full, failed OOS)
- Recommend: larger TF (1H, daily) with directional filter

## Timeframe
- Original NR7: Daily bars
- Intraday adaptation: last N 15m bars form compression zone
- 5m on pre-RTH: FAILED (CELL-019)

## Session
- Original: detect NR7 on daily, trade breakout next day's RTH open
- Intraday: detect compression in first 30-60m, trade breakout

## Indicators
1. Bar range (high - low) for last 7 bars
2. Compression detection: current range = min(last 7 bar ranges)
3. ATR(14) — breakout threshold and stop
4. Optional: ADX(14) — must NOT be too high (compression needs low ADX)
5. Required: directional filter (EMA slope, VWAP side, trend bias)

## Entry Rules
**Long (compression breakout up):**
1. Current bar range < all prior 6 bar ranges (NR7 condition)
2. ADX(14) < 20 (confirming compression, not trending yet)
3. Directional filter: price above EMA(20) OR above VWAP (add direction)
4. Entry: break above compression high + ATR * 0.1 buffer
5. Enter on breakout bar or next open

**Short (compression breakout down):**
1. NR7 condition
2. ADX < 20
3. Directional filter: price below EMA(20) OR below VWAP
4. Entry: break below compression low - ATR * 0.1 buffer

## Exit Rules
- **Stop:** opposite side of compression zone
- **Target:** compression range * 2.0 (volatility expansion target)
- **Time stop:** 2 hours after entry or session end

## Stop Loss Logic
- Compression zone is tight → natural stop is tight
- Stop = compression low - ATR * 0.5 for longs
- Often 8-15 ticks (advantage of compression entry)

## CELL-019 Lesson Applied
CELL-019 failure: entered breakout in BOTH directions without directional bias.
**Fix for future AI-CELL:**
1. Add EMA bias filter (only long above EMA20, only short below)
2. Add VWAP bias (only long above VWAP, only short below)
3. Use 15m+ bars not 5m pre-RTH for compression detection

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| CompressionBars | 7 | [5, 10] |
| AdxMaxThreshold | 20.0 | [15.0, 25.0] |
| AtrBuffer | 0.1 | [0.05, 0.3] |
| AtrStopMult | 0.5 | [0.25, 1.0] |
| TargetRangeMult | 2.0 | [1.5, 3.0] |
| RequireDirectionalBias | true | [true, false] |

## Expected Signal Frequency
- Daily NR7: 5-8 signals per month (NR7 occurs ~25% of days)
- Intraday: 0-2 per day (with directional filter: 0-1)

## Failure Modes
1. **No directional filter:** enters both directions randomly (CELL-019 failure)
2. **5m pre-RTH:** too noisy, few bars form compression
3. **NR7 in downtrend:** compression is just a pause, continues down
4. **Wide range instruments:** MGC compression range still wide vs commission

## Market Regimes
- Transitioning from low to high volatility: excellent
- Sustained trends: poor (compression won't develop well)

## Overfit Risk
**MEDIUM** — CompressionBars and AdxMaxThreshold can be overfit.
Original NR7 uses 7 bars — don't optimize this number.

## Reference Value
Demonstrates importance of directional filter on any breakout strategy.
Future AI-CELL: NR7 compression + EMA bias + VWAP confirmation.
