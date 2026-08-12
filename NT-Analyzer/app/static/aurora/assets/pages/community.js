/* Community workspace — peer conversations and sharing, never Orchestrator. */
(function () {
  const UI = window.UI;
  const API = window.API;
  let channel = 'general';
  let threadRootId = '';
  let pendingAttachments = [];
  let lastFeed = null;

  function q(id) { return UI.qs(id); }
  function esc(value) { return UI.esc(value == null ? '' : String(value)); }
  function time(value) { return esc(String(value || '').slice(11, 16) || '—'); }
  function attachmentHtml(items) {
    const rows = Array.isArray(items) ? items : [];
    return rows.map(item => `<a class="community-attachment" href="${esc(item.url || '')}" target="_blank" rel="noopener"><span>🖼</span>${esc(item.name || 'image')} <small>${Math.ceil(Number(item.size || 0) / 1024)} KB</small></a>`).join('');
  }
  function renderPendingAttachments() {
    const host = q('#c-attachments');
    if (!host) return;
    host.innerHTML = pendingAttachments.map((item, index) => `<span class="community-pending-file">${esc(item.name)} <button class="btn ghost sm" type="button" data-remove-file="${index}">×</button></span>`).join('');
    UI.qsa('[data-remove-file]', host).forEach(btn => {
      btn.onclick = () => { pendingAttachments.splice(Number(btn.dataset.removeFile), 1); renderPendingAttachments(); };
    });
  }
  function renderThreadState() {
    const host = q('#c-thread-state');
    if (!host) return;
    if (!threadRootId) { host.hidden = true; host.innerHTML = ''; return; }
    const root = (lastFeed && lastFeed.messages || []).find(row => row.message_id === threadRootId);
    host.hidden = false;
    host.innerHTML = `<span>Ответ в ветке: ${esc((root && root.display_name) || 'сообщение')}</span><button class="btn ghost sm" type="button" id="c-thread-cancel">Отменить</button>`;
    const cancel = q('#c-thread-cancel'); if (cancel) cancel.onclick = () => { threadRootId = ''; renderThreadState(); };
  }
  function renderChannels(feed) {
    const host = q('#c-channels');
    const channels = feed.channels || [];
    if (!host) return;
    host.innerHTML = channels.map(item => `<button type="button" class="${item.id === channel ? 'active' : ''}" data-channel="${esc(item.id)}">${esc(item.label)}</button>`).join('');
    UI.qsa('[data-channel]', host).forEach(btn => btn.onclick = () => {
      channel = btn.dataset.channel || 'general';
      threadRootId = '';
      refresh().catch(UI.reportError);
    });
    const selected = channels.find(item => item.id === channel) || {};
    const title = q('#c-channel-title'); if (title) title.textContent = selected.label || 'Community';
    const hint = q('#c-channel-hint'); if (hint) hint.textContent = selected.hint || '';
  }
  function renderChat(feed) {
    const host = q('#c-chat');
    if (!host) return;
    host.innerHTML = (feed.messages || []).map(m => {
      const reply = m.thread_root_id ? '<span class="community-reply-mark">↳ ответ в ветке</span>' : '';
      return `<article class="row community-message ${m.thread_root_id ? 'community-message-reply' : ''}"><div class="row-main"><div class="row-title">${esc(m.display_name || m.user_id)} ${reply}</div><div class="row-sub community-message-body">${esc(m.text)}</div>${attachmentHtml(m.attachments)}</div><div class="community-message-actions"><span class="muted">${time(m.created_at_utc)}</span><button class="btn ghost sm" type="button" data-reply="${esc(m.thread_root_id || m.message_id)}">Ответить</button></div></article>`;
    }).join('') || '<div class="muted">Пока тихо — начните обсуждение.</div>';
    UI.qsa('[data-reply]', host).forEach(btn => btn.onclick = () => {
      threadRootId = btn.dataset.reply || '';
      renderThreadState();
      const input = q('#c-text'); if (input) input.focus();
    });
  }
  function renderReports(feed) {
    const reports = (feed.shared_reports || []).filter(row => !row.channel_id || row.channel_id === channel || channel === 'reports');
    const requests = (feed.requests || []).filter(row => !row.channel_id || row.channel_id === channel || channel === 'reports');
    const reportHost = q('#c-reports');
    if (reportHost) reportHost.innerHTML = reports.map(r => `<div class="row"><div class="row-main"><div class="row-title">${esc(r.title)}</div><div class="row-sub">${esc(r.display_name)} · ${esc(r.summary || 'без описания')}</div><div class="community-metrics">${Object.entries(r.metrics || {}).map(([key, value]) => `<span>${esc(key)}: ${esc(value)}</span>`).join('')}</div>${attachmentHtml(r.attachments)}</div><span class="muted">${time(r.created_at_utc)}</span></div>`).join('') || '<div class="muted">Отчётов в этом канале пока нет.</div>';
    const requestHost = q('#c-requests');
    if (requestHost) requestHost.innerHTML = requests.map(r => `<div class="row"><div class="row-main"><div class="row-title">${esc(r.title)} <span class="badge">${esc(r.request_type)}</span></div><div class="row-sub">от ${esc(r.from_display_name)} · ${Number(r.recipient_user_id || 0) ? 'для ID ' + esc(r.recipient_user_id) : 'для всех'} · ${esc(r.status)}</div></div></div>`).join('') || '<div class="muted">Открытых запросов нет.</div>';
  }
  function renderStrategies(feed) {
    const strategies = q('#c-strategies');
    if (strategies) strategies.innerHTML = (feed.strategies || []).map(s => `<div class="row"><div class="row-main"><div class="row-title">${esc(s.title)}</div><div class="row-sub">${esc(s.display_name)} · copies ${Number(s.copies || 0)} · net ${esc((s.metrics && s.metrics.net_profit) || '—')}</div></div><button class="btn sm" data-copy="${esc(s.strategy_id)}">Copy</button></div>`).join('') || '<div class="muted">Нет публикаций</div>';
    UI.qsa('[data-copy]').forEach(btn => btn.onclick = async () => {
      try {
        const out = await API.http.communityCopy({ strategy_id: btn.dataset.copy });
        UI.toast(out.import && out.import.personal_strategy_created ? 'Стратегия импортирована' : 'Запрос на импорт создан — подтвердите его в портфеле');
        refresh();
      } catch (error) { UI.reportError(error); }
    });
    const ratings = (feed.ratings && feed.ratings.composite) || [];
    const ratingHost = q('#c-ratings');
    if (ratingHost) ratingHost.innerHTML = '<div class="cab-sub">С поправкой на риск + копии</div>' + (ratings.slice(0, 8).map((s, index) => `<div class="row"><div class="row-main"><div class="row-title">#${index + 1} ${esc(s.title)}</div><div class="row-sub">копий ${Number(s.copies || 0)}</div></div></div>`).join('') || '<div class="muted">—</div>');
  }
  async function refresh() {
    const feed = await API.http.communityFeed({ channel });
    lastFeed = feed;
    renderChannels(feed);
    renderChat(feed);
    renderThreadState();
    renderReports(feed);
    renderStrategies(feed);
  }
  async function readFiles(files) {
    const candidates = Array.from(files || []);
    const available = 3 - pendingAttachments.length;
    if (candidates.length > available) { UI.toast('Можно приложить не более трёх изображений.'); }
    for (const file of candidates.slice(0, Math.max(0, available))) {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) {
        UI.toast('Подходит PNG/JPEG/WebP до 2 МБ.');
        continue;
      }
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(new Error('Не удалось прочитать файл.'));
        reader.readAsDataURL(file);
      });
      pendingAttachments.push({ name: file.name, data_url: dataUrl });
    }
    renderPendingAttachments();
  }
  UI.ready(() => {
    q('#c-send').onclick = async () => {
      const input = q('#c-text');
      const text = input.value;
      try {
        await API.http.communityMessage({ text, channel_id: channel, thread_root_id: threadRootId, attachments: pendingAttachments });
        input.value = ''; pendingAttachments = []; threadRootId = ''; renderPendingAttachments();
        await refresh();
      } catch (error) { UI.reportError(error); }
    };
    q('#c-files').onchange = async event => { try { await readFiles(event.target.files); } catch (error) { UI.reportError(error); } finally { event.target.value = ''; } };
    q('#c-share-report').onclick = async () => {
      try {
        await API.http.communityShareReport({
          title: q('#c-report-title').value,
          summary: q('#c-report-summary').value,
          metrics: { pnl: Number(q('#c-report-pnl').value || 0), max_drawdown: Number(q('#c-report-dd').value || 0) },
          channel_id: 'reports',
          attachments: pendingAttachments,
        });
        q('#c-report-title').value = ''; q('#c-report-summary').value = ''; pendingAttachments = []; renderPendingAttachments();
        channel = 'reports'; await refresh(); UI.toast('Отчёт опубликован в сообществе');
      } catch (error) { UI.reportError(error); }
    };
    q('#c-create-request').onclick = async () => {
      try {
        await API.http.communityRequest({
          title: q('#c-request-title').value,
          request_type: q('#c-request-type').value,
          recipient_user_id: Number(q('#c-request-user').value || 0),
          channel_id: 'reports',
        });
        q('#c-request-title').value = ''; q('#c-request-user').value = ''; channel = 'reports'; await refresh(); UI.toast('Запрос создан');
      } catch (error) { UI.reportError(error); }
    };
    q('#c-publish').onclick = async () => {
      try {
        await API.http.communityPublishStrategy({
          title: q('#c-title').value,
          notes: q('#c-notes').value,
          metrics: { net_profit: Number(q('#c-net').value || 0), max_drawdown: Number(q('#c-dd').value || 0) },
        });
        UI.toast('Стратегия опубликована'); refresh();
      } catch (error) { UI.reportError(error); }
    };
    renderPendingAttachments();
    refresh().catch(UI.reportError);
    setInterval(() => refresh().catch(() => {}), 8000);
  });
})();
