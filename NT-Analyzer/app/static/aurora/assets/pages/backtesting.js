/* Бэктестирование — реальная интеграция. CSP-safe (external, no inline handlers).
   Instruments /api/ops/runtime/instruments · strategies/templates /api/catalog · reports /api/reports ·
   submit POST /api/jobs · favorites /api/report-favorites · job detail /api/jobs/{id}[/trades]. */
UI.ready(async function () {
  let roots = [], strategies = [], profiles = [], coverage = null, catalog = null, basket = [], repOffset = 0, repFilter = 'all', repSort = 'mtime', repDir = 'desc', repHierarchy = 'report';
  const reportSummaries = new Map();
  const reportSparkLoaded = new Set();
  const REP_PAGE = 50;
  const ST_BADGE = { done: 'done', failed: 'failed', cancelled: 'archived', running: 'running', pending: 'trial', cancel_requested: 'running' };
  // What the operator is told while a cancel is in flight. NinjaTrader
  // cannot be interrupted mid-run, so this is a normal state to be in for
  // a while -- not an error, and not a finished cancellation.
  const ST_TEXT = { cancel_requested: 'Отмена… NinjaTrader завершает текущую фазу' };
  const stText = s => ST_TEXT[s] || s;
  const statusBadge = (st) => `<span class="badge ${ST_BADGE[st] || ''}">${UI.esc(st || '')}</span>`;
  const fmtDate = (iso) => { try { return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso || ''; } };
  const tfLabel = (tf) => tf ? `${tf.value || tf.bars_period_value || ''} ${(tf.bars_period_type === 'Minute' ? 'мин' : (tf.bars_period_type || ''))}` : '';
  const pf = (v) => v == null ? '—' : Number(v).toFixed(2);
  const periodLabel = period => period && (period.from_utc || period.to_utc) ? `${String(period.from_utc || '').slice(0, 10)} … ${String(period.to_utc || '').slice(0, 10)}` : '—';
  function rootGroup(row) {
    if (row.group || row.category || row.asset_class) return row.group || row.category || row.asset_class;
    const root = String(row.root || '').toUpperCase();
    if (['ES','MES','NQ','MNQ','YM','MYM','RTY','M2K'].includes(root)) return 'Индексы';
    if (['GC','MGC','SI','SIL','HG'].includes(root)) return 'Металлы';
    if (['CL','MCL','NG','RB','HO'].includes(root)) return 'Энергия';
    if (/^6[A-Z]$/.test(root) || ['M6A','M6B','M6E','M6J'].includes(root)) return 'Валюты';
    if (['ZB','ZN','ZF','ZT','UB'].includes(root)) return 'Ставки';
    return 'Сырьё и прочее';
  }

  // ---------- instruments ----------
  function renderInst(q) {
    q = (q || '').toLowerCase();
    const group = UI.qs('#inst-group').value;
    const list = roots.filter(r => (group === 'all' || rootGroup(r) === group) && (!q || (r.root + ' ' + rootGroup(r) + ' ' + ((r.front_month && r.front_month.instrument) || '')).toLowerCase().includes(q)));
    UI.qs('#inst-count').textContent = list.length + ' инстр.';
    UI.qs('#inst-list').innerHTML = list.map(r => {
      const fm = r.front_month || {};
      return `<div class="inst-row ${basket.includes(r.root) ? 'on' : ''}" data-sym="${UI.esc(r.root)}" data-inst="${UI.esc(fm.instrument || r.root)}">
        <span class="inst-sym">${UI.esc(r.root)}</span>
        <div class="row-main"><div class="row-title" style="font-size:12px">${UI.esc(fm.instrument || r.root)}</div>
          <div class="row-sub">${UI.esc(rootGroup(r))} · ${UI.esc(fm.exchange || '')} · шаг ${fm.tick_size != null ? fm.tick_size : '—'} = <b style="color:var(--tx-2)">$${fm.tick_value != null ? fm.tick_value : '—'}</b>/тик · ${(r.contracts || []).length} контр.</div></div>
        ${basket.includes(r.root) ? `<span class="pos">${UI.icon('check')}</span>` : `<span class="faint">${UI.icon('plus')}</span>`}
      </div>`;
    }).join('') || '<div class="empty-state">Ничего не найдено.</div>';
    UI.qsa('#inst-list .inst-row').forEach(el => el.onclick = () => {
      const s = el.dataset.sym;
      UI.qs('#f-instrument').value = el.dataset.inst;
      if (basket.includes(s)) basket = basket.filter(x => x !== s); else basket.push(s);
      renderInst(UI.qs('#inst-search').value); renderBasket();
    });
  }
  function renderBasket() {
    UI.qs('#basket').innerHTML = basket.length ? basket.map(s => `<span class="chip-tag">${UI.esc(s)}<span class="x" data-s="${UI.esc(s)}">${UI.icon('close')}</span></span>`).join('') : '<span class="muted">Выберите инструменты слева (для пакетного прогона)</span>';
    UI.qsa('#basket .x').forEach(x => x.onclick = () => { basket = basket.filter(v => v !== x.dataset.s); renderInst(UI.qs('#inst-search').value); renderBasket(); });
  }
  function openEcon() {
    UI.drawer(
      '<div class="tb-title"><span class="tb-kicker">Из каталога NinjaTrader</span><span class="tb-h1">Экономика инструментов</span></div>',
      `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Рут</th><th>Контракт</th><th>Биржа</th><th class="num">Шаг</th><th class="num">$/тик</th><th class="num">$/пункт</th><th class="num">Контрактов</th></tr></thead>
      <tbody>${roots.map(r => { const fm = r.front_month || {}; return `<tr><td class="mono"><strong>${UI.esc(r.root)}</strong></td><td class="muted">${UI.esc(fm.instrument || '')}</td><td class="muted">${UI.esc(fm.exchange || '')}</td><td class="num mono">${fm.tick_size != null ? fm.tick_size : '—'}</td><td class="num"><strong class="pos">$${fm.tick_value != null ? fm.tick_value : '—'}</strong></td><td class="num mono">$${fm.point_value != null ? fm.point_value : '—'}</td><td class="num muted">${(r.contracts || []).length}</td></tr>`; }).join('')}</tbody></table></div>`
    );
  }

  function renderProfiles() {
    const box = UI.qs('#profile-list');
    box.innerHTML = profiles.length ? profiles.map(p => `<div class="row" data-profile="${UI.esc(p.profile_id || '')}"><div class="row-main"><div class="row-title">${UI.esc(p.name || p.strategy_class || '')}</div><div class="row-sub">${UI.esc(p.cell_id || '')} · ${UI.esc(p.instrument || '')} · ${UI.esc(p.timeframe || '')}</div></div><div class="row-val"><span class="badge ${p.status === 'ready' ? 'live' : 'trial'}">${UI.esc(p.status || '')}</span></div></div>`).join('') : '<div class="empty-state">Профилей нет.</div>';
    UI.qsa('#profile-list .row[data-profile]').forEach(row => row.onclick = () => {
      const p = profiles.find(item => item.profile_id === row.dataset.profile); if (!p) return;
      const cls = p.strategy_class || p.deploy_strategy_class || p.class_name || '';
      UI.drawer(`<h3>${UI.esc(p.name || cls || 'Профиль')}</h3>`, `<div class="flex wrap gap-sm"><span class="badge ${p.status === 'ready' ? 'live' : 'trial'}">${UI.esc(p.status || '—')}</span><span class="tag">${UI.esc(p.cell_id || 'без ячейки')}</span><span class="tag">${UI.esc(p.instrument || 'инструмент не указан')}</span></div><div class="grid cols-3"><div class="kpi"><div class="kpi-label">Стратегия</div><div class="kpi-val sm">${UI.esc(cls || '—')}</div></div><div class="kpi"><div class="kpi-label">Таймфрейм</div><div class="kpi-val sm">${UI.esc(String(p.timeframe || '—'))}</div></div><div class="kpi"><div class="kpi-label">Решение</div><div class="kpi-val sm">${UI.esc(p.decision || p.status || '—')}</div></div></div>${p.notes || p.description ? `<div class="finance-note">${UI.esc(p.notes || p.description)}</div>` : ''}<details><summary>Параметры профиля</summary><pre class="logbox">${UI.esc(JSON.stringify(p.parameters || p.strategy_parameters || {}, null, 2))}</pre></details><button class="btn primary" id="apply-profile">Применить к новому бэктесту</button>`);
      UI.qs('#apply-profile').onclick = () => {
      const cls = p.strategy_class || p.deploy_strategy_class || p.class_name || '';
      const option = Array.from(UI.qs('#f-strategy').options).find(o => o.value === cls); if (option) UI.qs('#f-strategy').value = cls;
      if (p.instrument) UI.qs('#f-instrument').value = p.instrument;
      renderStrategyParams(p.parameters || p.strategy_parameters || {});
      UI.toast(`Профиль ${p.name || cls} применён`);
      UI.closeDrawer();
      };
    });
  }

  function renderCoverage() {
    const rows = (coverage && coverage.instruments) || [];
    UI.qs('#coverage-list').innerHTML = rows.length ? rows.map(row => `<div class="row" data-root="${UI.esc(row.root || '')}"><div class="row-main"><div class="row-title">${UI.esc(row.root || '')}</div><div class="row-sub">${row.strategy_count || 0} профилей · ${UI.esc(row.best_status || 'нет готовой')}</div></div><div class="row-val">${row.ready_count || (row.best_status === 'ready' ? 1 : 0)}</div></div>`).join('') : '<div class="empty-state">Coverage недоступно.</div>';
    UI.qsa('#coverage-list .row[data-root]').forEach(row => row.onclick = () => {
      const data = rows.find(item => item.root === row.dataset.root) || {};
      const item = roots.find(root => root.root === row.dataset.root);
      const matching = profiles.filter(profile => String(profile.instrument || profile.root || '').startsWith(row.dataset.root));
      UI.drawer(`<h3>Покрытие ${UI.esc(row.dataset.root)}</h3>`, `<div class="grid cols-3"><div class="kpi"><div class="kpi-label">Профили</div><div class="kpi-val">${data.strategy_count || matching.length || 0}</div></div><div class="kpi pos"><div class="kpi-label">Готово</div><div class="kpi-val">${data.ready_count || 0}</div></div><div class="kpi"><div class="kpi-label">Лучший статус</div><div class="kpi-val sm">${UI.esc(data.best_status || 'нет')}</div></div></div><div class="list">${matching.length ? matching.map(profile => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(profile.name || profile.strategy_class || '')}</div><div class="row-sub">${UI.esc(profile.cell_id || '')}</div></div><span class="badge ${profile.status === 'ready' ? 'live' : 'trial'}">${UI.esc(profile.status || '')}</span></div>`).join('') : '<div class="empty-state">Профили для этого root не найдены.</div>'}</div>${item ? '<button class="btn primary" id="apply-coverage">Выбрать инструмент</button>' : ''}`);
      const apply = UI.qs('#apply-coverage'); if (apply) apply.onclick = () => { UI.qs('#f-instrument').value = (item.front_month && item.front_month.instrument) || item.root; UI.toast(`${item.root} выбран`); UI.closeDrawer(); };
    });
  }

  function renderStrategyParams(values) {
    const cls = UI.qs('#f-strategy').value;
    const meta = ((catalog && catalog.strategies) || []).find(item => item.class_name === cls) || {};
    const params = meta.parameters || [];
    const supplied = values || {};
    UI.qs('#strategy-params').innerHTML = params.length ? params.map(param => {
      const value = supplied[param.name] != null ? supplied[param.name] : param.default;
      if (param.kind === 'bool') return `<label class="field flex gap-sm" style="align-items:center"><input type="checkbox" data-param="${UI.esc(param.name)}" data-kind="bool" ${value ? 'checked' : ''}> ${UI.esc(param.label || param.name)}</label>`;
      if (Array.isArray(param.enum_values) && param.enum_values.length) return `<div class="field"><label>${UI.esc(param.label || param.name)}</label><select data-param="${UI.esc(param.name)}" data-kind="string">${param.enum_values.map(option => `<option ${String(option) === String(value) ? 'selected' : ''}>${UI.esc(option)}</option>`).join('')}</select></div>`;
      const type = param.kind === 'int' || param.kind === 'float' ? 'number' : 'text'; const step = param.kind === 'float' ? 'any' : '1';
      return `<div class="field"><label>${UI.esc(param.label || param.name)}</label><input type="${type}" step="${step}" ${param.min != null ? `min="${param.min}"` : ''} ${param.max != null ? `max="${param.max}"` : ''} value="${UI.esc(value == null ? '' : value)}" data-param="${UI.esc(param.name)}" data-kind="${UI.esc(param.kind || 'string')}"></div>`;
    }).join('') : '<span class="muted">У стратегии нет экспортированных параметров.</span>';
  }

  function renderStrategyCatalog() {
    const entries = ((catalog && catalog.strategies) || []).filter(item => item && item.class_name);
    strategies = entries.map(item => String(item.class_name));
    UI.qs('#f-strategy').innerHTML = entries.map(item => {
      const className = String(item.class_name);
      const displayName = String(item.display_name || className);
      const label = displayName && displayName !== className
        ? `${displayName} · ${className}` : className;
      return `<option value="${UI.esc(className)}">${UI.esc(label)}</option>`;
    }).join('') || '<option value="">нет стратегий</option>';

    const note = UI.qs('#f-strategy-source-note');
    if (!note) return;
    const device = catalog && catalog.device_catalog;
    if (device) {
      const count = entries.length;
      const sourceText = device.fresh
        ? `Каталог VMNINJA актуален · ${count} стратегий`
        : device.present
          ? `Каталог VMNINJA: последний snapshot (${device.state || 'stale'}) · ${count} стратегий`
          : `Каталог VMNINJA недоступен (${device.state || 'missing'}); device-стратегии не подтверждены`;
      note.textContent = sourceText;
      note.hidden = false;
      return;
    }
    if (!catalog) {
      note.textContent = 'Каталог стратегий недоступен; список не подменён резервными данными.';
      note.hidden = false;
      return;
    }
    note.hidden = true;
  }

  // The bridge applies commission only through a NinjaTrader template; a
  // numeric commission is rejected outright, which is why the request always
  // carries 0. That makes the template the single thing standing between a
  // backtest and honest costs, so a run must never fall back to "no
  // commission" quietly -- the metrics would look better than the strategy is.
  function defaultCommissionTemplate() {
    return (catalog && catalog.execution_defaults
            && catalog.execution_defaults.commission_template) || 'None';
  }

  function commissionTemplateOrDefault(name) {
    const wanted = String(name || '').trim();
    const supported = ((catalog && catalog.commission_templates) || [])
      .filter(item => item && item.supported !== false && item.name)
      .map(item => item.name);
    if (wanted && (wanted === 'None' || supported.indexOf(wanted) >= 0)) return wanted;
    return defaultCommissionTemplate();
  }

  function renderCommissionTemplates() {
    const select = UI.qs('#f-commission-template');
    if (!select) return;
    const templates = ((catalog && catalog.commission_templates) || [])
      .filter(item => item && item.supported !== false && item.name);
    if (!templates.some(item => item.name === 'None')) {
      templates.push({ name: 'None', display: 'Без комиссии · 0 (не реальные издержки)', supported: true });
    }
    select.innerHTML = templates.map(item => {
      const label = item.name === 'None'
        ? 'Без комиссии · 0 (не реальные издержки)'
        : (item.display || item.name);
      return `<option value="${UI.esc(item.name)}">${UI.esc(label)}</option>`;
    }).join('');
    const preferred = defaultCommissionTemplate();
    select.value = templates.some(item => item.name === preferred) ? preferred : 'None';
    const warn = UI.qs('#f-commission-zero-note');
    const sync = () => { if (warn) warn.hidden = select.value !== 'None'; };
    select.onchange = sync;
    sync();
  }

  function collectStrategyParams() {
    const values = {};
    UI.qsa('#strategy-params [data-param]').forEach(input => {
      if (input.dataset.kind === 'bool') values[input.dataset.param] = input.checked;
      else if (input.dataset.kind === 'int') values[input.dataset.param] = parseInt(input.value, 10);
      else if (input.dataset.kind === 'float') values[input.dataset.param] = parseFloat(input.value);
      else values[input.dataset.param] = input.value;
    });
    return values;
  }

  // ---------- reports ----------
  function reportQueryParams() {
    return {
      filter: repFilter, limit: REP_PAGE, offset: repOffset, sort: repSort, dir: repDir,
      q: UI.qs('#rep-search').value.trim(), report_no: UI.qs('#rep-no').value.trim(),
      instrument: UI.qs('#rep-instrument').value.trim(), frequency: UI.qs('#rep-frequency').value,
      min_trades: UI.qs('#rep-min-trades').value, min_win: UI.qs('#rep-min-win').value,
      min_pf: UI.qs('#rep-min-pf').value, min_confidence: UI.qs('#rep-min-confidence').value,
      pnl_sign: UI.qs('#rep-pnl-sign').value, from: UI.qs('#rep-from').value, to: UI.qs('#rep-to').value,
      analysis_limit: UI.qs('#rep-analysis-limit').value,
    };
  }
  async function loadReports(reset) {
    if (reset) { repOffset = 0; reportSparkLoaded.clear(); reportSummaries.clear(); UI.qs('#rep-body').innerHTML = '<tr><td colspan="12"><div class="state-loading"><span class="spinner"></span>Загрузка отчётов…</div></td></tr>'; }
    let doc;
    try { doc = await API.http.reports(reportQueryParams(), { signal: UI.signal() }); }
    catch (e) { if (e.name !== 'AbortError') UI.qs('#rep-body').innerHTML = `<tr><td colspan="12" class="muted">Ошибка: ${UI.esc(e.message)}</td></tr>`; return; }
    const c = doc.counts || {};
    UI.qs('#rep-counts').textContent = `${doc.total || 0} найдено${doc.scope_limited ? ` в последних ${doc.analysis_limit} из ${doc.archive_total}` : ''} · ${c.done || 0} готово · ${c.running || 0} в работе · ${c.failed || 0} ошибок`;
    if (reset) UI.qs('#rep-body').innerHTML = '';
    const pageCount = (doc.jobs || []).length + (doc.batches || []).length;
    appendReports(doc.jobs || [], doc.total || 0, repOffset + pageCount);
    repOffset += pageCount;
  }
  async function loadReportSparks(jobs) {
    jobs.filter(row => row.status === 'done' && row.job_id).forEach(row => {
      const canvas = Array.from(UI.qsa('[data-report-spark]')).find(item => item.dataset.reportSpark === row.job_id);
      if (!canvas) return;
      const metrics = row.metrics || row;
      const net = Number(metrics.net_profit_after_commission != null ? metrics.net_profit_after_commission : (metrics.net_profit || 0));
      Chart.spark(canvas, [0, net], { height: 30 });
      canvas.title = `Итог отчёта: ${UI.money(net, { sign: true })}`;
    });
    const candidates = jobs.filter(row => row.status === 'done' && row.job_id).slice(0, 12);
    await Promise.allSettled(candidates.map(async row => {
      if (reportSparkLoaded.has(row.job_id)) return;
      const canvas = Array.from(UI.qsa('[data-report-spark]')).find(item => item.dataset.reportSpark === row.job_id);
      if (!canvas) return;
      reportSparkLoaded.add(row.job_id);
      try {
        const doc = await API.http.jobTrades(row.job_id, { limit: 200 }, { signal: UI.signal() });
        const trades = doc.trades || doc.rows || doc.items || [];
        if (!canvas.isConnected || !trades.length) return;
        let cumulative = 0;
        const values = [0, ...trades.map(trade => (cumulative += Number(AuroraDomain.tradePnl(trade) || 0)))];
        Chart.spark(canvas, values, { height: 30 });
        canvas.title = `Кривая результата: ${UI.money(cumulative, { sign: true })} · ${trades.length} сделок`;
      } catch (error) {
        if (error.name !== 'AbortError') canvas.title = 'Мини-график недоступен';
      }
    }));
  }
  function appendReports(jobs, total, nextOffset) {
    const body = UI.qs('#rep-body');
    const moreRow = body.querySelector('.load-more-row'); if (moreRow) moreRow.remove();
    if (!jobs.length && !body.children.length) { body.innerHTML = '<tr><td colspan="12"><div class="empty-state">Отчётов по выбранным условиям нет.</div></td></tr>'; return; }
    jobs.forEach(r => reportSummaries.set(r.job_id, r));
    const displayJobs = jobs.slice();
    if (repHierarchy === 'strategy') displayJobs.sort((a, b) => String(a.class_name || '').localeCompare(String(b.class_name || ''), 'ru'));
    if (repHierarchy === 'day') displayJobs.sort((a, b) => String(b.created_at_utc || '').slice(0, 10).localeCompare(String(a.created_at_utc || '').slice(0, 10)));
    let lastGroup = null;
    body.insertAdjacentHTML('beforeend', displayJobs.map(r => {
      const m = r.metrics || r;
      const net = m.net_profit_after_commission != null ? m.net_profit_after_commission : (m.net_profit != null ? m.net_profit : null);
      const profitFactor = m.profit_factor_after_commission != null ? m.profit_factor_after_commission : m.profit_factor;
      const done = r.status === 'done';
      const assessment = r.assessment || AuroraDomain.assessReport(m.trade_count, r.period, m);
      const frequency = r.frequency || assessment.frequency;
      const confidence = r.confidence || assessment.confidence;
      const group = repHierarchy === 'strategy' ? (r.class_name || 'Без стратегии') : repHierarchy === 'day' ? String(r.created_at_utc || '').slice(0, 10) || 'Без даты' : null;
      const groupRow = group && group !== lastGroup ? `<tr class="report-group-row"><td colspan="12"><span class="section-title">${UI.esc(group)}</span></td></tr>` : '';
      lastGroup = group;
      const frequencyTitle = `${frequency.explanation || ''} Риск: ${frequency.risk_expectation || '—'}; ожидаемая прибыль: ${frequency.profit_expectation || '—'}.`;
      const confidenceTitle = (confidence.reasons || []).join(' · ');
      return `${groupRow}<tr class="clickable" data-id="${UI.esc(r.job_id)}">
        <td><button class="btn icon ghost fav-star" data-fav="${UI.esc(r.job_id)}" data-on="${r.favorite ? '1' : '0'}" style="color:${r.favorite ? 'var(--warn)' : 'var(--tx-4)'}">${UI.icon('star')}</button></td>
        <td class="mono muted">${r.report_no || ''}</td>
        <td class="muted">${fmtDate(r.created_at_utc)}</td>
        <td><div class="report-strategy-cell"><div><div class="cell-strat"><strong>${UI.esc(r.class_name || '')}</strong>${r.origin && r.origin.type === 'ai_lab' ? '<span class="badge ai-origin-badge">AI</span>' : ''}</div><div class="row-sub">${UI.esc(r.instrument || '')} · ${tfLabel(r.timeframe)}</div></div>${done ? `<canvas class="row-spark" data-report-spark="${UI.esc(r.job_id)}" aria-label="Мини-график результата бэктеста"></canvas>` : ''}</div></td>
        <td>${statusBadge(r.status)}</td>
        <td class="muted mono">${periodLabel(r.period)}</td>
        <td title="${UI.esc(frequencyTitle)}"><span class="badge ${frequency.key === 'normal' ? 'live' : frequency.key === 'unknown' ? 'archived' : 'trial'}">${UI.esc(frequency.label || '—')}</span><div class="row-sub">${frequency.trades_per_week == null ? '—' : Number(frequency.trades_per_week).toFixed(1)}/нед</div></td>
        <td class="num ${done ? AuroraDomain.metricTone('trades', m.trade_count, r.period) : 'muted'}">${done ? (m.trade_count != null ? m.trade_count : '—') : '—'}</td>
        <td class="num ${done ? AuroraDomain.metricTone('win', m.winning_pct) : 'muted'}">${done && m.winning_pct != null ? UI.pct(m.winning_pct) : '—'}</td>
        <td class="num ${done ? AuroraDomain.metricTone('pf', profitFactor) : 'muted'}">${done ? pf(profitFactor) : '—'}</td>
        <td class="num ${AuroraDomain.metricTone('confidence', confidence.score)}" title="${UI.esc(confidenceTitle)}"><strong>${confidence.score != null ? confidence.score + '%' : '—'}</strong><div class="row-sub">${UI.esc(confidence.label || '')}</div></td>
        <td class="num"><strong class="${done && net != null ? UI.pnlClass(net) : 'muted'}">${done && net != null ? UI.money(net, { sign: true }) : '—'}</strong></td></tr>`;
    }).join(''));
    if (nextOffset < total) body.insertAdjacentHTML('beforeend', `<tr class="load-more-row"><td colspan="12" style="text-align:center"><button class="btn sm" id="rep-more">Загрузить ещё (${total - nextOffset})</button></td></tr>`);
    UI.qsa('#rep-body tr.clickable').forEach(tr => tr.onclick = (e) => { if (e.target.closest('.fav-star')) return; openReport(tr.dataset.id); });
    UI.qsa('#rep-body .fav-star').forEach(b => b.onclick = async (e) => {
      e.stopPropagation();
      const id = b.dataset.fav, on = b.dataset.on === '1';
      try { if (on) await API.http.unfavoriteReport('job', id); else await API.http.favoriteReport({ kind: 'job', id }); UI.toast(on ? 'Убрано из избранного' : 'В избранном'); loadReports(true); }
      catch (er) { UI.reportError(er); }
    });
    const more = UI.qs('#rep-more'); if (more) more.onclick = () => loadReports(false);
    void loadReportSparks(jobs);
  }

  // ---------- detail drawer ----------
  function metricCards(m, period) {
    const assessment = AuroraDomain.assessReport(m.trade_count, period, m);
    const profitFactor = m.profit_factor_after_commission != null ? m.profit_factor_after_commission : m.profit_factor;
    const cards = [
      ['Чистый P&L', m.net_profit_after_commission != null ? UI.money(m.net_profit_after_commission, { sign: true }) : (m.net_profit != null ? UI.money(m.net_profit, { sign: true }) : '—'), UI.pnlClass(m.net_profit_after_commission != null ? m.net_profit_after_commission : (m.net_profit || 0))],
      ['Profit Factor', pf(profitFactor), AuroraDomain.metricTone('pf', profitFactor)],
      ['Win Rate', m.winning_pct != null ? UI.pct(m.winning_pct) : '—', AuroraDomain.metricTone('win', m.winning_pct)],
      ['Сделок', m.trade_count != null ? m.trade_count : '—', AuroraDomain.metricTone('trades', m.trade_count, period)],
      ['Частота', assessment.frequency.label, assessment.frequency.key === 'normal' ? 'pos' : 'warn'],
      ['Личное доверие', assessment.confidence.score + '%', AuroraDomain.metricTone('confidence', assessment.confidence.score)],
      ['Макс. просадка', m.max_drawdown != null ? UI.money(m.max_drawdown) : '—', 'neg'],
      ['Комиссия', m.commission_total_adjusted != null ? UI.money(m.commission_total_adjusted) : (m.commission != null ? UI.money(m.commission) : '—'), 'muted'],
      ['Валовая прибыль', m.gross_profit != null ? UI.money(m.gross_profit, { sign: true }) : '—', ''],
      ['Валовой убыток', m.gross_loss != null ? UI.money(m.gross_loss, { sign: true }) : '—', 'neg'],
    ];
    return cards.map(c => `<div class="kpi ${c[2]}"><div class="kpi-label">${c[0]}</div><div class="kpi-val sm ${c[2]}">${c[1]}</div></div>`).join('');
  }
  const tradePnl = AuroraDomain.tradePnl;
  const tradeTime = AuroraDomain.tradeTime;

  async function openReport(jobId) {
    UI.drawer(`<h3 style="margin:0">Отчёт ${UI.esc(jobId)}</h3>`, '<div class="state-loading"><span class="spinner"></span>Загрузка отчёта…</div>');
    const body = UI.qs('.drawer-b');
    let detail;
    try { detail = await API.http.job(jobId); } catch (e) { UI.renderError(body, e, () => openReport(jobId)); return; }
    let trades = [];
    try { const t = await API.http.jobTrades(jobId, { limit: 500 }); trades = t.trades || t.rows || t.items || []; } catch (e) { /* none */ }
    let summary = reportSummaries.get(jobId) || {};
    if (!Object.keys(summary).length) {
      try {
        const favDoc = await API.http.reportFavorites();
        const isFavorite = (favDoc.favorites || []).some(item => item.kind === 'job' && item.id === jobId);
        summary = { favorite: isFavorite };
      } catch (error) { /* favorite state remains unknown */ }
    }
    const model = AuroraDomain.normalizeJobDetail(detail, summary);
    const { execution, risk, metrics: m, instrument, timeframe, period, origin,
      className, status, favorite, parameters: params, warnings } = model;
    // The device runs the whole backtest but sends a bounded number of trade
    // rows. Showing "37" beside metrics computed over 269 trades would read as
    // a disagreement in the data rather than as what it is: a sample.
    const transfer = (detail && detail.trade_transfer)
      || (detail && detail.result && detail.result.trade_transfer)
      || (model && model.trade_transfer) || null;
    const truncated = !!(transfer && (transfer.trades_truncated
      || (transfer.trades_total || 0) > (transfer.trades_transferred || 0)));
    const tradesCountLabel = truncated
      ? `Показано ${trades.length} из ${transfer.trades_total} сделок`
      : String(trades.length);
    const linkedProfile = profiles.find(profile => [profile.strategy_class, profile.deploy_strategy_class, profile.class_name, profile.name].includes(className)) || {};
    const strategyMeta = ((catalog && catalog.strategies) || []).find(item => item.class_name === className) || {};
    const description = linkedProfile.description || linkedProfile.notes || linkedProfile.hypothesis || strategyMeta.description || strategyMeta.summary || '';
    const rules = Array.isArray(linkedProfile.rules) ? linkedProfile.rules : Array.isArray(strategyMeta.rules) ? strategyMeta.rules : [];
    const assessment = AuroraDomain.assessReport(m.trade_count, period, m);
    let cum = 0; const eq = trades.map(t => { cum += tradePnl(t); return Math.round(cum * 100) / 100; });
    const monthlyMap = {};
    trades.forEach(trade => {
      const stamp = String(tradeTime(trade, 'exit') || tradeTime(trade, 'entry') || '');
      const key = stamp.slice(0, 7) || '—';
      monthlyMap[key] = (monthlyMap[key] || 0) + tradePnl(trade);
    });
    const monthly = Object.keys(monthlyMap).sort().map(key => ({ label: key.slice(5) || key, tooltipLabel: `Месяц ${key}`, value: Math.round(monthlyMap[key] * 100) / 100 }));
    const isDemo = origin.type === 'demo' || detail.kind === 'demo_backtest' || (detail.result && detail.result.kind === 'demo_backtest')
      || (detail.job && detail.job.kind === 'demo_backtest');
    body.innerHTML = `
      ${isDemo ? '<div class="demo-report-banner">Демоверсия. Данные нереальные. · <button type="button" class="btn sm" id="dw-demo-cta">Что откроется после подписки</button></div>' : ''}
      <div class="tb-title" style="margin-bottom:10px"><span class="tb-kicker">№${detail.report_no || summary.report_no || ''} · ${UI.esc(instrument)} · ${UI.esc(status)}${isDemo ? ' · ДЕМО' : ''}</span><span class="tb-h1">${UI.esc(className)}</span></div>
      <div class="flex wrap gap-sm">${statusBadge(status)}${isDemo ? '<span class="badge demo">демо</span>' : ''}<span class="tag">${tfLabel(timeframe)}</span>${period.from_utc || period.to_utc ? `<span class="tag">${(period.from_utc || '').slice(0, 10)} … ${(period.to_utc || '').slice(0, 10)}</span>` : ''}${origin.type === 'ai_lab' ? '<span class="badge ai-origin-badge">AI</span>' : ''}${detail.validated_against_strategy_analyzer ? '<span class="tag">Strategy Analyzer: проверено</span>' : ''}</div>
      <section class="panel" style="margin-top:12px"><div class="panel-h"><h2>Как работает стратегия</h2><span class="sub">${UI.esc(linkedProfile.family || strategyMeta.family || linkedProfile.pattern || 'правила из каталога/профиля')}</span></div><div class="panel-b col gap-sm">${description ? `<p style="margin:0;color:var(--tx-2);line-height:1.55">${UI.esc(description)}</p>` : '<div class="muted">Описание стратегии пока не заполнено в профиле или каталоге; интерфейс не выдумывает правила.</div>'}${rules.length ? `<ul>${rules.map(rule => `<li>${UI.esc(typeof rule === 'string' ? rule : rule.label || rule.summary || JSON.stringify(rule))}</li>`).join('')}</ul>` : ''}<div class="flex wrap gap-sm"><span class="tag" title="${UI.esc(assessment.frequency.explanation)}">${UI.esc(assessment.frequency.label)} · ${assessment.frequency.trades_per_week == null ? '—' : Number(assessment.frequency.trades_per_week).toFixed(1)}/нед</span><span class="tag" title="${UI.esc(assessment.confidence.reasons.join(' · '))}">доверие ${assessment.confidence.score}% · ${UI.esc(assessment.confidence.label)}</span>${linkedProfile.profile_id ? `<a class="tag" href="strategies.html?strategy=${encodeURIComponent(className)}">профиль ${UI.esc(linkedProfile.profile_id)}</a>` : ''}</div></div></section>
      ${eq.length ? '<section class="panel" style="margin-top:12px"><div class="panel-h"><h2>Кривая накопленного P&L (по сделкам)</h2></div><div class="panel-b"><div class="chart-box"><canvas id="dw-eq" style="height:240px"></canvas></div></div></section>' : ''}
      ${trades.length ? '<div class="grid cols-2" style="margin-top:12px"><section class="panel"><div class="panel-h"><h2>P&L каждой сделки</h2></div><div class="panel-b"><div class="chart-box"><canvas id="dw-trade-pnl" style="height:220px"></canvas></div></div></section><section class="panel"><div class="panel-h"><h2>Итог по месяцам</h2></div><div class="panel-b"><div class="chart-box"><canvas id="dw-monthly" style="height:220px"></canvas></div></div></section></div>' : ''}
      <div class="grid cols-4" style="margin-top:12px">${metricCards(m, period)}</div>
      <section class="panel" style="margin-top:12px"><div class="panel-h"><h2>Параметры прогона</h2></div><div class="panel-b"><div class="grid cols-4">
        <div><div class="muted">Исполнение</div><strong>${UI.esc(execution.calculate || '—')}</strong></div>
        <div><div class="muted">Fill resolution</div><strong>${UI.esc(execution.order_fill_resolution || '—')}</strong></div>
        <div><div class="muted">Проскальзывание</div><strong>${execution.slippage_ticks != null ? execution.slippage_ticks + ' тик.' : '—'}</strong></div>
        <div><div class="muted">Начальный капитал</div><strong>${risk.starting_capital != null || risk.StartingCapital != null ? UI.money(Number(risk.starting_capital != null ? risk.starting_capital : risk.StartingCapital)) : '—'}</strong></div>
      </div>${Object.keys(params).length ? `<details style="margin-top:10px"><summary>Параметры стратегии (${Object.keys(params).length})</summary><pre class="logbox">${UI.esc(JSON.stringify(params, null, 2))}</pre></details>` : ''}</div></section>
      ${warnings.length ? `<details class="panel" style="margin-top:12px"><summary class="panel-h"><h2>Проверка и журнал (${warnings.length})</h2></summary><div class="panel-b"><pre class="logbox">${UI.esc(warnings.join('\n'))}</pre></div></details>` : ''}
      <div class="flex wrap gap-sm" style="margin-top:12px">
        <button class="btn" id="dw-fav">${UI.icon('star')}${favorite ? 'Убрать из избранного' : 'В избранное'}</button>
        <button class="btn" id="dw-repeat">${UI.icon('refresh')}Повторить прогон</button>
        <button class="btn" id="dw-price">${UI.icon('chart')}Обновить график цены</button>
        <a class="btn ghost" href="/api/jobs/${encodeURIComponent(jobId)}" target="_blank" rel="noopener">${UI.icon('download')}Сырой JSON</a>
        <button class="btn danger" id="dw-delete">${UI.icon('trash')}Удалить</button>
      </div>
      <section class="panel" id="dw-price-panel" style="margin-top:12px"><div class="panel-h"><h2>Цена и артефакты</h2><span class="sub" id="dw-price-sub">загрузка...</span></div><div class="panel-b"><div class="chart-box" id="dw-price-box"><div class="state-loading"><span class="spinner"></span>Загрузка bars…</div></div></div></section>
      <section class="panel" style="margin-top:12px"><div class="panel-h"><h2>Сделки</h2><span class="sub">${UI.esc(tradesCountLabel)}</span></div>
        <div class="panel-b tight"><div class="tbl-wrap" style="max-height:320px"><table class="tbl"><thead><tr><th>#</th><th>Сторона</th><th>Вход</th><th>Выход</th><th class="num">Кол.</th><th class="num">Цена входа</th><th class="num">Цена выхода</th><th class="num">Тики</th><th class="num">Комис.</th><th class="num">P&L</th></tr></thead>
        <tbody>${trades.length ? trades.slice(0, 200).map((t, i) => { const pnl = tradePnl(t); return `<tr><td class="muted">${t.trade_no || i + 1}</td><td>${UI.esc(t.side || t.market_position || t.direction || '')}</td><td class="mono muted">${UI.esc(tradeTime(t, 'entry').toString().slice(0, 16).replace('T', ' '))}</td><td class="mono muted">${UI.esc(tradeTime(t, 'exit').toString().slice(0, 16).replace('T', ' '))}</td><td class="num">${t.quantity != null ? t.quantity : '—'}</td><td class="num">${t.entry_price != null ? t.entry_price : (t.price != null ? t.price : '—')}</td><td class="num">${t.exit_price != null ? t.exit_price : '—'}</td><td class="num">${t.pnl_ticks != null ? t.pnl_ticks : '—'}</td><td class="num muted">${t.commission != null ? UI.money(t.commission) : '—'}</td><td class="num ${UI.pnlClass(pnl)}">${UI.money(pnl, { sign: true })}</td></tr>`; }).join('') : '<tr><td colspan="10"><div class="empty-state">Сделок нет.</div></td></tr>'}</tbody></table></div></div></section>`;
    if (eq.length) requestAnimationFrame(() => {
      Chart.pnl(UI.qs('#dw-eq'), eq, { money: true, height: 240, labels: trades.map(trade => String(tradeTime(trade, 'exit') || tradeTime(trade, 'entry') || '').slice(0, 16).replace('T', ' ')) });
      Chart.bars(UI.qs('#dw-trade-pnl'), trades.slice(-80).map((trade, index) => { const number = Math.max(1, trades.length - 79 + index); return { label: index % 10 === 0 ? String(number) : '', tooltipLabel: `Сделка #${number}`, tooltipDetail: String(tradeTime(trade, 'exit') || tradeTime(trade, 'entry') || '').slice(0, 16).replace('T', ' '), value: tradePnl(trade) }; }), { money: true, height: 220 });
      Chart.bars(UI.qs('#dw-monthly'), monthly, { money: true, height: 220 });
    });
    UI.qs('#dw-fav').onclick = async () => { try { if (favorite) await API.http.unfavoriteReport('job', jobId); else await API.http.favoriteReport({ kind: 'job', id: jobId }); UI.toast(favorite ? 'Убрано из избранного' : 'В избранном'); UI.closeDrawer(); loadReports(true); } catch (e) { UI.reportError(e); } };
    const demoCta = UI.qs('#dw-demo-cta');
    if (demoCta) demoCta.onclick = () => { try { UI.openCabinet('plans'); } catch (e) { /* ignore */ } };
    if (isDemo) {
      const rep = UI.qs('#dw-repeat'); if (rep) { rep.disabled = true; rep.title = 'Повтор реального прогона недоступен в демо'; }
    }
    UI.qs('#dw-repeat').onclick = async () => {
      if (isDemo) { UI.toast('В демо повторите сценарий кнопкой «Демо-бэктест»'); return; }
      const reqBody = {
        class_name: className, instrument,
        bars_period_type: timeframe.bars_period_type || 'Minute', bars_period_value: timeframe.value || timeframe.bars_period_value || 1,
        from_utc: period.from_utc || '', to_utc: period.to_utc || '', parameters: params,
        risk_profile: risk, order_fill_resolution: execution.order_fill_resolution || 'High',
        slippage_ticks: execution.slippage_ticks != null ? execution.slippage_ticks : 1,
        commission: 0,
        commission_template: commissionTemplateOrDefault(execution.commission_template), session_template: execution.session_template || '',
        is_tick_replay: !!execution.is_tick_replay, role: execution.role || 'research',
      };
      try { const r = await API.http.createJob(reqBody); UI.toast('Прогон поставлен в очередь · ' + (r.job_id || '')); UI.closeDrawer(); loadReports(true); pollQueue(); }
      catch (e) { UI.reportError(e); }
    };
    async function loadPriceChart() {
      UI.qs('#dw-price').disabled = true;
      try {
        const [barsDoc, drawDoc] = await Promise.all([API.http.jobBars(jobId, { limit: 3000 }), API.http.jobDrawObjects(jobId).catch(() => ({ draw_objects: [] }))]);
        const bars = barsDoc.bars || []; const draws = drawDoc.draw_objects || drawDoc.items || [];
        UI.qs('#dw-price-sub').textContent = `${bars.length}/${barsDoc.total || bars.length} bars · ${trades.length} сделок · ${draws.length} объектов`;
        if (!bars.length) UI.renderEmpty(UI.qs('#dw-price-box'), 'Bars artifact отсутствует.');
        else { UI.qs('#dw-price-box').innerHTML = '<canvas id="dw-price-chart" style="height:300px"></canvas>'; const chart = Chart.price(UI.qs('#dw-price-chart'), bars, { height: 300, trades, draws }); UI.qs('#dw-price-sub').textContent += ` · ${chart.markerCount} маркеров`; }
      } catch (e) { UI.renderError(UI.qs('#dw-price-box'), e, loadPriceChart); }
      finally { UI.qs('#dw-price').disabled = false; }
    }
    UI.qs('#dw-price').onclick = loadPriceChart;
    loadPriceChart();
    UI.qs('#dw-delete').onclick = async () => { if (!confirm('Удалить отчёт ' + jobId + '? Действие необратимо.')) return; try { await API.http.deleteJob(jobId); UI.toast('Отчёт удалён'); UI.closeDrawer(); loadReports(true); } catch (e) { UI.reportError(e); } };
  }

  // ---------- composer / submit ----------
  function buildJobBody() {
    const [tfType, tfVal] = UI.qs('#f-tf').value.split(':');
    const period = UI.qs('#f-period').value;
    const ymd = d => d.toISOString().slice(0, 10) + 'T00:00:00Z';
    let from = '', to = '';
    if (period === 'custom') { const f = UI.qs('#f-from').value, t = UI.qs('#f-to').value; from = f ? f + 'T00:00:00Z' : ''; to = t ? t + 'T00:00:00Z' : ''; }
    else { const days = parseInt(period, 10), today = new Date(); from = ymd(new Date(today.getTime() - days * 86400000)); to = ymd(today); }
    return {
      class_name: UI.qs('#f-strategy').value,
      instrument: UI.qs('#f-instrument').value.trim(),
      bars_period_type: tfType, bars_period_value: parseInt(tfVal, 10),
      from_utc: from, to_utc: to,
      order_fill_resolution: UI.qs('#f-fill').value,
      slippage_ticks: parseInt(UI.qs('#f-slippage').value, 10),
      commission: 0,
      commission_template: commissionTemplateOrDefault(UI.qs('#f-commission-template').value),
      is_tick_replay: UI.qs('#f-tickreplay').checked,
      risk_profile: { StartingCapital: parseFloat(UI.qs('#f-capital').value) },
      parameters: collectStrategyParams(),
      role: 'research',
    };
  }
  async function runBacktest() {
    const body = buildJobBody();
    if (!body.class_name) { UI.toast('Выберите стратегию'); return; }
    if (!body.instrument) { UI.toast('Укажите инструмент'); return; }
    if (!body.from_utc || !body.to_utc) { UI.toast('Укажите период (даты)'); return; }
    if (basket.length > 1) {
      const btn = UI.qs('#run-btn'); btn.disabled = true;
      try { const instruments = basket.map(root => { const fm = (roots.find(r => r.root === root) || {}).front_month; return (fm && fm.instrument) || root; }); const out = await API.http.createBatch(Object.assign({}, body, { instruments, name: `${body.class_name} ×${instruments.length}` })); UI.toast(`Пакет ${out.batch_id || ''}: ${instruments.length} прогонов`); loadReports(true); pollQueue(); }
      catch (e) { UI.reportError(e); } finally { btn.disabled = false; }
      return;
    }
    const btn = UI.qs('#run-btn'); btn.disabled = true;
    try { const r = await API.http.createJob(body); UI.toast('Бэктест поставлен в очередь · ' + (r.job_id || '')); loadReports(true); pollQueue(); }
    catch (e) { UI.reportError(e); } finally { btn.disabled = false; }
  }

  async function runDemoBacktest(scenarioId) {
    const btn = UI.qs('#demo-run-btn');
    if (btn) btn.disabled = true;
    try {
      const out = await API.http.createDemoBacktest({ scenario_id: scenarioId || selectedDemoScenario || '' });
      UI.toast((out.watermark || 'Демо готово') + ' · осталось сегодня: ' + (out.remaining_today ?? '—'));
      await loadReports(true);
      if (out.job_id) openReport(out.job_id);
    } catch (e) { UI.reportError(e); }
    finally { if (btn) btn.disabled = false; }
  }

  let selectedDemoScenario = '';
  async function setupDemoTier() {
    const demoBtn = UI.qs('#demo-run-btn');
    const runBtn = UI.qs('#run-btn');
    const host = UI.qs('#demo-scenarios');
    const demoTier = document.body.dataset.demoTier === '1'
      || !!(window.UI && UI.CURRENT_AUTH && UI.CURRENT_AUTH.demo_tier);
    const auth = (window.UI && UI.CURRENT_AUTH) || (window.API && (await API.refreshAuth()).auth) || {};
    const caps = auth.capabilities || {};
    const isDemoOnly = !!(auth.demo_tier || (caps.demo_backtest && !caps.backtesting && !auth.is_owner));
    if (isDemoOnly && runBtn) {
      runBtn.hidden = true;
      const composer = UI.qs('.composer');
      if (composer) composer.hidden = true;
    }
    if (!demoBtn) return;
    try {
      const doc = await API.http.demoBacktestScenarios();
      const scenarios = doc.scenarios || [];
      selectedDemoScenario = (scenarios[0] && scenarios[0].id) || '';
      // The scenario picker carries the demo watermark and the subscription
      // upsell, so it belongs to the demo tier alone. Rendering it for an
      // account that already has full backtesting told the owner their real
      // backtests were "Демоверсия. Данные нереальные." -- a false claim about
      // authoritative data, not just cosmetic noise. The demo button itself
      // stays available; only this tier-specific panel is scoped.
      if (host && isDemoOnly) {
        host.hidden = false;
        host.innerHTML = `<div class="cab-sub">${UI.esc(doc.watermark || 'Демоверсия. Данные нереальные.')}</div>
          <div class="seg demo-scenario-seg">${scenarios.map((s, i) =>
            `<button type="button" class="${i === 0 ? 'active' : ''}" data-demo-sc="${UI.esc(s.id)}">${UI.esc(s.label)}</button>`
          ).join('')}</div>
          <div class="muted">После подписки откроются полный бэктест, свои стратегии и live/paper.</div>`;
        UI.qsa('[data-demo-sc]', host).forEach(b => b.onclick = () => {
          UI.qsa('[data-demo-sc]', host).forEach(x => x.classList.remove('active'));
          b.classList.add('active');
          selectedDemoScenario = b.dataset.demoSc;
        });
      } else if (host) {
        host.hidden = true;
        host.innerHTML = '';
      }
    } catch (e) { /* scenarios optional for paid users */ }
    demoBtn.onclick = () => runDemoBacktest(selectedDemoScenario);
    if (!isDemoOnly && !caps.demo_backtest && !auth.is_owner && !caps.backtesting) {
      demoBtn.hidden = true;
    }
  }

  // ---------- active queue ----------
  async function pollQueue() {
    let doc;
    try { doc = await API.http.jobs({ limit: 20 }); } catch (e) { return; }
    const c = doc.counts || {};
    const active = (doc.jobs || []).filter(j => j.status === 'running' || j.status === 'pending' || j.status === 'cancel_requested');
    const panel = UI.qs('#queue-panel');
    if (!active.length) { panel.hidden = true; return; }
    panel.hidden = false;
    UI.qs('#queue-sub').textContent = `${c.running || 0} в работе · ${c.pending || 0} в очереди`;
    UI.qs('#queue-list').innerHTML = active.map(j => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(j.class_name || j.job_id)}</div><div class="row-sub">${UI.esc(j.instrument || '')} · ${UI.esc(stText(j.status))}</div></div><div class="row-val">${j.status === 'cancel_requested' ? '<span class="sub">отменяется…</span>' : `<button class="btn sm danger" data-cancel="${UI.esc(j.job_id)}">Отмена</button>`}</div></div>`).join('');
    // No native confirm(): it blocks the page, cannot be styled, and stands
    // between an operator and stopping a run that is burning time right now.
    // Cancelling is reversible -- the backtest can simply be started again --
    // so it acts immediately and says so. Deleting a report keeps its
    // confirmation, because that one cannot be undone.
    UI.qsa('#queue-list button[data-cancel]').forEach(b => b.onclick = async () => { b.disabled = true; try { await API.http.cancelJob(b.dataset.cancel); UI.toast('Отмена запрошена — NinjaTrader завершает текущую фазу'); pollQueue(); loadReports(true); } catch (e) { b.disabled = false; UI.reportError(e); } });
  }

  // ---------- init ----------
  UI.qs('#inst-search').oninput = e => renderInst(e.target.value);
  UI.qs('#inst-group').onchange = () => renderInst(UI.qs('#inst-search').value);
  UI.qs('#econ-btn').onclick = openEcon;
  UI.qs('#add-all').onclick = () => { roots.forEach(r => { if (!basket.includes(r.root)) basket.push(r.root); }); renderInst(UI.qs('#inst-search').value); renderBasket(); UI.toast('Все видимые добавлены в корзину'); };
  UI.qsa('#side-tabs button').forEach(b => b.onclick = () => { UI.qsa('#side-tabs button').forEach(x => x.classList.remove('active')); b.classList.add('active'); const t = b.dataset.tab; ['inst', 'prof', 'cov'].forEach(name => { UI.qs('#pane-' + name).hidden = t !== name; }); });
  UI.qs('#f-period').onchange = (e) => { const cu = e.target.value === 'custom'; UI.qs('#f-custom-from').hidden = !cu; UI.qs('#f-custom-to').hidden = !cu; };
  UI.qs('#f-strategy').onchange = () => renderStrategyParams({});
  UI.qs('#run-btn').innerHTML = UI.icon('play') + 'Запустить прогон';
  UI.qs('#run-btn').onclick = runBacktest;
  setupDemoTier();
  UI.qsa('#rep-filter button').forEach(b => b.onclick = () => { UI.qsa('#rep-filter button').forEach(x => x.classList.remove('active')); b.classList.add('active'); repFilter = b.dataset.f === 'fav' ? 'favorite' : b.dataset.f; loadReports(true); });
  UI.qsa('#rep-table th.sortable').forEach(header => header.onclick = () => {
    const next = header.dataset.sort;
    if (repSort === next) repDir = repDir === 'asc' ? 'desc' : 'asc'; else { repSort = next; repDir = ['label','status','period'].includes(next) ? 'asc' : 'desc'; }
    UI.qsa('#rep-table th.sortable').forEach(item => { item.classList.toggle('active', item === header); item.dataset.dir = item === header ? repDir : ''; });
    loadReports(true);
  });
  let filterTimer = null;
  const filterIds = ['rep-search','rep-no','rep-instrument','rep-frequency','rep-min-trades','rep-min-win','rep-min-pf','rep-min-confidence','rep-pnl-sign','rep-from','rep-to','rep-analysis-limit'];
  filterIds.forEach(id => UI.qs('#' + id).addEventListener(['SELECT','INPUT'].includes(UI.qs('#' + id).tagName) ? 'input' : 'change', () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => loadReports(true), 350); }));
  UI.qs('#rep-hierarchy').onchange = e => { repHierarchy = e.target.value; loadReports(true); };
  UI.qs('#rep-clear').onclick = () => { filterIds.forEach(id => { UI.qs('#' + id).value = id === 'rep-analysis-limit' ? '500' : ''; }); repHierarchy = 'report'; UI.qs('#rep-hierarchy').value = 'report'; loadReports(true); };

  // load data
  const initialReports = loadReports(true);
  const initialQueue = pollQueue();
  const [instr, prof, cov, cat] = await Promise.all([API.http.instruments().catch(() => null), API.http.profiles().catch(() => null), API.http.coverage().catch(() => null), API.http.catalog().catch(() => null)]);
  roots = (instr && instr.roots) || [];
  profiles = (prof && prof.profiles) || []; coverage = cov; catalog = cat;
  renderStrategyCatalog();
  renderCommissionTemplates();
  const groups = Array.from(new Set(roots.map(rootGroup))).sort((a, b) => a.localeCompare(b, 'ru'));
  UI.qs('#inst-group').innerHTML = '<option value="all">Все группы</option>' + groups.map(group => `<option>${UI.esc(group)}</option>`).join('');
  renderInst(); renderBasket(); renderProfiles(); renderCoverage(); renderStrategyParams({});
  await initialReports;
  await initialQueue;
  UI.poll(pollQueue, 8000);

  // deep links
  const params = new URLSearchParams(location.search);
  const wantJob = params.get('job');
  const wantInstrument = params.get('instrument');
  const wantStrategy = params.get('strategy');
  if (wantInstrument) { const r = roots.find(x => x.root === wantInstrument); if (r && r.front_month) UI.qs('#f-instrument').value = r.front_month.instrument; }
  if (wantStrategy) { const opt = Array.from(UI.qs('#f-strategy').options).find(o => o.value === wantStrategy); if (opt) UI.qs('#f-strategy').value = wantStrategy; }
  if (wantJob) setTimeout(() => openReport(wantJob), 300);
});
