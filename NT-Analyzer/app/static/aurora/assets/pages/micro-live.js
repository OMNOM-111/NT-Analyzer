(function () {
  const { qs, qsa, esc, toast, reportError, money } = UI;

  function render(data) {
    const acct = data.account || {};
    const availability = data.availability || {};
    const available = data.available === true;
    const badge = qs('#ml-badge');
    if (badge) badge.textContent = data.badge || 'Реальные деньги · масштаб';
    const stub = qs('#ml-stub');
    if (stub) stub.textContent = data.staging_stub ? 'staging simulator · без реальных платежей' : (available ? 'live adapters verified' : 'coming soon · fail-closed');
    qs('#ml-kpis').innerHTML = [
      ['Баланс', money(Number(acct.balance || 0), { dec: 4 })],
      ['Free trades', String(acct.free_trades_left ?? '—')],
      ['Масштаб', '1:' + String(acct.scale || 100)],
      ['Статус', !available ? 'недоступно' : (acct.locked ? ('LOCK · ' + (acct.lock_reason || '')) : (acct.warnings_accepted ? 'готов' : 'нужен accept'))],
    ].map(([l, v]) => `<div class="kpi"><div class="kpi-label">${esc(l)}</div><div class="kpi-value">${esc(v)}</div></div>`).join('');
    qs('#ml-trades').innerHTML = (data.trades || []).length
      ? data.trades.map(t => `<div class="row"><div class="row-main"><div class="row-title">${esc(t.side)} ${esc(t.symbol)} · ${t.free_trade ? 'FREE' : 'PAID'}</div>
          <div class="row-sub">${esc(t.comparison || '')}</div></div>
          <div class="row-meta">${esc(String(t.pnl_micro))} / full ${esc(String(t.pnl_full))}</div></div>`).join('')
      : '<div class="muted">Сделок пока нет</div>';
    const warning = qs('#ml-warn');
    if (warning) warning.textContent = availability.note || (available ? 'Контур доступен.' : 'Micro Live недоступен до подключения реальных adapters.');
    ['#ml-accept', '#ml-trade', '#ml-deposit'].forEach(id => {
      const button = qs(id);
      if (button) {
        button.disabled = !available;
        button.title = available ? '' : 'Fail-closed: payment/broker adapters не подключены или не разрешены';
      }
    });
  }

  async function refresh() {
    const data = await API.http.microLiveAccount();
    render(data);
    return data;
  }

  async function boot() {
    try {
      await refresh();
    } catch (e) {
      qs('#ml-kpis').innerHTML = `<div class="error">${esc(e.message || e)}</div>`;
    }
    const accept = qs('#ml-accept');
    if (accept) accept.onclick = async () => {
      accept.disabled = true;
      try { await API.http.microLiveAccept(); toast('Риски приняты'); await refresh(); }
      catch (e) { reportError(e); }
      finally { accept.disabled = false; }
    };
    const trade = qs('#ml-trade');
    if (trade) trade.onclick = async () => {
      trade.disabled = true;
      try {
        const out = await API.http.microLiveTrade({
          symbol: qs('#ml-symbol').value,
          side: qs('#ml-side').value,
          notional_full: Number(qs('#ml-notional').value || 100),
        });
        qs('#ml-compare').textContent = (out.trade && out.trade.comparison) || '';
        toast(out.trade && out.trade.free_trade ? 'Free trade записан' : 'Micro trade записан');
        render(out);
      } catch (e) { reportError(e); }
      finally { trade.disabled = false; }
    };
    const dep = qs('#ml-deposit');
    if (dep) dep.onclick = async () => {
      dep.disabled = true;
      try { await API.http.microLiveDeposit({ amount: 50 }); toast('Запрос депозита обработан'); await refresh(); }
      catch (e) { reportError(e); }
      finally { dep.disabled = false; }
    };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
