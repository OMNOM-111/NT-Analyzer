/* StratForge Community v2 — real social feed plus compatible workspace channels. */
(function () {
  'use strict';
  const UI = window.UI;
  const API = window.API;
  const STATE = {
    view: 'for-you', query: '', cursor: '', loading: false,
    feed: null, profiles: [], pendingPostFiles: [],
    channel: 'general', channelFeed: null, threadRootId: '', pendingChannelFiles: [],
  };

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
  function renderViewer(profile) {
    if (!profile) return;
    const self = q('#community-self-card');
    if (self) self.innerHTML = `${avatar(profile, 'sm')}<button type="button" class="community-self-main" data-profile="${esc(profile.profile_id)}"><strong>${esc(profile.display_name)}</strong><span>@${esc(profile.username)}</span></button><button type="button" class="community-mini-action" data-edit-profile title="Настроить профиль">•••</button>`;
    const composeAvatar = q('#community-composer-avatar');
    if (composeAvatar) composeAvatar.outerHTML = avatar(profile, '').replace('<span ', '<span id="community-composer-avatar" ');
    const summary = q('#community-profile-summary');
    if (summary) summary.innerHTML = `
      <div class="community-profile-cover"><span>SF</span></div>
      <div class="community-profile-summary-body">
        ${avatar(profile, 'xl')}
        <span class="community-role">${esc(profile.role_label)}</span>
        <button type="button" class="community-profile-name" data-profile="${esc(profile.profile_id)}">${esc(profile.display_name)}</button>
        <span class="community-handle">@${esc(profile.username)}</span>
        <p>${esc(profile.bio || 'Добавьте несколько слов о себе и своём стиле торговли.')}</p>
        ${profileStats(profile)}
        <button type="button" class="btn ghost" data-edit-profile>Редактировать профиль</button>
      </div>`;
    qa('[data-edit-profile]').forEach(button => { button.onclick = () => editProfile(profile); });
    qa(`[data-profile="${cssEscape(profile.profile_id || '')}"]`).forEach(button => { button.onclick = () => openProfile(profile.profile_id); });
  }

  function renderPeople(profiles) {
    const rows = Array.isArray(profiles) ? profiles.filter(item => !item.is_self) : [];
    STATE.profiles = rows;
    const recommended = q('#community-recommended');
    if (recommended) recommended.innerHTML = rows.slice(0, 5).map(profile => `
      <article class="community-person-row">
        <button type="button" class="community-person-main" data-profile="${esc(profile.profile_id)}">${avatar(profile, 'sm')}<span><strong>${esc(profile.display_name)}</strong><small>@${esc(profile.username)} · ${esc(profile.role_label)}</small></span></button>
        <button type="button" class="community-follow-button ${profile.is_following ? 'following' : ''}" data-follow="${esc(profile.profile_id)}" data-following="${profile.is_following ? '1' : '0'}">${profile.is_following ? 'Вы читаете' : 'Подписаться'}</button>
      </article>`).join('') || '<p class="muted">Другие участники появятся после первого входа в Community.</p>';
    const following = q('#community-following-list');
    const followed = rows.filter(profile => profile.is_following);
    if (following) following.innerHTML = followed.slice(0, 8).map(profile => `<button type="button" class="community-followed-person" data-profile="${esc(profile.profile_id)}">${avatar(profile, 'xs')}<span><strong>${esc(profile.display_name)}</strong><small>@${esc(profile.username)}</small></span></button>`).join('') || '<p class="muted">Вы пока ни на кого не подписаны.</p>';
    wirePeopleActions(document);
  }

  function objectCard(object) {
    if (!object || typeof object !== 'object') return '';
    const metrics = object.metrics && typeof object.metrics === 'object'
      ? Object.entries(object.metrics).slice(0, 4).map(([key, value]) => `<span><small>${esc(key)}</small><strong>${esc(value)}</strong></span>`).join('') : '';
    return `<section class="community-object-card"><div><span class="community-object-kind">${esc(object.kind || 'Объект')}</span><h4>${esc(object.title || 'Публикация StratForge')}</h4><p>${esc(object.summary || '')}</p></div>${metrics ? `<div class="community-object-metrics">${metrics}</div>` : ''}</section>`;
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
    const author = comment.author || {};
    return `<div class="community-comment">${avatar(author, 'xs')}<div><button type="button" data-profile="${esc(author.profile_id || '')}">${esc(author.display_name || 'Участник')}</button><p>${esc(comment.text || '')}</p><small>${esc(fmtDate(comment.created_at_utc))}</small></div></div>`;
  }
  function postHtml(post) {
    const author = post.author || {};
    const reactions = post.reactions || {};
    const active = String(post.viewer_reaction || '');
    const comments = (post.recent_comments || []).map(commentHtml).join('');
    return `<article class="community-post-card" data-post-id="${esc(post.post_id)}" data-viewer-reaction="${esc(active)}">
      <header class="community-post-head">
        <button type="button" class="community-post-author" data-profile="${esc(author.profile_id || '')}">${avatar(author, '')}<span><strong>${esc(author.display_name || 'Участник')}</strong><small>@${esc(author.username || '')} · ${esc(author.role_label || '')}</small></span></button>
        <div class="community-post-meta"><time>${esc(fmtDate(post.created_at_utc))}</time><span title="Видимость">${post.visibility === 'followers' ? '◎' : '◉'}</span><button type="button" data-report-post="${esc(post.post_id)}" title="Пожаловаться">•••</button></div>
      </header>
      ${post.text ? `<div class="community-post-text">${esc(post.text)}</div>` : ''}
      ${(post.hashtags || []).length ? `<div class="community-tags">${post.hashtags.map(tag => `<button type="button" data-hashtag="${esc(tag)}">#${esc(tag)}</button>`).join('')}</div>` : ''}
      ${postMedia(post.attachments)}${objectCard(post.object)}
      <div class="community-post-actions">
        <button type="button" class="${active === 'support' ? 'active' : ''}" data-reaction="support"><span>♡</span>${shortNumber(reactions.support)}</button>
        <button type="button" class="${active === 'insightful' ? 'active' : ''}" data-reaction="insightful"><span>◇</span>${shortNumber(reactions.insightful)}</button>
        <button type="button" class="${active === 'fire' ? 'active' : ''}" data-reaction="fire"><span>↗</span>${shortNumber(reactions.fire)}</button>
        <button type="button" data-focus-comment><span>◌</span>${shortNumber(post.comment_count)}</button>
        <span class="community-action-spacer"></span>
        <button type="button" class="${post.bookmarked ? 'active' : ''}" data-bookmark="${post.bookmarked ? '1' : '0'}" title="Сохранить"><span>◇</span></button>
      </div>
      <div class="community-comments">${comments}<form class="community-comment-form"><input maxlength="1200" placeholder="Ответить по существу…"><button type="submit" aria-label="Отправить комментарий">↑</button></form></div>
    </article>`;
  }

  function wirePeopleActions(root) {
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
        try { const out = await API.http.communityV2Bookmark(postId, bookmark.dataset.bookmark !== '1'); replacePost(out.post); }
        catch (error) { UI.reportError(error); }
      };
      const focus = q('[data-focus-comment]', card);
      if (focus) focus.onclick = () => { const input = q('.community-comment-form input', card); if (input) input.focus(); };
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
      qa('[data-hashtag]', card).forEach(button => button.onclick = () => {
        const search = q('#community-search'); if (search) search.value = '#' + button.dataset.hashtag;
        STATE.query = ''; loadFeed(true, { hashtag: button.dataset.hashtag });
      });
    });
  }
  function replacePost(post) {
    if (!post) return;
    const selector = `.community-post-card[data-post-id="${cssEscape(post.post_id || '')}"]`;
    const existing = q(selector);
    if (!existing) { loadFeed(true); return; }
    const shell = document.createElement('div'); shell.innerHTML = postHtml(post);
    const next = shell.firstElementChild; existing.replaceWith(next); wirePostActions(next);
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
      renderViewer(doc.viewer);
      renderPeople((people && people.profiles) || doc.recommended_profiles || []);
      const posts = doc.posts || [];
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
      }
      const more = q('#community-load-more'); if (more) more.hidden = !STATE.cursor;
      setStatus(`${Number(doc.total_visible || posts.length)} публикаций`, 'ready');
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
  async function submitPost() {
    const input = q('#community-post-text'); const submit = q('#community-post-submit');
    const text = input ? input.value.trim() : '';
    if (!text && !STATE.pendingPostFiles.length) { UI.toast('Добавьте текст или изображение'); return; }
    if (submit) submit.disabled = true;
    try {
      await API.http.communityV2Post({ text, attachments: STATE.pendingPostFiles, visibility: q('#community-post-visibility').value });
      if (input) input.value = '';
      STATE.pendingPostFiles = []; renderPending('post');
      STATE.view = 'for-you'; syncViewButtons(); await loadFeed(true); UI.toast('Публикация добавлена');
    } catch (error) { UI.reportError(error); }
    finally { if (submit) submit.disabled = false; }
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
    if (channelsView) channelsView.hidden = !channels;
    if (feed) feed.hidden = channels;
    if (composer) composer.hidden = channels || STATE.view === 'saved';
    if (more && channels) more.hidden = true;
  }
  async function setView(view) {
    if (view === 'profile') {
      const viewer = STATE.feed && STATE.feed.viewer;
      if (viewer) await openProfile(viewer.profile_id);
      return;
    }
    STATE.view = ['for-you', 'following', 'saved', 'channels'].includes(view) ? view : 'for-you';
    STATE.cursor = ''; syncViewButtons();
    if (STATE.view === 'channels') await loadChannels(); else await loadFeed(true);
  }

  async function openProfile(profileId) {
    if (!profileId) return;
    const modal = q('#community-profile-modal'); const host = q('#community-profile-detail');
    if (!modal || !host) return;
    modal.hidden = false; document.body.classList.add('community-modal-open');
    host.innerHTML = '<div class="community-skeleton profile"></div>';
    try {
      const doc = await API.http.communityV2Profile(profileId, { posts_limit: 30 });
      const profile = doc.profile || {};
      host.innerHTML = `<div class="community-profile-hero"><div class="community-profile-cover"><span>SF</span></div>${avatar(profile, 'xxl')}<div class="community-profile-identity"><span class="community-role">${esc(profile.role_label)}</span><h2 id="community-profile-name">${esc(profile.display_name)}</h2><span>@${esc(profile.username)}</span><p>${esc(profile.bio || 'Описание пока не заполнено.')}</p>${profileStats(profile)}<div class="community-profile-actions">${profile.is_self
        ? '<button type="button" class="btn primary" data-modal-edit>Редактировать профиль</button>'
        : `<button type="button" class="btn ${profile.is_following ? 'ghost' : 'primary'}" data-follow="${esc(profile.profile_id)}" data-following="${profile.is_following ? '1' : '0'}">${profile.is_following ? 'Вы читаете' : 'Подписаться'}</button>${profile.can_message ? `<button type="button" class="btn ghost" data-message-profile="${esc(profile.profile_id)}">Сообщение</button>` : ''}<button type="button" class="btn ghost" data-block-profile="${esc(profile.profile_id)}">Заблокировать</button>`}</div></div></div><div class="community-profile-wall"><h3>Публикации</h3>${(doc.posts || []).map(postHtml).join('') || renderEmpty('На стене пока тихо', 'Публикации появятся здесь.')}</div>`;
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
    const modal = q('#community-profile-modal'); if (modal) modal.hidden = true;
    document.body.classList.remove('community-modal-open');
  }
  async function startMessage(profileId) {
    try {
      const out = await API.http.sfChatStartConversation(profileId);
      closeProfile();
      const conversationId = out && out.conversation && out.conversation.conversation_id;
      if (window.UI && typeof UI.openSFChat === 'function') await UI.openSFChat({ conversationId, conversationType: 'human' });
      else if (window.UI && typeof UI.openOrchestrator === 'function') await UI.openOrchestrator({ conversationId, conversationType: 'human' });
    } catch (error) { UI.reportError(error); }
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
    qa('[data-community-profile-close]').forEach(button => button.onclick = closeProfile);
    q('#community-post-submit').onclick = submitPost;
    q('#community-load-more').onclick = () => loadFeed(false);
    q('#community-post-files').onchange = async event => { try { await readImages(event.target.files, 'post'); } catch (error) { UI.reportError(error); } finally { event.target.value = ''; } };
    q('#c-files').onchange = async event => { try { await readImages(event.target.files, 'channel'); } catch (error) { UI.reportError(error); } finally { event.target.value = ''; } };
    q('#c-send').onclick = sendChannelMessage;
    const search = q('#community-search'); let searchTimer = null;
    if (search) {
      search.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { const raw = search.value.trim(); STATE.query = raw.startsWith('#') ? '' : raw; loadFeed(true, raw.startsWith('#') ? { hashtag: raw.slice(1) } : {}); }, 350); });
      document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); search.focus(); } });
    }
    const findPeople = q('#community-find-people'); if (findPeople) findPeople.onclick = () => { search.focus(); search.value = ''; search.dispatchEvent(new Event('input')); };
    const refreshPeople = q('#community-refresh-people'); if (refreshPeople) refreshPeople.onclick = () => loadFeed(true);
    syncViewButtons(); renderPending('post'); renderPending('channel'); loadFeed(true);
    setInterval(() => { if (STATE.view === 'channels' && !document.hidden) loadChannels(); }, 10000);
  });
})();
