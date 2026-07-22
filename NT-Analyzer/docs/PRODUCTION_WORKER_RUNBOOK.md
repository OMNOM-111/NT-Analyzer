# StratForge Production worker runbook

Production API и Production workers — разные процессы. API принимает и
проверяет запрос, атомарно записывает job в PostgreSQL и не запускает локальный
SQLite worker. `stratforge-worker.service` забирает jobs через `SKIP LOCKED`,
обновляет lease/heartbeat и фиксирует результат в той же authoritative базе.
Development по-прежнему использует локальный worker и не требует PostgreSQL.

## Неизменяемые правила

- `STRATFORGE_ENV=production` и отдельные data/database/queue identities.
- API unit имеет `STRATFORGE_DEPLOYMENT_ROLE=api`, worker unit переопределяет
  роль на `worker`.
- Схема применяется административной migration-role до запуска новой версии.
- API и worker используют только runtime role `stratforge_app`; migration/backup
  DSN в service environment не хранится.
- Payload, provider prompt, result, user/workspace id и DSN не выводятся в
  метрики или обычный journal.
- Опасная команда имеет idempotency key, `dangerous=true` и максимум одну
  попытку. Неопределённый downstream-result уходит в dead-letter/review, а не
  повторяется автоматически.
- Потеря PostgreSQL не включает fallback на SQLite/in-memory queue.

## Классы и стартовые лимиты

| Класс | Global concurrency | Payload | Timeout | Per-workspace queued/running |
|---|---:|---:|---:|---:|
| `interactive_ai` | 4 | 64 KiB | 900 s | 100 / 2 |
| `chart` | 4 | 512 KiB | 180 s | 80 / 2 |
| `telemetry` | 2 | 128 KiB | 300 s | 200 / 2 |
| `maintenance` | 1 | 64 KiB | 300 s | 40 / 1 |

DB-конфигурация является верхней границей. Переменные
`STRATFORGE_WORKER_CONCURRENCY_<CLASS>` могут только уменьшить фактическое
число потоков конкретного процесса. Увеличение лимита требует нового load
report и контролируемого изменения DB config; добавлять процессы вслепую
запрещено.

Очередь выбирает workspace round-robin по `last_claimed_at`, затем priority и
created time. Одновременные claim используют row locks/`SKIP LOCKED`. Quota
проверяется и при enqueue, и при claim, поэтому один tenant не может занять весь
класс.

## Установка и запуск

1. Создать combined backup и проверить его manifest.
2. Проверить migration plan и применить только по подтверждённому
   `migration_set_sha256` согласно `PRODUCTION_STORAGE_RUNBOOK.md`.
3. Установить `stratforge.service`, `stratforge-worker.service` и
   `cloudflared.service` в `~/.config/systemd/user/`.
4. Выполнить preflight из нового immutable release.
5. Запустить worker и API без внешнего traffic, проверить local readiness.
6. Только затем запустить Cloudflare Tunnel.

~~~bash
systemctl --user daemon-reload
systemctl --user enable --now stratforge-worker.service stratforge.service
systemctl --user status stratforge-worker.service stratforge.service --no-pager
systemctl --user enable --now cloudflared.service
~~~

Нормальный worker journal содержит только число потоков/классы и итог
graceful stop. Любой DSN, payload или provider response в journal — security
incident.

## Метрики и сигналы

Readiness проверяет наличие всех четырёх class configs, доступность базы и
отсутствие просроченного lease. Aggregate worker metrics содержат:

- queued/running/completed/dead-letter count по классу;
- queue age p50/p95/p99/max;
- attempts p50/p95/p99;
- active/expired leases;
- payload bytes p50/p95/p99/max/total;
- fairness min/max/total без tenant identifiers.

Начальные локальные SLO из `STAGE7_LOAD_REPORT_2026-07-21.md`:

- 100-workspace chart profile: все 200 jobs завершены, fairness exact;
- p95 end-to-end не больше 30 s;
- expired leases после drain: 0;
- post-crash recovery меньше 2 s;
- duplicate dangerous rows: 0.

Это стартовый safety/SLO contract, не сертификат мощности конкретного Linux
host. После deploy обязательны те же probes на production-like clone без
реальных команд и без пользовательских payload.

## Retry, cancel и lease

- Обычная ошибка получает exponential backoff до `max_attempts`, затем
  `dead_letter`.
- Provider outage классифицируется отдельно; очередь остаётся durable.
- `cancel_requested` проверяется перед commit результата. Late finish не может
  заменить terminal `cancelled`.
- Worker обновляет heartbeat/lease каждые 5 секунд во время выполнения.
- Истёкший lease sweep возвращает обычную безопасную job в очередь с новой
  lease token; старый worker больше не может завершить её.
- Dangerous job после ошибки не requeue независимо от переданного
  `max_attempts`.

## Graceful restart

~~~bash
systemctl --user stop cloudflared.service
systemctl --user restart stratforge.service
systemctl --user restart stratforge-worker.service
systemctl --user start cloudflared.service
~~~

SIGTERM сначала прекращает новые claim, затем ждёт in-flight threads до
`STRATFORGE_WORKER_SHUTDOWN_GRACE_SEC`/unit timeout. Если stop вернул
`graceful=false`, traffic не возвращается: проверить running leases, дождаться
expiry/sweep и только потом запускать replacement.

## Отказы

- PostgreSQL unavailable: API enqueue/rate-limit и worker fail closed; не
  переключать на Development storage.
- Provider unavailable: безопасные jobs retry/backoff; проверить queue age и
  circuit/provider status. Dangerous jobs вручную расследуются.
- Worker crash: дождаться lease expiry, выполнить/дождаться stale sweep,
  проверить новую lease token и отсутствие duplicate side effect.
- Slow/offline Connector: command TTL истекает; stale command не доставляется.
  Replay того же idempotency key возвращает исходную expired command.
- Saturated API: клиент получает JSON `503`, code
  `api_admission_saturated`, `Retry-After: 1`; transport reset недопустим.

## Rollback

1. Остановить Cloudflare traffic.
2. Остановить API и worker; queued state и jobs не удалять.
3. Если старый release совместим с текущей schema, переключить symlink на
   проверенный `previous` и запустить worker/API локально.
4. Если schema несовместима, восстановить pre-migration backup в отдельную
   database/artifact target. In-place downgrade и правка migration ledger
   запрещены.
5. Для оперативного снижения риска уменьшить class concurrency или отключить
   тяжёлый класс в DB config; не очищать очередь.
6. Вернуть tunnel только после readiness, queue metrics и canary idempotency
   smoke.
