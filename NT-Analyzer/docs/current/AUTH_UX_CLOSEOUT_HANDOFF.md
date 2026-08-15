# Auth / user-contour closeout — handoff

Дата: `2026-08-15` UTC. Базовый релиз на всех окружениях: `ca06cb9f`.

Этот документ существует, чтобы следующая сессия **начала с незакрытого пункта
и не проводила повторную диагностику**. Всё в разделе «Зафиксировано» —
проверено на живых окружениях; переизобретать не нужно.

**Статус на 2026-08-15 (вторая сессия).** Закрыты пункты 2, 5, 6, 7, 8, 10;
код для п.4 готов и в проде; п.3 и 9 закрыты в тестах, живой прогон за
владельцем. Полный прогон: **1375 passed, 31 skipped**.

Смержено и выкачено: PR #51 … #58, пять релизов
`0.10.0-beta.1 → beta.5`, каждый Canary → acceptance → **тот же immutable
artifact** → Production, 8/8 blue-green шагов на обоих окружениях.

Открыто только то, что физически требует владельца — см. **WAITING FOR
OWNER** в конце. Общая причина у почти всего: автоматизации недоступны
учётные данные владельца, поэтому любая аутентифицированная проверка на
живых Canary/Production выполняется только человеком.

Найдено и починено попутно, вне исходного списка:

- **удаление аккаунта было неполным** — оставляло identities, devices и
  security challenges (п.4);
- **релиз не доезжал до браузеров** — `?v=` штампы ассетов правились руками и
  разъехались на девять значений (старейшее от `20260629`), а CDN держит эти
  URL 4 часа. Зелёный деплой ≠ доставленный деплой (PR #57);
- **аватар инлайнился base64 в каждый payload** — ~27 КБ на пользователя
  (п.8).

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

### 4. Удаление test fixtures — код готов, само удаление за владельцем

Удалить `9de0d410…` (legacy `123456`) и `bca76cf5…` (legacy `505`).

**Сначала пришлось починить сам механизм удаления.** `delete_user()` удалял
только запись пользователя, сессии, challenges и файл аватара — а identities,
trusted devices и security challenges (ключ `user_uuid`) оставались. Это не
косметика: осевшая identity-строка держит subject привязанным к
несуществующему пользователю, и `_link_identity_in_doc` навсегда отвечает
`identity_already_linked` — освободившийся Telegram id или e-mail уже никогда
нельзя привязать к живому аккаунту. Если бы п.4 выполнили старым кодом,
фикстуры удалились бы наполовину.

Исправлено (PR #53, в проде с `0.10.0-beta.3`):

- удаление покрывает identities, devices, security challenges и sessions;
- строки сопоставляются по каноническому UUID с fallback на legacy id —
  до Phase 3 backfill строки несут только legacy id, после — только UUID;
- workspaces живут в отдельном документе и чистятся через
  `workspaces.purge_user()`, который **отказывается** забирать рабочую
  область, где остаются другие участники;
- отказ проверяется **до** мутации auth-документа, поэтому rejection не может
  оставить полуудалённый аккаунт; owner protection проверяется первой;
- `account_auth.account_footprint()` — тот же учёт read-only, это и есть
  dependency-check перед удалением (FK на `user_uuid` объявлены `NOT VALID`,
  поэтому снизу никто не откажет).

Осталось владельцу: выполнить удаление на Canary и Production через Users →
кнопка удаления (`POST /api/auth/users/<legacy_id>/delete`). Автоматизация
это сделать не может: нужна аутентифицированная сессия владельца.

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

### 7. Users/Admin CRUD и owner protection — ЗАКРЫТО

Owner protection проверена и усилена: `delete_user()` отказывает по владельцу
раньше всех прочих причин (403 «Аккаунт владельца нельзя удалить»), и это
покрыто тестом — до фикса общий workspace владельца давал 409 вместо 403.
Полный аудит удаления — п.4. Остальные мутации (`role`, `status`, `features`,
`permission`, `admin-permission`, `sessions`) идут через
`_require_admin_capability_in_doc(..., "users.manage")` и уже покрыты
`tests/test_account_auth.py` / `tests/test_cabinet.py`.

### 8. Производительность — ЗАКРЫТО, с before/after

Профиль всех эндпоинтов за Cabinet / Users / Admin / Release Center /
Documents / Environment Switcher (LOCAL, 12 замеров, первый отброшен).

**Латентность здорова**: максимум `48 ms p50` (`/api/admin/operations`),
всё остальное ниже. Оптимизировать нечего.

**Реальная проблема — объём.** `_public_user()` инлайнил аватар как base64
data URL рядом с `avatar_url`, который и так отдавался. Data URL не
кэшируется, поэтому те же ~27 КБ уходили в каждом ответе, называющем
пользователя — включая `/api/auth/me` и `/api/auth/status` (UI дёргает их на
каждой странице) и `/api/auth/users`, где это платилось **за каждого**
пользователя.

| endpoint | было | стало | Δ |
| --- | ---: | ---: | ---: |
| `/api/auth/me` | 39 780 B | 12 444 B | −69 % |
| `/api/auth/status` | 34 853 B | 7 519 B | −78 % |
| `/api/auth/users` | 84 715 B | 15 288 B | −82 % |

`/api/auth/users` больше не растёт на 27 КБ с каждым новым пользователем.
Аватар едет только как `avatar_url` со штампом `?v=<avatar_updated_at_utc>`,
эндпоинт отдаёт `private, max-age=86400, immutable`. PR #55, в проде с
`0.10.0-beta.4`.

### 9. Market-data regression — репозиторная часть закрыта

`test_market_data*.py` + `test_owner_market_data_gateway.py` +
`test_topstep_market_data.py` — **136 passed**. Живая проверка
(Production=hub, Canary=consumer, одна provider connection, live charts)
требует аутентифицированной сессии владельца — см. WAITING FOR OWNER.

### 10. Environment Switcher / Release Center — ЗАКРЫТО

Release Center прогнан end-to-end **пять раз** (beta.2 … beta.5), всё
кнопками из LOCAL DEV: `run` → build → verify → deploy-canary →
`record-canary-check` → `approve-production` → `promote-production`. Каждый
раз 8/8 blue-green шагов pass на обоих окружениях, и на Production уезжал тот
же самый immutable artifact, что проверялся на Canary. Adapter:
`stage9_ssh`, `mode: real`, `configuration_state: ready`.

Грабли, подтверждённые заново: Release Center отказывает на грязном дереве
(`dirty_worktree`), а приложение **перегенерирует `data/governance-rendered/*`
при каждом старте**, поэтому перед каждым билдом эти файлы приходится
складывать в stash. Это стоит починить отдельно — приложение не должно писать
в tracked-файлы на старте.

### 11–12. Регистрация нового пользователя, browser E2E

Требуют браузера и живых учётных данных — см. WAITING FOR OWNER.

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

Единственная общая причина: **у автоматизации нет учётных данных владельца**.
Прочитать сохранённые session-cookie ей запрещено, а хост-скрипты, читающие
живые данные аккаунтов, заблокированы политикой. Поэтому всё, что требует
аутентифицированной сессии на Canary/Production, делает человек. Всё
остальное уже сделано, выкачено и проверено.

Каждый пункт доведён до последнего клика.

1. **Email → login-identity** (п.1, блокирует п.2 из исходного списка).
   Кабинет → Безопасность → «Привязать e-mail» на Canary, затем на
   Production. Код придёт письмом: доставка проверена —
   `/api/auth/providers` на обоих окружениях отдаёт
   `email: {provider: resend, operational: true, production_ready: true,
   test_backend: false}`. Ввести OTP. Ожидаемо: в `auth_identities`
   появляется строка `provider=email` с `verified_at_utc` на **том же**
   UUID, нового аккаунта не создаётся.

2. **Подтверждение устройства** (п.3, живой прогон). После п.1 в
   подтверждении устройства должны предлагаться Telegram, email и Google —
   до этого только Telegram. Кабинет → Безопасность → устройство в
   `pending` → «Подтвердить» → выбрать канал → код теперь **реально
   приходит** (это и был корневой баг, PR #51). Пройти цепочку целиком:
   `pending → код → verify → trusted → logout/login → revoke → повторный
   вход`. Та же цепочка автоматически прогоняется в
   `test_trusted_device_lifecycle_end_to_end_with_real_delivery`.

3. **Удаление test fixtures** (п.4). Users → найти `123456`
   (`9de0d410…`) и `505` (`bca76cf5…`) → удалить, на Canary и на
   Production. Механизм удаления починен и уже в проде (`0.10.0-beta.3`):
   теперь уносит identities, devices, security challenges, sessions и
   workspaces, отказывается забирать общую рабочую область и защищает
   владельца. `ARTUR_CA` (`75c34783…`), canonical owner
   (`eb9d8e32…`) и `stage9_canary_operator` (`c33c5adb…`) **не трогать**.

4. **Google на Canary** (живая проверка). `/api/auth/providers` уже
   подтверждает `google: {available: true, configured: true,
   test_auth_fallback: false}` на обоих окружениях — то есть настроен
   реальный Google, а не тестовая заглушка. Остаётся сам вход: войти на
   Canary через Google и убедиться, что `google_sub` лёг в **тот же** UUID
   и второй аккаунт не создан (на Production это уже доказано).

5. **Market-data live** (п.9). Репозиторная регрессия зелёная (136 passed).
   Живьём: Production=hub, Canary=consumer, одна provider connection,
   живые графики.

6. **Регистрация нового пользователя и browser E2E** (п.11–12).
   LOCAL → CANARY → PRODUCTION в браузере. Заодно проверить, что после
   PR #57 страница подтягивает ассеты со свежим `?v=<build_id>` — раньше
   релиз мог не доехать до браузера четыре часа.

7. **Перевыпустить раскрытые секреты** перед публичным запуском: Google
   Client Secret ×2, Resend API key ×2. Места замены —
   `/home/stratforge/production_data/config/{production-app,canary}.env`
   (ключи `NTA_GOOGLE_CLIENT_ID`, `NTA_GOOGLE_CLIENT_SECRET`,
   `NTA_RESEND_API_KEY`), локально —
   `NT-Analyzer/data/development/integrations/secrets.local.json`.
   После правки: `supervisorctl restart api api-app`.

## Стоит починить отдельно

- Приложение **перегенерирует `data/governance-rendered/*` при каждом
  старте**, а Release Center отказывает на грязном дереве, поэтому перед
  каждым билдом эти файлы приходится складывать в stash. Приложение не
  должно писать в tracked-файлы на старте.
- CDN отдаёт ассеты с `public, max-age=14400`, тогда как origin ставит
  `max-age=120`. После PR #57 это безопасно (URL меняется с каждым билдом),
  но расхождение стоит осознанно зафиксировать в правилах CDN.

<!-- STRATFORGE_INTERNAL_AMENDMENT
2026-08-15T01:20:00Z | Claude Opus 5 через Claude Code по запросу owner | Handoff незакрытого auth/user контура: owner UUID и Telegram/Google подтверждены, email-identity и доставка кода подтверждения остаются открытыми; зафиксированы root cause, порядок работ и готовые инструменты.
2026-08-15T00:00:00Z | Claude Opus 5 через Claude Code по запросу owner | Закрыты п.2 (доставка кода подтверждения устройства: реальная отправка Telegram/email, честный 503 и сожжённый challenge при провале), п.5 (owner без профиля подписывается по роли) и п.6 (Telegram one-click); п.3 покрыт E2E-тестом жизненного цикла на пути реальной доставки. П.1 ждёт OTP владельца, п.4 — подтверждения на удаление данных, п.7–12 — релиза и живых окружений.
2026-08-15T22:45:00Z | Claude Opus 5 через Claude Code по запросу owner | Закрытие этапа: PR #51–#58 смержены, пять релизов beta.1→beta.5 через Canary → acceptance → тот же immutable artifact → Production. Дополнительно закрыты п.7 (owner protection), п.8 (профиль производительности и сокращение payload: me −69%, status −78%, users −82%), п.10 (Release Center end-to-end ×5); п.9 закрыт в тестах. Попутно найдены и починены три дефекта вне списка: неполное удаление аккаунта, релиз не доезжавший до браузеров из-за ручных ?v= штампов и CDN, инлайн base64 аватара. Открытое сведено к WAITING FOR OWNER — всё оно требует учётных данных владельца.
-->
