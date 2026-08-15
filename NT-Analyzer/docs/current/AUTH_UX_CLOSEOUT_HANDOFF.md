# Auth / user-contour closeout — handoff

Дата: `2026-08-15` UTC. Базовый релиз на всех окружениях: `ca06cb9f`.

Этот документ существует, чтобы следующая сессия **начала с незакрытого пункта
и не проводила повторную диагностику**. Всё в разделе «Зафиксировано» —
проверено на живых окружениях; переизобретать не нужно.

---

## Зафиксировано (не переисследовать)

| Факт | Значение |
| --- | --- |
| Canonical owner UUID | `eb9d8e32-8db0-d590-9b35-ef1bd07ec61f` |
| Owner Telegram identity | ID `1647145559`, `dimon_check` — PASS |
| Owner Google identity | `google_sub` записан в **тот же** UUID, второй аккаунт не создан — PASS (Production) |
| Owner email | пока **атрибут профиля**, не login-identity |
| Email delivery | Resend через `auth.stratforges.com` — PASS, письма реально доходят |
| Production sender | `StratForge <no-reply@auth.stratforges.com>` |
| Canary sender | `StratForge Canary <canary@auth.stratforges.com>` |
| Trusted-device архитектура | credential в httpOnly cookie на окружение, сервер хранит digest, проекция в `sf_trusted_devices` — PASS |
| Очистка устройств | Canary 4→1, Production 2→1 — выполнена через canonical auth-document |
| Backup / rollback point | `pre-identity-cleanup-20260814T235458Z` (валиден, проверен) |
| `ARTUR_CA` (`75c34783…`) | реальный пользователь — не трогать |
| `stage9_canary_operator` (`c33c5adb…`) | системная запись |
| `123456` (`9de0d410…`), `505` (`bca76cf5…`) | доказанные test fixtures — удалить |

Counts на момент записи — Production: users 5, identities 6, sessions 7,
devices 1, workspaces 4. Canary: users 1, identities 1, devices 1, workspaces 1.

---

## Незакрытые пункты, по порядку причинности

### 1. Email как verified login identity (блокирует пункт 2)

`security_devices._available_providers()` (`app/security_devices.py:446`)
отдаёт `email` **только** если у пользователя есть identity с провайдером
`email` и заполненным `verified_at_utc`. У owner email лежит атрибутом
профиля, identity нет → в подтверждении устройства не предлагается ни email,
ни Google, остаётся только Telegram.

Что делать: провести owner через существующий
`/api/auth/email/link/start` → `/api/auth/email/link/verify`
(`app/server.py:7683`), который создаёт identity на **текущем** пользователе,
без нового аккаунта. Код придёт письмом (delivery уже работает).
Требует ввода OTP человеком → `WAITING FOR OWNER`.

### 2. Доставка кода подтверждения устройства (корневой баг)

`security_devices.create_challenge()` (`app/security_devices.py:492`)
генерирует код, сохраняет `code_hash`, возвращает `delivery: <provider>` —
**и не вызывает ни одной отправки**. В модуле нет ни `api_call`, ни email.
Код раскрывается только через `test_code` за Development-гейтом.

Поэтому «код не приходит» — он никогда не отправлялся.

Что делать:
- Telegram — `telegram_service._api_call` (используется в `account_auth`
  для owner-approval, шаблон готов);
- email — `account_auth._deliver_email_code(recipient, code, purpose=...)`
  (уже рабочий, с User-Agent для Cloudflare перед `api.resend.com`);
- при неуспехе доставки возвращать честную ошибку (по образцу
  `email_delivery_failed`, 503), а не мнимый успех.

Тесты: доставка вызвана; провал доставки → 503 и challenge не выдаётся как
успешный; секреты не попадают в ответ.

### 3. Trusted-device E2E

После пунктов 1–2 проверить цепочку целиком:
`pending → real delivery → verify → trusted → refresh → logout/login →
approve → revoke → delete → login после revoke`, отсутствие дублей,
очистка данных браузера создаёт новое устройство, изоляция Canary/Production.

### 4. Удаление test fixtures

Удалить `9de0d410…` (legacy `123456`) и `bca76cf5…` (legacy `505`) вместе с их
identities/sessions/workspaces/devices. У каждого по 1 workspace, сессий и
устройств нет. Перед удалением — dependency-check по `sf_workspaces`,
`sf_workspace_memberships`, `sf_active_workspaces`, `sf_jobs`, `sf_commands`,
`sf_audit_events` (FK на `user_uuid` объявлены `NOT VALID`, поэтому проверять
явно). Чистить **в auth-документе**, не в проекционных таблицах.

### 5. LOCAL owner profile

`127.0.0.1:8765` показывает владельца как «Пользователь». Не диагностировано.
Запущенный процесс LOCAL отстал от репозитория — перед проверкой перезапустить
на актуальном commit (`DEPLOYMENT_ENV=development python -m app.server 8765`
из `NT-Analyzer`), затем сверить `/api/auth/me` с owner-документом.

### 6. Telegram one-click UX

Сейчас `/api/auth/login/start` возвращает `bot_url` вида
`https://t.me/StratForgeAI_bot?start=canary_login_<CODE>` — deep link уже есть.
Нужно: кнопка открывает его сама, страница поллит `/api/auth/login/status` и
входит без ручного копирования; `manual_command` оставить аварийным fallback.
Архитектуру общего бота не менять: Production принимает webhook, `[CANARY]`
форвардится во внутренний Canary origin.

### 7–12. Остальное

Регистрация нового пользователя и изоляция; Users/Admin CRUD и owner
protection; производительность Cabinet/Users/Admin/Release Center/Documents/
Environment Switcher (before/after); market-data regression (Production=hub,
Canary=consumer, одна provider connection, live charts); browser E2E
LOCAL→CANARY→PRODUCTION.

---

## Готовые инструменты

На хосте (`/home/stratforge/`), запуск через
`scratchpad/run_host_script.py`, интерпретатор выбирается
`SF_REMOTE_PYTHON=canary|production`:

| Скрипт | Назначение |
| --- | --- |
| `sf-device-cleanup.py <env> [--apply]` | классификация и очистка устройств; dry-run по умолчанию |
| `sf-user-mapping.py <env>` | полный mapping аккаунтов, контакты маскированы |
| `sf-verify-backup.py <backup-dir-name>` | счётчики таблиц + проверка дампов |

Важно: скрипты читают окружение из `/proc/<pid>/environ` живого api-процесса —
разбор env-файла не даёт storage-конфигурацию (`storage_configuration`).
Запускать только интерпретатором релиза (`.venv/bin/python`), иначе нет
`psycopg`.

Релиз выполняется кнопками Release Center с LOCAL DEV
(`scratchpad/release_buttons.py` дублирует те же вызовы):
`run <version> <channel> <commit>` → `canary-pass <id>` → `production <id>`.

## Грабли, на которые уже наступали

- Значения env с пробелами и `<`/`>` **обязаны** быть в одинарных кавычках:
  лаунчеры делают `source`, иначе приложение не стартует и blue/green
  откатывается.
- `pg_dump` под ролью приложения требует `--enable-row-security` вместе с
  `stratforge.service_scope=global`, иначе дамп молча пустой.
- `git bundle create` требует явного `HEAD` в списке ref, иначе клон на хосте
  не имеет HEAD.
- POSIX-путь, переданный аргументом из Git-Bash, переписывается MSYS.

## WAITING FOR OWNER

1. Ввести OTP из письма для превращения email в login-identity (Canary и
   Production).
2. Подтвердить устройство после того, как доставка кода заработает.
3. Перевыпустить раскрытые секреты перед публичным запуском: Google Client
   Secret ×2, Resend API key ×2. Места замены —
   `/home/stratforge/production_data/config/{production-app,canary}.env`
   (ключи `NTA_GOOGLE_CLIENT_ID`, `NTA_GOOGLE_CLIENT_SECRET`,
   `NTA_RESEND_API_KEY`), локально —
   `NT-Analyzer/data/development/integrations/secrets.local.json`.
   После правки: `supervisorctl restart api api-app`.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-15T01:20:00Z | Claude Opus 5 через Claude Code по запросу owner | Handoff незакрытого auth/user контура: owner UUID и Telegram/Google подтверждены, email-identity и доставка кода подтверждения остаются открытыми; зафиксированы root cause, порядок работ и готовые инструменты.
-->
