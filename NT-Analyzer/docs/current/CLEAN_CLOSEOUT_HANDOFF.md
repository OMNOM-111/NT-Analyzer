# Clean closeout — executable handoff

Дата: `2026-08-16` UTC. Продолжать **с первого FAIL**, повторный аудит не нужен.

## LIVE состояние (проверено)

| | |
| --- | --- |
| Canary | `0.10.0-beta.8`, commit `3897e471`, artifact `F584E2E0BB580F6E…`, **migration 0012 применена** |
| Production | `0.10.0-beta.6`, commit `c7b2ed23`, artifact `E370051663484F77…`, 0012 **не** применена |
| repo HEAD | `3897e471` (`0.10.0-beta.8`) |
| LOCAL | запущен на HEAD, дерево чистое |

Canary acceptance PASS. Parity Canary/Production **временно нарушена намеренно**:
Canary впереди, Production ждёт применения 0012.

## РЕШЕНО: модель прав и порядок миграций

Прошлая запись «0012 требует ownership, роль приложения им не обладает» была
**верной по факту, но не тем выводом**. Правильная модель уже существует и
работает — менять архитектуру не нужно:

| окружение | runtime role | владелец таблиц |
| --- | --- | --- |
| Canary | `stratforge_canary_app` | `stratforge_canary_migration` (53 таблицы) |
| Production | `stratforge_app` | `stratforge_migration` (53 таблицы) |

`InsufficientPrivilege` возникал только потому, что воспроизведение шло по
runtime-DSN из `/proc`. Под migration-ролью 0012 применяется чисто, идемпотентна,
и даёт ровно задуманные `ON DELETE` (проверено на живой Canary):
CASCADE для owned-строк, **SET NULL для `sf_audit_events` / `sf_operational_events`
/ `sf_migration_runs`** (история сохраняется), RESTRICT для `sf_workspaces`.
`still NO ACTION: none`.

**Главное операционное открытие.** Шаг `expand_migrate` в blue/green —
**косметический**: `stage9_remote_release.sh` печатает фиксированный список
шагов со статусом `pass`, а `canary_blue_green_promote.sh` миграции **не
запускает вообще** (`grep -n "migrat" tools/canary_blue_green_promote.sh` —
пусто). Миграции применяются отдельно, вручную:

```
tools/production_storage_cli.py schema --apply \
  --url-env STRATFORGE_MIGRATION_DATABASE_URL \
  --confirm-migration-set-sha256 <set sha>
```

Поэтому деплой beta.7/beta.8 и падал в `ROLLING_BACK`: новый код проверяет
готовность против БД, где его миграции ещё нет. **Порядок обязателен:
expand-миграция → затем промоут кода.** Именно так Canary и поехала.

Готовые скрипты: `scratchpad/apply_schema.py` (canary),
`scratchpad/own_model.py` (модель прав), `scratchpad/test_0012_mig.py`
(0012 в транзакции с откатом + вывод получившихся FK-правил).

## FIRST FAIL — на Production нет persisted migration credential

Production нельзя мигрировать: **ни один конфиг на хосте не объявляет
`STRATFORGE_MIGRATION_DATABASE_URL` для Production.** Проверено явно:

```
production-maintenance.env : absent
production-app.env         : has STRATFORGE_MIGRATION_DATABASE_URL = False
production.env             : has STRATFORGE_MIGRATION_DATABASE_URL = False
```

У Canary такой файл есть — `canary-maintenance.env` (mode 0600), создан
`tools/canary_isolation_provision.py`. Производственного аналога не создавалось.
Старый `production_data/runtime/promote-0.10.0-beta.1.sh` читает
`os.environ["STRATFORGE_MIGRATION_DATABASE_URL"]` и проверяет, что пользователь
именно `stratforge_migration` — то есть значение подавалось извне и нигде не
сохранилось.

**Это и есть первый FAIL для следующей сессии.** Варианты, по возрастанию
инвазивности:

1. Найти, откуда значение подавалось при прошлых промоутах (оператор/менеджер
   секретов), и создать `config/production-maintenance.env` по образцу
   canary — mode 0600, владелец `stratforge`, вне Git, не source-ится из
   supervisor-программы api.
2. Провижнить production-maintenance.env инструментом, аналогичным
   `canary_isolation_provision.py`. Учесть: это может **сменить пароль роли**,
   что затрагивает и другие потребители.
3. Применить 0012 под `sudo -u postgres` — обходит ledger `sf_schema_migrations`
   и рассинхронизирует учёт миграций. **Не рекомендуется.**

Автоматизация дальше не пошла сознательно: путь (1) требует обращения с
секретом, который в конфигурации хоста отсутствует.

## Порядок работ после того, как 0012 применится на Production

1. Применить 0012 на Production **до** промоута кода (см. FIRST FAIL), затем
   `approve-production → promote-production` для уже собранного кандидата
   `rc_ea3c6d37fb43400aa679fa6e7e2c49fa` (`0.10.0-beta.8`, artifact
   `F584E2E0BB580F6E…`) — тот же immutable artifact, что уже принят на Canary.
2. Проверить FK-семантику на Production: `tools/host_fk_audit.py`.
3. **Production DB cleanup** — всё готово, скрипт написан и dependency-check
   пройден: `scratchpad/host_user_cleanup.py`.
   Dry-run: `SF_REMOTE_PYTHON=production python run_host_script.py
   host_user_cleanup.py sf-user-cleanup.py production eb9d8e32-8db0-d590-9b35-ef1bd07ec61f`
   Применение: то же с `--apply`.
   Удаляются 4 аккаунта (все `safe_to_delete=True`, разрешение владельца дано):
   `stage9_canary_operator` (9000000000728), `123456`, `505`,
   `ARTUR_CA` (1279070095).
4. Counts + orphan integrity: `scratchpad/host_user_mapping.py`,
   `scratchpad/host_blockers.py`.

## Что уже сделано и в проде (`beta.6`)

- **PR #60** — удаление аккаунта освобождает его операционные строки
  (`sf_commands`, `sf_jobs`, `sf_artifacts`, `sf_ai_usage_events`,
  `sf_ai_reservations`, `sf_market_data_subscriptions`). Без этого удаление
  любого non-owner аккаунта откатывалось целиком и пользователь молча оставался.
- Ранее: доставка кода подтверждения устройства (#51), полное удаление аккаунта
  (#53), сокращение payload аватара (#55), build-derived asset stamps (#57).

## Что merged, но ещё НЕ в проде (ждёт 0012)

- **PR #62** — migration 0012 (ON DELETE semantics для всех
  `sf_identity_*_user_uuid_fk`) **+ LOCAL market-data gateway fix**.
- **PR #64** — согласованность `build_date` / `build_timestamp_utc`.
- **PR #65** — `0.10.0-beta.8`.

## Зафиксированные факты (не переисследовать)

- Canary DB **уже чистая**: 1 owner, 3 identities, 1 device.
- Production DB: owner + 4 аккаунта на удаление. Backup
  `pre-identity-cleanup-20260815T223000Z` снят и проверен против live counts.
- `stage9_canary_operator` **не используется кодом** — grep по `app/` пустой,
  переносить в service principal не требуется, можно просто удалить.
- Owner на Production: `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f`, identities
  telegram + google + email, devices = 1. Совпадает с ручной проверкой владельца.
- `NOT VALID` у FK **не отключает enforcement** — только пропускает проверку
  уже существующих строк. Прежняя запись в handoff была неверной.
- LOCAL market data: причина найдена и исправлена в коде (`gateway_url()` не
  имел правила для Development → `isolated` → 0 backup providers). Осталось
  положить `NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN` в local secret store.

## Грабли этой сессии

- **Прерванный деплой делает свою версию невозможной для пересборки.**
  Remote-скрипт именует каталог релиза `$RELEASES/<version>-<commit12>` и
  переиспользует его, если он есть; пересборка той же версии даёт другой
  manifest → build падает на assertion `artifact_sha256` в
  `canary_manifest_trust`. Обход — новая версия. Починить отдельно.
- `release_buttons.py` умирает молча, если его убить в фоне: буферизованный
  вывод теряется и candidate остаётся в неконсистентном состоянии.
  Использовать `drive_release.py`.
- Приложение перегенерирует `data/governance-rendered/*` при каждом старте, а
  Release Center отказывает на грязном дереве → перед каждым билдом
  `git stash push -- NT-Analyzer/data/`.
- `VERSION.json`: `build_date` обязан совпадать с датой `build_timestamp_utc`,
  иначе бэкенд не стартует (теперь есть тест).

## Не начато

Пункты 4 (RBAC/Admin во всех средах, встроенный connector dashboard,
Environment Switcher auto-load), 5 (new-user E2E), 6 (browser E2E),
7 (повторный perf-замер).

## WAITING FOR OWNER

1. Физический клик в Google/Telegram consent там, где браузерная автоматизация
   не может пройти OAuth за человека.
2. Ротация 4 секретов — **только после полного технического PASS**
   (Google Client Secret ×2, Resend API key ×2).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-16T01:30:00Z | Claude Opus 5 через Claude Code по запросу owner | Executable handoff чистого закрытия этапа. Первый FAIL: migration 0012 требует ownership таблиц, роль приложения им не обладает — блокирует Canary-деплой beta.7/beta.8 и, следовательно, Production cleanup. Live остаётся beta.6 с полным artifact parity. Зафиксированы готовые скрипты, порядок работ и грабли.
-->
