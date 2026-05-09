// Strategy Control Center — SCC v2
// Data source: /api/scc/strategies (real NT Strategies folder + runtime telemetry)
// NO fake running statuses. NO rejected-strategy launches.
// Launch: real command via bridge, or manual flow if bridge offline.

"use strict";

// ---------- helpers ---------------------------------------------------------
const $ = id => document.getElementById(id);
function esc(s) {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g,
    c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtMoney(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!isFinite(n)) return "—";
  return (n >= 0 ? "+" : "") + "$" + n.toFixed(2);
}
async function api(url, opts) {
  const r = await fetch(url, Object.assign({ headers: {"Content-Type":"application/json"} }, opts||{}));
  let body = null;
  try { body = await r.json(); } catch { body = {error: r.statusText}; }
  if (!r.ok) {
    const err = new Error(body?.error || "HTTP " + r.status);
    err.status = r.status; err.body = body;
    throw err;
  }
  return body;
}

// ---------- state -----------------------------------------------------------
const S = {
  data:       null,   // result from /api/scc/strategies
  selectedCls: null,  // class_name of selected strategy
  activeTab:  "runtime",
  launching:  false,
};

// ---------- main refresh ----------------------------------------------------
async function refresh() {
  let data;
  try {
    data = await api("/api/scc/strategies");
  } catch (e) {
    renderChipBad("chip-backend", "Backend: ошибка");
    return;
  }
  S.data = data;

  const hb = data.heartbeat || {};
  const fresh = hb.fresh === true;

  // Status chips
  renderChip("chip-backend", "Backend: OK", "ok");
  if (!hb.present) {
    renderChip("chip-nt", "NT Runtime: оффлайн", "bad");
    renderChip("chip-acct", "Аккаунт: —", "");
  } else if (!fresh) {
    const age = hb.age_sec != null ? ` (${hb.age_sec}s)` : "";
    renderChip("chip-nt", `NT Runtime: устарел${age}`, "warn");
    renderChip("chip-acct", "Аккаунт: —", "warn");
  } else {
    renderChip("chip-nt", "NT Runtime: OK", "ok");
    // Show account from first active running strategy
    const running = (data.strategies || []).find(s => s.runtime_enabled);
    const acct = running ? running.account_name : "—";
    const mode = running ? running.account_mode : "";
    const cls = mode === "paper" ? "ok" : mode === "live" ? "bad" : "";
    renderChip("chip-acct", `Аккаунт: ${acct}${mode ? " (" + mode + ")" : ""}`, cls);
  }

  // Alarms
  renderAlarms(data);

  // Strategy list
  renderStrategyList(data.strategies || []);

  // Refresh params panel if a strategy is selected
  if (S.selectedCls) {
    const sel = (data.strategies || []).find(s => s.class_name === S.selectedCls);
    if (sel) renderParamsPanel(sel);
  }

  // Refresh active tab
  refreshActiveTab();
}

function renderChip(id, text, cls) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.className = "chip" + (cls ? " " + cls : "");
}
function renderChipBad(id, text) { renderChip(id, text, "bad"); }

// ---------- alarms ----------------------------------------------------------
function renderAlarms(data) {
  const strip = $("alarm-strip");
  if (!strip) return;
  const rejRunning = data.rejected_running || [];
  let html = "";
  for (const r of rejRunning) {
    html += `<div class="alarm red">⛔ <b>Отклонённая стратегия ${esc(r.class_name)}</b>
      запущена в NinjaTrader (аккаунт: ${esc(r.account_name || "—")}).
      Немедленно выключите её в NinjaTrader → Strategies.</div>`;
  }
  // Warn if any active strategy shows runtime_enabled but bridge is stale
  const hb = data.heartbeat || {};
  if (!hb.fresh && (data.strategies || []).some(s => s.runtime)) {
    html += `<div class="alarm yellow">⚠ Сигнал NT bridge устарел — данные из NinjaTrader могут быть неактуальны.</div>`;
  }
  strip.innerHTML = html;
}

// ---------- strategy list (left panel) --------------------------------------
function renderStrategyList(strategies) {
  const list = $("strat-list");
  const cnt  = $("cnt-chip");
  if (!list) return;
  cnt.textContent = String(strategies.length);
  if (!strategies.length) {
    list.innerHTML = `<div class="empty">Активные стратегии не найдены.<br>Источник: NinjaTrader 8/bin/Custom/Strategies</div>`;
    return;
  }
  let html = "";
  for (const s of strategies) {
    const active = s.class_name === S.selectedCls ? " active" : "";
    let dotCls = "gray";
    if (s.runtime_detected && s.runtime_enabled) dotCls = "green";
    else if (s.runtime_detected) dotCls = "yellow";
    const statusLabel = s.runtime_detected && s.runtime_enabled
      ? "▶ работает в NT"
      : s.runtime_detected
        ? "● найдена в NT (выкл.)"
        : "○ не в NT";
    html += `<div class="strat-item${active}" data-cls="${esc(s.class_name)}" onclick="onSelectStrategy('${esc(s.class_name)}')">
      <div class="name"><span class="dot ${dotCls}"></span>${esc(s.display_name || s.class_name)}</div>
      <div class="sub">${esc(s.class_name)}</div>
      <div class="sub">${esc(statusLabel)}</div>
    </div>`;
  }
  list.innerHTML = html;
}

function onSelectStrategy(cls) {
  S.selectedCls = cls;
  // Update highlight in list
  document.querySelectorAll(".strat-item").forEach(el => {
    el.classList.toggle("active", el.dataset.cls === cls);
  });
  if (!S.data) return;
  const s = (S.data.strategies || []).find(x => x.class_name === cls);
  if (s) renderParamsPanel(s);
  refreshActiveTab();
}

// ---------- params panel (right) --------------------------------------------
function renderParamsPanel(s) {
  $("params-empty").style.display = "none";
  const content = $("params-content");
  content.style.display = "block";

  const hb = (S.data || {}).heartbeat || {};
  const bridgeOnline = hb.fresh === true;
  const rt = s.runtime || {};
  const running = s.runtime_detected && s.runtime_enabled;
  const account = s.account_name || rt.account_name || "";
  const mode = s.account_mode || "";
  const isLive = mode === "live";
  const regStatus = s.registry_status || "unknown";

  // Mode badge
  const badgeCls = mode === "paper" ? "paper" : mode === "live" ? "live" : "unknown";

  let html = `
  <div class="section">
    <div class="section-title">${esc(s.display_name || s.class_name)}</div>
    <div class="kv-grid">
      <div class="kv-field"><span class="kv-label">Класс</span><span class="kv-val mono">${esc(s.class_name)}</span></div>
      <div class="kv-field"><span class="kv-label">Статус реестра</span><span class="kv-val">${esc(regStatus)}</span></div>
      <div class="kv-field"><span class="kv-label">Аккаунт NT</span><span class="kv-val">${account ? esc(account) + ' <span class="badge ' + badgeCls + '">' + esc(mode) + '</span>' : '<span class="muted">—</span>'}</span></div>
      <div class="kv-field"><span class="kv-label">Инструмент</span><span class="kv-val">${esc(s.instrument || rt.instrument || "—")}</span></div>
      <div class="kv-field"><span class="kv-label">Таймфрейм</span><span class="kv-val">${esc(s.timeframe || rt.timeframe || "—")}</span></div>
      <div class="kv-field"><span class="kv-label">Состояние NT</span><span class="kv-val">${running ? '<span style="color:#b9f5cd">▶ работает</span>' : s.runtime_detected ? '<span style="color:#ffd6a5">● найдена, выкл.</span>' : '<span class="muted">— не в NT</span>'}</span></div>
    </div>
  </div>`;

  // Locked params section (VWAP Short MNQ 5m v1)
  const locked = s.locked_params || {};
  if (Object.keys(locked).length > 0) {
    const rtParams = rt.params || {};
    html += `<div class="section">
      <div class="section-title">Заблокированные параметры VWAP Short MNQ 5m v1</div>
      <div class="small muted" style="margin-bottom:6px">Параметры жёстко зафиксированы. Bridge отклоняет команды с любым отличием.</div>
      <table class="params-table">
        <thead><tr><th>Параметр</th><th>Требуется</th><th>В NT runtime</th></tr></thead>
        <tbody>`;
    for (const [k, expected] of Object.entries(locked)) {
      const actual = rtParams[k];
      const hasRt = actual !== undefined && actual !== null;
      const matches = hasRt && String(actual) === String(expected);
      const rowCls = hasRt ? (matches ? "ok" : "mismatch") : "";
      const icon = hasRt ? (matches ? "✓" : "✗") : "";
      html += `<tr class="${rowCls}">
        <td>${esc(k)}</td>
        <td class="mono">${esc(String(expected))}</td>
        <td class="mono">${hasRt ? `<span class="match-icon">${esc(icon)}</span>${esc(String(actual))}` : '<span class="muted">нет данных</span>'}</td>
      </tr>`;
    }
    html += `</tbody></table></div>`;
  }

  // Launch controls
  html += `<div class="section"><div class="section-title">Управление</div>`;

  if (isLive) {
    html += `<div class="alert red">🔒 LIVE-аккаунт: управление запрещено. Только чтение.</div>`;
  } else if (!bridgeOnline) {
    // Bridge offline → manual flow
    html += `<div class="alert yellow">⚠ NT bridge оффлайн. Управление только вручную из NinjaTrader.</div>`;
    if (!running) {
      html += `<div class="manual-flow">
        <p><b>Как включить стратегию вручную:</b></p>
        <ol>
          <li>Откройте NinjaTrader → раздел «Стратегии»</li>
          <li>Убедитесь, что экземпляр ${esc(s.class_name)} добавлен</li>
          <li>Включите его (Enable) на аккаунте Sim/Paper</li>
          <li>Нажмите кнопку ниже для подтверждения в реестре</li>
        </ol>
        <div class="btn-row">
          ${s.registry_id ? `<button class="btn secondary" onclick="onConfirmManual('${esc(s.registry_id)}','started')">✔ Подтвердить запуск</button>` : ""}
        </div>
      </div>`;
    } else {
      html += `<div class="manual-flow">
        <p>Стратегия работает в NT. Для остановки вручную:</p>
        <ol>
          <li>Откройте NinjaTrader → раздел «Стратегии»</li>
          <li>Выключите ${esc(s.class_name)}</li>
          <li>Подтвердите ниже</li>
        </ol>
        <div class="btn-row">
          ${s.registry_id ? `<button class="btn danger" onclick="onConfirmManual('${esc(s.registry_id)}','stopped')">■ Подтвердить остановку</button>` : ""}
        </div>
      </div>`;
    }
  } else {
    // Bridge online → real command
    if (running) {
      html += `<div class="alert green">▶ Стратегия активна в NinjaTrader. Bridge онлайн.</div>
        <div class="btn-row">
          <button class="btn danger" id="btn-stop-strat" onclick="onStop('${esc(s.registry_id||"")}','${esc(s.class_name)}','${esc(account)}')">■ Остановить</button>
        </div>`;
    } else {
      html += `<div class="alert info">○ Стратегия не запущена в NT. Bridge онлайн.</div>
        <div class="alert yellow small">Экземпляр ${esc(s.class_name)} должен быть добавлен в окне «Стратегии» NinjaTrader. Bridge только включает/выключает существующий экземпляр.</div>
        <div class="btn-row">
          <button class="btn primary" id="btn-launch-strat" onclick="onLaunch('${esc(s.registry_id||"")}','${esc(s.class_name)}','${esc(account)}')">▶ Запустить</button>
        </div>`;
    }
  }

  html += `</div>`;
  content.innerHTML = html;
}

// ---------- launch / stop ---------------------------------------------------
async function onLaunch(registryId, className, accountName) {
  if (S.launching) return;
  S.launching = true;
  const btn = $("btn-launch-strat");
  if (btn) { btn.disabled = true; btn.textContent = "Отправка команды..."; }

  const s = S.data ? (S.data.strategies || []).find(x => x.class_name === className) : null;
  const instrument = s ? (s.instrument || "") : "";
  const contract = s ? (s.contract_month || (s.runtime && s.runtime.contract_month) || "") : "";

  try {
    const result = await api("/api/ops/runtime/command", {
      method: "POST",
      body: JSON.stringify({
        command: "enable_strategy",
        strategy_id: registryId || className,
        account_name: accountName,
        class_name: className,
        instrument: instrument,
        contract_month: contract,
        quantity: 1,
        reason: "SCC v2 launch",
        operator: "ui",
      }),
    });
    showMsg("params-content",
      `✓ Команда enable_strategy отправлена (ID: ${result.command_id || "—"}). Ожидайте ответа bridge.`, "green");
    setTimeout(refresh, 3000);
  } catch (e) {
    showMsg("params-content", `✗ Ошибка запуска: ${e.message}`, "red");
  } finally {
    S.launching = false;
    if (btn) { btn.disabled = false; btn.textContent = "▶ Запустить"; }
  }
}

async function onStop(registryId, className, accountName) {
  if (S.launching) return;
  S.launching = true;
  const btn = $("btn-stop-strat");
  if (btn) { btn.disabled = true; btn.textContent = "Остановка..."; }

  const s = S.data ? (S.data.strategies || []).find(x => x.class_name === className) : null;
  const instrument = s ? (s.instrument || "") : "";
  const contract = s ? (s.contract_month || (s.runtime && s.runtime.contract_month) || "") : "";

  try {
    const result = await api("/api/ops/runtime/command", {
      method: "POST",
      body: JSON.stringify({
        command: "disable_strategy",
        strategy_id: registryId || className,
        account_name: accountName,
        class_name: className,
        instrument: instrument,
        contract_month: contract,
        quantity: 1,
        reason: "SCC v2 stop",
        operator: "ui",
      }),
    });
    showMsg("params-content",
      `■ Команда disable_strategy отправлена (ID: ${result.command_id || "—"}).`, "yellow");
    setTimeout(refresh, 3000);
  } catch (e) {
    showMsg("params-content", `✗ Ошибка остановки: ${e.message}`, "red");
  } finally {
    S.launching = false;
    if (btn) { btn.disabled = false; btn.textContent = "■ Остановить"; }
  }
}

async function onConfirmManual(registryId, action) {
  const url = `/api/ops/strategies/${encodeURIComponent(registryId)}/runtime/confirm-${action}`;
  try {
    await api(url, { method: "POST", body: JSON.stringify({reason: "SCC v2 manual confirm"}) });
    showMsg("params-content", `✓ Подтверждение «${action}» принято.`, "green");
    setTimeout(refresh, 1500);
  } catch (e) {
    showMsg("params-content", `✗ Ошибка подтверждения: ${e.message}`, "red");
  }
}

function showMsg(containerId, text, cls) {
  const existing = document.querySelector(`#${containerId} .flash-msg`);
  if (existing) existing.remove();
  const div = document.createElement("div");
  div.className = `alert ${cls} flash-msg`;
  div.textContent = text;
  const container = $(containerId);
  if (container) container.prepend(div);
  setTimeout(() => { if (div.parentNode) div.remove(); }, 8000);
}

// ---------- tabs ------------------------------------------------------------
function setupTabs() {
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const pane = $("pane-" + tab);
      if (pane) pane.classList.add("active");
      S.activeTab = tab;
      loadTab(tab);
    });
  });
}

function refreshActiveTab() {
  if (S.activeTab) loadTab(S.activeTab);
}

function loadTab(tab) {
  const s = S.data ? (S.data.strategies || []).find(x => x.class_name === S.selectedCls) : null;
  const regId = s ? s.registry_id : null;
  switch (tab) {
    case "runtime":    loadTabRuntime(s); break;
    case "executions": loadTabExecutions(regId); break;
    case "orders":     loadTabOrders(regId); break;
    case "journal":    loadTabJournal(regId); break;
    case "risk":       loadTabRisk(regId); break;
    case "commands":   loadTabCommands(); break;
    case "audit":      loadTabAudit(regId); break;
  }
}

// Runtime tab
function loadTabRuntime(s) {
  const pane = $("pane-runtime");
  if (!pane) return;
  if (!s) { pane.innerHTML = `<div class="empty">Выберите стратегию.</div>`; return; }
  const rt = s.runtime || {};
  const hb = (S.data || {}).heartbeat || {};
  const fields = [
    ["Класс", rt.strategy_class || s.class_name],
    ["Аккаунт", rt.account_name || "—"],
    ["Режим аккаунта", rt.account_mode || s.account_mode || "—"],
    ["Инструмент", rt.instrument || "—"],
    ["Таймфрейм", rt.timeframe || "—"],
    ["Enabled", s.runtime_enabled ? "✓ Да" : "✗ Нет"],
    ["Состояние", rt.state || "—"],
    ["Контракт", rt.contract_month || "—"],
    ["PnL сегодня", rt.session_pnl != null ? fmtMoney(rt.session_pnl) : "—"],
    ["Heartbeat", hb.present ? (hb.fresh ? `✓ OK (${hb.age_sec}s)` : `⚠ Устарел (${hb.age_sec}s)`) : "✗ Нет"],
    ["NT версия", hb.ninja_version || "—"],
    ["Машина", hb.machine || "—"],
  ];
  let html = `<table class="data"><thead><tr><th>Поле</th><th>Значение</th></tr></thead><tbody>`;
  for (const [k, v] of fields) html += `<tr><td class="muted">${esc(k)}</td><td class="mono">${esc(String(v ?? "—"))}</td></tr>`;
  html += `</tbody></table>`;
  if (rt.params && Object.keys(rt.params).length) {
    html += `<div style="margin-top:10px;font-size:11px;color:#7a8aa3;font-weight:600;text-transform:uppercase;">Параметры NT</div>
      <table class="data" style="margin-top:4px"><thead><tr><th>Параметр</th><th>Значение</th></tr></thead><tbody>`;
    for (const [k, v] of Object.entries(rt.params)) {
      html += `<tr><td class="muted">${esc(k)}</td><td class="mono">${esc(String(v ?? ""))}</td></tr>`;
    }
    html += `</tbody></table>`;
  }
  pane.innerHTML = html;
}

// Executions / сделки
async function loadTabExecutions(regId) {
  const pane = $("pane-executions");
  if (!pane) return;
  if (!regId) { pane.innerHTML = `<div class="empty">Выберите зарегистрированную стратегию.</div>`; return; }
  pane.innerHTML = `<div class="muted">Загрузка...</div>`;
  try {
    const url = `/api/ops/runtime/executions?strategy_id=${encodeURIComponent(regId)}&limit=100`;
    const d = await api(url);
    const rows = (d.executions || []).slice().reverse();
    if (!rows.length) { pane.innerHTML = `<div class="empty">Сделок нет.</div>`; return; }
    let html = `<table class="data"><thead><tr><th>Время</th><th>Инстр.</th><th>Напр.</th><th>Кол-во</th><th>Цена</th><th>P&amp;L</th><th>Роль</th></tr></thead><tbody>`;
    for (const r of rows) {
      html += `<tr>
        <td class="mono small">${esc(r.timestamp_utc||"")}</td>
        <td>${esc(r.instrument||"")}</td>
        <td>${esc(r.side||r.direction||"")}</td>
        <td class="mono">${esc(r.quantity||"")}</td>
        <td class="mono">${esc(r.fill_price||r.price||"")}</td>
        <td class="mono">${fmtMoney(r.realized_pnl ?? r.pnl_currency)}</td>
        <td class="muted small">${esc(r.role||r.exit_reason||"")}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    pane.innerHTML = html;
  } catch (e) { pane.innerHTML = `<div class="muted">Ошибка: ${esc(e.message)}</div>`; }
}

// Orders
async function loadTabOrders(regId) {
  const pane = $("pane-orders");
  if (!pane) return;
  if (!regId) { pane.innerHTML = `<div class="empty">Выберите зарегистрированную стратегию.</div>`; return; }
  pane.innerHTML = `<div class="muted">Загрузка...</div>`;
  try {
    const url = `/api/ops/runtime/orders?strategy_id=${encodeURIComponent(regId)}&limit=100`;
    const d = await api(url);
    const rows = (d.orders || []).slice().reverse();
    if (!rows.length) { pane.innerHTML = `<div class="empty">Ордеров нет.</div>`; return; }
    let html = `<table class="data"><thead><tr><th>Время</th><th>ID</th><th>Инстр.</th><th>Напр.</th><th>Кол-во</th><th>Тип</th><th>Статус</th></tr></thead><tbody>`;
    for (const r of rows) {
      html += `<tr>
        <td class="mono small">${esc(r.timestamp_utc||"")}</td>
        <td class="mono small">${esc(r.order_id||"")}</td>
        <td>${esc(r.instrument||"")}</td>
        <td>${esc(r.side||r.direction||"")}</td>
        <td class="mono">${esc(r.quantity||"")}</td>
        <td class="muted small">${esc(r.order_type||"")}</td>
        <td class="muted small">${esc(r.status||r.state||"")}</td>
      </tr>`;
    }
    html += `</tbody></table>`;
    pane.innerHTML = html;
  } catch (e) { pane.innerHTML = `<div class="muted">Ошибка: ${esc(e.message)}</div>`; }
}

// Journal
async function loadTabJournal(regId) {
  const pane = $("pane-journal");
  if (!pane) return;
  if (!regId) { pane.innerHTML = `<div class="empty">Выберите зарегистрированную стратегию.</div>`; return; }
  pane.innerHTML = `<div class="muted">Загрузка...</div>`;
  try {
    const d = await api(`/api/ops/strategies/${encodeURIComponent(regId)}/journal`);
    const rows = d.journal || d.rows || [];
    if (!rows.length) { pane.innerHTML = `<div class="empty">Журнал пуст.</div>`; return; }
    const cols = Object.keys(rows[0]);
    let html = `<table class="data"><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>`;
    for (const r of rows) html += `<tr>${cols.map(c=>`<td class="small mono">${esc(r[c]??"")}</td>`).join("")}</tr>`;
    html += `</tbody></table>`;
    pane.innerHTML = html;
  } catch (e) { pane.innerHTML = `<div class="muted">Журнал недоступен: ${esc(e.message)}</div>`; }
}

// Risk
async function loadTabRisk(regId) {
  const pane = $("pane-risk");
  if (!pane) return;
  if (!regId) { pane.innerHTML = `<div class="empty">Выберите зарегистрированную стратегию.</div>`; return; }
  pane.innerHTML = `<div class="muted">Загрузка...</div>`;
  try {
    const d = await api(`/api/ops/strategies/${encodeURIComponent(regId)}/risk`);
    const fields = [
      ["Риск-статус", d.risk_state],
      ["Причины", (d.risk_reasons||[]).join(", ") || "—"],
      ["Сегодня adj P&L", fmtMoney(d.today_adj_pnl)],
      ["Неделя adj P&L", fmtMoney(d.weekly_adj_pnl)],
      ["Текущая просадка", fmtMoney(d.current_drawdown)],
      ["Серия убыт. дней", d.consec_losing_days ?? "—"],
    ];
    const lim = d.limits || {};
    const limFields = [
      ["Макс. убыток/день", fmtMoney(lim.max_daily_loss_usd)],
      ["Макс. убыток/неделя", fmtMoney(lim.max_weekly_loss_usd)],
      ["Трейл. просадка", fmtMoney(lim.max_trailing_dd_usd)],
      ["Серия убыт. дней (лимит)", lim.consec_losing_days ?? "—"],
      ["Макс. контрактов", lim.user_max_contracts ?? "—"],
    ];
    let html = `<table class="data"><thead><tr><th>Показатель</th><th>Значение</th></tr></thead><tbody>`;
    for (const [k, v] of fields) html += `<tr><td class="muted">${esc(k)}</td><td>${esc(String(v??"—"))}</td></tr>`;
    html += `<tr><td colspan="2" class="muted small" style="padding-top:8px;font-weight:600">Лимиты риска</td></tr>`;
    for (const [k, v] of limFields) html += `<tr><td class="muted">${esc(k)}</td><td>${esc(String(v??"—"))}</td></tr>`;
    html += `</tbody></table>`;
    pane.innerHTML = html;
  } catch (e) { pane.innerHTML = `<div class="muted">Риск недоступен: ${esc(e.message)}</div>`; }
}

// Commands
async function loadTabCommands() {
  const pane = $("pane-commands");
  if (!pane) return;
  pane.innerHTML = `<div class="muted">Загрузка...</div>`;
  try {
    const [cmds, res] = await Promise.all([
      api("/api/ops/runtime/commands?limit=50"),
      api("/api/ops/runtime/command-results?limit=50").catch(() => ({results:[]})),
    ]);
    const cs = (cmds.commands || []).slice().reverse();
    const rs = (res.results || []).slice().reverse();
    let html = `<div style="font-size:11px;font-weight:600;color:#7a8aa3;text-transform:uppercase;margin-bottom:4px">Очередь команд (до 50)</div>`;
    if (!cs.length) html += `<div class="empty">Команд нет.</div>`;
    else {
      html += `<table class="data"><thead><tr><th>Время</th><th>Команда</th><th>Класс</th><th>Аккаунт</th><th>ID</th></tr></thead><tbody>`;
      for (const c of cs)
        html += `<tr><td class="mono small">${esc(c.timestamp_utc||"")}</td><td>${esc(c.command||"")}</td><td class="mono small">${esc(c.strategy_class||"")}</td><td class="small">${esc(c.account_name||"")}</td><td class="mono small">${esc(c.command_id||"")}</td></tr>`;
      html += `</tbody></table>`;
    }
    html += `<div style="font-size:11px;font-weight:600;color:#7a8aa3;text-transform:uppercase;margin:10px 0 4px">Результаты bridge</div>`;
    if (!rs.length) html += `<div class="empty">Результатов нет (bridge ещё не отвечал).</div>`;
    else {
      html += `<table class="data"><thead><tr><th>Время</th><th>ID команды</th><th>Статус</th><th>Сообщение</th></tr></thead><tbody>`;
      for (const r of rs)
        html += `<tr><td class="mono small">${esc(r.timestamp_utc||"")}</td><td class="mono small">${esc(r.command_id||"")}</td><td>${esc(r.status||"")}</td><td class="small">${esc(r.message||r.error||"")}</td></tr>`;
      html += `</tbody></table>`;
    }
    pane.innerHTML = html;
  } catch (e) { pane.innerHTML = `<div class="muted">Ошибка: ${esc(e.message)}</div>`; }
}

// Audit log
async function loadTabAudit(regId) {
  const pane = $("pane-audit");
  if (!pane) return;
  pane.innerHTML = `<div class="muted">Загрузка...</div>`;
  try {
    const url = regId
      ? `/api/ops/audit-log?strategy_id=${encodeURIComponent(regId)}&limit=100`
      : `/api/ops/audit-log?limit=100`;
    const d = await api(url);
    const rows = (d.entries || []).slice().reverse();
    if (!rows.length) { pane.innerHTML = `<div class="empty">Аудит пуст.</div>`; return; }
    let html = `<table class="data"><thead><tr><th>Время</th><th>Действие</th><th>Strategy</th><th>Пред → Новый</th><th>Кто</th><th>Причина</th></tr></thead><tbody>`;
    for (const r of rows)
      html += `<tr><td class="mono small">${esc(r.timestamp_utc||r.time||"")}</td><td class="small">${esc(r.action||"")}</td><td class="small">${esc(r.strategy_id||"")}</td><td class="small">${esc(r.prev||"")} → ${esc(r.new||"")}</td><td class="small">${esc(r.by||"")}</td><td class="small">${esc(r.reason||"")}</td></tr>`;
    html += `</tbody></table>`;
    pane.innerHTML = html;
  } catch (e) { pane.innerHTML = `<div class="muted">Аудит недоступен: ${esc(e.message)}</div>`; }
}

// ---------- init ------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  refresh();
  setInterval(refresh, 10000);
});
