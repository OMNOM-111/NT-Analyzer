# Aurora UI architecture

Актуально на 2026-07-13.

## Layout

`/ui/` обслуживает `app/static/aurora/`. Classic UI физически остаётся в
`app/static/` и доступен через `/ui/legacy/`. Такой route-level cutover не
дублирует production-логику и не требует копирования classic-файлов.

```text
app/static/
  index.html, trading.html, ...   classic UI
  legacy_switch.js               classic -> Aurora
  aurora/
    *.html                       CSP-safe page shells
    assets/theme.css             design system and responsive rules
    assets/ui.js                 shell, PT market/date, account, search, menus
    assets/api.js                all HTTP contracts
    assets/domain.js             pure response/finance/time adapters
    assets/charts.js             dependency-free canvas charts
    assets/pages/*.js            page controllers
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
- `server.py`: primary/classic static routing, CSP headers, portfolio and account
  history endpoints.

## Shared shell

- Pacific date/time uses `America/Los_Angeles` explicitly.
- Market state and countdown are DST-safe and tested.
- Selected runtime account is shared through `localStorage` and
  `nt-account-change`.
- The classic switch exists once in Aurora's system menu. Classic pages inject
  exactly one `#nta-new-ui-switch`.
- At 1024 px market, account and PT date remain visible; technical chips/search
  collapse first. At phone width the rail becomes bottom navigation.

## Security and lifecycle

- `script-src 'self'`; no inline `<script>` or HTML `onclick`.
- HTML also carries CSP meta; server sends the uniform CSP header.
- `UI.ready`, abort signals and polling cleanup prevent work after page unload.
- Async blocks have loading/empty/error states. Independent requests are loaded
  concurrently where one failure must not blank unrelated data.
- Общий chat widget сохраняет прежнее имя `StratForge Orchestrator`, но
  пользователь разговаривает с Витьком. Ошибка API или истёкшая сессия не
  очищает список диалогов: UI показывает вход через Telegram и сохраняет
  последнюю успешно загруженную историю.
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
