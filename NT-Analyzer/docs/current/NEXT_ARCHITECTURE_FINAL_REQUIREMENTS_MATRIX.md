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
| 7 | Isolated Canary contour + Developer Preview / View-As | IMPLEMENTED live (Telegram bot PARTIAL) | Live `canary.stratforges.com` on isolated DB/queue/storage; Developer Preview remains Development-only. Separate Canary Telegram bot not provisioned. Code: `assert_environment_isolation`, `deploy/canary/*`; merge `5955f2e5` (PR #13) |
| 8 | Release Center: immutable-artifact promotion state machine | BETA — real Canary workflow accepted | Release Center created clean candidate `7ebda6fa`, built and verified the production-signed artifact, deployed it to Canary and recorded granular `pass`/`blocked` checks. Production action remains separately owner-gated. Code: `app/release_center.py`, `app/release_executor.py`; evidence `docs/changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md` |
| 9 | Blue-green deployment tooling | BETA — real Canary deploy/rollback accepted | `stage9_ssh` executed all eight Canary stages, then a real previous-slot rollback and re-promotion to the same artifact (`rollback_verified=true`, `re_promoted=true`). Production switch was not invoked. Evidence: `docs/changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md` |
| 10A | Canonical docs tree spec + migration map + governance amendment hardening | IMPLEMENTED | `docs/DOCS_STRUCTURE.md`, `app/server.py` `_require_governance_manage` (owner/`docs.manage_global` on governance writes); `tests/test_phase10_docs_governance.py`; merge `bd4fbc47` (PR #16) |
| 10B | Physical documentation move + reference rewrite + language/changelog/matrix | PARTIALLY IMPLEMENTED | This branch: `git mv` of ~55 docs into canonical dirs, all markdown links + release manifest + tests + systemd + code comments updated; see §D for the honest residuals |

## B. Test & acceptance matrix (plan §10.11)

| Area | Status | Evidence |
|---|---|---|
| Unit/integration regression (runtime_env, permissions, auth identity, trusted devices, release state machine, resource lease, market data, docs, blue-green) | IMPLEMENTED | final clean-branch run: targeted `259 passed`; full `1303 passed, 31 skipped, 0 failed`; repository harness `13/13` suites PASS. Skips are only the three explicit live-PostgreSQL groups requiring `STRATFORGE_TEST_POSTGRES_*` |
| Migration (0001–0011, RLS, additive) | IMPLEMENTED locally; live Canary+Production applied 2026-08-12 | `0001..0011` on `stratforge_canary` and `stratforge_production`. UUID DML backfill on Production required postgres/BYPASSRLS replay |
| Auth / account linking (Telegram/Google/email OTP, no email auto-merge, last-method guard) | PARTIAL live | Telegram `login/start` on live `795db0c1` returns 200 and the waiting UI. Completing owner session still needs a real Telegram tap. Google **EXTERNAL BLOCKED** (no Production OAuth client). Email OTP **EXTERNAL BLOCKED** (no transactional provider; DEV test-auth only). Primary UI is Sign in/Register; promo/donation is optional. |
| Multi-device (pending/approve/reject/revoke, session invalidation) | IMPLEMENTED | `app/security_devices.py`; `tests/test_phase4_trusted_devices.py` |
| Permissions (owner/developer/ordinary, product modes, Mini App) | IMPLEMENTED | `app/permissions.py`; `tests/test_permissions.py`, `tests/test_ux_mode.py` |
| Environment isolation (cookie/CSRF/storage/DB/queue/host) | IMPLEMENTED live | Distinct Canary vs Production DB/role/queue/cookie/origin; CONNECT privilege negatives verified 2026-08-12 |
| Telegram separation (per-env bot/webhook/dedupe) | PARTIAL | Production Telegram READY. Canary has no separate bot (`disabled_pending_canary_bot_provisioning`) |
| Release promotion (clean commit, signature, artifact/manifest SHA, Canary checks, exact-artifact Production) | BETA | Release Center UI and real executor accepted through Canary on `7ebda6fa` / archive `AFBCEADF…` / manifest `CE09030A…`. Exact-artifact Production invariant remains enforced; this candidate has not been approved or promoted to Production |
| Blue-green / rollback (green readiness, drain, expand/migrate/contract, rollback switch) | BETA | Real Canary stages and rollback→re-promote PASS. Canary previous=`de7acaed`; Production remains `6b6dc458`, previous=`795db0c1`; no Production switch in this task |
| Connector pairing (P-256, signed hello, workspace/capability mismatch, canary contour) | IMPLEMENTED; real pairing EXTERNAL | `app/connector_protocol.py`; `tests/test_connector*`. Real device enrollment = EXTERNAL |
| Shared NinjaTrader locking (exclusive/queue/TTL/heartbeat/cancel) | IMPLEMENTED | `app/ninjatrader_resources.py`; `tests/test_phase6_*` |
| Documentation permissions (global governance not mutable by workspace/strategy override) | IMPLEMENTED | `app/server.py` `_require_governance_manage`, `app/governance.py` (global-only, no workspace param), `app/jobqueue.py` `update_strategy_profile` allowlist; `tests/test_phase10_docs_governance.py` |
| E2E owner/developer/ordinary user | PARTIAL | DEV owner/developer/admin/ordinary/disposable persona and new-user/permission surfaces were browser-tested; Canary public guest/auth boundary was browser-tested on `7ebda6fa`. Authenticated Canary/Production owner flows still require real Telegram action; Google/email remain EXTERNAL BLOCKED |

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
| Real Canary provisioning (isolated DB/DSN, Cloudflare tunnel, `canary.stratforges.com` DNS, separate Telegram bot, Canary Connector) | PARTIAL | Isolated DB/DNS/tunnel and real Release Center executor live; cross-environment DB CONNECT negatives rechecked 2026-08-13. Separate Canary Telegram bot not provisioned; no authenticated Canary Connector/chart session fabricated |
| Real Production deployment + exact-artifact promotion + real blue-green switch | EXTERNAL BLOCKED | Previous `6b6dc458` exact-artifact Production deployment remains live. New `7ebda6fa` artifact passed Canary but Production approval/execution requires a separate owner answer and was intentionally not performed |
| Live PostgreSQL migration acceptance (apply 0005–0011 to a real DB, RLS/restore) | IMPLEMENTED on live Canary+Production | Applied 2026-08-12. Isolated restore drill of Production dump PASS (5 users / 3 workspaces / max migration 4 before expand). UUID DML required postgres/BYPASSRLS replay |
| Production transactional email provider (email OTP / magic link delivery) | EXTERNAL BLOCKED | Code path exists; `available` is Development test-auth only. No `NTA_EMAIL_AUTH_PROVIDER` in Production. |
| Google OAuth login | EXTERNAL BLOCKED | Implementation present; Production env has no `NTA_GOOGLE_CLIENT_ID` / `SECRET` / `NTA_GOOGLE_REDIRECT_URI`. Redirect contract: `https://app.stratforges.com/api/auth/google/callback` |
| Market-calendar provider (Release Center "after market close" scheduling) | EXTERNAL DEPENDENCY / owner decision | Disabled in code (`market_calendar_unavailable`); needs timezone/holiday/early-close source |
| Full strategy-spec revision product module | IMPLEMENTED (Phase 11) | See §C — `strategy.spec.manage` + migration 0011 + `app/doc_specs.py` + API/UI + tests |
| Russian normalization of all user/product/governance docs | PARTIALLY IMPLEMENTED | Governance docs and agent docs are already Russian; several architecture/operations/product docs are mixed or English. Localization policy (Russian = canonical) recorded in `docs/LOCALIZATION.md`; a full normalization pass across every technical doc is a follow-up |
| Physical relocation of `AGENT_PERSONAS.md` / `VITEK.md` / `AI_DIALOGUE_CONTRACT.md` / duplicate `repository-hygiene.md` | NOT IMPLEMENTED (owner-gated) | See `docs/REQUIRES_OWNER_CLASSIFICATION.md` (dirty file + diverged duplicate) |
| Governance law `source_refs` still cite pre-move `docs/<file>.md` paths | IMPLEMENTED (Phase 11) | `source_refs` updated to the canonical subdir paths in `app/governance.py` `DEFAULT_LAWS` + `data/governance/laws.json`; governance renderer is now deterministic (`_governance_updated_at()`), so re-render no longer dirties a clean checkout |
| Browser / visual E2E QA | BETA | Explicit owner authorization enabled real DEV/Canary/Production read-only browser QA. DEV main pages, roles, Documents, Release Center and multi-browser MNQ/MES were exercised; Canary public surface passed. Authenticated Canary/Production chart smoke remains externally blocked by real auth, not replaced with a mock |

## E. Version readiness

- Current candidate version: `0.10.0-beta.1` (`VERSION.json`; channel `beta`, status `pre_release`). Canary runs git `7ebda6faf2e7c64d4a707a41062b29857882181a`, manifest SHA256 `CE09030A2050CBF7D2BCE985D90E36D0C0294F298178B862F4AFBDB0C3D351D3`, build `sf-0.10.0-beta.1-7ebda6faf2e7-20260813T093530Z`. Production remains on `6b6dc4589407855526cf6cc345376d64cf95200e`.
- Development runtime still defaults `RELEASE_CHANNEL=dev` even while VERSION.json describes the next candidate.
- `0.10.0-beta.1` current status: **CANARY CORE PASS WITH EXTERNAL BLOCKERS** on `7ebda6fa`; Production unchanged pending a separate owner answer. Remaining external blockers: Canary Telegram bot, authenticated server chart smoke, Google OAuth and Production transactional email.
- Environment vs release channel vs SemVer remain distinct: `DEPLOYMENT_ENV` (development/canary/production), `RELEASE_CHANNEL` (dev/beta/stable) and the SemVer string are separate fields.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-12T22:30:00Z | Grok 4.6 через Cursor по запросу owner | Record live 795db0c1 / D1CB6FF4 artifact: DEV restored, Production Sign in/Register, Telegram login/start 200.
2026-08-12T22:15:00Z | Grok 4.6 через Cursor по запросу owner | Reopen 0.10.0-beta.1 owner auth/DEV acceptance: Telegram storage_constraint, legacy promo gate, VERSION.json launcher block, Google/email EXTERNAL BLOCKED.
2026-08-12T21:30:00Z | GPT-5.5 через Codex по запросу owner | Record factual 0.10.0-beta.1 Canary PASS and exact-artifact Production promotion.
2026-08-11T08:13:16Z | GPT-5.5 через Codex по запросу owner | Removed the visible technical amendment header during final Development documentation closeout; historical evidence remains in Git history.
2026-08-13T08:31:00Z | GPT-5.5 через Codex по запросу owner | Recorded real Release Center Canary lifecycle, exact artifact identity, rollback rehearsal and browser acceptance; Production remained unchanged.
2026-08-13T09:49:37Z | GPT-5.5 через Codex по запросу owner | Recorded exact 7ebda6fa Canary artifact, mission-led Documents UI, live market-data soak and rollback/load acceptance; Production remained unchanged.
-->
