# Normalized Spec: REF-007 — Bollinger Bands Mean Reversion

## Strategy Family
`mean_reversion`

## Hypothesis
When price touches the lower Bollinger Band (BB), it has moved 2 standard deviations
below the 20-period moving average, indicating statistically extreme oversold conditions.
Price tends to revert toward the BB midband (SMA20). Entering longs at lower band with
target at midband captures this statistical tendency.

## Instrument Candidates
- MNQ (primary)
- MES (secondary)
- MYM, M2K (tertiary)

## Timeframe
- Primary: 15m (5m causes commission drag — CELL-019 lesson)
- Secondary: 1H (fewer but more reliable signals)
- Avoid: 5m on micros (same-bar% problem from CELL-019 experience)

## Session
- RTH: 09:30–15:30 ET
- Avoid: first 30m (BB expands excessively at open)

## Indicators
1. BB(20, 2.0) — standard Bollinger Bands
   - Upper band: SMA20 + 2 * StdDev
   - Middle band: SMA20
   - Lower band: SMA20 - 2 * StdDev
2. ATR(14) — stop sizing
3. Optional: RSI(14) < 40 (confirm oversold for long)
4. Optional: ADX(14) < 25 (avoid trending environment — mean reversion needs ranging)

## Entry Rules
**Long:**
1. Close < BB Lower Band (touched/broken lower band)
2. ADX(14) < 25 (ranging environment — optional but important)
3. RSI(14) < 40 (confirm oversold)
4. Next bar: price starts to recover (open > prior close or BB lower band)
5. Enter at next bar open

**Short:**
1. Close > BB Upper Band
2. ADX(14) < 25
3. RSI(14) > 60
4. Enter at next bar open

## Exit Rules
- **Target:** BB midband (SMA20)
- **Trailing:** BB midband as trailing exit
- **Stop:** ATR(14) * 1.5 below entry (for longs)
- **Time stop:** session end
- **Abort if:** BB bands EXPAND after entry (new breakout, not reversion)

## Stop Loss Logic
- ATR-based: 1.5 * ATR below entry
- Minimum: 8 ticks
- Maximum: 20 ticks

**SAME-BAR RISK (from CELL-019 lesson):**
- If stop < BB lower band extension, same-bar stop-out before fill
- Fix: MinStopTicks must exceed typical BB lower band width from close price
- Set MinStopTicks = max(8, ceil(BB_band_width / TickSize))

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| BbPeriod | 20 | [15, 30] |
| BbMultiplier | 2.0 | [1.5, 2.5] |
| AdxPeriod | 14 | [10, 20] |
| AdxMax | 25.0 | [15.0, 30.0] |
| RsiPeriod | 14 | [10, 20] |
| AtrPeriod | 14 | [10, 20] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| MaxDailyTrades | 4 | [2, 8] |

## Expected Signal Frequency
- 15m RTH with ADX<25 filter: 0–2 signals/day
- Monthly: 15–40 trades

## Failure Modes
1. **Trending market:** price walks down the lower BB → multiple losing entries
2. **Same-bar%** (CELL-019 lesson): tight stop + 5m = instant stop-out same bar
3. **BB period too short** → too many signals, low quality
4. **ADX threshold too high** → too many false ranging signals

## CELL-019 Lessons Applicable Here
- VWAP Fade CELL-019: 518 trades on 5m = commission drag ($1.46/trade < $1.90)
- Lesson: BB mean reversion on 5m micros = structural commission problem
- Fix: Use 15m minimum. Target midband (SMA20) not just tiny reversal

## Why BB Mean Reversion May Work
- Statistical edge: 95% of closes within 2 StdDev bands
- Self-fulfilling: many traders watch BB
- Works well in ranging/consolidating markets

## Why It May Fail
- "Walks the band" in strong trends
- Standard BB width on MNQ 15m (~40 ticks) makes target achievable but stop too wide

## Market Regimes
- Ranging/consolidating: excellent
- Trending: poor
- High volatility intraday: mixed

## Overfit Risk
**LOW-MEDIUM** — BB(20, 2.0) is standard. Avoid optimizing per year.
ADX threshold can overfit — use 25 as fixed value.
