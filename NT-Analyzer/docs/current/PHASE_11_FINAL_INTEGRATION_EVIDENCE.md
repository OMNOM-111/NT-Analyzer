# Phase 11 — финальная интеграционная доводка (evidence)

Ветка: `phase/11-final-integration-corrections` от `release/0.10.0-next-architecture`
(tip `e3d1d6bd`). Не затронуты `main`, Canary, Production, DNS, Cloudflare,
реальные secrets и сервер. Финальный PR в `main` не создаётся.

Фаза закрывает внутренние замечания независимого аудита GPT-5.5 коммита
`e3d1d6bd` (verdict `PASS WITH CONDITIONS` для локального кода, `FAIL` для
готовности к реальному Canary) и расширенный owner-запрос на полный
функциональный и визуальный аудит приложения.

## Замечания аудита (findings)

- **F1 — модуль ревизий спецификаций рабочих областей/стратегий.** Право
  `strategy.spec.manage` (`app/permissions.py`); миграция
  `0011_document_specifications.sql` (`sf_documents` + `sf_document_revisions`,
  RLS `sf_scope_global()`/`sf_scope_workspace()`, FK на `sf_users(user_uuid)`,
  GRANT для `stratforge_app`); модуль `app/doc_specs.py` (scopes
  global/governance/workspace/strategy/changelog; жизненный цикл
  draft→review→approved→published→superseded; supersede + revert; шифрованный
  dev-store / `storage_router` в Production); API `/api/documents*`
  (`app/server.py`); клиенты `api.js`; UI-модуль «Документы рабочих областей» +
  просмотр/редактирование глобальных governance-документов; запрет менять
  global governance/safety-limits из workspace/strategy scope; тесты
  `tests/test_phase11_doc_specs.py` (12). Global governance неизменяем из
  workspace/strategy (проверено).
- **F2 — Account Security UI.** `renderSecurityInto` (`ui.js`): список
  Telegram/Google/email identities, привязка e-mail (`/api/auth/email/link/*`) и
  Google (`/api/auth/google/start`), unlink, понятный запрет удаления последнего
  способа входа (`last_login_method`), устройства pending/trusted/revoked,
  русские сообщения. Кнопки привязки показываются только для providers с реальным
  backend-flow (Telegram привязывается через бота — показана честная подсказка,
  без ложной кнопки). Проверено в браузере как owner.
- **F3 — Admin Panel.** Убраны placeholder-модули без backend (`workspaces`,
  `security`); удалён generic-shell «в своей плановой фазе»; реализованы реальные
  workflow «Глобальные документы» (governance) и «Документы рабочих областей»
  (doc_specs). Разделы русифицированы и сгруппированы (см. ниже).
- **F4 — dirty-state после тестов.** `.gitignore` (dev runtime dirs);
  `governance.py` — идемпотентный `_write_if_changed` + детерминированная дата
  рендера (`_governance_updated_at()` вместо wall-clock `_project_local_date`),
  так что повторный рендер/перезапуск не грязнит clean checkout; test SQLite
  через `NT_ANALYZER_SQLITE_PATH`.
- **F5 — governance `source_refs`.** Обновлены под новые пути после переноса
  документации (`governance.py` + `data/governance/laws.json`).
- **F6 — cookie/local-storage namespaces.** Раздельные имена для
  DEV/CANARY/PRODUCTION, но только при явно выбранном окружении
  (`environment_explicit()`); неявное/локальное окружение сохраняет канонический
  `sf_session` и пустой namespace — иначе неявный default в PRODUCTION ломал
  loopback-тесты. ADR `docs/adr/0008-…`; тесты
  `tests/test_phase11_env_isolation.py`.
- **F7 — изолированная PostgreSQL-приёмка.** `deploy/testing/` (README,
  `provision-test-postgres.sql`, `postgres-acceptance.env.example`, runner для
  Windows/Linux, backup/restore). Тестовой БД в этом окружении нет →
  **BLOCKED — EXTERNAL TEST DATABASE REQUIRED**; suite (`test_stage8_postgresql`,
  `test_production_storage`, `test_production_workers`) запускается при заданных
  DSN.

## Browser-QA (owner расширил scope; ограничение AGENTS.md на браузер снято)

Локальная Development-версия запущена (`app.server 8765`, loopback owner через
`NTA_TEST_BYPASS_AUTH=1`). Проверка реальными кликами/загрузками/консолью.

Исправленные фактические дефекты приложения:

- **Значки DEV/CANARY/BETA как «битые изображения» (404).** `/ui/brand/*`
  раньше резолвился в legacy `app/static/brand/` (там только mark/icon/logo), а
  `stratforge-{dev,canary,beta}.png` лежат только в `app/static/aurora/brand/`.
  Исправление: `/ui`-handler отдаёт `/brand/*` из Aurora-дерева. Все иконки → 200;
  файлы git-tracked и попадают в release build. DEV-метка оранжевая.
- **CSP-ошибка в консоли на каждой странице** (`http://[::1]:*` — невалидный
  источник). Удалена из `STATIC_CSP` и из `<meta>`-CSP всех 14 `aurora/*.html`.
- **Admin Panel на английском.** Русифицированы названия модулей и capabilities,
  добавлена логическая группировка (Доступ и пользователи / Операции / Релизы и
  окружения / Документы / Владелец); «Панель администратора».
- **Пропавшая кнопка «Перейти в старый интерфейс».** Восстановлена в
  системном меню; обратный переход (`legacy_switch.js` «✦ Новый интерфейс») уже
  есть; legacy UI отдаётся на `/ui/legacy/` (200).
- **Локальный DEV = гость.** `backend_supervisor` dev-профиль теперь включает
  loopback-owner (`NTA_TEST_BYPASS_AUTH=1`; guard loopback-only, Production
  отвергает bypass в `assert_startup_safe`).
- **GRANT для `stratforge_app`** отсутствовал в миграции `0011` (сломал бы
  Production-PG path) — добавлен.

Все owner-страницы (Обзор, Бэктест, Торговля, Рабочий стол, Финансы, Стратегии,
AI Lab, AI Agents, Новости, Сообщество, TopStep, Документы) грузятся без ошибок
консоли и без 4xx/5xx. `desktop.html` не достигает `networkidle` из-за realtime
polling (не дефект); `504` на bars-эндпоинте — нет подключённого источника данных
(ожидаемо в dev, не выдаётся за рабочее).

Роль-based доступ (developer с ограниченными правами / обычный пользователь /
personal NinjaTrader / общий owner-training NinjaTrader): loopback-owner bypass
намеренно перекрывает persona-сессию, поэтому переключение ролей прямо в браузере
недоступно; корректность прав по ролям подтверждена автоматическими тестами
(`test_cabinet` capability-gate, `test_phase7_dev_preview`, `test_permissions`).

## Тесты и гейты (локально, Windows, Python 3.12)

- Полная регрессия: **1175 passed, 31 skipped**.
- Новое: `tests/test_phase11_ui_wiring.py` (10) — иконки отдаются по HTTP, CSP без
  `[::1]`, legacy-switch в обе стороны, Admin Panel русский/сгруппированный/без
  fake-placeholder. `tests/test_phase11_doc_specs.py` (12),
  `tests/test_phase11_env_isolation.py` (5).
- `compileall app tools tests` OK; `node --check` для `ui.js`/`api.js` OK;
  `tools/release_static_scan.py` — CSP/SECRETS/MARKDOWN OK; `git diff --check`
  чисто (только CRLF-warnings нормализуются `.gitattributes`).

## Внешние acceptance-гейты (по-прежнему PENDING/BLOCKED, не PASS)

- Изолированная PostgreSQL-приёмка — **BLOCKED — EXTERNAL TEST DATABASE REQUIRED**.
- Реальный Canary/Production deploy, blue-green switch, реальные
  Telegram/Connector/email/данные рынка — вне локального scope.

Готовность: локальный код и UI приведены к рабочему состоянию для ручной проверки
owner; повторный аудит может выполняться с этой ветки.

## Git closeout

- Implementation commit `198ba9dc` на `phase/11-final-integration-corrections`.
- [PR #18](https://github.com/OMNOM-111/NT-Analyzer/pull/18) →
  `release/0.10.0-next-architecture`; merge commit `8b6a2643`; task branch
  удалена локально и на origin.
- CI [Actions run 30857565524](https://github.com/OMNOM-111/NT-Analyzer/actions/runs/30857565524)
  SUCCESS: Static gates, Tests (ubuntu-latest), Tests (windows-latest) — все PASS.
- Clean-worktree verification из `origin/phase/11-final-integration-corrections`
  (детач, без локальных stray-файлов): git status чист до и после; full regression
  **1175 passed / 31 skipped**; `compileall` / `node --check` (ui.js, api.js) /
  `release_static_scan` (CSP+SECRETS+MARKDOWN) / `git diff --check` — PASS.
- `main`, Canary, Production, DNS, Cloudflare, реальные secrets и сервер не
  затронуты. Финальный PR в `main` не создавался.

**Phase 11 IMPLEMENTATION CLOSED / GIT CLOSEOUT COMPLETE.** Внешние acceptance-гейты
(изолированная PostgreSQL-приёмка — BLOCKED, реальный Canary/Production deploy,
blue-green switch, реальные Telegram/Connector/email/данные рынка) остаются
PENDING/BLOCKED и не выдаются за PASS.
