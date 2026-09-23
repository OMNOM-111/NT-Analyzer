# Local charts: correct Development origin

Status: BETA. Release title: Restore Local chart gateway routing.
Change summary: give the Development supervisor its actual loopback origin so
it can consume the designated TopstepX hub without triggering self-loop protection.
Source base: `77eda536`; branch: `codex/fix-local-chart-gateway`.
Implementation commit: `d9c538605e8e6cade81524fc1b41850b7f500980`.
PR: [#292](https://github.com/OMNOM-111/NT-Analyzer/pull/292), stacked on `feat/shared-model-access`.
Verification result: PASS for scoped Local origin correction and real HTTP/WebSocket delivery.

## Incident and cause

On 2026-09-23 the running Local 8765 process reported `role=isolated`,
`self_loop_blocked=true`, credentials present, zero TopstepX sessions and zero
incoming IPC events. Its public origin was incorrectly `https://app.stratforges.com`.
The actual runtime was clean `c9a9d7e6` in the pinned local-runtime worktree,
using the original owner data directory. NinjaTrader was not running; its last
heartbeat was 2026-09-15. Browser WebSocket delivery was connected.

The Development public-origin default originated in `2c4d43bd` (2026-07-21).
The designated-hub and self-loop rules in `a525c493` (2026-08-14) made that
identity collision disable both direct TopstepX and gateway consumption.
`8a34719b` added Development gateway derivation, but isolated gateway tests did
not exercise the actual supervisor profile. This evidence identifies interacting
commits, not an independently verified identity of their AI author.

With owner-authorized gateway HTTP reads, Production returned ten real MET
5-minute candles from TopstepX (`MET 09-26`, `external_live`). Thus the upstream
works and the proven Local defect is routing/identity, not missing credentials.
The separate saved `MBT 08-26` request was unavailable (`active/exact contract
not found`); an MNQ probe also returned no bars. Neither is claimed fixed by this
launcher change, and no contract is silently substituted.

## Change and prevention

- Default Local public origin is `http://127.0.0.1:<actual port>`; an explicit
  HTTPS Development origin remains supported, including its port.
- Full-profile regression tests cover default/custom ports, the real gateway
  role decision, true loopback rejection, token removal and CLI port propagation.
- TopstepX adapter/auth, SignalR, chart renderer, failover and user entitlements
  are unchanged. No extra direct upstream connection is enabled.
- Verification: supervisor/gateway 41 passed; TopstepX/failover/access/cache
  fan-out 62 passed. Tests used disposable state, not owner runtime data.
- External context validation PASS; pre-release bundle gates PASS (631 files,
  static scan, runtime reads, Python compilation and shipped JavaScript syntax).

## Publication and remaining acceptance

Only Development launcher code, regression tests and corresponding records are
to be published in the task PR. No Canary/Production deployment, signing,
promotion, DB migration, credential change or distribution-policy change.
Local activation and live delivery are verified below; no visual-rendering or all-user acceptance is claimed.
There is no claim that provider outages or unavailable contracts cannot recur.

## Local recovery evidence

Verified UTC: 2026-09-23T00:49:11Z; build `dev-0.10.0-beta.96-d9c538605e8e`,
`dirty=false`, `preview_sandbox.enabled=false` from Local `/api/health`.

- Activated clean pinned runtime at `d9c538605e8e6cade81524fc1b41850b7f500980`
  through the existing `StratForge Vitek` task. Previous clean `c9a9d7e6` remains
  the rollback target. Original owner data root and access settings preserved.
- Local status: `role=consumer`, `self_loop_blocked=false`, public origin
  `http://127.0.0.1:8765`, TopstepX `LIVE`.
- Local HTTP: 50 real 5-minute bars each for `MET 09-26`, `MBT 09-26`,
  `MNQ 12-26`, provider `topstepx`, `external_live`, source mode
  `owner_gateway_consumer`.
- Local WebSocket: `welcome -> subscribe_ack -> market_event`, updating
  the `MET 09-26` 00:45 UTC candle. No browser was launched.
- Scoped IMPLEMENTATION COMPLETE; GIT CLOSEOUT COMPLETE: scoped commits pushed to draft PR #292.
  STAGE CLOSED applies only to Local origin routing recovery, not all-user
  chart acceptance, unavailable expired contracts, root-only MNQ resolution,
  visual acceptance or a server release. Those broader claims remain PARTIAL.
