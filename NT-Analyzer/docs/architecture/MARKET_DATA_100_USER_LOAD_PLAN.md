# Market-data 100-user load plan

Date: 2026-07-16
Status: plan only — **100-USER LOAD PASSED** not yet claimed

## Worst-case profile

| Dimension | Target |
|---|---|
| Concurrent authenticated users | 100 |
| Chart panels / user | up to 64 |
| Total panels | up to 6 400 |
| Instruments | mix of shared + unique |
| Timeframes | several per contract |
| Duration | ≥ 60 minutes |
| Extra chaos | reconnect storm, backend restart, Redis restart, provider disconnect, slow client, tab close/open |

## Anti-goals (must fail the test if observed)

- upstream subscriptions ≈ users or panels
- HTTP live polling remains ~286 batch/sec
- repeated provider history download for same contract
- MES/MNQ identical `cache_key` or `series_hash`
- tenant A sees tenant B overlays

## Pass criteria

| Metric | Pass |
|---|---|
| Upstream subs | = unique `(provider, exact_contract, channel)` |
| HTTP live polling while WS healthy | ~0 full-series polls |
| Redis hit ratio (warm) | ≥ 95% on repeated contracts |
| p95 end-to-end (event→WS) | budget TBD after baseline; no unbounded growth |
| Memory | no leak over 60 min (stable RSS band) |
| Dropped closed bars | 0 |
| Coalesced provisional updates | allowed, counted |
| Tenant isolation | 100% |

## Harness outline

1. Synthetic `RecordedProvider` / `FaultInjectionProvider` event pump
2. N parallel HTTP clients authenticate (staging test-auth)
3. Each opens M chart subscriptions over same-origin WS
4. Metrics scraped from `/api/ops/runtime/market-data/diagnostics`
5. Inject chaos mid-run
6. Write report `docs/MARKET_DATA_100_USER_LOAD_REPORT_<date>.md`

## Current blocker for a real run

- Redis/PostgreSQL production instances not yet wired as default
- Licensed multi-user market-data entitlement not confirmed
- Synthetic harness can still validate fan-in/refcount/cache keys offline

Until the report exists, status remains: **100-USER LOAD PENDING**.
