# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-13T04:59:15Z
- Verified against Git SHA: cad53f682e413db86bc3a77e57f8942baf4d4bc3
- Scope: Current factual subsystem snapshot only
- Status: DONE
- Current Production version/build/artifact when known: repository evidence snapshot is `cad53f682e413db86bc3a77e57f8942baf4d4bc3`; operational release evidence says Production runs `0.10.0-beta.1`, artifact git `6b6dc4589407855526cf6cc345376d64cf95200e`, build `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256 `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`, archive SHA256 `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730`, previous slot `0.10.0-beta.1-795db0c1`.

## Evidence modes

- **Repository evidence** in this pack means current code/schema/config/docs
  snapshot `cad53f682e413db86bc3a77e57f8942baf4d4bc3`.
- **Operational evidence** means the last accepted live release/deployment
  closeout, currently
  [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md).
- If the repository and the live environment answer different questions, this
  file says which evidence mode it is using instead of pretending they are the
  same thing.

## Current-only snapshot

| Подсистема | Status | Что реально работает сейчас | PARTIAL / EXTERNAL BLOCKED / лимиты | Compact evidence |
| --- | --- | --- | --- | --- |
| Auth | `PARTIAL` | repository: Telegram / Google / email / UUID identity paths exist in code and schema. operational: Production `login/start` via Telegram is working; local DEV owner session is working | Canary Telegram remains `disabled_pending_canary_bot_provisioning`; Google and email are operationally `EXTERNAL BLOCKED` in Production until external provider config exists; DEV test auth is not Production acceptance | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `app/account_auth.py`, `app/auth_identity.py`, `app/production_storage/migrations/0005_identity_uuid.sql`, [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Users / workspaces | `PARTIAL` | active workspace, memberships, owner-training vs personal-runtime split, bridge pairing contracts | broader entitlement/subscription/commercial rollout is incomplete | [../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md](../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md), `app/workspaces.py`, `app/production_storage/migrations/0001_authoritative_storage.sql` |
| DEV / CANARY / PRODUCTION | `PARTIAL` | repository: env/channel split is canonical, startup is fail-closed, origins are separated by contract. operational: DEV `[DEV]`, CANARY `[CANARY]` and PRODUCTION `[BETA]` were all accepted on the `6b6dc458` release snapshot with separate origins | Canary Telegram is still partial and external provider auth on Production is still blocked; future deployments still need fresh operational closeout evidence | [../adr/0001-environments-and-release-identity.md](../adr/0001-environments-and-release-identity.md), `app/runtime_env.py`, [../../README-RUN-MODES.md](../../README-RUN-MODES.md), [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Admin | `PARTIAL` | capability catalog, server-side permission resolver, owner-only modules and Environment Switcher UI exist | separate polished Admin Panel shell continues to evolve | [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md), `app/permissions.py`, `app/static/aurora/assets/ui.js` |
| Release Center | `PARTIAL` | repository: candidate/artifact/deployment/check/approval/rollback state machine and blue-green step log exist. operational: the exact-artifact path was actually used for `6b6dc458`, Canary first and the same release directory to Production | the in-app Release Center still should not be described as a fully closed operator workflow just because the host closeout succeeded once | `app/release_center.py`, `app/blue_green.py`, `app/production_storage/migrations/0009_release_center.sql`, `0010_blue_green_deploy_steps.sql`, [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Connector | `PARTIAL` | pair/enroll/challenge/hello/heartbeat/market-data/commands protocol is implemented with P-256 device identity | real Production acceptance still depends on a real Windows VM and published endpoint | [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md), `app/connector_protocol.py` |
| NinjaTrader | `PARTIAL` | remains the source of truth for compilation, backtests, fills, trades, runtime state and actual Simulation vs real/live account mode | specific actions against a real/live account remain gated by permissions, safety, release and account capability; accepted 2026-08-12 closeout placed no orders | [../../README.md](../../README.md), [../operations/manual-validation.md](../operations/manual-validation.md), `app/server.py`, [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Market data / TopstepX | `PARTIAL` | TopstepX is the primary independent read-only chart feed; fresh NinjaTrader Connector is current fallback | 100-user load, licensed-provider parity and full Production failover acceptance are still pending | [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md), `app/market_data_failover.py`, `app/market_data_live_adapters.py` |
| Charts | `DONE` | Aurora Desktop charts work with provider provenance and no synthetic candles | visual acceptance should still be rerun after major chart-engine changes | `app/market_data_ws_http.py`, `app/static/aurora/assets/pages/desktop.js`, `app/static/aurora/assets/chart-engine.js` |
| AI agents | `PARTIAL` | Vitek, Orchestrator, management tiers, specialist agents and TTS profiles are live in the product surface | per-workspace personal agent-team architecture and some automation boundaries remain incomplete | [../agents/AGENTS.md](../agents/AGENTS.md), `app/ai_lab/chief_agent.py`, `app/ai_lab/domain_agents.py`, `app/vitek.py` |
| Documents | `PARTIAL` | governance source, rendered docs, document revision schema and documents UI exist | this new pack and future enforcement are needed to keep external current-state context synchronized | [../DOCUMENTATION_GOVERNANCE.md](../DOCUMENTATION_GOVERNANCE.md), `app/governance.py`, `app/production_storage/migrations/0011_document_specifications.sql` |
| Telegram | `PARTIAL` | paired bot, Mini App auth, notifications and mirrored conversations exist. operational: Production Telegram login/start is available | separate Canary bot remains unprovisioned; Mini App does not grant real/live execution authority | [../../README.md](../../README.md), `app/telegram_service.py`, [../architecture/TELEGRAM_MINI_APP.md](../architecture/TELEGRAM_MINI_APP.md), [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Security | `PARTIAL` | sessions, CSRF, device registry schema, security challenges and step-up actions exist | full trusted-device lifecycle UX and hard enforcement on every critical action are not yet uniformly complete | [../adr/0003-trusted-devices-and-step-up.md](../adr/0003-trusted-devices-and-step-up.md), `app/security_devices.py`, `app/personal_nt_security.py`, `app/production_storage/migrations/0006_trusted_devices.sql`, `0007_step_up_actions.sql` |
| Deployment | `PARTIAL` | signed build scripts, preflight checks, canary/production runbooks and blue-green schema exist. operational: `6b6dc458` / `0.10.0-beta.1` was accepted on Canary and promoted to Production from the same release directory; readiness fix is live and fast | future deployments still require their own accepted closeout; Canary Telegram remains partial and some provider/auth acceptance remains blocked | `tools/build_server_release.py`, `tools/production_preflight.py`, [../../deploy/production/README.md](../../deploy/production/README.md), [../../../.github/workflows/next-architecture-ci.yml](../../../.github/workflows/next-architecture-ci.yml), [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Legal | `IN DEVELOPMENT` | a structured legal document set exists and is mapped to product data-flow | package is still DRAFT and requires owner placeholders plus counsel review before publication | [../legal/README.md](../legal/README.md) |

## Important current limitations

- Repository evidence and operational evidence answer different questions; use
  the accepted live release snapshot for current deployed state, not only the
  code tree.
- Google and email auth are still `EXTERNAL BLOCKED` in Production despite code
  and schema support.
- Connector Production acceptance, licensed-provider market-data acceptance and
  some trusted-device/release flows still depend on further external execution evidence.

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