/* Legacy UI → new Aurora UI switch.
   Injected on each classic (legacy) page so operators always have a one-click
   path to the new primary interface. CSP-safe (external file, no inline code). */
(function () {
  if (document.getElementById('nta-new-ui-switch')) return;
  var a = document.createElement('a');
  a.id = 'nta-new-ui-switch';
  a.href = '/ui/';
  a.textContent = '✦ Новый интерфейс';
  a.title = 'Перейти на новый интерфейс NT-Analyzer';
  a.style.cssText = [
    'position:fixed', 'top:10px', 'right:12px', 'z-index:99999',
    'background:#6e8bff', 'color:#fff', 'padding:7px 14px', 'border-radius:8px',
    'font:600 13px/1 system-ui,Segoe UI,sans-serif', 'text-decoration:none',
    'box-shadow:0 4px 14px rgba(0,0,0,.35)', 'cursor:pointer'
  ].join(';');
  function mount() { (document.body || document.documentElement).appendChild(a); }
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
})();
