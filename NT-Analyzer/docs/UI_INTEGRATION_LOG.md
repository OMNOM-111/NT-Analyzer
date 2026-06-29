# NT-Analyzer — UI Integration Log

Chronological record of the new-UI ("Claude" concept) integration into the production NT-Analyzer app.
Append-only. Newest entries at the bottom.

---

## 2026-06-27 — Phase 0: Backup

- Full external backup created at:
  `C:\Users\dimon\Documents\NT-Analyzer-UI-backups\20260627_231759\`
  - `repo_full.bundle` — `git bundle --all` (complete history, restorable).
  - `git_diff_tracked.patch` + `git_diff_tracked_binary.patch` — uncommitted tracked changes (441 KB).
  - `git_untracked_list.txt` — 219 untracked files listed.
  - `git_status.txt`, `git_HEAD.txt` (HEAD = `e7123a427d45205ab1b8f75738a475a370d37638`).
  - `project_snapshot\` — full project copy incl. `.git` (3066 files).
  - `legacy_static_snapshot\` — copy of `NT-Analyzer/app/static` (18 files) + `legacy_static_sha256.txt` (SHA-256 manifest). File count verified src=dst=18.
- **Restore:** see `docs/UI_ROUTES_AND_ROLLBACK.md` → "Восстановление из backup".

## 2026-06-27 — Phase 1: Baseline + Inventory

- Baseline tests: `python -m pytest -q` → **12 passed** (31.78s). Captured to `%TEMP%\nt_pytest_baseline.txt`.
- Read the REAL backend (`app/server.py`) to build a ground-truth endpoint map (see `docs/UI_API_MAP.md`).
- Routing facts (server.py):
  - `GET /` → 302 `/ui/`.
  - `GET /ui` + rest → `_serve_static(rel)`; `rel="/"` → `index.html`; extensionless paths get `.html` fallback. STATIC_DIR = `app/static`.
  - CSP is **per-page `<meta>`** (`script-src 'self'`), NOT a server header. JSON responses get `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`.
  - POST/DELETE validate `Origin`/`Referer` host∈{127.0.0.1, localhost} and port == bind port. Missing Origin (CLI) allowed.
  - `POST /api/server/restart` exists (graceful re-spawn). Default port 8765, bind 127.0.0.1 only, auto-picks 8765..8774 if busy.
- Corrections vs the earlier prototype `api.js` (which had invented endpoint names):
  - `/api/instruments` → **does not exist**; real is `GET /api/ops/runtime/instruments` (`{roots:[{root, front_month, contracts}]}`).
  - `/api/instrument-coverage` → real is `GET /api/coverage`.
  - `/api/performance/day` → does not exist; day data derived from `GET /api/performance`.

### Decision log (conservative choices)
- **Do not flip the production default to the mock UI until pages are wired to real data.** Reason: the new pages still render `window.MOCK`; making a mock dashboard the `/ui/` default would degrade a working app and "imitate success", which the task forbids. The cutover (new → `/ui/`, old → `/ui/legacy/`) is prepared and documented as the final step after per-page wiring (`docs/UI_ROUTES_AND_ROLLBACK.md`).
- **`api.js` becomes a real async adapter** over the actual endpoints, with a `window.MOCK` fallback used ONLY when served from `file://` (the offline design preview). Production HTML will not ship `mock.js`.
- **Legacy UI is preserved verbatim** (full functional depth) and reachable; nothing in `app/static` is deleted.

## 2026-06-27 — Foundation implemented + verified (Phases 2/3/5 partial)

- **api.js rewritten** to a two-layer data seam: real async `API.http.*` over the actual `/api/*`
  endpoints (`getJSON` w/ retry, `send` for POST, `HttpError`) + a sync `window.MOCK` facade used
  only for the `file://` preview. `API.config.legacyUrl` = `/ui/legacy/` when served, relative on `file://`.
- **Single legacy switch:** removed the duplicate «Перейти на старый интерфейс» item from the system
  menu (`ui.js`); the topbar keeps exactly one «Старый интерфейс» button. Verified 1/page.
- **Responsive overflow eliminated:** `minmax(0,1fr)` tracks + `min-width:0` on shell/grid containers,
  `.tbl-wrap` internal scroll, `.content{overflow-x:clip}` safety net, log-line wrap, dedicated
  topbar trim @900, left-rail→bottom-nav @600, full-screen drawer @760. Verified `window.scrollX==0`
  after scroll-right at 390/480/768/1024/1440 on all 7 pages.
- **Verification:** `node --check` OK for 11/11 JS files; 0 console errors on load (all pages);
  `pytest -q` still **12 passed** (no backend code changed — only `docs/` added).
- **Docs created:** `UI_API_MAP.md`, `UI_ARCHITECTURE.md`, `UI_ROUTES_AND_ROLLBACK.md`, `UI_VERIFICATION.md`.
- **Decision (CSP):** enforce CSP via a **server response header** on `/ui/*` (uniform, covers legacy +
  documents) instead of per-page `<meta>` — a strict `script-src 'self'` meta breaks the `file://`
  preview, and a header is centralised/un-forgettable. Patch specified in `UI_ROUTES_AND_ROLLBACK.md`.
  `script-src 'self'` is not weakened (new UI has zero inline JS).

### Remaining (staged, page-by-page) — NOT yet done
Per-page wiring of new pages to real `/api/*` data with loading/empty/error/stale states and real
button actions (Phase 4), then the routing cutover + launch + CSP-header + legacy «Новый интерфейс»
button + redirects (Phase 2/5 application). All prepared; sequence and exact patches in the docs.
Production (`app/server.py`, `app/static`) intentionally left untouched this session to avoid shipping
a mock UI as primary; only additive `docs/` files were added.


## 2026-06-28 — Real integration: Overview wired to LIVE backend (+ audit fixes)

Second pre-cutover backup: `NT-Analyzer-UI-backups\precutover_20260628_000554\` (git bundle + binary diff +
untracked list + legacy_static_snapshot 18 files + test_design_ui 23 files + SHA256_MANIFEST.txt).

Audit code-bug fixes (verified):
- `UI.ready` is now async-safe: awaits async callbacks, routes rejected Promises to a global handler,
  catches `unhandledrejection`; new `UI.poll`/`UI.signal`/`UI.onLeave` clean up intervals + AbortControllers on `pagehide`.
- Responsive masking removed: deleted `overflow-x: clip/hidden` used to hide overflow. Fixed the real sources
  (form `select` width, calendar cell shrink to `minmax(0,1fr)`, hero badge wrap, topbar wraps on phones).
  Re-verified with bounding-rect (every element's right edge ≤ viewport unless inside a visible `.tbl-wrap`/`.kanban`
  scroller) AND `window.scrollX==0` at 390/480/768/1024/1440 → CLEAN on all 7 pages.
- Accessibility: clickable rows/cards/cells get `role=button`+`tabindex=0` (centralized in ui.js, MutationObserver
  for dynamic content), global Enter/Space→click, `:focus-visible` ring. Verified (47/134/67… per page).
- `UI_VERIFICATION.md` corrected to honest statuses; retracted the wrong "No functional depth lost = Done"
  (parity in the NEW UI is NOT DONE — depth lives in legacy, not yet ported).

REAL wiring (the central audit point):
- `overview.js` rewritten **dual-mode**: `API.config.offline` (file://) → MOCK preview; served over HTTP → real
  `await API.http.*` with loading/error/empty states and `UI.signal()` aborts. Real endpoints + adapters:
  `/api/performance?period=month|today` (summary + per-strategy `daily` → cumulative equity), `/api/coverage`,
  `/api/ai-lab/summary`, `/api/health`, `/api/reports`.
- Deployed new UI additively to `app/static/aurora/` (22 files) → served by the running backend at
  `/ui/aurora/index.html` (no change to the production `/ui/` default).
- VERIFIED against the LIVE backend (8765): Overview renders REAL data — Net P&L −$1,043 (188 trades),
  WinRate 19.1% (36/152), PF 0.35, commission $369, coverage 2/12 (MGC 7 prof, MNQ 14 prof), AI experiments 58,
  real top strategies (VWAP Short MNQ 5m +$76 …), real job reports, NinjaTrader online, account DEMO3369390.
  `offline=false`, 0 console errors, 0 network failures, legacy button → `/ui/legacy/`. pytest still **12 passed**.

Status: ONE page (Overview) is genuinely wired + verified against the live backend — the real integration pattern
is proven end-to-end. NOT yet done: the other 6 pages (Backtesting/Trading/Performance/Strategies/AI Lab/Documents)
still use the MOCK facade and would show mock data when served; full parity, real actions, routing cutover (new→/ui/,
legacy→/ui/legacy/), server CSP header and launch scripts remain. The `app/static/aurora/` copy is an additive,
removable proof artifact (still ships mock.js + unwired pages) — the production cutover drops mock.js and wires every page.

## Phase 4 — Full production cutover (2026-06-28) — DONE + verified

All seven Aurora pages are now served-only and wired to the real backend; the production cutover is live.

- **Shell (`ui.js`)** — topbar chips show real status (NinjaTrader `/api/health`, Bridge `/api/ops/runtime/heartbeat`,
  LM Studio `/api/ai-lab/lm-studio/health`, Market = client-side CME PT calc). Topbar actions are real
  (`UI.action` helper: restart, diagnostics drawer, unload AI memory, refresh catalog, refresh margins) and only
  toast on success. Global search builds a real index (profiles/jobs/governance docs/coverage) with deep links.
- **Pages** — every controller is served-only, calls `API.http.*`, and renders loading/empty/error/partial states
  (`Promise.allSettled` so one failing endpoint never zeroes the rest):
  - Overview: real KPIs, working 1М/3М/6М/Год range selector (refetches), honest cumulative-P&L label.
  - Performance: period + custom dates + account filter + real CSV download + equity/drawdown + strategy/instrument
    breakdown + per-strategy drilldown.
  - Documents: governance list/summary/runtime-defaults, markdown view, edit (actor+reason+confirm+dirty guard),
    save → `POST /api/governance/documents/{id}`, per-doc history with diffs.
  - Strategies: KPIs + lifecycle kanban + origin filter + coverage matrix + goals + detail drawer (status change /
    delete) + AI cell-history drawer + archive drawer (prod/AI/registry) + NinjaTrader cleanup (dry-run → execute).
  - Trading / Control Center: account band + control table (enable/disable, paper-guarded) + positions/orders/
    executions/errors tabs + command queue + live bridge log + today-by-strategy + calendar day drilldown.
  - AI Lab: KPIs + LM Studio/bootstrap + run form (start/stop, disabled with explanation when LM Studio not ready)
    + activity log + experiment matrix/table + detail drawer + error memory + lessons + global operator note.
  - Backtesting: instruments + tick economics + composer (`POST /api/jobs`) + reports (filter/paginate/favorite) +
    detail drawer (trades equity, repeat, delete, raw JSON) + active queue with cancel.
- **Production hygiene** — `assets/mock.js` deleted; `api.js` mock facade and `overview.js` `renderMock` removed;
  no `window.MOCK`, no demo-toast in production controllers.
- **Routing (`server.py`)** — `/ui/` + new pages + `/ui/assets/*` serve from `app/static/aurora/`; `/ui/legacy/*`
  serves the classic UI from `app/static/`; directory-index for trailing-slash; 302 redirects
  `ai-strategy.html→ai-lab.html`, `ops.html→trading.html`, `docs.html→documents.html`, `/ui/aurora/*→/ui/*`;
  uniform `Content-Security-Policy` response header (`STATIC_CSP`) on every static response.
- **Legacy switch** — `legacy_switch.js` injects a single «✦ Новый интерфейс» → `/ui/` button on every classic page.
- **Launchers** — `start.ps1` opens `/ui/` (now the new UI; `_bind_or_pick_port` handles busy ports);
  `start-ai-lab.ps1` opens `/ui/ai-lab.html`.
- **Tests** — `tests/test_cutover_routing.py` (6 cases) asserts aurora pages exist + CSP + mock-free, controllers call
  real endpoints, server routing/redirects/CSP, legacy switch, launcher targets. `pytest -q` → **18 passed**.
- **Verified live** (Playwright over `/ui/…`): all 7 pages 0 console errors with real data; CSP blocks injected inline
  script; bidirectional new↔legacy switch works; responsive 390 px clean. Backup: `cutover_20260628_135431`.

## 2026-06-28 — Functional parity completion and audit

- Created and verified pre-parity backup
  `C:\Users\dimon\Documents\NT-Analyzer-UI-backups\parity_20260628_150128`
  (static/app Python/tests/docs/launchers, git bundle, SHA-256, RESTORE.md).
- Added pure `assets/domain.js` adapters and contract tests for nested job detail,
  trade fields, trading-only P&L/drawdown and Pacific market phases.
- Backtesting now includes profiles, coverage, catalog-driven parameters, canonical
  batch submit and lazy bars/draw-object chart loading.
- Trading/Performance now separate NetLiq, closed-trade P&L and account cash events.
  Added `account_ledger.py`; unexplained deltas require manual classification and
  never become automatic strategy profit/deposit.
- Added persistent `portfolio_registry.py` with immutable `CELL-001..180` legacy
  mapping and safe manual root/cell expansion.
- Restored classic-only operational endpoint families in Aurora: runtime sessions,
  strategy history/display, start dates, command status, strategy journals, AI
  performance/calendar/current/compile-source and user-research scan.
- Expanded AI Lab with role activity, quality board and research/compile visibility.
- Fixed tablet topbar overflow while preserving market/account/PT date at 1024 px.
- Updated documentation to remove obsolete mock/staging claims; added
  `UI_PARITY_MATRIX.md`.

## 2026-06-28 — Final production completion audit

- Preserved the active AI run until it completed; no forced stop or backend
  restart occurred during the run.
- Fixed real response-contract defects in AI active state, nested runtime
  strategies, disconnected account visibility and the GET trade-detail route.
- Added yearly overview/account/cash-flow charts and strategy sparklines.
- Added canonical performance pagination and strategy-only time breakdowns.
- Added manual/idempotent CSV cash events and removed false zero-balance events
  caused by `positions_fallback`.
- Added resizable/full drawers, four default backtest charts, factual runtime
  strategy drilldowns and persistent operator notes.
- Added AI model/role request, latency, token and experiment-outcome telemetry;
  fixed activity timeline clearing and lazy-readiness messaging.
- Moved environment/restart/classic actions into the single system menu and
  verified one classic-to-Aurora switch.
- Live acceptance: 188 monthly trades, 100-row page, 31-trade backtest report,
  3,000 price bars, 181 immutable cells and 3,581 audited LM requests.
- Final gates: `pytest` 36/36, performance suite 13/13, all JS syntax checks and
  CSP inline-script scan passed.

## 2026-06-28 — Release-final closure

- Fixed every classic navigation and deep-link target to stay under
  `/ui/legacy/`; added a regression contract and verified classic tab clicks plus
  the single classic-to-Aurora switch in the browser.
- Added contextual bar-chart hover (full date/period, value and detail), report
  sparklines, AI-origin badges and explicit `Цикл не запущен` idle wording.
- Submitted and validated three real historical jobs: reports 17119, 17121 and
  17122. All completed with trades, bars, nested metrics and Strategy Analyzer
  validation.
- Rechecked all seven Aurora pages and all seven classic pages with zero browser
  console errors; 390 px responsive audit had no document-level overflow.
- Confirmed old `accounts.json` lock messages were May history, not current:
  exporter 1.3.0 and heartbeat were fresh. The classic summary now limits events
  to seven days while diagnostics retain the full history.
- Archived and removed `test_design_ui`, `ui_audit_screens`, the audit report and
  obsolete parity task. Archive:
  `C:\Users\dimon\Documents\NT-Analyzer-UI-backups\final_cleanup_20260628_183443`
  with a verified 46-file SHA-256 manifest.
- Final gates: `pytest` 38/38, performance suite 13/13, Python compileall, all JS
  syntax checks and CSP inline-script/handler scans passed.
- Created final Git-visible release snapshot
  `C:\Users\dimon\Documents\NT-Analyzer-UI-backups\release_final_20260628_183903`
  (590 files, 7,706,535 bytes, SHA-256 manifest, binary diff and Git bundle).
