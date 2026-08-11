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
  const TIMEFRAMES = ['1m', '3m', '5m', '15m', '30m', '1h', '4h', '1D', '1w', '1M'];
  const INDICATORS = [
    { id: 'vol', label: 'Объём', kind: 'pane' },
    { id: 'ma:9', label: 'MA 9', kind: 'overlay' },
    { id: 'ma:20', label: 'MA 20', kind: 'overlay' },
    { id: 'ema:21', label: 'EMA 21', kind: 'overlay' },
    { id: 'ema:50', label: 'EMA 50', kind: 'overlay' },
    { id: 'hma:21', label: 'HMA 21', kind: 'overlay' },
    { id: 'hma:55', label: 'HMA 55', kind: 'overlay' },
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
  const MIN_W = 260, MIN_H = 180;
  const ZOOM_MIN = 0.05, ZOOM_MAX = 2;
  const LIVE_POLL_MS = 350;
  const HEALTH_POLL_MS = 5000;
  function mergeFormingLiveBar(existing, incoming) {
    if (!existing || !incoming) return incoming;
    const existingMs = Date.parse(existing.t || existing.time_utc || existing.time || existing.timestamp);
    const incomingMs = Date.parse(incoming.t || incoming.time_utc || incoming.time || incoming.timestamp);
    if (!Number.isFinite(existingMs) || existingMs !== incomingMs) return incoming;
    const o = Number(existing.o), h = Number(existing.h), l = Number(existing.l);
    const nextH = Number(incoming.h), nextL = Number(incoming.l);
    const existingV = Number(existing.v || 0), incomingV = Number(incoming.v || 0);
    return Object.assign({}, incoming, {
      o: Number.isFinite(o) ? o : Number(incoming.o),
      h: Math.max(Number.isFinite(h) ? h : nextH, nextH),
      l: Math.min(Number.isFinite(l) ? l : nextL, nextL),
      c: Number(incoming.c),
      v: Math.max(Number.isFinite(existingV) ? existingV : 0, Number.isFinite(incomingV) ? incomingV : 0),
    });
  }
  const protocol = (window.location && window.location.protocol === 'https:') ? 'wss:' : 'ws:';
  const MARKET_DATA_WS_URL = (window.location && window.location.host)
    ? `${protocol}//${window.location.host}/ws/market-data`
    : '';
  let marketDataWs = null;
  let marketDataWsOk = false;
  let marketDataWsRetryAt = 0;
  let marketDataWsBackoff = 1000;
  let marketDataWsState = 'OFF';
  function sendMarketDataSubscription(type, instrument, timeframe) {
    const contract = String(instrument || '').trim().toUpperCase();
    const tf = String(timeframe || '5m').trim();
    if (!contract || !marketDataWs || marketDataWs.readyState !== WebSocket.OPEN) return;
    try { marketDataWs.send(JSON.stringify({ type, exact_contract: contract, timeframe: tf })); } catch (e) { /* reconnect/poll fallback */ }
  }
  // A large saved desktop can mount dozens of charts.  Start visible data in a
  // small bounded queue and keep deep-history requests even narrower.
  const INITIAL_LOAD_CONCURRENCY = 4;
  const HISTORY_LOAD_CONCURRENCY = 2;
  const initialLoadQueue = [];
  const historyLoadQueue = [];
  let initialLoadsActive = 0;
  let historyLoadsActive = 0;

  function ensureMarketDataWs() {
    if (!MARKET_DATA_WS_URL || typeof WebSocket === 'undefined') return;
    if (marketDataWs && (marketDataWs.readyState === 0 || marketDataWs.readyState === 1)) return;
    if (Date.now() < marketDataWsRetryAt) return;
    try {
      marketDataWsState = 'CONNECTING';
      const ws = new WebSocket(MARKET_DATA_WS_URL);
      marketDataWs = ws;
      ws.addEventListener('open', () => {
        marketDataWsOk = true;
        marketDataWsState = 'CONNECTED';
        marketDataWsBackoff = 1000;
        for (const rec of wins.values()) {
          const instrument = String((rec.model.config && rec.model.config.instrument) || '');
          const timeframe = String((rec.model.config && rec.model.config.timeframe) || '5m');
          if (!instrument) continue;
          sendMarketDataSubscription('subscribe', instrument, timeframe);
        }
      });
      ws.addEventListener('message', (ev) => {
        let msg = null;
        try { msg = JSON.parse(ev.data); } catch (e) { return; }
        if (!msg || !msg.type) return;
        if (msg.type === 'welcome' || msg.type === 'subscribe_ack') {
          marketDataWsOk = true;
          marketDataWsState = 'CONNECTED';
          return;
        }
        if (msg.type !== 'market_event') return;
        const updates = Array.isArray(msg.bar_updates) ? msg.bar_updates : [];
        const sources = msg.sources || {};
        for (const rec of wins.values()) {
          if (rec.model.minimized || !rec.chart) continue;
          const instrument = String((rec.model.config && rec.model.config.instrument) || '').toUpperCase();
          const tf = String((rec.model.config && rec.model.config.timeframe) || '').toLowerCase();
          let touched = false;
          for (const upd of updates) {
            const bar = upd && (upd.bar || upd);
            if (!bar) continue;
            if (String(bar.exact_contract || '').toUpperCase() !== instrument) continue;
            const barTf = String(bar.timeframe || '').toLowerCase();
            if (barTf && barTf !== tf && tf !== '1d') continue;
            touched = true;
            try {
              // ChartEngine's public live API is appendBar(). It replaces the
              // final bar when the timestamp is unchanged and appends at a
              // period boundary. Older desktop code called a non-existent
              // updateLastBar(), silently discarding every valid WS update.
              const chartRows = rec.chart.getData ? rec.chart.getData() : [];
              const existingBar = chartRows.length ? chartRows[chartRows.length - 1] : null;
              const liveBar = mergeFormingLiveBar(existingBar, bar);
              if (typeof rec.chart.updateLastBar === 'function') rec.chart.updateLastBar(liveBar);
              else if (typeof rec.chart.appendBar === 'function') rec.chart.appendBar(liveBar);
              rec.liveBar = liveBar;
              rec.liveBarAt = Date.now();
              rec.liveBarProvider = String(liveBar.provider || sources.chart_source || '').toLowerCase();
              rec.historyBars = mergeChartBars(rec.historyBars, [liveBar]);
            } catch (e) { /* poll fallback */ }
          }
          // A provider label alone is not a tick for every chart.  Mark only
          // the matching visible contract LIVE; otherwise a busy MNQ stream
          // could incorrectly revive an unrelated stale window.
          if (touched) {
            const src = sources.chart_source || 'ninjatrader';
            // WS ticks only mark LIVE when document is not in offline mode.
            if (document.documentElement.dataset.mdOffline === '1') {
              if (rec.chart.setLivePriceEnabled) rec.chart.setLivePriceEnabled(false);
              setSrc(rec, 'err', `OFFLINE · ${src} · ${instrument} · WS blocked`);
            } else {
              // A matching market event proves that this chart's feed is live.
              // HTTP health polling may have muted the price marker earlier;
              // restore its red/green semantics on the same event that updates
              // the forming candle instead of leaving a live quote grey.
              if (rec.chart.setLivePriceEnabled) rec.chart.setLivePriceEnabled(true);
              setSrc(rec, 'live', `LIVE · ${src} · ${instrument} · WS · age now`);
              rec._transport = 'WS';
              rec.nextPollAt = Date.now() + HEALTH_POLL_MS;
            }
          }
        }
      });
      ws.addEventListener('close', () => {
        marketDataWsOk = false;
        marketDataWsState = 'RECONNECTING';
        marketDataWs = null;
        marketDataWsRetryAt = Date.now() + marketDataWsBackoff;
        marketDataWsBackoff = Math.min(15000, Math.round(marketDataWsBackoff * 1.7 + Math.random() * 300));
      });
      ws.addEventListener('error', () => {
        marketDataWsOk = false;
        marketDataWsState = 'ERROR';
        try { ws.close(); } catch (e) { /* ignore */ }
      });
    } catch (e) {
      marketDataWsRetryAt = Date.now() + marketDataWsBackoff;
      marketDataWsBackoff = Math.min(15000, marketDataWsBackoff * 2);
    }
  }

  // Global chart template helpers live in desktop-template.js (pure, testable).
  const DT = window.DesktopTemplate;
  if (!DT) { toast('Не загружен модуль макета графика'); return; }
  const DEFAULT_STYLE = DT.DEFAULT_STYLE;
  const cloneStyle = DT.cloneStyle;
  const makeTemplateFromConfig = DT.makeTemplateFromConfig;
  const applyTemplateToConfig = DT.applyTemplateToConfig;
  function loadTemplate() { return DT.loadTemplate(); }
  function saveTemplate(t) { return DT.saveTemplate(t); }

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
      trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 15h10l1-15"/><path d="M10 11v6M14 11v6"/>',
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
  let template = loadTemplate();
  const wins = new Map();     // id → { model, node, chart, chartHost, refresh }
  let zTop = 10;
  let instrumentCache = null;
  let agentCache = null;
  let persistTimer = null;
  let bulkMounting = false;
  let drawingClipboard = null;

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
      if (l.gridMode !== 'instruments') l.gridMode = 'free';
      if (!Array.isArray(l.gridRoots)) l.gridRoots = [];
      if (typeof l.gridTimeframe !== 'string') l.gridTimeframe = '5m';
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
        // Older desktop versions only offered the current contract picker, so
        // their saved layouts are root-managed by definition. New/edited
        // charts may opt into ``fixed`` to preserve a chosen historical expiry.
        if (m.config.contract_mode !== 'fixed') m.config.contract_mode = 'auto';
        if (!Array.isArray(m.drawings)) m.drawings = [];
        if (typeof m.bare !== 'boolean') m.bare = false;
      });
    });
    if (!Array.isArray(raw.order)) raw.order = Object.keys(raw.layouts);
    return raw;
  }
  function newLayout(id, name) {
    return { id, name, resolution: { w: 1920, h: 1080 }, zoom: 1, screenFit: true, grid: 0,
      gridMode: 'free', gridRoots: [], gridTimeframe: '5m',
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
          <button class="clear-drawings" data-act="clear-drawings" title="Очистить все рисунки">${wIcon('trash')}</button>
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
    // Persist pane heights and price-axis width immediately when the drag ends.
    chart.on('viewport', (vp) => {
      if (vp && vp.paneHeights) { model.config.paneHeights = vp.paneHeights; markDirty(); }
      if (vp && vp.axisWidth != null) {
        model.config.style = Object.assign({}, model.config.style || {}, { axisWidth: vp.axisWidth });
        markDirty();
      }
      queueHistoryPrefetch(rec, vp);
    });

    const rec = { model, node, chart, chartHost, srcEl: qs('.dwin-src', node), inFlight: false,
      historyBars: [], historySignature: '', historyExhausted: false, historyInFlight: false,
      historyController: null, historyPrefetchTimer: null, historySourceIdentity: '',
      viewportPriority: 0, offscreenSince: 0, liveBar: null, liveBarAt: 0, liveBarProvider: '' };
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
        layout.grid = 0; layout.gridMode = 'free';
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
          layout.grid = 0; layout.gridMode = 'free';
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
      else if (act === 'clear-drawings') clearWindowDrawings(rec);
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
  // Low-level teardown of a single window (no grid bookkeeping / no confirm).
  function destroyWindow(model) {
    deleteModelAlerts(model);
    const rec = wins.get(model.id);
    if (rec) {
      sendMarketDataSubscription('unsubscribe', rec.model.config && rec.model.config.instrument,
        rec.model.config && rec.model.config.timeframe);
      if (rec.chart) rec.chart.destroy();
      if (rec.refreshStop) rec.refreshStop();
      rec.node.remove();
      wins.delete(model.id);
    }
    layout.windows = layout.windows.filter(m => m.id !== model.id);
  }

  function closeWindow(rec) {
    const root = modelRoot(rec.model);
    destroyWindow(rec.model);
    // In an instrument grid, dropping one chart re-tiles the rest evenly; in
    // free mode we just clear the grid marker so windows keep their positions.
    if (layout.gridMode === 'instruments') {
      layout.gridRoots = (layout.gridRoots || []).filter(r => r !== root);
      if (layout.windows.length) { layout.grid = layout.windows.length; retileGrid(); }
      else { layout.grid = 0; layout.gridMode = 'free'; }
    } else {
      layout.grid = 0;
    }
    renderDock();
    refreshEmpty();
    markDirty();
  }

  function clearWindowDrawings(rec) {
    const count = (rec.model.drawings || []).length;
    if (!count) { toast('На графике нет рисунков'); return; }
    deleteModelAlerts(rec.model);
    rec.model.drawings = [];
    if (rec.chart) { rec.chart.setDrawings([]); rec.chart.selectDrawing(null); }
    const editor = qs('.dwin-drawing-editor', rec.node);
    if (editor) { editor.classList.remove('show', 'collapsed'); editor.innerHTML = ''; }
    markDirty();
    toast('Все рисунки на графике очищены');
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
          const contracts = Array.isArray(r.contracts) ? r.contracts.map(c => ({
            instrument: String((c && (c.instrument || c.symbol || c.name)) || ''),
            expiry: String((c && c.expiry) || ''),
          })).filter(c => c.instrument) : [];
          return { root: r.root, symbol: fm.instrument || r.root, label: r.root, contract: fm.instrument || r.root,
            name: info.name, group: info.group, expiry: fm.expiry || '', available: !!fm.instrument, contracts };
        });
        instrumentCache = list;
        return list;
      } catch (e) { instrumentCache = null; return []; }
    },
    async bars(instrument, timeframe, opts) {
      opts = opts || {};
      try {
        const q = opts.query || marketRequest(opts.config || { instrument, timeframe }, opts.limit, opts.maxPoints);
        const res = await window.API.http.marketBars(q, { signal: opts.signal });
        return {
          bars: Array.isArray(res && res.bars) ? res.bars : [],
          note: (res && res.note) || '',
          source: (res && res.source) || null,
          live: !!(res && res.live),
          status: (res && res.status) || '',
          alerts: Array.isArray(res && res.alerts) ? res.alerts : [],
          history: (res && res.history) || {},
          resolvedInstrument: (res && res.resolved_instrument) || '',
        };
      } catch (e) {
        return { bars: [], note: (e && e.message) || 'нет соединения', source: null, live: false, status: 'error', alerts: [], history: {} };
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
      if (model.config.contract_mode === 'fixed') continue;
      const root = model.config.root || String(model.config.instrument || '').split(' ')[0];
      const current = byRoot.get(root);
      if (!current || !current.symbol || current.symbol === model.config.instrument) continue;
      model.config.root = root; model.config.instrument = current.symbol;
      rolled++;
      const rec = wins.get(model.id);
      if (rec) { renderWindowMeta(rec); rec.hasBars = false; rec.nextPollAt = 0; resetDataTracking(rec); loadWindowData(rec); }
      for (const drawing of (model.drawings || [])) if (drawing.ruleAction && drawing.ruleAction !== 'none' && rec) syncDrawingRule(rec, drawing, true);
      markDirty();
    }
    if (rolled) toast(`Rollover: обновлено ${rolled} ${rolled === 1 ? 'контракт' : 'контракта'} до актуального фронт-мансяца`);
  }

  function chartMaxPoints(rec) {
    const box = rec && rec.node ? rec.node.getBoundingClientRect() : null;
    const width = box && Number.isFinite(box.width) ? box.width : 1200;
    return Math.max(800, Math.min(8000, Math.ceil(width * 3)));
  }

  function marketRequest(config, forcedLimit, maxPoints, historyRange) {
    const range = config.range || { days: 31 };
    let days = Number(range.days || 0);
    if (range.id === 'custom' && range.from && range.to) {
      days = Math.max(1, Math.ceil((Date.parse(range.to) - Date.parse(range.from)) / 86400000) + 1);
    }
    const tf = String(config.timeframe || '5m');
    let perDay = tf === '1D' ? 1 : (tf === '1w' || tf === '1W') ? 1 / 7 : tf === '1M' ? 1 / 31 : tf.endsWith('h') ? 24 / Math.max(1, Number(tf.slice(0, -1))) :
      1440 / Math.max(1, Number(tf.slice(0, -1)) || 5);
    // First paint is deliberately bounded. Older history is fetched only as
    // the viewport approaches its left edge, rather than downloading years of
    // candles before the user can see a chart.
    const limit = forcedLimit || Math.max(800, Math.min(2500, Math.ceil(Math.max(1, perDay) * 2)));
    const points = Math.max(0, Math.min(20000, Number(maxPoints || 0)));
    return { instrument: config.contract_mode === 'auto' ? (config.root || config.instrument) : config.instrument,
      timeframe: config.timeframe, limit,
      range_days: range.id === 'custom' ? 0 : 0, from: range.from || '', to: range.to || '',
      from_ts: historyRange && historyRange.from_ts || '', to_ts: historyRange && historyRange.to_ts || '',
      max_points: points };
  }

  function dataSignature(config) {
    config = config || {};
    const range = config.range || {};
    return [config.instrument || '', config.timeframe || '', range.id || '', range.days || '', range.from || '', range.to || ''].join('|');
  }

  function beginDataRequest(rec) {
    const stamp = { seq: (rec.dataSeq || 0) + 1, sig: dataSignature(rec.model.config) };
    rec.dataSeq = stamp.seq;
    rec.inFlight = true;
    return stamp;
  }

  function requestStillCurrent(rec, stamp) {
    return !!(rec && stamp && wins.has(rec.model.id) && rec.dataSeq === stamp.seq && dataSignature(rec.model.config) === stamp.sig);
  }

  function finishDataRequest(rec, stamp) {
    if (rec && stamp && rec.dataSeq === stamp.seq) rec.inFlight = false;
  }

  function resetDataTracking(rec) {
    if (!rec) return;
    if (rec.historyController) { try { rec.historyController.abort(); } catch (e) {} }
    rec.historyController = null;
    rec.historyQueued = false;
    rec.loadQueued = false;
    rec.historyBars = [];
    rec.historySignature = '';
    rec.historySourceIdentity = '';
    rec.historyExhausted = false;
    rec.historyInFlight = false;
    rec.lastUpdated = '';
    rec.lastBarMs = null;
    rec.lastStatus = '';
    rec.rejectedPayloads = 0;
    rec.liveBar = null;
    rec.liveBarAt = 0;
    rec.liveBarProvider = '';
  }

  function mergeChartBars(left, right) {
    const rows = new Map();
    (Array.isArray(left) ? left : []).concat(Array.isArray(right) ? right : []).forEach((bar) => {
      const stamp = Date.parse(bar && (bar.t || bar.time_utc || bar.time || bar.timestamp));
      if (Number.isFinite(stamp)) rows.set(stamp, bar);
    });
    return Array.from(rows.entries()).sort((a, b) => a[0] - b[0]).map(row => row[1]);
  }

  function timeframeMs(timeframe) {
    const match = String(timeframe || '1m').match(/^(\d+)([smhdwM])$/);
    if (!match) return 60000;
    const units = { s: 1000, m: 60000, h: 3600000, d: 86400000, w: 604800000, M: 2678400000 };
    return Math.max(1, Number(match[1])) * units[match[2]];
  }

  function queueHistoryPrefetch(rec, vp) {
    if (!rec || rec.historyInFlight || rec.historyExhausted || !rec.historyBars || !rec.historyBars.length) return;
    const start = Number(vp && vp.start);
    const count = Number(vp && vp.count) || 120;
    if (!Number.isFinite(start) || start > Math.max(32, Math.ceil(count * 0.45))) return;
    if (rec.historyPrefetchTimer) clearTimeout(rec.historyPrefetchTimer);
    rec.historyPrefetchTimer = setTimeout(() => loadOlderHistory(rec), 80);
  }

  function loadOlderHistory(rec) {
    if (!rec || rec.historyQueued || rec.historyInFlight || rec.historyExhausted) return;
    rec.historyQueued = true;
    historyLoadQueue.push(rec);
    drainHistoryLoadQueue();
  }

  function drainHistoryLoadQueue() {
    while (historyLoadsActive < HISTORY_LOAD_CONCURRENCY && historyLoadQueue.length) {
      const rec = historyLoadQueue.shift();
      if (!rec || !wins.has(rec.model.id)) continue;
      rec.historyQueued = false;
      historyLoadsActive += 1;
      loadOlderHistoryNow(rec).finally(() => {
        historyLoadsActive -= 1;
        drainHistoryLoadQueue();
      });
    }
  }

  async function loadOlderHistoryNow(rec) {
    if (!rec || rec.historyInFlight || rec.historyExhausted || !rec.historyBars || !rec.historyBars.length) return;
    const sig = dataSignature(rec.model.config);
    const earliest = Date.parse(rec.historyBars[0] && (rec.historyBars[0].t || rec.historyBars[0].time));
    if (!Number.isFinite(earliest)) return;
    const count = Math.max(1000, Math.min(20000, Math.max(chartMaxPoints(rec), rec.chart && rec.chart.view && rec.chart.view.count || 120) * 2));
    const end = new Date(earliest).toISOString();
    const start = new Date(earliest - timeframeMs(rec.model.config.timeframe) * count * 1.15).toISOString();
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    rec.historyController = controller;
    rec.historyInFlight = true;
    setSrc(rec, 'wait', `DATA · ${String(rec.historySourceIdentity || 'TopstepX').split('|')[0]} · подгружаю более раннюю историю…`);
    try {
      const q = marketRequest(rec.model.config, count, 0, { from_ts: start, to_ts: end });
      const payload = await NTData.bars(rec.model.config.instrument, rec.model.config.timeframe, {
        config: rec.model.config, query: q,
        signal: controller && controller.signal,
      });
      if (!wins.has(rec.model.id) || dataSignature(rec.model.config) !== sig) return;
      if (!payload.bars || !payload.bars.length || (payload.history && payload.history.exhausted)) {
        rec.historyExhausted = true;
        setSrc(rec, 'wait', `DATA · ${String(rec.historySourceIdentity || 'TopstepX').split('|')[0]} · доступная история этого контракта исчерпана`);
      } else {
        applyWindowPayload(rec, payload);
      }
    } catch (e) {
      if (!(e && e.name === 'AbortError')) setSrc(rec, 'wait', `DATA · ${String(rec.historySourceIdentity || 'TopstepX').split('|')[0]} · история временно недоступна; повторим при прокрутке`);
    } finally {
      if (rec.historyController === controller) rec.historyController = null;
      rec.historyInFlight = false;
    }
  }

  function payloadLastBarMs(bars) {
    const last = Array.isArray(bars) && bars.length ? bars[bars.length - 1] : null;
    const raw = last && (last.t || last.time_utc || last.time || last.timestamp);
    const ms = Date.parse(raw || '');
    return Number.isFinite(ms) ? ms : null;
  }

  function sourceAgeSec(source) {
    const age = Number(source && source.age_sec);
    return Number.isFinite(age) ? age : null;
  }

  function ageText(age) {
    if (!Number.isFinite(age)) return '';
    if (age < 1) return 'сейчас';
    if (age < 60) return `${Math.round(age)}с назад`;
    return `${Math.round(age / 60)}м назад`;
  }

  function loadWindowData(rec) {
    if (!rec || rec.loadQueued || rec.inFlight || rec.model.minimized) return;
    rec.loadQueued = true;
    initialLoadQueue.push(rec);
    drainInitialLoadQueue();
  }

  function drainInitialLoadQueue() {
    while (initialLoadsActive < INITIAL_LOAD_CONCURRENCY && initialLoadQueue.length) {
      const rec = initialLoadQueue.shift();
      if (!rec || !wins.has(rec.model.id)) continue;
      rec.loadQueued = false;
      initialLoadsActive += 1;
      loadWindowDataNow(rec).catch((e) => {
        if (wins.has(rec.model.id)) setSrc(rec, 'err', 'Ошибка потока данных: ' + (e.message || e));
      }).finally(() => {
        initialLoadsActive -= 1;
        drainInitialLoadQueue();
      });
    }
  }

  async function loadWindowDataNow(rec) {
    const m = rec.model;
    if (m.minimized) return;
    if (rec.inFlight) return;
    const stamp = beginDataRequest(rec);
    setSrc(rec, 'wait', 'DATA · загружаю актуальные бары…');
    const payload = await NTData.bars(m.config.instrument, m.config.timeframe, {
      signal: UI.signal(), config: m.config, maxPoints: chartMaxPoints(rec),
    });
    finishDataRequest(rec, stamp);
    if (!requestStillCurrent(rec, stamp)) return;
    applyWindowPayload(rec, payload);
  }

  function applyWindowPayload(rec, payload) {
    payload = payload || {};
    const bars = Array.isArray(payload.bars) ? payload.bars : [];
    const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
    const note = payload.note || '', live = !!payload.live, status = payload.status || '';
    const source = payload.source || {};
    const freshness = payload.freshness || {};
    const offline = status === 'offline' || !!freshness.offline || !!payload.offline_banner
      || String(source.runtime_state || '').toUpperCase() === 'OFFLINE';
    const chartSource = source.active || source.provider || source.kind || source.name || 'NO DATA';
    const topstepSource = String(chartSource || '').toLowerCase() === 'topstepx';
    // A forming 5m/1h bar naturally ages.  For TopstepX, liveness is instead
    // the current SignalR/quote transport state: a fresh bid/ask or heartbeat
    // remains LIVE even when GatewayQuote.lastPrice is unchanged for seconds.
    const marketFeedFresh = topstepSource
      ? freshness.market_feed_fresh === true
      : freshness.fresh === true;
    const marketFeedStale = topstepSource
      ? freshness.market_feed_stale === true
      : freshness.stale === true;
    const strategySource = payload.strategy_source || 'ninjatrader';
    const executionSource = payload.execution_source || 'ninjatrader';
    const planes = `Chart:${chartSource} · Strategy:${strategySource} · Execution:${executionSource}`;
    const resolvedByProvider = String(payload.resolvedInstrument || payload.resolved_instrument || '').trim();
    if (rec.model.config.contract_mode === 'auto' && resolvedByProvider
        && resolvedByProvider !== rec.model.config.instrument) {
      // The request used the root, and the provider returned the current exact
      // contract. Persist it for a truthful chart header while retaining the
      // root-managed mode for the next rollover.
      rec.model.config.instrument = resolvedByProvider;
      rec.model.config.root = String(rec.model.config.root || resolvedByProvider.split(' ')[0]).toUpperCase();
      rec.historyBars = [];
      rec.historySourceIdentity = '';
      rec.lastBarMs = null;
      rec.lastUpdated = '';
      rec.liveBar = null;
      rec.liveBarAt = 0;
      rec.liveBarProvider = '';
      if (rec.chart && rec.chart.setMeta) rec.chart.setMeta(rec.model.config.instrument, rec.model.config.timeframe);
      renderWindowMeta(rec);
      // The socket may have opened before the HTTP response resolved a root
      // symbol to its current exact expiry.  Subscribe the resolved contract
      // as well, otherwise the server correctly emits MNQ 09-26 updates but
      // this root-backed window remains filtered on its former MNQ request.
      sendMarketDataSubscription('subscribe', resolvedByProvider, rec.model.config.timeframe || '5m');
      markDirty();
    }
    const signature = dataSignature(rec.model.config);
    if (rec.historySignature !== signature) {
      rec.historySignature = signature;
      rec.historyBars = [];
      rec.historyExhausted = false;
    }
    const sourceIdentity = [chartSource, payload.resolved_instrument || '', payload.series_mode || 'contract'].join('|');
    if (rec.historySourceIdentity && rec.historySourceIdentity !== sourceIdentity) {
      // Never join different providers/contract modes into one rendered series.
      // A failover is a clean range replacement; the backend requests a fresh
      // normalized range from the new source, which also performs its gap fill.
      rec.historyBars = [];
      rec.lastBarMs = null;
      rec.lastUpdated = '';
      rec.liveBar = null;
      rec.liveBarAt = 0;
      rec.liveBarProvider = '';
    }
    rec.historySourceIdentity = sourceIdentity;
    updateGlobalOfflineBanner(payload, rec);
    if (bars.length) {
      let mergedBars = mergeChartBars(rec.historyBars, bars);
      const liveMs = rec.liveBar && Date.parse(rec.liveBar.t || rec.liveBar.time_utc || rec.liveBar.time || rec.liveBar.timestamp);
      const payloadMs = payloadLastBarMs(mergedBars);
      const liveFresh = rec.liveBar && Number.isFinite(liveMs) && Date.now() - Number(rec.liveBarAt || 0) <= 15000;
      const liveProviderCompatible = !rec.liveBarProvider
        || rec.liveBarProvider === String(chartSource || '').toLowerCase();
      // A health/history poll is allowed to fill gaps, but it must not roll a
      // fresher same-provider WebSocket forming bar backwards. A genuinely
      // newer HTTP bucket or provider switch remains authoritative.
      if (liveFresh && liveProviderCompatible && (payloadMs == null || liveMs >= payloadMs)) {
        mergedBars = mergeChartBars(mergedBars, [rec.liveBar]);
      }
      rec.historyBars = mergedBars;
      const lastMs = payloadLastBarMs(mergedBars);
      const staleBars = rec.lastBarMs != null && lastMs != null && lastMs < rec.lastBarMs - 1000;
      if (staleBars && !offline) {
        rec.rejectedPayloads = (rec.rejectedPayloads || 0) + 1;
        rec.nextPollAt = Date.now() + 500;
        setSrc(rec, 'wait', `RECOVERING · устаревший пакет · ${planes}`);
        return;
      }
      const updated = source.updated_at_utc || `${payload.status || ''}:${mergedBars.length}:${mergedBars[mergedBars.length - 1] && (mergedBars[mergedBars.length - 1].t || mergedBars[mergedBars.length - 1].c)}`;
      if (updated !== rec.lastUpdated || bars.length) {
        rec.chart.setData(mergedBars);
        rec.lastUpdated = updated;
      }
      if (lastMs != null) rec.lastBarMs = lastMs;
      rec.rejectedPayloads = 0;
      rec.hasBars = true;
      if (payload.history && payload.history.exhausted) rec.historyExhausted = true;
      const age = sourceAgeSec(source) != null ? sourceAgeSec(source) : Number(freshness.age_sec);
      const ageLabel = Number.isFinite(age) ? ` · age ${ageText(age)}` : '';
      const asOf = freshness.market_feed_as_of_utc || freshness.data_as_of_utc || source.updated_at_utc || '';
      const asOfLabel = asOf ? ` · last ${String(asOf).replace('T', ' ').slice(0, 19)}` : '';
      const diag = payload.diagnostics || {};
      const transport = marketDataWsOk ? 'WS' : 'HTTP';
      const hashShort = diag.series_hash ? String(diag.series_hash).slice(0, 8) : '';
      const contract = payload.resolvedInstrument || payload.resolved_instrument || (rec.model.config && rec.model.config.instrument) || '';
      const extra = hashShort ? ` · #${hashShort}` : '';
      let health = 'OFFLINE';
      let css = 'err';
      if (offline || payload.market_data_available === false) {
        health = 'OFFLINE';
        css = 'err';
      } else if (live && marketFeedFresh && !marketFeedStale) {
        health = 'LIVE';
        css = 'live';
      } else if (marketFeedStale || status === 'external_stale' || status === 'failover_stale' || status === 'stale') {
        health = 'STALE';
        css = 'wait';
      } else if (bars.length) {
        health = 'DEGRADED';
        css = 'wait';
      }
      // A 5m/1h candle timestamp naturally ages between ticks.  Its explicit
      // provider freshness limit (not an arbitrary UI-second threshold) is
      // authoritative for the price-line colour.
      if (css === 'live' && (live !== true || !marketFeedFresh)) {
        health = marketFeedStale ? 'STALE' : 'DEGRADED';
        css = 'wait';
      }
      const transition = source.failover_from ? ` · switched from ${source.failover_from}` : '';
      setSrc(rec, css, `${health} · DATA · ${chartSource} · ${contract} · ${transport}${transition}${ageLabel}${asOfLabel}${extra}${note ? ' · ' + note : ''}`);
      rec._diagnostics = diag;
      rec._transport = transport;
      // Freeze price marker semantics for offline/stale.
      if (rec.chart && rec.chart.setLivePriceEnabled) {
        try { rec.chart.setLivePriceEnabled(css === 'live'); } catch (e) { /* optional */ }
      }
    } else {
      if (!rec.hasBars) {
        if (rec.chart && rec.chart.setEmptyMessage) {
          rec.chart.setEmptyMessage(
            offline
              ? 'OFFLINE · нет данных в кэше · Live price unavailable'
              : 'Нет данных'
          );
        }
        rec.chart.setData([]);
      }
      const waitForever = status === 'waiting' || status === 'subscription_requested';
      if (offline || !waitForever) {
        setSrc(rec, 'err', `OFFLINE · ${planes}` + (note ? ' · ' + note : ''));
      } else {
        setSrc(rec, 'wait', `OFFLINE timeout · нет live-источника` + (note ? ' · ' + note : ''));
      }
    }
    rec.lastStatus = offline ? 'offline' : (status || (live ? 'live' : 'waiting'));
    rec.nextPollAt = Date.now() + (
      offline ? 15000
        : marketDataWsOk ? HEALTH_POLL_MS
          : (live ? Math.max(100, LIVE_POLL_MS - 50) : rec.lastStatus === 'historical_fallback' ? 10000 : 2000)
    );
    // Never leave infinite loaders when we already decided offline/stale/empty.
    if (rec.chart && rec.chart.setLoading) {
      rec.chart.setLoading(false);
    }
    if (rec.chart && rec.chart.getPaneHeights) {
      const ph = rec.chart.getPaneHeights();
      if (JSON.stringify(ph) !== JSON.stringify(rec.model.config.paneHeights || {})) {
        rec.model.config.paneHeights = ph; markDirty();
      }
    }
    if (rec.chart && rec.chart.getAxisWidth) {
      const aw = Math.round(rec.chart.getAxisWidth());
      if (aw && aw !== Math.round((rec.model.config.style || {}).axisWidth || 62)) {
        rec.model.config.style = Object.assign({}, rec.model.config.style || {}, { axisWidth: aw });
        markDirty();
      }
    }
    syncAlerts(rec, alerts);
  }

  function updateGlobalOfflineBanner(payload, rec) {
    let banner = qs('#dsk-md-offline-banner');
    if (!banner && viewport) {
      banner = el(`<div id="dsk-md-offline-banner" class="dsk-md-offline-banner" hidden></div>`);
      viewport.insertBefore(banner, viewport.firstChild);
    }
    if (!banner) return;
    const offline = payload && (
      payload.status === 'offline'
      || (payload.freshness && payload.freshness.offline)
      || payload.offline_banner
      || payload.market_data_available === false
    );
    if (rec) rec._marketOffline = !!offline;
    // A chart-level provider failure is not a global outage. Show red OFFLINE
    // only if no active chart currently has a usable live/fresh source.
    const active = Array.from(wins.values()).filter(row => !row.model.minimized);
    const anyUsable = active.some(row => row._marketOffline === false);
    if (offline && !anyUsable) {
      const ob = payload.offline_banner || {};
      const age = ob.age_sec != null ? ageText(Number(ob.age_sec)) : '';
      banner.hidden = false;
      banner.innerHTML = `<strong>OFFLINE — LIVE MARKET DATA UNAVAILABLE</strong>`
        + `<span>Last valid event: ${ob.last_valid_event || (payload.freshness && payload.freshness.data_as_of_utc) || 'unknown'}</span>`
        + `<span>Age: ${age || 'n/a'}</span>`
        + `<span>Last source: ${ob.last_source || 'NinjaTrader'}</span>`
        + `<span>Backup live providers available: ${ob.backup_providers_available != null ? ob.backup_providers_available : 0}</span>`
        + `<span>Strategies/execution must not use these prices as live.</span>`;
      document.documentElement.dataset.mdOffline = '1';
    } else if (anyUsable || (payload && payload.live === true && payload.freshness && payload.freshness.fresh === true)) {
      banner.hidden = true;
      delete document.documentElement.dataset.mdOffline;
    }
  }
  function setSrc(rec, state, title) {
    const s = rec.srcEl; if (!s) return;
    s.classList.remove('live', 'wait', 'err');
    s.classList.add(state);
    s.title = title;
    const text = s.querySelector('.src-tx');
    if (text) {
      const bits = String(title || '').split(' · ');
      const dataAt = bits.indexOf('DATA');
      text.textContent = dataAt >= 0 && bits[dataAt + 1] ? `DATA · ${bits[dataAt + 1]}` : (bits[1] || bits[0] || 'DATA');
    }
  }

  // One consolidated request updates every due chart. The bridge publishes its
  // BarsRequest snapshots every tick/second, so live windows refresh without
  // multiplying HTTP traffic when a 36/64-chart grid is open.
  // HTTP batch remains the fallback while WS incremental proves itself.
  UI.poll(async () => {
    ensureMarketDataWs();
    const now = Date.now();
    const recs = Array.from(wins.values()).filter(rec => {
      if (rec.model.minimized || rec.inFlight || rec.loadQueued) return false;
      // With a healthy WS, slow HTTP fallback to reduce full-series re-sends.
      const dueAt = rec.nextPollAt || 0;
      if (marketDataWsOk && dueAt && (now - dueAt) < 1500 && rec.hasBars) return false;
      return !rec.nextPollAt || rec.nextPollAt <= now;
    });
    if (!recs.length) return;
    const isVisible = (rec) => {
      const box = rec.node && rec.node.getBoundingClientRect();
      return !!(box && box.bottom > 0 && box.right > 0 && box.top < window.innerHeight && box.left < window.innerWidth);
    };
    // Viewport-first: a compact visible group is rendered before background
    // windows. Identical symbol/timeframe/range requests share one HTTP row.
    recs.sort((a, b) => Number(isVisible(b)) - Number(isVisible(a)));
    const selected = recs.slice(0, 12);
    const groups = new Map();
    selected.forEach((rec) => {
      const request = marketRequest(rec.model.config, null, chartMaxPoints(rec));
      const key = JSON.stringify(request);
      const group = groups.get(key) || { request, items: [] };
      group.items.push({ rec, stamp: beginDataRequest(rec) });
      groups.set(key, group);
    });
    const batch = Array.from(groups.values());
    try {
      const out = await API.http.marketBarsBatch({ requests: batch.map(item => item.request) });
      const rows = (out && out.series) || [];
      batch.forEach((item, index) => {
        item.items.forEach((entry) => {
          if (requestStillCurrent(entry.rec, entry.stamp)) applyWindowPayload(entry.rec, rows[index] || { bars: [], alerts: [], status: 'waiting' });
        });
      });
    } catch (e) {
      batch.forEach(item => {
        item.items.forEach((entry) => {
          if (requestStillCurrent(entry.rec, entry.stamp)) {
            entry.rec.nextPollAt = Date.now() + 2000;
            setSrc(entry.rec, 'err', 'Ошибка потока данных: ' + (e.message || e));
          }
        });
      });
    } finally { batch.forEach(item => item.items.forEach(entry => finishDataRequest(entry.rec, entry.stamp))); }
  }, LIVE_POLL_MS);

  // ---- add / configure chart dialog -------------------------------------
  async function openChartDialog(existingRec, mode) {
    const editing = !!existingRec;
    const templateMode = mode === 'template';
    const cfg = editing ? Object.assign({}, existingRec.model.config) : {
      instrument: '', root: '', timeframe: template.timeframe, type: template.type,
      indicators: template.indicators.slice(), range: Object.assign({}, template.range),
      aspect: template.aspect, style: cloneStyle(template.style),
    };
    cfg.style = Object.assign({}, DEFAULT_STYLE, cfg.style || {});
    cfg.style.macd = Object.assign({}, DEFAULT_STYLE.macd, cfg.style.macd || {});
    cfg.range = Object.assign({ id: '1m', days: 31, from: '', to: '' }, cfg.range || {});
    const d = UI.drawer(
      editing ? 'Параметры графика' : templateMode ? 'Макет графика — стандарт для всех' : 'Новый график',
      `<form class="dchart-form" id="dchart-form">
        <div class="dchart-layout">
          <div class="dchart-settings">
            <div class="fgrid">
              <label id="dc-inst-field" ${templateMode ? 'hidden' : ''}>Инструмент (актуальный контракт)
                <select id="dc-inst"><option value="">Загрузка инструментов…</option></select>
              </label>
              <label class="ind-chip" id="dc-contract-mode-wrap" ${templateMode ? 'hidden' : ''} title="Автоматический режим всегда использует актуальный контракт TopstepX. Закреплённый контракт не меняется."><input type="checkbox" id="dc-contract-fixed" ${cfg.contract_mode === 'fixed' ? 'checked' : ''}><span>Закрепить выбранный контракт</span></label>
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
            <div class="dchart-field">
              <span class="dchart-cap">Индикаторы</span>
              <div class="ind-grid" id="dc-ind">${INDICATORS.map(ind => `
                <label class="ind-chip ${cfg.indicators.includes(ind.id) ? 'on' : ''}"><input type="checkbox" value="${ind.id}" ${cfg.indicators.includes(ind.id) ? 'checked' : ''}><span>${ind.label}</span></label>`).join('')}</div>
            </div>
            <div class="dchart-field">
              <span class="dchart-cap">Внешний вид свечей</span>
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
            </div>
            <div class="macd-fields ${cfg.indicators.includes('macd') ? 'show' : ''} dchart-field" id="dc-macd">
              <span class="dchart-cap">Вид MACD</span>
              <div class="fgrid style-options">
                <label class="ind-chip ${cfg.style.macd.fill ? 'on' : ''}"><input type="checkbox" id="dc-macd-fill" ${cfg.style.macd.fill ? 'checked' : ''}><span>Заливка гистограммы</span></label>
                <label class="ind-chip ${cfg.style.macd.area ? 'on' : ''}"><input type="checkbox" id="dc-macd-area" ${cfg.style.macd.area ? 'checked' : ''}><span>Заливка между линиями</span></label>
                <label class="ind-chip ${cfg.style.macd.fillToZero ? 'on' : ''}"><input type="checkbox" id="dc-macd-zero" ${cfg.style.macd.fillToZero ? 'checked' : ''}><span>Заливка до нуля</span></label>
                <label class="ind-chip ${cfg.style.macd.vol ? 'on' : ''}"><input type="checkbox" id="dc-macd-vol" ${cfg.style.macd.vol ? 'checked' : ''}><span>Объём поверх MACD</span></label>
              </div>
              <div class="style-grid">
                <label>Гист. ↑<input type="color" id="dc-macd-up" value="${escAttr(cfg.style.macd.up)}"></label>
                <label>Гист. ↓<input type="color" id="dc-macd-down" value="${escAttr(cfg.style.macd.down)}"></label>
                <label>Насыщенность<input type="range" id="dc-macd-op" min="10" max="100" value="${Math.round((cfg.style.macd.opacity == null ? 0.85 : cfg.style.macd.opacity) * 100)}"></label>
                <label>Линия MACD<input type="color" id="dc-macd-line" value="${escAttr(cfg.style.macd.line)}"></label>
                <label>Сигнальная<input type="color" id="dc-macd-signal" value="${escAttr(cfg.style.macd.signal)}"></label>
              </div>
            </div>
          </div>
          <div class="dchart-preview-wrap">
            <div class="dchart-preview-title"><b>Живой предпросмотр</b><span>${editing ? 'Текущие данные графика' : 'Наглядный пример свечей'} · изменения видны сразу</span></div>
            <div class="dchart-preview" id="dc-preview"></div>
            ${templateMode ? '<div class="dchart-hint">Это стандартный макет: по нему создаются все новые графики. При сохранении он сразу применяется ко всем открытым окнам (снимите галочку ниже, если нужно только сохранить на будущее).</div>' : ''}
            ${editing ? '<button type="button" class="btn" id="dc-style-all">Применить этот стиль ко всем графикам</button>' : ''}
          </div>
        </div>
        <div class="dchart-actions">
          ${templateMode
            ? `<label class="ind-chip" id="dc-tpl-all-wrap" style="margin-right:auto"><input type="checkbox" id="dc-tpl-skip-open"><span>Только сохранить — не менять открытые (${layout.windows.length})</span></label>`
            : '<label class="ind-chip" id="dc-as-default-wrap" style="margin-right:auto" title="Сохранить эти параметры как стандарт для новых графиков"><input type="checkbox" id="dc-as-default"><span>Использовать по умолчанию</span></label>'}
          <button type="button" class="btn ghost" data-close-drawer>Отмена</button>
          <button type="submit" class="btn primary" id="dc-submit">${editing ? 'Применить' : templateMode ? 'Сохранить макет' : 'Добавить график'}</button>
        </div>
      </form>`
    );
    d.classList.add('wide');

    const instSel = qs('#dc-inst', d);
    if (!templateMode) {
      const list = await NTData.instruments();
      if (!list.length) {
        instSel.innerHTML = '<option value="">Нет инструментов — NinjaTrader офлайн</option>';
      } else {
        const groups = new Map(); list.forEach(x => { if (!groups.has(x.group)) groups.set(x.group, []); groups.get(x.group).push(x); });
        instSel.innerHTML = Array.from(groups.entries()).map(([group, rows]) => `<optgroup label="${escAttr(group)}">${rows.map(x => {
          const current = `<option value="${escAttr(x.symbol)}" data-root="${escAttr(x.root)}" data-contract-mode="auto" ${x.available ? '' : 'disabled'}>${escAttr(x.root)} — ${escAttr(x.name)}${x.available ? ` · актуальный ${escAttr(x.symbol)}` : ' · контракт пока недоступен'}</option>`;
          const fixed = (x.contracts || []).filter(c => c.instrument !== x.symbol).map(c => `<option value="${escAttr(c.instrument)}" data-root="${escAttr(x.root)}" data-contract-mode="fixed">${escAttr(x.root)} — ${escAttr(x.name)} · ${escAttr(c.instrument)}${c.expiry ? ` (expiry ${escAttr(c.expiry)})` : ''}</option>`).join('');
          return current + fixed;
        }).join('')}</optgroup>`).join('');
        const firstAvailable = list.find(x => x.available);
        const chosen = cfg.contract_mode === 'fixed' ? cfg.instrument : ((cfg.root && (list.find(x => x.root === cfg.root) || {}).symbol) || cfg.instrument || (firstAvailable && firstAvailable.symbol) || '');
        instSel.value = chosen;
        if (!instSel.value) instSel.selectedIndex = 0;
        cfg.instrument = instSel.value;
      }
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
      const indRoot = qs('#dc-ind', d);
      // Only checkboxes inside #dc-ind — never the "apply to all" / "as default" chips.
      const indicators = indRoot
        ? Array.from(indRoot.querySelectorAll('input[type="checkbox"]')).filter(x => x.checked).map(x => x.value).filter(Boolean)
        : [];
      return Object.assign({}, cfg, {
        instrument: (instSel && instSel.value) || '', root: (instSel && instSel.selectedOptions[0] && instSel.selectedOptions[0].dataset.root) || '',
        contract_mode: (qs('#dc-contract-fixed', d) && qs('#dc-contract-fixed', d).checked) ? 'fixed' : 'auto',
        indicators,
        range: { id: rangeId, days: preset ? preset.days : null, from: qs('#dc-from', d).value, to: qs('#dc-to', d).value },
        style: Object.assign({}, cfg.style, {
          upColor: qs('#dc-up', d).value, upFill: qs('#dc-up', d).value,
          downColor: qs('#dc-down', d).value, downFill: qs('#dc-down', d).value,
          background: qs('#dc-bg', d).value, bodyWidth: Number(qs('#dc-body', d).value) / 100,
          wickWidth: Number(qs('#dc-wick', d).value), borderWidth: Number(qs('#dc-border', d).value),
          fillOpacity: qs('#dc-fill', d).checked ? 0.85 : 0, legendMode: qs('#dc-legend', d).value,
          macd: {
            fill: qs('#dc-macd-fill', d).checked, area: qs('#dc-macd-area', d).checked,
            fillToZero: qs('#dc-macd-zero', d).checked, vol: qs('#dc-macd-vol', d).checked,
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
    instSel.addEventListener('change', () => {
      const fixed = qs('#dc-contract-fixed', d);
      const selected = instSel.selectedOptions && instSel.selectedOptions[0];
      if (fixed && selected && selected.dataset.contractMode) fixed.checked = selected.dataset.contractMode === 'fixed';
      const wrap = qs('#dc-contract-mode-wrap', d);
      if (wrap && fixed) wrap.classList.toggle('on', !!fixed.checked);
      refreshPreview();
    });
    const fixedContract = qs('#dc-contract-fixed', d);
    if (fixedContract) fixedContract.addEventListener('change', () => {
      const wrap = qs('#dc-contract-mode-wrap', d);
      if (wrap) wrap.classList.toggle('on', !!fixedContract.checked);
      refreshPreview();
    });
    qsaLocal('#dc-up,#dc-down,#dc-bg,#dc-body,#dc-wick,#dc-border,#dc-fill,#dc-legend,#dc-macd-fill,#dc-macd-area,#dc-macd-zero,#dc-macd-vol,#dc-macd-up,#dc-macd-down,#dc-macd-op,#dc-macd-line,#dc-macd-signal', d).forEach(node => node.addEventListener('input', () => {
      if (node.closest('.ind-chip')) node.closest('.ind-chip').classList.toggle('on', node.checked);
      refreshPreview();
    }));
    const styleAll = qs('#dc-style-all', d);
    if (styleAll) styleAll.addEventListener('click', () => {
      const style = readForm().style;
      layout.windows.forEach(model => { model.config.style = Object.assign({}, style); const rec = wins.get(model.id); if (rec) rec.chart.setStyle(style); });
      markDirty(); toast('Стиль применён ко всем графикам');
    });
    // Keep .on visual state in sync for the action chips.
    [['#dc-tpl-skip-open', '#dc-tpl-all-wrap'], ['#dc-as-default', '#dc-as-default-wrap']].forEach(([cbSel, wrapSel]) => {
      const cb = qs(cbSel, d); const wrap = qs(wrapSel, d);
      if (!cb || !wrap) return;
      const sync = () => wrap.classList.toggle('on', !!cb.checked);
      cb.addEventListener('change', sync); sync();
    });

    const cleanup = () => preview.destroy();
    qsaLocal('[data-close-drawer]', d).forEach(btn => btn.addEventListener('click', cleanup, { once: true }));

    qs('#dchart-form', d).addEventListener('submit', (e) => {
      e.preventDefault();
      const next = readForm();
      if (next.range.id === 'custom' && (!next.range.from || !next.range.to)) { toast('Укажите обе даты диапазона'); return; }
      if (templateMode) {
        template = saveTemplate(makeTemplateFromConfig(next));
        // Default: push the template onto every open chart. Opt out via checkbox.
        const skipOpen = !!(qs('#dc-tpl-skip-open', d) && qs('#dc-tpl-skip-open', d).checked);
        let applied = 0;
        if (!skipOpen && layout.windows.length) applied = applyTemplateToAll(template);
        cleanup();
        const indLabel = (template.indicators || []).join(', ') || 'нет';
        toast(skipOpen || !layout.windows.length
          ? `Макет сохранён · индикаторы: ${indLabel} — по нему создаются новые графики`
          : `Макет сохранён и применён к ${applied} из ${layout.windows.length} · индикаторы: ${indLabel}`);
        UI.closeDrawer();
        return;
      }
      if (!next.instrument) { toast('Выберите инструмент'); return; }
      const asDefault = !!(qs('#dc-as-default', d) && qs('#dc-as-default', d).checked);
      if (asDefault) template = saveTemplate(makeTemplateFromConfig(next));
      cleanup();
      if (editing) applyChartConfig(existingRec, next);
      else addChart(next);
      UI.closeDrawer();
      if (asDefault) toast(editing ? 'Параметры применены и сохранены по умолчанию' : 'График добавлен — эти параметры теперь по умолчанию');
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
    if (!rec || !rec.chart) return;
    const prev = rec.model.config || {};
    const identityChanged = prev.instrument !== cfg.instrument || prev.timeframe !== cfg.timeframe;
    if (identityChanged) {
      sendMarketDataSubscription('unsubscribe', prev.instrument, prev.timeframe);
      deleteModelAlerts(rec.model);
      rec.model.drawings = [];
      if (rec.chart.setDrawings) rec.chart.setDrawings([]);
      rec.hasBars = false;
      resetDataTracking(rec);
    }
    // Always replace indicators/style with a fresh copy so apply-to-all cannot
    // leave shared array/object references across windows.
    rec.model.config = Object.assign({}, prev, cfg, {
      indicators: Array.isArray(cfg.indicators) ? cfg.indicators.slice() : [],
      style: cloneStyle(cfg.style),
      range: Object.assign({}, cfg.range || prev.range || {}),
    });
    if (identityChanged) sendMarketDataSubscription('subscribe', rec.model.config.instrument, rec.model.config.timeframe);
    renderWindowMeta(rec);
    try {
      rec.chart.setIndicators(rec.model.config.indicators);
      rec.chart.setStyle(rec.model.config.style);
      if (rec.chart.setAspect) rec.chart.setAspect(rec.model.config.aspect || 'auto');
      // Pane count changed → force a synchronous remeasure/redraw so MACD/RSI
      // panes appear immediately on every window, not only the first few.
      if (rec.chart.resize) rec.chart.resize();
    } catch (e) { /* keep going — other windows must still update */ }
    renderSidePanel(rec);
    if (identityChanged || dataSignature(prev) !== dataSignature(rec.model.config)) {
      if (rec.chart && rec.chart.setLoading) rec.chart.setLoading(true, 'Загрузка…');
      rec.inFlight = false;
      loadWindowData(rec);
    }
    markDirty();
  }

  // Push a template onto every open chart. Accepts an explicit template so the
  // caller can pass the just-saved value (never a stale closure). One failed
  // window must not abort the rest (that was leaving MNQ/M2K/MYM without MACD).
  function applyTemplateToAll(tpl) {
    const source = makeTemplateFromConfig(tpl || template);
    template = source;
    let applied = 0;
    layout.windows.slice().forEach(model => {
      try {
        const cfg = applyTemplateToConfig(model.config, source);
        const rec = wins.get(model.id);
        if (rec && rec.chart) { applyChartConfig(rec, cfg); applied += 1; }
        else { model.config = cfg; applied += 1; }
      } catch (e) { /* continue with remaining windows */ }
    });
    persistNow();
    return applied;
  }

  function addChart(cfg) {
    cfg = Object.assign({ contract_mode: 'auto' }, cfg || {});
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
    layout.grid = 0; layout.gridMode = 'free';
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
    resetDataTracking(rec);
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
      <label class="drawing-lock"><input type="checkbox" id="mc-vol" ${macd.vol ? 'checked' : ''}><span>Объём поверх MACD (полупрозрачно)</span></label>
      <div class="dchart-actions"><button type="button" class="btn ghost" id="mc-all">Применить ко всем</button><button type="button" class="btn primary" data-close-drawer>Готово</button></div>
    </form>`);
    const read = () => ({
      fill: qs('#mc-fill', d).checked,
      opacity: Number(qs('#mc-op', d).value) / 100,
      up: qs('#mc-up', d).value, down: qs('#mc-down', d).value,
      line: qs('#mc-line', d).value, signal: qs('#mc-signal', d).value,
      area: qs('#mc-area', d).checked,
      fillToZero: qs('#mc-zero', d).checked,
      vol: qs('#mc-vol', d).checked,
    });
    const apply = () => {
      const next = read();
      rec.model.config.style = Object.assign({}, rec.model.config.style, { macd: next });
      rec.chart.setStyle({ macd: next });
      markDirty();
    };
    qsaLocal('#mc-fill,#mc-op,#mc-up,#mc-down,#mc-line,#mc-signal,#mc-area,#mc-zero,#mc-vol', d).forEach(node => node.addEventListener('input', apply));
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
    box.querySelector('[data-draw-collapse]').addEventListener('click', () => { box.classList.toggle('collapsed'); });
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
      if (isTask) {
        // Open the task's own chat with the owner's поручение as its first
        // message and Иван's confirmation, so the same thread already exists in
        // the app and Telegram before the scheduled snapshot/report arrives.
        const convId = patch.conversationId;
        if (convId && convId !== 'default') {
          try {
            await API.http.aiOrchestratorAnnounceChartTask(convId, {
              instruction: patch.agentMessage || '',
              agent_id: patch.agentId || 'ivan',
              instrument: rec.model.config.instrument,
              price: Number(drawing.price),
              type: drawing.type,
              label: patch.label || '',
              delay_seconds: parseDelaySeconds(patch.agentMessage),
              duration_minutes: patch.durationMinutes || 0,
              report_mode: patch.reportMode || 'touch',
              action: ruleAction,
            });
          } catch (er) { /* announcement is best-effort */ }
        }
        if (window.UI && UI.openOrchestrator) { try { UI.openOrchestrator(); } catch (er) {} }
      }
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

  function isTypingTarget(el) {
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
  }

  function selectedDrawingCtx() {
    const active = activeRec();
    if (active && active.chart) {
      const drawing = active.chart.getSelectedDrawing();
      if (drawing) return { rec: active, drawing };
    }
    for (const rec of wins.values()) {
      if (rec.model.minimized || !rec.chart) continue;
      const drawing = rec.chart.getSelectedDrawing();
      if (drawing) return { rec, drawing };
    }
    return null;
  }

  function cloneDrawing(drawing) {
    const clone = JSON.parse(JSON.stringify(drawing));
    clone.id = 'dr_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7);
    delete clone.alertId;
    clone.status = 'local-only';
    clone.createdAt = new Date().toISOString();
    const px = Number(drawing.price);
    const priceStep = Number.isFinite(px) ? Math.max(Math.abs(px) * 0.001, 0.25) : 0.25;
    const indexStep = 3;
    if (Array.isArray(clone.points)) {
      clone.points = clone.points.map(pt => Object.assign({}, pt, {
        price: Number(pt.price) + priceStep,
        index: (Number(pt.index) || 0) + indexStep,
      }));
      delete clone.price;
    } else {
      if (Number.isFinite(Number(clone.price))) clone.price = Number(clone.price) + priceStep;
      if (clone.index != null) clone.index = Number(clone.index) + indexStep;
    }
    return clone;
  }

  function copySelectedDrawing() {
    const ctx = selectedDrawingCtx();
    if (!ctx) return false;
    drawingClipboard = JSON.parse(JSON.stringify(ctx.drawing));
    toast('Отметка скопирована');
    return true;
  }

  function pasteDrawingClipboard() {
    if (!drawingClipboard) return false;
    const rec = activeRec();
    if (!rec || !rec.chart) return false;
    const clone = cloneDrawing(drawingClipboard);
    rec.model.drawings = Array.isArray(rec.model.drawings) ? rec.model.drawings : [];
    rec.model.drawings.push(clone);
    rec.chart.setDrawings(rec.model.drawings);
    rec.chart.selectDrawing(clone.id);
    renderDrawingEditor(rec, clone);
    markDirty();
    toast('Отметка вставлена');
    return true;
  }

  async function deleteSelectedDrawing() {
    const ctx = selectedDrawingCtx();
    if (!ctx) return false;
    await removeDrawing(ctx.rec, ctx.drawing);
    return true;
  }

  function deleteModelAlerts(model) {
    (model.drawings || []).forEach(drawing => {
      if (drawing.alertId) API.http.deletePriceAlert(drawing.alertId).catch(() => {});
    });
  }

  function syncAlerts(rec, alerts) {
    if (!Array.isArray(alerts)) return;
    rec.model.drawings = Array.isArray(rec.model.drawings) ? rec.model.drawings : [];
    // Backend deletion is authoritative for drawings linked to a persisted
    // alert. Preserve local-only/manual drawings, but do not leave a stale line
    // on the canvas after its alert was removed (including repaired bad tasks).
    const alertIds = new Set(alerts.map(alert => alert && alert.id).filter(Boolean));
    const beforeCount = rec.model.drawings.length;
    rec.model.drawings = rec.model.drawings.filter(drawing => !drawing.alertId || alertIds.has(drawing.alertId));
    let removed = rec.model.drawings.length !== beforeCount;
    alerts.forEach(alert => {
      if (!alert.drawing_id || rec.model.drawings.some(drawing => drawing.id === alert.drawing_id)) return;
      rec.model.drawings.push({
        id: alert.drawing_id, type: alert.type || 'line', price: Number(alert.price),
        label: alert.label || 'Иван', color: alert.color || '#4fd1e0', locked: false,
        durationMinutes: 0, ruleAction: alert.action || 'none', snapshot: !!alert.snapshot,
        reportMode: alert.report_mode || 'touch', agentId: alert.agent_id || 'ivan',
        agentMessage: alert.agent_message || '', conversationId: alert.conversation_id || 'default',
        createdAt: alert.created_at_utc || new Date().toISOString(),
        alertId: alert.id, status: alert.status || 'active',
      });
    });
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
    if (changed || removed) { rec.chart.setDrawings(rec.model.drawings); markDirty(); }
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
    addChart({ instrument: symbol, root: root, contract_mode: 'auto', timeframe: timeframe || template.timeframe,
      indicators: template.indicators.slice(), type: template.type,
      range: Object.assign({}, template.range), aspect: template.aspect,
      style: cloneStyle(template.style) });
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
    addChart({ instrument: item.symbol, root: item.root, contract_mode: 'auto', timeframe: timeframe || template.timeframe,
      indicators: template.indicators.slice(), type: template.type,
      range: Object.assign({}, template.range), aspect: template.aspect,
      style: cloneStyle(template.style) });
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
    if (type === 'open_desktop_tab') {
      return { ok: true, already_open: true };
    }
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
        id: p.drawing_id || ('dr_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7)),
        type: p.type || 'line', price: Number(p.price), label: p.label || 'Иван',
        color: p.color || '#4fd1e0', locked: false,
        durationMinutes: Number(p.duration_minutes) || 0,
        ruleAction: ruleMap[p.rule] || 'none',
        snapshot: !!p.snapshot, reportMode: p.report_mode || 'touch',
        agentId: 'ivan', agentMessage: cmd.note || '',
        conversationId: cmd.conversation_id || currentConversationId(),
        createdAt: new Date().toISOString(), status: 'active', alertId: p.alert_id || '',
      };
      if (!Number.isFinite(drawing.price)) return { ok: false, error: 'нет цены' };
      rec.model.drawings = Array.isArray(rec.model.drawings) ? rec.model.drawings : [];
      if (!rec.model.drawings.some(row => row.id === drawing.id)) rec.model.drawings.push(drawing);
      rec.chart.setDrawings(rec.model.drawings);
      bringToFront(rec);
      if (!drawing.alertId) await syncDrawingRule(rec, drawing, true);
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

  // ---- proportional chart grids (all / group / manual) ------------------
  function modelRoot(model) {
    return (model.config && (model.config.root || String(model.config.instrument || '').split(' ')[0])) || '';
  }

  // Build ordered groups from the static catalog: 'Индексы' → [{root,name,group}].
  function instrumentGroups() {
    const map = new Map();
    DESKTOP_INSTRUMENTS.forEach(([root, name, group]) => {
      if (!map.has(group)) map.set(group, []);
      map.get(group).push({ root, name, group });
    });
    return map;
  }

  // Toolbar menu: whole catalog, a single category, or manual checkbox picker.
  function openChartsMenu(anchor) {
    const items = [{ icon: 'grid', label: `Все графики (${DESKTOP_INSTRUMENTS.length})`, onClick: () => applyAllInstruments() },
      { divider: true }];
    for (const [group, rows] of instrumentGroups()) {
      items.push({ icon: 'layers', label: `${group} (${rows.length})`, onClick: () => applyGroup(group) });
    }
    items.push({ divider: true });
    items.push({ icon: 'list', label: 'Выбрать вручную…', onClick: () => openInstrumentPicker() });
    UI.menu(anchor, items);
  }

  // Presets replace the whole set; the manual picker (below) is additive.
  function applyAllInstruments() { return syncInstrumentGrid(DESKTOP_INSTRUMENTS.map(r => r[0])); }
  function applyGroup(group) {
    return syncInstrumentGrid(DESKTOP_INSTRUMENTS.filter(r => r[2] === group).map(r => r[0]));
  }

  // Core: reconcile the open windows with the requested instrument roots and
  // tile them into equal cells filling the screen. Every selection mode funnels
  // through here, so add/remove always ends in a proportional retileGrid().
  async function syncInstrumentGrid(roots, opts) {
    opts = opts || {};
    const wanted = new Set(roots);
    const all = (await NTData.instruments()).filter(item => item.available && item.symbol);
    const byRoot = new Map(all.map(item => [item.root, item]));
    // Keep catalog order and only roots that actually have a live contract.
    const desired = [];
    DESKTOP_INSTRUMENTS.forEach(([root]) => { if (wanted.has(root) && byRoot.has(root)) desired.push(root); });
    if (!desired.length) { toast('Нет доступных контрактов для выбранных инструментов'); return; }

    const tf = opts.timeframe || layout.gridTimeframe || '5m';
    layout.gridMode = 'instruments';
    layout.gridRoots = desired.slice();
    layout.gridTimeframe = tf;
    layout.screenFit = true;
    applyCanvas();

    const desiredSet = new Set(desired);
    const bigGrid = desired.length >= 12;
    bulkMounting = true;
    try {
      // Drop windows whose instrument is no longer requested.
      layout.windows.slice().forEach(model => { if (!desiredSet.has(modelRoot(model))) destroyWindow(model); });
      // Add windows for newly requested instruments.
      const have = new Set(layout.windows.map(modelRoot));
      desired.forEach(root => {
        if (have.has(root)) return;
        const item = byRoot.get(root);
        const cfg = { instrument: item.symbol, root: item.root, contract_mode: 'auto', timeframe: tf || template.timeframe,
          indicators: template.indicators.slice(), type: template.type,
          range: bigGrid ? { id: '1d', days: 1, from: '', to: '' } : Object.assign({}, template.range),
          aspect: template.aspect, style: cloneStyle(template.style) };
        layout.seq = (layout.seq || 0) + 1;
        const model = { id: 'c' + Date.now() + '_' + layout.seq, x: 0, y: 0, w: 640, h: 420,
          z: 10, minimized: false, maximized: false, pinned: false, bare: false, config: cfg, drawings: [] };
        layout.windows.push(model);
        createWindow(model);
      });
      // Stable, catalog-ordered layout so tiling is deterministic.
      layout.windows.sort((a, b) => desired.indexOf(modelRoot(a)) - desired.indexOf(modelRoot(b)));
    } finally { bulkMounting = false; }

    layout.grid = layout.windows.length;
    retileGrid();
    wins.forEach(rec => { rec.nextPollAt = 0; if (rec.chart) rec.chart.resize(); });
    viewport.scrollLeft = 0; viewport.scrollTop = 0;
    renderDock(); refreshEmpty(); markDirty();
    const n = layout.windows.length;
    toast(`На весь экран: ${n} ${n === 1 ? 'график' : n < 5 ? 'графика' : 'графиков'}`);
  }

  // Manual picker: checkbox list grouped by category, with per-group toggles.
  // Pre-checks the current set, so applying is additive relative to what's open.
  async function openInstrumentPicker() {
    const all = (await NTData.instruments());
    const availByRoot = new Map(all.map(item => [item.root, !!item.available]));
    const current = (layout.gridMode === 'instruments' && (layout.gridRoots || []).length)
      ? layout.gridRoots
      : layout.windows.map(modelRoot).filter(Boolean);
    const sel = new Set(current);
    const curTf = layout.gridTimeframe || '5m';

    const groupsHtml = Array.from(instrumentGroups().entries()).map(([group, rows]) => `
      <div class="dsk-pick-group" data-group="${escAttr(group)}">
        <label class="dsk-pick-ghead"><input type="checkbox" data-group-cb><b>${escAttr(group)}</b><span class="dsk-pick-gc">${rows.length}</span></label>
        <div class="dsk-pick-grid">${rows.map(x => {
          const avail = availByRoot.get(x.root);
          return `<label class="ind-chip ${sel.has(x.root) ? 'on' : ''} ${avail ? '' : 'dsk-pick-off'}">
            <input type="checkbox" value="${escAttr(x.root)}" ${sel.has(x.root) ? 'checked' : ''} ${avail ? '' : 'disabled'}>
            <span>${escAttr(x.root)} · ${escAttr(x.name)}${avail ? '' : ' · нет контракта'}</span></label>`;
        }).join('')}</div>
      </div>`).join('');

    const d = UI.drawer('Инструменты на рабочем столе', `<div class="dsk-pick" id="dsk-pick">
      <div class="dsk-pick-bar">
        <button type="button" class="btn sm" data-pick-all>Включить все</button>
        <button type="button" class="btn sm ghost" data-pick-none>Снять все</button>
        <div class="spacer"></div>
        <label class="dsk-pick-tf">Таймфрейм<select data-pick-tf>${TIMEFRAMES.map(t => `<option value="${t}" ${t === curTf ? 'selected' : ''}>${t}</option>`).join('')}</select></label>
      </div>
      <div class="dsk-pick-groups">${groupsHtml}</div>
      <div class="dchart-hint">Пресеты («Все графики» и группы) заменяют набор целиком. Здесь набор пополняется: отметьте нужные графики, снимите лишние. Все окна разложатся пропорционально одинаковыми ячейками на весь экран.</div>
      <div class="dchart-actions">
        <button type="button" class="btn ghost" data-close-drawer>Отмена</button>
        <button type="button" class="btn primary" data-pick-apply>Применить (<span data-pick-count>${sel.size}</span>)</button>
      </div>
    </div>`);
    d.classList.add('wide');
    const root = qs('#dsk-pick', d);

    function refreshState() {
      const cEl = qs('[data-pick-count]', d);
      if (cEl) cEl.textContent = String(root.querySelectorAll('.dsk-pick-grid input:checked').length);
      qsaLocal('.dsk-pick-group', root).forEach(g => {
        const boxes = Array.from(g.querySelectorAll('.dsk-pick-grid input:not(:disabled)'));
        const on = boxes.filter(b => b.checked).length;
        const head = qs('[data-group-cb]', g);
        head.checked = boxes.length > 0 && on === boxes.length;
        head.indeterminate = on > 0 && on < boxes.length;
      });
    }
    root.addEventListener('change', (e) => {
      const inst = e.target.closest('.dsk-pick-grid input[type="checkbox"]');
      if (inst) { inst.closest('.ind-chip').classList.toggle('on', inst.checked); refreshState(); return; }
      const gh = e.target.closest('[data-group-cb]');
      if (gh) {
        gh.closest('.dsk-pick-group').querySelectorAll('.dsk-pick-grid input:not(:disabled)')
          .forEach(b => { b.checked = gh.checked; b.closest('.ind-chip').classList.toggle('on', b.checked); });
        refreshState();
      }
    });
    qs('[data-pick-all]', d).addEventListener('click', () => {
      root.querySelectorAll('.dsk-pick-grid input:not(:disabled)').forEach(b => { b.checked = true; b.closest('.ind-chip').classList.add('on'); });
      refreshState();
    });
    qs('[data-pick-none]', d).addEventListener('click', () => {
      root.querySelectorAll('.dsk-pick-grid input').forEach(b => { b.checked = false; b.closest('.ind-chip').classList.remove('on'); });
      refreshState();
    });
    qs('[data-pick-apply]', d).addEventListener('click', () => {
      const roots = Array.from(root.querySelectorAll('.dsk-pick-grid input:checked')).map(b => b.value);
      if (!roots.length) { toast('Отметьте хотя бы один график'); return; }
      const tf = qs('[data-pick-tf]', d).value || '5m';
      UI.closeDrawer();
      syncInstrumentGrid(roots, { timeframe: tf });
    });
    refreshState();
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
        <select id="snap-inst"><option value="">Все инструменты</option></select>
        <select id="snap-sort">
          <option value="new">Сначала новые</option>
          <option value="old">Сначала старые</option>
          <option value="inst">По инструменту</option>
          <option value="pattern">По паттерну</option>
        </select>
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
    const instSel = qs('#snap-inst', d), sortSel = qs('#snap-sort', d);
    function sortSnaps(items, mode) {
      const rows = items.slice();
      if (mode === 'old') rows.sort((a, b) => String(a.created_at_utc || '').localeCompare(String(b.created_at_utc || '')));
      else if (mode === 'inst') rows.sort((a, b) => String(a.instrument || '').localeCompare(String(b.instrument || '')) || String(b.created_at_utc || '').localeCompare(String(a.created_at_utc || '')));
      else if (mode === 'pattern') rows.sort((a, b) => String(a.pattern || 'яяя').localeCompare(String(b.pattern || 'яяя')) || String(b.created_at_utc || '').localeCompare(String(a.created_at_utc || '')));
      else rows.sort((a, b) => String(b.created_at_utc || '').localeCompare(String(a.created_at_utc || '')));
      return rows;
    }
    async function reload() {
      grid.innerHTML = '<div class="empty-state">Загрузка…</div>';
      let data;
      try { data = await API.http.snapshots({ pattern: patternSel.value || undefined, favorites: favOnly.checked ? 1 : undefined }); }
      catch (e) { grid.innerHTML = '<div class="empty-state">Не удалось загрузить снимки.</div>'; return; }
      let items = (data && data.snapshots) || [];
      const patterns = (data && data.patterns) || [];
      const cur = patternSel.value;
      patternSel.innerHTML = '<option value="">Все снимки</option>' +
        patterns.map(p => `<option value="${escAttr(p.name)}" ${p.name === cur ? 'selected' : ''}>${escAttr(p.name)} · ${p.count}</option>`).join('');
      // Instrument filter is populated from what is present, then applied.
      const instruments = Array.from(new Set(items.map(s => s.instrument).filter(Boolean))).sort();
      const curInst = instSel.value;
      instSel.innerHTML = '<option value="">Все инструменты</option>' +
        instruments.map(i => `<option value="${escAttr(i)}" ${i === curInst ? 'selected' : ''}>${escAttr(i)}</option>`).join('');
      if (curInst) items = items.filter(s => s.instrument === curInst);
      items = sortSnaps(items, sortSel.value);
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
    instSel.addEventListener('change', reload);
    sortSel.addEventListener('change', reload);
    qs('#snap-refresh', d).addEventListener('click', reload);
    qs('#snap-clear', d).addEventListener('click', async () => {
      if (!confirm('Очистить все снимки, кроме избранных?')) return;
      try { await API.http.clearSnapshots(true); toast('Список снимков очищен'); } catch (e) {}
      reload();
    });
    reload();
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
    // Bulk mounting deliberately skips per-window work while the DOM is
    // assembled.  Queue the first viewport load afterwards: relying solely
    // on a later batch poll allowed a flood of WS ticks to mask a failed or
    // delayed first batch, leaving a perfectly live chart stuck at "Нет
    // данных".  The existing bounded queue keeps large layouts responsive.
    wins.forEach(rec => { rec.nextPollAt = 0; loadWindowData(rec); });
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
  qs('#dsk-grid').addEventListener('click', (e) => { e.stopPropagation(); openChartsMenu(e.currentTarget); });
  const templateBtn = qs('#dsk-template'); if (templateBtn) templateBtn.addEventListener('click', () => openChartDialog(null, 'template'));
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

  // Delete / copy / paste for selected drawings (lines, points, arrows, …).
  // Use e.code (KeyC/KeyV) — e.key is layout-dependent (Russian «с»/«м» break Ctrl+C/V).
  document.addEventListener('keydown', (e) => {
    if (!wins.size || isTypingTarget(document.activeElement)) return;
    if (e.key === 'Delete' || e.key === 'Backspace') {
      if (!selectedDrawingCtx()) return;
      e.preventDefault();
      deleteSelectedDrawing();
      return;
    }
    if (!(e.ctrlKey || e.metaKey)) return;
    if (e.code === 'KeyC') {
      if (!copySelectedDrawing()) return;
      e.preventDefault();
    } else if (e.code === 'KeyV') {
      if (!pasteDrawingClipboard()) return;
      e.preventDefault();
    }
  }, true);

  // ---- boot --------------------------------------------------------------
  // Clear the daily rollover cache key so the contract-refresh always runs
  // against the live server on a fresh page load (the server itself is the
  // authoritative source; caching one whole day is too coarse for expiry events).
  try { localStorage.removeItem('desktop.contract-refresh-day'); } catch (e) { /* ignore */ }
  mountLayout();
  refreshContractsIfDue();
});
