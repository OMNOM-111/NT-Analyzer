# Prompt 01 - Code Generation

Write a short NinjaTrader 8 strategy in C# for benchmark evaluation.

Requirements:

- Output one fenced `csharp` code block first.
- Namespace must be exactly `NinjaTrader.NinjaScript.Strategies`.
- Use `OnStateChange` and `OnBarUpdate`.
- Use `EMA(20)`, `EMA(50)`, and `ATR(14)`.
- Use `SetStopLoss`.
- Use `SetProfitTarget`.
- Use `EnterLong` and `EnterShort`.
- Expose `MaxTradesPerDay` and `ForceFlatTime` as `[NinjaScriptProperty]` inputs.
- Force-flat positions using `ForceFlatTime` in `HHmm` integer format.
- Keep it intraday-only and avoid overnight holds.
- Do not use `NinjaTrader.Strategy`, NT7 `Initialize()`, live/account API, or Strategy Analyzer API.
- Keep the code within 180 lines.
- Prefer code that is likely to compile in NinjaTrader 8.

After the code block, add at most 5 short bullets for assumptions or known limitations.