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
