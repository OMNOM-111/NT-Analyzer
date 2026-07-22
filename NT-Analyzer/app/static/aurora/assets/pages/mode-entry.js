/* Initial product-contour selection.  It deliberately runs before ui.js. */
(function () {
  const KEY = 'stratforge.entry.mode';
  const state = document.getElementById('mode-entry-state');
  const lead = document.getElementById('mode-entry-lead');
  const status = document.getElementById('mode-entry-status');
  const options = Array.from(document.querySelectorAll('[data-mode]'));
  let auth = null;
  let currentMode = '';

  function applyBuildIdentity(payload) {
    const source = payload || {};
    const deployment = source.deployment && typeof source.deployment === 'object'
      ? source.deployment : source;
    const channel = String(deployment.release_channel || '').toLowerCase();
    const version = String(deployment.build_version || '').trim();
    const buildDate = String(deployment.build_date || '').trim();
    const labels = {
      development: { short: 'DEV', full: 'РАЗРАБОТКА', cls: 'dev' },
      canary: { short: 'CANARY', full: 'ПРЕДРЕЛИЗ', cls: 'canary' },
      stable: { short: 'STABLE', full: 'СТАБИЛЬНАЯ', cls: 'stable' },
    };
    if (!version || !buildDate || !labels[channel]) return;
    const label = labels[channel];
    const parts = buildDate.split('-');
    const visibleDate = parts.length === 3
      ? `${parts[2]}.${parts[1]}.${parts[0]}` : buildDate;
    const badge = document.getElementById('mode-entry-release-badge');
    const meta = document.getElementById('mode-entry-build-meta');
    if (badge) {
      badge.className = `rail-release-badge ${label.cls}`;
      badge.textContent = label.short;
      badge.title = label.full;
    }
    if (meta) {
      meta.textContent = `v${version} · от ${visibleDate}`;
      meta.title = `${label.full}: версия ${version}, сборка от ${visibleDate}`;
    }
    document.documentElement.dataset.releaseChannel = channel;
    document.title = `[${label.short}] Выбор режима — StratForge AI`;
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
