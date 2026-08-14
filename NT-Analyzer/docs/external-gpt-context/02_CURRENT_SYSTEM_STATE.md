# 02. Current System State

- Context Pack document: 02_CURRENT_SYSTEM_STATE.md
- Last verified UTC: 2026-08-14T17:12:00Z
- Verified against Git SHA: 77e8645f1725d20545992efdeabafdf2f3d0e684
- Scope: Current factual subsystem snapshot only
- Status: DONE
- Current Production version/build/artifact when known: LOCAL/CANARY/PRODUCTION git `77e8645f1725d20545992efdeabafdf2f3d0e684`, build `sf-0.10.0-beta.1-77e8645f1725-20260814T164341Z`, public artifact SHA256 `1F0C95E48447632CB97EF88A85E38354D6A71AC32C41285600DACA182A8748C6`. Previous slot is `1fae1f39`. Owner Documents/Release Center 200 and TopstepX LIVE.

## Evidence modes

- **Repository evidence** in this pack means current code/schema/config/docs
  on git `77e8645f1725d20545992efdeabafdf2f3d0e684`.
- **Operational evidence** means the 2026-08-14 live closeout
  [../changelog/2026-08-14-live-release-77e8645f-documents-charts.md](../changelog/2026-08-14-live-release-77e8645f-documents-charts.md).
  Historical `1fae1f39`, Canary `7ebda6fa` and hang-fix Production `6b6dc458`
  remain in changelog.
- If the repository and the live environment answer different questions, this
  file says which evidence mode it is using instead of pretending they are the
  same thing.

## Current-only snapshot

| Подсистема | Status | Что реально работает сейчас | PARTIAL / EXTERNAL BLOCKED / лимиты | Compact evidence |
| --- | --- | --- | --- | --- |
| Auth | `PARTIAL` | Telegram login works on DEV, Canary and Production on live `77e8645f` | Google and email remain `EXTERNAL BLOCKED` in Production | [../adr/0002-unified-identity.md](../adr/0002-unified-identity.md), `app/account_auth.py`, [../changelog/2026-08-14-live-release-77e8645f-documents-charts.md](../changelog/2026-08-14-live-release-77e8645f-documents-charts.md) |
| Users / workspaces | `PARTIAL` | active workspace, memberships, owner-training vs personal-runtime split, bridge pairing contracts | broader entitlement/subscription/commercial rollout is incomplete | [../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md](../architecture/MULTI_USER_ACCOUNT_ARCHITECTURE.md), `app/workspaces.py`, `app/production_storage/migrations/0001_authoritative_storage.sql` |
| DEV / CANARY / PRODUCTION | `BETA` | env/channel split is fail-closed. LOCAL/CANARY/PRODUCTION process identity is `77e8645f` / same release dir | Google/email EXTERNAL BLOCKED | [../adr/0001-environments-and-release-identity.md](../adr/0001-environments-and-release-identity.md), [../changelog/2026-08-14-live-release-77e8645f-documents-charts.md](../changelog/2026-08-14-live-release-77e8645f-documents-charts.md) |
| Admin | `PARTIAL` | capability catalog, server-side permission resolver, owner-only modules and Environment Switcher UI exist | separate polished Admin Panel shell continues to evolve | [../adr/0004-admin-panel-and-capabilities.md](../adr/0004-admin-panel-and-capabilities.md), `app/permissions.py`, `app/static/aurora/assets/ui.js` |
| Release Center | `BETA` | owner-facing UI now completes clean candidate, protected signed build, verify, real Canary deployment, structured acceptance checks and real rollback→re-promote. Exact fingerprint is immutable | Production approval and process gate remain intentionally separate; notification delivery still depends on environment infrastructure | `app/release_center.py`, `app/release_executor.py`, `app/blue_green.py`, [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md) |
| Connector | `PARTIAL` | pair/enroll/challenge/hello/heartbeat/market-data/commands protocol is implemented with P-256 device identity | real Production acceptance still depends on a real Windows VM and published endpoint | [../architecture/CONNECTOR_PROTOCOL_V1.md](../architecture/CONNECTOR_PROTOCOL_V1.md), `app/connector_protocol.py` |
| NinjaTrader | `PARTIAL` | remains the source of truth for compilation, backtests, fills, trades, runtime state and actual Simulation vs real/live account mode | specific actions against a real/live account remain gated by permissions, safety, release and account capability; accepted 2026-08-12 closeout placed no orders | [../../README.md](../../README.md), [../operations/manual-validation.md](../operations/manual-validation.md), `app/server.py`, [../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md](../changelog/2026-08-12-live-release-snapshot-0.10.0-beta.1.md) |
| Market data / TopstepX | `BETA` | TopstepX is the primary independent read-only chart feed. Owner sessions on DEV/Canary/Production serve MNQ history + realtime while NinjaTrader is unavailable | External feed never grants order authority. Host needs credentials plus remote/redistribution flags and `websockets` | [../architecture/MARKET_DATA_RESILIENCE_PLAN.md](../architecture/MARKET_DATA_RESILIENCE_PLAN.md), `app/server.py`, `app/workspaces.py`, [../changelog/2026-08-14-live-release-77e8645f-documents-charts.md](../changelog/2026-08-14-live-release-77e8645f-documents-charts.md) |
| Charts | `BETA` | Aurora Desktop charts work with TopstepX; server environments no longer stub `/api/ops/runtime/bars*` | In-app browser visual was not used this closeout; HTTP/API proof is LIVE | `app/market_data_ws_http.py`, `app/static/aurora/assets/pages/desktop.js`, [../changelog/2026-08-14-live-release-77e8645f-documents-charts.md](../changelog/2026-08-14-live-release-77e8645f-documents-charts.md) |
| AI agents | `PARTIAL` | Vitek, Orchestrator, management tiers, specialist agents and TTS profiles are live in the product surface | per-workspace personal agent-team architecture and some automation boundaries remain incomplete | [../agents/AGENTS.md](../agents/AGENTS.md), `app/ai_lab/chief_agent.py`, `app/ai_lab/domain_agents.py`, `app/vitek.py` |
| Documents | `BETA` | `/api/documents` is HTTP 200 for owner sessions on DEV/Canary/Production; allowlist includes `doc_specs` and `releases` | Empty document list is data, not a 500 | [../DOCUMENTATION_GOVERNANCE.md](../DOCUMENTATION_GOVERNANCE.md), `app/doc_specs.py`, `app/production_storage/core.py` |
| Telegram | `PARTIAL` | Production and Canary Telegram login/start work on `77e8645f`; Canary reuses the existing bot via shared-webhook forwarding | Public HTTPS Canary forward can still hit Cloudflare 1010; live Production sets `STRATFORGE_CANARY_INTERNAL_ORIGIN=http://127.0.0.1:18765` | [../../README.md](../../README.md), `app/telegram_service.py` |
| Deployment | `BETA` | Live LOCAL/CANARY/PRODUCTION git `77e8645f`; `canary-current`=`current`; all eight app `/proc` cwd match | Next build must install `websockets` from requirements into `.venv` | `tools/build_server_release.py`, [../changelog/2026-08-14-live-release-77e8645f-documents-charts.md](../changelog/2026-08-14-live-release-77e8645f-documents-charts.md) |
| Security | `PARTIAL` | sessions, CSRF, device registry schema, security challenges and step-up actions exist | full trusted-device lifecycle UX and hard enforcement on every critical action are not yet uniformly complete | [../adr/0003-trusted-devices-and-step-up.md](../adr/0003-trusted-devices-and-step-up.md), `app/security_devices.py`, `app/personal_nt_security.py`, `app/production_storage/migrations/0006_trusted_devices.sql`, `0007_step_up_actions.sql` |
| Legal | `IN DEVELOPMENT` | a structured legal document set exists and is mapped to product data-flow | package is still DRAFT and requires owner placeholders plus counsel review before publication | [../legal/README.md](../legal/README.md) |

## Important current limitations

- Repository evidence and operational evidence answer different questions; use
  the accepted live release snapshot for current deployed state, not only the
  code tree.
- Google and email auth are still `EXTERNAL BLOCKED` in Production despite code
  and schema support.
- Authenticated Canary/Production Connector and some trusted-device flows still
  depend on real external authentication or hardware evidence. Documents and
  server TopstepX charts on `77e8645f` are owner-verified PASS.

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
2026-08-14T17:12:00Z | Grok 4.6 через Cursor по запросу owner | Live identity 77e8645f; Documents+TopstepX PASS on LOCAL/CANARY/PRODUCTION.
2026-08-14T06:20:00Z | Grok 4.6 через Cursor по запросу owner | Recorded live HTTP identity 1fae1f39 vs repository Documents/Charts follow-up; Status PARTIAL.
-->
