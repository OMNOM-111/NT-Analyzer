# NTAMicroSessionEdgeExplorer — multi-mode research strategy

Modular research strategy for non-MNQ Topstep micros. Exposes a `SetupMode`
parameter that dispatches to different entry families. **Not** a paper-ready
strategy; produces research candidates only.

## Locked Pilot is NOT touched
`NTAMicroVwapRiskPilot` (and its locked B1 ShortOnly MNQ profile) remains the
sole `paper_ready` strategy. This new class lives alongside it as research.
**MNQ is excluded** from this strategy's research universe.

## SetupMode catalog

| Mode | Intended families | What it does |
|---|---|---|
| `VwapPullback` (default) | sanity / regression | Bit-for-bit identical to `NTAMicroVwapRiskExplorer` v0.5 entry logic. Compile-safe baseline. |
| `OrbContinuation` | index micros (MES/MYM/M2K) | Build OR over first `OrbDurationMinutes` after `TradeStartTime`. Enter long on close > OR high + buffer; short on close < OR low − buffer. |
| `FailedOrbReversal` | index micros | After OR break-up that closes back inside OR within `OrbFailedLookback` bars + down momentum → enter short. Symmetric for failed break-down. |
| `VwapMeanReversion` | metals (MGC/MHG) | When `(Close − VWAP)/ATR ≥ MeanRevExtensionAtr` and momentum reverses, fade toward VWAP. Optional VWAP-target. |
| `CompressionBreakout` | energy (MCL/MNG) | Current ATR is in lowest `CompressionAtrPct` of last `CompressionLookback` bars → break of recent extreme triggers entry. |
| `RollingVwapCrypto` | crypto (MBT/MET) | Maintains rolling 24h VWAP via ring buffer (`RollingVwapBars` bars). Cross + momentum entry. Set `Use24hSession=true` to bypass intraday window/force-flat. |

## File layout

```
NTAMicroSessionEdgeExplorer/
  NTAMicroSessionEdgeExplorer.cs              # SetDefaults, OnStateChange, OnBarUpdate, ORB state
  NTAMicroSessionEdgeExplorer.Properties.cs   # All [NinjaScriptProperty] declarations
  NTAMicroSessionEdgeExplorer.Time.cs         # Trade window + news blackout
  NTAMicroSessionEdgeExplorer.Position.cs     # Breakeven move + trailing stop
  NTAMicroSessionEdgeExplorer.RiskManager.cs  # Equity/sizing/daily limits
  NTAMicroSessionEdgeExplorer.Events.cs       # OnOrderUpdate / OnPositionUpdate
  NTAMicroSessionEdgeExplorer.Diagnostics.cs  # Skip-log dedupe
  NTAMicroSessionEdgeExplorer.Entry.cs        # All 6 EvaluateEntry_* methods + helpers
```

## How to compile (REQUIRED before running any backtests)

1. Open NinjaTrader 8.
2. Open NinjaScript Editor (Tools → NinjaScript Editor).
3. Press **F5** (Compile). Resolve any errors before continuing.
4. Backend reads the strategy whitelist from `data/catalog/strategies.json`,
   which the bridge writes after a successful compile + restart cycle.
5. Submit a Stage 0 smoke job (one per family × mode) to confirm the class
   resolves end-to-end.

If compile fails, the file pair to inspect first is `*.Entry.cs` (most new
code) and `*.cs` (state machine + ORB helpers).

## Risk & cost conventions
Same as Pilot/Explorer:
- `commission_template="None"` upstream → NT8 reports gross PnL → strategy
  subtracts `RoundTurnCommission * |qty|` once per closed trade in
  `RiskManager.RecordClosedTrade`.
- All HHMM windows are **Pacific Time** (PC local). ET = PT + 3h.
- `RoundTurnCommission` is a **project backtest assumption**, NOT a TopStep
  fee schedule.

## Default parameter table per SetupMode (for submit scripts)
See `tools/research/python/research_lib.py → setup_mode_defaults(mode, root)`.
