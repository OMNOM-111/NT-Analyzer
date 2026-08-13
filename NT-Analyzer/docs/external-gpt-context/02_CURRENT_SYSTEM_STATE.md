# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-13T02:25:57Z
- Verified against Git SHA: c4711ae3f876966f6bedcba8fc3b4ad9c309c836
- Scope: Current factual subsystem snapshot only
- Status: DONE
- Current Production version/build/artifact when known: public version is `0.10.0-beta.1` from `VERSION.json`; current deployed Production artifact/SHA/slot is not provable from repository evidence alone.

## Current-only snapshot

| Подсистема | Status | Что реально работает сейчас | PARTIAL / EXTERNAL BLOCKED / лимиты | Compact evidence |
| --- | --- | --- | --- | --- |
| Auth | `PARTIAL` | Telegram login, profile/session surfaces, Google and UUID identity layer exist in code and schema | Production-grade email delivery and fully polished account-link UX should be treated as incomplete until explicitly evidenced in deployment | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `app/account_auth.py`, `app/auth_identity.py`, `app/production_storage/migrations/0005_identity_uuid.sql` |
| Users / workspaces | `PARTIAL` | active workspace, memberships, owner-training vs personal-runtime split, bridge pairing contracts | broader entitlement/subscription/commercial rollout is incomplete | [../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md](../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md), `app/workspaces.py`, `app/production_storage/migrations/0001_authoritative_storage.sql` |
| DEV / CANARY / PRODUCTION | `PARTIAL` | env/channel split is canonical, startup is fail-closed, origins are separated by contract | repo does not prove the currently deployed live build in Canary or Production | [../adr/0001-environments-and-release-identity.md](../adr/0001-environments-and-release-identity.md), `app/runtime_env.py`, [../../README-RUN-MODES.md](../../README-RUN-MODES.md) |
| Admin | `PARTIAL` | capability catalog, server-side permission resolver, owner-only modules and Environment Switcher UI exist | separate polished Admin Panel shell continues to evolve | [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md), `app/permissions.py`, `app/static/aurora/assets/ui.js` |
| Release Center | `PARTIAL` | candidate/artifact/deployment/check/approval/rollback state machine and blue-green step log exist | same-artifact promotion is modeled; live deployment evidence is not proven from repo alone | `app/release_center.py`, `app/blue_green.py`, `app/production_storage/migrations/0009_release_center.sql`, `0010_blue_green_deploy_steps.sql` |
| Connector | `PARTIAL` | pair/enroll/challenge/hello/heartbeat/market-data/commands protocol is implemented with P-256 device identity | real Production acceptance still depends on a real Windows VM and published endpoint | [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md), `app/connector_protocol.py` |
| NinjaTrader | `PARTIAL` | remains the source of truth for compilation, backtests, fills, trades and runtime state | public live execution is still gated and should not be described as generally available | [../../README.md](../../README.md), [../operations/manual-validation.md](../operations/manual-validation.md), `app/server.py` |
| Market data / TopstepX | `PARTIAL` | TopstepX is the primary independent read-only chart feed; fresh NinjaTrader Connector is current fallback | 100-user load, licensed-provider parity and full Production failover acceptance are still pending | [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md), `app/market_data_failover.py`, `app/market_data_live_adapters.py` |
| Charts | `DONE` | Aurora Desktop charts work with provider provenance and no synthetic candles | visual acceptance should still be rerun after major chart-engine changes | `app/market_data_ws_http.py`, `app/static/aurora/assets/pages/desktop.js`, `app/static/aurora/assets/chart-engine.js` |
| AI agents | `PARTIAL` | Vitek, Orchestrator, management tiers, specialist agents and TTS profiles are live in the product surface | per-workspace personal agent-team architecture and some automation boundaries remain incomplete | [../agents/AGENTS.md](../agents/AGENTS.md), `app/ai_lab/chief_agent.py`, `app/ai_lab/domain_agents.py`, `app/vitek.py` |
| Documents | `PARTIAL` | governance source, rendered docs, document revision schema and documents UI exist | this new pack and future enforcement are needed to keep external current-state context synchronized | [../DOCUMENTATION_GOVERNANCE.md](../DOCUMENTATION_GOVERNANCE.md), `app/governance.py`, `app/production_storage/migrations/0011_document_specifications.sql` |
| Telegram | `PARTIAL` | paired bot, Mini App auth, notifications and mirrored conversations exist | live trading via Mini App is blocked; separate Canary bot identity is not proven live from repo | [../../README.md](../../README.md), `app/telegram_service.py`, [../architecture/TELEGRAM_MINI_APP.md](../architecture/TELEGRAM_MINI_APP.md) |
| Security | `PARTIAL` | sessions, CSRF, device registry schema, security challenges and step-up actions exist | full trusted-device lifecycle UX and hard enforcement on every critical action are not yet uniformly complete | [../adr/0003-trusted-devices-and-step-up.md](../adr/0003-trusted-devices-and-step-up.md), `app/security_devices.py`, `app/personal_nt_security.py`, `app/production_storage/migrations/0006_trusted_devices.sql`, `0007_step_up_actions.sql` |
| Deployment | `PARTIAL` | signed build scripts, preflight checks, canary/production runbooks and blue-green schema exist | current deployed artifact/version/slot is unknown from repo alone | `tools/build_server_release.py`, `tools/production_preflight.py`, [../../deploy/production/README.md](../../deploy/production/README.md), [../../../.github/workflows/next-architecture-ci.yml](../../../.github/workflows/next-architecture-ci.yml) |
| Legal | `IN DEVELOPMENT` | a structured legal document set exists and is mapped to product data-flow | package is still DRAFT and requires owner placeholders plus counsel review before publication | [../legal/README.md](../legal/README.md) |

## Important current limitations

- The repo proves architecture, code paths and schemas better than it proves any
  currently deployed live environment.
- Live broker automation must still be treated as gated, not as a released
  public feature.
- Connector Production acceptance, licensed-provider market-data acceptance and
  some trusted-device/release flows still depend on external execution evidence.

## Deprecated current-state claims to avoid

- Do not treat old audit gaps around UUID identities or trusted-device schema as
  current facts; migrations `0005` and `0006` now exist.
- Do not treat historical release bundles in sibling folders as proof of the
  current deployed Production build.
- Do not treat DRAFT legal texts as effective published terms.

## Canonical follow-up file

If only one dynamic file is updated after a meaningful task, update
[11_ACTIVE_WORK_AND_HANDOFF.md](11_ACTIVE_WORK_AND_HANDOFF.md) together with this
snapshot.