# 12. API and Schema Reference

- Context Pack document: 12_API_AND_SCHEMA_REFERENCE.md
- Last verified UTC: 2026-09-05T04:04:22Z
- Verified against Git SHA: 8f42158661e8247832c90bea8fc4d9f0071e647b
- Local source verified SHA: 486db834850d465006a3983d2d83ee809202df60 (clean beta.96 runtime baseline)
- New integrated domain/model/social source: dirty worktree above 486db834; final commit and runtime acceptance pending
- Unified Local base: beta.96, PR #280; separate owner-review slice above foundation PR #281; no merge or Canary/Production promotion
- Scope: Compact index of important endpoint families, entities and capability names
- Status: IN DEVELOPMENT

Local `8765` currently serves the clean `486db834` beta.96 build with original
owner data/settings. New domain/model/social endpoints below describe the dirty
integration delta, not a completed runtime switch or live-provider/browser PASS.
`fc78677` is the historical adapter snapshot. The deployed anchor
`8f42158661e8247832c90bea8fc4d9f0071e647b` remains unchanged; Production was not
rechecked in this task.

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
| Agent World read model | `/api/ai-control-center/overview`, `/api/ai-control-center/tasks`, `/api/ai-control-center/tasks/{UUID}`, `/api/ai-control-center/tasks/{UUID}/chat` | scoped real history and separate Preview adapter; real chat-link POST accepts only an empty body and never appends; existing auth/device/flags remain authoritative |
| Agent World Preview | `/api/ai-control-center/demo-runs` | isolated synthetic calculations, never real-provider or real-owner runs |
| Agent World domains | `/api/ai-control-center/domains/{domain}`, `/api/ai-control-center/domains/{domain}/{UUID}`, `/api/ai-control-center/domains/{domain}/{new-or-UUID}/{action}` | Development-only current membership/session admission; own-owner writes and immutable revisions; collection/detail reads are non-mutating |
| Agent World evidence | `/api/ai-control-center/artifacts/{UUID}`, `/api/ai-control-center/memory-artifacts/{memory-UUID}/{artifact-UUID}` | private owner artifact lookup; shared Memory read only through an explicitly active same-workspace grant, source/TTL/hash checked; separate Preview store |
| Agent World social publication | `/api/ai-control-center/domains/publications/new/{prepare,publish}` | explicit human review and permanent-publication consent over exact snapshot SHA/revision; existing Community store/capability/idempotency |
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
| Agent World Development ledger | `aw_records`, `aw_revisions`, `aw_events`, `aw_outbox`, `aw_mutations`, `aw_inbox`, `aw_artifacts` | `app/ai_control_center/sqlite_repository.py`; typed domain/model records, atomic CAS/outbox/idempotency and private artifact hashes; no PG adapter |

## Agent World domain/API contract

Agent World adds a Development-only SQLite repository with atomic revision,
event, history and idempotency commit plus immutable private artifacts.
No global migration is added: sequence still ends at
`0022_community_post_private_visibility.sql`. There is no Agent World PostgreSQL
domain implementation. The 41 actual isolated PostgreSQL tests concern existing
RLS/relational behavior through migrations `0001`–`0022`, not this new ledger.
Non-Development Agent World storage/access remains fail-closed.

No facade accepts a client-selected workspace, user UUID, actor or capability
grant. The new explicit model workflow does accept an owned selected Model ID
or a guarded new private Provider Account configuration; this does not confer
permissions or expose another user's model/owner registry. Real provider calls
require separate `ai_pro_models`, session and existing budget admission. Preview
still makes no external provider calls. The earlier statement that no Agent World
endpoint can call a provider describes the historical adapter-only snapshot.

GET collection/detail routes open a read-only repository: absent DB means empty
history without path/schema creation. Existing WAL state is read, not ignored.
GET never enqueues a job, invokes a model, acknowledges a completion or publishes
social content. All artifacts retain private/no-store, nosniff and sandbox CSP.
The active-Memory grant does not change private artifact access or let a reader
revoke somebody else's source.

Domain mutation envelope is `{payload, expected_revision, idempotency_key}`.
The HTTP facade requires a bounded key; stale revisions and same-key/different
semantic requests conflict. Scope comes only from fresh server admission.

| Domain | Implemented actions in this dirty delta |
| --- | --- |
| `personas` | create/update, activate/suspend/archive |
| `memory` | create/update draft, promote/revoke/expire, explicit `publish_to_workspace`; purpose/TTL/source-bound retrieval |
| `projects` | create/update, append immutable parameter `version`, archive |
| `routines`, `calendar` | create, accept/dismiss; routines also `suggest_routine` from verified Outcome IDs; acceptance is an existing-queue manual reminder, automation OFF |
| `decisions`, `court` | create proposal, `propose_consensus` from independent accepted Contributions, review with exactly three Model IDs, withdraw an eligible proposal; Court detail is read-only |
| `models` | `connect`, owner-only `bind_existing`, connection `test`, bounded `task`, disconnect; no client budget grants |
| `model_tasks`, `tasks` | owned task details/history and explicit cancel through the existing execution/queue authority |
| `experiments` | explicit same-input selected-model comparisons and independently checked per-input evidence, no Router change |
| `publications` | eligible owned source candidates, read-only `prepare`, then explicit permanent `publish` |
| `system` | scope, flags, existing capabilities/storage/worker limitations; no new control-plane authority |

Publication preparation payload is `{source_kind, source_id}` and returns
`snapshot`, `snapshot_sha256`, `source_revision`, `permanent` and
`requires_explicit_confirmation`. Publish payload names the same source,
`approved_snapshot_sha256`, optional human `text`, `visibility` and
`confirm_permanent=true`, with `expected_revision`/`idempotency_key` in the
envelope. Raw Memory/artifacts/prompts cannot be passed as public snapshots.
The source and fresh social capability are checked again before the existing
Community write; approved snapshot and actor/requester evidence are immutable.

Post-trial professional history access is a narrow entitlement exception, not
authentication or new work permission. The real `/tasks/{UUID}/chat` POST takes
only `{}` and returns an already-existing `conversation_id`; it does not append
messages or attach PNGs. Preview's explicit synthetic chat/PNG acceptance path
remains isolated and must not be generalized to ordinary Local.

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

All flags default OFF. Controlled Preview enables its four synthetic gates;
the new exact-workspace Development composition enables `AI_CONTROL_CENTER_READ_MODEL`,
`AI_COMMAND_CENTER_UI`, `AI_TASK_GRAPH_V2`, `AI_EVALUATION_SHADOW`, `AI_MEMORY_V2`,
`AI_CONSENSUS_V2`, `AI_COURT_V1` and `AI_SOCIAL_PUBLISH_V1`. `AI_ROUTER_SHADOW_V2`
and `AI_EXECUTION_V2` remain OFF. Existing `ai_lab`, `ai_pro_models`, `community`,
backtesting, session/device and budget authorities still decide access. See
[ADR-0010](../adr/0010-agent-world-owner-review.md) and
[ADR-0011](../adr/0011-agent-world-real-local-jobs.md).

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
- `app/ai_control_center/domain_gateway.py`
- `app/ai_control_center/domain_service.py`
- `app/ai_control_center/model_service.py`
- `app/ai_control_center/social_publication.py`
- `app/ai_control_center/sqlite_repository.py`
- `app/ai_control_center/live_http_api.py`
- `tools/community_storage_migration.py`
