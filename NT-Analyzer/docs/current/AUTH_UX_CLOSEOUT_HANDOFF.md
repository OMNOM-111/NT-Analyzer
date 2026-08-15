# Auth / user-contour closeout — handoff

Дата: `2026-08-15` UTC. Базовый релиз на всех окружениях: `ca06cb9f`.

Этот документ существует, чтобы следующая сессия **начала с незакрытого пункта
и не проводила повторную диагностику**. Всё в разделе «Зафиксировано» —
проверено на живых окружениях; переизобретать не нужно.

**Статус на 2026-08-15 (вторая сессия).** Закрыты пункты 2, 5, 6; пункт 3
покрыт в тестах и ждёт живой прогон. Полный прогон: 1363 passed, 31 skipped.
Открыты: 1 (ждёт владельца), 4 (удаление данных на живых окружениях — нужно
подтверждение), 7–12 (требуют релиза и живых окружений). Ничего из открытого
не блокируется кодом.

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

### 2. Доставка кода подтверждения устройства (корневой баг) — ЗАКРЫТО

Было: `create_challenge()` генерировал код, сохранял `code_hash`, возвращал
`delivery: <provider>` — и не вызывал ни одной отправки. «Код не приходит»,
потому что он никогда не отправлялся.

Сделано в `app/security_devices.py`:

- секция «Challenge delivery»: `_delivery_target()` резолвит адрес **только**
  из серверного identity-состояния (клиент никогда не называет получателя),
  `_deliver_telegram_code()` через `telegram_service._api_call`,
  email/google через `account_auth._deliver_email_code(...)`;
- `create_challenge()` отправляет код после записи challenge, но **до** того
  как отдать успех. Сеть вызывается вне store-lock;
- провал доставки → `_fail_challenge()` жжёт challenge (`status: failed`,
  подтвердить его уже нельзя) + audit `security.challenge_delivery_failed`,
  наружу `503 challenge_delivery_failed`; не настроен транспорт →
  `503 challenge_delivery_unavailable`. Мнимого успеха больше нет;
- ошибки провайдера могут содержать токен бота, поэтому наружу уходит
  фиксированный текст; причина пишется в audit (`detail`);
- Development-гейт не изменился: при `_dev_code_echo()` код раскрывается
  через `test_code` и отправка не выполняется.

В `app/account_auth.py`: `_email_code_message()` получил step-up-цели
(`device_confirm` / `step_up` / `revoke`), `_deliver_email_code()` — `ttl_sec`,
чтобы письмо называло TTL device-challenge, а не email-login.

Тесты (`tests/test_phase4_trusted_devices.py`, секция «Challenge delivery»):
доставка реально вызвана и получатель взят из identity; доставленный код
подтверждает устройство; кода нет в ответе; провал → 503, challenge сожжён,
устройство осталось `pending`, токен не утёк; нет транспорта → 503;
email уходит на verified identity с правильными purpose/TTL; echo-гейт не
отправляет ничего.

### 3. Trusted-device E2E — покрыто в харнессе, живая проверка ждёт п.1

`test_trusted_device_lifecycle_end_to_end_with_real_delivery` проходит цепочку
через реальный путь доставки: `pending → доставленный код → confirm → trusted →
logout/login (одна запись, trust сохраняется) → очистка данных браузера даёт
новое pending-устройство → revoke гасит только его сессии → повторный вход не
воскрешает trust`. Изоляция окружений уже закрыта
`test_challenge_wrong_environment`.

Осталось живьём (после п.1 и релиза): та же цепочка на Canary и Production
с настоящим Telegram/письмом и браузером.

### 4. Удаление test fixtures

Удалить `9de0d410…` (legacy `123456`) и `bca76cf5…` (legacy `505`) вместе с их
identities/sessions/workspaces/devices. У каждого по 1 workspace, сессий и
устройств нет. Перед удалением — dependency-check по `sf_workspaces`,
`sf_workspace_memberships`, `sf_active_workspaces`, `sf_jobs`, `sf_commands`,
`sf_audit_events` (FK на `user_uuid` объявлены `NOT VALID`, поэтому проверять
явно). Чистить **в auth-документе**, не в проекционных таблицах.

### 5. LOCAL owner profile — ЗАКРЫТО

LOCAL перезапущен через `start.ps1` (это единственный правильный лаунчер: он
форсирует `DEPLOYMENT_ENV=development` и
`STRATFORGE_DEVELOPMENT_DATA_ROOT=<repo>/data`). На актуальном commit
`/api/runtime/env` отдаёт `development / dev / c487ee05`, а `/api/auth/me` —
полный профиль владельца: `dimon_check`, `DMYTRO CHEREVKO`,
`6b0738c8-efca-4285-9100-905e34633d56`, `profile_complete: true`.
`userLabel()` на нём рисует «DMYTRO CHEREVKO». Самого симптома «Пользователь»
на `/api/auth/me` нет.

Что реально нашлось: в LOCAL-хранилище (`data/integrations/accounts.dpapi`)
есть **вторая** запись с `is_owner: true` — `user_id 424242`,
`643f4ab5-536c-4122-86e5-4d702a9f2043`, с пустыми `username` / `first_name` /
`last_name` и verified telegram identity на subject `424242`. Именно она в
списках пользователей рисовалась анонимным «Пользователь».

Исправлено в `userLabel()` (`app/static/aurora/assets/ui.js`): безымянный
профиль подписывается по роли — владелец виден как «Владелец». Фикс общий, не
LOCAL-костыль. Сама запись `424242` — локальная workstation-фикстура, к
серверным окружениям отношения не имеет; в п.4 она не входит и не трогается.

Предупреждение на будущее: `NTA_APP_ENV=development` уводит на
`data/development/integrations/accounts.dpapi` — **не** то хранилище, которое
обслуживает LOCAL. Сверять только через запущенный сервер или через
`STRATFORGE_DEVELOPMENT_DATA_ROOT`.

### 6. Telegram one-click UX — ЗАКРЫТО

`renderWaiting()` (`app/static/aurora/assets/ui.js`) теперь открывает deep link
сам (`window.open`), ровно один раз на challenge (`openedDeepLinks`, иначе
поллинг каждые 2 с устраивал бы popup-шторм), поллинг
`/api/auth/login/status` уже был и оставлен. `manual_command` спрятан в
свёрнутый `<details class="auth-manual-fallback">` «Telegram не открылся?» —
аварийный fallback, а не инструкция. Если браузер заблокировал вкладку, кнопка
`#auth-open-telegram` остаётся, и подсказка это говорит. Стили —
`.auth-manual-fallback` в `theme.css`. Архитектура общего бота не менялась.

Тесты: `tests/test_phase11_ui_wiring.py`, секции one-click и owner-label.

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
2026-08-15T00:00:00Z | Claude Opus 5 через Claude Code по запросу owner | Закрыты п.2 (доставка кода подтверждения устройства: реальная отправка Telegram/email, честный 503 и сожжённый challenge при провале), п.5 (owner без профиля подписывается по роли) и п.6 (Telegram one-click); п.3 покрыт E2E-тестом жизненного цикла на пути реальной доставки. П.1 ждёт OTP владельца, п.4 — подтверждения на удаление данных, п.7–12 — релиза и живых окружений.
-->
