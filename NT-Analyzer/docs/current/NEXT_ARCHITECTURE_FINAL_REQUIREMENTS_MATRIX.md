# Next Architecture — Final Requirements Matrix

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
| 3 | UUID identity, provider abstraction, dual-write compatibility | IMPLEMENTED (live PostgreSQL applied 2026-08-12) | `app/auth_identity.py`, migration `0005_identity_uuid.sql`; live Canary+Production apply. Existing Production rows required a postgres/BYPASSRLS backfill replay because `stratforge_migration` is not `BYPASSRLS` under FORCE RLS |
| 4 | Trusted-device registry + step-up challenges | IMPLEMENTED | `app/security_devices.py`, migration `0006_trusted_devices.sql`, `/api/account/security`,`/devices`; `tests/test_phase4_trusted_devices.py`; merge `4c60df6c` (PR #10) |
| 5 | Personal NinjaTrader two-factor + per-action step-up | IMPLEMENTED | `app/personal_nt_security.py`, `account_auth.nt_action_gate`, migration `0007_step_up_actions.sql`; `tests/test_phase5_*`,`test_nt_dual_auth.py`; merge `1b4249cc` (PR #11) |
| 6 | Agent allocation + durable shared-NinjaTrader lease/queue | IMPLEMENTED | `app/ninjatrader_resources.py`, `app/agent_allocation.py`, migration `0008_ninjatrader_resource_leases.sql`, `/api/ninjatrader/*`; `tests/test_phase6_*`; merge `93b1fced` (PR #12) |
| 7 | Isolated Canary contour + Developer Preview / View-As | IMPLEMENTED live | `canary.stratforges.com` uses isolated DB/queue/storage/session/cookie state; existing-owner Telegram routing works without a separate Canary bot. Developer Preview remains Development-only |
| 8 | Release Center: immutable-artifact promotion state machine | IMPLEMENTED / BETA UI | Beta.29 candidate `rc_a7c6c0…` completed clean build/sign, Canary acceptance, owner approval and same-artifact Production promotion. Code: `app/release_center.py`, `app/release_executor.py`; current evidence `docs/changelog/2026-08-22-market-data-responsive-release-beta29.md` |
| 9 | Blue-green deployment tooling | IMPLEMENTED live | `stage9_ssh` executed verified Canary and Production switches for the exact beta.29 artifact; identity/readiness/signature/same-artifact evidence passed and no rebuild occurred |
| 10A | Canonical docs tree spec + migration map + governance amendment hardening | IMPLEMENTED | `docs/DOCS_STRUCTURE.md`, `app/server.py` `_require_governance_manage` (owner/`docs.manage_global` on governance writes); `tests/test_phase10_docs_governance.py`; merge `bd4fbc47` (PR #16) |
| 10B | Physical documentation move + reference rewrite + language/changelog/matrix | PARTIALLY IMPLEMENTED | This branch: `git mv` of ~55 docs into canonical dirs, all markdown links + release manifest + tests + systemd + code comments updated; see §D for the honest residuals |

## B. Test & acceptance matrix (plan §10.11)

| Area | Status | Evidence |
|---|---|---|
| Unit/integration regression (runtime_env, permissions, auth identity, trusted devices, release state machine, resource lease, market data, docs, blue-green) | IMPLEMENTED | beta.29: targeted market/chart/Operations/responsive `251 passed`; full `1924 passed, 32 skipped, 0 failed`; all five PR #142 CI jobs PASS. Skips: 31 explicit live-PostgreSQL checks plus one Windows bash-syntax check |
| Migration (0001–0011, RLS, additive) | IMPLEMENTED locally; live Canary+Production applied 2026-08-12 | `0001..0011` on `stratforge_canary` and `stratforge_production`. UUID DML backfill on Production required postgres/BYPASSRLS replay |
| Auth / account linking (Telegram/Google/email OTP, no email auto-merge, last-method guard) | PARTIAL live | Existing owner sessions/login work in isolated Canary and Production; authenticated owner acceptance passed. Google remains **EXTERNAL BLOCKED** without its Production OAuth client; email OTP remains **EXTERNAL BLOCKED** without a transactional provider |
| Multi-device (pending/approve/reject/revoke, session invalidation) | IMPLEMENTED | `app/security_devices.py`; `tests/test_phase4_trusted_devices.py` |
| Permissions (owner/developer/ordinary, product modes; Mini App deprecated) | IMPLEMENTED | `app/permissions.py`; `tests/test_permissions.py`, `tests/test_ux_mode.py`; retired Mini App routes return HTTP 410 |
| Environment isolation (cookie/CSRF/storage/DB/queue/host) | IMPLEMENTED live | Distinct Canary vs Production DB/role/queue/cookie/origin; CONNECT privilege negatives verified 2026-08-12 |
| Telegram separation (per-env marker/queue/dedupe) | IMPLEMENTED / BETA | Production is unmarked; Canary uses `[CANARY]` and isolated queues/sessions while reusing the existing bot/webhook routing. Admin UI reported Telegram connected on both beta.29 environments |
| Release promotion (clean commit, signature, artifact/manifest SHA, Canary checks, exact-artifact Production) | IMPLEMENTED live | Beta.29 `4d15f1d` / runtime `CBA4FA70…2379` is live on both Canary and Production; exact-artifact invariant and authoritative promotion decision passed |
| Blue-green / rollback (green readiness, drain, expand/migrate/contract, rollback switch) | IMPLEMENTED live | Real beta.29 Canary and Production eight-stage deploys PASS; pending migrations `0`; beta.28 is the verified previous/rollback slot |
| Connector pairing (P-256, signed hello, workspace/capability mismatch, canary contour) | IMPLEMENTED; real pairing EXTERNAL | `app/connector_protocol.py`; `tests/test_connector*`. Real device enrollment = EXTERNAL |
| Shared NinjaTrader locking (exclusive/queue/TTL/heartbeat/cancel) | IMPLEMENTED | `app/ninjatrader_resources.py`; `tests/test_phase6_*` |
| Documentation permissions (global governance not mutable by workspace/strategy override) | IMPLEMENTED | `app/server.py` `_require_governance_manage`, `app/governance.py` (global-only, no workspace param), `app/jobqueue.py` `update_strategy_profile` allowlist; `tests/test_phase10_docs_governance.py` |
| E2E owner/developer/ordinary user | PARTIAL | DEV owner/developer/admin/ordinary/disposable persona and new-user/permission surfaces were browser-tested; authenticated owner UI/Documents/charts flows passed on beta.29 in both Canary and Production. Broader non-owner live-environment personas remain incomplete; Google/email remain EXTERNAL BLOCKED |

## C. Workspace-scoped strategy specifications (plan §10 Phase 10, acceptance line 817/836)

| Requirement | Status | Evidence |
|---|---|---|
| Global governance / safety limits / system laws cannot be changed by a workspace or strategy override | IMPLEMENTED | Disjoint stores (`data/governance/` vs `data/profiles/`); `app/governance.py` `update_law`/`update_markdown_document` take no workspace/tenant/scope; `app/jobqueue.py` `update_strategy_profile` strict allowlist never calls `governance.update_*`; governance writes owner/`docs.manage_global`-gated (`app/server.py` `_require_governance_manage`). Tests: `tests/test_phase10_docs_governance.py` |
| A user cannot mutate another workspace's settings via strategy actions | IMPLEMENTED | `app/community.py` `copy_strategy` is workspace-scoped (`_same_workspace`, `workspace_id`); `tests/test_community.py` (cross-workspace copy rejected) |
| A user can fork / copy a strategy into their own workspace | PARTIALLY IMPLEMENTED | `app/community.py` `copy_strategy(workspace_id=)` creates a `pending_import` workspace-scoped copy of a published strategy. This is a community copy, not a full editable per-user strategy-spec revision |
| Full workspace/strategy **specification revision model** (`strategy.spec.manage` capability; `sf_document_revisions` with `scope_type IN ('global','governance','workspace','strategy','changelog')`; draft→review→approved→published→superseded; revert) | **IMPLEMENTED** (Phase 11) | `strategy.spec.manage` in `app/permissions.py`; migration `0011_document_specifications.sql` (`sf_documents`+`sf_document_revisions`, RLS `sf_scope_global()`/`sf_scope_workspace()`, GRANT `stratforge_app`); `app/doc_specs.py`; API `/api/documents*` (`app/server.py`); UI «Документы рабочих областей»; workspace/strategy scope не может менять global governance/safety-limits. Tests: `tests/test_phase11_doc_specs.py` (12) |

## D. Cross-cutting incomplete requirements and external dependencies

| Item | Status | Note |
|---|---|---|
| Real Canary provisioning (isolated DB/DSN, origin, Telegram routing, Canary Connector) | PARTIAL | Isolated application/auth/data contour and authenticated owner charts are live; physical Canary Connector enrollment remains external and was not fabricated |
| Real Production deployment + exact-artifact promotion + real blue-green switch | IMPLEMENTED | Beta.29 same immutable artifact is live/ready on Canary and Production; archive/runtime identities, deployment IDs and rollback slot are recorded in the current closeout |
| Live PostgreSQL migration acceptance (apply 0005–0011 to a real DB, RLS/restore) | IMPLEMENTED on live Canary+Production | Applied 2026-08-12. Isolated restore drill of Production dump PASS (5 users / 3 workspaces / max migration 4 before expand). UUID DML required postgres/BYPASSRLS replay |
| Production transactional email provider (email OTP / magic link delivery) | EXTERNAL BLOCKED | Code path exists; `available` is Development test-auth only. No `NTA_EMAIL_AUTH_PROVIDER` in Production. |
| Google OAuth login | EXTERNAL BLOCKED | Implementation present; Production env has no `NTA_GOOGLE_CLIENT_ID` / `SECRET` / `NTA_GOOGLE_REDIRECT_URI`. Redirect contract: `https://app.stratforges.com/api/auth/google/callback` |
| Market-calendar provider (Release Center "after market close" scheduling) | EXTERNAL DEPENDENCY / owner decision | Disabled in code (`market_calendar_unavailable`); needs timezone/holiday/early-close source |
| Full strategy-spec revision product module | IMPLEMENTED (Phase 11) | See §C — `strategy.spec.manage` + migration 0011 + `app/doc_specs.py` + API/UI + tests |
| Russian normalization of all user/product/governance docs | PARTIALLY IMPLEMENTED | Governance docs and agent docs are already Russian; several architecture/operations/product docs are mixed or English. Localization policy (Russian = canonical) recorded in `docs/LOCALIZATION.md`; a full normalization pass across every technical doc is a follow-up |
| Physical relocation of `AGENT_PERSONAS.md` / `VITEK.md` / `AI_DIALOGUE_CONTRACT.md` / duplicate `repository-hygiene.md` | NOT IMPLEMENTED (owner-gated) | See `docs/REQUIRES_OWNER_CLASSIFICATION.md` (dirty file + diverged duplicate) |
| Governance law `source_refs` still cite pre-move `docs/<file>.md` paths | IMPLEMENTED (Phase 11) | `source_refs` updated to the canonical subdir paths in `app/governance.py` `DEFAULT_LAWS` + `data/governance/laws.json`; governance renderer is now deterministic (`_governance_updated_at()`), so re-render no longer dirties a clean checkout |
| Browser / visual E2E QA | BETA | Explicit owner authorization enabled real DEV/Canary/Production browser QA. Authenticated Canary/Production MES/MNQ charts, Documents/Admin, second clients and responsive breakpoints passed; broader owner design taste remains separate |

## E. Version readiness

- Current accepted version: `0.10.0-beta.29` (`VERSION.json`; channel `beta`, status `pre_release`). Live public API identity: git `4d15f1d2250e2c52bde02b902d88ec7aad043543`, build `sf-0.10.0-beta.29-4d15f1d2250e-20260823T020155Z`, runtime artifact SHA256 `CBA4FA70BD3868CBB80A8E8A42FE807B5401969CE09E1314671A73F51D132379` on both Canary and Production.
- Development runtime still defaults `RELEASE_CHANNEL=dev` even while VERSION.json describes the next candidate.
- `0.10.0-beta.29` current status: **STAGE CLOSED.** Market-data fan-out and responsive functional acceptance passed through Development, Canary and same-artifact Production. Google OAuth, Production transactional email, unrelated-user feed redistribution and physical Connector enrollment retain their explicit external boundaries.
- Environment vs release channel vs SemVer remain distinct: `DEPLOYMENT_ENV` (development/canary/production), `RELEASE_CHANNEL` (dev/beta/stable) and the SemVer string are separate fields.
