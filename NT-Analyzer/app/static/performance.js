"use strict";

(() => {
  const ALL_ACCOUNTS = "__all__";
  const SORT_STORAGE_KEY = "nta.performance.sorts.v1";
  const CURVE_STORAGE_KEY = "nta.performance.curves.v1";
  const CURVE_PALETTE = [
    "#58d889", "#5b9cf5", "#f0b429", "#ff8585", "#c77dff",
    "#45c7b8", "#f97316", "#e879f9", "#38bdf8", "#a3e635",
    "#fb7185", "#facc15", "#2dd4bf", "#818cf8", "#c084fc",
    "#f472b6", "#84cc16", "#60a5fa", "#f59e0b", "#34d399",
  ];
  const $ = (id) => document.getElementById(id);

  function loadStoredSorts() {
    try {
      if (!window.localStorage) return {};
      const raw = JSON.parse(window.localStorage.getItem(SORT_STORAGE_KEY) || "{}");
      return raw && typeof raw === "object" ? raw : {};
    } catch (_) {
      return {};
    }
  }

  function loadStoredCurveVisibility() {
    try {
      if (!window.localStorage) return {};
      const raw = JSON.parse(window.localStorage.getItem(CURVE_STORAGE_KEY) || "{}");
      return raw && typeof raw === "object" ? raw : {};
    } catch (_) {
      return {};
    }
  }

  const STORED_SORTS = loadStoredSorts();
  const STORED_CURVE_VISIBILITY = loadStoredCurveVisibility();

  const STATE = {
    period: "month",
    from: "",
    to: "",
    account: ALL_ACCOUNTS,
    data: null,
    profiles: [],
    strategiesSort: STORED_SORTS.strategies || { col: "pnl", dir: "desc" },
    instrumentsSort: STORED_SORTS.instruments || { col: "pnl", dir: "desc" },
    selectedStrategyKey: null,
    selectedInstrument: null,
    curveVisible: STORED_CURVE_VISIBILITY,
    focusedCurveKey: null,
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  async function getJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function ptDateKey(d = new Date()) {
    try {
      return new Intl.DateTimeFormat("sv-SE", {
        timeZone: "America/Los_Angeles",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(d);
    } catch (_) {
      return d.toISOString().slice(0, 10);
    }
  }

  function num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function valueClass(value) {
    const n = num(value);
    if (n == null || Math.abs(n) < 1e-9) return "zero";
    return n > 0 ? "pos" : "neg";
  }

  function fmtMoney(value) {
    const n = num(value);
    if (n == null) return "—";
    if (Math.abs(n) < 0.005) return "$0.00";
    return (n > 0 ? "+$" : "-$") + Math.abs(n).toFixed(2);
  }

  function fmtCommission(value) {
    const n = num(value);
    if (n == null) return "—";
    if (Math.abs(n) < 0.005) return "$0.00";
    return "-$" + Math.abs(n).toFixed(2);
  }

  function fmtWin(value, trades) {
    const n = num(value);
    if (!trades || n == null) return "—";
    return (Math.abs(n - Math.round(n)) < 0.05 ? Math.round(n) : n.toFixed(1)) + "%";
  }

  function fmtSignedPct(value) {
    const n = num(value);
    if (n == null) return "—";
    const text = Math.abs(n - Math.round(n)) < 0.05 ? String(Math.round(Math.abs(n))) : Math.abs(n).toFixed(1);
    if (Math.abs(n) < 0.05) return "0%";
    return (n > 0 ? "+" : "-") + text + "%";
  }

  function fmtPf(row) {
    if (!row || row.profit_factor_kind === "none") return "—";
    if (row.profit_factor_kind === "infinite") return "∞";
    return fmtSignedPct(row.profit_factor_pct);
  }

  function shortDate(value) {
    if (!value) return "—";
    const parts = String(value).split("-");
    if (parts.length !== 3) return String(value);
    return `${parts[2]}.${parts[1]}`;
  }

  function setChip(id, text, kind) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.classList.remove("ok", "bad", "warn");
    if (kind) el.classList.add(kind);
  }

  function setMoney(id, value) {
    const el = $(id);
    if (!el) return;
    el.textContent = fmtMoney(value);
    el.classList.remove("pos", "neg", "zero");
    el.classList.add(valueClass(value));
  }

  function setText(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  async function loadAccounts() {
    let rows = [];
    try {
      const doc = await getJson("/api/ops/runtime/accounts");
      rows = (doc.online_accounts || doc.accounts || []).filter((r) => r && r.account_name);
    } catch (_) {
      rows = [];
    }

    let saved = "";
    try { saved = window.localStorage ? (window.localStorage.getItem("nta.performance.account") || "") : ""; }
    catch (_) { saved = ""; }
    const names = rows.map((r) => String(r.account_name || ""));
    STATE.account = names.includes(saved) ? saved : (names[0] || ALL_ACCOUNTS);

    const select = $("pc-account");
    if (!select) return;
    const options = [`<option value="${ALL_ACCOUNTS}">Все счета</option>`].concat(rows.map((r) => {
      const mode = r.account_mode ? ` · ${r.account_mode}` : "";
      return `<option value="${escapeHtml(r.account_name)}">${escapeHtml(r.account_name + mode)}</option>`;
    }));
    select.innerHTML = options.join("");
    select.value = STATE.account;
  }

  function buildPerformanceUrl() {
    const qp = new URLSearchParams();
    qp.set("period", STATE.period);
    if (STATE.account && STATE.account !== ALL_ACCOUNTS) qp.set("account", STATE.account);
    if (STATE.period === "custom") {
      if (STATE.from) qp.set("from", STATE.from);
      if (STATE.to) qp.set("to", STATE.to);
    }
    return "/api/performance?" + qp.toString();
  }

  function buildTradesDownloadUrl() {
    const qp = new URLSearchParams();
    qp.set("period", STATE.period);
    if (STATE.account && STATE.account !== ALL_ACCOUNTS) qp.set("account", STATE.account);
    if (STATE.period === "custom") {
      if (STATE.from) qp.set("from", STATE.from);
      if (STATE.to) qp.set("to", STATE.to);
    }
    return "/api/performance/trades.csv?" + qp.toString();
  }

  function saveSorts() {
    try {
      if (!window.localStorage) return;
      window.localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify({
        strategies: STATE.strategiesSort,
        instruments: STATE.instrumentsSort,
      }));
    } catch (_) { /* ignore storage failures */ }
  }

  function saveCurveVisibility() {
    try {
      if (!window.localStorage) return;
      window.localStorage.setItem(CURVE_STORAGE_KEY, JSON.stringify(STATE.curveVisible || {}));
    } catch (_) { /* ignore storage failures */ }
  }

  async function loadPerformance() {
    setChip("pc-status", "Загрузка данных...", "warn");
    try {
      const [data, profilesDoc] = await Promise.all([
        getJson(buildPerformanceUrl()),
        getJson("/api/profiles").catch(() => ({ profiles: [] })),
      ]);
      STATE.data = data;
      STATE.profiles = Array.isArray(profilesDoc?.profiles) ? profilesDoc.profiles : [];
      render();
      setChip("pc-status", "Данные загружены", "ok");
    } catch (error) {
      setChip("pc-status", "Ошибка загрузки", "bad");
      const empty = $("pc-empty");
      if (empty) {
        empty.hidden = false;
        empty.textContent = "Не удалось загрузить Центр доходности: " + error.message;
      }
    }
  }

  function updatePeriodControls() {
    document.querySelectorAll(".performance-periods button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.period === STATE.period);
    });
    const manual = $("pc-manual-dates");
    if (manual) manual.hidden = STATE.period !== "custom";
  }

  function renderSummary(data) {
    const summary = data.summary || {};
    setMoney("pc-total-pnl", summary.pnl);
    const c = $("pc-total-commission");
    if (c) {
      c.textContent = fmtCommission(summary.commission);
      c.classList.remove("pos", "neg", "zero");
      c.classList.add((summary.commission || 0) > 0 ? "neg" : "zero");
    }
    setText("pc-total-win", fmtWin(summary.win_rate, summary.trades));
    setText("pc-total-pf", fmtPf(summary));
  }

  function sortRows(rows, sort) {
    const col = sort.col;
    const dir = sort.dir === "asc" ? 1 : -1;
    return rows.slice().sort((a, b) => {
      let av = a[col];
      let bv = b[col];
      if (col === "profit_factor_sort") {
        av = a.profit_factor_kind === "infinite" ? 1e9 : a.profit_factor_sort;
        bv = b.profit_factor_kind === "infinite" ? 1e9 : b.profit_factor_sort;
      }
      const an = num(av);
      const bn = num(bv);
      if (an != null || bn != null) {
        if (an == null) return 1;
        if (bn == null) return -1;
        if (an !== bn) return (an - bn) * dir;
      }
      return String(a.strategy || a.instrument || "").localeCompare(String(b.strategy || b.instrument || ""), "ru");
    });
  }

  function updateSortHeaderState() {
    document.querySelectorAll("th.sortable").forEach((th) => {
      const table = th.dataset.table;
      const sort = table === "instruments" ? STATE.instrumentsSort : STATE.strategiesSort;
      th.classList.toggle("active", th.dataset.sort === sort.col);
      th.dataset.dir = th.dataset.sort === sort.col ? sort.dir : "";
    });
  }

  function renderStrategiesTable(data) {
    const tbody = document.querySelector("#pc-strategies-table tbody");
    if (!tbody) return;
    const rows = sortRows(data.strategies || [], STATE.strategiesSort);
    setText("pc-strategies-count", `${rows.length} строк`);
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="performance-empty-cell">За выбранный период сделок нет.</td></tr>';
      $("pc-strategy-detail").hidden = true;
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr data-key="${escapeHtml(r.key)}">
        <td class="cell-no">${escapeHtml(r.cell || "—")}</td>
        <td>
          <div class="pc-main-name">${escapeHtml(r.strategy || "—")}</div>
          <div class="pc-sub-name">${escapeHtml(r.strategy_class || r.strategy_id || "")}</div>
        </td>
        <td>${escapeHtml(r.instrument || "—")}</td>
        <td class="num ${valueClass(r.pnl)}">${escapeHtml(fmtMoney(r.pnl))}</td>
        <td class="num neg">${escapeHtml(fmtCommission(r.commission))}</td>
        <td class="num">${escapeHtml(fmtWin(r.win_rate, r.trades))}</td>
        <td class="num">${escapeHtml(fmtPf(r))}</td>
      </tr>
    `).join("");
    tbody.querySelectorAll("tr[data-key]").forEach((tr) => {
      tr.classList.toggle("sel", tr.dataset.key === STATE.selectedStrategyKey);
      tr.addEventListener("click", () => {
        STATE.selectedStrategyKey = tr.dataset.key;
        renderStrategiesTable(STATE.data);
        renderStrategyDetail(findStrategy(STATE.selectedStrategyKey));
      });
    });
  }

  function renderInstrumentsTable(data) {
    const tbody = document.querySelector("#pc-instruments-table tbody");
    if (!tbody) return;
    const rows = sortRows(data.instruments || [], STATE.instrumentsSort);
    setText("pc-instruments-count", `${rows.length} строк`);
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="performance-empty-cell">За выбранный период сделок нет.</td></tr>';
      $("pc-instrument-detail").hidden = true;
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr data-instrument="${escapeHtml(r.instrument)}">
        <td><strong>${escapeHtml(r.instrument || "—")}</strong></td>
        <td class="num">${escapeHtml(r.strategy_count ?? 0)}</td>
        <td class="num ${valueClass(r.pnl)}">${escapeHtml(fmtMoney(r.pnl))}</td>
        <td class="num neg">${escapeHtml(fmtCommission(r.commission))}</td>
        <td class="num">${escapeHtml(fmtWin(r.win_rate, r.trades))}</td>
        <td class="num">${escapeHtml(fmtPf(r))}</td>
        <td>${escapeHtml(r.best_strategy || "—")}</td>
      </tr>
    `).join("");
    tbody.querySelectorAll("tr[data-instrument]").forEach((tr) => {
      tr.classList.toggle("sel", tr.dataset.instrument === STATE.selectedInstrument);
      tr.addEventListener("click", () => {
        STATE.selectedInstrument = tr.dataset.instrument;
        renderInstrumentsTable(STATE.data);
        renderInstrumentDetail(findInstrument(STATE.selectedInstrument));
      });
    });
  }

  function findStrategy(key) {
    return (STATE.data?.strategies || []).find((row) => String(row.key) === String(key)) || null;
  }

  function findInstrument(instrument) {
    return (STATE.data?.instruments || []).find((row) => String(row.instrument) === String(instrument)) || null;
  }

  function detailMetricGrid(row) {
    return `
      <div class="performance-detail-metrics">
        <div><span>Profit and Loss</span><strong class="${valueClass(row.pnl)}">${escapeHtml(fmtMoney(row.pnl))}</strong></div>
        <div><span>Комиссия</span><strong class="neg">${escapeHtml(fmtCommission(row.commission))}</strong></div>
        <div><span>Win Rate</span><strong>${escapeHtml(fmtWin(row.win_rate, row.trades))}</strong></div>
        <div><span>Profit Factor</span><strong>${escapeHtml(fmtPf(row))}</strong></div>
      </div>`;
  }

  function renderStrategyDetail(row) {
    const panel = $("pc-strategy-detail");
    if (!panel || !row) return;
    panel.hidden = false;
    setText("pc-strategy-detail-title", "ДЕТАЛИ СТРАТЕГИИ: " + (row.strategy_full || row.strategy || "—"));
    const windowText = row.trade_window_pt ? `${row.trade_window_pt} PT` : "—";
    $("pc-strategy-detail-body").innerHTML = `
      <div class="performance-detail-lines">
        <div>Инструмент: <b>${escapeHtml(row.instrument_full || row.instrument || "—")}</b> | Таймфрейм: <b>${escapeHtml(row.timeframe || "—")}</b> | Окно: <b>${escapeHtml(windowText)}</b></div>
        <div>Статус: <b>${escapeHtml(row.status || "нет данных")}</b></div>
      </div>
      ${detailMetricGrid(row)}
      <h4>График стратегии по дням</h4>
    `;
    drawDailyLineChart($("pc-strategy-detail-chart"), row.daily || []);
    renderLastTrades("pc-strategy-last-trades", row.last_trades || []);
    panel.scrollIntoView({ block: "nearest" });
  }

  function renderInstrumentDetail(row) {
    const panel = $("pc-instrument-detail");
    if (!panel || !row) return;
    panel.hidden = false;
    setText("pc-instrument-detail-title", "ДЕТАЛИ ИНСТРУМЕНТА: " + (row.instrument || "—"));
    $("pc-instrument-detail-body").innerHTML = `
      <div class="performance-detail-lines">
        <div>Инструмент: <b>${escapeHtml(row.instrument_full || row.instrument || "—")}</b></div>
        <div>Стратегий на инструменте: <b>${escapeHtml(row.strategy_count ?? 0)}</b></div>
      </div>
      ${detailMetricGrid(row)}
      <h4>График инструмента по дням</h4>
    `;
    drawDailyLineChart($("pc-instrument-detail-chart"), row.daily || []);
    renderInstrumentStrategies(row);
    panel.scrollIntoView({ block: "nearest" });
  }

  function renderLastTrades(containerId, trades) {
    const root = $(containerId);
    if (!root) return;
    if (!trades.length) {
      root.innerHTML = '<h4>Последние сделки</h4><div class="performance-empty-inline">Нет сделок.</div>';
      return;
    }
    root.innerHTML = `
      <h4>Последние сделки</h4>
      <table class="performance-mini-table">
        <thead><tr><th>Время</th><th>Действие</th><th>Инст</th><th class="num">P/L</th></tr></thead>
        <tbody>
          ${trades.map((t) => `
            <tr>
              <td>${escapeHtml(t.time_pt || "—")}</td>
              <td>${escapeHtml(t.action || "—")}</td>
              <td>${escapeHtml(t.instrument || "—")}</td>
              <td class="num ${valueClass(t.pnl)}">${escapeHtml(fmtMoney(t.pnl))}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;
  }

  function renderInstrumentStrategies(row) {
    const root = $("pc-instrument-strategies");
    if (!root) return;
    const rows = row.strategies || [];
    if (!rows.length) {
      root.innerHTML = '<h4>Стратегии, которые торговали инструмент</h4><div class="performance-empty-inline">Нет привязанных стратегий.</div>';
      return;
    }
    root.innerHTML = `
      <h4>Стратегии, которые торговали ${escapeHtml(row.instrument || "")}</h4>
      <table class="performance-mini-table">
        <thead><tr><th>Стратегия</th><th class="num">P/L</th></tr></thead>
        <tbody>
          ${rows.map((r) => `
            <tr>
              <td>${escapeHtml(r.strategy || "—")}</td>
              <td class="num ${valueClass(r.pnl)}">${escapeHtml(fmtMoney(r.pnl))}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>`;
  }

  function hashText(value) {
    let hash = 0;
    const text = String(value || "");
    for (let i = 0; i < text.length; i += 1) {
      hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
    }
    return Math.abs(hash);
  }

  function colorForStrategy(row, index) {
    const cellNumber = num(normalizeCellNumber(row?.cell || row?.cell_id));
    if (cellNumber != null) return CURVE_PALETTE[(Math.max(1, Math.floor(cellNumber)) - 1) % CURVE_PALETTE.length];
    return CURVE_PALETTE[hashText(row?.key || row?.strategy || index) % CURVE_PALETTE.length];
  }

  function normalizeCellNumber(value) {
    const match = String(value || "").trim().match(/(\d{1,3})/);
    return match ? match[1].padStart(3, "0") : "";
  }

  function curveCellLabel(row) {
    const cell = normalizeCellNumber(row?.cell || row?.cell_id);
    return cell ? `C${cell}` : "Без ячейки";
  }

  function cleanCurveLabel(value, row) {
    const cell = normalizeCellNumber(row?.cell || row?.cell_id);
    let text = String(value || "").trim();
    if (cell) {
      const numeric = String(Number(cell));
      text = text
        .replace(new RegExp(`^0*${numeric}\\s+`, "i"), "")
        .replace(new RegExp(`\\s+c0*${numeric}\\b`, "i"), "")
        .replace(new RegExp(`\\s+cell-?0*${numeric}\\b`, "i"), "");
    }
    return text.trim() || "—";
  }

  function stableCurveKey(row) {
    const cell = normalizeCellNumber(row?.cell || row?.cell_id);
    if (cell) return `cell:${cell}`;
    const strategy = String(row?.strategy || "").trim();
    if (!strategy || strategy === "Без привязки к стратегии") return "__unmapped__";
    return `strategy:${String(row?.strategy_id || row?.strategy_class || row?.runtime_instance_id || strategy || row?.key || "").trim()}`;
  }

  function compareCurveRows(a, b) {
    const ac = num(normalizeCellNumber(a?.cell || a?.cell_id));
    const bc = num(normalizeCellNumber(b?.cell || b?.cell_id));
    if (ac != null || bc != null) {
      if (ac == null) return -1;
      if (bc == null) return 1;
      if (ac !== bc) return ac - bc;
    }
    const an = String(a?.strategy || a?.strategy_class || a?.key || "");
    const bn = String(b?.strategy || b?.strategy_class || b?.key || "");
    return an.localeCompare(bn, "ru");
  }

  function toCumulativeCurve(rows) {
    let cumulative = 0;
    return (rows || []).map((row) => {
      cumulative += Number(row?.pnl || 0);
      return {
        date: row?.date || "",
        value: cumulative,
      };
    });
  }

  function parseYmdUtc(value) {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatYmdUtc(date) {
    return date.toISOString().slice(0, 10);
  }

  function emptyDailyForPeriod(data) {
    const start = parseYmdUtc(data?.period?.from);
    const end = parseYmdUtc(data?.period?.to);
    if (!start || !end || start > end) return [{ date: "", pnl: 0 }];
    const rows = [];
    const cur = new Date(start.getTime());
    for (let i = 0; i < 370 && cur <= end; i += 1) {
      rows.push({ date: formatYmdUtc(cur), pnl: 0 });
      cur.setUTCDate(cur.getUTCDate() + 1);
    }
    return rows.length ? rows : [{ date: "", pnl: 0 }];
  }

  function profileReadyForCurves(profile) {
    const status = String(profile?.status || "").trim();
    return !!normalizeCellNumber(profile?.cell_id) && (status === "ready" || status === "paper_ready");
  }

  function profileCurveRow(profile, data) {
    const cell = normalizeCellNumber(profile?.cell_id);
    const strategy = cleanCurveLabel(
      profile?.name ||
      profile?.expected_name ||
      profile?.runtime_strategy_id ||
      profile?.deploy_strategy_class ||
      profile?.strategy_class ||
      profile?.profile_id,
      { cell },
    );
    return {
      key: `cell:${cell}`,
      cell,
      strategy,
      strategy_full: profile?.name || strategy,
      strategy_class: profile?.deploy_strategy_class || profile?.strategy_class || "",
      strategy_id: profile?.runtime_strategy_id || profile?.profile_id || "",
      instrument: profile?.instrument || profile?.current_contract || "—",
      pnl: 0,
      daily: emptyDailyForPeriod(data),
      profile_only: true,
    };
  }

  function buildCurveRows(data) {
    const rows = (data?.strategies || []).map((row) => ({
      ...row,
      key: stableCurveKey(row),
      cell: normalizeCellNumber(row?.cell) || row?.cell || "",
      strategy: cleanCurveLabel(row?.strategy || row?.strategy_class || row?.strategy_id, row),
    }));
    const seenKeys = new Set(rows.map((row) => stableCurveKey(row)));
    const seenCells = new Set(rows.map((row) => normalizeCellNumber(row.cell)).filter(Boolean));
    (STATE.profiles || []).filter(profileReadyForCurves).forEach((profile) => {
      const cell = normalizeCellNumber(profile.cell_id);
      const key = `cell:${cell}`;
      if (!cell || seenKeys.has(key) || seenCells.has(cell)) return;
      rows.push(profileCurveRow(profile, data));
      seenKeys.add(key);
      seenCells.add(cell);
    });
    return rows.sort(compareCurveRows);
  }

  function buildCurveSeries(data) {
    return buildCurveRows(data).map((row, index) => {
      const key = String(row.key || stableCurveKey(row) || index);
      const points = toCumulativeCurve(row.daily || []);
      const fallbackPnl = num(row.pnl);
      if (!points.length && fallbackPnl != null) {
        points.push({ date: "", value: fallbackPnl });
      }
      return {
        key,
        cellLabel: curveCellLabel(row),
        label: cleanCurveLabel(row.strategy || row.strategy_class || row.strategy_id, row),
        total: fallbackPnl || 0,
        color: colorForStrategy(row, index),
        points,
      };
    });
  }

  function isCurveVisible(key) {
    return STATE.curveVisible[String(key)] !== false;
  }

  function updateCurveCount(series) {
    const total = (series || []).length;
    const visible = (series || []).filter((item) => isCurveVisible(item.key)).length;
    setText("pc-curves-count", total ? `${visible}/${total} линий` : "—");
  }

  function renderCurveLegend(series) {
    const root = $("pc-curves-legend");
    if (!root) return;
    updateCurveCount(series);
    if (!series.length) {
      root.innerHTML = '<div class="performance-empty-inline">Нет стратегий за выбранный период.</div>';
      return;
    }
    root.innerHTML = series.map((item) => `
      <label class="performance-curve-row${STATE.focusedCurveKey === item.key ? " focused" : ""}" data-key="${escapeHtml(item.key)}" style="--curve-color:${item.color}">
        <input type="checkbox" data-key="${escapeHtml(item.key)}"${isCurveVisible(item.key) ? " checked" : ""}>
        <span class="performance-curve-color"></span>
        <span class="performance-curve-text">
          <span class="performance-curve-cell">${escapeHtml(item.cellLabel)}</span>
          <span class="performance-curve-name">${escapeHtml(item.label)}</span>
        </span>
        <span class="performance-curve-pnl ${valueClass(item.total)}">${escapeHtml(fmtMoney(item.total))}</span>
      </label>
    `).join("");
    root.querySelectorAll("input[type='checkbox'][data-key]").forEach((input) => {
      input.addEventListener("change", () => {
        STATE.curveVisible[input.dataset.key] = input.checked;
        saveCurveVisibility();
        renderCharts(STATE.data);
      });
    });
    root.querySelectorAll(".performance-curve-row[data-key]").forEach((row) => {
      row.addEventListener("mouseenter", () => {
        STATE.focusedCurveKey = row.dataset.key;
        row.classList.add("focused");
        drawMultiEquityCurves($("pc-curves-chart"), buildCurveSeries(STATE.data));
      });
      row.addEventListener("mouseleave", () => {
        if (STATE.focusedCurveKey === row.dataset.key) STATE.focusedCurveKey = null;
        row.classList.remove("focused");
        drawMultiEquityCurves($("pc-curves-chart"), buildCurveSeries(STATE.data));
      });
    });
  }

  function prepareCanvas(canvas, fallbackHeight) {
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(320, Math.floor(rect.width || canvas.clientWidth || 320));
    const height = Math.max(120, Math.floor(rect.height || fallbackHeight || 240));
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { ctx, width, height };
  }

  function drawEmptyCanvas(canvas, text) {
    const c = prepareCanvas(canvas, 220);
    if (!c) return;
    c.ctx.fillStyle = "#7e8da5";
    c.ctx.font = "13px Segoe UI, sans-serif";
    c.ctx.textAlign = "center";
    c.ctx.fillText(text, c.width / 2, c.height / 2);
  }

  function drawHorizontalBars(canvas, rows, labelKey) {
    const c = prepareCanvas(canvas, 300);
    if (!c) return;
    const { ctx, width, height } = c;
    const data = (rows || []).filter((r) => num(r.pnl) != null).slice(0, 14);
    if (!data.length) {
      drawEmptyCanvas(canvas, "За выбранный период сделок нет.");
      return;
    }
    const maxAbs = Math.max(1, ...data.map((r) => Math.abs(Number(r.pnl || 0))));
    const labelW = Math.min(300, Math.max(120, width * 0.33));
    const valueW = 92;
    const top = 18;
    const bottom = data.length < (rows || []).length ? 30 : 14;
    const chartX = labelW + 12;
    const chartW = width - chartX - valueW - 16;
    const zeroX = chartX + chartW / 2;
    const rowH = Math.max(22, (height - top - bottom) / data.length);

    ctx.strokeStyle = "#2a3242";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(zeroX, top - 6);
    ctx.lineTo(zeroX, height - bottom + 4);
    ctx.stroke();

    data.forEach((row, i) => {
      const y = top + i * rowH + rowH * 0.22;
      const barH = Math.min(16, rowH * 0.55);
      const v = Number(row.pnl || 0);
      const barW = Math.abs(v) / maxAbs * (chartW / 2 - 8);
      const x = v >= 0 ? zeroX : zeroX - barW;
      const cls = valueClass(v);
      ctx.fillStyle = cls === "pos" ? "#48c978" : cls === "neg" ? "#e35b5b" : "#7f8794";
      ctx.fillRect(x, y, Math.max(1, barW), barH);

      ctx.fillStyle = "#d9e4f5";
      ctx.font = "12px Segoe UI, sans-serif";
      ctx.textAlign = "left";
      const label = String(row[labelKey] || "—");
      ctx.fillText(label.length > 34 ? label.slice(0, 33) + "…" : label, 10, y + barH - 2);

      ctx.fillStyle = cls === "pos" ? "#75e59b" : cls === "neg" ? "#ff8585" : "#a6afbd";
      let vx = v >= 0 ? zeroX + barW + 8 : zeroX - barW - 8;
      ctx.textAlign = v >= 0 ? "left" : "right";
      if (v >= 0 && vx > width - 78) {
        vx = width - 10;
        ctx.textAlign = "right";
      } else if (v < 0 && vx < chartX + 72) {
        vx = chartX + 8;
        ctx.textAlign = "left";
      }
      ctx.fillText(fmtMoney(v), vx, y + barH - 2);
    });

    if (data.length < (rows || []).length) {
      ctx.fillStyle = "#7e8da5";
      ctx.font = "11px Segoe UI, sans-serif";
      ctx.textAlign = "left";
      ctx.fillText(`Показаны первые ${data.length} строк из ${(rows || []).length}. Полный список ниже.`, 10, height - 10);
    }
  }

  function drawDailyLineChart(canvas, rows) {
    const c = prepareCanvas(canvas, 210);
    if (!c) return;
    const { ctx, width, height } = c;
    const data = (rows || []).map((r) => ({ date: r.date, pnl: Number(r.pnl || 0) }));
    if (!data.length) {
      drawEmptyCanvas(canvas, "Нет данных по дням.");
      return;
    }
    const padL = 54;
    const padR = 16;
    const padT = 18;
    const padB = 34;
    const innerW = width - padL - padR;
    const innerH = height - padT - padB;
    const values = data.map((r) => r.pnl);
    const min = Math.min(0, ...values);
    const max = Math.max(0, ...values);
    const span = max - min || 1;
    const x = (i) => padL + (data.length === 1 ? innerW / 2 : i * innerW / (data.length - 1));
    const y = (v) => padT + innerH - ((v - min) / span) * innerH;
    const zeroY = y(0);

    ctx.strokeStyle = "#263142";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, zeroY);
    ctx.lineTo(width - padR, zeroY);
    ctx.stroke();

    ctx.fillStyle = "#7e8da5";
    ctx.font = "11px Segoe UI, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(fmtMoney(max), padL - 8, y(max) + 4);
    if (min !== max) ctx.fillText(fmtMoney(min), padL - 8, y(min) + 4);

    ctx.beginPath();
    data.forEach((row, i) => {
      const px = x(i);
      const py = y(row.pnl);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    const last = data[data.length - 1].pnl;
    ctx.strokeStyle = last >= 0 ? "#58d889" : "#ef6b6b";
    ctx.lineWidth = 2;
    ctx.stroke();

    data.forEach((row, i) => {
      if (data.length > 40 && i % Math.ceil(data.length / 24) !== 0 && i !== data.length - 1) return;
      ctx.fillStyle = row.pnl > 0 ? "#58d889" : row.pnl < 0 ? "#ef6b6b" : "#8d97a8";
      ctx.beginPath();
      ctx.arc(x(i), y(row.pnl), 3, 0, Math.PI * 2);
      ctx.fill();
    });

    ctx.fillStyle = "#7e8da5";
    ctx.font = "11px Segoe UI, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(shortDate(data[0].date), padL, height - 12);
    ctx.textAlign = "right";
    ctx.fillText(shortDate(data[data.length - 1].date), width - padR, height - 12);
  }

  function drawMultiEquityCurves(canvas, series) {
    const c = prepareCanvas(canvas, 420);
    if (!c) return;
    const { ctx, width, height } = c;
    const rows = (series || []).filter((item) => (item.points || []).length);
    if (!rows.length) {
      drawEmptyCanvas(canvas, "Нет стратегий за выбранный период.");
      return;
    }
    const visible = rows.filter((item) => isCurveVisible(item.key));
    if (!visible.length) {
      drawEmptyCanvas(canvas, "Все линии скрыты.");
      return;
    }

    const padL = 66;
    const padR = 18;
    const padT = 22;
    const padB = 38;
    const innerW = Math.max(1, width - padL - padR);
    const innerH = Math.max(1, height - padT - padB);
    const longest = Math.max(1, ...visible.map((item) => item.points.length));

    let min = 0;
    let max = 0;
    visible.forEach((item) => {
      item.points.forEach((point) => {
        const value = Number(point.value || 0);
        min = Math.min(min, value);
        max = Math.max(max, value);
      });
    });
    if (min === max) {
      min -= 1;
      max += 1;
    } else {
      const pad = (max - min) * 0.08;
      min -= pad;
      max += pad;
    }
    const span = max - min || 1;
    const x = (i, length) => padL + (length <= 1 ? innerW / 2 : i * innerW / (length - 1));
    const y = (value) => padT + innerH - ((value - min) / span) * innerH;
    const zeroY = y(0);

    ctx.strokeStyle = "rgba(143,162,189,0.13)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const gy = padT + innerH * i / 4;
      ctx.beginPath();
      ctx.moveTo(padL, gy);
      ctx.lineTo(width - padR, gy);
      ctx.stroke();
    }
    for (let i = 0; i <= 4; i += 1) {
      const gx = padL + innerW * i / 4;
      ctx.beginPath();
      ctx.moveTo(gx, padT);
      ctx.lineTo(gx, padT + innerH);
      ctx.stroke();
    }

    ctx.strokeStyle = "#3b465c";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(padL, zeroY);
    ctx.lineTo(width - padR, zeroY);
    ctx.stroke();

    ctx.fillStyle = "#7e8da5";
    ctx.font = "11px Segoe UI, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(fmtMoney(max), padL - 8, y(max) + 4);
    ctx.fillText("$0.00", padL - 8, zeroY + 4);
    ctx.fillText(fmtMoney(min), padL - 8, y(min) + 4);

    visible.forEach((item) => {
      const focused = STATE.focusedCurveKey === item.key;
      const dimmed = STATE.focusedCurveKey && !focused;
      const points = item.points || [];
      ctx.save();
      ctx.beginPath();
      ctx.rect(padL, padT, innerW, innerH);
      ctx.clip();
      ctx.beginPath();
      points.forEach((point, i) => {
        const px = x(i, points.length);
        const py = y(Number(point.value || 0));
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.strokeStyle = item.color;
      ctx.lineWidth = focused ? 3 : 1.7;
      ctx.globalAlpha = dimmed ? 0.22 : 0.95;
      ctx.stroke();
      const last = points[points.length - 1];
      if (focused && last) {
        ctx.globalAlpha = 1;
        ctx.fillStyle = item.color;
        ctx.beginPath();
        ctx.arc(x(points.length - 1, points.length), y(Number(last.value || 0)), 4, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    });

    const firstSeries = visible.find((item) => item.points.length >= longest) || visible[0];
    const dates = firstSeries?.points || [];
    ctx.fillStyle = "#7e8da5";
    ctx.font = "11px Segoe UI, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(shortDate(dates[0]?.date), padL, height - 13);
    if (dates.length > 2) {
      const mid = Math.floor((dates.length - 1) / 2);
      ctx.textAlign = "center";
      ctx.fillText(shortDate(dates[mid]?.date), padL + innerW / 2, height - 13);
    }
    ctx.textAlign = "right";
    ctx.fillText(shortDate(dates[dates.length - 1]?.date), width - padR, height - 13);
  }

  function renderCharts(data) {
    if (!data) return;
    const strategyRows = sortRows(data.strategies || [], { col: "pnl", dir: "desc" });
    const instrumentRows = sortRows(data.instruments || [], { col: "pnl", dir: "desc" });
    const curveSeries = buildCurveSeries(data);
    renderCurveLegend(curveSeries);
    drawMultiEquityCurves($("pc-curves-chart"), curveSeries);
    drawHorizontalBars($("pc-strategies-chart"), strategyRows, "strategy");
    drawHorizontalBars($("pc-instruments-chart"), instrumentRows, "instrument");
    if (STATE.selectedStrategyKey) renderStrategyDetail(findStrategy(STATE.selectedStrategyKey));
    if (STATE.selectedInstrument) renderInstrumentDetail(findInstrument(STATE.selectedInstrument));
  }

  function render() {
    const data = STATE.data;
    if (!data) return;
    updatePeriodControls();
    renderSummary(data);
    renderStrategiesTable(data);
    renderInstrumentsTable(data);
    updateSortHeaderState();
    renderCharts(data);

    const empty = $("pc-empty");
    if (empty) {
      empty.hidden = !!data.has_trades;
      empty.textContent = data.empty_message || "За выбранный период сделок нет.";
    }
    const p = data.period || {};
    setText("pc-period-chip", `Период: ${p.label || "—"} · ${p.from || "—"} → ${p.to || "—"}`);
    setText("pc-updated", data.generated_at_utc ? data.generated_at_utc.replace("T", " ").slice(0, 19) + " UTC" : "—");
  }

  function bind() {
    document.querySelectorAll(".performance-periods button").forEach((btn) => {
      btn.addEventListener("click", () => {
        STATE.period = btn.dataset.period || "now";
        updatePeriodControls();
        loadPerformance();
      });
    });

    const today = ptDateKey();
    STATE.from = today;
    STATE.to = today;
    const from = $("pc-from-date");
    const to = $("pc-to-date");
    if (from) {
      from.value = today;
      from.addEventListener("change", () => {
        STATE.from = from.value;
        if (STATE.period === "custom") loadPerformance();
      });
    }
    if (to) {
      to.value = today;
      to.addEventListener("change", () => {
        STATE.to = to.value;
        if (STATE.period === "custom") loadPerformance();
      });
    }

    const account = $("pc-account");
    if (account) {
      account.addEventListener("change", () => {
        STATE.account = account.value || ALL_ACCOUNTS;
        try { if (window.localStorage) window.localStorage.setItem("nta.performance.account", STATE.account); }
        catch (_) { /* ignore storage failures */ }
        STATE.selectedStrategyKey = null;
        STATE.selectedInstrument = null;
        loadPerformance();
      });
    }

    const refresh = $("pc-refresh");
    if (refresh) refresh.addEventListener("click", loadPerformance);
    const download = $("pc-download-trades");
    if (download) {
      download.addEventListener("click", () => {
        window.location.href = buildTradesDownloadUrl();
      });
    }
    const curvesAllOn = $("pc-curves-all-on");
    if (curvesAllOn) {
      curvesAllOn.addEventListener("click", () => {
        if (!STATE.data) return;
        buildCurveSeries(STATE.data).forEach((item) => { STATE.curveVisible[item.key] = true; });
        saveCurveVisibility();
        renderCharts(STATE.data);
      });
    }
    const curvesAllOff = $("pc-curves-all-off");
    if (curvesAllOff) {
      curvesAllOff.addEventListener("click", () => {
        if (!STATE.data) return;
        buildCurveSeries(STATE.data).forEach((item) => { STATE.curveVisible[item.key] = false; });
        saveCurveVisibility();
        renderCharts(STATE.data);
      });
    }

    document.querySelectorAll("th.sortable").forEach((th) => {
      th.addEventListener("click", () => {
        const table = th.dataset.table;
        const sort = table === "instruments" ? STATE.instrumentsSort : STATE.strategiesSort;
        const col = th.dataset.sort;
        if (sort.col === col) sort.dir = sort.dir === "desc" ? "asc" : "desc";
        else {
          sort.col = col;
          sort.dir = "desc";
        }
        saveSorts();
        render();
      });
    });

    document.querySelectorAll(".pc-detail-close").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.dataset.detail === "strategy") {
          STATE.selectedStrategyKey = null;
          $("pc-strategy-detail").hidden = true;
          renderStrategiesTable(STATE.data);
        } else {
          STATE.selectedInstrument = null;
          $("pc-instrument-detail").hidden = true;
          renderInstrumentsTable(STATE.data);
        }
      });
    });

    window.addEventListener("resize", () => {
      if (STATE.data) renderCharts(STATE.data);
    });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    bind();
    updatePeriodControls();
    await loadAccounts();
    await loadPerformance();
  });

  // Expose chart functions for reuse by ai-strategy.js.
  // Helper resolves either a <canvas>, a container DOM element, or an element id.
  function _resolveCanvas(target, height) {
    if (!target) return null;
    let el = (typeof target === "string") ? document.getElementById(target) : target;
    if (!el) return null;
    if (el.tagName === "CANVAS") return el;
    let canvas = el.querySelector("canvas");
    if (!canvas) {
      canvas = document.createElement("canvas");
      canvas.style.width = "100%";
      canvas.style.height = (height || 220) + "px";
      el.appendChild(canvas);
    }
    return canvas;
  }

  window.drawDailyLineChart = function (target, rows) {
    const c = _resolveCanvas(target, 210);
    if (c) drawDailyLineChart(c, rows || []);
  };
  window.drawMultiEquityCurves = function (target, series) {
    const c = _resolveCanvas(target, 240);
    if (c) drawMultiEquityCurves(c, series || []);
  };
  window.drawHorizontalBars = function (target, rows, labelKey) {
    const c = _resolveCanvas(target, 220);
    if (c) drawHorizontalBars(c, rows || [], labelKey || "label");
  };
  window.renderLastTrades = function (target, trades) {
    if (!target) return;
    if (typeof target === "string") return renderLastTrades(target, trades || []);
    // target is a DOM element — assign id if missing and delegate
    if (!target.id) target.id = "tmp-trades-" + Math.random().toString(36).slice(2);
    renderLastTrades(target.id, trades || []);
  };
})();
