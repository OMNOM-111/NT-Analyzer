# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-23T01:29:45Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Repository baseline: beta.28 is live; beta.29 is active in Development
- Candidate: `0.10.0-beta.29`
- Scope: Market-data fan-out and responsive application acceptance
- Status: IN DEVELOPMENT
- Acceptance note: Development browser/load/responsive checks passed; PR, mandatory CI, immutable Canary acceptance and same-artifact Production promotion remain.
- Current Production version/build/artifact when known: `0.10.0-beta.28`; build `sf-0.10.0-beta.28-36600dba3d73-20260821T031309Z`; runtime SHA256 `864F7D16C03999EF2119EA13C73FBD05DD7FF160E49ADD8EA6D02E91555D916C`

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `7ebda6faf2e7c64d4a707a41062b29857882181a` remains the pack-wide verification baseline; current repository baseline is main `516480bce337eebbd3dbdae4da0a2a92ce9d934d` plus the unmerged beta.29 acceptance change set |
| LOCAL | beta.29 implementation/browser acceptance PASS; `1924 passed`, `32 skipped`, `0 failed`; Git closeout pending |
| Canary | beta.28 `36600dba`, runtime manifest `864F7D16...D916C`, authenticated owner UI/Documents/charts PASS |
| Production | same beta.28 `36600dba` and runtime manifest, public live/ready/exact UI PASS; isolated owner login awaiting physical confirmation |
| Release parity | YES: same candidate/artifact/build/archive/runtime identity; no rebuild |
| Market-data baseline | protected; TopstepX/SignalR/history/cache/failover order unchanged; only reproduced disconnect/refcount diagnostics fixed |
| Secret rotation | explicitly deferred; do not rotate the four Google/Resend secrets |

## Implemented in the beta.29 change set

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

## Remaining release sequence

1. Scoped commit, PR and mandatory CI.
2. Merge clean implementation SHA and build/sign exactly one beta.29 artifact.
3. Canary identity, authenticated UI/responsive/gateway acceptance.
4. Promote the same accepted artifact to Production without rebuild and repeat
   live identity/readiness smoke.

## Explicitly deferred / external

- Physical enrollment of a new Windows NinjaTrader Connector device. Existing
  Connector/NinjaTrader state may be observed, but no synthetic enrollment or
  unnecessary restart is allowed.
- Google OAuth and transactional e-mail remain `EXTERNAL BLOCKED` until their
  separate provider/security closeout.
- Legal package publication remains `IN DEVELOPMENT` / DRAFT.

## Stop conditions

Do not touch Canary/Production until the clean beta.29 merge and mandatory CI
exist. Any code/UI/document correction after Canary acceptance starts a new
artifact cycle; do not rebuild or hotfix an accepted artifact in place.

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
-->
