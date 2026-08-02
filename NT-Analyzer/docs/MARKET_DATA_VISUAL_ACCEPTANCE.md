# Market-data visual acceptance checklist

Date: 2026-07-16  
Status: **ACCEPTANCE PENDING**

Screenshots that only show “charts loaded from NinjaTrader” are **not** acceptance.

## Per-chart chrome (always visible, compact)

- `LIVE` / `DEGRADED` / `STALE` / `RECOVERING` / `OFFLINE`
- chart source (provider)
- exact contract
- `WS` or `HTTP`
- last update age
- latency (when known)
- gap indicator when recovering

## Owner / debug diagnostics (owner-only)

```text
requested_symbol
canonical_symbol
raw_provider_symbol
exact_contract
timeframe
session_template
provider
provider_subscription_id
cache_key
cache_level (L1/L2/L3/MISS)
cache_hit
series_hash
source_epoch
first_bar_time
last_bar_time
last_price
transport
ws_state
subscriber_count
last_event_age
e2e_latency_ms
```

## Global Market Data Diagnostics panel (owner)

- provider streams
- unique contracts
- connected users
- WebSocket clients
- chart panels
- deduplication ratio
- Redis hit rate
- PostgreSQL query rate
- messages/sec, bytes/sec
- queue depth, dropped, reconnects
- stale charts, source switches

## Visual similarity rules

| Pair | Expected look | Required proof |
|---|---|---|
| RTY vs M2K | nearly identical shape (same Russell index) | **different** cache_key + series identity |
| MES vs MNQ vs MYM | often correlated | **different** series_hash; different prices |

Automated test must load five instruments and assert no accidental shared series.

## Deploy acceptance steps

1. Backup current `NTAnalyzerBridge.dll`
2. Install Release build
3. Restart NinjaTrader
4. Confirm IPC metrics / queue
5. Confirm UI shows `WS` when connected; HTTP slowed
6. Open multi-chart grid; verify diagnostics differ per symbol
7. Stop Bridge → status not sticky green LIVE
8. Restore Bridge → recover
9. Preserve Telegram PNG, snapshots, draw, LTTB, Practice, layouts

## Evidence required before ACCEPTANCE PASSED

- UI screenshot with LIVE/DEGRADED/STALE + WS/HTTP + age
- diagnostics dump JSON
- series_hash matrix for RTY/M2K/MES/MNQ/MYM/MGC
- Bridge deploy note (backup path + timestamp)
