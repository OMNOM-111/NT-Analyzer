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
};

// ---------------- active-run state machine -------------------------------
// Tracks the most recently submitted single job or batch so we can show
// "Ожидание…/В работе…", display a cancel button, and gate the submit
// button until the run reaches a terminal status.
let _activeRun = null;
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

function isTerminalStatus(s) {
  return s === "done" || s === "failed" || s === "cancelled" || s === "missing";
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
      const done = (c.done||0) + (c.failed||0) + (c.cancelled||0) + (c.missing||0);
      _activeRun.last_status =
        (c.running||0) > 0 ? "running" :
        (c.pending||0) > 0 ? "pending" :
        (c.failed||0) === total && total > 0 ? "failed" :
        (c.cancelled||0) === total && total > 0 ? "cancelled" :
        "done";
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
  submit.textContent = state === "running" ? "В работе…" : "Ожидание…";
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
      ? `${(p.from_utc||"").slice(0,10)} → ${(p.to_utc||"").slice(0,10)}`
      : "—";

  // Progress (batch only). For single-job there's no fraction we can trust.
  const bar  = document.getElementById("active-run-bar");
  const txt  = document.getElementById("active-run-progress");
  const hint = document.getElementById("active-run-hint");
  if (ar.kind === "batch" && ar.counts && ar.total) {
    const c = ar.counts;
    const finished = (c.done||0) + (c.failed||0) + (c.cancelled||0) + (c.missing||0);
    const pct = ar.total > 0 ? Math.round((finished / ar.total) * 100) : 0;
    bar.style.width = pct + "%";
    txt.textContent = `${finished} из ${ar.total} · в работе ${c.running||0} · ожидает ${c.pending||0}` +
      ((c.failed||0) > 0 ? ` · ошибок ${c.failed}` : "");
    hint.hidden = true;
  } else {
    // Single job: indeterminate bar (just full when done).
    const finished = isTerminalStatus(ar.last_status);
    bar.style.width = finished ? "100%" : (ar.last_status === "running" ? "55%" : "15%");
    txt.textContent = ar.kind === "batch" ? "Ожидание данных…" : "Один инструмент";
    if (!finished) {
      hint.hidden = false;
      hint.textContent = "Прогресс по датам недоступен — bridge не отдаёт его в MVP-1.";
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
  refreshJobs();
}

// Compat shim: was previously a small "recent reports" placeholder block.
// The full reports list now lives in #reports-panel and is refreshed via
// refreshJobs(), so all callers can simply hit refreshJobs() instead.
function loadRecentReports() { refreshJobs(); }

function summarizeBatchCounts(c, total) {
  const p = c.pending||0, r = c.running||0;
  if (p + r > 0) return r > 0 ? "running" : "pending";
  if ((c.failed||0) === total && total > 0) return "failed";
  if ((c.cancelled||0) === total && total > 0) return "cancelled";
  return "done";
}

// ---------------- overlay panels (Jobs / Diagnostics) -------------------
function openOverlay(name) {
  const el = document.getElementById(`overlay-${name}`);
  if (!el) return;
  el.hidden = false;
  if (name === "jobs") refreshJobs();
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

// ---------------- bootstrap -----------------------------------------------
let _catalog = null;  // last GET /api/catalog response

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
    document.getElementById("d-host").textContent = h.host;
    document.getElementById("d-root").textContent = h.project_root;
  } catch (e) {
    document.getElementById("health-pill").textContent = "backend недоступен";
    document.getElementById("health-pill").classList.add("bad");
    setStatusChip("ss-nt", "Backend: недоступен", "bad");
  }

  await loadCatalog();

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
      refreshJobs();
    });
  });
  document.getElementById("jobs-refresh").addEventListener("click", refreshJobs);

  document.getElementById("run-cancel").addEventListener("click", onCancelActiveRun);

  refreshJobs();
  // Auto-refresh jobs every 2s.
  setInterval(refreshJobs, 2000);
  // Auto-refresh NinjaTrader status chip every 10s.
  setInterval(refreshNinjaTraderChip, 10000);
  // Active-run elapsed-time tick (visual only; status comes from poll).
  setInterval(tickActiveRunElapsed, 1000);

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

  // 2) instrument basket: groups + instruments + selected. Default basket
  //    holds MES 06-26 (or first available) so the single-instrument
  //    workflow keeps working with one click.
  initBasket();
  if (_basket.length === 0) {
    const has = (cat.instruments || []).find(i => i.instrument === "MES 06-26");
    if (has) _basket.push("MES 06-26");
    else if (cat.instruments && cat.instruments[0]) _basket.push(cat.instruments[0].instrument);
    renderBasket();
  }
  renderInstrumentBrowser();
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
  cSel.value = "None";
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
      try { localStorage.setItem("ib_hidden", hidden ? "1" : "0"); } catch {}
    });
    try {
      if (localStorage.getItem("ib_hidden") === "1") {
        document.getElementById("workbench")?.classList.add("no-instruments");
      }
    } catch {}
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
  if (_activeRun) {
    // A run is already in flight — guard against double submit.
    return;
  }
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
      refreshJobs();
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
      refreshJobs();
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
let _jobsFilter  = "all";  // all | running | done | failed

// Whitelist of allowed status -> CSS class. Anything else falls back to
// "unknown" so an unexpected backend value can never inject arbitrary
// classNames into the DOM.
const STATUS_CLASSES = {
  pending:   "pending",
  running:   "running",
  done:      "done",
  failed:    "failed",
  cancelled: "cancelled",
};
const STATUS_LABELS = {
  pending:   "ожидание",
  running:   "в работе",
  done:      "готово",
  failed:    "ошибка",
  cancelled: "отменено",
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
function setSelectedReport(kind, id) {
  _selectedReportKey = `${kind}:${id}`;
  const tbody = document.querySelector("#jobs-table tbody");
  if (!tbody) return;
  tbody.querySelectorAll("tr").forEach(r => {
    r.classList.toggle("selected", r.dataset.repkey === _selectedReportKey);
  });
}

async function refreshJobs() {
  let jobsData = null, batchesData = null;
  try { jobsData = await api.get("/api/jobs?limit=50"); } catch (e) { /* noop */ }
  try { batchesData = await api.get("/api/batches?limit=50"); } catch (e) { /* noop */ }
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
    items.push({
      kind: "batch",
      id: b.batch_id,
      label: b.name || b.batch_id,
      strategy: b.class_name || "—",
      status: summarizeBatchCounts(b.counts || {}, b.total || 0),
      counts: b.counts || {},
      total: b.total || 0,
      period: b.period || null,
      created: b.created_at_utc || "",
      finished: "",
      trades: b.trade_count != null ? b.trade_count : null,
      winning_pct: b.winning_pct != null ? b.winning_pct : null,
      net_profit: b.net_profit != null ? b.net_profit : null,
      mtime: b.created_at_utc ? Date.parse(b.created_at_utc) : 0,
    });
  }
  for (const j of jobsData.jobs || []) {
    if (j.batch && j.batch.batch_id) continue;
    const finished = j.finished_at_utc || j.heartbeat_at_utc || "";
    items.push({
      kind: "job",
      id: j.job_id,
      label: fmtContract(j.instrument) || j.job_id,
      strategy: j.class_name || "—",
      status: j.status,
      period: j.period || null,
      created: j.created_at_utc || "",
      finished: finished,
      trades: j.trade_count != null ? j.trade_count : null,
      winning_pct: j.winning_pct != null ? j.winning_pct : null,
      net_profit: j.net_profit != null ? j.net_profit : null,
      mtime: j.mtime ? j.mtime * 1000
              : (j.created_at_utc ? Date.parse(j.created_at_utc) : 0),
    });
  }
  items.sort((a,b) => b.mtime - a.mtime);

  // Apply the toolbar status filter.
  const filtered = items.filter(it =>
    _jobsFilter === "all" ? true : (it.status === _jobsFilter)
  );

  const tbody = document.querySelector("#jobs-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  filtered.forEach(it => {
    const tr = el("tr");
    tr.dataset.repkey = `${it.kind}:${it.id}`;
    if (tr.dataset.repkey === _selectedReportKey) tr.classList.add("selected");

    // Имя / инструмент (with id as title for power users)
    const tdName = el("td", { cls: "col-rep-name" });
    tdName.textContent = it.label;
    tdName.title = `${it.kind === "batch" ? "Пакет" : "Запуск"}: ${it.id}`;
    tr.appendChild(tdName);

    // Тип
    const tdKind = el("td");
    tdKind.appendChild(el("span", {
      cls: "badge-kind " + it.kind,
      text: it.kind === "batch"
              ? `пакет ×${it.total || ""}`.trim()
              : "запуск",
    }));
    tr.appendChild(tdKind);

    // Стратегия
    tr.appendChild(td(it.strategy));

    // Статус (for batches show counts inline)
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

    // Период
    const period = it.period
      ? `${(it.period.from_utc||"").slice(0,10)} → ${(it.period.to_utc||"").slice(0,10)}`
      : "";
    tr.appendChild(td(period, {
      title: it.period ? `${it.period.from_utc} → ${it.period.to_utc}` : "" }));

    // Создан / Финиш / Сделок / Win%
    tr.appendChild(td(it.created));
    tr.appendChild(td(it.finished));
    tr.appendChild(td(it.trades != null ? it.trades : "", { cls: "col-num-compact" }));

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

    // Delete button (×) — stops propagation so it doesn't open the report.
    const tdDel = el("td", { cls: "col-del" });
    const btnDel = el("button");
    btnDel.className = "btn-row-delete";
    btnDel.title = "Удалить отчёт";
    btnDel.textContent = "×";
    btnDel.addEventListener("click", (ev) => {
      ev.stopPropagation();
      deleteReport(it.kind, it.id);
    });
    tdDel.appendChild(btnDel);
    tr.appendChild(tdDel);

    tr.addEventListener("click", () => {
      setSelectedReport(it.kind, it.id);
      if (it.kind === "batch") openBatch(it.id);
      else openResult(it.id);
    });
    tbody.appendChild(tr);
  });
}

async function deleteReport(kind, id) {
  const label = kind === "batch" ? "пакет" : "запуск";
  if (!confirm(`Удалить ${label} «${id}»? Это действие необратимо.`)) return;
  const url = kind === "batch"
    ? `/api/batches/${encodeURIComponent(id)}`
    : `/api/jobs/${encodeURIComponent(id)}`;
  try {
    const resp = await fetch(url, { method: "DELETE" });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      const msg = data.error || data.message || resp.statusText;
      alert(`Не удалось удалить: ${msg}`);
      return;
    }
  } catch (e) {
    alert(`Ошибка при удалении: ${e.message}`);
    return;
  }
  // If the deleted report was the one currently displayed, clear the detail area.
  if (_selectedReportKey === `${kind}:${id}`) {
    _selectedReportKey = null;
    document.getElementById("result-content").hidden = true;
    document.getElementById("result-empty").hidden = false;
  }
  refreshJobs();
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
let _barsState = "loading"; // loading|ok|missing|error
let _drawObjects = [];      // strategy draw objects (universal schema)
let _drawObjectsState = { exported: false, reason: "loading", diagnostics: [] };
let _chartHover = null;
let _resultJob = null;      // last loaded job for chart cross-reference

const _tradeFilters = { side: "all", pnl: "all" };

let _activeBatch = null;        // batch detail object, or null for single-job mode
let _activeBatchRows = [];      // rows[] from /api/batches/{id}/results
let _batchPollTimer = null;     // setTimeout id for auto-refresh while jobs run

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
  // Standalone job: highlight in reports panel.
  setSelectedReport("job", jobId);

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
  };
  _activeBatchRows = [singleRow];
  renderResultRowsTable(_activeBatchRows, jobId);
  await setActiveJob(jobId, job);
}

async function openBatch(batchId, focusJobId) {
  setSelectedReport("batch", batchId);
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
  _activeBatchRows = (data.rows || []).slice();

  // Decorate rows for table render: strategy class + params from manifest.
  const stratClass = (data.strategy && data.strategy.class_name) || "";
  const params = (data.strategy && data.strategy.parameters) || {};
  for (const r of _activeBatchRows) {
    r._strategy_class = stratClass;
    r._params = params;
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

  rows.forEach(r => {
    const tr = el("tr");
    if (r.job_id === activeJobId) tr.classList.add("selected");
    if (r.status === "failed") tr.classList.add("row-failed");
    if (r.period_check && r.period_check.ok === false) tr.classList.add("row-period-bad");

    const paramStr = r._params && Object.keys(r._params).length
      ? Object.entries(r._params).map(([k,v]) => `${k}=${v}`).join(", ")
      : "";
    if (paramStr) tr.title = `Параметры: ${paramStr}`;
    tr.appendChild(td(fmtContract(r.instrument) || "—", { cls: "col-instr" }));
    tr.appendChild(td(r._strategy_class || "—", { cls: "col-strat" }));

    const m = r.metrics || {};
    tr.appendChild(td(fmtMoneySign(m.gross_profit), { cls: "num pos" }));
    tr.appendChild(td(fmtMoneySign(m.gross_loss),   { cls: "num neg" }));
    tr.appendChild(td(
      typeof m.profit_factor === "number"
        ? m.profit_factor.toLocaleString(undefined, { minimumFractionDigits: 3, maximumFractionDigits: 3 })
        : "—",
      { cls: "num " + (m.profit_factor >= 1 ? "pos" : (m.profit_factor != null ? "neg" : "")) }));
    tr.appendChild(td(fmtMoneySign(m.max_drawdown), { cls: "num neg" }));
    tr.appendChild(td(m.trade_count != null ? m.trade_count.toLocaleString() : "—",
      { cls: "num" }));
    tr.appendChild(td(
      typeof m.winning_pct === "number"
        ? m.winning_pct.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%"
        : "—", { cls: "num" }));

    const tdStatus = el("td");
    tdStatus.appendChild(el("span", {
      cls: "status-badge " + (STATUS_CLASSES[r.status] || "unknown"),
      text: statusLabel(r.status) }));
    tr.appendChild(tdStatus);

    const tdPC = el("td");
    const pc = r.period_check;
    let pcText = "n/a", pcCls = "unknown";
    if (pc) {
      if (pc.ok) { pcText = "OK"; pcCls = "ok"; }
      else { pcText = `FAIL ${pc.before_from}/${pc.after_to}`; pcCls = "fail"; }
    }
    tdPC.appendChild(el("span", { cls: "status-badge " + pcCls, text: pcText }));
    tr.appendChild(tdPC);

    // Итог (net profit) — moved to end of the row.
    tr.appendChild(td(fmtMoneySign(m.net_profit), {
      cls: "num " + (m.net_profit > 0 ? "pos" : (m.net_profit < 0 ? "neg" : "")) }));

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
  _barsState = "loading";
  _drawObjects = [];
  _drawObjectsState = { exported: false, reason: "loading", diagnostics: [] };
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
  await loadAllTrades();
  // Now that trades are loaded, populate the All/Long/Short matrix.
  renderPerfMatrix(metrics, _allTrades, exec);
  // ---- График: bars + strategy draw objects (lazy, but kick off now) ---
  loadBars();
  loadDrawObjects();
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
  if (!_selectedJob) return;
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
        `/api/jobs/${encodeURIComponent(_selectedJob)}/trades`
        + `?offset=${off}&limit=${PAGE}`
      );
    } catch (e) { break; }
    const got = data.trades || [];
    acc = acc.concat(got);
    off += got.length;
    if (got.length < PAGE || off >= (data.total || 0)) break;
  }
  _allTrades = acc;
  applyTradeFilters();
  drawEquityCurve();
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
  if (name === "chart")    requestAnimationFrame(drawPriceChart);
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
  const status = document.getElementById("chart-status");
  const info   = document.getElementById("chart-info");
  status.classList.remove("error");
  status.hidden = false;
  status.textContent = "Загрузка bars.json…";
  // Capture which job we started loading for; if user clicks another row
  // before paging completes, abandon results to avoid mixing instruments.
  const startedFor = _selectedJob;
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
        status.hidden = false;
        status.textContent =
          "График недоступен: bars.json отсутствует для этого job. " +
          "Перезапустите бэктест после обновления bridge — bars.json появится у новых jobs.";
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
    status.hidden = false;
    status.classList.add("error");
    status.textContent = "Ошибка загрузки bars.json: " + e.message;
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
  const startedFor = _selectedJob;
  const banner = document.getElementById("chart-drawings-status");
  try {
    const data = await api.get(`/api/jobs/${encodeURIComponent(startedFor)}/draw_objects`);
    if (_selectedJob !== startedFor) return;
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
      setStatusChip("ss-nt", "NinjaTrader: запущен", "ok");
    } else if (h.ninjatrader_running === false) {
      setStatusChip("ss-nt", "NinjaTrader: не запущен", "warn");
    } else {
      setStatusChip("ss-nt", "NinjaTrader: статус неизвестен", "warn");
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
