# Unified Trial, Market-Data Admission and Connector Closeout

- Date: 2026-08-23 UTC
- Development base: `653f2b5bcfae2597dc0d14a22f07e741acd84cc8`
- Branch: `codex/trial-connector-release-20260823`
- Status: `IN DEVELOPMENT / LOCAL ACCEPTANCE PASS / CONNECTOR ACCEPTANCE PASS / EXTERNAL GATES OPEN`
- Live environments: unchanged `0.10.0-beta.29`

## Product change

Before: an unauthenticated visitor could enter a blurred preview shell, new
accounts used several inconsistent activation/access contours, and trial
extension was not a first-class audited owner operation.

After: only the protected login/registration surface is available before
authentication. A newly verified human registration receives one idempotent
full seven-day trial per canonical account. The owner may extend it by days or
an exact future UTC date from the Admin user card; actor, reason and compact
`before -> after` history are retained. Expiry leaves the account active on the
authenticated baseline and keeps personal TopstepX/NinjaTrader setup reachable.

## Market-data safety change

HTTP charts, practice quotes and the same-origin browser WebSocket now resolve
one server-owned source admission: owner, verified private provider, fresh
personal Connector, or a bounded shared trial only when both explicit
remote-server and redistribution authority flags are true. Private caches and
events are scoped, live subscriptions are periodically revalidated, queued data
is purged on revoke/source change, and browser diagnostics contain no raw
credential/account/device identity.

The accepted TopstepX history/SignalR/cache/failover implementation was not
refactored. The admission layer prevents a user-owned source from falling
through to another workspace or the owner's global feed.

## Honest external boundaries

- Current policy has no written cross-user redistribution authority; the shared
  trial feed therefore remains fail-closed. This is independent from the
  seven-day StratForge product grant.
- NinjaTrader `8.1.7.2` was explicitly saved and closed by the owner, then the
  verified Development Connector was installed and NinjaTrader was restarted.
  Device-owned enrollment remained intact; signed hello, heartbeat and the two
  configured `MNQ SEP26 5m` / `MES SEP26 5m` subscriptions are authenticated
  against Development with no cross-environment binding.
- A reproduced Connector transport defect sent one market-data snapshot before
  each 15-second command long poll. The bounded queue therefore discarded
  intermediate live snapshots. `0.4.1-dev.14` drains a capped burst before the
  poll. Runtime evidence for 3m02s advanced `source_sequence 110 -> 375` with
  `drops=0` and `transport_errors=0`; Admin reported one installation online.
- The safe product demo-backtest completed as report `#18781` / `done` with 28
  explicitly synthetic trades and zero real orders. Production Connector mode
  remains read-only for this device (`telemetry`, `accounts_read`).
- A publishable Production Connector package still requires the authorized
  Authenticode tool/material. The tested package is Development trust only and
  is not exposed as a public download.
- Four Google/Resend secrets were not read, changed or rotated.

## Verification checkpoint

- Focused Connector/installer/Admin/trial/market-data suites: `50 passed`.
- Full repository suite: `1945 passed`, `32 skipped`, `0 failed`.
- Custom release runner: `13/13` suites passed.
- Bridge Debug build: `0 warnings`, `0 errors`.
- Compileall, 22 Aurora JavaScript syntax checks, CSP, secret, Markdown/link,
  External GPT Context and `git diff --check`: PASS.
- Browser LOCAL acceptance: two simultaneous clients observed MNQ 5m and MES
  5m from `2026-08-23T21:58:35Z` through `22:09:31Z` (10m56s). Final exact
  sample matched WebSocket `lastPrice`, last-bar close and rendered marker in
  both clients: MNQ `29329.75` / red `#ff6b81`, MES `7685.50` / red
  `#ff6b81`; `external_live=true`, `price_marker_live=true`, provider state
  authenticated/live. The live price changed repeatedly without the marker
  becoming grey or `OFF`.
- During the two-client sample the gateway held `browser_websockets=2`,
  `logical_subscriptions=4`, `wire_subscriptions=2`, one shared upstream
  SignalR connection and zero direct provider/auth/loginKey sessions in the
  consumer. After both tabs closed, browser/logical/wire counts returned to
  zero while the shared feed stayed fresh.
- Browser-loaded `api.js`, `ui.js`, `chart-engine.js` and `pages/desktop.js`
  matched the disk bytes; the actual cache-bust was
  `dev-0.10.0-beta.29-653f2b5bcfae`. No service-worker registration exists.
- Git/PR/CI and immutable release evidence are recorded only after they
  complete; no early Canary/Production PASS is claimed here.
- Final LOCAL Connector package: `0.4.1-dev.14`, source
  `a3979a3f42ab55dc968e69ae57f4742d5d56879a`, archive SHA256
  `8B3B7D3A1271829406EE5ED57F8D31B315C82F75AA1E655A9903B5415ED08C84`,
  manifest SHA256
  `9FBAD8AB1276393249504564D2C1E398872D83A3987CF68880D06BD4E7E50E32`.
  Installed DLL exactly matched the verified payload SHA256
  `DB55FCCC1980B2AE2E5CC75912836F3519E88949A6E6B0181FBD39524CE5DAE5`.
- Clean `a3979a3f` browser smoke kept the accepted TopstepX baseline intact:
  MNQ/MES were `LIVE`, colored price labels remained rendered and a second
  simultaneous client saw the same two live instruments.
