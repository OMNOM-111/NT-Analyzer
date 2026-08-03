# PostgreSQL + Redis migration plan

Date: 2026-07-16
Status: **ARCHITECTURE DOCUMENTED** — phased migration, no big-bang

## Principle

Do not mechanically replace every store. Introduce interfaces, then migrate
components that benefit first (market-data cache/fan-out, then durable bars).

## Phase M0 — Interfaces (this cycle)

Modules under `app/data_platform/`:

- `cache.py` — `Cache` protocol + `MemoryCache`
- `locks.py` — `LockProvider` + `ThreadLockProvider`
- `event_bus.py` — `EventBus` + `LocalEventBus`
- `repository.py` — `Repository` protocol
- `redis_adapters.py` — optional Redis (graceful if package/env missing)
- `postgres_adapters.py` — optional PostgreSQL (graceful if missing)
- `config.py` — `NTA_DATA_PLATFORM=memory|redis|postgres`

Default local: memory (+ existing SQLite/files).
Production target: `postgres` + `redis` via env.

## Phase M1 — Market-data L2

- latest quote hash
- current bar hash
- series cache with TTL
- pub/sub channel `md:live:{exact_contract}`
- capped stream `md:stream:{exact_contract}` for reconnect
- lock `md:lock:history:{cache_key}` against stampede

## Phase M2 — Market-data L3

- tables: instruments, contracts, bars_canonical (partitioned by time),
  gaps, provider_switches, subscriptions_meta, audit
- async batch writers from bar-close path
- retention job

TimescaleDB: optional after benchmark; not a hard dependency yet.

## Phase M3 — App state migration

Users/workspaces/entitlements/layouts already have durable paths — migrate
deliberately behind Repository interfaces without breaking DPAPI/secure_store.

## Env flags

```text
NTA_DATA_PLATFORM=memory          # local default
NTA_REDIS_URL=redis://127.0.0.1:6379/0
NTA_DATABASE_URL=postgresql://...
NTA_REQUIRE_REDIS=0               # set 1 in production multi-user
NTA_REQUIRE_POSTGRES=0
```

## Health

- `GET /api/ops/runtime/market-data/diagnostics` includes cache backend,
  redis_ok, postgres_ok, hit rates, lock stats.

## Rollback

- set `NTA_DATA_PLATFORM=memory`
- existing `market_bars.json` + `/bars/batch` remain emergency fallback
