# Market-data backup matrix (2026-07-16)

Status: **PRODUCTION BLOCKED** — no independent live backup is connected.

Do **not** claim “four backups work” until each row is CONNECTED and Scenario C passes with that provider.

## Capability vocabulary

`implementation_state`: `NOT_IMPLEMENTED` | `ADAPTER_READY` | `TESTED_WITH_RECORDED_DATA` | `CONNECTED`

`runtime_state`: `DISABLED` | `CONNECTING` | `LIVE` | `DEGRADED` | `STALE` | `OFFLINE` | `AUTH_FAILED` | `ENTITLEMENT_MISSING` | `RATE_LIMITED` | `ERROR`

## Matrix

| Role | Provider | implementation_state | runtime_state | Credentials | Entitlement | Coverage | Live/Delayed | Trades | Bid/Ask | Depth | Historical | Reconnect | Replay | Licensing / cost (est.) | Blockers |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Primary | NinjaTrader Bridge IPC | ADAPTER_READY | OFFLINE when NT stopped; LIVE when HB fresh | Local Bridge DLL | NT data feed | Futures via NT | Live (when NT on) | Yes | Via NT | Limited | Via NT history | Bridge reconnect | No | NT license | DLL must stay deployed; NT process required |
| Independent live A | Databento Live | ADAPTER_READY (`market_data_live_adapters.DatabentoLiveAdapter` + supervisor) | ENTITLEMENT_MISSING until key | `NTA_DATABENTO_API_KEY` | GLBX.MDP3 live | CME micros exact (`MNQU6`…) | Live | Yes | via tbbo | Optional | hist + 24h replay | Required | Yes | Commercial Databento | **No API key / pip databento**; auto-failover blocked until shadow parity |
| Independent live B | CME WebSocket API | NOT_IMPLEMENTED → interface scaffold only | DISABLED | CME credentials | CME MDP / WebSocket entitlement | CME | Live | Required | Required | Optional | Separate | Required | Required | CME commercial | Adapter, auth, symbol map, fixtures missing |
| Independent live C | dxFeed **or** Rithmic **or** CQG | NOT_IMPLEMENTED | DISABLED | Vendor credentials | Vendor entitlement | Vendor coverage | Live | Required | Required | Optional | Vendor-dependent | Required | Required | Vendor commercial | Choose one; full adapter + fixtures missing |
| Emergency offline | PostgreSQL + Redis canonical bars | Foundation / dual-write design | Not default production path | Local/ops | N/A | Cached series only | **Not live** | Cached | Cached | No | Yes | N/A | Cache replay | Ops infra | Must never be labeled LIVE |
| Delayed only | Yahoo Chart | ADAPTER_READY | STALE when used | None (public) | None | Root futures proxies | **DELAYED_OR_UNVERIFIED** | Approx | Estimated | No | Limited | N/A | No | Public ToS | **Never** automatic production live failover |
| Test only | RecordedProvider | TESTED_WITH_RECORDED_DATA | DISABLED | Fixture files | N/A | Fixture symbols | Not live | Replay | Replay | No | Yes | N/A | Yes | N/A | No `REALTIME_PRODUCTION` |
| Test only | FaultInjectionProvider | TESTED_WITH_RECORDED_DATA | DISABLED | N/A | N/A | Wrapped stream | Not live | Chaos | Chaos | No | Via inner | N/A | Yes | N/A | No `REALTIME_PRODUCTION` |

## Current automatic failover eligibility

| Provider | Eligible for automatic production live failover? |
|---|---|
| NinjaTrader | Primary only |
| Databento | Only after key + entitlement + shadow parity PASS |
| CME / dxFeed / Rithmic / CQG | No — not connected |
| Yahoo | **No** |
| Recorded / FaultInjection | **No** |
| PG/Redis cache | **No** (OFFLINE history only) |

## Correct offline mode (no external live provider)

When NinjaTrader is off and Databento is not configured:

1. Declare primary OFFLINE quickly (heartbeat / process check).
2. Do **not** call Yahoo (or any delayed HTTP) per chart panel.
3. Serve last valid bars from runtime/historical cache immediately.
4. Mark payload `status=offline`, `live=false`, `strategy_blocked`, `execution_blocked`.
5. UI: global OFFLINE banner + per-chart OFFLINE + muted price marker.
