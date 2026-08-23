# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-23T02:27:02Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: beta.29 implementation merge is live; this operational docs-only closeout follows it
- Candidate: `0.10.0-beta.29`
- Scope: Market-data fan-out and responsive application acceptance
- Status: DONE
- Acceptance note: Development, PR/CI, immutable Canary acceptance and same-artifact Production promotion all passed; no market-data architecture rewrite was introduced.
- Current Production version/build/artifact when known: `0.10.0-beta.29`; build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`; runtime SHA256 `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379`

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` remains the pack-wide verification baseline |
| Deployed implementation SHA | `4d15f1d2250e2c52bde02b902d88ec7aad043543`; post-release operational docs-only closeout does not mutate the artifact |
| LOCAL | beta.29 implementation/browser/load/responsive PASS; `1924 passed`, `32 skipped`, `0 failed`; main clean before docs closeout |
| Canary | beta.29 `4d15f1d`, runtime manifest `CBA4FA70...2379`, authenticated owner UI/Documents/36-chart/second-client PASS |
| Production | same beta.29 merge/build/runtime manifest; authenticated owner, two-client MES/MNQ, MNQ 15m and responsive smoke PASS |
| Release parity | YES: same candidate/artifact/build/archive/runtime identity; no rebuild |
| Market-data baseline | protected; TopstepX/SignalR/history/cache/failover order unchanged; only reproduced disconnect/refcount diagnostics fixed |
| Secret rotation | explicitly deferred; no Google/Resend or provider secret was exposed or rotated |

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

Beta.29 infrastructure closeout is complete. New product work starts from a new
Development branch/cycle. Any code, UI or user-document correction requires a
new commit, artifact and Canary acceptance; do not hotfix beta.29 in place.

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
-->
