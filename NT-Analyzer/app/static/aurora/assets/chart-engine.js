/* =====================================================================
   ChartEngine — dependency-free professional candlestick chart.
   A self-contained trading chart (Japanese candles, right price axis,
   bottom time axis, indicator subpanes, crosshair) built on <canvas>.
   Designed as the visual foundation of the "Рабочий стол" (desktop) —
   meant to grow into a full trading surface (orders, signals, drawings).

   Public API (window.ChartEngine):
     const chart = ChartEngine.create(hostEl, {
       timeframe: '5m', instrument: 'MNQ',
       indicators: ['vol','ma:9','ema:21','macd','rsi'],
     });
     chart.setData(bars);           // bars: [{t,o,h,l,c,v}]
     chart.appendBar(bar);          // live tick / new bar
     chart.setIndicators([...]);    // reconfigure overlays / subpanes
     chart.resize();                // re-measure host + redraw
     chart.destroy();               // detach observers + listeners
     chart.on('crosshair', fn);     // { index, bar } | null
     chart.on('drawing', fn);       // future: user-drawn objects → events

   No fabricated data: an empty bars array renders an honest empty state.
   ===================================================================== */
(function () {
  'use strict';

  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const MAX_DPR = 1.5;
  const MAX_CANVAS_SIDE = 4096;
  const MAX_CANVAS_PIXELS = 5000000;
  const MAX_BAR_PRICE_JUMP = 4;

  function cssVar(name, fallback) {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    } catch (e) { return fallback; }
  }

  // Resolve theme colours once per draw (cheap; keeps chart in sync with theme).
  function palette(style) {
    style = style || {};
    const macd = style.macd || {};
    const macdUp = macd.up || '#34d399';
    const macdDown = macd.down || '#ff6b81';
    const macdFill = macd.fill === false ? 0 : (macd.opacity == null ? 0.85 : clamp(Number(macd.opacity), 0, 1));
    return {
      up: style.upColor || cssVar('--pos', '#34d399'),
      down: style.downColor || cssVar('--neg', '#ff6b81'),
      upFill: style.upFill || style.upColor || cssVar('--pos', '#34d399'),
      downFill: style.downFill || style.downColor || cssVar('--neg', '#ff6b81'),
      grid: 'rgba(255,255,255,0.05)',
      gridStrong: 'rgba(255,255,255,0.10)',
      axis: cssVar('--tx-3', '#8b93a7'),
      text: cssVar('--tx-2', '#aeb6c6'),
      textDim: cssVar('--tx-4', '#5c6478'),
      // Axis labels (time + price) are kept deliberately brighter than the
      // muted UI text so they stay readable over candles. `axisBrightness`
      // (0.5..1.6, default 1) lets the owner tune it per chart.
      axisText: mixWhite(style.axisText || cssVar('--tx-2', '#aeb6c6'), style.axisBrightness),
      axisStrong: mixWhite(style.axisStrong || '#e8ecf5', style.axisBrightness),
      cross: 'rgba(180,200,255,0.55)',
      crossBg: cssVar('--bg-3', '#1a2030'),
      ma: ['#4fd1e0', '#fcc55a', '#b48cff', '#f59e6b', '#8a7cff'],
      macdUp: withA(macdUp, macdFill),
      macdDown: withA(macdDown, macdFill),
      macdUpColor: macdUp,
      macdDownColor: macdDown,
      macdFillOn: macdFill > 0,
      macdLine: macd.line || '#4fd1e0',
      macdSignal: macd.signal || '#fcc55a',
      macdArea: macd.area === true,
      macdFillBetween: macd.area === true,
      macdFillToZero: macd.fillToZero === true,
      macdBetweenOpacity: macd.betweenOpacity == null ? 0.4 : clamp(Number(macd.betweenOpacity), 0, 1),
      macdZeroOpacity: macd.zeroOpacity == null ? 0.16 : clamp(Number(macd.zeroOpacity), 0, 1),
      // Semi-transparent volume bars drawn inside the MACD pane (indicator over indicator).
      macdVolOverlay: macd.vol === true,
      macdVolOpacity: macd.volOpacity == null ? 0.2 : clamp(Number(macd.volOpacity), 0, 1),
      rsi: '#b48cff',
      volUp: 'rgba(52,211,153,0.40)',
      volDown: 'rgba(255,107,129,0.40)',
    };
  }

  // ---- indicator maths ------------------------------------------------------
  function sma(values, period) {
    const out = new Array(values.length).fill(null);
    let sum = 0;
    for (let i = 0; i < values.length; i++) {
      sum += values[i];
      if (i >= period) sum -= values[i - period];
      if (i >= period - 1) out[i] = sum / period;
    }
    return out;
  }
  function ema(values, period) {
    const out = new Array(values.length).fill(null);
    const k = 2 / (period + 1);
    let prev = null;
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (prev == null) {
        // seed with SMA over the first `period` points
        if (i >= period - 1) {
          let s = 0; for (let j = i - period + 1; j <= i; j++) s += values[j];
          prev = s / period; out[i] = prev;
        }
      } else {
        prev = v * k + prev * (1 - k);
        out[i] = prev;
      }
    }
    return out;
  }
  function macd(values, fast, slow, signal) {
    const ef = ema(values, fast), es = ema(values, slow);
    const line = values.map((_, i) => (ef[i] != null && es[i] != null) ? ef[i] - es[i] : null);
    const compact = line.map(v => (v == null ? 0 : v));
    const sig = ema(compact, signal).map((v, i) => (line[i] == null ? null : v));
    const hist = line.map((v, i) => (v != null && sig[i] != null) ? v - sig[i] : null);
    return { line, signal: sig, hist };
  }
  function rsi(values, period) {
    const out = new Array(values.length).fill(null);
    let gain = 0, loss = 0;
    for (let i = 1; i < values.length; i++) {
      const ch = values[i] - values[i - 1];
      const g = Math.max(0, ch), l = Math.max(0, -ch);
      if (i <= period) {
        gain += g; loss += l;
        if (i === period) {
          const rs = loss === 0 ? 100 : gain / loss;
          out[i] = 100 - 100 / (1 + rs);
          gain /= period; loss /= period;
        }
      } else {
        gain = (gain * (period - 1) + g) / period;
        loss = (loss * (period - 1) + l) / period;
        const rs = loss === 0 ? 100 : gain / loss;
        out[i] = 100 - 100 / (1 + rs);
      }
    }
    return out;
  }
  // Weighted moving average (linear weights 1..period), used to build the HMA.
  function wma(values, period) {
    const out = new Array(values.length).fill(null);
    const denom = period * (period + 1) / 2;
    for (let i = period - 1; i < values.length; i++) {
      let sum = 0, ok = true;
      for (let k = 0; k < period; k++) {
        const v = values[i - period + 1 + k];
        if (v == null || !Number.isFinite(v)) { ok = false; break; }
        sum += v * (k + 1);
      }
      out[i] = ok ? sum / denom : null;
    }
    return out;
  }
  // Hull Moving Average: WMA( 2*WMA(n/2) − WMA(n), sqrt(n) ) — fast & smooth,
  // drawn as an overlay on the price bars just like MA/EMA.
  function hma(values, period) {
    const half = Math.max(1, Math.floor(period / 2));
    const sq = Math.max(1, Math.round(Math.sqrt(period)));
    const wHalf = wma(values, half);
    const wFull = wma(values, period);
    const diff = values.map((_, i) => (wHalf[i] != null && wFull[i] != null) ? 2 * wHalf[i] - wFull[i] : null);
    const out = new Array(values.length).fill(null);
    const denom = sq * (sq + 1) / 2;
    for (let i = sq - 1; i < diff.length; i++) {
      let sum = 0, ok = true;
      for (let k = 0; k < sq; k++) {
        const v = diff[i - sq + 1 + k];
        if (v == null) { ok = false; break; }
        sum += v * (k + 1);
      }
      out[i] = ok ? sum / denom : null;
    }
    return out;
  }

  // ---- time formatting ------------------------------------------------------
  const PTZ = 'America/Los_Angeles';
  const fTime = new Intl.DateTimeFormat('ru-RU', { timeZone: PTZ, hour: '2-digit', minute: '2-digit' });
  const fDay = new Intl.DateTimeFormat('ru-RU', { timeZone: PTZ, day: '2-digit', month: 'short' });
  const fFull = new Intl.DateTimeFormat('ru-RU', { timeZone: PTZ, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  function barMs(bar) {
    const raw = bar && (bar.t || bar.time_utc || bar.time || bar.timestamp);
    const ms = Date.parse(raw || '');
    return Number.isFinite(ms) ? ms : null;
  }

  // Parse indicator spec strings: 'ma:9', 'ema:21', 'vol', 'macd', 'rsi', 'rsi:14'.
  function parseIndicators(list) {
    const overlays = [];
    const panes = [];
    (list || []).forEach((raw) => {
      const spec = String(raw || '').toLowerCase().trim();
      if (!spec) return;
      const [kind, arg] = spec.split(':');
      const n = parseInt(arg, 10);
      if (kind === 'ma' || kind === 'sma') overlays.push({ type: 'sma', period: n || 20 });
      else if (kind === 'ema') overlays.push({ type: 'ema', period: n || 21 });
      else if (kind === 'hma') overlays.push({ type: 'hma', period: n || 21 });
      else if (kind === 'vol' || kind === 'volume') panes.push({ type: 'vol' });
      else if (kind === 'macd') panes.push({ type: 'macd', fast: 12, slow: 26, signal: 9 });
      else if (kind === 'rsi') panes.push({ type: 'rsi', period: n || 14 });
    });
    return { overlays, panes };
  }

  function indicatorWarmup(indicators) {
    let warmup = 80;
    (indicators && indicators.overlays || []).forEach((item) => {
      warmup = Math.max(warmup, (Number(item.period) || 20) * 3);
    });
    (indicators && indicators.panes || []).forEach((item) => {
      if (item.type === 'macd') warmup = Math.max(warmup, ((Number(item.slow) || 26) + (Number(item.signal) || 9)) * 3);
      else if (item.type === 'rsi') warmup = Math.max(warmup, (Number(item.period) || 14) * 4);
    });
    return Math.min(360, Math.max(80, Math.round(warmup)));
  }

  // =========================================================================
  class Chart {
    constructor(host, opts) {
      opts = opts || {};
      this.host = host;
      this.instrument = opts.instrument || '';
      this.timeframe = opts.timeframe || '';
      this.bars = [];
      this.indicators = parseIndicators(opts.indicators || ['vol']);
      this.style = Object.assign({ upColor: '#34d399', downColor: '#ff6b81',
        upFill: '#34d399', downFill: '#ff6b81', bodyWidth: 0.7,
        wickWidth: 1, borderWidth: 1, fillOpacity: 0.85, background: '#0b1018' }, opts.style || {});
      this.drawings = Array.isArray(opts.drawings) ? opts.drawings.slice() : [];
      this.tool = null;
      this.selectedDrawingId = null;
      this.priceScale = 1;
      // Right price-axis width in css px, draggable by the owner (40..200).
      this.axisW = clamp(Number((opts.style && opts.style.axisWidth) || 62), 40, 200);
      this.listeners = { crosshair: [], drawing: [], drawingSelect: [], drawingChange: [], viewport: [] };

      // Viewport over the bar array: `count` visible bars ending at `offset`
      // (offset = index of the right-most visible bar; -1 means "latest").
      this.view = { count: opts.initialBars || 120, offset: -1 };
      this.minBars = 12;
      this.maxBars = 4000;

      this.cursor = null;       // {x,y} in css px, or null
      this._dragging = null;    // {startX, startOffset}
      this._drawingDrag = null;
      this._axisDrag = null;
      this._paneDrag = null;    // { index, startY, startH }
      this._axisWidthDrag = null; // { startX, startW } — resize the price column
      this._raf = null;
      this.paneHeights = Object.assign({}, opts.paneHeights || {});  // index → height px
      this.aspect = opts.aspect || 'auto';  // 'auto' | 'square' | 'wide'
      // When false, last-price tag must not look like a live quote.
      this.livePriceEnabled = opts.livePriceEnabled !== false;
      // Direction of the most recent live price change. Candle colour still
      // follows close-vs-open, while the current-price line follows the last
      // actual tick (the behaviour traders expect from a live price marker).
      this.livePriceDirection = 0;

      this._build();
      this._wire();
      this._empty();
    }

    setLivePriceEnabled(on) {
      const next = !!on;
      if (this.livePriceEnabled === next) return this;
      this.livePriceEnabled = next;
      this._schedule();
      return this;
    }

    // ---- DOM scaffold -------------------------------------------------------
    _build() {
      this.host.classList.add('ce-host');
      this.host.innerHTML = '';
      this.canvas = document.createElement('canvas');
      this.canvas.className = 'ce-canvas';
      this.host.appendChild(this.canvas);
      // Floating OHLC legend (top-left) + empty-state overlay.
      this.legend = document.createElement('div');
      this.legend.className = 'ce-legend';
      this.host.appendChild(this.legend);
      this.emptyEl = document.createElement('div');
      this.emptyEl.className = 'ce-empty';
      this.host.appendChild(this.emptyEl);
      this.loadingEl = document.createElement('div');
      this.loadingEl.className = 'ce-loading';
      this.loadingEl.innerHTML = '<div class="ce-empty-mark"></div><div class="ce-empty-tx">Загрузка…</div>';
      this.host.appendChild(this.loadingEl);
      this.ctx = this.canvas.getContext('2d');
      this.host.style.background = this.style.background || '';
      this._applyAspect();
    }

    setLoading(on, msg) {
      if (!this.loadingEl) return this;
      if (msg) { const tx = this.loadingEl.querySelector('.ce-empty-tx'); if (tx) tx.textContent = msg; }
      this.loadingEl.classList.toggle('show', !!on);
      return this;
    }
    // Aspect ratio preset for the host element. The chart does not resize the
    // window — it applies a padding-based intrinsic ratio to the host element
    // via inline style, which the window's flexbox then respects.
    setAspect(aspect) {
      this.aspect = aspect || 'auto';
      this._applyAspect(); this._schedule(); return this;
    }
    _applyAspect() {
      if (this.aspect === 'square') {
        this.host.style.aspectRatio = '1 / 1';
      } else if (this.aspect === 'wide') {
        this.host.style.aspectRatio = '16 / 9';
      } else {
        this.host.style.aspectRatio = '';
      }
    }
    getPaneHeights() { return Object.assign({}, this.paneHeights); }
    setPaneHeights(heights) { this.paneHeights = Object.assign({}, heights || {}); this._schedule(); return this; }

    _wire() {
      this._ro = new ResizeObserver(() => this.resize());
      this._ro.observe(this.host);

      this._onMove = (e) => {
        this.cursor = this._eventPoint(e);
        if (this._drawingDrag && this._geometry) {
          const drawing = this.drawings.find(row => row.id === this._drawingDrag.id);
          if (drawing) {
            const point = this._drawingPoint(this.cursor, this._geometry);
            if (drawing.type === 'trendline' && Array.isArray(drawing.points)) {
              const part = this._drawingDrag.part;
              if (part === 'p1') drawing.points[0] = point;
              else if (part === 'p2') drawing.points[1] = point;
              else if (this._drawingDrag.start) {
                const st = this._drawingDrag.start;
                const dPrice = point.price - st.price, dIndex = point.index - st.index;
                drawing.points = st.points.map(pt => {
                  const idx = Math.round(pt.index + dIndex);
                  const bar = this.bars[idx];
                  return { price: pt.price + dPrice, index: idx,
                    time: bar && (bar.t || bar.time_utc || bar.time || null) };
                });
              }
            } else {
              drawing.price = point.price;
              if (drawing.type !== 'line') { drawing.index = point.index; drawing.time = point.time; }
            }
            this._schedule();
          }
        } else if (this._axisDrag && this._axisDrag.kind === 'time') {
          const delta = this.cursor.x - this._axisDrag.startX;
          // NinjaTrader/TopStep convention: drag the time axis RIGHT to compress
          // (more bars come in), drag LEFT to expand (fewer, wider bars).
          const factor = Math.exp(delta / 180);
          this.view.count = clamp(Math.round(this._axisDrag.startCount * factor), this.minBars,
            Math.min(this.maxBars, Math.max(this.minBars, this.bars.length)));
          this._setOffset(this._resolvedOffset());
        } else if (this._axisDrag && this._axisDrag.kind === 'price') {
          const delta = this.cursor.y - this._axisDrag.startY;
          this.priceScale = clamp(this._axisDrag.startScale * Math.exp(delta / 180), 0.2, 8);
          this._schedule();
        } else if (this._paneDrag) {
          // Dragging a pane separator: adjust that pane's height.
          const dy = this.cursor.y - this._paneDrag.startY;
          if (!this.paneHeights) this.paneHeights = {};
          this.paneHeights[this._paneDrag.index] = Math.max(40, Math.min(400, this._paneDrag.startH - dy));
          this._schedule();
        } else if (this._axisWidthDrag) {
          // Drag the price column LEFT to widen it, RIGHT to narrow it.
          const dx = this.cursor.x - this._axisWidthDrag.startX;
          this.axisW = clamp(this._axisWidthDrag.startW - dx, 40, 200);
          this._schedule();
        } else if (this._dragging) {
          const dxBars = Math.round((this._dragging.startX - this.cursor.x) / this._barW);
          this._setOffset(this._dragging.startOffset + dxBars);
        }
        this._schedule();
      };
      this._onLeave = () => { this.cursor = null; this._emitCrosshair(null); this._schedule(); };
      this._onDown = (e) => {
        if (e.button !== 0) return;
        const p = this._eventPoint(e);
        if (this.tool && this._geometry && p.x <= this._geometry.plotW &&
            p.y >= this._geometry.main.top && p.y <= this._geometry.main.top + this._geometry.main.height) {
          e.preventDefault();
          const point = this._drawingPoint(p, this._geometry);
          if (this.tool.type === 'trendline') {
            // Two-click placement: first click sets the start, second the end.
            if (!this._pendingTrend) { this._pendingTrend = { p1: point }; this._schedule(); return; }
            const drawing = Object.assign({}, this.tool, {
              id: this.tool.id || ('dr_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7)),
              points: [this._pendingTrend.p1, point],
              createdAt: new Date().toISOString(), status: 'active',
            });
            delete drawing.price;
            this.drawings.push(drawing);
            this.selectedDrawingId = drawing.id;
            this.tool = null; this._pendingTrend = null;
            this.host.classList.remove('ce-drawing');
            this._emit('drawing', drawing);
            this._emit('drawingSelect', drawing);
            this._schedule();
            return;
          }
          const drawing = Object.assign({}, this.tool, {
            id: this.tool.id || ('dr_' + Date.now() + '_' + Math.random().toString(36).slice(2, 7)),
            price: point.price, index: point.index, time: point.time,
            createdAt: new Date().toISOString(), status: 'active',
          });
          this.drawings.push(drawing);
          this.selectedDrawingId = drawing.id;
          this.tool = null;
          this.host.classList.remove('ce-drawing');
          this._emit('drawing', drawing);
          this._emit('drawingSelect', drawing);
          this._schedule();
          return;
        }
        const hit = this._hitDrawing(p);
        if (hit) {
          e.preventDefault();
          this.selectedDrawingId = hit.id;
          this._emit('drawingSelect', hit);
          if (!hit.locked) {
            this._drawingDrag = { id: hit.id, part: this._lastHitPart || 'whole' };
            if (hit.type === 'trendline' && (this._lastHitPart === 'whole' || !this._lastHitPart)) {
              const cp = this._drawingPoint(p, this._geometry);
              this._drawingDrag.start = { price: cp.price, index: cp.index,
                points: (hit.points || []).map(pt => Object.assign({}, pt)) };
            }
          }
          this.host.classList.add('ce-grabbing');
          this._schedule();
          return;
        }
        this.selectedDrawingId = null;
        this._emit('drawingSelect', null);
        if (this._geometry && p.y >= this._geometry.priceBottom) {
          this._axisDrag = { kind: 'time', startX: p.x, startCount: this.view.count };
          this.host.classList.add('ce-grabbing'); return;
        }
        // Grab the plot/price-axis boundary (±5px) to resize the price column.
        if (this._geometry && p.y < this._geometry.priceBottom &&
            Math.abs(p.x - this._geometry.plotW) <= 5) {
          e.preventDefault();
          this._axisWidthDrag = { startX: p.x, startW: this.axisW };
          this.host.style.cursor = 'col-resize';
          return;
        }
        if (this._geometry && p.x >= this._geometry.plotW) {
          this._axisDrag = { kind: 'price', startY: p.y, startScale: this.priceScale };
          this.host.classList.add('ce-grabbing'); return;
        }
        // Pane separator drag: 12px grab zone on each subpane top border.
        if (this._geometry) {
          for (const row of (this._geometry.rows || [])) {
            if (row.type === 'main') continue;
            if (Math.abs(p.y - row.top) <= 12 && p.x <= this._geometry.plotW) {
              e.preventDefault();
              this._paneDrag = { index: row.paneIndex, startY: p.y, startH: row.height };
              this.host.style.cursor = 'ns-resize';
              return;
            }
          }
        }
        const x = p.x;
        this._dragging = { startX: x, startOffset: this._resolvedOffset() };
        this.host.classList.add('ce-grabbing');
      };
      this._onUp = () => {
        if (this._drawingDrag) {
          const changed = this.drawings.find(row => row.id === this._drawingDrag.id);
          if (changed) this._emit('drawingChange', changed);
        }
        if (this._paneDrag) {
          this._paneDrag = null; this.host.style.cursor = '';
          this._emit('viewport', { paneHeights: Object.assign({}, this.paneHeights) });
          this._schedule();
        }
        if (this._axisWidthDrag) { this._axisWidthDrag = null; this.host.style.cursor = ''; this._emit('viewport', { axisWidth: this.axisW }); this._schedule(); }
        this._dragging = null; this._drawingDrag = null; this._axisDrag = null;
        this.host.classList.remove('ce-grabbing');
      };
      this._onWheel = (e) => {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 1.15 : 0.87;
        this._zoom(factor, e);
      };
      this._onDbl = () => { this.view.offset = -1; this.view.count = this._defaultCount(); this.priceScale = 1; this._schedule(); };

      this.canvas.addEventListener('mousemove', this._onMove);
      this.canvas.addEventListener('mouseleave', this._onLeave);
      this.canvas.addEventListener('mousedown', this._onDown);
      window.addEventListener('mouseup', this._onUp);
      this.canvas.addEventListener('wheel', this._onWheel, { passive: false });
      this.canvas.addEventListener('dblclick', this._onDbl);
    }

    on(evt, fn) { if (this.listeners[evt]) this.listeners[evt].push(fn); return this; }
    _emit(evt, payload) { (this.listeners[evt] || []).forEach(fn => { try { fn(payload); } catch (e) { /* isolate */ } }); }
    _emitCrosshair(payload) { this._emit('crosshair', payload); }

    _eventPoint(e) {
      const r = this.canvas.getBoundingClientRect();
      const sx = r.width ? (this.canvas.clientWidth / r.width) : 1;
      const sy = r.height ? (this.canvas.clientHeight / r.height) : 1;
      return { x: (e.clientX - r.left) * sx, y: (e.clientY - r.top) * sy };
    }

    _drawingPoint(p, g) {
      const price = g.lo + (1 - (p.y - g.main.top) / g.main.height) * (g.hi - g.lo);
      const iVis = Math.floor(p.x / g.barW);
      if (iVis >= g.vis.length) {
        // Click is in the future zone — project the bar index beyond the last real bar.
        const slotsAhead = iVis - g.vis.length + 1;
        const lastBar = this.bars[this.bars.length - 1];
        const index = this.bars.length - 1 + slotsAhead;
        // Estimate the future bar time using the average bar interval.
        let futureTime = null;
        if (lastBar && this.bars.length >= 2) {
          const prevBar = this.bars[this.bars.length - 2];
          const msPerBar = barMs(lastBar) - barMs(prevBar);
          if (msPerBar > 0) futureTime = new Date(barMs(lastBar) + slotsAhead * msPerBar).toISOString();
        }
        return { price, index, time: futureTime };
      }
      const clampedIVis = clamp(iVis, 0, g.vis.length - 1);
      const index = g.start + clampedIVis;
      const bar = this.bars[index];
      return { price, index, time: bar && (bar.t || bar.time_utc || bar.time || null) };
    }

    _drawingX(d, g) {
      let idx = Number.isFinite(Number(d.index)) ? Number(d.index) : -1;
      if (d.time) {
        const wanted = Date.parse(d.time);
        if (Number.isFinite(wanted)) {
          let best = Infinity;
          for (let i = g.start; i < g.end; i++) {
            const ms = barMs(this.bars[i]);
            if (ms != null && Math.abs(ms - wanted) < best) { best = Math.abs(ms - wanted); idx = i; }
          }
          // Check if it's a future time past the last bar.
          if (best === Infinity || best > 0) {
            const lastMs = barMs(this.bars[this.bars.length - 1]);
            if (Number.isFinite(wanted) && wanted > lastMs && this.bars.length >= 2) {
              const msPerBar = barMs(this.bars[this.bars.length - 1]) - barMs(this.bars[this.bars.length - 2]);
              if (msPerBar > 0) {
                const slotsAhead = Math.round((wanted - lastMs) / msPerBar);
                const futureIVis = g.vis.length + slotsAhead - 1;
                if (futureIVis >= 0) return g.xOf(futureIVis);
              }
            }
          }
        }
      }
      if (idx >= g.end && idx >= this.bars.length) {
        // Future index: map it relative to the last real bar.
        const slotsAhead = idx - (this.bars.length - 1);
        const futureIVis = g.vis.length + slotsAhead - 1;
        return futureIVis >= 0 ? g.xOf(futureIVis) : null;
      }
      return idx >= g.start && idx < g.end ? g.xOf(idx - g.start) : null;
    }

    _hitDrawing(p) {
      const g = this._geometry; if (!g) return null;
      this._lastHitPart = null;
      for (let i = this.drawings.length - 1; i >= 0; i--) {
        const d = this.drawings[i];
        if (d.type === 'trendline' && Array.isArray(d.points) && d.points.length === 2) {
          const x1 = this._drawingX(d.points[0], g), y1 = g.yOf(Number(d.points[0].price));
          const x2 = this._drawingX(d.points[1], g), y2 = g.yOf(Number(d.points[1].price));
          if (x1 == null || x2 == null) continue;
          if (Math.hypot(p.x - x1, p.y - y1) <= 9) { this._lastHitPart = 'p1'; return d; }
          if (Math.hypot(p.x - x2, p.y - y2) <= 9) { this._lastHitPart = 'p2'; return d; }
          if (this._distToSegment(p.x, p.y, x1, y1, x2, y2) <= 6) { this._lastHitPart = 'whole'; return d; }
          continue;
        }
        const y = g.yOf(Number(d.price));
        if (!Number.isFinite(y)) continue;
        if (d.type === 'line' && p.x <= g.plotW && Math.abs(p.y - y) <= 8) { this._lastHitPart = 'whole'; return d; }
        const x = this._drawingX(d, g);
        if (x != null && Math.hypot(p.x - x, p.y - y) <= 14) { this._lastHitPart = 'whole'; return d; }
      }
      return null;
    }

    _distToSegment(px, py, x1, y1, x2, y2) {
      const dx = x2 - x1, dy = y2 - y1;
      const len2 = dx * dx + dy * dy;
      if (len2 === 0) return Math.hypot(px - x1, py - y1);
      let t = ((px - x1) * dx + (py - y1) * dy) / len2;
      t = clamp(t, 0, 1);
      return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
    }

    // ---- data ---------------------------------------------------------------
    setData(bars) {
      const next = normalizeBars(bars);
      // Preserve the viewport across a live refresh so the chart never "jumps"
      // or resets when the feed replaces the bar array every tick. If the user
      // is pinned to the latest bar we keep following; if they panned into
      // history we re-anchor by timestamp so the same time window stays put even
      // when the source returns a different-length window.
      const prev = this.bars;
      const hadData = prev.length > 0;
      let anchorMs = null;
      if (this.view.offset !== -1 && hadData) {
        const idx = clamp(this._resolvedOffset(), 0, prev.length - 1);
        anchorMs = barMs(prev[idx]);
      }
      this.bars = next;
      if (anchorMs != null && this.bars.length) {
        let found = -1;
        for (let i = this.bars.length - 1; i >= 0; i--) {
          if (barMs(this.bars[i]) === anchorMs) { found = i; break; }
        }
        // Keep the same bar at the right edge; if it rolled off, follow latest.
        this.view.offset = (found < 0 || found >= this.bars.length - 1) ? -1 : found;
      }
      // Only fit the zoom to the data on the FIRST load (e.g. a small instrument).
      // A transient short live response must never shrink the user's zoom — the
      // render clamps the visible count locally, so it restores when data returns.
      if (!hadData && this.bars.length && this.view.count > this.bars.length) {
        this.view.count = Math.max(this.minBars, this.bars.length);
      }
      if (this.view.count < this.minBars) this.view.count = this.minBars;
      if (!this.bars.length) this._empty(this._emptyMessage || 'OFFLINE · нет данных');
      else this.emptyEl.classList.remove('show');
      this._schedule();
      return this;
    }
    setEmptyMessage(msg) {
      this._emptyMessage = msg || '';
      if (!this.bars.length) this._empty(this._emptyMessage || 'OFFLINE · нет данных');
      return this;
    }
    appendBar(bar) {
      const b = normalizeBar(bar);
      if (!b) return this;
      const last = this.bars[this.bars.length - 1];
      const lastMs = barMs(last), nextMs = barMs(b);
      const previousClose = Number(last && last.c), nextClose = Number(b.c);
      if ((!last || lastMs == null || nextMs == null || nextMs >= lastMs)
          && Number.isFinite(previousClose) && Number.isFinite(nextClose)
          && nextClose !== previousClose) {
        this.livePriceDirection = nextClose > previousClose ? 1 : -1;
      }
      if (last && lastMs != null && nextMs != null && lastMs === nextMs) this.bars[this.bars.length - 1] = b; // update forming bar
      else if (last && lastMs != null && nextMs != null && nextMs < lastMs) return this.setData(this.bars.concat([b]));
      else this.bars.push(b);
      this.emptyEl.classList.remove('show');
      this._schedule();
      return this;
    }
    setIndicators(list) {
      this.indicators = parseIndicators(list);
      // Drop stale pane-height overrides for panes that no longer exist so a
      // newly added MACD/RSI pane always gets the default visible height.
      const n = (this.indicators.panes || []).length;
      if (this.paneHeights) {
        Object.keys(this.paneHeights).forEach((k) => {
          if (Number(k) >= n) delete this.paneHeights[k];
        });
      }
      // Force an immediate redraw (not just a coalesced rAF) so apply-to-all
      // updates every window in the same turn, not only the first few.
      if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
      try { this._draw(); } catch (e) { this._schedule(); }
      return this;
    }
    setStyle(style) {
      this.style = Object.assign({}, this.style, style || {});
      this.host.style.background = this.style.background || '';
      if (style && style.axisWidth != null) this.axisW = clamp(Number(style.axisWidth) || 62, 40, 200);
      this._schedule(); return this;
    }
    getAxisWidth() { return this.axisW; }
    setDrawings(drawings) { this.drawings = Array.isArray(drawings) ? drawings.slice() : []; this._schedule(); return this; }
    updateDrawing(id, patch) {
      const row = this.drawings.find(d => d.id === id); if (!row) return null;
      Object.assign(row, patch || {}); this._schedule(); return row;
    }
    removeDrawing(id) {
      const before = this.drawings.length;
      this.drawings = this.drawings.filter(d => d.id !== id);
      if (this.selectedDrawingId === id) this.selectedDrawingId = null;
      this._schedule(); return this.drawings.length !== before;
    }
    selectDrawing(id) {
      this.selectedDrawingId = id || null;
      const row = this.drawings.find(d => d.id === id) || null;
      this._emit('drawingSelect', row); this._schedule(); return row;
    }
    setTool(tool) {
      this.tool = tool ? Object.assign({}, tool) : null;
      this._pendingTrend = null;
      this.host.classList.toggle('ce-drawing', !!this.tool);
      return this;
    }
    latestPrice() { const b = this.bars[this.bars.length - 1]; return b ? b.c : null; }
    // Reset to a clean, fully-visible view (latest bars, auto price scale) —
    // used before a snapshot so the whole recent picture reads well.
    fitView(bars) {
      const want = bars || 140;
      this.view.offset = -1;
      this.view.count = clamp(want, this.minBars, Math.max(this.minBars, this.bars.length || want));
      this.priceScale = 1;
      this.cursor = null;
      this._schedule();
      return this;
    }
    getData() { return this.bars.slice(); }
    // Render the current chart to a downscaled data URL (for snapshots to chat).
    toImage(opts) {
      opts = opts || {};
      const type = opts.type || 'image/jpeg';
      const quality = opts.quality == null ? 0.85 : opts.quality;
      const maxW = opts.maxWidth || 1400;
      try { this._draw(); } catch (e) { /* keep last frame */ }
      const src = this.canvas;
      if (!src || !src.width || !src.height) return '';
      const scale = Math.min(1, maxW / src.width);
      const w = Math.max(1, Math.round(src.width * scale));
      const h = Math.max(1, Math.round(src.height * scale));
      const off = document.createElement('canvas');
      off.width = w; off.height = h;
      const octx = off.getContext('2d');
      octx.fillStyle = this.style.background || '#0b1018';
      octx.fillRect(0, 0, w, h);
      try { octx.drawImage(src, 0, 0, w, h); } catch (e) { return ''; }
      try { return off.toDataURL(type, quality); } catch (e) { return ''; }
    }
    setMeta(instrument, timeframe) {
      if (instrument != null) this.instrument = instrument;
      if (timeframe != null) this.timeframe = timeframe;
      this._schedule();
      return this;
    }

    _empty(msg) {
      this.emptyEl.innerHTML = `<div class="ce-empty-mark"></div><div class="ce-empty-tx">${msg || 'Нет данных'}</div>`;
      this.emptyEl.classList.add('show');
    }

    // ---- viewport helpers ---------------------------------------------------
    // Maximum right-scroll: the user may pan up to FUTURE_BARS candle-widths
    // past the last real bar so they can draw price targets in empty space.
    _futureSlots() { return Math.max(20, Math.round(this.view.count * 0.30)); }
    _resolvedOffset() {
      const n = this.bars.length;
      if (this.view.offset < 0) return n - 1;
      // Allow up to FUTURE_BARS blank slots past the last bar.
      return Math.min(this.view.offset, n - 1 + this._futureSlots());
    }
    _setOffset(next) {
      const n = this.bars.length;
      const maxOff = n - 1 + this._futureSlots();   // allow scrolling into the future
      const minOff = Math.max(this.view.count - 1, this.minBars - 1);
      const clamped = clamp(next, minOff, maxOff);
      // -1 means "pinned to right edge (latest bar)"; only pin if exactly at latest bar.
      this.view.offset = (clamped >= n - 1 && clamped < n) ? -1 : clamped;
      const visible = this._visibleRange();
      this._emit('viewport', {
        count: this.view.count, offset: this.view.offset,
        start: visible.start, end: visible.end, total: this.bars.length,
      });
      this._schedule();
    }
    _defaultCount() { return clamp(120, this.minBars, Math.max(this.minBars, this.bars.length || 120)); }
    _zoom(factor, e) {
      const prev = this.view.count;
      let next = clamp(Math.round(prev * factor), this.minBars, Math.min(this.maxBars, Math.max(this.minBars, this.bars.length)));
      if (next === prev) return;
      this.view.count = next;
      // keep right edge anchored (chart grows from the left, TradingView-style)
      this._setOffset(this._resolvedOffset());
    }

    // ---- rendering ----------------------------------------------------------
    _schedule() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => { this._raf = null; this._draw(); });
    }
    resize() { this._schedule(); }

    _canvasDpr(w, h, transformScale) {
      let dpr = (window.devicePixelRatio || 1) * Math.max(1, transformScale || 1);
      dpr = Math.min(MAX_DPR, dpr);
      if (w > 0 && h > 0) {
        dpr = Math.min(dpr, MAX_CANVAS_SIDE / Math.max(w, h));
        dpr = Math.min(dpr, Math.sqrt(MAX_CANVAS_PIXELS / (w * h)));
      }
      return Math.max(0.35, dpr);
    }

    _measure() {
      const w = this.host.clientWidth || 320;
      const h = this.host.clientHeight || 200;
      const rect = this.host.getBoundingClientRect();
      const transformScale = w ? rect.width / w : 1;
      const dpr = this._canvasDpr(w, h, transformScale);
      if (this.canvas.width !== Math.round(w * dpr) || this.canvas.height !== Math.round(h * dpr)) {
        this.canvas.width = Math.round(w * dpr);
        this.canvas.height = Math.round(h * dpr);
      }
      this.canvas.style.width = w + 'px';
      this.canvas.style.height = h + 'px';
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { w, h };
    }

    _layout(w, h) {
      const axisW = clamp(this.axisW || 62, 40, 200);               // right price axis (draggable)
      const timeH = 22;               // bottom time axis
      const gap = 6;
      const panes = this.indicators.panes;
      // Per-pane height overrides (user-draggable). Default 84px.
      const paneHeights = this.paneHeights || {};
      const subTotal = panes.reduce((sum, p, i) => sum + (paneHeights[i] || 84) + gap, 0);
      const plotW = Math.max(40, w - axisW);
      const mainTop = 0;
      const mainH = Math.max(80, h - timeH - subTotal);
      const rows = [{ type: 'main', top: mainTop, height: mainH }];
      let y = mainTop + mainH + gap;
      panes.forEach((p, i) => {
        const paneH = Math.max(40, paneHeights[i] || 84);
        rows.push({ type: p.type, cfg: p, top: y, height: paneH, paneIndex: i });
        y += paneH + gap;
      });
      return { axisW, timeH, gap, plotW, rows, priceBottom: h - timeH };
    }

    _visibleRange() {
      const n = this.bars.length;
      if (!n) return { start: 0, end: 0, futureSlots: 0 };
      const maxOff = n - 1 + this._futureSlots();
      const off = clamp(this._resolvedOffset(), 0, maxOff);
      const count = clamp(this.view.count, this.minBars, this.maxBars);
      const end = Math.min(off + 1, n);              // real bars end
      const futureSlots = Math.max(0, off + 1 - n); // blank candle slots visible on right
      const start = Math.max(0, end - count + futureSlots);
      return { start, end, futureSlots };
    }

    _draw() {
      const { w, h } = this._measure();
      const ctx = this.ctx;
      ctx.clearRect(0, 0, w, h);
      if (!this.bars.length) { this.legend.classList.remove('show'); return; }

      const P = palette(this.style);
      const L = this._layout(w, h);
      const { start, end, futureSlots } = this._visibleRange();
      const vis = this.bars.slice(start, end);
      if (!vis.length) return;
      const plotW = L.plotW;
      // The view.count determines slot width; future blank slots count toward it.
      const totalSlots = Math.max(this.view.count, vis.length + futureSlots);
      const barW = plotW / totalSlots;
      this._barW = barW;
      // xOf(i): pixel x of the i-th slot's centre (i = 0 is left-most visible slot).
      // Real bars occupy slots [0 … vis.length-1]; future blank slots follow after.
      const xOf = (i) => (i + 0.5) * barW;

      // Shade the future zone so it's obvious where real data ends.
      if (futureSlots > 0) {
        const futureX = vis.length * barW;
        ctx.save();
        ctx.fillStyle = 'rgba(255,255,255,0.022)';
        ctx.fillRect(futureX, 0, plotW - futureX, h);
        // Light dashed vertical separator
        ctx.strokeStyle = 'rgba(255,255,255,0.12)'; ctx.lineWidth = 1; ctx.setLineDash([3, 5]);
        ctx.beginPath(); ctx.moveTo(Math.round(futureX) + 0.5, 0); ctx.lineTo(Math.round(futureX) + 0.5, h); ctx.stroke();
        ctx.setLineDash([]); ctx.restore();
      }

      const bodyRatio = clamp(Number(this.style.bodyWidth) || 0.7, 0.15, 1);
      const candleW = Math.max(1, Math.min(barW * bodyRatio, 24));

      // ---- main price pane ----
      const main = L.rows[0];
      const warmup = indicatorWarmup(this.indicators);
      const calcStart = Math.max(0, start - warmup);
      const calcBars = this.bars.slice(calcStart, end);
      const closes = calcBars.map(b => b.c);
      // overlays computed over full series, sliced to view
      const overlaySeries = this.indicators.overlays.map((o, idx) => {
        const vals = o.type === 'ema' ? ema(closes, o.period)
          : o.type === 'hma' ? hma(closes, o.period)
          : sma(closes, o.period);
        const name = o.type === 'ema' ? 'EMA' : o.type === 'hma' ? 'HMA' : 'MA';
        return { color: P.ma[idx % P.ma.length], label: name + o.period, values: vals, offset: calcStart };
      });
      let lo = Infinity, hi = -Infinity;
      vis.forEach(b => { if (b.l < lo) lo = b.l; if (b.h > hi) hi = b.h; });
      overlaySeries.forEach(s => { for (let i = start; i < end; i++) { const v = s.values[i - s.offset]; if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } } });
      if (!isNum(lo) || !isNum(hi) || lo === hi) { hi = (hi || 1) + 1; lo = (lo || 0) - 1; }
      const padP = (hi - lo) * 0.08; lo -= padP; hi += padP;
      if (this.priceScale !== 1) {
        const center = (hi + lo) / 2;
        const half = ((hi - lo) / 2) * this.priceScale;
        lo = center - half; hi = center + half;
      }
      const yOf = (price) => main.top + (1 - (price - lo) / (hi - lo)) * main.height;

      this._drawGrid(ctx, P, 0, main.top, plotW, main.height, lo, hi, L.axisW, w, yOf, true);

      // candles
      vis.forEach((b, i) => {
        const x = xOf(i);
        const up = b.c >= b.o;
        const col = up ? P.up : P.down;
        ctx.strokeStyle = col;
        ctx.fillStyle = up ? withA(P.upFill, 0.85) : withA(P.downFill, 0.85);
        ctx.lineWidth = clamp(Number(this.style.wickWidth) || 1, 0.5, 5);
        // wick
        ctx.beginPath();
        ctx.moveTo(Math.round(x) + 0.5, yOf(b.h));
        ctx.lineTo(Math.round(x) + 0.5, yOf(b.l));
        ctx.stroke();
        // body
        const yO = yOf(b.o), yC = yOf(b.c);
        const top = Math.min(yO, yC), bh = Math.max(1, Math.abs(yC - yO));
        const opacity = this.style.fillOpacity == null ? 0.85 : clamp(Number(this.style.fillOpacity), 0, 1);
        ctx.fillStyle = up ? withA(P.upFill, opacity) : withA(P.downFill, opacity);
        if (opacity > 0) ctx.fillRect(x - candleW / 2, top, candleW, bh);
        ctx.lineWidth = this.style.borderWidth == null ? 1 : clamp(Number(this.style.borderWidth), 0, 5);
        if (ctx.lineWidth > 0) ctx.strokeRect(Math.round(x - candleW / 2) + 0.5, Math.round(top) + 0.5, Math.round(candleW), Math.round(bh));
      });

      // overlays (MA/EMA lines)
      overlaySeries.forEach(s => {
        ctx.strokeStyle = s.color; ctx.lineWidth = 1.4; ctx.beginPath();
        let started = false;
        for (let i = start; i < end; i++) {
          const v = s.values[i - s.offset]; if (v == null) { started = false; continue; }
          const x = xOf(i - start), y = yOf(v);
          if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      });

      // last price marker line + tag (muted when not LIVE)
      const lastBar = this.bars[end - 1];
      if (lastBar) {
        const y = yOf(lastBar.c);
        // A green candle can still be ticking down (and vice versa). The live
        // marker reports the latest movement; before the first live change it
        // safely falls back to the candle direction.
        const up = this.livePriceDirection === 0
          ? lastBar.c >= lastBar.o
          : this.livePriceDirection > 0;
        const live = this.livePriceEnabled !== false;
        const tagColor = live ? (up ? P.up : P.down) : '#6b7280';
        ctx.strokeStyle = withA(tagColor, live ? 0.5 : 0.35); ctx.setLineDash([2, 3]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(plotW, y); ctx.stroke(); ctx.setLineDash([]);
        const label = live ? fmtPrice(lastBar.c) : (`${fmtPrice(lastBar.c)} · OFF`);
        this._axisTag(ctx, P, plotW, y, L.axisW, label, tagColor);
      }

      this._geometry = { start, end, vis, barW, plotW, yOf, lo, hi, main, rows: L.rows, xOf, priceBottom: L.priceBottom };
      this._drawDrawings(ctx, P, this._geometry);

      // ---- subpanes ----
      for (let r = 1; r < L.rows.length; r++) {
        const row = L.rows[r];
        this._drawSubpane(ctx, P, row, { start, end, calcStart, vis, xOf, plotW, axisW: L.axisW, w, closes, totalSlots });
      }

      // ---- cursor management (single pass, correct priority) ----
      if (!this._paneDrag && !this._axisWidthDrag) {
        const p = this.cursor;
        let cur = '';
        if (p) {
          // Pane separator hover (12px zone)
          if (L.rows.some(row => row.type !== 'main' && Math.abs(p.y - row.top) <= 12 && p.x <= L.plotW)) {
            cur = 'ns-resize';
          // Price-axis width drag handle (5px zone on plotW boundary)
          } else if (p.y < L.priceBottom && Math.abs(p.x - L.plotW) <= 5) {
            cur = 'col-resize';
          // Price-axis drag zone
          } else if (p.x >= L.plotW && p.y < L.priceBottom) {
            cur = 'ns-resize';
          // Time-axis drag zone
          } else if (p.y >= L.priceBottom) {
            cur = 'ew-resize';
          }
        }
        this.host.style.cursor = cur;
      }

      // ---- bottom time axis ----
      this._drawTimeAxis(ctx, P, vis, start, xOf, L.priceBottom, L.timeH, plotW, futureSlots);

      // ---- crosshair + legend ----
      this._drawCrosshair(ctx, P, L, { start, end, vis, barW, plotW, yOf, lo, hi, main });
      this._drawLegend(P, lastBar, overlaySeries, end - 1);
    }

    _drawDrawings(ctx, P, g) {
      this.drawings.forEach(d => {
        if (d.type === 'trendline') { this._drawTrendline(ctx, g, d); return; }
        const price = Number(d.price); if (!Number.isFinite(price)) return;
        const y = g.yOf(price); if (y < g.main.top - 2 || y > g.main.top + g.main.height + 2) return;
        const color = d.status === 'triggered' ? '#ff6b81' : (d.color || '#fcc55a');
        ctx.save(); ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = d.status === 'triggered' ? 2.4 : 1.5;
        if (d.type === 'line') {
          ctx.setLineDash(d.status === 'triggered' ? [] : [7, 4]);
          ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(g.plotW, y); ctx.stroke(); ctx.setLineDash([]);
        } else {
          const x = this._drawingX(d, g); if (x == null) { ctx.restore(); return; }
          if (d.type === 'arrow' || d.type === 'arrow_up') {
            ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 7, y - 11); ctx.lineTo(x - 3, y - 10);
            ctx.lineTo(x - 3, y - 20); ctx.lineTo(x + 3, y - 20); ctx.lineTo(x + 3, y - 10);
            ctx.lineTo(x + 7, y - 11); ctx.closePath(); ctx.fill();
          } else if (d.type === 'arrow_down') {
            ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 7, y + 11); ctx.lineTo(x - 3, y + 10);
            ctx.lineTo(x - 3, y + 20); ctx.lineTo(x + 3, y + 20); ctx.lineTo(x + 3, y + 10);
            ctx.lineTo(x + 7, y + 11); ctx.closePath(); ctx.fill();
          } else if (d.type === 'flag') {
            ctx.lineWidth = 1.6; ctx.beginPath(); ctx.moveTo(x, y + 8); ctx.lineTo(x, y - 14); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(x, y - 14); ctx.lineTo(x + 14, y - 11); ctx.lineTo(x, y - 4); ctx.closePath(); ctx.fill();
          } else if (d.type === 'target') {
            ctx.lineWidth = 1.6;
            ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2); ctx.stroke();
            ctx.beginPath(); ctx.arc(x, y, 2.4, 0, Math.PI * 2); ctx.fill();
          } else if (d.type === 'label') {
            ctx.beginPath(); ctx.arc(x, y, 2.6, 0, Math.PI * 2); ctx.fill();
          } else {
            ctx.beginPath(); ctx.arc(x, y, d.status === 'triggered' ? 6 : 4.5, 0, Math.PI * 2); ctx.fill();
            ctx.strokeStyle = '#0b1018'; ctx.lineWidth = 1.5; ctx.stroke();
          }
        }
        const label = String(d.label || '').trim();
        if (label) {
          ctx.font = '600 10px Inter, system-ui, sans-serif';
          const tw = Math.min(g.plotW - 12, ctx.measureText(label).width + 12);
          const lx = d.type === 'line' ? 6 : Math.max(4, Math.min(g.plotW - tw - 4, (this._drawingX(d, g) || 6) + 8));
          ctx.globalAlpha = 0.92; ctx.fillStyle = '#111827'; ctx.fillRect(lx, y - 19, tw, 16);
          ctx.globalAlpha = 1; ctx.fillStyle = color; ctx.fillText(label, lx + 6, y - 7);
        }
        if (d.id === this.selectedDrawingId) {
          const hx = d.type === 'line' ? Math.min(g.plotW - 18, 18) : this._drawingX(d, g);
          if (hx != null) {
            ctx.setLineDash([]); ctx.fillStyle = '#ffffff'; ctx.strokeStyle = color; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(hx, y, 5.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
          }
        }
        ctx.restore();
      });
      this._drawPendingTrend(ctx, g);
    }

    _drawTrendline(ctx, g, d) {
      if (!Array.isArray(d.points) || d.points.length !== 2) return;
      const x1 = this._drawingX(d.points[0], g), y1 = g.yOf(Number(d.points[0].price));
      const x2 = this._drawingX(d.points[1], g), y2 = g.yOf(Number(d.points[1].price));
      if (x1 == null || x2 == null) return;
      const color = d.status === 'triggered' ? '#ff6b81' : (d.color || '#fcc55a');
      ctx.save();
      ctx.strokeStyle = color; ctx.lineWidth = d.width || 1.8; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      const label = String(d.label || '').trim();
      if (label) {
        ctx.font = '600 10px Inter, system-ui, sans-serif';
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
        const tw = ctx.measureText(label).width + 12;
        ctx.globalAlpha = 0.92; ctx.fillStyle = '#111827'; ctx.fillRect(mx - tw / 2, my - 18, tw, 16);
        ctx.globalAlpha = 1; ctx.fillStyle = color; ctx.fillText(label, mx - tw / 2 + 6, my - 6);
      }
      if (d.id === this.selectedDrawingId) {
        [[x1, y1], [x2, y2]].forEach(([hx, hy]) => {
          ctx.setLineDash([]); ctx.fillStyle = '#ffffff'; ctx.strokeStyle = color; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.arc(hx, hy, 5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        });
      }
      ctx.restore();
    }

    _drawPendingTrend(ctx, g) {
      if (!this._pendingTrend || !this.cursor) return;
      const px = this._drawingX(this._pendingTrend.p1, g), py = g.yOf(this._pendingTrend.p1.price);
      if (px == null) return;
      ctx.save(); ctx.strokeStyle = (this.tool && this.tool.color) || '#fcc55a';
      ctx.setLineDash([5, 4]); ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(this.cursor.x, this.cursor.y); ctx.stroke();
      ctx.fillStyle = '#ffffff'; ctx.strokeStyle = (this.tool && this.tool.color) || '#fcc55a';
      ctx.setLineDash([]); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, py, 4.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.restore();
    }

    _drawGrid(ctx, P, x0, y0, plotW, paneH, lo, hi, axisW, w, yOf, withLabels) {
      ctx.save();
      ctx.font = '600 11px Inter, system-ui, sans-serif';
      ctx.textBaseline = 'middle';
      const steps = Math.max(2, Math.min(6, Math.round(paneH / 46)));
      for (let g = 0; g <= steps; g++) {
        const val = lo + (g / steps) * (hi - lo);
        const y = yOf(val);
        ctx.strokeStyle = P.grid; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x0 + plotW, y); ctx.stroke();
        if (withLabels) {
          ctx.fillStyle = P.axisText; ctx.textAlign = 'left';
          ctx.fillText(fmtPrice(val), x0 + plotW + 6, y);
        }
      }
      // axis separator
      ctx.strokeStyle = P.gridStrong; ctx.beginPath();
      ctx.moveTo(x0 + plotW + 0.5, y0); ctx.lineTo(x0 + plotW + 0.5, y0 + paneH); ctx.stroke();
      ctx.restore();
    }

    _axisTag(ctx, P, plotW, y, axisW, text, color) {
      ctx.save();
      ctx.font = '10px Inter, system-ui, sans-serif';
      ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
      const h = 15;
      ctx.fillStyle = color;
      ctx.fillRect(plotW, y - h / 2, axisW, h);
      ctx.fillStyle = '#0b1018';
      ctx.fillText(text, plotW + 6, y + 0.5);
      ctx.restore();
    }

    _drawSubpane(ctx, P, row, g) {
      const { start, end, calcStart, vis, xOf, plotW, axisW, closes, totalSlots } = g;
      const localStart = Math.max(0, start - (calcStart || 0));
      const localEnd = Math.max(localStart, end - (calcStart || 0));
      const useTotalSlots = totalSlots || Math.max(this.view.count, vis.length);
      const top = row.top, hgt = row.height;
      // Pane separator + resize handle (12px grab zone indicated by small dots).
      ctx.strokeStyle = P.gridStrong; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, top + 0.5); ctx.lineTo(plotW, top + 0.5); ctx.stroke();
      // Draw subtle resize gripper dots in the middle of the separator.
      const mx = Math.round(plotW / 2);
      const nearSep = this.cursor && !this._paneDrag && Math.abs(this.cursor.y - top) <= 12 && this.cursor.x <= plotW;
      ctx.fillStyle = nearSep ? P.text : P.axis;
      for (let dx = -18; dx <= 18; dx += 6) {
        ctx.beginPath(); ctx.arc(mx + dx, top + 0.5, nearSep ? 2 : 1.5, 0, Math.PI * 2); ctx.fill();
      }
      // Cursor is set once at the end of _draw so it is not overridden mid-draw.

      const label = (t) => {
        ctx.save(); ctx.font = '10px Inter, system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
        ctx.fillStyle = P.textDim; ctx.fillText(t, 6, top + 4); ctx.restore();
      };

      if (row.type === 'vol') {
        let mx = 0; vis.forEach(b => { if (b.v > mx) mx = b.v; });
        if (mx <= 0) mx = 1;
        const barW = plotW / useTotalSlots;
        const cw = Math.max(1, Math.min(barW * 0.7, 18));
        vis.forEach((b, i) => {
          const x = xOf(i);
          const bh = (b.v / mx) * (hgt - 12);
          ctx.fillStyle = b.c >= b.o ? P.volUp : P.volDown;
          ctx.fillRect(x - cw / 2, top + hgt - bh, cw, bh);
        });
        label('Объём');
      } else if (row.type === 'macd') {
        const m = macd(closes, row.cfg.fast, row.cfg.slow, row.cfg.signal);
        let lo = Infinity, hi = -Infinity;
        for (let i = localStart; i < localEnd; i++) {
          [m.line[i], m.signal[i], m.hist[i]].forEach(v => { if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } });
        }
        if (!isNum(lo) || !isNum(hi) || lo === hi) { hi = 1; lo = -1; }
        const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
        const yOf = (v) => top + (1 - (v - lo) / (hi - lo)) * hgt;
        // zero line
        ctx.strokeStyle = P.grid; ctx.beginPath(); ctx.moveTo(0, yOf(0)); ctx.lineTo(plotW, yOf(0)); ctx.stroke();
        const barW = plotW / useTotalSlots;
        const cw = Math.max(1, Math.min(barW * 0.72, 16));
        // Optional volume overlay INSIDE the MACD pane (semi-transparent, behind
        // the histogram) — lets the owner read volume without a separate pane.
        if (P.macdVolOverlay) {
          let mxv = 0;
          for (let i = start; i < end; i++) { const b = this.bars[i]; if (b && b.v > mxv) mxv = b.v; }
          if (mxv > 0) {
            const cwv = Math.max(1, Math.min(barW * 0.72, 16));
            for (let i = start; i < end; i++) {
              const b = this.bars[i]; if (!b || !(b.v > 0)) continue;
              const vh = (b.v / mxv) * (hgt - 6);
              ctx.fillStyle = withA(b.c >= b.o ? P.macdUpColor : P.macdDownColor, P.macdVolOpacity);
              ctx.fillRect(xOf(i - start) - cwv / 2, top + hgt - vh, cwv, vh);
            }
          }
        }
        for (let i = localStart; i < localEnd; i++) {
          const hv = m.hist[i]; if (hv == null) continue;
          const x = xOf(i - localStart); const y0 = yOf(0), y1 = yOf(hv);
          const top = Math.min(y0, y1), bh = Math.max(1, Math.abs(y1 - y0));
          if (P.macdFillOn) {
            ctx.fillStyle = hv >= 0 ? P.macdUp : P.macdDown;
            ctx.fillRect(x - cw / 2, top, cw, bh);
          } else {
            ctx.strokeStyle = hv >= 0 ? P.macdLine : P.macdSignal; ctx.lineWidth = 1;
            ctx.strokeRect(Math.round(x - cw / 2) + 0.5, Math.round(top) + 0.5, Math.round(cw), Math.round(bh));
          }
        }
        // optional shaded fills — down to the zero baseline, and between lines,
        // both coloured by MACD-vs-signal direction (NinjaTrader-style).
        const localX = (slot) => xOf(slot);
        if (P.macdFillToZero) this._macdFillToZero(ctx, m.line, m.signal, localStart, localEnd, localX, yOf, P);
        if (P.macdFillBetween) this._macdFillBetween(ctx, m.line, m.signal, localStart, localEnd, localX, yOf, P);
        this._paneLine(ctx, m.line, localStart, localEnd, localX, yOf, P.macdLine, 1.5);
        this._paneLine(ctx, m.signal, localStart, localEnd, localX, yOf, P.macdSignal, 1.5);
        label('MACD ' + row.cfg.fast + '·' + row.cfg.slow + '·' + row.cfg.signal);
      } else if (row.type === 'rsi') {
        const r = rsi(closes, row.cfg.period);
        const yOf = (v) => top + (1 - (v - 0) / 100) * hgt;
        [30, 50, 70].forEach(lvl => {
          ctx.strokeStyle = lvl === 50 ? P.grid : P.gridStrong;
          ctx.setLineDash(lvl === 50 ? [] : [2, 3]);
          ctx.beginPath(); ctx.moveTo(0, yOf(lvl)); ctx.lineTo(plotW, yOf(lvl)); ctx.stroke(); ctx.setLineDash([]);
          ctx.fillStyle = P.textDim; ctx.font = '9px Inter, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
          ctx.fillText(String(lvl), plotW + 6, yOf(lvl));
        });
        const localX = (slot) => xOf(slot);
        this._paneLine(ctx, r, localStart, localEnd, localX, yOf, P.rsi, 1.4);
        label('RSI ' + row.cfg.period);
      }
      // axis separator for subpane
      ctx.strokeStyle = P.gridStrong; ctx.beginPath();
      ctx.moveTo(plotW + 0.5, top); ctx.lineTo(plotW + 0.5, top + hgt); ctx.stroke();
    }

    _paneLine(ctx, arr, start, end, xOf, yOf, color, lw) {
      ctx.strokeStyle = color; ctx.lineWidth = lw || 1.2; ctx.beginPath();
      let started = false;
      for (let i = start; i < end; i++) {
        const v = arr[i]; if (v == null) { started = false; continue; }
        const x = xOf(i - start), y = yOf(v);
        if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // Fill the band between the MACD and signal lines, green where MACD is above
    // the signal and red where it is below (per segment, so crossings look clean).
    _macdFillBetween(ctx, line, signal, start, end, xOf, yOf, P) {
      ctx.save();
      for (let i = start; i < end - 1; i++) {
        const a0 = line[i], a1 = line[i + 1], b0 = signal[i], b1 = signal[i + 1];
        if (a0 == null || a1 == null || b0 == null || b1 == null) continue;
        const x0 = xOf(i - start), x1 = xOf(i + 1 - start);
        const up = (a0 - b0) >= 0;
        ctx.fillStyle = withA(up ? P.macdUpColor : P.macdDownColor, P.macdBetweenOpacity);
        ctx.beginPath();
        ctx.moveTo(x0, yOf(a0)); ctx.lineTo(x1, yOf(a1));
        ctx.lineTo(x1, yOf(b1)); ctx.lineTo(x0, yOf(b0));
        ctx.closePath(); ctx.fill();
      }
      ctx.restore();
    }

    // Fill from the MACD line down to the zero baseline (highlights the whole
    // area to the bottom of the pane).
    _macdFillToZero(ctx, line, signal, start, end, xOf, yOf, P) {
      ctx.save();
      const yz = yOf(0);
      for (let i = start; i < end - 1; i++) {
        const v0 = line[i], v1 = line[i + 1]; if (v0 == null || v1 == null) continue;
        const ref = signal && signal[i] != null ? signal[i] : 0;
        const up = (v0 - ref) >= 0;
        const x0 = xOf(i - start), x1 = xOf(i + 1 - start);
        ctx.fillStyle = withA(up ? P.macdUpColor : P.macdDownColor, P.macdZeroOpacity);
        ctx.beginPath();
        ctx.moveTo(x0, yOf(v0)); ctx.lineTo(x1, yOf(v1));
        ctx.lineTo(x1, yz); ctx.lineTo(x0, yz);
        ctx.closePath(); ctx.fill();
      }
      ctx.restore();
    }

    _drawTimeAxis(ctx, P, vis, start, xOf, top, timeH, plotW, futureSlots) {
      ctx.save();
      ctx.font = '600 11px Inter, system-ui, sans-serif';
      ctx.fillStyle = P.axisText; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.strokeStyle = P.gridStrong; ctx.beginPath(); ctx.moveTo(0, top + 0.5); ctx.lineTo(plotW, top + 0.5); ctx.stroke();
      const n = vis.length;
      const total = n + (futureSlots || 0);
      const step = Math.max(1, Math.ceil(total / 8));
      let lastDayKey = '';
      // Real bar labels
      for (let i = 0; i < n; i += step) {
        const ms = barMs(vis[i]); if (ms == null) continue;
        const d = new Date(ms);
        const dayKey = fDay.format(d);
        const showDay = dayKey !== lastDayKey; lastDayKey = dayKey;
        const lbl = showDay ? dayKey : fTime.format(d);
        const x = xOf(i);
        ctx.strokeStyle = P.grid; ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + 4); ctx.stroke();
        ctx.fillStyle = showDay ? P.axisStrong : P.axisText;
        ctx.fillText(lbl, x, top + timeH / 2 + 2);
      }
      // Future projected labels (when panned right)
      if (futureSlots > 0 && n >= 2) {
        const lastMs = barMs(vis[n - 1]);
        const prevMs = barMs(vis[n - 2]);
        const msPerBar = lastMs != null && prevMs != null ? (lastMs - prevMs) : null;
        if (msPerBar && msPerBar > 0) {
          // start from the first future slot that lands on a step boundary
          const iFirst = n - ((n - 1) % step); // align to step grid
          for (let slot = iFirst; slot < total; slot += step) {
            if (slot < n) continue;
            const slotsAhead = slot - n + 1;
            const ms = lastMs + slotsAhead * msPerBar;
            const d = new Date(ms);
            const dayKey = fDay.format(d);
            const showDay = dayKey !== lastDayKey; lastDayKey = dayKey;
            const lbl = showDay ? dayKey : fTime.format(d);
            const x = xOf(slot);
            ctx.strokeStyle = 'rgba(255,255,255,0.06)'; ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + 4); ctx.stroke();
            ctx.fillStyle = P.textDim;
            ctx.globalAlpha = 0.55;
            ctx.fillText(lbl, x, top + timeH / 2 + 2);
            ctx.globalAlpha = 1;
          }
        }
      }
      ctx.restore();
    }

    _drawCrosshair(ctx, P, L, g) {
      if (!this.cursor) return;
      const { start, vis, barW, plotW, yOf, lo, hi, main } = g;
      const cx = this.cursor.x, cy = this.cursor.y;
      if (cx < 0 || cx > plotW) { this._emitCrosshair(null); return; }
      const iVis = clamp(Math.floor(cx / barW), 0, vis.length - 1);
      const globalIdx = start + iVis;
      const bar = this.bars[globalIdx];
      const snapX = (iVis + 0.5) * barW;
      ctx.save();
      ctx.strokeStyle = P.cross; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      // vertical
      ctx.beginPath(); ctx.moveTo(Math.round(snapX) + 0.5, 0); ctx.lineTo(Math.round(snapX) + 0.5, L.priceBottom); ctx.stroke();
      // horizontal (only within main pane band for readability)
      if (cy >= main.top && cy <= main.top + main.height) {
        ctx.beginPath(); ctx.moveTo(0, Math.round(cy) + 0.5); ctx.lineTo(plotW, Math.round(cy) + 0.5); ctx.stroke();
        const price = lo + (1 - (cy - main.top) / main.height) * (hi - lo);
        this._axisTag(ctx, P, plotW, cy, L.axisW, fmtPrice(price), P.crossBg);
        ctx.fillStyle = P.text; ctx.font = '10px Inter, sans-serif'; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
        ctx.fillText(fmtPrice(price), plotW + 6, cy);
      }
      ctx.setLineDash([]);
      // time tag on bottom axis
      if (bar) {
        const ms = barMs(bar);
        if (ms != null) {
          const tx = fFull.format(new Date(ms));
          ctx.font = '10px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          const tw = ctx.measureText(tx).width + 12;
          ctx.fillStyle = P.crossBg; ctx.fillRect(snapX - tw / 2, L.priceBottom + 1, tw, L.timeH - 2);
          ctx.fillStyle = P.text; ctx.fillText(tx, snapX, L.priceBottom + L.timeH / 2 + 1);
        }
      }
      ctx.restore();
      this._emitCrosshair(bar ? { index: globalIdx, bar } : null);
      if (bar) this._drawLegend(P, bar, null, globalIdx, true);
    }

    _drawLegend(P, bar, overlays, idx, fromCursor) {
      if (!bar || this.style.legendMode === 'hidden') { this.legend.classList.remove('show'); return; }
      const up = bar.c >= bar.o;
      const chg = bar.c - bar.o;
      const pct = bar.o ? (chg / bar.o) * 100 : 0;
      const col = up ? 'var(--pos)' : 'var(--neg)';
      const ohlc = `<span class="ce-k">O</span>${fmtPrice(bar.o)} <span class="ce-k">H</span>${fmtPrice(bar.h)} <span class="ce-k">L</span>${fmtPrice(bar.l)} <span class="ce-k">C</span><b style="color:${col}">${fmtPrice(bar.c)}</b>`;
      const chgTx = `<span style="color:${col}">${chg >= 0 ? '+' : ''}${fmtPrice(chg)} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)</span>`;
      const vol = isNum(bar.v) && bar.v > 0 ? ` <span class="ce-k">V</span>${fmtVol(bar.v)}` : '';
      this.legend.innerHTML =
        `<span class="ce-sym">${escapeHtml(this.instrument || '')}</span>` +
        `<span class="ce-tf">${escapeHtml(this.timeframe || '')}</span>` +
        (this.style.legendMode === 'full' ? `<span class="ce-ohlc">${ohlc} ${chgTx}${vol}</span>` : '');
      this.legend.classList.add('show');
    }

    destroy() {
      if (this._ro) this._ro.disconnect();
      if (this._raf) cancelAnimationFrame(this._raf);
      this.canvas.removeEventListener('mousemove', this._onMove);
      this.canvas.removeEventListener('mouseleave', this._onLeave);
      this.canvas.removeEventListener('mousedown', this._onDown);
      window.removeEventListener('mouseup', this._onUp);
      this.canvas.removeEventListener('wheel', this._onWheel);
      this.canvas.removeEventListener('dblclick', this._onDbl);
      this.listeners = { crosshair: [], drawing: [], drawingSelect: [], drawingChange: [], viewport: [] };
    }
  }

  // ---- helpers --------------------------------------------------------------
  function normalizeBars(bars) {
    const rows = [];
    (Array.isArray(bars) ? bars : []).forEach((bar, seq) => {
      const row = normalizeBar(bar);
      if (!row) return;
      rows.push({ row, seq, ms: barMs(row) });
    });
    rows.sort((a, b) => {
      if (a.ms == null && b.ms == null) return a.seq - b.seq;
      if (a.ms == null) return 1;
      if (b.ms == null) return -1;
      return a.ms - b.ms || a.seq - b.seq;
    });
    const out = [];
    const byTime = new Map();
    rows.forEach((item) => {
      if (item.ms == null) { out.push(item.row); return; }
      const key = String(item.ms);
      const existing = byTime.get(key);
      if (existing == null) {
        byTime.set(key, out.length);
        out.push(item.row);
      } else {
        out[existing] = item.row;
      }
    });
    return filterBadBars(out);
  }
  function filterBadBars(rows) {
    const out = [];
    let prevClose = null;
    rows.forEach((row) => {
      if (!row || row.o <= 0 || row.h <= 0 || row.l <= 0 || row.c <= 0) return;
      if (row.h < row.l) return;
      if (prevClose != null && prevClose > 0) {
        const hi = Math.max(row.h, row.o, row.c);
        const lo = Math.min(row.l, row.o, row.c);
        if (hi / prevClose > MAX_BAR_PRICE_JUMP || prevClose / lo > MAX_BAR_PRICE_JUMP) return;
      }
      out.push(row);
      prevClose = row.c;
    });
    return out;
  }
  function normalizeBar(b) {
    if (!b || typeof b !== 'object') return null;
    const o = Number(b.o != null ? b.o : b.open);
    const h = Number(b.h != null ? b.h : b.high);
    const l = Number(b.l != null ? b.l : b.low);
    const c = Number(b.c != null ? b.c : b.close);
    if (![o, h, l, c].every(Number.isFinite)) return null;
    const v = Number(b.v != null ? b.v : (b.volume != null ? b.volume : 0));
    const t = b.t || b.time_utc || b.time || b.timestamp || null;
    return {
      o,
      h: Math.max(h, o, c),
      l: Math.min(l, o, c),
      c,
      v: Number.isFinite(v) ? Math.max(0, v) : 0,
      t,
    };
  }
  function withA(color, a) {
    const c = String(color || '').trim();
    if (c.startsWith('#')) {
      let hex = c.slice(1);
      if (hex.length === 3) hex = hex.split('').map(x => x + x).join('');
      const n = parseInt(hex, 16);
      return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
    }
    if (c.startsWith('rgb')) return c.replace(/rgba?\(([^)]+)\)/, (_, inner) => {
      const parts = inner.split(',').slice(0, 3).map(s => s.trim());
      return `rgba(${parts.join(',')},${a})`;
    });
    return c;
  }
  // Brighten a colour toward white by `factor` (1 = unchanged, >1 lighter,
  // <1 darker). Lets axis labels be tuned for readability without a theme change.
  function mixWhite(color, factor) {
    let f = Number(factor);
    if (!Number.isFinite(f)) f = 1;
    f = clamp(f, 0.4, 1.8);
    const hex = String(color || '').trim();
    if (f === 1 || !hex.startsWith('#')) return hex;
    let h = hex.slice(1);
    if (h.length === 3) h = h.split('').map(x => x + x).join('');
    const n = parseInt(h, 16);
    let r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    if (f >= 1) { const t = f - 1; r += (255 - r) * t; g += (255 - g) * t; b += (255 - b) * t; }
    else { r *= f; g *= f; b *= f; }
    const cl = (x) => clamp(Math.round(x), 0, 255);
    return `rgb(${cl(r)},${cl(g)},${cl(b)})`;
  }
  function fmtPrice(v) {
    if (!Number.isFinite(v)) return '—';
    const a = Math.abs(v);
    const dec = a >= 1000 ? 2 : a >= 100 ? 2 : a >= 1 ? 2 : 4;
    return v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  function fmtVol(v) {
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return String(Math.round(v));
  }
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  }

  window.ChartEngine = {
    create(host, opts) { return new Chart(host, opts); },
    _math: { sma, ema, macd, rsi },
  };
})();
