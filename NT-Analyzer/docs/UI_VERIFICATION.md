# UI verification

Status: Aurora, Vitek and Orchestrator production integration re-audited on
2026-07-13. Историческая визуальная приёмка ниже сохранена как evidence июня;
текущие автоматические release-gates выполнены заново.

## Automated gates

- `python -m pytest -q`: **447 passed**.
- `python -m tests`: **13/13 suites passed**.
- `node --check`: every JS file under `app/static/aurora/assets` passed.
- `python -m compileall -q app tests`: passed.
- `dotnet build bridge\NTAnalyzerBridge.csproj -c Debug`: 0 warnings,
  0 errors.
- CSP scan: no inline `<script>` and no HTML `onclick=` in Aurora pages.
- HTTP contract tests cover `/ui/`, `/ui/legacy/`, CSP, GET trade pagination,
  nested job details, runtime adapters, PT market phases, immutable cells,
  account-ledger accounting rules, AI model telemetry, Telegram auth, workspace
  isolation, scoped chat migration, Vitek events and real yes/no decisions.

## Live acceptance

После подтверждённого обновления Codex и прямого разрешения владельца выполнена
попытка подключить встроенный браузер. Два запуска остановились внутри модуля
Codex до создания вкладки с ошибкой `Cannot redefine property: process`;
приложение и backend не закрылись. Повторный рискованный цикл не выполнялся.
Поэтому субъективный визуальный click-through остаётся проверкой владельца в
обычном браузере по `http://127.0.0.1:8765/ui/`.

На заново запущенном backend PID 11020 выполнен безопасный live smoke:

- все 11 Aurora HTML-страниц и актуальные `api.js`, `ui.js`, `theme.css`
  вернули HTTP 200 и cache-version `20260713-vitek7`;
- неавторизованный `/api/auth/status` вернул 401 с требованием Telegram-входа;
- webhook с неверным secret вернул 403 и не изменил очередь;
- реальный owner-запрос «Витя, какие на сегодня задания у тебя остались?» прошёл
  через HTTP webhook → durable inbox → `chief_private` → общий scoped transcript
  → Telegram: `consumed=true`, `delivered=true`, assistant message id сохранён;
- после smoke `queued=0`, `running=0`, `dead_letter=0`.

Verified against the running backend at `127.0.0.1:8765`:

- Overview: selected account balance, month/year strategy P&L, annual drawdown,
  commissions, account history, cash-flow separation, daily/weekly/monthly rhythm
  and strategy sparklines. No balance movement is counted as trading profit.
- Backtesting: a real completed report rendered 31 trades and four charts
  (cumulative P&L, per-trade P&L, monthly result and 3,000/3,773 price bars).
  Drawer normal/wide/full modes were clicked and verified. A final three-job
  acceptance run completed as reports 17119, 17121 and 17122
  (`ui_20260629T011725173Z`, `ui_20260629T011922093Z`,
  `ui_20260629T011922610Z`); all three returned trades, bars, commission-aware
  metrics and `validated_against_strategy_analyzer=true`.
- Charts: every visible completed report has a summary sparkline; the latest 12
  are enriched from real trades. Hover on bar charts shows the full period/date,
  amount and context. The annual rhythm tooltip was verified with a full date.
- Trading: demo and disconnected live accounts are visible. Eight managed
  strategies are shown; one personal/external strategy is hidden by default.
  Runtime detail shows actual window, account, events, parameters and annual P&L.
- Account ledger: four valid snapshots, zero false events after removing
  `positions_fallback` artifacts. Manual event and CSV import forms were opened
  and validated without writing test finance data.
- Performance: both accounts are selectable; monthly view returned 188 trades,
  100 rows on page one, 13 daily groups, seven hourly groups and weekday charts.
- Strategies: 12 roots and 181 persistent cells, including the operator-created
  `CELL-181`. Existing IDs were not renumbered. Detail contains runtime readiness,
  factual trading history and editable profile notes.
- AI Lab: the active run `RUN-9b54d2184837` was observed through generation and
  compile heartbeats and finished without interruption. Model audit contains
  3,581 requests across four models and 12 roles. Environment bootstrap started
  NinjaTrader/LM Studio server and loaded the judge/coder models.
- New -> classic -> new routing exposes exactly one switch in each direction.
  All classic tabs and classic deep links stay under `/ui/legacy/`.
- Responsive 390 px acceptance has no document-level horizontal overflow;
  wide tables retain intentional internal scrolling. Prior 760/1024/1280/1440
  checks remain covered by the responsive contract and browser audit.
- Browser console: no JavaScript errors on the verified flows.

## Known data boundaries

- NinjaTrader does not export historical broker cash transactions. History starts
  at the first account snapshot. Earlier deposits/withdrawals are not guessed.
- The live account `1267509` is currently disconnected and therefore displays
  zero runtime values; it remains visible and read-only.
- Historical LM logs did not include token usage. Latency/success/result metrics
  are available now; exact token totals accumulate for new responses that return
  an OpenAI-compatible `usage` object.
- A zero candidate count in AI Lab is a research outcome, not a missing UI value.

## Safety boundary

Acceptance submitted only the three historical backtests listed above. It did not
submit live/paper trades, enable/disable a strategy, delete jobs/profiles, classify
finance events or start a new AI research run. Environment readiness was probed
intentionally. Runtime commands remain paper-only at the backend.

## Re-run

```powershell
Set-Location 'C:\Users\dimon\Documents\Анализатор стратегий NinjaTrader\NT-Analyzer'
C:\Python312\python.exe -m pytest -q
C:\Python312\python.exe -m tests
Get-ChildItem app\static\aurora\assets -Recurse -Filter *.js |
  ForEach-Object { node --check $_.FullName }
python -m compileall -q app tests
dotnet build bridge\NTAnalyzerBridge.csproj -c Debug
```
