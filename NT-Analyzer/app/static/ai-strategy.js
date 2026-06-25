(() => {
  "use strict";

  const DEBUG = new URLSearchParams(location.search).get("debug") === "1";

  const STATE = {
    summary: null,
    matrix: null,
    performance: null,
    portfolio: null,
    calendar: null,
    selectedExperimentId: localStorage.getItem("aiLab.selectedExperimentId") || null,
    experimentFilter: localStorage.getItem("aiLab.experimentFilter") || "all",
    activityNextLine: 0,
    activityTimer: null,
    busyTimer: null,
    refreshTimer: null,
    sourceStatusTimer: null,
    compileBaselineUtc: null,
    lastScrollAt: 0,
    restoringScroll: false,
    lastByRole: {},
    btLoadedForJob: null,
    renderKeys: {},
    detailCache: {},
    runActive: false,
  };

  let _lmReadinessTimer = null;
  let _lmReadinessPromise = null;

  const TERMINAL_STATUSES = new Set([
    "validation_failed", "compile_failed", "compile_failed_after_fix_loop",
    "awaiting_compile_timeout", "blocked_by_real_environment_issue",
    "blocked_lm_studio", "backtest_failed", "pipeline_failed",
    "rejected", "mutation_candidate", "sandbox_candidate",
    "champion_candidate", "human_review_candidate", "portfolio_contributor",
    "archived", "cancelled",
  ]);

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const PERFORMANCE_COLUMNS = [
    { key: "ai_cell_id", label: "AI-CELL", text: true },
    { key: "class_name", label: "Class", text: true },
    { key: "target_root", label: "Root", text: true },
    { key: "family", label: "Family", text: true },
    { key: "status", label: "Status", text: true },
    { key: "compile_status", label: "Compile", text: true },
    { key: "backtest_status", label: "Backtest", text: true },
    { key: "trade_count", label: "Trades" },
    { key: "verdict", label: "Verdict", text: true },
    { key: "model_roles_used", label: "Models", text: true },
    { key: "job_id", label: "Job", text: true },
    { key: "report_path", label: "Report", text: true, format: row => row.report_path ? "report" : "—" },
    { key: "source_code_link", label: "Source", text: true, format: row => row.source_code_link ? "source" : "—" },
    { key: "pf_after_commission", label: "PF After Comm" },
    { key: "dd_after_commission", label: "DD After Comm" },
    { key: "ai_arbitration_score", label: "AI Score" },
    { key: "experiment_id", label: "Experiment ID", text: true },
  ];

  const HISTORY_FILTERS = [
    ["all", "All experiments"],
    ["draft", "Draft"],
    ["compile_failed", "Compile failed"],
    ["backtest_done", "Backtest done"],
    ["rejected", "Rejected"],
    ["candidate", "Candidate"],
    ["approved", "Approved"],
    ["blocked", "Blocked"],
    ["zero_trades", "0 trades"],
  ];

  function fmt(v, opts = {}) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "boolean") return v ? "yes" : "no";
    if (typeof v === "number") {
      if (Number.isNaN(v)) return "—";
      if (opts.pct) return v.toFixed(2) + "%";
      if (Math.abs(v) >= 1000) return v.toFixed(0);
      return v.toFixed(2);
    }
    return String(v);
  }

  async function fetchJson(url, init = {}) {
    const r = await fetch(url, init);
    if (!r.ok) throw new Error(`${url} -> HTTP ${r.status}`);
    return r.json();
  }

  function stableKey(value) {
    try {
      return JSON.stringify(value);
    } catch (_) {
      return String(Date.now());
    }
  }

  function renderIfChanged(key, data, renderFn, force = false) {
    const next = stableKey(data);
    if (!force && STATE.renderKeys[key] === next) return;
    STATE.renderKeys[key] = next;
    renderFn();
  }

  function persistSelection() {
    if (STATE.selectedExperimentId) {
      localStorage.setItem("aiLab.selectedExperimentId", STATE.selectedExperimentId);
    } else {
      localStorage.removeItem("aiLab.selectedExperimentId");
    }
  }

  function restoreScroll(x, y) {
    const restore = () => {
      STATE.restoringScroll = true;
      window.scrollTo({ left: x || 0, top: y || 0, behavior: "auto" });
      setTimeout(() => { STATE.restoringScroll = false; }, 120);
    };
    requestAnimationFrame(restore);
    setTimeout(restore, 50);
    setTimeout(restore, 250);
    setTimeout(restore, 750);
  }

  async function refreshAll(options = {}) {
    const background = options.background === true;
    const preserveScroll = background || options.preserveScroll === true;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const scrollStamp = STATE.lastScrollAt;
    const selectedBefore = STATE.selectedExperimentId;
    const [summary, matrix, perf, portfolio, calendar] = await Promise.all([
      fetchJson("/api/ai-lab/summary").catch(e => ({ error: String(e) })),
      fetchJson("/api/ai-lab/matrix").catch(e => ({ error: String(e), rows: [] })),
      fetchJson("/api/ai-lab/performance").catch(e => ({ error: String(e), rows: [] })),
      fetchJson("/api/ai-lab/portfolio").catch(e => ({ error: String(e), rows: [] })),
      fetchJson("/api/ai-lab/calendar").catch(e => ({ error: String(e), by_relative_month: [] })),
    ]);
    const previousLm = STATE.summary?.lm_studio || null;
    const incomingLm = summary?.lm_studio || null;
    if (
      previousLm?.run_allowed === true
      && incomingLm
      && (incomingLm.probe_pending === true || incomingLm.status === "pending_check")
    ) {
      // /summary intentionally does not run a blocking chat probe. When its
      // cache expires it reports pending_check; do not erase a previously
      // successful readiness result while a background refresh is pending.
      summary.lm_studio = { ...incomingLm, ...previousLm };
    }
    STATE.summary = summary;
    STATE.matrix = matrix;
    STATE.performance = perf;
    STATE.portfolio = portfolio;
    STATE.calendar = calendar;
    renderSummary();
    renderFilters();
    renderIfChanged("matrix", matrix, renderMatrix, options.force);
    renderIfChanged("portfolio", portfolio, renderPortfolio, options.force);
    renderIfChanged(`performance:${STATE.experimentFilter}`, perf, renderPerformance, options.force);
    renderIfChanged("calendar", calendar, renderCalendar, options.force);

    STATE.selectedExperimentId = selectedBefore;
    persistSelection();
    markSelectedRows();

    if (!background && STATE.selectedExperimentId && options.reloadDetail !== false) {
      await loadDetail(STATE.selectedExperimentId, { preserveActivity: true, preserveScroll: true, force: true });
    }
    if (preserveScroll && STATE.lastScrollAt === scrollStamp) restoreScroll(scrollX, scrollY);
    queueLmReadinessRefresh();
  }

  function lmRunBypassAllowed() {
    return DEBUG && !!$("#ai-allow-template-fallback")?.checked;
  }

  function renderLmGate() {
    const lm = STATE.summary?.lm_studio || {};
    const lmChip = $("#ai-lm-chip");
    const runBtn = $("#ai-run-btn");
    const runSubmit = $("#ai-run-submit");
    const banner = $("#ai-lm-gate-banner");
    const bypass = lmRunBypassAllowed();
    const runAllowed = bypass || lm.run_allowed === true;
    const probing = lm.probe_pending === true || lm.status === "pending_check";

    let chipText = "LM Studio: …";
    let chipClass = "bad";

    if (!lm.available) {
      chipText = "LM Studio: недоступна";
    } else if (lm.ready === true) {
      chipText = `LM Studio: готово (${(lm.models || []).length} моделей)`;
      chipClass = "ok";
    } else if (probing) {
      chipText = "LM Studio: проверка моделей…";
      chipClass = "warn";
    } else if (lm.status === "models_not_loaded") {
      chipText = "LM Studio: загрузите AI-модели";
      chipClass = "warn";
    } else if (lm.status === "models_not_listed") {
      chipText = "LM Studio: нет моделей в списке";
      chipClass = "warn";
    } else {
      chipText = `LM Studio: ${lm.models?.length || 0} моделей (не готово)`;
      chipClass = "warn";
    }

    if (lmChip) {
      lmChip.textContent = chipText;
      lmChip.classList.remove("ok", "warn", "bad");
      lmChip.classList.add(chipClass);
      lmChip.title = lm.message_ru || chipText;
    }

    if (banner) {
      banner.classList.remove("is-probing", "is-ready", "is-debug");
      if (bypass) {
        banner.hidden = false;
        banner.textContent = "Debug: запуск без LLM (шаблон), очередь исследований не использует AI.";
        banner.classList.add("is-debug");
      } else if (!runAllowed) {
        banner.hidden = false;
        banner.textContent = lm.message_ru || "Подождите включения AI-моделей. Очередь не создаётся.";
        if (probing) banner.classList.add("is-probing");
      } else {
        banner.hidden = true;
        banner.textContent = "";
        banner.classList.add("is-ready");
      }
    }

    const disableRun = STATE.runActive || !runAllowed;
    const title = STATE.runActive
      ? "Исследовательский цикл уже выполняется"
      : (disableRun ? (lm.message_ru || "AI-модели не готовы") : "");
    if (runBtn) {
      runBtn.disabled = disableRun;
      if (disableRun) runBtn.title = title;
      else runBtn.removeAttribute("title");
    }
    if (runSubmit) {
      runSubmit.disabled = disableRun;
      if (disableRun) runSubmit.title = title;
      else runSubmit.removeAttribute("title");
    }
  }

  function scheduleLmReadinessPoll() {
    if (_lmReadinessTimer) return;
    const lm = STATE.summary?.lm_studio || {};
    const ttlMs = Math.max(15, Number(lm.preflight_cache_ttl_sec) || 60) * 1000;
    const delay = lm.run_allowed ? ttlMs : Math.min(15000, ttlMs);
    _lmReadinessTimer = setTimeout(() => {
      _lmReadinessTimer = null;
      refreshLmReadiness({ force: !lm.run_allowed }).catch(() => {});
    }, delay);
  }

  function queueLmReadinessRefresh() {
    const lm = STATE.summary?.lm_studio;
    if (!lm) return;
    if (STATE.runActive) {
      renderLmGate();
      return;
    }
    if (lm.probe_pending || lm.status === "pending_check" || !lm.run_allowed) {
      refreshLmReadiness().catch(e => console.error("refreshLmReadiness", e));
    } else {
      renderLmGate();
      scheduleLmReadinessPoll();
    }
  }

  async function refreshLmReadiness(options = {}) {
    if (STATE.runActive) return STATE.summary?.lm_studio || {};
    if (_lmReadinessPromise) return _lmReadinessPromise;
    const force = options.force === true;
    const url = `/api/ai-lab/lm-studio/readiness${force ? "?force=1" : ""}`;
    _lmReadinessPromise = (async () => {
      const data = await fetchJson(url);
      STATE.summary = {
        ...(STATE.summary || {}),
        lm_studio: { ...(STATE.summary?.lm_studio || {}), ...data },
      };
      renderLmGate();
      scheduleLmReadinessPoll();
      return data;
    })();
    try {
      return await _lmReadinessPromise;
    } finally {
      _lmReadinessPromise = null;
    }
  }

  function renderSummary() {
    const s = STATE.summary || {};
    const totals = s.totals || {};
    $("#ai-stat-experiments").textContent = totals.experiments ?? "0";
    $("#ai-stat-running").textContent = totals.running_jobs ?? "0";
    $("#ai-stat-candidates").textContent = totals.candidates ?? "0";
    $("#ai-stat-champions").textContent = totals.champions ?? "0";
    $("#ai-stat-compile-fail").textContent = totals.compile_failures ?? "0";
    $("#ai-stat-rejects").textContent = totals.rejects ?? "0";
    const portfolioStat = $("#ai-stat-portfolio");
    if (portfolioStat) portfolioStat.textContent = totals.portfolio_members ?? "0";

    renderLmGate();

    $("#ai-totals-chip").textContent = `Эксперименты: ${totals.experiments ?? 0}`;
    const ur = s.user_research || {};
    $("#ai-research-chip").textContent = `User research: ${ur.files ?? 0} файлов`;
  }

  function renderFilters() {
    const wrap = $("#ai-history-filters");
    if (!wrap) return;
    wrap.innerHTML = HISTORY_FILTERS.map(([key, label]) => `
      <button type="button" class="ai-filter-btn ${STATE.experimentFilter === key ? "active" : ""}"
        data-filter="${escape(key)}">${escape(label)}</button>
    `).join("");
    $$("#ai-history-filters .ai-filter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const next = btn.getAttribute("data-filter") || "all";
        STATE.experimentFilter = next;
        localStorage.setItem("aiLab.experimentFilter", next);
        renderFilters();
        renderPerformance();
        markSelectedRows();
      });
    });
  }

  function statusToken(value) {
    return String(value || "unknown").replace(/[^a-zA-Z0-9_-]/g, "-");
  }

  function rowFilterStatus(row) {
    return row.history_status || row.status || "draft";
  }

  function matchesHistoryFilter(row) {
    const f = STATE.experimentFilter || "all";
    const st = row.status || "";
    const hist = rowFilterStatus(row);
    const portfolioStatus = row.portfolio_status || "";
    if (f === "all") return true;
    if (f === "candidate") return st.endsWith("_candidate") || portfolioStatus === "candidate";
    if (f === "approved") return row.is_portfolio_member && ["approved", "promoted", "paper_ready"].includes(portfolioStatus);
    if (f === "blocked") {
      return ["awaiting_compile_timeout", "backtest_failed", "validation_failed", "cancelled", "archived"].includes(st)
        || String(st).includes("blocked");
    }
    if (f === "zero_trades") return hist === "zero_trades" || Number(row.trade_count) === 0;
    return st === f || hist === f;
  }

  function filteredPerformanceRows() {
    const rows = (STATE.performance && STATE.performance.rows) || [];
    return rows.filter(matchesHistoryFilter);
  }

  function detailRowFor(experimentId) {
    const fromPerf = ((STATE.performance && STATE.performance.rows) || [])
      .find(r => r.experiment_id === experimentId);
    if (fromPerf) return fromPerf;
    return ((STATE.portfolio && STATE.portfolio.rows) || [])
      .find(r => r.experiment_id === experimentId) || {};
  }

  function markSelectedRows() {
    const selected = STATE.selectedExperimentId || "";
    $$("[data-experiment-id]").forEach(el => {
      el.classList.toggle("selected", !!selected && el.getAttribute("data-experiment-id") === selected);
    });
  }

  function selectExperiment(experimentId) {
    if (!experimentId) return;
    loadDetail(experimentId).catch(e => console.error(e));
  }

  function renderMatrix() {
    const wrap = $("#ai-matrix-wrap");
    const m = STATE.matrix;
    if (!m || !m.rows || !m.rows.length) {
      wrap.innerHTML = `<div class="ai-empty">Матрица пуста.</div>`;
      return;
    }
    const lanes = m.lanes || 15;
    let html = `<table class="ai-matrix-table"><thead><tr><th>Root \\ Lane</th>`;
    for (let i = 1; i <= lanes; i++) html += `<th>${i}</th>`;
    html += `</tr></thead><tbody>`;
    for (const row of m.rows) {
      html += `<tr><th>${escape(row.root)}</th>`;
      for (const c of row.cells) {
        const status = c.history_status || c.status || "empty";
        const score = c.score !== null && c.score !== undefined ? c.score.toFixed(1) : "";
        const cls = c.class_name ? c.class_name.slice(-12) : "";
        if (status === "empty") {
          html += `<td class="empty">·</td>`;
        } else {
          const selected = c.experiment_id && c.experiment_id === STATE.selectedExperimentId ? " selected" : "";
          const portfolio = c.is_portfolio_member ? " portfolio-member" : "";
          html += `<td class="${statusToken(status)} ai-matrix-cell${selected}${portfolio}" data-experiment-id="${escape(c.experiment_id || "")}" title="${escape(c.ai_cell_id || "")} ${escape(c.class_name || "")}">
            <span class="score">${score || status.slice(0, 4)}</span>
            <span class="class">${escape(cls)}</span>
            ${c.is_portfolio_member ? "<span class=\"portfolio-dot\">P</span>" : ""}
          </td>`;
        }
      }
      html += `</tr>`;
    }
    html += `</tbody></table>`;
    wrap.innerHTML = html;
    $$("#ai-matrix-wrap .ai-matrix-cell").forEach(td => {
      td.addEventListener("click", () => {
        const id = td.getAttribute("data-experiment-id");
        if (id) selectExperiment(id);
      });
    });
    markSelectedRows();
  }

  function renderTableCell(row, col) {
    const raw = col.format ? col.format(row) : row[col.key];
    const title = col.key === "report_path" ? row.report_path
      : col.key === "source_code_link" ? row.source_code_link
      : col.key === "model_roles_used" ? row.model_roles_used
      : "";
    const val = col.text ? escape(raw == null ? "" : String(raw)) : escape(fmt(raw, { pct: col.pct }));
    const cls = col.text ? "text" : "";
    return `<td class="${cls}" ${title ? `title="${escape(title)}"` : ""}>${val}</td>`;
  }

  function rowPills(row) {
    const pills = [];
    if (row.compile_status) pills.push(["compile", row.compile_status]);
    if (row.backtest_status) pills.push(["backtest", row.backtest_status]);
    if (row.history_status === "zero_trades" || Number(row.trade_count) === 0) pills.push(["zero", "0 trades"]);
    if (row.verdict) pills.push(["verdict", row.verdict]);
    if (row.is_portfolio_member) pills.push(["portfolio", row.portfolio_status || "portfolio"]);
    return pills.map(([k, v]) => `<span class="ai-mini-pill ${statusToken(k)}">${escape(v)}</span>`).join("");
  }

  function renderPortfolio() {
    const wrap = $("#ai-portfolio-wrap");
    if (!wrap) return;
    const rows = (STATE.portfolio && STATE.portfolio.rows) || [];
    if (!rows.length) {
      wrap.innerHTML = `<div class="ai-empty">Portfolio пуст. Rejected, blocked, compile_failed и 0-trades остаются только в Experiment History.</div>`;
      return;
    }
    let html = `<table class="ai-performance-table ai-portfolio-table"><thead><tr>
      <th>AI-CELL</th><th>Class</th><th>Status</th><th>Portfolio</th><th>Trades</th><th>Verdict</th><th>Score</th><th>Job</th><th>Experiment</th>
    </tr></thead><tbody>`;
    for (const row of rows) {
      const selected = row.experiment_id === STATE.selectedExperimentId ? " selected" : "";
      html += `<tr class="row-link${selected}" data-experiment-id="${escape(row.experiment_id || "")}">
        <td class="text">${escape(row.ai_cell_id || "")}</td>
        <td class="text">${escape(row.class_name || "")}</td>
        <td class="text">${escape(row.status || "")}</td>
        <td class="text">${escape(row.portfolio_status || "")}</td>
        <td>${escape(fmt(row.trade_count))}</td>
        <td class="text">${escape(row.verdict || "")}</td>
        <td>${escape(fmt(row.ai_arbitration_score))}</td>
        <td class="text">${escape(row.job_id || "")}</td>
        <td class="text">${escape(row.experiment_id || "")}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    wrap.innerHTML = html;
    $$("#ai-portfolio-wrap .row-link").forEach(tr => {
      tr.addEventListener("click", () => selectExperiment(tr.getAttribute("data-experiment-id")));
    });
    markSelectedRows();
  }

  function renderPerformance() {
    const wrap = $("#ai-performance-wrap");
    const p = STATE.performance;
    const rows = filteredPerformanceRows();
    if (!p || !p.rows || !p.rows.length) {
      wrap.innerHTML = `<div class="ai-empty">Experiment History пуста.</div>`;
      return;
    }
    if (!rows.length) {
      wrap.innerHTML = `<div class="ai-empty">Нет экспериментов для фильтра ${escape(STATE.experimentFilter)}.</div>`;
      return;
    }
    let html = `<table class="ai-performance-table"><thead><tr>`;
    html += `<th>Flags</th>`;
    for (const col of PERFORMANCE_COLUMNS) html += `<th>${escape(col.label)}</th>`;
    html += `</tr></thead><tbody>`;
    for (const row of rows) {
      const selected = row.experiment_id === STATE.selectedExperimentId ? " selected" : "";
      html += `<tr class="row-link ${statusToken(rowFilterStatus(row))}${selected}" data-experiment-id="${escape(row.experiment_id || "")}">`;
      html += `<td class="text flags">${rowPills(row)}</td>`;
      for (const col of PERFORMANCE_COLUMNS) html += renderTableCell(row, col);
      html += `</tr>`;
    }
    html += `</tbody></table>`;
    wrap.innerHTML = html;
    $$("#ai-performance-wrap .row-link").forEach(tr => {
      tr.addEventListener("click", () => selectExperiment(tr.getAttribute("data-experiment-id")));
    });
    markSelectedRows();
  }

  function renderCalendar() {
    const wrap = $("#ai-calendar-wrap");
    const c = STATE.calendar;
    if (!c || !c.by_relative_month || !c.by_relative_month.length) {
      wrap.innerHTML = `<div class="ai-empty">Нет данных для AI Research Calendar.</div>`;
      return;
    }
    let html = `<div class="ai-calendar-grid">`;
    for (const cell of c.by_relative_month) {
      const v = Number(cell.ai_total_pnl || 0);
      const cls = v > 0 ? "pos" : v < 0 ? "neg" : "";
      html += `<div class="ai-calendar-cell ${cls}">
        <div class="month-label">${escape(cell.month)}</div>
        <span class="pnl ${cls}">${fmt(v)}</span>
      </div>`;
    }
    html += `</div>`;
    wrap.innerHTML = html;
  }

  async function loadDetail(experimentId, options = {}) {
    const sameSelection = STATE.selectedExperimentId === experimentId;
    const preserveActivity = sameSelection && options.preserveActivity === true;
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const scrollStamp = STATE.lastScrollAt;
    STATE.selectedExperimentId = experimentId;
    persistSelection();
    markSelectedRows();
    if (!preserveActivity) {
      STATE.activityNextLine = 0;
      STATE.lastByRole = {};
      STATE.btLoadedForJob = null;
      const logEl = $("#ai-process-log");
      if (logEl) logEl.innerHTML = "";
    }
    const wrap = $("#ai-detail");
    wrap.classList.remove("ai-detail-empty");
    if (!preserveActivity || options.force) {
      wrap.innerHTML = `<div class="ai-empty">Загрузка ${escape(experimentId)}...</div>`;
    }
    // Show note/paste panels for the selected experiment
    const noteBox = $("#ai-operator-notes"); if (noteBox) noteBox.hidden = false;
    const pasteBox = $("#ai-paste-errors"); if (pasteBox) pasteBox.hidden = false;
    try {
      const [exp, hist] = await Promise.all([
        fetchJson(`/api/ai-lab/experiments/${encodeURIComponent(experimentId)}`),
        fetchJson(`/api/ai-lab/experiments/${encodeURIComponent(experimentId)}/history`).catch(() => ({ history: [] })),
      ]);
      STATE.detailCache[experimentId] = exp;
      wrap.innerHTML = renderDetail(exp, hist.history || [], detailRowFor(experimentId));
      bindDetailActions(exp);
      const cls = exp.class_name || "";
      const pc = $("#ai-paste-class"); if (pc) pc.value = cls;
      refreshNotesList(experimentId);
      if (!preserveActivity) startActivityPolling(experimentId);
      maybeLoadBacktest(exp);
      updateCancelBtn(exp);
      markSelectedRows();
    } catch (e) {
      wrap.innerHTML = `<div class="ai-empty">Ошибка: ${escape(String(e))}</div>`;
    }
    if (options.preserveScroll && STATE.lastScrollAt === scrollStamp) restoreScroll(scrollX, scrollY);
  }

  function updateCancelBtn(exp) {
    const btn = $("#ai-cancel-btn");
    if (!btn) return;
    const status = exp?.status || "";
    const running = status && !TERMINAL_STATUSES.has(status);
    btn.hidden = !running;
  }

  function startActivityPolling(experimentId) {
    if (STATE.activityTimer) { clearInterval(STATE.activityTimer); STATE.activityTimer = null; }
    const tick = async () => {
      if (STATE.selectedExperimentId !== experimentId) return;
      try {
        const data = await fetchJson(
          `/api/ai-lab/experiments/${encodeURIComponent(experimentId)}/activity?since=${STATE.activityNextLine}`
        );
        appendActivity(data.entries || [], { showHeartbeat: !data.terminal });
        STATE.activityNextLine = data.next_line || STATE.activityNextLine;
        updateCompileBanner(data);
        updateCancelBtn({ status: data.status });
        if (data.terminal) {
          if (STATE.activityTimer) { clearInterval(STATE.activityTimer); STATE.activityTimer = null; }
          hideHeartbeat();
          await refreshAll({ background: true, reloadDetail: false });
          // After terminal, reload selected exp once without resetting the visible log.
          try {
            await loadDetail(experimentId, { preserveActivity: true, preserveScroll: true, force: true });
            const exp = STATE.detailCache[experimentId]
              || await fetchJson(`/api/ai-lab/experiments/${encodeURIComponent(experimentId)}`);
            maybeLoadBacktest(exp);
          } catch (_) {}
        }
      } catch (e) { /* keep polling */ }
    };
    STATE.activityTimer = setInterval(tick, 2000);
    tick();
  }

  function roleOf(e) {
    return e.role || e.model_role || null;
  }

  function appendActivity(entries, options = {}) {
    const logEl = $("#ai-process-log");
    if (!logEl) return;
    if (logEl.firstChild && logEl.firstChild.classList && logEl.firstChild.classList.contains("ai-empty")) {
      logEl.innerHTML = "";
    }
    let latestHeartbeat = null;
    for (const e of entries) {
      const role = roleOf(e);
      if (role) STATE.lastByRole[role] = e;
      if (e.heartbeat === true) {
        latestHeartbeat = e;
        continue;  // do not add to scrolling log
      }
      const row = document.createElement("div");
      row.className = `ai-log-row level-${escape(e.level || "info")}`;
      // Big visible warn block when the coder fell back to the template
      // (allow_template_fallback=true). The hard gate makes this rare, but
      // it's important to surface when it happens.
      if (e.path === "fallback_template" || e.model === "fallback_template" ||
          e.action === "blocked_lm_studio" || e.action === "blocked_lm_studio_autofix") {
        const warn = document.createElement("div");
        warn.className = "ai-log-row ai-log-fallback-warn";
        warn.innerHTML = e.path === "fallback_template" || e.model === "fallback_template"
          ? "⚠️ Код сгенерирован ШАБЛОНОМ, не LLM (fallback_template). Включена опция allow_template_fallback."
          : "🛑 LM Studio недоступна — пайплайн заблокирован. Запустите LM Studio с настроенными моделями.";
        logEl.appendChild(warn);
      }
      const ts = (e.ts || "").slice(11, 19);
      const fields = Object.keys(e).filter(k => !["ts","line","stage","action","level","role","model_role","heartbeat"].includes(k))
                       .map(k => `${k}=${typeof e[k] === "string" ? e[k] : JSON.stringify(e[k])}`)
                       .join(" ");
      const chip = role
        ? `<span class="role-chip role-${escape(role)}">${escape(role)}</span>`
        : `<span class="role-chip role-stage">${escape(e.stage || "")}</span>`;
      row.innerHTML = `<span class="t">${escape(ts)}</span>`
        + `<span class="s">${chip}</span>`
        + `<span class="a">${escape(e.action || "")}</span>`
        + (fields ? `<span class="f">${escape(fields)}</span>` : "");
      logEl.appendChild(row);
    }
    while (logEl.childNodes.length > 400) logEl.removeChild(logEl.firstChild);
    logEl.scrollTop = logEl.scrollHeight;
    if (latestHeartbeat && options.showHeartbeat !== false) showHeartbeat(latestHeartbeat);
    else if (options.showHeartbeat === false) hideHeartbeat();
    renderModelCoord();
  }

  function showHeartbeat(e) {
    const pill = $("#ai-heartbeat-pill");
    if (!pill) return;
    const secs = e.elapsed_sec ?? 0;
    pill.hidden = false;
    pill.textContent = `⌛ ${e.stage || ""} · ${e.action || ""} · ${secs}s`;
  }
  function hideHeartbeat() {
    const pill = $("#ai-heartbeat-pill");
    if (pill) pill.hidden = true;
  }

  function renderModelCoord() {
    const wrap = $("#ai-model-coord");
    if (!wrap) return;
    const roles = ["judge", "coder", "coder-autofix", "validator", "arbitrator"];
    const cells = roles.map(r => {
      const e = STATE.lastByRole[r];
      if (!e) return `<div class="ai-model-coord-cell"><span class="lbl">${escape(r)}</span><span class="val muted">—</span></div>`;
      const ts = (e.ts || "").slice(11, 19);
      return `<div class="ai-model-coord-cell">
        <span class="lbl"><span class="role-chip role-${escape(r)}">${escape(r)}</span></span>
        <span class="val">${escape(e.action || "")} <span class="muted">${escape(ts)}</span></span>
      </div>`;
    });
    wrap.innerHTML = cells.join("");
    wrap.hidden = false;
  }

  function updateCompileBanner(data) {
    const banner = $("#ai-compile-banner");
    if (!banner) return;
    if (data.status === "awaiting_compile") {
      banner.hidden = false;
      const path = data.sandbox_path || "";
      banner.innerHTML = `
        <div class="title">Ожидание компиляции <code>${escape(data.class_name || "")}</code></div>
        <div>AI Lab отправляет F5 в открытый NinjaScript Editor. Если DLL не обновится, откройте редактор и нажмите F5 вручную.</div>
        <div class="path">Файл: <code>${escape(path)}</code></div>
      `;
    } else if (data.status === "awaiting_compile_timeout") {
      banner.hidden = false;
      const eid = STATE.selectedExperimentId || "";
      banner.innerHTML = `
        <div class="title">Compile timeout — <code>${escape(data.class_name || "")}</code> не был перекомпилирован.</div>
        <div>Откройте NinjaScript Editor, проверьте что окно активно, нажмите F5 и затем продолжите ожидание.</div>
        <button class="hdr-btn" id="ai-resume-compile">Подождать ещё</button>
      `;
      const btn = $("#ai-resume-compile");
      if (btn) btn.addEventListener("click", async () => {
        await fetch(`/api/ai-lab/experiments/${encodeURIComponent(eid)}/resume-compile`,
          { method: "POST", headers: {"Content-Type": "application/json"}, body: "{}" });
        loadDetail(eid);
      });
    } else {
      banner.hidden = true;
    }
  }

  function startBusyPolling() {
    const refresh = async () => {
      try {
        const d = await fetchJson("/api/ai-lab/current");
        const banner = $("#ai-busy-banner");
        if (!banner) return;
        if (d.current) {
          banner.hidden = false;
          banner.innerHTML = `
            <span>⚙ Цикл выполняется:
              <a href="#" id="ai-busy-link"><code>${escape(d.current.experiment_id || "")}</code></a>
              · ${escape(d.current.class_name || "")} · ${escape(d.current.status || "")}</span>`;
          const a = $("#ai-busy-link");
          if (a) a.addEventListener("click", (ev) => {
            ev.preventDefault();
            loadDetail(d.current.experiment_id);
          });
        } else {
          banner.hidden = true;
        }
      } catch (e) { /* idle */ }
    };
    refresh();
    if (STATE.busyTimer) clearInterval(STATE.busyTimer);
    STATE.busyTimer = setInterval(refresh, 3000);
  }

  function portfolioActionHtml(row) {
    const blockers = row.portfolio_blockers || [];
    const eligible = row.portfolio_eligible === true;
    const isMember = row.is_portfolio_member === true;
    const disabled = eligible ? "" : " disabled";
    const blockerText = blockers.length
      ? `<div class="ai-portfolio-blockers">Blocked: ${escape(blockers.join("; "))}</div>`
      : `<div class="muted">Eligible for manual promotion.</div>`;
    return `
      <div class="ai-portfolio-actions">
        <button type="button" class="hdr-btn" data-portfolio-action="promote"${isMember ? "" : disabled}>Promote to Portfolio</button>
        <button type="button" class="hdr-btn" data-portfolio-action="approve"${isMember || eligible ? "" : disabled}>Approve Candidate</button>
        <button type="button" class="hdr-btn ai-remove-btn" data-portfolio-action="remove"${isMember ? "" : " disabled"}>Remove from Portfolio</button>
      </div>
      ${eligible || isMember ? "<div class=\"muted\">Promotion is manual only; no live/paper/demo trading is started.</div>" : blockerText}
    `;
  }

  function bindDetailActions(exp) {
    $$("#ai-detail [data-portfolio-action]").forEach(btn => {
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-portfolio-action");
        submitPortfolioAction(exp.experiment_id, action, btn).catch(e => {
          const msg = $("#ai-portfolio-message");
          if (msg) msg.textContent = `Ошибка: ${String(e)}`;
        });
      });
    });
  }

  async function submitPortfolioAction(experimentId, action, btn) {
    if (!experimentId || !action) return;
    if (btn) { btn.disabled = true; btn.textContent = "Saving..."; }
    const r = await fetch(`/api/ai-lab/experiments/${encodeURIComponent(experimentId)}/portfolio/${encodeURIComponent(action)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved_by: "ui" }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || data.message || `HTTP ${r.status}`);
    await refreshAll({ background: true, reloadDetail: false, force: true });
    await loadDetail(experimentId, { preserveActivity: true, preserveScroll: true, force: true });
  }

  function renderDetail(exp, history, row = {}) {
    const a = exp.analysis || {};
    const arb = exp.arbitration || {};
    const verdict = exp.verdict || {};
    const merged = { ...(exp.portfolio || {}), ...row };
    const isMember = merged.is_portfolio_member === true;
    return `
      <div class="ai-detail-section">
        <h4>${escape(exp.experiment_id)} <span class="ai-origin-marker">AI</span></h4>
        <div class="ai-detail-kv">
          <span class="k">AI-CELL</span><span class="v">${escape(exp.ai_cell_id || "—")}</span>
          <span class="k">Class</span><span class="v">${escape(exp.class_name || "—")}</span>
          <span class="k">Root</span><span class="v">${escape(exp.target_root || "—")}</span>
          <span class="k">Family</span><span class="v">${escape(exp.family || "—")}</span>
          <span class="k">Status</span><span class="v">${escape(exp.status || "—")}</span>
          <span class="k">History status</span><span class="v">${escape(row.history_status || exp.status || "—")}</span>
          <span class="k">Capital</span><span class="v">${escape(String(exp.primary_capital || ""))}</span>
          <span class="k">User goal</span><span class="v">${escape(exp.user_goal || "auto")}</span>
          <span class="k">Hypothesis</span><span class="v">${escape(exp.hypothesis || "")}</span>
        </div>
      </div>

      <div class="ai-detail-section">
        <h4>Knowledge Context</h4>
        <div class="ai-detail-kv">
          <span class="k">Built</span><span class="v">${exp.knowledge_context?.built ? "yes" : "no"}</span>
          <span class="k">Sources</span><span class="v">${fmt((exp.knowledge_context?.sources_read || []).length)}</span>
          <span class="k">Path</span><span class="v">${escape(exp.knowledge_context?.path || exp.memory_intake?.knowledge_context_path || "—")}</span>
          <span class="k">Reference</span><span class="v">${escape(exp.goal_constraints?.reference_pattern || "—")}</span>
        </div>
      </div>

      <div class="ai-detail-section">
        <h4>Portfolio Gate</h4>
        <div class="ai-detail-kv">
          <span class="k">Member</span><span class="v">${isMember ? "yes" : "no"}</span>
          <span class="k">Portfolio status</span><span class="v">${escape(merged.portfolio_status || "—")}</span>
          <span class="k">Promoted at</span><span class="v">${escape(merged.promoted_at || "—")}</span>
          <span class="k">Approved by</span><span class="v">${escape(merged.approved_by || "—")}</span>
          <span class="k">Source experiment</span><span class="v">${escape(merged.source_experiment_id || exp.experiment_id || "—")}</span>
        </div>
        <div id="ai-portfolio-message" class="ai-portfolio-message">${portfolioActionHtml(merged)}</div>
      </div>

      <div class="ai-detail-section">
        <h4>Arbitration Score</h4>
        <div class="ai-detail-score-strip">
          <div class="ai-detail-score-cell"><div class="label">Total</div><div class="val">${fmt(arb.score)}</div></div>
          <div class="ai-detail-score-cell"><div class="label">Growth</div><div class="val">${fmt(arb.growth_score)}</div></div>
          <div class="ai-detail-score-cell"><div class="label">Robust</div><div class="val">${fmt(arb.robustness_score)}</div></div>
          <div class="ai-detail-score-cell"><div class="label">Longev</div><div class="val">${fmt(arb.longevity_score)}</div></div>
          <div class="ai-detail-score-cell"><div class="label">Trades</div><div class="val">${fmt(arb.trade_confidence_score)}</div></div>
          <div class="ai-detail-score-cell"><div class="label">Fit</div><div class="val">${fmt(arb.portfolio_fit_score)}</div></div>
        </div>
        <p class="muted" style="margin-top:6px;font-size:11px;">${escape(arb.rationale || "")}</p>
      </div>

      <div class="ai-detail-section">
        <h4>Averages</h4>
        <div class="ai-detail-kv">
          <span class="k">Day</span><span class="v">${fmt(a.avg_per_day)}</span>
          <span class="k">Week</span><span class="v">${fmt(a.avg_per_week)}</span>
          <span class="k">Month</span><span class="v">${fmt(a.avg_per_month)}</span>
          <span class="k">Quarter</span><span class="v">${fmt(a.avg_per_quarter)}</span>
          <span class="k">Year</span><span class="v">${fmt(a.avg_per_year)}</span>
          <span class="k">Monthly Growth</span><span class="v">${fmt(a.monthly_growth_pct, { pct: true })}</span>
          <span class="k">Trades Total</span><span class="v">${fmt(a.trades_total)}</span>
          <span class="k">Years Tested</span><span class="v">${fmt(a.years_tested)}</span>
        </div>
      </div>

      <div class="ai-detail-section">
        <h4>Backtests</h4>
        <ul class="ai-detail-list">
          ${(exp.backtests || []).map(b => `
            <li>${escape(b.job_id)} — ${escape(b.status)} — ${escape(b.from_utc)} → ${escape(b.to_utc)}</li>
          `).join("") || "<li class='muted'>пока нет backtest jobs</li>"}
        </ul>
      </div>

      <div class="ai-detail-section">
        <h4>Verdict</h4>
        <div class="ai-detail-kv">
          <span class="k">Outcome</span><span class="v">${escape(verdict.outcome || "—")}</span>
          <span class="k">Code</span><span class="v">${escape(verdict.rejection_code || "—")}</span>
          <span class="k">Structural</span><span class="v">${verdict.structural ? "yes" : "no"}</span>
        </div>
        <ul class="ai-detail-list">
          ${(verdict.reasons || []).map(r => `<li>${escape(r)}</li>`).join("")}
        </ul>
      </div>

      <div class="ai-detail-section">
        <h4>Lineage</h4>
        <div class="ai-detail-kv">
          <span class="k">Parent</span><span class="v">${escape(exp.parent_experiment_id || "—")}</span>
          <span class="k">Chain</span><span class="v">${escape((exp.lineage || []).join(" → ") || "—")}</span>
        </div>
      </div>

      <div class="ai-detail-section">
        <h4>History & Lessons</h4>
        <ul class="ai-detail-list">
          ${history.slice(-30).reverse().map(h => `
            <li><strong>${escape(h.kind)}</strong> · ${escape(h.timestamp_utc || "")} — ${escape(h.normalized_pattern || h.summary || h.message || h.rejection_code || "")}</li>
          `).join("") || "<li class='muted'>пока пусто</li>"}
        </ul>
      </div>

      <div class="ai-detail-section">
        <h4>Sandbox source</h4>
        <div class="ai-detail-kv">
          <span class="k">Sandbox path</span><span class="v">${escape(exp.strategy_source?.sandbox_path || "—")}</span>
          <span class="k">Mirror path</span><span class="v">${escape(exp.strategy_source?.mirror_path || "—")}</span>
          <span class="k">SHA256</span><span class="v">${escape((exp.strategy_source?.sha256 || "").slice(0, 16) + "...")}</span>
        </div>
      </div>
    `;
  }

  function escape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  async function submitRun(ev) {
    ev.preventDefault();
    const lm = STATE.summary?.lm_studio || {};
    const resultBox = $("#ai-run-result");
    resultBox.hidden = false;
    if (!lmRunBypassAllowed() && !lm.run_allowed) {
      resultBox.innerHTML =
        `<strong style="color:#b00">Запуск заблокирован.</strong><br>` +
        `${escape(lm.message_ru || "Подождите включения AI-моделей в LM Studio.")}<br>` +
        `<span class="muted">Очередь исследований не создаётся, пока модели не ответят.</span>`;
      return;
    }
    const goal = $("#ai-run-goal").value.trim();
    const root = $("#ai-run-root").value || null;
    const capitalStr = $("#ai-run-capital").value;
    const capital = capitalStr ? Number(capitalStr) : null;
    const strategyCount = Math.max(1, Math.min(10, Number($("#ai-strategy-count")?.value || 1)));
    const itersRaw = $("#ai-iterations-per-strategy")?.value || "3";
    const iterationsUnlimited = itersRaw === "unlimited";
    const iterationsPerStrategy = iterationsUnlimited
      ? null
      : Math.max(1, Math.min(20, Number(itersRaw) || 3));
    const runtimeRaw = Number($("#ai-max-runtime-min")?.value || 60);
    const runtimeMinutes = runtimeRaw <= 0 ? null : Math.max(1, Math.min(1440, runtimeRaw));
    const stopOnFirst = !!$("#ai-stop-on-first-candidate")?.checked;
    const skipCompile = DEBUG ? !!$("#ai-skip-compile")?.checked : false;
    const skipBacktest = DEBUG ? !!$("#ai-skip-backtest")?.checked : false;
    const allowTemplateFallback = DEBUG ? !!$("#ai-allow-template-fallback")?.checked : false;
    resultBox.hidden = false;
    resultBox.textContent = "Запуск цикла...";
    STATE.runActive = true;
    renderLmGate();
    if (_lmReadinessTimer) {
      clearTimeout(_lmReadinessTimer);
      _lmReadinessTimer = null;
    }
    try {
      const r = await fetch("/api/ai-lab/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal, target_root: root, capital,
          research_mode: "research_until_candidate_or_budget_exhausted",
          strategy_count: strategyCount,
          iterations_per_strategy: iterationsPerStrategy,
          iterations_unlimited: iterationsUnlimited,
          max_total_runtime_minutes: runtimeMinutes,
          stop_on_first_candidate: stopOnFirst,
          target_candidate_count: 1,
          allow_template_fallback: allowTemplateFallback,
          skip_compile: skipCompile, skip_backtest: skipBacktest,
        }),
      });
      const data = await r.json();
      if (r.status === 409 && data.blocked_lm_studio) {
        STATE.runActive = false;
        renderLmGate();
        const missing = (data.preflight?.missing_roles || [])
          .map(m => `${m.role || "?"} (${m.reason || m.error || "?"})`).join(", ");
        resultBox.innerHTML =
          `<strong style="color:#b00">Запуск отменён — AI-модели не готовы.</strong><br>` +
          `<span class="muted">Очередь не создана.</span><br>` +
          `Недоступны роли: ${escape(missing) || "?"}.<br>` +
          `${escape(data.hint || lm.message_ru || "")}`;
        refreshLmReadiness({ force: true }).catch(() => {});
        return;
      }
      if (r.status === 409 && data.busy && data.current) {
        STATE.runActive = true;
        renderLmGate();
        resultBox.textContent = `Уже идёт цикл: ${data.current.experiment_id}. Открываю его.`;
        loadDetail(data.current.experiment_id);
        return;
      }
      resultBox.textContent = JSON.stringify(data, null, 2);
      await refreshAll({ preserveScroll: true, force: true, reloadDetail: false });
      const eid = data.experiment_id || data?.experiment?.experiment_id;
      if (eid) loadDetail(eid);
      startBusyPolling();
      startRunStatusPolling();
    } catch (e) {
      STATE.runActive = false;
      renderLmGate();
      resultBox.textContent = `Ошибка: ${e}`;
      scheduleLmReadinessPoll();
    }
  }

  async function scanResearch() {
    const chip = $("#ai-research-chip");
    chip.textContent = "User research: сканирование...";
    try {
      const r = await fetch("/api/ai-lab/user-research/scan", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      const data = await r.json();
      chip.textContent = `User research: ${data.files?.length || 0} файлов (new ${data.new?.length || 0}, changed ${data.changed?.length || 0})`;
    } catch (e) {
      chip.textContent = `User research: ошибка ${e}`;
    }
  }

  async function requestCancel() {
    const eid = STATE.selectedExperimentId;
    const btn = $("#ai-cancel-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Останавливаю…"; }
    // Cancel both the current experiment AND the outer run loop so the
    // runner won't auto-spawn the next strategy.
    try {
      await fetch("/api/ai-lab/run/cancel", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
    } catch (e) { /* swallow */ }
    if (eid) {
      try {
        await fetch(`/api/ai-lab/experiments/${encodeURIComponent(eid)}/cancel`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
        });
      } catch (e) { /* swallow */ }
    }
    setTimeout(() => {
      if (btn) { btn.disabled = false; btn.textContent = "Остановить"; }
    }, 2000);
  }

  async function submitNote(ev) {
    ev.preventDefault();
    const eid = STATE.selectedExperimentId;
    if (!eid) return;
    const ta = $("#ai-note-text");
    const text = (ta?.value || "").trim();
    if (!text) return;
    try {
      await fetch(`/api/ai-lab/experiments/${encodeURIComponent(eid)}/notes`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      ta.value = "";
      refreshNotesList(eid);
    } catch (e) { /* ignore */ }
  }

  async function refreshNotesList(experimentId) {
    const wrap = $("#ai-note-list");
    if (!wrap) return;
    try {
      const data = await fetchJson(`/api/ai-lab/experiments/${encodeURIComponent(experimentId)}/notes`);
      const notes = data.notes || [];
      if (!notes.length) { wrap.innerHTML = "Пока нет заметок."; return; }
      wrap.innerHTML = notes.map(n => {
        const applied = n.applied_at_stage ? " applied" : "";
        const ts = (n.ts_utc || "").slice(11, 19);
        const stage = n.applied_at_stage ? ` → applied at <em>${escape(n.applied_at_stage)}</em>` : " (pending)";
        return `<div class="note-row${applied ? ' applied' : ''}">
          <span class="muted">${escape(ts)}</span> ${escape(n.text || "")}${stage}
        </div>`;
      }).join("");
    } catch (e) {
      wrap.innerHTML = `<span class="muted">Ошибка: ${escape(String(e))}</span>`;
    }
  }

  async function submitPaste(ev) {
    ev.preventDefault();
    const eid = STATE.selectedExperimentId;
    if (!eid) return;
    const className = $("#ai-paste-class")?.value?.trim();
    const text = $("#ai-paste-text")?.value || "";
    if (!className || !text.trim()) return;
    try {
      const r = await fetch(`/api/ai-lab/experiments/${encodeURIComponent(eid)}/compile-errors/paste`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ class_name: className, text }),
      });
      const data = await r.json();
      $("#ai-paste-text").value = "";
      const chip = $("#ai-compile-source-status");
      if (chip) chip.textContent = `paste: +${data.count || 0} строк`;
    } catch (e) { /* ignore */ }
  }

  async function pollSourceStatus() {
    const chip = $("#ai-compile-source-status");
    if (!chip) return;
    try {
      const s = await fetchJson("/api/ai-lab/compile-source-status");
      const src = s.last_emitted_source || s.reason || "no compile-error pipe yet";
      const ts = (s.last_emit_ts_utc || s.checked_at_utc || "").slice(11, 19);
      chip.textContent = `compile source: ${src}${ts ? " · " + ts : ""}`;
      chip.classList.toggle("ok", !!s.last_emitted_source);
      chip.classList.toggle("bad", !!s.error || !!s.reason);
    } catch (e) {
      chip.textContent = "compile source: n/a";
      chip.classList.add("bad");
    }
  }

  function startDataPolling() {
    if (STATE.refreshTimer) clearInterval(STATE.refreshTimer);
    STATE.refreshTimer = setInterval(() => {
      if (document.hidden) return;
      refreshAll({ background: true, reloadDetail: false }).catch(() => {});
    }, 5000);
  }

  async function maybeLoadBacktest(exp) {
    const wrap = $("#ai-backtest-visuals");
    if (!wrap) return;
    const bts = exp.backtests || [];
    const jobId = bts.length ? bts[bts.length - 1].job_id : null;
    const status = exp.status || "";
    const eligible = jobId && (
      status === "backtesting" || status === "backtest_done" || status === "analysis_ready"
      || status.endsWith("_candidate") || status === "rejected" || status === "portfolio_contributor"
    );
    if (!eligible) { wrap.hidden = true; wrap.innerHTML = ""; STATE.btLoadedForJob = null; return; }
    if (STATE.btLoadedForJob === jobId) return;
    STATE.btLoadedForJob = jobId;
    wrap.hidden = false;
    wrap.innerHTML = `<div class="bt-section"><div class="ai-empty">Загрузка backtest визуалов…</div></div>`;
    try {
      const payload = await fetchJson(`/api/ai-lab/experiments/${encodeURIComponent(exp.experiment_id)}/backtest`);
      renderBacktestVisuals(wrap, payload);
    } catch (e) {
      wrap.innerHTML = `<div class="bt-section"><div class="ai-empty">Backtest визуалы недоступны: ${escape(String(e))}</div></div>`;
    }
  }

  function renderBacktestVisuals(wrap, payload) {
    if (!payload || !payload.ok) {
      wrap.innerHTML = `<div class="bt-section"><div class="ai-empty">Нет данных backtest.</div></div>`;
      return;
    }
    const m = payload.metrics || {};
    const metricsHtml = `
      <div class="bt-metrics">
        ${metricCell("Net PnL", fmt(m.net_pnl))}
        ${metricCell("Trades", fmt(m.trades_total))}
        ${metricCell("PF", fmt(m.profit_factor))}
        ${metricCell("Max DD", fmt(m.max_drawdown))}
        ${metricCell("Win %", fmt(m.win_rate_pct, { pct: true }))}
        ${metricCell("Sharpe", fmt(m.sharpe))}
      </div>`;
    wrap.innerHTML = `
      <div class="bt-section"><h4>Метрики</h4>${metricsHtml}</div>
      <div class="bt-section"><h4>Equity Curve</h4><div id="ai-bt-equity"></div></div>
      <div class="bt-section"><h4>Daily PnL</h4><div id="ai-bt-daily"></div></div>
      <div class="bt-section"><h4>Drawdown</h4><div id="ai-bt-dd"></div></div>
      <div class="bt-section">
        <h4>Trades (последние 200)</h4>
        <div class="bt-trades" id="ai-bt-trades"></div>
      </div>
      <div class="bt-section">
        <a href="${escape(payload.job_url || "#")}" target="_blank">Открыть полный job report →</a>
      </div>`;
    // Reuse performance.js renderers if available
    const eqEl = document.getElementById("ai-bt-equity");
    const dlyEl = document.getElementById("ai-bt-daily");
    const ddEl = document.getElementById("ai-bt-dd");
    try { if (window.drawMultiEquityCurves && payload.equity_curve) window.drawMultiEquityCurves(eqEl, payload.equity_curve); } catch (_) {}
    try { if (window.drawDailyLineChart && payload.daily) window.drawDailyLineChart(dlyEl, payload.daily); } catch (_) {}
    try { if (window.drawHorizontalBars && payload.drawdown_series) window.drawHorizontalBars(ddEl, payload.drawdown_series); } catch (_) {}
    try { if (window.renderLastTrades && payload.trades) window.renderLastTrades(document.getElementById("ai-bt-trades"), payload.trades); }
    catch (_) {
      const tEl = document.getElementById("ai-bt-trades");
      if (tEl) tEl.innerHTML = renderTradesFallback(payload.trades || []);
    }
  }

  function metricCell(lbl, val) {
    return `<div class="m-cell"><div class="lbl">${escape(lbl)}</div><div class="val">${escape(val)}</div></div>`;
  }

  function renderTradesFallback(trades) {
    if (!trades.length) return `<span class="muted">нет сделок</span>`;
    const rows = trades.slice(-200).map(t => `
      <tr>
        <td>${escape(t.entry_time || "")}</td>
        <td>${escape(t.side || "")}</td>
        <td>${fmt(t.entry_price)}</td>
        <td>${fmt(t.exit_price)}</td>
        <td>${fmt(t.profit)}</td>
      </tr>`).join("");
    return `<table><thead><tr><th>Entry</th><th>Side</th><th>Entry$</th><th>Exit$</th><th>PnL</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---------- Tabs (Experiments | Portfolio | Error Memory | LM Studio) ----------
  const TAB_TARGETS = {
    "experiments": ["#ai-process-log", ".ai-grid", "#ai-run-result"],
    "portfolio": [".ai-grid"],          // portfolio lives in the left grid column
    "error-memory": ["#ai-error-memory-panel"],
    "lm-studio": ["#ai-lm-studio-panel"],
  };

  function showTab(tab) {
    document.querySelectorAll(".ai-tab").forEach(b => {
      b.classList.toggle("active", b.getAttribute("data-tab") === tab);
    });
    // Always keep run-panel + hero visible. Hide/show the optional dedicated panels.
    const errorPanel = document.getElementById("ai-error-memory-panel");
    const lmPanel = document.getElementById("ai-lm-studio-panel");
    if (errorPanel) errorPanel.hidden = tab !== "error-memory";
    if (lmPanel) lmPanel.hidden = tab !== "lm-studio";
    if (tab === "error-memory") loadErrorMemory();
    if (tab === "lm-studio") loadLmStudioPanel();
  }

  async function loadErrorMemory() {
    try {
      const r = await fetch("/api/ai-lab/errors/summary");
      const data = await r.json();
      const patternsWrap = document.getElementById("ai-error-patterns-wrap");
      const lessonsWrap = document.getElementById("ai-lessons-wrap");
      const notesWrap = document.getElementById("ai-global-notes-wrap");
      const patterns = (data.patterns || []).slice(0, 30);
      patternsWrap.innerHTML = patterns.length
        ? `<ul class="ai-error-list-ul">${patterns.map(p => `
            <li><strong>${escape(p.phase)}/${escape(p.error_type)}</strong> ×${p.count}
              — <span class="muted">${escape((p.normalized_pattern || "").slice(0, 220))}</span></li>
          `).join("")}</ul>`
        : "(пусто)";
      const lessons = (data.lessons_recent || []).slice(0, 20).reverse();
      lessonsWrap.innerHTML = lessons.length
        ? `<ul class="ai-error-list-ul">${lessons.map(l => `
            <li><strong>${escape(l.scope || "global")}</strong>
              ${escape(l.scope_key ? "/" + l.scope_key : "")}
              — ${escape(l.summary || "")}
              ${l.rule ? `<br><span class="muted">rule: ${escape(l.rule)}</span>` : ""}</li>
          `).join("")}</ul>`
        : "(пусто)";
      const notes = (data.global_operator_notes || []).slice(-20).reverse();
      notesWrap.innerHTML = notes.length
        ? `<ul class="ai-error-list-ul">${notes.map(n => `
            <li>[${escape(n.priority || "normal")}] ${escape(n.text || "")}
              ${n.source_experiment_id ? `<span class="muted"> · из ${escape(n.source_experiment_id)}</span>` : ""}</li>
          `).join("")}</ul>`
        : "(пусто)";
    } catch (e) {
      console.error("loadErrorMemory", e);
    }
  }

  async function loadLmStudioPanel() {
    const wrap = document.getElementById("ai-lm-studio-wrap");
    if (!wrap) return;
    wrap.textContent = "Проверяем LM Studio и AI-модели…";
    try {
      const data = await fetchJson("/api/ai-lab/lm-studio/readiness?force=1");
      if (STATE.summary) {
        STATE.summary.lm_studio = { ...(STATE.summary.lm_studio || {}), ...data };
      }
      renderLmGate();
      const missing = (data.missing_roles || []);
      const missingRun = (data.missing_run_roles || []);
      const pre = data.preflight || {};
      const roleHealth = pre.role_health || {};
      const healthRows = Object.entries(roleHealth).map(([role, row]) => {
        const ok = row.ok ? "✅" : "❌";
        return `<li>${ok} <strong>${escape(role)}</strong> · ${escape(row.model || "?")} — ${escape(row.status || "?")}${row.elapsed_sec != null ? ` (${row.elapsed_sec}s)` : ""}</li>`;
      }).join("");
      wrap.innerHTML = `
        <div><strong>Статус:</strong> ${escape(data.message_ru || data.status || "?")}</div>
        <div><strong>Запуск разрешён:</strong> ${data.run_allowed ? "✅ да" : "❌ нет"}</div>
        <div><strong>Base URL:</strong> ${escape(data.base_url || "?")}</div>
        <div><strong>Сервер LM Studio:</strong> ${data.available ? "✅" : "❌"}</div>
        <div><strong>Модели в списке (${(data.models || []).length}):</strong> ${escape((data.models || []).join(", ") || "—")}</div>
        <div><strong>Нужны для запуска (judge + coder):</strong>
          ${missingRun.length ? `<ul>${missingRun.map(m => `<li>${escape(m.role || "?")} → ${escape(m.model || "?")}</li>`).join("")}</ul>` : "в списке есть"}
        </div>
        <div><strong>Chat-probe (preflight):</strong>
          ${healthRows ? `<ul>${healthRows}</ul>` : (data.probe_pending ? "ожидает проверки" : "—")}
        </div>
        <div><strong>Все роли из model_roles (в списке /models):</strong>
          ${missing.length ? `<ul>${missing.map(m => `<li>❌ ${escape(m.role || "?")} (ожидается ${escape(m.expected_model || "?")})</li>`).join("")}</ul>` : "✅"}
        </div>
        <div class="muted">Проверено: ${escape(data.preflight_checked_at_utc || "—")} · кэш ${escape(String(data.preflight_cache_ttl_sec || 60))} с</div>
      `;
    } catch (e) {
      wrap.textContent = `Ошибка: ${e}`;
    }
  }

  async function submitGlobalNote(ev) {
    ev.preventDefault();
    const ta = document.getElementById("ai-global-note-text");
    const text = (ta?.value || "").trim();
    if (!text) return;
    try {
      const r = await fetch("/api/ai-lab/operator-notes/global", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, priority: "high" }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      ta.value = "";
      await loadErrorMemory();
    } catch (e) {
      alert(`Не удалось сохранить правило: ${e}`);
    }
  }

  async function sweepStale() {
    const btn = document.getElementById("ai-stale-sweep-btn");
    if (btn) { btn.disabled = true; btn.textContent = "Очищаю…"; }
    try {
      const r = await fetch("/api/ai-lab/maintenance/sweep-stale", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ heartbeat_ttl_hours: 6 }),
      });
      const data = await r.json();
      alert(`Sweep: scanned=${data.scanned}, cancelled=${(data.cancelled || []).length}`);
      await refreshAll({ preserveScroll: true, force: true });
    } catch (e) {
      alert(`Sweep failed: ${e}`);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "Очистить зависшие"; }
    }
  }

  // ---------- Run-level progress polling (outer/inner indices) ----------
  let _runStatusTimer = null;
  function startRunStatusPolling() {
    if (_runStatusTimer) return;
    pollRunStatus();
    _runStatusTimer = setInterval(pollRunStatus, 3000);
  }
  function stopRunStatusPolling() {
    if (_runStatusTimer) { clearInterval(_runStatusTimer); _runStatusTimer = null; }
    const box = document.getElementById("ai-run-progress");
    if (box) box.hidden = true;
  }
  async function pollRunStatus() {
    try {
      const r = await fetch("/api/ai-lab/run/status");
      const data = await r.json();
      const box = document.getElementById("ai-run-progress");
      if (!box) return;
      const run = data.run;
      if (!run) {
        const wasActive = STATE.runActive;
        STATE.runActive = false;
        renderLmGate();
        stopRunStatusPolling();
        if (wasActive) scheduleLmReadinessPoll();
        return;
      }
      STATE.runActive = true;
      renderLmGate();
      if (_lmReadinessTimer) {
        clearTimeout(_lmReadinessTimer);
        _lmReadinessTimer = null;
      }
      box.hidden = false;
      const innerTotal = run.iterations_unlimited ? "∞" : (run.iterations_per_strategy ?? "?");
      const secLeft = run.seconds_remaining;
      const timeStr = secLeft == null
        ? "без лимита"
        : `${Math.floor(secLeft / 60)} мин ${secLeft % 60} с`;
      box.innerHTML =
        `<strong>Run ${escape(run.run_id || "?")}:</strong> ` +
        `strategy ${run.strategy_idx ?? "?"}/${run.strategy_count ?? "?"}, ` +
        `iter ${run.iteration_idx ?? "?"}/${innerTotal}, ` +
        `время осталось: ${escape(timeStr)}, ` +
        `кандидатов: ${run.candidate_count ?? 0}` +
        (run.cancelled ? ` · <span style="color:#b00">остановлено</span>` : "");
    } catch (e) {
      // network glitch — keep polling
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const qs = new URLSearchParams(window.location.search);
    const eid = qs.get("experiment");
    if (eid) {
      STATE.selectedExperimentId = eid;
      persistSelection();
    }
    window.addEventListener("scroll", () => {
      if (!STATE.restoringScroll) STATE.lastScrollAt = Date.now();
    }, { passive: true });
    $("#ai-refresh-btn")?.addEventListener("click", () => refreshAll({ preserveScroll: true, force: true }));
    $("#ai-run-btn")?.addEventListener("click", () => $("#ai-run-form").requestSubmit());
    $("#ai-scan-btn")?.addEventListener("click", scanResearch);
    $("#ai-run-form")?.addEventListener("submit", submitRun);
    $("#ai-cancel-btn")?.addEventListener("click", requestCancel);
    $("#ai-note-form")?.addEventListener("submit", submitNote);
    $("#ai-paste-form")?.addEventListener("submit", submitPaste);
    // New: tabs, error memory, stale sweep, run-status polling.
    document.querySelectorAll(".ai-tab").forEach(btn => {
      btn.addEventListener("click", () => showTab(btn.getAttribute("data-tab")));
    });
    $("#ai-error-memory-refresh")?.addEventListener("click", loadErrorMemory);
    $("#ai-stale-sweep-btn")?.addEventListener("click", sweepStale);
    $("#ai-global-note-form")?.addEventListener("submit", submitGlobalNote);
    // Kick off run-status polling — it'll auto-hide when no run is active.
    startRunStatusPolling();
    if (DEBUG) {
      document.querySelectorAll(".ai-debug-only").forEach(el => { el.hidden = false; });
      $("#ai-allow-template-fallback")?.addEventListener("change", renderLmGate);
    }
    refreshAll({ force: true, reloadDetail: false }).then(() => {
      if (STATE.selectedExperimentId) {
        return loadDetail(STATE.selectedExperimentId);
      }
      return null;
    }).catch(e => console.error(e));
    startDataPolling();
    startBusyPolling();
    pollSourceStatus();
    STATE.sourceStatusTimer = setInterval(pollSourceStatus, 5000);
  });
})();
