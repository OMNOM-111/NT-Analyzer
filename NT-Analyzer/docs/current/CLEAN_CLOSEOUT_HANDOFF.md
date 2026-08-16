# Clean closeout — executable handoff

Дата: `2026-08-16` UTC. Продолжать **с первого невыполненного пункта**,
повторный аудит не нужен.

## LIVE состояние (проверено прямым чтением)

| | |
| --- | --- |
| Canary | `0.10.0-beta.11`, commit `0cd4bde7`, artifact `62CAC04AE8351F8B…` |
| Production | `0.10.0-beta.11`, commit `0cd4bde7`, artifact `62CAC04AE8351F8B…` |
| Release state | исправлено (PR #79): verified deploy → `production_live`; ошибочная попытка остаётся retryable |
| Parity | **EXACT MATCH**, acceptance PASS на обоих |
| migration 0012 | применена на Canary **и** Production, FK-семантика проверена |
| repo HEAD | `baeddbe5` |

### База очищена — на обоих окружениях ровно один human user

```
production: users=1 identities=3 sessions=6 devices=1 workspaces=2
canary:     users=1 identities=3 sessions=7 devices=1 workspaces=1

eb9d8e32-8db0-d590-9b35-ef1bd07ec61f  dimon_check  DMYTRO CHEREVKO  is_owner=True
  identities = telegram + google + email     devices = 1
```

Удалены: `stage9_canary_operator`, `123456`, `505`, `ARTUR_CA`.
Orphan integrity PASS: во всех RESTRICT-таблицах `held_by_doomed={}`.
Backup перед операцией: `pre-identity-cleanup-20260815T223000Z`.

## Что было починено, чтобы это стало возможно

Удаление аккаунта не работало вообще — четыре независимых дефекта, каждый
маскировал следующий:

1. **PR #60** — операционные строки (`sf_commands`, `sf_jobs`, `sf_artifacts`,
   `sf_ai_*`, `sf_market_data_subscriptions`) держали `sf_users` через
   `RESTRICT` и не освобождались.
2. **PR #62 / migration 0012** — все `sf_identity_*_user_uuid_fk` были созданы
   без `ON DELETE` (т.е. `NO ACTION`) и блокировали удаление на каждой таблице
   с `user_uuid`. Теперь: CASCADE для owned-строк, **SET NULL** для
   `sf_audit_events` / `sf_operational_events` / `sf_migration_runs`
   (история сохраняется), RESTRICT для `sf_workspaces`.
3. **PR #71** — audit удаления ссылался на только что удалённый аккаунт.
   `append_audit` берёт scope из `values["user_id"]`, а это FK на `sf_users`;
   INSERT падал. `ON DELETE SET NULL` тут не помогает — он про удаление
   родителя, а не про вставку ссылки на уже удалённого.
4. **PR #73** — workspaces чистились **после** записи account-документа, а
   `sf_workspaces.owner_user_id` — `RESTRICT`. Purge не мог сработать никогда:
   запись, которую он ждал, к тому моменту уже откатилась.

## Восстановление Production migration credential (выполнено)

Модель прав была правильной изначально: runtime `stratforge_app` ≠ владелец,
таблицами владеет `stratforge_migration`. Отсутствовал только persisted
credential — `production-maintenance.env` никогда не создавался.

Выполнено по санкции владельца: ACL снят в snapshot, `postgres` получил
**только traverse (x)**, нерекурсивно; peer-admin probe PASS; пароль
`stratforge_migration` сгенерирован на хосте и нигде не выведен;
`production-maintenance.env` создан (0600); соединение и DDL проверены в
транзакции с откатом; ACL восстановлен из snapshot — **EXACT MATCH**, доступ
`postgres` к сокету снова DENIED.

Дальнейшие миграции ACL не требуют: DSN — обычный loopback SCRAM.

## Release Center: expand_migrate теперь настоящий — ЗАКРЫТО (PR #76)

`promote_release` выполняет pending-миграции окружения **до** любого движения
кода, через maintenance-DSN именно этого окружения:
`plan → сверка checksum набора → apply → проверка, что pending пуст`.

- любой сбой → **промоут отменяется**, код не уезжает на схему, которая не
  дошла до нужного состояния;
- нет pending → честный **SKIPPED**, а не выдуманный pass;
- статус шага в payload — реальный результат, а не константа;
- **отсутствие maintenance credential = отказ**, а не тихий пропуск (именно
  это состояние и позволило Production незаметно разъехаться);
- DSN читается в subshell, наружу уходят только производные значения без
  секретов.

Проверено end-to-end на обоих окружениях (`beta.11`):

```
2. canary/expand_migrate     -> skipped  {"pending":0,"migration_set_sha256":"af4fe7bb…"}
2. production/expand_migrate -> skipped  {"pending":0,"migration_set_sha256":"af4fe7bb…"}
```

Гейт доказан и в отрицательном сценарии: первый промоут Production **отказал**
до деплоя, потому что DSN читался пустым (см. грабли ниже).

## Item 2 — LOCAL market data: контур доказан, UI-подтверждение за владельцем

Токен `NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN` перенесён в LOCAL secret store
(`data/integrations/secrets.local.json`, gitignored, значение нигде не
печаталось, второй credential не создавался).

Роли подтверждены из живых процессов:

| | effective_role | chart_source_mode |
| --- | --- | --- |
| Production | **hub** | `direct_hub` |
| Canary | consumer | `owner_gateway_consumer` |
| LOCAL | consumer | `owner_gateway_consumer` |

LOCAL `/api/ops/runtime/bars/status`: `topstepx runtime_state=LIVE`,
`blocking_reasons: [owner_market_data_gateway_consumer,
owner_credentials_present_but_direct_hub_forbidden]` — то есть LOCAL получает
данные через hub и **не открывает свою сессию**.

**Одна provider connection** доказана lease-механизмом: держатель ровно один —
Production `api-app` (pid 2068227, environment `production`), heartbeat свежий.

Market-data regression: **142 passed**.

**Не подтверждено автоматизацией:** живые графики в UI Canary/Production —
`/api/ops/runtime/bars/status` там отдаёт 401 без сессии владельца. Требуется
владелец (см. WAITING FOR OWNER). Мультиплексирование подписок и live-failover
измерены только регрессией, не на живом трафике.

Ловушка: разовый in-process probe без окружения `start.ps1` покажет
`isolated`, потому что `data_path` разрешается в другой data root. Верить
только запущенному серверу.

## Осталось (не начато)

1. ~~LOCAL market data~~ — см. выше — код consumer'а смержен (PR #62), осталось положить
   `NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN` в LOCAL secret store и доказать
   LIVE на LOCAL + Canary + Production при одной provider connection.
3. RBAC/Admin во всех окружениях.
4. Встроенный Connectors/Telegram dashboard.
5. Environment Switcher auto-load.
6. New-user onboarding E2E + удаление тестового пользователя.
7. Market-data regression (репозиторная часть зелёная: 136 passed).
8. Browser E2E LOCAL → CANARY → PRODUCTION.
9. Повторный perf-замер.

## Готовые инструменты (в репозитории)

`tools/drive_release.py`, `tools/host_user_cleanup.py`, `tools/host_fk_audit.py`,
`tools/host_blockers.py`, `tools/admin_reach.py`.
Запуск host-скриптов: `scratchpad/run_host_script.py`,
интерпретатор через `SF_REMOTE_PYTHON=canary|production`.

## Грабли

- Прерванный деплой раньше делал версию непересобираемой — **исправлено
  (PR #68)**: каталог уходит в `$RELEASES/.quarantine`, живой не трогается.
- Приложение перегенерирует `data/governance-rendered/*` при старте, а Release
  Center отказывает на грязном дереве → `git stash push -- NT-Analyzer/data/`.
- `VERSION.json`: `build_date` обязан совпадать с датой `build_timestamp_utc`.
- **Значение в `*-maintenance.env` обязано быть в одинарных кавычках.** DSN
  содержит `&`, `?`, `=`; без кавычек `set -a; . file` даёт **пустую**
  переменную (bash читает `&` как оператор), и миграции падают с
  «Required database URL environment variable is empty». Ошибку видно только
  по пустому значению, не по ошибке sourcing.

## WAITING FOR OWNER

1. Физический Google/Telegram/email клик там, где OAuth-consent нельзя пройти
   автоматизацией.
2. Ротация четырёх секретов (Google ×2, Resend ×2) — **только после полного
   технического PASS**.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-16T21:30:00Z | Claude Opus 5 через Claude Code по запросу owner | Production migration credential восстановлен по санкции владельца (ACL temporary + exact restore), migration 0012 применена на обоих окружениях, четыре дефекта удаления аккаунта исправлены (PR #60/#62/#71/#73), база очищена до canonical owner на Canary и Production, parity beta.10 EXACT MATCH, orphan integrity PASS.
-->
