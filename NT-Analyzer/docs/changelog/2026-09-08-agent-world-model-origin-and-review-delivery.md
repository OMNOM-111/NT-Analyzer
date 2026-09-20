# Agent World — происхождение модельного результата и доставка ручной проверки

Дата: 2026-09-08. AI-assisted change. Ветка
`codex/agent-world-unified-acceptance`; исходная интеграционная база
`1409553a46d0dffa7ef329b28029d93f68b405d7`, промежуточный checkpoint
`13573bf76bae2dbad4f9efc4f6893d0bcb4d5406` + scoped WIP.
Без merge/deploy, смены версии, включения пользовательских флагов или
изменения доступного владельцу Local 8765.

## Что изменено

`model_service` получает происхождение из сохранённого receipt, а не из
названия подключения, prompt или текущего состояния test-executor switch.
Named `agent-world-local-test-executor-v1` выдаёт
`source_kind=synthetic_model_response`, `synthetic=true`, свою actual identity,
`external_call=false` и нулевую стоимость. Противоречивый новый receipt
отклоняется. Старые immutable artifacts с ошибочным `synthetic=false`
сохраняются: read projection использует оставшиеся executor/actual-model
маркеры и продолжает проверять task/request/hash и независимый rubric proof.

Проверка local test executor не выставляет внешнему подключению `connected`:
DTO отдельно сообщает `test_executor_verified` и `test_executor_only`.
Имя провайдера/модели, Persona и сохранённое подключение не переименовываются.
Результаты тестового исполнителя исключены из real-model знаменателя;
`synthetic_observations` показывает свой класс, число различных входов,
количество задач и успешных/неуспешных проверок **без процента качества**.
Реальные bounded-model наблюдения и application conformance остаются разными
видами evidence. PNG/бэктест не получают оценку профессионального качества.

`model_chat` передаёт тот же lifecycle, что карточка задачи: полученный ответ
с успешной автоматической проверкой остаётся `awaiting_review`, пока человек
явно не принял или не отклонил результат. Connection/Court diagnostics имеют
отдельный `verified_automatically`, не human acceptance. Тестовый результат
обозначен в тексте и структурированных полях SF Chat. Chief-side guards и
отображение интегрирует root; нового chat store или general synthetic bypass
не создаётся.

Подпись сообщения включает точную immutable human-review projection.
Доставка принятия/отклонения использует **существующее событие Evaluation**
этой проверки; task/checkpoint не переписываются. Иначе прежний task inbox ack
скрывал бы новое решение. Для исторического неверно обозначенного synthetic
результата используется отдельное существующее model Evaluation событие.
Произвольные event UUID не создаются: inbox принимает только видимые события.
Без подтверждённого persisted ack доставка не объявляется успешной;
повторная доставка не повторяет модельный вызов и не удаляет старые сообщения.

`deviation_control.inspect_provider` распознаёт только строгую пару actual
model/executor named local-test marker, корректные new/legacy source markers,
нулевую стоимость и отсутствие внешнего/платного вызова. Сохраняются approved
Development/workspace/task reference, task/request/hash и output-limit guards.
Новое действие требует текущий exact-workspace test opt-in. Единственное
изменение caller — receipt-only `ExecutionV2.observe` может завершить запись
уже полученного доказательства после выключения switch; это не новый dispatch.
`before_application` по-прежнему проверяет актуальный opt-in. Проверка реальных
application receipts не смягчена.

## Проверки и ограничения evidence

Все новые тесты работают с disposable auth/SQLite/queue/chat roots, in-memory
test keys и bounded test executor. Fixtures внешнего транспорта проверяют
реальный контракт, но **не являются** реальными credentialed model calls.

- Прежние model + local-test-executor focused tests после producer fix:
  **128 passed, 0 skipped**, 39.37 s.
- Provenance/lifecycle + прежняя worker/SF Chat delivery suite:
  **68 passed, 0 skipped**, 94.23 s. Проверены exact saved-envelope tampering,
  scope, review pending → accept/reject, отдельный persisted event/ack,
  сохранение истории и повтор без второго исполнения.
- Совместный финальный scoped regression — **310 passed, 0 skipped**,
  **353.70 s** после последнего metadata diff. Команда:
  `python -m pytest tests/test_agent_world_models.py tests/test_agent_world_local_test_executor.py tests/test_agent_world_model_provenance.py tests/test_agent_world_model_delivery.py tests/test_agent_world_synthetic_deviation.py tests/test_agent_world_execution_v2.py -q -p no:cacheprovider`.
  Включены новые отрицательные Execution V2 receipt cases, закрытие сохранённого
  receipt после switch OFF и automatic connection chat. Предварительный
  совместный прогон до последнего уточнения metadata также прошёл: 310 tests,
  293.21 s; он не подменяет итоговый повтор.
- `tests/test_agent_world_postgres_runtime_harness.py`: **42 passed, 0 skipped**,
  0.71 s; это pure harness contracts, не новый PostgreSQL runtime pass.
- `py_compile` четырёх затронутых app-модулей, двух новых test-файлов и
  runtime harness — PASS; scoped `git diff --check` — PASS.

Первый новый provenance проход обнаружил ошибку собственного foreign-context
fixture (несовпадение ActorRef и principal) и ещё не интегрированный Chief
source guard. Первый deviation проход имел две конфликтующие fixture env
настройки, корректно отклонённые runtime. Fixtures исправлены, Chief guard
интегрирован root; приведённый финальный повтор включает эти сценарии. Ни
один failure не был скрыт skip/xfail, смягчением auth или сбросом истории.

Предыдущий PostgreSQL runtime PASS относится к своему зафиксированному app
manifest, описанному в `2026-09-08-agent-world-postgres-unified-acceptance.md`.
Этот новый Python diff **не** объявляется повторно PG-runtime/browser accepted.
PG harness ожидание после restart скорректировано: synthetic connection check
подтверждает local executor, а не внешний provider. Новый actual runtime
проход требует отдельной изолированной базы и нового exact-code manifest.

Внешний пользовательский ключ, реальный provider quality test, окончательная
регистрация владельцем и конкретная постоянная SF Social публикация остаются
отдельными владельческими действиями. Этот исполнитель не читает/не копирует
owner credentials и не запускает внешние/платные вызовы или торговые команды.

Git closeout, канонический implementation status и External GPT Context Pack
объединяет root; этот scoped исполнитель не stage/commit/push. Release impact:
будущая локальная интеграция после проверки, не Canary/Production readiness.
