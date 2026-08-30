# beta.68 — Production API auth polling performance

Status before release: **IMPLEMENTATION VERIFIED / RELEASE PENDING**.

## Measured root cause

The remaining Production load after the beta.61 worker fix was reproduced on
the live beta.67 API process. A 30-second `pidstat` window showed sustained
bursts around 55–69% of one CPU core. Equal read-only PostgreSQL sampling found
no new `sf_connector_sessions` writes; the hot statements were repository and
user reads initiated by authenticated browser polling.

An isolated 100-call Production benchmark attributed the dominant cost to
owner permission resolution:

| Operation | Wall p50 | Mean process CPU per call |
| --- | ---: | ---: |
| Current owner permission resolution | 77.053 ms | 36.321 ms |
| Unconditional owner resolution without entitlement repository read | 0.002 ms | 0.001 ms |
| Full auth document read | 15.127 ms | 7.241 ms |
| One authoritative session/user join | 14.319 ms | 5.887 ms |

The browser route capture showed ordinary authenticated UI polls rather than a
Connector hot loop. Connector heartbeat, command polling, account snapshot and
market-data semantics therefore were not changed.

## Scoped correction

- Owner permissions now take the already-existing unconditional owner branch
  before loading the entitlement repository.
- Server environments authenticate one session through the normalized
  `sf_auth_sessions` + `sf_users` mirror written atomically with the auth
  document. Every request still checks token hash, revocation, expiry and active
  user status; no security decision is cached.
- PostgreSQL `Decimal` values are normalized at the JSON boundary so health and
  Operations payloads do not fail serialization.

No worker scheduling, TopstepX, SignalR, market-data, chart, Connector protocol,
NinjaTrader, host, container, firewall or Supervisor behavior changed.

## Pre-release verification

- full regression: `2213 passed`, `32 skipped`, `0 failed`;
- release-focused regression: `115 passed`, `0 failed`;
- custom project runner: `13/13` suites;
- compile, 32 JavaScript syntax checks, CSP, secrets, Markdown/link, Context
  Pack validation and `git diff --check`: PASS.

Live equal-window after measurements and exact immutable release identity are
recorded only after Canary acceptance and same-artifact Production promotion.
