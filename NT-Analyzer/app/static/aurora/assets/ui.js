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
    chat: '<path d="M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2v10Z"/><path d="M8 9h8M8 13h5"/>',
    send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8"/>',
    pin: '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6ZM12 14v7"/>',
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
    palette: '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.5 0-.5-.3-.9-.6-1.2-.3-.3-.5-.6-.5-1 0-.8.7-1.3 1.5-1.3H15a5 5 0 0 0 5-5c0-4-3.6-7-8-7Z"/><circle cx="7.5" cy="11" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="16.5" cy="11" r="1"/>',
  };
  function icon(name, cls) { return `<svg class="${cls || 'ic'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${I[name] || ''}</svg>`; }
  const APP_NAME = 'StratForge AI';
  const APP_KICKER = 'StratForge AI · NTA Edition';

  // ---- app theme (auto / dark / light) ---------------------------------------
  const THEME_KEY = 'app.theme';
  function loadTheme() { try { return localStorage.getItem(THEME_KEY) || 'auto'; } catch (e) { return 'auto'; } }
  function applyTheme(mode) {
    const m = (mode === 'dark' || mode === 'light') ? mode : 'auto';
    if (document.documentElement) document.documentElement.setAttribute('data-theme', m);
  }
  function setTheme(mode) {
    const m = (mode === 'dark' || mode === 'light') ? mode : 'auto';
    try { localStorage.setItem(THEME_KEY, m); } catch (e) { /* ignore */ }
    applyTheme(m);
  }
  applyTheme(loadTheme());  // apply immediately to avoid a flash before shell builds
  const BRAND_MARK = 'brand/stratforge-mark.png';

  const NAV = [
    { id: 'overview', label: 'Обзор', href: 'index.html', icon: 'overview' },
    { id: 'backtest', label: 'Бэктест', href: 'backtesting.html', icon: 'backtest' },
    { id: 'trading', label: 'Торговля', href: 'trading.html', icon: 'trading' },
    { id: 'performance', label: 'Финансы', href: 'performance.html', icon: 'performance' },
    { id: 'strategies', label: 'Стратегии', href: 'strategies.html', icon: 'strategies' },
    { id: 'ai', label: 'AI Lab', href: 'ai-lab.html', icon: 'ai' },
    { id: 'agents', label: 'AI Agents', href: 'ai-agents.html', icon: 'plug' },
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

  function normalizeNewsKey(text) {
    return String(text || '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function itemSeverity(item) {
    const raw = String((item && (item.severity || item.impact)) || 'low').toLowerCase();
    return ['high', 'medium', 'low'].includes(raw) ? raw : 'low';
  }

  function itemTimeMs(item) {
    const stamp = new Date((item && (item.event_time_utc || item.published_at_utc)) || 0).getTime();
    return Number.isFinite(stamp) ? stamp : 0;
  }

  function itemInstruments(item, maxCount) {
    const rows = (item && (item.affected_instruments || item.instruments)) || [];
    const unique = Array.from(new Set((Array.isArray(rows) ? rows : []).filter(Boolean).map(value => String(value))));
    if (!unique.length) return '';
    const limit = Math.max(1, maxCount || 3);
    const shown = unique.slice(0, limit).join('/');
    return unique.length > limit ? `${shown}+${unique.length - limit}` : shown;
  }

  function uniqueTickerRows(rows, limit) {
    const seen = new Set();
    const out = [];
    (rows || []).forEach(row => {
      if (!row || !row.text) return;
      const key = normalizeNewsKey(row.dedupeKey || row.title || row.text);
      if (seen.has(key)) return;
      seen.add(key);
      out.push(row);
    });
    return out.slice(0, limit || 18);
  }

  function expandTickerRows(rows, targetCount) {
    const base = (rows || []).filter(Boolean);
    if (!base.length) return [];
    const total = Math.max(base.length, targetCount || 12);
    const out = [];
    let cycle = 0;
    while (out.length < total) {
      const offset = base.length > 1 ? ((cycle * 2) + 1) % base.length : 0;
      const rotated = cycle === 0 ? base : base.slice(offset).concat(base.slice(0, offset));
      rotated.forEach(row => {
        if (out.length >= total) return;
        if (!out.length || normalizeNewsKey(out[out.length - 1].text) !== normalizeNewsKey(row.text)) out.push(row);
      });
      if (base.length === 1) break;
      cycle += 1;
      if (cycle > total) break;
    }
    return out;
  }

  function ptMinuteOfDay(date) {
    if (!window.AuroraDomain || !AuroraDomain.ptParts) return 0;
    const p = AuroraDomain.ptParts(date || new Date());
    return p.hour * 60 + p.minute;
  }

  function inPtWindow(minute, start, end) {
    return start <= end ? minute >= start && minute < end : minute >= start || minute < end;
  }

  function ptMinutesUntil(minute, target) {
    return target >= minute ? target - minute : 1440 - minute + target;
  }

  function samePtDay(a, b) {
    if (!window.AuroraDomain || !AuroraDomain.ptParts) return false;
    const pa = AuroraDomain.ptParts(a);
    const pb = AuroraDomain.ptParts(b);
    return pa.year === pb.year && pa.month === pb.month && pa.day === pb.day;
  }

  function marketNoticeRows(events, now) {
    const rows = [];
    const current = new Date(now || Date.now());
    if (window.AuroraDomain && AuroraDomain.marketStatus) {
      const market = AuroraDomain.marketStatus(current);
      const sev = market.state === 'warn' ? 'medium' : market.state === 'off' ? 'medium' : 'low';
      rows.push({ severity: sev, text: `📈 CME futures: ${market.label}`, dedupeKey: `market:cme:${market.phase}` });
      if (market.phase === 'maintenance') {
        rows.push({ severity: 'medium', text: '⛔ Идёт техпауза CME: новые входы лучше отложить до открытия', dedupeKey: 'market:maintenance' });
      } else if (market.phase === 'weekend') {
        rows.push({ severity: 'low', text: '🌙 Американская cash-сессия закрыта: фокус смещается на открытие Европы и Азии', dedupeKey: 'market:weekend' });
      }
    }
    if (window.AuroraDomain && AuroraDomain.ptParts) {
      const minute = ptMinuteOfDay(current);
      const sessions = [
        { id: 'asia', label: 'азиатская сессия', start: 17 * 60, end: 1 * 60, severity: 'low' },
        { id: 'europe', label: 'европейская сессия', start: 0, end: 8 * 60, severity: 'low' },
        { id: 'us', label: 'американская cash-сессия', start: 6 * 60 + 30, end: 13 * 60, severity: 'medium' },
      ];
      const active = sessions.filter(session => inPtWindow(minute, session.start, session.end));
      if (active.length) {
        rows.push({
          severity: active.some(session => session.id === 'us') ? 'medium' : 'low',
          text: `🕒 Сейчас активна ${active.map(session => session.label).join(' и ')}`,
          dedupeKey: `market:active:${active.map(session => session.id).join(',')}`,
        });
      } else {
        rows.push({ severity: 'low', text: '🕒 Сейчас вне основных cash-сессий США, Европы и Азии', dedupeKey: 'market:active:none' });
      }
      const next = sessions
        .filter(session => !active.some(item => item.id === session.id))
        .map(session => ({ session, minutes: ptMinutesUntil(minute, session.start) }))
        .sort((a, b) => a.minutes - b.minutes)[0];
      if (next) {
        rows.push({
          severity: next.session.severity,
          text: `⏭ Следующая сессия: ${next.session.label} откроется ${newsEta(next.minutes * 60000)}`,
          dedupeKey: `market:next:${next.session.id}`,
        });
      }
    }
    const list = Array.isArray(events) ? events : [];
    const upcoming24 = list
      .filter(item => {
        const at = itemTimeMs(item);
        const remaining = at - current.getTime();
        return remaining > 0 && remaining <= 24 * 3600000;
      })
      .sort((a, b) => itemTimeMs(a) - itemTimeMs(b));
    const todayCount = list.filter(item => samePtDay(current, new Date(item.event_time_utc || 0))).length;
    if (todayCount) {
      rows.push({
        severity: upcoming24.some(item => itemSeverity(item) === 'high') ? 'medium' : 'low',
        text: `📅 Сегодня в календаре ${todayCount} событий${upcoming24[0] ? ` · ближайшее ${newsEta(itemTimeMs(upcoming24[0]) - current.getTime())}` : ''}`,
        dedupeKey: `market:today:${todayCount}`,
      });
    } else if (upcoming24[0]) {
      rows.push({
        severity: 'low',
        text: `📅 Ближайшее событие календаря ${newsEta(itemTimeMs(upcoming24[0]) - current.getTime())}`,
        dedupeKey: `market:upcoming:${upcoming24[0].id || upcoming24[0].title || ''}`,
      });
    }
    return uniqueTickerRows(rows, 8);
  }

  function scheduleStrategyRows(events, now, limit) {
    const current = Number(now || Date.now());
    const list = Array.isArray(events) ? events : [];
    const rows = [];
    const immediate = list
      .filter(item => {
        const severity = itemSeverity(item);
        const remaining = itemTimeMs(item) - current;
        if (!item || !item.title || !['high', 'medium'].includes(severity)) return false;
        if (severity === 'high') return remaining >= -(Number(item.block_after_min || 0) * 60000 + 90 * 60000) && remaining <= 72 * 3600000;
        return remaining > 0 && remaining <= 36 * 3600000;
      })
      .sort((a, b) => itemTimeMs(a) - itemTimeMs(b));

    immediate.forEach(item => {
      const remaining = itemTimeMs(item) - current;
      const severity = itemSeverity(item);
      const target = itemInstruments(item, 3);
      const timing = remaining <= 0 ? 'только что вышло' : newsEta(remaining);
      const prefix = remaining <= 0 ? '🟢' : severity === 'high' ? '🎯' : '⚙';
      rows.push({
        severity: severity === 'high' ? 'high' : 'medium',
        text: `${prefix} ${timing}: ${item.title}${target ? ` · ${target}` : ''}${item.is_confirmed ? '' : ' · время требует проверки'}`,
        url: item.url || item.source_url || '',
        dedupeKey: `event:${item.id || item.title}`,
      });
    });

    if (rows.length < 4) {
      const laterHigh = list
        .filter(item => {
          const remaining = itemTimeMs(item) - current;
          return item && item.title && itemSeverity(item) === 'high' && remaining > 72 * 3600000 && remaining <= 7 * 24 * 3600000;
        })
        .sort((a, b) => itemTimeMs(a) - itemTimeMs(b))
        .slice(0, 4 - rows.length);
      laterHigh.forEach(item => rows.push({
        severity: 'medium',
        text: `📅 ${newsEta(itemTimeMs(item) - current)}: ${item.title}${itemInstruments(item, 3) ? ` · ${itemInstruments(item, 3)}` : ''}`,
        url: item.url || item.source_url || '',
        dedupeKey: `event:${item.id || item.title}`,
      }));
    }

    return uniqueTickerRows(rows, limit || 10);
  }

  function renderGlobalNewsStrip(strip, calendar, live, agentNews) {
    const label = qs('.global-news-label', strip);
    const track = qs('.global-news-track', strip);
    const now = Date.now();
    const events = (calendar && calendar.items) || [];
    const liveItems = ((live && live.items) || [])
      .filter(item => item && item.title && itemSeverity(item) !== 'low')
      .filter(item => item.age_min == null || (item.age_min >= -5 && item.age_min <= 720))
      .sort((a, b) => itemTimeMs(b) - itemTimeMs(a));
    const severity = item => itemSeverity(item);
    const eventMs = item => itemTimeMs(item);
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
    const warning = !critical && (upcoming.some(item => eventMs(item) - now <= 24 * 3600000) || liveItems.some(item => severity(item) === 'high'));
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
      dedupeKey: `event:${item.id || item.title}`,
    }));
    liveItems.filter(item => severity(item) === 'high').slice(0, 4).forEach(item => rows.push({
      severity: 'high',
      text: `🔴 ВАЖНАЯ НОВОСТЬ · ${item.source || 'источник'}: ${item.title}${item.age_min == null ? '' : ' · ' + newsAge(item.age_min)}`,
      url: item.url || item.source_url || '',
      dedupeKey: `live:${item.source || ''}:${item.title || ''}`,
    }));
    upcoming.slice(0, 4).forEach(item => rows.push({
      severity: item.is_confirmed ? 'high' : 'medium',
      text: `${item.is_confirmed ? '📅' : '⚠ оценка'} ${newsEta(eventMs(item) - now)}: ${item.title}`,
      url: item.url || item.source_url || '',
      dedupeKey: `event:${item.id || item.title}`,
    }));
    liveItems.filter(item => severity(item) === 'medium').slice(0, 4).forEach(item => rows.push({
      severity: 'medium',
      text: `${item.source || 'источник'}: ${item.title}${item.age_min == null ? '' : ' · ' + newsAge(item.age_min)}`,
      url: item.url || item.source_url || '',
      dedupeKey: `live:${item.source || ''}:${item.title || ''}`,
    }));
    ((agentNews && agentNews.items) || []).slice(0, 6).forEach(item => rows.push({
      severity: item.severity || 'medium',
      text: `🧠 Никита: ${item.title} — ${String(item.recommendation || '').slice(0, 180)}`,
      url: item.source_url || '',
      dedupeKey: `agent:${item.news_id || item.title}`,
    }));

    let unique = uniqueTickerRows(rows.concat(scheduleStrategyRows(events, now, 12)), 24);
    if (unique.length < 10) unique = uniqueTickerRows(unique.concat(marketNoticeRows(events, now)), 24);
    if (!unique.length) {
      track.classList.add('paused');
      track.innerHTML = '<span class="global-news-static">Нет свежих важных сообщений; календарь доступен на вкладке «Новости».</span>';
      return;
    }
    track.classList.remove('paused');
    const expanded = expandTickerRows(unique, unique.length < 10 ? 20 : 14);
    const rollover = expanded.length > 1 ? expanded.slice(1).concat(expanded.slice(0, 1)) : expanded;
    const renderRow = row => {
      const content = `<span class="dot"></span><b>${esc(row.text)}</b>`;
      return row.url
        ? `<a class="global-news-item ${row.severity}" href="${esc(row.url)}" target="_blank" rel="noopener noreferrer">${content}</a>`
        : `<span class="global-news-item ${row.severity}">${content}</span>`;
    };
    track.innerHTML = expanded.map(renderRow).join('') + rollover.map(renderRow).join('');
  }

  function wireGlobalNewsStrip(strip) {
    if (!strip || !window.API || !API.http) return;
    const refresh = async () => {
      try {
        const [calendar, live, agentNews] = await Promise.all([
          API.http.news({ limit: 120 }, { signal: signal() }),
          API.http.newsLive({ max_age_min: 720, limit: 40 }, { signal: signal() }).catch(() => null),
          API.http.newsAnalysis({ limit: 20 }, { signal: signal() }).catch(() => null),
        ]);
        renderGlobalNewsStrip(strip, calendar, live, agentNews);
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
    if (newsStrip) main.classList.add('has-global-news-strip');
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
    buildOrchestratorWidget();
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

  function telegramRightRow(label, ok) {
    return `<div class="row"><div class="row-main"><div class="row-title">${esc(label)}</div></div><div class="row-val ${ok ? 'pos' : 'neg'}">${ok ? 'да' : 'нет'}</div></div>`;
  }

  function showThemePicker() {
    const opts = [
      ['auto', 'Автоматически', 'Как в системе (сейчас по умолчанию)'],
      ['dark', 'Тёмная', 'Тёмный интерфейс Aurora'],
      ['light', 'Светлая', 'Светлый интерфейс'],
    ];
    const render = () => {
      const current = loadTheme();
      const html = `<div class="list theme-picker">${opts.map(o => `
        <button class="row theme-opt ${o[0] === current ? 'active' : ''}" data-theme-opt="${o[0]}">
          <div class="row-main"><div class="row-title">${esc(o[1])}</div><div class="row-sub">${esc(o[2])}</div></div>
          <div class="row-val">${o[0] === current ? icon('check') : ''}</div>
        </button>`).join('')}</div>
        <div class="finance-note">Тема сохраняется в этом браузере и действует на всех страницах приложения.</div>`;
      const d = drawer('<h3>Тема приложения</h3>', html);
      const body = qs('.drawer-b', d);
      qsa('[data-theme-opt]', body).forEach(b => b.addEventListener('click', () => { setTheme(b.dataset.themeOpt); toast('Тема применена'); render(); }));
    };
    render();
  }

  async function showTelegram() {
    if (!window.API || API.config.offline) { toast('Telegram недоступен в офлайн-превью'); return; }
    const d = drawer('<h3>Telegram</h3>', '<div class="state-loading"><span class="spinner"></span>Проверка подключения…</div>');
    const body = qs('.drawer-b', d);

    async function refresh() {
      try {
        const status = await API.http.telegramStatus();
        let group = null;
        if (status.token_configured) { try { group = await API.http.telegramGroupStatus(); } catch (e) { group = null; } }
        const connectionLabel = status.configured ? 'подключён' : status.token_configured ? 'нужно подключить чат' : 'не настроен';
        const botLabel = status.bot_username ? `@${status.bot_username}` : (status.bot_name || 'бот не проверен');
        const settingRows = (status.setting_definitions || []).map(item => {
          const checked = status.settings && status.settings[item.key];
          const unavailable = item.key !== 'enabled' && !status.configured;
          return `<label class="telegram-setting ${unavailable ? 'disabled' : ''}">
            <span class="telegram-setting-copy"><strong>${esc(item.label)}</strong><small>${esc(item.description)}</small></span>
            <input type="checkbox" data-telegram-setting="${esc(item.key)}" ${checked ? 'checked' : ''} ${unavailable ? 'disabled' : ''}>
            <span class="telegram-switch" aria-hidden="true"></span>
          </label>`;
        }).join('');

        body.innerHTML = `
          <section class="telegram-card">
            <div class="flex between"><div><div class="section-title">Подключение</div><div class="telegram-bot-name">${esc(botLabel)}</div></div><span class="badge ${status.configured ? 'live' : status.token_configured ? 'pending' : 'archived'}"><span class="dot"></span>${esc(connectionLabel)}</span></div>
            ${status.chat_label ? `<div class="row-sub">Чат: ${esc(status.chat_label)}</div>` : ''}
            ${status.last_delivery_at_utc ? `<div class="row-sub">Последняя отправка: ${esc(status.last_delivery_at_utc)}</div>` : ''}
            ${status.last_error ? `<div class="finance-note telegram-error"><strong>Последняя ошибка:</strong> ${esc(status.last_error)}</div>` : ''}
          </section>

          <section class="telegram-card">
            <div class="section-title">Токен бота</div>
            <div class="field"><label for="telegram-token">${status.token_configured ? 'Новый токен (текущий скрыт)' : 'Токен от BotFather'}</label><input id="telegram-token" type="password" autocomplete="new-password" placeholder="123456789:AA…"></div>
            <div class="flex wrap gap-sm"><button class="btn ${status.token_configured ? '' : 'primary'}" id="telegram-save-token">${status.token_configured ? 'Заменить токен' : 'Сохранить и проверить'}</button>${status.bot_username ? `<a class="btn ghost" href="https://t.me/${esc(status.bot_username)}" target="_blank" rel="noopener">Открыть бота</a>` : ''}</div>
            <div class="row-sub">Токен сохраняется только в локальном gitignored-хранилище backend и никогда не возвращается в браузер.</div>
          </section>

          ${status.token_configured && !status.chat_configured ? `<section class="telegram-card">
            <div class="section-title">Подключение личного чата</div>
            <p class="muted mt-0">Создайте одноразовую ссылку, откройте её и нажмите Start в Telegram.</p>
            <div id="telegram-pair-result"></div>
            <div class="flex wrap gap-sm"><button class="btn primary" id="telegram-pair-start">Создать ссылку</button><button class="btn" id="telegram-pair-complete" ${status.pairing_active ? '' : 'disabled'}>Проверить подключение</button></div>
          </section>` : ''}

          ${status.token_configured ? `<section class="telegram-card">
            <div class="flex between"><div class="section-title">Группа с темами (StratForge AI Control)</div><span class="badge ${group && group.configured ? (group.rights && group.rights.ready ? 'live' : 'pending') : 'archived'}"><span class="dot"></span>${group && group.configured ? (group.rights && group.rights.ready ? 'готова' : 'нужны права') : 'не привязана'}</span></div>
            <p class="muted mt-0">Каждый чат приложения показывается отдельной темой группы. Добавьте бота <strong>@${esc(status.bot_username || 'StratForgeAI_bot')}</strong> в супергруппу с включёнными Topics и сделайте его админом с правом «Управление темами».</p>
            ${group && !group.configured ? `<div class="finance-note"><strong>Как настроить:</strong><br>
              1. Откройте группу → Добавить участников → найдите @${esc(status.bot_username || 'StratForgeAI_bot')} → добавьте.<br>
              2. Откройте профиль бота в группе → Назначить администратором → включите «Управление темами».<br>
              3. Убедитесь, что в группе включены Topics (Групп. темы) в настройках группы.<br>
              4. <strong>Бот обнаружит группу автоматически</strong> при следующем сообщении (≤30 сек) — или введите ID вручную ниже.</div>` : ''}
            ${group && group.configured ? `
              <div class="row-sub">Группа: ${esc(group.group_title || group.group_id || '')}${group.topics_count != null ? ` · тем: ${group.topics_count}` : ''}</div>
              <div class="list" style="margin:8px 0">
                ${telegramRightRow('Темы включены (is_forum)', group.rights && group.rights.is_forum)}
                ${telegramRightRow('Бот — администратор', group.rights && group.rights.is_admin)}
                ${telegramRightRow('Может управлять темами', group.rights && group.rights.can_manage_topics)}
                ${telegramRightRow('Может отправлять сообщения', group.rights && group.rights.can_post_messages)}
              </div>
              ${group.rights && group.rights.error ? `<div class="finance-note telegram-error">${esc(group.rights.error)}</div>` : ''}
              <div class="flex wrap gap-sm"><button class="btn" id="telegram-group-recheck">Проверить права</button><button class="btn danger" id="telegram-group-disconnect">Отвязать группу</button></div>
            ` : `
              <div class="field"><label for="telegram-group-id">ID супергруппы (необязательно — бот обнаружит автоматически)</label><input id="telegram-group-id" inputmode="numeric" placeholder="-1001234567890"></div>
              <div class="flex wrap gap-sm"><button class="btn primary" id="telegram-group-connect">Привязать группу вручную</button></div>
              <div class="row-sub">ID: откройте группу в Telegram Web → скопируйте число из URL (начинается с -100...). Или дождитесь автоопределения после добавления бота.</div>
            `}
          </section>` : ''}

          <section class="telegram-card">
            <div class="section-title">Уведомления</div>
            <div class="telegram-settings">${settingRows}</div>
          </section>

          <div class="finance-note"><strong>Команды из Telegram:</strong> выключены. Запуск бэктестов и торговые действия будут добавляться отдельно после авторизации чата, защиты от повторов и security-аудита.</div>
          <div class="flex wrap gap-sm">${status.configured ? '<button class="btn primary" id="telegram-test">Отправить тест</button>' : ''}${status.token_configured ? '<button class="btn danger" id="telegram-disconnect">Отключить Telegram</button>' : ''}</div>`;

        const saveToken = qs('#telegram-save-token', body);
        if (saveToken) saveToken.onclick = async () => {
          const input = qs('#telegram-token', body);
          const token = input && input.value.trim();
          if (!token) { toast('Введите новый токен Telegram'); return; }
          saveToken.disabled = true;
          try {
            await API.http.telegramSaveToken(token);
            input.value = '';
            toast('Токен проверен и сохранён');
            await refresh();
          } catch (error) { reportError(error); saveToken.disabled = false; }
        };

        const pairStart = qs('#telegram-pair-start', body);
        if (pairStart) pairStart.onclick = async () => {
          pairStart.disabled = true;
          try {
            const pair = await API.http.telegramPairStart();
            const result = qs('#telegram-pair-result', body);
            result.innerHTML = `<div class="telegram-pair"><div>Код: <strong>${esc(pair.code)}</strong></div><a class="btn primary" href="${esc(pair.bot_url)}" target="_blank" rel="noopener">Открыть Telegram и нажать Start</a><div class="row-sub">Ссылка действует 10 минут.</div></div>`;
            const complete = qs('#telegram-pair-complete', body);
            if (complete) complete.disabled = false;
          } catch (error) { reportError(error); pairStart.disabled = false; }
        };

        const pairComplete = qs('#telegram-pair-complete', body);
        if (pairComplete) pairComplete.onclick = async () => {
          pairComplete.disabled = true;
          try { await API.http.telegramPairComplete(); toast('Чат Telegram подключён'); await refresh(); }
          catch (error) { reportError(error); pairComplete.disabled = false; }
        };

        const groupConnect = qs('#telegram-group-connect', body);
        if (groupConnect) groupConnect.onclick = async () => {
          const input = qs('#telegram-group-id', body);
          const gid = input && input.value.trim();
          if (!gid) { toast('Введите ID группы'); return; }
          groupConnect.disabled = true;
          try { await API.http.telegramConfigureGroup(gid); toast('Группа привязана'); await refresh(); }
          catch (error) { reportError(error); groupConnect.disabled = false; }
        };
        const groupRecheck = qs('#telegram-group-recheck', body);
        if (groupRecheck) groupRecheck.onclick = async () => { groupRecheck.disabled = true; try { await refresh(); } catch (e) { groupRecheck.disabled = false; } };
        const groupDisconnect = qs('#telegram-group-disconnect', body);
        if (groupDisconnect) groupDisconnect.onclick = async () => {
          if (!confirm('Отвязать группу и удалить карту тем? Личный чат останется.')) return;
          groupDisconnect.disabled = true;
          try { await API.http.telegramDisconnectGroup(); toast('Группа отвязана'); await refresh(); }
          catch (error) { reportError(error); groupDisconnect.disabled = false; }
        };

        qsa('[data-telegram-setting]', body).forEach(input => {
          input.onchange = async () => {
            input.disabled = true;
            try { await API.http.telegramSettings({ [input.dataset.telegramSetting]: input.checked }); toast('Настройка сохранена'); }
            catch (error) { input.checked = !input.checked; reportError(error); }
            finally { input.disabled = false; }
          };
        });

        const test = qs('#telegram-test', body);
        if (test) test.onclick = async () => {
          test.disabled = true;
          try { await API.http.telegramTest(); toast('Тестовое сообщение отправлено'); await refresh(); }
          catch (error) { reportError(error); test.disabled = false; }
        };

        const disconnect = qs('#telegram-disconnect', body);
        if (disconnect) disconnect.onclick = async () => {
          if (!confirm('Удалить локальный токен, привязку чата и выключить Telegram?')) return;
          disconnect.disabled = true;
          try { await API.http.telegramDisconnect(); toast('Telegram отключён'); await refresh(); }
          catch (error) { reportError(error); disconnect.disabled = false; }
        };
      } catch (error) { renderError(body, error, refresh); }
    }

    await refresh();
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
        { icon: 'palette', label: 'Тема приложения', onClick: () => showThemePicker() },
        { icon: 'telegram', label: 'Telegram', onClick: () => showTelegram() },
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

  // ---- global orchestrator chat widget ---------------------------------------
  // Floating launcher (bottom-right) that opens a full StratForge Orchestrator
  // chat with a conversation list, per-dialogue context, timestamps and titles.
  // Non-blocking: sending shows the message + a typing indicator immediately and
  // only awaits the reply; it never freezes the page.
  const ORCH = {
    built: false, open: false, sending: false,
    conversations: [], currentId: 'default', loadingList: false, pollStop: null,
  };
  const ORCH_KEY = 'orch.currentConversationId';
  function orchLoadLastId() {
    try { return localStorage.getItem(ORCH_KEY) || 'default'; } catch (e) { return 'default'; }
  }
  function orchSaveCurrentId(cid) {
    ORCH.currentId = cid || 'default';
    try { localStorage.setItem(ORCH_KEY, ORCH.currentId); } catch (e) { /* ignore */ }
  }
  function orchFmtTime(iso) {
    if (!iso) return '';
    try {
      return new Intl.DateTimeFormat('ru-RU', {
        timeZone: (window.AuroraDomain && AuroraDomain.PT_ZONE) || 'America/Los_Angeles',
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      }).format(new Date(iso));
    } catch (e) { return String(iso).slice(0, 16); }
  }
  function buildOrchestratorWidget() {
    if (ORCH.built || qs('.orch-fab')) return;
    ORCH.built = true;
    const offline = !window.API || API.config.offline;
    const fab = el(`<button class="orch-fab" id="orch-fab" type="button" title="StratForge Orchestrator — чат с ассистентом" aria-label="Открыть чат оркестратора">${icon('chat')}<span class="orch-fab-dot" aria-hidden="true"></span></button>`);
    const panel = el(`<section class="orch-panel" id="orch-panel" hidden aria-label="Чат StratForge Orchestrator">
      <header class="orch-head">
        <button class="orch-icon-btn orch-list-toggle" id="orch-list-toggle" type="button" title="Список диалогов" aria-label="Список диалогов">${icon('list')}</button>
        <div class="orch-head-title"><span class="orch-head-name">StratForge Orchestrator</span><span class="orch-head-sub" id="orch-head-sub">выбирает модель · работает вместо вас</span></div>
        <button class="orch-icon-btn" id="orch-new" type="button" title="Новый диалог" aria-label="Новый диалог">${icon('plus')}</button>
        <button class="orch-icon-btn" id="orch-close" type="button" title="Свернуть" aria-label="Свернуть">${icon('close')}</button>
      </header>
      <div class="orch-body">
        <aside class="orch-convos" id="orch-convos" aria-label="Диалоги"></aside>
        <div class="orch-main">
          <div class="orch-msgs" id="orch-msgs"><div class="empty-state">Загрузка…</div></div>
          <div class="orch-experts" aria-label="Вызвать специалиста">
            <span>Специалисты</span>
            <button type="button" data-orch-agent="Марина" title="Финансы и бухгалтерия">Марина · финансы</button>
            <button type="button" data-orch-agent="Толик" title="Стратегии и качество тестов">Толик · стратегии</button>
            <button type="button" data-orch-agent="Никита" title="Новости рынка и события приложения">Никита · новости</button>
          </div>
          <form class="orch-input" id="orch-form" autocomplete="off">
            <textarea id="orch-text" rows="1" maxlength="6000" placeholder="Напишите задачу обычным текстом…" ${offline ? 'disabled' : ''}></textarea>
            <button class="orch-mic" id="orch-mic" type="button" title="Голосовой ввод" aria-label="Голосовой ввод" hidden>${icon('mic')}</button>
            <button class="orch-send" id="orch-send" type="submit" title="Отправить" aria-label="Отправить" ${offline ? 'disabled' : ''}>${icon('send')}</button>
          </form>
        </div>
      </div>
    </section>`);
    document.body.appendChild(fab);
    document.body.appendChild(panel);

    fab.addEventListener('click', () => { ORCH.open ? closeOrchestrator() : openOrchestrator(); });
    qs('#orch-close', panel).addEventListener('click', closeOrchestrator);
    qs('#orch-list-toggle', panel).addEventListener('click', () => panel.classList.toggle('show-convos'));
    qs('#orch-new', panel).addEventListener('click', orchNewConversation);
    qs('#orch-form', panel).addEventListener('submit', (e) => { e.preventDefault(); orchSend(); });
    qsa('[data-orch-agent]', panel).forEach(button => button.addEventListener('click', () => orchAddressAgent(button.dataset.orchAgent)));
    const ta = qs('#orch-text', panel);
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px'; });
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); orchSend(); } });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && ORCH.open) closeOrchestrator(); });
    wireOrchestratorVoice(panel);
  }
  function orchAddressAgent(name) {
    const ta = qs('#orch-text');
    if (!ta || ta.disabled) return;
    const clean = ta.value.trim();
    const withoutOldAddress = clean.replace(/^(Марина|Толик|Никита)\s*[,,:;-]?\s*/i, '');
    ta.value = `${name}, ${withoutOldAddress}`;
    ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px';
    ta.focus();
  }
  // Voice input: dictate into the message box using the browser Web Speech API
  // (microphone). No external resources — CSP-safe. Hidden if unsupported.
  function wireOrchestratorVoice(panel) {
    const mic = qs('#orch-mic', panel); const ta = qs('#orch-text', panel);
    if (!mic || !ta) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR || (!window.API || API.config.offline)) { mic.hidden = true; return; }
    mic.hidden = false;
    let rec = null, listening = false, baseText = '';
    function stop() { listening = false; mic.classList.remove('listening'); mic.title = 'Голосовой ввод'; try { if (rec) rec.stop(); } catch (e) { /* ignore */ } }
    mic.addEventListener('click', () => {
      if (listening) { stop(); return; }
      try {
        rec = new SR();
        rec.lang = 'ru-RU';
        rec.interimResults = true;
        rec.continuous = true;
        baseText = ta.value ? ta.value.replace(/\s+$/, '') + ' ' : '';
        rec.onresult = (event) => {
          let finalText = '', interim = '';
          for (let i = event.resultIndex; i < event.results.length; i++) {
            const t = event.results[i][0].transcript;
            if (event.results[i].isFinal) finalText += t; else interim += t;
          }
          if (finalText) baseText = (baseText + finalText).replace(/\s+/g, ' ') + ' ';
          ta.value = (baseText + interim).slice(0, 6000);
          ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px';
        };
        rec.onerror = (event) => { if (event && event.error === 'not-allowed') toast('Нет доступа к микрофону — разрешите его в браузере'); stop(); };
        rec.onend = () => { if (listening) { try { rec.start(); } catch (e) { stop(); } } };
        rec.start();
        listening = true;
        mic.classList.add('listening');
        mic.title = 'Остановить запись';
        ta.focus();
      } catch (e) { toast('Голосовой ввод недоступен в этом браузере'); stop(); }
    });
    onLeave(stop);
  }
  async function openOrchestrator() {
    buildOrchestratorWidget();
    const panel = qs('#orch-panel'); const fab = qs('#orch-fab');
    if (!panel) return;
    ORCH.open = true;
    panel.hidden = false;
    requestAnimationFrame(() => panel.classList.add('open'));
    if (fab) fab.classList.add('active');
    if (!window.API || API.config.offline) {
      qs('#orch-msgs', panel).innerHTML = '<div class="empty-state">Чат оркестратора доступен только в работающем приложении (не в офлайн-превью).</div>';
      return;
    }
    // Restore the last opened conversation so a reload lands where you left off.
    ORCH.currentId = orchLoadLastId();
    await orchLoadConversations();
    await orchLoadMessages(ORCH.currentId);
    const ta = qs('#orch-text', panel); if (ta && !ta.disabled) ta.focus();
    // gentle refresh only while open (keeps context in sync with Telegram/автономная работа)
    if (ORCH.pollStop) ORCH.pollStop();
    let stopped = false;
    const id = setInterval(() => { if (!stopped && ORCH.open && !ORCH.sending) orchLoadMessages(ORCH.currentId, true).catch(() => {}); }, 8000);
    ORCH.pollStop = () => { stopped = true; clearInterval(id); };
  }
  function closeOrchestrator() {
    const panel = qs('#orch-panel'); const fab = qs('#orch-fab');
    ORCH.open = false;
    if (panel) { panel.classList.remove('open'); setTimeout(() => { if (!ORCH.open) panel.hidden = true; }, 220); }
    if (fab) fab.classList.remove('active');
    if (ORCH.pollStop) { ORCH.pollStop(); ORCH.pollStop = null; }
  }
  async function orchLoadConversations() {
    const wrap = qs('#orch-convos'); if (!wrap) return;
    try {
      const data = await API.http.aiOrchestratorConversations();
      ORCH.conversations = data.conversations || [];
    } catch (e) { ORCH.conversations = []; }
    if (!ORCH.conversations.some(c => c.conversation_id === ORCH.currentId)) {
      orchSaveCurrentId((ORCH.conversations[0] && ORCH.conversations[0].conversation_id) || 'default');
    }
    orchRenderConversations();
  }
  function orchRenderConversations() {
    const wrap = qs('#orch-convos'); if (!wrap) return;
    wrap.innerHTML = ORCH.conversations.map(c => {
      const active = c.conversation_id === ORCH.currentId;
      const canEdit = !c.is_default;
      const pinned = !!c.pinned;
      return `<div class="orch-convo ${active ? 'active' : ''} ${pinned ? 'pinned' : ''}" data-cid="${esc(c.conversation_id)}" role="button" tabindex="0">
        <div class="orch-convo-main">
          <div class="orch-convo-title">${pinned ? icon('pin') : ''}${esc(c.title || 'Диалог')}</div>
          <div class="orch-convo-sub">${orchFmtTime(c.updated_at_utc)} · ${Number(c.message_count || 0)} сообщ.</div>
        </div>
        <div class="orch-convo-acts">
          <button class="orch-icon-btn sm ${pinned ? 'on' : ''}" data-pin="${esc(c.conversation_id)}" data-pinned="${pinned ? '1' : '0'}" title="${pinned ? 'Открепить' : 'Закрепить вверху'}" aria-label="Закрепить">${icon('pin')}</button>
          ${canEdit ? `<button class="orch-icon-btn sm" data-rename="${esc(c.conversation_id)}" title="Переименовать" aria-label="Переименовать">${icon('edit')}</button><button class="orch-icon-btn sm" data-del="${esc(c.conversation_id)}" title="Удалить" aria-label="Удалить">${icon('trash')}</button>` : ''}
        </div>
      </div>`;
    }).join('') || '<div class="empty-state">Диалогов нет.</div>';
    qsa('.orch-convo', wrap).forEach(node => {
      node.addEventListener('click', (e) => {
        if (e.target.closest('[data-rename]') || e.target.closest('[data-del]') || e.target.closest('[data-pin]')) return;
        orchSelectConversation(node.dataset.cid);
      });
    });
    qsa('[data-pin]', wrap).forEach(b => b.addEventListener('click', (e) => { e.stopPropagation(); orchPin(b.dataset.pin, b.dataset.pinned !== '1'); }));
    qsa('[data-rename]', wrap).forEach(b => b.addEventListener('click', (e) => { e.stopPropagation(); orchRename(b.dataset.rename); }));
    qsa('[data-del]', wrap).forEach(b => b.addEventListener('click', (e) => { e.stopPropagation(); orchDelete(b.dataset.del); }));
  }
  async function orchPin(cid, pinned) {
    try { await API.http.aiOrchestratorPinConversation(cid, pinned); await orchLoadConversations(); }
    catch (e) { reportError(e); }
  }
  async function orchSelectConversation(cid) {
    if (!cid || cid === ORCH.currentId) { qs('#orch-panel').classList.remove('show-convos'); return; }
    orchSaveCurrentId(cid);
    orchRenderConversations();
    qs('#orch-panel').classList.remove('show-convos');
    await orchLoadMessages(cid);
    const ta = qs('#orch-text'); if (ta && !ta.disabled) ta.focus();
  }
  async function orchNewConversation() {
    if (!window.API || API.config.offline) return;
    try {
      const res = await API.http.aiOrchestratorCreateConversation('');
      orchSaveCurrentId((res.conversation && res.conversation.conversation_id) || 'default');
      await orchLoadConversations();
      await orchLoadMessages(ORCH.currentId);
      qs('#orch-panel').classList.remove('show-convos');
      const ta = qs('#orch-text'); if (ta && !ta.disabled) ta.focus();
    } catch (e) { reportError(e); }
  }
  async function orchRename(cid) {
    const current = ORCH.conversations.find(c => c.conversation_id === cid);
    const title = prompt('Название диалога:', (current && current.title) || '');
    if (title == null) return;
    const clean = String(title).trim();
    if (!clean) return;
    try { await API.http.aiOrchestratorRenameConversation(cid, clean); await orchLoadConversations(); }
    catch (e) { reportError(e); }
  }
  async function orchDelete(cid) {
    if (!confirm('Удалить этот диалог вместе с его историей?')) return;
    try {
      await API.http.aiOrchestratorDeleteConversation(cid);
      if (ORCH.currentId === cid) orchSaveCurrentId('default');
      await orchLoadConversations();
      await orchLoadMessages(ORCH.currentId);
    } catch (e) { reportError(e); }
  }
  function orchMessageHtml(row) {
    const isUser = row.role === 'user';
    // Provider/model/action diagnostics remain available on AI Agents and in
    // backend logs. The owner-facing chat reads like a normal manager dialogue.
    const meta = [row.agent_name && !isUser ? esc(row.agent_name) : '', orchFmtTime(row.timestamp_utc)].filter(Boolean).join(' · ');
    return `<div class="orch-msg ${isUser ? 'user' : 'assistant'}"><div class="orch-msg-body">${esc(row.content || '')}</div><div class="orch-msg-meta">${meta}</div></div>`;
  }
  async function orchLoadMessages(cid, silent) {
    const box = qs('#orch-msgs'); if (!box) return;
    if (!silent) box.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка диалога…</div>';
    let messages = [];
    try {
      const data = await API.http.aiOrchestratorConversation(cid, { limit: 200 });
      messages = data.messages || [];
    } catch (e) { if (!silent) { renderError(box, e, () => orchLoadMessages(cid)); return; } return; }
    if (ORCH.currentId !== cid) return;
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    box.innerHTML = messages.length ? messages.map(orchMessageHtml).join('') : '<div class="empty-state">Начните диалог: например «Разработай простую стратегию максимально быстро».</div>';
    if (!silent || atBottom) box.scrollTop = box.scrollHeight;
  }
  async function orchSend() {
    if (ORCH.sending) return;
    const ta = qs('#orch-text'); const box = qs('#orch-msgs'); const sendBtn = qs('#orch-send');
    if (!ta || !box) return;
    const text = ta.value.trim();
    if (!text) return;
    if (!window.API || API.config.offline) { toast('Чат недоступен в офлайн-превью'); return; }
    ORCH.sending = true;
    if (sendBtn) sendBtn.disabled = true;
    ta.value = ''; ta.style.height = 'auto';
    // optimistic render: show the owner message + a typing bubble immediately
    if (box.querySelector('.empty-state')) box.innerHTML = '';
    box.insertAdjacentHTML('beforeend', orchMessageHtml({ role: 'user', content: text, timestamp_utc: new Date().toISOString(), source: 'app' }));
    box.insertAdjacentHTML('beforeend', '<div class="orch-msg assistant orch-typing" id="orch-typing"><div class="orch-msg-body"><span class="orch-dots"><i></i><i></i><i></i></span> оркестратор работает…</div></div>');
    box.scrollTop = box.scrollHeight;
    const cid = ORCH.currentId;
    try {
      const res = await API.http.aiOrchestratorMessage(text, cid);
      if (res && res.conversation_id) orchSaveCurrentId(res.conversation_id);
    } catch (e) {
      const typing = qs('#orch-typing'); if (typing) typing.remove();
      box.insertAdjacentHTML('beforeend', `<div class="orch-msg assistant"><div class="orch-msg-body orch-err">Не удалось получить ответ: ${esc((e && e.message) || String(e))}</div></div>`);
      box.scrollTop = box.scrollHeight;
    } finally {
      ORCH.sending = false;
      if (sendBtn) sendBtn.disabled = false;
      const typing = qs('#orch-typing'); if (typing) typing.remove();
      await orchLoadMessages(ORCH.currentId);
      await orchLoadConversations();
      if (ta && !ta.disabled) ta.focus();
    }
  }

  window.UI = { icon, money, pct, pnlClass, badge, esc, el, qs, qsa, toast, drawer, closeDrawer, sortable, ready, menu, pageActions, onLeave, signal, poll, renderLoading, renderEmpty, renderError, reportError, enhanceA11y, action, getSelectedAccount, setSelectedAccount, normalizeNewsKey, uniqueTickerRows, expandTickerRows, marketNoticeRows, scheduleStrategyRows, NAV, openOrchestrator, closeOrchestrator };
  document.addEventListener('DOMContentLoaded', buildShell);
})();
