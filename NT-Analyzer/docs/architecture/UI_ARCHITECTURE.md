# Aurora UI architecture

Актуально на 2026-09-01.

## Layout

`/ui/` обслуживает только `app/static/aurora/`. Classic UI удалён из текущего
static/runtime contour: `/ui/legacy/*` возвращает HTTP 410. Его frozen assets
находятся в `legacy_viewer/static/` и доступны только через отдельный
localhost-only процесс `app.legacy_viewer`.

```text
app/static/
  aurora/
    *.html                       CSP-safe page shells
    assets/theme.css             design system and responsive rules
    assets/ui.js                 shell, PT market/date, account, search, menus
    assets/api.js                all HTTP contracts
    assets/domain.js             pure response/finance/time adapters
    assets/charts.js             dependency-free canvas charts
    assets/pages/*.js            page controllers
legacy_viewer/static/            frozen classic UI, separate process only
```

## Backend additions

- `portfolio_registry.py`: atomic persistent cell registry, collision checks,
  immutable IDs and history.
- `account_ledger.py`: atomic account snapshots and conservative cash-flow
  attribution, manual events and idempotent statement import. Position-only
  fallback data is rejected as a balance source.
- `performance.py`: commission-aware strategy/account aggregates, temporal
  breakdowns and paginated canonical closed trades.
- `ai_lab/read_model.py`: experiment/model/role telemetry over the append-only
  LM request audit.
- `server.py`: Aurora static routing, retired-surface HTTP 410 guards, CSP
  headers, portfolio and account history endpoints.
- `legacy_viewer.py`: localhost-only read-only classic viewer without current
  workers, Telegram, trading or release automation.
- `community.py`: Community social graph, profiles/privacy, cursor feed,
  reactions/comments/bookmarks, server-attested posts, channels and moderation.
- `sf_chat.py`: единый human-to-human conversation store для действий из
  Community и глобального launcher. Существующий AI Orchestrator не перенесён и
  не переписан: он подключён к тому же SF Chat shell через API facade.
- `production_storage`: документы `community`/`sf_chat` остаются совместимым
  авторитетным контрактом, а миграции `0020`/`0021` добавляют allowlist и
  связанные FK/index/RLS mirrors. Canary/Production не падают обратно в JSON.

## Shared shell

- Pacific date/time uses `America/Los_Angeles` explicitly.
- Market state and countdown are DST-safe and tested.
- Selected runtime account is shared through `localStorage` and
  `nt-account-change`.
- Current navigation contains no classic UI switch or Mini App controls.
- At 1024 px market, account and PT date remain visible; technical chips/search
  collapse first. At phone width the rail becomes bottom navigation.

## Security and lifecycle

- `script-src 'self'`; no inline `<script>` or HTML `onclick`.
- HTML also carries CSP meta; server sends the uniform CSP header.
- Current CSP does not authorize Telegram Web framing.
- `UI.ready`, abort signals and polling cleanup prevent work after page unload.
- Async blocks have loading/empty/error states. Independent requests are loaded
  concurrently where one failure must not blank unrelated data.
- Общий пользовательский chat widget называется `SF Chat` и показывает в одной
  оболочке личные human-диалоги и существующие AI-диалоги. Технический
  `StratForge Orchestrator` остаётся внутренним AI gateway; его storage и
  маршрутизация совместимы с прежним API. Ошибка API или истёкшая сессия не
  очищает список диалогов: UI показывает вход через Telegram и сохраняет
  последнюю успешно загруженную историю.
- Community отвечает за discovery/social graph, а SF Chat — за communication.
  Кнопка `Message` и глобальный launcher открывают один и тот же deterministic
  human `conversation_id`, историю и unread/read state; второго Community DM
  store нет. Компактные уведомления группируют непрочитанные сообщения одного
  диалога и не помечают их прочитанными при простом закрытии карточки.
- Все Aurora-страницы используют одинаковую cache-version для общего
  `api.js`, поэтому после обновления нельзя получить смесь старого адаптера и
  нового backend-контракта.

## Data semantics

- `AuroraDomain.normalizeJobDetail` owns nested job/result/trade adaptation.
- `AuroraDomain.tradingSeries` builds cumulative P&L and drawdown only from
  closed trades; deposits and NetLiq never enter that curve.
- Account ledger and trading performance are deliberately separate sources.
- Temporal profitability uses `strategy_breakdowns`; unmatched/account-level
  executions remain visible in attribution categories and the full trade ledger.
- Production has no `mock.js`, `window.MOCK` or demo action facade.
