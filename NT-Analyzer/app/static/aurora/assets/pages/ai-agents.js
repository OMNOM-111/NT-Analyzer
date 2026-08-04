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
      ['Кеш провайдера', `${Number(totals.provider_cache_hit_pct || 0).toFixed(1)}%`, Number(totals.provider_cache_hit_pct || 0) >= 50 ? 'pos' : ''],
      ['Эффективный кеш', `${Number(totals.cache_hit_pct || 0).toFixed(1)}%`, Number(totals.cache_hit_pct || 0) >= 50 ? 'pos' : ''],
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
      return `<tr><td><strong>${UI.esc(agent.model)}</strong><div class="row-sub">${UI.esc(provider.label)} · ${UI.esc(agent.endpoint_type)}</div><div class="row-sub">роль: ${UI.esc(roleById(agent.role).label)}</div></td><td><strong>${UI.esc(agent.account_name)}</strong><div class="row-sub">${UI.esc(billing.label)} · pool ${UI.esc(agent.rotation_group || '—')} · priority ${Number(agent.priority || 100)}</div></td><td><span class="mono">${UI.esc(agent.key_mask || 'не настроен')}</span><div class="row-sub">${agent.key_configured ? 'Windows DPAPI' : UI.esc(agent.key_storage_error || '')}</div></td><td>${budget}<div class="row-sub">${UI.esc(pricing)}</div></td><td><strong>${credit}</strong><div class="row-sub">общий для ${Number(agent.account_models || 1)} моделей этого аккаунта</div></td><td><span class="badge ${agent.enabled ? 'live' : 'archived'}"><span class="dot"></span>${agent.enabled ? 'включён' : 'выключен'}</span>${agent.disabled_reason && agent.disabled_reason !== 'disabled_by_operator' ? `<div class="row-sub">${UI.esc(agent.disabled_reason)}</div>` : ''}${agent.last_test ? `<div class="row-sub">тест: ${agent.last_test.ok ? 'OK' : 'ошибка'} · ${fmtDate(agent.last_test.tested_at_utc)}</div>` : ''}</td><td><div class="agent-actions"><button class="btn sm" data-agent-test="${UI.esc(agent.id)}">Проверка</button><button class="btn sm" data-agent-edit="${UI.esc(agent.id)}">Изменить</button><button class="btn sm ${agent.enabled ? 'danger' : 'primary'}" data-agent-toggle="${UI.esc(agent.id)}" data-enabled="${agent.enabled ? '1' : '0'}">${agent.enabled ? 'Выключить' : 'Включить'}</button>${provider.supports_balance_sync ? `<button class="btn sm" data-agent-balance="${UI.esc(agent.id)}">Синхр. кредит</button>` : ''}<button class="btn sm danger" data-agent-delete="${UI.esc(agent.id)}">Удалить</button></div></td></tr>`;
    }).join('') : '<tr><td colspan="7"><div class="empty-state">Моделей пока нет. Нажмите «Добавить модель»; технические параметры будут определены автоматически.</div></td></tr>';

    const routes = state.routing?.roles || {};
    UI.qs('#routing-body').innerHTML = Object.keys(routes).length
      ? Object.entries(routes).map(([role, rows]) => `<tr><td><strong>${UI.esc(roleById(role).label)}</strong></td><td>${rows.length ? rows.map((row, index) => `<div class="row-sub"><strong>${index + 1}.</strong> ${UI.esc(row.account_name || '')} · <span class="mono">${UI.esc(row.model || '')}</span></div>`).join('') : '<span class="row-sub">нет включённой модели</span>'}</td><td><span class="badge archived">консультативно / песочница</span></td></tr>`).join('')
      : '<tr><td colspan="3"><div class="empty-state">Маршруты пока не рассчитаны.</div></td></tr>';

    UI.qs('#pricing-body').innerHTML = agents.length ? agents.map(agent => {
      const provider = providerById(agent.provider);
      const known = agent.pricing_status !== 'unpriced';
      const free = agent.pricing_status === 'free';
      const input = free ? '$0' : known ? usd(agent.input_price_usd_per_m, 6) : '—';
      const output = free ? '$0' : known ? usd(agent.output_price_usd_per_m, 6) : '—';
      const example = free ? '$0 · free tier' : known ? usd(Number(agent.input_price_usd_per_m || 0) * .025 + Number(agent.output_price_usd_per_m || 0) * .003, 6) : 'будет рассчитано после catalog';
      const priceUrl = agent.pricing_source_url || provider.pricing_url;
      const source = priceUrl ? `<a class="btn sm" href="${UI.esc(priceUrl)}" target="_blank" rel="noopener noreferrer">Официальные тарифы</a>` : 'Свой провайдер';
      return `<tr><td><strong>${UI.esc(provider.label)}</strong><div class="row-sub mono">${UI.esc(agent.model)}</div></td><td class="num">${input}</td><td class="num">${free ? '$0' : known && agent.cached_input_price_usd_per_m != null ? usd(agent.cached_input_price_usd_per_m, 6) : '—'}</td><td class="num">${output}</td><td class="num"><strong>${example}</strong></td><td>${source}</td></tr>`;
    }).join('') : '<tr><td colspan="6"><div class="empty-state">После добавления модели здесь появится её режим тарификации.</div></td></tr>';

    const select = UI.qs('#test-agent');
    const previous = select.value;
    select.innerHTML = agents.length ? agents.map(agent => `<option value="${UI.esc(agent.id)}">${UI.esc(agent.account_name)} · ${UI.esc(agent.model)}</option>`).join('') : '<option value="">нет моделей</option>';
    if (agents.some(agent => agent.id === previous)) select.value = previous;
    UI.qs('#test-send').disabled = !agents.length;
    UI.qs('#usage-body').innerHTML = (state.usage || []).length ? state.usage.slice().reverse().map(row => `<tr><td>${fmtDate(row.timestamp_utc)}</td><td><strong>${UI.esc(row.user_name || (row.user_id ? `ID ${row.user_id}` : 'system'))}</strong><div class="row-sub">${UI.esc(row.workspace_id || '')}</div></td><td><strong>${UI.esc(row.agent_name || row.agent_id || '—')}</strong><div class="row-sub">${UI.esc(row.account_name || '')}${row.request_role ? ` · ${UI.esc(row.request_role)}` : ''}</div></td><td>${UI.esc(row.provider || '—')}<div class="row-sub mono">${UI.esc(row.actual_model || row.model || '')}</div></td><td><span class="badge ${row.status === 'success' ? 'live' : 'failed'}">${UI.esc(row.status || '—')}</span>${row.purpose ? `<div class="row-sub">${UI.esc(row.purpose)}</div>` : ''}${row.error ? `<div class="row-sub">${UI.esc(row.error)}</div>` : ''}</td><td class="num">${Number(row.input_tokens || 0).toLocaleString('ru-RU')}</td><td class="num">${Number(row.cached_input_tokens || 0).toLocaleString('ru-RU')}<div class="row-sub">${Number(row.input_tokens || 0) ? (Number(row.cached_input_tokens || 0) / Number(row.input_tokens || 1) * 100).toFixed(1) : '0.0'}%${row.application_cache_hit ? ` · app saved ${Number(row.application_cache_saved_input_tokens || 0).toLocaleString('ru-RU')}` : ''}</div></td><td class="num">${Number(row.output_tokens || 0).toLocaleString('ru-RU')}</td><td class="num">${Number(row.total_tokens || 0).toLocaleString('ru-RU')}</td><td class="num">${costText(row)}</td></tr>`).join('') : '<tr><td colspan="10"><div class="empty-state">Журнал запросов пуст.</div></td></tr>';
    renderBuckets('#account-usage', state.by_account || [], 'Запросов по аккаунтам пока нет.');
    renderBuckets('#model-usage', state.by_model || [], 'Запросов по моделям пока нет.');
    wireRows();
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
    const d = UI.drawer(`<h3>${editing ? 'Изменить модель' : 'Добавить модель'}</h3>`, `
      <div class="finance-note"><strong>Минимальная настройка:</strong> выберите провайдера, укажите аккаунт/квоту, модель и API-ключ. Тип endpoint, авторизацию, цены и блокирующие бюджеты приложение определяет само. Ключ после сохранения показывается только маской.</div>
      <div class="agent-form-grid">
        <div class="field"><label for="af-provider">Провайдер</label><select id="af-provider">${providerOptions}</select></div>
        <div class="field"><label for="af-account">Аккаунт / квота / API-ключ</label><input id="af-account" maxlength="120" value="${UI.esc(agent?.account_name || '')}" placeholder="Azure Student Grant ($100)"></div>
        <div class="field"><label for="af-model">Модель / имя развёртывания</label><input id="af-model" maxlength="180" value="${UI.esc(agent?.model || '')}" placeholder="gpt-5-mini"></div>
        <div class="field"><label for="af-key">${editing ? 'Новый API-ключ (пусто = оставить текущий)' : 'API-ключ'}</label><input id="af-key" type="password" autocomplete="new-password" placeholder="вставьте ключ только здесь"></div>
        <div class="field wide" id="af-base-field"><label for="af-base">Адрес ресурса (endpoint)</label><input id="af-base" maxlength="500" value="${UI.esc(agent?.base_url || '')}" placeholder="базовый URL или полный endpoint из portal"></div>
        <div class="field"><label for="af-billing">Тип квоты</label><select id="af-billing">${billingOptions}</select></div>
        <div class="field" id="af-credit-field"><label for="af-credit">Общий кредит аккаунта, USD</label><input id="af-credit" type="number" min="0" step="0.01" value="${agent?.credit_total_usd ?? 0}"></div>
        <div class="field wide"><label class="telegram-setting"><span class="telegram-setting-copy"><strong>Включена</strong><small>Нулевой budget означает monitoring-only и больше не блокирует тест.</small></span><input id="af-enabled" type="checkbox" ${agent?.enabled ? 'checked' : ''}><span class="telegram-switch"></span></label></div>
      </div>
      <details><summary>Маршрутизация и назначение — можно настроить позже</summary><div class="agent-form-grid" style="margin-top:12px"><div class="field"><label for="af-pool">Пул ротации</label><input id="af-pool" maxlength="80" value="${UI.esc(agent?.rotation_group || '')}" placeholder="gemini-free"></div><div class="field"><label for="af-priority">Приоритет</label><input id="af-priority" type="number" min="1" max="1000" value="${Number(agent?.priority || 100)}"></div><div class="field"><label for="af-role">Роль</label><select id="af-role">${roleOptions}</select></div><div class="field"><label for="af-purpose">Назначение</label><input id="af-purpose" maxlength="500" value="${UI.esc(agent?.purpose || '')}"></div></div></details>
      <div class="finance-note" id="af-provider-note"></div>
      <div class="flex wrap gap-sm"><button class="btn primary" id="af-save">${editing ? 'Сохранить модель' : 'Добавить модель'}</button><button class="btn ghost" data-close-drawer>Отмена</button></div>`);
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
        keyInput.value = ''; UI.toast(editing ? 'Модель обновлена' : 'Модель добавлена'); UI.closeDrawer(); await load();
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
      UI.toast(result.ok ? 'Проверка подключения пройдена' : 'Проверка подключения не пройдена'); await load();
    } catch (error) { UI.qs('#test-result').textContent = `ERROR: ${error.message}`; UI.reportError(error); }
    finally { button.disabled = false; }
  }

  function wireRows() {
    UI.qsa('[data-agent-edit]').forEach(button => button.onclick = () => openAgentForm(state.agents.find(row => row.id === button.dataset.agentEdit)));
    UI.qsa('[data-agent-test]').forEach(button => button.onclick = () => { UI.qs('#test-agent').value = button.dataset.agentTest; runTest(button.dataset.agentTest); });
    UI.qsa('[data-agent-toggle]').forEach(button => button.onclick = async () => {
      const enable = button.dataset.enabled !== '1';
      if (!confirm(`${enable ? 'Включить' : 'Выключить'} модель?`)) return;
      try { await API.http.aiAgentToggle(button.dataset.agentToggle, enable); UI.toast(enable ? 'Модель включена' : 'Модель выключена'); await load(); } catch (error) { UI.reportError(error); }
    });
    UI.qsa('[data-agent-delete]').forEach(button => button.onclick = async () => {
      const agent = state.agents.find(row => row.id === button.dataset.agentDelete);
      if (!confirm(`Удалить модель ${agent?.model || ''}? Зашифрованный ключ также будет удалён.`)) return;
      try { await API.http.aiAgentDelete(button.dataset.agentDelete); UI.toast('Модель удалена'); await load(); } catch (error) { UI.reportError(error); }
    });
    UI.qsa('[data-agent-balance]').forEach(button => button.onclick = async () => {
      try { await API.http.aiAgentSyncBalance(button.dataset.agentBalance); UI.toast('Баланс кредита синхронизирован'); await load(); } catch (error) { UI.reportError(error); }
    });
  }

  let voiceState = { agents: [], presets: [], catalog: null, key_configured: false };
  let voicePreviewAudio = null;
  let voicePreviewUrl = null;

  function stopVoicePreview() {
    if (voicePreviewAudio) {
      try { voicePreviewAudio.pause(); voicePreviewAudio.removeAttribute('src'); voicePreviewAudio.load(); } catch (e) { /* ignore */ }
      voicePreviewAudio = null;
    }
    if (voicePreviewUrl) {
      try { URL.revokeObjectURL(voicePreviewUrl); } catch (e) { /* ignore */ }
      voicePreviewUrl = null;
    }
    try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (e) { /* ignore */ }
  }

  function setVoiceStatus(text, cls) {
    const el = UI.qs('#staff-voice-status');
    if (!el) return;
    el.className = `voice-status${cls ? ' ' + cls : ''}`;
    el.textContent = text || '';
  }

  function voicesForModel(modelId) {
    const providers = voiceState.catalog?.providers || [];
    for (const provider of providers) {
      for (const model of provider.models || []) {
        if (model.id === modelId) return model.voices || [];
      }
    }
    return [];
  }

  function supportsFor(providerId, modelId) {
    const providers = voiceState.catalog?.providers || [];
    for (const provider of providers) {
      if (provider.id !== providerId) continue;
      for (const model of provider.models || []) {
        if (model.id === modelId) return model.supports || {};
      }
    }
    return {};
  }

  function renderStaffVoices() {
    const grid = UI.qs('#staff-voice-grid');
    const badge = UI.qs('#voice-key-badge');
    if (!grid) return;
    if (badge) {
      badge.className = `badge ${voiceState.key_configured ? 'live' : 'archived'}`;
      badge.innerHTML = `<span class="dot"></span>${voiceState.key_configured ? 'OpenAI TTS' : 'браузерная озвучка'}`;
    }
    const rows = voiceState.agents || [];
    if (!rows.length) {
      grid.innerHTML = '<div class="empty-state">Голоса сотрудников пока недоступны.</div>';
      return;
    }
    grid.innerHTML = rows.map(row => {
      const v = row.voice || {};
      const face = UI.agentAvatarHtml ? UI.agentAvatarHtml(row.id, { label: row.name, cls: 'sm' }) : '';
      return `<article class="staff-voice-card" data-staff-id="${UI.esc(row.id)}">
        <div class="staff-voice-top">${face}<div class="staff-voice-meta"><strong>${UI.esc(row.name || row.id)}</strong><div class="row-sub">${UI.esc(row.title || '')}</div></div></div>
        <div class="row-sub">${UI.esc(row.personality || '')}</div>
        <div class="voice-tags">
          <span>${UI.esc(v.voice || '—')}</span>
          <span>${UI.esc(v.tts_model || '—')}</span>
          <span>×${Number(v.speed || 1).toFixed(2)}</span>
          <span>${v.is_custom ? 'свой' : 'стандарт'}</span>
          <span>${v.tts_enabled === false ? 'выкл' : 'вкл'}</span>
        </div>
        <div class="agent-actions">
          <button class="btn sm primary" data-voice-settings="${UI.esc(row.id)}">Настройки · Голос</button>
          <button class="btn sm" data-voice-preview-card="${UI.esc(row.id)}">Прослушать</button>
        </div>
      </article>`;
    }).join('');
    if (UI.wireAgentFaces) UI.wireAgentFaces(grid);
    UI.qsa('[data-voice-settings]', grid).forEach(btn => {
      btn.onclick = () => openVoiceSettings(btn.dataset.voiceSettings);
    });
    UI.qsa('[data-voice-preview-card]', grid).forEach(btn => {
      btn.onclick = () => previewSavedVoice(btn.dataset.voicePreviewCard);
    });
  }

  async function playVoiceResult(result, phrase, meta) {
    stopVoicePreview();
    if (result && !(result instanceof Blob) && result.fallback === 'browser') {
      setVoiceStatus(`Fallback: браузерный голос (${result.reason || 'no key'})`, 'warn');
      if (!window.speechSynthesis) return;
      const utter = new SpeechSynthesisUtterance(phrase);
      utter.lang = result.language || result.fallback_voice || 'ru-RU';
      const speed = Number(result.speed);
      if (Number.isFinite(speed) && speed > 0) utter.rate = Math.max(0.5, Math.min(1.8, speed));
      speechSynthesis.speak(utter);
      return;
    }
    if (!(result instanceof Blob)) {
      setVoiceStatus('Не удалось получить аудио', 'err');
      return;
    }
    const url = URL.createObjectURL(result);
    voicePreviewUrl = url;
    const audio = new Audio(url);
    voicePreviewAudio = audio;
    setVoiceStatus(`Воспроизведение${meta ? ': ' + meta : ''}…`, 'ok');
    audio.onended = () => setVoiceStatus('Остановлено', '');
    audio.onerror = () => setVoiceStatus('Ошибка воспроизведения', 'err');
    await audio.play();
  }

  async function previewSavedVoice(agentId) {
    const row = (voiceState.agents || []).find(a => a.id === agentId);
    const phrase = row?.preview_phrase || 'Здравствуйте. Готов приступить к работе.';
    setVoiceStatus('Загрузка аудио…', '');
    try {
      const result = await API.http.domainAgentVoicePreview(agentId, null);
      await playVoiceResult(result, phrase, row?.voice?.voice);
    } catch (error) {
      setVoiceStatus(error.message || 'Ошибка предпрослушивания', 'err');
      UI.reportError(error);
    }
  }

  function openVoiceSettings(agentId) {
    const row = (voiceState.agents || []).find(a => a.id === agentId);
    if (!row) return;
    const draft = Object.assign({}, row.voice || {});
    const presets = voiceState.presets || [];
    const providers = voiceState.catalog?.providers || [];
    const face = UI.agentAvatarHtml ? UI.agentAvatarHtml(row.id, { label: row.name, cls: 'lg' }) : '';
    const presetOpts = presets.map(p => `<option value="${UI.esc(p.id)}" ${draft.preset_id === p.id ? 'selected' : ''}>${UI.esc(p.label)}</option>`).join('');
    const providerOpts = providers.map(p => `<option value="${UI.esc(p.id)}" ${draft.tts_provider === p.id ? 'selected' : ''}>${UI.esc(p.label)}</option>`).join('');
    const d = UI.drawer(`<h3>Голос · ${UI.esc(row.name)}</h3>`, `
      <div class="staff-voice-top" style="margin-bottom:12px">${face}<div class="staff-voice-meta"><strong>${UI.esc(row.name)}</strong><div class="row-sub">${UI.esc(row.title || '')}</div><div class="row-sub">${UI.esc(row.personality || '')}</div></div></div>
      <div class="finance-note">Модель ответа и TTS — разные механизмы. Здесь только озвучка. Pitch OpenAI не поддерживает и скрыт.</div>
      <div class="agent-form-grid">
        <div class="field wide"><label class="telegram-setting"><span class="telegram-setting-copy"><strong>Озвучка включена</strong><small>Выкл. — только анимация аватара без речи</small></span><input id="vf-enabled" type="checkbox" ${draft.tts_enabled !== false ? 'checked' : ''}><span class="telegram-switch"></span></label></div>
        <div class="field"><label for="vf-preset">Пресет</label><select id="vf-preset"><option value="">— свой набор —</option>${presetOpts}</select></div>
        <div class="field"><label for="vf-provider">TTS-провайдер</label><select id="vf-provider">${providerOpts}</select></div>
        <div class="field" id="vf-model-wrap"><label for="vf-model">TTS-модель</label><select id="vf-model"></select></div>
        <div class="field" id="vf-voice-wrap"><label for="vf-voice">Голос</label><select id="vf-voice"></select></div>
        <div class="field"><label for="vf-gender">Тип голоса</label><select id="vf-gender">
          <option value="male" ${draft.voice_gender === 'male' ? 'selected' : ''}>Мужской</option>
          <option value="female" ${draft.voice_gender === 'female' ? 'selected' : ''}>Женский</option>
          <option value="neutral" ${draft.voice_gender === 'neutral' ? 'selected' : ''}>Нейтральный</option>
        </select></div>
        <div class="field" id="vf-speed-wrap"><label for="vf-speed">Скорость <span id="vf-speed-val">${Number(draft.speed || 1).toFixed(2)}</span></label><input id="vf-speed" type="range" min="0.5" max="1.5" step="0.01" value="${Number(draft.speed || 1)}"></div>
        <div class="field"><label for="vf-lang">Язык</label><input id="vf-lang" maxlength="16" value="${UI.esc(draft.language || 'ru-RU')}"></div>
        <div class="field wide" id="vf-style-wrap"><label for="vf-style">Стиль / выразительность</label><input id="vf-style" maxlength="200" value="${UI.esc(draft.style || '')}"></div>
        <div class="field wide" id="vf-instr-wrap"><label for="vf-instructions">Инструкция манеры (gpt-4o-mini-tts)</label><textarea id="vf-instructions" rows="3" maxlength="500">${UI.esc(draft.instructions || '')}</textarea></div>
      </div>
      <div class="voice-status" id="vf-status"></div>
      <div class="flex wrap gap-sm" style="margin-top:12px">
        <button class="btn primary" id="vf-preview">Прослушать голос</button>
        <button class="btn primary" id="vf-save">Сохранить</button>
        <button class="btn ghost" id="vf-cancel" data-close-drawer>Отменить изменения</button>
        <button class="btn danger" id="vf-reset">Вернуть стандартный голос</button>
      </div>`);
    d.classList.add('wide');
    const body = UI.qs('.drawer-b', d);
    const status = UI.qs('#vf-status', body);
    const modelSel = UI.qs('#vf-model', body);
    const voiceSel = UI.qs('#vf-voice', body);
    const providerSel = UI.qs('#vf-provider', body);
    const speed = UI.qs('#vf-speed', body);

    function fillModels() {
      const provider = providers.find(p => p.id === providerSel.value) || providers[0];
      const models = provider?.models || [];
      modelSel.innerHTML = models.map(m => `<option value="${UI.esc(m.id)}" ${draft.tts_model === m.id ? 'selected' : ''}>${UI.esc(m.label || m.id)}</option>`).join('');
      if (!models.some(m => m.id === modelSel.value) && models[0]) modelSel.value = models[0].id;
    }
    function fillVoices() {
      const list = voicesForModel(modelSel.value);
      voiceSel.innerHTML = list.length
        ? list.map(v => `<option value="${UI.esc(v)}" ${draft.voice === v ? 'selected' : ''}>${UI.esc(v)}</option>`).join('')
        : '<option value="">—</option>';
      if (list.includes(draft.voice)) voiceSel.value = draft.voice;
    }
    function applySupports() {
      const supports = supportsFor(providerSel.value, modelSel.value);
      UI.qs('#vf-voice-wrap', body).hidden = supports.voice === false;
      UI.qs('#vf-speed-wrap', body).hidden = supports.speed === false;
      UI.qs('#vf-style-wrap', body).hidden = !supports.style;
      UI.qs('#vf-instr-wrap', body).hidden = !supports.instructions;
      UI.qs('#vf-model-wrap', body).hidden = providerSel.value === 'browser';
    }
    function readDraft() {
      return {
        tts_enabled: UI.qs('#vf-enabled', body).checked,
        tts_provider: providerSel.value,
        tts_model: modelSel.value || 'tts-1',
        voice: voiceSel.value || draft.voice,
        voice_gender: UI.qs('#vf-gender', body).value,
        language: UI.qs('#vf-lang', body).value.trim() || 'ru-RU',
        speed: Number(speed.value || 1),
        style: UI.qs('#vf-style', body).value.trim(),
        instructions: UI.qs('#vf-instructions', body).value.trim(),
        fallback_voice: UI.qs('#vf-lang', body).value.trim() || 'ru-RU',
        preset_id: UI.qs('#vf-preset', body).value || '',
      };
    }
    fillModels(); fillVoices(); applySupports();
    providerSel.onchange = () => { fillModels(); fillVoices(); applySupports(); };
    modelSel.onchange = () => { fillVoices(); applySupports(); };
    speed.oninput = () => { UI.qs('#vf-speed-val', body).textContent = Number(speed.value).toFixed(2); };
    UI.qs('#vf-preset', body).onchange = () => {
      const preset = presets.find(p => p.id === UI.qs('#vf-preset', body).value);
      if (!preset) return;
      if (preset.voice) { draft.voice = preset.voice; if ([...voiceSel.options].some(o => o.value === preset.voice)) voiceSel.value = preset.voice; }
      if (preset.voice_gender) UI.qs('#vf-gender', body).value = preset.voice_gender;
      if (preset.speed != null) { speed.value = preset.speed; UI.qs('#vf-speed-val', body).textContent = Number(preset.speed).toFixed(2); }
      if (preset.style) UI.qs('#vf-style', body).value = preset.style;
      if (preset.instructions) UI.qs('#vf-instructions', body).value = preset.instructions;
    };
    UI.qs('#vf-preview', body).onclick = async () => {
      const payload = readDraft();
      status.textContent = 'Загрузка аудио…'; status.className = 'voice-status';
      try {
        const result = await API.http.domainAgentVoicePreview(agentId, payload);
        await playVoiceResult(result, row.preview_phrase || '', payload.voice);
        status.textContent = voiceState.key_configured ? 'Предпрослушивание' : 'Браузерная озвучка';
        status.className = voiceState.key_configured ? 'voice-status ok' : 'voice-status warn';
      } catch (error) {
        status.textContent = error.message || 'Ошибка'; status.className = 'voice-status err';
        UI.reportError(error);
      }
    };
    UI.qs('#vf-save', body).onclick = async () => {
      const btn = UI.qs('#vf-save', body); btn.disabled = true;
      status.textContent = 'Сохранение…';
      try {
        await API.http.domainAgentVoiceSave(agentId, readDraft());
        UI.toast('Голос сохранён');
        stopVoicePreview();
        UI.closeDrawer();
        await loadVoices();
      } catch (error) {
        btn.disabled = false;
        status.textContent = error.message || 'Ошибка сохранения';
        status.className = 'voice-status err';
        UI.reportError(error);
      }
    };
    UI.qs('#vf-reset', body).onclick = async () => {
      if (!confirm('Вернуть стандартный голос этого сотрудника?')) return;
      try {
        await API.http.domainAgentVoiceReset(agentId);
        UI.toast('Стандартный голос восстановлен');
        stopVoicePreview();
        UI.closeDrawer();
        await loadVoices();
      } catch (error) { UI.reportError(error); }
    };
    UI.qs('#vf-cancel', body).onclick = () => stopVoicePreview();
  }

  async function loadVoices() {
    try {
      const data = await API.http.domainAgentVoices({ signal: UI.signal() });
      voiceState = {
        agents: data.agents || [],
        presets: data.presets || [],
        catalog: data.catalog || null,
        key_configured: !!data.key_configured,
      };
      renderStaffVoices();
      if (!data.key_configured) setVoiceStatus('OpenAI-ключ не настроен — озвучка через браузерный fallback.', 'warn');
      else setVoiceStatus('', '');
    } catch (error) {
      const grid = UI.qs('#staff-voice-grid');
      if (grid) grid.innerHTML = `<div class="empty-state">${UI.esc(error.message || 'Не удалось загрузить голоса')}</div>`;
      setVoiceStatus(error.message || 'Ошибка загрузки голосов', 'err');
    }
  }

  async function load() {
    try { state = await API.http.aiAgents({ signal: UI.signal() }); render(); }
    catch (error) { UI.reportError(error); }
    await loadVoices();
  }

  UI.qs('#agent-add').onclick = () => openAgentForm(null);
  UI.qs('#test-send').onclick = () => runTest(UI.qs('#test-agent').value);
  await load();
});
