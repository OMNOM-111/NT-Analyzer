# Normalized Spec: REF-013 — Donchian Channel Breakout (Turtle System)

## Strategy Family
`breakout_channel`

## Hypothesis
Price breaking to a new N-period high represents a momentum signal: the market is
making new ground and trend-following buyers are in control. The Turtle Trading System
(Richard Donchian / Curtis Faith) systematized this approach: enter on 20-day high
breakout (System 1) or 55-day high (System 2), exit on 10-day low.

## IMPORTANT NOTE ON TIMEFRAME
The original Turtle System uses DAILY bars for futures. The Donchian breakout
concept can be adapted to intraday (using N-bar highs instead of N-day highs),
but the statistical properties differ significantly from the daily system.

## Instrument Candidates
- MGC (gold — trends strongly, Donchian was designed for commodities)
- MCL (crude oil — similar)
- MNQ (can work but equity index is more mean-reverting than commodities)
- MES (similar)

## Timeframe
- **Original:** Daily bars (N=20 or N=55)
- **Intraday adaptation:** 1H bars with N=20 bars (= 2-3 RTH sessions)
- **Avoid:** 5m/15m (too much noise for Donchian)

## Session
- Original: session-agnostic (daily)
- Intraday: RTH + ETH for level calculation, enter RTH

## Indicators
1. DonchianHigh(20) = highest high of last 20 bars
2. DonchianLow(20) = lowest low of last 20 bars
3. ATR(20) — position sizing (Turtle system uses N = ATR)
4. Optional: DonchianHigh(10) / DonchianLow(10) — exit levels

## Turtle System 1 Rules (adapted)
**Entry:**
1. Price closes above DonchianHigh(20) = new 20-period high
2. Enter at next bar open
3. Add units at each 0.5N (ATR unit) above entry (pyramiding)
   — For $2k account: NO pyramiding, single entry only

**Exit (System 1):**
1. Price closes below DonchianLow(10) = new 10-period low
2. Exit at next bar open

**Stop (Turtle):**
1. Initial stop = entry - 2 * N (where N = ATR)
2. Trail stop at 2N below highest high since entry

## Stop Loss Logic
- Turtle system: 2 * ATR(20) from entry (WIDE stop)
- For $2k MNQ: 2 * ATR can be 40-80 ticks → qty = 0 via ComputeQuantity
- **ADAPTATION NEEDED:** MaxStopTicks = 25 cap with floor qty=1
- This changes the system significantly from original

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| DonchianPeriod | 20 | [10, 55] |
| ExitPeriod | 10 | [5, 20] |
| AtrPeriod | 20 | [14, 30] |
| AtrStopMult | 2.0 | [1.0, 3.0] |
| MaxStopTicks | 25 | [15, 40] |

## Expected Signal Frequency
- 1H RTH: 0–1 signals/week
- Monthly: 4–12 trades
- Low frequency = each trade matters significantly

## Failure Modes
1. **Wide stops** → position sizing to 0 on $2k account without fix
2. **Choppy equity markets:** Turtle system designed for trending commodities
3. **Short holding periods:** Donchian needs multi-day trends to profit
4. **Adaptation kills edge:** capping stops changes Turtle system's statistical basis

## Turtle System Public Domain Status
The Turtle Trading Rules were published by Curtis Faith at originalturtles.org.
The complete rules are public domain (released freely after original secrecy ended).
Original Turtle Trading System rules: https://www.originalturtles.org/docs/turtlerules.pdf

## Why Donchian Works for Commodities
- Commodities trend persistently (supply/demand cycles)
- 20-day new high = institutional recognition of new price level
- Works on MGC, MCL historically

## Why May Not Work for Intraday Index Micros
- NQ/MNQ is more mean-reverting at 1H than daily
- Commission drag higher relative to move size on intraday
- Position sizing issues at $2k account level

## Market Regimes
- Trending commodities markets: excellent
- Mean-reverting equity markets: poor
- Sideways/choppy: very poor (whipsaw)

## Overfit Risk
**LOW** — N=20 and 55 are fixed Turtle system values. Don't optimize.
If results poor, the market regime doesn't suit the system (don't fix with optimization).

## Reference Value for AI
- Teaches systematic trend following concepts
- ATR-based position sizing is applicable to all strategies
- Pyramiding concept (disabled for $2k) is important for larger accounts
