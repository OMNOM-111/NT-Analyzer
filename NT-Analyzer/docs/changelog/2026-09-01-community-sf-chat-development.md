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

## Community information architecture and the registration milestone

Закреплена модель навигации `LEFT = discovery / CENTER = current context /
RIGHT = me` и добавлена системная запись о регистрации. Rich post cards, social
dock, структура Recommendation, SF Chat, PostgreSQL/RLS, Backtest, Connector и
Orchestrator не переделывались.

### Профиль участника открывается в центре, а не поверх Community

- Раньше `openProfile` рисовал профиль в `#community-profile-modal` —
  полноэкранный overlay `position: fixed; inset: 0; z-index: 110` с backdrop и
  `body.community-modal-open { overflow: hidden }`. Он перекрывал всё
  приложение, включая правую колонку.
- Теперь центральная область переключается на стену участника
  (`#community-profile-view`) с явным возвратом `← Recommendation`, который
  называет ту ленту, из которой пришёл читатель. Overlay и его разметка
  удалены; Escape и кнопка возврата ведут в поток.
- Aurora route не менялся: это навигация внутри Community, как уже было
  сделано для `community-channels-view`.

### Правая колонка всегда принадлежит текущему пользователю

Аудит подтвердил, что `loadWall()` читает `STATE.viewer` и запрашивает
`communityV2Profile(viewer.profile_id)`; она никогда не переключалась на чужой
профиль. Раньше это работало потому, что чужой профиль открывался поверх всего;
теперь, когда центр меняет контекст, инвариант зафиксирован контрактным тестом.

### Системная запись о регистрации

Аудит показал, что такого объекта в backend **не существовало** — ни поля, ни
поста, ни миграции. Реализовано канонично на сервере: `_registration_milestone`
выводит запись из собственных полей профиля и отдаётся в `social_profile` как
`registration`.

Запись **выводится**, а не хранится отдельным постом. Это делает все требования
истинными по построению: она существует ровно один раз, её нельзя удалить или
изменить, дату невозможно переписать, а повторный login, перезапуск, импорт или
миграция не могут создать второй экземпляр — дублировать просто нечего.
Никакой JavaScript её не выдумывает: страница рисует только то, что вернул
сервер.

Содержимое строго фактическое:

- `registered_at_utc` — `joined_at_utc` профиля (иначе `created_at_utc`);
- `activated_at_utc` — только если момент активации действительно отличается от
  регистрации, иначе поле пустое и в интерфейсе не рисуется;
- `account_status` — **только на собственном профиле**. Чужая стена показывает
  дату регистрации, которая и так публична, и ничего о состоянии чужого
  аккаунта.

Карточка стоит первой на стене — и на своей (правая колонка), и на чужой
(центр), — перед обычными публикациями. Она компактная, в общей Orbital Glass
эстетике, с системным знаком и статус-строкой, без Like/Share: это часть
истории продукта, а не социальный пост. В `Закладках` она не показывается —
там чужие публикации, а не история этого профиля.

### Messaging

`Написать` на чужом профиле по-прежнему открывает единый SF Chat через
`sfChatStartConversation` + `UI.openSFChat`; отдельного Community Messenger нет.

## DEV contour recovery and Community browser QA (scenarios A-D)

### Восстановленный DEV-контур `8875`

Прежняя конфигурация восстановлена по свидетельствам самого runtime, без
подбора. Сервер публикует активный data root в `.stratforge-active-root.json`
(`app/data_root_guard.py`), и файл в контуре называл `pid 25392` — ровно тот
процесс, который обслуживал `8875` до перезапуска:

- `STRATFORGE_DEVELOPMENT_DATA_ROOT` = `C:\\Users\\dimon\\AppData\\Local\\StratForge\\dev-contours\\community-sf-chat-pr270-d3fa41bc`
- `NTA_MARKET_DATA_IPC_PORT` = `18875` — из `runtime/market_data_ipc_token.json`
  того же контура (`tcp_port: 18875`, `bind: 127.0.0.1`), при `DEFAULT_TCP_PORT`
  равном `18765`
- `DEPLOYMENT_ENV` / `STRATFORGE_ENV` = `development`
- порт `8875`, origin `http://127.0.0.1:8875`
- `STRATFORGE_DATA_ROOT` и `NTA_DATA_ROOT` **не заданы** — это production-root
- `NTA_TELEGRAM_CHAT_ID` не задавался: контур уже содержит подтверждённого
  владельца (`primary_owner_id() = 999`, `status active`), и localhost-байпас
  штатно резолвит его через `primary_owner()`. `ensure_owner` и Telegram-
  подтверждение не обходились, фиктивный владелец не создавался
- instance/database/queue/object-storage IDs в Development не требуются и берутся
  из безопасных значений по умолчанию (`development-sqlite`,
  `development-local-worker`, `development-files`), Telegram bot —
  `development-disabled`

Побочно удалён ложный маркер `.stratforge-active-root.json`, который прошлые
перезапуски оставили в `NT-Analyzer/data/development` — заброшенный root без
`accounts.dpapi`, способный ввести обслуживающие инструменты в заблуждение.

### Две ошибки, найденные именно прогоном по реальным данным

- **Дата активации была выдумкой.** Milestone брал `created_at_utc` профиля как
  «дату активации», если она отличалась от `joined_at_utc`. На реальном профиле
  это дало `2 сент. 09:52` при регистрации `2 сент. 03:19`: `created_at_utc`
  строки профиля — это бухгалтерия, он сдвигается при перезаписи строки, и
  никакой активацией не является. Каноническая активация — `approved_at_utc`
  аккаунта, и только когда она действительно отличается от `created_at_utc`
  аккаунта. У владельца они совпадают, поэтому строка активации теперь
  отсутствует — как и должно быть.
- **`Написать` теряло контекст Community.** `startMessage` вызывал
  `closeProfile()` — правильно, пока профиль был overlay, который иначе остался
  бы за чатом. После переноса профиля в центр это выбрасывало читателя обратно
  в ленту. Вызов удалён: стена остаётся на месте и во время чата, и после его
  закрытия.

### Результаты сценариев

- **A** — Recommendation → Elena Vaskos: центр переключается на её стену,
  `← Recommendation` присутствует, лента и composer скрыты, **правая колонка не
  меняется**; возврат восстанавливает Recommendation.
- **B** — собственный профиль: milestone присутствует, идёт **первым** на стене
  (`H3 → community-milestone → …`), дата `1 сент., 20:19` соответствует
  `created_at_utc` аккаунта `2026-09-02T03:19:21Z`, статус `active`.
- **C** — чужой профиль: milestone Elena показывает её настоящую дату
  `2026-09-02T03:20:30Z`, `account_status` пуст, `is_self: false`; правая
  колонка остаётся текущим владельцем.
- **D** — `Написать` → открывается существующий диалог SF Chat «Elena Vaskos» в
  едином чате; после закрытия чата центр по-прежнему на стене Elena.

Дополнительно: milestone ровно один на обеих стенах и после reload; три
последовательных чтения дают идентичный объект; milestone не является постом
(его нет в `posts`, у него нет Like/Share и id для удаления); чужой
`account_status` не раскрывается; на чистой вкладке console errors и warnings
равны нулю; horizontal overflow равен нулю (`1785 = 1785`, `1600 = 1600`).

## PostgreSQL acceptance executed for the first time

Ранее пропускавшийся PostgreSQL-набор впервые выполнен против настоящей базы.

### Контур

Portable PostgreSQL **17.6** (binaries-only ZIP, `329 891 687` B, официальная
дистрибуция EnterpriseDB), распакован в изолированную папку acceptance-контура
вне репозитория, поднят в user space через `initdb`/`pg_ctl` на
`127.0.0.1:55432`, `listen_addresses = '127.0.0.1'`. Без Windows service, без
admin/UAC, полностью удаляемо. Роли и база созданы существующим
`deploy/testing/provision-test-postgres.sql`; заданы только
`STRATFORGE_TEST_POSTGRES_ADMIN_URL` и `STRATFORGE_TEST_POSTGRES_URL`.
Production DB/data root не использовались.

### Результат: 9/9 PASS

`tests/test_sf_chat_relational_postgres.py` — `9 passed`. Проверено на живой
базе: keyset-обход без повторов, unread и последнее сообщение одним statement,
обратная пагинация истории без пересечений, `EXPLAIN` без
`Seq Scan on sf_chat_messages`, индексный резолв identity, отказ не-участнику,
markers-only опрос, профили страницы одним statement, восемь одновременных
читателей.

Три дефекта были в самой фикстуре, не в продукте, и исправлены: сырые
соединения не выставляли `stratforge.service_scope`, из-за чего FORCE RLS
справедливо отклонял seed (исправлено установкой scope, а не выдачей
`BYPASSRLS` — защита осталась включённой); клиент создавался с
`production=True` и требовал TLS, которого у локального сервера нет; seed писал
документ без предварительного чтения, что запрещено оптимистической блокировкой.

### Реальные измерения latency (PostgreSQL 17.6, медиана из 7)

| Объём | conversation list | first history page | idle poll | unread | switch | 8 сессий |
| --- | --- | --- | --- | --- | --- | --- |
| 5 диалогов / 200 сообщений | `67.8` мс | `66.1` мс | `66.8` мс | `54.5` мс | `57.2` мс | `193.5` мс |
| 50 / 5 000 | `66.2` | `51.7` | `87.3` | `64.5` | `163.7` | `310.9` |
| 500 / 25 000 | `66.2` | `53.2` | `73.7` | `73.4` | `74.9` | `236.5` |
| 2 000 / 50 000 | `69.8` | `61.9` | `94.1` | `104.6` | `63.7` | `384.3` |

Вторая страница списка (`68.6` мс при 2 000) и вторая страница истории (`51.3`
мс) стоят столько же, сколько первые. `Seq Scan` по `sf_chat_messages`
отсутствует везде, кроме 200 сообщений, где планировщик закономерно
предпочитает его индексу на такой таблице.

### Главное наблюдение: latency упирается не в запросы

| Операция | медиана |
| --- | --- |
| `client.transaction()` + `SELECT 1` | `51.2` мс |
| голое `psycopg.connect` + `SELECT 1` | `44.6` мс |
| постоянное соединение, `SELECT 1` | `0.1` мс |

То есть ~`45` мс каждого замера — установка TCP-соединения и аутентификация:
`PostgresClient` открывает новое соединение на каждый вызов. Собственная работа
запросов — единицы миллисекунд и **не растёт** с объёмом: список диалогов при
2 000 диалогов стоит примерно `69.8 - 51.2 ≈ 19` мс сверх соединения. Connection
pooling — очевидный следующий шаг для production, но вслепую он здесь не
внедрялся.

### Два других PostgreSQL-набора: предсуществующий bit-rot

`tests/test_production_storage.py` (`10 failed, 2 passed`) и
`tests/test_production_workers.py` (`12 errors`) впервые выполнились и показали
собственную устаревшесть, не связанную с Community/SF Chat:

- workers: те же сырые соединения без `stratforge.service_scope` (12 ошибок);
- storage: `Auth user UUID is required during the identity transition` (8 раз) —
  фикстуры сеют пользователей без `user_uuid`; один тест требует TLS от
  локального DSN; `test_workspace_membership_upsert_defect` падает с
  `NameError: name 'core' is not defined` и вызывает `core.init_pool()` /
  `core._pool`, которых в текущем `production_storage/core.py` нет вовсе.

Ни один из этих файлов не менялся в этой задаче. Это отдельные подсистемы
(auth identity transition, production workers); чинить их здесь значило бы
расширить PR за его предмет. Зафиксировано как отдельная работа.

## Community profile derives from the existing StratForge account

Community не имеет собственной регистрации. Профиль создаётся при первом
обращении уже существующего аккаунта и наследует его данные. Отдельный
acceptance-пользователь не создавался; изолированный acceptance-контур приложения
свёрнут, чтобы не плодить третью локальную версию.

### Найденный дефект

На основном локальном checkout владелец зарегистрирован `2026-08-03T21:20:32Z`,
а Community-профилей там `0`. При первом заходе `_ensure_profile_in_doc`
проставлял `joined_at_utc = now`, и milestone показал бы **сегодняшнюю** дату
вместо августовской. Это ровно то, что ломает требование «registration milestone
берётся из существующего account registration date».

### Исправление

- `_account_registered_at()` читает `created_at_utc` аккаунта, и профиль при
  создании наследует именно её.
- Строка, созданная до того, как аккаунт был опрошен, чинится при следующем
  обращении — дата двигается только **назад**, к дате аккаунта, и только когда
  сохранённое значение позже. Поле зеркалит данные аккаунта, поэтому это
  починка, а не переписывание пользовательского содержимого.
- Для собственного профиля milestone берёт дату аккаунта как источник истины.

### Подтверждённые инварианты

Проверено на сценарии интеграции (аккаунт от 3 августа, профилей нет):

| Инвариант | Результат |
| --- | --- |
| существующий owner account автоматически получает Community profile | профиль создан при первом обращении |
| никакого второго registration flow внутри Community | в `community.html`/`community.js` нет ни одного signup/register элемента; `community.py` только читает `account_auth` (`find_active_user`, `user_uuid_for_legacy_id`, `avatar_file`) и никогда не создаёт пользователя |
| milestone берётся из account registration date | `2026-08-03T21:20:32Z`, а не дата первого захода |
| SF Chat использует ту же identity | `chat_identity().profile_id == ensure_social_profile().profile_id` |
| никаких duplicate users/profiles | после трёх циклов обращений с обеих поверхностей — `1` профиль на аккаунт |

Закреплено тестами `test_profile_inherits_the_existing_account_registration_date`,
`test_a_profile_stamped_before_the_account_was_consulted_is_repaired` и
`test_community_and_sf_chat_share_one_profile_for_one_account`.

## One composer, on your own wall, with real visibility

Публикация создаётся только на собственной стене. Раньше это можно было
сделать из двух мест: composer в центральной ленте и кнопка `+ Создать пост`
рядом с профилем.

- Composer убран из центральной колонки. `Recommendation` осталась
  читательской поверхностью: чтение, Like, Comment, Share, Bookmark, переход к
  автору или объекту.
- Дублирующая кнопка `+ Создать пост` удалена.
- Composer перенесён в правую колонку, порядок:
  `Профиль → Статистика → Публикации/Закладки → Composer → Registration
  milestone → публикации`. Статистика профиля, rich cards, milestone, SF Chat и
  принятая геометрия не менялись.
- Composer остаётся моим, даже когда в центре открыта чужая стена: правая
  колонка всегда принадлежит текущему пользователю.

### Видимость — серверный ACL, а не скрытая карточка

Добавлено значение `private` к существующему контракту (`network`,
`followers`); миграция `0022` расширяет CHECK на `sf_community_posts` —
expand-only, существующие строки остаются валидными, профильная видимость не
трогалась.

- `Публично` (`network`) — на своей стене и в Сообществе, может попасть в
  Recommendation.
- `Только на моей странице` (`private`) — остаётся на стене автора.
  `_post_visible` отказывает всем остальным, а `social_feed` исключает такие
  посты из Recommendation **и для самого автора**: иначе единственным, кто
  видит приватный пост в публичной ленте, оказался бы человек, которому проще
  всего решить, что пост публичный. Search использует тот же путь, поэтому
  приватная запись не всплывает и там.

Один объект публикации: `стена автора → visibility → пригодность для
Recommendation`. Копия для ленты не создаётся.

Composer не привязан жёстко к физическому пользователю: значение автора
передаётся как значение, а не как допущение, поэтому будущий company identity
не потребует переписывать путь публикации. Fake company flow не создавался.

## Product rename: «Сообщество» -> SF Link

Брендовая иерархия: **STRATFORGE** — платформа, **SF Link** — социальный слой,
**SF Chat** — мессенджер. Мессенджер намеренно остаётся `SF Chat`, а не
`SF Link Chat`.

Переименование выполнено **только в интерфейсе и документации**:

- sidebar: `SF Link`;
- `<title>` и заголовок страницы: `SF Link`;
- kicker страницы: «Социальный слой StratForge — лента, профили и каналы»;
- tooltip видимости: «Виден в SF Link и может попасть в Recommendation»;
- подтверждение публикации: «Опубликовано на вашей стене и в SF Link»;
- пустое состояние SF Chat: «Начните переписку из профиля участника в SF Link»;
- строка возможностей плана: `SF Link (социальный слой)` (идентификатор
  `community` не менялся);
- `mode-entry`, документы в приложении, `UI_API_MAP.md`, `UI_OPERATIONS.md`.

Рядом с заголовком SF Link теперь стоит знак SF — тот же монограммный знак,
что и у SF Chat: различает слои не он, а словесная часть бренда.

Намеренно **не** переименованы: маршруты `/api/community/*`, таблицы
`sf_community_*` и `sf_chat_*`, имена миграций, `data-page="community"`,
внутренние идентификаторы `community_*` и классы `community-*`. Это лишний риск
перед релизом; внутри код остаётся `Community`, пользователю показывается
`SF Link`.

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

- Browser QA pass: полная регрессия `2525 passed, 42 skipped` за `391.87s`;
  `node --check`, `py_compile`, `git diff --check`, External GPT Context
  validator и `pre_release_check.py` (474 files): PASS.
- Сценарии A-D выполнены на восстановленном контуре `8875` против реальных
  данных владельца (Elena Vaskos, Marcus Thorne, реальные профили и
  существующий диалог SF Chat). Console errors/warnings на чистой вкладке = 0,
  horizontal overflow = 0.

- Community IA pass: focused Community/UI contract suite и полная регрессия
  `2525 passed, 42 skipped` за `366.80s`. Новые тесты:
  `test_registration_milestone_is_derived_single_and_immutable`,
  `test_registration_milestone_reports_absent_facts_as_absent`, плюс
  расширенный `test_community_v2_and_unified_sf_chat_are_real_api_backed_surfaces`,
  который теперь запрещает возврат overlay и требует, чтобы правая колонка
  читала `viewer.profile_id`, а карточка регистрации приходила с сервера.
- `node --check`, `py_compile`, `git diff --check`, External GPT Context
  validator, `pre_release_check.py` (474 files): PASS.
- **Browser QA сценариев A–D не выполнена.** Перезапуск DEV-сервера в
  предыдущем проходе потерял окружение владельца: `NTA_TELEGRAM_CHAT_ID` и
  data-root не заданы ни в user, ни в machine environment, а единственный
  `accounts.dpapi` лежит в основном репозитории, а не в этом worktree. Поэтому
  `primary_owner_id()` равен 0 и Community/SF Chat отвечают `401`. Создать
  владельца в одноразовом data-root нельзя: `ensure_owner` намеренно требует
  подтверждение через Telegram, и этот контроль не обходился.
- Что проверено в браузере без сессии: структура (профильная секция и кнопка
  возврата присутствуют, overlay удалён, правая стена на месте), отсутствие
  horizontal overflow (`1110 < 1120`, `1600 = 1600`) и внешний вид
  `← Recommendation` и milestone-карточки в центре и в правой колонке на
  реальной разметке и реальном CSS. Console errors в этом состоянии —
  исключительно `401`/`connection refused` из-за отсутствующей сессии.

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
