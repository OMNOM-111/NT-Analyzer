/* Legacy UI → new Aurora UI switch.
   Injected on each classic (legacy) page so operators always have a one-click
   path to the new primary interface. CSP-safe (external file, no inline code). */
(function () {
  var APP_NAME = 'StratForge AI';
  if (document.getElementById('nta-new-ui-switch')) return;
  var a = document.createElement('a');
  a.id = 'nta-new-ui-switch';
  a.href = '/ui/';
  a.textContent = '✦ Новый интерфейс';
  a.title = 'Перейти на новый интерфейс StratForge AI';
  a.style.cssText = [
    'position:fixed', 'top:10px', 'right:12px', 'z-index:99999',
    'background:linear-gradient(135deg,#1fc9ff,#8a56ff)', 'color:#fff', 'padding:7px 14px', 'border-radius:8px',
    'font:600 13px/1 system-ui,Segoe UI,sans-serif', 'text-decoration:none',
    'box-shadow:0 4px 14px rgba(0,0,0,.35)', 'cursor:pointer'
  ].join(';');
  function decorateHeader() {
    var h1 = document.querySelector('header h1');
    if (!h1 || h1.getAttribute('data-brand-decorated') === '1') return;
    h1.setAttribute('data-brand-decorated', '1');
    h1.style.display = 'flex';
    h1.style.alignItems = 'center';
    h1.style.gap = '10px';
    var mark = document.createElement('img');
    mark.src = '../brand/stratforge-mark.png';
    mark.alt = APP_NAME;
    mark.className = 'legacy-brand-mark';
    mark.style.width = '28px';
    mark.style.height = '28px';
    mark.style.flex = 'none';
    mark.style.filter = 'drop-shadow(0 4px 12px rgba(31, 201, 255, 0.18))';
    h1.insertBefore(mark, h1.firstChild);
  }
  function mount() { (document.body || document.documentElement).appendChild(a); }
  function init() { mount(); decorateHeader(); }
  if (document.body) init(); else document.addEventListener('DOMContentLoaded', init);
})();
