# Phase 17 task for Claude — NinjaTrader runtime bridge for Strategy Control Center

## Goal

Finish the Strategy Control Center so it shows the real NinjaTrader runtime state, not only NT-Analyzer registry state.

Current Phase 16 is useful but incomplete:
- UI shows registered strategies and paper workflow state from `NT-Analyzer/data/ops`.
- UI does **not** auto-detect a strategy manually enabled inside NinjaTrader.
- UI does **not** ingest real paper executions/fills from NinjaTrader.
- UI does **not** reconcile Ninja runtime state against locked strategy parameters.

Phase 17 must close that gap end-to-end.

## Hard safety rules

1. **No live trading control.**
   - Live account start/stop/order controls remain blocked.
   - Live runtime can be read-only if visible from NinjaTrader, but no API endpoint may enable/disable live strategies or submit/cancel orders.
2. **Paper/sim only for control.**
   - If command control is implemented, it must be limited to `Sim101` / paper accounts and must require explicit operator confirmation in UI.
3. **B1 ShortOnly trading logic and locked params must not change.**
4. **All paper metrics must be quantity-aware:**
   `adjusted_pnl = gross_pnl - RoundTurnCommission * quantity`.
5. **Live remains forbidden until paper review passes.**

## Required deliverables

### 1. NinjaTrader runtime telemetry exporter

Implement a NinjaTrader-side exporter, preferably as an AddOn or a safe strategy helper, that writes heartbeat/runtime state to NT-Analyzer.

Minimum output files under:

`NT-Analyzer/data/runtime/`

Required files:
- `heartbeat.json`
- `strategies.json`
- `executions.jsonl`
- `orders.jsonl`
- `positions.json`
- `errors.jsonl`

Required fields for `strategies.json`:
- `timestamp_utc`
- `account_name`
- `account_mode`: `paper`, `live`, `playback`, or `unknown`
- `strategy_id`
- `strategy_class`
- `strategy_name`
- `instrument`
- `contract_month`
- `enabled`
- `state`
- `connection_status`
- `position_market_position`
- `position_qty`
- `avg_price`
- `unrealized_pnl`
- `realized_pnl`
- `session_trades_count`
- `params`
- `params_hash`

For `NTAMicroVwapRiskPilot` B1 ShortOnly, verify the runtime params against locked params:
- `EnableLong=false`
- `EnableShort=true`
- `TradeStartTime=635`
- `TradeEndTime=700`
- `MinStopTicks=12`
- `MaxStopTicks=12`
- `RewardRiskRatio=3.5`
- `RiskPerTradePct=2.0`
- `UserMaxContracts=5`
- `RoundTurnCommission=1.90`
- `SlippageTicks=1`

If any mismatch exists, UI must show `PARAM_MISMATCH` and block paper state advancement.

### 2. NT-Analyzer backend runtime API

Extend `app/ops.py` and `app/server.py` with read-only runtime endpoints:

- `GET /api/ops/runtime/heartbeat`
- `GET /api/ops/runtime/strategies`
- `GET /api/ops/runtime/strategies/{id}`
- `GET /api/ops/runtime/executions?strategy_id=...`
- `GET /api/ops/runtime/orders?strategy_id=...`
- `GET /api/ops/runtime/positions`
- `GET /api/ops/runtime/health`

Backend must merge:
- registry strategy (`data/ops/registry.json`)
- paper state (`data/ops/state.json`)
- Ninja runtime telemetry (`data/runtime/*.json*`)
- paper journal (`PAPER_B1_SHORTONLY_DAILY_JOURNAL.csv`)

Result should expose:
- `registry_status`
- `paper_state`
- `runtime_detected`
- `runtime_enabled`
- `account_name`
- `account_mode`
- `params_ok`
- `runtime_warnings`
- `runtime_errors`
- latest executions/fills
- today quantity-aware gross/adjusted PnL

### 3. UI changes

Update `app/static/ops.html` and `app/static/ops.js`:

Strategy cards must show:
- Registry state
- Runtime state from NinjaTrader
- Account name and account mode
- Enabled/disabled status
- Runtime heartbeat freshness
- Params check: `LOCKED PARAMS OK` or `PARAM MISMATCH`
- Today gross/adjusted PnL from real paper executions
- Current position qty / side / avg price
- Orders/executions tab from runtime files

If NinjaTrader has a strategy enabled manually, it must appear clearly as:

`Runtime detected: enabled on Sim101`

If registry state says `paper_ready` but runtime says enabled, UI should show:

`Runtime enabled but not confirmed in Control Center`

and provide:
- `Confirm Runtime Started` button for paper/sim only.

If runtime says disabled but registry says `paper_running`, UI should show:

`Runtime stopped outside Control Center`

and provide:
- `Confirm Runtime Stopped` button.

### 4. Paper journal auto-fill

Use `executions.jsonl` to auto-compute and append/update daily journal rows:
- `date_pt`
- `trades_count`
- `total_qty`
- `gross_pnl`
- `commission_estimated = 1.90 * total_qty`
- `adjusted_pnl`
- `cumulative_adjusted_pnl`
- `current_drawdown`
- `daily_win_count`
- `daily_loss_count`
- `median_slippage_ticks`
- `max_slippage_ticks`
- `stop_hit_count`
- `target_hit_count`
- `notes`

Manual journal edits must remain possible.

### 5. Risk enforcement UI

Paper UI must detect:
- daily adjusted PnL <= -200
- weekly adjusted PnL <= -400
- trailing DD <= -300
- 4 consecutive losing paper days
- param mismatch
- live account detected

For paper/sim:
- UI may show a paper stop instruction.
- If command control is implemented, stop command must be paper/sim only and must require operator confirmation.

For live:
- read-only only, no control.

### 6. Tests

Add tests covering:
- runtime files missing -> UI/backend shows `runtime_detected=false`, no crash
- stale heartbeat -> warning
- enabled Sim101 B1 ShortOnly with correct params -> detected as paper runtime OK
- enabled Sim101 B1 ShortOnly with wrong params -> `PARAM_MISMATCH`
- enabled live account -> `LIVE_LOCKED`, no start/stop controls
- executions.jsonl -> quantity-aware daily journal metrics
- runtime enabled but registry paper_ready -> mismatch warning
- runtime disabled but registry paper_running -> mismatch warning
- rejected strategies cannot be runtime-confirmed
- all existing Phase 16 tests still pass

### 7. Acceptance criteria

Phase 17 is complete only when:

1. Start NinjaTrader, enable B1 ShortOnly on `Sim101`.
2. Open `http://127.0.0.1:8765/ui/ops.html`.
3. UI shows B1 ShortOnly as runtime-detected and enabled on Sim101.
4. UI confirms locked params OK.
5. Runtime executions appear in the Orders/Executions tab.
6. Daily Journal can auto-fill from runtime executions.
7. If strategy is disabled manually in NinjaTrader, UI detects that after heartbeat refresh.
8. Live account is visible as read-only but impossible to control.
9. All backend tests pass.
10. No trading logic changed in `NTAMicroVwapRiskPilot`.

## Important note

Do not treat Phase 16 manual workflow as sufficient. The user expects the Control Center to reflect the real NinjaTrader runtime state. If the NinjaTrader bridge cannot expose runtime strategy state, document the blocker precisely and implement the file protocol / AddOn changes needed to expose it.
