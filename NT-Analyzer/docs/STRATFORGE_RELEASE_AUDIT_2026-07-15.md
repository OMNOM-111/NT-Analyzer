# StratForge release audit — BLOCKED

Date: 2026-07-16 (America/Los_Angeles), final repeat audit
Branch: `codex/stratforge-release-20260716`
Release base commit: `73e005e038f91b5766193004705a891ee204be0d`
Acceptance status: **BLOCKED — not approved for production release**

Current product-contour addendum (2026-07-18): see
[PRODUCT_MODES_AND_CONTOURS_AUDIT_2026-07-18.md](PRODUCT_MODES_AND_CONTOURS_AUDIT_2026-07-18.md).
It supersedes the former Micro/Scaled Live product path: the current code has a
real pre-shell Student/Professional entry, removes Micro Live entirely and has
isolated staging visual evidence for guest, Student, Community and Professional
rails. Exact TopStep parity and credentialed external acceptance remain separate
from that code/UI PASS.

This is a complete audit of the requested scope, not a declaration that the release is done. The code and automated staging gates below pass, but the mandatory real-browser, real-Google, real-Telegram, NinjaTrader Strategy Analyzer, payment-provider and broker scenarios cannot be truthfully signed off in the current environment. The task explicitly requires missing-credential items to remain `BLOCKED`.

## 1. Results for the nine directions

| # | Direction | Code/API/automated status | Final status |
|---|---|---|---|
| 1 | User sessions and monitoring | Session/device revoke, admin kill, session inventory, monitoring context and audit are implemented and covered. | BLOCKED on manual two-browser-profile E2E. |
| 2 | Working demo | Demo backtests, entitlement path, scoped jobs and non-blurred demo flow are covered. | BLOCKED on visual/manual E2E. |
| 3 | Practice trading | Wallet-first; bid/ask/last; 1m/5m/15m/1h; market/limit, Buy/Sell, SL/TP, addressable close/cancel, virtual buying power, source/freshness/recovery and isolated ledger are implemented. | Code/headless production QA PASS; BLOCKED only on human visual/mobile E2E. |
| 4 | Community | Workspace isolation, finite metrics, idempotent posting and separate Telegram mirror routing are implemented. | BLOCKED: the primary Telegram bot works, but separate `NTA_COMMUNITY_TELEGRAM_CHAT_ID` is absent. |
| 5 | Telegram login + Google/Telegram NT step-up | Server-side `google_sub`, unique Google identity, session-bound fresh Telegram step-up, revoke and direct-API gates are covered. Non-NT surfaces remain available without Google. Read-only live Telegram bot/webhook/owner-chat probes pass. | BLOCKED: real Google OAuth is absent and the complete browser login/step-up scenario was not executed. |
| 6 | Staging, virtual users and impersonation | Environment-specific roots, production startup hard-fails for test-auth/impersonation/rate-limit bypass, and production operations are fail-closed. | Automated PASS; manual browser role matrix BLOCKED. |
| 7 | Micro/Scaled Live | Staging simulator, separate ledger, verified-result contracts and risk gates are implemented. Production UI now explicitly reports `coming_soon`, `available=false`, `real_money=false` without adapters/flags. | BLOCKED: no approved payment/broker adapter, credentials or written live-operation authorization. Not claimed as a finished real-money product. |
| 8 | AI ratings | Canonical role/model/pair aggregates, idempotent upsert, workspace-scoped routing and fulfillment penalties are covered. | Automated PASS; real provider/manual UI scenario BLOCKED. |
| 9 | Beginner/Professional modes | Navigation and direct API enforcement, safe upgrades/downgrades and data preservation are covered. | Automated PASS; manual responsive/profile matrix BLOCKED. |

The previously recorded architecture risk is closed in code: interactive Orchestrator/domain-agent calls now enqueue workspace- and user-scoped durable jobs, synchronous and SSE endpoints only wait/poll those jobs, and stable request ids make replay idempotent. Large chart computations also leave the HTTP handler and run as durable worker jobs. The worker provides leases, heartbeat renewal, timeout, cancellation, bounded retry, stale recovery and a process supervisor.

The separate market-data risk is also closed in code: durable queue is not treated as a provider. NinjaTrader remains primary; Databento HTTP is the credentialed independent adapter and Yahoo Chart is the no-key chart-only fallback. Bars are normalized, checked for freshness/gaps and merged by timestamp with primary collision priority and no invented OHLCV bars. Production stop/restart testing proved NT-off bars+PNG and automatic return to the resolved current contract.

## 2. Changed files and migrations

Release-scope implementation files:

- Auth, tenancy and permissions: `app/account_auth.py`, `app/google_auth.py`, `app/permissions.py`, `app/server.py`, `app/test_auth.py`, `app/workspaces.py`, `app/subscriptions.py`.
- Environment/data isolation: `app/runtime_env.py`, `app/account_ledger.py`, `app/portfolio_registry.py`, `app/jobqueue.py`, `app/ops.py`, `app/runtime.py`, `app/local_secrets.py`, `app/secure_store.py`, `app/integrations.py`, `app/in_app_notifications.py`, `app/admin_journal.py`, `app/user_support.py`, `app/vitek.py`, `app/market_data.py`, `app/market_data_failover.py`, `app/market_events.py`, `app/market_news.py`, `app/governance.py`, `app/tunnel_manager.py`, `app/strategy_recovery.py`.
- Product directions: `app/demo_backtest.py`, `app/practice_trading.py`, `app/community.py`, `app/micro_live.py`, `app/telegram_remote.py`, `app/telegram_service.py`.
- AI ratings/routing: `app/ai_lab/agent_registry.py`, `app/ai_lab/agent_router.py`, `app/ai_lab/ai_ratings.py`, `app/ai_lab/chief_agent.py`, `app/ai_lab/cloud_agents.py`, `app/ai_lab/paths.py`.
- Durable work: `app/durable.py`, `app/local_worker.py`.
- Aurora/UI contracts: `app/static/aurora/*.html`, `app/static/aurora/assets/api.js`, `app/static/aurora/assets/ui.js`, `app/static/aurora/assets/pages/ai-agents.js`, `community.js`, `micro-live.js`, plus supporting static files.
- Release tooling: `tools/staging_release_probe.py`, `tools/release_static_scan.py`, `tools/ai_worker_http_probe.py`, `tools/worker_supervisor_probe.py`.
- Tests: auth/cabinet/NT dual-auth/phase A/phase D/practice/community/AI/UX/workspaces/permissions/jobqueue/worker/Telegram/market-data/staging-isolation and Aurora contract suites under `tests/`.

Migrations and compatibility work:

- Account/auth store v1 data is normalized to the v2 user/session model; existing users retain professional UX while truly new users can remain pending mode selection.
- Durable SQLite schema v2 adds worker ownership, heartbeat, lease/deadline, cancellation, attempts/retry and workspace indexes using additive migrations.
- Staging mutable stores resolve under a separate staging root; production historical paths remain compatible.
- Jobs, batches, reports, favorites, chats, ratings, practice/community/micro ledgers and worker rows now carry workspace scope. Missing workspace identifiers reject user writes.

The complete original dirty tracked+untracked tree is preserved at safety commit `3019a571de43fccec3e928ee350f5e18de03bb5e` on `codex/stratforge-pre-separation-safety`. The release work was separated on `codex/stratforge-release-20260716` into intentional atomic commits; no original file is unrecoverable and no hard reset/history rewrite was used.

## 3. Exact automated release results

| Command/gate | Result |
|---|---|
| `python -m pytest -q` | **628 passed in 216.65s** on final post-storage/root-resolution HEAD |
| `python -m tests` | **13/13 suites passed** |
| Expanded nine-direction/security/recovery pytest set | **345 passed in 86.38s** |
| `python tools/ai_worker_http_probe.py` | PASS: sync replay, SSE, 20,000-point chart and large batch |
| `python tools/worker_supervisor_probe.py` | PASS: killed worker replaced, leased job retried and succeeded |
| `python -m compileall -q app tests tools` | PASS |
| `node --check` for all `app/static/**/*.js` | **32 files PASS** |
| `dotnet build bridge/NTAnalyzerBridge.csproj --configuration Release --no-restore` | PASS, **0 warnings, 0 errors** |
| `git diff --check` | PASS; line-ending conversion notices only |
| CSP scan | PASS |
| committed-secret pattern scan | PASS |
| Markdown local-link scan | PASS |

The standalone server-error suite intentionally prints simulated tracebacks for the `500` and disk-full cases; it reports all six cases passed.

Current local production runtime was restarted after the final code changes: listener PID `21872`; `/ui/` is HTTP 200 and the unauthenticated API correctly returns the Telegram login gate. Signed Telegram owner HTTP probes pass. NinjaTrader PID `28280` is back in Control Center; heartbeat is fresh (NinjaTrader 8.1.7.2, Bridge 1.3.0). Google OAuth and Community chat remain unconfigured; TopStep is an unavailable safe scaffold; real payments and live orders remain off.

## 4. Required manual role and device matrix

| Profile | Code/API automation | Manual running-app E2E |
|---|---|---|
| Owner | PASS | BLOCKED |
| New user, no mode | PASS | BLOCKED |
| Beginner, no practice wallet | PASS | BLOCKED |
| Beginner, funded practice wallet | PASS | BLOCKED |
| Free professional | PASS | BLOCKED |
| Paid user | PASS | BLOCKED |
| Developer | PASS | BLOCKED |
| User without Google | PASS | BLOCKED |
| Google-linked without fresh Telegram step-up | PASS | BLOCKED |
| Revoked session | PASS | BLOCKED |
| Blocked user | PASS | BLOCKED |

| Surface | Contract/DOM automation | Manual console/network/screenshots |
|---|---|---|
| 1440 px | PASS | BLOCKED |
| 1024 px | PASS | BLOCKED |
| 760 px | PASS | BLOCKED |
| 390 px | PASS | BLOCKED |
| Telegram Mini App | API/auth automation PASS | BLOCKED |
| Second independent browser profile | Not automatable here | BLOCKED |

An authorized in-app Browser attempt captured only the initial unauthenticated login-gate state. A retry initialized `codex-browser-use` and immediately correlated with another Codex Desktop restart, so that runtime is excluded by the workspace stability policy for the remainder of this release. No full role/device matrix or fabricated screenshot is claimed; final visual QA must use a user-controlled Chrome window.

## 5. Load and soak results

Clean staging root, 10 concurrent virtual users, 66.302 seconds:

- Requests: **2133**, all HTTP **200**.
- Error rate: **0/2133 (0%)**; 5xx: **0**; SQLite lock errors: **0**.
- Latency: average **259.163 ms**, p95 **347.122 ms**, max **1090.198 ms**.
- Process CPU: **105.016 s**, CPU/wall ratio **1.584**.
- RSS: **44.45 MB → 52.46 MB**, delta **8.01 MB**.
- Durable queue: **21 succeeded**, including **10/10 durable AI messages**; no stuck rows.
- Telegram-authenticated polling groups: **711**; duplicate actions: **0**.
- Community idempotency confirmations: **10/10**.
- Simulated Micro fills: **10/10**; real payments/orders enabled: **false/false**.
- Workspace isolation: PASS; production sentinel/root unchanged: PASS.
- Injected stale-lease recovery: **180.768 ms**; restarted HTTP listener returned 200 in **74.119 ms**.

Repeat start on the same staging data:

- Requests: **354**, all HTTP **200**, errors/5xx/SQLite locks: **0/0/0**.
- Average/p95/max: **264.694 / 363.070 / 1291.254 ms**.
- Queue resumed at **42 succeeded**; **10/10 durable AI messages** remained exactly-once for the reused user set.
- Worker recovery: **155.054 ms**; HTTP restart: **60.693 ms**, status 200.
- Production guard remained unchanged.

Evidence JSON is retained locally under `.artifacts/staging-reaudit-soak-report.json` and `.artifacts/staging-reaudit-reuse-report.json` (ignored by Git because it contains generated staging state).

Final post-failover staging probe (fresh root, requested 4 concurrent groups; ten scenario users): **489/489 HTTP 200**, error/5xx/SQLite lock counts **0/0/0**, p95 **668.477 ms**, RSS delta **6.56 MB**, workspace isolation PASS, production guard unchanged, 21 durable jobs succeeded, worker stale recovery **159.773 ms**, HTTP restart **54.407 ms**.

## 6. Recovery results

| Failure | Evidence/status |
|---|---|
| Backend/listener restart | PASS in both staging probes. |
| Worker crash/stale lease | PASS; a real worker process was killed, supervisor replaced PID `27728` with `27956`, and the leased job retried and succeeded in **5963.58 ms**. Stale-row recovery also passed. |
| Telegram unavailable/tunnel failure | Automated webhook/tunnel fail-closed and self-heal tests PASS; real network test BLOCKED by credentials. |
| Duplicate Telegram callback/update | Exact-update and message idempotency tests PASS. |
| Expired Telegram step-up | PASS. |
| Admin session kill/revoke | PASS. |
| Foreign-machine DPAPI file | PASS; store is quarantined/fails closed. |
| Corrupted market snapshot | PASS; degrades to empty state and recovers after a valid snapshot. |
| NinjaTrader stopped | PASS on real production runtime: 180 independent MNQ bars, HTTP 200 PNG snapshot (20,482 bytes), `primary_healthy=false`. |
| NinjaTrader restarted / bare root | PASS: `MNQ` resolved to `MNQ 09-26`; independent response was immediate, then Bridge returned 120 live bars after six seconds with age 0.056 s. |
| Disk exhaustion | PASS; uncaught `ENOSPC` returns HTTP 507 with `code=storage_full`. |
| DPAPI entitlement sharing violation | PASS; transient `PermissionError` is retried with a unique temp file, and the regression test no longer touches production storage. |
| Upgrade over existing data | PASS in the repeated staging probe and additive migration tests. |

## 7. Security and isolation evidence

- Authenticated request context exposes `user_id`, `workspace_id`, `membership_role` and capabilities; tenant writes require workspace scope.
- User A/B isolation is covered for jobs, batches, reports, favorites, chats, ratings, practice/community/micro state and worker jobs.
- Beginner restrictions are enforced by backend permissions, not only hidden navigation.
- Google linkage is resolved from the server store by user id; forged client flags do not satisfy NT dual-auth.
- Staging uses isolated paths and cannot opt into production payments or live orders.
- Production startup rejects test-auth, impersonation and rate-limit bypass flags.
- Subscription tests now always use a temporary encrypted store. Production entitlement writes use writer-unique temp files and bounded retry for transient Windows sharing violations. Five rows proven to have been created by the previously unisolated test during this session were removed after an encrypted backup; all older rows were preserved.
- Community writes are idempotent and use a distinct Telegram destination; they never fall back to the owner chat.
- CSP is present both in Aurora pages and response headers; inline scripts/events and JavaScript URLs are rejected by the release scanner.
- Secret-pattern scan covers tracked and untracked release source/config/document files and passed.

## 8. Screenshots/recordings

**BLOCKED for the full matrix.** One initial unauthenticated state was observed before browser-runtime restart; no full matrix/screenshots are claimed. Supplying fabricated evidence would violate the acceptance criteria.

## 9. Git identity

- Release branch: `codex/stratforge-release-20260716`
- Release base: `73e005e038f91b5766193004705a891ee204be0d`
- Original dirty-tree safety branch/commit: `codex/stratforge-pre-separation-safety` / `3019a571de43fccec3e928ee350f5e18de03bb5e`
- Market failover commits: `62f8c926`, `40101aa8`
- No release commit has been pushed.

## 10. Deploy and rollback

Do not deploy while this audit is `BLOCKED`.

After all blockers are removed:

1. Review the already separated safety/release branches and final atomic commit list.
2. Back up the production data root and DPAPI material before first startup.
3. Configure `NTA_APP_ENV=production`, Google OAuth, Telegram owner/community destinations and approved provider/broker adapters through the secure store/environment.
4. Keep `NTA_ENABLE_TEST_AUTH`, `NTA_ENABLE_IMPERSONATION` and `NTA_DISABLE_RATE_LIMIT` unset; keep payment/live-order flags off until the separately authorized test window.
5. Re-run every command in section 3, then run the full manual matrix and Strategy Analyzer comparison.
6. Start the backend, verify `/api/health`, worker health, Telegram delivery, session revoke and read-only NT visibility before enabling any mutation.

Rollback procedure:

1. Disable payment/live-order flags and stop the backend/worker.
2. Restore the prior application commit.
3. Restore the pre-deploy data-root backup if the older build cannot read the migrated auth store; durable schema changes are additive but the backup remains the authoritative rollback boundary.
4. Restart read-only, verify health and workspace isolation, then re-enable ordinary traffic.

## 11. Required personal confirmation

The required sentence is **not signed**, because it would be false. Manual browser/mobile/Telegram/NinjaTrader scenarios and external production integrations were not executed. The only truthful release decision is **BLOCKED**.

### Exact unblock list

1. Provide staging Google OAuth client id/secret and allowed redirect URI.
2. Provide a staging Telegram bot, owner chat and separate Community chat destination.
3. Open the local application in user-controlled Chrome and make two independent profiles available for the remaining visual matrix; do not initialize Codex in-app Browser again.
4. Make NinjaTrader Strategy Analyzer available for the manual comparison of the changed bridge/backtest contract.
5. Provide an approved payment-provider and broker sandbox adapter; real money/order tests still require separate written authorization and limits.
