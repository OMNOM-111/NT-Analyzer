# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-14T06:20:00Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Current factual subsystem snapshot only
- Status: PARTIAL
- Current Production version/build/artifact when known: Canary and Production public `/live` `/ready` `/runtime/env` plus host `canary-current`/`current` and `/proc` cwd for all eight app processes report the same `0.10.0-beta.1` git `1fae1f3966dc53294b73772be47992d844575115`, build `sf-0.10.0-beta.1-1fae1f3966dc-20260814T052203Z`, artifact SHA256 `08265412DECF4D04962A14A0D17208BB7E67031F09AF62FB525634749B6B449B`. Previous slot is `0f2a90ea`. Repository Documents/Charts follow-up is not that live artifact. Local DEV was not listening.

## Evidence modes

- **Repository evidence** in this pack means current code/schema/config/docs
  plus the Documents/Charts follow-up in this change set. Live servers are
  still on `1fae1f3966dc53294b73772be47992d844575115`.
- **Operational evidence** means the latest environment-specific accepted
  closeout plus the 2026-08-14 public HTTP identity
  [../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md](../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md).
  Historical Canary `7ebda6fa` and hang-fix Production `6b6dc458` snapshots
  remain in changelog.
- If the repository and the live environment answer different questions, this
  file says which evidence mode it is using instead of pretending they are the
  same thing.

## Current-only snapshot

| Подсистема | Status | Что реально работает сейчас | PARTIAL / EXTERNAL BLOCKED / лимиты | Compact evidence |
| --- | --- | --- | --- | --- |
| Auth | `PARTIAL` | repository: Telegram / Google / email / UUID identity paths exist. operational: Production Telegram login works; Canary and Production API identity is `1fae1f39`; shared-webhook Canary routing exists in that artifact | Live Canary/Production Documents 500 and server TopstepX chart fallback are repository follow-ups not in `1fae1f39`. Google and email remain `EXTERNAL BLOCKED` in Production | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `app/account_auth.py`, [../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md](../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md) |
| Users / workspaces | `PARTIAL` | active workspace, memberships, owner-training vs personal-runtime split, bridge pairing contracts | broader entitlement/subscription/commercial rollout is incomplete | [../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md](../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md), `app/workspaces.py`, `app/production_storage/migrations/0001_authoritative_storage.sql` |
| DEV / CANARY / PRODUCTION | `BETA` | env/channel split is fail-closed. Canary and Production process identity is `1fae1f39` / same release dir | Authenticated server TopstepX still needs the follow-up artifact; local DEV was not listening; Google/email EXTERNAL BLOCKED | [../adr/0001-environments-and-release-identity.md](../adr/0001-environments-and-release-identity.md), [../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md](../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md) |
| Admin | `PARTIAL` | capability catalog, server-side permission resolver, owner-only modules and Environment Switcher UI exist | separate polished Admin Panel shell continues to evolve | [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md), `app/permissions.py`, `app/static/aurora/assets/ui.js` |
| Release Center | `BETA` | owner-facing UI now completes clean candidate, protected signed build, verify, real Canary deployment, structured acceptance checks and real rollback→re-promote. Exact fingerprint is immutable | Production approval and process gate remain intentionally separate; notification delivery still depends on environment infrastructure | `app/release_center.py`, `app/release_executor.py`, `app/blue_green.py`, [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |
| Connector | `PARTIAL` | pair/enroll/challenge/hello/heartbeat/market-data/commands protocol is implemented with P-256 device identity | real Production acceptance still depends on a real Windows VM and published endpoint | [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md), `app/connector_protocol.py` |
| NinjaTrader | `PARTIAL` | remains the source of truth for compilation, backtests, fills, trades, runtime state and actual Simulation vs real/live account mode | specific actions against a real/live account remain gated by permissions, safety, release and account capability; accepted 2026-08-12 closeout placed no orders | [../../README.md](../../README.md), [../operations/manual-validation.md](../operations/manual-validation.md), `app/server.py`, [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Market data / TopstepX | `BETA` | TopstepX is the primary independent read-only chart feed in DEV. Repository now uses the same order on Canary/Production instead of stubbing bars when NinjaTrader is absent | Live `1fae1f39` still stubs/skips TopstepX on server environments; authenticated server chart PASS needs the follow-up artifact. External feed never grants order authority | [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md), `app/server.py`, `app/workspaces.py`, [../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md](../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md) |
| Charts | `BETA` | Aurora Desktop charts work in DEV with TopstepX and no synthetic candles | Server-environment charts on live `1fae1f39` can return `workspace_runtime_not_connected`; repository fix is not deployed | `app/market_data_ws_http.py`, `app/static/aurora/assets/pages/desktop.js`, [../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md](../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md) |
| AI agents | `PARTIAL` | Vitek, Orchestrator, management tiers, specialist agents and TTS profiles are live in the product surface | per-workspace personal agent-team architecture and some automation boundaries remain incomplete | [../agents/AGENTS.md](../agents/AGENTS.md), `app/ai_lab/chief_agent.py`, `app/ai_lab/domain_agents.py`, `app/vitek.py` |
| Documents | `PARTIAL` | governance source, rendered docs, document revision schema and documents UI exist. Repository allowlist now includes `doc_specs` and `releases` | Live Production `1fae1f39` still 500s Documents/Release Center until the follow-up artifact | [../DOCUMENTATION_GOVERNANCE.md](../DOCUMENTATION_GOVERNANCE.md), `app/doc_specs.py`, `app/production_storage/core.py` |
| Telegram | `PARTIAL` | Production Telegram login/start is available. Canary can reuse the existing bot via shared-webhook forwarding; both `/ready` telegram_consumer probes are `ready` on `1fae1f39` | Cloudflare 1010 can still block public Canary forward; live Production already sets `STRATFORGE_CANARY_INTERNAL_ORIGIN=http://127.0.0.1:18765` | [../../README.md](../../README.md), `app/telegram_service.py` |
| Deployment | `BETA` | Live Canary+Production `current`/`canary-current` and all eight app `/proc` cwd paths are `1fae1f39` | Documents/Charts follow-up needs a new signed artifact and DEV→CANARY→PRODUCTION; local DEV was not listening | `tools/build_server_release.py`, [../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md](../changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md) |
| Security | `PARTIAL` | sessions, CSRF, device registry schema, security challenges and step-up actions exist | full trusted-device lifecycle UX and hard enforcement on every critical action are not yet uniformly complete | [../adr/0003-trusted-devices-and-step-up.md](../adr/0003-trusted-devices-and-step-up.md), `app/security_devices.py`, `app/personal_nt_security.py`, `app/production_storage/migrations/0006_trusted_devices.sql`, `0007_step_up_actions.sql` |
| Legal | `IN DEVELOPMENT` | a structured legal document set exists and is mapped to product data-flow | package is still DRAFT and requires owner placeholders plus counsel review before publication | [../legal/README.md](../legal/README.md) |

## Important current limitations

- Repository evidence and operational evidence answer different questions; use
  the accepted live release snapshot for current deployed state, not only the
  code tree.
- Google and email auth are still `EXTERNAL BLOCKED` in Production despite code
  and schema support.
- Authenticated Canary/Production Connector and licensed-provider chart smoke,
  plus some trusted-device flows, still depend on real external authentication
  or hardware evidence. Live `1fae1f39` still needs the Documents/Charts
  follow-up artifact before server TopstepX and Production Documents can PASS.

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

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T06:20:00Z | Grok 4.6 через Cursor по запросу owner | Recorded live HTTP identity 1fae1f39 vs repository Documents/Charts follow-up; Status PARTIAL.
-->
