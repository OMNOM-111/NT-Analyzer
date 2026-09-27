UI.ready(async function () {
  const kpis = UI.qs('#topstep-kpis'); const checks = UI.qs('#topstep-checks');
  UI.renderLoading(kpis, 'Проверка TopStep…');
  try {
    const status = await API.http.topstepStrategyStatus({ signal: UI.signal() });
    const cards = [
      ['Фаза', status.phase || 'неизвестно', 'info'],
      ['API-конфигурация', status.configured ? 'настроена' : 'не настроена', status.configured ? 'pos' : 'warn'],
      ['Live-действия', status.live_actions_enabled ? 'разрешены' : 'заблокированы', status.live_actions_enabled ? 'neg' : 'pos'],
      ['Маршрут', status.transport || 'ProjectX REST + SignalR', 'info'],
    ];
    kpis.innerHTML = cards.map(row => `<div class="kpi ${row[2]}"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm">${UI.esc(row[1])}</div></div>`).join('');
    checks.innerHTML = [
      ['Username', status.username_configured],
      ['API key', status.api_key_configured],
      ['Read-only', status.read_only],
      ['Live-команды отключены', !status.live_actions_enabled]
    ].map(row => `<div class="row"><div class="row-main"><div class="row-title">${row[0]}</div></div><span class="badge ${row[1] ? 'live' : 'archived'}">${row[1] ? 'да' : 'нет'}</span></div>`).join('');
    const note = UI.qs('#topstep-note');
    if (note) note.textContent = status.note || 'TopStep live-контур заблокирован.';
  } catch (error) { if (error.name !== 'AbortError') UI.renderError(kpis, error, () => location.reload()); }
});
