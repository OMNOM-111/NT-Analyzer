# Stage 7 load and failure report — 2026-07-21

Статус локального automated acceptance: **PASS**. Статус capacity acceptance
на целевом Linux Production: **BLOCKED_EXTERNAL** до запуска тех же probes на
фактическом server/managed PostgreSQL. Ни один тест не включал live trading,
real payments или реальные provider credentials.

## Контур и критерии

- Windows Development host, Python 3.12, bounded stdlib HTTP server.
- PostgreSQL 17.10 test cluster на loopback, TLS required, отдельные admin/app
  roles, schema versions `[1, 2]`.
- HTTP request window 12 s, 10/50/100 users, два authenticated read routes,
  отдельный workspace каждому пользователю.
- Worker profile: 2 chart jobs на workspace, 8 drain threads, часть downstream
  jobs получает детерминированную задержку.
- API PASS: zero transport/unexpected/lock errors, каждый user получает 200,
  admitted p95 <= 1 s, p99 <= 1.5 s, overload p95 <= 250 ms, recovery <= 1 s.
- Worker PASS: все jobs завершены, exact fairness, p95 E2E <= 30 s, no expired
  leases, crash recovery <= 2 s, no dangerous duplicate.

`503` в 50/100 профиле — ожидаемый bounded overload при tight loop без user
think-time. Он считается PASS только при JSON code `api_admission_saturated`,
`Retry-After: 1`, отсутствии dropped/reset и последующем 200 recovery.

## HTTP/API

| Users | HTTP 200 | Bounded 503 | Admitted p50/p95/p99 | Max | Per-user success min..max | RSS delta |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1434 | 0 | 78.6 / 118.6 / 174.9 ms | 348.7 ms | 140..146 | +5.96 MiB |
| 50 | 1446 | 228 | 397.7 / 476.1 / 611.6 ms | 992.6 ms | 23..32 | +5.41 MiB |
| 100 | 971 | 3525 | 683.9 / 764.0 / 808.0 ms | 1038.7 ms | 5..14 | +4.04 MiB |

Overload p95: 50 users `24.5 ms`; 100 users `112.5 ms`. Rejector pool peak:
`2/16` и `7/16`; dropped responses: `0`. Post-load recovery: `10.3 ms` и
`8.0 ms`. Во всех профилях workspace isolation, read-only store checksum и
Production guard — PASS; real operations flags — false.

~~~text
Admitted HTTP p95 (ms, lower is better; limit 1000)
10   119  ███
50   476  ████████████
100  764  ███████████████████
~~~

До исправления профиль 100 воспроизводимо имел 8-second timeouts. cProfile
показал ~120 ms CPU на полный auth-chain: основная доля приходилась на deepcopy
целых DPAPI документов и повторный Windows canonical-path lookup. После
read-only row snapshots, write-isolated cache и env-keyed root cache chain
снизился примерно до 11 ms; финальный профиль не имел timeout/reset.

## PostgreSQL workers

| Users/workspaces | Jobs | Enqueue p50/p95/p99 | E2E p50/p95/p99 | Throughput | CPU one core | RSS peak |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 20 | 436.7 / 504.4 / 513.9 ms | 2.088 / 2.698 / 2.705 s | 5.11 jobs/s | 14.77% | 64.95 MiB |
| 50 | 100 | 986.8 / 1903.7 / 2060.7 ms | 8.442 / 11.826 / 12.135 s | 6.19 jobs/s | 20.99% | 67.09 MiB |
| 100 | 200 | 943.2 / 1597.2 / 1791.0 ms | 16.819 / 21.735 / 22.461 s | 6.75 jobs/s | 22.47% | 69.33 MiB |

Каждый workspace завершил ровно 2 jobs. Attempts p50/p95/p99 = `1/1/1`,
active/expired leases после drain = `0/0`, errors = `[]`. База выросла во
время прогона с `10,139,315` до `10,688,179` bytes (`+548,864` bytes) до
cleanup тестовых tenants.

~~~text
Worker E2E p95 (seconds, lower is better; limit 30)
10    2.7  ██
50   11.8  ████████
100  21.7  ███████████████

Peak RSS (MiB)
10   65.0  ██████████████████
50   67.1  ███████████████████
100  69.3  ████████████████████
~~~

## Failure/isolation acceptance

| Scenario | Evidence | Result |
|---|---|---|
| Provider outage | safe job requeued, then completed after recovery | PASS |
| Worker crash | stale lease swept, replacement lease differs, recovery 955.4 ms | PASS |
| Dangerous duplicate | 24 concurrent requests -> 1 row + 23 idempotent replays | PASS |
| Graceful SIGTERM model | service waits for in-flight job within grace; threads exit | PASS |
| Cancellation | cancel requested; late completion cannot commit result | PASS |
| Slow Connector | 5.295 s > TTL; expired command not delivered; replay same id | PASS |
| Connector isolation | cross-workspace denied; revoked session denied | PASS |
| Shared rate limit | 10 concurrent requests with limit 5 -> exactly 5 allowed | PASS |
| PostgreSQL RLS | foreign workspace reads/writes denied by real app role | PASS |

## Evidence artifacts

Local evidence JSON is retained outside the repository in the Stage 7 backup:

- `stage7-http-10-final.json`
- `stage7-http-50-final.json`
- `stage7-http-100-final.json`
- `stage7-worker-load-final.json`

Key automated gates at this revision:

- real PostgreSQL storage+worker integration: `20 passed`;
- Production worker suite including graceful shutdown: `12 passed`;
- Connector suite: `10 passed`;
- slow/concurrent Connector probe: `ok=true`;
- bounded reject burst: 64/64 structured 503, no transport reset.

## Remaining external acceptance

Повторить на целевом Linux host после backup/migration, без public traffic:

1. 10/50/100 API и worker profiles с host CPU/RAM/disk/network graphs.
2. Managed PostgreSQL failover/read-only/connection exhaustion.
3. Real Cloudflare Tunnel saturation and reconnect.
4. Owner Windows VM и clean third-party NinjaTrader installation.
5. Real provider timeout/quota с расходным лимитом.

До этих действий нельзя переносить локальную throughput цифру на Production
capacity или объявлять весь Production rollout завершённым.
