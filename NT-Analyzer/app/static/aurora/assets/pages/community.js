/* Community page — separate from Orchestrator. */
(function () {
  const UI = window.UI;
  const API = window.API;

  async function refresh() {
    const feed = await API.http.communityFeed();
    const chat = UI.qs('#c-chat');
    chat.innerHTML = (feed.messages || []).map(m =>
      `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(m.display_name || m.user_id)}</div><div class="row-sub">${UI.esc(m.text)}</div></div><div class="muted">${UI.esc((m.created_at_utc || '').slice(11, 16))}</div></div>`
    ).join('') || '<div class="muted">Пока тихо — напишите первое сообщение</div>';
    UI.qs('#c-strategies').innerHTML = (feed.strategies || []).map(s =>
      `<div class="row"><div class="row-main"><div class="row-title">${UI.esc(s.title)}</div><div class="row-sub">${UI.esc(s.display_name)} · copies ${s.copies || 0} · net ${(s.metrics && s.metrics.net_profit) || '—'}</div></div><button class="btn sm" data-copy="${UI.esc(s.strategy_id)}">Copy</button></div>`
    ).join('') || '<div class="muted">Нет публикаций</div>';
    UI.qsa('[data-copy]').forEach(b => b.onclick = async () => {
      try {
        const out = await API.http.communityCopy({ strategy_id: b.dataset.copy });
        UI.toast(out.import && out.import.personal_strategy_created
          ? 'Стратегия импортирована в личное пространство'
          : 'Запрос на импорт создан — подтвердите его в портфеле');
        refresh();
      }
      catch (e) { UI.reportError(e); }
    });
    const ratings = (feed.ratings && feed.ratings.composite) || [];
    UI.qs('#c-ratings').innerHTML = '<div class="cab-sub">Рейтинг (risk-adjusted + copies)</div>' + (ratings.slice(0, 8).map((s, i) =>
      `<div class="row"><div class="row-main"><div class="row-title">#${i + 1} ${UI.esc(s.title)}</div><div class="row-sub">copies ${s.copies || 0}</div></div></div>`
    ).join('') || '<div class="muted">—</div>');
  }

  UI.ready(() => {
    UI.qs('#c-send').onclick = async () => {
      const text = UI.qs('#c-text').value;
      try {
        await API.http.communityMessage({ text });
        UI.qs('#c-text').value = '';
        refresh();
      } catch (e) { UI.reportError(e); }
    };
    UI.qs('#c-publish').onclick = async () => {
      try {
        await API.http.communityPublishStrategy({
          title: UI.qs('#c-title').value,
          notes: UI.qs('#c-notes').value,
          metrics: { net_profit: Number(UI.qs('#c-net').value || 0), max_drawdown: Number(UI.qs('#c-dd').value || 0) },
        });
        UI.toast('Стратегия опубликована');
        refresh();
      } catch (e) { UI.reportError(e); }
    };
    refresh().catch(UI.reportError);
    setInterval(() => refresh().catch(() => {}), 8000);
  });
})();
