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
3. Introduce SQLite WAL index for telemetry/job/chat metadata.
4. Move one heavy path to worker process as a vertical slice.
5. Add chart cache/downsampling signatures.
6. Add owner session/device management UI.
