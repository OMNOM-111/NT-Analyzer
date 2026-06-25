# Normalized Spec: REF-012 — Opening Range Retest

## Strategy Family
`breakout_orb`

## Hypothesis
After a genuine ORB breakout, price often pulls back to test the ORB level
(support for longs, resistance for shorts) before continuing in the breakout direction.
The retest entry offers better R:R than the initial breakout: smaller stop (entry closer
to the ORB boundary) and the same directional target.

## Instrument Candidates
- MNQ (primary)
- MES (secondary)

## Timeframe
- ORB formation: first 30 min (09:30–10:00 ET)
- Retest entry: 5m–15m bars, typically 10:00–12:00 ET

## Session
- RTH only: trade after 10:00 ET through 13:00 ET maximum

## Indicators
1. ORB High / ORB Low (calculated from first 30m)
2. ATR(14) — retest tolerance and stop sizing
3. EMA(20) — trend bias (retest should happen with EMA supporting direction)

## Entry Rules
**Long retest:**
1. Initial ORB breakout: price broke above ORB High and traded 1+ ATR above it
2. Price PULLS BACK to within ATR * 0.5 of ORB High
3. ORB High now acts as support (hold above it)
4. Entry bar closes above ORB High (retest confirmed, bouncing off it)
5. Enter at next bar open

**Short retest:**
1. ORB Low broken, price traded 1+ ATR below it
2. Price rallies back to within ATR * 0.5 of ORB Low
3. Entry bar closes below ORB Low (resistance confirmed)
4. Enter at next bar open

## Exit Rules
- **Stop:** ORB boundary (High for longs) minus ATR * 0.5 — tight stop!
- **Target:** Same as initial ORB target (ORB range * 1.5 from ORB boundary)
- **Time stop:** 13:00–14:00 ET

## Stop Loss Logic
- Tighter than initial ORB entry: stop just below ORB boundary
- Typically 5-15 ticks for longs (ORB High - 5-15 ticks)
- This is the KEY advantage: better R:R than initial ORB entry

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| OrbMinutes | 30 | [15, 60] |
| RetestAtrTolerance | 0.5 | [0.25, 1.0] |
| RequiredPriorATR | 1.0 | [0.5, 2.0] |
| StopBelowOrbTicks | 8 | [4, 16] |
| TargetOrbMult | 1.5 | [1.0, 3.0] |
| MaxTradesPerDay | 1 | [1, 2] |

## Expected Signal Frequency
- RTH: 0–1 signals/day (retest doesn't always occur)
- Monthly: 8–20 trades

## CELL-019 Result
- Engine #7 H1 ORB Retest: REJECTED — cross-year positives existed but OOS PF < 1.25
- Engine #8 15m ORB Retest: REJECTED
- Lesson: retest pattern works sometimes but unreliable cross-year on MNQ 2024-2025
- Needs additional directional bias filter

## Failure Modes
1. **Retest doesn't happen:** strong trend day = no pullback, misses the move
2. **Retest too deep:** price breaks back into ORB = stop-out
3. **Late in session:** retest happens at 13:30+ = time stop conflicts
4. **2025 regime:** more reversals = ORB breaks then reverses into ORB

## Why Retest Has Better R:R Than Initial Breakout
- Entry closer to ORB boundary = smaller stop (8-12 ticks vs 15-25 ticks)
- Same target = higher R:R (1:3 vs 1:2 for initial ORB)
- Retest confirms the breakout is real (second test of level)

## Market Regimes
- Trend days with healthy pullback: excellent
- Full gap-and-go days: may miss (no retest)
- Choppy days: poor

## Overfit Risk
**MEDIUM** — retest tolerance window can overfit.
