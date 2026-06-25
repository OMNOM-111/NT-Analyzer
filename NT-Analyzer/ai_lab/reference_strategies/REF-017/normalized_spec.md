# Normalized Spec: REF-017 — Liquidity Sweep Reversal

## Strategy Family
`reversal_sweep`

## Hypothesis
Market makers and large participants take liquidity from retail stop clusters.
Retail traders place stops just below swing lows (longs) or just above swing highs (shorts).
A "liquidity sweep" occurs when price briefly breaks below/above these levels to trigger
the stops, then reverses. Entering AFTER the sweep, in the reversal direction, catches
the bounce as price quickly recovers.

## IMPORTANT: CELL-015 REFERENCE
**This is the strategy family of our ONLY ACCEPTED production strategy (CELL-015).**
NTAMnqLiquiditySweepReversalC015 is our reference implementation on MNQ pre-RTH.

This spec describes the concept for AI learning.
The actual implementation details are in the CELL-015 source code.

## Instrument Candidates
- MNQ (primary — CELL-015 accepted on pre-RTH MNQ)
- MES (potential — similar liquidity dynamics)
- Avoid: very low volume instruments (MCL, MGC have thinner books)

## Timeframe
- 5m bars (CELL-015 uses 5m)
- Pre-RTH window: 03:00–05:55 PT (CELL-015 specific)
- RTH 15m: untested but plausible

## Session
- Pre-RTH ETH: CELL-015 specific (03:00–05:55 PT)
- RTH morning: alternative (09:30–11:00 ET)

## Indicators
1. Swing High / Swing Low detection (lookback bars)
2. ATR(14) — stop sizing and sweep distance measurement
3. Rejection candle detection (wick-to-body ratio)
4. Optional: Volume spike on sweep bar

## Entry Rules (from CELL-015 pattern)
**Long (sweep below swing low + reversal):**
1. Price breaks below recent swing low (sweeps buy-stop cluster)
2. Distance of sweep: between MinSweepTicks and MaxSweepTicks
3. Price closes ABOVE the sweep low (rejection candle confirmed)
4. Optional: wick-to-body ratio > threshold (strong rejection)
5. Enter at next bar open (or on close of rejection bar)

**Short (sweep above swing high + reversal):**
1. Price breaks above recent swing high (sweeps sell-stop cluster)
2. Distance within MinSweepTicks and MaxSweepTicks range
3. Price closes BELOW the sweep high
4. Enter at next bar open

## Exit Rules
- **Stop:** Below the sweep low (for longs) — if price goes back below, sweep is NOT reverting
- **Target:** Pre-sweep swing high/low (mean reversion target)
- **Time stop:** session end
- **Max trades:** limited by MaxDailyLossUsd

## Stop Loss Logic
- Stop below sweep extreme: sweep_low - ATR * 0.5
- MinStopTicks: 4 (CELL-015 uses tight stops)
- MaxStopTicks: 10 (CELL-015 specific — wide stops kill position sizing on $2k)

**CELL-015 CRITICAL LESSON:**
MinStopTicks = 4, MaxStopTicks = 10 was KEY to making position sizing work on $2k.
ATR-sized stops (16-40 ticks) → byRisk = 0 → silent no-trade bug.

## Parameters (CELL-015 based)
| Parameter | Default | Range |
|-----------|---------|-------|
| SwingLookback | 10 | [5, 20] |
| MinSweepTicks | 4 | [2, 8] |
| MaxSweepTicks | 20 | [10, 40] |
| MinStopTicks | 4 | [2, 8] |
| MaxStopTicks | 10 | [8, 20] |
| AtrStopMult | 0 | [0, 1] |
| MaxDailyLossUsd | 80.0 | [40.0, 150.0] |

## Expected Signal Frequency
- Pre-RTH 5m: 0–2 sweeps per session
- Monthly: 10–30 trades (CELL-015 range)

## CELL-015 Production Results
CELL-015 is the ONLY accepted AI Lab strategy so far.
Key metrics (reference, not guarantee):
- Accepted after Smoke/Full/IS/OOS/Stress pipeline
- Active in demo mode on MNQ pre-RTH
- Serves as baseline for future improvement

## Failure Modes
1. **Wide stops** → position sizing to 0 (must cap MaxStopTicks)
2. **Oversweep:** price sweeps too far and doesn't recover (real breakdown)
3. **Pre-RTH thinness:** sometimes only 1-2 contracts at sweep low → manipulation
4. **Session timing:** pre-RTH ETH has fewer signals but cleaner sweeps

## Why Liquidity Sweep Works (Pre-RTH Specifically)
- Pre-RTH has fewer participants → retail stops are MORE impactful
- Market makers CAN efficiently take stops with smaller volume
- Post-sweep recovery is faster in thin pre-RTH market
- CELL-015 demonstrates this is real, not theoretical

## Risk Flags
- `concept_hard_to_operationalize` — requires precise sweep detection
- `license_unknown_reference_only` — ICT concepts, use concept not ICT terminology

## Market Regimes
- All regimes (concept works in trending and ranging)
- Works best when there are clear swing levels to sweep

## Overfit Risk
**MEDIUM** — SwingLookback and MinSweepTicks/MaxSweepTicks can be overfit.
CELL-015 lesson: tight stop range (4-10 ticks) was not just a choice, it was necessary.
