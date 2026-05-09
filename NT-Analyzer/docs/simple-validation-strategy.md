# NTAnalyzerEveryNBarLong validation strategy

This is a deliberately simple deterministic strategy for comparing NinjaTrader Strategy Analyzer results with NT-Analyzer results.

Strategy file:

`%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\Strategies\NTAnalyzerEveryNBarLong.cs`

## Logic

- Long-only.
- Wait until `CurrentBar >= StartBar`.
- If flat and `(CurrentBar - StartBar) % EntryEveryBars == 0`, enter long.
- Exit after `HoldBars` bars since entry execution.
- Uses `Calculate.OnBarClose`.
- Uses one named entry signal: `Long`.
- Uses one named exit signal: `Exit`.

## Default parameters

| Parameter | Default |
|---|---:|
| Quantity | 1 |
| StartBar | 20 |
| EntryEveryBars | 50 |
| HoldBars | 10 |

Important: `EntryEveryBars` must be greater than `HoldBars`; otherwise the strategy will not enter trades.

## Recommended comparison setup

Use exactly the same values in NinjaTrader Strategy Analyzer and NT-Analyzer:

- Strategy: `NTAnalyzerEveryNBarLong`
- Instrument: `MES 06-26`
- Type: `Minute`
- Value: `1`
- Period: `2026-03-12` to `2026-04-24`
- Trading hours: `CME US Index Futures RTH`
- Commission template: compare both `None` and the selected NinjaTrader template separately.
- Parameters:
  - `Quantity = 1`
  - `StartBar = 20`
  - `EntryEveryBars = 50`
  - `HoldBars = 10`

## What to compare

Compare these fields first:

- Total trades
- Net profit
- Gross profit
- Gross loss
- Profit factor
- Max drawdown
- Percent profitable
- First trade entry/exit time
- Last trade entry/exit time

If these match, then the bridge period, bar series, fills, commission setting, and trade export are aligned.

