# Community and SF Chat — Development Vertical Slice

Release title: StratForge Community + unified SF Chat
Change summary: В изолированной Community-ветке создана внутренняя социальная
сеть и единая human/AI chat-оболочка без второго Community messenger и без
изменения существующего AI Orchestrator authority.
Source branch: `codex/community-social-network`
Checkpoint commit: `d5a77e9392e1`
Core implementation commit: `a2cc5e72a610d22605a1af0aaacfcb03341456d5`
Latest owner-review UI commit: `55523872f2860a3a21489debe01e160207b0b288`
Latest SF Chat presentation commit: `8844421cbaefa9abc1888d36c5d4274aa41bd53c`
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
- Browser QA выполнена в изолированном Development runtime на порту `8875`:
  desktop `1569x912`/`1280x720`, tablet `1024x768` и mobile `390x844` без
  document-level horizontal overflow; center/wall scroll independently and
  console warnings/errors are absent. Последний orbital-launch delta повторно
  проверен на desktop `1569x912` и mobile `390x844`, включая launcher → shell,
  mobile conversation drawer и отсутствие horizontal overflow.
  Синтетические LOCAL QA PREVIEW записи находятся только в изолированном
  runtime state, явно помечены и не являются торговыми результатами.

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

- Focused Community/SF Chat/storage/UI contract suite: `106 passed`.
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
