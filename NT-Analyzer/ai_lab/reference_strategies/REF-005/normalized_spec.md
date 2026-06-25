# Normalized Spec: REF-005 — SuperTrend Trend Following

## Strategy Family
`trend_following`

## Hypothesis
SuperTrend uses ATR-based bands to define trend direction. When price is above the
SuperTrend line, the trend is up; when below, the trend is down. Unlike MA crossovers,
SuperTrend incorporates volatility directly into its calculation, providing adaptive
stop levels that expand in volatile conditions and contract in quiet ones.

## Instrument Candidates
- MNQ (intraday trend following)
- MES (similar)
- MGC (excellent — gold trends strongly)
- MCL (crude oil trends)

## Timeframe
- Primary: 15m, 1H
- Daily works for swing trading (not focus for this library)

## Session
- RTH + ETH (SuperTrend is time-agnostic, but ETH can have thin bars)
- Recommend RTH only for first adaptation

## Indicators
1. ATR(14) — used internally by SuperTrend
2. SuperTrend(10, 3.0) — period=10, multiplier=3.0 standard
   - Upper band = Median ± (ATR * mult)
   - Direction flips when price crosses band

## Entry Rules
**Long:**
1. SuperTrend direction flips to bullish (previous bar was bearish, current is bullish)
2. Price > SuperTrend line
3. Enter at next bar open (or same-bar close if confirmed)

**Short:**
1. SuperTrend direction flips to bearish
2. Price < SuperTrend line
3. Enter at next bar open

## Exit Rules
- **Primary:** SuperTrend flips opposite direction (trailing nature of the indicator)
- **Stop:** SuperTrend line itself acts as trailing stop
- **Time stop:** Session end
- Fixed ATR stop as fallback: ATR(14) * 2.0

## Stop Loss Logic
- SuperTrend line = dynamic trailing stop
- Fixed fallback: ATR * 2.0 from entry
- Key: SuperTrend stop is usually 2-3x ATR away on entry — WIDE stop

**$2k account concern:** Wide stops on MNQ may push quantity to 0 via ComputeQuantity.
Must use MaxStopTicks cap or floor qty=1.

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| SuperTrendPeriod | 10 | [7, 20] |
| SuperTrendMultiplier | 3.0 | [2.0, 4.0] |
| AtrPeriod | 14 | [10, 20] |
| MaxStopTicks | 30 | [20, 50] |
| MaxDailyTrades | 3 | [1, 6] |

## Expected Signal Frequency
- 15m RTH: 0–2 flips per day
- Monthly: 15–35 trades

## Failure Modes
1. **Wide stops** → position sizing to 0 on $2k account
2. **Whipsaw in ranging market** → rapid back-and-forth flips
3. **Entry too late** → SuperTrend flip confirmed well after actual turn
4. **Same-bar stop risk** on fast moves (stop is 2-3 ATR away but price can gap)

## Why SuperTrend Is a Good Reference
- Natural ATR-based trailing stop built into the indicator
- No separate stop calculation needed (simplifies strategy code)
- Works across multiple instruments and timeframes
- Lower signal frequency → fewer commission charges

## Market Regimes
- Strong trending (commodities, NASDAQ in bull runs): excellent
- Sideways/choppy: poor (multiple flips, all small losses)

## Overfit Risk
**MEDIUM** — multiplier (3.0) and period (10) can be optimized. Use defaults.
Standard (10, 3.0) is widely used benchmark.
