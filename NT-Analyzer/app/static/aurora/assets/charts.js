/* =====================================================================
   Charts — tiny dependency-free canvas charting for the prototype.
   Crisp on HiDPI, auto-resizes, light hover tooltips.
   API attached to window.Chart
   ===================================================================== */
(function () {
  const COLORS = ['#6e8bff', '#34d399', '#fcc55a', '#ff6b81', '#4fd1e0', '#b48cff', '#f59e6b', '#5ad19a', '#8a7cff', '#e879c9'];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
  }
  function fmtMoney(v) {
    const s = v < 0 ? '-' : '';
    const a = Math.abs(v);
    return s + '$' + a.toLocaleString('en-US', { maximumFractionDigits: 0 });
  }
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[ch]);
  }

  // Prepare a canvas for DPR and return {ctx, w, h}
  function setup(canvas, height) {
    const box = canvas.parentElement;
    const w = canvas.clientWidth || (box && box.clientWidth) || 600;
    const h = height || canvas.clientHeight || 200;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
  }

  function bindResize(canvas, draw) {
    if (canvas._ro) canvas._ro.disconnect();
    let raf = null;
    const ro = new ResizeObserver(() => {
      // The canvas may have been removed (e.g. innerHTML replaced on re-render);
      // stop observing instead of drawing on a detached node.
      if (!canvas.isConnected) { ro.disconnect(); return; }
      if (raf) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => { if (canvas.isConnected) draw(); });
    });
    ro.observe(canvas.parentElement);
    canvas._ro = ro;
  }

  function ensureTip(canvas) {
    let tip = canvas.parentElement.querySelector('.chart-tip');
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'chart-tip';
      canvas.parentElement.appendChild(tip);
    }
    return tip;
  }

  /* ---------- Line / area chart (one or many series) ---------- */
  // series: [{ name, color, values:[{x?,y}] | [numbers], dash? }]
  function line(canvas, series, opts) {
    opts = opts || {};
    const height = opts.height || 240;
    const pad = { l: 54, r: 16, t: 14, b: 24 };
    const visible = () => series.filter(s => !s._hidden);

    function draw() {
      const { ctx, w, h } = setup(canvas, height);
      ctx.clearRect(0, 0, w, h);
      const vis = visible();
      const norm = vis.map(s => s.values.map((v, i) => (typeof v === 'number' ? { x: i, y: v } : v)));
      let maxLen = 0; norm.forEach(a => maxLen = Math.max(maxLen, a.length));
      if (!maxLen) return;
      let minY = Infinity, maxY = -Infinity;
      norm.forEach(a => a.forEach(p => { minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); }));
      if (opts.baseZero) minY = Math.min(minY, 0);
      if (minY === maxY) { maxY += 1; minY -= 1; }
      const padY = (maxY - minY) * 0.08; minY -= padY; maxY += padY;

      const X = i => pad.l + (i / (maxLen - 1)) * (w - pad.l - pad.r);
      const Y = v => pad.t + (1 - (v - minY) / (maxY - minY)) * (h - pad.t - pad.b);

      // grid + y labels
      ctx.font = '10px Inter, sans-serif';
      ctx.textBaseline = 'middle';
      const lines = 4;
      for (let g = 0; g <= lines; g++) {
        const val = minY + (g / lines) * (maxY - minY);
        const y = Y(val);
        ctx.strokeStyle = 'rgba(255,255,255,0.045)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
        ctx.fillStyle = css('--tx-4');
        ctx.textAlign = 'right';
        ctx.fillText(opts.money ? fmtMoney(val) : Math.round(val), pad.l - 8, y);
      }
      // zero line
      if (minY < 0 && maxY > 0) {
        const y0 = Y(0);
        ctx.strokeStyle = 'rgba(255,255,255,0.16)';
        ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(pad.l, y0); ctx.lineTo(w - pad.r, y0); ctx.stroke(); ctx.setLineDash([]);
      }

      // x labels
      if (opts.labels) {
        ctx.fillStyle = css('--tx-4'); ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        const step = Math.ceil(opts.labels.length / 7);
        opts.labels.forEach((lab, i) => { if (i % step === 0) ctx.fillText(lab, X(i), h - pad.b + 6); });
      }

      // series
      norm.forEach((arr, si) => {
        const s = vis[si];
        const color = s.color || COLORS[si % COLORS.length];
        // area for single-series or opts.area
        if (opts.area && vis.length === 1) {
          const grad = ctx.createLinearGradient(0, pad.t, 0, h - pad.b);
          grad.addColorStop(0, hexA(color, 0.28));
          grad.addColorStop(1, hexA(color, 0));
          ctx.beginPath();
          arr.forEach((p, i) => { const x = X(i), y = Y(p.y); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
          ctx.lineTo(X(arr.length - 1), Y(minY)); ctx.lineTo(X(0), Y(minY)); ctx.closePath();
          ctx.fillStyle = grad; ctx.fill();
        }
        ctx.beginPath();
        ctx.lineWidth = 2; ctx.strokeStyle = color; ctx.lineJoin = 'round';
        if (s.dash) ctx.setLineDash([5, 4]);
        arr.forEach((p, i) => { const x = X(i), y = Y(p.y); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
        ctx.stroke(); ctx.setLineDash([]);
        // last point dot
        const last = arr[arr.length - 1];
        ctx.fillStyle = color; ctx.beginPath(); ctx.arc(X(arr.length - 1), Y(last.y), 3, 0, 7); ctx.fill();
      });

      canvas._geo = { X, Y, norm, vis, pad, w, h, maxLen };
    }

    // hover tooltip
    const tip = ensureTip(canvas);
    canvas.onmousemove = e => {
      const geo = canvas._geo; if (!geo) return;
      const r = canvas.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const i = Math.round(((mx - geo.pad.l) / (geo.w - geo.pad.l - geo.pad.r)) * (geo.maxLen - 1));
      if (i < 0 || i >= geo.maxLen) { tip.style.opacity = 0; return; }
      const rows = geo.vis.map((s, si) => {
        const p = geo.norm[si][i]; if (!p) return '';
        const c = s.color || COLORS[si % COLORS.length];
        return `<div class="t-val" style="color:${c}">${s.name ? s.name + ': ' : ''}${opts.money ? fmtMoney(p.y) : p.y.toFixed(1)}</div>`;
      }).join('');
      const lab = (opts.labels && opts.labels[i]) || ('#' + i);
      tip.innerHTML = `<div class="t-lab">${esc(lab)}</div>${rows}`;
      tip.style.left = geo.X(i) + 'px';
      tip.style.top = geo.pad.t + 'px';
      tip.style.opacity = 1;
    };
    canvas.onmouseleave = () => { tip.style.opacity = 0; };

    draw();
    bindResize(canvas, draw);
    return { redraw: draw, toggle: (name) => { const s = series.find(x => x.name === name); if (s) { s._hidden = !s._hidden; draw(); } return s ? !s._hidden : false; } };
  }

  /* ---------- Bar chart (vertical, +/- colored) ---------- */
  // data: [{ label, tooltipLabel?, tooltipDetail?, value, color? }]
  function bars(canvas, data, opts) {
    opts = opts || {};
    const height = opts.height || 220;
    const pad = { l: 50, r: 12, t: 12, b: 40 };
    function draw() {
      const { ctx, w, h } = setup(canvas, height);
      ctx.clearRect(0, 0, w, h);
      if (!data.length) return;
      let min = 0, max = 0;
      data.forEach(d => { min = Math.min(min, d.value); max = Math.max(max, d.value); });
      if (min === max) max += 1;
      const padv = (max - min) * 0.12; max += padv; if (min < 0) min -= padv;
      const Y = v => pad.t + (1 - (v - min) / (max - min)) * (h - pad.t - pad.b);
      const bw = (w - pad.l - pad.r) / data.length;
      const innerW = Math.min(bw * 0.62, 46);

      ctx.font = '10px Inter'; ctx.textBaseline = 'middle';
      for (let g = 0; g <= 4; g++) {
        const val = min + (g / 4) * (max - min); const y = Y(val);
        ctx.strokeStyle = 'rgba(255,255,255,0.045)'; ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
        ctx.fillStyle = css('--tx-4'); ctx.textAlign = 'right';
        ctx.fillText(opts.money ? fmtMoney(val) : Math.round(val), pad.l - 8, y);
      }
      const y0 = Y(0);
      data.forEach((d, i) => {
        const cx = pad.l + bw * i + bw / 2;
        const x = cx - innerW / 2;
        const y = Y(d.value);
        const col = d.color || (d.value >= 0 ? css('--pos') : css('--neg'));
        const top = Math.min(y, y0), hgt = Math.abs(y - y0);
        const grad = ctx.createLinearGradient(0, top, 0, top + hgt);
        grad.addColorStop(0, hexA(col, 0.95)); grad.addColorStop(1, hexA(col, 0.55));
        roundRect(ctx, x, top, innerW, Math.max(hgt, 2), 4); ctx.fillStyle = grad; ctx.fill();
        // label
        ctx.fillStyle = css('--tx-3'); ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        ctx.font = '10px Inter';
        ctx.fillText(d.label, cx, h - pad.b + 7);
      });
      canvas._barGeo = { data, pad, w, h, bw, innerW };
    }
    const tip = ensureTip(canvas);
    canvas.onmousemove = event => {
      const geo = canvas._barGeo;
      if (!geo || !geo.data.length) return;
      const rect = canvas.getBoundingClientRect();
      const mx = event.clientX - rect.left;
      const index = Math.floor((mx - geo.pad.l) / geo.bw);
      if (index < 0 || index >= geo.data.length || mx > geo.w - geo.pad.r) {
        tip.style.opacity = 0;
        return;
      }
      const item = geo.data[index];
      const label = item.tooltipLabel || item.fullLabel || item.label || `#${index + 1}`;
      const value = opts.money ? fmtMoney(Number(item.value || 0)) : Number(item.value || 0).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
      const detail = item.tooltipDetail ? `<div class="t-detail">${esc(item.tooltipDetail)}</div>` : '';
      tip.innerHTML = `<div class="t-lab">${esc(label)}</div><div class="t-val">${esc(value)}</div>${detail}`;
      tip.style.left = Math.max(geo.pad.l, Math.min(geo.w - geo.pad.r, geo.pad.l + geo.bw * index + geo.bw / 2)) + 'px';
      tip.style.top = Math.max(32, event.clientY - rect.top) + 'px';
      tip.style.opacity = 1;
    };
    canvas.onmouseleave = () => { tip.style.opacity = 0; };
    draw(); bindResize(canvas, draw);
    return { redraw: draw };
  }

  /* ---------- Sparkline ---------- */
  function spark(canvas, values, opts) {
    opts = opts || {};
    function draw() {
      const { ctx, w, h } = setup(canvas, opts.height || 32);
      ctx.clearRect(0, 0, w, h);
      if (!values.length) return;
      const min = Math.min(...values), max = Math.max(...values);
      const X = i => (i / (values.length - 1)) * (w - 2) + 1;
      const Y = v => h - 3 - ((v - min) / (max - min || 1)) * (h - 6);
      const up = values[values.length - 1] >= values[0];
      const color = opts.color || (up ? css('--pos') : css('--neg'));
      const grad = ctx.createLinearGradient(0, 0, 0, h);
      grad.addColorStop(0, hexA(color, 0.30)); grad.addColorStop(1, hexA(color, 0));
      ctx.beginPath(); values.forEach((v, i) => { const x = X(i), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.lineTo(X(values.length - 1), h); ctx.lineTo(X(0), h); ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
      ctx.beginPath(); values.forEach((v, i) => { const x = X(i), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.lineWidth = 1.6; ctx.strokeStyle = color; ctx.lineJoin = 'round'; ctx.stroke();
    }
    draw(); bindResize(canvas, draw);
    return { redraw: draw };
  }

  /* ---------- Donut ---------- */
  // segments: [{ value, color, label }]
  function donut(canvas, segments, opts) {
    opts = opts || {};
    function draw() {
      const { ctx, w, h } = setup(canvas, opts.height || 160);
      ctx.clearRect(0, 0, w, h);
      const total = segments.reduce((a, s) => a + s.value, 0) || 1;
      const cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2 - 6, r = R * 0.62;
      let a0 = -Math.PI / 2;
      segments.forEach(s => {
        const a1 = a0 + (s.value / total) * Math.PI * 2;
        ctx.beginPath(); ctx.arc(cx, cy, R, a0, a1); ctx.arc(cx, cy, r, a1, a0, true); ctx.closePath();
        ctx.fillStyle = s.color; ctx.fill();
        a0 = a1;
      });
      if (opts.center) {
        ctx.fillStyle = css('--tx'); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.font = '700 18px Inter'; ctx.fillText(opts.center, cx, cy - 6);
        if (opts.centerSub) { ctx.font = '10px Inter'; ctx.fillStyle = css('--tx-3'); ctx.fillText(opts.centerSub, cx, cy + 12); }
      }
    }
    draw(); bindResize(canvas, draw);
    return { redraw: draw };
  }

  // helpers
  function roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function hexA(hex, a) {
    hex = hex.replace('#', '');
    if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
    const n = parseInt(hex, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }

  window.Chart = { line, bars, spark, donut, COLORS, fmtMoney };
})();
