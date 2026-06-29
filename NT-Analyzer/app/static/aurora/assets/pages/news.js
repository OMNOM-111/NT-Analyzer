UI.ready(async function () {
  const listView = UI.qs('#list-view');
  const PTZ = 'America/Los_Angeles';
  const CAT = { central_bank: 'ЦБ', inflation: 'инфляция', labor: 'труд', growth: 'рост', energy: 'энергия', live: 'новости' };

  // Brief explanations of why each category matters for trading.
  const WHY = {
    central_bank: 'Решение по ключевой ставке ФРС — самый волатильный момент рынка. NQ/ES/MYM/MGC могут двинуться на 1–3% в первые минуты. Рекомендуется выйти из позиций за 30 мин.',
    inflation: 'CPI/PPI/PCE — главный ориентир ФРС. Неожиданное значение разворачивает тренд на весь день. Влияет на все фьючерсы и USD.',
    labor: 'NFP и Jobless Claims — барометр экономики. В день выхода возможны гэпы по NQ/ES/MYM в первые 5–10 минут.',
    growth: 'ВВП влияет на долгосрочный сентимент. Волатильность умеренная, но вблизи экспирации может быть усиленной.',
    energy: 'Данные EIA по запасам нефти прямо двигают CL/MCL. Особо критично для нефтяных стратегий.',
    live: 'Горячая новость — оцените влияние перед входом в сделку.',
  };

  const state = {
    events: [],
    live: {
      items: [], all_items: [], providers: [],
      last_fetch_utc: '', configured: false,
      providers_ok: 0, providers_total: 0,
      max_age_min: 60, total_recent: 0,
    },
    cal: null,
    selDay: null,
  };

  // ---- time helpers (PT-first) -------------------------------------------
  const fmtKey  = new Intl.DateTimeFormat('en-CA', { timeZone: PTZ, year: 'numeric', month: '2-digit', day: '2-digit' });
  const fmtTime = new Intl.DateTimeFormat('ru-RU', { timeZone: PTZ, hour: '2-digit', minute: '2-digit' });
  const fmtDay  = new Intl.DateTimeFormat('ru-RU', { timeZone: PTZ, day: '2-digit', month: 'short' });
  function pt(iso) { const d = new Date(iso); return { d, key: fmtKey.format(d), time: fmtTime.format(d), day: fmtDay.format(d) }; }
  function todayKey() { return fmtKey.format(new Date()); }
  function eta(ms) {
    if (ms <= 0) return { txt: 'идёт / прошло', live: true };
    const m = Math.round(ms / 60000), h = Math.floor(m / 60), d = Math.floor(h / 24);
    if (d > 0) return { txt: `через ${d} дн ${h % 24} ч`, live: false };
    if (h > 0) return { txt: `через ${h} ч ${m % 60} мин`, live: false };
    return { txt: `через ${m} мин`, live: m <= 30 };
  }
  function ago(min) {
    if (min == null) return '';
    if (min < 1) return 'только что';
    if (min < 60) return `${Math.round(min)} мин назад`;
    const h = Math.floor(min / 60);
    if (h < 24) return `${h} ч ${Math.round(min % 60)} мин назад`;
    return `${Math.floor(h / 24)} дн назад`;
  }
  const sev = i => (i.severity || i.impact || 'low');

  // ---- filtering ---------------------------------------------------------
  function filtered() {
    const imp = UI.qs('#f-impact').value, cat = UI.qs('#f-cat').value, inst = UI.qs('#f-inst').value;
    return state.events.filter(e =>
      (imp === 'all' || sev(e) === imp) &&
      (cat === 'all' || e.category === cat) &&
      (inst === 'all' || (e.affected_instruments || e.instruments || []).indexOf(inst) >= 0));
  }
  function populateInstruments() {
    const set = new Set();
    state.events.forEach(e => (e.affected_instruments || e.instruments || []).forEach(v => set.add(v)));
    const sel = UI.qs('#f-inst');
    sel.innerHTML = '<option value="all">Все инструменты</option>' +
      Array.from(set).sort().map(v => `<option value="${UI.esc(v)}">${UI.esc(v)}</option>`).join('');
  }

  // ---- list view ---------------------------------------------------------
  function instrTags(item) {
    return (item.affected_instruments || item.instruments || [])
      .map(v => `<span class="tag mono">${UI.esc(v)}</span>`).join('');
  }
  function rowHtml(item, now) {
    const p = pt(item.event_time_utc);
    const e = eta(p.d - now);
    const s = sev(item);
    const isUpcoming = p.d > now;
    const isImminent = item.is_confirmed && isUpcoming && (p.d - now) <= 30 * 60000 && s === 'high';
    const conf = item.is_confirmed ? '<span class="tag">✓ официально</span>' : '<span class="tag muted">оценка</span>';
    const title = item.url
      ? `<a href="${UI.esc(item.url)}" target="_blank" rel="noopener noreferrer">${UI.esc(item.title)}</a>`
      : UI.esc(item.title);
    const badgeLabel = s === 'high' ? '● ВАЖНО' : s === 'medium' ? '● СРЕДН.' : '● НИЗК.';
    const badge = `<span class="impact-badge ${UI.esc(s)}">${badgeLabel}</span>`;
    const blockRow = (item.block_before_min || item.block_after_min)
      ? `<div class="blackout">⛔ блок −${item.block_before_min} / +${item.block_after_min} мин</div>` : '';
    const stopRow = isImminent
      ? '<div class="stop-warn">⛔ Рекомендуем остановить стратегии!</div>' : '';
    return `<article class="news-item impact-${UI.esc(s)}${isUpcoming && s === 'high' ? ' upcoming' : ''}">
      <div class="news-when">
        <div class="d">${UI.esc(p.day)}</div>
        <div class="d">${UI.esc(p.time)}</div>
        <div class="pt">PT · ${UI.esc(item.event_time_et || '')}</div>
      </div>
      <div>
        <h3>${title}</h3>
        <div class="flex wrap gap-sm" style="margin:4px 0">${badge}<span class="section-title">${UI.esc(item.source || 'источник')}</span>${conf}<span class="tag">${UI.esc(CAT[item.category] || item.category || '')}</span>${instrTags(item)}</div>
        ${blockRow}${stopRow}
      </div>
      <div class="news-eta${e.live ? ' live' : ''}">${UI.esc(e.txt)}</div>
    </article>`;
  }
  function renderList() {
    const now = Date.now(), rows = filtered();
    if (!rows.length) {
      UI.renderEmpty(listView, state.events.length
        ? 'Нет событий с выбранными фильтрами.'
        : 'Календарь не сгенерирован. Запустите: python -m app.market_events');
      return;
    }
    const up   = rows.filter(i => new Date(i.event_time_utc) >= now);
    const past = rows.filter(i => new Date(i.event_time_utc) < now).reverse();
    listView.innerHTML =
      (up.length   ? `<div class="news-grp">Предстоящие · ${up.length}</div>${up.map(i => rowHtml(i, now)).join('')}` : '') +
      (past.length ? `<div class="news-grp">Недавние</div>${past.map(i => rowHtml(i, now)).join('')}` : '');
  }

  // ---- calendar ----------------------------------------------------------
  const MONTHS = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
  function eventsByDay() {
    const map = {};
    filtered().forEach(e => {
      const k = pt(e.event_time_utc).key;
      (map[k] = map[k] || []).push(e);
    });
    Object.values(map).forEach(list => list.sort((a, b) => a.event_time_utc < b.event_time_utc ? -1 : 1));
    return map;
  }
  function renderCalendar() {
    if (!state.cal) {
      const t = todayKey().split('-');
      state.cal = { y: +t[0], m: +t[1] - 1 };
    }
    const { y, m } = state.cal;
    UI.qs('#cal-title').textContent = `${MONTHS[m]} ${y}`;
    const map = eventsByDay(), tKey = todayKey();
    const first = new Date(Date.UTC(y, m, 1));
    const startOffset = (first.getUTCDay() + 6) % 7; // Monday-first
    const grid = UI.qs('#cal-grid');
    let html = '';
    for (let i = 0; i < 42; i++) {
      const cell = new Date(Date.UTC(y, m, 1 - startOffset + i));
      const key = `${cell.getUTCFullYear()}-${String(cell.getUTCMonth() + 1).padStart(2,'0')}-${String(cell.getUTCDate()).padStart(2,'0')}`;
      const evs = map[key] || [];
      const hasHigh = evs.some(e => sev(e) === 'high');
      const hasMed  = evs.some(e => sev(e) === 'medium');
      const evCls   = hasHigh ? 'ev-high' : hasMed ? 'ev-medium' : evs.length ? 'ev-low' : '';
      const cls = [
        cell.getUTCMonth() !== m ? 'out' : '',
        key === tKey ? 'today' : '',
        key === state.selDay ? 'sel' : '',
        evCls,
      ].filter(Boolean).join(' ');

      // Show up to 2 event badges inside the cell
      const shown = evs.slice(0, 2);
      const badges = shown.map(e =>
        `<div class="cal-ev s-${UI.esc(sev(e))}"><span class="dot"></span>${UI.esc(pt(e.event_time_utc).time)} ${UI.esc((e.title || '').slice(0, 12))}</div>`
      ).join('');
      const more = evs.length > 2 ? `<div class="cal-more">+${evs.length - 2}</div>` : '';
      const badge = evs.length ? `<span class="cal-ev-count">${evs.length}</span>` : '';

      html += `<div class="cal-cell ${cls}" data-day="${key}" role="button" tabindex="0" aria-label="${UI.esc(dayLabel(key))}, событий: ${evs.length}"><div class="cal-day">${cell.getUTCDate()}</div>${badge}${badges}${more}</div>`;
    }
    grid.innerHTML = html;
    grid.querySelectorAll('.cal-cell').forEach(c => {
      const choose = () => { state.selDay = c.dataset.day; renderCalendar(); renderDayPanel(); };
      c.addEventListener('click', choose);
    });
  }

  // ---- day panel (below calendar) ----------------------------------------
  function dayLabel(key) {
    const [yy, mm, dd] = key.split('-');
    return `${dd} ${MONTHS[+mm - 1]} ${yy}`;
  }
  function renderDayPanel() {
    const node = UI.qs('#side-day');
    if (!state.selDay) { node.classList.remove('visible'); return; }
    node.classList.add('visible');
    const evs = eventsByDay()[state.selDay] || [];
    node.innerHTML = `<div class="side-h">📅 ${UI.esc(dayLabel(state.selDay))}</div>` +
      (evs.length
        ? evs.map(e => `<div class="side-row">
            <div class="t"><span class="dot s-${UI.esc(sev(e))}" style="display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px"></span>${UI.esc(pt(e.event_time_utc).time)} PT · ${UI.esc(e.title)}</div>
            <div class="m">${UI.esc(e.source || '')} · блок −${e.block_before_min}/+${e.block_after_min} мин</div>
          </div>`).join('')
        : '<div class="side-row m">Нет событий в этот день.</div>');
  }

  // ---- strategy stop card ------------------------------------------------
  function renderStopCard(now) {
    const node = UI.qs('#side-stop');
    // Show if high-impact event is within 2 hours (or blackout is active)
    const candidate = filtered()
      .filter(i => {
        const t = new Date(i.event_time_utc).getTime();
        const blockStart = t - (i.block_before_min || 0) * 60000;
        return i.is_confirmed && blockStart <= now + 120 * 60000 && t + (i.block_after_min || 0) * 60000 >= now && sev(i) === 'high';
      })
      .sort((a, b) => a.event_time_utc < b.event_time_utc ? -1 : 1)[0];

    if (!candidate) { node.innerHTML = ''; return; }
    const ms   = new Date(candidate.event_time_utc) - now;
    const e    = eta(ms);
    const p    = pt(candidate.event_time_utc);
    const instrs = (candidate.affected_instruments || candidate.instruments || []);
    const why  = WHY[candidate.category] || 'Ожидается повышенная волатильность рынка.';
    node.innerHTML = `<div class="stop-card">
      <div class="side-h"><span style="font-size:14px;line-height:1">🔴</span> СТОП СТРАТЕГИИ</div>
      <div class="stop-timer">${UI.esc(e.txt)}</div>
      <div class="stop-event-name">${UI.esc(candidate.title)}</div>
      <div class="stop-meta">${UI.esc(p.day)} ${UI.esc(p.time)} PT · блок −${candidate.block_before_min}/+${candidate.block_after_min} мин</div>
      ${instrs.length ? `<div class="stop-meta">Инструменты: ${instrs.map(v => UI.esc(v)).join(', ')}</div>` : ''}
      <div class="stop-why">${UI.esc(why)}</div>
    </div>`;
  }

  // ---- next high-impact sidebar ------------------------------------------
  function renderNext(now) {
    const node = UI.qs('#side-next');
    const next = filtered().filter(i => new Date(i.event_time_utc) >= now && sev(i) === 'high')[0];
    if (!next) {
      node.innerHTML = '<div class="side-h">Ближайшее high-impact</div><div class="side-row m">Нет предстоящих событий высокого влияния.</div>';
      return;
    }
    const ms = new Date(next.event_time_utc) - now;
    // Hide if stop-card already covers this event (within 2h)
    if (ms <= 120 * 60000) { node.innerHTML = ''; return; }
    const e = eta(ms), p = pt(next.event_time_utc);
    const why = WHY[next.category] || '';
    node.innerHTML = `<div class="side-h"><span class="dot s-high" style="width:8px;height:8px;border-radius:50%"></span>Ближайшее high-impact</div>
      <div class="kpi neg" style="margin:0">
        <div class="kpi-top"><span class="kpi-label">${UI.esc(next.title)}</span></div>
        <div class="kpi-val sm">${UI.esc(e.txt)}</div>
        <div class="kpi-foot">${UI.esc(p.day)} ${UI.esc(p.time)} PT · блок −${next.block_before_min}/+${next.block_after_min} мин</div>
      </div>
      ${why ? `<div class="side-row m" style="margin-top:6px;padding-top:6px;border-top:1px solid var(--line);font-size:11px">${UI.esc(why)}</div>` : ''}`;
  }

  // ---- today's events sidebar --------------------------------------------
  function renderToday() {
    const node = UI.qs('#side-today'), tKey = todayKey();
    const evs = filtered().filter(e => pt(e.event_time_utc).key === tKey);
    node.innerHTML = '<div class="side-h">Сегодня</div>' +
      (evs.length
        ? evs.map(e => `<div class="side-row">
            <div class="t"><span class="dot s-${UI.esc(sev(e))}" style="display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px"></span>${UI.esc(pt(e.event_time_utc).time)} PT · ${UI.esc(e.title)}</div>
          </div>`).join('')
        : '<div class="side-row m">На сегодня событий нет.</div>');
  }

  // ---- live news sidebar -------------------------------------------------
  function renderLiveSide() {
    const node = UI.qs('#side-live'), live = state.live;
    const head = `<div class="side-h"><span class="live-dot ${live.total_recent ? '' : 'idle'}"></span>Свежие заголовки</div>`;
    if (!live.configured) {
      node.innerHTML = head + '<div class="side-row m">Лента не настроена. python -m app.market_news</div>';
      return;
    }
    // Use fresh items; fall back to all stored items if none recent
    const src = ((live.items || []).length > 0 ? live.items : (live.all_items || []))
      .filter(item => sev(item) === 'high' || sev(item) === 'medium');
    const items = src.slice(0, 5);
    node.innerHTML = head + (items.length
      ? items.map(i => {
          const title = i.url
            ? `<a href="${UI.esc(i.url)}" target="_blank" rel="noopener noreferrer">${UI.esc(i.title)}</a>`
            : UI.esc(i.title);
          return `<div class="side-row">
            <div class="t"><span class="dot s-${UI.esc(sev(i))}" style="display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px"></span>${title}</div>
            <div class="m">${UI.esc(i.source || '')} · ${UI.esc(ago(i.age_min))}</div>
          </div>`;
        }).join('')
      : `<div class="side-row m">Нет заголовков за последние ${live.max_age_min} мин.</div>`);
  }

  // ---- fetch status sidebar ----------------------------------------------
  function renderFetchStatus() {
    const node = UI.qs('#side-fetch'), live = state.live, provs = live.providers || [];
    const last = live.last_fetch_utc ? new Date(live.last_fetch_utc).toLocaleString('ru-RU') : 'ещё не запускалось';
    const head = `<div class="side-h">Источники · ${live.providers_ok}/${live.providers_total}</div>`;
    const rows = provs.length
      ? provs.map(p => {
          const isKeyErr = !p.ok && (p.error || '').toLowerCase().includes('ключ не задан');
          const errHint = isKeyErr
            ? `<div class="api-key-hint">Бесплатный ключ (25 запр./день):<br>
               <a href="https://www.alphavantage.co/support/#api-key" target="_blank" rel="noopener noreferrer">alphavantage.co → Free API Key</a><br>
               Установить: <code>NTA_ALPHAVANTAGE_API_KEY=ваш_ключ</code></div>`
            : '';
          return `<div class="side-row">
            <div class="t"><span class="live-dot ${p.ok ? '' : 'err'}" style="display:inline-block;margin-right:6px"></span>${UI.esc(p.name)}</div>
            <div class="m">${p.ok ? `${p.count} записей · ${UI.esc(p.source_type || 'rss')}` : 'ошибка: ' + UI.esc(p.error || 'нет данных')}</div>
            ${errHint}
          </div>`;
        }).join('')
      : '<div class="side-row m">Не запускалось. Команда: python -m app.market_news</div>';
    node.innerHTML = head + rows + `<div class="side-row m">Обновлено: ${UI.esc(last)}</div>`;
  }

  // ---- alert banner at top -----------------------------------------------
  function renderAlertBanner(now) {
    const banner = UI.qs('#alert-banner');
    if (!banner) return;
    const next = filtered()
      .filter(i => { const ms = new Date(i.event_time_utc) - now; return i.is_confirmed && ms > 0 && ms <= 60 * 60000 && sev(i) === 'high'; })
      .sort((a, b) => a.event_time_utc < b.event_time_utc ? -1 : 1)[0];
    if (!next) { banner.classList.remove('visible'); return; }
    banner.classList.add('visible');
    const ms = new Date(next.event_time_utc) - now;
    const e = eta(ms), p = pt(next.event_time_utc);
    const instrs = (next.affected_instruments || next.instruments || []);
    const why = WHY[next.category] || '';
    UI.qs('#alert-banner-title').textContent = `⛔ ${e.txt} — ${next.title}`;
    UI.qs('#alert-banner-body').innerHTML =
      `${UI.esc(p.day)} ${UI.esc(p.time)} PT · блок −${next.block_before_min}/+${next.block_after_min} мин` +
      (instrs.length ? ` · <b>Инструменты: ${instrs.map(v => UI.esc(v)).join(', ')}</b>` : '') +
      (why ? `<br><em>${UI.esc(why)}</em>` : '');
  }

  // ---- ticker: blackouts + upcoming + news (with fallback) ---------------
  function blackoutAlerts(now) {
    return state.events.filter(e => {
      const t = new Date(e.event_time_utc).getTime();
      return e.is_confirmed && sev(e) === 'high' && now >= t - (e.block_before_min || 0) * 60000 && now <= t + (e.block_after_min || 0) * 60000;
    });
  }
  function renderTicker(now) {
    const wrap  = UI.qs('#news-ticker');
    const track = UI.qs('#news-track');
    const lbl   = UI.qs('#ticker-lbl');
    wrap.hidden = false;

    // Layers of content (priority order)
    const alerts = blackoutAlerts(now);

    const upcomingCrit = state.events.filter(e => {
      const ms = new Date(e.event_time_utc) - now;
      return e.is_confirmed && ms > 0 && ms <= 30 * 60000 && sev(e) === 'high';
    });
    const upcomingWarn = state.events.filter(e => {
      const ms = new Date(e.event_time_utc) - now;
      return ms > 30 * 60000 && ms <= 24 * 3600000 && sev(e) === 'high';
    });
    const recentNews = state.live.items || [];

    const hasCrit = alerts.length > 0 || upcomingCrit.length > 0;
    const hasWarn = !hasCrit && upcomingWarn.length > 0;
    wrap.classList.toggle('alert', hasCrit);
    wrap.classList.toggle('warn', hasWarn);
    lbl.textContent = hasCrit ? '🔴 СТОП' : hasWarn ? '⚠ ВАЖНО' : 'LIVE';

    // Build ticker items
    const alertTk = alerts.map(e =>
      `<span class="tk alert"><span class="dot"></span>⛔ ОТКЛЮЧИТЕ СТРАТЕГИИ: <b>${UI.esc(e.title)}</b> — защитное окно активно</span>`);
    const critTk = upcomingCrit.map(e => {
      const e2 = eta(new Date(e.event_time_utc) - now);
      return `<span class="tk t-crit"><span class="dot" style="background:var(--neg)"></span>🔴 ОЧЕНЬ СРОЧНО — ${UI.esc(e2.txt)}: <b>${UI.esc(e.title)}</b>. Отключите затронутые стратегии</span>`;
    });
    const warnTk = upcomingWarn.map(e => {
      const e2 = eta(new Date(e.event_time_utc) - now);
      const status = e.is_confirmed ? '' : ' · время требует проверки';
      return `<span class="tk t-warn"><span class="dot" style="background:var(--warn)"></span>⚠ ${UI.esc(e2.txt)}: <b>${UI.esc(e.title)}</b>${status}</span>`;
    });
    const newsTk = recentNews.map(i => {
      const prefix = sev(i) === 'high' ? '🔴 ВАЖНАЯ НОВОСТЬ · ' : '';
      return `<span class="tk s-${UI.esc(sev(i))}"><span class="dot"></span>${prefix}<b>${UI.esc(i.source || '')}:</b> ${UI.esc(i.title)} · ${UI.esc(ago(i.age_min))}</span>`;
    });

    let all = [...alertTk, ...critTk, ...warnTk, ...newsTk];

    // Fallback 1: older stored live news (beyond max_age_min)
    if (all.length < 3) {
      const recentIds = new Set((state.live.items || []).map(i => i.id));
      const olderNews = (state.live.all_items || [])
        .filter(i => !recentIds.has(i.id))
        .filter(i => sev(i) === 'high' || sev(i) === 'medium')
        .slice(0, 8)
        .map(i => `<span class="tk s-${UI.esc(sev(i))}"><span class="dot"></span><b>${UI.esc(i.source || '')}:</b> ${UI.esc(i.title)} · ${UI.esc(ago(i.age_min))}</span>`);
      all = [...all, ...olderNews];
    }

    // Fallback 2: upcoming calendar events (next 7 days, any severity)
    if (all.length < 3) {
      const upcoming7 = state.events
        .filter(e => { const ms = new Date(e.event_time_utc) - now; return ms > 0 && ms <= 7 * 24 * 3600000; })
        .sort((a, b) => a.event_time_utc < b.event_time_utc ? -1 : 1)
        .slice(0, 8);
      const upcoming7Tk = upcoming7.map(e => {
        const e2 = eta(new Date(e.event_time_utc) - now);
        return `<span class="tk s-${UI.esc(sev(e))}"><span class="dot"></span>📅 ${UI.esc(e2.txt)}: <b>${UI.esc(e.title)}</b></span>`;
      });
      all = [...all, ...upcoming7Tk];
    }

    if (!all.length) {
      wrap.classList.add('paused');
      track.innerHTML = `<span class="static">${state.live.configured
        ? 'Нет свежих данных. Запустите: python -m app.market_news'
        : 'Лента не настроена (python -m app.market_news).'}</span>`;
      return;
    }
    wrap.classList.remove('paused');
    const body = all.join('');
    track.innerHTML = body + body; // duplicate for seamless marquee
  }

  // ---- orchestration -----------------------------------------------------
  function renderAll() {
    const now = Date.now();
    renderList();
    renderCalendar();
    renderDayPanel();
    renderAlertBanner(now);
    renderStopCard(now);
    renderNext(now);
    renderToday();
    renderLiveSide();
    renderFetchStatus();
    renderTicker(now);
  }

  // ---- load --------------------------------------------------------------
  UI.renderLoading(listView, 'Загрузка событий…');
  try {
    const [cal, live] = await Promise.all([
      API.http.news({ limit: 200 }, { signal: UI.signal() }),
      API.http.newsLive({ max_age_min: 60, limit: 40 }, { signal: UI.signal() }).catch(() => null),
    ]);
    state.events = cal.items || [];
    if (live) state.live = live;
    UI.qs('#news-summary').textContent = cal.configured
      ? `${cal.total || state.events.length} событий · ${state.live.total_recent || 0} свежих новостей`
      : 'источники не настроены';
    populateInstruments();
    if (!cal.configured && !state.events.length) {
      UI.renderEmpty(listView, 'Календарь не сгенерирован. Запустите: python -m app.market_events');
    }
    renderAll();
  } catch (error) {
    if (error.name !== 'AbortError') UI.renderError(listView, error, () => location.reload());
    return;
  }

  // ---- wiring ------------------------------------------------------------
  ['#f-impact', '#f-cat', '#f-inst'].forEach(s => { UI.qs(s).onchange = renderAll; });
  UI.qs('#cal-prev').onclick = () => {
    state.cal.m--;
    if (state.cal.m < 0) { state.cal.m = 11; state.cal.y--; }
    renderCalendar();
  };
  UI.qs('#cal-next').onclick = () => {
    state.cal.m++;
    if (state.cal.m > 11) { state.cal.m = 0; state.cal.y++; }
    renderCalendar();
  };

  // Refresh ETAs and live feed periodically.
  let ticks = 0;
  UI.poll(async () => {
    ticks++;
    if (ticks % 3 === 0) {
      try {
        const live = await API.http.newsLive({ max_age_min: 60, limit: 40 }, { signal: UI.signal() });
        if (live) state.live = live;
      } catch (e) { /* keep last */ }
    }
    const now = Date.now();
    renderTicker(now);
    renderAlertBanner(now);
    renderLiveSide();
    renderList();
    renderDayPanel();
    renderStopCard(now);
    renderNext(now);
  }, 60000);
});
