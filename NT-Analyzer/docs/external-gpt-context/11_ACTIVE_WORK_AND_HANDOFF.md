# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-02T03:42:40Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Development branch implementation SHA: `55523872f2860a3a21489debe01e160207b0b288` (PR #270; latest owner-review UI pass; not deployed)
- Verified deployed artifact Git SHA: `8f42158661e8247832c90bea8fc4d9f0071e647b`
- Current Production version/build/artifact when known: `0.10.0-beta.87`; `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`
- Scope: beta.87 live baseline plus isolated Community/SF Chat Development branch
- Status: PARTIAL

## Active isolated development — Community / SF Chat

- Worktree: isolated Community/SF Chat checkout; local absolute paths are intentionally omitted.
- Branch: `codex/community-social-network`; implementation:
  `55523872f2860a3a21489debe01e160207b0b288`; PR #270.
- Community owns profiles, privacy/social graph, feed/search/interactions,
  moderation and existing Channels. SF Chat owns the only new human conversation
  state. Community does not contain a second DM subsystem.
- The SF Chat UI facade combines human conversations with existing AI
  conversations; AI Orchestrator storage/routing remains unchanged.
- Server-attested publishing currently covers completed Demo/Backtest results.
  Strategy, Chart and Live result adapters remain visibly disabled.
- The approved-reference presentation uses a compact social dock, dominant
  rich-object feed, compact composer and full profile/wall panel. The latest
  owner-review pass removes unused view icons, adds explicit Like/Comments/
  Share/Bookmark actions, independent center/wall scrolling, a compact
  profile-visibility dialog and a restrained cosmic SF Chat launcher. Isolated
  browser QA passed at desktop, tablet and mobile sizes without document-level
  horizontal overflow or new console warnings/errors.
- Production path uses fail-closed PostgreSQL documents plus migrations
  `0020`/`0021` (allowlist, FK/index/FORCE-RLS mirrors). A checksum-confirmed,
  backup-first idempotent legacy importer exists but was not run against any
  environment.
- PR #270 required CI reached `5/5 PASS` at the pre-refinement `d3fa41bc`
  checkpoint. The UI refinement needs fresh PR checks after push, and merge
  still requires owner approval.
- No Backtest/Connector, market-data, trading, future `МИР АГЕНТОВ`, Canary or
  Production action belongs to this branch.

## Release closeout - beta.87 live

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
| Current Git SHA | `8f42158661e8247832c90bea8fc4d9f0071e647b` (deployed beta.87 baseline) |
| Development Git implementation | `f475568475290df2161da9b6fe5da3b73342939b` on `codex/community-social-network`; PR #270; not deployed |
| Deployed Git SHA | `8f42158661e8247832c90bea8fc4d9f0071e647b` (beta.87) |
| Code change | PR #254 legacy isolation; PR #255 Telegram `/start` URL flow; PR #256 release-record visibility and gate |
| Release | Production `0.10.0-beta.87`, state `production_live` |
| Build | live `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`; artifact `art_9ce9dbcb9a7a4fee9df6a54d40f29806` |
| Archive / runtime hashes | archive `8052B7A5...BABE7D`, manifest `0E95CF8B...BCA4`; full values in the beta.87 changelog |
| Canary | beta.87 accepted/ready |
| Production | beta.87 same immutable artifact without rebuild, live/ready |
| Release parity | Canary and Production report the same beta.87 artifact SHA256 |
| Worker concurrency | `interactive_ai=4`, `chart=4`, `telemetry=2`, `maintenance=1` |
| Canary idle result | CPU `83.711% → 4.839%`; total DB TX/s `155.378 → 28.700`; pickup p50/max `1.372/1.455 s` |
| Production idle result | worker CPU `83.778% → 5.522%`; worker-attributable TX/s about `69.002 → 5.822`; pickup p50/max `1.392/1.468 s` |
| Tests | legacy-isolation full regression `2430 passed, 34 skipped`; PR #255 focused `94 passed`; both merged PRs mandatory CI GREEN; beta.87 full suite `2449 passed, 32 skipped` |
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
| Community trusted object adapters | `IN DEVELOPMENT` | Demo/Backtest result snapshot is implemented; Strategy, Chart and Live result require their own server-side ownership adapters |
| Community acceptance | `IN DEVELOPMENT` | Automated regression and isolated desktop/tablet/mobile browser QA are PASS; credentialed PostgreSQL tests, owner visual acceptance, owner-approved merge, clean-main integration and Canary/Production are not yet complete |

## Next development boundary

Run credentialed PostgreSQL and owner visual acceptance when those gates are
available, then merge PR #270 only after owner approval and clean-main
integration. Any release must build one signed immutable artifact after merge,
accept it on Canary and promote that exact artifact to Production. Preserve the
accepted Connector, Backtest, market-data and AI Orchestrator baselines.

## Canonical evidence

- [beta.79 secret management and cancel closeout](../changelog/2026-08-29-beta79-secret-management-and-cancel-closeout.md)
- [current clean closeout](../current/CLEAN_CLOSEOUT_HANDOFF.md)
- [environments and release](04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and worker queues](07_AI_AGENTS_AND_AUTOMATION.md)
- [market data and Connector](06_MARKET_DATA_TRADING_CONNECTOR.md)
- [Community/SF Chat Development record](../changelog/2026-09-01-community-sf-chat-development.md)
