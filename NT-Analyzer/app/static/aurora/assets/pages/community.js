/* StratForge Community v2 — real social feed plus compatible workspace channels. */
(function () {
  'use strict';
  const UI = window.UI;
  const API = window.API;
  const STATE = {
    view: 'for-you', query: '', cursor: '', loading: false, sort: 'recent',
    feed: null, profiles: [], viewer: null, pendingPostFiles: [],
    wallTab: 'posts', wallRequest: 0, wallSavedCount: 0,
    channel: 'general', channelFeed: null, threadRootId: '', pendingChannelFiles: [],
    centerMode: 'stream', openProfileId: '', openOrgId: '', loadMoreVisible: false,
    identities: [], correctionTarget: null,
  };
  // The centre column's heading, reused by the back control so it names the
  // stream the reader actually came from.
  const STREAM_TITLES = {
    'for-you': 'Recommendation', following: 'Подписки',
    saved: 'Сохранённое', channels: 'Каналы',
  };
  // Постоянная запись. Опубликованное нельзя удалить или изменить — ни автору,
  // ни владельцу. Сервер отказывает в удалении; здесь нет и самого контрола,
  // чтобы интерфейс не обещал того, чего не произойдёт. Текст приходит с
  // сервера (`permanence_notice`), значение ниже — только запасной вариант,
  // если ответ пришёл без него.
  const PERMANENCE_FALLBACK = 'Опубликованное становится частью постоянной истории профиля: '
    + 'удалить или переписать запись нельзя. Ошибку исправляет новая публикация — обе останутся.';
  let PERMANENCE_TITLE = PERMANENCE_FALLBACK;
  function applyPermanenceNotice(doc) {
    const text = String((doc && doc.permanence_notice) || '').trim();
    if (text) PERMANENCE_TITLE = text;
    const node = q('#community-permanence-note');
    if (node) node.textContent = PERMANENCE_TITLE;
  }

  function q(value, root) { return UI.qs(value, root); }
  function qa(value, root) { return UI.qsa(value, root); }
  function esc(value) { return UI.esc(value == null ? '' : String(value)); }
  function cssEscape(value) {
    const text = String(value == null ? '' : value);
    return window.CSS && typeof window.CSS.escape === 'function'
      ? window.CSS.escape(text) : text.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  }
  function safeUrl(value, prefix) {
    const url = String(value || '');
    return url.startsWith(prefix || '/api/') ? url : '';
  }
  function initials(profile) {
    const parts = String((profile && profile.display_name) || 'SF').trim().split(/\s+/).filter(Boolean);
    return (parts.slice(0, 2).map(item => item[0]).join('') || 'SF').toUpperCase().slice(0, 2);
  }
  function avatar(profile, cls) {
    const src = safeUrl(profile && profile.avatar_url, '/api/community/v2/profiles/');
    const label = esc((profile && profile.display_name) || 'Участник');
    return `<span class="community-avatar ${esc(cls || '')}" title="${label}">${src
      ? `<img src="${esc(src)}" alt="${label}" loading="lazy">`
      : esc(initials(profile))}</span>`;
  }
  function fmtDate(value) {
    if (!value) return '';
    try {
      return new Intl.DateTimeFormat('ru-RU', {
        timeZone: (window.AuroraDomain && AuroraDomain.PT_ZONE) || 'America/Los_Angeles',
        day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
      }).format(new Date(value));
    } catch (e) { return String(value).slice(0, 16); }
  }
  function shortNumber(value) {
    const n = Math.max(0, Number(value) || 0);
    if (n >= 1000000) return (n / 1000000).toFixed(n >= 10000000 ? 0 : 1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'K';
    return String(n);
  }
  function domId(value) {
    const safe = String(value == null ? '' : value).replace(/[^a-zA-Z0-9_-]/g, '-');
    return safe || 'post';
  }
  function actionIcon(name) {
    const icons = {
      heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.8 8.7c0 5.3-8.8 10.2-8.8 10.2S3.2 14 3.2 8.7A4.4 4.4 0 0 1 11 5.8a4.4 4.4 0 0 1 9.8 2.9Z"/></svg>',
      comment: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11.5a7.5 7.5 0 0 1-8 7.5 8.7 8.7 0 0 1-3.3-.6L4 20l1.5-3.8A7.2 7.2 0 0 1 4 11.5 7.5 7.5 0 0 1 12 4a7.5 7.5 0 0 1 8 7.5Z"/></svg>',
      share: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m12 16 4-4-4-4"/><path d="M4 19v-1.5A5.5 5.5 0 0 1 9.5 12H16"/></svg>',
      bookmark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 4.5A2.5 2.5 0 0 1 9 2h6a2.5 2.5 0 0 1 2.5 2.5V21L12 17.5 6.5 21V4.5Z"/></svg>',
    };
    return icons[name] || '';
  }
  function reactionTotal(reactions) {
    return Object.values(reactions && typeof reactions === 'object' ? reactions : {})
      .reduce((sum, value) => sum + Math.max(0, Number(value) || 0), 0);
  }
  function setStatus(text, tone) {
    const node = q('#community-tab-status');
    if (!node) return;
    node.textContent = text || '';
    node.dataset.tone = tone || '';
  }
  function renderEmpty(title, text) {
    return `<div class="community-empty"><span>◇</span><strong>${esc(title)}</strong><p>${esc(text || '')}</p></div>`;
  }

  function profileStats(profile) {
    const stats = (profile && profile.stats) || {};
    return `<div class="community-profile-stats">
      <span><strong>${shortNumber(stats.posts)}</strong>публикаций</span>
      <span><strong>${shortNumber(stats.followers)}</strong>подписчиков</span>
      <span><strong>${shortNumber(stats.following)}</strong>подписок</span>
    </div>`;
  }
  function wallStats(profile) {
    const stats = (profile && profile.stats) || {};
    return `<div class="community-wall-stats">
      <span><small>Публикации</small><strong>${shortNumber(stats.posts)}</strong></span>
      <span><small>Подписчики</small><strong>${shortNumber(stats.followers)}</strong></span>
      <span><small>Подписки</small><strong>${shortNumber(stats.following)}</strong></span>
      <span><small>Закладки</small><strong id="community-profile-saved-stat">${shortNumber(STATE.wallSavedCount)}</strong></span>
    </div>`;
  }
  function renderViewer(profile) {
    if (!profile) return;
    STATE.viewer = profile;
    const composeAvatar = q('#community-composer-avatar');
    if (composeAvatar) composeAvatar.outerHTML = avatar(profile, '').replace('<span ', '<span id="community-composer-avatar" ');
    const summary = q('#community-profile-summary');
    if (summary) summary.innerHTML = `
      <div class="community-wall-profile-head">
        ${avatar(profile, 'xl')}
        <div class="community-wall-identity">
          <div><button type="button" class="community-profile-name" data-profile="${esc(profile.profile_id)}">${esc(profile.display_name)}</button><span class="community-role">${esc(profile.role_label)}</span></div>
          <span class="community-handle">@${esc(profile.username)}</span>
          <p>${esc(profile.bio || 'Добавьте несколько слов о себе и своём стиле торговли.')}</p>
        </div>
        <button type="button" class="community-wall-settings" data-edit-profile title="Настроить профиль" aria-label="Настроить профиль">⚙</button>
      </div>

      ${wallStats(profile)}`;
    qa('[data-edit-profile]').forEach(button => { button.onclick = () => openProfileVisibility(profile); });
    qa(`[data-profile="${cssEscape(profile.profile_id || '')}"]`).forEach(button => { button.onclick = () => openProfile(profile.profile_id); });
  }

  function renderPeople(profiles) {
    const rows = Array.isArray(profiles) ? profiles.filter(item => !item.is_self) : [];
    STATE.profiles = rows;
    const following = q('#community-following-list');
    const followed = rows.filter(profile => profile.is_following);
    const ordered = followed.concat(rows.filter(profile => !profile.is_following)).slice(0, 7);
    if (following) following.innerHTML = ordered.map(profile => `<button type="button" class="community-followed-person ${profile.is_following ? 'following' : ''}" data-profile="${esc(profile.profile_id)}" title="${esc(profile.display_name)} · @${esc(profile.username)}">${avatar(profile, 'sm')}<span class="community-dock-person-label">${esc(profile.display_name)}</span>${profile.is_following ? '<i class="community-following-mark" aria-label="В подписках"></i>' : ''}</button>`).join('') || '<span class="community-dock-empty" title="Другие участники появятся позже">SF</span>';
    const count = q('#community-social-count'); if (count) count.textContent = shortNumber(rows.length);
    wirePeopleActions(document);
  }

  function objectType(object) {
    const raw = `${object.source_type || ''} ${object.result_type || ''} ${object.kind || ''}`.toLowerCase();
    if (raw.includes('backtest')) return { key: 'backtest', label: 'БЭКТЕСТ', icon: '▧' };
    if (raw.includes('demo') || raw.includes('result') || raw.includes('результ')) return { key: 'result', label: 'РЕЗУЛЬТАТ', icon: '↗' };
    if (raw.includes('chart') || raw.includes('график')) return { key: 'chart', label: 'ГРАФИК', icon: '⌗' };
    if (raw.includes('strategy') || raw.includes('стратег')) return { key: 'strategy', label: 'СТРАТЕГИЯ', icon: '▱' };
    return { key: 'object', label: String(object.kind || 'ОБЪЕКТ').toUpperCase(), icon: '◇' };
  }
  function objectMetricLabel(key) {
    const normalized = String(key || '').trim().toLowerCase().replace(/[_-]+/g, ' ');
    const aliases = {
      'net p&l': 'ПРИБЫЛЬ (P&L)', 'net pnl': 'ПРИБЫЛЬ (P&L)', 'net profit': 'ПРИБЫЛЬ (P&L)', pnl: 'ПРИБЫЛЬ (P&L)', profit: 'ПРИБЫЛЬ (P&L)',
      'win rate': 'ВИНРЕЙТ', 'winning pct': 'ВИНРЕЙТ', 'profit factor': 'PROFIT FACTOR', 'max drawdown': 'МАКС. ПРОСАДКА', drawdown: 'МАКС. ПРОСАДКА',
      trades: 'СДЕЛКИ', 'trade count': 'СДЕЛКИ', timeframe: 'ТАЙМФРЕЙМ', instrument: 'ИНСТРУМЕНТ',
    };
    return aliases[normalized] || String(key || '').replace(/_/g, ' ').toUpperCase();
  }
  function objectMetricValue(key, value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return String(value == null ? '—' : value);
    const normalized = String(key || '').toLowerCase();
    if (normalized.includes('win') || normalized.includes('pct') || normalized.includes('rate')) return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`;
    if (normalized.includes('factor')) return value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const formatted = Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: Number.isInteger(value) ? 0 : 2, maximumFractionDigits: 2 });
    return `${value > 0 && (normalized.includes('profit') || normalized.includes('pnl') || normalized.includes('p&l')) ? '+' : value < 0 ? '-' : ''}${formatted}`;
  }
  function objectMetricTone(key, value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '';
    const normalized = String(key || '').toLowerCase();
    if (normalized.includes('drawdown')) return value === 0 ? '' : 'negative';
    if (normalized.includes('profit') || normalized.includes('pnl') || normalized.includes('p&l')) return value > 0 ? 'positive' : value < 0 ? 'negative' : '';
    return '';
  }
  function objectChartSeries(object) {
    const source = Array.isArray(object.chart_points) ? object.chart_points
      : Array.isArray(object.equity_curve) ? object.equity_curve
        : object.chart && Array.isArray(object.chart.points) ? object.chart.points : [];
    return source.slice(0, 80).map(item => {
      const raw = typeof item === 'number' ? item : item && (item.value != null ? item.value : item.equity != null ? item.equity : item.close);
      const value = Number(raw); return Number.isFinite(value) ? value : null;
    }).filter(value => value != null);
  }
  function objectChart(object) {
    const preview = safeUrl(object.chart_preview_url || object.preview_url, '/api/');
    if (preview) return `<div class="community-object-chart"><img src="${esc(preview)}" alt="Превью графика ${esc(object.title || '')}" loading="lazy"></div>`;
    const series = objectChartSeries(object);
    if (series.length < 2) return `<div class="community-object-chart community-object-chart-empty" role="img" aria-label="График не включён в публичный snapshot"><span>⌁</span><strong>Превью графика</strong><small>Серия не включена в публичный snapshot</small></div>`;
    const min = Math.min(...series); const max = Math.max(...series); const span = max - min || 1;
    const points = series.map((value, index) => `${(index / (series.length - 1) * 348 + 6).toFixed(1)},${(96 - ((value - min) / span) * 82).toFixed(1)}`).join(' ');
    const tone = series[series.length - 1] >= series[0] ? 'positive' : 'negative';
    return `<div class="community-object-chart ${tone}" role="img" aria-label="Превью серии из ${series.length} точек"><svg viewBox="0 0 360 104" preserveAspectRatio="none" aria-hidden="true"><path class="grid" d="M0 26H360M0 52H360M0 78H360M90 0V104M180 0V104M270 0V104"></path><polyline points="${points}"></polyline></svg></div>`;
  }
  function objectCard(object) {
    if (!object || typeof object !== 'object') return '';
    const type = objectType(object);
    const rawMetrics = object.metrics && typeof object.metrics === 'object' ? Object.entries(object.metrics) : [];
    const priority = key => {
      const normalized = String(key).toLowerCase();
      if (normalized.includes('p&l') || normalized.includes('pnl') || normalized.includes('net profit')) return 0;
      if (normalized.includes('win')) return 1;
      if (normalized.includes('factor')) return 2;
      if (normalized.includes('drawdown')) return 3;
      if (normalized.includes('trade')) return 4;
      return 8;
    };
    const metrics = rawMetrics.sort((a, b) => priority(a[0]) - priority(b[0])).slice(0, 5).map(([key, value]) => `<span class="${objectMetricTone(key, value)}"><small>${esc(objectMetricLabel(key))}</small><strong>${esc(objectMetricValue(key, value))}</strong></span>`).join('');
    const attested = object.attestation && String(object.attestation.algorithm || '').toLowerCase() === 'sha256';
    const source = [object.instrument, object.timeframe].filter(Boolean).map(esc).join(' · ');
    return `<section class="community-object-card community-object-type-${esc(type.key)}" data-community-rich-object="${esc(type.key)}">
      <header class="community-object-head"><span class="community-object-icon" aria-hidden="true">${esc(type.icon)}</span><div><span class="community-object-kind">${esc(type.label)}</span><h4>${esc(object.title || 'Объект StratForge')}</h4></div>${object.synthetic === true ? '<span class="community-attested" title="Диагностика механизма, не оценка качества модели">SYNTHETIC · диагностика</span>' : attested ? '<span class="community-attested" title="Server-attested SHA-256 snapshot">✓ подтверждено</span>' : ''}</header>
      ${object.summary ? `<p class="community-object-summary">${esc(object.summary)}</p>` : ''}${source ? `<p class="community-object-source">${source}</p>` : ''}
      ${objectChart(object)}
      ${metrics ? `<div class="community-object-metrics">${metrics}</div>` : ''}
      <footer class="community-object-foot"><span>${attested ? 'Immutable public snapshot' : 'StratForge object'}</span>${object.timestamp_utc ? `<time>${esc(fmtDate(object.timestamp_utc))}</time>` : ''}</footer>
    </section>`;
  }
  function postMedia(items) {
    const rows = Array.isArray(items) ? items : [];
    if (!rows.length) return '';
    return `<div class="community-post-media media-${Math.min(3, rows.length)}">${rows.map(item => {
      const url = safeUrl(item.url, '/api/community/attachment/');
      return url ? `<a href="${esc(url)}" target="_blank" rel="noopener"><img src="${esc(url)}" alt="${esc(item.name || 'Изображение публикации')}" loading="lazy"></a>` : '';
    }).join('')}</div>`;
  }
  function commentHtml(comment) {
    if (comment.removed) {
      return `<div class="community-comment community-removed" data-comment-id="${esc(comment.comment_id || '')}">`
        + `<span class="community-removed-mark" aria-hidden="true">⊘</span>`
        + `<div><p>${esc(comment.text || 'Комментарий удалён администрацией')}</p>`
        + `<small>${esc(fmtDate(comment.removed_at_utc || comment.created_at_utc))}</small></div></div>`;
    }
    const author = comment.author || {};
    return `<div class="community-comment" data-comment-id="${esc(comment.comment_id || '')}">${avatar(author, 'xs')}<div><button type="button" data-profile="${esc(author.profile_id || '')}">${esc(author.display_name || 'Участник')}</button><p>${esc(comment.text || '')}</p><small>${esc(fmtDate(comment.created_at_utc))}</small></div></div>`;
  }
  function postHtml(post, surface) {
    if (post.removed) {
      // Your own wall says so rather than quietly losing the entry: a record
      // that vanishes without a word teaches the author nothing.
      return `<article id="community-post-${esc(domId(post.post_id))}" class="community-post-card community-removed" data-post-id="${esc(post.post_id)}">`
        + `<div class="community-removed-body"><span class="community-removed-mark" aria-hidden="true">⊘</span>`
        + `<div><strong>${esc(post.text || 'Публикация удалена администрацией')}</strong>`
        + `<small>${esc(fmtDate(post.removed_at_utc || post.created_at_utc))}</small></div></div></article>`;
    }
    const author = post.author || {};
    const reactions = post.reactions || {};
    const active = String(post.viewer_reaction || '');
    const comments = (post.recent_comments || []).map(commentHtml).join('');
    return `<article id="community-post-${esc(domId(post.post_id))}" class="community-post-card ${surface === 'wall' ? 'community-post-compact' : ''}" data-post-id="${esc(post.post_id)}" data-created="${esc(post.created_at_utc || '')}" data-viewer-reaction="${esc(active)}">
      <header class="community-post-head">
        <button type="button" class="community-post-author" ${author.identity_kind === 'organization' ? `data-org="${esc(author.org_id || '')}"` : `data-profile="${esc(author.profile_id || '')}"`}>${avatar(author, '')}<span><strong>${esc(author.display_name || 'Участник')}</strong><small>@${esc(author.username || '')} · ${esc(author.role_label || '')}</small></span></button>
        <div class="community-post-meta"><time>${esc(fmtDate(post.created_at_utc))}</time><span title="Видимость">${post.visibility === 'followers' ? '◎' : '◉'}</span>${post.is_author ? `<span class="community-post-permanent" title="${esc(PERMANENCE_TITLE)}" aria-label="${esc(PERMANENCE_TITLE)}">∞</span><button type="button" class="community-correct-post" data-correct-post="${esc(post.post_id)}" title="Опубликовать исправление к этой записи">Исправить</button>` : `<button type="button" data-report-post="${esc(post.post_id)}" title="Пожаловаться">•••</button>`}</div>
      </header>
      ${post.corrects_post_id ? `<button type="button" class="community-correction-link" data-goto-post="${esc(post.corrects_post_id)}">Исправление к более ранней публикации</button>` : ''}
      ${(post.corrected_by_post_ids || []).length ? `<button type="button" class="community-correction-link later" data-goto-post="${esc(post.corrected_by_post_ids[0])}">Есть более позднее исправление</button>` : ''}
      ${post.text ? `<div class="community-post-text">${esc(post.text)}</div>` : ''}
      ${(post.hashtags || []).length ? `<div class="community-tags">${post.hashtags.map(tag => `<button type="button" data-hashtag="${esc(tag)}">#${esc(tag)}</button>`).join('')}</div>` : ''}
      ${postMedia(post.attachments)}${objectCard(post.object)}
      <div class="community-post-actions">
        <button type="button" class="community-post-action ${active === 'support' ? 'active' : ''}" data-reaction="support" aria-label="Нравится, ${shortNumber(reactionTotal(reactions))}" title="Нравится"><span class="community-action-icon" aria-hidden="true">${actionIcon('heart')}</span><span class="community-action-label">Нравится</span><span class="community-action-count">${shortNumber(reactionTotal(reactions))}</span></button>
        <button type="button" class="community-post-action" data-focus-comment aria-label="Комментарии, ${shortNumber(post.comment_count)}" title="Комментарии"><span class="community-action-icon" aria-hidden="true">${actionIcon('comment')}</span><span class="community-action-label">Комментарии</span><span class="community-action-count">${shortNumber(post.comment_count)}</span></button>
        <button type="button" class="community-post-action" data-share-post aria-label="Поделиться публикацией" title="Поделиться"><span class="community-action-icon" aria-hidden="true">${actionIcon('share')}</span><span class="community-action-label">Поделиться</span></button>
        <span class="community-action-spacer"></span>
        <button type="button" class="community-post-action community-bookmark-action ${post.bookmarked ? 'active' : ''}" data-bookmark="${post.bookmarked ? '1' : '0'}" aria-label="${post.bookmarked ? 'Убрать из закладок' : 'Сохранить в закладки'}" title="${post.bookmarked ? 'Убрать из закладок' : 'Сохранить'}"><span class="community-action-icon" aria-hidden="true">${actionIcon('bookmark')}</span><span class="community-action-label">${post.bookmarked ? 'Сохранено' : 'Сохранить'}</span></button>
      </div>
      <div class="community-comments">${comments}<form class="community-comment-form"><input maxlength="1200" placeholder="Ответить по существу…"><button type="submit" aria-label="Отправить комментарий">↑</button></form></div>
    </article>`;
  }

  function wirePeopleActions(root) {
    qa('[data-org]', root).forEach(button => {
      button.onclick = () => openOrganization(button.dataset.org);
    });
    qa('[data-profile]', root).forEach(button => {
      button.onclick = () => { const id = button.dataset.profile; if (id) openProfile(id); };
    });
    qa('[data-follow]', root).forEach(button => {
      button.onclick = async () => {
        if (button.disabled) return;
        button.disabled = true;
        try {
          await API.http.communityV2Follow(button.dataset.follow, button.dataset.following !== '1');
          await loadFeed(true);
        } catch (error) { UI.reportError(error); }
        finally { button.disabled = false; }
      };
    });
  }
  function wirePostActions(root) {
    wirePeopleActions(root);
    qa('.community-post-card', root).forEach(card => {
      const postId = card.dataset.postId;
      qa('[data-reaction]', card).forEach(button => button.onclick = async () => {
        const current = card.dataset.viewerReaction || '';
        const next = current === button.dataset.reaction ? '' : button.dataset.reaction;
        try { const out = await API.http.communityV2Reaction(postId, next); replacePost(out.post); }
        catch (error) { UI.reportError(error); }
      });
      const bookmark = q('[data-bookmark]', card);
      if (bookmark) bookmark.onclick = async () => {
        try {
          const out = await API.http.communityV2Bookmark(postId, bookmark.dataset.bookmark !== '1'); replacePost(out.post);
          if (STATE.wallTab === 'saved') await loadWall();
        }
        catch (error) { UI.reportError(error); }
      };
      const focus = q('[data-focus-comment]', card);
      if (focus) focus.onclick = () => { const input = q('.community-comment-form input', card); if (input) input.focus(); };
      const share = q('[data-share-post]', card);
      if (share) share.onclick = async () => {
        const url = `${window.location.href.split('#')[0]}#community-post-${encodeURIComponent(postId)}`;
        const nav = window.navigator || {};
        try {
          if (typeof nav.share === 'function') await nav.share({ title: 'Публикация StratForge', url });
          else if (nav.clipboard && typeof nav.clipboard.writeText === 'function') { await nav.clipboard.writeText(url); UI.toast('Ссылка на публикацию скопирована'); }
          else UI.toast('Ссылка на публикацию готова');
        } catch (error) {
          if (!error || error.name !== 'AbortError') UI.reportError(error);
        }
      };
      const form = q('.community-comment-form', card);
      if (form) form.onsubmit = async event => {
        event.preventDefault();
        const input = q('input', form); const text = input ? input.value.trim() : '';
        if (!text) return;
        try { const out = await API.http.communityV2Comment(postId, text); replacePost(out.post); }
        catch (error) { UI.reportError(error); }
      };
      const report = q('[data-report-post]', card);
      if (report) report.onclick = async () => {
        const reason = prompt('Кратко опишите нарушение:');
        if (!reason || !reason.trim()) return;
        try { await API.http.communityV2Report({ target_id: postId, target_type: 'post', reason: reason.trim() }); UI.toast('Жалоба передана на проверку'); }
        catch (error) { UI.reportError(error); }
      };
      qa('[data-goto-post]', card).forEach(button => button.onclick = () => {
        const target = q(`#community-post-${cssEscape(domId(button.dataset.gotoPost))}`);
        if (target && target.scrollIntoView) target.scrollIntoView({ block: 'center', behavior: 'smooth' });
        else UI.toast('Связанная публикация не в этом списке');
      });
      const correct = q('[data-correct-post]', card);
      if (correct) correct.onclick = () => startCorrection({
        post_id: correct.dataset.correctPost,
        created_at_utc: card.dataset.created || '',
      });
      qa('[data-hashtag]', card).forEach(button => button.onclick = () => {
        const search = q('#community-search'); if (search) search.value = '#' + button.dataset.hashtag;
        STATE.query = ''; loadFeed(true, { hashtag: button.dataset.hashtag });
      });
    });
  }
  function replacePost(post) {
    if (!post) return;
    const selector = `.community-post-card[data-post-id="${cssEscape(post.post_id || '')}"]`;
    const existing = qa(selector);
    if (!existing.length) { loadFeed(true); return; }
    existing.forEach(card => {
      const shell = document.createElement('div'); shell.innerHTML = postHtml(post, card.classList.contains('community-post-compact') ? 'wall' : 'feed');
      const next = shell.firstElementChild; card.replaceWith(next); wirePostActions(next);
    });
  }

  function scrollToSharedPost() {
    const hash = String(window.location.hash || '').replace(/^#/, '');
    if (!hash.startsWith('community-post-')) return;
    let target = hash;
    try { target = decodeURIComponent(hash); } catch (error) { /* keep the safe hash */ }
    const node = document.getElementById(target);
    if (node) window.requestAnimationFrame(() => node.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }

  function relevanceScore(post) {
    const reactions = post && post.reactions && typeof post.reactions === 'object' ? post.reactions : {};
    const reactionTotal = Object.values(reactions).reduce((sum, value) => sum + (Number(value) || 0), 0);
    return reactionTotal + (Number(post && post.comment_count) || 0) * 2 + (Number(post && post.share_count) || 0) * 3;
  }
  function sortPosts(posts) {
    const rows = Array.isArray(posts) ? posts.slice() : [];
    return rows.sort((left, right) => {
      if (STATE.sort === 'relevant') {
        const delta = relevanceScore(right) - relevanceScore(left);
        if (delta) return delta;
      }
      return new Date(right.created_at_utc || 0).getTime() - new Date(left.created_at_utc || 0).getTime();
    });
  }
  function updateWallCounts(profile, savedCount) {
    const postCount = q('#community-wall-post-count');
    const saved = q('#community-wall-saved-count');
    const savedStat = q('#community-profile-saved-stat');
    const stats = (profile && profile.stats) || {};
    if (postCount) postCount.textContent = `(${shortNumber(stats.posts)})`;
    if (saved) saved.textContent = `(${shortNumber(savedCount)})`;
    if (savedStat) savedStat.textContent = shortNumber(savedCount);
  }
  async function loadWall() {
    const host = q('#community-profile-wall-feed');
    const viewer = STATE.viewer || (STATE.feed && STATE.feed.viewer);
    if (!host || !viewer || !viewer.profile_id) return;
    const requestId = ++STATE.wallRequest;
    host.innerHTML = '<div class="community-skeleton post"></div>';
    try {
      let doc; let savedDoc = null;
      if (STATE.wallTab === 'saved') {
        doc = await API.http.communityV2Saved({ limit: 30 });
        savedDoc = doc;
      } else {
        [doc, savedDoc] = await Promise.all([
          API.http.communityV2Profile(viewer.profile_id, { posts_limit: 30 }),
          API.http.communityV2Saved({ limit: 1 }),
        ]);
      }
      if (requestId !== STATE.wallRequest) return;
      const profile = doc.profile || viewer;
      const savedCount = Number((savedDoc && savedDoc.total_visible) || (savedDoc && savedDoc.posts && savedDoc.posts.length) || 0);
      STATE.wallSavedCount = savedCount;
      if (doc.profile) renderViewer(profile);
      updateWallCounts(profile, savedCount);
      const posts = sortPosts(doc.posts || []);
      // The registration entry heads the member's own wall too, and only the
      // wall — bookmarks are someone else's posts, not this profile's history.
      const milestone = STATE.wallTab === 'saved' ? '' : registrationCardHtml(doc.registration, profile);
      const body = posts.map(post => postHtml(post, 'wall')).join('') || renderEmpty(
        STATE.wallTab === 'saved' ? 'Закладок пока нет' : 'На стене пока тихо',
        STATE.wallTab === 'saved' ? 'Сохранённые rich-публикации появятся здесь.' : 'Опубликуйте идею или подтверждённый результат.',
      );
      host.innerHTML = milestone + body;
      wirePostActions(host);
    } catch (error) {
      if (requestId === STATE.wallRequest) UI.renderError(host, error, loadWall);
    }
  }

  async function loadFeed(reset, filters) {
    if (STATE.loading) return;
    STATE.loading = true;
    const host = q('#community-feed');
    if (reset && host) host.innerHTML = '<div class="community-feed-loading"><div class="community-skeleton post"></div><div class="community-skeleton post"></div></div>';
    setStatus('Обновляем…', 'loading');
    try {
      const query = Object.assign({
        scope: STATE.view === 'following' ? 'following' : 'for-you',
        cursor: reset ? '' : STATE.cursor,
        limit: 20,
        q: STATE.query,
      }, filters || {});
      const request = STATE.view === 'saved' ? API.http.communityV2Saved(query) : API.http.communityV2Feed(query);
      const [doc, people] = await Promise.all([request, API.http.communityV2Profiles({ q: STATE.query, limit: 40 })]);
      STATE.feed = doc; STATE.cursor = doc.next_cursor || '';
      applyPermanenceNotice(doc);
      renderViewer(doc.viewer);
      renderPeople((people && people.profiles) || doc.recommended_profiles || []);
      const posts = sortPosts(doc.posts || []);
      if (host) {
        const peopleSearch = STATE.query && people && (people.profiles || []).length
          ? `<section class="community-search-results"><h3>Участники</h3>${(people.profiles || []).slice(0, 6).map(profile => `<button type="button" data-profile="${esc(profile.profile_id)}">${avatar(profile, 'sm')}<span><strong>${esc(profile.display_name)}</strong><small>@${esc(profile.username)}</small></span></button>`).join('')}</section>` : '';
        const content = posts.map(postHtml).join('');
        if (reset) host.innerHTML = peopleSearch + (content || renderEmpty(
          STATE.view === 'saved' ? 'Сохранённых публикаций пока нет' : 'Лента пока пуста',
          STATE.view === 'following' ? 'Подпишитесь на участников или откройте рекомендации.' : 'Сделайте первую публикацию без раскрытия приватного workspace.',
        ));
        else host.insertAdjacentHTML('beforeend', content);
        wirePostActions(host);
        scrollToSharedPost();
      }
      STATE.loadMoreVisible = !!STATE.cursor;
      const more = q('#community-load-more'); if (more) more.hidden = !STATE.cursor || STATE.centerMode === 'profile';
      setStatus(`${Number(doc.total_visible || posts.length)} публикаций`, 'ready');
      await loadWall();
    } catch (error) {
      if (host) UI.renderError(host, error, () => loadFeed(true));
      setStatus('Не удалось обновить', 'error');
    } finally { STATE.loading = false; }
  }

  async function readImages(files, target) {
    const state = target === 'channel' ? STATE.pendingChannelFiles : STATE.pendingPostFiles;
    const list = Array.from(files || []);
    const available = Math.max(0, 3 - state.length);
    if (list.length > available) UI.toast('Можно приложить не более трёх изображений');
    for (const file of list.slice(0, available)) {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 2 * 1024 * 1024) {
        UI.toast('Подходит PNG/JPEG/WebP до 2 МБ'); continue;
      }
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(new Error('Не удалось прочитать файл'));
        reader.readAsDataURL(file);
      });
      state.push({ name: file.name, data_url: dataUrl });
    }
    renderPending(target);
  }
  function renderPending(target) {
    const state = target === 'channel' ? STATE.pendingChannelFiles : STATE.pendingPostFiles;
    const host = q(target === 'channel' ? '#c-attachments' : '#community-pending-media');
    if (!host) return;
    host.innerHTML = state.map((item, index) => `<span><strong>${esc(item.name)}</strong><button type="button" data-remove-media="${index}" aria-label="Убрать">×</button></span>`).join('');
    qa('[data-remove-media]', host).forEach(button => button.onclick = () => { state.splice(Number(button.dataset.removeMedia), 1); renderPending(target); });
  }
  // Exactly one composer exists, and it lives on the member's own wall. The
  // control is a two-state radio group rather than a settings row: the reader
  // is choosing where this post goes, not configuring the product.
  // The selector appears only when the server reports an identity the caller
  // may publish as beyond their own profile. A member without company rights
  // never sees it, and the server checks the permission again on publish.
  async function loadPublishIdentities() {
    const wrap = q('#community-publish-as-wrap');
    const select = q('#community-publish-as');
    if (!wrap || !select) return;
    try {
      const doc = await API.http.communityV2Identities();
      const rows = (doc && doc.identities) || [];
      STATE.identities = rows;
      const extra = rows.filter(row => row.identity_kind !== 'profile');
      if (!extra.length) { wrap.hidden = true; select.innerHTML = ''; return; }
      select.innerHTML = rows.map(row => `<option value="${esc(row.identity_kind === 'organization' ? row.id : '')}">${esc(row.identity_kind === 'organization' ? row.display_name : 'Мой профиль')}</option>`).join('');
      wrap.hidden = false;
    } catch (error) {
      // Not being able to ask is not a reason to offer the choice.
      wrap.hidden = true;
    }
  }
  function composerPublishAs() {
    const select = q('#community-publish-as');
    return select && !q('#community-publish-as-wrap').hidden ? String(select.value || '') : '';
  }
  function composerVisibility() {
    const active = q('[data-post-visibility].active');
    const value = active ? String(active.dataset.postVisibility || '') : '';
    return value === 'private' ? 'private' : 'network';
  }
  function wireComposerVisibility() {
    qa('[data-post-visibility]').forEach(button => {
      button.onclick = () => {
        qa('[data-post-visibility]').forEach(other => {
          const on = other === button;
          other.classList.toggle('active', on);
          other.setAttribute('aria-checked', on ? 'true' : 'false');
        });
      };
    });
  }
  // A correction never edits the original: it is a new publication that names
  // the one it corrects, so the timeline reads forward.
  function renderCorrectionTarget() {
    const bar = q('#community-correction-target');
    if (!bar) return;
    const target = STATE.correctionTarget;
    bar.hidden = !target;
    if (!target) return;
    const when = target.created_at_utc ? fmtDate(target.created_at_utc) : '';
    bar.innerHTML = `<span>Исправление к публикации${when ? ' от ' + esc(when) : ''}</span>`
      + '<button type="button" data-cancel-correction aria-label="Отменить исправление">Отменить</button>';
    const cancel = q('[data-cancel-correction]', bar);
    if (cancel) cancel.onclick = () => { STATE.correctionTarget = null; renderCorrectionTarget(); };
  }
  function startCorrection(target) {
    STATE.correctionTarget = target;
    renderCorrectionTarget();
    const input = q('#community-post-text');
    if (input) { input.focus(); input.scrollIntoView({ block: 'center' }); }
  }
  async function submitPost() {
    const input = q('#community-post-text'); const submit = q('#community-post-submit');
    const text = input ? input.value.trim() : '';
    if (!text && !STATE.pendingPostFiles.length) { UI.toast('Добавьте текст или изображение'); return; }
    if (submit) submit.disabled = true;
    try {
      // The author is whoever the composer is publishing as. Today that is
      // always the signed-in member, and the server derives it from the
      // session; keeping it a value rather than an assumption is what lets a
      // company identity be added later without moving the publish path.
      await API.http.communityV2Post({
        text, attachments: STATE.pendingPostFiles, visibility: composerVisibility(),
        publish_as: composerPublishAs(),
        corrects_post_id: (STATE.correctionTarget || {}).post_id || '',
      });
      const wasCorrection = !!STATE.correctionTarget;
      STATE.correctionTarget = null; renderCorrectionTarget();
      if (input) input.value = '';
      STATE.pendingPostFiles = []; renderPending('post');
      // The post belongs to my wall either way; Recommendation only refreshes
      // because a public post may now be eligible for it.
      const publishedAs = composerPublishAs();
      if (publishedAs) { if (STATE.openOrgId === publishedAs) await openOrganization(publishedAs); }
      else await loadWall();
      if (composerVisibility() === 'network') { STATE.view = 'for-you'; syncViewButtons(); await loadFeed(true); }
      UI.toast(wasCorrection
        ? 'Исправление опубликовано; прежняя запись осталась на месте'
        : (composerVisibility() === 'network'
          ? 'Опубликовано на вашей стене и в SF Social'
          : 'Опубликовано только на вашей стене'));
    } catch (error) { UI.reportError(error); }
    finally { if (submit) submit.disabled = false; }
  }

  async function openResultPublisher() {
    const drawer = UI.drawer('Подтверждённый результат', '<div class="community-feed-loading"><div class="community-skeleton compact"></div><div class="community-skeleton compact"></div></div>');
    const host = q('.drawer-b', drawer);
    try {
      const doc = await API.http.communityV2Objects({ source_type: 'result', limit: 20 });
      const rows = (doc && doc.objects) || [];
      if (!rows.length) {
        host.innerHTML = renderEmpty('Нет завершённых результатов', 'Сначала завершите Demo или Backtest. Незавершённые и чужие job не публикуются.');
        return;
      }
      host.innerHTML = `<div class="col gap-md"><p class="muted"><strong>server-attested snapshot:</strong> StratForge формирует карточку результата на сервере. Клиент не может изменить метрики или выдать произвольный P&amp;L за подтверждённый результат.</p>${rows.map(row => `<article class="community-object-picker">${objectCard(row)}<button type="button" class="btn primary sm" data-publish-result="${esc(row.source_id || '')}">Опубликовать</button></article>`).join('')}</div>`;
      qa('[data-publish-result]', host).forEach(button => button.onclick = async () => {
        button.disabled = true;
        try {
          const input = q('#community-post-text');
          await API.http.communityV2PublishObject({
            source_type: 'job_result', source_id: button.dataset.publishResult,
            text: input ? input.value.trim() : '',
            visibility: composerVisibility(),
          });
          if (input) input.value = '';
          UI.closeDrawer(); STATE.view = 'for-you'; syncViewButtons();
          await loadFeed(true); UI.toast('Подтверждённый результат опубликован');
        } catch (error) { UI.reportError(error); button.disabled = false; }
      });
    } catch (error) { UI.renderError(host, error, openResultPublisher); }
  }

  function syncViewButtons() {
    qa('[data-community-view]').forEach(button => button.classList.toggle('active', button.dataset.communityView === STATE.view));
    qa('[data-community-tab]').forEach(button => {
      const active = button.dataset.communityTab === STATE.view || (STATE.view === 'saved' && false);
      button.classList.toggle('active', active); button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    const channels = STATE.view === 'channels';
    const channelsView = q('#community-channels-view'); const feed = q('#community-feed');
    const composer = q('#community-composer-card'); const more = q('#community-load-more');
    const sort = q('.community-sort'); const title = q('#community-stream-title');
    if (title) title.textContent = STREAM_TITLES[STATE.view] || STREAM_TITLES['for-you'];
    if (sort) sort.hidden = channels;
    if (channelsView) channelsView.hidden = !channels;
    if (feed) feed.hidden = channels;
    // The composer is not part of the centre stream any more; it is the one
    // place a post is created and it is always available on my own wall.
    if (composer) composer.hidden = false;
    if (more && channels) { more.hidden = true; STATE.loadMoreVisible = false; }
  }
  async function setView(view) {
    if (view === 'profile') {
      const viewer = STATE.feed && STATE.feed.viewer;
      if (viewer) await openProfile(viewer.profile_id);
      return;
    }
    STATE.view = ['for-you', 'following', 'saved', 'channels'].includes(view) ? view : 'for-you';
    STATE.cursor = ''; STATE.openProfileId = '';
    setCenterMode(STATE.view === 'channels' ? 'channels' : 'stream');
    syncViewButtons();
    if (STATE.view === 'channels') await loadChannels(); else await loadFeed(true);
  }
  function syncSortButtons() {
    qa('[data-community-sort]').forEach(button => {
      const active = button.dataset.communitySort === STATE.sort;
      button.classList.toggle('active', active); button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }
  function syncWallTabs() {
    qa('[data-community-wall-tab]').forEach(button => {
      const active = button.dataset.communityWallTab === STATE.wallTab;
      button.classList.toggle('active', active); button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }

  // A member's wall is a place inside Community, not an overlay on top of it.
  // The centre column carries the current context and offers the way back; the
  // right column stays the signed-in member throughout.
  function setCenterMode(mode) {
    STATE.centerMode = mode;
    const showingProfile = mode === 'profile';
    const profileView = q('#community-profile-view');
    if (profileView) profileView.hidden = !showingProfile;
    const toolbar = document.querySelector('.community-stream-toolbar');
    if (toolbar) toolbar.hidden = showingProfile;
    // Only the stream itself yields to a member's wall. The composer lives in
    // the right column and belongs to the signed-in member, so it stays put
    // whoever is open in the centre.
    const feed = q('#community-feed');
    if (feed) feed.hidden = showingProfile;
    const more = q('#community-load-more');
    if (more) more.hidden = showingProfile ? true : !STATE.loadMoreVisible;
    if (showingProfile) {
      const channels = q('#community-channels-view');
      if (channels) channels.hidden = true;
    }
  }
  // The registration entry is server-derived from the profile's own fields, so
  // it cannot be duplicated, deleted or back-dated here. Absent facts are left
  // out rather than filled in.
  function registrationCardHtml(registration, profile) {
    if (!registration || !registration.registered_at_utc) return '';
    const name = String((profile && profile.display_name) || 'Участник');
    const facts = [
      '<span><small>Дата регистрации</small><strong>' + esc(fmtDate(registration.registered_at_utc)) + '</strong></span>',
    ];
    if (registration.activated_at_utc) {
      facts.push('<span><small>Дата активации</small><strong>' + esc(fmtDate(registration.activated_at_utc)) + '</strong></span>');
    }
    if (registration.account_status) {
      facts.push('<span><small>Статус аккаунта</small><strong>' + esc(registration.account_status) + '</strong></span>');
    }
    return '<article class="community-milestone" aria-label="Системная запись">'
      + '<header><span class="community-milestone-mark" aria-hidden="true">◈</span>'
      + '<div><strong>Поздравляем с регистрацией в StratForge!</strong>'
      + '<small>Системная запись · ' + esc(name) + '</small></div>'
      + '<span class="community-milestone-tag">Защищённая запись</span></header>'
      + '<p>Профиль создан в StratForge. Доступны модули стратегий, графиков и отчётов.</p>'
      + '<div class="community-milestone-facts">' + facts.join('') + '</div>'
      + '</article>';
  }
  // An organization opens in the centre exactly like a member, so the reader
  // keeps one mental model and the right column keeps belonging to them.
  async function openOrganization(orgId) {
    if (!orgId) return;
    const host = q('#community-profile-detail-center');
    if (!host) return;
    STATE.openOrgId = orgId; STATE.openProfileId = '';
    setCenterMode('profile');
    const backLabel = q('#community-profile-back-label');
    if (backLabel) backLabel.textContent = STREAM_TITLES[STATE.view] || 'Recommendation';
    host.innerHTML = '<div class="community-skeleton profile"></div>';
    try {
      const doc = await API.http.communityV2Organization(orgId, { posts_limit: 30 });
      if (STATE.openOrgId !== orgId) return;
      const org = doc.organization || {};
      const stats = org.stats || {};
      const follow = '<button type="button" class="btn ' + (org.is_following ? 'ghost' : 'primary')
        + '" data-follow-org="' + esc(org.org_id) + '" data-following="' + (org.is_following ? '1' : '0')
        + '">' + (org.is_following ? 'Вы читаете' : 'Подписаться') + '</button>';
      const wall = (doc.posts || []).map(postHtml).join('')
        || renderEmpty('На странице пока тихо', 'Публикации компании появятся здесь.');
      host.innerHTML = '<div class="community-profile-hero"><div class="community-profile-cover"><span>SF</span></div>'
        + '<div class="community-avatar xxl community-org-avatar" aria-hidden="true">SF</div>'
        + '<div class="community-profile-identity"><span class="community-role">Организация</span>'
        + '<h2 id="community-profile-name">' + esc(org.display_name) + '</h2>'
        + '<span>@' + esc(org.username) + '</span>'
        + '<p>' + esc(org.description || 'Описание пока не заполнено.') + '</p>'
        + '<div class="community-profile-stats">'
        + '<span><small>Публикации</small><strong>' + shortNumber(stats.posts) + '</strong></span>'
        + '<span><small>Подписчики</small><strong>' + shortNumber(stats.followers) + '</strong></span>'
        + '<span><small>Редакторы</small><strong>' + shortNumber(stats.editors) + '</strong></span></div>'
        + '<div class="community-profile-actions">' + follow + '</div></div></div>'
        + '<div class="community-profile-wall"><h3>Стена ' + esc(org.display_name) + '</h3>'
        + orgMilestoneHtml(doc.registration, org) + wall + '</div>';
      wirePeopleActions(host); wirePostActions(host);
      const followBtn = q('[data-follow-org]', host);
      if (followBtn) followBtn.onclick = async () => {
        followBtn.disabled = true;
        try {
          await API.http.communityV2FollowOrganization(org.org_id, followBtn.dataset.following !== '1');
          await openOrganization(org.org_id);
        } catch (error) { UI.reportError(error); followBtn.disabled = false; }
      };
    } catch (error) { UI.renderError(host, error, () => openOrganization(orgId)); }
  }
  // The organization's own first record: when the page was created, which is
  // not when anybody registered an account.
  function orgMilestoneHtml(registration, org) {
    if (!registration || !registration.created_at_utc) return '';
    return '<article class="community-milestone" aria-label="Системная запись">'
      + '<header><span class="community-milestone-mark" aria-hidden="true">◈</span>'
      + '<div><strong>' + esc(org.display_name) + ' — официальная страница создана</strong>'
      + '<small>Системная запись · StratForge</small></div>'
      + '<span class="community-milestone-tag">Защищённая запись</span></header>'
      + '<div class="community-milestone-facts"><span><small>Дата создания</small><strong>'
      + esc(fmtDate(registration.created_at_utc)) + '</strong></span></div>'
      + '</article>';
  }
  async function openProfile(profileId) {
    if (!profileId) return;
    const host = q('#community-profile-detail-center');
    if (!host) return;
    STATE.openProfileId = profileId; STATE.openOrgId = '';
    setCenterMode('profile');
    const backLabel = q('#community-profile-back-label');
    if (backLabel) backLabel.textContent = STREAM_TITLES[STATE.view] || 'Recommendation';
    host.innerHTML = '<div class="community-skeleton profile"></div>';
    try {
      const doc = await API.http.communityV2Profile(profileId, { posts_limit: 30 });
      if (STATE.openProfileId !== profileId) return;
      const profile = doc.profile || {};
      const actions = profile.is_self
        ? '<button type="button" class="btn primary" data-modal-edit>Редактировать профиль</button>'
        : '<button type="button" class="btn ' + (profile.is_following ? 'ghost' : 'primary') + '" data-follow="' + esc(profile.profile_id) + '" data-following="' + (profile.is_following ? '1' : '0') + '">' + (profile.is_following ? 'Вы читаете' : 'Подписаться') + '</button>'
          + (profile.can_message ? '<button type="button" class="btn ghost" data-message-profile="' + esc(profile.profile_id) + '">Написать</button>' : '')
          + '<button type="button" class="btn ghost" data-block-profile="' + esc(profile.profile_id) + '">Заблокировать</button>';
      const wall = (doc.posts || []).map(postHtml).join('')
        || renderEmpty('На стене пока тихо', 'Публикации появятся здесь.');
      host.innerHTML = '<div class="community-profile-hero"><div class="community-profile-cover"><span>SF</span></div>'
        + avatar(profile, 'xxl')
        + '<div class="community-profile-identity"><span class="community-role">' + esc(profile.role_label) + '</span>'
        + '<h2 id="community-profile-name">' + esc(profile.display_name) + '</h2>'
        + '<span>@' + esc(profile.username) + '</span>'
        + '<p>' + esc(profile.bio || 'Описание пока не заполнено.') + '</p>'
        + profileStats(profile)
        + '<div class="community-profile-actions">' + actions + '</div></div></div>'
        + '<div class="community-profile-wall"><h3>Стена ' + esc(profile.display_name || 'участника') + '</h3>'
        + registrationCardHtml(doc.registration, profile) + wall + '</div>';
      wirePeopleActions(host); wirePostActions(host);
      const edit = q('[data-modal-edit]', host); if (edit) edit.onclick = () => editProfile(profile);
      const message = q('[data-message-profile]', host); if (message) message.onclick = () => startMessage(message.dataset.messageProfile);
      const block = q('[data-block-profile]', host); if (block) block.onclick = async () => {
        if (!confirm('Заблокировать участника? Подписки будут удалены, личные сообщения станут недоступны.')) return;
        try { await API.http.communityV2Block(block.dataset.blockProfile, true); closeProfile(); await loadFeed(true); }
        catch (error) { UI.reportError(error); }
      };
    } catch (error) { UI.renderError(host, error, () => openProfile(profileId)); }
  }
  function closeProfile() {
    STATE.openProfileId = ''; STATE.openOrgId = '';
    setCenterMode(STATE.view === 'channels' ? 'channels' : 'stream');
    syncModalLock();
  }

  async function startMessage(profileId) {
    try {
      const out = await API.http.sfChatStartConversation(profileId);
      // The member's wall stays where it is. Dismissing it here was right while
      // the profile was an overlay the chat would have opened behind; now it is
      // the centre context, and closing SF Chat must return the reader to it.
      const conversationId = out && out.conversation && out.conversation.conversation_id;
      if (window.UI && typeof UI.openSFChat === 'function') await UI.openSFChat({ conversationId, conversationType: 'human' });
      else if (window.UI && typeof UI.openOrchestrator === 'function') await UI.openOrchestrator({ conversationId, conversationType: 'human' });
    } catch (error) { UI.reportError(error); }
  }
  function syncModalLock() {
    const visibilityModal = q('#community-visibility-modal');
    const visibilityOpen = visibilityModal && !visibilityModal.hidden;
    document.body.classList.toggle('community-modal-open', Boolean(visibilityOpen));
  }
  function openProfileVisibility(profile) {
    const modal = q('#community-visibility-modal');
    const network = q('#community-visibility-network');
    const messages = q('#community-visibility-messages-select');
    if (!modal || !network || !messages) return;
    network.checked = profile && profile.profile_visibility !== 'followers';
    messages.value = (profile && profile.allow_messages) || 'everyone';
    modal.hidden = false;
    syncModalLock();
    network.focus();
  }
  function closeProfileVisibility() {
    const modal = q('#community-visibility-modal');
    if (modal) modal.hidden = true;
    syncModalLock();
  }
  async function saveProfileVisibility(event) {
    event.preventDefault();
    const submit = q('#community-visibility-form button[type="submit"]');
    const network = q('#community-visibility-network');
    const messages = q('#community-visibility-messages-select');
    if (!submit || !network || !messages) return;
    submit.disabled = true;
    try {
      await API.http.communityV2UpdateProfile({
        profile_visibility: network.checked ? 'network' : 'followers',
        allow_messages: messages.value,
      });
      closeProfileVisibility();
      await loadFeed(true);
      UI.toast('Настройки видимости сохранены');
    } catch (error) {
      UI.reportError(error);
    } finally {
      submit.disabled = false;
    }
  }
  function editProfile(profile) {
    const drawer = UI.drawer('Профиль Community', `<div class="col gap-lg"><div class="field"><label>Отображаемое имя</label><input id="community-edit-name" maxlength="80" value="${esc(profile.display_name || '')}"></div><div class="field"><label>Username</label><input id="community-edit-username" maxlength="30" value="${esc(profile.username || '')}"></div><div class="field"><label>О себе</label><textarea id="community-edit-bio" rows="5" maxlength="500">${esc(profile.bio || '')}</textarea></div><div class="form-row"><div class="field"><label>Профиль видят</label><select id="community-edit-visibility"><option value="network" ${profile.profile_visibility !== 'followers' ? 'selected' : ''}>Вся сеть</option><option value="followers" ${profile.profile_visibility === 'followers' ? 'selected' : ''}>Подписчики</option></select></div><div class="field"><label>Кто может писать</label><select id="community-edit-messages"><option value="everyone">Все участники</option><option value="following">Только мои подписки</option><option value="nobody">Никто</option></select></div></div><button type="button" class="btn primary" id="community-edit-save">Сохранить</button></div>`);
    const policy = q('#community-edit-messages', drawer); if (policy) policy.value = profile.allow_messages || 'everyone';
    q('#community-edit-save', drawer).onclick = async event => {
      event.currentTarget.disabled = true;
      try {
        await API.http.communityV2UpdateProfile({ display_name: q('#community-edit-name', drawer).value, username: q('#community-edit-username', drawer).value, bio: q('#community-edit-bio', drawer).value, profile_visibility: q('#community-edit-visibility', drawer).value, allow_messages: q('#community-edit-messages', drawer).value });
        UI.closeDrawer(); await loadFeed(true); UI.toast('Профиль обновлён');
      } catch (error) { UI.reportError(error); event.currentTarget.disabled = false; }
    };
  }

  function channelAttachments(items) {
    return (Array.isArray(items) ? items : []).map(item => {
      const url = safeUrl(item.url, '/api/community/attachment/');
      return url ? `<a class="community-attachment" href="${esc(url)}" target="_blank" rel="noopener">▧ ${esc(item.name || 'image')}</a>` : '';
    }).join('');
  }
  function renderChannels(doc) {
    const pills = q('#c-channels');
    if (pills) pills.innerHTML = (doc.channels || []).map(item => `<button type="button" class="${item.id === STATE.channel ? 'active' : ''}" data-channel="${esc(item.id)}"># ${esc(item.label)}</button>`).join('');
    qa('[data-channel]', pills).forEach(button => button.onclick = () => { STATE.channel = button.dataset.channel || 'general'; STATE.threadRootId = ''; loadChannels(); });
    const selected = (doc.channels || []).find(item => item.id === STATE.channel) || {};
    q('#c-channel-title').textContent = selected.label || 'Канал'; q('#c-channel-hint').textContent = selected.hint || '';
    const chat = q('#c-chat');
    if (chat) chat.innerHTML = (doc.messages || []).map(message => `<article class="community-channel-message ${message.thread_root_id ? 'reply' : ''}"><div class="community-channel-author"><strong>${esc(message.display_name || 'Участник')}</strong><time>${esc(fmtDate(message.created_at_utc))}</time></div><p>${esc(message.text || '')}</p>${channelAttachments(message.attachments)}<button type="button" data-channel-reply="${esc(message.thread_root_id || message.message_id)}">Ответить</button></article>`).join('') || renderEmpty('В канале пока тихо', 'Начните рабочее обсуждение.');
    qa('[data-channel-reply]', chat).forEach(button => button.onclick = () => { STATE.threadRootId = button.dataset.channelReply; renderThreadState(); q('#c-text').focus(); });
    const objects = q('#c-channel-objects');
    if (objects) {
      const reports = (doc.shared_reports || []).slice(0, 5).map(row => `<article><span>ОТЧЁТ</span><strong>${esc(row.title)}</strong><p>${esc(row.summary || '')}</p></article>`).join('');
      const strategies = (doc.strategies || []).slice(0, 5).map(row => `<article><span>СТРАТЕГИЯ</span><strong>${esc(row.title)}</strong><p>${esc(row.display_name || '')}</p><button type="button" class="btn sm ghost" data-copy-strategy="${esc(row.strategy_id)}">Запросить импорт</button></article>`).join('');
      const requests = (doc.requests || []).slice(0, 5).map(row => `<article><span>ЗАПРОС</span><strong>${esc(row.title)}</strong><p>${esc(row.status || 'open')}</p></article>`).join('');
      objects.innerHTML = (reports || strategies || requests) ? `<h3>Объекты workspace</h3><div>${reports}${strategies}${requests}</div>` : '';
      qa('[data-copy-strategy]', objects).forEach(button => button.onclick = async () => { try { await API.http.communityCopy({ strategy_id: button.dataset.copyStrategy }); UI.toast('Создан безопасный запрос pending_import'); } catch (error) { UI.reportError(error); } });
    }
    renderThreadState();
  }
  function renderThreadState() {
    const host = q('#c-thread-state'); if (!host) return;
    if (!STATE.threadRootId) { host.hidden = true; host.innerHTML = ''; return; }
    host.hidden = false; host.innerHTML = `<span>Ответ в ветке</span><button type="button" class="btn ghost sm" id="c-thread-cancel">Отменить</button>`;
    q('#c-thread-cancel').onclick = () => { STATE.threadRootId = ''; renderThreadState(); };
  }
  async function loadChannels() {
    try { STATE.channelFeed = await API.http.communityFeed({ channel: STATE.channel }); renderChannels(STATE.channelFeed); setStatus('Workspace-каналы', 'ready'); }
    catch (error) { UI.renderError(q('#c-chat'), error, loadChannels); }
  }
  async function sendChannelMessage() {
    const input = q('#c-text'); const body = input ? input.value.trim() : '';
    if (!body) { UI.toast('Введите сообщение'); return; }
    try {
      await API.http.communityMessage({ text: body, channel_id: STATE.channel, thread_root_id: STATE.threadRootId, attachments: STATE.pendingChannelFiles });
      input.value = ''; STATE.threadRootId = ''; STATE.pendingChannelFiles = []; renderPending('channel'); await loadChannels();
    } catch (error) { UI.reportError(error); }
  }

  UI.ready(() => {
    qa('[data-community-view]').forEach(button => button.onclick = () => setView(button.dataset.communityView));
    qa('[data-community-tab]').forEach(button => button.onclick = () => setView(button.dataset.communityTab));
    qa('[data-community-sort]').forEach(button => button.onclick = () => {
      STATE.sort = button.dataset.communitySort === 'relevant' ? 'relevant' : 'recent';
      syncSortButtons(); loadFeed(true);
    });
    qa('[data-community-wall-tab]').forEach(button => button.onclick = () => {
      STATE.wallTab = button.dataset.communityWallTab === 'saved' ? 'saved' : 'posts';
      syncWallTabs(); loadWall();
    });
    qa('[data-community-profile-close]').forEach(button => button.onclick = closeProfile);
    const backButton = q('#community-profile-back'); if (backButton) backButton.onclick = closeProfile;
    qa('[data-community-visibility-close]').forEach(button => button.onclick = closeProfileVisibility);
    const visibilityForm = q('#community-visibility-form'); if (visibilityForm) visibilityForm.onsubmit = saveProfileVisibility;
    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      const visibilityModal = q('#community-visibility-modal');
      if (visibilityModal && !visibilityModal.hidden) closeProfileVisibility();
      else if (STATE.centerMode === 'profile') closeProfile();
    });
    q('#community-post-submit').onclick = submitPost;
    wireComposerVisibility();
    loadPublishIdentities();
    const resultButton = q('[data-community-object="result"]'); if (resultButton) resultButton.onclick = openResultPublisher;
    q('#community-load-more').onclick = () => loadFeed(false);
    q('#community-post-files').onchange = async event => { try { await readImages(event.target.files, 'post'); } catch (error) { UI.reportError(error); } finally { event.target.value = ''; } };
    q('#c-files').onchange = async event => { try { await readImages(event.target.files, 'channel'); } catch (error) { UI.reportError(error); } finally { event.target.value = ''; } };
    q('#c-send').onclick = sendChannelMessage;
    const search = q('#community-search'); let searchTimer = null;
    if (search) {
      search.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => {
        const raw = search.value.trim();
        const profileQuery = raw.startsWith('@') ? raw.slice(1).trim() : raw;
        STATE.query = raw.startsWith('#') ? '' : profileQuery;
        loadFeed(true, raw.startsWith('#') ? { hashtag: raw.slice(1) } : {});
      }, 350); });
      document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); search.focus(); } });
    }
    const findPeople = q('#community-find-people'); if (findPeople) findPeople.onclick = () => { search.focus(); search.value = ''; search.dispatchEvent(new Event('input')); };
    const refreshPeople = q('#community-refresh-people'); if (refreshPeople) refreshPeople.onclick = () => loadFeed(true);
    syncViewButtons(); syncSortButtons(); syncWallTabs(); renderPending('post'); renderPending('channel'); loadFeed(true);
    setInterval(() => { if (STATE.view === 'channels' && !document.hidden) loadChannels(); }, 10000);
  });
})();
