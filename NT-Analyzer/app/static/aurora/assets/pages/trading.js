/* Центр управления торговлей — реальная интеграция (/api/ops/runtime/*). CSP-safe.
   Команды: paper-only enable/disable_strategy + bounded reconnect_account for
   paper/demo/playback; live-счета блокируются на сервере. */
UI.ready(async function () {
  let accounts = [], controlAccount = '', catalog = [], perfMonth = null, rtTab = 'positions', bridgePaused = false, bridgeOnline = false;
  let historySessions = [], hiddenClasses = [], strategyStartDates = {}, trackedCommandId = '';
  let runtimeStrategies = [], showHiddenStrategies = false;
  let calendarDate = new Date();
  const ymdPT = (ts) => { try { return new Date(ts).toLocaleDateString('en-CA', { timeZone: 'America/Los_Angeles' }); } catch (e) { return ''; } };
  const timePT = (ts) => { try { return new Date(ts).toLocaleTimeString('ru-RU', { timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ''; } };

  // ---------- account band ----------
  async function loadAccounts() {
    const accBox = UI.qs('#acct');
    UI.renderLoading(accBox, 'Загрузка счетов…');
    let doc;
    try { doc = await API.http.runtimeAccounts({ signal: UI.signal() }); }
    catch (e) { if (e.name !== 'AbortError') UI.renderError(accBox, e, loadAccounts); return; }
    accounts = (doc.accounts || doc.online_accounts || []).filter(account => !account.is_system);
    bridgeOnline = !!doc.bridge_online;
    accBox.innerHTML = accounts.length ? accounts.map(accountCard).join('') : '<div class="empty-state">Счета недоступны — мост NinjaTrader офлайн.</div>';
    const sel = UI.qs('#ctrl-account');
    const ctrlable = accounts.filter(a => a.control_allowed && !a.is_live);
    sel.innerHTML = ctrlable.length ? ctrlable.map(a => `<option value="${UI.esc(a.account_name)}">${UI.esc(a.account_name)} · ${UI.esc(a.account_mode || 'paper')}</option>`).join('') : '<option value="">нет paper-счетов</option>';
    const shared = UI.getSelectedAccount();
    if (shared && ctrlable.some(a => a.account_name === shared.account_name)) sel.value = shared.account_name;
    controlAccount = sel.value;
    UI.qs('#ctrl-sub').textContent = doc.bridge_online ? `мост онлайн · ${accounts.length} счетов · стратегии только paper, reconnect modeling доступен` : 'мост офлайн';
    refreshControlActions();
    loadAccountAnalytics();
  }
  function accountCard(a) {
    const connected = String(a.connection_status || '').toLowerCase() === 'connected';
    return `<div class="kpi"><div class="kpi-top"><span class="kpi-label">${UI.esc(a.display_name || a.account_name)}</span><span class="badge ${!connected ? 'archived' : a.is_live ? 'failed' : 'demo'}">${a.is_live ? 'LIVE' : (a.account_mode || 'paper')} · ${connected ? 'подключён' : 'офлайн'}</span></div>
      <div class="kpi-val sm">${UI.money(a.net_liquidation || a.cash_value || 0)}</div>
      <div class="kpi-foot">реализ. <b class="${UI.pnlClass(a.realized_pnl || 0)}">${UI.money(a.realized_pnl || 0, { sign: true })}</b> · нереализ. <b class="${UI.pnlClass(a.unrealized_pnl || 0)}">${UI.money(a.unrealized_pnl || 0, { sign: true })}</b>${a.connection_status ? ' · ' + (connected ? 'подключён' : 'отключён') : ''}</div></div>`;
  }

  async function loadAccountAnalytics() {
    const shared = UI.getSelectedAccount();
    const account = (shared && accounts.find(a => a.account_name === shared.account_name)) || accounts[0] || null;
    const kpis = UI.qs('#account-analytics-kpis');
    const chartBox = UI.qs('#account-pnl-box');
    const ledgerBody = UI.qs('#account-ledger-body');
    if (!account) { UI.renderEmpty(kpis, 'Нет доступного торгового счёта.'); chartBox.innerHTML = ''; ledgerBody.innerHTML = '<tr><td colspan="7"><div class="empty-state">Счёт не выбран.</div></td></tr>'; return; }
    UI.qs('#account-analytics-sub').textContent = `${account.account_name} · ${account.is_live ? 'LIVE' : (account.account_mode || 'paper')}${account.connection_status ? ' · ' + (String(account.connection_status).toLowerCase() === 'connected' ? 'подключён' : 'отключён') : ''}`;
    let perf, history;
    try {
      [perf, history] = await Promise.all([
        API.http.performance({ period: 'month', account: account.account_name }, { signal: UI.signal() }),
        API.http.runtimeAccountHistory({ account: account.account_name, limit: 250 }, { signal: UI.signal() }),
      ]);
    }
    catch (e) { if (e.name !== 'AbortError') UI.renderError(kpis, e, loadAccountAnalytics); return; }
    const summary = perf.summary || {};
    const series = AuroraDomain.tradingSeries(perf.strategies || []);
    const maxDd = series.reduce((m, row) => Math.min(m, row.drawdown), 0);
    kpis.innerHTML = [
      ['Net liquidation', UI.money(account.net_liquidation || 0), ''],
      ['Trading P&L за месяц', UI.money(summary.pnl || 0, { sign: true }), UI.pnlClass(summary.pnl || 0)],
      ['Комиссии', UI.money(summary.commission || 0), 'warn'],
      ['Просадка торговли', UI.money(maxDd), 'neg'],
    ].map(row => `<div class="kpi"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm ${row[2]}">${row[1]}</div></div>`).join('');
    const ledger = (history.accounts || [])[0] || { snapshots: [], events: [] };
    const events = ledger.events || [];
    const pending = events.filter(row => row.classification_status === 'needs_review');
    UI.qs('#cashflow-note').innerHTML = `<strong>Разделение средств:</strong> линия ниже — только накопленный P&amp;L закрытых сделок после комиссии. NetLiq и события средств ведутся отдельно. Необъяснённые изменения никогда автоматически не считаются прибылью или пополнением; сейчас требуют проверки: <strong>${pending.length}</strong>.`;
    renderLedger(account, ledger);
    if (series.length) {
      chartBox.innerHTML = '<canvas id="account-pnl-curve" style="height:240px"></canvas>';
      Chart.pnl(UI.qs('#account-pnl-curve'), series.map(row => row.cumulativeTradingPnl), { money: true, height: 240, labels: series.map(row => row.date) });
    } else UI.renderEmpty(chartBox, 'За выбранный месяц закрытых сделок нет. Баланс не используется как замена P&L.');
  }

  function renderLedger(account, ledger) {
    const events = (ledger.events || []).slice().reverse();
    const snapshots = ledger.snapshots || [];
    const pending = events.filter(row => row.classification_status === 'needs_review').length;
    UI.qs('#account-ledger-sub').textContent = `${account.account_name} · ${snapshots.length} снимков · ${events.length} событий · ${pending} требуют проверки`;
    const body = UI.qs('#account-ledger-body');
    if (!events.length) {
      body.innerHTML = '<tr><td colspan="7"><div class="empty-state">Изменений средств пока не зафиксировано. Наблюдение начинается с первого сохранённого снимка; старые пополнения не восстанавливаются догадками.</div></td></tr>';
      return;
    }
    const labels = { deposit: 'Пополнение', withdrawal: 'Снятие', transfer: 'Перевод', fee: 'Комиссия', unclassified_adjustment: 'Не классифицировано' };
    body.innerHTML = events.map(row => `<tr><td class="muted">${timePT(row.at_utc)}</td><td><span class="badge ${row.classification_status === 'needs_review' ? 'warn' : 'demo'}">${UI.esc(labels[row.kind] || row.kind)}</span></td><td class="num ${UI.pnlClass(row.amount || 0)}">${UI.money(row.amount || 0, { sign: true })}</td><td class="num">${UI.money(row.equity_delta || 0, { sign: true })}</td><td class="num">${UI.money(row.trading_pnl_delta || 0, { sign: true })}</td><td class="muted">${UI.esc(row.note || '')}</td><td>${row.classification_status === 'needs_review' ? `<button class="btn sm" data-classify-event="${UI.esc(row.event_id)}">Классифицировать</button>` : ''}</td></tr>`).join('');
    UI.qsa('#account-ledger-body [data-classify-event]').forEach(button => button.onclick = () => openClassification(account.account_name, button.dataset.classifyEvent));
  }

  function openClassification(accountName, eventId) {
    UI.drawer('<h3>Классифицировать изменение средств</h3>', `
      <p class="muted">Выберите тип только по подтверждённым данным брокера. Классификация не изменяет торговый P&amp;L.</p>
      <label class="field-label" for="ledger-kind">Тип события</label>
      <select class="field" id="ledger-kind"><option value="deposit">Пополнение</option><option value="withdrawal">Снятие</option><option value="transfer">Перевод</option><option value="fee">Комиссия</option></select>
      <label class="field-label" for="ledger-note">Основание</label>
      <textarea class="field" id="ledger-note" rows="3" placeholder="Например: подтверждено выпиской брокера"></textarea>
      <div class="flex gap-sm" style="margin-top:12px"><button class="btn primary" id="ledger-save">Сохранить</button><button class="btn ghost" data-close-drawer>Отмена</button></div>`);
    UI.qs('#ledger-save').onclick = async () => {
      const note = UI.qs('#ledger-note').value.trim();
      if (!note) { UI.toast('Укажите основание классификации'); return; }
      try {
        await API.http.classifyAccountEvent({ account_name: accountName, event_id: eventId, kind: UI.qs('#ledger-kind').value, actor: 'ui', note });
        UI.closeDrawer(); UI.toast('Событие классифицировано'); loadAccountAnalytics();
      } catch (e) { UI.reportError(e); }
    };
  }

  function refreshControlActions() {
    const reconnect = UI.qs('#ctrl-reconnect');
    if (!reconnect) return;
    const account = accounts.find(a => a.account_name === controlAccount) || null;
    const connected = String(account && account.connection_status || '').toLowerCase() === 'connected';
    const canReconnect = !!account && !account.is_live && !!bridgeOnline && !connected;
    reconnect.disabled = !canReconnect;
    reconnect.title = canReconnect
      ? `Переподключить paper/demo/playback соединение для ${account.account_name}`
      : !bridgeOnline ? 'Мост NinjaTrader офлайн'
      : !account ? 'Выберите paper/demo/playback счёт'
      : 'Счёт уже подключён';
  }

  function selectedLedgerAccount() {
    const shared = UI.getSelectedAccount();
    return (shared && accounts.find(account => account.account_name === shared.account_name)) || accounts[0] || null;
  }

  function openManualLedgerEvent() {
    const account = selectedLedgerAccount();
    if (!account) { UI.toast('Счёт не выбран'); return; }
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    UI.drawer('<h3>Подтверждённое движение средств</h3>', `
      <div class="finance-note">Операция попадёт только в журнал средств счёта ${UI.esc(account.account_name)} и не будет учтена как прибыль стратегии.</div>
      <div class="grid cols-2">
        <label class="field"><span>Тип</span><select id="ledger-add-kind"><option value="deposit">Пополнение</option><option value="withdrawal">Снятие</option><option value="transfer">Перевод</option><option value="fee">Комиссия</option></select></label>
        <label class="field"><span>Сумма, USD</span><input id="ledger-add-amount" type="number" step="0.01" min="0.01" required></label>
        <label class="field"><span>Дата и время</span><input id="ledger-add-time" type="datetime-local" value="${local}"></label>
        <label class="field"><span>ID операции брокера</span><input id="ledger-add-source-id" placeholder="необязательно, защищает от дублей"></label>
      </div>
      <label class="field"><span>Основание / комментарий</span><textarea id="ledger-add-note" rows="3" placeholder="Например: подтверждено выпиской брокера"></textarea></label>
      <div class="flex gap-sm"><button class="btn primary" id="ledger-add-save">Сохранить</button><button class="btn ghost" data-close-drawer>Отмена</button></div>`);
    UI.qs('#ledger-add-save').onclick = async () => {
      const amount = Number(UI.qs('#ledger-add-amount').value);
      const note = UI.qs('#ledger-add-note').value.trim();
      if (!Number.isFinite(amount) || amount <= 0) { UI.toast('Укажите положительную сумму'); return; }
      if (!note) { UI.toast('Укажите основание операции'); return; }
      const at = UI.qs('#ledger-add-time').value;
      try {
        const result = await API.http.addAccountEvent({
          account_name: account.account_name,
          kind: UI.qs('#ledger-add-kind').value,
          amount,
          at_utc: at ? new Date(at).toISOString() : null,
          source_id: UI.qs('#ledger-add-source-id').value.trim(),
          source: 'manual_ui', actor: 'ui', note,
        });
        UI.closeDrawer();
        UI.toast(result.duplicate ? 'Операция уже была импортирована' : 'Движение средств сохранено');
        loadAccountAnalytics();
      } catch (error) { UI.reportError(error); }
    };
  }

  function parseLedgerCsv(text) {
    const records = [];
    let row = [], field = '', quoted = false;
    for (let index = 0; index <= text.length; index += 1) {
      const char = text[index] || '\n';
      if (quoted) {
        if (char === '"' && text[index + 1] === '"') { field += '"'; index += 1; }
        else if (char === '"') quoted = false;
        else field += char;
      } else if (char === '"') quoted = true;
      else if (char === ',') { row.push(field.trim()); field = ''; }
      else if (char === '\n') { row.push(field.trim()); field = ''; if (row.some(Boolean)) records.push(row); row = []; }
      else if (char !== '\r') field += char;
    }
    if (records.length < 2) throw new Error('CSV должен содержать заголовок и хотя бы одну операцию');
    const headers = records.shift().map(value => value.replace(/^\uFEFF/, '').toLowerCase());
    const alias = { timestamp: 'at_utc', date: 'at_utc', type: 'kind', id: 'source_id', comment: 'note' };
    const kinds = { deposit: 'deposit', пополнение: 'deposit', withdrawal: 'withdrawal', снятие: 'withdrawal', transfer: 'transfer', перевод: 'transfer', fee: 'fee', комиссия: 'fee' };
    return records.map((values, index) => {
      const raw = {};
      headers.forEach((header, column) => { raw[alias[header] || header] = values[column] || ''; });
      const kind = kinds[String(raw.kind || '').toLowerCase()];
      const amount = Number(String(raw.amount || '').replace(/\s/g, '').replace(',', '.'));
      if (!kind) throw new Error(`Строка ${index + 2}: неизвестный тип операции`);
      if (!Number.isFinite(amount) || amount === 0) throw new Error(`Строка ${index + 2}: неверная сумма`);
      return { at_utc: raw.at_utc, kind, amount, note: raw.note || '', source_id: raw.source_id || '' };
    });
  }

  function openLedgerImport() {
    const account = selectedLedgerAccount();
    if (!account) { UI.toast('Счёт не выбран'); return; }
    let prepared = [];
    UI.drawer('<h3>Импорт выписки CSV</h3>', `
      <div class="finance-note">Счёт: <strong>${UI.esc(account.account_name)}</strong>. Колонки: <span class="mono">at_utc,kind,amount,note,source_id</span>. Типы: deposit, withdrawal, transfer, fee. Импорт не меняет торговый P&amp;L.</div>
      <label class="field"><span>Файл выписки</span><input id="ledger-import-file" type="file" accept=".csv,text/csv"></label>
      <div id="ledger-import-preview"><div class="empty-state">Выберите файл для проверки.</div></div>
      <div class="flex gap-sm"><button class="btn primary" id="ledger-import-save" disabled>Импортировать</button><button class="btn ghost" data-close-drawer>Отмена</button></div>`);
    UI.qs('#ledger-import-file').onchange = async event => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      try {
        prepared = parseLedgerCsv(await file.text());
        const preview = prepared.slice(0, 10);
        UI.qs('#ledger-import-preview').innerHTML = `<div class="finance-note">Проверено строк: <strong>${prepared.length}</strong>${prepared.length > 10 ? ' · показаны первые 10' : ''}</div><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Дата</th><th>Тип</th><th class="num">Сумма</th><th>ID</th></tr></thead><tbody>${preview.map(row => `<tr><td>${UI.esc(row.at_utc || 'текущее время')}</td><td>${UI.esc(row.kind)}</td><td class="num ${UI.pnlClass(row.kind === 'deposit' ? Math.abs(row.amount) : -Math.abs(row.amount))}">${UI.money(row.amount, { sign: true })}</td><td class="mono muted">${UI.esc(row.source_id || '—')}</td></tr>`).join('')}</tbody></table></div>`;
        UI.qs('#ledger-import-save').disabled = false;
      } catch (error) {
        prepared = [];
        UI.qs('#ledger-import-save').disabled = true;
        UI.qs('#ledger-import-preview').innerHTML = `<div class="finance-note neg"><strong>Файл отклонён:</strong> ${UI.esc(error.message)}</div>`;
      }
    };
    UI.qs('#ledger-import-save').onclick = async () => {
      if (!prepared.length) return;
      try {
        const result = await API.http.importAccountEvents({ account_name: account.account_name, rows: prepared, actor: 'ui', source: 'broker_statement_csv' });
        UI.closeDrawer(); UI.toast(`Импортировано: ${result.imported || 0} · дубликатов: ${result.duplicates || 0}`); loadAccountAnalytics();
      } catch (error) { UI.reportError(error); }
    };
  }

  // ---------- control table (runtime strategies) ----------
  async function loadControl() {
    const body = UI.qs('#ctrl-body');
    body.innerHTML = '<tr><td colspan="8"><div class="state-loading"><span class="spinner"></span>Загрузка…</div></td></tr>';
    let doc;
    try { doc = await API.http.runtimeStrategies({ signal: UI.signal() }); }
    catch (e) { if (e.name !== 'AbortError') body.innerHTML = `<tr><td colspan="8" class="muted">Не удалось загрузить: ${UI.esc(e.message)}</td></tr>`; return; }
    runtimeStrategies = (doc.strategies || []).map(row => AuroraDomain.normalizeRuntimeStrategy(row, new Date()));
    if (!runtimeStrategies.length) {
      body.innerHTML = `<tr><td colspan="8"><div class="empty-state">Нет активных стратегий в NinjaTrader.${(doc.warnings && doc.warnings[0]) ? ' ' + UI.esc(doc.warnings[0]) : ''}</div></td></tr>`;
      return;
    }
    renderControlRows();
  }
  function renderControlRows() {
    const body = UI.qs('#ctrl-body');
    const visible = runtimeStrategies.filter(strategy => showHiddenStrategies || (!strategy.hidden && !strategy.external));
    const hiddenCount = runtimeStrategies.length - visible.length;
    const alerts = visible.filter(strategy => AuroraDomain.strategyOperationalState(strategy).severity === 'bad').length;
    UI.qs('#ctrl-sub').textContent = `${visible.length}/${runtimeStrategies.length} стратегий · ${hiddenCount} скрыто/внешних${alerts ? ` · ${alerts} требуют внимания` : ''}`;
    body.innerHTML = visible.length ? visible.map(ctrlRow).join('') : '<tr><td colspan="8"><div class="empty-state">Управляемых стратегий нет. Включите показ скрытых/внешних для диагностики.</div></td></tr>';
    UI.qsa('#ctrl-body button[data-disable]').forEach(b => b.onclick = () => disableStrategy(b.dataset.disable, b.dataset.cls, b.dataset.acct, b.dataset.iid));
    UI.qsa('#ctrl-body tr[data-runtime-detail]').forEach(row => row.onclick = event => {
      if (event.target.closest('button')) return;
      const strategy = runtimeStrategies.find(item => item.runtimeInstanceId === row.dataset.runtimeDetail);
      if (strategy) openRuntimeStrategy(strategy);
    });
  }
  function ctrlRow(s) {
    const state = AuroraDomain.strategyOperationalState(s);
    const badge = state.severity === 'bad' ? 'failed' : state.severity === 'warn' ? 'trial' : state.severity === 'ok' ? 'live' : state.severity === 'info' ? 'demo' : 'archived';
    const identity = s.external ? 'внешняя/runtime-only' : s.registryStatus;
    return `<tr class="clickable" data-runtime-detail="${UI.esc(s.runtimeInstanceId)}"><td><strong>${UI.esc(s.name || s.strategyId)}</strong><div class="row-sub">${UI.esc(identity)} · ${UI.esc(s.timeframe || '')}</div></td><td class="mono muted" style="font-size:10px">${UI.esc(s.className)}</td><td class="mono"><strong>${UI.esc(s.instrument)}</strong><div class="row-sub">${UI.esc(s.tradeWindowLabel)}</div></td><td class="mono muted">${UI.esc(s.accountName)}</td><td>${UI.esc(s.position)}${s.quantity ? ` · ${s.quantity}` : ''}</td><td class="num ${UI.pnlClass(s.realizedPnl)}">${UI.money(s.realizedPnl, { sign: true })}</td><td><span class="badge ${badge}"><span class="dot"></span>${UI.esc(state.label)}</span>${!s.paramsOk ? '<div class="row-sub neg">locked params mismatch</div>' : ''}</td><td>${s.enabled ? `<button class="btn sm danger" data-disable="${UI.esc(s.strategyId)}" data-cls="${UI.esc(s.className)}" data-acct="${UI.esc(s.accountName)}" data-iid="${UI.esc(s.runtimeInstanceId)}">Остановить</button>` : '<span class="muted">—</span>'}</td></tr>`;
  }
  async function openRuntimeStrategy(strategy) {
    UI.drawer(`<h3>${UI.esc(strategy.name || strategy.strategyId)}</h3>`, '<div class="state-loading"><span class="spinner"></span>Загрузка фактической истории...</div>');
    const body = UI.qs('.drawer-b');
    const [perf, history, journal] = await Promise.all([
      API.http.performance({ period: 'year', account: strategy.accountName }).catch(() => null),
      API.http.runtimeStrategyHistory({ runtime_instance_id: strategy.runtimeInstanceId, limit_events: 300, limit_sessions: 100 }).catch(() => ({ events: [], sessions: [] })),
      API.http.opsStrategyJournal(strategy.strategyId).catch(() => ({ rows: [] })),
    ]);
    if (!body || !body.isConnected) return;
    const perfRow = ((perf && perf.strategies) || []).find(row => (row.runtime_instance_ids || []).includes(strategy.runtimeInstanceId) || String(row.strategy_class || '').toLowerCase() === String(strategy.className || '').toLowerCase());
    const sessions = history.sessions || [];
    const events = history.events || [];
    const operating = AuroraDomain.strategyOperationalState(strategy);
    const params = Object.entries(strategy.runtime.params || {});
    const warnings = [].concat(strategy.warnings || [], strategy.errors || []);
    body.innerHTML = `<div class="flex wrap gap-sm"><span class="badge ${operating.severity === 'bad' ? 'failed' : operating.severity === 'ok' ? 'live' : operating.severity === 'warn' ? 'trial' : 'demo'}"><span class="dot"></span>${UI.esc(operating.label)}</span><span class="tag">${UI.esc(strategy.accountName)}</span><span class="tag">${UI.esc(strategy.instrument)}</span><span class="tag">${UI.esc(strategy.tradeWindowLabel)}</span></div>
      <div class="grid cols-4"><div class="kpi"><div class="kpi-label">Позиция</div><div class="kpi-val sm">${UI.esc(strategy.position)} ${strategy.quantity || ''}</div></div><div class="kpi"><div class="kpi-label">P&amp;L сессии</div><div class="kpi-val sm ${UI.pnlClass(strategy.realizedPnl)}">${UI.money(strategy.realizedPnl, { sign: true })}</div></div><div class="kpi"><div class="kpi-label">Trading P&amp;L · год</div><div class="kpi-val sm ${UI.pnlClass(perfRow && perfRow.pnl || 0)}">${perfRow ? UI.money(perfRow.pnl || 0, { sign: true }) : '—'}</div></div><div class="kpi"><div class="kpi-label">Сессий / событий</div><div class="kpi-val sm">${sessions.length} / ${events.length}</div></div></div>
      ${!strategy.paramsOk ? `<div class="finance-note neg"><strong>Стратегия включена с неверными параметрами.</strong> Исправьте: ${UI.esc(strategy.parameterMismatches.map(item => item.key || item.name || JSON.stringify(item)).join(', '))}</div>` : ''}
      ${warnings.length ? `<div class="finance-note warn"><strong>Runtime:</strong> ${UI.esc(warnings.map(item => typeof item === 'string' ? item : JSON.stringify(item)).join(' · '))}</div>` : ''}
      ${perfRow && (perfRow.daily || []).length ? '<section class="panel"><div class="panel-h"><h2>Фактическая доходность</h2><span class="sub">без пополнений счёта</span></div><div class="panel-b"><div class="chart-box"><canvas id="runtime-strategy-chart" style="height:260px"></canvas></div></div></section>' : '<div class="empty-state">Закрытых сделок этой стратегии за год не найдено.</div>'}
      <section class="panel"><div class="panel-h"><h2>Последние жизненные события</h2></div><div class="panel-b tight"><div class="tbl-wrap" style="max-height:280px"><table class="tbl"><thead><tr><th>Время</th><th>Событие</th><th>Причина</th><th>Состояние</th></tr></thead><tbody>${events.length ? events.slice(-80).reverse().map(row => `<tr><td class="muted">${fmtRuntimeDate(row.timestamp_utc)}</td><td>${UI.esc(row.event || '')}</td><td class="muted">${UI.esc(row.reason || '')}</td><td>${UI.esc(row.state || '')}</td></tr>`).join('') : '<tr><td colspan="4"><div class="empty-state">Событий нет.</div></td></tr>'}</tbody></table></div></div></section>
      <details><summary>Текущие параметры (${params.length})</summary><div class="tbl-wrap" style="max-height:360px"><table class="tbl"><tbody>${params.map(([key, value]) => `<tr><td class="mono muted">${UI.esc(key)}</td><td class="mono">${UI.esc(typeof value === 'object' ? JSON.stringify(value) : value)}</td></tr>`).join('')}</tbody></table></div></details>
      <details><summary>Операторский журнал (${(journal.rows || []).length})</summary><pre class="logbox">${UI.esc(JSON.stringify((journal.rows || []).slice(-50), null, 2))}</pre></details>`;
    if (perfRow && (perfRow.daily || []).length) {
      let cumulative = 0;
      Chart.pnl(UI.qs('#runtime-strategy-chart'), perfRow.daily.map(day => (cumulative += Number(day.pnl || 0))), { money: true, height: 260, labels: perfRow.daily.map(day => day.date) });
    }
  }
  async function disableStrategy(sid, cls, acct, iid) {
    if (!confirm(`Остановить стратегию ${sid} на счёте ${acct}? Команда будет поставлена в очередь моста.`)) return;
    try {
      const result = await API.http.runtimeCommand({ command: 'disable_strategy', strategy_id: sid, class_name: cls, account_name: acct, runtime_instance_id: iid, reason: 'остановлено оператором из UI', operator: 'ui' });
      trackCommand(result);
      UI.toast('Команда «остановить» поставлена в очередь');
      loadControl(); loadCommands();
    } catch (e) { UI.reportError(e); }
  }

  async function reconnectSimulation() {
    const account = accounts.find(a => a.account_name === controlAccount) || null;
    if (!account) { UI.toast('Выберите paper/demo/playback счёт'); return; }
    if (!confirm(`Переподключить моделирование для счёта ${account.account_name}? Команда будет поставлена в очередь моста.`)) return;
    try {
      const result = await API.http.runtimeCommand({
        command: 'reconnect_account',
        strategy_id: '',
        account_name: account.account_name,
        reason: 'переподключение моделирования из UI',
        operator: 'ui',
      });
      trackCommand(result);
      UI.toast('Команда reconnect поставлена в очередь');
      loadControl(); loadCommands(); loadAccounts();
    } catch (e) { UI.reportError(e); }
  }

  async function openLaunch() {
    if (!controlAccount) { UI.toast('Нет paper-счёта для управления'); return; }
    UI.drawer('<h3>Запустить стратегию (paper)</h3>', '<div class="state-loading"><span class="spinner"></span>Загрузка каталога…</div>');
    const body = UI.qs('.drawer-b');
    let cat;
    try { cat = await API.http.opsStrategies(); } catch (e) { UI.renderError(body, e); return; }
    catalog = cat.strategies || [];
    body.innerHTML = `
      <p class="muted" style="font-size:12px">Счёт: <strong>${UI.esc(controlAccount)}</strong> · только paper. Команда ставится в очередь моста NinjaTrader; live-счета сервер отклоняет.</p>
      <div class="field"><label for="lc-strat">Стратегия из каталога</label><select class="field" id="lc-strat">${catalog.map(s => `<option value="${UI.esc(s.strategy_id || s.id)}">${UI.esc(s.name || s.strategy_id)}${s.class_name ? ' · ' + UI.esc(s.class_name) : ''}</option>`).join('') || '<option value="">каталог пуст</option>'}</select></div>
      <div class="field"><label for="lc-qty">Количество контрактов</label><input type="number" class="field" id="lc-qty" value="1" min="1" max="20"></div>
      <div class="field"><label for="lc-reason">Причина</label><input class="field" id="lc-reason" placeholder="например: paper-forward тест"></div>
      <div class="flex gap-sm" style="margin-top:8px"><button class="btn primary" id="lc-submit">Запустить (enable)</button><button class="btn ghost" data-close-drawer>Отмена</button></div>`;
    const sub = UI.qs('#lc-submit');
    if (sub) sub.onclick = async () => {
      const sid = UI.qs('#lc-strat').value;
      if (!sid) { UI.toast('Выберите стратегию'); return; }
      const s = catalog.find(x => (x.strategy_id || x.id) === sid) || {};
      const qty = Math.max(1, parseInt(UI.qs('#lc-qty').value, 10) || 1);
      const reason = UI.qs('#lc-reason').value.trim();
      if (!confirm(`Запустить «${s.name || sid}» на paper-счёте ${controlAccount}, ${qty} контр.?`)) return;
      sub.disabled = true;
      try {
        const result = await API.http.runtimeCommand({ command: 'enable_strategy', strategy_id: sid, class_name: s.class_name || '', account_name: controlAccount, instrument: s.instrument || '', quantity: qty, reason, operator: 'ui' });
        trackCommand(result);
        UI.toast('Команда «запустить» поставлена в очередь'); UI.closeDrawer(); loadControl(); loadCommands();
      } catch (e) { UI.reportError(e); sub.disabled = false; }
    };
  }

  // ---------- runtime tabs ----------
  async function loadRuntime() {
    const head = UI.qs('#rt-head'), body = UI.qs('#rt-body');
    body.innerHTML = '<tr><td colspan="9"><div class="state-loading"><span class="spinner"></span>Загрузка…</div></td></tr>';
    try {
      if (rtTab === 'positions') {
        const doc = await API.http.runtimePositions({ signal: UI.signal() });
        const rows = [];
        Object.entries(doc).forEach(([acct, val]) => { if (Array.isArray(val)) val.forEach(p => rows.push(Object.assign({ acct }, p))); });
        head.innerHTML = '<tr><th>Счёт</th><th>Инстр.</th><th>Сторона</th><th class="num">Кол-во</th><th class="num">Ср. цена</th><th class="num">Нереализ.</th></tr>';
        body.innerHTML = rows.length ? rows.map(p => `<tr><td class="mono muted">${UI.esc(p.acct)}</td><td class="mono">${UI.esc(p.instrument || '')}</td><td>${UI.esc(p.market_position || p.side || '')}</td><td class="num">${p.quantity != null ? p.quantity : ''}</td><td class="num">${p.avg_price != null ? p.avg_price : (p.average_price != null ? p.average_price : '')}</td><td class="num ${UI.pnlClass(p.unrealized_pnl || 0)}">${p.unrealized_pnl != null ? UI.money(p.unrealized_pnl, { sign: true }) : '—'}</td></tr>`).join('') : '<tr><td colspan="6"><div class="empty-state">Открытых позиций нет.</div></td></tr>';
      } else if (rtTab === 'orders') {
        const doc = await API.http.runtimeOrders({ limit: 100 }, { signal: UI.signal() });
        const rows = doc.orders || [];
        head.innerHTML = '<tr><th>Время</th><th>Стратегия</th><th>Инстр.</th><th>Действие</th><th>Тип</th><th class="num">Кол-во</th><th>Статус</th></tr>';
        body.innerHTML = rows.length ? rows.map(o => `<tr><td class="muted">${timePT(o.timestamp_utc)}</td><td>${UI.esc(o.strategy_name || o.strategy_id || '')}</td><td class="mono">${UI.esc(o.instrument || '')}</td><td>${UI.esc(o.order_action || '')}</td><td class="muted">${UI.esc(o.order_type || '')}</td><td class="num">${o.quantity || ''}</td><td>${UI.esc(o.order_state || '')}</td></tr>`).join('') : '<tr><td colspan="7"><div class="empty-state">Ордеров нет.</div></td></tr>';
      } else if (rtTab === 'executions') {
        const doc = await API.http.runtimeExecutions({ limit: 100 }, { signal: UI.signal() });
        const rows = doc.executions || [];
        head.innerHTML = '<tr><th>Время</th><th>Стратегия</th><th>Инстр.</th><th>Роль</th><th class="num">Кол-во</th><th class="num">Цена</th><th class="num">P&L</th></tr>';
        body.innerHTML = rows.length ? rows.map(x => `<tr><td class="muted">${timePT(x.timestamp_utc)}</td><td>${UI.esc(x.strategy_name || x.strategy_id || '')}</td><td class="mono">${UI.esc(x.instrument || '')}</td><td>${UI.esc(x.role || x.order_action || '')}</td><td class="num">${x.quantity || ''}</td><td class="num">${x.price != null ? x.price : ''}</td><td class="num ${UI.pnlClass(x.realized_pnl || 0)}">${x.realized_pnl != null ? UI.money(x.realized_pnl, { sign: true }) : '—'}</td></tr>`).join('') : '<tr><td colspan="7"><div class="empty-state">Исполнений нет.</div></td></tr>';
      } else {
        const doc = await API.http.runtimeErrors({ limit: 50 }, { signal: UI.signal() });
        const rows = doc.errors || [];
        head.innerHTML = '<tr><th>Время</th><th>Источник</th><th>Сообщение</th></tr>';
        body.innerHTML = rows.length ? rows.map(x => `<tr><td class="muted">${timePT(x.timestamp_utc || x.ts)}</td><td class="mono muted">${UI.esc(x.source || x.class_name || '')}</td><td>${UI.esc(x.message || x.text || JSON.stringify(x))}</td></tr>`).join('') : '<tr><td colspan="3"><div class="empty-state">Ошибок нет.</div></td></tr>';
      }
    } catch (e) { if (e.name !== 'AbortError') body.innerHTML = `<tr><td colspan="9" class="muted">Ошибка: ${UI.esc(e.message)}</td></tr>`; }
  }

  // ---------- command queue ----------
  function trackCommand(result) {
    trackedCommandId = String((result && (result.command_id || result.id || (result.command && result.command.command_id))) || '');
    if (trackedCommandId) loadTrackedCommand();
  }

  async function loadTrackedCommand() {
    if (!trackedCommandId) return;
    const box = UI.qs('#command-status');
    try {
      const status = await API.http.runtimeCommandStatus({ command_id: trackedCommandId, timeout_sec: 45 });
      const state = status.state || status.status || 'pending';
      box.hidden = false;
      box.innerHTML = `<strong>Последняя команда ${UI.esc(trackedCommandId)}:</strong> ${UI.esc(state)}${status.reason || status.message ? ' · ' + UI.esc(status.reason || status.message) : ''}`;
      if (/^(confirmed_|failed_|unknown_command)/.test(String(state))) trackedCommandId = '';
    } catch (e) {
      box.hidden = false;
      box.textContent = 'Статус команды временно недоступен: ' + e.message;
    }
  }

  async function loadCommands() {
    const box = UI.qs('#cmd-list');
    try {
      const [cmds, results] = await Promise.all([API.http.runtimeCommands({ limit: 20 }), API.http.runtimeCommandResults({ limit: 20 }).catch(() => ({ results: [] }))]);
      const list = cmds.commands || [];
      const resById = {}; (results.results || []).forEach(r => { resById[r.command_id] = r; });
      UI.qs('#cmd-sub').textContent = list.length + ' команд';
      box.innerHTML = list.length ? list.map(c => {
        const r = resById[c.command_id];
        const st = r ? (r.status || r.result || 'выполнено') : 'в очереди';
        return `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(c.command)} · ${UI.esc(c.account_name || '')}</div><div class="row-sub">${UI.esc(c.instrument || '')} · ${UI.esc(c.operator || '')}${c.reason ? ' · ' + UI.esc(c.reason) : ''}</div></div><div class="row-val"><span class="badge ${r ? 'live' : 'trial'}">${UI.esc(st)}</span></div></div>`;
      }).join('') : '<div class="empty-state">Команд пока нет.</div>';
      if (trackedCommandId) loadTrackedCommand();
    } catch (e) { box.innerHTML = '<div class="empty-state">Команды недоступны.</div>'; }
  }

  // ---------- bridge log ----------
  async function loadBridge() {
    if (bridgePaused) return;
    try {
      const diag = await API.http.diagnostics();
      const node = UI.qs('#bridge-log');
      node.textContent = (diag.bridge_log_tail || []).slice(-60).join('\n');
      node.scrollTop = node.scrollHeight;
      const st = UI.qs('#bridge-state');
      bridgeOnline = !!diag.ninjatrader_running;
      st.className = 'badge ' + (diag.ninjatrader_running ? 'live' : 'failed');
      st.innerHTML = `<span class="dot"></span>${diag.ninjatrader_running ? 'онлайн' : 'офлайн'}`;
      refreshControlActions();
    } catch (e) { /* keep last */ }
  }

  // ---------- today by strategy ----------
  async function loadToday() {
    const box = UI.qs('#today-strats');
    try {
      const account = UI.getSelectedAccount();
      const t = await API.http.performance({ period: 'today', account: account && account.account_name }, { signal: UI.signal() });
      const strats = (t.strategies || []).slice().sort((a, b) => (b.pnl || 0) - (a.pnl || 0));
      UI.qs('#today-sub').textContent = (t.summary && t.summary.trades || 0) + ' сделок · ' + UI.money(t.summary && t.summary.pnl || 0, { sign: true });
      box.innerHTML = strats.length ? strats.map(s => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(s.strategy || s.cell || '')}</div><div class="row-sub">${UI.esc(s.instrument || '')} · WR ${UI.pct(s.win_rate || 0)} · ${s.trades || 0} сд.</div></div><div class="row-val ${UI.pnlClass(s.pnl || 0)}">${UI.money(s.pnl || 0, { sign: true })}</div></div>`).join('') : '<div class="empty-state">Сегодня сделок ещё нет.</div>';
    } catch (e) { if (e.name !== 'AbortError') box.innerHTML = '<div class="empty-state">Данные за сегодня недоступны.</div>'; }
  }

  // ---------- calendar + day drilldown ----------
  async function loadCalendar() {
    const year = calendarDate.getFullYear(), month = calendarDate.getMonth();
    const from = `${year}-${String(month + 1).padStart(2, '0')}-01`;
    const to = `${year}-${String(month + 1).padStart(2, '0')}-${String(new Date(year, month + 1, 0).getDate()).padStart(2, '0')}`;
    const account = UI.getSelectedAccount();
    try { perfMonth = await API.http.performance({ period: 'custom', from, to, account: account && account.account_name }, { signal: UI.signal() }); } catch (e) { perfMonth = null; }
    renderCalendar();
  }

  function durationText(seconds) {
    const total = Math.max(0, Number(seconds || 0));
    if (total < 60) return Math.round(total) + ' сек';
    if (total < 3600) return Math.round(total / 60) + ' мин';
    return (total / 3600).toFixed(total >= 36000 ? 0 : 1) + ' ч';
  }

  async function loadRuntimeAudit() {
    const body = UI.qs('#runtime-history-body');
    body.innerHTML = '<tr><td colspan="8"><div class="state-loading"><span class="spinner"></span>Загрузка истории…</div></td></tr>';
    try {
      const [history, display, starts] = await Promise.all([
        API.http.runtimeHistory({ limit: 300 }, { signal: UI.signal() }),
        API.http.runtimeStrategyDisplay({ signal: UI.signal() }),
        API.http.strategyStartDates({ signal: UI.signal() }),
      ]);
      historySessions = history.sessions || [];
      hiddenClasses = display.hidden_classes || [];
      strategyStartDates = starts.strategies || {};
      const active = historySessions.filter(row => row.is_open).length;
      const trades = historySessions.reduce((sum, row) => sum + Number(row.trades_count || 0), 0);
      const gross = historySessions.reduce((sum, row) => sum + Number(row.gross_pnl || 0), 0);
      UI.qs('#runtime-audit-sub').textContent = `${historySessions.length} сессий · источник: телеметрия NinjaTrader`;
      UI.qs('#runtime-audit-kpis').innerHTML = [
        ['Сейчас активны', String(active), active ? 'pos' : ''],
        ['Сессий в истории', String(historySessions.length), ''],
        ['Сделок в сессиях', String(trades), ''],
        ['Gross P&L сессий', UI.money(gross, { sign: true }), UI.pnlClass(gross)],
      ].map(row => `<div class="kpi"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm ${row[2]}">${row[1]}</div></div>`).join('');
      body.innerHTML = historySessions.length ? historySessions.map(row => `<tr class="clickable" data-runtime-instance="${UI.esc(row.runtime_instance_id || '')}"><td class="muted">${fmtRuntimeDate(row.started_at_utc)}</td><td><strong>${UI.esc(row.strategy_name || row.strategy_id || '')}</strong><div class="muted mono" style="font-size:10px">${UI.esc(row.strategy_class || '')}</div></td><td class="mono">${UI.esc(row.instrument || '')}</td><td class="mono muted">${UI.esc(row.account_name || '')}</td><td class="num">${durationText(row.duration_sec)}</td><td class="num">${row.trades_count || 0}</td><td class="num ${UI.pnlClass(row.gross_pnl || 0)}">${UI.money(row.gross_pnl || 0, { sign: true })}</td><td><span class="badge ${row.is_open ? 'live' : 'archived'}">${row.is_open ? 'активна' : UI.esc(row.end_reason || 'завершена')}</span></td></tr>`).join('') : '<tr><td colspan="8"><div class="empty-state">История запусков пока пуста.</div></td></tr>';
      UI.qsa('#runtime-history-body tr[data-runtime-instance]').forEach(row => row.onclick = () => openRuntimeSession(row.dataset.runtimeInstance));
    } catch (e) {
      if (e.name !== 'AbortError') body.innerHTML = `<tr><td colspan="8"><div class="empty-state">История недоступна: ${UI.esc(e.message)}</div></td></tr>`;
    }
  }

  function fmtRuntimeDate(value) {
    if (!value) return '—';
    try { return new Date(value).toLocaleString('ru-RU', { timeZone: 'America/Los_Angeles', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return value; }
  }

  async function openRuntimeSession(instanceId) {
    const session = historySessions.find(row => row.runtime_instance_id === instanceId);
    if (!session) return;
    UI.drawer(`<h3>${UI.esc(session.strategy_name || session.strategy_id)}</h3>`, '<div class="state-loading"><span class="spinner"></span>Загрузка аудита…</div>');
    const body = UI.qs('.drawer-b');
    const start = strategyStartDates[String(session.strategy_id || '').toLowerCase()] || {};
    const [history, journal] = await Promise.all([
      API.http.runtimeStrategyHistory({ runtime_instance_id: instanceId, limit_events: 200, limit_sessions: 50 }).catch(() => ({ events: [], sessions: [] })),
      API.http.opsStrategyJournal(session.strategy_id || '').catch(() => ({ rows: [] })),
    ]);
    const params = Object.entries(session.parameters || {});
    const events = history.events || [];
    const journalRows = journal.rows || [];
    body.innerHTML = `<div class="grid cols-3"><div class="kpi"><div class="kpi-label">Старт наблюдения</div><div class="kpi-val sm">${UI.esc(start.start_date_pt || fmtRuntimeDate(session.started_at_utc))}</div></div><div class="kpi"><div class="kpi-label">Длительность</div><div class="kpi-val sm">${durationText(session.duration_sec)}</div></div><div class="kpi"><div class="kpi-label">Сделок / Gross</div><div class="kpi-val sm ${UI.pnlClass(session.gross_pnl || 0)}">${session.trades_count || 0} · ${UI.money(session.gross_pnl || 0, { sign: true })}</div></div></div>
      <h4>События жизненного цикла</h4>${events.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Время PT</th><th>Событие</th><th>Причина</th><th>Состояние</th></tr></thead><tbody>${events.map(row => `<tr><td class="muted">${fmtRuntimeDate(row.timestamp_utc)}</td><td>${UI.esc(row.event || '')}</td><td class="muted">${UI.esc(row.reason || '')}</td><td>${UI.esc(row.state || '')}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty-state">Событий нет.</div>'}
      <h4>Параметры запуска · ${params.length}</h4>${params.length ? `<div class="tbl-wrap" style="max-height:320px"><table class="tbl"><tbody>${params.map(([key, value]) => `<tr><td class="mono muted">${UI.esc(key)}</td><td class="mono">${UI.esc(typeof value === 'object' ? JSON.stringify(value) : value)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty-state">Параметры не переданы.</div>'}
      <h4>Операторский журнал · ${journalRows.length}</h4>${journalRows.length ? `<pre class="logbox">${UI.esc(JSON.stringify(journalRows.slice(-50), null, 2))}</pre>` : '<div class="empty-state">Журнал пуст.</div>'}`;
  }

  function openHiddenClasses() {
    UI.drawer('<h3>Скрытые классы стратегий</h3>', hiddenClasses.length ? `<div class="list">${hiddenClasses.map(cls => `<div class="row"><div class="row-main"><div class="row-title mono">${UI.esc(cls)}</div></div><button class="btn sm" data-unhide-class="${UI.esc(cls)}">Вернуть</button></div>`).join('')}</div>` : '<div class="empty-state">Скрытых классов нет.</div>');
    UI.qsa('[data-unhide-class]').forEach(button => button.onclick = async () => {
      try { await API.http.setRuntimeStrategyDisplay({ class_name: button.dataset.unhideClass, hidden: false }); UI.toast('Класс возвращён'); UI.closeDrawer(); loadRuntimeAudit(); } catch (e) { UI.reportError(e); }
    });
  }
  function renderCalendar() {
    UI.qs('#cal-dow').innerHTML = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(d => `<div class="cal-dow">${d}</div>`).join('');
    const byDate = {};
    if (perfMonth) (perfMonth.strategies || []).forEach(s => (s.daily || []).forEach(d => { byDate[d.date] = (byDate[d.date] || 0) + (d.pnl || 0); }));
    const year = calendarDate.getFullYear(), month = calendarDate.getMonth();
    UI.qs('#cal-title').textContent = calendarDate.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' });
    const startDow = (new Date(year, month, 1).getDay() + 6) % 7;
    const days = new Date(year, month + 1, 0).getDate();
    let cells = '', monthSum = 0;
    for (let i = 0; i < startDow; i++) cells += '<div class="cal-day empty"></div>';
    for (let d = 1; d <= days; d++) {
      const ds = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      const pnl = byDate[ds];
      if (pnl) monthSum += pnl;
      const cls = pnl > 0 ? 'pos' : pnl < 0 ? 'neg' : '';
      cells += `<div class="cal-day ${cls}" data-date="${ds}"><span class="d">${d}</span>${(pnl != null && pnl !== 0) ? `<span class="v">${UI.money(pnl, { sign: true })}</span>` : ''}</div>`;
    }
    UI.qs('#cal').innerHTML = cells;
    UI.qs('#cal-sum').textContent = 'итого ' + UI.money(monthSum, { sign: true });
    UI.qsa('#cal .cal-day[data-date]').forEach(el => el.onclick = () => { UI.qsa('#cal .cal-day').forEach(x => x.classList.remove('sel')); el.classList.add('sel'); loadDay(el.dataset.date); });
    // default-select the most recent day that has P&L
    const dated = UI.qsa('#cal .cal-day[data-date]');
    const withPnl = dated.filter(el => byDate[el.dataset.date]);
    const pick = (withPnl.length ? withPnl[withPnl.length - 1] : dated[dated.length - 1]);
    if (pick) { pick.classList.add('sel'); loadDay(pick.dataset.date); }
  }
  async function loadDay(date) {
    UI.qs('#day-title').textContent = 'Сделки за ' + date;
    const body = UI.qs('#day-body');
    body.innerHTML = '<tr><td colspan="9"><div class="state-loading"><span class="spinner"></span>Загрузка…</div></td></tr>';
    let exDoc;
    try { exDoc = await API.http.runtimeExecutions({ limit: 2000 }, { signal: UI.signal() }); }
    catch (e) { if (e.name !== 'AbortError') body.innerHTML = '<tr><td colspan="7" class="muted">Не удалось загрузить.</td></tr>'; return; }
    const account = UI.getSelectedAccount();
    const all = (exDoc.executions || []).filter(x => ymdPT(x.timestamp_utc) === date && (!account || !account.account_name || (x.account_name || x.acct) === account.account_name));
    const strats = [...new Set(all.map(x => x.strategy_name || x.strategy_id).filter(Boolean))];
    const sel = UI.qs('#day-strat');
    sel.innerHTML = '<option value="">Все стратегии</option>' + strats.map(s => `<option value="${UI.esc(s)}">${UI.esc(s)}</option>`).join('');
    function render() {
      const f = sel.value;
      const rows = all.filter(x => !f || (x.strategy_name || x.strategy_id) === f);
      const comm = rows.reduce((a, x) => a + (x.commission || 0), 0);
      const realized = rows.reduce((a, x) => a + (Number(x.realized_pnl) || 0), 0);
      UI.qs('#day-summary').innerHTML = `<div class="flex wrap gap-lg"><span class="muted">Исполнений: <strong>${rows.length}</strong></span><span class="muted">Комиссия: <strong>${UI.money(comm)}</strong></span><span class="muted">Realized P&amp;L: <strong class="${UI.pnlClass(realized)}">${UI.money(realized, { sign: true })}</strong></span></div>`;
      body.innerHTML = rows.length ? rows.map(x => { const pnl = Number(x.realized_pnl) || 0; return `<tr><td class="muted">${timePT(x.timestamp_utc)}</td><td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${UI.esc(x.strategy_name || x.strategy_id || '')}</td><td class="mono">${UI.esc(x.instrument || '')}</td><td>${UI.esc(x.order_action || x.market_position || '')}</td><td class="num">${x.quantity || ''}</td><td class="num">${x.price != null ? x.price : ''}</td><td class="num muted">${UI.money(Number(x.commission) || 0)}</td><td class="num ${UI.pnlClass(pnl)}">${x.realized_pnl != null ? UI.money(pnl, { sign: true }) : '—'}</td><td>${UI.esc(x.order_state || x.role || '')}</td></tr>`; }).join('') : '<tr><td colspan="9"><div class="empty-state">Исполнений за день нет.</div></td></tr>';
    }
    sel.onchange = render; render();
  }

  // ---------- wire + init ----------
  UI.qsa('#rt-tabs button').forEach(b => b.onclick = () => { UI.qsa('#rt-tabs button').forEach(x => x.classList.remove('active')); b.classList.add('active'); rtTab = b.dataset.t; loadRuntime(); });
  UI.qs('#ctrl-launch').onclick = openLaunch;
  UI.qs('#ctrl-reconnect').onclick = reconnectSimulation;
  UI.qs('#ctrl-refresh').onclick = () => { loadAccounts(); loadControl(); loadRuntime(); loadRuntimeAudit(); };
  UI.qs('#ctrl-show-hidden').onclick = (event) => {
    showHiddenStrategies = !showHiddenStrategies;
    event.currentTarget.textContent = showHiddenStrategies ? 'Скрыть внешние / личные' : 'Показать скрытые / внешние';
    renderControlRows();
  };
  UI.qs('#hidden-classes-btn').onclick = openHiddenClasses;
  UI.qs('#ledger-add').onclick = openManualLedgerEvent;
  UI.qs('#ledger-import').onclick = openLedgerImport;
  UI.qs('#ctrl-account').onchange = (e) => { controlAccount = e.target.value; UI.setSelectedAccount(controlAccount, true); refreshControlActions(); };
  UI.qs('#cal-prev').onclick = () => { calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth() - 1, 1); loadCalendar(); };
  UI.qs('#cal-next').onclick = () => { calendarDate = new Date(calendarDate.getFullYear(), calendarDate.getMonth() + 1, 1); loadCalendar(); };
  UI.qs('#cal-today').onclick = () => { calendarDate = new Date(); loadCalendar(); };
  UI.qs('#bridge-pause').onclick = (e) => { bridgePaused = !bridgePaused; e.target.textContent = bridgePaused ? 'Продолжить' : 'Пауза'; };
  UI.qs('#bridge-clear').onclick = () => { UI.qs('#bridge-log').textContent = ''; };

  await loadAccounts();
  await Promise.all([loadControl(), loadRuntime(), loadRuntimeAudit(), loadToday(), loadCalendar()]);
  window.addEventListener('nt-account-change', () => { loadAccounts(); loadToday(); loadCalendar(); });
  UI.poll(loadBridge, 5000);
  UI.poll(loadCommands, 9000);
});
