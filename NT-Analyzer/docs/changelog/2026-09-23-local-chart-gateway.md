# Local charts: correct Development origin

Status: IN DEVELOPMENT. Release title: Restore Local chart gateway routing.
Change summary: give the Development supervisor its actual loopback origin so
it can consume the designated TopstepX hub without triggering self-loop protection.
Source base: `77eda536`; branch: `codex/fix-local-chart-gateway`.
Verification result: targeted tests PASS; Local activation pending.

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
Real Local HTTP bars and stream delivery must be checked after activation.
There is no claim that provider outages or unavailable contracts cannot recur.
