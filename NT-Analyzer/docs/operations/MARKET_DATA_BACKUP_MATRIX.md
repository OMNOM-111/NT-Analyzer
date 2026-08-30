# Market-data runtime and backup matrix

Status on 2026-08-11: **Development baseline AVAILABLE; final design/UI acceptance pending.**

TopstepX is the primary independent read-only source for chart history and realtime data. A fresh NinjaTrader Connector remains the next runtime source and the execution path. Other credentialed live providers may participate only when their entitlement and parity gates pass. Cache is history/offline continuity and is never labelled live.

Production/Canary promotion remains a separate owner gate. This Development statement does not claim a Production deployment or licensed-backup acceptance.

## Capability vocabulary

`implementation_state`: `NOT_IMPLEMENTED` | `ADAPTER_READY` | `TESTED_WITH_RECORDED_DATA` | `CONNECTED`

`runtime_state`: `DISABLED` | `CONNECTING` | `LIVE` | `DEGRADED` | `STALE` | `OFFLINE` | `AUTH_FAILED` | `ENTITLEMENT_MISSING` | `RATE_LIMITED` | `ERROR`

## Current runtime order

1. TopstepX / ProjectX Gateway — primary independent read-only chart history and realtime.
2. Fresh NinjaTrader Connector — chart fallback when its heartbeat is current; the execution authority remains NinjaTrader.
3. Other explicitly configured, credentialed live adapters that passed their safety and parity gates.
4. Canonical cache — honest history/offline continuity with `live=false`.

## Matrix

| Role | Provider | implementation_state | Development runtime | Coverage | History/realtime | Trading authority | Automatic chart eligibility | Important boundary |
|---|---|---|---|---|---|---|---|---|
| Primary read-only charts | TopstepX / ProjectX Gateway | CONNECTED | LIVE when the authenticated shared adapter is healthy | Entitled futures contracts | History + realtime | No order routing through the chart data path | Yes, first | One process-level authenticated adapter fans out to UI clients; consumer count must not create extra loginKey or SignalR sessions |
| Runtime fallback + execution | NinjaTrader Bridge IPC | ADAPTER_READY | LIVE only while the Connector heartbeat is fresh; OFFLINE when NinjaTrader is stopped | Futures available through NinjaTrader | History + realtime when connected | **Yes** | Yes, after TopstepX | Stale heartbeat is never treated as live |
| Independent live backup | Databento Live | ADAPTER_READY | ENTITLEMENT_MISSING until configured | Exact entitled CME instruments | Live + historical/replay | No | Only after key, entitlement and shadow-parity PASS | No credentials or entitlement are committed to Git |
| Candidate backup | CME WebSocket API | NOT_IMPLEMENTED | DISABLED | CME | Vendor-dependent | No | No | Adapter, auth, symbol map and fixtures are not complete |
| Candidate backup | dxFeed, Rithmic or CQG | NOT_IMPLEMENTED | DISABLED | Vendor-dependent | Vendor-dependent | No | No | Provider selection and implementation are still required |
| Offline continuity | Canonical bar cache | ADAPTER_READY | OFFLINE/cache | Previously received series | Historical only | No | No live eligibility | Must report `live=false`; never masquerades as realtime |
| Delayed only | Yahoo Chart | ADAPTER_READY | DELAYED_OR_UNVERIFIED | Root-future proxies | Limited/delayed | No | **No** | Never an automatic live-production failover |
| Tests only | RecordedProvider / FaultInjectionProvider | TESTED_WITH_RECORDED_DATA | DISABLED | Fixtures | Replay/chaos | No | **No** | Never `REALTIME_PRODUCTION` |

## Correct offline mode

If TopstepX is unavailable, NinjaTrader is off, and no eligible credentialed live backup is healthy:

1. Declare live sources unavailable promptly.
2. Do not call delayed HTTP providers per chart panel.
3. Serve the last valid canonical bars when available.
4. Mark the payload `status=offline`, `live=false`, `strategy_blocked`, `execution_blocked` as applicable.
5. Show the global/per-chart offline state instead of a false live price.
