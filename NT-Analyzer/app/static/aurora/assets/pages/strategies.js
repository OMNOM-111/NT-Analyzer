/* Портфель стратегий — реальная интеграция. CSP-safe (external, no inline handlers).
   Endpoints: /api/profiles, /api/ai-lab/lifecycle, /api/coverage, /api/profiles/archive,
   actions: /api/ops/profiles/{id}/{update|delete}, /api/profiles/ninjatrader/cleanup. */
UI.ready(async function () {
  const STATUS_CLASS = { ready: 'live', paper_ready: 'demo', rejected: 'rejected', archived: 'rejected' };
  const STATUS_LABEL = { ready: 'Готова', paper_ready: 'Paper-ready', rejected: 'Отклонено', archived: 'Архив' };
  const BADGE_CLASS = { ready: 'live', paper_ready: 'demo', rejected: 'failed', archived: 'archived' };
  const LC_COLS = [
    { key: 'trial', title: 'Испытание', accent: 'var(--warn)' },
    { key: 'approved_demo', title: 'Демо', accent: 'var(--info)' },
    { key: 'approved_live', title: 'Реальная торговля', accent: 'var(--pos)' },
  ];
  let profiles = [], aiCards = [], coverage = null, archive = [], registry = null, runtimeRoots = [], curOrigin = 'all', curFrequency = 'all';

  function fmtDate(iso) { try { return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: '2-digit' }); } catch (e) { return iso || ''; } }
  function normProfile(p) {
    const m = p.metrics || {};
    const period = p.test_period || (m.full_2024_2025 && { from_utc: m.full_2024_2025.from_utc, to_utc: m.full_2024_2025.to_utc }) || {};
    const frequency = AuroraDomain.frequencyAssessment(m.trade_count, period);
    return {
      id: p.profile_id, name: p.name, cell: p.cell_id || p.archived_cell_id || '',
      root: p.root_family || (p.instrument || '').split(' ')[0] || '—', instrument: p.instrument, tf: p.timeframe,
      status: p.status, statusLabel: p.status_label, lifecycle: p.lifecycle, lifecycleLabel: p.lifecycle_label,
      origin: p.origin || 'production', originLabel: p.origin_label, isAi: !!p.is_ai_lab, family: p.strategy_family,
      net: m.net_profit_after_commission, pf: m.profit_factor_after_commission, win: m.winning_pct, trades: m.trade_count,
      lastJob: p.last_job_id, updated: p.updated_at_utc, decision: p.decision, metrics: m, period, frequency, raw: p,
    };
  }
  function normAi(c) {
    return {
      id: c.profile_id || c.experiment_id, name: c.name, cell: c.cell_id || '', root: c.instrument, instrument: c.instrument, tf: c.timeframe,
      status: c.ai_status, statusLabel: c.ai_status_label, lifecycle: c.lifecycle, lifecycleLabel: c.lifecycle_label,
      origin: 'ai_lab', originLabel: c.origin_label, isAi: true, family: c.strategy_family, attempts: c.attempts,
      archiveReason: c.archive_reason, experimentId: c.experiment_id, updated: c.updated_at_utc,
      net: null, pf: null, win: null, raw: c,
      frequency: { key: 'unknown', label: 'частота неизвестна', trades_per_week: null, explanation: 'Эксперимент ещё не имеет итогового профиля.' },
    };
  }
  const byId = (id) => [...profiles, ...aiCards].find(x => x.id === id);
  function statusBadge(c) { return `<span class="badge ${BADGE_CLASS[c.status] || ''}"><span class="dot"></span>${UI.esc(c.statusLabel || c.status || '—')}</span>`; }

  const kpiBox = UI.qs('#kpis');
  UI.renderLoading(kpiBox, 'Загрузка портфеля стратегий…');
  async function fetchAll() {
    const [pr, ai, cov, arc, reg, inst] = await Promise.all([
      API.http.profiles().catch(() => null), API.http.aiLifecycle().catch(() => null),
      API.http.coverage().catch(() => null), API.http.profilesArchive().catch(() => null),
      API.http.portfolioCells().catch(() => null), API.http.instruments().catch(() => null),
    ]);
    profiles = ((pr && pr.profiles) || []).map(normProfile);
    aiCards = ((ai && ai.cards) || []).map(normAi);
    coverage = cov; archive = (arc && arc.entries) || []; registry = reg;
    runtimeRoots = (inst && inst.roots) || [];
    return !!(pr || cov);
  }
  async function reload() { await fetchAll(); renderKpis(); renderKanban(); renderMatrix(); renderGoals(); }

  if (!(await fetchAll())) { UI.renderError(kpiBox, new Error('backend недоступен'), () => location.reload()); return; }
  renderKpis(); renderKanban(); renderMatrix(); renderGoals(); wireControls();
  const wanted = new URLSearchParams(location.search).get('strategy');
  if (wanted) { const c = [...profiles, ...aiCards].find(x => x.name === wanted); if (c) openCard(c); }

  function renderKpis() {
    const ready = profiles.filter(p => p.status === 'ready' || p.status === 'paper_ready').length;
    const demoLc = profiles.filter(p => p.lifecycle === 'approved_demo').length;
    const archived = profiles.filter(p => ['archived', 'rejected'].includes(p.status)).length;
    const cs = (coverage && coverage.summary) || {};
    const rs = (registry && registry.summary) || {};
    kpiBox.innerHTML = [
      { label: 'Portfolio roots', val: rs.roots != null ? rs.roots : ((coverage && coverage.instruments) || []).length, cls: 'pos', icon: 'layers', foot: `${rs.active || 0} активных ячеек · ${runtimeRoots.length || 0} roots в каталоге` },
      { label: 'Готовых профилей', val: ready, cls: 'info', icon: 'strategies', foot: 'ready + paper-ready' },
      { label: 'Утверждено для демо', val: demoLc, cls: '', icon: 'check', foot: 'жизненный цикл' },
      { label: 'AI-эксперименты', val: aiCards.length, cls: 'warn', icon: 'ai', foot: 'архив AI Lab' },
      { label: 'Архив / отклонено', val: archived, cls: 'neg', icon: 'trash', foot: 'do-not-recreate: ' + archive.length },
    ].map(k => `<div class="kpi ${k.cls}"><div class="kpi-top"><span class="kpi-label">${k.label}</span><span class="kpi-ic">${UI.icon(k.icon)}</span></div><div class="kpi-val sm">${k.val}</div><div class="kpi-foot">${k.foot}</div></div>`).join('');
  }

  function kanCard(c) {
    const meta = c.isAi
      ? `<span>${UI.esc(c.statusLabel || '')}</span><span>попыток <b>${c.attempts || 1}</b></span>`
      : `<span>P&L <b class="${UI.pnlClass(c.net || 0)}">${c.net != null ? UI.money(c.net, { sign: true }) : '—'}</b></span>${c.win != null ? `<span>WR <b class="${AuroraDomain.metricTone('win', c.win)}">${UI.pct(c.win)}</b></span>` : ''}${c.pf != null ? `<span>PF <b class="${AuroraDomain.metricTone('pf', c.pf)}">${Number(c.pf).toFixed(2)}</b></span>` : ''}`;
    const frequency = c.frequency || { key: 'unknown', label: 'частота неизвестна' };
    return `<div class="kan-card ${c.isAi ? 'ai-origin' : ''}" data-id="${UI.esc(c.id)}">${c.isAi ? `<div class="ai-origin-ribbon">${UI.icon('ai')}AI стратегия · автономная лаборатория</div>` : ''}<div class="kc-top"><span class="kc-name">${UI.esc(c.name)}</span><span class="tag">${UI.esc(c.cell || c.root || '')}</span></div><div class="kc-meta">${meta}</div><div class="flex between" style="margin-top:9px"><span class="badge ${frequency.key === 'normal' ? 'live' : frequency.key === 'unknown' ? 'archived' : 'trial'}" title="${UI.esc(frequency.explanation || '')}">${UI.esc(frequency.label)}</span><span class="muted mono" style="font-size:10px">${frequency.trades_per_week == null ? '—' : Number(frequency.trades_per_week).toFixed(1) + '/нед'}</span></div></div>`;
  }
  function renderKanban() {
    let cards = [...profiles, ...aiCards];
    if (curOrigin !== 'all') cards = cards.filter(c => c.origin === curOrigin);
    if (curFrequency !== 'all') cards = cards.filter(c => c.frequency && c.frequency.key === curFrequency);
    UI.qs('#kanban').innerHTML = LC_COLS.map(col => {
      const list = cards.filter(c => c.lifecycle === col.key);
      return `<div class="kan-col"><div class="kan-h"><span class="accent" style="background:${col.accent}"></span><span class="t">${col.title}</span><span class="n">${list.length}</span></div><div class="kan-b">${list.map(kanCard).join('') || '<div class="empty-state" style="padding:18px">пусто</div>'}</div></div>`;
    }).join('');
    UI.qsa('#kanban .kan-card').forEach(el => el.onclick = () => openCard(byId(el.dataset.id)));
  }

  function renderMatrix() {
    const hideRej = UI.qs('#hide-rejected').checked;
    const cells = (registry && registry.cells) || [];
    const byRoot = {};
    cells.forEach(cell => { (byRoot[cell.root] = byRoot[cell.root] || []).push(cell); });
    const profileByCell = {};
    profiles.forEach(profile => { if (profile.cell) profileByCell[profile.cell.toUpperCase()] = profile; });
    UI.qs('#matrix').innerHTML = Object.entries(byRoot).map(([root, rootCells]) => {
      rootCells.sort((a, b) => a.slot - b.slot);
      const rendered = rootCells.map(cell => {
        const p = profileByCell[String(cell.cell_id).toUpperCase()];
        const hiddenProfile = p && hideRej && (p.status === 'rejected' || p.status === 'archived');
        const active = cell.status !== 'archived';
        const cls = !active ? 'archived' : (p && !hiddenProfile ? (STATUS_CLASS[p.status] || '') : 'empty');
        const attrs = p && !hiddenProfile ? ` data-id="${UI.esc(p.id)}"` : ` data-cell="${UI.esc(cell.cell_id)}"`;
        const title = p && !hiddenProfile ? `${p.name} · ${p.statusLabel || p.status} · ${cell.cell_id}` : `${cell.cell_id} · ${root} · слот ${cell.slot} · ${active ? 'свободно' : 'архив'}`;
        return `<div class="mcell ${cls}"${attrs} title="${UI.esc(title)}"><span class="mc-no">${String(cell.cell_id).replace('CELL-', '')}</span><span class="mc-tf">${p && !hiddenProfile ? UI.esc((p.tf || '').replace(/ ?Minute/, 'м')) : (active ? 'free' : 'arc')}</span></div>`;
      });
      const approved = rootCells.filter(cell => { const p = profileByCell[String(cell.cell_id).toUpperCase()]; return p && (p.status === 'ready' || p.status === 'paper_ready'); }).length;
      const active = rootCells.filter(cell => cell.status !== 'archived').length;
      return `<div class="matrix-row"><div class="matrix-root"><span class="sym">${UI.esc(root)}</span><span class="meta">${approved}/${active} одобрено</span></div><div class="matrix-cells">${rendered.join('')}</div></div>`;
    }).join('') || '<div class="empty-state">Registry ячеек недоступен.</div>';
    UI.qsa('#matrix .mcell[data-id]').forEach(el => el.onclick = () => openCard(byId(el.dataset.id)));
    UI.qsa('#matrix .mcell[data-cell]').forEach(el => el.onclick = () => openEmptyCell(el.dataset.cell));
  }

  function renderGoals() {
    const coverageByRoot = {}; ((coverage && coverage.instruments) || []).forEach(row => { coverageByRoot[row.root] = row; });
    const insts = (registry && registry.roots) || [];
    UI.qs('#goal-body').innerHTML = insts.length ? insts.map(c => {
      const cov = coverageByRoot[c.root] || {}; const cnt = cov.strategy_count || 0; const target = c.active_count || c.cell_count || 1; const ready = cov.best_status === 'ready';
      return `<tr><td class="mono"><strong>${UI.esc(c.root)}</strong><div class="muted" style="font-size:10px">${c.legacy ? 'базовый root' : 'добавлен вручную'}</div></td><td class="num">${cnt}/${target}</td><td><span class="minibar" style="width:120px"><span style="width:${Math.min(100, cnt / target * 100)}%;background:${ready ? 'var(--pos)' : 'var(--warn)'}"></span></span></td><td>${UI.esc(cov.best_status || 'нет профиля')}</td></tr>`;
    }).join('') : '<tr><td colspan="4" class="muted">Нет данных покрытия.</td></tr>';
  }

  function openEmptyCell(cellId) {
    const cell = ((registry && registry.cells) || []).find(row => row.cell_id === cellId);
    if (!cell) return;
    UI.drawer(`<h3>${UI.esc(cell.cell_id)}</h3>`, `<div class="list"><div class="row"><div class="row-main"><div class="row-title">${UI.esc(cell.root)} · слот ${cell.slot}</div><div class="row-sub">Стабильный ID · ${cell.legacy ? 'историческая схема' : 'ручное расширение'}</div></div><div class="row-val"><span class="badge ${cell.status === 'active' ? 'live' : 'archived'}">${UI.esc(cell.status)}</span></div></div></div><p class="muted" style="margin-top:12px">Профиль пока не назначен. ID зарезервирован и не будет использован повторно.</p>${!cell.legacy && cell.status === 'active' ? '<button class="btn danger" id="archive-cell" style="margin-top:12px">Архивировать ячейку</button>' : ''}`);
    const button = UI.qs('#archive-cell');
    if (button) button.onclick = async () => { if (!confirm(`Архивировать ${cell.cell_id}? ID больше не будет использоваться.`)) return; try { await API.http.portfolioArchiveCell(cell.cell_id, { actor: 'ui' }); UI.toast('Ячейка архивирована'); UI.closeDrawer(); await reload(); } catch (e) { UI.reportError(e); } };
  }

  function rootName(row) { return typeof row === 'string' ? row : (row.root || row.symbol || ''); }

  function openAddRoot() {
    const existing = new Set(((registry && registry.roots) || []).map(row => row.root));
    const choices = runtimeRoots.map(rootName).filter(Boolean).filter(root => !existing.has(root));
    UI.drawer('<h3>Добавить инструмент в портфель</h3>', `<div class="col gap-sm"><div class="field"><label for="new-root">Root</label><input id="new-root" list="runtime-root-list" placeholder="например MCD"><datalist id="runtime-root-list">${choices.map(root => `<option value="${UI.esc(root)}"></option>`).join('')}</datalist></div><div class="field"><label for="new-root-slots">Количество ячеек</label><input id="new-root-slots" type="number" min="1" max="50" value="15"></div><div class="field"><label for="new-root-start">Начальный ID (необязательно)</label><input id="new-root-start" placeholder="например 200 или CELL-200"></div><p class="muted">Без начального ID используется следующий свободный номер. Существующие и архивные ID не переиспользуются.</p><button class="btn primary" id="new-root-save">Создать root и ячейки</button></div>`);
    UI.qs('#new-root-save').onclick = async () => {
      const root = UI.qs('#new-root').value.trim().toUpperCase(); const slots = Number(UI.qs('#new-root-slots').value); const start = UI.qs('#new-root-start').value.trim();
      if (!root) { UI.toast('Укажите root'); return; }
      if (!confirm(`Добавить ${root}: ${slots} ячеек${start ? ` начиная с ${start}` : ''}?`)) return;
      try { await API.http.portfolioAddRoot({ root, slots, start_id: start || null, actor: 'ui' }); UI.toast(`${root} добавлен`); UI.closeDrawer(); await reload(); } catch (e) { UI.reportError(e); }
    };
  }

  function openAddCell() {
    const roots = ((registry && registry.roots) || []).map(row => row.root);
    UI.drawer('<h3>Добавить ячейку</h3>', `<div class="col gap-sm"><div class="field"><label for="cell-root">Root</label><select id="cell-root">${roots.map(root => `<option>${UI.esc(root)}</option>`).join('')}</select></div><div class="field"><label for="cell-explicit">Явный ID (необязательно)</label><input id="cell-explicit" placeholder="CELL-300"></div><p class="muted">Новый slot добавляется в конец выбранного root. Автоматический ID всегда больше текущего максимума.</p><button class="btn primary" id="cell-save">Добавить ячейку</button></div>`);
    UI.qs('#cell-save').onclick = async () => { const root = UI.qs('#cell-root').value; const cellId = UI.qs('#cell-explicit').value.trim().toUpperCase(); if (!confirm(`Добавить новую ячейку для ${root}?`)) return; try { await API.http.portfolioAddCell({ root, cell_id: cellId || null, actor: 'ui' }); UI.toast('Ячейка добавлена'); UI.closeDrawer(); await reload(); } catch (e) { UI.reportError(e); } };
  }

  function openCard(c) {
    if (!c) return;
    if (c.isAi) return openAiCard(c);
    const m = c.metrics || {};
    const url = c.lastJob ? ('backtesting.html?job=' + encodeURIComponent(c.lastJob)) : ('backtesting.html?strategy=' + encodeURIComponent(c.name));
    const metrics = [
      ['Чистый P&L (2024-25)', m.net_profit_after_commission != null ? UI.money(m.net_profit_after_commission, { sign: true }) : '—', UI.pnlClass(m.net_profit_after_commission || 0)],
      ['Profit Factor', m.profit_factor_after_commission != null ? Number(m.profit_factor_after_commission).toFixed(2) : '—', AuroraDomain.metricTone('pf', m.profit_factor_after_commission)],
      ['Win Rate', m.winning_pct != null ? UI.pct(m.winning_pct) : '—', AuroraDomain.metricTone('win', m.winning_pct)],
      ['Сделок', m.trade_count != null ? m.trade_count : '—', AuroraDomain.metricTone('trades', m.trade_count, c.period)],
      ['Просадка', m.max_drawdown != null ? UI.money(m.max_drawdown) : '—', 'neg'],
      ['Полож. кварталы', m.positive_quarters || '—', ''],
      ['IS 2024 aPF', m.is_2024_adj_pf != null ? Number(m.is_2024_adj_pf).toFixed(2) : '—', ''],
      ['OOS 2025 aPF', m.oos_2025_adj_pf != null ? Number(m.oos_2025_adj_pf).toFixed(2) : '—', ''],
    ];
    const dec = c.decision || {};
    const frequency = c.frequency || AuroraDomain.frequencyAssessment(m.trade_count, c.period || {});
    UI.drawer(
      `<div class="tb-title"><span class="tb-kicker">${UI.esc([c.cell, c.root, c.tf, c.originLabel].filter(Boolean).join(' · '))}</span><span class="tb-h1">${UI.esc(c.name)}</span></div>`,
      `<div class="flex wrap gap-sm">${statusBadge(c)}${c.family ? `<span class="tag">семейство ${UI.esc(c.family)}</span>` : ''}${c.lifecycleLabel ? `<span class="tag">${UI.esc(c.lifecycleLabel)}</span>` : ''}<span class="badge ${frequency.key === 'normal' ? 'live' : 'trial'}" title="${UI.esc(frequency.explanation || '')}">${UI.esc(frequency.label)} · ${frequency.trades_per_week == null ? '—' : Number(frequency.trades_per_week).toFixed(1)}/нед</span>${c.updated ? `<span class="tag">обновл. ${fmtDate(c.updated)}</span>` : ''}</div>
       <div class="finance-note" style="margin-top:12px"><strong>Политика частоты:</strong> ожидаемая прибыль — ${UI.esc(frequency.profit_expectation || 'не определена')}; риск — ${UI.esc(frequency.risk_expectation || 'не определён')}. ${UI.esc(frequency.explanation || '')}</div>
       <div class="grid cols-4" style="margin-top:14px">${metrics.map(mm => `<div class="kpi"><div class="kpi-label">${mm[0]}</div><div class="kpi-val sm ${mm[2]}">${mm[1]}</div></div>`).join('')}</div>
       ${dec.verdict ? `<section class="panel" style="margin-top:14px"><div class="panel-h"><h2>Решение: ${UI.esc(dec.verdict)}</h2></div><div class="panel-b col gap-sm"><p class="muted" style="font-size:12.5px">${UI.esc(dec.reason || '')}</p>${dec.weaknesses && dec.weaknesses.length ? `<div><strong style="font-size:12px">Слабые места</strong><ul style="margin:6px 0 0 16px;font-size:12px;color:var(--tx-2)">${dec.weaknesses.map(w => `<li>${UI.esc(w)}</li>`).join('')}</ul></div>` : ''}${dec.next_test ? `<div class="muted" style="font-size:12px"><strong>След. тест:</strong> ${UI.esc(dec.next_test)}</div>` : ''}</div></section>` : ''}
       <section class="panel" style="margin-top:14px"><div class="panel-h"><h2>Фактическая торговля и готовность</h2><span class="sub">runtime NinjaTrader · отдельно от бэктеста</span></div><div class="panel-b" id="sd-live"><div class="state-loading"><span class="spinner"></span>Сопоставление runtime и сделок...</div></div></section>
       <section class="panel" style="margin-top:14px"><div class="panel-h"><h2>Операторские заметки</h2><span class="sub">сохраняются в профиле</span></div><div class="panel-b"><label class="field"><span>Комментарий, наблюдения, причины остановки</span><textarea id="sd-notes" rows="6">${UI.esc(c.raw && c.raw.notes || '')}</textarea></label><div class="flex gap-sm"><button class="btn" id="sd-notes-save">Сохранить заметки</button></div></div></section>
       <div class="field" style="margin-top:14px"><label for="sd-status">Изменить статус</label><div class="flex gap-sm"><select class="field" id="sd-status">${Object.keys(STATUS_LABEL).map(s => `<option value="${s}" ${s === c.status ? 'selected' : ''}>${STATUS_LABEL[s]}</option>`).join('')}</select><button class="btn" id="sd-save">Применить</button></div></div>
       <div class="flex wrap gap-sm" style="margin-top:14px"><a class="btn primary" href="${url}">${UI.icon('chart')}Открыть бэктест</a>${c.raw && c.raw.strategy_class ? `<button class="btn" id="sd-hide-runtime">Скрыть класс в runtime-матрице</button>` : ''}<button class="btn danger" id="sd-delete">${UI.icon('trash')}Удалить профиль</button></div>`
    );
    loadStrategyOperationalDetail(c);
    requestAnimationFrame(() => {
      const saveBtn = UI.qs('#sd-save');
      if (saveBtn) saveBtn.onclick = async () => {
        const st = UI.qs('#sd-status').value;
        if (st === c.status) { UI.toast('Статус не изменился'); return; }
        if (!confirm(`Изменить статус «${c.name}» на «${STATUS_LABEL[st]}»?`)) return;
        saveBtn.disabled = true;
        try { await API.http.profileUpdate(c.id, { status: st, status_label: STATUS_LABEL[st] }); UI.toast('Статус обновлён'); UI.closeDrawer(); await reload(); }
        catch (e) { UI.reportError(e); saveBtn.disabled = false; }
      };
      const delBtn = UI.qs('#sd-delete');
      if (delBtn) delBtn.onclick = async () => {
        if (!confirm(`Удалить профиль «${c.name}»? Действие необратимо.`)) return;
        delBtn.disabled = true;
        try { await API.http.profileDelete(c.id); UI.toast('Профиль удалён'); UI.closeDrawer(); await reload(); }
        catch (e) { UI.reportError(e); delBtn.disabled = false; }
      };
      const hideBtn = UI.qs('#sd-hide-runtime');
      if (hideBtn) hideBtn.onclick = async () => {
        const className = c.raw.strategy_class;
        if (!confirm(`Скрыть класс ${className} из runtime-матрицы? История и профиль сохранятся.`)) return;
        try { await API.http.setRuntimeStrategyDisplay({ class_name: className, hidden: true }); UI.toast('Класс скрыт; вернуть его можно в «Торговля → Скрытые классы»'); UI.closeDrawer(); }
        catch (e) { UI.reportError(e); }
      };
      const notesBtn = UI.qs('#sd-notes-save');
      if (notesBtn) notesBtn.onclick = async () => {
        notesBtn.disabled = true;
        try {
          await API.http.profileUpdate(c.id, { notes: UI.qs('#sd-notes').value.trim() });
          c.raw.notes = UI.qs('#sd-notes').value.trim();
          UI.toast('Заметки сохранены');
        } catch (e) { UI.reportError(e); }
        finally { notesBtn.disabled = false; }
      };
    });
  }

  async function loadStrategyOperationalDetail(c) {
    const box = UI.qs('#sd-live');
    if (!box) return;
    const account = UI.getSelectedAccount();
    const accountName = account && account.account_name;
    const [runtimeDoc, perf, journal] = await Promise.all([
      API.http.runtimeStrategies().catch(() => ({ strategies: [] })),
      API.http.performance({ period: 'year', account: accountName }).catch(() => null),
      API.http.opsStrategyJournal((c.raw && c.raw.strategy_id) || c.id).catch(() => ({ rows: [] })),
    ]);
    if (!UI.qs('#sd-live')) return;
    const profileClass = String(c.raw && c.raw.strategy_class || '').toLowerCase();
    const profileId = String(c.id || '').toLowerCase();
    const cellDigits = String(c.cell || '').replace(/\D/g, '');
    const cell = cellDigits ? cellDigits.padStart(3, '0') : '';
    const runtimeRow = (runtimeDoc.strategies || []).find(row => {
      const runtime = row.runtime || {};
      return [row.profile_id, row.strategy_id, runtime.strategy_id, runtime.strategy_class]
        .some(value => String(value || '').toLowerCase() === profileId || (profileClass && String(value || '').toLowerCase() === profileClass));
    });
    const runtime = runtimeRow ? AuroraDomain.normalizeRuntimeStrategy(runtimeRow, new Date()) : null;
    const operating = runtime ? AuroraDomain.strategyOperationalState(runtime) : { label: 'не найдена в runtime', severity: 'bad' };
    const perfRow = ((perf && perf.strategies) || []).find(row => {
      const rowDigits = String(row.cell || '').replace(/\D/g, '');
      const rowCell = rowDigits ? rowDigits.padStart(3, '0') : '';
      return (cell && rowCell === cell) || (profileClass && String(row.strategy_class || '').toLowerCase() === profileClass);
    });
    const journalRows = journal.rows || [];
    box.innerHTML = `<div class="flex wrap gap-sm"><span class="badge ${operating.severity === 'bad' ? 'failed' : operating.severity === 'ok' ? 'live' : operating.severity === 'warn' ? 'trial' : 'demo'}"><span class="dot"></span>${UI.esc(operating.label)}</span>${runtime ? `<span class="tag">${UI.esc(runtime.accountName || 'счёт не указан')}</span><span class="tag">${UI.esc(runtime.instrument || 'инструмент не указан')}</span><span class="tag">${UI.esc(runtime.tradeWindowLabel)}</span>` : ''}</div>
      ${runtime ? `<div class="grid cols-4" style="margin-top:12px"><div class="kpi"><div class="kpi-label">Runtime state</div><div class="kpi-val sm">${UI.esc(runtime.state || '—')}</div></div><div class="kpi"><div class="kpi-label">Позиция</div><div class="kpi-val sm">${UI.esc(runtime.position)} ${runtime.quantity || ''}</div></div><div class="kpi"><div class="kpi-label">Session realized</div><div class="kpi-val sm ${UI.pnlClass(runtime.realizedPnl)}">${UI.money(runtime.realizedPnl, { sign: true })}</div></div><div class="kpi"><div class="kpi-label">Locked params</div><div class="kpi-val sm ${runtime.paramsOk ? 'pos' : 'neg'}">${runtime.paramsOk ? 'совпадают' : 'расхождение'}</div></div></div>${runtime.parameterMismatches.length ? `<div class="finance-note neg"><strong>Расхождения параметров:</strong> ${UI.esc(runtime.parameterMismatches.map(item => item.key || item.name || JSON.stringify(item)).join(', '))}</div>` : ''}` : '<div class="finance-note warn">Стратегия не обнаружена в текущем runtime. Если рынок открыт и профиль должен торговать, проверьте запуск стратегии и её locked-параметры.</div>'}
      <div class="grid cols-3" style="margin-top:12px"><div class="kpi"><div class="kpi-label">Trading P&amp;L · год</div><div class="kpi-val sm ${UI.pnlClass(perfRow && perfRow.pnl || 0)}">${perfRow ? UI.money(perfRow.pnl || 0, { sign: true }) : '—'}</div></div><div class="kpi"><div class="kpi-label">Сделок / Win Rate</div><div class="kpi-val sm">${perfRow ? `${perfRow.trades || 0} · ${UI.pct(perfRow.win_rate || 0)}` : '—'}</div></div><div class="kpi"><div class="kpi-label">Журнал</div><div class="kpi-val sm">${journalRows.length}</div></div></div>
      ${perfRow && (perfRow.daily || []).length ? '<div class="chart-box" id="sd-live-chart-box" style="margin-top:12px"><canvas id="sd-live-chart" style="height:240px"></canvas></div>' : '<div class="empty-state">Фактических сделок для графика пока нет.</div>'}
      ${journalRows.length ? `<details style="margin-top:12px"><summary>Последние записи операторского журнала (${journalRows.length})</summary><pre class="logbox">${UI.esc(JSON.stringify(journalRows.slice(-30), null, 2))}</pre></details>` : ''}`;
    if (perfRow && (perfRow.daily || []).length) {
      let cumulative = 0;
      const daily = perfRow.daily;
      Chart.pnl(UI.qs('#sd-live-chart'), daily.map(day => (cumulative += Number(day.pnl || 0))), { money: true, height: 240, labels: daily.map(day => day.date) });
    }
  }

  async function openAiCard(c) {
    UI.drawer(
      `<div class="tb-title"><span class="tb-kicker">${UI.esc([c.cell, c.instrument, c.originLabel].filter(Boolean).join(' · '))}</span><span class="tb-h1">${UI.esc(c.name)}</span></div>`,
      `<div class="flex wrap gap-sm"><span class="badge ai-origin-badge">${UI.icon('ai')}AI стратегия</span>${statusBadge(c)}${c.lifecycleLabel ? `<span class="tag">${UI.esc(c.lifecycleLabel)}</span>` : ''}<span class="tag">попыток: ${c.attempts || 1}</span></div>
       ${c.archiveReason ? `<p class="muted" style="margin-top:12px;font-size:12.5px"><strong>Причина архива:</strong> ${UI.esc(c.archiveReason)}</p>` : ''}
       <div class="flex gap-sm" style="margin-top:12px"><a class="btn primary" href="ai-lab.html?exp=${encodeURIComponent(c.experimentId || '')}">${UI.icon('ai')}Открыть в AI Lab</a></div>
       <h4 style="margin:16px 0 8px">История попыток по ячейке ${UI.esc(c.cell || '')}</h4><div id="ai-cell-hist"><div class="state-loading"><span class="spinner"></span>Загрузка…</div></div>`
    );
    const box = UI.qs('#ai-cell-hist');
    try {
      const h = await API.http.aiCellHistory(c.cell);
      const items = (h && (h.experiments || h.history || h.cards || h.attempts)) || [];
      box.innerHTML = items.length
        ? `<div class="list">${items.map(e => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(e.name || e.experiment_id || '')}</div><div class="row-sub">${UI.esc(e.ai_status_label || e.status || '')} · ${fmtDate(e.updated_at_utc || e.created_at_utc || '')}</div></div></div>`).join('')}</div>`
        : '<div class="empty-state">История по ячейке пуста.</div>';
    } catch (e) { box.innerHTML = '<div class="empty-state">История недоступна.</div>'; }
  }

  function openArchiveDrawer() {
    const archivedProfiles = profiles.filter(p => p.status === 'archived' || p.status === 'rejected' || p.lifecycle === 'failed_archived');
    UI.drawer(
      `<div class="tb-title"><span class="tb-kicker">do-not-recreate реестр · ${archive.length}</span><span class="tb-h1">Архив и отклонённые</span></div>`,
      `<div class="seg" id="arc-tabs"><button class="active" data-t="prod">Production (${archivedProfiles.length})</button><button data-t="ai">AI Lab (${aiCards.length})</button><button data-t="reg">Реестр (${archive.length})</button></div><div id="arc-body" style="margin-top:12px"></div>`
    );
    function tableHtml(list) {
      if (!list.length) return '<div class="empty-state">Пусто.</div>';
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Слот</th><th>Стратегия</th><th>Инстр.</th><th>Причина</th></tr></thead><tbody>${list.map(c => `<tr class="clickable" data-id="${UI.esc(c.id)}"><td class="mono muted">${UI.esc(c.cell || '')}</td><td><div class="cell-strat"><strong>${UI.esc(c.name)}</strong>${c.isAi ? '<span class="badge ai-origin-badge">AI стратегия</span>' : ''}</div></td><td class="mono muted">${UI.esc(c.root || c.instrument || '')}</td><td class="muted" style="font-size:11px;max-width:220px">${UI.esc(c.archiveReason || (c.raw && c.raw.archive_reason) || '')}</td></tr>`).join('')}</tbody></table></div>`;
    }
    function regHtml(entries) {
      if (!entries.length) return '<div class="empty-state">Реестр пуст.</div>';
      return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Имя</th><th>Класс</th><th>Инстр.</th><th>Причина</th></tr></thead><tbody>${entries.map(e => `<tr><td><strong>${UI.esc(e.name || '')}</strong></td><td class="mono muted" style="font-size:10px">${UI.esc(e.strategy_class || '')}</td><td class="mono muted">${UI.esc(e.instrument || '')}</td><td class="muted" style="font-size:11px;max-width:240px">${UI.esc(e.reason || '')}</td></tr>`).join('')}</tbody></table></div>`;
    }
    function renderTab(t) {
      const body = UI.qs('#arc-body');
      body.innerHTML = t === 'prod' ? tableHtml(archivedProfiles) : t === 'ai' ? tableHtml(aiCards) : regHtml(archive);
      UI.qsa('#arc-body tr[data-id]').forEach(tr => tr.onclick = () => openCard(byId(tr.dataset.id)));
    }
    requestAnimationFrame(() => {
      UI.qsa('#arc-tabs button').forEach(b => b.onclick = () => { UI.qsa('#arc-tabs button').forEach(x => x.classList.remove('active')); b.classList.add('active'); renderTab(b.dataset.t); });
      renderTab('prod');
    });
  }

  async function ntCleanup() {
    UI.toast('Анализ NinjaTrader (предпросмотр)…');
    let plan;
    try { plan = await API.http.ninjatraderCleanup({ dry_run: true, include_ai_sandbox: true, include_ref_lib: true }); }
    catch (e) { UI.reportError(e); return; }
    const toRemove = plan.removed || plan.to_quarantine || plan.quarantined || plan.candidates || [];
    const list = Array.isArray(toRemove) ? toRemove : [];
    const n = plan.removed_count != null ? plan.removed_count : (plan.quarantine_count != null ? plan.quarantine_count : list.length);
    UI.drawer('<h3>Очистка NinjaTrader до одобренных</h3>',
      `<p class="muted" style="font-size:12.5px">Будет перенесено в карантин (только из NinjaTrader Custom, репозиторий не трогается): <strong>${n}</strong> классов. Одобренные и базовые движки сохраняются.</p>
       ${list.length ? `<div class="logbox">${UI.esc(list.slice(0, 80).map(x => typeof x === 'string' ? x : (x.class_name || x.name || JSON.stringify(x))).join('\n'))}</div>` : '<div class="empty-state">Нечего переносить — NinjaTrader уже чист.</div>'}
       <div class="flex gap-sm" style="margin-top:14px"><button class="btn danger" id="cl-exec" ${n ? '' : 'disabled'}>Выполнить очистку</button><button class="btn ghost" data-close-drawer>Отмена</button></div>
       <p class="muted" style="font-size:11px;margin-top:8px">После очистки нажмите F5 в NinjaScript Editor.</p>`);
    requestAnimationFrame(() => {
      const ex = UI.qs('#cl-exec');
      if (ex) ex.onclick = async () => {
        if (!confirm(`Выполнить очистку? ${n} классов будут перенесены в карантин.`)) return;
        ex.disabled = true;
        try { await API.http.ninjatraderCleanup({ dry_run: false, include_ai_sandbox: true, include_ref_lib: true }); UI.toast('Очистка выполнена. Нажмите F5 в NinjaTrader.'); UI.closeDrawer(); }
        catch (e) { UI.reportError(e); ex.disabled = false; }
      };
    });
  }

  function wireControls() {
    UI.qsa('#origin button').forEach(b => b.onclick = () => { UI.qsa('#origin button').forEach(x => x.classList.remove('active')); b.classList.add('active'); curOrigin = b.dataset.o; renderKanban(); });
    UI.qsa('#frequency-filter button').forEach(b => b.onclick = () => { UI.qsa('#frequency-filter button').forEach(x => x.classList.remove('active')); b.classList.add('active'); curFrequency = b.dataset.frequency; renderKanban(); });
    UI.qs('#hide-rejected').onchange = renderMatrix;
    UI.qs('#rejected-btn').onclick = openArchiveDrawer;
    UI.qs('#add-root-btn').onclick = openAddRoot;
    UI.qs('#add-cell-btn').onclick = openAddCell;
    UI.pageActions(`<button class="btn sm" id="pa-cleanup">${UI.icon('eraser')}Очистить NinjaTrader</button>`);
    const cb = UI.qs('#pa-cleanup'); if (cb) cb.onclick = ntCleanup;
  }
});
