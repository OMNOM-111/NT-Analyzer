/* Screens of the previous architecture: kept for сверка, never part of the path.

   The owner's decision of 20.09.2026: the old surfaces leave the active user
   path and remain only as read-only history, so a developer can still see how
   the system used to work and compare it with the new Agent World. Nothing may
   change the system from here - every write is refused before it leaves the
   page, and the banner says where the working path is. */
(function () {
  'use strict';
  var SAFE = { GET: 1, HEAD: 1, OPTIONS: 1 };
  var REFUSAL = 'Это экран прежней архитектуры: он сохранён только для сверки. Действия отсюда отключены — рабочий путь в AI Центре.';

  function methodOf(input, init) {
    var method = (init && init.method)
      || (input && typeof input === 'object' && input.method)
      || 'GET';
    return String(method).toUpperCase();
  }

  var fetched = window.fetch;
  if (typeof fetched === 'function') {
    window.fetch = function (input, init) {
      if (!SAFE[methodOf(input, init)]) return Promise.reject(new Error(REFUSAL));
      return fetched.apply(this, arguments);
    };
  }
  var open = window.XMLHttpRequest && window.XMLHttpRequest.prototype.open;
  if (open) {
    window.XMLHttpRequest.prototype.open = function (method) {
      if (!SAFE[String(method || 'GET').toUpperCase()]) throw new Error(REFUSAL);
      return open.apply(this, arguments);
    };
  }

  function banner() {
    if (document.getElementById('legacy-banner')) return;
    var box = document.createElement('div');
    box.id = 'legacy-banner';
    box.setAttribute('role', 'status');
    box.innerHTML = '<strong>Архив прежней архитектуры.</strong> '
      + 'Экран сохранён для сверки и разработки: смотреть можно, изменить отсюда ничего нельзя. '
      + 'Рабочий путь — <a href="ai-command-center.html">AI Центр</a>: вы ставите поручение Заместителю, он распределяет работу и возвращает итог.';
    var host = document.querySelector('.content') || document.querySelector('main') || document.body;
    host.insertBefore(box, host.firstChild);
    document.body.dataset.legacyScreen = '1';
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', banner);
  else banner();
})();
