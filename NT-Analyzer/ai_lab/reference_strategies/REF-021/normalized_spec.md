# Normalized Spec: REF-021 — ORB + VWAP Direction Filter

## Strategy Family
`breakout_filtered`

## Hypothesis
Standard ORB (REF-011) has significant fake-breakout risk. Adding VWAP as a directional
filter dramatically improves quality: only take ORB long breakouts when price is above
VWAP, only take ORB short breakouts when price is below VWAP. VWAP represents
institutional fair value for the day, so alignment with VWAP side means:
1. Institutions are aligned with the breakout direction
2. The breakout has institutional support, not just retail momentum

## Instrument Candidates
- MNQ (primary — VWAP usage is high on NQ)
- MES (secondary)

## Timeframe
- ORB formation: 09:30–10:00 ET (30 min)
- Entry: 5m or 15m bars after ORB period

## Session
- RTH only: 10:00–14:00 ET

## Indicators
1. ORB High / ORB Low (first 30 min of RTH)
2. VWAP (session, daily reset at 09:30 ET)
3. ATR(14) — stop sizing
4. Optional: Volume expansion on breakout

## Entry Rules
**Long ORB + VWAP filter:**
1. After 10:00 ET: price breaks above ORB High
2. Close > ORB High (confirmed break)
3. Close > VWAP (VWAP filter: above VWAP = institutional bullish)
4. VWAP itself is rising or flat (not falling sharply)
5. Enter at next bar open

**Short ORB + VWAP filter:**
1. Price breaks below ORB Low
2. Close < ORB Low
3. Close < VWAP (below VWAP = institutional bearish)
4. VWAP is falling or flat
5. Enter at next bar open

## Filter Impact
Without VWAP filter: ~3-5 ORB signals per week
With VWAP filter: ~1-2 per week (VWAP agreement)
Filter removes ~40-60% of false breakouts based on theory
Actual improvement: must verify in backtest

## Exit Rules
- **Stop:** ORB boundary ± ATR * 0.5
- **Target:** ORB range * 1.5 from breakout level
- OR: next resistance/support level
- **Time stop:** 14:00 ET
- **Max trades:** 1 long + 1 short per day maximum

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| OrbMinutes | 30 | [15, 60] |
| RequireVwapAlignment | true | [true, false] |
| VwapSlopeCheck | false | [true, false] |
| AtrStopMult | 0.5 | [0.25, 1.0] |
| TargetOrbMult | 1.5 | [1.0, 3.0] |
| MaxTradesPerDay | 2 | [1, 4] |

## Expected Signal Frequency
- RTH: 0–1 signals/day (VWAP filter reduces frequency)
- Monthly: 8–18 trades

## Why ORB + VWAP Is Better Than Pure ORB
1. **VWAP above = institutions positioned long** → breakout has institutional support
2. **False ORB High break with price below VWAP** = likely test-and-fail → filtered out
3. VWAP alignment with ORB direction = both momentum indicators agree

## Failure Modes
1. VWAP and ORB may conflict on gap days (open above VWAP, ORB forms above yesterday)
2. VWAP late in session loses predictive value (converges to price)
3. VWAP filter blocks valid breakouts on trend days where price dips below VWAP briefly

## CELL-019 Lesson Applied
CELL-019 Engine #7 (ORB Retest) was rejected. Key missing element was VWAP alignment.
If Engine #7 had VWAP filter, results might have improved.
**Future AI-CELL recommendation: always include VWAP alignment in any ORB variant.**

## Market Regimes
- Trend days with VWAP trending: excellent
- Choppy days: VWAP filter reduces entries (good)
- Gap-and-go: VWAP may be far from price → filter evaluates differently

## Overfit Risk
**LOW** — VWAP is objective (calculated from market data).
ORB minutes (30) is a standard benchmark. Don't optimize per year.

## TOP RECOMMENDATION FOR AI-CELL-007/008
This is the #1 recommended strategy family for next AI generation:
- Builds on ORB (proven concept)
- VWAP filter adds institutional alignment
- Max 2 trades/day addresses CELL-005 overtrading lesson
- Directional clarity from dual-indicator alignment
