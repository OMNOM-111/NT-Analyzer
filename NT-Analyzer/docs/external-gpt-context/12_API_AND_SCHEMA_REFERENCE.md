# 12. API and Schema Reference

- Context Pack document: 12_API_AND_SCHEMA_REFERENCE.md
- Last verified UTC: 2026-09-03T02:47:29Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Device-confirmation Development implementation SHA: `19e0f43a35bee5a2e396538962e8f24e92bed6ef` (PR #278; isolated branch; not deployed)
- Scope: Compact index of important endpoint families, entities and capability names
- Status: DONE

## Key endpoint families

| Area | Endpoint family | Purpose |
| --- | --- | --- |
| Auth | `/api/auth/*` | status, login, profile, users, sessions, consent |
| Device confirmation | `/api/account/security`, `/api/account/security/challenge*`, `/api/account/devices/{approve,reject,rename,revoke}`, `/api/account/machines/{rename,revoke}`, `/api/account/sessions/revoke` | pending bootstrap, Telegram/verified-email OTP, permanent/current-session access, normalized security catalog and scope-correct access management |
| Workspaces | `/api/workspaces*` | list/select/create workspace context |
| Bridge pairing | `/api/bridge/pair/*`, `/api/bridge/connections*` | pair/revoke/manage local NinjaTrader connections |
| Connector protocol | `/api/connector/v1/*` | enroll, challenge, hello, heartbeat, market-data, commands poll/result |
| Runtime ops | `/api/ops/runtime/*` | accounts, positions, orders, executions, bars, strategy runtime surfaces |
| Market-data browser edge | `/api/ops/runtime/bars`, `/api/ops/runtime/bars/batch`, `/ws/market-data` | same-origin history/health and deduplicated browser realtime; no provider credentials |
| AI Lab / Orchestrator | `/api/ai-lab/*`, `/api/vitek/*` | orchestration, domain agents, TTS, experiments, summaries |
| Release / admin | `/api/admin/releases*`, `/api/admin/pipeline`, `/api/admin/environment-targets` | create/build/verify/deploy/accept/promote/rollback and separate-origin switching |
| Release control | `/api/environments/release-control` | signed, replay-protected authoritative Canary/Production promotion decision |
| Admin integrations | `/api/admin/connectors`, `/api/admin/operations` | bounded status cards for gateway/providers, Telegram, Worker and Connector |
| News / integrations | `/api/news`, `/api/news/live`, `/api/topstep/status`, `/api/integrations/status` | read-only provider/news status |
| Telegram current | `/api/telegram/pair`, `/api/telegram/status`, settings/test/notification routes | login, bot and notification flows |
| Telegram retired | Mini App registration, `/api/telegram/remote*`, `/api/telegram/tunnel*` | HTTP 410; no current runtime capability |
| Documents / governance | governance/document routes plus documents UI contracts | global docs, revisions, rendered/current documents |

## Important schema / entity groups

| Group | Main entities | Evidence |
| --- | --- | --- |
| Core auth/workspace | users, sessions, workspaces, memberships, entitlements, jobs, commands | `0001_authoritative_storage.sql` |
| UUID identity | `user_uuid`, `sf_auth_identities` | `0005_identity_uuid.sql` |
| Trusted devices / challenges | `sf_trusted_devices`, `sf_security_challenges` | `0006_trusted_devices.sql`, `0007_step_up_actions.sql` |
| Physical machines / sessions | `sf_physical_devices`, `sf_auth_sessions` | existing document mirrors; Device Confirmation adds fields to existing JSONB documents and requires no new migration |
| Shared NT resource access | resource lease schema | `0008_ninjatrader_resource_leases.sql` |
| Release Center | `sf_release_artifacts`, `sf_release_candidates`, `sf_release_deployments`, `sf_release_checks`, `sf_release_approvals`, `sf_release_rollbacks`, `sf_release_events` | `0009_release_center.sql` |
| Blue-green detail | `sf_release_deploy_steps`, `sf_maintenance_windows` | `0010_blue_green_deploy_steps.sql` |
| Documents | `sf_documents`, `sf_document_revisions` | `0011_document_specifications.sql` |

## Capability names worth recognizing

| Capability | Meaning |
| --- | --- |
| `admin.view` | access to admin shell/modules |
| `users.manage` | manage users |
| `workspaces.manage` | manage workspaces |
| `connectors.manage` | manage Connector installations and pairing |
| `operations.view` / `operations.execute` | split observation from execution |
| `releases.view` / `releases.create` | view and create release candidates |
| `releases.deploy_canary` | deploy to Canary |
| `releases.promote_production` | promote same artifact to Production |
| `releases.rollback_production` | rollback Production |
| `environment.switch` | open another environment origin |
| `docs.manage_global` / `docs.manage_workspace` | edit global or workspace-scoped docs |

## Source files external GPT should request for code-level work

- `app/server.py`
- `app/runtime_env.py`
- `app/account_auth.py`
- `app/auth_identity.py`
- `app/security_devices.py`
- `app/physical_devices.py`
- `app/personal_nt_security.py`
- `app/connector_protocol.py`
- `app/market_data_failover.py`
- `app/release_center.py`
- `app/blue_green.py`
- `app/permissions.py`
