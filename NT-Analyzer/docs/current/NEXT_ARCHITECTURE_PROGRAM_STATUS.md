# Next Architecture Program Status

Канонический текущий статус программы StratForge AI. Здесь зафиксированы действующий baseline, завершённые этапы и открытые условия приёмки; история редакций доступна в журнале документов.

## Baseline

- Repository: `OMNOM-111/NT-Analyzer`
- Baseline: `72f46a1a3a1d32051a00d087808755676ec4d992`
- Baseline branch: `main`; при старте `HEAD == origin/main`, working tree clean
- Version at baseline: `0.9.0-dev.10`
- Release history: Git tags on non-baseline history reach `stratforge-server-v0.9.0-dev.15`; the next minor line avoids reusing any `0.9.0-dev.N` identifier
- Next version: `0.10.0-beta.1` (live Canary + Production hang-fix artifact `6b6dc458` as of 2026-08-12)
- Integration branch: `release/0.10.0-next-architecture` merged to `main` via [PR #26](https://github.com/OMNOM-111/NT-Analyzer/pull/26) (`5b43569d`); live artifact remains `6b6dc4589407855526cf6cc345376d64cf95200e`
- Production/Canary boundary: both live on the Supervisor host; Canary Telegram bot remains unprovisioned; Production Telegram is live; no live trading / real payments

## Сводка

| Phase | Status | Branch | Commit/PR | Ключевой результат |
|---|---|---|---|---|
| 0 | STAGE CLOSED | merged/deleted | `fe38c3b7`; [PR #6](https://github.com/OMNOM-111/NT-Analyzer/pull/6) | Принятые решения зафиксированы в ADR; CI PASS |
| 1 | STAGE CLOSED | merged/deleted | `f4bcb3fc`; [PR #7](https://github.com/OMNOM-111/NT-Analyzer/pull/7) | Environment metadata, version, badges, owner icons; CI PASS |
| 2 | STAGE CLOSED | merged/deleted | `ca65be2e`; [PR #8](https://github.com/OMNOM-111/NT-Analyzer/pull/8) | Admin Panel, explicit expiring grants и origin-isolated Environment Switcher; CI PASS |
| 3 | STAGE CLOSED | merged/deleted | `7fb34762`; [PR #9](https://github.com/OMNOM-111/NT-Analyzer/pull/9) | UUID identity, provider abstraction и dual-write compatibility; CI PASS |
| 4 | STAGE CLOSED | merged/deleted | `4c60df6c`; [PR #10](https://github.com/OMNOM-111/NT-Analyzer/pull/10) | Trusted devices, step-up challenges, migration 0006; CI PASS |
| 5 | STAGE CLOSED | merged/deleted | `1b4249cc`; [PR #11](https://github.com/OMNOM-111/NT-Analyzer/pull/11) | Personal NT security: two-factor + per-action step-up; CI PASS |
| 6 | STAGE CLOSED | merged/deleted | `93b1fced`; [PR #12](https://github.com/OMNOM-111/NT-Analyzer/pull/12) | Agent allocation и durable NinjaTrader lease/queue; CI PASS |
| 7 | IMPLEMENTATION COMPLETE (external Canary acceptance pending) | merged/deleted | `5955f2e5`; [PR #13](https://github.com/OMNOM-111/NT-Analyzer/pull/13) | Изолированный Canary-контур + Developer Preview / View-As без deployment; CI PASS |
| 8 | IMPLEMENTATION COMPLETE (external Canary/Production acceptance pending) | merged/deleted | `4efddb42`; [PR #14](https://github.com/OMNOM-111/NT-Analyzer/pull/14) | Release Center: immutable-artifact promotion state machine + migration 0009; CI PASS |
| 9 | IMPLEMENTATION CLOSED (external blue-green/Production acceptance pending) | merged/deleted | `3a787c6a`; [PR #15](https://github.com/OMNOM-111/NT-Analyzer/pull/15) | Blue-green deployment tooling (fail-closed dry-run) + migration 0010; CI PASS |
| 10 | 10A CLOSED; 10B PARTIAL — NOT fully closed | `bd4fbc47` (10A) / `phase/10b-documentation-finalization` | [PR #16](https://github.com/OMNOM-111/NT-Analyzer/pull/16) | 10A: docs-tree + map + governance gate. 10B: фактический перенос доков + matrix/changelog/language. Strategy-spec closed in Phase 11 |
| 12 | STAGE CLOSED — hang-fix live Canary+Production | `main` | live `6b6dc458`; merge `5b43569d`; [PR #26](https://github.com/OMNOM-111/NT-Analyzer/pull/26) MERGED; tag `stratforge-server-v0.10.0-beta.1-6b6dc458` | `/ready` 36ms; Environment Switcher DEV→CANARY→PROD; Telegram Production PASS / Canary PARTIAL; Google/email EXTERNAL BLOCKED |

## Phase 0 evidence

- Components: `docs/adr/*`, `docs/architecture/NEXT_ARCHITECTURE_OVERVIEW.md`, этот program status, governance change log и `.github/workflows/next-architecture-ci.yml`.
- Tests: `release_static_scan.py --scan markdown` — PASS; `--scan secrets` — PASS; targeted regression — `154 passed, 20 skipped`.
- CI: Ubuntu static gates PASS; Ubuntu tests PASS; Windows tests PASS; Actions run `30726953570`.
- Migrations: none.
- Risks: ADR может разойтись с runtime, если последующие phases обойдут acceptance tests.
- Rollback: revert documentation commit; runtime rollback не требуется.
- Remaining dependencies: последовательная реализация Phase 1–10; реальные email/bot credentials и deployment остаются owner gates.
- Environment impact: Development/Canary/Production behavior unchanged.

## Phase 1 evidence

- Components: `app/runtime_env.py`, server/runtime API, local launchers, immutable server release manifest/verifier, Production env template, Aurora shell/mode-entry UI, три owner icon assets.
- Runtime contract: `DEPLOYMENT_ENV=development|canary|production`; `RELEASE_CHANNEL=dev|beta|stable`; `APP_VERSION`, `BUILD_ID`, `GIT_COMMIT_SHA`, `ARTIFACT_SHA256`, `BUILD_TIMESTAMP_UTC`, `dirty` доступны через `/api/runtime/env`.
- Isolation: Canary имеет отдельный обязательный `STRATFORGE_CANARY_DATA_ROOT`; пересечение Development/Canary/Production roots и dirty remote build отклоняются.
- Visual contract: `DEV`, `CANARY`, `BETA`; stable Production без `STABLE`; favicon и внутренний mark выбираются по environment/channel.
- Local tests: focused `75 passed`; full regression `889 passed, 31 skipped`; post-fix server release verifier `6 passed`; PowerShell parse, `node --check`, `py_compile` — PASS.
- Static gates: CSP PASS; SECRETS PASS; MARKDOWN PASS.
- Signed Development artifact: self-verification PASS; 378 payload files; 4 migration checksums; artifact SHA-256 `95057E77329468B3D8A1710ECD384A2DC1133ADBBCE2E205217C0145D2734282`.
- CI/PR: [PR #7](https://github.com/OMNOM-111/NT-Analyzer/pull/7) merged; run `30728473002`; Static gates PASS; Ubuntu `890 passed, 31 skipped`; Windows `890 passed, 31 skipped`.
- Git closeout: implementation `e09cc180`; merge `f4bcb3fc`; task branch удалена локально и на origin; integration совпадает с origin после merge.
- Migrations: none.
- Rollback: revert Phase 1 commit; schema rollback не требуется.
- Environment impact: изменён только код и Development metadata; Canary/Production deployment, secrets, DNS, DB и реальные bot/email credentials не затронуты.
- Remaining CI note: GitHub показал non-blocking deprecation annotation для Node.js 20 внутри `actions/checkout@v4`/`actions/setup-python@v5`; Phase 1 checks при этом завершились SUCCESS, обновление action major versions не смешивалось с runtime scope.

## Phase 2 evidence

- Components: отдельный каталог administrative capabilities в `app/permissions.py`; owner-only grant/revoke в `app/account_auth.py`; server-side route authorization и Admin API в `app/server.py`; Admin Panel и Environment Switcher в Aurora UI.
- Authorization boundary: тарифы и product permissions не могут открыть control plane. Owner получает полный административный набор; non-owner получает только structured explicit grants с необязательным будущим UTC expiry; invalid, legacy-unstructured и expired grants fail closed.
- Capabilities: `admin.view`, `users.manage`, `workspaces.manage`, `connectors.manage`, `operations.view`, `operations.execute`, `releases.view`, `releases.create`, `releases.deploy_canary`, `releases.promote_production`, `releases.rollback_production`, `environment.switch`, `docs.manage_global`, `docs.manage_workspace`.
- UI boundary: личный кабинет содержит только `Профиль` и `Тарифы`; three-dot menu содержит кабинет, условный Admin Panel, настройки дизайна и logout. Operations, users, connectors и прежние owner tabs перенесены в server-filtered Admin Panel modules.
- Environment transition: top button виден только с `environment.switch`; Development принимает только loopback origin, Canary/Production — только HTTPS standard port. Переход открывает новый origin с `noopener,noreferrer`; cookies, CSRF, tokens и browser storage не передаются; Local DEV требует успешный credential-free identity probe.
- Compatibility: старый `/api/owner/operations` сохранён, но использует общий payload и тот же capability resolver; фактические Release Center workflows остаются scope Phase 8.
- Local tests: initial focused Admin/auth/UI/cutover suite — `102 passed`; full regression after contract update — `900 passed, 31 skipped`; final Phase 2/Auth/UI/Telegram suite — `154 passed`; Production public-runtime contract — `4 passed`; governance — `8 passed`.
- Static/syntax gates: CSP PASS; SECRETS PASS; MARKDOWN PASS; `node --check`, `py_compile`, `git diff --check` — PASS.
- Browser QA: не запускался согласно workspace stability policy; использованы HTTP, CORS/CSP и DOM/source contract tests.
- Migrations: none.
- Rollback: revert Phase 2 implementation commit; schema rollback не требуется; legacy operations endpoint остаётся совместимым.
- Environment impact: изменён код и UI Development checkout; Canary/Production deployment, secrets, DNS, DB и bot/email credentials не затронуты.
- CI/PR: [PR #8](https://github.com/OMNOM-111/NT-Analyzer/pull/8) merged; run `30730281079`; Static gates PASS; Ubuntu `900 passed, 31 skipped`; Windows `900 passed, 31 skipped`.
- Git closeout: implementation `2f33726f`; merge `ca65be2e`; task branch удалена локально и на origin; integration совпадает с origin после merge.

## Phase 3 evidence

- Components: provider-neutral UUID primitives в `app/auth_identity.py`; account/session/challenge/provider identity lifecycle в `app/account_auth.py`; Google login/link flow, email OTP development-test flow и provider status routes; UUID companions для workspaces, subscriptions, Connector, Community, scoped dialogues и SQLite chat index; Aurora provider-login UI.
- Identity contract: UUID — canonical internal account key. Legacy numeric `user_id`/`legacy_user_id` сохранён и dual-written для существующих Telegram users, profiles, workspaces, memberships, dialogs, Connector mappings и audit history. Public ordinary-user payload выдаёт UUID как `id`; administrative compatibility views сохраняют numeric keys.
- Session boundary: browser session state переносится в Telegram Mini App context только когда совпадают legacy numeric ID и canonical UUID, разрешённый account store; mismatch fails closed.
- Provider contract: Telegram, Google и verified email являются отдельными provider subjects. Совпадающий email сам по себе не объединяет accounts; link/unlink проверяет ownership provider subject и запрещает убрать последний usable login.
- Local migration behavior: DPAPI stores и scoped JSONL/SQLite documents lazily backfill UUID companions without removing numeric references. Account-store v2 migration creates a recoverable encrypted backup before persisting v3 dual-write data.
- PostgreSQL source migration: `0005_identity_uuid.sql` является additive expand/backfill/dual-write migration: UUID companions, `sf_auth_identities`, backfill, generated triggers and nonvalidated foreign keys. It contains no destructive contract or `DROP` statements.
- Local validation: focused Phase 3 suite `249 passed`; Community `14 passed`; account auth `35 passed`; final repository regression `925 passed, 31 skipped`. `python -B -m compileall -q app tests`, `node --check app/static/aurora/assets/ui.js`, release static scan (CSP/SECRETS/MARKDOWN) and `git diff --check` passed.
- CI/PR: [PR #9](https://github.com/OMNOM-111/NT-Analyzer/pull/9) merged; [Actions run 30765531139](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30765531139) SUCCESS; Static gates, Ubuntu tests и Windows tests PASS.
- PostgreSQL acceptance: skipped safely because isolated `STRATFORGE_TEST_POSTGRES_ADMIN_URL` and `STRATFORGE_TEST_POSTGRES_URL` were absent. No PostgreSQL migration was applied.
- Deployment boundary: no destructive contract, Production migration, Canary deployment or Production deployment was performed; no Production secrets, DNS, bot/email credentials or databases were accessed.
- Git closeout: implementation `2266fc99`; merge `7fb34762`; task branch удалена локально и на origin; integration совпадает с origin after merge. Generated `data/development/durable/nt_analyzer.sqlite3` and unrelated governance-rendered changes remained outside the Phase 3 delivery.

## Phase 4 evidence

- Components: изолированный `app/security_devices.py` (trusted-device registry + step-up challenges); session-correlation hook `account_auth._observe_session_device` в обоих путях создания сессии; device-revoke notice в `session_auth_failure`/`_cleanup`; self-service HTTP-контур `/api/account/security`, `/api/account/devices` и mutation-эндпоинты в `app/server.py`; Aurora cabinet вкладка `Безопасность` в `app/static/aurora/assets/ui.js` и клиенты в `api.js`.
- Data model: `app/production_storage/migrations/0006_trusted_devices.sql` — additive expand-only. Создаёт `sf_trusted_devices` (device_id UUID, user_uuid canonical, legacy_user_id для RLS-scope, masked audit_metadata) и `sf_security_challenges` (challenge_id, purpose/provider/environment binding, PBKDF2 `code_hash`+`code_salt`, attempts/max_attempts). RLS enable/force + `sf_scope_global() OR legacy_user_id = sf_scope_user()`; нет `DROP`, нет contract.
- Lifecycle: устройство имеет случайный UUID и server-side статус `pending -> trusted -> revoked|expired`. Новая сессия регистрируется как `pending` и никогда не становится trusted автоматически; revoked/expired fingerprint не переиспользуется. Trust выдаётся только после подтверждения challenge через telegram/email/google verified email.
- Security invariants (проверены тестами): cross-user read/approve/reject/revoke закрыт (device_not_found); legacy numeric id не обходит UUID ownership; совпадение email/IP/UA/fingerprint не выдаёт trust; challenge одноразовый, purpose/device/environment/user-bound, attempt-capped, replay-safe; concurrent consume даёт единственного победителя; revoked-устройство завершает только свои сессии; чужие устройства и другой пользователь не затронуты; legacy-сессии без device продолжают авторизацию (нет mass lockout); секреты/OTP/raw fingerprint/raw IP не попадают в public API или audit.
- Audit events: `device.pending/approved/rejected/revoked`, `security.challenge_created/succeeded/failed/expired/denied`, `session.revoked_by_device` через `account_auth._audit`; код и токены в audit не пишутся.
- Backward compatibility / rollback: expand-only. Rollback Phase 4 останавливает approval новых устройств и оставляет session/device/challenge records и UUID identity mapping нетронутыми; revoked не возвращается в trusted; existing sessions не очищаются.
- Local validation: focused Phase 4 suite `29 passed`; auth-related suites (`test_phase_a_auth`, `test_account_auth`, `test_permissions`, `test_nt_dual_auth`) `70 passed`; final repository regression `954 passed, 31 skipped`. `python -B -m compileall -q app tests`, `node --check` (ui.js/api.js), release static scan CSP/SECRETS/MARKDOWN — все PASS; `git diff --check` — только CRLF-нормализация на посторонних governance/docs файлах, без whitespace-ошибок в Phase 4 файлах.
- PostgreSQL acceptance: migration 0006 покрыта статическим контрактным тестом без БД; live acceptance пропущен безопасно, потому что `STRATFORGE_TEST_POSTGRES_ADMIN_URL`/`STRATFORGE_TEST_POSTGRES_URL` отсутствовали. Никакая PostgreSQL migration не применялась к Production или Canary.
- Deployment boundary: Production не изменялась; Canary не изменялся; deployment не выполнялся; main не затронут; Production secrets, DNS, bot/email credentials и базы данных не использовались.
- Residual: реальная доставка кода через Telegram/email — owner gate (в Development test-auth код echo только за явным gate); production email provider остаётся отдельным решением. Посторонние dirty/untracked файлы (`data/development/durable/nt_analyzer.sqlite3`, `data/governance-rendered/*`, `docs/AGENT_PERSONAS.md`, `docs/governance/*`) не трогались и не включались в commit.
- CI/PR: [PR #10](https://github.com/OMNOM-111/NT-Analyzer/pull/10) merged; [Actions run 30769037213](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30769037213) SUCCESS; Static gates, Ubuntu tests и Windows tests PASS.
- Git closeout: implementation `2ec986b4`; merge `4c60df6c`; task branch удалена локально и на origin; integration совпадает с origin after merge. Посторонние dirty/untracked файлы сохранены на диске и остались вне Phase 4 delivery.

## Phase 5 evidence

- Components: изолированный `app/personal_nt_security.py` (factors + per-action step-up); generalized identity factor и email-фактор в `account_auth.nt_action_gate`/`require_nt_dual_auth`; self-service `unlink_identity_self`/`list_account_identities`; `security_devices` challenge получил `action`-binding; `workspaces.set_default_connection`/`set_connection_capabilities`; server API и Aurora onboarding/step-up UI.
- Factor model: личный NinjaTrader требует подтверждённый Telegram И verified email. Verified email login identity или безопасно привязанный Google verified email закрывают email-фактор; Telegram остаётся обязательным независимым каналом. Owner exempt.
- Step-up model: подтверждённый `step_up` challenge (Phase 4 machinery + `action`) становится single-use grant, привязанным к (user UUID, action, deployment environment). Критическое действие расходует ровно один grant; grant нельзя переиграть, использовать для другого action, перенести между окружениями или применить другим пользователем. Grant TTL 10 минут от consumption. Development test-auth helper выдаёт grant без реального кода, чтобы owner/developer тесты не блокировались.
- Guarded actions: pairing (`/api/bridge/pair/start` + connector enroll, require ready + step-up), pair complete (require ready), connector revoke (step-up), default account change (ready + step-up), trading capability raise до live (ready + step-up), self-service identity unlink (step-up + last-method guard). Owner exempt.
- Data model: `app/production_storage/migrations/0007_step_up_actions.sql` — additive expand-only: `ALTER TABLE sf_security_challenges ADD action, step_up_used_at` + partial index + length check. Нет `DROP`, нет contract.
- API: `GET /api/account/nt-security`, `GET /api/account/identities`; `POST /api/account/nt-security/step-up/{start,confirm,staging}`, `POST /api/account/identities/unlink`; `POST /api/bridge/connections/{id}/{default,capabilities}`. Все self-service, server-side authorization по user_id/UUID.
- Security invariants (проверены тестами): missing Telegram/email → onboarding; Google verified email = email-фактор; email OTP identity = email-фактор; pairing без grant отклоняется; step-up single-use; action/environment/user binding; cross-user grant не работает; challenge_id binding; unlink последнего способа входа запрещён; cross-user unlink → not found; owner exempt; staging helper. E-mail код не называется SMS.
- Audit: `security.step_up_consumed`, `identity_unlinked`, `bridge_default_connection_set`, `bridge_connection_capabilities_set`; step-up challenge lifecycle через Phase 4 `security.*` events. Коды/токены в audit не пишутся.
- Backward compatibility / rollback: expand-only. Существующие Telegram-пользователи и NT-команды не сломаны; email-фактор generalization additive; rollback останавливает новые pairing/critical-action approvals и оставляет challenge/grant/identity records и UUID mapping нетронутыми; revoked не возвращается.
- Local validation: focused Phase 5 suite `30 passed`; regression-sensitive suites (`test_workspaces`, `test_nt_dual_auth`, `test_phase_a_auth`, `test_permissions`, `test_phase4_trusted_devices`) `77 passed`; final repository regression `984 passed, 31 skipped`. `python -B -m compileall -q app tests`, `node --check` (ui.js/api.js), release static scan CSP/SECRETS/MARKDOWN и `git diff --check` (Phase 5 файлы) — PASS.
- PostgreSQL acceptance: migration 0007 покрыта статическим контрактным тестом; live acceptance пропущен безопасно (нет `STRATFORGE_TEST_POSTGRES_*`). Никакая migration не применялась к Production или Canary.
- Deployment boundary: Production не изменялась; Canary не изменялся; deployment не выполнялся; main не затронут; Production secrets, DNS, bot/email credentials и базы данных не использовались.
- Residual: реальная доставка step-up кода через Telegram/email — owner gate (Development test-auth echo только за явным gate); production email provider — отдельное решение. Посторонние dirty/untracked файлы (`data/development/durable/nt_analyzer.sqlite3`, `data/governance-rendered/*`, `docs/AGENT_PERSONAS.md`, `docs/governance/*`) не трогались и не включались в commit.
- CI/PR: [PR #11](https://github.com/OMNOM-111/NT-Analyzer/pull/11) merged; [Actions run 30771449462](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30771449462) SUCCESS; Static gates, Ubuntu tests и Windows tests PASS.
- Git closeout: implementation `5506704f`; merge `1b4249cc`; task branch удалена локально и на origin; integration совпадает с origin after merge. Посторонние dirty/untracked файлы сохранены на диске и остались вне Phase 5 delivery.

## Phase 6 evidence

- Components: новый `app/ninjatrader_resources.py` (durable resource lease + FIFO очередь поверх workspace store) и `app/agent_allocation.py` (детерминированное распределение агентов); server API `/api/ninjatrader/*` и `/api/admin/ninjatrader/resources`; capability-gating в `app/permissions.py`; Aurora anonymized shared-NT queue UI.
- Agent allocation (ADR-0006): personal NinjaTrader workspace → изолированная Agent Team (`Управляющий` + специалисты Толик/Иван/Никита/Марина), scoped к workspace/Connector/accounts, без fallback на owner runtime; owner-training user → один ограниченный `Координатор` ниже Виктора, только training/backtest, без owner team и admin; owner → полная команда. Аллокация определяется workspace kind + entitlement + connection type, не глобальным аккаунтом.
- Resource lease: `NinjaTraderResourceLease` states queued/active/released/expired/cancelled/failed. Атомарный acquire под workspace lock; один активный exclusive lease на shared owner-training resource; FIFO по `queue_seq`; idempotency по (resource, user UUID, key); TTL + heartbeat + crash recovery + cancel + expiration; read-only параллелизм только для явного `readonly` из proven allow-list (`telemetry_read`); read-write lock semantics. Personal job привязан к personal resource и никогда не использует owner-training runtime.
- Token discipline: lease token генерируется server-side, возвращается worker-у один раз; хранится только sha256 hash, не логируется; client-provided token не доверяется; heartbeat/release проверяют hash; ownership (workspace/user/resource) проверяется server-side по UUID.
- Anonymized UI: обычный пользователь видит только свободен/выполняется/в очереди, свою позицию и upsell личного NinjaTrader — без чужой identity, workspace, account, strategy, job metadata или token. Owner/admin detail защищён `operations.view`/`operations.execute` server-side.
- Data model: `app/production_storage/migrations/0008_ninjatrader_resource_leases.sql` — additive expand-only: `sf_ninjatrader_resource_leases` с RLS (`sf_scope_global() OR workspace_id = sf_scope_workspace() OR requested_by_legacy_id = sf_scope_user()`), partial unique idx «один active exclusive на resource» и idempotency idx, masked document metadata. Нет `DROP`, нет contract. Agent allocation детерминирована и не требует таблицы.
- Security invariants (проверены тестами): два конфликтующих owner-training job не active одновременно; read-only не параллелен без явного parallel_group; personal job без owner-runtime fallback; чужой workspace/lease недоступен; нельзя отменить чужой job; idempotency retry не создаёт дубль; expired lease безопасно восстанавливается; stale token не работает после release/expire; неверный heartbeat отклоняется; worker crash не блокирует навсегда; cancel/expiration не приводят к двойному выполнению; queue position не раскрывает identity; admin detail capability-gated; ordinary user не получает полную Agent Team; UUID boundaries Phase 3–5 сохранены.
- Local validation: focused Phase 6 suite `29 passed`; routing/permission suites (`test_workspaces`, `test_permissions`, `test_cutover_routing`, `test_aurora_contracts`) `73 passed`; final repository regression `1013 passed, 31 skipped`. `python -B -m compileall -q app tests`, `node --check` (ui.js/api.js), release static scan CSP/SECRETS/MARKDOWN и `git diff --check` (Phase 6 файлы) — PASS.
- PostgreSQL acceptance: migration 0008 покрыта статическим контрактным тестом; live acceptance пропущен безопасно (нет `STRATFORGE_TEST_POSTGRES_*`). Никакая migration не применялась к Production или Canary; очереди и NinjaTrader не изменялись.
- Deployment boundary: Production не изменялась; Canary не изменялся; deployment не выполнялся; main не затронут; Production secrets, DNS, bot/email credentials, реальный Connector pairing и базы данных не использовались.
- Rollback: expand-only. Остановка scheduling новых shared jobs и безопасная отмена queued jobs; active leases дожидаются или истекают; audit и job history сохраняются; personal NT mappings не теряются; personal jobs не получают owner-runtime fallback.
- Residual / owner decision (non-blocking): персона `Координатор` взята из ADR-0006 (утверждена). Реальная интеграция с исполнением backtest/optimization в orchestrator/worker остаётся последующей работой; текущая фаза даёт durable lease/queue контракт и allocation policy.
- CI/PR: [PR #12](https://github.com/OMNOM-111/NT-Analyzer/pull/12) merged; [Actions run 30779156395](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30779156395) SUCCESS; Static gates, Ubuntu tests и Windows tests PASS.
- Git closeout: implementation `7f3dba64`; merge `93b1fced`; task branch удалена локально и на origin; integration совпадает с origin after merge. Посторонние dirty/untracked файлы сохранены на диске и остались вне Phase 6 delivery.

## Phase 7 evidence

Status: **IMPLEMENTATION COMPLETE; REAL CANARY PROVISIONING AND EXTERNAL ACCEPTANCE PENDING OWNER APPROVAL — NOT STAGE CLOSED.** Полное evidence: `docs/current/PHASE_7_CANARY_IMPLEMENTATION_EVIDENCE.md`.

- Components: `app/runtime_env.py` (per-environment cookie/local-storage/telegram namespaces + fail-closed `assert_environment_isolation`, wired в `assert_startup_safe`); `app/server.py` (per-environment session cookie name + dev preview/bootstrap routes); `app/telegram_service.py` (environment marker в исходящих сообщениях); `app/connector_protocol.py` (environment-stamped installations + cross-environment rejection); `app/service_readiness.py` (Canary держится того же control-plane readiness контракта, что и Production); `tools/production_preflight.py` (named `environment_isolation` check); `deploy/canary/*` (secret-free Linux Canary templates + runbook); новый `app/dev_preview.py` и Aurora `ui.js`/`api.js`/`theme.css`.
- Isolation contract: Canary имеет отдельные database/queue/object-storage/telegram/cookie/signing/log/instance identities, origin `https://canary.stratforges.com`, обязательный `STRATFORGE_CANARY_DATA_ROOT`, cookie `sf_canary_session`, local-storage namespace `canary` и `[CANARY] ` Telegram marking. Любое совпадение identity/DSN/data-root/allowed-hosts с Production reference identifiers отклоняется fail-closed на старте и в preflight; симметричный guard защищает Production от объявленного Canary bot id. Connector installation привязана к окружению и отклоняется при cross-environment использовании (`connector_environment_mismatch`).
- Developer Preview / View-As: Development-only. Owner видит приложение глазами роли через реальные серверные права выбранной persona без изменения реальных ролей; persistent `VIEW AS` marking; быстрый возврат к developer session (loopback return работает и для unauthenticated persona). Single-use, time-boxed, loopback-only, hash-only bootstrap открывает Development как владелец из отдельного браузера. Developer persona получает только `admin.view`/`operations.view`/`environment.switch`, не owner set. Fail-closed в Canary/Production; в Production dev bootstrap и View-As отсутствуют; audit не содержит raw token. В Canary нет dev-login bypass — доступ только через реальный Canary account + capability grants.
- Local validation: focused `tests/test_phase7_canary_isolation.py` `28 passed` + `tests/test_phase7_dev_preview.py` `18 passed`; final repository regression `1059 passed, 31 skipped`. `python -m compileall -q app tools`, `node --check` (ui.js/api.js), release static scan CSP/SECRETS/MARKDOWN и `git diff --check` — PASS.
- Errors fixed: пять тестов с hand-rolled `Request` doubles сломались после введения per-environment cookie name — cookie sites переведены на прямой `runtime_env.session_cookie_name()` и wrapper удалён; bootstrap replay возвращал `token_not_found` вместо `token_used` — использованный токен сохраняется до следующего mint. Оба покрыты регрессией/фокусными тестами.
- External checks intentionally NOT run: реальный Canary/Production deployment; Cloudflare/DNS; создание реальной Canary DB; применение migrations к реальным DB; реальный Telegram webhook/token; реальный Connector pairing; изменение сервера. Browser QA не запускался (workspace stability policy).
- Missing infra (owner-gated): изолированная Canary PostgreSQL DB/DSN, Canary Cloudflare tunnel + `canary.stratforges.com` DNS, отдельный Canary Telegram bot token/webhook secret, Canary Connector контур.
- Migrations: none (Canary использует существующую схему).
- Rollback: revert Phase 7 implementation/merge commit; schema rollback не требуется; `deploy/canary/*` и `app/dev_preview.py` инертны без явной конфигурации `DEPLOYMENT_ENV=canary`/`development`.
- Environment impact: изменён только код, Development/Canary конфигурационные templates и UI. Production и Canary серверы, Cloudflare, DNS, реальные базы, реальные secrets, реальные Telegram credentials и реальные Connector sessions не затронуты.
- CI/PR/Git closeout: [PR #13](https://github.com/OMNOM-111/NT-Analyzer/pull/13) merged; [Actions run 30782625524](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30782625524) SUCCESS (Static gates, Ubuntu tests, Windows tests PASS); implementation `2a4f4839`; merge `5955f2e5`; task branch удалена локально и на origin; integration совпадает с origin after merge. Посторонние dirty/untracked файлы сохранены на диске и остались вне Phase 7 delivery. External Canary acceptance (real DB/DNS/tunnel/Telegram/Connector) остаётся owner gate; этап не STAGE CLOSED.

## Phase 8 evidence

Status: **IMPLEMENTATION COMPLETE; REAL CANARY DEPLOYMENT / PRODUCTION PROMOTION ACCEPTANCE PENDING OWNER APPROVAL — NOT STAGE CLOSED.** Полное evidence: `docs/current/PHASE_8_RELEASE_CENTER_IMPLEMENTATION_EVIDENCE.md`.

- Components: новый `app/release_center.py` (immutable-artifact promotion state machine, exact-artifact invariants, encrypted/Postgres document store, redacted audit, fail-closed dry-run deployment adapter, scheduling, notifications, step-up); `app/production_storage/migrations/0009_release_center.sql` (8 таблиц, additive expand-only, global-scope RLS); server API + per-action permissions + step-up; Aurora `Центр релизов` UI (`ui.js`/`api.js`).
- State machine: `draft → building → built → signed → canary_deploying → canary_checking → canary_passed → approved_for_production → production_scheduled → production_deploying → production_live`; failure/terminal `build_failed`, `canary_failed`, `production_failed`, `rolled_back`, `superseded`, `cancelled`. Каждый переход валидируется server-side по allow-map (пропущенные/обратные отклоняются), имеет idempotency key, capability, step-up для критических действий, audit с actor UUID и timestamp; повтор запроса не создаёт двойной deployment/approval.
- Data model: migration 0009 — `sf_release_artifacts/candidates/deployments/checks/approvals/rollbacks/notifications/events`; UUID, app_version, channel, build_id, commit, artifact/manifest SHA-256, signature status, evidence JSON, failure reason, idempotency; global RLS `sf_scope_global()`; unique `(artifact_sha256, manifest_sha256, git_commit_sha, build_id)`; idempotency и one-active-deployment unique indexes. Никаких signing keys/tokens/credentials в БД, UI, логах или evidence. `latest_version` = 9 (auto-discovered).
- Exact-artifact controls (проверены тестами): dirty worktree не создаёт публикуемый кандидат/сборку; artifact immutable после сборки; verify требует `verified` подпись и замораживает fingerprint; любой дрейф artifact/manifest/commit/build после подписи отклоняется; Canary и Production ссылаются на один fingerprint; Production promotion требует совпадающего Canary pass, живого owner approval, привязанного к тому же fingerprint, и свежего step-up; rollback только на ранее развёрнутый в Production artifact.
- Deployment adapter: fail-closed dry-run. Реальный executor не подключён (Phase 9); внешний результат всегда PENDING, `production_live` достигается только отдельным owner-подтверждением `mark-production-live` — dry-run не может подделать live-deploy. Scheduling: now/in_5m/in_15m/explicit; «после закрытия рынка» отключено (`market_calendar_unavailable`) до утверждённого календаря — owner decision зафиксирован. Notifications: записи scheduled_update/warn_5m/warn_60s/deploy_started/deploy_successful/deploy_failed/rollback/reload_available без реальной отправки.
- Permissions: `releases.view/create/deploy_canary/promote_production/rollback_production`. Owner — полный доступ; delegated admin — только явные grants; ordinary user не видит Release Center и получает server-side denial. Route gate `/api/admin/releases` = `releases.view`, per-action capability в handler.
- Local validation: focused `tests/test_phase8_release_center.py` `34 passed`; full regression `1093 passed, 31 skipped`. `python -m compileall -q app tools tests`, `node --check` (ui.js/api.js), release static scan CSP/SECRETS/MARKDOWN, `git diff --check` — PASS.
- Errors fixed: 20 фокусных тестов сначала падали из-за idempotency-ключей короче 8 символов (инвариант, совпадающий с migration CHECK); ключи в тестах удлинены, product assertions не ослаблены.
- External checks intentionally NOT run: реальный Canary/Production deployment; SSH/Cloudflare/DNS/systemd/реальные DB команды; реальные signing keys/Production credentials/Telegram/Connector; применение migration к реальным DB. Browser QA не запускался (workspace stability policy).
- Migrations: `0009_release_center.sql` (additive expand-only). Rollback: revert Phase 8 implementation/merge commit; таблицы пустые, data rollback не требуется; `app/release_center.py` инертен без использования.
- Environment impact: изменён только код, UI и миграция-исходник. Production и Canary серверы, Cloudflare, DNS, реальные базы, реальные secrets/signing keys, реальные Telegram credentials и реальные Connector sessions не затронуты.
- CI/PR/Git closeout: [PR #14](https://github.com/OMNOM-111/NT-Analyzer/pull/14) merged; [Actions run 30807581743](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30807581743) SUCCESS (Static gates, Ubuntu tests, Windows tests PASS); implementation `4d529f49`; merge `4efddb42`; task branch удалена локально и на origin; integration совпадает с origin after merge. Посторонние dirty/untracked файлы сохранены на диске и остались вне Phase 8 delivery. External Canary/Production acceptance (реальный Canary deployment и exact-artifact Production promotion) остаётся owner gate; этап не STAGE CLOSED.

## Phase 9 evidence

Status: **IMPLEMENTATION COMPLETE; REAL BLUE-GREEN DEPLOYMENT / PRODUCTION PROMOTION ACCEPTANCE PENDING OWNER APPROVAL — NOT STAGE CLOSED.** Полное evidence: `docs/current/PHASE_9_BLUE_GREEN_IMPLEMENTATION_EVIDENCE.md`.

- Components: новый `app/blue_green.py` (fail-closed dry-run blue-green engine: symlink slot-model, expand→migrate→contract классификация миграций, graceful worker-drain, webhook/outbox replay-dedupe, green-readiness gate через `service_readiness`, traffic-switch и rollback-switch планы, maintenance-window записи, ordered deployment plan, rehearsal); `app/production_storage/migrations/0010_blue_green_deploy_steps.sql`; интеграция в `app/release_center.py` (deploy step log + maintenance записи, rollback traffic-switch evidence, `rehearse_blue_green`); server rehearsal endpoint; Aurora `Центр релизов` blue-green UI; deploy templates `deploy/production/blue-green/*` и `docs/PRODUCTION_BLUE_GREEN_RUNBOOK.md`.
- Blue-green mechanism (owner decision #7 — symlink/current-release switch): два слота `blue`/`green` и атомарная символьная ссылка `current`. Ordered plan: `prepare_green → expand_migrate → start_green → green_readiness → drain_blue → switch_traffic → verify_live → contract_migrate`. Только online-safe expand-миграции идут до переключения; destructive contract-миграции откладываются до стабильного green. Rollback — обратное переключение символьной ссылки на предыдущий совместимый слот с сохранением persistent data.
- Fail-closed dry-run: реальный executor не подключён; `deployment_strategy.real_available=False` всегда; именованный `STRATFORGE_BLUEGREEN_EXECUTOR` → `blocked` с PENDING; без него → локальный `dry_run` с PENDING. Release Center оставляет Production в `production_deploying`; `production_live` достигается только отдельным owner-подтверждением `mark-production-live` — dry-run не подделывает live-deploy. Отсутствие инфраструктуры = PENDING/BLOCKED, не PASS.
- Migration compatibility: `classify_migrations` делит миграции на expand (additive/online-safe) и contract (drop table/column/constraint, alter column type, set not null, rename, truncate, delete). Guarded `DROP POLICY/INDEX/TRIGGER/FUNCTION IF EXISTS` — online-safe. В dry-run без целевой БД pending-набор неизвестен → expand-стадия честно `pending` (весь исторический набор не считается pending). Консервативная классификация проверена на реальном наборе (0004 `SET NOT NULL` = contract).
- Data model: migration 0010 — `sf_release_deploy_steps` (deployment/candidate FKs, environment, strategy, stage, ordinal, status, active/target slot, redacted evidence) и `sf_maintenance_windows` (candidate FK, environment, kind, state, reason, timestamps, redacted document); additive expand-only; global RLS `sf_scope_global()`. `latest_version` = 10 (auto-discovered). Никаких signing keys/tokens/credentials/абсолютных host-путей в БД, UI, логах или evidence.
- Permissions: rehearsal `POST /api/admin/releases/{id}/rehearse-bluegreen` = `releases.deploy_canary` (новых capability не вводилось). Owner — полный доступ; delegated admin — только явный grant; ordinary user — server-side denial.
- Local validation: focused `tests/test_phase9_blue_green.py` `43 passed`; full regression `1136 passed, 31 skipped`. `python -m compileall -q app tools tests`, `node --check` (ui.js/api.js), release static scan CSP/SECRETS/MARKDOWN, `git diff --check` — PASS.
- Errors fixed: (1) тест rollback стартовал из `production_deploying`, что запрещено картой переходов Phase 8 — путь исправлен через owner-confirmed `mark-production-live` (Phase 8 guard не менялся, без scope creep); (2) `test_migration_0010_is_additive` падал из-за литералов «DROP TABLE»/«DROP COLUMN» в комментарии миграции — комментарий переформулирован как в 0009, схема осталась additive.
- External checks intentionally NOT run: реальный Canary/Production deployment; реальный blue-green traffic switch; SSH/systemd/symlink switch/Cloudflare/DNS/реальные DB команды; реальные signing keys/Production credentials/Telegram/Connector; применение migration к реальным DB. Browser QA не запускался (workspace stability policy).
- Migrations: `0010_blue_green_deploy_steps.sql` (additive expand-only). Rollback: revert Phase 9 implementation/merge commit; таблицы пустые, data rollback не требуется; `app/blue_green.py` инертен без развёртывания/репетиции; deploy templates инертны без явного executor и действия оператора.
- Environment impact: изменён только код, UI, миграция-исходник и deploy templates/runbook. Production и Canary серверы, Cloudflare, DNS, реальные базы, реальные secrets/signing keys, реальные Telegram credentials и реальные Connector sessions не затронуты.
- CI/PR/Git closeout: [PR #15](https://github.com/OMNOM-111/NT-Analyzer/pull/15) merged; [Actions run 30825143931](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30825143931) SUCCESS (Static gates, Ubuntu tests, Windows tests PASS); implementation `86b0ed4e`; merge `3a787c6a`; task branch `phase/9-blue-green` удалена локально и на origin; integration совпадает с origin after merge. **IMPLEMENTATION CLOSED / GIT CLOSEOUT COMPLETE**; external blue-green/Production deployment acceptance (реальный Canary deployment и exact-artifact Production blue-green promotion) остаётся owner gate — этап не STAGE CLOSED. Посторонние dirty/untracked файлы (`data/catalog/margins.json`, `data/development/durable/nt_analyzer.sqlite3`, `data/development/audit/`, `data/development/integrations/`, `data/governance-rendered/*`, `docs/AGENT_PERSONAS.md`, `docs/governance/*`) сохранены на диске и остались вне Phase 9 delivery.

## Phase 10 evidence

Status: **IMPLEMENTATION COMPLETE.** Полное evidence: `docs/current/PHASE_10_DOCS_GOVERNANCE_IMPLEMENTATION_EVIDENCE.md`.

- Components: канонический docs-tree + migration map `docs/DOCS_STRUCTURE.md`; новые каталоги `docs/{security,product,agents,strategies,changelog,archive,archive/audits}` с index READMEs; ужесточение governance amendment workflow в `app/server.py` (`_require_governance_manage`); `tests/test_phase10_docs_governance.py`.
- Canonical tree (acceptance: current vs target separated): создан `docs/{current,architecture,operations,security,product,agents,strategies,governance,changelog,adr,archive}` (+ `archive/audits`, `schemas`). `docs/current/` — только активная next-architecture программа; dated audits маппятся в `docs/archive/`. `docs/DOCS_STRUCTURE.md` — authoritative migration map (каждый loose-документ → целевой каталог, список из ~14 dated audits в archive, rename `PRODUCT_MODES...2026-07-18 → archive/audits/2026-07-18-product-contours.md`).
- Staged relocation: физический перенос уже-ссылающихся документов НЕ выполняется в этой фазе — у dated audits **32 inbound-ссылки в 21 файле** (включая repo-root `README.md`, `STRATFORGE_ГЕНЕРАЛЬНЫЙ_ПЛАН.md`, `docs/AGENTS.md`). Plan требует owner-approved migration map как зависимость. Phase 10 отдаёт tree + map на owner-approval; каждый `git mv` + reference-rewrite выполняется owner-approved шагом, проверяется markdown link audit, ни один перенос не оставляет битую ссылку.
- Governance amendment workflow (acceptance + owner decision #9): `POST /api/governance/laws|documents` раньше был защищён только read-level `documents`; теперь `_require_governance_manage` требует owner ИЛИ `docs.manage_global` (high-risk grant, по умолчанию только у owner), иначе `403 governance_manage_required`. GET-чтение остаётся на `documents`. Amendment journal (`data/governance/change_log.jsonl`: actor/reason/ts_utc/amendment_no/changes) без изменений и уже совместим.
- Global governance не изменяется workspace/strategy override (acceptance): governance — единый глобальный store; `update_law`/`update_markdown_document` не принимают workspace/tenant/scope; `jobqueue.update_strategy_profile` имеет строгий allowlist без governance-полей и не вызывает `governance.update_*`; stores `data/governance/` и `data/profiles/` disjoint; запись governance дополнительно owner/`docs.manage_global`-gated на HTTP-границе.
- Local validation: focused `tests/test_phase10_docs_governance.py` `12 passed`; regression-sensitive suites `94 passed`; full regression `1148 passed, 31 skipped`. `python -m compileall -q app tools tests`, release static scan CSP/SECRETS/MARKDOWN, `git diff --check` — PASS.
- Errors: none (governance guard не регрессировал ни один suite; единственный governance HTTP-тест — GET, не затронут).
- Rollback: revert Phase 10 implementation/merge commit; каталоги/READMEs/`DOCS_STRUCTURE.md` additive; guard — один серверный метод; schema/migration в Phase 10 не менялись.
- Environment impact: изменён только `app/server.py` + docs. Production/Canary/main, реальные базы, secrets, DNS/Cloudflare не затронуты.
- CI/PR/Git closeout: implementation commit, PR в `release/0.10.0-next-architecture`, cross-platform CI и merge commit будут записаны в Phase 10 closeout после CI PASS. Посторонние dirty/untracked файлы сохранены на диске и остались вне Phase 10 delivery.

### Phase 10 closeout

- [PR #16](https://github.com/OMNOM-111/NT-Analyzer/pull/16) merged; [Actions run 30829268990](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30829268990) SUCCESS (Static gates, Ubuntu tests, Windows tests PASS); implementation `25fffb42`; merge `bd4fbc47`; task branch `phase/10-documentation` удалена локально и на origin; integration совпадает с origin after merge. **IMPLEMENTATION CLOSED / GIT CLOSEOUT COMPLETE**. Физическое массовое перемещение документов по `docs/DOCS_STRUCTURE.md` выполняется owner-approved шагами (миграционная карта = требуемая зависимость).

## Phase 10B evidence

Status: **Phase 10 NOT fully closed.** Полное evidence: `docs/current/PHASE_10B_DOCUMENTATION_FINALIZATION_EVIDENCE.md`; полный аудит требований: `docs/current/NEXT_ARCHITECTURE_FINAL_REQUIREMENTS_MATRIX.md`.

- Актуальный отчёт Phase 10A преждевременно объявил Phase 10 закрытой. Phase 10B выполняет фактическую работу: `git mv` ~55 документов в канонические каталоги (`agents/architecture/operations/strategies/product/changelog/archive` + `archive/audits`) с обновлением всех markdown-ссылок, release-manifest (`tools/build_server_release.py` + `tests/test_server_release.py`), 3 runbook-path тестов, systemd unit'ов, `.gitattributes`, code comments и repo/user docs.
- Не перемещены (owner-gated, `docs/REQUIRES_OWNER_CLASSIFICATION.md`): `AGENT_PERSONAS.md` (stray dirty), `VITEK.md`+`AI_DIALOGUE_CONTRACT.md` (ссылаются как siblings из dirty AGENT_PERSONAS.md), дублирующийся `repository-hygiene.md` (расходящийся контент).
- Language: `docs/LOCALIZATION.md` — русский canonical source; не переводятся API/классы/поля/команды/пути/идентификаторы/код; смысл законов не меняется; без расходящейся английской копии. Governance и agent docs уже на русском; полная нормализация technical docs — follow-up.
- Changelog: `docs/changelog/NEXT_ARCHITECTURE_CHANGELOG.md` (User/Admin/Security/Infra&Releases/Externally-blocked/Not-yet-in-Production/Not-implemented; dry-run/mock не выдаются за operational).
- Strategy specs: safety invariant IMPLEMENTED+tested; workspace fork PARTIAL (`community.copy_strategy`); полная модель `strategy.spec.manage`/`sf_document_revisions` **NOT IMPLEMENTED** (крупный продуктовый модуль) → Phase 10 не закрывается полностью.
- Version: `VERSION.json` = `0.10.0-dev.1`; next dev suffix `0.10.0-dev.2`; `0.10.0-beta.1` **NOT READY** (incomplete requirement + external gates); env/channel/SemVer не смешаны; VERSION.json не менялся.
- Residuals (honest, non-CI): governance law `source_refs` + generated rendered files цитируют pre-move пути (provenance, regenerate); archive-internal historical cross-refs. Local gates: full regression 1148 passed / 31 skipped; compileall / node --check / static scan CSP/SECRETS/MARKDOWN / git diff --check PASS.
- CI/PR/merge/clean-checkout: [PR #17](https://github.com/OMNOM-111/NT-Analyzer/pull/17) merged; [Actions run 30834935279](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30834935279) SUCCESS (Static gates, Ubuntu, Windows PASS); implementation `d1087f59`; merge `753d2271`; task branch удалена локально и на origin. Clean-checkout из `origin/release/0.10.0-next-architecture` (без локальных stray): full regression 1148 passed / 31 skipped, compileall / node --check / static scan CSP+SECRETS+MARKDOWN / git diff --check — PASS. SKIPPED/EXTERNAL (не PASS): live-PostgreSQL suites, реальный Canary/Production deploy, blue-green switch, реальные Telegram/Connector/email provider, browser QA. **Phase 10B GIT CLOSEOUT COMPLETE; Phase 10 NOT fully closed.**

## Phase 11 evidence

Status: полное evidence — `docs/current/PHASE_11_FINAL_INTEGRATION_EVIDENCE.md`.
Ветка `phase/11-final-integration-corrections` от `release/0.10.0-next-architecture` (`e3d1d6bd`). `main`/Canary/Production/DNS/Cloudflare/secrets/сервер не затронуты; финальный PR в `main` не создаётся.

- Закрыты внутренние замечания аудита GPT-5.5 (`PASS WITH CONDITIONS`) плюс расширенный owner-запрос на полный функциональный/визуальный аудит приложения.
- **F1 IMPLEMENTED:** модуль ревизий спецификаций рабочих областей/стратегий — право `strategy.spec.manage`, миграция `0011_document_specifications.sql` (`sf_documents`+`sf_document_revisions`, RLS, GRANT для `stratforge_app`), `app/doc_specs.py`, API `/api/documents*`, UI-модуль, история версий + revert, запрет менять global governance/safety-limits из workspace/strategy; тесты `test_phase11_doc_specs.py`. Это снимает пункт «strategy-spec revision module NOT IMPLEMENTED» из Phase 10B.
- **F2–F6 DONE:** Account Security UI (привязка/unlink/step-up/last-method); Admin Panel — русификация + группировка, убраны placeholder-модули без backend, реальные workflow для документов; dirty-state — идемпотентный + детерминированный governance-рендер, dev runtime dirs в `.gitignore`; `source_refs` обновлены; per-env cookie/LS namespaces (guard `environment_explicit()`) + ADR-0008.
- **Browser-QA фиксы:** иконки DEV/CANARY/BETA (404 → 200, Aurora-brand route), CSP-ошибка `[::1]` убрана (header + 14 html), восстановлен переключатель «Перейти в старый интерфейс», локальный DEV = loopback owner.
- **F7 BLOCKED — EXTERNAL TEST DATABASE REQUIRED:** `deploy/testing/` (provision SQL, env example, runner Windows/Linux, backup/restore, README). Suite запускается при заданных `STRATFORGE_TEST_POSTGRES_*` DSN.
- Локальные гейты: full regression **1175 passed / 31 skipped**; compileall / node --check / static scan CSP+SECRETS+MARKDOWN / git diff --check — PASS. CI/PR/merge/clean-checkout записываются в Phase 11 closeout после CI PASS.

### Phase 11 closeout

- Implementation `198ba9dc`; [PR #18](https://github.com/OMNOM-111/NT-Analyzer/pull/18) merged; merge commit `8b6a2643`; task branch `phase/11-final-integration-corrections` удалена локально и на origin; integration совпадает с origin (`8b6a2643`).
- CI [Actions run 30857565524](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30857565524) SUCCESS (Static gates, Tests ubuntu-latest, Tests windows-latest — PASS).
- Clean-worktree verification (detach из origin, без stray): git status чист до и после; full regression 1175 passed / 31 skipped; compileall / node --check / static scan / git diff --check PASS.
- **Phase 11 IMPLEMENTATION CLOSED / GIT CLOSEOUT COMPLETE.** F1 (strategy-spec revision module) снял главный incomplete-пункт Phase 10B. Внешние гейты (PostgreSQL — BLOCKED, реальный Canary/Production/blue-green, реальные Telegram/Connector/email/market-data) остаются PENDING/BLOCKED. `main`/Canary/Production/DNS/Cloudflare/secrets не затронуты; финальный PR в `main` не создавался.

## Phase 11c — local Development canonical storage + AI service accounts

- **Каноническое локальное хранилище + настоящий owner-профиль.** Локальная Development-версия использует существующий канонический data root (`STRATFORGE_DEVELOPMENT_DATA_ROOT=<repo>/data`, как в supervised dev-профиле) и реального владельца. `account_auth.primary_owner()`/`primary_owner_id()` резолвят настоящего owner из локального стора, `server._local_owner_context` использует его вместо пустого synthetic `ws_local_owner`, а `_decorate_workspace_context` уважает `_owner_scope_id`. Проверено в браузере: имя владельца, роль, workspace `ws_owner_training_*`, 22 стратегии и NinjaTrader-Bridge снова отображаются.
- **Dev-only служебные аккаунты Claude/GPT.** `app/dev_service_accounts.py` + `POST /api/dev/service-login`: отдельные аккаунты с owner-правами к тому же workspace и данным (owner-роль в workspace владельца, `uses_owner_runtime`), но с отдельным `user_id` и отдельным audit (`data/audit/dev-service-accounts.jsonl`). Вход обходит Telegram только на localhost и невозможен в Canary/Production (`dev_service_accounts.available()`=is_development + loopback-guard). UI-переключатель (dev-only) в системном меню. Reserved id band внутри JS safe-integer range.
- Тесты: `tests/test_phase11c_dev_service_accounts.py` (9). Full regression **1184 passed / 31 skipped**; compileall / node --check / static scan / git diff --check PASS. `main`/Canary/Production не затронуты.

### Phase 11c closeout

- Implementation `3ded4518`; [PR #19](https://github.com/OMNOM-111/NT-Analyzer/pull/19) merged; merge commit `178493c0`; task branch `phase/11c-local-dev-owner-storage` удалена локально и на origin.
- CI [Actions run 30872561331](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30872561331) SUCCESS (Static gates, Tests ubuntu-latest, Tests windows-latest — PASS).
- Clean-worktree verification (detach из origin, clean env): git status чист до и после; full regression 1184 passed / 31 skipped; compileall / node --check / static scan / git diff --check PASS.
- **Phase 11c GIT CLOSEOUT COMPLETE.** `main`/Canary/Production/DNS/Cloudflare/secrets не затронуты.

## Phase 12 — 0.10.0-beta.1 live Canary + exact-artifact Production

- Current Production artifact: version `0.10.0-beta.1`, git `6b6dc4589407855526cf6cc345376d64cf95200e`, build `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`, manifest SHA256 `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`, archive SHA256 `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730`. One-step Production rollback target is `0.10.0-beta.1-795db0c1` / `D1CB6FF4…`.
- Current Canary artifact: git `de7acaedd9301b0b1f9a88ccf6f320316a68d881`, build `sf-0.10.0-beta.1-de7acaedd930-20260813T081638Z`, archive SHA256 `E26747873949633C9CC6A66CEECD400CC035DF0F1CD71A079FA45EDCC541D867`, manifest SHA256 `A2D17E51D4403C272A1F7A05DB1F2C346AE72B1459B7B8C9CC816836A29EF95F`. `/live` и `/ready` — `200`; isolated DB/queue/storage/cookie namespace unchanged. Telegram remains `EXTERNAL BLOCKED` (`disabled_pending_canary_bot_provisioning`).
- Production `https://app.stratforges.com`: same release directory `.../releases/0.10.0-beta.1-6b6dc458`. `/ready` 36ms. Browser: `[BETA]` `6b6dc45` + Sign in/Register; Telegram `login/start` 200 + waiting UI. Owner account not duplicated (5 users, 1 owner). Expand migrations 0005–0011 already applied. Live trading and real payments remain false.
- Host mechanism: Supervisor `canary-current`/`canary-previous` and Production `current`/`previous` symlink pairs. Current Canary=`de7acaed`, Canary previous=`6b6dc458`; current Production=`6b6dc458`, Production previous=`795db0c1`. Production links were not touched by the 2026-08-13 acceptance.
- **`/ready` hang root cause (reproduced on previous live Production `795db0c1`):** `connector_protocol.readiness_status()` held the Connector lock and called `storage_router.read_document("connectors")`, which deserialized the full JSON document (~19s). Promote used `curl --max-time 5` against `/api/health/ready`; the handler does not write headers until every probe finishes, so each poll received 0 bytes while the previous probe was still running and stacked more inflight `/ready` work on `BoundedThreadingHTTPServer`. `/api/health/live` already includes deployment identity and stays cheap.
- **Fix now live:** `DocumentRepository.ping()` does `SELECT 1` and never loads JSON; `/ready` runs control-plane probes concurrently with a 2s per-probe timeout, single-flight cache, and `probe_timeout` fail-closed. Environment Switcher defaults to `http://127.0.0.1:8765`, `https://canary.stratforges.com`, `https://app.stratforges.com`. Browser DEV→CANARY→PROD opened those origins in new tabs without copying cookies.
- Isolation: Production cannot CONNECT to Canary DB and vice versa; live ACL negatives were rechecked 2026-08-13. No orders were placed. Authenticated Canary/Production TopstepX chart smoke remains `EXTERNAL BLOCKED` for a fresh browser (real Telegram action required; no session fabricated). Local DEV owner session shows paper Topstep account read-only.
- Previous Production closeout: artifact commit `6b6dc458`; [PR #26](https://github.com/OMNOM-111/NT-Analyzer/pull/26) merged as `5b43569d`. Current hardening is tracked in PR #30 and has not been merged.

### `/ready` hang-fix — required new artifact

The hang-fix commit `6b6dc458` was built as a signed artifact, accepted on Canary (`/ready` 38ms, concurrent 8× 9ms, browser `[CANARY]` Sign in/Register, Telegram disabled PARTIAL), then the **same directory** was promoted to Production (`/ready` 36ms, promote ~27s, browser `[BETA]` Telegram waiting UI). Do not retag a later docs-only commit. Existing tag `stratforge-server-v0.10.0-beta.1` remains on `2f9409c4`.

### Rollback after expand-only schema 11

Traffic/code rollback target is `0.10.0-beta.1-795db0c1` (`D1CB6FF4…`). Schema 11 is expand-only: do not run destructive down-migrations. `0.9.0-dev.15-f05f287d` is **not** a compatible full rollback candidate (`database_migration_pending`). Restore evidence stays the existing PostgreSQL backup/restore contract in `docs/operations/PRODUCTION_STORAGE_RUNBOOK.md`.

### Owner acceptance REOPENED 2026-08-12 (infra `/ready` is not product acceptance)

Real owner/user check failed while the live artifact remained `2f9409c4` / `FB302F80…`:

1. **Local DEV did not open.** `start.ps1` / `backend_supervisor` refused to start because `VERSION.json` was stamped `channel=beta` / `status=pre_release` for the release cut. Runtime already forced `RELEASE_CHANNEL=dev`; the launchers did not. After reboot nothing listened on `8765`.
2. **Production showed the legacy promo/donation/«Смотреть бесплатно» gate.** Not a stale frontend: Production/Canary `ui.js` SHA matched the repo. Unauthenticated boot called `renderWelcomeAccess` before Sign in / Register.
3. **Telegram login returned 503 `storage_constraint`.** `/api/auth/providers` showed `@StratForgeAI_bot` available. `POST /api/auth/login/start` could not persist a challenge: the authoritative auth JSON document still had 5 users **without** `user_uuid` and **0** `auth_identities`, while `sf_users` / `sf_auth_identities` already had the SQL-backfilled UUIDs. `_migrate_doc` minted new UUIDs and collided on `(provider, provider_subject)`.
4. **Google** — implementation exists (`app/google_auth.py`, `/api/auth/google/login/start`); Production has no `NTA_GOOGLE_CLIENT_ID` / `SECRET` / redirect URI and no DPAPI store. Status: **EXTERNAL BLOCKED**. Do not fabricate a working provider.
5. **Email OTP** — challenge/verify exist, but `email_auth_status().available` is true only for Development test-auth; Production has no `NTA_EMAIL_AUTH_PROVIDER` and never sends mail. Status: **EXTERNAL BLOCKED**.

Code fix shipped as commit `795db0c1` and the signed artifact above: hydrate auth JSON from mirror UUIDs before persist/sync; Development launchers ignore VERSION.json channel; primary unauthenticated UI is Sign in / Register (Telegram / Google / email), with promo/donation optional.

Browser verification 2026-08-12 (hang-fix artifact `6b6dc458`): local DEV `[DEV]` `6b6dc45` `dirty=0` owner auto-auth; Canary `[CANARY]` Sign in/Register with Telegram disabled; Production `[BETA]` Sign in/Register + Telegram waiting UI. Environment Switcher from DEV opened Canary and Production in new tabs. Google/email remain EXTERNAL BLOCKED. Completing a Production owner session in a fresh browser still requires the owner Telegram tap (no session fabricated).

### Final acceptance hardening — Canary 2026-08-13

- Release Center is now a real owner-facing Canary workflow rather than a
  dry-run-only shell. Candidate `de7acaed` was built on the protected signer,
  verified, deployed and accepted through the UI. Production execution retains
  a separate process-level gate and was not enabled.
- Real Canary blue-green and rollback rehearsal PASS: all eight deploy stages
  passed; previous `6b6dc458` was restored and verified, then the same
  `de7acaed` artifact was re-promoted (`rollback_verified=true`,
  `re_promoted=true`, `online_safe=true`).
- Release build defect found and fixed: `git bundle create <file> <raw-sha>`
  produced an empty bundle. The executor now first verifies selected SHA equals
  current clean `HEAD`, then bundles symbolic `HEAD`; a regression test creates
  and validates a real non-empty bundle.
- DEV chart regression found and fixed without changing the accepted
  TopstepX/SignalR architecture: HTTP history/health refreshes could discard a
  fresh WebSocket marker state. Browser acceptance on the artifact commit ran
  `689 s` across two in-app clients and Chrome, MNQ/MES 5m, `32`
  observations, `0` grey/OFF/non-live states; raw quote, WS close, last bar and
  rendered label matched on stable frames.
- Safe Canary load: 10/50/100 clients, `0 failed`; 100-client p95 `/live`
  `1288.37 ms`, `/ready` `837.39 ms`, UI `1005.53 ms`.
- Final automated closeout: targeted market-data/chart + governance/docs +
  release/rollback `259 passed`; full pytest `1302 passed, 31 skipped, 0
  failed`; repository harness `13/13` suites PASS. Static scan, context
  validation, compileall/py_compile, 32 JavaScript syntax checks, four deploy
  script syntax checks and diff check PASS. The 31 skips are only the explicit
  live-PostgreSQL suites requiring `STRATFORGE_TEST_POSTGRES_*`.
- Canonical evidence:
  [../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md](../changelog/2026-08-13-final-acceptance-canary-0.10.0-beta.1.md).
- Status: **CANARY CORE PASS WITH EXTERNAL BLOCKERS**. Canary Telegram and
  authenticated server-side chart smoke remain explicitly blocked by real
  external authentication. Production remains unchanged pending a separate
  owner answer.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-13T08:31:00Z | GPT-5.5 через Codex по запросу owner | Recorded final acceptance hardening, real Release Center Canary lifecycle and rollback rehearsal; Production unchanged.
2026-08-12T23:50:00Z | Grok 4.6 через Cursor по запросу owner | Record PR #26 MERGED to main (5b43569d) and annotated tag stratforge-server-v0.10.0-beta.1-6b6dc458 on the live hang-fix artifact.
2026-08-12T23:40:00Z | Grok 4.6 через Cursor по запросу owner | Record live 6b6dc458 hang-fix artifact: Canary then exact-artifact Production, /ready 36ms, Environment Switcher DEV→CANARY→PROD.
2026-08-12T23:45:00Z | Grok 4.6 через Cursor по запросу owner | Record /ready hang root cause (Connector JSON load ~19s + overlapping curl --max-time 5) and the bounded ping/timeout/single-flight/promote-/live fix that requires a new signed artifact.
2026-08-12T22:30:00Z | Grok 4.6 через Cursor по запросу owner | Record live 795db0c1 artifact after auth/DEV fix: Canary+Production Sign in/Register, Telegram login/start 200, local DEV restored.
2026-08-12T22:15:00Z | Grok 4.6 через Cursor по запросу owner | Reopen 0.10.0-beta.1: record real DEV/auth acceptance failures and the code fix that must ship as a new artifact.
2026-08-12T21:30:00Z | GPT-5.5 через Codex по запросу owner | Record factual 0.10.0-beta.1 Canary PASS and exact-artifact Production promotion results.
2026-08-11T09:15:42Z | GPT-5.5 через Codex по запросу owner | Removed the visible technical amendment preamble during final Development documentation closeout; historical evidence remains in Git history.
-->
