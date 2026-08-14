# Next Architecture Program — Changelog (0.10.0 line)

История поправки: 2026-08-14T17:12:00Z; внёс `Grok 4.6 через Cursor по запросу owner`; scope: live LOCAL/CANARY/PRODUCTION `77e8645f`; Documents/Release Center 200; TopstepX LIVE.
История поправки: 2026-08-14T06:20:00Z; внёс `Grok 4.6 через Cursor по запросу owner`; scope: live HTTP identity `1fae1f39` on Canary+Production; repository Documents/Charts fix not yet that artifact.
История поправки: 2026-08-12T23:50:00Z; внёс `Grok 4.6 через Cursor по запросу owner`; scope: PR #26 merged to main; hang-fix tag on `6b6dc458`.
История поправки: 2026-08-03T16:53:14Z; внёс `GitHub Copilot`; scope: Phase 10B — создать честный changelog новой архитектурной программы с разделением по аудитории и по фактическому статусу развёртывания.

Программа: переход от одновладельческого контура к многопользовательской
архитектуре StratForge (`0.10.0-dev` line, integration branch
`release/0.10.0-next-architecture`). Ниже — фактические изменения по категориям.
Dry-run, mock, тестовый backend и неподключённые внешние провайдеры **не**
выдаются за рабочие функции; такие пункты вынесены в разделы «Внешне
заблокировано» и «Развёрнуто 2026-08-12».

## Пользовательские изменения (User)

- Единая идентичность аккаунта на UUID с поддержкой провайдеров Telegram, Google
  и verified email; e-mail сам по себе не объединяет аккаунты, нельзя удалить
  последний способ входа (Phase 3).
- Управление доверенными устройствами: подтверждение/отзыв устройства,
  немедленное завершение сессий отозванного устройства (Phase 4).
- Онбординг и step-up для личного NinjaTrader (Telegram + verified email,
  подтверждение критических действий) (Phase 5).
- Обезличенная очередь общего NinjaTrader: обычный пользователь видит только
  свободен/выполняется/в очереди и свою позицию, без чужих данных (Phase 6).
- Fork/копирование опубликованной стратегии в свой workspace как `pending_import`
  (`community.copy_strategy`) — **ограниченная** возможность (см. «Не реализовано»).

## Административные изменения (Admin)

- Capability-gated Admin Panel: административные права отделены от тарифов;
  owner получает полный набор, делегированному администратору выдаются только
  явные истекающие grants (Phase 2).
- Изолированный Environment Switcher (Development/Canary/Production) без передачи
  cookies/CSRF/токенов между origin (Phase 2). Если `STRATFORGE_*_ORIGIN` не
  заданы, API подставляет `http://127.0.0.1:8765`,
  `https://canary.stratforges.com`, `https://app.stratforges.com`. Local DEV
  открывается только после credential-free probe. Обычным пользователям
  переключатель не показывается.
- Developer Preview / View-As: owner может просматривать приложение глазами роли
  через реальные серверные права, только в Development (Phase 7).
- Центр релизов в Admin Panel: создание release candidate, сборка immutable
  artifact, Canary-проверки, owner approval, продвижение того же artifact,
  расписание, rollback-записи, репетиция blue-green (Phase 8–9). Real Canary
  deploy/rollback now exists; Production promotion stays a separate owner gate.
- Governance amendment workflow ужесточён: запись глобального governance доступна
  только owner или администратору с `docs.manage_global` (Phase 10A).

## Безопасность (Security)

- Fail-closed изоляция окружений: отдельные cookie/CSRF/local-storage/DB/queue/
  storage/bot identity; пересечение Canary↔Production reference-идентификаторов
  отклоняется на старте и в preflight (Phase 1, 7).
- Per-action step-up grants (single-use, привязка к user/action/environment,
  TTL) для критических действий (Phase 5, 8).
- Строгий exact-artifact контроль продвижения релиза: dirty checkout, изменение
  manifest/подписи после подписи, несовпадение artifact/manifest/commit/build,
  approval без step-up — отклоняются (Phase 8).
- Глобальный governance нельзя изменить workspace/strategy override: disjoint
  stores + строгий allowlist `update_strategy_profile` + owner/`docs.manage_global`
  gate на запись governance (Phase 10A).
- Markdown link audit включён в статические ворота релиза (Phase 10).

## Инфраструктура и релизы (Infrastructure & Releases)

- Environment metadata + build identity + signed server release
  manifest/verifier; визуальная маркировка DEV/CANARY/BETA (Phase 1).
- Additive expand-only миграции `0005`–`0011` (RLS, Release Center, documents) —
  определены, покрыты тестами и **применены** к live Canary и Production
  PostgreSQL 2026-08-12.
- Durable NinjaTrader resource lease/queue; agent allocation policy (Phase 6).
- Секрет-free deploy templates: `deploy/canary/*`, `deploy/production/*`,
  `deploy/production/blue-green/*`; runbooks в `docs/operations/`.
- Каноническое дерево документации `docs/{current,architecture,operations,
  security,product,agents,strategies,governance,changelog,adr,archive}` +
  migration map `docs/DOCS_STRUCTURE.md` (Phase 10A/10B).

## Внешне заблокировано (External acceptance gates — не «готово»)

- Отдельный Canary Telegram bot (BotFather) remains unused: Canary reuses the
  existing bot via shared-webhook forwarding. Public HTTPS forward can still
  hit Cloudflare 1010; optional loopback origin is not a live host env yet.
- Реальный Production transactional email provider для email OTP / magic link.
- Google OAuth client (`NTA_GOOGLE_CLIENT_ID` / `SECRET` + redirect
  `https://app.stratforges.com/api/auth/google/callback`) — реализация есть,
  Production secrets отсутствуют.
- Утверждённый market-calendar provider для расписания «после закрытия рынка».

## Развёрнуто 2026-08-14 (live identity `77e8645f` — Documents/Charts STAGE CLOSED)

- Public `/api/runtime/env` on Canary and Production plus local DEV report git
  `77e8645f1725d20545992efdeabafdf2f3d0e684`, build
  `sf-0.10.0-beta.1-77e8645f1725-20260814T164341Z`, public artifact SHA256
  `1F0C95E48447632CB97EF88A85E38354D6A71AC32C41285600DACA182A8748C6`.
- Host `/proc` cwd for all eight app processes matches
  `.../0.10.0-beta.1-77e8645f1725`. Previous slot is `1fae1f39`.
- Owner Documents/Release Center HTTP 200. TopstepX MNQ history + realtime LIVE
  with NinjaTrader unavailable.
- Evidence: `docs/changelog/2026-08-14-live-release-77e8645f-documents-charts.md`.

## Развёрнуто 2026-08-14 (live HTTP identity `1fae1f39` — historical)

- Public `/live` `/ready` `/runtime/env` on Canary and Production both report
  git `1fae1f3966dc53294b73772be47992d844575115`, build
  `sf-0.10.0-beta.1-1fae1f3966dc-20260814T052203Z`, artifact SHA256
  `08265412DECF4D04962A14A0D17208BB7E67031F09AF62FB525634749B6B449B`.
- That artifact 500'd Documents/Release Center and stubbed server charts.
  Superseded by `77e8645f`.
- Evidence: `docs/changelog/2026-08-14-live-identity-1fae1f39-and-server-chart-fix.md`.

## Развёрнуто 2026-08-12 (0.10.0-beta.1 `/ready` hang-fix — historical)

- Signed artifact git `6b6dc4589407855526cf6cc345376d64cf95200e`, manifest SHA256
  `272045DB15D98C8505D770BAC9389215FD90E9C70F0BB14C19CEABABD31BD9F3`, archive
  SHA256 `3EF790F05A24BC4EB7A9DFAD343F7284E0A61F832A1A3B8392C815E7C59E6730`,
  build `sf-0.10.0-beta.1-6b6dc4589407-20260812T232811Z`. Canary first, then
  the same directory promoted to Production (`previous` = `795db0c1`).
- `/ready` Production 36ms / Canary 38ms; concurrent 8× does not stall the
  threaded API. Promote `/live` then `/ready` finished in ~27s.
- Environment Switcher: DEV current; CANARY/PROD open
  `https://canary.stratforges.com` / `https://app.stratforges.com` in new tabs.
- Telegram: Production available `@StratForgeAI_bot`; Canary PARTIAL
  `disabled_pending_canary_bot_provisioning`. Google/email remain EXTERNAL
  BLOCKED.
- Git: [PR #26](https://github.com/OMNOM-111/NT-Analyzer/pull/26) MERGED;
  merge `5b43569d` on `main`; tag `stratforge-server-v0.10.0-beta.1-6b6dc458`
  on `6b6dc458` only. Existing `stratforge-server-v0.10.0-beta.1` stays on
  `2f9409c4`.

## Развёрнуто 2026-08-12 (0.10.0-beta.1 auth/DEV fix)

- New signed artifact after owner acceptance failed on `2f9409c4`: git
  `795db0c110712814bda751b4c74457dece476822`, manifest SHA256
  `D1CB6FF4A8BD5DAB0525BA8EFCD2F6DB29DC6C327534AB85AE1C8C6A76AA4E2E`,
  build `sf-0.10.0-beta.1-795db0c11071-20260812T221054Z`. Canary first, then
  the same directory promoted to Production (`previous` = `2f9409c4`).
- Local DEV: `start.ps1` starts with `VERSION.json` channel=beta; `[DEV]`,
  `795db0c`, `dirty=0`, `deployment_environment=development`.
- Production browser: Sign in/Register (Telegram/Google/email); promo/donation
  optional. Telegram `login/start` 200 + waiting UI. Google/email remain
  EXTERNAL BLOCKED. Owner Telegram tap still required to finish a Production
  session. PR #26 later MERGED after the hang-fix artifact.

## Развёрнуто 2026-08-12 (0.10.0-beta.1) — infra PASS, owner auth FAIL

- Previous live artifact (now Production rollback target): git
  `2f9409c48a6c1480617749462323562ade3eb6fe`, manifest SHA256
  `FB302F809F7FD38A7BDB6CCFC0ADD1A1D01DA43B4C947EB0C9726F5FBB42C870`,
  build `sf-0.10.0-beta.1-2f9409c48a6c-20260812T054311Z`.
- Owner acceptance 2026-08-12: local DEV launcher blocked by `VERSION.json`
  channel=beta; Production primary gate was promo/donation; Telegram
  `POST /api/auth/login/start` returned `storage_constraint` because the auth
  JSON document lacked the SQL-backfilled UUIDs. Infra `/ready` remained green.

## Не реализовано (Not implemented)

- Полная модель workspace/strategy specification revision закрыта в Phase 11
  (`strategy.spec.manage`, migration `0011`, `app/doc_specs.py`). Остаётся
  owner design/UI acceptance. Canary Telegram uses shared-webhook forwarding;
  public Cloudflare 1010 and `/proc` identity proof remain open.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-14T17:12:00Z | Grok 4.6 через Cursor по запросу owner | Live 77e8645f LOCAL/CANARY/PRODUCTION; Documents/Charts STAGE CLOSED.
2026-08-14T06:20:00Z | Grok 4.6 через Cursor по запросу owner | Recorded live HTTP identity 1fae1f39; hang-fix 6b6dc458 is historical; Documents/Charts follow-up not STAGE CLOSED.
2026-08-12T22:30:00Z | Grok 4.6 через Cursor по запросу owner | Record live 795db0c1 auth/DEV fix artifact on Canary and Production.
2026-08-12T22:15:00Z | Grok 4.6 через Cursor по запросу owner | Reopen: owner auth/DEV acceptance failed on live 2f9409c4; record UUID hydrate + launcher + primary Sign in/Register fix requiring a new artifact.
2026-08-12T21:30:00Z | GPT-5.5 через Codex по запросу owner | Record factual 0.10.0-beta.1 Canary/Production deployment; remove stale "not deployed" claims.
-->
