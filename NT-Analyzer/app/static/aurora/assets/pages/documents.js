/* Документы и законы — реальная интеграция (/api/governance/*). CSP-safe. */
UI.ready(async function () {
  let docs = [], active = null, current = null, dirty = false;

  // minimal markdown renderer (headings, bold, code, lists, blockquote, hr)
  function md(src) {
    const lines = String(src || '').split('\n'); let html = ''; let inList = false, listType = 'ul';
    const inline = t => UI.esc(t).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
    function closeList() { if (inList) { html += `</${listType}>`; inList = false; } }
    lines.forEach(raw => {
      const l = raw.replace(/\r$/, '');
      if (/^### /.test(l)) { closeList(); html += '<h3>' + inline(l.slice(4)) + '</h3>'; }
      else if (/^## /.test(l)) { closeList(); html += '<h2>' + inline(l.slice(3)) + '</h2>'; }
      else if (/^# /.test(l)) { closeList(); html += '<h1>' + inline(l.slice(2)) + '</h1>'; }
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

  const listBox = UI.qs('#doc-list');
  UI.renderLoading(listBox, 'Загрузка документов…');
  let summary;
  try {
    const [list, defaults] = await Promise.all([
      API.http.governanceDocuments({ signal: UI.signal() }),
      API.http.governanceRuntimeDefaults({ signal: UI.signal() }),
    ]);
    summary = { documents: list.documents || [], runtime_defaults: defaults || {} };
  }
  catch (e) { if (e.name === 'AbortError') return; UI.renderError(listBox, e, () => location.reload()); return; }
  docs = summary.documents || [];
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
      active = el.dataset.id; renderList(UI.qs('#doc-search').value); selectDoc(active);
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
    UI.qs('#doc-meta').textContent = (doc.rel_path || doc.path || '') + (doc.editable_kind === 'markdown' ? '' : ' · только чтение');
    viewBox.innerHTML = md(doc.content);
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
      const entries = (h && h.entries) || [];
      if (!entries.length) { box.innerHTML = '<div class="empty-state" style="padding:14px">Поправок по этому документу ещё нет.</div>'; return; }
      box.innerHTML = entries.map(e => {
        const diffs = (e.changes || []).map(c => {
          if (c.before_text || c.after_text) return `<div class="diff"><span class="old">${UI.esc(c.before_text || '—')}</span> → <span class="new">${UI.esc(c.after_text || '—')}</span></div>`;
          if (c.before_hash || c.after_hash) return `<div class="diff"><span class="old mono">${UI.esc((c.before_hash || '—').slice(0, 10))}</span> → <span class="new mono">${UI.esc((c.after_hash || '—').slice(0, 10))}</span></div>`;
          return '';
        }).join('');
        return `<div class="tl-item update"><div class="tl-dot"></div><div class="tl-body">
          <div class="t">Поправка №${e.amendment_no} · ${UI.esc(e.entity_title || '')}</div>
          <div class="m">${UI.esc(e.actor || '')} · ${fmtTs(e.ts_utc)}</div>
          <div class="m" style="color:var(--tx-2)">${UI.esc(e.reason || '')}</div>${diffs}
        </div></div>`;
      }).join('');
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

  // initial selection (honor ?doc= deep link)
  const wanted = new URLSearchParams(location.search).get('doc');
  active = (wanted && docs.find(d => d.id === wanted)) ? wanted : (docs[0] && docs[0].id);
  renderList('');
  if (active) await selectDoc(active);
});
