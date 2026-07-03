/* =====================================================================
   Рабочий стол (desktop) — fully customizable trading workspace.

   A virtual canvas (up to 8K) hosting free-floating chart windows the
   operator adds, arranges, resizes, pins, minimizes/maximizes and saves.
   First open is intentionally empty; every layout is persisted to
   localStorage and restored on the next visit.

   Market data flows through the NTData seam → NinjaTrader (real instrument
   catalog + bars). The architecture is deliberately event-driven so it can
   grow into a full trading surface (orders, signals, strategy overlays,
   user drawings emitting events to other modules).
   ===================================================================== */
UI.ready(async function () {
  const { qs, el, toast } = UI;

  // ---- constants ---------------------------------------------------------
  const STORE_KEY = 'desktop.workspaces.v2';
  const RESOLUTIONS = [
    { id: 'hd', label: 'HD · 1280×720', w: 1280, h: 720 },
    { id: 'fhd', label: 'Full HD · 1920×1080', w: 1920, h: 1080 },
    { id: 'qhd', label: '2K · 2560×1440', w: 2560, h: 1440 },
    { id: 'uwqhd', label: 'UltraWide · 3440×1440', w: 3440, h: 1440 },
    { id: 'uhd', label: '4K · 3840×2160', w: 3840, h: 2160 },
    { id: 'uhd5k', label: '5K · 5120×2880', w: 5120, h: 2880 },
    { id: 'uhd8k', label: '8K · 7680×4320', w: 7680, h: 4320 },
  ];
  const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1D'];
  const INDICATORS = [
    { id: 'vol', label: 'Объём', kind: 'pane' },
    { id: 'ma:9', label: 'MA 9', kind: 'overlay' },
    { id: 'ma:20', label: 'MA 20', kind: 'overlay' },
    { id: 'ema:21', label: 'EMA 21', kind: 'overlay' },
    { id: 'ema:50', label: 'EMA 50', kind: 'overlay' },
    { id: 'macd', label: 'MACD 12·26·9', kind: 'pane' },
    { id: 'rsi', label: 'RSI 14', kind: 'pane' },
  ];
  const CHART_TYPES = [{ id: 'candles', label: 'Свечи' }];
  const MIN_W = 260, MIN_H = 180;
  const ZOOM_MIN = 0.05, ZOOM_MAX = 2;

  // window-control icons (kept local so the desktop owns its chrome)
  const wIcon = (name) => {
    const P = {
      pin: '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6Z"/><path d="M12 14v7"/>',
      min: '<path d="M6 15h12"/>',
      max: '<rect x="5" y="5" width="14" height="14" rx="1.5"/>',
      restore: '<rect x="7" y="7" width="12" height="12" rx="1.5"/><path d="M7 10V6a1 1 0 0 1 1-1h9"/>',
      close: '<path d="M6 6l12 12M18 6L6 18"/>',
      cfg: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
    };
    return `<svg viewBox="0 0 24 24">${P[name] || ''}</svg>`;
  };

  // ---- DOM refs ----------------------------------------------------------
  const dsk = qs('#dsk');
  const viewport = qs('#dsk-viewport');
  const canvasWrap = qs('#dsk-canvas-wrap');
  const canvas = qs('#dsk-canvas');
  const dock = qs('#dsk-dock');
  const resSel = qs('#dsk-res');
  const zoomVal = qs('#dsk-zoom-val');
  const layoutName = qs('#dsk-layout-name');
  const dirtyEl = qs('#dsk-dirty');
  if (!dsk || !canvas) return;

  const emptyEl = el(`<div class="dsk-empty" id="dsk-empty">
    <svg viewBox="0 0 24 24"><path d="M3 4h18v12H3zM3 20h18M9 16v4M15 16v4"/><path d="M7 12l3-3 2 2 5-5"/></svg>
    <h3>Пустой рабочий стол</h3>
    <p>Добавьте графики, разместите их как удобно, растяните и закрепите окна. Все макеты сохраняются и восстанавливаются при следующем открытии.</p>
    <button class="btn primary" id="dsk-empty-add">+ Добавить первый график</button>
  </div>`);
  viewport.appendChild(emptyEl);

  // ---- runtime state -----------------------------------------------------
  let store = loadStore();
  let layout = store.layouts[store.activeId];
  const wins = new Map();     // id → { model, node, chart, chartHost, refresh }
  let zTop = 10;
  let instrumentCache = null;
  let persistTimer = null;

  // ---- persistence -------------------------------------------------------
  function loadStore() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(STORE_KEY) || 'null'); } catch (e) { raw = null; }
    if (raw && raw.layouts && raw.activeId && raw.layouts[raw.activeId]) return migrate(raw);
    // first ever open → single empty workspace
    const id = 'w' + Date.now();
    return {
      activeId: id,
      order: [id],
      layouts: { [id]: newLayout(id, 'Рабочий стол 1') },
    };
  }
  function migrate(raw) {
    Object.values(raw.layouts).forEach(l => {
      if (!l.resolution) l.resolution = { w: 1920, h: 1080 };
      if (typeof l.zoom !== 'number') l.zoom = 1;
      if (!Array.isArray(l.windows)) l.windows = [];
      if (typeof l.seq !== 'number') l.seq = l.windows.length;
      if (!l.scroll) l.scroll = { x: 0, y: 0 };
    });
    if (!Array.isArray(raw.order)) raw.order = Object.keys(raw.layouts);
    return raw;
  }
  function newLayout(id, name) {
    return { id, name, resolution: { w: 1920, h: 1080 }, zoom: 1, scroll: { x: 0, y: 0 }, windows: [], seq: 0 };
  }
  function persistNow() {
    layout.scroll = { x: viewport.scrollLeft, y: viewport.scrollTop };
    try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch (e) { /* storage disabled */ }
    if (dirtyEl) dirtyEl.hidden = true;
  }
  function markDirty() {
    if (dirtyEl) dirtyEl.hidden = false;
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(persistNow, 600);
  }

  // ---- virtual canvas: resolution + zoom --------------------------------
  function applyCanvas() {
    const { w, h } = layout.resolution;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    canvas.style.transform = `scale(${layout.zoom})`;
    canvasWrap.style.width = Math.round(w * layout.zoom) + 'px';
    canvasWrap.style.height = Math.round(h * layout.zoom) + 'px';
    if (zoomVal) zoomVal.textContent = Math.round(layout.zoom * 100) + '%';
  }
  function setZoom(z, anchor) {
    const next = clamp(z, ZOOM_MIN, ZOOM_MAX);
    // keep the anchor point (viewport-relative) stable while zooming
    const a = anchor || { x: viewport.clientWidth / 2, y: viewport.clientHeight / 2 };
    const vx = (viewport.scrollLeft + a.x) / layout.zoom;
    const vy = (viewport.scrollTop + a.y) / layout.zoom;
    layout.zoom = next;
    applyCanvas();
    viewport.scrollLeft = vx * next - a.x;
    viewport.scrollTop = vy * next - a.y;
    markDirty();
  }
  function fitZoom() {
    const { w, h } = layout.resolution;
    const pad = 24;
    const z = Math.min((viewport.clientWidth - pad) / w, (viewport.clientHeight - pad) / h);
    layout.zoom = clamp(z, ZOOM_MIN, ZOOM_MAX);
    applyCanvas();
    viewport.scrollLeft = 0; viewport.scrollTop = 0;
    markDirty();
  }
  function setResolution(id) {
    const r = RESOLUTIONS.find(x => x.id === id) || RESOLUTIONS.find(x => x.w === layout.resolution.w) || RESOLUTIONS[1];
    layout.resolution = { w: r.w, h: r.h };
    // clamp existing windows into the new bounds
    layout.windows.forEach(m => clampModel(m));
    applyCanvas();
    wins.forEach(rec => { placeWindow(rec); if (rec.chart) rec.chart.resize(); });
    markDirty();
  }

  // ---- window model helpers ---------------------------------------------
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function clampModel(m) {
    const { w: Wv, h: Hv } = layout.resolution;
    m.w = clamp(m.w, MIN_W, Wv);
    m.h = clamp(m.h, MIN_H, Hv);
    m.x = clamp(m.x, 0, Math.max(0, Wv - m.w));
    m.y = clamp(m.y, 0, Math.max(0, Hv - m.h));
  }

  // ---- window creation ---------------------------------------------------
  function createWindow(model) {
    const node = el(`<div class="dwin" data-id="${model.id}">
      <div class="dwin-head">
        <div class="dwin-meta">
          <span class="dwin-sym"></span>
          <span class="dwin-tf"></span>
          <span class="dwin-src wait" title="Источник данных: NinjaTrader"><span class="dot"></span><span class="src-tx">NinjaTrader</span></span>
        </div>
        <div class="dwin-ctl">
          <button class="cfg" data-act="config" title="Параметры графика">${wIcon('cfg')}</button>
          <button class="pin" data-act="pin" title="Закрепить">${wIcon('pin')}</button>
          <button class="min" data-act="min" title="Свернуть">${wIcon('min')}</button>
          <button class="max" data-act="max" title="Развернуть">${wIcon('max')}</button>
          <button class="close" data-act="close" title="Закрыть">${wIcon('close')}</button>
        </div>
      </div>
      <div class="dwin-body"><div class="dwin-chart"></div></div>
      ${['e', 'w', 's', 'n', 'se', 'sw', 'ne', 'nw'].map(d => `<div class="dwin-grip" data-dir="${d}"></div>`).join('')}
    </div>`);
    canvas.appendChild(node);

    const chartHost = qs('.dwin-chart', node);
    const chart = window.ChartEngine.create(chartHost, {
      instrument: model.config.instrument,
      timeframe: model.config.timeframe,
      indicators: model.config.indicators,
    });
    // future seam: user drawings / crosshair broadcast to other modules
    chart.on('drawing', (obj) => window.dispatchEvent(new CustomEvent('desktop-chart-drawing', { detail: { winId: model.id, object: obj } })));

    const rec = { model, node, chart, chartHost, srcEl: qs('.dwin-src', node), inFlight: false };
    wins.set(model.id, rec);

    renderWindowMeta(rec);
    placeWindow(rec);
    wireWindow(rec);
    bringToFront(rec, false);
    loadWindowData(rec);
    return rec;
  }

  function renderWindowMeta(rec) {
    const m = rec.model;
    qs('.dwin-sym', rec.node).textContent = m.config.instrument || '—';
    qs('.dwin-tf', rec.node).textContent = m.config.timeframe || '';
    rec.node.querySelector('[data-act="pin"]').classList.toggle('on', !!m.pinned);
    rec.node.classList.toggle('pinned', !!m.pinned);
    rec.node.classList.toggle('minimized', !!m.minimized);
    rec.node.classList.toggle('maximized', !!m.maximized);
    const maxBtn = rec.node.querySelector('[data-act="max"]');
    if (maxBtn) { maxBtn.innerHTML = wIcon(m.maximized ? 'restore' : 'max'); maxBtn.title = m.maximized ? 'Восстановить' : 'Развернуть'; }
    if (rec.chart) rec.chart.setMeta(m.config.instrument, m.config.timeframe);
  }

  function placeWindow(rec) {
    const m = rec.model;
    const n = rec.node;
    if (m.maximized) {
      n.style.left = '0px'; n.style.top = '0px';
      n.style.width = layout.resolution.w + 'px';
      n.style.height = layout.resolution.h + 'px';
    } else {
      n.style.left = m.x + 'px'; n.style.top = m.y + 'px';
      n.style.width = m.w + 'px';
      n.style.height = m.minimized ? 'auto' : m.h + 'px';
    }
    n.style.zIndex = String(m.z || 10);
    if (rec.chart && !m.minimized) rec.chart.resize();
  }

  function bringToFront(rec, dirty) {
    zTop += 1;
    rec.model.z = (rec.model.pinned ? 100000 : 0) + zTop;
    rec.node.style.zIndex = String(rec.model.z);
    wins.forEach(r => r.node.classList.toggle('active', r === rec));
    if (dirty !== false) markDirty();
  }

  // ---- window interactions (drag / resize / controls) -------------------
  function wireWindow(rec) {
    const m = rec.model, node = rec.node;
    const head = qs('.dwin-head', node);

    node.addEventListener('pointerdown', () => bringToFront(rec), true);

    // drag by header
    head.addEventListener('pointerdown', (e) => {
      if (e.target.closest('.dwin-ctl')) return;
      if (m.pinned || m.maximized) return;
      e.preventDefault();
      const startX = e.clientX, startY = e.clientY;
      const ox = m.x, oy = m.y;
      head.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const dx = (ev.clientX - startX) / layout.zoom;
        const dy = (ev.clientY - startY) / layout.zoom;
        m.x = ox + dx; m.y = oy + dy; clampModel(m); placeWindow(rec);
      };
      const up = () => {
        head.removeEventListener('pointermove', move);
        head.removeEventListener('pointerup', up);
        head.removeEventListener('pointercancel', up);
        markDirty();
      };
      head.addEventListener('pointermove', move);
      head.addEventListener('pointerup', up);
      head.addEventListener('pointercancel', up);
    });

    // resize by grips
    node.querySelectorAll('.dwin-grip').forEach(grip => {
      grip.addEventListener('pointerdown', (e) => {
        if (m.pinned || m.maximized) return;
        e.preventDefault(); e.stopPropagation();
        const dir = grip.dataset.dir;
        const startX = e.clientX, startY = e.clientY;
        const o = { x: m.x, y: m.y, w: m.w, h: m.h };
        grip.setPointerCapture(e.pointerId);
        const move = (ev) => {
          const dx = (ev.clientX - startX) / layout.zoom;
          const dy = (ev.clientY - startY) / layout.zoom;
          if (dir.includes('e')) m.w = o.w + dx;
          if (dir.includes('s')) m.h = o.h + dy;
          if (dir.includes('w')) { m.w = o.w - dx; m.x = o.x + dx; }
          if (dir.includes('n')) { m.h = o.h - dy; m.y = o.y + dy; }
          // enforce minimums while keeping the anchored edge fixed
          if (m.w < MIN_W) { if (dir.includes('w')) m.x = o.x + o.w - MIN_W; m.w = MIN_W; }
          if (m.h < MIN_H) { if (dir.includes('n')) m.y = o.y + o.h - MIN_H; m.h = MIN_H; }
          clampModel(m); placeWindow(rec);
        };
        const up = () => {
          grip.removeEventListener('pointermove', move);
          grip.removeEventListener('pointerup', up);
          grip.removeEventListener('pointercancel', up);
          markDirty();
        };
        grip.addEventListener('pointermove', move);
        grip.addEventListener('pointerup', up);
        grip.addEventListener('pointercancel', up);
      });
    });

    // control buttons
    qs('.dwin-ctl', node).addEventListener('click', (e) => {
      const btn = e.target.closest('button'); if (!btn) return;
      e.stopPropagation();
      const act = btn.dataset.act;
      if (act === 'close') closeWindow(rec);
      else if (act === 'pin') togglePin(rec);
      else if (act === 'min') minimizeWindow(rec, true);
      else if (act === 'max') toggleMaximize(rec);
      else if (act === 'config') openChartDialog(rec);
    });

    // double-click header = maximize toggle (familiar desktop behaviour)
    head.addEventListener('dblclick', (e) => { if (e.target.closest('.dwin-ctl')) return; toggleMaximize(rec); });
  }

  function togglePin(rec) {
    rec.model.pinned = !rec.model.pinned;
    if (rec.model.pinned && rec.model.maximized) rec.model.maximized = false;
    renderWindowMeta(rec);
    bringToFront(rec);
    placeWindow(rec);
    toast(rec.model.pinned ? 'Окно закреплено' : 'Окно откреплено');
  }
  function toggleMaximize(rec) {
    const m = rec.model;
    if (m.pinned) return;
    if (m.maximized) { m.maximized = false; }
    else { m.prev = { x: m.x, y: m.y, w: m.w, h: m.h }; m.maximized = true; m.minimized = false; }
    renderWindowMeta(rec); placeWindow(rec); bringToFront(rec);
  }
  function minimizeWindow(rec, on) {
    rec.model.minimized = on;
    if (on) rec.model.maximized = false;
    renderWindowMeta(rec);
    if (on) rec.node.style.display = 'none';
    else { rec.node.style.display = ''; placeWindow(rec); bringToFront(rec); }
    renderDock();
    markDirty();
  }
  function closeWindow(rec) {
    if (rec.chart) rec.chart.destroy();
    if (rec.refreshStop) rec.refreshStop();
    rec.node.remove();
    wins.delete(rec.model.id);
    layout.windows = layout.windows.filter(m => m.id !== rec.model.id);
    renderDock();
    refreshEmpty();
    markDirty();
  }

  function renderDock() {
    dock.innerHTML = '';
    layout.windows.filter(m => m.minimized).forEach(m => {
      const item = el(`<div class="dock-item" data-id="${m.id}"><span class="dot"></span><b>${escAttr(m.config.instrument)}</b><span style="color:var(--tx-2)">${escAttr(m.config.timeframe)}</span></div>`);
      item.addEventListener('click', () => { const rec = wins.get(m.id); if (rec) minimizeWindow(rec, false); });
      dock.appendChild(item);
    });
  }

  function refreshEmpty() { emptyEl.style.display = layout.windows.length ? 'none' : 'flex'; }

  // ---- data seam → NinjaTrader ------------------------------------------
  const NTData = {
    async instruments() {
      if (instrumentCache) return instrumentCache;
      try {
        const res = await window.API.http.instruments({ signal: UI.signal() });
        const roots = (res && res.roots) || [];
        const list = roots.map(r => {
          const fm = r.front_month || {};
          return { root: r.root, symbol: fm.instrument || r.root, label: r.root, contract: fm.instrument || r.root };
        }).filter(x => x.root);
        instrumentCache = list;
        return list;
      } catch (e) { instrumentCache = null; return []; }
    },
    async bars(instrument, timeframe, opts) {
      opts = opts || {};
      try {
        const res = await window.API.http.marketBars({ instrument, timeframe, limit: opts.limit || 1500 }, { signal: opts.signal });
        return {
          bars: Array.isArray(res && res.bars) ? res.bars : [],
          note: (res && res.note) || '',
          source: (res && res.source) || null,
          live: !!(res && res.live),
        };
      } catch (e) {
        return { bars: [], note: (e && e.message) || 'нет соединения', source: null, live: false };
      }
    },
  };

  async function loadWindowData(rec) {
    const m = rec.model;
    if (m.minimized) return;
    if (rec.inFlight) return;
    rec.inFlight = true;
    setSrc(rec, 'wait', 'NinjaTrader · загрузка…');
    const { bars, note, live } = await NTData.bars(m.config.instrument, m.config.timeframe, { signal: UI.signal() });
    rec.inFlight = false;
    if (!wins.has(m.id)) return;
    rec.chart.setData(bars);
    if (bars.length) setSrc(rec, live ? 'live' : 'live', `NinjaTrader · ${bars.length} баров`);
    else setSrc(rec, 'wait', 'Ожидание данных NinjaTrader' + (note ? ' · ' + note : ''));
  }
  function setSrc(rec, state, title) {
    const s = rec.srcEl; if (!s) return;
    s.classList.remove('live', 'wait', 'err');
    s.classList.add(state);
    s.title = title;
  }

  // Light refresh loop — one shared poll refreshes all open (non-min) windows.
  // The seam is ready for a true streaming feed; today it re-pulls NT bars.
  UI.poll(async () => {
    for (const rec of wins.values()) {
      if (rec.model.minimized) continue;
      await loadWindowData(rec);
    }
  }, 8000);

  // ---- add / configure chart dialog -------------------------------------
  async function openChartDialog(existingRec) {
    const editing = !!existingRec;
    const cfg = editing ? Object.assign({}, existingRec.model.config) : {
      instrument: '', timeframe: '5m', indicators: ['vol'], type: 'candles',
    };
    const d = UI.drawer(
      editing ? 'Параметры графика' : 'Новый график',
      `<form class="dchart-form" id="dchart-form">
        <div class="fgrid">
          <label>Инструмент (NinjaTrader)
            <select id="dc-inst"><option value="">Загрузка инструментов…</option></select>
          </label>
          <label>Тип графика
            <div class="type-seg" id="dc-type">${CHART_TYPES.map(t => `<button type="button" data-v="${t.id}" class="${cfg.type === t.id ? 'on' : ''}">${t.label}</button>`).join('')}</div>
          </label>
        </div>
        <label>Таймфрейм
          <div class="tf-seg" id="dc-tf">${TIMEFRAMES.map(t => `<button type="button" data-v="${t}" class="${cfg.timeframe === t ? 'on' : ''}">${t}</button>`).join('')}</div>
        </label>
        <label>Индикаторы
          <div class="ind-grid" id="dc-ind">${INDICATORS.map(ind => `
            <label class="ind-chip ${cfg.indicators.includes(ind.id) ? 'on' : ''}"><input type="checkbox" value="${ind.id}" ${cfg.indicators.includes(ind.id) ? 'checked' : ''}><span>${ind.label}</span></label>`).join('')}</div>
        </label>
        <div class="dchart-hint">Все котировки, инструменты, таймфреймы и активные стратегии поступают из NinjaTrader. График рассчитан на минимальную задержку и дальнейшее расширение (ордера, сигналы, стратегии, рисование объектов).</div>
        <div class="dchart-actions">
          <button type="button" class="btn ghost" data-close-drawer>Отмена</button>
          <button type="submit" class="btn primary" id="dc-submit">${editing ? 'Применить' : 'Добавить график'}</button>
        </div>
      </form>`
    );

    const instSel = qs('#dc-inst', d);
    const list = await NTData.instruments();
    if (!list.length) {
      instSel.innerHTML = '<option value="">Нет инструментов — NinjaTrader офлайн</option>';
    } else {
      instSel.innerHTML = list.map(x => `<option value="${escAttr(x.symbol)}" data-root="${escAttr(x.root)}">${escAttr(x.label)}${x.symbol !== x.root ? ' · ' + escAttr(x.symbol) : ''}</option>`).join('');
      const chosen = cfg.instrument || list[0].symbol;
      instSel.value = chosen;
      if (!instSel.value) instSel.selectedIndex = 0;
      cfg.instrument = instSel.value;
    }

    // segmented pickers
    qs('#dc-tf', d).addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]'); if (!b) return;
      cfg.timeframe = b.dataset.v;
      qs('#dc-tf', d).querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    });
    qs('#dc-type', d).addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]'); if (!b) return;
      cfg.type = b.dataset.v;
      qs('#dc-type', d).querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    });
    qs('#dc-ind', d).addEventListener('change', (e) => {
      const cb = e.target.closest('input[type="checkbox"]'); if (!cb) return;
      cb.closest('.ind-chip').classList.toggle('on', cb.checked);
    });
    instSel.addEventListener('change', () => { cfg.instrument = instSel.value; });

    qs('#dchart-form', d).addEventListener('submit', (e) => {
      e.preventDefault();
      cfg.instrument = instSel.value || (list[0] && list[0].symbol) || '';
      if (!cfg.instrument) { toast('Выберите инструмент'); return; }
      cfg.indicators = Array.from(qs('#dc-ind', d).querySelectorAll('input:checked')).map(x => x.value);
      if (editing) applyChartConfig(existingRec, cfg);
      else addChart(cfg);
      UI.closeDrawer();
    });
  }

  function applyChartConfig(rec, cfg) {
    rec.model.config = Object.assign({}, rec.model.config, cfg);
    renderWindowMeta(rec);
    rec.chart.setIndicators(cfg.indicators);
    loadWindowData(rec);
    markDirty();
  }

  function addChart(cfg) {
    const { w: Wv, h: Hv } = layout.resolution;
    layout.seq = (layout.seq || 0) + 1;
    // cascade placement anchored to the current viewport top-left (virtual coords)
    const baseX = viewport.scrollLeft / layout.zoom;
    const baseY = viewport.scrollTop / layout.zoom;
    const stagger = ((layout.seq - 1) % 6) * 34;
    const model = {
      id: 'c' + Date.now() + '_' + layout.seq,
      x: clamp(baseX + 40 + stagger, 0, Math.max(0, Wv - 720)),
      y: clamp(baseY + 40 + stagger, 0, Math.max(0, Hv - 460)),
      w: Math.min(720, Wv - 40), h: Math.min(460, Hv - 40),
      z: 10, minimized: false, maximized: false, pinned: false,
      config: cfg,
    };
    clampModel(model);
    layout.windows.push(model);
    createWindow(model);
    refreshEmpty();
    renderDock();
    markDirty();
  }

  // ---- layouts menu ------------------------------------------------------
  function openLayoutsMenu(anchor) {
    const items = [];
    store.order.forEach(id => {
      const l = store.layouts[id]; if (!l) return;
      items.push({
        icon: id === store.activeId ? 'check' : 'grid',
        label: l.name + (id === store.activeId ? '' : ` · ${l.windows.length} окон`),
        onClick: () => switchLayout(id),
      });
    });
    items.push({ divider: true });
    items.push({ icon: 'plus', label: 'Новый рабочий стол', onClick: createLayout });
    items.push({ icon: 'edit', label: 'Переименовать', onClick: renameLayout });
    if (store.order.length > 1) items.push({ icon: 'trash', label: 'Удалить этот стол', danger: true, onClick: deleteLayout });
    UI.menu(anchor, items);
  }
  function switchLayout(id) {
    if (id === store.activeId) return;
    persistNow();
    teardownWindows();
    store.activeId = id;
    layout = store.layouts[id];
    mountLayout();
    persistNow();
  }
  function createLayout() {
    const id = 'w' + Date.now();
    const name = 'Рабочий стол ' + (store.order.length + 1);
    store.layouts[id] = newLayout(id, name);
    store.order.push(id);
    switchLayout(id);
    toast('Создан новый рабочий стол');
  }
  function renameLayout() {
    const name = prompt('Название рабочего стола:', layout.name);
    if (name == null) return;
    layout.name = name.trim() || layout.name;
    layoutName.textContent = layout.name;
    persistNow();
  }
  function deleteLayout() {
    if (store.order.length <= 1) return;
    if (!confirm(`Удалить «${layout.name}» со всеми графиками?`)) return;
    const removed = store.activeId;
    store.order = store.order.filter(x => x !== removed);
    delete store.layouts[removed];
    teardownWindows();
    store.activeId = store.order[0];
    layout = store.layouts[store.activeId];
    mountLayout();
    persistNow();
    toast('Рабочий стол удалён');
  }

  function teardownWindows() {
    wins.forEach(rec => { if (rec.chart) rec.chart.destroy(); rec.node.remove(); });
    wins.clear();
  }

  function mountLayout() {
    layoutName.textContent = layout.name;
    resSel.value = (RESOLUTIONS.find(r => r.w === layout.resolution.w && r.h === layout.resolution.h) || {}).id || '';
    applyCanvas();
    canvas.innerHTML = '';
    zTop = 10;
    layout.windows.slice().sort((a, b) => (a.z || 0) - (b.z || 0)).forEach(m => { clampModel(m); createWindow(m); });
    viewport.scrollLeft = (layout.scroll && layout.scroll.x) || 0;
    viewport.scrollTop = (layout.scroll && layout.scroll.y) || 0;
    renderDock();
    refreshEmpty();
  }

  // ---- toolbar wiring ----------------------------------------------------
  resSel.innerHTML = RESOLUTIONS.map(r => `<option value="${r.id}">${r.label}</option>`).join('');
  qs('#dsk-add').addEventListener('click', () => openChartDialog(null));
  qs('#dsk-empty-add').addEventListener('click', () => openChartDialog(null));
  qs('#dsk-layouts').addEventListener('click', (e) => { e.stopPropagation(); openLayoutsMenu(e.currentTarget); });
  qs('#dsk-save').addEventListener('click', () => { persistNow(); toast('Рабочий стол сохранён'); });
  qs('#dsk-clear').addEventListener('click', () => {
    if (!layout.windows.length) return;
    if (!confirm('Убрать все графики с этого рабочего стола?')) return;
    teardownWindows();
    layout.windows = [];
    renderDock(); refreshEmpty(); persistNow();
  });
  resSel.addEventListener('change', () => setResolution(resSel.value));
  qs('#dsk-zoom-in').addEventListener('click', () => setZoom(layout.zoom * 1.2));
  qs('#dsk-zoom-out').addEventListener('click', () => setZoom(layout.zoom / 1.2));
  qs('#dsk-zoom-fit').addEventListener('click', fitZoom);
  zoomVal.addEventListener('click', () => setZoom(1));

  // ctrl+wheel zoom over the viewport (TradingView-style)
  viewport.addEventListener('wheel', (e) => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    const r = viewport.getBoundingClientRect();
    const anchor = { x: e.clientX - r.left, y: e.clientY - r.top };
    setZoom(layout.zoom * (e.deltaY > 0 ? 0.9 : 1.1), anchor);
  }, { passive: false });
  viewport.addEventListener('scroll', () => { if (persistTimer) clearTimeout(persistTimer); persistTimer = setTimeout(persistNow, 800); });

  UI.pageActions(`<button class="btn sm ghost" id="pa-fit">Вместить</button><button class="btn sm primary" id="pa-add">+ График</button>`);
  const paAdd = qs('#pa-add'); if (paAdd) paAdd.addEventListener('click', () => openChartDialog(null));
  const paFit = qs('#pa-fit'); if (paFit) paFit.addEventListener('click', fitZoom);

  UI.onLeave(persistNow);
  window.addEventListener('resize', () => wins.forEach(rec => { if (rec.chart) rec.chart.resize(); }));

  // ---- helpers -----------------------------------------------------------
  function escAttr(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch])); }

  // ---- boot --------------------------------------------------------------
  mountLayout();
});
