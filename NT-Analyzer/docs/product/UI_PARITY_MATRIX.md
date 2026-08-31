# Aurora functional parity matrix

This matrix compares active operator capabilities, not pixel-for-pixel layout.
Aurora is the only current product UI. Classic is retained temporarily in a
separate read-only Legacy Viewer for historical report reference.

| Area | Aurora capability | Status |
|---|---|---|
| Shell | PT date/time, CME market state/countdown, NinjaTrader/Bridge/LM status, selected account, global search | Complete |
| Routing | Aurora-only current runtime, canonical redirects, retired legacy/Mini App routes return HTTP 410 | Complete |
| Backtesting | grouped instruments, profile/coverage drilldowns, dynamic parameters, single/batch submit, server filters/sorting/hierarchy, period/frequency/confidence, favorites, queue/cancel/delete, nested metrics/trades, semantic P&L, entry/exit/draw markers, resizable/full drawer | Complete |
| Trading control | real accounts, paper-only start/stop, positions/orders/executions/errors, command queue and command-status tracking | Complete |
| Trading audit | runtime sessions, start dates, lifecycle events, launch parameters, operator journal, hidden-class restore | Complete |
| Account analytics | NetLiq snapshot, realized/unrealized values, closed-trade P&L curve, commission, drawdown, account selection | Complete |
| Cash movements | durable snapshots, fallback rejection, unknown-delta review, manual event, CSV statement import/idempotency, classification | Complete from first snapshot; no invented historical reconstruction |
| Calendar | arbitrary month navigation, per-day P&L, strategy filter, executions, commissions | Complete |
| Performance | standard/custom periods, all accounts, scoped CSV, equity/drawdown, time/weekday/direction breakdowns, paginated trades, strategy/instrument charts, attribution/cash separation | Complete |
| Portfolio cells | persistent root/cell registry, immutable IDs, manual root/cell creation, explicit 200/300/400 blocks, archive/no reuse | Complete |
| Strategy lifecycle | kanban, origin + rare/normal/frequent filters, coverage, goals, profile status/delete/notes, factual runtime readiness/P&L, AI history and 3D origin badges, archive, runtime hide/restore, NinjaTrader cleanup | Complete |
| AI Lab | lazy readiness/bootstrap, run/cancel, heartbeat/activity roles, experiments, quality board, model/role request and outcome telemetry, external-agent budget/activity, calendar, candidates, error memory, compile source, research scan, notes | Complete; external execution intentionally disabled |
| AI Agents / API Keys | DPAPI key storage, provider/model/role CRUD, chat/embedding test, editable tariff table, token/cost audit, daily/monthly/single-call gates, grant snapshots | Complete base mechanism; workflow permissions intentionally disconnected |
| News | separate feed + Overview summary; only persisted real events | Scaffold complete; sources not configured by default |
| TopstepX | primary independent read-only chart history + realtime, shared auth/session and browser fan-out | Available; trade routing disabled, NinjaTrader remains execution authority |
| Telegram | dedicated system drawer, secure token/chat pairing, test send, per-event switches, app/strategy/connection/error/news alerts, daily/weekly/monthly summaries | Notifications complete; commands intentionally disabled |
| Documents | product-first navigation; compact right-side revision journal with semantic red/green `Было → Стало`; full diff/path only in collapsed `Подробнее`; authenticated author attribution; DRAFT legal docs | Complete; journal/internal metadata owner/docs-admin only |
| Security | CSP `script-src 'self'`, external scripts/handlers, Origin guard, paper/live safety | Complete |
| Responsive | 390/760/1024/1280/1440 layouts, internal table scrollers, mobile bottom nav | Complete |

## Deliberate differences from classic

- Aurora groups detailed legacy controls into drawers, tabs and audit panels rather
  than reproducing the classic page density verbatim.
- Technical status chips and search collapse before market/account/PT date so the
  most important operator context remains visible at tablet width.
- Account funding is never inferred from balance direction. Unknown historical
  movements stay unknown; this is stricter than displaying balance growth as P&L.
- Classic assets are preserved outside the current static root. The isolated
  Legacy Viewer is reference-only and is not a fallback runtime.
