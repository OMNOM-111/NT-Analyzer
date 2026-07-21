# StratForge Connector Protocol v1

Статус: реализован локально; Production acceptance требует реального Windows VM
и опубликованного server endpoint.

## Граница доверия

Production Connector работает только исходящими HTTPS-запросами к canonical
origin. Он не открывает входящий порт, не передаёт broker credentials и не
считает `installation_id`, `connection_id`, workspace из JSON или IP-адрес
доказательством личности. Localhost queue/IPC остаётся отдельным транспортом
`local_development`.

Идентичность устройства — ECDSA P-256 key pair. Private key и локальное state
хранятся под Windows DPAPI CurrentUser. Сервер хранит только public JWK,
fingerprint и SHA-256 hash короткоживущего session token.

## Enrollment и сессия

1. Авторизованный пользователь с write-доступом к workspace вызывает
   `POST /api/bridge/pair/start` и получает 80-bit одноразовый code с TTL 10
   минут. В хранилище остаётся только hash code.
2. Connector генерирует device key и вызывает `POST /api/connector/v1/enroll`.
   Code потребляется один раз, installation создаётся в `pending`.
3. Первый server nonce возвращается вместе с enrollment. Для последующих nonce
   Connector вызывает `POST /api/connector/v1/challenge` с отдельным client
   nonce, UTC timestamp и подписью device key. Повтор и stale request
   отклоняются.
4. Connector подписывает canonical hello и отправляет его в
   `POST /api/connector/v1/hello`. Только после проверки key fingerprint,
   workspace binding, одноразового nonce и signature состояние становится
   `online`.
5. Сервер выдаёт opaque session token на 15 минут. Heartbeat/poll/result требуют
   bearer token и монотонный `connector_sequence`. Reconnect создаёт новую
   подписанную сессию и supersede предыдущую.

Canonical JSON использует UTF-8, ASCII escaping, сортировку ключей и compact
separators. Тест `tools/connector_interop_probe.py` доказывает одинаковый byte
stream и проверку C# signatures на Python.

## Состояния

| Состояние | Условие | Команды |
|---|---|---|
| `pending` | code принят, signed hello ещё нет | запрещены |
| `online` | активная session и heartbeat не старше 45 секунд | только выданные capabilities |
| `offline` | heartbeat/session истекли | новые команды могут ждать только до TTL |
| `revoked` | пользователь отозвал installation | session и queued commands отменяются |

Revoke проверяется при каждой session operation. Просроченная команда никогда
не выдаётся Connector и не может принять result. Live capability закрыта
release gate; default — telemetry/accounts read, paper добавляется только явно.

## HTTP endpoints

| Endpoint | Credential | Назначение |
|---|---|---|
| `/api/connector/v1/enroll` | одноразовый code + public key | pending installation |
| `/api/connector/v1/challenge` | device signature | новый one-time server nonce |
| `/api/connector/v1/hello` | device signature + nonce | short-lived session |
| `/api/connector/v1/heartbeat` | bearer + sequence | last-seen и masked account labels |
| `/api/connector/v1/commands/poll` | bearer + sequence | bounded HTTPS long-poll |
| `/api/connector/v1/commands/result` | bearer + sequence | idempotent ack/result |

Browser routes `/api/bridge/setup`, `/api/bridge/connections`, pairing, revoke,
queue и command status дополнительно требуют обычную user/workspace policy,
CSRF и NinjaTrader dual-auth для write operations.

Строгий machine-readable контракт находится в
`docs/schemas/connector-protocol-v1.schema.json`. Unknown top-level message
fields отклоняются; расширения допускаются только внутри versioned
`extensions` object.

## Command safety

Command envelope связан с workspace, installation и connection. Idempotency key
уникален в workspace; повтор с другим body даёт conflict. Delivery lease
разрешает безопасную повторную доставку после сетевого обрыва. Connector заново
проверяет workspace, connection, capability, expiry и update state перед
локальной постановкой. Production v1 исполняет только безопасные telemetry,
account snapshot и paper commands; произвольный C# и секретные поля запрещены.

## Хранилище и rollback

Windows Development/bootstrap repository — atomic DPAPI file. Это не
Production source of truth: Stage 6 переводит тот же repository contract в
PostgreSQL. Откат Stage 3 — выключить Production connector commands и сохранить
`local_development`; private key/config не удаляются, installation можно
отозвать. Ни rollback, ни repair не должны включать live commands.
