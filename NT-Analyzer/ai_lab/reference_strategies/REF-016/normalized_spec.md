# Normalized Spec: REF-016 — Previous Day High/Low Reclaim

## Strategy Family
`breakout_level`

## Hypothesis
A PDH "reclaim" is a two-stage pattern with higher quality than a direct PDH breakout:
1. Price breaks ABOVE PDH (initial breakout)
2. Price FAILS and pulls back BELOW PDH (fake-out, trapping early longs)
3. Price reverses and RECLAIMS PDH (second break, now with shorts squeezed)

The reclaim entry is higher quality because it:
- Traps and flushes weak longs before continuing
- Short sellers who shorted the failed breakout are now squeezed
- Entry is still near PDH level (good stop placement)

## Instrument Candidates
- MNQ (primary)
- MES (secondary)
- M2K (good for reclaim pattern)

## Timeframe
- 5m bars (primary — need precision for 3-stage pattern)
- 15m bars (secondary — coarser but more reliable)

## Session
- RTH: best in morning 09:30–12:30 ET
- Avoid after 14:00 ET

## Indicators
1. PreviousDayHigh / PreviousDayLow
2. ATR(14) — stop sizing
3. Optional: Volume surge on reclaim bar (confirms institutions buying)

## Entry Rules
**Long PDH Reclaim:**
1. Stage 1: Price breaks above PDH (high > PDH)
2. Stage 2: Price pulls back below PDH (close < PDH after Stage 1)
3. Stage 3: Price closes back above PDH (reclaim confirmed)
4. Enter at next bar open after Stage 3

**Short PDL Reclaim:**
1. Stage 1: Price breaks below PDL
2. Stage 2: Price rallies back above PDL (failed breakdown)
3. Stage 3: Price closes back below PDL (reclaim downside)
4. Enter at next bar open

## Exit Rules
- **Stop:** Below PDH by ATR * 0.5 (just below the reclaim level)
- **Target:** PDH + ATR * 1.5 minimum
- **Time stop:** session end
- **Max trades:** 1 reclaim per level per day

## Stop Loss Logic
- Tight stop: entry above PDH, stop below PDH - small buffer
- Typically 6-12 ticks
- Better R:R than direct PDH breakout entry

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| ReturnBelowAtr | 0.3 | [0.1, 0.8] |
| AtrStopMult | 0.5 | [0.25, 1.0] |
| AtrTargetMult | 1.5 | [1.0, 3.0] |
| MaxBarsForReclaim | 8 | [4, 20] |

## Expected Signal Frequency
- RTH: 0–1 reclaim signal per day (lower frequency than direct breakout)
- Monthly: 5–15 trades

## Failure Modes
1. Pattern may not complete (Stage 2 or 3 doesn't happen)
2. Three-stage detection requires careful bar-by-bar state machine in code
3. MaxBarsForReclaim: if reclaim takes too long, signal weakens

## Why Reclaim Has Better Quality Than Direct Breakout
- Fake-out + reclaim = short squeeze setup
- Weak longs flushed during Stage 2 → more committed buyers in Stage 3
- Stop is same distance (below PDH) but entry is at better price

## Market Regimes
- Morning volatility with level testing: excellent
- Low-volatility days: pattern may not form

## Overfit Risk
**LOW** — pattern logic is binary (did the 3 stages complete?), few parameters.

## Implementation Note for NT8
State machine required:
```
enum ReclaimState { Watching, BreakAbove, FailedBack, Reclaimed }
```
Track state transitions per bar. Exit state machine on session end.
