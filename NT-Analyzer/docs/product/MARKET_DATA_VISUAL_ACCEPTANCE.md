# Market-data visual acceptance checklist

Date: 2026-08-11
Status: **FUNCTIONAL BASELINE ACCEPTED · FINAL DESIGN/UI ACCEPTANCE PENDING**

The owner-accepted functional baseline is protected: TopstepX supplies real
history + realtime with NinjaTrader OFF; live price/candles update; multiple
browser clients may view charts concurrently while the TopstepX web platform
remains usable. This baseline is not a refactoring target without a reproducible
defect.

## Canonical current data path

- TopstepX is the primary independent read-only chart source (history + realtime).
- Runtime fallback: TopstepX → fresh NinjaTrader Connector → another authorized
  credentialed provider → explicit OFFLINE/cache.
- NinjaTrader is the only execution path and source of truth for trades/runtime;
  external chart bars never authorize orders.
- One shared TopstepX auth/session and SignalR transport fans out to browser
  clients; extra layouts/clients must not create repeated `loginKey` calls or
  redundant upstream SignalR sessions.

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

## Development closeout smoke evidence

Verified on 2026-08-11 at `127.0.0.1:8765`, with NinjaTrader processes absent:

- two parallel HTTP clients each loaded a 16-chart layout across `1m`, `5m`,
  `15m` and `1h`; after warm-up both received 16/16 `external_live` TopstepX
  series with at least 300 bars each;
- repeated samples changed the current 1m candle/price for MNQ, MES and M2K;
- two simultaneous UI clients opened the saved multi-chart desktop: every
  visible chart had a canvas and `LIVE · DATA · topstepx · WS`; offline banner
  was absent and browser console errors were zero;
- the process kept one shared adapter, made zero new `loginKey` calls and had
  exactly one active upstream SignalR transport. Automatic reconnects did not
  create per-client or parallel upstream sessions;
- the already accepted concurrent TopstepX web-platform baseline was not
  disturbed: this closeout did not log it out, change credentials or alter its
  auth/session implementation.

This is functional smoke evidence, not the owner's final design/UI acceptance.

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

## Remaining final design/UI acceptance

- Owner reviews final spacing, hierarchy, chart chrome and document-journal design.
- No merge, Canary/Production promotion or deployment occurs before that separate
  acceptance and approval.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-11T09:03:34Z | GPT-5.5 через Codex по запросу owner | Зафиксирован принятый baseline и добавлено фактическое DEV smoke-evidence: multi-client TopstepX live, NinjaTrader OFF, одна upstream session, без нового loginKey; финальный design acceptance остаётся owner gate.
-->
