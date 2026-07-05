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
    { id: 'screen', label: 'Экран · под монитор', w: 0, h: 0 },
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
  const RANGE_PRESETS = [
    { id: '1d', label: '1 день', days: 1 }, { id: '1w', label: '1 нед.', days: 7 },
    { id: '1m', label: '1 мес.', days: 31 }, { id: '3m', label: '3 мес.', days: 93 },
    { id: '6m', label: '6 мес.', days: 186 }, { id: '1y', label: '1 год', days: 366 },
    { id: '2y', label: '2 года', days: 732 }, { id: 'max', label: 'Макс.', days: 0 },
    { id: 'custom', label: 'Диапазон', days: null },
  ];
  const DESKTOP_INSTRUMENTS = [
    ['MBT','Micro Bitcoin','Крипто'],['MET','Micro Ether','Крипто'],
    ['RTY','E-mini Russell 2000','Индексы'],['MES','Micro E-mini S&P 500','Индексы'],['MNQ','Micro E-mini NASDAQ 100','Индексы'],['M2K','Micro E-mini Russell 2000','Индексы'],['MYM','Micro Mini-DOW','Индексы'],
    ['MCL','Micro Crude Oil','Энергетика'],['MNG','Micro Henry Hub Natural Gas','Энергетика'],['RB','RBOB Gasoline','Энергетика'],['HO','Heating Oil','Энергетика'],
    ['MGC','Micro Gold','Металлы'],['SIL','Micro Silver','Металлы'],['MHG','Micro Copper','Металлы'],
    ['6A','Australian $','FX Futures'],['6B','British Pound','FX Futures'],['6C','Canadian $','FX Futures'],['6E','Euro FX','FX Futures'],['6J','Japanese Yen','FX Futures'],['6S','Swiss Franc','FX Futures'],['E7','E-mini Euro FX','FX Futures'],['6M','Mexican Peso','FX Futures'],['6N','New Zealand $','FX Futures'],
    ['HE','Lean Hogs','Livestock'],['LE','Live Cattle','Livestock'],
    ['ZC','Corn','Зерно и соевые'],['ZW','Wheat','Зерно и соевые'],['ZS','Soybeans','Зерно и соевые'],['ZM','Soybean Meal','Зерно и соевые'],['ZL','Soybean Oil','Зерно и соевые'],
    ['ZT','2-Year Note','Облигации'],['ZF','5-Year Note','Облигации'],['ZN','10-Year Note','Облигации'],['TN','10-Year Ultra Note','Облигации'],['ZB','30-Year Bond','Облигации'],['UB','Ultra-Bond','Облигации'],
  ];
  const GRID_COUNTS = [1, 2, 4, 6, 9, 12, 16, 24, 36, 48, 64];
  const MIN_W = 260, MIN_H = 180;
  const ZOOM_MIN = 0.05, ZOOM_MAX = 2;
  const DEFAULT_STYLE = { upColor: '#34d399', downColor: '#ff6b81', upFill: '#34d399',
    downFill: '#ff6b81', background: '#0b1018', bodyWidth: 0.7, wickWidth: 1,
    borderWidth: 1, fillOpacity: 0.85, legendMode: 'compact',
    macd: { fill: true, up: '#34d399', down: '#ff6b81', line: '#4fd1e0', signal: '#fcc55a', opacity: 0.85, area: true, fillToZero: true } };

  // window-control icons (kept local so the desktop owns its chrome)
  const wIcon = (name) => {
    const P = {
      pin: '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6Z"/><path d="M12 14v7"/>',
      min: '<path d="M6 15h12"/>',
      max: '<rect x="5" y="5" width="14" height="14" rx="1.5"/>',
      restore: '<rect x="7" y="7" width="12" height="12" rx="1.5"/><path d="M7 10V6a1 1 0 0 1 1-1h9"/>',
      close: '<path d="M6 6l12 12M18 6L6 18"/>',
      cfg: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>',
      bare: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
      pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"/>',
      sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
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
  let agentCache = null;
  let persistTimer = null;
  let bulkMounting = false;

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
      if (typeof l.screenFit !== 'boolean') l.screenFit = false;
      if (typeof l.grid !== 'number') l.grid = 0;
      if (!Array.isArray(l.windows)) l.windows = [];
      if (typeof l.seq !== 'number') l.seq = l.windows.length;
      if (!l.scroll) l.scroll = { x: 0, y: 0 };
      l.windows.forEach(m => {
        m.config = m.config || {};
        if (!Array.isArray(m.config.indicators)) m.config.indicators = ['vol'];
        m.config.style = Object.assign({}, DEFAULT_STYLE, m.config.style || {});
        m.config.style.macd = Object.assign({}, DEFAULT_STYLE.macd, m.config.style.macd || {});
        if (!m.config.range) m.config.range = { id: '1m', days: 31, from: '', to: '' };
        if (!m.config.root) m.config.root = String(m.config.instrument || '').split(' ')[0];
        if (!Array.isArray(m.drawings)) m.drawings = [];
        if (typeof m.bare !== 'boolean') m.bare = false;
      });
    });
    if (!Array.isArray(raw.order)) raw.order = Object.keys(raw.layouts);
    return raw;
  }
  function newLayout(id, name) {
    return { id, name, resolution: { w: 1920, h: 1080 }, zoom: 1, screenFit: true, grid: 0,
      scroll: { x: 0, y: 0 }, windows: [], seq: 0 };
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
  function viewportSize() {
    return { w: Math.max(480, Math.round(viewport.clientWidth)),
             h: Math.max(320, Math.round(viewport.clientHeight)) };
  }
  function applyCanvas() {
    if (layout.screenFit) {
      const s = viewportSize();
      layout.resolution = { w: s.w, h: s.h };
      layout.zoom = 1;
    }
    const { w, h } = layout.resolution;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    canvas.style.transform = `scale(${layout.zoom})`;
    canvasWrap.style.width = Math.round(w * layout.zoom) + 'px';
    canvasWrap.style.height = Math.round(h * layout.zoom) + 'px';
    if (zoomVal) zoomVal.textContent = layout.screenFit ? 'Экран' : Math.round(layout.zoom * 100) + '%';
  }
  function setZoom(z, anchor) {
    if (layout.screenFit) return; // screen-fit ignores manual zoom
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
    if (layout.screenFit) {
      applyCanvas();
      viewport.scrollLeft = 0; viewport.scrollTop = 0;
      requestAnimationFrame(() => wins.forEach(rec => rec.chart && rec.chart.resize()));
      markDirty();
      return;
    }
    const { w, h } = layout.resolution;
    const pad = 24;
    const z = Math.min((viewport.clientWidth - pad) / w, (viewport.clientHeight - pad) / h);
    layout.zoom = clamp(z, ZOOM_MIN, ZOOM_MAX);
    applyCanvas();
    viewport.scrollLeft = 0; viewport.scrollTop = 0;
    markDirty();
  }
  function setResolution(id) {
    if (id === 'screen') {
      layout.screenFit = true;
      applyCanvas();
      layout.windows.forEach(m => clampModel(m));
      wins.forEach(rec => placeWindow(rec));
      if (layout.grid) retileGrid();
      viewport.scrollLeft = 0; viewport.scrollTop = 0;
      requestAnimationFrame(() => wins.forEach(rec => rec.chart && rec.chart.resize()));
      markDirty();
      return;
    }
    layout.screenFit = false;
    const r = RESOLUTIONS.find(x => x.id === id && x.w) || RESOLUTIONS.find(x => x.w === layout.resolution.w) || RESOLUTIONS[2];
    layout.resolution = { w: r.w, h: r.h };
    // clamp existing windows into the new bounds
    layout.windows.forEach(m => clampModel(m));
    applyCanvas();
    if (layout.grid) retileGrid();
    wins.forEach(rec => placeWindow(rec));
    // A resolution switch changes the whole visual density, like a monitor:
    // HD makes windows larger; 4K/8K fits more, smaller windows on screen.
    fitZoom();
    requestAnimationFrame(() => wins.forEach(rec => rec.chart && rec.chart.resize()));
  }
  // Re-tile the current window set into the active grid, filling the canvas.
  function retileGrid() {
    const count = layout.windows.length;
    if (!count) return;
    const colMap = { 1: 1, 2: 2, 4: 2, 6: 3, 9: 3, 12: 4, 16: 4, 24: 6, 36: 6, 48: 8, 64: 8 };
    const cols = colMap[layout.grid] || colMap[count] || Math.ceil(Math.sqrt(count));
    const rows = Math.ceil(count / cols);
    const gap = Math.max(4, Math.round(layout.resolution.w / 900));
    const cellW = (layout.resolution.w - gap * (cols + 1)) / cols;
    const cellH = (layout.resolution.h - gap * (rows + 1)) / rows;
    layout.windows.forEach((model, index) => {
      model.x = gap + (index % cols) * (cellW + gap);
      model.y = gap + Math.floor(index / cols) * (cellH + gap);
      model.w = cellW; model.h = cellH; model.minimized = false; model.maximized = false;
      const rec = wins.get(model.id);
      if (rec) { renderWindowMeta(rec); placeWindow(rec); }
    });
  }
  // After the viewport changes size (window resize, entering/leaving fullscreen).
  function relayoutViewport() {
    if (layout.screenFit) {
      applyCanvas();
      if (layout.grid) retileGrid(); else layout.windows.forEach(m => clampModel(m));
      wins.forEach(rec => { placeWindow(rec); if (rec.chart) rec.chart.resize(); });
    } else {
      wins.forEach(rec => { if (rec.chart) rec.chart.resize(); });
    }
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
          <button class="bare" data-act="bare" title="График без рамок">${wIcon('bare')}</button>
          <button class="close" data-act="close" title="Закрыть">${wIcon('close')}</button>
        </div>
      </div>
      <div class="dwin-body">
        <div class="dwin-alert"></div>
        <div class="dwin-side" title="Параметры графика">
          <div class="dwin-side-tab" data-side-toggle title="Меню графика"><svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg></div>
          <div class="dwin-side-panel">
            <div class="dsd-inst"><b class="dsd-inst-sym">—</b><button type="button" class="dsd-link" data-side="instrument">изменить</button></div>
            <div class="dsd-cap">Таймфрейм</div>
            <div class="dsd-row dsd-tf"></div>
            <div class="dsd-cap">Индикаторы</div>
            <div class="dsd-inds"></div>
            <div class="dsd-cap">Пропорции</div>
            <div class="dsd-row dsd-aspect">
              <button type="button" data-aspect="auto">Авто</button>
              <button type="button" data-aspect="wide">16:9</button>
              <button type="button" data-aspect="square">1:1</button>
            </div>
            <button type="button" class="btn sm dsd-macd" data-side="macd" hidden>Настроить MACD</button>
            <button type="button" class="btn sm ghost" data-side="params">Все параметры</button>
          </div>
        </div>
        <div class="dwin-tools" title="Инструменты рисования">
          <button type="button" class="dwin-tools-btn" data-tools-toggle title="Инструменты рисования">${wIcon('pen')}</button>
          <div class="dwin-tools-menu">
            <button type="button" data-tool="line"><span class="dt-ic">━</span><span>Горизонтальная линия</span></button>
            <button type="button" data-tool="trendline"><span class="dt-ic">╱</span><span>Трендовая линия (2 точки)</span></button>
            <button type="button" data-tool="point"><span class="dt-ic">●</span><span>Точка</span></button>
            <button type="button" data-tool="arrow_up"><span class="dt-ic">↑</span><span>Стрелка вверх</span></button>
            <button type="button" data-tool="arrow_down"><span class="dt-ic">↓</span><span>Стрелка вниз</span></button>
            <button type="button" data-tool="flag"><span class="dt-ic">⚑</span><span>Флажок</span></button>
            <button type="button" data-tool="target"><span class="dt-ic">◎</span><span>Цель</span></button>
            <button type="button" data-tool="label"><span class="dt-ic">🅣</span><span>Подпись</span></button>
          </div>
        </div>
        <button class="dwin-bare-exit" data-act="bare-exit" title="Вернуть рамку и панель">${wIcon('bare')}</button>
        <div class="dwin-drawing-editor"></div>
        <div class="dwin-chart"></div>
      </div>
      ${['e', 'w', 's', 'n', 'se', 'sw', 'ne', 'nw'].map(d => `<div class="dwin-grip" data-dir="${d}"></div>`).join('')}
    </div>`);
    canvas.appendChild(node);

    const chartHost = qs('.dwin-chart', node);
    const chart = window.ChartEngine.create(chartHost, {
      instrument: model.config.instrument,
      timeframe: model.config.timeframe,
      indicators: model.config.indicators,
      style: Object.assign({}, DEFAULT_STYLE, model.config.style || {}),
      drawings: model.drawings || [],
      paneHeights: model.config.paneHeights || {},
      aspect: model.config.aspect || 'auto',
    });
    chart.on('drawing', (obj) => {
      model.drawings = Array.isArray(model.drawings) ? model.drawings : [];
      if (!model.drawings.some(row => row.id === obj.id)) model.drawings.push(obj);
      markDirty();
      renderDrawingEditor(rec, obj);
      window.dispatchEvent(new CustomEvent('desktop-chart-drawing', { detail: { winId: model.id, object: obj } }));
    });
    chart.on('drawingSelect', obj => renderDrawingEditor(rec, obj));
    chart.on('drawingChange', obj => {
      const stored = (model.drawings || []).find(row => row.id === obj.id);
      if (stored) Object.assign(stored, obj);
      // Persist pane height changes whenever the user interacts with a drawing
      // (same pointer-up cycle that ends pane-resize drag).
      model.config.paneHeights = chart.getPaneHeights();
      markDirty();
      if (obj.alertId) syncDrawingRule(rec, obj, true);
    });

    const rec = { model, node, chart, chartHost, srcEl: qs('.dwin-src', node), inFlight: false };
    wins.set(model.id, rec);

    renderWindowMeta(rec);
    placeWindow(rec);
    wireWindow(rec);
    bringToFront(rec, false);
    if (!bulkMounting) loadWindowData(rec);
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
    rec.node.classList.toggle('bare', !!m.bare);
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
        layout.grid = 0;
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
          layout.grid = 0;
          markDirty();
        };
        grip.addEventListener('pointermove', move);
        grip.addEventListener('pointerup', up);
        grip.addEventListener('pointercancel', up);
      });
    });

    // control buttons
    qsaLocal('.dwin-ctl button', node).forEach(btn => btn.addEventListener('click', (e) => {
      e.preventDefault(); e.stopPropagation();
      const act = btn.dataset.act;
      if (act === 'close') closeWindow(rec);
      else if (act === 'pin') togglePin(rec);
      else if (act === 'min') minimizeWindow(rec, true);
      else if (act === 'max') toggleMaximize(rec);
      else if (act === 'bare') toggleBare(rec, true);
      else if (act === 'config') openChartDialog(rec);
    }));

    const toolsWrap = qs('.dwin-tools', node);
    toolsWrap.addEventListener('pointerdown', e => e.stopPropagation());
    toolsWrap.addEventListener('click', (e) => {
      e.stopPropagation();
      if (e.target.closest('[data-tools-toggle]')) {
        const menu = qs('.dwin-tools-menu', node);
        const open = menu.classList.toggle('open');
        toolsWrap.classList.toggle('open', open);
        return;
      }
      const btn = e.target.closest('button[data-tool]');
      if (btn) { activateDrawingTool(rec, btn.dataset.tool); toolsWrap.classList.remove('open'); }
    });

    // in-chart side menu (instrument / timeframe / indicators / MACD / params)
    const side = qs('.dwin-side', node);
    side.addEventListener('pointerdown', e => e.stopPropagation());
    side.addEventListener('click', (e) => {
      e.stopPropagation();
      if (e.target.closest('[data-side-toggle]')) {
        const open = side.classList.toggle('open');
        if (open) renderSidePanel(rec);
        return;
      }
      const tf = e.target.closest('.dsd-tf button'); if (tf) { setWindowTimeframe(rec, tf.dataset.tf); return; }
      const ind = e.target.closest('.dsd-inds button'); if (ind) { toggleWindowIndicator(rec, ind.dataset.ind); return; }
      const asp = e.target.closest('.dsd-aspect button[data-aspect]');
      if (asp) {
        rec.model.config.aspect = asp.dataset.aspect;
        if (rec.chart && rec.chart.setAspect) rec.chart.setAspect(asp.dataset.aspect);
        renderSidePanel(rec); markDirty(); return;
      }
      const act = e.target.closest('[data-side]'); if (!act) return;
      if (act.dataset.side === 'params' || act.dataset.side === 'instrument') { side.classList.remove('open'); openChartDialog(rec); }
      else if (act.dataset.side === 'macd') { side.classList.remove('open'); openMacdSettings(rec); }
    });
    renderSidePanel(rec);

    const bareExit = qs('.dwin-bare-exit', node);
    bareExit.addEventListener('pointerdown', e => e.stopPropagation());
    bareExit.addEventListener('click', e => { e.stopPropagation(); toggleBare(rec, false); });

    // The drawing editor sits over the chart canvas, so mousedown/pointerdown on any
    // of its children must not bubble to the canvas — otherwise the canvas re-fires
    // drawingSelect and resets the editor before click handlers run.
    const drawingEditor = qs('.dwin-drawing-editor', node);
    drawingEditor.addEventListener('pointerdown', e => e.stopPropagation());

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
    deleteModelAlerts(rec.model);
    if (rec.chart) rec.chart.destroy();
    if (rec.refreshStop) rec.refreshStop();
    rec.node.remove();
    wins.delete(rec.model.id);
    layout.windows = layout.windows.filter(m => m.id !== rec.model.id);
    layout.grid = 0;
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
        const res = await window.API.http.desktopInstruments({ signal: UI.signal() });
        const roots = (res && res.roots) || [];
        const byRoot = new Map(roots.map(r => [r.root, r]));
        const list = DESKTOP_INSTRUMENTS.map(row => {
          const info = { name: row[1], group: row[2] };
          const r = byRoot.get(row[0]);
          if (!r) return { root: row[0], symbol: '', label: row[0], contract: '', name: info.name,
            group: info.group, expiry: '', available: false };
          const fm = r.front_month || {};
          return { root: r.root, symbol: fm.instrument || r.root, label: r.root, contract: fm.instrument || r.root,
            name: info.name, group: info.group, expiry: fm.expiry || '', available: !!fm.instrument };
        });
        instrumentCache = list;
        return list;
      } catch (e) { instrumentCache = null; return []; }
    },
    async bars(instrument, timeframe, opts) {
      opts = opts || {};
      try {
        const q = marketRequest(opts.config || { instrument, timeframe }, opts.limit);
        const res = await window.API.http.marketBars(q, { signal: opts.signal });
        return {
          bars: Array.isArray(res && res.bars) ? res.bars : [],
          note: (res && res.note) || '',
          source: (res && res.source) || null,
          live: !!(res && res.live),
          status: (res && res.status) || '',
          alerts: Array.isArray(res && res.alerts) ? res.alerts : [],
        };
      } catch (e) {
        return { bars: [], note: (e && e.message) || 'нет соединения', source: null, live: false, status: 'error', alerts: [] };
      }
    },
  };

  async function refreshContractsIfDue() {
    const day = new Date().toISOString().slice(0, 10);
    const key = 'desktop.contract-refresh-day';
    if (localStorage.getItem(key) !== day) {
      localStorage.setItem(key, day);
      try { await API.http.catalogRefresh(); } catch (e) { /* existing catalog remains usable */ }
      instrumentCache = null;
    }
    const list = await NTData.instruments();
    const byRoot = new Map(list.map(row => [row.root, row]));
    let rolled = 0;
    for (const model of layout.windows) {
      const root = model.config.root || String(model.config.instrument || '').split(' ')[0];
      const current = byRoot.get(root);
      if (!current || !current.symbol || current.symbol === model.config.instrument) continue;
      model.config.root = root; model.config.instrument = current.symbol;
      rolled++;
      const rec = wins.get(model.id);
      if (rec) { renderWindowMeta(rec); rec.hasBars = false; rec.nextPollAt = 0; loadWindowData(rec); }
      for (const drawing of (model.drawings || [])) if (drawing.ruleAction && drawing.ruleAction !== 'none' && rec) syncDrawingRule(rec, drawing, true);
      markDirty();
    }
    if (rolled) toast(`Rollover: обновлено ${rolled} ${rolled === 1 ? 'контракт' : 'контракта'} до актуального фронт-мансяца`);
  }

  function marketRequest(config, forcedLimit) {
    const range = config.range || { days: 31 };
    let days = Number(range.days || 0);
    if (range.id === 'custom' && range.from && range.to) {
      days = Math.max(1, Math.ceil((Date.parse(range.to) - Date.parse(range.from)) / 86400000) + 1);
    }
    const tf = String(config.timeframe || '5m');
    let perDay = tf === '1D' ? 1 : tf.endsWith('h') ? 24 / Math.max(1, Number(tf.slice(0, -1))) :
      1440 / Math.max(1, Number(tf.slice(0, -1)) || 5);
    const limit = forcedLimit || Math.max(500, Math.min(50000, Math.ceil((days || 60) * perDay * 1.15)));
    return { instrument: config.instrument, timeframe: config.timeframe, limit,
      range_days: range.id === 'custom' ? 0 : (days || 0), from: range.from || '', to: range.to || '' };
  }

  async function loadWindowData(rec) {
    const m = rec.model;
    if (m.minimized) return;
    if (rec.inFlight) return;
    rec.inFlight = true;
    setSrc(rec, 'wait', 'NinjaTrader · загрузка…');
    const payload = await NTData.bars(m.config.instrument, m.config.timeframe, { signal: UI.signal(), config: m.config });
    rec.inFlight = false;
    if (!wins.has(m.id)) return;
    applyWindowPayload(rec, payload);
  }

  function applyWindowPayload(rec, payload) {
    payload = payload || {};
    const bars = Array.isArray(payload.bars) ? payload.bars : [];
    const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
    const note = payload.note || '', live = !!payload.live, status = payload.status || '';
    if (bars.length) {
      const updated = payload.source && payload.source.updated_at_utc || `${payload.status || ''}:${bars.length}:${bars[bars.length - 1] && (bars[bars.length - 1].t || bars[bars.length - 1].c)}`;
      if (updated !== rec.lastUpdated) { rec.chart.setData(bars); rec.lastUpdated = updated; }
      rec.hasBars = true;
      setSrc(rec, live ? 'live' : 'wait', `${live ? 'NinjaTrader · live' : 'История NinjaTrader'} · ${bars.length} баров${note ? ' · ' + note : ''}`);
    } else {
      if (!rec.hasBars) rec.chart.setData([]);
      setSrc(rec, 'err', 'Нет данных NinjaTrader' + (note ? ' · ' + note : ''));
    }
    rec.lastStatus = status || (live ? 'live' : 'waiting');
    rec.nextPollAt = Date.now() + (live ? 500 : rec.lastStatus === 'historical_fallback' ? 10000 : 2000);
    if (rec.chart && rec.chart.setLoading && (bars.length || status === 'error')) rec.chart.setLoading(false);
    // Persist pane heights lazily (they are updated by the user dragging the separator).
    if (rec.chart && rec.chart.getPaneHeights) {
      const ph = rec.chart.getPaneHeights();
      if (JSON.stringify(ph) !== JSON.stringify(rec.model.config.paneHeights || {})) {
        rec.model.config.paneHeights = ph; markDirty();
      }
    }
    syncAlerts(rec, alerts);
  }
  function setSrc(rec, state, title) {
    const s = rec.srcEl; if (!s) return;
    s.classList.remove('live', 'wait', 'err');
    s.classList.add(state);
    s.title = title;
  }

  // One consolidated request updates every due chart. The bridge publishes its
  // BarsRequest snapshots every tick/second, so live windows refresh without
  // multiplying HTTP traffic when a 36/64-chart grid is open.
  UI.poll(async () => {
    const now = Date.now();
    const recs = Array.from(wins.values()).filter(rec => !rec.model.minimized && !rec.inFlight && (!rec.nextPollAt || rec.nextPollAt <= now));
    if (!recs.length) return;
    recs.forEach(rec => { rec.inFlight = true; });
    try {
      const out = await API.http.marketBarsBatch({ requests: recs.map(rec => marketRequest(rec.model.config)) });
      const rows = (out && out.series) || [];
      recs.forEach((rec, index) => { if (wins.has(rec.model.id)) applyWindowPayload(rec, rows[index] || { bars: [], alerts: [], status: 'waiting' }); });
    } catch (e) {
      recs.forEach(rec => { rec.nextPollAt = Date.now() + 2000; setSrc(rec, 'err', 'Ошибка потока данных: ' + (e.message || e)); });
    } finally { recs.forEach(rec => { rec.inFlight = false; }); }
  }, 650);

  // ---- add / configure chart dialog -------------------------------------
  async function openChartDialog(existingRec) {
    const editing = !!existingRec;
    const cfg = editing ? Object.assign({}, existingRec.model.config) : {
      instrument: '', root: '', timeframe: '5m', indicators: [], type: 'candles',
      range: { id: '1m', days: 31, from: '', to: '' }, style: Object.assign({}, DEFAULT_STYLE),
    };
    cfg.style = Object.assign({}, DEFAULT_STYLE, cfg.style || {});
    cfg.style.macd = Object.assign({}, DEFAULT_STYLE.macd, cfg.style.macd || {});
    cfg.range = Object.assign({ id: '1m', days: 31, from: '', to: '' }, cfg.range || {});
    const d = UI.drawer(
      editing ? 'Параметры графика' : 'Новый график',
      `<form class="dchart-form" id="dchart-form">
        <div class="dchart-layout">
          <div class="dchart-settings">
            <div class="fgrid">
              <label>Инструмент (актуальный контракт)
                <select id="dc-inst"><option value="">Загрузка инструментов…</option></select>
              </label>
              <label>Тип графика
                <div class="type-seg" id="dc-type">${CHART_TYPES.map(t => `<button type="button" data-v="${t.id}" class="${cfg.type === t.id ? 'on' : ''}">${t.label}</button>`).join('')}</div>
              </label>
            </div>
            <label>Таймфрейм
              <div class="tf-seg" id="dc-tf">${TIMEFRAMES.map(t => `<button type="button" data-v="${t}" class="${cfg.timeframe === t ? 'on' : ''}">${t}</button>`).join('')}</div>
            </label>
            <label>Период данных
              <div class="tf-seg range-seg" id="dc-range">${RANGE_PRESETS.map(r => `<button type="button" data-v="${r.id}" class="${cfg.range.id === r.id ? 'on' : ''}">${r.label}</button>`).join('')}</div>
            </label>
            <div class="fgrid dc-custom-range ${cfg.range.id === 'custom' ? 'show' : ''}" id="dc-custom-range">
              <label>От<input type="date" id="dc-from" value="${escAttr(cfg.range.from || '')}"></label>
              <label>До<input type="date" id="dc-to" value="${escAttr(cfg.range.to || '')}"></label>
            </div>
            <label>Индикаторы
              <div class="ind-grid" id="dc-ind">${INDICATORS.map(ind => `
                <label class="ind-chip ${cfg.indicators.includes(ind.id) ? 'on' : ''}"><input type="checkbox" value="${ind.id}" ${cfg.indicators.includes(ind.id) ? 'checked' : ''}><span>${ind.label}</span></label>`).join('')}</div>
            </label>
            <label>Внешний вид свечей
              <div class="style-grid">
                <label>Рост<input type="color" id="dc-up" value="${escAttr(cfg.style.upColor)}"></label>
                <label>Падение<input type="color" id="dc-down" value="${escAttr(cfg.style.downColor)}"></label>
                <label>Фон<input type="color" id="dc-bg" value="${escAttr(cfg.style.background)}"></label>
                <label>Ширина тела<input type="range" id="dc-body" min="15" max="100" value="${Math.round(cfg.style.bodyWidth * 100)}"></label>
                <label>Толщина тени<input type="range" id="dc-wick" min="1" max="5" step=".5" value="${cfg.style.wickWidth}"></label>
                <label>Толщина контура<input type="range" id="dc-border" min="0" max="5" step=".5" value="${cfg.style.borderWidth}"></label>
              </div>
              <div class="fgrid style-options">
                <label class="ind-chip ${cfg.style.fillOpacity > 0 ? 'on' : ''}"><input type="checkbox" id="dc-fill" ${cfg.style.fillOpacity > 0 ? 'checked' : ''}><span>Заливка свечей</span></label>
                <label>Данные сверху<select id="dc-legend"><option value="compact" ${cfg.style.legendMode === 'compact' ? 'selected' : ''}>Только инструмент и ТФ</option><option value="full" ${cfg.style.legendMode === 'full' ? 'selected' : ''}>Полные OHLCV</option><option value="hidden" ${cfg.style.legendMode === 'hidden' ? 'selected' : ''}>Скрыть всё</option></select></label>
              </div>
            </label>
            <label class="macd-fields ${cfg.indicators.includes('macd') ? 'show' : ''}" id="dc-macd">Вид MACD
              <div class="fgrid style-options">
                <label class="ind-chip ${cfg.style.macd.fill ? 'on' : ''}"><input type="checkbox" id="dc-macd-fill" ${cfg.style.macd.fill ? 'checked' : ''}><span>Заливка гистограммы</span></label>
                <label class="ind-chip ${cfg.style.macd.area ? 'on' : ''}"><input type="checkbox" id="dc-macd-area" ${cfg.style.macd.area ? 'checked' : ''}><span>Заливка между линиями</span></label>
                <label class="ind-chip ${cfg.style.macd.fillToZero ? 'on' : ''}"><input type="checkbox" id="dc-macd-zero" ${cfg.style.macd.fillToZero ? 'checked' : ''}><span>Заливка до нуля</span></label>
              </div>
              <div class="style-grid">
                <label>Гист. ↑<input type="color" id="dc-macd-up" value="${escAttr(cfg.style.macd.up)}"></label>
                <label>Гист. ↓<input type="color" id="dc-macd-down" value="${escAttr(cfg.style.macd.down)}"></label>
                <label>Насыщенность<input type="range" id="dc-macd-op" min="10" max="100" value="${Math.round((cfg.style.macd.opacity == null ? 0.85 : cfg.style.macd.opacity) * 100)}"></label>
                <label>Линия MACD<input type="color" id="dc-macd-line" value="${escAttr(cfg.style.macd.line)}"></label>
                <label>Сигнальная<input type="color" id="dc-macd-signal" value="${escAttr(cfg.style.macd.signal)}"></label>
              </div>
            </label>
          </div>
          <div class="dchart-preview-wrap">
            <div class="dchart-preview-title"><b>Живой предпросмотр</b><span>${editing ? 'Текущие данные графика' : 'Наглядный пример свечей'} · изменения видны сразу</span></div>
            <div class="dchart-preview" id="dc-preview"></div>
            ${editing ? '<button type="button" class="btn" id="dc-style-all">Применить этот стиль ко всем графикам</button>' : ''}
          </div>
        </div>
        <div class="dchart-actions">
          <button type="button" class="btn ghost" data-close-drawer>Отмена</button>
          <button type="submit" class="btn primary" id="dc-submit">${editing ? 'Применить' : 'Добавить график'}</button>
        </div>
      </form>`
    );
    d.classList.add('wide');

    const instSel = qs('#dc-inst', d);
    const list = await NTData.instruments();
    if (!list.length) {
      instSel.innerHTML = '<option value="">Нет инструментов — NinjaTrader офлайн</option>';
    } else {
      const groups = new Map(); list.forEach(x => { if (!groups.has(x.group)) groups.set(x.group, []); groups.get(x.group).push(x); });
      instSel.innerHTML = Array.from(groups.entries()).map(([group, rows]) => `<optgroup label="${escAttr(group)}">${rows.map(x => `<option value="${escAttr(x.symbol)}" data-root="${escAttr(x.root)}" ${x.available ? '' : 'disabled'}>${escAttr(x.root)} — ${escAttr(x.name)}${x.available ? ` · ${escAttr(x.symbol)}` : ' · контракт пока недоступен'}</option>`).join('')}</optgroup>`).join('');
      const firstAvailable = list.find(x => x.available);
      const chosen = cfg.instrument || (firstAvailable && firstAvailable.symbol) || '';
      instSel.value = chosen;
      if (!instSel.value) instSel.selectedIndex = 0;
      cfg.instrument = instSel.value;
    }

    const preview = window.ChartEngine.create(qs('#dc-preview', d), {
      instrument: cfg.root || String(cfg.instrument || '').split(' ')[0], timeframe: cfg.timeframe,
      indicators: cfg.indicators, style: cfg.style, initialBars: 60,
    });
    const previewData = editing && existingRec.chart.getData().length ? existingRec.chart.getData() : makePreviewBars();
    preview.setData(previewData);

    const readForm = () => {
      const rangeId = qs('#dc-range .on', d)?.dataset.v || cfg.range.id;
      const preset = RANGE_PRESETS.find(row => row.id === rangeId);
      return Object.assign({}, cfg, {
        instrument: instSel.value || '', root: instSel.selectedOptions[0]?.dataset.root || '',
        indicators: Array.from(qs('#dc-ind', d).querySelectorAll('input:checked')).map(x => x.value),
        range: { id: rangeId, days: preset ? preset.days : null, from: qs('#dc-from', d).value, to: qs('#dc-to', d).value },
        style: Object.assign({}, cfg.style, {
          upColor: qs('#dc-up', d).value, upFill: qs('#dc-up', d).value,
          downColor: qs('#dc-down', d).value, downFill: qs('#dc-down', d).value,
          background: qs('#dc-bg', d).value, bodyWidth: Number(qs('#dc-body', d).value) / 100,
          wickWidth: Number(qs('#dc-wick', d).value), borderWidth: Number(qs('#dc-border', d).value),
          fillOpacity: qs('#dc-fill', d).checked ? 0.85 : 0, legendMode: qs('#dc-legend', d).value,
          macd: {
            fill: qs('#dc-macd-fill', d).checked, area: qs('#dc-macd-area', d).checked,
            fillToZero: qs('#dc-macd-zero', d).checked,
            up: qs('#dc-macd-up', d).value, down: qs('#dc-macd-down', d).value,
            line: qs('#dc-macd-line', d).value, signal: qs('#dc-macd-signal', d).value,
            opacity: Number(qs('#dc-macd-op', d).value) / 100,
          },
        }),
      });
    };
    const refreshPreview = () => {
      const current = readForm();
      preview.setMeta(current.root || current.instrument, current.timeframe);
      preview.setIndicators(current.indicators); preview.setStyle(current.style);
    };

    // segmented pickers
    qs('#dc-tf', d).addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]'); if (!b) return;
      cfg.timeframe = b.dataset.v;
      qs('#dc-tf', d).querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      refreshPreview();
    });
    qs('#dc-type', d).addEventListener('click', (e) => {
      const b = e.target.closest('button[data-v]'); if (!b) return;
      cfg.type = b.dataset.v;
      qs('#dc-type', d).querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
    });
    qs('#dc-ind', d).addEventListener('change', (e) => {
      const cb = e.target.closest('input[type="checkbox"]'); if (!cb) return;
      cb.closest('.ind-chip').classList.toggle('on', cb.checked);
      if (cb.value === 'macd') qs('#dc-macd', d).classList.toggle('show', cb.checked);
      refreshPreview();
    });
    qs('#dc-range', d).addEventListener('click', e => {
      const b = e.target.closest('button[data-v]'); if (!b) return;
      qs('#dc-range', d).querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
      qs('#dc-custom-range', d).classList.toggle('show', b.dataset.v === 'custom');
    });
    instSel.addEventListener('change', refreshPreview);
    qsaLocal('#dc-up,#dc-down,#dc-bg,#dc-body,#dc-wick,#dc-border,#dc-fill,#dc-legend,#dc-macd-fill,#dc-macd-area,#dc-macd-zero,#dc-macd-up,#dc-macd-down,#dc-macd-op,#dc-macd-line,#dc-macd-signal', d).forEach(node => node.addEventListener('input', () => {
      if (node.closest('.ind-chip')) node.closest('.ind-chip').classList.toggle('on', node.checked);
      refreshPreview();
    }));
    const styleAll = qs('#dc-style-all', d);
    if (styleAll) styleAll.addEventListener('click', () => {
      const style = readForm().style;
      layout.windows.forEach(model => { model.config.style = Object.assign({}, style); const rec = wins.get(model.id); if (rec) rec.chart.setStyle(style); });
      markDirty(); toast('Стиль применён ко всем графикам');
    });

    const cleanup = () => preview.destroy();
    qsaLocal('[data-close-drawer]', d).forEach(btn => btn.addEventListener('click', cleanup, { once: true }));

    qs('#dchart-form', d).addEventListener('submit', (e) => {
      e.preventDefault();
      const next = readForm();
      if (!next.instrument) { toast('Выберите инструмент'); return; }
      if (next.range.id === 'custom' && (!next.range.from || !next.range.to)) { toast('Укажите обе даты диапазона'); return; }
      cleanup();
      if (editing) applyChartConfig(existingRec, next);
      else addChart(next);
      UI.closeDrawer();
    });
  }

  function makePreviewBars() {
    const out = []; let close = 100;
    for (let i = 0; i < 90; i++) {
      const drift = Math.sin(i / 5) * 0.7 + Math.cos(i / 11) * 0.35;
      const open = close; close = open + drift;
      out.push({ t: new Date(Date.now() - (89 - i) * 300000).toISOString(), o: open,
        h: Math.max(open, close) + 0.7, l: Math.min(open, close) - 0.6, c: close, v: 100 + i * 3 });
    }
    return out;
  }

  function applyChartConfig(rec, cfg) {
    const identityChanged = rec.model.config.instrument !== cfg.instrument || rec.model.config.timeframe !== cfg.timeframe;
    if (identityChanged) {
      deleteModelAlerts(rec.model);
      rec.model.drawings = [];
      rec.chart.setDrawings([]);
      rec.hasBars = false;
    }
    rec.model.config = Object.assign({}, rec.model.config, cfg);
    renderWindowMeta(rec);
    rec.chart.setIndicators(cfg.indicators);
    rec.chart.setStyle(cfg.style || DEFAULT_STYLE);
    renderSidePanel(rec);
    if (rec.chart && rec.chart.setLoading) rec.chart.setLoading(true, 'Загрузка…');
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
      drawings: [],
    };
    clampModel(model);
    layout.windows.push(model);
    layout.grid = 0;
    createWindow(model);
    refreshEmpty();
    renderDock();
    markDirty();
  }
  function toggleBare(rec, on) {
    rec.model.bare = on;
    renderWindowMeta(rec); placeWindow(rec); markDirty();
  }

  // ---- drawings + persistent server-side alerts -------------------------
  function activateDrawingTool(rec, type) {
    if (!rec.hasBars) { toast('Сначала дождитесь данных NinjaTrader'); return; }
    const names = { line: 'Горизонтальная линия', trendline: 'Трендовая линия', point: 'Точка', arrow: 'Стрелка вверх',
      arrow_up: 'Стрелка вверх', arrow_down: 'Стрелка вниз', flag: 'Флажок', target: 'Цель', label: 'Подпись' };
    rec.chart.setTool({ type, label: '', color: '#fcc55a', locked: false,
      ruleAction: 'none', durationMinutes: 0, agentId: '', agentMessage: '' });
    const menu = qs('.dwin-tools-menu', rec.node); if (menu) menu.classList.remove('open');
    qsaLocal('.dwin-tools-menu button[data-tool]', rec.node).forEach(b => b.classList.toggle('on', b.dataset.tool === type));
    qs('.dwin-drawing-editor', rec.node).classList.remove('show');
    toast(type === 'trendline' ? 'Отметьте две точки: начало и конец линии' : 'Щёлкните по нужному месту на графике');
  }

  // ---- in-chart side menu helpers ---------------------------------------
  function renderSidePanel(rec) {
    const m = rec.model, node = rec.node;
    const symEl = qs('.dsd-inst-sym', node); if (symEl) symEl.textContent = m.config.instrument || '—';
    const tfWrap = qs('.dsd-tf', node);
    if (tfWrap) tfWrap.innerHTML = TIMEFRAMES.map(t => `<button type="button" data-tf="${t}" class="${m.config.timeframe === t ? 'on' : ''}">${t}</button>`).join('');
    const indWrap = qs('.dsd-inds', node);
    if (indWrap) indWrap.innerHTML = INDICATORS.map(i => `<button type="button" data-ind="${escAttr(i.id)}" class="${(m.config.indicators || []).includes(i.id) ? 'on' : ''}">${escAttr(i.label)}</button>`).join('');
    const aspect = m.config.aspect || 'auto';
    qsaLocal('.dsd-aspect button', node).forEach(b => b.classList.toggle('on', b.dataset.aspect === aspect));
    const macdBtn = qs('.dsd-macd', node);
    if (macdBtn) macdBtn.hidden = !(m.config.indicators || []).includes('macd');
  }
  function setWindowTimeframe(rec, tf) {
    if (!tf || rec.model.config.timeframe === tf) return;
    rec.model.config.timeframe = tf;
    renderWindowMeta(rec);
    rec.hasBars = false; rec.nextPollAt = 0;
    if (rec.chart && rec.chart.setLoading) rec.chart.setLoading(true, 'Загрузка ' + tf + '…');
    loadWindowData(rec);
    renderSidePanel(rec);
    markDirty();
  }
  function toggleWindowIndicator(rec, ind) {
    const list = Array.isArray(rec.model.config.indicators) ? rec.model.config.indicators.slice() : [];
    const idx = list.indexOf(ind);
    if (idx >= 0) list.splice(idx, 1); else list.push(ind);
    rec.model.config.indicators = list;
    rec.chart.setIndicators(list);
    renderSidePanel(rec);
    markDirty();
  }
  function openMacdSettings(rec) {
    const macd = Object.assign({}, DEFAULT_STYLE.macd, (rec.model.config.style && rec.model.config.style.macd) || {});
    const d = UI.drawer('Настройки MACD', `<form class="drawing-edit-form macd-fields show" id="macd-form" style="padding:14px">
      <label class="drawing-lock"><input type="checkbox" id="mc-fill" ${macd.fill ? 'checked' : ''}><span>Заливка гистограммы</span></label>
      <label>Насыщенность заливки<input type="range" id="mc-op" min="10" max="100" value="${Math.round((macd.opacity == null ? 0.85 : macd.opacity) * 100)}"></label>
      <div class="macd-grid">
        <label>Гистограмма ↑<input type="color" id="mc-up" value="${escAttr(macd.up || '#34d399')}"></label>
        <label>Гистограмма ↓<input type="color" id="mc-down" value="${escAttr(macd.down || '#ff6b81')}"></label>
        <label>Линия MACD<input type="color" id="mc-line" value="${escAttr(macd.line || '#4fd1e0')}"></label>
        <label>Сигнальная<input type="color" id="mc-signal" value="${escAttr(macd.signal || '#fcc55a')}"></label>
      </div>
      <label class="drawing-lock"><input type="checkbox" id="mc-area" ${macd.area ? 'checked' : ''}><span>Заливка между линиями</span></label>
      <label class="drawing-lock"><input type="checkbox" id="mc-zero" ${macd.fillToZero ? 'checked' : ''}><span>Заливка до нуля (вниз)</span></label>
      <div class="dchart-actions"><button type="button" class="btn ghost" id="mc-all">Применить ко всем</button><button type="button" class="btn primary" data-close-drawer>Готово</button></div>
    </form>`);
    const read = () => ({
      fill: qs('#mc-fill', d).checked,
      opacity: Number(qs('#mc-op', d).value) / 100,
      up: qs('#mc-up', d).value, down: qs('#mc-down', d).value,
      line: qs('#mc-line', d).value, signal: qs('#mc-signal', d).value,
      area: qs('#mc-area', d).checked,
      fillToZero: qs('#mc-zero', d).checked,
    });
    const apply = () => {
      const next = read();
      rec.model.config.style = Object.assign({}, rec.model.config.style, { macd: next });
      rec.chart.setStyle({ macd: next });
      markDirty();
    };
    qsaLocal('#mc-fill,#mc-op,#mc-up,#mc-down,#mc-line,#mc-signal,#mc-area,#mc-zero', d).forEach(node => node.addEventListener('input', apply));
    qs('#mc-all', d).addEventListener('click', () => {
      const next = read();
      layout.windows.forEach(model => {
        model.config.style = Object.assign({}, model.config.style, { macd: Object.assign({}, next) });
        const r = wins.get(model.id); if (r) r.chart.setStyle({ macd: Object.assign({}, next) });
      });
      markDirty(); toast('Настройки MACD применены ко всем графикам');
    });
  }

  async function loadAgentOptions() {
    if (agentCache) return agentCache;
    try {
      const res = await API.http.aiAgents({ signal: UI.signal() });
      agentCache = (res && res.agents || []).filter(row => row && row.enabled !== false).map(row => ({
        id: row.id || row.agent_id || row.name, name: row.name || row.label || row.id,
      }));
    } catch (e) { agentCache = []; }
    // Иван (chart operator) always leads the list — he owns the desktop.
    agentCache = [{ id: 'ivan', name: 'Иван · оператор графиков' }].concat(
      agentCache.filter(a => a.id !== 'ivan'));
    return agentCache;
  }

  async function renderDrawingEditor(rec, drawing) {
    qsaLocal('.dwin-tools button', rec.node).forEach(b => b.classList.remove('on'));
    const box = qs('.dwin-drawing-editor', rec.node);
    if (!drawing) { box.classList.remove('show', 'collapsed'); box.innerHTML = ''; return; }
    const agents = await loadAgentOptions();
    if (!wins.has(rec.model.id) || !(rec.model.drawings || []).some(row => row.id === drawing.id)) return;
    const action = drawing.ruleAction || (drawing.telegram ? 'telegram' : 'none');
    const isPrice = drawing.type !== 'trendline';
    const typeName = { line: 'Линия', trendline: 'Трендовая линия', point: 'Точка', flag: 'Флажок',
      target: 'Цель', label: 'Подпись', arrow_up: 'Стрелка вверх', arrow_down: 'Стрелка вниз' }[drawing.type] || 'Стрелка';
    const dur = Number(drawing.durationMinutes || 0);
    const durEnabled = dur > 0;
    const DUR_PRESETS = [
      { label: '5м', m: 5 }, { label: '10м', m: 10 }, { label: '15м', m: 15 }, { label: '30м', m: 30 },
      { label: '1ч', m: 60 }, { label: '3ч', m: 180 }, { label: '12ч', m: 720 }, { label: 'сутки', m: 1440 },
    ];
    const isCustomDur = durEnabled && !DUR_PRESETS.some(p => p.m === dur);
    const ruleHtml = isPrice ? `
      <div class="draw-dur-row">
        <label class="drawing-lock" style="flex:0 0 auto"><input type="checkbox" data-draw-dur-on ${durEnabled ? 'checked' : ''}><span>Срок</span></label>
        <div class="draw-dur-presets ${durEnabled ? '' : 'hidden'}" data-draw-dur-wrap>
          ${DUR_PRESETS.map(p => `<button type="button" class="tf-seg-btn ${dur === p.m ? 'on' : ''}" data-dur-minutes="${p.m}">${p.label}</button>`).join('')}
          <button type="button" class="tf-seg-btn ${isCustomDur ? 'on' : ''}" data-dur-custom>...</button>
        </div>
        <input class="draw-dur-custom ${isCustomDur ? '' : 'hidden'}" type="number" data-draw-duration min="1" max="525600" value="${dur || 60}" placeholder="мин.">
      </div>
      <label>Правило<select data-draw-action>
        <option value="none" ${action === 'none' ? 'selected' : ''}>Без действия</option>
        <option value="snapshot" ${action === 'snapshot' ? 'selected' : ''}>Снимок в чат (Иван)</option>
        <option value="agent" ${action === 'agent' ? 'selected' : ''}>Поручить AI-агенту</option>
        <option value="telegram" ${action === 'telegram' ? 'selected' : ''}>Сообщить в Telegram</option>
      </select></label>
      <label class="drawing-report-field ${(action === 'snapshot' || action === 'agent') ? 'show' : ''}">Когда отчитаться<select data-draw-report>
        <option value="touch" ${(drawing.reportMode || 'touch') === 'touch' ? 'selected' : ''}>При касании уровня</option>
        <option value="expire" ${drawing.reportMode === 'expire' ? 'selected' : ''}>Если не дойдёт за срок</option>
        <option value="both" ${drawing.reportMode === 'both' ? 'selected' : ''}>В обоих случаях</option>
      </select></label>
      <div class="drawing-agent-fields ${action === 'agent' ? 'show' : ''}">
        <label>Агент<select data-draw-agent>${agents.map(a => `<option value="${escAttr(a.id)}" ${drawing.agentId === a.id ? 'selected' : ''}>${escAttr(a.name)}</option>`).join('')}</select></label>
        <label>Поручение<textarea data-draw-message rows="2" placeholder="Что выполнить (можно «через 30 минут снимок»)">${escAttr(drawing.agentMessage || '')}</textarea></label>
      </div>` : '<div class="dchart-hint" style="margin:0">Трендовую линию можно перетаскивать за концы и целиком.</div>';
    // Panel starts COLLAPSED (just the title bar) — click ⇔ to see settings.
    const alreadyOpen = box.classList.contains('show') && !box.classList.contains('collapsed');
    box.innerHTML = `<form class="drawing-edit-form">
      <div class="drawing-edit-head">
        <b>${typeName}</b>
        <button type="button" data-draw-collapse title="Развернуть / свернуть настройки">⇔</button>
        <button type="button" data-draw-close>×</button>
      </div>
      <div class="draw-settings-body">
        <label>Подпись<input data-draw-label maxlength="160" value="${escAttr(drawing.label || '')}" placeholder="(без подписи)"></label>
        <div class="drawing-edit-row"><label>Цвет<input type="color" data-draw-color value="${escAttr(drawing.color || '#fcc55a')}"></label></div>
        <label class="drawing-lock"><input type="checkbox" data-draw-lock ${drawing.locked ? 'checked' : ''}><span>${drawing.locked ? 'Закреплена' : 'Можно перетаскивать'}</span></label>
        ${ruleHtml}
        <div class="drawing-edit-actions"><button type="button" class="btn sm danger" data-draw-delete>Удалить</button><button class="btn sm primary" type="submit">Сохранить</button></div>
      </div>
    </form>`;
    box.classList.add('show');
    // Always start collapsed; stay open if the user already expanded for this drawing.
    if (!alreadyOpen) box.classList.add('collapsed'); else box.classList.remove('collapsed');
    box.querySelector('[data-draw-close]').addEventListener('click', () => { box.classList.remove('show', 'collapsed'); rec.chart.selectDrawing(null); });
    // Duration presets
    box.querySelector('[data-draw-dur-on]')?.addEventListener('change', e => {
      box.querySelector('[data-draw-dur-wrap]').classList.toggle('hidden', !e.target.checked);
      if (!e.target.checked) { box.querySelector('.draw-dur-custom')?.classList.add('hidden'); }
    });
    box.querySelectorAll('[data-dur-minutes]').forEach(btn => btn.addEventListener('click', () => {
      box.querySelectorAll('[data-dur-minutes],[data-dur-custom]').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
      box.querySelector('.draw-dur-custom')?.classList.add('hidden');
    }));
    box.querySelector('[data-dur-custom]')?.addEventListener('click', () => {
      box.querySelectorAll('[data-dur-minutes],[data-dur-custom]').forEach(b => b.classList.remove('on'));
      box.querySelector('[data-dur-custom]').classList.add('on');
      box.querySelector('.draw-dur-custom')?.classList.remove('hidden');
    });
    const actionSel = box.querySelector('[data-draw-action]');
    if (actionSel) actionSel.addEventListener('change', e => {
      const v = e.target.value;
      const af = box.querySelector('.drawing-agent-fields');
      const rf = box.querySelector('.drawing-report-field');
      if (af) af.classList.toggle('show', v === 'agent');
      if (rf) rf.classList.toggle('show', v === 'snapshot' || v === 'agent');
    });
    box.querySelector('[data-draw-lock]').addEventListener('change', e => {
      drawing.locked = e.target.checked; e.target.nextElementSibling.textContent = drawing.locked ? 'Закреплена' : 'Можно перетаскивать';
      rec.chart.updateDrawing(drawing.id, { locked: drawing.locked }); markDirty();
    });
    box.querySelector('[data-draw-delete]').addEventListener('click', () => removeDrawing(rec, drawing));
    box.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault();
      const ruleAction = actionSel ? actionSel.value : 'none';
      const durOnEl = box.querySelector('[data-draw-dur-on]');
      const durEnabled = durOnEl ? durOnEl.checked : false;
      const durEl = box.querySelector('[data-draw-duration]');
      const activePreset = box.querySelector('[data-dur-minutes].on');
      let durationMinutes = 0;
      if (durEnabled) {
        if (activePreset) durationMinutes = Number(activePreset.dataset.durMinutes) || 0;
        else if (durEl) durationMinutes = Math.max(1, Number(durEl.value) || 0);
      }
      const repEl = box.querySelector('[data-draw-report]');
      const agEl = box.querySelector('[data-draw-agent]');
      const msgEl = box.querySelector('[data-draw-message]');
      const patch = {
        label: box.querySelector('[data-draw-label]').value.trim(),  // empty = no label on chart
        color: box.querySelector('[data-draw-color]').value,
        durationMinutes,
        locked: box.querySelector('[data-draw-lock]').checked,
        ruleAction: ruleAction,
        reportMode: repEl ? repEl.value : (drawing.reportMode || 'touch'),
        snapshot: ruleAction === 'snapshot',
        conversationId: currentConversationId(),
        agentId: ruleAction === 'snapshot' ? 'ivan' : (agEl ? agEl.value : (drawing.agentId || '')),
        agentMessage: msgEl ? msgEl.value.trim() : (drawing.agentMessage || ''),
      };
      // A real Иван task gets its own chat + Telegram topic named by the task,
      // so reports (and the snapshot photo) land in a dedicated thread.
      const isTask = isPrice && (ruleAction === 'snapshot' || ruleAction === 'agent');
      if (isTask) {
        let convId = (drawing.conversationId && drawing.conversationId !== 'default') ? drawing.conversationId : '';
        if (!convId) {
          const title = `Иван · ${rec.model.config.instrument} · ${patch.label}`.slice(0, 90);
          try {
            const res = await API.http.aiOrchestratorCreateConversation(title);
            convId = res && res.conversation && res.conversation.conversation_id;
          } catch (er) { /* fall back to current chat */ }
        }
        if (convId) { patch.conversationId = convId; try { localStorage.setItem('orch.currentConversationId', convId); } catch (er) {} }
      }
      Object.assign(drawing, patch); rec.chart.updateDrawing(drawing.id, patch); markDirty();
      await syncDrawingRule(rec, drawing, false); box.classList.remove('show');
      if (isTask && window.UI && UI.openOrchestrator) { try { UI.openOrchestrator(); } catch (er) {} }
    });
  }

  async function syncDrawingRule(rec, drawing, silent) {
    if (drawing.alertId) {
      try { await API.http.deletePriceAlert(drawing.alertId); } catch (e) { /* already removed */ }
      drawing.alertId = '';
    }
    if (!drawing.ruleAction || drawing.ruleAction === 'none' || !Number.isFinite(Number(drawing.price))) {
      drawing.status = 'local-only'; rec.chart.setDrawings(rec.model.drawings); markDirty();
      if (!silent && drawing.ruleAction && drawing.ruleAction !== 'none' && !Number.isFinite(Number(drawing.price))) {
        toast('Для правила нужна ценовая отметка, а не линия из двух точек');
      } else if (!silent) { toast('Отметка сохранена без правила'); }
      return;
    }
    try {
      const delaySeconds = (drawing.ruleAction === 'snapshot' || drawing.ruleAction === 'agent')
        ? parseDelaySeconds(drawing.agentMessage) : 0;
      const out = await API.http.createPriceAlert({
        drawing_id: drawing.id, window_id: rec.model.id,
        instrument: rec.model.config.instrument, timeframe: rec.model.config.timeframe,
        type: drawing.type, price: drawing.price, label: drawing.label, color: drawing.color,
        duration_minutes: drawing.durationMinutes || 0,
        trigger: delaySeconds > 0 ? 'time' : 'price',
        delay_seconds: delaySeconds,
        action: drawing.ruleAction, telegram: drawing.ruleAction === 'telegram',
        snapshot: drawing.ruleAction === 'snapshot' || !!drawing.snapshot,
        report_mode: drawing.reportMode || 'touch',
        conversation_id: drawing.conversationId || currentConversationId(),
        agent_id: drawing.ruleAction === 'snapshot' ? (drawing.agentId || 'ivan') : (drawing.agentId || ''),
        agent_message: drawing.agentMessage || '',
        current_price: rec.chart.latestPrice(),
      });
      drawing.alertId = out && out.alert && out.alert.id; drawing.status = 'active';
      rec.chart.setDrawings(rec.model.drawings); markDirty();
      if (!silent) toast('Правило отметки сохранено');
    } catch (e) {
      drawing.status = 'local-only'; rec.chart.setDrawings(rec.model.drawings);
      if (!silent) toast('Правило не создано: ' + (e.message || e));
    }
  }

  async function removeDrawing(rec, drawing) {
    rec.model.drawings = (rec.model.drawings || []).filter(row => row.id !== drawing.id);
    rec.chart.removeDrawing(drawing.id); qs('.dwin-drawing-editor', rec.node).classList.remove('show'); markDirty();
    if (drawing.alertId) try { await API.http.deletePriceAlert(drawing.alertId); } catch (e) { /* already removed */ }
    toast('Отметка удалена');
  }

  function deleteModelAlerts(model) {
    (model.drawings || []).forEach(drawing => {
      if (drawing.alertId) API.http.deletePriceAlert(drawing.alertId).catch(() => {});
    });
  }

  function syncAlerts(rec, alerts) {
    if (!Array.isArray(alerts) || !alerts.length || !Array.isArray(rec.model.drawings)) return;
    const byDrawing = new Map(alerts.map(a => [a.drawing_id, a]));
    let changed = false;
    rec.model.drawings.forEach(drawing => {
      const alert = byDrawing.get(drawing.id); if (!alert) return;
      if (drawing.alertId !== alert.id || drawing.status !== alert.status) changed = true;
      drawing.alertId = alert.id; drawing.status = alert.status;
      const mode = alert.report_mode || 'touch';
      // Иван owns 'snapshot'-rule and time-scheduled reporting (captures the
      // canvas from the browser); the classic 'agent' rule stays backend-driven.
      const wantsReport = alert.action === 'snapshot' || alert.trigger === 'time';
      if (alert.status === 'triggered' && !rec.notifiedAlerts?.has(alert.id)) {
        if (!rec.notifiedAlerts) rec.notifiedAlerts = new Set();
        rec.notifiedAlerts.add(alert.id);
        const banner = qs('.dwin-alert', rec.node);
        banner.textContent = `🔔 ${alert.label}: цена коснулась ${Number(alert.price).toLocaleString('en-US')}`;
        banner.classList.add('show');
        setTimeout(() => banner.classList.remove('show'), 12000);
        toast(`${alert.instrument}: ${alert.label} — уровень достигнут`);
      }
      if (alert.status === 'triggered' && wantsReport && alert.conversation_id && (mode === 'touch' || mode === 'both')) {
        reportAlertSnapshot(rec, alert, 'reached');
      }
      if (alert.status === 'expired' && wantsReport && alert.conversation_id && (mode === 'expire' || mode === 'both')) {
        reportAlertSnapshot(rec, alert, 'not_reached');
      }
    });
    if (changed) { rec.chart.setDrawings(rec.model.drawings); markDirty(); }
  }

  // Иван's report loop: when a watched level is touched (or its window expires
  // without a touch) we capture the chart canvas and post it to the chat.
  function currentConversationId() {
    try { return localStorage.getItem('orch.currentConversationId') || 'default'; } catch (e) { return 'default'; }
  }
  // Parse a delay ("через 30 секунд", "через минуту") from a free-text task.
  function parseDelaySeconds(text) {
    const low = String(text || '').toLowerCase();
    const m = low.match(/(?:через|спустя|in)\s+(\d+(?:[.,]\d+)?)\s*(секунд\w*|сек|мин\w*|час\w*|ч)\b/);
    if (m) {
      const v = parseFloat(m[1].replace(',', '.'));
      const u = m[2];
      if (u.startsWith('сек') || u === 'сек') return Math.max(1, Math.round(v));
      if (u.startsWith('мин')) return Math.max(1, Math.round(v * 60));
      return Math.max(1, Math.round(v * 3600));
    }
    if (/через\s+минут|спустя\s+минут/.test(low)) return 60;
    if (/через\s+час|спустя\s+час/.test(low)) return 3600;
    if (/через\s+секунд/.test(low)) return 5;
    return 0;
  }
  function snapshotReported(alertId, phase) {
    try { return localStorage.getItem('desktop.snap.' + alertId + '.' + phase) === '1'; } catch (e) { return false; }
  }
  function markSnapshotReported(alertId, phase) {
    try { localStorage.setItem('desktop.snap.' + alertId + '.' + phase, '1'); } catch (e) { /* storage off */ }
  }
  async function reportAlertSnapshot(rec, alert, phase) {
    if (snapshotReported(alert.id, phase)) return;
    markSnapshotReported(alert.id, phase);
    const price = Number(alert.price);
    const level = Number.isFinite(price) ? price.toLocaleString('en-US') : String(alert.price);
    const inst = alert.instrument || rec.model.config.instrument;
    const tf = alert.timeframe || rec.model.config.timeframe;
    const label = alert.label || 'уровень';
    const cur = rec.chart.latestPrice();
    const curTxt = cur != null ? Number(cur).toLocaleString('en-US') : '—';
    let text;
    if (alert.trigger === 'time') {
      text = `Снимок ${inst} (${tf}) по расписанию готов. Текущая цена: ${curTxt}.`;
    } else if (phase === 'reached') {
      text = `Готово: цена ${inst} коснулась уровня ${level} (${label}). Текущая цена: ${curTxt}.`;
    } else {
      text = `Цена ${inst} не дошла до уровня ${level} (${label}) за отведённое время. Текущая цена: ${curTxt}. Прикладываю снимок графика.`;
    }
    const wantImage = alert.action === 'snapshot' || alert.snapshot || alert.trigger === 'time';
    if (wantImage && rec.chart && rec.chart.fitView) rec.chart.fitView();
    await nextFrame();
    const image = wantImage && rec.chart ? rec.chart.toImage({ maxWidth: 1600, quality: 0.9 }) : '';
    try {
      await API.http.chartSnapshot({
        image: image || undefined,
        conversation_id: alert.conversation_id,
        instrument: inst, timeframe: tf,
        outcome: phase, text,
        caption: `${inst} · ${label} · ${level}`,
      });
    } catch (e) { /* best-effort; will not retry to avoid spamming */ }
  }

  function qsaLocal(selector, root) { return Array.from((root || document).querySelectorAll(selector)); }

  // ---- Иван — chart commands issued from the orchestrator chat -----------
  function findRecByRoot(root) {
    root = String(root || '').toUpperCase();
    if (!root) return null;
    for (const rec of wins.values()) {
      const r = (rec.model.config.root || String(rec.model.config.instrument || '').split(' ')[0]).toUpperCase();
      if (r === root) return rec;
    }
    return null;
  }
  async function ensureWindowForRoot(root, timeframe) {
    root = String(root || '').toUpperCase();
    if (!root) return null;
    let rec = findRecByRoot(root);
    if (rec) return rec;
    const list = await NTData.instruments();
    const item = list.find(x => x.root === root && x.available && x.symbol) || list.find(x => x.root === root);
    const symbol = (item && item.symbol) || root;
    addChart({ instrument: symbol, root: root, timeframe: timeframe || '5m', indicators: [], type: 'candles',
      range: { id: '1m', days: 31, from: '', to: '' }, style: Object.assign({}, DEFAULT_STYLE) });
    return findRecByRoot(root);
  }
  // The currently active chart window (or the top-most one) — used when Иван is
  // asked to snapshot "the chart" without naming an instrument.
  function activeRec() {
    let active = null;
    for (const rec of wins.values()) {
      if (rec.node.classList.contains('active') && !rec.model.minimized) return rec;
      if (!rec.model.minimized && (!active || (rec.model.z || 0) > (active.model.z || 0))) active = rec;
    }
    return active;
  }
  async function ensureAnyWindow(timeframe) {
    const rec = activeRec();
    if (rec) return rec;
    const list = (await NTData.instruments()).filter(x => x.available && x.symbol);
    if (!list.length) return null;
    const item = list[0];
    addChart({ instrument: item.symbol, root: item.root, timeframe: timeframe || '5m', indicators: [], type: 'candles',
      range: { id: '1m', days: 31, from: '', to: '' }, style: Object.assign({}, DEFAULT_STYLE) });
    return findRecByRoot(item.root);
  }
  function waitForBars(rec, timeoutMs) {
    return new Promise(resolve => {
      const t0 = Date.now();
      const tick = () => {
        if (!wins.has(rec.model.id) || rec.hasBars || Date.now() - t0 > (timeoutMs || 6000)) return resolve();
        setTimeout(tick, 300);
      };
      tick();
    });
  }
  function nextFrame() { return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); }
  async function captureAndReport(rec, cmd, outcome, text) {
    const fit = !cmd.payload || cmd.payload.fit !== false;
    if (fit && rec.chart && rec.chart.fitView) rec.chart.fitView();
    await nextFrame();
    const inst = rec.model.config.instrument;
    const image = rec.chart ? rec.chart.toImage({ maxWidth: 1600, quality: 0.9 }) : '';
    await API.http.chartSnapshot({
      image: image || undefined, conversation_id: cmd.conversation_id || currentConversationId(),
      instrument: inst, timeframe: rec.model.config.timeframe,
      outcome: outcome || 'manual', text: text || `Снимок графика ${inst} (${rec.model.config.timeframe}).`,
      caption: `${inst} · ${rec.model.config.timeframe}`,
    });
  }
  async function applyChartCommand(cmd) {
    const type = cmd && cmd.type;
    if (type === 'clear') {
      const root = String(cmd.instrument || '').toUpperCase();
      const targets = root ? [findRecByRoot(root)].filter(Boolean) : Array.from(wins.values());
      targets.forEach(rec => {
        (rec.model.drawings || []).forEach(d => { if (d.alertId) API.http.deletePriceAlert(d.alertId).catch(() => {}); });
        rec.model.drawings = []; rec.chart.setDrawings([]);
        const box = qs('.dwin-drawing-editor', rec.node); if (box) box.classList.remove('show');
      });
      markDirty();
      return { ok: true, cleared: targets.length };
    }
    if (type === 'draw') {
      const p = (cmd.payload && cmd.payload.drawing) || {};
      const rec = await ensureWindowForRoot(cmd.instrument, cmd.timeframe);
      if (!rec) return { ok: false, error: 'нет окна для инструмента' };
      const ruleMap = { snapshot: 'snapshot', agent: 'agent', telegram: 'telegram', none: 'none' };
      const drawing = {
        id: 'dr_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7),
        type: p.type || 'line', price: Number(p.price), label: p.label || 'Иван',
        color: p.color || '#4fd1e0', locked: false,
        durationMinutes: Number(p.duration_minutes) || 0,
        ruleAction: ruleMap[p.rule] || 'none',
        snapshot: !!p.snapshot, reportMode: p.report_mode || 'touch',
        agentId: 'ivan', agentMessage: cmd.note || '',
        conversationId: cmd.conversation_id || currentConversationId(),
        createdAt: new Date().toISOString(), status: 'active',
      };
      if (!Number.isFinite(drawing.price)) return { ok: false, error: 'нет цены' };
      rec.model.drawings = Array.isArray(rec.model.drawings) ? rec.model.drawings : [];
      rec.model.drawings.push(drawing);
      rec.chart.setDrawings(rec.model.drawings);
      bringToFront(rec);
      await syncDrawingRule(rec, drawing, true);
      markDirty();
      toast(`Иван: отметка на ${rec.model.config.instrument} по ${drawing.price}`);
      return { ok: true, drawing_id: drawing.id, window_id: rec.model.id };
    }
    if (type === 'snapshot') {
      let rec = cmd.instrument ? await ensureWindowForRoot(cmd.instrument, cmd.timeframe) : activeRec();
      if (!rec && !cmd.instrument) rec = await ensureAnyWindow(cmd.timeframe);
      if (!rec) return { ok: false, error: 'нет открытого графика' };
      bringToFront(rec);
      if (!rec.hasBars) await waitForBars(rec, 6000);
      await captureAndReport(rec, cmd, 'manual');
      return { ok: true, window_id: rec.model.id };
    }
    if (type === 'open') {
      let rec = cmd.instrument ? await ensureWindowForRoot(cmd.instrument, cmd.timeframe) : activeRec();
      if (!rec) return { ok: false, error: 'нет открытого графика' };
      bringToFront(rec);
      if (rec.chart && rec.chart.fitView) { if (!rec.hasBars) await waitForBars(rec, 6000); rec.chart.fitView(); }
      return { ok: true, window_id: rec.model.id };
    }
    if (type === 'focus') {
      const rec = findRecByRoot(cmd.instrument); if (rec) bringToFront(rec);
      return { ok: !!rec };
    }
    return { ok: false, error: 'неизвестная команда' };
  }
  let cmdInFlight = false;
  UI.poll(async () => {
    if (cmdInFlight || !window.API || (API.config && API.config.offline)) return;
    cmdInFlight = true;
    try {
      const out = await API.http.chartCommands({ status: 'pending' });
      for (const cmd of ((out && out.commands) || [])) {
        // Scheduled commands ("через минуту") stay pending until due.
        if (cmd.due_at_utc && Date.parse(cmd.due_at_utc) > Date.now() + 400) continue;
        let result = { ok: false }, status = 'done';
        try { result = await applyChartCommand(cmd); if (!result || result.ok === false) status = 'failed'; }
        catch (e) { result = { ok: false, error: String((e && e.message) || e) }; status = 'failed'; }
        try { await API.http.ackChartCommand(cmd.id, status, result); } catch (e) { /* retry next tick */ }
      }
    } catch (e) { /* transient */ }
    finally { cmdInFlight = false; }
  }, 2000);

  // ---- proportional chart grids ----------------------------------------
  function openGridMenu(anchor) {
    UI.menu(anchor, GRID_COUNTS.map(count => ({
      icon: 'grid', label: `${count} ${count === 1 ? 'график' : count < 5 ? 'графика' : 'графиков'}`,
      onClick: () => applyGrid(count),
    })));
  }

  // ---- snapshot gallery (Иван's captures + saved patterns) --------------
  function fmtSnapTime(iso) {
    try {
      return new Intl.DateTimeFormat('ru-RU', { timeZone: 'America/Los_Angeles',
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(iso));
    } catch (e) { return String(iso || '').slice(0, 16); }
  }
  async function openGallery() {
    const d = UI.drawer('Снимки графиков — Иван', `<div class="snap-gallery-wrap">
      <div class="snap-gallery-bar">
        <select id="snap-pattern"><option value="">Все снимки</option></select>
        <label class="snap-fav-toggle"><input type="checkbox" id="snap-fav-only"><span>Только избранное</span></label>
        <div class="spacer"></div>
        <button class="btn sm" id="snap-refresh">Обновить</button>
        <button class="btn sm danger" id="snap-clear">Очистить список</button>
      </div>
      <div class="snap-grid" id="snap-grid"><div class="empty-state">Загрузка…</div></div>
      <div class="dchart-hint" style="margin-top:12px">Избранные снимки (★) не удаляются при очистке. Присвойте паттерн (🏷), например «голова и плечи» — снимки сгруппируются для анализа. Файлы лежат в data/runtime/snapshots.</div>
    </div>`);
    d.classList.add('wide');
    const grid = qs('#snap-grid', d), patternSel = qs('#snap-pattern', d), favOnly = qs('#snap-fav-only', d);
    async function reload() {
      grid.innerHTML = '<div class="empty-state">Загрузка…</div>';
      let data;
      try { data = await API.http.snapshots({ pattern: patternSel.value || undefined, favorites: favOnly.checked ? 1 : undefined }); }
      catch (e) { grid.innerHTML = '<div class="empty-state">Не удалось загрузить снимки.</div>'; return; }
      const items = (data && data.snapshots) || [];
      const patterns = (data && data.patterns) || [];
      const cur = patternSel.value;
      patternSel.innerHTML = '<option value="">Все снимки</option>' +
        patterns.map(p => `<option value="${escAttr(p.name)}" ${p.name === cur ? 'selected' : ''}>${escAttr(p.name)} · ${p.count}</option>`).join('');
      grid.innerHTML = items.length ? items.map(s => `
        <div class="snap-card ${s.favorite ? 'fav' : ''}" data-id="${escAttr(s.id)}">
          <a href="${escAttr(s.url)}" target="_blank" rel="noopener"><img loading="lazy" src="${escAttr(s.url)}" alt=""></a>
          <div class="snap-meta"><b>${escAttr(s.instrument || '—')}</b> · ${escAttr(s.timeframe || '')} <span>${fmtSnapTime(s.created_at_utc)}</span>${s.pattern ? `<span class="snap-tag">${escAttr(s.pattern)}</span>` : ''}</div>
          <div class="snap-actions">
            <button data-snap-fav title="В избранное">${s.favorite ? '★' : '☆'}</button>
            <button data-snap-pattern title="Паттерн">🏷</button>
            <button data-snap-del title="Удалить">🗑</button>
          </div>
        </div>`).join('') : '<div class="empty-state">Пока нет снимков. Попросите Ивана: «сделай снимок MNQ».</div>';
    }
    grid.addEventListener('click', async (e) => {
      const card = e.target.closest('.snap-card'); if (!card) return;
      const id = card.dataset.id;
      if (e.target.closest('[data-snap-fav]')) {
        const on = !card.classList.contains('fav');
        try { await API.http.updateSnapshot({ id, favorite: on }); } catch (er) {}
        reload();
      } else if (e.target.closest('[data-snap-pattern]')) {
        const name = prompt('Название паттерна (например «голова и плечи»):', '');
        if (name == null) return;
        try { await API.http.updateSnapshot({ id, pattern: name.trim() }); } catch (er) {}
        reload();
      } else if (e.target.closest('[data-snap-del]')) {
        if (!confirm('Удалить этот снимок?')) return;
        try { await API.http.deleteSnapshot(id); } catch (er) {}
        reload();
      }
    });
    patternSel.addEventListener('change', reload);
    favOnly.addEventListener('change', reload);
    qs('#snap-refresh', d).addEventListener('click', reload);
    qs('#snap-clear', d).addEventListener('click', async () => {
      if (!confirm('Очистить все снимки, кроме избранных?')) return;
      try { await API.http.clearSnapshots(true); toast('Список снимков очищен'); } catch (e) {}
      reload();
    });
    reload();
  }

  async function applyGrid(count) {
    const list = (await NTData.instruments()).filter(item => item.available && item.symbol);
    if (!list.length) { toast('Список актуальных инструментов пока недоступен'); return; }
    // Grids fill the actual screen: switch to screen-fit so N charts tile the
    // whole visible area (and the whole monitor in fullscreen), no letterboxing.
    layout.screenFit = true;
    layout.grid = count;
    applyCanvas();

    while (layout.windows.length > count) {
      const model = layout.windows.pop(); deleteModelAlerts(model);
      const rec = wins.get(model.id); if (rec) { rec.chart.destroy(); rec.node.remove(); wins.delete(model.id); }
    }
    const shuffled = list.slice().sort(() => Math.random() - 0.5);
    bulkMounting = true;
    try {
      while (layout.windows.length < count) {
        const item = shuffled[layout.windows.length % shuffled.length];
        const cfg = { instrument: item.symbol, root: item.root, timeframe: '5m', indicators: [], type: 'candles',
          range: { id: count >= 12 ? '1d' : '1m', days: count >= 12 ? 1 : 31, from: '', to: '' }, style: Object.assign({}, DEFAULT_STYLE) };
        layout.seq = (layout.seq || 0) + 1;
        const model = { id: 'c' + Date.now() + '_' + layout.seq, x: 0, y: 0, w: 640, h: 420,
          z: 10, minimized: false, maximized: false, pinned: false, bare: false, config: cfg, drawings: [] };
        layout.windows.push(model); createWindow(model);
      }
    } finally { bulkMounting = false; }

    retileGrid();
    wins.forEach(rec => { rec.nextPollAt = 0; if (rec.chart) rec.chart.resize(); });
    viewport.scrollLeft = 0; viewport.scrollTop = 0;
    renderDock(); refreshEmpty(); markDirty();
    toast(`Сетка на весь экран: ${count} ${count === 1 ? 'график' : count < 5 ? 'графика' : 'графиков'}`);
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
    layout.windows.forEach(deleteModelAlerts);
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
    resSel.value = layout.screenFit ? 'screen'
      : ((RESOLUTIONS.find(r => r.w === layout.resolution.w && r.h === layout.resolution.h) || {}).id || '');
    applyCanvas();
    canvas.innerHTML = '';
    zTop = 10;
    bulkMounting = true;
    try {
      layout.windows.slice().sort((a, b) => (a.z || 0) - (b.z || 0)).forEach(m => { clampModel(m); createWindow(m); });
    } finally { bulkMounting = false; }
    wins.forEach(rec => { rec.nextPollAt = 0; });
    if (layout.screenFit && layout.grid) retileGrid();
    viewport.scrollLeft = (layout.scroll && layout.scroll.x) || 0;
    viewport.scrollTop = (layout.scroll && layout.scroll.y) || 0;
    renderDock();
    refreshEmpty();
    requestAnimationFrame(() => wins.forEach(rec => rec.chart && rec.chart.resize()));
  }

  // ---- toolbar wiring ----------------------------------------------------
  resSel.innerHTML = RESOLUTIONS.map(r => `<option value="${r.id}">${r.label}</option>`).join('');
  qs('#dsk-add').addEventListener('click', () => openChartDialog(null));
  qs('#dsk-empty-add').addEventListener('click', () => openChartDialog(null));
  qs('#dsk-layouts').addEventListener('click', (e) => { e.stopPropagation(); openLayoutsMenu(e.currentTarget); });
  qs('#dsk-grid').addEventListener('click', (e) => { e.stopPropagation(); openGridMenu(e.currentTarget); });
  const galleryBtn = qs('#dsk-gallery'); if (galleryBtn) galleryBtn.addEventListener('click', openGallery);
  qs('#dsk-save').addEventListener('click', () => { persistNow(); toast('Рабочий стол сохранён'); });
  qs('#dsk-clear').addEventListener('click', () => {
    if (!layout.windows.length) return;
    if (!confirm('Убрать все графики с этого рабочего стола?')) return;
    layout.windows.forEach(deleteModelAlerts);
    teardownWindows();
    layout.windows = [];
    renderDock(); refreshEmpty(); persistNow();
  });
  resSel.addEventListener('change', () => setResolution(resSel.value));
  qs('#dsk-zoom-in').addEventListener('click', () => setZoom(layout.zoom * 1.2));
  qs('#dsk-zoom-out').addEventListener('click', () => setZoom(layout.zoom / 1.2));
  qs('#dsk-zoom-fit').addEventListener('click', fitZoom);
  zoomVal.addEventListener('click', () => setZoom(1));

  const focusBtn = qs('#dsk-focus');
  const focusExit = qs('#dsk-focus-exit');
  const focusRoot = dsk.closest('.main') || dsk;
  // After the viewport size changes (fullscreen enter/exit): screen-fit layouts
  // re-fill the whole area; fixed-resolution layouts fit-to-view like before.
  function afterViewportChange() { if (layout.screenFit) relayoutViewport(); else fitZoom(); }
  async function enterFocus() {
    dsk.classList.add('focus-mode'); focusRoot.classList.add('workspace-focus');
    try {
      if (focusRoot.requestFullscreen && document.fullscreenElement !== focusRoot) await focusRoot.requestFullscreen();
      else if (!focusRoot.requestFullscreen) document.body.classList.add('dsk-focus-fallback');
    } catch (e) { document.body.classList.add('dsk-focus-fallback'); }
    requestAnimationFrame(() => requestAnimationFrame(afterViewportChange));
  }
  async function leaveFocus() {
    if (document.fullscreenElement && document.exitFullscreen) {
      try { await document.exitFullscreen(); } catch (e) { /* fallback below */ }
    }
    dsk.classList.remove('focus-mode'); focusRoot.classList.remove('workspace-focus');
    document.body.classList.remove('dsk-focus-fallback');
    requestAnimationFrame(() => requestAnimationFrame(afterViewportChange));
  }
  focusBtn.addEventListener('click', enterFocus);
  focusExit.addEventListener('click', leaveFocus);
  document.addEventListener('fullscreenchange', () => {
    if (document.fullscreenElement === focusRoot) { requestAnimationFrame(() => requestAnimationFrame(afterViewportChange)); return; }
    dsk.classList.remove('focus-mode'); focusRoot.classList.remove('workspace-focus');
    document.body.classList.remove('dsk-focus-fallback');
    requestAnimationFrame(() => requestAnimationFrame(afterViewportChange));
  });

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
  let resizeRaf = null;
  window.addEventListener('resize', () => {
    if (resizeRaf) cancelAnimationFrame(resizeRaf);
    resizeRaf = requestAnimationFrame(relayoutViewport);
  });

  // ---- helpers -----------------------------------------------------------
  function escAttr(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch])); }

  // close any open in-chart tool menu / side panel when clicking elsewhere
  document.addEventListener('pointerdown', (e) => {
    qsaLocal('.dwin-tools.open', canvas).forEach(w => { if (!w.contains(e.target)) { w.classList.remove('open'); const m = qs('.dwin-tools-menu', w); if (m) m.classList.remove('open'); } });
    qsaLocal('.dwin-side.open', canvas).forEach(s => { if (!s.contains(e.target)) s.classList.remove('open'); });
  }, true);

  // ---- boot --------------------------------------------------------------
  // Clear the daily rollover cache key so the contract-refresh always runs
  // against the live server on a fresh page load (the server itself is the
  // authoritative source; caching one whole day is too coarse for expiry events).
  try { localStorage.removeItem('desktop.contract-refresh-day'); } catch (e) { /* ignore */ }
  mountLayout();
  refreshContractsIfDue();
});
