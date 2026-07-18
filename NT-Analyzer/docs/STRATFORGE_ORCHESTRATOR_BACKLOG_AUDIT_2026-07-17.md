# StratForge Orchestrator — аудит реестра проблем 1–210

Дата сверки: 17 июля 2026 года (Pacific Time)

Источник: `STRATFORGE_ORCHESTRATOR_BACKLOG_ISSUES_1-210_CODEX.md`, переданный владельцем.

Область: Виктор/Витёк, Управляющий, Толик, incident decisions, task guard, jobs, уведомления, очистка и restart recovery.

## Итог

210 пунктов описывают не 210 независимых дефектов, а повторяющиеся симптомы восьми системных причин:

1. решение владельца не являлось durable authorization;
2. создание чата, поручения и запуска не было идемпотентным lifecycle;
3. UI смешивал queued, running, waiting и blocked;
4. модель могла объявить запуск до ответа backend guard;
5. runtime-события закрытой сессии не имели общего `SESSION_CLOSED` guard;
6. отсутствовал управляемый preview/apply reconciler;
7. task/event recovery не имел полной lease/correlation модели;
8. карточки скрывали объект, доказательства и техническую трассировку.

Проблемы подтверждены реальными данными до очистки: 68 инцидентов, 26 owner-decision карточек и 7 lifecycle-active задач. Пять задач содержали одновременно обещание запуска и `current_message_does_not_authorize_action`; одна не была активирована, одна не получила проверяемый план.

## Что исправлено в текущем блоке

- Один `incident_id` теперь имеет устойчивые `decision_id`, `mission_id`, `chat_thread_id`, `task_id`, `assigned_agent`, внешние job/command IDs и `result_id`.
- `authorization_status`, `authorized_by`, `authorized_at_utc` и `authorization_scope` сохраняются в incident и task. Повторная доставка решения возвращает существующую работу.
- Кнопка согласия вызывает одну backend lifecycle-операцию. Чат имеет детерминированный ID; retry восстанавливает недостающую task без нового решения.
- Первичное согласие разрешает только `audit`. `safe_fix`, `restart` и `live_enable` не наследуются автоматически.
- Internal task guard учитывает сохранённое разрешение нужного scope, а не только последнюю реплику.
- При guard failure модельный черновик о якобы начатой работе отбрасывается. Пользователь не видит внутренний код как результат.
- Внешний статус канонизирован: `queued`, `running`, `waiting_for_input`, `blocked`, `completed`, `failed`, `cancelled`, `obsolete`, `duplicate`, `archived`.
- `completed` требует проверяемого результата и получает `result_id`.
- Счётчики running/queued, waiting и blocked разделены. Blocked больше не изображается работающим агентом.
- Карточка показывает стратегию, инструмент, счёт, наблюдаемое состояние, severity, время, число повторов, incident ID и исходные доказательства.
- `SESSION_CLOSED` блокирует `strategy_stopped`, `strategy_disappeared` и `connection_lost` recovery; офлайн-аудит остаётся доступен.
- Добавлен preview/apply lifecycle reconciler: duplicate/orphan/ghost/stalled, legacy guard failures, missing result IDs, unactivated/stale queue, incident TTL и архивирование терминальных задач.
- Очистка не удаляет историю. UI показывает preview и только затем разрешает применить безопасные изменения.
- Waiting task предлагает выбрать сохранённую стратегию, CELL/класс/инструмент/последний experiment либо режим «проверить все сохранённые стратегии».
- Event и task получают lease owner/expiry, heartbeat, stage и progress. Старый lease не может завершить задачу после смены владельца.
- После backend restart running events возвращаются в очередь; UI различает новый backend instance и не принимает ответ с меньшей revision.
- Frontend errors, unhandled rejections и reconnect события сохраняются с correlation ID, route, version и bounded deduplication.
- Незапрошенная проверка LM Studio больше не может подменить strategy task.
- Ручная кнопка ложного `Готово` удалена: владелец может отменить поручение, а завершение подтверждает backend result.
- TopstepX HTTP переведён на stdlib `urllib.request`; чистый GitHub runner больше не зависит от неуказанного `requests`.
- Исправлен отсутствующий импорт `timedelta` в календаре рыночных сессий.

## Матрица 1–210

| Пункты | Статус после блока | Проверяемый результат / остаток |
|---|---|---|
| 1–7 | Реализовано | Durable decision, reject/revoke, idempotent task/chat, UI busy-state; повторное решение не создаёт копию. |
| 8–13 | Реализовано | Stable event/incident keys, одна активная task на incident, legacy duplicate reconciliation; разные стратегии больше не выглядят одинаково. |
| 14–19 | Реализовано | Strategy/class/instrument/account/state/details/severity/timestamps показываются в карточке. |
| 20–25 | Реализовано | Persisted authorization и scopes; последующая реплика не сбрасывает approval. Live authority отдельно. |
| 26–34 | Реализовано частично | Backend IDs, start time, heartbeat, stage и progress есть. Детальные счётчики «найдено/проверено» зависят от конкретного executor и ещё не универсальны. |
| 35–40 | Реализовано | Один backend-derived canonical status; completed требует result ID. |
| 41–47 | Реализовано | `SESSION_CLOSED`, без watchdog recovery; live check считается skipped/blocked, offline audit разрешён. |
| 48–56 | Реализовано | Решение видно через lifecycle state; доказательства и scope доступны; внутренний код скрыт. Отмена меняет ранее выданное решение. |
| 57–67 | Реализовано | Кнопки блокируются, backend decision идемпотентен, deterministic chat/task; этапы click/queued/running различаются. |
| 68–79 | Реализовано | Reconciler сворачивает дубли без удаления истории; панель выполняет preview и массовую безопасную очистку. |
| 80–89 | Реализовано | Running не включает waiting/blocked; agent activity строится по task/run state, а не по тексту. |
| 90–97 | Реализовано | Notification dedupe существовал; теперь notification содержит incident reference, а terminal уведомление зависит от backend state. |
| 98–104 | Реализовано | Owner-only endpoint, structured authorization, replay recovery и одна lifecycle операция. |
| 105–114 | Реализовано | LM Studio action фильтруется, если инфраструктура не названа в исходной задаче; role/route сохраняются. |
| 115–129 | Реализовано | `waiting_for_input`, blocking reason, exact task reply, strategy selector и «все сохранённые»; stalled/heartbeat escalation через reconciler. |
| 130 | Реализовано | Trace chain сохраняется в incident/task и внешних execution metadata. |
| 131–150 | Реализовано частично | Persisted deterministic route/mission есть; произвольные LLM-планы всё ещё требуют дальнейшего расширения capability-specific progress adapters. |
| 151–160 | Реализовано | Terminal failure освобождает worker/lease, clarification продолжает ту же task, stale continuation перепроверяется. |
| 161–190 | Реализовано | Preview/apply sweeper, duplicate/stalled/orphan/ghost/obsolete/TTL/archive; физическое удаление не используется. Селективные фильтры можно расширять без изменения lifecycle. |
| 191–210 | Реализовано частично | Instance/revision/requeue/lease/frontend telemetry есть. Причина жёсткого OS process crash и exit code недоступны без внешнего Windows service supervisor; это production integration blocker, а не скрытый PASS. |

## Retention и очистка

- Incident owner-decision TTL: 7 дней, затем `obsolete` после повторной проверки.
- Terminal task archive: 30 дней; запись остаётся в durable audit trail.
- State limits: до 1000 tasks/incidents/events, 1000 event history, 500 lifecycle history, 200 deduplicated frontend telemetry records.
- Массовая операция сначала возвращает preview с точными IDs и counts.
- Strategy parameters и live authority reconciliation не изменяет.

## Приёмочные доказательства

Фактический прогон после реализации и очистки:

| Проверка | Результат |
|---|---|
| Focused Vitek / Chief Agent / market-data / Aurora | **217 passed** |
| Полный `python -m pytest -q` | **690 passed** |
| Проектный `python -m tests` | **13/13 suites passed** |
| Python `py_compile` изменённых модулей | **PASS** |
| JavaScript `node --check` изменённых assets | **PASS** |
| `git diff --check` | **PASS** |

Реальная очистка выполнена после preview и точной резервной копии
`data/operations/vitek.json.bak-lifecycle-20260717-224756` (SHA-256
`3BE020902FEB775830C5DFE28C6BC24E13C038B30C87E9099D3F045BDD84CD03`).
Применено 40 действий: 10 `result_id`, 5 legacy guard failures, 1 неактивированная
task, 1 executor-plan failure и 23 `SESSION_CLOSED` deferrals. Повторный preview:
**0 действий**. Все 18 задач и 68 инцидентов сохранены; итоговые task-статусы:
10 completed, 6 failed, 1 cancelled, 1 obsolete.

Обязательные автоматические сценарии добавлены для:

- повторного approval и сохранённого authorization scope;
- `SESSION_CLOSED` без runtime incident/recovery;
- preview/apply reconciliation с сохранением истории;
- запрета completed без result и выдачи result ID;
- frontend telemetry deduplication;
- выбора сохранённой стратегии и продолжения той же task;
- сохранённой task authorization после изменения текста реплики;
- запрета подмены strategy task восстановлением LM Studio;
- event recovery и lease ownership;
- существующих Vitek/Chief Agent/Aurora/market-data контрактов.

Ручная визуальная проверка не выполнялась: правила workspace запрещают автоматически открывать встроенный браузер без прямого поручения пользователя. Production/live acceptance также не подменяется headless-тестами.

## Остаточные production blockers

- внешний Windows service supervisor для точного backend exit code/crash reason;
- credentialed/live проверка NinjaTrader/Bridge и provider connectors в разрешённое торговое окно;
- ручная визуальная проверка карточек, drawers, reload/reconnect и accessibility;
- нагрузочная проверка multi-user/Redis/PostgreSQL согласно release plan.
