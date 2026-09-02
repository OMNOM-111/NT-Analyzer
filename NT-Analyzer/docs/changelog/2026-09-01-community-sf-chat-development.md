# Community and SF Chat — Development Vertical Slice

Release title: StratForge Community + unified SF Chat
Change summary: В изолированной Community-ветке создана внутренняя социальная
сеть и единая human/AI chat-оболочка без второго Community messenger и без
изменения существующего AI Orchestrator authority.
Source branch: `codex/community-social-network`
Checkpoint commit: `d5a77e9392e1`
Final implementation commit: `PENDING_GIT_CLOSEOUT`
Pull request: `PENDING_GIT_CLOSEOUT`
Verification result: `PASS` for Development automated gates; credentialed
PostgreSQL, manual visual, PR/CI and release gates remain explicitly separate.
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

- Focused Community/SF Chat/storage/HTTP contract suite: `143 passed`.
- Full repository regression: `2501 passed, 35 skipped` in `342.86s`.
- Python/JavaScript syntax, `git diff --check`, repository-wide Markdown scan
  and External GPT Context Pack validator: PASS.
- Git-indexed `pre_release_check.py`: PASS (`474` bundle files; in-bundle
  static scan, runtime reads, Python compile and shipped JavaScript syntax).
- Real PostgreSQL tests require explicit acceptance DSNs and remain separately
  reported when unavailable; no database or server was mutated by this task.
- Strategy metadata, Chart snapshot and Live result adapters remain disabled,
  not simulated. Manual browser visual acceptance and Canary/Production are
  separate gates.
- Backtest/Connector, market data, trading and future `МИР АГЕНТОВ` were not
  changed. Any integration change starts a new immutable artifact cycle.
