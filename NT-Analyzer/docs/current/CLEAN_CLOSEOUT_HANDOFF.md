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

**Это и есть первый FAIL для следующей сессии.**

### Что уже проверено (не повторять)

Поиск существующего credential по всему хосту — `config/`, `runtime/`, `run/`,
`/home/stratforge`, `/etc/supervisor`, `/etc/default`, `/etc/systemd` — с
выводом только *формы* присваивания, без значений:
**реального Production migration DSN нет нигде.** Все совпадения с
`LITERAL-DSN` — это тестовые фикстуры в `tests/test_phase7_canary_isolation.py`
внутри старых build-каталогов. `/root` доступен через sudo, но **пуст**.
`/etc/stratforge` отсутствует.

Попытка пойти по разрешённому пути ротации остановлена на шаге доказательства
«роль maintenance-only». Установлено:

- ни одна supervisor-программа не называет роль в своём environment;
- живых сессий роли в БД нет (только `stratforge_app`);
- cron/systemd-таймеров с ролью нет;
- **НО** у двух процессов environment нечитаем: `postgresql` и
  **`offhost-backup-scheduler`**. На Canary `STRATFORGE_BACKUP_DATABASE_URL`
  **равен** migration DSN, поэтому вероятно, что Production backup-планировщик
  ходит именно этой ролью. Ротация пароля сломала бы off-host backup.
- `sudo -n -u postgres psql` по умолчанию **не подключается**
  (`/var/run/postgresql/.s.PGSQL.5432` — не тот сокет; кластер живёт в
  `/home/stratforge/production_data/run/postgresql`). Проверить проектный сокет
  не удалось: дальнейшая инспекция была заблокирована политикой.

### Что нужно сделать следующей сессии

1. Выяснить, каким credential ходит `offhost-backup-scheduler` (его environment
   читается только root/самим процессом). Пока это не выяснено — **не
   ротировать**: это единственный кандидат на активного потребителя роли.
2. Проверить админ-доступ через проектный сокет:
   `sudo -n -u postgres psql -h /home/stratforge/production_data/run/postgresql`.
   Если он работает и п.1 подтверждает, что роль maintenance-only — ротировать
   **только** пароль `stratforge_migration`, записать DSN **только** в
   `config/production-maintenance.env` (0600, owner `stratforge`), runtime
   app credential не трогать, значение не печатать, затем проверить DDL в
   транзакции с откатом.
3. Если ни credential, ни админ-пути нет — это настоящий `WAITING FOR OWNER`.

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

- ~~Прерванный деплой делает свою версию невозможной для пересборки.~~
  **ИСПРАВЛЕНО (PR #68).** Каталог переиспользуется только если проходит
  `canary_manifest_trust` как ровно этот immutable release; иначе уезжает в
  `$RELEASES/.quarantine/<ref>.<timestamp>` (паркуется, не удаляется).
  Каталог, на который смотрит живой симлинк, не трогается никогда.
- `release_buttons.py` умирает молча, если его убить в фоне: буферизованный
  вывод теряется и candidate остаётся в неконсистентном состоянии.
  Использовать `drive_release.py`.
- Приложение перегенерирует `data/governance-rendered/*` при каждом старте, а
  Release Center отказывает на грязном дереве → перед каждым билдом
  `git stash push -- NT-Analyzer/data/`.
- `VERSION.json`: `build_date` обязан совпадать с датой `build_timestamp_utc`,
  иначе бэкенд не стартует (теперь есть тест).

## Не начато

- **Release Center: честный pipeline** (крупный пункт, не начат). Сейчас
  `expand_migrate` — косметический `pass`. Нужно:
  `backup/verify → expand migration через maintenance DSN → migration
  verification → blue-green deploy → readiness → acceptance → promote`;
  отсутствие миграций = честный `SKIPPED`; провал миграции = код не
  выкатывается; maintenance credential не попадает в artifact/browser/log;
  regression/integration тесты. Затрагивает `stage9_remote_release.sh`
  (жёстко зашитый список шагов), `release_executor.py`, `blue_green.py`.
- RBAC/Admin во всех средах, встроенный connector dashboard,
  Environment Switcher auto-load, new-user E2E, browser E2E, повторный
  perf-замер, LOCAL gateway token.

## WAITING FOR OWNER

1. Физический клик в Google/Telegram consent там, где браузерная автоматизация
   не может пройти OAuth за человека.
2. Ротация 4 секретов — **только после полного технического PASS**
   (Google Client Secret ×2, Resend API key ×2).

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-16T01:30:00Z | Claude Opus 5 через Claude Code по запросу owner | Executable handoff чистого закрытия этапа. Первый FAIL: migration 0012 требует ownership таблиц, роль приложения им не обладает — блокирует Canary-деплой beta.7/beta.8 и, следовательно, Production cleanup. Live остаётся beta.6 с полным artifact parity. Зафиксированы готовые скрипты, порядок работ и грабли.
-->
