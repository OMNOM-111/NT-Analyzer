# StratForge Orchestrator — аудит реестра проблем 1–210

Дата сверки: 18 июля 2026 года (Pacific Time)

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
- Универсальный progress-контракт теперь содержит `items_found`, `items_checked`,
  `items_total`, `items_remaining`, step counters, percent, текущий объект и
  bounded checkpoint. Счётчики монотонны, а активный worker lease нельзя обойти
  анонимным или устаревшим исполнителем.
- Каждое поручение получает детерминированный workflow с зависимостями,
  участниками и обязательными доказательствами. Если в поручении явно названы
  Толик/Управляющий/другой сотрудник, `completed` не принимается без evidence от
  каждого названного участника.
- После backend restart running events возвращаются в очередь; UI различает новый backend instance и не принимает ответ с меньшей revision.
- Resumable task продолжает работу по внешнему ID/checkpoint после restart;
  незавершимая без checkpoint работа честно переходит в `stalled`. Recovery
  показывает число продолженных/остановленных задач и `lost_actions=0`.
- Внешний Python supervisor заменил PowerShell-цикл, который терял exit code. Он
  сохраняет точный код/причину/пути stdout-stderr, ведёт append-only restart
  history, применяет exponential backoff и включает ограниченный safe mode после
  трёх abnormal exits за десять минут.
- Task Scheduler запускает supervisor напрямую, а backend входит в Windows Job
  Object с `KILL_ON_JOB_CLOSE`: административный stop завершает всё дерево и не
  оставляет orphan listener.
- Safe mode сохраняет очередь, но не начинает новые автоматические поручения;
  status и UI показывают причину, срок режима, restart count и последний exit.
- Панель очистки теперь применяет отдельно дубликаты, архив, obsolete и stalled
  группы; полная история сохраняется и физического удаления нет.
- Frontend errors, unhandled rejections и reconnect события сохраняются с correlation ID, route, version и bounded deduplication.
- Незапрошенная проверка LM Studio больше не может подменить strategy task.
- Ручная кнопка ложного `Готово` удалена: владелец может отменить поручение, а завершение подтверждает backend result.
- TopstepX HTTP переведён на stdlib `urllib.request`; чистый GitHub runner больше не зависит от неуказанного `requests`.
- Исправлен отсутствующий импорт `timedelta` в календаре рыночных сессий.
- Browser QA обнаружила и закрыла два owner/API дефекта: Vitek POST больше не
  требует AI workspace для progress/reconcile/telemetry, а локальный владелец без
  заранее созданной account row сохраняет professional mode и все owner
  capabilities. Disabled mass-action теперь визуально отличается от активной.

## Матрица 1–210

| Пункты | Статус после блока | Проверяемый результат / остаток |
|---|---|---|
| 1–7 | Реализовано | Durable decision, reject/revoke, idempotent task/chat, UI busy-state; повторное решение не создаёт копию. |
| 8–13 | Реализовано | Stable event/incident keys, одна активная task на incident, legacy duplicate reconciliation; разные стратегии больше не выглядят одинаково. |
| 14–19 | Реализовано | Strategy/class/instrument/account/state/details/severity/timestamps показываются в карточке. |
| 20–25 | Реализовано | Persisted authorization и scopes; последующая реплика не сбрасывает approval. Live authority отдельно. |
| 26–34 | Реализовано | Универсальный monotonic progress: найдено/проверено/всего/осталось, steps, percent, current item, heartbeat, revision и checkpoint; stale/anonymous worker отклоняется. |
| 35–40 | Реализовано | Один backend-derived canonical status; completed требует result ID. |
| 41–47 | Реализовано | `SESSION_CLOSED`, без watchdog recovery; live check считается skipped/blocked, offline audit разрешён. |
| 48–56 | Реализовано | Решение видно через lifecycle state; доказательства и scope доступны; внутренний код скрыт. Отмена меняет ранее выданное решение. |
| 57–67 | Реализовано | Кнопки блокируются, backend decision идемпотентен, deterministic chat/task; этапы click/queued/running различаются. |
| 68–79 | Реализовано | Reconciler сворачивает дубли без удаления истории; preview и отдельные кнопки применяют только выбранные duplicate/archive/obsolete/stalled группы. |
| 80–89 | Реализовано | Running не включает waiting/blocked; agent activity строится по task/run state, а не по тексту. |
| 90–97 | Реализовано | Notification dedupe существовал; теперь notification содержит incident reference, а terminal уведомление зависит от backend state. |
| 98–104 | Реализовано | Owner-only endpoint, structured authorization, replay recovery и одна lifecycle операция. |
| 105–114 | Реализовано | LM Studio action фильтруется, если инфраструктура не названа в исходной задаче; role/route сохраняются. |
| 115–129 | Реализовано | `waiting_for_input`, blocking reason, exact task reply, strategy selector и «все сохранённые»; stalled/heartbeat escalation через reconciler. |
| 130 | Реализовано | Trace chain сохраняется в incident/task и внешних execution metadata. |
| 131–150 | Реализовано | Persisted route/mission дополнены детерминированным workflow: последовательные steps, зависимости, named participants, evidence requirement и owner-visible состояние. Capability executor может дополнять checkpoint, не меняя общий контракт. |
| 151–160 | Реализовано | Terminal failure освобождает worker/lease, clarification продолжает ту же task, stale continuation перепроверяется. |
| 161–190 | Реализовано | Preview/apply sweeper, duplicate/stalled/orphan/ghost/obsolete/TTL/archive; физическое удаление не используется. Селективные фильтры можно расширять без изменения lifecycle. |
| 191–210 | Реализовано | Instance/revision/requeue/lease/frontend telemetry дополнены внешним supervisor: точный exit code/reason/log paths, restart ledger, backoff, bounded safe mode, checkpoint task recovery и owner-visible recovery outcome. |

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
| Focused Vitek / Chief Agent / market-data / Aurora / supervisor | **230 passed** |
| Полный `python -m pytest -q` | **704 passed** |
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

После прямого поручения владельца выполнена ручная проверка встроенным браузером
на изолированном staging (`127.0.0.1:8877`, отдельный data root, test owner auth,
real payments/live orders/owner Telegram disabled). Проверены owner professional
mode, отсутствие login/UX gate, task progress `12/5/7` и `42%`, workflow
`Виктор → Толик → Управляющий`, preview selective cleanup, disabled action,
формы поручения, три supervisor restart и восстановление checkpoint без дубля.
Именно этот прогон выявил и закрыл lazy-workspace и owner-capability дефекты;
повторная browser-проверка после исправлений прошла. Production/live acceptance
по-прежнему не подменяется staging и headless-тестами.

Рабочая задача `StratForge Vitek` после резервной копии реального state переведена
на прямой supervisor action. Реальные stop/start и hard-kill подтвердили: полное
дерево завершается без orphan, новый listener принадлежит записанному backend PID,
Windows exit `4294967295` сохранён точно и классифицирован как
`signal_or_forced_exit`, restart `34636 → 24020` состоялся, safe mode остался
выключен, 18 задач и 68 инцидентов сохранены.

## Остаточные production blockers

- credentialed/live проверка NinjaTrader/Bridge и provider connectors в разрешённое торговое окно;
- полный mobile/Telegram/two-profile accessibility/role matrix (проверенный в этом
  блоке owner desktop contour больше не является blocker);
- нагрузочная проверка multi-user/Redis/PostgreSQL согласно release plan.
