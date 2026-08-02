/* Initial product-contour selection.  It deliberately runs before ui.js. */
(function () {
  const KEY = 'stratforge.entry.mode';
  const state = document.getElementById('mode-entry-state');
  const lead = document.getElementById('mode-entry-lead');
  const status = document.getElementById('mode-entry-status');
  const options = Array.from(document.querySelectorAll('[data-mode]'));
  let auth = null;
  let currentMode = '';

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
    const visibleParts = [`v${version}`, gitSha.slice(0, 7)];
    if (dirty) visibleParts.push('dirty');
    const badge = document.getElementById('mode-entry-release-badge');
    const meta = document.getElementById('mode-entry-build-meta');
    if (badge) {
      badge.className = `rail-release-badge ${label.cls}`;
      badge.hidden = !label.short;
      badge.textContent = label.short;
      badge.title = label.short ? `${label.full} — ${environment}` : '';
    }
    if (meta) {
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
    }
    const brand = document.querySelector('[data-release-icon]');
    if (brand) brand.src = label.icon;
    const favicon = document.querySelector('link[rel~="icon"]');
    if (favicon) favicon.href = label.icon === RELEASE_ICONS.stable
      ? 'brand/stratforge-icon.ico' : label.icon;
    document.documentElement.dataset.deploymentEnvironment = environment;
    document.documentElement.dataset.releaseChannel = channel;
    document.title = label.short
      ? `[${label.short}] Выбор режима — StratForge AI`
      : 'Выбор режима — StratForge AI';
  }

  async function loadBuildIdentity() {
    try { applyBuildIdentity(await window.API.http.runtimeEnv({ retries: 0 })); }
    catch (e) { /* Keep the unresolved marker visible; never guess a channel. */ }
  }

  function label(mode) { return mode === 'beginner' ? 'Студент' : 'Профессионал'; }
  function destination(mode) { return mode === 'beginner' ? 'practice-trading.html' : 'index.html'; }
  function saveGuestChoice(mode) {
    try { sessionStorage.setItem(KEY, mode === 'beginner' ? 'student' : 'professional'); } catch (e) { /* optional */ }
  }
  function setStatus(text) { if (status) status.textContent = text || ''; }
  function setBusy(on) { options.forEach(btn => { btn.disabled = !!on; }); }
  function selectVisual(mode) {
    options.forEach(btn => {
      const selected = btn.dataset.mode === mode;
      btn.classList.toggle('selected', selected);
      const current = btn.querySelector('[data-current-mode]');
      if (current) current.remove();
      if (selected && currentMode) {
        const badge = document.createElement('small');
        badge.dataset.currentMode = '1';
        badge.textContent = 'Текущий режим';
        btn.appendChild(badge);
      }
    });
  }
  function route(mode) {
    saveGuestChoice(mode);
    window.location.replace(destination(mode));
  }
  async function choose(mode) {
    if (mode !== 'beginner' && mode !== 'professional') return;
    setBusy(true);
    setStatus('Открываю режим…');
    try {
      let resolvedMode = mode;
      if (auth) {
        if (currentMode && currentMode !== mode) {
          const changingToStudent = currentMode === 'professional' && mode === 'beginner';
          if (changingToStudent && !window.confirm('Перейти в режим «Студент»? Стратегии, AI и NinjaTrader будут скрыты до обратного переключения.')) {
            setStatus('Переключение отменено.');
            setBusy(false);
            return;
          }
          const out = await window.API.http.authUxMode({
            ux_mode: mode,
            confirm_downgrade: changingToStudent,
          });
          resolvedMode = String((out && out.ux_mode) || mode).toLowerCase();
        } else if (!currentMode) {
          const out = await window.API.http.authUxMode({ ux_mode: mode });
          resolvedMode = String((out && out.ux_mode) || mode).toLowerCase();
        }
      }
      // The server keeps the owner in the professional contour.  Honour the
      // effective response rather than briefly routing that account into the
      // student terminal.
      route(resolvedMode === 'beginner' ? 'beginner' : 'professional');
    } catch (error) {
      setStatus((error && error.message) || 'Не удалось сохранить режим. Повторите попытку.');
      setBusy(false);
    }
  }
  function show() {
    if (auth && currentMode) {
      if (state) state.textContent = `Сейчас выбран режим: ${label(currentMode)}`;
      if (lead) lead.textContent = 'Продолжите в текущий контур или явно переключите режим. Студенческий терминал и профессиональный command center не смешиваются.';
      selectVisual(currentMode);
      return;
    }
    if (auth) {
      if (state) state.textContent = 'Перед первым входом выберите режим';
      if (lead) lead.textContent = 'Выбор сохранится в профиле. Его можно изменить позднее через этот экран или кабинет.';
      return;
    }
    if (state) state.textContent = 'Ознакомительный вход';
    if (lead) lead.textContent = 'Выберите, какой интерфейс посмотреть. Для сохранения виртуального счёта и доступа к данным потребуется вход через Telegram.';
  }
  options.forEach(btn => btn.addEventListener('click', () => choose(String(btn.dataset.mode || ''))));
  loadBuildIdentity();
  (async function start() {
    try {
      const result = await window.API.authReady;
      auth = result && result.auth ? result.auth : null;
      const user = auth && auth.user ? auth.user : {};
      currentMode = String((auth && auth.ux_mode) || user.ux_mode || '').toLowerCase();
      if (currentMode !== 'beginner' && currentMode !== 'professional') currentMode = '';
    } catch (e) { auth = null; currentMode = ''; }
    show();
  })();
})();
