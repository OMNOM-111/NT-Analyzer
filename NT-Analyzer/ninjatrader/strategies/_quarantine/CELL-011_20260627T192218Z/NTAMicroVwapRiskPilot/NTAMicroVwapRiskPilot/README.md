# NTAMicroVwapRiskPilot - B1 ShortOnly locked snapshot

This folder is a Git-tracked snapshot of the NinjaTrader 8 strategy source from:

`Documents/NinjaTrader 8/bin/Custom/Strategies/NTAMicroVwapRiskPilot/`

The live NinjaTrader installation still compiles the source from the NinjaTrader
`Custom/Strategies` folder. This snapshot exists so the first accepted working
strategy is preserved in GitHub together with NT-Analyzer.

## Accepted paper candidate

Strategy: `NTAMicroVwapRiskPilot`

Mode: B1 ShortOnly

Canonical backtest:

- Job: `ui_20260501T185820607Z`
- Instrument: `MNQ 06-26`
- Timeframe: `5 Minute`
- Period: `2024-01-01` to `2025-12-31`
- Fill: `High`
- Slippage: `1 tick`
- Round-turn commission: `$1.90 * quantity`
- Trades: `92`
- Qty-aware adjusted net: `+$2,738.30`
- Adjusted PF: `2.49`
- Adjusted max drawdown: `-$174.00`
- Positive quarters: `8/8`

## Locked defaults

These defaults are intentionally locked by NT-Analyzer for backtests and paper:

| Parameter | Value |
|---|---:|
| `EnableLong` | `false` |
| `EnableShort` | `true` |
| `UseDailyBiasFilter` | `false` |
| `EmaFastPeriod` | `50` |
| `EmaSlowPeriod` | `200` |
| `TradeStartTime` | `635` |
| `TradeEndTime` | `700` |
| `MinStopTicks` | `12` |
| `MaxStopTicks` | `12` |
| `RewardRiskRatio` | `3.5` |
| `RiskPerTradePct` | `2.0` |
| `UserMaxContracts` | `5` |
| `RoundTurnCommission` | `1.90` |
| `SlippageTicks` | `1` |
| `StartingCapital` | `2000.0` |
| `IntradayOnly` | `true` |
| `ActiveMarginPerContract` | `50.0` |
| `MaxContractsByCapital` | `40` |
| `InstrumentStatus` | `allowed` |
| `MarginSourceBroker` | `NinjaTrader` |

## File layout

The strategy is split into NinjaScript partial class files:

| File | Purpose |
|---|---|
| `NTAMicroVwapRiskPilot.cs` | Fields, `OnStateChange`, `OnBarUpdate`; only file declaring `: Strategy`. |
| `NTAMicroVwapRiskPilot.Properties.cs` | `[NinjaScriptProperty]` declarations. |
| `NTAMicroVwapRiskPilot.RiskManager.cs` | Risk gate, position sizing, adjusted accounting. |
| `NTAMicroVwapRiskPilot.Entry.cs` | Entry signal, stop calculation, pending-entry handling. |
| `NTAMicroVwapRiskPilot.Position.cs` | Open-position management. |
| `NTAMicroVwapRiskPilot.Time.cs` | Time-window helpers. |
| `NTAMicroVwapRiskPilot.Events.cs` | Order/position event handlers. |
| `NTAMicroVwapRiskPilot.Diagnostics.cs` | Diagnostic logging helpers. |

Do not change trading logic or optimize parameters during paper testing.
