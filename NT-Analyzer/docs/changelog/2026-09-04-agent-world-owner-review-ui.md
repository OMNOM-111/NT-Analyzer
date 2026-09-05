# AI Центр — интерфейс локальной проверки владельца

## Назначение изменения

Добавлен нативный Aurora-интерфейс AI Центра для объединённого просмотра
задач, Persona, измеренных оценок и артефактов. Визуальная композиция следует
согласованным эскизам: работа, команда и требующие внимания события на обзоре,
подробности доступны в Task Inspector и профиле агента.

Статус функции: **IN DEVELOPMENT** — локальный интерфейс owner review,
подключённый через facade и разрешённые workspace-флаги. Интеграция реальных
источников и итоговая визуальная приёмка ещё не закрыты. Это не
Canary/Production release.

## Пользовательские изменения

- Три локальных раздела: Обзор, Работа, Агенты. Задачи, результаты, команда
  и измеренный рейтинг расположены рядом на основном экране. Адаптивная компоновка, клавиатурная навигация,
  состояния загрузки, отсутствующих данных, ошибок и недостаточного доступа.
- Задачи с фильтрами, наблюдаемой активностью, проверками, результатами и
  scoped-артефактами. Нет публикации скрытой цепочки рассуждений модели.
- Отдельные Persona, Agent Role и Model. Проверочный рейтинг показывает
  размер выборки и уверенность; недостаточная выборка обозначена NEW.
- Локальные synthetic-задачи запускаются только по явному разрешению backend.
  Synthetic benchmark не называется оценкой качества внешней модели.
- Результат открывается в существующем SF Chat. SVG-график по явному клику
  растеризуется браузером в PNG и передаётся серверу для проверки и сохранения.
- Выключенные высокорисковые разделы не имитируют Court или торговые решения.
  Существующие исследования, подключения и настройки голосов не удалены.

## Scope и сохранённые границы

Изменены только новые `ai-command-center.html`, page-scoped CSS/JavaScript,
новые UI contract tests и эта запись. Общие `ui.js`, `api.js`, навигация,
server-side facade, permissions, реестр флагов и контекст-пакет интегрируются
в основной ветке задачи. Auth, Device Confirmation, SF Social, SF Chat stores,
Charts engine, Connector и торговое исполнение этим UI-slice не изменены.

Никакие credentials, cookies, runtime state или generated governance output
не включены в commit. Нет новой frontend-системы авторизации или хранения чата.

## Исходная точка и closeout

- Base SHA: `d5d07ac6817cd10f57d916dab0ce655347a8cbde`.
- Рабочая ветка UI-slice: `codex/agent-world-ui`.
- Интеграционная ветка: `codex/agent-world-owner-preview`; UI-slice передаётся
  туда отдельным commit, не добавляется в PR #280 или PR #281.
- Версия Local остаётся `0.10.0-beta.96`.
- Source commit, интеграционные проверки, PR и owner visual acceptance
  фиксируются основным change record этого implementation slice.

## Проверки и release impact

Первый UI-slice, до компактной редакции: `python -m pytest -q tests/test_agent_world_ui.py` —
**47 passed** (executable Node presentation contracts, HTML/CSP/assets,
keyboard/accessibility contracts, scope/URL validation и PNG rasterization).
`node --check`, Python compilation test-файла и `git diff --check` — **PASS**.
Полная регрессия, bundle/static/context gates и браузерная проверка проводятся
после подключения backend основной задачей; этот результат их не заменяет.

К публикации здесь ничего не подготовлено. Merge, artifact signing,
Canary/Production deployment и изменение версии не выполнялись.
External GPT Context Pack затронут; его current-state/UI/agents/handoff
изменения принадлежат основному интеграционному исполнителю этой же задачи.

## Согласование cache version при интеграции

После изменения общих `api.js` и `ui.js` их HTML cache markers механически
согласованы на `20260904-agent-world1` во всех Aurora-страницах, включая
mode picker (там только `api.js`). Обновлены ровно два соответствующих
ожидания в `test_aurora_contracts.py`. Версия `theme.css`, содержимое остальных
страниц и их контроллеры не менялись.

Проверка: cache/domain contracts — **4 passed, 57 deselected**;
Agent World UI contracts — **47 passed**; `git diff --check` — **PASS**.
`deselected` обозначает незапущенные в этом focused run сценарии, а не PASS.
Полную регрессию и static route allowlist проверяет основной исполнитель.

## Компактная редакция по дополнительному эскизу владельца

Референс: `МИР АГЕНТОВ/Без имени.png`. Редакция выполнена в интеграционном
checkout `agent-world-owner-preview`, поверх уже подключённого UI. Общие
Aurora-файлы и текущие изменения других исполнителей сохранены.

- Вместо первоначальных восьми верхних разделов оставлены три. Обзор
  одновременно показывает сводку, задачи, внимание, результаты с источником,
  последние действия, команду и проверочный рейтинг. Task Inspector и профиль
  агента остаются выдвижными панелями на этой же странице.
- Неактивные решения, память и эксперименты объединены в одну компактную
  карточку **IN DEVELOPMENT**. Отдельных пустых страниц и фоновых запросов к
  model/system API нет. Server-side flags отображаются только при явном
  `can_view_system`; существующие исследования и подключения не удалены.
- Реальные результаты принимаются через `overview.outcomes`, без генерации
  демонстрационных чисел. При отсутствии этого поля используется только
  сохранённое описание завершённых задач. Явный пустой список не подменяется
  резервными данными.
- Источник определяется по явным `synthetic: false` и `source_kind`:
  `ninjatrader_report`, `desktop_chart`, `runtime_observation`. Неизвестные
  данные не называются реальными или live. `synthetic: true` всегда имеет
  отдельную подпись и не получает ссылку на настоящий отчёт.
- Исходный отчёт открывается существующей страницей Backtesting по
  валидированному `source_job_id`. Проверка принадлежности отчёта остаётся
  server-side; UI не заменяет её. Изображения допускаются со scoped opaque
  artifact endpoint; узкое исключение для подтверждённого Desktop-источника
  описано в дополнении ниже.
- Сохранены интеграционные ограничения PNG в 256 KiB и ожидаемое завершение
  открытия SF Chat. Растеризация локального SVG не называется снимком живого
  Desktop: подключение такого источника принадлежит runtime-интеграции.
- Собственные page CSS/JS cache markers обновлены на
  `20260904-agent-world2`; общий API/UI marker не изменён.

Проверки компактной редакции: UI contracts — **66 passed**. В том числе
исполнение полного initial overview render без браузера, проверка XSS,
provenance/ссылок, выборки рейтинга, трёх вкладок, отсутствия лишних API
запросов и сохранения read-only/fail-closed поведения.
`node --check`, `python -m py_compile` и scoped `git diff --check` — **PASS**.
Браузерная проверка этой редакции и реальный runtime workflow — **PENDING**,
их выполняет основной интеграционный исполнитель. Эти contract tests не
подменяют визуальную приёмку владельца и не закрывают весь Agent World.

## Реальный SF Chat и снимок рабочего стола

Дополнительный разрешённый scope: `assets/pages/desktop.js` и новый
`tests/test_agent_world_desktop_snapshot.py`. Backend handler, очередь,
`market_data.py`, ChartEngine, Connector и engine бэктестов не изменены этим
исполнителем; server-side scope/admission подключаются основным исполнителем.

На Обзоре при явном `scope.synthetic: false` показаны две команды-примера
для существующего SF Chat: запуск `SampleMACrossOver` в NinjaTrader и снимок
существующего графика рабочего стола. Инструмент, период и параметры подписаны
как заменяемые примеры, не как выполненный результат. Даты — UTC, конец
периода исключён. Новый композер бэктеста и автоматическая отправка команд
не созданы; Preview не показывает эту подсказку.

Для `snapshot` с `payload.agent_world: true`:

- Существующий `ChartEngine.toImage()` снимает текущий вид в PNG с
  `maxWidth: 1200`; `fitView()` не вызывается, даже если входной payload
  ошибочно просит `fit: true`. Data URL ограничен 350000 символами;
  превышение 256 KiB объясняется владельцу до HTTP-запроса. Legacy-команды
  сохраняют JPEG/default options. Серверная проверка CRC и bounded PNG
  decompression принадлежит интеграционному handler.
- После ожидания проверяются существование окна, наличие фактических баров
  и непустой отображаемый диапазон. Пустой/недоступный canvas, недоступные
  данные и transport errors не дают успешный результат.
- Реально отображаемые бары читаются через существующие `getData()` и
  `_visibleRange()` того же renderer. Алгоритмы графика не копируются и не
  меняются. Метаданные относятся к снимку текущего графика, не к вымышленному
  headless-изображению.
- Запрос передаёт `agent_world`, `command_id`, `mirror_to_telegram: false`
  и `capture`: surface/window/instrument/timeframe, `view_preserved`, время,
  количество отображаемых и загруженных баров, первый/последний timestamp,
  имеющиеся series hash, price-marker state, provider/history state и
  transport. Неизвестное остаётся `null`; connected transport сам по себе
  не называется LIVE.
- Для успеха обязательны `ok: true`, совпадающий серверный `command_id`,
  сохранённый snapshot с согласованными id/file/url и `report.ok: true`.
  Ack содержит ссылки на этот сохранённый snapshot и capture receipt.
  Ошибки сохранения/доставки отмечаются существующим poller как `failed`.
- Legacy-команды сохраняют предыдущие request body, default fit и ack shape.
  Новые поля и ограничения не применяются к ним автоматически.
- Для подтверждённого `synthetic: false, source_kind: desktop_chart`
  Overview и Task Inspector отображают миниатюру с существующего
  authenticated snapshot store: только `/api/ops/runtime/snapshots/` и
  `cs_<32 lowercase hex>.(jpg|png|webp)`, без query, fragment и traversal.
  Неподтверждённые и synthetic-источники не получают это исключение.
  Это не замена server-side проверкам доступа. Миниатюра отображается и
  когда снимок не первый в списке результатов; рейтинг моделей остаётся
  NEW при недостаточной выборке, без автоматической подписи SHADOW.

Проверки после этого дополнения: UI contracts — **89 passed**; Desktop
snapshot receipt contracts — **26 passed** (общий focused run **115 passed**).
Существующие desktop template/instrument fallback и Aurora contracts —
**73 passed**. `node --check` обоих JS, Python compilation обоих тестов и
scoped `git diff --check` — **PASS**. Live screenshot через браузер,
server-side command ownership и фактический NinjaTrader workflow остаются
отдельной интеграционной проверкой; эти результаты не являются её PASS.

## HTTP facade checkpoint и совместимость runtime-статусов

Новый `tests/test_agent_world_live_http.py` поднимает временный loopback
`ThreadingHTTPServer` с настоящим `server.Handler`. Auth-контекст владельца
и каталоги заменены изолированными fixtures; facade, свежий gateway admission,
разбор HTTP body, Origin/CSRF, canonical job/report projection и чтение
Desktop receipt выполняются существующим кодом. Тестовые job/result/trades/bars
созданы в disposable roots. NinjaTrader, внешние модели и сеть вне этого
тестового HTTP-сервера не используются.

- Проверены GET overview/tasks/detail, открытие существующего SF Chat,
  fallback на chart task и полные совместимые DTO с исходными источниками.
- Default OFF, не-owner/read-only, pending device, отозванное членство,
  изменённый UUID, capability/budget denial, чужие UUID, scope/body injection,
  некорректные JSON/UUID и Origin/CSRF fail closed до доменного действия.
- В real Local нет demo-runs; POST точного backtest-spec использует canonical
  очередь, остаётся pending и идемпотентно повторяется без исполнения NT.
- Отдельный действующий Preview HTTP fixture подтверждает synthetic scope
  и невозможность перехода в real Local facade. Некорректный Preview root
  также не получает fallback в owner Local.
- Повторные GET и открытие диалога не изменяют domain/files или логическое
  содержимое SQLite и не вызывают start/reconcile/publish. Единственное
  исключение — обязательная audit-запись активации трёх server-side flags.
  SQLite WAL checkpoint сам по себе не трактуется как изменение доменных строк.
- Canonical `ready` отображается «В очереди» и включён в активные/ожидающие
  задачи. `working` — совместимый alias состояния running; миграций состояний нет.

Итоговый focused checkpoint: **156 passed** — **36 HTTP + 91 UI + 29 Desktop**.
`node --check` обоих JS, `py_compile` трёх test-файлов и scoped
`git diff --check` — **PASS**. Это implementation/test evidence, не полный
regression/CI closeout и не подтверждение запуска реального NinjaTrader.
Code freeze передан основному исполнителю для общей регрессии и браузерной
проверки. Stage/commit этим исполнителем в интеграционном checkout не выполнялись.

## Полный набор инструментов на одной странице — новое поручение owner

Исходная точка: `486db834850d465006a3983d2d83ee809202df60`. Это продолжение
локальной реализации, не смена версии, release, merge или deployment.

Три основных режима «Обзор / Работа / Агенты» сохранены; теперь они не
ограничивают функциональный объём. Постоянная панель инструментов открывает
на этой же странице Решения / Court, Память, Эксперименты, Модели,
Strategy Projects, Рутины, Календарь и Систему. Persona открывается из
«Агенты → Создать / изменить Persona», карточки рабочего пространства или
навигации любой панели. Task Inspector и профиль остаются боковыми панелями.
Ссылки на старые AI Lab/подключения больше не выдаются за реализацию этих
инструментов; при полностью выключенном AI Центре прежние совместимые пути
остаются доступны.

UI использует согласованный scoped facade: GET `domains/{domain}` и
`domains/{domain}/{id}`, POST `domains/{domain}/{id-or-new}/{action}`.
Mutation envelope — `payload`, `idempotency_key`, для существующих записей
доступная `expected_revision`. Действия доступны только из server-issued
`actions`; task cancel/retry — из `allowed_actions`. Формы не отправляют
user/workspace, роль, permissions или лимит бюджета. Backend повторно
проверяет полномочия и принадлежность; UI не является security authority.

- Persona: создание, изменение, активация, приостановка и архив по текущему
  разрешённому состоянию; личность не объединяется с моделью или ролью.
- Память: черновик, редактирование, основание продвижения/отзыва, источники
  и retention. Скрытое backend содержимое после TTL/revoke не восстанавливается.
- Проекты: описание, strategy key, версии с JSON-параметрами и архив.
- Рутины/календарь: создание, принятие/отклонение предложения, интервал или
  локальное время с сохранением UTC. UI явно не обещает фоновое исполнение.
- Решения/Court: proposal, risk, trigger, собственные JSON evidence candidates,
  выбор трёх проверяющих, реальные verdict/rationale/packet/session provenance.
  Клиент не голосует от имени модели и не разрешает исполнение решения.
- Модели: свой ключ в password-поле, активная Persona, model/external-agent
  connection, провайдеры только из server catalog, test/task/disconnect.
  Ключ не заполняется из DTO, не сохраняется в browser storage и очищается
  после подтверждённого действия. Сырые ошибки провайдера не выводятся.
- Эксперименты: одинаковый проверяемый вход для 2–3 подключённых моделей,
  реальные ответы, independent checks, latency и доступная cost-информация.
  Отсутствие расходов/Model ID показывается как неизвестное, не как ноль
  или угаданная модель. Наблюдение одного ответа не называется общим рейтингом.
- История моделей открывается из «Модели → История задач моделей»;
  ответ/проверки доступны в record inspector и через существующий SF Chat.
- Система: только inline чтение опубликованных status/flags/budget/limitations,
  без форм управления глобальными настройками.

Внешние test/task/comparison/Court вызовы требуют отдельного ручного checkbox
перед POST; cancel/disconnect/archive/revoke также явно подтверждаются.
Успешное принятие запроса не называется завершением задачи. Повтор после
неподтверждённого ответа сохраняет idempotency key. Все подписи/параметры
экранируются; секретоподобные поля в structured preview скрываются.

UI checkpoint: **142 passed**, включая исполнение реальных JS event handlers
для открытия доменов, моделей/Persona, CAS update, ручного consent, actual
response/evaluation, cancel, idempotency retry и отсутствия secret echo.
Это DOM/service-contract tests, не browser/provider acceptance. Фактические
внешние вызовы, endpoint/ключ/budget отрицательные сценарии и owner visual QA
проверяются основным исполнителем на согласованном runtime; их PASS здесь
не заявляется. Current/status/Context Pack и общий Git closeout ведёт основной
исполнитель. Scoped файлы оставлены без stage/commit.

## Реальный PostgreSQL acceptance — fixture drift, без изменения RLS

По отдельному поручению основного исполнителя исправлены только устаревшие
fixtures `test_production_storage.py`, `test_production_workers.py` и
`test_stage8_postgresql.py`. SF Chat relational fixture уже корректно задавал
service scope и не изменён.

Raw fixture connections задают `stratforge.service_scope=global`, как настоящий
PostgresClient для служебной транзакции. Auth document fixtures содержат
канонический UUID, требуемый writer после identity transition. Ожидаемый набор
миграций соответствует фактическим `0001`–`0022`. Неисполняемый тест с
отсутствующими `core.init_pool/flush_workspaces` и несуществующими SQL-колонками
заменён проверкой действующего DocumentRepository: повторный membership upsert
сохраняет одну строку, изменяет роль и не разрушает FK уже созданной задачи.
Outage checks резервируют отдельный loopback-порт без listener вместо
предположения о фиксированном порте `55432`.

Проверка выполнена runner основного исполнителя на fresh fixture cluster:
PostgreSQL **17.10**, `127.0.0.1:55439`, база
`agent_world_acceptance_20260905`, TLS `sslmode=require`.
`stratforge_test_admin` и `stratforge_app` — `NOSUPERUSER NOBYPASSRLS`.
Прямое чтение pg_stat_ssl/pg_roles/pg_class подтверждает TLS и сохранение
RLS/FORCE RLS. Это реальная изолированная тестовая БД, не mocks и не Production.

**41 passed, 0 skipped, 0 errors**, **124.45 s**: storage **12**, workers **12**,
Stage 8 **8**, SF Chat relational **9**. UI повторно после финального
отображения requested/actual model — **142 passed**. Production-код,
schema/RLS policies, реальные пользовательские данные и глобальные настройки
не изменялись. Общий full regression/CI и runtime acceptance ведёт основной
исполнитель.

## Дополнение: полная панель действий, публикация и HTTP authority contracts

Сохранены одна страница и три основных поверхности «Обзор / Работа / Агенты».
Решения/Court, Memory, Strategy Projects, routines/calendar, модели,
эксперименты и публикация проверенных результатов в SF Social открываются
внутри той же панели. Принятые страницы Auth, Security, SF Chat и SF Social
не переписывались. Legacy `community*` API/страница остаются действующими.

Формы используют разрешённые сервером actions, обычный mutation envelope
с revision/idempotency и свежие списки собственных сущностей. Привязка
существующей Local-модели появляется только по server `bind_existing` и
`owner_bindings`: ключ не копируется и новый бюджет не создаётся. Private
Memory публикуется в workspace только по отдельной кнопке и после явного
согласия с аудиторией. Consensus/routine proposals принимают минимум два
реальных contribution/outcome ID; браузер не создаёт голоса, результаты,
оценки или разрешение автоматизации.

Публикация в SF Social — два разных запроса: подготовка серверного снимка и
подтверждённая публикация. Предпросмотр показывает только разрешённые публичные
поля, hashes и source revision, не raw model response/private Memory/ключи.
После просмотра пользователь выбирает видимость (исходно «Только я») и сам
подтверждает постоянный снимок. Publish отправляет точные source/hash/revision
из prepare, а не из редактируемых полей. Неопределённый ответ не считается
успехом; ключ повторной отправки сохраняется.

Добавлены `test_agent_world_domain_gateway.py`: реальный scoped ModelService,
domain facade, state/evidence contracts и SF Chat adapter при изолированных
in-memory границах провайдера, canonical queue и social store. Проверены
ordinary-user history, отзыв сессии/owner/runtime, запрет глобальных ключей,
существующий бюджет, exact queue identity, scope/body/query tampering,
действующие JSON/Origin/CSRF методы Handler, read-only история после истечения
доступа, публикационный whitelist и обязательное отдельное подтверждение.
Найденные свежими тестами дефекты owner-binding revocation и backtest callback
исправлены основным исполнителем и перепроверены, без ослабления assertions.

Итоговые focused результаты этого дополнения:

- UI/helper/DOM-event contracts: **171 passed**.
- Domain/model-chat/publication gateway contracts: **93 passed**.
- Disposable actual HTTPServer/Handler contracts: **36 passed**.
- `node --check`, Python compilation и scoped `git diff --check`: **PASS**.

Actual HTTP no-write check по-прежнему сравнивает файлы и SQL rows до/после
GET/open-chat: не скрывает инициализацию storage предварительным fixture seed.
Разрешена только одна обязательная audit-запись восьми Development feature flags.
Reader history не означает право на NT/Desktop owner runtime либо mutation.

Это не credentialed provider/browser acceptance, не full regression и не
Canary/Production readiness. Эти проверки, current/Context Pack и общий Git
closeout выполняет основной исполнитель. Все перечисленные изменения
оставлены без stage/commit; версия этой записью не изменяется.

### Финальная проверка Preview-панелей и publication flag

Добавлены actual HTTP-проверки всех 13 известных `domains/*` Preview-панелей:
ответ содержит только explanatory `enabled=false`, `synthetic=true`, пустые
items/actions/source candidates и выключенный social publishing. Доступ всё
ещё требует Owner Preview control cookie. Запрещённые domain POST не открывают
SQLite, не создают файлы и не входят в Local/model/provider adapters. Неизвестный
domain не превращается в разрешённый инструмент.

Отдельные проверки отключают `AI_SOCIAL_PUBLISH_V1` на environment- и
workspace-уровне, оставляя Task Graph включённым: публикационные GET, prepare
и publish отклоняются до вызова сервиса. Флаг включается только восьмым явно
разрешённым Development opt-in flag; Preview/Canary/Production не наследуют grant.

Итог повторного запуска: **142 passed** — actual HTTP **47** и domain gateway
**95**, без skipped; Python compilation и scoped diff-check **PASS**.
UI остаётся неизменным после **171 PASS**. PostgreSQL-кластер этим slice не
затрагивался; его независимый повтор ведёт основной исполнитель.

### Исправление единой AI-навигации после Local browser review

Воспроизведено расхождение: AI Центр был разрешён для текущего workspace,
но первичный `/api/auth/status` возвращал выключенную навигацию. Bootstrap
ещё не сохранял проверенный context в Handler, а navigation adapter читал
именно его. Основной исполнитель исправил передачу свежего context с
восстановлением прежнего значения в `finally`; новые проверки выполняют
настоящие HTTP bootstrap/overview и не подменяют navigation DTO.

Rail объединяется в один «AI Центр» только при точном server
`agent_world.enabled === true`. Отсутствующий, выключенный или некорректный
grant сохраняет существующие Legacy/locked/student правила. Старые закладки
`ai-lab.html` и `ai-agents.html` в разрешённом workspace переходят на
«Обзор»/«Агенты» внутри AI Центра; сам AI Центр не перенаправляется.
После перенаправления bootstrap не запускает старую страницу. Дизайн rail,
Auth/Device Confirmation и прочие пункты навигации не менялись.

Проверки этого дополнения: navigation/actual bootstrap **22 passed**;
совместный UI + Aurora + navigation запуск **254 passed**, без skipped;
`node --check`, Python compilation и scoped diff-check — **PASS**.
Browser QA, общий cache-token bump, current/Context Pack, общий commit/PR и
полный regression принадлежат основному исполнителю. Этот scoped результат
не означает release/deploy или завершённую credentialed provider acceptance.
