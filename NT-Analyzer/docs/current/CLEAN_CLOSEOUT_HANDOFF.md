# Clean closeout — executable handoff

Дата: `2026-08-16` UTC. Продолжать **с первого FAIL**, повторный аудит не нужен.

## LIVE состояние (проверено)

| | |
| --- | --- |
| Canary | `0.10.0-beta.6`, commit `c7b2ed23`, artifact `E370051663484F77…` |
| Production | `0.10.0-beta.6`, commit `c7b2ed23`, artifact `E370051663484F77…` |
| Parity | ✅ идентичный artifact, acceptance PASS, оба здоровы |
| repo HEAD | `3897e471` (`0.10.0-beta.8` в VERSION.json) |
| LOCAL | запущен на HEAD, дерево чистое |

`beta.7` и `beta.8` — **не live**, обе откатились. Считать live только `beta.6`.

## FIRST FAIL — migration 0012 не может примениться

**Это единственное, что блокирует всё остальное.**

Canary-деплой и `beta.7`, и `beta.8` падает на шаге миграции. Точная причина
воспроизведена напрямую против Canary DB:

```
InsufficientPrivilege: must be owner of table sf_auth_challenges
CONTEXT: SQL statement "ALTER TABLE sf_auth_challenges
         DROP CONSTRAINT IF EXISTS sf_identity_sf_auth_challenges_user_uuid_fk"
PL/pgSQL function inline_code_block line 30 at EXECUTE
```

Роль приложения (DSN `STRATFORGE_DATABASE_URL` из `/proc/<api pid>/environ`)
**не владелец таблиц**, а `ALTER TABLE … DROP CONSTRAINT` требует владения.
Отдельного migration-DSN в коде нет: `grep -rn "MIGRATION_DSN\|STRATFORGE_MIGRATION"
app/production_storage/ app/storage_router.py` — пусто.

Открытый вопрос, с которого начинать: **чем именно 0005 сумел выполнить
`ADD CONSTRAINT`, если 0012 не может выполнить `DROP CONSTRAINT`?** Варианты:

1. `expand_migrate` в blue/green запускает миграции под другой ролью, чем
   работающий api-процесс — тогда мой тест использовал не тот DSN, и настоящую
   ошибку деплоя надо взять из host-логов blue/green, а не из моего теста;
2. владелец таблиц сменился после 0001/0005 — тогда нужно вернуть ownership
   или выдать роли приложения права;
3. 0012 нужно переписать так, чтобы он не требовал ownership (для смены FK
   semantics это невозможно) либо применялся отдельным привилегированным шагом.

Проверить (1) первым: это самый дешёвый и самый вероятный.

Воспроизведение под рукой:
`scratchpad/test_0012.py` — применяет 0012 в транзакции и откатывает,
печатает точную ошибку. Запуск:
`SF_REMOTE_PYTHON=canary python run_host_script.py test_0012.py sf-test-0012.py canary`

## Порядок работ после того, как 0012 применится

1. Новый candidate из HEAD → `build → verify → deploy-canary → record-canary-check
   → approve-production → promote-production`. Драйвер:
   `scratchpad/drive_release.py <version> <commit>` (пишет каждый шаг с flush,
   в отличие от `release_buttons.py`, который умирал молча).
2. Проверить, что 0012 реально применена и FK delete-семантика соответствует
   задуманной: `scratchpad/host_fk_audit.py`.
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
