# Unified Trial, Market-Data Admission and Connector Closeout

- Date: 2026-08-23 UTC
- Author: GPT-5.5 через Codex по запросу owner
- Development base: `653f2b5bcfae2597dc0d14a22f07e741acd84cc8`
- Branch: `codex/trial-connector-release-20260823`
- Status: `IN DEVELOPMENT / LOCAL ACCEPTANCE PASS / EXTERNAL GATES OPEN`
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
- The running NinjaTrader `8.1.7.2` process was observed but not terminated or
  restarted. Its installed Connector is Canary-bound, not enrolled and has no
  authenticated heartbeat/market-data streams.
- A Development Connector package verifies locally, but a publishable
  Production package still requires the authorized Authenticode tool/material.
- The next acceptance step is physical: owner saves/closes NinjaTrader, then the
  candidate Connector can be installed and the owner restarts/approves native
  prompts. No synthetic enrollment is accepted.
- Four Google/Resend secrets were not read, changed or rotated.

## Verification checkpoint

- Focused trial/auth/permissions/cabinet/market-data/fan-out suites: PASS.
- Full repository suite: `1943 passed`, `32 skipped`, `0 failed`.
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

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-23T21:36:03Z | GPT-5.5 через Codex по запросу owner | Created the canonical Development checkpoint for unified trial/access, scoped market-data admission and real Connector closeout boundaries.
2026-08-23T22:20:31Z | GPT-5.5 через Codex по запросу owner | Recorded clean LOCAL automated and two-client 10-minute visual acceptance; preserved external redistribution, physical Connector and signing gates.
-->
