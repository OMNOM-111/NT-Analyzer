/* Документы и законы — реальная интеграция (/api/governance/*). CSP-safe. */
UI.ready(async function () {
  let docs = [], active = null, current = null, dirty = false, owner = 'Черевко Дмитро';
  let historyEntries = [];
  let pendingLawHighlight = null;
  let pendingAmendmentNo = null;

  function headingHtml(level, raw, inline) {
    const lawMatch = raw.match(/^(GOV-[A-Z]+-\d+)\s*[—–-]\s*/);
    if (lawMatch) {
      const id = lawMatch[1];
      return `<h${level} id="law-${id}" class="doc-law-anchor">${inline(raw)}</h${level}>`;
    }
    return `<h${level}>${inline(raw)}</h${level}>`;
  }

  // minimal markdown renderer (headings, bold, code, lists, blockquote, hr)
  function md(src) {
    const lines = String(src || '').split('\n'); let html = ''; let inList = false, listType = 'ul';
    const inline = t => UI.esc(t).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
    function closeList() { if (inList) { html += `</${listType}>`; inList = false; } }
    lines.forEach(raw => {
      const l = raw.replace(/\r$/, '');
      if (/^### /.test(l)) { closeList(); html += headingHtml(3, l.slice(4), inline); }
      else if (/^## /.test(l)) { closeList(); html += headingHtml(2, l.slice(3), inline); }
      else if (/^# /.test(l)) { closeList(); html += headingHtml(1, l.slice(2), inline); }
      else if (/^> /.test(l)) { closeList(); html += '<blockquote>' + inline(l.slice(2)) + '</blockquote>'; }
      else if (/^---/.test(l)) { closeList(); html += '<hr>'; }
      else if (/^\s*[-*] /.test(l)) { if (!inList || listType !== 'ul') { closeList(); html += '<ul>'; inList = true; listType = 'ul'; } html += '<li>' + inline(l.replace(/^\s*[-*] /, '')) + '</li>'; }
      else if (/^\s*\d+\. /.test(l)) { if (!inList || listType !== 'ol') { closeList(); html += '<ol>'; inList = true; listType = 'ol'; } html += '<li>' + inline(l.replace(/^\s*\d+\. /, '')) + '</li>'; }
      else if (l.trim() === '') { closeList(); }
      else { closeList(); html += '<p>' + inline(l) + '</p>'; }
    });
    closeList(); return html;
  }

  function fmtTs(iso) { try { return new Date(iso).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso || ''; } }

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

  function renderList(q) {
    q = (q || '').toLowerCase();
    const items = docs.filter(d => !q || (d.title + ' ' + d.label + ' ' + d.category).toLowerCase().includes(q));
    const cats = {}; items.forEach(d => { (cats[d.category] = cats[d.category] || []).push(d); });
    listBox.innerHTML = Object.entries(cats).map(([cat, list]) => `
      <div style="padding:10px 14px 4px"><span class="section-title">${UI.esc(cat)}</span></div>
      ${list.map(d => `<div class="row ${d.id === active ? 'active' : ''}" data-id="${UI.esc(d.id)}"><div class="row-main"><div class="row-title" style="font-size:12.5px">${UI.esc(d.title)}</div><div class="row-sub">${UI.esc(d.label || '')}${d.editable_kind === 'markdown' ? '' : ' · только чтение'}</div></div></div>`).join('')}
    `).join('');
    UI.qsa('#doc-list .row').forEach(el => el.onclick = () => {
      if (!confirmLeaveEdit()) return;
      active = el.dataset.id;
      renderList(UI.qs('#doc-search').value);
      setDocUrl(active, null, null);
      selectDoc(active);
    });
  }

  const viewBox = UI.qs('#doc-view');
  async function selectDoc(id) {
    setEdit(false);
    UI.renderLoading(viewBox, 'Загрузка документа…');
    let doc;
    try { doc = await API.http.governanceDocument(id, { signal: UI.signal() }); }
    catch (e) { if (e.name === 'AbortError') return; UI.renderError(viewBox, e, () => selectDoc(id)); return; }
    current = doc;
    UI.qs('#doc-cat').textContent = doc.title || doc.label || doc.id;
    UI.qs('#doc-meta').textContent = `Владелец: ${doc.owner || owner} · ` + (doc.rel_path || doc.path || '') + (doc.editable_kind === 'markdown' ? '' : ' · только чтение');
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

  async function loadHistory(id) {
    const box = UI.qs('#history');
    UI.qs('#hist-scope').textContent = current ? (current.title || id) : '';
    try {
      const h = await API.http.governanceHistory({ document_id: id, limit: 40 }, { signal: UI.signal() });
      historyEntries = (h && h.entries) || [];
      if (!historyEntries.length) {
        box.innerHTML = '<div class="empty-state" style="padding:14px">Поправок по этому документу ещё нет.</div>';
        return;
      }
      box.innerHTML = historyEntries.map(e => {
        const diffs = (e.changes || []).map(c => renderChangeDiff(c, false)).join('');
        return `<div class="tl-item update clickable" data-amendment-no="${e.amendment_no}" tabindex="0" role="button" aria-label="Открыть поправку №${e.amendment_no}"><div class="tl-dot"></div><div class="tl-body">
          <div class="t">Поправка №${e.amendment_no} · ${UI.esc(e.entity_title || '')}</div>
          <div class="m">${UI.esc(e.actor || '')} · ${fmtTs(e.ts_utc)}</div>
          <div class="m" style="color:var(--tx-2)">${UI.esc(e.reason || '')}</div>${diffs}
          <div class="m amend-open-hint">Нажмите, чтобы открыть</div>
        </div></div>`;
      }).join('');
      wireHistoryClicks();
      UI.qsa('#history .tl-item[data-amendment-no]').forEach(el => {
        el.onkeydown = (ev) => {
          if (ev.key === 'Enter' || ev.key === ' ') {
            ev.preventDefault();
            el.click();
          }
        };
      });
      maybeOpenPendingAmendment();
    } catch (e) { if (e.name !== 'AbortError') box.innerHTML = '<div class="empty-state" style="padding:14px">История недоступна.</div>'; }
  }

  function setEdit(on) {
    UI.qs('#doc-view').hidden = on; UI.qs('#doc-edit').hidden = !on;
    UI.qs('#edit-btn').textContent = on ? 'Просмотр' : 'Редактировать';
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
    const actor = UI.qs('#edit-actor').value.trim();
    const reason = UI.qs('#edit-reason').value.trim();
    if (!reason) { UI.toast('Укажите основание поправки'); UI.qs('#edit-reason').focus(); return; }
    if (!actor) { UI.toast('Укажите подпись (кто вносит правку)'); UI.qs('#edit-actor').focus(); return; }
    if (content === (current.content || '')) { UI.toast('Изменений нет'); return; }
    if (!confirm(`Сохранить поправку в «${current.title || current.id}»?\nПодпись: ${actor}\nОснование: ${reason}`)) return;
    const btn = UI.qs('#save-btn'); btn.disabled = true;
    try {
      const res = await API.http.saveDocument(current.id, { content, actor, reason });
      dirty = false;
      UI.toast(res && res.changed ? 'Поправка сохранена в журнал' : 'Без изменений');
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
  active = (wantedDoc && docs.find(d => d.id === wantedDoc)) ? wantedDoc : (docs[0] && docs[0].id);
  renderList('');
  if (active) await selectDoc(active);
});
