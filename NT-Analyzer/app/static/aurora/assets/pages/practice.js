/* Practice trading page — virtual money only. */
(function () {
  const UI = window.UI;
  const API = window.API;
  let state = null;

  function money(v) { return UI.money(Number(v || 0), { sign: true, dec: 2 }); }

  function renderCharts(layout) {
    const host = UI.qs('#practice-charts');
    if (!host) return;
    host.className = 'practice-charts layout-' + layout;
    const n = Number(layout) || 1;
    const mark = ((state && state.marks) || {}).MNQ || 20150;
    host.innerHTML = Array.from({ length: n }, (_, i) =>
      `<div class="practice-chart-pane"><div class="muted">Chart ${i + 1}</div><div class="tb-h1">${UI.esc(String(mark))}</div><div class="sub">симуляция цены · не биржа</div></div>`
    ).join('');
  }

  function render(doc) {
    state = doc;
    const a = (doc && doc.account) || {};
    UI.qs('#practice-badge').textContent = doc.badge || 'Учебный счёт · не реальные деньги';
    UI.qs('#practice-kpis').innerHTML = [
      ['Equity', money(a.equity)],
      ['Balance', money(a.balance)],
      ['Day P&L', money(a.day_pnl)],
      ['Unrealized', money(a.unrealized_pnl)],
    ].map(([k, v]) => `<div class="kpi"><div class="kpi-label">${k}</div><div class="kpi-value">${v}</div></div>`).join('');
    UI.qs('#p-risk').textContent = a.locked
      ? ('LOCK: ' + (a.lock_reason || ''))
      : `daily loss ≤ ${money(-Math.abs(a.daily_loss_limit || 0))} · DD ≤ ${money(-Math.abs(a.max_drawdown || 0))}`;
    const positions = doc.positions || [];
    UI.qs('#p-positions').innerHTML = positions.length
      ? positions.map(p => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(p.side)} ${UI.esc(p.symbol)} ×${p.quantity}</div><div class="row-sub">avg ${p.avg_price} · mark ${p.mark || '—'} · uPnL ${money(p.unrealized_pnl)}</div></div></div>`).join('')
      : '<div class="muted">Нет открытых позиций</div>';
    const orders = doc.orders || [];
    UI.qs('#p-orders').innerHTML = orders.length
      ? orders.map(o => `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(o.order_type)} ${UI.esc(o.side)} ${UI.esc(o.symbol)}</div><div class="row-sub">${o.limit_price || ''} · ${UI.esc(o.status)}</div></div></div>`).join('')
      : '<div class="muted">Нет рабочих ордеров</div>';
    const trades = doc.trades || [];
    UI.qs('#p-trades').innerHTML = trades.slice(0, 8).map(t =>
      `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(t.action)} ${UI.esc(t.side)} ${UI.esc(t.symbol)}</div><div class="row-sub">${money(t.pnl)} · comm ${money(t.commission)} · ${UI.esc((t.at_utc || '').slice(0, 19))}</div></div></div>`
    ).join('') || '<div class="muted">Сделок пока нет</div>';
    renderCharts(UI.qs('#layout-seg .active')?.dataset.layout || 1);
  }

  async function refresh() {
    try {
      const doc = await API.http.practiceAccount();
      render(doc);
      const rep = await API.http.practiceReport().catch(() => null);
      if (rep) {
        UI.qs('#p-report').innerHTML = `<strong>Отчёт:</strong> сделок ${rep.trade_count}, winrate ${rep.winrate}%, realized ${money(rep.realized_pnl)}, комиссии ${money(rep.commissions)}`;
      }
    } catch (e) {
      if (e.status === 404) {
        UI.qs('#practice-kpis').innerHTML = '<div class="muted">Создайте учебный счёт кнопкой справа</div>';
      } else { UI.reportError(e); }
    }
  }

  UI.ready(async () => {
    UI.qsa('#layout-seg button').forEach(b => b.onclick = () => {
      UI.qsa('#layout-seg button').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderCharts(b.dataset.layout);
    });
    UI.qs('#p-create').onclick = async () => {
      if (!confirm('Создать новый учебный счёт на $50 000? Старый будет перезаписан.')) return;
      try {
        const doc = await API.http.practiceCreateAccount({ deposit: 50000, commission: 2, daily_loss_limit: 1000, max_drawdown: 2000, position_limit: 4 });
        UI.toast('Учебный счёт создан');
        render(doc);
      } catch (e) { UI.reportError(e); }
    };
    UI.qs('#p-buy').onclick = async () => {
      try {
        const doc = await API.http.practiceOrder({
          symbol: UI.qs('#p-symbol').value,
          side: UI.qs('#p-side').value,
          quantity: Number(UI.qs('#p-qty').value || 1),
          order_type: UI.qs('#p-type').value,
          limit_price: Number(UI.qs('#p-limit').value || 0),
          stop_loss: Number(UI.qs('#p-sl').value || 0),
          take_profit: Number(UI.qs('#p-tp').value || 0),
        });
        UI.toast(doc.filled ? 'Исполнено' : 'Ордер выставлен');
        render(doc);
      } catch (e) { UI.reportError(e); }
    };
    UI.qs('#p-close').onclick = async () => {
      try {
        const doc = await API.http.practiceClose({});
        UI.toast('Позиция закрыта');
        render(doc);
      } catch (e) { UI.reportError(e); }
    };
    await refresh();
    setInterval(async () => {
      try {
        const doc = await API.http.practiceTick({ symbol: UI.qs('#p-symbol')?.value || 'MNQ' });
        render(doc);
      } catch (e) { /* ignore while no account */ }
    }, 4000);
  });
})();
