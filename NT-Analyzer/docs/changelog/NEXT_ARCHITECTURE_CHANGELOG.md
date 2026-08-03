# Next Architecture Program — Changelog (0.10.0 line)

История поправки: 2026-08-03T16:53:14Z; внёс `GitHub Copilot`; scope: Phase 10B — создать честный changelog новой архитектурной программы с разделением по аудитории и по фактическому статусу развёртывания.

Программа: переход от одновладельческого контура к многопользовательской
архитектуре StratForge (`0.10.0-dev` line, integration branch
`release/0.10.0-next-architecture`). Ниже — фактические изменения по категориям.
Dry-run, mock, тестовый backend и неподключённые внешние провайдеры **не**
выдаются за рабочие функции; такие пункты вынесены в разделы «Внешне
заблокировано» и «Ещё не в Production».

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
  cookies/CSRF/токенов между origin (Phase 2).
- Developer Preview / View-As: owner может просматривать приложение глазами роли
  через реальные серверные права, только в Development (Phase 7).
- Центр релизов в Admin Panel: создание release candidate, сборка immutable
  artifact, Canary-проверки, owner approval, продвижение того же artifact,
  расписание, rollback-записи, репетиция blue-green (Phase 8–9). **Все внешние
  развёртывания — dry-run** (см. ниже).
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
- Additive expand-only миграции `0005`–`0010` (RLS, global-scope для Release
  Center) — определены и покрыты статическими контрактными тестами.
- Durable NinjaTrader resource lease/queue; agent allocation policy (Phase 6).
- Секрет-free deploy templates: `deploy/canary/*`, `deploy/production/*`,
  `deploy/production/blue-green/*`; runbooks в `docs/operations/`.
- Каноническое дерево документации `docs/{current,architecture,operations,
  security,product,agents,strategies,governance,changelog,adr,archive}` +
  migration map `docs/DOCS_STRUCTURE.md` (Phase 10A/10B).

## Внешне заблокировано (External acceptance gates — не «готово»)

- Реальный Canary: изолированная PostgreSQL DB/DSN, Cloudflare tunnel и
  `canary.stratforges.com` DNS, отдельный Telegram bot token/webhook, Canary
  Connector — требуют owner-инфраструктуры.
- Реальный Production transactional email provider для email OTP / magic link.
- Live PostgreSQL применение миграций `0005`–`0010` к реальной БД (RLS/restore).
- Утверждённый market-calendar provider для расписания «после закрытия рынка».

## Ещё не развёрнуто в Production (Not yet in Production)

- Реального развёртывания Canary или Production **не выполнялось**. Центр релизов
  и blue-green работают в режиме fail-closed dry-run: внешний результат всегда
  `pending`; `production_live` достигается только отдельным owner-подтверждением.
- `release/0.10.0-next-architecture` **не** слит в `main`; версия остаётся
  `0.10.0-dev.1`; `0.10.0-beta.1` не подготовлена.

## Не реализовано (Not implemented)

- Полная модель workspace/strategy specification revision (`strategy.spec.manage`
  capability, `sf_document_revisions` со `scope_type`,
  `document_revisions/approvals/publications`) — отдельный крупный продуктовый
  модуль (см. `docs/current/NEXT_ARCHITECTURE_FINAL_REQUIREMENTS_MATRIX.md` §C).
  Поэтому Phase 10 **не** объявляется полностью закрытой.
