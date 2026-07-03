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

  function cssVar(name, fallback) {
    try {
      const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return v || fallback;
    } catch (e) { return fallback; }
  }

  // Resolve theme colours once per draw (cheap; keeps chart in sync with theme).
  function palette() {
    return {
      up: cssVar('--pos', '#34d399'),
      down: cssVar('--neg', '#ff6b81'),
      upFill: cssVar('--pos', '#34d399'),
      downFill: cssVar('--neg', '#ff6b81'),
      grid: 'rgba(255,255,255,0.05)',
      gridStrong: 'rgba(255,255,255,0.10)',
      axis: cssVar('--tx-3', '#8b93a7'),
      text: cssVar('--tx-2', '#aeb6c6'),
      textDim: cssVar('--tx-4', '#5c6478'),
      cross: 'rgba(180,200,255,0.55)',
      crossBg: cssVar('--bg-3', '#1a2030'),
      ma: ['#4fd1e0', '#fcc55a', '#b48cff', '#f59e6b', '#8a7cff'],
      macdUp: 'rgba(52,211,153,0.55)',
      macdDown: 'rgba(255,107,129,0.55)',
      macdLine: '#4fd1e0',
      macdSignal: '#fcc55a',
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
      else if (kind === 'vol' || kind === 'volume') panes.push({ type: 'vol' });
      else if (kind === 'macd') panes.push({ type: 'macd', fast: 12, slow: 26, signal: 9 });
      else if (kind === 'rsi') panes.push({ type: 'rsi', period: n || 14 });
    });
    return { overlays, panes };
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
      this.listeners = { crosshair: [], drawing: [], viewport: [] };

      // Viewport over the bar array: `count` visible bars ending at `offset`
      // (offset = index of the right-most visible bar; -1 means "latest").
      this.view = { count: opts.initialBars || 120, offset: -1 };
      this.minBars = 12;
      this.maxBars = 4000;

      this.cursor = null;       // {x,y} in css px, or null
      this._dragging = null;    // {startX, startOffset}
      this._raf = null;

      this._build();
      this._wire();
      this._empty();
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
      this.ctx = this.canvas.getContext('2d');
    }

    _wire() {
      this._ro = new ResizeObserver(() => this.resize());
      this._ro.observe(this.host);

      this._onMove = (e) => {
        const r = this.canvas.getBoundingClientRect();
        this.cursor = { x: e.clientX - r.left, y: e.clientY - r.top };
        if (this._dragging) {
          const dxBars = Math.round((this._dragging.startX - this.cursor.x) / this._barW);
          this._setOffset(this._dragging.startOffset + dxBars);
        }
        this._schedule();
      };
      this._onLeave = () => { this.cursor = null; this._emitCrosshair(null); this._schedule(); };
      this._onDown = (e) => {
        if (e.button !== 0) return;
        const r = this.canvas.getBoundingClientRect();
        const x = e.clientX - r.left;
        this._dragging = { startX: x, startOffset: this._resolvedOffset() };
        this.host.classList.add('ce-grabbing');
      };
      this._onUp = () => { this._dragging = null; this.host.classList.remove('ce-grabbing'); };
      this._onWheel = (e) => {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 1.15 : 0.87;
        this._zoom(factor, e);
      };
      this._onDbl = () => { this.view.offset = -1; this.view.count = this._defaultCount(); this._schedule(); };

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

    // ---- data ---------------------------------------------------------------
    setData(bars) {
      this.bars = (Array.isArray(bars) ? bars : []).map(normalizeBar).filter(Boolean);
      if (this.view.count > this.bars.length) this.view.count = Math.max(this.minBars, this.bars.length || this.minBars);
      if (!this.bars.length) this._empty('Ожидание данных NinjaTrader…');
      else this.emptyEl.classList.remove('show');
      this._schedule();
      return this;
    }
    appendBar(bar) {
      const b = normalizeBar(bar);
      if (!b) return this;
      const last = this.bars[this.bars.length - 1];
      if (last && barMs(last) === barMs(b)) this.bars[this.bars.length - 1] = b; // update forming bar
      else this.bars.push(b);
      this.emptyEl.classList.remove('show');
      this._schedule();
      return this;
    }
    setIndicators(list) { this.indicators = parseIndicators(list); this._schedule(); return this; }
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
    _resolvedOffset() {
      return this.view.offset < 0 ? (this.bars.length - 1) : this.view.offset;
    }
    _setOffset(next) {
      const maxOff = this.bars.length - 1;
      const minOff = Math.max(this.view.count - 1, this.minBars - 1);
      const clamped = clamp(next, minOff, maxOff);
      this.view.offset = (clamped >= maxOff) ? -1 : clamped;
      this._emit('viewport', { count: this.view.count, offset: this.view.offset });
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

    _measure() {
      const dpr = window.devicePixelRatio || 1;
      const w = this.host.clientWidth || 320;
      const h = this.host.clientHeight || 200;
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
      const axisW = 62;               // right price axis
      const timeH = 22;               // bottom time axis
      const gap = 6;
      const panes = this.indicators.panes;
      const paneH = 84;               // each subpane fixed-ish height
      const subTotal = panes.length * (paneH + gap);
      const plotW = Math.max(40, w - axisW);
      const mainTop = 0;
      const mainH = Math.max(80, h - timeH - subTotal);
      const rows = [{ type: 'main', top: mainTop, height: mainH }];
      let y = mainTop + mainH + gap;
      panes.forEach((p) => { rows.push({ type: p.type, cfg: p, top: y, height: paneH }); y += paneH + gap; });
      return { axisW, timeH, gap, plotW, rows, priceBottom: h - timeH };
    }

    _visibleRange() {
      const n = this.bars.length;
      if (!n) return { start: 0, end: 0 };
      const off = clamp(this._resolvedOffset(), 0, n - 1);
      const count = clamp(this.view.count, this.minBars, this.maxBars);
      const end = off + 1;
      const start = Math.max(0, end - count);
      return { start, end };
    }

    _draw() {
      const { w, h } = this._measure();
      const ctx = this.ctx;
      ctx.clearRect(0, 0, w, h);
      if (!this.bars.length) { this.legend.classList.remove('show'); return; }

      const P = palette();
      const L = this._layout(w, h);
      const { start, end } = this._visibleRange();
      const vis = this.bars.slice(start, end);
      if (!vis.length) return;
      const plotW = L.plotW;
      const barW = plotW / Math.max(this.view.count, vis.length);
      this._barW = barW;
      const candleW = Math.max(1, Math.min(barW * 0.7, 18));
      const xOf = (i) => (i + 0.5) * barW;         // i = index within `vis`

      // ---- main price pane ----
      const main = L.rows[0];
      const closes = this.bars.map(b => b.c);
      // overlays computed over full series, sliced to view
      const overlaySeries = this.indicators.overlays.map((o, idx) => {
        const vals = o.type === 'ema' ? ema(closes, o.period) : sma(closes, o.period);
        return { color: P.ma[idx % P.ma.length], label: (o.type === 'ema' ? 'EMA' : 'MA') + o.period, values: vals };
      });
      let lo = Infinity, hi = -Infinity;
      vis.forEach(b => { if (b.l < lo) lo = b.l; if (b.h > hi) hi = b.h; });
      overlaySeries.forEach(s => { for (let i = start; i < end; i++) { const v = s.values[i]; if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } } });
      if (!isNum(lo) || !isNum(hi) || lo === hi) { hi = (hi || 1) + 1; lo = (lo || 0) - 1; }
      const padP = (hi - lo) * 0.08; lo -= padP; hi += padP;
      const yOf = (price) => main.top + (1 - (price - lo) / (hi - lo)) * main.height;

      this._drawGrid(ctx, P, 0, main.top, plotW, main.height, lo, hi, L.axisW, w, yOf, true);

      // candles
      vis.forEach((b, i) => {
        const x = xOf(i);
        const up = b.c >= b.o;
        const col = up ? P.up : P.down;
        ctx.strokeStyle = col;
        ctx.fillStyle = up ? withA(P.upFill, 0.85) : withA(P.downFill, 0.85);
        ctx.lineWidth = 1;
        // wick
        ctx.beginPath();
        ctx.moveTo(Math.round(x) + 0.5, yOf(b.h));
        ctx.lineTo(Math.round(x) + 0.5, yOf(b.l));
        ctx.stroke();
        // body
        const yO = yOf(b.o), yC = yOf(b.c);
        const top = Math.min(yO, yC), bh = Math.max(1, Math.abs(yC - yO));
        ctx.fillRect(x - candleW / 2, top, candleW, bh);
        ctx.strokeRect(Math.round(x - candleW / 2) + 0.5, Math.round(top) + 0.5, Math.round(candleW), Math.round(bh));
      });

      // overlays (MA/EMA lines)
      overlaySeries.forEach(s => {
        ctx.strokeStyle = s.color; ctx.lineWidth = 1.4; ctx.beginPath();
        let started = false;
        for (let i = start; i < end; i++) {
          const v = s.values[i]; if (v == null) { started = false; continue; }
          const x = xOf(i - start), y = yOf(v);
          if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      });

      // last price marker line + tag
      const lastBar = this.bars[end - 1];
      if (lastBar) {
        const y = yOf(lastBar.c);
        const up = lastBar.c >= lastBar.o;
        ctx.strokeStyle = withA(up ? P.up : P.down, 0.5); ctx.setLineDash([2, 3]); ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(plotW, y); ctx.stroke(); ctx.setLineDash([]);
        this._axisTag(ctx, P, plotW, y, L.axisW, fmtPrice(lastBar.c), up ? P.up : P.down);
      }

      // ---- subpanes ----
      for (let r = 1; r < L.rows.length; r++) {
        const row = L.rows[r];
        this._drawSubpane(ctx, P, row, { start, end, vis, xOf, plotW, axisW: L.axisW, w, closes });
      }

      // ---- bottom time axis ----
      this._drawTimeAxis(ctx, P, vis, start, xOf, L.priceBottom, L.timeH, plotW);

      // ---- crosshair + legend ----
      this._drawCrosshair(ctx, P, L, { start, end, vis, barW, plotW, yOf, lo, hi, main });
      this._drawLegend(P, lastBar, overlaySeries, end - 1);
    }

    _drawGrid(ctx, P, x0, y0, plotW, paneH, lo, hi, axisW, w, yOf, withLabels) {
      ctx.save();
      ctx.font = '10px Inter, system-ui, sans-serif';
      ctx.textBaseline = 'middle';
      const steps = Math.max(2, Math.min(6, Math.round(paneH / 46)));
      for (let g = 0; g <= steps; g++) {
        const val = lo + (g / steps) * (hi - lo);
        const y = yOf(val);
        ctx.strokeStyle = P.grid; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x0 + plotW, y); ctx.stroke();
        if (withLabels) {
          ctx.fillStyle = P.textDim; ctx.textAlign = 'left';
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
      const { start, end, vis, xOf, plotW, axisW, closes } = g;
      const top = row.top, hgt = row.height;
      // pane background frame
      ctx.strokeStyle = P.grid; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, top + 0.5); ctx.lineTo(plotW, top + 0.5); ctx.stroke();

      const label = (t) => {
        ctx.save(); ctx.font = '10px Inter, system-ui, sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
        ctx.fillStyle = P.textDim; ctx.fillText(t, 6, top + 4); ctx.restore();
      };

      if (row.type === 'vol') {
        let mx = 0; vis.forEach(b => { if (b.v > mx) mx = b.v; });
        if (mx <= 0) mx = 1;
        const barW = plotW / Math.max(this.view.count, vis.length);
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
        for (let i = start; i < end; i++) {
          [m.line[i], m.signal[i], m.hist[i]].forEach(v => { if (v != null) { if (v < lo) lo = v; if (v > hi) hi = v; } });
        }
        if (!isNum(lo) || !isNum(hi) || lo === hi) { hi = 1; lo = -1; }
        const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
        const yOf = (v) => top + (1 - (v - lo) / (hi - lo)) * hgt;
        // zero line
        ctx.strokeStyle = P.grid; ctx.beginPath(); ctx.moveTo(0, yOf(0)); ctx.lineTo(plotW, yOf(0)); ctx.stroke();
        const barW = plotW / Math.max(this.view.count, vis.length);
        const cw = Math.max(1, Math.min(barW * 0.7, 14));
        for (let i = start; i < end; i++) {
          const hv = m.hist[i]; if (hv == null) continue;
          const x = xOf(i - start); const y0 = yOf(0), y1 = yOf(hv);
          ctx.fillStyle = hv >= 0 ? P.macdUp : P.macdDown;
          ctx.fillRect(x - cw / 2, Math.min(y0, y1), cw, Math.max(1, Math.abs(y1 - y0)));
        }
        this._paneLine(ctx, m.line, start, end, xOf, yOf, P.macdLine, 1.3);
        this._paneLine(ctx, m.signal, start, end, xOf, yOf, P.macdSignal, 1.3);
        label('MACD 12·26·9');
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
        this._paneLine(ctx, r, start, end, xOf, yOf, P.rsi, 1.4);
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

    _drawTimeAxis(ctx, P, vis, start, xOf, top, timeH, plotW) {
      ctx.save();
      ctx.font = '10px Inter, system-ui, sans-serif';
      ctx.fillStyle = P.textDim; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.strokeStyle = P.gridStrong; ctx.beginPath(); ctx.moveTo(0, top + 0.5); ctx.lineTo(plotW, top + 0.5); ctx.stroke();
      const n = vis.length;
      const step = Math.max(1, Math.ceil(n / 8));
      let lastDayKey = '';
      for (let i = 0; i < n; i += step) {
        const ms = barMs(vis[i]); if (ms == null) continue;
        const d = new Date(ms);
        const dayKey = fDay.format(d);
        const showDay = dayKey !== lastDayKey; lastDayKey = dayKey;
        const label = showDay ? dayKey : fTime.format(d);
        const x = xOf(i);
        ctx.strokeStyle = P.grid; ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, top + 4); ctx.stroke();
        ctx.fillStyle = showDay ? P.text : P.textDim;
        ctx.fillText(label, x, top + timeH / 2 + 2);
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
      if (!bar) { this.legend.classList.remove('show'); return; }
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
        `<span class="ce-ohlc">${ohlc} ${chgTx}${vol}</span>`;
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
      this.listeners = { crosshair: [], drawing: [], viewport: [] };
    }
  }

  // ---- helpers --------------------------------------------------------------
  function normalizeBar(b) {
    if (!b || typeof b !== 'object') return null;
    const o = Number(b.o != null ? b.o : b.open);
    const h = Number(b.h != null ? b.h : b.high);
    const l = Number(b.l != null ? b.l : b.low);
    const c = Number(b.c != null ? b.c : b.close);
    if (![o, h, l, c].every(Number.isFinite)) return null;
    const v = Number(b.v != null ? b.v : (b.volume != null ? b.volume : 0));
    const t = b.t || b.time_utc || b.time || b.timestamp || null;
    return { o, h, l, c, v: Number.isFinite(v) ? v : 0, t };
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
