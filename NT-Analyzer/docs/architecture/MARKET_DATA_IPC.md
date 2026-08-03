# Market-data IPC (Bridge ↔ backend)

Localhost-only authenticated event stream. Replaces neither `market_bars.json`
nor `/bars/batch` — those remain fallbacks until Phase 7 cutover tests pass.

## Transports

| Transport | Framing | Default |
|---|---|---|
| TCP `127.0.0.1:18765` | 4-byte big-endian length + UTF-8 JSON | **yes** |
| Named Pipe `\\.\pipe\stratforge-market-data` | same frames | Bridge-selectable |
| WebSocket `ws://127.0.0.1:18765/bridge/market-events` | JSON text frames | Bridge-selectable |

Benchmark: `python tools/ipc_transport_benchmark.py`

## Auth

Token file (gitignored runtime): `data/runtime/market_data_ipc_token.json`

Hello frame **must** include:

- `type: hello`
- `protocol_version: 1`
- `auth_token`
- `connection_id`
- `transport`

Unauthenticated or wrong-token connects are rejected and audited.

## Metrics

- Backend: `GET /api/ops/runtime/market-data/ipc`
- Bridge writer: `data/runtime/market_data_ipc_bridge_metrics.json`
- Audit: `data/runtime/market_data_ipc_audit.jsonl`

## Callback rule (NinjaTrader)

`MarketData` callback may only: read Last/Bid/Ask/Volume, normalize, timestamp,
enqueue to bounded queue, return. File snapshot writes stay on the timer/writer path.
