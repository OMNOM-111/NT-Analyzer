# Normalized Spec: REF-011 — Opening Range Breakout (Classic ORB)

## Strategy Family
`breakout_orb`

## Hypothesis
The Opening Range (first N minutes of RTH session) defines the initial price discovery
zone. A break above the opening range high signals bullish momentum continuation.
A break below the opening range low signals bearish momentum. The ORB strategy enters
on these breakouts, betting that the initial directional move will continue.

## Instrument Candidates
- MNQ (primary — NQ/MNQ has strong directional bias at open)
- MES (secondary — S&P less volatile but good volume)
- MYM (tertiary — Dow)
- M2K (tertiary — Russell)

## Timeframe
- ORB period: first 15–30 minutes of RTH (09:30–09:45 ET or 09:30–10:00 ET)
- Trading timeframe: 5m bars for entry precision

## Session
- RTH only: trade after ORB period ends through 14:00–15:00 ET
- Do NOT trade on first 30m (that IS the ORB formation period)

## Indicators
1. ORB High = high of first N minutes
2. ORB Low = low of first N minutes
3. ATR(14) — stop sizing
4. Optional: VWAP — direction filter (REF-021 extension)
5. Optional: Volume — expansion filter

## Entry Rules
**Long ORB:**
1. Price breaks above ORB High (close > ORB High)
2. Enter on break bar close or next bar open
3. Filter: breakout bar volume > average volume (optional)
4. Filter: price above VWAP (optional, REF-021)

**Short ORB:**
1. Price breaks below ORB Low (close < ORB Low)
2. Enter on break bar or next bar open
3. Filter: volume expansion
4. Filter: price below VWAP

## Exit Rules
- **Stop:** ORB opposite side (ORB Low for longs, ORB High for shorts)
  OR ATR(14) * 1.5 — whichever is tighter
- **Target:** ORB range * 1.5 beyond breakout level
  Example: ORB range = 20 ticks → target = ORB High + 30 ticks
- **Time stop:** 14:00–15:00 ET (exit before close)
- **Max trades:** 1 per direction per day

## Stop Loss Logic
- ORB midpoint or opposite side of ORB as natural stop
- For $2k MNQ: ORB range can be 20-60 ticks → stop may be 15-50 ticks
- Position sizing critical: must floor qty=1 with MaxDailyLossUsd cap
- MaxStopTicks = 30 (cap to avoid qty=0 from wide ORB days)

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| OrbMinutes | 30 | [15, 60] |
| StopType | "orb_opposite" | ["orb_opposite", "atr"] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| TargetOrbMult | 1.5 | [1.0, 3.0] |
| MaxStopTicks | 30 | [20, 50] |
| RequireVwap | false | [true, false] |
| RequireVolume | false | [true, false] |
| MaxTradesPerDay | 2 | [1, 4] |

## Expected Signal Frequency
- 5m RTH: 0–2 signals/day
- Monthly: 10–30 trades

## CELL-019 Reference (ORB Retest = REF-012)
- Engine #7 ORB Retest H1: cross-year positives existed but OOS gates failed
- Key lesson: ORB alone not sufficient; directional bias (VWAP) improves results
- Engine #8 ORB Retest 15m: also REJECTED

## Why ORB Works
- High institutional participation in first 30m defines day's range
- Momentum days: first 30m range broken decisively → 60-80% continue
- Well-documented in academic studies and practical trading

## Why ORB May Fail
- Fake breakouts: first break fails, reverses into range = stop-out
- Gap-days: ORB may be too large (25+ points MNQ) → wide stop
- Choppy days: multiple false breaks both directions

## Risk Flags
- `overfit_risk_window_selection` — ORB minute window can be over-fit
- `fake_breakout_risk` — needs volume/VWAP filter to reduce

## Market Regimes
- Trend days: excellent (clean break, continuation)
- Choppy days: poor (false breaks)
- Gap days: caution (ORB may be giant)

## Overfit Risk
**MEDIUM** — OrbMinutes (15 vs 30 vs 45) and TargetOrbMult can overfit.
Use standard 30-minute ORB and fixed 1.5x target as baseline.

## Recommended for AI-CELL-007/008
**HIGH PRIORITY** — ORB with VWAP filter (REF-021) is the top recommendation.
Key: "Берём ORB, после AI-CELL-005 max 2 trades/day, добавляем VWAP filter."
