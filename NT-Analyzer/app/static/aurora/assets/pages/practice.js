/* Practice trading — wallet-first, then TopStep-like virtual desk. */
(function () {
  const UI = window.UI;
  const API = window.API;
  const SYMBOLS = ['MNQ', 'MES', 'MGC'];
  const TF = '1m';

  let state = null;
  let hasAccount = false;
  let charts = []; // { el, engine, symbol }
  let pollTimer = null;
  let lastLiveClose = {};

  function money(v) { return UI.money(Number(v || 0), { sign: true, dec: 2 }); }
  function activeSymbol() {
    return (UI.qs('#p-symbol') && UI.qs('#p-symbol').value) || 'MNQ';
  }
  function activeLayout() {
    return Number(UI.qs('#layout-seg .active')?.dataset.layout || 1) || 1;
  }

  function showOnboard(msg) {
    hasAccount = false;
    const onboard = UI.qs('#practice-onboard');
    const desk = UI.qs('#practice-desk');
    if (onboard) onboard.hidden = false;
    if (desk) desk.hidden = true;
    destroyCharts();
    if (msg) {
      const el = UI.qs('#p-onboard-msg');
      if (el) el.textContent = msg;
    }
  }

  function showDesk() {
    hasAccount = true;
    const onboard = UI.qs('#practice-onboard');
    const desk = UI.qs('#practice-desk');
    if (onboard) onboard.hidden = true;
    if (desk) desk.hidden = false;
  }

  function destroyCharts() {
    charts.forEach(c => {
      try { if (c.engine && c.engine.destroy) c.engine.destroy(); } catch (e) { /* ignore */ }
    });
    charts = [];
  }

  function syncSymbolControls(sym) {
    const s = String(sym || 'MNQ').toUpperCase();
    const sel = UI.qs('#p-symbol');
    if (sel) sel.value = s;
    UI.qsa('#p-symbol-seg button').forEach(b => {
      b.classList.toggle('active', b.dataset.symbol === s);
    });
  }

  async function fetchBars(symbol) {
    try {
      const payload = await API.http.marketBarsBatch({
        requests: [{ instrument: symbol, timeframe: TF, max_points: 180 }],
      });
      const series = (payload && (payload.series || payload.results || payload.items)) || [];
      if (Array.isArray(series) && series.length) {
        const first = series[0];
        if (Array.isArray(first?.bars)) return first.bars;
      }
      if (payload && Array.isArray(payload.bars)) return payload.bars;
      const one = await API.http.marketBars({ instrument: symbol, timeframe: TF, max_points: 180 });
      return Array.isArray(one?.bars) ? one.bars : [];
    } catch (e) {
      return [];
    }
  }

  function markFromBars(bars) {
    if (!bars || !bars.length) return 0;
    const last = bars[bars.length - 1];
    return Number(last.c || last.close || 0) || 0;
  }

  async function renderCharts(layout) {
    const host = UI.qs('#practice-charts');
    if (!host) return;
    destroyCharts();
    const n = Number(layout) || 1;
    const base = activeSymbol();
    host.className = 'practice-charts layout-' + n;
    host.innerHTML = '';
    const srcEl = UI.qs('#p-chart-src');

    for (let i = 0; i < n; i++) {
      const sym = SYMBOLS[(SYMBOLS.indexOf(base) + i) % SYMBOLS.length];
      const pane = document.createElement('div');
      pane.className = 'practice-chart-pane';
      pane.innerHTML = `<div class="practice-chart-meta"><strong>${UI.esc(sym)}</strong><span class="sub">${TF}</span></div><div class="practice-chart-host"></div>`;
      host.appendChild(pane);
      const chartHost = UI.qs('.practice-chart-host', pane);
      let engine = null;
      if (window.ChartEngine && chartHost) {
        try {
          engine = window.ChartEngine.create(chartHost, {
            instrument: sym,
            timeframe: TF,
          });
        } catch (e) { engine = null; }
      }
      const bars = await fetchBars(sym);
      const close = markFromBars(bars);
      if (close) lastLiveClose[sym] = close;
      if (engine && bars.length) {
        engine.setData(bars);
        if (srcEl) srcEl.textContent = 'рыночный поток · ' + sym;
      } else {
        const mark = ((state && state.marks) || {})[sym] || close || '—';
        if (chartHost) {
          chartHost.innerHTML = `<div class="practice-chart-fallback"><div class="tb-h1">${UI.esc(String(mark))}</div><div class="sub">${bars.length ? 'график недоступен' : 'ожидание котировок · симуляция mark'}</div></div>`;
        }
        if (srcEl) srcEl.textContent = bars.length ? 'котировки без ChartEngine' : 'симуляция · не биржа';
      }
      charts.push({ el: pane, engine, symbol: sym });
    }
  }

  function renderRisk(a) {
    const body = UI.qs('#p-risk-body');
    const risk = UI.qs('#p-risk');
    if (!a) return;
    if (risk) {
      risk.textContent = a.locked
        ? ('LOCK: ' + (a.lock_reason || ''))
        : 'лимиты активны';
    }
    if (body) {
      body.innerHTML = `
        <div class="cab-kv"><span class="k">Daily loss</span><span class="v">${money(-Math.abs(a.daily_loss_limit || 0))}</span></div>
        <div class="cab-kv"><span class="k">Max DD</span><span class="v">${money(-Math.abs(a.max_drawdown || 0))}</span></div>
        <div class="cab-kv"><span class="k">Pos limit</span><span class="v">${UI.esc(String(a.position_limit || 4))}</span></div>
        <div class="cab-kv"><span class="k">Статус</span><span class="v">${a.locked ? '<span class="badge archived">заблокирован</span>' : '<span class="badge live">можно торговать</span>'}</span></div>`;
    }
  }

  function render(doc) {
    state = doc;
    showDesk();
    const a = (doc && doc.account) || {};
    const badge = UI.qs('#practice-badge');
    if (badge) badge.textContent = doc.badge || 'Учебный счёт · не реальные деньги';
    const kpis = UI.qs('#practice-kpis');
    if (kpis) {
      kpis.innerHTML = [
        ['Equity', money(a.equity)],
        ['Balance', money(a.balance)],
        ['Day P&L', money(a.day_pnl)],
        ['Unrealized', money(a.unrealized_pnl)],
        ['Deposit', money(a.deposit)],
      ].map(([k, v]) => `<div class="kpi"><div class="kpi-label">${k}</div><div class="kpi-value">${v}</div></div>`).join('');
    }
    renderRisk(a);
    const positions = doc.positions || [];
    UI.qs('#p-positions').innerHTML = positions.length
      ? positions.map(p => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(p.side)} ${UI.esc(p.symbol)} ×${p.quantity}</div><div class="row-sub">avg ${p.avg_price} · mark ${p.mark || '—'} · uPnL ${money(p.unrealized_pnl)}</div></div></div>`).join('')
      : '<div class="muted">Нет открытых позиций</div>';
    const orders = doc.orders || [];
    UI.qs('#p-orders').innerHTML = orders.length
      ? orders.map(o => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(o.order_type)} ${UI.esc(o.side)} ${UI.esc(o.symbol)}</div><div class="row-sub">${o.limit_price || ''} · ${UI.esc(o.status)}</div></div></div>`).join('')
      : '<div class="muted">Нет рабочих ордеров</div>';
    const trades = doc.trades || [];
    UI.qs('#p-trades').innerHTML = trades.slice(0, 12).map(t =>
      `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(t.action)} ${UI.esc(t.side)} ${UI.esc(t.symbol)}</div><div class="row-sub">${money(t.pnl)} · comm ${money(t.commission)} · ${UI.esc((t.at_utc || '').slice(0, 19))}</div></div></div>`
    ).join('') || '<div class="muted">Сделок пока нет</div>';
  }

  async function refreshReport() {
    try {
      const rep = await API.http.practiceReport();
      const el = UI.qs('#p-report');
      if (el && rep) {
        el.innerHTML = `<strong>Отчёт:</strong> сделок ${rep.trade_count}, winrate ${rep.winrate}%, realized ${money(rep.realized_pnl)}, комиссии ${money(rep.commissions)}`;
      }
    } catch (e) { /* optional */ }
  }

  async function refresh() {
    try {
      const doc = await API.http.practiceAccount();
      render(doc);
      await renderCharts(activeLayout());
      await refreshReport();
    } catch (e) {
      if (e.status === 404) {
        showOnboard('');
      } else {
        UI.reportError(e);
        showOnboard(e.message || String(e));
      }
    }
  }

  async function createFromDeposit() {
    const input = UI.qs('#p-deposit');
    const msg = UI.qs('#p-onboard-msg');
    const deposit = Number(input && input.value);
    if (!Number.isFinite(deposit) || deposit < 1000 || deposit > 500000) {
      if (msg) msg.textContent = 'Введите сумму от $1 000 до $500 000.';
      return;
    }
    const btn = UI.qs('#p-create');
    if (btn) btn.disabled = true;
    if (msg) msg.textContent = 'Создаю счёт…';
    try {
      const doc = await API.http.practiceCreateAccount({
        deposit,
        commission: 2,
        daily_loss_limit: Math.max(500, Math.round(deposit * 0.02)),
        max_drawdown: Math.max(1000, Math.round(deposit * 0.04)),
        position_limit: 4,
      });
      UI.toast('Учебный счёт создан · $' + deposit.toLocaleString('en-US'));
      render(doc);
      await renderCharts(activeLayout());
      await refreshReport();
    } catch (e) {
      if (msg) msg.textContent = e.message || String(e);
      UI.reportError(e);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function tickLoop() {
    if (!hasAccount) return;
    const sym = activeSymbol();
    try {
      const bars = await fetchBars(sym);
      const close = markFromBars(bars);
      if (close) {
        lastLiveClose[sym] = close;
        charts.forEach(c => {
          if (c.symbol === sym && c.engine && bars.length) {
            try { c.engine.setData(bars); } catch (e) { /* ignore */ }
          }
        });
        const srcEl = UI.qs('#p-chart-src');
        if (srcEl) srcEl.textContent = 'рыночный поток · live · ' + sym;
      }
    } catch (e) { /* keep sim */ }
    try {
      const body = { symbol: sym };
      const doc = await API.http.practiceTick(body);
      render(doc);
    } catch (e) { /* ignore while no account */ }
  }

  UI.ready(async () => {
    // Start on onboard until account confirmed — never flash ticket first.
    showOnboard('');

    UI.qsa('#p-deposit-presets [data-deposit]').forEach(btn => {
      btn.onclick = () => {
        const v = Number(btn.dataset.deposit);
        const input = UI.qs('#p-deposit');
        if (input) input.value = String(v);
        UI.qsa('#p-deposit-presets [data-deposit]').forEach(b => {
          b.classList.toggle('primary', b === btn);
          b.classList.toggle('ghost', b !== btn);
        });
      };
    });

    const createBtn = UI.qs('#p-create');
    if (createBtn) createBtn.onclick = () => createFromDeposit();

    const resetBtn = UI.qs('#p-reset');
    if (resetBtn) {
      resetBtn.onclick = () => {
        if (!confirm('Сбросить учебный счёт? Потребуется снова внести виртуальную сумму.')) return;
        showOnboard('Введите новую сумму депозита.');
      };
    }

    UI.qsa('#layout-seg button').forEach(b => {
      b.onclick = async () => {
        UI.qsa('#layout-seg button').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        if (hasAccount) await renderCharts(b.dataset.layout);
      };
    });

    UI.qsa('#p-symbol-seg button').forEach(b => {
      b.onclick = async () => {
        syncSymbolControls(b.dataset.symbol);
        if (hasAccount) await renderCharts(activeLayout());
      };
    });
    const symSel = UI.qs('#p-symbol');
    if (symSel) {
      symSel.onchange = async () => {
        syncSymbolControls(symSel.value);
        if (hasAccount) await renderCharts(activeLayout());
      };
    }

    const buy = UI.qs('#p-buy');
    if (buy) {
      buy.onclick = async () => {
        try {
          const doc = await API.http.practiceOrder({
            symbol: UI.qs('#p-symbol').value,
            side: UI.qs('#p-side').value,
            quantity: Number(UI.qs('#p-qty').value || 1),
            order_type: UI.qs('#p-type').value,
            limit_price: Number(UI.qs('#p-limit').value || 0),
            stop_loss: Number(UI.qs('#p-sl').value || 0),
            take_profit: Number(UI.qs('#p-tp').value || 0),
          });
          UI.toast(doc.filled ? 'Исполнено' : 'Ордер выставлен');
          render(doc);
          await refreshReport();
        } catch (e) { UI.reportError(e); }
      };
    }
    const closeBtn = UI.qs('#p-close');
    if (closeBtn) {
      closeBtn.onclick = async () => {
        try {
          const doc = await API.http.practiceClose({});
          UI.toast('Позиция закрыта');
          render(doc);
          await refreshReport();
        } catch (e) { UI.reportError(e); }
      };
    }

    await refresh();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(tickLoop, 4000);
  });
})();
