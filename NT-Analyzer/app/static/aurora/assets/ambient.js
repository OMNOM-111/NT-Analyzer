/* =====================================================================
   AmbientBackground — the deepest animated layer of StratForge AI.
   A single <canvas> that renders a calm, premium "AI trading command
   center" backdrop: soft cyan/violet glow, slow data-waves and a sparse
   field of drifting particles. One canvas, capped particle counts, FPS
   throttling, pauses on tab hide, and honours prefers-reduced-motion.

   No build step, no dependencies, CSP-safe (script-src 'self').

   Layering (see theme.css):
     z-index 0 → .ambient-bg  (this canvas)
     z-index 1 → .ambient-vignette (static grid + edge darkening)
     z-index 2 → .app (the whole interface)

   Public API (window.Ambient):
     setMode('off' | 'subtle' | 'medium')
     setReduceMotion('auto' | 'on' | 'off')
     getMode() / getReduceMotion()
     refresh()   — re-read device tier and rebuild the scene
   ===================================================================== */
(function () {
  'use strict';

  var MODE_KEY = 'app.bg';           // 'off' | 'subtle' | 'medium'
  var MOTION_KEY = 'app.reduceMotion'; // 'auto' | 'on' | 'off'
  var DEFAULT_MODE = 'subtle';
  var DEFAULT_MOTION = 'auto';
  var MAX_BG_CANVAS_SIDE = 2560;
  var MAX_BG_CANVAS_PIXELS = 2500000;

  // Intensity presets (desktop baseline). Mobile / low-end scales these down.
  var PRESETS = {
    subtle: { particles: 64, waves: 2, blobs: 2, fps: 30, pAlpha: 0.55, wAlpha: 0.16, bAlpha: 0.05, speed: 0.55 },
    medium: { particles: 104, waves: 3, blobs: 3, fps: 40, pAlpha: 0.72, wAlpha: 0.22, bAlpha: 0.07, speed: 0.8 },
  };

  var COLORS = {
    cyan: [31, 201, 255],
    violet: [138, 86, 255],
    green: [52, 211, 153],
  };

  function store(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
  }
  function save(key, val) { try { localStorage.setItem(key, val); } catch (e) { /* storage disabled */ } }

  function prefersReducedMotion() {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  }
  function isMobile() {
    try { return window.matchMedia('(max-width: 760px)').matches; } catch (e) { return window.innerWidth <= 760; }
  }
  // Rough "is this a weak device" heuristic — trims particles and effects.
  function isLowEnd() {
    var cores = navigator.hardwareConcurrency || 8;
    var mem = navigator.deviceMemory || 8;
    return cores <= 4 || mem <= 4;
  }

  var A = {
    mode: normalizeMode(store(MODE_KEY, DEFAULT_MODE)),
    motion: normalizeMotion(store(MOTION_KEY, DEFAULT_MOTION)),
    canvas: null,
    ctx: null,
    vignette: null,
    w: 0, h: 0, dpr: 1,
    raf: 0,
    running: false,
    last: 0,
    t: 0,
    dtSec: 0.016,
    particles: [],
    waves: [],
    blobs: [],
    sprites: {},
    preset: null,
  };

  function normalizeMode(m) { return (m === 'off' || m === 'medium' || m === 'subtle') ? m : DEFAULT_MODE; }
  function normalizeMotion(m) { return (m === 'on' || m === 'off' || m === 'auto') ? m : DEFAULT_MOTION; }

  function isTradingDesktop() {
    return /\/desktop\.html$/i.test(location.pathname || '');
  }

  // Resolve whether the scene should animate given the motion setting.
  function shouldAnimate() {
    if (A.mode === 'off') return false;
    if (A.motion === 'off') return true;
    if (A.motion === 'on') return false;
    return !prefersReducedMotion(); // 'auto'
  }

  function rand(a, b) { return a + Math.random() * (b - a); }
  function rgba(rgb, a) { return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + a + ')'; }

  // A soft round glow sprite (pre-rendered once per colour — cheap to blit).
  function makeSprite(rgb) {
    var size = 64;
    var c = document.createElement('canvas');
    c.width = c.height = size;
    var g = c.getContext('2d');
    var grd = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    grd.addColorStop(0, rgba(rgb, 0.95));
    grd.addColorStop(0.35, rgba(rgb, 0.35));
    grd.addColorStop(1, rgba(rgb, 0));
    g.fillStyle = grd;
    g.fillRect(0, 0, size, size);
    return c;
  }

  function buildScene() {
    if (A.mode === 'off') { A.particles = []; A.waves = []; A.blobs = []; return; }
    var p = PRESETS[A.mode] || PRESETS.subtle;
    // Device-tier scaling.
    var scale = 1;
    if (isMobile()) scale *= 0.5;
    if (isLowEnd()) scale *= 0.6;
    var count = Math.max(12, Math.round(p.particles * scale));
    var blobCount = Math.max(1, Math.min(p.blobs, isMobile() || isLowEnd() ? 2 : p.blobs));
    A.preset = p;

    // Sprites
    A.sprites.cyan = A.sprites.cyan || makeSprite(COLORS.cyan);
    A.sprites.violet = A.sprites.violet || makeSprite(COLORS.violet);
    A.sprites.green = A.sprites.green || makeSprite(COLORS.green);

    // Particles — mostly cyan, a few violet, a rare green.
    A.particles = [];
    for (var i = 0; i < count; i++) {
      var roll = Math.random();
      var sprite = roll > 0.82 ? A.sprites.violet : (roll > 0.94 ? A.sprites.green : A.sprites.cyan);
      A.particles.push({
        x: Math.random(), y: Math.random(),
        vx: rand(-0.018, 0.018) * p.speed,   // normalized units / second
        vy: rand(-0.05, -0.015) * p.speed,   // gentle upward drift / second
        r: rand(0.6, 2.2),
        a: rand(0.25, 1) * p.pAlpha,
        tw: rand(0.4, 1.6),          // twinkle frequency
        ph: rand(0, Math.PI * 2),    // phase
        sprite: sprite,
      });
    }

    // Data-waves — slow horizontal sine bands.
    A.waves = [];
    for (var wI = 0; wI < p.waves; wI++) {
      A.waves.push({
        base: rand(0.28, 0.82),
        amp: rand(0.02, 0.06),
        len: rand(0.7, 1.4),
        speed: rand(0.03, 0.07) * p.speed * (wI % 2 ? -1 : 1),
        phase: rand(0, Math.PI * 2),
        color: wI % 3 === 1 ? COLORS.violet : (wI % 3 === 2 ? COLORS.green : COLORS.cyan),
        alpha: p.wAlpha * rand(0.7, 1.05),
      });
    }

    // Glow blobs — large, very soft, slowly breathing.
    A.blobs = [];
    for (var bI = 0; bI < blobCount; bI++) {
      A.blobs.push({
        x: rand(0.1, 0.9), y: rand(0.05, 0.7),
        r: rand(0.35, 0.6),
        drift: rand(0.01, 0.03) * p.speed,
        phase: rand(0, Math.PI * 2),
        color: bI % 2 ? COLORS.violet : COLORS.cyan,
        alpha: p.bAlpha,
      });
    }
  }

  function ensureNodes() {
    if (A.canvas) return;
    var canvas = document.createElement('canvas');
    canvas.className = 'ambient-bg';
    canvas.setAttribute('aria-hidden', 'true');
    var vignette = document.createElement('div');
    vignette.className = 'ambient-vignette';
    vignette.setAttribute('aria-hidden', 'true');
    // Insert at the very start of <body> so they sit behind everything.
    if (document.body.firstChild) {
      document.body.insertBefore(vignette, document.body.firstChild);
      document.body.insertBefore(canvas, document.body.firstChild);
    } else {
      document.body.appendChild(canvas);
      document.body.appendChild(vignette);
    }
    A.canvas = canvas;
    A.vignette = vignette;
    A.ctx = canvas.getContext('2d');
  }

  function resize() {
    if (!A.canvas) return;
    A.dpr = Math.min(window.devicePixelRatio || 1, isMobile() || isLowEnd() ? 1.25 : 1.5);
    A.w = window.innerWidth;
    A.h = window.innerHeight;
    if (A.w > 0 && A.h > 0) {
      A.dpr = Math.min(A.dpr, MAX_BG_CANVAS_SIDE / Math.max(A.w, A.h));
      A.dpr = Math.min(A.dpr, Math.sqrt(MAX_BG_CANVAS_PIXELS / (A.w * A.h)));
      A.dpr = Math.max(0.4, A.dpr);
    }
    A.canvas.width = Math.round(A.w * A.dpr);
    A.canvas.height = Math.round(A.h * A.dpr);
    A.canvas.style.width = A.w + 'px';
    A.canvas.style.height = A.h + 'px';
    A.ctx.setTransform(A.dpr, 0, 0, A.dpr, 0, 0);
  }

  function drawBlobs() {
    var ctx = A.ctx;
    for (var i = 0; i < A.blobs.length; i++) {
      var b = A.blobs[i];
      var breathe = 0.5 + 0.5 * Math.sin(A.t * b.drift + b.phase);
      var cx = (b.x + Math.sin(A.t * b.drift * 0.6 + b.phase) * 0.04) * A.w;
      var cy = (b.y + Math.cos(A.t * b.drift * 0.5 + b.phase) * 0.03) * A.h;
      var rad = b.r * Math.max(A.w, A.h) * (0.85 + breathe * 0.25);
      var grd = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad);
      grd.addColorStop(0, rgba(b.color, b.alpha * (0.7 + breathe * 0.5)));
      grd.addColorStop(1, rgba(b.color, 0));
      ctx.fillStyle = grd;
      ctx.fillRect(0, 0, A.w, A.h);
    }
  }

  function drawWaves() {
    var ctx = A.ctx;
    var step = Math.max(14, Math.round(A.w / 60));
    for (var i = 0; i < A.waves.length; i++) {
      var wv = A.waves[i];
      ctx.beginPath();
      for (var x = -step; x <= A.w + step; x += step) {
        var nx = x / A.w;
        var y = (wv.base + Math.sin((nx * wv.len * Math.PI * 2) + A.t * wv.speed + wv.phase) * wv.amp) * A.h;
        if (x === -step) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = rgba(wv.color, wv.alpha);
      ctx.lineWidth = 1.2;
      ctx.stroke();
    }
  }

  function drawParticles(animate) {
    var ctx = A.ctx;
    ctx.globalCompositeOperation = 'lighter';
    for (var i = 0; i < A.particles.length; i++) {
      var p = A.particles[i];
      if (animate) {
        p.x += p.vx * A.dtSec;
        p.y += p.vy * A.dtSec;
        if (p.y < -0.02) { p.y = 1.02; p.x = Math.random(); }
        if (p.x < -0.02) p.x = 1.02; else if (p.x > 1.02) p.x = -0.02;
      }
      var tw = animate ? (0.6 + 0.4 * Math.sin(A.t * p.tw + p.ph)) : 0.85;
      var size = p.r * 8;
      var alpha = p.a * tw;
      ctx.globalAlpha = alpha;
      ctx.drawImage(p.sprite, p.x * A.w - size / 2, p.y * A.h - size / 2, size, size);
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = 'source-over';
  }

  function renderFrame(animate) {
    if (!A.ctx) return;
    A.ctx.clearRect(0, 0, A.w, A.h);
    if (A.mode === 'off') return;
    drawBlobs();
    drawWaves();
    drawParticles(animate);
  }

  function loop(now) {
    if (!A.running) return;
    A.raf = requestAnimationFrame(loop);
    var interval = 1000 / (A.preset ? A.preset.fps : 30);
    if (now - A.last < interval) return;
    var dt = A.last ? (now - A.last) : 16;
    A.last = now;
    A.dtSec = Math.min(dt, 60) * 0.001;  // clamp so tab-resume doesn't jump
    A.t += A.dtSec * 6;                    // scaled time for pleasant motion
    renderFrame(true);
  }

  function start() {
    if (A.running) return;
    if (A.mode === 'off') return;
    A.running = true;
    A.last = 0;
    A.raf = requestAnimationFrame(loop);
  }
  function stop() {
    A.running = false;
    if (A.raf) cancelAnimationFrame(A.raf);
    A.raf = 0;
  }

  // Apply the current mode/motion: build scene, then either animate or render
  // a single static frame (reduced motion) or clear (off).
  function apply() {
    ensureNodes();
    if (A.mode === 'off' || isTradingDesktop()) {
      stop();
      if (A.canvas) A.canvas.style.display = 'none';
      if (A.vignette) A.vignette.classList.add('is-off');
      document.documentElement.setAttribute('data-ambient', 'off');
      return;
    }
    if (A.canvas) A.canvas.style.display = '';
    if (A.vignette) A.vignette.classList.remove('is-off');
    document.documentElement.setAttribute('data-ambient', A.mode);
    resize();
    buildScene();
    if (shouldAnimate() && !document.hidden) {
      start();
    } else {
      stop();
      renderFrame(false); // one calm static frame
    }
  }

  // ---- public API ----
  function setMode(mode) {
    A.mode = normalizeMode(mode);
    save(MODE_KEY, A.mode);
    apply();
  }
  function setReduceMotion(val) {
    A.motion = normalizeMotion(val);
    save(MOTION_KEY, A.motion);
    apply();
  }

  window.Ambient = {
    setMode: setMode,
    setReduceMotion: setReduceMotion,
    getMode: function () { return A.mode; },
    getReduceMotion: function () { return A.motion; },
    refresh: apply,
  };

  // ---- lifecycle ----
  var resizeTimer = 0;
  window.addEventListener('resize', function () {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (A.mode !== 'off') apply(); }, 200);
  });

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { stop(); }
    else if (A.mode !== 'off' && shouldAnimate()) { start(); }
  });

  // React live to OS reduced-motion changes when set to 'auto'.
  try {
    window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', function () {
      if (A.motion === 'auto' && A.mode !== 'off') apply();
    });
  } catch (e) { /* older browsers */ }

  function boot() { apply(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
