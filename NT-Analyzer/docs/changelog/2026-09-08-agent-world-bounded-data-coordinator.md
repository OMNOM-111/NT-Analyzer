# Agent World — новая ограниченная задача Координатора и неторговый root

Статус пользовательской функции: **IN DEVELOPMENT**. Это локальный implementation slice,
не приёмка программы, не Canary/Production release и не визуальное согласование.
Исходный checkout: `codex/agent-world-unified-acceptance`, intake
`1409553a46d0dffa7ef329b28029d93f68b405d7`.
Запись относится к следующему незакоммиченному delta; итоговый SHA/PR фиксирует интегратор.
Первый общий checkpoint после первоначального Coordinator/review slice:
`13573bf76bae2dbad4f9efc4f6893d0bcb4d5406`. Следующее уточнение provenance/events
описано отдельно ниже; оно не объявляется автоматически проверенным старым checkpoint.

## Что изменено и зачем

Закрыт прежний функциональный разрыв: graph мог начинаться только от проверенного
application result. Добавлен отдельный строго проверяемый `verified_model_data` root
для `json_arithmetic` / `extract_facts`. Старый application/NinjaTrader/PNG verifier
не заменяется и не ослабляется этим новым путём.

Также добавлен запуск **новой** работы, а не только handoff готового результата:

1. Пользователь формулирует цель, передаёт 3–20 целых чисел и явно выбирает свои модели.
2. Координатор сохраняет ограниченный серверный план и запускает обычную root model task
   через существующий SF Chat ingress / durable worker.
3. Независимый verifier проверяет числовую сводку. До корректного receipt/evidence
   согласование графа недоступно; никакие дочерние model calls не создаются.
4. Пользователь просматривает точный план и отдельным действием согласует его hash,
   фиксированное время окончания и ceiling существующего automation grant.
5. Существующий delegation worker создаёт дочерние задачи с typed dependencies;
   каждая передаёт проверенные факты и имеет отдельные Contribution / Evaluation / Outcome.
6. Общий результат переходит в `review` / `awaiting_required_reviews`. Владелец
   отдельно проверяет исходный результат и каждый вклад через существующий `task_review`.
   Их ожидания не закрываются автоматически. После этого доступна явная приёмка
   общего результата; отказ или недействительный источник блокирует её.
7. Приёмка aggregate сохраняется отдельным immutable `Evaluation` с тем же rubric
   `human_review`, а сообщение SF Chat переходит в `completed` только после явного
   принятия. Это решение не переписывает технические Task/Outcome и не повышает рейтинг.

План здесь фиксированный и ограниченный; это не произвольный LLM-планировщик.
Root operation — `numeric_summary`. Каждый дочерний operation —
`verify_fact_transfer`, role — `fact_transfer_checker`, `produces_new_analysis=false`.
Повторение фактов не представляется новым исследованием, анализом рынка или профессиональным рейтингом.

## Контракты и безопасность

- Максимум три уровня, fanout 2, семь узлов вместе с root; циклы и повторение
  модели/ancestor Persona запрещены существующим graph validator.
- Нет второй очереди, хранилища jobs, permission system, бюджетной системы или scheduler thread.
- Approval идёт через существующий `automation_authority`, fresh account/device/capability/
  environment/workspace flags и budget/call ceiling. Private paid подключения не получают новый bypass.
- Сохранённые Task → receipt → Contribution → Outcome → Evaluation → Execution ссылки
  сверяются по typed identities и immutable historical revisions; ответ повторно проверяется
  независимым rubric verifier, а не по статусу/проценту из DTO.
- Каждый descendant проверяет исходные доказательства, hash плана, своего родителя,
  identity/persona/account/connection, grant и фактический worker claim.
- Новый Coordinator plan связан с исходной целью и input; повтор с тем же ключом
  не меняет данные/модели и не создаёт второй вызов. Изменение требует новой явной задачи.
- Новый data-root `delegate` требует показанный `approved_plan_sha256` и фиксированный
  `expires_at`; retries не получают новое время grant автоматически.
- Root и дочерние результаты сохраняют executor/actual_model/external_call.
  `local_test_executor`, `provider_receipt` и подтверждённый внешний вызов различимы.
  Наличие provider receipt без `external_call=true` не объявляется live-provider acceptance.
- Named local test receipts маркируют data source, contribution, aggregate и Chat envelope
  как `synthetic=true`; условие строгое: оба executor/actual_model равны доверенному
  серверному test executor, `external_call=false`, известная нулевая стоимость,
  совпавшие task/request/hash и scoped immutable ссылки. Любой произвольный synthetic
  payload не становится допустимым root. Scope берётся из Task/artifact, не из payload.
- Старый неверный `synthetic=false` у доказанного named local executor исправляется
  только в read-проекции; исходные bytes/история не переписываются. Compatibility
  сравнение допускает только этот известный marker, а не изменение фактов или ссылок.
- Новая работа от test source требует действующего exact workspace test opt-in
  дополнительно к обычным flags/grant/device/budget. Отключение тестового исполнителя
  не скрывает прежние receipts; оно запрещает новые шаги, которые могли бы уйти реальному provider.
- Trusted controller/approval plan сохраняет `synthetic=false` как признак настоящего
  server-created workflow, а не Preview; это не характеристика качества входных результатов.
  Результаты и source provenance показываются отдельно и остаются synthetic.
- Тестовый исполнитель по-прежнему включается только точным Development workspace opt-in.
  Ни один защитный/runtime флаг в этой задаче не включался на действующем Local.
- Cancel прекращает будущие шаги и сохраняет прежние receipts, ошибки и проверки.
- Aggregate review использует тот же `review_result` endpoint, CAS текущей ревизии
  graph Task и hash полного immutable source snapshot: план, исходные receipts,
  технический Outcome, отдельные contributions/checks/human reviews, актуальные
  ссылки и состояние authority. Нет второй системы оценок или нового execution grant.
- Отзыв grant/доступа, отключение флага, изменение подключения/источника, cancellation
  делают текущую приёмку недействительной (`stale`); исходное человеческое решение
  остаётся в истории. Reads не создают согласований и не закрывают проверок.

## Точки интеграции

- API domain `automation`: `commission`, `preview_commission`, `approve_commission`;
  standalone data roots: `preview_delegation` → `delegate`.
- Read-проекция содержит `commissions`, `delegations`, отдельные node contributions и aggregate provenance.
  GET не запускает вычисление, согласование или reconcile.
- SF Chat ingress: `coordinator.try_chat`; основной пользовательский мастер вызывает тот же
  API commission, сохраняя понятный текст поручения в существующем чате.
- Worker continuation: `coordinator.after_model` принимает только точный fresh automation
  context, controller/grant которого совпадают с sealed task checkpoint. Recovery использует
  существующую очередь и `delegation.reconcile`, не browser session.
- Aggregate delivery: `coordinator.completion` / `deliver` / `validate_history_envelope`,
  source `bounded_delegation_result`, status `awaiting_review` → `completed` после явной
  приёмки. После уточнения event contract `event_id` — только существующий scoped
  UnitOfWork event технического Outcome или последнего relevant human Evaluation /
  изменённого source record. Выдуманные hash-based event IDs не используются.
  Дедупликация inbox дополнительно разделена по graph ID, потому что одна root review
  может относиться к нескольким графам. Chat `request_id` также включает graph ID,
  чтобы общий root review event не подавлял второй отчёт в той же беседе.
  `acknowledge=false` без уже существующего ack
  даёт явную ошибку доставки, не PASS. Требуется shared Chief/worker
  wiring с claim-fenced delivery; итог после такого wiring проверяется интегратором отдельно.
- Existing `tasks/{graph_id}/review_result` принимает `{decision, comment, source_sha256}`,
  `expected_revision` и `idempotency_key`. Проекция возвращает `human_review`,
  `required_reviews`, `review_state`, доступные actions и прежнее решение отдельно
  от текущего состояния, если доказательства изменились.
- `coordinator.related_completions(authorized, service, reviewed_task_id)` возвращает
  `{deliveries, blocked}` по уже существующим собственным root/child/graph связям;
  не создаёт граф, не согласует его и не запускает/reconcile работу. Shared gateway
  использует этот read-only helper после явного review.
- `operation_role=fact_transfer_checker` обозначает функцию узла. Отдельные
  `agent_role_key=model_response` / `agent_role_ref` показывают фактическую существующую
  системную роль Task/Contribution; новое имя функции не является новой authority.
- Чистое изменение environment-флага или течение времени без нового AW event отражается
  в текущей `stale` проекции; этот slice не выдумывает ради него событие или отдельную
  durable Chat notification. Историческое сообщение/человеческое решение сохраняется.

## Проверки

Все перечисленные здесь проверки выполняются в disposable SQLite/auth/worker/chat roots
без внешних вызовов, owner credentials или реальных market/trading данных.
Результаты локального test executor **не** являются проверкой реального качества моделей.

- Первичный регрессионный baseline после выделения evidence reader:
  `test_agent_world_delegation.py` + `test_agent_world_result_handoff.py` — **55 passed**.
- Новый API → нормальный root worker → явный реальный automation grant → три уровня
  child worker → отдельные contributions/checks → общий `review`, а также hash/idempotency,
  depth/fanout/cycle, auth revocation, запрещённый unclaimed dispatch, immutable-evidence
  rejection и normal Chat ingress: `test_agent_world_coordinator.py` — **11 passed**
  до добавления расширенных lease/budget/restart/cancel/failure кейсов.
- Python compile для четырёх backend модулей — **PASS**.
- Расширенный focused regression: `python -m pytest -q
  tests/test_agent_world_coordinator.py tests/test_agent_world_delegation.py
  tests/test_agent_world_result_handoff.py tests/test_agent_world_mechanism_domains.py -x`
  — **76 passed**, 366.88 с; включает новые настоящие grant call-ceiling / чужая модель,
  fresh-service restart, cancel и отказ независимой проверки root с сохранением истории.
- Дополнительно параметризован guard истёкшего claim; `python -m pytest -q
  tests/test_agent_world_coordinator.py -k 'unclaimed or ceiling'`
  — **3 passed, 13 deselected**, 20.20 с. `deselected` — не отдельное PASS: остальные
  случаи покрыты указанным выше полным focused прогоном. Совокупно проверены 77 случаев
  на одном замороженном backend delta; все provider ответы локального test executor.
- Финальные Python compile четырёх backend модулей и нового тестового файла,
  `git diff --check` для изменённых tracked backend файлов — **PASS**.
- Browser integration, реальный отдельный пользовательский ключ и live-provider
  Coordinator acceptance: **не проверены этим slice**.
- Последующий aggregate-review delta: первый сквозной прогон нового goal и
  existing review route — **2 passed, 21 deselected**, 105.95 с. Подтверждены отдельные
  четыре human reviews → одно aggregate human Evaluation → `completed` Chat envelope,
  изменившийся event_id, CAS/source-hash отказ и immutable идемпотентный повтор.
  Это предварительный focused результат; полный текущий regression фиксируется ниже
  после завершения прогона. Предыдущие 77 случаев относятся к историческому frozen delta.
- Coordinator + прежняя manual-review regression: `python -m pytest -q
  tests/test_agent_world_coordinator.py tests/test_agent_world_manual_review.py -x`
  — **30 passed**, 478.94 с, без skips. Проверены явная отдельная приёмка,
  блокировка при незавершённых/отклонённых индивидуальных проверках, отзыв grant до
  приёмки, сохранение решения со статусом `stale` при revoke/flag OFF/disconnect/cancel.
  Малое последующее усиление final-CAS/fresh-grant и deterministic Evaluation ID
  дополнительно проверено: `test_agent_world_coordinator.py -k existing_review_route -x`
  — **1 passed, 22 deselected**, 61.25 с; Python compile пяти owned backend модулей
  и Coordinator tests — **PASS**. Этот повтор не является новым полным regression.
- Последующее provenance/events уточнение: **5 passed, 26 deselected**, 256.64 с.
  Проверены новый goal и aggregate acceptance с truthful synthetic, выключение
  test opt-in только для новых действий, сохранность старого local false marker,
  read-only related graph scan и подтверждение доставки реальным событием/inbox.
  Штатный test tick пока дополнительно вызывает `after_model`; этот прогон не заменяет
  отдельную проверку shared continuation worker без ручного callback.
- Полный текущий regression handoff/delegation/mechanism после provenance/events delta:
  `python -m pytest -q tests/test_agent_world_delegation.py
  tests/test_agent_world_result_handoff.py tests/test_agent_world_mechanism_domains.py -x`
  — **61 passed**, 270.17 с, без skips. Это новый SQLite-прогон текущего delta;
  предыдущие числа выше оставлены как история контрольных точек, не суммируются с ним.
- Полный текущий Coordinator + manual review: `python -m pytest -q
  tests/test_agent_world_coordinator.py tests/test_agent_world_manual_review.py -x`
  — **40 passed**, 1036.99 с, без skips. Проверены строгий synthetic receipt reader,
  paid/cost/external-call отказ, сохранение исторических markers, реальные inbox events
  и ручная приёмка полного immutable snapshot. Последующий graph-scoped Chat request ID
  проверен отдельным двухграфовым сценарием ниже; этот небольшой final delta
  не включён в приведённый полный прогон 40 случаев.
- Final Chat identity delta: `python -m pytest -q tests/test_agent_world_coordinator.py
  -k 'two_graphs_share or related_completion' -x` — **2 passed, 32 deselected**, 109.50 с.
  Два графа созданы через API → отдельные явные grants → существующие workers;
  одна ручная root review даёт один настоящий event, но два отдельных сообщения SF Chat
  и два graph-scoped inbox acknowledgements. Chief/storage при этой проверке настоящие
  disposable механизмы, не заглушки; executor остаётся локальным тестовым.
  Повторные Python compile owned backend/test файлов и scoped `git diff --check` — **PASS**.
- PostgreSQL/RLS: эти тесты используют SQLite; они **не** засчитываются как новый
  PostgreSQL PASS. PG acceptance идёт отдельным процессом интегратора.

## Release impact / rollback / ограничения

Нет изменения версии, merge, deploy, Live Local 8765, Production DB или secrets.
Рабочие Local-данные и результаты не переносились и не переписывались.
Возврат на сохранённый intake не требует отката owner data: изменения ограничены
кодом и disposable test state. Операционные переключения/backup/rollback действующего
Local остаются отдельной ответственностью интегратора.

Не объявлены закрытыми общий Agent World scope, новый произвольный Router-планировщик,
вся визуальная приёмка, реальный профессиональный рейтинг, внешние model credentials
или полнота многопользовательского продукта. Current implementation status и
External GPT Context Pack должны ссылаться на фактический результат интеграции,
а не считать этот ограниченный сценарий полной реализацией всех видов Координатора.
