# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-08-30T02:05:00Z
- Verified against Git SHA: 1279645e48e32000978364b38fb20d3dcd303843
- Verified deployed artifact Git SHA: `1a1d54aa728d487203bb8342ecf142752610f4cd`
- Current Production version/build/artifact when known: `0.10.0-beta.79`; `sf-0.10.0-beta.79-1a1d54aa728d-20260829T234541Z`; live release dir `0.10.0-beta.79-1a1d54aa728d`
- Scope: Final repository housekeeping after beta.79 closeout
- Status: DONE

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `1279645e48e32000978364b38fb20d3dcd303843`; deployed artifact `1a1d54aa728d487203bb8342ecf142752610f4cd` |
| Code change | beta.70-beta.79 closeout through PR #230 |
| Release | `0.10.0-beta.79` |
| Build | `sf-0.10.0-beta.79-1a1d54aa728d-20260829T234541Z` |
| Archive / runtime hashes | recorded in release evidence |
| Canary | accepted, ready, same release dir as Production |
| Production | same immutable artifact, live/ready |
| Release parity | same release directory suffix `0.10.0-beta.79-1a1d54aa728d`; previous/rollback beta.78 for Production |
| Worker concurrency | `interactive_ai=4`, `chart=4`, `telemetry=2`, `maintenance=1` |
| Canary idle result | CPU `83.711% → 4.839%`; total DB TX/s `155.378 → 28.700`; pickup p50/max `1.372/1.455 s` |
| Production idle result | worker CPU `83.778% → 5.522%`; worker-attributable TX/s about `69.002 → 5.822`; pickup p50/max `1.392/1.468 s` |
| Tests | full beta.79 closeout `2327 passed, 32 skipped, 0 failed`; current housekeeping local audit `2326 passed, 34 skipped, 0 failed`; CI GREEN |
| Market-data and Connector baseline | preserved; accepted TopstepX and Connector functional paths remain current |
| Secret rotation | completed for the two Google Client Secrets and two Resend keys; three older platform secrets remain in env until their separate migration |

## Completed actions

1. SERVER BACKTEST executes on VMNINJA, returns device aggregates and report UI
   data, and no longer recalculates authoritative metrics from truncated trades.
2. Cancel is cooperative and honest: `cancel_requested` persists until the
   device reaches a safe boundary; late success remains `done` with race audit.
3. Connector state presentation separates transport lease from confirmed
   NinjaTrader live state; stale accounts are last-known and non-controllable.
4. Worker idle scheduling and the later auth status hotspot are closed with
   regression coverage and live evidence.
5. Four platform secrets were rotated and post-revoke Google/Resend smoke
   passed on both Canary and Production.
6. Final repository housekeeping is in progress only for local dirty files,
   stale Context Pack beta.61 text, old conflicting PRs, old worktrees and
   historical stashes.

## Remaining boundaries, not blockers for this closeout

| Area | State | Boundary |
| --- | --- | --- |
| DB tx/s diagnostics path | missing | safe `pg_stat_database` diagnostics are not exposed in the app; do not search DSNs/secrets for this |
| Cross-user shared owner feed | `EXTERNAL BLOCKED` | written provider/exchange distribution authority and per-user entitlement policy |
| Public Connector installer | `EXTERNAL BLOCKED` | authorized Authenticode signing tool/material |
| Legal publication | `IN DEVELOPMENT` | DRAFT until owner/legal decisions and counsel review |

## Next development boundary

The beta.79 release is closed. The next development stage should start from a
clean `main` after this housekeeping pass resolves local WIP, obsolete PRs,
old worktrees and stale stashes. Future performance work must begin with a
measured hotspot and preserve the accepted beta.79 Connector and market-data
baselines.

## Canonical evidence

- [beta.79 secret management and cancel closeout](../changelog/2026-08-29-beta79-secret-management-and-cancel-closeout.md)
- [current clean closeout](../current/CLEAN_CLOSEOUT_HANDOFF.md)
- [environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and worker queues](07_AI_AGENTS_AND_AUTOMATION.md)
- [market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-27T22:33:11Z | GPT-5.5 через Codex по запросу owner | Replaced the completed beta.48 handoff with exact beta.61 worker scheduling, test, live measurement, immutable release and bounded residual-attribution evidence.
2026-08-30T02:05:00Z | GPT-5.5 через Codex по запросу owner | Housekeeping sync to beta.79 and marked remaining work as repository cleanup only.
-->
