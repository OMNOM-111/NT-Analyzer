# StratForge Production storage runbook

## Назначение и граница

Production использует PostgreSQL как единственный authoritative store для
auth, workspaces, entitlements, Connector state, jobs, commands и audit.
Крупные payload-файлы хранятся в изолированном artifact root; PostgreSQL
содержит только server-generated object key, workspace, checksum, размер,
retention и metadata. Production никогда не откатывается на локальный
DPAPI/JSON/SQLite при недоступности базы.

Локальные DPAPI/JSON/SQLite остаются только Development-контуром. Их полный
автоматический перенос запрещён: owner cutover всегда строится из явно
выбранных категорий, workspace и Connector installation.

## Роли и секреты

Используются разные подключения:

| Назначение | Минимальная роль | Где доступно |
|---|---|---|
| Runtime | `stratforge_app`, без superuser/BYPASSRLS | только service secret provider |
| Migration | ограниченная DDL-role/владелец схемы | только окно изменения schema |
| Backup | managed snapshot identity или read-only role с правом видеть все RLS-строки | только backup job |
| Restore | владелец новой пустой базы; может replay default ACL migration-role | только incident/restore drill |

DSN не передаётся аргументом CLI, не записывается в Git, report или shell
history. CLI читает только имя environment variable. Production DSN обязан
использовать TLS; штатный вариант — `sslmode=verify-full` с доверенным CA.
`sslmode=require` допустим только по отдельно зафиксированному решению, если
проверка имени/CA обеспечена другим управляемым слоем.

Runtime role не используется для полного `pg_dump`: принудительный RLS может
сделать такой dump неполным. Backup identity должна обходить RLS только для
чтения либо заменяться provider snapshot.

`pg_dump` сохраняет `ALTER DEFAULT PRIVILEGES FOR ROLE stratforge_migration`.
Поэтому отдельная `stratforge_restore` должна иметь `SET`/`INHERIT` membership
в migration-role, иначе `pg_restore --exit-on-error` остановится на default ACL.
Эта роль не получает `CONNECT` к действующей Production database; её пароль
доступен только административному restore job. После создания ролей на
PostgreSQL 16+ используется:

~~~sql
GRANT stratforge_migration TO stratforge_restore WITH INHERIT TRUE, SET TRUE;
REVOKE CONNECT ON DATABASE stratforge_production FROM stratforge_restore;
~~~

## Каталоги

~~~text
~/apps/stratforge/releases/<version>/       immutable code
~/var/stratforge/                           small runtime state
~/var/stratforge-artifacts/                 authoritative artifact payloads
~/backups/stratforge/<backup-id>/           dump + objects + manifest
~/.config/stratforge/production.env         mode 0600
~~~

Release, runtime state, artifact root и backup root не могут быть вложены друг
в друга. Symlink внутри artifact root останавливает backup.

## Schema migration

Перед изменением schema создаётся и проверяется combined backup. Затем в
защищённой административной сессии:

~~~bash
read -r -s -p 'Migration DSN: ' STRATFORGE_MIGRATION_DATABASE_URL
export STRATFORGE_MIGRATION_DATABASE_URL
python tools/production_storage_cli.py schema
~~~

Dry-run выводит pending versions и `migration_set_sha256`, но не DSN. Apply
выполняется только с checksum именно этого плана:

~~~bash
python tools/production_storage_cli.py schema \
  --apply \
  --confirm-migration-set-sha256 '<reviewed-migration-set-sha256>'
unset STRATFORGE_MIGRATION_DATABASE_URL
~~~

Каждая применённая SQL migration immutable. Старый файл не редактируется;
следующее изменение получает новый номер. Advisory lock и одна транзакция не
дают двум операторам применить набор одновременно. Checksum mismatch — стоп,
а не повод менять migration ledger вручную.

## Выборочная миграция owner data

До dry-run обязателен проверенный snapshot Development data root. Команда
запускается на текущем Development Windows-компьютере под тем пользователем,
который может расшифровать DPAPI store. `STRATFORGE_ENV` остаётся явно
`development`, а целевой DSN передаётся отдельно через защищённую переменную.

Пример без Connector и без ledger:

~~~powershell
$env:STRATFORGE_ENV = 'development'
$env:STRATFORGE_DATABASE_URL = '<read from protected secret provider>'
python tools/production_storage_cli.py owner `
  --owner-user-id 123456789 `
  --include auth `
  --include workspaces `
  --include entitlements `
  --workspace-id ws_owner_EXPLICIT_ID
~~~

Для Connector требуется отдельный `--include connectors` и один или несколько
`--installation-id`. Для account ledger требуется `--include ledgers`.
Ни одна категория и ни один ID не выбираются автоматически.

Dry-run выводит только IDs, counts, redaction counts, `source_sha256` и
`plan_sha256`; owner payload не печатается и не сохраняется. После проверки
того же источника apply повторяет команду с:

~~~text
--apply --confirm-sha256 <reviewed-plan-sha256>
~~~

Одна PostgreSQL transaction применяет compatibility documents, normalized
mirrors, ledgers и migration journal. Повтор того же plan checksum идемпотентен.
Конфликт с уже существующей отличающейся записью останавливает весь перенос.

Никогда не переносятся:

- auth challenges, cookies, session/CSRF/access/refresh tokens;
- enrollment codes/nonces, Connector sessions, commands и results;
- legacy pairings/connections, которые не доказали device-key handshake;
- payment secrets/config и произвольные vouchers/requests;
- absolute client paths, NinjaTrader user directory, project/data/runtime root;
- private JWK fields.

Выбранная Connector installation после переноса получает `offline` и должна
заново выполнить signed hello. Фактические owner-данные нельзя применять до
явного выбора владельца; синтетический acceptance test не является owner
cutover.

## Quota и retention

Baseline из production template:

- default workspace quota: 10 GiB;
- max one artifact: 512 MiB;
- minimum free-space gate: 4 GiB;
- audit retention в schema: 730 дней;
- artifact retention задаётся metadata записи, максимум 3650 дней.

Просмотр и явное изменение workspace quota:

~~~bash
python tools/production_storage_cli.py quota \
  --workspace-id ws_EXPLICIT

python tools/production_storage_cli.py quota \
  --workspace-id ws_EXPLICIT \
  --set-bytes 21474836480 \
  --confirm-workspace-id ws_EXPLICIT
~~~

Quota нельзя установить ниже текущего active usage. Artifact object key всегда
создаёт сервер; logical filename очищается, а чтение повторно проверяет размер
и SHA-256.

Retention сначала только планируется:

~~~bash
python tools/production_storage_cli.py retention \
  --workspace-id ws_EXPLICIT
~~~

Apply требует совпадающий checksum и дополнительный host gate:

~~~bash
export STRATFORGE_RETENTION_EXECUTION_ALLOWED=1
python tools/production_storage_cli.py retention \
  --workspace-id ws_EXPLICIT \
  --apply \
  --confirm-sha256 '<reviewed-plan-sha256>'
unset STRATFORGE_RETENTION_EXECUTION_ALLOWED
~~~

Payload сначала перемещается в `.trash/<workspace>/...`, metadata получает
`quarantined`, а ошибка транзакции запускает компенсационный filesystem
rollback. Permanent purge намеренно отсутствует: он добавляется только после
отдельного backup, owner approval и подтверждённого retention window.

## Combined backup

Для первого Production cutover используется простой и доказуемый quiesced
window: убрать traffic, остановить application writers и подтвердить отсутствие
активных worker/Connector writes. Один только флаг CLI не заменяет эту
операционную проверку.

~~~bash
systemctl --user stop cloudflared.service stratforge.service stratforge-worker.service
read -r -s -p 'Backup DSN: ' STRATFORGE_BACKUP_DATABASE_URL
export STRATFORGE_BACKUP_DATABASE_URL
export STRATFORGE_PG_BIN='/usr/lib/postgresql/17/bin'
python tools/production_storage_cli.py backup \
  --artifact-root "$HOME/var/stratforge-artifacts" \
  --output-dir "$HOME/backups/stratforge/$(date -u +%Y%m%dT%H%M%SZ)" \
  --confirm-quiesced
unset STRATFORGE_BACKUP_DATABASE_URL
~~~

Backup публикуется атомарно только после:

- successful custom-format `pg_dump` and `pg_restore --list`;
- table counts и schema migration ledger;
- стабильного полного сканирования artifact root;
- per-file SHA-256 и aggregate SHA-256;
- отдельного checksum самого manifest.

Повторная проверка:

~~~bash
python tools/production_storage_cli.py verify-backup \
  --backup-dir '<exact-backup-directory>'
~~~

После успешной проверки сервис запускается, затем проверяются liveness,
readiness и canary read/write. Backup directory после создания read-only и
реплицируется в отдельный encrypted failure domain.

## Isolated restore drill

Restore поверх действующей базы или существующего artifact root запрещён. До
команды администратор создаёт отдельную пустую database и выбирает
несуществующий каталог. Restore-role владеет этой database, имеет описанное
выше membership для replay default ACL и по-прежнему не может подключаться к
действующей Production database. Имя target DB и dump SHA подтверждаются
отдельно:

~~~bash
read -r -s -p 'Restore DSN: ' STRATFORGE_RESTORE_DATABASE_URL
export STRATFORGE_RESTORE_DATABASE_URL
python tools/production_storage_cli.py restore \
  --backup-dir '<exact-backup-directory>' \
  --artifact-target '<new-nonexistent-artifact-root>' \
  --confirm-dump-sha256 '<verified-dump-sha256>' \
  --confirm-target-database '<new-empty-database-name>'
unset STRATFORGE_RESTORE_DATABASE_URL
~~~

CLI отказывает, если target DB имеет хотя бы одну public table или artifact
target уже существует. После restore он сравнивает counts, migration ledger и
artifact checksums. Затем приложение под runtime role выполняет read-only smoke
в изолированной цели. Неуспешная цель сохраняется для расследования или
удаляется администратором только после проверки точного имени/пути.

## RPO, RTO и расписание

До фактического измерения на Production baseline такой:

- RPO не более 24 часов; дополнительно backup перед каждым schema/release/data
  migration;
- RTO target 4 часа для database + artifacts + application smoke;
- хранение: 7 daily, 4 weekly, 12 monthly;
- ежемесячный isolated restore drill и внеочередной drill после изменения
  backup tooling/provider.

Эти значения — launch gate. Если provider/администратор не подтверждает место,
шифрование, расписание, off-host copy и measured restore, Production остаётся
`BLOCKED_EXTERNAL`.

## Отказы и rollback

- Database outage/read-only: process liveness может оставаться 200, readiness
  становится 503, authoritative read/write fail closed; local fallback нет.
- Artifact root missing/read-only/low-space: readiness 503, новые artifacts не
  принимаются; PostgreSQL metadata не подменяет отсутствующий payload.
- Disk-full/partial copy: backup не публикуется, temp directory очищается;
  действующие DB/artifacts не меняются.
- Schema failure: transaction rollback; исправление только новой migration.

Rollback после cutover:

1. Убрать traffic и остановить writers.
2. Сохранить failed DB/artifact state для расследования.
3. Восстановить last-known-good backup в новую DB и новый artifact root.
4. Указать старому совместимому release новый DSN/root через secret/config.
5. Проверить migration checksum, runtime-role access, readiness и canary smoke.
6. Только затем вернуть traffic.

In-place downgrade SQL, ручное изменение `sf_schema_migrations` и непроверенный
dual-write запрещены. Текущий переход выполняется single-write cutover только
после checksum-confirmed owner migration и restore-ready rollback.
