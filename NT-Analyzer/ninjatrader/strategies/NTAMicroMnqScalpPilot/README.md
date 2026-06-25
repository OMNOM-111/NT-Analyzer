# NTAMicroMnqScalpPilot

High-frequency intraday scalping strategy family for **MNQ** (Micro E-mini NASDAQ-100) at **$2000 starting capital**, primary timeframe **1 Minute**.

Lives **alongside** the locked `NTAMicroVwapRiskPilot` B1 ShortOnly profile (`b1_shortonly_mnq_5m_high_slip1_paper_v2`). Does **not** modify, share state with, or replace the locked Pilot.

## Modules

Primary architecture is four independent enable/disable modules. `SetupMode`
is retained only as a legacy single-module research filter when
`UseSetupModeFilter = true`.

| Parameter | Module | Idea |
|------|------|
| `EnableVwapReclaim` | VWAP Reclaim | price reclaims/loses session VWAP with EMA9/21 confirmation |
| `EnableEmaMomentum` | EMA Momentum Burst | EMA9>EMA21>EMA50 or inverse, pullback to EMA9/21, continuation bar |
| `EnableMicroOrb` | Micro ORB | 3-minute 06:30 PT opening range break, retest, continuation |
| `EnableFailedBreakout` | Failed Breakout | local high/low sweep that closes back through the broken level |

Direction is gated by `EnableLong` / `EnableShort` toggles independent of mode.

## Risk shell

Mirrors `NTAMicroVwapRiskPilot` / `NTAMicroSessionEdgeExplorer` `RiskManager`:

- `RiskPerTradePct` budget vs `(stop_ticks * tick_value + RoundTurnCommission + slip*tick_value)`
- `MaxDailyLossUsd` / `MaxWeeklyLossUsd` / `MaxConsecutiveLosses` / `MaxTradesPerDay` daily stop
- `PauseAfterConsecutiveLosses` + `PauseMinutesAfterLosses`
- `MoveToBreakevenAtR` + `TrailAfterR`
- `UseTimeStop` + `TimeStopBars` + `MinProgressR` (scalp-essential)
- `ForceFlatTime` (default 12:45 PT)

## Cost model

- `commission_template = "None"` upstream → NT8 reports gross PnL.
- Strategy subtracts `RoundTurnCommission * |qty|` on each closed trade.
- All accepted research uses `OrderFillResolution = High`, `slippage_ticks ≥ 1`, `RoundTurnCommission ≥ 1.90`.

## Default trading windows (PT)

- Primary: 06:35 – 08:30 PT  (09:35 – 11:30 ET)
- Secondary: 10:30 – 12:00 PT  (13:30 – 15:00 ET)
- Force flat: 12:45 PT

## Default scalp parameters

```
EmaFast=9   EmaMid=21   EmaSlow=50
Atr=14      AtrStopMult=0.35  MinStop=8   MaxStop=16
RR=1.25     BE=0.7R     Trail=1.0R
TimeStopBars=3   MinProgressR=0.30
MaxTradesPerDay=20   HardMaxTradesPerDay=25
RiskPerTradePct=0.35   MaxDailyLossUsd=60   MaxWeeklyLossUsd=150
UserMaxContracts=1
RoundTurnCommission=1.90   SlippageTicks=1
OrbStartTime=630   OrbDurationMinutes=3
```

## Research pipeline

```
tools/research/python/submit_mnq_scalp_pilot.py   stage0/full
tools/research/python/collect_mnq_scalp_pilot.py  metrics + classification
```

Bundle output: `data/research/mnq_scalp_pilot_<timestamp>/`

## Acceptance gates (combined: spec + ГПТ aggressive scalping)

- High fill / slippage_ticks ≥ 1 / RoundTurnCommission ≥ 1.90 / commission_template = None
- Trades/day 10–20
- Adj PF ≥ 1.35
- OOS Adj PF ≥ 1.25
- Win rate ≥ 52%
- Avg trade after commission ≥ $1.50
- Max drawdown ≤ 15% × StartingCapital (allocated capital ячейки; при $2000 → $300)
- Max losing streak ≤ 5
- Daily stop hits ≤ 5% of trading days
