# Next Architecture — Final Requirements Matrix

История поправки: 2026-08-03T16:53:14Z; внёс `GitHub Copilot`; scope: Phase 10B — сопоставить исходные требования программы (PLAN_TASK / AUDIT_AND_IMPLEMENTATION_PLAN / PROGRAM_STATUS) с фактическим кодом integration branch `release/0.10.0-next-architecture` и честно классифицировать каждый пункт.

Integration branch at authoring: `release/0.10.0-next-architecture` (Phase 10A tip
`f0028ace`; Phase 10B adds the physical documentation move on top). Sources
compared: `docs/current/STRATFORGE_NEXT_ARCHITECTURE_AUDIT_AND_IMPLEMENTATION_PLAN_2026-08-01.md`,
`docs/current/NEXT_ARCHITECTURE_PROGRAM_STATUS.md`, the per-phase evidence docs,
and the actual `app/`, `tools/`, `tests/`, migration and UI code.

**A plan or a document is never counted as an implementation.** Status legend:
`IMPLEMENTED` (code + tests present), `PARTIALLY IMPLEMENTED`, `EXTERNAL
DEPENDENCY` (code done; real acceptance needs owner infra/credentials),
`NOT IMPLEMENTED`, `NOT APPLICABLE`.

## A. Program phases

| # | Requirement | Status | Evidence (files / endpoints / migrations / tests / commit) |
|---|---|---|---|
| 0 | ADRs + governance overview + CI workflow | IMPLEMENTED | `docs/adr/0001..0007`, `.github/workflows/next-architecture-ci.yml`; merge `fe38c3b7` (PR #6) |
| 1 | Environment metadata, build identity, visual marking, owner icons | IMPLEMENTED | `app/runtime_env.py` (`DeploymentConfig`, `deployment_config`, `/api/runtime/env`), signed server release manifest/verifier `tools/build_server_release.py`/`verify_server_release.py`, Aurora badges; `tests/test_deployment_config.py`, `tests/test_server_release.py`; merge `f4bcb3fc` (PR #7) |
| 2 | Capability-gated Admin Panel + expiring grants + isolated Environment Switcher | IMPLEMENTED | `app/permissions.py` (`ADMIN_CAPABILITIES`, `resolve_admin_capabilities`), `app/account_auth.py` (owner-only grant/revoke), `app/server.py` `_ADMIN_MODULES`; `tests/test_permissions.py`; merge `ca65be2e` (PR #8) |
| 3 | UUID identity, provider abstraction, dual-write compatibility | IMPLEMENTED (live PostgreSQL acceptance EXTERNAL) | `app/auth_identity.py`, `app/account_auth.py` (Google/email OTP/provider status), migration `0005_identity_uuid.sql`; `tests/test_account_auth.py`, `tests/test_phase_a_auth.py`; merge `7fb34762` (PR #9). Live PostgreSQL backfill = EXTERNAL |
| 4 | Trusted-device registry + step-up challenges | IMPLEMENTED | `app/security_devices.py`, migration `0006_trusted_devices.sql`, `/api/account/security`,`/devices`; `tests/test_phase4_trusted_devices.py`; merge `4c60df6c` (PR #10) |
| 5 | Personal NinjaTrader two-factor + per-action step-up | IMPLEMENTED | `app/personal_nt_security.py`, `account_auth.nt_action_gate`, migration `0007_step_up_actions.sql`; `tests/test_phase5_*`,`test_nt_dual_auth.py`; merge `1b4249cc` (PR #11) |
| 6 | Agent allocation + durable shared-NinjaTrader lease/queue | IMPLEMENTED | `app/ninjatrader_resources.py`, `app/agent_allocation.py`, migration `0008_ninjatrader_resource_leases.sql`, `/api/ninjatrader/*`; `tests/test_phase6_*`; merge `93b1fced` (PR #12) |
| 7 | Isolated Canary contour + Developer Preview / View-As | EXTERNAL DEPENDENCY (implementation complete) | `app/runtime_env.py` (`assert_environment_isolation`), `app/dev_preview.py`, `deploy/canary/*`; `tests/test_phase7_canary_isolation.py`,`test_phase7_dev_preview.py`; merge `5955f2e5` (PR #13). Real Canary DB/DNS/tunnel/bot/Connector = EXTERNAL |
| 8 | Release Center: immutable-artifact promotion state machine | EXTERNAL DEPENDENCY (implementation complete) | `app/release_center.py`, migration `0009_release_center.sql`, `/api/admin/releases/*`, Aurora `Центр релизов`; `tests/test_phase8_release_center.py`; merge `4efddb42` (PR #14). Real Canary deploy + exact-artifact Production promotion = EXTERNAL |
| 9 | Blue-green deployment tooling (fail-closed dry-run) | EXTERNAL DEPENDENCY (implementation complete) | `app/blue_green.py`, migration `0010_blue_green_deploy_steps.sql`, `/api/admin/releases/{id}/rehearse-bluegreen`, `deploy/production/blue-green/*`; `tests/test_phase9_blue_green.py`; merge `3a787c6a` (PR #15). Real blue-green deploy/rollback = EXTERNAL |
| 10A | Canonical docs tree spec + migration map + governance amendment hardening | IMPLEMENTED | `docs/DOCS_STRUCTURE.md`, `app/server.py` `_require_governance_manage` (owner/`docs.manage_global` on governance writes); `tests/test_phase10_docs_governance.py`; merge `bd4fbc47` (PR #16) |
| 10B | Physical documentation move + reference rewrite + language/changelog/matrix | PARTIALLY IMPLEMENTED | This branch: `git mv` of ~55 docs into canonical dirs, all markdown links + release manifest + tests + systemd + code comments updated; see §D for the honest residuals |

## B. Test & acceptance matrix (plan §10.11)

| Area | Status | Evidence |
|---|---|---|
| Unit (runtime_env, permissions, auth identity, trusted devices, release state machine, resource lease, blue-green) | IMPLEMENTED | corresponding `tests/test_*`; full local run `1148 passed, 31 skipped` |
| Migration (0001–0010, RLS, additive) | IMPLEMENTED locally; live-PostgreSQL EXTERNAL | `app/production_storage/migrations/0001..0010`, `MigrationRunner`; `tests/test_production_storage.py` (`latest_version == 10`). Live apply to real DB skipped without `STRATFORGE_TEST_POSTGRES_*` = EXTERNAL |
| Auth / account linking (Telegram/Google/email OTP, no email auto-merge, last-method guard) | IMPLEMENTED (production email delivery EXTERNAL) | `app/account_auth.py`, `app/auth_identity.py`; `tests/test_account_auth.py`. Real transactional email provider = EXTERNAL DEPENDENCY |
| Multi-device (pending/approve/reject/revoke, session invalidation) | IMPLEMENTED | `app/security_devices.py`; `tests/test_phase4_trusted_devices.py` |
| Permissions (owner/developer/ordinary, product modes, Mini App) | IMPLEMENTED | `app/permissions.py`; `tests/test_permissions.py`, `tests/test_ux_mode.py` |
| Environment isolation (cookie/CSRF/storage/DB/queue/host) | IMPLEMENTED locally; real cross-env EXTERNAL | `app/runtime_env.py`; `tests/test_phase7_canary_isolation.py`, `tests/test_staging_isolation.py` |
| Telegram separation (per-env bot/webhook/dedupe) | IMPLEMENTED locally; real per-env bot tokens EXTERNAL | `app/telegram_service.py`, `app/production_telegram.py`; `tests/test_telegram.py`, `tests/test_stage8_operations.py` |
| Connector pairing (P-256, signed hello, workspace/capability mismatch, canary contour) | IMPLEMENTED; real pairing EXTERNAL | `app/connector_protocol.py`; `tests/test_connector*`. Real device enrollment = EXTERNAL |
| Shared NinjaTrader locking (exclusive/queue/TTL/heartbeat/cancel) | IMPLEMENTED | `app/ninjatrader_resources.py`; `tests/test_phase6_*` |
| Release promotion (clean commit, signature, artifact/manifest SHA, Canary checks, exact-artifact Production) | IMPLEMENTED (dry-run); real promotion EXTERNAL | `app/release_center.py`; `tests/test_phase8_release_center.py` |
| Blue-green / rollback (green readiness, drain, expand/migrate/contract, rollback switch) | IMPLEMENTED (dry-run); real deploy EXTERNAL | `app/blue_green.py`; `tests/test_phase9_blue_green.py` |
| Documentation permissions (global governance not mutable by workspace/strategy override) | IMPLEMENTED | `app/server.py` `_require_governance_manage`, `app/governance.py` (global-only, no workspace param), `app/jobqueue.py` `update_strategy_profile` allowlist; `tests/test_phase10_docs_governance.py` |
| E2E owner/developer/ordinary user | PARTIALLY IMPLEMENTED | Server/DOM/contract tests (`tests/test_aurora_contracts.py`, `tests/test_cutover_routing.py`); browser QA intentionally not run (workspace stability policy) — see §D |

## C. Workspace-scoped strategy specifications (plan §10 Phase 10, acceptance line 817/836)

| Requirement | Status | Evidence |
|---|---|---|
| Global governance / safety limits / system laws cannot be changed by a workspace or strategy override | IMPLEMENTED | Disjoint stores (`data/governance/` vs `data/profiles/`); `app/governance.py` `update_law`/`update_markdown_document` take no workspace/tenant/scope; `app/jobqueue.py` `update_strategy_profile` strict allowlist never calls `governance.update_*`; governance writes owner/`docs.manage_global`-gated (`app/server.py` `_require_governance_manage`). Tests: `tests/test_phase10_docs_governance.py` |
| A user cannot mutate another workspace's settings via strategy actions | IMPLEMENTED | `app/community.py` `copy_strategy` is workspace-scoped (`_same_workspace`, `workspace_id`); `tests/test_community.py` (cross-workspace copy rejected) |
| A user can fork / copy a strategy into their own workspace | PARTIALLY IMPLEMENTED | `app/community.py` `copy_strategy(workspace_id=)` creates a `pending_import` workspace-scoped copy of a published strategy. This is a community copy, not a full editable per-user strategy-spec revision |
| Full workspace/strategy **specification revision model** (`strategy.spec.manage` capability; `sf_document_revisions` with `scope_type IN ('global','governance','workspace','strategy','changelog')`; `document_revisions`/`document_approvals`/`document_publications`) | **NOT IMPLEMENTED** | Described only in the plan (`...AUDIT_AND_IMPLEMENTATION_PLAN...:123,360,368,600`) and ADR `docs/adr/0007-document-governance.md`. No `strategy.spec.manage` capability in `app/permissions.py`; no `sf_document_revisions` migration (migrations end at 0010). This is a **larger product module** and a concrete incomplete requirement — **Phase 10 is therefore not fully closed** |

## D. Cross-cutting incomplete requirements and external dependencies

| Item | Status | Note |
|---|---|---|
| Real Canary provisioning (isolated DB/DSN, Cloudflare tunnel, `canary.stratforges.com` DNS, separate Telegram bot, Canary Connector) | EXTERNAL DEPENDENCY | Owner infra/credentials; code is fail-closed until configured |
| Real Production deployment + exact-artifact promotion + real blue-green switch | EXTERNAL DEPENDENCY | Owner-gated; dry-run only in code |
| Live PostgreSQL migration acceptance (apply 0005–0010 to a real DB, RLS/restore) | EXTERNAL DEPENDENCY | Skipped without `STRATFORGE_TEST_POSTGRES_*`; static contract tests present |
| Production transactional email provider (email OTP / magic link delivery) | EXTERNAL DEPENDENCY | Schema/API present; real delivery owner decision (plan §12.3) |
| Market-calendar provider (Release Center "after market close" scheduling) | EXTERNAL DEPENDENCY / owner decision | Disabled in code (`market_calendar_unavailable`); needs timezone/holiday/early-close source |
| Full strategy-spec revision product module | NOT IMPLEMENTED | See §C — concrete incomplete requirement |
| Russian normalization of all user/product/governance docs | PARTIALLY IMPLEMENTED | Governance docs and agent docs are already Russian; several architecture/operations/product docs are mixed or English. Localization policy (Russian = canonical) recorded in `docs/LOCALIZATION.md`; a full normalization pass across every technical doc is a follow-up |
| Physical relocation of `AGENT_PERSONAS.md` / `VITEK.md` / `AI_DIALOGUE_CONTRACT.md` / duplicate `repository-hygiene.md` | NOT IMPLEMENTED (owner-gated) | See `docs/REQUIRES_OWNER_CLASSIFICATION.md` (dirty file + diverged duplicate) |
| Governance law `source_refs` still cite pre-move `docs/<file>.md` paths | PARTIALLY IMPLEMENTED | Provenance metadata in `app/governance.py` `DEFAULT_LAWS` + `data/governance/laws.json` (repeated identical strings); substring-validated by `tests/test_governance.py`; regenerated rendered files (`data/*/governance-rendered/*`) update when the backend re-renders. A dedicated source_ref refresh is a follow-up |
| Browser / visual E2E QA | NOT RUN (policy) | Intentionally not run per the workspace stability policy (`AGENTS.md`); replaced by HTTP/DOM/source contract tests |

## E. Version readiness

- Current development version: `0.10.0-dev.1` (`VERSION.json`; channel `dev`, status `in_development`). Latest release tag on non-baseline history: `stratforge-server-v0.9.0-dev.15`; the `0.10.0` line does not reuse any `0.9.0-dev.N` identifier.
- Next allowed dev suffix: `0.10.0-dev.2` (monotonic increment on the same line).
- `0.10.0-beta.1` readiness: **NOT READY.** The plan gates a beta on final integration acceptance PASS; there is at least one concrete incomplete requirement (the strategy-spec revision module, §C) plus multiple external acceptance gates (§D). `VERSION.json` is intentionally **not** changed in Phase 10B.
- Environment vs release channel vs SemVer are kept distinct: `DEPLOYMENT_ENV` (development/canary/production), `RELEASE_CHANNEL` (dev/beta/stable) and the SemVer string are separate fields in `app/runtime_env.py` and `VERSION.json`; they are not mixed.
