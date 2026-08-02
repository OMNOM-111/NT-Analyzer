# Market-data cache and fan-out

Date: 2026-07-16

## Goal

Serve up to `100 users × 64 panels = 6400` chart panels from a small number of
upstream contract streams, without 350 ms full-series HTTP polling.

## Cache key contract

Raw/market keys **must not** collide across instruments.

Minimum fields:

```text
schema_version
provider
exchange
exact_contract
channel
timeframe          # for assembled bars only
session_template
adjustment_mode
bar_engine_version
source_epoch / data_revision
```

Example:

```text
md:v1:global:-:-:-:ninjatrader:CME:MNQ 09-26:trades:5m:cme_equity_eth:raw:be1:epoch3
```

### Separated namespaces

| Namespace | Contents |
|---|---|
| `md:*` | global licensed market-data (quotes/bars) |
| `ws:*` | workspace overlays (layouts, drawings) |
| `acct:*` | account / positions |
| `strat:*` | strategies |
| `perm:*` | permissions / sessions |

**Never** put tenant overlays into `md:*`.

### Collision test set

RTY, M2K, MES, MNQ, MYM, MGC — each must produce a **distinct** cache key and
(except expected RTY≈M2K correlation) distinct `series_hash`.

## Fan-in subscription registry

Key: `(provider, exact_contract, channel)`

- first browser client → create upstream + refcount=1
- next clients → join existing, refcount++
- window close → refcount--
- refcount=0 → cooldown, then unsubscribe upstream

Timeframes are **not** upstream keys; they are derived by `CanonicalBarEngine`.

## L1 / L2 / L3 behaviour

1. Live tick → L1 update → publish EventBus → optional L2 quote hash
2. Bar close/correction → L1 + L2 + async batch write L3
3. History miss → single-flight LockProvider → provider/L3 → fill L2 → return

## Reconnect

- Redis Streams (capped) hold short replay cursor
- client sends `last_cursor` / `source_epoch`
- server sends missed closed bars + current provisional bar
- **not** a full series re-download

## Backpressure (slow clients)

Per-WebSocket bounded outbound queue:

- closed bars: never drop
- corrections / source changes: never drop
- provisional candle updates: **coalesce** to latest
- overflow → drop oldest coalescable updates, metric `ws_coalesced`

## HTTP remaining uses

Allowed:

- initial series
- recovery / cursor catch-up
- health check
- emergency fallback when WS down

Forbidden when WS healthy:

- full series every 350 ms
- per-panel provider fetch
