# Data Platform Architecture — StratForge

Date: 2026-07-16  
Status: **ARCHITECTURE DOCUMENTED** (implementation in progress)

## Platform standard

### A. Production / multi-user

| Layer | Role |
|---|---|
| **PostgreSQL** | Durable system of record |
| **Redis** | Shared runtime cache, fan-out, locks, sessions, rate limits |
| SQLite / process-only cache | **Not** production multi-user storage |

### B. Local development / emergency offline

SQLite + in-memory fallback allowed only for:

- local development;
- emergency offline mode;
- backward compatibility with existing owner single-node setups.

Migration is **incremental** via interfaces — no big-bang rewrite of every store.

## Interfaces (mandatory)

```text
Repository[T]     — durable read/write (PG in prod, SQLite locally)
Cache             — get/set/invalidate with TTL (Redis in prod, memory locally)
EventBus          — pub/sub for live fan-out (Redis Pub/Sub+Streams in prod)
LockProvider      — distributed locks (Redis in prod, threading.Lock locally)
```

Components must depend on interfaces, not on concrete drivers.

## Data planes (unchanged rule)

| Plane | May drive chart | May drive execution |
|---|---|---|
| display | yes | **no** |
| analytics | yes | no |
| strategy | policy-gated | no auto from chart |
| execution | no from chart | yes (NT / broker only) |
| history_replay | tests/replay | no |

Chart source ≠ strategy source ≠ execution source.

## Two transport planes

```text
NinjaTrader Bridge → backend
  localhost-only secured IPC (127.0.0.1 TCP / Named Pipe / optional WS)
  auth token, protocol_version, heartbeat, bounded queue

Browser → backend
  same-origin ws/wss://{host}/ws/market-data
  via main HTTP server + reverse proxy / Cloudflare Tunnel
  NEVER direct to Bridge or 127.0.0.1 from remote browsers
```

## Market-data fan-in / fan-out

```text
Provider (NT / Databento / …)
        │  ONE subscription per (provider, exact_contract, channel)
        ▼
Canonical MarketData Engine + CanonicalBarEngine (all TFs)
        │
   ┌────┴────┐
   ▼         ▼
  L1 RAM    L2 Redis
   │         │
   └────┬────┘
        ▼
   WS gateways (coalesced latest-value per client)
        ▼
   N authenticated browsers
```

Upstream subscription count = unique contracts×channels, **not** users×panels.

## Three-level cache

| Level | Store | Contents |
|---|---|---|
| L1 | process memory | ring buffer, latest quotes, current bars |
| L2 | Redis | shared quotes/bars, series cache, pub/sub, streams replay, locks |
| L3 | PostgreSQL | finalized bars, instruments, gaps, audit, entitlements, layouts |

Redis is **not** permanent SoR. After Redis flush, rebuild from PostgreSQL / provider history.

## Status vocabulary (strict)

| Status | Meaning |
|---|---|
| ARCHITECTURE DOCUMENTED | docs only |
| CORE IMPLEMENTATION COMPLETED | code + unit tests; not deployed/accepted |
| IMPLEMENTATION COMPLETE | code + automated tests finished for a scope |
| DEPLOYED | build installed in running NT/backend |
| ACCEPTANCE PASSED | manual checks on real UI |
| 100-USER LOAD PASSED | load report attached |
| PRODUCTION FAILOVER COMPLETE | licensed live external + NT stop test |

Do **not** use ENGINEERING COMPLETE until deployed and user-verified.
