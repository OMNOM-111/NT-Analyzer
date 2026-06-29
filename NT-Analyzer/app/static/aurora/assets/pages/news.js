UI.ready(async function () {
  const box = UI.qs('#news-list');
  let items = [];
  UI.renderLoading(box, 'Загрузка ленты…');

  function render() {
    const impact = UI.qs('#news-impact').value;
    const rows = items.filter(item => impact === 'all' || item.impact === impact);
    if (!rows.length) { UI.renderEmpty(box, items.length ? 'Нет событий с выбранным уровнем влияния.' : 'Источники настроены, но сохранённых новостей пока нет.'); return; }
    box.innerHTML = rows.map(item => {
      const date = item.published_at_utc ? new Date(item.published_at_utc).toLocaleString('ru-RU') : 'время не указано';
      const instruments = (item.instruments || []).map(value => `<span class="tag mono">${UI.esc(value)}</span>`).join('');
      const title = item.url ? `<a href="${UI.esc(item.url)}" target="_blank" rel="noopener noreferrer">${UI.esc(item.title)}</a>` : UI.esc(item.title);
      return `<article class="news-item impact-${UI.esc(item.impact || 'unknown')}"><div class="flex between"><span class="section-title">${UI.esc(item.source || 'источник')}</span><span class="muted mono">${UI.esc(date)}</span></div><h3>${title}</h3>${item.summary ? `<p class="muted">${UI.esc(item.summary)}</p>` : ''}<div class="flex wrap gap-sm">${instruments}</div></article>`;
    }).join('');
  }

  try {
    const doc = await API.http.news({ limit: 100 }, { signal: UI.signal() });
    items = doc.items || [];
    UI.qs('#news-summary').textContent = doc.configured ? `${doc.total || items.length} реальных событий` : 'источники не настроены';
    if (!doc.configured) UI.renderEmpty(box, 'Источники новостей не настроены. Добавьте NTA_NEWS_FEEDS и backend-коннектор; вымышленные новости не показываются.');
    else render();
  } catch (error) { if (error.name !== 'AbortError') UI.renderError(box, error, () => location.reload()); }
  UI.qs('#news-impact').onchange = render;
});
