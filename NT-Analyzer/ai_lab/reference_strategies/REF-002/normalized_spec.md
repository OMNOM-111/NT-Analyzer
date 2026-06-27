# Normalized Spec: REF-002 — EMA 8/21 Crossover

## Strategy Family
`crossover_trend`

## Hypothesis
EMA reacts faster to recent price changes than SMA. An EMA 8/21 crossover provides earlier
signals than SMA 9/21 while still filtering out micro-noise. The strategy captures
momentum shifts with reduced lag compared to SMA variants.

## Instrument Candidates
- MNQ (primary)
- MES (secondary)
- MYM, M2K (tertiary)

## Timeframe
- Primary: 15m
- Secondary: 1H
- Note: On 5m, EMA 8 is very reactive — excessive whipsaw

## Session
- RTH only: 09:30–16:00 ET
- Avoid 09:30–09:45 ET opening noise

## Indicators
1. EMA(8) — fast
2. EMA(21) — slow
3. Optional: EMA(50) — trend bias (trade only in direction of EMA50)
4. Optional: RSI(14) — avoid overbought/oversold entries

## Entry Rules
**Long:**
1. EMA8 crosses above EMA21
2. Price > EMA50 (trend bias filter)
3. RSI(14) < 70 (not overbought)
4. Enter at next bar open

**Short:**
1. EMA8 crosses below EMA21
2. Price < EMA50
3. RSI(14) > 30
4. Enter at next bar open

## Exit Rules
- Stop: ATR(14) * 1.5 from entry
- Target: ATR(14) * 2.0 from entry (or trailing ATR * 1.0)
- Opposite crossover exits trade
- Session end exits all

## Stop Loss Logic
- ATR-based (same position sizing warning as REF-001)
- MinStopTicks = 8, MaxStopTicks = 20
- $2k account: qty may be 1 only when one contract fits the risk budget after costs

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| FastPeriod | 8 | [5, 15] |
| SlowPeriod | 21 | [15, 50] |
| TrendPeriod | 50 | [30, 100] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| MaxDailyTrades | 4 | [2, 8] |

## Expected Signal Frequency
- 15m RTH: 1–4 signals/day
- With EMA50 bias: 0–2 signals/day

## Failure Modes
1. EMA50 whipsaws on choppy days — blocks valid signals
2. RSI filter can delay entry past optimal level
3. All same as REF-001 crossover issues

## Why EMA Better Than SMA for This Strategy
- EMA8 is more responsive than SMA9 to momentum shifts
- Better for high-volatility intraday (MNQ 2024-2025)
- Crosses happen faster → slightly earlier entry, slightly lower risk per trade

## Market Regimes
- Same as REF-001: trending regimes preferred
- EMA version slightly better in fast-trend environments
- Still poor in choppy markets

## Overfit Risk
**LOW** — well-known parameter set. Avoid fine-tuning EMA periods per year.
