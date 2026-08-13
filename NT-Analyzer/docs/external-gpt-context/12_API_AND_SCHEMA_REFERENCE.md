# 12. API and Schema Reference

- Context Pack document: 12_API_AND_SCHEMA_REFERENCE.md
- Last verified UTC: 2026-08-13T09:49:37Z
- Verified against Git SHA: 7ebda6faf2e7c64d4a707a41062b29857882181a
- Scope: Compact index of important endpoint families, entities and capability names
- Status: DONE

## Key endpoint families

| Area | Endpoint family | Purpose |
| --- | --- | --- |
| Auth | `/api/auth/*` | status, login, profile, users, sessions, consent |
| Workspaces | `/api/workspaces*` | list/select/create workspace context |
| Bridge pairing | `/api/bridge/pair/*`, `/api/bridge/connections*` | pair/revoke/manage local NinjaTrader connections |
| Connector protocol | `/api/connector/v1/*` | enroll, challenge, hello, heartbeat, market-data, commands poll/result |
| Runtime ops | `/api/ops/runtime/*` | accounts, positions, orders, executions, bars, strategy runtime surfaces |
| AI Lab / Orchestrator | `/api/ai-lab/*`, `/api/vitek/*` | orchestration, domain agents, TTS, experiments, summaries |
| Release / admin | owner/admin release-center and environment-switch surfaces in `app/server.py` + `app/release_center.py` | create/build/verify/deploy/promote/rollback workflows |
| News / integrations | `/api/news`, `/api/news/live`, `/api/topstep/status`, `/api/integrations/status` | read-only provider/news status |
| Telegram | `/api/telegram/*` | pair, status, settings, test and notification flows |
| Documents / governance | governance/document routes plus documents UI contracts | global docs, revisions, rendered/current documents |

## Important schema / entity groups

| Group | Main entities | Evidence |
| --- | --- | --- |
| Core auth/workspace | users, sessions, workspaces, memberships, entitlements, jobs, commands | `0001_authoritative_storage.sql` |
| UUID identity | `user_uuid`, `sf_auth_identities` | `0005_identity_uuid.sql` |
| Trusted devices / challenges | `sf_trusted_devices`, `sf_security_challenges` | `0006_trusted_devices.sql`, `0007_step_up_actions.sql` |
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
- `app/personal_nt_security.py`
- `app/connector_protocol.py`
- `app/market_data_failover.py`
- `app/release_center.py`
- `app/blue_green.py`
- `app/permissions.py`
