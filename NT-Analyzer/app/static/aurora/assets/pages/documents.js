/* Документы и законы — реальная интеграция (/api/governance/*). CSP-safe. */
UI.ready(async function () {
  let docs = [], active = null, current = null, dirty = false, owner = 'Черевко Дмитро';
  let historyEntries = [];
  let pendingLawHighlight = null;
  let pendingAmendmentNo = null;
  let privileged = false; // owner/admin → видит журнал и dev/owner-разделы
  let currentUserLabel = '';
  const collapsed = new Set(['dev', 'owner']); // внутренние разделы свёрнуты по умолчанию

  // Product-first разделы вкладки. audience: user | dev | owner.
  const SECTIONS = [
    { key: 'about',        title: 'О StratForge AI / Цель',             audience: 'user' },
    { key: 'capabilities', title: 'Что умеет платформа',                audience: 'user' },
    { key: 'principles',   title: 'Основные принципы',                  audience: 'user' },
    { key: 'rules',        title: 'Правила и законы',                   audience: 'user' },
    { key: 'strategies',   title: 'Стратегии и риск',                   audience: 'user' },
    { key: 'ai',           title: 'AI и агенты',                        audience: 'user' },
    { key: 'marketdata',   title: 'Market Data и интеграции',           audience: 'user' },
    { key: 'security',     title: 'Безопасность и конфиденциальность',  audience: 'user' },
    { key: 'legal',        title: 'Юридические документы (проекты)',    audience: 'user' },
    { key: 'dev',          title: 'Для разработчиков и администраторов', audience: 'dev' },
    { key: 'owner',        title: 'Владелец и внутренние записи',       audience: 'owner' },
  ];
  const DOC_META = {
    'charter':            { section: 'about',      title: 'О StratForge AI',                       desc: 'Цель, назначение, текущие возможности и направление.' },
    'project-overview':   { section: 'rules',      title: 'Обзор и рабочие параметры',             desc: 'Краткая сводка и параметры стратегий для разработчиков.' },
    'laws':               { section: 'rules',      title: 'Законы проекта',                        desc: 'Канонические правила проекта.' },
    'local-ai-laws':      { section: 'rules',      title: 'Законы локального ИИ',                  desc: 'Правила для локального ИИ.' },
    'sync-map':           { section: 'rules',      title: 'Карта синхронизации правил',            desc: 'Где проверять после изменения закона.' },
    'risk-profile':       { section: 'strategies', title: 'Профиль риска стратегий',               desc: 'Технический контракт риска и капитала.' },
    'legacy-rules':       { section: 'strategies', title: 'Общие правила разработки стратегий',     desc: 'Методология разработки стратегий.' },
    'legacy-registry':    { section: 'strategies', title: 'Реестр стратегий',                      desc: 'Каталог стратегий проекта.' },
    'legacy-hub-deploy':  { section: 'strategies', title: 'Цикл Research Hub → Deploy',             desc: 'Двухэтапный цикл разработки.' },
    'legacy-family-plan': { section: 'strategies', title: 'Переход стратегий в семьи',             desc: 'План перехода в семьи и новый цикл.' },
    'ai-staff-index':     { section: 'ai',         title: 'Карта агентов',                         desc: 'Кто есть кто в команде агентов.' },
    'ai-staff-vitek':     { section: 'ai',         title: 'Виктор — оркестратор',                  desc: 'Правая рука и единый шлюз общения.' },
    'ai-staff-chief':     { section: 'ai',         title: 'Оркестратор и маршрутизация',           desc: 'Как распределяются задачи между агентами.' },
    'ai-staff-dialogue':  { section: 'ai',         title: 'Контракт диалога',                      desc: 'Публичные правила общения агентов.' },
    'ai-staff-marina':    { section: 'ai',         title: 'Марина — финансы',                      desc: 'Финансовый агент.' },
    'ai-lab-run-controls':{ section: 'ai',         title: 'AI Lab: управление запусками',          desc: 'Контроль исследовательских прогонов.' },
    'ai-lab-quality':     { section: 'ai',         title: 'AI Lab: качество',                      desc: 'Конвейер проверки качества стратегий.' },
    'ai-lab-cloud-agents':{ section: 'ai',         title: 'AI Lab: облачные агенты',               desc: 'Роли, бюджет и лимиты облачных моделей.' },
    'ai-lab-competitive-feedback': { section: 'ai', title: 'AI Lab: обратная связь',               desc: 'Контракт конкурентной обратной связи.' },
    'governance-readme':  { section: 'dev',        title: 'Индекс governance',                     desc: 'Служебный указатель governance-документов.' },
    'roles':              { section: 'dev',        title: 'Роли людей и ИИ',                       desc: 'Карта ответственности.' },
    'registry-policy':    { section: 'dev',        title: 'Политика реестра стратегий',            desc: 'Правила ведения реестра.' },
    'ai-lab-system-coder':{ section: 'dev',        title: 'Локальный AI prompt',                   desc: 'Технический промпт-контракт.' },
    'ai-staff-management':{ section: 'owner',      title: 'Секретарь / Заместитель / Управляющий', desc: 'Внутренние управляющие роли.' },
    'legal-00': { section: 'legal', title: 'Ключевые юридические положения', desc: 'Краткое резюме перед регистрацией.', badge: 'ПРОЕКТ' },
    'legal-01': { section: 'legal', title: 'Пользовательское соглашение (ToS + EULA)', desc: 'Главный договор пользователя.', badge: 'ПРОЕКТ' },
    'legal-02': { section: 'legal', title: 'Политика конфиденциальности', desc: 'Обработка данных.', badge: 'ПРОЕКТ' },
    'legal-03': { section: 'legal', title: 'Раскрытие торговых и авто-рисков', desc: 'Market / software / AI / automation риски.', badge: 'ПРОЕКТ' },
    'legal-04': { section: 'legal', title: 'Сторонние интеграции и market data', desc: 'NinjaTrader, TopstepX, Telegram, Google.', badge: 'ПРОЕКТ' },
    'legal-05': { section: 'legal', title: 'Раскрытие ИИ и обработки данных', desc: 'Что передаётся AI-провайдерам.', badge: 'ПРОЕКТ' },
    'legal-06': { section: 'legal', title: 'Согласие на автоматизацию / live', desc: 'Отдельные согласия и активация.', badge: 'ПРОЕКТ' },
    'legal-07': { section: 'legal', title: 'Электронный акцепт и согласия', desc: 'Clickwrap, версии, отзыв.', badge: 'ПРОЕКТ' },
    'legal-08': { section: 'legal', title: 'Cookies и региональные приложения', desc: 'Cookie/Analytics + California/EU.', badge: 'ПРОЕКТ' },
  };
  function metaFor(doc) {
    if (DOC_META[doc.id]) return DOC_META[doc.id];
    const label = doc.label || doc.title || doc.id;
    if (doc.category === 'legacy') return { section: 'strategies', title: label, desc: '' };
    if (doc.category === 'ai-staff') return { section: 'ai', title: label, desc: '' };
    if (doc.category === 'technical') return { section: /risk/i.test(doc.id) ? 'strategies' : 'ai', title: label, desc: '' };
    return { section: 'dev', title: label, desc: '' };
  }
  const STATIC_DOCS = [
    { id: 'p-capabilities', section: 'capabilities', title: 'Что умеет платформа', desc: 'Текущие возможности со статусами.', content: [
      '# Что умеет StratForge AI', '',
      'Статусы: `AVAILABLE` — доступно · `EXTERNAL BLOCKED` — реализовано, но выключено внешним условием.', '',
      '- **Realtime-графики и market data** — `AVAILABLE`. TopstepX — основной независимый read-only источник history + realtime; графики работают при выключенном NinjaTrader.',
      '- **NinjaTrader Connector** — runtime fallback для графиков и единственный путь исполнения; внешний chart feed никогда не авторизует ордер.',
      '- **Бэктестинг и управление стратегиями** — `AVAILABLE`.',
      '- **AI Strategy Lab и AI-агенты** — `AVAILABLE` (локальный LLM приоритетно, облачный резерв — opt-in с лимитами).',
      '- **Учебная (Practice) торговля** — `AVAILABLE`, на виртуальные средства.',
      '- **Режим Simulation / Live** — `IN DEVELOPMENT — release-gated`. Определяется подключённым аккаунтом NinjaTrader; отправка live-команд сейчас закрыта release-gate на стороне сервера. Внешние/regulatory prerequisites — отдельно.', '',
      'Полная цель и границы — в разделе «О StratForge AI».',
    ].join('\n') },
    { id: 'p-principles', section: 'principles', title: 'Основные принципы', desc: 'Как устроена работа платформы.', content: [
      '# Основные принципы', '',
      '- Сначала правила, потом код и запуск.',
      '- Один закон = один канонический источник.',
      '- Человек утверждает цель, капитал и допуски к paper/live.',
      '- Local-first: данные и секреты — на устройстве (Windows DPAPI).',
      '- NinjaTrader — источник истины по исполнению, сделкам и метрикам.',
      '- Документация — часть Definition of Done: current-документы соответствуют коду.',
    ].join('\n') },
    { id: 'p-marketdata', section: 'marketdata', title: 'Market Data и интеграции', desc: 'Источники данных и подключения.', content: [
      '# Market Data и интеграции', '',
      '**Каноническая схема (history / realtime / failover):**', '',
      '- **TopstepX** — основной независимый источник графиков: credentialed read-only realtime + история (по вашим credentials); ордера не маршрутизируются.',
      '- **Фактический порядок выбора:** TopstepX → свежий NinjaTrader Connector runtime → другой разрешённый credentialed provider → честный OFFLINE/cache.',
      '  - **Databento** — credentialed historical (по вашему ключу; по умолчанию выключен).',
      '  - **Yahoo** — публичный best-effort только для delayed/history display; никогда не live-failover.',
      '- **NinjaTrader** остаётся источником истины по исполнению, сделкам и runtime; его включение не вытесняет исправный TopstepX chart feed.',
      '- Авто-rollover фьючерсного корня; синтетические свечи не создаются; кэш изолируется по пользователю; внешние bars — только display/research, не авторизуют ордера.',
    ].join('\n') },
    { id: 'p-security', section: 'security', title: 'Безопасность и конфиденциальность', desc: 'Как защищены ваши данные.', content: [
      '# Безопасность и конфиденциальность', '',
      '- **Local-first**: большая часть данных — на вашем устройстве.',
      '- Секреты и ключи шифруются средствами **Windows DPAPI**; ключи не возвращаются через API и маскируются в логах.',
      '- **Доверенные устройства** и повышенное подтверждение (**step-up**) для критических действий с NinjaTrader.',
      '- Вход и связывание — Telegram, Google, e-mail.',
      '- Ни одна система не гарантирует абсолютной безопасности.', '',
      'Полные тексты — в разделе «Юридические документы» (Политика конфиденциальности, проект).',
    ].join('\n') },
    { id: 'owner-info', section: 'owner', title: 'Владелец и внутренние записи', desc: 'Только для владельца/разработчика.', content: [
      '# Владелец и внутренние записи', '',
      '- **Владелец проекта:** Черевко Дмитро.',
      '- Журнал редакций и внутренние технические сведения доступны справа; подробности каждой редакции свёрнуты в «Подробнее».',
      '- Эти материалы намеренно скрыты по умолчанию и не показываются обычному пользователю.',
    ].join('\n') },
  ];
  const STATIC_ALL = STATIC_DOCS.slice();
  const staticById = {};
  STATIC_ALL.forEach(s => { staticById[s.id] = s; });

  function headingHtml(level, raw, inline) {
    const lawMatch = raw.match(/^(GOV-[A-Z]+-\d+)\s*[—–-]\s*/);
    if (lawMatch) {
      const id = lawMatch[1];
      return `<h${level} id="law-${id}" class="doc-law-anchor">${inline(raw)}</h${level}>`;
    }
    return `<h${level}>${inline(raw)}</h${level}>`;
  }

  // minimal markdown renderer (headings, bold, code, lists, blockquote, hr, tables)
  function md(src) {
    const lines = String(src || '').split('\n').map(s => s.replace(/\r$/, ''));
    let html = ''; let inList = false, listType = 'ul';
    const inline = t => UI.esc(t).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
    function closeList() { if (inList) { html += `</${listType}>`; inList = false; } }
    const isSep = s => /\|/.test(s) && /^[\s:|-]+$/.test(s) && /-/.test(s);
    const cells = s => s.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(c => c.trim());
    let inComment = false;
    for (let i = 0; i < lines.length; i++) {
      const l = lines[i];
      if (inComment) {
        if (/-->/.test(l)) inComment = false;
        continue;
      }
      if (/^\s*<!--/.test(l)) {
        if (!/-->/.test(l)) inComment = true;
        continue;
      }
      if (/\|/.test(l) && i + 1 < lines.length && isSep(lines[i + 1])) {
        closeList();
        const header = cells(l);
        let j = i + 2; const rows = [];
        while (j < lines.length && /\|/.test(lines[j]) && lines[j].trim() !== '') { rows.push(cells(lines[j])); j++; }
        html += '<table class="doc-table"><thead><tr>' + header.map(h => '<th>' + inline(h) + '</th>').join('') +
          '</tr></thead><tbody>' + rows.map(r => '<tr>' + r.map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>').join('') +
          '</tbody></table>';
        i = j - 1;
        continue;
      }
      if (/^### /.test(l)) { closeList(); html += headingHtml(3, l.slice(4), inline); }
      else if (/^## /.test(l)) { closeList(); html += headingHtml(2, l.slice(3), inline); }
      else if (/^# /.test(l)) { closeList(); html += headingHtml(1, l.slice(2), inline); }
      else if (/^> /.test(l)) { closeList(); html += '<blockquote>' + inline(l.slice(2)) + '</blockquote>'; }
      else if (/^---/.test(l)) { closeList(); html += '<hr>'; }
      else if (/^\s*[-*] /.test(l)) { if (!inList || listType !== 'ul') { closeList(); html += '<ul>'; inList = true; listType = 'ul'; } html += '<li>' + inline(l.replace(/^\s*[-*] /, '')) + '</li>'; }
      else if (/^\s*\d+\. /.test(l)) { if (!inList || listType !== 'ol') { closeList(); html += '<ol>'; inList = true; listType = 'ol'; } html += '<li>' + inline(l.replace(/^\s*\d+\. /, '')) + '</li>'; }
      else if (l.trim() === '') { closeList(); }
      else { closeList(); html += '<p>' + inline(l) + '</p>'; }
    }
    closeList(); return html;
  }

  function fmtTs(iso) { try { return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso || ''; } }

  function lawDocForId(lawId) {
    return String(lawId || '').startsWith('GOV-AI-') ? 'local-ai-laws' : 'laws';
  }

  function parseLawIds(text) {
    const ids = [];
    const seen = new Set();
    const add = (id) => {
      if (!id || seen.has(id)) return;
      seen.add(id);
      ids.push(id);
    };
    const src = String(text || '');
    const re = /(GOV-[A-Z]+-)(\d{3,4})(?:\.\.(\d{3,4}))?/g;
    let m;
    while ((m = re.exec(src)) !== null) {
      const prefix = m[1];
      const width = m[2].length;
      const start = parseInt(m[2], 10);
      const end = m[3] ? parseInt(m[3], 10) : start;
      const lo = Math.min(start, end);
      const hi = Math.max(start, end);
      if (hi - lo + 1 > 8) {
        add(prefix + String(lo).padStart(width, '0'));
        add(prefix + String(hi).padStart(width, '0'));
      } else {
        for (let n = lo; n <= hi; n++) add(prefix + String(n).padStart(width, '0'));
      }
    }
    return ids;
  }

  function resolveAmendmentTarget(entry) {
    if (!entry) return { docId: null, lawIds: [], mode: 'summary' };
    if (entry.entity_type === 'law' && entry.entity_id) {
      return { docId: lawDocForId(entry.entity_id), lawIds: [entry.entity_id], mode: 'law' };
    }
    if (entry.entity_type === 'document' && entry.entity_id) {
      return { docId: entry.entity_id, lawIds: [], mode: 'document' };
    }
    const fromTitle = parseLawIds(entry.entity_title);
    if (fromTitle.length) {
      return { docId: lawDocForId(fromTitle[0]), lawIds: fromTitle, mode: 'law' };
    }
    const fromChanges = parseLawIds((entry.changes || []).map(c => `${c.before_text || ''} ${c.after_text || ''}`).join(' '));
    if (fromChanges.length) {
      return { docId: lawDocForId(fromChanges[0]), lawIds: fromChanges, mode: 'law' };
    }
    const docIds = (entry.document_ids || []).filter(id => id !== 'project-overview');
    const docId = docIds.find(id => docs.some(d => d.id === id)) || docIds[0] || entry.entity_id || null;
    return { docId, lawIds: [], mode: 'summary' };
  }

  function docTitle(docId) {
    const row = docs.find(d => d.id === docId);
    return row ? (row.title || row.label || docId) : docId;
  }

  function renderChangeDiff(change, expanded) {
    if (!change) return '';
    const diff = Array.isArray(change.diff) ? change.diff : [];
    if (diff.length) {
      const shown = expanded ? diff : diff.slice(0, 10);
      const rows = shown.map(r => {
        const op = r.op === 'add' ? 'add' : (r.op === 'del' ? 'del' : 'ctx');
        const sign = op === 'add' ? '+ ' : (op === 'del' ? '\u2212 ' : '\u00A0\u00A0');
        return `<span class="dl ${op}">${sign}${UI.esc(r.text || '')}</span>`;
      }).join('');
      const more = (!expanded && diff.length > 10)
        ? `<span class="dl ctx">… ещё ${diff.length - 10} строк(и) — откройте редакцию</span>` : '';
      return `<div class="rev-diff">${rows}${more}</div>`;
    }
    const label = UI.esc(change.label || change.field || 'Изменение');
    if (change.before_text || change.after_text) {
      if (expanded) {
        return `<div class="amend-change-row"><div class="amend-change-label">${label}</div><div class="amend-diff-wide"><div class="amend-diff-col"><div class="amend-diff-head">Было</div><pre class="amend-diff-pre old">${UI.esc(change.before_text || '—')}</pre></div><div class="amend-diff-col"><div class="amend-diff-head">Стало</div><pre class="amend-diff-pre new">${UI.esc(change.after_text || '—')}</pre></div></div></div>`;
      }
      return `<div class="diff"><span class="old">${UI.esc(change.before_text || '—')}</span> → <span class="new">${UI.esc(change.after_text || '—')}</span></div>`;
    }
    if (change.before_hash || change.after_hash) {
      return `<div class="diff"><span class="old mono">${UI.esc((change.before_hash || '—').slice(0, 10))}</span> → <span class="new mono">${UI.esc((change.after_hash || '—').slice(0, 10))}</span></div>`;
    }
    return '';
  }

  function renderChangesDetail(changes) {
    const items = Array.isArray(changes) ? changes : [];
    if (!items.length) return '<div class="muted" style="font-size:12px">Детализированных полей нет.</div>';
    return items.map(c => renderChangeDiff(c, true)).join('');
  }

  function setDocUrl(docId, lawId, amendmentNo) {
    const p = new URLSearchParams();
    if (docId) p.set('doc', docId);
    if (lawId) p.set('law', lawId);
    if (amendmentNo != null) p.set('amendment', String(amendmentNo));
    const qs = p.toString();
    history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
  }

  function highlightLaws(lawIds) {
    const ids = (lawIds || []).filter(Boolean);
    UI.qsa('.doc-law-highlight').forEach(el => el.classList.remove('doc-law-highlight'));
    if (!ids.length) return;
    ids.forEach(id => {
      const el = UI.qs(`#law-${CSS.escape(id)}`);
      if (el) el.classList.add('doc-law-highlight');
    });
    const first = UI.qs(`#law-${CSS.escape(ids[0])}`);
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => {
      UI.qsa('.doc-law-highlight').forEach(el => el.classList.remove('doc-law-highlight'));
    }, 4000);
  }

  function openAmendmentDrawer(entry) {
    if (!entry) return;
    const target = resolveAmendmentTarget(entry);
    const title = UI.esc(entry.entity_title || entry.entity_id || 'Изменение');
    let actions = '';
    if (target.docId) {
      let label = `Открыть в «${docTitle(target.docId)}»`;
      if (target.lawIds.length) label = `Открыть ${target.lawIds.join(', ')} в «${docTitle(target.docId)}»`;
      actions = `<div class="flex gap-sm" style="margin-top:16px"><button class="btn primary" id="amend-open-doc">${UI.esc(label)}</button><button class="btn ghost" data-close-drawer>Закрыть</button></div>`;
    } else {
      actions = `<div class="flex gap-sm" style="margin-top:16px"><button class="btn ghost" data-close-drawer>Закрыть</button></div>`;
    }
    const body = `
      <div class="amend-drawer-meta">
        <div class="t">${title}</div>
        <div class="m">${UI.esc(entry.actor || '')} · ${UI.esc(fmtTs(entry.ts_utc))}</div>
      </div>
      ${entry.reason ? `<div class="amend-drawer-reason"><div class="amend-change-label">Основание</div><p>${UI.esc(entry.reason)}</p></div>` : ''}
      <div class="amend-drawer-changes"><div class="amend-change-label">Изменения</div>${renderChangesDetail(entry.changes)}</div>
      ${actions}`;
    UI.drawer(`<h3>Поправка №${entry.amendment_no}</h3>`, body);
    const openBtn = UI.qs('#amend-open-doc');
    if (openBtn) {
      openBtn.onclick = () => {
        UI.closeDrawer();
        openAmendmentInDocument(entry, target);
      };
    }
    setDocUrl(active, target.lawIds[0] || null, entry.amendment_no);
  }

  async function openAmendmentInDocument(entry, target) {
    if (!target || !target.docId) {
      UI.toast('Для этой поправки не удалось определить документ');
      return;
    }
    if (!confirmLeaveEdit()) return;
    pendingLawHighlight = target.lawIds.length ? target.lawIds.slice() : null;
    setDocUrl(target.docId, target.lawIds[0] || null, entry.amendment_no);
    if (active !== target.docId) {
      active = target.docId;
      renderList(UI.qs('#doc-search').value);
      await selectDoc(target.docId);
      return;
    }
    if (pendingLawHighlight?.length) {
      highlightLaws(pendingLawHighlight);
      pendingLawHighlight = null;
    }
  }

  function wireHistoryClicks() {
    UI.qsa('#history .tl-item[data-amendment-no]').forEach(el => {
      el.onclick = () => {
        const no = parseInt(el.dataset.amendmentNo, 10);
        const entry = historyEntries.find(e => e.amendment_no === no);
        if (entry) openAmendmentDrawer(entry);
      };
    });
  }

  function maybeOpenPendingAmendment() {
    if (pendingAmendmentNo == null) return;
    const entry = historyEntries.find(e => e.amendment_no === pendingAmendmentNo);
    pendingAmendmentNo = null;
    if (entry) openAmendmentDrawer(entry);
  }

  const listBox = UI.qs('#doc-list');
  UI.renderLoading(listBox, 'Загрузка документов…');
  let summary;
  try {
    const [list, defaults] = await Promise.all([
      API.http.governanceDocuments({ signal: UI.signal() }),
      API.http.governanceRuntimeDefaults({ signal: UI.signal() }),
    ]);
    summary = { owner: list.owner, documents: list.documents || [], runtime_defaults: defaults || {} };
  }
  catch (e) { if (e.name === 'AbortError') return; UI.renderError(listBox, e, () => location.reload()); return; }
  docs = summary.documents || [];
  owner = summary.owner || (docs[0] && docs[0].owner) || owner;
  UI.qs('#project-owner').textContent = owner;
  renderRuntimeDefaults(summary.runtime_defaults || {});
  try {
    const me = await API.http.authMe({ signal: UI.signal() });
    const caps = (me && me.admin_capabilities) || {};
    privileged = !!(me && (me.is_owner || caps['docs.manage_global'] || caps['docs.manage_workspace']));
    const u = (me && me.user) || {};
    currentUserLabel = [u.first_name, u.last_name].filter(Boolean).join(' ').trim() || u.username || (me && me.is_owner ? owner : (me && me.role)) || 'текущий пользователь';
  } catch (e) { privileged = false; }
  const ownerBanner = UI.qs('#owner-banner'); if (ownerBanner) ownerBanner.hidden = true;
  const histPanel = UI.qs('#hist-panel'); if (histPanel) histPanel.hidden = !privileged;
  const grid = UI.qs('.docs-grid'); if (grid) grid.style.gridTemplateColumns = privileged ? '280px minmax(0,1fr) 300px' : '280px minmax(0,1fr)';
  const editBtnEl = UI.qs('#edit-btn'); if (editBtnEl) editBtnEl.hidden = !privileged;
  const journalToggle = UI.qs('#journal-toggle');
  if (journalToggle) {
    journalToggle.hidden = !privileged;
    journalToggle.textContent = privileged ? 'Скрыть журнал' : 'Журнал редакций';
    journalToggle.onclick = () => {
      const hp = UI.qs('#hist-panel'); if (!hp) return;
      hp.hidden = !hp.hidden;
      const g = UI.qs('.docs-grid'); if (g) g.style.gridTemplateColumns = hp.hidden ? '280px minmax(0,1fr)' : '280px minmax(0,1fr) 300px';
      journalToggle.textContent = hp.hidden ? 'Журнал и параметры' : 'Скрыть журнал';
    };
  }

  function renderRuntimeDefaults(rd) {
    const fmt = (v) => typeof v === 'number' ? v.toLocaleString('ru-RU', { maximumFractionDigits: 2 }) : String(v);
    const rows = [
      ['Стартовый капитал', '$' + fmt(rd.starting_capital)],
      ['Макс. просадка', rd.max_drawdown_pct != null ? (rd.max_drawdown_pct * 100).toFixed(0) + '%' : '—'],
      ['Комиссия (round-turn)', '$' + fmt(rd.round_turn_commission)],
      ['Проскальзывание', (rd.slippage_ticks != null ? rd.slippage_ticks : '—') + ' тик'],
      ['Заполнение ордера', rd.order_fill_resolution || '—'],
      ['Только интрадей', rd.intraday_only ? 'да' : 'нет'],
      ['Окно сессии AI Lab', rd.ai_lab_session_window_pt || '—'],
    ];
    UI.qs('#runtime-defaults').innerHTML = rows.map(r => `<div class="flex between"><span class="muted" style="font-size:12px">${r[0]}</span><strong class="mono" style="font-size:12px">${UI.esc(r[1])}</strong></div>`).join('');
  }

  function itemsForRender() {
    const mapped = docs.map(d => {
      const m = metaFor(d);
      return { id: d.id, section: m.section, title: m.title || d.title || d.label, desc: m.desc || d.label || '', badge: m.badge || (d.draft ? 'ПРОЕКТ' : ''), editable: d.editable_kind === 'markdown', isStatic: false };
    });
    const statics = STATIC_ALL.map(s => ({ id: s.id, section: s.section, title: s.title, desc: s.desc || '', badge: s.badge || '', editable: false, isStatic: true }));
    let all = mapped.concat(statics);
    if (!privileged) all = all.filter(it => {
      const sec = SECTIONS.find(x => x.key === it.section);
      return !sec || sec.audience === 'user';
    });
    return all;
  }

  function renderList(q) {
    q = (q || '').toLowerCase();
    const rowHtml = it => `<div class="row ${it.id === active ? 'active' : ''}" data-id="${UI.esc(it.id)}"><div class="row-main"><div class="row-title" style="font-size:12.5px">${UI.esc(it.title)}${it.badge ? ` <span class="badge demo" style="font-size:9px">${UI.esc(it.badge)}</span>` : ''}</div><div class="row-sub">${UI.esc(it.desc || '')}${(!it.editable && !it.isStatic) ? ' · только чтение' : ''}</div></div></div>`;
    const all = itemsForRender().filter(it => !q || (it.title + ' ' + it.desc + ' ' + it.section).toLowerCase().includes(q));
    const bySec = {}; all.forEach(it => { (bySec[it.section] = bySec[it.section] || []).push(it); });
    const order = SECTIONS.filter(s => bySec[s.key] && bySec[s.key].length);
    listBox.innerHTML = order.map(sec => {
      const internal = sec.audience !== 'user';
      const isCollapsed = internal && collapsed.has(sec.key) && !q;
      const head = internal
        ? `<div class="docs-sec-head docs-sec-toggle" data-sec="${UI.esc(sec.key)}" style="padding:12px 14px 4px; cursor:pointer"><span class="section-title">${isCollapsed ? '▸' : '▾'} ${UI.esc(sec.title)}</span></div>`
        : `<div class="docs-sec-head" style="padding:12px 14px 4px"><span class="section-title">${UI.esc(sec.title)}</span></div>`;
      return head + (isCollapsed ? '' : bySec[sec.key].map(rowHtml).join(''));
    }).join('');
    UI.qsa('#doc-list .docs-sec-toggle').forEach(el => el.onclick = () => {
      const k = el.dataset.sec;
      if (collapsed.has(k)) collapsed.delete(k); else collapsed.add(k);
      renderList(UI.qs('#doc-search').value);
    });
    UI.qsa('#doc-list .row').forEach(el => el.onclick = () => {
      if (!confirmLeaveEdit()) return;
      active = el.dataset.id;
      renderList(UI.qs('#doc-search').value);
      setDocUrl(active, null, null);
      selectDoc(active);
    });
  }

  const viewBox = UI.qs('#doc-view');

  function renderDocInfo(doc) {
    const box = UI.qs('#doc-info');
    const body = UI.qs('#doc-info-body');
    if (!box || !body) return;
    if (!doc || !privileged) { box.hidden = true; box.open = false; body.innerHTML = ''; return; }
    const editable = doc.editable_kind === 'markdown';
    const kind = editable ? 'редактируется вручную' : (doc.editable_kind === 'laws' ? 'генерируется из реестра законов' : 'генерируется автоматически');
    const rows = [
      ['Владелец', UI.esc(doc.owner || owner || '—')],
      ['Файл', `<code>${UI.esc(doc.rel_path || doc.path || '—')}</code>`],
      ['Тип', UI.esc(kind)],
      ['Статус', doc.draft ? 'проект (DRAFT)' : 'действует'],
    ];
    body.innerHTML = rows.map(([k, v]) => `<div class="kv"><b>${k}</b><span>${v}</span></div>`).join('');
    box.hidden = false;
  }

  async function selectDoc(id) {
    setEdit(false);
    const st = staticById[id];
    if (st) {
      current = null;
      UI.qs('#doc-cat').textContent = st.title;
      UI.qs('#doc-meta').textContent = st.badge ? 'Проект документа' : 'Раздел платформы';
      renderDocInfo(null);
      viewBox.innerHTML = md(st.content);
      const editBtn = UI.qs('#edit-btn'); editBtn.disabled = true; editBtn.title = 'Информационный раздел'; editBtn.textContent = 'Редактировать';
      UI.qs('#hist-scope').textContent = st.title;
      const hb = UI.qs('#history'); if (hb) hb.innerHTML = '<div class="empty-state" style="padding:14px">Для этого раздела журнал не ведётся.</div>';
      return;
    }
    UI.renderLoading(viewBox, 'Загрузка документа…');
    let doc;
    try { doc = await API.http.governanceDocument(id, { signal: UI.signal() }); }
    catch (e) { if (e.name === 'AbortError') return; UI.renderError(viewBox, e, () => selectDoc(id)); return; }
    current = doc;
    UI.qs('#doc-cat').textContent = doc.title || doc.label || doc.id;
    UI.qs('#doc-meta').textContent = doc.draft ? 'Проект документа' : (doc.editable_kind === 'markdown' ? '' : 'только чтение');
    renderDocInfo(doc);
    viewBox.innerHTML = md(doc.content);
    if (pendingLawHighlight?.length) {
      highlightLaws(pendingLawHighlight);
      pendingLawHighlight = null;
    }
    UI.qs('#edit-area').value = doc.content || '';
    const editable = doc.editable_kind === 'markdown';
    const editBtn = UI.qs('#edit-btn');
    editBtn.disabled = !editable;
    editBtn.title = editable ? '' : 'Этот документ генерируется автоматически и не редактируется вручную';
    editBtn.textContent = 'Редактировать';
    await loadHistory(id);
  }

  function compactText(value, limit) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    return text.length <= limit ? text : text.slice(0, Math.max(0, limit - 1)).trimEnd() + '…';
  }

  function renderCompactChange(change) {
    if (!change) return '';
    const before = compactText(change.before_text || '—', 92);
    const after = compactText(change.after_text || '—', 92);
    return `<div class="rev-summary"><div><span class="rev-summary-label">Было:</span> <del>${UI.esc(before)}</del></div><div><span class="rev-summary-label">Стало:</span> <ins>${UI.esc(after)}</ins></div></div>`;
  }

  function renderRevision(r) {
    const initiator = r.initiator ? ` <span class="rev-init">· по запросу ${UI.esc(r.initiator)}</span>` : '';
    const ts = r.ts_utc ? fmtTs(r.ts_utc) : 'дата не зафиксирована';
    const mark = r.author_kind === 'ai' ? '⚙︎ ' : '';
    const reason = UI.esc(r.reason || (r.kind === 'created' ? 'Документ создан.' : 'Основание не указано.'));
    const changes = Array.isArray(r.changes) ? r.changes : [];
    const compact = r.kind === 'created'
      ? '<div class="rev-created">Документ создан</div>'
      : changes.slice(0, 2).map(renderCompactChange).join('');
    const technicalRows = [
      r.version_id && r.version_id !== 'created' ? `<div><b>Версия:</b> <code>${UI.esc(r.version_id)}</code></div>` : '',
      r.path ? `<div><b>Файл:</b> <code>${UI.esc(r.path)}</code></div>` : '',
      r.amendment_no ? `<div><b>Запись журнала:</b> №${UI.esc(r.amendment_no)}</div>` : '',
    ].filter(Boolean).join('');
    const full = changes.map(c => renderChangeDiff(c, true)).join('');
    const details = (technicalRows || full)
      ? `<details class="rev-details"><summary class="rev-diff-toggle">Подробнее</summary><div class="rev-tech">${technicalRows}</div>${full}</details>` : '';
    const heading = r.kind === 'created' ? `Редакция №${r.revision_no} — документ создан` : `Редакция №${r.revision_no}`;
    return `<div class="rev-item">
      <div class="rev-head"><span class="rev-no">${heading}</span><span class="rev-date">${UI.esc(ts)}</span></div>
      <div class="rev-meta"><b>Автор:</b> ${mark}${UI.esc(r.author || '—')}${initiator}</div>
      <div class="rev-reason"><b>Основание:</b> ${reason}</div>
      ${compact}${details}
    </div>`;
  }

  async function loadHistory(id) {
    const box = UI.qs('#history');
    UI.qs('#hist-scope').textContent = current ? (current.title || id) : '';
    if (!privileged) { box.innerHTML = ''; return; }
    try {
      const data = await API.http.governanceRevisions({ document_id: id }, { signal: UI.signal() });
      const revs = (data && data.revisions) || [];
      if (!revs.length) {
        box.innerHTML = '<div class="empty-state" style="padding:14px">Журнал недоступен для вашей роли.</div>';
        return;
      }
      const ordered = revs.slice().reverse();
      box.innerHTML = ordered.map(renderRevision).join('');
    } catch (e) { if (e.name !== 'AbortError') box.innerHTML = '<div class="empty-state" style="padding:14px">Журнал недоступен.</div>'; }
  }

  function setEdit(on) {
    UI.qs('#doc-view').hidden = on; UI.qs('#doc-edit').hidden = !on;
    UI.qs('#edit-btn').textContent = on ? 'Просмотр' : 'Редактировать';
    const hint = UI.qs('#edit-author-hint');
    if (hint) hint.textContent = on ? `Автор правки будет записан автоматически: ${currentUserLabel || 'текущий пользователь'}.` : '';
    if (!on) { dirty = false; UI.qs('#edit-status').textContent = ''; }
  }
  function confirmLeaveEdit() {
    if (!dirty) return true;
    return confirm('Есть несохранённые изменения. Покинуть без сохранения?');
  }

  UI.qs('#edit-btn').onclick = () => {
    if (UI.qs('#edit-btn').disabled) return;
    const editing = !UI.qs('#doc-edit').hidden;
    if (editing) { if (!confirmLeaveEdit()) return; setEdit(false); }
    else setEdit(true);
  };
  UI.qs('#cancel-btn').onclick = () => { if (confirmLeaveEdit()) { UI.qs('#edit-area').value = (current && current.content) || ''; setEdit(false); } };
  UI.qs('#edit-area').addEventListener('input', () => { dirty = ((current && current.content) || '') !== UI.qs('#edit-area').value; UI.qs('#edit-status').textContent = dirty ? '● несохранённые изменения' : ''; });

  UI.qs('#save-btn').onclick = async () => {
    if (!current || current.editable_kind !== 'markdown') { UI.toast('Документ не редактируется'); return; }
    const content = UI.qs('#edit-area').value;
    const reason = UI.qs('#edit-reason').value.trim();
    if (!reason) { UI.toast('Укажите основание правки'); UI.qs('#edit-reason').focus(); return; }
    if (content === (current.content || '')) { UI.toast('Изменений нет'); return; }
    if (!confirm(`Сохранить правку в «${current.title || current.id}»?\nАвтор (автоматически): ${currentUserLabel || 'текущий пользователь'}\nОснование: ${reason}`)) return;
    const btn = UI.qs('#save-btn'); btn.disabled = true;
    try {
      const res = await API.http.saveDocument(current.id, { content, reason });
      dirty = false;
      UI.toast(res && res.changed ? 'Правка сохранена в журнал редакций' : 'Без изменений');
      setEdit(false);
      await selectDoc(current.id);
    } catch (e) { UI.reportError(e); }
    finally { btn.disabled = false; }
  };

  UI.qs('#doc-search').oninput = e => renderList(e.target.value);
  window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

  const params = new URLSearchParams(location.search);
  const wantedDoc = params.get('doc');
  const wantedLaw = params.get('law');
  const wantedAmendment = params.get('amendment');
  if (wantedLaw) pendingLawHighlight = [wantedLaw];
  if (wantedAmendment) {
    const no = parseInt(wantedAmendment, 10);
    if (!Number.isNaN(no)) pendingAmendmentNo = no;
  }
  const hasCharter = docs.some(d => d.id === 'charter');
  active = (wantedDoc && (docs.some(d => d.id === wantedDoc) || staticById[wantedDoc])) ? wantedDoc : (hasCharter ? 'charter' : (docs[0] && docs[0].id));
  renderList('');
  if (active) await selectDoc(active);
});
