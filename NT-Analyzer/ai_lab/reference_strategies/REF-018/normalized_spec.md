# Normalized Spec: REF-018 — ATR Breakout Momentum

## Strategy Family
`breakout_momentum`

## Hypothesis
When price moves more than a specified ATR multiple above/below the prior bar's
close or high/low, it signals a momentum expansion beyond normal daily noise.
This ATR-based breakout is adaptive: in low-volatility periods (small ATR),
the threshold is tight; in high-volatility periods (large ATR), the threshold expands.
The strategy captures the start of accelerating moves.

## Instrument Candidates
- MNQ (primary)
- MES (secondary)
- MGC, MCL (commodities with ATR-appropriate moves)

## Timeframe
- Primary: 15m, 1H
- 5m: ATR threshold often triggered intrabar, same-bar risk high

## Session
- RTH: 09:30–14:00 ET
- Avoid: 15:30–16:00 ET (thin end-of-day moves)

## Indicators
1. ATR(14) — primary indicator (breakout threshold)
2. EMA(20) — trend bias
3. Volume — optional confirmation

## Entry Rules
**Long ATR momentum break:**
1. Current bar high > prior bar high + ATR(14) * multiplier
2. Close confirms momentum (close > open + ATR * 0.5)
3. EMA(20) is rising (trend bias)
4. Enter at next bar open (avoid chasing on same bar)

**Short ATR momentum break:**
1. Current bar low < prior bar low - ATR(14) * multiplier
2. Close < open - ATR * 0.5
3. EMA(20) is falling
4. Enter at next bar open

## Exit Rules
- **Stop:** Entry - ATR(14) * 1.5 (for longs)
- **Target:** Entry + ATR(14) * 2.0 (for longs)
- **Trailing:** ATR * 1.0 trail once target half reached
- **Time stop:** session end

## Stop Loss Logic
- Fixed ATR from entry (not from bar level)
- MinStopTicks: 8, MaxStopTicks: 25
- ATR stop ensures commission viability (ATR move >> commission)

## Parameters
| Parameter | Default | Range |
|-----------|---------|-------|
| AtrPeriod | 14 | [10, 20] |
| AtrBreakMult | 1.0 | [0.5, 2.0] |
| AtrStopMult | 1.5 | [1.0, 2.5] |
| AtrTargetMult | 2.0 | [1.5, 3.5] |
| EmaPeriod | 20 | [10, 50] |
| MaxDailyTrades | 4 | [2, 8] |

## Expected Signal Frequency
- 15m RTH: 1–3 signals/day
- Monthly: 25–60 trades

## Failure Modes
1. Momentum bar followed by immediate reversal (false breakout)
2. ATR expands in choppy period → entries become too frequent
3. Same-bar exit risk: big momentum bar = entry AND stop on same bar

## Why ATR Breakout Works as a Component
ATR breakout is most powerful as a COMPONENT of other strategies, not standalone:
- ORB breakout: ORB break > ATR * 1.0 above opening range = confirm momentum
- VWAP deviation: price > VWAP + 2 ATR = significant deviation
- Compression: compression break + ATR expansion = momentum confirmation

## Market Regimes
- High-volatility trending: excellent
- Low-volatility ranging: poor (frequent small ATR breaks, no follow-through)

## Overfit Risk
**LOW-MEDIUM** — AtrBreakMult selection (0.5 vs 1.0 vs 1.5) matters.
Test: does same mult work on 2024 and 2025? If only one year, overfit.
