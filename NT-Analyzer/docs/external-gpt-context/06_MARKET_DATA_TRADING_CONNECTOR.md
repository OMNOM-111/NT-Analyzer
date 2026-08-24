# 06. Market Data, Trading and Connector

- Context Pack document: 06_MARKET_DATA_TRADING_CONNECTOR.md
- Last verified UTC: 2026-08-23T21:36:03Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: NinjaTrader authority, Connector protocol, market-data gateway and trading safety gates
- Status: PARTIAL

## Non-negotiable current rules

1. NinjaTrader is the execution path and the source of truth for fills, trades,
   metrics and runtime strategy state.
2. TopstepX is the primary independent read-only history/realtime chart source
   when configured.
3. Current chart order is TopstepX, then fresh NinjaTrader Connector runtime,
   then another explicitly allowed credentialed provider, then offline/cache.
4. Synthetic candles are not created and delayed/history data is not labeled
   live.
5. A chart feed never authorizes an order.
6. Exactly one explicitly designated StratForge process opens the owner
   TopstepX/ProjectX loginKey + SignalR session. Production is the current hub;
   Canary and Development consume it through the authenticated internal
   gateway. Browser clients connect only to their own same-origin StratForge
   `/ws/market-data` endpoint and never receive provider credentials.
7. Gateway role selection is fail-closed. `auto` never opens a direct provider
   session. A process opens one only with
   `NTA_OWNER_MARKET_DATA_GATEWAY_ROLE=hub`; consumers require an approved
   canonical/loopback origin and a configured internal token.
8. Product access and provider/exchange permission are independent. A seven-day
   product trial cannot consume the owner feed unless both remote-server use and
   cross-user redistribution are explicitly authorized.
9. A non-owner chart request resolves exactly one server-owned scope: verified
   private provider, fresh online personal Connector, or an explicitly
   authorized shared trial. HTTP cache keys and WebSocket events are filtered by
   that scope; browser messages cannot assert an entitlement.

## Current status matrix

| Area | Status | Current fact |
| --- | --- | --- |
| Connector protocol v1 | `BETA` | Pair/enroll/challenge/hello/heartbeat/market-data/commands are implemented with device-owned P-256 keys and bounded capabilities |
| Read-only charts | `BETA` | TopstepX history/realtime works with NinjaTrader OFF in Development, Canary and Production; beta.29 is the current live artifact in both server environments |
| Owner market-data gateway | `AVAILABLE` | One Production upstream session fans out to authorized same-account/environment consumers. Browser tabs share the local StratForge WebSocket and logical subscriptions are reference-counted and released on close/reconnect |
| Connector fallback | `BETA` | Fresh NinjaTrader Connector bars remain a separate chart fallback when actually connected; NinjaTrader remains the execution route |
| SignalR/session/freshness | `AVAILABLE` | Quote/SignalR heartbeat freshness is independent of price movement. A fresh heartbeat keeps the marker live when the last price is unchanged; stale/offline states mute it honestly |
| Responsive chart UI | `BETA` | Desktop free-positioned layouts remain intact; at 1100 px and below chart windows reflow into a readable vertical stack without whole-page horizontal overflow |
| Cross-user market-data redistribution | `EXTERNAL BLOCKED` | The owner gateway is not a license grant. Serving one owner entitlement to unrelated users remains fail-closed until written provider/CME distribution authority and per-user entitlement mapping exist |
| Per-user HTTP/WS admission | `IN DEVELOPMENT` | Development candidate gates every bars/chart/practice-tick request and every WebSocket subscription through the same resolver, revalidates live sockets every five seconds or sooner at expiry, purges queued events on revoke/source change and exposes only hashed scope diagnostics |
| User-owned source isolation | `IN DEVELOPMENT` | Verified private provider data uses private cache/backfill only; personal Connector data uses its workspace snapshot only. Neither path can fall through to global owner TopstepX/cache/failover |
| Simulation/paper runtime control | `BETA` | Safe runtime commands exist for paper/demo/playback contours |

## Current physical NinjaTrader / Connector checkpoint

- The owner explicitly saved and closed NinjaTrader `8.1.7.2`; verified package
  `0.4.1-dev.14` was installed and NinjaTrader was restarted normally. The
  running Connector is bound only to `http://127.0.0.1:8765` Development.
- Device-owned enrollment survived repair. Signed hello was accepted, Admin
  reported `installations=1`, `online=1`, and heartbeat
  `2026-08-24T01:48:40Z`; no bootstrap credential remained on disk.
- The exact configured read-only streams are `MNQ SEP26 5m` and `MES SEP26 5m`.
  Both history requests subscribed, late price-connection readiness triggered
  one bounded resubscribe, and live batches reached the authenticated server.
- The reproduced one-batch-per-long-poll transport lag was fixed by draining a
  bounded queue burst before command polling. A 3m02s post-fix observation
  advanced source sequence `110 -> 375` with `drops=0` and
  `transport_errors=0`. The prior dev.13 control advanced only one batch about
  every 15 seconds and logged continuous oldest-batch drops.
- Package source is `a3979a3f42ab55dc968e69ae57f4742d5d56879a`;
  archive SHA256 is
  `8B3B7D3A1271829406EE5ED57F8D31B315C82F75AA1E655A9903B5415ED08C84`,
  manifest SHA256 is
  `9FBAD8AB1276393249504564D2C1E398872D83A3987CF68880D06BD4E7E50E32`,
  and installed/payload DLL SHA256 is
  `DB55FCCC1980B2AE2E5CC75912836F3519E88949A6E6B0181FBD39524CE5DAE5`.
- A safe in-product demo-backtest finished `done` as report `#18781` with 28
  explicitly synthetic trades and no real orders. The enrolled Production
  Connector device has only `telemetry` and `accounts_read` capabilities.
- A publishable Production Connector remains blocked because the authorized
  Authenticode signing tool/material is unavailable. The dev.14 package is
  Development trust only and is not offered as a public installer.
- One physical NinjaTrader instance can bind to one environment at a time.
  LOCAL, Canary and Production acceptance therefore requires sequential manual
  save/close, install/restart and any native license/provider confirmation; it
  must not be simulated or automated by terminating the process.

## Verified beta.29 Development evidence

- 12 browser pages across three isolated profiles, 24 charts total, MES 5m and
  MNQ 15m: every completed chart showed the same close and the same colored
  live price label; no page had whole-document horizontal overflow.
- Browser traffic used only `127.0.0.1:8765`; every browser WebSocket was
  `ws://127.0.0.1:8765/ws/market-data`; there were zero direct TopstepX,
  ProjectX or Gateway API browser requests.
- At peak: 14 browser WebSockets, two wire instrument subscriptions and one
  owner-gateway SignalR connection. Direct provider connections and loginKey
  calls in the Development consumer remained zero.
- After all 12 test pages closed, browser WebSockets returned `14 -> 2` and
  logical references returned exactly `22 -> 4`; wire subscriptions stayed at
  two and the gateway connection stayed at one. No reconnect error remained.
- NinjaTrader was OFF throughout this acceptance. The market was closed, so an
  unchanged price was expected; provider/heartbeat freshness, not invented
  price movement, kept labels live.

Detailed evidence and defect scope:
[2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md).

## Verified beta.29 server evidence

- Production Admin reports `hub/direct_hub`, TopstepX `LIVE`; Canary and LOCAL
  report `consumer/owner_gateway_consumer`. No consumer opens a direct provider
  or loginKey session.
- Authenticated Canary and Production browser clients showed MES 5m close
  `7687.5` → rendered `7,687.50` green and MNQ close `29370` → rendered
  `29,370.00` red with `external_live=true` and `price_marker_live=true`.
  Production MNQ 15m passed the same contract and was restored to 5m.
- Production browser resource inventory contained only same-origin StratForge
  bars/batch endpoints. Provider credentials and direct TopstepX/ProjectX
  browser requests were absent.
- The accepted runtime artifact is
  `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`;
  Canary and Production asset hashes were byte-identical. The market was
  closed, so no fabricated moving-tick claim is made; live color was sustained
  by fresh gateway/SignalR heartbeat.

## Read-only versus execution boundaries

| Boundary | Can do | Cannot do |
| --- | --- | --- |
| TopstepX / another chart feed | Supply authorized chart/history/realtime data | Route or authorize orders; grant redistribution rights |
| StratForge market-data gateway | Deduplicate one authorized upstream and fan it out to scoped application clients | Expose provider credentials; silently create a second hub; bypass user entitlement |
| Connector market-data session | Deliver authenticated bounded OHLCV batches | Infer new permissions beyond its session capabilities |
| NinjaTrader runtime | Compile, backtest, manage runtime state and execute orders when allowed | Bypass product release/auth/safety gates |

## Areas that require a reproduced defect before change

- `app/connector_protocol.py`
- `app/market_data_failover.py`
- `app/market_data_live_adapters.py`
- `app/market_data_ws_http.py`
- `app/owner_market_data_gateway.py`
- [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md)
- [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md)

## Canonical evidence

- [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md)
- [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md)
- [../changelog/2026-08-20-final-product-acceptance-beta28.md](../changelog/2026-08-20-final-product-acceptance-beta28.md)
- [../changelog/2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md)
- `app/owner_market_data_gateway.py`
- `app/market_data_ws_http.py`

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T18:45:00Z | Claude Opus 5 через Claude Code по запросу owner | Записано правило единственного назначенного owner market-data hub и его fail-closed default.
2026-08-14T06:20:00Z | Grok 4.6 через Cursor по запросу owner | Recorded repository TopstepX-first server chart order; live 1fae1f39 still stubs/skips TopstepX.
2026-08-23T01:29:45Z | GPT-5.5 через Codex по запросу owner | Удалены устаревшие live 1fae1f39/IN DEVELOPMENT формулировки; зафиксированы фактический Production hub, Canary/DEV consumer fan-out, browser/load evidence и внешний entitlement blocker.
2026-08-23T02:27:02Z | GPT-5.5 через Codex по запросу owner | Добавлены live beta.29 Canary/Production gateway roles, exact artifact, two-client chart/marker and same-origin browser-network evidence; Connector/redistribution gaps оставлены честно PARTIAL/EXTERNAL BLOCKED.
2026-08-23T21:36:03Z | GPT-5.5 через Codex по запросу owner | Added the Development per-user HTTP/WS admission and source-isolation contracts, recorded the real running Connector/NinjaTrader checkpoint and preserved redistribution, Authenticode and physical-interaction blockers without changing the accepted TopstepX baseline.
2026-08-24T01:52:25Z | GPT-5.5 через Codex по запросу owner | Replaced the obsolete unenrolled Connector checkpoint with verified dev.14 install, signed enrollment/heartbeat, two-stream history/live ingestion, bounded drain evidence and safe no-order demo-backtest; Authenticode remains external.
-->
