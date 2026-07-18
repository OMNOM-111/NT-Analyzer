/* Practice trading — wallet-first, then TopStep-like virtual desk. */
(function () {
  const UI = window.UI;
  const API = window.API;
  const SYMBOLS = ['MNQ', 'MES', 'MGC'];
  let TF = '1m';

  let state = null;
  let hasAccount = false;
  let charts = []; // { el, engine, symbol }
  let pollTimer = null;
  let lastLiveClose = {};
  let latestSeries = {};
  let chartRequestId = 0;
  let marketPolling = false;

  function money(v) { return UI.money(Number(v || 0), { sign: true, dec: 2 }); }
  function activeSymbol() {
    return (UI.qs('#p-symbol') && UI.qs('#p-symbol').value) || 'MNQ';
  }
  function activeLayout() {
    return Number(UI.qs('#layout-seg .active')?.dataset.layout || 1) || 1;
  }

  function isGuestPreview() {
    return !!(UI && typeof UI.isGuest === 'function' && UI.isGuest());
  }

  function applyGuestPracticeLock() {
    const guest = isGuestPreview();
    document.body.classList.toggle('practice-guest-locked', guest);
    UI.qsa('#practice-onboard button, #practice-onboard input').forEach(el => {
      el.disabled = guest;
      el.setAttribute('aria-disabled', guest ? 'true' : 'false');
    });
    const message = UI.qs('#p-onboard-msg');
    if (guest && message) message.textContent = 'Войдите через Telegram, чтобы создать и сохранить свой учебный счёт.';
  }

  function currentMarket(symbol) {
    const rows = (state && state.markets && typeof state.markets === 'object') ? state.markets : {};
    const row = rows[String(symbol || '').toUpperCase()];
    return row && typeof row === 'object' ? row : null;
  }

  function marketIsTradable(symbol) {
    return !!currentMarket(symbol)?.tradable;
  }

  function updateTicketAvailability() {
    const account = (state && state.account) || {};
    const symbol = activeSymbol();
    const market = currentMarket(symbol);
    const ready = !!(market && market.tradable);
    const locked = !!account.locked;
    const positions = Array.isArray(state?.positions) ? state.positions : [];
    const reason = market?.reason || 'Нет актуальной подтверждённой котировки.';
    const guest = isGuestPreview();
    const setDisabled = (id, disabled) => {
      const el = UI.qs(id);
      if (el) el.disabled = !!disabled;
    };
    setDisabled('#p-buy', guest || !hasAccount || locked || !ready);
    setDisabled('#p-sell', guest || !hasAccount || locked || !ready);
    setDisabled('#p-close', guest || !hasAccount || locked || !ready || !positions.length);
    const note = UI.qs('#p-order-state');
    if (note) {
      note.textContent = guest
        ? 'Войдите через Telegram, чтобы открыть виртуальный счёт и отправлять учебные ордера.'
        : (!hasAccount
          ? 'Сначала создайте учебный счёт.'
          : (locked
            ? 'Торговля остановлена риск-лимитом.'
            : (ready
              ? 'Котировка подтверждена сервером. Все сделки остаются виртуальными.'
              : `Ордеры и закрытие позиции заблокированы: ${reason}`)));
      note.classList.toggle('warn', (guest || !ready) && hasAccount && !locked);
    }
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
    applyGuestPracticeLock();
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
    updateTicketAvailability();
  }

  function firstSeries(payload) {
    const series = (payload && (payload.series || payload.results || payload.items)) || [];
    if (Array.isArray(series) && series.length && series[0] && typeof series[0] === 'object') return series[0];
    return payload && typeof payload === 'object' ? payload : {};
  }

  async function fetchSeries(symbol) {
    try {
      const payload = await API.http.marketBarsBatch({
        requests: [{ instrument: symbol, timeframe: TF, limit: 600, max_points: 240 }],
      });
      const first = firstSeries(payload);
      if (Array.isArray(first.bars)) return first;
      const one = await API.http.marketBars({ instrument: symbol, timeframe: TF, limit: 600, max_points: 240 });
      return one && typeof one === 'object' ? one : { bars: [], status: 'empty' };
    } catch (e) {
      return { bars: [], status: 'error', error: e.message || String(e) };
    }
  }

  function markFromBars(bars) {
    if (!bars || !bars.length) return 0;
    const last = bars[bars.length - 1];
    return Number(last.c || last.close || 0) || 0;
  }

  function price(v) {
    const n = Number(v);
    return Number.isFinite(n) && n > 0 ? n.toLocaleString('en-US', { maximumFractionDigits: 8 }) : '—';
  }

  function ageLabel(seconds) {
    const n = Number(seconds);
    if (!Number.isFinite(n)) return 'время неизвестно';
    if (n < 90) return Math.round(n) + ' сек. назад';
    if (n < 7200) return Math.round(n / 60) + ' мин. назад';
    return Math.round(n / 3600) + ' ч. назад';
  }

  function sourceLabel(series) {
    const src = (series && series.source) || {};
    const active = src.active || src.provider || src.kind || 'источник не определён';
    const recovery = (series && series.gap_recovery) || {};
    const recovered = Number(recovery.recovered_bars || 0);
    return String(active) + (recovered ? ` · восстановлено ${recovered}` : '');
  }

  function setMarketState(series, symbol) {
    const root = UI.qs('#p-market-state');
    const srcEl = UI.qs('#p-chart-src');
    const executionMarket = !!(series && Object.prototype.hasOwnProperty.call(series, 'tradable'));
    const bars = Array.isArray(series?.bars) ? series.bars : [];
    const close = markFromBars(bars);
    const quote = series?.quote || {};
    const freshness = series?.freshness || {};
    const source = series?.source || {};
    const recovery = series?.gap_recovery || {};
    const loading = series?.status === 'loading';
    const failed = series?.status === 'error';
    const tradable = !!series?.tradable;
    const empty = executionMarket ? !tradable : !bars.length;
    const stale = !!freshness.stale || series?.status === 'external_stale' || series?.status === 'failover_stale';
    const stateName = loading ? 'loading' : (failed ? 'error' : (empty ? 'unavailable' : (stale ? 'stale' : 'ready')));
    if (root) root.dataset.state = stateName;
    const set = (id, text) => { const el = UI.qs(id); if (el) el.textContent = text; };
    set('#p-bid', price(quote.bid));
    set('#p-ask', price(quote.ask));
    set('#p-last', price(quote.last || series?.price || close));
    const provider = sourceLabel(series || {});
    const unavailable = series?.reason || 'Нет подтверждённой котировки';
    set('#p-source-state', loading ? 'Загрузка…' : (failed ? ('Ошибка: ' + (series.error || 'нет ответа')) : (empty ? unavailable : provider)));
    const timing = freshness.data_as_of_utc || source.updated_at_utc || '';
    const flags = [];
    if (quote.bid_ask_estimated) flags.push('bid/ask ориентировочные');
    if (stale) flags.push('данные неактуальны');
    if (recovery.attempted && recovery.provider_available === false) flags.push('failover недоступен');
    set('#p-source-time', [timing ? ageLabel(freshness.age_sec ?? source.age_sec) : 'timestamp отсутствует', ...flags].join(' · '));
    if (srcEl) srcEl.textContent = empty ? 'котировки не подтверждены · исполнение остановлено' : `${provider} · ${symbol} · ${TF}`;
    updateTicketAvailability();
  }

  async function renderCharts(layout) {
    const host = UI.qs('#practice-charts');
    if (!host) return;
    const requestId = ++chartRequestId;
    destroyCharts();
    const n = Number(layout) || 1;
    const base = activeSymbol();
    host.className = 'practice-charts layout-' + n;
    host.innerHTML = '<div class="practice-chart-loading">Загружаю рыночные данные…</div>';
    const srcEl = UI.qs('#p-chart-src');
    if (srcEl) srcEl.textContent = 'загрузка · ' + base + ' · ' + TF;
    setMarketState({ bars: [], status: 'loading', freshness: {} }, base);
    host.innerHTML = '';

    for (let i = 0; i < n; i++) {
      if (requestId !== chartRequestId) return;
      const sym = SYMBOLS[(SYMBOLS.indexOf(base) + i) % SYMBOLS.length];
      const pane = document.createElement('div');
      pane.className = 'practice-chart-pane';
      pane.innerHTML = `<div class="practice-chart-meta"><strong>${UI.esc(sym)}</strong><span class="sub">${UI.esc(TF)} · загрузка</span></div><div class="practice-chart-host"><div class="practice-chart-loading">Ожидание данных…</div></div>`;
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
      const series = await fetchSeries(sym);
      if (requestId !== chartRequestId) return;
      latestSeries[sym] = series;
      const bars = Array.isArray(series?.bars) ? series.bars : [];
      const close = markFromBars(bars);
      if (close) lastLiveClose[sym] = close;
      const meta = UI.qs('.practice-chart-meta .sub', pane);
      if (meta) meta.textContent = `${TF} · ${sourceLabel(series)}`;
      if (i === 0) setMarketState(series, sym);
      if (engine && bars.length) {
        engine.setData(bars);
      } else {
        const mark = ((state && state.marks) || {})[sym] || close || '—';
        if (chartHost) {
          const reason = series?.error || series?.note || (bars.length ? 'ChartEngine не построил серию' : 'Ни один источник не вернул бары');
          chartHost.innerHTML = `<div class="practice-chart-fallback"><div class="tb-h1">${UI.esc(String(mark))}</div><div class="sub">${UI.esc(reason)}</div><button class="btn ghost sm practice-pane-retry" type="button">Повторить</button></div>`;
          const retry = UI.qs('.practice-pane-retry', chartHost);
          if (retry) retry.onclick = () => renderCharts(activeLayout());
        }
      }
      charts.push({ el: pane, engine, symbol: sym, series });
    }
    // Chart history is informative.  The ticket uses only the independent
    // market state returned by /api/practice/tick, so a cached chart cannot
    // accidentally enable a fill.
    const market = currentMarket(base);
    if (market) setMarketState(market, base);
  }

  function renderRisk(a) {
    const body = UI.qs('#p-risk-body');
    const risk = UI.qs('#p-risk');
    if (!a) return;
    const status = String(a.account_status || (a.locked ? 'daily_locked' : 'active'));
    const reason = {
      daily_loss: 'дневной лимит убытка',
      max_drawdown: 'максимальная просадка',
      account_depleted: 'виртуальный баланс исчерпан',
    }[a.lock_reason] || a.lock_reason || '';
    const statusText = status === 'failed'
      ? 'счёт завершён · откройте новый'
      : (status === 'daily_locked' ? 'пауза до следующего UTC-дня' : 'лимиты активны');
    if (risk) {
      risk.textContent = a.locked ? (reason || statusText) : statusText;
    }
    if (body) {
      body.innerHTML = `
        <div class="cab-kv"><span class="k">Daily loss</span><span class="v">${money(-Math.abs(a.daily_loss_limit || 0))}</span></div>
        <div class="cab-kv"><span class="k">Max DD</span><span class="v">${money(-Math.abs(a.max_drawdown || 0))}</span></div>
        <div class="cab-kv"><span class="k">Pos limit</span><span class="v">${UI.esc(String(a.position_limit || 4))}</span></div>
        <div class="cab-kv"><span class="k">Статус</span><span class="v">${status === 'failed' ? '<span class="badge archived">счёт завершён</span>' : (a.locked ? '<span class="badge pending">дневная пауза</span>' : '<span class="badge live">можно торговать</span>')}</span></div>
        ${a.locked ? `<div class="finance-note">${UI.esc(reason || statusText)}.${a.requires_new_account ? ' Создайте новый виртуальный счёт через кнопку ниже.' : ''}</div>` : ''}`;
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
        ['Buying power · virtual', money(a.buying_power)],
        ['Day P&L', money(a.day_pnl)],
        ['Unrealized', money(a.unrealized_pnl)],
        ['Deposit', money(a.deposit)],
      ].map(([k, v]) => `<div class="kpi"><div class="kpi-label">${k}</div><div class="kpi-value">${v}</div></div>`).join('');
    }
    renderRisk(a);
    const reset = UI.qs('#p-reset');
    if (reset) reset.textContent = a.requires_new_account ? 'Открыть новый виртуальный счёт' : 'Сбросить счёт и внести заново';
    const positions = doc.positions || [];
    UI.qs('#p-positions').innerHTML = positions.length
      ? positions.map(p => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(p.side)} ${UI.esc(p.symbol)} ×${p.quantity}</div><div class="row-sub">avg ${p.avg_price} · mark ${p.mark || '—'} · uPnL ${money(p.unrealized_pnl)} · SL ${p.stop_loss || '—'} · TP ${p.take_profit || '—'}</div></div><button class="btn ghost sm p-close-one" data-position-id="${UI.esc(p.position_id || '')}" type="button">Закрыть</button></div>`).join('')
      : '<div class="muted">Нет открытых позиций</div>';
    const orders = doc.orders || [];
    UI.qs('#p-orders').innerHTML = orders.length
      ? orders.map(o => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(o.order_type)} ${UI.esc(o.side)} ${UI.esc(o.symbol)} ×${o.quantity}</div><div class="row-sub">${o.limit_price || ''} · ${UI.esc(o.status)}</div></div><button class="btn ghost sm p-cancel-order" data-order-id="${UI.esc(o.order_id || '')}" type="button">Отменить</button></div>`).join('')
      : '<div class="muted">Нет рабочих ордеров</div>';
    const trades = doc.trades || [];
    UI.qs('#p-trades').innerHTML = trades.slice(0, 12).map(t =>
      `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(t.action)} ${UI.esc(t.side)} ${UI.esc(t.symbol)}</div><div class="row-sub">${money(t.pnl)} · comm ${money(t.commission)} · ${UI.esc((t.at_utc || '').slice(0, 19))}</div></div></div>`
    ).join('') || '<div class="muted">Сделок пока нет</div>';
    UI.qsa('.p-close-one').forEach(btn => {
      btn.onclick = async () => {
        btn.disabled = true;
        try { render(await API.http.practiceClose({ position_id: btn.dataset.positionId })); await refreshReport(); }
        catch (e) { UI.reportError(e); }
        finally { btn.disabled = false; }
      };
    });
    UI.qsa('.p-cancel-order').forEach(btn => {
      btn.onclick = async () => {
        btn.disabled = true;
        try { render(await API.http.practiceCancelOrder({ order_id: btn.dataset.orderId })); UI.toast('Ордер отменён'); }
        catch (e) { UI.reportError(e); }
        finally { btn.disabled = false; }
      };
    });
    updateTicketAvailability();
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
    if (isGuestPreview()) {
      showOnboard('Войдите через Telegram, чтобы создать и сохранить свой учебный счёт.');
      return;
    }
    try {
      const doc = await API.http.practiceAccount();
      render(doc);
      await renderCharts(activeLayout());
      await refreshReport();
      await refreshMarket();
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
    if (UI.requireSignIn && UI.requireSignIn()) return;
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
      await refreshMarket();
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
      const series = await fetchSeries(sym);
      latestSeries[sym] = series;
      const bars = Array.isArray(series?.bars) ? series.bars : [];
      const close = markFromBars(bars);
      if (close) {
        lastLiveClose[sym] = close;
        charts.forEach(c => {
          if (c.symbol === sym && c.engine && bars.length) {
            try { c.engine.setData(bars); } catch (e) { /* ignore */ }
          }
        });
      }
      setMarketState(series, sym);
    } catch (e) { /* keep sim */ }
    await refreshMarket();
  }

  async function refreshMarket() {
    if (isGuestPreview() || !hasAccount || marketPolling) return null;
    marketPolling = true;
    const sym = activeSymbol();
    try {
      // The backend ignores all client prices and returns its own live/fresh
      // verdict.  It can therefore fail closed while the chart still shows
      // historical context.
      const doc = await API.http.practiceTick({ symbol: sym });
      render(doc);
      const market = currentMarket(sym);
      if (market) setMarketState(market, sym);
      return doc;
    } catch (e) {
      const market = { tradable: false, status: 'error', reason: e.message || String(e), quote: {}, source: {}, freshness: {} };
      setMarketState(market, sym);
      return null;
    } finally {
      marketPolling = false;
    }
  }

  async function submitOrder(side) {
    if (UI.requireSignIn && UI.requireSignIn()) return;
    if (!marketIsTradable(activeSymbol())) {
      updateTicketAvailability();
      UI.toast('Нет актуальной подтверждённой котировки — учебный ордер не отправлен');
      return;
    }
    const buy = UI.qs('#p-buy');
    const sell = UI.qs('#p-sell');
    if (buy) buy.disabled = true;
    if (sell) sell.disabled = true;
    const sideSelect = UI.qs('#p-side');
    if (sideSelect) sideSelect.value = side;
    try {
      const doc = await API.http.practiceOrder({
        symbol: UI.qs('#p-symbol').value,
        side,
        quantity: Number(UI.qs('#p-qty').value || 1),
        order_type: UI.qs('#p-type').value,
        limit_price: Number(UI.qs('#p-limit').value || 0),
        stop_loss: Number(UI.qs('#p-sl').value || 0),
        take_profit: Number(UI.qs('#p-tp').value || 0),
      });
      UI.toast(doc.filled ? 'Исполнено на учебном счёте' : 'Учебный ордер выставлен');
      render(doc);
      await refreshReport();
    } catch (e) { UI.reportError(e); }
    finally {
      if (buy) buy.disabled = false;
      if (sell) sell.disabled = false;
    }
  }

  UI.ready(async () => {
    // Start on onboard until account confirmed — never flash ticket first.
    showOnboard('');
    applyGuestPracticeLock();

    UI.qsa('#p-deposit-presets [data-deposit]').forEach(btn => {
      btn.onclick = () => {
        if (UI.requireSignIn && UI.requireSignIn()) return;
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
      resetBtn.onclick = async () => {
        if (UI.requireSignIn && UI.requireSignIn()) return;
        const failed = !!(state && state.account && state.account.requires_new_account);
        const prompt = failed
          ? 'Этот учебный счёт завершён. Открыть новый виртуальный счёт с новой суммой?'
          : 'Сбросить учебный счёт? Потребуется снова внести виртуальную сумму.';
        if (!confirm(prompt)) return;
        resetBtn.disabled = true;
        try {
          await API.http.practiceReset();
          state = null;
          latestSeries = {};
          showOnboard('Учебный счёт удалён. Введите новую сумму депозита.');
        } catch (e) { UI.reportError(e); }
        finally { resetBtn.disabled = false; }
      };
    }

    const retryData = UI.qs('#p-retry-data');
    if (retryData) retryData.onclick = async () => {
      await renderCharts(activeLayout());
      await refreshMarket();
    };

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

    const timeframe = UI.qs('#p-timeframe');
    if (timeframe) {
      timeframe.value = TF;
      timeframe.onchange = async () => {
        TF = timeframe.value || '1m';
        latestSeries = {};
        if (hasAccount) await renderCharts(activeLayout());
      };
    }

    const buy = UI.qs('#p-buy');
    if (buy) buy.onclick = () => submitOrder('buy');
    const sell = UI.qs('#p-sell');
    if (sell) sell.onclick = () => submitOrder('sell');
    const closeBtn = UI.qs('#p-close');
    if (closeBtn) {
      closeBtn.onclick = async () => {
        if (UI.requireSignIn && UI.requireSignIn()) return;
        if (!marketIsTradable(activeSymbol())) {
          updateTicketAvailability();
          UI.toast('Нет актуальной подтверждённой котировки — позиция не закрыта');
          return;
        }
        try {
          const doc = await API.http.practiceClose({});
          UI.toast('Позиция закрыта');
          render(doc);
          await refreshReport();
        } catch (e) { UI.reportError(e); }
      };
    }

    const orderType = UI.qs('#p-type');
    if (orderType) orderType.onchange = () => updateTicketAvailability();

    await refresh();
    if (pollTimer) clearInterval(pollTimer);
    if (!isGuestPreview()) pollTimer = setInterval(tickLoop, 4000);
  });
})();
