# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-13T09:49:37Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Current factual subsystem snapshot only
- Status: DONE
- Current Production version/build/artifact when known: repository evidence snapshot is `7ebda6faf2e7c64d4a707a41062b29857882181a`; Production remains on `0.10.0-beta.1`, artifact git `6b6dc4589407855526cf6cc345376d64cf95200e`, build `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256 `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`, archive SHA256 `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730`, previous slot `0.10.0-beta.1-795db0c1`. Canary runs the newer accepted `7ebda6fa` artifact recorded below; it has not been promoted to Production.

## Evidence modes

- **Repository evidence** in this pack means current code/schema/config/docs
  snapshot `7ebda6faf2e7c64d4a707a41062b29857882181a`.
- **Operational evidence** means the latest environment-specific accepted
  release/deployment closeout: current Canary is
  [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md), while current
  Production remains the
  [2026-08-12 snapshot](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md).
- If the repository and the live environment answer different questions, this
  file says which evidence mode it is using instead of pretending they are the
  same thing.

## Current-only snapshot

| Подсистема | Status | Что реально работает сейчас | PARTIAL / EXTERNAL BLOCKED / лимиты | Compact evidence |
| --- | --- | --- | --- | --- |
| Auth | `PARTIAL` | repository: Telegram / Google / email / UUID identity paths exist in code and schema. operational: Production `login/start` via Telegram is working; local DEV owner session is working. Canary owner login now supports `[CANARY]`/`canary_login_*` shared-webhook forwarding into the isolated Canary auth/session store | Live Canary PASS still requires deploying the auth hotfix artifact and host consumer/env readiness; Google and email are operationally `EXTERNAL BLOCKED` in Production until external provider config exists; DEV test auth is not Production acceptance | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `app/account_auth.py`, `app/auth_identity.py`, `app/production_storage/migrations/0005_identity_uuid.sql`, [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Users / workspaces | `PARTIAL` | active workspace, memberships, owner-training vs personal-runtime split, bridge pairing contracts | broader entitlement/subscription/commercial rollout is incomplete | [../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md](../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md), `app/workspaces.py`, `app/production_storage/migrations/0001_authoritative_storage.sql` |
| DEV / CANARY / PRODUCTION | `BETA` | env/channel split is fail-closed. DEV ran clean `7ebda6fa`; Canary runs a signed beta artifact after real blue-green acceptance; Production remains separately on `6b6dc458` | Authenticated Canary/Production chart smoke remains external; Canary owner-login hotfix needs live redeploy; Production promotion needs a separate owner answer | [../adr/0001-environments-and-release-identity.md](../adr/0001-environments-and-release-identity.md), `app/runtime_env.py`, [../../README-RUN-MODES.md](../../README-RUN-MODES.md), [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |
| Admin | `PARTIAL` | capability catalog, server-side permission resolver, owner-only modules and Environment Switcher UI exist | separate polished Admin Panel shell continues to evolve | [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md), `app/permissions.py`, `app/static/aurora/assets/ui.js` |
| Release Center | `BETA` | owner-facing UI now completes clean candidate, protected signed build, verify, real Canary deployment, structured acceptance checks and real rollback→re-promote. Exact fingerprint is immutable | Production approval and process gate remain intentionally separate; notification delivery still depends on environment infrastructure | `app/release_center.py`, `app/release_executor.py`, `app/blue_green.py`, [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |
| Connector | `PARTIAL` | pair/enroll/challenge/hello/heartbeat/market-data/commands protocol is implemented with P-256 device identity | real Production acceptance still depends on a real Windows VM and published endpoint | [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md), `app/connector_protocol.py` |
| NinjaTrader | `PARTIAL` | remains the source of truth for compilation, backtests, fills, trades, runtime state and actual Simulation vs real/live account mode | specific actions against a real/live account remain gated by permissions, safety, release and account capability; accepted 2026-08-12 closeout placed no orders | [../../README.md](../../README.md), [../operations/manual-validation.md](../operations/manual-validation.md), `app/server.py`, [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Market data / TopstepX | `BETA` | TopstepX is the primary independent read-only chart feed; fresh NinjaTrader Connector remains fallback. DEV fanout/load reached 100 concurrent chart/API clients without extra upstream loginKey/SignalR sessions | authenticated Canary/Production licensed-provider and full failover acceptance remain external; external feed never grants order authority | [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md), `app/market_data_failover.py`, `app/market_data_live_adapters.py`, [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |
| Charts | `DONE` | Aurora Desktop charts work with provider provenance and no synthetic candles. Final clean-SHA browser proof: MNQ/MES 5m, independent in-app and Chrome clients, `619.899 s`, `44` observations, `0` grey/OFF/non-live states; live marker direction remained independent of candle colour | authenticated server-environment chart smoke still needs real user auth | `app/market_data_ws_http.py`, `app/static/aurora/assets/pages/desktop.js`, `app/static/aurora/assets/chart-engine.js`, [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |
| AI agents | `PARTIAL` | Vitek, Orchestrator, management tiers, specialist agents and TTS profiles are live in the product surface | per-workspace personal agent-team architecture and some automation boundaries remain incomplete | [../agents/AGENTS.md](../agents/AGENTS.md), `app/ai_lab/chief_agent.py`, `app/ai_lab/domain_agents.py`, `app/vitek.py` |
| Documents | `PARTIAL` | governance source, rendered docs, document revision schema and documents UI exist | this new pack and future enforcement are needed to keep external current-state context synchronized | [../DOCUMENTATION_GOVERNANCE.md](../DOCUMENTATION_GOVERNANCE.md), `app/governance.py`, `app/production_storage/migrations/0011_document_specifications.sql` |
| Telegram | `PARTIAL` | paired bot, Mini App auth, notifications and mirrored conversations exist. operational: Production Telegram login/start is available. Canary owner login can reuse the existing bot via shared-webhook forwarding and a Canary-only queue/consumer | live Canary verification waits for hotfix redeploy and host env/consumer readiness; Mini App does not grant real/live execution authority | [../../README.md](../../README.md), `app/telegram_service.py`, [../architecture/TELEGRAM_MINI_APP.md](../architecture/TELEGRAM_MINI_APP.md), [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Security | `PARTIAL` | sessions, CSRF, device registry schema, security challenges and step-up actions exist | full trusted-device lifecycle UX and hard enforcement on every critical action are not yet uniformly complete | [../adr/0003-trusted-devices-and-step-up.md](../adr/0003-trusted-devices-and-step-up.md), `app/security_devices.py`, `app/personal_nt_security.py`, `app/production_storage/migrations/0006_trusted_devices.sql`, `0007_step_up_actions.sql` |
| Deployment | `BETA` | protected signer, immutable artifacts, real Canary blue-green, identity/readiness verification and real rollback rehearsal are available from Release Center. Canary=`7ebda6fa`; Production=`6b6dc458` | Production promotion is `EXTERNAL BLOCKED` until the owner explicitly approves this exact artifact; Canary Telegram and authenticated provider smoke remain external | `tools/build_server_release.py`, `app/release_executor.py`, `tools/stage9_remote_release.sh`, [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |
| Legal | `IN DEVELOPMENT` | a structured legal document set exists and is mapped to product data-flow | package is still DRAFT and requires owner placeholders plus counsel review before publication | [../legal/README.md](../legal/README.md) |

## Important current limitations

- Repository evidence and operational evidence answer different questions; use
  the accepted live release snapshot for current deployed state, not only the
  code tree.
- Google and email auth are still `EXTERNAL BLOCKED` in Production despite code
  and schema support.
- Authenticated Canary/Production Connector and licensed-provider chart smoke,
  plus some trusted-device flows, still depend on real external authentication
  or hardware evidence. Canary Telegram no longer requires a separate bot in
  code, but the owner-login hotfix still needs live redeploy before PASS.

## Deprecated current-state claims to avoid

- Do not treat old audit gaps around UUID identities or trusted-device schema as
  current facts; migrations `0005` and `0006` now exist.
- Do not treat older “current live build unknown” wording as current truth; the
  latest accepted live closeout is now captured in canonical operational docs.
- Do not treat DRAFT legal texts as effective published terms.

## Canonical follow-up file

If only one dynamic file is updated after a meaningful task, update
[11_ACTIVE_WORK_AND_HANDOFF.md](11_ACTIVE_WORK_AND_HANDOFF.md) together with this
snapshot.
