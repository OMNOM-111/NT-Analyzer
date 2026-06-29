/* AI Strategy Lab — реальная интеграция (/api/ai-lab/*). CSP-safe (external). */
UI.ready(async function () {
  let lmHealth = null, runStatus = null, summary = null, scoreMap = {}, activityExp = null, activitySince = 0, activityRows = [];
  const STATUS_BADGE = { rejected: 'failed', candidate: 'trial', champion: 'live', portfolio_contributor: 'live', running: 'running', in_progress: 'running' };
  const fmtDate = (iso) => { try { return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso || ''; } };
  const statusBadge = (st) => STATUS_BADGE[st] || (String(st).includes('compile') ? 'failed' : 'archived');
  const statusToCell = (st) => {
    if (st === 'running' || st === 'in_progress') return 'running';
    if (st === 'portfolio_contributor' || st === 'champion') return 'champion';
    if (st === 'candidate') return 'candidate';
    if (String(st).includes('compile')) return 'compileFail';
    return 'rejected';
  };

  const kpiBox = UI.qs('#ai-kpis');
  UI.renderLoading(kpiBox, 'Загрузка AI Lab…');
  async function loadSummary() {
    try { summary = await API.http.aiSummary({ signal: UI.signal() }); }
    catch (e) { if (e.name !== 'AbortError') UI.renderError(kpiBox, e, () => location.reload()); return false; }
    scoreMap = {}; (summary.top || []).forEach(t => { if (t.experiment_id) scoreMap[t.experiment_id] = t.score; });
    const t = summary.totals || {};
    kpiBox.innerHTML = [
      { label: 'Эксперименты', val: t.experiments || 0, icon: 'flask', cls: '' },
      { label: 'В работе', val: t.running_jobs || 0, icon: 'cpu', cls: 'info' },
      { label: 'Кандидаты', val: t.candidates || 0, icon: 'target', cls: 'warn' },
      { label: 'Чемпионы', val: t.champions || 0, icon: 'check', cls: 'pos' },
      { label: 'Отклонено', val: t.rejects || 0, icon: 'close', cls: 'neg' },
    ].map(k => `<div class="kpi ${k.cls}"><div class="kpi-top"><span class="kpi-label">${k.label}</span><span class="kpi-ic">${UI.icon(k.icon)}</span></div><div class="kpi-val">${k.val}</div></div>`).join('');
    return true;
  }

  // ---- LM Studio + bootstrap ----
  async function refreshLm() {
    try { lmHealth = await API.http.aiLmStudioHealth(); }
    catch (e) { lmHealth = { available: false, ready: false, run_allowed: false, message_ru: 'статус недоступен' }; }
    const badge = UI.qs('#lm-badge');
    badge.className = 'badge ' + (lmHealth.run_allowed ? 'live' : lmHealth.available ? 'trial' : 'failed');
    badge.innerHTML = `<span class="dot"></span>LM Studio: ${lmHealth.ready ? 'модель загружена' : lmHealth.run_allowed ? 'standby · готова' : lmHealth.available ? 'сервер доступен' : 'офлайн'}`;
    const panel = UI.qs('#lm-panel');
    if (lmHealth.run_allowed) {
      panel.innerHTML = `<div class="finance-note"><strong>Контур готов к запуску.</strong><br>${UI.esc(lmHealth.message_ru || (lmHealth.ready ? 'Модель загружена.' : 'Нужная модель загрузится автоматически по запросу.'))}</div>`;
    } else {
      panel.innerHTML = `<div class="state-error" style="margin:0"><div><div class="se-title">LM Studio не готова</div><div class="se-msg">${UI.esc(lmHealth.message_ru || 'Запустите LM Studio (порт 1234).')}</div></div></div>
        <div class="flex gap-sm"><button class="btn sm" id="lm-boot">Запустить окружение</button><button class="btn sm ghost" id="lm-check">Проверить</button></div>`;
      const boot = UI.qs('#lm-boot'); if (boot) boot.onclick = bootstrap;
      const chk = UI.qs('#lm-check'); if (chk) chk.onclick = async () => { UI.toast('Проверка LM Studio…'); try { await API.http.aiLmReadiness({ force: 1 }); } catch (e) { } refreshLm(); };
    }
    updateLaunchEnabled();
  }
  async function bootstrap() {
    if (!confirm('Запустить окружение AI Lab (NinjaTrader + LM Studio + сервер моделей)?')) return;
    try { await UI.action('Запуск окружения AI Lab', () => API.http.aiBootstrapStart({ load_models: true, wait_readiness: false }), 'Окружение запускается — проверяю готовность'); }
    catch (e) { return; }
    setTimeout(refreshLm, 4000);
  }

  // ---- run controls ----
  function runActive() {
    return AuroraDomain.aiRunIsActive(runStatus);
  }
  function updateLaunchEnabled() {
    const launch = UI.qs('#ai-launch');
    if (runActive()) { launch.disabled = false; launch.title = ''; return; }
    const allowed = lmHealth && lmHealth.run_allowed;
    launch.disabled = !allowed;
    launch.title = allowed ? '' : 'LM Studio не готова — сначала запустите окружение';
  }
  async function refreshRun() {
    try {
      const [r, current] = await Promise.all([API.http.aiRunStatus(), API.http.aiCurrent().catch(() => ({ current: null }))]);
      runStatus = AuroraDomain.mergeAiRunStatus(r, current);
    } catch (e) { runStatus = null; }
    const active = runActive();
    const badge = UI.qs('#ai-run-badge');
    badge.className = 'badge ' + (active ? 'running' : 'archived');
    const phase = runStatus && (runStatus.current_experiment_status || runStatus.status || (runStatus.current && runStatus.current.status));
    badge.innerHTML = `<span class="dot"></span>${active ? `Цикл активен${phase ? ' · ' + UI.esc(phase) : ''}` : 'Цикл не запущен'}`;
    const launch = UI.qs('#ai-launch');
    if (active) {
      launch.className = 'btn danger'; launch.style.width = '100%'; launch.style.justifyContent = 'center';
      launch.innerHTML = UI.icon('stop') + 'Остановить цикл'; launch.onclick = stopRun;
      const strategyTotal = Number(runStatus.strategy_count || 1);
      const iterationTotal = Number(runStatus.iterations_per_strategy || 1);
      const strategyIndex = Math.max(1, Number(runStatus.strategy_idx || 1));
      const iterationIndex = Math.max(1, Number(runStatus.iteration_idx || 1));
      const completedUnits = (strategyIndex - 1) * iterationTotal + (iterationIndex - 1);
      const derivedPct = completedUnits / Math.max(1, strategyTotal * iterationTotal) * 100;
      const pct = runStatus.progress_pct != null ? runStatus.progress_pct : (runStatus.progress != null ? runStatus.progress : derivedPct);
      UI.qs('#ai-prog').style.width = Math.min(100, pct) + '%';
      const cur = runStatus.current_experiment_id || runStatus.experiment_id || (runStatus.current && runStatus.current.experiment_id);
      UI.qs('#ai-prog-label').textContent = [runStatus.phase || phase || 'выполняется', cur, `стратегия ${strategyIndex}/${strategyTotal}`, `итерация ${iterationIndex}/${iterationTotal}`].filter(Boolean).join(' · ');
      renderRunMeta(cur, strategyIndex, strategyTotal, iterationIndex, iterationTotal);
      if (cur) await loadActivity(cur);
    } else {
      launch.className = 'btn primary'; launch.style.width = '100%'; launch.style.justifyContent = 'center';
      launch.innerHTML = UI.icon('play') + 'Запустить цикл'; launch.onclick = startRun;
      UI.qs('#ai-prog').style.width = '0%';
      UI.qs('#ai-prog-label').textContent = 'нет активного цикла';
      UI.qs('#ai-run-meta').innerHTML = '<div class="empty-state" style="grid-column:1/-1;padding:12px">Активного run нет.</div>';
    }
    updateLaunchEnabled();
  }

  function renderRunMeta(experimentId, strategyIndex, strategyTotal, iterationIndex, iterationTotal) {
    const started = runStatus && runStatus.started_utc;
    const elapsed = started ? Math.max(0, Math.round((Date.now() - new Date(started).getTime()) / 60000)) : null;
    const last = activityRows.length ? activityRows[activityRows.length - 1] : null;
    const lastAt = last && (last.ts || last.timestamp_utc);
    const staleSec = lastAt ? Math.max(0, Math.round((Date.now() - new Date(lastAt).getTime()) / 1000)) : null;
    const rows = [
      ['Run', runStatus.run_id || '—', 'mono'],
      ['Эксперимент', experimentId || '—', 'mono'],
      ['Прогресс', `${strategyIndex}/${strategyTotal} · ${iterationIndex}/${iterationTotal}`, ''],
      ['Время / heartbeat', `${elapsed == null ? '—' : elapsed + ' мин'}${staleSec == null ? '' : ' · ' + staleSec + ' сек назад'}`, staleSec != null && staleSec > 90 ? 'warn' : ''],
    ];
    UI.qs('#ai-run-meta').innerHTML = rows.map(row => `<div class="kpi"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm ${row[2]}">${UI.esc(row[1])}</div></div>`).join('');
  }
  async function startRun() {
    if (runActive()) { UI.toast('Цикл уже активен: ' + (runStatus.run_id || runStatus.experiment_id || '')); return; }
    if (!(lmHealth && lmHealth.run_allowed)) { UI.toast('LM Studio не готова — сначала запустите окружение'); return; }
    const iterVal = UI.qs('#ai-iter').value;
    const body = {
      target_root: UI.qs('#ai-root').value || undefined,
      capital: parseFloat(UI.qs('#ai-capital').value) || undefined,
      goal: UI.qs('#ai-goal').value.trim() || undefined,
      strategy_count: parseInt(UI.qs('#ai-count').value, 10) || 3,
      iterations_per_strategy: iterVal ? parseInt(iterVal, 10) : undefined,
      iterations_unlimited: iterVal === '',
    };
    if (!confirm(`Запустить цикл AI Lab? Инструмент: ${body.target_root || 'авто'}, стратегий: ${body.strategy_count}.`)) return;
    UI.qs('#ai-launch').disabled = true;
    try { await API.http.aiRun(body); UI.toast('Цикл запущен'); }
    catch (e) { if (e.status === 409) UI.toast('Запуск заблокирован: ' + (e.message || 'LM Studio / занятость')); else UI.reportError(e); }
    refreshRun();
  }
  async function stopRun() {
    if (!confirm('Остановить текущий цикл AI Lab?')) return;
    try { await API.http.aiRunCancel({ run_id: runStatus && runStatus.run_id }); UI.toast('Запрошена остановка цикла'); }
    catch (e) { UI.reportError(e); }
    refreshRun();
  }

  function fmtLogLine(l) {
    if (typeof l === 'string') return l;
    const ts = String(l.ts || l.timestamp || l.timestamp_utc || '').slice(11, 19);
    const stage = l.stage_ru || l.stage || l.phase || l.source || '';
    const action = l.action_ru || l.action || l.event || l.message || l.text || '';
    const reason = l.reason_ru || l.reason || '';
    const model = l.selected_model || l.model || '';
    return `[${ts}] ${stage}: ${action}${model ? ` · ${model}` : ''}${reason ? ` · ${reason}` : ''}`.trim();
  }

  async function loadResearchAnalytics() {
    const body = UI.qs('#ai-performance-body');
    body.innerHTML = '<tr><td colspan="7"><div class="state-loading"><span class="spinner"></span>Загрузка аналитики…</div></td></tr>';
    try {
      const [performance, calendar, compile] = await Promise.all([
        API.http.aiPerformance({ signal: UI.signal() }),
        API.http.aiCalendar({ signal: UI.signal() }),
        API.http.aiCompileSourceStatus({ signal: UI.signal() }),
      ]);
      const rows = (performance.rows || []).slice().sort((a, b) => Number(b.ai_arbitration_score || 0) - Number(a.ai_arbitration_score || 0));
      UI.qs('#ai-performance-sub').textContent = `${rows.length} экспериментов · post-commission метрики`;
      body.innerHTML = rows.length ? rows.slice(0, 80).map(row => `<tr><td><strong>${UI.esc(row.class_name || row.experiment_id)}</strong><div class="muted mono" style="font-size:10px">${UI.esc(row.experiment_id || '')}</div></td><td class="mono">${UI.esc(row.target_root || '')}</td><td class="num">${row.pf_after_commission != null ? Number(row.pf_after_commission).toFixed(2) : '—'}</td><td class="num ${UI.pnlClass(row.dd_after_commission || 0)}">${row.dd_after_commission != null ? UI.money(row.dd_after_commission) : '—'}</td><td class="num ${UI.pnlClass(row.avg_per_month || 0)}">${row.avg_per_month != null ? UI.money(row.avg_per_month, { sign: true }) : '—'}</td><td class="num">${row.years_tested != null ? Number(row.years_tested).toFixed(2) : '—'}</td><td><span class="badge ${row.portfolio_eligible ? 'live' : 'failed'}">${row.portfolio_eligible ? 'допущен' : UI.esc((row.portfolio_blockers || [row.status || 'нет']).join(' · '))}</span></td></tr>`).join('') : '<tr><td colspan="7"><div class="empty-state">История метрик пуста.</div></td></tr>';
      const months = calendar.by_relative_month || [];
      const chartBox = UI.qs('#ai-calendar-chart');
      UI.qs('#ai-calendar-sub').textContent = `${months.length} относительных окон`;
      if (months.length) {
        chartBox.innerHTML = '<canvas style="height:240px"></canvas>';
        Chart.bars(chartBox.querySelector('canvas'), months.map(row => ({ label: row.month, tooltipLabel: `Месяц ${row.month}`, value: row.ai_total_pnl || 0 })), { money: true, height: 240 });
      } else UI.renderEmpty(chartBox, 'Календарных окон пока нет.');
      const source = compile.last_emitted_source || (compile.compile_errors_txt && compile.compile_errors_txt.exists ? 'CompileErrors.txt' : 'trace NinjaTrader');
      UI.qs('#ai-compile-source').innerHTML = `<strong>Источник ошибок компиляции:</strong> ${UI.esc(source || 'ещё не определён')} · проверено ${UI.esc(fmtDate(compile.checked_at_utc))} · передано событий: ${compile.total_emitted || 0}.`;
    } catch (e) {
      if (e.name !== 'AbortError') body.innerHTML = `<tr><td colspan="7"><div class="empty-state">Аналитика недоступна: ${UI.esc(e.message)}</div></td></tr>`;
    }
  }
  async function loadModelPerformance() {
    const modelBody = UI.qs('#ai-model-body');
    modelBody.innerHTML = '<tr><td colspan="6"><div class="state-loading"><span class="spinner"></span>Чтение model audit...</div></td></tr>';
    let doc;
    try { doc = await API.http.aiModelPerformance({ days: 30 }, { signal: UI.signal() }); }
    catch (error) {
      if (error.name !== 'AbortError') modelBody.innerHTML = '<tr><td colspan="6"><div class="empty-state">Телеметрия станет доступна после безопасного перезапуска backend.</div></td></tr>';
      return;
    }
    const models = doc.models || [];
    const roles = doc.roles || [];
    const totalTokens = models.reduce((sum, row) => sum + Number(row.total_tokens || 0), 0);
    const totalErrors = models.reduce((sum, row) => sum + Number(row.errors || 0), 0);
    const avgLatency = models.reduce((sum, row) => sum + Number(row.avg_latency_sec || 0) * Number(row.requests || 0), 0) / Math.max(1, Number(doc.requests || 0));
    UI.qs('#ai-model-sub').textContent = `${doc.requests || 0} запросов · ${doc.log_files || 0} файлов аудита · окно ${doc.window_days || 30} дней`;
    UI.qs('#ai-model-kpis').innerHTML = [
      ['Запросы к моделям', doc.requests || 0, ''],
      ['Ошибки', totalErrors, totalErrors ? 'neg' : 'pos'],
      ['Средняя задержка', `${avgLatency.toFixed(1)} сек`, 'info'],
      ['Токены (сообщены)', totalTokens ? totalTokens.toLocaleString('ru-RU') : 'нет usage', 'warn'],
    ].map(row => `<div class="kpi"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm ${row[2]}">${row[1]}</div></div>`).join('');
    modelBody.innerHTML = models.length ? models.map(row => `<tr><td><strong>${UI.esc(row.model)}</strong><div class="row-sub">${row.experiment_count || 0} экспериментов</div></td><td class="num">${row.requests || 0}</td><td class="num ${Number(row.success_rate_pct || 0) < 90 ? 'warn' : 'pos'}">${row.success_rate_pct == null ? '—' : UI.pct(Number(row.success_rate_pct))}</td><td class="num">${row.avg_latency_sec == null ? '—' : `${row.avg_latency_sec}s / ${row.p95_latency_sec}s`}</td><td class="num">${row.accepted_experiments || 0}/${row.terminal_experiments || 0}<div class="row-sub">score ${row.avg_arbitration_score == null ? '—' : row.avg_arbitration_score}</div></td><td class="num">${row.tokens_reported ? Number(row.total_tokens || 0).toLocaleString('ru-RU') : '—'}</td></tr>`).join('') : '<tr><td colspan="6"><div class="empty-state">Запросов к моделям пока нет.</div></td></tr>';
    UI.qs('#ai-role-stats').innerHTML = roles.length ? roles.map(row => `<tr><td><strong>${UI.esc(row.role)}</strong></td><td class="num">${row.requests || 0}</td><td class="num ${row.errors ? 'neg' : ''}">${row.errors || 0}</td><td class="num">${row.success_rate_pct == null ? '—' : UI.pct(Number(row.success_rate_pct))}</td><td class="num">${row.avg_latency_sec == null ? '—' : `${row.avg_latency_sec} сек`}</td><td class="num">${row.experiment_count || 0}</td></tr>`).join('') : '<tr><td colspan="6"><div class="empty-state">Статистика ролей пуста.</div></td></tr>';
    const chartBox = UI.qs('#ai-model-chart');
    if (models.length) {
      chartBox.innerHTML = '<canvas style="height:230px"></canvas>';
      Chart.bars(chartBox.querySelector('canvas'), models.map(row => ({ label: String(row.model).split('/').pop().slice(0, 10), tooltipLabel: String(row.model), tooltipDetail: `Ошибок: ${Number(row.errors || 0)}`, value: Number(row.requests || 0), color: Number(row.errors || 0) ? '#fcc55a' : '#34d399' })), { height: 230 });
    } else UI.renderEmpty(chartBox, 'Нет модельной телеметрии.');
  }
  function renderRoleTimeline(rows, target) {
    const box = target || UI.qs('#ai-role-timeline');
    if (!box) return;
    const visible = (rows || []).slice(-8);
    box.innerHTML = visible.length ? visible.map(row => {
      const stage = row.stage_ru || row.stage || row.phase || 'процесс';
      const action = row.action_ru || row.action || row.message || 'событие';
      const detail = [row.selected_model || row.model, row.reason_ru || row.reason, row.class_name].filter(Boolean).join(' · ');
      const ts = String(row.ts || row.timestamp_utc || '').slice(11, 19);
      return `<div class="role-step"><span class="stage">${UI.esc(stage)}</span><span class="task" title="${UI.esc(detail || action)}">${UI.esc(action)}${detail ? ` · ${UI.esc(detail)}` : ''}</span><span class="time">${UI.esc(ts)}</span></div>`;
    }).join('') : '<div class="empty-state" style="padding:12px">Нет активных этапов. Выберите эксперимент в истории для подробного журнала.</div>';
  }
  async function loadActivity(expId) {
    if (activityExp !== expId) { activityExp = expId; activitySince = 0; activityRows = []; UI.qs('#ai-log').textContent = ''; }
    try {
      const a = await API.http.aiExperimentActivity(expId, { since: activitySince, limit: 200 });
      const lines = a.entries || a.lines || a.events || a.activity || [];
      if (lines.length) {
        const log = UI.qs('#ai-log');
        log.textContent += lines.map(fmtLogLine).join('\n') + '\n';
        log.scrollTop = log.scrollHeight;
        activityRows = activityRows.concat(lines).slice(-200);
        renderRoleTimeline(activityRows);
        if (runActive()) renderRunMeta(expId, Math.max(1, Number(runStatus.strategy_idx || 1)), Math.max(1, Number(runStatus.strategy_count || 1)), Math.max(1, Number(runStatus.iteration_idx || 1)), Math.max(1, Number(runStatus.iterations_per_strategy || 1)));
        activitySince = a.next_line || a.last_line || (activitySince + lines.length);
      }
    } catch (e) { /* ignore */ }
  }

  // ---- experiments ----
  async function loadExperiments() {
    let doc;
    try { doc = await API.http.aiExperiments({ limit: 300 }, { signal: UI.signal() }); } catch (e) { return; }
    const exps = doc.experiments || [];
    UI.qs('#ai-matrix').innerHTML = exps.map(e => `<div class="ai-cell ${statusToCell(e.status)}" data-id="${UI.esc(e.experiment_id)}" title="${UI.esc(e.class_name || e.experiment_id)} · ${UI.esc(e.status)}"></div>`).join('');
    UI.qsa('#ai-matrix .ai-cell').forEach(el => el.onclick = () => openExp(el.dataset.id));

    const cands = exps.filter(e => ['candidate', 'champion', 'portfolio_contributor'].includes(e.status));
    UI.qs('#port-body').innerHTML = cands.length ? cands.map(e => `<tr class="clickable" data-id="${UI.esc(e.experiment_id)}"><td><strong>${UI.esc(e.class_name || e.experiment_id)}</strong></td><td class="mono muted">${UI.esc(e.target_root || '')}</td><td class="num">${scoreMap[e.experiment_id] != null ? Number(scoreMap[e.experiment_id]).toFixed(1) : '—'}</td><td><span class="badge ${statusBadge(e.status)}">${UI.esc(e.status)}</span></td></tr>`).join('') : '<tr><td colspan="4"><div class="empty-state">Кандидатов нет.</div></td></tr>';
    UI.qsa('#port-body tr[data-id]').forEach(tr => tr.onclick = () => openExp(tr.dataset.id));

    UI.qs('#exp-count').textContent = exps.length + ' экспериментов';
    UI.qs('#exp-body').innerHTML = exps.map(e => `<tr class="clickable" data-id="${UI.esc(e.experiment_id)}"><td class="mono muted" style="font-size:10px">${UI.esc(e.experiment_id)}</td><td class="muted">${fmtDate(e.created_at_utc)}</td><td><strong>${UI.esc(e.class_name || '')}</strong></td><td class="mono muted">${UI.esc(e.target_root || '')}</td><td class="muted">${UI.esc(e.family || '')}</td><td class="num">${scoreMap[e.experiment_id] != null ? Number(scoreMap[e.experiment_id]).toFixed(1) : '—'}</td><td><span class="badge ${statusBadge(e.status)}">${UI.esc(e.status)}</span></td></tr>`).join('');
    UI.qsa('#exp-body tr[data-id]').forEach(tr => tr.onclick = () => openExp(tr.dataset.id));
  }

  async function openExp(id) {
    UI.drawer(`<h3 style="margin:0">${UI.esc(id)}</h3>`, '<div class="state-loading"><span class="spinner"></span>Загрузка эксперимента…</div>');
    const body = UI.qs('.drawer-b');
    let e;
    try { e = await API.http.aiExperiment(id); } catch (err) { UI.renderError(body, err, () => openExp(id)); return; }
    body.innerHTML = `
      <div class="tb-title" style="margin-bottom:10px"><span class="tb-kicker">${UI.esc([e.ai_cell_id, e.target_root, e.family].filter(Boolean).join(' · '))}</span><span class="tb-h1">${UI.esc(e.class_name || id)}</span></div>
      <div class="flex wrap gap-sm"><span class="badge ${statusBadge(e.status)}">${UI.esc(e.status)}</span><span class="tag">создан ${fmtDate(e.created_at_utc)}</span>${e.primary_capital ? `<span class="tag">капитал $${e.primary_capital}</span>` : ''}${scoreMap[id] != null ? `<span class="tag">score ${Number(scoreMap[id]).toFixed(1)}</span>` : ''}</div>
      ${e.hypothesis ? `<section class="panel" style="margin-top:12px"><div class="panel-h"><h2>Гипотеза</h2></div><div class="panel-b"><p style="font-size:12.5px;color:var(--tx-2);line-height:1.55">${UI.esc(e.hypothesis)}</p></div></section>` : ''}
      <h4 style="margin:14px 0 6px">Этапы и роли</h4><div class="role-timeline" id="ed-roles"></div>
      <h4 style="margin:14px 0 6px">Журнал работы</h4><pre class="logbox" id="ed-log">загрузка…</pre>
      <details style="margin-top:12px"><summary>Технические данные эксперимента</summary><pre class="logbox">${UI.esc(JSON.stringify({ memory_intake: e.memory_intake, analysis: e.analysis, decision: e.decision, portfolio: e.portfolio, lineage: e.lineage }, null, 2))}</pre></details>
      <div class="flex gap-sm" style="margin-top:12px">${e.class_name ? `<a class="btn" href="strategies.html?strategy=${encodeURIComponent(e.class_name)}">${UI.icon('strategies')}В портфеле стратегий</a>` : ''}${e.status === 'running' ? '<button class="btn danger" id="ed-cancel">Отменить</button>' : ''}</div>`;
    try { const a = await API.http.aiExperimentActivity(id, { since: 0, limit: 500 }); const lines = a.entries || a.lines || a.events || a.activity || []; UI.qs('#ed-log').textContent = lines.length ? lines.map(fmtLogLine).join('\n') : 'нет записей в журнале'; renderRoleTimeline(lines, UI.qs('#ed-roles')); }
    catch (err) { UI.qs('#ed-log').textContent = 'журнал недоступен'; }
    const cancel = UI.qs('#ed-cancel');
    if (cancel) cancel.onclick = async () => { if (!confirm('Отменить эксперимент ' + id + '?')) return; try { await API.http.aiCancel({ experiment_id: id }); UI.toast('Отмена запрошена'); UI.closeDrawer(); refreshRun(); } catch (er) { UI.reportError(er); } };
  }

  // ---- error memory + lessons ----
  async function loadErrors() {
    try {
      const e = await API.http.aiErrorsSummary({ signal: UI.signal() });
      const patterns = e.patterns || [];
      UI.qs('#err-count').textContent = patterns.length + ' паттернов';
      UI.qs('#err-list').innerHTML = patterns.length ? patterns.slice(0, 12).map(p => `<div class="row"><div class="row-main"><div class="row-title" style="font-size:12px">${UI.esc(p.pattern || p.signature || p.message || p.summary || 'ошибка')}</div><div class="row-sub">${UI.esc(p.phase || '')} · ${p.count || p.occurrences || p.total || 0}×</div></div></div>`).join('') : '<div class="empty-state">Паттернов нет.</div>';
      const lessons = e.lessons_recent || [];
      UI.qs('#lesson-count').textContent = (e.lessons_count != null ? e.lessons_count : lessons.length) + ' уроков';
      UI.qs('#lesson-list').innerHTML = lessons.length ? lessons.slice(0, 12).map(l => `<div class="row"><div class="row-main"><div class="row-title" style="font-size:12px">${UI.esc(l.summary || l.text || l.rule || '')}</div><div class="row-sub">${UI.esc(l.source || '')} · ${fmtDate(l.created_at_utc || l.ts || l.timestamp_utc || '')}</div></div></div>`).join('') : '<div class="empty-state">Уроков нет.</div>';
    } catch (e) { /* ignore */ }
  }

  // ---- wire + init ----
  UI.qs('#ai-note-send').onclick = async () => {
    const text = UI.qs('#ai-note').value.trim();
    if (!text) { UI.toast('Введите текст заметки'); return; }
    try { await API.http.aiOperatorNoteGlobal({ text, priority: 'high' }); UI.toast('Заметка сохранена в глобальную память AI'); UI.qs('#ai-note').value = ''; }
    catch (e) { UI.reportError(e); }
  };
  UI.pageActions(`<button class="btn sm" id="ai-research-scan">${UI.icon('search')}Сканировать исследования</button><button class="btn sm" id="ai-unload">${UI.icon('eraser')}Освободить память</button><button class="btn sm" id="ai-sweep">${UI.icon('refresh')}Очистить зависшие</button>`);
  UI.qs('#ai-research-scan').onclick = () => { if (!confirm('Просканировать пользовательские исследования и обновить входной контекст AI Lab?')) return; UI.action('Сканирование исследований', () => API.http.aiUserResearchScan({}), 'Исследования просканированы').then(loadResearchAnalytics).catch(() => {}); };
  UI.qs('#ai-unload').onclick = () => { if (!confirm('Выгрузить модели LM Studio и остановить локальный model server?')) return; UI.action('Выгрузка моделей', () => API.http.aiBootstrapUnload({ stop_server: true }), 'Модели выгружены').then(refreshLm).catch(() => {}); };
  UI.qs('#ai-sweep').onclick = () => { if (!confirm('Пометить эксперименты без heartbeat более 6 часов как cancelled?')) return; UI.action('Проверка зависших экспериментов', () => API.http.aiSweepStale({ stale_after_hours: 6 }), 'Проверка завершена').then(() => { loadSummary(); loadExperiments(); }).catch(() => {}); };

  if (!(await loadSummary())) return;
  await Promise.all([refreshLm(), refreshRun(), loadExperiments(), loadErrors(), loadResearchAnalytics(), loadModelPerformance()]);
  if (!activityRows.length) renderRoleTimeline([]);
  UI.poll(refreshRun, 5000);
  UI.poll(async () => { await loadSummary(); }, 20000);
});
