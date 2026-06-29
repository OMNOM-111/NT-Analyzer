/* =====================================================================
   UI shell + helpers shared by every prototype page.
   Builds the left rail + topbar, exposes window.UI helpers.
   ===================================================================== */
(function () {
  // ---- inline icon set (stroke, currentColor) --------------------------------
  const I = {
    overview: '<path d="M3 13h8V3H3v10Zm10 8h8V11h-8v10ZM3 21h8v-6H3v6ZM13 3v6h8V3h-8Z"/>',
    backtest: '<path d="M3 3v18h18"/><path d="M7 14l3-4 3 3 4-6"/>',
    trading: '<path d="M3 17l5-5 4 4 8-9"/><path d="M21 7h-5m5 0v5"/>',
    performance: '<rect x="3" y="12" width="4" height="8" rx="1"/><rect x="10" y="7" width="4" height="13" rx="1"/><rect x="17" y="3" width="4" height="17" rx="1"/>',
    strategies: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    ai: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><rect x="7" y="7" width="10" height="10" rx="3"/><path d="M10 10h4v4h-4z"/>',
    docs: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    news: '<path d="M4 5h12v14H5a2 2 0 0 1-2-2V6a1 1 0 0 1 1-1Z"/><path d="M16 8h4v9a2 2 0 0 1-2 2h-2M7 9h6M7 13h6M7 16h4"/>',
    trophy: '<path d="M8 4h8v4a4 4 0 0 1-8 0V4Z"/><path d="M8 6H4v2a4 4 0 0 0 4 4M16 6h4v2a4 4 0 0 1-4 4M12 12v5M8 21h8M9 17h6"/>',
    telegram: '<path d="m21 3-4 18-6-5-4 3 1-6 9-7-11 6-4-2 19-7Z"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 4v4h-4"/>',
    play: '<path d="M6 4l14 8-14 8V4Z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    download: '<path d="M12 3v12M7 11l5 5 5-5M5 21h14"/>',
    trash: '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13h10l1-13"/>',
    star: '<path d="M12 3l2.6 5.6 6.1.6-4.6 4 1.4 6-5.5-3.2L6 19.8l1.4-6-4.6-4 6.1-.6L12 3Z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    bolt: '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3"/>',
    wallet: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18M17 14h2"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    layers: '<path d="M12 3 2 8l10 5 10-5-10-5ZM2 16l10 5 10-5M2 12l10 5 10-5"/>',
    edit: '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    close: '<path d="M18 6 6 18M6 6l12 12"/>',
    arrowUp: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    arrowDown: '<path d="M12 5v14M5 12l7 7 7-7"/>',
    coins: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    spark: '<path d="M12 2v6M12 16v6M2 12h6M16 12h6M5 5l4 4M15 15l4 4M19 5l-4 4M9 15l-4 4"/>',
    dots: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
    back: '<path d="M9 6l-6 6 6 6M3 12h13a5 5 0 0 1 5 5v1"/>',
    eraser: '<path d="M3 16l7 7h7M18 13L9 22M16 3l5 5L9 20H4v-5L16 3Z"/>',
    plug: '<path d="M9 2v6M15 2v6M7 8h10v3a5 5 0 0 1-10 0V8ZM12 16v6"/>',
    chart: '<path d="M3 3v18h18"/><path d="M7 14l3-4 3 3 4-6"/>',
    book: '<path d="M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2V5Z"/><path d="M8 7h7M8 11h7"/>',
  };
  function icon(name, cls) { return `<svg class="${cls || 'ic'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${I[name] || ''}</svg>`; }
  const APP_NAME = 'StratForge AI';
  const APP_KICKER = 'StratForge AI · NTA Edition';
  const BRAND_MARK = 'brand/stratforge-mark.png';

  const NAV = [
    { id: 'overview', label: 'Обзор', href: 'index.html', icon: 'overview' },
    { id: 'backtest', label: 'Бэктест', href: 'backtesting.html', icon: 'backtest' },
    { id: 'trading', label: 'Торговля', href: 'trading.html', icon: 'trading' },
    { id: 'performance', label: 'Доход', href: 'performance.html', icon: 'performance' },
    { id: 'strategies', label: 'Стратегии', href: 'strategies.html', icon: 'strategies' },
    { id: 'ai', label: 'AI Lab', href: 'ai-lab.html', icon: 'ai' },
    { id: 'news', label: 'Новости', href: 'news.html', icon: 'news' },
    { id: 'topstep', label: 'TopStep', href: 'topstep.html', icon: 'trophy' },
    { id: 'docs', label: 'Документы', href: 'documents.html', icon: 'docs' },
  ];
  let runtimeAccounts = [];
  let selectedAccount = null;

  // ---- formatting helpers -----------------------------------------------------
  function money(v, opts) {
    opts = opts || {};
    const sign = v > 0 && opts.sign ? '+' : (v < 0 ? '−' : '');
    const a = Math.abs(v);
    return sign + '$' + a.toLocaleString('en-US', { maximumFractionDigits: opts.dec ?? 0, minimumFractionDigits: opts.dec ?? 0 });
  }
  function pct(v) { return (v).toFixed(1) + '%'; }
  function pnlClass(v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : 'muted'; }
  function badge(status) {
    const labels = { done: 'готово', pending: 'в работе', live: 'онлайн', demo: 'демо', trial: 'испытание', running: 'идёт', archived: 'архив', failed: 'ошибка' };
    const lbl = labels[status] || status;
    return `<span class="badge ${status}"><span class="dot"></span>${esc(lbl)}</span>`;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
  function el(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
  function qs(s, r) { return (r || document).querySelector(s); }
  function qsa(s, r) { return Array.from((r || document).querySelectorAll(s)); }

  function newsEta(ms) {
    const min = Math.max(0, Math.round(ms / 60000));
    if (min < 60) return `через ${min} мин`;
    const hours = Math.floor(min / 60);
    if (hours < 24) return `через ${hours} ч ${min % 60} мин`;
    return `через ${Math.floor(hours / 24)} дн ${hours % 24} ч`;
  }

  function newsAge(minutes) {
    if (minutes == null) return '';
    if (minutes < 1) return 'только что';
    if (minutes < 60) return `${Math.round(minutes)} мин назад`;
    return `${Math.floor(minutes / 60)} ч назад`;
  }

  function renderGlobalNewsStrip(strip, calendar, live) {
    const label = qs('.global-news-label', strip);
    const track = qs('.global-news-track', strip);
    const now = Date.now();
    const events = (calendar && calendar.items) || [];
    const liveItems = (live && live.items) || [];
    const severity = item => ['high', 'medium', 'low'].includes(String(item.severity || item.impact || '').toLowerCase())
      ? String(item.severity || item.impact).toLowerCase() : 'low';
    const eventMs = item => new Date(item.event_time_utc || 0).getTime();
    const activeCritical = events.filter(item => {
      const at = eventMs(item);
      return item.is_confirmed && severity(item) === 'high' &&
        now >= at - Number(item.block_before_min || 0) * 60000 &&
        now <= at + Number(item.block_after_min || 0) * 60000;
    });
    const imminentCritical = events.filter(item => {
      const remaining = eventMs(item) - now;
      return item.is_confirmed && severity(item) === 'high' && remaining > 0 && remaining <= 60 * 60000;
    });
    const upcoming = events.filter(item => {
      const remaining = eventMs(item) - now;
      return severity(item) === 'high' && remaining > 0 && remaining <= 7 * 24 * 3600000;
    }).sort((a, b) => eventMs(a) - eventMs(b));

    const critical = activeCritical.length > 0 || imminentCritical.length > 0;
    const warning = !critical && upcoming.some(item => eventMs(item) - now <= 24 * 3600000);
    strip.classList.toggle('critical', critical);
    strip.classList.toggle('warning', warning);
    label.textContent = critical ? '🔴 СТОП' : warning ? '⚠ ВАЖНО' : 'РЫНОК';

    const rows = [];
    activeCritical.forEach(item => rows.push({
      severity: 'high',
      text: `⛔ ОТКЛЮЧИТЕ СТРАТЕГИИ: ${item.title} — защитное окно активно`,
      url: item.url || item.source_url || '',
    }));
    imminentCritical.forEach(item => rows.push({
      severity: 'high',
      text: `🔴 ОЧЕНЬ СРОЧНО — ${newsEta(eventMs(item) - now)}: ${item.title}. Отключите затронутые стратегии`,
      url: item.url || item.source_url || '',
    }));
    liveItems.filter(item => severity(item) === 'high').slice(0, 8).forEach(item => rows.push({
      severity: 'high',
      text: `🔴 ВАЖНАЯ НОВОСТЬ · ${item.source || 'источник'}: ${item.title}${item.age_min == null ? '' : ' · ' + newsAge(item.age_min)}`,
      url: item.url || item.source_url || '',
    }));
    upcoming.slice(0, 8).forEach(item => rows.push({
      severity: item.is_confirmed ? 'high' : 'medium',
      text: `${item.is_confirmed ? '📅' : '⚠ оценка'} ${newsEta(eventMs(item) - now)}: ${item.title}`,
      url: item.url || item.source_url || '',
    }));
    liveItems.filter(item => severity(item) === 'medium').slice(0, 8).forEach(item => rows.push({
      severity: 'medium',
      text: `${item.source || 'источник'}: ${item.title}${item.age_min == null ? '' : ' · ' + newsAge(item.age_min)}`,
      url: item.url || item.source_url || '',
    }));

    const seen = new Set();
    const unique = rows.filter(row => {
      const key = row.text.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key); return true;
    }).slice(0, 18);
    if (!unique.length) {
      track.classList.add('paused');
      track.innerHTML = '<span class="global-news-static">Нет свежих важных сообщений; календарь доступен на вкладке «Новости».</span>';
      return;
    }
    track.classList.remove('paused');
    const html = unique.map(row => {
      const content = `<span class="dot"></span><b>${esc(row.text)}</b>`;
      return row.url
        ? `<a class="global-news-item ${row.severity}" href="${esc(row.url)}" target="_blank" rel="noopener noreferrer">${content}</a>`
        : `<span class="global-news-item ${row.severity}">${content}</span>`;
    }).join('');
    const copies = unique.length < 3 ? 8 : unique.length < 6 ? 4 : 2;
    track.innerHTML = html.repeat(copies);
  }

  function wireGlobalNewsStrip(strip) {
    if (!strip || !window.API || !API.http) return;
    const refresh = async () => {
      try {
        const [calendar, live] = await Promise.all([
          API.http.news({ limit: 120 }, { signal: signal() }),
          API.http.newsLive({ max_age_min: 180, limit: 40 }, { signal: signal() }).catch(() => null),
        ]);
        renderGlobalNewsStrip(strip, calendar, live);
      } catch (error) {
        if (error && error.name === 'AbortError') return;
        const track = qs('.global-news-track', strip);
        if (track) track.innerHTML = '<span class="global-news-static">Новостная лента временно недоступна.</span>';
      }
    };
    refresh();
    const timer = setInterval(refresh, 180000);
    onLeave(() => clearInterval(timer));
  }

  // ---- shell ------------------------------------------------------------------
  function buildShell() {
    const page = document.body.dataset.page;
    const title = document.body.dataset.title || APP_NAME;
    const kicker = document.body.dataset.kicker || APP_KICKER;

    const rail = el(`<nav class="rail">
      <a class="rail-logo" href="index.html" title="${APP_NAME}"><img class="rail-logo-mark" src="${BRAND_MARK}" alt="${APP_NAME}"></a>
      <div class="rail-nav">
        ${NAV.map(n => `<a class="rail-item ${n.id === page ? 'active' : ''}" href="${n.href}" title="${n.label}">${icon(n.icon)}<span class="lb">${n.label}</span></a>`).join('')}
      </div>
      <div class="rail-foot"><span class="rail-dot" title="Сервер онлайн"></span></div>
    </nav>`);

    const topbar = el(`<header class="topbar">
      <div class="tb-title"><span class="tb-kicker">${kicker}</span><span class="tb-h1">${title}</span></div>
      <div class="tb-search-wrap">
        <label class="tb-search">${icon('search')}<input type="search" id="global-search" autocomplete="off" placeholder="Поиск стратегий, отчётов, инструментов…"></label>
        <div class="search-results" id="search-results" hidden></div>
      </div>
      <div class="tb-right">
        <span class="tb-page-actions" id="page-actions"></span>
        <span class="chip off" id="chip-nt" title="NinjaTrader"><span class="dot"></span>NinjaTrader</span>
        <span class="chip off" id="chip-bridge" title="Bridge (мост данных)"><span class="dot"></span>Bridge</span>
        <span class="chip off" id="chip-lm" title="LM Studio"><span class="dot"></span>LM&#160;Studio</span>
        <span class="chip off chip-market" id="chip-market" title="Рынок"><span class="dot"></span>Рынок</span>
        <button class="chip off chip-account" id="chip-account" type="button" title="Текущий торговый счёт"><span class="dot"></span>Счёт —</button>
        <span class="tb-datetime"><span id="pt-date">—</span><span class="mono" id="clock">—</span></span>
        <span class="tb-sep"></span>
        <button class="btn icon ghost" id="tb-more" title="Системные действия">${icon('dots')}</button>
      </div>
    </header>`);

    const app = el('<div class="app"></div>');
    const main = el('<div class="main"></div>');
    main.appendChild(topbar);
    const newsStrip = page === 'news' ? null : el('<div class="global-news-strip" data-global-news-strip><span class="global-news-label">РЫНОК</span><div class="global-news-window"><div class="global-news-track"><span class="global-news-static">Загрузка новостей…</span></div></div></div>');
    if (newsStrip) main.appendChild(newsStrip);
    // move existing body content into <main class=content>
    const content = el('<div class="content"></div>');
    while (document.body.firstChild) content.appendChild(document.body.firstChild);
    main.appendChild(content);
    app.appendChild(rail);
    app.appendChild(main);
    document.body.appendChild(app);

    startClock();
    wireSystemStatus();
    wireTopbar();
    wireSearch();
    wireDelegatedActions();
    wireA11y();
    wireGlobalNewsStrip(newsStrip);
    // run page initializers (await async ones; route rejections to the global handler)
    requestAnimationFrame(() => { runReady(); });
  }

  // ---- accessibility: make non-semantic clickables keyboard-operable ---------
  const A11Y_SEL = 'tr.clickable, .clickable, .kan-card, .mcell[data-id], .mcell[data-cell], .cal-day[data-i], .cal-day[data-date], .legend-item, .inst-row[data-sym], .igroup-h, .ai-cell[data-id], .row[data-id], .row[data-profile], .row[data-root], #top-strats .row, #recent .row, #doc-list .row';
  function enhanceA11y(scope) {
    qsa(A11Y_SEL, scope || document).forEach(eln => {
      const tag = eln.tagName;
      if (tag === 'A' || tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT') return;
      if (!eln.hasAttribute('tabindex')) eln.setAttribute('tabindex', '0');
      if (!eln.hasAttribute('role')) eln.setAttribute('role', 'button');
    });
  }
  function wireA11y() {
    document.addEventListener('keydown', (e) => {
      const t = e.target;
      if ((e.key === 'Enter' || e.key === ' ') && t && t.getAttribute && t.getAttribute('role') === 'button' && t.hasAttribute('tabindex')) {
        e.preventDefault(); t.click();
      }
    });
    // enhance dynamically-rendered content (tables/cards re-render often)
    let raf = null;
    const obs = new MutationObserver(() => { if (raf) cancelAnimationFrame(raf); raf = requestAnimationFrame(() => enhanceA11y(document)); });
    const content = qs('.content'); if (content) obs.observe(content, { childList: true, subtree: true });
  }

  async function runReady() {
    READY._done = true;
    const fns = READY.splice(0);
    for (const fn of fns) {
      try { await fn(); }
      catch (e) { if (e && e.name === 'AbortError') continue; reportError(e); }
    }
    enhanceA11y(document);
  }

  // Centralised UI error surface (used by pages' loading/error states too).
  function reportError(err) {
    console.error('[UI]', err);
    const msg = (err && err.message) ? err.message : String(err);
    toast('Ошибка: ' + msg.slice(0, 120));
  }

  // CSP-safe global click handling for declarative actions in injected HTML.
  function wireDelegatedActions() {
    document.addEventListener('click', (e) => {
      const t = e.target.closest('[data-toast]');
      if (t) { toast(t.getAttribute('data-toast')); return; }
      const c = e.target.closest('[data-close-drawer]');
      if (c) { closeDrawer(); }
      const size = e.target.closest('[data-drawer-size]');
      if (size) {
        const drawerNode = qs('.drawer');
        if (drawerNode) setDrawerSize(drawerNode, size.dataset.drawerSize);
      }
    });
  }

  // ---- live system status chips ---------------------------------------------
  function setChip(node, state, label, title) {
    if (!node) return;
    node.classList.remove('ok', 'warn', 'bad', 'off');
    node.classList.add(state);
    node.innerHTML = `<span class="dot"></span>${esc(label)}`;
    if (title) node.title = title;
  }
  function setSelectedAccount(name, notify) {
    const next = AuroraDomain.selectAccount(runtimeAccounts, name);
    selectedAccount = next;
    try {
      if (next) localStorage.setItem(AuroraDomain.ACCOUNT_KEY, next.account_name);
      else localStorage.removeItem(AuroraDomain.ACCOUNT_KEY);
    } catch (e) { /* storage may be disabled */ }
    const chip = qs('#chip-account');
    if (next) {
      const mode = next.is_live ? 'LIVE' : (next.account_mode || 'paper');
      setChip(chip, next.is_live ? 'bad' : 'ok', `${next.account_name} · ${mode}`, `${next.display_name || next.account_name} · ${next.connection_status || 'статус неизвестен'} · NetLiq ${money(next.net_liquidation || 0)}`);
    } else setChip(chip, 'off', 'Счёт недоступен', 'Runtime account list пуст');
    if (notify !== false) window.dispatchEvent(new CustomEvent('nt-account-change', { detail: next }));
    return next;
  }

  function getSelectedAccount() { return selectedAccount; }

  function accountMenu(anchor) {
    if (!runtimeAccounts.length) { toast('Список счетов недоступен'); return; }
    menu(anchor, runtimeAccounts.map(account => ({
      icon: 'wallet',
      label: `${account.account_name} · ${account.is_live ? 'LIVE' : (account.account_mode || 'paper')}`,
      danger: !!account.is_live,
      onClick: () => setSelectedAccount(account.account_name, true),
    })));
  }

  function wireSystemStatus() {
    const ntC = qs('#chip-nt'), brC = qs('#chip-bridge'), lmC = qs('#chip-lm'), mkC = qs('#chip-market'), accC = qs('#chip-account');
    const tickMarket = () => { const m = AuroraDomain.marketStatus(new Date()); setChip(mkC, m.state, m.label, m.title); };
    tickMarket(); setInterval(tickMarket, 30000);
    if (accC) accC.onclick = (e) => { e.stopPropagation(); accountMenu(accC); };
    try { const stored = localStorage.getItem(AuroraDomain.ACCOUNT_KEY); if (stored) setChip(accC, 'off', `${stored} · проверка…`, 'Проверяю account в актуальном runtime list'); } catch (e) { /* ignore */ }
    if (!window.API || API.config.offline) {
      setChip(ntC, 'off', 'NinjaTrader', 'демо-превью (без backend)');
      setChip(brC, 'off', 'Bridge', 'демо-превью (без backend)');
      setChip(lmC, 'off', 'LM Studio', 'демо-превью (без backend)');
      setChip(accC, 'off', 'Счёт недоступен', 'backend не подключён');
      return;
    }
    async function refresh() {
      const healthTask = API.http.health().then(h => {
        setChip(ntC, h.ninjatrader_running ? 'ok' : 'bad', 'NinjaTrader', h.ninjatrader_running ? 'NinjaTrader запущен' : 'NinjaTrader не запущен');
      }).catch(() => setChip(ntC, 'off', 'NinjaTrader', 'статус недоступен'));
      const bridgeTask = API.http.runtimeHeartbeat().then(hb => {
        const ok = hb.present && hb.fresh;
        setChip(brC, ok ? 'ok' : (hb.present ? 'warn' : 'bad'), 'Bridge', ok ? `мост активен · ${Math.round(hb.age_sec || 0)}с · v${hb.exporter_version || '?'}` : (hb.present ? `данные устарели (${Math.round(hb.age_sec || 0)}с)` : 'мост не отвечает'));
      }).catch(() => setChip(brC, 'off', 'Bridge', 'статус недоступен'));
      const lmTask = API.http.aiLmStudioHealth().then(lm => {
        const st = lm.ready ? 'ok' : (lm.available ? 'warn' : 'off');
        setChip(lmC, st, 'LM Studio', lm.message_ru || (lm.ready ? 'модели готовы' : 'недоступна'));
      }).catch(() => setChip(lmC, 'off', 'LM Studio', 'статус недоступен'));
      const accountsTask = API.http.runtimeAccounts().then(accounts => {
        runtimeAccounts = (accounts.accounts || accounts.online_accounts || []).filter(account => !account.is_system);
        let preferred = selectedAccount && selectedAccount.account_name;
        if (!preferred) { try { preferred = localStorage.getItem(AuroraDomain.ACCOUNT_KEY); } catch (e) { /* ignore */ } }
        setSelectedAccount(preferred, false);
      }).catch(() => { runtimeAccounts = []; selectedAccount = null; setChip(accC, 'off', 'Счёт недоступен', 'runtime accounts endpoint недоступен'); });
      await Promise.allSettled([healthTask, bridgeTask, lmTask, accountsTask]);
    }
    poll(refresh, 15000);
  }

  // Run a backend action with pending → success/error toasts (success only after OK).
  async function action(pendingMsg, fn, okMsg) {
    if (!window.API || API.config.offline) { toast((pendingMsg || 'Действие') + ' — недоступно в офлайн-превью'); return; }
    toast((pendingMsg || 'Выполняю') + '…');
    try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
    catch (e) { reportError(e); throw e; }
  }

  async function showDiagnostics() {
    if (!window.API || API.config.offline) { toast('Диагностика — недоступно в офлайн-превью'); return; }
    const d = drawer('<h3>Диагностика системы</h3>', '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>');
    const body = qs('.drawer-b', d);
    try {
      const diag = await API.http.diagnostics();
      const cat = diag.catalog || {};
      body.innerHTML = `
        <div class="list">
          <div class="row"><div class="row-main"><div class="row-title">NinjaTrader</div></div><div class="row-val ${diag.ninjatrader_running ? 'pos' : 'neg'}">${diag.ninjatrader_running ? 'запущен' : 'не запущен'}</div></div>
          <div class="row"><div class="row-main"><div class="row-title">Стратегий в каталоге</div></div><div class="row-val">${cat.strategies_count != null ? cat.strategies_count : '—'}</div></div>
          <div class="row"><div class="row-main"><div class="row-title">Инструментов</div></div><div class="row-val">${cat.instruments_count != null ? cat.instruments_count : '—'}</div></div>
        </div>
        <h4 style="margin:16px 0 8px">Журнал моста (хвост)</h4>
        <pre class="logbox">${esc((diag.bridge_log_tail || []).slice(-25).join('\n'))}</pre>`;
    } catch (e) { renderError(body, e, showDiagnostics); }
  }

  async function showIntegrations() {
    if (!window.API || API.config.offline) { toast('Интеграции недоступны в офлайн-превью'); return; }
    const d = drawer('<h3>Интеграции и уведомления</h3>', '<div class="state-loading"><span class="spinner"></span>Проверка конфигурации…</div>');
    const body = qs('.drawer-b', d);
    try {
      const status = await API.http.integrationsStatus();
      const rows = [
        ['Telegram', status.telegram, 'Уведомления; команды заблокированы до security-аудита'],
        ['TopStep', status.topstep, 'Только одобренные стратегии через NinjaTrader; live-действия пока заблокированы'],
        ['Новости', status.news, 'Отображаются только реальные сохранённые источники'],
        ['Платные AI-агенты', status.external_agents, 'Бюджет и выполнение требуют отдельного разрешения'],
      ];
      body.innerHTML = `<div class="list">${rows.map(([name, item, note]) => `<div class="row"><div class="row-main"><div class="row-title">${esc(name)}</div><div class="row-sub">${esc(note)}</div></div><span class="badge ${item && item.configured ? 'live' : 'archived'}"><span class="dot"></span>${item && item.configured ? 'настроено' : 'не настроено'}</span></div>`).join('')}</div>
        <div class="finance-note"><strong>Безопасность:</strong> токены и API-ключи никогда не возвращаются в браузер. Подключение выполняется через переменные окружения backend.</div>
        <div class="flex wrap gap-sm"><a class="btn" href="topstep.html">TopStep</a><a class="btn" href="news.html">Новости</a><a class="btn" href="ai-lab.html">AI-агенты</a></div>`;
    } catch (error) { renderError(body, error, showIntegrations); }
  }

  function wireTopbar() {
    const offline = !window.API || API.config.offline;
    const legacyUrl = (window.API && API.config && API.config.legacyUrl) || '/ui/legacy/';
    const more = qs('#tb-more');
    if (more) more.onclick = (e) => {
      e.stopPropagation();
      menu(more, [
        { icon: 'play', label: 'Запустить всё окружение', onClick: () => showEnvironment(true) },
        { icon: 'cpu', label: 'Состояние окружения', onClick: () => showEnvironment(false) },
        { icon: 'cpu', label: 'Диагностика системы', onClick: () => showDiagnostics() },
        { icon: 'telegram', label: 'Интеграции и Telegram', onClick: () => showIntegrations() },
        { icon: 'refresh', label: 'Перезапустить backend', onClick: () => {
          if (offline) { toast('Перезапуск backend недоступен в офлайн-превью'); return; }
          if (!confirm('Перезапустить python-backend? Активные HTTP-запросы прервутся.')) return;
          action('Перезапуск python-backend', () => API.http.restartServer(), 'Backend перезапускается').then(() => setTimeout(() => location.reload(), 1800)).catch(() => {});
        } },
        { icon: 'eraser', label: 'Освободить память ИИ', onClick: () => action('Выгрузка моделей LM Studio', () => API.http.aiBootstrapUnload({ stop_server: true }), 'Память LM Studio освобождена').catch(() => { }) },
        { icon: 'refresh', label: 'Обновить каталог стратегий', onClick: () => action('Обновление каталога стратегий', () => API.http.refreshCatalog(), 'Каталог обновлён').catch(() => { }) },
        { icon: 'coins', label: 'Пересчитать маржу', onClick: () => action('Обновление маржинальных требований', () => API.http.refreshMargins(), 'Маржа обновлена').catch(() => { }) },
        { divider: true },
        { icon: 'back', label: 'Перейти в старый интерфейс', onClick: () => { window.location.href = legacyUrl; } },
      ]);
    };
  }

  function environmentHtml(result) {
    result = result || {};
    const steps = result.steps || [];
    const readiness = result.readiness || (result.status && result.status.components && result.status.components.lm_studio_server) || (result.components && result.components.lm_studio_server) || {};
    return `<div class="list">${steps.length ? steps.map(step => `<div class="row"><div class="row-main"><div class="row-title">${esc(step.component || 'компонент')}</div><div class="row-sub">${esc(step.status || step.stderr || step.stdout || '')}</div></div><span class="badge ${step.ok ? 'live' : 'failed'}">${step.ok ? 'готово' : 'ошибка'}</span></div>`).join('') : '<div class="empty-state">Действия запуска ещё не выполнялись.</div>'}</div>
      <div class="finance-note"><strong>LM Studio:</strong> ${esc(readiness.message_ru || readiness.status || 'статус проверяется')}<br><strong>Run allowed:</strong> ${readiness.run_allowed ? 'да' : 'нет'} · <strong>Models:</strong> ${esc((readiness.models || []).join(', ') || 'нет данных')}</div>
      <div class="flex gap-sm"><button class="btn" id="env-refresh">Обновить статус</button><button class="btn ghost" data-close-drawer>Закрыть</button></div>`;
  }

  async function showEnvironment(start) {
    if (!window.API || API.config.offline) { toast('Управление окружением недоступно в офлайн-превью'); return; }
    const d = drawer('<h3>Окружение StratForge AI</h3>', '<div class="state-loading"><span class="spinner"></span>Проверка компонентов…</div>');
    const body = qs('.drawer-b', d);
    async function refresh() {
      try {
        const result = start ? await API.http.aiBootstrapStart({ load_models: true, wait_readiness: false }) : await API.http.aiBootstrapStatus();
        start = false;
        body.innerHTML = environmentHtml(result);
        const button = qs('#env-refresh', body);
        if (button) button.onclick = () => { body.innerHTML = '<div class="state-loading"><span class="spinner"></span>Обновление…</div>'; refresh(); };
      } catch (e) { renderError(body, e, refresh); }
    }
    await refresh();
  }

  // ---- global search ----------------------------------------------------------
  // offline preview index (file://) — uses the MOCK facade
  function buildSearchIndexMock() {
    const A = window.API; const idx = [];
    NAV.forEach(n => idx.push({ label: n.label, sub: 'раздел', href: n.href, icon: n.icon }));
    (A.strategies || []).forEach(s => idx.push({ label: s.name, sub: `стратегия · ${s.cellId} · ${s.root}`, href: 'strategies.html', icon: 'strategies' }));
    (A.reports || []).forEach(rp => idx.push({ label: rp.label, sub: `отчёт №${rp.no} · ${rp.strategy}`, href: 'backtesting.html', icon: 'backtest' }));
    (A.ROOTS || []).forEach(r0 => idx.push({ label: `${r0.sym} — ${r0.name}`, sub: `инструмент · ${r0.group}`, href: 'backtesting.html', icon: 'coins' }));
    (A.documents || []).forEach(d => idx.push({ label: d.title, sub: `документ · ${d.cat}`, href: 'documents.html', icon: 'docs' }));
    return idx;
  }
  // real backend index (served) — strategies / jobs / documents / instruments + deep links
  async function buildSearchIndexReal() {
    const idx = [];
    NAV.forEach(n => idx.push({ label: n.label, sub: 'раздел', href: n.href, icon: n.icon }));
    const safe = async (p) => { try { return await p; } catch (e) { return null; } };
    const [profiles, reports, docs, cov] = await Promise.all([
      safe(API.http.profiles()), safe(API.http.reports({ limit: 250 })),
      safe(API.http.governanceDocuments()), safe(API.http.coverage()),
    ]);
    ((profiles && profiles.profiles) || []).forEach(s => {
      const name = s.name || s.strategy_name || s.class_name || s.id || '—';
      idx.push({ label: name, sub: `стратегия · ${[s.cell_id || s.cell, s.root || s.instrument_root].filter(Boolean).join(' · ')}`, href: 'strategies.html?strategy=' + encodeURIComponent(name), icon: 'strategies' });
    });
    ((reports && reports.jobs) || []).forEach(j => {
      const lbl = j.label || j.class_name || j.strategy || j.job_id || 'отчёт';
      idx.push({ label: lbl, sub: `отчёт · ${j.status || ''}`, href: 'backtesting.html?job=' + encodeURIComponent(j.job_id || ''), icon: 'backtest' });
    });
    ((docs && docs.documents) || []).forEach(d => {
      idx.push({ label: d.title || d.id, sub: `документ · ${d.category || d.group || ''}`, href: 'documents.html?doc=' + encodeURIComponent(d.id || ''), icon: 'docs' });
    });
    ((cov && cov.instruments) || []).forEach(c => {
      idx.push({ label: c.root, sub: `инструмент · ${c.group || ''} · ${c.strategy_count || 0} проф.`, href: 'backtesting.html?instrument=' + encodeURIComponent(c.root), icon: 'coins' });
    });
    return idx;
  }
  function wireSearch() {
    const input = qs('#global-search'); const box = qs('#search-results');
    if (!input || !box) return;
    const offline = !window.API || API.config.offline;
    let index = null, indexPromise = null, items = [];
    function close() { box.hidden = true; box.innerHTML = ''; items = []; }
    function ensureIndex() {
      if (index) return Promise.resolve(index);
      if (!indexPromise) {
        indexPromise = (offline ? Promise.resolve(buildSearchIndexMock()) : buildSearchIndexReal())
          .then(idx => { index = idx; return idx; })
          .catch(() => { index = null; return null; });
      }
      return indexPromise;
    }
    function render(q) {
      items = index.filter(e => e.label.toLowerCase().includes(q) || (e.sub || '').toLowerCase().includes(q)).slice(0, 8);
      if (!items.length) { box.innerHTML = `<div class="search-empty">Ничего не найдено по «${esc(q)}»</div>`; box.hidden = false; return; }
      box.innerHTML = items.map((e, i) => `<a class="search-item ${i === 0 ? 'active' : ''}" href="${e.href}">${icon(e.icon)}<span class="si-main"><span class="si-label">${esc(e.label)}</span><span class="si-sub">${esc(e.sub)}</span></span></a>`).join('');
      box.hidden = false;
    }
    async function run(raw) {
      const q = raw.trim().toLowerCase();
      if (!q) { close(); return; }
      if (!index) { box.innerHTML = '<div class="search-empty"><span class="spinner"></span> Индексация…</div>'; box.hidden = false; await ensureIndex(); }
      if (!index) { box.innerHTML = '<div class="search-empty">Поиск недоступен</div>'; box.hidden = false; return; }
      if (input.value.trim().toLowerCase() === q) render(q);
    }
    input.addEventListener('input', () => run(input.value));
    input.addEventListener('focus', () => { ensureIndex(); if (input.value) run(input.value); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && items.length) { e.preventDefault(); window.location.href = items[0].href; }
      else if (e.key === 'Escape') { close(); input.blur(); }
    });
    document.addEventListener('click', (e) => { if (!e.target.closest('.tb-search-wrap')) close(); });
  }

  // dropdown menu anchored to a button
  function menu(anchor, items) {
    closeMenu();
    const m = el(`<div class="menu"></div>`);
    items.forEach(it => {
      if (it.divider) { m.appendChild(el('<div class="menu-sep"></div>')); return; }
      const row = el(`<button class="menu-item ${it.danger ? 'danger' : ''}">${it.icon ? icon(it.icon) : ''}<span>${it.label}</span></button>`);
      row.onclick = () => { closeMenu(); it.onClick && it.onClick(); };
      m.appendChild(row);
    });
    document.body.appendChild(m);
    const r = anchor.getBoundingClientRect();
    m.style.top = (r.bottom + 6) + 'px';
    m.style.right = (window.innerWidth - r.right) + 'px';
    requestAnimationFrame(() => m.classList.add('open'));
    document._menu = m;
    setTimeout(() => document.addEventListener('click', closeMenu, { once: true }), 0);
  }
  function closeMenu() { if (document._menu) { document._menu.remove(); document._menu = null; } }

  // pages inject contextual top-bar buttons here
  function pageActions(html) { const slot = qs('#page-actions'); if (slot) slot.innerHTML = html; return slot; }

  const READY = [];
  function ready(fn) {
    if (READY._done) { Promise.resolve().then(fn).catch(e => { if (!(e && e.name === 'AbortError')) reportError(e); }); }
    else READY.push(fn);
  }

  // ---- page lifecycle: cleanup of polls / aborts on navigation away ----------
  const CLEANUP = [];
  function onLeave(fn) { CLEANUP.push(fn); }
  function disposeAll() { while (CLEANUP.length) { try { CLEANUP.pop()(); } catch (e) { /* ignore */ } } }
  window.addEventListener('pagehide', disposeAll);
  window.addEventListener('beforeunload', disposeAll);
  window.addEventListener('unhandledrejection', (e) => { if (e.reason && e.reason.name === 'AbortError') return; reportError(e.reason || e); });

  // AbortController whose signal is auto-aborted when the page is left.
  function signal() { const c = new AbortController(); onLeave(() => c.abort()); return c.signal; }
  // Interval poll that is automatically cleared on navigation away. Returns stop().
  function poll(fn, ms) {
    let stopped = false;
    const tick = async () => { if (stopped) return; try { await fn(); } catch (e) { if (!(e && e.name === 'AbortError')) reportError(e); } };
    const id = setInterval(tick, ms);
    const stop = () => { stopped = true; clearInterval(id); };
    onLeave(stop);
    tick();
    return stop;
  }

  // ---- standard async states (loading / empty / error+retry) -----------------
  function renderLoading(node, label) {
    if (node) node.innerHTML = `<div class="state-loading"><span class="spinner"></span>${esc(label || 'Загрузка…')}</div>`;
  }
  function renderEmpty(node, label) {
    if (node) node.innerHTML = `<div class="empty-state">${esc(label || 'Нет данных за выбранный период.')}</div>`;
  }
  function renderError(node, err, retry) {
    if (!node) return;
    const msg = (err && err.message) ? err.message : String(err);
    node.innerHTML = `<div class="state-error">${icon('close')}<div><div class="se-title">Не удалось загрузить данные</div><div class="se-msg">${esc(msg).slice(0, 160)}</div></div><button class="btn sm" data-retry>${icon('refresh')}Повторить</button></div>`;
    const btn = node.querySelector('[data-retry]');
    if (btn && retry) btn.addEventListener('click', retry);
  }

  function startClock() {
    const node = qs('#clock'); const dateNode = qs('#pt-date'); if (!node) return;
    function tick() {
      // real Pacific time (the market clock the platform runs on)
      let txt;
      try {
        txt = new Date().toLocaleTimeString('ru-RU', { timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit', second: '2-digit' });
      } catch (e) {
        txt = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      }
      node.textContent = txt + ' PT';
      if (dateNode) {
        try { dateNode.textContent = new Date().toLocaleDateString('ru-RU', { timeZone: AuroraDomain.PT_ZONE, weekday: 'long', day: 'numeric', month: 'long' }); }
        catch (e) { dateNode.textContent = new Date().toLocaleDateString('ru-RU'); }
      }
    }
    tick(); setInterval(tick, 1000);
  }

  // ---- toast ------------------------------------------------------------------
  function toast(msg) {
    let wrap = qs('.toast-wrap'); if (!wrap) { wrap = el('<div class="toast-wrap"></div>'); document.body.appendChild(wrap); }
    const t = el(`<div class="toast">${msg}</div>`); wrap.appendChild(t);
    setTimeout(() => { t.style.transition = 'opacity .3s, transform .3s'; t.style.opacity = '0'; t.style.transform = 'translateY(8px)'; setTimeout(() => t.remove(), 320); }, 2200);
  }

  // ---- drawer -----------------------------------------------------------------
  function drawer(titleHtml, bodyHtml) {
    let back = qs('.drawer-back');
    if (!back) {
      back = el('<div class="drawer-back"></div>');
      const d = el('<aside class="drawer"><div class="drawer-resize" aria-hidden="true"></div><div class="drawer-h"></div><div class="drawer-b"></div></aside>');
      document.body.appendChild(back); document.body.appendChild(d);
      back.addEventListener('click', closeDrawer);
      back._d = d;
      wireDrawerResize(d);
    }
    const d = back._d;
    d.style.width = '';
    d.classList.remove('wide', 'full', 'custom');
    qs('.drawer-h', d).innerHTML = `<div class="drawer-title">${titleHtml}</div><div class="drawer-tools"><button class="btn sm ghost" data-drawer-size="wide">Шире</button><button class="btn sm ghost" data-drawer-size="full">На весь экран</button><button class="btn icon ghost" data-close-drawer aria-label="Закрыть">${icon('close')}</button></div>`;
    qs('.drawer-b', d).innerHTML = bodyHtml;
    requestAnimationFrame(() => { back.classList.add('open'); d.classList.add('open'); });
    return d;
  }
  function setDrawerSize(drawerNode, size) {
    drawerNode.style.width = '';
    drawerNode.classList.remove('wide', 'full', 'custom');
    if (size === 'wide') drawerNode.classList.add('wide');
    if (size === 'full') drawerNode.classList.add('full');
  }
  function wireDrawerResize(drawerNode) {
    const handle = qs('.drawer-resize', drawerNode);
    handle.addEventListener('pointerdown', event => {
      if (window.innerWidth <= 760) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = drawerNode.getBoundingClientRect().width;
      handle.setPointerCapture(event.pointerId);
      const move = current => {
        const width = Math.max(480, Math.min(window.innerWidth, startWidth + startX - current.clientX));
        drawerNode.classList.remove('wide', 'full');
        drawerNode.classList.add('custom');
        drawerNode.style.width = width + 'px';
      };
      const finish = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', finish);
        handle.removeEventListener('pointercancel', finish);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', finish);
      handle.addEventListener('pointercancel', finish);
    });
  }
  function closeDrawer() { const back = qs('.drawer-back'); if (back) { back.classList.remove('open'); back._d.classList.remove('open'); } }

  // table sorting — safe to call repeatedly (clones headers to drop stale listeners)
  function sortable(table, rows, render) {
    let dir = -1, key = null;
    qsa('th.sortable', table).forEach(orig => {
      const th = orig.cloneNode(true);
      qsa('.arrow', th).forEach(a => a.remove());
      orig.replaceWith(th);
      th.addEventListener('click', () => {
        const k = th.dataset.sort;
        dir = key === k ? -dir : -1; key = k;
        rows.sort((a, b) => { const av = a[k], bv = b[k]; return (av < bv ? 1 : av > bv ? -1 : 0) * dir; });
        qsa('th.sortable .arrow', table).forEach(a => a.remove());
        th.insertAdjacentHTML('beforeend', `<span class="arrow"> ${dir < 0 ? '▼' : '▲'}</span>`);
        render(rows);
      });
    });
  }

  window.UI = { icon, money, pct, pnlClass, badge, esc, el, qs, qsa, toast, drawer, closeDrawer, sortable, ready, menu, pageActions, onLeave, signal, poll, renderLoading, renderEmpty, renderError, reportError, enhanceA11y, action, getSelectedAccount, setSelectedAccount, NAV };
  document.addEventListener('DOMContentLoaded', buildShell);
})();
