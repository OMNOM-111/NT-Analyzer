# Normalized Spec: REF-019 — Gap Fill / Gap Fade Strategy

## Strategy Family
`gap_fade`

## Hypothesis
When a market opens significantly above or below the prior session close (overnight gap),
there is a tendency for price to partially or fully fill the gap as the day session
establishes fair value. Entering against the gap direction targets the gap fill.

## CELL-019 REFERENCE RESULT (Settlement Reversion)
This pattern was tested as "Overnight Settlement Reversion" and "Overnight Settlement
Breakout" in CELL-019.

Both were REJECTED:
- Settlement Reversion: deeply negative across all variants
- Settlement Breakout: smoke mirages (M2K smoke +446.7) → Full -31.6 negative
- Lesson: Gap/settlement fade on equity index micros is DIFFICULT in 2024-2025

## Why Gap Fade Failed in CELL-019
1. 2024-2025 MNQ: overnight gaps frequently CONTINUE, not fill
2. Fed/macro events cause gap-and-go days where fade = big loss
3. Settlement fade: 2025 regime more trending overnight than mean-reverting

## Instrument Candidates Where Gap Fade May Work Better
- MES (S&P less extreme than NQ)
- MGC (gold overnight gaps often fill on RTH open — institutional)
- Daily charts (not intraday) — slower reversion, smaller commissions per trade

## Timeframe
- Entry: 5m bars at RTH open (09:30–10:30 ET)
- Gap measured from prior RTH close to current RTH open

## Session
- RTH only: gap forms overnight, fade at RTH open
- Critical: first 15-30m of session

## Indicators
1. PreviousDayClose (prior session RTH close)
2. CurrentOpen (first RTH bar open)
3. GapSize = |CurrentOpen - PreviousDayClose|
4. ATR(14) — filter: gap must be > MinGapATR AND < MaxGapATR
5. Optional: VIX/volatility proxy — don't fade gap if high macro risk day

## Entry Rules
**Long (gap down fade — short gap):**
1. CurrentOpen < PreviousDayClose - ATR * MinGapFactor
2. Gap is not a "gap-and-run" (no major news catalyst)
3. Enter long at or near the open targeting partial gap fill
4. Stop: below current open - ATR * 1.0

**Short (gap up fade):**
1. CurrentOpen > PreviousDayClose + ATR * MinGapFactor
2. Enter short at open targeting partial gap fill
3. Stop: above current open + ATR * 1.0

## Exit Rules
- **Target:** 50% gap fill OR full gap fill (PreviousDayClose level)
- **Stop:** ATR * 1.0 from entry (gap continues instead of filling)
- **Time stop:** if gap not filled by 11:00 ET, exit

## Stop Loss Logic
- ATR-based from entry bar
- Tight: 8-15 ticks for short gap
- Risk: if gap continues, stop triggered quickly

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| MinGapAtrFactor | 0.5 | [0.3, 1.0] |
| MaxGapAtrFactor | 2.0 | [1.5, 4.0] |
| TargetFillPct | 50.0 | [25.0, 100.0] |
| AtrStopMult | 1.0 | [0.5, 2.0] |
| FadeDeadlineHour | 11.0 | [10.0, 13.0] |

## Expected Signal Frequency
- RTH: 0-1 gap fade per day (gap must be within size range)
- Monthly: 5-15 trades

## CRITICAL LESSONS FROM CELL-019
1. Settlement fade on equity index micros is STRUCTURALLY difficult 2024-2025
2. Try on MGC/MCL before MNQ/MES
3. Verify regime: more trending overnight = fade is wrong direction
4. Consider gap continuation instead of gap fade as alternative

## Market Regimes Where Gap Fade Works
- Mean-reverting markets (2016-2019 equity chop): works
- News-driven gaps (earnings, macro events): do NOT fade
- Technical overnight rebalancing gaps: may fill

## Overfit Risk
**MEDIUM-HIGH** — MinGapAtrFactor and TargetFillPct can easily overfit.
CELL-019 lesson: smoke mirage (M2K +446.7) → Full -31.6 = classic overfit signal.
