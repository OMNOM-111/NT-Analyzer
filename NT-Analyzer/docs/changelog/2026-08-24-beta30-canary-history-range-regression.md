# Beta.30 Canary History-Range Regression and Beta.31 Correction

- Date: 2026-08-24 UTC
- Development base: `27184197ea5d495b8e0d90d0cc5c06d6539f7ab9`
- Branch: `codex/canary-history-range-beta31`
- Status: `BETA.30 CANARY NOT ACCEPTED / BETA.31 DEVELOPMENT PASS`
- Production: unchanged accepted `0.10.0-beta.29`

## Non-accepted beta.30 attempt

PR #145 merged cleanly with all five mandatory CI jobs green. Candidate
`rc_3be5871e0bde48b392f5055e7c6dde2b`, artifact
`art_6ae472715d594d99a55a0c0efbb1ebf6`, build
`sf-0.10.0-beta.30-27184197ea5d-20260824T035054Z`, archive SHA256
`7A4B23D15BCF2DBCFA95CD2E9C091D59857BDFC60D45A56B84FA1E7A74779BF3`
and runtime/manifest SHA256
`B958DE90A2211B84C5F38D87BE202392A300D4482F0C8F6EDDAF443E59227F98`
were deployed only to Canary as `dep_dd7c5ac3c9d94f6f9c85baa8616a16ff`.

Two simultaneous 36-chart layouts retained colored MNQ/MES realtime markers
and exactly two promoted browser WebSockets, but deep-history polling eventually
occupied all `24/24` bounded HTTP slots. Readiness and Admin then returned 503;
the candidate remained `canary_checking`. No acceptance was recorded, no
Production promotion occurred and the artifact is not release-eligible.

## First divergence and bounded correction

The provider and realtime path were healthy. The first divergence was
`OwnerGatewayChartAdapter.history_range()`: it accepted viewport
`start_time/end_time` but did not forward them to the existing gateway bars
endpoint. Each backward-prefetch iteration therefore fetched the same latest
chunk instead of advancing through the requested range.

Beta.31 formats those two UTC bounds as the endpoint's existing
`from_ts/to_ts` query fields and propagates its existing requested-range,
cache, chunk, exhaustion and native-aggregation metadata. A regression asserts
the exact forwarded query and exhaustion result.

This change does not modify TopstepX credentials or auth/session ownership,
loginKey, SignalR, provider history implementation, cache/failover, rollover,
realtime event shape, candle construction or chart rendering.

## LOCAL browser and capacity evidence

The correction was run with the same Canary admission ceiling,
`STRATFORGE_API_MAX_INFLIGHT=24`, and two independent 36-chart clients from
`2026-08-24T04:18:09.952Z` through `04:28:25.396Z` (`10.26 min`). Both ended
`36/36 external_live` with a live price marker.

In both clients the final exact DOM sample matched provider WebSocket price,
last-bar close and rendered right-side label:

- MNQ 5m: `29273.25` → `29273.25` → red `29,273.25` (`#ff6b81`);
- MES 5m: `7680.75` → `7680.75` → red `7,680.75` (`#ff6b81`).

Both reported provider `LIVE`, `external_live=true`,
`price_marker_live=true`, and the price changed repeatedly without grey/`OFF`.
Readiness probes passed `20/20`; HTTP admission peak was `8/24`, rejected `0`.
The consumer reported zero direct provider connections, authentication sessions
or loginKey calls, one shared upstream SignalR connection and three browser
WebSockets: the two test clients plus the owner's already-open local page.

## Verification

- Focused owner-gateway/TopstepX/admission/cache/fan-out/resilience suites:
  `81 passed`.
- Combined market-data/gateway and governance/docs suites: `121 passed`.
- Full regression: `1946 passed`, `32 skipped`, `0 failed`; custom runner:
  `13/13` suites.
- Bridge Debug build: `0 warnings`, `0 errors`.
- Compileall, 22 JavaScript syntax checks, External GPT Context, CSP, secret,
  Markdown and `git diff --check`: PASS.
- Production remained on accepted beta.29 throughout this corrective cycle.
