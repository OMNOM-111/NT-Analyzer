/* =====================================================================
   Desktop chart template — pure helpers (no DOM).

   Shared by the desktop page and node-based unit tests. A template is the
   instrument-free chart config used as the default for every new window and
   optionally pushed onto already-open charts ("apply to all").
   ===================================================================== */
(function (root) {
  'use strict';

  const TEMPLATE_KEY = 'desktop.chart-template.v1';

  const DEFAULT_STYLE = {
    upColor: '#34d399', downColor: '#ff6b81', upFill: '#34d399',
    downFill: '#ff6b81', background: '#0b1018', bodyWidth: 0.7, wickWidth: 1,
    borderWidth: 1, fillOpacity: 0.85, legendMode: 'compact',
    macd: { fill: true, up: '#34d399', down: '#ff6b81', line: '#4fd1e0', signal: '#fcc55a',
      opacity: 0.85, area: true, fillToZero: true, vol: false },
  };

  function cloneStyle(style) {
    const s = Object.assign({}, DEFAULT_STYLE, style || {});
    s.macd = Object.assign({}, DEFAULT_STYLE.macd, (style && style.macd) || {});
    return s;
  }

  function defaultTemplate() {
    return {
      timeframe: '5m',
      type: 'candles',
      indicators: [],
      range: { id: '1m', days: 31, from: '', to: '' },
      aspect: 'auto',
      style: cloneStyle(DEFAULT_STYLE),
    };
  }

  function normalizeTemplate(raw) {
    const base = defaultTemplate();
    const src = raw && typeof raw === 'object' ? raw : {};
    return {
      timeframe: src.timeframe || base.timeframe,
      type: src.type || base.type,
      indicators: Array.isArray(src.indicators) ? src.indicators.slice() : [],
      range: Object.assign({}, base.range, src.range || {}),
      aspect: src.aspect || base.aspect,
      style: cloneStyle(src.style),
    };
  }

  function makeTemplateFromConfig(cfg) {
    cfg = cfg || {};
    return normalizeTemplate({
      timeframe: cfg.timeframe,
      type: cfg.type,
      indicators: cfg.indicators,
      range: cfg.range,
      aspect: cfg.aspect,
      style: cfg.style,
    });
  }

  /** Merge a template onto an existing chart config, keeping instrument/root. */
  function applyTemplateToConfig(config, tpl) {
    const t = normalizeTemplate(tpl);
    const base = config && typeof config === 'object' ? config : {};
    return Object.assign({}, base, {
      timeframe: t.timeframe,
      type: t.type,
      indicators: t.indicators.slice(),
      range: Object.assign({}, t.range),
      aspect: t.aspect,
      style: cloneStyle(t.style),
    });
  }

  function loadTemplate(storage) {
    let raw = null;
    try {
      const store = storage || (typeof localStorage !== 'undefined' ? localStorage : null);
      if (store) raw = JSON.parse(store.getItem(TEMPLATE_KEY) || 'null');
    } catch (e) { raw = null; }
    return normalizeTemplate(raw);
  }

  function saveTemplate(tpl, storage) {
    const normalized = normalizeTemplate(tpl);
    try {
      const store = storage || (typeof localStorage !== 'undefined' ? localStorage : null);
      if (store) store.setItem(TEMPLATE_KEY, JSON.stringify(normalized));
    } catch (e) { /* storage off / quota */ }
    return normalized;
  }

  const api = {
    TEMPLATE_KEY,
    DEFAULT_STYLE,
    cloneStyle,
    defaultTemplate,
    normalizeTemplate,
    makeTemplateFromConfig,
    applyTemplateToConfig,
    loadTemplate,
    saveTemplate,
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.DesktopTemplate = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
