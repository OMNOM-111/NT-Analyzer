# Agent World — явная передача проверенных фактов другой персоне

Change summary: владелец может передать проверенные факты завершённого результата NinjaTrader/Рабочего стола другой активной Persona через существующий SF Chat и model worker. Дочерняя задача сохраняет настоящую typed зависимость от исходной задачи; перед вызовом модели исходное evidence проверяется повторно.

Status: BETA — ограниченный DEV-путь, не автономная рекурсивная делегация. Исходный checkout `f80d67f730bcd4734893ee7f83643f580138be9a`, ветка `codex/agent-world-owner-preview`, PR #282. Итоговые source SHA и результаты общего Local/Git closeout фиксируются основным исполнителем. Версия `0.10.0-beta.96` не меняется; merge, release, Canary/Production deploy отсутствуют.

## Пользовательский контракт

- Действие «Передать факты агенту» доступно только для завершённой реальной application-задачи с подтверждённым Evaluation, исходным SF Chat и user message. Нужна другая активная Persona с другим активным Model/Provider Account.
- Сервер передаёт только разрешённые скалярные поля: instrument, source kind/id/hash; для бэктеста — strategy и доступные trades/net/PF с явным basis до/после комиссии; для PNG — timeframe и rendered/total bar counts. Не передаются приватные пути, raw files, картинки, prompts, Memory, judge reasoning или credentials.
- Существующая независимая `extract_facts` rubric измеряет **точность передачи фактов**, а не анализ изображения, проверку стратегии или прибыльности. Ограничение явно записано в acknowledgment, DTO и окончательном сообщении SF Chat. Арифметический и application-conformance рейтинги не объединяются с этой проверкой.
- В том же диалоге создаётся новое явное пользовательское поручение и acknowledgment с источником/получателем. Исходные сообщения и artifacts не меняются. Результат дочерней задачи доставляется через существующий single-delivery/inbox путь; новая очередь или отдельный messenger не создаются.

## Архитектура и границы

- `result_handoff.start(authorized, service, task_id, target_model_id, idempotency_key)` — узкий server-side adapter. Существующая строгая проверка source PNG/report и sanitized scalar metrics переиспользована read-only; SF Social publication не вызывается и автоматически не разрешается.
- В `start_task` перед первым enqueue передаётся внутренний immutable `SealedHandoff`, не поле HTTP payload. `Task.dependencies` содержит точный parent EntityRef/revision; Intent/Task/Decision/Execution и последующие evidence сохраняют parent correlation. Request digest включает source snapshot, target и facts.
- Перед передачей провайдеру повторно проверяются fresh admission/session/capabilities, source task/revision, привязки Model/Outcome/Evaluation, hashes и доступность artifacts. Trusted `chat_scope` передаётся только из server composition в ModelService, не из task payload: исходное и новое user messages должны по-прежнему существовать в том же собственном SF Chat. Удаление сообщения после enqueue блокирует платный вызов. Существующие account/workspace budget gates и единственный provider attempt сохраняются.
- Изменившийся/недоступный source, чужой scope, одинаковая Persona, неактивный target, подделанный/неполный packet или dependency не запускают provider. Ошибки остаются явными в task history без synthetic PASS. Исходные finalized records остаются immutable; никакие массовые миграции/перезаписи не выполняются.
- Дочерняя задача не может делегировать результат дальше. Здесь нет новых tools, Court auto-execution, Router/Execution V2, торговых команд, собственной системы permissions/budgets/jobs или автономного scheduler.

## Проверки и release impact

Focused handoff checkpoint: **27 passed**, 83.05s. Общий scoped regression с двумя дополнительными UI-action проверками: **270 passed**, 460.99s (`test_agent_world_result_handoff`, `test_agent_world_application_evaluation`, `test_agent_world_models`, `test_agent_world_application_chat`, `test_agent_world_model_delivery`, `test_agent_world_social_publication`). После финального trusted-chat guard все **34 handoff-сценария passed**, 163.57s, включая удаление original/child message после enqueue и отсутствие/несоответствие trusted scope. Во всех перечисленных прогонах пропусков нет.

`py_compile` runtime-модулей и новых focused тестов — PASS; `git diff --check` — PASS. Тесты используют только disposable fixtures/PNG/report/SQLite/SF Chat и mock transport — это не live acceptance. Общий exact-final-code full regression выполняется основным исполнителем отдельно; предыдущие 270 checks не выдаются за повторный прогон последней chat-guard delta.

Изменены `model_service.py`, добавлены `result_handoff.py` и focused тесты. Root-интеграция добавляет строгое действие `tasks/<id>/handoff` / `model_tasks/<id>/handoff` с payload только `target_model_id` и существующим idempotency key. Документы текущего состояния, UI, общий regression, bundle/context/static checks и actual Local verification обновляет основной исполнитель в том же end-to-end поручении.

Rollback — предыдущий проверенный код без восстановления/удаления runtime-данных. Typed dependencies и checkpoints используют существующую schema; миграция БД не нужна. Новые model calls, публикации SF Social и другие внешние эффекты в ходе этой изолированной разработки не выполнялись.
