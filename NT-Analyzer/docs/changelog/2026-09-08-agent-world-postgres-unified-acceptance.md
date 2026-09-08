# Agent World — повторная disposable PostgreSQL acceptance

Дата: 2026-09-08. Область: testing tools и независимое evidence в принятом
`codex/agent-world-unified-acceptance`. Исходный checkout:
`1409553a46d0dffa7ef329b28029d93f68b405d7`.
Авторство: AI-assisted change. Это не release, merge или deploy.

## Что изменено

- Добавлен воспроизводимый bounded launcher
  `deploy/testing/agent-world-postgres-runtime-acceptance.py`: собственные
  ignored roots, generated credentials, HTTP API, настоящий spawned worker,
  named local test executor, остановка только подтверждённого PID-дерева,
  повторный старт и прямые RLS-проверки обычной PostgreSQL-ролью.
- Идентичность кода фиксируется SHA Git, dirty status, полным manifest SHA-256
  `app/**/*.py`, общим hash этого manifest и hash самого acceptance tool.
  Изменение Python приложения между стартами проваливает проверку.
- Добавлены pure safety/response-shape тесты launcher. Он не наследует ключи
  оператора, не принимает чужие DSN/roots и отказывает защищённым портам.
  Python socket guard действует также в spawned worker; внешняя сеть запрещена.
- Исправлен только testing provisioner: `pg_ctl start` больше не передаёт
  дочернему PostgreSQL захваченные stdout/stderr pipes, из-за которых Windows
  мог удерживать launcher после успешного старта. CREATE ROLE выполняется
  psycopg в процессе: пароль не попадает в `psql -c` process argv.

Shared server, migration order, storage selection, permissions, Auth,
Device Confirmation, SF Chat, SF Social и рабочие Local-данные этим slice
не изменялись. Изменения других исполнителей учитываются отдельным manifest.

## Проверки: независимые результаты, не сумма старых PASS

| Проверка этого checkout | Результат |
| --- | --- |
| Новая Agent World PostgreSQL/RLS suite | **69 passed, 0 skipped**, 76.33 s |
| Legacy PostgreSQL: production storage/workers, relational SF Chat, stage 8 | **41 passed, 0 skipped**, 113.09 s |
| Pure acceptance harness contracts | **42 passed, 0 skipped**, 0.99 s |
| `py_compile` обоих testing tools | PASS |
| Полностью свежий запуск исправленного provisioner | PASS; TLS, own cluster, launcher завершился |
| HTTP → worker → PG result/evaluation → exact restart → history/RLS | **PASS**, собственный API 8805; synthetic, не реальный LLM |
| `git diff --check` | PASS |

Прежние опубликованные PostgreSQL PASS не переиспользованы как результаты
этого checkout. Missing opt-in в обычной full suite остаётся `skipped`, а не
подтверждённой PostgreSQL acceptance. Обе PostgreSQL suite здесь действительно
запущены на новой disposable БД, последовательно и **до** runtime-сценария:
fixtures используют TRUNCATE. Launcher запрещает suites после runtime evidence.

## Изоляция и локальные артефакты

Основная disposable БД: `aw_disposable_60948dfe8f76`, PostgreSQL **16.4**,
TLS loopback `127.0.0.1:55387`, application role `stratforge_app`,
`NOSUPERUSER / NOCREATEDB / NOBYPASSRLS`. Миграции 1–23 применены штатным
`MigrationRunner`; migration-set SHA-256:
`3e5a1ccf5c1e1fa75ef9ba66e8e9926ceebc3aac97adc7bea470c3f534ee38e3`.

Evidence, логи, JUnit XML и generated `cluster/acceptance.env` находятся только
в `.artifacts/pg-runtime-acceptance-20260908/`. Environment-файл содержит
исключительно собственные disposable credentials; не печатать и не включать
в Git. Эти файлы не являются отгружаемыми данными приложения.

Для самостоятельной проверки исправленного provisioner создан второй cluster:
`aw_disposable_bcba72953b32`, TLS `64913`. После PASS PostgreSQL PID `31620`
остановлен штатным `pg_ctl` с предварительной проверкой точного PID/PGDATA.
Его данные сохранены в
`.artifacts/pg-runtime-acceptance-provision-check-20260908/`.
Порт 8765 и рабочие owner-данные не использовались; порт 8804 другого исполнителя
не занимался. Runtime этого slice предназначен только для `127.0.0.1:8805`.

## Фактический runtime проход

Runtime evidence и собственные app/queue/keys:
`.artifacts/pg-runtime-acceptance-20260908-r2/`. Его `cluster` — junction к
своему первому disposable cluster, не к рабочей PostgreSQL. БД не очищалась
и существующие task/job IDs при повторе не пересоздавались.

- Старт/повторный старт выполнялись в согласованное окно без изменений
  `app/**/*.py`. Git SHA указан выше, working tree содержал интеграционный WIP.
  **214** Python-файлов; одинаковый tree SHA-256 до/после:
  `6ab20f16fb9254201d717cb085dd612e80f06776e753c152886ca54bbd6b1ff2`.
  Hash выполненного harness:
  `c00b41423818f1e99cf15eafd8a904eb720a140d2fa300ed3c679eeee41b271c`.
- Штатный Local entry создал disposable owner `991880501`, UUID
  `90e49cd9-3a3d-416c-942a-e2bed7a52304`, workspace
  `ws_owner_training_2dba2dd8f4f2`. Не использовались browser bypass для service
  principal, owner-копия данных или direct writes в application repository.
- Persona создана/активирована API:
  `bf3a1e44-4747-5d7d-9ea5-b82784cadac6`; модель/подключение:
  `5087c27d-90dd-5059-ae1a-edbbc1c12a32`. Сгенерированный
  `not-a-provider-key-*` — бесполезная synthetic строка, не внешний ключ.
- Connection-check `9a8cb64f-6932-580e-9ebc-34a85307f409` завершился
  `verified_automatically`. Задача
  `4386baff-3b80-5d66-9afb-d9b7cf045a42` для `[11,7,3,5]` вернула
  `count=4, sum=26, min=3, max=11, mean=6.5`; одна независимая evaluation.
  Статус `awaiting_review` остался тем же после перезапуска. Проверка владельца
  автоматически не подтверждалась.
- Реальные source jobs `wj_aw_model_<task UUID без дефисов>` обработал
  **дочерний worker `proc-16316`**, оба `succeeded`, `attempts=1`.
  Это подтверждено `/api/worker/jobs`, exact owned tree, user/workspace и
  queue path внутри своего app-data. Идемпотентный повтор сохранил те же jobs
  и исходный worker ID; он не переименован в нового worker после restart.
- Контрольный parent **17772** / worker **20104** остановлены; новый parent
  **27472** / worker **12412** прочитал прежние task/result/evaluation и
  активное подключение. Оба дерева остановлены с проверкой PID + creation time
  и точного launcher argv. Порт 8805 после прохода свободен; данные сохранены.
- DB app-role: `stratforge_app`, `rolsuper=false`, `rolbypassrls=false`; TLS
  включён, 10 таблиц имеют `ENABLE` и `FORCE ROW LEVEL SECURITY`, role не их owner.
  До/после restart: **20 records, 65 revisions/events/outbox/mutations,
  2 inbox, 28 artifacts** — без изменения счётчиков.
- Чужой workspace, отсутствующий scope и чужой environment видят **0 rows**
  во всех 10 таблицах. Другой principal в том же workspace видит допустимые
  workspace-shared records/revisions, но не owned events, outbox, mutations,
  inbox, artifacts или private records. Случай private memory с непустой
  выборкой отдельно подтверждён 69-suite, не подменён пустой runtime-выборкой.
  Запись события в чужой workspace отклонена PostgreSQL **SQLSTATE 42501**.
- HTTP подмена workspace через query отклонена **409**; выбор workspace без
  membership — **403**. Файл `ai_lab/agent-world.sqlite3` не создавался до или
  после restart. Существующая очередь `durable/nt_analyzer.sqlite3` —
  предусмотренный Development worker, а не fallback Agent World repository.

Первая настройка harness потребовала исправления ожидания legacy `user_id`
на public canonical `user.id`. В следующем проходе уточнены две ошибочные
acceptance-предпосылки: workspace-shared не равно private; идемпотентный retry
сохраняет прежний worker ID. Failed artifacts и `harness_failures` сохранены,
app data не откатывались. Это исправления testing harness, не замаскированные
ошибки приложения и не повторные внешние вызовы.

## Границы доказательства и следующий шаг

Тест использует **нового disposable Local-owner**, штатный Development entry и
обычную DB application role. Это **не** приёмка регистрации обычного человека,
его отдельного ключа или BYOK. Named `agent-world-local-test-executor-v1` —
synthetic infrastructure evidence: не реальный LLM, не профессиональное
качество модели, не NinjaTrader backtest и не PNG графика. SQL-проверки
Agent World PostgreSQL не означают перевод всего Development auth/queue на PG:
существующая отдельная local worker queue остаётся SQLite по контракту.

Известное отдельное замечание к продуктовой проекции: при named local test
executor поля `actual_model/executor/external_call=false` честные, но
`model_service` на этом manifest ещё выдаёт `synthetic=false` и
`source_kind=real_model_response` в общем DTO. Это передано root для отдельной
правки после freeze и не интерпретируется как реальный model-result PASS.

Следующий шаг: root интегрирует truthful synthetic projection и остальные
независимые изменения; при новом Python manifest этот runtime snapshot
не обозначается автоматически проверкой нового кода. Current-status и
External GPT Context Pack согласует root до Git closeout. Это testing
checkpoint, а не закрытие всей программы Agent World.
Commit/PR integration — ответственность root; этот исполнитель ничего не
stage/commit/push. Версия приложения не менялась. Release impact: отсутствует.
