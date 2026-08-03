# Market-data production runbook (draft)

Date: 2026-07-16

## Status gates

| Gate | Meaning |
|---|---|
| CORE IMPLEMENTATION COMPLETED | code + unit tests |
| DEPLOYED | Bridge DLL installed + backend restarted |
| ACCEPTANCE PASSED | visual checklist signed |
| 100-USER LOAD PASSED | load report |
| PRODUCTION FAILOVER COMPLETE | licensed live external + NT stop |

## Deploy Bridge

1. Stop chart load if needed (optional).
2. Backup `%USERPROFILE%\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.dll`.
3. Copy `bridge/bin/Release/NTAnalyzerBridge.dll` over Custom.
4. Restart NinjaTrader (AddOn reload).
5. Confirm `data/runtime/market_data_ipc_bridge_metrics.json` updates.
6. Confirm backend log: `market-data IPC listening on 127.0.0.1:18765`.

## Browser WS

- URL: same-origin `ws(s)://{host}/ws/market-data`
- Never point browsers at Bridge `127.0.0.1:18766`.
- Cloudflare Tunnel must forward WebSocket upgrades for `/ws/market-data`.

## Rollback

1. Restore `.bak-*` DLL.
2. Restart NinjaTrader.
3. Set `NTA_DATA_PLATFORM=memory` if Redis/PG misbehave.
4. HTTP `/bars/batch` + `market_bars.json` remain emergency fallbacks.

## Diagnostics

- `GET /api/ops/runtime/market-data/diagnostics`
- Per-chart title: `LIVE|DEGRADED|STALE · provider · contract · WS|HTTP · age · #hash`
