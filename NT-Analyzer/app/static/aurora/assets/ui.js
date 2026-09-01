/* =====================================================================
   UI shell + helpers shared by every prototype page.
   Builds the left rail + topbar, exposes window.UI helpers.
   ===================================================================== */
(function () {
  // ---- inline icon set (stroke, currentColor) --------------------------------
  const I = {
    overview: '<path d="M3 13h8V3H3v10Zm10 8h8V11h-8v10ZM3 21h8v-6H3v6ZM13 3v6h8V3h-8Z"/>',
    backtest: '<path d="M3 3v18h18"/><path d="M7 14l3-4 3 3 4-6"/>',
    trading: '<path d="M3 17l5-5 4 4 8-9"/><path d="M21 7h-5m5 0v5"/>',
    performance: '<rect x="3" y="12" width="4" height="8" rx="1"/><rect x="10" y="7" width="4" height="13" rx="1"/><rect x="17" y="3" width="4" height="17" rx="1"/>',
    strategies: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    ai: '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><rect x="7" y="7" width="10" height="10" rx="3"/><path d="M10 10h4v4h-4z"/>',
    docs: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    news: '<path d="M4 5h12v14H5a2 2 0 0 1-2-2V6a1 1 0 0 1 1-1Z"/><path d="M16 8h4v9a2 2 0 0 1-2 2h-2M7 9h6M7 13h6M7 16h4"/>',
    trophy: '<path d="M8 4h8v4a4 4 0 0 1-8 0V4Z"/><path d="M8 6H4v2a4 4 0 0 0 4 4M16 6h4v2a4 4 0 0 1-4 4M12 12v5M8 21h8M9 17h6"/>',
    telegram: '<path d="m21 3-4 18-6-5-4 3 1-6 9-7-11 6-4-2 19-7Z"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    chat: '<path d="M21 15a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2v10Z"/><path d="M8 9h8M8 13h5"/>',
    send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z"/>',
    paperclip: '<path d="m21.4 11.6-8.5 8.5a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8"/>',
    pin: '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3-1-6ZM12 14v7"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 4v4h-4"/>',
    play: '<path d="M6 4l14 8-14 8V4Z"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    download: '<path d="M12 3v12M7 11l5 5 5-5M5 21h14"/>',
    trash: '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13h10l1-13"/>',
    star: '<path d="M12 3l2.6 5.6 6.1.6-4.6 4 1.4 6-5.5-3.2L6 19.8l1.4-6-4.6-4 6.1-.6L12 3Z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    bolt: '<path d="M13 2 3 14h7l-1 8 10-12h-7l1-8Z"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3"/>',
    wallet: '<rect x="3" y="6" width="18" height="13" rx="2"/><path d="M3 10h18M17 14h2"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    layers: '<path d="M12 3 2 8l10 5 10-5-10-5ZM2 16l10 5 10-5M2 12l10 5 10-5"/>',
    edit: '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5Z"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    close: '<path d="M18 6 6 18M6 6l12 12"/>',
    arrowUp: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    arrowDown: '<path d="M12 5v14M5 12l7 7 7-7"/>',
    coins: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    spark: '<path d="M12 2v6M12 16v6M2 12h6M16 12h6M5 5l4 4M15 15l4 4M19 5l-4 4M9 15l-4 4"/>',
    dots: '<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
    back: '<path d="M9 6l-6 6 6 6M3 12h13a5 5 0 0 1 5 5v1"/>',
    eraser: '<path d="M3 16l7 7h7M18 13L9 22M16 3l5 5L9 20H4v-5L16 3Z"/>',
    plug: '<path d="M9 2v6M15 2v6M7 8h10v3a5 5 0 0 1-10 0V8ZM12 16v6"/>',
    chart: '<path d="M3 3v18h18"/><path d="M7 14l3-4 3 3 4-6"/>',
    book: '<path d="M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2V5Z"/><path d="M8 7h7M8 11h7"/>',
    bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10 21a2 2 0 0 0 4 0"/>',
    palette: '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.5 0-.5-.3-.9-.6-1.2-.3-.3-.5-.6-.5-1 0-.8.7-1.3 1.5-1.3H15a5 5 0 0 0 5-5c0-4-3.6-7-8-7Z"/><circle cx="7.5" cy="11" r="1"/><circle cx="12" cy="7.5" r="1"/><circle cx="16.5" cy="11" r="1"/>',
    desktop: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M3 13h18M9 21h6M12 17v4M7 9l2.5 2.5L13 8l4 4"/>',
  };
  function icon(name, cls) { return `<svg class="${cls || 'ic'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${I[name] || ''}</svg>`; }
  const APP_NAME = 'StratForge AI';
  const APP_KICKER = 'StratForge AI · NTA Edition';
  let CURRENT_AUTH = null;
  let BUILD_IDENTITY = null;

  // ---- per-environment localStorage namespace --------------------------------
  // Each environment prefixes its persisted UI state so no two contours share
  // local-storage even inside the same browser or a shared parent domain. The
  // namespace is derived synchronously from the origin host (defence in depth on
  // top of the browser's per-origin isolation). Canary and Production use
  // explicit prefixes; Development (localhost) keeps bare keys, so no migration
  // is needed. Mirrors app/runtime_env.local_storage_namespace().
  function lsNamespace() {
    try {
      const host = String(location.hostname || '').toLowerCase();
      if (host === 'canary.stratforges.com' || host.startsWith('canary.')) return 'canary';
      if (host === 'stratforges.com' || host === 'www.stratforges.com' || host.endsWith('.stratforges.com')) return 'production';
    } catch (e) { /* ignore */ }
    return '';
  }
  const LS_NS = lsNamespace();
  function lsKey(name) { return LS_NS ? `${LS_NS}:${name}` : String(name); }

  const RELEASE_ICONS = {
    dev: 'brand/stratforge-dev.png',
    canary: 'brand/stratforge-canary.png',
    beta: 'brand/stratforge-beta.png',
    stable: 'brand/stratforge-mark.png',
  };

  function releasePresentation(environment, channel) {
    if (environment === 'development' && channel === 'dev') {
      return { short: 'DEV', full: 'РАЗРАБОТКА', cls: 'dev', icon: RELEASE_ICONS.dev };
    }
    if (environment === 'canary' && ['beta', 'stable'].includes(channel)) {
      return { short: 'CANARY', full: 'CANARY', cls: 'canary', icon: RELEASE_ICONS.canary };
    }
    if (environment === 'production' && channel === 'beta') {
      return { short: 'BETA', full: 'ПУБЛИЧНАЯ БЕТА', cls: 'beta', icon: RELEASE_ICONS.beta };
    }
    if (environment === 'production' && channel === 'stable') {
      return { short: '', full: 'PRODUCTION', cls: 'stable', icon: RELEASE_ICONS.stable };
    }
    return null;
  }

  function applyReleaseIcon(path) {
    // The rail/brand logo always uses the clean transparent mark. The release
    // variant (a dark square app-icon with a ribbon) is only meaningful as the
    // browser tab favicon — placing it inside the rail produced a boxed
    // "picture-in-a-square" look. The environment is already shown by the
    // coloured DEV/CANARY/BETA text badge next to the brand name.
    let favicon = document.querySelector('link[rel~="icon"]');
    if (!favicon) {
      favicon = document.createElement('link');
      favicon.rel = 'icon';
      document.head.appendChild(favicon);
    }
    favicon.href = path === RELEASE_ICONS.stable ? 'brand/stratforge-icon.ico' : path;
  }

  function applyBuildIdentity(payload) {
    const source = payload || {};
    const deployment = source.deployment && typeof source.deployment === 'object'
      ? source.deployment : source;
    const environment = String(deployment.deployment_environment || deployment.environment || source.deployment_environment || '').toLowerCase();
    const channel = String(deployment.release_channel || '').toLowerCase();
    const version = String(deployment.app_version || deployment.build_version || '').trim();
    const timestamp = String(deployment.build_timestamp_utc || '').trim();
    const buildId = String(deployment.build_id || '').trim();
    const gitSha = String(deployment.git_commit_sha || '').trim();
    const artifactSha = String(deployment.artifact_sha256 || '').trim();
    const dirty = deployment.dirty === true;
    const label = releasePresentation(environment, channel);
    if (!version || !timestamp || !gitSha || !label) return;
    const shortSha = gitSha.slice(0, 7);
    const visibleParts = [`v${version}`, shortSha];
    if (dirty) visibleParts.push('dirty');
    BUILD_IDENTITY = {
      environment, channel, version, timestamp, buildId, gitSha, artifactSha, dirty, label,
    };
    document.documentElement.dataset.deploymentEnvironment = environment;
    document.documentElement.dataset.releaseChannel = channel;
    qsa('[data-release-badge]').forEach(badge => {
      badge.classList.remove('pending', 'dev', 'canary', 'beta', 'stable');
      badge.classList.add(label.cls);
      badge.hidden = !label.short;
      badge.textContent = label.short;
      badge.title = label.short ? `${label.full} — ${environment}` : '';
    });
    qsa('[data-build-meta]').forEach(meta => {
      meta.textContent = visibleParts.join(' · ');
      meta.title = [
        `APP_VERSION=${version}`,
        `DEPLOYMENT_ENV=${environment}`,
        `RELEASE_CHANNEL=${channel}`,
        `BUILD_ID=${buildId || 'local-source'}`,
        `GIT_COMMIT_SHA=${gitSha}`,
        `ARTIFACT_SHA256=${artifactSha || 'not-applicable'}`,
        `BUILD_TIMESTAMP_UTC=${timestamp}`,
        `dirty=${dirty}`,
      ].join('\n');
    });
    applyReleaseIcon(label.icon);
    const baseTitle = String(document.title || APP_NAME).replace(/^\[(DEV|CANARY|BETA|STABLE)\]\s*/, '');
    document.title = label.short ? `[${label.short}] ${baseTitle}` : baseTitle;
    if (CURRENT_AUTH) {
      wireAdminEnvironmentButton();
      wireDevPreviewButton();
      renderDevPreviewBanner();
    }
  }

  async function refreshBuildIdentity(seed) {
    if (seed) applyBuildIdentity(seed);
    if (BUILD_IDENTITY || !(window.API && API.http && API.http.runtimeEnv)) return;
    try { applyBuildIdentity(await API.http.runtimeEnv({ retries: 0 })); }
    catch (e) { /* Version marker remains visibly unresolved instead of guessing. */ }
  }

  // ---- app theme (auto / dark / light) ---------------------------------------
  const THEME_KEY = lsKey('app.theme');
  function loadTheme() { try { return localStorage.getItem(THEME_KEY) || 'auto'; } catch (e) { return 'auto'; } }
  function applyTheme(mode) {
    const m = (mode === 'dark' || mode === 'light') ? mode : 'auto';
    if (document.documentElement) document.documentElement.setAttribute('data-theme', m);
  }
  function setTheme(mode) {
    const m = (mode === 'dark' || mode === 'light') ? mode : 'auto';
    try { localStorage.setItem(THEME_KEY, m); } catch (e) { /* ignore */ }
    applyTheme(m);
  }
  applyTheme(loadTheme());  // apply immediately to avoid a flash before shell builds

  // ---- design settings: animated background · UI density · reduced motion -----
  const BG_KEY = lsKey('app.bg');               // 'off' | 'subtle' | 'medium'
  const DENSITY_KEY = lsKey('app.density');     // 'comfortable' | 'compact'
  const MOTION_KEY = lsKey('app.reduceMotion'); // 'auto' | 'on' | 'off'
  function loadBg() { try { return localStorage.getItem(BG_KEY) || 'subtle'; } catch (e) { return 'subtle'; } }
  function setBg(v) {
    const m = (v === 'off' || v === 'medium') ? v : 'subtle';
    if (window.Ambient) window.Ambient.setMode(m);
    else { try { localStorage.setItem(BG_KEY, m); } catch (e) { /* ignore */ } }
  }
  function loadDensity() { try { return localStorage.getItem(DENSITY_KEY) || 'comfortable'; } catch (e) { return 'comfortable'; } }
  function applyDensity(v) { const m = v === 'compact' ? 'compact' : 'comfortable'; if (document.documentElement) document.documentElement.setAttribute('data-density', m); }
  function setDensity(v) { const m = v === 'compact' ? 'compact' : 'comfortable'; try { localStorage.setItem(DENSITY_KEY, m); } catch (e) { /* ignore */ } applyDensity(m); }
  function loadMotion() { try { return localStorage.getItem(MOTION_KEY) || 'auto'; } catch (e) { return 'auto'; } }
  function applyMotion(v) { const m = (v === 'on' || v === 'off') ? v : 'auto'; if (document.documentElement) document.documentElement.setAttribute('data-reduce-motion', m); }
  function setMotion(v) { const m = (v === 'on' || v === 'off') ? v : 'auto'; try { localStorage.setItem(MOTION_KEY, m); } catch (e) { /* ignore */ } applyMotion(m); if (window.Ambient) window.Ambient.setReduceMotion(m); }
  applyDensity(loadDensity());
  applyMotion(loadMotion());

  const BRAND_MARK = 'brand/stratforge-mark.png';
  // Staff faces: one webm per agent. Paused frame = avatar; hover/typing = play.
  // Orchestrator message faces also TTS the message body (see agentSpeakFromFace).
  // Masters: `/Agents/<Имя>/`; served: `assets/agents/<id>/speaking.webm`.
  // Crop tuned per source framing (verified via tools/_avatar_preview.py).
  const AGENT_AVATAR_IDS = {
    vitek: 'vitek', виктор: 'vitek', витёк: 'vitek', витек: 'vitek', витя: 'vitek',
    manager: 'manager', управляющий: 'manager', orchestrator: 'manager',
    secretary: 'manager', секретарь: 'manager',
    deputy: 'manager', заместитель: 'manager', зам: 'manager',
    marina: 'marina', марина: 'marina',
    tolik: 'tolik', толик: 'tolik',
    nikita: 'nikita', никита: 'nikita',
    ivan: 'ivan', иван: 'ivan',
  };
  const AGENT_FACE_CROP = {
    vitek: { zoom: 2.5, cx: 50, cy: 34.53 },
    manager: { zoom: 2.274, cx: 49.1, cy: 43.63 },
    marina: { zoom: 2.274, cx: 46.32, cy: 43.16 },
    tolik: { zoom: 2.274, cx: 49.93, cy: 44.65 },
    nikita: { zoom: 3.333, cx: 38.89, cy: 31.17 },
    ivan: { zoom: 2.5, cx: 50.14, cy: 51.17 },
  };
  function agentAvatarId(ref) {
    const raw = String(ref == null ? '' : ref).trim();
    if (!raw) return 'vitek';
    const key = raw.toLowerCase();
    if (AGENT_AVATAR_IDS[key]) return AGENT_AVATAR_IDS[key];
    const head = key.split(/[\s·|,(/]+/)[0];
    return AGENT_AVATAR_IDS[head] || 'vitek';
  }
  function agentAvatarUrl(ref) {
    return `assets/agents/${agentAvatarId(ref)}/speaking.webm`;
  }
  function agentFaceReduceMotion() {
    try {
      if (document.documentElement.getAttribute('data-reduce-motion') === 'on') return true;
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { return false; }
  }
  function agentFacePause(face) {
    if (!face) return;
    const video = face.querySelector('video');
    if (!video) return;
    try { video.loop = false; video.pause(); if (video.currentTime) video.currentTime = 0; } catch (e) { /* ignore */ }
    face.classList.remove('playing');
  }
  function agentFacePlay(face, opts) {
    if (!face || agentFaceReduceMotion()) return;
    const video = face.querySelector('video');
    if (!video) return;
    const loop = !!(opts && opts.loop) || face.classList.contains('speaking');
    video.loop = loop;
    face.classList.add('playing');
    const start = () => { video.play().catch(() => {}); };
    if (video.readyState >= 2) start();
    else video.addEventListener('loadeddata', start, { once: true });
  }
  // Hover TTS for Orchestrator message faces: loop webm while reading the
  // message body via OpenAI Speech (or browser speechSynthesis fallback).
  const AGENT_SPEAK = { gen: 0, timer: null, audio: null, url: null, face: null, utter: null };
  const AGENT_SPEAK_HOVER_MS = 350;
  function agentSpeakStop() {
    AGENT_SPEAK.gen += 1;
    if (AGENT_SPEAK.timer) { clearTimeout(AGENT_SPEAK.timer); AGENT_SPEAK.timer = null; }
    if (AGENT_SPEAK.audio) {
      try { AGENT_SPEAK.audio.pause(); AGENT_SPEAK.audio.removeAttribute('src'); AGENT_SPEAK.audio.load(); } catch (e) { /* ignore */ }
      AGENT_SPEAK.audio = null;
    }
    if (AGENT_SPEAK.url) {
      try { URL.revokeObjectURL(AGENT_SPEAK.url); } catch (e) { /* ignore */ }
      AGENT_SPEAK.url = null;
    }
    if (AGENT_SPEAK.utter) {
      AGENT_SPEAK.utter = null;
      try { if (window.speechSynthesis) speechSynthesis.cancel(); } catch (e) { /* ignore */ }
    }
    const face = AGENT_SPEAK.face;
    AGENT_SPEAK.face = null;
    if (face && face.isConnected && !face.classList.contains('speaking')) agentFacePause(face);
  }
  function agentSpeakBrowser(text, face, gen, opts) {
    const options = opts || {};
    if (!window.speechSynthesis || !text) {
      if (gen === AGENT_SPEAK.gen && face && !face.classList.contains('speaking')) agentFacePause(face);
      return;
    }
    try { speechSynthesis.cancel(); } catch (e) { /* ignore */ }
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = String(options.language || options.fallback_voice || 'ru-RU');
    const speed = Number(options.speed);
    utter.rate = Number.isFinite(speed) && speed > 0 ? Math.max(0.5, Math.min(1.8, speed)) : 1.02;
    if (options.voice_gender === 'female') utter.pitch = 1.15;
    else if (options.voice_gender === 'male') utter.pitch = 0.85;
    AGENT_SPEAK.utter = utter;
    try {
      const voices = speechSynthesis.getVoices() || [];
      const lang = utter.lang.toLowerCase();
      const gender = String(options.voice_gender || '').toLowerCase();
      const femaleRe = /female|жен|zira|irina|natalia|helena|katya|samantha|eva|anna/i;
      const maleRe = /male|муж|david|paul|mark|yuri|dmitri|pavel|george|daniel/i;
      const langPool = voices.filter(v => String(v.lang || '').toLowerCase().startsWith(lang.slice(0, 2)))
        .concat(voices.filter(v => /ru/i.test(String(v.lang || ''))));
      const pool = langPool.length ? langPool : voices;
      let match = null;
      if (gender === 'female') match = pool.find(v => femaleRe.test(`${v.name} ${v.voiceURI}`));
      if (gender === 'male') match = pool.find(v => maleRe.test(`${v.name} ${v.voiceURI}`));
      if (!match) match = pool.find(v => String(v.lang || '').toLowerCase().startsWith(lang.slice(0, 2))) || pool[0];
      if (match) utter.voice = match;
    } catch (e) { /* ignore */ }
    const done = () => {
      if (gen !== AGENT_SPEAK.gen) return;
      AGENT_SPEAK.utter = null;
      AGENT_SPEAK.face = null;
      if (face && face.isConnected && !face.classList.contains('speaking')) agentFacePause(face);
    };
    utter.onend = done;
    utter.onerror = done;
    const start = () => { try { speechSynthesis.speak(utter); } catch (e) { done(); } };
    if ((speechSynthesis.getVoices() || []).length) start();
    else {
      speechSynthesis.addEventListener('voiceschanged', start, { once: true });
      setTimeout(start, 250);
    }
  }
  async function agentSpeakPlayAudio(blob, text, face, gen, fallbackOpts) {
    if (gen !== AGENT_SPEAK.gen) return;
    if (!(blob instanceof Blob) || !blob.size) {
      agentSpeakBrowser(text, face, gen, fallbackOpts);
      return;
    }
    const typed = blob.type && /audio\//i.test(blob.type)
      ? blob
      : new Blob([await blob.arrayBuffer()], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(typed);
    AGENT_SPEAK.url = url;
    const audio = new Audio();
    AGENT_SPEAK.audio = audio;
    const done = () => {
      if (gen !== AGENT_SPEAK.gen) return;
      agentSpeakStop();
    };
    audio.onended = done;
    audio.onerror = () => {
      if (gen !== AGENT_SPEAK.gen) return;
      if (AGENT_SPEAK.url) {
        try { URL.revokeObjectURL(AGENT_SPEAK.url); } catch (e) { /* ignore */ }
        AGENT_SPEAK.url = null;
      }
      AGENT_SPEAK.audio = null;
      agentSpeakBrowser(text, face, gen, fallbackOpts);
    };
    audio.src = url;
    try { await audio.play(); }
    catch (e) { agentSpeakBrowser(text, face, gen, fallbackOpts); }
  }
  function agentSpeakFromFace(face) {
    if (!face || !face.classList.contains('orch-msg-face')) return;
    if (face.classList.contains('speaking')) return;
    const msg = face.closest('.orch-msg');
    if (!msg || msg.classList.contains('user')) return;
    const body = msg.querySelector('.orch-msg-body');
    const text = String((body && body.textContent) || '').replace(/\s+/g, ' ').trim();
    if (!text) return;
    agentSpeakStop();
    const gen = AGENT_SPEAK.gen;
    AGENT_SPEAK.face = face;
    agentFacePlay(face, { loop: true });
    AGENT_SPEAK.timer = setTimeout(async () => {
      AGENT_SPEAK.timer = null;
      if (gen !== AGENT_SPEAK.gen) return;
      const agentId = face.getAttribute('data-agent-face') || 'vitek';
      const messageId = face.getAttribute('data-message-id') || '';
      try {
        if (!window.API || API.config.offline || !API.http.aiOrchestratorSpeak) {
          agentSpeakBrowser(text, face, gen, { language: 'ru-RU' });
          return;
        }
        const result = await API.http.aiOrchestratorSpeak({
          text, agent_id: agentId, message_id: messageId,
        });
        if (gen !== AGENT_SPEAK.gen) return;
        if (result && !(result instanceof Blob) && result.fallback === 'browser') {
          agentSpeakBrowser(text, face, gen, result);
          return;
        }
        await agentSpeakPlayAudio(result, text, face, gen, { language: 'ru-RU' });
      } catch (e) {
        if (gen === AGENT_SPEAK.gen) agentSpeakBrowser(text, face, gen, { language: 'ru-RU' });
      }
    }, AGENT_SPEAK_HOVER_MS);
  }
  function agentAvatarHtml(ref, opts) {
    const options = opts || {};
    const speaking = !!options.speaking;
    const cls = options.cls ? ` ${options.cls}` : '';
    const label = String(options.label || ref || 'агент');
    const id = agentAvatarId(ref);
    const src = agentAvatarUrl(ref);
    const crop = AGENT_FACE_CROP[id] || AGENT_FACE_CROP.vitek;
    const attrs = speaking ? ' loop autoplay' : '';
    const style = `--face-zoom:${crop.zoom};--face-cx:${crop.cx};--face-cy:${crop.cy};`;
    const msgAttr = options.messageId ? ` data-message-id="${esc(String(options.messageId))}"` : '';
    return `<span class="agent-face${speaking ? ' speaking' : ''}${cls}" title="${esc(label)}" data-agent-face="${esc(id)}"${msgAttr} style="${style}"><video src="${esc(src)}" muted playsinline preload="metadata"${attrs} aria-hidden="true"></video></span>`;
  }
  function wireAgentFaces(root) {
    qsa('.agent-face', root || document).forEach((face) => {
      if (face.dataset.faceWired === '1') return;
      face.dataset.faceWired = '1';
      const video = face.querySelector('video');
      if (!video) return;
      const freeze = () => {
        if (face.classList.contains('speaking') || face.classList.contains('playing')) return;
        try {
          video.pause();
          if (video.currentTime > 0.02) video.currentTime = 0;
        } catch (e) { /* ignore */ }
      };
      video.addEventListener('loadeddata', freeze);
      video.addEventListener('ended', () => {
        if (face.classList.contains('speaking')) return;
        if (AGENT_SPEAK.face === face) return;
        agentFacePause(face);
      });
      face.addEventListener('mouseenter', () => {
        if (face.classList.contains('speaking')) return;
        if (face.classList.contains('orch-msg-face')) {
          agentSpeakFromFace(face);
          return;
        }
        if (agentFaceReduceMotion()) return;
        agentFacePlay(face, { loop: false });
      });
      face.addEventListener('mouseleave', () => {
        if (face.classList.contains('speaking')) return;
        if (face.classList.contains('orch-msg-face')) {
          if (AGENT_SPEAK.face === face || AGENT_SPEAK.timer) agentSpeakStop();
          else agentFacePause(face);
          return;
        }
        agentFacePause(face);
      });
      if (face.classList.contains('speaking')) agentFacePlay(face, { loop: true });
      else if (video.readyState >= 2) freeze();
    });
  }

  const NAV = [
    { id: 'overview', label: 'Обзор', href: 'index.html', icon: 'overview' },
    { id: 'backtest', label: 'Бэктест', href: 'backtesting.html', icon: 'backtest' },
    { id: 'practice', label: 'Учебный терминал', href: 'practice-trading.html', icon: 'trading' },
    { id: 'trading', label: 'Торговля', href: 'trading.html', icon: 'trading' },
    { id: 'desktop', label: 'Рабочий стол', href: 'desktop.html', icon: 'desktop' },
    { id: 'performance', label: 'Финансы', href: 'performance.html', icon: 'performance' },
    { id: 'strategies', label: 'Стратегии', href: 'strategies.html', icon: 'strategies' },
    { id: 'ai', label: 'AI Lab', href: 'ai-lab.html', icon: 'ai' },
    { id: 'agents', label: 'AI Agents', href: 'ai-agents.html', icon: 'plug' },
    { id: 'news', label: 'Новости', href: 'news.html', icon: 'news' },
    { id: 'community', label: 'Сообщество', href: 'community.html', icon: 'docs' },
    { id: 'topstep', label: 'TopStep', href: 'topstep.html', icon: 'trophy' },
    { id: 'docs', label: 'Документы', href: 'documents.html', icon: 'docs' },
  ];
  let runtimeAccounts = [];
  let selectedAccount = null;

  // ---- formatting helpers -----------------------------------------------------
  function money(v, opts) {
    opts = opts || {};
    const sign = v > 0 && opts.sign ? '+' : (v < 0 ? '−' : '');
    const a = Math.abs(v);
    return sign + '$' + a.toLocaleString('en-US', { maximumFractionDigits: opts.dec ?? 0, minimumFractionDigits: opts.dec ?? 0 });
  }
  function pct(v) { return (v).toFixed(1) + '%'; }
  function pnlClass(v) { return v > 0 ? 'pos' : v < 0 ? 'neg' : 'muted'; }
  function badge(status) {
    const labels = { done: 'готово', pending: 'в работе', live: 'онлайн', demo: 'демо', trial: 'испытание', running: 'идёт', archived: 'архив', failed: 'ошибка' };
    const lbl = labels[status] || status;
    return `<span class="badge ${status}"><span class="dot"></span>${esc(lbl)}</span>`;
  }
  // A request with no deadline can leave a spinner up forever, which tells the
  // reader nothing and is indistinguishable from a slow network. Every panel
  // that puts up a spinner owes an answer -- including the answer "it did not
  // reply". The failure is a normal error, so each panel's existing retry path
  // handles it without a second mechanism.
  const PANEL_DEADLINE_MS = 12000;
  function withDeadline(promise, what, ms) {
    const limit = ms || PANEL_DEADLINE_MS;
    let timer;
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(
        (what || 'Источник') + ' не ответил за ' + Math.round(limit / 1000) + ' с.')), limit);
    });
    return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
  }

  function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
  function el(html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; }
  function qs(s, r) { return (r || document).querySelector(s); }
  function qsa(s, r) { return Array.from((r || document).querySelectorAll(s)); }

  function openExternal(url) {
    const u = String(url || '').trim();
    if (!u) return;
    window.open(u, '_blank', 'noopener');
  }
  function bindExternalLinks(root) {
    qsa('[data-external]', root || document).forEach(a => {
      a.onclick = (ev) => { ev.preventDefault(); openExternal(a.getAttribute('href') || a.dataset.external); };
    });
  }

  function newsEta(ms) {
    const min = Math.max(0, Math.round(ms / 60000));
    if (min < 60) return `через ${min} мин`;
    const hours = Math.floor(min / 60);
    if (hours < 24) return `через ${hours} ч ${min % 60} мин`;
    return `через ${Math.floor(hours / 24)} дн ${hours % 24} ч`;
  }

  function newsAge(minutes) {
    if (minutes == null) return '';
    if (minutes < 1) return 'только что';
    if (minutes < 60) return `${Math.round(minutes)} мин назад`;
    return `${Math.floor(minutes / 60)} ч назад`;
  }

  function normalizeNewsKey(text) {
    return String(text || '').toLowerCase().replace(/\s+/g, ' ').trim();
  }

  function itemSeverity(item) {
    const raw = String((item && (item.severity || item.impact)) || 'low').toLowerCase();
    return ['high', 'medium', 'low'].includes(raw) ? raw : 'low';
  }

  function itemTimeMs(item) {
    const stamp = new Date((item && (item.event_time_utc || item.published_at_utc)) || 0).getTime();
    return Number.isFinite(stamp) ? stamp : 0;
  }

  function itemInstruments(item, maxCount) {
    const rows = (item && (item.affected_instruments || item.instruments)) || [];
    const unique = Array.from(new Set((Array.isArray(rows) ? rows : []).filter(Boolean).map(value => String(value))));
    if (!unique.length) return '';
    const limit = Math.max(1, maxCount || 3);
    const shown = unique.slice(0, limit).join('/');
    return unique.length > limit ? `${shown}+${unique.length - limit}` : shown;
  }

  function uniqueTickerRows(rows, limit) {
    const seen = new Set();
    const out = [];
    (rows || []).forEach(row => {
      if (!row || !row.text) return;
      const key = normalizeNewsKey(row.dedupeKey || row.title || row.text);
      if (seen.has(key)) return;
      seen.add(key);
      out.push(row);
    });
    return out.slice(0, limit || 18);
  }

  function expandTickerRows(rows, targetCount) {
    const base = (rows || []).filter(Boolean);
    if (!base.length) return [];
    const total = Math.max(base.length, targetCount || 12);
    const out = [];
    let cycle = 0;
    while (out.length < total) {
      const offset = base.length > 1 ? ((cycle * 2) + 1) % base.length : 0;
      const rotated = cycle === 0 ? base : base.slice(offset).concat(base.slice(0, offset));
      rotated.forEach(row => {
        if (out.length >= total) return;
        if (!out.length || normalizeNewsKey(out[out.length - 1].text) !== normalizeNewsKey(row.text)) out.push(row);
      });
      if (base.length === 1) break;
      cycle += 1;
      if (cycle > total) break;
    }
    return out;
  }

  function ptMinuteOfDay(date) {
    if (!window.AuroraDomain || !AuroraDomain.ptParts) return 0;
    const p = AuroraDomain.ptParts(date || new Date());
    return p.hour * 60 + p.minute;
  }

  function inPtWindow(minute, start, end) {
    return start <= end ? minute >= start && minute < end : minute >= start || minute < end;
  }

  function ptMinutesUntil(minute, target) {
    return target >= minute ? target - minute : 1440 - minute + target;
  }

  function samePtDay(a, b) {
    if (!window.AuroraDomain || !AuroraDomain.ptParts) return false;
    const pa = AuroraDomain.ptParts(a);
    const pb = AuroraDomain.ptParts(b);
    return pa.year === pb.year && pa.month === pb.month && pa.day === pb.day;
  }

  function marketNoticeRows(events, now) {
    const rows = [];
    const current = new Date(now || Date.now());
    if (window.AuroraDomain && AuroraDomain.marketStatus) {
      const market = AuroraDomain.marketStatus(current);
      const sev = market.state === 'warn' ? 'medium' : market.state === 'off' ? 'medium' : 'low';
      rows.push({ severity: sev, text: `📈 CME futures: ${market.label}`, dedupeKey: `market:cme:${market.phase}` });
      if (market.phase === 'maintenance') {
        rows.push({ severity: 'medium', text: '⛔ Идёт техпауза CME: новые входы лучше отложить до открытия', dedupeKey: 'market:maintenance' });
      } else if (market.phase === 'weekend') {
        rows.push({ severity: 'low', text: '🌙 Американская cash-сессия закрыта: фокус смещается на открытие Европы и Азии', dedupeKey: 'market:weekend' });
      }
    }
    if (window.AuroraDomain && AuroraDomain.ptParts) {
      const minute = ptMinuteOfDay(current);
      const sessions = [
        { id: 'asia', label: 'азиатская сессия', start: 17 * 60, end: 1 * 60, severity: 'low' },
        { id: 'europe', label: 'европейская сессия', start: 0, end: 8 * 60, severity: 'low' },
        { id: 'us', label: 'американская cash-сессия', start: 6 * 60 + 30, end: 13 * 60, severity: 'medium' },
      ];
      const active = sessions.filter(session => inPtWindow(minute, session.start, session.end));
      if (active.length) {
        rows.push({
          severity: active.some(session => session.id === 'us') ? 'medium' : 'low',
          text: `🕒 Сейчас активна ${active.map(session => session.label).join(' и ')}`,
          dedupeKey: `market:active:${active.map(session => session.id).join(',')}`,
        });
      } else {
        rows.push({ severity: 'low', text: '🕒 Сейчас вне основных cash-сессий США, Европы и Азии', dedupeKey: 'market:active:none' });
      }
      const next = sessions
        .filter(session => !active.some(item => item.id === session.id))
        .map(session => ({ session, minutes: ptMinutesUntil(minute, session.start) }))
        .sort((a, b) => a.minutes - b.minutes)[0];
      if (next) {
        rows.push({
          severity: next.session.severity,
          text: `⏭ Следующая сессия: ${next.session.label} откроется ${newsEta(next.minutes * 60000)}`,
          dedupeKey: `market:next:${next.session.id}`,
        });
      }
    }
    const list = Array.isArray(events) ? events : [];
    const upcoming24 = list
      .filter(item => {
        const at = itemTimeMs(item);
        const remaining = at - current.getTime();
        return remaining > 0 && remaining <= 24 * 3600000;
      })
      .sort((a, b) => itemTimeMs(a) - itemTimeMs(b));
    const todayCount = list.filter(item => samePtDay(current, new Date(item.event_time_utc || 0))).length;
    if (todayCount) {
      rows.push({
        severity: upcoming24.some(item => itemSeverity(item) === 'high') ? 'medium' : 'low',
        text: `📅 Сегодня в календаре ${todayCount} событий${upcoming24[0] ? ` · ближайшее ${newsEta(itemTimeMs(upcoming24[0]) - current.getTime())}` : ''}`,
        dedupeKey: `market:today:${todayCount}`,
      });
    } else if (upcoming24[0]) {
      rows.push({
        severity: 'low',
        text: `📅 Ближайшее событие календаря ${newsEta(itemTimeMs(upcoming24[0]) - current.getTime())}`,
        dedupeKey: `market:upcoming:${upcoming24[0].id || upcoming24[0].title || ''}`,
      });
    }
    return uniqueTickerRows(rows, 8);
  }

  function scheduleStrategyRows(events, now, limit) {
    const current = Number(now || Date.now());
    const list = Array.isArray(events) ? events : [];
    const rows = [];
    const immediate = list
      .filter(item => {
        const severity = itemSeverity(item);
        const remaining = itemTimeMs(item) - current;
        if (!item || !item.title || !['high', 'medium'].includes(severity)) return false;
        if (severity === 'high') return remaining >= -(Number(item.block_after_min || 0) * 60000 + 90 * 60000) && remaining <= 72 * 3600000;
        return remaining > 0 && remaining <= 36 * 3600000;
      })
      .sort((a, b) => itemTimeMs(a) - itemTimeMs(b));

    immediate.forEach(item => {
      const remaining = itemTimeMs(item) - current;
      const severity = itemSeverity(item);
      const target = itemInstruments(item, 3);
      const timing = remaining <= 0 ? 'только что вышло' : newsEta(remaining);
      const prefix = remaining <= 0 ? '🟢' : severity === 'high' ? '🎯' : '⚙';
      rows.push({
        severity: severity === 'high' ? 'high' : 'medium',
        text: `${prefix} ${timing}: ${item.title}${target ? ` · ${target}` : ''}${item.is_confirmed ? '' : ' · время требует проверки'}`,
        url: item.url || item.source_url || '',
        dedupeKey: `event:${item.id || item.title}`,
      });
    });

    if (rows.length < 4) {
      const laterHigh = list
        .filter(item => {
          const remaining = itemTimeMs(item) - current;
          return item && item.title && itemSeverity(item) === 'high' && remaining > 72 * 3600000 && remaining <= 7 * 24 * 3600000;
        })
        .sort((a, b) => itemTimeMs(a) - itemTimeMs(b))
        .slice(0, 4 - rows.length);
      laterHigh.forEach(item => rows.push({
        severity: 'medium',
        text: `📅 ${newsEta(itemTimeMs(item) - current)}: ${item.title}${itemInstruments(item, 3) ? ` · ${itemInstruments(item, 3)}` : ''}`,
        url: item.url || item.source_url || '',
        dedupeKey: `event:${item.id || item.title}`,
      }));
    }

    return uniqueTickerRows(rows, limit || 10);
  }

  function clipText(text, limit) {
    const clean = String(text || '').trim();
    if (clean.length <= limit) return clean;
    return clean.slice(0, Math.max(0, limit - 1)).replace(/[\s.,;:—-]+$/, '') + '…';
  }

  // Compact one-line ticker text for a news-agent item: title + short advice,
  // no long recommendation "water". Low severity shows the headline only.
  function agentTickerText(item) {
    const title = clipText(item && item.title, 74);
    const advice = String((item && (item.ticker_line || item.short_recommendation)) || '').trim();
    return (advice && item && item.severity !== 'low') ? `🧠 ${title} · ${advice}` : `🧠 ${title}`;
  }

  function renderGlobalNewsStrip(strip, calendar, live, agentNews) {
    const label = qs('.global-news-label', strip);
    const track = qs('.global-news-track', strip);
    const now = Date.now();
    const events = (calendar && calendar.items) || [];
    const liveItems = ((live && live.items) || [])
      .filter(item => item && item.title && itemSeverity(item) !== 'low')
      .filter(item => item.age_min == null || (item.age_min >= -5 && item.age_min <= 720))
      .sort((a, b) => itemTimeMs(b) - itemTimeMs(a));
    const severity = item => itemSeverity(item);
    const eventMs = item => itemTimeMs(item);
    const activeCritical = events.filter(item => {
      const at = eventMs(item);
      return item.is_confirmed && severity(item) === 'high' &&
        now >= at - Number(item.block_before_min || 0) * 60000 &&
        now <= at + Number(item.block_after_min || 0) * 60000;
    });
    const imminentCritical = events.filter(item => {
      const remaining = eventMs(item) - now;
      return item.is_confirmed && severity(item) === 'high' && remaining > 0 && remaining <= 60 * 60000;
    });
    const upcoming = events.filter(item => {
      const remaining = eventMs(item) - now;
      return severity(item) === 'high' && remaining > 0 && remaining <= 7 * 24 * 3600000;
    }).sort((a, b) => eventMs(a) - eventMs(b));

    const critical = activeCritical.length > 0 || imminentCritical.length > 0;
    const warning = !critical && (upcoming.some(item => eventMs(item) - now <= 24 * 3600000) || liveItems.some(item => severity(item) === 'high'));
    strip.classList.toggle('critical', critical);
    strip.classList.toggle('warning', warning);
    label.textContent = critical ? '🔴 СТОП' : warning ? '⚠ ВАЖНО' : 'РЫНОК';

    const rows = [];
    activeCritical.forEach(item => rows.push({
      severity: 'high',
      text: `⛔ ОТКЛЮЧИТЕ СТРАТЕГИИ: ${item.title} — защитное окно активно`,
      url: item.url || item.source_url || '',
    }));
    imminentCritical.forEach(item => rows.push({
      severity: 'high',
      text: `🔴 ОЧЕНЬ СРОЧНО — ${newsEta(eventMs(item) - now)}: ${item.title}. Отключите затронутые стратегии`,
      url: item.url || item.source_url || '',
      dedupeKey: `event:${item.id || item.title}`,
    }));
    liveItems.filter(item => severity(item) === 'high').slice(0, 4).forEach(item => rows.push({
      severity: 'high',
      text: `🔴 ВАЖНАЯ НОВОСТЬ · ${item.source || 'источник'}: ${item.title}${item.age_min == null ? '' : ' · ' + newsAge(item.age_min)}`,
      url: item.url || item.source_url || '',
      dedupeKey: `live:${item.source || ''}:${item.title || ''}`,
    }));
    upcoming.slice(0, 4).forEach(item => rows.push({
      severity: item.is_confirmed ? 'high' : 'medium',
      text: `${item.is_confirmed ? '📅' : '⚠ оценка'} ${newsEta(eventMs(item) - now)}: ${item.title}`,
      url: item.url || item.source_url || '',
      dedupeKey: `event:${item.id || item.title}`,
    }));
    liveItems.filter(item => severity(item) === 'medium').slice(0, 4).forEach(item => rows.push({
      severity: 'medium',
      text: `${item.source || 'источник'}: ${item.title}${item.age_min == null ? '' : ' · ' + newsAge(item.age_min)}`,
      url: item.url || item.source_url || '',
      dedupeKey: `live:${item.source || ''}:${item.title || ''}`,
    }));
    ((agentNews && agentNews.items) || []).slice(0, 6).forEach(item => rows.push({
      severity: item.severity || 'medium',
      text: agentTickerText(item),
      url: item.source_url || '',
      dedupeKey: `agent:${item.news_id || item.title}`,
    }));

    let unique = uniqueTickerRows(rows.concat(scheduleStrategyRows(events, now, 12)), 24);
    if (unique.length < 10) unique = uniqueTickerRows(unique.concat(marketNoticeRows(events, now)), 24);
    if (!unique.length) {
      track.classList.add('paused');
      track.innerHTML = '<span class="global-news-static">Нет свежих важных сообщений; календарь доступен на вкладке «Новости».</span>';
      return;
    }
    track.classList.remove('paused');
    const expanded = expandTickerRows(unique, unique.length < 10 ? 20 : 14);
    const rollover = expanded.length > 1 ? expanded.slice(1).concat(expanded.slice(0, 1)) : expanded;
    const renderRow = row => {
      const content = `<span class="dot"></span><b>${esc(row.text)}</b>`;
      return row.url
        ? `<a class="global-news-item ${row.severity}" href="${esc(row.url)}" target="_blank" rel="noopener noreferrer">${content}</a>`
        : `<span class="global-news-item ${row.severity}">${content}</span>`;
    };
    track.innerHTML = expanded.map(renderRow).join('') + rollover.map(renderRow).join('');
  }

  function wireGlobalNewsStrip(strip) {
    if (!strip || !window.API || !API.http) return;
    const refresh = async () => {
      try {
        const [calendar, live, agentNews] = await Promise.all([
          API.http.news({ limit: 120 }, { signal: signal() }),
          API.http.newsLive({ max_age_min: 720, limit: 40 }, { signal: signal() }).catch(() => null),
          API.http.newsAnalysis({ limit: 20 }, { signal: signal() }).catch(() => null),
        ]);
        renderGlobalNewsStrip(strip, calendar, live, agentNews);
      } catch (error) {
        if (error && error.name === 'AbortError') return;
        const track = qs('.global-news-track', strip);
        if (track) track.innerHTML = '<span class="global-news-static">Новостная лента временно недоступна.</span>';
      }
    };
    refresh();
    const timer = setInterval(refresh, 180000);
    onLeave(() => clearInterval(timer));
  }

  // ---- shell ------------------------------------------------------------------
  function buildShell() {
    const page = document.body.dataset.page;
    const title = document.body.dataset.title || APP_NAME;
    const kicker = document.body.dataset.kicker || APP_KICKER;

    const rail = el(`<nav class="rail">
      <a class="rail-brand" href="index.html" title="${APP_NAME}">
        <span class="rail-logo"><img class="rail-logo-mark" src="${BRAND_MARK}" alt="${APP_NAME}" data-release-icon></span>
        <span class="rail-brand-tx"><span class="rail-brand-name-row"><span class="rail-brand-name">${APP_NAME}</span><span class="rail-release-badge pending" id="app-release-badge" data-release-badge>…</span></span><span class="rail-brand-version" id="app-build-meta" data-build-meta>версия определяется…</span><span class="rail-brand-sub">Strategy command center</span></span>
      </a>
      <div class="rail-nav">
        ${NAV.map(n => `<a class="rail-item ${n.id === page ? 'active' : ''}" href="${n.href}" title="${n.label}" data-nav="${n.id}">${icon(n.icon)}<span class="lb">${n.label}</span></a>`).join('')}
      </div>
      <div class="rail-foot"><span class="rail-dot" title="Сервер онлайн"></span><span class="rail-foot-tx">Сервер онлайн</span></div>
    </nav>`);

    const topbar = el(`<header class="topbar">
      <div class="tb-title"><span class="tb-kicker-row"><span class="tb-kicker">${kicker}</span><span class="rail-release-badge pending tb-release-badge" data-release-badge>…</span><span class="tb-build-meta" data-build-meta>версия определяется…</span></span><span class="tb-h1">${title}</span></div>
      <div class="tb-search-wrap">
        <label class="tb-search">${icon('search')}<input type="search" id="global-search" autocomplete="off" placeholder="Поиск стратегий, отчётов, инструментов…"></label>
        <div class="search-results" id="search-results" hidden></div>
      </div>
      <div class="tb-right">
        <button class="chip ok user-chip" id="chip-user" type="button" hidden title="Мой кабинет"><span class="avatar avatar-sm" id="chip-avatar">·</span><span id="chip-user-name">Пользователь</span></button>
        <button class="chip ok" id="chip-workspace" type="button" hidden><span class="dot"></span><span id="chip-workspace-name">Workspace</span></button>
        <span class="tb-page-actions" id="page-actions"></span>
        <span class="chip off" id="chip-nt" title="NinjaTrader"><span class="dot"></span>NinjaTrader</span>
        <span class="chip off" id="chip-bridge" title="Bridge (мост данных)"><span class="dot"></span>Bridge</span>
        <span class="chip off" id="chip-lm" title="LM Studio"><span class="dot"></span>LM&#160;Studio</span>
        <span class="chip off chip-market" id="chip-market" title="Рынок"><span class="dot"></span>Рынок</span>
        <button class="chip off chip-account" id="chip-account" type="button" title="Текущий торговый счёт"><span class="dot"></span>Счёт —</button>
        <span class="tb-datetime"><span id="pt-date">—</span><span class="mono" id="clock">—</span></span>
        <span class="tb-sep"></span>
        <button class="btn icon ghost tb-bell" id="tb-bell" type="button" title="Уведомления" aria-label="Уведомления" hidden>${icon('bell')}<span class="tb-bell-badge" id="tb-bell-badge" hidden>0</span></button>
        <button class="btn icon ghost" id="tb-more" title="Системные действия">${icon('dots')}</button>
      </div>
    </header>`);

    const app = el('<div class="app"></div>');
    const main = el('<div class="main"></div>');
    main.appendChild(topbar);
    const newsStrip = el('<div class="global-news-strip" data-global-news-strip><span class="global-news-label">РЫНОК</span><div class="global-news-window"><div class="global-news-track"><span class="global-news-static">Загрузка новостей…</span></div></div></div>');
    if (newsStrip) main.classList.add('has-global-news-strip');
    if (newsStrip) main.appendChild(newsStrip);
    // move existing body content into <main class=content>, but leave the
    // ambient background layers (canvas + vignette) as direct <body> children
    // so they stay the deepest layer, behind the whole app shell.
    const content = el('<div class="content"></div>');
    Array.from(document.body.childNodes).forEach(node => {
      if (node.nodeType === 1 && node.classList && (node.classList.contains('ambient-bg') || node.classList.contains('ambient-vignette'))) return;
      content.appendChild(node);
    });
    main.appendChild(content);
    app.appendChild(rail);
    app.appendChild(main);
    document.body.appendChild(app);

    refreshBuildIdentity();

    wireDelegatedActions();
    wireA11y();
    wireRailResize(rail, app);
    renderDevPreviewBanner();
    requestAnimationFrame(() => { authenticateAndStart(newsStrip); });
  }

  // ---- Rail (sidebar) drag-resize ------------------------------------------
  // The handle is a 6px transparent strip on the right border of the rail.
  // Width is clamped to 140..340px and persisted to localStorage.
  const RAIL_W_KEY = lsKey('ui.rail-width');
  const RAIL_W_MIN = 140, RAIL_W_MAX = 340, RAIL_W_DEFAULT = 240;
  function applyRailWidth(w, app) {
    const clamped = Math.round(Math.max(RAIL_W_MIN, Math.min(RAIL_W_MAX, w)));
    document.documentElement.style.setProperty('--rail-w', clamped + 'px');
    if (app) app.style.gridTemplateColumns = clamped + 'px minmax(0,1fr)';
    return clamped;
  }
  function wireRailResize(rail, app) {
    if (!rail || !app) return;
    // Restore saved width
    try {
      const saved = parseInt(localStorage.getItem(RAIL_W_KEY) || '', 10);
      if (saved >= RAIL_W_MIN) applyRailWidth(saved, app);
    } catch (e) { /* ignore */ }
    // Create the drag handle
    const handle = document.createElement('div');
    handle.className = 'rail-resize-handle';
    handle.title = 'Потяните, чтобы изменить ширину панели';
    rail.appendChild(handle);
    // Pointer events
    handle.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      handle.classList.add('dragging');
      handle.setPointerCapture(e.pointerId);
      const startX = e.clientX;
      const startW = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--rail-w') || RAIL_W_DEFAULT, 10) || RAIL_W_DEFAULT;
      const move = (ev) => {
        const w = applyRailWidth(startW + (ev.clientX - startX), app);
        try { localStorage.setItem(RAIL_W_KEY, w); } catch (ex) { /* ignore */ }
      };
      const up = () => {
        handle.classList.remove('dragging');
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
        // Trigger any canvas resize listeners (desktop charts etc.)
        window.dispatchEvent(new Event('resize'));
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    });
  }

  // ---- accessibility: make non-semantic clickables keyboard-operable ---------
  const A11Y_SEL = 'tr.clickable, .clickable, .kan-card, .mcell[data-id], .mcell[data-cell], .cal-day[data-i], .cal-day[data-date], .legend-item, .inst-row[data-sym], .igroup-h, .ai-cell[data-id], .row[data-id], .row[data-profile], .row[data-root], #top-strats .row, #recent .row, #doc-list .row';
  function enhanceA11y(scope) {
    qsa(A11Y_SEL, scope || document).forEach(eln => {
      const tag = eln.tagName;
      if (tag === 'A' || tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT') return;
      if (!eln.hasAttribute('tabindex')) eln.setAttribute('tabindex', '0');
      if (!eln.hasAttribute('role')) eln.setAttribute('role', 'button');
    });
  }
  function wireA11y() {
    document.addEventListener('keydown', (e) => {
      const t = e.target;
      if ((e.key === 'Enter' || e.key === ' ') && t && t.getAttribute && t.getAttribute('role') === 'button' && t.hasAttribute('tabindex')) {
        e.preventDefault(); t.click();
      }
    });
    // enhance dynamically-rendered content (tables/cards re-render often)
    let raf = null;
    const obs = new MutationObserver(() => { if (raf) cancelAnimationFrame(raf); raf = requestAnimationFrame(() => enhanceA11y(document)); });
    const content = qs('.content'); if (content) obs.observe(content, { childList: true, subtree: true });
  }

  async function authenticateAndStart(newsStrip, refresh = false) {
    const result = window.API
      ? await (refresh && API.refreshAuth ? API.refreshAuth() : API.authReady)
      : { auth: null };
    if (result.error) {
      if (!result.error.status || ![401, 403].includes(Number(result.error.status))) {
        document.documentElement.classList.remove('auth-locked');
        let banner = qs('#auth-reconnect');
        if (!banner) {
          banner = el('<div id="auth-reconnect" class="connection-banner">Связь с сервером временно недоступна. Восстанавливаю… <button class="btn sm" type="button">Повторить</button></div>');
          document.body.appendChild(banner);
          const retry = qs('button', banner);
          if (retry) retry.onclick = () => { banner.remove(); authenticateAndStart(newsStrip, true); };
        }
        setTimeout(() => { if (document.body.contains(banner)) { banner.remove(); authenticateAndStart(newsStrip, true); } }, 5000);
        return;
      }
      // Unauthenticated users see Sign in / Register first. Promo/donation is
      // optional and must not replace the primary account authentication flow.
      const adminRevoked = result.error.code === 'session_admin_revoked'
        || /Сессия завершена администратором/i.test(String(result.error.message || ''));
      if (adminRevoked) {
        renderTelegramLogin('Сессия завершена администратором. Войдите снова.');
        return;
      }
      renderTelegramLogin('');
      return;
    }
    CURRENT_AUTH = result.auth || { role: 'owner', is_owner: true, user: {} };
    document.documentElement.classList.remove('auth-locked');
    const user = CURRENT_AUTH.user || {};
    applyChipUser(user);
    captureReferral();
    handlePaypalReturn();
    applyNavAccess(CURRENT_AUTH);
    const chipUser = qs('#chip-user');
    if (chipUser) chipUser.onclick = () => openCabinet();
    const activeWorkspace = CURRENT_AUTH.active_workspace || {};
    const chipWorkspace = qs('#chip-workspace');
    if (chipWorkspace && activeWorkspace.workspace_id) {
      chipWorkspace.hidden = false;
      const workspaceName = qs('#chip-workspace-name');
      if (workspaceName) workspaceName.textContent = activeWorkspace.display_name || 'Workspace';
      chipWorkspace.onclick = () => openCabinet('workspaces');
      chipWorkspace.title = activeWorkspace.uses_owner_runtime ? 'Учебный контур владельца' : 'Личный контур пользователя';
    }
    maybeRefreshAvatar(user);
    if (user.needs_ux_mode || CURRENT_AUTH.ux_pending) {
      // The initial choice must precede the Aurora shell.  A direct deep link
      // may still reach this code, so send it back to the dedicated entry page.
      location.replace('mode-entry.html');
      return;
    }
    if (maybeRedirectBeginnerHome(user)) return;
    const studentShell = isStudentContour(CURRENT_AUTH);
    if (studentShell) applyStudentShell(newsStrip);
    startClock();
    if (!studentShell) {
      wireSystemStatus();
      wireTopbar();
      wireSearch();
      wireGlobalNewsStrip(newsStrip);
      buildOrchestratorWidget();
      startInAppNotices();
      startDesktopCommandBridge();
    }
    // Student can still use the account cabinet, the virtual terminal and
    // Community.  This support bridge is self-service and never exposes a
    // professional runtime command.
    startUserSupportBridge();
    renderImpersonationBanner(CURRENT_AUTH);
    // Google is NOT required for login / general use — only for NinjaTrader control.
    runReady();
    maybeRedeemStoredPromo();
    maybeHandleGoogleReturn();
  }

  function renderSessionEndedNotice() {
    const existing = qs('#session-ended-notice');
    if (existing) existing.remove();
    const card = el(`<div id="session-ended-notice" class="auth-screen"><section class="auth-card">
      <div class="auth-brand"><img src="${BRAND_MARK}" alt=""><div><strong>${APP_NAME}</strong><span>Сессия завершена</span></div></div>
      <p class="auth-lead">Сессия завершена администратором. Войдите снова через Telegram.</p>
      <button class="btn primary" type="button" id="session-ended-login">Войти</button>
    </section></div>`);
    document.body.appendChild(card);
    const btn = qs('#session-ended-login', card);
    if (btn) btn.onclick = () => { card.remove(); renderTelegramLogin(''); };
  }

  function renderUxModeGate() {
    const existing = qs('#ux-mode-gate');
    if (existing) existing.remove();
    document.documentElement.classList.add('ux-mode-locked');
    const card = el(`<div id="ux-mode-gate" class="auth-screen ux-mode-gate" role="dialog" aria-modal="true" aria-label="Выбор режима">
      <section class="auth-card ux-mode-card">
        <div class="auth-brand"><img src="${BRAND_MARK}" alt=""><div><strong>${APP_NAME}</strong><span>Выберите режим работы</span></div></div>
        <p class="auth-lead">Без выбора режим нельзя пропустить. Позже можно сменить в кабинете.</p>
        <div class="ux-mode-choices">
          <button type="button" class="ux-mode-choice" data-ux="beginner">
            <strong>Студент</strong>
            <span>Виртуальный prop-счёт: баланс → график → сделки → риск-лимиты. Без стратегий и ИИ.</span>
          </button>
          <button type="button" class="ux-mode-choice" data-ux="professional">
            <strong>Профессионал</strong>
            <span>Стратегии, AI Lab, NinjaTrader и расширенные разделы по тарифу. Community остаётся общим.</span>
          </button>
        </div>
        <div class="cab-sub" id="ux-mode-msg"></div>
      </section>
    </div>`);
    document.body.appendChild(card);
    qsa('[data-ux]', card).forEach(btn => {
      btn.onclick = async () => {
        const mode = btn.dataset.ux;
        const msg = qs('#ux-mode-msg', card);
        qsa('[data-ux]', card).forEach(b => { b.disabled = true; });
        if (msg) msg.textContent = 'Сохраняю…';
        try {
          const out = await API.http.authUxMode({ ux_mode: mode });
          CURRENT_AUTH = Object.assign({}, CURRENT_AUTH, out, {
            user: out.user || CURRENT_AUTH.user,
            features: out.features,
            capabilities: out.capabilities,
            locked_nav: out.locked_nav,
            ux_mode: out.ux_mode || mode,
            ux_pending: false,
          });
          if (CURRENT_AUTH.user) {
            CURRENT_AUTH.user.ux_mode = out.ux_mode || mode;
            CURRENT_AUTH.user.needs_ux_mode = false;
          }
          location.replace(mode === 'beginner' ? 'practice-trading.html' : 'index.html');
        } catch (e) {
          if (msg) msg.textContent = e.message || String(e);
          qsa('[data-ux]', card).forEach(b => { b.disabled = false; });
        }
      };
    });
  }

  function renderImpersonationBanner(auth) {
    const old = qs('#impersonation-banner');
    if (old) old.remove();
    if (!auth || !auth.impersonating) return;
    const user = auth.user || {};
    const label = `${user.first_name || ''} ${user.last_name || ''}`.trim() || user.username || user.id || user.user_id || 'пользователь';
    const bar = el(`<div id="impersonation-banner" class="impersonation-banner" role="status">
      <strong>Тестовый режим.</strong> Вы вошли как пользователь: ${esc(label)} (id ${esc(user.id || user.user_id || '')}).
      <button type="button" class="btn sm" id="impersonation-return">Вернуться в админку</button>
    </div>`);
    document.body.appendChild(bar);
    const btn = qs('#impersonation-return', bar);
    if (btn) btn.onclick = async () => {
      btn.disabled = true;
      try {
        if (auth.impersonation_preset === 'dev_preview') {
          await API.http.devPreviewExit();
          setDevPreviewLabel('');
        } else {
          await API.http.ownerImpersonateEnd();
        }
        toast('Возврат в админку');
        setTimeout(() => location.reload(), 400);
      } catch (e) { reportError(e); btn.disabled = false; }
    };
  }

  // ---- Developer Preview / View As (Development only) ------------------------
  // The active persona label is kept in sessionStorage so the persistent
  // "VIEW AS" banner survives the reload that swaps the preview session cookie,
  // and even renders on the logged-out (unauthenticated persona) screen. It is
  // never a permission source: real server-side permissions come from the
  // preview session the server minted. The Development-only, loopback-only
  // return route restores the developer session for any persona.
  const DEV_VIEW_AS_KEY = 'sf.dev.viewAs';

  function devPreviewLabel() {
    try { return sessionStorage.getItem(DEV_VIEW_AS_KEY) || ''; } catch (e) { return ''; }
  }
  function setDevPreviewLabel(label) {
    try {
      if (label) sessionStorage.setItem(DEV_VIEW_AS_KEY, label);
      else sessionStorage.removeItem(DEV_VIEW_AS_KEY);
    } catch (e) { /* ignore */ }
  }

  function devEnvironment() {
    const runtime = (CURRENT_AUTH && CURRENT_AUTH.runtime) || {};
    const deployment = runtime.deployment || runtime;
    return String(
      (BUILD_IDENTITY && BUILD_IDENTITY.environment)
      || deployment.deployment_environment || deployment.environment || ''
    ).toLowerCase();
  }

  function isDevelopmentEnv() {
    const runtime = (CURRENT_AUTH && CURRENT_AUTH.runtime) || {};
    return devEnvironment() === 'development' || !!runtime.test_auth_enabled;
  }

  function devPreviewAvailable() {
    return isDevelopmentEnv() && !!(CURRENT_AUTH && CURRENT_AUTH.is_owner);
  }

  function renderDevPreviewBanner() {
    const old = qs('#dev-view-as-banner');
    if (old) old.remove();
    const label = devPreviewLabel();
    // Only Development ever shows the banner; it is absent/forbidden elsewhere.
    if (!label || (CURRENT_AUTH && !isDevelopmentEnv())) return;
    const bar = el(`<div id="dev-view-as-banner" class="dev-view-as-banner" role="status" aria-live="polite">
      <span class="dev-view-as-tag">VIEW AS</span>
      <span class="dev-view-as-role">${esc(label)}</span>
      <span class="dev-view-as-note">Просмотр глазами роли. Реальные права не изменены.</span>
      <a class="btn sm" id="dev-view-as-return" href="/api/dev/preview/return">Вернуться к разработчику</a>
    </div>`);
    document.body.appendChild(bar);
    document.documentElement.classList.add('dev-view-as-active');
    const back = qs('#dev-view-as-return', bar);
    if (back) back.onclick = () => { setDevPreviewLabel(''); };
  }

  // Update-banner preview (item 6): renders the top update banner using the
  // canonical notification text, cycling through a sequence when asked. This is
  // a preview only — it never triggers a real send or reload.
  let _updateBannerTimer = null;
  function showUpdateBannerPreview(items, note, sequence) {
    const list = (items || []).filter(Boolean);
    if (!list.length) return;
    if (_updateBannerTimer) { clearTimeout(_updateBannerTimer); _updateBannerTimer = null; }
    const old = qs('#update-preview-banner');
    if (old) old.remove();
    const bar = el(`<div id="update-preview-banner" class="update-preview-banner" role="status" aria-live="polite">
      <span class="upb-tag">ПРЕДПРОСМОТР</span>
      <span class="upb-main"><strong class="upb-title"></strong><span class="upb-msg"></span></span>
      <button class="btn sm ghost" id="upb-close" type="button">Закрыть</button>
    </div>`);
    document.body.appendChild(bar);
    const titleEl = qs('.upb-title', bar);
    const msgEl = qs('.upb-msg', bar);
    let idx = 0;
    const show = () => {
      const item = list[idx];
      if (titleEl) titleEl.textContent = item.title || 'Обновление';
      if (msgEl) msgEl.textContent = ' — ' + (item.message || '');
      bar.classList.toggle('upb-done', item.kind === 'deploy_successful' || item.kind === 'reload_available');
      if (sequence && idx < list.length - 1) {
        idx += 1;
        _updateBannerTimer = setTimeout(show, 2600);
      }
    };
    show();
    const close = qs('#upb-close', bar);
    if (close) close.onclick = () => { if (_updateBannerTimer) clearTimeout(_updateBannerTimer); bar.remove(); };
    if (!sequence) {
      _updateBannerTimer = setTimeout(() => { if (document.body.contains(bar)) bar.remove(); }, 8000);
    }
  }

  function wireDevPreviewButton() {
    const right = qs('.tb-right');
    if (!right) return;
    let button = qs('#dev-preview-button');
    if (!devPreviewAvailable()) { if (button) button.remove(); return; }
    if (!button) {
      button = el('<button class="btn sm ghost" id="dev-preview-button" type="button" title="Developer Preview / View As">Preview</button>');
      const more = qs('#tb-more', right);
      right.insertBefore(button, more || right.firstChild);
    }
    button.onclick = () => openDevPreviewPanel();
  }

  async function openDevPreviewPanel() {
    const d = drawer('<h3>Developer Preview</h3>', '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>');
    const body = qs('.drawer-b', d);
    let status;
    try { status = await API.http.devPreviewStatus(); }
    catch (e) { return renderError(body, e, () => { closeDrawer(); openDevPreviewPanel(); }); }
    const personas = Array.isArray(status.personas) ? status.personas : [];
    body.innerHTML = `
      <div class="finance-note"><strong>Только Development.</strong> Переключатель показывает приложение глазами роли, применяя реальные серверные права выбранной роли. Реальные роли и права не меняются. В Canary и Production функция отключена.</div>
      <div class="section-title">Смотреть как</div>
      <div class="dev-persona-grid">${personas.map(p => `<button class="btn ghost dev-persona" data-persona="${esc(p.id)}"><strong>${esc(p.label)}</strong><span class="cab-sub">${esc(p.description || '')}</span></button>`).join('')}</div>
      <div class="section-title">Открыть Development как разработчик</div>
      <div class="finance-note">Создаёт одноразовую ссылку для входа как владелец из отдельного браузера. Ссылка действует только с localhost и один раз.</div>
      <div class="flex gap-sm"><button class="btn" id="dev-bootstrap-mint">Получить ссылку</button></div>
      <div id="dev-bootstrap-url" class="dev-bootstrap-url" hidden></div>
      <div class="section-title">Обслуживание</div>
      <div class="flex gap-sm"><button class="btn ghost" id="dev-personas-reset">Сбросить тестовые персоны</button></div>`;
    qsa('.dev-persona', body).forEach(btn => {
      btn.onclick = async () => {
        const persona = btn.dataset.persona;
        const label = (btn.querySelector('strong') || {}).textContent || persona;
        qsa('.dev-persona', body).forEach(b => { b.disabled = true; });
        try {
          await API.http.devPreviewViewAs(persona);
          setDevPreviewLabel(label);
          toast('Предпросмотр роли активирован');
          setTimeout(() => location.reload(), 300);
        } catch (e) { reportError(e); qsa('.dev-persona', body).forEach(b => { b.disabled = false; }); }
      };
    });
    const mint = qs('#dev-bootstrap-mint', body);
    if (mint) mint.onclick = async () => {
      mint.disabled = true;
      try {
        const out = await API.http.devBootstrapMint();
        const target = qs('#dev-bootstrap-url', body);
        if (target) {
          target.hidden = false;
          target.innerHTML = `<code class="mono">${esc(out.url || out.token || '')}</code><div class="cab-sub">Одноразовая ссылка. Действует ${esc(String(out.expires_in_sec || ''))} сек. Откройте её в отдельном браузере на этом компьютере.</div>`;
        }
      } catch (e) { reportError(e); }
      finally { mint.disabled = false; }
    };
    const reset = qs('#dev-personas-reset', body);
    if (reset) reset.onclick = async () => {
      reset.disabled = true;
      try { await API.http.devPreviewResetPersonas(); toast('Тестовые персоны сброшены'); }
      catch (e) { reportError(e); }
      finally { reset.disabled = false; }
    };
  }

  function renderGoogleLinkGate(auth) {
    if (qs('#google-link-gate')) return;
    const staging = !!(auth.runtime && auth.runtime.test_auth_enabled);
    const configured = !!(auth.google_oauth && auth.google_oauth.configured);
    const card = el(`<div id="google-link-gate" class="auth-screen google-link-gate"><section class="auth-card">
      <div class="auth-brand"><img src="${BRAND_MARK}" alt=""><div><strong>${APP_NAME}</strong><span>Google для NinjaTrader</span></div></div>
      <p class="auth-lead">Остальные разделы доступны с Telegram. Google нужен только перед подключением и управлением NinjaTrader (личный или рабочий контур).</p>
      <div class="auth-actions">
        <button class="btn primary" type="button" id="google-link-start">${configured ? 'Подключить Google' : (staging ? 'Привязать тестовый Google (staging)' : 'Google OAuth не настроен')}</button>
        <button class="btn ghost" type="button" id="google-link-later">Закрыть</button>
      </div>
      <div class="auth-security">После Google потребуется повторное подтверждение в Telegram</div>
    </section></div>`);
    document.body.appendChild(card);
    const start = qs('#google-link-start', card);
    const later = qs('#google-link-later', card);
    if (later) later.onclick = () => card.remove();
    if (start) start.onclick = async () => {
      start.disabled = true;
      try {
        if (configured) {
          const out = await API.http.googleAuthStart({ return_path: location.pathname || '/ui/' });
          if (out.auth_url) location.href = out.auth_url;
          else toast('Не удалось начать Google OAuth');
        } else if (staging) {
          await API.http.testAuthGoogleLink({});
          toast('Тестовый Google привязан');
          setTimeout(() => location.reload(), 500);
        } else {
          toast('Владелец должен задать NTA_GOOGLE_CLIENT_ID / SECRET');
          start.disabled = false;
        }
      } catch (e) { reportError(e); start.disabled = false; }
    };
  }

  async function ensureNtDualAuth(me) {
    const nt = (me && me.nt_access) || (CURRENT_AUTH && CURRENT_AUTH.nt_access) || {};
    if (me && me.is_owner) return true;
    if (nt.ready) return true;
    if (!nt.google_ok) {
      renderGoogleLinkGate(me || CURRENT_AUTH || {});
      toast(nt.message || 'Подключите Google для NinjaTrader');
      return false;
    }
    const staging = !!(me && me.runtime && me.runtime.test_auth_enabled) || !!(CURRENT_AUTH && CURRENT_AUTH.runtime && CURRENT_AUTH.runtime.test_auth_enabled);
    try {
      if (staging) {
        await API.http.testAuthNtElevate({});
        toast('Staging: Telegram-подтверждение NT выдано');
        if (CURRENT_AUTH) CURRENT_AUTH.nt_access = Object.assign({}, CURRENT_AUTH.nt_access || {}, { ready: true, telegram_ok: true, google_ok: true });
        return true;
      }
      const started = await API.http.ntConfirmStart({});
      toast('Подтвердите действие в Telegram');
      const challengeId = started.challenge_id;
      for (let i = 0; i < 45; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const st = await API.http.ntConfirmStatus({ challenge_id: challengeId });
        if (st.status === 'nt_confirmed' || (st.nt_access && st.nt_access.ready)) {
          if (CURRENT_AUTH) CURRENT_AUTH.nt_access = st.nt_access || Object.assign({}, CURRENT_AUTH.nt_access || {}, { ready: true, telegram_ok: true });
          toast('NinjaTrader подтверждён');
          return true;
        }
        if (st.status === 'nt_denied' || st.status === 'expired') {
          toast(st.message || 'Подтверждение отклонено или истекло');
          return false;
        }
      }
      toast('Не дождались подтверждения в Telegram');
      return false;
    } catch (e) {
      reportError(e);
      return false;
    }
  }

  async function ntStepUp(action) {
    // Phase 5: obtain a single-use step-up grant for a critical NinjaTrader
    // action (pairing, revoke, default account, capability change, unlink).
    // In Development test-auth the server echoes the code; otherwise the user
    // enters the code delivered via Telegram or e-mail (never SMS).
    try {
      const started = await API.http.accountNtStepUpStart({ action });
      let code = started.test_code || '';
      if (!code) {
        const via = started.provider === 'google' ? 'Google e-mail' : (started.provider === 'email' ? 'e-mail' : 'Telegram');
        code = (prompt('Введите код подтверждения, отправленный через ' + via + ' (это не SMS):') || '').trim();
        if (!code) { toast('Код не введён'); return null; }
      }
      await API.http.accountNtStepUpConfirm({ challenge_id: started.challenge_id, code });
      return started.challenge_id;
    } catch (e) {
      const posture = (e && e.payload && e.payload.onboarding) || null;
      const steps = posture && Array.isArray(posture.onboarding) ? posture.onboarding : [];
      if (steps.length) {
        toast(steps[0].message || 'Подтвердите Telegram и e-mail для личного NinjaTrader');
      } else {
        reportError(e);
      }
      return null;
    }
  }

  function maybeHandleGoogleReturn() {
    try {
      const params = new URLSearchParams(location.search || '');
      if (params.get('google_linked') === '1') {
        toast('Google успешно подключён');
        params.delete('google_linked');
        const next = location.pathname + (params.toString() ? '?' + params.toString() : '') + location.hash;
        history.replaceState({}, '', next);
      }
      const err = params.get('google_error');
      if (err) {
        toast('Google: ' + err);
        params.delete('google_error');
        const next = location.pathname + (params.toString() ? '?' + params.toString() : '') + location.hash;
        history.replaceState({}, '', next);
      }
    } catch (e) { /* ignore */ }
  }

  async function maybeRedeemStoredPromo() {
    let code = '';
    try { code = String(sessionStorage.getItem('stratforge.pending.promo') || '').trim(); } catch (e) { code = ''; }
    if (!code || !window.API) return;
    try {
      const out = await API.http.billingPromoRedeem({ code });
      try { sessionStorage.removeItem('stratforge.pending.promo'); } catch (e) { /* ignore */ }
      if (out && !out.checkout_required) { toast('Промокод активирован'); setTimeout(() => location.reload(), 700); }
    } catch (e) { /* keep code for retry from cabinet */ }
  }

  function isGuest() {
    return !!(CURRENT_AUTH && CURRENT_AUTH.guest);
  }

  function dismissWelcomeAccess() {
    try { sessionStorage.setItem('stratforge.welcome.dismissed', '1'); } catch (e) { /* ignore */ }
    const node = qs('#welcome-access');
    if (node) node.remove();
    document.documentElement.classList.remove('auth-locked');
  }

  function lockedNavClick(e) {
    if (e) { e.preventDefault(); e.stopPropagation(); }
    openCabinet('plans');
  }

  // ---- avatars + personal / owner cabinet -----------------------------------
  function hashCode(str) { let h = 0; for (let i = 0; i < String(str).length; i++) { h = (h << 5) - h + String(str).charCodeAt(i); h |= 0; } return h; }
  // A profile with no name still has a role. An owner account bootstrapped
  // without a Telegram profile (the LOCAL build authenticates as the owner
  // without a login) used to read as the anonymous "Пользователь".
  function userLabel(user) {
    user = user || {};
    const named = [user.first_name, user.last_name].filter(Boolean).join(' ') || user.username;
    if (named) return named;
    return user.is_owner ? 'Владелец' : 'Пользователь';
  }
  function avatarHtml(user, cls) {
    user = user || {};
    // avatar_url carries a ?v= stamp and is cached by the browser; the old
    // inline base64 copy re-sent ~27KB per user on every payload that named one.
    const url = user.avatar_url || '';
    const label = userLabel(user);
    const initials = (label.trim().split(/\s+/).map(w => w[0]).filter(Boolean).slice(0, 2).join('') || '·').toUpperCase();
    const hue = Math.abs(hashCode(String(user.id || user.user_id || label))) % 360;
    if (url) return `<span class="avatar ${cls || ''}"><img src="${esc(url)}" alt="" referrerpolicy="no-referrer"></span>`;
    return `<span class="avatar ${cls || ''}" style="--av-h:${hue}">${esc(initials)}</span>`;
  }
  function applyChipUser(user) {
    const chip = qs('#chip-user'); if (!chip) return;
    chip.hidden = false;
    chip.innerHTML = avatarHtml(user, 'avatar-sm') + `<span id="chip-user-name">${esc(userLabel(user))}</span>`;
  }
  function applyNavFeatures(features) {
    qsa('.rail-item[data-nav]').forEach(item => {
      const id = item.dataset.nav;
      if (id === 'overview') { item.hidden = false; return; }
      item.hidden = !(!features || features[id] !== false);
    });
  }
  const STUDENT_NAV_IDS = new Set(['practice', 'community']);

  function isStudentContour(auth) {
    const source = auth || {};
    const user = source.user || {};
    return String(source.ux_mode || user.ux_mode || '').toLowerCase() === 'beginner';
  }

  function applyStudentShell(newsStrip) {
    // The student product is a separate virtual prop terminal, not a
    // professional dashboard with some tabs hidden.  Suppress professional
    // controls before page scripts initialize so they cannot issue forbidden
    // background calls or leave misleading NT/AI controls on the screen.
    document.body.classList.add('student-shell');
    document.body.dataset.studentShell = '1';
    const sub = qs('.rail-brand-sub');
    if (sub) sub.textContent = 'Учебный prop-терминал';
    const search = qs('.tb-search-wrap');
    if (search) search.hidden = true;
    if (newsStrip) newsStrip.hidden = true;
    qsa('#page-actions, #chip-workspace, #chip-nt, #chip-bridge, #chip-lm, #chip-account, #tb-bell, #tb-more').forEach(node => {
      node.hidden = true;
      node.setAttribute('aria-hidden', 'true');
    });
  }
  // Central access control for authenticated accounts with locked sections.
  // Anonymous users never reach this shell; a locked page gets an explicit
  // access gate instead of the retired blurred preview.
  // Beginner UX: hide pro sections entirely (not lock-blur).
  function applyNavAccess(auth) {
    auth = auth || {};
    const isOwner = !!auth.is_owner;
    const user = auth.user || {};
    const uxMode = String(auth.ux_mode || user.ux_mode || (isOwner ? 'professional' : '')).toLowerCase();
    const features = auth.features || user.features || null;
    const caps = auth.capabilities || {};
    // The owner is never a demo tier. Stated explicitly rather than relying on
    // the server always sending a complete payload: a partial or stale auth
    // response would otherwise paint the owner's real data as a demo.
    const demoTier = !isOwner
      && !!(auth.demo_tier || (caps.demo_backtest && !caps.backtesting) || uxMode === 'beginner');
    document.body.dataset.demoTier = demoTier ? '1' : '0';
    document.body.dataset.uxMode = uxMode || '';
    document.documentElement.classList.toggle('demo-tier', demoTier);
    document.documentElement.classList.toggle('ux-beginner', uxMode === 'beginner');
    const hasLockList = Array.isArray(auth.locked_nav);
    const locked = new Set(isOwner ? [] : (auth.locked_nav || []));
    qsa('.rail-item[data-nav]').forEach(item => {
      const id = item.dataset.nav;
      item.removeEventListener('click', lockedNavClick);
      if (uxMode === 'beginner') {
        item.hidden = !STUDENT_NAV_IDS.has(id);
        item.classList.remove('rail-locked');
        const lk = item.querySelector('.rail-lock');
        if (lk) lk.remove();
        return;
      }
      // A professional must not see a student-only terminal in their rail.
      item.hidden = id === 'practice';
      if (id === 'overview') { item.classList.remove('rail-locked'); return; }
      let isLocked = hasLockList ? locked.has(id) : (!isOwner && features && features[id] === false);
      item.classList.toggle('rail-locked', !!isLocked);
      let lk = item.querySelector('.rail-lock');
      if (isLocked) {
        if (!lk) { lk = document.createElement('span'); lk.className = 'rail-lock'; lk.textContent = '🔒'; item.appendChild(lk); }
        item.addEventListener('click', lockedNavClick);
      } else if (lk) { lk.remove(); }
    });
    const page = document.body.dataset.page;
    if (uxMode === 'beginner') {
      ensureBeginnerWatermark();
      return;
    }
    if (uxMode === 'professional' && page === 'practice') {
      location.replace('index.html');
      return;
    }
    if (!isOwner && page && locked.has(page)) {
      renderLockGate(auth.unlock_message || 'Раздел доступен после активации подписки, промокода или доступа владельца.', auth.free_preview);
    } else if (demoTier && (page === 'backtest' || page === 'practice')) {
      ensureDemoWatermark();
    }
  }
  function maybeRedirectBeginnerHome(user) {
    user = user || {};
    if (String(user.ux_mode || '').toLowerCase() !== 'beginner') return false;
    const page = document.body.dataset.page;
    if (!page || STUDENT_NAV_IDS.has(page)) return false;
    location.replace('practice-trading.html');
    return true;
  }
  function ensureBeginnerWatermark() {
    if (qs('#beginner-watermark')) return;
    const bar = el(`<div id="beginner-watermark" class="demo-watermark beginner-watermark" role="status">Режим «Студент» · виртуальные деньги · учебный контур <button type="button" class="btn sm" id="beginner-upgrade-cta">Перейти в профессиональный</button></div>`);
    document.body.appendChild(bar);
    const btn = qs('#beginner-upgrade-cta', bar);
    if (btn) btn.onclick = () => openCabinet('profile');
  }
  function ensureDemoWatermark() {
    if (qs('#demo-watermark')) return;
    const bar = el(`<div id="demo-watermark" class="demo-watermark" role="status">Демоверсия. Данные нереальные. <button type="button" class="btn sm" id="demo-upgrade-cta">Что откроется после подписки</button></div>`);
    document.body.appendChild(bar);
    const btn = qs('#demo-upgrade-cta', bar);
    if (btn) btn.onclick = () => openCabinet('plans');
  }
  function renderLockGate(msg, freePreview) {
    if (qs('#lock-gate')) return;
    document.documentElement.classList.add('has-lock-gate');
    const host = qs('.content') || document.body;
    const gate = el(`<div id="lock-gate" class="lock-gate"><div class="lock-gate-card">
      <div class="lock-gate-icon">🔒</div>
      <h2>Раздел заблокирован</h2>
      <p>${esc(msg)}</p>
      <div class="lock-gate-actions">
        <button class="btn primary" id="lock-gate-plans">Промокод или донат</button>
      </div>
      ${freePreview ? '<div class="lock-gate-hint">Ознакомительный профессиональный режим: открыты Обзор, Новости и Документы.</div>' : ''}
    </div></div>`);
    host.appendChild(gate);
    const p = qs('#lock-gate-plans', gate);
    if (p) p.onclick = () => {
      if (CURRENT_AUTH && CURRENT_AUTH.guest) renderTelegramLogin('');
      else openCabinet('plans');
    };
  }

  async function renderWelcomeAccess(opts) {
    opts = opts || {};
    const existing = qs('#welcome-access');
    if (existing) existing.remove();
    const ref = (typeof getReferral === 'function' ? getReferral() : '') || '';
    let donate = { tiers: [], payment: {} };
    try { donate = await API.http.billingAccessOptions({ retries: 0 }); } catch (e) {
      try { donate = await API.http.billingDonate({ retries: 0 }); } catch (e2) { /* optional */ }
    }
    const paypal = (donate.payment || {}).paypal_me || '';
    const tiers = donate.tiers || [];
    const tierBtns = tiers.map(t => {
      const amount = Number(t.price_usd || 0);
      const label = amount ? ('$' + String(amount).replace(/\.0$/, '')) : esc(t.label || t.plan_id);
      const url = t.paypal_url || (paypal ? paypalFor(paypal, amount) : '');
      return `<button type="button" class="btn wa-tier ${url ? 'primary' : 'ghost'}" data-wa-tier="${esc(t.plan_id)}" data-wa-amount="${esc(String(amount))}" data-wa-url="${esc(url)}" ${url ? '' : 'disabled'}>${label}</button>`;
    }).join('');

    const host = el(`<div id="welcome-access" class="welcome-access-overlay" role="dialog" aria-modal="true" aria-label="Доступ">
      <div class="welcome-access-card">
        <div class="welcome-access-head">
          <div class="auth-brand"><img src="${BRAND_MARK}" alt=""><div><strong>${APP_NAME}</strong><span>Открыть больше возможностей</span></div></div>
          <button type="button" class="btn icon ghost welcome-access-x" id="wa-x" title="Закрыть" aria-label="Закрыть">✕</button>
        </div>
        <p class="welcome-access-lead">Войдите через Telegram, чтобы открыть свои чаты и рабочие данные. Промокод или донат используются только для выдачи доступа новым пользователям.</p>
        <div class="access-promo">
          <label class="cab-sub">Промокод</label>
          <div class="flex gap-sm"><input id="wa-promo" placeholder="Код приглашения" value="${esc(ref)}" style="flex:1"><button class="btn primary" id="wa-promo-go">Далее</button></div>
          <div class="cab-sub" id="wa-promo-msg"></div>
        </div>
        <div class="access-donate">
          <label class="cab-sub">Отблагодарить</label>
          <div class="wa-tiers">${tierBtns || '<span class="cab-sub">Суммы скоро появятся</span>'}</div>
          <div class="flex gap-sm wa-custom">
            <input id="wa-donate-custom" type="number" min="1" step="1" placeholder="Своя сумма, $">
            <button type="button" class="btn ghost" id="wa-donate-custom-go" ${paypal ? '' : 'disabled'}>PayPal</button>
          </div>
          <label class="access-request"><input type="checkbox" id="wa-donate-request" checked><span>Запросить доступ после доната</span></label>
          <div class="cab-sub" id="wa-donate-msg"></div>
        </div>
        <div class="welcome-access-actions">
          <button type="button" class="btn primary" id="wa-telegram">Войти через Telegram</button>
          <button type="button" class="btn ghost" id="wa-close">Вернуться ко входу</button>
        </div>
      </div>
    </div>`);
    document.body.appendChild(host);

    const root = host;
    const beginAuth = (intent) => {
      try {
        if (intent && intent.promo) sessionStorage.setItem('stratforge.pending.promo', intent.promo);
        if (intent && intent.donatePlan) sessionStorage.setItem('stratforge.pending.donate', JSON.stringify(intent));
      } catch (e) { /* ignore */ }
      host.remove();
      renderTelegramLogin('');
    };
    const openPay = (url) => { if (url) try { window.open(url, '_blank', 'noopener'); } catch (e) { location.href = url; } };
    const wantAccess = () => !!(qs('#wa-donate-request', root) && qs('#wa-donate-request', root).checked);
    const onClose = () => {
      dismissWelcomeAccess();
      if (!CURRENT_AUTH) renderTelegramLogin('');
    };

    const xBtn = qs('#wa-x', root); if (xBtn) xBtn.onclick = onClose;
    const closeBtn = qs('#wa-close', root); if (closeBtn) closeBtn.onclick = onClose;
    host.addEventListener('click', (e) => { if (e.target === host) onClose(); });

    const tgBtn = qs('#wa-telegram', root);
    if (tgBtn) tgBtn.onclick = () => beginAuth({});

    const promoGo = qs('#wa-promo-go', root);
    if (promoGo) promoGo.onclick = () => {
      const code = ((qs('#wa-promo', root) || {}).value || '').trim();
      if (!code) { toast('Введите промокод'); return; }
      const msg = qs('#wa-promo-msg', root);
      if (msg) msg.textContent = 'Дальше — Telegram и регистрация. Владелец подтвердит доступ.';
      beginAuth({ promo: code });
    };

    qsa('[data-wa-tier]', root).forEach(b => b.onclick = () => {
      const url = b.dataset.waUrl || '';
      const planId = b.dataset.waTier || '';
      const amount = b.dataset.waAmount || '';
      if (url) openPay(url);
      const msg = qs('#wa-donate-msg', root);
      if (wantAccess()) {
        if (msg) msg.textContent = 'Оплатите в PayPal, затем войдите через Telegram.';
        beginAuth({ donatePlan: planId, amount });
      } else if (msg) {
        msg.textContent = 'Чтобы получить доступ — включите галочку и войдите через Telegram.';
      }
    });

    const customGo = qs('#wa-donate-custom-go', root);
    if (customGo) customGo.onclick = () => {
      const raw = Number((qs('#wa-donate-custom', root) || {}).value || 0);
      if (!(raw >= 1)) { toast('Укажите сумму от $1'); return; }
      const amount = Math.round(raw * 100) / 100;
      const url = paypal ? paypalFor(paypal, amount) : '';
      const tier = donationPlanForAmount(tiers, amount);
      if (url) openPay(url);
      if (wantAccess() && tier) beginAuth({ donatePlan: tier.plan_id, amount });
      else toast(url ? 'Оплатите в PayPal, затем войдите через Telegram' : 'PayPal владельца ещё не настроен');
    };
  }
  async function maybeRefreshAvatar(user) {
    if (!window.API || API.config.offline) return;
    if (user && user.has_avatar) return;
    try {
      const out = await API.http.authAvatarRefresh();
      if (out && out.ok && out.user) { if (CURRENT_AUTH) CURRENT_AUTH.user = out.user; applyChipUser(out.user); }
    } catch (e) { /* best-effort avatar fetch */ }
  }
  function showCode(code, label) {
    if (!code) return;
    toast((label || 'Код') + ': ' + code);
    try { if (navigator.clipboard) navigator.clipboard.writeText(code); } catch (e) { /* clipboard may be blocked */ }
  }
  const REF_KEY = lsKey('app.ref');
  function captureReferral() {
    let code = '';
    try {
      const params = new URLSearchParams(location.search);
      code = params.get('ref') || '';
      code = code.replace(/[^A-Za-z0-9-]/g, '').slice(0, 40);
      if (code) localStorage.setItem(REF_KEY, code);
    } catch (e) { /* ignore */ }
    return code;
  }
  function getReferral() { try { return localStorage.getItem(REF_KEY) || ''; } catch (e) { return ''; } }
  function clearReferral() { try { localStorage.removeItem(REF_KEY); } catch (e) { /* ignore */ } }
  function handlePaypalReturn() {
    try {
      const params = new URLSearchParams(location.search);
      const status = params.get('paypal');
      if (!status) return;
      if (status === 'success') toast('Оплата PayPal принята. Тариф активируется после подтверждения PayPal.');
      else if (status === 'cancel') toast('Оплата отменена.');
      params.delete('paypal');
      const rest = params.toString();
      history.replaceState(null, '', location.pathname + (rest ? '?' + rest : ''));
    } catch (e) { /* ignore */ }
  }

  async function openCabinet(initialTab) {
    const d = drawer('<h3>Кабинет</h3>', '<div class="state-loading"><span class="spinner"></span>Загрузка кабинета…</div>');
    const body = qs('.drawer-b', d);
    const load = async () => {
      let me;
      try { me = await API.http.authMe(); }
      catch (e) { renderError(body, e, load); return; }
      CURRENT_AUTH = Object.assign({}, CURRENT_AUTH, {
        user: me.user,
        features: me.features,
        capabilities: me.capabilities,
        admin_capabilities: me.admin_capabilities,
        is_owner: me.is_owner,
        role: me.role,
        active_workspace: me.active_workspace,
      });
      applyChipUser(me.user || {});
      renderCabinet(body, me, initialTab || 'profile');
    };
    await load();
  }

  function cabinetHeader(me) {
    const user = me.user || {};
    const roleLabel = me.is_owner ? 'Владелец' : (me.role === 'read_only' ? 'Только чтение' : 'Полное управление');
    return `<div class="cab-head">${avatarHtml(user, 'avatar-lg')}<div class="cab-id"><div class="cab-name">${esc(userLabel(user))}</div><div class="cab-sub">${user.username ? '@' + esc(user.username) + ' · ' : ''}${esc(user.email || 'e-mail не указан')}</div><div class="cab-badges"><span class="badge ${me.is_owner ? 'live' : 'demo'}">${esc(roleLabel)}</span>${user.phone_mask ? `<span class="badge archived">${esc(user.phone_mask)}</span>` : ''}</div></div><div class="cab-head-actions">${me.telegram_configured ? '<button class="btn sm ghost" id="cab-avatar-refresh">Обновить фото</button>' : ''}</div></div>`;
  }
  function cabinetProfile(me) {
    const sub = me.subscription || {};
    const plan = sub.plan || {};
    const feats = me.features || {};
    const activeFeatures = (me.feature_catalog || []).filter(f => feats[f.id] !== false);
    const isOwner = !!me.is_owner;
    const user = me.user || {};
    const uxMode = String(me.ux_mode || user.ux_mode || (isOwner ? 'professional' : '')).toLowerCase();
    const planLabel = sub.plan_id ? (plan.label || sub.plan_id) : (isOwner ? 'Founder' : 'Нет активной подписки');
    const planBadge = isOwner
      ? '<span class="badge trial">★ Золотая звезда · Основатель</span>'
      : (sub.plan_id ? `<span class="badge ${(sub.status === 'active' || sub.status === 'promo_grant' || sub.status === 'founder') ? 'live' : 'archived'}">${esc(sub.status || '')}</span>` : '');
    const expires = sub.expires_at_utc ? ('до ' + esc(sub.expires_at_utc)) : ((sub.plan_id || isOwner) ? 'бессрочно' : '');
    const modeLabel = uxMode === 'beginner' ? 'Студент' : (uxMode === 'professional' ? 'Профессионал' : 'не выбран');
    const modeCard = isOwner
      ? `<div class="cab-card"><h4>Режим интерфейса</h4><div class="cab-kv"><span class="k">Режим</span><span class="v"><strong>Профессионал</strong> <span class="badge live">владелец</span></span></div><div class="cab-sub">Владелец всегда в режиме «Профессионал». Для проверки новичка используйте Staging → impersonation.</div></div>`
      : `<div class="cab-card"><h4>Режим интерфейса</h4>
          <div class="cab-kv"><span class="k">Сейчас</span><span class="v"><strong>${esc(modeLabel)}</strong></span></div>
          <p class="cab-sub">Студент — отдельный учебный терминал и Community. Профессионал — стратегии, ИИ, NinjaTrader и документы по тарифу; Community остаётся общим.</p>
          <div class="flex gap-sm wrap" id="cab-ux-actions">
            <button type="button" class="btn ${uxMode === 'beginner' ? 'ghost' : 'primary'} sm" data-set-ux="professional" ${uxMode === 'professional' ? 'disabled' : ''}>Стать профессионалом</button>
            <button type="button" class="btn ${uxMode === 'professional' ? 'ghost' : 'primary'} sm" data-set-ux="beginner" ${uxMode === 'beginner' ? 'disabled' : ''}>Режим новичка</button>
          </div>
          <div class="cab-sub" id="cab-ux-msg"></div>
        </div>`;
    const ntCard = uxMode === 'beginner'
      ? `<div class="cab-card"><h4>Мой NinjaTrader</h4><div class="cab-sub">Подключение NT доступно в режиме «Профессионал».</div></div>`
      : `<div class="cab-card"><h4>Мой NinjaTrader</h4><div id="cab-nt"><div class="state-loading"><span class="spinner"></span>Проверка…</div></div></div>`;
    return `
      ${modeCard}
      <div class="cab-card"><h4>Подписка</h4>
        <div class="cab-kv"><span class="k">Тариф</span><span class="v"><strong>${esc(planLabel)}</strong> ${planBadge}</span></div>
        ${expires ? `<div class="cab-kv"><span class="k">Срок</span><span class="v">${expires}</span></div>` : ''}
      </div>
      ${ntCard}
      <div class="cab-card"><h4>Доступные разделы</h4><div class="chips-in">${(uxMode === 'beginner'
        ? ['Учебный терминал', 'Community']
        : activeFeatures.map(f => f.label)
      ).map(label => `<span class="chip-tag">${esc(label)}</span>`).join('') || '<span class="cab-sub">Разделы не назначены</span>'}</div></div>`;
  }

  async function renderSharedQueueInto(node) {
    // Anonymized shared owner-training NinjaTrader status: free / busy / queued,
    // occupancy and the caller's own position only — never another user's
    // identity — plus the caller's single limited coordinator agent.
    try {
      const [st, alloc] = await Promise.all([
        API.http.ntResourceStatus(),
        API.http.ntAllocation().catch(() => null),
      ]);
      if (!st || st.resource_kind !== 'shared_owner_training') { node.innerHTML = ''; return; }
      const badge = st.state === 'busy' ? '<span class="badge pending">выполняется бэктест</span>'
        : (st.state === 'queued' ? '<span class="badge pending">в очереди</span>'
        : '<span class="badge live">свободен</span>');
      const occ = `<div class="cab-sub">В очереди: <strong>${esc(Number(st.queue_depth || 0))}</strong> · выполняется: <strong>${esc(Number(st.active_count || 0))}</strong></div>`;
      const yours = st.your_job && st.your_job.state === 'queued'
        ? `<div class="cab-sub">Ваша позиция в очереди: <strong>${esc(st.your_job.position)}</strong></div>` : '';
      const msg = st.message ? `<div class="finance-note">${esc(st.message)}</div>` : '';
      const upsell = st.upsell ? `<div class="cab-sub">${esc(st.upsell)}</div>` : '';
      let agentBlock = '';
      const a = alloc && alloc.allocation;
      if (a && Array.isArray(a.agents) && a.agents.length) {
        const opLabel = { training: 'обучение', backtest: 'бэктест', compile: 'компиляция', optimization: 'оптимизация', telemetry_read: 'телеметрия', live: 'live' };
        const ops = (a.allowed_operations || []).map(o => opLabel[o] || o).join(', ');
        agentBlock = `<div class="cab-kv"><span class="k">Ваш агент</span><span class="v">${a.agents.map(n => `<span class="chip-tag">${esc(n)}</span>`).join(' ')}</span></div>`
          + (ops ? `<div class="cab-sub">Доступные операции: ${esc(ops)}. Общий контур ограничен наблюдением и постановкой заданий в общую очередь.</div>` : '');
      }
      node.innerHTML = `<div class="cab-kv"><span class="k">Общий NinjaTrader</span><span class="v">${badge}</span></div>${occ}${yours}${agentBlock}${msg}${upsell}`;
    } catch (e) { node.innerHTML = ''; }
  }

  async function renderNinjaInto(node, me) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Проверка…</div>';
    try {
      const [ws, setup] = await Promise.all([API.http.workspaces(), API.http.bridgeSetup()]);
      const active = ws.active_workspace || {};
      const rows = ws.workspaces || [];
      const connectorMode = setup.transport === 'production_connector';
      if (me && me.is_owner && !connectorMode) {
        node.innerHTML = `<div class="cab-kv"><span class="k">Статус</span><span class="v"><span class="badge live">Подключён ваш NinjaTrader</span></span></div><div class="cab-sub">Полный доступ владельца: все реальные счета и все возможности интерфейса.</div>`;
        return;
      }
      const canPersonal = !!(me.is_owner || (me.capabilities || {}).personal_nt === true || (me.features || {}).personal_nt === true);
      const ntAccess = me.nt_access || {};
      const googleOk = !!(me.is_owner || ntAccess.google_ok || (me.user && me.user.google_linked));
      const tgOk = !!(me.is_owner || ntAccess.telegram_ok);
      const dualNote = me.is_owner ? '' : `<div class="finance-note">NinjaTrader: Google ${googleOk ? '✓' : 'нужен'} · Telegram-подтверждение ${tgOk ? '✓' : 'нужно'}. Остальной кабинет работает без Google.</div>`;
      const areaSwitch = rows.length > 1
        ? `<div class="cab-kv"><span class="k">Область</span><span class="v"><select id="nt-area">${rows.map(r => `<option value="${esc(r.workspace_id)}" ${r.workspace_id === active.workspace_id ? 'selected' : ''}>${esc(r.uses_owner_runtime ? 'Наблюдение за владельцем' : (r.display_name || 'Мой NinjaTrader'))}</option>`).join('')}</select></span></div>`
        : '';
      let inner = dualNote + areaSwitch;
      if (active.uses_owner_runtime && !connectorMode) {
        inner += `<div class="cab-sub">Сейчас вы наблюдаете за реальным аккаунтом владельца (только просмотр). Наблюдение не требует Google.</div>`;
        inner += `<div id="nt-shared-queue"></div>`;
        inner += canPersonal
          ? `<div class="dchart-actions"><button class="btn primary" id="nt-connect">Подключить свой NinjaTrader</button></div>`
          : `<div class="cab-sub">Свой NinjaTrader доступен на тарифах «Стандарт» и выше.</div>`;
      } else {
        const conns = setup.connections || [];
        const onlineCount = conns.filter(c => c.functional_online).length;
        const heartbeatOnlyCount = conns.filter(c => c.heartbeat_online && !c.functional_online).length;
        const stateLabel = { online: 'онлайн', degraded: 'heartbeat без данных', pending: 'ожидает подписи', offline: 'офлайн', revoked: 'отозван' };
        const stateBadge = { online: 'live', degraded: 'pending', pending: 'pending', offline: 'archived', revoked: 'failed' };
        inner += `<div class="cab-kv"><span class="k">Ваш NinjaTrader</span><span class="v">${onlineCount ? `<span class="badge live">функционально онлайн · ${onlineCount}</span>` : (heartbeatOnlyCount ? '<span class="badge pending">heartbeat есть, account snapshot отсутствует</span>' : (conns.length ? '<span class="badge pending">нет активной сессии</span>' : '<span class="badge pending">не подключён</span>'))}</span></div>`;
        // Two things an operator can act on, said once and prominently instead
        // of being buried as a detail line on one connection row.
        const needRestart = conns.filter(c => c.restart_required && c.status !== 'revoked');
        if (needRestart.length) {
          inner += `<div class="nt-notice nt-notice-action" role="status">Доступно обновление StratForge Connector. Перезапустите NinjaTrader, чтобы завершить обновление и восстановить подключение.${needRestart.length > 1 ? ` <span class="cab-sub">Устройств: ${needRestart.length}</span>` : ''}</div>`;
        }
        const wrongEnv = conns.filter(c => c.environment_mismatch && c.status !== 'revoked');
        if (wrongEnv.length) {
          inner += `<div class="nt-notice nt-notice-warn" role="status">Этот Connector зарегистрирован в другом окружении (${wrongEnv.map(c => esc(String(c.deployment_environment || '—'))).join(', ')}) и здесь отклоняется. Подключение восстановится только в своём окружении или после повторной регистрации.</div>`;
        }
        if (connectorMode) {
          inner += conns.length ? `<div class="nt-connections">${conns.map(c => {
            const rawStatus = String(c.status || 'offline');
            const status = rawStatus === 'online' ? (c.functional_online ? 'online' : 'degraded') : rawStatus;
            const fingerprint = String(c.public_key_fingerprint || '');
            const version = [c.connector_version, c.nt_version && ('NT ' + c.nt_version)].filter(Boolean).join(' · ');
            const updateLabel = {
              compatible: 'версия актуальна',
              update_available: 'обновление подготовится при безопасном перезапуске',
              blocked: 'обновление обязательно — команды исполнения заблокированы',
            }[String(c.update_state || '')] || '';
            const details = [
              version,
              c.release_channel ? ('канал ' + c.release_channel) : '',
              updateLabel,
              c.last_heartbeat_utc ? ('heartbeat ' + c.last_heartbeat_utc) : '',
              c.account_snapshot_at_utc ? (`account snapshot ${c.account_snapshot_at_utc} · счетов ${c.account_snapshot_accounts || 0}`) : '',
              (c.account_labels || []).join(', '),
            ].filter(Boolean).map(v => esc(v)).join(' · ');
            return `<div class="cab-kv nt-connection"><span class="k"><strong>${esc(c.machine_label || 'NinjaTrader')}</strong><br><span class="mono" title="${esc(fingerprint)}">${esc(fingerprint ? fingerprint.slice(0, 22) + '…' : '')}</span></span><span class="v"><span class="badge ${stateBadge[status] || 'archived'}">${esc(stateLabel[status] || status)}</span>${details ? `<div class="cab-sub">${details}</div>` : ''}${status !== 'revoked' ? `<button class="btn sm danger" data-nt-revoke="${esc(c.connection_id || '')}">Отозвать</button>` : ''}</span></div>`;
          }).join('')}</div>` : '<div class="cab-sub">Установок пока нет. Код одноразовый и действует 10 минут.</div>';
          const installer = setup.installer || {};
          inner += installer.download_url
            ? `<div class="dchart-actions"><a class="btn primary" href="${esc(installer.download_url)}">Скачать StratForge Connector</a></div>`
            : `<div class="finance-note">${esc(installer.message || 'Установщик Connector ещё не опубликован.')}</div>`;
        }
        inner += `<ol class="nt-steps">${(setup.steps || []).map(s => `<li>${esc(s)}</li>`).join('')}</ol>`;
        if (setup.runtime_data_dir) inner += `<div class="cab-kv"><span class="k">runtime_data_dir</span><span class="v mono nt-path">${esc(setup.runtime_data_dir)}</span></div>`;
        inner += `<div class="dchart-actions">${connectorMode ? '' : '<button class="btn ghost" id="nt-copycfg">Скопировать конфиг</button>'}<button class="btn primary" id="nt-pair">Получить код подключения</button>${me.is_owner ? '' : '<button class="btn ghost" id="nt-observe">Вернуться к наблюдению</button>'}</div>`;
      }
      if (!me.is_owner && (!googleOk || !tgOk)) {
        inner += `<div class="dchart-actions"><button class="btn ghost" id="nt-dual">Пройти Google + Telegram для NT</button></div>`;
      }
      node.innerHTML = inner;
      const sharedQueue = qs('#nt-shared-queue', node);
      if (sharedQueue) renderSharedQueueInto(sharedQueue);
      const areaSel = qs('#nt-area', node);
      if (areaSel) areaSel.onchange = async () => { try { await API.http.workspaceSelect(areaSel.value); toast('Область переключена'); location.reload(); } catch (e) { reportError(e); } };
      const dualBtn = qs('#nt-dual', node);
      if (dualBtn) dualBtn.onclick = async () => { dualBtn.disabled = true; try { await ensureNtDualAuth(me); await renderNinjaInto(node, me); } catch (e) { reportError(e); } finally { dualBtn.disabled = false; } };
      const connect = qs('#nt-connect', node);
      if (connect) connect.onclick = async () => {
        connect.disabled = true;
        try {
          if (!(await ensureNtDualAuth(me))) { connect.disabled = false; return; }
          await API.http.workspacePersonal({ display_name: 'Мой NinjaTrader' });
          toast('Личный контур создан');
          await renderNinjaInto(node, me);
        } catch (e) { reportError(e); connect.disabled = false; }
      };
      const pair = qs('#nt-pair', node);
      if (pair) pair.onclick = async () => {
        pair.disabled = true;
        try {
          if (!(await ensureNtDualAuth(me))) return;
          const stepUp = me.is_owner ? '' : await ntStepUp('pairing');
          if (!me.is_owner && !stepUp) return;
          const out = await API.http.bridgePairStart({
            machine_label: 'Мой компьютер',
            transport: connectorMode ? 'production_connector' : 'local_development',
            step_up_challenge_id: stepUp || '',
          });
          showCode(out && out.code, 'Код подключения');
          if (connectorMode && out && out.pairing_uri && confirm('Код скопирован. Открыть установленный StratForge Connector?')) {
            location.href = out.pairing_uri;
          }
        } catch (e) { reportError(e); }
        finally { pair.disabled = false; }
      };
      const copycfg = qs('#nt-copycfg', node);
      if (copycfg) copycfg.onclick = () => { try { navigator.clipboard.writeText(JSON.stringify(setup.config_template || {}, null, 2)); toast('Конфиг NinjaTrader скопирован'); } catch (e) { reportError(e); } };
      node.querySelectorAll('[data-nt-revoke]').forEach(btn => btn.onclick = async () => {
        const id = btn.getAttribute('data-nt-revoke');
        if (!id || !confirm('Отозвать эту установку NinjaTrader? Текущая сессия и ожидающие команды будут остановлены.')) return;
        btn.disabled = true;
        try {
          const stepUp = me.is_owner ? '' : await ntStepUp('connector_revoke');
          if (!me.is_owner && !stepUp) { btn.disabled = false; return; }
          await API.http.bridgeConnectionRevoke(id, { step_up_challenge_id: stepUp || '' });
          toast('Установка отозвана');
          await renderNinjaInto(node, me);
        } catch (e) { reportError(e); btn.disabled = false; }
      });
      const observe = qs('#nt-observe', node);
      if (observe) observe.onclick = async () => { const ownerWs = (rows.find(r => r.uses_owner_runtime) || {}).workspace_id; if (!ownerWs) return; try { await API.http.workspaceSelect(ownerWs); toast('Вернулись к наблюдению'); location.reload(); } catch (e) { reportError(e); } };
    } catch (e) { renderError(node, e, () => renderNinjaInto(node, me)); }
  }

  function userRowHtml(u, catalog, planOptions, monitoring) {
    const roleSel = u.is_owner ? '<span class="badge live">owner</span>' : `<select data-user-role="${esc(u.user_id)}" ${u.status === 'active' ? '' : 'disabled'}><option value="read_only" ${u.role === 'read_only' ? 'selected' : ''}>Только чтение</option><option value="full_control" ${u.role === 'full_control' ? 'selected' : ''}>Полное управление</option></select>`;
    const revoke = u.is_owner ? '' : `<button class="btn sm danger" data-user-revoke="${esc(u.user_id)}" ${u.status === 'active' ? '' : 'disabled'}>Отозвать</button>`;
    const featBtn = u.is_owner ? '' : `<button class="btn sm ghost" data-user-feat="${esc(u.user_id)}">Параметры</button>`;
    const planBtn = u.is_owner ? '' : `<button class="btn sm ghost" data-user-plan="${esc(u.user_id)}">Тариф</button>`;
    const detailBtn = `<button class="btn sm ghost" data-user-detail="${esc(u.user_id)}">Детали</button>`;
    const blockBtn = u.is_owner ? '' : (u.status === 'blocked'
      ? `<button class="btn sm ghost" data-user-unblock="${esc(u.user_id)}">Разблокировать</button>`
      : `<button class="btn sm ghost" data-user-block="${esc(u.user_id)}" ${u.status === 'active' ? '' : 'disabled'}>Блокировать</button>`);
    const delBtn = u.is_owner ? '' : `<button class="btn sm danger" data-user-delete="${esc(u.user_id)}">Удалить</button>`;
    const feats = u.features || {};
    const featPanel = u.is_owner ? '' : `<div class="feat-panel" data-feat-panel="${esc(u.user_id)}" hidden>${(catalog || []).map(f => `<div class="feat-row"><span>${esc(f.label)}</span><label class="switch"><input type="checkbox" data-feat-toggle="${esc(u.user_id)}" data-feat-id="${esc(f.id)}" ${feats[f.id] !== false ? 'checked' : ''}><span class="sl"></span></label></div>`).join('')}</div>`;
    const planLabel = u.subscription && u.subscription.plan && u.subscription.plan.label ? u.subscription.plan.label : '';
    const planPanel = u.is_owner ? '' : `<div class="feat-panel" data-plan-panel="${esc(u.user_id)}" hidden><div class="finance-note">Текущий тариф: <strong>${esc(planLabel || 'Базовый доступ аккаунта')}</strong>. Назначьте тариф после проверки оплаты в PayPal.</div><div class="flex gap-sm" style="align-items:flex-end;flex-wrap:wrap"><label style="flex:1;min-width:160px">Тариф<select data-grant-plan="${esc(u.user_id)}">${planOptions || ''}</select></label><label>Срок дней (0=бессрочно)<input type="number" data-grant-days="${esc(u.user_id)}" min="0" max="3650" value="30" style="width:90px"></label><button class="btn sm primary" data-grant-apply="${esc(u.user_id)}">Назначить</button><button class="btn sm ghost" data-grant-clear="${esc(u.user_id)}">Сбросить</button></div></div>`;
    const detailPanel = `<div class="feat-panel user-detail-panel" data-detail-panel="${esc(u.user_id)}" hidden></div>`;
    const statusCls = u.status === 'active' ? 'live' : u.status === 'pending' ? 'pending' : u.status === 'blocked' ? 'pending' : 'archived';
    const mon = monitoring || {};
    const monitorLine = mon.online
      ? `<div class="row-sub user-monitor-line"><span class="support-online-dot"></span>${esc(mon.session_count || 1)} онлайн · CPU ${Number(mon.cpu_main_thread_percent || 0).toFixed(0)}% · память ${Number(mon.js_heap_used_mb || 0).toFixed(0)} МБ · сеть ${Number(mon.network_mb_per_min || 0).toFixed(1)} МБ/мин${mon.alert_count ? ` · <span class="support-alert-inline">⚠ ${esc(mon.alert_count)}</span>` : ''}</div>`
      : '<div class="row-sub user-monitor-line">Не в сети · телеметрия вкладки недоступна</div>';
    return `<div class="row user-row"><div class="row-main u-main">${avatarHtml(u, '')}<div class="u-txt"><div class="row-title">${esc(userLabel(u))}${u.is_owner ? ' · владелец' : ''}</div><div class="row-sub">ID ${esc(u.user_id)} · ${esc(u.email || 'e-mail не указан')}${u.phone_mask ? ' · ' + esc(u.phone_mask) : ''}${planLabel ? ' · ' + esc(planLabel) : ''}</div>${monitorLine}</div></div><span class="badge ${statusCls}">${esc(u.status || '—')}</span>${roleSel}${detailBtn}${featBtn}${planBtn}${blockBtn}${revoke}${delBtn}</div>${featPanel}${planPanel}${detailPanel}`;
  }
  function shortDt(value) { return value ? String(value).replace('T', ' ').replace('Z', '').slice(0, 16) : ''; }
  const SUPPORT_DETAIL_TIMERS = new Map();
  function stopUserSupportPoll(uid) {
    const timer = SUPPORT_DETAIL_TIMERS.get(String(uid));
    if (timer) clearInterval(timer);
    SUPPORT_DETAIL_TIMERS.delete(String(uid));
  }
  function supportStatusLabel(status) {
    return ({ pending: 'ожидает пользователя', claimed: 'открыт пользователем', completed: 'получен', denied: 'отказано', error: 'ошибка', expired: 'истёк', deleted: 'удалён' })[status] || status || '—';
  }
  function userSupportHtml(data, uid) {
    const telemetry = data.sessions || [];
    const authSessions = data.auth_sessions || [];
    const alerts = data.alerts || [];
    const shots = data.screenshot_requests || [];
    const activeShots = shots.slice(0, 8);
    const currentSessionId = String(data.current_session_id || '');
    const selfNote = data.is_self
      ? '<div class="finance-note support-self-note"><strong>Это ваш один аккаунт владельца.</strong> ID относится к аккаунту Telegram, а не к компьютеру. Ниже показаны его отдельные устройства и сессии. Удалять аккаунт или подключаться заново не нужно — устройство можно переименовать. Если старая сессия ещё без имени, просто обновите приложение на том устройстве: оно появится в живой телеметрии.</div>'
      : '';
    const liveCards = telemetry.map(session => {
      const cpu = session.cpu_available ? `${Number(session.cpu_main_thread_percent || 0).toFixed(1)}% (${Number(session.cpu_core_equivalent || 0).toFixed(2)} ядра)` : 'недоступно';
      const memory = session.memory_available ? `${Number(session.js_heap_used_mb || 0).toFixed(0)} / ${Number(session.js_heap_limit_mb || 0).toFixed(0)} МБ` : 'недоступно';
      const target = session.session_id ? `data-support-reload-session="${esc(session.session_id)}"` : `data-support-reload-client="${esc(session.client_id)}"`;
      const isCurrent = !!currentSessionId && String(session.session_id || '') === currentSessionId;
      const rename = session.device_id ? `<button class="btn sm ghost" data-support-rename-device="${esc(session.device_id)}" data-support-device-name="${esc(session.device_name || 'Устройство')}">Переименовать</button>` : '';
      return `<div class="support-session ${session.online ? 'online' : ''}"><div class="flex between gap-sm"><div><strong>${esc(session.device_name || 'Устройство')}${isCurrent ? ' · <span class="badge live">текущее устройство</span>' : ''}</strong><div class="cab-sub">${esc(session.client || 'Браузер')}${session.platform ? ' · ' + esc(session.platform) : ''} · ${session.online ? 'в сети' : 'нет связи'} · ${esc(session.page || 'страница не указана')}</div><div class="cab-sub">Последний отчёт ${esc(shortDt(session.reported_at_utc) || '—')} · ${session.visible ? 'вкладка видима' : 'в фоне'} · ${esc(session.effective_type || 'сеть —')}</div></div><div class="flex gap-sm support-session-actions">${rename}${session.online ? `<button class="btn sm ghost" data-support-client-shot="${esc(session.client_id)}">Снимок</button><button class="btn sm ghost" ${target}>Перезагрузить</button>` : ''}</div></div><div class="support-metrics"><span>CPU вкладки <strong>${cpu}</strong></span><span>JS-память <strong>${memory}</strong></span><span>Сеть <strong>${Number(session.network_mb_per_min || 0).toFixed(2)} МБ/мин</strong></span><span>Канал <strong>${Number(session.downlink_mbps || 0).toFixed(1)} Мбит/с · ${Number(session.rtt_ms || 0).toFixed(0)} мс</strong></span><span>Логических ядер устройства <strong>${esc(session.logical_cores || '—')}</strong></span></div></div>`;
    }).join('');
    const authCards = authSessions.map(session => {
      const isCurrent = !!currentSessionId && String(session.session_id || '') === currentSessionId;
      return `<div class="row support-auth-session"><div class="row-main"><div class="row-title">${esc(session.device_name || session.machine || 'Устройство')} · ${esc(session.client || 'Браузер')}${isCurrent ? ' · <span class="badge live">текущая сессия</span>' : ''}</div><div class="row-sub">Создана ${esc(shortDt(session.created_at_utc) || '—')}${session.ip ? ' · ' + esc(session.ip) : ''}</div></div><button class="btn sm ghost" data-support-reload-session="${esc(session.session_id)}">Перезагрузить</button><button class="btn sm danger" data-support-end-session="${esc(session.session_id)}" data-support-current="${isCurrent ? '1' : ''}">Завершить</button></div>`;
    }).join('');
    const shotCards = activeShots.map(shot => `<div class="support-shot"><div class="flex between gap-sm"><div><strong>${esc(supportStatusLabel(shot.status))}</strong><div class="cab-sub">${esc(shortDt(shot.created_at_utc) || '—')}${shot.retained_until_utc ? ' · хранится до ' + esc(shortDt(shot.retained_until_utc)) : ''}</div></div>${shot.status === 'completed' ? `<button class="btn sm danger" data-support-delete-shot="${esc(shot.request_id)}">Удалить</button>` : ''}</div>${shot.error ? `<div class="support-error">${esc(shot.error)}</div>` : ''}${shot.image_url ? `<a href="${esc(shot.image_url)}" target="_blank" rel="noopener"><img src="${esc(shot.image_url)}" loading="lazy" alt="Снимок экрана пользователя"></a>` : ''}</div>`).join('');
    return `${selfNote}<div class="support-toolbar"><button class="btn primary" data-support-request-shot>Запросить снимок экрана</button><button class="btn ghost" data-support-reload-all ${authSessions.length || telemetry.some(row => row.online) ? '' : 'disabled'}>Перезагрузить все</button><button class="btn danger" data-support-end-all ${authSessions.length ? '' : 'disabled'} data-support-self="${data.is_self ? '1' : ''}">Завершить все браузерные сесии</button>${(CURRENT_AUTH && CURRENT_AUTH.is_owner && CURRENT_AUTH.runtime && CURRENT_AUTH.runtime.is_staging && !data.is_self) ? '<button class="btn ghost" data-support-impersonate>Войти как пользователь</button>' : ''}<button class="btn ghost" data-support-refresh>Обновить</button></div>
      <div class="finance-note support-privacy-note">${esc(data.telemetry_note || '')} Снимок возможен только после согласия пользователя и системного выбора экрана; хранится зашифрованным не более ${esc(data.screenshot_retention_hours || 24)} часов.</div>
      ${alerts.length ? `<div class="support-alerts">${alerts.map(alert => `<div class="support-alert ${alert.severity === 'critical' ? 'critical' : ''}">⚠ ${esc(alert.message)}</div>`).join('')}</div>` : '<div class="support-ok">Критических превышений сейчас нет.</div>'}
      <div class="section-title">Живая телеметрия вкладок</div>${liveCards || '<div class="empty-state">Пользователь не передаёт телеметрию: приложение закрыто или ещё не обновлено.</div>'}
      <div class="section-title">Активные браузерные сессии</div><div class="list">${authCards || '<div class="empty-state">Активных cookie-сессий нет.</div>'}</div>
      <div class="section-title">Запросы снимков</div><div class="support-shots">${shotCards || '<div class="empty-state">Снимки ещё не запрашивались.</div>'}</div>`;
  }
  async function refreshUserSupport(container, uid) {
    if (!container || container.dataset.supportBusy === '1') return;
    container.dataset.supportBusy = '1';
    try {
      const data = await API.http.ownerSupportUser(uid);
      container.innerHTML = userSupportHtml(data, uid);
      const run = async (button, task, success) => { button.disabled = true; try { await task(); toast(success); await refreshUserSupport(container, uid); } catch (e) { reportError(e); button.disabled = false; } };
      const shot = qs('[data-support-request-shot]', container);
      if (shot) shot.onclick = () => {
        if (!confirm('Отправить пользователю одноразовый запрос снимка? Без его явного согласия и выбора экрана снимок не создастся.')) return;
        run(shot, () => API.http.ownerSupportScreenshotRequest(uid, 'Помощь с диагностикой приложения'), 'Запрос отправлен пользователю');
      };
      const reloadAll = qs('[data-support-reload-all]', container);
      if (reloadAll) reloadAll.onclick = () => run(reloadAll, () => API.http.ownerSupportReload(uid, { all_sessions: true }), 'Команда перезагрузки отправлена');
      const endAll = qs('[data-support-end-all]', container);
      if (endAll) endAll.onclick = () => {
        const warning = endAll.dataset.supportSelf === '1'
          ? 'Это ваш аккаунт. Завершить все браузерные сессии, включая текущую? Вы сразу выйдете из приложения на этих устройствах.'
          : 'Принудительно завершить все браузерные сессии пользователя?';
        if (confirm(warning)) run(endAll, () => API.http.authUserSessions(uid, { all_sessions: true }), 'Сессии завершены');
      };
      const impersonate = qs('[data-support-impersonate]', container);
      if (impersonate) impersonate.onclick = () => {
        if (!confirm('Войти как этот пользователь? Появится красный banner тестового режима.')) return;
        run(impersonate, async () => {
          await API.http.ownerImpersonate(Number(uid));
          setTimeout(() => location.reload(), 400);
        }, 'Impersonation активна');
      };
      const refresh = qs('[data-support-refresh]', container); if (refresh) refresh.onclick = () => refreshUserSupport(container, uid);
      qsa('[data-support-reload-session]', container).forEach(button => button.onclick = () => run(button, () => API.http.ownerSupportReload(uid, { session_id: button.dataset.supportReloadSession }), 'Команда перезагрузки отправлена'));
      qsa('[data-support-reload-client]', container).forEach(button => button.onclick = () => run(button, () => API.http.ownerSupportReload(uid, { client_id: button.dataset.supportReloadClient }), 'Команда перезагрузки отправлена'));
      qsa('[data-support-client-shot]', container).forEach(button => button.onclick = () => {
        if (!confirm('Запросить снимок именно у этого устройства? На нём появится подтверждение и системный выбор экрана.')) return;
        run(button, () => API.http.ownerSupportScreenshotRequest(uid, 'Помощь с диагностикой приложения', button.dataset.supportClientShot), 'Запрос отправлен выбранному устройству');
      });
      qsa('[data-support-rename-device]', container).forEach(button => button.onclick = () => {
        const current = button.dataset.supportDeviceName || 'Устройство';
        const name = window.prompt('Введите понятное имя, например «Основной компьютер» или «Ноутбук»:', current);
        if (name == null || !String(name).trim() || String(name).trim() === current) return;
        run(button, () => API.http.ownerSupportDeviceName(uid, button.dataset.supportRenameDevice, String(name).trim()), 'Имя устройства сохранено');
      });
      qsa('[data-support-end-session]', container).forEach(button => button.onclick = () => {
        const warning = button.dataset.supportCurrent === '1'
          ? 'Это текущая сессия. Завершить её? Вы сразу выйдете из приложения на этом устройстве.'
          : 'Завершить выбранную сессию?';
        if (confirm(warning)) run(button, () => API.http.authUserSessions(uid, { session_id: button.dataset.supportEndSession }), 'Сессия завершена');
      });
      qsa('[data-support-delete-shot]', container).forEach(button => button.onclick = () => { if (confirm('Удалить зашифрованный снимок сейчас?')) run(button, () => API.http.ownerSupportScreenshotDelete(button.dataset.supportDeleteShot), 'Снимок удалён'); });
    } catch (e) { renderError(container, e, () => refreshUserSupport(container, uid)); }
    finally { container.dataset.supportBusy = ''; }
  }
  function startUserSupportPoll(container, uid) {
    stopUserSupportPoll(uid);
    refreshUserSupport(container, uid);
    const timer = setInterval(() => {
      const detail = container && container.closest('[data-detail-panel]');
      if (!container || !container.isConnected || (detail && detail.hidden)) return;
      refreshUserSupport(container, uid);
    }, 5000);
    SUPPORT_DETAIL_TIMERS.set(String(uid), timer);
    onLeave(() => stopUserSupportPoll(uid));
  }
  async function renderUserDetail(panel, uid, listNode) {
    panel.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>';
    try {
      const d = await API.http.authUserDetail(uid);
      const u = d.user || {};
      const caps = d.capabilities || {};
      const catalog = d.capability_catalog || [];
      const adminCaps = d.admin_capabilities || {};
      const adminCatalog = d.admin_capability_catalog || [];
      const adminGrants = u.admin_permission_grants || {};
      const canGrant = !!(CURRENT_AUTH && CURRENT_AUTH.is_owner);
      const nt = d.nt_connection || {};
      const hist = u.login_history || [];
      const devices = u.devices || [];
      const sub = d.subscription || {};
      const access = d.access || {};
      const planLabel = (sub.plan && sub.plan.label) || 'Базовый доступ аккаунта';
      const ntMode = nt.mode === 'own_ninjatrader' ? 'Свой NinjaTrader' : 'Наблюдение за владельцем';
      const telegramIdentity = (u.linked_providers || []).find(item => item && item.provider === 'telegram');
      const permissionsHtml = u.is_owner
        ? '<div class="finance-note">У владельца всегда полный доступ. Индивидуальные переключатели разрешений для него не требуются.</div>'
        : (canGrant
          ? `<div class="section-title">Продуктовые разрешения (тариф + индивидуально)</div><div class="finance-note">Эти права управляют продуктом и не открывают Admin Panel.</div><div class="cap-panel">${catalog.map(c => `<div class="feat-row"><span>${esc(c.label)}${c.hint ? ` <span class="cab-sub">(${esc(c.hint)})</span>` : ''}</span><label class="switch"><input type="checkbox" data-cap-toggle="${esc(uid)}" data-cap-id="${esc(c.id)}" ${caps[c.id] ? 'checked' : ''}><span class="sl"></span></label></div>`).join('')}</div>`
          : `<div class="section-title">Продуктовые разрешения</div><div class="cap-panel">${catalog.filter(c => caps[c.id]).map(c => `<div class="feat-row"><span>${esc(c.label)}</span><span class="badge live">активно</span></div>`).join('') || '<div class="empty-state">Нет активных прав.</div>'}</div>`);
      const adminPermissionsHtml = u.is_owner
        ? ''
        : `<div class="section-title">Административные grants</div><div class="finance-note">Не связаны с тарифом. ${canGrant ? 'Выдать или отозвать их может только owner; UTC-срок необязателен.' : 'Доступен только просмотр эффективных grants.'}</div><div class="cap-panel">${adminCatalog.map(c => {
          const grant = adminGrants[c.id] || {};
          const expiry = String(grant.expires_at_utc || '').replace('Z', '').slice(0, 16);
          return `<div class="admin-grant-row"><div><strong>${esc(c.label)}</strong><div class="cab-sub mono">${esc(c.id)} · risk=${esc(c.risk || 'high')}</div></div>${canGrant ? `<input type="datetime-local" aria-label="UTC expiry" data-admin-cap-expiry="${esc(c.id)}" value="${esc(expiry)}"><label class="switch"><input type="checkbox" data-admin-cap-toggle="${esc(uid)}" data-admin-cap-id="${esc(c.id)}" ${adminCaps[c.id] ? 'checked' : ''}><span class="sl"></span></label>` : `<span class="badge ${adminCaps[c.id] ? 'live' : 'archived'}">${adminCaps[c.id] ? 'активно' : 'нет'}</span>`}</div>`;
        }).join('')}</div>`;
      const accessStateLabel = {
        active: 'активен', expired: 'истёк', not_granted: 'не выдавался',
        unlimited: 'бессрочно', superseded: 'заменён другим доступом',
      }[String(access.state || '')] || String(access.state || '—');
      const accessStateBadge = access.state === 'active' || access.state === 'unlimited'
        ? 'live' : (access.state === 'expired' ? 'failed' : 'pending');
      const accessDate = (value) => {
        if (!value) return '—';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ru-RU');
      };
      const accessHistoryHtml = (access.history || []).map(event => {
        const before = event.before || {};
        const after = event.after || {};
        const actor = event.actor_user_id ? `owner ${event.actor_user_id}` : (event.source || 'system');
        return `<div class="row"><div class="row-main"><div class="row-title">${esc(event.event === 'initial_trial_granted' ? 'Пробный период создан' : 'Пробный период продлён')}</div><div class="row-sub">${esc(accessDate(event.at_utc))} · ${esc(actor)}${event.reason ? ' · ' + esc(event.reason) : ''}</div><div class="row-sub">Было: ${esc(accessDate(before.expires_at_utc))} → Стало: ${esc(accessDate(after.expires_at_utc))}</div></div></div>`;
      }).join('') || '<div class="empty-state">История доступа пока пуста.</div>';
      // Compact tabs keep identity, access, rights and support separated. The card tab
      // is the canonical builder at admin scope: the same facts the account
      // sees in its own Cabinet, rendered by the same function. The identity,
      // device and session lists that used to live here were a second,
      // independent description of the same things, and are gone.
      panel.innerHTML = `
        <div class="cab-tabs udetail-tabs">
          <button class="cab-tab on" data-udetail-tab="card">Карточка</button>
          <button class="cab-tab" data-udetail-tab="access">Доступ</button>
          <button class="cab-tab" data-udetail-tab="rights">Права</button>
          <button class="cab-tab" data-udetail-tab="support">Поддержка</button>
        </div>
        <div class="udetail-tabbody" data-udetail-body></div>`;
      const tabBody = qs('[data-udetail-body]', panel);
      const wireRights = () => {
        qsa('[data-cap-toggle]', tabBody).forEach(t => t.onchange = async () => {
          t.disabled = true;
          try {
            await API.http.authUserPermission(t.dataset.capToggle, t.dataset.capId, t.checked);
            toast('Разрешение обновлено');
          } catch (e) { t.checked = !t.checked; reportError(e); }
          finally { t.disabled = false; }
        });
        qsa('[data-admin-cap-toggle]', tabBody).forEach(t => t.onchange = async () => {
          t.disabled = true;
          const expiryInput = qs('[data-admin-cap-expiry="' + t.dataset.adminCapId + '"]', tabBody);
          let expiresAt = '';
          try {
            if (t.checked && expiryInput && expiryInput.value) expiresAt = new Date(expiryInput.value + 'Z').toISOString();
            await API.http.authUserAdminPermission(t.dataset.adminCapToggle, t.dataset.adminCapId, t.checked, expiresAt);
            toast(t.checked ? 'Административный grant выдан' : 'Административный grant отозван');
            await renderUserDetail(panel, uid, listNode);
          } catch (e) { t.checked = !t.checked; reportError(e); t.disabled = false; }
        });
      };
      const wireAccess = () => {
        const runExtend = async (payload, button) => {
          button.disabled = true;
          try {
            const reason = (qs('[data-trial-reason]', tabBody) || {}).value || '';
            const idempotencyKey = (window.crypto && crypto.randomUUID)
              ? crypto.randomUUID() : `trial-${uid}-${Date.now()}`;
            await API.http.ownerTrialExtend(uid, { ...payload, reason, idempotency_key: idempotencyKey });
            toast('Пробный период продлён');
            await renderUserDetail(panel, uid, listNode);
            const accessTab = qs('[data-udetail-tab="access"]', panel);
            if (accessTab) accessTab.click();
          } catch (e) { reportError(e); button.disabled = false; }
        };
        const daysButton = qs('[data-trial-extend-days]', tabBody);
        if (daysButton) daysButton.onclick = () => {
          const days = Number((qs('[data-trial-days]', tabBody) || {}).value || 0);
          if (!Number.isInteger(days) || days < 1) { toast('Укажите целое число дней'); return; }
          runExtend({ days }, daysButton);
        };
        const dateButton = qs('[data-trial-extend-date]', tabBody);
        if (dateButton) dateButton.onclick = () => {
          const raw = (qs('[data-trial-date]', tabBody) || {}).value || '';
          if (!raw) { toast('Укажите дату окончания'); return; }
          const date = new Date(raw);
          if (Number.isNaN(date.getTime())) { toast('Дата некорректна'); return; }
          runExtend({ expires_at_utc: date.toISOString() }, dateButton);
        };
      };
      const showTab = (which) => {
        qsa('[data-udetail-tab]', panel).forEach(
          b => b.classList.toggle('on', b.dataset.udetailTab === which));
        if (which === 'access') {
          tabBody.innerHTML = `
            <div class="udetail-grid">
              <div class="cab-kv"><span class="k">Пробный доступ</span><span class="v"><span class="badge ${accessStateBadge}">${esc(accessStateLabel)}</span></span></div>
              <div class="cab-kv"><span class="k">Начало</span><span class="v">${esc(accessDate(access.starts_at_utc))}</span></div>
              <div class="cab-kv"><span class="k">Окончание</span><span class="v">${esc(accessDate(access.expires_at_utc))}</span></div>
            </div>
            ${canGrant && !u.is_owner ? `<div class="section-title">Продлить доступ</div>
              <div class="finance-note">Количество дней прибавляется к текущему сроку; если он истёк — от текущего момента. Точная дата должна быть позже действующего срока.</div>
              <div class="trial-access-controls">
                <label>На дней<input type="number" min="1" max="3650" value="7" data-trial-days></label>
                <button class="btn primary" type="button" data-trial-extend-days>Продлить</button>
                <label>До даты<input type="datetime-local" data-trial-date></label>
                <button class="btn ghost" type="button" data-trial-extend-date>Установить дату</button>
                <label class="trial-access-reason">Основание<input maxlength="300" placeholder="Причина продления" data-trial-reason></label>
              </div>` : ''}
            <div class="section-title">История изменений</div><div class="list">${accessHistoryHtml}</div>`;
          wireAccess();
        } else if (which === 'rights') {
          tabBody.innerHTML = `
            <div class="udetail-grid">
              <div class="cab-kv"><span class="k">Тариф</span><span class="v">${esc(planLabel)}</span></div>
              <div class="cab-kv"><span class="k">NinjaTrader</span><span class="v">${esc(ntMode)}${nt.workspace ? ' · ' + esc(nt.workspace) : ''} ${nt.connected ? '<span class="badge live">подключён</span>' : '<span class="badge pending">нет</span>'}</span></div>
            </div>
            ${permissionsHtml}
            ${adminPermissionsHtml}`;
          wireRights();
        } else if (which === 'support') {
          tabBody.innerHTML = `<div class="user-support-live" data-user-support-live="${esc(uid)}"><div class="state-loading"><span class="spinner"></span>Загрузка мониторинга…</div></div>`;
          startUserSupportPoll(qs('[data-user-support-live]', tabBody), uid);
        } else {
          renderUserCardInto(tabBody, () => API.http.adminUserCard(uid));
        }
      };
      qsa('[data-udetail-tab]', panel).forEach(
        b => b.onclick = () => showTab(b.dataset.udetailTab));
      showTab('card');
    } catch (e) { renderError(panel, e, () => renderUserDetail(panel, uid, listNode)); }
  }
  async function renderUsersInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>';
    try {
      const [data, plansData, monitorData] = await withDeadline(Promise.all([API.http.authUsers(), API.http.ownerPlans().catch(() => ({ plans: [] })), API.http.ownerSupportMonitoring().catch(() => ({ users: [], online_count: 0, alert_count: 0 }))]), 'Список пользователей');
      const users = data.users || [];
      const catalog = data.feature_catalog || [];
      const planOptions = buildPlanOptions(plansData.plans || []);
      const monitoring = new Map((monitorData.users || []).map(row => [String(row.user_id), row]));
      node.innerHTML = `<div class="dchart-actions" style="justify-content:flex-start"><button class="btn primary" id="users-invite">＋ Пригласить (ссылка + промокод)</button></div>
        <div class="finance-note"><strong>Хранилище:</strong> ${esc((data.storage || {}).backend || '—')} · ${data.storage && data.storage.encrypted ? 'зашифровано' : 'ещё не создано'}. После подтверждения личности новый аккаунт автоматически получает полный пробный доступ на 7 дней.</div>
        <div class="finance-note"><strong>Мониторинг:</strong> ${esc(monitorData.online_count || 0)} пользователей онлайн${monitorData.alert_count ? ` · <span class="support-alert-inline">⚠ ${esc(monitorData.alert_count)} предупреждений</span>` : ' · превышений нет'}. Показатели относятся к вкладкам StratForge AI.</div>
        <div class="list account-user-list">${users.map(u => userRowHtml(u, catalog, planOptions, monitoring.get(String(u.user_id)))).join('') || '<div class="empty-state">Аккаунтов пока нет.</div>'}</div>`;
      const invite = qs('#users-invite', node);
      if (invite) invite.onclick = () => openAdminPanel('invites');
      qsa('[data-user-role]', node).forEach(s => s.onchange = async () => { s.disabled = true; try { await API.http.authUserRole(s.dataset.userRole, s.value); toast('Роль обновлена'); } catch (e) { reportError(e); } finally { s.disabled = false; } });
      qsa('[data-user-revoke]', node).forEach(b => b.onclick = async () => { if (!confirm('Отозвать аккаунт? Все его сессии завершатся.')) return; b.disabled = true; try { await API.http.authUserRevoke(b.dataset.userRevoke); toast('Аккаунт отозван'); await renderUsersInto(node); } catch (e) { reportError(e); b.disabled = false; } });
      qsa('[data-user-detail]', node).forEach(b => b.onclick = async () => { const uid = b.dataset.userDetail; const p = qs(`[data-detail-panel="${uid}"]`, node); if (!p) return; if (!p.hidden) { p.hidden = true; stopUserSupportPoll(uid); return; } p.hidden = false; await renderUserDetail(p, uid, node); });
      qsa('[data-user-block]', node).forEach(b => b.onclick = async () => { if (!confirm('Заблокировать пользователя? Доступ и сессии будут приостановлены.')) return; b.disabled = true; try { await API.http.authUserStatus(b.dataset.userBlock, 'blocked'); toast('Пользователь заблокирован'); await renderUsersInto(node); } catch (e) { reportError(e); b.disabled = false; } });
      qsa('[data-user-unblock]', node).forEach(b => b.onclick = async () => { b.disabled = true; try { await API.http.authUserStatus(b.dataset.userUnblock, 'active'); toast('Пользователь разблокирован'); await renderUsersInto(node); } catch (e) { reportError(e); b.disabled = false; } });
      qsa('[data-user-delete]', node).forEach(b => b.onclick = async () => { if (!confirm('Удалить пользователя навсегда? Это действие необратимо.')) return; b.disabled = true; try { await API.http.authUserDelete(b.dataset.userDelete); toast('Пользователь удалён'); await renderUsersInto(node); } catch (e) { reportError(e); b.disabled = false; } });
      qsa('[data-user-feat]', node).forEach(b => b.onclick = () => { const p = qs(`[data-feat-panel="${b.dataset.userFeat}"]`, node); if (p) p.hidden = !p.hidden; });
      qsa('[data-feat-toggle]', node).forEach(t => t.onchange = async () => { t.disabled = true; try { await API.http.authUserFeature(t.dataset.featToggle, t.dataset.featId, t.checked); toast('Параметр обновлён'); } catch (e) { t.checked = !t.checked; reportError(e); } finally { t.disabled = false; } });
      qsa('[data-user-plan]', node).forEach(b => b.onclick = () => { const p = qs(`[data-plan-panel="${b.dataset.userPlan}"]`, node); if (p) p.hidden = !p.hidden; });
      qsa('[data-grant-apply]', node).forEach(b => b.onclick = async () => {
        const uid = b.dataset.grantApply;
        const plan = (qs(`[data-grant-plan="${uid}"]`, node) || {}).value;
        const days = Number((qs(`[data-grant-days="${uid}"]`, node) || {}).value || 0);
        b.disabled = true;
        try { await API.http.ownerGrant(uid, plan, days); toast('Тариф назначен'); await renderUsersInto(node); }
        catch (e) { reportError(e); b.disabled = false; }
      });
      qsa('[data-grant-clear]', node).forEach(b => b.onclick = async () => {
        const uid = b.dataset.grantClear;
        b.disabled = true;
        try { await API.http.ownerGrant(uid, '', 0); toast('Тариф сброшен'); await renderUsersInto(node); }
        catch (e) { reportError(e); b.disabled = false; }
      });
      if (PENDING_USER_DETAIL) {
        const uid = PENDING_USER_DETAIL; PENDING_USER_DETAIL = '';
        const openBtn = qs(`[data-user-detail="${uid}"]`, node);
        if (openBtn) { openBtn.click(); try { openBtn.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) { /* ignore */ } }
      }
    } catch (e) { renderError(node, e, () => renderUsersInto(node)); }
  }

  function planPriceLabel(p) {
    const v = Number(p.price_usd || 0);
    if (!v) return 'Бесплатно';
    const s = v.toFixed(2).replace(/\.00$/, '');
    return '$' + s + (p.period ? ' / ' + esc(p.period) : '');
  }
  function paypalFor(handle, amount) {
    const h = String(handle || '').replace(/[^A-Za-z0-9_.\-]/g, '');
    if (!h) return '';
    return 'https://www.paypal.com/paypalme/' + h + (amount ? '/' + Number(amount) : '');
  }
  function donationPlanForAmount(tiers, amount) {
    const sorted = (tiers || []).slice().sort((a, b) => Number(a.price_usd || 0) - Number(b.price_usd || 0));
    if (!sorted.length) return null;
    let pick = sorted[0];
    const n = Number(amount || 0);
    for (const t of sorted) {
      if (n >= Number(t.price_usd || 0)) pick = t;
    }
    return pick;
  }
  function planCardHtml(p, catalog, opts) {
    const feats = p.features || {};
    const donation = p.category === 'donation';
    const rows = (catalog || []).map(f => {
      if (opts.isOwner && p.plan_id !== 'founder') {
        return `<div class="feat-row"><span>${esc(f.label)}${f.hint ? ` <span class="cab-sub">(${esc(f.hint)})</span>` : ''}</span><label class="switch"><input type="checkbox" data-plan-toggle="${esc(p.plan_id)}" data-plan-feat="${esc(f.id)}" ${feats[f.id] ? 'checked' : ''}><span class="sl"></span></label></div>`;
      }
      return `<div class="feat-row"><span>${esc(f.label)}</span><span class="feat-mark ${feats[f.id] ? 'on' : 'off'}">${feats[f.id] ? '✓' : '—'}</span></div>`;
    }).join('');
    let action = '';
    if (!opts.isOwner) {
      if (opts.current) {
        action = '<span class="badge live">Ваш тариф</span>';
      } else if (donation) {
        // Donations stay available even while automatic subscriptions are in development.
        const url = opts.paypal ? paypalFor(opts.paypal, p.price_usd) : '';
        action = url
          ? `<a class="btn primary" href="${esc(url)}" data-external target="_blank" rel="noopener">Поддержать ${planPriceLabel(p)}</a>`
          : `<span class="cab-sub">Реквизиты владельца не заданы</span>`;
      } else if (!opts.paymentsEnabled || opts.subscriptionsSoon) {
        action = '<span class="plan-soon">В разработке</span>';
      } else {
        action = `<button class="btn primary" data-choose-plan="${esc(p.plan_id)}">Выбрать</button>`;
      }
    }
    return `<div class="plan-card ${donation ? 'donation' : ''} ${opts.current ? 'current' : ''}${opts.subscriptionsSoon && !donation ? ' soon' : ''}">
      <div class="plan-head"><div class="plan-name">${esc(p.label)}${p.badge ? ` <span class="badge trial">${esc(p.badge)}</span>` : ''}</div><div class="plan-price">${planPriceLabel(p)}</div></div>
      <div class="plan-tag">${esc(p.tagline || '')}</div>
      <div class="plan-feats">${rows}</div>
      <div class="plan-action">${action}</div></div>`;
  }
  function renderCheckoutPanel(node, out) {
    if (!node || !out) return;
    const amount = out.amount_usd ? ('$' + Number(out.amount_usd).toFixed(2).replace(/\.00$/, '')) : '';
    const payUrl = out.paypal_url || out.card_url || '';
    node.innerHTML = `<div class="cab-card checkout-card"><h4>Оплата тарифа «${esc(out.label || out.plan_id)}» ${amount}</h4>
      <div class="finance-note" style="white-space:pre-line">${esc(out.instructions || '')}</div>
      <div class="dchart-actions" style="justify-content:flex-start">
        ${payUrl ? `<a class="btn primary" href="${esc(payUrl)}" data-external target="_blank" rel="noopener">Оплатить ${amount} через PayPal</a>` : '<span class="cab-sub">Владелец ещё не указал реквизиты PayPal — попросите ссылку или промокод.</span>'}
        <button class="btn ghost" id="checkout-paid" data-plan="${esc(out.plan_id)}">Я оплатил — сообщить владельцу</button>
      </div>
      <div class="cab-sub" id="checkout-msg"></div></div>`;
    bindExternalLinks(node);
    const paid = qs('#checkout-paid', node);
    if (paid) paid.onclick = async () => {
      paid.disabled = true;
      try {
        await API.http.billingPaymentRequest(paid.dataset.plan);
        const m = qs('#checkout-msg', node);
        if (m) m.textContent = 'Заявка отправлена владельцу. Тариф включат после проверки платежа в PayPal.';
        toast('Заявка отправлена владельцу');
      } catch (e) { reportError(e); paid.disabled = false; }
    };
    try { node.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); } catch (e) { /* ignore */ }
  }
  // Two audiences, one endpoint. `scope` decides which: a member sees what
  // they hold and how to get more, an operator edits what a plan grants.
  // Deciding what a plan grants is an administrative act, so it belongs in
  // Admin -- an owner opening their own cabinet should see their account, not
  // the switchboard for everyone's.
  async function renderPlansInto(node, me, scope) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка тарифов…</div>';
    try {
      const isOwner = scope === 'admin' && !!(me && me.is_owner);
      if (scope === 'admin' && !isOwner) {
        node.innerHTML = `<div class="finance-note">Управление привилегиями тарифов доступно только владельцу.</div>`;
        return;
      }
      // One self-service endpoint for everyone. /api/owner/plans returns the
      // same list behind an owner gate, so the branch bought nothing and put an
      // owner-scoped call in a personal surface. Subscription *management*
      // lives in the Admin panel and is unaffected.
      const data = await API.http.billingPlans();
      let donate = { payment: {}, tiers: [] };
      try { donate = await API.http.billingDonate(); } catch (e) { /* optional */ }
      const catalog = data.feature_catalog || [];
      const plans = (data.plans || data.public_plans || []).filter(p => p.public);
      const subs = plans.filter(p => p.category === 'subscription');
      const donations = plans.filter(p => p.category === 'donation');
      const tiers = (donate.tiers && donate.tiers.length)
        ? donate.tiers
        : donations.map(p => ({
            plan_id: p.plan_id, label: p.label, badge: p.badge, tagline: p.tagline,
            price_usd: p.price_usd, paypal_url: '', features: p.features,
          }));
      const currentPlan = (me && me.subscription && me.subscription.plan_id) || '';
      const paypal = (donate.payment || {}).paypal_me || '';
      const paymentsEnabled = !!(me && me.payments_enabled);
      // Automatic subscription checkout stays secondary until payments are live.
      const subscriptionsSoon = !paymentsEnabled;
      const ref = getReferral();

      if (isOwner) {
        node.innerHTML = '<div class="finance-note">Переключатели включают/выключают привилегию для тарифа. Разница между тарифами видна по колонкам ниже.</div>'
          + `<div class="section-title">Подписки</div><div class="plan-grid">${subs.map(p => planCardHtml(p, catalog, { isOwner, current: p.plan_id === currentPlan, paypal, paymentsEnabled, subscriptionsSoon: false })).join('')}</div>`
          + `<div class="section-title">Донат — для своих</div><div class="plan-grid">${donations.map(p => planCardHtml(p, catalog, { isOwner, current: p.plan_id === currentPlan, paypal, paymentsEnabled, subscriptionsSoon: false })).join('')}</div>`;
        qsa('[data-plan-toggle]', node).forEach(t => t.onchange = async () => { t.disabled = true; try { await API.http.ownerPlanFeature(t.dataset.planToggle, t.dataset.planFeat, t.checked); toast('Привилегия тарифа обновлена'); } catch (e) { t.checked = !t.checked; reportError(e); } finally { t.disabled = false; } });
        return;
      }

      const tierBtns = tiers.map(t => {
        const amount = Number(t.price_usd || 0);
        const label = amount ? ('$' + String(amount).replace(/\.0$/, '')) : esc(t.label || t.plan_id);
        const url = t.paypal_url || (paypal ? paypalFor(paypal, amount) : '');
        return `<button type="button" class="btn ${url ? 'primary' : 'ghost'}" data-donate-tier="${esc(t.plan_id)}" data-donate-amount="${esc(String(amount))}" data-donate-url="${esc(url)}" ${url ? '' : 'disabled'}>${label}</button>`;
      }).join('');

      const accessBlock = `<div class="cab-card access-primary">
        <h4>Введите промокод или отблагодарите</h4>
        <p class="cab-sub">Основной способ получить доступ сейчас — промокод от разработчиков или донат с запросом доступа. Автоматическая подписка ещё в разработке.</p>
        <div class="access-promo">
          <label class="cab-sub">Промокод</label>
          <div class="flex gap-sm"><input id="cab-promo" placeholder="Код приглашения" value="${esc(ref)}" style="flex:1"><button class="btn primary" id="cab-promo-apply">Активировать</button></div>
          <div class="cab-sub" id="cab-promo-msg">${ref ? 'Найдено приглашение — нажмите «Активировать».' : ''}</div>
        </div>
        <div class="access-donate" style="margin-top:16px">
          <label class="cab-sub">Отблагодарить</label>
          <div class="flex gap-sm" style="flex-wrap:wrap;margin-top:8px">${tierBtns || '<span class="cab-sub">Суммы доната пока не настроены.</span>'}</div>
          <div class="flex gap-sm" style="margin-top:10px;flex-wrap:wrap;align-items:center">
            <input id="cab-donate-custom" type="number" min="1" step="1" placeholder="Своя сумма, $" style="width:140px">
            <button type="button" class="btn ghost" id="cab-donate-custom-go" ${paypal ? '' : 'disabled'}>PayPal</button>
          </div>
          <p class="cab-sub" style="margin-top:14px">Сначала завершите оплату в PayPal, затем отправьте заявку. Владелец вручную сверит платёж и откроет тариф.</p>
          <div class="dchart-actions" style="justify-content:flex-start;margin-top:10px">
            <button type="button" class="btn ghost" id="cab-donate-paid" ${paypal ? '' : 'disabled'}>Я поддержал — запросить доступ</button>
          </div>
          ${paypal ? '' : '<div class="cab-sub">PayPal владельца ещё не настроен, поэтому запрос доступа после доната сейчас недоступен.</div>'}
          <div class="cab-sub" id="cab-donate-msg"></div>
        </div>
      </div>`;

      node.innerHTML = accessBlock
        + '<div id="cab-checkout"></div>'
        + `<div class="section-title" style="margin-top:18px">Автоматическая подписка · в разработке</div>`
        + `<div class="finance-note">Онлайн-оплата подписок подключается позже. Карточки ниже — для ознакомления с будущими тарифами.</div>`
        + `<div class="plan-grid">${subs.map(p => planCardHtml(p, catalog, { isOwner: false, current: p.plan_id === currentPlan, paypal, paymentsEnabled, subscriptionsSoon: true })).join('')}</div>`;

      bindExternalLinks(node);

      const setDonateMsg = (text) => { const m = qs('#cab-donate-msg', node); if (m) m.textContent = text || ''; };
      const openPay = (url) => { if (url) try { window.open(url, '_blank', 'noopener'); } catch (e) { location.href = url; } };
      const requestAccess = async (planId, amount, btn) => {
        if (!planId) { toast('Не удалось определить тариф доната'); return; }
        if (btn) btn.disabled = true;
        try {
          const note = amount ? (`Донат $${Number(amount)} через PayPal`) : 'Донат через PayPal';
          await API.http.billingPaymentRequest(planId, note);
          setDonateMsg('Заявка отправлена владельцу. Доступ включат после проверки платежа в PayPal.');
          toast('Заявка на доступ отправлена');
        } catch (e) { reportError(e); }
        finally { if (btn) btn.disabled = false; }
      };

      qsa('[data-donate-tier]', node).forEach(b => b.onclick = async () => {
        const url = b.dataset.donateUrl || '';
        if (!url) { toast('PayPal владельца ещё не настроен'); return; }
        openPay(url);
        setDonateMsg('Откройте PayPal и завершите оплату. Затем вернитесь сюда и нажмите «Я поддержал — запросить доступ».');
      });

      const customGo = qs('#cab-donate-custom-go', node);
      if (customGo) customGo.onclick = async () => {
        const raw = Number((qs('#cab-donate-custom', node) || {}).value || 0);
        if (!(raw >= 1)) { toast('Укажите сумму от $1'); return; }
        const amount = Math.round(raw * 100) / 100;
        const url = paypal ? paypalFor(paypal, amount) : '';
        if (!url) { toast('PayPal владельца ещё не настроен'); return; }
        openPay(url);
        setDonateMsg('Откройте PayPal и завершите оплату. Затем вернитесь сюда и нажмите «Я поддержал — запросить доступ».');
      };

      const paidBtn = qs('#cab-donate-paid', node);
      if (paidBtn) paidBtn.onclick = async () => {
        if (!paypal) { toast('PayPal владельца ещё не настроен'); return; }
        const customRaw = Number((qs('#cab-donate-custom', node) || {}).value || 0);
        let tier = null;
        let amount = 0;
        if (customRaw >= 1) {
          amount = Math.round(customRaw * 100) / 100;
          tier = donationPlanForAmount(tiers, amount);
        } else {
          tier = tiers[0] || null;
          amount = tier ? Number(tier.price_usd || 0) : 0;
        }
        if (!tier) { toast('Нет доступных уровней доната'); return; }
        await requestAccess(tier.plan_id, amount, paidBtn);
      };

      qsa('[data-choose-plan]', node).forEach(b => b.onclick = async () => {
        const pid = b.dataset.choosePlan;
        b.disabled = true;
        try {
          const out = await API.http.billingCheckout(pid);
          renderCheckoutPanel(qs('#cab-checkout', node), out);
        } catch (e) { reportError(e); }
        finally { b.disabled = false; }
      });

      const applyBtn = qs('#cab-promo-apply', node);
      if (applyBtn) applyBtn.onclick = async () => {
        const code = (qs('#cab-promo', node).value || '').trim();
        if (!code) { toast('Введите код'); return; }
        applyBtn.disabled = true;
        const msg = qs('#cab-promo-msg', node);
        try {
          const out = await API.http.billingPromoRedeem({ code });
          if (out && out.checkout_required) { if (msg) msg.textContent = 'Для этого кода нужна оплата тарифа.'; }
          else { clearReferral(); toast('Доступ активирован'); setTimeout(() => location.reload(), 700); }
        } catch (e) { reportError(e); } finally { applyBtn.disabled = false; }
      };
    } catch (e) { renderError(node, e, () => renderPlansInto(node, me, scope)); }
  }

  function buildPlanOptions(plans) {
    const order = ['developer_free', 'basic', 'standard', 'pro', 'donate_5', 'donate_3', 'donate_1', 'learner_viewer'];
    const byId = {}; (plans || []).forEach(p => { byId[p.plan_id] = p; });
    return order.filter(id => byId[id]).map(id => { const p = byId[id]; return `<option value="${esc(id)}">${esc(p.label)}${p.price_usd ? ' · ' + planPriceLabel(p) : ' · бесплатно'}</option>`; }).join('');
  }
  function voucherRowHtml(v) {
    const isActive = v.status === 'active';
    const actions = `<div class="flex gap-sm wrap inv-actions">
      ${isActive ? `<button class="btn sm ghost" data-inv-status="${esc(v.voucher_id)}" data-inv-to="paused">Отменить</button>` : `<button class="btn sm ghost" data-inv-status="${esc(v.voucher_id)}" data-inv-to="active">Возобновить</button>`}
      <button class="btn sm ghost" data-inv-status="${esc(v.voucher_id)}" data-inv-to="archived">В архив</button>
      <button class="btn sm danger" data-inv-del="${esc(v.voucher_id)}">Удалить</button>
    </div>`;
    const badge = v.status === 'active' ? 'live' : v.status === 'paused' ? 'pending' : 'archived';
    const reds = v.redemptions || [];
    const redLine = reds.length
      ? `<div class="inv-redeemers"><span class="cab-sub">Использовали:</span> ${reds.map(r => `<button class="btn sm ghost" data-open-user="${esc(r.user_id)}" ${r.user_exists ? '' : 'disabled'} title="Открыть аккаунт">${esc(r.user_label || ('ID ' + r.user_id))}${r.redeemed_at_utc ? ' · ' + esc(shortDt(r.redeemed_at_utc)) : ''}</button>`).join(' ')}</div>`
      : '';
    return `<div class="inv-wrap"><div class="row inv-row"><div class="row-main"><div class="row-title">${esc(v.label || v.voucher_id)}</div><div class="row-sub">${esc(v.grant_plan_id || 'скидка')} · ${Number(v.discount_percent || 0)}% · использовано ${Number(v.used_count || 0)}/${Number(v.usage_limit || 0)}</div></div><span class="badge ${badge}">${esc(v.status || '—')}</span>${actions}</div>${redLine}</div>`;
  }
  function renderInviteResult(node, out) {
    if (!node) return;
    const code = (out.voucher || {}).code || '';
    const inv = out.invite || {};
    const render = out.render || {};
    const link = inv.telegram || inv.web || '';
    const cardImg = render.image_data_url ? `<div class="invite-card-preview"><img src="${esc(render.image_data_url)}" alt="Приглашение"></div>` : '';
    const sendBtn = render.image_data_url || render.text ? `<button class="btn primary" id="inv-send">Отправить себе в Telegram</button>` : '';
    node.innerHTML = `<div class="invite-result">
      ${cardImg}
      <div class="cab-kv"><span class="k">Промокод</span><span class="v mono"><strong>${esc(code)}</strong> <button class="btn sm ghost" data-copy="${esc(code)}">Копировать</button></span></div>
      ${inv.telegram ? `<div class="cab-kv"><span class="k">Ссылка Telegram</span><span class="v"><a href="${esc(inv.telegram)}" target="_blank" rel="noopener">${esc(inv.telegram)}</a> <button class="btn sm ghost" data-copy="${esc(inv.telegram)}">Копировать</button></span></div>` : ''}
      ${inv.web ? `<div class="cab-kv"><span class="k">Ссылка Web</span><span class="v"><a href="${esc(inv.web)}" target="_blank" rel="noopener">${esc(inv.web)}</a> <button class="btn sm ghost" data-copy="${esc(inv.web)}">Копировать</button></span></div>` : ''}
      ${render.text ? `<div class="cab-kv"><span class="k">Текст</span><span class="v"><button class="btn sm ghost" data-copy="${esc(render.text)}">Копировать текст</button></span></div>` : (inv.message ? `<div class="cab-kv"><span class="k">Текст</span><span class="v"><button class="btn sm ghost" data-copy="${esc(inv.message)}">Копировать приглашение</button></span></div>` : '')}
      <div class="dchart-actions" style="justify-content:flex-start">${sendBtn}${render.image_data_url ? `<a class="btn ghost" href="${esc(render.image_data_url)}" download="invite.png">Скачать картинку</a>` : ''}</div>
      ${(!inv.telegram && !inv.web) ? '<div class="cab-sub">Ссылка появится после настройки бота или web URL. Промокод уже работает.</div>' : ''}</div>`;
    qsa('[data-copy]', node).forEach(b => b.onclick = () => { try { navigator.clipboard.writeText(b.dataset.copy); toast('Скопировано'); } catch (e) { reportError(e); } });
    const send = qs('#inv-send', node);
    if (send) send.onclick = async () => {
      send.disabled = true;
      try {
        const r = await API.http.ownerInviteSend({ text: render.text || inv.message || '', image_data_url: render.image_data_url || '' });
        toast(r && r.ok ? 'Отправлено в ваш Telegram — можно переслать' : 'Не удалось отправить');
      } catch (e) { reportError(e); } finally { send.disabled = false; }
    };
  }
  async function renderInvitesInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>';
    try {
      const [plansData, vouchersData] = await withDeadline(Promise.all([API.http.billingPlans(), API.http.ownerVouchers()]), 'Приглашения');
      const opts = buildPlanOptions(plansData.plans || []);
      const vouchers = vouchersData.vouchers || [];
      node.innerHTML = `<div class="cab-card"><h4>Пригласить пользователя</h4>
        <div class="finance-note">Создаётся промокод и красивая ссылка-приглашение. Пользователь переходит по ссылке, входит через Telegram и получает выбранный уровень доступа.</div>
        <form class="dchart-form" id="inv-form"><div class="fgrid">
          <label>Название<input id="inv-label" value="Приглашение"></label>
          <label>Тариф доступа<select id="inv-plan">${opts}</select></label>
          <label>Скидка %, если платный<input id="inv-discount" type="number" min="0" max="100" value="0"></label>
          <label>Сколько людей<input id="inv-limit" type="number" min="1" max="100000" value="1"></label>
          <label>Срок дней (0=бессрочно)<input id="inv-days" type="number" min="0" max="3650" value="0"></label>
          <label>Префикс кода<input id="inv-prefix" value="REF"></label>
        </div><div class="dchart-actions"><button class="btn primary" type="submit">Создать приглашение</button></div></form>
        <div id="inv-result"></div></div>
        <div class="cab-card"><h4>Выданные приглашения</h4><div class="list account-user-list">${vouchers.map(voucherRowHtml).join('') || '<div class="empty-state">Пока нет.</div>'}</div></div>`;
      const form = qs('#inv-form', node);
      form.onsubmit = async (e) => {
        e.preventDefault();
        const btn = form.querySelector('button[type="submit"]');
        btn.disabled = true;
        try {
          const out = await API.http.ownerInviteCreate({
            label: qs('#inv-label', form).value,
            grant_plan_id: qs('#inv-plan', form).value,
            discount_percent: Number(qs('#inv-discount', form).value || 0),
            usage_limit: Number(qs('#inv-limit', form).value || 1),
            grant_duration_days: Number(qs('#inv-days', form).value || 0),
            code_prefix: qs('#inv-prefix', form).value,
          });
          renderInviteResult(qs('#inv-result', node), out);
          toast('Приглашение создано');
        } catch (err) { reportError(err); } finally { btn.disabled = false; }
      };
      qsa('[data-inv-status]', node).forEach(b => b.onclick = async () => { b.disabled = true; try { await API.http.ownerInviteStatus(b.dataset.invStatus, b.dataset.invTo); toast('Приглашение обновлено'); await renderInvitesInto(node); } catch (e) { reportError(e); b.disabled = false; } });
      qsa('[data-inv-del]', node).forEach(b => b.onclick = async () => { if (!confirm('Удалить приглашение навсегда?')) return; b.disabled = true; try { await API.http.ownerInviteDelete(b.dataset.invDel); toast('Приглашение удалено'); await renderInvitesInto(node); } catch (e) { reportError(e); b.disabled = false; } });
      qsa('[data-open-user]', node).forEach(b => b.onclick = () => { PENDING_USER_DETAIL = b.dataset.openUser; openAdminPanel('users'); });
    } catch (e) { renderError(node, e, () => renderInvitesInto(node)); }
  }

  async function renderPaymentInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>';
    try {
      const [data, pp] = await Promise.all([API.http.ownerPaymentGet(), API.http.ownerPaypalGet().catch(() => ({ paypal: {} }))]);
      const p = data.payment || {};
      const pay = pp.paypal || {};
      const webhookUrl = location.origin + '/api/billing/paypal/webhook';
      const planIds = pay.plans || {};
      const previewMe = p.paypal_me ? ('https://www.paypal.com/paypalme/' + String(p.paypal_me).replace(/[^A-Za-z0-9_.\-]/g, '')) : '';
      node.innerHTML = `<div class="cab-card"><h4>PayPal — ручная оплата</h4>
        <div class="finance-note">Пользователь платит по вашей ссылке PayPal.me как разовый перевод/поддержку, затем нажимает «Я оплатил». Вы проверяете платёж в PayPal и включаете тариф во вкладке <strong>Заявки</strong> или прямо у пользователя. Карты и автосписания не используются.</div>
        <form class="dchart-form" id="pm-form"><div class="fgrid">
          <label>PayPal.me (ваш ник)<input id="pm-paypalme" value="${esc(p.paypal_me || '')}" placeholder="myhandle"></label>
          <label>Готовая платёжная ссылка (необязательно)<input id="pm-cardurl" value="${esc(p.card_url || '')}" placeholder="https://paypal.com/ncp/payment/..."></label>
          <label>Примечание к оплате<input id="pm-cardnote" value="${esc(p.card_note || '')}" placeholder="Напишите мне в Telegram после оплаты"></label>
        </div>
        <label class="drawing-lock"><input type="checkbox" id="pm-enabled" ${p.enabled !== false ? 'checked' : ''}><span>Показывать оплату и кнопки тарифов пользователям</span></label>
        <div class="dchart-actions"><button class="btn primary" type="submit">Сохранить</button></div></form>
        ${previewMe ? `<div class="cab-kv"><span class="k">Ссылка PayPal.me</span><span class="v mono nt-path"><a href="${esc(previewMe)}" target="_blank" rel="noopener">${esc(previewMe)}</a></span></div>` : ''}
      </div>
      <details class="cab-card"><summary><strong>Автоматические подписки PayPal (на будущее)</strong></summary>
        <div class="finance-note">Не обязательно сейчас. Требует PayPal Business и публичный webhook. Заполните, когда захотите включить автосписание тарифов — ручная схема выше продолжит работать.</div>
        <form class="dchart-form" id="pp-form"><div class="fgrid">
          <label>Режим<select id="pp-mode"><option value="sandbox" ${pay.mode !== 'live' ? 'selected' : ''}>Sandbox (тест)</option><option value="live" ${pay.mode === 'live' ? 'selected' : ''}>Live (боевой)</option></select></label>
          <label>Client ID<input id="pp-client" value="${esc(pay.client_id || '')}" placeholder="PayPal REST client id"></label>
          <label>Secret ${pay.secret_set ? '(задан)' : ''}<input id="pp-secret" type="password" placeholder="${pay.secret_set ? '•••••• оставьте пустым, чтобы не менять' : 'PayPal REST secret'}"></label>
          <label>Webhook ID<input id="pp-webhook" value="${esc(pay.webhook_id || '')}" placeholder="ID webhook из PayPal"></label>
        </div>
        <label class="drawing-lock"><input type="checkbox" id="pp-enabled" ${pay.enabled ? 'checked' : ''}><span>Включить автоматические подписки PayPal</span></label>
        <div class="dchart-actions"><button class="btn primary" type="submit">Сохранить автоподписки</button><button class="btn ghost" type="button" id="pp-plans">Создать планы Basic/Standard/Pro в PayPal</button></div></form>
        <div class="cab-kv"><span class="k">Webhook URL для PayPal</span><span class="v mono nt-path">${esc(webhookUrl)} <button class="btn sm ghost" data-copy-pp="${esc(webhookUrl)}">Копировать</button></span></div>
        <div class="cab-kv"><span class="k">Продукт</span><span class="v mono">${esc(pay.product_id || '—')}</span></div>
        <div class="cab-kv"><span class="k">Планы</span><span class="v mono">Basic: ${esc(planIds.basic || '—')} · Standard: ${esc(planIds.standard || '—')} · Pro: ${esc(planIds.pro || '—')}</span></div>
      </details>`;
      qsa('[data-copy-pp]', node).forEach(b => b.onclick = () => { try { navigator.clipboard.writeText(b.dataset.copyPp); toast('Скопировано'); } catch (e) { reportError(e); } });
      const manual = qs('#pm-form', node);
      manual.onsubmit = async (e) => {
        e.preventDefault();
        const btn = manual.querySelector('button[type="submit"]');
        btn.disabled = true;
        try {
          await API.http.ownerPaymentSet({
            paypal_me: qs('#pm-paypalme', manual).value,
            card_url: qs('#pm-cardurl', manual).value,
            card_note: qs('#pm-cardnote', manual).value,
            enabled: qs('#pm-enabled', manual).checked,
          });
          toast('Реквизиты сохранены');
          await renderPaymentInto(node);
        } catch (err) { reportError(err); btn.disabled = false; }
      };
      const form = qs('#pp-form', node);
      form.onsubmit = async (e) => {
        e.preventDefault();
        const btn = form.querySelector('button[type="submit"]');
        btn.disabled = true;
        try {
          await API.http.ownerPaypalSet({
            mode: qs('#pp-mode', form).value,
            client_id: qs('#pp-client', form).value,
            secret: qs('#pp-secret', form).value,
            webhook_id: qs('#pp-webhook', form).value,
            enabled: qs('#pp-enabled', form).checked,
          });
          toast('Настройки автоподписок сохранены');
          await renderPaymentInto(node);
        } catch (err) { reportError(err); btn.disabled = false; }
      };
      const plansBtn = qs('#pp-plans', node);
      if (plansBtn) plansBtn.onclick = async () => {
        plansBtn.disabled = true; plansBtn.textContent = 'Создаю в PayPal…';
        try { await API.http.ownerPaypalEnsurePlans(); toast('Планы PayPal созданы'); await renderPaymentInto(node); }
        catch (err) { reportError(err); plansBtn.disabled = false; plansBtn.textContent = 'Создать планы Basic/Standard/Pro в PayPal'; }
      };
    } catch (e) { renderError(node, e, () => renderPaymentInto(node)); }
  }

  function requestRowHtml(r) {
    const amount = r.amount_usd ? ('$' + Number(r.amount_usd).toFixed(2).replace(/\.00$/, '')) : '';
    const pending = r.status === 'pending';
    const who = r.user_label ? esc(r.user_label) : ('ID ' + esc(r.user_id));
    const controls = pending
      ? `<label class="req-days">срок дней<input type="number" data-req-days min="0" max="3650" value="30" style="width:64px"></label><button class="btn sm primary" data-req-approve="${esc(r.request_id)}">Включить</button><button class="btn sm danger" data-req-reject="${esc(r.request_id)}">Отклонить</button>`
      : `<span class="badge ${r.status === 'approved' ? 'live' : 'archived'}">${esc(r.status || '—')}</span>`;
    return `<div class="row" data-req><div class="row-main"><div class="row-title">${who} · ${esc(r.plan_label || r.plan_id)} ${amount}</div><div class="row-sub">${esc(r.created_at_utc || '')}${r.note ? ' · ' + esc(r.note) : ''}</div></div>${controls}</div>`;
  }
  async function renderRequestsInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>';
    try {
      const data = await withDeadline(API.http.ownerPaymentRequests(), 'Запросы доступа');
      const reqs = data.requests || [];
      const pending = reqs.filter(r => r.status === 'pending');
      const done = reqs.filter(r => r.status !== 'pending');
      node.innerHTML = `<div class="finance-note">Пользователь нажал «Я оплатил» — проверьте платёж в PayPal и включите тариф с нужным сроком. Заявки не списывают деньги и не хранят карты.</div>
        <div class="section-title">Новые заявки</div><div class="list account-user-list">${pending.map(requestRowHtml).join('') || '<div class="empty-state">Новых заявок нет.</div>'}</div>
        ${done.length ? `<div class="section-title">История</div><div class="list account-user-list">${done.map(requestRowHtml).join('')}</div>` : ''}`;
      qsa('[data-req-approve]', node).forEach(b => b.onclick = async () => {
        const wrap = b.closest('[data-req]');
        const days = Number(((wrap && qs('input[data-req-days]', wrap)) || {}).value || 30);
        b.disabled = true;
        try { await API.http.ownerPaymentRequestResolve(b.dataset.reqApprove, true, days); toast('Тариф включён'); await renderRequestsInto(node); }
        catch (e) { reportError(e); b.disabled = false; }
      });
      qsa('[data-req-reject]', node).forEach(b => b.onclick = async () => {
        b.disabled = true;
        try { await API.http.ownerPaymentRequestResolve(b.dataset.reqReject, false, 0); toast('Заявка отклонена'); await renderRequestsInto(node); }
        catch (e) { reportError(e); b.disabled = false; }
      });
    } catch (e) { renderError(node, e, () => renderRequestsInto(node)); }
  }

  let PENDING_USER_DETAIL = '';
  // Default to a week rather than to everything: "the last 300 events" is a
  // month on a quiet week and an hour on a busy day, so the same filter meant
  // two different things depending on when it was read.
  const JOURNAL_STATE = { category: '', q: '', suspicious: false, period: '7d' };
  function journalRowHtml(e) {
    // The time alone on the row; the date is carried by the day heading above
    // it. Repeating the full timestamp on every line is what made three hundred
    // rows read as an undifferentiated wall.
    const stamp = String(e.timestamp || '');
    const clock = stamp.includes('T') ? stamp.split('T')[1].slice(0, 5) : stamp.slice(0, 5);
    return `<div class="jrow ${e.suspicious ? 'jrow-warn' : ''}">
      <div class="jrow-time mono">${esc(clock)}</div>
      <div class="jrow-body">
        <div class="jrow-title">${esc(e.event || '—')}${
          e.suspicious ? ' <span class="badge pending">внимание</span>' : ''}</div>
        <div class="cab-sub"><span class="badge">${esc(e.category_label || e.category)}</span> ${esc(e.summary || '')}</div>
      </div>
    </div>`;
  }

  function journalTimelineHtml(entries) {
    if (!entries.length) return '<div class="empty-state">Записей нет.</div>';
    // Grouped by day, newest first, so a question like "what happened yesterday
    // evening" is answered by looking rather than by reading every timestamp.
    const days = [];
    const byDay = new Map();
    for (const entry of entries) {
      const day = String(entry.timestamp || '').slice(0, 10) || 'без даты';
      if (!byDay.has(day)) { byDay.set(day, []); days.push(day); }
      byDay.get(day).push(entry);
    }
    return `<div class="jtimeline">${days.map(day => {
      const rows = byDay.get(day);
      const flagged = rows.filter(r => r.suspicious).length;
      return `<section class="jday">
        <div class="jday-head">
          <span class="jday-date mono">${esc(day)}</span>
          <span class="cab-sub">${rows.length} ${flagged ? `· внимание: ${flagged}` : ''}</span>
        </div>
        <div class="jday-rows">${rows.map(journalRowHtml).join('')}</div>
      </section>`;
    }).join('')}</div>`;
  }
  async function renderJournalInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка журнала…</div>';
    try {
      const params = new URLSearchParams();
      if (JOURNAL_STATE.category) params.set('category', JOURNAL_STATE.category);
      if (JOURNAL_STATE.q) params.set('q', JOURNAL_STATE.q);
      if (JOURNAL_STATE.suspicious) params.set('suspicious', '1');
      if (JOURNAL_STATE.period) params.set('period', JOURNAL_STATE.period);
      params.set('limit', '300');
      const data = await withDeadline(API.http.ownerJournal(params.toString()), 'Журнал');
      const cats = data.categories || [];
      const entries = data.entries || [];
      node.innerHTML = `<div class="finance-note">Скрытый журнал администратора: регистрации, входы, изменения прав и подписок, ошибки и подозрительная активность. Только для владельца.</div>
        <div class="flex gap-sm wrap" style="align-items:flex-end;margin-bottom:8px">
          <label>Категория<select id="jr-cat"><option value="">Все</option>${cats.map(c => `<option value="${esc(c.id)}" ${c.id === JOURNAL_STATE.category ? 'selected' : ''}>${esc(c.label)}</option>`).join('')}</select></label>
          <label style="flex:1;min-width:160px">Поиск<input id="jr-q" value="${esc(JOURNAL_STATE.q)}" placeholder="событие, id, путь…"></label>
          <label>Период<select id="jr-period">${(data.periods || []).map(
            p => `<option value="${esc(p.id)}" ${p.id === JOURNAL_STATE.period ? 'selected' : ''}>${esc(p.label)}</option>`).join('')}</select></label>
          <label class="flex gap-sm" style="align-items:center">Только подозрительные<input type="checkbox" id="jr-sus" ${JOURNAL_STATE.suspicious ? 'checked' : ''}></label>
          <button class="btn ghost" id="jr-refresh">Обновить</button>
        </div>
        <div class="cab-sub">Показано записей: ${entries.length}${
          JOURNAL_STATE.category || JOURNAL_STATE.q || JOURNAL_STATE.suspicious
            ? ' (с учётом фильтров)' : ''}${data.truncated
            ? ' · список обрезан по лимиту — сузьте период или фильтр' : ''}</div>
        ${journalTimelineHtml(entries)}`;
      const apply = () => {
        JOURNAL_STATE.category = (qs('#jr-cat', node) || {}).value || '';
        JOURNAL_STATE.q = ((qs('#jr-q', node) || {}).value || '').trim();
        JOURNAL_STATE.suspicious = !!(qs('#jr-sus', node) || {}).checked;
        JOURNAL_STATE.period = (qs('#jr-period', node) || {}).value || 'all';
        renderJournalInto(node);
      };
      const cat = qs('#jr-cat', node); if (cat) cat.onchange = apply;
      const sus = qs('#jr-sus', node); if (sus) sus.onchange = apply;
      const per = qs('#jr-period', node); if (per) per.onchange = apply;
      const refresh = qs('#jr-refresh', node); if (refresh) refresh.onclick = apply;
      const qInput = qs('#jr-q', node); if (qInput) qInput.onkeydown = (e) => { if (e.key === 'Enter') apply(); };
    } catch (e) { renderError(node, e, () => renderJournalInto(node)); }
  }

  function wireCabinetHeader(body, me) {
    const btn = qs('#cab-avatar-refresh', body);
    if (!btn) return;
    btn.onclick = async () => {
      btn.disabled = true; btn.textContent = 'Обновляю…';
      try {
        const out = await API.http.authAvatarRefresh();
        if (out && out.ok && out.user) {
          if (CURRENT_AUTH) CURRENT_AUTH.user = out.user;
          applyChipUser(out.user);
          const head = qs('.cab-head', body);
          if (head) { head.outerHTML = cabinetHeader(Object.assign({}, me, { user: out.user })); wireCabinetHeader(body, me); }
          toast('Фото обновлено');
        } else { toast('Фото профиля в Telegram не найдено'); }
      } catch (e) { reportError(e); }
      finally { const again = qs('#cab-avatar-refresh', body); if (again) { again.disabled = false; again.textContent = 'Обновить фото'; } }
    };
  }
  function renderProfileInto(cb, me) {
    cb.innerHTML = cabinetProfile(me);
    const nt = qs('#cab-nt', cb);
    if (nt) renderNinjaInto(nt, me);
    qsa('[data-set-ux]', cb).forEach(btn => {
      btn.onclick = async () => {
        const mode = btn.dataset.setUx;
        const msg = qs('#cab-ux-msg', cb);
        if (mode === 'beginner') {
          const ok = confirm('Перейти в режим «Студент»? Стратегии, ИИ и NinjaTrader будут скрыты; Community останется доступным.');
          if (!ok) return;
        } else if (mode === 'professional') {
          const ok = confirm('Перейти в режим «Профессионал»? Откроются разделы по вашему тарифу (стратегии, ИИ, NT и др.).');
          if (!ok) return;
        }
        btn.disabled = true;
        if (msg) msg.textContent = 'Сохраняю…';
        try {
          const out = await API.http.authUxMode({
            ux_mode: mode,
            confirm_downgrade: mode === 'beginner',
          });
          CURRENT_AUTH = Object.assign({}, CURRENT_AUTH, out, {
            user: out.user || CURRENT_AUTH.user,
            features: out.features,
            capabilities: out.capabilities,
            locked_nav: out.locked_nav,
            ux_mode: out.ux_mode || mode,
          });
          applyNavAccess(CURRENT_AUTH);
          toast(mode === 'beginner' ? 'Режим «Студент»' : 'Режим «Профессионал»');
          if (mode === 'beginner') {
            closeDrawer();
            if (maybeRedirectBeginnerHome(CURRENT_AUTH.user || {})) return;
            location.reload();
            return;
          }
          openCabinet('profile');
        } catch (e) {
          if (msg) msg.textContent = e.message || String(e);
          reportError(e);
          btn.disabled = false;
        }
      };
    });
  }
  const SEC_DEVICE_ICONS = { phone: '📱', tablet: '📲', desktop: '🖥️', browser: '🌐', connector: '🔌' };
  const SEC_DEVICE_TYPE_LABEL = {
    phone: 'Телефон', tablet: 'Планшет', desktop: 'Компьютер',
    browser: 'Браузер', connector: 'Коннектор NinjaTrader',
  };
  const SEC_STATUS = {
    pending: ['pending', 'Ожидает подтверждения'],
    trusted: ['live', 'Доверенное'],
    revoked: ['failed', 'Отозвано'],
    expired: ['archived', 'Истекло'],
  };
  const SEC_PROVIDER_LABEL = { telegram: 'Telegram', email: 'e-mail', google: 'Google' };

  // Relative-time label for an ISO/UTC string, with an absolute title on hover.
  function secWhen(iso) {
    if (!iso) return '—';
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return esc(String(iso));
    const min = Math.round((Date.now() - t) / 60000);
    let rel;
    if (min < 0) rel = 'только что';
    else if (min < 1) rel = 'только что';
    else if (min < 60) rel = `${min} мин назад`;
    else if (min < 1440) rel = `${Math.floor(min / 60)} ч назад`;
    else rel = `${Math.floor(min / 1440)} дн назад`;
    let abs = iso;
    try { abs = new Date(t).toLocaleString(); } catch (_) { /* keep iso */ }
    return `<span title="${esc(abs)}">${esc(rel)}</span>`;
  }

  function securityDeviceRow(device) {
    const type = String(device.device_type || 'browser');
    const icon = SEC_DEVICE_ICONS[type] || '🌐';
    const typeLabel = SEC_DEVICE_TYPE_LABEL[type] || 'Устройство';
    const [badgeCls, statusLabel] = SEC_STATUS[device.status] || ['archived', device.status];
    const online = !!device.online;
    const onlineDot = `<span class="dev-online ${online ? 'on' : 'off'}" title="${online ? 'Есть активная сессия' : 'Нет активной сессии'}">${online ? '● в сети' : '○ не в сети'}</span>`;
    const os = device.os_family
      ? (device.os_version ? device.os_family + ' ' + device.os_version : device.os_family) : '';
    // A Connector shows its own client/app; browsers/computers show the client label.
    const clientLabel = type === 'connector' ? 'Приложение' : 'Браузер / приложение';
    const kv = [];
    if (os) kv.push([type === 'connector' ? 'Хост-ОС' : 'ОС', os]);
    if (device.client) kv.push([clientLabel, device.client]);
    if (device.app_version) kv.push(['Версия', device.app_version]);
    kv.push(['Первый вход', device.first_seen_at_utc ? secWhen(device.first_seen_at_utc) : '—', true]);
    kv.push(['Последняя активность', device.last_seen_at_utc ? secWhen(device.last_seen_at_utc) : '—', true]);
    if (device.confirmation_provider) {
      kv.push(['Подтверждено через', SEC_PROVIDER_LABEL[device.confirmation_provider] || device.confirmation_provider]);
    }
    const kvHtml = kv.map(([k, v, raw]) =>
      `<div class="dev-kv-item"><span class="k">${esc(k)}</span><span class="v">${raw ? v : esc(String(v))}</span></div>`).join('');
    // Details drawer: internal, non-tracking identifiers only (no hardware id).
    const detailRows = [
      ['Внутренний ID устройства', device.device_id || '—'],
      type === 'connector' && device.connector_installation_id
        ? ['ID установки Connector', device.connector_installation_id] : null,
      device.last_region ? ['Последний регион (маскирован)', device.last_region] : null,
      device.last_auth_at_utc ? ['Последний вход', device.last_auth_at_utc] : null,
      device.expires_at_utc ? ['Доверие истекает', device.expires_at_utc] : null,
      device.revoked_at_utc ? ['Отозвано', device.revoked_at_utc] : null,
    ].filter(Boolean);
    const detailsHtml = detailRows.map(([k, v]) =>
      `<div class="dev-detail-item"><span class="k">${esc(k)}</span><span class="v mono">${esc(String(v))}</span></div>`).join('');
    let actions = `<button class="btn sm ghost" data-sec-details="${esc(device.device_id)}">Подробнее</button>`;
    if (device.status === 'pending') {
      actions += `<button class="btn sm primary" data-sec-approve="${esc(device.device_id)}">Подтвердить</button>
                 <button class="btn sm ghost" data-sec-reject="${esc(device.device_id)}">Отклонить</button>`;
    } else if (device.status === 'trusted') {
      actions += `<button class="btn sm ghost" data-sec-revoke="${esc(device.device_id)}">Отозвать</button>`;
    }
    return `<div class="device-card dev-${esc(type)}" data-device-card="${esc(device.device_id)}">
      <div class="device-card-head">
        <span class="dev-ic">${icon}</span>
        <div class="dev-headmain">
          <div class="dev-name">${esc(device.display_name || 'Устройство')} ${onlineDot}</div>
          <div class="dev-type">${esc(typeLabel)}${os ? ' · ' + esc(os) : ''}</div>
        </div>
        <span class="badge ${badgeCls}">${esc(statusLabel)}</span>
      </div>
      <div class="device-kv">${kvHtml}</div>
      <div class="device-actions">${actions}</div>
      <div class="device-details" data-device-details="${esc(device.device_id)}" hidden>${detailsHtml}</div>
    </div>`;
  }

  // ---- Canonical user card (Phase 5) ----------------------------------------
  //
  // One renderer for the Cabinet and for the Admin user page, fed by one server
  // builder. Two renderers over the same facts drift the same way two builders
  // would: a device revoked in one view still looks live in the other, and
  // nothing says which is wrong. `card.scope` is the server's word for how much
  // detail it returned; the renderer shows what is present and never guesses.
  const CARD_STATE_LABEL = {
    trusted: 'доверено', pending: 'ожидает подтверждения',
    revoked: 'отозвано', expired: 'истекло',
  };
  const CARD_STATE_CLASS = {
    trusted: 'live', pending: 'pending', revoked: 'failed', expired: 'archived',
  };
  const CARD_IDENTITY_LABEL = {
    telegram: 'Telegram', google: 'Google', email: 'E-mail', phone: 'Телефон',
  };
  const CARD_ATTENTION = {
    no_verified_identity: 'Нет подтверждённого способа входа',
    single_recovery_channel: 'Только один способ восстановить доступ',
    devices_awaiting_confirmation: 'Есть устройства, ожидающие подтверждения',
  };
  const CARD_TIMELINE_ICON = {
    login: '→', session: '×', identity: '@', device: '▢', machine: '▣', admin: '!',
  };

  function cardBadge(status) {
    const key = String(status || '');
    return `<span class="badge ${CARD_STATE_CLASS[key] || 'archived'}">${esc(CARD_STATE_LABEL[key] || key)}</span>`;
  }

  function cardWhen(value) {
    const text = String(value || '');
    return text ? esc(text.replace('T', ' ').replace('Z', '')) : '—';
  }

  function cardSummaryHtml(card) {
    const s = card.summary || {};
    const sec = s.security || {};
    const attention = (sec.attention || []).map(
      code => `<div>⚠ ${esc(CARD_ATTENTION[code] || code)}</div>`).join('');
    // Counts, not a score. "Two devices awaiting confirmation" is actionable;
    // a single number invites belief in a precision that is not there.
    const counts = [
      ['Подтверждённые идентификаторы', sec.verified_identities],
      ['Доверенные клиенты', sec.trusted_devices],
      ['Ожидают подтверждения', sec.pending_devices],
      ['Известные компьютеры', sec.known_machines],
      ['Активные сессии', sec.live_sessions],
    ].map(([label, value]) =>
      `<div><span>${esc(label)}</span><strong>${esc(String(value ?? 0))}</strong></div>`).join('');

    const uuidRow = s.user_uuid
      ? `<div><span>UUID</span><strong class="mono">${esc(s.user_uuid)}</strong></div>` : '';
    const legacyRow = s.legacy_user_id
      ? `<div><span>Внутренний id</span><strong class="mono">${esc(String(s.legacy_user_id))}</strong></div>` : '';

    return `<section class="cab-card card-summary">
      <div class="card-summary-head">
        ${avatarHtml({ first_name: s.display_name, username: s.username, avatar_url: s.avatar_url }, 'avatar-lg')}
        <div class="card-summary-id">
          <div class="cab-name">${esc(s.display_name || s.username || '—')}</div>
          <div class="cab-sub">${s.username ? '@' + esc(s.username) : ''}</div>
          <div class="cab-badges">
            <span class="badge ${s.is_owner ? 'live' : 'demo'}">${esc(s.role || '—')}</span>
            <span class="badge ${s.status === 'active' ? 'live' : 'failed'}">${esc(s.status || '—')}</span>
          </div>
        </div>
      </div>
      <div class="admin-env-meta">
        ${uuidRow}${legacyRow}
        <div><span>Создан</span><strong>${cardWhen(s.created_at_utc)}</strong></div>
        <div><span>Последний вход</span><strong>${cardWhen(s.last_login_at_utc)}</strong></div>
        ${counts}
      </div>
      ${attention ? `<div class="admin-env-warnings">${attention}</div>` : ''}
    </section>`;
  }

  function cardIdentityRow(row) {
    const provider = esc(CARD_IDENTITY_LABEL[row.provider] || row.provider || '');
    const verified = row.verified_at
      ? '<span class="badge live">подтверждён</span>'
      : '<span class="badge pending">не подтверждён</span>';
    return `<div class="card-row">
      <div class="card-row-main">
        <div class="card-row-title">${provider} · <span class="mono">${esc(row.display_value || '')}</span></div>
        <div class="cab-sub">действует с ${cardWhen(row.valid_from)}</div>
      </div>
      <div class="card-row-side">${verified}</div>
    </div>`;
  }

  function cardRetiredRow(row) {
    const provider = esc(CARD_IDENTITY_LABEL[row.provider] || row.provider || '');
    // Retired-because-superseded and revoked-because-compromised are different
    // events. Collapsing them would lose the distinction that matters most when
    // reading a compromise.
    const why = row.state === 'revoked'
      ? '<span class="badge failed">отозван</span>'
      : '<span class="badge archived">заменён</span>';
    const reason = row.replacement_reason ? ` · ${esc(row.replacement_reason)}` : '';
    return `<div class="card-row">
      <div class="card-row-main">
        <div class="card-row-title">${provider} · <span class="mono">${esc(row.display_value || '')}</span></div>
        <div class="cab-sub">${cardWhen(row.valid_from)} → ${cardWhen(row.valid_to)}${reason}</div>
      </div>
      <div class="card-row-side">${why}</div>
    </div>`;
  }

  function cardIdentitiesHtml(card) {
    const ids = card.identities || {};
    const current = ids.current || [];
    const history = ids.history || [];
    const chains = ids.replacement_timeline || [];

    const chainHtml = chains.length
      ? `<div class="card-chain">${chains.map(chain => `
          <div class="cab-sub"><strong>${esc(CARD_IDENTITY_LABEL[chain.provider] || chain.provider)}</strong>: ${
            (chain.steps || []).map(step =>
              `<span class="mono">${esc(step.from || '')}</span> → <span class="mono">${esc(step.to || '')}</span> <span class="cab-sub">(${cardWhen(step.at_utc)})</span>`
            ).join(' · ')}</div>`).join('')}</div>`
      : '';

    return `<section class="cab-card">
      <h4>Идентификаторы</h4>
      ${current.length ? current.map(cardIdentityRow).join('')
        : '<div class="cab-sub">Нет активных идентификаторов.</div>'}
      ${history.length ? `<details class="card-details">
        <summary>Предыдущие идентификаторы (${history.length})</summary>
        ${history.map(cardRetiredRow).join('')}
        ${chainHtml}
      </details>` : ''}
    </section>`;
  }

  function cardSessionsHtml(client) {
    const sessions = client.sessions || [];
    if (!sessions.length) return '<div class="cab-sub card-empty">Нет активных сессий.</div>';
    return `<div class="card-sessions">${sessions.map(session => `
      <div class="card-row card-row-nested">
        <div class="card-row-main">
          <div class="card-row-title">Сессия <span class="mono">${esc(String(session.session_id || '').slice(0, 12))}</span></div>
          <div class="cab-sub">${esc(session.environment || '—')} · с ${cardWhen(session.created_at_utc)}${
            session.last_region ? ' · ' + esc(session.last_region) : ''}</div>
        </div>
        <div class="card-row-side">
          <button class="btn sm ghost" data-card-end-session="${esc(session.session_id || '')}">Завершить сессию</button>
        </div>
      </div>`).join('')}</div>`;
  }

  function cardClientHtml(client) {
    const isConnector = client.kind === 'connector';
    const name = isConnector ? 'Windows Connector' : (client.display_name || client.client || 'Клиент');
    const bound = client.bound_via === 'connector_self'
      ? '<span class="badge live">собственный клиент компьютера</span>'
      : (client.bound_via === 'attested_pairing'
        ? '<span class="badge live">привязан кодом Connector</span>' : '');
    const revoke = client.actions && client.actions.revoke_client
      ? `<button class="btn sm ghost" data-card-revoke-client="${esc(client.device_id)}">Отозвать клиента</button>`
      : '';
    return `<div class="card-client">
      <div class="card-row">
        <div class="card-row-main">
          <div class="card-row-title">${isConnector ? '▣' : '▢'} ${esc(name)}${
            client.online ? ' <span class="badge live">онлайн</span>' : ''}</div>
          <div class="cab-sub">${esc(client.os_family || '')} ${esc(client.os_version || '')} · впервые ${
            cardWhen(client.first_seen_at_utc)} · активность ${cardWhen(client.last_seen_at_utc)}</div>
          <div class="cab-badges">${cardBadge(client.status)}${bound}</div>
        </div>
        <div class="card-row-side">${revoke}</div>
      </div>
      ${cardSessionsHtml(client)}
    </div>`;
  }

  function cardMachineHtml(machine) {
    const revoke = machine.actions && machine.actions.revoke_physical_device
      ? `<button class="btn sm danger" data-card-revoke-machine="${esc(machine.physical_device_id)}">Отозвать компьютер</button>`
      : '';
    return `<section class="cab-card card-machine">
      <div class="card-row">
        <div class="card-row-main">
          <div class="card-row-title">🖥 ${esc(machine.display_name || 'Компьютер')}</div>
          <div class="cab-sub">${esc(machine.os_family || '')} ${esc(machine.os_version || '')} · впервые ${
            cardWhen(machine.first_seen_at_utc)} · активность ${cardWhen(machine.last_seen_at_utc)}</div>
          <div class="cab-badges">${cardBadge(machine.status)}</div>
        </div>
        <div class="card-row-side">${revoke}</div>
      </div>
      <div class="cab-sub card-machine-note">Отзыв компьютера завершает все его клиенты и сессии. Завершение отдельной сессии или клиента компьютер не затрагивает.</div>
      <div class="card-clients">${(machine.clients || []).map(cardClientHtml).join('')}</div>
    </section>`;
  }

  function cardDevicesHtml(card) {
    const devices = card.devices || {};
    const machines = devices.machines || [];
    const unbound = devices.unbound_clients || [];

    const machineHtml = machines.length
      ? machines.map(cardMachineHtml).join('')
      : '<section class="cab-card"><h4>Компьютеры</h4><div class="cab-sub">Ни один компьютер ещё не подтвердил себя через Windows Connector.</div></section>';

    // Unpaired clients are shown apart on purpose. Chrome and Edge on one
    // workstation are indistinguishable from the server side, so presenting
    // them under a shared machine would be a guess dressed as a fact.
    const unboundHtml = unbound.length
      ? `<section class="cab-card">
          <h4>Клиенты без привязки к компьютеру (${unbound.length})</h4>
          <div class="cab-sub">${esc(devices.unbound_explanation || '')}</div>
          <div class="card-clients">${unbound.map(cardClientHtml).join('')}</div>
          <div class="cab-sub card-machine-note">Чтобы привязать браузер к компьютеру, запросите код в Windows Connector на этом компьютере и введите его здесь. Объединение по имени компьютера, IP или User-Agent не выполняется никогда — это не доказательство.</div>
          <div class="card-pair-row">
            <input class="input" id="card-pair-code" inputmode="numeric" autocomplete="one-time-code" placeholder="Код привязки" maxlength="8">
            <select class="input" id="card-pair-client">${unbound.map(
              c => `<option value="${esc(c.device_id)}">${esc(c.display_name || c.client || c.device_id)}</option>`).join('')}</select>
            <button class="btn primary" id="card-pair-submit">Привязать к компьютеру</button>
          </div>
        </section>`
      : '';

    return machineHtml + unboundHtml;
  }

  function cardTimelineHtml(card) {
    const rows = card.timeline || [];
    if (!rows.length) {
      return `<section class="cab-card"><h4>Журнал безопасности</h4>
        <div class="cab-sub">Событий пока нет.</div></section>`;
    }
    return `<section class="cab-card">
      <h4>Журнал безопасности</h4>
      <div class="card-timeline">${rows.slice(0, 60).map(row => `
        <div class="card-row card-timeline-row">
          <div class="card-row-main">
            <div class="card-row-title"><span class="card-timeline-icon">${esc(CARD_TIMELINE_ICON[row.category] || '·')}</span> ${esc(row.label || row.event || '')}</div>
            <div class="cab-sub">${cardWhen(row.at_utc)}${
              row.actor_user_id ? ' · инициатор #' + esc(String(row.actor_user_id)) : ''}${
              row.origin ? ' · ' + esc(row.origin) : ''}</div>
          </div>
        </div>`).join('')}</div>
    </section>`;
  }

  function cardExtrasHtml(card) {
    // Admin-only blocks. Absent from the self view because the server does not
    // send them, not because the renderer hides them.
    const extras = card.admin || {};
    const blocks = [];
    const grants = extras.grants || [];
    if (grants.length) {
      blocks.push(`<section class="cab-card"><h4>Права и гранты</h4>
        <div class="cab-badges">${grants.map(g => `<span class="chip-tag">${esc(g)}</span>`).join('')}</div></section>`);
    }
    const workspaces = extras.workspaces || [];
    if (workspaces.length) {
      blocks.push(`<section class="cab-card"><h4>Рабочие пространства (${workspaces.length})</h4>
        ${workspaces.map(w => `<div class="card-row"><div class="card-row-main">
          <div class="card-row-title mono">${esc(w.workspace_id || '')}</div>
          <div class="cab-sub">${esc(w.kind || '')} · ${esc(w.status || '')}</div>
        </div></div>`).join('')}</section>`);
    }
    return blocks.join('');
  }

  function userCardHtml(card) {
    return cardSummaryHtml(card)
      + cardIdentitiesHtml(card)
      + cardExtrasHtml(card)
      + cardDevicesHtml(card)
      + cardTimelineHtml(card);
  }

  // One wiring function too. The actions are the same actions in both views;
  // only who may reach the page differs, and that is enforced on the server.
  function wireUserCard(node, reload) {
    qsa('[data-card-revoke-machine]', node).forEach(button => button.onclick = async () => {
      const id = button.dataset.cardRevokeMachine;
      if (!confirm('Отозвать компьютер? Это завершит все его клиенты и сессии.')) return;
      button.disabled = true;
      try {
        const out = await API.http.accountRevokeMachine(id);
        toast(`Компьютер отозван · клиентов: ${out.revoked_clients} · сессий: ${out.revoked_sessions}`);
        await reload();
      } catch (e) { reportError(e); button.disabled = false; }
    });
    qsa('[data-card-revoke-client]', node).forEach(button => button.onclick = async () => {
      const id = button.dataset.cardRevokeClient;
      if (!confirm('Отозвать этот клиент? Компьютер и остальные клиенты не затрагиваются.')) return;
      button.disabled = true;
      try {
        await API.http.accountRevokeDevice(id);
        toast('Клиент отозван');
        await reload();
      } catch (e) { reportError(e); button.disabled = false; }
    });
    qsa('[data-card-end-session]', node).forEach(button => button.onclick = async () => {
      const id = button.dataset.cardEndSession;
      button.disabled = true;
      try {
        await API.http.accountEndSession(id);
        toast('Сессия завершена');
        await reload();
      } catch (e) { reportError(e); button.disabled = false; }
    });
    const pair = qs('#card-pair-submit', node);
    if (pair) pair.onclick = async () => {
      const code = (qs('#card-pair-code', node) || {}).value || '';
      const client = (qs('#card-pair-client', node) || {}).value || '';
      if (!code.trim()) { toast('Введите код привязки из Windows Connector.'); return; }
      pair.disabled = true;
      try {
        await API.http.accountRedeemPairing(client, code.trim());
        toast('Клиент привязан к компьютеру');
        await reload();
      } catch (e) { reportError(e); pair.disabled = false; }
    };
  }

  async function renderUserCardInto(node, loader) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка карточки…</div>';
    try {
      const card = await loader();
      node.innerHTML = userCardHtml(card);
      wireUserCard(node, () => renderUserCardInto(node, loader));
    } catch (e) {
      renderError(node, e, () => renderUserCardInto(node, loader));
    }
  }

  async function renderSecurityInto(cb, me) {
    cb.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка устройств…</div>';
    let data, nt = null;
    try {
      [data, nt] = await Promise.all([
        API.http.accountSecurity(),
        API.http.accountNtSecurity().catch(() => null),
      ]);
    }
    catch (e) { renderError(cb, e, () => renderSecurityInto(cb, me)); return; }
    const devices = data.devices || [];
    const identities = data.identities || [];
    const providers = data.step_up_providers || [];
    const provNote = providers.length
      ? `Каналы подтверждения: ${providers.map(p => esc(SEC_PROVIDER_LABEL[p] || p)).join(', ')}.`
      : 'Нет подтверждённого канала. Привяжите Telegram или e-mail, чтобы подтверждать устройства.';
    const LOGIN_PROVIDERS = ['telegram', 'google', 'email'];
    const linkedSet = new Set(identities.map(i => String(i.provider || '')));
    const loginCount = identities.filter(i => LOGIN_PROVIDERS.includes(String(i.provider || ''))).length;
    const idRows = identities.length
      ? identities.map(i => {
          const prov = String(i.provider || '');
          const isLogin = LOGIN_PROVIDERS.includes(prov);
          const isLast = isLogin && loginCount <= 1;
          const label = `${esc(SEC_PROVIDER_LABEL[prov] || prov)}${i.label ? ' · ' + esc(i.label) : ''}`;
          const meta = `${i.verified ? '<span class="badge live">подтверждён</span>' : '<span class="badge pending">не подтверждён</span>'}`;
          const action = isLast
            ? '<span class="cab-sub" title="Это единственный способ войти в аккаунт. Сначала привяжите другой способ входа.">Последний способ входа — нельзя отвязать</span>'
            : `<button class="btn ghost" data-id-unlink="${esc(i.identity_id)}" data-id-prov="${esc(prov)}">Отвязать</button>`;
          return `<div class="sec-id-row flex between items-center gap-sm" style="padding:8px 0;border-bottom:1px solid var(--line,rgba(255,255,255,.06))">
            <div class="flex col gap-xs"><span class="chip-tag">${label}</span>${meta}</div>${action}</div>`;
        }).join('')
      : '<div class="muted">Нет привязанных способов входа</div>';
    const addButtons = [];
    if (!linkedSet.has('email')) addButtons.push('<button class="btn" data-id-link="email">Привязать e-mail</button>');
    if (!linkedSet.has('google')) addButtons.push('<button class="btn" data-id-link="google">Привязать Google</button>');
    const telegramNote = !linkedSet.has('telegram')
      ? '<div class="cab-sub">Telegram привязывается автоматически при входе через Telegram-бота.</div>' : '';
    const addSection = (addButtons.length || telegramNote)
      ? `<div class="flex gap-sm wrap" style="margin-top:10px">${addButtons.join('')}</div>${telegramNote}`
      : '<div class="cab-sub" style="margin-top:10px">Все доступные способы входа привязаны.</div>';

    let ntCard = '';
    if (nt && nt.factors && !nt.is_owner) {
      const factorRow = (ok, label) => `<span class="chip-tag">${ok ? '✓' : '•'} ${esc(label)}</span>`;
      const onboardingHtml = (nt.onboarding || []).map(o =>
        `<div class="finance-note"><strong>${esc(o.title)}</strong><br>${esc(o.message)}</div>`).join('');
      const via = nt.email_factor_via && nt.email_factor_via !== 'owner'
        ? ` (через ${esc(SEC_PROVIDER_LABEL[nt.email_factor_via] || nt.email_factor_via)})` : '';
      ntCard = `<div class="cab-card"><h4>Личный NinjaTrader — безопасность</h4>
        <div class="chips-in">${factorRow(nt.factors.telegram, 'Telegram')}${factorRow(nt.factors.email, 'e-mail' + via)}</div>
        <div class="cab-kv"><span class="k">Готовность</span><span class="v"><span class="badge ${nt.ready ? 'live' : 'pending'}">${nt.ready ? 'готово к подключению' : 'нужны факторы'}</span></span></div>
        ${nt.ready
          ? '<div class="cab-sub">Обязательны подтверждённый Telegram и verified e-mail; критические действия дополнительно требуют step-up. E-mail-код — не SMS.</div>'
          : onboardingHtml}</div>`;
    }
    cb.innerHTML = ntCard + `
      <div class="cab-card"><h4>Способы входа</h4><div class="list" id="sec-identities">${idRows}</div>
        <div class="cab-sub">Внутренний идентификатор аккаунта — UUID. Способы входа не объединяются автоматически по совпадению e-mail. Последний способ входа удалить нельзя.</div>
        ${addSection}</div>
      <div class="cab-card"><h4>Устройства</h4>
        <div class="finance-note">${provNote} Новое устройство появляется как «Ожидает подтверждения» и не становится доверенным автоматически. Каждое устройство — отдельная карточка с внутренним ID (UUID), без «железного» идентификатора. Повторные входы одного устройства не создают дублей. Отзыв немедленно завершает сессии только этого устройства.</div>
        <div class="device-grid" id="sec-devices">${devices.length ? devices.map(securityDeviceRow).join('') : '<div class="muted">Устройства не найдены</div>'}</div>
      </div>`;
    const reload = () => renderSecurityInto(cb, me);
    const busy = (btn, fn) => async () => {
      btn.disabled = true;
      try { await fn(); toast('Готово'); reload(); }
      catch (e) { reportError(e); btn.disabled = false; }
    };
    qsa('[data-id-unlink]', cb).forEach(btn => {
      btn.onclick = async () => {
        const prov = SEC_PROVIDER_LABEL[btn.dataset.idProv] || btn.dataset.idProv;
        if (!confirm(`Отвязать способ входа «${prov}»? Войти через него больше не получится, пока вы не привяжете его заново.`)) return;
        btn.disabled = true;
        try {
          await API.http.accountIdentityUnlink({ identity_id: btn.dataset.idUnlink });
          toast('Способ входа отвязан'); reload();
        } catch (e) {
          if (e && (e.code === 'last_login_method' || e.status === 409)) {
            toast('Нельзя удалить последний способ входа. Сначала привяжите другой.');
          } else { reportError(e); }
          btn.disabled = false;
        }
      };
    });
    qsa('[data-id-link]', cb).forEach(btn => {
      const provider = btn.dataset.idLink;
      if (provider === 'google') {
        btn.onclick = busy(btn, async () => {
          const out = await API.http.authGoogleLinkStart({ return_path: location.pathname + location.search });
          if (out && out.auth_url) { location.href = out.auth_url; }
          else throw new Error('Google-линковка недоступна.');
        });
      } else if (provider === 'email') {
        btn.onclick = busy(btn, async () => {
          const email = (prompt('E-mail для привязки:') || '').trim();
          if (!email) throw new Error('E-mail не введён.');
          const started = await API.http.authEmailLinkStart({ email });
          let code = started.test_code || '';
          if (!code) {
            code = (prompt('Введите код, отправленный на ' + email + ':') || '').trim();
            if (!code) throw new Error('Код не введён.');
          }
          await API.http.authEmailLinkVerify({ challenge_id: started.challenge_id, code });
        });
      }
    });

    qsa('[data-sec-details]', cb).forEach(btn => {
      btn.onclick = () => {
        const id = btn.dataset.secDetails;
        const safe = (window.CSS && CSS.escape) ? CSS.escape(id) : id;
        const panel = qs(`[data-device-details="${safe}"]`, cb);
        if (!panel) return;
        const open = panel.hasAttribute('hidden');
        if (open) { panel.removeAttribute('hidden'); btn.textContent = 'Скрыть'; }
        else { panel.setAttribute('hidden', ''); btn.textContent = 'Подробнее'; }
      };
    });
    qsa('[data-sec-approve]', cb).forEach(btn => {
      btn.onclick = busy(btn, async () => {
        const deviceId = btn.dataset.secApprove;
        const started = await API.http.accountSecurityChallenge({ purpose: 'device_confirm', device_id: deviceId });
        let code = started.test_code || '';
        if (!code) {
          code = (prompt('Введите код подтверждения, отправленный через ' + (SEC_PROVIDER_LABEL[started.provider] || started.provider) + ':') || '').trim();
          if (!code) throw new Error('Код не введён.');
        }
        await API.http.accountDeviceApprove({ device_id: deviceId, challenge_id: started.challenge_id, code });
      });
    });
    qsa('[data-sec-reject]', cb).forEach(btn => {
      btn.onclick = async () => {
        if (!confirm('Отклонить это устройство? Его текущие сессии будут завершены.')) return;
        btn.disabled = true;
        try { await API.http.accountDeviceReject(btn.dataset.secReject); toast('Устройство отклонено'); renderSecurityInto(cb, me); }
        catch (e) { reportError(e); btn.disabled = false; }
      };
    });
    qsa('[data-sec-revoke]', cb).forEach(btn => {
      btn.onclick = async () => {
        if (!confirm('Отозвать это устройство? Сессии только этого устройства сразу завершатся.')) return;
        btn.disabled = true;
        try { await API.http.accountDeviceRevoke(btn.dataset.secRevoke); toast('Устройство отозвано'); renderSecurityInto(cb, me); }
        catch (e) { reportError(e); btn.disabled = false; }
      };
    });
  }

  function renderCabinet(body, me, tab) {
    const header = cabinetHeader(me);
    // Cabinet is personal self-service only. System operations, user
    // management, monitoring and owner controls live in the capability-gated
    // Admin Panel.
    const tabs = [['profile', 'Профиль'], ['card', 'Моя карточка'], ['security', 'Безопасность'], ['plans', 'Тарифы']];
    const start = tabs.some(t => t[0] === tab) ? tab : 'profile';
    body.innerHTML = header + `<div class="cab-tabs">${tabs.map(([id, label]) => `<button class="cab-tab ${id === start ? 'on' : ''}" data-cab-tab="${id}">${label}</button>`).join('')}</div><div id="cab-body"></div>`;
    const cb = qs('#cab-body', body);
    const renderTab = (t) => {
      qsa('[data-cab-tab]', body).forEach(b => b.classList.toggle('on', b.dataset.cabTab === t));
      if (t === 'plans') renderPlansInto(cb, me, 'self');
      else if (t === 'card') renderUserCardInto(cb, () => API.http.accountCard());
      else if (t === 'security') renderSecurityInto(cb, me);
      else renderProfileInto(cb, me);
    };
    qsa('[data-cab-tab]', body).forEach(b => b.onclick = () => renderTab(b.dataset.cabTab));
    renderTab(start);
    wireCabinetHeader(body, me);
  }

  async function renderAiRatingsInto(node) {
    node.innerHTML = `<div class="cab-sub">Три рейтинга ★★★ · влияют на routing (после gates ключей/бюджета)</div><div class="muted">Загрузка…</div>`;
    try {
      const data = await API.http.aiStarRatings();
      const table = (rows, cols) => rows && rows.length
        ? `<div class="list">${rows.slice(0, 40).map(r => `<div class="row"><div class="row-main"><div class="row-title">${esc(cols.map(c => r[c] ?? '').filter(Boolean).join(' · '))}</div>
            <div class="row-sub">avg ${esc(r.avg)} · n=${esc(r.count)} · ★1=${esc(r.ones || 0)}</div></div></div>`).join('')}</div>`
        : '<div class="muted">Пока нет оценок</div>';
      node.innerHTML = `
        <div class="cab-sub">Exploration rate: ${esc(data.exploration_rate)} · рейтинги не обходят key/budget/cooldown</div>
        <h4 class="cab-section-title">Должности</h4>${table(data.roles, ['role_id'])}
        <h4 class="cab-section-title">Модели</h4>${table(data.models, ['model_id', 'provider'])}
        <h4 class="cab-section-title">Должность + модель</h4>${table(data.role_model, ['role_id', 'model_id'])}
        <div class="support-toolbar"><button class="btn ghost" id="air-refresh">Обновить</button></div>`;
      const refresh = qs('#air-refresh', node);
      if (refresh) refresh.onclick = () => renderAiRatingsInto(node);
    } catch (e) {
      node.innerHTML = `<div class="error">${esc(e.message || e)}</div>`;
    }
  }

  async function renderOperationsInto(node) {
    node.innerHTML = '<div class="cab-sub">Production control plane</div><div class="muted">Загрузка…</div>';
    try {
      const data = await API.http.ownerOperations();
      const queues = data.queues || {};
      const worker = data.worker || {};
      const workerMetrics = worker.metrics || {};
      const workerCounts = workerMetrics.counts || {};
      const serviceHealth = data.service_health || {};
      const services = Array.isArray(serviceHealth.services) ? serviceHealth.services : [];
      const telegram = data.telegram || {};
      const telegramCounts = telegram.counts || {};
      const connectorCounts = data.connectors || {};
      const formatAge = value => {
        const seconds = Math.max(0, Number(value || 0));
        return seconds < 60 ? `${Math.round(seconds)} с` : `${Math.round(seconds / 60)} мин`;
      };
      const value = (source, key) => Number((source || {})[key] || 0);
      const healthy = service => !!service.fresh && String(service.status || '') === 'healthy';
      const serviceRows = services.map(service => `<div class="row"><div class="row-main"><div class="row-title">${esc(service.service_role || 'service')} <span class="badge ${healthy(service) ? 'live' : 'pending'}">${healthy(service) ? 'healthy' : esc(service.status || 'unknown')}</span></div><div class="row-sub">${esc(service.instance_id || '—')} · ${formatAge(service.age_sec)} назад</div></div></div>`).join('');
      const workerRows = Object.entries(workerCounts).map(([kind, counts]) => `<div class="row"><div class="row-main"><div class="row-title">${esc(kind)}</div><div class="row-sub">queued ${value(counts, 'queued')} · running ${value(counts, 'running')} · completed ${value(counts, 'completed')} · dead letter ${value(counts, 'dead_letter')}</div></div></div>`).join('');
      const dashboardState = data.ok ? 'live' : 'pending';
      node.innerHTML = `
        <div class="cab-sub">Только агрегированные статусы: без payload, токенов, путей и tenant-данных.</div>
        <div class="kpi-row cab-kpi"><div class="kpi ${dashboardState}"><div class="kpi-label">Control plane</div><div class="kpi-value">${data.ok ? 'ready' : 'degraded'}</div></div>
        <div class="kpi"><div class="kpi-label">Critical alerts</div><div class="kpi-value">${value(queues, 'critical_alerts')}</div></div>
        <div class="kpi"><div class="kpi-label">Jobs queued</div><div class="kpi-value">${value(queues, 'jobs_queued')}</div></div>
        <div class="kpi"><div class="kpi-label">Telegram queued</div><div class="kpi-value">${value(telegramCounts, 'updates_queued') + value(telegramCounts, 'outbox_queued')}</div></div></div>
        <h4 class="cab-section-title">Service heartbeats</h4><div class="list">${serviceRows || '<div class="muted">Нет зарегистрированных heartbeat</div>'}</div>
        <h4 class="cab-section-title">Durable queues</h4><div class="kpi-row cab-kpi"><div class="kpi"><div class="kpi-label">Telegram inbox</div><div class="kpi-value">${value(queues, 'telegram_inbox')}</div></div>
        <div class="kpi"><div class="kpi-label">Telegram outbox</div><div class="kpi-value">${value(queues, 'telegram_outbox')}</div></div>
        <div class="kpi"><div class="kpi-label">Worker p95 age</div><div class="kpi-value">${formatAge((workerMetrics.queue_age_seconds || {}).p95)}</div></div>
        <div class="kpi"><div class="kpi-label">Expired leases</div><div class="kpi-value">${value(workerMetrics.leases, 'expired')}</div></div></div>
        <h4 class="cab-section-title">Worker classes</h4><div class="list">${workerRows || '<div class="muted">Worker metrics недоступны</div>'}</div>
        <h4 class="cab-section-title">Connector fleet</h4><div class="kpi-row cab-kpi"><div class="kpi"><div class="kpi-label">Online</div><div class="kpi-value">${value(connectorCounts, 'online')}</div></div>
        <div class="kpi"><div class="kpi-label">Offline</div><div class="kpi-value">${value(connectorCounts, 'offline')}</div></div>
        <div class="kpi"><div class="kpi-label">Blocked</div><div class="kpi-value">${value(connectorCounts, 'blocked')}</div></div>
        <div class="kpi"><div class="kpi-label">Consumer</div><div class="kpi-value">${(telegram.consumer || {}).active ? 'active' : 'offline'}</div></div></div>
        <div class="support-toolbar"><button class="btn ghost" id="ops-refresh">Обновить</button></div>`;
      const refresh = qs('#ops-refresh', node);
      if (refresh) refresh.onclick = () => renderOperationsInto(node);
    } catch (e) {
      renderError(node, e, () => renderOperationsInto(node));
    }
  }

  async function renderMonitoringInto(node) {
    node.innerHTML = `<div class="cab-sub">Сессии и ресурсы · метрики вкладки браузера</div><div class="muted">Загрузка…</div>`;
    try {
      const data = await withDeadline(API.http.ownerSupportMonitoring(), 'Мониторинг');
      const users = data.users || [];
      const sessions = data.auth_sessions || [];
      const note = esc(data.telemetry_note || 'Метрики вкладки браузера, не ОС.');
      // Derived here rather than added to the payload: both are simple facts
      // about the session list the page already has, and a second source for
      // them would be a second thing to keep in step.
      const impersonating = sessions.filter(s => s.impersonating).length;
      const accountsWithSession = new Set(sessions.map(s => String(s.user_id))).size;
      node.innerHTML = `
        <div class="cab-sub">${note}</div>
        <div class="kpi-row cab-kpi">
          <div class="kpi"><div class="kpi-label">Сейчас online</div><div class="kpi-value">${Number(data.online_count || 0)}</div>
            <div class="kpi-sub">из ${users.length} с телеметрией</div></div>
          <div class="kpi ${Number(data.alert_count || 0) ? 'kpi-warn' : ''}"><div class="kpi-label">Требуют внимания</div><div class="kpi-value">${Number(data.alert_count || 0)}</div>
            <div class="kpi-sub">${Number(data.alert_count || 0) ? 'проверьте список ниже' : 'алертов нет'}</div></div>
          <div class="kpi"><div class="kpi-label">Активные сессии</div><div class="kpi-value">${sessions.length}</div>
            <div class="kpi-sub">${impersonating ? impersonating + ' под impersonation' : 'без impersonation'}</div></div>
          <div class="kpi"><div class="kpi-label">Аккаунтов с сессией</div><div class="kpi-value">${accountsWithSession}</div>
            <div class="kpi-sub">${sessions.length > accountsWithSession ? 'есть вход с нескольких клиентов' : 'по одному клиенту'}</div></div>
        </div>
        <h4 class="cab-section-title">Пользователи online</h4>
        <div class="list">${users.length ? users.map(u => {
          const name = esc(`${u.first_name || ''} ${u.last_name || ''}`.trim() || u.username || u.user_id);
          const metrics = u.online
            ? `CPU ${Number(u.cpu_main_thread_percent || 0).toFixed(0)}% · heap ${Number(u.js_heap_used_mb || 0).toFixed(0)} MB · net ${Number(u.network_mb_per_min || 0).toFixed(2)} MB/мин`
            : 'offline';
          return `<div class="row"><div class="row-main"><div class="row-title">${name} <span class="badge ${u.online ? 'live' : ''}">${u.online ? 'online' : 'offline'}</span></div>
            <div class="row-sub">id ${esc(u.user_id)} · вкладок ${Number(u.session_count || 0)} · auth ${Number(u.auth_session_count || 0)} · ${esc(metrics)}${u.page ? ' · ' + esc(u.page) : ''}</div></div>
            <button class="btn sm ghost" data-mon-open="${esc(u.user_id)}">Карточка</button></div>`;
        }).join('') : '<div class="muted">Нет данных телеметрии</div>'}</div>
        <h4 class="cab-section-title">Активные auth-сессии</h4>
        <div class="list">${sessions.length ? sessions.map(s => {
          const name = esc(`${s.first_name || ''} ${s.last_name || ''}`.trim() || s.username || s.user_id);
          return `<div class="row"><div class="row-main"><div class="row-title">${name}${s.impersonating ? ' · <span class="badge">impersonation</span>' : ''}</div>
            <div class="row-sub">${esc(s.client || 'Браузер')} · ${esc(s.machine || '—')} · ${esc(s.ip || '')} · ${esc(shortDt(s.created_at_utc) || '')}</div></div>
            <button class="btn sm danger" data-mon-end="${esc(s.user_id)}" data-mon-session="${esc(s.session_id)}">Завершить</button></div>`;
        }).join('') : '<div class="muted">Нет активных сессий</div>'}</div>
        <div class="support-toolbar"><button class="btn ghost" id="mon-refresh">Обновить</button></div>`;
      const refresh = qs('#mon-refresh', node);
      if (refresh) refresh.onclick = () => renderMonitoringInto(node);
      qsa('[data-mon-open]', node).forEach(btn => btn.onclick = () => {
        try { sessionStorage.setItem('stratforge.open.user', String(btn.dataset.monOpen || '')); } catch (e) { /* ignore */ }
        openAdminPanel('users');
      });
      qsa('[data-mon-end]', node).forEach(btn => btn.onclick = async () => {
        if (!confirm('Завершить выбранную сессию? Пользователь увидит сообщение «Сессия завершена администратором».')) return;
        btn.disabled = true;
        try {
          await API.http.authUserSessions(btn.dataset.monEnd, { session_id: btn.dataset.monSession });
          toast('Сессия завершена');
          renderMonitoringInto(node);
        } catch (e) { reportError(e); btn.disabled = false; }
      });
    } catch (e) {
      node.innerHTML = `<div class="error">${esc(e.message || e)}</div>`;
    }
  }

  // Connector and integration status, rendered on the Admin page itself.
  // Previously this module was a single button to another screen, so the
  // ordinary question -- is Telegram up, which environment holds the
  // market-data hub -- cost an extra navigation. No secret is ever rendered:
  // the endpoint returns states and identifiers only.
  const CONNECTOR_STATE_LABEL = {
    healthy: 'работает', degraded: 'деградация', not_configured: 'не настроено',
    error: 'ошибка', unknown: 'неизвестно', timeout: 'нет ответа',
  };

  function connectorBadge(state) {
    const key = String(state || 'unknown');
    const label = CONNECTOR_STATE_LABEL[key] || key;
    return `<span class="conn-badge conn-${esc(key)}">${esc(label)}</span>`;
  }

  function connectorDetails(row) {
    const skip = new Set(['id', 'label', 'state', 'providers']);
    const parts = Object.keys(row).filter(k => !skip.has(k) && row[k] !== '' && row[k] !== null && row[k] !== undefined)
      .map(k => `<div class="conn-kv"><span>${esc(k)}</span><b>${esc(String(row[k]))}</b></div>`);
    if (Array.isArray(row.providers) && row.providers.length) {
      parts.push(row.providers.map(p => `<div class="conn-kv"><span>${esc(p.name || '')}</span><b>${esc(String(p.runtime_state || ''))}</b></div>`).join(''));
    }
    return parts.join('');
  }

  // A connector dashboard is read when something is already wrong, so it has
  // to degrade well: show every source that answered, say plainly which ones
  // did not, and never leave a spinner running with nothing behind it.
  const CONNECTOR_DEADLINE_MS = 8000;

  function connectorSectionHtml(row) {
    const state = String(row.state || 'unknown');
    const slow = Number(row.elapsed_ms || 0);
    const timing = slow >= 500 ? ` <span class="cab-sub">${slow} мс</span>` : '';
    // A source that timed out or errored says so in place of its details. It
    // keeps its card rather than disappearing: a missing card reads as "there
    // is no such connector", which is a different and wrong statement.
    const body = (state === 'timeout' || state === 'error')
      ? `<div class="conn-unavailable">${esc(state === 'timeout'
          ? 'Источник не ответил вовремя. Остальные данные на странице актуальны.'
          : 'Источник вернул ошибку. Остальные данные на странице актуальны.')}
         ${row.detail ? `<div class="cab-sub mono">${esc(String(row.detail))}</div>` : ''}</div>`
      : connectorDetails(row);
    return `<div class="conn-card${state === 'timeout' || state === 'error' ? ' is-unavailable' : ''}">
      <div class="conn-head"><b>${esc(row.label || row.id)}</b>${connectorBadge(state)}${timing}</div>
      <div class="conn-body">${body}</div>
    </div>`;
  }

  // Connecting a Connector is three acts: get the program, install it, let it
  // in. The panel used to open on "выдать код подключения", which made an
  // implementation detail the first thing a new user met -- and a one-time
  // secret is a poor greeting. The code still exists, as the fallback for when
  // the deep link cannot reach an installed Connector.
  function connectorInstallerHtml(installer) {
    const url = String((installer || {}).download_url || '');
    if (url) {
      return `<a class="btn primary" id="conn-download" href="${esc(url)}"
        rel="noopener">Скачать Connector</a>`;
    }
    // No link is offered when there is nothing signed to link to. A dead
    // download button teaches the reader that the page lies.
    return `<button class="btn ghost" disabled>Скачать Connector</button>
      <div class="cab-sub">${esc((installer || {}).message
        || 'Подписанный установщик ещё не опубликован.')}</div>`;
  }

  function connectorEnrollHtml(environment, installer) {
    return `<section class="cab-card" id="conn-enroll">
      <h4>Подключить NinjaTrader</h4>
      <div class="cab-sub">Connector работает только с окружением
        <b>${esc(environment || '—')}</b>: подключённый здесь, он не отвечает другому.</div>

      <ol class="conn-steps">
        <li>
          <div class="conn-step-title">Скачать Connector</div>
          <div class="cab-sub">Устанавливается рядом с NinjaTrader 8 на том же компьютере.</div>
          <div class="flex gap-sm wrap" style="margin-top:6px">${connectorInstallerHtml(installer)}</div>
        </li>
        <li>
          <div class="conn-step-title">Установить и открыть в NinjaTrader</div>
          <div class="cab-sub">NinjaTrader → вкладка StratForge Connector. NinjaTrader 8 должен быть запущен.</div>
        </li>
        <li>
          <div class="conn-step-title">Авторизовать</div>
          <div class="cab-sub">Разрешение передаётся установленному Connector напрямую —
            вводить ничего не нужно.</div>
          <div class="grid cols-2" style="margin-top:6px">
            <label class="field"><span>Название компьютера</span>
              <input id="conn-enroll-label" placeholder="например, DIMONCHECK"></label>
            <label class="field"><span>Workspace ID (необязательно)</span>
              <input id="conn-enroll-ws" placeholder="ws_…"></label>
          </div>
          <div class="flex gap-sm wrap" style="margin-top:8px">
            <button class="btn primary" id="conn-authorize">Авторизовать Connector</button>
          </div>
          <div id="conn-enroll-out" class="cab-sub"></div>
        </li>
      </ol>

      <details class="card-details" id="conn-manual">
        <summary>Не открылся Connector — ввести код вручную</summary>
        <div class="cab-sub">Одноразовый код для этого окружения. Действует несколько минут
          и показывается один раз.</div>
        <div class="flex gap-sm" style="margin-top:8px">
          <button class="btn" id="conn-enroll-start">Показать код подключения</button>
        </div>
        <div id="conn-manual-out" class="cab-sub"></div>
      </details>
    </section>`;
  }

  async function connectorMintPairing(node) {
    return API.http.bridgePairStart({
      machine_label: (qs('#conn-enroll-label', node).value || '').trim(),
      workspace_id: (qs('#conn-enroll-ws', node).value || '').trim(),
      // This Admin flow installs the authenticated Connector, even in LOCAL.
      // Without the explicit transport Development falls back to the legacy
      // eight-character bridge code, which the Connector correctly rejects.
      transport: 'production_connector',
    });
  }

  function wireConnectorEnroll(node) {
    const authorize = qs('#conn-authorize', node);
    if (authorize) authorize.onclick = async () => {
      const out = qs('#conn-enroll-out', node);
      authorize.disabled = true;
      out.innerHTML = '<span class="spinner"></span> Готовим авторизацию…';
      try {
        const res = await connectorMintPairing(node);
        if (res && res.pairing_uri) {
          // Handed to the installed program rather than to the human. Nothing
          // is displayed: a code nobody has to read is a code nobody can leak.
          out.innerHTML = `<div class="finance-note">Разрешение отправлено в установленный
            Connector. Подтвердите подключение в окне NinjaTrader.</div>`;
          location.href = res.pairing_uri;
        } else {
          // No deep link means nothing is installed to receive it. Say so and
          // point at the fallback rather than failing silently.
          out.innerHTML = `<div class="admin-env-warnings"><div>⚠ Установленный Connector
            не отвечает. Откройте «ввести код вручную» ниже.</div></div>`;
          const manual = qs('#conn-manual', node);
          if (manual) manual.open = true;
        }
      } catch (e) {
        out.innerHTML = `<div class="admin-env-warnings"><div>⚠ ${esc((e && e.message) || e)}</div></div>`;
      } finally {
        authorize.disabled = false;
      }
    };

    const button = qs('#conn-enroll-start', node);
    if (!button) return;
    button.onclick = async () => {
      const out = qs('#conn-manual-out', node);
      button.disabled = true;
      out.innerHTML = '<span class="spinner"></span> Выдаём код…';
      try {
        const res = await connectorMintPairing(node);
        const minutes = Math.max(1, Math.round((res.expires_in_sec || 600) / 60));
        // Shown once. It is a credential for the duration of its life, so it is
        // not stored anywhere in the page and not repeated after a refresh.
        out.innerHTML = `<div class="finance-note">
          <div>Код подключения (действует ${minutes} мин, показывается один раз):</div>
          <div class="mono" style="font-size:18px;letter-spacing:2px;margin:6px 0">${esc(res.code || '')}</div>
          <div>Введите его в NinjaTrader → StratForge Connector → «Подключить».</div>
          ${res.workspace && res.workspace.workspace_id
            ? `<div class="cab-sub mono">workspace: ${esc(res.workspace.workspace_id)}</div>` : ''}
        </div>`;
      } catch (e) {
        out.innerHTML = `<div class="admin-env-warnings"><div>⚠ ${esc((e && e.message) || e)}</div></div>`;
      } finally {
        button.disabled = false;
      }
    };
  }

  async function renderConnectorsInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка статусов…</div>';

    // A deadline on the client as well as on each source. Without it a request
    // that never completes leaves the spinner up forever, which tells the
    // operator nothing and looks identical to a slow network.
    let doc = null;
    let failure = '';
    try {
      doc = await withDeadline(API.http.adminConnectors(), 'Статусы коннекторов',
                               CONNECTOR_DEADLINE_MS);
    } catch (e) {
      failure = (e && e.message) || String(e);
    }

    if (!doc) {
      // Even total failure is a report, not a blank page: it says what was
      // tried, why it stopped, and offers the retry.
      node.innerHTML = `
        <div class="conn-unavailable">
          <b>Статусы коннекторов недоступны.</b>
          <div class="cab-sub">${esc(failure)}</div>
        </div>
        <div class="row" style="margin-top:12px;gap:8px">
          <button class="btn" id="conn-refresh">Повторить</button>
          <button class="btn ghost" id="conn-detail">Подробный экран Telegram / Connector</button>
        </div>`;
      const retry = qs('#conn-refresh', node);
      if (retry) retry.onclick = () => renderConnectorsInto(node);
      const detailBtn = qs('#conn-detail', node);
      if (detailBtn) detailBtn.onclick = () => { closeDrawer(); showTelegram(); };
      return;
    }

    const sections = doc.sections || [];
    const missing = doc.unavailable_sources || [];
    const partialNote = missing.length
      ? `<div class="admin-env-warnings"><div>⚠ Часть источников не ответила: ${
          missing.map(id => esc(String(id))).join(', ')}. Остальные карточки показывают актуальные данные.</div></div>`
      : '';

    node.innerHTML = `
      <div class="cab-sub">Окружение: <b>${esc(doc.environment || '')}</b> · обновлено ${esc(doc.generated_at_utc || '')}${
        doc.probe_timeout_sec ? ` · таймаут источника ${esc(String(doc.probe_timeout_sec))} с` : ''}</div>
      <div class="finance-note">Секреты и токены здесь не показываются — только статусы и явные действия.</div>
      ${partialNote}
      ${connectorEnrollHtml(doc.environment, doc.installer)}
      <div class="conn-grid">${sections.map(connectorSectionHtml).join('')}</div>
      <div class="row" style="margin-top:12px;gap:8px">
        <button class="btn" id="conn-refresh">Обновить</button>
        <button class="btn ghost" id="conn-detail">Подробный экран Telegram / Connector</button>
      </div>`;
    wireConnectorEnroll(node);
    const refresh = qs('#conn-refresh', node);
    if (refresh) refresh.onclick = () => renderConnectorsInto(node);
    const detail = qs('#conn-detail', node);
    if (detail) detail.onclick = () => { closeDrawer(); showTelegram(); };
  }

  async function renderStagingInto(node) {
    node.innerHTML = `<div class="cab-sub">Разработка / QA · открыть приложение глазами любого пользователя (только Development, 127.0.0.1)</div><div class="muted">Загрузка…</div>`;
    let status, usersDoc;
    try {
      [status, usersDoc] = await Promise.all([
        API.http.testAuthStatus().catch(err => ({ enabled: false, error: err.message })),
        API.http.testAuthUsers().catch(() => ({ users: [] })),
      ]);
    } catch (e) { node.innerHTML = `<div class="empty-state">${esc(e.message || e)}</div>`; return; }
    if (!status || !status.enabled) {
      node.innerHTML = `<div class="finance-note"><strong>Недоступно.</strong> Локальная QA-имперсонизация работает только в Development на 127.0.0.1. В Canary/Production она намеренно отключена.${status && status.error ? '<br>' + esc(status.error) : ''}</div>`;
      return;
    }
    const users = usersDoc.users || [];
    const findPreset = (p) => users.find(u => String(u.virtual_preset || '') === p);
    const PERSONAS = [
      { preset: 'developer', label: 'Разработчик', sub: 'полная команда агентов' },
      { preset: 'ordinary', label: 'Обычный пользователь', sub: 'платный тариф' },
      { preset: 'personal_nt', label: 'Свой NinjaTrader', sub: 'личный контур + команда' },
      { preset: 'shared_nt', label: 'Общий NinjaTrader', sub: 'один координатор' },
      { preset: 'new', label: 'Новый пользователь', sub: 'до выбора режима' },
      { preset: 'blocked', label: 'Заблокирован', sub: 'нет доступа' },
      { preset: 'no_google', label: 'Telegram без Google', sub: 'нужна привязка' },
    ];
    const openAs = async (preset) => {
      try {
        let u = findPreset(preset);
        if (!u) { u = (await API.http.testAuthVirtualUser({ preset })).user; }
        await API.http.ownerImpersonate(Number(u.user_id), preset);
        toast('Открываю приложение как: ' + preset);
        setTimeout(() => location.reload(), 300);
      } catch (e) { reportError(e); }
    };
    node.innerHTML = `
      <div class="finance-note">Откройте приложение глазами любого пользователя — появится красный баннер тестового режима, вернуться к владельцу можно кнопкой ниже. Реальные Telegram/Google/e-mail не нужны: состояния входа имитируются локально. Реальный внешний вход остаётся external acceptance.</div>
      <div class="section-title">Открыть как персону</div>
      <div class="qa-persona-grid">${PERSONAS.map(p => `<button class="qa-persona" data-qa-persona="${esc(p.preset)}"><span class="qa-persona-title">${esc(p.label)}</span><span class="qa-persona-sub">${esc(p.sub)}</span></button>`).join('')}</div>
      <div class="section-title">Способы входа — состояние и симуляция</div>
      <div class="finance-note">Локально можно проверить весь UI привязок, но <strong>реальный сквозной вход — это external acceptance, а не PASS</strong>: он требует настоящего Telegram-бота и/или Google OAuth-учётных данных.</div>
      <div class="list">
        <div class="feat-row"><span><strong>Telegram</strong> — привязывается автоматически при входе через бота. Локально у виртуальных пользователей отмечен ✓.</span><span class="badge trial">реальный E2E: external</span></div>
        <div class="feat-row"><span><strong>Google</strong> — реальный OAuth требует настроенных client_id/secret. Локально привязка и вход имитируются test-auth.</span><span class="badge trial">реальный E2E: external</span></div>
        <div class="feat-row"><span><strong>e-mail</strong> — вход по коду. Локально код виден в ответе test-auth; реальная доставка письма — вне этой среды.</span><span class="badge trial">реальный E2E: external</span></div>
      </div>
      <div class="section-title">Служебные AI-аккаунты разработки</div>
      <div class="finance-note">Эти входы для агентов разработки (Claude/GPT), а не для владельца, поэтому вынесены сюда. Действия аудируются под отдельным идентификатором.</div>
      <div class="flex gap-sm wrap"><button class="btn ghost" data-qa-svc="claude">Войти как Claude</button><button class="btn ghost" data-qa-svc="gpt">Войти как GPT</button><button class="btn primary" data-qa-return>Вернуться к владельцу</button></div>
      <div class="section-title">Виртуальные пользователи и состояния входа</div>
      <div class="form-row"><label>Preset</label><select id="stg-preset">${(status.presets || []).map(p => `<option value="${esc(p.id)}">${esc(p.label || p.id)}</option>`).join('')}</select>
        <input id="stg-name" placeholder="Имя (опционально)" /><button class="btn primary" id="stg-create">Создать</button></div>
      <div class="list" id="stg-list">${users.map(u => {
        const name = esc(`${u.first_name || ''} ${u.last_name || ''}`.trim() || u.username || u.user_id);
        return `<div class="row"><div class="row-main"><div class="row-title">${name} · <span class="badge">${esc(u.virtual_preset || '')}</span></div>
          <div class="row-sub">id ${esc(u.user_id)} · Telegram ✓ · Google ${u.google_linked ? '✓' : '—'} · e-mail ${u.email ? '✓' : '—'} · ${esc(u.status || '')}</div></div>
          <div class="flex gap-xs wrap">
            <button class="btn sm primary" data-stg-as="${esc(u.user_id)}">Открыть как</button>
            ${u.google_linked ? '' : `<button class="btn sm ghost" data-stg-google="${esc(u.user_id)}">+ Google</button>`}
            <button class="btn sm ghost" data-stg-team="${esc(u.user_id)}">Полная команда</button>
          </div></div>`;
      }).join('') || '<div class="muted">Пока нет виртуальных пользователей</div>'}</div>`;
      qsa('[data-qa-persona]', node).forEach(b => b.onclick = () => openAs(b.dataset.qaPersona));
      qsa('[data-qa-svc]', node).forEach(b => b.onclick = async () => {
        try { await API.http.devServiceLogin(b.dataset.qaSvc); toast('Служебный вход'); location.reload(); } catch (e) { reportError(e); }
      });
      const ret = qs('[data-qa-return]', node);
      if (ret) ret.onclick = async () => {
        try { await API.http.devServiceLogin('owner').catch(() => {}); await API.http.ownerImpersonateEnd().catch(() => {}); toast('Сессия владельца'); location.reload(); } catch (e) { reportError(e); }
      };
      const create = qs('#stg-create', node);
      if (create) create.onclick = async () => {
        create.disabled = true;
        try { await API.http.testAuthVirtualUser({ preset: qs('#stg-preset', node)?.value || 'demo', display_name: qs('#stg-name', node)?.value || '' }); toast('Виртуальный пользователь создан'); renderStagingInto(node); }
        catch (e) { reportError(e); create.disabled = false; }
      };
      qsa('[data-stg-as]', node).forEach(btn => btn.onclick = async () => {
        if (!confirm('Открыть приложение как этот пользователь?')) return;
        btn.disabled = true;
        try { await API.http.ownerImpersonate(Number(btn.dataset.stgAs)); toast('Открываю'); setTimeout(() => location.reload(), 300); }
        catch (e) { reportError(e); btn.disabled = false; }
      });
      qsa('[data-stg-google]', node).forEach(btn => btn.onclick = async () => {
        try { await API.http.testAuthGoogleLink({ user_id: Number(btn.dataset.stgGoogle) }); toast('Google привязан'); renderStagingInto(node); } catch (e) { reportError(e); }
      });
      qsa('[data-stg-team]', node).forEach(btn => btn.onclick = async () => {
        try { await API.http.ownerAgentTeamGrant(Number(btn.dataset.stgTeam), 'grant'); toast('Выдана полная команда агентов'); } catch (e) { reportError(e); }
      });
  }

  function loginCard(inner) {
    return `<div class="auth-screen"><section class="auth-card"><div class="auth-brand"><img src="${BRAND_MARK}" alt=""><div><strong>${APP_NAME}</strong><span>Защищённый вход</span></div></div>${inner}<div class="auth-security">Единый профиль · подтверждённые Telegram, Google или e-mail<br>Внутренний идентификатор аккаунта — UUID; способы входа не объединяются автоматически</div></section></div>`;
  }

  async function showLegalNoticeModal(id, fallbackLabel) {
    let data;
    try { data = await (window.API ? API.http.legalDocument(id) : Promise.reject()); }
    catch (e) { toast('Не удалось загрузить связанный документ'); return; }
    data = data.document || data;
    const title = data.title || fallbackLabel || 'Связанный документ';
    const overlay = el(`<div class="terms-modal terms-notice-modal"><div class="terms-modal-card"><div class="terms-modal-head"><strong>${esc(title)}</strong><button class="btn ghost sm" data-notice-close>Закрыть</button></div><div class="terms-modal-body"><p class="cab-sub">Официальный информационный документ текущей версии продукта. Отдельное принятие при регистрации не требуется.</p><pre class="terms-notice-text">${esc(data.content || '')}</pre></div></div></div>`);
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    const closeBtn = qs('[data-notice-close]', overlay); if (closeBtn) closeBtn.onclick = close;
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  }

  async function showTermsModal() {
    let data;
    try { data = await (window.API ? API.http.legalTerms() : Promise.reject()); }
    catch (e) { toast('Не удалось загрузить условия'); return; }
    const sections = (data.sections || []).map(s => `<h4>${esc(s.heading)}</h4><p>${esc(s.body)}</p>`).join('');
    const meta = [data.summary, data.date].filter(Boolean).map(esc).join(' · ');
    const notices = (data.notices || []).map(n => `<button type="button" class="linklike terms-notice-link" data-legal-notice="${esc(n.id)}">${esc(n.label)}</button>`).join('');
    const noticeBlock = notices ? `<h4>Дополнительные информационные документы</h4><p>Эти официальные материалы можно прочитать отдельно. Они не требуют отдельного принятия при регистрации.</p><div class="terms-notice-links">${notices}</div>` : '';
    const overlay = el(`<div class="terms-modal"><div class="terms-modal-card"><div class="terms-modal-head"><strong>${esc(data.title || 'Условия использования')}</strong><button class="btn ghost sm" id="terms-close">Закрыть</button></div><div class="terms-modal-body">${meta ? `<p class="cab-sub">${meta}</p>` : ''}${sections}${noticeBlock}<div class="cab-sub">Версия ${esc(data.version || '')} · SHA-256 ${esc(data.digest || '')}</div></div></div></div>`);
    document.body.appendChild(overlay);
    const close = () => overlay.remove();
    const closeBtn = qs('#terms-close', overlay); if (closeBtn) closeBtn.onclick = close;
    qsa('[data-legal-notice]', overlay).forEach(btn => btn.onclick = () => showLegalNoticeModal(btn.dataset.legalNotice, btn.textContent));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  }

  function renderTelegramLogin(initialError) {
    document.documentElement.classList.add('auth-locked');
    const content = qs('.content');
    const news = qs('[data-global-news-strip]'); if (news) news.hidden = true;
    if (!content) return;
    let polling = null;
    let providers = (initialError && initialError.providers) || {};
    const initialMessage = typeof initialError === 'string'
      ? initialError
      : (initialError && initialError.status && ![401, 403].includes(Number(initialError.status)) ? initialError.message : '');
    let qrTick = null;
    const stopQrRefresh = () => { if (qrTick) clearInterval(qrTick); qrTick = null; };
    const stopPolling = () => {
      if (polling) clearInterval(polling);
      polling = null;
      stopQrRefresh();
    };
    const renderStart = (message) => {
      stopPolling();
      const telegram = providers.telegram || {};
      const google = providers.google || {};
      const email = providers.email || {};
      const telegramDisabled = telegram.available === false;
      const googleEnabled = !!(google.available || google.test_auth_fallback);
      const emailEnabled = !!email.available;
      content.innerHTML = loginCard(`<div id="auth-provider-start"><div class="auth-copy"><h1>Вход и регистрация</h1><p>Войдите в существующий аккаунт или зарегистрируйте новый. После подтверждения личности новый пользователь автоматически получает полный пробный доступ к продукту на 7 дней. Живые графики используют только разрешённый для аккаунта источник market data.</p></div>${message ? `<div class="finance-note telegram-error">${esc(message)}</div>` : ''}<button class="btn primary auth-main-action" id="auth-start" ${telegramDisabled ? 'disabled' : ''}>Продолжить через Telegram</button><button class="btn ghost auth-main-action" id="auth-google-start" ${googleEnabled ? '' : 'disabled'}>${google.test_auth_fallback && !google.available ? 'Google · Development test' : (googleEnabled ? 'Продолжить через Google' : 'Google пока не настроен')}</button><div class="auth-copy"><p>Или используйте подтверждённый e-mail.</p></div><form id="auth-email-start-form" class="auth-form"><div class="field"><label for="auth-login-email">E-mail</label><input id="auth-login-email" type="email" autocomplete="email" required maxlength="254" placeholder="you@example.com"></div><div class="field"><label for="auth-login-first">Имя <span class="cab-sub">(для нового профиля)</span></label><input id="auth-login-first" autocomplete="given-name" maxlength="80"></div><div class="field"><label for="auth-login-last">Фамилия <span class="cab-sub">(для нового профиля)</span></label><input id="auth-login-last" autocomplete="family-name" maxlength="80"></div><label class="auth-terms"><input type="checkbox" id="auth-provider-accept"> <span>Для нового профиля я соглашаюсь с <button type="button" class="linklike" id="auth-provider-terms">договором StratForge AI</button>.</span></label><button class="btn ghost auth-main-action" type="submit" ${emailEnabled ? '' : 'disabled'}>${emailEnabled ? 'Получить код по e-mail' : 'E-mail вход пока недоступен'}</button></form><button class="btn ghost auth-main-action" id="auth-open-promo" type="button">Промокод или донат</button></div>`);
      const button = qs('#auth-start', content);
      if (button) button.onclick = async () => {
        button.disabled = true;
        try { renderWaiting(await API.http.authLoginStart()); }
        catch (error) { renderStart(error.message || String(error)); }
      };
      const terms = qs('#auth-provider-terms', content);
      if (terms) terms.onclick = () => showTermsModal();
      const profile = () => ({
        email: (qs('#auth-login-email', content) || {}).value || '',
        first_name: (qs('#auth-login-first', content) || {}).value || '',
        last_name: (qs('#auth-login-last', content) || {}).value || '',
        accept_terms: !!((qs('#auth-provider-accept', content) || {}).checked),
      });
      const googleButton = qs('#auth-google-start', content);
      if (googleButton && googleEnabled) googleButton.onclick = async () => {
        const details = profile();
        googleButton.disabled = true;
        try {
          if (google.available) {
            const out = await API.http.authGoogleLoginStart({ return_path: location.pathname || '/ui/', accept_terms: details.accept_terms });
            if (out.auth_url) location.href = out.auth_url;
            else throw new Error('Google не вернул ссылку входа');
          } else {
            const out = await API.http.testAuthGoogleLogin({ email: details.email, google_name: [details.first_name, details.last_name].filter(Boolean).join(' '), accept_terms: details.accept_terms });
            if (out.status === 'authenticated') { location.reload(); return; }
            if (out.challenge_id) renderWaiting({ challenge_id: out.challenge_id }, out);
          }
        } catch (error) { renderStart(error.message || String(error)); }
      };
      const emailForm = qs('#auth-email-start-form', content);
      if (emailForm && emailEnabled) emailForm.onsubmit = async (event) => {
        event.preventDefault();
        const details = profile();
        const submit = emailForm.querySelector('button[type="submit"]'); submit.disabled = true;
        try { renderEmailCode(await API.http.authEmailStart({ email: details.email }), details); }
        catch (error) { renderStart(error.message || String(error)); }
      };
      const promo = qs('#auth-open-promo', content);
      if (promo) promo.onclick = () => renderWelcomeAccess({ asOverlay: true });
    };
    const renderProfile = (challengeId, state) => {
      stopPolling();
      const profile = state.profile || {};
      content.innerHTML = loginCard(`<div class="auth-copy"><h1>Завершите профиль</h1><p>Telegram подтвердил личность. Укажите имя, фамилию и e-mail — после регистрации полный 7-дневный доступ включится автоматически.</p></div><form id="auth-profile-form" class="auth-form"><div class="field"><label for="auth-first-name">Имя</label><input id="auth-first-name" autocomplete="given-name" required maxlength="80" value="${esc(profile.first_name || '')}"></div><div class="field"><label for="auth-last-name">Фамилия</label><input id="auth-last-name" autocomplete="family-name" required maxlength="80" value="${esc(profile.last_name || '')}"></div><div class="field"><label for="auth-email">E-mail</label><input id="auth-email" type="email" autocomplete="email" required maxlength="254" value="${esc(profile.email || '')}"></div><label class="auth-terms"><input type="checkbox" id="auth-accept-terms"> <span>Я соглашаюсь с <button type="button" class="linklike" id="auth-terms-link">договором StratForge AI</button> и беру все риски на себя.</span></label><button class="btn primary auth-main-action" type="submit">Зарегистрироваться</button></form>`);
      const form = qs('#auth-profile-form', content);
      const termsLink = qs('#auth-terms-link', form);
      if (termsLink) termsLink.onclick = () => showTermsModal();
      form.onsubmit = async (event) => {
        event.preventDefault();
        if (!(qs('#auth-accept-terms', form) || {}).checked) { toast('Подтвердите согласие'); return; }
        const submit = form.querySelector('button[type="submit"]'); submit.disabled = true;
        try {
          const next = await API.http.authProfile(challengeId, {
            first_name: qs('#auth-first-name', form).value,
            last_name: qs('#auth-last-name', form).value,
            email: qs('#auth-email', form).value,
            accept_terms: true,
          });
          renderWaiting({ challenge_id: challengeId }, next);
        } catch (error) { submit.disabled = false; toast('Ошибка: ' + (error.message || error)); }
      };
    };
    const renderEmailCode = (started, profile) => {
      stopPolling();
      const testCode = String((started || {}).test_code || '');
      content.innerHTML = loginCard(`<div class="auth-copy"><h1>Подтвердите e-mail</h1><p>${testCode ? 'Development test-backend: используйте показанный одноразовый код.' : 'Код отправлен через настроенного почтового провайдера.'}</p></div>${testCode ? `<div class="finance-note"><strong>Тестовый код:</strong> <span class="mono">${esc(testCode)}</span></div>` : ''}<form id="auth-email-verify-form" class="auth-form"><div class="field"><label for="auth-email-code">Одноразовый код</label><input id="auth-email-code" inputmode="numeric" autocomplete="one-time-code" required pattern="[0-9]{6}" maxlength="6" value="${esc(testCode)}"></div><label class="auth-terms"><input type="checkbox" id="auth-email-verify-accept" ${profile.accept_terms ? 'checked' : ''}> <span>Для нового профиля я соглашаюсь с <button type="button" class="linklike" id="auth-email-verify-terms">договором StratForge AI</button>.</span></label><button class="btn primary auth-main-action" type="submit">Подтвердить e-mail</button></form><button class="btn ghost auth-main-action" id="auth-email-back" type="button">Другой способ входа</button>`);
      const form = qs('#auth-email-verify-form', content);
      const terms = qs('#auth-email-verify-terms', form); if (terms) terms.onclick = () => showTermsModal();
      form.onsubmit = async (event) => {
        event.preventDefault();
        const submit = form.querySelector('button[type="submit"]'); submit.disabled = true;
        try {
          const out = await API.http.authEmailVerify({
            challenge_id: started.challenge_id,
            code: (qs('#auth-email-code', form) || {}).value || '',
            profile: Object.assign({}, profile, {
              accept_terms: !!((qs('#auth-email-verify-accept', form) || {}).checked),
            }),
          });
          if (out.status === 'authenticated') { location.reload(); return; }
          if (out.challenge_id) { renderWaiting({ challenge_id: out.challenge_id }, out); return; }
          renderStart('Не удалось завершить вход по e-mail.');
        } catch (error) {
          submit.disabled = false;
          toast('Ошибка: ' + (error.message || error));
        }
      };
      const back = qs('#auth-email-back', content); if (back) back.onclick = () => renderStart('');
    };
    const check = async (challengeId) => {
      try {
        const state = await API.http.authLoginStatus(challengeId);
        if (state.status === 'authenticated') { stopPolling(); location.reload(); return; }
        if (state.status === 'awaiting_profile') { renderProfile(challengeId, state); return; }
        if (state.status === 'pending_owner') { renderWaiting({ challenge_id: challengeId }, state); return; }
        if (['denied', 'account_blocked', 'identity_mismatch', 'phone_mismatch'].includes(state.status)) renderStart('Вход отклонён. Обратитесь к владельцу.');
      } catch (error) {
        if (error.status === 410) renderStart('Ссылка входа истекла. Создайте новую.');
      }
    };
    const renderWaiting = (login, knownState) => {
      const challengeId = login.challenge_id;
      const status = (knownState || {}).status || 'created';
      if (status === 'awaiting_profile') { renderProfile(challengeId, knownState); return; }
      const pendingOwner = status === 'pending_owner';
      const manual = login.manual_command || (login.code ? `/login ${login.code}` : '');
      const botUrl = pendingOwner ? '' : String(login.bot_url || '');
      const qrSvg = pendingOwner ? '' : String(login.qr_svg || '');
      // The phone is the second device: scanning a QR with the normal camera
      // is the primary path, so nothing here opens a popup window. On the
      // phone itself the same deep link is one tap away.
      const webFallback = pendingOwner ? '' : String(login.web_fallback_url || login.bot_url || '');
      // The QR carries the tg: scheme so a phone camera opens Telegram itself.
      // That scheme is a dead end without Telegram installed, so the https
      // link stays visible right underneath as the escape hatch.
      const scanBlock = qrSvg
        ? `<div class="auth-qr"><div class="auth-qr-frame">${qrSvg}</div><p class="auth-qr-copy">Наведите камеру телефона — откроется Telegram и наш бот. Нажмите <strong>«Подтвердить вход»</strong>, и эта страница войдёт сама.</p><div class="auth-qr-life" id="auth-qr-life"></div>${webFallback ? `<a class="auth-qr-fallback" id="auth-qr-web" href="${esc(webFallback)}" rel="noopener">Telegram не установлен? Открыть в браузере</a>` : ''}</div>`
        : '';
      const appUrl = pendingOwner ? '' : String(login.app_url || '');
      // The href stays the https link so the control degrades to something
      // real without JS, and so a long-press still offers a working target.
      const sameDevice = botUrl
        ? `<a class="btn ghost auth-main-action" id="auth-open-telegram" href="${esc(botUrl)}" rel="noopener">Открыть в Telegram</a><div class="row-sub" id="auth-telegram-hint"></div>`
        : '';
      content.innerHTML = loginCard(`<div class="auth-copy"><h1>${pendingOwner ? 'Ожидается решение владельца' : 'Вход через Telegram'}</h1><p>${pendingOwner ? 'Аккаунт будет активирован только после личного подтверждения владельцем. Это правило одинаково для Telegram, Google и e-mail.' : 'Одно подтверждение в Telegram — и вход завершится здесь автоматически. Отправлять контакт не нужно.'}</p></div>${scanBlock}${sameDevice}${manual ? `<details class="auth-manual-fallback"><summary>Другой способ · ввести код вручную</summary><div class="finance-note">Отправьте боту команду:<br><span class="mono">${esc(manual)}</span> <button class="btn sm ghost" id="auth-copy-code" type="button">Копировать</button></div></details>` : ''}<div class="auth-wait"><span class="spinner"></span><span>Ждём подтверждения…</span></div><button class="btn ghost" id="auth-restart">Другой способ входа</button>`);
      const copy = qs('#auth-copy-code', content);
      if (copy) copy.onclick = async () => {
        try { await navigator.clipboard.writeText(manual); toast('Код скопирован'); }
        catch (e) { toast(manual); }
      };
      const restart = qs('#auth-restart', content); if (restart) restart.onclick = () => renderStart('');
      // Reach an installed Telegram directly instead of routing through a web
      // page. `tg:` has no fallback of its own, so watch for the app taking
      // over: if the tab is still here and visible shortly after, the scheme
      // went nowhere and the https link is used instead. A permission prompt
      // the OS or browser shows is left alone -- it just delays the handover,
      // which is why the check is on visibility rather than on a timer alone.
      const openTelegram = qs('#auth-open-telegram', content);
      if (openTelegram && appUrl) openTelegram.onclick = (event) => {
        event.preventDefault();
        const hint = qs('#auth-telegram-hint', content);
        let handedOver = false;
        const noteHandover = () => { handedOver = true; };
        window.addEventListener('pagehide', noteHandover, { once: true });
        window.addEventListener('blur', noteHandover, { once: true });
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'hidden') noteHandover();
        }, { once: true });
        try { location.href = appUrl; } catch (e) { handedOver = false; }
        setTimeout(() => {
          if (handedOver || document.visibilityState === 'hidden') return;
          if (hint) hint.textContent = 'Telegram не открылся — продолжаем в браузере.';
          location.href = botUrl;
        }, 1400);
      };
      // A QR is a bearer token with a short life. When it lapses, replace it
      // in place rather than leaving a code on screen that no longer works.
      stopPolling();
      polling = setInterval(() => check(challengeId), 2000);
      const ttl = Number(login.expires_in_sec || 0);
      if (ttl > 0 && qrSvg) {
        const deadline = Date.now() + ttl * 1000;
        qrTick = setInterval(async () => {
          const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
          const life = qs('#auth-qr-life', content);
          if (life) life.textContent = left ? `Код действует ещё ${left} с` : 'Обновляем код…';
          if (left > 0) return;
          stopPolling();
          try { renderWaiting(await API.http.authLoginStart()); }
          catch (e) { renderStart('Не удалось обновить код входа. Попробуйте снова.'); }
        }, 1000);
      }
      check(challengeId);
    };
    let callbackChallenge = '';
    try {
      const params = new URLSearchParams(location.search || '');
      callbackChallenge = String(params.get('auth_challenge') || '');
      if (callbackChallenge) {
        params.delete('auth_challenge');
        history.replaceState({}, '', location.pathname + (params.toString() ? '?' + params.toString() : '') + location.hash);
      }
    } catch (e) { callbackChallenge = ''; }
    if (callbackChallenge) renderWaiting({ challenge_id: callbackChallenge }, { status: 'pending_owner' });
    else renderStart(initialMessage);
    API.http.authProviders({ retries: 0 }).then((out) => {
      providers = (out && out.providers) || providers;
      if (!callbackChallenge && qs('#auth-provider-start', content)) renderStart(initialMessage);
    }).catch(() => { /* configured current providers remain available */ });
  }

  async function runReady() {
    READY._done = true;
    const fns = READY.splice(0);
    for (const fn of fns) {
      try { await fn(); }
      catch (e) { if (e && e.name === 'AbortError') continue; reportError(e); }
    }
    enhanceA11y(document);
  }

  // Centralised UI error surface (used by pages' loading/error states too).
  function isAbortError(err) {
    if (!err) return false;
    if (err.name === 'AbortError') return true;
    const message = String(err.message || err);
    return /AbortError|signal is aborted/i.test(message);
  }

  function reportError(err) {
    // Page cleanup deliberately aborts in-flight requests. Some Chromium
    // versions wrap that DOMException as a plain Error, so checking only
    // `name` leaks a false red console error during normal navigation.
    if (isAbortError(err)) return;
    console.error('[UI]', err);
    // A stale/missing session used to be swallowed here, making every button
    // look frozen.  Tell the user what happened and expose the sign-in action.
    if (isGuest() && err && (err.status === 401 || err.status === 403)) {
      toast('Нужно войти. Ваши чаты и данные сохранены.');
      renderTelegramLogin('');
      return;
    }
    const msg = (err && err.message) ? err.message : String(err);
    toast('Ошибка: ' + msg.slice(0, 120));
  }

  // CSP-safe global click handling for declarative actions in injected HTML.
  function wireDelegatedActions() {
    document.addEventListener('click', (e) => {
      const t = e.target.closest('[data-toast]');
      if (t) { toast(t.getAttribute('data-toast')); return; }
      const c = e.target.closest('[data-close-drawer]');
      if (c) { closeDrawer(); }
      const size = e.target.closest('[data-drawer-size]');
      if (size) {
        const drawerNode = qs('.drawer');
        if (drawerNode) setDrawerSize(drawerNode, size.dataset.drawerSize);
      }
    });
  }

  // ---- live system status chips ---------------------------------------------
  function setChip(node, state, label, title) {
    if (!node) return;
    node.classList.remove('ok', 'warn', 'bad', 'off');
    node.classList.add(state);
    node.innerHTML = `<span class="dot"></span>${esc(label)}`;
    if (title) node.title = title;
  }
  function setSelectedAccount(name, notify) {
    const next = AuroraDomain.selectAccount(runtimeAccounts, name);
    selectedAccount = next;
    try {
      if (next) localStorage.setItem(AuroraDomain.ACCOUNT_KEY, next.account_name);
      else localStorage.removeItem(AuroraDomain.ACCOUNT_KEY);
    } catch (e) { /* storage may be disabled */ }
    const chip = qs('#chip-account');
    if (next) {
      const mode = next.is_live ? 'LIVE' : (next.account_mode || 'paper');
      setChip(chip, next.is_live ? 'bad' : 'ok', `${next.account_name} · ${mode}`, `${next.display_name || next.account_name} · ${next.connection_status || 'статус неизвестен'} · NetLiq ${money(next.net_liquidation || 0)}`);
    } else setChip(chip, 'off', 'Счёт недоступен', 'Runtime account list пуст');
    if (notify !== false) window.dispatchEvent(new CustomEvent('nt-account-change', { detail: next }));
    return next;
  }

  function getSelectedAccount() { return selectedAccount; }

  function accountMenu(anchor) {
    if (!runtimeAccounts.length) { toast('Список счетов недоступен'); return; }
    menu(anchor, runtimeAccounts.map(account => ({
      icon: 'wallet',
      label: `${account.account_name} · ${account.is_live ? 'LIVE' : (account.account_mode || 'paper')}`,
      danger: !!account.is_live,
      onClick: () => setSelectedAccount(account.account_name, true),
    })));
  }

  function wireSystemStatus() {
    const ntC = qs('#chip-nt'), brC = qs('#chip-bridge'), lmC = qs('#chip-lm'), mkC = qs('#chip-market'), accC = qs('#chip-account');
    const tickMarket = () => { const m = AuroraDomain.marketStatus(new Date()); setChip(mkC, m.state, m.label, m.title); };
    tickMarket(); setInterval(tickMarket, 30000);
    if (accC) accC.onclick = (e) => { e.stopPropagation(); accountMenu(accC); };
    try { const stored = localStorage.getItem(AuroraDomain.ACCOUNT_KEY); if (stored) setChip(accC, 'off', `${stored} · проверка…`, 'Проверяю account в актуальном runtime list'); } catch (e) { /* ignore */ }
    if (!window.API || API.config.offline) {
      setChip(ntC, 'off', 'NinjaTrader', 'демо-превью (без backend)');
      setChip(brC, 'off', 'Bridge', 'демо-превью (без backend)');
      setChip(lmC, 'off', 'LM Studio', 'демо-превью (без backend)');
      setChip(accC, 'off', 'Счёт недоступен', 'backend не подключён');
      return;
    }
    async function refresh() {
      const healthTask = API.http.health().then(h => {
        const connectorState = h.connector_confirmation_state || '';
        const connectorGraded = !!connectorState;
        const age = Math.round(h.connector_heartbeat_age_sec || 0);
        if (connectorGraded && h.connector_confirmed_live) {
          setChip(ntC, 'ok', 'NinjaTrader · LIVE', `последний подписанный heartbeat ${age}с назад`);
        } else if (connectorGraded && h.connector_functional) {
          setChip(ntC, 'warn', 'NinjaTrader · ожидание', `ожидается heartbeat; последнее подтверждение ${age}с назад`);
        } else if (connectorGraded) {
          setChip(ntC, 'bad', 'NinjaTrader · OFF', h.connector_heartbeat_age_sec == null ? 'NinjaTrader не подтверждён' : `heartbeat устарел (${age}с)`);
        } else {
          setChip(ntC, h.ninjatrader_running ? 'ok' : 'bad', h.ninjatrader_running ? 'NinjaTrader · LIVE' : 'NinjaTrader · OFF', h.ninjatrader_running ? 'локальный процесс NinjaTrader запущен' : 'локальный процесс NinjaTrader не запущен');
        }
      }).catch(() => setChip(ntC, 'off', 'NinjaTrader', 'статус недоступен'));
      const bridgeTask = API.http.runtimeHeartbeat().then(hb => {
        // functional_live is the Connector transport's word. A local runtime
        // heartbeat does not carry it and must not be judged by its absence:
        // where the field is missing the old, correct local rule applies.
        const graded = Object.prototype.hasOwnProperty.call(hb, 'functional_live');
        const confirmationGraded = Object.prototype.hasOwnProperty.call(hb, 'confirmed_live');
        const ok = hb.present && hb.fresh && (!graded || hb.functional_live) && (!confirmationGraded || hb.confirmed_live);
        const grace = hb.present && hb.fresh && confirmationGraded && hb.functional_live && !hb.confirmed_live;
        const heartbeatOnly = hb.present && hb.fresh && graded && !hb.functional_live;
        const title = ok
          ? `мост и account snapshot активны · ${Math.round(hb.age_sec || 0)}с · v${hb.exporter_version || '?'}`
          : (grace
            ? `ожидается следующий heartbeat; последнее подтверждение ${Math.round(hb.age_sec || 0)}с назад`
            : (heartbeatOnly
            ? 'heartbeat активен, но свежий account snapshot отсутствует'
            : (hb.present ? `данные устарели (${Math.round(hb.age_sec || 0)}с)` : 'мост не отвечает')));
        setChip(brC, ok ? 'ok' : (hb.present ? 'warn' : 'bad'), 'Bridge', title);
      }).catch(() => setChip(brC, 'off', 'Bridge', 'статус недоступен'));
      const lmTask = API.http.aiLmStudioHealth().then(lm => {
        const st = lm.ready ? 'ok' : (lm.available ? 'warn' : 'off');
        setChip(lmC, st, 'LM Studio', lm.message_ru || (lm.ready ? 'модели готовы' : 'недоступна'));
      }).catch(() => setChip(lmC, 'off', 'LM Studio', 'статус недоступен'));
      const accountsTask = API.http.runtimeAccounts().then(accounts => {
        const listed = (accounts.accounts || accounts.online_accounts || []).filter(account => !account.is_system);
        let preferred = selectedAccount && selectedAccount.account_name;
        if (!preferred) { try { preferred = localStorage.getItem(AuroraDomain.ACCOUNT_KEY); } catch (e) { /* ignore */ } }
        const confirmationGraded = Object.prototype.hasOwnProperty.call(accounts, 'confirmed_live');
        if (confirmationGraded && !accounts.confirmed_live) {
          runtimeAccounts = [];
          selectedAccount = null;
          const lastKnown = AuroraDomain.selectAccount(listed, preferred);
          const grace = accounts.heartbeat_confirmation_state === 'grace';
          setChip(accC, grace ? 'warn' : 'bad', lastKnown ? `${lastKnown.account_name} · ${grace ? 'ожидание' : 'OFF'}` : 'Счёт недоступен', lastKnown ? `последние подтверждённые данные; ${grace ? 'ожидается heartbeat' : 'NinjaTrader offline'}` : 'свежий account snapshot отсутствует');
          window.dispatchEvent(new CustomEvent('nt-account-change', { detail: null }));
        } else {
          runtimeAccounts = listed;
          setSelectedAccount(preferred, false);
        }
      }).catch(() => { runtimeAccounts = []; selectedAccount = null; setChip(accC, 'off', 'Счёт недоступен', 'runtime accounts endpoint недоступен'); });
      await Promise.allSettled([healthTask, bridgeTask, lmTask, accountsTask]);
    }
    poll(refresh, 15000);
  }

  // Run a backend action with pending → success/error toasts (success only after OK).
  async function action(pendingMsg, fn, okMsg) {
    if (!window.API || API.config.offline) { toast((pendingMsg || 'Действие') + ' — недоступно в офлайн-превью'); return; }
    toast((pendingMsg || 'Выполняю') + '…');
    try { const r = await fn(); if (okMsg) toast(okMsg); return r; }
    catch (e) { reportError(e); throw e; }
  }

  async function showDiagnostics() {
    if (!window.API || API.config.offline) { toast('Диагностика — недоступно в офлайн-превью'); return; }
    const d = drawer('<h3>Диагностика системы</h3>', '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>');
    const body = qs('.drawer-b', d);
    try {
      const diag = await API.http.diagnostics();
      const cat = diag.catalog || {};
      body.innerHTML = `
        <div class="list">
          <div class="row"><div class="row-main"><div class="row-title">NinjaTrader</div></div><div class="row-val ${diag.ninjatrader_running ? 'pos' : 'neg'}">${diag.ninjatrader_running ? 'запущен' : 'не запущен'}</div></div>
          <div class="row"><div class="row-main"><div class="row-title">Стратегий в каталоге</div></div><div class="row-val">${cat.strategies_count != null ? cat.strategies_count : '—'}</div></div>
          <div class="row"><div class="row-main"><div class="row-title">Инструментов</div></div><div class="row-val">${cat.instruments_count != null ? cat.instruments_count : '—'}</div></div>
        </div>
        <h4 style="margin:16px 0 8px">Журнал моста (хвост)</h4>
        <pre class="logbox">${esc((diag.bridge_log_tail || []).slice(-25).join('\n'))}</pre>`;
    } catch (e) { renderError(body, e, showDiagnostics); }
  }

  function telegramRightRow(label, ok) {
    return `<div class="row"><div class="row-main"><div class="row-title">${esc(label)}</div></div><div class="row-val ${ok ? 'pos' : 'neg'}">${ok ? 'да' : 'нет'}</div></div>`;
  }

  function showDesignSettings() {
    const groups = [
      { key: 'theme', title: 'Тема', get: loadTheme, set: (v) => setTheme(v), opts: [
        ['dark', 'Тёмная', 'Тёмный premium-интерфейс (по умолчанию)'],
        ['light', 'Светлая', 'Светлый интерфейс'],
        ['auto', 'Как в системе', 'Следовать теме операционной системы'],
      ] },
      { key: 'bg', title: 'Анимированный фон', get: loadBg, set: (v) => setBg(v), opts: [
        ['subtle', 'Спокойный', 'Мягкое свечение и редкие частицы (по умолчанию)'],
        ['medium', 'Насыщенный', 'Заметнее волны и частицы'],
        ['off', 'Выключен', 'Полностью статичный фон'],
      ] },
      { key: 'density', title: 'Плотность интерфейса', get: loadDensity, set: (v) => setDensity(v), opts: [
        ['comfortable', 'Просторная', 'Больше воздуха между блоками (по умолчанию)'],
        ['compact', 'Компактная', 'Плотнее — больше данных на экране'],
      ] },
      { key: 'motion', title: 'Уменьшить движение', get: loadMotion, set: (v) => setMotion(v), opts: [
        ['auto', 'Авто', 'Следовать системной настройке (по умолчанию)'],
        ['off', 'Разрешить анимации', 'Не ограничивать движение'],
        ['on', 'Остановить движение', 'Замереть фон и лишние анимации'],
      ] },
    ];
    const d = drawer('<h3>Настройки дизайна</h3>', '<div class="state-loading"><span class="spinner"></span></div>');
    const render = () => {
      const body = qs('.drawer-b', d);
      body.innerHTML = groups.map((g, gi) => {
        const cur = g.get();
        return `<div class="settings-group">
          <div class="settings-group-title">${esc(g.title)}</div>
          <div class="settings-opts">${g.opts.map(o => `
            <button class="row theme-opt ${o[0] === cur ? 'active' : ''}" data-group="${gi}" data-opt="${esc(o[0])}">
              <div class="row-main"><div class="row-title">${esc(o[1])}</div><div class="row-sub">${esc(o[2])}</div></div>
              <div class="row-val">${o[0] === cur ? icon('check') : ''}</div>
            </button>`).join('')}</div>
        </div>`;
      }).join('') + `<div class="settings-note">Настройки сохраняются в этом браузере и действуют на всех страницах. Анимированный фон автоматически облегчается на слабых устройствах и останавливается при сворачивании вкладки.</div>`;
      qsa('[data-opt]', body).forEach(b => b.addEventListener('click', () => {
        groups[+b.dataset.group].set(b.dataset.opt);
        toast('Настройка применена');
        render();
      }));
    };
    render();
  }

  async function showTelegram() {
    if (!window.API || API.config.offline) { toast('Telegram недоступен в офлайн-превью'); return; }
    const d = drawer('<h3>Telegram</h3>', '<div class="state-loading"><span class="spinner"></span>Проверка подключения…</div>');
    const body = qs('.drawer-b', d);

    async function refresh() {
      try {
        const status = await API.http.telegramStatus();
        let group = null;
        let accounts = null;
        if (status.token_configured) { try { group = await API.http.telegramGroupStatus(); } catch (e) { group = null; } }
        try { accounts = await API.http.authUsers(); } catch (e) { accounts = null; }
        const connectionLabel = status.configured ? 'подключён' : status.token_configured ? 'нужно подключить чат' : 'не настроен';
        const botLabel = status.bot_username ? `@${status.bot_username}` : (status.bot_name || 'бот не проверен');
        const settingRows = (status.setting_definitions || []).map(item => {
          const checked = status.settings && status.settings[item.key];
          const unavailable = item.key !== 'enabled' && !status.configured;
          return `<label class="telegram-setting ${unavailable ? 'disabled' : ''}">
            <span class="telegram-setting-copy"><strong>${esc(item.label)}</strong><small>${esc(item.description)}</small></span>
            <input type="checkbox" data-telegram-setting="${esc(item.key)}" ${checked ? 'checked' : ''} ${unavailable ? 'disabled' : ''}>
            <span class="telegram-switch" aria-hidden="true"></span>
          </label>`;
        }).join('');

        body.innerHTML = `
          <section class="telegram-card">
            <div class="flex between"><div><div class="section-title">Подключение</div><div class="telegram-bot-name">${esc(botLabel)}</div></div><span class="badge ${status.configured ? 'live' : status.token_configured ? 'pending' : 'archived'}"><span class="dot"></span>${esc(connectionLabel)}</span></div>
            ${status.chat_label ? `<div class="row-sub">Чат: ${esc(status.chat_label)}</div>` : ''}
            ${status.last_delivery_at_utc ? `<div class="row-sub">Последняя отправка: ${esc(status.last_delivery_at_utc)}</div>` : ''}
            ${status.last_error ? `<div class="finance-note telegram-error"><strong>Последняя ошибка:</strong> ${esc(status.last_error)}</div>` : ''}
          </section>

          <section class="telegram-card">
            <div class="section-title">Токен бота</div>
            <div class="field"><label for="telegram-token">${status.token_configured ? 'Новый токен (текущий скрыт)' : 'Токен от BotFather'}</label><input id="telegram-token" type="password" autocomplete="new-password" placeholder="123456789:AA…"></div>
            <div class="flex wrap gap-sm"><button class="btn ${status.token_configured ? '' : 'primary'}" id="telegram-save-token">${status.token_configured ? 'Заменить токен' : 'Сохранить и проверить'}</button>${status.bot_username ? `<a class="btn ghost" href="https://t.me/${esc(status.bot_username)}" target="_blank" rel="noopener">Открыть бота</a>` : ''}</div>
            <div class="row-sub">Токен сохраняется только в локальном gitignored-хранилище backend и никогда не возвращается в браузер.</div>
          </section>

          ${status.token_configured && !status.chat_configured ? `<section class="telegram-card">
            <div class="section-title">Подключение личного чата</div>
            <p class="muted mt-0">Создайте одноразовую ссылку, откройте её и нажмите Start в Telegram.</p>
            <div id="telegram-pair-result"></div>
            <div class="flex wrap gap-sm"><button class="btn primary" id="telegram-pair-start">Создать ссылку</button><button class="btn" id="telegram-pair-complete" ${status.pairing_active ? '' : 'disabled'}>Проверить подключение</button></div>
          </section>` : ''}

          ${status.token_configured ? `<section class="telegram-card">
            <div class="flex between"><div class="section-title">Группа с темами (StratForge AI Control)</div><span class="badge ${group && group.configured ? (group.rights && group.rights.ready ? 'live' : 'pending') : 'archived'}"><span class="dot"></span>${group && group.configured ? (group.rights && group.rights.ready ? 'готова' : 'нужны права') : 'не привязана'}</span></div>
            <p class="muted mt-0">Каждый чат приложения показывается отдельной темой группы. Добавьте бота <strong>@${esc(status.bot_username || 'StratForgeAI_bot')}</strong> в супергруппу с включёнными Topics и сделайте его админом с правом «Управление темами».</p>
            ${group && !group.configured ? `<div class="finance-note"><strong>Как настроить:</strong><br>
              1. Откройте группу → Добавить участников → найдите @${esc(status.bot_username || 'StratForgeAI_bot')} → добавьте.<br>
              2. Откройте профиль бота в группе → Назначить администратором → включите «Управление темами».<br>
              3. Убедитесь, что в группе включены Topics (Групп. темы) в настройках группы.<br>
              4. <strong>Бот обнаружит группу автоматически</strong> при следующем сообщении (≤30 сек) — или введите ID вручную ниже.</div>` : ''}
            ${group && group.configured ? `
              <div class="row-sub">Группа: ${esc(group.group_title || group.group_id || '')}${group.topics_count != null ? ` · тем: ${group.topics_count}` : ''}</div>
              <div class="list" style="margin:8px 0">
                ${telegramRightRow('Темы включены (is_forum)', group.rights && group.rights.is_forum)}
                ${telegramRightRow('Бот — администратор', group.rights && group.rights.is_admin)}
                ${telegramRightRow('Может управлять темами', group.rights && group.rights.can_manage_topics)}
                ${telegramRightRow('Может отправлять сообщения', group.rights && group.rights.can_post_messages)}
              </div>
              ${group.rights && group.rights.error ? `<div class="finance-note telegram-error">${esc(group.rights.error)}</div>` : ''}
              <div class="flex wrap gap-sm"><button class="btn" id="telegram-group-recheck">Проверить права</button><button class="btn danger" id="telegram-group-disconnect">Отвязать группу</button></div>
            ` : `
              <div class="field"><label for="telegram-group-id">ID супергруппы (необязательно — бот обнаружит автоматически)</label><input id="telegram-group-id" inputmode="numeric" placeholder="-1001234567890"></div>
              <div class="flex wrap gap-sm"><button class="btn primary" id="telegram-group-connect">Привязать группу вручную</button></div>
              <div class="row-sub">ID: откройте группу в Telegram Web → скопируйте число из URL (начинается с -100...). Или дождитесь автоопределения после добавления бота.</div>
            `}
          </section>` : ''}

          <section class="telegram-card">
            <div class="flex between"><div><div class="section-title">Аккаунты и вход</div><div class="row-sub">${accounts ? `${(accounts.users || []).filter(user => user.status === 'active').length} активных · ${(accounts.users || []).filter(user => user.status === 'pending').length} ожидают` : 'статус недоступен'}</div></div><button class="btn" id="telegram-open-users">Управление пользователями</button></div>
            <div class="finance-note"><strong>Новый порядок:</strong> пользователь нажимает «Войти через Telegram», подтверждает свой контакт и заполняет имя, фамилию и e-mail. После подтверждения личности аккаунт активируется автоматически с полным пробным доступом на 7 дней.</div>
          </section>

          <section class="telegram-card">
            <div class="section-title">Уведомления</div>
            <div class="telegram-settings">${settingRows}</div>
          </section>

          <div class="flex wrap gap-sm">${status.configured ? '<button class="btn primary" id="telegram-test">Отправить тест</button>' : ''}</div>`;

        const saveToken = qs('#telegram-save-token', body);
        if (saveToken) saveToken.onclick = async () => {
          const input = qs('#telegram-token', body);
          const token = input && input.value.trim();
          if (!token) { toast('Введите новый токен Telegram'); return; }
          saveToken.disabled = true;
          try {
            await API.http.telegramSaveToken(token);
            input.value = '';
            toast('Токен проверен и сохранён');
            await refresh();
          } catch (error) { reportError(error); saveToken.disabled = false; }
        };

        const pairStart = qs('#telegram-pair-start', body);
        if (pairStart) pairStart.onclick = async () => {
          pairStart.disabled = true;
          try {
            const pair = await API.http.telegramPairStart();
            const result = qs('#telegram-pair-result', body);
            result.innerHTML = `<div class="telegram-pair"><div>Код: <strong>${esc(pair.code)}</strong></div><a class="btn primary" href="${esc(pair.bot_url)}" target="_blank" rel="noopener">Открыть Telegram и нажать Start</a><div class="row-sub">Ссылка действует 10 минут.</div></div>`;
            const complete = qs('#telegram-pair-complete', body);
            if (complete) complete.disabled = false;
          } catch (error) { reportError(error); pairStart.disabled = false; }
        };

        const pairComplete = qs('#telegram-pair-complete', body);
        if (pairComplete) pairComplete.onclick = async () => {
          pairComplete.disabled = true;
          try { await API.http.telegramPairComplete(); toast('Чат Telegram подключён'); await refresh(); }
          catch (error) { reportError(error); pairComplete.disabled = false; }
        };

        const groupConnect = qs('#telegram-group-connect', body);
        if (groupConnect) groupConnect.onclick = async () => {
          const input = qs('#telegram-group-id', body);
          const gid = input && input.value.trim();
          if (!gid) { toast('Введите ID группы'); return; }
          groupConnect.disabled = true;
          try { await API.http.telegramConfigureGroup(gid); toast('Группа привязана'); await refresh(); }
          catch (error) { reportError(error); groupConnect.disabled = false; }
        };

        const openUsers = qs('#telegram-open-users', body);
        if (openUsers) openUsers.onclick = () => { closeDrawer(); openAdminPanel('users'); };
        const groupRecheck = qs('#telegram-group-recheck', body);
        if (groupRecheck) groupRecheck.onclick = async () => { groupRecheck.disabled = true; try { await refresh(); } catch (e) { groupRecheck.disabled = false; } };
        const groupDisconnect = qs('#telegram-group-disconnect', body);
        if (groupDisconnect) groupDisconnect.onclick = async () => {
          if (!confirm('Отвязать группу и удалить карту тем? Личный чат останется.')) return;
          groupDisconnect.disabled = true;
          try { await API.http.telegramDisconnectGroup(); toast('Группа отвязана'); await refresh(); }
          catch (error) { reportError(error); groupDisconnect.disabled = false; }
        };

        qsa('[data-telegram-setting]', body).forEach(input => {
          input.onchange = async () => {
            input.disabled = true;
            try { await API.http.telegramSettings({ [input.dataset.telegramSetting]: input.checked }); toast('Настройка сохранена'); }
            catch (error) { input.checked = !input.checked; reportError(error); }
            finally { input.disabled = false; }
          };
        });

        const test = qs('#telegram-test', body);
        if (test) test.onclick = async () => {
          test.disabled = true;
          try { await API.http.telegramTest(); toast('Тестовое сообщение отправлено'); await refresh(); }
          catch (error) { reportError(error); test.disabled = false; }
        };

        const disconnect = qs('#telegram-disconnect', body);
        if (disconnect) disconnect.onclick = async () => {
          if (!confirm('Удалить локальный токен, привязку чата и выключить Telegram?')) return;
          disconnect.disabled = true;
          try { await API.http.telegramDisconnect(); toast('Telegram отключён'); await refresh(); }
          catch (error) { reportError(error); disconnect.disabled = false; }
        };
      } catch (error) { renderError(body, error, refresh); }
    }

    await refresh();
  }

  function adminCapabilities() {
    return (CURRENT_AUTH && CURRENT_AUTH.admin_capabilities) || {};
  }

  function hasAdminCapability(capability) {
    return !!(CURRENT_AUTH && (CURRENT_AUTH.is_owner || adminCapabilities()[capability] === true));
  }


  // ---- Environment registry (Phase 5) ---------------------------------------
  // The probe path can only describe environments that answer an HTTP call
  // right now, which permanently excluded LOCAL behind NAT and blanked out
  // everything about any environment that happened to be unreachable. The
  // registry is the other direction: environments publish, and what they last
  // published is kept and shown with the time it was said.
  function environmentAge(row) {
    const age = row.age_sec;
    if (age === null || age === undefined) return '';
    if (age < 60) return `${age} с назад`;
    if (age < 3600) return `${Math.round(age / 60)} мин назад`;
    if (age < 86400) return `${Math.round(age / 3600)} ч назад`;
    return `${Math.round(age / 86400)} сут назад`;
  }

  function environmentStateBadge(row) {
    const label = {
      live: 'на связи', stale: 'молчит', offline: 'офлайн', never_seen: 'не отчитывалась',
    }[row.state] || row.state;
    const cls = { live: 'live', stale: 'pending', offline: 'failed', never_seen: 'archived' }[row.state] || 'archived';
    return `<span class="badge ${cls}">${esc(label)}</span>`;
  }

  function environmentCompareHtml(payload) {
    const rows = (payload && payload.environments) || [];
    const compare = (payload && payload.compare) || {};
    const known = rows.filter(row => row.metadata_known);
    if (!known.length) {
      return `<section class="cab-card"><h4>Сравнение сред</h4>
        <p class="cab-sub">Ни одна среда ещё не присылала heartbeat. Сравнивать нечего — это отсутствие данных, а не расхождение.</p></section>`;
    }

    const parity = compare.canary_production_parity || {};
    let parityHtml;
    if (!parity.known) {
      const why = parity.reason === 'artifact_not_reported'
        ? 'артефакт не сообщён' : 'отчитались не обе среды';
      parityHtml = `<div class="admin-env-warnings"><div>Паритет Canary / Production неизвестен: ${esc(why)}.</div></div>`;
    } else {
      // A stale reading is still shown, but never as if it were current.
      const freshness = parity.both_current
        ? 'по актуальным данным'
        : `по последним данным: Canary ${esc(parity.canary_as_of_utc || '—')}, Production ${esc(parity.production_as_of_utc || '—')}`;
      parityHtml = `<div class="finance-note"><strong>${parity.match ? 'Canary и Production на одном артефакте' : 'Артефакты Canary и Production различаются'}</strong> — ${freshness}.</div>`;
    }

    const header = known.map(row => `<th>${esc(row.environment.toUpperCase())}</th>`).join('');
    const body = ((compare.fields) || []).map(field => {
      const readable = {
        ready: 'готов', degraded: 'деградация', not_ready: 'не готов',
        hub: 'hub', consumer: 'consumer', disabled: 'выключено',
        ok: 'ок', unavailable: 'недоступен',
      };
      const cells = known.map(row => {
        const raw = field.values[row.environment];
        const value = readable[raw] || raw;
        const missing = (field.missing || []).includes(row.environment);
        // Missing and different are rendered differently on purpose: calling
        // absent data a mismatch teaches the reader to ignore the panel.
        const text = missing ? 'не сообщено' : String(value === 0 ? '0' : (value || '—'));
        const short = text.length > 20 ? text.slice(0, 16) + '…' : text;
        return `<td class="mono${missing ? ' cab-sub' : ''}" title="${esc(text)}">${esc(short)}</td>`;
      }).join('');
      return `<tr class="${field.differs ? 'is-diff' : ''}"><th scope="row">${esc(field.label)}${field.differs ? ' ⚠' : ''}</th>${cells}</tr>`;
    }).join('');

    const stateRow = known.map(row => `<td>${environmentStateBadge(row)}<div class="cab-sub">${esc(environmentAge(row))}</div></td>`).join('');

    return `<section class="cab-card"><h4>Сравнение сред</h4>
      ${parityHtml}
      <div class="table-scroll"><table class="admin-env-compare">
        <thead><tr><th></th>${header}</tr></thead>
        <tbody><tr><th scope="row">Связь</th>${stateRow}</tr>${body}</tbody>
      </table></div>
      <p class="cab-sub">Значения — то, что среда сообщила о себе в последний раз, с отметкой времени. Среда, переставшая отвечать, не становится средой с неизвестной версией.</p>
    </section>`;
  }

  async function renderEnvironmentCompareInto(node) {
    if (!node) return;
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка реестра сред…</div>';
    try {
      node.innerHTML = environmentCompareHtml(await API.http.adminEnvironments());
    } catch (e) {
      renderError(node, e, () => renderEnvironmentCompareInto(node));
    }
  }

  async function probeEnvironmentTarget(target, card) {
    const data = await API.http.adminEnvironmentProbe(target.environment);
    // Merged into the target the caller already holds; the card is repainted
    // slot by slot afterwards, so nothing the reader opened is thrown away.
    Object.assign(target, data.target || {});
    return target;
  }

  function openEnvironmentOrigin(target) {
    const origin = target.current ? location.origin : String(target.origin || '');
    if (!origin) return;
    // Deliberately no query string, Telegram initData, cookies, CSRF token or
    // localStorage payload. A different origin starts its own authentication.
    window.open(origin + '/ui/', '_blank', 'noopener,noreferrer');
  }

  // The Environment Switcher is the release control panel, not a list of links.
  // It used to lead with a probe button, a "просмотреть переход" button and an
  // engineering comparison table, so the owner had to assemble the workflow
  // themselves. The three stages now read in the order they happen, each card
  // carries the one action available at that stage, and the identifiers live
  // behind a disclosure.
  // The stages of each single action, and the ledger state that means the
  // stage is currently running. Derived from what the release ledger reports,
  // so the progress shown is the progress that happened.
  const DELIVER_STAGES = [
    { key: 'candidate', label: 'Создание кандидата', running: [''] },
    { key: 'build', label: 'Сборка', running: ['draft', 'build_failed'] },
    { key: 'verify', label: 'Проверка', running: ['built'] },
    { key: 'deploy', label: 'Развёртывание', running: ['signed', 'canary_deploying', 'canary_failed'] },
    { key: 'acceptance', label: 'Canary checks / acceptance', running: ['canary_checking'] },
    { key: 'done', label: 'Готово', running: [] },
  ];
  const PUBLISH_STAGES = [
    { key: 'approve', label: 'Подтверждение', running: ['canary_passed'] },
    { key: 'deploy', label: 'Развёртывание', running: ['approved_for_production', 'production_scheduled', 'production_deploying'] },
    { key: 'readiness', label: 'Readiness', running: [] },
    { key: 'smoke', label: 'Smoke', running: [] },
    { key: 'done', label: 'Готово', running: [] },
  ];

  function progressHtml(plan, activeKey, finished) {
    const activeIndex = plan.findIndex(row => row.key === activeKey);
    return '<div class="pub-stages">' + plan.map((row, index) => {
      let state = 'not_started';
      if (finished) state = 'passed';
      else if (activeIndex >= 0 && index < activeIndex) state = 'passed';
      else if (index === activeIndex) state = 'running';
      return '<span class="pub-stage is-' + state + '">'
        + (state === 'running' ? '<span class="spinner sm"></span> '
          : (state === 'passed' ? '✓ ' : '· '))
        + esc(row.label) + '</span>';
    }).join('<span class="pub-sep">→</span>') + '</div>';
  }

  function finalStagesHtml(stages) {
    const icon = { passed: '✓', failed: '✕', not_started: '·' };
    return '<div class="pub-stages">' + (stages || []).map(row =>
      '<span class="pub-stage is-' + esc(row.state) + '">' + (icon[row.state] || '·')
      + ' ' + esc(row.label) + '</span>').join('<span class="pub-sep">→</span>') + '</div>';
  }

  // One user action, however many internal steps it takes. While it runs the
  // card shows which step is happening rather than a frozen button, and the
  // button is disabled so a second click cannot start a second run.
  async function runStagedAction(card, node, msg, options) {
    const box = qs('[data-stage-progress]', card);
    const actions = qs('[data-slot="actions"]', card);
    const button = actions && qs('button', actions);
    card.dataset.busy = '1';
    if (button) { button.disabled = true; button.textContent = options.working; }
    if (msg) msg.textContent = '';
    if (box) box.innerHTML = progressHtml(options.plan, options.plan[0].key, false);

    let polling = true;
    const advance = async () => {
      while (polling) {
        try {
          const view = await API.http.adminPipeline();
          const state = String(((view || {}).candidate || {}).state || '');
          const stage = options.plan.find(row => row.running.indexOf(state) >= 0);
          if (stage && box && polling) box.innerHTML = progressHtml(options.plan, stage.key, false);
        } catch (e) { /* a poll that fails must not end the operation */ }
        await new Promise(resolve => setTimeout(resolve, 2500));
      }
    };
    advance();

    try {
      const out = await options.request();
      polling = false;
      if (box) {
        box.innerHTML = finalStagesHtml(out.stages)
          + (out.checks && out.checks.length ? checksHtml(out.checks) : '');
      }
      toast(options.done);
      await options.again();
    } catch (e) {
      polling = false;
      const detail = (e && e.payload) || {};
      if (box) box.innerHTML = finalStagesHtml(detail.stages)
        + (detail.checks && detail.checks.length ? checksHtml(detail.checks) : '')
        + options.failure(detail);
      if (msg) msg.textContent = (e && e.message) || String(e);
      if (button) { button.disabled = false; button.textContent = options.label; }
    } finally {
      polling = false;
      delete card.dataset.busy;
    }
  }

  function wireStageActions(node, targets, candidate, msg) {
    const again = () => renderEnvironmentSwitcherInto(node);

    qsa('[data-stage-deliver]', node).forEach(button => {
      if (button.dataset.wired) return;
      button.dataset.wired = '1';
      button.onclick = () => {
        // Building and deploying to Canary from one click, with no statement of
        // what is being built, is how an artifact from an unmerged branch
        // reached Canary during beta.82. Still one decision, but a stated one.
        const target = (targets || []).find(row => row.environment === 'development') || {};
        if (!window.confirm('Отправить в Canary?' + '\n\n'
          + 'Будет собран artifact из текущего commit ' + String(target.commit || '').slice(0, 12)
          + ' и развёрнут в Canary с автоматической приёмкой.')) return;
        return runStagedAction(button.closest('[data-stage-env]'), node, msg, {
        plan: DELIVER_STAGES,
        label: 'Отправить в Canary',
        working: 'Отправляю…',
        done: 'Развёрнуто в Canary и принято',
        again,
        request: () => API.http.releaseDeliverCanary(releaseKey()),
        failure: detail => '<div class="pub-outcome is-failed">Отправка остановлена'
          + (detail.failed_stage ? ' · этап: ' + esc(detail.failed_stage) : '') + '</div>',
        });
      };
    });

    qsa('[data-stage-publish]', node).forEach(button => {
      if (button.dataset.wired) return;
      button.dataset.wired = '1';
      button.onclick = () => {
        const version = String((candidate || {}).app_version || '');
        if (!window.confirm('Опубликовать ' + version + '?' + '\n\n'
          + 'В Production будет продвинут тот же проверенный artifact. Пересборки не будет.')) return;
        return runStagedAction(button.closest('[data-stage-env]'), node, msg, {
          plan: PUBLISH_STAGES,
          label: 'Опубликовать в Production',
          working: 'Публикую…',
          done: 'Опубликовано в Production',
          again,
          request: () => API.http.releasePublish(button.dataset.stagePublish, releaseKey()),
          failure: detail => {
            const deployed = detail.production_deployed;
            return '<div class="pub-outcome ' + (deployed ? 'is-deployed' : 'is-failed') + '">'
              + (deployed ? 'Production развёрнут, validation failed' : 'Публикация не выполнена')
              + (detail.failed_stage ? ' · этап: ' + esc(detail.failed_stage) : '') + '</div>'
              + (detail.closeout_blocked
                ? '<div class="cab-sub">Closeout заблокирован до устранения причины.</div>' : '')
              + (deployed && detail.rollback && detail.rollback.available
                ? '<div class="cab-sub">Откат — штатным действием «rollback-production».</div>' : '');
          },
        });
      };
    });
  }

  const RELEASE_ORDER = ['development', 'canary', 'production'];

  // One scale for every load figure on this screen, so the same colour always
  // means the same thing. Defined once rather than per metric: three different
  // notions of "high" on one card is how a panel stops being read.
  const LOAD_THRESHOLDS = { elevated: 60, high: 80, critical: 92 };

  function loadLevel(percent) {
    const value = Number(percent);
    if (!isFinite(value)) return 'unknown';
    if (value >= LOAD_THRESHOLDS.critical) return 'critical';
    if (value >= LOAD_THRESHOLDS.high) return 'high';
    if (value >= LOAD_THRESHOLDS.elevated) return 'elevated';
    return 'normal';
  }

  function loadGaugeHtml(label, percent, valueText) {
    // A figure the environment did not report is named, not drawn as zero.
    if (percent == null || !isFinite(Number(percent))) {
      return '<div class="load-gauge is-unknown"><span class="load-name">' + esc(label) + '</span>'
        + '<span class="load-track"></span><span class="load-value">нет данных</span></div>';
    }
    const value = Math.max(0, Math.min(100, Number(percent)));
    return '<div class="load-gauge is-' + loadLevel(value) + '">'
      + '<span class="load-name">' + esc(label) + '</span>'
      + '<span class="load-track"><span class="load-fill" style="width:' + value.toFixed(0) + '%"></span></span>'
      + '<span class="load-value">' + esc(valueText || (value.toFixed(0) + '%')) + '</span></div>';
  }

  // First level: CPU, RAM and disk. Everything else is diagnosis, not notice.
  function gaugesHtml(host) {
    const measured = host && typeof host === 'object' ? host : {};
    const known = ['cpu_percent', 'memory_percent', 'disk_percent']
      .some(key => measured[key] != null);
    if (!known) return '<div class="env-load-none">Данные недоступны</div>';
    return loadGaugeHtml('CPU', measured.cpu_percent)
      + loadGaugeHtml('RAM', measured.memory_percent)
      + loadGaugeHtml('Диск', measured.disk_percent);
  }

  function technicalHtml(target) {
    const admission = (target.health_metrics && target.health_metrics.admission) || null;
    const rows = [
      ['Commit', (target.commit || '').slice(0, 12) || '—'],
      ['Build', target.build_id || '—'],
      ['Artifact', (target.artifact_sha256 || '').slice(0, 16) || '—'],
      ['Канал', target.release_channel || '—'],
      ['Готовность', target.readiness || '—'],
      ['Последний отчёт', target.last_seen_at_utc || '—'],
    ];
    if (admission) {
      const latency = admission.duration_ms || {};
      const sockets = admission.websockets || {};
      const ms = value => {
        const number = Number(value);
        if (!isFinite(number)) return '—';
        return number >= 1000
          ? (number / 1000).toFixed(number >= 10000 ? 0 : 1) + ' с'
          : Math.round(number) + ' мс';
      };
      rows.push(['Активных запросов', String(admission.active != null ? admission.active : '—')
        + (admission.max_inflight ? ' / ' + admission.max_inflight : '')]);
      rows.push(['Задержка p50', ms(latency.p50)]);
      rows.push(['Задержка p95', ms(latency.p95)]);
      rows.push(['Задержка p99', ms(latency.p99)]);
      rows.push(['Пик активных', String(admission.peak_active != null ? admission.peak_active : '—')]);
      rows.push(['Принято', String(admission.accepted != null ? admission.accepted : '—')]);
      rows.push(['Отклонено', String(admission.rejected != null ? admission.rejected : '—')]);
      rows.push(['WebSocket', String(sockets.active != null ? sockets.active : '—')
        + (sockets.max ? ' / ' + sockets.max : '')]);
    }
    return '<div class="admin-env-meta">' + rows.map(row =>
      '<div><span>' + esc(row[0]) + '</span><strong class="mono">' + esc(row[1]) + '</strong></div>'
    ).join('') + '</div>';
  }

  const ENV_PURPOSE = {
    development: 'Локальная разработка',
    canary: 'Проверочная среда',
    production: 'Рабочая среда',
  };

  // Each card explains its own version. The same release on two stages may
  // legitimately show the same words; what it must not do is leave a card
  // unable to say what it is running.
  function summaryHtml(target) {
    const points = Array.isArray(target.summary) ? target.summary.slice(0, 3) : [];
    if (!target.summary_title && !points.length) return '';
    return (target.summary_title
      ? '<div class="env-summary-title">' + esc(target.summary_title) + '</div>' : '')
      + (points.length ? '<ul class="env-summary">' + points.map(row =>
        '<li>' + esc(row) + '</li>').join('') + '</ul>' : '');
  }

  function statusHtml(target, candidate) {
    const env = String(target.environment || '');
    const state = String((candidate || {}).state || '');
    if (env === 'canary' && state === 'canary_passed') {
      return '<div class="stage-status is-pass">✓ Canary PASS · приёмка пройдена</div>';
    }
    if (env === 'canary' && state === 'canary_checking') {
      return '<div class="stage-status is-progress">Идут проверки Canary</div>';
    }
    if (env === 'canary' && state === 'canary_failed') {
      return '<div class="stage-status is-fail">Canary не принят</div>';
    }
    if (env === 'production' && state === 'production_live') {
      return '<div class="stage-status is-pass">✓ Активная версия</div>';
    }
    const health = String(target.health || 'unknown');
    const offline = health === 'offline' || String(target.presence || '') === 'never_seen';
    if (offline && env === 'development') {
      return '<div class="stage-status is-idle">Локальный сервер не запущен</div>';
    }
    if (health === 'unreachable') {
      // The reason the probe gave, not a generic word: "недоступен" alone
      // sends the reader to the logs to find out what actually failed.
      return '<div class="stage-status is-fail">Недоступен'
        + (target.probe_error ? ' · ' + esc(target.probe_error) : '') + '</div>';
    }
    return '<div class="stage-status ' + (health === 'reachable' ? 'is-ok' : 'is-idle') + '">'
      + (health === 'reachable' ? 'На связи' : 'Состояние неизвестно') + '</div>';
  }

  // Identity, not the version string: two environments can report the same
  // version and run different builds, which is exactly the mistake the release
  // ledger exists to prevent.
  function sameArtifact(a, b) {
    const build = String((a || {}).build_id || '');
    const other = String((b || {}).build_id || '');
    if (build && other) return build === other;
    const sha = String((a || {}).artifact_sha256 || '');
    const otherSha = String((b || {}).artifact_sha256 || '');
    return !!sha && sha === otherSha;
  }

  function actionsHtml(target, targets, candidate, promotion) {
    const env = String(target.environment || '');
    const state = String((candidate || {}).state || '');
    const id = String((candidate || {}).candidate_id || '');
    if (env === 'development') {
      if (!hasAdminCapability('releases.deploy_canary')) return '';
      return '<button class="btn primary stage-action" data-stage-deliver="1"'
        + ' title="Создать кандидата из текущего commit, собрать artifact,'
        + ' проверить и развернуть в Canary">Отправить в Canary</button>';
    }
    if (env === 'canary') {
      if (!hasAdminCapability('releases.promote_production')) return '';
      const production = (targets || []).find(row => row.environment === 'production');
      // Nothing to publish when Production already runs this exact artifact.
      if (sameArtifact(target, production)) {
        return '<div class="stage-done">✓ Уже опубликовано в Production</div>';
      }
      if (state !== 'canary_passed' || !id) return '';
      const blocked = !(promotion || {}).allowed;
      const why = blocked ? ((promotion || {}).reason || 'Промоушен недоступен')
        : 'Опубликовать проверенный artifact в Production';
      return '<button class="btn primary stage-action" data-stage-publish="' + esc(id) + '"'
        + (blocked ? ' disabled' : '') + ' title="' + esc(why) + '">Опубликовать в Production</button>'
        + (blocked ? '<div class="stage-blocked">Недоступно: ' + esc(why) + '</div>' : '');
    }
    return '';
  }

  // What acceptance actually checked, in one line, with the detail folded away.
  function checksHtml(checks) {
    const rows = Array.isArray(checks) ? checks : [];
    if (!rows.length) return '';
    return '<div class="stage-checks">' + rows.map(row =>
      '<span class="stage-check ' + (row.ok ? 'ok' : 'fail') + '">'
      + (row.ok ? '✓' : '✕') + ' ' + esc(row.label || row.name) + '</span>').join('')
      + '</div><details class="env-tech"><summary>Детали проверки</summary>'
      + '<div class="admin-env-meta">' + rows.map(row =>
        '<div><span>' + esc(row.label || row.name) + '</span><strong>'
        + esc(row.detail || (row.ok ? 'пройдено' : 'не пройдено')) + '</strong></div>').join('')
      + '</div></details>';
  }

  function stageCardSkeleton(target, index) {
    const env = String(target.environment || '');
    return '<section class="cab-card stage-card" data-env-card="' + index + '" data-stage-env="' + esc(env) + '">'
      + '<div class="stage-head">'
      + '<span class="badge" data-slot="badge">' + esc(env.toUpperCase()) + '</span>'
      + '<span class="cab-sub" data-slot="current"></span>'
      + '<span class="mono cab-sub stage-origin" data-slot="origin"></span>'
      + '</div>'
      + '<div class="env-line"><strong class="env-version" data-slot="version"></strong>'
      + '<span class="cab-sub" data-slot="purpose"></span></div>'
      + '<div data-slot="summary"></div>'
      + '<div data-slot="status"></div>'
      + '<div class="env-load" data-slot="gauges"></div>'
      + '<details class="env-tech"><summary>Технические данные / Метрики</summary>'
      + '<div data-slot="tech"></div></details>'
      + '<div data-slot="checks"></div>'
      + '<div class="stage-actions" data-slot="actions"></div>'
      + '<div data-stage-progress></div>'
      + '</section>';
  }

  // Updating in place, field by field. Replacing the panel's innerHTML on every
  // poll closed whatever the reader had opened, threw away the scroll position
  // and made the screen flash like a reload every few seconds.
  function patchSlot(card, name, html) {
    const slot = qs('[data-slot="' + name + '"]', card);
    if (slot && slot.innerHTML !== html) slot.innerHTML = html;
  }

  function patchCard(card, target, targets, candidate, promotion) {
    const badge = qs('[data-slot="badge"]', card);
    if (badge) {
      const cls = 'badge ' + (target.current ? 'live' : (target.configured ? 'pending' : 'archived'));
      if (badge.className !== cls) badge.className = cls;
    }
    patchSlot(card, 'current', target.current ? 'текущая' : '');
    patchSlot(card, 'origin', esc(target.current
      ? location.origin : (target.origin || 'origin не задан')));
    patchSlot(card, 'version', esc(target.version || '—'));
    patchSlot(card, 'purpose', esc(ENV_PURPOSE[String(target.environment || '')] || ''));
    patchSlot(card, 'summary', summaryHtml(target));
    patchSlot(card, 'status', statusHtml(target, candidate));
    patchSlot(card, 'gauges', gaugesHtml(target.host));
    patchSlot(card, 'tech', technicalHtml(target));
    // Actions are left alone while an operation is running in this card, so a
    // poll cannot replace the button under the pointer mid-run.
    if (!card.dataset.busy) {
      patchSlot(card, 'actions', actionsHtml(target, targets, candidate, promotion));
    }
  }

  function renderEnvironmentTargets(node, payload, pipeline) {
    const targets = ((payload && payload.targets) || []).slice().sort(
      (a, b) => RELEASE_ORDER.indexOf(a.environment) - RELEASE_ORDER.indexOf(b.environment));
    const doc = pipeline || {};
    const candidate = doc.candidate || {};
    const promotion = doc.promotion || {};

    if (!qs('.stage-flow', node)) {
      node.innerHTML = '<div class="stage-flow">'
        + targets.map((target, index) => stageCardSkeleton(target, index))
          .join('<div class="stage-arrow">→</div>')
        + '</div><div class="cab-sub stage-note" id="stage-msg"></div>'
        + '<details class="card-details" id="env-diagnostics">'
        + '<summary>Технические данные / Диагностика</summary>'
        + '<div class="finance-note">Каждая среда открывается на своём origin в новой вкладке.'
        + ' Токены, cookies, CSRF и localStorage не переносятся.</div>'
        + '<div data-env-compare></div></details>';
      renderEnvironmentCompareInto(qs('[data-env-compare]', node));
    }

    const cards = qsa('.stage-card', node);
    targets.forEach((target, index) => {
      const card = cards[index];
      if (card) patchCard(card, target, targets, candidate, promotion);
    });

    const msg = qs('#stage-msg', node);
    wireStageActions(node, targets, candidate, msg);

    // Probes add live reachability on top of what an environment last
    // reported; one slow origin must not hold up the others.
    targets.forEach((target, index) => {
      if (target.current || !target.origin) return;
      const card = cards[index];
      probeEnvironmentTarget(target, card).then(() => {
        if (card) patchSlot(card, 'status', statusHtml(target, candidate));
      }).catch(e => {
        target.probe_ok = false;
        target.health = 'unreachable';
        target.probe_error = String((e && e.message) || e || 'endpoint недоступен');
        if (card) patchSlot(card, 'status', statusHtml(target, candidate));
      });
    });
  }

  // ---- Environments and releases (one module) -------------------------------
  //
  // The Environment Switcher knew what each environment ran; the Release Center
  // knew how a candidate moves. Neither knew the other, so the owner had to
  // hold the workflow in their head across two screens: which candidate is on
  // Canary, and whether it is the same artifact Production would receive.
  //
  // This is both, fed by /api/admin/pipeline, which joins the environment
  // registry and the release centre server-side rather than making the browser
  // reconcile two payloads. The release engine is untouched: every button here
  // calls the same release_center transitions the detail drawer calls.
  const PIPE_PRESENCE = {
    live: ['live', 'на связи'], stale: ['pending', 'молчит'],
    offline: ['failed', 'офлайн'], never_seen: ['archived', 'не отчитывалась'],
  };
  const PIPE_SYNC = {
    current: ['live', 'соответствует checkout'],
    stale: ['failed', 'запущен НЕ тот код'],
    dirty: ['pending', 'есть незакоммиченные правки'],
    behind: ['failed', 'отстаёт от релиза'],
    ahead: ['pending', 'новее принятого релиза'],
    diverged: ['failed', 'другая ревизия версии'],
    unknown: ['archived', 'состояние неизвестно'],
    not_applicable: ['archived', 'релизный артефакт'],
  };
  const PIPE_STAGE_MARK = { done: '●', pending: '○', failed: '✕' };

  // Seven stages, four buttons: each button drives the several engine
  // transitions that make up one step an owner actually decides on. Legs are
  // skipped when the candidate is already past them, so the same button works
  // whether it is starting the step or resuming it.
  const PIPE_SEQUENCE = {
    'deploy-canary': [
      // build_failed is retryable: the engine allows it, and a build that died
      // on a transient remote error would otherwise strand the candidate with
      // no way forward in this module at all.
      { from: ['draft', 'build_failed'], action: 'build', note: 'сборка артефакта' },
      { from: ['built'], action: 'verify', note: 'проверка подписи' },
      { from: ['signed', 'canary_failed'], action: 'deploy-canary', note: 'развёртывание Canary' },
    ],
    'acceptance': [
      { from: ['canary_checking'], action: 'record-canary-check', note: 'приёмка Canary',
        body: { name: 'acceptance', result: 'pass', final: true } },
    ],
    'promote-production': [
      { from: ['canary_passed'], action: 'approve-production', note: 'одобрение Production' },
      { from: ['approved_for_production', 'production_scheduled', 'production_failed'],
        action: 'promote-production', note: 'промоушен Production' },
    ],
  };

  function pipeBadge(map, key) {
    const pair = map[String(key || '')] || ['archived', String(key || '—')];
    return `<span class="badge ${pair[0]}">${esc(pair[1])}</span>`;
  }

  function pipeWhen(value) {
    const text = String(value || '');
    return text ? esc(text.replace('T', ' ').replace('Z', '')) : '—';
  }

  function pipeShort(value, size) {
    const text = String(value == null ? '' : value);
    if (!text || text === '0') return '—';
    return esc(text.length > size ? text.slice(0, size) + '…' : text);
  }

  function pipeRows(pairs) {
    return `<div class="admin-env-meta">${pairs.map(
      p => `<div><span>${esc(p[0])}</span><strong>${p[1]}</strong></div>`).join('')}</div>`;
  }

  function pipeDevelopmentCard(card, access) {
    // The sync state sits on the card rather than in a separate banner: a
    // release cut from a checkout LOCAL is not actually running is exactly the
    // failure this pipeline exists to prevent.
    const off = ['stale', 'dirty', 'behind', 'ahead', 'diverged'].indexOf(card.sync_state) >= 0;
    const open = !!(access && access.allowed);
    return `<section class="cab-card pipe-card${off ? ' pipe-card-warn' : ''}">
      <div class="pipe-card-head"><b>Development</b>
        ${pipeBadge(PIPE_PRESENCE, card.presence)}${pipeBadge(PIPE_SYNC, card.sync_state)}</div>
      ${off ? `<div class="admin-env-warnings"><div>⚠ ${esc(card.sync_message || '')}</div></div>` : ''}
      ${pipeRows([
        ['Версия', pipeShort(card.version, 24)],
        ['Запущенный commit', `<span class="mono">${pipeShort(card.running_commit, 12)}</span>`],
        ['Checkout HEAD', `<span class="mono">${pipeShort(card.head_commit, 12)}</span>`],
        ['Ветка', pipeShort(card.head_branch, 20)],
        ['Незакоммичено', esc(String(card.dirty_count || 0))],
        ['Build', pipeShort(card.build_id, 22)],
        ['Схема БД', pipeShort(card.schema_version, 8)],
        ['Готовность', pipeShort(card.readiness, 14)],
        ['Market data', pipeShort(card.market_data, 14)],
        ['Connector', pipeShort(card.connector, 14)],
        ['Активность', pipeWhen(card.last_seen_at_utc)],
      ])}
      ${open ? '' : `<div class="cab-sub">${esc((access && access.reason) || '')}</div>`}
      <div class="flex gap-sm wrap pipe-actions">
        ${open
          ? '<button class="btn primary" id="pipe-open-dev">Открыть Development</button>'
          : '<button class="btn ghost" disabled>Открыть Development</button>'}
      </div>
    </section>`;
  }

  function pipeServerCard(title, card) {
    return `<section class="cab-card pipe-card">
      <div class="pipe-card-head"><b>${esc(title)}</b>${pipeBadge(PIPE_PRESENCE, card.presence)}</div>
      ${pipeRows([
        ['Версия', pipeShort(card.version, 24)],
        ['Commit', `<span class="mono">${pipeShort(card.commit, 12)}</span>`],
        ['Артефакт', `<span class="mono">${pipeShort(card.artifact_sha256, 16)}</span>`],
        ['Схема БД', pipeShort(card.schema_version, 8)],
        ['Готовность', pipeShort(card.readiness, 14)],
        ['Market data', pipeShort(card.market_data, 14)],
        ['Connector', pipeShort(card.connector, 14)],
        ['Последний деплой', pipeWhen(card.last_deploy_at_utc)],
        ['Активность', pipeWhen(card.last_seen_at_utc)],
      ])}
    </section>`;
  }

  function pipeStagesHtml(stages) {
    // failed is drawn as failed, never as "not yet reached". That distinction
    // is the reason someone opened this page.
    return `<div class="pipe-stages">${(stages || []).map(s => `
      <div class="pipe-stage pipe-stage-${esc(s.state)}">
        <span class="pipe-stage-dot">${PIPE_STAGE_MARK[s.state] || '○'}</span>
        <span class="pipe-stage-label">${esc(s.label)}</span>
      </div>`).join('<span class="pipe-arrow">→</span>')}</div>`;
  }

  function pipeGatesHtml(promotion) {
    const gates = (promotion && promotion.gates) || [];
    if (!gates.length) return '';
    if (promotion.complete) {
      return `<div class="cab-sub">${esc(promotion.note || 'Промоушен закрыт.')}</div>`;
    }
    // Who ruled matters as much as the ruling. On LOCAL the Canary gates are
    // decided by the authoritative server, and "nobody could be asked" is a
    // different problem from "the server said no".
    const authority = promotion.decided_by
      ? `<div class="cab-sub">Решение принимает сервер: ${esc(promotion.decided_by)}</div>`
      : (promotion.control_available === false
        ? `<div class="admin-env-warnings"><div>⚠ Control plane недоступен — промоушен закрыт до ответа сервера.</div></div>`
        : '');
    return `<details class="card-details"${promotion.allowed ? '' : ' open'}>
      <summary>${promotion.allowed
        ? 'Условия промоушена в Production выполнены'
        : 'Почему промоушен в Production заблокирован'}</summary>
      <div class="pipe-gates">${gates.map(g => `
        <div class="pipe-gate ${g.ok ? 'is-ok' : 'is-blocked'}">
          <span>${g.ok ? '✓' : '✕'}</span><span>${esc(g.label)}</span>
        </div>`).join('')}</div>
      ${authority}
    </details>`;
  }

  function pipeCompareHtml(compare) {
    const envs = (compare && compare.environments) || [];
    if (!envs.length) {
      return `<section class="cab-card"><h4>Сравнение окружений</h4>
        <div class="cab-sub">Ни одно окружение ещё не сообщило о себе.</div></section>`;
    }
    const head = envs.map(e => `<th>${esc(String(e).toUpperCase())}</th>`).join('');
    const body = (compare.fields || []).map(f => {
      const cells = envs.map(e => {
        const missing = (f.missing || []).indexOf(e) >= 0;
        const text = missing ? 'не сообщено' : String(f.values[e] == null ? '—' : f.values[e]);
        const short = text.length > 18 ? text.slice(0, 14) + '…' : text;
        return `<td class="mono${missing ? ' cab-sub' : ''}" title="${esc(text)}">${esc(short)}</td>`;
      }).join('');
      return `<tr class="${f.differs ? 'is-diff' : ''}">
        <th scope="row">${esc(f.label)}${f.differs ? ' ⚠' : ''}</th>${cells}</tr>`;
    }).join('');
    return `<section class="cab-card"><h4>Сравнение окружений</h4>
      <div class="table-scroll"><table class="admin-env-compare">
        <thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table></div>
      <p class="cab-sub">«Не сообщено» — отсутствие данных, а не расхождение.</p></section>`;
  }

  function releaseDuration(seconds) {
    const total = Math.max(0, Number(seconds) || 0);
    if (total < 60) return Math.round(total) + ' сек';
    if (total < 3600) return Math.round(total / 60) + ' мин';
    const hours = Math.floor(total / 3600);
    const minutes = Math.round((total % 3600) / 60);
    return hours + ' ч' + (minutes ? ' ' + minutes + ' мин' : '');
  }

  function pipeReleaseRecordHtml(doc) {
    const candidate = doc.candidate || {};
    const record = candidate.release_record || {};
    if (!candidate.candidate_id) return '';
    const envs = doc.environments || {};
    const stage = String(record.current_stage || 'CI');
    const status = String(record.status || 'BLOCKED');
    const route = stage === 'DONE' ? 'Canary → Production'
      : (stage === 'PRODUCTION PROMOTION' ? 'Canary → Production' : 'Development → Canary');
    const changes = Array.isArray(record.changes) ? record.changes.slice(0, 4) : [];
    const prs = Array.isArray(record.prs) ? record.prs : [];
    const checks = Array.isArray(record.verification_checks) ? record.verification_checks : [];
    const missing = Array.isArray(record.missing_fields) ? record.missing_fields : [];
    const runtimeArtifact = String(candidate.manifest_sha256 || candidate.artifact_sha256 || '');
    const canaryArtifact = String((envs.canary || {}).artifact_sha256 || '');
    const productionArtifact = String((envs.production || {}).artifact_sha256 || '');
    const sameOnServers = !!runtimeArtifact
      && canaryArtifact.toLowerCase() === runtimeArtifact.toLowerCase()
      && productionArtifact.toLowerCase() === runtimeArtifact.toLowerCase();
    const identityRows = [
      ['DEV / candidate', candidate.artifact_id || (envs.development || {}).build_id ||
        (envs.development || {}).commit || 'ещё не собран'],
      ['Canary', canaryArtifact ? canaryArtifact.slice(0, 16) : 'не сообщено'],
      ['Production', productionArtifact ? productionArtifact.slice(0, 16) : 'не сообщено'],
    ];
    return `<div class="release-record ${missing.length ? 'is-incomplete' : ''}">
      <div class="release-record-head">
        <div><div class="cab-sub">Сейчас выпускается</div>
          <h3>${esc(record.title || 'Release/change record не заполнен')}</h3></div>
        <span class="badge ${status === 'PASS' ? 'live' : (status === 'FAIL' ? 'failed' :
          (status === 'BLOCKED' ? 'pending' : 'running'))}">${esc(status)}</span>
      </div>
      <div class="release-record-summary">${esc(record.change_summary ||
        'Краткое описание выпуска отсутствует.')}</div>
      ${prs.length ? `<div class="release-record-prs"><strong>Вошли:</strong> ${prs.map(esc).join(' · ')}</div>` : ''}
      ${changes.length ? `<ul class="release-record-changes">${changes.map(item =>
        `<li>${esc(item)}</li>`).join('')}</ul>` : ''}
      <div class="release-record-grid">
        <div><span>Этап</span><strong>${esc(stage)} · ${esc(status)}</strong></div>
        <div><span>Направление</span><strong>${esc(route)}</strong></div>
        <div><span>Source SHA</span><strong class="mono">${esc(record.source_sha || '—')}</strong></div>
        <div><span>Version / Build</span><strong class="mono">${esc(candidate.app_version || '—')} · ${esc(candidate.build_id || 'ещё не собран')}</strong></div>
        <div><span>Artifact ID</span><strong class="mono">${esc(candidate.artifact_id || 'ещё не собран')}</strong></div>
        <div><span>Выполняется</span><strong>${esc(releaseDuration(record.duration_seconds))}</strong></div>
      </div>
      <div class="release-record-envs">${identityRows.map(row =>
        `<div><span>${esc(row[0])}</span><strong class="mono">${esc(row[1])}</strong></div>`).join('')}</div>
      <div class="release-record-proof ${sameOnServers ? 'is-pass' : ''}">
        ${sameOnServers
          ? 'PASS: Canary и Production выполняют тот же immutable artifact.'
          : 'Контракт: Canary → Production продвигает тот же artifact без rebuild.'}
      </div>
      ${checks.length ? `<div class="stage-checks">${checks.map(row =>
        `<span class="stage-check ${row.result === 'PASS' ? 'ok' : 'fail'}">${row.result === 'PASS' ? '✓' : '✕'} ${esc(row.name)}</span>`).join('')}</div>` : ''}
      ${missing.length ? `<div class="stage-blocked">Production BLOCKED: отсутствует ${esc(missing.join(', '))}</div>` : ''}
      ${(record.subsystems || record.release_impact) ? `<details class="env-tech"><summary>Release impact</summary>
        <div class="admin-env-meta">
          <div><span>Подсистемы</span><strong>${esc(record.subsystems || '—')}</strong></div>
          <div><span>Влияние</span><strong>${esc(record.release_impact || '—')}</strong></div>
        </div></details>` : ''}
    </div>`;
  }

  function pipeCandidateHtml(doc) {
    const candidate = doc.candidate || {};
    const promotion = doc.promotion || {};
    const id = candidate.candidate_id || '';
    const blocked = !promotion.allowed;
    const state = String(candidate.state || '');
    // A step whose every leg is behind or ahead of the current state can do
    // nothing. Leaving it clickable turns a state question into an error toast.
    const runnable = step => (PIPE_SEQUENCE[step] || []).some(l => l.from.indexOf(state) >= 0);
    const stepAttrs = (step, blockedReason) => {
      const reason = blockedReason || (runnable(step) ? '' :
        'Состояние «' + state + '» не допускает этот шаг');
      return `data-pipe-step="${step}"${reason ? ' disabled' : ''} title="${esc(reason ||
        'Выполнить шаг')}"`;
    };
    const canCreate = hasAdminCapability('releases.create');
    const canCanary = hasAdminCapability('releases.deploy_canary');
    const canPromote = hasAdminCapability('releases.promote_production');
    const createBtn = canCreate
      ? `<button class="btn ${id ? 'ghost' : 'primary'}" id="pipe-create-toggle">Создать релиз-кандидат</button>`
      : '';
    if (!id) {
      return `<section class="cab-card"><h4>Релиз-кандидат</h4>
        <div class="cab-sub">Активного кандидата нет. Кандидат создаётся только из чистого текущего commit.</div>
        ${pipeStagesHtml(doc.stages)}
        <div class="flex gap-sm wrap pipe-actions">${createBtn}</div>
        <div id="pipe-create-form" hidden></div></section>`;
    }
    return `<section class="cab-card"><h4>Релиз-кандидат</h4>
      ${pipeReleaseRecordHtml(doc)}
      <div class="cab-sub mono">${esc(id)} · v${esc(candidate.app_version || '')} ·
        ${esc(candidate.release_channel || '')} · ${esc(candidate.state || '')}</div>
      ${pipeStagesHtml(doc.stages)}
      ${pipeGatesHtml(promotion)}
      <div class="flex gap-sm wrap pipe-actions">
        ${createBtn}
        ${canCanary ? `<button class="btn" ${stepAttrs('deploy-canary')}>Развернуть в Canary</button>` : ''}
        ${canCanary ? `<button class="btn" ${stepAttrs('acceptance')}>Приёмка</button>` : ''}
        ${canPromote ? (state === 'canary_passed'
          ? `<button class="btn ${blocked ? 'ghost' : 'primary'}" data-pipe-publish="${esc(id)}"
              ${blocked ? 'disabled' : ''} title="${esc(blocked
                ? (promotion.note || promotion.reason || 'Промоушен недоступен')
                : 'Опубликовать проверенный artifact в Production')}"
              >Опубликовать в Production</button>`
          : `<button class="btn ghost" disabled
              title="Доступно только для кандидата, прошедшего Canary">Опубликовать в Production</button>`) : ''}
        <button class="btn sm ghost" data-release-open="${esc(id)}">Все действия</button>
      </div>
      ${blocked && !promotion.complete ? `<div class="admin-env-warnings">
        <div>⚠ Промоушен заблокирован: ${esc(promotion.reason || '')}</div></div>` : ''}
      <div id="pipe-publish-progress"></div>
      <div class="cab-sub" id="pipe-step-msg"></div>
      <div id="pipe-create-form" hidden></div></section>`;
  }

  function pipeNotificationsHtml(preview) {
    const items = (preview && preview.previews) || [];
    if (!items.length) return '';
    return `<details class="card-details"><summary>Уведомления об обновлении (предпросмотр)</summary>
      <div class="cab-sub">${esc(preview.note || '')}</div>
      <div class="list">${items.map(p => `<div class="feat-row">
        <span><strong>${esc(p.title)}</strong> — ${esc(p.message)}</span>
        <span class="badge archived">${esc(p.kind)}</span></div>`).join('')}</div>
      <div class="flex gap-sm wrap" style="margin-top:10px">
        <button class="btn sm" data-pipe-banner="warn_5m">Баннер: через 5 минут</button>
        <button class="btn sm" data-pipe-banner="warn_60s">Баннер: через 60 секунд</button>
        <button class="btn sm" data-pipe-banner="deploy_successful">Баннер: обновление завершено</button>
        <button class="btn sm ghost" data-pipe-banner="*">Проиграть последовательность</button>
      </div></details>`;
  }

  function pipeHistoryHtml(candidates) {
    const rows = candidates || [];
    if (rows.length < 2) return '';
    return `<details class="card-details"><summary>История кандидатов (${rows.length})</summary>
      <div class="list">${rows.map(renderReleaseRow).join('')}</div></details>`;
  }

  async function pipeRunStep(candidateId, step, state) {
    // Walk only the legs the candidate has not already passed. A failure names
    // the transition that refused; "не удалось" alone would send the reader
    // back to guessing which of three calls broke.
    let current = String(state || '');
    let ran = 0;
    for (const leg of PIPE_SEQUENCE[step]) {
      if (leg.from.indexOf(current) < 0) continue;
      const payload = Object.assign({ idempotency_key: releaseKey() }, leg.body || {});
      let out;
      try {
        out = await API.http.adminReleaseAction(candidateId, leg.action, payload);
      } catch (e) {
        throw new Error(leg.note + ': ' + ((e && e.code === 'step_up_required')
          ? 'требуется подтверждение действия (step-up)'
          : ((e && e.message) || String(e))));
      }
      // build and canary deploy report their own failure with HTTP 200; a body
      // that says it did not work is a failure whatever the status line said.
      if (out && out.ok === false) {
        throw new Error(leg.note + ': ' + (out.failure_reason || out.state || 'не выполнено'));
      }
      current = String((out && out.state) || current);
      ran += 1;
    }
    if (!ran) throw new Error('Состояние «' + (state || '—') + '» не допускает этот шаг.');
    return current;
  }

  function pipeCreateForm(node, refresh) {
    const form = qs('#pipe-create-form', node);
    const toggle = qs('#pipe-create-toggle', node);
    if (!form || !toggle) return;
    toggle.onclick = () => {
      form.hidden = !form.hidden;
      if (form.hidden) { form.innerHTML = ''; return; }
      form.innerHTML = `<div class="cab-card"><h4>Новый кандидат</h4>
        <div class="cab-sub">Только чистый текущий commit. Грязное рабочее дерево сервер отклоняет.</div>
        <label class="field"><span>Версия (semver)</span>
          <input id="pipe-version" type="text" placeholder="0.10.0-beta.28"></label>
        <label class="field"><span>Канал</span><select id="pipe-channel">
          <option value="beta">beta</option><option value="dev">dev</option>
          <option value="stable">stable</option></select></label>
        <label class="field"><span>Commit SHA (пусто = текущий HEAD)</span>
          <input id="pipe-commit" type="text" class="mono" placeholder="HEAD"></label>
        <div class="flex gap-sm"><button class="btn primary" id="pipe-create">Создать</button></div>
        <div class="cab-sub" id="pipe-create-msg"></div></div>`;
      const create = qs('#pipe-create', form);
      create.onclick = async () => {
        const msg = qs('#pipe-create-msg', form);
        create.disabled = true;
        msg.textContent = 'Создаю…';
        try {
          await API.http.adminReleaseCreate({
            app_version: (qs('#pipe-version', form).value || '').trim(),
            release_channel: qs('#pipe-channel', form).value,
            git_commit_sha: (qs('#pipe-commit', form).value || '').trim(),
            idempotency_key: releaseKey(),
          });
          toast('Кандидат создан');
          refresh();
        } catch (e) {
          msg.textContent = (e && e.message) || String(e);
          create.disabled = false;
        }
      };
    };
  }

  async function renderPipelineInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка окружений…</div>';
    let doc;
    try { doc = await withDeadline(API.http.adminPipeline(), 'Состояние окружений'); }
    catch (e) { return renderError(node, e, () => renderPipelineInto(node)); }

    const envs = doc.environments || {};
    const overall = doc.overall || {};
    const again = () => renderPipelineInto(node);
    node.innerHTML = `
      <div class="finance-note"><strong>Один путь:</strong> Development → релиз-кандидат →
        Canary → приёмка → тот же артефакт в Production. Между Canary и Production
        артефакт не пересобирается. ${releaseAdapterSummary(doc.adapter || {})}</div>
      ${(() => {
        // Unknown is its own answer: an environment nobody could read must not
        // be drawn as a mismatch, and must not be drawn as a pass either.
        const st = String(overall.state || 'unknown');
        const cls = st === 'pass' ? 'finance-note' : 'admin-env-warnings';
        const detail = (overall.gates || []).filter(g => g.state !== 'pass' && g.detail)
          .map(g => `<div class="cab-sub">${esc(g.label)} — ${esc(g.detail)}</div>`).join('');
        const src = overall.registry_source === 'peer' && overall.registry_origin
          ? `<div class="cab-sub">реестр прочитан у ${esc(overall.registry_origin)}</div>` : '';
        return `<div class="${cls}"><div><strong>${esc(overall.message || 'Состояние окружений не определено')}</strong>${overall.target_version ? ` · ${esc(overall.target_version)} · <span class="mono">${esc(overall.target_commit || '')}</span>` : ''}</div>${src}${detail}</div>`;
      })()}
      <div class="pipe-grid">
        ${pipeDevelopmentCard(envs.development || {}, doc.development_access)}
        ${pipeServerCard('Canary', envs.canary || {})}
        ${pipeServerCard('Production', envs.production || {})}
      </div>
      ${pipeCandidateHtml(doc)}
      ${pipeCompareHtml(doc.compare)}
      ${pipeHistoryHtml(doc.candidates)}
      ${pipeNotificationsHtml(doc.notification_preview)}
      <div class="flex gap-sm wrap"><button class="btn ghost" id="pipe-refresh">Обновить</button></div>`;

    qs('#pipe-refresh', node).onclick = again;
    pipeCreateForm(node, again);

    const openDev = qs('#pipe-open-dev', node);
    if (openDev) openDev.onclick = () => {
      // Only ever a loopback origin, and only in a new tab: the development
      // server is never published outward and never proxied through here.
      const origin = (doc.development_access || {}).origin || '';
      if (origin) window.open(origin + '/ui/', '_blank', 'noopener,noreferrer');
    };

    qsa('[data-release-open]', node).forEach(
      b => b.onclick = () => openReleaseDetail(b.dataset.releaseOpen));

    const previews = ((doc.notification_preview || {}).previews) || [];
    qsa('[data-pipe-banner]', node).forEach(b => b.onclick = () => {
      const kind = b.dataset.pipeBanner;
      const note = (doc.notification_preview || {}).note;
      if (kind === '*') {
        return showUpdateBannerPreview(
          ['warn_5m', 'warn_60s', 'deploy_successful']
            .map(k => previews.find(p => p.kind === k)).filter(Boolean), note, true);
      }
      showUpdateBannerPreview(previews.filter(p => p.kind === kind), note);
    });

    const msg = qs('#pipe-step-msg', node);
    // Publishing is one backend call. The panel shows the stages that call
    // reports and stops at the first failure with its reason, instead of a log.
    function publishStagesHtml(stages) {
      const icon = { passed: '✓', failed: '✕', not_started: '·' };
      return `<div class="pub-stages">${(stages || []).map(row => `<span class="pub-stage is-${esc(row.state)}">${icon[row.state] || '·'} ${esc(row.label)}</span>`).join('<span class="pub-sep">→</span>')}</div>`;
    }

    qsa('[data-pipe-publish]', node).forEach(button => button.onclick = async () => {
      const candidate = doc.candidate || {};
      const version = String(candidate.app_version || '');
      if (!window.confirm(
        'Опубликовать ' + version + '?' +
        '\n\n' +
        'В Production будет продвинут тот же проверенный artifact. Пересборки не будет.')) return;
      const box = qs('#pipe-publish-progress', node);
      const before = button.textContent;
      button.disabled = true;
      button.textContent = 'Публикую…';
      if (msg) msg.textContent = '';
      try {
        const out = await API.http.releasePublish(candidate.candidate_id, releaseKey());
        if (box) box.innerHTML = publishStagesHtml(out.stages);
        toast('Опубликовано в Production');
        await again();
      } catch (e) {
        // The failure carries how far the run got; show that, not just the text.
        const detail = (e && e.payload) || {};
        if (box) {
          // A failure after the deploy stage means Production is already
          // switched over. Saying "публикация не состоялась" there would send
          // the owner looking for a deployment that is live.
          const deployed = detail.production_deployed;
          box.innerHTML = publishStagesHtml(detail.stages) +
            `<div class="pub-outcome ${deployed ? 'is-deployed' : 'is-failed'}">${
              deployed
                ? 'Production развёрнут, validation failed'
                : 'Публикация не выполнена'}${
              detail.failed_stage ? ' · этап: ' + esc(detail.failed_stage) : ''}</div>` +
            (detail.closeout_blocked ? '<div class="cab-sub">Closeout заблокирован до устранения причины.</div>' : '') +
            (deployed && detail.rollback && detail.rollback.available
              ? '<div class="cab-sub">Откат — штатным действием «rollback-production» в разделе «Все действия».</div>'
              : '');
        }
        if (msg) msg.textContent = (e && e.message) || String(e);
        button.disabled = false;
        button.textContent = before;
      }
    });

    qsa('[data-pipe-step]', node).forEach(button => button.onclick = async () => {
      const step = button.dataset.pipeStep;
      const candidate = doc.candidate || {};
      if (step === 'promote-production' && !window.confirm(
        'Продвинуть в Production артефакт ' + String(candidate.artifact_sha256 || '').slice(0, 16) +
        '…\nБудут выполнены одобрение и промоушен того же артефакта, который принял Canary.')) return;
      const before = button.textContent;
      button.disabled = true;
      button.textContent = 'Выполняю…';
      if (msg) msg.textContent = '';
      try {
        const state = await pipeRunStep(candidate.candidate_id, step, candidate.state);
        toast('Состояние: ' + state);
        await again();
      } catch (e) {
        if (msg) msg.textContent = (e && e.message) || String(e);
        button.disabled = false;
        button.textContent = before;
      }
    });
  }

  // Both payloads describe the same three environments: targets carries the
  // origins and the release summary, the pipeline carries the candidate and the
  // promotion gates. The panel needs both to show one action per stage, and a
  // failure to reach the pipeline must not blank the environments.
  let ENV_PANEL_TIMER = 0;

  async function renderEnvironmentSwitcherInto(node) {
    if (!node.querySelector('.stage-flow')) {
      node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка environments…</div>';
    }
    try {
      const targets = await API.http.adminEnvironmentTargets();
      // Load figures come from /api/health, which is authenticated per
      // origin: this session can read them for the environment it is signed
      // in to and for no other. The rest render as unavailable.
      const current = ((targets && targets.targets) || []).find(t => t.current);
      if (current) {
        try { current.health_metrics = await API.http.health(); }
        catch (e) { current.health_metrics = null; }
      }
      let pipeline = null;
      try { pipeline = await API.http.adminPipeline(); } catch (e) { pipeline = null; }
      renderEnvironmentTargets(node, targets, pipeline);
      // The panel keeps itself current; the owner should not have to press a
      // button to find out what an environment is running.
      if (ENV_PANEL_TIMER) clearTimeout(ENV_PANEL_TIMER);
      ENV_PANEL_TIMER = setTimeout(() => {
        if (document.body.contains(node)) renderEnvironmentSwitcherInto(node);
      }, 20000);
    } catch (e) {
      renderError(node, e, () => renderEnvironmentSwitcherInto(node));
    }
  }

  async function showEnvironmentSwitcher() {
    if (!hasAdminCapability('environment.switch')) return;
    const d = drawer('<h3>Environment Switcher</h3>', '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>');
    await renderEnvironmentSwitcherInto(qs('.drawer-b', d));
  }

  // ---- Release Center (Phase 8) ---------------------------------------------
  function releaseKey() {
    return 'ui-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  function releaseStateClass(state) {
    if (['production_live', 'canary_passed'].includes(state)) return 'live';
    if (['build_failed', 'canary_failed', 'production_failed'].includes(state)) return 'failed';
    if (['rolled_back', 'superseded', 'cancelled'].includes(state)) return 'archived';
    return 'trial';
  }

  function shortSha(value) { return String(value || '').slice(0, 12) || '—'; }

  function releaseAdapterSummary(adapter) {
    const mode = esc(adapter.mode || 'dry_run');
    if (adapter.real_available) {
      const production = adapter.production_available
        ? 'Production executor разрешён текущим отдельным owner-gate.'
        : 'Production остаётся заблокирован до отдельного подтверждения владельца.';
      return `Развёртывание выполняется в режиме <strong>${mode}</strong>. Canary executor подключён и готов. ${production}`;
    }
    if (adapter.real_configured) {
      return `Развёртывание настроено в режиме <strong>${mode}</strong>, но executor сейчас недоступен; внешнее выполнение будет BLOCKED.`;
    }
    return `Развёртывание выполняется в режиме <strong>${mode}</strong>; инфраструктурный executor не настроен, поэтому внешний результат остаётся PENDING.`;
  }

  function releaseBlueGreenSummary(detail) {
    const bg = detail.blue_green || {};
    const adapter = detail.adapter || {};
    const prefix = `<strong>${esc(bg.strategy || 'blue_green_symlink')}</strong> · слоты ${esc((bg.slots || ['blue', 'green']).join('/'))} · символьная ссылка «${esc(bg.current_link || 'current')}». `;
    if (adapter.real_available) {
      const production = adapter.production_available
        ? 'Production executor разрешён отдельным owner-gate.'
        : 'Production traffic switch заблокирован до отдельного подтверждения владельца.';
      return prefix + `Canary deploy и rollback rehearsal выполняются реальным executor с readiness/identity verification. ${production}`;
    }
    if (adapter.real_configured) {
      return prefix + 'Executor настроен, но недоступен; реальный deploy/rehearsal будет BLOCKED.';
    }
    return prefix + 'Инфраструктурный executor не настроен: доступен только безопасный dry-run plan с внешним результатом PENDING.';
  }

  function renderReleaseRow(r) {
    return `<div class="row" data-release-row="${esc(r.candidate_id)}">
      <div class="row-main">
        <div class="row-title">v${esc(r.app_version)} <span class="badge">${esc(r.release_channel)}</span>
          <span class="badge ${releaseStateClass(r.state)}">${esc(r.state)}</span></div>
        <div class="row-sub mono">commit ${esc(shortSha(r.git_commit_sha))} · build ${esc(r.build_id || '—')} · artifact ${esc(shortSha(r.artifact_sha256))} · подпись ${esc(r.signature_status || '—')}</div>
        <div class="row-sub">Canary: ${esc(r.canary_state || '—')} · Production: ${esc(r.production_state || '—')}${r.failure_reason ? ' · <span class="orch-err">' + esc(r.failure_reason) + '</span>' : ''}</div>
      </div>
      <button class="btn sm ghost" data-release-open="${esc(r.candidate_id)}">Детали</button>
    </div>`;
  }

  function releaseConfirm(action, detail) {
    const s = detail.summary || {};
    const lines = [
      `Действие: ${action}`,
      `Версия: v${s.app_version} (${s.release_channel})`,
      `Commit: ${s.git_commit_sha || '—'}`,
      `Build ID: ${s.build_id || '—'}`,
      `Artifact SHA: ${s.artifact_sha256 || '—'}`,
      `Manifest SHA: ${s.manifest_sha256 || '—'}`,
      `Подпись: ${s.signature_status || '—'}`,
      `Canary: ${s.canary_state || '—'} · Production: ${s.production_state || '—'}`,
      '',
      ((detail.adapter || {}).real_available
        ? 'Будет выполнено реальное развёртывание immutable artifact. Продолжить?'
        : 'Реальное развёртывание недоступно (dry-run/blocked). Продолжить?'),
    ];
    return window.confirm(lines.join('\n'));
  }

  function releaseActionButtons(detail) {
    const s = detail.summary || {};
    const state = s.state;
    const btns = [];
    const has = c => hasAdminCapability(c);
    const adapter = detail.adapter || {};
    const infraReady = !!adapter.real_available;
    const productionReady = !!adapter.production_available;
    const INFRA_ACTIONS = new Set(['deploy-canary', 'promote-production', 'mark-production-live', 'rollback-production']);
    const push = (action, label, critical) => {
      const prodAction = ['promote-production', 'mark-production-live', 'rollback-production'].includes(action);
      const blocked = INFRA_ACTIONS.has(action) && !(prodAction ? productionReady : infraReady);
      btns.push([action, label, critical, blocked]);
    };
    if (state === 'draft' && has('releases.create')) push('build', 'Собрать артефакт', false);
    if (state === 'built' && has('releases.create')) push('verify', 'Проверить подпись', false);
    if (state === 'signed' && has('releases.deploy_canary')) push('deploy-canary', 'Развернуть в Canary', true);
    if (state === 'canary_failed' && has('releases.deploy_canary')) push('deploy-canary', 'Повторить Canary (тот же артефакт)', true);
    if (state === 'canary_checking' && has('releases.deploy_canary')) {
      push('record-canary-check:pass', 'Отметить проверку: PASS (final)', false);
      push('record-canary-check:fail', 'Отметить проверку: FAIL', false);
    }
    if (state === 'canary_passed' && has('releases.promote_production')) push('approve-production', 'Одобрить Production', true);
    if (state === 'approved_for_production' && has('releases.promote_production')) {
      push('schedule-production', 'Запланировать', false);
      push('promote-production', 'Продвинуть в Production', true);
    }
    if (state === 'production_scheduled' && has('releases.promote_production')) push('promote-production', 'Продвинуть в Production', true);
    if (state === 'production_deploying' && has('releases.promote_production')) push('mark-production-live', 'Подтвердить production_live', true);
    if (['production_live', 'production_deploying', 'production_failed'].includes(state) && has('releases.rollback_production')) push('rollback-production', 'Откатить Production', true);
    if (!['production_live', 'rolled_back', 'superseded', 'cancelled'].includes(state) && has('releases.create')) push('cancel', 'Отменить', false);
    return btns;
  }

  async function openReleaseDetail(candidateId) {
    const d = drawer('<h3>Релиз</h3>', '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>');
    d.classList.add('wide');
    const body = qs('.drawer-b', d);
    let detail;
    try { detail = await API.http.adminRelease(candidateId); }
    catch (e) { return renderError(body, e, () => openReleaseDetail(candidateId)); }
    const s = detail.summary || {};
    const a = detail.artifact || {};
    const kv = (k, v) => `<div class="admin-env-meta"><div><span>${esc(k)}</span><strong class="mono">${esc(v || '—')}</strong></div></div>`;
    const deployments = (detail.deployments || []).map(dep => `<div class="row"><div class="row-main"><div class="row-title">${esc(dep.environment)} · <span class="badge ${releaseStateClass(dep.state)}">${esc(dep.state)}</span></div><div class="row-sub mono">artifact ${esc(shortSha(dep.artifact_sha256))} · adapter ${esc(dep.adapter)} · ${esc((dep.document || {}).external_result || '')}</div></div></div>`).join('') || '<div class="empty-state">Нет развёртываний.</div>';
    const checks = (detail.checks || []).map(c => `<div class="feat-row"><span>${esc(c.name)}</span><span class="badge ${c.result === 'pass' ? 'live' : (c.result === 'fail' ? 'failed' : 'archived')}">${esc(c.result)}</span></div>`).join('') || '<div class="empty-state">Проверок нет.</div>';
    const approvals = (detail.approvals || []).map(ap => `<div class="row-sub mono">approval ${esc(ap.status)} · artifact ${esc(shortSha(ap.artifact_sha256))} · by ${esc(ap.approved_by_legacy_id)}</div>`).join('') || '<div class="empty-state">Одобрений нет.</div>';
    const rollbacks = (detail.rollbacks || []).map(rb => `<div class="row-sub mono">rollback -> ${esc(shortSha(rb.to_artifact_id))} · ${esc(rb.reason || '')}</div>`).join('') || '<div class="empty-state">Откатов нет.</div>';
    const events = (detail.events || []).slice(-20).map(ev => `<div class="row-sub mono">${esc(ev.created_at_utc)} · ${esc(ev.event_type)} (${esc(ev.from_state)}→${esc(ev.to_state)})</div>`).join('') || '';
    const bg = detail.blue_green || {};
    const stepBadge = st => (st === 'dry_run' ? 'trial' : (st === 'blocked' ? 'failed' : (st === 'skipped' ? 'archived' : (st === 'pass' ? 'live' : 'archived'))));
    const steps = (detail.deploy_steps || []).map(sp => `<div class="feat-row"><span class="mono">${esc(sp.ordinal)}. ${esc(sp.stage)} <span class="cab-sub">(${esc(sp.environment)} ${esc(sp.active_slot || '?')}→${esc(sp.target_slot || '?')})</span></span><span class="badge ${stepBadge(sp.status)}">${esc(sp.status)}</span></div>`).join('') || '<div class="empty-state">Шагов деплоя пока нет (blue-green появляется при развёртывании/репетиции).</div>';
    const maint = (detail.maintenance || []).map(m => `<div class="row-sub mono">${esc(m.environment)} · ${esc(m.kind)} · ${esc(m.state)} · ${esc(m.reason || '')}</div>`).join('') || '<div class="empty-state">Окон обслуживания нет.</div>';
    const rehearsals = (detail.rehearsals || []).slice(-5).map(h => `<div class="row-sub mono">${esc(h.created_at_utc)} · ${esc(h.environment)} · online_safe=${h.online_safe ? 'да' : 'нет'}${(h.blocked_stages || []).length ? ' · blocked: ' + esc((h.blocked_stages || []).join(', ')) : ''}</div>`).join('') || '<div class="empty-state">Репетиций нет.</div>';
    body.innerHTML = `
      <div class="grid cols-3">
        <div class="kpi"><span>Состояние</span><strong>${esc(s.state)}</strong></div>
        <div class="kpi"><span>Версия</span><strong>v${esc(s.app_version)} ${esc(s.release_channel)}</strong></div>
        <div class="kpi"><span>Подпись</span><strong>${esc(a.signature_status || s.signature_status || '—')}</strong></div>
      </div>
      ${s.failure_reason ? `<div class="finance-note"><strong>Ошибка:</strong> ${esc(s.failure_reason)}</div>` : ''}
      <div class="section-title">Артефакт</div>
      ${kv('Build ID', a.build_id || s.build_id)}${kv('Commit', a.git_commit_sha || s.git_commit_sha)}${kv('Artifact SHA-256', a.artifact_sha256 || s.artifact_sha256)}${kv('Manifest SHA-256', a.manifest_sha256 || s.manifest_sha256)}${kv('Trust tier', a.trust_tier)}${kv('Immutable', a.immutable ? 'да' : '—')}
      <div class="section-title">Действия</div>
      <div class="flex gap-sm wrap" id="rc-actions"></div>
      <div class="cab-sub" id="rc-action-msg"></div>
      <div class="section-title">Развёртывания</div><div class="list">${deployments}</div>
      <div class="section-title">Blue-green деплой</div>
      <div class="finance-note">${releaseBlueGreenSummary(detail)}</div>
      <div class="flex gap-sm wrap" id="rc-bg-actions"></div>
      <div class="cab-sub" id="rc-bg-msg"></div>
      <div class="cap-panel">${steps}</div>
      <div class="section-title">Окна обслуживания</div><div>${maint}</div>
      <div class="section-title">Репетиции blue-green</div><div>${rehearsals}</div>
      <div class="section-title">Проверки Canary</div><div class="cap-panel">${checks}</div>
      <div class="section-title">Одобрения</div><div>${approvals}</div>
      <div class="section-title">Откаты</div><div>${rollbacks}</div>
      <div class="section-title">История</div><div>${events}</div>`;
    const actions = qs('#rc-actions', body);
    const msg = qs('#rc-action-msg', body);
    let blockedInfra = false;
    releaseActionButtons(detail).forEach(([action, label, critical, blocked]) => {
      if (blocked) {
        blockedInfra = true;
        const wrap = el('<span class="rc-blocked-action"></span>');
        const btn = el('<button class="btn ghost sm" disabled></button>');
        btn.textContent = label;
        btn.title = 'Заблокировано: инфраструктура не настроена';
        wrap.appendChild(btn);
        wrap.appendChild(el('<span class="badge failed">Заблокировано: инфраструктура не настроена</span>'));
        actions.appendChild(wrap);
        return;
      }
      const btn = el(`<button class="btn ${critical ? 'primary' : 'ghost'} sm"></button>`);
      btn.textContent = label;
      btn.onclick = () => runReleaseAction(candidateId, action, critical, detail, body);
      actions.appendChild(btn);
    });
    if (blockedInfra && msg) {
      const adapter = detail.adapter || {};
      msg.textContent = adapter.real_available && !adapter.production_available
        ? 'Canary executor готов. Production остаётся заблокирован до отдельного owner-подтверждения.'
        : 'Реальный deploy заблокирован: executor или целевое окружение не настроены.';
    }
    if (!actions.children.length) actions.innerHTML = '<span class="cab-sub">Нет доступных переходов для вашей роли в этом состоянии.</span>';
    const bgActions = qs('#rc-bg-actions', body);
    const bgMsg = qs('#rc-bg-msg', body);
    if (bgActions && (a.build_id || s.build_id) && hasAdminCapability('releases.deploy_canary')) {
      ['production', 'canary'].forEach(env => {
        const btn = el('<button class="btn ghost sm"></button>');
        const realCanary = env === 'canary' && (detail.adapter || {}).canary_available
          && ['canary_checking', 'canary_passed'].includes(s.state);
        btn.textContent = realCanary
          ? 'Проверить rollback в Canary (реально)'
          : 'План blue-green (' + env + ')';
        btn.onclick = async () => {
          if (realCanary && !confirm('Canary будет временно переключён на previous slot, проверен и возвращён на этот же immutable artifact. Продолжить?')) return;
          if (bgMsg) bgMsg.textContent = realCanary ? 'Проверяю rollback и возврат Canary…' : 'Строю dry-run plan…';
          try {
            const out = await API.http.adminReleaseRehearse(candidateId, { environment: env, idempotency_key: releaseKey() });
            const r = out.rehearsal || {};
            toast((realCanary ? 'Canary rollback rehearsal' : 'План') + ': online_safe=' + (r.online_safe ? 'да' : 'нет'));
            openReleaseDetail(candidateId);
          } catch (e) { if (bgMsg) bgMsg.textContent = e.message || String(e); }
        };
        bgActions.appendChild(btn);
      });
    }
  }

  async function runReleaseAction(candidateId, action, critical, detail, body) {
    const msg = qs('#rc-action-msg', body);
    if (critical && !releaseConfirm(action, detail)) return;
    let realAction = action;
    const payload = { idempotency_key: releaseKey() };
    if (action.startsWith('record-canary-check:')) {
      realAction = 'record-canary-check';
      const result = action.split(':')[1];
      payload.name = 'acceptance';
      payload.result = result;
      payload.final = result === 'pass';
    } else if (action === 'schedule-production') {
      const mode = window.prompt('Режим расписания: now / in_5m / in_15m / explicit', 'now') || 'now';
      payload.mode = mode.trim();
      if (payload.mode === 'explicit') payload.explicit_utc = (window.prompt('Время UTC (ISO-8601)', '') || '').trim();
    } else if (action === 'rollback-production') {
      payload.to_artifact_id = (window.prompt('artifact_id для отката (ранее развёрнутый в Production)', (detail.summary || {}).artifact_id || '') || '').trim();
      payload.reason = (window.prompt('Причина отката', '') || '').trim();
    }
    if (msg) msg.textContent = 'Выполняю…';
    try {
      await API.http.adminReleaseAction(candidateId, realAction, payload);
      toast('Готово');
      openReleaseDetail(candidateId);
    } catch (e) {
      if (e && e.code === 'step_up_required') {
        if (msg) msg.textContent = 'Требуется подтверждение действия (step-up). Владелец освобождён; делегированному администратору нужно подтвердить действие.';
      } else if (msg) { msg.textContent = e.message || String(e); }
    }
  }

  async function renderDelegatedUsersInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка users…</div>';
    try {
      const data = await API.http.authUsers();
      const users = data.users || [];
      node.innerHTML = `<div class="finance-note">Делегированный users.manage не позволяет выдавать тарифные или административные grants.</div><div class="list">${users.map(u => `<div class="row"><div class="row-main"><div class="row-title">${esc(userLabel(u))}${u.is_owner ? ' <span class="badge trial">owner</span>' : ''}</div><div class="row-sub">${esc(u.status || '')} · ${esc(u.role || '')} · ${esc(u.username ? '@' + u.username : String(u.user_id || ''))}</div></div>${u.is_owner ? '' : `<button class="btn sm ghost" data-delegated-user="${esc(u.user_id)}">Детали</button>`}</div><div data-delegated-detail="${esc(u.user_id)}" hidden></div>`).join('') || '<div class="empty-state">Пользователей нет.</div>'}</div>`;
      qsa('[data-delegated-user]', node).forEach(button => button.onclick = async () => {
        const detail = qs(`[data-delegated-detail="${button.dataset.delegatedUser}"]`, node);
        if (!detail) return;
        detail.hidden = !detail.hidden;
        if (!detail.hidden) await renderUserDetail(detail, button.dataset.delegatedUser, node);
      });
    } catch (e) { renderError(node, e, () => renderDelegatedUsersInto(node)); }
  }

  async function renderAdminOperationsInto(node) {
    node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Проверка operations…</div>';
    try {
      const data = await withDeadline(API.http.adminOperations(), 'Operations');
      const worker = data.worker || {};
      const telegram = data.telegram || {};
      const connector = data.connector || {};
      const canExecute = hasAdminCapability('operations.execute');
      const deploymentEnvironment = String(
        (BUILD_IDENTITY && BUILD_IDENTITY.environment)
        || document.documentElement.dataset.deploymentEnvironment || '',
      ).toLowerCase();
      const localDiagnosticsAvailable = deploymentEnvironment === 'development';
      // Capability answers "may this person"; the descriptor answers "does this
      // environment do that at all". A restart a supervisor performs and one
      // this process improvises are different acts, and the button used to look
      // the same either way.
      const actions = data.actions || {};
      const opBtn = (id, label, key, cls) => {
        const rule = actions[key] || { allowed: true, reason: '' };
        return `<button class="btn ${rule.allowed ? (cls || 'ghost') : 'ghost'}" id="${id}"${
          rule.allowed ? '' : ' disabled'} title="${esc(rule.reason || label)}">${esc(label)}</button>`;
      };
      const opNotes = Object.values(actions).filter(r => r && !r.allowed && r.reason)
        .map(r => `<div>⚠ ${esc(r.reason)}</div>`).join('');
      node.innerHTML = `<div class="grid cols-3"><div class="kpi"><span>Worker</span><strong>${esc(worker.status || (worker.running ? 'running' : 'unknown'))}</strong></div><div class="kpi"><span>Telegram</span><strong>${esc(telegram.status || (telegram.ok ? 'ok' : 'unknown'))}</strong></div><div class="kpi"><span>Connector</span><strong>${esc(connector.status || (connector.ok ? 'ok' : 'unknown'))}</strong></div></div>
        <div class="section-title">Безопасные операции</div><div class="flex gap-sm wrap"><button class="btn ghost" id="admin-diagnostics"${localDiagnosticsAvailable ? '' : ' disabled'} title="${localDiagnosticsAvailable ? 'Локальный NinjaTrader и bridge log' : 'Локальные пути и bridge log не публикуются через Canary/Production edge'}">${localDiagnosticsAvailable ? 'Диагностика' : 'Локальная диагностика · DEV'}</button><button class="btn ghost" id="admin-env-status">Состояние environment</button>${hasAdminCapability('connectors.manage') ? '<button class="btn ghost" id="admin-telegram">Telegram / Connector</button>' : ''}</div>
        ${localDiagnosticsAvailable ? '' : '<div class="finance-note">Локальные пути NinjaTrader и bridge log доступны только в Development. Серверная диагностика Canary/Production показана в безопасной сводке Worker / Telegram / Connector выше.</div>'}
        ${canExecute ? `<div class="section-title">Операции с подтверждением</div>
          <div class="flex gap-sm wrap">
            ${opBtn('admin-restart', 'Перезапустить backend', 'restart', 'danger')}
            ${opBtn('admin-ai-unload', 'Освободить AI memory', 'ai_unload')}
            ${opBtn('admin-catalog-refresh', 'Обновить каталог', 'catalog_refresh')}
            ${opBtn('admin-margin-refresh', 'Пересчитать маржу', 'margin_refresh')}
          </div>
          ${opNotes ? `<div class="admin-env-warnings">${opNotes}</div>` : ''}`
          : '<div class="finance-note">operations.execute не выдан: restart/recovery controls скрыты.</div>'}`;
      const diagnostics = qs('#admin-diagnostics', node); if (diagnostics && !diagnostics.disabled) diagnostics.onclick = () => { closeDrawer(); showDiagnostics(); };
      const env = qs('#admin-env-status', node); if (env) env.onclick = () => { closeDrawer(); showEnvironment(false); };
      const telegramButton = qs('#admin-telegram', node); if (telegramButton) telegramButton.onclick = () => { closeDrawer(); showTelegram(); };
      const restart = qs('#admin-restart', node);
      if (restart && !restart.disabled) restart.onclick = () => {
        const mode = ((actions.restart || {}).mode === 'supervised')
          ? 'Супервизор перезапустит процесс.' : 'Процесс перезапустит сам себя.';
        if (confirm('Перезапустить backend? ' + mode)) {
          action('Backend restart', () => API.http.restartServer(), 'Backend перезапускается').catch(() => {});
        }
      };
      const unload = qs('#admin-ai-unload', node); if (unload && !unload.disabled) unload.onclick = () => action('AI memory', () => API.http.aiBootstrapUnload({ stop_server: true }), 'AI memory освобождена').catch(() => {});
      const catalog = qs('#admin-catalog-refresh', node); if (catalog && !catalog.disabled) catalog.onclick = () => action('Каталог', () => API.http.refreshCatalog(), 'Каталог обновлён').catch(() => {});
      const margins = qs('#admin-margin-refresh', node); if (margins && !margins.disabled) margins.onclick = () => action('Маржа', () => API.http.refreshMargins(), 'Маржа обновлена').catch(() => {});
    } catch (e) { renderError(node, e, () => renderAdminOperationsInto(node)); }
  }

  function adminOverviewHtml(data) {
    const deployment = data.deployment || {};
    const caps = data.admin_capabilities || {};
    const catalog = data.admin_capability_catalog || [];
    return `<div class="grid cols-3"><div class="kpi"><span>Среда</span><strong>${esc(deployment.deployment_environment || deployment.environment || '—')}</strong></div><div class="kpi"><span>Версия</span><strong>${esc(deployment.app_version || '—')}</strong></div><div class="kpi"><span>Commit</span><strong class="mono">${esc((deployment.git_commit_sha || '').slice(0, 12) || '—')}</strong></div></div><div class="finance-note"><strong>Контракт безопасности:</strong> секреты не выдаются; между средами не переносятся учётные данные, cookies, CSRF-токены и хранилище браузера.</div><div class="section-title">Действующие права доступа</div><div class="cap-panel">${catalog.map(c => `<div class="feat-row"><span>${esc(c.label)} <span class="cab-sub mono">${esc(c.id)}</span></span><span class="badge ${caps[c.id] ? 'live' : 'archived'}">${caps[c.id] ? 'разрешено' : 'нет'}</span></div>`).join('')}</div>`;
  }

  // Users and sessions, one module. Monitoring was a separate owner entry
  // showing who is online and which sessions exist -- facts about exactly the
  // people the user list is about. Keeping them apart meant answering "is this
  // account being used right now" required leaving the account you were
  // looking at.
  async function renderUsersAndSessionsInto(node, initial) {
    const owner = !!(CURRENT_AUTH && CURRENT_AUTH.is_owner);
    if (!owner) return renderDelegatedUsersInto(node);

    const tabs = [['users', 'Пользователи'], ['monitoring', 'Мониторинг и сессии']];
    const start = tabs.some(t => t[0] === initial) ? initial : 'users';
    node.innerHTML = `<div class="cab-tabs">${tabs.map(
      ([id, label]) => `<button class="cab-tab ${id === start ? 'on' : ''}" data-users-tab="${id}">${label}</button>`
    ).join('')}</div><div data-users-body></div>`;

    const body = qs('[data-users-body]', node);
    const show = (which) => {
      qsa('[data-users-tab]', node).forEach(b => b.classList.toggle('on', b.dataset.usersTab === which));
      if (which === 'monitoring') renderMonitoringInto(body);
      else renderUsersInto(body);
    };
    qsa('[data-users-tab]', node).forEach(b => b.onclick = () => show(b.dataset.usersTab));
    show(start);
  }

  async function renderAdminModule(node, moduleId, overview) {
    if (moduleId === 'overview') { node.innerHTML = adminOverviewHtml(overview); return; }
    if (moduleId === 'users') return renderUsersAndSessionsInto(node);
    // Monitoring is a tab of that module now; the old id opens it directly.
    if (moduleId === 'monitoring') return renderUsersAndSessionsInto(node, 'monitoring');
    if (moduleId === 'operations') return renderAdminOperationsInto(node);
    if (moduleId === 'pipeline') return renderPipelineInto(node);
    // The two former modules are one now. Their ids stay routable so an
    // existing deep link lands in the merged view rather than on nothing.
    if (moduleId === 'environments') return renderPipelineInto(node);
    if (moduleId === 'releases') return renderPipelineInto(node);
    if (moduleId === 'requests') return renderRequestsInto(node);

    // Documents left Admin: governance and workspace specifications are one
    // surface in the main menu now, because half the documents living behind
    // an operator panel meant nobody could answer "where are the documents"
    // without first knowing which kind they meant. Old ids point there rather
    // than rendering an empty panel.
    if (['docs', 'docs-global', 'docs-workspace'].includes(moduleId)) {
      node.innerHTML = `<div class="finance-note">Документы переехали в главное меню —
        один раздел для governance-документов и спецификаций рабочих областей.</div>
        <div class="flex gap-sm"><a class="btn primary" href="documents.html">Открыть Документы</a></div>`;
      return;
    }
    if (moduleId === 'subscriptions') {
      node.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>';
      try { return renderPlansInto(node, await API.http.authMe(), 'admin'); }
      catch (e) { return renderError(node, e, () => renderAdminModule(node, moduleId, overview)); }
    }
    if (moduleId === 'invites') return renderInvitesInto(node);
    if (moduleId === 'payment') return renderPaymentInto(node);
    if (moduleId === 'ai-ratings') return renderAiRatingsInto(node);
    if (moduleId === 'journal') return renderJournalInto(node);
    if (moduleId === 'staging') return renderStagingInto(node);
    if (moduleId === 'connectors') {
      await renderConnectorsInto(node);
      return;
    }
    const meta = (overview.modules || []).find(row => row.id === moduleId) || {};
    node.innerHTML = `<div class="cab-card"><h4>${esc(meta.label || moduleId)}</h4><p class="cab-sub">Для этого раздела пока нет отдельного интерфейса. Он появится в списке только когда за ним будет реальный backend-workflow.</p></div>`;
  }

  async function openAdminPanel(initialModule) {
    if (!hasAdminCapability('admin.view')) { toast('Панель администратора недоступна.'); return; }
    const d = drawer('<h3>Панель администратора</h3>', '<div class="state-loading"><span class="spinner"></span>Загрузка прав доступа…</div>');
    d.classList.add('wide');
    const body = qs('.drawer-b', d);
    try {
      const overview = await API.http.adminOverview();
      CURRENT_AUTH.admin_capabilities = overview.admin_capabilities || {};
      const modules = overview.modules || [];
      const start = modules.some(row => row.id === initialModule) ? initialModule : 'overview';
      const groupOrder = [];
      const grouped = new Map();
      modules.forEach(row => {
        const g = row.group || '';
        if (!grouped.has(g)) { grouped.set(g, []); groupOrder.push(g); }
        grouped.get(g).push(row);
      });
      const navHtml = groupOrder.map(g => {
        const items = grouped.get(g).map(row => `<button class="admin-module" data-admin-module="${esc(row.id)}" title="${esc(row.capability)}"><span>${esc(row.label)}</span></button>`).join('');
        return (g ? `<div class="admin-module-group">${esc(g)}</div>` : '') + items;
      }).join('');
      body.innerHTML = `<div class="admin-shell"><nav class="admin-modules">${navHtml}</nav><main class="admin-module-body" id="admin-module-body"></main></div>`;
      const moduleBody = qs('#admin-module-body', body);
      let renderSeq = 0;
      const select = async id => {
        const seq = ++renderSeq;
        qsa('[data-admin-module]', body).forEach(button => button.classList.toggle('on', button.dataset.adminModule === id));
        const container = el('<div class="admin-module-render"></div>');
        moduleBody.replaceChildren(container);
        try {
          await renderAdminModule(container, id, overview);
        } catch (e) {
          if (seq === renderSeq) renderError(container, e, () => select(id));
        }
      };
      qsa('[data-admin-module]', body).forEach(button => button.onclick = () => select(button.dataset.adminModule));
      await select(start);
    } catch (e) { renderError(body, e, () => { closeDrawer(); openAdminPanel(initialModule); }); }
  }

  const ENV_SEGMENTS = [
    { env: 'development', short: 'DEV', title: 'Local DEV' },
    { env: 'canary', short: 'CANARY', title: 'Canary' },
    { env: 'production', short: 'PROD', title: 'Production' },
  ];

  async function wireAdminEnvironmentButton() {
    const right = qs('.tb-right');
    if (!right) return;
    let host = qs('#admin-env-switcher');
    if (!hasAdminCapability('environment.switch')) { if (host) host.remove(); return; }
    if (!host) {
      host = el('<div class="env-seg" id="admin-env-switcher" role="group" aria-label="Переключение окружения"></div>');
      const more = qs('#tb-more', right);
      right.insertBefore(host, more || right.firstChild);
    }
    const current = String((BUILD_IDENTITY && BUILD_IDENTITY.environment)
      || document.documentElement.dataset.deploymentEnvironment
      || ((CURRENT_AUTH && CURRENT_AUTH.runtime && (CURRENT_AUTH.runtime.deployment || CURRENT_AUTH.runtime).deployment_environment))
      || 'development').toLowerCase();
    let byEnv = host._envTargets || {};
    if (!host._envLoaded) {
      host.innerHTML = ENV_SEGMENTS.map(s => `<span class="env-seg-btn ${s.env}${current === s.env ? ' on' : ''}">${s.short}</span>`).join('');
      try {
        const data = await API.http.adminEnvironmentTargets();
        byEnv = {}; (data.targets || []).forEach(t => { byEnv[t.environment] = t; });
        host._envTargets = byEnv; host._envLoaded = true;
      } catch (e) { /* keep static labels; drawer still available */ }
    }
    host.innerHTML = ENV_SEGMENTS.map(s => {
      const t = byEnv[s.env] || {};
      const isCurrent = current === s.env;
      const openable = isCurrent || !!t.open_allowed;
      const title = `${s.title}${isCurrent ? ' · текущая' : (openable ? ' · открыть в новой вкладке' : ' · origin не настроен')}`;
      return `<button type="button" class="env-seg-btn ${s.env}${isCurrent ? ' on' : ''}" data-env-seg="${s.env}" title="${esc(title)}"${(openable || isCurrent) ? '' : ' data-env-unset="1"'}>${s.short}</button>`;
    }).join('') + '<button type="button" class="env-seg-more" title="Подробнее об окружениях" aria-label="Подробнее">⋯</button>';
    qsa('[data-env-seg]', host).forEach(b => b.onclick = () => {
      const env = b.dataset.envSeg;
      const t = (host._envTargets || {})[env];
      if (current === env) { showEnvironmentSwitcher(); return; }
      if (t && t.open_allowed && env !== 'development') { openEnvironmentOrigin(t); return; }
      showEnvironmentSwitcher();
    });
    const moreBtn = qs('.env-seg-more', host);
    if (moreBtn) moreBtn.onclick = () => showEnvironmentSwitcher();
  }

  function isDevelopmentEnv() {
    const env = (BUILD_IDENTITY && BUILD_IDENTITY.environment)
      || document.documentElement.dataset.deploymentEnvironment || '';
    return String(env).toLowerCase() === 'development';
  }

  // Development-only: switch the localhost session between the owner and the
  // Claude / GPT service accounts (separate audit, same workspace + data).
  function devServiceMenuItems() {
    if (!isDevelopmentEnv()) return [];
    const loginAs = async (actor, label) => {
      try {
        await API.http.devServiceLogin(actor);
        toast(actor === 'owner' ? 'Сессия владельца' : ('Служебный вход: ' + label));
        location.reload();
      } catch (e) { reportError(e); }
    };
    return [
      { divider: true },
      { icon: 'cpu', label: 'Войти как Claude (dev)', onClick: () => loginAs('claude', 'Claude') },
      { icon: 'cpu', label: 'Войти как GPT (dev)', onClick: () => loginAs('gpt', 'GPT') },
      { icon: 'users', label: 'Вернуться к владельцу (dev)', onClick: () => loginAs('owner', 'владелец') },
    ];
  }

  function wireTopbar() {
    const more = qs('#tb-more');
    if (more) more.onclick = (e) => {
      e.stopPropagation();
      const systemItems = [
        { icon: 'users', label: 'Кабинет', onClick: () => openCabinet() },
        ...(hasAdminCapability('admin.view') ? [{ icon: 'cpu', label: 'Панель администратора', onClick: () => openAdminPanel() }] : []),
        ...(devPreviewAvailable() ? [{ icon: 'eye', label: 'Developer Preview', onClick: () => openDevPreviewPanel() }] : []),
        { icon: 'palette', label: 'Настройки дизайна', onClick: () => showDesignSettings() },
        { divider: true },
        { icon: 'back', label: 'Выйти из аккаунта', onClick: async () => { try { await API.http.authLogout(); location.reload(); } catch (error) { reportError(error); } } },
      ];
      menu(more, systemItems);
    };
    wireAdminEnvironmentButton();
    wireDevPreviewButton();
    renderDevPreviewBanner();
  }

  function environmentHtml(result) {
    result = result || {};
    const steps = result.steps || [];
    const readiness = result.readiness || (result.status && result.status.components && result.status.components.lm_studio_server) || (result.components && result.components.lm_studio_server) || {};
    return `<div class="list">${steps.length ? steps.map(step => `<div class="row"><div class="row-main"><div class="row-title">${esc(step.component || 'компонент')}</div><div class="row-sub">${esc(step.status || step.stderr || step.stdout || '')}</div></div><span class="badge ${step.ok ? 'live' : 'failed'}">${step.ok ? 'готово' : 'ошибка'}</span></div>`).join('') : '<div class="empty-state">Действия запуска ещё не выполнялись.</div>'}</div>
      <div class="finance-note"><strong>LM Studio:</strong> ${esc(readiness.message_ru || readiness.status || 'статус проверяется')}<br><strong>Run allowed:</strong> ${readiness.run_allowed ? 'да' : 'нет'} · <strong>Models:</strong> ${esc((readiness.models || []).join(', ') || 'нет данных')}</div>
      <div class="flex gap-sm"><button class="btn" id="env-refresh">Обновить статус</button><button class="btn ghost" data-close-drawer>Закрыть</button></div>`;
  }

  async function showEnvironment(start) {
    if (!window.API || API.config.offline) { toast('Управление окружением недоступно в офлайн-превью'); return; }
    const d = drawer('<h3>Окружение StratForge AI</h3>', '<div class="state-loading"><span class="spinner"></span>Проверка компонентов…</div>');
    const body = qs('.drawer-b', d);
    async function refresh() {
      try {
        const result = start ? await API.http.aiBootstrapStart({ load_models: true, wait_readiness: false }) : await API.http.aiBootstrapStatus();
        start = false;
        body.innerHTML = environmentHtml(result);
        const button = qs('#env-refresh', body);
        if (button) button.onclick = () => { body.innerHTML = '<div class="state-loading"><span class="spinner"></span>Обновление…</div>'; refresh(); };
      } catch (e) { renderError(body, e, refresh); }
    }
    await refresh();
  }

  // ---- global search ----------------------------------------------------------
  // offline preview index (file://) — uses the MOCK facade
  function buildSearchIndexMock() {
    const A = window.API; const idx = [];
    NAV.forEach(n => idx.push({ label: n.label, sub: 'раздел', href: n.href, icon: n.icon }));
    (A.strategies || []).forEach(s => idx.push({ label: s.name, sub: `стратегия · ${s.cellId} · ${s.root}`, href: 'strategies.html', icon: 'strategies' }));
    (A.reports || []).forEach(rp => idx.push({ label: rp.label, sub: `отчёт №${rp.no} · ${rp.strategy}`, href: 'backtesting.html', icon: 'backtest' }));
    (A.ROOTS || []).forEach(r0 => idx.push({ label: `${r0.sym} — ${r0.name}`, sub: `инструмент · ${r0.group}`, href: 'backtesting.html', icon: 'coins' }));
    (A.documents || []).forEach(d => idx.push({ label: d.title, sub: `документ · ${d.cat}`, href: 'documents.html', icon: 'docs' }));
    return idx;
  }
  // real backend index (served) — strategies / jobs / documents / instruments + deep links
  async function buildSearchIndexReal() {
    const idx = [];
    NAV.forEach(n => idx.push({ label: n.label, sub: 'раздел', href: n.href, icon: n.icon }));
    const safe = async (p) => { try { return await p; } catch (e) { return null; } };
    const [profiles, reports, docs, cov] = await Promise.all([
      safe(API.http.profiles()), safe(API.http.reports({ limit: 250 })),
      safe(API.http.governanceDocuments()), safe(API.http.coverage()),
    ]);
    ((profiles && profiles.profiles) || []).forEach(s => {
      const name = s.name || s.strategy_name || s.class_name || s.id || '—';
      idx.push({ label: name, sub: `стратегия · ${[s.cell_id || s.cell, s.root || s.instrument_root].filter(Boolean).join(' · ')}`, href: 'strategies.html?strategy=' + encodeURIComponent(name), icon: 'strategies' });
    });
    ((reports && reports.jobs) || []).forEach(j => {
      const lbl = j.label || j.class_name || j.strategy || j.job_id || 'отчёт';
      idx.push({ label: lbl, sub: `отчёт · ${j.status || ''}`, href: 'backtesting.html?job=' + encodeURIComponent(j.job_id || ''), icon: 'backtest' });
    });
    ((docs && docs.documents) || []).forEach(d => {
      idx.push({ label: d.title || d.id, sub: `документ · ${d.category || d.group || ''}`, href: 'documents.html?doc=' + encodeURIComponent(d.id || ''), icon: 'docs' });
    });
    ((cov && cov.instruments) || []).forEach(c => {
      idx.push({ label: c.root, sub: `инструмент · ${c.group || ''} · ${c.strategy_count || 0} проф.`, href: 'backtesting.html?instrument=' + encodeURIComponent(c.root), icon: 'coins' });
    });
    return idx;
  }
  function wireSearch() {
    const input = qs('#global-search'); const box = qs('#search-results');
    if (!input || !box) return;
    const offline = !window.API || API.config.offline;
    let index = null, indexPromise = null, items = [];
    function close() { box.hidden = true; box.innerHTML = ''; items = []; }
    function ensureIndex() {
      if (index) return Promise.resolve(index);
      if (!indexPromise) {
        indexPromise = (offline ? Promise.resolve(buildSearchIndexMock()) : buildSearchIndexReal())
          .then(idx => { index = idx; return idx; })
          .catch(() => { index = null; return null; });
      }
      return indexPromise;
    }
    function render(q) {
      items = index.filter(e => e.label.toLowerCase().includes(q) || (e.sub || '').toLowerCase().includes(q)).slice(0, 8);
      if (!items.length) { box.innerHTML = `<div class="search-empty">Ничего не найдено по «${esc(q)}»</div>`; box.hidden = false; return; }
      box.innerHTML = items.map((e, i) => `<a class="search-item ${i === 0 ? 'active' : ''}" href="${e.href}">${icon(e.icon)}<span class="si-main"><span class="si-label">${esc(e.label)}</span><span class="si-sub">${esc(e.sub)}</span></span></a>`).join('');
      box.hidden = false;
    }
    async function run(raw) {
      const q = raw.trim().toLowerCase();
      if (!q) { close(); return; }
      if (!index) { box.innerHTML = '<div class="search-empty"><span class="spinner"></span> Индексация…</div>'; box.hidden = false; await ensureIndex(); }
      if (!index) { box.innerHTML = '<div class="search-empty">Поиск недоступен</div>'; box.hidden = false; return; }
      if (input.value.trim().toLowerCase() === q) render(q);
    }
    input.addEventListener('input', () => run(input.value));
    input.addEventListener('focus', () => { ensureIndex(); if (input.value) run(input.value); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && items.length) { e.preventDefault(); window.location.href = items[0].href; }
      else if (e.key === 'Escape') { close(); input.blur(); }
    });
    document.addEventListener('click', (e) => { if (!e.target.closest('.tb-search-wrap')) close(); });
  }

  // dropdown menu anchored to a button
  function menu(anchor, items) {
    closeMenu();
    const m = el(`<div class="menu"></div>`);
    items.forEach(it => {
      if (it.divider) { m.appendChild(el('<div class="menu-sep"></div>')); return; }
      const row = el(`<button class="menu-item ${it.danger ? 'danger' : ''}">${it.icon ? icon(it.icon) : ''}<span>${it.label}</span></button>`);
      row.onclick = () => { closeMenu(); it.onClick && it.onClick(); };
      m.appendChild(row);
    });
    document.body.appendChild(m);
    const r = anchor.getBoundingClientRect();
    m.style.top = (r.bottom + 6) + 'px';
    m.style.right = (window.innerWidth - r.right) + 'px';
    requestAnimationFrame(() => m.classList.add('open'));
    document._menu = m;
    setTimeout(() => document.addEventListener('click', closeMenu, { once: true }), 0);
  }
  function closeMenu() { if (document._menu) { document._menu.remove(); document._menu = null; } }

  // pages inject contextual top-bar buttons here
  function pageActions(html) { const slot = qs('#page-actions'); if (slot) slot.innerHTML = html; return slot; }

  const READY = [];
  function ready(fn) {
    if (READY._done) { Promise.resolve().then(fn).catch(e => { if (!(e && e.name === 'AbortError')) reportError(e); }); }
    else READY.push(fn);
  }

  // ---- page lifecycle: cleanup of polls / aborts on navigation away ----------
  const CLEANUP = [];
  function onLeave(fn) { CLEANUP.push(fn); }
  function disposeAll() { while (CLEANUP.length) { try { CLEANUP.pop()(); } catch (e) { /* ignore */ } } }
  window.addEventListener('pagehide', disposeAll);
  window.addEventListener('beforeunload', disposeAll);
  window.addEventListener('unhandledrejection', (e) => { if (e.reason && e.reason.name === 'AbortError') return; reportError(e.reason || e); });

  // AbortController whose signal is auto-aborted when the page is left.
  function signal() { const c = new AbortController(); onLeave(() => c.abort()); return c.signal; }
  // Interval poll that is automatically cleared on navigation away. Returns stop().
  function poll(fn, ms) {
    let stopped = false, running = false;
    const tick = async () => {
      if (stopped || running) return;
      running = true;
      try { await fn(); }
      catch (e) { if (!(e && e.name === 'AbortError')) reportError(e); }
      finally { running = false; }
    };
    const id = setInterval(tick, ms);
    const stop = () => { stopped = true; clearInterval(id); };
    onLeave(stop);
    tick();
    return stop;
  }

  // ---- consent-based support bridge + per-tab telemetry ----------------------
  let SUPPORT_BRIDGE_STARTED = false;
  function supportClientId() {
    const key = 'stratforge.support.client-id';
    try {
      let value = sessionStorage.getItem(key) || '';
      if (!value) {
        value = (window.crypto && typeof window.crypto.randomUUID === 'function')
          ? window.crypto.randomUUID()
          : 'client-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
        sessionStorage.setItem(key, value);
      }
      return value;
    } catch (e) { return 'client-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2); }
  }
  function supportDeviceIdentity(clientId) {
    const key = 'stratforge.support.device-id';
    let id = '';
    try {
      id = localStorage.getItem(key) || '';
      if (!id) {
        id = (window.crypto && typeof window.crypto.randomUUID === 'function')
          ? window.crypto.randomUUID()
          : 'device-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
        localStorage.setItem(key, id);
      }
    } catch (e) { id = clientId; }
    const ua = String(navigator.userAgent || '').toLowerCase();
    const browser = ua.includes('edg/') ? 'Edge' : ua.includes('firefox') ? 'Firefox' : ua.includes('chrome') ? 'Chrome' : ua.includes('safari') ? 'Safari' : 'Браузер';
    const platform = String((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || '').slice(0, 60);
    return { id, name: [browser, platform].filter(Boolean).join(' · ') || 'Это устройство', browser, platform };
  }
  function blobFromCanvas(canvas, quality) {
    return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Не удалось сформировать изображение.')), 'image/jpeg', quality));
  }
  function dataUrlFromBlob(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ''));
      reader.onerror = () => reject(new Error('Не удалось прочитать снимок.'));
      reader.readAsDataURL(blob);
    });
  }
  async function captureSharedScreen() {
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getDisplayMedia !== 'function') {
      throw new Error('Этот браузер не поддерживает безопасный выбор экрана.');
    }
    const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 1 }, audio: false });
    try {
      const video = document.createElement('video');
      video.muted = true; video.playsInline = true; video.srcObject = stream;
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Экран не успел подготовиться.')), 8000);
        video.onloadedmetadata = () => { clearTimeout(timer); video.play().then(resolve).catch(reject); };
      });
      const sourceW = Math.max(1, Number(video.videoWidth || 1));
      const sourceH = Math.max(1, Number(video.videoHeight || 1));
      let scale = Math.min(1, 1600 / sourceW, 1000 / sourceH);
      const canvas = document.createElement('canvas');
      let blob = null;
      for (let attempt = 0; attempt < 5; attempt++) {
        canvas.width = Math.max(320, Math.round(sourceW * scale));
        canvas.height = Math.max(180, Math.round(sourceH * scale));
        const ctx = canvas.getContext('2d', { alpha: false });
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        blob = await blobFromCanvas(canvas, Math.max(.48, .82 - attempt * .09));
        if (blob.size <= 650 * 1024) break;
        scale *= .82;
      }
      if (!blob || blob.size > 700 * 1024) throw new Error('Снимок слишком большой для защищённой отправки.');
      return { data_url: await dataUrlFromBlob(blob), width: canvas.width, height: canvas.height };
    } finally {
      stream.getTracks().forEach(track => track.stop());
    }
  }
  function showScreenshotConsent(request, clientId) {
    if (!request || qs('[data-support-consent]')) return;
    const overlay = el(`<div class="terms-modal support-consent" data-support-consent role="dialog" aria-modal="true" aria-label="Запрос снимка экрана">
      <div class="terms-modal-card"><div class="terms-modal-head"><strong>Запрос помощи: снимок экрана</strong></div>
      <div class="terms-modal-body"><p>Владелец StratForge AI просит одноразовый снимок, чтобы разобраться с проблемой.${request.note ? '<br><br><strong>Комментарий:</strong> ' + esc(request.note) : ''}</p>
        <div class="support-privacy-note">Снимок не делается скрытно. После согласия браузер отдельно предложит выбрать экран, окно или вкладку. Вы сами решаете, чем поделиться.</div>
        <div class="flex gap-sm support-consent-actions"><button class="btn primary" data-support-allow type="button">Выбрать экран и разрешить</button><button class="btn ghost" data-support-deny type="button">Отказать</button></div>
      </div></div></div>`);
    document.body.appendChild(overlay);
    const finish = () => overlay.remove();
    qs('[data-support-deny]', overlay).onclick = async () => {
      qsa('button', overlay).forEach(button => { button.disabled = true; });
      try { await API.http.supportScreenshotRespond({ client_id: clientId, request_id: request.request_id, decision: 'denied' }); }
      catch (e) { reportError(e); }
      finally { finish(); }
    };
    qs('[data-support-allow]', overlay).onclick = async () => {
      qsa('button', overlay).forEach(button => { button.disabled = true; });
      try {
        const shot = await captureSharedScreen();
        await API.http.supportScreenshotRespond({ client_id: clientId, request_id: request.request_id, decision: 'approved', data_url: shot.data_url, width: shot.width, height: shot.height });
        toast('Снимок защищённо отправлен владельцу');
      } catch (e) {
        const denied = e && (e.name === 'NotAllowedError' || e.name === 'AbortError');
        try { await API.http.supportScreenshotRespond({ client_id: clientId, request_id: request.request_id, decision: denied ? 'denied' : 'error', error: String((e && e.message) || e || '').slice(0, 240) }); }
        catch (sendError) { reportError(sendError); }
        if (!denied) reportError(e);
      } finally { finish(); }
    };
  }
  function startUserSupportBridge() {
    if (SUPPORT_BRIDGE_STARTED || !window.API || API.config.offline || !CURRENT_AUTH || CURRENT_AUTH.guest) return;
    SUPPORT_BRIDGE_STARTED = true;
    const clientId = supportClientId();
    const device = supportDeviceIdentity(clientId);
    let stopped = false, polling = false, reporting = false, lastBytes = 0, lastReportAt = performance.now(), busyMs = 0;
    let cpuAvailable = false, observer = null;
    try {
      observer = new PerformanceObserver(list => { list.getEntries().forEach(entry => { busyMs += Number(entry.duration || 0); }); });
      observer.observe({ type: 'longtask', buffered: true });
      cpuAvailable = true;
    } catch (e) { observer = null; }
    const resourceBytes = () => {
      try { return performance.getEntriesByType('resource').reduce((sum, entry) => sum + Number(entry.transferSize || entry.encodedBodySize || 0), 0); }
      catch (e) { return 0; }
    };
    const report = async () => {
      if (stopped || reporting) return;
      reporting = true;
      const now = performance.now();
      const elapsed = Math.max(1000, now - lastReportAt);
      const bytes = resourceBytes();
      const delta = Math.max(0, bytes - lastBytes);
      const memory = performance.memory || null;
      const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection || {};
      const cpu = cpuAvailable ? Math.min(100, busyMs / elapsed * 100) : 0;
      try {
        await API.http.supportTelemetry({
          client_id: clientId, device_id: device.id, device_name: device.name,
          client: device.browser, platform: device.platform,
          page: location.pathname + location.search, visible: document.visibilityState === 'visible',
          logical_cores: Number(navigator.hardwareConcurrency || 0), device_memory_gb: Number(navigator.deviceMemory || 0),
          cpu_main_thread_percent: cpu, cpu_core_equivalent: cpu / 100, cpu_available: cpuAvailable,
          js_heap_used_mb: memory ? Number(memory.usedJSHeapSize || 0) / 1048576 : 0,
          js_heap_limit_mb: memory ? Number(memory.jsHeapSizeLimit || 0) / 1048576 : 0,
          memory_available: !!memory, network_mb_per_min: delta / 1048576 * 60000 / elapsed,
          network_total_mb: bytes / 1048576, downlink_mbps: Number(connection.downlink || 0),
          rtt_ms: Number(connection.rtt || 0), effective_type: String(connection.effectiveType || ''),
        });
        lastBytes = bytes; lastReportAt = now; busyMs = 0;
      } catch (e) {
        if (e && e.status === 401) { stopped = true; location.reload(); }
      } finally { reporting = false; }
    };
    const check = async () => {
      if (stopped || polling) return;
      polling = true;
      try {
        const out = await API.http.supportPoll(clientId);
        const command = ((out && out.commands) || [])[0];
        if (command && command.type === 'reload') {
          await API.http.supportCommandAck(clientId, command.command_id, 'done', '');
          setTimeout(() => location.reload(), 120);
          return;
        }
        if (out && out.screenshot_request) showScreenshotConsent(out.screenshot_request, clientId);
      } catch (e) {
        if (e && e.status === 401) { stopped = true; location.reload(); }
      } finally { polling = false; }
    };
    const pollId = setInterval(check, 4000);
    const reportId = setInterval(report, 10000);
    onLeave(() => { stopped = true; clearInterval(pollId); clearInterval(reportId); if (observer) observer.disconnect(); });
    report(); check();
  }

  // A chart command can be issued from the global chat on any Aurora page.
  // When a canvas operation needs Desktop, acknowledge the navigation command
  // first and switch pages automatically; desktop.js then consumes the queued
  // draw/open/clear/snapshot operation. Headless snapshots never enqueue this.
  function startDesktopCommandBridge() {
    if (!window.API || (API.config && API.config.offline) || document.body.dataset.page === 'desktop') return;
    // The bridge only hops a global-chat chart command to the Desktop page and
    // polls /api/ops/runtime/chart-commands (live_read). A limited user without
    // the Desktop entitlement would otherwise loop on a 403 every 5s, so never
    // start it for them.
    const auth = CURRENT_AUTH || {};
    const feats = auth.features || (auth.user && auth.user.features) || {};
    const caps = auth.capabilities || {};
    if (!auth.is_owner && !feats.desktop && !caps.charts_realtime && !caps.live_read) return;
    let busy = false;
    poll(async () => {
      if (busy) return;
      busy = true;
      try {
        const out = await API.http.chartCommands({ status: 'pending' });
        const command = ((out && out.commands) || []).find(row => row && row.type === 'open_desktop_tab');
        if (!command) return;
        await API.http.ackChartCommand(command.id, 'done', { ok: true, navigation: 'desktop.html' });
        try { sessionStorage.setItem('stratforge.desktop.auto-open', command.id || '1'); } catch (e) { /* ignore */ }
        window.location.href = 'desktop.html';
      } catch (e) {
        // Best-effort background bridge: never surface entitlement/transient
        // errors as toasts or console noise.
      } finally {
        busy = false;
      }
    }, 5000);
  }

  // ---- standard async states (loading / empty / error+retry) -----------------
  function renderLoading(node, label) {
    if (node) node.innerHTML = `<div class="state-loading"><span class="spinner"></span>${esc(label || 'Загрузка…')}</div>`;
  }
  function renderEmpty(node, label) {
    if (node) node.innerHTML = `<div class="empty-state">${esc(label || 'Нет данных за выбранный период.')}</div>`;
  }
  function renderError(node, err, retry) {
    if (!node) return;
    if (isGuest() && err && (err.status === 401 || err.status === 403
        || /whitelist|не входит/i.test(String(err && err.message || '')))) {
      node.innerHTML = `<div class="empty-state">Данные недоступны · войдите в подтверждённый аккаунт.</div>`;
      return;
    }
    const msg = (err && err.message) ? err.message : String(err);
    node.innerHTML = `<div class="state-error">${icon('close')}<div><div class="se-title">Не удалось загрузить данные</div><div class="se-msg">${esc(msg).slice(0, 160)}</div></div><button class="btn sm" data-retry>${icon('refresh')}Повторить</button></div>`;
    const btn = node.querySelector('[data-retry]');
    if (btn && retry) btn.addEventListener('click', retry);
  }

  function startClock() {
    const node = qs('#clock'); const dateNode = qs('#pt-date'); if (!node) return;
    function tick() {
      // real Pacific time (the market clock the platform runs on)
      let txt;
      try {
        txt = new Date().toLocaleTimeString('ru-RU', { timeZone: 'America/Los_Angeles', hour: '2-digit', minute: '2-digit', second: '2-digit' });
      } catch (e) {
        txt = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      }
      node.textContent = txt + ' PT';
      if (dateNode) {
        try { dateNode.textContent = new Date().toLocaleDateString('ru-RU', { timeZone: AuroraDomain.PT_ZONE, weekday: 'long', day: 'numeric', month: 'long' }); }
        catch (e) { dateNode.textContent = new Date().toLocaleDateString('ru-RU'); }
      }
    }
    tick(); setInterval(tick, 1000);
  }

  // ---- toast ------------------------------------------------------------------
  function toast(msg) {
    let wrap = qs('.toast-wrap'); if (!wrap) { wrap = el('<div class="toast-wrap"></div>'); document.body.appendChild(wrap); }
    const t = el(`<div class="toast">${msg}</div>`); wrap.appendChild(t);
    setTimeout(() => { t.style.transition = 'opacity .3s, transform .3s'; t.style.opacity = '0'; t.style.transform = 'translateY(8px)'; setTimeout(() => t.remove(), 320); }, 2200);
  }

  // ---- in-app notices: one grouped card above the SF Chat launcher ------------
  const NOTICE = {
    shown: new Set(), timers: new Map(), started: false,
    unreadByConversation: {}, unreadCount: 0, panelOpen: false,
    graceUntil: 0, fading: false, interactWired: false,
    retryAfter: 0, inflight: false,
  };
  function canUseSFChatNotices() {
    return !!(window.API && !API.config.offline && !isGuest()
      && API.http && typeof API.http.sfChatConversations === 'function');
  }
  function canUseSystemNotices() {
    return !!(window.API && !API.config.offline && !isGuest()
      && CURRENT_AUTH && (CURRENT_AUTH.is_owner || CURRENT_AUTH.role === 'owner')
      && API.http && typeof API.http.notifications === 'function');
  }
  function canUseNotices() {
    return canUseSFChatNotices() || canUseSystemNotices();
  }
  function noticeWrap() {
    let wrap = qs('.sf-notice-wrap');
    if (!wrap) {
      wrap = el('<div class="sf-notice-wrap" aria-live="polite"></div>');
      document.body.appendChild(wrap);
    }
    return wrap;
  }
  function noticeVisibleInOpenChat(item) {
    const cid = String((item && item.conversation_id) || '');
    if (!ORCH.open) return false;
    if (!cid) return false;
    return cid === String(ORCH.currentId || '');
  }
  async function ackNotices(payload) {
    if (!canUseSystemNotices()) return null;
    try { return await API.http.notificationsAck(payload || {}); }
    catch (e) { return null; }
  }
  async function purgeReadNotices() {
    if (!canUseSystemNotices()) return;
    try { await API.http.notificationsClear({ mode: 'read' }); } catch (e) { /* ignore */ }
  }
  function updateBellBadge(count) {
    const bell = qs('#tb-bell');
    const badge = qs('#tb-bell-badge');
    if (!bell) return;
    bell.hidden = !canUseNotices();
    const n = Math.max(0, Number(count) || 0);
    NOTICE.unreadCount = n;
    if (!badge) return;
    if (n <= 0) { badge.hidden = true; badge.textContent = '0'; bell.classList.remove('has-unread'); return; }
    badge.hidden = false;
    badge.textContent = n > 99 ? '99+' : String(n);
    bell.classList.add('has-unread');
  }
  function updateNoticeFabBadge(count) {
    const fab = qs('#orch-fab'); if (!fab) return;
    let badge = qs('.orch-fab-notice', fab);
    const n = Math.max(0, Number(count) || 0);
    if (n <= 0) { if (badge) badge.remove(); return; }
    if (!badge) {
      badge = el('<span class="orch-fab-notice" aria-hidden="true"></span>');
      fab.appendChild(badge);
    }
    badge.textContent = n > 9 ? '9+' : String(n);
  }
  function applyUnreadConversationMap(map) {
    NOTICE.unreadByConversation = map && typeof map === 'object' ? map : {};
    if (qs('#orch-convos')) orchRenderConversations();
  }
  function dismissNoticeDom(id, opts) {
    const immediate = !!(opts && opts.immediate);
    const sel = (CSS && CSS.escape) ? CSS.escape(String(id || '')) : String(id || '');
    if (!sel) return;
    const node = qs(`.sf-notice[data-nid="${sel}"]`);
    const timer = NOTICE.timers.get(id);
    if (timer) { clearTimeout(timer); NOTICE.timers.delete(id); }
    if (!node) return;
    if (immediate) { node.remove(); return; }
    if (node.classList.contains('leaving')) return;
    node.classList.add('leaving');
    setTimeout(() => { if (node.parentNode) node.remove(); }, 780);
  }
  function dismissNoticesForConversation(cid) {
    const want = String(cid || '');
    if (!want) return;
    qsa('.sf-notice[data-cid]').forEach((node) => {
      if (String(node.dataset.cid || '') === want) dismissNoticeDom(node.dataset.nid);
    });
  }
  /** Soft-hide banners after user activity — stay unread in the bell. */
  function fadeAwayVisibleNotices() {
    const cards = qsa('.sf-notice:not(.leaving)');
    if (!cards.length) return;
    NOTICE.fading = true;
    cards.forEach((node, i) => {
      const id = String(node.dataset.nid || '');
      setTimeout(() => {
        node.classList.add('leaving');
        if (id) NOTICE.shown.add(id);
        const timer = NOTICE.timers.get(id);
        if (timer) { clearTimeout(timer); NOTICE.timers.delete(id); }
        setTimeout(() => { if (node.parentNode) node.remove(); }, 780);
      }, i * 90);
    });
    setTimeout(() => { NOTICE.fading = false; }, 90 * cards.length + 820);
  }
  function wireNoticeInteractionFade() {
    if (NOTICE.interactWired) return;
    NOTICE.interactWired = true;
    // A drawer sized in vw changes width with the window, and so does the room
    // left beside it.
    window.addEventListener('resize', syncNoticeOffset);
    let pending = null;
    const onInteract = (e) => {
      if (NOTICE.fading) return;
      if (Date.now() < NOTICE.graceUntil) return;
      const t = e && e.target;
      if (t && t.closest && t.closest('.sf-notice-wrap, #tb-bell, .drawer-back, .drawer')) {
        if (pending) { clearTimeout(pending); pending = null; }
        return;
      }
      if (!qs('.sf-notice:not(.leaving)')) return;
      // Debounce: brief pause after activity so a quick mouse twitch doesn't wipe it.
      if (pending) clearTimeout(pending);
      pending = setTimeout(() => {
        pending = null;
        if (Date.now() < NOTICE.graceUntil) return;
        if (qs('.sf-notice:hover')) return;
        fadeAwayVisibleNotices();
      }, 900);
    };
    ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart'].forEach((ev) => {
      window.addEventListener(ev, onInteract, { passive: true, capture: true });
    });
  }
  async function markNoticeRead(itemOrId, opts) {
    const item = (itemOrId && typeof itemOrId === 'object') ? itemOrId : { id: itemOrId };
    const id = String(item.id || '');
    const cid = String(item.conversation_id || (opts && opts.conversation_id) || '');
    if (id) {
      dismissNoticeDom(id);
      NOTICE.shown.add(id);
    }
    if (cid) dismissNoticesForConversation(cid);
    if (item.kind === 'human_message' && cid) {
      try { await API.http.sfChatRead(cid); } catch (e) { return null; }
      await refreshInAppNotices({ silent: true });
      return { ok: true };
    }
    const payload = {};
    if (id) payload.ids = [id];
    // Only clear the whole conversation when the user explicitly opened a notice
    // that belongs to it (openNotice). Polling / opening chat must NOT do this.
    if (cid && opts && opts.ackConversation) payload.conversation_id = cid;
    if (!payload.ids && !payload.conversation_id) return null;
    const res = await ackNotices(payload);
    // Drop consumed items from storage so the unread inbox stays truthful.
    if (id) {
      try { await API.http.notificationsDelete({ ids: [id] }); } catch (e) { /* ignore */ }
    }
    if (opts && opts.ackConversation) await purgeReadNotices();
    await refreshInAppNotices({ silent: true });
    return res;
  }
  async function openNotice(item) {
    const cid = String(item.conversation_id || '');
    if (item.kind === 'human_message' && cid) {
      await openSFChat({ conversationId: cid, conversationType: 'human' });
      await markNoticeRead(item, { ackConversation: true });
      await refreshInAppNotices({ silent: true });
      return;
    }
    await markNoticeRead(item, { ackConversation: !!cid });
    if (cid) {
      await openOrchestrator();
      if (cid !== ORCH.currentId) {
        try { await orchSelectConversation(cid); } catch (e) { /* ignore */ }
      }
    } else if (!ORCH.open) {
      await openOrchestrator();
    }
    await refreshInAppNotices({ silent: true });
  }
  // How many banners may be on screen at once, and how long an ordinary one
  // stays. Nothing bounded the stack before, and only user interaction cleared
  // it, so a quiet session accumulated cards until they covered the right-hand
  // side of the page -- including the panel the reader was working in.
  const NOTICE_MAX_VISIBLE = 1;
  const NOTICE_AUTO_DISMISS_MS = 7000;

  function trimNoticeStack() {
    // Oldest first: the stack is prepended, so the tail is the stale end. They
    // stay unread in the bell, so trimming loses nothing but the interruption.
    const cards = qsa('.sf-notice:not(.leaving)');
    for (const node of cards.slice(NOTICE_MAX_VISIBLE)) {
      dismissNoticeDom(String(node.dataset.nid || ''));
    }
  }

  function renderNotice(item) {
    const id = String(item.id || '');
    if (!id || NOTICE.shown.has(id) || qs(`.sf-notice[data-nid="${id}"]`)) return;
    NOTICE.shown.add(id);
    wireNoticeInteractionFade();
    // Stay visible long enough to read even if the mouse moves right away.
    NOTICE.graceUntil = Math.max(NOTICE.graceUntil, Date.now() + 9000);
    const wrap = noticeWrap();
    wrap.classList.add('has-notices');
    const urgent = !!item.urgent;
    const cid = String(item.conversation_id || '');
    const kicker = item.conversation_title
      ? String(item.conversation_title)
      : (urgent ? 'Срочно' : 'Уведомление');
    const preview = String(item.body || '').trim();
    const avatar = item.avatar_url
      ? `<span class="sf-notice-avatar"><img src="${esc(item.avatar_url)}" alt=""></span>`
      : `<span class="sf-notice-avatar ${item.kind === 'human_message' ? '' : 'ai'}">${item.kind === 'human_message'
        ? esc(String(item.title || '?').slice(0, 1).toUpperCase()) : sfChatMark()}</span>`;
    const more = Math.max(0, Number(item._more || 0));
    const card = el(`<button type="button" class="sf-notice ${urgent ? 'urgent' : ''}" data-nid="${esc(id)}" data-cid="${esc(cid)}">
      <span class="sf-notice-glow" aria-hidden="true"></span>
      <span class="sf-notice-top">
        <span class="sf-notice-source">${avatar}<span class="sf-notice-kicker">${esc(kicker)}</span></span>
        <span class="sf-notice-close" data-notice-close="${esc(id)}" title="Скрыть" aria-label="Скрыть">${icon('close')}</span>
      </span>
      <span class="sf-notice-title">${esc(item.title || 'Уведомление')}</span>
      ${preview ? `<span class="sf-notice-body">${esc(preview)}</span>` : ''}
      <span class="sf-notice-actions"><span>Открыть в чате</span><span class="ghost">Подробнее</span></span>
      ${more ? `<span class="sf-notice-more"><span>ещё ${more} уведомлен.</span><strong>+${more}</strong></span>` : ''}
    </button>`);
    card.addEventListener('click', (e) => {
      if (e.target.closest('[data-notice-close]')) {
        e.preventDefault(); e.stopPropagation();
        dismissNoticeDom(id);
        NOTICE.shown.add(id);
        return;
      }
      openNotice(item);
    });
    wrap.prepend(card);
    requestAnimationFrame(() => card.classList.add('in'));
    trimNoticeStack();
    // An ordinary notice retires on its own; one that needs a decision stays
    // until someone makes it. Auto-dismissing those would be the interface
    // deciding on the reader's behalf that nothing was needed.
    if (!urgent) {
      NOTICE.timers.set(id, setTimeout(() => dismissNoticeDom(id), NOTICE_AUTO_DISMISS_MS));
    }
    // Hovering a card is a reader in the middle of it; the timer restarts when
    // they leave rather than pulling the text out from under them.
    if (!urgent) {
      card.addEventListener('mouseenter', () => {
        const timer = NOTICE.timers.get(id);
        if (timer) { clearTimeout(timer); NOTICE.timers.delete(id); }
      });
      card.addEventListener('mouseleave', () => {
        if (NOTICE.timers.has(id) || !card.parentNode) return;
        NOTICE.timers.set(id, setTimeout(() => dismissNoticeDom(id), NOTICE_AUTO_DISMISS_MS));
      });
    }
  }
  async function unifiedNoticeData() {
    const items = [];
    const unreadByConversation = {};
    const humanConversations = [];
    let humanUnread = 0;
    let systemData = { items: [], unread_count: 0, unread_by_conversation: {} };
    if (canUseSFChatNotices()) {
      try {
        const data = await API.http.sfChatConversations();
        for (const conversation of data.conversations || []) {
          const unread = Math.max(0, Number(conversation.unread_count || 0));
          if (conversation.conversation_type !== 'human' || !unread) continue;
          const cid = String(conversation.conversation_id || '');
          humanConversations.push(conversation);
          humanUnread += unread;
          unreadByConversation[cid] = unread;
          const participant = conversation.participant || {};
          items.push({
            id: `sfchat:${String(conversation.last_message_id || cid)}:${unread}`,
            kind: 'human_message', conversation_id: cid,
            conversation_title: 'SF Chat · личное сообщение',
            title: String(conversation.title || participant.display_name || 'Новое сообщение'),
            body: String(conversation.last_message_preview || 'Новое сообщение'),
            created_at_utc: String(conversation.updated_at_utc || ''),
            avatar_url: String(participant.avatar_url || ''), urgent: false,
          });
        }
      } catch (e) { /* system notices may still remain available */ }
    }
    if (canUseSystemNotices()) {
      try { systemData = await API.http.notifications({ unread: 1, limit: 40 }); }
      catch (e) { systemData = { items: [], unread_count: 0, unread_by_conversation: {} }; }
      for (const [cid, count] of Object.entries(systemData.unread_by_conversation || {})) {
        unreadByConversation[cid] = Math.max(Number(unreadByConversation[cid] || 0), Number(count || 0));
      }
      items.push(...(systemData.items || []).map(row => ({ ...row, kind: row.kind || 'system' })));
    }
    items.sort((left, right) => String(right.created_at_utc || '').localeCompare(String(left.created_at_utc || '')));
    return {
      ok: true, items, human_conversations: humanConversations,
      system_items: systemData.items || [], unread_by_conversation: unreadByConversation,
      unread_count: humanUnread + Math.max(0, Number(systemData.unread_count || 0)),
    };
  }
  function noticeTimeLabel(iso) {
    if (!iso) return '';
    try {
      return new Intl.DateTimeFormat('ru-RU', {
        timeZone: (window.AuroraDomain && AuroraDomain.PT_ZONE) || 'America/Los_Angeles',
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      }).format(new Date(iso));
    } catch (e) { return String(iso).slice(0, 16); }
  }
  async function showNotificationsCenter() {
    if (!canUseNotices()) { toast('Уведомления доступны после входа'); return; }
    fadeAwayVisibleNotices();
    const d = drawer(
      `<span style="display:inline-flex;align-items:center;gap:8px">${icon('bell')} Уведомления</span>`,
      '<div class="state-loading"><span class="spinner"></span>Загрузка…</div>',
    );
    NOTICE.panelOpen = true;
    const render = async () => {
      const body = qs('.drawer-b', d); if (!body) return;
      let data;
      try { data = await unifiedNoticeData(); }
      catch (e) { renderError(body, e, render); return; }
      const items = (data && data.items) || [];
      const unread = Number((data && data.unread_count) || 0);
      applyUnreadConversationMap((data && data.unread_by_conversation) || {});
      updateBellBadge(unread);
      updateNoticeFabBadge(unread);
      const tools = `
        <div class="sf-inbox-toolbar">
          <p class="sf-inbox-lead">Новые ответы и события, пока вы в приложении. Откройте — и пункт исчезнет.</p>
          <div class="sf-inbox-actions">
            <button type="button" class="btn sm ghost" data-inbox-ack-all ${unread ? '' : 'disabled'}>Прочитать все</button>
            ${canUseSystemNotices() ? `<button type="button" class="btn sm danger" data-inbox-clear-all ${(data.system_items || []).length ? '' : 'disabled'}>Удалить системные</button>` : ''}
          </div>
        </div>`;
      if (!items.length) {
        body.innerHTML = tools + '<div class="empty-state">Нет новых уведомлений.</div>';
      } else {
        body.innerHTML = tools + `<div class="sf-inbox-list">${items.map((item, idx) => {
          const urgentCls = item.urgent ? ' urgent' : '';
          const preview = String(item.body || '').trim().slice(0, 180);
          return `<article class="sf-inbox-item unread${urgentCls}" data-inbox-id="${esc(item.id)}" style="--i:${idx}">
            <button type="button" class="sf-inbox-main" data-inbox-open="${esc(item.id)}">
              <div class="sf-inbox-meta">
                <span class="sf-inbox-title">${esc(item.title || 'Уведомление')}</span>
                <span class="sf-inbox-time">${esc(noticeTimeLabel(item.created_at_utc))}</span>
              </div>
              ${item.conversation_title ? `<div class="sf-inbox-thread">${esc(item.conversation_title)}</div>` : ''}
              ${preview ? `<div class="sf-inbox-body">${esc(preview)}</div>` : ''}
            </button>
            <div class="sf-inbox-acts">
              ${item.kind === 'human_message' ? '' : `<button type="button" class="btn sm ghost" data-inbox-del="${esc(item.id)}" title="Удалить">${icon('trash')}</button>`}
            </div>
          </article>`;
        }).join('')}</div>`;
      }
      const byId = Object.fromEntries(items.map((row) => [String(row.id), row]));
      const ackAll = qs('[data-inbox-ack-all]', body);
      if (ackAll) ackAll.onclick = async () => {
        try {
          const human = data.human_conversations || [];
          await Promise.all(human.map(row => API.http.sfChatRead(row.conversation_id)));
          const ids = (data.system_items || []).map((row) => row.id).filter(Boolean);
          if (ids.length) await API.http.notificationsAck({ ids });
          await purgeReadNotices();
          toast('Все прочитаны');
          await render();
          refreshInAppNotices({ silent: true });
        } catch (e) { reportError(e); }
      };
      const clearAll = qs('[data-inbox-clear-all]', body);
      if (clearAll) clearAll.onclick = async () => {
        if (!confirm('Удалить все системные уведомления? Личные сообщения останутся в SF Chat.')) return;
        try {
          await API.http.notificationsClear({ mode: 'all' });
          qsa('.sf-notice').forEach((n) => n.remove());
          toast('Уведомления очищены');
          await render();
          refreshInAppNotices({ silent: true });
        } catch (e) { reportError(e); }
      };
      qsa('[data-inbox-open]', body).forEach((btn) => btn.addEventListener('click', async () => {
        const item = byId[btn.dataset.inboxOpen]; if (!item) return;
        const row = btn.closest('.sf-inbox-item');
        if (row) {
          row.classList.add('removing');
          await new Promise((r) => setTimeout(r, 280));
        }
        closeDrawer();
        NOTICE.panelOpen = false;
        await openNotice(item);
      }));
      qsa('[data-inbox-del]', body).forEach((btn) => btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const row = btn.closest('.sf-inbox-item');
        try {
          await API.http.notificationsDelete({ ids: [btn.dataset.inboxDel] });
          dismissNoticeDom(btn.dataset.inboxDel);
          if (row) {
            row.classList.add('removing');
            await new Promise((r) => setTimeout(r, 280));
          }
          await render();
          refreshInAppNotices({ silent: true });
        } catch (err) { reportError(err); }
      }));
    };
    await render();
    const back = qs('.drawer-back');
    if (back) back.addEventListener('click', () => { NOTICE.panelOpen = false; }, { once: true });
  }
  function wireNotificationsBell() {
    const bell = qs('#tb-bell');
    if (!bell || bell._wired) return;
    bell._wired = true;
    bell.addEventListener('click', (e) => { e.stopPropagation(); showNotificationsCenter(); });
    updateBellBadge(NOTICE.unreadCount);
  }
  function startInAppNotices() {
    if (NOTICE.started) return;
    if (!canUseNotices()) return;
    NOTICE.started = true;
    wireNotificationsBell();
    wireNoticeInteractionFade();
    const bell = qs('#tb-bell'); if (bell) bell.hidden = false;
    // 12s is enough for live alerts without flooding the owner rate bucket.
    poll(() => refreshInAppNotices(), 12000);
  }
  async function refreshInAppNotices(opts) {
    if (!canUseNotices()) return;
    if (NOTICE.inflight) return;
    if (Date.now() < NOTICE.retryAfter) return;
    wireNotificationsBell();
    const silent = !!(opts && opts.silent);
    NOTICE.inflight = true;
    let data;
    try {
      data = await unifiedNoticeData();
      NOTICE.retryAfter = 0;
    } catch (e) {
      if (e && e.status === 429) {
        NOTICE.retryAfter = Date.now() + Math.max(20000, Number(e.retryAfterMs || 0));
      }
      return;
    } finally {
      NOTICE.inflight = false;
    }
    const items = (data && data.items) || [];
    const unread = Number((data && data.unread_count) || items.length || 0);
    applyUnreadConversationMap((data && data.unread_by_conversation) || {});
    updateBellBadge(unread);
    updateNoticeFabBadge(unread);
    const displayItems = items.filter(item => !noticeVisibleInOpenChat(item));
    for (const item of items) {
      // While the matching chat is open, skip the toast — but NEVER auto-ack.
      // Unread must stay in the bell until the user opens or clears it.
      if (noticeVisibleInOpenChat(item)) {
        dismissNoticeDom(String(item.id || ''));
        continue;
      }
    }
    if (!silent && displayItems.length) {
      const item = { ...displayItems[0], _more: Math.max(0, displayItems.length - 1) };
      renderNotice(item);
    }
  }

  // ---- drawer -----------------------------------------------------------------
  function drawer(titleHtml, bodyHtml) {
    let back = qs('.drawer-back');
    if (!back) {
      back = el('<div class="drawer-back"></div>');
      const d = el('<aside class="drawer"><div class="drawer-resize" aria-hidden="true"></div><div class="drawer-h"></div><div class="drawer-b"></div></aside>');
      document.body.appendChild(back); document.body.appendChild(d);
      back.addEventListener('click', closeDrawer);
      back._d = d;
      wireDrawerResize(d);
    }
    const d = back._d;
    d.style.width = '';
    d.classList.remove('wide', 'full', 'custom');
    qs('.drawer-h', d).innerHTML = `<div class="drawer-title">${titleHtml}</div><div class="drawer-tools"><button class="btn sm ghost" data-drawer-size="wide">Шире</button><button class="btn sm ghost" data-drawer-size="full">На весь экран</button><button class="btn icon ghost" data-close-drawer aria-label="Закрыть">${icon('close')}</button></div>`;
    qs('.drawer-b', d).innerHTML = bodyHtml;
    requestAnimationFrame(() => {
      back.classList.add('open');
      d.classList.add('open');
      // After the class lands, so the measurement sees the real width.
      syncNoticeOffset();
    });
    return d;
  }

  // The drawer owns the right-hand side, which is where notices land. Its width
  // is not a constant -- normal, wide, full, or dragged anywhere in between --
  // so the offset is measured rather than assumed. A guessed offset puts the
  // stack back on top of the panel in every case the guess did not cover.
  function syncNoticeOffset() {
    const open = qs('.drawer.open');
    const width = open ? Math.round(open.getBoundingClientRect().width) : 0;
    document.body.style.setProperty('--drawer-w', width + 'px');
    document.body.classList.toggle('has-drawer', !!open);
    // Below this there is no room beside the panel. Yield the space: the bell
    // still holds every notice, so nothing is lost by not drawing the banner.
    const room = window.innerWidth - width;
    document.body.classList.toggle('notices-cramped', !!open && room < 360);
  }
  function setDrawerSize(drawerNode, size) {
    drawerNode.style.width = '';
    drawerNode.classList.remove('wide', 'full', 'custom');
    if (size === 'wide') drawerNode.classList.add('wide');
    if (size === 'full') drawerNode.classList.add('full');
    syncNoticeOffset();
  }
  function wireDrawerResize(drawerNode) {
    const handle = qs('.drawer-resize', drawerNode);
    handle.addEventListener('pointerdown', event => {
      if (window.innerWidth <= 760) return;
      event.preventDefault();
      const startX = event.clientX;
      const startWidth = drawerNode.getBoundingClientRect().width;
      handle.setPointerCapture(event.pointerId);
      const move = current => {
        const width = Math.max(480, Math.min(window.innerWidth, startWidth + startX - current.clientX));
        drawerNode.classList.remove('wide', 'full');
        drawerNode.classList.add('custom');
        drawerNode.style.width = width + 'px';
        syncNoticeOffset();
      };
      const finish = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', finish);
        handle.removeEventListener('pointercancel', finish);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', finish);
      handle.addEventListener('pointercancel', finish);
    });
  }
  function closeDrawer() {
    const back = qs('.drawer-back');
    if (back) { back.classList.remove('open'); back._d.classList.remove('open'); }
    syncNoticeOffset();
  }

  // table sorting — safe to call repeatedly (clones headers to drop stale listeners)
  function sortable(table, rows, render) {
    let dir = -1, key = null;
    qsa('th.sortable', table).forEach(orig => {
      const th = orig.cloneNode(true);
      qsa('.arrow', th).forEach(a => a.remove());
      orig.replaceWith(th);
      th.addEventListener('click', () => {
        const k = th.dataset.sort;
        dir = key === k ? -dir : -1; key = k;
        rows.sort((a, b) => { const av = a[k], bv = b[k]; return (av < bv ? 1 : av > bv ? -1 : 0) * dir; });
        qsa('th.sortable .arrow', table).forEach(a => a.remove());
        th.insertAdjacentHTML('beforeend', `<span class="arrow"> ${dir < 0 ? '▼' : '▲'}</span>`);
        render(rows);
      });
    });
  }

  // ---- global orchestrator chat widget ---------------------------------------
  // Floating launcher (bottom-right) for Vitek, the owner's chief of staff.
  // chat with a conversation list, per-dialogue context, timestamps and titles.
  // Non-blocking: sending shows the message + a typing indicator immediately and
  // only awaits the reply; it never freezes the page.
  const ORCH = {
    built: false, open: false, sending: false,
    conversations: [], currentId: 'default', loadingList: false, pollStop: null,
    mode: 'auto', messagesSignature: '', feedbackVoice: null, loadError: null,
    retryAfter: 0, transientError: null, viewerProfileId: '', aiAvailable: null,
    pendingAttachments: [],
  };
  const ORCH_KEY = lsKey('orch.currentConversationId');
  const ORCH_SKIN_KEY = lsKey('orch.skin');
  const ORCH_SKIN_LEGACY = {
    ledger: 'terminal', pulse: 'slate', atelier: 'studio', mica: 'glass', signal: 'day',
  };
  const ORCH_SKINS = [
    { id: 'forge',    title: 'Forge',    sub: 'Стандарт · торговый терминал',     icon: 'chat',   fabTitle: 'SF Chat · Forge' },
    { id: 'terminal', title: 'Terminal', sub: 'Институциональный desk · amber',   icon: 'cpu',    fabTitle: 'SF Chat · Terminal' },
    { id: 'slate',    title: 'Slate',    sub: 'Современный продукт · Linear',     icon: 'spark',  fabTitle: 'SF Chat · Slate' },
    { id: 'studio',   title: 'Studio',   sub: 'Корпоративный светлый · Stripe',  icon: 'layers', fabTitle: 'SF Chat · Studio' },
    { id: 'glass',    title: 'Glass',    sub: 'Сдержанное стекло · Fluent',      icon: 'desktop', fabTitle: 'SF Chat · Glass' },
    { id: 'day',      title: 'Day',      sub: 'Светлый operations desk',         icon: 'chart',  fabTitle: 'SF Chat · Day' },
  ];
  function sfChatMark() {
    return '<span class="sf-chat-mark" aria-hidden="true"><i>S</i><i>F</i></span>';
  }
  function orchIsHumanConversation(value) {
    const row = typeof value === 'object' && value
      ? value
      : ORCH.conversations.find(c => c.conversation_id === String(value || ORCH.currentId));
    return !!((row && row.conversation_type === 'human')
      || String((row && row.conversation_id) || value || ORCH.currentId).startsWith('sfh_'));
  }
  function orchSkinMeta(id) {
    const mapped = ORCH_SKIN_LEGACY[id] || id;
    return ORCH_SKINS.find((s) => s.id === mapped) || ORCH_SKINS[0];
  }
  function orchLoadSkin() {
    try {
      const v = localStorage.getItem(ORCH_SKIN_KEY);
      const mapped = ORCH_SKIN_LEGACY[v] || v;
      return ORCH_SKINS.some((s) => s.id === mapped) ? mapped : 'forge';
    } catch (e) { return 'forge'; }
  }
  function orchApplySkin(id) {
    const skin = orchSkinMeta(id);
    if (document.documentElement) document.documentElement.setAttribute('data-orch-skin', skin.id);
    const fab = qs('#orch-fab');
    if (fab) {
      const badge = qs('.orch-fab-notice', fab);
      const badgeText = badge ? badge.textContent : '';
      fab.innerHTML = `${sfChatMark()}${badgeText ? `<span class="orch-fab-notice" aria-hidden="true">${esc(badgeText)}</span>` : ''}`;
      fab.title = skin.fabTitle;
      fab.setAttribute('aria-label', `Открыть ${skin.fabTitle}`);
    }
    const menu = qs('#orch-skin-menu');
    if (menu && !menu.hidden) orchRenderSkinMenu();
  }
  function orchSetSkin(id) {
    const skin = orchSkinMeta(id);
    try { localStorage.setItem(ORCH_SKIN_KEY, skin.id); } catch (e) { /* ignore */ }
    orchApplySkin(skin.id);
    const panel = qs('#orch-panel');
    if (panel) panel.classList.remove('show-convos');
  }
  function orchRenderSkinMenu() {
    const menu = qs('#orch-skin-menu');
    if (!menu) return;
    const cur = orchLoadSkin();
    menu.innerHTML = `<div class="orch-skin-menu-head">Облик чата</div>` + ORCH_SKINS.map((s) => `
      <button type="button" class="orch-skin-item ${s.id === cur ? 'active' : ''}" data-orch-skin-opt="${esc(s.id)}" title="${esc(s.sub)}">
        <span class="orch-skin-swatch" data-swatch="${esc(s.id)}" aria-hidden="true"><i></i><i></i></span>
        <span class="orch-skin-item-main">
          <span class="orch-skin-item-title">${esc(s.title)}</span>
          <span class="orch-skin-item-sub">${esc(s.sub)}</span>
        </span>
        <span class="orch-skin-item-check">${s.id === cur ? icon('check') : ''}</span>
      </button>`).join('');
    qsa('[data-orch-skin-opt]', menu).forEach((b) => b.addEventListener('click', () => {
      orchSetSkin(b.dataset.orchSkinOpt);
      orchCloseSkinMenu();
      toast(`Облик: ${orchSkinMeta(b.dataset.orchSkinOpt).title}`);
    }));
  }
  function orchOpenSkinMenu() {
    const menu = qs('#orch-skin-menu');
    const btn = qs('#orch-skin-btn');
    if (!menu || !btn) return;
    orchRenderSkinMenu();
    menu.hidden = false;
    btn.classList.add('on-skin');
    btn.setAttribute('aria-expanded', 'true');
  }
  function orchCloseSkinMenu() {
    const menu = qs('#orch-skin-menu');
    const btn = qs('#orch-skin-btn');
    if (menu) menu.hidden = true;
    if (btn) {
      btn.classList.remove('on-skin');
      btn.setAttribute('aria-expanded', 'false');
    }
  }
  function orchToggleSkinMenu() {
    const menu = qs('#orch-skin-menu');
    if (!menu) return;
    if (menu.hidden) orchOpenSkinMenu();
    else orchCloseSkinMenu();
  }
  orchApplySkin(orchLoadSkin());
  // Model selection is an internal responsibility of Vitek and the Manager.
  const ORCH_MODES = {
    auto:     { label: 'Авто',         agent: '',          sub: 'подбирает модель под задачу',      ph: 'Напишите задачу обычным текстом…' },
  };
  function orchLoadMode() {
    return 'auto';
  }
  function orchLoadLastId() {
    try { return localStorage.getItem(ORCH_KEY) || 'default'; } catch (e) { return 'default'; }
  }
  function orchSaveCurrentId(cid) {
    ORCH.currentId = String(cid || '');
    try {
      if (ORCH.currentId) localStorage.setItem(ORCH_KEY, ORCH.currentId);
      else localStorage.removeItem(ORCH_KEY);
    } catch (e) { /* ignore */ }
  }
  function orchFmtTime(iso) {
    if (!iso) return '';
    try {
      return new Intl.DateTimeFormat('ru-RU', {
        timeZone: (window.AuroraDomain && AuroraDomain.PT_ZONE) || 'America/Los_Angeles',
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
      }).format(new Date(iso));
    } catch (e) { return String(iso).slice(0, 16); }
  }
  function buildOrchestratorWidget() {
    if (ORCH.built || qs('.orch-fab')) return;
    ORCH.built = true;
    const offline = !window.API || API.config.offline;
    const skin = orchSkinMeta(orchLoadSkin());
    orchApplySkin(skin.id);
    const fab = el(`<button class="orch-fab" id="orch-fab" type="button" title="${esc(skin.fabTitle)}" aria-label="Открыть ${esc(skin.fabTitle)}">${sfChatMark()}</button>`);
    const panel = el(`<section class="orch-panel sf-chat-panel" id="orch-panel" hidden aria-label="SF Chat · люди и AI-помощники">
      <header class="orch-head">
        <button class="orch-icon-btn orch-list-toggle" id="orch-list-toggle" type="button" title="Список диалогов" aria-label="Список диалогов">${icon('list')}</button>
        <div class="orch-head-brand">${sfChatMark()}</div>
        <div class="orch-head-title" title="SF Chat"><span class="orch-head-name">SF Chat</span><span class="orch-head-sub" id="orch-head-sub">Люди и AI-помощники</span><span class="orch-task-state open" id="orch-task-state">Тема открыта</span></div>
        <button class="orch-icon-btn" id="orch-thread-state" type="button" title="Закрыть завершённую тему" aria-label="Закрыть тему">${icon('check')}</button>
        <button class="orch-icon-btn" id="orch-new" type="button" title="Новый диалог" aria-label="Новый диалог">${icon('plus')}</button>
        <div class="orch-skin-wrap">
          <button class="orch-icon-btn" id="orch-skin-btn" type="button" title="Облик чата" aria-label="Облик чата" aria-haspopup="menu" aria-expanded="false">${icon('palette')}</button>
          <div class="orch-skin-menu" id="orch-skin-menu" role="menu" hidden></div>
        </div>
        <button class="orch-icon-btn" id="orch-close" type="button" title="Свернуть" aria-label="Свернуть">${icon('close')}</button>
      </header>
      <div class="orch-body">
        <button type="button" class="orch-drawer-scrim" id="orch-drawer-scrim" aria-label="Закрыть список диалогов" tabindex="-1"></button>
        <aside class="orch-convos" id="orch-convos" aria-label="Диалоги"></aside>
        <div class="orch-main">
          <div class="orch-msgs" id="orch-msgs"><div class="empty-state">Загрузка…</div></div>
          <div class="orch-compose">
            <div class="orch-model-picker" id="orch-model-picker" hidden aria-hidden="true"></div>
            <div class="orch-attachments" id="orch-attachments" hidden></div>
            <form class="orch-input" id="orch-form" autocomplete="off">
              <button class="orch-attach" id="orch-attach" type="button" title="Прикрепить изображение" aria-label="Прикрепить изображение" hidden>${icon('paperclip')}</button>
              <input id="orch-files" type="file" accept="image/png,image/jpeg,image/webp" multiple hidden>
              <textarea id="orch-text" rows="1" maxlength="6000" placeholder="Напишите задачу обычным текстом…" ${offline ? 'disabled' : ''}></textarea>
              <button class="orch-mic" id="orch-mic" type="button" title="Голосовой ввод" aria-label="Голосовой ввод" hidden>${icon('mic')}</button>
              <button class="orch-send" id="orch-send" type="submit" title="Отправить" aria-label="Отправить" ${offline ? 'disabled' : ''}>${icon('send')}</button>
            </form>
          </div>
        </div>
      </div>
    </section>`);
    document.body.appendChild(fab);
    document.body.appendChild(panel);

    fab.addEventListener('click', () => { ORCH.open ? closeOrchestrator() : openOrchestrator(); });
    qs('#orch-close', panel).addEventListener('click', closeOrchestrator);
    qs('#orch-list-toggle', panel).addEventListener('click', () => { orchCloseSkinMenu(); panel.classList.toggle('show-convos'); });
    qs('#orch-drawer-scrim', panel).addEventListener('click', () => panel.classList.remove('show-convos'));
    qs('#orch-new', panel).addEventListener('click', () => { orchCloseSkinMenu(); orchNewConversation(); });
    qs('#orch-thread-state', panel).addEventListener('click', () => { orchCloseSkinMenu(); orchToggleConversationState(); });
    qs('#orch-skin-btn', panel).addEventListener('click', (e) => { e.stopPropagation(); orchToggleSkinMenu(); });
    qs('#orch-skin-menu', panel).addEventListener('click', (e) => e.stopPropagation());
    qs('#orch-form', panel).addEventListener('submit', (e) => { e.preventDefault(); orchSend(); });
    qs('#orch-attach', panel).addEventListener('click', () => qs('#orch-files', panel).click());
    qs('#orch-files', panel).addEventListener('change', (e) => orchAddAttachments(e.target.files));
    const ta = qs('#orch-text', panel);
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px'; });
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); orchSend(); } });
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape' || !ORCH.open) return;
      const menu = qs('#orch-skin-menu');
      if (menu && !menu.hidden) { orchCloseSkinMenu(); e.preventDefault(); return; }
      if (panel.classList.contains('show-convos')) { panel.classList.remove('show-convos'); e.preventDefault(); return; }
      closeOrchestrator();
    });
    document.addEventListener('click', (e) => {
      const wrap = qs('.orch-skin-wrap', panel);
      if (wrap && !wrap.contains(e.target)) orchCloseSkinMenu();
    });
    wireOrchestratorVoice(panel);
    orchSelectMode(orchLoadMode(), { silent: true });
  }
  // Persistent model selection: the chosen chip sets the model strength for
  // every message until the owner switches. `auto` restores automatic routing.
  function orchSelectMode(mode, opts) {
    const meta = ORCH_MODES[mode] ? mode : 'auto';
    ORCH.mode = meta;
    const info = ORCH_MODES[meta];
    orchUpdateHeader();
    const ta = qs('#orch-text'); if (ta) ta.placeholder = info.ph;
    if (!(opts && opts.silent) && ta && !ta.disabled) ta.focus();
  }
  // Voice input: dictate into the message box using the browser Web Speech API
  // (microphone). No external resources — CSP-safe. Hidden if unsupported.
  function wireOrchestratorVoice(panel) {
    const mic = qs('#orch-mic', panel); const ta = qs('#orch-text', panel);
    if (!mic || !ta) return;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR || (!window.API || API.config.offline)) { mic.hidden = true; return; }
    mic.hidden = false;
    let rec = null, listening = false;
    // Idempotent transcript assembly (fixes the mobile duplication bug). Some
    // phones re-deliver already-final results (resultIndex resets to 0) and the
    // recognizer auto-restarts on `onend`; appending deltas duplicated the text.
    // Instead we rebuild the value from *all* results of the current session on
    // every event, and only carry finalized text forward when a session ends.
    let sessionBase = '';   // textarea text captured before recording started
    let committed = '';     // finalized text from earlier (ended) sessions
    let liveFinal = '';     // finalized text of the current session
    let interimText = '';   // in-flight (not yet final) text of the current session
    function render() {
      const combined = (sessionBase + committed + ' ' + liveFinal + ' ' + interimText).replace(/\s{2,}/g, ' ').replace(/^\s+/, '');
      ta.value = combined.slice(0, 6000);
      ta.style.height = 'auto'; ta.style.height = Math.min(120, ta.scrollHeight) + 'px';
    }
    function stop() { listening = false; mic.classList.remove('listening'); mic.title = 'Голосовой ввод'; try { if (rec) rec.stop(); } catch (e) { /* ignore */ } }
    mic.addEventListener('click', () => {
      if (listening) { stop(); return; }
      try {
        rec = new SR();
        rec.lang = 'ru-RU';
        rec.interimResults = true;
        rec.continuous = true;
        sessionBase = ta.value ? ta.value.replace(/\s+$/, '') + ' ' : '';
        committed = ''; liveFinal = ''; interimText = '';
        rec.onresult = (event) => {
          let finalText = '', interim = '';
          for (let i = 0; i < event.results.length; i++) {
            const t = event.results[i][0].transcript;
            if (event.results[i].isFinal) finalText += t + ' '; else interim += t;
          }
          liveFinal = finalText; interimText = interim;
          render();
        };
        rec.onerror = (event) => { if (event && event.error === 'not-allowed') toast('Нет доступа к микрофону — разрешите его в браузере'); stop(); };
        rec.onend = () => {
          committed = (committed + ' ' + liveFinal).replace(/\s{2,}/g, ' ').trim();
          liveFinal = ''; interimText = '';
          if (listening) { try { rec.start(); } catch (e) { stop(); } }
        };
        rec.start();
        listening = true;
        mic.classList.add('listening');
        mic.title = 'Остановить запись';
        ta.focus();
      } catch (e) { toast('Голосовой ввод недоступен в этом браузере'); stop(); }
    });
    onLeave(stop);
  }
  function orchRenderPendingAttachments() {
    const wrap = qs('#orch-attachments');
    if (!wrap) return;
    const rows = ORCH.pendingAttachments || [];
    wrap.hidden = !rows.length;
    wrap.innerHTML = rows.map((row, index) => `<span class="orch-attachment-preview">
      <img src="${esc(row.data_url)}" alt=""><span>${esc(row.name || 'image')}</span>
      <button type="button" data-orch-remove-file="${index}" aria-label="Убрать вложение">${icon('close')}</button>
    </span>`).join('');
    qsa('[data-orch-remove-file]', wrap).forEach((button) => button.addEventListener('click', () => {
      ORCH.pendingAttachments.splice(Number(button.dataset.orchRemoveFile), 1);
      orchRenderPendingAttachments();
    }));
  }
  async function orchAddAttachments(fileList) {
    const files = Array.from(fileList || []);
    const allowed = new Set(['image/png', 'image/jpeg', 'image/webp']);
    for (const file of files) {
      if (ORCH.pendingAttachments.length >= 3) { toast('Можно приложить до 3 изображений'); break; }
      if (!allowed.has(String(file.type || '').toLowerCase())) { toast('Поддерживаются PNG, JPEG и WebP'); continue; }
      if (Number(file.size || 0) > 2 * 1024 * 1024) { toast('Каждое изображение — не более 2 МБ'); continue; }
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(new Error('Не удалось прочитать изображение'));
        reader.readAsDataURL(file);
      }).catch((error) => { reportError(error); return ''; });
      if (dataUrl) ORCH.pendingAttachments.push({
        name: String(file.name || 'image').slice(0, 120),
        mime_type: file.type,
        size: file.size,
        data_url: dataUrl,
      });
    }
    const input = qs('#orch-files'); if (input) input.value = '';
    orchRenderPendingAttachments();
  }
  async function openOrchestrator(options) {
    buildOrchestratorWidget();
    const panel = qs('#orch-panel'); const fab = qs('#orch-fab');
    if (!panel) return;
    ORCH.open = true;
    panel.hidden = false;
    requestAnimationFrame(() => panel.classList.add('open'));
    if (fab) fab.classList.add('active');
    if (!window.API || API.config.offline) {
      qs('#orch-msgs', panel).innerHTML = '<div class="empty-state">SF Chat доступен только в работающем приложении (не в офлайн-превью).</div>';
      return;
    }
    if (isGuest()) {
      orchRenderAuthRequired(panel);
      return;
    }
    // Restore the last opened conversation unless the caller requested an exact
    // human or AI dialogue (for example from Community or a notification).
    const requestedId = String((options && options.conversationId) || '').trim();
    ORCH.currentId = requestedId || orchLoadLastId();
    const loaded = await orchLoadConversations();
    if (!loaded) return;
    if (ORCH.currentId) await orchLoadMessages(ORCH.currentId);
    else qs('#orch-msgs', panel).innerHTML = '<div class="empty-state">Начните переписку из профиля участника в Сообществе.</div>';
    const ta = qs('#orch-text', panel); if (ta && !ta.disabled) ta.focus();
    if (ORCH.currentId) dismissNoticesForConversation(ORCH.currentId);
    // Fast local refresh while open: Telegram uses a separate long-poll receiver,
    // so new messages and a first-request title become visible here almost at once.
    if (ORCH.pollStop) ORCH.pollStop();
    let stopped = false, refreshing = false;
    const id = setInterval(async () => {
      if (stopped || refreshing || !ORCH.open || ORCH.sending
          || Date.now() < Number(ORCH.retryAfter || 0)) return;
      refreshing = true;
      try {
        const refreshed = await Promise.all([
          orchLoadMessages(ORCH.currentId, true),
          orchLoadConversations(),
        ]);
        if (refreshed.every(Boolean)) ORCH.retryAfter = 0;
      } finally { refreshing = false; }
    }, 3000);
    ORCH.pollStop = () => { stopped = true; clearInterval(id); };
  }
  async function openSFChat(options) {
    return openOrchestrator(options || {});
  }
  function orchRenderAuthRequired(panel) {
    const root = panel || qs('#orch-panel');
    if (!root) return;
    ORCH.loadError = { status: 401, message: 'Требуется вход через Telegram.' };
    const wrap = qs('#orch-convos', root);
    const box = qs('#orch-msgs', root);
    if (wrap) wrap.innerHTML = '<div class="empty-state">История не удалена. Войдите, чтобы загрузить свои диалоги.</div>';
    if (box) box.innerHTML = '<div class="empty-state"><strong>Войдите через Telegram</strong><br>После входа вернутся прежние чаты и станут доступны поручения.<div style="margin-top:12px"><button class="btn primary" id="orch-auth-login" type="button">Войти через Telegram</button></div></div>';
    const login = qs('#orch-auth-login', root);
    if (login) login.onclick = () => { closeOrchestrator(); renderTelegramLogin(''); };
    const ta = qs('#orch-text', root); const send = qs('#orch-send', root); const mic = qs('#orch-mic', root);
    if (ta) { ta.disabled = true; ta.placeholder = 'Сначала войдите через Telegram'; }
    if (send) send.disabled = true;
    if (mic) mic.hidden = true;
  }
  function closeOrchestrator() {
    const panel = qs('#orch-panel'); const fab = qs('#orch-fab');
    ORCH.open = false;
    orchCloseSkinMenu();
    if (panel) { panel.classList.remove('open'); setTimeout(() => { if (!ORCH.open) panel.hidden = true; }, 220); }
    if (fab) fab.classList.remove('active');
    if (ORCH.pollStop) { ORCH.pollStop(); ORCH.pollStop = null; }
    orchStopFeedbackVoice();
    agentSpeakStop();
  }
  async function orchLoadConversations() {
    const wrap = qs('#orch-convos'); if (!wrap) return;
    try {
      const data = await API.http.sfChatConversations();
      ORCH.conversations = data.conversations || [];
      ORCH.viewerProfileId = String(data.viewer_profile_id || '');
      ORCH.aiAvailable = data.ai_available !== false;
      ORCH.loadError = null;
    } catch (e) {
      // Never replace a previously loaded list with an empty one because of a
      // session/network error.  That made intact history look deleted.
      ORCH.loadError = e || new Error('Не удалось загрузить диалоги');
      if (e && e.status === 429) ORCH.retryAfter = Date.now() + Math.max(15000, Number(e.retryAfterMs || 0));
      if (e && (e.status === 401 || e.status === 403)) orchRenderAuthRequired(qs('#orch-panel'));
      else orchRenderConversations();
      return false;
    }
    if (!ORCH.conversations.some(c => c.conversation_id === ORCH.currentId)) {
      orchSaveCurrentId((ORCH.conversations[0] && ORCH.conversations[0].conversation_id) || '');
    }
    orchRenderConversations();
    orchRenderWorkState();
    return true;
  }
  const ORCH_WORK_STATES = {
    open: ['Тема открыта', 'open'], awaiting_owner: ['Ожидается ваше решение', 'waiting'],
    in_progress: ['Работа выполняется', 'running'], completed: ['Тема завершена', 'done'],
    blocked: ['Требует внимания', 'blocked'],
  };
  function orchCurrentConversation() { return ORCH.conversations.find(c => c.conversation_id === ORCH.currentId) || null; }
  function orchHasUnfinishedCurrent() {
    const c = orchCurrentConversation();
    return !!(c && !orchIsHumanConversation(c) && !c.closed
      && ['awaiting_owner', 'in_progress', 'blocked'].includes(c.work_state));
  }
  function orchUpdateHeader() {
    const current = orchCurrentConversation();
    const sub = qs('#orch-head-sub');
    if (!sub) return;
    if (orchIsHumanConversation(current)) {
      sub.textContent = String((current && current.subtitle) || (current && current.title) || 'Личная переписка');
      return;
    }
    sub.textContent = current
      ? String(current.subtitle || 'AI · Виктор и агенты')
      : 'Люди и AI-помощники';
  }
  function orchRenderWorkState() {
    const c = orchCurrentConversation();
    const human = orchIsHumanConversation(c);
    const workState = (c && c.work_state) || 'open';
    const meta = ORCH_WORK_STATES[workState] || ORCH_WORK_STATES.open;
    const isDefault = !!(c && c.is_default);
    orchUpdateHeader();
    const badge = qs('#orch-task-state');
    if (badge) {
      if (!c || human || isDefault) {
        // The main/system chat is a durable service inbox — never show topic
        // lifecycle badges such as «Тема открыта» / «Тема завершена».
        badge.hidden = true;
      } else if (c && c.closed) {
        badge.textContent = 'Тема закрыта'; badge.className = 'orch-task-state closed'; badge.hidden = false;
      } else {
        badge.textContent = meta[0]; badge.className = 'orch-task-state ' + meta[1]; badge.hidden = false;
      }
    }
    const toggle = qs('#orch-thread-state');
    if (toggle) {
      // The main/system chat can never be closed — hide the close/reopen button.
      toggle.hidden = !c || human || isDefault;
      toggle.innerHTML = icon(c && c.closed ? 'refresh' : 'check');
      toggle.title = c && c.closed ? 'Переоткрыть тему' : 'Закрыть тему';
      toggle.setAttribute('aria-label', toggle.title);
    }
    const ta = qs('#orch-text'); const send = qs('#orch-send'); const mic = qs('#orch-mic');
    const attach = qs('#orch-attach'); const create = qs('#orch-new');
    const closed = !!(c && c.closed);
    const disabled = !c || closed || (!window.API || API.config.offline);
    if (ta) {
      ta.disabled = disabled;
      ta.placeholder = !c ? 'Выберите диалог' : closed
        ? 'Тема закрыта. Переоткройте её, чтобы продолжить.'
        : human ? 'Напишите сообщение…' : (ORCH_MODES[ORCH.mode] || ORCH_MODES.auto).ph;
      ta.maxLength = human ? 4000 : 6000;
    }
    if (send) send.disabled = disabled;
    if (attach) attach.hidden = !human || disabled;
    if (create) create.hidden = human || ORCH.aiAvailable === false;
    if (mic) mic.hidden = human || closed || !(window.SpeechRecognition || window.webkitSpeechRecognition) || (!window.API || API.config.offline);
    if (!human && ORCH.pendingAttachments.length) {
      ORCH.pendingAttachments = [];
      orchRenderPendingAttachments();
    }
  }
  function orchRenderConversations() {
    const wrap = qs('#orch-convos'); if (!wrap) return;
    const unreadMap = NOTICE.unreadByConversation || {};
    const rows = ORCH.conversations.map(c => {
      const active = c.conversation_id === ORCH.currentId;
      const human = orchIsHumanConversation(c);
      const canEdit = !human && !c.is_default;
      const pinned = !!c.pinned;
      const unreadN = Math.max(0, Number(c.unread_count || unreadMap[c.conversation_id] || 0));
      const unreadCls = unreadN ? ' unread' : '';
      const unreadBadge = unreadN
        ? `<span class="orch-convo-unread" title="${unreadN} непрочитанных">${unreadN > 9 ? '9+' : unreadN}</span>`
        : '';
      const participant = c.participant || {};
      const face = human ? `<span class="orch-convo-face">${participant.avatar_url
        ? `<img src="${esc(participant.avatar_url)}" alt="">`
        : esc(String(participant.display_name || c.title || '?').slice(0, 1).toUpperCase())}</span>` : '';
      const subtitle = human
        ? [String(c.last_message_preview || ''), orchFmtTime(c.updated_at_utc)].filter(Boolean).join(' · ')
        : `${orchFmtTime(c.updated_at_utc)} · ${Number(c.message_count || 0)} сообщ.`;
      const state = human
        ? '<div class="orch-convo-state human">личная переписка</div>'
        : `<div class="orch-convo-state ${(c.closed ? 'closed' : (c.is_default ? 'open' : (ORCH_WORK_STATES[c.work_state] || ORCH_WORK_STATES.open)[1]))}">${c.closed ? 'закрыта' : (c.is_default ? 'всегда открыт' : (ORCH_WORK_STATES[c.work_state] || ORCH_WORK_STATES.open)[0])}</div>`;
      return `<div class="orch-convo ${active ? 'active' : ''} ${pinned ? 'pinned' : ''}${unreadCls}" data-cid="${esc(c.conversation_id)}" role="button" tabindex="0">
        ${face}
        <div class="orch-convo-main">
          <div class="orch-convo-title">${pinned ? icon('pin') : ''}${esc(c.title || 'Диалог')}${unreadBadge}</div>
          <div class="orch-convo-sub">${esc(subtitle)}</div>
          ${state}
        </div>
        <div class="orch-convo-acts">
          ${human ? '' : (c.is_default ? '<span class="orch-convo-sys" title="Системный чат — всегда закреплён">AI</span>' : `<button class="orch-icon-btn sm ${pinned ? 'on' : ''}" data-pin="${esc(c.conversation_id)}" data-pinned="${pinned ? '1' : '0'}" title="${pinned ? 'Открепить' : 'Закрепить вверху'}" aria-label="Закрепить">${icon('pin')}</button>`)}
          ${canEdit ? `<button class="orch-icon-btn sm" data-rename="${esc(c.conversation_id)}" title="Переименовать" aria-label="Переименовать">${icon('edit')}</button><button class="orch-icon-btn sm" data-del="${esc(c.conversation_id)}" title="Удалить" aria-label="Удалить">${icon('trash')}</button>` : ''}
        </div>
      </div>`;
    }).join('');
    const error = ORCH.loadError
      ? '<div class="empty-state">Не удалось обновить список. Показана сохранённая история; повторите после восстановления соединения.</div>'
      : '';
    wrap.innerHTML = error + (rows || (ORCH.loadError ? '' : '<div class="empty-state">Создайте первый диалог.</div>'));
    qsa('.orch-convo', wrap).forEach(node => {
      node.addEventListener('click', (e) => {
        if (e.target.closest('[data-rename]') || e.target.closest('[data-del]') || e.target.closest('[data-pin]')) return;
        orchSelectConversation(node.dataset.cid);
      });
    });
    qsa('[data-pin]', wrap).forEach(b => b.addEventListener('click', (e) => { e.stopPropagation(); orchPin(b.dataset.pin, b.dataset.pinned !== '1'); }));
    qsa('[data-rename]', wrap).forEach(b => b.addEventListener('click', (e) => { e.stopPropagation(); orchRename(b.dataset.rename); }));
    qsa('[data-del]', wrap).forEach(b => b.addEventListener('click', (e) => { e.stopPropagation(); orchDelete(b.dataset.del); }));
  }
  async function orchPin(cid, pinned) {
    if (ORCH.sending) { toast('Дождитесь ответа в текущем диалоге'); return; }
    if (orchIsHumanConversation(cid)) return;
    try { await API.http.aiOrchestratorPinConversation(cid, pinned); await orchLoadConversations(); }
    catch (e) { reportError(e); }
  }
  async function orchSelectConversation(cid) {
    if (ORCH.sending) { toast('Дождитесь ответа в текущем диалоге'); return; }
    if (!cid || cid === ORCH.currentId) {
      qs('#orch-panel').classList.remove('show-convos');
      if (cid) dismissNoticesForConversation(cid);
      return;
    }
    if (orchHasUnfinishedCurrent() && !confirm('Текущая тема ещё не завершена. Перейти в другой диалог?')) return;
    orchSaveCurrentId(cid);
    ORCH.messagesSignature = '';
    orchStopFeedbackVoice();
    orchRenderConversations();
    qs('#orch-panel').classList.remove('show-convos');
    await orchLoadMessages(cid);
    orchRenderWorkState();
    if (orchIsHumanConversation(cid)) {
      try { await API.http.sfChatRead(cid); } catch (e) { /* visible dialogue remains usable */ }
      await refreshInAppNotices({ silent: true });
    }
    dismissNoticesForConversation(cid);
    const ta = qs('#orch-text'); if (ta && !ta.disabled) ta.focus();
  }
  async function orchNewConversation() {
    if (ORCH.sending) { toast('Дождитесь ответа в текущем диалоге'); return; }
    if (!window.API || API.config.offline) return;
    if (ORCH.aiAvailable === false) return;
    if (orchHasUnfinishedCurrent() && !confirm('Текущая тема ещё не завершена. Создать новую тему всё равно?')) return;
    try {
      const res = await API.http.aiOrchestratorCreateConversation('');
      orchSaveCurrentId((res.conversation && res.conversation.conversation_id) || 'default');
      await orchLoadConversations();
      await orchLoadMessages(ORCH.currentId);
      qs('#orch-panel').classList.remove('show-convos');
      const ta = qs('#orch-text'); if (ta && !ta.disabled) ta.focus();
    } catch (e) { reportError(e); }
  }
  async function orchRename(cid) {
    if (ORCH.sending) { toast('Дождитесь ответа в текущем диалоге'); return; }
    if (orchIsHumanConversation(cid)) return;
    const current = ORCH.conversations.find(c => c.conversation_id === cid);
    const title = prompt('Название диалога:', (current && current.title) || '');
    if (title == null) return;
    const clean = String(title).trim();
    if (!clean) return;
    try { await API.http.aiOrchestratorRenameConversation(cid, clean); await orchLoadConversations(); }
    catch (e) { reportError(e); }
  }
  async function orchDelete(cid) {
    if (ORCH.sending) { toast('Дождитесь ответа в текущем диалоге'); return; }
    if (orchIsHumanConversation(cid)) return;
    if (!confirm('Удалить этот диалог вместе с его историей?')) return;
    try {
      await API.http.aiOrchestratorDeleteConversation(cid);
      if (ORCH.currentId === cid) orchSaveCurrentId('default');
      await orchLoadConversations();
      await orchLoadMessages(ORCH.currentId);
    } catch (e) { reportError(e); }
  }
  function orchRatingHtml(row, isUser) {
    if (isUser || !row.message_id) return '';
    const rating = Number(row.rating || 0);
    const comment = String(row.feedback_comment || '');
    const hasComment = !!comment.trim();
    const labels = { 1: 'Слабый ответ', 2: 'Нормально', 3: 'Хороший ответ' };
    const stars = [1, 2, 3].map(n => `<button type="button" class="orch-rate-star ${rating >= n ? 'active' : ''}" data-orch-rate="${n}" title="${labels[n]}" aria-label="${labels[n]}">${icon('star')}</button>`).join('');
    const feedbackOpen = rating === 1 && !hasComment;
    return `<div class="orch-rating" data-orch-message-id="${esc(row.message_id)}" data-rating="${rating || ''}">
      <div class="orch-rating-row"><span class="orch-rating-label">Оценка</span><div class="orch-rating-stars">${stars}</div><span class="orch-feedback-saved" ${rating ? '' : 'hidden'}>${rating ? 'сохранено' : ''}</span></div>
      <div class="orch-feedback-archive" ${hasComment ? '' : 'hidden'}>
        <div><span class="orch-feedback-archive-label">Сохранённый комментарий</span><div class="orch-feedback-archive-text">${esc(comment)}</div></div>
        <button type="button" class="orch-feedback-edit">Редактировать</button>
      </div>
      <div class="orch-feedback-area" ${feedbackOpen ? '' : 'hidden'}>
        <textarea class="orch-feedback-text" rows="2" maxlength="2000" placeholder="Что исправить в ответе?"></textarea>
        <div class="orch-feedback-actions">
          <button type="button" class="orch-feedback-mic" title="Надиктовать комментарий" aria-label="Надиктовать комментарий" hidden>${icon('mic')}</button>
          <button type="button" class="orch-feedback-cancel" hidden>Отмена</button>
          <button type="button" class="orch-feedback-save">Сохранить комментарий</button>
        </div>
      </div>
    </div>`;
  }
  const ORCH_KIND_LABELS = {
    chat: 'сообщение', request: 'просьба', task: 'поручение', report: 'отчёт', informational: 'уведомление',
  };
  const ORCH_FULFILL_LABELS = {
    unset: 'не отмечено', done: 'выполнено', failed: 'не выполнено', na: 'переписка',
  };
  function orchInferKind(row) {
    const explicit = String(row.message_kind || '').trim();
    if (ORCH_KIND_LABELS[explicit]) return explicit;
    const actions = Array.isArray(row.actions) ? row.actions.filter(a => a && typeof a === 'object') : [];
    if (!actions.length) return 'chat';
    const names = actions.map(a => String(a.name || a.action || ''));
    const statuses = actions.map(a => String(a.status || ''));
    if (names.some(n => /^(strategy_(started|stopped|enabled|disabled)|ninjatrader_(started|stopped)|connection_restored)$/.test(n))) return 'informational';
    if (names.some(n => /mission_completed|deliver_report|request_.*_report/.test(n))) return 'report';
    if (statuses.some(s => /needs_input|approval_required|waiting_review/.test(s))) return 'request';
    return 'task';
  }
  function orchFulfillmentOf(row) {
    const raw = String(row.fulfillment || '').trim();
    if (ORCH_FULFILL_LABELS[raw]) return raw;
    const kind = orchInferKind(row);
    if (kind === 'chat') return 'na';
    const actions = Array.isArray(row.actions) ? row.actions.filter(a => a && typeof a === 'object') : [];
    if (!actions.length) return 'unset';
    const statuses = actions.map(a => String(a.status || ''));
    if (statuses.some(s => /queued|running|in_progress|needs_input|approval_required|waiting_review/.test(s))) return 'unset';
    if (statuses.some(s => /error|blocked/.test(s))) return 'failed';
    if (statuses.some(s => /completed|confirmed_connected/.test(s))) return 'done';
    return 'unset';
  }
  const ORCH_ACTION_LABELS = {
    reconnect_runtime_connection: 'Проверка связи с NinjaTrader',
    runtime_reconnect: 'Восстановление связи с NinjaTrader',
    review_financial_records: 'Проверка финансовых операций',
    review_failed_strategies: 'Проверка проваленных стратегий',
    start_research: 'Исследование стратегии',
    research_progress: 'Исследование стратегии',
    mission_completed: 'Исследование',
    request_performance_report: 'Подготовка финансового отчёта',
    request_accounting_report: 'Проверка бухгалтерского журнала',
    request_strategy_report: 'Подготовка отчёта по стратегиям',
    chart_open: 'Открытие графика',
    chart_watch: 'Наблюдение за графиком',
    chart_clear: 'Очистка графика',
    deliver_report: 'Доставка отчёта',
    vitek_task: 'Поручение Виктора',
    vitek_activate_task: 'Виктор принял поручение',
    vitek_add_task: 'Поручение передано Управляющему',
    vitek_create_incident_task: 'Поручение создано',
    vitek_set_plan: 'План сохранён',
    vitek_scan: 'Проверка системы',
    vitek_resume_task: 'Ответ передан исполнителю',
  };
  const ORCH_ACTION_STATES = {
    queued: ['В очереди', 'running'], running: ['Выполняется', 'running'],
    in_progress: ['Выполняется', 'running'], approval_required: ['Нужно ваше решение', 'waiting'],
    needs_input: ['Жду ваш ответ', 'waiting'], waiting_review: ['Жду ваш ответ', 'waiting'],
    blocked: ['Нужно внимание', 'blocked'], error: ['Ошибка', 'blocked'],
    completed: ['', 'done'], confirmed_connected: ['', 'done'],
  };
  function orchActionsHtml(row, isUser) {
    if (isUser || !Array.isArray(row.actions) || !row.actions.length) return '';
    // Progress rows stay informative while unfinished; terminal «Выполнено»
    // lives in the footer marks instead of repeating above every bubble.
    const items = row.actions.filter(action => action && typeof action === 'object').slice(0, 8).map(action => {
      const name = String(action.name || action.action || 'vitek_task');
      const status = String(action.status || 'running');
      const state = ORCH_ACTION_STATES[status] || [status || 'Выполняется', 'running'];
      const label = String(action.owner_label || action.summary || ORCH_ACTION_LABELS[name] || 'Работа по поручению');
      const stateText = state[0] ? `<span class="orch-action-state">${esc(state[0])}</span>` : '';
      return `<div class="orch-action ${esc(state[1])}"><span class="orch-action-mark" aria-hidden="true"></span><span class="orch-action-label">${esc(label)}</span>${stateText}</div>`;
    }).join('');
    return items ? `<div class="orch-actions" aria-label="Ход выполнения">${items}</div>` : '';
  }
  function orchChainHtml(row) {
    const chain = Array.isArray(row.participation_chain)
      ? row.participation_chain.filter(step => step && typeof step === 'object')
      : [];
    if (chain.length < 2) return '';
    const steps = chain.map((step, index) => {
      const who = String(step.agent_name || step.agent_id || 'агент');
      const title = String(step.title || step.role || '');
      const model = String(step.model || '');
      const provider = String(step.provider || '');
      const detail = [title, model ? `модель: ${model}${provider ? ` (${provider})` : ''}` : ''].filter(Boolean).join(' · ');
      return `<li class="orch-chain-step"><span class="orch-chain-n">${index + 1}</span><div><strong>${esc(who)}</strong>${detail ? `<div class="orch-chain-detail">${esc(detail)}</div>` : ''}</div></li>`;
    }).join('');
    return `<details class="orch-chain"><summary>Цепочка участников · ${chain.length}</summary><ol class="orch-chain-list">${steps}</ol></details>`;
  }
  function orchFooterHtml(row, isUser) {
    if (isUser || !row.message_id) return orchRatingHtml(row, isUser);
    const kind = orchInferKind(row);
    const fulfillment = orchFulfillmentOf(row);
    const kindLabel = ORCH_KIND_LABELS[kind] || kind;
    const fulfillLabel = ORCH_FULFILL_LABELS[fulfillment] || fulfillment;
    const isInformational = kind === 'informational';
    const showMarks = !isInformational && (kind !== 'chat' || fulfillment === 'done' || fulfillment === 'failed');
    const agentRef = row.agent_id || row.agent_name || row.domain_agent || 'vitek';
    const agentLabel = String(row.agent_name || agentRef || 'Витёк');
    const title = String(row.agent_title || '').trim();
    const model = String(row.model || '').trim();
    const provider = String(row.provider || '').trim();
    const modelMeta = model ? `модель: ${esc(model)}${provider ? ` (${esc(provider)})` : ''}` : '';
    const metaBits = [
      esc(agentLabel),
      title ? esc(title) : '',
      modelMeta,
      orchFmtTime(row.timestamp_utc),
    ].filter(Boolean).join(' · ');
    const statusCls = fulfillment === 'done' ? 'done' : fulfillment === 'failed' ? 'failed' : fulfillment === 'na' ? 'na' : 'unset';
    const marks = showMarks ? `<div class="orch-fulfill-marks" data-orch-fulfill-id="${esc(row.message_id)}" data-fulfillment="${esc(fulfillment)}">
        <span class="orch-msg-kind">${esc(kindLabel)}</span>
        <button type="button" class="orch-fulfill-btn ${fulfillment === 'done' ? 'active done' : ''}" data-orch-fulfill="done" title="Выполнено" aria-label="Выполнено">${icon('check')}</button>
        <button type="button" class="orch-fulfill-btn ${fulfillment === 'failed' ? 'active failed' : ''}" data-orch-fulfill="failed" title="Не выполнено" aria-label="Не выполнено">${icon('close')}</button>
      </div>` : `<span class="orch-msg-kind soft">${esc(kindLabel)}</span>`;
    return `<div class="orch-msg-footer" data-orch-message-id="${esc(row.message_id)}">
      <div class="orch-msg-footer-row">
        <div class="orch-msg-footer-left">
          ${isInformational ? '' : `<div class="orch-rating compact" data-orch-message-id="${esc(row.message_id)}" data-rating="${Number(row.rating || 0) || ''}">
            <div class="orch-rating-row"><span class="orch-rating-label">Оценка</span><div class="orch-rating-stars">${[1, 2, 3].map(n => `<button type="button" class="orch-rate-star ${Number(row.rating || 0) >= n ? 'active' : ''}" data-orch-rate="${n}" title="${({ 1: 'Слабый ответ', 2: 'Нормально', 3: 'Хороший ответ' })[n]}" aria-label="${({ 1: 'Слабый ответ', 2: 'Нормально', 3: 'Хороший ответ' })[n]}">${icon('star')}</button>`).join('')}</div></div>
          </div>`}
          ${isInformational ? `<span class="orch-msg-kind soft">${esc(kindLabel)}</span>` : `<span class="orch-fulfill-status ${statusCls}" title="${esc(fulfillLabel)}">${fulfillment === 'done' ? icon('check') : fulfillment === 'failed' ? icon('close') : ''}<span>${esc(fulfillLabel)}</span></span>`}
        </div>
        <div class="orch-msg-footer-right">${marks}</div>
      </div>
      <div class="orch-msg-meta">${metaBits}${orchChainHtml(row)}</div>
      ${(() => {
        const comment = String(row.feedback_comment || '');
        const hasComment = !!comment.trim();
        const rating = Number(row.rating || 0);
        const feedbackOpen = rating === 1 && !hasComment;
        return `<div class="orch-feedback-archive" ${hasComment ? '' : 'hidden'}>
          <div><span class="orch-feedback-archive-label">Сохранённый комментарий</span><div class="orch-feedback-archive-text">${esc(comment)}</div></div>
          <button type="button" class="orch-feedback-edit">Редактировать</button>
        </div>
        <div class="orch-feedback-area" ${feedbackOpen ? '' : 'hidden'}>
          <textarea class="orch-feedback-text" rows="2" maxlength="2000" placeholder="Что исправить в ответе?"></textarea>
          <div class="orch-feedback-actions">
            <button type="button" class="orch-feedback-mic" title="Надиктовать комментарий" aria-label="Надиктовать комментарий" hidden>${icon('mic')}</button>
            <button type="button" class="orch-feedback-cancel" hidden>Отмена</button>
            <button type="button" class="orch-feedback-save">Сохранить комментарий</button>
          </div>
        </div>`;
      })()}
    </div>`;
  }
  function orchMessageHtml(row) {
    const humanMessage = row.sender_type === 'human' || !!row.sender_profile_id;
    if (humanMessage) {
      const sender = row.sender || {};
      const outgoing = row.outgoing === true
        || (!!ORCH.viewerProfileId && String(row.sender_profile_id || '') === ORCH.viewerProfileId);
      const label = outgoing ? 'Вы' : String(sender.display_name || 'Участник');
      const attachments = Array.isArray(row.attachments) ? row.attachments.filter(a => a && a.url) : [];
      const media = attachments.map(a => `<a class="orch-msg-shot" href="${esc(a.url)}" target="_blank" rel="noopener" title="${esc(a.name || 'Изображение')}"><img loading="lazy" src="${esc(a.url)}" alt="${esc(a.name || 'Изображение')}"></a>`).join('');
      const face = outgoing ? '' : `<span class="orch-human-face">${sender.avatar_url
        ? `<img src="${esc(sender.avatar_url)}" alt="">`
        : esc(label.slice(0, 1).toUpperCase())}</span>`;
      const meta = [label, orchFmtTime(row.timestamp_utc)].filter(Boolean).join(' · ');
      return `<div class="orch-msg human ${outgoing ? 'user' : 'assistant'}">${face}<div class="orch-msg-stack">${row.content ? `<div class="orch-msg-body">${esc(row.content)}</div>` : ''}${media}<div class="orch-msg-meta">${esc(meta)}</div></div></div>`;
    }
    const isUser = row.role === 'user';
    const actor = isUser
      ? (row.actor_is_owner ? String(row.actor_name || 'Вы') : String(row.actor_name || row.user_name || row.user_id || 'Пользователь'))
      : '';
    const agentRef = row.agent_id || row.agent_name || row.domain_agent || 'vitek';
    const agentLabel = String(row.agent_name || agentRef || 'Витёк');
    const meta = isUser
      ? [esc(actor), orchFmtTime(row.timestamp_utc)].filter(Boolean).join(' · ')
      : '';
    const actions = orchActionsHtml(row, isUser);
    const footer = isUser
      ? (meta ? `<div class="orch-msg-meta">${meta}</div>` : '')
      : orchFooterHtml(row, isUser);
    const attachments = Array.isArray(row.attachments) ? row.attachments.filter(a => a && a.type === 'image' && a.url) : [];
    const media = attachments.map(a =>
      `<a class="orch-msg-shot" href="${esc(a.url)}" target="_blank" rel="noopener" title="${esc(a.caption || 'Снимок графика')}"><img loading="lazy" src="${esc(a.url)}" alt="${esc(a.caption || 'Снимок графика')}"></a>`
    ).join('');
    const face = isUser ? '' : agentAvatarHtml(agentRef, {
      label: agentLabel, cls: 'orch-msg-face', messageId: row.message_id || '',
    });
    return `<div class="orch-msg ${isUser ? 'user' : 'assistant'}">${face}<div class="orch-msg-stack"><div class="orch-msg-body">${esc(row.content || '')}</div>${media}${actions}${footer}</div></div>`;
  }
  function orchStopFeedbackVoice() {
    const voice = ORCH.feedbackVoice;
    if (!voice) return;
    ORCH.feedbackVoice = null;
    voice.listening = false;
    if (voice.btn) { voice.btn.classList.remove('listening'); voice.btn.title = 'Надиктовать комментарий'; }
    try { if (voice.rec) voice.rec.stop(); } catch (e) { /* ignore */ }
  }
  async function orchToggleConversationState() {
    const current = orchCurrentConversation();
    if (!current || !window.API || API.config.offline) return;
    if (orchIsHumanConversation(current)) return;
    const next = current.closed ? 'open' : 'closed';
    if (next === 'closed' && orchHasUnfinishedCurrent() && !confirm('Вопрос ещё не завершён. Закрыть тему без продолжения?')) return;
    try {
      await API.http.aiOrchestratorSetConversationState(ORCH.currentId, next);
      await orchLoadConversations();
      orchRenderWorkState();
      const ta = qs('#orch-text'); if (ta && !ta.disabled) ta.focus();
    } catch (e) { reportError(e); }
  }
  function orchStartFeedbackVoice(btn, ta) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR || !btn || !ta) return;
    if (ORCH.feedbackVoice && ORCH.feedbackVoice.btn === btn) { orchStopFeedbackVoice(); return; }
    orchStopFeedbackVoice();
    let rec;
    try { rec = new SR(); } catch (e) { toast('Голосовой ввод недоступен в этом браузере'); return; }
    rec.lang = 'ru-RU';
    rec.interimResults = true;
    rec.continuous = true;
    // Idempotent assembly — same mobile-duplication fix as the composer mic.
    const voice = {
      rec, btn, ta, listening: true,
      sessionBase: ta.value.trim() ? ta.value.trim() + ' ' : '',
      committed: '', liveFinal: '', interim: '',
    };
    ORCH.feedbackVoice = voice;
    btn.classList.add('listening');
    btn.title = 'Остановить запись';
    const renderFeedback = () => {
      const combined = (voice.sessionBase + voice.committed + ' ' + voice.liveFinal + ' ' + voice.interim).replace(/\s{2,}/g, ' ').replace(/^\s+/, '');
      ta.value = combined.slice(0, 2000);
      ta.dataset.dirty = '1';
    };
    rec.onresult = (ev) => {
      let finalText = '', interim = '';
      for (let i = 0; i < ev.results.length; i++) {
        const text = ev.results[i][0].transcript;
        if (ev.results[i].isFinal) finalText += text + ' '; else interim += text;
      }
      voice.liveFinal = finalText; voice.interim = interim;
      renderFeedback();
    };
    rec.onerror = (event) => {
      if (event && event.error === 'not-allowed') toast('Нет доступа к микрофону — разрешите его в браузере');
      if (event && ['not-allowed', 'service-not-allowed', 'audio-capture'].includes(event.error)) orchStopFeedbackVoice();
    };
    rec.onend = () => {
      voice.committed = (voice.committed + ' ' + voice.liveFinal).replace(/\s{2,}/g, ' ').trim();
      voice.liveFinal = ''; voice.interim = '';
      if (ORCH.feedbackVoice === voice && voice.listening && btn.isConnected) {
        try { rec.start(); } catch (e) { orchStopFeedbackVoice(); }
      }
    };
    try { rec.start(); } catch (e) { orchStopFeedbackVoice(); toast('Голосовой ввод недоступен в этом браузере'); }
  }
  async function orchSaveFulfillment(node, fulfillment) {
    if (!node || !window.API || API.config.offline) return;
    const mid = node.dataset.orchFulfillId || '';
    if (!mid || !API.http.aiOrchestratorFulfillMessage) return;
    const next = fulfillment === node.dataset.fulfillment ? 'unset' : fulfillment;
    node.classList.add('saving');
    try {
      await API.http.aiOrchestratorFulfillMessage(ORCH.currentId, mid, next);
      ORCH.messagesSignature = '';
      await orchLoadMessages(ORCH.currentId, true);
    } catch (e) { reportError(e); }
    finally { node.classList.remove('saving'); }
  }
  async function orchSaveRating(node, rating, comment) {
    if (!node || !window.API || API.config.offline) return;
    const mid = node.dataset.orchMessageId || '';
    if (!mid) return;
    node.classList.add('saving');
    try {
      orchStopFeedbackVoice();
      const result = await API.http.aiOrchestratorRateMessage(ORCH.currentId, mid, rating, comment || '');
      const savedComment = String(result && result.message && result.message.feedback_comment || '');
      node.dataset.rating = String(rating);
      qsa('[data-orch-rate]', node).forEach(btn => btn.classList.toggle('active', Number(btn.dataset.orchRate) <= rating));
      const root = node.closest('.orch-msg-footer') || node;
      const saved = qs('.orch-feedback-saved', root);
      if (saved) { saved.hidden = false; saved.textContent = 'сохранено'; }
      const archive = qs('.orch-feedback-archive', root);
      const archiveText = qs('.orch-feedback-archive-text', root);
      if (archiveText) archiveText.textContent = savedComment;
      if (archive) archive.hidden = !savedComment;
      const area = qs('.orch-feedback-area', root);
      if (area) area.hidden = rating !== 1 || !!savedComment;
      const ta = qs('.orch-feedback-text', root);
      if (ta) { ta.value = ''; ta.dataset.dirty = ''; }
      const cancel = qs('.orch-feedback-cancel', root); if (cancel) cancel.hidden = true;
      const status = qs('.orch-fulfill-status', root);
      if (status && result && result.message) {
        /* keep footer marks in sync after a silent reload path */
      }
    } catch (e) { reportError(e); }
    finally { node.classList.remove('saving'); }
  }
  function wireOrchFeedback(root) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    qsa('.orch-fulfill-marks', root).forEach(node => {
      qsa('[data-orch-fulfill]', node).forEach(btn => btn.addEventListener('click', () => {
        orchSaveFulfillment(node, btn.dataset.orchFulfill);
      }));
    });
    qsa('.orch-rating', root).forEach(node => {
      const shell = node.closest('.orch-msg-footer') || node;
      qsa('[data-orch-rate]', node).forEach(btn => btn.addEventListener('click', () => {
        const rating = Number(btn.dataset.orchRate || 0);
        const ta = qs('.orch-feedback-text', shell);
        const archive = qs('.orch-feedback-archive', shell);
        const archived = qs('.orch-feedback-archive-text', shell);
        if (rating === 1) {
          node.dataset.rating = '1';
          qsa('[data-orch-rate]', node).forEach(star => star.classList.toggle('active', Number(star.dataset.orchRate) <= 1));
          const area = qs('.orch-feedback-area', shell); if (area) area.hidden = false;
          if (archive) archive.hidden = true;
          if (ta) { ta.value = archived ? archived.textContent : ta.value; ta.dataset.dirty = '1'; ta.focus(); }
          const saved = qs('.orch-feedback-saved', shell); if (saved) { saved.hidden = false; saved.textContent = 'добавьте комментарий'; }
          return;
        }
        const comment = archive && !archive.hidden && archived ? archived.textContent : (ta ? ta.value : '');
        orchSaveRating(node, rating, comment);
      }));
      const save = qs('.orch-feedback-save', shell);
      if (save) save.addEventListener('click', () => {
        const rating = Number(node.dataset.rating || 1) || 1;
        const ta = qs('.orch-feedback-text', shell);
        orchSaveRating(node, rating, ta ? ta.value : '');
      });
      const edit = qs('.orch-feedback-edit', shell);
      if (edit) edit.addEventListener('click', () => {
        orchStopFeedbackVoice();
        const area = qs('.orch-feedback-area', shell);
        const archive = qs('.orch-feedback-archive', shell);
        const archived = qs('.orch-feedback-archive-text', shell);
        const ta = qs('.orch-feedback-text', shell);
        if (area) area.hidden = false;
        if (archive) archive.hidden = true;
        if (ta) { ta.value = archived ? archived.textContent : ''; ta.dataset.dirty = '1'; ta.focus(); }
        const cancel = qs('.orch-feedback-cancel', shell); if (cancel) cancel.hidden = false;
      });
      const cancel = qs('.orch-feedback-cancel', shell);
      if (cancel) cancel.addEventListener('click', () => {
        orchStopFeedbackVoice();
        const area = qs('.orch-feedback-area', shell); if (area) area.hidden = true;
        const archive = qs('.orch-feedback-archive', shell); if (archive) archive.hidden = false;
        const ta = qs('.orch-feedback-text', shell); if (ta) { ta.value = ''; ta.dataset.dirty = ''; }
        cancel.hidden = true;
      });
      const mic = qs('.orch-feedback-mic', shell);
      const ta = qs('.orch-feedback-text', shell);
      if (ta) ta.addEventListener('input', () => { ta.dataset.dirty = '1'; });
      if (mic && ta && SR && window.API && !API.config.offline) {
        mic.hidden = false;
        mic.addEventListener('click', () => orchStartFeedbackVoice(mic, ta));
      }
    });
  }
  async function orchLoadMessages(cid, silent) {
    const box = qs('#orch-msgs'); if (!box) return;
    if (!cid) return false;
    if (!silent) box.innerHTML = '<div class="state-loading"><span class="spinner"></span>Загрузка диалога…</div>';
    let messages = [];
    const human = orchIsHumanConversation(cid);
    try {
      const data = human
        ? await API.http.sfChatConversation(cid, { limit: 200 })
        : await API.http.aiOrchestratorConversation(cid, { limit: 200 });
      messages = data.messages || [];
      if (data.viewer_profile_id) ORCH.viewerProfileId = String(data.viewer_profile_id);
      if (data.conversation) {
        const index = ORCH.conversations.findIndex(row => row.conversation_id === cid);
        if (index >= 0) ORCH.conversations[index] = { ...ORCH.conversations[index], ...data.conversation };
      }
    } catch (e) {
      if (e && e.status === 429) {
        ORCH.retryAfter = Math.max(Number(ORCH.retryAfter || 0), Date.now() + Number(e.retryAfterMs || 15000));
      }
      if (!silent) { renderError(box, e, () => orchLoadMessages(cid)); return false; }
      return false;
    }
    if (ORCH.currentId !== cid) return;
    const signature = JSON.stringify(messages.map(row => [
      row.message_id, row.timestamp_utc, row.content, row.rating,
      row.feedback_comment, row.feedback_timestamp_utc, row.model, row.provider,
      row.agent_name, row.actions, row.fulfillment, row.message_kind, row.participation_chain,
      row.sender_profile_id, row.attachments,
    ]));
    if (silent && signature === ORCH.messagesSignature) return;
    if (silent && (ORCH.feedbackVoice || qsa('.orch-feedback-text', box).some(ta => ta.dataset.dirty === '1'))) return;
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
    orchStopFeedbackVoice();
    box.innerHTML = messages.length ? messages.map(orchMessageHtml).join('') : (human
      ? '<div class="empty-state">Личная переписка начнётся с первого сообщения.</div>'
      : '<div class="empty-state">Начните диалог: например «Разработай простую стратегию максимально быстро».</div>');
    if (ORCH.transientError && ORCH.transientError.cid === cid) {
      box.insertAdjacentHTML('beforeend', `<div class="orch-msg assistant"><span class="orch-err">${esc(ORCH.transientError.text)}</span></div>`);
    }
    ORCH.messagesSignature = signature;
    if (!human) {
      wireOrchFeedback(box);
      wireAgentFaces(box);
    }
    if (!silent || atBottom) box.scrollTop = box.scrollHeight;
    if (human && ORCH.open && ORCH.currentId === cid) {
      try { await API.http.sfChatRead(cid); } catch (e) { /* read state retries on the next poll */ }
    }
    return true;
  }
  async function orchSend() {
    if (ORCH.sending) return;
    const ta = qs('#orch-text'); const box = qs('#orch-msgs'); const sendBtn = qs('#orch-send');
    if (!ta || !box) return;
    const text = ta.value.trim();
    const human = orchIsHumanConversation(ORCH.currentId);
    if (!text && !(human && ORCH.pendingAttachments.length)) return;
    if (isGuest()) { orchRenderAuthRequired(qs('#orch-panel')); return; }
    if (!window.API || API.config.offline) { toast('Чат недоступен в офлайн-превью'); return; }
    ORCH.sending = true;
    ORCH.transientError = null;
    if (sendBtn) sendBtn.disabled = true;
    ta.value = ''; ta.style.height = 'auto';
    if (human) {
      const cid = ORCH.currentId;
      const attachments = ORCH.pendingAttachments.slice();
      ORCH.pendingAttachments = [];
      orchRenderPendingAttachments();
      if (box.querySelector('.empty-state')) box.innerHTML = '';
      box.insertAdjacentHTML('beforeend', orchMessageHtml({
        sender_type: 'human', sender_profile_id: ORCH.viewerProfileId,
        outgoing: true, content: text, attachments: attachments.map(row => ({
          url: row.data_url, name: row.name, mime_type: row.mime_type,
        })), timestamp_utc: new Date().toISOString(),
      }));
      box.scrollTop = box.scrollHeight;
      try {
        await API.http.sfChatMessage(cid, text, attachments);
        ORCH.messagesSignature = '';
        await orchLoadMessages(cid);
        await orchLoadConversations();
        await refreshInAppNotices({ silent: true });
      } catch (e) {
        reportError(e);
        ORCH.messagesSignature = '';
        await orchLoadMessages(cid).catch(() => false);
      } finally {
        ORCH.sending = false;
        if (sendBtn) sendBtn.disabled = false;
        if (ta && !ta.disabled) ta.focus();
      }
      return;
    }
    // optimistic render: show the owner message immediately
    if (box.querySelector('.empty-state')) box.innerHTML = '';
    box.insertAdjacentHTML('beforeend', orchMessageHtml({ role: 'user', content: text, timestamp_utc: new Date().toISOString(), source: 'app' }));
    // Live block contains only public progress labels. Provider chain-of-thought
    // is never rendered or persisted in the owner-facing conversation.
    const live = el(`<div class="orch-live" id="orch-live">
      <div class="orch-think-live" id="orch-live-think">
        <div class="orch-think-live-label">${icon('spark')}<span>Передаю запрос…</span></div>
        <div class="orch-think-live-text"><span id="orch-live-think-body"></span></div>
      </div>
      <div class="orch-msg assistant orch-live-answer" id="orch-live-body">${agentAvatarHtml('vitek', { speaking: true, label: 'Виктор', cls: 'orch-msg-face' })}<div class="orch-msg-stack"><span class="orch-dots"><i></i><i></i><i></i></span></div></div>
    </div>`);
    box.appendChild(live);
    wireAgentFaces(live);
    box.scrollTop = box.scrollHeight;
    const cid = ORCH.currentId;
    const thinkWrap = qs('#orch-live-think', live);
    const thinkBody = qs('#orch-live-think-body', live);
    const liveBody = qs('#orch-live-body', live);
    const liveStack = () => qs('.orch-msg-stack', liveBody) || liveBody;
    const setLiveFace = (ref, label) => {
      if (!liveBody) return;
      const next = agentAvatarHtml(ref || 'vitek', {
        speaking: true, label: label || 'Виктор', cls: 'orch-msg-face',
      });
      const current = qs('.orch-msg-face', liveBody);
      if (current) current.outerHTML = next;
      else liveBody.insertAdjacentHTML('afterbegin', next);
      wireAgentFaces(liveBody);
    };
    const setLiveBody = (html) => {
      const stack = liveStack();
      if (stack) stack.innerHTML = html;
    };
    let sawThinking = false;
    const nearBottom = () => box.scrollHeight - box.scrollTop - box.clientHeight < 160;
    const keepBottom = () => { if (nearBottom()) box.scrollTop = box.scrollHeight; };
    const setThink = (t) => { if (thinkBody) thinkBody.textContent = t; keepBottom(); };
    const removeThink = () => { if (thinkWrap) thinkWrap.remove(); };
    const agent = (ORCH_MODES[ORCH.mode] || ORCH_MODES.auto).agent;
    try {
      const streamResult = await API.http.aiOrchestratorMessageStream(text, cid, agent, {
        onThinkingDelta: () => { sawThinking = true; setThink('Анализирую задачу…'); },
        onStatus: (s) => { if (!sawThinking) setThink(s); },
        onFinal: (data) => {
          if (ORCH.currentId === cid && data && data.conversation_id) orchSaveCurrentId(data.conversation_id);
          removeThink();
          const faceRef = (data && (data.agent_id || data.domain_agent || data.agent_name || data.agent)) || 'vitek';
          const faceLabel = String((data && data.agent_name) || faceRef || 'Виктор');
          setLiveFace(faceRef, faceLabel);
          setLiveBody(esc(String((data && data.reply) || '')));
          keepBottom();
        },
        onError: (err) => {
          removeThink();
          setLiveBody(`<span class="orch-err">Не удалось получить ответ: ${esc(err)}</span>`);
          keepBottom();
        },
      });
      if (!streamResult || streamResult.ok !== true) {
        const message = String((streamResult && streamResult.error) || 'Не удалось получить ответ.');
        ORCH.transientError = { cid, text: `Не удалось получить ответ: ${message}` };
        removeThink();
        setLiveBody(`<span class="orch-err">${esc(ORCH.transientError.text)}</span>`);
      }
    } catch (e) {
      // A failed streaming POST may already have been committed by the server.
      // Never repeat the same mutating message through a second transport.
      const message = String((e && e.message) || e || 'Соединение прервалось');
      ORCH.transientError = { cid, text: `Не удалось подтвердить получение ответа: ${message}. Обновите историю перед повторной отправкой.` };
      removeThink();
      setLiveBody(`<span class="orch-err">${esc(ORCH.transientError.text)}</span>`);
    } finally {
      ORCH.sending = false;
      if (sendBtn) sendBtn.disabled = false;
      // Reload from storage so the final reply and auditable action states
      // replace the transient public progress block.
      if (!ORCH.transientError && ORCH.currentId === cid) await orchLoadMessages(cid);
      await orchLoadConversations();
      if (ta && !ta.disabled) ta.focus();
    }
  }

  function requireSignIn() {
    if (!isGuest()) return false;
    renderTelegramLogin('');
    return true;
  }

  window.UI = { icon, money, pct, pnlClass, badge, esc, el, qs, qsa, toast, drawer, closeDrawer, sortable, ready, menu, pageActions, onLeave, signal, poll, renderLoading, renderEmpty, renderError, reportError, enhanceA11y, action, getSelectedAccount, setSelectedAccount, normalizeNewsKey, uniqueTickerRows, expandTickerRows, marketNoticeRows, scheduleStrategyRows, NAV, openOrchestrator, openSFChat, closeOrchestrator, isGuest, requireSignIn, agentAvatarId, agentAvatarUrl, agentAvatarHtml, wireAgentFaces, agentFacePlay, agentFacePause, openCabinet, openAdminPanel, showEnvironmentSwitcher, get CURRENT_AUTH() { return CURRENT_AUTH; } };
  document.addEventListener('DOMContentLoaded', buildShell);
})();
