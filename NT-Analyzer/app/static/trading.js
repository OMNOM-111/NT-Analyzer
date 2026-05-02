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
  const fmtMoney = (v) =>
    (v == null || isNaN(v)) ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(2);
  const fmtNum = (v) => (v == null || isNaN(v)) ? "—" : Number(v).toFixed(2);
  const escapeHtml = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");

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
    // Phase 6 — command pipeline live status
    activeCommand: null,    // { command_id, command, submitted_at_utc }
    cmdPollTimer: null,
    // Phase 6.7 — selection vs runtime diff for the currently-selected row
    selectionDiff: null,
    // Phase 9 — paper status
    paperJournal: null,
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
      const sel = $("sel-strategy");
      sel.innerHTML = "";
      strats.forEach(s => {
        const o = document.createElement("option");
        o.value = s.class_name || s.name || s.id || "";
        o.textContent = (s.label || s.class_name || o.value);
        sel.appendChild(o);
      });
      const def = strats.find(s => (s.class_name || s.name) === "NTAMicroVwapRiskPilot");
      if (def) sel.value = def.class_name || def.name;
      STATE.selectedStrategy = sel.value || "NTAMicroVwapRiskPilot";

      // instruments from catalog (same source as backtest page)
      const insts = (cat && cat.instruments) || [];
      STATE.instruments = insts;
      // populate group selector once
      populateGroupSelector();
      renderInstruments();
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
    } catch (e) {
      console.warn("catalog load failed:", e.message);
    }
  }

  function populateGroupSelector() {
    const sel = $("inst-group"); if (!sel) return;
    const present = new Set();
    (STATE.instruments || []).forEach(i => present.add(groupOf(instrumentName(i))));
    sel.innerHTML = '<option value="__all__">Все группы</option>';
    GROUP_DEFS.forEach(([name]) => {
      if (!present.has(name)) return;
      const o = document.createElement("option");
      o.value = name; o.textContent = name;
      sel.appendChild(o);
    });
    if (present.has("Other")) {
      const o = document.createElement("option");
      o.value = "Other"; o.textContent = "Other";
      sel.appendChild(o);
    }
  }

  function autoSelectFrontMonthIfNeeded() {
    // For B1 ShortOnly default to MNQ front-month + 5 Minute when nothing selected.
    if (STATE.selectedStrategy !== "NTAMicroVwapRiskPilot" &&
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

    // Render live accounts as read-only info cards below the selector
    const liveAccounts = STATE.accounts.filter(a => a.account_mode === "live" || a.is_live);
    const liveBox = $("live-accounts-info");
    if (liveBox) {
      if (liveAccounts.length) {
        liveBox.innerHTML = liveAccounts.map(a => {
          const cash = fmtMoney(a.cash_value);
          const net = fmtMoney(a.net_liquidation);
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
        <div class="kv"><span class="k">Cash value</span><span class="v">${escapeHtml(fmtMoney(a.cash_value))}</span></div>
        <div class="kv"><span class="k">Buying power</span><span class="v">${escapeHtml(fmtMoney(a.buying_power))}</span></div>
        <div class="kv"><span class="k">Net liquidation</span><span class="v">${escapeHtml(fmtMoney(a.net_liquidation))}</span></div>
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
    const elCur  = $("ah-currency");
    const elSub  = $("ah-sub");
    const elWarn = $("ah-warn");

    // Bridge offline = NinjaTrader closed or AddOn not running.
    // Show explicit OFFLINE state instead of stale balance.
    if (STATE.bridgeOnline === false) {
      root.className = "acct-headline mode-unknown mode-disconnected";
      elMode.textContent = "OFFLINE";
      elName.textContent = "NinjaTrader не запущен или bridge не отвечает";
      elConn.textContent = ""; elConn.className = "ah-conn";
      elBal.innerHTML = `<span class="ah-amount" style="color:#aaa;">— нет данных —</span>`;
      elCur.textContent = "";
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
      elBal.innerHTML = `<span class="ah-amount">—</span>`;
      elCur.textContent = "";
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
      elBal.innerHTML = `<span class="ah-amount">${escapeHtml(fmtMoney(main))}</span>`;
      elCur.textContent = a.currency ? String(a.currency).replace("UsDollar","USD") : "";
    } else if (hasMoney && !isConnected) {
      elBal.innerHTML = `<span class="ah-amount" style="color:#aaa;">${escapeHtml(fmtMoney(cash != null ? cash : netliq))}</span>`;
      elCur.textContent = "(stale, NT disconnected)";
    } else {
      elBal.innerHTML = `<span class="ah-amount" style="color:#aaa;">— нет данных —</span>`;
      elCur.textContent = "";
    }

    const subParts = [];
    if (cash != null) subParts.push(`<b>Cash</b> ${escapeHtml(fmtMoney(cash))}`);
    if (netliq != null) subParts.push(`<b>NetLiq</b> ${escapeHtml(fmtMoney(netliq))}`);
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

  function renderInstruments() {
    const root = $("inst-list");
    const filter = (STATE.instrumentFilter || "").trim().toLowerCase();
    let items = (STATE.instruments || []).slice();
    // group filter
    if (STATE.instrumentGroup && STATE.instrumentGroup !== "__all__") {
      items = items.filter(i => groupOf(instrumentName(i)) === STATE.instrumentGroup);
    }
    // current/expired filter
    if (STATE.instOnlyCurrent && !STATE.instShowExpired) {
      items = items.filter(isInstrumentCurrent);
    } else if (STATE.instShowExpired) {
      // include everything (no-op)
    }
    // search filter
    if (filter) {
      items = items.filter(i => {
        const sym = instrumentName(i).toLowerCase();
        const grp = groupOf(instrumentName(i)).toLowerCase();
        return sym.includes(filter) || grp.includes(filter);
      });
    }
    $("inst-count").textContent = String(items.length);
    if (!items.length) {
      root.innerHTML = '<div class="muted-empty">Нет инструментов.</div>';
      return;
    }
    // Sort: group, then front-month first inside root, then alpha.
    const front = frontMonthMap(items);
    items.sort((a, b) => {
      const ga = groupOf(instrumentName(a)), gb = groupOf(instrumentName(b));
      if (ga !== gb) return ga.localeCompare(gb);
      const ra = rootOf(instrumentName(a)), rb = rootOf(instrumentName(b));
      if (ra !== rb) return ra.localeCompare(rb);
      // Front-month first within root
      const fa = (front[ra] === (a.data_last || "")) ? 0 : 1;
      const fb = (front[rb] === (b.data_last || "")) ? 0 : 1;
      if (fa !== fb) return fa - fb;
      return instrumentName(a).localeCompare(instrumentName(b));
    });
    const html = items.map(i => {
      const sym = instrumentName(i);
      const grp = groupOf(sym);
      const r = rootOf(sym);
      const isFront = (front[r] === (i.data_last || ""));
      const sel = (sym === STATE.selectedInstrument) ? " sel" : "";
      const fm = isFront ? '<span class="frontmark" title="Front-month">•</span>' : "";
      return `<div class="inst-row${sel}" data-sym="${escapeHtml(sym)}">
        <span class="sym">${fm}${escapeHtml(sym)}</span>
        <span class="grp">${escapeHtml(grp)}</span>
      </div>`;
    }).join("");
    root.innerHTML = html;
    root.querySelectorAll(".inst-row").forEach(el => {
      el.addEventListener("click", () => {
        STATE.selectedInstrument = el.dataset.sym;
        const isel = $("sel-instrument");
        if (isel) isel.value = STATE.selectedInstrument;
        renderInstruments();
        renderInstrumentDisplay();
        refreshSelectionDiff();
        refreshLaunchControls();
      });
    });
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

  // ----- runtime strategies table ------------------------------------------
  async function loadRuntime() {
    let hb, all;
    try { hb = await api("/api/ops/runtime/heartbeat"); }
    catch (e) { hb = { present: false, fresh: false }; }
    STATE.bridgeOnline = !!(hb && hb.fresh);
    setChip("chip-backend", "Backend: онлайн", "ok");
    setChip("chip-runtime",
      "NT runtime: " + (STATE.bridgeOnline ? "онлайн" : "offline"),
      STATE.bridgeOnline ? "ok" : "bad");

    // Pass current selectors so backend can compute selection_diff per row.
    const qp = new URLSearchParams();
    if (STATE.selectedAccount)    qp.set("selected_account", STATE.selectedAccount);
    if (STATE.selectedInstrument) qp.set("selected_instrument", STATE.selectedInstrument);
    const tfEl = $("sel-timeframe");
    if (tfEl && tfEl.value)       qp.set("selected_timeframe", tfEl.value);
    const url = "/api/ops/runtime/strategies" + (qp.toString() ? "?" + qp.toString() : "");
    try { all = await api(url); }
    catch (e) { all = { strategies: [] }; }
    STATE.runtimeStrats = (all && all.strategies) || [];
    renderRuntimeTable();
    refreshSelectionDiff();
    refreshLaunchControls();
    if (STATE.selectedRuntime) renderAnalytics(STATE.selectedRuntime);
  }

  function fmtHms(iso) {
    if (!iso) return "—";
    const d = new Date(String(iso));
    if (isNaN(d.getTime())) return String(iso).slice(0, 19).replace("T", " ");
    const pad = (n) => String(n).padStart(2, "0");
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function renderRuntimeTable() {
    const body = $("rt-strats-body");
    $("rt-strats-count").textContent = String(STATE.runtimeStrats.length);
    const banner = $("rt-banner");
    banner.innerHTML = "";
    const visible = STATE.runtimeStrats;
    if (!visible.length) {
      const msg = "Нет активных стратегий в NinjaTrader. " +
                  "Добавьте и включите стратегию вручную: NinjaTrader → Strategies tab → Add → Enable. " +
                  "После этого она появится здесь и платформа начнёт мониторинг.";
      body.innerHTML = `<tr><td colspan="10" class="muted-empty">${escapeHtml(msg)}</td></tr>`;
      return;
    }
    body.innerHTML = visible.map(s => {
      const rt = s.runtime || {};
      const iid = s.runtime_instance_id || s.strategy_id || "";
      const cls = rt.strategy_class || s.strategy_id || "";
      const acct = rt.account_name || s.account_name || "—";
      const mode = s.account_mode || rt.account_mode || "—";
      const modeBadge = s.is_live ? '<span class="badge bad">live</span>' :
                        mode === "playback" ? '<span class="badge warn">playback</span>' :
                        mode === "demo"     ? '<span class="badge demo">demo</span>'   :
                        mode === "paper"    ? '<span class="badge ok">paper</span>'   :
                        '<span class="badge mut">' + escapeHtml(mode) + '</span>';
      const inst = rt.instrument || rt.contract_month || "—";
      const tfRaw = rt.timeframe;
      const tfCell = tfRaw
        ? escapeHtml(tfRaw)
        : '<span class="muted">— (bridge устарел)</span>';
      const enabled = !!s.runtime_enabled;
      const stateBadge = !s.runtime_detected ? '<span class="badge mut">offline</span>' :
                         enabled ? '<span class="badge ok">running</span>' :
                         '<span class="badge mut">stopped</span>';
      const pos = (rt.position_qty != null) ?
        ((rt.position_market_position || "") + " " + rt.position_qty) : "—";
      const pnl = rt.realized_pnl != null ? fmtMoney(rt.realized_pnl) : "—";
      // Params badge is informational only — Phase 19: mismatch does NOT block controls
      const pcheck = s.params_check || {};
      const nMis = (pcheck.mismatches || []).length;
      const paramsBadge = s.params_ok
        ? '<span class="badge ok">OK</span>'
        : `<span class="badge warn clickable params-mismatch-badge"
                  data-iid="${escapeHtml(iid)}"
                  title="Открыть Parameters diff">MISMATCH (${nMis})</span>`;
      const since = fmtHms(rt.timestamp_utc);
      const sel = (iid === STATE.selectedRuntime) ? " sel" : "";
      return `<tr class="${sel}" data-iid="${escapeHtml(iid)}">
        <td>${escapeHtml(cls)}</td>
        <td>${escapeHtml(acct)}</td>
        <td>${modeBadge}</td>
        <td>${escapeHtml(inst)}</td>
        <td>${tfCell}</td>
        <td>${stateBadge}</td>
        <td>${paramsBadge}</td>
        <td class="num">${escapeHtml(pos)}</td>
        <td class="num">${escapeHtml(pnl)}</td>
        <td><span class="muted small">${escapeHtml(since)}</span></td>
      </tr>`;
    }).join("");
    body.querySelectorAll("tr[data-iid]").forEach(tr => {
      tr.addEventListener("click", () => {
        STATE.selectedRuntime = tr.dataset.iid;
        renderRuntimeTable();
        refreshSelectionDiff();
        refreshLaunchControls();
        const view = STATE.runtimeStrats.find(s => s.runtime_instance_id === tr.dataset.iid
                                                  || s.strategy_id === tr.dataset.iid);
        if (view) renderAnalytics(view.strategy_id || tr.dataset.iid);
      });
    });
    body.querySelectorAll(".params-mismatch-badge").forEach(b => {
      b.addEventListener("click", (ev) => {
        ev.stopPropagation();
        STATE.selectedRuntime = b.dataset.iid;
        renderRuntimeTable();
        const view = STATE.runtimeStrats.find(s => s.runtime_instance_id === b.dataset.iid
                                                  || s.strategy_id === b.dataset.iid);
        if (view) renderAnalytics(view.strategy_id || b.dataset.iid);
        switchBottomTab("params-diff");
      });
    });
    // Phase 19: no "НЕ locked B1" banner — params mismatch is informational only.
    // Banner area reserved for bridge-level warnings (exporter version, offline).
    const hb = (STATE.runtimeStrats[0] || {}).heartbeat || {};
    const ev = hb.exporter_version || "";
    if (ev && ev < "1.1.0") {
      banner.innerHTML = `⚠ Bridge версия ${escapeHtml(ev)} устарела. ` +
        `Закройте NinjaTrader и запустите <b>01_INSTALL_BRIDGE.cmd</b> для обновления.`;
    }
  }

  function switchBottomTab(tabName) {
    document.querySelectorAll("#bot-tabs button").forEach(b => {
      b.classList.toggle("active", b.dataset.tab === tabName);
    });
    document.querySelectorAll(".tab-pane").forEach(p => {
      p.classList.toggle("active", p.id === ("pane-" + tabName));
    });
  }

  // ----- analytics tabs -----------------------------------------------------
  async function renderAnalytics(sid) {
    const view = STATE.runtimeStrats.find(s => s.strategy_id === sid);
    if (!view) return;
    const rt = view.runtime || {};
    const today = view.today || {};
    $("pane-overview").innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <div class="acct-info">
          <div class="kv"><span class="k">Стратегия</span><span class="v">${escapeHtml(rt.strategy_class || sid)}</span></div>
          <div class="kv"><span class="k">Счёт</span><span class="v">${escapeHtml(rt.account_name || "—")}</span></div>
          <div class="kv"><span class="k">Инструмент</span><span class="v">${escapeHtml(rt.instrument || "—")}</span></div>
          <div class="kv"><span class="k">Состояние</span><span class="v">${escapeHtml(rt.state || "—")}</span></div>
          <div class="kv"><span class="k">Позиция</span><span class="v">${escapeHtml((rt.position_market_position || "") + " " + (rt.position_qty || 0))}</span></div>
        </div>
        <div class="acct-info">
          <div class="kv"><span class="k">Сделок сегодня</span><span class="v">${escapeHtml(today.trades_today != null ? today.trades_today : (today.trades_count != null ? today.trades_count : "—"))}</span></div>
          <div class="kv"><span class="k">PnL сегодня</span><span class="v">${escapeHtml(fmtMoney(today.pnl_today != null ? today.pnl_today : today.adjusted_pnl))}</span></div>
          <div class="kv"><span class="k">Win%</span><span class="v">${escapeHtml(fmtNum(today.win_pct))}</span></div>
          <div class="kv"><span class="k">PF</span><span class="v">${escapeHtml(fmtNum(today.profit_factor))}</span></div>
          <div class="kv"><span class="k">Drawdown</span><span class="v">${escapeHtml(fmtMoney(today.drawdown))}</span></div>
        </div>
      </div>
      ${view.runtime_warnings && view.runtime_warnings.length ?
        '<div style="margin-top:8px;color:#ffd99b;font-size:11px;">⚠ ' +
        view.runtime_warnings.map(escapeHtml).join("<br>⚠ ") + "</div>" : ""}
      ${view.runtime_errors && view.runtime_errors.length ?
        '<div style="margin-top:8px;color:#ffb3b3;font-size:11px;">⛔ ' +
        view.runtime_errors.map(escapeHtml).join("<br>⛔ ") + "</div>" : ""}
    `;

    try {
      const r = await api("/api/ops/runtime/executions?strategy_id=" + encodeURIComponent(sid) + "&limit=200");
      $("pane-trades").innerHTML = renderRows(r.executions, ["timestamp_utc", "direction", "quantity", "price", "pnl"]);
    } catch (e) { $("pane-trades").innerHTML = '<div class="muted-empty">Нет данных.</div>'; }
    try {
      const r = await api("/api/ops/runtime/orders?strategy_id=" + encodeURIComponent(sid) + "&limit=200");
      $("pane-orders").innerHTML = renderRows(r.orders, ["timestamp_utc", "side", "type", "quantity", "price", "state"]);
    } catch (e) { $("pane-orders").innerHTML = '<div class="muted-empty">Нет данных.</div>'; }

    $("pane-position").innerHTML = `<pre style="font-size:11px;color:#cfe1ff;">` +
      escapeHtml(JSON.stringify({
        instrument: rt.instrument,
        market_position: rt.position_market_position,
        quantity: rt.position_qty,
        avg_price: rt.avg_price,
        unrealized_pnl: rt.unrealized_pnl,
        realized_pnl: rt.realized_pnl,
      }, null, 2)) + "</pre>";

    renderParamsDiffPane(view);

    try {
      const j = await api("/api/ops/strategies/" + encodeURIComponent(sid) + "/journal");
      $("pane-journal").innerHTML = renderRows(j && j.rows, ["date_pt", "session_status", "trades_today", "pnl_today"]);
    } catch (e) { $("pane-journal").innerHTML = '<div class="muted-empty">Журнал недоступен.</div>'; }
    try {
      const r = await api("/api/ops/runtime/errors?limit=50");
      $("pane-events").innerHTML = renderRows(r.errors, ["timestamp_utc", "kind", "message"]);
    } catch (e) { $("pane-events").innerHTML = '<div class="muted-empty">Нет событий.</div>'; }

    renderLockedParams(view);
  }

  // Phase 5.5 — Parameters diff pane
  function renderParamsDiffPane(view) {
    const pane = $("pane-params-diff");
    if (!pane) return;
    if (!view) {
      pane.innerHTML = '<div class="muted-empty">Сравнение параметров недоступно</div>';
      return;
    }
    const pcheck = view.params_check || {};
    if (!pcheck.checked) {
      pane.innerHTML = '<div class="muted-empty">Сравнение параметров недоступно</div>';
      return;
    }
    if (view.params_ok) {
      pane.innerHTML = '<div style="padding:8px;color:#b9f5cd;">' +
        '✓ Все ' + escapeHtml(pcheck.checked) + ' параметров совпадают с locked B1 ShortOnly' +
        '</div>';
      return;
    }
    const rows = (pcheck.mismatches || []).map(m => {
      const exp = (m.expected == null ? "—" : String(m.expected));
      const act = (m.actual   == null ? "(missing)" : String(m.actual));
      return `<tr class="diff">
        <td>${escapeHtml(m.key)}</td>
        <td class="expected">${escapeHtml(exp)}</td>
        <td class="actual">${escapeHtml(act)}</td>
      </tr>`;
    }).join("");
    pane.innerHTML = `<table class="params-diff-tbl">
      <thead><tr>
        <th>Параметр</th>
        <th>Ожидается (locked B1)</th>
        <th>Фактически в NT</th>
      </tr></thead>
      <tbody>${rows}</tbody>
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

  // ----- locked params + launch gating -------------------------------------
  function renderLockedParams(view) {
    const root = $("locked-params");
    const cls = view ? (view.runtime || {}).strategy_class : STATE.selectedStrategy;
    if (cls !== "NTAMicroVwapRiskPilot") {
      root.innerHTML = '<div class="muted-empty" style="padding:4px;">Locked-параметры ' +
        'определены только для NTAMicroVwapRiskPilot (B1 ShortOnly).</div>';
      return;
    }
    const expected = (view && view.params_check && view.params_check.checked > 0)
      ? B1_LOCKED_DISPLAY : B1_LOCKED_DISPLAY;
    const mism = (view && view.params_check && view.params_check.mismatches) || [];
    const mismMap = {};
    mism.forEach(m => { mismMap[m.key] = m; });
    root.innerHTML = Object.entries(expected).map(([k, v]) => {
      const m = mismMap[k];
      const cls2 = m ? " mismatch" : "";
      const actual = m ? (" (rt=" + (m.actual ?? "missing") + ")") : "";
      return `<div class="row${cls2}"><span class="k">${k}</span><span class="v">${v}${actual}</span></div>`;
    }).join("");
  }

  const B1_LOCKED_DISPLAY = {
    EnableLong: false, EnableShort: true, UseDailyBiasFilter: false,
    EmaFastPeriod: 50, EmaSlowPeriod: 200,
    TradeStartTime: 635, TradeEndTime: 700,
    MinStopTicks: 12, MaxStopTicks: 12,
    RewardRiskRatio: 3.5, RiskPerTradePct: 2.0, UserMaxContracts: 5,
    RoundTurnCommission: 1.90, SlippageTicks: 1,
    StartingCapital: 2000, IntradayOnly: true,
    ActiveMarginPerContract: 50, MaxContractsByCapital: 40,
    InstrumentStatus: "allowed", MarginSourceBroker: "NinjaTrader",
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
    else if (!["paper", "playback", "demo", "live"].includes(acct.account_mode))
      reasons.push("Аккаунт не paper/playback/demo/live (mode=" + (acct.account_mode || "?") + ")");

    const cls = STATE.selectedStrategy;
    if (!cls) reasons.push("Стратегия не выбрана");

    // Monitor+Validate: must select an existing runtime row.
    if (!STATE.selectedRuntime) {
      reasons.push("Выберите строку стратегии в таблице NinjaTrader выше");
      return { can_start: false, reasons };
    }
    const view = STATE.runtimeStrats.find(s =>
      s.runtime_instance_id === STATE.selectedRuntime || s.strategy_id === STATE.selectedRuntime);
    if (!view) {
      reasons.push("Выбранная строка не найдена — обновите таблицу");
    } else {
      if (view.registry_status === "rejected" || view.registry_status === "archived")
        reasons.push("Стратегия rejected/archived — запуск запрещён");
      // Already running → enabling again makes no sense
      if (view.runtime_detected && view.runtime_enabled)
        reasons.push("Уже активна в NinjaTrader");
    }

    return { can_start: reasons.length === 0, reasons };
  }

  // ----- Runtime validation panel ------------------------------------------
  // Renders into #sel-diff: running state + config diff + params check.
  function renderRuntimeValidation(view) {
    const box = $("sel-diff");
    if (!box) return;

    if (!STATE.bridgeOnline) {
      box.innerHTML = '<div class="rt-status-row bad">⚫ NinjaTrader bridge offline. Откройте NinjaTrader.</div>';
      return;
    }
    if (!view) {
      box.innerHTML =
        '<div class="rt-status-row muted">Стратегия не выбрана в таблице.<br>' +
        'Добавьте и включите стратегию в NinjaTrader → Strategies, ' +
        'затем выберите строку выше.</div>';
      return;
    }

    const rt = view.runtime || {};
    const detected = !!view.runtime_detected;
    const running  = !!(detected && view.runtime_enabled);
    const stateIcon  = !detected ? "⚫" : running ? "🟢" : "⚪";
    const stateLabel = !detected ? "Не обнаружена в NinjaTrader"
                     : running   ? "Активна в NinjaTrader — мониторинг активен"
                     :             "Остановлена в NinjaTrader";
    const stateCls   = !detected ? "bad" : running ? "ok" : "warn";

    // Config diff: compare right-panel selectors vs the runtime row values
    const checks = [
      { label: "Стратегия",  sel: STATE.selectedStrategy || "",
        rt: rt.strategy_class || "" },
      { label: "Аккаунт",   sel: STATE.selectedAccount  || "",
        rt: rt.account_name   || "" },
      { label: "Инструмент", sel: STATE.selectedInstrument || "",
        rt: rt.instrument || rt.contract_month || "" },
      { label: "Таймфрейм", sel: ($("sel-timeframe") || {}).value || "",
        rt: rt.timeframe || "" },
    ];
    const mismatches = checks.filter(c =>
      c.sel && c.rt && c.sel.trim().toLowerCase() !== c.rt.trim().toLowerCase());
    const allMatch = mismatches.length === 0;

    const configStatus = allMatch
      ? '<div class="rt-status-row ok" style="margin-top:4px;">✓ Конфиг совпадает с активным instance</div>'
      : '<div class="rt-status-row warn" style="margin-top:4px;">⚠ Выбранный конфиг отличается от active instance:</div>';
    const diffHtml = mismatches.map(c =>
      `<div class="rt-diff-row"><span class="k">${escapeHtml(c.label)}</span>` +
      `<span>выбрано: <b>${escapeHtml(c.sel)}</b> · в NT: <b>${escapeHtml(c.rt)}</b></span></div>`
    ).join("");

    // Params validation
    let paramsHtml = "";
    if (view.params_ok) {
      paramsHtml = '<div class="rt-status-row ok" style="margin-top:4px;">✓ B1 ShortOnly locked params: совпадают</div>';
    } else if (view.params_check && (view.params_check.checked || 0) > 0) {
      const nMis = (view.params_check.mismatches || []).length;
      paramsHtml = `<div class="rt-status-row warn" style="margin-top:4px;">` +
        `⚠ B1 params: ${nMis} расхождений — см. вкладку "Parameters diff"</div>`;
    }

    box.innerHTML =
      `<div class="rt-status-row ${escapeHtml(stateCls)}">${stateIcon} ${escapeHtml(stateLabel)}</div>` +
      configStatus + diffHtml + paramsHtml;
  }

  function refreshLaunchControls() {
    const gate = computeGate();
    const br       = $("block-reasons");
    const startBtn = $("btn-start");
    const stopBtn  = $("btn-stop");

    const view = STATE.runtimeStrats.find(s =>
      s.runtime_instance_id === STATE.selectedRuntime || s.strategy_id === STATE.selectedRuntime);
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
      ["paper", "demo", "playback", "live"].includes(acct.account_mode);
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
    // Honest live-status chip (account-agnostic mode)
    {
      const allAccts = STATE.accounts || [];
      const live = allAccts.find(a => (a.account_mode === "live") || a.is_live);
      const sel  = allAccts.find(a => a.account_name === STATE.selectedAccount);
      if (!STATE.bridgeOnline) {
        setChip("chip-live", "Live: NT offline", "bad");
      } else if (sel && (sel.account_mode === "live" || sel.is_live)) {
        setChip("chip-live", "Live: подключён (выбран)", "ok");
      } else if (live) {
        setChip("chip-live", "Live: доступен", "ok");
      } else {
        setChip("chip-live", "Live: нет", "mut");
      }
    }
  }

  // Phase 6.7 — selection vs runtime diff: now rendered by renderRuntimeValidation()
  function refreshSelectionDiff() {
    const view = STATE.runtimeStrats.find(s =>
      s.runtime_instance_id === STATE.selectedRuntime || s.strategy_id === STATE.selectedRuntime);
    STATE.selectionDiff = (view && view.selection_diff) || null;
    renderRuntimeValidation(view || null);
  }

  async function refreshTradingState() {
    await loadAccounts();
    await loadRuntime();
  }

  // ----- online command (enable / disable strategy) ------------------------
  // Monitor+Validate mode: we only enable/disable EXISTING NinjaTrader strategy instances.
  // Creating a new instance programmatically is NOT supported by NinjaTrader AddOn API.
  async function sendCommand(command) {
    const view = STATE.runtimeStrats.find(s =>
      s.runtime_instance_id === STATE.selectedRuntime || s.strategy_id === STATE.selectedRuntime);

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
    const params = (command === "enable_strategy" && targetCls === "NTAMicroVwapRiskPilot")
      ? B1_LOCKED_DISPLAY : {};
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
          loadRuntime();
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
        head = "✗ Bridge отклонил: параметры не совпадают с locked B1.";
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
      resp = await api("/api/ops/strategies/b1_shortonly/journal");
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
        '<code>POST /api/ops/strategies/b1_shortonly/journal/autofill</code> после торговой сессии.' +
        '</div>';
      return;
    }
    const m = computePaperStatus(rows);
    if (!m) { body.innerHTML = '<div class="muted-empty">Нет данных.</div>'; return; }
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

  // ----- wiring -------------------------------------------------------------
  function wire() {
    $("sel-account").addEventListener("change", e => {
      STATE.selectedAccount = e.target.value;
      renderAccountInfo();
      renderAccountHeadline(pickActiveAccount());
      loadRuntime();
    });
    $("sel-strategy").addEventListener("change", e => {
      STATE.selectedStrategy = e.target.value;
      autoSelectFrontMonthIfNeeded();
      renderInstrumentDisplay();
      refreshLaunchControls();
    });
    const isel = $("sel-instrument");
    if (isel) isel.addEventListener("change", e => {
      STATE.selectedInstrument = e.target.value;
      renderInstrumentDisplay();
      refreshSelectionDiff();
    });
    $("inst-search").addEventListener("input", e => {
      STATE.instrumentFilter = e.target.value || "";
      renderInstruments();
    });
    const grpSel = $("inst-group");
    if (grpSel) grpSel.addEventListener("change", e => {
      STATE.instrumentGroup = e.target.value || "__all__";
      renderInstruments();
    });
    const onlyCur = $("inst-only-current");
    if (onlyCur) onlyCur.addEventListener("change", e => {
      STATE.instOnlyCurrent = !!e.target.checked;
      renderInstruments();
    });
    const showExp = $("inst-show-expired");
    if (showExp) showExp.addEventListener("change", e => {
      STATE.instShowExpired = !!e.target.checked;
      renderInstruments();
    });
    const tfSel = $("sel-timeframe");
    if (tfSel) tfSel.addEventListener("change", () => {
      refreshSelectionDiff();
      loadRuntime();
    });
    $("btn-refresh").addEventListener("click", refreshTradingState);
    $("btn-status").addEventListener("click", refreshTradingState);
    $("btn-start").addEventListener("click", () => sendCommand("enable_strategy"));
    $("btn-stop").addEventListener("click", () => sendCommand("disable_strategy"));
    const obb = $("btn-open-backtest");
    if (obb) obb.addEventListener("click", () => {
      const cls = STATE.selectedStrategy || "";
      const inst = STATE.selectedInstrument || "";
      const tf = ($("sel-timeframe") || {}).value || "5 Minute";
      const qp = new URLSearchParams({
        strategy: cls, instrument: inst, timeframe: tf,
      }).toString();
      window.open("/ui/index.html?" + qp, "_blank");
    });
    document.querySelectorAll("#bot-tabs button").forEach(b => {
      b.addEventListener("click", () => switchBottomTab(b.dataset.tab));
    });
    window.addEventListener("beforeunload", () => {
      stopCmdPolling();
      if (STATE.timer) clearInterval(STATE.timer);
    });
  }

  async function init() {
    wire();
    await loadCatalog();
    await loadAccounts();
    await loadRuntime();
    await loadPaperStatus();
    refreshLaunchControls();
    STATE.timer = setInterval(refreshTradingState, 5000);
  }

  document.addEventListener("DOMContentLoaded", init);
})();
