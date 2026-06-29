/* Центр доходности — реальная интеграция с backend (/api/performance). CSP-safe. */
UI.ready(async function () {
  const state = { range: 'month', from: '', to: '', account: '', offset: 0, limit: 100, breakdown: 'daily' };
  let firstLoad = true, rows = [], currentPerf = null, currentTrades = null;
  const ymd = d => d.toISOString().slice(0, 10);

  function toQuery() {
    const today = new Date();
    let q;
    if (state.range === 'quarter') q = { period: 'custom', from: ymd(new Date(today.getTime() - 90 * 86400000)), to: ymd(today) };
    else if (state.range === 'custom') q = { period: 'custom', from: state.from, to: state.to };
    else q = { period: state.range };
    if (state.account) q.account = state.account;
    return q;
  }
  function pfText(kind, pf) {
    if (kind === 'infinite') return '∞';
    if (pf == null) return '—';
    return Number(pf).toFixed(2);
  }

  const sumBox = UI.qs('#sum');
  async function load() {
    UI.renderLoading(sumBox, 'Загрузка доходности из backend…');
    const sharedNow = UI.getSelectedAccount();
    if (firstLoad && !state.account && sharedNow) state.account = sharedNow.account_name;
    let perf, accountDoc, accountHistory, tradesDoc;
    try {
      [perf, accountDoc, accountHistory, tradesDoc] = await Promise.all([
        API.http.performance(toQuery(), { signal: UI.signal() }),
        API.http.runtimeAccounts().catch(() => ({ online_accounts: [] })),
        API.http.runtimeAccountHistory({ account: state.account, limit: 250 }).catch(() => ({ accounts: [] })),
        API.http.performanceTrades(Object.assign({}, toQuery(), { offset: state.offset, limit: state.limit }), { signal: UI.signal() }).catch(() => null),
      ]);
    }
    catch (e) { if (e.name === 'AbortError') return; UI.renderError(sumBox, e, load); return; }
    render(perf, accountDoc, accountHistory, tradesDoc);
  }

  function render(perf, accountDoc, accountHistory, tradesDoc) {
    currentPerf = perf;
    currentTrades = tradesDoc;
    // account selector — populated once from real accounts
    if (firstLoad) {
      const sel = UI.qs('#acct-filter');
      const selectableAccounts = ((accountDoc && (accountDoc.accounts || accountDoc.online_accounts)) || perf.accounts || []).filter(account => !account.is_system);
      sel.innerHTML = '<option value="">Все счета</option>' + selectableAccounts.map(a => `<option value="${UI.esc(a.account_name)}">${UI.esc(a.account_name)} · ${a.is_live ? 'LIVE' : (a.account_mode || 'paper')}${String(a.connection_status || '').toLowerCase() === 'connected' ? '' : ' · offline'}</option>`).join('');
      const shared = UI.getSelectedAccount();
      if (!state.account && shared && selectableAccounts.some(a => a.account_name === shared.account_name)) state.account = shared.account_name;
      sel.value = state.account;
      firstLoad = false;
    }
    // CSV link (real download endpoint, same filters)
    const q = toQuery(); const params = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => { if (v) params.set(k, v); });
    UI.qs('#csv-btn').href = '/api/performance/trades.csv?' + params.toString();
    UI.qs('#period-label').textContent = perf.period ? `${perf.period.label || ''} · ${perf.period.from} … ${perf.period.to} · ${perf.trade_count || 0} сделок` : '';

    const sum = perf.strategy_summary || perf.summary || {};
    const strategies = perf.strategies || [];

    // merged cumulative P&L + drawdown
    const tradeSeries = AuroraDomain.tradingSeries(strategies);
    const dates = tradeSeries.map(row => row.date);
    const eq = tradeSeries.map(row => row.cumulativeTradingPnl);
    const dd = tradeSeries.map(row => row.drawdown);
    const maxDd = dd.reduce((m, value) => Math.min(m, value), 0);

    sumBox.innerHTML = [
      { label: 'Trading P&L', val: UI.money(sum.pnl || 0, { sign: true }), cls: (sum.pnl || 0) >= 0 ? 'pos' : 'neg', icon: 'coins' },
      { label: 'Комиссия', val: UI.money(sum.commission || 0), cls: 'warn', icon: 'wallet' },
      { label: 'Win Rate', val: sum.win_rate != null ? UI.pct(sum.win_rate) : '—', cls: 'info', icon: 'target' },
      { label: 'Profit Factor', val: pfText(sum.profit_factor_kind, sum.profit_factor), cls: '', icon: 'spark' },
      { label: 'Макс. просадка', val: UI.money(maxDd), cls: 'neg', icon: 'performance' },
    ].map(k => `<div class="kpi ${k.cls}"><div class="kpi-top"><span class="kpi-label">${k.label}</span><span class="kpi-ic">${UI.icon(k.icon)}</span></div><div class="kpi-val sm">${k.val}</div></div>`).join('');

    renderAccountContext(perf, accountDoc, accountHistory, sum, maxDd);
    renderCategories(perf.categories || {});
    renderTimeBreakdowns(perf.strategy_breakdowns || perf.breakdowns || {});
    renderTrades(tradesDoc);

    UI.qs('#eqdd-sub').textContent = `${dates.length} сессий · накопленная реализованная прибыль (без стартового депозита)`;
    const eqBox = UI.qs('#eq-curve-box');
    const ddBox = UI.qs('#dd-curve-box');
    if (eq.length) {
      eqBox.innerHTML = '<canvas id="eq-curve" style="height:240px"></canvas>';
      ddBox.innerHTML = '<canvas id="dd-curve" style="height:130px"></canvas>';
      Chart.pnl(UI.qs('#eq-curve'), eq, { money: true, height: 240, labels: dates });
      Chart.line(UI.qs('#dd-curve'), [{ name: 'Просадка', color: '#ff6b81', values: dd }], { area: true, money: true, height: 130, baseZero: true });
    } else { UI.renderEmpty(eqBox, perf.empty_message || 'Нет сделок за период.'); ddBox.innerHTML = ''; }

    // per-strategy cumulative curves (top 6)
    const top = strategies.slice(0, 6);
    UI.qs('#curves-count').textContent = top.length + ' стратегий на графике';
    const series = top.map((s, i) => {
      let c = 0; const vals = (s.daily || []).map(d => { c += (d.pnl || 0); return Math.round(c * 100) / 100; });
      return { name: s.strategy, color: Chart.COLORS[i % Chart.COLORS.length], values: vals.length ? vals : [0] };
    });
    let curvesCtl = null;
    const curvesBox = UI.qs('#curves-box');
    if (top.length) {
      curvesBox.innerHTML = '<canvas id="curves" style="height:320px"></canvas>';
      curvesCtl = Chart.line(UI.qs('#curves'), series, { money: true, height: 320, baseZero: true });
      UI.qs('#curves-legend').innerHTML = top.map((s, i) => `<span class="legend-item" data-name="${UI.esc(s.strategy)}"><span class="sw" style="background:${Chart.COLORS[i % Chart.COLORS.length]}"></span>${UI.esc(s.strategy)} · ${UI.money(s.pnl || 0, { sign: true })}</span>`).join('');
      UI.qsa('#curves-legend .legend-item').forEach(li => li.onclick = () => { const on = curvesCtl.toggle(li.dataset.name); li.classList.toggle('off', !on); });
    } else { UI.qs('#curves-legend').innerHTML = ''; UI.renderEmpty(curvesBox, 'Нет данных за период.'); }

    // by-strategy bars + table
    UI.qs('#strat-count').textContent = strategies.length + ' стратегий';
    Chart.bars(UI.qs('#strat-bars'), strategies.slice(0, 14).map(s => ({ label: (s.instrument || '').split(',')[0] || s.cell || '—', tooltipLabel: s.strategy || s.name || s.cell || s.instrument || 'Стратегия', tooltipDetail: s.instrument || '', value: s.pnl || 0 })), { money: true, height: 200 });
    rows = strategies.map(s => ({ ...s, win: s.win_rate || 0, pf: s.profit_factor_kind === 'infinite' ? 1e9 : (s.profit_factor || 0) }));
    function renderStrat(list) {
      UI.qs('#strat-body').innerHTML = list.map((s, i) => `
        <tr class="clickable" data-strategy="${UI.esc(s.strategy)}"><td class="muted">${i + 1}</td><td><strong>${UI.esc(s.strategy)}</strong>${s.cell ? ` <span class="muted mono" style="font-size:10px">${UI.esc(s.cell)}</span>` : ''}</td><td class="mono muted">${UI.esc((s.instrument || '').split(',')[0] || '—')}</td>
        <td class="num">${s.trades || 0}</td><td class="num">${s.win_rate != null ? UI.pct(s.win_rate) : '—'}</td>
        <td class="num">${pfText(s.profit_factor_kind, s.profit_factor)}</td><td class="num muted">${UI.money(s.commission || 0)}</td>
        <td class="num ${UI.pnlClass(s.pnl || 0)}"><strong>${UI.money(s.pnl || 0, { sign: true })}</strong></td></tr>`).join('');
    }
    UI.sortable(UI.qs('#strat-table'), rows, renderStrat); renderStrat(rows);

    // by-instrument bars + table
    const insts = perf.instruments || [];
    UI.qs('#inst-count').textContent = insts.length + ' инструментов';
    Chart.bars(UI.qs('#inst-bars'), insts.map(s => ({ label: s.instrument, tooltipLabel: `Инструмент ${s.instrument}`, value: s.pnl || 0 })), { money: true, height: 200 });
    UI.qs('#inst-body').innerHTML = insts.map(s => `
      <tr><td class="mono"><strong>${UI.esc(s.instrument)}</strong></td><td class="num">${s.strategy_count || 0}</td><td class="num">${s.trades || 0}</td>
      <td class="num">${s.win_rate != null ? UI.pct(s.win_rate) : '—'}</td><td class="num">${pfText(s.profit_factor_kind, s.profit_factor)}</td><td class="num muted">${UI.money(s.commission || 0)}</td>
      <td class="muted" style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${UI.esc(s.best_strategy || '—')}</td>
      <td class="num ${UI.pnlClass(s.pnl || 0)}"><strong>${UI.money(s.pnl || 0, { sign: true })}</strong></td></tr>`).join('');
  }

  function renderTimeBreakdowns(breakdowns) {
    const hourly = Array.isArray(breakdowns.hourly) ? breakdowns.hourly : [];
    const weekday = Array.isArray(breakdowns.weekday) ? breakdowns.weekday : [];
    const hourlyBox = UI.qs('#hourly-box');
    const weekdayBox = UI.qs('#weekday-box');
    if (hourly.length) {
      hourlyBox.innerHTML = '<canvas id="hourly-chart" style="height:240px"></canvas>';
      Chart.bars(UI.qs('#hourly-chart'), hourly.map(row => ({ label: String(row.key).padStart(2, '0'), tooltipLabel: `${String(row.key).padStart(2, '0')}:00–${String(row.key).padStart(2, '0')}:59`, tooltipDetail: 'Торговый P&L по часу входа', value: Number(row.pnl || 0) })), { money: true, height: 240 });
    } else UI.renderEmpty(hourlyBox, 'Почасовой разрез появится после обновления backend.');
    if (weekday.length) {
      weekdayBox.innerHTML = '<canvas id="weekday-chart" style="height:240px"></canvas>';
      Chart.bars(UI.qs('#weekday-chart'), weekday.map(row => ({ label: row.label, value: Number(row.pnl || 0) })), { money: true, height: 240 });
    } else UI.renderEmpty(weekdayBox, 'Нет данных по дням недели.');
    renderBreakdownTable(breakdowns, state.breakdown);
  }

  function renderBreakdownTable(breakdowns, kind) {
    const entries = Array.isArray(breakdowns[kind]) ? breakdowns[kind] : [];
    UI.qs('#breakdown-sub').textContent = `${entries.length} строк · P&L после комиссии`;
    UI.qs('#breakdown-body').innerHTML = entries.length ? entries.slice().reverse().map(row => `<tr><td><strong>${UI.esc(row.label || row.key || '—')}</strong></td><td class="num">${row.trades || 0}</td><td class="num">${row.wins || 0} / ${row.losses || 0}</td><td class="num">${row.win_rate == null ? '—' : UI.pct(Number(row.win_rate))}</td><td class="num">${pfText(row.profit_factor_kind, row.profit_factor)}</td><td class="num muted">${UI.money(Number(row.commission || 0))}</td><td class="num ${UI.pnlClass(Number(row.pnl || 0))}"><strong>${UI.money(Number(row.pnl || 0), { sign: true })}</strong></td></tr>`).join('') : '<tr><td colspan="7"><div class="empty-state">Данных для этого разреза нет.</div></td></tr>';
  }

  function renderTrades(doc) {
    const body = UI.qs('#trades-body');
    if (!doc) {
      UI.qs('#trades-sub').textContent = 'детальный endpoint станет доступен после безопасного перезапуска backend';
      body.innerHTML = '<tr><td colspan="11"><div class="empty-state">Детальный журнал временно недоступен.</div></td></tr>';
      UI.qs('#trades-prev').disabled = true;
      UI.qs('#trades-next').disabled = true;
      return;
    }
    const trades = doc.trades || [];
    const total = Number(doc.total || 0);
    const start = total ? state.offset + 1 : 0;
    const end = Math.min(state.offset + trades.length, total);
    UI.qs('#trades-sub').textContent = `${start}–${end} из ${total} · выбранный период и счёт`;
    UI.qs('#trades-prev').disabled = state.offset <= 0;
    UI.qs('#trades-next').disabled = state.offset + state.limit >= total;
    body.innerHTML = trades.length ? trades.map((trade, index) => `<tr class="clickable" data-trade-index="${index}"><td class="muted">${UI.esc(trade.trade_no || '')}</td><td class="muted">${UI.esc(trade.date_pt || '')} ${UI.esc(trade.time_pt || '')}</td><td><strong>${UI.esc(trade.strategy_name || trade.strategy_class || trade.cell_id || 'Без привязки')}</strong><div class="row-sub mono">${UI.esc(trade.cell_id || trade.runtime_instance_id || '')}</div></td><td class="mono">${UI.esc(trade.instrument_root || trade.instrument || '')}</td><td>${UI.esc(trade.direction || '')}</td><td class="num">${UI.esc(trade.quantity || '')}</td><td class="num mono">${UI.esc(trade.entry_price || '')}</td><td class="num mono">${UI.esc(trade.exit_price || '')}</td><td class="num muted">${UI.money(Number(trade.commission || 0))}</td><td class="num ${UI.pnlClass(Number(trade.pnl || 0))}"><strong>${UI.money(Number(trade.pnl || 0), { sign: true })}</strong></td><td><span class="badge ${trade.category === 'normal' ? 'live' : 'warn'}">${UI.esc(trade.category || trade.attribution_status || '—')}</span></td></tr>`).join('') : '<tr><td colspan="11"><div class="empty-state">За выбранный период сделок нет.</div></td></tr>';
  }

  function renderAccountContext(perf, accountDoc, accountHistory, summary, maxDd) {
    const accounts = (accountDoc && (accountDoc.accounts || accountDoc.online_accounts)) || [];
    const selected = accounts.find(a => a.account_name === state.account) || (state.account ? null : accounts[0]);
    const box = UI.qs('#account-context-kpis');
    UI.qs('#account-context-sub').textContent = selected ? `${selected.account_name} · ${selected.is_live ? 'LIVE' : (selected.account_mode || 'paper')} · ${selected.connection_status || ''}` : (state.account || 'Все счета');
    const rows = [
      ['Текущий NetLiq', selected ? UI.money(selected.net_liquidation || 0) : '—', ''],
      ['Trading P&L', UI.money(summary.pnl || 0, { sign: true }), UI.pnlClass(summary.pnl || 0)],
      ['Gross P&L', UI.money(summary.gross_pnl || 0, { sign: true }), UI.pnlClass(summary.gross_pnl || 0)],
      ['Drawdown торговли', UI.money(maxDd), 'neg'],
    ];
    box.innerHTML = rows.map(row => `<div class="kpi"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm ${row[2]}">${row[1]}</div></div>`).join('');
    const histories = (accountHistory && accountHistory.accounts) || [];
    const history = histories.find(row => row.account_name === (selected && selected.account_name)) || histories[0] || { snapshots: [], events: [] };
    const events = history.events || [];
    const classified = events.filter(row => row.classification_status === 'classified');
    const amount = kind => classified.filter(row => row.kind === kind).reduce((sum, row) => sum + Number(row.amount || 0), 0);
    const pending = events.filter(row => row.classification_status === 'needs_review');
    UI.qs('#performance-cashflow-note').innerHTML = `<strong>Методика:</strong> все графики доходности рассчитаны только из закрытых сделок после комиссии. NetLiq и журнал средств являются отдельными источниками. Необъяснённые изменения не включаются в Trading P&amp;L и требуют ручной проверки в разделе «Торговля».`;
    UI.qs('#cashflow-kpis').innerHTML = [
      ['Подтверждённые пополнения', UI.money(amount('deposit'), { sign: true }), ''],
      ['Подтверждённые снятия', UI.money(amount('withdrawal'), { sign: true }), ''],
      ['Прочие движения', UI.money(amount('transfer') + amount('fee'), { sign: true }), ''],
      ['Требуют проверки', String(pending.length), pending.length ? 'warn' : ''],
    ].map(row => `<div class="kpi"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm ${row[2]}">${row[1]}</div></div>`).join('');
  }

  function renderCategories(categories) {
    const counts = categories.counts || {};
    const pnl = categories.pnl || {};
    const labels = { normal: 'Атрибутированные', rollover: 'Ролловер', account_level: 'Уровень счёта', unmatched: 'Без атрибуции' };
    const keys = Object.keys(labels);
    UI.qs('#category-kpis').innerHTML = keys.map(key => `<div class="kpi"><div class="kpi-label">${labels[key]}</div><div class="kpi-val sm ${UI.pnlClass(pnl[key] || 0)}">${UI.money(pnl[key] || 0, { sign: true })}</div><div class="kpi-foot">${counts[key] || 0} сделок</div></div>`).join('');
  }

  function openStrategyDrawer(s) {
    const trades = s.last_trades || [];
    UI.drawer(`<h3>${UI.esc(s.strategy)}</h3>`, `
      <div class="grid" style="grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
        <div class="kpi ${(s.pnl || 0) >= 0 ? 'pos' : 'neg'}"><div class="kpi-label">Чистый P&L</div><div class="kpi-val sm">${UI.money(s.pnl || 0, { sign: true })}</div></div>
        <div class="kpi"><div class="kpi-label">Сделок · Win · PF</div><div class="kpi-val sm">${s.trades || 0} · ${s.win_rate != null ? UI.pct(s.win_rate) : '—'} · ${pfText(s.profit_factor_kind, s.profit_factor)}</div></div>
      </div>
      <h4 style="margin:0 0 8px">Последние сделки</h4>
      ${trades.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Время</th><th>Инстр.</th><th class="num">Комис.</th><th class="num">P&L</th></tr></thead><tbody>${trades.map(t => `<tr><td class="muted">${UI.esc(t.date_pt || '')} ${UI.esc(t.time_pt || '')}</td><td class="mono">${UI.esc(t.instrument || '')}</td><td class="num muted">${UI.money(t.commission || 0)}</td><td class="num ${UI.pnlClass(t.pnl || 0)}">${UI.money(t.pnl || 0, { sign: true })}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty-state">Нет сделок.</div>'}`);
  }

  // wire controls
  UI.qsa('#period button').forEach(b => b.addEventListener('click', () => {
    UI.qsa('#period button').forEach(x => x.classList.remove('active')); b.classList.add('active');
    state.range = b.dataset.p; state.offset = 0; load();
  }));
  UI.qs('#acct-filter').addEventListener('change', (e) => { state.account = e.target.value; state.offset = 0; if (state.account) UI.setSelectedAccount(state.account, true); load(); });
  UI.qs('#apply-custom').addEventListener('click', () => {
    const f = UI.qs('#from-date').value, t = UI.qs('#to-date').value;
    if (!f || !t) { UI.toast('Укажите обе даты периода'); return; }
    state.range = 'custom'; state.from = f; state.to = t; state.offset = 0;
    UI.qsa('#period button').forEach(x => x.classList.remove('active'));
    load();
  });
  UI.qs('#strat-body').addEventListener('click', (e) => {
    const tr = e.target.closest('tr[data-strategy]'); if (!tr) return;
    const s = rows.find(x => x.strategy === tr.dataset.strategy); if (s) openStrategyDrawer(s);
  });

  await load();
  window.addEventListener('nt-account-change', (e) => {
    const next = e.detail && e.detail.account_name;
    if (next && next !== state.account) { state.account = next; state.offset = 0; UI.qs('#acct-filter').value = next; load(); }
  });
  UI.qsa('#breakdown-tabs button').forEach(button => button.addEventListener('click', () => {
    state.breakdown = button.dataset.breakdown;
    UI.qsa('#breakdown-tabs button').forEach(item => item.classList.toggle('active', item === button));
    renderBreakdownTable((currentPerf && (currentPerf.strategy_breakdowns || currentPerf.breakdowns)) || {}, state.breakdown);
  }));
  UI.qs('#trades-prev').addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); load(); });
  UI.qs('#trades-next').addEventListener('click', () => { state.offset += state.limit; load(); });
  UI.qs('#trades-body').addEventListener('click', event => {
    const row = event.target.closest('[data-trade-index]');
    if (!row || !currentTrades) return;
    const trade = (currentTrades.trades || [])[Number(row.dataset.tradeIndex)];
    if (!trade) return;
    UI.drawer(`<h3>Сделка ${UI.esc(trade.trade_no || trade.trade_id || '')}</h3>`, `<div class="grid cols-3"><div class="kpi"><div class="kpi-label">P&amp;L после комиссии</div><div class="kpi-val sm ${UI.pnlClass(Number(trade.pnl || 0))}">${UI.money(Number(trade.pnl || 0), { sign: true })}</div></div><div class="kpi"><div class="kpi-label">Gross</div><div class="kpi-val sm">${UI.money(Number(trade.gross_pnl || 0), { sign: true })}</div></div><div class="kpi"><div class="kpi-label">Комиссия</div><div class="kpi-val sm warn">${UI.money(Number(trade.commission || 0))}</div></div></div><div class="tbl-wrap"><table class="tbl"><tbody>${Object.entries(trade).map(([key, value]) => `<tr><td class="mono muted">${UI.esc(key)}</td><td class="mono">${UI.esc(Array.isArray(value) ? value.join(', ') : value)}</td></tr>`).join('')}</tbody></table></div>`);
  });
});
