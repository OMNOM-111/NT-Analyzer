# 06. Market Data, Trading and Connector

- Context Pack document: 06_MARKET_DATA_TRADING_CONNECTOR.md
- Last verified UTC: 2026-08-14T06:20:00Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
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
| Read-only charts | `PARTIAL` | TopstepX history + realtime operate with NinjaTrader OFF in DEV. Repository now uses the same order on Canary/Production; live `1fae1f39` still stubs/skips TopstepX on server environments |
| Connector fallback | `PARTIAL` | fresh NinjaTrader Connector bars are a current fallback for charts when TopstepX is unavailable |
| Simulation / paper / demo runtime control | `PARTIAL` | safe runtime commands exist for paper/demo/playback contours |
| Account-mode execution gates | `PARTIAL` | Simulation vs real/live comes from the connected NinjaTrader account; app-side execution on that account is allowed or blocked by permissions, safety gates, release state and account capabilities |
| Market-data entitlement / licensed-provider parity | `EXTERNAL BLOCKED` | DEV owner feed and fanout are accepted; authenticated Canary/Production provider parity still needs real server-environment user authentication |
| SignalR / session / freshness rules | `DONE` | provider health, quote heartbeat, cooldowns, freshness and provenance are part of the charting contract. A fresh quote heartbeat keeps the marker live even when price itself is unchanged |

## Stable baseline external GPT should assume

- Charting is primarily a read-only market-data problem, not an execution
  authorization problem.
- Trading mode comes from the connected NinjaTrader account/runtime state.
- The accepted 2026-08-13 DEV baseline kept TopstepX auth/session, SignalR,
  rollover and backend cache/failover architecture unchanged. The scoped UI
  fix preserves a fresh WebSocket bar/marker across health/history refreshes.
- Live public API identity is `1fae1f39` on Canary and Production. The
  repository Documents/Charts follow-up is not that artifact. No orders were
  placed during this record.
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
- A connected live account mode does not by itself grant execution authority;
  live-account actions stay blocked unless the current environment, account
  capability, safety gate and release gate all allow them.

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
- [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md)
- [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md)
- [../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md](../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md)

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T06:20:00Z | Grok 4.6 через Cursor по запросу owner | Recorded repository TopstepX-first server chart order; live 1fae1f39 still stubs/skips TopstepX.
-->
