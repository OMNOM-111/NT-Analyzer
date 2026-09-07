# Agent World — PostgreSQL repository и проверенная RLS-изоляция

## Изменение и границы

Добавлен PostgreSQL-адаптер канонических Agent World contracts, чтобы закрыть
отсутствовавшую реализацию нового хранилища. Исходная точка этого slice:
`45ab4361d5ab9b8422ec049c0c689953d548a318`, ветка `codex/agent-world-mechanisms`.
Это AI-assisted change; новый номер версии не назначен. Итоговый commit/PR
фиксируется координатором общего этапа после интеграционных gates.

- `PostgresAgentWorldRepository` использует существующий `PostgresClient`:
  scoped-транзакции, CAS, immutable revisions/events, атомарные outbox и
  idempotency result, inbox receipts, content-addressed artifacts и signed
  snapshot pagination. Проверено сохранение всех 17 существующих типов DTO.
- Добавочная миграция `0023_agent_world_repository.sql` создаёт 10 таблиц с
  `ENABLE ROW LEVEL SECURITY`, `FORCE ROW LEVEL SECURITY`, явными `USING` /
  `WITH CHECK` и scoped foreign keys. Обычная роль приложения не владелец
  таблиц, не superuser, не наследует роль владельца и не имеет `BYPASSRLS`.
- Каждый вызов устанавливает transaction-local environment/workspace/user
  context. Отсутствующий контекст и global service scope не обходят RLS.
  Аутентификацию, членство, capabilities и budgets по-прежнему проверяют
  существующие сервисы; `RequestContext` не принимается из пользовательского
  JSON и сам по себе не является авторизацией.
- Сохраняется текущий контракт видимости: workspace-visible record DTO может
  читаться допущенным участником workspace; private Memory, artifacts,
  immutable revision API, events, mutations и receipts изолированы по owner.
  Запись чужой сущности запрещена дополнительно и в БД.
- Публикация Memory использует только производные grant/anchor indexes,
  сформированные атомарно из существующего active Memory, publication proof,
  точной source revision, TTL и, для verified lesson, текущего Outcome.
  Изменение source/Outcome инвалидирует индекс той же транзакцией; SQL trigger
  также закрывает доступ, если scoped writer не выполнил application refresh.
  Истечение TTL проверяется по времени БД. Private artifact API не включает
  опубликованные grants; чтение опубликованных bytes — отдельный явный путь.
- Конструктор не подключается к БД, не выполняет DDL/миграции и не создаёт
  fallback. Canary/Production требуют клиента с existing Production/TLS
  contract. Отсутствующая схема или небезопасная роль закрывают доступ.
- Не создана вторая очередь, scheduler, worker lease, permission или budget
  система. PostgreSQL advisory transaction locks обеспечивают CAS, а durable
  worker leases остаются в существующем production worker механизме.

## Проверки на новой временной БД

Проверена отдельная новая PostgreSQL **17.11** на случайном loopback-порту,
с временным TLS-сертификатом и непривилегированной ролью `stratforge_app`.
Существующие Local/owner/Canary/Production БД, DSN, секреты и runtime 8765
не использовались. Метки сред в тестах — данные для RLS-проверки, не deploy.

| Проверка | Фактический результат этого slice |
| --- | --- |
| Новые Agent World PG tests | **69 PASS**, 0 failed, 0 skipped; 97.59 s |
| Existing PG storage/workers/Stage8/SF Chat regression | **41 PASS**, 0 failed, 0 skipped; 131.80 s |
| SQLite storage + domain service + contracts regression | **311 PASS** |
| Python compile затронутых Python-файлов | PASS |
| `git diff --check` | PASS |
| Новые PG tests без explicit disposable configuration | 1 unit PASS / **68 SKIPPED**, не PG acceptance |

Исторические 41 PASS старого этапа и прежние 41 SKIPPED без тестового DSN не
использовались как доказательство. Здесь существующие 41 тест реально выполнены
повторно на новой схеме 1–23. Во время проверки найдены четыре устаревших
ожидания номера миграции в `test_production_storage.py`,
`test_production_workers.py`, `test_stage8_postgresql.py`: обновлены только
литералы 22 → 23 / диапазон 1–22 → 1–23; логика этих тестов не изменена.

Новые тесты включают cross-environment/workspace/user SELECT/INSERT/UPDATE,
RLS без каждого обязательного контекста, FORCE RLS для schema owner, запрет
TRUNCATE/rewrite evidence у app role, очистку контекста между соединениями,
concurrent CAS и replay, rollback всего commit при отказе outbox, private
artifact hashes, pagination/restart и Memory revoke/expiry/Outcome revalidation.
Fixtures синтетические; это настоящие SQL/RLS-транзакции, не реальные запросы
к модели, бирже или пользовательские результаты работы агентов.

Локальные generated evidence/JUnit и disposable runner находятся только в
ignored `.artifacts/agent-world-postgres-20260905/`; они не входят в artifact
или обычную Git-историю. `acceptance-evidence.json` содержит hashes JUnit,
миграции, сведения TLS/ролей/RLS без DSN и секретов. PostgreSQL получен с
официального EDB HTTPS download; SHA256 скачанного архива вычислен локально,
vendor-published checksum/Authenticode подпись не заявлены.

## Следующий шаг и статус

Адаптер и новые storage contracts проверены локально. Product status для
эксплуатации нового PostgreSQL пути — **IN DEVELOPMENT** до интеграции
единственной server-side repository factory, service/worker scope admission
и общего review/gates. Конструктор не может сам включить этот путь или
мигрировать Local; обычный SQLite Development не изменён.

Full application regression, current/context docs, финальный source SHA и
Git/CI closeout относятся к общему этапу координатора. **STAGE CLOSED**,
Canary acceptance и Production readiness этим slice не объявляются.
Rollback для неактивированного пути — не выбирать новый adapter; существующие
данные не переносились. Обратная разрушительная миграция не добавлена.
