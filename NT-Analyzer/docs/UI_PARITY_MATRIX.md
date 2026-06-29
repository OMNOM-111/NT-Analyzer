# Aurora functional parity matrix

This matrix compares active operator capabilities, not pixel-for-pixel layout.
Classic remains available for rollback/reference, but normal work starts in Aurora.

| Area | Aurora capability | Status |
|---|---|---|
| Shell | PT date/time, CME market state/countdown, NinjaTrader/Bridge/LM status, selected account, global search | Complete |
| Routing | Aurora default, classic fallback, canonical redirects, bidirectional single switch | Complete |
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
| News | separate feed + Overview summary; only persisted real events | Scaffold complete; sources not configured by default |
| TopStep | connection/risk status and approved-strategy transport design | Scaffold complete; live actions intentionally disabled |
| Telegram | status in system integration drawer; secrets remain server-side | Scaffold complete; commands intentionally disabled |
| Documents | explicit owner `Черевко Дмитро`, governance list, runtime defaults, markdown view/edit, actor/reason save, history | Complete |
| Security | CSP `script-src 'self'`, external scripts/handlers, Origin guard, paper/live safety | Complete |
| Responsive | 390/760/1024/1280/1440 layouts, internal table scrollers, mobile bottom nav | Complete |

## Deliberate differences from classic

- Aurora groups detailed legacy controls into drawers, tabs and audit panels rather
  than reproducing the classic page density verbatim.
- Technical status chips and search collapse before market/account/PT date so the
  most important operator context remains visible at tablet width.
- Account funding is never inferred from balance direction. Unknown historical
  movements stay unknown; this is stricter than displaying balance growth as P&L.
- Classic is not deleted. It is a safe fallback at `/ui/legacy/`, but not required
  to access the endpoint families used by normal operation.
