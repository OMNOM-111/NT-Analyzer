// trading.js — "Торговля онлайн" page.
// Wires the Trading Online UI to /api/* and /api/ops/runtime/* endpoints.
// "Запустить стратегию" / "Остановить стратегию" post to
// /api/ops/runtime/command. Backend rejects live/unknown accounts and writes
// the command into data/runtime/commands.jsonl for the NinjaTrader bridge
// AddOn to pick up. UI surfaces actionable hints when the bridge can't find
// the strategy instance — without redirecting the user away from this page.

// === Phase 5–9 rewrite (Trading Online — full UI flow) ===================
// All API calls return JSON. UI text Russian. No raw innerHTML with API data —
// strings are escaped via escapeHtml() before interpolation.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const DEFAULT_ROUND_TURN_COMMISSION = 1.90;
  const PERFORMANCE_START_DATE_PT = "2026-05-13";
  const PERFORMANCE_STARTING_CAPITAL = 2000;
  const MAX_INTRADAY_TRADE_HOLD_SECONDS = 24 * 60 * 60;
  const fmtMoney = (v) =>
    (v == null || isNaN(v)) ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(2);
  const fmtCurrency = (v) =>
    (v == null || isNaN(v)) ? "—" : Number(v).toFixed(2);
  const fmtNum = (v) => (v == null || isNaN(v)) ? "—" : Number(v).toFixed(2);
  const fmtMoneyShort = (v) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1) + "k";
    return n.toFixed(0);
  };
  const escapeHtml = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const TRADING_SORT_STORAGE_KEY = "nta.trading.tableSorts.v1";
  const DEFAULT_TRADING_TABLE_SORTS = {
    runtimeStrategies: { col: "cell", dir: "asc" },
    closedTrades: { col: "exit_time", dir: "desc" },
    executions: { col: "timestamp", dir: "desc" },
  };

  function cloneSort(sort, fallback) {
    const fb = fallback || { col: "exit_time", dir: "desc" };
    return {
      col: String(sort && sort.col || fb.col || "exit_time"),
      dir: sort && sort.dir === "asc" ? "asc" : (fb.dir === "asc" ? "asc" : "desc"),
    };
  }

  function loadTradingTableSorts() {
    let raw = {};
    try {
      raw = window.localStorage
        ? (JSON.parse(window.localStorage.getItem(TRADING_SORT_STORAGE_KEY) || "{}") || {})
        : {};
    }
    catch (_) { raw = {}; }
    return {
      runtimeStrategies: cloneSort(raw.runtimeStrategies || DEFAULT_TRADING_TABLE_SORTS.runtimeStrategies, DEFAULT_TRADING_TABLE_SORTS.runtimeStrategies),
      closedTrades: cloneSort(raw.closedTrades || DEFAULT_TRADING_TABLE_SORTS.closedTrades, DEFAULT_TRADING_TABLE_SORTS.closedTrades),
      executions: cloneSort(raw.executions || DEFAULT_TRADING_TABLE_SORTS.executions, DEFAULT_TRADING_TABLE_SORTS.executions),
    };
  }

  function saveTradingTableSorts() {
    try {
      if (window.localStorage) {
        window.localStorage.setItem(TRADING_SORT_STORAGE_KEY, JSON.stringify(STATE.tableSorts || DEFAULT_TRADING_TABLE_SORTS));
      }
    } catch (_) { /* ignore storage failures */ }
  }

  function makeDateFormatter(locale, options) {
    try { return new Intl.DateTimeFormat(locale, options); }
    catch (_) { return null; }
  }
  const PT_DATE_FORMATTER = makeDateFormatter("sv-SE", {
    timeZone: "America/Los_Angeles",
    year: "numeric", month: "2-digit", day: "2-digit",
  });
  const PT_HMS_FORMATTER = makeDateFormatter("sv-SE", {
    timeZone: "America/Los_Angeles",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
  const PT_DATETIME_FORMATTER = makeDateFormatter("sv-SE", {
    timeZone: "America/Los_Angeles",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
  const PT_HHMM_PARTS_FORMATTER = makeDateFormatter("en-US", {
    timeZone: "America/Los_Angeles",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const PT_WEEKDAY_FORMATTER = makeDateFormatter("en-US", {
    timeZone: "America/Los_Angeles", weekday: "short",
  });
  const RU_MONTH_FORMATTER = makeDateFormatter("ru-RU", {
    month: "long", year: "numeric", timeZone: "UTC",
  });
  const RU_DAY_FORMATTER = makeDateFormatter("ru-RU", {
    weekday: "long", day: "2-digit", month: "long", year: "numeric", timeZone: "UTC",
  });
  const WEEKDAY_INDEX = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const DATE_CACHE_MAX = 50000;
  const PT_WALL_DATE_CACHE = new Map();
  const PT_SESSION_DATE_CACHE = new Map();
  const UTC_GUESS_FOR_PT_YMD_CACHE = new Map();
  function cacheDateValue(cache, key, value) {
    if (cache.size > DATE_CACHE_MAX) cache.clear();
    cache.set(key, value);
    return value;
  }

  // Group mapping: predefined Trading Online groups (Phase 7).
  const GROUP_DEFS = [
    ["Index micros", ["MES", "MNQ", "MYM", "M2K"]],
    ["Metals",       ["MGC", "SIL", "SI", "MSI"]],
    ["Energies",     ["MCL", "MNG", "RB", "HO"]],
    ["FX micros",    ["M6E", "M6B", "M6A", "M6J", "M6C"]],
    ["Crypto",       ["MBT", "MET"]],
  ];
  function rootOf(sym) {
    if (!sym) return "";
    return String(sym).trim().toUpperCase().split(/\s+/, 1)[0];
  }
  function groupOf(sym) {
    const r = rootOf(sym);
    for (const [name, roots] of GROUP_DEFS) if (roots.includes(r)) return name;
    return "Other";
  }
  // Render "MNQ JUN26" with hint "(= MNQ 06-26)" if shapes differ.
  const _MONTH_NAME = {"01":"JAN","02":"FEB","03":"MAR","04":"APR","05":"MAY","06":"JUN",
                       "07":"JUL","08":"AUG","09":"SEP","10":"OCT","11":"NOV","12":"DEC"};
  function instrumentDisplay(sym) {
    if (!sym) return "—";
    const s = String(sym).trim();
    const m = s.match(/^([A-Z0-9]+)\s+(\d{2})-(\d{2})$/i);
    if (m) {
      const mn = _MONTH_NAME[m[2]] || m[2];
      return `${m[1].toUpperCase()} ${mn}${m[3]} (= ${s.toUpperCase()})`;
    }
    return s;
  }

  const FUTURES_MULTIPLIER = {
    MES: 5, MNQ: 2, MYM: 0.5, M2K: 5,
    MGC: 10, SIL: 1000, SI: 5000, MSI: 1000,
    MCL: 100, MNG: 1000, MBT: 0.1, MET: 0.1,
    M6E: 12500, M6B: 6250, M6A: 10000, M6J: 1250000, M6C: 10000,
  };
  const UNMAPPED_STRATEGY_MARKERS = new Set([
    "", "short", "long", "entry", "exit", "target", "stop", "manual",
    "buy", "sell", "sellshort", "buytocover",
  ]);

  function numOrNull(v) {
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function moneyClass(v) {
    const n = numOrNull(v);
    if (n == null || n === 0) return "";
    return n > 0 ? "pos" : "neg";
  }

  /** Pacific wall-calendar date (midnight rollover), fallback when market API missing. */
  function ptWallCalendarDate(iso) {
    if (!iso) return "";
    const key = String(iso);
    if (PT_WALL_DATE_CACHE.has(key)) return PT_WALL_DATE_CACHE.get(key);
    const d = new Date(key);
    if (isNaN(d.getTime())) return "";
    try {
      const value = PT_DATE_FORMATTER ? PT_DATE_FORMATTER.format(d) : key.slice(0, 10);
      return cacheDateValue(PT_WALL_DATE_CACHE, key, value);
    } catch (_) {
      return cacheDateValue(PT_WALL_DATE_CACHE, key, key.slice(0, 10));
    }
  }

  function isPerformanceWindowDate(datePt) {
    const d = String(datePt || "");
    return !!d && d >= PERFORMANCE_START_DATE_PT;
  }

  function isPerformanceWindowTimestamp(iso) {
    return isPerformanceWindowDate(ptWallCalendarDate(iso));
  }

  /** Same session-day key as #chip-market / NTAMarketClock (CME Globex model, PT). */
  function sessionDatePt(iso) {
    if (!iso) return "";
    const key = String(iso);
    if (PT_SESSION_DATE_CACHE.has(key)) return PT_SESSION_DATE_CACHE.get(key);
    try {
      const MC = window.NTAMarketClock;
      if (MC && typeof MC.timestampSessionDatePt === "function") {
        const s = MC.timestampSessionDatePt(key);
        if (s) return cacheDateValue(PT_SESSION_DATE_CACHE, key, s);
      }
    } catch (_) { /* ignore */ }
    return cacheDateValue(PT_SESSION_DATE_CACHE, key, ptWallCalendarDate(key));
  }

  function todaySessionDatePt() {
    return sessionDatePt(new Date().toISOString());
  }

  /** Pacific calendar day (matches NinjaTrader daily fields); use for Performance Center + date_pt. */
  function todayWallPtDate() {
    return ptWallCalendarDate(new Date().toISOString());
  }

  const TRADE_WINDOW_PARAM_KEYS = [
    "TradeStartTime", "TradeEndTime",
    "UseSecondTradeWindow", "SecondTradeStartTime", "SecondTradeEndTime",
    "Use24hSession", "IntradayOnly",
  ];

  function truthyParam(v) {
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v !== 0;
    const s = String(v == null ? "" : v).trim().toLowerCase();
    return s === "1" || s === "true" || s === "yes" || s === "on";
  }

  function parseHhmmParam(v) {
    if (v == null || v === "") return null;
    if (typeof v === "boolean") return null;
    if (typeof v === "number" && Number.isFinite(v)) {
      const n = Math.trunc(v);
      return n > 0 ? n : null;
    }
    const s = String(v).trim();
    if (!s) return null;
    if (s.includes(":")) {
      const parts = s.split(":", 2);
      const hh = Number.parseInt(parts[0], 10);
      const mm = Number.parseInt(parts[1], 10);
      if (Number.isFinite(hh) && Number.isFinite(mm) && hh >= 0 && hh <= 23 && mm >= 0 && mm <= 59) {
        return hh * 100 + mm;
      }
      return null;
    }
    const n = Number.parseInt(s, 10);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  function fmtHhmmDisplay(hhmm) {
    const n = Number(hhmm);
    if (!Number.isFinite(n) || n <= 0) return "";
    const hh24 = Math.floor(n / 100);
    const mm = n % 100;
    const period = hh24 < 12 ? "AM" : "PM";
    const hh12 = (hh24 % 12) || 12;
    return String(hh12).padStart(2, "0") + ":" + String(mm).padStart(2, "0") + " " + period;
  }

  const TRADE_WINDOW_RANGE_RE = /^(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})$/;

  function buildTradeWindowLabelFromConfig(config) {
    if (!config || typeof config !== "object") return "";
    if (config.use_24h) return "круглосуточно";
    const windows = config.windows || [];
    const parts = [];
    for (const w of windows) {
      const start = Number(w.start);
      const end = Number(w.end);
      if (start > 0 && end > 0) {
        parts.push(fmtHhmmDisplay(start) + " – " + fmtHhmmDisplay(end));
      }
    }
    return parts.join(" + ");
  }

  function reformatTradeWindowPtString(label) {
    let s = String(label == null ? "" : label).trim();
    if (!s) return s;
    if (s.toLowerCase() === "круглосуточно") return s;
    let suffix = "";
    const ann = s.match(/\s*(\([^)]*\))\s*$/);
    if (ann) {
      suffix = " " + ann[1].trim();
      s = s.slice(0, ann.index).trim();
    }
    s = s.replace(/\s+PT\s*$/i, "").trim();
    const chunks = s.split(/\s*\+\s*/).map(c => c.trim()).filter(Boolean);
    if (!chunks.length) return label;
    const out = [];
    for (const chunk of chunks) {
      const m = chunk.match(TRADE_WINDOW_RANGE_RE);
      if (!m) return label;
      const start = parseHhmmParam(m[1]);
      const end = parseHhmmParam(m[2]);
      if (!start || !end) return label;
      out.push(fmtHhmmDisplay(start) + " – " + fmtHhmmDisplay(end));
    }
    return out.join(" + ") + suffix;
  }

  function mergeTradeWindowParams(...sources) {
    const merged = {};
    for (const src of sources) {
      if (!src || typeof src !== "object") continue;
      for (const key of TRADE_WINDOW_PARAM_KEYS) {
        if (src[key] != null && src[key] !== "") merged[key] = src[key];
      }
    }
    return merged;
  }

  function buildTradeWindowPtFromParams(params) {
    if (!params || typeof params !== "object") return "";
    if (truthyParam(params.Use24hSession)) return "круглосуточно";
    return buildTradeWindowLabelFromConfig(extractTradeWindowConfig(params));
  }

  function extractTradeWindowConfig(params) {
    if (!params || typeof params !== "object") {
      return { windows: [], use_24h: false, intraday_only: true, has_windows: false };
    }
    const use24 = truthyParam(params.Use24hSession);
    const intradayOnly = params.IntradayOnly == null ? true : truthyParam(params.IntradayOnly);
    const windows = [];
    const start = parseHhmmParam(params.TradeStartTime);
    const end = parseHhmmParam(params.TradeEndTime);
    if (start && end) windows.push({ start, end });
    if (truthyParam(params.UseSecondTradeWindow)) {
      const s2 = parseHhmmParam(params.SecondTradeStartTime);
      const e2 = parseHhmmParam(params.SecondTradeEndTime);
      if (s2 && e2) windows.push({ start: s2, end: e2 });
    }
    return { windows, use_24h: use24, intraday_only: intradayOnly, has_windows: windows.length > 0 };
  }

  function resolveTradeWindow(view) {
    const rt = (view && view.runtime) || {};
    const prof = profileForStrategyView(view) || {};
    const rtParams = (rt.parameters && typeof rt.parameters === "object") ? rt.parameters
      : (rt.params && typeof rt.params === "object") ? rt.params : {};
    const locked = (view && view.locked_params) || prof.locked_parameters || rt.locked_params || {};
    const merged = mergeTradeWindowParams(locked, rtParams);
    let config = (view && view.trade_window) || null;
    if (!config || typeof config !== "object") config = extractTradeWindowConfig(merged);
    let label = "";
    if (config.use_24h) {
      label = "круглосуточно";
    } else if (config.has_windows) {
      label = buildTradeWindowLabelFromConfig(config);
    } else {
      label = String((view && view.trade_window_pt) || prof.trade_window_pt || "").trim();
      if (!label) label = buildTradeWindowPtFromParams(merged);
      else if (label.toLowerCase() !== "круглосуточно") label = reformatTradeWindowPtString(label);
    }
    return { label, config, merged };
  }

  function ptNowHhmm() {
    try {
      const parts = Object.fromEntries((PT_HHMM_PARTS_FORMATTER || new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Los_Angeles",
        hour: "2-digit", minute: "2-digit", hour12: false,
      })).formatToParts(new Date()).map(p => [p.type, p.value]));
      const h = Number.parseInt(parts.hour, 10);
      const m = Number.parseInt(parts.minute, 10);
      if (Number.isFinite(h) && Number.isFinite(m)) return h * 100 + m;
    } catch (_) { /* ignore */ }
    const d = new Date();
    return d.getHours() * 100 + d.getMinutes();
  }

  function isHhmmInTradeWindow(todHhmm, config) {
    if (!config || typeof config !== "object") return null;
    if (config.use_24h) return true;
    const windows = config.windows || [];
    if (!windows.length) return null;
    for (const w of windows) {
      const start = Number(w.start);
      const end = Number(w.end);
      if (start > 0 && end > 0 && todHhmm >= start && todHhmm <= end) return true;
    }
    return false;
  }

  /** Entry-window label + status for active-strategies table. */
  function computeTradeWindowState(view) {
    const tw = resolveTradeWindow(view);
    const label = tw.label || "";
    const enabled = !!(view && view.runtime_enabled && view.runtime_detected && !view._is_phantom);
    const inWindow = enabled ? isHhmmInTradeWindow(ptNowHhmm(), tw.config) : null;
    let tint = "";
    let statusBadge = '<span class="muted small">—</span>';
    if (!label && inWindow == null) {
      return { label: "—", tint, statusBadge, inWindow: null };
    }
    if (enabled && inWindow === true) {
      tint = "in";
      statusBadge = '<span class="badge ok tw-status-badge" title="Сейчас внутри окна входа (PT)">в окне</span>';
    } else if (enabled && inWindow === false) {
      tint = "out";
      statusBadge = '<span class="badge mut tw-status-badge" title="Включена, но вне окна входа (PT)">вне окна</span>';
    } else if (label && tw.config && tw.config.use_24h) {
      statusBadge = '<span class="badge ok tw-status-badge">24ч</span>';
    }
    return { label: label || "—", tint, statusBadge, inWindow };
  }

  function refreshTradeWindowVisuals() {
    document.querySelectorAll("#rt-strats-body tr[data-iid]").forEach(tr => {
      const view = findRuntimeView(tr.dataset.iid);
      if (!view) return;
      const st = computeTradeWindowState(view);
      tr.classList.remove("strategy-in-window", "strategy-out-window");
      if (st.tint === "in") tr.classList.add("strategy-in-window");
      else if (st.tint === "out") tr.classList.add("strategy-out-window");
      const badge = tr.querySelector(".tw-status-badge");
      if (badge) badge.outerHTML = st.statusBadge;
    });
  }

  /** Row belongs to selected calendar day if either PT wall or CME session key matches (orders use wall time; fills use exchange time). */
  function rowMatchesSelectedActivityDate(iso, targetDate) {
    if (!targetDate) return true;
    if (!iso) return false;
    return ptWallCalendarDate(iso) === targetDate || sessionDatePt(iso) === targetDate;
  }

  function utcGuessForPtYmd(y, m, d) {
    const key = dateKey(y, m, d);
    if (UTC_GUESS_FOR_PT_YMD_CACHE.has(key)) return new Date(UTC_GUESS_FOR_PT_YMD_CACHE.get(key));
    for (let h = 0; h < 24; h++) {
      const dt = new Date(Date.UTC(y, m - 1, d, h, 30, 0));
      if (ptWallCalendarDate(dt.toISOString()) === key) {
        UTC_GUESS_FOR_PT_YMD_CACHE.set(key, dt.getTime());
        return dt;
      }
    }
    const fallback = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
    UTC_GUESS_FOR_PT_YMD_CACHE.set(key, fallback.getTime());
    return fallback;
  }

  /** Next/previous America/Los_Angeles civil date (DST-safe). */
  function stepPtWallDay(ymdKey, deltaDays) {
    const p = parseDateKey(ymdKey);
    if (!p) return ymdKey;
    let t = utcGuessForPtYmd(p.year, p.month, p.day);
    const dir = deltaDays >= 0 ? 1 : -1;
    for (let n = 0; n < Math.abs(deltaDays); n++) {
      const curWall = ptWallCalendarDate(t.toISOString());
      let t2 = new Date(t.getTime() + dir * 3600000);
      for (let guard = 0; guard < 28; guard++) {
        const w = ptWallCalendarDate(t2.toISOString());
        if (w && w !== curWall) break;
        t2 = new Date(t2.getTime() + dir * 3600000);
      }
      t = t2;
    }
    return ptWallCalendarDate(t.toISOString()) || ymdKey;
  }

  function ptWeekdaySunday0(ymdKey) {
    const p = parseDateKey(ymdKey);
    if (!p) return 0;
    const t = utcGuessForPtYmd(p.year, p.month, p.day);
    try {
      const wd = PT_WEEKDAY_FORMATTER ? PT_WEEKDAY_FORMATTER.format(t) : "";
      return WEEKDAY_INDEX[wd] ?? 0;
    } catch (_) {
      return 0;
    }
  }

  function parseDateKey(key) {
    const m = String(key || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return null;
    return { year: Number(m[1]), month: Number(m[2]), day: Number(m[3]) };
  }

  function dateKey(year, month, day) {
    return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  }

  function addMonthsToDateKey(key, delta) {
    const p = parseDateKey(key) || parseDateKey(todaySessionDatePt());
    const d = new Date(Date.UTC(p.year, p.month - 1 + delta, 1));
    return dateKey(d.getUTCFullYear(), d.getUTCMonth() + 1, 1);
  }

  function monthTitle(key) {
    const p = parseDateKey(key) || parseDateKey(todaySessionDatePt());
    const d = new Date(Date.UTC(p.year, p.month - 1, 1));
    try {
      return RU_MONTH_FORMATTER ? RU_MONTH_FORMATTER.format(d) : `${String(p.month).padStart(2, "0")}.${p.year}`;
    } catch (_) {
      return `${String(p.month).padStart(2, "0")}.${p.year}`;
    }
  }

  function dayTitle(key) {
    const p = parseDateKey(key);
    if (!p) return "Выбранный день";
    const d = new Date(Date.UTC(p.year, p.month - 1, p.day));
    try {
      return RU_DAY_FORMATTER ? RU_DAY_FORMATTER.format(d) : key;
    } catch (_) {
      return key;
    }
  }

  function selectedAccountRow() {
    return (STATE.accounts || []).find(a => a.account_name === STATE.selectedAccount) ||
      pickActiveAccount();
  }

  function selectedAccountNameForData() {
    const a = selectedAccountRow();
    return (a && a.account_name) || STATE.selectedAccount || "";
  }

  function strategyTokenSet(view) {
    const rt = (view && view.runtime) || {};
    const raw = [
      view && view.strategy_id,
      view && view.display_name,
      view && view.runtime_instance_id,
      rt.strategy_id,
      rt.strategy_class,
      rt.strategy_name,
      rt.runtime_instance_id,
    ];
    (rt.legacy_strategy_ids || view?.legacy_strategy_ids || []).forEach(x => raw.push(x));
    return new Set(raw.map(x => String(x || "").trim().toLowerCase()).filter(Boolean));
  }

  function isUnmappedTelemetry(row) {
    const sid = String(row && row.strategy_id || "").trim().toLowerCase();
    const cls = String(row && row.strategy_class || "").trim().toLowerCase();
    const name = String(row && row.strategy_name || "").trim().toLowerCase();
    const iid = String(row && row.runtime_instance_id || "").trim();
    if (iid) return false;
    if (sid && !UNMAPPED_STRATEGY_MARKERS.has(sid)) return false;
    if (cls && !UNMAPPED_STRATEGY_MARKERS.has(cls)) return false;
    if (name && !UNMAPPED_STRATEGY_MARKERS.has(name)) return false;
    return true;
  }

  function strategyMarkerIsUsable(value) {
    const v = String(value || "").trim();
    return !!v && !UNMAPPED_STRATEGY_MARKERS.has(v.toLowerCase());
  }

  function entryStrategyFieldName(field) {
    return field === "runtime_instance_id" ? "entry_runtime_instance_id" : `entry_${field}`;
  }

  function effectiveStrategyField(closedOrRow, field) {
    if (!closedOrRow) return "";
    const primary = String(closedOrRow[field] || "").trim();
    if (strategyMarkerIsUsable(primary)) return primary;
    const entry = String(closedOrRow[entryStrategyFieldName(field)] || "").trim();
    return strategyMarkerIsUsable(entry) ? entry : "";
  }

  function isClosedTradeUnmapped(trade) {
    if (!trade) return true;
    return !["strategy_class", "strategy_id", "strategy_name", "runtime_instance_id"]
      .some(field => effectiveStrategyField(trade, field));
  }

  function attributionCandidates(row, fields) {
    const keys = fields || [
      "_strategy_attribution_candidates",
      "strategy_attribution_candidates",
      "entry_strategy_attribution_candidates",
    ];
    let raw = [];
    for (const key of keys) {
      const value = row && row[key];
      if (Array.isArray(value) && value.length) {
        raw = value;
        break;
      }
    }
    if (!Array.isArray(raw)) return [];
    return raw.map(c => {
      if (typeof c === "string") return c;
      return c && (c.strategy_class || c.strategy_name || c.strategy_id);
    }).map(x => String(x || "").trim()).filter(Boolean);
  }

  function attributionCandidateLabel(row, fields) {
    const cands = attributionCandidates(row, fields);
    if (!cands.length) return "";
    return cands.join(" / ") + (cands.length > 1 ? " (спорно)" : "");
  }

  function firstStrategyLabelFromFields(row, fields) {
    for (const field of fields) {
      const value = String(row && row[field] || "").trim();
      if (strategyMarkerIsUsable(value)) return value;
    }
    return "";
  }

  function closedTradeStrategyLabel(trade) {
    const exitLabel = firstStrategyLabelFromFields(trade, [
      "strategy_class", "strategy_name", "strategy_id", "runtime_instance_id",
    ]);
    if (exitLabel) return exitLabel;
    const entryLabel = firstStrategyLabelFromFields(trade, [
      "entry_strategy_class", "entry_strategy_name", "entry_strategy_id", "entry_runtime_instance_id",
    ]);
    if (entryLabel) return entryLabel;
    return attributionCandidateLabel(trade, ["_strategy_attribution_candidates", "strategy_attribution_candidates"]) ||
      attributionCandidateLabel(trade, ["entry_strategy_attribution_candidates"]) ||
      "Unmapped / неизвестная стратегия";
  }

  function rowMatchesStrategyView(row, view) {
    if (!row || !view) return false;
    const rt = view.runtime || {};
    const rowIid = effectiveStrategyField(row, "runtime_instance_id");
    const viewIid = String(view.runtime_instance_id || rt.runtime_instance_id || "").trim();
    if (rowIid && viewIid && rowIid === viewIid) return true;
    const tokens = strategyTokenSet(view);
    const candidates = [
      effectiveStrategyField(row, "strategy_id"),
      effectiveStrategyField(row, "strategy_class"),
      effectiveStrategyField(row, "strategy_name"),
    ].map(x => String(x || "").trim().toLowerCase()).filter(Boolean);
    return candidates.some(x => tokens.has(x));
  }

  function rowIsUnmappedCandidate(row, view) {
    if (!row || !view || !isUnmappedTelemetry(row)) return false;
    const rt = view.runtime || {};
    const acct = rt.account_name || view.account_name || "";
    if (acct && String(row.account_name || "").trim() !== String(acct).trim()) return false;
    const rowRoot = rootOf(row.instrument || "");
    const viewRoot = rootOf(rt.instrument || rt.contract_month || "");
    return !!rowRoot && !!viewRoot && rowRoot === viewRoot;
  }

  function rowEntryMatchesStrategyView(row, view) {
    if (!row || !view) return false;
    const rt = view.runtime || {};
    const rowIid = String(row.entry_runtime_instance_id || "").trim();
    const viewIid = String(view.runtime_instance_id || rt.runtime_instance_id || "").trim();
    if (rowIid && viewIid && rowIid === viewIid) return true;
    const tokens = strategyTokenSet(view);
    const candidates = [
      row.entry_strategy_id,
      row.entry_strategy_class,
      row.entry_strategy_name,
    ].map(x => String(x || "").trim().toLowerCase())
      .filter(x => x && !UNMAPPED_STRATEGY_MARKERS.has(x));
    if (candidates.some(x => tokens.has(x))) return true;
    const entryCands = attributionCandidates(row, ["entry_strategy_attribution_candidates"])
      .map(x => x.toLowerCase())
      .filter(x => x && !UNMAPPED_STRATEGY_MARKERS.has(x));
    return entryCands.length === 1 && tokens.has(entryCands[0]);
  }

  function closedUnmappedTradeMatchesStrategyView(row, view) {
    if (!row || !view || !isClosedTradeUnmapped(row)) return false;
    if (!rowEntryMatchesStrategyView(row, view)) return false;
    return rowIsUnmappedCandidate(row, view);
  }

  function executionSide(row) {
    const action = String(row.order_action || row.action || "").toLowerCase();
    if (action.includes("buy")) return 1;
    if (action.includes("sell")) return -1;
    const mp = String(row.market_position || "").toLowerCase();
    if (mp === "long") return 1;
    if (mp === "short") return -1;
    return 0;
  }

  function executionStrategyIdentity(row) {
    const raw = row.runtime_instance_id || row.strategy_class || row.strategy_id || "";
    const v = String(raw || "").trim().toLowerCase();
    if (v && !UNMAPPED_STRATEGY_MARKERS.has(v)) return v;
    const cands = attributionCandidates(row).map(x => x.toLowerCase()).sort();
    return cands.length ? `__legacy_candidates__:${cands.join("|")}` : "__unmapped__";
  }

  function executionLotKey(row) {
    return [
      String(row.account_name || "").trim().toLowerCase(),
      rootOf(row.instrument || ""),
      executionStrategyIdentity(row),
    ].join("|");
  }

  function executionAccountLotKey(row) {
    return [
      String(row.account_name || "").trim().toLowerCase(),
      rootOf(row.instrument || ""),
    ].join("|");
  }

  function executionHasLegacyAttribution(row) {
    if (!row) return false;
    return !!(
      row._strategy_attribution_confidence ||
      row.strategy_attribution_confidence ||
      attributionCandidates(row).length
    );
  }

  function lotsOpposeSignedQty(lots, signedQty) {
    return !!(lots && lots.length && Math.sign(Number(lots[0].qty) || 0) !== Math.sign(signedQty));
  }

  function firstLotTimestamp(lots) {
    if (!lots || !lots.length) return "";
    return String(lots[0].entry_ts || "");
  }

  function secondsBetweenIso(startIso, endIso) {
    if (!startIso || !endIso) return null;
    const a = new Date(String(startIso)).getTime();
    const b = new Date(String(endIso)).getTime();
    if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
    return Math.max(0, (b - a) / 1000);
  }

  function executionActionToken(row) {
    return String(row && (row.order_action || row.action) || "")
      .trim().toLowerCase().replace(/\s+/g, "");
  }

  function executionLooksCloseOnly(row) {
    const action = executionActionToken(row);
    if (action === "buytocover" || action === "sell") return true;
    if (action === "buy" || action === "sellshort") return false;
    const role = String(row && (row.role || row.position_action) || "").trim().toLowerCase();
    if (["exit", "close", "stop", "target", "manual"].includes(role)) return true;
    const label = String(row && (row.order_name || row.from_entry_signal || row.exit_reason) || "").toLowerCase();
    return /\b(stop|target|profit|timeexit|flat|exit|guard)\b/.test(label);
  }

  function tradePairIsTooOld(row, lot) {
    const durationSec = secondsBetweenIso(lot && lot.entry_ts, row && row.timestamp_utc);
    return durationSec != null && durationSec > MAX_INTRADAY_TRADE_HOLD_SECONDS
      ? durationSec
      : null;
  }

  function rejectedClosedTradeRecord(row, lot, signedQty, price, durationSec, reason) {
    const closeQty = Math.min(Math.abs(signedQty || 0), Math.abs(Number(lot && lot.qty) || 0)) || 0;
    const inst = row && row.instrument || "—";
    const mult = instrumentMultiplier(inst);
    const entryPrice = numOrNull(lot && lot.price);
    const exitPrice = numOrNull(price);
    let grossPnl = null;
    if (entryPrice != null && exitPrice != null && closeQty) {
      grossPnl = Number(lot.qty) > 0
        ? (exitPrice - entryPrice) * closeQty * mult
        : (entryPrice - exitPrice) * closeQty * mult;
    }
    return {
      timestamp_utc: row && row.timestamp_utc,
      exit_time_utc: row && row.timestamp_utc,
      entry_time_utc: lot && lot.entry_ts || null,
      date_pt: ptWallCalendarDate(row && row.timestamp_utc),
      account_name: row && row.account_name,
      instrument: inst,
      quantity: closeQty,
      entry_price: entryPrice,
      exit_price: exitPrice,
      gross_pnl: grossPnl,
      pnl: null,
      reason,
      duration_sec: durationSec,
      duration_label: fmtDurationSec(durationSec),
      strategy_id: row && row.strategy_id || "",
      strategy_class: row && row.strategy_class || "",
      strategy_name: row && row.strategy_name || "",
      runtime_instance_id: row && row.runtime_instance_id || "",
      entry_strategy_id: lot && lot.strategy_id || "",
      entry_strategy_class: lot && lot.strategy_class || "",
      entry_strategy_name: lot && lot.strategy_name || "",
      entry_runtime_instance_id: lot && lot.runtime_instance_id || "",
      entry_order_id: lot && lot.order_id || "",
      exit_order_id: row && row.order_id || "",
      entry_execution_id: lot && lot.execution_id || "",
      exit_execution_id: row && row.execution_id || "",
      order_name: row && row.order_name || "",
      from_entry_signal: row && row.from_entry_signal || "",
      rejected: true,
    };
  }

  function closingLotsForRow(lotsByKey, activeLotKey, accountLotKey, signedQty, rowUnmapped) {
    const lots = lotsByKey.get(activeLotKey) || [];
    if (lotsOpposeSignedQty(lots, signedQty) || !rowUnmapped) return { key: activeLotKey, lots };
    const prefix = `${accountLotKey}|`;
    const matches = [];
    for (const [key, altLots] of lotsByKey.entries()) {
      if (key === activeLotKey || !String(key).startsWith(prefix)) continue;
      if (lotsOpposeSignedQty(altLots, signedQty)) matches.push({ key, lots: altLots });
    }
    matches.sort((a, b) => firstLotTimestamp(a.lots).localeCompare(firstLotTimestamp(b.lots)));
    return matches.length ? matches[0] : { key: activeLotKey, lots };
  }

  function instrumentMultiplier(inst) {
    return FUTURES_MULTIPLIER[rootOf(inst)] || 1;
  }

  function reliableAccountRealizedPnl(acctRealized, executionNet, closedCount) {
    const ar = numOrNull(acctRealized);
    if (ar == null) return null;
    const eg = numOrNull(executionNet);
    if (!closedCount) return ar;
    if (Math.abs(ar) > 1e-9) {
      if (eg != null && Math.abs(eg) > 1e-9) {
        const drift = Math.abs(ar - eg);
        const tolerance = Math.max(3, 0.03 * Math.max(Math.abs(ar), Math.abs(eg)));
        if (drift > tolerance) return null;
      }
      return ar;
    }
    if (eg != null && Math.abs(eg) > 1e-9) return null;
    return ar;
  }

  function activeStartingCapitalForAccount(accountName) {
    const acct = String(accountName || "").trim();
    const vals = [];
    for (const view of (STATE.runtimeStrats || [])) {
      const rt = (view && view.runtime) || {};
      if (acct && String(rt.account_name || view.account_name || "").trim() !== acct) continue;
      const params = rt.params || rt.parameters || {};
      const v = numOrNull(params.StartingCapital);
      if (v != null && v > 0) vals.push(v);
    }
    for (const row of (STATE.runtimeRawStrats || [])) {
      if (acct && String(row.account_name || "").trim() !== acct) continue;
      const params = row.params || row.parameters || {};
      const v = numOrNull(params.StartingCapital);
      if (v != null && v > 0) vals.push(v);
    }
    if (!vals.length) return null;
    const first = vals[0];
    return vals.every(v => Math.abs(v - first) < 1e-9) ? first : null;
  }

  function accountEquityDeltaPnl(acct, accountName, executionNet, closedCount) {
    if (!acct || !closedCount) return null;
    const balance = numOrNull(acct.cash_value) ?? numOrNull(acct.net_liquidation);
    const start = activeStartingCapitalForAccount(accountName);
    if (balance == null || start == null) return null;
    const delta = balance - start;
    if (Math.abs(delta) < 1e-9) return null;
    const en = numOrNull(executionNet);
    if (en != null && Math.abs(en) > 1e-9) {
      const drift = Math.abs(delta - en);
      if (drift > Math.max(100, Math.abs(en) * 0.5)) return null;
    }
    return delta;
  }

  function accountPnlSourceLabel(m) {
    if (!m) return "—";
    if (m.accountRealizedUsed != null) return "source: NinjaTrader RealizedPnL";
    if (m.accountEquityDeltaPnl != null) return "source: cash/netliq - StartingCapital";
    return "source: FIFO execution net";
  }

  function accountAllTimeStats(m) {
    const closed = (m && m.allClosedTrades) || [];
    const executions = (m && m.executions) || [];
    const out = {
      startDate: PERFORMANCE_START_DATE_PT,
      startingCapital: PERFORMANCE_STARTING_CAPITAL,
      executions: executions.length,
      closed: closed.length,
      wins: 0,
      losses: 0,
      flats: 0,
      pnl: 0,
      gross: 0,
      commission: 0,
      balance: PERFORMANCE_STARTING_CAPITAL,
      tradingDays: new Set(),
      byInstrument: {},
    };
    for (const t of closed) {
      const pnl = Number(t.pnl || 0);
      out.pnl += pnl;
      out.gross += Number(t.gross_pnl ?? t.pnl ?? 0);
      out.commission += Number(t.commission || 0);
      if (pnl > 0) out.wins += 1;
      else if (pnl < 0) out.losses += 1;
      else out.flats += 1;
      const d = ptWallCalendarDate(t.timestamp_utc);
      if (d) out.tradingDays.add(d);
      const inst = t.instrument || "—";
      if (!out.byInstrument[inst]) out.byInstrument[inst] = { pnl: 0, trades: 0 };
      out.byInstrument[inst].pnl += pnl;
      out.byInstrument[inst].trades += 1;
    }
    out.balance = out.startingCapital + out.pnl;
    return out;
  }

  function tradeSourceKey(t) {
    return [
      t && t.account_name,
      t && t.instrument,
      t && t.entry_time_utc,
      t && (t.exit_time_utc || t.timestamp_utc),
      t && t.entry_order_id,
      t && t.exit_order_id,
      t && t.entry_execution_id,
      t && t.exit_execution_id,
      t && t.quantity,
      t && t.entry_price,
      t && t.exit_price,
    ].map(x => String(x == null ? "" : x)).join("|");
  }

  function simpleHash16(text) {
    let h1 = 0x811c9dc5;
    let h2 = 0x01000193;
    const s = String(text || "");
    for (let i = 0; i < s.length; i += 1) {
      const c = s.charCodeAt(i);
      h1 ^= c;
      h1 = Math.imul(h1, 0x01000193);
      h2 = Math.imul(h2 ^ c, 0x85ebca6b);
    }
    return ((h1 >>> 0).toString(16).padStart(8, "0") + (h2 >>> 0).toString(16).padStart(8, "0")).slice(0, 16);
  }

  function assignTradeNumbers(trades) {
    const sorted = (Array.isArray(trades) ? trades : []).slice().sort((a, b) => {
      const at = String((a && (a.exit_time_utc || a.timestamp_utc)) || "");
      const bt = String((b && (b.exit_time_utc || b.timestamp_utc)) || "");
      if (at !== bt) return at.localeCompare(bt);
      return String((a && a.entry_time_utc) || "").localeCompare(String((b && b.entry_time_utc) || ""));
    });
    const counters = {};
    for (const t of sorted) {
      const acct = String(t.account_name || "account").trim() || "account";
      counters[acct] = (counters[acct] || 0) + 1;
      t.trade_no = counters[acct];
      t.trade_id = `${acct}|${simpleHash16(tradeSourceKey(t))}`;
    }
    return trades;
  }

  function executionCommissionAmount(row) {
    const c = numOrNull(row && row.commission);
    return c == null ? 0 : Math.abs(c);
  }

  function runtimeParamRows() {
    const out = [];
    for (const view of (STATE.runtimeStrats || [])) {
      const rt = (view && view.runtime) || {};
      out.push(rt);
      out.push(view);
    }
    for (const row of (STATE.runtimeRawStrats || [])) out.push(row);
    return out.filter(Boolean);
  }

  function identityTokens(row) {
    const vals = [
      row && row.runtime_instance_id,
      row && row.strategy_class,
      row && row.strategy_id,
      row && row.strategy_name,
    ];
    return new Set(vals.map(x => String(x || "").trim().toLowerCase())
      .filter(x => x && !UNMAPPED_STRATEGY_MARKERS.has(x)));
  }

  function roundTurnCommissionForExecution(row) {
    const tokens = identityTokens(row);
    const acct = String(row && row.account_name || "").trim();
    const instRoot = rootOf(row && row.instrument || "");
    const exact = [];
    const scoped = [];
    for (const rr of runtimeParamRows()) {
      const params = rr.params || rr.parameters || {};
      const rtc = numOrNull(params.RoundTurnCommission);
      if (rtc == null || rtc < 0) continue;
      const rrTokens = identityTokens(rr);
      const hasExact = tokens.size && [...rrTokens].some(t => tokens.has(t));
      if (hasExact) {
        exact.push(rtc);
        continue;
      }
      const rrAcct = String(rr.account_name || "").trim();
      const rrRoot = rootOf(rr.instrument || rr.contract_month || "");
      if ((!acct || !rrAcct || rrAcct === acct) && instRoot && rrRoot === instRoot) {
        scoped.push(rtc);
      }
    }
    if (exact.length) return Math.max(...exact);
    if (scoped.length) return Math.max(...scoped);
    return DEFAULT_ROUND_TURN_COMMISSION;
  }

  function annotateExecutionsWithPnl(rows, options = {}) {
    const strategyScoped = options.strategyScoped !== false;
    const out = (Array.isArray(rows) ? rows : []).map(r => ({
      ...r,
      _estimated_pnl: null,
      _closed_qty: 0,
      _opened_qty: 0,
      _fill_role: "",
    }));
    const sorted = out.slice().sort((a, b) => String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || "")));
    const lotsByKey = new Map();
    const closedTrades = [];
    const rejectedClosedTrades = [];
    for (const r of sorted) {
      const inst = r.instrument || "—";
      const qtyAbs = Math.abs(numOrNull(r.quantity) || 0);
      const price = numOrNull(r.price);
      const side = executionSide(r);
      if (!qtyAbs || price == null || !side) continue;
      let signedQty = side * qtyAbs;
      const fillCommission = executionCommissionAmount(r);
      const fillCommissionPerContract = qtyAbs ? (fillCommission / qtyAbs) : 0;
      let fillCommissionConsumed = 0;
      const lotKey = executionLotKey(r);
      const accountLotKey = executionAccountLotKey(r);
      const activeLotKey = strategyScoped || executionHasLegacyAttribution(r) ? lotKey : accountLotKey;
      const baseLots = lotsByKey.get(activeLotKey) || [];
      lotsByKey.set(activeLotKey, baseLots);
      const rowUnmapped = isUnmappedTelemetry(r);
      let rowPnl = 0;
      let rowGrossPnl = 0;
      let rowCommission = 0;
      let rowRejectedCount = 0;
      while (signedQty !== 0) {
        const closeMatch = closingLotsForRow(lotsByKey, activeLotKey, accountLotKey, signedQty, rowUnmapped);
        const lots = closeMatch.lots;
        if (!lotsOpposeSignedQty(lots, signedQty)) break;
        const lot = lots[0];
        const staleDurationSec = tradePairIsTooOld(r, lot);
        if (staleDurationSec != null) {
          rejectedClosedTrades.push(rejectedClosedTradeRecord(
            r, lot, signedQty, price, staleDurationSec, "stale_intraday_pair"));
          rowRejectedCount += 1;
          r._pnl_rejected_reason = "stale_intraday_pair";
          r._pnl_rejected_duration_sec = staleDurationSec;
          lots.shift();
          continue;
        }
        const closeQty = Math.min(Math.abs(signedQty), Math.abs(lot.qty));
        const mult = instrumentMultiplier(inst);
        const grossPnl = lot.qty > 0
          ? (price - lot.price) * closeQty * mult
          : (lot.price - price) * closeQty * mult;
        const entryCommission = Math.min(
          Math.abs(lot.commission_remaining || 0),
          Math.abs(lot.commission_per_contract || 0) * closeQty);
        const exitCommission = fillCommissionPerContract * closeQty;
        fillCommissionConsumed += exitCommission;
        if (entryCommission) lot.commission_remaining = Math.max(0, Math.abs(lot.commission_remaining || 0) - entryCommission);
        const actualCommission = entryCommission + exitCommission;
        const estimatedCommission = roundTurnCommissionForExecution(r) * closeQty;
        const commission = actualCommission > 1e-9 ? actualCommission : estimatedCommission;
        const commissionSource = actualCommission > 1e-9 ? "execution_commission" : "round_turn_estimate";
        const direction = lot.qty > 0 ? "long" : "short";
        const pnl = grossPnl - commission;
        rowGrossPnl += grossPnl;
        rowCommission += commission;
        rowPnl += pnl;
        r._closed_qty += closeQty;
        const closedTrade = {
          timestamp_utc: r.timestamp_utc,
          exit_time_utc: r.timestamp_utc,
          entry_time_utc: lot.entry_ts || null,
          date_pt: ptWallCalendarDate(r.timestamp_utc),
          account_name: r.account_name,
          instrument: inst,
          direction,
          quantity: closeQty,
          entry_price: lot.price,
          exit_price: price,
          gross_pnl: grossPnl,
          commission,
          commission_source: commissionSource,
          pnl,
          action: r.order_action || r.market_position || "",
          role: r.role || r.position_action || "exit",
          exit_reason: r.exit_reason || "",
          strategy_id: r.strategy_id || "",
          strategy_class: r.strategy_class || "",
          strategy_name: r.strategy_name || "",
          runtime_instance_id: r.runtime_instance_id || "",
          strategy_attribution_confidence: r._strategy_attribution_confidence || "",
          strategy_attribution_source: r._strategy_attribution_source || "",
          strategy_attribution_candidates: r._strategy_attribution_candidates || [],
          entry_strategy_id: lot.strategy_id || "",
          entry_strategy_class: lot.strategy_class || "",
          entry_strategy_name: lot.strategy_name || "",
          entry_runtime_instance_id: lot.runtime_instance_id || "",
          entry_strategy_attribution_confidence: lot.strategy_attribution_confidence || "",
          entry_strategy_attribution_source: lot.strategy_attribution_source || "",
          entry_strategy_attribution_candidates: lot.strategy_attribution_candidates || [],
          entry_order_id: lot.order_id || "",
          exit_order_id: r.order_id || "",
          entry_execution_id: lot.execution_id || "",
          exit_execution_id: r.execution_id || "",
          order_name: r.order_name || "",
          from_entry_signal: r.from_entry_signal || "",
        };
        ["strategy_id", "strategy_class", "strategy_name", "runtime_instance_id"].forEach(field => {
          closedTrade[field] = effectiveStrategyField(closedTrade, field);
        });
        closedTrade.unmapped = isClosedTradeUnmapped(closedTrade);
        closedTrades.push(closedTrade);
        lot.qty += Math.sign(lot.qty) * -closeQty;
        signedQty += Math.sign(signedQty) * -closeQty;
        if (Math.abs(lot.qty) < 1e-9) lots.shift();
      }
      if (Math.abs(rowPnl) > 1e-9) r._estimated_pnl = rowPnl;
      if (Math.abs(rowGrossPnl) > 1e-9) r._gross_pnl = rowGrossPnl;
      if (Math.abs(rowCommission) > 1e-9) r._commission = rowCommission;
      if (rowRejectedCount) r._pnl_rejected_count = rowRejectedCount;
      if (Math.abs(signedQty) > 1e-9) {
        if (executionLooksCloseOnly(r) && !r._opened_qty) {
          r._unmatched_exit_qty = (r._unmatched_exit_qty || 0) + Math.abs(signedQty);
          r._pnl_rejected_reason = r._pnl_rejected_reason || "unmatched_exit";
          signedQty = 0;
          r._fill_role = r._closed_qty ? "exit" : "unmatched_exit";
          continue;
        }
        r._opened_qty += Math.abs(signedQty);
        const remainingCommission = Math.max(0, fillCommission - fillCommissionConsumed);
        baseLots.push({
          qty: signedQty,
          price,
          entry_ts: r.timestamp_utc,
          strategy_id: r.strategy_id || "",
          strategy_class: r.strategy_class || "",
          strategy_name: r.strategy_name || "",
          runtime_instance_id: r.runtime_instance_id || "",
          strategy_attribution_confidence: r._strategy_attribution_confidence || "",
          strategy_attribution_source: r._strategy_attribution_source || "",
          strategy_attribution_candidates: r._strategy_attribution_candidates || [],
          order_id: r.order_id || "",
          execution_id: r.execution_id || "",
          commission_remaining: remainingCommission,
          commission_per_contract: Math.abs(signedQty) > 1e-9
            ? remainingCommission / Math.abs(signedQty)
            : 0,
        });
      }
      r._fill_role = r._unmatched_exit_qty ? "unmatched_exit"
        : r._closed_qty && r._opened_qty ? "reverse"
        : r._closed_qty ? "exit"
        : r._opened_qty ? "entry"
        : "";
    }
    assignTradeNumbers(closedTrades);
    assignTradeNumbers(rejectedClosedTrades);
    return { executions: out, closedTrades, rejectedClosedTrades };
  }

  function accountMetricsCacheKey() {
    const execs = STATE.accountExecs || [];
    const orders = STATE.accountOrders || [];
    return [
      STATE.accountActivityRevision || 0,
      STATE.accountsRevision || 0,
      selectedAccountNameForData() || "",
      STATE.selectedDatePt || "",
      execs.length,
      orders.length,
    ].join("|");
  }

  function computeAccountMetrics(force) {
    const cacheKey = accountMetricsCacheKey();
    if (!force && STATE.accountMetrics && STATE.accountMetrics._cacheKey === cacheKey) {
      return STATE.accountMetrics;
    }
    const acct = selectedAccountRow();
    const accountName = selectedAccountNameForData();
    // today = PT wall calendar (aligns with NT "cash day"); sessionToday = CME session key from market clock.
    const today = todayWallPtDate();
    const sessionToday = todaySessionDatePt();
    const selectedDate = STATE.selectedDatePt || today;
    const execs = (STATE.accountExecs || []).filter(r =>
      (!accountName || r.account_name === accountName) &&
      isPerformanceWindowTimestamp(r.timestamp_utc));
    const orders = (STATE.accountOrders || []).filter(r =>
      (!accountName || r.account_name === accountName) &&
      isPerformanceWindowTimestamp(r.timestamp_utc));
    const paired = annotateExecutionsWithPnl(execs, { strategyScoped: false });
    const strategyPaired = annotateExecutionsWithPnl(execs, { strategyScoped: true });
    const executions = paired.executions;
    const strategyExecutions = strategyPaired.executions;
    const todayExecs = executions.filter(r => ptWallCalendarDate(r.timestamp_utc) === today);
    const selectedExecs = executions.filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, selectedDate));
    const closedToday = paired.closedTrades.filter(r => ptWallCalendarDate(r.timestamp_utc) === today);
    const selectedClosedTrades = paired.closedTrades.filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, selectedDate));
    const strategyTodayExecs = strategyExecutions.filter(r => ptWallCalendarDate(r.timestamp_utc) === today);
    const strategySelectedExecs = strategyExecutions.filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, selectedDate));
    const strategyClosedToday = strategyPaired.closedTrades.filter(r => ptWallCalendarDate(r.timestamp_utc) === today);
    const strategySelectedClosedTrades = strategyPaired.closedTrades.filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, selectedDate));
    const execNet = closedToday.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
    const execGross = closedToday.reduce((acc, r) => acc + (numOrNull(r.gross_pnl) ?? numOrNull(r.pnl) ?? 0), 0);
    const execCommission = closedToday.reduce((acc, r) => acc + (numOrNull(r.commission) || 0), 0);
    const selectedExecNet = selectedClosedTrades.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
    const selectedExecGross = selectedClosedTrades.reduce((acc, r) => acc + (numOrNull(r.gross_pnl) ?? numOrNull(r.pnl) ?? 0), 0);
    const selectedExecCommission = selectedClosedTrades.reduce((acc, r) => acc + (numOrNull(r.commission) || 0), 0);
    const acctRealizedRaw = acct ? numOrNull(acct.realized_pnl) : null;
    const acctRealized = reliableAccountRealizedPnl(acctRealizedRaw, execNet, closedToday.length);
    const acctEquityDelta = accountEquityDeltaPnl(acct, accountName, execNet, closedToday.length);
    const todayPnl = acctRealized != null ? acctRealized
      : acctEquityDelta != null ? acctEquityDelta
      : execNet;
    const selectedPnl = selectedDate === today ? todayPnl : selectedExecNet;
    const instruments = [...new Set(todayExecs.map(r => r.instrument).filter(Boolean))].sort();
    const selectedInstruments = [...new Set(selectedExecs.map(r => r.instrument).filter(Boolean))].sort();
    const byInstrument = {};
    for (const t of closedToday) {
      const inst = t.instrument || "—";
      if (!byInstrument[inst]) byInstrument[inst] = { pnl: 0, trades: 0 };
      byInstrument[inst].pnl += Number(t.pnl || 0);
      byInstrument[inst].trades += 1;
    }
    // When NinjaTrader replays fills, FIFO net can diverge from account RealizedPnL.
    // Scale per-instrument bars (today) so their sum matches the account when drift is large.
    const authoritativeTodayPnl = acctRealized != null ? acctRealized : acctEquityDelta;
    if (authoritativeTodayPnl != null && Number.isFinite(authoritativeTodayPnl) && Math.abs(execNet) > 1e-6) {
      const drift = Math.abs(execNet - authoritativeTodayPnl);
      const thr = Math.max(3, 0.03 * Math.max(Math.abs(execNet), Math.abs(authoritativeTodayPnl)));
      if (drift > thr) {
        const k = authoritativeTodayPnl / execNet;
        for (const inst of Object.keys(byInstrument)) {
          byInstrument[inst].pnl *= k;
        }
      }
    }
    const daily = {};
    const ensureDay = (datePt) => {
      if (!datePt) return null;
      if (!daily[datePt]) {
        daily[datePt] = {
        date_pt: datePt, executions: [], closedTrades: [], pnl: 0,
        gross_pnl: 0, commission: 0, pnl_source: "execution_net", wins: 0, losses: 0, flats: 0,
          unmapped: 0, duplicates_ignored: 0, instruments: new Set(),
        };
      }
      return daily[datePt];
    };
    executions.forEach(r => {
      const d = ensureDay(sessionDatePt(r.timestamp_utc));
      if (!d) return;
      d.executions.push(r);
      if (r.instrument) d.instruments.add(r.instrument);
      if (isUnmappedTelemetry(r)) d.unmapped += 1;
      d.duplicates_ignored += Number(r._duplicates_ignored || 0);
    });
    paired.closedTrades.forEach(t => {
      const d = ensureDay(sessionDatePt(t.timestamp_utc));
      if (!d) return;
      d.closedTrades.push(t);
      d.pnl += Number(t.pnl || 0);
      d.gross_pnl += Number(t.gross_pnl ?? t.pnl ?? 0);
      d.commission += Number(t.commission || 0);
      if (Number(t.pnl || 0) > 0) d.wins += 1;
      else if (Number(t.pnl || 0) < 0) d.losses += 1;
      else d.flats += 1;
    });
    Object.values(daily).forEach(d => {
      d.instruments = [...d.instruments].sort();
    });
    const dailyWall = {};
    const ensureDayWall = (datePt) => {
      if (!datePt) return null;
      if (!dailyWall[datePt]) {
        dailyWall[datePt] = {
          date_pt: datePt, executions: [], closedTrades: [], pnl: 0,
          gross_pnl: 0, commission: 0, pnl_source: "execution_net", wins: 0, losses: 0, flats: 0,
          unmapped: 0, duplicates_ignored: 0, instruments: new Set(),
        };
      }
      return dailyWall[datePt];
    };
    executions.forEach(r => {
      const dw = ensureDayWall(ptWallCalendarDate(r.timestamp_utc));
      if (!dw) return;
      dw.executions.push(r);
      if (r.instrument) dw.instruments.add(r.instrument);
      if (isUnmappedTelemetry(r)) dw.unmapped += 1;
      dw.duplicates_ignored += Number(r._duplicates_ignored || 0);
    });
    paired.closedTrades.forEach(t => {
      const dw = ensureDayWall(ptWallCalendarDate(t.timestamp_utc));
      if (!dw) return;
      dw.closedTrades.push(t);
      dw.pnl += Number(t.pnl || 0);
      dw.gross_pnl += Number(t.gross_pnl ?? t.pnl ?? 0);
      dw.commission += Number(t.commission || 0);
      if (Number(t.pnl || 0) > 0) dw.wins += 1;
      else if (Number(t.pnl || 0) < 0) dw.losses += 1;
      else dw.flats += 1;
    });
    Object.values(dailyWall).forEach(d => {
      d.instruments = [...d.instruments].sort();
    });
    if (acctRealized != null) {
      // Only write to session-keyed daily when session date matches wall date.
      // After ~15:00 PT the CME session rolls to the next calendar day
      // (sessionToday becomes tomorrow), so we must not write today's P&L
      // into tomorrow's daily slot — the calendar would show it on the wrong cell.
      if (sessionToday === today) {
        const dS = ensureDay(sessionToday);
        if (dS) {
          dS.pnl = acctRealized;
          dS.pnl_source = "account_realized";
          dS.execution_gross = execGross;
          dS.execution_net = execNet;
          dS.commission = execCommission;
        }
      }
      const dWall = ensureDayWall(today);
      if (dWall) {
        dWall.pnl = acctRealized;
        dWall.pnl_source = "account_realized";
        dWall.execution_gross = execGross;
        dWall.execution_net = execNet;
        dWall.commission = execCommission;
      }
    } else if (acctEquityDelta != null) {
      if (sessionToday === today) {
        const dS = ensureDay(sessionToday);
        if (dS) {
          dS.pnl = acctEquityDelta;
          dS.pnl_source = "account_cash_delta";
          dS.execution_gross = execGross;
          dS.execution_net = execNet;
          dS.commission = execCommission;
        }
      }
      const dWall = ensureDayWall(today);
      if (dWall) {
        dWall.pnl = acctEquityDelta;
        dWall.pnl_source = "account_cash_delta";
        dWall.execution_gross = execGross;
        dWall.execution_net = execNet;
        dWall.commission = execCommission;
      }
    }
    const selectedDay = dailyWall[selectedDate] || daily[selectedDate] || {
      date_pt: selectedDate, executions: selectedExecs, closedTrades: selectedClosedTrades,
      pnl: selectedDate === today ? todayPnl : selectedExecNet,
      pnl_source: selectedDate === today
        ? (acctRealized != null ? "account_realized" : (acctEquityDelta != null ? "account_cash_delta" : "execution_net"))
        : "execution_net",
      wins: 0, losses: 0, flats: 0, unmapped: 0, duplicates_ignored: 0, instruments: [],
      execution_gross: selectedExecGross,
      execution_net: selectedExecNet,
      commission: selectedExecCommission,
    };
    const wins = closedToday.filter(t => Number(t.pnl || 0) > 0).length;
    const losses = closedToday.filter(t => Number(t.pnl || 0) < 0).length;
    const flats = closedToday.filter(t => Number(t.pnl || 0) === 0).length;
    const selectedWins = selectedClosedTrades.filter(t => Number(t.pnl || 0) > 0).length;
    const selectedLosses = selectedClosedTrades.filter(t => Number(t.pnl || 0) < 0).length;
    const selectedFlats = selectedClosedTrades.filter(t => Number(t.pnl || 0) === 0).length;
    const unmappedToday = todayExecs.filter(isUnmappedTelemetry).length;
    const orderCounts = {};
    const ordersByWall = {};
    for (const o of orders) {
      const wallDate = ptWallCalendarDate(o.timestamp_utc);
      if (!wallDate) continue;
      if (!ordersByWall[wallDate]) ordersByWall[wallDate] = { ids: new Set(), rows: 0 };
      const oid = String(o.order_id || "").trim();
      if (oid) ordersByWall[wallDate].ids.add(oid);
      ordersByWall[wallDate].rows += 1;
      if (wallDate !== today) continue;
      const st = String(o.order_state || "—").toLowerCase();
      orderCounts[st] = (orderCounts[st] || 0) + 1;
    }
    const orderCountsByWallDate = {};
    for (const [datePt, v] of Object.entries(ordersByWall)) {
      orderCountsByWallDate[datePt] = v.ids.size || v.rows;
    }
    const metrics = {
      account: acct || null,
      accountName,
      date_pt: today,
      selectedDatePt: selectedDate,
      executions,
      strategyExecutions,
      todayExecs,
      strategyTodayExecs,
      selectedExecs,
      strategySelectedExecs,
      closedTrades: closedToday,
      allClosedTrades: paired.closedTrades,
      rejectedClosedTrades: paired.rejectedClosedTrades || [],
      strategyClosedTrades: strategyClosedToday,
      allStrategyClosedTrades: strategyPaired.closedTrades,
      strategyRejectedClosedTrades: strategyPaired.rejectedClosedTrades || [],
      selectedClosedTrades,
      strategySelectedClosedTrades,
      todayPnl,
      selectedPnl,
      executionGross: execGross,
      executionNet: execNet,
      executionCommission: execCommission,
      selectedExecutionGross: selectedExecGross,
      selectedExecutionNet: selectedExecNet,
      selectedExecutionCommission: selectedExecCommission,
      accountRealizedRaw: acctRealizedRaw,
      accountRealizedUsed: acctRealized,
      accountEquityDeltaPnl: acctEquityDelta,
      tradesCount: todayExecs.length,
      closedTradesCount: closedToday.length,
      selectedTradesCount: selectedExecs.length,
      selectedClosedTradesCount: selectedClosedTrades.length,
      wins,
      losses,
      flats,
      selectedWins,
      selectedLosses,
      selectedFlats,
      instruments,
      selectedInstruments,
      byInstrument,
      unmappedToday,
      selectedUnmapped: selectedExecs.filter(isUnmappedTelemetry).length,
      selectedDay,
      daily,
      dailyWall,
      orderCounts,
      orderCountsByWallDate,
      executionDedupe: STATE.executionDedupeMeta || {},
      orderDedupe: STATE.orderDedupeMeta || {},
    };
    Object.defineProperty(metrics, "_cacheKey", { value: cacheKey, enumerable: false });
    STATE.accountMetrics = metrics;
    return metrics;
  }

  const SYSTEM_ACCOUNTS = new Set(["backtest", "sim101", "playback101"]);
  function isSystemAccount(a) {
    const name = String((a && a.account_name) || "").trim().toLowerCase();
    return SYSTEM_ACCOUNTS.has(name) || !!(a && a.is_system);
  }
  function isOnlineSelectableAccount(a) {
    if (!a || isSystemAccount(a)) return false;
    const mode = String(a.account_mode || "").toLowerCase();
    const name = String(a.account_name || "").toUpperCase();
    if (a.is_selectable_for_online === true) return true;
    if (name === "DEMO3369390") return true;
    return mode === "demo" || mode === "paper" || mode === "playback" || mode === "live";
  }

  const STATE = {
    accounts: [],
    catalog: null,
    strategies: [],
    runtimeStrats: [],
    runtimeRawStrats: [],
    selectedAccount: null,
    selectedStrategy: "NTAMicroVwapRiskPilot",
    selectedRuntime: null,
    instruments: [],
    instrumentFilter: "",
    instrumentGroup: "__all__",
    instOnlyCurrent: true,
    instShowExpired: false,
    selectedInstrument: "MNQ 06-26",
    timer: null,
    bridgeOnline: false,
    showHiddenStrategies: false,
    displayPrefs: { hidden_classes: [] },
    // Phase 6 — command pipeline live status
    activeCommand: null,    // { command_id, command, submitted_at_utc }
    cmdPollTimer: null,
    // Phase 6.7 — selection vs runtime diff for the currently-selected row
    selectionDiff: null,
    // Phase 9 — paper status
    paperJournal: null,
    // Account-level trading picture. These rows are intentionally independent
    // from strategy_id because older bridge builds write "" or signal names.
    accountExecs: [],
    accountOrders: [],
    positions: {},
    accountMetrics: null,
    accountActivityRevision: 0,
    accountsRevision: 0,
    executionDedupeMeta: {},
    orderDedupeMeta: {},
    selectedDatePt: todayWallPtDate(),
    calendarMonthPt: todayWallPtDate().slice(0, 7) + "-01",
    dayExplicitlySelected: false,
    bottomTab: "overview",
    tradeMode: "account",
    tableSorts: loadTradingTableSorts(),
    orderMode: "account",
    orderStatusFilter: "__all__",
    orderInstrumentFilter: "__all__",
    analyticsRenderSeq: 0,
    runtimeHistorySessions: [],
    strategyStartDates: {},
    // Approved Strategy Profiles (from /api/profiles). Used to build the
    // "Active strategies" list so that approved cells stay visible even when
    // their NinjaTrader instance is disabled. The list is overlaid with
    // runtime rows so each row carries cell # + live state when available.
    profiles: [],
    phantomRows: [],
  };

  const instrumentName = (i) =>
    i && (i.instrument || i.full_name || i.display || i.symbol || i.name || "");

  const instrumentGroup = (i) =>
    i && (i.group || i.category || i.exchange || "");

  // ----- API helpers --------------------------------------------------------
  const api = async (url, opts = {}) => {
    const r = await fetch(url, opts);
    const txt = await r.text();
    let json = null;
    try { json = txt ? JSON.parse(txt) : null; } catch (e) { json = null; }
    if (!r.ok) {
      const msg = (json && (json.error || json.detail)) || txt || ("HTTP " + r.status);
      throw new Error(msg);
    }
    return json;
  };

  function findRuntimeView(id) {
    if (!id) return undefined;
    const live = (STATE.runtimeStrats || []).find(s =>
      s.runtime_instance_id === id || s.strategy_id === id);
    if (live) return live;
    return (STATE.phantomRows || []).find(s =>
      s.runtime_instance_id === id || s.strategy_id === id);
  }

  // --- Approved-profile cells (CELL-NNN) overlay ---------------------------
  // Build a merged "Active strategies" list: every approved profile (with a
  // cell_id) is shown, with live runtime data overlaid when matched by class
  // name. Profiles without a running runtime instance appear as phantom rows
  // (greyed out) so the user can still inspect their stats.
  function profileApprovedCellId(p) {
    if (!p || typeof p !== "object") return "";
    return String(p.cell_id || "").trim();
  }
  function cellIdNumber(cell) {
    const m = String(cell || "").match(/(\d+)$/);
    return m ? parseInt(m[1], 10) : Number.POSITIVE_INFINITY;
  }
  function profileClassCandidates(p) {
    const out = [];
    const push = (v) => { const s = String(v || "").trim().toLowerCase(); if (s) out.push(s); };
    push(p && p.deploy_strategy_class);
    push(p && p.strategy_class);
    push(p && p.stable_id);
    if (Array.isArray(p && p.runtime_strategy_classes)) {
      for (const v of p.runtime_strategy_classes) push(v);
    }
    return out;
  }
  function profileIdentityCandidates(p) {
    const out = [];
    const push = (v) => { const s = String(v || "").trim().toLowerCase(); if (s) out.push(s); };
    push(p && p.profile_id);
    push(p && p.strategy_id);
    push(p && p.stable_id);
    push(p && p.cell_id);
    return out;
  }
  function viewProfileClassCandidates(view) {
    const out = [];
    const push = (v) => { const s = String(v || "").trim().toLowerCase(); if (s) out.push(s); };
    const rt = (view && view.runtime) || {};
    push(rt.strategy_class);
    push(view && view.display_key);
    push(view && view.strategy_id);
    push(rt.strategy_id);
    push(rt.strategy_name);
    push(view && view.cell_id);
    return [...new Set(out)];
  }
  function viewProfileIdentityCandidates(view) {
    const out = [];
    const push = (v) => { const s = String(v || "").trim().toLowerCase(); if (s) out.push(s); };
    const rt = (view && view.runtime) || {};
    push(view && view.strategy_id);
    push(rt.strategy_id);
    push(view && view.runtime_instance_id);
    push(rt.runtime_instance_id);
    push(view && view.cell_id);
    return [...new Set(out)];
  }
  function profileForStrategyView(view) {
    if (!view) return null;
    const profiles = (STATE.profiles || []).concat(view.profile_ref ? [view.profile_ref] : []);
    const classKeys = viewProfileClassCandidates(view);
    const idKeys = viewProfileIdentityCandidates(view);
    const rt = (view && view.runtime) || {};
    const root = rootOf(rt.instrument || rt.contract_month || "");
    const tf = String(rt.timeframe || "").trim().toLowerCase();
    let best = null;
    let bestScore = -1;
    for (const p of profiles) {
      if (!p || typeof p !== "object") continue;
      let score = 0;
      const pDeploy = String(p.deploy_strategy_class || "").trim().toLowerCase();
      const pStrategy = String(p.strategy_class || "").trim().toLowerCase();
      const runtimeClasses = Array.isArray(p.runtime_strategy_classes)
        ? p.runtime_strategy_classes.map(x => String(x || "").trim().toLowerCase()).filter(Boolean)
        : [];
      if (pDeploy && classKeys.includes(pDeploy)) score += 120;
      if (runtimeClasses.some(k => classKeys.includes(k))) score += 110;
      if (pStrategy && classKeys.includes(pStrategy)) score += 90;
      if (profileIdentityCandidates(p).some(k => idKeys.includes(k))) score += 80;
      const pRoot = rootOf(p.instrument || p.current_contract || "");
      const pTf = String(p.timeframe || "").trim().toLowerCase();
      if (root && pRoot === root) score += 10;
      if (tf && pTf === tf) score += 5;
      if (p.metrics && Object.keys(p.metrics).length) score += 2;
      if (p === view.profile_ref) score += 1;
      if (score > bestScore) {
        best = p;
        bestScore = score;
      }
    }
    if (best && bestScore > 0) return best;
    const byInstrTf = profiles.filter(p => {
      const pRoot = rootOf(p && (p.instrument || p.current_contract || ""));
      const pTf = String((p && p.timeframe) || "").trim().toLowerCase();
      return root && pRoot === root && (!tf || !pTf || pTf === tf);
    });
    return byInstrTf.length === 1 ? byInstrTf[0] : null;
  }
  function runtimeMatchesProfile(rtRow, profile) {
    const rt = (rtRow && rtRow.runtime) || {};
    const cls = String(rt.strategy_class || "").trim().toLowerCase();
    if (!cls) return false;
    return profileClassCandidates(profile).includes(cls);
  }
  function approvedProfiles() {
    const ready = new Set(["ready", "paper_ready"]);
    return (STATE.profiles || []).filter(p =>
      p && profileApprovedCellId(p) && ready.has(String(p.status || "").trim().toLowerCase())
    );
  }
  function rebuildPhantomRows() {
    const live = STATE.runtimeStrats || [];
    const usedRuntimeIds = new Set();
    const phantoms = [];
    for (const p of approvedProfiles()) {
      const match = live.find(rt => runtimeMatchesProfile(rt, p));
      if (match) {
        match.cell_id = match.cell_id || profileApprovedCellId(p);
        match.cell_num = cellIdNumber(match.cell_id);
        match.profile_ref = p;
        usedRuntimeIds.add(match.runtime_instance_id || match.strategy_id);
      } else {
        const cls = String(p.deploy_strategy_class || p.strategy_class || "").trim();
        const sid = "profile:" + (p.profile_id || profileApprovedCellId(p));
        phantoms.push({
          // Mimic runtime-view shape just enough for renderRuntimeTable +
          // analytics: not detected and not enabled (greyed-out).
          runtime_instance_id: sid,
          strategy_id: sid,
          display_key: cls,
          display_hidden: false,
          runtime_detected: false,
          runtime_enabled: false,
          runtime: {
            strategy_class: cls,
            instrument: p.instrument || "",
            timeframe: p.timeframe || "",
            account: "",
            mode: "",
            position_qty: null,
            trades_count: null,
            today_pnl: null,
            last_update_utc: null,
            locked_params: p.locked_parameters || {},
            params_check: null,
          },
          cell_id: profileApprovedCellId(p),
          cell_num: cellIdNumber(profileApprovedCellId(p)),
          profile_ref: p,
          trade_window_pt: p.trade_window_pt || buildTradeWindowPtFromParams(p.locked_parameters || {}),
          trade_window: extractTradeWindowConfig(p.locked_parameters || {}),
          locked_params: p.locked_parameters || {},
          _is_phantom: true,
        });
      }
    }
    STATE.phantomRows = phantoms;
    return { phantoms, usedRuntimeIds };
  }

  function visibleRuntimeStrats() {
    const live = STATE.runtimeStrats || [];
    const phantoms = STATE.phantomRows || [];
    // Build a stable order: approved cells (sorted by cell number) first,
    // followed by any live runtime entries that don't map to an approved cell.
    const usedLive = new Set();
    const approvedOrdered = [];
    for (const p of approvedProfiles()) {
      const match = live.find(rt => runtimeMatchesProfile(rt, p));
      if (match) {
        approvedOrdered.push(match);
        usedLive.add(match.runtime_instance_id || match.strategy_id);
      }
    }
    const phantomOrdered = phantoms.slice();
    const merged = approvedOrdered.concat(phantomOrdered)
      .sort((a, b) => (a.cell_num || 0) - (b.cell_num || 0));
    const orphans = live.filter(s => !usedLive.has(s.runtime_instance_id || s.strategy_id));
    const all = merged.concat(orphans);
    return STATE.showHiddenStrategies ? all : all.filter(s => !s.display_hidden);
  }

  function runtimeClassName(view) {
    const rt = (view && view.runtime) || {};
    return rt.strategy_class || view.display_key || view.strategy_id || "";
  }

  function displayKey(v) {
    return String(v || "").trim().toLowerCase();
  }

  function hiddenDisplayClassSet() {
    const items = ((STATE.displayPrefs && STATE.displayPrefs.hidden_classes) || []);
    return new Set(items.map(displayKey).filter(Boolean));
  }

  function historyEntryKeys(entry) {
    return [
      entry && entry.strategy_class,
      entry && entry.class_name,
      entry && entry.strategy_name,
      entry && entry.strategy_id,
    ].map(displayKey).filter(Boolean);
  }

  function isHistoryEntryHidden(entry) {
    const hidden = hiddenDisplayClassSet();
    if (!hidden.size) return false;
    return historyEntryKeys(entry).some(k => hidden.has(k));
  }

  function visibleHistorySessions(rows) {
    const all = Array.isArray(rows) ? rows : [];
    return STATE.showHiddenStrategies ? all : all.filter(r => !isHistoryEntryHidden(r));
  }

  function visibleHistoryEvents(rows) {
    const all = Array.isArray(rows) ? rows : [];
    return STATE.showHiddenStrategies ? all : all.filter(r => !isHistoryEntryHidden(r));
  }

  // ----- top status chips ---------------------------------------------------
  function setChip(id, text, cls) {
    const el = $(id); if (!el) return;
    el.textContent = text;
    el.classList.remove("ok", "bad", "warn");
    if (cls) el.classList.add(cls);
  }

  // ----- catalog / strategies -----------------------------------------------
  async function loadCatalog() {
    try {
      const cat = await api("/api/catalog");
      STATE.catalog = cat;
      const strats = (cat && cat.strategies) || [];
      // sel-strategy dropdown removed in Phase 22c — strategy is now driven by
      // the row clicked in the Active strategies table. We only keep the list
      // in STATE so that defaults still work when no row is selected yet.
      STATE.strategies = strats;
      const def = strats.find(s => (s.class_name || s.name) === "NTAMicroVwapRiskPilot");
      STATE.selectedStrategy = (def && (def.class_name || def.name)) || "NTAMicroVwapRiskPilot";

      // instruments from catalog (still useful for instrument display name & default)
      const insts = (cat && cat.instruments) || [];
      STATE.instruments = insts;
      // legacy hidden select kept in sync
      const isel = $("sel-instrument");
      if (isel) {
        isel.innerHTML = "";
        insts.forEach(i => {
          const sym = instrumentName(i);
          if (!sym) return;
          const o = document.createElement("option");
          o.value = sym; o.textContent = sym;
          isel.appendChild(o);
        });
      }
      autoSelectFrontMonthIfNeeded();
      renderInstrumentDisplay();
      renderStrategyDisplay();
    } catch (e) {
      console.warn("catalog load failed:", e.message);
    }
  }

  // Phase 22c: instrument browser UI was replaced by Performance Center.
  // populateGroupSelector / renderInstruments are kept as no-op stubs to avoid
  // breaking any external callers; the related DOM nodes no longer exist.
  function populateGroupSelector() { /* no-op */ }
  function renderInstruments()    { /* no-op */ }

  async function loadDisplayPrefs() {
    try {
      const prefs = await api("/api/ops/runtime/strategy-display");
      STATE.displayPrefs = prefs || { hidden_classes: [] };
    } catch (e) {
      STATE.displayPrefs = { hidden_classes: [] };
    }
  }

  async function setStrategyHidden(className, hidden) {
    if (!className) return;
    try {
      await api("/api/ops/runtime/strategy-display", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ class_name: className, hidden: !!hidden }),
      });
      await loadDisplayPrefs();
      await loadRuntime();
    } catch (e) {
      const banner = $("rt-banner");
      if (banner) banner.textContent = "Не удалось сохранить видимость стратегии: " + e.message;
    }
  }

  function autoSelectFrontMonthIfNeeded() {
    // For VWAP Short MNQ 5m v1 default to MNQ front-month + 5 Minute when nothing selected.
    if (STATE.selectedStrategy !== "NTAMicroVwapRiskPilot" &&
      STATE.selectedStrategy !== "vwap_short_mnq_5m_v1" &&
        STATE.selectedStrategy !== "b1_shortonly") return;
    const tf = $("sel-timeframe");
    if (tf && !tf.value) tf.value = "5 Minute";
    if (STATE.selectedInstrument && !/^MNQ\b/i.test(STATE.selectedInstrument)) return;
    // Find front-month MNQ
    const mnqs = (STATE.instruments || []).filter(i => rootOf(instrumentName(i)) === "MNQ");
    if (!mnqs.length) return;
    mnqs.sort((a, b) => (b.data_last || "").localeCompare(a.data_last || ""));
    STATE.selectedInstrument = instrumentName(mnqs[0]);
  }

  // ----- accounts -----------------------------------------------------------
  async function loadAccounts() {
    let resp = null;
    try {
      resp = await api("/api/ops/runtime/accounts");
      STATE.accounts = (resp && resp.accounts) || [];
      STATE.onlineAccounts = (resp && resp.online_accounts) || [];
      STATE.accountsSource = (resp && resp.source) || "empty";
      STATE.accountsWarnings = (resp && resp.warnings) || [];
      STATE.accountsNextAction = (resp && resp.next_action) || null;
      STATE.bridgeOnline = !!(resp && resp.bridge_online);
      STATE.accountsAgeSec = (resp && resp.accounts_age_sec);
      STATE.heartbeatAgeSec = (resp && resp.heartbeat_age_sec);
    } catch (e) {
      STATE.accounts = [];
      STATE.onlineAccounts = [];
      STATE.accountsSource = "empty";
      STATE.accountsWarnings = ["Не удалось загрузить /api/ops/runtime/accounts"];
      STATE.bridgeOnline = false;
      STATE.accountsAgeSec = null;
      STATE.heartbeatAgeSec = null;
    }
    const sel = $("sel-account");
    const prev = STATE.selectedAccount || sel.value || "";
    sel.innerHTML = "";
    // Use online_accounts when the backend provides it. If an old backend is
    // still running and only returns accounts[], defensively filter the list so
    // Backtest/Sim101/Playback101 never appear as user-selectable accounts.
    const selectable = (STATE.onlineAccounts.length ? STATE.onlineAccounts : STATE.accounts)
      .filter(isOnlineSelectableAccount);
    if (!selectable.length) {
      const o = document.createElement("option");
      o.value = ""; o.textContent = "(нет данных от bridge)";
      sel.appendChild(o);
    } else {
      selectable.forEach(a => {
        const o = document.createElement("option");
        o.value = a.account_name || "";
        // Display ONLY account_name — never decorated with mode suffix.
        o.textContent = (a.display_name || a.account_name || "?");
        sel.appendChild(o);
      });
      // Preserve selection or default to DEMO > first
      const prevOk = selectable.find(a => a.account_name === prev);
      const demo   = selectable.find(a => a.account_name === "DEMO3369390") ||
        selectable.find(a => a.account_mode === "demo") || selectable[0];
      sel.value = prevOk ? prev : (demo ? demo.account_name : "");
    }
    STATE.selectedAccount = sel.value;
    STATE.accountsRevision = (STATE.accountsRevision || 0) + 1;
    STATE.accountMetrics = null;

    // Render live accounts as read-only info cards below the selector
    const liveAccounts = STATE.accounts.filter(a => a.account_mode === "live" || a.is_live);
    const liveBox = $("live-accounts-info");
    if (liveBox) {
      if (liveAccounts.length) {
        liveBox.innerHTML = liveAccounts.map(a => {
          const cash = fmtCurrency(a.cash_value);
          const net = fmtCurrency(a.net_liquidation);
          const conn = a.connection_status || "—";
          return `<div class="acct-live-card">
            <span class="badge live">${escapeHtml(a.account_name)}</span>
            <span class="badge warn">LIVE</span>
            <span class="muted-small">Cash ${escapeHtml(cash)} · NetLiq ${escapeHtml(net)} · ${escapeHtml(conn)}.</span>
          </div>`;
        }).join("");
        liveBox.style.display = "";
      } else {
        liveBox.innerHTML = "";
        liveBox.style.display = "none";
      }
    }

    renderAccountInfo();
    renderAccountHeadline(pickActiveAccount());
  }

  function renderAccountInfo() {
    const a = STATE.accounts.find(x => x.account_name === STATE.selectedAccount);
    const box = $("acct-info");
    const modeBadge = $("sel-account-mode");
    if (!a) {
      box.innerHTML = '<div class="muted-empty" style="padding:4px;">Аккаунт не выбран.</div>';
      if (modeBadge) { modeBadge.textContent = "—"; modeBadge.className = "badge mut"; }
      renderAccountHeadline(null);
      return;
    }
    if (modeBadge) {
      const m = a.account_mode || "unknown";
      modeBadge.textContent = m;
      modeBadge.className = "badge " +
        (m === "live" ? "warn" :
         m === "playback" ? "warn" :
         m === "paper" || m === "demo" ? "ok" : "mut");
      modeBadge.title = m === "live"
        ? "Live аккаунт — управление работает так же, как на demo/paper"
        : "";
    }
    const hasMoney = (a.cash_value != null) || (a.buying_power != null) || (a.net_liquidation != null);
    let moneyBlock;
    if (hasMoney) {
      moneyBlock = `
        <div class="kv"><span class="k">Cash value</span><span class="v">${escapeHtml(fmtCurrency(a.cash_value))}</span></div>
        <div class="kv"><span class="k">Buying power</span><span class="v">${escapeHtml(fmtCurrency(a.buying_power))}</span></div>
        <div class="kv"><span class="k">Net liquidation</span><span class="v">${escapeHtml(fmtCurrency(a.net_liquidation))}</span></div>
        <div class="kv"><span class="k">Realized PnL</span><span class="v">${escapeHtml(fmtMoney(a.realized_pnl))}</span></div>
        <div class="kv"><span class="k">Unrealized PnL</span><span class="v">${escapeHtml(fmtMoney(a.unrealized_pnl))}</span></div>`;
    } else {
      const reason = a.next_action ||
        (STATE.accountsSource === "positions_fallback"
          ? "Баланс недоступен: bridge ещё не отдаёт accounts.json (есть только positions.json)."
          : "Баланс недоступен: bridge не отдал данные счёта.");
      moneyBlock = `<div style="color:#ffd99b;font-size:11px;padding:2px 0;">⚠ ${escapeHtml(reason)}</div>`;
    }
    if (a.account_mode === "unknown") {
      moneyBlock += `<div style="margin-top:4px;color:#ffd99b;font-size:11px;">⚠ UNKNOWN — режим аккаунта не определён</div>`;
    }
    box.innerHTML = `
      <div class="kv"><span class="k">Режим</span><span class="v">${escapeHtml(a.account_mode || "—")}</span></div>
      ${moneyBlock}
      <div class="kv"><span class="k">Connection</span><span class="v">${escapeHtml(a.connection_status || "—")}</span></div>
    `;
    refreshLaunchControls();
  }

  function renderAccountChip(a) {
    if (STATE.bridgeOnline === false) {
      setChip("chip-acct", "Аккаунт: NT offline", "bad");
      return;
    }
    if (!a) {
      setChip("chip-acct", "Аккаунт: —", "warn");
      return;
    }
    const mode = String(a.account_mode || "unknown").toLowerCase();
    const isLive = !!a.is_live || mode === "live";
    const isConnected = String(a.connection_status || "").toLowerCase() === "connected";
    let label = isLive ? "LIVE" : mode.toUpperCase();
    if (mode === "paper" && String(a.account_name || "").toLowerCase().includes("demo")) label = "DEMO";
    const suffix = isConnected ? "" : " offline";
    setChip("chip-acct", "Аккаунт: " + label + " " + (a.account_name || "—") + suffix,
      isLive ? "bad" : (isConnected ? "ok" : "warn"));
  }

  // Phase 19+ hotfix3: pick which account the headline should display.
  // The dropdown only has user-selectable (paper/demo) accounts, but NinjaTrader
  // may actually be connected to a LIVE broker account. The headline should
  // reflect what NT is *actively connected to*, regardless of dropdown choice.
  // Priority: live+connected > paper/demo+connected (matching dropdown) >
  //           any connected > selected dropdown account > first account.
  function pickActiveAccount() {
    const all = STATE.accounts || [];
    if (!all.length) return null;
    const isConn = a => (a.connection_status || "").toLowerCase() === "connected";
    const liveConn = all.find(a => (a.is_live || a.account_mode === "live") && isConn(a));
    if (liveConn) return liveConn;
    const selected = all.find(a => a.account_name === STATE.selectedAccount);
    if (selected && isConn(selected)) return selected;
    const anyConn = all.find(a => isConn(a) && !_isSystemAccountName(a.account_name));
    if (anyConn) return anyConn;
    return selected || null;
  }

  function _isSystemAccountName(n) {
    const lc = (n || "").toLowerCase();
    return lc === "backtest" || lc === "sim101" || lc === "playback101";
  }

  // Phase 19+ hotfix2: prominent account mode + balance headline.
  // Shows DEMO / LIVE / PAPER / PLAYBACK with current cash balance so the user
  // immediately sees what NinjaTrader account is active (and whether it's real
  // money). When NT is switched between demo and live, this updates on the
  // next /api/ops/runtime/accounts poll (~5s).
  function renderAccountHeadline(a) {
    const root = $("acct-headline");
    if (!root) return;
    const elMode = $("ah-mode");
    const elName = $("ah-name");
    const elConn = $("ah-conn");
    const elBal  = $("ah-balance");
    const elSub  = $("ah-sub");
    const elWarn = $("ah-warn");
    if (!elMode || !elName || !elConn || !elBal || !elSub || !elWarn) return;
    const setBalance = (amountHtml, currencyText = "") => {
      elBal.innerHTML = amountHtml +
        `<span class="ah-currency" id="ah-currency">${escapeHtml(currencyText)}</span>`;
    };

    // Bridge offline = NinjaTrader closed or AddOn not running.
    // Show explicit OFFLINE state instead of stale balance.
    if (STATE.bridgeOnline === false) {
      root.className = "acct-headline mode-unknown mode-disconnected";
      elMode.textContent = "OFFLINE";
      elName.textContent = "NinjaTrader не запущен или bridge не отвечает";
      elConn.textContent = ""; elConn.className = "ah-conn";
      setBalance(`<span class="ah-amount" style="color:#aaa;">— нет данных —</span>`);
      elSub.innerHTML = "";
      const ageHb = STATE.heartbeatAgeSec;
      const ageStr = (ageHb != null) ? `heartbeat ${Math.round(ageHb)}s назад` : "heartbeat отсутствует";
      elWarn.style.display = "";
      elWarn.className = "ah-warn lock";
      elWarn.textContent = `⚠ NinjaTrader OFFLINE — ${ageStr}. Откройте NinjaTrader, чтобы увидеть актуальный аккаунт и баланс.`;
      renderAccountChip(null);
      return;
    }

    if (!a) {
      root.className = "acct-headline mode-unknown";
      elMode.textContent = "—";
      elName.textContent = "Аккаунт не выбран";
      elConn.textContent = ""; elConn.className = "ah-conn";
      setBalance(`<span class="ah-amount">—</span>`);
      elSub.innerHTML = "";
      elWarn.style.display = "none";
      renderAccountChip(null);
      return;
    }

    const mode = (a.account_mode || "unknown").toLowerCase();
    const isLive = !!a.is_live || mode === "live";
    const conn = (a.connection_status || "").toLowerCase();
    const isConnected = conn === "connected";

    let modeClass = "mode-unknown";
    let modeLabel = mode.toUpperCase();
    if (isLive) { modeClass = "mode-live"; modeLabel = "LIVE"; }
    else if (mode === "demo") { modeClass = "mode-demo"; modeLabel = "DEMO"; }
    else if (mode === "paper") {
      // Bridge currently maps "demo*" account names to paper. Surface as DEMO
      // when the account name itself contains DEMO so the user sees DEMO not
      // PAPER for their NinjaTrader DEMO account.
      const nameLc = (a.account_name || "").toLowerCase();
      if (nameLc.includes("demo")) { modeClass = "mode-demo"; modeLabel = "DEMO"; }
      else { modeClass = "mode-paper"; modeLabel = "PAPER (SIM)"; }
    }
    else if (mode === "playback") { modeClass = "mode-playback"; modeLabel = "PLAYBACK"; }
    if (!isConnected) modeClass += " mode-disconnected";

    root.className = "acct-headline " + modeClass;
    elMode.textContent = modeLabel;
    elName.textContent = a.account_name || "—";
    elConn.textContent = isConnected ? "● CONNECTED" : "● DISCONNECTED";
    elConn.className = "ah-conn " + (isConnected ? "connected" : "disconnected");

    // Balance: prefer cash_value, fall back to net_liquidation
    const cash = (a.cash_value != null) ? a.cash_value : null;
    const netliq = (a.net_liquidation != null) ? a.net_liquidation : null;
    const hasMoney = (cash != null) || (netliq != null);
    if (hasMoney && isConnected) {
      const main = (cash != null) ? cash : netliq;
      setBalance(
        `<span class="ah-amount">${escapeHtml(fmtCurrency(main))}</span>`,
        a.currency ? String(a.currency).replace("UsDollar","USD") : ""
      );
    } else if (hasMoney && !isConnected) {
      setBalance(
        `<span class="ah-amount" style="color:#aaa;">${escapeHtml(fmtCurrency(cash != null ? cash : netliq))}</span>`,
        "(stale, NT disconnected)"
      );
    } else {
      setBalance(`<span class="ah-amount" style="color:#aaa;">— нет данных —</span>`);
    }

    const subParts = [];
    if (cash != null) subParts.push(`<b>Cash</b> ${escapeHtml(fmtCurrency(cash))}`);
    if (netliq != null) subParts.push(`<b>NetLiq</b> ${escapeHtml(fmtCurrency(netliq))}`);
    if (a.realized_pnl != null) subParts.push(`<b>Real PnL</b> ${escapeHtml(fmtMoney(a.realized_pnl))}`);
    if (a.unrealized_pnl != null) subParts.push(`<b>Unreal PnL</b> ${escapeHtml(fmtMoney(a.unrealized_pnl))}`);
    elSub.innerHTML = subParts.join("");

    // Warnings
    let warn = "";
    let warnLock = false;
    if (isLive) {
      warn = "⚠ LIVE — реальные деньги. Управление работает идентично demo/paper-аккаунту: enable/disable будут отправлены на этот счёт.";
      warnLock = false;
    } else if (!isConnected) {
      warn = "⚠ NinjaTrader не подключён к этому аккаунту. Баланс может быть устаревшим. Подключите аккаунт в NT (Connections → log in).";
    } else if (mode === "unknown") {
      warn = "⚠ Режим аккаунта не определён bridge'ом — управление заблокировано из соображений безопасности.";
      warnLock = true;
    }
    if (warn) {
      elWarn.style.display = "";
      elWarn.className = "ah-warn" + (warnLock ? " lock" : "");
      elWarn.textContent = warn;
    } else {
      elWarn.style.display = "none";
    }
    renderAccountChip(a);
  }

  // ----- instruments left list (Phase 7) -----------------------------------
  // Month-code → 0-based month index
  const _MONTH_CODE = {
    JAN:0, FEB:1, MAR:2, APR:3, MAY:4, JUN:5,
    JUL:6, AUG:7, SEP:8, OCT:9, NOV:10, DEC:11
  };

  function _parseContractExpiry(sym) {
    // Try "MNQ JUN26" or "MNQ 06-26" patterns
    if (!sym) return null;
    const m1 = sym.match(/\b([A-Z]{3})(\d{2})\b/);
    if (m1) {
      const mo = _MONTH_CODE[m1[1]];
      if (mo !== undefined) {
        const yr = 2000 + parseInt(m1[2], 10);
        // Futures expire mid-month; treat as last day of that month
        return new Date(yr, mo + 1, 0);
      }
    }
    const m2 = sym.match(/\b(\d{2})-(\d{2})\b/);
    if (m2) {
      const mo = parseInt(m2[1], 10) - 1;
      const yr = 2000 + parseInt(m2[2], 10);
      return new Date(yr, mo + 1, 0);
    }
    return null;
  }

  function isInstrumentCurrent(i) {
    const name = instrumentName(i);
    // Try to parse expiry from the contract symbol name first
    const expiry = _parseContractExpiry(name);
    if (expiry) {
      // Allow up to 7 days after expiry (roll window)
      return expiry.getTime() >= Date.now() - 7 * 86400 * 1000;
    }
    // Fallback: data_last within 60 days (or blank → assume current)
    const dl = i && i.data_last;
    if (!dl) return true;
    const d = new Date(String(dl));
    if (isNaN(d.getTime())) return true;
    const cutoff = Date.now() - 60 * 86400 * 1000;
    return d.getTime() >= cutoff;
  }
  function frontMonthMap(items) {
    // Per-root: max data_last
    const m = {};
    items.forEach(i => {
      const r = rootOf(instrumentName(i));
      if (!r) return;
      const dl = i.data_last || "";
      if (!(r in m) || dl > m[r]) m[r] = dl;
    });
    return m;
  }



  function renderInstrumentDisplay() {
    const box = $("sel-instrument-display");
    if (!box) return;
    if (!STATE.selectedInstrument) {
      box.innerHTML = '<span class="muted-empty">не выбран</span>';
      return;
    }
    box.innerHTML = `<span style="color:#cfe1ff;">${escapeHtml(instrumentDisplay(STATE.selectedInstrument))}</span>`;
  }

  function renderStrategyDisplay() {
    const box = $("sel-strategy-display");
    if (!box) return;
    if (!STATE.selectedStrategy) {
      box.innerHTML = '<span class="muted-empty">не выбрана</span>';
      return;
    }
    box.innerHTML = `<span style="color:#cfe1ff;">${escapeHtml(STATE.selectedStrategy)}</span>`;
  }

  // Show/hide right panel: visible only when a runtime row is selected.
  function setRightPanelVisible(visible) {
    const grid  = $("trading-grid");
    const right = $("trading-right");
    if (!grid || !right) return;
    if (visible) {
      right.classList.remove("hidden");
      grid.classList.remove("no-right");
    } else {
      right.classList.add("hidden");
      grid.classList.add("no-right");
    }
  }

  async function loadAccountActivity() {
    const acct = selectedAccountNameForData();
    const qp = new URLSearchParams({ limit: "10000" });
    if (acct) qp.set("account_name", acct);
    try {
      const [execResp, orderResp, posResp] = await Promise.all([
        api("/api/ops/runtime/executions?" + qp.toString()),
        api("/api/ops/runtime/orders?" + qp.toString()),
        api("/api/ops/runtime/positions"),
      ]);
      STATE.accountExecs = (execResp && execResp.executions) || [];
      STATE.accountOrders = (orderResp && orderResp.orders) || [];
      STATE.executionDedupeMeta = (execResp && execResp.dedupe) || {};
      STATE.orderDedupeMeta = (orderResp && orderResp.dedupe) || {};
      STATE.positions = posResp || {};
    } catch (e) {
      STATE.accountExecs = [];
      STATE.accountOrders = [];
      STATE.executionDedupeMeta = {};
      STATE.orderDedupeMeta = {};
      STATE.positions = {};
      const banner = $("acct-data-warning");
      if (banner) banner.textContent = "Не удалось загрузить сделки/ордера счёта: " + e.message;
    }
    STATE.accountActivityRevision = (STATE.accountActivityRevision || 0) + 1;
    STATE.accountMetrics = computeAccountMetrics(true);
    renderAccountOverviewBand();
    renderSessionBoard();
    if (!STATE.selectedRuntime) renderAccountLevelPanes();
  }

  function renderAccountOverviewBand() {
    const m = STATE.accountMetrics || computeAccountMetrics();
    const a = m.account || {};
    const name = m.accountName || "—";
    const allTime = accountAllTimeStats(m);
    const pnl = allTime.pnl;
    const execNet = allTime.pnl;
    const execGross = allTime.gross;
    const execCommission = allTime.commission;
    const allTimeUnmapped = (m.executions || []).filter(isUnmappedTelemetry).length;
    const rejectedPairs = (m.rejectedClosedTrades || []).length;
    const cash = numOrNull(a.cash_value);
    const net = numOrNull(a.net_liquidation);
    const unreal = numOrNull(a.unrealized_pnl);
    const conn = a.connection_status || (STATE.bridgeOnline ? "Connected" : "offline");
    const setText = (id, text) => { const el = $(id); if (el) el.textContent = text; };
    const startLabel = dayTitle(PERFORMANCE_START_DATE_PT);
    setText("acct-day-title", `С ${startLabel}`);
    setText("acct-instruments-title", `Доход по инструментам с ${startLabel}`);
    setText("acct-overview-name", name);
    setText("acct-overview-conn", conn);
    setText("acct-overview-cash", cash == null ? "—" : fmtCurrency(cash));
    setText("acct-overview-netliq", net == null ? "—" : fmtCurrency(net));
    setText("acct-overview-realized", pnl == null ? "—" : fmtMoney(pnl));
    setText("acct-overview-unrealized", unreal == null ? "—" : fmtMoney(unreal));
    setText("acct-today-pnl", pnl == null ? "—" : fmtMoney(pnl));
    setText("acct-today-trades", String(allTime.executions || 0));
    setText("acct-today-winloss", `${allTime.wins || 0} / ${allTime.losses || 0}`);
    const allInstruments = Object.keys(allTime.byInstrument || {}).sort();
    setText("acct-today-instruments", allInstruments.length ? allInstruments.map(rootOf).join(", ") : "—");
    setText("acct-today-unmapped", String(allTimeUnmapped || 0));
    const execMeta = m.executionDedupe || {};
    const raw = Number(execMeta.raw_count || 0);
    const deduped = Number(execMeta.deduped_count || 0);
    const dup = Number(execMeta.duplicate_count || 0);
    const dedupeText = raw && deduped ? ` · raw ${raw} → ${deduped}` : "";
    const commText = Math.abs(execCommission || 0) > 1e-9
      ? ` · gross ${fmtMoney(execGross || 0)} · comm -${fmtCurrency(execCommission)}`
      : "";
    setText("acct-exec-gross", "deduped net est.: " + fmtMoney(execNet || 0) + commText + dedupeText);
    ["acct-today-pnl", "acct-overview-realized", "acct-overview-unrealized"].forEach(id => {
      const el = $(id);
      if (!el) return;
      el.classList.remove("pos", "neg");
      const cls = id === "acct-overview-unrealized" ? moneyClass(unreal) : moneyClass(pnl);
      if (cls) el.classList.add(cls);
    });
    const warn = $("acct-data-warning");
    if (warn) {
      const parts = [];
      if (dup) parts.push(`После перезапуска отброшено ${dup} replay-дубликатов executions.`);
      if (m.accountRealizedRaw != null && m.accountRealizedUsed == null && m.accountEquityDeltaPnl != null) {
        const raw = Number(m.accountRealizedRaw || 0);
        const rawText = Math.abs(raw) > 1e-9 ? fmtMoney(raw) : "0";
        parts.push(`NinjaTrader account RealizedPnL (${rawText}) не совпал с закрытыми executions, поэтому дневной PnL взят из cash/netliq минус StartingCapital.`);
      } else if (m.accountRealizedRaw != null && m.accountRealizedUsed == null && Math.abs(m.executionNet || 0) > 1e-9) {
        const raw = Number(m.accountRealizedRaw || 0);
        const rawText = Math.abs(raw) > 1e-9 ? fmtMoney(raw) : "0";
        parts.push(`NinjaTrader account RealizedPnL (${rawText}) не совпал с закрытыми executions, поэтому дневной PnL взят из deduped net executions.`);
      }
      if (allTimeUnmapped) {
        parts.push(`За весь период есть ${allTimeUnmapped} executions без нормальной привязки к стратегии. Они показаны на уровне счёта и не теряются.`);
      }
      if (rejectedPairs) {
        parts.push(`${rejectedPairs} подозрительных FIFO-пар исключены из PnL: длительность слишком большая для intraday-стратегии.`);
      }
      warn.textContent = parts.join(" ");
    }
    renderAccountPnlChart(m);
    renderInstrumentPnlBars(m);
  }

  function renderAccountPnlChart(m) {
    const cv = $("acct-pnl-chart");
    if (!cv) return;
    const ctx = cv.getContext && cv.getContext("2d");
    if (!ctx) return;
    const W = cv.width = cv.clientWidth || 320;
    const H = cv.height = cv.clientHeight || 132;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0f1115";
    ctx.fillRect(0, 0, W, H);

    const trades = (m.allClosedTrades || m.closedTrades || []).slice().sort((a, b) =>
      String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || "")));
    let cum = 0;
    let curve = [0].concat(trades.map(t => {
      cum += Number(t.pnl || 0);
      return cum;
    }));
    const allTime = accountAllTimeStats(m);
    const accountPnl = numOrNull(allTime.pnl);
    if (trades.length && accountPnl != null && Math.abs(cum) > 1e-9) {
      const scale = Number(accountPnl) / cum;
      curve = curve.map(v => v * scale);
      cum = Number(accountPnl);
    } else if (!trades.length && accountPnl != null) {
      curve = [0, Number(accountPnl || 0)];
      cum = Number(accountPnl || 0);
    }
    if (!curve.length || (curve.length === 1 && curve[0] === 0)) {
      ctx.fillStyle = "#666";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("Сделок нет", W / 2, H / 2);
      return;
    }

    let lo = Math.min(0, ...curve);
    let hi = Math.max(0, ...curve);
    if (lo === hi) hi = lo + 1;
    const base = 0;
    const padL = 44, padR = 8, padT = 9, padB = 18;
    const innerW = Math.max(1, W - padL - padR);
    const innerH = Math.max(1, H - padT - padB);
    const x = i => padL + (i / Math.max(1, curve.length - 1)) * innerW;
    const y = v => padT + innerH - ((v - lo) / (hi - lo)) * innerH;
    const yBase = y(base);

    function pathToBaseline() {
      ctx.beginPath();
      ctx.moveTo(x(0), y(curve[0]));
      for (let i = 1; i < curve.length; i += 1) ctx.lineTo(x(i), y(curve[i]));
      ctx.lineTo(x(curve.length - 1), yBase);
      ctx.lineTo(x(0), yBase);
      ctx.closePath();
    }
    function linePath() {
      ctx.beginPath();
      ctx.moveTo(x(0), y(curve[0]));
      for (let i = 1; i < curve.length; i += 1) ctx.lineTo(x(i), y(curve[i]));
    }

    ctx.strokeStyle = "rgba(255,255,255,0.07)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 4; i += 1) {
      const gy = padT + (innerH * i / 4);
      ctx.beginPath();
      ctx.moveTo(padL, gy);
      ctx.lineTo(padL + innerW, gy);
      ctx.stroke();
    }

    ctx.save();
    ctx.beginPath();
    ctx.rect(padL, padT, innerW, Math.max(0, yBase - padT));
    ctx.clip();
    pathToBaseline();
    ctx.fillStyle = "rgba(45, 170, 75, 0.46)";
    ctx.fill();
    ctx.restore();

    ctx.save();
    ctx.beginPath();
    ctx.rect(padL, yBase, innerW, Math.max(0, padT + innerH - yBase));
    ctx.clip();
    pathToBaseline();
    ctx.fillStyle = "rgba(185, 24, 24, 0.50)";
    ctx.fill();
    ctx.restore();

    ctx.lineWidth = 1.6;
    ctx.save();
    ctx.beginPath();
    ctx.rect(padL, padT, innerW, Math.max(0, yBase - padT));
    ctx.clip();
    linePath();
    ctx.strokeStyle = "#35d04d";
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.beginPath();
    ctx.rect(padL, yBase, innerW, Math.max(0, padT + innerH - yBase));
    ctx.clip();
    linePath();
    ctx.strokeStyle = "#ff2020";
    ctx.stroke();
    ctx.restore();

    ctx.strokeStyle = "#2c3142";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, yBase);
    ctx.lineTo(padL + innerW, yBase);
    ctx.stroke();

    ctx.fillStyle = "#6b7280";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("$" + fmtMoneyShort(hi), padL - 4, padT + 8);
    ctx.fillText("$" + fmtMoneyShort(base), padL - 4, yBase + 3);
    ctx.fillText("$" + fmtMoneyShort(lo), padL - 4, padT + innerH);

    ctx.fillStyle = cum >= 0 ? "#b9f5cd" : "#ffb3b3";
    ctx.textAlign = "left";
    ctx.font = "10px sans-serif";
    const tailLabel = `${trades.length} закр. · ${(allTime.executions || 0)} fills · ${fmtMoney(cum)}`;
    ctx.fillText(tailLabel, padL, H - 5);
  }

  function renderInstrumentPnlBars(m) {
    const root = $("acct-pnl-instruments");
    if (!root) return;
    let rows;
    const all = m.allClosedTrades || [];
    if (all.length) {
      const agg = {};
      for (const t of all) {
        const inst = t.instrument || "—";
        if (!agg[inst]) agg[inst] = { pnl: 0, trades: 0 };
        agg[inst].pnl += Number(t.pnl || 0);
        agg[inst].trades += 1;
      }
      rows = Object.entries(agg).sort((a, b) => Math.abs(b[1].pnl) - Math.abs(a[1].pnl));
    } else {
      rows = Object.entries(m.byInstrument || {})
        .sort((a, b) => Math.abs(b[1].pnl) - Math.abs(a[1].pnl));
    }
    if (!rows.length) {
      root.innerHTML = '<div class="muted-empty compact">нет закрытых сделок</div>';
      return;
    }
    const maxAbs = Math.max(...rows.map(([, v]) => Math.abs(v.pnl)), 1);
    root.innerHTML = rows.slice(0, 6).map(([inst, v]) => {
      const w = Math.max(4, Math.round(Math.abs(v.pnl) / maxAbs * 100));
      const cls = v.pnl >= 0 ? "pos" : "neg";
      return `<div class="acct-bar-row">
        <div class="acct-bar-label">${escapeHtml(inst)} <span>${escapeHtml(v.trades)} сд.</span></div>
        <div class="acct-bar-track"><i class="${cls}" style="width:${w}%"></i></div>
        <div class="acct-bar-value ${cls}">${escapeHtml(fmtMoney(v.pnl))}</div>
      </div>`;
    }).join("");
  }

  function renderSessionBoard() {
    renderTradingCalendar();
    renderSelectedDaySummary();
    renderSnapshotPositions();
    renderSnapshotWorkingOrders();
    renderSelectedDayTradesPanel();
  }

  function calendarDatesForMonth(monthKey) {
    const base = parseDateKey(monthKey) || parseDateKey(todayWallPtDate());
    const y = base.year, mo = base.month;
    const monthStart = dateKey(y, mo, 1);
    let first = monthStart;
    let guard = 0;
    while (ptWeekdaySunday0(first) !== 0 && guard < 8) {
      first = stepPtWallDay(first, -1);
      guard++;
    }
    const dates = [];
    let cur = first;
    for (let i = 0; i < 42; i++) {
      dates.push(cur);
      cur = stepPtWallDay(cur, 1);
    }
    return dates;
  }

  function ordersByWallDate() {
    if (STATE.accountMetrics && STATE.accountMetrics.orderCountsByWallDate) {
      return STATE.accountMetrics.orderCountsByWallDate;
    }
    const accountName = selectedAccountNameForData();
    const out = {};
    for (const o of (STATE.accountOrders || [])) {
      if (accountName && o.account_name !== accountName) continue;
      if (!isPerformanceWindowTimestamp(o.timestamp_utc)) continue;
      const d = ptWallCalendarDate(o.timestamp_utc);
      if (!d) continue;
      const id = String(o.order_id || "").trim();
      if (!out[d]) out[d] = { ids: new Set(), rows: 0 };
      if (id) out[d].ids.add(id);
      out[d].rows += 1;
    }
    const counts = {};
    for (const [d, v] of Object.entries(out)) {
      counts[d] = v.ids.size || v.rows;
    }
    return counts;
  }

  function renderTradingCalendar() {
    const grid = $("trade-calendar");
    if (!grid) return;
    const m = STATE.accountMetrics || computeAccountMetrics();
    const monthKey = STATE.calendarMonthPt || (todayWallPtDate().slice(0, 7) + "-01");
    const monthPrefix = monthKey.slice(0, 7);
    const title = $("cal-month-title");
    if (title) title.textContent = monthTitle(monthKey);
    const wallDaily = m.dailyWall || {};
    const monthPnl = Object.values(wallDaily)
      .filter(d => String(d.date_pt || "").slice(0, 7) === monthPrefix)
      .reduce((acc, d) => acc + Number(d.pnl || 0), 0);
    const pnlEl = $("cal-month-pnl");
    if (pnlEl) {
      pnlEl.textContent = "Monthly P/L: " + fmtMoney(monthPnl);
      pnlEl.classList.remove("pos", "neg");
      const cls = moneyClass(monthPnl);
      if (cls) pnlEl.classList.add(cls);
    }
    const today = todayWallPtDate();
    const selected = STATE.selectedDatePt || today;
    const ordersCount = m.orderCountsByWallDate || ordersByWallDate();
    grid.innerHTML = calendarDatesForMonth(monthKey).map(day => {
      const d = (wallDaily[day] || (m.daily || {})[day]) || { executions: [], closedTrades: [], pnl: 0 };
      const dayNum = Number(day.slice(-2));
      const inMonth = day.slice(0, 7) === monthPrefix;
      const pnl = Number(d.pnl || 0);
      const ordCount = ordersCount[day] || 0;
      const tradeCount = (d.closedTrades || []).length;
      const hasActivity = (d.executions || []).length || tradeCount || ordCount || Math.abs(pnl) > 1e-9;
      const cls = [
        "calendar-day",
        inMonth ? "" : "other-month",
        day === today ? "today" : "",
        day === selected ? "selected" : "",
        hasActivity && pnl > 0 ? "pos" : "",
        hasActivity && pnl < 0 ? "neg" : "",
      ].filter(Boolean).join(" ");
      const tradeLabel = tradeCount ? `${tradeCount} сделок` : "нет закрытых сделок";
      const pnlLine = (hasActivity
        ? `<div class="cal-pnl ${moneyClass(pnl)}">${escapeHtml(fmtMoney(pnl))}</div>`
        : '<div class="cal-empty">—</div>') +
        `<div class="cal-orders${tradeCount ? "" : " empty"}">${escapeHtml(tradeLabel)}</div>`;
      return `<button type="button" class="${cls}" data-date="${escapeHtml(day)}">
        <div class="cal-date-row"><span class="cal-date">${escapeHtml(dayNum)}</span></div>
        ${pnlLine}
      </button>`;
    }).join("");
    grid.querySelectorAll("[data-date]").forEach(btn => {
      btn.addEventListener("click", () => {
        STATE.selectedDatePt = btn.dataset.date || todayWallPtDate();
        STATE.calendarMonthPt = STATE.selectedDatePt.slice(0, 7) + "-01";
        STATE.dayExplicitlySelected = true;
        STATE.accountMetrics = computeAccountMetrics();
        renderSessionBoard();
        renderRuntimeTable();
        if (STATE.selectedRuntime) renderAnalytics(STATE.selectedRuntime);
        else renderAccountLevelPanes();
      });
    });
  }

  function renderSelectedDaySummary() {
    const root = $("selected-day-summary");
    if (!root) return;
    const m = STATE.accountMetrics || computeAccountMetrics();
    const d = m.selectedDay || {};
    const title = $("selected-day-title");
    if (title) title.textContent = dayTitle(m.selectedDatePt || todayWallPtDate());
    const selectedDay = m.selectedDatePt || todayWallPtDate();
    const dayOrders = selectedDayOrderRows(selectedDay);
    const missingFilled = filledOrdersMissingExecutions(dayOrders, d.executions || []);
    const source = $("selected-day-source");
    if (source) {
      const duplicates = Number(d.duplicates_ignored || 0);
      const src = d.pnl_source === "account_realized" ? "account realized"
        : d.pnl_source === "account_cash_delta" ? "account cash delta"
        : "net estimate";
      const details = [];
      if (Math.abs(Number(d.commission || 0)) > 1e-9) details.push(`commission -${fmtCurrency(d.commission)}`);
      if (duplicates) details.push(`duplicates ignored: ${duplicates}`);
      if (missingFilled.length) details.push(`filled без executions: ${missingFilled.length}`);
      source.textContent = [src].concat(details).join(", ");
    }
    const pnl = Number(d.pnl || 0);
    const fills = (d.executions || []).length;
    const closed = (d.closedTrades || []).length;
    const ordersTotal = (m.orderCountsByWallDate || ordersByWallDate())[selectedDay] || 0;
    const instruments = Array.isArray(d.instruments)
      ? d.instruments
      : (d.instruments && typeof d.instruments[Symbol.iterator] === "function")
        ? [...d.instruments]
        : [];
    const inst = instruments.map(rootOf).join(", ") || "—";
    root.innerHTML = `
      <div class="metric"><span class="k">PnL</span><span class="v ${moneyClass(pnl)}">${escapeHtml(fmtMoney(pnl))}</span></div>
      <div class="metric"><span class="k">Ордеров</span><span class="v">${escapeHtml(ordersTotal)}</span></div>
      <div class="metric"><span class="k">Closed / W-L</span><span class="v">${escapeHtml(closed)} · ${escapeHtml(d.wins || 0)} / ${escapeHtml(d.losses || 0)}</span></div>
      <div class="metric"><span class="k">Инструменты</span><span class="v">${escapeHtml(inst)}</span></div>
    `;
  }

  function latestOrderUpdates(rows) {
    const byId = new Map();
    (Array.isArray(rows) ? rows : []).forEach((r, idx) => {
      const id = String(r.order_id || "").trim() || [
        r.account_name, r.instrument, r.order_action, r.order_type,
        r.quantity, r.limit_price, r.stop_price, idx,
      ].join("|");
      const prev = byId.get(id);
      if (!prev || String(r.timestamp_utc || "") >= String(prev.timestamp_utc || "")) byId.set(id, r);
    });
    return [...byId.values()].sort((a, b) => String(b.timestamp_utc || "").localeCompare(String(a.timestamp_utc || "")));
  }

  function orderStateKind(state) {
    const s = String(state || "").toLowerCase();
    if (s === "filled") return "filled";
    if (s === "working" || s === "accepted" || s === "submitted" || s === "partfilled") return "working";
    if (s.includes("cancel")) return "cancelled";
    if (s.includes("reject")) return "rejected";
    if (s.includes("pending") || s === "initialized") return "pending";
    return "pending";
  }

  function isWorkingOrder(row) {
    return orderStateKind(row && row.order_state) === "working";
  }

  function orderPrice(row) {
    const limit = numOrNull(row && row.limit_price);
    const stop = numOrNull(row && row.stop_price);
    const avg = numOrNull(row && row.avg_fill);
    if (avg != null && avg !== 0) return avg;
    if (limit != null && limit !== 0) return limit;
    if (stop != null && stop !== 0) return stop;
    if (limit != null) return limit;
    if (stop != null) return stop;
    return null;
  }

  function formatOrderLimitStopAvg(r) {
    const lim = numOrNull(r && r.limit_price);
    const stp = numOrNull(r && r.stop_price);
    const avg = numOrNull(r && r.avg_fill);
    const parts = [];
    if (lim != null) parts.push(`lim ${fmtNum(lim)}`);
    if (stp != null) parts.push(`stop ${fmtNum(stp)}`);
    if (avg != null) parts.push(`avg ${fmtNum(avg)}`);
    return parts.length ? parts.join(" · ") : "—";
  }

  function orderReason(row) {
    const candidates = [
      row && row.reject_reason,
      row && row.rejection_reason,
      row && row.cancel_reason,
      row && row.error,
      row && row.message,
      row && row.native_error,
      row && row.reason,
      row && row.comment,
    ];
    for (const value of candidates) {
      const text = String(value || "").trim();
      if (text) return text;
    }
    const kind = orderStateKind(row && row.order_state);
    if (kind === "cancelled") return "отменен; bridge не передал отдельную причину";
    if (kind === "rejected") return "отклонен; bridge не передал отдельную причину";
    return "—";
  }

  function selectedDayOrderRows(day) {
    const accountName = selectedAccountNameForData();
    const rows = (STATE.accountOrders || []).filter(r =>
      (!accountName || r.account_name === accountName) &&
      isPerformanceWindowTimestamp(r.timestamp_utc) &&
      ptWallCalendarDate(r.timestamp_utc) === day);
    return latestOrderUpdates(rows);
  }

  function orderSummaryBadges(rows) {
    const counts = {};
    for (const row of rows) {
      const kind = orderStateKind(row && row.order_state);
      counts[kind] = (counts[kind] || 0) + 1;
    }
    return ["filled", "working", "pending", "cancelled", "rejected"]
      .filter(kind => counts[kind])
      .map(kind => `<span class="status-pill ${kind}">${escapeHtml(kind)}: ${escapeHtml(counts[kind])}</span>`)
      .join(" ");
  }

  function filledOrdersMissingExecutions(orderRows, executionRows) {
    const executionOrderIds = new Set((Array.isArray(executionRows) ? executionRows : [])
      .map(r => String(r && r.order_id || "").trim())
      .filter(Boolean));
    return (Array.isArray(orderRows) ? orderRows : []).filter(row => {
      const oid = String(row && row.order_id || "").trim();
      return oid && orderStateKind(row && row.order_state) === "filled" && !executionOrderIds.has(oid);
    });
  }

  function dayOrdersTableHTML(rows) {
    if (!rows.length) return '<div class="muted-empty">Ордеров за этот день не найдено</div>';
    const body = rows.slice(0, 220).map(r => {
      const kind = orderStateKind(r.order_state);
      const strat = r.strategy_class || r.strategy_name || r.strategy_id || "—";
      const signal = r.from_entry_signal || r.order_name || "—";
      const oid = String(r.order_id || "").slice(-10) || "—";
      return `<tr class="day-order-${kind}">
        <td><span class="muted small">${escapeHtml(fmtHms(r.timestamp_utc))}</span></td>
        <td><span class="muted small">${escapeHtml(oid)}</span></td>
        <td>${escapeHtml(r.instrument || "—")}</td>
        <td><span class="muted small">${escapeHtml(strat)}</span></td>
        <td>${escapeHtml(signal)}</td>
        <td>${escapeHtml(r.order_action || "—")}</td>
        <td>${escapeHtml(r.order_type || "—")}</td>
        <td><span class="status-pill ${kind}">${escapeHtml(r.order_state || "—")}</span></td>
        <td class="num">${escapeHtml(r.quantity ?? "—")}</td>
        <td class="num"><span class="muted small">${escapeHtml(formatOrderLimitStopAvg(r))}</span></td>
        <td><span class="muted small">${escapeHtml(orderReason(r))}</span></td>
      </tr>`;
    }).join("");
    return `<div class="day-orders-table-wrap"><table class="tg-tbl day-orders-table">
      <thead><tr>
        <th>Время PT</th><th>Order ID</th><th>Symbol</th><th>Стратегия</th><th>Signal</th>
        <th>Side</th><th>Type</th><th>Status</th><th class="num">Qty</th><th class="num">Цена</th><th>Причина</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table></div>`;
  }

  function renderSnapshotPositions() {
    const root = $("snapshot-positions");
    const count = $("snapshot-position-count");
    if (!root) return;
    const rows = normalizePositionsForAccount();
    const liveRows = rows.filter(r => Number(r.quantity || 0) !== 0 || String(r.market_position || "").toLowerCase() !== "flat");
    if (count) count.textContent = liveRows.length ? `${liveRows.length} open` : "Flat";
    if (!liveRows.length) {
      root.innerHTML = '<div class="flat-state">Flat по всем инструментам выбранного счёта.</div>';
      return;
    }
    root.innerHTML = `<table class="mini-tbl"><thead><tr><th>Symbol</th><th>Position</th><th class="num">Avg</th><th class="num">U-PnL</th></tr></thead><tbody>` +
      liveRows.map(r => {
        const side = String(r.market_position || "Flat");
        return `<tr>
          <td>${escapeHtml(r.instrument || "—")}</td>
          <td><span class="status-pill ${side.toLowerCase() === "short" ? "rejected" : "filled"}">${escapeHtml(side)} ${escapeHtml(r.quantity ?? "")}</span></td>
          <td class="num">${escapeHtml(fmtNum(r.avg_price))}</td>
          <td class="num ${moneyClass(r.unrealized_pnl)}">${escapeHtml(fmtMoney(r.unrealized_pnl))}</td>
        </tr>`;
      }).join("") + "</tbody></table>";
  }

  function renderSnapshotWorkingOrders() {
    const root = $("snapshot-working-orders");
    const count = $("snapshot-order-count");
    if (!root) return;
    const acct = selectedAccountNameForData();
    const latest = latestOrderUpdates((STATE.accountOrders || []).filter(r => !acct || r.account_name === acct));
    const rows = latest.filter(isWorkingOrder);
    if (count) count.textContent = rows.length ? `${rows.length} active` : "0 active";
    if (!rows.length) {
      root.innerHTML = '<div class="muted-empty compact">Активных стопов, тейков или лимитных ордеров сейчас нет.</div>';
      return;
    }
    root.innerHTML = `<table class="mini-tbl"><thead><tr><th>Symbol</th><th>Strategy</th><th>Name</th><th>Side</th><th>Type</th><th>Status</th><th class="num">Qty</th><th class="num">Limit / Stop / Avg</th></tr></thead><tbody>` +
      rows.map(r => {
        const kind = orderStateKind(r.order_state);
        const strat = r.strategy_class || r.strategy_name || r.strategy_id || "—";
        const oname = r.order_name || r.from_entry_signal || "—";
        return `<tr>
          <td>${escapeHtml(r.instrument || "—")}</td>
          <td><span class="muted small">${escapeHtml(strat)}</span></td>
          <td><span class="muted small">${escapeHtml(oname)}</span></td>
          <td>${escapeHtml(r.order_action || "—")}</td>
          <td>${escapeHtml(r.order_type || "—")}</td>
          <td><span class="status-pill ${kind}">${escapeHtml(r.order_state || "—")}</span></td>
          <td class="num">${escapeHtml(r.quantity ?? "—")}</td>
          <td class="num"><span class="muted small">${escapeHtml(formatOrderLimitStopAvg(r))}</span></td>
        </tr>`;
      }).join("") + "</tbody></table>";
  }

  // ----- runtime strategies table ------------------------------------------
  async function loadRuntimeHistorySessions() {
    try {
      const data = await api("/api/ops/runtime/history?limit=1000");
      STATE.runtimeHistorySessions = (data && Array.isArray(data.sessions)) ? data.sessions : [];
    } catch (_) {
      STATE.runtimeHistorySessions = [];
    }
  }

  async function loadStrategyStartDates() {
    try {
      const data = await api("/api/ops/strategy-start-dates");
      STATE.strategyStartDates = (data && data.strategies && typeof data.strategies === "object")
        ? data.strategies
        : {};
    } catch (_) {
      STATE.strategyStartDates = {};
    }
  }

  async function loadRuntime() {
    // Pass current selectors so backend can compute selection_diff per row.
    const qp = new URLSearchParams();
    if (STATE.selectedAccount)    qp.set("selected_account", STATE.selectedAccount);
    if (STATE.selectedInstrument) qp.set("selected_instrument", STATE.selectedInstrument);
    const tfEl = $("sel-timeframe");
    if (tfEl && tfEl.value)       qp.set("selected_timeframe", tfEl.value);
    const url = "/api/ops/runtime/strategies" + (qp.toString() ? "?" + qp.toString() : "");
    const heartbeatPromise = api("/api/ops/runtime/heartbeat")
      .catch(() => ({ present: false, fresh: false }));
    const displayPrefsPromise = loadDisplayPrefs();
    const strategiesPromise = api(url)
      .catch(() => ({ strategies: [] }));
    const profilesPromise = api("/api/profiles")
      .catch(() => null);
    const historyPromise = loadRuntimeHistorySessions();
    const startDatesPromise = loadStrategyStartDates();

    const hb = await heartbeatPromise;
    STATE.bridgeOnline = !!(hb && hb.fresh);
    setChip("chip-backend", "Backend: онлайн", "ok");
    setChip("chip-runtime",
      "NT runtime: " + (STATE.bridgeOnline ? "онлайн" : "offline"),
      STATE.bridgeOnline ? "ok" : "bad");

    const [all, reg] = await Promise.all([strategiesPromise, profilesPromise, displayPrefsPromise, historyPromise, startDatesPromise])
      .then(([allResp, regResp]) => [allResp, regResp]);
    STATE.runtimeStrats = (all && all.strategies) || [];
    STATE.runtimeRawStrats = (all && all.raw) || [];
    // Load approved profiles registry so we can show every approved cell
    // (greyed-out when not running) ordered by CELL number.
    if (reg) {
      STATE.profiles = (reg && Array.isArray(reg.profiles)) ? reg.profiles : [];
    }
    rebuildPhantomRows();
    const selected = findRuntimeView(STATE.selectedRuntime);
    if (selected && selected.display_hidden && !STATE.showHiddenStrategies) {
      STATE.selectedRuntime = null;
      setRightPanelVisible(false);
    }
    renderRuntimeTable();
    refreshSelectionDiff();
    refreshLaunchControls();
    renderPerformanceCenter();
    if (STATE.selectedRuntime) renderAnalytics(STATE.selectedRuntime);
  }

  function fmtHms(iso) {
    if (!iso) return "—";
    const d = new Date(String(iso));
    if (isNaN(d.getTime())) return String(iso).slice(0, 19).replace("T", " ");
    return PT_HMS_FORMATTER ? PT_HMS_FORMATTER.format(d) : String(iso).slice(11, 19);
  }

  function fmtDatePt(iso) {
    if (!iso) return "—";
    const d = new Date(String(iso));
    if (isNaN(d.getTime())) return String(iso).slice(0, 10) || "—";
    return PT_DATE_FORMATTER ? PT_DATE_FORMATTER.format(d) : String(iso).slice(0, 10);
  }

  function fmtDateTime(iso) {
    if (!iso) return "—";
    const d = new Date(String(iso));
    if (isNaN(d.getTime())) return String(iso).slice(0, 19).replace("T", " ");
    return PT_DATETIME_FORMATTER ? PT_DATETIME_FORMATTER.format(d) : String(iso).slice(0, 19).replace("T", " ");
  }

  function fmtDurationSec(sec) {
    if (sec == null || isNaN(Number(sec))) return "—";
    let s = Math.max(0, Math.round(Number(sec)));
    const d = Math.floor(s / 86400); s -= d * 86400;
    const h = Math.floor(s / 3600); s -= h * 3600;
    const m = Math.floor(s / 60);
    if (d) return `${d}д ${h}ч`;
    if (h) return `${h}ч ${m}м`;
    return `${m}м`;
  }

  function historySessionMatchesView(sess, view) {
    if (!sess || !view) return false;
    const rt = (view && view.runtime) || {};
    const viewIid = String(view.runtime_instance_id || rt.runtime_instance_id || "").trim();
    const sessIid = String(sess.runtime_instance_id || "").trim();
    if (viewIid && sessIid && viewIid === sessIid) return true;
    const tokens = strategyTokenSet(view);
    const candidates = [
      sess.strategy_id,
      sess.strategy_class,
      sess.strategy_name,
      sess.class_name,
      sess.runtime_instance_id,
    ].map(x => String(x || "").trim().toLowerCase()).filter(Boolean);
    if (!candidates.some(x => tokens.has(x))) return false;
    const viewAcct = String(rt.account_name || view.account_name || "").trim();
    const sessAcct = String(sess.account_name || "").trim();
    if (viewAcct && sessAcct && viewAcct !== sessAcct) return false;
    const viewRoot = rootOf(rt.instrument || rt.contract_month || "");
    const sessRoot = rootOf(sess.instrument || "");
    if (viewRoot && sessRoot && viewRoot !== sessRoot) return false;
    const viewTf = String(rt.timeframe || "").trim().toLowerCase();
    const sessTf = String(sess.timeframe || "").trim().toLowerCase();
    if (viewTf && sessTf && viewTf !== sessTf) return false;
    return true;
  }

  function strategyRuntimeDurationSec(view) {
    const sessions = STATE.runtimeHistorySessions || [];
    let total = 0;
    let matched = false;
    for (const sess of sessions) {
      if (!historySessionMatchesView(sess, view)) continue;
      const dur = numOrNull(sess.duration_sec);
      if (dur != null) {
        total += dur;
        matched = true;
      }
    }
    return matched ? total : null;
  }

  function tradeDurationValue(t) {
    const entry = t && t.entry_time_utc ? new Date(t.entry_time_utc).getTime() : NaN;
    const exit = t && (t.exit_time_utc || t.timestamp_utc) ? new Date(t.exit_time_utc || t.timestamp_utc).getTime() : NaN;
    return Number.isFinite(entry) && Number.isFinite(exit) ? Math.max(0, exit - entry) / 1000 : null;
  }

  function closedTradeSortValue(row, col) {
    switch (col) {
      case "trade_no": return numOrNull(row.trade_no);
      case "strategy": return tradeStrategyLabel(row, "");
      case "instrument": return row.instrument || "";
      case "quantity": return numOrNull(row.quantity);
      case "direction": return row.direction || row.action || "";
      case "pnl": return numOrNull(row.pnl);
      case "exit_time": return row.exit_time_utc || row.timestamp_utc || "";
      case "entry_time": return row.entry_time_utc || "";
      case "duration": return tradeDurationValue(row);
      case "entry_price": return numOrNull(row.entry_price);
      case "exit_price": return numOrNull(row.exit_price);
      case "gross_pnl": return numOrNull(row.gross_pnl);
      case "commission": return numOrNull(row.commission);
      case "exit_reason": return row.exit_reason || "";
      default: return row[col];
    }
  }

  function executionSortValue(row, col) {
    switch (col) {
      case "date": return row.timestamp_utc || "";
      case "timestamp": return row.timestamp_utc || "";
      case "strategy": return strategyLabel(row) || "";
      case "instrument": return row.instrument || "";
      case "side": return sideLabel(row);
      case "role": return fillRoleLabel(row);
      case "status": return `${row.order_type || ""} ${row.order_state || ""}`;
      case "quantity": return numOrNull(row.quantity);
      case "price": return numOrNull(row.price);
      case "pnl": return numOrNull(row._estimated_pnl) ?? numOrNull(row.realized_pnl);
      case "exit_reason": return row.exit_reason || "";
      case "signal": return row.from_entry_signal || row.order_name || "";
      case "order_id": return row.order_id || "";
      default: return row[col];
    }
  }

  function compareSortValues(av, bv, dir) {
    const mult = dir === "asc" ? 1 : -1;
    const an = numOrNull(av);
    const bn = numOrNull(bv);
    if (an != null || bn != null) {
      if (an == null) return 1;
      if (bn == null) return -1;
      if (Math.abs(an - bn) > 1e-9) return (an - bn) * mult;
      return 0;
    }
    const as = String(av == null ? "" : av);
    const bs = String(bv == null ? "" : bv);
    return as.localeCompare(bs, "ru", { numeric: true, sensitivity: "base" }) * mult;
  }

  function sortTableRows(rows, tableName) {
    const sort = (STATE.tableSorts && STATE.tableSorts[tableName]) || DEFAULT_TRADING_TABLE_SORTS[tableName] || { col: "timestamp", dir: "desc" };
    const getter = tableName === "closedTrades" ? closedTradeSortValue : executionSortValue;
    return (Array.isArray(rows) ? rows : []).slice().sort((a, b) => {
      const primary = compareSortValues(getter(a, sort.col), getter(b, sort.col), sort.dir);
      if (primary) return primary;
      return String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || ""));
    });
  }

  function sortableHeader(tableName, col, label, cls = "") {
    const sort = (STATE.tableSorts && STATE.tableSorts[tableName]) || {};
    const active = sort.col === col;
    const dirClass = active ? (sort.dir === "asc" ? "sort-asc" : "sort-desc") : "";
    return `<th class="${[cls, "sortable", dirClass].filter(Boolean).join(" ")}" data-trading-sort-table="${escapeHtml(tableName)}" data-trading-sort="${escapeHtml(col)}">${label}</th>`;
  }

  function updateStaticSortableHeaders(tableName) {
    const sort = (STATE.tableSorts && STATE.tableSorts[tableName]) || {};
    document.querySelectorAll(`th[data-trading-sort-table="${tableName}"]`).forEach(th => {
      th.classList.remove("sort-asc", "sort-desc");
      if (th.dataset.tradingSort === sort.col) {
        th.classList.add(sort.dir === "asc" ? "sort-asc" : "sort-desc");
      }
    });
  }

  function handleTradingSortClick(th) {
    const table = th && th.dataset ? th.dataset.tradingSortTable : "";
    const col = th && th.dataset ? th.dataset.tradingSort : "";
    if (!table || !col) return;
    const current = (STATE.tableSorts && STATE.tableSorts[table]) || { col, dir: "desc" };
    const next = current.col === col
      ? { col, dir: current.dir === "desc" ? "asc" : "desc" }
      : { col, dir: "desc" };
    STATE.tableSorts[table] = next;
    saveTradingTableSorts();
    if (table === "runtimeStrategies") {
      renderRuntimeTable();
    } else if (table === "closedTrades") {
      renderSelectedDayTradesPanel();
      const view = findRuntimeView(STATE.selectedRuntime);
      if (activeBottomTab() === "trades") renderTradesPane(view);
    } else if (table === "executions") {
      const view = findRuntimeView(STATE.selectedRuntime);
      if (activeBottomTab() === "trades") renderTradesPane(view);
    }
  }

  function versionLt(a, b) {
    const pa = String(a || "").split(".").map(x => Number.parseInt(x, 10) || 0);
    const pb = String(b || "").split(".").map(x => Number.parseInt(x, 10) || 0);
    const n = Math.max(pa.length, pb.length, 3);
    for (let i = 0; i < n; i += 1) {
      const av = pa[i] || 0;
      const bv = pb[i] || 0;
      if (av !== bv) return av < bv;
    }
    return false;
  }

  function markSelectedRuntimeRow() {
    const selected = String(STATE.selectedRuntime || "");
    document.querySelectorAll("#rt-strats-body tr[data-iid]").forEach(tr => {
      tr.classList.toggle("sel", !!selected && tr.dataset.iid === selected);
    });
  }

  function scheduleAnalyticsRender(sid, tabName) {
    const seq = ++STATE.analyticsRenderSeq;
    const targetTab = tabName || activeBottomTab();
    const pane = $("pane-" + targetTab);
    if (pane && targetTab !== "overview") {
      pane.innerHTML = '<div class="muted-empty compact">Загрузка...</div>';
    }
    setTimeout(() => {
      if (seq !== STATE.analyticsRenderSeq) return;
      renderAnalytics(sid, targetTab);
    }, 50);
  }

  function runtimeTableCellNumber(view) {
    if (view && view.cell_num != null) return numOrNull(view.cell_num);
    const raw = String(view && view.cell_id || "");
    const m = raw.match(/(\d+)/);
    return m ? Number(m[1]) : null;
  }

  function runtimeTableStateRank(view) {
    if (view && view._is_phantom) return 3;
    if (!(view && view.runtime_detected)) return 2;
    return view.runtime_enabled ? 0 : 1;
  }

  function runtimeTableMetrics(view, ctx) {
    const rt = (view && view.runtime) || {};
    const startDatePt = strategyStartDateForView(view);
    const dayClosed = (ctx.strategyDayClosed || ctx.dayClosed || [])
      .filter(r => rowMatchesStrategyView(r, view) && rowOnOrAfterDate(r, startDatePt));
    const dayRows = (ctx.strategyDayRows || ctx.dayRows || [])
      .filter(r => rowMatchesStrategyView(r, view) && rowOnOrAfterDate(r, startDatePt));
    const allClosed = (ctx.strategyAllClosed || ctx.allClosed || [])
      .filter(r => rowMatchesStrategyView(r, view) && rowOnOrAfterDate(r, startDatePt));
    const selectedIsToday = !!ctx.selectedIsToday;
    const mappedPnl = dayClosed.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
    const pnlDay = dayClosed.length ? mappedPnl : selectedIsToday ? numOrNull(rt.realized_pnl) : 0;
    const pnlAll = allClosed.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
    return { dayClosed, dayRows, allClosed, pnlDay, pnlAll };
  }

  function runtimeSortValue(view, col, ctx) {
    const rt = (view && view.runtime) || {};
    const metrics = runtimeTableMetrics(view, ctx || {});
    switch (col) {
      case "cell": return runtimeTableCellNumber(view);
      case "strategy": return runtimeClassName(view);
      case "account": return rt.account_name || view.account_name || "";
      case "mode": return view.account_mode || rt.account_mode || "";
      case "instrument": return rt.instrument || rt.contract_month || "";
      case "timeframe": return rt.timeframe || "";
      case "state": return runtimeTableStateRank(view);
      case "entry_window": return (computeTradeWindowState(view).label || "");
      case "params": return view && view._is_phantom ? -1 : (view && view.params_ok ? 1 : 0);
      case "trades": return metrics.dayClosed.length;
      case "position": return numOrNull(rt.position_qty) || 0;
      case "pnl_day": return metrics.pnlDay;
      case "pnl_all": return metrics.pnlAll;
      case "last_update": return rt.timestamp_utc || "";
      case "runtime_duration": return strategyRuntimeDurationSec(view) ?? -1;
      case "display": return view && view.display_hidden ? 0 : 1;
      default: return "";
    }
  }

  function sortRuntimeRows(rows, ctx) {
    const sort = (STATE.tableSorts && STATE.tableSorts.runtimeStrategies)
      || DEFAULT_TRADING_TABLE_SORTS.runtimeStrategies;
    return (Array.isArray(rows) ? rows : []).slice().sort((a, b) => {
      const primary = compareSortValues(
        runtimeSortValue(a, sort.col, ctx),
        runtimeSortValue(b, sort.col, ctx),
        sort.dir,
      );
      if (primary) return primary;
      return compareSortValues(runtimeTableCellNumber(a), runtimeTableCellNumber(b), "asc")
        || String(runtimeClassName(a) || "").localeCompare(String(runtimeClassName(b) || ""), "ru", { numeric: true, sensitivity: "base" });
    });
  }

  function strategyRiskBreachForDay(view, closedRows) {
    const rows = (closedRows || []).slice().sort((a, b) =>
      String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || "")));
    const params = ((view && view.runtime && (view.runtime.params || view.runtime.parameters))
      || (view && view.locked_params) || {});
    const dailyLossLimit = numOrNull(params.DailyLossLimit) ?? numOrNull(params.MaxDailyLossUsd);
    const maxTrades = numOrNull(params.MaxTradesPerDay);
    const maxConsecutive = numOrNull(params.MaxConsecutiveLosses);
    const pnl = rows.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
    let consec = 0;
    let maxConsecSeen = 0;
    for (const r of rows) {
      if (Number(r.pnl || 0) < 0) {
        consec += 1;
        maxConsecSeen = Math.max(maxConsecSeen, consec);
      } else if (Number(r.pnl || 0) > 0) {
        consec = 0;
      }
    }
    const reasons = [];
    if (dailyLossLimit != null && dailyLossLimit > 0 && pnl <= -dailyLossLimit) {
      reasons.push(`daily loss ${fmtMoney(pnl)} <= -${fmtMoney(dailyLossLimit)}`);
    }
    if (maxTrades != null && maxTrades > 0 && rows.length >= maxTrades) {
      reasons.push(`trades ${rows.length} >= ${maxTrades}`);
    }
    if (maxConsecutive != null && maxConsecutive > 0 && maxConsecSeen >= maxConsecutive) {
      reasons.push(`consecutive losses ${maxConsecSeen} >= ${maxConsecutive}`);
    }
    return { breached: reasons.length > 0, reasons, pnl, maxConsecSeen };
  }

  function renderRuntimeTable() {
    const body = $("rt-strats-body");
    const allRows = STATE.runtimeStrats || [];
    const visible = visibleRuntimeStrats();
    const hiddenCount = allRows.filter(s => s.display_hidden).length;
    $("rt-strats-count").textContent = String(visible.length);
    const hiddenEl = $("rt-hidden-count");
    if (hiddenEl) hiddenEl.textContent = hiddenCount ? `скрыто: ${hiddenCount}` : "";
    const banner = $("rt-banner");
    banner.innerHTML = "";
    if (!visible.length) {
      const msg = "Нет активных стратегий в NinjaTrader. " +
                  "Добавьте и включите стратегию вручную: NinjaTrader → Strategies tab → Add → Enable. " +
                  "После этого она появится здесь и платформа начнёт мониторинг.";
      const hiddenMsg = hiddenCount && !STATE.showHiddenStrategies
        ? " Все текущие стратегии скрыты фильтром."
        : "";
      body.innerHTML = `<tr><td colspan="16" class="muted-empty">${escapeHtml(msg + hiddenMsg)}</td></tr>`;
      updateStaticSortableHeaders("runtimeStrategies");
      return;
    }
    const acctMetrics = STATE.accountMetrics || computeAccountMetrics();
    const selectedDate = acctMetrics.selectedDatePt || acctMetrics.date_pt || todayWallPtDate();
    const selectedIsToday = selectedDate === acctMetrics.date_pt;
    const pnlHead = $("rt-pnl-day-head");
    if (pnlHead) pnlHead.textContent = selectedIsToday ? "PnL сегодня" : "PnL выбранного дня";
    const dayRows = acctMetrics.selectedExecs || (acctMetrics.executions || [])
      .filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, selectedDate));
    const dayClosed = acctMetrics.selectedClosedTrades || (acctMetrics.allClosedTrades || [])
      .filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, selectedDate));
    const allClosed = acctMetrics.allClosedTrades || [];
    const strategyDayRows = acctMetrics.strategySelectedExecs || (acctMetrics.strategyExecutions || acctMetrics.executions || [])
      .filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, selectedDate));
    const strategyDayClosed = acctMetrics.strategySelectedClosedTrades || (acctMetrics.allStrategyClosedTrades || acctMetrics.allClosedTrades || [])
      .filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, selectedDate));
    const strategyAllClosed = acctMetrics.allStrategyClosedTrades || acctMetrics.allClosedTrades || [];
    const runtimeSortContext = {
      dayRows, dayClosed, allClosed,
      strategyDayRows, strategyDayClosed, strategyAllClosed,
      selectedIsToday,
    };
    updateStaticSortableHeaders("runtimeStrategies");
    body.innerHTML = sortRuntimeRows(visible, runtimeSortContext).map(s => {
      const rt = s.runtime || {};
      const startDatePt = strategyStartDateForView(s);
      const mappedRows = strategyDayRows.filter(r => rowMatchesStrategyView(r, s) && rowOnOrAfterDate(r, startDatePt));
      const closedRows = strategyDayClosed.filter(r => rowMatchesStrategyView(r, s) && rowOnOrAfterDate(r, startDatePt));
      const allClosedRows = strategyAllClosed.filter(r => rowMatchesStrategyView(r, s) && rowOnOrAfterDate(r, startDatePt));
      const closedUnmappedRows = dayClosed.filter(r => closedUnmappedTradeMatchesStrategyView(r, s));
      const unmappedRows = closedUnmappedRows;
      const iid = s.runtime_instance_id || s.strategy_id || "";
      const cls = rt.strategy_class || s.strategy_id || "";
      const acct = rt.account_name || s.account_name || "—";
      const mode = s.account_mode || rt.account_mode || "—";
      const modeBadge = s.is_live ? '<span class="badge bad">live</span>' :
                        mode === "playback" ? '<span class="badge warn">playback</span>' :
                        mode === "demo"     ? '<span class="badge demo">demo</span>'   :
                        mode === "paper"    ? '<span class="badge ok">paper</span>'   :
                        mode && mode !== "—" ? '<span class="badge mut">' + escapeHtml(mode) + '</span>' :
                        '<span class="muted small">—</span>';
      const inst = rt.instrument || rt.contract_month || "—";
      const tfRaw = rt.timeframe;
      const tfCell = tfRaw
        ? escapeHtml(tfRaw)
        : '<span class="muted">—</span>';
      const enabled = !!s.runtime_enabled;
      const isPhantom = !!s._is_phantom;
      const riskBreach = strategyRiskBreachForDay(s, closedRows);
      const stateBadge = isPhantom ? '<span class="badge mut" title="Не запущена в NinjaTrader">не запущена</span>' :
                         !s.runtime_detected ? '<span class="badge mut">offline</span>' :
                         enabled ? '<span class="badge ok">running</span>' :
                         '<span class="badge mut">stopped</span>';
      const riskBadge = riskBreach.breached
        ? `<span class="badge bad" title="${escapeHtml(riskBreach.reasons.join("; "))}">HALT</span>`
        : "";
      const pos = (rt.position_qty != null) ?
        ((rt.position_market_position || "") + " " + rt.position_qty) : "—";
      const mappedPnl = closedRows.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
      const unmappedPnl = closedUnmappedRows.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
      const pnlSource = closedRows.length ? mappedPnl
        : closedUnmappedRows.length ? 0
        : selectedIsToday ? numOrNull(rt.realized_pnl) : 0;
      const pnl = pnlSource != null ? fmtMoney(pnlSource) : "—";
      const pnlCls = moneyClass(pnlSource);
      const allTimePnl = allClosedRows.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
      const allTimePnlCls = moneyClass(allTimePnl);
      const allTimePnlTitle = `${allClosedRows.length} mapped closed trades за всё время`;
      const tradeBadge = unmappedRows.length
        ? `<span class="badge warn" title="Unmapped fills не входят в PnL стратегии. Их PnL показан отдельно и входит только в PnL счёта.">unmapped ${unmappedRows.length}</span>`
        : isPhantom ? '' : '<span class="badge ok">mapped</span>';
      const closedUnmappedText = closedUnmappedRows.length
        ? ` · unmapped closed ${closedUnmappedRows.length}`
        : "";
      const tradesCell = isPhantom
        ? '<span class="muted small">—</span>'
        : `${closedRows.length} closed · ${mappedRows.length} fills${closedUnmappedText} ${tradeBadge}`;
      const pnlSub = closedUnmappedRows.length
        ? `<div class="muted-small warn-text" title="Неподписанные закрытия по этому счёту/инструменту: входят в Account PnL, но не приписываются стратегии.">unmapped ${escapeHtml(fmtMoney(unmappedPnl))}</div>`
        : "";
      const pnlTitle = closedUnmappedRows.length
        ? `mapped ${fmtMoney(mappedPnl)}; unmapped ${fmtMoney(unmappedPnl)}; account ${selectedDate} ${fmtMoney(acctMetrics.selectedPnl)}`
        : "";
      // Params badge is informational only — Phase 19: mismatch does NOT block controls
      const pcheck = s.params_check || {};
      const nMis = (pcheck.mismatches || []).length;
      const paramsBadge = isPhantom
        ? '<span class="muted small">—</span>'
        : s.params_ok
          ? '<span class="badge ok">OK</span>'
          : `<span class="badge warn clickable params-mismatch-badge"
                  data-iid="${escapeHtml(iid)}"
                  title="${escapeHtml(paramsMismatchBadgeTitle(pcheck))}">MISMATCH (${nMis})</span>`;
      const since = isPhantom ? "—" : fmtHms(rt.timestamp_utc);
      const runtimeDuration = strategyRuntimeDurationSec(s);
      const runtimeDurationLabel = runtimeDuration == null ? "—" : fmtDurationSec(runtimeDuration);
      const hidden = !!s.display_hidden;
      const displayCls = escapeHtml(runtimeClassName(s));
      const displayToggle = isPhantom
        ? '<span class="muted small">—</span>'
        : `<input type="checkbox" class="rt-display-toggle"
          data-class-name="${displayCls}" ${hidden ? "" : "checked"}
          title="${hidden ? "Показать в приложении" : "Скрыть в приложении"}">`;
      const cellNo = s.cell_id ? String(s.cell_id).replace(/^CELL-?/i, "") : "—";
      const twSt = computeTradeWindowState(s);
      const twTintCls = twSt.tint === "in" ? " strategy-in-window"
        : twSt.tint === "out" ? " strategy-out-window" : "";
      const twLabel = twSt.label && twSt.label !== "—"
        ? escapeHtml(twSt.label)
        : '<span class="muted small">—</span>';
      const sel = (iid === STATE.selectedRuntime) ? " sel" : "";
      const phantomCls = isPhantom ? " rt-phantom-row" : "";
      const stoppedCls = (!isPhantom && s.runtime_detected && !s.runtime_enabled) ? " rt-stopped-row" : "";
      return `<tr class="${sel}${hidden ? " rt-hidden-row" : ""}${unmappedRows.length ? " rt-unmapped-row" : ""}${phantomCls}${stoppedCls}${twTintCls}" data-iid="${escapeHtml(iid)}">
        <td class="num cell-no">${escapeHtml(cellNo)}</td>
        <td>${escapeHtml(cls)}</td>
        <td>${escapeHtml(acct)}</td>
        <td>${modeBadge}</td>
        <td>${escapeHtml(inst)}</td>
        <td>${tfCell}</td>
        <td>${stateBadge}${riskBadge ? `<div class="tw-status-line">${riskBadge}</div>` : ""}</td>
        <td class="tw-cell">${twLabel}<div class="tw-status-line">${twSt.statusBadge}</div></td>
        <td>${paramsBadge}</td>
        <td>${tradesCell}</td>
        <td class="num">${escapeHtml(pos)}</td>
        <td class="num ${pnlCls}" title="${escapeHtml(pnlTitle)}"><div>${escapeHtml(pnl)}</div>${pnlSub}</td>
        <td class="num ${allTimePnlCls}" title="${escapeHtml(allTimePnlTitle)}">${escapeHtml(fmtMoney(allTimePnl))}</td>
        <td><span class="muted small">${escapeHtml(since)}</span></td>
        <td><span class="muted small">${escapeHtml(runtimeDurationLabel)}</span></td>
        <td class="num">${displayToggle}</td>
      </tr>`;
    }).join("");
    body.querySelectorAll("tr[data-iid]").forEach(tr => {
      tr.addEventListener("click", () => {
        STATE.selectedRuntime = tr.dataset.iid;
        // Phase 22c: row click is the single source of truth. Sync
        // STATE.selectedStrategy / Instrument / timeframe from this row so the
        // right-panel displays and "Открыть в бэктесте" use real runtime values.
        const view = findRuntimeView(tr.dataset.iid);
        if (view) {
          const rt = view.runtime || {};
          STATE.selectedStrategy   = rt.strategy_class || STATE.selectedStrategy;
          STATE.selectedInstrument = rt.instrument || STATE.selectedInstrument;
          const tfEl = $("sel-timeframe");
          if (tfEl && rt.timeframe) {
            // Add option dynamically if NT timeframe is not in the static list.
            if (![...tfEl.options].some(o => o.value === rt.timeframe)) {
              const o = document.createElement("option");
              o.value = rt.timeframe; o.textContent = rt.timeframe;
              tfEl.appendChild(o);
            }
            tfEl.value = rt.timeframe;
          }
          // Show panel only when row is selected.
          setRightPanelVisible(true);
        }
        renderStrategyDisplay();
        renderInstrumentDisplay();
        markSelectedRuntimeRow();
        refreshLaunchControls();
        if (view) scheduleAnalyticsRender(view.runtime_instance_id || view.strategy_id || tr.dataset.iid);
      });
    });
    body.querySelectorAll(".rt-display-toggle").forEach(cb => {
      cb.addEventListener("click", (ev) => ev.stopPropagation());
      cb.addEventListener("change", async (ev) => {
        ev.stopPropagation();
        await setStrategyHidden(cb.dataset.className || "", !cb.checked);
      });
    });
    body.querySelectorAll(".params-mismatch-badge").forEach(b => {
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        STATE.selectedRuntime = b.dataset.iid;
        markSelectedRuntimeRow();
        const view = findRuntimeView(b.dataset.iid);
        switchBottomTab("params-diff");
      });
    });
    refreshTradeWindowVisuals();
    // Phase 19: no "НЕ locked B1" banner — params mismatch is informational only.
    // Banner area reserved for bridge-level warnings (exporter version, offline).
    const hb = (STATE.runtimeStrats[0] || {}).heartbeat || {};
    const ev = hb.exporter_version || "";
    if (ev && versionLt(ev, "1.3.0")) {
      banner.innerHTML = `⚠ Bridge версия ${escapeHtml(ev)} устарела. ` +
        `Нужна 1.3.0+: она пишет strategy_id/class/name/runtime_instance_id/order_name/from_entry_signal, ` +
        `trading_cycle_id/cell_id/attribution_status/param_snapshot_hash в executions/orders. ` +
        `Закройте NinjaTrader и запустите <b>01_INSTALL_BRIDGE.cmd</b> для обновления.`;
    }
  }

  function switchBottomTab(tabName) {
    const known = new Set(["overview", "equity", "trades", "orders", "notes"]);
    let target = tabName || "overview";
    if (!known.has(target)) target = "overview";
    STATE.bottomTab = target;
    document.querySelectorAll("#bot-tabs button").forEach(b => {
      b.classList.toggle("active", b.dataset.tab === STATE.bottomTab);
    });
    document.querySelectorAll(".tab-pane").forEach(p => {
      p.classList.toggle("active", p.id === ("pane-" + STATE.bottomTab));
    });
    const view = findRuntimeView(STATE.selectedRuntime);
    if (view) scheduleAnalyticsRender(view.runtime_instance_id || view.strategy_id || STATE.selectedRuntime, STATE.bottomTab);
    else renderAccountLevelPanes(STATE.bottomTab);
  }

  // ----- analytics tabs -----------------------------------------------------
  function activeBottomTab() {
    if (STATE.bottomTab) return STATE.bottomTab;
    const active = document.querySelector("#bot-tabs button.active");
    return (active && active.dataset && active.dataset.tab) || "overview";
  }

  async function renderAnalyticsTab(view, tabName) {
    switch (tabName || "overview") {
      case "equity":
        renderEquityPane(view);
        break;
      case "trades":
        renderTradesPane(view);
        break;
      case "notes":
        await renderNotesPane(view);
        break;
      case "overview":
      default:
        renderOverviewPane(view);
        break;
    }
  }

  async function renderAnalytics(sid, tabName) {
    const view = findRuntimeView(sid);
    if (!view) return;
    STATE.accountMetrics = computeAccountMetrics();
    renderLockedParams(view);
    await renderAnalyticsTab(view, tabName || activeBottomTab());
  }

  function renderAccountLevelPanes(tabName) {
    STATE.accountMetrics = computeAccountMetrics();
    renderAnalyticsTab(null, tabName || activeBottomTab());
  }

  function strategyExecutionSets(view, datePt) {
    const m = STATE.accountMetrics || computeAccountMetrics();
    const targetDate = datePt || m.selectedDatePt || m.date_pt;
    const accountRows = (m.executions || []).filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, targetDate));
    const accountClosedRows = (m.allClosedTrades || []).filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, targetDate));
    const strategyRows = (m.strategyExecutions || m.executions || [])
      .filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, targetDate));
    const strategyClosedRows = (m.allStrategyClosedTrades || m.allClosedTrades || [])
      .filter(r => rowMatchesSelectedActivityDate(r.timestamp_utc, targetDate));
    if (!view) {
      return {
        account: accountRows,
        closedAccount: accountClosedRows,
        mapped: [],
        closedMapped: [],
        unmapped: accountRows.filter(isUnmappedTelemetry),
        closedUnmapped: accountClosedRows.filter(isClosedTradeUnmapped),
      };
    }
    return {
      account: accountRows,
      closedAccount: accountClosedRows,
      mapped: strategyRows.filter(r => rowMatchesStrategyView(r, view)),
      closedMapped: strategyClosedRows.filter(r => rowMatchesStrategyView(r, view)),
      unmapped: accountRows.filter(r => rowIsUnmappedCandidate(r, view)),
      closedUnmapped: accountClosedRows.filter(r => closedUnmappedTradeMatchesStrategyView(r, view)),
    };
  }

  function strategyOrderSets(view, datePt) {
    const accountName = selectedAccountNameForData();
    const m = STATE.accountMetrics || computeAccountMetrics();
    const targetDate = datePt || m.selectedDatePt || m.date_pt;
    const rows = (STATE.accountOrders || [])
      .filter(r => (!accountName || r.account_name === accountName) &&
        isPerformanceWindowTimestamp(r.timestamp_utc) &&
        rowMatchesSelectedActivityDate(r.timestamp_utc, targetDate));
    if (!view) {
      return {
        account: rows,
        mapped: [],
        unmapped: rows.filter(isUnmappedTelemetry),
      };
    }
    return {
      account: rows,
      mapped: rows.filter(r => rowMatchesStrategyView(r, view)),
      unmapped: rows.filter(r => rowIsUnmappedCandidate(r, view)),
    };
  }

  function mappingNotice(view, sets) {
    if (!view || !sets || !sets.unmapped.length) return "";
    const instr = instrumentOfView(view) || "—";
    return `<div class="mapping-warning">
      <b>${escapeHtml(sets.unmapped.length)}</b> fills по счёту/инструменту <b>${escapeHtml(instr)}</b>
      не размечены bridge-ом (<code>strategy_class</code> пустой). Они видны во вкладке
      <b>Unmapped</b> и в сводке счёта, но <b>не входят</b> в PnL и метрики этой стратегии.
    </div>`;
  }

  function formatMismatchParamValue(key, value) {
    if (value == null || value === "") return "—";
    if (TRADE_WINDOW_PARAM_KEYS.includes(key) && key !== "UseSecondTradeWindow"
        && key !== "Use24hSession" && key !== "IntradayOnly") {
      const hhmm = parseHhmmParam(value);
      if (hhmm) return fmtHhmmDisplay(hhmm);
    }
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value);
  }

  function paramsMismatchBadgeTitle(pcheck) {
    const mism = (pcheck && pcheck.mismatches) || [];
    if (!mism.length) return "Открыть Parameters diff";
    const lines = mism.slice(0, 4).map(m => {
      const exp = m.expected_display != null ? m.expected_display : formatMismatchParamValue(m.key, m.expected);
      const act = m.actual_display != null ? m.actual_display : formatMismatchParamValue(m.key, m.actual);
      const src = m.source ? ` [${m.source}]` : "";
      return `${m.key}: NT=${act} ≠ профиль=${exp}${src}`;
    });
    if (mism.length > 4) lines.push(`… +${mism.length - 4}`);
    if (pcheck.recommendation) lines.push(pcheck.recommendation);
    return lines.join("\n");
  }

  // --- All-time aggregates for the selected strategy class ----------------
  function strategyClassOfView(view) {
    if (!view) return "";
    const rt = view.runtime || {};
    const cls = String(rt.strategy_class || view.display_key || view.strategy_id || "").trim();
    return cls;
  }

  function classCandidatesForView(view) {
    const cands = new Set();
    const cls = strategyClassOfView(view);
    if (cls) cands.add(cls.toLowerCase());
    const profile = profileForStrategyView(view);
    if (profile) {
      for (const c of profileClassCandidates(profile)) cands.add(c);
    }
    return cands;
  }

  function rowBelongsToStrategy(row, classSet) {
    if (!row || !classSet || !classSet.size) return false;
    const candidates = [
      effectiveStrategyField(row, "strategy_class"),
      effectiveStrategyField(row, "strategy_name"),
      effectiveStrategyField(row, "strategy_id"),
    ];
    for (const c of candidates) {
      const v = String(c || "").trim().toLowerCase();
      if (v && classSet.has(v)) return true;
    }
    return false;
  }

  function rowHasMappedStrategy(row) {
    return ["strategy_class", "strategy_name", "strategy_id", "runtime_instance_id"]
      .some(field => effectiveStrategyField(row, field));
  }

  function instrumentOfView(view) {
    if (!view) return "";
    const rt = view.runtime || {};
    const profile = profileForStrategyView(view);
    return String(rt.instrument || (profile && (profile.instrument || profile.current_contract)) || "").trim();
  }

  function strategyStartDateForView(view) {
    if (!view) return "";
    const rows = STATE.strategyStartDates || {};
    const tokens = new Set([
      ...strategyTokenSet(view),
      ...viewProfileClassCandidates(view),
      ...viewProfileIdentityCandidates(view),
    ].map(x => String(x || "").trim().toLowerCase()).filter(Boolean));
    const validDate = (v) => {
      const s = String(v || "").trim();
      return parseDateKey(s) ? s : "";
    };
    for (const [key, meta] of Object.entries(rows)) {
      const direct = String(key || "").trim().toLowerCase();
      const classes = Array.isArray(meta && meta.strategy_classes)
        ? meta.strategy_classes.map(x => String(x || "").trim().toLowerCase()).filter(Boolean)
        : [];
      const ids = [
        direct,
        meta && meta.strategy_id,
        meta && meta.profile_id,
        meta && meta.stable_id,
      ].map(x => String(x || "").trim().toLowerCase()).filter(Boolean);
      if (ids.concat(classes).some(x => tokens.has(x))) {
        const d = validDate(meta && meta.start_date_pt);
        if (d) return d;
      }
    }
    const cell = String(view.cell_id || "").trim().toLowerCase();
    if (cell) {
      for (const meta of Object.values(rows)) {
        if (String(meta && meta.cell_id || "").trim().toLowerCase() === cell) {
          const d = validDate(meta && meta.start_date_pt);
          if (d) return d;
        }
      }
    }
    return "";
  }

  function rowOnOrAfterDate(row, startDatePt) {
    if (!startDatePt) return true;
    const ts = row && (row.exit_time_utc || row.timestamp_utc || row.entry_time_utc);
    const d = ptWallCalendarDate(ts);
    return !!d && d >= startDatePt;
  }

  function aggregateAllTimeForStrategy(view) {
    const classSet = classCandidatesForView(view);
    const startDatePt = strategyStartDateForView(view);
    const m = STATE.accountMetrics || computeAccountMetrics();
    const paired = {
      executions: m.strategyExecutions || m.executions || [],
      closedTrades: m.allStrategyClosedTrades || m.allClosedTrades || [],
    };
    let execs = paired.executions
      .filter(r => rowBelongsToStrategy(r, classSet))
      .filter(r => rowOnOrAfterDate(r, startDatePt));
    let closed = paired.closedTrades
      .filter(r => rowBelongsToStrategy(r, classSet))
      .filter(r => rowOnOrAfterDate(r, startDatePt));
    let orders = (STATE.accountOrders || []).filter(r =>
      isPerformanceWindowTimestamp(r.timestamp_utc) &&
      rowBelongsToStrategy(r, classSet) &&
      rowOnOrAfterDate(r, startDatePt));
    const instr = instrumentOfView(view);
    const unmappedAll = paired.executions.filter(r => rowIsUnmappedCandidate(r, view) && rowOnOrAfterDate(r, startDatePt));
    const totals = {
      fills: execs.length,
      closed: closed.length,
      unmappedFills: unmappedAll.length,
      wins: 0, losses: 0, flats: 0,
      gross: 0, commission: 0, net: 0,
      best: -Infinity, worst: Infinity,
      firstTs: "", lastTs: "",
      startDatePt,
      tradingDays: new Set(),
      instruments: new Set(),
      orderCount: orders.length,
      fallbackUsed: false,
    };
    for (const t of closed) {
      const pnl = Number(t.pnl || 0);
      totals.gross += Number(t.gross_pnl ?? t.pnl ?? 0);
      totals.commission += Number(t.commission || 0);
      totals.net += pnl;
      if (pnl > 0) totals.wins += 1;
      else if (pnl < 0) totals.losses += 1;
      else totals.flats += 1;
      if (pnl > totals.best) totals.best = pnl;
      if (pnl < totals.worst) totals.worst = pnl;
      if (t.instrument) totals.instruments.add(t.instrument);
      const ts = String(t.timestamp_utc || "");
      if (ts) {
        if (!totals.firstTs || ts < totals.firstTs) totals.firstTs = ts;
        if (!totals.lastTs || ts > totals.lastTs)  totals.lastTs = ts;
        const d = ptWallCalendarDate(ts);
        if (d) totals.tradingDays.add(d);
      }
    }
    for (const r of execs) {
      const ts = String(r.timestamp_utc || "");
      if (!ts) continue;
      if (!totals.firstTs || ts < totals.firstTs) totals.firstTs = ts;
      if (!totals.lastTs || ts > totals.lastTs)  totals.lastTs = ts;
      const d = ptWallCalendarDate(ts);
      if (d) totals.tradingDays.add(d);
      if (r.instrument) totals.instruments.add(r.instrument);
    }
    if (totals.best === -Infinity) totals.best = 0;
    if (totals.worst === Infinity) totals.worst = 0;
    return { execs, closed, orders, totals };
  }

  function renderOverviewPane(view) {
    const pane = $("pane-overview");
    if (!pane) return;
    if (!view) {
      const m = STATE.accountMetrics || computeAccountMetrics();
      const selectedDate = m.selectedDatePt || m.date_pt || todayWallPtDate();
      const d = m.selectedDay || {};
      const dayClosed = d.closedTrades || [];
      const dayOrders = selectedDayOrderRows(selectedDate);
      const dayPnl = Number(d.pnl || 0);
      const allTime = accountAllTimeStats(m);
      pane.innerHTML = `
        <div class="analytics-grid">
          <section class="analytics-panel">
            <h3>Выбранный день</h3>
            <div class="kv"><span class="k">Дата</span><span class="v">${escapeHtml(dayTitle(selectedDate))}</span></div>
            <div class="kv"><span class="k">PnL</span><span class="v ${moneyClass(dayPnl)}">${escapeHtml(fmtMoney(dayPnl))}</span></div>
            <div class="kv"><span class="k">Закрытые сделки</span><span class="v">${escapeHtml(dayClosed.length)}</span></div>
            <div class="kv"><span class="k">Fills</span><span class="v">${escapeHtml((d.executions || []).length)}</span></div>
            <div class="kv"><span class="k">Ордера</span><span class="v">${escapeHtml(dayOrders.length)}</span></div>
          </section>
          <section class="analytics-panel">
            <h3>Счёт за весь период</h3>
            <div class="kv"><span class="k">Период</span><span class="v">с ${escapeHtml(dayTitle(PERFORMANCE_START_DATE_PT))}</span></div>
            <div class="kv"><span class="k">Чистый P/L</span><span class="v ${moneyClass(allTime.pnl)}">${escapeHtml(fmtMoney(allTime.pnl))}</span></div>
            <div class="kv"><span class="k">Закрытые сделки</span><span class="v">${escapeHtml(allTime.closed)}</span></div>
            <div class="kv"><span class="k">W / L / Flat</span><span class="v">${escapeHtml(allTime.wins)} / ${escapeHtml(allTime.losses)} / ${escapeHtml(allTime.flats)}</span></div>
            <div class="kv"><span class="k">Исполнения</span><span class="v">${escapeHtml(allTime.executions)}</span></div>
          </section>
        </div>`;
      return;
    }
    const m = STATE.accountMetrics || computeAccountMetrics();
    const selectedDate = m.selectedDatePt || m.date_pt || todayWallPtDate();
    const daySets = strategyExecutionSets(view, selectedDate);
    const dayOrders = strategyOrderSets(view, selectedDate);
    const dayClosed = daySets.closedMapped || [];
    const dayFills = daySets.mapped || [];
    const dayPnl = dayClosed.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
    const dayWins = dayClosed.filter(t => Number(t.pnl || 0) > 0).length;
    const dayLosses = dayClosed.filter(t => Number(t.pnl || 0) < 0).length;
    const dayFlats = dayClosed.filter(t => Number(t.pnl || 0) === 0).length;
    const dayUnmapped = (daySets.closedUnmapped || []).length;
    const agg = aggregateAllTimeForStrategy(view);
    const t = agg.totals;
    const rt = view.runtime || {};
    const profile = profileForStrategyView(view);
    const cls = strategyClassOfView(view) || "—";
    const cellLabel = view.cell_id || (profile && profile.cell_id) || "—";
    const winRate = t.closed ? ((t.wins / t.closed) * 100) : null;
    const avgPnl = t.closed ? (t.net / t.closed) : null;
    const daysCount = t.tradingDays.size;
    const startTax = profile && profile.metrics && numOrNull(profile.metrics.commission);
    let durationLabel = "—";
    if (t.firstTs && t.lastTs) {
      const dt = (new Date(t.lastTs).getTime() - new Date(t.firstTs).getTime()) / 1000;
      durationLabel = fmtDurationSec(dt);
    }
    const finalCapital = (profile && profile.metrics && numOrNull(profile.metrics.starting_capital))
      ? (numOrNull(profile.metrics.starting_capital) + t.net)
      : null;
    const instr = instrumentOfView(view);
    pane.innerHTML = `
      <div class="analytics-grid">
        <section class="analytics-panel">
          <h3>Стратегия / ячейка</h3>
          <div class="kv"><span class="k">Ячейка</span><span class="v">${escapeHtml(cellLabel)}</span></div>
          <div class="kv"><span class="k">Класс</span><span class="v">${escapeHtml(cls)}</span></div>
          <div class="kv"><span class="k">Инструмент</span><span class="v">${escapeHtml(rt.instrument || (profile && profile.instrument) || "—")}</span></div>
          <div class="kv"><span class="k">Timeframe</span><span class="v">${escapeHtml(rt.timeframe || (profile && profile.timeframe) || "—")}</span></div>
          <div class="kv"><span class="k">Состояние</span><span class="v">${escapeHtml(view._is_phantom ? "не запущена в NinjaTrader" : (view.runtime_enabled ? "running" : (view.runtime_detected ? "stopped" : "offline")))}</span></div>
        </section>
        <section class="analytics-panel">
          <h3>Выбранный день</h3>
          <div class="kv"><span class="k">Дата</span><span class="v">${escapeHtml(dayTitle(selectedDate))}</span></div>
          <div class="kv"><span class="k">PnL стратегии</span><span class="v ${moneyClass(dayPnl)}">${escapeHtml(fmtMoney(dayPnl))}</span></div>
          <div class="kv"><span class="k">Закрытые сделки</span><span class="v">${escapeHtml(dayClosed.length)}</span></div>
          <div class="kv"><span class="k">Fills стратегии</span><span class="v">${escapeHtml(dayFills.length)}</span></div>
          <div class="kv"><span class="k">W / L / Flat</span><span class="v">${escapeHtml(dayWins)} / ${escapeHtml(dayLosses)} / ${escapeHtml(dayFlats)}</span></div>
          <div class="kv"><span class="k">Ордера стратегии</span><span class="v">${escapeHtml((dayOrders.mapped || []).length)}</span></div>
        </section>
        <section class="analytics-panel">
          <h3>Работа за всё время</h3>
          <div class="kv"><span class="k">Период</span><span class="v">${escapeHtml((t.startDatePt || t.firstTs) ? ((t.startDatePt || fmtDatePt(t.firstTs)) + " — " + (t.lastTs ? fmtDatePt(t.lastTs) : "сейчас")) : "—")}</span></div>
          <div class="kv"><span class="k">Длительность</span><span class="v">${escapeHtml(durationLabel)}</span></div>
          <div class="kv"><span class="k">Торговых дней</span><span class="v">${escapeHtml(daysCount)}</span></div>
          <div class="kv"><span class="k">Инструменты</span><span class="v">${escapeHtml([...t.instruments].sort().join(", ") || "—")}</span></div>
          <div class="kv"><span class="k">Последняя активность</span><span class="v">${escapeHtml(t.lastTs ? (fmtDatePt(t.lastTs) + " " + fmtHms(t.lastTs)) : "—")}</span></div>
        </section>
        <section class="analytics-panel">
          <h3>Сделки</h3>
          <div class="kv"><span class="k">Fills всего</span><span class="v">${escapeHtml(t.fills)}</span></div>
          <div class="kv"><span class="k">Закрытые сделки</span><span class="v">${escapeHtml(t.closed)}</span></div>
          <div class="kv"><span class="k">W / L / Flat</span><span class="v">${escapeHtml(t.wins)} / ${escapeHtml(t.losses)} / ${escapeHtml(t.flats)}</span></div>
          <div class="kv"><span class="k">Win rate</span><span class="v">${winRate == null ? "—" : escapeHtml(winRate.toFixed(1) + " %")}</span></div>
          <div class="kv"><span class="k">Avg PnL / сделку</span><span class="v ${moneyClass(avgPnl)}">${avgPnl == null ? "—" : escapeHtml(fmtMoney(avgPnl))}</span></div>
          <div class="kv"><span class="k">Best / Worst</span><span class="v">${escapeHtml(fmtMoney(t.best))} / ${escapeHtml(fmtMoney(t.worst))}</span></div>
        </section>
        <section class="analytics-panel">
          <h3>Финансы (итог)</h3>
          <div class="kv"><span class="k">Gross</span><span class="v ${moneyClass(t.gross)}">${escapeHtml(fmtMoney(t.gross))}</span></div>
          <div class="kv"><span class="k">Комиссия (всего)</span><span class="v">-${escapeHtml(fmtCurrency(t.commission))}</span></div>
          <div class="kv"><span class="k">Чистый P/L</span><span class="v ${moneyClass(t.net)}">${escapeHtml(fmtMoney(t.net))}</span></div>
          <div class="kv"><span class="k">Итоговый капитал</span><span class="v">${finalCapital == null ? "—" : escapeHtml(fmtMoney(finalCapital))}</span></div>
          <div class="kv"><span class="k">Ордеров (всего)</span><span class="v">${escapeHtml(t.orderCount)}</span></div>
        </section>
      </div>
      ${dayUnmapped ? `<div class="analytics-note warn">За выбранный день есть ${escapeHtml(dayUnmapped)} закрытых unmapped-сделок по этому инструменту/счёту. Они входят в PnL счёта, но не включены в PnL стратегии.</div>` : ""}
      ${view._is_phantom ? '<div class="analytics-note">Стратегия не запущена в NinjaTrader — статистика по последним загруженным executions/orders.</div>' : ""}
      ${t.unmappedFills ? `<div class="analytics-note warn">Bridge не размечает <code>strategy_class</code> для <b>${escapeHtml(t.unmappedFills)}</b> fills по ${escapeHtml(instr || "—")} — они <b>не включены</b> в PnL/метрики этой ячейки (см. Unmapped / сводку счёта).</div>` : ""}
      ${(t.fills === 0 && t.closed === 0) ? renderOverviewEmptyHint(view) : ""}
    `;
  }

  function renderOverviewEmptyHint(view) {
    const profile = profileForStrategyView(view);
    const since = profile && (profile.updated_at_utc || profile.last_updated_utc);
    const allExecs = STATE.accountExecs || [];
    let earliestAll = "";
    for (const r of allExecs) {
      const ts = String(r.timestamp_utc || "");
      if (ts && (!earliestAll || ts < earliestAll)) earliestAll = ts;
    }
    const sinceLabel = since ? fmtDatePt(since) : (earliestAll ? fmtDatePt(earliestAll) : "—");
    const instr = instrumentOfView(view) || "—";
    return `<div class="analytics-note warn">
      Данных по этой стратегии пока нет. Возможные причины:
      <ul style="margin:6px 0 0 16px; padding:0;">
        <li>NinjaTrader-bridge ещё не зафиксировал ни одной сделки этой ячейки.</li>
        <li>Bridge не пишет <code>strategy_class</code> в fills — они остаются unmapped на уровне счёта (${escapeHtml(instr)}).</li>
        <li>Стратегия не запущена / отключена в NinjaTrader.</li>
      </ul>
      Данные будут появляться по мере поступления executions/orders от bridge. Профиль обновлён ${escapeHtml(sinceLabel)}; всего executions в системе: ${escapeHtml(allExecs.length)}${earliestAll ? `, с ${escapeHtml(fmtDatePt(earliestAll))}` : ""}.
    </div>`;
  }

  function strategyStartingCapital(view) {
    const rt = view && view.runtime || {};
    const profile = profileForStrategyView(view) || {};
    const params = rt.params || rt.parameters || view && view.locked_params || {};
    return numOrNull(params.StartingCapital)
      ?? numOrNull(profile && profile.starting_capital)
      ?? numOrNull(profile && profile.metrics && profile.metrics.starting_capital)
      ?? PERFORMANCE_STARTING_CAPITAL;
  }

  function maxDrawdownFromCurve(values) {
    let peak = values.length ? values[0] : 0;
    let maxDd = 0;
    for (const v of values) {
      peak = Math.max(peak, v);
      maxDd = Math.min(maxDd, v - peak);
    }
    return maxDd;
  }

  function currentLosingStreak(trades) {
    let streak = 0;
    for (let i = trades.length - 1; i >= 0; i -= 1) {
      const pnl = Number(trades[i].pnl || 0);
      if (pnl < 0) streak += 1;
      else if (pnl > 0) break;
    }
    return streak;
  }

  function daysBetweenDateKeys(startKey, endKey) {
    const a = parseDateKey(startKey);
    const b = parseDateKey(endKey);
    if (!a || !b) return null;
    const at = Date.UTC(a.year, a.month - 1, a.day);
    const bt = Date.UTC(b.year, b.month - 1, b.day);
    return Math.max(0, Math.round((bt - at) / 86400000));
  }

  function profileBacktestExpectation(view, liveDays, points) {
    const profile = profileForStrategyView(view) || {};
    const metrics = profile.metrics || {};
    const period = profile.test_period || {};
    const backtestNet = numOrNull(metrics.net_profit_after_commission)
      ?? numOrNull(metrics.adj_net)
      ?? numOrNull(metrics.net_profit)
      ?? numOrNull(metrics.gross_net_profit);
    const backtestTrades = numOrNull(metrics.trade_count) ?? numOrNull(metrics.trades);
    const start = period.from_utc ? String(period.from_utc).slice(0, 10) : "";
    const end = period.to_utc ? String(period.to_utc).slice(0, 10) : "";
    const testDays = start && end ? ((daysBetweenDateKeys(start, end) || 0) + 1) : null;
    const expectedNet = backtestNet != null && testDays
      ? backtestNet / testDays * Math.max(1, liveDays || 1)
      : null;
    const expectedTrades = backtestTrades != null && testDays
      ? backtestTrades / testDays * Math.max(1, liveDays || 1)
      : null;
    const n = Math.max(2, Number(points) || 2);
    const curve = [];
    for (let i = 0; i < n; i += 1) {
      curve.push(expectedNet == null ? 0 : expectedNet * (i / Math.max(1, n - 1)));
    }
    return {
      backtestNet,
      backtestTrades,
      expectedNet,
      expectedTrades,
      testDays,
      start,
      end,
      curve,
      pf: numOrNull(metrics.profit_factor_after_commission) ?? numOrNull(metrics.profit_factor),
      winRate: numOrNull(metrics.winning_pct) ?? numOrNull(metrics.win_rate_pct),
      maxDrawdown: numOrNull(metrics.max_drawdown) ?? numOrNull(metrics.adj_max_drawdown),
    };
  }

  function drawPnlCanvas(canvas, values, opts = {}) {
    const ctx = canvas && canvas.getContext && canvas.getContext("2d");
    if (!ctx) return;
    const W = canvas.width = canvas.clientWidth || 640;
    const H = canvas.height = canvas.clientHeight || 220;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "#0a1017";
    ctx.fillRect(0, 0, W, H);
    if (!values || values.length < 2) {
      ctx.fillStyle = "#667";
      ctx.font = "12px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(opts.emptyText || "Недостаточно данных", W / 2, H / 2);
      return;
    }
    let lo = Math.min(0, ...values);
    let hi = Math.max(0, ...values);
    if (Math.abs(hi - lo) < 1e-9) hi = lo + 1;
    const finalValue = values[values.length - 1] || 0;
    const positive = finalValue >= 0;
    const lineColor = positive ? "#45d483" : "#ff7474";
    const fillColor = positive ? "rgba(69,212,131,0.22)" : "rgba(255,116,116,0.22)";
    const padL = 54, padR = 10, padT = 12, padB = 24;
    const innerW = Math.max(1, W - padL - padR);
    const innerH = Math.max(1, H - padT - padB);
    const x = i => padL + (i / Math.max(1, values.length - 1)) * innerW;
    const y = v => padT + innerH - ((v - lo) / (hi - lo)) * innerH;
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const gy = padT + innerH * i / 4;
      ctx.beginPath();
      ctx.moveTo(padL, gy);
      ctx.lineTo(padL + innerW, gy);
      ctx.stroke();
    }
    const zeroY = y(0);
    ctx.strokeStyle = "rgba(255,255,255,0.28)";
    ctx.beginPath();
    ctx.moveTo(padL, zeroY);
    ctx.lineTo(padL + innerW, zeroY);
    ctx.stroke();
    ctx.beginPath();
    values.forEach((v, i) => {
      if (i === 0) ctx.moveTo(x(i), zeroY);
      ctx.lineTo(x(i), y(v));
    });
    ctx.lineTo(x(values.length - 1), zeroY);
    ctx.closePath();
    ctx.fillStyle = fillColor;
    ctx.fill();
    ctx.beginPath();
    values.forEach((v, i) => {
      if (i === 0) ctx.moveTo(x(i), y(v));
      else ctx.lineTo(x(i), y(v));
    });
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "#7b8798";
    ctx.font = "10px sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(fmtCurrency(hi), padL - 6, padT + 8);
    ctx.fillText(fmtCurrency(lo), padL - 6, padT + innerH);
    ctx.textAlign = "left";
    ctx.fillText(opts.footer || `${values.length - 1} closed`, padL, H - 7);
  }

  function renderEquityPane(view) {
    const pane = $("pane-equity");
    if (!pane) return;
    if (!view) {
      pane.innerHTML = '<div class="muted-empty">Выберите стратегию выше.</div>';
      return;
    }
    const agg = aggregateAllTimeForStrategy(view);
    const trades = (agg.closed || []).slice().sort((a, b) =>
      String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || "")));
    let net = 0;
    const pnlCurve = [0];
    for (const t of trades) {
      net += Number(t.pnl || 0);
      pnlCurve.push(net);
    }
    const dd = maxDrawdownFromCurve(pnlCurve);
    const avg = trades.length ? net / trades.length : null;
    const winRate = trades.length
      ? trades.filter(t => Number(t.pnl || 0) > 0).length / trades.length * 100
      : null;
    const m = STATE.accountMetrics || computeAccountMetrics();
    const currentDate = m.date_pt || todayWallPtDate();
    const startDate = agg.totals.startDatePt || (agg.totals.firstTs ? ptWallCalendarDate(agg.totals.firstTs) : "");
    const lastTradeDate = agg.totals.lastTs ? ptWallCalendarDate(agg.totals.lastTs) : startDate;
    const endDate = startDate
      ? ((view.runtime_enabled || view.runtime_detected) ? currentDate : (lastTradeDate || currentDate))
      : "";
    const liveDays = startDate && endDate ? ((daysBetweenDateKeys(startDate, endDate) || 0) + 1) : 0;
    const bt = profileBacktestExpectation(view, liveDays, pnlCurve.length);
    const variance = bt.expectedNet == null ? null : net - bt.expectedNet;
    const variancePct = bt.expectedNet == null || Math.abs(bt.expectedNet) < 1e-9
      ? null
      : variance / Math.abs(bt.expectedNet) * 100;
    pane.innerHTML = `
      <div class="analytics-grid">
        <section class="analytics-panel">
          <h3>Факт: PnL стратегии от нуля</h3>
          <canvas class="strategy-equity-canvas" id="strategy-pnl-canvas"></canvas>
        </section>
        <section class="analytics-panel">
          <h3>План по бэктесту за тот же срок</h3>
          <canvas class="strategy-equity-canvas" id="strategy-plan-canvas"></canvas>
        </section>
        <section class="analytics-panel">
          <h3>Факт</h3>
          <div class="kv"><span class="k">Старт наблюдения</span><span class="v">${escapeHtml(startDate || "—")}</span></div>
          <div class="kv"><span class="k">Дней в наблюдении</span><span class="v">${escapeHtml(liveDays || "—")}</span></div>
          <div class="kv"><span class="k">Чистый P/L</span><span class="v ${moneyClass(net)}">${escapeHtml(fmtMoney(net))}</span></div>
          <div class="kv"><span class="k">Max drawdown</span><span class="v ${moneyClass(dd)}">${escapeHtml(fmtMoney(dd))}</span></div>
        </section>
        <section class="analytics-panel">
          <h3>Отклонение от плана</h3>
          <div class="kv"><span class="k">Backtest net</span><span class="v ${moneyClass(bt.backtestNet)}">${bt.backtestNet == null ? "—" : escapeHtml(fmtMoney(bt.backtestNet))}</span></div>
          <div class="kv"><span class="k">Ожидание за ${escapeHtml(liveDays || "—")} дн.</span><span class="v ${moneyClass(bt.expectedNet)}">${bt.expectedNet == null ? "—" : escapeHtml(fmtMoney(bt.expectedNet))}</span></div>
          <div class="kv"><span class="k">Разница факт - план</span><span class="v ${moneyClass(variance)}">${variance == null ? "—" : escapeHtml(fmtMoney(variance))}</span></div>
          <div class="kv"><span class="k">Отклонение</span><span class="v ${moneyClass(variance)}">${variancePct == null ? "—" : escapeHtml(variancePct.toFixed(1) + " %")}</span></div>
        </section>
        <section class="analytics-panel">
          <h3>Качество сделок</h3>
          <div class="kv"><span class="k">Закрытые сделки</span><span class="v">${escapeHtml(trades.length)}</span></div>
          <div class="kv"><span class="k">Win rate</span><span class="v">${winRate == null ? "—" : escapeHtml(winRate.toFixed(1) + " %")}</span></div>
          <div class="kv"><span class="k">Avg PnL</span><span class="v ${moneyClass(avg)}">${avg == null ? "—" : escapeHtml(fmtMoney(avg))}</span></div>
          <div class="kv"><span class="k">Текущая серия убытков</span><span class="v">${escapeHtml(currentLosingStreak(trades))}</span></div>
        </section>
        <section class="analytics-panel">
          <h3>Бэктест-качество</h3>
          <div class="kv"><span class="k">Период теста</span><span class="v">${escapeHtml(bt.start && bt.end ? `${bt.start} - ${bt.end}` : "—")}</span></div>
          <div class="kv"><span class="k">Сделки факт / план</span><span class="v">${escapeHtml(trades.length)} / ${bt.expectedTrades == null ? "—" : escapeHtml(bt.expectedTrades.toFixed(1))}</span></div>
          <div class="kv"><span class="k">PF backtest</span><span class="v">${bt.pf == null ? "—" : escapeHtml(bt.pf.toFixed(2))}</span></div>
          <div class="kv"><span class="k">Win rate backtest</span><span class="v">${bt.winRate == null ? "—" : escapeHtml(bt.winRate.toFixed(1) + " %")}</span></div>
        </section>
      </div>`;
    drawPnlCanvas($("strategy-pnl-canvas"), pnlCurve, {
      footer: `${trades.length} closed · ${fmtMoney(net)}`,
      emptyText: "Нет закрытых сделок",
    });
    drawPnlCanvas($("strategy-plan-canvas"), bt.curve, {
      footer: bt.expectedNet == null ? "нет backtest summary" : `ожидание ${fmtMoney(bt.expectedNet)}`,
      emptyText: "Нет backtest summary",
    });
  }

  function tradesPaneOrderRows(view, mode, selectedDate) {
    const m = STATE.accountMetrics || computeAccountMetrics();
    const date = selectedDate || m.selectedDatePt || m.date_pt || todayWallPtDate();
    const sortDesc = (a, b) => String(b.timestamp_utc || "").localeCompare(String(a.timestamp_utc || ""));
    if (mode === "strategy" && view) {
      return (strategyOrderSets(view, date).mapped || []).slice().sort(sortDesc);
    }
    if (mode === "unmapped") {
      const sets = strategyOrderSets(view, date);
      const unmapped = view
        ? (sets.unmapped || [])
        : (sets.account || []).filter(isUnmappedTelemetry);
      return unmapped.slice().sort(sortDesc);
    }
    return selectedDayOrderRows(date);
  }

  function tradesPaneOrdersSectionHTML(view, mode, selectedDate, executionRows) {
    const dayOrders = tradesPaneOrderRows(view, mode, selectedDate);
    const orderSummary = orderSummaryBadges(dayOrders);
    const missingFilled = filledOrdersMissingExecutions(dayOrders, executionRows || []);
    const executionGap = missingFilled.length
      ? `<span class="status-pill rejected" title="Эти Order ID имеют статус Filled, но в executions.jsonl для выбранного дня нет соответствующей записи. PnL по ним посчитать нельзя, пока bridge не пришлёт execution.">filled без executions: ${escapeHtml(missingFilled.length)}</span>`
      : "";
    const ordersHead = `<div class="day-orders-head" style="margin-top:12px;">
      <div class="day-section-title">Ордера</div>
      <span class="muted small">показан последний статус каждого Order ID · ${escapeHtml(dayOrders.length)} ордеров</span>
      <span class="day-orders-badges">${orderSummary}${executionGap}</span>
    </div>`;
    return ordersHead + (dayOrders.length
      ? dayOrdersTableHTML(dayOrders)
      : '<div class="muted-empty">Ордеров за выбранный день не найдено.</div>');
  }

  function renderTradesPane(view) {
    const pane = $("pane-trades");
    if (!pane) return;
    const sets = strategyExecutionSets(view);
    const mode = view ? STATE.tradeMode : "account";
    let rows = sets.account;
    let closedRows = sets.closedAccount;
    if (mode === "strategy") rows = sets.mapped;
    if (mode === "unmapped") rows = sets.unmapped;
    if (mode === "strategy") closedRows = sets.closedMapped;
    if (mode === "unmapped") closedRows = sets.closedUnmapped;
    const m = STATE.accountMetrics || computeAccountMetrics();
    const selectedDate = m.selectedDatePt || m.date_pt || todayWallPtDate();
    const dayOrders = tradesPaneOrderRows(view, mode, selectedDate);
    const controls = `<div class="pane-toolbar">
      <button type="button" class="${mode === "account" ? "active" : ""}" data-trade-mode="account">Все сделки счёта</button>
      <button type="button" class="${mode === "strategy" ? "active" : ""}" data-trade-mode="strategy" ${view ? "" : "disabled"}>Выбранная стратегия</button>
      <button type="button" class="${mode === "unmapped" ? "active" : ""}" data-trade-mode="unmapped">Unmapped</button>
      <span class="toolbar-note">${escapeHtml(m.selectedDatePt || m.date_pt)} · ${escapeHtml(closedRows.length)} closed · ${escapeHtml(rows.length)} fills · ${escapeHtml(dayOrders.length)} ордеров</span>
    </div>`;
    const empty = view && mode === "strategy" && !rows.length && sets.unmapped.length
      ? '<div class="mapping-warning">Mapped-сделок нет, но есть сделки по этому счёту/инструменту без strategy_id. Переключитесь на Unmapped.</div>'
      : "";
    pane.innerHTML = controls + mappingNotice(view, sets) + empty +
      `<section class="analytics-panel span-2"><h3>Закрытые сделки</h3>${tradesTableHTML(closedRows, runtimeClassName(view), 500)}</section>` +
      `<section class="analytics-panel span-2" style="margin-top:8px;"><h3>Fills / executions</h3>${renderExecutionsTable(rows)}</section>` +
      `<section class="analytics-panel span-2" style="margin-top:8px;">${tradesPaneOrdersSectionHTML(view, mode, selectedDate, rows)}</section>`;
    pane.querySelectorAll("[data-trade-mode]").forEach(btn => {
      btn.addEventListener("click", () => {
        if (btn.disabled) return;
        STATE.tradeMode = btn.dataset.tradeMode || "account";
        renderTradesPane(view);
      });
    });
  }

  function fillRoleLabel(row) {
    const explicit = String(row.role || row.position_action || "").trim().toLowerCase();
    const inferred = String(row._fill_role || "").trim().toLowerCase();
    const v = explicit || inferred;
    if (v.includes("unmatched")) return "Unmatched exit";
    if (v.includes("reverse")) return "Реверс";
    if (v.includes("exit") || v.includes("close") || v.includes("target") || v.includes("stop")) return "Выход";
    if (v.includes("entry") || v.includes("open")) return "Вход";
    if (numOrNull(row._closed_qty) > 0 && numOrNull(row._opened_qty) > 0) return "Реверс";
    if (numOrNull(row._closed_qty) > 0) return "Выход";
    if (numOrNull(row._opened_qty) > 0) return "Вход";
    return "—";
  }

  function sideLabel(row) {
    const action = String(row.order_action || row.action || "").trim();
    const al = action.toLowerCase();
    if (al.includes("sellshort")) return "Short";
    if (al.includes("buytocover")) return "Cover";
    if (al === "buy") return "Buy / Long";
    if (al === "sell") return "Sell / Short";
    const mp = String(row.market_position || "").trim();
    return mp || action || "—";
  }

  function strategyLabel(row) {
    const label = ["strategy_class", "strategy_name", "strategy_id", "runtime_instance_id"]
      .map(field => effectiveStrategyField(row, field))
      .find(Boolean);
    return label || attributionCandidateLabel(row) || "";
  }

  function renderExecutionsTable(rows) {
    if (!Array.isArray(rows) || !rows.length) {
      return '<div class="muted-empty">Сделок нет для выбранного режима.</div>';
    }
    const body = sortTableRows(rows, "executions").slice(0, 180).map(r => {
      const pnl = numOrNull(r._estimated_pnl) ?? numOrNull(r.realized_pnl);
      const gross = numOrNull(r._gross_pnl);
      const comm = numOrNull(r._commission);
      const pnlTitle = (gross != null || comm != null)
        ? `gross ${fmtMoney(gross || 0)} · commission -${fmtCurrency(comm || 0)}`
        : "";
      const strategyText = strategyLabel(r);
      const strategy = isUnmappedTelemetry(r)
        ? `<span class="badge warn">${escapeHtml(attributionCandidateLabel(r) || "Unmapped / account-level")}</span>`
        : `<span class="badge ok">${escapeHtml(strategyText || "mapped")}</span>`;
      const signal = r.from_entry_signal || r.order_name || "";
      const replay = Number(r._duplicates_ignored || 0)
        ? ` <span class="badge mut" title="Повтор этой execution был отброшен после рестарта">replay -${escapeHtml(r._duplicates_ignored)}</span>`
        : "";
      const orderInfo = r.order_type || r.order_state
        ? `${r.order_type || "—"}${r.order_state ? " / " + r.order_state : ""}`
        : "—";
      const oid = String(r.order_id || "").slice(-8);
      return `<tr class="${isUnmappedTelemetry(r) ? "unmapped-row" : ""}">
        <td><span class="muted small">${escapeHtml(fmtDatePt(r.timestamp_utc))}</span></td>
        <td><span class="muted small">${escapeHtml(fmtHms(r.timestamp_utc))}</span></td>
        <td>${strategy}${replay}</td>
        <td>${escapeHtml(r.instrument || "—")}</td>
        <td>${escapeHtml(sideLabel(r))}</td>
        <td>${escapeHtml(fillRoleLabel(r))}</td>
        <td>${escapeHtml(orderInfo)}</td>
        <td class="num">${escapeHtml(r.quantity ?? "—")}</td>
        <td class="num">${escapeHtml(fmtNum(r.price))}</td>
        <td class="num ${moneyClass(pnl)}" title="${escapeHtml(pnlTitle)}">${pnl == null ? "—" : escapeHtml(fmtMoney(pnl))}</td>
        <td>${escapeHtml(r.exit_reason || "—")}</td>
        <td><span class="muted small">${escapeHtml(signal || "—")}</span></td>
        <td><span class="muted small">${escapeHtml(oid || "—")}</span></td>
      </tr>`;
    }).join("");
    return `<table class="tg-tbl account-rows">
      <thead><tr>
        ${sortableHeader("executions", "date", "Дата")}${sortableHeader("executions", "timestamp", "Время PT")}${sortableHeader("executions", "strategy", "Стратегия")}${sortableHeader("executions", "instrument", "Инструмент")}${sortableHeader("executions", "side", "Side")}${sortableHeader("executions", "role", "Вход/выход")}${sortableHeader("executions", "status", "Тип / статус")}
        ${sortableHeader("executions", "quantity", "Qty", "num")}${sortableHeader("executions", "price", "Price", "num")}
        ${sortableHeader("executions", "pnl", "PnL", "num")}${sortableHeader("executions", "exit_reason", "Exit reason")}${sortableHeader("executions", "signal", "Signal")}${sortableHeader("executions", "order_id", "Order ID")}
      </tr></thead>
      <tbody>${body}</tbody>
    </table>`;
  }

  function tradeStrategyLabel(t, fallbackStratLabel) {
    const label = closedTradeStrategyLabel(t);
    if (label && label !== "Unmapped / неизвестная стратегия") return label;
    if (strategyMarkerIsUsable(fallbackStratLabel)) return fallbackStratLabel;
    return label;
  }

  function tradesTableHTML(trades, fallbackStratLabel, limit) {
    const cap = Math.max(1, Number(limit) || 500);
    const sorted = sortTableRows(trades, "closedTrades");
    const rows = sorted.slice(0, cap).map((t, idx) => {
      const entryTs = t.entry_time_utc || "";
      const exitTs = t.exit_time_utc || t.timestamp_utc || "";
      let duration = "—";
      const durationSec = tradeDurationValue(t);
      if (durationSec != null) duration = fmtDurationSec(durationSec);
      const direction = String(t.direction || "").toLowerCase();
      const side = direction === "long" ? "Long"
                 : direction === "short" ? "Short"
                 : (t.action || "—");
      const status = t.unmapped ? '<span class="badge warn">Unmapped</span>' : '<span class="badge ok">Closed</span>';
      const pnl = numOrNull(t.pnl);
      const gross = numOrNull(t.gross_pnl);
      const tradeNo = t.trade_no || (idx + 1);
      const tradeTitle = t.trade_id ? `Trade ID: ${t.trade_id}` : "";
      return `<tr>
        <td class="num" title="${escapeHtml(tradeTitle)}">${escapeHtml(tradeNo)}</td>
        <td>${escapeHtml(tradeStrategyLabel(t, fallbackStratLabel))}</td>
        <td>${escapeHtml(t.instrument || "—")}</td>
        <td class="num">${escapeHtml(t.quantity ?? "—")}</td>
        <td>${escapeHtml(side)}</td>
        <td>${status}</td>
        <td class="num ${moneyClass(pnl)}">${pnl == null ? "—" : escapeHtml(fmtMoney(pnl))}</td>
        <td class="num ${moneyClass(gross)}">${gross == null ? "—" : escapeHtml(fmtMoney(gross))}</td>
        <td><span class="muted small">${escapeHtml(exitTs ? fmtDatePt(exitTs) : "—")}</span></td>
        <td><span class="muted small">${escapeHtml(exitTs ? fmtHms(exitTs) : "—")}</span></td>
        <td><span class="muted small">${escapeHtml(entryTs ? fmtDatePt(entryTs) : "—")}</span></td>
        <td><span class="muted small">${escapeHtml(entryTs ? fmtHms(entryTs) : "—")}</span></td>
        <td>${escapeHtml(duration)}</td>
        <td class="num">${escapeHtml(fmtNum(t.entry_price))}</td>
        <td class="num">${escapeHtml(fmtNum(t.exit_price))}</td>
        <td class="num">-${escapeHtml(fmtCurrency(Number(t.commission || 0)))}</td>
        <td>${escapeHtml(t.exit_reason || "—")}</td>
      </tr>`;
    }).join("");
    return `<table class="tg-tbl account-rows">
      <thead><tr>
        ${sortableHeader("closedTrades", "trade_no", "№", "num")}
        ${sortableHeader("closedTrades", "strategy", "Стратегия")}
        ${sortableHeader("closedTrades", "instrument", "Инструмент")}
        ${sortableHeader("closedTrades", "quantity", "Size", "num")}
        ${sortableHeader("closedTrades", "direction", "Type")}
        <th>Status</th>
        ${sortableHeader("closedTrades", "pnl", "P/L", "num")}
        ${sortableHeader("closedTrades", "gross_pnl", "Gross", "num")}
        ${sortableHeader("closedTrades", "exit_time", "Дата выхода")}
        ${sortableHeader("closedTrades", "exit_time", "Время выхода PT")}
        ${sortableHeader("closedTrades", "entry_time", "Дата входа")}
        ${sortableHeader("closedTrades", "entry_time", "Время входа PT")}
        ${sortableHeader("closedTrades", "duration", "продолжительность")}
        ${sortableHeader("closedTrades", "entry_price", "entry_price", "num")}
        ${sortableHeader("closedTrades", "exit_price", "exit_price", "num")}
        ${sortableHeader("closedTrades", "commission", "комиссия", "num")}
        ${sortableHeader("closedTrades", "exit_reason", "exit reason")}
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  function renderSelectedDayTradesPanel() {
    const card = $("session-day-trades");
    if (!card) return;
    if (!STATE.dayExplicitlySelected || !STATE.selectedDatePt) {
      card.hidden = true;
      card.innerHTML = "";
      return;
    }
    const day = STATE.selectedDatePt;
    const accountName = selectedAccountNameForData();
    const m = STATE.accountMetrics || computeAccountMetrics();
    const trades = (m.allClosedTrades || [])
      .filter(t => (!accountName || t.account_name === accountName)
        && ptWallCalendarDate(t.timestamp_utc) === day)
      .sort((a, b) => String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || "")));
    const orders = selectedDayOrderRows(day);
    const missingFilled = filledOrdersMissingExecutions(orders, (m.selectedDay || {}).executions || []);
    card.hidden = false;
    const head = `<div class="session-card-head">
      <h3 class="grow">Календарь: сделки и ордера за ${escapeHtml(dayTitle(day))}</h3>
      <span class="muted small">${escapeHtml(trades.length)} сделок · ${escapeHtml(orders.length)} ордеров</span>
      <button type="button" class="session-btn" id="day-trades-close" title="Закрыть">×</button>
    </div>`;
    const tradeBody = trades.length
      ? `<div class="day-trades-table-wrap">${tradesTableHTML(trades, "", 500)}</div>`
      : '<div class="muted-empty">Сделок за этот день не найдено</div>';
    const orderSummary = orderSummaryBadges(orders);
    const executionGap = missingFilled.length
      ? `<span class="status-pill rejected" title="Эти Order ID имеют статус Filled, но в executions.jsonl для выбранного дня нет соответствующей записи. PnL по ним посчитать нельзя, пока bridge не пришлет execution.">filled без executions: ${escapeHtml(missingFilled.length)}</span>`
      : "";
    const ordersHead = `<div class="day-orders-head">
      <strong>Календарные ордера за день</strong>
      <span class="muted small">показан последний статус каждого Order ID</span>
      <span class="day-orders-badges">${orderSummary}${executionGap}</span>
    </div>`;
    card.innerHTML = head +
      `<div class="day-section-title">Календарные закрытые сделки</div>${tradeBody}` +
      ordersHead + dayOrdersTableHTML(orders);
    const close = $("day-trades-close");
    if (close) close.addEventListener("click", () => {
      STATE.dayExplicitlySelected = false;
      renderSelectedDayTradesPanel();
    });
  }


  function normalizePositionsForAccount() {
    const acct = selectedAccountNameForData();
    const raw = (STATE.positions || {})[acct];
    if (Array.isArray(raw)) return raw;
    if (raw && typeof raw === "object") return Object.values(raw);
    return [];
  }

  function renderPositionsPane(view) {
    const pane = $("pane-position");
    if (!pane) return;
    const rt = (view && view.runtime) || {};
    const rows = normalizePositionsForAccount();
    const liveRows = rows.filter(r => Number(r.quantity || 0) !== 0 || String(r.market_position || "").toLowerCase() !== "flat");
    const strategyBlock = view ? `<section class="analytics-panel">
      <h3>Runtime позиция стратегии</h3>
      <div class="kv"><span class="k">Инструмент</span><span class="v">${escapeHtml(rt.instrument || "—")}</span></div>
      <div class="kv"><span class="k">Side</span><span class="v">${escapeHtml(rt.position_market_position || "Flat")}</span></div>
      <div class="kv"><span class="k">Qty</span><span class="v">${escapeHtml(rt.position_qty ?? 0)}</span></div>
      <div class="kv"><span class="k">Avg price</span><span class="v">${escapeHtml(fmtNum(rt.avg_price))}</span></div>
      <div class="kv"><span class="k">Unrealized</span><span class="v ${moneyClass(rt.unrealized_pnl)}">${escapeHtml(fmtMoney(rt.unrealized_pnl))}</span></div>
    </section>` : "";
    const accountBlock = liveRows.length
      ? `<table class="tg-tbl"><thead><tr><th>Инструмент</th><th>Side</th><th class="num">Qty</th><th class="num">Avg price</th><th class="num">Unrealized</th></tr></thead><tbody>` +
        liveRows.map(r => `<tr>
          <td>${escapeHtml(r.instrument || "—")}</td>
          <td><span class="badge ${String(r.market_position || "").toLowerCase() === "short" ? "bad" : "ok"}">${escapeHtml(r.market_position || "Flat")}</span></td>
          <td class="num">${escapeHtml(r.quantity ?? "—")}</td>
          <td class="num">${escapeHtml(fmtNum(r.avg_price))}</td>
          <td class="num ${moneyClass(r.unrealized_pnl)}">${escapeHtml(fmtMoney(r.unrealized_pnl))}</td>
        </tr>`).join("") + "</tbody></table>"
      : '<div class="flat-state">Flat по всем инструментам выбранного счёта.</div>';
    pane.innerHTML = `<div class="analytics-grid">${strategyBlock}<section class="analytics-panel span-2"><h3>Позиции счёта</h3>${accountBlock}</section></div>`;
  }

  function renderStrategiesPane() {
    const pane = $("pane-strategies");
    if (!pane) return;
    const m = STATE.accountMetrics || computeAccountMetrics();
    const rows = visibleRuntimeStrats();
    if (!rows.length) {
      pane.innerHTML = '<div class="muted-empty">Активных runtime-стратегий нет.</div>';
      return;
    }
    pane.innerHTML = `<table class="tg-tbl">
      <thead><tr><th>Стратегия</th><th>Инструмент</th><th>Счёт</th><th class="num">Fills</th><th class="num">Closed</th><th class="num">Contracts</th><th class="num">Working</th><th class="num">Unmapped</th><th class="num">PnL</th></tr></thead>
      <tbody>${rows.map(s => {
        const sets = strategyExecutionSets(s);
        const orderSets = strategyOrderSets(s);
        const working = orderSets.mapped.filter(r => /working|accepted|submitted/i.test(String(r.order_state || ""))).length;
        const contracts = sets.closedMapped.reduce((acc, r) => acc + Math.abs(numOrNull(r.quantity) || 0), 0);
        const pnl = sets.closedMapped.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
        const pnlText = !sets.closedMapped.length && sets.unmapped.length ? "—" : fmtMoney(pnl);
        const rt = s.runtime || {};
        return `<tr>
          <td>${escapeHtml(rt.strategy_class || s.display_name || s.strategy_id || "—")}</td>
          <td>${escapeHtml(rt.instrument || "—")}</td>
          <td>${escapeHtml(rt.account_name || s.account_name || m.accountName || "—")}</td>
          <td class="num">${escapeHtml(sets.mapped.length)}</td>
          <td class="num">${escapeHtml(sets.closedMapped.length)}</td>
          <td class="num">${escapeHtml(fmtNum(contracts))}</td>
          <td class="num">${escapeHtml(working)}</td>
          <td class="num ${sets.unmapped.length ? "warn-text" : ""}">${escapeHtml(sets.unmapped.length)}</td>
          <td class="num ${moneyClass(pnl)}">${escapeHtml(pnlText)}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
  }

  async function renderEventsPane(view) {
    const pane = $("pane-events");
    if (!pane) return;
    let errors = [];
    try {
      const r = await api("/api/ops/runtime/errors?limit=50");
      errors = (r && r.errors) || [];
    } catch (_) {
      errors = [];
    }
    const sets = strategyExecutionSets(view);
    const synthetic = [];
    if (sets.unmapped.length) {
      synthetic.push({
        timestamp_utc: new Date().toISOString(),
        kind: "warning",
        message: `Есть ${sets.unmapped.length} unmapped executions по выбранному счёту/инструменту.`,
      });
    }
    pane.innerHTML = renderRows(synthetic.concat(errors), ["timestamp_utc", "kind", "message"]);
  }

  // Phase 5.5 — Parameters diff pane
  function strategyConfigForView(view) {
    const cls = view ? (view.runtime || {}).strategy_class : STATE.selectedStrategy;
    const fallback = STRATEGY_CONFIGS[cls] || null;
    const locked = view && view.locked_params && Object.keys(view.locked_params).length
      ? view.locked_params
      : null;
    if (!locked) return fallback;
    const displayName = String(
      view.display_name || (view.runtime || {}).strategy_name || cls || (fallback && fallback.displayName) || "locked profile"
    ).trim();
    const versionMatch = displayName.match(/\bv\d+\b/i);
    return {
      displayName,
      version: (fallback && fallback.version) || (versionMatch ? versionMatch[0] : ""),
      lockedParams: locked,
    };
  }

  function strategyConfigLabel(cfg) {
    if (!cfg) return "locked profile";
    const name = String(cfg.displayName || "").trim();
    const version = String(cfg.version || "").trim();
    if (!name) return version || "locked profile";
    if (!version) return name;
    return name.toLowerCase().includes(version.toLowerCase()) ? name : `${name} ${version}`;
  }

  function renderParamsDiffPane(view) {
    const pane = $("pane-params-diff");
    if (!pane) return;
    if (!view) {
      pane.innerHTML = '<div class="muted-empty">Сравнение параметров недоступно</div>';
      return;
    }
    const pcheck = view.params_check || {};
    const cfg = strategyConfigForView(view);
    const cfgLabel = strategyConfigLabel(cfg);
    if (!pcheck.checked) {
      pane.innerHTML = cfg
        ? '<div class="muted-empty">Данные параметров не получены от NT</div>'
        : '<div class="muted-empty">Нет конфига параметров для этой стратегии</div>';
      return;
    }
    if (view.params_ok) {
      pane.innerHTML = '<div style="padding:8px;color:#b9f5cd;">' +
        '✓ Все ' + escapeHtml(pcheck.checked) + ` параметров совпадают с ${escapeHtml(cfgLabel)}` +
        '</div>';
      return;
    }
    const srcLabel = pcheck.source || "locked profile";
    const hint = pcheck.recommendation
      ? `<div class="analytics-note warn" style="margin-bottom:8px;">${escapeHtml(pcheck.recommendation)}</div>`
      : "";
    const rows = (pcheck.mismatches || []).map(m => {
      const exp = m.expected_display != null
        ? m.expected_display
        : formatMismatchParamValue(m.key, m.expected);
      const act = m.actual == null
        ? "(missing)"
        : (m.actual_display != null ? m.actual_display : formatMismatchParamValue(m.key, m.actual));
      const reason = m.reason === "missing" ? "отсутствует в NT" : "значение";
      return `<tr class="diff">
        <td>${escapeHtml(m.key)}<div class="muted-small">${escapeHtml(reason)} · ${escapeHtml(m.source || srcLabel)}</div></td>
        <td class="expected">${escapeHtml(exp)}</td>
        <td class="actual">${escapeHtml(act)}</td>
      </tr>`;
    }).join("");
    pane.innerHTML = `${hint}<table class="params-diff-tbl">
      <thead><tr>
        <th>Параметр</th>
        <th>Ожидается (${escapeHtml(cfgLabel)})</th>
        <th>Фактически в NT</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  function renderOrdersAudit(rows) {
    if (!Array.isArray(rows) || !rows.length) {
      return '<div class="muted-empty">Журнал ордеров пуст.</div>';
    }
    const counts = {};
    for (const r of rows) {
      const st = String(r.order_state || "").toLowerCase() || "—";
      counts[st] = (counts[st] || 0) + 1;
    }
    const STATE_BADGE = {
      filled:        "ok",
      partfilled:    "ok",
      working:       "warn",
      accepted:      "warn",
      submitted:     "warn",
      cancelpending: "mut",
      cancelled:     "mut",
      rejected:      "bad",
      expired:       "mut",
    };
    const order = ["filled","partfilled","working","accepted","submitted","cancelled","cancelpending","rejected","expired"];
    const summaryParts = order.filter(k => counts[k]).map(k =>
      `<span class="badge ${STATE_BADGE[k] || "mut"}">${escapeHtml(k)}: ${counts[k]}</span>`
    );
    for (const k of Object.keys(counts)) {
      if (!order.includes(k)) summaryParts.push(`<span class="badge mut">${escapeHtml(k)}: ${counts[k]}</span>`);
    }
    const summary = `<div style="padding:6px 8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;">
       <span class="muted small">Всего событий: ${rows.length}</span>
       ${summaryParts.join(" ")}
     </div>`;

    const body = rows.slice().reverse().slice(0, 220).map(r => {
      const ts = fmtHms(r.timestamp_utc);
      const oid = String(r.order_id || "").slice(-8) || "—";
      const action = String(r.order_action || "—");
      const actCls = /buy/i.test(action) ? "ok" : (/sell/i.test(action) ? "bad" : "mut");
      const otype = String(r.order_type || "—");
      const st = String(r.order_state || "—");
      const stCls = STATE_BADGE[st.toLowerCase()] || "mut";
      const qtyTotal = (r.quantity != null) ? r.quantity : "—";
      const qtyFilled = (r.filled != null) ? r.filled : 0;
      const qtyCell = (r.filled != null && r.quantity != null && r.filled !== r.quantity)
        ? `${qtyFilled}/${qtyTotal}` : String(qtyTotal);
      const lim = numOrNull(r.limit_price);
      const stp = numOrNull(r.stop_price);
      const avg = numOrNull(r.avg_fill);
      const limCell = lim != null ? escapeHtml(fmtNum(lim)) : "—";
      const stpCell = stp != null ? escapeHtml(fmtNum(stp)) : "—";
      const avgCell = avg != null ? escapeHtml(fmtNum(avg)) : "—";
      const inst = r.instrument || "—";
      const signal = r.from_entry_signal || r.order_name || "";
      const stratCell = escapeHtml(r.strategy_class || r.strategy_name || r.strategy_id || "—");
      const mapping = isUnmappedTelemetry(r)
        ? '<span class="badge warn">Unmapped / account-level</span>'
        : `<span class="badge ok">${escapeHtml(r.strategy_class || r.strategy_id || r.runtime_instance_id || "mapped")}</span>`;
      return `<tr>
        <td><span class="muted small">${escapeHtml(fmtDatePt(r.timestamp_utc))}</span></td>
        <td><span class="muted small">${escapeHtml(ts)}</span></td>
        <td><span class="muted small">${escapeHtml(oid)}</span></td>
        <td><span class="muted small">${stratCell}</span></td>
        <td><span class="badge ${actCls}">${escapeHtml(action)}</span></td>
        <td>${escapeHtml(otype)}</td>
        <td><span class="badge ${stCls}">${escapeHtml(st)}</span></td>
        <td class="num">${escapeHtml(qtyCell)}</td>
        <td class="num">${limCell}</td>
        <td class="num">${stpCell}</td>
        <td class="num">${avgCell}</td>
        <td><span class="muted small">${escapeHtml(inst)}</span></td>
        <td><span class="muted small">${escapeHtml(signal || "—")}</span></td>
        <td>${mapping}</td>
      </tr>`;
    }).join("");
    return summary + `<table class="tg-tbl">
      <thead><tr>
        <th>Дата</th><th>Время PT</th><th>Order ID</th><th>Стратегия</th><th>Действие</th><th>Тип</th>
        <th>Состояние</th><th class="num">Кол-во</th><th class="num">Limit</th><th class="num">Stop</th><th class="num">Avg</th><th>Инструмент</th><th>Signal</th><th>Mapping</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>`;
  }

  function renderRows(rows, cols) {
    if (!Array.isArray(rows) || !rows.length) {
      return '<div class="muted-empty">Нет данных.</div>';
    }
    const head = "<tr>" + cols.map(c => "<th>" + escapeHtml(c) + "</th>").join("") + "</tr>";
    const body = rows.slice(-100).reverse().map(r => {
      return "<tr>" + cols.map(c => {
        const v = r[c];
        return "<td>" + escapeHtml(v == null ? "" : String(v)) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return '<table class="tg-tbl"><thead>' + head + "</thead><tbody>" + body + "</tbody></table>";
  }

  async function renderStrategyHistoryPane(view) {
    const pane = $("pane-history");
    if (!pane || !view) return;
    const cls = runtimeClassName(view);
    if (!STATE.showHiddenStrategies && isHistoryEntryHidden({ strategy_class: cls, strategy_name: cls })) {
      pane.innerHTML = '<div class="muted-empty">История этой стратегии скрыта настройкой отображения.</div>';
      return;
    }
    const qp = new URLSearchParams({
      class_name: cls,
      limit_events: "200",
      limit_sessions: "200",
    });
    try {
      const hist = await api("/api/ops/runtime/strategy-history?" + qp.toString());
      pane.innerHTML = renderStrategyHistory(hist);
    } catch (e) {
      pane.innerHTML = '<div class="muted-empty">История недоступна: ' +
        escapeHtml(e.message) + '</div>';
    }
  }

  function notesStrategyId(view) {
    if (!view) return "";
    const rt = view.runtime || {};
    return String(view.strategy_id || rt.strategy_id || runtimeClassName(view) || "").trim();
  }

  async function renderNotesPane(view) {
    const pane = $("pane-notes");
    if (!pane) return;
    if (!view) {
      pane.innerHTML = '<div class="muted-empty">Выберите стратегию выше.</div>';
      return;
    }
    const sid = notesStrategyId(view);
    if (!sid) {
      pane.innerHTML = '<div class="muted-empty">У выбранной стратегии нет strategy_id для заметок.</div>';
      return;
    }
    let notes = "";
    try {
      const resp = await api("/api/ops/strategies/" + encodeURIComponent(sid) + "/notes");
      notes = String(resp && resp.notes || "");
    } catch (e) {
      pane.innerHTML = '<div class="muted-empty">Заметки недоступны: ' + escapeHtml(e.message) + '</div>';
      return;
    }
    pane.innerHTML = `
      <div class="analytics-grid">
        <section class="analytics-panel">
          <h3>Новая заметка</h3>
          <div class="notes-editor">
            <textarea id="strategy-note-text" placeholder="Статус испытания, комментарий по сделке, решение по стратегии"></textarea>
            <button type="button" id="strategy-note-add">Добавить заметку</button>
            <div class="muted-small" id="strategy-note-status">${escapeHtml(sid)}</div>
          </div>
        </section>
        <section class="analytics-panel">
          <h3>История заметок</h3>
          <div class="notes-body">${notes ? escapeHtml(notes) : "Заметок пока нет."}</div>
        </section>
      </div>`;
    const btn = $("strategy-note-add");
    const ta = $("strategy-note-text");
    const status = $("strategy-note-status");
    if (btn && ta) {
      btn.addEventListener("click", async () => {
        const text = String(ta.value || "").trim();
        if (!text) {
          if (status) status.textContent = "Введите текст заметки.";
          return;
        }
        btn.disabled = true;
        if (status) status.textContent = "Сохранение...";
        try {
          await api("/api/ops/strategies/" + encodeURIComponent(sid) + "/notes", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
          });
          await renderNotesPane(view);
        } catch (e) {
          btn.disabled = false;
          if (status) status.textContent = "Ошибка: " + e.message;
        }
      });
    }
  }

  function renderStrategyHistory(hist) {
    const allSessions = (hist && hist.sessions) || [];
    const allEvents = (hist && hist.events) || [];
    const sessions = visibleHistorySessions(allSessions);
    const events = visibleHistoryEvents(allEvents);
    const hiddenSessions = Math.max(0, allSessions.length - sessions.length);
    const warnings = (hist && hist.warnings) || [];
    const totalDurationSec = sessions.reduce((acc, s) => acc + Number(s.duration_sec || 0), 0);
    const activeSessions = sessions.filter(s => s.is_open).length;
    const chips = `<div class="history-summary">
      <span class="badge ok">активно: ${escapeHtml(activeSessions || 0)}</span>
      <span class="badge mut">сессий: ${escapeHtml(sessions.length || 0)}</span>
      <span class="badge mut">всего: ${escapeHtml(fmtDurationSec(totalDurationSec || 0))}</span>
    </div>`;
    const warnBlock = warnings.length
      ? '<div class="rt-banner">' + warnings.map(escapeHtml).join("<br>") + '</div>'
      : "";
    if (!sessions.length && !events.length) {
      if (hiddenSessions && !STATE.showHiddenStrategies) {
        return chips + warnBlock +
          '<div class="muted-empty">История скрыта фильтром отображения стратегий.</div>';
      }
      return chips + warnBlock +
        '<div class="muted-empty">История пока пуста. Новые включения/остановки начнут записываться после обновления bridge.</div>';
    }
    const sessionRows = sessions.slice().reverse().map(s => {
      const status = s.is_open
        ? '<span class="badge ok">идёт</span>'
        : '<span class="badge mut">закрыта</span>';
      return `<tr>
        <td>${escapeHtml(fmtDateTime(s.started_at_utc))}</td>
        <td>${s.is_open ? status : escapeHtml(fmtDateTime(s.ended_at_utc))}</td>
        <td class="num">${escapeHtml(fmtDurationSec(s.duration_sec))}</td>
        <td>${escapeHtml(s.account_name || "")}</td>
        <td>${escapeHtml(s.instrument || "")}</td>
        <td>${escapeHtml(s.timeframe || "")}</td>
        <td>${escapeHtml(s.start_event || "")}${s.end_reason ? " / " + escapeHtml(s.end_reason) : ""}</td>
      </tr>`;
    }).join("");
    const eventsRows = events.slice(-50).reverse().map(e => `<tr>
      <td>${escapeHtml(fmtDateTime(e.timestamp_utc))}</td>
      <td>${escapeHtml(e.event || "")}</td>
      <td>${escapeHtml(e.account_name || "")}</td>
      <td>${escapeHtml(e.instrument || "")}</td>
      <td>${escapeHtml(e.state || "")}</td>
      <td>${escapeHtml(e.reason || "")}</td>
    </tr>`).join("");
    return chips + warnBlock + `<table class="tg-tbl history-table">
      <thead><tr>
        <th>Старт</th><th>Финиш</th><th class="num">Длительность</th>
        <th>Счёт</th><th>Инструмент</th><th>TF</th><th>Событие</th>
      </tr></thead>
      <tbody>${sessionRows}</tbody>
    </table>
    <details class="history-events">
      <summary>Сырые события (${events.length})</summary>
      <table class="tg-tbl">
        <thead><tr><th>Время</th><th>Event</th><th>Счёт</th><th>Инструмент</th><th>State</th><th>Reason</th></tr></thead>
        <tbody>${eventsRows}</tbody>
      </table>
    </details>`;
  }

  // ----- locked params + launch gating -------------------------------------
  function renderLockedParams(view) {
    const root = $("locked-params");
    const cfg = strategyConfigForView(view);
    if (!cfg) {
      root.innerHTML = '<div class="muted-empty" style="padding:4px;">Нет конфига параметров для этой стратегии.</div>';
      return;
    }
    const mism = (view && view.params_check && view.params_check.mismatches) || [];
    const mismMap = {};
    mism.forEach(m => { mismMap[m.key] = m; });
    const header = `<div style="font-size:10px;color:#667;margin-bottom:4px;">${escapeHtml(strategyConfigLabel(cfg))}</div>`;
    root.innerHTML = header + Object.entries(cfg.lockedParams).map(([k, v]) => {
      const m = mismMap[k];
      const cls2 = m ? " mismatch" : "";
      const actual = m ? (" (rt=" + (m.actual ?? "missing") + ")") : "";
      return `<div class="row${cls2}"><span class="k">${k}</span><span class="v">${v}${actual}</span></div>`;
    }).join("");
  }

  // Per-strategy "best params" registry.
  // Add a new entry here when you have optimised locked params for a strategy.
  // Key: exact strategy class name as reported by NinjaTrader.
  // If a strategy has no entry, the locked-params panel and params diff are hidden.
  const STRATEGY_CONFIGS = {
    "NTAMicroVwapRiskPilot": {
      displayName: "VWAP Short MNQ 5m v1",
      version: "v1",
      lockedParams: {
        EnableLong: false, EnableShort: true, UseDailyBiasFilter: false,
        EmaFastPeriod: 50, EmaSlowPeriod: 200,
        TradeStartTime: 635, TradeEndTime: 700,
        MinStopTicks: 12, MaxStopTicks: 12,
        RewardRiskRatio: 3.5, RiskPerTradePct: 2.0, UserMaxContracts: 5,
        RoundTurnCommission: 1.90, SlippageTicks: 1,
        StartingCapital: 2000, IntradayOnly: true,
        ActiveMarginPerContract: 100, MaxContractsByCapital: 20,
        InstrumentStatus: "allowed", MarginSourceBroker: "NinjaTrader",
      },
    },
    // Пример добавления другой стратегии:
    // "MyOtherStrategy": {
    //   displayName: "Trend Follow",
    //   version: "v2",
    //   lockedParams: { EnableLong: true, EnableShort: false, ... },
    // },
  };

  // Compute the gate. Returns {can_start, reasons[]}.
  // Monitor+Validate mode: we can only enable/disable an EXISTING NT strategy instance.
  // A selected runtime row is therefore required before the button is active.
  function computeGate() {
    const reasons = [];
    if (!STATE.bridgeOnline) reasons.push("NinjaTrader bridge offline");

    // Use online_accounts list for gate check (no system accounts)
    const acctList = STATE.onlineAccounts && STATE.onlineAccounts.length
      ? STATE.onlineAccounts : STATE.accounts;
    const acct = acctList.find(a => a.account_name === STATE.selectedAccount);
    if (!acct) reasons.push("Аккаунт не выбран");
    else if (acct.account_mode === "live" || acct.is_live)
      reasons.push("Live аккаунт доступен только для чтения — управление отключено");
    else if (!["paper", "playback", "demo"].includes(acct.account_mode))
      reasons.push("Аккаунт не paper/playback/demo (mode=" + (acct.account_mode || "?") + ")");

    const cls = STATE.selectedStrategy;
    if (!cls) reasons.push("Стратегия не выбрана");

    // Monitor+Validate: must select an existing runtime row.
    if (!STATE.selectedRuntime) {
      reasons.push("Выберите строку стратегии в таблице NinjaTrader выше");
      return { can_start: false, reasons };
    }
    const view = findRuntimeView(STATE.selectedRuntime);
    if (!view) {
      reasons.push("Выбранная строка не найдена — обновите таблицу");
    } else {
      if (view.registry_status === "rejected" || view.registry_status === "archived")
        reasons.push("Стратегия rejected/archived — запуск запрещён");
      if (view.params_ok === false)
        reasons.push("Параметры instance не совпадают с locked profile");
      // Already running → enabling again makes no sense
      if (view.runtime_detected && view.runtime_enabled)
        reasons.push("Уже активна в NinjaTrader");
    }

    return { can_start: reasons.length === 0, reasons };
  }

  // Phase 22c: sel-diff block removed from DOM. The validation panel was
  // misleading (compared right-panel selectors with NT). It is now a no-op;
  // active-state info is reflected in the table badges and block-reasons.
  function renderRuntimeValidation(_view) { /* no-op */ }

  function refreshLaunchControls() {
    const gate = computeGate();
    const br       = $("block-reasons");
    const startBtn = $("btn-start");
    const stopBtn  = $("btn-stop");

    const view = findRuntimeView(STATE.selectedRuntime);
    const isRunning = !!(view && view.runtime_detected && view.runtime_enabled);
    const isStopped = !!(view && view.runtime_detected && !view.runtime_enabled);

    // ----- btn-start ("Включить instance в NT") -----
    // Hidden when row is already running; otherwise enabled per gate.
    if (startBtn) {
      if (isRunning) {
        startBtn.style.display = "none";
      } else {
        startBtn.style.display = "";
        startBtn.disabled = !gate.can_start;
        startBtn.title = !gate.can_start
          ? gate.reasons.join("; ")
          : "Включить существующий instance в NinjaTrader";
      }
    }

    // ----- btn-stop ("Остановить") -----
    // Enabled only when bridge online + valid account + row selected + currently running
    const acctList = STATE.onlineAccounts && STATE.onlineAccounts.length
      ? STATE.onlineAccounts : STATE.accounts;
    const acct = acctList.find(a => a.account_name === STATE.selectedAccount);
    const acctOk = acct &&
      !acct.is_live &&
      ["paper", "demo", "playback"].includes(acct.account_mode);
    const canStop = STATE.bridgeOnline && !!view && isRunning && !!acctOk;
    if (stopBtn) {
      stopBtn.disabled = !canStop;
      stopBtn.title = canStop ? "Отправить команду disable в NinjaTrader"
        : !STATE.bridgeOnline ? "Bridge offline"
        : !view              ? "Выберите строку в таблице"
        : !isRunning         ? "Стратегия уже остановлена в NinjaTrader"
        :                      "Остановите вручную в NinjaTrader";
    }

    // ----- block-reasons: inline status text -----
    if (br) {
      br.className = "block-reasons";
      if (isRunning) {
        br.classList.add("is-running");
        br.textContent = "✓ Активна в NinjaTrader";
      } else if (!gate.can_start && gate.reasons.length) {
        br.classList.add("is-blocked");
        // Show only first reason to keep it short; full list is in button title
        br.textContent = "⚠ " + gate.reasons[0];
      } else {
        br.textContent = "";
      }
    }

    // Update validation panel and locked params
    renderRuntimeValidation(view || null);
    renderLockedParams(view || null);
    // Honest live-status chip (read-only control policy)
    {
      const allAccts = STATE.accounts || [];
      const live = allAccts.find(a => (a.account_mode === "live") || a.is_live);
      const sel  = allAccts.find(a => a.account_name === STATE.selectedAccount);
      if (!STATE.bridgeOnline) {
        setChip("chip-live", "Live: NT offline", "bad");
      } else if (sel && (sel.account_mode === "live" || sel.is_live)) {
        setChip("chip-live", "Live: read-only (выбран)", "warn");
      } else if (live) {
        setChip("chip-live", "Live: read-only", "warn");
      } else {
        setChip("chip-live", "Live: нет", "mut");
      }
    }
  }

  // Phase 22c: selection_diff block removed; this is now a thin wrapper that
  // simply ensures the right panel visibility tracks the selected runtime row.
  function refreshSelectionDiff() {
    const view = findRuntimeView(STATE.selectedRuntime);
    STATE.selectionDiff = (view && view.selection_diff) || null;
    setRightPanelVisible(!!view);
  }

  async function refreshTradingState() {
    await loadAccounts();
    await Promise.all([
      loadAccountActivity(),
      loadRuntime(),
    ]);
  }

  // ----- online command (enable / disable strategy) ------------------------
  // Monitor+Validate mode: we only enable/disable EXISTING NinjaTrader strategy instances.
  // Creating a new instance programmatically is NOT supported by NinjaTrader AddOn API.
  async function sendCommand(command) {
    const view = findRuntimeView(STATE.selectedRuntime);

    // Gate should already prevent reaching this without a view, but guard explicitly.
    if (!view) {
      renderCmdStatus({
        state: "failed_no_instance",
        reason: "Не выбрана строка стратегии в таблице NinjaTrader. Выберите строку и повторите.",
      });
      return;
    }

    const cls  = STATE.selectedStrategy || "";
    const acct = STATE.selectedAccount || "";
    const inst = STATE.selectedInstrument || "";
    const tf   = ($("sel-timeframe") || {}).value || "5 Minute";
    if (!cls && !view)  return;
    if (!acct && !view) return;
    if (!inst && !view) return;
    const iid = (view && view.runtime_instance_id) || null;
    const rt = (view && view.runtime) || {};
    const targetCls = (rt.strategy_class || cls || "");
    const targetAcct = (rt.account_name || acct || "");
    const targetInst = (rt.instrument || inst || "");
    const targetTf = (rt.timeframe || tf || "5 Minute");
    const sid = (view && view.strategy_id) || (targetCls + "@" + targetAcct + "@" + targetInst);
    const stratCfg = strategyConfigForView(view);
    const params = (command === "enable_strategy" && stratCfg) ? stratCfg.lockedParams : {};
    const body = {
      command, strategy_id: sid, runtime_instance_id: iid, class_name: targetCls,
      account_name: targetAcct, instrument: targetInst, timeframe: targetTf,
      quantity: 1,
      operator: "ui-trading-online",
      reason: command + " from Trading Online",
      params,
    };
    try {
      const r = await api("/api/ops/runtime/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const cid = r.command_id;
      STATE.activeCommand = {
        command_id: cid,
        command,
        submitted_at_utc: r.timestamp_utc || new Date().toISOString(),
        timeout_sec: r.timeout_sec || 30,
        cls: targetCls, acct: targetAcct, inst: targetInst, tf: targetTf,
      };
      renderCmdStatus({ state: "waiting_for_bridge", elapsed_sec: 0,
                        timeout_sec: STATE.activeCommand.timeout_sec,
                        command_id: cid });
      startCmdPolling(cid, STATE.activeCommand.timeout_sec);
      setTimeout(loadRuntime, 1500);
    } catch (e) {
      renderCmdStatus({ state: "failed_other", command_id: null,
                        reason: "Backend отклонил: " + e.message });
    }
  }

  // ----- Phase 6.6 — command status polling --------------------------------
  function stopCmdPolling() {
    if (STATE.cmdPollTimer) {
      clearInterval(STATE.cmdPollTimer);
      STATE.cmdPollTimer = null;
    }
  }
  function startCmdPolling(cid, timeoutSec) {
    stopCmdPolling();
    const tick = async () => {
      try {
        const url = "/api/ops/runtime/command-status?command_id=" +
          encodeURIComponent(cid) + "&timeout_sec=" + (timeoutSec || 30);
        const st = await api(url);
        renderCmdStatus(st);
        if (st && /^(confirmed_|failed_|unknown_command)/.test(String(st.state || ""))) {
          stopCmdPolling();
          refreshTradingState();
        }
      } catch (e) {
        const msg = String(e.message || "");
        if (/no route|404|not found/i.test(msg)) {
          try {
            const fallback = await api("/api/ops/runtime/command-results?limit=50");
            const rows = (fallback && fallback.results) || [];
            const rec = rows.slice().reverse().find(r => r.command_id === cid);
            if (rec) {
              renderCmdStatus({
                state: rec.status === "completed" ? "bridge_completed_awaiting_runtime" : "failed_other",
                command_id: cid,
                reason: rec.message || "Bridge вернул результат команды.",
                bridge_result: rec,
              });
            } else {
              renderCmdStatus({ state: "failed_other", command_id: cid,
                reason: "Backend запущен старой версией: нет /api/ops/runtime/command-status. Перезапустите NT-Analyzer backend." });
            }
          } catch (e2) {
            renderCmdStatus({ state: "failed_other", command_id: cid,
              reason: "Backend запущен старой версией: нет /api/ops/runtime/command-status. Перезапустите NT-Analyzer backend." });
          }
          stopCmdPolling();
        } else {
          renderCmdStatus({ state: "failed_other", command_id: cid,
                            reason: "Не удалось опросить status: " + e.message });
          stopCmdPolling();
        }
      }
    };
    tick();
    STATE.cmdPollTimer = setInterval(tick, 1500);
  }

  function renderCmdStatus(st) {
    const bar = $("cmd-status-bar");
    if (!bar) return;
    if (!st) { bar.classList.add("hidden"); bar.innerHTML = ""; return; }
    bar.classList.remove("hidden", "waiting", "success", "failure");
    const cmdLabel = (st.command === "disable_strategy") ? "Остановка" :
                     (st.command === "enable_strategy")  ? "Запуск" : "Команда";
    const elapsed = (st.elapsed_sec != null) ? Math.round(st.elapsed_sec) : "?";
    const timeout = st.timeout_sec || 30;
    let cls = "waiting", head = "", body = "", spin = "";
    switch (String(st.state || "")) {
      case "waiting_for_bridge":
        cls = "waiting"; spin = '<span class="spinner"></span>';
        head = `${cmdLabel}: команда отправлена в NinjaTrader.`;
        body = `Жду подтверждения (${elapsed}s / ${timeout}s)…`;
        break;
      case "bridge_completed_awaiting_runtime":
        cls = "waiting"; spin = '<span class="spinner"></span>';
        head = `${cmdLabel}: NinjaTrader принял команду.`;
        body = `Жду обновления статуса стратегии…`;
        break;
      case "confirmed_running":
        cls = "success"; head = "✓ NinjaTrader подтвердил запуск стратегии."; break;
      case "confirmed_running_unverified":
        cls = "failure";
        head = "✗ Не удалось подтвердить запуск стратегии.";
        body = "Обновите список и проверьте состояние в NinjaTrader → Strategies tab.";
        break;
      case "confirmed_stopped":
        cls = "success"; head = "✓ NinjaTrader подтвердил остановку стратегии."; break;
      case "confirmed_stopped_unverified":
        cls = "failure";
        head = "✗ Не удалось подтвердить остановку стратегии.";
        body = "Обновите список и проверьте состояние в NinjaTrader → Strategies tab.";
        break;
      case "failed_no_runtime_confirmation":
        cls = "failure";
        head = "✗ NinjaTrader не подтвердил изменение состояния.";
        body = "Обновите список и проверьте Strategies tab вручную.";
        break;
      case "failed_timeout":
        cls = "failure";
        head = `✗ Таймаут ${timeout}s. NinjaTrader не обработал команду.`;
        body = "Возможные причины:\n" +
               "  • Bridge DLL устарела — закройте NT, запустите 01_INSTALL_BRIDGE.cmd, откройте NT.\n" +
               "  • RuntimeCommandProcessor не запустился — см. NTAnalyzerBridge.log.\n" +
               "  • commands.jsonl читается, но обработчик молчит.";
        break;
      case "failed_no_instance": {
        cls = "failure";
        const ac = STATE.activeCommand || {};
        head = `✗ NinjaTrader не нашёл instance стратегии '${ac.cls || st.strategy_class || "?"}' ` +
               `на счёте '${ac.acct || st.account_name || "?"}'.`;
        body = `Платформа работает в режиме Monitor+Validate и управляет только ` +
               `уже существующими strategy instances.\n` +
               `Добавьте стратегию вручную: NinjaTrader → Strategies tab → Add → ` +
               `выберите класс, инструмент и таймфрейм → Enable. ` +
               `После этого она появится в таблице выше и платформа начнёт мониторинг.`;
        break;
      }
      case "failed_account_mismatch":
        cls = "failure";
        head = "✗ Bridge отклонил: счёт не paper/playback.";
        body = (st.bridge_result && st.bridge_result.message) || st.reason || "";
        break;
      case "failed_param_mismatch":
        cls = "failure";
        head = "✗ Bridge отклонил: параметры не совпадают с locked params стратегии.";
        body = (st.bridge_result && st.bridge_result.message) || st.reason || "";
        break;
      case "failed_bridge_offline":
        cls = "failure";
        head = "✗ Bridge offline. Откройте NinjaTrader.";
        body = st.reason || "";
        break;
      case "failed_rejected":
      case "failed_other":
        cls = "failure";
        head = "✗ " + ((st.bridge_result && st.bridge_result.message) || st.reason || "Команда отклонена.");
        break;
      case "unknown_command":
        cls = "failure";
        head = "✗ Команда не найдена в commands.jsonl.";
        body = st.reason || "";
        break;
      default:
        cls = "waiting";
        head = "Статус: " + (st.state || "—");
        body = st.reason || "";
    }
    bar.classList.add(cls);
    bar.innerHTML =
      `<div class="head">${spin}${escapeHtml(head)}</div>` +
      (body ? `<div>${escapeHtml(body)}</div>` : "") +
      `<button class="reset" type="button" id="cmd-reset">Сбросить</button>`;
    const btn = $("cmd-reset");
    if (btn) btn.addEventListener("click", () => {
      stopCmdPolling();
      STATE.activeCommand = null;
      bar.classList.add("hidden");
      bar.innerHTML = "";
    });
  }

  // ----- Phase 9 — Paper status block --------------------------------------
  function _toNum(v) { const n = Number(v); return isFinite(n) ? n : 0; }
  function _toInt(v) { const n = parseInt(v, 10); return isFinite(n) ? n : 0; }

  function computePaperStatus(rows) {
    if (!Array.isArray(rows) || !rows.length) return null;
    const sorted = rows.slice().sort((a, b) =>
      String(a.date_pt || "").localeCompare(String(b.date_pt || "")));
    const first = sorted[0];
    const last  = sorted[sorted.length - 1];
    let days_elapsed = 0;
    if (first && first.date_pt) {
      const d0 = new Date(String(first.date_pt));
      const today = new Date();
      if (!isNaN(d0.getTime())) {
        days_elapsed = Math.floor((today.getTime() - d0.getTime()) / 86400000) + 1;
      }
    }
    let trading_days = 0;
    sorted.forEach(r => { if (r.trading_day_number) trading_days += 1; });
    let trades = 0, wins = 0, losses = 0, cum = 0;
    sorted.forEach(r => {
      trades += _toInt(r.trades_count);
      wins   += _toInt(r.daily_win_count);
      losses += _toInt(r.daily_loss_count);
    });
    cum = _toNum(last.cumulative_adjusted_pnl);
    const dd  = _toNum(last.current_drawdown);
    const wp  = (wins + losses) > 0 ? (100 * wins / (wins + losses)) : null;
    let days_since_last_trade = null;
    for (let i = sorted.length - 1; i >= 0; i--) {
      if (_toInt(sorted[i].trades_count) > 0) {
        const d = new Date(String(sorted[i].date_pt));
        if (!isNaN(d.getTime())) {
          days_since_last_trade = Math.floor((Date.now() - d.getTime()) / 86400000);
        }
        break;
      }
    }
    const requirement_pass = (trading_days >= 60) && (trades >= 25);
    return {
      days_elapsed, trading_days, trades, cum, dd, wp,
      days_since_last_trade, requirement_pass,
    };
  }

  async function loadPaperStatus() {
    const body = $("paper-status-body");
    if (!body) return;
    let resp;
    try {
      resp = await api("/api/ops/strategies/vwap_short_mnq_5m_v1/journal");
    } catch (e) {
      body.innerHTML = '<div class="muted-empty" style="padding:8px;">Журнал недоступен: ' +
        escapeHtml(e.message) + '</div>';
      return;
    }
    const rows = (resp && resp.rows) || [];
    STATE.paperJournal = rows;
    if (!rows.length) {
      body.innerHTML = '<div class="muted-empty" style="padding:8px;">' +
        'Журнал пуст. Запустите автозаполнение командой ' +
        '<code>POST /api/ops/strategies/vwap_short_mnq_5m_v1/journal/autofill</code> после торговой сессии.' +
        '</div>';
      return;
    }
    const m = computePaperStatus(rows);
    if (!m) { body.innerHTML = '<div class="muted-empty">Нет данных.</div>'; return; }
    renderEquitySparkline();
    const passBadge = m.requirement_pass
      ? '<span class="badge ok">PASS</span>'
      : '<span class="badge bad">FAIL</span>';
    body.innerHTML = `
      <div class="ps-grid">
        <div class="ps-cell"><span class="k">Календарных дней</span><span class="v">${m.days_elapsed}</span></div>
        <div class="ps-cell"><span class="k">Торговых дней</span><span class="v">${m.trading_days} / 60</span></div>
        <div class="ps-cell"><span class="k">Сделок</span><span class="v">${m.trades} / 25</span></div>
        <div class="ps-cell"><span class="k">Требование 60 дн ∧ 25 сделок</span><span class="v">${passBadge}</span></div>
        <div class="ps-cell"><span class="k">Cumulative adj PnL</span><span class="v">${escapeHtml(fmtMoney(m.cum))}</span></div>
        <div class="ps-cell"><span class="k">Current drawdown</span><span class="v">${escapeHtml(fmtMoney(m.dd))}</span></div>
        <div class="ps-cell"><span class="k">Win %</span><span class="v">${m.wp == null ? "—" : m.wp.toFixed(1) + "%"}</span></div>
        <div class="ps-cell"><span class="k">Дней без сделок</span><span class="v">${m.days_since_last_trade == null ? "—" : m.days_since_last_trade}</span></div>
      </div>
    `;
  }

  // ----- Phase 22c: Performance Center (left panel) ------------------------
  // Aggregates runtime data already loaded by the page (no extra polls except
  // a lightweight /api/ops/runtime/errors fetch for the events list) and
  // renders into the #performance-center sidebar. Called from loadRuntime()
  // and from loadPaperStatus() so the equity sparkline updates with the
  // journal poll.
  let _pcEventsLastFetch = 0;
  async function renderPerformanceCenter() {
    const rts = visibleRuntimeStrats();
    const accountMetrics = STATE.accountMetrics || computeAccountMetrics();

    // ---- summary cards
    let activeCount = 0;
    rts.forEach(s => {
      if (s.runtime_detected && s.runtime_enabled) activeCount += 1;
    });
    const allTime = accountAllTimeStats(accountMetrics);
    const pnlToday = accountMetrics.todayPnl;
    const tradesToday = accountMetrics.tradesCount || 0;
    const acct = accountMetrics.account || pickActiveAccount();
    const netliq = (acct && acct.net_liquidation != null) ? acct.net_liquidation
                 : (acct && acct.cash_value != null) ? acct.cash_value : null;

    const elPnl = $("pc-pnl-today");
    if (elPnl) {
      elPnl.textContent = fmtMoney(allTime.pnl);
      elPnl.title = `FIFO execution net с ${PERFORMANCE_START_DATE_PT}`;
      elPnl.classList.remove("pos", "neg");
      const cls = moneyClass(allTime.pnl);
      if (cls) elPnl.classList.add(cls);
    }
    const elPnlSource = $("pc-pnl-source");
    if (elPnlSource) elPnlSource.textContent = `start ${fmtCurrency(allTime.startingCapital)} · с ${allTime.startDate}`;
    const elNet = $("pc-netliq");
    if (elNet) {
      elNet.textContent = fmtCurrency(allTime.balance);
      elNet.title = netliq == null
        ? "Расчётный баланс = стартовый капитал + PnL с даты старта"
        : `Расчётный баланс; NinjaTrader NetLiq сейчас ${fmtCurrency(netliq)}`;
    }
    const elAct = $("pc-active-count");
    if (elAct) elAct.textContent = String(activeCount);
    const elTr = $("pc-trades-today");
    if (elTr) {
      elTr.textContent = String(allTime.closed);
      elTr.title = `Закрытые сделки с ${PERFORMANCE_START_DATE_PT}; сегодня fills ${tradesToday}`;
    }

    // ---- equity sparkline (uses paper journal cumulative_adjusted_pnl)
    renderEquitySparkline();

    // ---- active strategies list
    const elList = $("pc-active-list");
    if (elList) {
      const running = rts.filter(s => s.runtime_detected && s.runtime_enabled);
      if (!running.length) {
        elList.innerHTML = '<div class="muted-empty" style="padding:6px;">нет активных</div>';
      } else {
        const rowsHtml = running.map(s => {
          const rt = s.runtime || {};
          const agg = aggregateAllTimeForStrategy(s);
          const totals = agg.totals || {};
          const pnl = Number(totals.net || 0);
          const daySets = strategyExecutionSets(s, accountMetrics.selectedDatePt || accountMetrics.date_pt);
          const dayPnl = (daySets.closedMapped || [])
            .reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
          const unmappedClosed = (accountMetrics.allClosedTrades || [])
            .filter(r => closedUnmappedTradeMatchesStrategyView(r, s));
          const unmappedPnl = unmappedClosed.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
          const suffix = unmappedClosed.length
            ? ` · unmapped ${unmappedClosed.length} ${fmtMoney(unmappedPnl)}`
            : "";
          const tw = computeTradeWindowState(s);
          const twHint = tw.label && tw.label !== "—" ? ` · ${tw.label} PT` : "";
          return `<div class="pc-row">
            <span class="lbl">${escapeHtml((rt.strategy_class || s.strategy_id || "?"))} <span class="muted-small">${escapeHtml((rt.instrument || "") + suffix + twHint)}</span></span>
            <span class="val ${moneyClass(pnl)}" title="день / всё время">${escapeHtml(fmtMoney(dayPnl))} / ${escapeHtml(fmtMoney(pnl))}</span>
          </div>`;
        });
        const unknownUnmapped = (accountMetrics.allClosedTrades || [])
          .filter(r => isClosedTradeUnmapped(r) && !running.some(s => closedUnmappedTradeMatchesStrategyView(r, s)));
        if (unknownUnmapped.length) {
          const unknownPnl = unknownUnmapped.reduce((acc, r) => acc + (numOrNull(r.pnl) || 0), 0);
          const instruments = [...new Set(unknownUnmapped.map(r => r.instrument || "—"))].sort().join(", ");
          rowsHtml.push(`<div class="pc-row">
            <span class="lbl">Unmapped / неизвестная стратегия <span class="muted-small">${escapeHtml(instruments)} · ${unknownUnmapped.length} closed</span></span>
            <span class="val ${moneyClass(unknownPnl)}">${escapeHtml(fmtMoney(unknownPnl))}</span>
          </div>`);
        }
        elList.innerHTML = rowsHtml.join("");
      }
    }

    // ---- instrument rating by all-time account-level PnL
    const elRank = $("pc-instr-rank");
    if (elRank) {
      const ranked = Object.entries(allTime.byInstrument || {})
        .sort((a, b) => b[1].pnl - a[1].pnl);
      if (!ranked.length) {
        elRank.innerHTML = '<div class="muted-empty" style="padding:6px;">нет данных</div>';
      } else {
        elRank.innerHTML = ranked.slice(0, 8).map(([inst, m]) => {
          const cls = m.pnl >= 0 ? "pos" : "neg";
          return `<div class="pc-row">
            <span class="lbl">${escapeHtml(inst)} <span class="muted-small">${m.trades} сд.</span></span>
            <span class="val ${cls}">${escapeHtml(fmtMoney(m.pnl))}</span>
          </div>`;
        }).join("");
      }
    }

    // ---- update stamp
    const elU = $("pc-updated");
    if (elU) {
      const d = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      elU.textContent = pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    }

    // ---- last events (poll at most once per 10s)
    const now = Date.now();
    if (now - _pcEventsLastFetch > 10000) {
      _pcEventsLastFetch = now;
      try {
        const r = await api("/api/ops/runtime/errors?limit=10");
        renderPerformanceEvents((r && r.errors) || []);
      } catch (e) {
        renderPerformanceEvents([]);
      }
    }
  }

  function renderPerformanceEvents(rows) {
    const elE = $("pc-events");
    if (!elE) return;
    if (!rows || !rows.length) {
      elE.innerHTML = '<div class="muted-empty" style="padding:6px;">нет</div>';
      return;
    }
    elE.innerHTML = rows.slice(-8).reverse().map(r => {
      const ts = fmtHms(r.timestamp_utc);
      const k = String(r.kind || "").toLowerCase();
      const kindCls = (k === "error" || k === "rejected") ? "kind-error"
                    : (k === "warn" || k === "warning") ? "kind-warn" : "";
      const msg = String(r.message || r.kind || "").slice(0, 200);
      return `<div class="pc-event ${kindCls}">
        <span class="ts">${escapeHtml(ts)}</span>
        <span class="msg">${escapeHtml(msg)}</span>
      </div>`;
    }).join("");
  }

  function renderEquitySparkline() {
    const svg = $("pc-equity");
    const meta = $("pc-equity-meta");
    if (!svg) return;
    const acctMetrics = STATE.accountMetrics || null;
    if (acctMetrics) {
      const trades = (acctMetrics.allClosedTrades || []).slice().sort((a, b) =>
        String(a.timestamp_utc || "").localeCompare(String(b.timestamp_utc || "")));
      let cum = 0;
      let pts = trades.map(t => {
        cum += Number(t.pnl || 0);
        return cum;
      });
      const allTime = accountAllTimeStats(acctMetrics);
      if (!pts.length && numOrNull(allTime.pnl) != null) {
        pts = [0, Number(allTime.pnl || 0)];
      }
      if (pts.length) {
        const min = Math.min(0, ...pts), max = Math.max(0, ...pts);
        const W = 200, H = 60, pad = 2;
        const xStep = pts.length > 1 ? (W - 2 * pad) / (pts.length - 1) : 0;
        const yScale = (max - min) || 1;
        const toY = (v) => H - pad - ((v - min) / yScale) * (H - 2 * pad);
        const toX = (i) => pad + i * xStep;
        const d = pts.map((v, i) => (i === 0 ? "M" : "L") + toX(i).toFixed(1) + "," + toY(v).toFixed(1)).join(" ");
        const last = pts[pts.length - 1];
        const colour = last >= 0 ? "#6fcf97" : "#ff8a8a";
        const zeroY = toY(0);
        svg.innerHTML =
          `<line x1="0" y1="${zeroY.toFixed(1)}" x2="${W}" y2="${zeroY.toFixed(1)}" stroke="#2a2d34" stroke-width="0.5"/>` +
          `<path d="${d}" fill="none" stroke="${colour}" stroke-width="1.5"/>`;
        if (meta) meta.textContent = `с ${PERFORMANCE_START_DATE_PT}: ${fmtMoney(allTime.pnl)} · ${trades.length} closed`;
        return;
      }
    }
    const rows = STATE.paperJournal || [];
    if (!rows.length) {
      svg.innerHTML = '<text x="100" y="32" text-anchor="middle" fill="#667" font-size="10">нет данных</text>';
      if (meta) meta.textContent = "—";
      return;
    }
    const sorted = rows.slice().sort((a, b) =>
      String(a.date_pt || "").localeCompare(String(b.date_pt || "")));
    const tail = sorted.slice(-30);
    const pts = tail.map(r => Number(r.cumulative_adjusted_pnl || 0));
    if (!pts.length) {
      svg.innerHTML = '<text x="100" y="32" text-anchor="middle" fill="#667" font-size="10">нет данных</text>';
      return;
    }
    const min = Math.min(0, ...pts), max = Math.max(0, ...pts);
    const W = 200, H = 60, pad = 2;
    const xStep = pts.length > 1 ? (W - 2 * pad) / (pts.length - 1) : 0;
    const yScale = (max - min) || 1;
    const toY = (v) => H - pad - ((v - min) / yScale) * (H - 2 * pad);
    const toX = (i) => pad + i * xStep;
    const d = pts.map((v, i) => (i === 0 ? "M" : "L") + toX(i).toFixed(1) + "," + toY(v).toFixed(1)).join(" ");
    const last = pts[pts.length - 1];
    const colour = last >= 0 ? "#6fcf97" : "#ff8a8a";
    const zeroY = toY(0);
    svg.innerHTML =
      `<line x1="0" y1="${zeroY.toFixed(1)}" x2="${W}" y2="${zeroY.toFixed(1)}" stroke="#2a2d34" stroke-width="0.5"/>` +
      `<path d="${d}" fill="none" stroke="${colour}" stroke-width="1.5"/>`;
    if (meta) meta.textContent = `последний: ${fmtMoney(last)} · ${tail.length} дн.`;
  }

  // ----- wiring -------------------------------------------------------------
  function wire() {
    $("sel-account").addEventListener("change", async e => {
      STATE.selectedAccount = e.target.value;
      renderAccountInfo();
      renderAccountHeadline(pickActiveAccount());
      await loadAccountActivity();
      await loadRuntime();
    });
    const isel = $("sel-instrument");
    if (isel) isel.addEventListener("change", e => {
      STATE.selectedInstrument = e.target.value;
      renderInstrumentDisplay();
    });
    const tfSel = $("sel-timeframe");
    if (tfSel) tfSel.addEventListener("change", () => {
      loadRuntime();
    });
    $("btn-refresh").addEventListener("click", refreshTradingState);
    $("btn-status").addEventListener("click", refreshTradingState);
    const calPrev = $("cal-prev-month");
    if (calPrev) calPrev.addEventListener("click", () => {
      STATE.calendarMonthPt = addMonthsToDateKey(STATE.calendarMonthPt || todayWallPtDate(), -1);
      renderSessionBoard();
    });
    const calNext = $("cal-next-month");
    if (calNext) calNext.addEventListener("click", () => {
      STATE.calendarMonthPt = addMonthsToDateKey(STATE.calendarMonthPt || todayWallPtDate(), 1);
      renderSessionBoard();
    });
    const calToday = $("cal-today");
    if (calToday) calToday.addEventListener("click", () => {
      STATE.selectedDatePt = todayWallPtDate();
      STATE.calendarMonthPt = STATE.selectedDatePt.slice(0, 7) + "-01";
      STATE.dayExplicitlySelected = true;
      STATE.accountMetrics = computeAccountMetrics();
      renderSessionBoard();
      renderRuntimeTable();
      if (STATE.selectedRuntime) renderAnalytics(STATE.selectedRuntime);
      else renderAccountLevelPanes();
    });
    $("btn-start").addEventListener("click", () => sendCommand("enable_strategy"));
    $("btn-stop").addEventListener("click", () => sendCommand("disable_strategy"));
    const showHidden = $("chk-show-hidden");
    if (showHidden) showHidden.addEventListener("change", e => {
      STATE.showHiddenStrategies = !!e.target.checked;
      const selected = findRuntimeView(STATE.selectedRuntime);
      if (selected && selected.display_hidden && !STATE.showHiddenStrategies) {
        STATE.selectedRuntime = null;
        setRightPanelVisible(false);
      }
      renderRuntimeTable();
      renderPerformanceCenter();
      refreshSelectionDiff();
      if (STATE.selectedRuntime) renderAnalytics(STATE.selectedRuntime);
      const histPanel = $("trading-history-panel");
      if (histPanel && !histPanel.hidden) loadTradingHistory();
    });
    const btnClose = $("btn-close-right");
    if (btnClose) btnClose.addEventListener("click", () => {
      STATE.selectedRuntime = null;
      renderRuntimeTable();
      setRightPanelVisible(false);
      refreshLaunchControls();
    });
    const obb = $("btn-open-backtest");
    if (obb) obb.addEventListener("click", () => {
      // Phase 22c: pass full runtime instance — strategy class, instrument,
      // timeframe AND actual NT params — so the backtest page can prefill the
      // form with what is *really* running, not what was in the dropdowns.
      const view = findRuntimeView(STATE.selectedRuntime);
      const rt = (view && view.runtime) || {};
      const cls  = rt.strategy_class || STATE.selectedStrategy || "";
      const inst = rt.instrument || STATE.selectedInstrument || "";
      const tf   = rt.timeframe || ($("sel-timeframe") || {}).value || "5 Minute";
      const qp = new URLSearchParams({ strategy: cls, instrument: inst, timeframe: tf });
      // Runtime params come from bridge as rt.parameters / rt.params (object).
      // Encode as JSON in the URL so the backtest page can apply them verbatim.
      const rtParams = (rt.parameters && typeof rt.parameters === "object") ? rt.parameters
                     : (rt.params     && typeof rt.params     === "object") ? rt.params
                     : null;
      if (rtParams && Object.keys(rtParams).length) {
        try { qp.set("params", JSON.stringify(rtParams)); }
        catch (_) { /* ignore non-serialisable values */ }
      }
      window.open("/ui/index.html?" + qp.toString(), "_blank");
    });
    document.querySelectorAll("#bot-tabs button").forEach(b => {
      b.addEventListener("click", () => switchBottomTab(b.dataset.tab));
    });
    document.addEventListener("click", (e) => {
      const th = e.target && e.target.closest ? e.target.closest("th[data-trading-sort]") : null;
      if (th) handleTradingSortClick(th);
    });
    window.addEventListener("beforeunload", () => {
      stopCmdPolling();
      if (STATE.timer) clearInterval(STATE.timer);
      if (STATE.tradeWindowTimer) clearInterval(STATE.tradeWindowTimer);
    });
  }

  async function init() {
    wire();
    await Promise.all([
      loadCatalog(),
      loadAccounts(),
    ]);
    STATE.accountMetrics = computeAccountMetrics(true);
    renderAccountOverviewBand();
    renderSessionBoard();
    await Promise.all([
      loadAccountActivity(),
      loadRuntime(),
    ]);
    await loadPaperStatus();
    refreshLaunchControls();
    renderPerformanceCenter();
    STATE.timer = setInterval(refreshTradingState, 5000);
    STATE.tradeWindowTimer = setInterval(refreshTradeWindowVisuals, 30000);
  }

  document.addEventListener("DOMContentLoaded", init);

  // ----- Trading History -------------------------------------------------------
  async function loadTradingHistory() {
    const tbody = document.getElementById("history-tbody");
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="8" class="muted-empty">Загрузка…</td></tr>';
    try {
      const data = await api("/api/ops/runtime/history?limit=200");
      const allSessions = (data && data.sessions) || [];
      const sessions = visibleHistorySessions(allSessions);
      const hiddenSessions = Math.max(0, allSessions.length - sessions.length);
      tbody.replaceChildren();
      if (!sessions.length) {
        const msg = hiddenSessions && !STATE.showHiddenStrategies
          ? "Все сессии скрыты фильтром отображения стратегий."
          : "История пуста — стратегии ещё не запускались.";
        tbody.innerHTML = `<tr><td colspan="8" class="muted-empty">${escapeHtml(msg)}</td></tr>`;
        return;
      }
      const fmtPT = (iso) => {
        if (!iso) return "—";
        try {
          const d = new Date(iso);
          const formatted = PT_DATETIME_FORMATTER ? PT_DATETIME_FORMATTER.format(d).slice(0, 16) : iso.slice(0, 16);
          return formatted + " PT";
        } catch { return iso.slice(0,16); }
      };
      const fmtDur = (sec) => {
        if (sec == null || isNaN(sec)) return "—";
        const s = Math.round(sec);
        if (s < 60) return s + "с";
        if (s < 3600) return Math.floor(s/60) + "м " + (s%60) + "с";
        return Math.floor(s/3600) + "ч " + Math.floor((s%3600)/60) + "м";
      };
      const fmtParams = (sess) => {
        const p = sess.parameters || sess.locked_parameters || sess.config || {};
        if (!p || typeof p !== "object") return "—";
        const keys = Object.keys(p);
        if (!keys.length) return "—";
        // Show first 3 most informative keys; full set on hover.
        const PRIORITY = ["SetupMode","EnableLong","EnableShort","RewardRiskRatio",
                          "MinAdx","TradeStartTime","TradeEndTime","UserMaxContracts"];
        const ordered = [...new Set([...PRIORITY.filter(k=>k in p), ...keys])];
        const head = ordered.slice(0,3).map(k => `${k}=${p[k]}`).join(", ");
        const more = ordered.length > 3 ? ` (+${ordered.length-3})` : "";
        return { text: head + more, title: ordered.map(k=>`${k}=${p[k]}`).join("\n") };
      };
      const fmtTradesPnl = (sess) => {
        const tc = sess.trades_count != null ? sess.trades_count
                 : sess.trade_count != null ? sess.trade_count : null;
        const pnl = sess.gross_pnl != null ? sess.gross_pnl
                  : sess.net_profit != null ? sess.net_profit : null;
        if (tc == null && pnl == null) return "—";
        const tcStr = tc != null ? String(tc) : "—";
        const pnlStr = pnl != null
          ? (pnl >= 0 ? "+" : "") + Number(pnl).toFixed(2)
          : "—";
        return `${tcStr} / ${pnlStr}`;
      };
      for (const sess of sessions) {
        const tr = document.createElement("tr");
        const params = fmtParams(sess);
        const cells = [
          { text: sess.strategy_name || sess.strategy_class || sess.class_name || sess.strategy_id || "—" },
          { text: sess.instrument || "—" },
          { text: sess.account_name || "—" },
          { text: fmtPT(sess.started_at_utc) },
          { text: fmtPT(sess.stopped_at_utc || sess.ended_at_utc) },
          { text: fmtDur(sess.duration_sec) },
          (typeof params === "string" ? { text: params } : params),
          { text: fmtTradesPnl(sess) },
        ];
        cells.forEach(c => {
          const td = document.createElement("td");
          td.textContent = c.text;
          if (c.title) td.title = c.title;
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      }
    } catch(e) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="8" class="muted-empty">Ошибка: ${escapeHtml(e.message)}</td></tr>`;
    }
  }

  // Wire up history button
  const btnHistory = document.getElementById("btn-trading-history");
  const histPanel  = document.getElementById("trading-history-panel");
  if (btnHistory && histPanel) {
    btnHistory.addEventListener("click", () => {
      const visible = !histPanel.hidden;
      histPanel.hidden = visible;
      btnHistory.textContent = visible ? "📋 История стратегий" : "📋 Скрыть историю";
      if (!visible) loadTradingHistory();
    });
  }
  const btnHistRefresh = document.getElementById("btn-history-refresh");
  if (btnHistRefresh) btnHistRefresh.addEventListener("click", loadTradingHistory);
})();
