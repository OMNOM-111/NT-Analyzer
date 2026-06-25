# Normalized Spec: REF-003 — EMA Trend Pullback

## Strategy Family
`trend_pullback`

## Hypothesis
In a trending market, price regularly pulls back to the EMA20. When price touches or
approaches the EMA20 from above (in an uptrend), it represents a lower-risk entry point
in the direction of the trend, offering better R:R than crossover entries.

## Instrument Candidates
- MNQ (primary — trends well intraday)
- MES (secondary)
- MGC (good trending commodity)

## Timeframe
- Primary: 15m or 1H
- Secondary: 5m (requires tight stops, fragile on micros)

## Session
- RTH: 09:30–15:30 ET (avoid final hour)
- ETH: possible on 1H if trend established overnight

## Indicators
1. EMA(20) — dynamic support/resistance
2. EMA(50) — trend bias
3. ADX(14) — trend strength (>25 = good trend)
4. ATR(14) — stop sizing

## Entry Rules
**Long pullback entry:**
1. EMA20 > EMA50 (uptrend confirmed)
2. ADX(14) > 25
3. Price has pulled back to within ATR(14) * 0.5 of EMA20
4. Entry bar: price bounces from EMA20 (close above EMA20 after touching it)
5. Enter on next bar open

**Short pullback entry:**
1. EMA20 < EMA50 (downtrend confirmed)
2. ADX(14) > 25
3. Price has pulled up to within ATR(14) * 0.5 of EMA20
4. Entry bar: price bounces off EMA20 (close below EMA20 after touching it)
5. Enter on next bar open

## Exit Rules
- Stop: EMA20 - ATR(14) * 1.0 (for longs) / EMA20 + ATR(14) * 1.0 (for shorts)
- Target: last swing high (for longs) or ATR * 2.5 minimum
- Exit: next opposite EMA crossover or session end

## Stop Loss Logic
- Dynamic: EMA20 ± ATR buffer
- Min stop: 8 ticks, Max: 24 ticks
- Key advantage over crossover: entry is closer to support → smaller stop → better R:R

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| EmaTrendPeriod | 50 | [30, 100] |
| EmaSupportPeriod | 20 | [10, 30] |
| AdxPeriod | 14 | [10, 20] |
| AdxThreshold | 25.0 | [20.0, 35.0] |
| AtrPeriod | 14 | [10, 20] |
| PullbackAtrMult | 0.5 | [0.25, 1.0] |
| StopAtrMult | 1.0 | [0.5, 2.0] |
| TargetAtrMult | 2.5 | [1.5, 4.0] |

## Expected Signal Frequency
- 15m RTH with ADX filter: 0–2 signals/day (10–40 trades/month)
- Low frequency but higher R:R than crossovers

## Failure Modes
1. **No pullback on strong trend day** — price never touches EMA20, misses entire move
2. **ADX spikes then drops** — enters after move is over
3. **2025 MNQ regime:** more reversals than 2022-2023; EMA support breaks frequently
4. **Choppy ADX readings:** ADX > 25 but actually ranging

## Why Higher R:R Than Crossover
- Entry at EMA = natural support, stop below support
- Crossover entry = after signal, further from support → larger stop
- Pullback entry: stop 8-12 ticks, target 20-30 ticks → R:R 2:1 or better

## Recommended For AI-CELL
Good candidate for AI-CELL-007/008. Key additions:
- VWAP as additional bias (price above VWAP AND above EMA50 = long only)
- Time filter: avoid ORB hour (09:30-10:00)
- Max 2 trades/day to avoid overtrading

## Market Regimes
- Trending days: excellent
- Choppy: poor (ADX filter helps but not fully)
- Pre-RTH (ETH): needs session-appropriate EMA period

## Overfit Risk
**MEDIUM** — pullback tolerance (PullbackAtrMult) and ADX threshold can be overfit.
Mitigation: use round numbers (ADX=25, mult=0.5) and don't optimize per year.
