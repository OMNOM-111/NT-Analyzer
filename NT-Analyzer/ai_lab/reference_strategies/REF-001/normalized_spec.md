# Normalized Spec: REF-001 — SMA 9/21 Crossover

## Strategy Family
`crossover_trend`

## Hypothesis
When a faster SMA (period 9) crosses above a slower SMA (period 21), momentum has shifted
upward and price is likely to continue higher in the short term. The reverse applies for
bearish crossovers. The strategy captures trending moves while avoiding holding through
counter-trend consolidations.

## Instrument Candidates
- MNQ (primary — liquid, trending index)
- MES (secondary — similar behavior)
- MYM, M2K (tertiary)

## Timeframe
- Primary: 15m (best signal/noise ratio for intraday micros)
- Secondary: 1H (lower frequency, larger stops needed)
- Avoid: 5m (too much noise, commission drag)

## Session
- RTH only: 09:30–16:00 ET
- Avoid first 15m after open (volatile)
- Avoid last 30m before close

## Indicators
1. SMA(9) — fast moving average
2. SMA(21) — slow moving average
3. Optional: ADX(14) — trend strength filter (>20 = trending)
4. Optional: Volume — confirm crossover with above-average volume

## Entry Rules
**Long entry:**
1. SMA9 crosses above SMA21 (golden cross on current bar close)
2. Candle closes above both SMAs
3. ADX(14) > 20 (trend is present)
4. Enter at next bar open (avoid same-bar execution risk)

**Short entry:**
1. SMA9 crosses below SMA21 (death cross on current bar close)
2. Candle closes below both SMAs
3. ADX(14) > 20
4. Enter at next bar open

## Exit Rules
**Exit long:**
- Stop: ATR(14) * 1.5 below entry (or fixed MinStopTicks)
- Target: ATR(14) * 2.5 above entry (or trailing)
- Time stop: exit at session end (IsExitOnSessionClose = true)
- Opposite signal: SMA9 crosses below SMA21

**Exit short:**
- Stop: ATR(14) * 1.5 above entry
- Target: ATR(14) * 2.5 below entry
- Time stop + opposite signal

## Stop Loss Logic
- ATR-based: StopTicks = ATR(14) * 1.5 / TickSize
- Minimum: 8 ticks (MNQ = 4 points = $20)
- Maximum: 24 ticks (MNQ = 12 points = $60)

**IMPORTANT for $2k MNQ account:**
- ComputeQuantity must handle ATR-sized stops
- If ATR stop plus costs exceeds riskBudget, qty must be 0 and the entry must be skipped
- Never use MaxDailyLossUsd to override a per-trade risk-budget failure

## Take Profit / Trailing / Time Stop
- Fixed R:R = 1.5 or use trailing stop (ATR * 1.0 trail)
- ExitOnSessionClose = true
- Max hold: session end only

## Max Trades/Day
- Recommended: 3 per direction (6 total)
- With ADX filter: typically 1-2 per day

## Risk Rules
- MaxDailyLossUsd: $80–120 on $2k account
- PauseAfterConsecutiveLosses: 2–3
- UserMaxContracts: 1

## Parameters (tunable)
| Parameter | Default | Range |
|-----------|---------|-------|
| FastPeriod | 9 | [5, 20] |
| SlowPeriod | 21 | [15, 50] |
| AdxPeriod | 14 | [10, 20] |
| AdxThreshold | 20.0 | [15.0, 30.0] |
| AtrPeriod | 14 | [10, 20] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| AtrTargetMult | 2.5 | [1.5, 4.0] |
| MaxDailyTrades | 6 | [2, 10] |
| MaxDailyLossUsd | 100.0 | [50.0, 200.0] |

## Expected Signal Frequency
- 15m, RTH only: 2–5 signals per day (with ADX filter: 0–2)
- Monthly: 20–60 trades

## Failure Modes
1. **Choppy market:** SMAs whipsaw → rapid losing streaks
2. **Large ATR:** stop sizing pushes qty to 0; this setup is infeasible for the account
3. **Late entry:** crossover already happened, signal stale by entry bar
4. **Commission drag:** crossover at 15m requires gross/trade >= $5 minimum

## Recommended Sanity Checks
1. Run smoke (12 variants) — verify trade_count > 0 with wide-open params
2. Check same-bar% — should be < 50%
3. Verify gross_per_trade > $3.80 (2x commission) before testing stops/targets
4. ADX filter must reduce trade count significantly vs no-ADX version
5. 2025 OOS check — ensure strategy works on recent data

## Market Regimes That Suit This Strategy
- Strong trending: excellent (2020-2021, 2023 bull runs)
- Slowly trending: OK
- Choppy/ranging: poor
- High volatility intraday reversals: poor

## Why This Strategy May Work
- Moving averages are self-fulfilling when widely watched levels (9, 21, 50, 200)
- Trend persistence in equity index futures (especially MNQ/NQ)
- ADX filter removes most choppy false signals

## Why This Strategy May Not Work
- Crossovers inherently lagging — entry often after the move is underway
- 2025 MNQ: more reversals than 2020-2022 trending years
- Commission of $1.90 per side = $3.80 RT is high for 15m signals
- Whipsaw: ADX often drops back below threshold mid-trend

## Overfit Risk Assessment
**LOW** — only 2 core parameters (fast/slow period), well-known values
- Risk: ADX threshold optimization can overfit to specific year
- Mitigation: use ADX > 20 as hard rule, don't optimize it
