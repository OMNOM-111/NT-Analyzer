# Next Architecture Program Status

История поправки: 2026-08-03T06:58:46Z; внёс `GitHub Copilot`; scope: Phase 8 — зафиксировать реализацию Release Center (immutable-artifact promotion state machine, migration 0009, API, UI, dry-run adapter; external Canary/Production acceptance pending owner approval).

История поправки: 2026-08-03T03:55:03Z; внёс `GitHub Copilot`; scope: Phase 7 closeout — записать PR #13, cross-platform CI run 30782625524, merge commit 5955f2e5 и удаление task branch (external Canary acceptance остаётся owner gate).

История поправки: 2026-08-03T03:42:05Z; внёс `GitHub Copilot`; scope: Phase 7 — зафиксировать реализацию изолированного Canary-контура и Developer Preview / View-As (implementation complete, external Canary acceptance pending owner approval).

История поправки: 2026-08-03T02:26:18Z; внёс `GitHub Copilot`; scope: Phase 6 closeout — записать PR #12, cross-platform CI run 30779156395, merge commit 93b1fced и удаление task branch.

История поправки: 2026-08-03T02:19:36Z; внёс `GitHub Copilot`; scope: Phase 6 — зафиксировать agent allocation и durable shared-NinjaTrader resource lease/queue, migration 0008 и локальный verification evidence.

История поправки: 2026-08-02T23:06:34Z; внёс `GitHub Copilot`; scope: Phase 5 closeout — записать PR #11, cross-platform CI run 30771449462, merge commit 1b4249cc и удаление task branch.

История поправки: 2026-08-02T23:01:01Z; внёс `GitHub Copilot`; scope: Phase 5 — зафиксировать personal NinjaTrader security (Telegram + verified email factors, per-action step-up), migration 0007 и локальный verification evidence.

История поправки: 2026-08-02T22:01:10Z; внёс `GitHub Copilot`; scope: Phase 4 closeout — записать PR #10, cross-platform CI run 30769037213, merge commit 4c60df6c и удаление task branch.

История поправки: 2026-08-02T21:54:12Z; внёс `GitHub Copilot`; scope: Phase 4 — зафиксировать trusted-device registry, step-up challenges, migration 0006 и локальный verification evidence.

История поправки: 2026-08-02T20:27:30Z; внёс `GitHub Copilot`; scope: Phase 3 closeout — записать PR #9, cross-platform CI, merge commit и удаление task branch.

История поправки: 2026-08-02T20:22:26Z; внёс `GitHub Copilot`; scope: Phase 3 — закрыть UUID session/Mini App merge gap и обновить final validation evidence.

История поправки: 2026-08-02T20:10:39Z; внёс `GitHub Copilot`; scope: Phase 3 — зафиксировать UUID identity implementation, local validation evidence и границу PostgreSQL acceptance.

История поправки: 2026-08-02T03:17:45Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 2 closeout — записать PR, cross-platform CI, merge commit и удаление task branch.

История поправки: 2026-08-02T03:06:47Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 2 — зафиксировать capability-gated Admin Panel, изолированный Environment Switcher и локальный verification evidence.

История поправки: 2026-08-02T02:17:26Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 1 closeout — зафиксировать PR, CI, merge commit, artifact evidence и удаление task branch.

История поправки: 2026-08-02T01:55:27Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 1 — зафиксировать реализацию environment metadata, build identity, visual marking и evidence.

История поправки: 2026-08-02T00:53:55Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 0 — создать единый журнал выполнения Phase 0–10.

Обновлено: 2026-08-03T06:58:46Z

## Baseline

- Repository: `OMNOM-111/NT-Analyzer`
- Baseline: `72f46a1a3a1d32051a00d087808755676ec4d992`
- Baseline branch: `main`; при старте `HEAD == origin/main`, working tree clean
- Version at baseline: `0.9.0-dev.10`
- Release history: Git tags on non-baseline history reach `stratforge-server-v0.9.0-dev.15`; the next minor line avoids reusing any `0.9.0-dev.N` identifier
- Next version: `0.10.0-dev.1`
- Integration branch: `release/0.10.0-next-architecture`
- Production/Canary boundary: deployment, Production DB/secrets, DNS/Cloudflare и реальные bot/email credentials вне scope

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
| 8 | IMPLEMENTATION COMPLETE (external Canary/Production acceptance pending) | `phase/8-release-center` | pending | Release Center: immutable-artifact promotion state machine + migration 0009 |
| 9 | PENDING | `phase/9-blue-green` | pending | Blue-green tooling без deployment |
| 10 | PENDING | `phase/10-documentation` | pending | Canonical docs и amendment workflow |

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
- CI/PR/Git closeout: записывается при closeout (base `release/0.10.0-next-architecture`).
