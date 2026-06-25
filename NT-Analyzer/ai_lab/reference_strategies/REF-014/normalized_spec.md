# Normalized Spec: REF-014 — Previous Day High/Low Breakout

## Strategy Family
`breakout_level`

## Hypothesis
The Previous Day High (PDH) and Previous Day Low (PDL) are widely watched by traders
and institutions. A decisive break above PDH signals continuation bullish momentum.
A break below PDL signals bearish momentum. These levels are natural resistance/support
that, when broken, often lead to follow-through moves.

## Instrument Candidates
- MNQ (primary)
- MES (secondary)
- MGC, MCL (good for commodity PDH/PDL)
- M2K, MYM (tertiary)

## Timeframe
- Entry: 5m or 15m bars
- PDH/PDL calculated from prior RTH session

## Session
- RTH: 09:30–15:00 ET
- Best window: 09:30–12:00 (morning momentum session)

## Indicators
1. PreviousDayHigh — max high of prior RTH session
2. PreviousDayLow — min low of prior RTH session
3. ATR(14) — stop sizing and entry filter
4. Optional: Volume — confirm breakout with volume expansion

## Entry Rules
**Long PDH breakout:**
1. Price closes above PDH
2. Close > PDH + ATR * 0.1 (buffer to avoid false poke)
3. Breakout occurs within first 3 hours of RTH
4. Enter at next bar open or on pull-back to PDH level

**Short PDL breakout:**
1. Price closes below PDL
2. Close < PDL - ATR * 0.1 (buffer)
3. Enter at next bar open

## Exit Rules
- **Stop:** PDH - ATR * 0.5 (for longs — pullback back below PDH = fail)
- **Target:** PDH + ATR * 2.0 or prior swing level
- **Time stop:** 14:00 ET
- **Max trades:** 1 per direction per day

## Stop Loss Logic
- Entry above PDH → stop below PDH - buffer
- Natural stop: if price fails to hold PDH, breakout is false
- Typically 8-20 ticks for MNQ

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| AtrBuffer | 0.1 | [0.05, 0.3] |
| AtrStopMult | 0.5 | [0.25, 1.0] |
| AtrTargetMult | 2.0 | [1.5, 3.5] |
| MaxTradesPerDay | 2 | [1, 4] |
| EntryDeadlineHours | 12.0 | [10.0, 14.0] |

## Expected Signal Frequency
- RTH: 0–1 PDH or PDL breakout per day
- Monthly: 10–25 trades

## Failure Modes
1. **Fake breakout:** price pokes above PDH then reverses
2. **Too far into session:** PDH break at 14:00 = late entry, less continuation
3. **Gap days:** open already above PDH → missed entry
4. **Wide PDH-PDL range days:** stop too wide for $2k account

## Why PDH/PDL Levels Work
- Widely watched by institutional and retail traders alike
- Prior session high/low represents real supply/demand zones
- Breaking these levels means prior sellers/buyers are now capitulating

## Why May Fail
- Many false breakouts on choppy days
- Gap open above PDH = no trade (level already broken overnight)
- Must add volume filter or buffer to reduce false breaks

## Market Regimes
- Trending days with overnight gap: capture continuation
- Choppy days: multiple false breaks
- Low-volatility days: PDH/PDL may not be reached

## Overfit Risk
**LOW-MEDIUM** — AtrBuffer and EntryDeadlineHours can be overfit.
Use conservative defaults: 0.1 ATR buffer, 12:00 deadline.
