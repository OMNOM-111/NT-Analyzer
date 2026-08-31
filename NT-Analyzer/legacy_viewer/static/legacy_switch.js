/* Isolated Legacy Viewer marker. Backend enforcement remains authoritative. */
(function () {
  if (document.getElementById('stratforge-legacy-viewer-banner')) return;
  var banner = document.createElement('div');
  banner.id = 'stratforge-legacy-viewer-banner';
  banner.textContent = 'StratForge Legacy Viewer | READ ONLY SNAPSHOT';
  banner.style.cssText = [
    'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:99999',
    'background:#111827', 'color:#f8fafc', 'border-bottom:1px solid #334155',
    'padding:7px 12px', 'font:600 12px/1.2 Segoe UI,sans-serif',
    'text-align:center', 'letter-spacing:0'
  ].join(';');

  function mount() {
    document.body.style.paddingTop = '30px';
    document.body.appendChild(banner);
    if (typeof api !== 'undefined' && api) {
      var blocked = function () { return Promise.reject(new Error('Legacy Viewer is read-only.')); };
      api.post = blocked;
      api.delete = blocked;
    }
  }
  if (document.body) mount();
  else document.addEventListener('DOMContentLoaded', mount);
})();
