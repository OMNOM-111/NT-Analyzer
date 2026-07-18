/* Initial product-contour selection.  It deliberately runs before ui.js. */
(function () {
  const KEY = 'stratforge.entry.mode';
  const state = document.getElementById('mode-entry-state');
  const lead = document.getElementById('mode-entry-lead');
  const status = document.getElementById('mode-entry-status');
  const options = Array.from(document.querySelectorAll('[data-mode]'));
  let auth = null;
  let currentMode = '';

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
