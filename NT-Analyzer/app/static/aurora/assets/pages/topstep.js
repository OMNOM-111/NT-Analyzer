UI.ready(async function () {
  const kpis = UI.qs('#topstep-kpis'); const checks = UI.qs('#topstep-checks');
  UI.renderLoading(kpis, 'Проверка TopStep…');
  try {
    const status = await API.http.topstepStatus({ signal: UI.signal() });
    const cards = [
      ['Режим', status.read_only ? 'только market data' : 'неизвестно', status.read_only ? 'pos' : 'warn'],
      ['API-конфигурация', status.configured ? 'настроена' : 'не настроена', status.configured ? 'pos' : 'warn'],
      ['Provider', status.available ? 'поток активен' : (status.status || 'не запущен'), status.available ? 'pos' : 'warn'],
      ['Данные', status.data_mode === 'live' ? 'live subscription' : 'sim subscription', 'info'],
    ];
    kpis.innerHTML = cards.map(row => `<div class="kpi ${row[2]}"><div class="kpi-label">${row[0]}</div><div class="kpi-val sm">${UI.esc(row[1])}</div></div>`).join('');
    checks.innerHTML = [
      ['TopstepX username', status.username_configured],
      ['API key', status.api_key_configured],
      ['Bars-ответ провайдера подтверждён', !!(status.provider_initialization || {}).bars_response_verified],
      ['Не зависит от NinjaTrader', status.ninjatrader_independent],
      ['Передача сделок отключена', !status.trade_routing_enabled],
      ['Remote server разрешён поставщиком', !status.remote_environment || status.remote_server_authorized],
      ['Redistribution разрешена', !status.remote_environment || status.redistribution_authorized],
    ].map(row => `<div class="row"><div class="row-main"><div class="row-title">${row[0]}</div></div><span class="badge ${row[1] ? 'live' : 'archived'}">${row[1] ? 'да' : 'нет'}</span></div>`).join('');
    const note = UI.qs('#topstep-note');
    if (note) {
      const blockers = (status.blocking_reasons || []).join(', ');
      note.textContent = blockers ? `${status.note || ''} Блокировки: ${blockers}.` : (status.note || 'TopstepX market data готов.');
    }
  } catch (error) { if (error.name !== 'AbortError') UI.renderError(kpis, error, () => location.reload()); }
});
