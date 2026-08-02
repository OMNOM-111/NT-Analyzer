# Next Architecture Program Status

История поправки: 2026-08-02T20:27:30Z; внёс `GitHub Copilot`; scope: Phase 3 closeout — записать PR #9, cross-platform CI, merge commit и удаление task branch.

История поправки: 2026-08-02T20:22:26Z; внёс `GitHub Copilot`; scope: Phase 3 — закрыть UUID session/Mini App merge gap и обновить final validation evidence.

История поправки: 2026-08-02T20:10:39Z; внёс `GitHub Copilot`; scope: Phase 3 — зафиксировать UUID identity implementation, local validation evidence и границу PostgreSQL acceptance.

История поправки: 2026-08-02T03:17:45Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 2 closeout — записать PR, cross-platform CI, merge commit и удаление task branch.

История поправки: 2026-08-02T03:06:47Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 2 — зафиксировать capability-gated Admin Panel, изолированный Environment Switcher и локальный verification evidence.

История поправки: 2026-08-02T02:17:26Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 1 closeout — зафиксировать PR, CI, merge commit, artifact evidence и удаление task branch.

История поправки: 2026-08-02T01:55:27Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 1 — зафиксировать реализацию environment metadata, build identity, visual marking и evidence.

История поправки: 2026-08-02T00:53:55Z; внёс `GPT-5.5 через Codex по запросу owner`; scope: Phase 0 — создать единый журнал выполнения Phase 0–10.

Обновлено: 2026-08-02T20:27:30Z

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
| 4 | PENDING | `phase/4-trusted-devices` | pending | Devices и step-up |
| 5 | PENDING | `phase/5-personal-nt-security` | pending | Personal NT security |
| 6 | PENDING | `phase/6-agent-resource-queue` | pending | Agent allocation и NT lease |
| 7 | PENDING | `phase/7-canary-environment` | pending | Canary config без deployment |
| 8 | PENDING | `phase/8-release-center` | pending | Release Center |
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
