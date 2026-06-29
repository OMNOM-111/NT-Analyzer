/* Dashboard (Обзор) - real backend data, no inline script. */
UI.ready(renderLive);

function ovYmd(date) { return date.toISOString().slice(0, 10); }

function ovRangeParams(range, accountName) {
  const today = new Date();
  const params = { account: accountName };
  if (range === 'month' || range === 'year') return Object.assign(params, { period: range });
  const days = range === 'q' ? 90 : 180;
  return Object.assign(params, {
    period: 'custom',
    from: ovYmd(new Date(today.getTime() - days * 86400000)),
    to: ovYmd(today),
  });
}

function ovStrategySummary(data) {
  return (data && (data.strategy_summary || data.summary)) || {};
}

function ovDrawdown(data) {
  const series = AuroraDomain.tradingSeries((data && data.strategies) || []);
  return series.reduce((lowest, row) => Math.min(lowest, Number(row.drawdown || 0)), 0);
}

function ovAccountConnected(account) {
  return String(account && account.connection_status || '').toLowerCase() === 'connected';
}

function ovRhythmFallback(data, mode) {
  const daily = AuroraDomain.tradingSeries((data && data.strategies) || []);
  const grouped = {};
  daily.forEach(row => {
    const date = new Date(row.date + 'T12:00:00Z');
    let key = row.date;
    if (mode === 'weekly') {
      const monday = new Date(date);
      const day = (monday.getUTCDay() + 6) % 7;
      monday.setUTCDate(monday.getUTCDate() - day);
      key = ovYmd(monday);
    } else if (mode === 'monthly') key = row.date.slice(0, 7);
    grouped[key] = (grouped[key] || 0) + Number(row.tradingPnl || 0);
  });
  return Object.keys(grouped).sort().map(key => ({ key, label: key, pnl: Math.round(grouped[key] * 100) / 100 }));
}

async function renderLive() {
  const kpiBox = UI.qs('#kpis');
  UI.renderLoading(kpiBox, 'Загрузка счетов и метрик...');

  let accountDoc = null;
  try { accountDoc = await API.http.runtimeAccounts({ signal: UI.signal() }); } catch (_) { accountDoc = null; }
  const accounts = ((accountDoc && (accountDoc.accounts || accountDoc.online_accounts)) || [])
    .filter(account => account && !account.is_system && account.account_name);
  const preferred = UI.getSelectedAccount();
  const selectedAccount = AuroraDomain.selectAccount(accounts, preferred && preferred.account_name);
  const accountName = selectedAccount && selectedAccount.account_name;
  if (selectedAccount && (!preferred || preferred.account_name !== accountName)) UI.setSelectedAccount(accountName, false);

  const settled = await Promise.allSettled([
    API.http.performance({ period: 'month', account: accountName }, { signal: UI.signal() }),
    API.http.performance({ period: 'year', account: accountName }, { signal: UI.signal() }),
    API.http.performance({ period: 'today', account: accountName }, { signal: UI.signal() }),
    API.http.runtimeAccountHistory({ account: accountName, limit: 500 }, { signal: UI.signal() }),
    API.http.reports({ limit: 6 }, { signal: UI.signal() }),
    API.http.coverage({}, { signal: UI.signal() }),
    API.http.aiSummary({}, { signal: UI.signal() }),
    API.http.health({}, { signal: UI.signal() }),
  ]);
  const value = index => settled[index].status === 'fulfilled' ? settled[index].value : null;
  const month = value(0);
  const year = value(1);
  const today = value(2);
  const history = value(3);
  const reports = value(4);
  const coverage = value(5);
  const ai = value(6);
  const health = value(7);
  if (!month && !year && !accountDoc && !coverage && !ai && !health) {
    UI.renderError(kpiBox, settled[0].reason || new Error('backend недоступен'), renderLive);
    return;
  }

  renderKpis(kpiBox, selectedAccount, month, year, coverage, ai);
  wireEquity(month, year, accountName);
  renderToday(today);
  renderAccountOverview(accounts, selectedAccount, history);
  wireRhythm(year);
  renderTopStrategies(month);
  renderReports(reports);
  renderSystems(selectedAccount, month, coverage, ai, health);
}

function renderKpis(box, account, month, year, coverage, ai) {
  const monthSum = ovStrategySummary(month);
  const yearSum = ovStrategySummary(year);
  const drawdown = ovDrawdown(year);
  const balance = account && Number(account.net_liquidation);
  const na = '<span class="muted">нет данных</span>';
  const kpis = [
    { label: 'Баланс выбранного счёта', val: Number.isFinite(balance) ? UI.money(balance) : na, cls: 'info', icon: 'wallet', foot: account ? `${UI.esc(account.account_name)} · ${ovAccountConnected(account) ? 'подключён' : 'offline'}` : 'счёт недоступен' },
    { label: 'Торговый P&L · месяц', val: month ? UI.money(monthSum.pnl || 0, { sign: true }) : na, cls: month ? UI.pnlClass(monthSum.pnl || 0) : '', icon: 'coins', foot: month ? `${monthSum.trades || 0} зачтённых сделок` : 'источник недоступен' },
    { label: 'Торговый P&L · год', val: year ? UI.money(yearSum.pnl || 0, { sign: true }) : na, cls: year ? UI.pnlClass(yearSum.pnl || 0) : '', icon: 'spark', foot: year ? `WR ${UI.pct(yearSum.win_rate || 0)} · PF ${yearSum.profit_factor == null ? '—' : Number(yearSum.profit_factor).toFixed(2)}` : 'источник недоступен' },
    { label: 'Макс. просадка · год', val: year ? UI.money(drawdown) : na, cls: drawdown < 0 ? 'neg' : '', icon: 'chart', foot: 'только результат стратегий' },
    { label: 'Комиссия · год', val: year ? UI.money(yearSum.commission || 0) : na, cls: 'warn', icon: 'coins', foot: year ? `${yearSum.trades || 0} сделок` : 'источник недоступен' },
    { label: 'Контур портфеля / AI', val: coverage ? `${(coverage.summary && coverage.summary.ready) || 0}/${(coverage.summary && coverage.summary.total_micros) || 0}` : na, cls: 'pos', icon: 'ai', foot: ai ? `${(ai.totals && ai.totals.experiments) || 0} экспериментов · ${(ai.totals && ai.totals.running_jobs) || 0} активно` : 'AI недоступен' },
  ];
  box.innerHTML = kpis.map(kpi => `<div class="kpi ${kpi.cls}"><div class="kpi-top"><span class="kpi-label">${kpi.label}</span><span class="kpi-ic">${UI.icon(kpi.icon)}</span></div><div class="kpi-val sm">${kpi.val}</div><div class="kpi-foot">${kpi.foot}</div></div>`).join('');
}

function wireEquity(month, year, accountName) {
  const box = UI.qs('#eq-chart-box');
  const sub = UI.qs('#eq-sub');
  function draw(data) {
    const series = AuroraDomain.tradingSeries((data && data.strategies) || []);
    const values = series.map(row => row.cumulativeTradingPnl);
    if (sub) sub.textContent = data ? `${series.length} сессий · реализованный P&L стратегий, без пополнений и выводов` : 'данные недоступны';
    if (!data || !values.length) { UI.renderEmpty(box, (data && data.empty_message) || 'Нет сделок за период.'); return; }
    box.innerHTML = '<canvas id="eq-chart" style="height:300px"></canvas>';
    Chart.line(UI.qs('#eq-chart'), [{ name: 'Стратегии', color: '#6e8bff', values }], {
      area: true, money: true, height: 300, baseZero: true,
      labels: series.map(row => row.date),
    });
  }
  async function select(range, button) {
    UI.qsa('#eq-range button').forEach(item => item.classList.toggle('active', item === button));
    if (range === 'month') { draw(month); return; }
    if (range === 'year') { draw(year); return; }
    UI.renderLoading(box, 'Загрузка диапазона...');
    try { draw(await API.http.performance(ovRangeParams(range, accountName), { signal: UI.signal() })); }
    catch (error) { if (error.name !== 'AbortError') UI.renderError(box, error, () => select(range, button)); }
  }
  UI.qsa('#eq-range button').forEach(button => button.addEventListener('click', () => select(button.dataset.range, button)));
  draw(month);
}

function renderToday(today) {
  const now = new Date();
  UI.qs('#today-date').textContent = `${now.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' })}, ${now.toLocaleDateString('ru-RU', { weekday: 'long' })}`;
  const box = UI.qs('#today');
  if (!today || !today.has_trades) { UI.renderEmpty(box, (today && today.empty_message) || 'Сегодня сделок ещё нет.'); return; }
  const summary = ovStrategySummary(today);
  box.innerHTML = [
    ['P&L стратегий', UI.money(summary.pnl || 0, { sign: true }), UI.pnlClass(summary.pnl || 0)],
    ['Сделок', String(summary.trades || 0), ''],
    ['Win Rate', UI.pct(summary.win_rate || 0), 'info'],
    ['Profit Factor', summary.profit_factor == null ? '—' : Number(summary.profit_factor).toFixed(2), ''],
    ['Комиссия', UI.money(summary.commission || 0), 'muted'],
  ].map(row => `<div class="flex between"><span class="muted">${row[0]}</span><strong class="${row[2]}">${row[1]}</strong></div>`).join('');
}

function renderAccountOverview(accounts, selected, history) {
  const cards = UI.qs('#account-overview-cards');
  const box = UI.qs('#account-balance-box');
  const sub = UI.qs('#account-overview-sub');
  const note = UI.qs('#account-flow-note');
  if (sub) sub.textContent = selected ? `${selected.account_name} · баланс отдельно от результата стратегий` : 'нет доступного счёта';
  cards.innerHTML = accounts.length ? accounts.map(account => {
    const active = selected && account.account_name === selected.account_name;
    return `<article class="account-card ${active ? 'active' : ''}"><div class="flex between"><strong>${UI.esc(account.account_name)}</strong><span class="badge ${ovAccountConnected(account) ? 'live' : 'archived'}"><span class="dot"></span>${ovAccountConnected(account) ? 'online' : 'offline'}</span></div><div class="account-money">${UI.money(Number(account.net_liquidation || 0))}</div><div class="row-sub">Cash ${UI.money(Number(account.cash_value || 0))} · Realized ${UI.money(Number(account.realized_pnl || 0), { sign: true })} · ${account.is_live ? 'LIVE' : 'DEMO'}</div></article>`;
  }).join('') : '<div class="empty-state">Счета не получены от NinjaTrader.</div>';

  const ledger = ((history && history.accounts) || []).find(row => selected && row.account_name === selected.account_name);
  const snapshots = ((ledger && ledger.snapshots) || []).filter(row => row.source !== 'positions_fallback');
  if (snapshots.length > 1) {
    box.innerHTML = '<canvas id="account-balance-chart" style="height:220px"></canvas>';
    Chart.line(UI.qs('#account-balance-chart'), [
      { name: 'NetLiq', color: '#4fd1e0', values: snapshots.map(row => Number(row.net_liquidation || 0)) },
      { name: 'Cash', color: '#fcc55a', values: snapshots.map(row => Number(row.cash_value || 0)), dash: true },
    ], { money: true, height: 220, labels: snapshots.map(row => new Date(row.at_utc).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })) });
  } else {
    UI.renderEmpty(box, snapshots.length ? 'Первый снимок баланса сохранён. График появится по мере накопления истории.' : 'История баланса пока не накоплена.');
  }

  const events = (ledger && ledger.events) || [];
  const classified = events.filter(event => event.classification_status === 'classified');
  const deposits = classified.filter(event => event.kind === 'deposit').reduce((sum, event) => sum + Number(event.amount || 0), 0);
  const withdrawals = classified.filter(event => ['withdrawal', 'fee'].includes(event.kind)).reduce((sum, event) => sum + Number(event.amount || 0), 0);
  const review = events.filter(event => event.classification_status === 'needs_review').length;
  note.innerHTML = `<div><strong>Внешние движения:</strong> пополнения ${UI.money(deposits)} · выводы/комиссии ${UI.money(withdrawals)}${review ? ` · <span class="warn">${review} требуют классификации</span>` : ''}</div><div class="muted">Движения средств не включаются в торговый P&L. Источник broker cash transactions пока недоступен; ручные и импортированные операции имеют отдельный аудит.</div>`;
}

function wireRhythm(year) {
  const box = UI.qs('#rhythm-box');
  const sub = UI.qs('#rhythm-sub');
  function draw(mode) {
    const breakdowns = year && (year.strategy_breakdowns || year.breakdowns);
    const fromBackend = breakdowns && breakdowns[mode];
    let rows = Array.isArray(fromBackend) ? fromBackend : ovRhythmFallback(year, mode);
    if (mode === 'daily' && rows.length > 60) rows = rows.slice(-60);
    if (sub) sub.textContent = `${rows.length} ${mode === 'daily' ? 'дней' : mode === 'weekly' ? 'недель' : 'месяцев'} · торговый P&L после комиссии`;
    if (!rows.length) { UI.renderEmpty(box, 'Нет данных для выбранного разреза.'); return; }
    box.innerHTML = '<canvas id="rhythm-chart" style="height:300px"></canvas>';
    Chart.bars(UI.qs('#rhythm-chart'), rows.map((row, index) => ({
      label: mode === 'daily'
        ? (index % 5 === 0 || index === rows.length - 1 ? String(row.label || row.key).slice(5) : '')
        : String(row.label || row.key).replace('с ', '').slice(2),
      tooltipLabel: String(row.label || row.key || `Период ${index + 1}`),
      tooltipDetail: mode === 'daily' ? 'День · торговый P&L' : mode === 'weekly' ? 'Неделя · торговый P&L' : 'Месяц · торговый P&L',
      value: Number(row.pnl || 0),
    })), { money: true, height: 300 });
  }
  UI.qsa('#rhythm-range button').forEach(button => button.addEventListener('click', () => {
    UI.qsa('#rhythm-range button').forEach(item => item.classList.toggle('active', item === button));
    draw(button.dataset.rhythm);
  }));
  draw('daily');
}

function renderTopStrategies(month) {
  const box = UI.qs('#top-strats');
  if (!month) { UI.renderEmpty(box, 'Данные о стратегиях недоступны.'); return; }
  const top = (month.strategies || []).slice().sort((a, b) => Number(b.pnl || 0) - Number(a.pnl || 0)).slice(0, 6);
  box.innerHTML = top.length ? top.map((strategy, index) => `<a class="row" href="strategies.html?strategy=${encodeURIComponent(strategy.strategy || strategy.cell || '')}"><div class="row-main"><div class="row-title">${UI.esc(strategy.strategy || strategy.cell || '—')}</div><div class="row-sub">${UI.esc(strategy.instrument || '')} · WR ${UI.pct(strategy.win_rate || 0)} · ${strategy.trades || 0} сд.</div></div><canvas class="row-spark" data-strategy-spark="${index}"></canvas><div class="row-val ${UI.pnlClass(strategy.pnl || 0)}">${UI.money(strategy.pnl || 0, { sign: true })}</div></a>`).join('') : '<div class="empty-state">Нет торговавших стратегий за период.</div>';
  top.forEach((strategy, index) => {
    let cumulative = 0;
    const values = (strategy.daily || []).map(day => (cumulative += Number(day.pnl || 0)));
    const canvas = UI.qs(`[data-strategy-spark="${index}"]`);
    if (canvas && values.length) Chart.spark(canvas, values, { height: 30 });
  });
}

function renderReports(reports) {
  const box = UI.qs('#recent');
  const jobs = (reports && reports.jobs) || [];
  box.innerHTML = jobs.length ? jobs.slice(0, 6).map(job => {
    const metrics = job.metrics || {};
    const pnl = metrics.net_profit_after_commission != null ? metrics.net_profit_after_commission : (metrics.net_profit != null ? metrics.net_profit : (job.net_pnl != null ? job.net_pnl : job.pnl));
    const ai = job.origin && job.origin.type === 'ai_lab';
    return `<a class="row" href="backtesting.html?job=${encodeURIComponent(job.job_id || '')}"><div class="row-main"><div class="row-title">${UI.esc(job.label || job.name || job.job_id || 'отчёт')} ${ai ? '<span class="badge ai-origin-badge">AI стратегия</span>' : ''}</div><div class="row-sub">${UI.esc(job.strategy || job.class_name || '')} · ${UI.esc(job.status || '')}</div></div><div class="row-val ${pnl != null ? UI.pnlClass(pnl) : 'muted'}">${pnl != null ? UI.money(pnl, { sign: true }) : '—'}</div></a>`;
  }).join('') : '<div class="empty-state">Отчётов пока нет.</div>';
}

function renderSystems(account, month, coverage, ai, health) {
  const summary = ovStrategySummary(month);
  const ntOk = health ? !!health.ninjatrader_running : null;
  const aiRunning = ai ? Number(ai.totals && ai.totals.running_jobs || 0) : null;
  UI.qs('#systems').innerHTML = `
    <div class="panel"><div class="panel-b col"><div class="flex between"><span class="section-title">NinjaTrader</span>${ntOk == null ? '<span class="badge">нет данных</span>' : `<span class="badge ${ntOk ? 'live' : 'failed'}"><span class="dot"></span>${ntOk ? 'онлайн' : 'offline'}</span>`}</div><div class="flex between"><span class="muted">Сделок стратегий (месяц)</span><strong>${month ? summary.trades || 0 : '—'}</strong></div><div class="flex between"><span class="muted">Счёт</span><strong>${UI.esc(account && account.account_name || '—')}</strong></div></div></div>
    <div class="panel"><div class="panel-b col"><div class="flex between"><span class="section-title">AI Lab</span>${aiRunning == null ? '<span class="badge">нет данных</span>' : `<span class="badge ${aiRunning > 0 ? 'running' : 'archived'}"><span class="dot"></span>${aiRunning > 0 ? 'идёт цикл' : 'цикл не запущен'}</span>`}</div><div class="flex between"><span class="muted">Эксперименты</span><strong>${ai ? Number(ai.totals && ai.totals.experiments || 0) : '—'}</strong></div><div class="flex between"><span class="muted">Чемпионы / кандидаты</span><strong>${ai ? `${Number(ai.totals && ai.totals.champions || 0)} / ${Number(ai.totals && ai.totals.candidates || 0)}` : '—'}</strong></div></div></div>
    <div class="panel"><div class="panel-b col"><div class="flex between"><span class="section-title">Покрытие портфеля</span>${coverage ? `<span class="badge demo">${Number(coverage.summary && coverage.summary.ready || 0)}/${Number(coverage.summary && coverage.summary.total_micros || 0)} готовы</span>` : '<span class="badge">нет данных</span>'}</div>${coverage ? (coverage.instruments || []).slice(0, 4).map(item => `<div class="flex between"><span class="muted mono">${UI.esc(item.root)}</span><span class="flex gap-sm"><strong>${item.strategy_count || 0} проф.</strong>${UI.badge(item.best_status === 'ready' ? 'done' : 'pending')}</span></div>`).join('') : '<div class="empty-state">Покрытие недоступно.</div>'}</div></div>`;
}

window.addEventListener('nt-account-change', () => location.reload());
