# Resilience, Security and Multi-user Backlog — 2026-07-10

Цель следующей сессии: убрать системные причины, из-за которых второй ПК,
Telegram Mini App, графики, AI-чат и пользовательские данные могут смешиваться,
тормозить или ломаться при 2-10 пользователях.

## Что уже исправлено в этом срезе

- Desktop Telegram login больше не зависит только от `t.me?...start=login_CODE`:
  UI показывает ручную команду `/login CODE`, а бот отвечает на пустой `/start`.
- `accounts.dpapi`, скопированный с другого ПК, больше не ломает вход: чужой
  DPAPI-файл сохраняется как backup и создаётся новый локальный store.
- У пользователя появилась история устройств: machine label, browser/client,
  masked IP и e-mail, введённый на конкретном устройстве.
- `cloudflared.exe` можно хранить внутри проекта:
  `tools/cloudflared/cloudflared.exe`.
- JSONL telemetry tail больше не читает весь файл в память.
- Batch-запросы графиков дедуплицируют одинаковые series внутри одного poll.
- Canvas-график фильтрует явно битые бары и считает индикаторы только по
  видимой области плюс warmup.
- AI Orchestrator HTTP-чаты теперь scoped по `user_id + workspace_id`: один и
  тот же `conversation_id=default` у разных пользователей пишет в разные
  истории, а строки истории содержат `user_id`, `workspace_id`, роль membership.
- Non-owner AI-chat ответы нормализуются, чтобы ассистент не обращался к
  другому пользователю как к Дмитрию Сергеевичу.
- `market_data.read_snapshot_index()` и `read_alerts_index()` используют
  signature cache по `mtime+size`, поэтому одинаковые poll-запросы нескольких
  пользователей не парсят одни и те же JSON snapshots заново.
- Добавлен локальный SQLite WAL durable index (`data/durable/nt_analyzer.sqlite3`)
  для job metadata, chat conversation metadata и telemetry file metadata.
- `jobqueue.create_job()` после атомарной публикации job пишет status/index в
  SQLite, а `jobqueue.sync_durable_index()` восстанавливает индекс из queue dirs.
- Batch/GET графики получили server-side payload cache по workspace/range/source
  signature и opt-in `max_points` LTTB downsampling для слабых ПК.
- Desktop-графики теперь отправляют `max_points` от ширины окна, чтобы canvas не
  получал десятки тысяч баров без необходимости.
- Добавлен recoverable local worker process поверх SQLite WAL: jobs имеют
  `queued/running/succeeded/failed/stale/cancelled`, attempts, timeout, priority,
  cancel flag и owner-only API `/api/worker/jobs`.
- `telemetry_index` worker-job теперь ротирует большие
  `executions.jsonl`, `orders.jsonl`, `errors.jsonl`, оставляет свежий пустой
  canonical-файл для bridge и индексирует текущие file signatures в SQLite.
- Telegram long-poll переведён на единый dispatcher: `account_auth`,
  `telegram_remote` и owner commands обрабатываются одним consumer path, offset,
  retries, poison-drop и audit пишутся в `data/audit/telegram-updates.jsonl`.
- `/api/health` показывает состояние local worker и Telegram update offset/error,
  чтобы на втором ПК было видно, где завис вход/команды.
- Backend-графики изолируют impossible bars до отдачи в UI и возвращают
  diagnostics, чтобы один битый/огромный бар не сжимал весь chart в линию.
- API получил rate limits per `user_id + tunnel_ip + action class`, а owner
  видит active sessions/devices и может revoke одну сессию, одно устройство или
  все сессии пользователя без удаления самого пользователя.

## P0: Identity, Workspaces, Data Isolation

Текущая главная опасность не в UI, а в том, что многие подсистемы всё ещё
исторически ориентированы на один локальный owner backend.

Сделать:

- В каждом API context обязательно иметь `user_id`, `workspace_id`,
  `membership_role`, `capabilities`.
- Любая запись runtime/account/report/portfolio/chat/history должна быть
  scoped по `workspace_id`. Нет `workspace_id` - нет записи.
- AI Orchestrator conversations должны быть ключом
  `workspace_id + user_id + conversation_id`, а не общим `default`.
- Telegram private/group replies должны сохранять автора, user id и workspace;
  агент не должен отвечать второму пользователю как Дмитрию Сергеевичу.
- Owner-training workspace для не-owner всегда read-only, даже если UI ошибся.
- Personal workspace должен читать только свой tenant runtime:
  `data/tenants/<workspace_id>/runtime`.

Acceptance:

- Два разных Telegram user id пишут агенту одинаковый текст и получают ответы
  в разных conversation histories.
- Пользователь A не видит performance/trading/account-history пользователя B.
- Все write endpoints падают с 403/400, если workspace context отсутствует или
  membership не подходит.

## P0: Durable Storage Contract

Рекомендация друзей про "файловая система как БД" верная. Но прямой прыжок в
Postgres/Celery может быть тяжёлым для локального Windows MVP. Нужен этапный
переход.

Сделать первым:

- Ввести SQLite WAL как локальную durable DB для accounts metadata, sessions,
  workspaces, job index, telemetry index и chat history.
- DPAPI оставить только для secrets/PII-at-rest или шифрованных полей.
- JSONL оставить как append-only ingress от bridge, но регулярно compact/index
  в SQLite.
- Job queue: atomic file queue можно оставить для bridge compatibility, но
  добавить SQLite status/index и recovery sweep.
- Все file writes должны быть atomic unique temp + retry, как уже сделано в
  `market_data.py`.

Дальше:

- Для hosted/control-plane режима: Postgres + Redis.
- Для локального слабого ПК: SQLite + worker process часто практичнее Redis.

## P0: Background Workers and Heavy Tasks

Идея "не считать heavy data в request" полностью правильная.

Сделать:

- Backtest, крупный pandas/indicator recompute, AI arbitration и chart
  precompute запускать через отдельный worker process.
- API endpoint только создаёт job, возвращает `job_id`, статус отдаётся отдельно.
- Добавить concurrency limits: максимум N heavy jobs, очередь, cancel, timeout.
- Для Windows local-first использовать `multiprocessing` или `rq`-style worker;
  Celery/Dramatiq оставить как production option, не как обязательный первый шаг.

Текущий статус: vertical slice готов для `durable_sweep` и `telemetry_index`.
Следующий шаг - переводить backtest/LLM/heavy chart precompute на этот contract,
не расширяя HTTP request path.

Acceptance:

- `POST /api/jobs` отвечает быстро и не держит HTTP thread во время backtest.
- При падении worker job остаётся recoverable: `queued/running/stale/failed`.

## P1: Telegram Robustness

Сейчас есть long-poll worker и owner notifier. Следующая цель - исключить
конкурирующие `getUpdates`, потерю offsets и немые команды.

Сделать:

- Один Telegram update consumer на bot token; все handlers подключаются через
  dispatcher.
- Persist offset before/after processing with retry policy.
- Логи для каждого update: update_id, handler, consumed, error.
- `/start`, `/login CODE`, `/access`, Mini App callbacks и owner commands
  должны иметь явные ответы на unknown/expired cases.
- В UI Telegram status показать last update time, last command error и offset.

Текущий статус: единый dispatcher, persisted offset/retry/drop audit и status
поля добавлены. Дальше стоит вынести все Telegram handlers в явный registry и
добавить UI-кнопку диагностики последнего update.

## P1: Charts on Weak PC

Сделать:

- Server-side cache for chart series by `(workspace_id, instrument, timeframe,
  range, source_signature)`.
- Downsampling/LTTB для больших диапазонов; canvas получает не больше нужного
  количества точек под текущую ширину.
- Adaptive polling: если snapshot не обновился, увеличивать interval; если окно
  minimized/offscreen, не poll.
- WebSocket/SSE для live invalidation позже; сначала достаточно etag/signature.
- Anomaly quarantine: backend должен помечать series с impossible bars и писать
  diagnostics вместо передачи мусора в UI.

Текущий статус: cache/downsampling и backend anomaly quarantine добавлены.
Открытым остаётся adaptive polling/minimized tab и live invalidation через
SSE/WebSocket.

Acceptance:

- 10 пользователей / несколько десятков графиков не создают N одинаковых чтений
  snapshot-файла на каждый poll.
- Один нулевой или огромный бар не сжимает график в линию.

## P1: JSONL Telemetry Lifecycle

Сделать:

- Ротация `executions.jsonl`, `orders.jsonl`, `errors.jsonl` по размеру/дате.
- SQLite index по timestamp, account, strategy, instrument.
- Tail-reader без `readlines()`, уже начато; добавить tests на большие файлы.
- Отдельный compactor, который не блокирует API.

Текущий статус: ротация по размеру и signature-index через worker готовы.
Открытым остаётся полноценный SQLite row-index по timestamp/account/strategy/
instrument и scheduled compaction policy.

## P1: LLM and AI Chat Safety

Рекомендация про синхронные LLM-запросы верная.

Сделать:

- LLM calls через worker/queue с timeout, retry, cancellation и circuit breaker.
- Per-user/workspace prompt context; запрет брать "последнего пользователя" из
  глобального состояния.
- Audit: user_id, workspace_id, model/provider, cost estimate, latency, status.
- SSE streaming должен быть tied to one conversation id and user id.

## P1: Security Hardening

Сделать:

- Review всех endpoints на owner-only, self-service, read-only exceptions.
- Rate limits per user + per tunnel IP + per action class.
- Session/device view для owner: active sessions, revoke one device/all devices.
- Secrets inventory: bot token, cloud keys, payment keys, tunnel config.
- Explicit security tests: CSRF, Origin, Telegram initData age/HMAC, path
  traversal, workspace isolation.
- Audit export для account-auth, mini-app, workspace-access, billing,
  bridge-pairing.

Текущий статус: rate limits и session/device revoke готовы. Открытым остаётся
полный endpoint threat review, CSRF/Origin matrix и secrets inventory/export.

## P2: Deployment and Operations

Для текущего локального продукта Docker не обязан быть первым шагом. Но нужен
управляемый запуск.

Сделать:

- Windows service/task wrapper для backend, Telegram worker, AI worker.
- Health page: backend, bridge heartbeat, worker, tunnel, DPAPI, disk space.
- One-click diagnostics bundle без secrets.
- Production profile later: Docker Compose with api, worker, redis, postgres,
  reverse proxy.

## Что не делать первым

- Не переписывать всё на FastAPI только ради async. Async endpoints не решат
  CPU-heavy backtest и pandas.
- Не внедрять Celery/Redis до того, как зафиксированы workspace_id, job schema и
  storage contracts.
- Не переносить live trading controls в Mini App. Нужен отдельный threat model.
- Не смешивать role/subscription/workspace membership в одно поле.

## Suggested Next Session Order

1. Trace all AI chat/orchestrator storage and add `user_id + workspace_id`
   isolation.
2. Add focused tests proving two users cannot share chat/history/performance.
3. Finish endpoint threat review: owner/self/read-only matrix + CSRF/Origin
   tests.
4. Add SQLite row-index for runtime telemetry by timestamp/account/strategy/
   instrument.
5. Move backtest/LLM/heavy chart precompute to worker jobs using the existing
   `worker_jobs` contract.
6. Add owner session/device management UI controls over the backend revoke API.
