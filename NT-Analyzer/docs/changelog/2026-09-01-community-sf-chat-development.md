# Community and SF Chat — Development Vertical Slice

Release title: StratForge Community + unified SF Chat
Change summary: В изолированной Community-ветке создана внутренняя социальная
сеть и единая human/AI chat-оболочка без второго Community messenger и без
изменения существующего AI Orchestrator authority.
Source branch: `codex/community-social-network`
Checkpoint commit: `d5a77e9392e1`
Core implementation commit: `a2cc5e72a610d22605a1af0aaacfcb03341456d5`
Latest owner-review UI commit: `55523872f2860a3a21489debe01e160207b0b288`
Latest SF Chat presentation commit: `27b4de3d65eb4e1d753302b90fec45c90a51765a`
Approved-reference UI baseline commit: `f475568475290df2161da9b6fe5da3b73342939b`
Pull request: [#270](https://github.com/OMNOM-111/NT-Analyzer/pull/270)
Verification result: `PASS` for Development automated gates and isolated local
browser QA; credentialed PostgreSQL, owner visual acceptance, PR/CI and release
gates remain explicitly separate.
Release impact: Development only; Canary/Production не изменялись.

## Пользовательский результат

- Community получила API-backed профили/privacy, рекомендации и подписки,
  cursor feed/search, изображения, реакции, комментарии, bookmarks, blocks,
  жалобы, owner moderation и soft delete. Старые workspace Channels сохранены.
- Кнопка профиля `Message` и глобальный launcher используют один SF Chat human
  conversation ID, единые history/unread/read/attachments/block rules.
- Существующие AI-диалоги остаются в прежнем Orchestrator storage/API и
  отображаются через ту же SF Chat shell без изменения AI authority.
- Нижнее уведомление группирует unread сообщения одного диалога, показывает
  время и deep-link; закрытие карточки не отмечает переписку прочитанной.
- Завершённый Demo/Backtest job можно опубликовать только через повторную
  server-side ownership проверку и immutable allowlisted SHA-256 snapshot.
  Клиент не может подменить P&L; raw trades/bars/source/path не публикуются.

## Owner-reference visual refinement

- Большой Community hero удалён. Рабочая область стала плотной трёхзонной
  композицией: компактный social dock, доминирующая центральная лента и
  полноценная profile/wall-панель с публикациями и закладками.
- Левая social-навигация сокращена до поиска людей и компактного списка
  участников; лишние view-иконки удалены из утверждённой композиции.
- Composer сокращён до avatar/input и явных действий. Strategy, Backtest,
  Result и Chart отображаются как rich StratForge objects с типом, источником,
  метриками, семантикой P&L/drawdown и безопасным chart preview, когда серия
  действительно присутствует в публичном snapshot.
- Поиск принимает имя, `@username` и `#hashtag`; сортировка по времени и
  релевантности, profile wall и bookmarks проверены через реальный UI/API.
- Действия публикации получили явные Like/Comments/Share/Bookmark labels и
  SVG-иконки с deep-link для share; центральная лента и wall прокручиваются
  независимо. Gear открывает компактный visibility-dialog, а не общий drawer.
- Глобальный SF Chat launcher получил минималистичный космический стиль:
  компактная тёмная карточка, SF mark, тонкая cyan-граница и restrained orbit
  accent без изменения human/AI chat backend.
- SF Chat shell получил presentation-only Orbital Glass pass: на desktop —
  полноценная glass/cosmic-панель с постоянным rail диалогов слева, активным
  разговором справа, различимыми human/AI bubbles, компактным header и нижним
  composer; на mobile rail остаётся безопасным выдвижным drawer. Existing
  history, unread/read, attachments, Human/AI routing and Orchestrator API
  остаются прежними.
- Финальный sidebar pass добавляет поиск по реальным conversation metadata,
  счётчик, действующий existing AI create-flow и фильтры `Все` /
  `Закреплённые` / `Недавние`. Никаких mock-диалогов, нового chat storage или
  изменения human/AI routing не добавлено.
- Финальный orbital-launch polish сохраняет эту полноценную shell, но больше
  не накладывает её на launcher: desktop-панель раскрывается из нижней правой
  точки, соединяется с launcher тонкой световой траекторией и оставляет под
  собой отдельный rail. В этом rail одна реальная сгруппированная карточка
  уведомления остаётся доступной рядом с launcher; на mobile shell остаётся
  полноэкранной, а декоративная траектория не показывается. Community layout,
  notification data/read semantics и chat routing не менялись.
- Последний messenger pass перестраивает только presentation сообщения:
  исходящие user messages остаются компактными правыми bubbles, а входящие
  AI/human messages получают отдельный левый avatar и glass bubble. Реальные
  rating/fulfillment/feedback controls сохранены, но перенесены в компактный
  disclosure `Детали ответа`; task status стал вторичным. Усилен векторный SF
  mark, cosmic depth, launcher trajectory, selected conversation и clean
  composer без новых функций, mock conversations или изменения данных.
- Browser QA выполнена в изолированном Development runtime на порту `8875`:
  desktop `1569x912`/`1280x720`, tablet `1024x768` и mobile `390x844` без
  document-level horizontal overflow; center/wall scroll independently and
  console warnings/errors are absent. Последний orbital-launch delta повторно
  проверен на desktop `1569x912` и mobile `390x844`, включая launcher → shell,
  mobile conversation drawer и отсутствие horizontal overflow.
  Синтетические LOCAL QA PREVIEW записи находятся только в изолированном
  runtime state, явно помечены и не являются торговыми результатами.
  Последний messenger delta отдельно проверен на desktop `1569x912` и mobile
  `390x844`: disclosure открывает реальные controls, mobile drawer содержит
  только действующие Search/create-flow/filters, console и horizontal overflow
  равны нулю. Визуальная owner acceptance остаётся отдельным ручным решением.

## Final design-audit pass — honest header state, real day marks

Финальный дизайн-аудит сравнил работающий `8875` с owner-reference изображениями
и нашёл три расхождения, каждое из которых нарушало собственное правило задачи
«не использовать fake UI». Пройдены только presentation layer и UI bindings;
backend, Community API, storage, PostgreSQL, ACL, Orchestrator, Backtest,
Connector, `МИР АГЕНТОВ` и trading/payment logic не изменялись.

- Имя активного облика чата перестало быть CSS-литералом. `.orch-head-name::after`
  и `#orch-skin-btn::after` печатали строку `Orbital Glass` в двух местах header,
  тогда как фактически применённый skin был `forge` («Forge»), и подпись не
  менялась ни при одном из шести обликов. Оба места стали реальными элементами
  (`.orch-head-skin`, `.orch-skin-label`), которые `orchApplySkin` заполняет
  названием действительно применённого облика; проверено переключением
  Forge → Terminal → Forge.
- Разделитель дня стал настоящим. `.sf-chat-panel .orch-msgs::before` печатал
  фиксированное `Сегодня` над каждым диалогом независимо от дат сообщений —
  в основном чате он стоял над перепиской от 01 сентября. Разделители теперь
  строятся из `timestamp_utc` (`orchDayKey`/`orchDayLabel`/`orchMessagesHtml`),
  бакетятся в той же зоне, в которой печатает `orchFmtTime`, и дают
  `Сегодня` / `Вчера` / дату; оптимистичные отправки открывают новый день через
  `orchAppendMessage`.
- Карточка уведомления вернулась в единую cyan/blue систему. Она стоит прямо над
  SF Chat launcher, но несла фиолетовые border, glow, action-gradient и
  count-pill — второй, ничем не связанный акцент вместо Orbital Glass. Позиция,
  группировка `+N`, скрытие при открытом чате и mobile-вариант сохранены без
  изменений.
- Composer получил честную строку `SF Chat может ошибаться. Проверяйте важную
  информацию.` Она показывается только в AI-диалогах: личная переписка человека
  с человеком не является ответом модели и предупреждение не несёт.

Намеренно сохранено: popup-геометрия shell и launcher, orbit link, desktop
conversation rail, модель bubbles, вторичные AI-controls внутри disclosure,
Community-архитектура (dock, feed, profile/wall, rich cards, independent scroll)
и все честные empty state. Реальные аватары агентов оставлены вместо SF-знака в
bubble: это действующие данные, а не декорация.

## Pre-acceptance technical and UX hardening

Профилирование interaction path на работающем `8875` и read-only аудит
persistence. Продуктовая концепция и набор функций не менялись. Backtest,
Connector, trading, payments, AI Orchestrator logic, `МИР АГЕНТОВ` и Production
не затронуты.

### Компактный desktop shell

- Desktop popup был `1040x740` — 48% экрана `1600x1000`. Теперь `700x620`, 27%:
  за чатом виден весь command center, launcher остаётся свободен.
- Причина, по которой прежние правки размера не действовали: два блока
  `@media (min-width: 1024px)` задавали `width`/`height`/offsets для
  `.sf-chat-panel`, и побеждал более поздний. Геометрия desktop сведена в один
  блок (пункт 9 — консолидация только SF Chat-правил, ради стабильности
  геометрии, а не ради чистоты).
- Mobile остался full-screen `375x812`, drawer и composer без изменений.

### Реальные причины задержек

- Shell анимировал `filter: blur(4px) -> 0` за 320 мс и держал
  `will-change: filter`. Полноэкранный blur заставлял композитор
  перерастрировать всю панель каждый кадр вместе с glass-бабблами внутри.
  Анимация blur убрана, движение launcher → shell сохранено.
- `transform` длился 420 мс. Теперь `.22s`, `opacity` `.15s`.
- Закрытие держало невидимую панель в DOM `460` мс при самой длинной анимации
  `220` мс. Таймер согласован с анимацией и сбрасывается при повторном открытии.
- Первые два запроса при открытии выполнялись последовательно; список диалогов
  и открытая переписка независимы и теперь идут параллельно.
- Боковой список перерисовывался целиком каждые 3 с независимо от изменений —
  `4` полные пересборки за `10` с простоя. Идентичная разметка больше не
  переписывается: `0` пересборок за `10` с.
- На каждый рендер вешалось `4N` слушателей (N — число диалогов). Заменено одним
  делегированным обработчиком на весь список.
- Поиск перерисовывал список на каждый символ. Один рендер на паузу набора.
- Число строк в DOM ограничено `300` с честной подписью «Показаны первые 300 из
  N»; счётчик над списком продолжает показывать реальные visible/total.

### Измерения в DEV (desktop `1600x1000`)

| Действие | До | После |
| --- | --- | --- |
| launcher click → shell settled | `443–467` мс | `241–272` мс |
| close → panel hidden | `476` мс | `248–262` мс |
| first history render (повторное открытие) | `1–2` мс | `70–101` мс* |
| сетевые запросы при открытии | 2 последовательных | 2 параллельных |
| пересборки списка за 10 с простоя | `4` | `0` |

* история теперь рендерится после параллельной загрузки, а не показывается из
предыдущего DOM до неё; это честное время до актуального содержимого.

При `2000` диалогов (in-page нагрузочный прогон через реальный render path):

| Действие | До | После |
| --- | --- | --- |
| фильтр «Все» | `1220` мс | `149` мс |
| фильтр «Закреплённые» | `79` мс | `49` мс |
| набор символа в поиске | `1230` мс блокировки | `0` мс |
| узлов в DOM списка | `30 080` | ограничено `300` строками |

### Persistence: найденная и исправленная квадратичность

- `list_conversations` вызывал `_public_conversation` для каждого диалога, а тот
  — `_conversation_messages`, сканирующий **все** сообщения. Итог —
  O(диалоги × сообщения). `_read_row` так же сканировал все read-строки.
- Сообщения группируются по диалогу и read-строки индексируются по
  `(conversation, profile)` один раз за вызов. Публичный payload не изменился.
- Изолированный замер (временный data root, без БД и без DEV state):

| Объём | `list_conversations` до | после |
| --- | --- | --- |
| 5 диалогов / 200 сообщений | `17.5` мс | `17.0` мс |
| 50 / 5 000 | `172` мс | `66` мс |
| 500 / 25 000 | `5 873` мс | `310` мс |
| 2 000 / 50 000 (потолок документа) | `44 445` мс | `659` мс |

- Регрессия закреплена детерминированно:
  `test_listing_conversations_does_not_rescan_messages_per_conversation`
  считает пер-диалоговые сканы, а не время.

### Read-only аудит схемы: проблем не найдено

Проверены `conversations`, `participants`, `messages`, `reads`, `follows`,
`posts`, `reactions`, `comments`, `bookmarks`, `moderation_reports`.
Индексы, FK, uniqueness/idempotency и RLS соответствуют запросам:
`sf_chat_messages(conversation_id, seq DESC) WHERE deleted_at IS NULL` для
пагинации истории, `UNIQUE(conversation_id, seq)` для порядка, частичный
уникальный индекс по `idempotency_key_hash`, `sf_chat_participants(profile_id,
conversation_id)` для «мои диалоги», `UNIQUE(conversation_id, profile_id)` в
`sf_chat_reads` для unread за O(1), `UNIQUE(post_id, profile_id)` в reactions и
bookmarks, `UNIQUE(follower, target)` плюс `(target, created_at DESC)` в follows,
feed/author/object индексы и GIN по документу постов. FORCE RLS включён на всех
таблицах. Отсутствующих индексов, FK и ограничений уникальности не обнаружено;
разрушительных миграций не выполнялось.

### Оставшийся технический риск

`_load()` читает **один** документ со всеми диалогами, сообщениями и
read-строками всех пользователей на каждый запрос — и в DEV (JSON), и в
Production (`storage_router.read_document`). `_save()` ограничивает его 5 000
диалогов и 50 000 сообщений (~19.5 МБ). После снятия квадратичности стоимость
линейна и упирается в разбор всего документа: `659` мс на потолке. Открытая
панель опрашивает два эндпоинта каждые 3 с, поэтому при многих одновременных
пользователях это станет ограничением. Устранение требует перевода read path на
уже существующие и корректно проиндексированные relational mirrors — это замена
модели хранения, а не минимальная правка, и она сознательно **не** выполнена в
рамках pre-acceptance прохода.

## Production read path moved onto the relational mirrors

Единственный оставшийся scalability risk закрыт: production authoritative reads
SF Chat больше не читают глобальный документ. Функциональность и дизайн
Community/SF Chat не менялись; Backtest, Connector, trading, payments, AI
Orchestrator logic, `МИР АГЕНТОВ` и Production не затронуты. Нового storage не
создавалось, миграции не выполнялись — используются уже существующие таблицы,
индексы и FORCE RLS из `0021`.

### Что было

Каждый запрос SF Chat читал **два** глобальных документа:

- `sf_chat._load()` — все диалоги, сообщения и read-строки всех пользователей;
- `community.chat_public_profiles` → `community._load()` — все профили, посты,
  комментарии, реакции и подписки всех пользователей.

Хуже того, `community.chat_identity` не только читал, но и **перезаписывал**
документ Community на каждом запросе, включая каждый tick опроса.

### Что стало

- `SFChatRepository` и `CommunityRepository` (`production_storage/core.py`)
  выполняют индексные чтения по `sf_chat_*` / `sf_community_*` под тем же
  service scope и теми же RLS-политиками.
- Список диалогов — один statement: строка, её read-указатель, последнее
  сообщение и unread приходят вместе через `LATERAL`, без запроса на диалог.
- Keyset-пагинация по `(updated_at, conversation_id)`. Offset отвергнут:
  диалог, поднявшийся наверх между страницами, сдвигает все последующие строки.
- История — обратный проход по `seq` на
  `sf_chat_messages(conversation_id, seq DESC) WHERE deleted_at IS NULL`,
  поэтому старая страница стоит столько же, сколько свежая.
- Опрос — отдельный `/api/sf-chat/state`: фиксированная change-signature плюс
  ограниченный список только тех диалогов, где действительно есть непрочитанное.
- `mark_read` при уже прочитанном диалоге отвечает по двум индексным чтениям и
  не трогает документ; запись через документ остаётся, когда есть что двигать.
- `chat_identity` в Production резолвится одним индексным чтением и ничего не
  пишет, пока учётная запись реально не изменила наблюдаемое поле.
- Документное хранилище сохранено как DEV/fallback/import-совместимость и
  остаётся авторитетным **писателем**: mirrors синхронизируются в той же
  транзакции, поэтому реляционные строки несут ровно тот документ, что и JSON.

### Единая проекция

`_conversation_payload` и `_profile_payload` — единственные места, где строится
публичная форма; оба пути (документ и mirrors) передают в них только те факты,
источник которых различается. Тест
`test_relational_and_document_projections_are_identical` сравнивает результаты
двух путей на одних данных, поэтому расхождение падает в тестах, а не тихо
уезжает в Production. Сортировка документного пути получила тот же tie-breaker
по `conversation_id`, что и keyset.

### Измерения

Statements и payload измерены на реальном коде через
`tests/_relational_fake`, который повторяет семантику SQL (порядок, keyset,
предикат участия, правило unread). Latency принадлежит живому PostgreSQL и
здесь **не измерялась** — см. раздел о непокрытом.

| Объём | statements: открытие / опрос / стр. истории / переключение | payload открытия | payload опроса |
| --- | --- | --- | --- |
| 5 диалогов / 200 сообщений | 4 / 2 / 4 / 4 | 5.1 КБ | 0.9 КБ |
| 50 / 5 000 | 4 / 2 / 4 / 4 | 29.9 КБ | 7.5 КБ |
| 500 / 25 000 | 4 / 2 / 4 / 4 | 30.0 КБ | 7.5 КБ |
| 2 000 / 50 000 | 4 / 2 / 4 / 4 | 30.1 КБ | 7.5 КБ |

Число statements постоянно на всех объёмах — N+1 отсутствует. Payload открытия
ограничен одной страницей, payload опроса — сигнатурой и лимитом в 50 строк
непрочитанного. `mark_read` на прочитанном диалоге — 2 statements и `advanced=0`.

Промежуточная итерация возвращала маркер на каждый диалог, и опрос при 2 000
диалогов весил `290 КБ` — тяжелее страницы, которую он должен был заменить. Это
исправлено до фиксированных `7.5 КБ`; свойство закреплено тестом
`test_idle_polling_payload_stays_flat_as_the_rail_grows`.

Для сравнения, документный путь (остаётся в DEV) на тех же объёмах:
`2.3 / 93.6 / 386.4 / 963.3` мс на один `list_conversations`.

### Чего эти измерения не покрывают

На этой машине нет PostgreSQL: ни сервера, ни Docker/podman, ни acceptance DSN
(`psycopg` установлен, слушателя на 5432 нет). Поэтому **latency conversation
list, first/next history page и поведение нескольких одновременных сессий
против реальной БД не измерены**. Написан отдельный acceptance-набор
`tests/test_sf_chat_relational_postgres.py` (9 тестов) по существующей
конвенции репозитория: он пропускается без
`STRATFORGE_TEST_POSTGRES_ADMIN_URL` / `STRATFORGE_TEST_POSTGRES_URL` и
проверяет keyset-обход без повторов, unread и последнее сообщение одним
statement, обратную пагинацию истории без пересечений, `EXPLAIN` без
`Seq Scan on sf_chat_messages`, индексный резолв identity, отказ
не-участнику и восемь одновременных читателей. Запустить его можно, передав
DSN; пока он не выполнялся ни разу.

### Fail-closed

Недоступность репозитория поднимает `503` и никогда не отвечает из документа —
`test_repository_failure_fails_closed_instead_of_falling_back`. Не-участник и
несуществующий диалог дают один и тот же `404`, без оракула существования.

## Storage, migration and security

- Development использует атомарные local documents. Explicit Canary/Production
  используют только PostgreSQL repositories `community` и `sf_chat`; outage
  возвращает 503 и никогда не включает local JSON fallback.
- `0020` расширяет repository allowlist. Expand-only `0021` добавляет 12
  relational mirrors с FK, индексами и FORCE RLS; запись document и mirrors
  выполняется в одной транзакции.
- `tools/community_storage_migration.py` по умолчанию делает dry-run, валидирует
  graph/ACL/sequence, строит checksum plan, требует backup и exact confirmation,
  идемпотентно объединяет данные и не удаляет legacy JSON.
- Attachments ограничены PNG/JPEG/WebP, 3 файлами по 2 МБ; MIME сверяется с file
  magic. API применяет session capability, CSRF, global rate limit,
  idempotency, pagination, privacy и non-enumerating ACL.

## Verification and honest remaining scope

- Relational read-path pass: focused Community/SF Chat/storage/UI contract suite
  `106 passed, 21 skipped` (пропуски — acceptance-тесты PostgreSQL без DSN);
  полная регрессия `2523 passed, 42 skipped` за `335.76s`.
- Новые тесты: `tests/test_sf_chat_relational.py` (16) — эквивалентность двух
  проекций, отсутствие глобального чтения документа в hot path, постоянное
  число statements, keyset-обход без повторов и пропусков, ограниченный payload
  опроса, изоляция одновременных читателей, fail-closed при отказе репозитория;
  `tests/test_sf_chat_relational_postgres.py` (9) — acceptance против живой
  PostgreSQL, пропускается без DSN.
- `node --check`, `py_compile`, `git diff --check`, External GPT Context
  validator и `pre_release_check.py` (474 bundle files): PASS.
- Известное окружение: на этой рабочей станции полный прогон помечает
  `development/durable/nt_analyzer.sqlite3` в live-data guard. Проверено на
  чистом HEAD без изменений этой задачи — поведение идентичное (`2507 passed`,
  тот же guard), то есть предшествующее и не связанное с этой работой; на CI
  live-data root отсутствует и guard проходит.

- Hardening pass: focused Community/SF Chat/storage/UI contract suite
  `90 passed`; полная регрессия `2507 passed, 33 skipped` за `437.20s`.
- Browser QA после правок: desktop `1600x1000` (panel `700x620`, 27% экрана,
  launcher свободен, `scrollWidth 1590 < 1600`), Community `1600x1000`,
  mobile `375x812` (`scrollWidth 375 = 375`, drawer открывается и закрывается).
  Console errors и warnings равны нулю.
- Сценарии устойчивости: 10 быстрых циклов открыть/закрыть, закрытие во время
  загрузки, поиск → очистка → фильтр → выбор диалога, Community профиль →
  «Сообщение» → SF Chat. Результат: одна панель, один launcher, нет зависших
  overlay, нет дублей сообщений, счётчик сообщений стабилен при работающем
  3-секундном опросе, ноль console-ошибок.

- Design-audit pass: focused Community/SF Chat/storage/UI contract suite
  `89 passed`; полная регрессия `2506 passed, 33 skipped` за `424.92s`.
- Новый contract-тест
  `test_sf_chat_header_chip_and_day_marks_render_real_state_not_css_literals`
  закрывает возврат обеих подписей в CSS `content`.
- Browser QA этого прохода в Development runtime `8875`: desktop `1600x1000`
  (SF Chat panel `1040x740`, launcher не перекрыт, `scrollWidth 1590 < 1600`),
  desktop `1120x780`, Community `1600x1000` и mobile `375x812`
  (`scrollWidth 375 = 375`). Console errors и warnings равны нулю на всех
  проверенных экранах; разделители `Вчера`/`Сегодня` и disclaimer подтверждены
  из DOM, а не только визуально.

- Focused Community/SF Chat/storage/UI contract suite: `106 passed`.
- Latest presentation-focused Community/SF Chat/UI suite: `101 passed`.
- Full repository regression: `2503 passed, 35 skipped` in `363.53s`.
- Python/JavaScript syntax, `git diff --check`, repository-wide Markdown scan
  and External GPT Context Pack validator: PASS.
- Git-indexed `pre_release_check.py`: PASS (`474` bundle files; in-bundle
  static scan, runtime reads, Python compile and shipped JavaScript syntax).
- Pull request #270 required CI reached `5/5 PASS` after the final sidebar pass
  at the code-and-record head `f464d069502a93c3d44c7de35c0cba3a2ba492e4`;
  the same required gate remains mandatory for the later orbital-launch head.
  Merge remains an explicit owner decision.
- Real PostgreSQL tests require explicit acceptance DSNs and remain separately
  reported when unavailable; no database or server was mutated by this task.
- Strategy metadata, Chart snapshot and Live result adapters remain disabled,
  not simulated. Owner visual acceptance and Canary/Production are separate
  gates.
- Backtest/Connector, market data, trading and future `МИР АГЕНТОВ` were not
  changed. Any integration change starts a new immutable artifact cycle.
