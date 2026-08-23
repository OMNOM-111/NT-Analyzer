# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-23T22:20:31Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: beta.29 implementation remains live; new work is isolated on `codex/trial-connector-release-20260823` from `653f2b5bcfae2597dc0d14a22f07e741acd84cc8`
- Candidate: unversioned Development trial/access and Connector closeout candidate
- Scope: authenticated entry, one seven-day full trial, owner extension history, per-user market-data source admission and real Connector acceptance
- Status: IN DEVELOPMENT
- Acceptance note: implementation and automated LOCAL validation are in progress. Canary/Production remain unchanged beta.29 until the new PR, physical Connector step and immutable Canary acceptance pass.
- Current Production version/build/artifact when known: `0.10.0-beta.29`; build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`; runtime SHA256 `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` remains the pack-wide verification baseline |
| Development branch base | `653f2b5bcfae2597dc0d14a22f07e741acd84cc8`; final candidate SHA is assigned at Git closeout |
| Deployed implementation SHA | `4d15f1d2250e2c52bde02b902d88ec7aad043543`; post-release operational docs-only closeout does not mutate the artifact |
| LOCAL | trial/access and source-admission implementation present; `1943 passed`, `32 skipped`, `0 failed`; custom runner, bridge build and static gates pass; two-client 10m56s MNQ/MES browser acceptance PASS |
| Canary | beta.29 `4d15f1d`, runtime manifest `CBA4FA70...2379`, authenticated owner UI/Documents/36-chart/second-client PASS |
| Production | same beta.29 merge/build/runtime manifest; authenticated owner, two-client MES/MNQ, MNQ 15m and responsive smoke PASS |
| Release parity | beta.29 YES; new Development candidate has not entered release pipeline |
| Market-data baseline | protected; TopstepX/SignalR/history/cache/failover order unchanged; only reproduced disconnect/refcount diagnostics fixed |
| Secret rotation | explicitly deferred; no Google/Resend or provider secret was exposed or rotated |

## Implemented in the new Development candidate

1. Anonymous visitors no longer enter a blurred or preview application shell.
2. Verified Telegram Mini App/contact, Google and e-mail registrations activate
   one idempotent seven-day `trial_full` grant; returning identities/devices do
   not restart it.
3. Trial expiry leaves the account active. The authenticated baseline keeps
   Cabinet, Documents, practice and personal TopstepX/NinjaTrader setup.
4. Admin user cards expose trial state, dates, extension by days or exact UTC
   date, reason and actor-aware before/after history.
5. HTTP and same-origin WebSocket market data share one fail-closed admission
   decision. Private-provider and personal-Connector scopes cannot fall through
   to the owner feed or another user's cache/events.
6. A shared product trial reaches the owner gateway only when both explicit
   remote-server and redistribution authority flags are true. Current policy is
   false, so this path remains honestly denied instead of silently sharing the
   owner's entitlement.

## New candidate LOCAL acceptance evidence

1. Two simultaneous browser clients observed MNQ 5m and MES 5m for `10m56s`.
   The final exact sample matched WebSocket `lastPrice`, last-bar close and the
   colored rendered price marker in both clients; live-state never degraded to
   grey/`OFF` while the shared feed was fresh.
2. Peak fan-out was two browser WebSockets, four logical subscriptions, two
   wire subscriptions and one shared upstream SignalR connection. Consumer
   direct provider/auth/loginKey counts stayed zero. Closing both tabs returned
   browser/logical/wire counts to zero.
3. The four loaded chart assets matched local disk bytes under cache-bust
   `dev-0.10.0-beta.29-653f2b5bcfae`; there is no service-worker registration.
4. Final clean regression: `1943 passed`, `32 skipped`, `0 failed`; custom
   runner `13/13`; Debug Connector build `0 warnings / 0 errors`; Python/JS,
   CSP, secrets, Markdown/link, context and diff gates PASS.

## Current blockers before release

| Gate | State | Required evidence |
| --- | --- | --- |
| Cross-user shared trial feed | `EXTERNAL BLOCKED` | written provider/exchange authority and explicit per-user entitlement policy; owner request alone cannot change third-party rights |
| Physical Connector | `BLOCKED ON USER INTERACTION` | owner manually saves/closes NinjaTrader, then Development Connector install/restart/enrollment/heartbeat/history/live/backtest can be observed |
| Production Connector package | `EXTERNAL BLOCKED` | Authenticode signing tool and release signing material available to the authorized release environment |
| PR/CI/release | `PENDING` | clean commit, mandatory CI, new signed immutable artifact, Canary acceptance, then same artifact Production |

The four Google/Resend secrets remain outside this task and must not be changed.

## Released in beta.29

- Responsive shell breakpoints keep environment/System controls reachable on
  large desktop, tablet and phone without whole-page horizontal overflow.
- Chart windows keep saved free-position geometry on desktop and reflow to a
  vertical compact stack at 1100 px and below.
- Mobile Admin tabs no longer sit under the active module; Connector content,
  notices and strategy Kanban reflow inside their own surfaces.
- Operations serializes live Telegram lease timestamps and bounds independent
  Worker/Telegram/Connector probes so one slow source cannot blank the panel.
- Normal browser TCP reset releases WebSocket leases quietly; a late history
  bootstrap cannot outlive an existing consumer; successful reconnect clears
  historical transport error state.

## Completed Development evidence

1. 84/84 page/viewport matrix checks passed; mobile Add Chart, Cabinet, Users,
   Connectors, Operations and Environments pointer-click journeys had zero
   document overflow, console errors or failed same-origin requests.
2. 12-page/24-chart load across three browser profiles held one gateway
   SignalR connection and two wire subscriptions. Browser traffic stayed
   same-origin and provider credentials were never exposed.
3. MES 5m and MNQ 15m rendered identical closes and colored live markers on
   desktop/tablet/mobile DPI profiles with NinjaTrader OFF.
4. Closing the test profiles returned browser WebSockets `14 -> 2` and logical
   refs `22 -> 4`, exactly matching pre-load baseline; direct/loginKey remained
   zero and reconnect error remained empty.
5. Targeted market/chart/Operations/responsive suite: `251 passed`; full suite:
   `1924 passed`, `32 skipped`, `0 failed`; py_compile/compileall, 32 JavaScript
   syntax checks, CSP, secret, Markdown/link, Context Pack and diff checks passed.

Detailed evidence:
[2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md).

## Completed release sequence

1. [PR #142](https://github.com/OMNOM-111/NT-Analyzer/pull/142): five mandatory
   checks green; merge `4d15f1d2250e`.
2. Candidate `rc_a7c6c0afb95d410f92474614efeb1b35`, artifact
   `art_ccaadc3a536e4272809d32073f072918`, archive
   `882FF352...195B`, runtime manifest `CBA4FA70...2379`.
3. Canary deployment `dep_de061542f96641e1a10b7bb4456c2df0` and acceptance
   `2026-08-23T02:08:54Z`: PASS.
4. Production deployment `dep_8716b7cf463f4cf8af092ba6a4e5bdae`, same artifact,
   no rebuild, `production_live` at `2026-08-23T02:16:30Z`: PASS.

## Explicitly deferred / external

- Physical enrollment of a new Windows NinjaTrader Connector device. Existing
  Connector/NinjaTrader state may be observed, but no synthetic enrollment or
  unnecessary restart is allowed.
- Google OAuth and transactional e-mail remain `EXTERNAL BLOCKED` until their
  separate provider/security closeout.
- Legal package publication remains `IN DEVELOPMENT` / DRAFT.

## Next development boundary

Commit and PR the LOCAL-accepted Development candidate, then stop at the
physical NinjaTrader interaction. Any code change after Canary
acceptance starts a new artifact cycle; beta.29 must not be hotfixed in place.

## Canonical evidence

- [LOCAL_BASELINE_CHECKPOINT.md](../current/LOCAL_BASELINE_CHECKPOINT.md)
- [2026-08-20-final-product-acceptance-beta28.md](../changelog/2026-08-20-final-product-acceptance-beta28.md)
- [2026-08-22-market-data-responsive-release-beta29.md](../changelog/2026-08-22-market-data-responsive-release-beta29.md)
- [04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [06_MARKET_DATA_TRADING_CONNECTOR.md](06_MARKET_DATA_TRADING_CONNECTOR.md)
- `app/owner_market_data_gateway.py`
- `app/market_data_ws_http.py`

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-20T23:00:44Z | GPT-5.5 через Codex по запросу owner | Replaced obsolete beta.1 handoff with executable beta.28 final-acceptance checkpoint and explicit stop/deferred boundaries.
2026-08-21T00:53:04Z | GPT-5.5 через Codex по запросу owner | Recorded first beta.28 Canary as not accepted, the live archive/runtime digest diagnosis and mandatory corrected rebuild; Production stayed beta.26.
2026-08-21T02:03:00Z | GPT-5.5 через Codex по запросу owner | Recorded the non-accepted 8865fad0 Canary artifact and the isolated governance-ledger parity correction required before final acceptance; Production stayed beta.26.
2026-08-21T02:52:33Z | GPT-5.5 через Codex по запросу owner | Recorded 2790fb43 Canary visual acceptance, the real authoritative promotion state blocker and mandatory new release cycle; Production stayed beta.26.
2026-08-21T03:50:00Z | GPT-5.5 через Codex по запросу owner | Closed the immutable beta.28 release sequence through accepted Canary and same-artifact Production; retained the physical Production Telegram login as the sole explicit interaction.
2026-08-23T01:29:45Z | GPT-5.5 через Codex по запросу owner | Opened beta.29 release handoff with completed Development fan-out/responsive evidence and the exact remaining PR/CI/Canary/same-artifact Production sequence.
2026-08-23T02:27:02Z | GPT-5.5 через Codex по запросу owner | Closed beta.29 handoff after PR #142, exact immutable Canary acceptance and same-artifact Production live promotion; remaining items are explicit external/product boundaries, not release blockers.
2026-08-23T21:36:03Z | GPT-5.5 через Codex по запросу owner | Opened the unified trial/access and real Connector closeout, recorded implemented Development scope plus exact redistribution, Authenticode and physical NinjaTrader blockers; beta.29 live environments remain untouched.
2026-08-23T22:20:31Z | GPT-5.5 через Codex по запросу owner | Recorded clean LOCAL 1943/32/0 and 10m56s two-client chart acceptance, asset parity and fan-out release; retained all external and physical gates.
-->
