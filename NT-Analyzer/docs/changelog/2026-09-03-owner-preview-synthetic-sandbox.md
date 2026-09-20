# Owner Preview / Synthetic User Sandbox — Development

Release title: Owner Preview / Synthetic User Sandbox

Change summary: владелец может открыть StratForge глазами обычного
пользователя. «Developer Preview» запускает отдельный loopback-процесс с
собственным data root, cookie namespace и synthetic identity, где реальный
Aurora UI, реальные маршруты и реальная бизнес-логика работают на одноразовых
synthetic-данных. Реальный аккаунт владельца при этом не подменяется, не
копируется и не изменяется, а внешние эффекты (Telegram, e-mail, платежи,
брокеры, cloud AI, live orders) технически заблокированы.

Source branch: `codex/device-confirmation-trusted-access`

Pull request: [#278](https://github.com/OMNOM-111/NT-Analyzer/pull/278)

Verification result: `PASS (Development)` — полный regression
`2527 passed, 32 skipped`, focused preview/auth/device suites, browser
walkthrough A–E во встроенном браузере, repository-root static scan и
production-bundle pre-release check зелёные.

Release impact: только Development. Preview физически невозможен в Canary и
Production: `runtime_env.assert_production_safe` падает при
`STRATFORGE_PREVIEW_SANDBOX=1`, а сам флаг действует лишь вместе с явным
Development-окружением, test-auth и высокоэнтропийным process id от
родительского сервера. Merge, build, release и deployment — отдельные решения
владельца.

## User result

1. ✅ «Developer Preview» → сценарий → отдельный процесс и одноразовая ссылка
   входа; настоящая owner-сессия остаётся нетронутой.
2. ✅ Внутри Preview владелец проходит настоящую регистрацию, первый вход,
   подтверждение устройства, OTP и попадает в обычный кабинет.
3. ✅ Полоса `PREVIEW / TEST USER` видна на выборе режима, на входе, на экране
   подтверждения устройства, на OTP, на success-экране и на всех страницах
   кабинета; рядом всегда есть `Exit Preview`.
4. ✅ `Reset Preview`, `New Preview User` и `Новый browser/client` работают из
   этой же полосы; `Exit Preview` возвращает в реальный аккаунт владельца.
5. ✅ Разделы (Обзор, Бэктест, Торговля, Рабочий стол, Финансы, Стратегии,
   AI Lab, AI Agents, Новости, Сообщество, TopStep, Документы) открываются с
   synthetic-данными, а не пустыми.

## Architecture

- `app/preview_server.py` — минимальный loopback-entrypoint. Тот же
  production `Handler`, но без worker, Telegram consumer, market-data
  transport, AI-моделей, туннеля и Connector-службы.
- `app/preview_sandbox.py` — идентичность песочницы, one-time entry token,
  HttpOnly control cookie, synthetic dataset, сценарии и guard-ы.
- `app/dev_preview.py` — запуск дочернего процесса владельцем: свободный
  loopback-порт, временный контейнер, очистка окружения от секретов, ожидание
  readiness и остановка/удаление предыдущей песочницы.
- Изоляция: уникальный `STRATFORGE_PREVIEW_ID`, data root строго внутри
  `<temp>/stratforge-preview-sandboxes/<pid>/<preview_id>/data`, cookie
  `sf_preview_<id>_session`, local-storage namespace `preview-<id>`.
- Внутри Preview localhost-owner bypass выключен: процесс обязан пройти
  настоящие public auth/session/device-гейты как synthetic user.
- Исходящие соединения блокируются на уровне сокета; дополнительно
  fail-closed отсекаются Telegram, Connector, admin-release, PayPal и cloud
  AI маршруты до диспетчеризации.

## Fixes found by the browser walkthrough

- Полоса Preview отсутствовала на экране выбора режима — добавлена в
  `pages/mode-entry.js`.
- `auth-locked` оболочка оставалась двухколоночной, из-за чего карточки
  подтверждения устройства сжимались в колонку rail — сетка схлопывается.
- Панель synthetic OTP в узкой карточке входа ломалась на одно слово в строке
  — у текстового блока появилась собственная flex-basis.
- Preview-пользователь ошибочно видел блокировку AI Agents / Workspace —
  synthetic identity получает полный пользовательский набор, оставаясь
  не-owner и без административных возможностей.
- «Мои сессии» показывали «Завершение по серверу: только что» для будущего
  времени — добавлен отдельный forward-looking `secUntil`.
- Строка сессии показывала имя клиента на момент входа и не менялась после
  переименования — сессия наследует текущее имя клиента.
- Удалённый API-клиент отображался как «Браузер» — User-Agent без браузерного
  движка теперь показывается как «Приложение».
- Обзор, Торговля и Финансы оставались пустыми: их данные читаются из
  process-global `runtime`, а seeder писал только в workspace store — теперь
  synthetic bridge snapshot пишется в оба, а его heartbeat поддерживается
  свежим отдельным потоком внутри песочницы.
- AI Lab и Новости открывались пустыми — добавлены synthetic-исследования и
  локально сгенерированный экономический календарь.
- Logout внутри Preview выводил владельца из его настоящей Development-сессии:
  cookie не ограничена портом, а маркер «остаться разлогиненным» имел общее
  имя. Внутри песочницы он теперь называется
  `sf_preview_<id>_dev_preview_mode`.
- Seeder мог записать synthetic-данные в репозиторный `ai_lab`, потому что
  `app.ai_lab.paths` фиксирует каталоги при импорте. Добавлен fail-closed
  guard: цель обязана лежать внутри изолированного root.

## Isolation and compatibility

- SF Chat и Community UI, маршруты, хранилище и бизнес-логика не изменялись.
- Реальные данные владельца не читаются, не копируются и не изменяются:
  процесс видит только свой временный root.
- Preview-маркер в аккаунте (`is_preview_user`, `preview_sandbox_id`) никогда
  не выводится из клиентского ввода и не даёт административных прав.
- Обычный Development-контур ведёт себя как раньше: synthetic OTP-панель
  скрыта, delivery остаётся `development_test`, маркер logout сохраняет
  прежнее имя.

## Verification evidence

- `tests/test_preview_sandbox.py` — идентичность и cookie-изоляция, one-time
  entry token, constant-time control token, реальная регистрация и pending
  gate, четыре сценария, группировка machine/client, блокировка внешних
  эффектов, очистка окружения дочернего процесса, отказ от root вне базы,
  наполнение runtime/research/calendar, свежесть heartbeat, остановка часов
  перед Reset, guard записи вне root и изоляция logout-маркера.
- Полный regression: `2527 passed, 32 skipped`.
- Browser walkthrough A–E во встроенном браузере: новый пользователь,
  доступ только до конца сессии, новый неизвестный client, раздел
  «Безопасность» целиком и обход разделов продукта.
- Repository-root static scan: CSP, SECRETS, MARKDOWN — PASS.
- `git diff --check`, `python -m compileall app`, `node --check` для
  отгружаемого JavaScript — PASS.
- Production bundle pre-release check: `476` файлов, четыре гейта PASS.
- Canary/Production не затрагивались; owner visual acceptance и живая
  доставка Telegram/e-mail остаются отдельными шагами.

## Unified Local beta.96 — contextual registration delta

В интеграционной ветке `integration/stratforge-unified-local` (PR #280,
implementation `42a99a85f164f69c6ddd0edf46859ef005e787e2`) Preview приведён в
соответствие с новым трёхшаговым onboarding. Удалён ускоренный сценарий,
который выбирал e-mail, получал код и отмечал согласие вместо owner. Теперь
каждый настоящий экран остаётся в цепочке, а локальная synthetic-кнопка
заменяет только credential/provider side: профиль, Telegram, Google, e-mail,
OTP или QR.

Telegram использует настоящий challenge и обычное завершение регистрации;
Google — настоящий staged-registration; e-mail — обычный OTP state. Terms,
создание профиля, Device Confirmation и permanent/session-only choice не
автоматизируются. Все synthetic identity/provider endpoints закрыты
Preview-флагом и HttpOnly control cookie, внешние Telegram/Google переходы и
provider transports в sandbox не выполняются. Обычный Local возвращает `404`
на synthetic endpoint, а `Exit Preview` возвращает исходный owner account,
balance, runtime и status без замены или изменения owner-данных.

Проверено: focused suite `173 passed`; full regression `2680 passed, 44
skipped`; ручной browser walkthrough всех трёх provider, QR, обоих режимов
доверия и восстановления Owner Local — PASS, browser console errors — 0.
