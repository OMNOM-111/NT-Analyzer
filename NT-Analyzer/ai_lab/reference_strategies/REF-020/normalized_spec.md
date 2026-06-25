# Normalized Spec: REF-020 — Trend Continuation Pullback

## Strategy Family
`trend_pullback`

## Hypothesis
In a trending market, the highest probability entries are NOT at breakouts but at
pullbacks within the trend. After a series of higher highs and higher lows (uptrend),
price consolidates and pulls back to a key level (EMA, VWAP, or prior swing). Entering
at this pullback captures the continuation move with a natural nearby stop (the pullback
level) and a high R:R target (prior swing high or ATR multiple).

## Instrument Candidates
- MNQ (primary — trends well intraday and daily)
- MES (secondary)
- MGC (excellent for multi-day pullback entries)

## Timeframe
- Primary: 15m (intraday pullback to EMA or VWAP)
- Secondary: 1H (larger pullback, fewer false signals)
- Avoid: 5m (too much noise, pullback never confirms)

## Session
- RTH: 09:30–14:00 ET
- ETH: possible on 1H with established overnight trend

## Indicators
1. EMA(20) — first support for pullback
2. EMA(50) — trend bias (price must be above EMA50 for longs)
3. ADX(14) — trend strength (>25 = real trend)
4. ATR(14) — stop sizing and pullback tolerance
5. Optional: VWAP as additional pullback target

## Entry Rules
**Long continuation pullback:**
1. ADX(14) > 25 (trend present)
2. EMA20 > EMA50 (bullish trend stack)
3. Price has been making higher highs in last 5-10 bars
4. Price pulls back to within ATR * 0.75 of EMA20
5. Pullback bar: close above EMA20 (hold at support)
6. ADX not declining sharply (trend not ending)
7. Enter at next bar open

**Short continuation pullback:**
1. ADX(14) > 25
2. EMA20 < EMA50 (bearish stack)
3. Price making lower lows
4. Price rallies to within ATR * 0.75 of EMA20
5. Close below EMA20
6. Enter at next bar open

## Exit Rules
- **Stop:** EMA20 - ATR * 0.75 (for longs — below pullback support)
- **Target:** Prior swing high (for longs) or ATR * 2.5 minimum
- **Trailing:** Trail by EMA20 once 1 ATR in profit
- **ADX decay exit:** exit if ADX falls below 20 and price stalls

## Stop Loss Logic
- EMA20 ± ATR buffer as dynamic stop
- Typically 8-16 ticks on 15m MNQ
- Better R:R than crossover entries because entry is closer to support

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| EmaTrend | 50 | [30, 100] |
| EmaSupport | 20 | [10, 30] |
| AdxPeriod | 14 | [10, 20] |
| AdxThreshold | 25.0 | [20.0, 35.0] |
| PullbackAtrTol | 0.75 | [0.25, 1.25] |
| StopAtrMult | 0.75 | [0.5, 1.5] |
| TargetAtrMult | 2.5 | [2.0, 4.0] |
| MaxDailyTrades | 3 | [1, 6] |

## Expected Signal Frequency
- 15m RTH with ADX>25 filter: 0–2 signals/day on trend days
- 0 signals on choppy days (correct behavior)
- Monthly: 15–40 trades

## Failure Modes
1. **ADX threshold** blocks entry on slow-developing trends
2. **EMA period mismatch:** EMA20 on 15m ≠ EMA20 on 1H — different zones
3. **2025 regime:** CELL-019 Engine #6 RTH Trend-Day H1 REJECTED
   - 2024 PF 1.44 → 2025 PF 1.07: regime shift, not parameter issue
   - 2025 MNQ: trend-days SET UP but REVERSE on H1 more than 2024

## CELL-019 Meta-Lesson Applied Here
From Engine #6 and #9 (Gap-Go, RTH trend-day): tightening stops shrinks 2024 PF
more than it shrinks 2025 DD. Hard tradeoff.
Regime filter (prior-day range expansion) isolates edge but 2025 those setups reverse.

## Why Pullback > Crossover Entry
- Entry at EMA = natural support level
- Stop is 8-12 ticks (below support), not 15-25 ticks (like crossover stop)
- R:R of 1:3 achievable vs 1:2 for crossover

## Market Regimes
- Strong trending days: excellent
- Choppy/ranging: ADX filter blocks correctly
- 2025 MNQ RTH: caution (Engine #6 regime shift confirmed)

## Recommended Enhancements for AI-CELL
1. Add VWAP as second support level (pullback to EMA OR VWAP)
2. Add prior-day range filter (NR7 previous day = compression → possible trend)
3. Max 2 trades/day (Engine #6 lesson: overtrading in trend)
4. Session filter: avoid 14:30-16:00 (FOMC/news risk at that hour)

## Overfit Risk
**MEDIUM** — ADX threshold and PullbackAtrTol can overfit.
Use fixed ADX=25 and ATR tolerance=0.75; don't optimize per year.
