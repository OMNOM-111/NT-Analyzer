# Market-data resilience — status

Date: 2026-07-16 (America/Los_Angeles)  
Branch: `codex/stratforge-release-20260716`

## Status (authoritative)

```text
IMPLEMENTATION PARTIAL (AUTOMATED GATES PASS)
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

### Bridge deployment

- 2026-07-17: Release build completed with 0 warnings / 0 errors.
- Installed while NinjaTrader was stopped; installed SHA-256 matches the Release
  build: `24F7DCBEC968BA4C6E13914A663564EE30A5F1AE068B6E0A59138F58288C514F`.
- Recoverable backup: `NTAnalyzerBridge.dll.bak-audit-20260717-220228`.
- File deployment is complete; live callback/IPC acceptance still requires an
  owner-controlled NinjaTrader start and therefore remains **BLOCKED**.

## Still pending for ACCEPTANCE

1. Start NinjaTrader manually → verify live callback, IPC metrics and reconnect.
2. Restart backend with new `/ws/market-data` route.
3. Hard-refresh Desktop → confirm title shows `WS` / `LIVE` / age / hash.
4. Owner diagnostics panel visual acceptance.
5. Redis + PostgreSQL production instances + `NTA_REQUIRE_*=1`.
6. 100-user load report.
7. Credentialed provider acceptance → shadow parity → production failover.

## 2026-07-17 audit evidence

- `python -m pytest -q` → **682 passed**.
- `python -m tests` → **13/13 suites passed**.
- Bridge Release build → **0 warnings, 0 errors**.
- Python compile, JavaScript syntax, JSON parsing and `git diff --check` passed.
- TopstepX remains opt-in/experimental; official ProjectX contract IDs and
  SignalR targets are covered by mocks, not credentialed production acceptance.

## External blockers

1. Live Databento / licensed external key  
2. Multi-user redistribution entitlement  
3. Production Redis + PostgreSQL provisioning  
4. NinjaTrader must be stopped/restarted to unlock DLL replace  

## Fallbacks retained

`market_bars.json`, `/bars/batch`, Telegram PNG, snapshots, draw/open/clear, LTTB, layouts, Practice, Desktop, workspace isolation, owner auth, Cloudflare, Mini App.
