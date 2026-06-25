# Weak Strategy Result Summary

- Class: `NTAAiSandboxEmaPullback01`
- Root: `MNQ`
- Timeframe: `5m`
- Session window: `06:30-09:30 PT`
- Current parameters: `EmaFast=20`, `EmaSlow=50`, `AtrStopMult=1.2`, `ProfitTargetR=1.4`, `TrendThreshold=0.25`, `MaxTradesPerDay=3`, `ForceFlatTime=1015`

Recent results:

- Full adjusted net: `-84.60`
- Profit factor: `0.96`
- IS adjusted net: `41.20`
- OOS adjusted net: `-125.80`
- Max drawdown: `-290.00`
- Trade count: `92`
- Same-bar ambiguity: `48%`

Observed behavior:

- Most losses come from the first 30 minutes after the open.
- Winners improve when the ATR stop is wider, but trade count drops quickly.
- The previous run already changed `AtrStopMult` from `1.0` to `1.2`.
- Avoid changing more than 2 parameters in one iteration.

Goal: decide whether this strategy should be rejected or which small next mutations are worth testing.