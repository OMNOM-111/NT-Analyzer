"use strict";

// ---------------- API helpers ---------------------------------------------
const api = {
  async get(url) {
    const r = await fetch(url, { headers: { Accept: "application/json" } });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `${r.status}`);
    return data;
  },
  async post(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `${r.status}`);
    return data;
  },
  async delete(url) {
    const r = await fetch(url, { method: "DELETE", headers: { Accept: "application/json" } });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `${r.status}`);
    return data;
  },
};

function storageGet(key, fallback = null) {
  try {
    const value = localStorage.getItem(key);
    return value == null ? fallback : value;
  } catch {
    return fallback;
  }
}

function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch {}
}

function storageJsonArray(key) {
  try {
    const parsed = JSON.parse(storageGet(key, "[]"));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

// ---------------- active-run state machine -------------------------------
// Tracks the most recently submitted single job or batch so we can show
// "Ожидание…/В работе…", display a cancel button, and gate the submit
// button until the run reaches a terminal status.
let _activeRun = null;
let _submitInFlight = false;
//   {
//     kind: "job" | "batch",
//     id: string,
//     strategy: string,
//     instruments: string[],
//     period: { from_utc, to_utc },
//     started_at: number,            // Date.now() at submit
//     last_status: string,           // last seen status ("pending"/"running"/...)
//     counts: {pending,running,done,failed,cancelled,missing}, // for batches
//     poll_timer: number|null,
//     cancel_requested: boolean,
//   }
let _activeRunPollTimer = null;
let _ntRunning = null;  // null=unknown, true/false from /api/health

function isTerminalStatus(s) {
  return s === "done" || s === "failed" || s === "cancelled" ||
    s === "partial_failed" || s === "partial_cancelled" || s === "missing";
}
function isBatchTerminal(counts, total) {
  if (!counts) return false;
  const pending = counts.pending || 0, running = counts.running || 0;
  return (pending + running) === 0;
}

function startActiveRun(info) {
  _activeRun = Object.assign({
    started_at: Date.now(),
    last_status: "pending",
    counts: null,
    cancel_requested: false,
  }, info);
  renderActiveRunPanel();
  setSubmitState("pending");
  if (_activeRunPollTimer) clearInterval(_activeRunPollTimer);
  pollActiveRun();
  _activeRunPollTimer = setInterval(pollActiveRun, 2000);
}

function endActiveRun(reason) {
  if (_activeRunPollTimer) { clearInterval(_activeRunPollTimer); _activeRunPollTimer = null; }
  setSubmitState("idle");
  renderActiveRunPanel();
  loadRecentReports();
  // Retry after a short delay: the server may not have written the report
  // file by the time the first refresh fires.
  setTimeout(() => refreshJobs({ reset: true }), 2000);
  // Auto-clear the active-run panel after a short grace period so it
  // doesn't permanently take sidebar space, but only if the operator
  // hasn't started another run in the meantime.
  const finishedId = _activeRun ? _activeRun.id : null;
  setTimeout(() => {
    if (_activeRun && _activeRun.id === finishedId
        && isTerminalStatus(_activeRun.last_status)) {
      _activeRun = null;
      const panel = document.getElementById("active-run");
      if (panel) panel.hidden = true;
    }
  }, 8000);
}

async function pollActiveRun() {
  if (!_activeRun) return;
  try {
    if (_activeRun.kind === "job") {
      const j = await api.get(`/api/jobs/${encodeURIComponent(_activeRun.id)}`);
      _activeRun.last_status = j.status;
      renderActiveRunPanel();
      setSubmitState(j.status);
      if (isTerminalStatus(j.status)) endActiveRun(j.status);
    } else {
      const b = await api.get(`/api/batches/${encodeURIComponent(_activeRun.id)}`);
      _activeRun.counts = b.counts || {};
      _activeRun.total  = b.total || 0;
      const c = _activeRun.counts;
      const total = _activeRun.total || 0;
      _activeRun.last_status = summarizeBatchCounts(c, total);
      renderActiveRunPanel();
      setSubmitState(_activeRun.last_status);
      if (isBatchTerminal(c, total)) endActiveRun(_activeRun.last_status);
    }
  } catch (e) {
    // Transient: keep polling.
  }
}

function setSubmitState(state) {
  const submit = document.getElementById("run-submit");
  const cancel = document.getElementById("run-cancel");
  if (!submit || !cancel) return;
  if (state === "idle") {
    submit.disabled = false;
    submit.classList.remove("busy");
    submit.textContent = "Запустить бэктест";
    cancel.hidden = true;
    cancel.disabled = false;
    cancel.textContent = "Остановить";
    return;
  }
  // running/pending — block re-submit, expose cancel.
  submit.disabled = true;
  submit.classList.add("busy");
  if (state === "running") {
    submit.textContent = "В работе…";
  } else if (state === "pending" && _ntRunning === false) {
    submit.textContent = "Ожидание запуска NinjaTrader…";
  } else {
    submit.textContent = "Ожидание…";
  }
  cancel.hidden = false;
  cancel.disabled = false;
  if (_activeRun && _activeRun.cancel_requested) {
    cancel.disabled = true;
    cancel.textContent = "Отмена запрошена…";
  } else {
    cancel.textContent = "Остановить";
  }
}

function renderActiveRunPanel() {
  const panel = document.getElementById("active-run");
  if (!panel) return;
  if (!_activeRun) { panel.hidden = true; return; }
  panel.hidden = false;

  const ar = _activeRun;
  const statusEl = document.getElementById("active-run-status");
  const status = ar.last_status || "pending";
  statusEl.textContent = statusLabel(status);
  statusEl.className = "active-run-status " + (STATUS_CLASSES[status] || "unknown");

  document.getElementById("active-run-strategy").textContent = ar.strategy || "—";
  const instrText = (ar.instruments && ar.instruments.length)
    ? (ar.instruments.length === 1
        ? fmtContract(ar.instruments[0])
        : `${ar.instruments.length} инструментов`)
    : "—";
  const instEl = document.getElementById("active-run-instruments");
  instEl.textContent = instrText;
  instEl.title = (ar.instruments || []).map(fmtContract).join(", ");

  const p = ar.period || {};
  document.getElementById("active-run-period").textContent =
    p.from_utc && p.to_utc
      ? `${_fmtDatePT(p.from_utc)} → ${_fmtDatePT(p.to_utc)}`
      : "—";

  // Progress (batch only).For single-job there's no fraction we can trust.
  const bar  = document.getElementById("active-run-bar");
  const txt  = document.getElementById("active-run-progress");
  const hint = document.getElementById("active-run-hint");
  if (ar.kind === "batch" && ar.counts && ar.total) {
    const c = ar.counts;
    const finished = (c.done||0) + (c.failed||0) + (c.cancelled||0) + (c.missing||0);
    const pct = ar.total > 0 ? Math.round((finished / ar.total) * 100) : 0;
    bar.style.width = pct + "%";
    txt.textContent = `${finished} из ${ar.total} · в работе ${c.running||0} · ожидает ${c.pending||0}` +
      ((c.failed||0) > 0 ? ` · ошибок ${c.failed}` : "") +
      ((c.missing||0) > 0 ? ` · пропало ${c.missing}` : "") +
      ((c.cancelled||0) > 0 ? ` · отменено ${c.cancelled}` : "");
    hint.hidden = true;
  } else {
    // Single job: indeterminate bar (just full when done).
    const finished = isTerminalStatus(ar.last_status);
    bar.style.width = finished ? "100%" : (ar.last_status === "running" ? "55%" : "15%");
    txt.textContent = ar.kind === "batch" ? "Ожидание данных…" : "Один инструмент";
    if (!finished) {
      hint.hidden = false;
      if (ar.last_status === "pending" && _ntRunning === false) {
        hint.textContent = "NinjaTrader не запущен — задача в очереди. Запустите NinjaTrader; bridge подхватит её автоматически.";
      } else {
        hint.textContent = "Прогресс по датам недоступен — текущий bridge его не отдаёт.";
      }
    } else {
      hint.hidden = true;
    }
  }
}

function tickActiveRunElapsed() {
  if (!_activeRun) return;
  const sec = Math.max(0, Math.round((Date.now() - _activeRun.started_at) / 1000));
  const m = Math.floor(sec / 60), s = sec % 60;
  const txt = m > 0 ? `${m} мин ${String(s).padStart(2,"0")} с` : `${s} с`;
  const el = document.getElementById("active-run-elapsed");
  if (el) el.textContent = txt;
}

async function onCancelActiveRun() {
  if (!_activeRun) return;
  if (!confirm("Остановить активный запуск?")) return;
  _activeRun.cancel_requested = true;
  setSubmitState(_activeRun.last_status || "pending");
  try {
    if (_activeRun.kind === "job") {
      await api.post(`/api/jobs/${encodeURIComponent(_activeRun.id)}/cancel`, {});
    } else {
      await api.post(`/api/batches/${encodeURIComponent(_activeRun.id)}/cancel`, {});
    }
  } catch (e) {
    alert("Ошибка отмены: " + e.message);
    _activeRun.cancel_requested = false;
    setSubmitState(_activeRun.last_status || "pending");
    return;
  }
  // Refresh sooner so the UI reflects the new state quickly.
  pollActiveRun();
  refreshJobs({ reset: true });
}

// Compat shim: was previously a small "recent reports" placeholder block.
// The full reports list now lives in #reports-panel and is refreshed via
// refreshJobs(), so all callers can simply hit refreshJobs() instead.
function loadRecentReports() { refreshJobs({ reset: true }); }

function summarizeBatchCounts(c, total) {
  const p = c.pending||0, r = c.running||0;
  if (p + r > 0) return r > 0 ? "running" : "pending";
  if ((c.failed||0) > 0 || (c.missing||0) > 0) {
    return ((c.failed||0) + (c.missing||0)) === total && total > 0
      ? "failed"
      : "partial_failed";
  }
  if ((c.cancelled||0) > 0) {
    return (c.cancelled||0) === total && total > 0
      ? "cancelled"
      : "partial_cancelled";
  }
  if ((c.failed||0) === total && total > 0) return "failed";
  if ((c.cancelled||0) === total && total > 0) return "cancelled";
  return "done";
}

// ---------------- overlay panels (Jobs / Diagnostics) -------------------
function openOverlay(name) {
  const el = document.getElementById(`overlay-${name}`);
  if (!el) return;
  el.hidden = false;
  if (name === "jobs") refreshJobs({ reset: true });
  if (name === "diag") refreshDiagnostics();
}
function closeOverlay(name) {
  const el = document.getElementById(`overlay-${name}`);
  if (el) el.hidden = true;
}
// no-op compat shim: code paths that used to call switchTab("jobs"/"diag")
// now open the overlay; calls for "run"/"result" become no-ops since the
// workbench shows both panes simultaneously.
function switchTab(name) {
  if (name === "jobs" || name === "diag") openOverlay(name);
}
document.addEventListener("click", (ev) => {
  const t = ev.target;
  if (!t) return;
  if (t.id === "btn-jobs") openOverlay("jobs");
  else if (t.id === "btn-diag") openOverlay("diag");
  else if (t.id === "btn-restart-server") restartServer();
  else if (t.classList && t.classList.contains("overlay-close")) {
    const which = t.dataset.close || "";
    const name = which.replace(/^overlay-/, "");
    if (name) closeOverlay(name);
  } else if (t.classList && t.classList.contains("overlay")) {
    // click on backdrop closes
    t.hidden = true;
  }
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") {
    document.querySelectorAll(".overlay:not([hidden])").forEach(el => el.hidden = true);
  }
});

// ---------------- server restart -------------------------------------------
async function restartServer() {
  const btn = document.getElementById("btn-restart-server");
  const pill = document.getElementById("health-pill");
  if (btn) { btn.disabled = true; btn.textContent = "↺ Перезапуск…"; }
  if (pill) { pill.textContent = "перезапуск…"; pill.className = "status-pill warn"; }
  try {
    await api.post("/api/server/restart", {});
  } catch (_) { /* server will drop the connection during restart — ignore */ }
  // Poll /api/health until server is back (up to 15 seconds).
  let ok = false;
  for (let i = 0; i < 30; i++) {
    await new Promise(r => setTimeout(r, 500));
    try {
      const h = await api.get("/api/health");
      if (h && h.host) { ok = true; break; }
    } catch (_) {}
  }
  if (btn) { btn.disabled = false; btn.textContent = "↺ Сервер"; }
  if (ok) {
    if (pill) { pill.textContent = "перезапущен ✓"; pill.className = "status-pill ok"; }
    // Reload profiles if that tab is active, then full bootstrap.
    _profilesState.loaded = false;
    setTimeout(() => bootstrap(), 300);
  } else {
    if (pill) { pill.textContent = "сервер не отвечает"; pill.className = "status-pill bad"; }
  }
}

// ---------------- bootstrap -----------------------------------------------
let _catalog = null;  // last GET /api/catalog response
let _bootstrapWired = false;

async function bootstrap() {
  // health + ninjatrader status
  try {
    const h = await api.get("/api/health");
    document.getElementById("health-pill").textContent =
      `backend ok @ ${h.host}`;
    document.getElementById("health-pill").classList.add("ok");
    setStatusChip("ss-nt",
      h.ninjatrader_running ? "NinjaTrader: запущен" : "NinjaTrader: не запущен",
      h.ninjatrader_running ? "ok" : "warn");
    _ntRunning = (h.ninjatrader_running === true) ? true
                : (h.ninjatrader_running === false) ? false : null;
    document.getElementById("d-host").textContent = h.host;
    document.getElementById("d-root").textContent = h.project_root;
    const dJobs = document.getElementById("d-jobs");
    if (dJobs) dJobs.textContent = h.jobs_dir || "";
  } catch (e) {
    document.getElementById("health-pill").textContent = "backend недоступен";
    document.getElementById("health-pill").classList.add("bad");
    setStatusChip("ss-nt", "Backend: недоступен", "bad");
  }

  await loadCatalog();

  // Phase 22c — accept prefill from "Открыть в бэктесте" on the Trading page.
  // URL params: ?strategy=<class>&instrument=<sym>&timeframe=<"5 Minute">&params=<json>
  applyTradingPrefillFromURL();

  if (!_bootstrapWired) {
  _bootstrapWired = true;
  document.getElementById("run-form").addEventListener("submit", onSubmitJob);
  document.getElementById("d-refresh").addEventListener("click", refreshDiagnostics);
  document.getElementById("d-catalog-refresh").addEventListener("click", () => triggerCatalogRefresh("diag"));
  document.getElementById("ss-stale-btn").addEventListener("click", (e) => { e.stopPropagation(); triggerCatalogRefresh("chip"); });
  const btnRefMargins = document.getElementById("btn-refresh-margins");
  if (btnRefMargins) btnRefMargins.addEventListener("click", triggerMarginsRefresh);
  document.getElementById("f-class").addEventListener("change", onStrategyChange);
  ["f-starting-capital", "f-intraday-only"]
    .forEach(id => {
      const node = document.getElementById(id);
      if (!node) return;
      node.addEventListener("input", updateRiskProfilePanel);
      node.addEventListener("change", updateRiskProfilePanel);
    });

  // Jobs toolbar: status filter + Refresh button.
  document.querySelectorAll("#jobs-filter button").forEach(btn => {
    btn.addEventListener("click", () => {
      _jobsFilter = btn.dataset.filter || "all";
      document.querySelectorAll("#jobs-filter button").forEach(b =>
        b.classList.toggle("active", b === btn)
      );
      refreshJobs({ reset: true });
    });
  });
  document.getElementById("jobs-refresh").addEventListener("click", () => refreshJobs({ reset: true }));

  // Sort headers
  document.querySelectorAll("#jobs-table th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (_sortCol === col) {
        _sortDir = _sortDir === "asc" ? "desc" : "asc";
      } else {
        _sortCol = col;
        _sortDir = col === "mtime" ? "desc" : "asc";
      }
      _updateSortHeaders();
      refreshJobs({ reset: true });
    });
  });

  // Check-all checkbox
  const chkAll = document.getElementById("jobs-check-all");
  if (chkAll) {
    chkAll.addEventListener("change", () => {
      document.querySelectorAll("#jobs-table tbody input[type=checkbox]").forEach(c => {
        if (c.disabled) return;
        c.checked = chkAll.checked;
        const key = c.dataset.repkey;
        if (chkAll.checked) _checkedKeys.add(key);
        else _checkedKeys.delete(key);
      });
      _updateDeleteCheckedBtn();
    });
  }
  const btnDelChecked = document.getElementById("btn-delete-checked");
  if (btnDelChecked) {
    btnDelChecked.addEventListener("click", deleteCheckedReports);
  }

  // View toggle buttons
  document.querySelectorAll(".view-btn[data-view]").forEach(btn => {
    btn.addEventListener("click", () => {
      _reportsView = btn.dataset.view;
      storageSet(_REPORTS_VIEW_CACHE_KEY, _reportsView);
      document.querySelectorAll(".view-btn[data-view]").forEach(b =>
        b.classList.toggle("active", b === btn)
      );
      refreshJobs({ reset: true });
    });
  });
  // Restore active button from saved state
  document.querySelectorAll(".view-btn[data-view]").forEach(b => {
    b.classList.toggle("active", b.dataset.view === _reportsView);
  });

  document.getElementById("run-cancel").addEventListener("click", onCancelActiveRun);

  const reportsWrap = document.querySelector(".reports-wrap");
  if (reportsWrap) reportsWrap.addEventListener("scroll", maybeLoadMoreReports);

  refreshJobs({ reset: true });
  // Poll every 3 s while the tab is visible; _pollReportsPage fetches the
  // latest first-page and merges without resetting scroll/pagination.
  setInterval(() => {
    if (document.visibilityState === "visible") refreshJobs({ poll: true });
  }, 3000);
  // Auto-refresh NinjaTrader status chip every 10s.
  setInterval(refreshNinjaTraderChip, 10000);
  // Active-run elapsed-time tick (visual only; status comes from poll).
  setInterval(tickActiveRunElapsed, 1000);
  }

  // If the workspace is empty (no submit yet this session), surface the
  // most recent reports so the operator has somewhere to click.
  updateRiskProfilePanel();
  loadRecentReports();
}

// ---------------- catalog (strategies + instruments + presets) ------------

async function loadCatalog() {
  let cat;
  try { cat = await api.get("/api/catalog"); }
  catch (e) {
    showCatalogBanner("Не удалось загрузить каталог: " + e.message);
    return;
  }
  _catalog = cat;
  _frontByRoot = null;  // rebuild on next browser render
  updateStaleChip(cat.staleness);

  // 1) strategy dropdown
  renderStrategySelect();
  /*
  const sel = document.getElementById("f-class");
  sel.replaceChildren();
  (cat.strategies || []).forEach(s => {
    const o = document.createElement("option");
    o.value = s.class_name;
    o.textContent = s.fallback ? `${s.class_name} (резерв)` : (s.display_name || s.class_name);
    sel.appendChild(o);
  });
  // pick first by default and render its params
  if (sel.options.length > 0) {
    sel.selectedIndex = 0;
    onStrategyChange();
  }
  */

  // 2) instrument basket: groups + instruments + selected. Default basket
  //    holds MNQ 06-26 (or first available) so the single-instrument
  //    workflow keeps working with one click.
  initBasket();
  if (_basket.length === 0) {
    const has = (cat.instruments || []).find(i => i.instrument === "MNQ 06-26");
    if (has) _basket.push("MNQ 06-26");
    else if (cat.instruments && cat.instruments[0]) _basket.push(cat.instruments[0].instrument);
    renderBasket();
  }
  renderInstrumentBrowser();
  // Phase 22e — initialize the second left-panel tab (Strategy Profiles).
  initLeftTabs();
  // Group warning is now surfaced via /api/catalog warnings + status-strip;
  // legacy basket-warn block removed.

  // 3) timeframe presets
  const presetsBox = document.getElementById("tf-presets");
  presetsBox.replaceChildren();
  (cat.timeframes?.presets || []).forEach(p => {
    const b = el("button", { text: p.label });
    b.type = "button";
    b.dataset.type = p.type;
    b.dataset.value = String(p.value);
    b.addEventListener("click", () => applyTimeframePreset(p));
    presetsBox.appendChild(b);
  });
  // mark current preset (1 Minute) active by default
  highlightActiveTimeframe();
  document.getElementById("f-tf-type").addEventListener("change",  highlightActiveTimeframe);
  document.getElementById("f-tf-value").addEventListener("input",  highlightActiveTimeframe);

  // date period quick-select buttons
  document.querySelectorAll("#date-presets button[data-period]").forEach(b =>
    b.addEventListener("click", () => applyDatePreset(b.dataset.period)));

  // 4) commission templates dropdown — bridge applies any supported template.
  const cSel  = document.getElementById("f-commission-template");
  const cHint = document.getElementById("f-commission-hint");
  cSel.replaceChildren();
  (cat.commission_templates || []).forEach(t => {
    const o = document.createElement("option");
    o.value = t.name;
    o.textContent = t.supported ? (t.display || t.name)
                                : `${t.display || t.name} (не поддерживается)`;
    if (!t.supported) o.disabled = true;
    cSel.appendChild(o);
  });
  const defaultTemplate = cat.execution_defaults?.commission_template || "None";
  cSel.value = defaultTemplate;
  if (!cSel.value) cSel.value = "None";
  const unsupportedNames = (cat.commission_templates || [])
    .filter(t => !t.supported && t.name !== "None")
    .map(t => t.name);
  cHint.textContent = unsupportedNames.length
    ? `Шаблон будет применён bridge при запуске. Не поддерживаются: ${unsupportedNames.join(", ")}.`
    : "Шаблон комиссии будет применён bridge при запуске бэктеста.";
  // Commission status chip:
  //   - all templates supported            -> hide chip (нет проблемы)
  //   - some XML templates unsupported     -> warn with count
  //   - only "None" exists / nothing real  -> warn "Доступен только None"
  const allTmpls = (cat.commission_templates || []);
  const realTmpls = allTmpls.filter(t => t.name !== "None");
  const unsupportedReal = realTmpls.filter(t => !t.supported);
  let chipMsg = "", chipKind = null;
  if (realTmpls.length === 0) {
    chipMsg = "Комиссии: доступен только None";
    chipKind = "warn";
  } else if (unsupportedReal.length > 0) {
    chipMsg = `Комиссии: не поддерживаются ${unsupportedReal.length} шаблонов`;
    chipKind = "warn";
  }
  setStatusChip("ss-commission", chipMsg, chipKind);

  // 5) trading-hours dropdown (locked to CME US Index Futures RTH).
  const thSel = document.getElementById("f-thours");
  thSel.replaceChildren();
  const ths = (cat.trading_hours_templates || []);
  if (ths.length === 0) {
    const o = document.createElement("option");
    o.value = "CME US Index Futures RTH";
    o.textContent = "CME US Index Futures RTH";
    thSel.appendChild(o);
  } else {
    ths.forEach(t => {
      const o = document.createElement("option");
      o.value = t.name;
      o.textContent = t.supported ? t.display || t.name
                                  : `${t.display || t.name} (locked)`;
      if (!t.supported) o.disabled = true;
      thSel.appendChild(o);
    });
  }
  thSel.value = "CME US Index Futures RTH";

  // 6) catalog warnings → status chip (defensive normalization: even if
  //    backend ever returns raw English text, surface a short Russian form
  //    in the Run header and stash the full text for Diagnostics).
  if (Array.isArray(cat.warnings) && cat.warnings.length > 0) {
    _diagCatalogWarnings = cat.warnings.slice();
    const msg = summarizeCatalogWarnings(cat.warnings);
    if (msg) showCatalogBanner(msg); else hideCatalogBanner();
  } else {
    _diagCatalogWarnings = [];
    hideCatalogBanner();
  }
}

function renderStrategySelect() {
  const sel = document.getElementById("f-class");
  if (!sel || !_catalog) return;
  const previous = sel.value;
  const strategies = (_catalog.strategies || []);

  sel.replaceChildren();
  strategies.forEach(s => {
    const o = document.createElement("option");
    o.value = s.class_name;
    o.textContent = s.display_name || s.class_name;
    sel.appendChild(o);
  });

  if (sel.options.length === 0) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "Нет стратегий в каталоге NinjaTrader";
    sel.appendChild(o);
    sel.disabled = true;
  } else {
    sel.disabled = false;
    const preferred = [...sel.options].find(o => o.value === previous)
      || [...sel.options].find(o => o.value === "NTAMicroVwapRiskPilot")
      || sel.options[0];
    sel.value = preferred.value;
  }
  onStrategyChange();
}

let _diagCatalogWarnings = [];

function summarizeCatalogWarnings(warnings) {
  const norm = warnings.map(w => String(w || "")).filter(Boolean);
  const has = (re) => norm.some(w => re.test(w));
  const msgs = [];
  // NOTE: "instrument groups are heuristic" is informational, not a problem
  // requiring user action — it stays in Diagnostics only and is NOT surfaced
  // here. Same for the obsolete "commissions: only None" — replaced by the
  // dedicated ss-commission chip computed from supported flags.
  if (has(/strategies\.json/i)) {
    msgs.push("Каталог стратегий: bridge ещё не сканировал NinjaTrader.");
  }
  if (has(/instruments\.json/i)) {
    msgs.push("Каталог инструментов: bridge ещё не сканировал NinjaTrader.");
  }
  if (msgs.length === 0) return null;     // nothing actionable → hide chip
  if (msgs.length > 2) return "есть ограничения (см. Диагностику)";
  return msgs.join(" ");
}

function showCatalogBanner(msg) {
  setStatusChip("ss-catalog", "Каталог: " + msg, "warn");
}
function hideCatalogBanner() {
  setStatusChip("ss-catalog", "", null);
}
function setStatusChip(id, text, kind) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!text) { el.hidden = true; return; }
  el.hidden = false;
  el.textContent = text;
  el.classList.remove("ok", "warn", "bad");
  if (kind) el.classList.add(kind);
}

function applyTimeframePreset(p) {
  document.getElementById("f-tf-type").value  = p.type;
  document.getElementById("f-tf-value").value = String(p.value);
  highlightActiveTimeframe();
}

function applyDatePreset(period) {
  const today = new Date();
  const toVal  = today.toISOString().slice(0, 10);
  let from = new Date(today);
  if      (period === "1d") from.setDate(from.getDate() - 1);
  else if (period === "1w") from.setDate(from.getDate() - 7);
  else if (period === "1m") from.setMonth(from.getMonth() - 1);
  else if (period === "3m") from.setMonth(from.getMonth() - 3);
  else if (period === "1y") from.setFullYear(from.getFullYear() - 1);
  const fromVal = from.toISOString().slice(0, 10);
  document.getElementById("f-from-date").value = fromVal;
  document.getElementById("f-to-date").value   = toVal;
  document.querySelectorAll("#date-presets button").forEach(b =>
    b.classList.toggle("active", b.dataset.period === period));
}

// Phase 22c — accept "Open in backtest" prefill from /ui/trading.html.
// Reads strategy / instrument / timeframe / params from the URL query string,
// applies them to the form. Safe to call when no params are present (no-op).
function applyTradingPrefillFromURL() {
  let qp;
  try { qp = new URLSearchParams(window.location.search); }
  catch (_) { return; }
  const strategy   = qp.get("strategy");
  const instrument = qp.get("instrument");
  const timeframe  = qp.get("timeframe");
  const paramsRaw  = qp.get("params");
  const periodPreset = qp.get("period");
  if (!strategy && !instrument && !timeframe && !paramsRaw && !periodPreset) return;

  // 1) Strategy class — also rebuilds the param fields.
  if (strategy) {
    const sel = document.getElementById("f-class");
    if (sel) {
      const opt = [...sel.options].find(o => o.value === strategy);
      if (opt) {
        sel.value = strategy;
        onStrategyChange();   // rebuild param fields with defaults
      } else {
        console.warn("Trading prefill: strategy not in catalog:", strategy);
      }
    }
  }

  // 2) Instrument basket — single contract from the runtime instance.
  if (instrument) {
    _basket = [instrument];
    try { renderBasket(); } catch (e) { console.warn("renderBasket:", e); }
  }

  // 3) Timeframe — parse "5 Minute" / "1 Hour" / "30 Second" / "Day".
  if (timeframe) {
    const m = String(timeframe).trim().match(/^(\d+)\s+(\w+)$/);
    let type = null, value = null;
    if (m) { value = parseInt(m[1], 10); type = m[2]; }
    else if (/^(day|tick|volume|second|minute)$/i.test(timeframe.trim())) {
      type = timeframe.trim().charAt(0).toUpperCase() + timeframe.trim().slice(1).toLowerCase();
      value = 1;
    }
    if (type) {
      const tEl = document.getElementById("f-tf-type");
      const vEl = document.getElementById("f-tf-value");
      if (tEl) {
        // Map common aliases → canonical NT period type
        const canon = type.charAt(0).toUpperCase() + type.slice(1).toLowerCase();
        if ([...tEl.options].some(o => o.value === canon)) tEl.value = canon;
      }
      if (vEl && value != null) vEl.value = String(value);
      try { highlightActiveTimeframe(); } catch (_) {}
    }
  }

  // 3b) Short date preset for "Проверить" from Strategies.
  if (periodPreset && ["1d", "1w", "1m", "3m", "1y"].includes(periodPreset)) {
    try { applyDatePreset(periodPreset); } catch (_) {}
  }

  // 4) Params — JSON-encoded snapshot of NT instance parameters. Apply by
  //    matching data-param-name on the rebuilt #strategy-params inputs.
  if (paramsRaw) {
    let obj = null;
    try { obj = JSON.parse(paramsRaw); }
    catch (e) { console.warn("Trading prefill: bad params JSON:", e); }
    if (obj && typeof obj === "object") {
      // Phase 22d — silently apply matched params; skipped ones are NT base/UI
      // properties (BarsRequiredToTrade, IsAutoScale, Panel, ...) that are
      // either already covered by the catalog or have no effect on backtest
      // behavior. The previous "applied N, skipped M" banner was misleading.
      Object.keys(obj).forEach(k => {
        const inp = document.querySelector(
          '#strategy-params [data-param-name="' + cssEscape(k) + '"]');
        if (!inp) return;
        const kind = inp.dataset.paramKind;
        const v = obj[k];
        if (kind === "bool") inp.checked = !!v;
        else                 inp.value = String(v == null ? "" : v);
      });
    }
  }
}

// Minimal CSS.escape polyfill (sufficient for parameter names).
function cssEscape(s) {
  if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(s);
  return String(s).replace(/[^a-zA-Z0-9_-]/g, ch => "\\" + ch);
}

function highlightActiveTimeframe() {
  const t = document.getElementById("f-tf-type").value;
  const v = document.getElementById("f-tf-value").value;
  document.querySelectorAll("#tf-presets button").forEach(b => {
    b.classList.toggle("active", b.dataset.type === t && b.dataset.value === v);
  });
}

function onInstrumentChange() {
  // No-op: kept as an exported name in case any old listener fires. The
  // basket widget mutates state directly via add/remove handlers.
}

// ============================================================================
// Instrument basket (Run tab) — groups + instruments + selected.
// ============================================================================

let _basket = [];                 // selected contract symbols, in order
let _activeGroup = null;          // currently open group_name (or null = "All")
let _basketSearchQuery = "";      // search inside the instruments column
let _basketOnlyCurrent = true;    // toggle: hide expired contracts
let _basketCollapsed = false;

function initBasket() {
  // Wire the static buttons / inputs.
  const search = document.getElementById("basket-instr-search");
  if (search) {
    search.addEventListener("input", () => {
      _basketSearchQuery = search.value;
      renderBasketInstruments();
    });
  }
  const addGroupBtn = document.getElementById("basket-add-group");
  if (addGroupBtn) {
    addGroupBtn.addEventListener("click", () => {
      if (!_activeGroup) return;
      const grp = (_catalog?.instrument_groups?.groups || [])
        .find(g => g.group_name === _activeGroup);
      if (!grp) return;
      // Respect the only-current toggle when adding the whole group.
      const src = _basketOnlyCurrent
        ? (grp.current_instruments || grp.instruments || [])
        : (grp.instruments || []);
      const wouldBe = new Set(_basket);
      for (const ins of src) wouldBe.add(ins);
      if (wouldBe.size > 50) {
        alert(`Лимит корзины — 50 инструментов. Группа даёт ${src.length}, в корзине уже ${_basket.length}.`);
        return;
      }
      if (src.length > 20 && !confirm(
          `Добавить ${src.length} инструментов из группы ${groupLabel(grp.group_name)}?\n` +
          `Это запустит ${src.length} отдельных бэктест-задач.`)) return;
      for (const ins of src) addToBasket(ins);
      renderBasket();
    });
  }
  const clearBtn = document.getElementById("basket-clear");
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      _basket = [];
      renderBasket();
    });
  }
  const onlyCur = document.getElementById("basket-only-current");
  if (onlyCur) {
    _basketOnlyCurrent = onlyCur.checked;
    onlyCur.addEventListener("change", () => {
      _basketOnlyCurrent = onlyCur.checked;
      renderBasketGroups();
      renderBasketInstruments();
    });
  }
  const toggleBtn = document.getElementById("basket-toggle-btn");
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      _basketCollapsed = !_basketCollapsed;
      const wid = document.getElementById("basket-widget");
      if (wid) wid.classList.toggle("collapsed", _basketCollapsed);
      toggleBtn.textContent = _basketCollapsed ? "▶" : "▼";
    });
  }
  renderBasketGroups();
  renderBasketInstruments();
  renderBasketSelected();
}

function addToBasket(name) {
  if (!name) return;
  if (_basket.includes(name)) return;
  if (_basket.length >= 50) return;  // backend hard cap
  _basket.push(name);
}

function removeFromBasket(name) {
  _basket = _basket.filter(x => x !== name);
}

function renderBasket() {
  renderBasketSelected();
  renderBasketInstruments();   // re-render so the [+] buttons disable
  renderInstrumentBrowser();   // keep left sidebar +/✓ in sync
  updateRiskProfilePanel();
}

// =====================================================================
// Instrument browser (left sidebar) — independent table over the same
// _basket state. Filters by group / search / tick value range / current
// contracts / minute data availability. "+" buttons add into _basket.
// =====================================================================
let _ib = {
  search: "",
  group: "all",
  tickMin: null,
  tickMax: null,
  onlyCurrent: true,
  showAllExpiries: false,
  initialized: false,
};

// Per-root front contract resolved from catalog. Built lazily; key=root, value=instrument name.
let _frontByRoot = null;

// "MM-YY" -> integer key YYYYMM (assumes 20YY). Returns null if invalid.
function expiryKey(exp) {
  if (!exp || typeof exp !== "string") return null;
  const m = /^(\d{2})-(\d{2})$/.exec(exp);
  if (!m) return null;
  const mm = parseInt(m[1], 10);
  const yy = parseInt(m[2], 10);
  if (mm < 1 || mm > 12) return null;
  return (2000 + yy) * 100 + mm;
}

function currentExpiryKey() {
  const d = new Date();
  return d.getFullYear() * 100 + (d.getMonth() + 1);
}

// Pick one current/front contract per root: smallest expiry >= current month.
// If no future contract exists, fall back to the latest past expiry.
function buildFrontByRoot() {
  _frontByRoot = {};
  const all = (_catalog && _catalog.instruments) || [];
  const cur = currentExpiryKey();
  const byRoot = {};
  for (const r of all) {
    const k = expiryKey(r.expiry);
    if (k == null) continue;
    const root = r.root || r.instrument.split(" ")[0];
    if (!byRoot[root]) byRoot[root] = [];
    byRoot[root].push({ name: r.instrument, key: k });
  }
  for (const root of Object.keys(byRoot)) {
    const list = byRoot[root].sort((a, b) => a.key - b.key);
    const front = list.find(x => x.key >= cur) || list[list.length - 1];
    if (front) _frontByRoot[root] = front.name;
  }
}

function isRootRecord(row) {
  // Root/master record: no space (no expiry suffix) AND not a 6-letter forex pair.
  if (!row || !row.instrument) return false;
  if (row.expiry) return false;
  const n = row.instrument;
  if (n.includes(" ")) return false;
  if (/^[A-Z]{6}$/.test(n)) return false; // forex
  return true;
}

function isFrontContract(row) {
  if (!_frontByRoot) buildFrontByRoot();
  const root = row.root || (row.instrument || "").split(" ")[0];
  return _frontByRoot[root] === row.instrument;
}

function isExpiredContract(row) {
  const k = expiryKey(row.expiry);
  if (k == null) return false;
  return k < currentExpiryKey();
}

function fmtTick(v) {
  if (v == null || isNaN(v)) return "—";
  return v.toFixed(2).replace(/\.?0+$/, m => m === "" ? "" : m);
}
function fmtMoney(v) {
  if (v == null || isNaN(v)) return "—";
  return "$" + v.toFixed(2);
}

// Phase 23 — display all timestamps in Pacific Time (same timezone as the clock chip).
const _PT_FMT_SHORT = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "America/Los_Angeles",
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", hour12: false
});
function _fmtCreated(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    if (isNaN(d)) return String(ts).slice(0, 16);
    // sv-SE locale gives "YYYY-MM-DD HH:MM" format — exactly what we need
    return _PT_FMT_SHORT.format(d) + " PT";
  } catch { return String(ts).slice(0, 16); }
}

function _fmtDatePT(isoStr) {
  if (!isoStr) return "—";
  try {
    const d = new Date(isoStr);
    if (isNaN(d)) return isoStr.slice(0,10);
    return new Intl.DateTimeFormat("sv-SE", {
      timeZone: "America/Los_Angeles",
      year:"numeric", month:"2-digit", day:"2-digit"
    }).format(d);
  } catch { return isoStr.slice(0,10); }
}

// ─────────────────────────────────────────────────────────────────────────────
// Backtest confidence model (Phase 22k).
// The table shows confidence_score only: statistical trust in the data sample.
// Profitability and quality metrics are shown in the tooltip as result context,
// but they do not lower confidence just because the strategy lost money.
// ─────────────────────────────────────────────────────────────────────────────
const TARGET_TRADES_PER_DAY = 2.0;

function computeBacktestAssessment(item) {
  const confidence_score = computeConfidenceScore(item);
  const quality_verdict = computeQualityVerdict(item);
  return { confidence_score, quality_verdict };
}

function computeConfidence(item) {
  return computeBacktestAssessment(item).confidence_score;
}

function computeConfidenceScore(item) {
  if (!item) {
    return { score: 0, level: "insufficient", label: "НЕТ ДАННЫХ", cssClass: "insufficient", reasons: ["нет данных"], trade_expectation: null, data_quality: null };
  }
  const isFinished = (item.kind === "batch") || (item.status === "done");
  if (!isFinished || item.trades == null || item.trades === 0) {
    return { score: 0, level: "insufficient", label: "НЕТ ДАННЫХ", cssClass: "insufficient", reasons: ["нет данных или 0 сделок"], trade_expectation: null, data_quality: null };
  }
  const N = Number(item.trades) || 0;
  const tradeExpectation = computeTradeExpectation(item, N);
  const dataQuality = computeConfidenceDataQuality(item, tradeExpectation);
  let score = tradeExpectation.sample_score + dataQuality.adjustment;
  if (N < 5) score = Math.min(score, 18);
  else if (N < 10) score = Math.min(score, 28);
  else if (N < 20) score = Math.min(score, 42);
  else if (N < 50) score = Math.min(score, 65);
  if (tradeExpectation.overtrade_warning) score = Math.min(score, 92);
  score = Math.max(0, Math.min(100, Math.round(score)));
  let level = "very_low";
  if (score >= 75) level = "high";
  else if (score >= 45) level = "medium";
  else if (score >= 25) level = "low";
  const reasons = tradeExpectation.reasons.slice();
  if (N < 20) reasons.push("меньше 20 сделок — статистическая база мала");
  if (dataQuality.reasons.length) reasons.push(...dataQuality.reasons);
  const label = _confidenceLabel(level);
  const cssClass = _confidenceClass(level, tradeExpectation);
  return { score, level, label, cssClass, reasons, trade_expectation: tradeExpectation, data_quality: dataQuality };
}

function computeQualityVerdict(item) {
  if (!item) {
    return { score: 0, verdict: "unknown", reasons: ["нет данных"], metrics: {} };
  }
  const isFinished = (item.kind === "batch") || (item.status === "done");
  if (!isFinished || item.trades == null || item.trades === 0) {
    return { score: 0, verdict: "unknown", reasons: ["нет данных или 0 сделок"], metrics: {} };
  }

  const reasons = [];
  const np = _metricNumber(item, "net_profit_after_commission", "net_profit");
  const pf = _profitFactorFromItem(item);
  const ddRaw = _metricNumber(item, "max_drawdown_after_commission", "max_drawdown");
  const wr = _metricNumber(item, "winning_pct");
  const dd = ddRaw != null ? Math.abs(ddRaw) : null;
  const metrics = { net_profit: np, profit_factor: pf, max_drawdown: ddRaw, winning_pct: wr };

  if (np == null && pf == null) {
    return { score: 0, verdict: "unknown", reasons: ["нет PnL/PF для оценки качества"], metrics };
  }
  if ((np != null && np <= 0) || (pf != null && pf < 1.0)) {
    if (np != null && np <= 0) reasons.push("результат отрицательный");
    if (pf != null && pf < 1.0) reasons.push("PF ниже 1.0");
    return { score: 20, verdict: "losing", reasons, metrics };
  }

  let score = 45;
  let verdict = "weak";
  if (pf != null) {
    if      (pf >= 2.0) { score = 90; verdict = "excellent"; }
    else if (pf >= 1.5) { score = 78; verdict = "good"; }
    else if (pf >= 1.2) { score = 62; verdict = "medium"; reasons.push(`PF=${pf.toFixed(2)} средний`); }
    else                { score = 42; verdict = "weak"; reasons.push(`PF=${pf.toFixed(2)} слабый`); }
  } else if (np != null && np > 0) {
    score = 55;
    verdict = "medium";
    reasons.push("PF отсутствует — качество оценивается осторожно");
  }
  if (dd != null && np != null && np > 0) {
    const ratio = dd / np;
    metrics.drawdown_to_net = ratio;
    if      (ratio <= 0.50) { score += 4; }
    else if (ratio <= 1.00) { score -= 6; reasons.push(`DD/Net=${ratio.toFixed(2)}`); }
    else                    { score -= 18; reasons.push(`просадка выше прибыли (DD/Net=${ratio.toFixed(2)})`); }
  }
  if (wr != null && (wr < 25 || wr > 80)) {
    score -= 6;
    reasons.push(`нетипичный win-rate ${wr.toFixed(0)}%`);
  }

  score = Math.max(0, Math.min(100, Math.round(score)));
  if (score >= 85) verdict = "excellent";
  else if (score >= 70) verdict = "good";
  else if (score >= 55) verdict = "medium";
  else verdict = "weak";
  return { score, verdict, reasons, metrics };
}

function computeTradeExpectation(item, trades) {
  const target = _targetTradesPerDay(item);
  const days = _periodTradingDays(item && item.period);
  const reasons = [];
  if (days != null && days > 0) {
    const expected = Math.max(1, days * target);
    const ratio = trades / expected;
    const tradesPerDay = trades / days;
    let sampleScore;
    let band = "";
    let active_note = false;
    let overtrade_warning = false;
    if (tradesPerDay <= 0) {
      sampleScore = 0;
      band = "нет сделок";
    } else if (tradesPerDay < 0.5) {
      sampleScore = 10 + (tradesPerDay / 0.5) * 15;
      band = "очень низкая частота";
      reasons.push(`меньше 0.5 сделки/день (${tradesPerDay.toFixed(2)})`);
    } else if (tradesPerDay < 1.0) {
      sampleScore = 25 + ((tradesPerDay - 0.5) / 0.5) * 20;
      band = "низкая частота";
      reasons.push(`0.5–1 сделка/день (${tradesPerDay.toFixed(2)})`);
    } else if (tradesPerDay < 2.0) {
      sampleScore = 45 + ((tradesPerDay - 1.0) / 1.0) * 20;
      band = "средняя частота";
    } else if (tradesPerDay < 4.0) {
      sampleScore = 75 + ((tradesPerDay - 2.0) / 2.0) * 20;
      band = "хорошая частота";
    } else if (tradesPerDay <= 6.0) {
      sampleScore = 90 + ((tradesPerDay - 4.0) / 2.0) * 10;
      band = "высокая активность";
      active_note = true;
      reasons.push(`активная стратегия: ${tradesPerDay.toFixed(2)} сделок/день`);
    } else {
      sampleScore = 92;
      band = "очень высокая активность";
      overtrade_warning = true;
      reasons.push(`возможна переторговка: ${tradesPerDay.toFixed(2)} сделок/день`);
    }
    return {
      target_trades_per_day: target,
      trading_days: days,
      expected_trades: expected,
      actual_trades: trades,
      trades_per_day: tradesPerDay,
      trade_ratio: ratio,
      sample_score: Math.round(sampleScore),
      band,
      active_note,
      overtrade_warning,
      reasons,
    };
  }

  let sampleScore;
  if      (trades >= 200) sampleScore = 88;
  else if (trades >= 100) sampleScore = 82;
  else if (trades >= 50)  sampleScore = 62;
  else if (trades >= 20)  sampleScore = 38;
  else                    sampleScore = 18;
  reasons.push("неизвестен период теста — expected trades посчитать нельзя");
  return {
    target_trades_per_day: target,
    trading_days: null,
    expected_trades: null,
    actual_trades: trades,
    trades_per_day: null,
    trade_ratio: null,
    sample_score: sampleScore,
    band: "период неизвестен",
    active_note: false,
    overtrade_warning: false,
    reasons,
  };
}

function computeConfidenceDataQuality(item, tradeExpectation) {
  const reasons = [];
  let adjustment = 0;
  if (!tradeExpectation || tradeExpectation.trading_days == null) {
    adjustment -= 8;
  } else if (tradeExpectation.trading_days < 5) {
    adjustment -= 10;
    reasons.push(`очень короткий период: ${tradeExpectation.trading_days.toFixed(1)} торговых дней`);
  } else if (tradeExpectation.trading_days < 20) {
    adjustment -= 5;
    reasons.push(`короткий период: ${tradeExpectation.trading_days.toFixed(1)} торговых дней`);
  }

  const checks = [
    { ok: item.winning_pct != null, name: "Win %" },
    { ok: _metricNumber(item, "net_profit_after_commission", "net_profit") != null, name: "Net Profit" },
    { ok: _profitFactorFromItem(item) != null, name: "PF" },
    { ok: _metricNumber(item, "max_drawdown_after_commission", "max_drawdown") != null, name: "Max DD" },
  ];
  const present = checks.filter(x => x.ok).length;
  const missing = checks.filter(x => !x.ok).map(x => x.name);
  if (present === checks.length) {
    adjustment += 3;
  } else if (present >= 2) {
    adjustment -= 4;
    reasons.push(`часть метрик отсутствует: ${missing.join(", ")}`);
  } else {
    adjustment -= 10;
    reasons.push(`мало метрик результата: ${missing.join(", ")}`);
  }
  return { adjustment, present_metrics: present, total_metrics: checks.length, missing_metrics: missing, reasons };
}

function _targetTradesPerDay(item) {
  const raw = item && (item.target_trades_per_day ?? item.TargetTradesPerDay);
  const v = raw != null ? Number(raw) : TARGET_TRADES_PER_DAY;
  return Number.isFinite(v) && v > 0 ? v : TARGET_TRADES_PER_DAY;
}

function _metricNumber(item, ...keys) {
  for (const k of keys) {
    if (item[k] == null) continue;
    const v = Number(item[k]);
    if (!Number.isNaN(v) && Number.isFinite(v)) return v;
  }
  return null;
}

function _profitFactorFromItem(item) {
  const direct = _metricNumber(item, "profit_factor_after_commission", "profit_factor");
  if (direct != null) return direct;
  for (const k of ["profit_factor_after_commission", "profit_factor"]) {
    const raw = item && item[k];
    if (raw === "∞" || raw === "Infinity" || raw === "inf") return Infinity;
  }
  const gp = _metricNumber(item, "gross_profit_after_commission", "gross_profit");
  const gl = _metricNumber(item, "gross_loss_after_commission", "gross_loss");
  if (gp == null || gl == null) return null;
  if (gl < 0) return gp / Math.abs(gl);
  if (gl === 0 && gp > 0) return Infinity;
  return null;
}

function _fmtProfitFactor(pf) {
  if (pf == null) return "—";
  if (pf === Infinity) return "∞";
  return Number(pf).toFixed(2);
}

function _periodMonths(period) {
  if (!period || !period.from_utc || !period.to_utc) return null;
  const a = Date.parse(period.from_utc);
  const b = Date.parse(period.to_utc);
  if (!isFinite(a) || !isFinite(b) || b <= a) return null;
  return (b - a) / (1000 * 60 * 60 * 24 * 30.4375);
}

function _periodTradingDays(period) {
  if (!period || !period.from_utc || !period.to_utc) return null;
  const a = new Date(period.from_utc), b = new Date(period.to_utc);
  if (!isFinite(a) || !isFinite(b) || b <= a) return null;
  // Approx: 5 trading days per 7 calendar days.
  const cal = (b - a) / (1000 * 60 * 60 * 24);
  return cal * (5 / 7);
}

const _CONF_LEVEL_LABEL = {
  high: "ВЫСОКОЕ",
  medium: "СРЕДНЕЕ",
  low: "НИЗКОЕ",
  very_low: "ОЧЕНЬ НИЗКОЕ",
  insufficient: "НЕТ ДАННЫХ",
};

const _QUALITY_VERDICT_LABEL = {
  excellent: "отличный результат",
  good: "хороший результат",
  medium: "средний результат",
  weak: "слабый результат",
  losing: "убыточный результат",
  unknown: "качество не оценено",
};

function _confidenceLabel(level) {
  return _CONF_LEVEL_LABEL[level] || level || "—";
}

function _confidenceClass(level, tradeExpectation) {
  if (level === "high") return tradeExpectation && tradeExpectation.active_note ? "excellent" : "good";
  if (level === "medium") return "medium";
  if (level === "low") return "weak";
  if (level === "very_low") return "low";
  return "insufficient";
}

function renderConfidenceBadge(item) {
  const td = el("td", { cls: "col-confidence" });
  const assessment = computeBacktestAssessment(item);
  const c = assessment.confidence_score;
  const span = el("span");
  span.className = "confidence-badge " + c.cssClass;
  span.textContent = `${c.score}% · ${c.label}`;
  span.title = buildBacktestRatingTooltip(assessment);
  td.appendChild(span);
  return td;
}

function buildBacktestRatingTooltip(assessment) {
  const c = assessment.confidence_score;
  const q = assessment.quality_verdict;
  const te = c.trade_expectation;
  const lines = [
    `Доверие к данным: ${c.score}% · ${c.label}`,
    `Основа: размер выборки, период, частота сделок, полнота метрик`,
  ];
  if (te) {
    lines.push(`Период: ${te.trading_days != null ? te.trading_days.toFixed(1) + " торговых дней" : "н/д"}`);
    lines.push(`Ожидалось сделок: ${te.expected_trades != null ? Math.round(te.expected_trades) : "н/д"}`);
    lines.push(`Фактически сделок: ${te.actual_trades}`);
    lines.push(`Цель: ${te.target_trades_per_day.toFixed(1)} сделок/день`);
    lines.push(`Сделок/день: ${te.trades_per_day != null ? te.trades_per_day.toFixed(2) : "н/д"}`);
    lines.push(`Частота: ${te.trade_ratio != null ? te.trade_ratio.toFixed(2) + " от нормы" : "н/д"}`);
    if (te.trades_per_day != null) {
      const delta = te.trades_per_day - te.target_trades_per_day;
      lines.push(`Отклонение: ${delta >= 0 ? "+" : ""}${delta.toFixed(2)} сделок/день`);
    }
    lines.push(`Диапазон: ${te.band || "н/д"}`);
  }
  if (c.data_quality) {
    lines.push(`Метрики: ${c.data_quality.present_metrics}/${c.data_quality.total_metrics}`);
    if (c.data_quality.missing_metrics && c.data_quality.missing_metrics.length) {
      lines.push(`Нет метрик: ${c.data_quality.missing_metrics.join(", ")}`);
    }
  }
  lines.push(`Качество результата: ${_QUALITY_VERDICT_LABEL[q.verdict] || q.verdict} (не влияет на доверие)`);
  if (q.metrics) {
    if (q.metrics.net_profit != null) lines.push(`Итог: ${fmtMoneySign(q.metrics.net_profit)}`);
    if (q.metrics.profit_factor != null) lines.push(`PF: ${_fmtProfitFactor(q.metrics.profit_factor)}`);
    if (q.metrics.max_drawdown != null) lines.push(`Max DD: ${fmtMoneySign(q.metrics.max_drawdown)}`);
    if (q.metrics.winning_pct != null) lines.push(`Win %: ${q.metrics.winning_pct.toFixed(1)}%`);
  }
  const reasons = [...(c.reasons || [])];
  if (reasons.length) lines.push("Детали доверия:\n— " + [...new Set(reasons)].join("\n— "));
  if (q.reasons && q.reasons.length) {
    lines.push("Контекст результата:\n— " + [...new Set(q.reasons)].join("\n— "));
  }
  return lines.join("\n");
}

// Convert "MES 06-26" → "MES JUN 26" (NinjaTrader-style display format).
// DISPLAY ONLY — never use for basket keys or catalog lookups.
const _MONTH_ABBR = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"];
function fmtContract(name) {
  if (!name || typeof name !== "string") return name || "—";
  const m = /^(.+)\s+(\d{2})-(\d{2})$/.exec(name.trim());
  if (!m) return name;
  const mm = parseInt(m[2], 10);
  if (mm < 1 || mm > 12) return name;
  return `${m[1]} ${_MONTH_ABBR[mm - 1]} ${m[3]}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// TopStep virtual group: roots the user trades on TopStep.
// Matching is done by root symbol (prefix before space, e.g. "MES 06-26" → "MES").
// ─────────────────────────────────────────────────────────────────────────────
const TOPSTEP_ROOTS = new Set([
  // Crypto
  "MBT", "MET",
  // Micro Indexes
  "MES", "MNQ", "MYM", "M2K",
  // E-mini Indexes
  "RTY",
  // Energy (NYMEX)
  "MCL", "MNG", "RB", "HO",
  // Metals (COMEX)
  "MGC", "SIL", "MHG",
  // FX Futures
  "6A", "6B", "6C", "6E", "6J", "6S", "E7", "6M", "6N",
  // Livestock
  "HE", "LE",
  // Grains
  "ZC", "ZW", "ZS", "ZM", "ZL",
  // Interest Rates
  "ZT", "ZF", "ZN", "TN", "ZB", "UB",
]);
const TOPSTEP_GROUP_KEY = "__topstep__";

function isTopStepRoot(name) {
  if (!name) return false;
  const root = (name.split(" ")[0] || name).toUpperCase();
  return TOPSTEP_ROOTS.has(root);
}

// Map an instrument name -> group label by searching catalog groups.
function instrumentGroupOf(name) {
  const groups = (_catalog && _catalog.instrument_groups && _catalog.instrument_groups.groups) || [];
  for (const g of groups) {
    const all = (g.instruments || []);
    const cur = (g.current_instruments || []);
    if (all.includes(name) || cur.includes(name)) return g.group_name || g.name;
  }
  return null;
}

function isCurrentInstrument(name) {
  const groups = (_catalog && _catalog.instrument_groups && _catalog.instrument_groups.groups) || [];
  for (const g of groups) {
    if ((g.current_instruments || []).includes(name)) return true;
  }
  // Forex / no-expiry instruments have no group concept of "current" — treat as current.
  return !/\d{2}-\d{2}$/.test(name);
}

function initInstrumentBrowser() {
  if (_ib.initialized) return;
  _ib.initialized = true;

  const search = document.getElementById("ib-search");
  const group  = document.getElementById("ib-group");
  const tmin   = document.getElementById("ib-tick-min");
  const tmax   = document.getElementById("ib-tick-max");
  const cur    = document.getElementById("ib-only-current");
  const allExp = document.getElementById("ib-show-all-expiries");
  const addAll = document.getElementById("ib-add-all-btn");
  const toggle = document.getElementById("btn-instruments-toggle");

  const re = () => renderInstrumentBrowser();
  if (search) search.addEventListener("input",  () => { _ib.search = search.value; re(); });
  if (group)  group.addEventListener("change",  () => { _ib.group  = group.value; re(); });
  if (tmin)   tmin.addEventListener("input",    () => { _ib.tickMin = tmin.value === "" ? null : parseFloat(tmin.value); re(); });
  if (tmax)   tmax.addEventListener("input",    () => { _ib.tickMax = tmax.value === "" ? null : parseFloat(tmax.value); re(); });
  if (cur)    cur.addEventListener("change",    () => { _ib.onlyCurrent = cur.checked; re(); });
  if (allExp) allExp.addEventListener("change", () => { _ib.showAllExpiries = allExp.checked; re(); });

  if (addAll) {
    addAll.addEventListener("click", () => {
      // Collect visible instruments from rendered table rows.
      const tbody = document.getElementById("ib-tbody");
      if (!tbody) return;
      const names = Array.from(tbody.querySelectorAll("tr[data-instrument]"))
        .map(tr => tr.dataset.instrument).filter(Boolean);
      if (!names.length) return;
      const wouldBe = new Set(_basket);
      for (const n of names) wouldBe.add(n);
      if (wouldBe.size > 50) {
        alert(`Лимит корзины — 50 инструментов. Видимых: ${names.length}, в корзине уже: ${_basket.length}.`);
        return;
      }
      if (names.length > 10 && !confirm(`Добавить ${names.length} инструментов в корзину?`)) return;
      for (const n of names) addToBasket(n);
      renderBasket();
    });
  }

  if (toggle) {
    toggle.addEventListener("click", () => {
      const wb = document.getElementById("workbench");
      if (!wb) return;
      const hidden = wb.classList.toggle("no-instruments");
      storageSet("ib_hidden", hidden ? "1" : "0");
    });
    try {
      if (storageGet("ib_hidden") === "1") {
        document.getElementById("workbench")?.classList.add("no-instruments");
      }
    } catch {}
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase 22e — left-panel tabs (Инструменты / Лучшие профили).
// Profiles are loaded once on first activation and cached in memory.
// ─────────────────────────────────────────────────────────────────────────────
let _profilesState = { loaded: false, data: null, search: "", statusFilter: "all" };
let _favoritesState = { loaded: false, data: null, search: "", pending: new Map(), repeating: new Set() };

function initLeftTabs() {
  const tabs = document.querySelectorAll(".left-tab[data-left-tab]");
  if (!tabs.length) return;
  tabs.forEach(btn => {
    if (btn.dataset.wired === "1") return;
    btn.dataset.wired = "1";
    btn.addEventListener("click", () => activateLeftTab(btn.dataset.leftTab));
  });
  // Profiles search/filter listeners.
  const ps = document.getElementById("prof-search");
  const pf = document.getElementById("prof-status-filter");
  const pr = document.getElementById("prof-refresh");
  if (ps && ps.dataset.wired !== "1") {
    ps.dataset.wired = "1";
    ps.addEventListener("input", () => { _profilesState.search = ps.value; renderProfilesList(); });
  }
  if (pf && pf.dataset.wired !== "1") {
    pf.dataset.wired = "1";
    pf.addEventListener("change", () => { _profilesState.statusFilter = pf.value; renderProfilesList(); });
  }
  if (pr && pr.dataset.wired !== "1") {
    pr.dataset.wired = "1";
    pr.addEventListener("click", () => { _profilesState.loaded = false; loadProfiles(); });
  }
  const fs = document.getElementById("fav-search");
  const fr = document.getElementById("fav-refresh");
  if (fs && fs.dataset.wired !== "1") {
    fs.dataset.wired = "1";
    fs.addEventListener("input", () => { _favoritesState.search = fs.value; renderFavoritesList(); });
  }
  if (fr && fr.dataset.wired !== "1") {
    fr.dataset.wired = "1";
    fr.addEventListener("click", () => loadReportFavorites({ force: true, validate: true }));
  }
}

function activateLeftTab(name) {
  document.querySelectorAll(".left-tab[data-left-tab]").forEach(btn => {
    const active = btn.dataset.leftTab === name;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  const paneInst = document.getElementById("left-pane-instruments");
  const paneProf = document.getElementById("left-pane-profiles");
  const paneCov  = document.getElementById("left-pane-coverage");
  const paneFav  = document.getElementById("left-pane-favorites");
  if (paneInst) paneInst.hidden = (name !== "instruments");
  if (paneProf) paneProf.hidden = (name !== "profiles");
  if (paneCov)  paneCov.hidden  = (name !== "coverage");
  if (paneFav)  paneFav.hidden  = (name !== "favorites");
  if (name === "profiles" && !_profilesState.loaded) loadProfiles();
  if (name === "coverage") loadCoverage();
  if (name === "favorites" && !_favoritesState.loaded) loadReportFavorites({ validate: false });
}

// ─── Coverage tab (Phase 24) ───────────────────────────────────────────
let _coverageState = {
  loaded: false,
  data: null,
  profilesData: null,
  catalogClasses: new Set(),
  runtimeRows: [],
  statusFilter: "all",
  expanded: new Set(),
};

async function loadCoverage() {
  try {
    const [covRes, profRes, catRes, rtRes] = await Promise.allSettled([
      api.get("/api/coverage"),
      api.get("/api/profiles"),
      api.get("/api/catalog"),
      api.get("/api/ops/runtime/strategies"),
    ]);
    if (covRes.status !== "fulfilled") throw covRes.reason;
    const data = covRes.value;
    _coverageState.data = data;
    if (profRes.status === "fulfilled") {
      _coverageState.profilesData = profRes.value;
      _profilesState.data = profRes.value;
      _profilesState.loaded = true;
    }
    if (catRes.status === "fulfilled") {
      const raw = Array.isArray(catRes.value?.strategies)
        ? catRes.value.strategies
        : (Array.isArray(catRes.value?.strategies?.strategies) ? catRes.value.strategies.strategies : []);
      _coverageState.catalogClasses = new Set(raw.map(s => s && s.class_name).filter(Boolean));
    }
    if (rtRes.status === "fulfilled") {
      _coverageState.runtimeRows = Array.isArray(rtRes.value?.strategies) ? rtRes.value.strategies : [];
    }
    _coverageState.loaded = true;
    renderCoverage();
  } catch (e) {
    const tb = document.getElementById("cov-tbody");
    if (tb) tb.innerHTML = `<tr><td colspan="5" class="muted small" style="padding:10px;color:#f87171;">Ошибка: ${e.message}</td></tr>`;
  }
}

const _COV_BADGE = {
  ready:       { cls: "ok",   emoji: "✅", label: "Готова" },
  in_progress: { cls: "info", emoji: "",   label: "В процессе" },
};

const _COV_STATUS_ORDER = {
  ready: 0,
  in_progress: 1,
};

function _covStatus(status) {
  return ["ready", "paper_ready"].includes(String(status || "")) ? "ready" : "in_progress";
}

const _COVERAGE_TARGETS = {
  trades_per_day: 3,
  monthly_profit: 2000,
  trading_days_per_week: 5,
  average_days_per_month: 30.4375,
};

function _contractRoot(value) {
  const s = String(value || "").trim().toUpperCase();
  const m = s.match(/^([A-Z0-9]+)/);
  return m ? m[1] : "";
}

function _profileRoot(p) {
  return _contractRoot(p && (p.instrument || p.current_contract || p.root));
}

function _profileEvidenceIds(p) {
  const ids = [];
  if (p && p.last_job_id) ids.push(p.last_job_id);
  const ev = p && Array.isArray(p.evidence_job_ids) ? p.evidence_job_ids : [];
  for (const id of ev) {
    if (id && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

function _profilesForRoot(root) {
  const data = _coverageState.profilesData || _profilesState.data || {};
  const profiles = Array.isArray(data.profiles) ? data.profiles : [];
  const r = String(root || "").toUpperCase();
  return profiles
    .filter(p => _profileRoot(p) === r)
    .sort((a, b) => {
      const ar = _COV_STATUS_ORDER[_covStatus(a.status)] ?? 9;
      const br = _COV_STATUS_ORDER[_covStatus(b.status)] ?? 9;
      if (ar !== br) return ar - br;
      return String(a.name || a.profile_id || "").localeCompare(String(b.name || b.profile_id || ""), "ru");
    });
}

function _coverageCounts(profiles, fallbackTotal) {
  const counts = {
    total: profiles.length || Number(fallbackTotal || 0),
    ready: 0,
    in_progress: 0,
    paper_ready: 0,
    paper_candidate: 0,
    research_baseline: 0,
    rejected: 0,
    archived: 0,
    available: 0,
    approved_available: 0,
    runtime_enabled: 0,
  };
  const catalog = _coverageState.catalogClasses || new Set();
  for (const p of profiles) {
    const available = !!(p.strategy_class && catalog.has(p.strategy_class));
    const displayStatus = _covStatus(p.status);
    const live = displayStatus === "ready" && _profileOnlineOk(p);
    counts[displayStatus] += 1;
    if (counts[p.status] != null) counts[p.status] += 1;
    if (available) counts.available += 1;
    if (available && displayStatus === "ready") counts.approved_available += 1;
    if (live) counts.runtime_enabled += 1;
  }
  return counts;
}

function _coverageCountsForRow(row, profiles) {
  const local = _coverageCounts(profiles, row && row.strategy_count);
  const server = (row && row.status_counts) || {};
  return Object.assign({}, local, server, {
    runtime_enabled: local.runtime_enabled,
  });
}

function _profileRuntimeMatches(p) {
  const rows = _coverageState.runtimeRows || [];
  const classes = _profileRuntimeClassSet(p);
  const strategyId = String(p?.runtime_strategy_id || "").toLowerCase();
  const root = _profileRoot(p);
  return rows.filter(row => {
    const r = row && (row.runtime || row);
    const rcls = String(r.strategy_class || r.strategy_name || "").toLowerCase();
    const rsid = String(row?.strategy_id || r?.strategy_id || "").toLowerCase();
    const rr = _contractRoot(r.instrument || r.contract_month || "");
    const classMatch = classes.has(rcls);
    const idMatch = strategyId && rsid === strategyId;
    return (classMatch || idMatch) && (!root || rr === root);
  });
}

function _profileRuntimeClassSet(p) {
  const out = new Set();
  const add = (v) => {
    const s = String(v || "").trim().toLowerCase();
    if (s) out.add(s);
  };
  add(p?.strategy_class);
  add(p?.deploy_strategy_class);
  if (Array.isArray(p?.runtime_strategy_classes)) {
    p.runtime_strategy_classes.forEach(add);
  }
  if (p?.profile_id === "sev2_mgc_vwappullback_shortonly_paper_v1") {
    add("VWAPPullbackMGC5mV1");
  }
  return out;
}

function _runtimeRecord(row) {
  return row && (row.runtime || row);
}

function _runtimeRowEnabled(row) {
  const r = _runtimeRecord(row);
  return !!(row?.runtime_enabled || r?.enabled);
}

function _runtimeRowParamsOk(row) {
  const r = _runtimeRecord(row);
  return !(row?.params_ok === false || r?.params_ok === false);
}

function _profileOnlineOk(p) {
  return _profileRuntimeMatches(p).some(row => _runtimeRowEnabled(row) && _runtimeRowParamsOk(row));
}

function _profileOnlineMismatch(p) {
  return _profileRuntimeMatches(p).some(row => _runtimeRowEnabled(row) && !_runtimeRowParamsOk(row));
}

function _profileRuntimeLabel(p) {
  const matches = _profileRuntimeMatches(p);
  if (!matches.length) return "не запущена";
  if (matches.some(row => _runtimeRowEnabled(row) && !_runtimeRowParamsOk(row))) {
    return "online: параметры отличаются";
  }
  if (matches.some(_runtimeRowEnabled)) return "online ok";
  return "найдена, выключена";
}

function _numOrNull(v) {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v !== "string") return null;
  let s = v.trim().replace(/\$/g, "").replace(/\s/g, "");
  if (!s) return null;
  if (s.includes(",") && s.includes(".")) s = s.replace(/,/g, "");
  else if (s.includes(",") && !s.includes(".")) s = s.replace(",", ".");
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function _profileMetric(p, names) {
  const m = (p && p.metrics) || {};
  for (const name of names) {
    const n = _numOrNull(m[name]);
    if (n != null) return n;
  }
  return null;
}

function _profilePeriodDays(p) {
  const per = (p && (p.test_period || p.period)) || {};
  const from = Date.parse(per.from_utc || per.from || per.start_utc || "");
  const to = Date.parse(per.to_utc || per.to || per.end_utc || "");
  if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return 0;
  return Math.max(1, (to - from) / 86400000);
}

function _profileGoalRate(p) {
  const days = _profilePeriodDays(p);
  const tradingDays = days > 0
    ? Math.max(1, days * (_COVERAGE_TARGETS.trading_days_per_week / 7))
    : 0;
  const months = days > 0
    ? Math.max(1, days / _COVERAGE_TARGETS.average_days_per_month)
    : 0;
  const trades = _profileMetric(p, ["trade_count", "trades", "total_trades"]) || 0;
  const net = _profileMetric(p, [
    "net_profit_after_commission",
    "adj_net",
    "net_profit",
    "net",
  ]) || 0;
  return {
    trades_per_day: tradingDays ? trades / tradingDays : 0,
    monthly_profit: months ? net / months : 0,
  };
}

function _sumGoalRates(profiles) {
  return (profiles || []).reduce((acc, p) => {
    const r = _profileGoalRate(p);
    acc.trades_per_day += r.trades_per_day;
    acc.monthly_profit += r.monthly_profit;
    return acc;
  }, { trades_per_day: 0, monthly_profit: 0 });
}

function _fmtGoalMoney(v) {
  const sign = v >= 0 ? "+" : "−";
  const n = Math.abs(v || 0);
  if (n >= 1000) return `${sign}$${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k/м`;
  return `${sign}$${n.toFixed(0)}/м`;
}

function _coverageGoalSummary(profiles) {
  const ready = (profiles || []).filter(p => _covStatus(p.status) === "ready");
  if (!ready.length) {
    return {
      state: "missing",
      title: "Цель считается только по готовым стратегиям.",
      top: "—",
      bottom: "нет ready",
    };
  }
  const onlineReady = ready.filter(_profileOnlineOk);
  const mismatch = ready.filter(_profileOnlineMismatch);
  const planned = _sumGoalRates(ready);
  const live = _sumGoalRates(onlineReady);
  const basis = onlineReady.length ? live : planned;
  const met = onlineReady.length > 0
    && basis.trades_per_day >= _COVERAGE_TARGETS.trades_per_day
    && basis.monthly_profit >= _COVERAGE_TARGETS.monthly_profit;
  const state = mismatch.length
    ? "error"
    : (onlineReady.length === ready.length ? "online-ok" : (onlineReady.length ? "warn" : "missing"));
  const top = mismatch.length
    ? `парам. ${mismatch.length}/${ready.length}`
    : onlineReady.length
    ? `online ready ${onlineReady.length}/${ready.length}`
    : `online ready 0/${ready.length}`;
  const bottom = `${basis.trades_per_day.toFixed(1)}/д ${_fmtGoalMoney(basis.monthly_profit)}`;
  const target = `${_COVERAGE_TARGETS.trades_per_day}/д и ${_fmtGoalMoney(_COVERAGE_TARGETS.monthly_profit)}`;
  const source = onlineReady.length ? "сейчас включено online" : "план по ready, но online еще не подтвержден";
  const pctTrades = _COVERAGE_TARGETS.trades_per_day > 0 ? basis.trades_per_day / _COVERAGE_TARGETS.trades_per_day : 0;
  const pctMoney  = _COVERAGE_TARGETS.monthly_profit > 0 ? basis.monthly_profit  / _COVERAGE_TARGETS.monthly_profit  : 0;
  const percent   = Math.min(100, Math.max(0, Math.round((pctTrades + pctMoney) / 2 * 100)));
  const goalDetail = `${basis.trades_per_day.toFixed(1)}/${_COVERAGE_TARGETS.trades_per_day} дн · ${_fmtGoalMoney(basis.monthly_profit)}/${_fmtGoalMoney(_COVERAGE_TARGETS.monthly_profit)}`;
  return {
    state,
    met,
    top,
    bottom,
    percent,
    goalDetail,
    title:
      `Цель остановки: ${target}. ` +
      `Расчет: ${source}. ` +
      `План ready: ${planned.trades_per_day.toFixed(2)}/д, ${_fmtGoalMoney(planned.monthly_profit)}. ` +
      `Online ok: ${onlineReady.length}/${ready.length}. ` +
      (mismatch.length ? `Есть расхождение параметров: ${mismatch.length}. ` : "") +
      (met ? "Целевая планка выполнена." : "Целевая планка еще не выполнена."),
  };
}

async function ensureProfilesLoaded() {
  if (_profilesState.loaded && _profilesState.data) return _profilesState.data;
  await loadProfiles();
  return _profilesState.data;
}

async function jumpToProfile(profileId) {
  if (!profileId) return;
  activateLeftTab("profiles");
  await ensureProfilesLoaded();
  _profilesState.search = "";
  const search = document.getElementById("prof-search");
  if (search) search.value = "";
  renderProfilesList();
  requestAnimationFrame(() => {
    const card = [...document.querySelectorAll(".profile-card")]
      .find(x => x.dataset.profileId === profileId);
    if (!card) return;
    document.querySelectorAll(".profile-card.focused").forEach(x => x.classList.remove("focused"));
    card.classList.add("focused");
    card.scrollIntoView({ block: "center", behavior: "smooth" });
  });
}

function openEvidenceId(id) {
  if (!id) return;
  if (String(id).startsWith("batch_") && !String(id).includes("__")) openBatch(id);
  else openResult(id);
}

function openProfileEvidence(p) {
  const ids = _profileEvidenceIds(p);
  if (ids.length) openEvidenceId(ids[0]);
}

function renderCoverage() {
  const tb = document.getElementById("cov-tbody");
  const sum = document.getElementById("cov-summary");
  if (!tb) return;
  const data = _coverageState.data || {};
  const rows = Array.isArray(data.instruments) ? data.instruments : [];
  const filt = _coverageState.statusFilter || "all";
  const visible = filt === "all" ? rows : rows.filter(r => _covStatus(r.best_status) === filt);

  tb.replaceChildren();
  if (!visible.length) {
    const tr = el("tr");
    const td = el("td"); td.colSpan = 4; td.className = "muted small";
    td.style.padding = "10px";
    td.textContent = rows.length ? "Нет инструментов с этим статусом." : "Покрытие пустое.";
    tr.appendChild(td); tb.appendChild(tr); return;
  }
  for (const r of visible) {
    const root = (r.root || "").trim();
    const profiles = Array.isArray(r.profiles) ? r.profiles : _profilesForRoot(root);
    const counts = _coverageCountsForRow(r, profiles);
    const isOpen = _coverageState.expanded.has(root);
    const tr = el("tr", { cls: "coverage-main-row" });
    tr.addEventListener("click", () => {
      if (!root) return;
      if (_coverageState.expanded.has(root)) _coverageState.expanded.delete(root);
      else _coverageState.expanded.add(root);
      renderCoverage();
    });
    const goal = _coverageGoalSummary(profiles);
    const tdName = el("td");
    const lockMark = r.locked ? " 🔒" : "";
    if (goal.state !== "missing") {
      tdName.appendChild(el("span", { cls: `cov-online-badge ${goal.state}`, text: goal.top }));
    }
    tdName.appendChild(el("span", { cls: "cov-instr-name", text: `${isOpen ? "▾" : "▸"} ${root}${lockMark}` }));
    if (r.group) tdName.appendChild(el("span", { cls: "cov-instr-group", text: r.group }));
    if (r.profile_name) tdName.title = `${r.profile_name}\n${r.profile_id || ""}`;
    tr.appendChild(tdName);
    const tdCnt = el("td", { cls: "num" });
    const cntBox = el("div", { cls: "coverage-count" });
    cntBox.appendChild(el("strong", { text: `${counts.ready || 0} / ${counts.total || 0}` }));
    cntBox.title = `Готовые профили: ${counts.ready || 0}. Всего профилей для ${root}: ${counts.total || 0}.`;
    const details = [];
    details.push("готовые / профили");
    if (counts.ready) details.push(`готово ${counts.ready}`);
    if (counts.in_progress) details.push(`в процессе ${counts.in_progress}`);
    cntBox.appendChild(el("small", { text: details.length ? details.join(" · ") : "нет профилей" }));
    tdCnt.appendChild(cntBox);
    tr.appendChild(tdCnt);
    const bs = _covStatus(r.best_status);
    const bd = _COV_BADGE[bs] || _COV_BADGE.in_progress;
    const tdSt = el("td");
    const span = el("span", {
      cls: "status-badge " + bd.cls,
      text: [bd.emoji, bd.label].filter(Boolean).join(" "),
    });
    tdSt.appendChild(span);
    tr.appendChild(tdSt);
    const tdGoal = el("td");
    const goalBox = el("div", { cls: `coverage-goal ${goal.state}` });
    goalBox.title = goal.title;
    if (goal.state === "missing") {
      goalBox.appendChild(el("strong", { text: "—" }));
      goalBox.appendChild(el("small", { text: "нет ready" }));
    } else {
      goalBox.appendChild(el("strong", { text: `${goal.percent}%` }));
      goalBox.appendChild(el("small", { text: goal.goalDetail }));
    }
    tdGoal.appendChild(goalBox);
    tr.appendChild(tdGoal);
    tb.appendChild(tr);
    if (isOpen) tb.appendChild(_buildCoverageDetailRow(root, profiles, r));
  }

  if (sum) {
    const c = data.summary || {};
    const total = c.total || c.total_micros || rows.length || 0;
    const approvedAvailable = visible.reduce((acc, r) => {
      const profiles = Array.isArray(r.profiles) ? r.profiles : _profilesForRoot(r.root);
      const counts = _coverageCountsForRow(r, profiles);
      return acc + (counts.approved_available || 0);
    }, 0);
    const runtimeEnabled = visible.reduce((acc, r) => {
      const profiles = Array.isArray(r.profiles) ? r.profiles : _profilesForRoot(r.root);
      const counts = _coverageCountsForRow(r, profiles);
      return acc + (counts.runtime_enabled || 0);
    }, 0);
    sum.textContent =
      `Всего: ${total} · Готово: ${c.ready||0} · ` +
      `Доступно готовых: ${approvedAvailable} · Online: ${runtimeEnabled} · ` +
      `В процессе: ${c.in_progress||0}` +
      (data.generated_at_utc ? ` · Обновлено: ${data.generated_at_utc}` : "");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const f = document.getElementById("cov-status-filter");
  if (f) f.addEventListener("change", () => {
    _coverageState.statusFilter = f.value || "all";
    renderCoverage();
  });
  const r = document.getElementById("cov-refresh");
  if (r) r.addEventListener("click", () => { _coverageState.loaded = false; loadCoverage(); });
});

async function loadProfiles() {
  try {
    const data = await api.get("/api/profiles");
    _profilesState.data = data;
    _profilesState.loaded = true;
    renderProfilesList();
  } catch (e) {
    const list = document.getElementById("profiles-list");
    if (list) list.innerHTML = `<div class="muted small" style="padding:10px;color:#f87171;">Ошибка загрузки профилей: ${e.message}</div>`;
  }
}

const _PROF_STATUS_LABEL = {
  ready: "Готова",
  in_progress: "В процессе",
};

function renderProfilesList() {
  const list = document.getElementById("profiles-list");
  if (!list) return;
  const data = _profilesState.data;
  const profiles = (data && Array.isArray(data.profiles)) ? data.profiles : [];

  const q = (_profilesState.search || "").trim().toLowerCase();
  const sf = _profilesState.statusFilter || "all";
  const filtered = profiles.filter(p => {
    if (sf !== "all" && _covStatus(p.status) !== sf) return false;
    if (!q) return true;
    const hay = [
      p.name, p.strategy_class, p.instrument, p.timeframe,
      p.status, p.profile_id,
    ].filter(Boolean).join(" ").toLowerCase();
    return hay.includes(q);
  });

  list.replaceChildren();
  if (!filtered.length) {
    const empty = el("div", { cls: "muted small" });
    empty.style.padding = "10px";
    empty.textContent = profiles.length
      ? "Профили не найдены по фильтру."
      : "Реестр профилей пуст. Добавьте через data/profiles/strategies.json.";
    list.appendChild(empty);
    return;
  }

  filtered.forEach(p => list.appendChild(renderProfileCard(p)));
}

function renderProfileCard(p) {
  const card = el("div", { cls: "profile-card" });
  if (p.profile_id) card.dataset.profileId = p.profile_id;
  card.title = "Нажмите, чтобы открыть отчет-основание профиля";
  card.addEventListener("click", () => openProfileEvidence(p));

  // Header: name + status badge.
  const head = el("div", { cls: "profile-head" });
  const title = el("div", { cls: "profile-title", text: p.name || p.profile_id });
  const badge = el("span");
  const displayStatus = _covStatus(p.status);
  badge.className = "profile-status " + displayStatus;
  badge.textContent = _PROF_STATUS_LABEL[displayStatus] || "В процессе";
  head.appendChild(title);
  head.appendChild(badge);
  card.appendChild(head);

  // Subtitle: strategy / instrument / timeframe / window.
  const sub = el("div", { cls: "profile-sub" });
  const parts = [
    p.strategy_class,
    fmtContract(p.instrument),
    p.timeframe,
    p.trade_window_pt ? `🕒 ${p.trade_window_pt} PT` : null,
  ].filter(Boolean);
  sub.textContent = parts.join(" · ");
  card.appendChild(sub);

  // Period of last test.
  if (p.test_period && p.test_period.from_utc && p.test_period.to_utc) {
    const per = el("div", { cls: "profile-period" });
    per.textContent = `Период: ${_fmtDatePT(p.test_period.from_utc)} → ${_fmtDatePT(p.test_period.to_utc)}`;
    card.appendChild(per);
  }

  // Metrics grid.
  const m = p.metrics || {};
  const conf = p.confidence_score || p.confidence;
  const metricsRow = el("div", { cls: "profile-metrics" });
  metricsRow.appendChild(_metricCell("Сделки", m.trade_count != null ? m.trade_count : "—"));
  metricsRow.appendChild(_metricCell("Win %",
    m.winning_pct != null ? m.winning_pct.toFixed(1) + "%" : "—"));
  metricsRow.appendChild(_metricCell("Чистый",
    m.net_profit_after_commission != null ? fmtMoneySign(m.net_profit_after_commission) : "—",
    m.net_profit_after_commission > 0 ? "pos" : (m.net_profit_after_commission < 0 ? "neg" : "")));
  metricsRow.appendChild(_metricCell("PF",
    m.profit_factor_after_commission != null ? Number(m.profit_factor_after_commission).toFixed(2) : "—"));
  metricsRow.appendChild(_metricCell("Макс. DD",
    m.max_drawdown != null ? fmtMoneySign(m.max_drawdown) : "—",
    m.max_drawdown < 0 ? "neg" : ""));
  metricsRow.appendChild(_metricCell("Доверие",
    conf && conf.score != null ? conf.score + "% " + (_CONF_LEVEL_LABEL[conf.level] || conf.level || "") : "—"));
  card.appendChild(metricsRow);

  const decision = p.decision || {};
  const decisionText = decision.reason || p.profile_summary || p.notes;
  if (decisionText) {
    const box = el("div", { cls: "profile-decision", text: decisionText });
    if (decision.next_test) box.title = "Следующий тест: " + decision.next_test;
    card.appendChild(box);
  }

  // Locked parameters preview (compact, expandable on hover via title).
  const lp = p.locked_parameters || {};
  const lpKeys = Object.keys(lp);
  if (lpKeys.length) {
    const params = el("div", { cls: "profile-params" });
    const preview = lpKeys.slice(0, 4)
      .map(k => `${k}=${lp[k]}`).join(" · ")
      + (lpKeys.length > 4 ? ` · +${lpKeys.length - 4} ещё` : "");
    params.textContent = "🔒 " + preview;
    params.title = lpKeys.map(k => `${k} = ${lp[k]}`).join("\n");
    card.appendChild(params);
  }

  // Footer actions: load into form, view last job.
  const foot = el("div", { cls: "profile-foot" });
  const btnLoad = el("button", { cls: "profile-btn", text: "Загрузить в форму" });
  btnLoad.addEventListener("click", (ev) => {
    ev.stopPropagation();
    loadProfileIntoForm(p);
  });
  foot.appendChild(btnLoad);
  const evidenceIds = _profileEvidenceIds(p);
  if (evidenceIds.length) {
    const btnJob = el("button", {
      cls: "profile-btn",
      text: evidenceIds.length > 1 ? `Открыть основание (${evidenceIds.length})` : "Открыть основание",
    });
    btnJob.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openEvidenceId(evidenceIds[0]);
    });
    foot.appendChild(btnJob);
  }
  card.appendChild(foot);

  return card;
}

function _metricCell(label, value, tone) {
  const cell = el("div", { cls: "profile-metric" + (tone ? " " + tone : "") });
  const lbl = el("div", { cls: "profile-metric-lbl", text: label });
  const val = el("div", { cls: "profile-metric-val", text: String(value) });
  cell.appendChild(lbl);
  cell.appendChild(val);
  return cell;
}

// Apply a profile's settings to the right-panel form so the user can run a
// fresh backtest with the locked configuration.
function loadProfileIntoForm(p) {
  if (!p) return;
  // Strategy class — rebuilds param fields with defaults.
  if (p.strategy_class) {
    const sel = document.getElementById("f-class");
    if (sel) {
      const opt = [...sel.options].find(o => o.value === p.strategy_class);
      if (opt) {
        sel.value = p.strategy_class;
        try { onStrategyChange(); } catch (_) {}
      }
    }
  }
  // Instrument basket.
  if (p.instrument) {
    _basket = [p.instrument];
    try { renderBasket(); } catch (_) {}
  }
  // Timeframe.
  if (p.timeframe) {
    const m = String(p.timeframe).trim().match(/^(\d+)\s+(\w+)$/);
    if (m) {
      const tEl = document.getElementById("f-tf-type");
      const vEl = document.getElementById("f-tf-value");
      const canon = m[2].charAt(0).toUpperCase() + m[2].slice(1).toLowerCase();
      if (tEl && [...tEl.options].some(o => o.value === canon)) tEl.value = canon;
      if (vEl) vEl.value = m[1];
      try { highlightActiveTimeframe(); } catch (_) {}
    }
  }
  // Locked parameters.
  const lp = p.locked_parameters || {};
  Object.keys(lp).forEach(k => {
    const inp = document.querySelector('#strategy-params [data-param-name="' + cssEscape(k) + '"]');
    if (!inp) return;
    if (inp.dataset.paramKind === "bool") inp.checked = !!lp[k];
    else                                    inp.value = String(lp[k] == null ? "" : lp[k]);
  });
  // Surface that a profile was loaded.
  try { console.log("[profile] loaded:", p.profile_id); } catch (_) {}
}

function reportFavoriteKey(kind, id) {
  return `${kind}:${id}`;
}

function reportFavoriteEntries() {
  const data = _favoritesState.data || {};
  return Array.isArray(data.favorites) ? data.favorites : [];
}

function ensureFavoritesStateData() {
  if (!_favoritesState.data || typeof _favoritesState.data !== "object") {
    _favoritesState.data = { schema_version: "1.0", favorites: [] };
  }
  if (!Array.isArray(_favoritesState.data.favorites)) {
    _favoritesState.data.favorites = [];
  }
  return _favoritesState.data;
}

function favoritePendingOp(key) {
  return (_favoritesState.pending instanceof Map) ? (_favoritesState.pending.get(key) || null) : null;
}

function favoriteRepeatBusy(key) {
  return (_favoritesState.repeating instanceof Set) ? _favoritesState.repeating.has(key) : false;
}

function reportFavoriteState(kind, id, baseFavorite = false) {
  const key = reportFavoriteKey(kind, id);
  const pendingOp = favoritePendingOp(key);
  const favorite = pendingOp === "add" ? true
    : (pendingOp === "remove" ? false : (!!baseFavorite || isReportFavoriteKey(key)));
  return {
    key,
    pendingOp,
    favorite,
    favoriteBusy: !!pendingOp,
  };
}

function canFavoriteTopReport(item) {
  return !!item && item.kind === "job";
}

function activeBatchFavoriteChildrenCount(batchId) {
  if (!_activeBatch || _activeBatch.batch_id !== batchId || !Array.isArray(_activeBatchRows)) {
    return 0;
  }
  let count = 0;
  for (const row of _activeBatchRows) {
    if (!row || !row.job_id) continue;
    if (reportFavoriteState("job", row.job_id).favorite) count += 1;
  }
  return count;
}

function upsertFavoriteLocal(item) {
  if (!item || !item.kind || !item.id) return;
  const data = ensureFavoritesStateData();
  const key = item.key || reportFavoriteKey(item.kind, item.id);
  item.key = key;
  const next = reportFavoriteEntries().filter(x => (x.key || reportFavoriteKey(x.kind, x.id)) !== key);
  next.unshift(item);
  data.favorites = next;
}

function removeFavoriteLocal(kind, id) {
  const data = ensureFavoritesStateData();
  const key = reportFavoriteKey(kind, id);
  data.favorites = reportFavoriteEntries().filter(x => (x.key || reportFavoriteKey(x.kind, x.id)) !== key);
}

function rerenderFavoritesUi() {
  pruneCheckedFavorites();
  renderFavoritesList();
  if (Array.isArray(_activeBatchRows) && _activeBatchRows.length) {
    renderResultRowsTable(_activeBatchRows, _selectedJob);
  }
  _lastJobsRenderSig = "";
  if (_jobsPayload) _renderJobsPayload(_jobsPayload.jobsData, _jobsPayload.batchesData || { batches: [] });
}

function reportFavoriteMap() {
  const map = new Map();
  for (const item of reportFavoriteEntries()) {
    const key = item.key || reportFavoriteKey(item.kind, item.id);
    if (key) map.set(key, item);
  }
  return map;
}

function reportFavoriteFor(kind, id) {
  return reportFavoriteMap().get(reportFavoriteKey(kind, id)) || null;
}

function isReportFavorite(kind, id) {
  return !!reportFavoriteFor(kind, id);
}

function isReportFavoriteKey(key) {
  const favs = reportFavoriteMap();
  return favs.has(key);
}

function pruneCheckedFavorites() {
  let changed = false;
  for (const key of [..._checkedKeys]) {
    if (isReportFavoriteKey(key)) {
      _checkedKeys.delete(key);
      changed = true;
    }
  }
  if (changed) _updateDeleteCheckedBtn();
}

async function loadReportFavorites(options = {}) {
  if (_favoritesState.loaded && _favoritesState.data && !options.force) {
    renderFavoritesList();
    return _favoritesState.data;
  }
  try {
    const url = options.validate ? "/api/report-favorites?validate=1" : "/api/report-favorites";
    const data = await api.get(url);
    _favoritesState.data = data;
    _favoritesState.loaded = true;
    rerenderFavoritesUi();
    return data;
  } catch (e) {
    if (!options.silent) {
      const list = document.getElementById("favorites-list");
      if (list) {
        list.replaceChildren(el("div", {
          cls: "muted small",
          text: `Ошибка загрузки избранных: ${e.message}`,
        }));
      }
    }
    throw e;
  }
}

function favoriteValidationTone(validation) {
  const status = validation?.status || "";
  if (status === "ok") return "ok";
  if (status === "stale") return "warn";
  return "bad";
}

function favoriteValidationLabel(validation) {
  switch (validation?.status) {
    case "ok": return "актуально";
    case "stale": return "перепроверить";
    case "missing": return "файл удален";
    case "strategy_missing": return "нет стратегии";
    case "params_mismatch": return "параметры изменились";
    default: return "не проверено";
  }
}

function favoriteParamLabel(validation) {
  if (!validation) return "парам.: ?";
  if (validation.parameters_match_catalog === true) return "парам.: ок";
  if (validation.parameters_match_catalog === false) return "парам.: нет";
  return "парам.: ?";
}

function renderFavoritesList() {
  const list = document.getElementById("favorites-list");
  if (!list) return;
  const q = String(_favoritesState.search || "").trim().toLowerCase();
  const favorites = reportFavoriteEntries().filter(item => {
    if (!q) return true;
    const hay = [
      item.report_no,
      item.label,
      item.strategy,
      item.instrument,
      (item.instruments || []).join(" "),
      item.timeframe,
      item.description,
      item.id,
      item.kind,
    ].filter(Boolean).join(" ").toLowerCase();
    return hay.includes(q);
  });
  list.replaceChildren();
  if (!favorites.length) {
    list.appendChild(el("div", {
      cls: "muted small",
      text: reportFavoriteEntries().length ? "Избранные не найдены по фильтру." : "Избранных отчетов пока нет. Нажмите звезду в таблице отчетов.",
    }));
    return;
  }
  favorites.forEach(item => list.appendChild(renderFavoriteCard(item)));
}

function renderFavoriteCard(item) {
  const validation = item.validation || {};
  const key = item.key || reportFavoriteKey(item.kind, item.id);
  const repeatBusy = favoriteRepeatBusy(key);
  const card = el("div", { cls: `profile-card favorite-card ${validation.status || ""}` });
  card.title = "Нажмите, чтобы открыть отчет";
  card.addEventListener("click", () => openFavoriteReport(item));

  const head = el("div", { cls: "profile-head" });
  const title = el("div", {
    cls: "profile-title",
    text: `${item.report_no != null ? "#" + item.report_no + " " : ""}${item.label || item.id}`,
  });
  const badge = el("span", {
    cls: `favorite-badge ${favoriteValidationTone(validation)}`,
    text: favoriteValidationLabel(validation),
    title: validation.checked_at_utc ? `Проверено: ${validation.checked_at_utc}` : "",
  });
  head.appendChild(title);
  head.appendChild(badge);
  card.appendChild(head);

  const sub = el("div", { cls: "profile-sub" });
  const period = item.period && item.period.from_utc && item.period.to_utc
    ? `${_fmtDatePT(item.period.from_utc)} → ${_fmtDatePT(item.period.to_utc)}`
    : "";
  sub.textContent = [
    item.kind === "batch" ? "Пакет" : "Запуск",
    item.strategy,
    item.timeframe,
    period,
  ].filter(Boolean).join(" · ");
  card.appendChild(sub);

  const meta = el("div", { cls: "favorite-meta" });
  meta.appendChild(el("span", {
    cls: `favorite-badge ${validation.report_unchanged ? "ok" : "warn"}`,
    text: validation.report_unchanged ? "отчет: ок" : "отчет: проверить",
  }));
  meta.appendChild(el("span", {
    cls: `favorite-badge ${validation.strategy_exists === false ? "bad" : "ok"}`,
    text: validation.strategy_exists === false ? "стратегия: нет" : "стратегия: ок",
  }));
  meta.appendChild(el("span", {
    cls: `favorite-badge ${validation.parameters_match_catalog === false ? "bad" : "ok"}`,
    text: favoriteParamLabel(validation),
    title: (validation.unknown_parameters || []).join("\n"),
  }));
  meta.appendChild(el("span", {
    cls: "favorite-badge ok",
    text: validation.validated_against_strategy_analyzer ? "SA: ok" : "SA: ?",
  }));
  card.appendChild(meta);

  const desc = String(item.description || "").trim();
  card.appendChild(el("div", {
    cls: `favorite-description ${desc ? "" : "empty"}`,
    text: desc || "Описание не задано.",
  }));

  const foot = el("div", { cls: "profile-foot" });
  const btnOpen = el("button", { cls: "profile-btn", text: "Открыть" });
  btnOpen.addEventListener("click", (ev) => {
    ev.stopPropagation();
    openFavoriteReport(item);
  });
  foot.appendChild(btnOpen);
  const btnRepeat = el("button", {
    cls: "profile-btn",
    text: repeatBusy ? "Запускаем..." : "Повторить",
  });
  btnRepeat.disabled = repeatBusy;
  btnRepeat.addEventListener("click", (ev) => {
    ev.stopPropagation();
    repeatFavoriteReport(item);
  });
  foot.appendChild(btnRepeat);
  const btnDesc = el("button", { cls: "profile-btn", text: "Описание" });
  btnDesc.addEventListener("click", (ev) => {
    ev.stopPropagation();
    editFavoriteDescription(item);
  });
  foot.appendChild(btnDesc);
  const btnRemove = el("button", { cls: "profile-btn", text: "Снять ★" });
  btnRemove.addEventListener("click", (ev) => {
    ev.stopPropagation();
    toggleReportFavorite(item.kind, item.id);
  });
  foot.appendChild(btnRemove);
  card.appendChild(foot);
  return card;
}

function openFavoriteReport(item) {
  if (!item || !item.kind || !item.id) return;
  setSelectedReport(item.kind, item.id, { scroll: true, reveal: true });
  if (item.kind === "batch") openBatch(item.id);
  else openResult(item.id);
}

async function repeatFavoriteReport(item) {
  if (!item || !item.kind || !item.id) return;
  if (_activeRun || _submitInFlight) {
    alert("Дождитесь завершения текущего запуска, затем повторите отчет.");
    return;
  }
  const key = item.key || reportFavoriteKey(item.kind, item.id);
  if (favoriteRepeatBusy(key)) return;
  _favoritesState.repeating.add(key);
  rerenderFavoritesUi();
  const out = document.getElementById("run-result");
  const period = item.period && typeof item.period === "object" ? item.period : {};
  const instruments = Array.isArray(item.instruments) && item.instruments.length
    ? item.instruments.slice()
    : (item.instrument ? [item.instrument] : []);
  try {
    const resp = await api.post(
      `/api/report-favorites/${encodeURIComponent(item.kind)}/${encodeURIComponent(item.id)}/repeat`,
      {}
    );
    if (resp.kind === "batch") {
      if (out) {
        out.hidden = false;
        out.textContent = `Повторный пакет отправлен: ${resp.batch_id} · задач: ${resp.total}`;
      }
      startActiveRun({
        kind: "batch",
        id: resp.batch_id,
        strategy: item.strategy || "",
        instruments,
        period: { from_utc: period.from_utc || "", to_utc: period.to_utc || "" },
        total: resp.total || instruments.length,
      });
      _submitInFlight = false;
      refreshJobs({ reset: true });
      setTimeout(() => openBatch(resp.batch_id), 400);
      return;
    }
    if (out) {
      out.hidden = false;
      out.textContent = `Повторный запуск отправлен: ${resp.job_id}`;
    }
    startActiveRun({
      kind: "job",
      id: resp.job_id,
      strategy: item.strategy || "",
      instruments,
      period: { from_utc: period.from_utc || "", to_utc: period.to_utc || "" },
    });
    _submitInFlight = false;
    refreshJobs({ reset: true });
    setTimeout(() => openResult(resp.job_id), 400);
  } catch (e) {
    alert("Не удалось повторить отчет: " + e.message);
  } finally {
    _favoritesState.repeating.delete(key);
    rerenderFavoritesUi();
  }
}

async function editFavoriteDescription(item) {
  const key = item.key || reportFavoriteKey(item.kind, item.id);
  const next = window.prompt("Описание избранного отчета", item.description || "");
  if (next == null) return;
  try {
    const [kind, ...rest] = key.split(":");
    const id = rest.join(":");
    const resp = await api.post(`/api/report-favorites/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/description`, {
      description: next,
    });
    if (resp && resp.favorite) {
      upsertFavoriteLocal(resp.favorite);
      rerenderFavoritesUi();
    }
  } catch (e) {
    alert("Не удалось сохранить описание: " + e.message);
  }
}

async function toggleReportFavorite(kind, id) {
  const key = reportFavoriteKey(kind, id);
  if (favoritePendingOp(key)) return;
  const existing = reportFavoriteFor(kind, id);
  const removing = !!existing;
  if (!removing && kind !== "job") {
    alert("Пакетный отчёт нельзя добавлять в избранное сверху. Выберите конкретный запуск в нижней таблице.");
    return;
  }
  _favoritesState.pending.set(key, removing ? "remove" : "add");
  if (removing) removeFavoriteLocal(kind, id);
  rerenderFavoritesUi();
  try {
    if (removing) {
      await api.delete(`/api/report-favorites/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
      _checkedKeys.delete(key);
    } else {
      const resp = await api.post("/api/report-favorites", { kind, id });
      if (resp && resp.favorite) upsertFavoriteLocal(resp.favorite);
    }
  } catch (e) {
    if (removing && existing) upsertFavoriteLocal(existing);
    alert("Не удалось обновить избранное: " + e.message);
  } finally {
    _favoritesState.pending.delete(key);
    rerenderFavoritesUi();
  }
}


function populateInstrumentBrowserGroups() {
  const sel = document.getElementById("ib-group");
  if (!sel) return;
  const cur = sel.value || "all";
  sel.replaceChildren();

  const optAll = document.createElement("option");
  optAll.value = "all"; optAll.textContent = "Все группы";
  sel.appendChild(optAll);

  // TopStep virtual group — first after "Все группы"
  const optTs = document.createElement("option");
  optTs.value = TOPSTEP_GROUP_KEY; optTs.textContent = "🏆 TopStep";
  sel.appendChild(optTs);

  const groups = (_catalog && _catalog.instrument_groups && _catalog.instrument_groups.groups) || [];
  for (const g of groups) {
    const o = document.createElement("option");
    const gname = g.group_name || g.name;
    o.value = gname; o.textContent = groupLabel(gname);
    sel.appendChild(o);
  }
  sel.value = (Array.from(sel.options).some(o => o.value === cur)) ? cur : "all";
  _ib.group = sel.value;
}

function renderInstrumentBrowser() {
  initInstrumentBrowser();
  populateInstrumentBrowserGroups();
  // Rebuild front-contract map (cheap) — catalog could have just refreshed.
  buildFrontByRoot();

  const tbody = document.getElementById("ib-tbody");
  const countEl = document.getElementById("ib-count");
  if (!tbody) return;

  const all = (_catalog && _catalog.instruments) || [];
  const q = (_ib.search || "").trim().toLowerCase();

  const rows = all.filter(r => {
    if (!r || !r.instrument) return false;

    // Root/continuous master records are always hidden.
    if (isRootRecord(r)) return false;

    // Always require minute data — instruments without data are useless for backtesting.
    if (!r.has_minute_data) return false;

    if (q) {
      const hay = (r.instrument + " " + (r.root || "")).toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (_ib.group && _ib.group !== "all") {
      if (_ib.group === TOPSTEP_GROUP_KEY) {
        if (!isTopStepRoot(r.instrument)) return false;
      } else {
        if (instrumentGroupOf(r.instrument) !== _ib.group) return false;
      }
    }

    // "Только актуальные": for futures contracts, show only the front
    //    contract per root. Non-futures rows (forex pairs) pass through.
    if (_ib.onlyCurrent && !_ib.showAllExpiries) {
      if (r.expiry) {
        if (!isFrontContract(r)) return false;
      }
    } else if (!_ib.showAllExpiries) {
      // onlyCurrent off but no "all expiries" → still hide expired ones
      if (isExpiredContract(r)) return false;
    }
    // If showAllExpiries is on, skip expiry checks (show every contract).

    const tv = r.tick_value;
    if (_ib.tickMin != null && (tv == null || tv < _ib.tickMin)) return false;
    if (_ib.tickMax != null && (tv == null || tv > _ib.tickMax)) return false;
    return true;
  });

  if (countEl) countEl.textContent = `${rows.length} / ${all.length}`;

  tbody.replaceChildren();
  if (rows.length === 0) {
    const tr = el("tr");
    const td = el("td", { text: "Нет инструментов под фильтр." });
    td.colSpan = 5; td.className = "ib-empty";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  // Sort: in-basket first, then by tick_value asc (nulls last), then name.
  rows.sort((a, b) => {
    const ba = _basket.includes(a.instrument) ? 0 : 1;
    const bb = _basket.includes(b.instrument) ? 0 : 1;
    if (ba !== bb) return ba - bb;
    const av = a.tick_value == null ? Infinity : a.tick_value;
    const bv = b.tick_value == null ? Infinity : b.tick_value;
    if (av !== bv) return av - bv;
    return a.instrument.localeCompare(b.instrument);
  });

  for (const r of rows) {
    const inBasket = _basket.includes(r.instrument);
    const tr = el("tr");
    tr.dataset.instrument = r.instrument;
    if (inBasket) tr.className = "selected";

    // Instrument name + status badge
    const tdName = el("td");
    tdName.appendChild(document.createTextNode(fmtContract(r.instrument)));
    if (r.expiry) {
      const expired = isExpiredContract(r);
      const front = isFrontContract(r);
      if (expired) {
        const b = el("span", { text: "стар.", cls: "ib-badge ib-badge-old" });
        b.title = "Срок истёк";
        tdName.appendChild(b);
      } else if (front) {
        const b = el("span", { text: "акт.", cls: "ib-badge ib-badge-cur" });
        b.title = "Актуальный (front) контракт";
        tdName.appendChild(b);
      }
    } else if (isRootRecord(r)) {
      const b = el("span", { text: "root", cls: "ib-badge ib-badge-root" });
      b.title = "Master/continuous запись — не торговый контракт";
      tdName.appendChild(b);
    }
    tr.appendChild(tdName);

    tr.appendChild(el("td", { text: groupShort(instrumentGroupOf(r.instrument) || "—") }));
    const tdStep = el("td", { text: fmtTick(r.tick_size) }); tdStep.className = "num";
    tr.appendChild(tdStep);
    const tdMon = el("td", { text: fmtMoney(r.tick_value) }); tdMon.className = "num";
    tr.appendChild(tdMon);
    const btn = el("button", { text: inBasket ? "✓" : "+" });
    btn.type = "button"; btn.className = "ib-add-btn";
    btn.title = inBasket ? "Уже в корзине — нажмите чтобы убрать" : "Добавить в корзину";
    btn.addEventListener("click", () => {
      if (_basket.includes(r.instrument)) {
        removeFromBasket(r.instrument);
      } else {
        if (_basket.length >= 50) { alert("Лимит корзины — 50 инструментов."); return; }
        addToBasket(r.instrument);
      }
      renderBasket();
    });
    const tdBtn = el("td"); tdBtn.appendChild(btn);
    tr.appendChild(tdBtn);
    tbody.appendChild(tr);
  }
}

// Display labels for instrument groups (catalog ids stay English so the
// JSON file matches NinjaTrader naming, but the UI uses Russian labels).
const GROUP_LABELS_RU = {
  [TOPSTEP_GROUP_KEY]: "🏆 TopStep",
  "Futures":        "Фьючерсы",
  "Indexes":        "Индексы",
  "Cryptocurrency": "Криптовалюта",
  "Micros":         "Микро-фьючерсы",
  "FOREX":          "Форекс",
  "SP 500":         "S&P 500",
  "NASDAQ 100":     "NASDAQ 100",
  "DOW 30":         "DOW 30",
  "DAX 30":         "DAX 30",
};
const GROUP_LABELS_SHORT = {
  [TOPSTEP_GROUP_KEY]: "TopStep",
  "Futures":        "Фьюч.",
  "Indexes":        "Индексы",
  "Cryptocurrency": "Крипто",
  "Micros":         "Микро",
  "FOREX":          "Форекс",
  "SP 500":         "S&P",
  "NASDAQ 100":     "NASDAQ",
  "DOW 30":         "DOW",
  "DAX 30":         "DAX",
};
function groupLabel(name) { return GROUP_LABELS_RU[name] || name; }
function groupShort(name) { return GROUP_LABELS_SHORT[name] || GROUP_LABELS_RU[name] || name; }

function renderBasketGroups() {
  const box = document.getElementById("basket-groups-list");
  if (!box) return;
  box.replaceChildren();
  // Synthetic "All instruments" entry maps to no group filter.
  const allItem = el("div", { cls: "basket-item active", text: "Все инструменты" });
  allItem.addEventListener("click", () => {
    _activeGroup = null;
    box.querySelectorAll(".basket-item").forEach(x => x.classList.remove("active"));
    allItem.classList.add("active");
    document.getElementById("basket-instr-title").textContent = "Все инструменты";
    document.getElementById("basket-add-group").disabled = true;
    renderBasketInstruments();
  });
  box.appendChild(allItem);

  const groups = _catalog?.instrument_groups?.groups || [];
  if (groups.length === 0) {
    const empty = el("div", { cls: "basket-empty",
      text: "(нет групп — instrument_groups.json пуст)" });
    box.appendChild(empty);
    return;
  }
  groups.forEach(g => {
    const item = el("div", { cls: "basket-item" });
    const name = el("span", { text: groupLabel(g.group_name) });
    const cnt  = _basketOnlyCurrent
      ? (g.current_count != null ? g.current_count : g.count)
      : g.count;
    const total = g.count;
    const badgeText = (_basketOnlyCurrent && g.current_count != null && g.current_count !== total)
      ? `${cnt}/${total}` : String(cnt);
    const badge = el("span", { cls: "badge", text: badgeText });
    if (g.note) badge.title = g.note;
    item.appendChild(name); item.appendChild(badge);
    item.addEventListener("click", () => {
      _activeGroup = g.group_name;
      box.querySelectorAll(".basket-item").forEach(x => x.classList.remove("active"));
      item.classList.add("active");
      document.getElementById("basket-instr-title").textContent =
        `${groupLabel(g.group_name)} (${cnt})`;
      document.getElementById("basket-add-group").disabled = (cnt === 0);
      renderBasketInstruments();
    });
    box.appendChild(item);
  });
}

function renderBasketInstruments() {
  const box = document.getElementById("basket-instr-list");
  if (!box) return;
  box.replaceChildren();
  if (!_catalog) return;
  let pool;
  let currentSet = null;   // names that the catalog flagged as the current contract
  if (_activeGroup) {
    const grp = (_catalog.instrument_groups?.groups || [])
      .find(g => g.group_name === _activeGroup);
    if (grp && Array.isArray(grp.current_instruments)) {
      currentSet = new Set(grp.current_instruments);
    }
    const src = _basketOnlyCurrent && grp && Array.isArray(grp.current_instruments)
      ? grp.current_instruments
      : (grp?.instruments || []);
    pool = src.map(name => {
      const r = (_catalog.instruments || []).find(i => i.instrument === name);
      return r || { instrument: name, has_minute_data: false };
    });
  } else {
    pool = _catalog.instruments || [];
    if (_basketOnlyCurrent) {
      // For "All instruments" view, treat current contract per first-token root
      // by relying on catalog ordering and de-duplicating by root.
      const seenRoot = new Set();
      pool = pool.slice().sort((a, b) => {
        const ah = a.has_minute_data ? 1 : 0;
        const bh = b.has_minute_data ? 1 : 0;
        if (ah !== bh) return bh - ah;
        const al = a.data_last || ""; const bl = b.data_last || "";
        if (al !== bl) return al < bl ? 1 : -1;
        return a.instrument.localeCompare(b.instrument);
      }).filter(r => {
        const root = (r.instrument.split(" ", 1)[0] || r.instrument).toUpperCase();
        if (seenRoot.has(root)) return false;
        seenRoot.add(root);
        return true;
      });
    }
  }
  const q = (_basketSearchQuery || "").trim().toLowerCase();
  if (q) pool = pool.filter(r => r.instrument.toLowerCase().includes(q));
  // Sort: has_minute_data desc, data_last desc, alpha
  pool = pool.slice().sort((a, b) => {
    const ah = a.has_minute_data ? 1 : 0;
    const bh = b.has_minute_data ? 1 : 0;
    if (ah !== bh) return bh - ah;
    const al = a.data_last || ""; const bl = b.data_last || "";
    if (al !== bl) return al < bl ? 1 : -1;
    return a.instrument.localeCompare(b.instrument);
  });
  const cap = 300;
  const total = pool.length;
  pool = pool.slice(0, cap);
  if (pool.length === 0) {
    box.appendChild(el("div", { cls: "basket-empty",
      text: _basketOnlyCurrent
        ? "Нет актуальных контрактов. Снимите флажок 'Только актуальные', чтобы увидеть expired."
        : "Ничего не найдено" }));
    return;
  }
  pool.forEach(r => {
    const isCurrent = currentSet ? currentSet.has(r.instrument) : false;
    const item = el("div", { cls: "basket-item" + (isCurrent ? " is-current" : "") });
    const sym  = el("span", { text: fmtContract(r.instrument) });
    if (!r.has_minute_data) sym.title = "no minute data";
    const right = el("span", { cls: "basket-item-right" });
    const last = el("span", { cls: "badge",
      text: r.data_last || (r.has_minute_data ? "?" : "no data") });
    if (isCurrent) last.title = "Актуальный контракт (ближайший месяц)";
    const add = el("button", { cls: "add-btn",
      text: _basket.includes(r.instrument) ? "✓" : "+" });
    add.type = "button";
    if (_basket.includes(r.instrument)) add.disabled = true;
    add.addEventListener("click", (ev) => {
      ev.stopPropagation();
      addToBasket(r.instrument);
      renderBasket();
    });
    right.appendChild(last); right.appendChild(add);
    item.appendChild(sym); item.appendChild(right);
    // Whole-row click also adds.
    item.addEventListener("click", () => {
      addToBasket(r.instrument);
      renderBasket();
    });
    box.appendChild(item);
  });
  if (total > cap) {
    box.appendChild(el("div", { cls: "basket-empty",
      text: `… еще ${total - cap}; уточните поиском` }));
  }
}

function renderBasketSelected() {
  const box = document.getElementById("basket-selected-list");
  const cnt = document.getElementById("basket-count");
  const badge = document.getElementById("basket-count-badge");
  const mode = document.getElementById("basket-mode-hint");
  const submitBtn = document.getElementById("run-submit");
  if (!box) return;
  box.replaceChildren();
  const n = _basket.length;
  if (cnt) cnt.textContent = String(n);
  if (badge) {
    badge.textContent = String(n);
    badge.classList.toggle("warn",   n > 20 && n <= 50);
    badge.classList.toggle("danger", n > 50);
  }
  if (mode) {
    mode.classList.remove("batch", "warn", "danger");
    if (n === 0) {
      mode.textContent = "Корзина пуста";
    } else if (n === 1) {
      mode.textContent = "1 инструмент: одиночный запуск";
    } else if (n <= 20) {
      mode.textContent = `${n} инструментов: пакетный запуск`;
      mode.classList.add("batch");
    } else if (n <= 50) {
      mode.textContent = `${n} инструментов: пакетный запуск (ПОДТВЕРДИТЬ)`;
      mode.classList.add("warn");
    } else {
      mode.textContent = `${n} инструментов: ПРЕВЫШЕН ЛИМИТ 50`;
      mode.classList.add("danger");
    }
  }
  if (submitBtn) submitBtn.disabled = (n > 50);
  // Sync the hidden input so the "single instrument" code path keeps working.
  const hidden = document.getElementById("f-instrument");
  if (hidden) hidden.value = _basket[0] || "";
  if (n === 0) {
    box.appendChild(el("div", { cls: "basket-empty",
      text: "Корзина пуста. Добавьте хотя бы один инструмент." }));
    return;
  }
  _basket.forEach((name, idx) => {
    const item = el("div", { cls: "basket-selected-item" });
    const lbl = el("span", { text: `${idx + 1}. ${fmtContract(name)}` });
    const rm  = el("button", { cls: "rm-btn", text: "×" });
    rm.type = "button"; rm.title = "Убрать";
    rm.addEventListener("click", () => {
      removeFromBasket(name);
      renderBasket();
    });
    item.appendChild(lbl); item.appendChild(rm);
    box.appendChild(item);
  });
}


// ---------------- dynamic strategy parameters -----------------------------

function onStrategyChange() {
  const className = document.getElementById("f-class").value;
  const cls = (_catalog?.strategies || []).find(s => s.class_name === className);
  const box = document.getElementById("strategy-params");
  box.replaceChildren();

  const params = (cls && cls.parameters) || [];
  if (params.length === 0) {
    const h = el("div", { cls: "hint",
      text: "У стратегии нет параметров с [NinjaScriptProperty], либо catalog недоступен." });
    box.appendChild(h);
    return;
  }
  params.forEach(p => box.appendChild(renderParamField(p)));
}

function renderParamField(p) {
  const wrap = el("label", { cls: "field" });
  const label = el("span", { cls: "lbl", text: p.label || p.name });
  if (p.group) label.title = `Group: ${p.group}`;
  wrap.appendChild(label);

  let input;
  switch (p.kind) {
    case "int":
      input = document.createElement("input");
      input.type = "number"; input.step = "1";
      if (p.min != null) input.min = String(p.min);
      if (p.max != null) input.max = String(p.max);
      input.value = (p.default != null) ? String(p.default) : "0";
      break;
    case "float":
      input = document.createElement("input");
      input.type = "number"; input.step = "any";
      if (p.min != null) input.min = String(p.min);
      if (p.max != null) input.max = String(p.max);
      input.value = (p.default != null) ? String(p.default) : "0";
      break;
    case "bool":
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = !!p.default;
      break;
    case "string":
      input = document.createElement("input");
      input.type = "text";
      input.value = (p.default != null) ? String(p.default) : "";
      break;
    case "enum":
      input = document.createElement("select");
      (p.enum_values || []).forEach(v => {
        const o = document.createElement("option");
        o.value = v; o.textContent = v;
        if (String(p.default) === v) o.selected = true;
        input.appendChild(o);
      });
      break;
    default:
      input = document.createElement("input");
      input.type = "text"; input.disabled = true;
      input.value = (p.default != null) ? String(p.default) : "";
      input.title = `Unsupported kind: ${p.kind} (${p.type})`;
      break;
  }
  input.dataset.paramName = p.name;
  input.dataset.paramKind = p.kind;
  wrap.appendChild(input);
  return wrap;
}

function collectStrategyParameters() {
  const out = {};
  document.querySelectorAll("#strategy-params [data-param-name]").forEach(inp => {
    const name = inp.dataset.paramName;
    const kind = inp.dataset.paramKind;
    if (kind === "bool") { out[name] = !!inp.checked; return; }
    if (kind === "int") {
      const n = parseInt(inp.value, 10);
      if (!Number.isNaN(n)) out[name] = n;
      return;
    }
    if (kind === "float") {
      const n = parseFloat(inp.value);
      if (!Number.isNaN(n)) out[name] = n;
      return;
    }
    if (kind === "enum" || kind === "string") {
      out[name] = String(inp.value);
      return;
    }
    // unsupported: skip
  });
  return out;
}

// ---------------- account / risk profile ----------------------------------
function inputNumber(id, fallback) {
  const node = document.getElementById(id);
  if (!node) return fallback;
  const n = Number(node.value);
  return Number.isFinite(n) ? n : fallback;
}

function roundMoney(v) {
  return Math.round((Number(v) || 0) * 100) / 100;
}

// Extract the futures root from a contract symbol.
//   "MES 06-26" -> "MES", "MNQ 12-26" -> "MNQ", "ES" -> "ES",
//   "EURUSD" -> "EURUSD" (no space => returned as-is).
function rootFromInstrument(name) {
  if (!name || typeof name !== "string") return "";
  const i = name.indexOf(" ");
  return (i === -1 ? name : name.slice(0, i)).toUpperCase();
}

function marginCatalogSymbols() {
  const cat = (_catalog && _catalog.margin_catalog) || null;
  if (!cat || !cat.symbols || typeof cat.symbols !== "object") return {};
  return cat.symbols;
}

function marginCatalogSource() {
  const cat = (_catalog && _catalog.margin_catalog) || {};
  return {
    broker:         String(cat.broker || ""),
    source:         String(cat.source || ""),
    fetched_at_utc: String(cat.fetched_at_utc || ""),
  };
}

// Build the per-instrument margin map for the current basket given current
// capital + intraday-only choice. Pure function; no DOM access except via
// callers reading `_basket` and the risk-profile inputs.
function buildInstrumentMargins(startingCapital, intradayOnly) {
  const symbols = marginCatalogSymbols();
  const out = {};
  const marginType = intradayOnly ? "intraday" : "initial";
  const marginField = intradayOnly ? "intraday_margin" : "initial_margin";
  for (const inst of (_basket || [])) {
    const root = rootFromInstrument(inst);
    const rec = symbols[root] || null;
    let margin = null;
    if (rec && rec[marginField] != null && Number.isFinite(Number(rec[marginField]))) {
      margin = roundMoney(Number(rec[marginField]));
    }
    let status = "unknown";
    let maxC = null;
    if (margin == null || margin <= 0) {
      status = "unknown";
    } else {
      maxC = Math.floor(startingCapital / margin);
      status = startingCapital >= margin ? "allowed" : "blocked";
    }
    out[inst] = {
      root: root,
      margin_type: marginType,
      margin_per_contract: margin,
      max_contracts_by_capital: maxC,
      status: status,
    };
  }
  return out;
}

function collectRiskProfile() {
  const startingCapital = Math.max(0, inputNumber("f-starting-capital", 0));
  const intradayOnly = document.getElementById("f-intraday-only")?.checked === true;
  const instrumentMargins = buildInstrumentMargins(
    roundMoney(startingCapital), intradayOnly);

  return {
    schema_version: "0.1",
    mode: "informational",
    currency: "USD",
    starting_capital: roundMoney(startingCapital),
    intraday_only: intradayOnly,
    margin_source: marginCatalogSource(),
    instrument_margins: instrumentMargins,
    status: "informational_only",
    status_text: "Risk Profile сохранён в запуске; стратегия пока не ограничивается.",
  };
}

function updateRiskProfilePanel() {
  const risk = collectRiskProfile();
  const entries = Object.entries(risk.instrument_margins || {});
  let allowed = 0, blocked = 0, unknown = 0;
  for (const [, info] of entries) {
    if (info.status === "allowed") allowed += 1;
    else if (info.status === "blocked") blocked += 1;
    else unknown += 1;
  }
  const setText2 = (id, txt) => {
    const n = document.getElementById(id);
    if (n) n.textContent = txt;
  };
  setText2("rp-sum-allowed",
    entries.length ? `Можно: ${allowed}` : "Можно: —");
  setText2("rp-sum-blocked",
    entries.length ? `Недоступно: ${blocked}` : "Недоступно: —");
  setText2("rp-sum-unknown",
    entries.length ? `Нет данных: ${unknown}` : "Нет данных: —");

  const list = document.getElementById("risk-profile-list");
  if (list) {
    list.replaceChildren();
    for (const [inst, info] of entries) {
      const li = document.createElement("li");
      li.classList.add("rp-" + info.status);
      const name = document.createElement("span");
      name.className = "rp-name";
      name.textContent = inst;
      const meta = document.createElement("span");
      meta.className = "rp-meta";
      if (info.status === "unknown") {
        meta.textContent = "unknown — no margin data";
      } else {
        const m = info.margin_per_contract;
        const mx = info.max_contracts_by_capital;
        meta.textContent = `${info.status} — margin ${m != null ? fmtMoney(m) : "—"} — max ${mx != null ? mx : "—"}`;
      }
      li.appendChild(name);
      li.appendChild(meta);
      list.appendChild(li);
    }
  }

  const hint = document.getElementById("risk-profile-hint");
  if (hint) {
    const cat = (_catalog && _catalog.margin_catalog) || null;
    if (!cat || cat.source === "missing" || !Object.keys(cat.symbols || {}).length) {
      hint.textContent = "margins.json не загружен — рассчёт по марже недоступен. Профиль всё равно сохранится в запуске.";
      hint.classList.add("warn");
    } else {
      hint.textContent = "Информационный профиль: сохраняется в запуске, но не меняет логику стратегии. Каталог маржи обновляется автоматически раз в сутки из NinjaTrader.";
      hint.classList.remove("warn");
    }
  }

  // Refresh-info line: source / fetched / last-error.
  const refInfo = document.getElementById("risk-profile-refresh-info");
  if (refInfo) {
    const cat = (_catalog && _catalog.margin_catalog) || null;
    const refresh = (cat && cat.refresh) || {};
    const src = (cat && cat.source) || "—";
    const fetched = (cat && cat.fetched_at_utc) || "";
    const symCount = (cat && cat.symbols) ? Object.keys(cat.symbols).length : 0;
    let txt = `источник: ${src}`;
    if (symCount) txt += ` · символов: ${symCount}`;
    if (fetched) txt += ` · обновлено: ${fetched}`;
    if (refresh.last_error && !refresh.in_progress) {
      txt += ` · ошибка авто-обновления: ${refresh.last_error}`;
      refInfo.classList.add("warn");
    } else {
      refInfo.classList.remove("warn");
    }
    refInfo.textContent = txt;
  }
}

async function triggerMarginsRefresh() {
  const btn = document.getElementById("btn-refresh-margins");
  const info = document.getElementById("risk-profile-refresh-info");
  if (btn) { btn.disabled = true; btn.classList.add("busy"); }
  const prevText = btn ? btn.textContent : "";
  if (btn) btn.textContent = "Обновляем…";
  if (info) info.textContent = "обновление маржи…";
  try {
    const r = await api.post("/api/margins/refresh", {});
    if (r && r.ok) {
      await loadCatalog();
      updateRiskProfilePanel();
    } else {
      const err = (r && (r.error || r.reason)) || "не удалось обновить";
      if (info) {
        info.textContent = "ошибка обновления: " + err;
        info.classList.add("warn");
      }
      alert("Не удалось обновить маржи: " + err);
    }
  } catch (e) {
    if (info) {
      info.textContent = "ошибка обновления: " + e.message;
      info.classList.add("warn");
    }
    alert("Ошибка обновления маржи: " + e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("busy");
      btn.textContent = prevText || "Обновить маржи";
    }
  }
}

// ---------------- run-job submission --------------------------------------
// Submits either a single-instrument job (basket size = 1) or a batch (basket > 1).
// The single-job path is preserved bit-for-bit so existing callers keep
// working.
async function onSubmitJob(ev) {
  ev.preventDefault();
  if (_activeRun || _submitInFlight) {
    // A run is already in flight — guard against double submit.
    return;
  }
  _submitInFlight = true;
  const btn = document.getElementById("run-submit");
  btn.disabled = true;
  btn.classList.add("busy");
  btn.textContent = "Запускаем…";
  const out = document.getElementById("run-result");
  out.hidden = true;

  const fromDate = document.getElementById("f-from-date").value;  // YYYY-MM-DD
  const toDate   = document.getElementById("f-to-date").value;
  const instruments = (_basket || []).slice();
  const resetBtn = () => {
    _submitInFlight = false;
    btn.disabled = false; btn.classList.remove("busy");
    btn.textContent = "Запустить бэктест";
  };
  if (instruments.length === 0) {
    out.hidden = false;
    out.textContent = "Корзина пуста: добавьте хотя бы один инструмент";
    resetBtn();
    return;
  }
  if (instruments.length > 50) {
    out.hidden = false;
    out.textContent = `Слишком большая корзина (${instruments.length}): лимит 50`;
    resetBtn();
    return;
  }
  if (instruments.length > 20 && !confirm(
        `Запустить ${instruments.length} бэктест-задач?\n` +
        `Мост к NinjaTrader выполнит их последовательно — это может занять время.`)) {
    resetBtn();
    return;
  }
  const common = {
    class_name:          document.getElementById("f-class").value,
    bars_period_type:    document.getElementById("f-tf-type").value,
    bars_period_value:   parseInt(document.getElementById("f-tf-value").value, 10),
    from_utc:            fromDate ? `${fromDate}T00:00:00Z` : "",
    to_utc:              toDate   ? `${toDate}T00:00:00Z`   : "",
    parameters:          collectStrategyParameters(),
    risk_profile:        collectRiskProfile(),
    commission_template: document.getElementById("f-commission-template").value,
    session_template:    document.getElementById("f-thours").value,
  };

  try {
    if (instruments.length === 1) {
      const body = Object.assign({ instrument: instruments[0] }, common);
      const r = await api.post("/api/jobs", body);
      out.hidden = false;
      out.textContent = `Запуск отправлен: ${r.job_id}`;
      startActiveRun({
        kind: "job", id: r.job_id,
        strategy: common.class_name, instruments: instruments,
        period: { from_utc: common.from_utc, to_utc: common.to_utc },
      });
      _submitInFlight = false;
      refreshJobs({ reset: true });
      // single-job: open the result for it directly in the workspace
      setTimeout(() => openResult(r.job_id), 400);
    } else {
      const body = Object.assign({
        instruments: instruments,
        name: `${common.class_name} ×${instruments.length}`,
      }, common);
      const r = await api.post("/api/batches", body);
      out.hidden = false;
      out.textContent =
        `Пакет отправлен: ${r.batch_id} · задач: ${r.total}`;
      startActiveRun({
        kind: "batch", id: r.batch_id,
        strategy: common.class_name, instruments: instruments,
        period: { from_utc: common.from_utc, to_utc: common.to_utc },
        total: r.total,
      });
      _submitInFlight = false;
      refreshJobs({ reset: true });
      // Open the batch view immediately so the user sees per-instrument
      // rows fill in as bridge processes them (auto-refresh inside openBatch).
      setTimeout(() => openBatch(r.batch_id), 400);
    }
  } catch (e) {
    out.hidden = false;
    out.textContent = `Ошибка: ${e.message}`;
    resetBtn();
  }
  // Note: we do NOT reset the button on success — startActiveRun() owns
  // the button state from here until the run reaches a terminal status.
}

// ---------------- jobs tab ------------------------------------------------
let _selectedJob = null;
let _jobsFilter  = "all";  // all | running | done | failed | favorite
let _sortCol = "mtime";   // default: sort by creation time
let _sortDir = "desc";    // default: newest first
const _checkedKeys = new Set();  // "kind:id" keys of checked rows
// Phase 23 — report view mode
const _REPORTS_VIEW_CACHE_KEY = "reportsView.v2";
let _reportsView = storageGet(_REPORTS_VIEW_CACHE_KEY, "list") || "list"; // "list"|"tree"
if (_reportsView !== "list" && _reportsView !== "tree") _reportsView = "list";
const _JOBS_CACHE_KEY = "jobsTableCache.v3";
let _jobsCacheShown = false;
let _lastJobsRenderSig = "";
let _jobsPayload = null;
// The backend sorts/filters before slicing, so the UI can load reports in
// predictable 50-row chunks without mixing old middle pages into the top.
const REPORTS_PAGE_SIZE = 50;
const REPORTS_RESET_PAGE_SIZE = 50;
const REPORTS_BACKGROUND_PREFETCH_ENABLED = false;
const REPORTS_BACKGROUND_PREFETCH_DELAY_MS = 900;
const REPORTS_BACKGROUND_PAGE_SIZE = 5000;
let _reportsPaging = {
  offset: 0,
  total: 0,
  hasMore: true,
  loading: false,
};
let _reportsPrefetchTimer = null;
let _reportsPrefetchInFlight = false;
let _reportsPrefetchToken = 0;

// Whitelist of allowed status -> CSS class. Anything else falls back to
// "unknown" so an unexpected backend value can never inject arbitrary
// classNames into the DOM.
const STATUS_CLASSES = {
  pending:   "pending",
  running:   "running",
  done:      "done",
  failed:    "failed",
  partial_failed: "failed",
  cancelled: "cancelled",
  partial_cancelled: "cancelled",
};
const STATUS_LABELS = {
  pending:   "ожидание",
  running:   "в работе",
  done:      "готово",
  failed:    "ошибка",
  partial_failed: "частично",
  cancelled: "отменено",
  partial_cancelled: "частично отменено",
};
function statusLabel(s) { return STATUS_LABELS[s] || s || ""; }

function el(tag, opts) {
  const e = document.createElement(tag);
  if (!opts) return e;
  if (opts.text != null)  e.textContent = String(opts.text);
  if (opts.cls)           e.className   = opts.cls;
  if (opts.title != null) e.title       = String(opts.title);
  return e;
}

function td(value, opts) {
  const c = el("td", opts);
  c.textContent = (value == null || value === "") ? "" : String(value);
  return c;
}

// Track which row in the reports panel is currently displayed below.
// Key is `kind:id` so a batch and a job with the same id can never collide.
let _selectedReportKey = null;
let _pendingSelectedScrollKey = null;
let _pendingRevealReportKey = null;

function _findRenderedReportRow(key) {
  const tbody = document.querySelector("#jobs-table tbody");
  if (!tbody || !key) return null;
  return [...tbody.querySelectorAll("tr")].find(r => r.dataset.repkey === key) || null;
}

function _applySelectedReportSelection(opts) {
  const tbody = document.querySelector("#jobs-table tbody");
  if (!tbody) return;
  let selectedRow = null;
  tbody.querySelectorAll("tr").forEach(r => {
    const active = r.dataset.repkey === _selectedReportKey;
    r.classList.toggle("selected", active);
    if (active) selectedRow = r;
  });
  const shouldScroll = !!(opts && opts.scroll) || _pendingSelectedScrollKey === _selectedReportKey;
  if (selectedRow && shouldScroll) {
    _pendingSelectedScrollKey = null;
    try {
      selectedRow.scrollIntoView({ block: "center", inline: "nearest" });
    } catch {
      selectedRow.scrollIntoView();
    }
  }
  if (selectedRow && _pendingRevealReportKey === _selectedReportKey) {
    _pendingRevealReportKey = null;
  }
}

function setSelectedReport(kind, id, opts) {
  _selectedReportKey = `${kind}:${id}`;
  if (opts && opts.scroll) _pendingSelectedScrollKey = _selectedReportKey;
  if (opts && opts.reveal) _pendingRevealReportKey = _selectedReportKey;
  if (_reportsView === "tree" && opts && opts.reveal && _jobsPayload && !_findRenderedReportRow(_selectedReportKey)) {
    _lastJobsRenderSig = null;
    _renderJobsPayload(_jobsPayload.jobsData, _jobsPayload.batchesData || { batches: [] });
    return;
  }
  _applySelectedReportSelection(opts);
}

function _sortItems(items) {
  const dir = _sortDir === "asc" ? 1 : -1;
  return items.slice().sort((a, b) => {
    let av, bv;
    switch (_sortCol) {
      case "report_no":
        av = a.report_no != null ? a.report_no : -1;
        bv = b.report_no != null ? b.report_no : -1;
        return dir * (av - bv);
      case "mtime":
        return dir * (a.mtime - b.mtime);
      case "label":
        return dir * String(a.label||"").localeCompare(String(b.label||""), "ru");
      case "strategy":
        return dir * String(a.strategy||"").localeCompare(String(b.strategy||""), "ru");
      case "kind":
        return dir * String(a.kind||"").localeCompare(String(b.kind||""));
      case "status":
        return dir * String(a.status||"").localeCompare(String(b.status||""));
      case "period":
        av = a.period && a.period.from_utc ? Date.parse(a.period.from_utc) : 0;
        bv = b.period && b.period.from_utc ? Date.parse(b.period.from_utc) : 0;
        return dir * (av - bv);
      case "trades":
        av = a.trades != null ? a.trades : -1;
        bv = b.trades != null ? b.trades : -1;
        return dir * (av - bv);
      case "winning_pct":
        av = a.winning_pct != null ? a.winning_pct : -1;
        bv = b.winning_pct != null ? b.winning_pct : -1;
        return dir * (av - bv);
      case "net_profit":
        av = a.net_profit != null ? a.net_profit : -Infinity;
        bv = b.net_profit != null ? b.net_profit : -Infinity;
        return dir * (av - bv);
      case "confidence":
        av = computeConfidenceScore(a).score;
        bv = computeConfidenceScore(b).score;
        return dir * (av - bv);
      default:
        return dir * (a.mtime - b.mtime);
    }
  });
}

function _createdSortMs(createdAtUtc, reportNo) {
  const t = Date.parse(createdAtUtc || "");
  if (Number.isFinite(t)) return t;
  const n = Number(reportNo);
  return Number.isFinite(n) ? n : 0;
}

function _updateSortHeaders() {
  document.querySelectorAll("#jobs-table th[data-sort]").forEach(th => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sort === _sortCol) {
      th.classList.add(_sortDir === "asc" ? "sort-asc" : "sort-desc");
    }
  });
}

function _syncCheckAllState() {
  const allChk = document.getElementById("jobs-check-all");
  if (!allChk) return;
  const all = document.querySelectorAll("#jobs-table tbody input[type=checkbox]:not(:disabled)");
  const checked = [...all].filter(c => c.checked);
  allChk.indeterminate = checked.length > 0 && checked.length < all.length;
  allChk.checked = all.length > 0 && checked.length === all.length;
}

function _updateDeleteCheckedBtn() {
  for (const key of [..._checkedKeys]) {
    if (isReportFavoriteKey(key)) _checkedKeys.delete(key);
  }
  const btn = document.getElementById("btn-delete-checked");
  if (btn) btn.hidden = _checkedKeys.size === 0;
}

// ---- tree state: which strategy / strategy::group folders are collapsed ----
const _treeCollapsed = new Set(storageJsonArray("treeCollapsed"));
function _saveTreeCollapsed() {
  storageSet("treeCollapsed", JSON.stringify([..._treeCollapsed]));
}

// Extract the instrument root (e.g. "MNQ 06-26" → "MNQ", "MGC Jun 26" → "MGC")
// from a row, or "(несколько)" when a batch covers multiple roots.
function _itemInstrumentKey(it) {
  const raw = it.labelTitle || it.label || "";
  if (!raw || raw === "—") return "—";
  // labelTitle is comma-separated for batches; check distinct roots.
  const roots = new Set();
  for (const piece of String(raw).split(",")) {
    const m = piece.trim().match(/^([A-Z0-9]+)/);
    if (m) roots.add(m[1]);
  }
  if (roots.size === 0) return raw.trim() || "—";
  if (roots.size === 1) return [...roots][0];
  return `(${roots.size} инструментов)`;
}

function _ensureSelectedTreePathVisible(items, targetKey) {
  if (_reportsView !== "tree" || !targetKey) return false;
  const target = (items || []).find(it => `${it.kind}:${it.id}` === targetKey);
  if (!target) return false;
  const stratName = target.strategy || "—";
  const instName = _itemInstrumentKey(target);
  const stratKey = `S::${stratName}`;
  const instKey = `I::${stratName}::${instName}`;
  let changed = false;
  if (_treeCollapsed.delete(stratKey)) changed = true;
  if (_treeCollapsed.delete(instKey)) changed = true;
  if (changed) _saveTreeCollapsed();
  return changed;
}

function _buildCoverageDetailRow(root, profiles, row) {
  const tr = el("tr", { cls: "coverage-detail-row" });
  const cell = el("td", { cls: "coverage-detail-cell" });
  cell.colSpan = 5;
  const wrap = el("div", { cls: "coverage-detail" });
  if (!profiles.length) {
    wrap.appendChild(el("div", {
      cls: "coverage-empty",
      text: row.next_action || "Для этого инструмента пока нет карточки стратегии.",
    }));
  }
  for (const p of profiles) {
    const pr = el("div", { cls: "coverage-profile-row" });
    const main = el("div", { cls: "coverage-profile-main" });
    const bd = _COV_BADGE[p.status] || { emoji: "", label: p.status || "—" };
    main.appendChild(el("div", {
      cls: "coverage-profile-title",
      text: `${bd.emoji} ${p.name || p.profile_id || "Профиль"}`,
      title: p.profile_id || "",
    }));
    const catalogOk = _coverageState.catalogClasses.has(p.strategy_class);
    const subBits = [
      p.strategy_class || "—",
      fmtContract(p.instrument),
      p.timeframe,
      catalogOk ? "в каталоге" : "нет в каталоге",
      _profileRuntimeLabel(p),
    ].filter(Boolean);
    main.appendChild(el("div", { cls: "coverage-profile-sub", text: subBits.join(" · ") }));
    pr.appendChild(main);

    const actions = el("div", { cls: "coverage-actions" });
    const btnProfile = el("button", { cls: "coverage-mini-btn", text: "Профиль" });
    btnProfile.addEventListener("click", (ev) => {
      ev.stopPropagation();
      jumpToProfile(p.profile_id);
    });
    actions.appendChild(btnProfile);
    const ids = _profileEvidenceIds(p);
    const btnReport = el("button", { cls: "coverage-mini-btn", text: ids.length ? "Отчет" : "Нет отчета" });
    btnReport.disabled = !ids.length;
    btnReport.addEventListener("click", (ev) => {
      ev.stopPropagation();
      openEvidenceId(ids[0]);
    });
    actions.appendChild(btnReport);
    pr.appendChild(actions);
    wrap.appendChild(pr);
  }
  cell.appendChild(wrap);
  tr.appendChild(cell);
  return tr;
}

function _aggregateTreeItems(items) {
  const counts = { pending: 0, running: 0, done: 0, failed: 0, cancelled: 0 };
  let latestCreated = "";
  let latestMtime = 0;
  let minFrom = null;
  let maxTo = null;
  let trades = 0;
  let hasTrades = false;
  let weightedWins = 0;
  let weightedWinTrades = 0;
  let avgWins = 0;
  let avgWinCount = 0;
  let net = 0;
  let hasNet = false;
  let grossProfit = 0;
  let hasGrossProfit = false;
  let grossLoss = 0;
  let hasGrossLoss = false;
  let maxDrawdown = null;
  let reportNoMin = null;
  let reportNoMax = null;
  let reportNoCount = 0;

  for (const it of items || []) {
    const st = it.status || "done";
    if (counts[st] != null) counts[st] += 1;
    if (it.mtime && it.mtime >= latestMtime) {
      latestMtime = it.mtime;
      latestCreated = it.created || "";
    }
    if (it.period && it.period.from_utc && it.period.to_utc) {
      const from = Date.parse(it.period.from_utc);
      const to = Date.parse(it.period.to_utc);
      if (Number.isFinite(from) && (minFrom == null || from < minFrom)) minFrom = from;
      if (Number.isFinite(to) && (maxTo == null || to > maxTo)) maxTo = to;
    }
    if (typeof it.trades === "number" && Number.isFinite(it.trades)) {
      trades += it.trades;
      hasTrades = true;
      if (typeof it.winning_pct === "number" && Number.isFinite(it.winning_pct)) {
        weightedWins += (it.winning_pct * it.trades);
        weightedWinTrades += it.trades;
      }
    } else if (typeof it.winning_pct === "number" && Number.isFinite(it.winning_pct)) {
      avgWins += it.winning_pct;
      avgWinCount += 1;
    }
    if (typeof it.net_profit === "number" && Number.isFinite(it.net_profit)) {
      net += it.net_profit;
      hasNet = true;
    }
    if (typeof it.gross_profit === "number" && Number.isFinite(it.gross_profit)) {
      grossProfit += it.gross_profit;
      hasGrossProfit = true;
    }
    if (typeof it.gross_loss === "number" && Number.isFinite(it.gross_loss)) {
      grossLoss += it.gross_loss;
      hasGrossLoss = true;
    }
    if (typeof it.max_drawdown === "number" && Number.isFinite(it.max_drawdown)) {
      maxDrawdown = maxDrawdown == null ? it.max_drawdown : Math.min(maxDrawdown, it.max_drawdown);
    }
    if (typeof it.report_no === "number" && Number.isFinite(it.report_no)) {
      reportNoMin = reportNoMin == null ? it.report_no : Math.min(reportNoMin, it.report_no);
      reportNoMax = reportNoMax == null ? it.report_no : Math.max(reportNoMax, it.report_no);
      reportNoCount += 1;
    }
  }

  let winningPct = null;
  if (weightedWinTrades > 0) winningPct = weightedWins / weightedWinTrades;
  else if (avgWinCount > 0) winningPct = avgWins / avgWinCount;

  let profitFactor = null;
  if (hasGrossProfit && hasGrossLoss) {
    if (grossLoss < 0) profitFactor = grossProfit / Math.abs(grossLoss);
    else if (grossLoss === 0 && grossProfit > 0) profitFactor = Infinity;
  }

  const total = items.length;
  const status = summarizeBatchCounts(counts, total);
  return {
    kind: "batch",
    status,
    counts,
    total,
    report_no_min: reportNoMin,
    report_no_max: reportNoMax,
    report_no_count: reportNoCount,
    created: latestCreated,
    mtime: latestMtime,
    period: (minFrom != null && maxTo != null)
      ? { from_utc: new Date(minFrom).toISOString(), to_utc: new Date(maxTo).toISOString() }
      : null,
    trades: hasTrades ? trades : null,
    winning_pct: winningPct,
    net_profit: hasNet ? net : null,
    gross_profit: hasGrossProfit ? grossProfit : null,
    gross_loss: hasGrossLoss ? grossLoss : null,
    profit_factor: profitFactor,
    max_drawdown: maxDrawdown,
  };
}

function _aggregateReportNoText(aggregate) {
  if (!aggregate) return "—";
  const min = aggregate.report_no_min;
  const max = aggregate.report_no_max;
  const count = aggregate.report_no_count || 0;
  if (count <= 0 || min == null || max == null) return "—";
  if (min === max) return String(min);
  return `${min}-${max}`;
}

function _buildTreeGroupRow({ depth, label, strategyText, kindText, aggregate, collapsed, onToggle }) {
  const tr = el("tr");
  tr.className = `tree-folder-row tree-level-${depth}`;

  tr.appendChild(td("", { cls: "col-check" }));
  tr.appendChild(td("", { cls: "col-star" }));
  tr.appendChild(td(_aggregateReportNoText(aggregate), { cls: "col-num-compact" }));
  tr.appendChild(td(_fmtCreated(aggregate.created), { title: aggregate.created || "" }));

  const tdName = el("td", { cls: "col-rep-name" });
  tdName.textContent = `${collapsed ? "▶" : "▼"} ${label} (${aggregate.total || 0})`;
  tdName.style.paddingLeft = depth === 1 ? "10px" : "28px";
  tdName.style.fontWeight = depth === 1 ? "600" : "500";
  tr.appendChild(tdName);

  tr.appendChild(td(strategyText || "—"));

  const tdKind = el("td");
  tdKind.appendChild(el("span", {
    cls: "badge-kind batch",
    text: kindText,
  }));
  tr.appendChild(tdKind);

  const tdStatus = el("td");
  tdStatus.appendChild(el("span", {
    cls: "status-badge " + (STATUS_CLASSES[aggregate.status] || "unknown"),
    text: statusLabel(aggregate.status),
  }));
  const done = (aggregate.counts.done || 0) + (aggregate.counts.failed || 0) + (aggregate.counts.cancelled || 0);
  const statExtra = el("span", { cls: "muted", text: ` ${done}/${aggregate.total || 0}` });
  statExtra.style.marginLeft = "5px";
  tdStatus.appendChild(statExtra);
  tr.appendChild(tdStatus);

  const periodText = aggregate.period
    ? `${_fmtDatePT(aggregate.period.from_utc)} → ${_fmtDatePT(aggregate.period.to_utc)}`
    : "—";
  tr.appendChild(td(periodText, {
    title: aggregate.period ? `${aggregate.period.from_utc} → ${aggregate.period.to_utc}` : "",
  }));

  tr.appendChild(td(aggregate.trades != null ? aggregate.trades.toLocaleString() : "—", { cls: "col-num-compact" }));

  const tdWin = el("td", { cls: "col-num-compact" });
  if (aggregate.winning_pct != null) {
    tdWin.textContent = aggregate.winning_pct.toFixed(1) + "%";
    tdWin.style.color = aggregate.winning_pct >= 50 ? "#4ade80" : "#f87171";
  } else {
    tdWin.textContent = "—";
    tdWin.style.color = "#4b5563";
  }
  tr.appendChild(tdWin);

  const tdNet = el("td", { cls: "col-num-compact" });
  if (aggregate.net_profit != null && !Number.isNaN(aggregate.net_profit)) {
    tdNet.textContent = fmtMoneySign(aggregate.net_profit);
    tdNet.style.color = aggregate.net_profit > 0 ? "#4ade80"
                      : aggregate.net_profit < 0 ? "#f87171" : "#9ca3af";
  } else {
    tdNet.textContent = "—";
    tdNet.style.color = "#4b5563";
  }
  tr.appendChild(tdNet);

  tr.appendChild(renderConfidenceBadge(aggregate));
  tr.appendChild(td("", { cls: "col-del" }));

  tr.addEventListener("click", onToggle);
  return tr;
}

function _renderTreeView(filtered, tbody) {
  tbody.replaceChildren();
  // Two-level grouping: strategy → instrument-root → rows
  const stratGroups = new Map();
  for (const it of filtered) {
    const sk = it.strategy || "—";
    if (!stratGroups.has(sk)) stratGroups.set(sk, new Map());
    const ik = _itemInstrumentKey(it);
    const inst = stratGroups.get(sk);
    if (!inst.has(ik)) inst.set(ik, []);
    inst.get(ik).push(it);
  }

  for (const [stratName, instMap] of stratGroups) {
    const stratKey = `S::${stratName}`;
    const stratCollapsed = _treeCollapsed.has(stratKey);
    let stratTotal = 0;
    const stratItems = [];
    for (const arr of instMap.values()) stratTotal += arr.length;
    for (const arr of instMap.values()) stratItems.push(...arr);
    const stratAggregate = _aggregateTreeItems(stratItems);

    const trS = _buildTreeGroupRow({
      depth: 1,
      label: stratName,
      strategyText: stratName,
      kindText: "стратегия",
      aggregate: stratAggregate,
      collapsed: stratCollapsed,
      onToggle: () => {
      if (_treeCollapsed.has(stratKey)) _treeCollapsed.delete(stratKey);
      else _treeCollapsed.add(stratKey);
      _saveTreeCollapsed();
      refreshJobs();
      },
    });
    tbody.appendChild(trS);
    if (stratCollapsed) continue;

    for (const [instName, items] of instMap) {
      const instKey = `I::${stratName}::${instName}`;
      const instCollapsed = _treeCollapsed.has(instKey);
      const instAggregate = _aggregateTreeItems(items);
      const trI = _buildTreeGroupRow({
        depth: 2,
        label: instName,
        strategyText: stratName,
        kindText: "группа",
        aggregate: instAggregate,
        collapsed: instCollapsed,
        onToggle: () => {
        if (_treeCollapsed.has(instKey)) _treeCollapsed.delete(instKey);
        else _treeCollapsed.add(instKey);
        _saveTreeCollapsed();
        refreshJobs();
        },
      });
      tbody.appendChild(trI);
      if (instCollapsed) continue;

      for (const it of items) tbody.appendChild(_buildReportRow(it));
    }
  }
}

function _readJobsCache() {
  try {
    const raw = storageGet(_JOBS_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && parsed.jobsData ? parsed : null;
  } catch {
    return null;
  }
}

function _writeJobsCache(jobsData, batchesData) {
  // Disabled: browser-local report cache can outlive row schema changes and
  // render shifted cells. Server-side cache is fast enough for first paint.
}

function _jobsRenderSignature(jobsData, batchesData) {
  const treeSig = _reportsView === "tree"
    ? JSON.stringify([..._treeCollapsed].sort())
    : "";
  const favoritesSig = reportFavoriteEntries().map(x => x.key || reportFavoriteKey(x.kind, x.id)).sort().join("|");
  const jobSig = (jobsData.jobs || []).map(j =>
    [j.job_id, j.status, j.report_no, j.mtime, j.trade_count, j.net_profit].join(":")
  ).join("|");
  const batchSig = ((batchesData && batchesData.batches) || []).map(b =>
    [
      b.batch_id,
      b.report_no,
      b.total,
      b.created_at_utc,
      b.trade_count,
      b.net_profit,
      JSON.stringify(b.counts || {}),
    ].join(":")
  ).join("|");
  return [
    _jobsFilter,
    _reportsView,
    _sortCol,
    _sortDir,
    treeSig,
    favoritesSig,
    JSON.stringify(jobsData.counts || {}),
    jobSig,
    batchSig,
  ].join("||");
}

function _renderJobsPayload(jobsData, batchesData) {
  if (!jobsData) return;
  const renderSig = _jobsRenderSignature(jobsData, batchesData);
  if (_lastJobsRenderSig === renderSig) return;
  _lastJobsRenderSig = renderSig;

  const c = jobsData.counts || {};
  const cwrap = document.getElementById("jobs-counts");
  if (cwrap) {
    cwrap.replaceChildren(
      countSpan("ожид.",   c.pending),
      countSpan("в работе", c.running),
      countSpan("готово",   c.done),
      countSpan("ошибка",   c.failed),
      countSpan("отмена",   c.cancelled),
    );
  }

  const items = [];
  const favorites = reportFavoriteMap();
  const batches = (batchesData && batchesData.batches) || [];
  for (const b of batches) {
    const favKey = reportFavoriteKey("batch", b.batch_id);
    const cached = _batchNormalizedCache[b.batch_id];
    const favoriteChildrenCount = Math.max(
      Number(b.favorite_children_count || 0),
      activeBatchFavoriteChildrenCount(b.batch_id)
    );
    const rawInsts = Array.isArray(b.instruments) ? b.instruments : [];
    const insts = rawInsts.length > 0
      ? rawInsts
      : (cached && cached.instruments && cached.instruments.length > 0 ? cached.instruments : []);
    const rawPeriod = b.period || null;
    const cachedPeriod = (cached && (cached.fromUtc || cached.toUtc))
      ? { from_utc: cached.fromUtc, to_utc: cached.toUtc } : null;
    const batchPeriod = rawPeriod || cachedPeriod;
    const MAX_SHOWN = 3;
    let label;
    if (insts.length === 0) {
      label = b.name || b.batch_id;
    } else if (insts.length <= MAX_SHOWN) {
      label = insts.map(fmtContract).join(", ");
    } else {
      const head = insts.slice(0, MAX_SHOWN).map(fmtContract).join(", ");
      label = `${head} + ${insts.length - MAX_SHOWN} ещё`;
    }
    items.push({
      kind: "batch",
      id: b.batch_id,
      favorite: favorites.has(favKey) || b.favorite === true,
      favorite_children_count: favoriteChildrenCount,
      report_no: b.report_no != null ? b.report_no : null,
      label,
      labelTitle: insts.length ? insts.join(", ") : (b.name || ""),
      rawMultiContract: insts.length > 1,
      rawContractCount: insts.length,
      strategy: b.class_name || "—",
      status: summarizeBatchCounts(b.counts || {}, b.total || 0),
      counts: b.counts || {},
      total: b.total || 0,
      period: batchPeriod,
      created: b.created_at_utc || "",
      finished: b.finished_at_utc || "",
      trades: b.trade_count != null ? b.trade_count : (cached && cached.trade_count != null ? cached.trade_count : null),
      winning_pct: b.winning_pct != null ? b.winning_pct : (cached && cached.winning_pct != null ? cached.winning_pct : null),
      net_profit: b.net_profit != null ? b.net_profit : (cached && cached.net_profit != null ? cached.net_profit : null),
      profit_factor: b.profit_factor != null ? b.profit_factor : (cached && cached.profit_factor != null ? cached.profit_factor : null),
      gross_profit: b.gross_profit != null ? b.gross_profit : (cached && cached.gross_profit != null ? cached.gross_profit : null),
      gross_loss: b.gross_loss != null ? b.gross_loss : (cached && cached.gross_loss != null ? cached.gross_loss : null),
      max_drawdown: b.max_drawdown != null ? b.max_drawdown : (cached && cached.max_drawdown != null ? cached.max_drawdown : null),
      mtime: _createdSortMs(b.created_at_utc, b.report_no),
    });
  }
  for (const j of jobsData.jobs || []) {
    if (j.batch && j.batch.batch_id) continue;
    const favKey = reportFavoriteKey("job", j.job_id);
    const finished = j.finished_at_utc || j.heartbeat_at_utc || "";
    items.push({
      kind: "job",
      id: j.job_id,
      favorite: favorites.has(favKey) || j.favorite === true,
      report_no: j.report_no != null ? j.report_no : null,
      label: fmtContract(j.instrument) || j.job_id,
      labelTitle: "",
      strategy: j.class_name || "вЂ”",
      status: j.status,
      period: j.period || null,
      created: j.created_at_utc || "",
      finished,
      trades: j.trade_count != null ? j.trade_count : null,
      winning_pct: j.winning_pct != null ? j.winning_pct : null,
      net_profit: j.net_profit != null ? j.net_profit : null,
      net_profit_after_commission: j.net_profit_after_commission != null ? j.net_profit_after_commission : null,
      profit_factor: j.profit_factor != null ? j.profit_factor : null,
      gross_profit: j.gross_profit != null ? j.gross_profit : null,
      gross_loss: j.gross_loss != null ? j.gross_loss : null,
      profit_factor_after_commission: j.profit_factor_after_commission != null ? j.profit_factor_after_commission : null,
      max_drawdown: j.max_drawdown != null ? j.max_drawdown : null,
      mtime: _createdSortMs(j.created_at_utc, j.report_no),
    });
  }
  const sorted = _sortItems(items);
  const filtered = sorted.filter(it => {
    if (_jobsFilter === "all") return true;
    if (_jobsFilter === "favorite") return !!it.favorite;
    if (_jobsFilter === "failed") return it.status === "failed" || it.status === "partial_failed";
    if (_jobsFilter === "cancelled") return it.status === "cancelled" || it.status === "partial_cancelled";
    return it.status === _jobsFilter;
  });
  const tbody = document.querySelector("#jobs-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  if (_pendingRevealReportKey) _ensureSelectedTreePathVisible(filtered, _pendingRevealReportKey);
  if (_reportsView === "tree") _renderTreeView(filtered, tbody);
  else filtered.forEach(it => tbody.appendChild(_buildReportRow(it)));
  _applySelectedReportSelection({});
  _updateSortHeaders();
  _syncCheckAllState();
  _updateDeleteCheckedBtn();
  setTimeout(maybeLoadMoreReports, 0);
  scheduleReportsAutoPrefetch();
}

let _refreshInFlight = false;

function _resetReportsPaging() {
  if (_reportsPrefetchTimer) {
    clearTimeout(_reportsPrefetchTimer);
    _reportsPrefetchTimer = null;
  }
  _reportsPrefetchToken += 1;
  _reportsPrefetchInFlight = false;
  _reportsPaging = {
    offset: 0,
    total: 0,
    hasMore: true,
    loading: false,
  };
  _jobsPayload = null;
  _lastJobsRenderSig = "";
}

function _mergeById(existing, incoming, idKey) {
  const out = Array.isArray(existing) ? existing.slice() : [];
  const index = new Map();
  out.forEach((item, i) => {
    if (item && item[idKey]) index.set(item[idKey], i);
  });
  (Array.isArray(incoming) ? incoming : []).forEach(item => {
    if (!item || !item[idKey]) return;
    if (index.has(item[idKey])) {
      const i = index.get(item[idKey]);
      out[i] = Object.assign({}, out[i], item);
    } else {
      index.set(item[idKey], out.length);
      out.push(item);
    }
  });
  return out;
}

function _mergeReportsPayload(reportsData) {
  const current = _jobsPayload || {
    jobsData: { jobs: [], counts: {} },
    batchesData: { batches: [] },
    reportsData: { offset: 0, limit: 0, total: 0 },
  };
  const mergedJobs = reportsData
    ? Object.assign({}, current.jobsData || {}, {
        counts: reportsData.counts || {},
        jobs: _mergeById((current.jobsData || {}).jobs, reportsData.jobs, "job_id"),
      })
    : (current.jobsData || { jobs: [], counts: {} });
  const mergedBatches = reportsData
    ? Object.assign({}, current.batchesData || {}, {
        batches: _mergeById((current.batchesData || {}).batches, reportsData.batches, "batch_id"),
      })
    : (current.batchesData || { batches: [] });
  const mergedMeta = reportsData
    ? {
        offset: reportsData.offset || 0,
        limit: reportsData.limit || 0,
        total: reportsData.total || 0,
      }
    : (current.reportsData || { offset: 0, limit: 0, total: 0 });
  _jobsPayload = { jobsData: mergedJobs, batchesData: mergedBatches, reportsData: mergedMeta };
  _writeJobsCache(mergedJobs, mergedBatches);
  _jobsCacheShown = true;
}

function _reportsHasMore() {
  return !!_reportsPaging.hasMore;
}

function _reportsQuery(offset, limit) {
  const qs = new URLSearchParams({
    offset: String(Math.max(0, Number(offset) || 0)),
    limit: String(Math.max(1, Number(limit) || REPORTS_PAGE_SIZE)),
    sort: _sortCol || "mtime",
    dir: _sortDir || "desc",
    filter: _jobsFilter || "all",
  });
  return `/api/reports?${qs.toString()}`;
}

async function _loadReportsPage(reset) {
  if (reset) {
    _resetReportsPaging();
    const wrap = document.querySelector(".reports-wrap");
    if (wrap) wrap.scrollTop = 0;
  }
  if (_reportsPaging.loading) return;
  if (!_reportsHasMore()) {
    if (_jobsPayload) _renderJobsPayload(_jobsPayload.jobsData, _jobsPayload.batchesData || { batches: [] });
    return;
  }
  _reportsPaging.loading = true;
  try {
    const pageLimit = reset ? REPORTS_RESET_PAGE_SIZE : REPORTS_PAGE_SIZE;
    const reportsData = await api.get(_reportsQuery(_reportsPaging.offset, pageLimit));
    if (reportsData) {
      const gotJobs = Array.isArray(reportsData.jobs) ? reportsData.jobs.length : 0;
      const gotBatches = Array.isArray(reportsData.batches) ? reportsData.batches.length : 0;
      const got = gotJobs + gotBatches;
      const base = Number.isFinite(Number(reportsData.offset)) ? Number(reportsData.offset) : _reportsPaging.offset;
      const total = Number.isFinite(Number(reportsData.total)) ? Number(reportsData.total) : base + got;
      _reportsPaging.offset = base + got;
      _reportsPaging.total = total;
      _reportsPaging.hasMore = got > 0 && _reportsPaging.offset < total;
      _mergeReportsPayload(reportsData);
      _renderJobsPayload(_jobsPayload.jobsData, _jobsPayload.batchesData || { batches: [] });
    } else {
      _reportsPaging.hasMore = false;
    }
  } finally {
    _reportsPaging.loading = false;
  }
}

// Fetches page 1 of jobs/batches and merges into the existing payload so that
// new entries appear without resetting the user's scroll position or pagination state.
async function _pollReportsPage() {
  try {
    const reportsData = await api.get(_reportsQuery(0, REPORTS_PAGE_SIZE));
    if (reportsData) {
      _mergeReportsPayload(reportsData);
      // Force re-render after every successful poll so status changes are
      // never silently skipped by the signature cache.
      _lastJobsRenderSig = "";
      _renderJobsPayload(_jobsPayload.jobsData, _jobsPayload.batchesData || { batches: [] });
    }
  } catch (e) { /* transient network error — next tick will retry */ }
}

async function refreshJobs(opts) {
  const options = opts || {};
  const reset  = options.reset  === true;
  const append = options.append === true;
  const poll   = options.poll   === true;   // background poll: bypass guard, keep existing payload
  if (_jobsPayload) {
    _renderJobsPayload(_jobsPayload.jobsData, _jobsPayload.batchesData || { batches: [] });
  }
  if (_refreshInFlight) return;
  if (!reset && !append && !poll && _jobsPayload) return;
  _refreshInFlight = true;
  try {
    if (poll && !reset) {
      await _pollReportsPage();
    } else {
      await _loadReportsPage(reset);
    }
  } finally {
    _refreshInFlight = false;
  }
}

function maybeLoadMoreReports() {
  const wrap = document.querySelector(".reports-wrap");
  if (!wrap || _reportsPaging.loading || _reportsPrefetchInFlight || !_reportsHasMore()) return;
  const distance = wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight;
  if (distance <= 240) refreshJobs({ append: true });
}

function scheduleReportsAutoPrefetch() {
  if (!REPORTS_BACKGROUND_PREFETCH_ENABLED) return;
  if (_reportsPrefetchTimer || !_reportsHasMore()) return;
  _reportsPrefetchTimer = setTimeout(() => {
    _reportsPrefetchTimer = null;
    if (!_reportsHasMore() || _reportsPrefetchInFlight) return;
    if (_reportsPaging.loading || _refreshInFlight) {
      scheduleReportsAutoPrefetch();
      return;
    }
    prefetchRemainingReports();
  }, REPORTS_BACKGROUND_PREFETCH_DELAY_MS);
}

async function prefetchRemainingReports() {
  if (_reportsPrefetchInFlight || _reportsPaging.loading || _refreshInFlight || !_reportsHasMore()) return;
  const token = _reportsPrefetchToken;
  _reportsPrefetchInFlight = true;
  try {
    const remaining = _reportsPaging.total > _reportsPaging.offset
      ? _reportsPaging.total - _reportsPaging.offset
      : REPORTS_BACKGROUND_PAGE_SIZE;
    const pageLimit = Math.max(
      REPORTS_PAGE_SIZE,
      Math.min(REPORTS_BACKGROUND_PAGE_SIZE, remaining)
    );
    const reportsData = await api.get(_reportsQuery(_reportsPaging.offset, pageLimit));
    if (token !== _reportsPrefetchToken || !reportsData) return;
    const gotJobs = Array.isArray(reportsData.jobs) ? reportsData.jobs.length : 0;
    const gotBatches = Array.isArray(reportsData.batches) ? reportsData.batches.length : 0;
    const got = gotJobs + gotBatches;
    const base = Number.isFinite(Number(reportsData.offset)) ? Number(reportsData.offset) : _reportsPaging.offset;
    const total = Number.isFinite(Number(reportsData.total)) ? Number(reportsData.total) : base + got;
    _reportsPaging.offset = base + got;
    _reportsPaging.total = total;
    _reportsPaging.hasMore = got > 0 && _reportsPaging.offset < total;
    _mergeReportsPayload(reportsData);
    _renderJobsPayload(_jobsPayload.jobsData, _jobsPayload.batchesData || { batches: [] });
  } catch (e) {
    // Keep the first page usable; scroll pagination or the next refresh can retry.
  } finally {
    _reportsPrefetchInFlight = false;
    if (token === _reportsPrefetchToken && _reportsHasMore()) scheduleReportsAutoPrefetch();
  }
}

async function _refreshJobsLegacyUnused() {
  if (_jobsPayload) {
    _renderJobsPayload(_jobsPayload.jobsData, _jobsPayload.batchesData || { batches: [] });
  }
  if (_refreshInFlight) return;
  _refreshInFlight = true;
  try {
  const [jobsRes, batchesRes] = await Promise.allSettled([
    api.get("/api/jobs?limit=500"),
    api.get("/api/batches?limit=1000"),
  ]);
  const jobsDataFast = jobsRes.status === "fulfilled" ? jobsRes.value : null;
  const batchesDataFast = batchesRes.status === "fulfilled" ? batchesRes.value : { batches: [] };
  if (!jobsDataFast) return;
  _jobsCacheShown = true;
  _jobsPayload = { jobsData: jobsDataFast, batchesData: batchesDataFast };
  _writeJobsCache(jobsDataFast, batchesDataFast);
  _renderJobsPayload(jobsDataFast, batchesDataFast);
  return;
  let jobsData = null, batchesData = null;
  try { jobsData = await api.get("/api/jobs?limit=500"); } catch (e) { /* noop */ }
  try { batchesData = await api.get("/api/batches?limit=100"); } catch (e) { /* noop */ }
  if (!jobsData) return;

  // Top counts come from the queue-wide aggregate (not derived per row).
  const c = jobsData.counts || {};
  const cwrap = document.getElementById("jobs-counts");
  if (cwrap) {
    cwrap.replaceChildren(
      countSpan("ожид.",   c.pending),
      countSpan("в работе", c.running),
      countSpan("готово",   c.done),
      countSpan("ошибка",   c.failed),
      countSpan("отмена",   c.cancelled),
    );
  }

  // Build a unified item list: one row per batch + one row per standalone
  // job. Jobs that belong to a batch are hidden behind their batch row.
  const items = [];
  const batches = (batchesData && batchesData.batches) || [];
  for (const b of batches) {
    // Phase 22d — show instruments (not strategy class) in the "Имя / инструмент"
    // column so batch rows don't duplicate the strategy column. Show first 2-3
    // contracts and a "+ N ещё" suffix when the basket is larger.
    // Phase 22h — prefer _batchNormalizedCache (derived from children on first
    // openBatch() call) over raw API data, so polling refreshes never revert
    // the parent row back to "strategy.name ×N" / "—" after normalization.
    const cached = _batchNormalizedCache[b.batch_id];
    const rawInsts = Array.isArray(b.instruments) ? b.instruments : [];
    const insts = (rawInsts.length > 0) ? rawInsts
                : (cached && cached.instruments && cached.instruments.length > 0)
                  ? cached.instruments : [];
    const rawPeriod = b.period || null;
    const cachedPeriod = (cached && (cached.fromUtc || cached.toUtc))
      ? { from_utc: cached.fromUtc, to_utc: cached.toUtc } : null;
    const batchPeriod = rawPeriod || cachedPeriod;
    const MAX_SHOWN = 3;
    let label;
    if (insts.length === 0) {
      label = b.name || b.batch_id;
    } else if (insts.length <= MAX_SHOWN) {
      label = insts.map(fmtContract).join(", ");
    } else {
      const head = insts.slice(0, MAX_SHOWN).map(fmtContract).join(", ");
      label = `${head} + ${insts.length - MAX_SHOWN} ещё`;
    }
    items.push({
      kind: "batch",
      id: b.batch_id,
      report_no: b.report_no != null ? b.report_no : null,
      label: label,
      labelTitle: insts.length ? insts.join(", ") : (b.name || ""),
      strategy: b.class_name || "—",
      status: summarizeBatchCounts(b.counts || {}, b.total || 0),
      counts: b.counts || {},
      total: b.total || 0,
      period: batchPeriod,
      created: b.created_at_utc || "",
      finished: b.finished_at_utc || "",
      trades: b.trade_count != null ? b.trade_count : (cached && cached.trade_count != null ? cached.trade_count : null),
      winning_pct: b.winning_pct != null ? b.winning_pct : (cached && cached.winning_pct != null ? cached.winning_pct : null),
      net_profit: b.net_profit != null ? b.net_profit : (cached && cached.net_profit != null ? cached.net_profit : null),
      profit_factor: b.profit_factor != null ? b.profit_factor : (cached && cached.profit_factor != null ? cached.profit_factor : null),
      gross_profit: b.gross_profit != null ? b.gross_profit : (cached && cached.gross_profit != null ? cached.gross_profit : null),
      gross_loss: b.gross_loss != null ? b.gross_loss : (cached && cached.gross_loss != null ? cached.gross_loss : null),
      max_drawdown:  b.max_drawdown  != null ? b.max_drawdown  : (cached && cached.max_drawdown != null ? cached.max_drawdown : null),
      mtime: b.created_at_utc ? Date.parse(b.created_at_utc) : 0,
    });
  }
  for (const j of jobsData.jobs || []) {
    if (j.batch && j.batch.batch_id) continue;
    const finished = j.finished_at_utc || j.heartbeat_at_utc || "";
    items.push({
      kind: "job",
      id: j.job_id,
      report_no: j.report_no != null ? j.report_no : null,
      label: fmtContract(j.instrument) || j.job_id,
      labelTitle: "",
      strategy: j.class_name || "—",
      status: j.status,
      period: j.period || null,
      created: j.created_at_utc || "",
      finished: finished,
      trades: j.trade_count != null ? j.trade_count : null,
      winning_pct: j.winning_pct != null ? j.winning_pct : null,
      net_profit: j.net_profit != null ? j.net_profit : null,
      net_profit_after_commission: j.net_profit_after_commission != null ? j.net_profit_after_commission : null,
      profit_factor: j.profit_factor != null ? j.profit_factor : null,
      gross_profit: j.gross_profit != null ? j.gross_profit : null,
      gross_loss: j.gross_loss != null ? j.gross_loss : null,
      profit_factor_after_commission: j.profit_factor_after_commission != null ? j.profit_factor_after_commission : null,
      max_drawdown:  j.max_drawdown  != null ? j.max_drawdown  : null,
      mtime: j.mtime ? j.mtime * 1000
              : (j.created_at_utc ? Date.parse(j.created_at_utc) : 0),
    });
  }
  const sorted = _sortItems(items);

  // Apply the toolbar status filter.
  const filtered = sorted.filter(it =>
    _jobsFilter === "all" ? true : (it.status === _jobsFilter)
  );

  const tbody = document.querySelector("#jobs-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();

  if (_reportsView === "tree") {
    _renderTreeView(filtered, tbody);
  } else {
    filtered.forEach(it => tbody.appendChild(_buildReportRow(it)));
  }
  _updateSortHeaders();
  _syncCheckAllState();
  _updateDeleteCheckedBtn();
  } finally {
    _refreshInFlight = false;
  }
}

function _buildReportRow(it) {
  const tr = el("tr");
  const favState = reportFavoriteState(it.kind, it.id, !!it.favorite);
  const repKey = favState.key;
  const favorite = favState.favorite;
  const favoriteBusy = favState.favoriteBusy;
  const canFavoriteHere = canFavoriteTopReport(it);
  const batchHasFavoriteChildren = it.kind === "batch" && Number(it.favorite_children_count || 0) > 0;
  const deleteProtected = favorite || favoriteBusy || batchHasFavoriteChildren;
  const deleteProtectTitle = favorite
    ? "Избранный отчёт защищён от удаления. Сначала снимите звезду."
    : batchHasFavoriteChildren
      ? "Внутри этого пакета есть избранный отчёт. Сначала снимите звезду с конкретного запуска в нижней таблице или в панели избранного."
      : "Выбрать для удаления";
  tr.dataset.repkey = repKey;
  if (tr.dataset.repkey === _selectedReportKey) tr.classList.add("selected");
  if (favorite) tr.classList.add("favorite");
  tr._item = it;  // for tree re-render

  // 0a) Checkbox column
  const tdCheck = el("td", { cls: "col-check" });
  const chk = document.createElement("input");
  chk.type = "checkbox";
  chk.dataset.repkey = repKey;
  chk.disabled = deleteProtected;
  chk.title = deleteProtectTitle;
  if (deleteProtected) _checkedKeys.delete(repKey);
  chk.checked = !deleteProtected && _checkedKeys.has(repKey);
  chk.addEventListener("change", (ev) => {
    ev.stopPropagation();
    const key = repKey;
    if (chk.checked) _checkedKeys.add(key);
    else _checkedKeys.delete(key);
    _syncCheckAllState();
    _updateDeleteCheckedBtn();
  });
  tdCheck.appendChild(chk);
  tr.appendChild(tdCheck);

  // 0b) Favorite star — protected reports cannot be deleted until unstarred.
  const tdStar = el("td", { cls: "col-star" });
  if (canFavoriteHere || favorite || favoriteBusy) {
    const btnStar = el("button");
    btnStar.type = "button";
    btnStar.disabled = favoriteBusy || !canFavoriteHere;
    btnStar.className = "report-star" + (favorite ? " active" : "") + (favoriteBusy ? " pending" : "");
    btnStar.textContent = favorite ? "★" : "☆";
    btnStar.title = favoriteBusy
      ? "Сохраняем изменение избранного..."
      : canFavoriteHere
        ? (favorite
            ? "В избранном. Нажмите, чтобы снять защиту удаления."
            : "Добавить отчёт в избранные")
        : "Пакетный отчёт нельзя добавлять в избранное сверху. Выберите конкретный запуск в нижней таблице.";
    btnStar.setAttribute("aria-label", btnStar.title);
    btnStar.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (favoriteBusy || !canFavoriteHere) return;
      toggleReportFavorite(it.kind, it.id);
    });
    tdStar.appendChild(btnStar);
  } else {
    const blocked = el("span", {
      cls: "report-star-blocked",
      text: "",
      title: "Для пакетного отчёта избранное ставится на конкретном запуске в нижней таблице.",
    });
    tdStar.appendChild(blocked);
  }
  tr.appendChild(tdStar);

  // Phase 22e — column order: ★, №, Создан, Имя, Стратегия, Тип, Статус,
  //   Период, Сделок, Win%, Итог, Доверие, ×

  // 0) № — persistent report number assigned by the backend.
  tr.appendChild(td(it.report_no != null ? it.report_no : "—", { cls: "col-num-compact" }));

  // 1) Создан — short ISO timestamp; full value as title.
  tr.appendChild(td(_fmtCreated(it.created), { title: it.created || "" }));

  // 2) Имя — instrument(s) for jobs and batches; never strategy class.
  const tdName = el("td", { cls: "col-rep-name" });
  tdName.textContent = it.label || "—";
  if (it.rawMultiContract) {
    const rawBadge = el("span", {
      cls: "raw-batch-badge",
      text: `RAW x${it.rawContractCount || ""}`.trim(),
      title: "Raw batch sum across multiple contracts; use profile/canonical research metrics for demo decisions.",
    });
    tdName.appendChild(document.createTextNode(" "));
    tdName.appendChild(rawBadge);
  }
  const kindLabel = it.kind === "batch" ? "Пакет" : "Запуск";
  tdName.title = it.labelTitle
    ? `${kindLabel}: ${it.id}\nИнструменты: ${it.labelTitle}`
      + (it.rawMultiContract ? "\nRAW multi-contract batch: metrics are summed across contracts." : "")
    : `${kindLabel}: ${it.id}`;
  tr.appendChild(tdName);

  // 3) Стратегия
  tr.appendChild(td(it.strategy));

  // 4) Тип
  const tdKind = el("td");
  tdKind.appendChild(el("span", {
    cls: "badge-kind " + it.kind,
    text: it.kind === "batch"
            ? `пакет ×${it.total || ""}`.trim()
            : "запуск",
  }));
  tr.appendChild(tdKind);

  // 5) Статус (for batches show counts inline)
  const tdSt = el("td");
  tdSt.appendChild(el("span", {
    cls: "status-badge " + (STATUS_CLASSES[it.status] || "unknown"),
    text: statusLabel(it.status),
  }));
  if (it.kind === "batch" && it.counts && it.total) {
    const cb = it.counts;
    const done = (cb.done||0) + (cb.failed||0) + (cb.cancelled||0) + (cb.missing||0);
    const span = el("span", { cls: "muted",
      text: ` ${done}/${it.total}` });
    span.style.marginLeft = "5px";
    tdSt.appendChild(span);
  }
  tr.appendChild(tdSt);

  // 6) Период — never empty, show "—" if unknown.
  const period = it.period
    ? `${_fmtDatePT(it.period.from_utc)} → ${_fmtDatePT(it.period.to_utc)}`
    : "—";
  tr.appendChild(td(period, {
    title: it.period ? `${it.period.from_utc} → ${it.period.to_utc}` : "" }));

  // 7) Сделок
  tr.appendChild(td(it.trades != null ? it.trades : "—", { cls: "col-num-compact" }));

  // Win % — green if ≥50, red if <50
  const tdWin = el("td", { cls: "col-num-compact" });
  if (it.winning_pct != null) {
    tdWin.textContent = it.winning_pct.toFixed(1) + "%";
    tdWin.style.color = it.winning_pct >= 50 ? "#4ade80" : "#f87171";
  } else {
    tdWin.textContent = "—";
    tdWin.style.color = "#4b5563";
  }
  tr.appendChild(tdWin);

  // Итог (net profit). Pending/running rows show "—".
  const tdNet = el("td", { cls: "col-num-compact" });
  if (it.net_profit != null && !Number.isNaN(it.net_profit)) {
    tdNet.textContent = fmtMoneySign(it.net_profit);
    tdNet.style.color = it.net_profit > 0 ? "#4ade80"
                      : it.net_profit < 0 ? "#f87171" : "#9ca3af";
  } else {
    tdNet.textContent = "—";
    tdNet.style.color = "#4b5563";
  }
  tr.appendChild(tdNet);

  // Доверие (Phase 22d) — Backtest Confidence Score 0-100% with tooltip.
  tr.appendChild(renderConfidenceBadge(it));

  // Delete button (×) — stops propagation so it doesn't open the report.
  const tdDel = el("td", { cls: "col-del" });
  const btnDel = el("button");
  btnDel.className = "btn-row-delete" + (deleteProtected ? " locked" : "");
  btnDel.disabled = deleteProtected;
  btnDel.title = favorite
    ? "Избранный отчёт нельзя удалить. Сначала снимите звезду."
    : batchHasFavoriteChildren
      ? "Внутри пакета есть избранный отчёт. Сначала снимите звезду с конкретного запуска."
      : "Удалить отчёт";
  btnDel.textContent = "×";
  btnDel.addEventListener("click", (ev) => {
    ev.stopPropagation();
    if (deleteProtected) return;
    deleteReport(it.kind, it.id);
  });
  tdDel.appendChild(btnDel);
  tr.appendChild(tdDel);

  tr.addEventListener("click", () => {
    setSelectedReport(it.kind, it.id, { scroll: true });
    if (it.kind === "batch") openBatch(it.id);
    else openResult(it.id);
  });
  return tr;
}

async function deleteReport(kind, id) {
  if (isReportFavorite(kind, id)) {
    alert("Этот отчёт в избранном. Сначала снимите звезду, затем удаляйте.");
    return;
  }
  const label = kind === "batch" ? "пакет" : "запуск";
  if (!confirm(`Удалить ${label} «${id}»? Это действие необратимо.`)) return;
  const url = kind === "batch"
    ? `/api/batches/${encodeURIComponent(id)}`
    : `/api/jobs/${encodeURIComponent(id)}`;
  try {
    await api.delete(url);
  } catch (e) {
    alert(`Не удалось удалить: ${e.message}`);
    return;
  }
  // If the deleted report was the one currently displayed, clear the detail area.
  if (_selectedReportKey === `${kind}:${id}`) {
    _selectedReportKey = null;
    document.getElementById("result-content").hidden = true;
    document.getElementById("result-empty").hidden = false;
  }
  refreshJobs({ reset: true });
}

async function deleteCheckedReports() {
  if (_checkedKeys.size === 0) return;
  const blocked = [..._checkedKeys].filter(isReportFavoriteKey);
  blocked.forEach(key => _checkedKeys.delete(key));
  const keys = [..._checkedKeys];
  if (blocked.length && !keys.length) {
    alert("Все выбранные отчёты находятся в избранном. Сначала снимите звёзды.");
    _updateDeleteCheckedBtn();
    _syncCheckAllState();
    return;
  }
  const extra = blocked.length ? `\n\n${blocked.length} избранных отчётов пропущены.` : "";
  if (!confirm(`Удалить ${keys.length} отмеченных отчётов? Это действие необратимо.${extra}`)) return;
  let errors = 0;
  for (const key of keys) {
    const [kind, ...rest] = key.split(":");
    const id = rest.join(":");
    const url = kind === "batch"
      ? `/api/batches/${encodeURIComponent(id)}`
      : `/api/jobs/${encodeURIComponent(id)}`;
    try {
      await api.delete(url);
      _checkedKeys.delete(key);
      if (_selectedReportKey === key) {
        _selectedReportKey = null;
        document.getElementById("result-content").hidden = true;
        document.getElementById("result-empty").hidden = false;
      }
    } catch { errors++; }
  }
  if (errors) alert(`Не удалось удалить ${errors} отчётов.`);
  _updateDeleteCheckedBtn();
  refreshJobs({ reset: true });
}

function countSpan(name, n) {
  const s = el("span");
  s.appendChild(el("b", { text: name }));
  s.appendChild(document.createTextNode(`: ${n ?? 0}`));
  return s;
}

// ---------------- result tab ----------------------------------------------
let _tradesOffset = 0;
const TRADES_PAGE = 100;
let _allTrades = [];        // full trades.json (loaded once per job)
let _filteredTrades = [];   // after side+pnl filters
let _selectedTradeNo = null;
let _bars = null;           // OHLCV array for the chart
let _barsState = "idle";    // idle|loading|ok|missing|error
let _barsLoadingFor = null;
let _drawObjects = [];      // strategy draw objects (universal schema)
let _drawObjectsState = { exported: false, reason: "idle", diagnostics: [] };
let _drawObjectsLoadingFor = null;
let _chartHover = null;
let _resultJob = null;      // last loaded job for chart cross-reference

const _tradeFilters = { side: "all", pnl: "all" };

let _activeBatch = null;        // batch detail object, or null for single-job mode
let _activeBatchRows = [];      // rows[] from /api/batches/{id}/results
let _batchPollTimer = null;     // setTimeout id for auto-refresh while jobs run
let _activeResultReportNo = null;
// Phase 22h — persistent normalized display data derived from batch children.
// Keyed by batch_id. Survives refreshJobs() re-renders so the top table never
// reverts to the raw "strategy.name ×N" / "—" values after polling updates.
const _batchNormalizedCache = {}; // { [batchId]: { instruments: [...], fromUtc, toUtc } }
const _batchHydrateInFlight = new Set();

async function openResult(jobId) {
  // Load the job header to detect batch membership; if part of a batch we
  // route through openBatch so the operator sees the multi-instrument top
  // table. Single-instrument runs get a synthesized one-row table.
  // Reports panel is in-page now; just clear any leftover overlay state.
  document.getElementById("result-empty").hidden = true;
  document.getElementById("result-content").hidden = false;
  document.getElementById("error-box").hidden = true;
  document.getElementById("result-job-id").textContent = jobId;

  let job;
  try { job = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`); }
  catch (e) {
    document.getElementById("error-box").hidden = false;
    document.getElementById("error-box").textContent = `Не удалось загрузить запуск: ${e.message}`;
    return;
  }

  const batchId = job.batch && job.batch.batch_id;
  if (batchId) {
    await openBatch(batchId, jobId);
    return;
  }
  _activeResultReportNo = job.report_no != null ? job.report_no : null;
  // Standalone job: highlight in reports panel.
  setSelectedReport("job", jobId, { scroll: true, reveal: true });

  // ---- Single-job mode: hide batch bar, render 1-row top table ---------
  _activeBatch = null;
  _activeBatchRows = [];
  if (_batchPollTimer) { clearTimeout(_batchPollTimer); _batchPollTimer = null; }
  const bar = document.getElementById("batch-bar");
  if (bar) bar.hidden = true;

  const m = (job.result && job.result.metrics) || {};
  const period_check = computePeriodCheck(job);
  const singleRow = {
    batch_index: 0,
    instrument: ((job.result && job.result.context && job.result.context.instrument && (job.result.context.instrument.full_name || job.result.context.instrument.name))
                 || job.instrument || ""),
    job_id: jobId,
    status: job.status,
    metrics: {
      trade_count:   m.trade_count,
      net_profit:    m.net_profit,
      gross_profit:  m.gross_profit,
      gross_loss:    m.gross_loss,
      profit_factor: m.profit_factor,
      max_drawdown:  m.max_drawdown,
      winning_pct:   m.winning_pct,
    },
    period_check: period_check,
    error: job.error || null,
    _job: job,
    _strategy_class: (job.result?.context?.strategy?.class_name) || job.class_name || "",
    _params: (job.result?.context?.strategy?.parameters) || (job.strategy?.parameters) || {},
    _detail_index: 1,
  };
  _activeBatchRows = [singleRow];
  renderResultRowsTable(_activeBatchRows, jobId);
  await setActiveJob(jobId, job);
}

async function openBatch(batchId, focusJobId) {
  setSelectedReport("batch", batchId, { scroll: true, reveal: true });
  document.getElementById("result-empty").hidden = true;
  document.getElementById("result-content").hidden = false;
  document.getElementById("error-box").hidden = true;

  let data;
  try { data = await api.get(`/api/batches/${encodeURIComponent(batchId)}/results`); }
  catch (e) {
    document.getElementById("error-box").hidden = false;
    document.getElementById("error-box").textContent =
      `Не удалось загрузить batch ${batchId}: ${e.message}`;
    return;
  }
  _activeBatch = data;
  _activeResultReportNo = data.report_no != null ? data.report_no : null;
  _activeBatchRows = (data.rows || []).slice();

  // Decorate rows for table render: strategy class + params from manifest.
  const stratClass = (data.strategy && data.strategy.class_name) || "";
  const params = (data.strategy && data.strategy.parameters) || {};
  for (const r of _activeBatchRows) {
    r._strategy_class = stratClass;
    r._params = params;
    r._detail_index = (typeof r.batch_index === "number" && Number.isFinite(r.batch_index))
      ? (r.batch_index + 1)
      : null;
  }

  const bar = document.getElementById("batch-bar");
  if (bar) {
    bar.hidden = false;
    document.getElementById("batch-bar-name").textContent =
      `${data.name || data.batch_id}`;
    const c = data.counts || {};
    document.getElementById("batch-bar-counts").textContent =
      `total ${data.total} · pending ${c.pending||0} · running ${c.running||0}` +
      ` · done ${c.done||0} · failed ${c.failed||0}` +
      (c.cancelled ? ` · cancelled ${c.cancelled}` : "") +
      (c.missing   ? ` · missing ${c.missing}`     : "");
    const refresh = document.getElementById("batch-refresh");
    if (refresh) refresh.onclick = () => openBatch(batchId, focusJobId);
  }

  // Decide which row is the "active" one. During auto-refresh poll keep the
  // user's current selection if it still exists in this batch; otherwise
  // prefer focusJobId, then first done, then first row.
  let pick = null;
  if (_selectedJob && _activeBatchRows.some(r => r.job_id === _selectedJob)) {
    pick = _selectedJob;
  }
  if (!pick) pick = focusJobId;
  if (!pick) {
    const doneRow = _activeBatchRows.find(r => r.status === "done");
    pick = (doneRow && doneRow.job_id) || (_activeBatchRows[0] && _activeBatchRows[0].job_id);
  }
  document.getElementById("result-job-id").textContent = pick || batchId;
  renderResultRowsTable(_activeBatchRows, pick);
  // Patch the parent batch row in the top table with instrument/period data
  // derived from the children. This corrects display even when the running
  // server process has an old list_batches() that lacks these fields.
  normalizeBatchReportRow(batchId, _activeBatchRows);
  if (pick) await setActiveJob(pick, null);

  // Auto-refresh while jobs are still in flight.
  const c = data.counts || {};
  const inFlight = (c.pending || 0) + (c.running || 0);
  if (_batchPollTimer) { clearTimeout(_batchPollTimer); _batchPollTimer = null; }
  if (inFlight > 0 && _activeBatch && _activeBatch.batch_id === batchId) {
    _batchPollTimer = setTimeout(() => {
      // Only re-poll if user is still looking at this batch.
      if (_activeBatch && _activeBatch.batch_id === batchId) {
        openBatch(batchId, focusJobId);
      }
    }, 2500);
  }
}

/**
 * Derives instruments and period from already-loaded child rows and:
 *   1. Writes results to _batchNormalizedCache so refreshJobs() polling
 *      never reverts the parent row to raw "strategy.name ×N" / "—".
 *   2. Patches the parent <tr> DOM cells immediately.
 *
 * Period derivation order:
 *   a) min/max across children's r.period (populated by updated read_batch_results)
 *   b) _activeBatch.period  (batch-manifest level, always present for new batches)
 *   c) null  → period cell left as-is
 *
 * Acceptance criteria (phase 22h):
 *   1. Parent row never shows "StrategyName ×N" in Имя when child instruments exist.
 *   2. Parent row shows correct merged period from children.
 *   3. If children have different periods: min(from) → max(to).
 *   4. Duplicate instruments are de-duplicated.
 *   5. More than 3 instruments: show first 3 + "+ N more".
 *   6. Normalization survives polling refreshes (cache is consulted in refreshJobs).
 */
function normalizeBatchReportRow(batchId, rows) {
  if (!batchId || !rows || rows.length === 0) return;
  const summary = _deriveBatchSummaryFromRows(rows);
  const BATCH_ROW_COL = {
    check: 0,
    star: 1,
    reportNo: 2,
    created: 3,
    name: 4,
    strategy: 5,
    kind: 6,
    status: 7,
    period: 8,
    trades: 9,
    winPct: 10,
    net: 11,
    confidence: 12,
    del: 13,
  };

  // 1. Derive unique instruments from child rows (preserve insertion order).
  const instruments = summary.instruments;

  // 2. Derive covering period: min(from_utc) → max(to_utc) across children.
  //    Fall back to _activeBatch.period when children lack per-row periods
  //    (old server process: read_batch_results did not include period per child).
  let fromUtc = summary.fromUtc, toUtc = summary.toUtc;
  // Fallback: use batch-manifest period when children lack per-row periods.
  if (!fromUtc && _activeBatch && _activeBatch.batch_id === batchId) {
    const bp = _activeBatch.period;
    if (bp) { fromUtc = bp.from_utc || null; toUtc = bp.to_utc || null; }
  }

  // 3. Persist to cache so refreshJobs() polling does not revert the row.
  if (instruments.length > 0 || fromUtc || summary.trade_count != null) {
    _batchNormalizedCache[batchId] = { ...summary, instruments, fromUtc, toUtc };
  }

  console.debug("[normalizeBatchReportRow]", batchId,
    "instruments:", instruments,
    "period:", fromUtc, "→", toUtc,
    "cached:", !!_batchNormalizedCache[batchId]);

  if (instruments.length === 0 && !fromUtc) return; // nothing to patch

  // 4. Find the parent <tr> in the top reports table.
  const tr = document.querySelector(`#jobs-table tr[data-repkey="batch:${batchId}"]`);
  if (!tr) return;
  const cells = tr.cells;
  // Column layout (matches thead in index.html):
  //   0:check  1:star  2:№  3:Создан  4:Имя  5:Стратегия  6:Тип
  //   7:Статус  8:Период  9:Сделок  10:Win%  11:Итог  12:Доверие  13:delete
  if (!cells || cells.length < (BATCH_ROW_COL.confidence + 1)) return;

  // 4a. Patch "Имя" (index 2) — instrument list, never strategy name.
  if (instruments.length > 0) {
    const MAX_SHOWN = 3;
    let label;
    if (instruments.length <= MAX_SHOWN) {
      label = instruments.map(fmtContract).join(", ");
    } else {
      const head = instruments.slice(0, MAX_SHOWN).map(fmtContract).join(", ");
      label = `${head} + ${instruments.length - MAX_SHOWN} ещё`;
    }
    cells[BATCH_ROW_COL.name].textContent = label;
    cells[BATCH_ROW_COL.name].title =
      `Пакет: ${batchId}\nИнструменты: ${instruments.map(fmtContract).join(", ")}`;
  }

  // 4b. Patch "Период" (index 6) — derived covering period.
  if (fromUtc || toUtc) {
    const periodText =
      `${_fmtDatePT(fromUtc)} → ${_fmtDatePT(toUtc)}`;
    cells[BATCH_ROW_COL.period].textContent = periodText;
    cells[BATCH_ROW_COL.period].title = `${fromUtc || ""} → ${toUtc || ""}`;
  }

  // 4c. Patch metrics and rating when /api/batches lacked aggregate fields.
  if (summary.trade_count != null) {
    cells[BATCH_ROW_COL.trades].textContent = summary.trade_count.toLocaleString();
    if (summary.winning_pct != null) {
      cells[BATCH_ROW_COL.winPct].textContent = summary.winning_pct.toFixed(1) + "%";
      cells[BATCH_ROW_COL.winPct].style.color = summary.winning_pct >= 50 ? "#4ade80" : "#f87171";
    }
    if (summary.net_profit != null) {
      cells[BATCH_ROW_COL.net].textContent = fmtMoneySign(summary.net_profit);
      cells[BATCH_ROW_COL.net].style.color = summary.net_profit > 0 ? "#4ade80"
                                : summary.net_profit < 0 ? "#f87171" : "#9ca3af";
    }
    const badgeTd = renderConfidenceBadge({
      kind: "batch",
      status: "done",
      trades: summary.trade_count,
      winning_pct: summary.winning_pct,
      net_profit: summary.net_profit,
      gross_profit: summary.gross_profit,
      gross_loss: summary.gross_loss,
      profit_factor: summary.profit_factor,
      max_drawdown: summary.max_drawdown,
      period: (fromUtc || toUtc) ? { from_utc: fromUtc, to_utc: toUtc } : null,
    });
    cells[BATCH_ROW_COL.confidence].replaceChildren(...Array.from(badgeTd.childNodes));
  }
}

async function hydrateVisibleBatchReportRows(items) {
  const candidates = items.filter(it => {
    if (it.kind !== "batch" || !it.id) return false;
    const cached = _batchNormalizedCache[it.id];
    if (_batchHydrateInFlight.has(it.id)) return false;
    return !cached || !cached.instruments || !cached.instruments.length
      || !it.period || it.profit_factor == null || it.gross_profit == null || it.gross_loss == null;
  }).slice(0, 12);
  for (const it of candidates) {
    _batchHydrateInFlight.add(it.id);
    api.get(`/api/batches/${encodeURIComponent(it.id)}/results`)
      .then(data => normalizeBatchReportRow(it.id, (data && data.rows) || []))
      .catch(e => console.warn("hydrate batch row:", it.id, e))
      .finally(() => _batchHydrateInFlight.delete(it.id));
  }
}

function _deriveBatchSummaryFromRows(rows) {
  const seenInst = new Set();
  const instruments = [];
  let fromUtc = null, toUtc = null;
  let totalTrades = 0, totalWinners = 0;
  let totalNet = 0, totalGrossProfit = 0, totalGrossLoss = 0;
  let worstDd = 0;
  let hasTrades = false, hasNet = false, hasGross = false, hasDd = false;

  for (const r of rows || []) {
    const inst = r.instrument;
    if (inst && !seenInst.has(inst)) { seenInst.add(inst); instruments.push(inst); }
    const p = r.period;
    if (p) {
      if (p.from_utc && (!fromUtc || p.from_utc < fromUtc)) fromUtc = p.from_utc;
      if (p.to_utc   && (!toUtc   || p.to_utc   > toUtc  )) toUtc   = p.to_utc;
    }
    if (r.status && r.status !== "done") continue;
    const m = r.metrics || {};
    const tc = _metricNumber({ v: m.trade_count }, "v");
    if (tc == null) continue;
    hasTrades = true;
    totalTrades += tc;
    const wp = _metricNumber({ v: m.winning_pct }, "v");
    if (wp != null) totalWinners += Math.round(wp * tc / 100);
    const np = _metricNumber({ v: m.net_profit }, "v");
    if (np != null) { totalNet += np; hasNet = true; }
    const gp = _metricNumber({ v: m.gross_profit }, "v");
    const gl = _metricNumber({ v: m.gross_loss }, "v");
    if (gp != null && gl != null) { totalGrossProfit += gp; totalGrossLoss += gl; hasGross = true; }
    const dd = _metricNumber({ v: m.max_drawdown }, "v");
    if (dd != null) { if (dd < worstDd) worstDd = dd; hasDd = true; }
  }

  let pf = null;
  if (hasGross) {
    if (totalGrossLoss < 0) pf = totalGrossProfit / Math.abs(totalGrossLoss);
    else if (totalGrossLoss === 0 && totalGrossProfit > 0) pf = Infinity;
  }
  const winningPct = (hasTrades && totalTrades > 0) ? (totalWinners / totalTrades * 100) : null;
  return {
    instruments,
    fromUtc,
    toUtc,
    trade_count: hasTrades ? totalTrades : null,
    winning_pct: winningPct,
    net_profit: hasNet ? totalNet : null,
    gross_profit: hasGross ? totalGrossProfit : null,
    gross_loss: hasGross ? totalGrossLoss : null,
    profit_factor: pf,
    max_drawdown: hasDd ? worstDd : null,
  };
}

// Build a period_check {before_from, after_to, ok} from a job by parsing
// its verification_warnings (mirrors backend logic, used in single-job mode).
function computePeriodCheck(job) {
  const result = job.result || job.result_partial || {};
  const warns = result.verification_warnings || [];
  for (const w of warns) {
    const m = /before_from=(\d+)\s+after_to=(\d+)/.exec(w);
    if (m) {
      const a = parseInt(m[1], 10), b = parseInt(m[2], 10);
      return { before_from: a, after_to: b, ok: (a === 0 && b === 0) };
    }
  }
  return null;
}

// Render the top instruments table (one row per job, single-job runs get
// 1 row). Highlights the active row and applies row-failed/row-period-bad.
function renderResultRowsTable(rows, activeJobId) {
  const tbl = document.getElementById("result-rows-table");
  if (!tbl) return;
  let tbody = tbl.querySelector("tbody");
  if (!tbody) { tbody = document.createElement("tbody"); tbl.appendChild(tbody); }
  tbody.replaceChildren();

  // Batch-details rows mirror the main reports table and allow favoriting the
  // concrete child run directly from the lower table.
  //   ★, №, Создан, Имя, Стратегия, Тип, Статус, Период, Сделок, Win%, Итог, Доверие
  //
  // created_at_utc and period now come from each child's job.json (via the
  // updated read_batch_results backend). Batch-level values are fallbacks.
  const batchCreated = (_activeBatch && _activeBatch.created_at_utc) || "";
  const batchPeriod  = (_activeBatch && _activeBatch.period) || null;
  const parentReportNo = _activeResultReportNo;

  rows.forEach((r, idx) => {
    const tr = el("tr");
    if (r.job_id === activeJobId) tr.classList.add("selected");
    if (r.status === "failed") tr.classList.add("row-failed");
    if (r.period_check && r.period_check.ok === false) tr.classList.add("row-period-bad");

    const paramStr = r._params && Object.keys(r._params).length
      ? Object.entries(r._params).map(([k,v]) => `${k}=${v}`).join(", ")
      : "";
    if (paramStr) tr.title = `Параметры: ${paramStr}`;

    const m = r.metrics || {};
    const favState = reportFavoriteState("job", r.job_id, !!r.favorite);
    const favorite = favState.favorite;
    const favoriteBusy = favState.favoriteBusy;
    if (favorite) tr.classList.add("favorite");

    const tdStar = el("td", { cls: "col-star" });
    const btnStar = el("button");
    btnStar.type = "button";
    btnStar.disabled = favoriteBusy;
    btnStar.className = "report-star" + (favorite ? " active" : "") + (favoriteBusy ? " pending" : "");
    btnStar.textContent = favorite ? "★" : "☆";
    btnStar.title = favoriteBusy
      ? "Сохраняем изменение избранного..."
      : favorite
        ? "В избранном. Нажмите, чтобы снять звезду."
        : "Добавить конкретный запуск в избранные";
    btnStar.setAttribute("aria-label", btnStar.title);
    btnStar.addEventListener("click", (ev) => {
      ev.stopPropagation();
      if (favoriteBusy) return;
      toggleReportFavorite("job", r.job_id);
    });
    tdStar.appendChild(btnStar);
    tr.appendChild(tdStar);

    // 0) № — child row is anchored to the selected top report number.
    const childIndex = (typeof r._detail_index === "number" && Number.isFinite(r._detail_index))
      ? r._detail_index
      : ((typeof r.batch_index === "number" && Number.isFinite(r.batch_index)) ? (r.batch_index + 1) : (idx + 1));
    const detailReportNo = parentReportNo != null
      ? `${parentReportNo}.${childIndex}`
      : String(childIndex);
    tr.appendChild(td(detailReportNo, { cls: "col-num-compact" }));

    // 1) Создан — per-child, fallback to batch
    const childCreated = r.created_at_utc || batchCreated;
    tr.appendChild(td(_fmtCreated(childCreated), { title: childCreated || "" }));

    // 2) Имя — instrument
    tr.appendChild(td(fmtContract(r.instrument) || "—", { cls: "col-rep-name" }));

    // 3) Стратегия — per-child class_name from job.json, fallback to batch-level
    tr.appendChild(td(r.class_name || r._strategy_class || "—"));

    // 4) Тип — child of a batch is always a single job
    const tdKind = el("td");
    tdKind.appendChild(el("span", { cls: "badge-kind job", text: "запуск" }));
    tr.appendChild(tdKind);

    // 5) Статус
    const tdStatus = el("td");
    tdStatus.appendChild(el("span", {
      cls: "status-badge " + (STATUS_CLASSES[r.status] || "unknown"),
      text: statusLabel(r.status) }));
    tr.appendChild(tdStatus);

    // 6) Период — per-child from job.json, fallback to batch period
    const rowPeriod = r.period || batchPeriod;
    const periodText = rowPeriod
      ? `${_fmtDatePT(rowPeriod.from_utc)} → ${_fmtDatePT(rowPeriod.to_utc)}`
      : "—";
    tr.appendChild(td(periodText, {
      title: rowPeriod ? `${rowPeriod.from_utc} → ${rowPeriod.to_utc}` : "" }));

    // 7) Сделок
    tr.appendChild(td(m.trade_count != null ? m.trade_count.toLocaleString() : "—",
      { cls: "col-num-compact" }));

    // 8) Win %
    const tdWin = el("td", { cls: "col-num-compact" });
    if (typeof m.winning_pct === "number") {
      tdWin.textContent = m.winning_pct.toFixed(1) + "%";
      tdWin.style.color = m.winning_pct >= 50 ? "#4ade80" : "#f87171";
    } else {
      tdWin.textContent = "—";
      tdWin.style.color = "#4b5563";
    }
    tr.appendChild(tdWin);

    // 9) Итог (net profit)
    const tdNet = el("td", { cls: "col-num-compact" });
    if (m.net_profit != null && !Number.isNaN(m.net_profit)) {
      tdNet.textContent = fmtMoneySign(m.net_profit);
      tdNet.style.color = m.net_profit > 0 ? "#4ade80"
                       : m.net_profit < 0 ? "#f87171" : "#9ca3af";
    } else {
      tdNet.textContent = "—";
      tdNet.style.color = "#4b5563";
    }
    tr.appendChild(tdNet);

    // 10) Доверие — reuse the badge renderer with a row-shaped item.
    tr.appendChild(renderConfidenceBadge({
      kind: "job",
      status: r.status,
      trades: m.trade_count != null ? m.trade_count : null,
      winning_pct: m.winning_pct != null ? m.winning_pct : null,
      net_profit: m.net_profit != null ? m.net_profit : null,
      profit_factor: m.profit_factor != null ? m.profit_factor : null,
      gross_profit: m.gross_profit != null ? m.gross_profit : null,
      gross_loss: m.gross_loss != null ? m.gross_loss : null,
      max_drawdown: m.max_drawdown != null ? m.max_drawdown : null,
      period: rowPeriod,
    }));

    tr.addEventListener("click", () => {
      // Only re-load if a different job was clicked.
      if (r.job_id === _selectedJob) return;
      // Re-paint selection now (snappier than waiting for setActiveJob).
      tbody.querySelectorAll("tr").forEach(x => x.classList.remove("selected"));
      tr.classList.add("selected");
      document.getElementById("result-job-id").textContent = r.job_id;
      setActiveJob(r.job_id, null);
    });
    tbody.appendChild(tr);
  });
}

async function setActiveJob(jobId, jobOpt) {
  _selectedJob = jobId;
  _tradesOffset = 0;
  _allTrades = [];
  _filteredTrades = [];
  _selectedTradeNo = null;
  _bars = null;
  _barsState = "idle";
  _barsLoadingFor = null;
  _drawObjects = [];
  _drawObjectsState = { exported: false, reason: "idle", diagnostics: [] };
  _drawObjectsLoadingFor = null;
  _chartViewStart = 0;
  _chartViewEnd   = null;
  switchResultTab("summary");
  document.getElementById("error-box").hidden = true;
  // Active-job pill in result tabs.
  const pill = document.getElementById("active-job-pill");
  if (pill) pill.textContent = `Активный: ${jobId}`;

  let job = jobOpt;
  if (!job) {
    try { job = await api.get(`/api/jobs/${encodeURIComponent(jobId)}`); }
    catch (e) {
      document.getElementById("error-box").hidden = false;
      document.getElementById("error-box").textContent = `Не удалось загрузить job: ${e.message}`;
      return;
    }
  }
  _resultJob = job;

  // ---- Итоги: параметры запуска -------------------------------------
  // Universal normalisation: try multiple shapes so any strategy /
  // instrument /  job source works without hard-coding class names.
  const rawJob = job.job || {};
  const result = job.result || job.result_partial || {};
  const ctx    = result.context || {};

  const strat  = ctx.strategy   || rawJob.strategy   || job.strategy   || {};
  const rawInstr = ctx.instrument || rawJob.instrument || job.instrument;
  const tf     = ctx.timeframe  || rawJob.timeframe  || job.timeframe  || {};
  const period = ctx.period     || rawJob.period     || job.period     || {};
  const exec   = ctx.execution  || rawJob.execution  || job.execution  || {};
  const params =
    (strat && (strat.final_parameters || strat.parameters)) ||
    (rawJob.strategy && rawJob.strategy.parameters) ||
    (job.strategy && job.strategy.parameters) ||
    {};

  const strategyName =
    strat.class_name || rawJob.class_name || job.class_name || "—";
  let instrumentName = "—";
  if (typeof rawInstr === "string") instrumentName = rawInstr;
  else if (rawInstr && typeof rawInstr === "object") {
    instrumentName = rawInstr.full_name || rawInstr.name ||
                     rawInstr.symbol    || rawInstr.id   || "—";
  }

  setText("sm-strategy",   strategyName);
  setText("sm-instrument", fmtContract(instrumentName));
  const tfType = tf.bars_period_type || tf.type || "—";
  const tfVal  = tf.value ?? tf.bars_period_value ?? "";
  setText("sm-timeframe", `${tfType} ${tfVal}`.trim());
  setText("sm-period",
    `${period.from_utc || "—"} → ${period.to_utc || "—"}`);
  setText("sm-thours",
    exec.session_template || "—");
  setText("sm-commission",
    exec.commission_template || (exec.commission != null ? `commission=${exec.commission}` : "—"));
  renderStrategyParams(params);
  renderRiskProfileSummary(riskProfileFromJob(job));

  // ---- Итоги: performance matrix (All / Long / Short) ---------------
  const metrics = (job.result && job.result.metrics) || {};

  // ---- Итоги: контроль ----------------------------------------------
  fillResultContext(job);
  document.getElementById("raw-link").href =
    `/api/jobs/${encodeURIComponent(jobId)}`;

  // failure?
  if (job.status === "failed") {
    const eb = document.getElementById("error-box");
    eb.hidden = false;
    const e  = job.error || {};
    const rp = job.result_partial || {};
    const tail = (rp.verification_warnings || []).slice(-15).join("\n");
    eb.textContent =
      `error_type: ${e.error_type}\nmessage:\n${e.message || ""}\n\nverification_warnings (tail):\n${tail}`;
    // Empty perf matrix on failure.
    renderPerfMatrix(metrics, [], exec);
    return;
  }

  // ---- Анализ: full trades + equity ----------------------------------
  // Show the bridge summary immediately; Long/Short slices update after
  // trades.json finishes loading in the background.
  renderPerfMatrix(metrics, [], exec);
  loadAllTrades().then((loaded) => {
    if (loaded && _selectedJob === jobId) renderPerfMatrix(metrics, _allTrades, exec);
  });
  // ---- График: bars + strategy draw objects ---------------------------
  // Large bars.json artifacts are loaded only when the chart tab is opened.
  const chartStatus = document.getElementById("chart-status");
  if (chartStatus) {
    chartStatus.hidden = false;
    chartStatus.classList.remove("error");
    chartStatus.textContent = "График опциональный: откройте вкладку, чтобы загрузить bars.json, если он есть у отчета.";
  }
  const chartInfo = document.getElementById("chart-info");
  if (chartInfo) chartInfo.textContent = "";
  const drawingsBanner = document.getElementById("chart-drawings-status");
  if (drawingsBanner) {
    drawingsBanner.hidden = true;
    drawingsBanner.textContent = "";
  }
}

function setText(id, v) {
  const e = document.getElementById(id);
  if (e) e.textContent = (v === undefined || v === null || v === "") ? "—" : String(v);
}

function riskProfileFromJob(job) {
  const rawJob = (job && job.job) || {};
  const result = (job && (job.result || job.result_partial)) || {};
  const ctx = result.context || {};
  return ctx.risk_profile || rawJob.risk_profile || job?.risk_profile || null;
}

function renderRiskProfileSummary(risk) {
  if (!risk) {
    setText("sm-risk-capital", "—");
    setText("sm-risk-mode", "NinjaTrader / unlimited");
    setText("sm-risk-margin", "—");
    setText("sm-risk-contracts", "—");
    setText("sm-risk-status", "Профиль не задан");
    return;
  }
  const mode = risk.mode === "informational"
    ? "Информационный"
    : (risk.mode || "—");
  const sessionMode = risk.intraday_only ? "только внутридень" : "overnight разрешен";
  setText("sm-risk-capital", fmtMoney(risk.starting_capital || 0));
  setText("sm-risk-mode", `${mode}, ${sessionMode}`);

  // Margin/contracts breakdown supports both the new schema
  // (instrument_margins map keyed by contract symbol) and the legacy
  // schema (margin_per_contract.{intraday,overnight,active}). Old jobs
  // remain readable for back-compat.
  const im = risk.instrument_margins;
  if (im && typeof im === "object" && Object.keys(im).length) {
    const entries = Object.entries(im);
    let allowed = 0, blocked = 0, unknown = 0, marginSample = null, maxSample = null;
    for (const [, info] of entries) {
      if (info.status === "allowed") {
        allowed += 1;
        if (marginSample == null && info.margin_per_contract != null) {
          marginSample = info.margin_per_contract;
          maxSample = info.max_contracts_by_capital;
        }
      } else if (info.status === "blocked") {
        blocked += 1;
      } else {
        unknown += 1;
      }
    }
    const broker = (risk.margin_source && risk.margin_source.broker) || "catalog";
    setText("sm-risk-margin",
      marginSample != null
        ? `${fmtMoney(marginSample)} / контракт (${broker})`
        : `по каталогу (${broker})`);
    setText("sm-risk-contracts",
      `${entries.length} инстр.: ${allowed}/${blocked}/${unknown} (allowed/blocked/unknown)`);
  } else {
    const m = risk.margin_per_contract || {};
    const active = m.active ?? (risk.intraday_only ? m.intraday : m.overnight);
    setText("sm-risk-margin",
      active != null ? `${fmtMoney(active)} / контракт (${risk.margin_model || "manual"})` : "—");
    setText("sm-risk-contracts",
      risk.max_contracts_by_capital == null ? "—" : `${risk.max_contracts_by_capital}`);
  }
  setText("sm-risk-status", risk.status_text || risk.status || "—");
}

// Render strategy parameters into #sm-params. Works for any strategy:
// 0 params → "Параметры не указаны"; 1–8 → all inline; >8 → first 8 + "ещё N"
// with a [Показать все] toggle that expands the full list. Full set always
// goes into the title attribute as a fallback.
function renderStrategyParams(params) {
  const cell = document.getElementById("sm-params");
  if (!cell) return;
  cell.replaceChildren();
  cell.removeAttribute("title");

  const entries = Object.entries(params || {});
  if (entries.length === 0) {
    cell.textContent = "Параметры не указаны";
    cell.style.color = "#6b7280";
    return;
  }
  cell.style.color = "";

  const fmt = ([k, v]) => {
    let s = (v === null || v === undefined) ? "" : String(v);
    if (s.length > 40) s = s.slice(0, 37) + "…";
    return `${k}=${s}`;
  };
  const fullText = entries.map(fmt).join(", ");
  cell.title = fullText;

  const LIMIT = 8;
  if (entries.length <= LIMIT) {
    cell.textContent = fullText;
    return;
  }
  const shortText = entries.slice(0, LIMIT).map(fmt).join(", ");
  const remaining = entries.length - LIMIT;

  const span = document.createElement("span");
  span.textContent = shortText + ", ";
  cell.appendChild(span);

  const toggle = document.createElement("a");
  toggle.href = "#";
  toggle.textContent = `ещё ${remaining}`;
  toggle.style.color = "#60a5fa";
  let expanded = false;
  toggle.addEventListener("click", (e) => {
    e.preventDefault();
    expanded = !expanded;
    if (expanded) {
      span.textContent = fullText;
      toggle.textContent = " свернуть";
    } else {
      span.textContent = shortText + ", ";
      toggle.textContent = `ещё ${remaining}`;
    }
  });
  cell.appendChild(toggle);
}

// Build the All / Long / Short performance matrix table (perf-matrix). Uses
// the bridge metrics for the All column and recomputes Long/Short from the
// loaded trades list. Commission / Sharpe / MAE / MFE / ETD are surfaced as
// "n/a" — see Round 5 §8: backend does not yet expose those.
function renderPerfMatrix(metricsAll, trades, exec) {
  const tbl = document.getElementById("perf-matrix");
  if (!tbl) return;
  let tbody = tbl.querySelector("tbody");
  if (!tbody) { tbody = document.createElement("tbody"); tbl.appendChild(tbody); }
  tbody.replaceChildren();

  const subset = (sideOrNull) => {
    if (sideOrNull == null) return trades.slice();
    return trades.filter(t => t.direction === sideOrNull);
  };
  const stats = (rows) => {
    const n = rows.length;
    let gp = 0, gl = 0, wins = 0;
    let best = -Infinity, worst = Infinity;
    let cum = 0, peak = 0, maxDD = 0;
    for (const t of rows) {
      const p = t.pnl_currency || 0;
      if (p > 0) { gp += p; wins++; }
      else       { gl += p; }
      if (p > best)  best  = p;
      if (p < worst) worst = p;
      cum += p;
      if (cum > peak) peak = cum;
      const dd = cum - peak;       // <= 0
      if (dd < maxDD) maxDD = dd;
    }
    const net = gp + gl;
    const pf  = (gl !== 0) ? (gp / Math.abs(gl)) : (gp > 0 ? Infinity : null);
    const winp = n ? (wins / n) * 100 : null;
    const avg  = n ? (net / n) : null;
    if (n === 0) { best = null; worst = null; }
    return { n, gp, gl, net, pf, winp, avg, best, worst, wins,
             losers: n - wins, maxDD: n ? maxDD : null };
  };

  const all   = stats(subset(null));
  const long  = stats(subset("long"));
  const short = stats(subset("short"));

  // For the "All" column, prefer bridge metrics where available — this
  // avoids drift with the official summary while keeping Long/Short locally
  // computed from trades.json.
  const m = metricsAll || {};
  const allOverride = {
    n:    (m.trade_count   != null) ? m.trade_count   : all.n,
    gp:   (m.gross_profit  != null) ? m.gross_profit  : all.gp,
    gl:   (m.gross_loss    != null) ? m.gross_loss    : all.gl,
    net:  (m.net_profit    != null) ? m.net_profit    : all.net,
    pf:   (m.profit_factor != null) ? m.profit_factor : all.pf,
    winp: (m.winning_pct   != null) ? m.winning_pct   : all.winp,
    avg:  all.avg, best: all.best, worst: all.worst,
    wins: (m.winning_pct != null && m.trade_count != null)
      ? Math.round(m.winning_pct * m.trade_count / 100)
      : all.wins,
    losers: null,
  };
  if (allOverride.wins != null && allOverride.n != null) {
    allOverride.losers = allOverride.n - allOverride.wins;
  } else { allOverride.losers = all.losers; }

  const moneyCell = (v) => {
    if (v == null || Number.isNaN(v)) return td("—", { cls: "num" });
    return td(fmtMoneySign(v),
      { cls: "num " + (v > 0 ? "pos" : (v < 0 ? "neg" : "")) });
  };
  const numCell = (v, digits) => {
    if (v == null || Number.isNaN(v) || !isFinite(v)) return td("—", { cls: "num" });
    return td(v.toLocaleString(undefined,
      { minimumFractionDigits: digits, maximumFractionDigits: digits }),
      { cls: "num" });
  };
  const intCell = (v) => {
    if (v == null) return td("—", { cls: "num" });
    return td(v.toLocaleString(), { cls: "num" });
  };
  const naCell = () => td("n/a", { cls: "num", title: "not exposed by bridge yet" });

  function row(label, all, lng, sht, fmt) {
    const tr = el("tr");
    tr.appendChild(td(label, { cls: "k" }));
    tr.appendChild(fmt(all));
    tr.appendChild(fmt(lng));
    tr.appendChild(fmt(sht));
    tbody.appendChild(tr);
  }
  function rowDivider() {
    const tr = el("tr", { cls: "divider" });
    for (let i = 0; i < 4; i++) tr.appendChild(el("td"));
    tbody.appendChild(tr);
  }
  function rowNA(label) {
    const tr = el("tr");
    tr.appendChild(td(label, { cls: "k" }));
    tr.appendChild(naCell()); tr.appendChild(naCell()); tr.appendChild(naCell());
    tbody.appendChild(tr);
  }

  row("Net Profit",     allOverride.net, long.net, short.net, moneyCell);
  row("Gross Profit",   allOverride.gp,  long.gp,  short.gp,  moneyCell);
  row("Gross Loss",     allOverride.gl,  long.gl,  short.gl,  moneyCell);

  // Commission row. The execution.commission field is the *requested* numeric
  // commission (always 0 in this build) — NEVER use it as the actual paid
  // commission. We only trust:
  //   * metrics.commission (bridge: aggregate from TradesPerformance.Commission)
  //   * per-trade trade.commission (bridge: Entry+Exit.Commission), summed
  //     to compute Long/Short slices.
  // Convention: bridge reports commission as a positive cost; we render with
  // a leading "-" sign in the All/Long/Short cells for clarity.
  const tmpl = (exec || {}).commission_template;
  const isNoneTmpl = !tmpl || tmpl === "None";

  const sumCommission = (rows) => {
    let s = 0, any = false;
    for (const t of rows) {
      if (t && t.commission != null && !Number.isNaN(t.commission)) {
        s += Math.abs(t.commission); any = true;
      }
    }
    return any ? s : null;
  };
  const commLong  = sumCommission(subset("long"));
  const commShort = sumCommission(subset("short"));
  const commAll   = (m.commission != null && !Number.isNaN(m.commission))
                  ? Math.abs(m.commission)
                  : sumCommission(trades);

  if (isNoneTmpl) {
    // No commission template requested → real cost is exactly 0.
    row("Комиссия", 0, 0, 0, moneyCell);
  } else if (commAll != null) {
    // Bridge exported the aggregate (and possibly per-side from trades).
    row("Комиссия",
        -commAll,
        commLong  != null ? -commLong  : null,
        commShort != null ? -commShort : null,
        moneyCell);
  } else {
    // Template applied but no exported amount — make this explicit instead
    // of pretending commission is $0.
    const tip = "Bridge применил шаблон комиссии «" + tmpl +
                "», но отдельная сумма комиссии не экспортирована. " +
                "Net Profit уже включает комиссию.";
    const noteCell = () => td("учтена в PnL", { cls: "num muted", title: tip });
    const tr = el("tr");
    tr.appendChild(td("Комиссия", { cls: "k", title: tip }));
    tr.appendChild(noteCell()); tr.appendChild(noteCell()); tr.appendChild(noteCell());
    tbody.appendChild(tr);
  }

  row("Profit Factor",  allOverride.pf,  long.pf,  short.pf,
    (v) => numCell(v, 3));
  // Max drawdown: All from bridge (если есть), Long/Short — из trades.
  row("Макс. просадка",
    (m.max_drawdown != null) ? m.max_drawdown : all.maxDD,
    long.maxDD, short.maxDD, moneyCell);

  rowDivider();

  row("Всего сделок",   allOverride.n,    long.n,      short.n,      intCell);
  row("Прибыльные",        allOverride.wins, long.wins,   short.wins,   intCell);
  row("Убыточные",         allOverride.losers, long.losers, short.losers, intCell);
  row("Win %",          allOverride.winp, long.winp,   short.winp,
    (v) => v == null ? td("—", { cls: "num" })
                     : td(v.toFixed(2) + "%", { cls: "num" }));

  rowDivider();

  row("Средняя сделка",  allOverride.avg,   long.avg,   short.avg,   moneyCell);
  row("Лучшая сделка",   allOverride.best,  long.best,  short.best,  moneyCell);
  row("Худшая сделка",   allOverride.worst, long.worst, short.worst, moneyCell);
}

// Populate the Result tab "context" block (requested period, first/last
// trade times, period check). All values are derived from data we already
// have on the job: result.context.period (or job.period from job.json) and
// the bridge's `period_invariant: ...` lines in verification_warnings.
function fillResultContext(job) {
  const result = job.result || job.result_partial || {};
  const period = (result.context && result.context.period) || job.period || {};
  const fromS = period.from_utc || "\u2014";
  const toS   = period.to_utc   || "\u2014";
  document.getElementById("rc-period").textContent = `${fromS} \u2192 ${toS}`;

  // Parse the bridge-emitted period_invariant lines.
  const warns = result.verification_warnings || [];
  let firstEntry = null, lastEntry = null;
  let before = null, after = null;
  for (const w of warns) {
    let m;
    if ((m = /trades_first_entry=(\S+)\s+trades_last_entry=(\S+)/.exec(w))) {
      firstEntry = m[1]; lastEntry = m[2];
    }
    if ((m = /before_from=(\d+)\s+after_to=(\d+)/.exec(w))) {
      before = parseInt(m[1], 10); after = parseInt(m[2], 10);
    }
  }
  document.getElementById("rc-first").textContent = firstEntry || "\u2014";
  document.getElementById("rc-last").textContent  = lastEntry  || "\u2014";

  const pill = document.getElementById("rc-check");
  pill.classList.remove("ok", "fail", "unknown", "warn");
  if (job.status === "failed" && (job.error || {}).error_type === "period_mismatch") {
    pill.textContent = `FAILED (before=${before ?? "?"}, after=${after ?? "?"})`;
    pill.classList.add("fail");
  } else if (before === 0 && after === 0) {
    pill.textContent = "OK";
    pill.classList.add("ok");
  } else if (before == null && after == null) {
    pill.textContent = "n/a";
    pill.classList.add("unknown");
  } else {
    pill.textContent = `FAILED (before=${before}, after=${after})`;
    pill.classList.add("fail");
  }

  const manualRow = document.getElementById("rc-manual-row");
  const manual = document.getElementById("rc-manual");
  if (manualRow && manual) {
    manualRow.hidden = false;
    manual.classList.remove("ok", "fail", "unknown", "warn", "muted");
    if (job.validated_against_strategy_analyzer) {
      manual.textContent = "PASSED";
      manual.classList.add("ok");
    } else {
      manual.textContent = "не выполнялась";
      manual.classList.add("unknown");
    }
  }
}

// ---- Analysis tab: full trades list, equity curve, filters ---------------

async function loadAllTrades() {
  if (!_selectedJob) return false;
  const startedFor = _selectedJob;
  // Pull the full trades list. NT runs we ship with cap out at ~2k trades
  // which is small enough to keep client-side; if a future job exceeds the
  // 1000-row backend cap we just truncate the analysis view.
  let acc = [];
  let off = 0;
  const PAGE = 1000;
  while (true) {
    let data;
    try {
      data = await api.get(
        `/api/jobs/${encodeURIComponent(startedFor)}/trades`
        + `?offset=${off}&limit=${PAGE}`
      );
    } catch (e) { break; }
    if (_selectedJob !== startedFor) return false;
    const got = data.trades || [];
    acc = acc.concat(got);
    off += got.length;
    if (got.length < PAGE || off >= (data.total || 0)) break;
  }
  if (_selectedJob !== startedFor) return false;
  _allTrades = acc;
  applyTradeFilters();
  drawEquityCurve();
  return true;
}

function applyTradeFilters() {
  let rows = _allTrades.slice();
  if (_tradeFilters.side === "long")  rows = rows.filter(t => t.direction === "long");
  if (_tradeFilters.side === "short") rows = rows.filter(t => t.direction === "short");
  if (_tradeFilters.pnl  === "winners") rows = rows.filter(t => (t.pnl_currency ?? 0) > 0);
  if (_tradeFilters.pnl  === "losers")  rows = rows.filter(t => (t.pnl_currency ?? 0) < 0);
  _filteredTrades = rows;
  _tradesOffset = 0;
  renderTradesTable();
  renderTradesSummary();
}

function renderTradesSummary() {
  const sum = document.getElementById("trades-summary");
  if (!sum) return;
  const n = _filteredTrades.length;
  if (n === 0) { sum.textContent = "Нет сделок по фильтру"; return; }
  let total = 0, best = -Infinity, worst = Infinity;
  for (const t of _filteredTrades) {
    const p = t.pnl_currency ?? 0;
    total += p;
    if (p > best)  best  = p;
    if (p < worst) worst = p;
  }
  const avg = total / n;
  sum.innerHTML =
    `Сделок: <b>${n}</b> · ` +
    `PnL: <b>${fmtMoneySign(total)}</b> · ` +
    `Средняя: <b>${fmtMoneySign(avg)}</b> · ` +
    `Лучшая: <b>${fmtMoneySign(best)}</b> · ` +
    `Худшая: <b>${fmtMoneySign(worst)}</b>`;
}

function renderTradesTable() {
  const tbody = document.querySelector("#trades-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  const start = _tradesOffset;
  const end   = Math.min(_filteredTrades.length, start + TRADES_PAGE);
  const rangeEl = document.getElementById("trades-range");
  if (rangeEl) {
    rangeEl.textContent = _filteredTrades.length
      ? `${start + 1}–${end} из ${_filteredTrades.length}`
      : `0–0 из 0`;
  }

  for (let i = start; i < end; i++) {
    const t = _filteredTrades[i];
    const tr = el("tr");
    if (t.trade_no === _selectedTradeNo) tr.classList.add("selected");
    tr.dataset.tradeNo = String(t.trade_no);
    tr.appendChild(td(t.trade_no, { cls: "num" }));
    tr.appendChild(td(t.direction));
    tr.appendChild(td(t.entry_time_utc));
    tr.appendChild(td(fmtPx(t.entry_price), { cls: "num" }));
    tr.appendChild(td(t.exit_time_utc));
    tr.appendChild(td(fmtPx(t.exit_price), { cls: "num" }));
    tr.appendChild(td(t.quantity, { cls: "num" }));
    const pnl = (t.pnl_currency ?? 0);
    tr.appendChild(td(fmtMoney(t.pnl_currency),
      { cls: "num " + (pnl >= 0 ? "pos" : "neg") }));
    tr.appendChild(td(t.pnl_ticks, { cls: "num" }));
    tr.addEventListener("click", () => selectTrade(t.trade_no));
    tbody.appendChild(tr);
  }
  document.getElementById("trades-prev").disabled = start <= 0;
  document.getElementById("trades-next").disabled = end >= _filteredTrades.length;
}

function selectTrade(tradeNo) {
  _selectedTradeNo = tradeNo;
  // Highlight in table.
  document.querySelectorAll("#trades-table tbody tr").forEach(tr => {
    tr.classList.toggle("selected",
      Number(tr.dataset.tradeNo) === tradeNo);
  });
  // Cross-link to chart: re-center on the trade and switch tab so the user
  // can see the price action behind the click.
  centerChartOnTrade(tradeNo);
}

function fmtPx(v) { return (v == null) ? "" : v.toLocaleString(undefined, { maximumFractionDigits: 4 }); }
function fmtMoney(v) { return (v == null) ? "" : v.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }); }
function fmtMoneySign(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v >= 0 ? "+" : "−";
  return s + "$" + Math.abs(v).toLocaleString(undefined,
    { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

document.getElementById("trades-prev").addEventListener("click", () => {
  _tradesOffset = Math.max(0, _tradesOffset - TRADES_PAGE); renderTradesTable();
});
document.getElementById("trades-next").addEventListener("click", () => {
  _tradesOffset = Math.min(_filteredTrades.length - TRADES_PAGE, _tradesOffset + TRADES_PAGE);
  if (_tradesOffset < 0) _tradesOffset = 0;
  renderTradesTable();
});
// Trade filter segmented buttons.
document.querySelectorAll("#trades-side-filter button").forEach(b => {
  b.addEventListener("click", () => {
    _tradeFilters.side = b.dataset.side;
    document.querySelectorAll("#trades-side-filter button").forEach(x =>
      x.classList.toggle("active", x === b));
    applyTradeFilters();
  });
});
document.querySelectorAll("#trades-pnl-filter button").forEach(b => {
  b.addEventListener("click", () => {
    _tradeFilters.pnl = b.dataset.pnl;
    document.querySelectorAll("#trades-pnl-filter button").forEach(x =>
      x.classList.toggle("active", x === b));
    applyTradeFilters();
  });
});

// ---- Result inner-tab switching ------------------------------------------
function switchResultTab(name) {
  document.querySelectorAll(".result-tabs .rtab").forEach(b => {
    const on = b.dataset.rtab === name;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".rtab-pane").forEach(p =>
    p.classList.toggle("active", p.id === `rtab-${name}`));
  // Defer the redraw one frame so the now-visible canvas has its real
  // clientWidth/clientHeight populated by layout.
  if (name === "analysis") requestAnimationFrame(drawEquityCurve);
  if (name === "chart") {
    ensureChartArtifactsLoaded();
    requestAnimationFrame(drawPriceChart);
  }
}
document.querySelectorAll(".result-tabs .rtab").forEach(b => {
  b.addEventListener("click", () => switchResultTab(b.dataset.rtab));
});

// Redraw chart/equity when their containers resize (window resize, sidebar
// width changes, etc.) so the canvas always fills the available area.
(function attachChartResize() {
  if (typeof ResizeObserver === "undefined") return;
  let pendingChart = false, pendingEq = false;
  const ro = new ResizeObserver(() => {
    if (!pendingChart) {
      pendingChart = true;
      requestAnimationFrame(() => { pendingChart = false; drawPriceChart(); });
    }
    if (!pendingEq) {
      pendingEq = true;
      requestAnimationFrame(() => { pendingEq = false; drawEquityCurve(); });
    }
  });
  const cw = document.querySelector(".chart-wrap");
  const eq = document.querySelector(".analysis-equity");
  if (cw) ro.observe(cw);
  if (eq) ro.observe(eq);
})();

// ---- Equity curve (cumulative PnL across all trades; ignores filters
// because the cumulative strategy curve is what the operator actually
// wants to see, regardless of which subset the table shows) -----------
function drawEquityCurve() {
  const cv = document.getElementById("equity-canvas");
  if (!cv) return;
  const ctx = cv.getContext("2d");
  const W = cv.width  = cv.clientWidth || 900;
  const H = cv.height = cv.clientHeight || 160;
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = "#0f1115";
  ctx.fillRect(0, 0, W, H);

  if (!_allTrades.length) {
    ctx.fillStyle = "#666"; ctx.font = "12px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Сделок нет", W/2, H/2);
    const note = document.getElementById("eq-note");
    if (note) note.textContent = "";
    return;
  }
  // Build cumulative curve. With a risk profile, the curve is shifted by
  // starting_capital but still compares gains/losses against the start line.
  const risk = riskProfileFromJob(_resultJob);
  const base = risk && Number.isFinite(Number(risk.starting_capital))
    ? Number(risk.starting_capital)
    : 0;
  const curve = new Array(_allTrades.length);
  let acc = 0, peak = -Infinity;
  let lo = base, hi = base;
  for (let i = 0; i < _allTrades.length; i++) {
    acc += _allTrades[i].pnl_currency || 0;
    curve[i] = base + acc;
    if (curve[i] > peak) peak = curve[i];
    if (curve[i] < lo)   lo = curve[i];
    if (curve[i] > hi)   hi = curve[i];
  }
  if (lo === hi) hi = lo + 1;
  const padL = 50, padR = 10, padT = 10, padB = 22;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  function x(i) { return padL + (i / Math.max(1, curve.length - 1)) * innerW; }
  function y(v) { return padT + innerH - ((v - lo) / (hi - lo)) * innerH; }

  const yBase = y(base);

  function equityPathToBaseline() {
    ctx.beginPath();
    ctx.moveTo(x(0), y(curve[0]));
    for (let i = 1; i < curve.length; i++) ctx.lineTo(x(i), y(curve[i]));
    ctx.lineTo(x(curve.length - 1), yBase);
    ctx.lineTo(x(0), yBase);
    ctx.closePath();
  }

  function equityLinePath() {
    ctx.beginPath();
    ctx.moveTo(x(0), y(curve[0]));
    for (let i = 1; i < curve.length; i++) ctx.lineTo(x(i), y(curve[i]));
  }

  // Soft NinjaTrader-style grid.
  ctx.strokeStyle = "rgba(255,255,255,0.07)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i++) {
    const gy = padT + (innerH * i / 4);
    ctx.beginPath();
    ctx.moveTo(padL, gy);
    ctx.lineTo(padL + innerW, gy);
    ctx.stroke();
  }

  // Fill area against the start line: profit is green, drawdown/loss is red.
  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, padT, innerW, Math.max(0, yBase - padT));
  ctx.clip();
  equityPathToBaseline();
  ctx.fillStyle = "rgba(45, 170, 75, 0.46)";
  ctx.fill();
  ctx.restore();

  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, yBase, innerW, Math.max(0, padT + innerH - yBase));
  ctx.clip();
  equityPathToBaseline();
  ctx.fillStyle = "rgba(185, 24, 24, 0.50)";
  ctx.fill();
  ctx.restore();

  // Curve outline is clipped by sign, so crossings change color at zero.
  ctx.lineWidth = 1.6;
  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, padT, innerW, Math.max(0, yBase - padT));
  ctx.clip();
  equityLinePath();
  ctx.strokeStyle = "#35d04d";
  ctx.stroke();
  ctx.restore();

  ctx.save();
  ctx.beginPath();
  ctx.rect(padL, yBase, innerW, Math.max(0, padT + innerH - yBase));
  ctx.clip();
  equityLinePath();
  ctx.strokeStyle = "#ff2020";
  ctx.stroke();
  ctx.restore();

  // Starting-capital baseline.
  ctx.strokeStyle = "#2c3142";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padL, yBase);
  ctx.lineTo(padL + innerW, yBase);
  ctx.stroke();
  // Y-axis labels.
  ctx.fillStyle = "#6b7280"; ctx.font = "10px sans-serif";
  ctx.textAlign = "right";
  ctx.fillText("$" + fmtMoneyShort(hi), padL - 4, padT + 8);
  ctx.fillText("$" + fmtMoneyShort(base), padL - 4, yBase + 3);
  ctx.fillText("$" + fmtMoneyShort(lo), padL - 4, padT + innerH);

  // Footer note.
  const finalEquity = base + acc;
  document.getElementById("eq-note").textContent =
    base > 0
      ? `(${curve.length} сделок, старт ${fmtMoney(base)}, итог ${fmtMoney(finalEquity)}, PnL ${fmtMoneySign(acc)})`
      : `(${curve.length} сделок, итого ${fmtMoneySign(acc)})`;
}
function fmtMoneyShort(v) {
  if (Math.abs(v) >= 1000) return (v/1000).toFixed(1) + "k";
  return v.toFixed(0);
}

// ---- Chart tab: candles + trade markers ----------------------------------
// Zoom/pan state: a window into _bars[_chartViewStart .. _chartViewEnd).
// _chartViewEnd === null means "all the way to the end".
let _chartViewStart = 0;
let _chartViewEnd   = null;
let _chartIsDragging = false;
let _chartDragStartX = 0;
let _chartDragStartView = [0, 0];   // snapshot of [start, end] at drag start

function _chartView() {
  if (!_bars || _bars.length === 0) return [0, 0];
  const end = (_chartViewEnd == null) ? _bars.length : _chartViewEnd;
  return [Math.max(0, _chartViewStart), Math.min(_bars.length, end)];
}

async function loadBars() {
  if (!_selectedJob) return;
  if (_barsState === "loading" && _barsLoadingFor === _selectedJob) return;
  if (_barsState === "ok" || _barsState === "missing") return;
  const status = document.getElementById("chart-status");
  const info   = document.getElementById("chart-info");
  status.classList.remove("error");
  status.hidden = false;
  status.textContent = "Загрузка bars.json…";
  // Capture which job we started loading for; if user clicks another row
  // before paging completes, abandon results to avoid mixing instruments.
  const startedFor = _selectedJob;
  _barsLoadingFor = startedFor;
  const PAGE = 50000;
  const HARD_CAP = 500000;   // sanity upper bound (10x ~year of M1)
  try {
    const all = [];
    let total = 0;
    let offset = 0;
    let truncated = false;
    while (true) {
      const data = await api.get(
        `/api/jobs/${encodeURIComponent(startedFor)}/bars`
        + `?offset=${offset}&limit=${PAGE}`
      );
      if (_selectedJob !== startedFor) return;  // user switched rows
      total = data.total || 0;
      const chunk = data.bars || [];
      if (offset === 0 && chunk.length === 0) {
        _bars = [];
        _barsState = "missing";
        _barsLoadingFor = null;
        status.hidden = false;
        status.textContent =
          "График недоступен: bars.json отсутствует для этого job. " +
          "Итоги и анализ работают без него; график появится только у отчетов, где bridge сохранил bars.json.";
        const cv = document.getElementById("price-canvas");
        if (cv) cv.style.display = "none";
        if (info) info.textContent = "";
        return;
      }
      for (const b of chunk) all.push(b);
      offset += chunk.length;
      if (chunk.length < PAGE) break;       // backend returned tail
      if (offset >= total) break;            // reached the end
      if (offset >= HARD_CAP) { truncated = true; break; }
    }
    _bars = all;
    _barsState = "ok";
    _barsLoadingFor = null;
    status.hidden = true;
    status.textContent = "";
    const cv = document.getElementById("price-canvas");
    if (cv) cv.style.display = "block";
    const first = _bars[0]?.t || "—";
    const last  = _bars[_bars.length - 1]?.t || "—";
    const loaded = _bars.length;
    const totalKnown = Math.max(total, loaded);
    const baseLine = `Бары: ${loaded.toLocaleString()} / ${totalKnown.toLocaleString()} · ${first} → ${last}`;
    if (info) {
      if (loaded < totalKnown) {
        info.textContent = baseLine
          + ` · график неполный: загружено ${loaded} из ${totalKnown} баров`;
      } else {
        info.textContent = baseLine;
      }
    }
    drawPriceChart();
  } catch (e) {
    if (_selectedJob !== startedFor) return;
    _barsState = "error";
    _barsLoadingFor = null;
    status.hidden = false;
    status.classList.add("error");
    status.textContent = "Ошибка загрузки bars.json: " + e.message;
  }
}

function ensureChartArtifactsLoaded() {
  if (!_selectedJob) return;
  if (_barsState === "idle" || _barsState === "error") loadBars();
  if (_drawObjectsState.reason === "idle" && _drawObjectsLoadingFor !== _selectedJob) {
    loadDrawObjects();
  }
}

// Cached geometry from the last drawPriceChart() call. Used by mouse
// handlers so they don't have to recompute the projection.
let _chartGeom = null;

function drawPriceChart() {
  const cv = document.getElementById("price-canvas");
  if (!cv) return;
  if (!document.getElementById("rtab-chart").classList.contains("active")) return;
  const status = document.getElementById("chart-status");
  if (_barsState !== "ok" || !_bars || _bars.length === 0) {
    cv.style.display = "none"; status.hidden = false; _chartGeom = null; return;
  }
  cv.style.display = "block"; status.hidden = true;

  const [vs, ve] = _chartView();
  const view = _bars.slice(vs, ve);
  if (view.length === 0) { _chartGeom = null; return; }

  const ctx = cv.getContext("2d");
  const W = cv.width  = cv.clientWidth || 1100;
  const H = cv.height = cv.clientHeight || 420;
  ctx.fillStyle = "#0b0f14"; ctx.fillRect(0, 0, W, H);

  // --- Y range: visible candles + visible trade markers --------------------
  let lo = +Infinity, hi = -Infinity;
  for (const b of view) { if (b.l < lo) lo = b.l; if (b.h > hi) hi = b.h; }
  const t0Vis = Date.parse(view[0].t);
  const t1Vis = Date.parse(view[view.length - 1].t);
  for (const t of _allTrades) {
    const te = Date.parse(t.entry_time_utc);
    const tx = Date.parse(t.exit_time_utc);
    if (te >= t0Vis && te <= t1Vis) {
      if (t.entry_price < lo) lo = t.entry_price;
      if (t.entry_price > hi) hi = t.entry_price;
    }
    if (tx >= t0Vis && tx <= t1Vis) {
      if (t.exit_price < lo) lo = t.exit_price;
      if (t.exit_price > hi) hi = t.exit_price;
    }
  }
  if (lo === hi) hi = lo + 1;
  const pad = (hi - lo) * 0.06; lo -= pad; hi += pad;

  // --- Layout: dedicated right gutter for price, bottom gutter for time ----
  const padL = 8, padR = 64, padT = 10, padB = 24;
  const innerW = W - padL - padR, innerH = H - padT - padB;

  // X axis is INDEX-BASED (NinjaTrader / TradingView style): consecutive
  // bars sit at consecutive slots, so weekend / overnight gaps disappear.
  const slotW = innerW / view.length;
  function xI(i) { return padL + (i + 0.5) * slotW; }
  function yP(p) { return padT + innerH - ((p - lo) / (hi - lo)) * innerH; }
  // Map a UTC timestamp to nearest visible bar index (binary scan; view is
  // monotone by time). Returns -1 when out of range.
  function tToIdx(ts) {
    if (ts < t0Vis - 1 || ts > t1Vis + 1) return -1;
    let l = 0, r = view.length - 1, best = 0, bestD = Infinity;
    while (l <= r) {
      const m = (l + r) >> 1;
      const tm = Date.parse(view[m].t);
      const d = Math.abs(tm - ts);
      if (d < bestD) { bestD = d; best = m; }
      if (tm < ts) l = m + 1; else r = m - 1;
    }
    return best;
  }

  // --- Subtle grid + price labels on the right gutter ---------------------
  ctx.strokeStyle = "#161b24"; ctx.lineWidth = 1;
  ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
  ctx.textBaseline = "middle";
  const TICKS_Y = 6;
  for (let i = 0; i <= TICKS_Y; i++) {
    const p = lo + ((hi - lo) * i / TICKS_Y);
    const yy = Math.round(yP(p)) + 0.5;
    ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(padL + innerW, yy); ctx.stroke();
    ctx.fillStyle = "#7a8696";
    ctx.textAlign = "left";
    ctx.fillText(p.toFixed(2), padL + innerW + 6, yy);
  }
  // Vertical separator between chart and right price gutter.
  ctx.strokeStyle = "#1a212c";
  ctx.beginPath();
  ctx.moveTo(padL + innerW + 0.5, padT);
  ctx.lineTo(padL + innerW + 0.5, padT + innerH);
  ctx.stroke();
  // Horizontal separator above bottom time axis.
  ctx.beginPath();
  ctx.moveTo(padL, padT + innerH + 0.5);
  ctx.lineTo(padL + innerW, padT + innerH + 0.5);
  ctx.stroke();

  // --- Adaptive time axis (bottom gutter) ---------------------------------
  const spanMs = t1Vis - t0Vis;
  const intraday = spanMs < 36 * 3600 * 1000;
  function fmtT(d) {
    const dt = new Date(d);
    const p2 = (n) => String(n).padStart(2, "0");
    if (intraday) {
      // HH:mm primarily, append date when crossing midnight.
      return p2(dt.getUTCHours()) + ":" + p2(dt.getUTCMinutes());
    }
    return dt.getUTCFullYear() + "-" + p2(dt.getUTCMonth() + 1) + "-" + p2(dt.getUTCDate());
  }
  // Aim for roughly one label per ~110 px so they don't overlap.
  const colsX = Math.max(2, Math.min(10, Math.floor(innerW / 110)));
  ctx.fillStyle = "#7a8696";
  ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
  for (let c = 0; c <= colsX; c++) {
    const idx = Math.min(view.length - 1, Math.round(c * (view.length - 1) / colsX));
    const x = Math.round(xI(idx)) + 0.5;
    ctx.strokeStyle = "#161b24";
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + innerH); ctx.stroke();
    ctx.fillText(fmtT(Date.parse(view[idx].t)), x, padT + innerH + 16);
  }

  // --- Candles (TradingView teal/red) -------------------------------------
  const COL_UP = "#26a69a", COL_DN = "#ef5350";
  const candleW = Math.max(1, Math.min(slotW * 0.78, 14));
  for (let i = 0; i < view.length; i++) {
    const b = view[i];
    const x  = xI(i);
    const yo = yP(b.o), yc = yP(b.c);
    const yh = yP(b.h), yl = yP(b.l);
    const up = b.c >= b.o;
    ctx.strokeStyle = up ? COL_UP : COL_DN;
    ctx.fillStyle   = up ? COL_UP : COL_DN;
    ctx.lineWidth   = 1;
    // Wick.
    ctx.beginPath();
    ctx.moveTo(Math.round(x) + 0.5, yh);
    ctx.lineTo(Math.round(x) + 0.5, yl);
    ctx.stroke();
    // Body.
    const bodyTop = Math.min(yo, yc);
    const bodyH   = Math.max(1, Math.abs(yo - yc));
    ctx.fillRect(Math.round(x - candleW / 2), Math.round(bodyTop),
                 Math.max(1, Math.round(candleW)), Math.max(1, Math.round(bodyH)));
  }

  // --- Last-price tag on the right gutter ---------------------------------
  const lastBar = view[view.length - 1];
  const lastY   = yP(lastBar.c);
  const lastUp  = lastBar.c >= lastBar.o;
  ctx.fillStyle = lastUp ? COL_UP : COL_DN;
  ctx.fillRect(padL + innerW + 1, Math.round(lastY) - 8, padR - 2, 16);
  ctx.fillStyle = "#0b0f14";
  ctx.font = "bold 10px ui-sans-serif, system-ui, sans-serif";
  ctx.textAlign = "left"; ctx.textBaseline = "middle";
  ctx.fillText(lastBar.c.toFixed(2), padL + innerW + 6, lastY);

  // --- Strategy draw objects (under trade markers) ------------------------
  drawStrategyOverlay(ctx, tToIdx, xI, yP, padL, padT, innerW, innerH);

  // --- Trade markers ------------------------------------------------------
  const showEntries = document.getElementById("chart-show-entries")?.checked !== false;
  const showExits   = document.getElementById("chart-show-exits")?.checked   !== false;
  const showLines   = document.getElementById("chart-show-lines")?.checked !== false;
  const onlySel     = document.getElementById("chart-only-selected")?.checked === true;

  if (showEntries || showExits || showLines) {
    // Pre-compute the bar each entry/exit lands on so the marker can sit
    // just outside that bar's high/low, NinjaTrader-style — easier to click,
    // never overlaps the wick.
    for (const tr of _allTrades) {
      if (onlySel && tr.trade_no !== _selectedTradeNo) continue;
      const ie = tToIdx(Date.parse(tr.entry_time_utc));
      const ix = tToIdx(Date.parse(tr.exit_time_utc));
      if (ie < 0 && ix < 0) continue;
      const xe = ie >= 0 ? xI(ie) : null;
      const xx = ix >= 0 ? xI(ix) : null;
      const ye = yP(tr.entry_price);
      const yx = yP(tr.exit_price);
      const isLong = tr.direction === "long";
      const sel = (tr.trade_no === _selectedTradeNo);
      const win = tr.pnl_currency >= 0;

      if ((showLines || sel) && xe != null && xx != null) {
        ctx.strokeStyle = sel ? "#ffd86b"
                              : (win ? "rgba(38,166,154,0.45)" : "rgba(239,83,80,0.45)");
        ctx.lineWidth = sel ? 1.8 : 0.6;
        ctx.beginPath(); ctx.moveTo(xe, ye); ctx.lineTo(xx, yx); ctx.stroke();
      }
      if (showEntries && xe != null && ie >= 0) {
        // Anchor on the entry bar's high (short) / low (long), with a
        // small offset so the arrow sits just outside the wick.
        const bar = view[ie];
        const yMark = isLong ? (yP(bar.l) + 12) : (yP(bar.h) - 12);
        ctx.fillStyle = sel ? "#ffd86b" : (isLong ? "#4caf50" : "#ef5350");
        drawTriangle(ctx, xe, yMark, isLong);
      }
      if (showExits && xx != null) {
        ctx.fillStyle = sel ? "#ffd86b" : "#e2e8f0";
        ctx.beginPath(); ctx.arc(xx, yx, sel ? 5 : 4, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "rgba(0,0,0,0.5)"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.arc(xx, yx, sel ? 5 : 4, 0, Math.PI * 2); ctx.stroke();
      }
    }
  }

  const info = document.getElementById("chart-info");
  if (info) {
    const loaded = _bars.length;
    info.textContent =
      `Видимо: ${view.length} / ${loaded} баров · ${view[0].t} → ${view[view.length-1].t}`;
  }

  _chartGeom = { padL, padR, padT, padB, innerW, innerH,
                 t0: t0Vis, t1: t1Vis, span: Math.max(1, spanMs),
                 lo, hi, view, viewStart: vs, slotW };
}

// Renders strategy Draw.* objects on top of candles.
// Universal schema: line / horizontal_line / vertical_line / ray /
// rectangle / region / text / arrow / marker / polyline.
function drawStrategyOverlay(ctx, tToIdx, xI, yP, padL, padT, innerW, innerH) {
  const enabled = document.getElementById("chart-show-drawings")?.checked !== false;
  if (!enabled || !_drawObjects || _drawObjects.length === 0) return;
  function pXY(time, price) {
    if (time == null) return null;
    const i = tToIdx(Date.parse(time));
    if (i < 0) return null;
    return { x: xI(i), y: yP(price) };
  }
  ctx.save();
  for (const o of _drawObjects) {
    if (o.visible === false) continue;
    const stroke = o.color || "#ffaa00";
    const fill   = o.fill;
    const w      = Math.max(1, +o.strokeWidth || 1);
    ctx.strokeStyle = stroke;
    ctx.fillStyle   = fill || stroke;
    ctx.lineWidth   = w;
    if (o.dash && Array.isArray(o.dash)) ctx.setLineDash(o.dash);
    else ctx.setLineDash([]);
    const t = o.type;
    const p1 = pXY(o.time1, o.price1);
    const p2 = pXY(o.time2, o.price2);

    if (t === "horizontal_line" && o.price1 != null) {
      const y = yP(o.price1);
      ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + innerW, y); ctx.stroke();
      if (o.label || o.text) {
        ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
        ctx.textAlign = "left"; ctx.textBaseline = "bottom";
        ctx.fillStyle = stroke;
        ctx.fillText(o.label || o.text, padL + 4, y - 2);
      }
    } else if (t === "vertical_line" && p1) {
      ctx.beginPath(); ctx.moveTo(p1.x, padT); ctx.lineTo(p1.x, padT + innerH); ctx.stroke();
    } else if ((t === "line" || t === "ray") && p1 && p2) {
      ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke();
    } else if ((t === "rectangle" || t === "region") && p1 && p2) {
      const x = Math.min(p1.x, p2.x), y = Math.min(p1.y, p2.y);
      const ww = Math.abs(p2.x - p1.x), hh = Math.abs(p2.y - p1.y);
      if (fill) { ctx.fillStyle = fill; ctx.fillRect(x, y, ww, hh); }
      ctx.strokeRect(x, y, ww, hh);
    } else if (t === "text" && p1) {
      ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
      ctx.textAlign = "left"; ctx.textBaseline = "middle";
      ctx.fillStyle = stroke;
      ctx.fillText(o.text || o.label || "", p1.x + 4, p1.y);
    } else if ((t === "arrow" || t === "marker") && p1) {
      ctx.beginPath(); ctx.arc(p1.x, p1.y, 4, 0, Math.PI * 2); ctx.fill();
    } else if (Array.isArray(o.points) && o.points.length >= 2) {
      ctx.beginPath();
      let started = false;
      for (const pt of o.points) {
        const q = pXY(pt.time, pt.price);
        if (!q) continue;
        if (!started) { ctx.moveTo(q.x, q.y); started = true; }
        else ctx.lineTo(q.x, q.y);
      }
      ctx.stroke();
    }
  }
  ctx.setLineDash([]);
  ctx.restore();
}

async function loadDrawObjects() {
  if (!_selectedJob) return;
  const startedFor = _selectedJob;
  if (_drawObjectsLoadingFor === startedFor) return;
  _drawObjectsLoadingFor = startedFor;
  const banner = document.getElementById("chart-drawings-status");
  try {
    const data = await api.get(`/api/jobs/${encodeURIComponent(startedFor)}/draw_objects`);
    if (_selectedJob !== startedFor) return;
    _drawObjectsLoadingFor = null;
    _drawObjects = (data.objects || []).filter(o => o && o.type);
    _drawObjectsState = {
      exported: data.exported === true,
      reason: data.reason || null,
      diagnostics: data.diagnostics || [],
    };
    if (banner) {
      if (!data.exported) {
        banner.hidden = false;
        banner.textContent = "Отрисовки стратегии не экспортированы bridge.";
      } else if (_drawObjects.length === 0) {
        banner.hidden = false;
        banner.textContent = "Отрисовки стратегии: 0 объектов " +
          "(NinjaScript Draw.* пропускается в headless RunBacktest).";
      } else {
        banner.hidden = true;
        banner.textContent = `Отрисовки стратегии: ${_drawObjects.length} объектов.`;
      }
    }
    drawPriceChart();
  } catch (e) {
    _drawObjectsLoadingFor = null;
    _drawObjects = [];
    _drawObjectsState = { exported: false, reason: "fetch_error", diagnostics: [String(e)] };
    if (banner) {
      banner.hidden = false;
      banner.textContent = "Отрисовки стратегии: ошибка загрузки (" + e.message + ")";
    }
  }
}
function drawTriangle(ctx, x, y, up) {
  // NinjaTrader-style entry arrow with stem. Total height ~18px.
  // Long (up): arrowhead pointing UP toward bar, stem extends downward.
  // Short (down): arrowhead pointing DOWN toward bar, stem extends upward.
  const w = 9, headH = 10, s = 2.5, stemH = 8;
  ctx.beginPath();
  if (up) {
    ctx.moveTo(x, y - headH);      // tip (toward bar)
    ctx.lineTo(x - w, y);          // left base of head
    ctx.lineTo(x - s, y);          // narrow to stem
    ctx.lineTo(x - s, y + stemH);  // stem bottom-left
    ctx.lineTo(x + s, y + stemH);  // stem bottom-right
    ctx.lineTo(x + s, y);          // up right side of stem
    ctx.lineTo(x + w, y);          // right base of head
  } else {
    ctx.moveTo(x, y + headH);      // tip (toward bar)
    ctx.lineTo(x + w, y);          // right base of head
    ctx.lineTo(x + s, y);          // narrow to stem
    ctx.lineTo(x + s, y - stemH);  // stem top-right
    ctx.lineTo(x - s, y - stemH);  // stem top-left
    ctx.lineTo(x - s, y);          // down left side of stem
    ctx.lineTo(x - w, y);          // left base of head
  }
  ctx.closePath();
  ctx.fill();
  ctx.save();
  ctx.lineWidth = 1.2;
  ctx.strokeStyle = "rgba(0,0,0,0.6)";
  ctx.stroke();
  ctx.restore();
}

// Re-render chart when toolbar toggled.
{
  ["chart-show-entries", "chart-show-exits", "chart-show-lines",
   "chart-only-selected", "chart-show-drawings"].forEach(id => {
    const cb = document.getElementById(id);
    if (cb) cb.addEventListener("change", drawPriceChart);
  });
}

// Center the chart's visible window on a given trade's entry time and
// switch to the chart tab. Used by the trades-table row click handler so
// the user can jump from a row to the corresponding price action.
function centerChartOnTrade(tradeNo) {
  if (_barsState !== "ok" || !_bars || _bars.length === 0) return;
  const tr = _allTrades.find(x => x.trade_no === tradeNo);
  if (!tr) return;
  const te = Date.parse(tr.entry_time_utc);
  // Find nearest bar index by binary scan.
  let best = 0, bestD = Infinity;
  for (let i = 0; i < _bars.length; i++) {
    const d = Math.abs(Date.parse(_bars[i].t) - te);
    if (d < bestD) { bestD = d; best = i; }
  }
  const [vs, ve] = _chartView();
  const size = Math.max(60, ve - vs);
  let ns = best - Math.floor(size / 2);
  let ne = ns + size;
  if (ns < 0) { ne -= ns; ns = 0; }
  if (ne > _bars.length) { ns -= (ne - _bars.length); ne = _bars.length; }
  if (ns < 0) ns = 0;
  _chartViewStart = ns; _chartViewEnd = ne;
  _selectedTradeNo = tradeNo;
  drawPriceChart();
}

// Click on canvas → find nearest trade marker, select it.
// ---- Chart interaction: wheel zoom, drag pan, hover tooltip, click-to-select.
(function attachChartInteraction() {
  const cv = document.getElementById("price-canvas");
  if (!cv) return;
  const tooltip = document.getElementById("chart-tooltip");

  // Convert mouse X → bar index in _bars using the index-based geometry.
  function xToBarIndex(xPx) {
    if (!_chartGeom || !_bars || _bars.length === 0) return -1;
    const g = _chartGeom;
    const rel = (xPx - g.padL) / g.innerW;
    if (rel < 0 || rel > 1) return -1;
    const i = Math.max(0, Math.min(g.view.length - 1,
                                   Math.floor(rel * g.view.length)));
    return g.viewStart + i;
  }
  // Helper used by tooltip / click hit-testing for trade markers.
  // Returns the on-screen position of the entry arrow (anchored at the
  // entry bar's high/low, matching what drawPriceChart renders).
  function tradeXY(tr, g) {
    const te = Date.parse(tr.entry_time_utc);
    if (te < g.t0 || te > g.t1) return null;
    let l = 0, r = g.view.length - 1, best = 0, bestD = Infinity;
    while (l <= r) {
      const m = (l + r) >> 1;
      const tm = Date.parse(g.view[m].t);
      const d = Math.abs(tm - te);
      if (d < bestD) { bestD = d; best = m; }
      if (tm < te) l = m + 1; else r = m - 1;
    }
    const bar = g.view[best];
    const x = g.padL + (best + 0.5) * g.slotW;
    const isLong = tr.direction === "long";
    const yPrice = (p) => g.padT + g.innerH - ((p - g.lo) / (g.hi - g.lo)) * g.innerH;
    const y = isLong ? (yPrice(bar.l) + 12) : (yPrice(bar.h) - 12);
    return { x, y };
  }

  // ---- wheel zoom (centered on cursor) ---
  cv.addEventListener("wheel", (ev) => {
    if (_barsState !== "ok" || !_bars || _bars.length === 0) return;
    ev.preventDefault();
    const r = cv.getBoundingClientRect();
    const x = ev.clientX - r.left;
    const idx = xToBarIndex(x);
    if (idx < 0) return;
    const [vs, ve] = _chartView();
    const size = ve - vs;
    const factor = (ev.deltaY > 0) ? 1.25 : 0.8;
    let newSize = Math.round(size * factor);
    newSize = Math.max(20, Math.min(_bars.length, newSize));
    // Keep cursor anchored to the same bar.
    const ratio = (idx - vs) / Math.max(1, size);
    let newStart = Math.round(idx - ratio * newSize);
    let newEnd   = newStart + newSize;
    if (newStart < 0) { newStart = 0; newEnd = newSize; }
    if (newEnd > _bars.length) { newEnd = _bars.length; newStart = newEnd - newSize; }
    if (newStart < 0) newStart = 0;
    _chartViewStart = newStart;
    _chartViewEnd   = newEnd;
    drawPriceChart();
  }, { passive: false });

  // ---- drag pan ---
  cv.addEventListener("mousedown", (ev) => {
    if (_barsState !== "ok" || !_bars || _bars.length === 0) return;
    _chartIsDragging = true;
    _chartDragStartX = ev.clientX;
    const [vs, ve] = _chartView();
    _chartDragStartView = [vs, ve];
    cv.style.cursor = "grabbing";
  });
  window.addEventListener("mouseup", () => {
    if (_chartIsDragging) { _chartIsDragging = false; cv.style.cursor = ""; }
  });
  cv.addEventListener("mouseleave", () => {
    if (tooltip) tooltip.hidden = true;
  });

  // ---- mousemove: pan or hover-tooltip ---
  cv.addEventListener("mousemove", (ev) => {
    if (_barsState !== "ok" || !_bars || _bars.length === 0) return;
    const r = cv.getBoundingClientRect();
    const x = ev.clientX - r.left;
    const y = ev.clientY - r.top;

    if (_chartIsDragging) {
      if (!_chartGeom) return;
      const [vs0, ve0] = _chartDragStartView;
      const size = ve0 - vs0;
      const barWidth = _chartGeom.innerW / Math.max(1, size);
      const dx = ev.clientX - _chartDragStartX;
      const shift = -Math.round(dx / barWidth);
      let ns = vs0 + shift, ne = ve0 + shift;
      if (ns < 0) { ne -= ns; ns = 0; }
      if (ne > _bars.length) { ns -= (ne - _bars.length); ne = _bars.length; }
      if (ns < 0) ns = 0;
      _chartViewStart = ns; _chartViewEnd = ne;
      drawPriceChart();
      return;
    }

    // Hover tooltip.
    if (!tooltip || !_chartGeom) return;
    const idx = xToBarIndex(x);
    if (idx < 0 || idx >= _bars.length) { tooltip.hidden = true; return; }
    const b = _bars[idx];
    let html = `<div><b>${b.t.replace("T", " ").replace("Z", "")}</b></div>` +
      `<div>O ${fmtPx(b.o)} · H ${fmtPx(b.h)}</div>` +
      `<div>L ${fmtPx(b.l)} · C ${fmtPx(b.c)}</div>` +
      `<div>V ${b.v != null ? b.v.toLocaleString() : "—"}</div>`;

    // Look for a trade marker close to the cursor (index-based geometry).
    let nearestTrade = null, nearestD = Infinity;
    const g = _chartGeom;
    for (const tr of _allTrades) {
      const xy = tradeXY(tr, g);
      if (!xy) continue;
      const d = Math.hypot(xy.x - x, xy.y - y);
      if (d < nearestD) { nearestD = d; nearestTrade = tr; }
    }
    if (nearestTrade && nearestD < 16) {
      const t = nearestTrade;
      html += `<hr style="border-color:#2a2f3d;margin:4px 0">` +
        `<div>trade #${t.trade_no} (${t.direction})</div>` +
        `<div>entry ${fmtPx(t.entry_price)} → exit ${fmtPx(t.exit_price)}</div>` +
        `<div>pnl ${fmtMoneySign(t.pnl_currency)}</div>`;
    }
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    // Position above-right of cursor; clamp inside canvas.
    const cw = cv.clientWidth, ch = cv.clientHeight;
    let tx = x + 14, ty = y + 14;
    const tw = tooltip.offsetWidth || 180;
    const th = tooltip.offsetHeight || 70;
    if (tx + tw > cw) tx = x - tw - 14;
    if (ty + th > ch) ty = y - th - 14;
    tooltip.style.left = tx + "px";
    tooltip.style.top  = ty + "px";
  });

  // ---- click → select nearest trade marker (only if no drag happened).
  let _downX = 0;
  cv.addEventListener("mousedown", (ev) => { _downX = ev.clientX; });
  cv.addEventListener("click", (ev) => {
    if (_barsState !== "ok" || !_allTrades.length || !_chartGeom) return;
    if (Math.abs(ev.clientX - _downX) > 3) return;   // was a drag, not a click
    const r = cv.getBoundingClientRect();
    const x = ev.clientX - r.left;
    const y = ev.clientY - r.top;
    const g = _chartGeom;
    let best = null, bestD = Infinity;
    for (const tr of _allTrades) {
      const xy = tradeXY(tr, g);
      if (!xy) continue;
      const d = (xy.x - x) * (xy.x - x) + (xy.y - y) * (xy.y - y);
      if (d < bestD) { bestD = d; best = tr; }
    }
    if (best && bestD < 30 * 30) {
      switchResultTab("analysis");
      _selectedTradeNo = best.trade_no;
      const idx = _filteredTrades.findIndex(t => t.trade_no === best.trade_no);
      if (idx >= 0) {
        _tradesOffset = Math.floor(idx / TRADES_PAGE) * TRADES_PAGE;
      }
      renderTradesTable();
      const row = document.querySelector(
        `#trades-table tbody tr[data-trade-no="${best.trade_no}"]`);
      if (row) row.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  });

  // ---- Reset view button ---
  const reset = document.getElementById("chart-reset-view");
  if (reset) {
    reset.addEventListener("click", () => {
      _chartViewStart = 0;
      _chartViewEnd   = null;
      drawPriceChart();
    });
  }
})();

// ---------------- diagnostics --------------------------------------------
async function refreshNinjaTraderChip() {
  try {
    const h = await api.get("/api/health");
    const pill = document.getElementById("health-pill");
    if (pill) {
      pill.textContent = `backend ok @ ${h.host}`;
      pill.classList.remove("bad");
      pill.classList.add("ok");
    }
    if (h.ninjatrader_running === true) {
      _ntRunning = true;
      setStatusChip("ss-nt", "NinjaTrader: запущен", "ok");
    } else if (h.ninjatrader_running === false) {
      _ntRunning = false;
      setStatusChip("ss-nt", "NinjaTrader: не запущен", "warn");
    } else {
      _ntRunning = null;
      setStatusChip("ss-nt", "NinjaTrader: статус неизвестен", "warn");
    }
    // Refresh pending-state label if a job is currently waiting.
    if (_activeRun && (_activeRun.last_status === "pending")) {
      setSubmitState("pending");
      renderActiveRunPanel();
    }
  } catch (e) {
    setStatusChip("ss-nt", "Backend: недоступен", "bad");
  }
}

async function refreshDiagnostics() {
  try {
    const d = await api.get("/api/diagnostics");
    document.getElementById("d-nt").textContent =
      d.ninjatrader_running === true ? "yes"
      : d.ninjatrader_running === false ? "no"
      : "unknown";
    document.getElementById("d-ntdir").textContent = d.ninjatrader_user_dir;
    const dlog = document.getElementById("d-log");
    const parts = [];
    if (Array.isArray(_diagCatalogWarnings) && _diagCatalogWarnings.length) {
      parts.push("[catalog warnings]");
      for (const w of _diagCatalogWarnings) parts.push("  - " + w);
      parts.push("");
    }
    parts.push("[bridge log tail]");
    parts.push((d.bridge_log_tail || []).join("\n") || "(log empty or missing)");
    dlog.textContent = parts.join("\n");
    // Catalog status block.
    const cs = (d.catalog && d.catalog.staleness) || {};
    const gen = ((d.catalog && d.catalog.generated_at_utc) || {}).strategies || "—";
    const cnt = (d.catalog && d.catalog.strategies_count) || 0;
    const status = document.getElementById("d-catalog-status");
    let line = "Стратегий: " + cnt + " · сгенерировано: " + gen;
    if (cs.stale) {
      const reason = cs.reason === "dll_newer"
        ? "NinjaScript был перекомпилирован — каталог устарел"
        : (cs.reason === "catalog_missing" ? "каталог отсутствует" : "устарел");
      line += " · ⚠ " + reason;
    } else {
      line += " · актуален";
    }
    status.textContent = line;
  } catch (e) {
    document.getElementById("d-log").textContent = `error: ${e.message}`;
  }
}

function updateStaleChip(stale) {
  const chip = document.getElementById("ss-stale");
  const txt  = document.getElementById("ss-stale-text");
  if (!chip || !txt) return;
  if (!stale || !stale.stale) { chip.hidden = true; return; }
  if (stale.reason === "catalog_missing") {
    txt.textContent = "Каталог стратегий отсутствует";
  } else {
    txt.textContent = "Каталог стратегий устарел (NinjaScript перекомпилирован)";
  }
  chip.hidden = false;
}

async function triggerCatalogRefresh(source) {
  const btnChip = document.getElementById("ss-stale-btn");
  const btnDiag = document.getElementById("d-catalog-refresh");
  const msg     = document.getElementById("d-catalog-refresh-msg");
  for (const b of [btnChip, btnDiag]) if (b) b.disabled = true;
  if (msg) msg.textContent = "обновление…";
  try {
    const r = await api.post("/api/catalog/refresh", {});
    if (r && r.ok) {
      if (msg) msg.textContent = "готово · стратегий: " + (r.strategies_count || 0);
      await loadCatalog();
      await refreshDiagnostics();
    } else {
      const err = (r && (r.error || r.reason)) || "не удалось обновить";
      if (msg) msg.textContent = "ошибка: " + err;
      alert("Не удалось обновить каталог: " + err);
    }
  } catch (e) {
    if (msg) msg.textContent = "ошибка: " + e.message;
    alert("Ошибка обновления каталога: " + e.message);
  } finally {
    for (const b of [btnChip, btnDiag]) if (b) b.disabled = false;
  }
}

bootstrap();
