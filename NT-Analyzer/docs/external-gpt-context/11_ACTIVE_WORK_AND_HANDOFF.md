# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-01T00:00:00Z
- Verified against Git SHA: 22ed7097b4ac9e863304197e118b1d3ce5109e8a
- Verified deployed artifact Git SHA: `22ed7097b4ac9e863304197e118b1d3ce5109e8a`
- Current Production version/build/artifact when known: `0.10.0-beta.86`; `sf-0.10.0-beta.86-22ed7097b4ac-20260901T005018Z`
- Scope: beta.86 Legacy Isolation + Telegram Bot Cleanup release
- Status: DONE

## Release closeout - beta.86 live

- Current Aurora has no classic UI or Telegram Mini App navigation/transport.
- Retired legacy, Mini App, remote-access and tunnel routes return HTTP 410.
- Classic assets run only in a localhost-only read-only Legacy Viewer using an
  isolated snapshot; current Telegram login, identity, bot and notifications
  remain supported.
- No historical report, audit record or user identity was deleted. Canary and
  Production were not changed; their release identity below remains historical
  operational truth until a separately approved promotion.
- Release Center now requires and displays the canonical release/change record;
  Production is fail closed without title, summary, source SHA and verification
  PASS.

## Current checkpoint

| Field | Value |
| --- | --- |
| Current Git SHA | `22ed7097b4ac9e863304197e118b1d3ce5109e8a`; deployed artifact is the same SHA |
| Code change | PR #254 legacy isolation; PR #255 Telegram `/start` URL flow; PR #256 release-record visibility and gate |
| Release | Production `0.10.0-beta.86`, state `production_live` |
| Build | live `sf-0.10.0-beta.86-22ed7097b4ac-20260901T005018Z`; artifact `art_e627d14a2dbb49fdaf98a0cc9847e8c2` |
| Archive / runtime hashes | archive `8052B7A5...BABE7D`, manifest `0E95CF8B...BCA4`; full values in the beta.86 changelog |
| Canary | beta.86 accepted/ready |
| Production | beta.86 same immutable artifact without rebuild, live/ready |
| Release parity | Canary and Production report the same beta.86 artifact SHA256 |
| Worker concurrency | `interactive_ai=4`, `chart=4`, `telemetry=2`, `maintenance=1` |
| Canary idle result | CPU `83.711% → 4.839%`; total DB TX/s `155.378 → 28.700`; pickup p50/max `1.372/1.455 s` |
| Production idle result | worker CPU `83.778% → 5.522%`; worker-attributable TX/s about `69.002 → 5.822`; pickup p50/max `1.392/1.468 s` |
| Tests | legacy-isolation full regression `2430 passed, 34 skipped`; PR #255 focused `94 passed`; both merged PRs mandatory CI GREEN; beta.86 checks pending |
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
| Legal package deployment | `IN DEVELOPMENT` | Official agreement `2026-08-30-v2`, public endpoint isolation, AI provenance policy and release governance are implemented in Development; immutable Canary/Production promotion remains separate. Live Trading is unavailable |

## Next development boundary

The active task is the beta.86 release. Complete its release-record PR and
final-main CI, build one signed immutable artifact, accept it on Canary and
promote that exact artifact to Production. Preserve the accepted Connector and
market-data baselines.

## Canonical evidence

- [beta.79 secret management and cancel closeout](../changelog/2026-08-29-beta79-secret-management-and-cancel-closeout.md)
- [current clean closeout](../current/CLEAN_CLOSEOUT_HANDOFF.md)
- [environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and worker queues](07_AI_AGENTS_AND_AUTOMATION.md)
- [market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)
