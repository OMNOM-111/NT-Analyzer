# Agent World — точное применение показанного Router-предпросмотра

Статус пользовательской функции: **IN DEVELOPMENT**. AI-assisted change.
Ветка `codex/agent-world-unified-acceptance`, сохранённый исходный checkpoint
`13573bf76bae2dbad4f9efc4f6893d0bcb4d5406` после intake
`1409553a46d0dffa7ef329b28029d93f68b405d7`. Эта запись описывает следующий
scoped WIP; итоговые commit/PR и общий implementation status фиксирует интегратор.
Это не Canary/Production release, не приёмка дизайна и не закрытие всей программы.

## Что изменено и зачем

Прежний `router/apply` заново вычислял выбор и не связывал показанный preview
с реально созданной Task. При изменении модели/наблюдений мог примениться другой
выбор; последующий read продолжал показывать `decided_by=request`.

Теперь владелец сначала получает shadow comparison, затем отдельным действием
применяет **тот же** immutable scoped preview. Сервер проверяет исходную Task/
ревизию/checkpoint/request hash, candidate identities и revisions, evidence,
стоимость/latency constraints, текущие права и environment/workspace gates.
Любое изменение выбора или его основания требует нового предпросмотра.
Текущий named-test/configured-provider режим также входит в candidate snapshot:
его изменение после preview или постановки в очередь блокирует новый вызов.

Apply создаёт **новую** Task выбранной модели через существующий ModelService
и durable worker. Исходная задача/ошибки/результаты не перемещаются и не стираются.
Server-issued routing packet входит в request identity до enqueue, approved
Execution V2 scope и receipt linkage. Нет другой очереди, permission system,
budget store, права на секреты или обхода Device Confirmation.
Перед provider transmit повторно проверяются текущая eligibility и тот же
selection fingerprint, в дополнение к существующим admission/deviation guards.

Повтор одного Apply с тем же idempotency key возвращает ту же Task и не повторяет
готовый/начатый model call. Другой preview с тем же ключом отклоняется.
Полный допустимый 120-символьный caller key хешируется перед внутренним ключом.
Старый apply без issued preview намеренно запрещён; read/preview и standalone
read-only `router_v2.select` сохраняются. Глобальный legacy Router не переключён.

## Пользовательский контракт

1. Выбрать существующую bounded model task → Router → «Предпросмотр».
   Ответ содержит текущую модель, выбранного кандидата, причины исключения,
   класс и сохранённые отдельные измерения. Сохраняется только scoped artifact;
   preview не создаёт Task, grant, job и не вызывает provider.
2. Нажать явное Apply для показанного preview. Ответ сообщает ID **новой** задачи,
   `routing_applied=true`, но `execution_observed=false`, пока ответа ещё нет.
3. После worker результат содержит actual model/executor/external-call и его
   provenance из receipt. Автоматическая rubric verification не закрывает
   отдельную ручную проверку результата. После изменения источника/подключения/
   прав/измерений безопасный маршрут — получить новый preview; прежняя история
   остаётся доступной, в том числе после отключения Router active flag.

API в существующем `/api/ai-control-center/domains`:

- `POST /router/{source_task_id}/preview`:
  `{idempotency_key, payload:{candidate_model_ids?, max_cost_usd?:0, max_latency_ms?:60000}}`.
  Возвращает `preview_ref` (artifact ID + SHA + exact scope), `source_revision`,
  `source_request_sha256`, `selection_sha256`, `requires_explicit_apply=true`,
  `creates_new_task=true`; action `apply` только при eligible choice и active gate.
- `POST /router/{source_task_id}/apply`:
  `{expected_revision:preview.source_revision, idempotency_key, payload:{preview_ref}}`.
  Нельзя подставить другой выбранный model ID или constraints. UI сохраняет один
  Apply key для повторения того же запроса, а не создаёт его заново после timeout.
- `GET /router/{started_task_id}`: `actual_choice.decided_by=router_v2`, source
  revision, preview/decision refs, selection hash, `routing_applied`,
  `execution_observed` и фактический executor из receipt. `applied=true` в ответе
  Apply не равно `succeeded`. Hash первоначального решения отдельно назван
  `preview_decision_sha256`; UI не должен хешировать обогащённый HTTP DTO.

## Происхождение измерений и границы

Router остаётся ограниченной explainable политикой cost → measured latency →
stable ID. Поддерживаются только существующие классы `json_arithmetic`,
`extract_facts`, `backtest_spec`, `chart_spec`; application-role restrictions
сохранены. Нужно минимум три **различных входа того же класса** в пределах
30 дней, все с независимым сохранённым proof; retry не увеличивает выборку.
Ни эта выборка, ни бэктест/PNG не являются профессиональной оценкой модели.
`quality_score=null`, `quality_ranking=false`. Pricing неизвестного/платного
подключения не угадывается: существующий server quote допускает только
разрешённый бесплатный bounded execution, иначе кандидат исключён.

Current и исторические неверно помеченные named local-test observations не
попадают в real routing eligibility: reader повторно проверяет receipt/evidence
и получает synthetic из immutable executor identity. Bytes истории не меняются.
Тестовая connection check не заменяет настоящее `connected` подключение.
`execution_origin`/`execution_synthetic` показывают планируемый режим; фактический
режим после запуска берётся только из receipt.

Routed non-trading результат поддержан прежним строгим `verified_model_data`
reader: routing packet добавлен в canonical request hash и отдельно проверен.
Application/NinjaTrader/PNG seal и торговые условия не изменены.

## Проверки

Новые acceptance тесты используют обычного disposable пользователя: реальный
account_auth/permissions, session, permanent device, personal workspace, SQLite,
ModelService, Worker и Execution V2. Только начальная регистрация/устройство —
fixture state; наблюдения, previews, tasks и receipts создаются через сервисы.
Транспорт — явно обозначенный локальный provider-contract double; sockets
запрещены. Это проверка контрактов, **не live-provider evidence** и не качество
реальной модели. Named local executor отдельно проверен как synthetic.

- Предварительный positive queue + реальный revoke ordinary-user capability:
  **2 passed, 18 deselected**, 38.90 s.
- Финальный Router acceptance + прежние Router/mechanism regression:
  `python -m pytest -q tests/test_agent_world_router_acceptance.py
  tests/test_agent_world_router_v2.py tests/test_agent_world_mechanism_domains.py -x`
  — **50 passed, 0 skipped**, 490.61 s. Из них 22 новых acceptance cases на
  обычном пользователе: exact apply → selected executor → normal queue →
  Execution V2 succeeded/0 deviations → pending human review; отказ при
  source/revision/hash/scope/identity/quote/evidence/capability/origin change;
  выключение флага/смена origin до provider transmit; terminal idempotent retry;
  исключение current/legacy named-test наблюдений из реальной выборки.
- Последующее расширение positive test только assertion строгого
  `verified_model_data` reader на таком routed result:
  `python -m pytest -q tests/test_agent_world_router_acceptance.py
  -k explicit_same_preview -x` — **1 passed, 21 deselected**, 20.49 s.
  Это тот же frozen app delta; `deselected` не обозначает дополнительные PASS.
- Финальные Python compile шести затронутых backend файлов и Router acceptance
  tests, scoped `git diff --check` tracked diff — **PASS**. Общий pytest/static/
  context и immutable-artifact gates программы остаются у интегратора.

Первый предварительный bundle остановился на попытке fixture снять
`ai_pro_models` с owner: account_auth корректно запрещает такую операцию.
Fixture переведён на обычного пользователя с настоящими отдельными grants;
guard не ослаблен. Ранее positive actual queue обнаружил отсутствующий `routing`
в request/approved identity Execution V2; добавлены только три точных поля/pins,
без пропуска scope/deviation проверки. Ни failure, ни история не скрыты skip/xfail.

Новые PostgreSQL/RLS, браузерная визуальная проверка, настоящее внешнее
подключение и весь regression программы не заявляются результатом этого
SQLite slice: они фиксируются интегратором отдельно с exact code identity.

## Release impact / rollback

Номер версии не менялся. Защитные flags по умолчанию выключены; флаги Local,
Canary и Production не включались. Local 8765, существующие owner данные,
credentials, аватары и Persona-настройки не читались/не переносились этим slice.
Нет merge, deploy, миграции рабочих хранилищ или нового paid/provider call.
Rollback относится к коду после сохранённого checkpoint, а не к удалению данных.
Current implementation status и External GPT Context Pack обновляет интегратор
в том же общем checkpoint; эта запись не создаёт второй roadmap/source of truth.
