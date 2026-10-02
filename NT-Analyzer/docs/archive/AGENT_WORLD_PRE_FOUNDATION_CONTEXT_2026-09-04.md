# Historical context before Agent World foundation

Archived on 2026-09-04 from baseline `4ae766ea0c3258a8bb049644ac2afbba6cb89330`.
This is history, not the current Local status. See [current implementation status](../current/AGENT_WORLD_IMPLEMENTATION_STATUS.md).

The external Agent World plan's `c9b2883997bccf4dd3706b0a5afcaee94da6361d`, dirty Preview and `2677 passed` were an earlier snapshot. Preview closed at implementation `42a99a85f164f69c6ddd0edf46859ef005e787e2`, documentation `4ae766ea0c3258a8bb049644ac2afbba6cb89330`, with `173 passed` focused and `2680 passed, 44 skipped` full. Those skips were not verified scenarios.

The former Auth Context Pack described a seven-day initial trial and roughly five-minute pending session. Local beta.96 uses five active-use hours and a two-minute pending session, with permanent/session trust and fresh single-use first-device login proof. Legacy calendar fields are compatibility data; they do not define the new starting grant.

## Original handoff (prose preserved; relative context links rebased)

# 11. Active Work and Handoff

- Context Pack document: 11_ACTIVE_WORK_AND_HANDOFF.md
- Last verified UTC: 2026-09-04T19:05:50Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Unified Local implementation SHA: `42a99a85f164f69c6ddd0edf46859ef005e787e2`
- Development branch: `integration/stratforge-unified-local` (PR #280), version `0.10.0-beta.96`, not deployed
- Verified deployed artifact Git SHA: `8f42158661e8247832c90bea8fc4d9f0071e647b`
- Current Production version/build/artifact when known: `0.10.0-beta.87`; `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`
- Scope: beta.87 live baseline plus unified Local auth, Device Confirmation, SF Social, SF Chat and Owner Preview
- Status: PARTIAL

## Active Unified Local — beta.96

- The current Local build combines the rebuilt login/registration, proof-based
  Device Confirmation, SF Social, SF Chat and isolated Owner Preview. The
  StratForge handle selected at registration is the shared profile/social/chat
  identity; there is no Community-side second registration or DM store.
- Owner Preview remains an isolated loopback process with its own data root,
  cookies and synthetic non-owner identity. It never turns the parent Local
  runtime into a reduced sandbox. `Exit Preview` returned to the original owner
  account and unchanged balance, workspace/runtime data and owner navigation in
  the browser acceptance run; private Local values are intentionally omitted.
- Preview registration is contextual rather than automatic. Profile,
  Telegram, Google, e-mail, OTP and QR each expose their own local synthetic
  action on the real screen. Terms, final profile creation, Device Confirmation
  and permanent/session-only choice remain manual.
- Synthetic actions reuse normal auth state: Telegram login challenge, Google
  staged registration, e-mail OTP and `/api/auth/register/complete`. Provider
  network effects are blocked; the Preview endpoint is `404` in ordinary
  Local and unavailable in Canary/Production.
- Evidence at implementation `42a99a85f164f69c6ddd0edf46859ef005e787e2`:
  focused `173 passed`, full `2680 passed, 44 skipped`, Python/JavaScript/static
  checks PASS, manual browser walkthrough of all providers, QR, both device
  trust modes and Owner Local restore PASS, browser console errors 0.
- No Agent World code or documents were changed by this Preview delta. Agent
  World work starts only as a separate task after this gate and Git closeout.

## Active isolated development — Community / SF Chat

- Worktree: isolated Community/SF Chat checkout; local absolute paths are intentionally omitted.
- Branch: `codex/community-social-network`; implementation:
  `27b4de3d65eb4e1d753302b90fec45c90a51765a`; PR #270.
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
  profile-visibility dialog and a restrained cosmic SF Chat launcher. The latest
  Orbital Glass pass turns the launcher into a full glass/cosmic shell with a
  persistent desktop conversation rail, distinct human/AI bubbles, compact
  header/composer and a mobile drawer. The final messenger pass moves incoming
  avatars outside compact glass bubbles, keeps outgoing messages as right-side
  bubbles, demotes rating/fulfillment fields into a real disclosure and
  strengthens the restrained vector SF mark and launcher trajectory. The final
  sidebar pass adds real-data
  conversation search/count, All/Pinned/Recent views and the existing AI topic
  create-flow without a parallel store or mock rows, while preserving the
  existing Orchestrator history, unread/read, attachments and routing contracts.
  The final orbital-launch pass connects the real desktop shell to its launcher
  with a restrained light trajectory, keeps the launcher outside the panel and
  docks one grouped real notice in the free lower rail. Mobile remains a
  full-screen shell without the desktop decoration. Isolated browser QA
  passed at desktop, tablet and mobile sizes without document-level horizontal
  overflow or new console warnings/errors.
- Production path uses fail-closed PostgreSQL documents plus migrations
  `0020`/`0021` (allowlist, FK/index/FORCE-RLS mirrors). A checksum-confirmed,
  backup-first idempotent legacy importer exists but was not run against any
  environment.
- PR #270 required CI reached `5/5 PASS` after the final sidebar pass at
  `f464d069502a93c3d44c7de35c0cba3a2ba492e4`; merge still requires owner
  approval.
- No Backtest/Connector, market-data, trading, future `МИР АГЕНТОВ`, Canary or
  Production action belongs to this branch.
- Device-confirmation Development implementation SHA: `19e0f43a35bee5a2e396538962e8f24e92bed6ef` (PR #278; isolated branch; not deployed)
- Verified deployed artifact Git SHA: `8f42158661e8247832c90bea8fc4d9f0071e647b`
- Current Production version/build/artifact when known: `0.10.0-beta.87`; `sf-0.10.0-beta.87-8f42158661e8-20260901T030837Z`
- Scope: beta.87 live baseline plus isolated Device Confirmation Development branch
- Status: PARTIAL

## Active isolated development — Device Confirmation / Trusted Access

- Branch: `codex/device-confirmation-trusted-access`; implementation
  `19e0f43a35bee5a2e396538962e8f24e92bed6ef`; PR #278; not deployed.
- The first unknown human browser/app Client receives a server-side pending
  Session with a roughly five-minute deadline. A global guard blocks product
  routes until a session-bound six-digit OTP is confirmed through Telegram or
  verified email.
- The user chooses permanent Client trust or access only for the current auth
  Session. Session-only access is not a 24-hour grant and is not inherited by
  the next login.
- Security now exposes Devices, My sessions and Login history. Rename and
  revoke actions distinguish Machine, Client and Session scope.
- Machine grouping is proof-based: Connector hardware identity or attested
  pairing only. IP, hostname, User-Agent, VPN/location and unsigned remote/AI
  browser labels cannot create a Machine.
- The branch intentionally leaves Community and SF Chat UI, routes, storage and
  business logic unchanged. Shared auth/session changes are limited to the
  confirmation gate and explicit exemptions for non-human development/service
  sessions.
- Canonical checklist and verification evidence:
  [Device Confirmation Development record](../changelog/2026-09-02-device-confirmation-trusted-access.md).

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
| Unified Local implementation | `42a99a85f164f69c6ddd0edf46859ef005e787e2` on `integration/stratforge-unified-local`; PR #280; `0.10.0-beta.96`; not deployed |
| Current Git SHA | `8f42158661e8247832c90bea8fc4d9f0071e647b` (deployed beta.87 baseline) |
| Development Git implementation | `c0bcf7af1a460d52212a596d0cdcfc100aadfacb` on `codex/community-social-network`; PR #270; not deployed |
| Deployed Git SHA | `8f42158661e8247832c90bea8fc4d9f0071e647b` (beta.87) |
| Current Git SHA | `8f42158661e8247832c90bea8fc4d9f0071e647b`; deployed artifact is the same SHA |
| Device-confirmation Development implementation | `19e0f43a35bee5a2e396538962e8f24e92bed6ef` on `codex/device-confirmation-trusted-access`; PR #278; not deployed |
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
| Device Confirmation acceptance | `IN DEVELOPMENT` | Automated Development verification is recorded in its changelog and PR #278 provides per-head CI evidence; real Telegram/email delivery, owner visual acceptance, merge and immutable Canary/Production promotion remain separate gates |

## Next development boundary

For Device Confirmation, require mandatory PR #278 checks plus owner
visual/provider acceptance before an owner-approved merge. Any later release must build one
signed immutable artifact after merge, accept it on Canary and promote that
exact artifact to Production. The deployed beta.87 identity remains unchanged.
Preserve the accepted Connector, Backtest, market-data and AI Orchestrator
baselines.

## Canonical evidence

- [beta.79 secret management and cancel closeout](../changelog/2026-08-29-beta79-secret-management-and-cancel-closeout.md)
- [current clean closeout](../current/CLEAN_CLOSEOUT_HANDOFF.md)
- [environments and release](../../../AI_CONTEXT/04_ENVIRONMENTS_RELEASE_DEPLOYMENT.md)
- [AI agents and worker queues](../../../AI_CONTEXT/07_AI_AGENTS_AND_AUTOMATION.md)
- [market data and Connector](../../../AI_CONTEXT/06_MARKET_DATA_TRADING_CONNECTOR.md)
- [Community/SF Chat Development record](../changelog/2026-09-01-community-sf-chat-development.md)
- [Device Confirmation Development record](../changelog/2026-09-02-device-confirmation-trusted-access.md)
