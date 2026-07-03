/* AI Agents / API Keys — simplified DPAPI-backed model registry. */
UI.ready(async function () {
  let state = { agents: [], providers: [], roles: [], billing_modes: [], usage: [], totals: {}, storage: {}, limits: {} };
  const usd = (value, digits = 4) => '$' + Number(value || 0).toFixed(digits);
  const fmtDate = value => { try { return value ? new Date(value).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—'; } catch (e) { return value || '—'; } };
  const providerById = id => state.providers.find(row => row.id === id) || { id, label: id };
  const roleById = id => state.roles.find(row => row.id === id) || { id, label: id };
  const billingById = id => state.billing_modes.find(row => row.id === id) || { id, label: id };
  const costText = row => row.cost_known === false ? 'цена не настроена' : `${row.cost_estimated ? '≈ ' : ''}${usd(row.cost_usd, 8)}`;

  function meter(spent, limit) {
    if (!(Number(limit) > 0)) return '<div class="row-sub">monitoring · без локального лимита</div>';
    const pct = Math.min(100, Math.max(0, Number(spent || 0) / Number(limit) * 100));
    const cls = pct >= 95 ? 'danger' : pct >= 75 ? 'warn' : '';
    return `<div class="budget-meter ${cls}"><span style="width:${pct.toFixed(1)}%"></span></div>`;
  }

  function renderBuckets(target, rows, empty) {
    UI.qs(target).innerHTML = rows.length ? rows.map(row => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(row.id)}</div><div class="row-sub">${Number(row.requests || 0)} запросов · ${Number(row.tokens || 0).toLocaleString('ru-RU')} tokens · provider cache ${Number(row.provider_cache_hit_pct || 0).toFixed(1)}% · effective ${Number(row.effective_cache_hit_pct || row.cache_hit_pct || 0).toFixed(1)}%${row.unpriced_requests ? ` · ${Number(row.unpriced_requests)} без цены` : ''}</div></div><strong>${usd(row.cost_usd, 6)}</strong></div>`).join('') : `<div class="empty-state">${UI.esc(empty)}</div>`;
  }

  function render() {
    const agents = state.agents || [];
    const totals = state.totals || {};
    const accounts = new Set(agents.map(row => `${row.provider}|${row.account_name}`));
    UI.qs('#agent-kpis').innerHTML = [
      ['Модели', totals.agents || 0, ''],
      ['Аккаунты / ключи', accounts.size, 'info'],
      ['Включены', totals.enabled || 0, totals.enabled ? 'pos' : ''],
      ['Provider cache', `${Number(totals.provider_cache_hit_pct || 0).toFixed(1)}%`, Number(totals.provider_cache_hit_pct || 0) >= 50 ? 'pos' : ''],
      ['Effective cache', `${Number(totals.cache_hit_pct || 0).toFixed(1)}%`, Number(totals.cache_hit_pct || 0) >= 50 ? 'pos' : ''],
      ['Известный расход / месяц', usd(totals.spend_month_usd, 6), 'warn'],
    ].map(row => `<div class="kpi"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm ${row[2]}">${UI.esc(row[1])}</div></div>`).join('');
    UI.qs('#storage-badge').className = `badge ${state.storage?.available ? 'live' : 'failed'}`;
    UI.qs('#storage-badge').innerHTML = `<span class="dot"></span>${state.storage?.available ? 'DPAPI готов' : 'хранилище недоступно'}`;
    UI.qs('#storage-title').textContent = state.storage?.available ? state.storage.backend : 'Добавление ключей заблокировано';
    UI.qs('#storage-note').textContent = state.security_note || 'Ключи не возвращаются через API.';
    UI.qs('#agent-count').textContent = `${agents.length} моделей · ${accounts.size} аккаунтов/ключей`;

    UI.qs('#agent-body').innerHTML = agents.length ? agents.map(agent => {
      const provider = providerById(agent.provider);
      const billing = billingById(agent.billing_mode);
      const credit = agent.billing_mode === 'credit'
        ? (agent.credit_remaining_estimated_usd == null ? `${usd(agent.credit_total_usd, 2)} credit` : `${usd(agent.credit_remaining_estimated_usd, 4)} из ${usd(agent.credit_total_usd, 2)} · использовано ${Number(agent.credit_used_pct || 0).toFixed(4)}%`)
        : billing.label;
      const pricing = agent.pricing_status === 'free' ? 'free tier · $0' : agent.pricing_status === 'estimated' ? 'стоимость ≈ по reference-тарифу' : agent.pricing_status === 'configured' ? 'стоимость считается' : 'tokens считаются · цена ожидает catalog';
      const dayBudget = Number(agent.daily_budget_usd || 0) > 0
        ? `<div>День: ${usd(agent.spend_today_usd, 6)} / ${usd(agent.daily_budget_usd, 2)}</div>${meter(agent.spend_today_usd, agent.daily_budget_usd)}`
        : `<div>День: ${usd(agent.spend_today_usd, 6)}</div><div class="row-sub">без дневного лимита</div>`;
      const monthSpent = agent.monthly_budget_scope === 'provider_account' ? Number(agent.account_spend_month_usd || 0) : Number(agent.spend_month_usd || 0);
      const monthBudget = Number(agent.monthly_budget_usd || 0) > 0
        ? `<div class="row-sub" style="margin-top:6px">Месяц${agent.monthly_budget_scope === 'provider_account' ? ' · общий аккаунт' : ''}: ${usd(monthSpent, 6)} / ${usd(agent.monthly_budget_usd, 2)}</div>${meter(monthSpent, agent.monthly_budget_usd)}`
        : `<div class="row-sub" style="margin-top:6px">Месяц: ${usd(agent.spend_month_usd, 6)} · без лимита</div>`;
      const budget = agent.budget_mode === 'monitor_only'
        ? `<strong>${usd(agent.spend_month_usd, 6)}</strong><div class="row-sub">monitoring · без блокирующего лимита</div>`
        : `${dayBudget}${monthBudget}`;
      return `<tr><td><strong>${UI.esc(agent.model)}</strong><div class="row-sub">${UI.esc(provider.label)} · ${UI.esc(agent.endpoint_type)}</div><div class="row-sub">роль: ${UI.esc(roleById(agent.role).label)}</div></td><td><strong>${UI.esc(agent.account_name)}</strong><div class="row-sub">${UI.esc(billing.label)} · pool ${UI.esc(agent.rotation_group || '—')} · priority ${Number(agent.priority || 100)}</div></td><td><span class="mono">${UI.esc(agent.key_mask || 'не настроен')}</span><div class="row-sub">${agent.key_configured ? 'Windows DPAPI' : UI.esc(agent.key_storage_error || '')}</div></td><td>${budget}<div class="row-sub">${UI.esc(pricing)}</div></td><td><strong>${credit}</strong><div class="row-sub">общий для ${Number(agent.account_models || 1)} моделей этого аккаунта</div></td><td><span class="badge ${agent.enabled ? 'live' : 'archived'}"><span class="dot"></span>${agent.enabled ? 'enabled' : 'disabled'}</span>${agent.disabled_reason && agent.disabled_reason !== 'disabled_by_operator' ? `<div class="row-sub">${UI.esc(agent.disabled_reason)}</div>` : ''}${agent.last_test ? `<div class="row-sub">test: ${agent.last_test.ok ? 'OK' : 'error'} · ${fmtDate(agent.last_test.tested_at_utc)}</div>` : ''}</td><td><div class="agent-actions"><button class="btn sm" data-agent-test="${UI.esc(agent.id)}">Test Connection</button><button class="btn sm" data-agent-edit="${UI.esc(agent.id)}">Edit Agent</button><button class="btn sm ${agent.enabled ? 'danger' : 'primary'}" data-agent-toggle="${UI.esc(agent.id)}" data-enabled="${agent.enabled ? '1' : '0'}">${agent.enabled ? 'Disable Agent' : 'Enable Agent'}</button>${provider.supports_balance_sync ? `<button class="btn sm" data-agent-balance="${UI.esc(agent.id)}">Sync credit</button>` : ''}<button class="btn sm danger" data-agent-delete="${UI.esc(agent.id)}">Delete Agent</button></div></td></tr>`;
    }).join('') : '<tr><td colspan="7"><div class="empty-state">Моделей пока нет. Нажмите Add Model; технические параметры будут определены автоматически.</div></td></tr>';

    const routes = state.routing?.roles || {};
    UI.qs('#routing-body').innerHTML = Object.keys(routes).length
      ? Object.entries(routes).map(([role, rows]) => `<tr><td><strong>${UI.esc(roleById(role).label)}</strong></td><td>${rows.length ? rows.map((row, index) => `<div class="row-sub"><strong>${index + 1}.</strong> ${UI.esc(row.account_name || '')} · <span class="mono">${UI.esc(row.model || '')}</span></div>`).join('') : '<span class="row-sub">нет enabled-модели</span>'}</td><td><span class="badge archived">advisory / sandbox</span></td></tr>`).join('')
      : '<tr><td colspan="3"><div class="empty-state">Маршруты пока не рассчитаны.</div></td></tr>';

    UI.qs('#pricing-body').innerHTML = agents.length ? agents.map(agent => {
      const provider = providerById(agent.provider);
      const known = agent.pricing_status !== 'unpriced';
      const free = agent.pricing_status === 'free';
      const input = free ? '$0' : known ? usd(agent.input_price_usd_per_m, 6) : '—';
      const output = free ? '$0' : known ? usd(agent.output_price_usd_per_m, 6) : '—';
      const example = free ? '$0 · free tier' : known ? usd(Number(agent.input_price_usd_per_m || 0) * .025 + Number(agent.output_price_usd_per_m || 0) * .003, 6) : 'будет рассчитано после catalog';
      const priceUrl = agent.pricing_source_url || provider.pricing_url;
      const source = priceUrl ? `<a class="btn sm" href="${UI.esc(priceUrl)}" target="_blank" rel="noopener noreferrer">Official pricing</a>` : 'Custom provider';
      return `<tr><td><strong>${UI.esc(provider.label)}</strong><div class="row-sub mono">${UI.esc(agent.model)}</div></td><td class="num">${input}</td><td class="num">${free ? '$0' : known && agent.cached_input_price_usd_per_m != null ? usd(agent.cached_input_price_usd_per_m, 6) : '—'}</td><td class="num">${output}</td><td class="num"><strong>${example}</strong></td><td>${source}</td></tr>`;
    }).join('') : '<tr><td colspan="6"><div class="empty-state">После добавления модели здесь появится её режим тарификации.</div></td></tr>';

    const select = UI.qs('#test-agent');
    const previous = select.value;
    select.innerHTML = agents.length ? agents.map(agent => `<option value="${UI.esc(agent.id)}">${UI.esc(agent.account_name)} · ${UI.esc(agent.model)}</option>`).join('') : '<option value="">нет моделей</option>';
    if (agents.some(agent => agent.id === previous)) select.value = previous;
    UI.qs('#test-send').disabled = !agents.length;
    UI.qs('#usage-body').innerHTML = (state.usage || []).length ? state.usage.slice().reverse().map(row => `<tr><td>${fmtDate(row.timestamp_utc)}</td><td><strong>${UI.esc(row.agent_name || row.agent_id || '—')}</strong><div class="row-sub">${UI.esc(row.account_name || '')}${row.request_role ? ` · ${UI.esc(row.request_role)}` : ''}</div></td><td>${UI.esc(row.provider || '—')}<div class="row-sub mono">${UI.esc(row.actual_model || row.model || '')}</div></td><td><span class="badge ${row.status === 'success' ? 'live' : 'failed'}">${UI.esc(row.status || '—')}</span>${row.purpose ? `<div class="row-sub">${UI.esc(row.purpose)}</div>` : ''}${row.error ? `<div class="row-sub">${UI.esc(row.error)}</div>` : ''}</td><td class="num">${Number(row.input_tokens || 0).toLocaleString('ru-RU')}</td><td class="num">${Number(row.cached_input_tokens || 0).toLocaleString('ru-RU')}<div class="row-sub">${Number(row.input_tokens || 0) ? (Number(row.cached_input_tokens || 0) / Number(row.input_tokens || 1) * 100).toFixed(1) : '0.0'}%${row.application_cache_hit ? ` · app saved ${Number(row.application_cache_saved_input_tokens || 0).toLocaleString('ru-RU')}` : ''}</div></td><td class="num">${Number(row.output_tokens || 0).toLocaleString('ru-RU')}</td><td class="num">${Number(row.total_tokens || 0).toLocaleString('ru-RU')}</td><td class="num">${costText(row)}</td></tr>`).join('') : '<tr><td colspan="9"><div class="empty-state">Usage log пуст.</div></td></tr>';
    renderBuckets('#account-usage', state.by_account || [], 'Запросов по аккаунтам пока нет.');
    renderBuckets('#model-usage', state.by_model || [], 'Запросов по моделям пока нет.');
    wireRows();
  }

  async function load() {
    try { state = await API.http.aiAgents({ signal: UI.signal() }); render(); }
    catch (error) { UI.reportError(error); }
  }

  function providerDefaults(providerId) {
    const count = state.agents.filter(row => row.provider === providerId).length + 1;
    if (providerId === 'azure_foundry') return { account: 'Azure Student Grant ($100)', billing: 'credit', credit: 100, pool: 'azure-student', model: '' };
    if (providerId === 'gemini') return { account: `Google AI Studio key ${count}`, billing: 'free_tier', credit: 0, pool: 'gemini-pool', model: 'gemini-2.5-flash' };
    if (providerId === 'openrouter') return { account: `OpenRouter key ${count}`, billing: 'free_tier', credit: 0, pool: 'openrouter-pool', model: 'openrouter/free' };
    if (providerId === 'zai') return { account: `Z.AI key ${count}`, billing: 'unknown', credit: 0, pool: 'zai-pool', model: 'glm-5.2' };
    if (providerId === 'deepseek') return { account: `DeepSeek paid account ${count}`, billing: 'payg', credit: 0, pool: 'deepseek-paid-critical', model: 'deepseek-v4-pro', monthly: 5 };
    return { account: `${providerById(providerId).label} key ${count}`, billing: 'unknown', credit: 0, pool: `${providerId}-pool`, model: '', monthly: 0 };
  }

  function openAgentForm(agent) {
    const editing = Boolean(agent);
    const providerOptions = state.providers.map(row => `<option value="${UI.esc(row.id)}" ${agent?.provider === row.id ? 'selected' : ''}>${UI.esc(row.label)}</option>`).join('');
    const billingOptions = state.billing_modes.map(row => `<option value="${UI.esc(row.id)}" ${agent?.billing_mode === row.id ? 'selected' : ''}>${UI.esc(row.label)}</option>`).join('');
    const roleOptions = state.roles.map(row => `<option value="${UI.esc(row.id)}" ${(agent?.role || 'general') === row.id ? 'selected' : ''}>${UI.esc(row.label)}</option>`).join('');
    const d = UI.drawer(`<h3>${editing ? 'Edit Model' : 'Add Model'}</h3>`, `
      <div class="finance-note"><strong>Минимальная настройка:</strong> выберите provider, укажите аккаунт/квоту, model и API key. Endpoint type, auth, цены и блокирующие бюджеты приложение определяет само. Ключ после сохранения показывается только маской.</div>
      <div class="agent-form-grid">
        <div class="field"><label for="af-provider">Provider</label><select id="af-provider">${providerOptions}</select></div>
        <div class="field"><label for="af-account">Аккаунт / квота / API key</label><input id="af-account" maxlength="120" value="${UI.esc(agent?.account_name || '')}" placeholder="Azure Student Grant ($100)"></div>
        <div class="field"><label for="af-model">Model / deployment name</label><input id="af-model" maxlength="180" value="${UI.esc(agent?.model || '')}" placeholder="gpt-5-mini"></div>
        <div class="field"><label for="af-key">${editing ? 'Новый API key (пусто = оставить текущий)' : 'API key'}</label><input id="af-key" type="password" autocomplete="new-password" placeholder="вставьте ключ только здесь"></div>
        <div class="field wide" id="af-base-field"><label for="af-base">Resource endpoint</label><input id="af-base" maxlength="500" value="${UI.esc(agent?.base_url || '')}" placeholder="базовый URL или полный endpoint из portal"></div>
        <div class="field"><label for="af-billing">Тип квоты</label><select id="af-billing">${billingOptions}</select></div>
        <div class="field" id="af-credit-field"><label for="af-credit">Общий credit аккаунта, USD</label><input id="af-credit" type="number" min="0" step="0.01" value="${agent?.credit_total_usd ?? 0}"></div>
        <div class="field wide"><label class="telegram-setting"><span class="telegram-setting-copy"><strong>Enabled</strong><small>Нулевой budget означает monitoring-only и больше не блокирует тест.</small></span><input id="af-enabled" type="checkbox" ${agent?.enabled ? 'checked' : ''}><span class="telegram-switch"></span></label></div>
      </div>
      <details><summary>Маршрутизация и назначение — можно настроить позже</summary><div class="agent-form-grid" style="margin-top:12px"><div class="field"><label for="af-pool">Rotation pool</label><input id="af-pool" maxlength="80" value="${UI.esc(agent?.rotation_group || '')}" placeholder="gemini-free"></div><div class="field"><label for="af-priority">Priority</label><input id="af-priority" type="number" min="1" max="1000" value="${Number(agent?.priority || 100)}"></div><div class="field"><label for="af-role">Role</label><select id="af-role">${roleOptions}</select></div><div class="field"><label for="af-purpose">Purpose</label><input id="af-purpose" maxlength="500" value="${UI.esc(agent?.purpose || '')}"></div></div></details>
      <div class="finance-note" id="af-provider-note"></div>
      <div class="flex wrap gap-sm"><button class="btn primary" id="af-save">${editing ? 'Save Model' : 'Add Model'}</button><button class="btn ghost" data-close-drawer>Cancel</button></div>`);
    const body = UI.qs('.drawer-b', d);
    const provider = UI.qs('#af-provider', body), base = UI.qs('#af-base', body), billing = UI.qs('#af-billing', body);
    const modelInput = UI.qs('#af-model', body);
    function applyBilling() { UI.qs('#af-credit-field', body).hidden = billing.value !== 'credit'; }
    function applyProvider(force) {
      const meta = providerById(provider.value), defaults = providerDefaults(provider.value);
      if (force || !UI.qs('#af-account', body).value) UI.qs('#af-account', body).value = defaults.account;
      if (force || !UI.qs('#af-pool', body).value) UI.qs('#af-pool', body).value = defaults.pool;
      if (force || !billing.value) billing.value = defaults.billing;
      if (force || !UI.qs('#af-credit', body).value) UI.qs('#af-credit', body).value = defaults.credit;
      if (force || !base.value) base.value = meta.base_url || '';
      if (defaults.model && (force || !modelInput.value)) modelInput.value = defaults.model;
      modelInput.placeholder = defaults.model || meta.default_free_model || 'gpt-5-mini';
      UI.qs('#af-base-field', body).hidden = !['azure_foundry', 'custom'].includes(provider.value);
      UI.qs('#af-provider-note', body).textContent = meta.note || 'Endpoint и auth для этого provider подставляются автоматически.';
      applyBilling();
    }
    provider.onchange = () => applyProvider(true);
    billing.onchange = applyBilling;
    applyProvider(false);
    UI.qs('#af-save', body).onclick = async () => {
      const keyInput = UI.qs('#af-key', body), model = UI.qs('#af-model', body).value.trim(), account = UI.qs('#af-account', body).value.trim();
      const payload = {
        name: `${account} · ${model}`, account_name: account, provider: provider.value,
        base_url: base.value.trim(), model, api_key: keyInput.value.trim(), billing_mode: billing.value,
        rotation_group: UI.qs('#af-pool', body).value.trim(), priority: Number(UI.qs('#af-priority', body).value || 100),
        role: UI.qs('#af-role', body).value || undefined, purpose: UI.qs('#af-purpose', body).value.trim(),
        credit_total_usd: billing.value === 'credit' ? Number(UI.qs('#af-credit', body).value || 0) : 0,
        daily_budget_usd: agent?.daily_budget_usd || 0, monthly_budget_usd: agent?.monthly_budget_usd ?? providerDefaults(provider.value).monthly ?? 0,
        input_price_usd_per_m: agent?.input_price_usd_per_m || 0, cached_input_price_usd_per_m: agent?.cached_input_price_usd_per_m ?? null,
        output_price_usd_per_m: agent?.output_price_usd_per_m || 0, enabled: UI.qs('#af-enabled', body).checked,
      };
      const save = UI.qs('#af-save', body); save.disabled = true;
      try {
        if (editing) await API.http.aiAgentUpdate(agent.id, payload); else await API.http.aiAgentCreate(payload);
        keyInput.value = ''; UI.toast(editing ? 'Model updated' : 'Model added'); UI.closeDrawer(); await load();
      } catch (error) { save.disabled = false; UI.reportError(error); }
    };
  }

  async function runTest(agentId) {
    const agent = state.agents.find(row => row.id === agentId);
    if (!agent) { UI.toast('Выберите модель'); return; }
    if (!confirm(`Отправить короткий API-запрос через ${agent.account_name} · ${agent.model}?`)) return;
    const button = UI.qs('#test-send'); button.disabled = true;
    UI.qs('#test-result').textContent = 'Проверка подключения…';
    try {
      const result = await API.http.aiAgentTest(agentId, UI.qs('#test-prompt').value.trim());
      const cost = agent.pricing_status === 'unpriced' ? 'Cost: цена ещё не внесена в централизованный catalog' : `Cost: ${usd(result.cost_usd, 8)}`;
      UI.qs('#test-result').textContent = result.ok ? `${result.response}\n\n${result.input_tokens} input + ${result.output_tokens} output = ${result.total_tokens} tokens\n${cost} · ${Number(result.elapsed_sec || 0).toFixed(2)} sec` : `ERROR: ${result.error}`;
      UI.toast(result.ok ? 'Connection test passed' : 'Connection test failed'); await load();
    } catch (error) { UI.qs('#test-result').textContent = `ERROR: ${error.message}`; UI.reportError(error); }
    finally { button.disabled = false; }
  }

  function wireRows() {
    UI.qsa('[data-agent-edit]').forEach(button => button.onclick = () => openAgentForm(state.agents.find(row => row.id === button.dataset.agentEdit)));
    UI.qsa('[data-agent-test]').forEach(button => button.onclick = () => { UI.qs('#test-agent').value = button.dataset.agentTest; runTest(button.dataset.agentTest); });
    UI.qsa('[data-agent-toggle]').forEach(button => button.onclick = async () => {
      const enable = button.dataset.enabled !== '1';
      if (!confirm(`${enable ? 'Enable' : 'Disable'} model?`)) return;
      try { await API.http.aiAgentToggle(button.dataset.agentToggle, enable); UI.toast(enable ? 'Model enabled' : 'Model disabled'); await load(); } catch (error) { UI.reportError(error); }
    });
    UI.qsa('[data-agent-delete]').forEach(button => button.onclick = async () => {
      const agent = state.agents.find(row => row.id === button.dataset.agentDelete);
      if (!confirm(`Delete Model ${agent?.model || ''}? Зашифрованный ключ также будет удалён.`)) return;
      try { await API.http.aiAgentDelete(button.dataset.agentDelete); UI.toast('Model deleted'); await load(); } catch (error) { UI.reportError(error); }
    });
    UI.qsa('[data-agent-balance]').forEach(button => button.onclick = async () => {
      try { await API.http.aiAgentSyncBalance(button.dataset.agentBalance); UI.toast('Credit balance synchronized'); await load(); } catch (error) { UI.reportError(error); }
    });
  }

  UI.qs('#agent-add').onclick = () => openAgentForm(null);
  UI.qs('#test-send').onclick = () => runTest(UI.qs('#test-agent').value);
  await load();
});
