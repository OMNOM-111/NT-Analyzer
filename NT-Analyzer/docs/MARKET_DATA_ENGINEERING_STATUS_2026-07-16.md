# Market-data resilience — status

Date: 2026-07-16 (America/Los_Angeles)  
Branch: `codex/stratforge-release-20260716`

## Status (authoritative)

```text
CORE IMPLEMENTATION COMPLETED
DEPLOYMENT, VISUAL VERIFICATION, CACHE ARCHITECTURE WIRING,
100-USER LOAD TEST AND ACCEPTANCE TESTING PENDING
PRODUCTION FAILOVER BLOCKED
```

**Do not use `ENGINEERING COMPLETE`.** Historical NT chart screenshots are not acceptance.

## What landed this revision

### Documentation (ARCHITECTURE DOCUMENTED)

- `docs/DATA_PLATFORM_ARCHITECTURE.md`
- `docs/MARKET_DATA_CACHE_AND_FANOUT.md`
- `docs/MARKET_DATA_100_USER_LOAD_PLAN.md`
- `docs/MARKET_DATA_VISUAL_ACCEPTANCE.md`
- `docs/POSTGRESQL_REDIS_MIGRATION_PLAN.md`
- `docs/MARKET_DATA_PRODUCTION_RUNBOOK.md`
- Updated `STRATFORGE_ГЕНЕРАЛЬНЫЙ_ПЛАН.md` addendum
- Updated this status + resilience plan

### Code

| Area | Change |
|---|---|
| Browser WS | same-origin `/ws/market-data` on main backend (`market_data_ws_http.py`) |
| Desktop client | `wss?://{location.host}/ws/market-data`; exponential backoff; HTTP poll slows to 5s when WS healthy |
| Chart chrome | `LIVE/DEGRADED/STALE · provider · contract · WS/HTTP · age · #series_hash` |
| Fan-in | `SubscriptionRegistry` refcount per `(provider, exact_contract, channel)` |
| Cache keys | `market_data_cache_keys.py` — RTY/M2K/MES/MNQ/MYM/MGC keys all distinct |
| Data platform | `data_platform.py` — Cache/Lock/EventBus/Repository; memory default; Redis/PG optional |
| Diagnostics API | `GET /api/ops/runtime/market-data/diagnostics` |
| Per-series diagnostics | attached on bars payload |

### Tests

`test_market_data_cache_fanout.py` + prior market-data suites — green in this session.

### Bridge deploy attempt

- Backup created: `NTAnalyzerBridge.dll.bak-20260716-212004`
- **Copy failed**: file locked by running NinjaTrader (PID present)
- Release build size 187904 vs installed 187392 → **DEPLOYED = pending NT restart + copy**

## Still pending for ACCEPTANCE

1. Restart NinjaTrader → install new DLL → verify IPC metrics file
2. Restart backend with new `/ws/market-data` route
3. Hard-refresh Desktop → confirm title shows `WS` / `LIVE` / age / hash (not only `NinjaTrader`)
4. Owner diagnostics panel UI (API exists; dedicated panel chrome still thin)
5. Redis + PostgreSQL production instances + `NTA_REQUIRE_*=1`
6. 100-user load report
7. Live Databento entitlement → shadow parity → PRODUCTION FAILOVER

## External blockers

1. Live Databento / licensed external key  
2. Multi-user redistribution entitlement  
3. Production Redis + PostgreSQL provisioning  
4. NinjaTrader must be stopped/restarted to unlock DLL replace  

## Fallbacks retained

`market_bars.json`, `/bars/batch`, Telegram PNG, snapshots, draw/open/clear, LTTB, layouts, Practice, Desktop, workspace isolation, owner auth, Cloudflare, Mini App.
