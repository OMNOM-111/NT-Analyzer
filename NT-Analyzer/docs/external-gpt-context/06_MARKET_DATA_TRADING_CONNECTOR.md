# 06. Market Data, Trading and Connector

- Context Pack document: 06_MARKET_DATA_TRADING_CONNECTOR.md
- Last verified UTC: 2026-08-13T02:25:57Z
- Verified against Git SHA: c4711ae3f876966f6bedcba8fc3b4ad9c309c836
- Scope: NinjaTrader authority, Connector protocol, market-data priorities and trading safety gates
- Status: DONE

## Non-negotiable current rules

1. NinjaTrader is the only execution path and the source of truth for fills,
   trades, metrics and runtime strategy state.
2. TopstepX is the primary independent read-only chart source when configured.
3. Current runtime failover order for charts is: TopstepX -> fresh NinjaTrader
   Connector runtime -> other allowed credentialed provider -> offline/cache.
4. Synthetic candles are not created.
5. A delayed/history feed must never be labeled live.
6. An external chart feed never authorizes orders.

## Current status matrix

| Area | Status | Current fact |
| --- | --- | --- |
| Connector protocol v1 | `PARTIAL` | pair/enroll/challenge/hello/heartbeat/market-data/commands protocol is implemented with device-owned P-256 keys and bounded capabilities |
| Read-only charts | `DONE` | TopstepX history + realtime can operate with NinjaTrader OFF and feed multiple browser clients |
| Connector fallback | `PARTIAL` | fresh NinjaTrader Connector bars are a current fallback for charts when TopstepX is unavailable |
| Simulation / paper / demo runtime control | `PARTIAL` | safe runtime commands exist for paper/demo/playback contours |
| Real-money automation | `EXTERNAL BLOCKED` | live order execution remains release-gated and owner/regulatory-gated |
| Market-data entitlement / licensed-provider parity | `PARTIAL` | provider slots and contracts exist; full licensed-provider acceptance is still pending |
| SignalR / session / freshness rules | `DONE` | provider health, cooldowns, freshness and provenance are part of the charting contract |

## Stable baseline external GPT should assume

- Charting is primarily a read-only market-data problem, not an execution
  authorization problem.
- Trading mode comes from the connected NinjaTrader account/runtime state.
- Production Connector should work only via outbound HTTPS to the canonical
  origin; it does not open an inbound port for the server.
- Market-data payloads are bounded and capability-scoped; workspace or account
  identity is not trusted from client payload fields.

## Read-only vs execution boundaries

| Boundary | What it can do | What it cannot do |
| --- | --- | --- |
| TopstepX / other chart feeds | supply chart/history/realtime bars | route or authorize orders |
| Connector market-data session | deliver authenticated bounded OHLCV batches | infer new permissions beyond its session capabilities |
| NinjaTrader runtime | compile, backtest, manage actual runtime state and order execution | bypass product-level release/auth gates |

## Safety gates

- Connector commands are workspace-bound, installation-bound and idempotent.
- Delivery leases prevent accidental duplicate execution after reconnect.
- Default Production posture is telemetry/accounts read plus optional paper
  commands, not arbitrary code execution.
- Live capability should be treated as blocked until explicitly released.

## Areas that must not be casually modified

- `app/connector_protocol.py`
- `app/market_data_failover.py`
- `app/market_data_live_adapters.py`
- `app/market_data_ws_http.py`
- [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md)
- [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md)

## Canonical evidence

- [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md)
- [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md)
- [../../README.md](../../README.md)
- `app/connector_protocol.py`
- `app/market_data_failover.py`
- `app/market_data_live_adapters.py`
- `app/market_data_ws_http.py`