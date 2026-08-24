# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-24T04:22:21Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: PR #145 is merged cleanly into `main`; beta.30 Canary was not accepted and Production remains beta.29
- Candidate: `0.10.0-beta.31` minimal consumer viewport-history correction over the accepted trial/access and Connector implementation
- Scope: authenticated entry, one seven-day full trial, owner extension history, per-user market-data source admission and real Connector acceptance
- Status: IN DEVELOPMENT
- Acceptance note: beta.30 chart realtime remained live, but two simultaneous 36-chart layouts saturated all 24 Canary HTTP slots because consumer viewport bounds were dropped. No acceptance or Production promotion occurred. Beta.31 forwards only those bounds; LOCAL capacity evidence passes and a fresh PR/CI/immutable Canary cycle is required.
- Current Production version/build/artifact when known: `0.10.0-beta.29`; build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`; runtime SHA256 `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` remains the pack-wide verification baseline |
| Development implementation SHA | clean base `27184197ea5d495b8e0d90d0cc5c06d6539f7ab9`; beta.31 changes only consumer viewport range forwarding, its regression, version and factual documents |
| Development branch base | clean `main` at `27184197ea5d495b8e0d90d0cc5c06d6539f7ab9`; branch `codex/canary-history-range-beta31` |
| Deployed implementation SHA | Canary non-accepted `27184197ea5d495b8e0d90d0cc5c06d6539f7ab9`; Production accepted `4d15f1d2250e2c52bde02b902d88ec7aad043543` |
| LOCAL | full regression `1946 passed, 32 skipped, 0 failed`; custom runner `13/13`; targeted market-data/gateway + governance/docs `121 passed`; two 36-chart clients completed `10.26 min` under `max_inflight=24`, ending `36/36 external_live + marker`, readiness `20/20`, peak `8`, rejected `0` |
| Canary | beta.30 `27184197` deployed but non-accepted after HTTP-slot saturation; candidate remains `canary_checking` and must be replaced by a fresh beta.31 artifact |
| Production | same beta.29 merge/build/runtime manifest; authenticated owner, two-client MES/MNQ, MNQ 15m and responsive smoke PASS |
| Release parity | accepted beta.29 Production baseline remains intact; beta.30 is not eligible for promotion; beta.31 requires a new one-artifact cycle |
| Market-data baseline | protected; beta.31 changes only consumer forwarding of viewport bounds to the existing history endpoint; TopstepX/SignalR/cache/failover/rollover/realtime/rendering unchanged |
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

## Beta.31 corrective evidence

1. Beta.30 Canary reproduction: two 36-chart clients kept live WebSockets, but
   deep-history prefetch repeated the latest range until all 24 bounded HTTP
   slots were occupied; readiness/Admin returned 503.
2. First divergence: consumer `history_range()` omitted viewport
   `start_time/end_time`. The hub endpoint, provider session and browser realtime
   were healthy.
3. Beta.31 forwards existing `from_ts/to_ts` and propagates the hub's existing
   history exhaustion/cache metadata. Focused gateway/admission regression:
   `81 passed`.
4. Same-limit LOCAL proof: two simultaneous 36-chart clients, `36/36 external_live`,
   `10.26 min`, readiness `20/20`, peak handlers `8/24`, rejected `0`, one
   shared upstream SignalR and zero consumer direct provider/auth/loginKey
   sessions. Both clients exactly matched MNQ/MES WebSocket price, last close
   and colored rendered marker at the final sample.
5. Final clean gates: full regression `1946 passed`, `32 skipped`, `0 failed`;
   custom runner `13/13`; combined market-data/gateway + governance/docs
   `121 passed`; bridge build, Python/JavaScript/static/context/diff checks PASS.

## Previous candidate LOCAL acceptance evidence

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
4. Final clean regression: `1945 passed`, `32 skipped`, `0 failed`; custom
   runner `13/13`; Debug Connector build `0 warnings / 0 errors`; Python/JS,
   CSP, secrets, Markdown/link, context and diff gates PASS.

## Physical Development Connector acceptance

1. Owner saved and closed NinjaTrader `8.1.7.2`; installer probe passed 17/17,
   Connector `0.4.1-dev.14` was repaired in place and its installed DLL matched
   the verified payload byte-for-byte.
2. Enrollment/device key survived repair. Signed hello and heartbeat were
   accepted; Admin showed one installation online in Development. Exact
   configured streams were `MNQ SEP26 5m` and `MES SEP26 5m`.
3. The late-feed lifecycle resubscribed both BarsRequests after the saved price
   connection became ready. History and live batches reached the server.
4. A reproduced one-batch-per-15-second-long-poll queue defect was fixed with a
   bounded burst drain. Post-fix 3m02s evidence advanced source sequence
   `110 -> 375`, `drops=0`, `transport_errors=0`; a second browser still saw
   MNQ/MES `LIVE` through the unchanged TopstepX gateway baseline.
5. Safe demo-backtest report `#18781` completed `done`: 28 explicitly synthetic
   trades, zero real orders. The enrolled device exposes only `telemetry` and
   `accounts_read` capabilities.

## Current blockers before release

| Gate | State | Required evidence |
| --- | --- | --- |
| Cross-user shared trial feed | `EXTERNAL BLOCKED` | written provider/exchange authority and explicit per-user entitlement policy; owner request alone cannot change third-party rights |
| Physical Connector | `PASS` | Development dev.14 install, retained enrollment, heartbeat, MNQ/MES history/live ingestion, queue-drain soak and safe no-order demo-backtest are evidenced above |
| Production Connector package | `EXTERNAL BLOCKED` | Authenticode signing tool and release signing material available to the authorized release environment |
| PR #145 / beta.30 CI | `PASS` | owner-authorized merge `27184197`; all five mandatory checks green |
| beta.31 correction release | `PENDING` | scoped clean commit/PR, mandatory CI, new signed immutable artifact, Canary acceptance, then same artifact Production |

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

- Public Production Connector package remains `EXTERNAL BLOCKED` until the
  authorized Authenticode tool/material is available; Development dev.14
  physical enrollment/runtime acceptance is already complete.
- Google OAuth and transactional e-mail remain `EXTERNAL BLOCKED` until their
  separate provider/security closeout.
- Legal package publication remains `IN DEVELOPMENT` / DRAFT.

## Next development boundary

Commit/push the beta.31 corrective branch, complete its mandatory CI and obtain
the required owner merge decision. Then build one immutable server artifact,
accept it in Canary and promote that same artifact to Production.
Any code change after Canary acceptance starts a new artifact cycle; beta.29
must not be hotfixed in place.

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
2026-08-24T01:52:25Z | GPT-5.5 через Codex по запросу owner | Closed physical Development Connector acceptance with exact dev.14 package, retained enrollment/heartbeat, two-stream live ingestion, bounded transport drain and safe demo-backtest; next gate is PR #144 CI.
2026-08-24T02:41:31Z | GPT-5.5 через Codex по запросу owner | Recorded PR #144 green merge fb7d7f9b, repeated clean-merge Connector heartbeat/history/live and safe UI demo-backtest #18782, and opened the minimal beta.30 versioned release preparation.
2026-08-24T04:22:21Z | GPT-5.5 через Codex по запросу owner | Recorded beta.30 Canary as non-accepted, Production beta.29 unchanged, reproduced the first viewport-range divergence and opened the bounded beta.31 corrective PR/CI/release cycle.
-->
