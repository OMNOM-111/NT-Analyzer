# 12. API and Schema Reference

- Context Pack document: 12_API_AND_SCHEMA_REFERENCE.md
- Last verified UTC: 2026-09-04T22:37:13Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 3afb75c5c2d02aa07703eadf274a1c1006ae8ada
- Unified Local accepted base: beta.96, PR #280; separate owner-review slice above foundation PR #281; not deployed
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
| Agent World read model | `/api/ai-control-center/overview`, `/api/ai-control-center/tasks`, `/api/ai-control-center/tasks/{UUID}`, `/api/ai-control-center/tasks/{UUID}/chat` | separate admitted Preview and explicit Local-owner adapters; existing auth/device/capability/role/CSRF plus exact scoped flags; no new permissions |
| Agent World Preview | `/api/ai-control-center/demo-runs`, `/api/ai-control-center/artifacts/{UUID}` | isolated synthetic calculations and owned immutable evidence; forbidden in real Local |
| Agent World Local backtest | `/api/ai-control-center/backtests` | exact explicit spec + idempotency_key + conversation_id; only opted-in real Local owner; canonical existing jobqueue, not a new engine |
| AI Lab / Orchestrator | `/api/ai-lab/*`, `/api/vitek/*` | orchestration, domain agents, TTS, experiments, summaries |
| Community v2 | `/api/community/v2/*` | profiles/privacy, feed/search, follows, interactions, blocks, moderation and server-attested result publications |
| SF Chat | `/api/sf-chat/*` | one human conversation/message/attachment/unread/read contract; global UI also projects existing AI conversations |
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
| Community / SF Chat documents | repository allowlist entries `community`, `sf_chat` | `0020_community_sf_chat_repositories.sql` |
| Community / SF Chat relational mirrors | `sf_community_*`, `sf_chat_*` with FK/index/FORCE RLS | `0021_community_sf_chat_relational_mirrors.sql` |

## Capability names worth recognizing

Agent World adds a Development-only SQLite repository with atomic revision,
event, history and idempotency commit plus immutable private artifacts.
No global migration is added: sequence still ends at
`0022_community_post_private_visibility.sql`. PostgreSQL/RLS remains a gap.

Both facades accept no client-selected workspace, actor, role, provider or model.
GET overview includes personas and shadow metrics; GET tasks/{UUID} exposes owned
task/result/evaluation/evidence; GET artifacts/{UUID} enforces private scope.
POST demo-runs takes only idempotency_key; POST tasks/{UUID}/chat optionally takes
a bounded PNG data URL. Only independently checked completed results publish.
No agent endpoint creates real credentials or calls an external provider.

The Local adapter projects only server-stamped owner jobs. Historical strategies
must be catalog-registered with explicit instrument/timeframe/UTC period and safe
research execution settings. Completion requires actual NinjaTrader job/result
context, complete bars/trades and matching fingerprint; incomplete evidence is
review, not succeeded. Read windows are bounded and are not all-time statistics.
The existing `/api/ops/runtime/chart-snapshot` accepts an additive
`agent_world=true`, `command_id`, `capture`, bounded PNG and explicit
`mirror_to_telegram=false`. Server checks command ownership and matching context,
persists its receipt before idempotent SF Chat publication, and echoes command_id.
Client ACK cannot overwrite that verified receipt. Existing snapshots stay at
their canonical authenticated `/api/ops/runtime/snapshots/cs_*.png` URLs.

All flags default OFF: four scoped flags for controlled Preview; three read/UI/
tasks flags for explicitly opted-in Local owner, no real evaluation flag.
Existing ai_lab/backtesting capabilities remain authoritative. See
[ADR-0010](../adr/0010-agent-world-owner-review.md) and
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md).

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
| `community` | access Community and unified human SF Chat; object publication also rechecks source job entitlement/ownership |

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
- `app/community.py`
- `app/sf_chat.py`
- `tools/community_storage_migration.py`
