// strategies.js — standalone "Стратегии" dashboard.
// Counts approved Strategy Profiles in the portfolio. Reserved research
// profiles stay visible in their fixed cells, but they do not occupy
// approved portfolio slots.
(() => {
  "use strict";

  const TARGET_SLOTS = 10;
  const TARGET_MONTHLY_PROFIT = 2000;
  const TARGET_TRADES_30D = 60;
  const PAGE_LIMIT = 1000;
  const STRATEGIES_LAYOUT_STORAGE_KEY = "ntanalyzer:strategies-layout:v3";
  const STRATEGIES_COMPACT_MEDIA_QUERY = "(max-width: 1180px)";
  const PORTFOLIO_ROOT_ORDER = [
    "MGC",
    "MNQ",
    "M2K",
    "M6A",
    "M6B",
    "M6E",
    "M6J",
    "MBT",
    "MCL",
    "MES",
    "MET",
    "MYM",
  ];
  const PORTFOLIO_ROOT_INDEX = new Map(PORTFOLIO_ROOT_ORDER.map((root, index) => [root, index]));
  const CELL_ID_PATTERN = /^CELL-(\d{3})$/i;
  const PROFILE_DISPLAY_NAME_RE = /^([A-Za-z][A-Za-z0-9]*(?:[ /&-][A-Za-z0-9]+)*) [A-Z0-9]+ \d+[mhd] v\d+( c\d{3})?$/;
  const VERSION_TOKEN_RE = /(?:^|[^A-Za-z0-9_]|_)v\s*(\d+)(?:$|[^A-Za-z0-9_]|_)/i;
  const APPROVED_PROFILE_FAMILY_PREFIXES = [
    "Scalping",
    "VWAP Pullback",
    "VWAP Short",
    "B1 ShortOnly",
    "ORB Open Scalp",
    "ORB Continuation",
    "Failed ORB Reversal",
    "VWAP Mean Reversion",
    "Compression Breakout",
    "Rolling VWAP Crypto",
    "Levels",
  ];
  const RU_DATE_FORMATTER = new Intl.DateTimeFormat("ru-RU", {
    timeZone: "UTC",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  const STATUS_LABEL = {
    ready: "Готова",
    in_progress: "В процессе",
    baseline: "Исследование",
    candidate: "Кандидат",
    rejected: "Отклонена",
    archived: "Архив",
    runtime_online: "Online",
  };
  const STATUS_ORDER = {
    ready: 0,
    runtime_online: 1,
    in_progress: 2,
  };

  const STATE = {
    coverage: null,
    catalog: null,
    profiles: [],
    jobs: [],
    runtimeRows: [],
    instruments: [],
    selectedRoot: "",
    selectedKey: "",
    revealSelectionAfterRender: false,
    search: "",
    statusFilter: "all",
    selectedHistoryJobId: "",
    historyViewerTab: "summary",
    historyLoadingJobId: "",
    historyJobId: "",
    historyJob: null,
    historyTrades: [],
    historyBarsJobId: "",
    historyBars: [],
    historyBarsStatus: "idle",
    historyError: "",
    researchLoadingJobId: "",
    researchJobId: "",
    researchJob: null,
    researchTrades: [],
    researchError: "",
    researchErrorJobId: "",
    researchCache: new Map(),
    errors: [],
    loadToken: 0,
    catalogClasses: new Set(),
    catalogDisplayNames: new Map(),
  };
  const PANE_RESIZE = {
    side: "",
    pointerId: null,
    startX: 0,
    startWidth: 0,
    handle: null,
  };
  const TOP_RESIZE = {
    pointerId: null,
    startY: 0,
    startHeight: 0,
    handle: null,
  };
  const RESEARCH_RESIZE = {
    pointerId: null,
    startX: 0,
    startWidth: 0,
    handle: null,
  };
  let researchChartRedrawRaf = 0;

  const $ = (id) => document.getElementById(id);

  function portfolioRoot(value) {
    return rootOf(value || "");
  }

  function portfolioRootIndex(value) {
    const root = portfolioRoot(value);
    return PORTFOLIO_ROOT_INDEX.has(root) ? PORTFOLIO_ROOT_INDEX.get(root) : -1;
  }

  function portfolioSlotNumber(value) {
    const slot = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isInteger(slot) || slot < 1 || slot > TARGET_SLOTS) return 0;
    return slot;
  }

  function portfolioCellId(root, slot) {
    const index = portfolioRootIndex(root);
    const slotNo = portfolioSlotNumber(slot);
    if (index < 0 || !slotNo) return "";
    return `CELL-${String((index * TARGET_SLOTS) + slotNo).padStart(3, "0")}`;
  }

  function slotFromCellId(cellId, root = "") {
    const match = String(cellId || "").trim().match(CELL_ID_PATTERN);
    if (!match) return 0;
    const number = Number.parseInt(match[1], 10);
    if (!Number.isInteger(number) || number < 1 || number > PORTFOLIO_ROOT_ORDER.length * TARGET_SLOTS) return 0;
    if (root) {
      const expectedRoot = PORTFOLIO_ROOT_ORDER[Math.floor((number - 1) / TARGET_SLOTS)] || "";
      if (expectedRoot !== portfolioRoot(root)) return 0;
    }
    return ((number - 1) % TARGET_SLOTS) + 1;
  }

  function profilePortfolioSortKey(profile) {
    const candidates = [
      profile?.stable_id,
      profile?.deploy_strategy_class,
      profile?.strategy_class,
      profile?.profile_id,
      profile?.name,
    ];
    for (const value of candidates) {
      const text = String(value || "").trim().toLowerCase();
      if (text) return text;
    }
    return "";
  }

  function familyPortfolioSortKey(family) {
    return profilePortfolioSortKey(family?.primary)
      || String(family?.ntClass || family?.key || family?.baseName || "").trim().toLowerCase();
  }

  function explicitSlotForProfile(profile, root = "") {
    return portfolioSlotNumber(profile?.slot) || slotFromCellId(profile?.cell_id, root || profileRoot(profile));
  }

  function profileHasExplicitSlot(profile, root = "") {
    return !!explicitSlotForProfile(profile, root);
  }

  function profileVisibleInMatrix(profile) {
    if (!profile || profile.runtimeOnly || profile.catalogOnly) return false;
    if (isReadyStatus(profile.status)) return true;
    switch (String(profile?.status || "").trim()) {
      case "research_baseline":
      case "paper_candidate":
      case "in_progress":
      case "rejected":
        return profileHasExplicitSlot(profile);
      default:
        return false;
    }
  }

  function explicitSlotForFamily(family) {
    const slots = (family?.versions || [])
      .map(profile => explicitSlotForProfile(profile, family?.root))
      .filter(Boolean)
      .sort((a, b) => a - b);
    return slots[0] || 0;
  }

  function assignFamilySlots(root, families) {
    const slots = Array.from({ length: TARGET_SLOTS }, () => null);
    const assignedKeys = new Set();
    const sortedFamilies = families.slice().sort((a, b) => {
      const ak = familyPortfolioSortKey(a);
      const bk = familyPortfolioSortKey(b);
      return ak.localeCompare(bk, "ru");
    });

    sortedFamilies
      .filter(family => family.explicitSlot > 0)
      .sort((a, b) => a.explicitSlot - b.explicitSlot || familyPortfolioSortKey(a).localeCompare(familyPortfolioSortKey(b), "ru"))
      .forEach(family => {
        const slotIndex = family.explicitSlot - 1;
        if (slotIndex < 0 || slotIndex >= TARGET_SLOTS || slots[slotIndex]) return;
        slots[slotIndex] = family;
        assignedKeys.add(family.key);
      });

    const freeSlots = [];
    for (let slot = 1; slot <= TARGET_SLOTS; slot += 1) {
      if (!slots[slot - 1]) freeSlots.push(slot);
    }

    sortedFamilies.forEach(family => {
      if (assignedKeys.has(family.key) || !freeSlots.length) return;
      const slot = freeSlots.shift();
      if (!slot) return;
      slots[slot - 1] = family;
      assignedKeys.add(family.key);
    });

    const assignedFamilies = [];
    slots.forEach((family, index) => {
      if (!family) return;
      family.slot = index + 1;
      family.slotLabel = `Стратегия ${family.slot}`;
      family.cellId = portfolioCellId(root, family.slot);
      assignedFamilies.push(family);
    });

    return { families: assignedFamilies, slots };
  }

  function clampNumber(value, min, max) {
    const safeMin = Number.isFinite(min) ? min : 0;
    const safeMax = Number.isFinite(max) ? max : safeMin;
    const upper = safeMax >= safeMin ? safeMax : safeMin;
    const n = Number(value);
    if (!Number.isFinite(n)) return safeMin;
    return Math.min(upper, Math.max(safeMin, n));
  }

  function parsePx(value, fallback) {
    const n = Number.parseFloat(String(value || "").trim());
    return Number.isFinite(n) ? n : fallback;
  }

  function isCompactStrategiesLayout() {
    return window.matchMedia(STRATEGIES_COMPACT_MEDIA_QUERY).matches;
  }

  function strategiesGrid() {
    return $("strategies-main-grid");
  }

  function strategiesPage() {
    return $("strategies-page");
  }

  function researchPanel() {
    return $("strategies-research-panel");
  }

  function researchLayout() {
    return $("strategies-research-layout");
  }

  function paneMetrics(grid) {
    const style = getComputedStyle(grid);
    return {
      total: grid.clientWidth,
      leftMin: parsePx(style.getPropertyValue("--strategies-left-min"), 260),
      leftMaxBase: parsePx(style.getPropertyValue("--strategies-left-max"), 520),
      centerMin: parsePx(style.getPropertyValue("--strategies-center-min"), 560),
      rightMin: parsePx(style.getPropertyValue("--strategies-right-min"), 320),
      rightMaxBase: parsePx(style.getPropertyValue("--strategies-right-max"), 760),
      resizerWidth: parsePx(style.getPropertyValue("--strategies-resizer-width"), 12),
    };
  }

  function topPanelMetrics(page) {
    const style = getComputedStyle(page);
    return {
      total: page.clientHeight,
      min: parsePx(style.getPropertyValue("--strategies-top-min"), 230),
      maxBase: parsePx(style.getPropertyValue("--strategies-top-max"), 720),
      mainMin: parsePx(style.getPropertyValue("--strategies-main-min"), 260),
      resizerHeight: parsePx(style.getPropertyValue("--strategies-row-resizer-height"), 12),
    };
  }

  function currentPaneWidths(grid) {
    const style = getComputedStyle(grid);
    return {
      left: parsePx(style.getPropertyValue("--strategies-left-width"), 310),
      right: parsePx(style.getPropertyValue("--strategies-right-width"), 440),
    };
  }

  function currentTopHeight(page) {
    const style = getComputedStyle(page);
    const fallback = Math.round(page.clientHeight * 0.52);
    return parsePx(style.getPropertyValue("--strategies-top-height"), fallback);
  }

  function currentResearchChartWidth(panel) {
    const style = getComputedStyle(panel);
    return parsePx(style.getPropertyValue("--strategies-research-chart-width"), 620);
  }

  function paneBounds(side, grid, otherWidth) {
    const metrics = paneMetrics(grid);
    const gutters = metrics.resizerWidth * 2;
    if (side === "left") {
      const max = Math.min(
        metrics.leftMaxBase,
        metrics.total - otherWidth - metrics.centerMin - gutters,
      );
      return {
        min: metrics.leftMin,
        max: Math.max(metrics.leftMin, max),
      };
    }
    const max = Math.min(
      metrics.rightMaxBase,
      metrics.total - otherWidth - metrics.centerMin - gutters,
    );
    return {
      min: metrics.rightMin,
      max: Math.max(metrics.rightMin, max),
    };
  }

  function topPanelBounds(page) {
    const metrics = topPanelMetrics(page);
    const max = Math.min(
      metrics.maxBase,
      metrics.total - metrics.mainMin - metrics.resizerHeight,
    );
    return {
      min: metrics.min,
      max: Math.max(metrics.min, max),
    };
  }

  function researchPanelMetrics(panel) {
    const style = getComputedStyle(panel);
    return {
      chartMin: parsePx(style.getPropertyValue("--strategies-research-chart-min"), 420),
      chartMaxBase: parsePx(style.getPropertyValue("--strategies-research-chart-max"), 1200),
      factsMin: parsePx(style.getPropertyValue("--strategies-research-facts-min"), 260),
      resizerWidth: parsePx(style.getPropertyValue("--strategies-research-inner-resizer-width"), 12),
    };
  }

  function researchChartBounds(panel) {
    const layout = researchLayout();
    const body = $("strategies-research-body");
    const metrics = researchPanelMetrics(panel);
    const total = layout?.clientWidth || body?.clientWidth || panel.clientWidth;
    const max = Math.min(
      metrics.chartMaxBase,
      total - metrics.factsMin - metrics.resizerWidth,
    );
    return {
      min: metrics.chartMin,
      max: Math.max(metrics.chartMin, max),
    };
  }

  function readStoredPaneLayout() {
    try {
      const raw = window.localStorage.getItem(STRATEGIES_LAYOUT_STORAGE_KEY);
      const data = raw ? JSON.parse(raw) : null;
      return data && typeof data === "object" ? data : {};
    } catch {
      return {};
    }
  }

  function updatePaneResizerA11y(grid) {
    if (!grid) return;
    const widths = currentPaneWidths(grid);
    const leftBounds = paneBounds("left", grid, widths.right);
    const rightBounds = paneBounds("right", grid, widths.left);
    const pairs = [
      [$("strategies-left-resizer"), widths.left, leftBounds],
      [$("strategies-right-resizer"), widths.right, rightBounds],
    ];
    pairs.forEach(([handle, width, bounds]) => {
      if (!handle) return;
      handle.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
      handle.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
      handle.setAttribute("aria-valuenow", String(Math.round(width)));
      handle.setAttribute("aria-valuetext", `${Math.round(width)} пикселей`);
    });
  }

  function updateTopResizerA11y(page) {
    if (!page) return;
    const handle = $("strategies-top-resizer");
    if (!handle) return;
    const bounds = topPanelBounds(page);
    const height = currentTopHeight(page);
    handle.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    handle.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
    handle.setAttribute("aria-valuenow", String(Math.round(height)));
    handle.setAttribute("aria-valuetext", `${Math.round(height)} пикселей`);
  }

  function updateResearchResizerA11y(panel) {
    const handle = $("strategies-research-resizer");
    if (!panel || !handle || isCompactStrategiesLayout()) return;
    const bounds = researchChartBounds(panel);
    const width = currentResearchChartWidth(panel);
    handle.setAttribute("aria-valuemin", String(Math.round(bounds.min)));
    handle.setAttribute("aria-valuemax", String(Math.round(bounds.max)));
    handle.setAttribute("aria-valuenow", String(Math.round(width)));
    handle.setAttribute("aria-valuetext", `${Math.round(width)} пикселей`);
  }

  function redrawResearchChart() {
    const canvas = document.querySelector("#strategies-research-body .strategies-equity-canvas");
    if (!canvas) return;
    const family = selectedFamily();
    const profile = selectedResearchProfile(family);
    if (!family || !profile) return;
    const jobId = researchJobIdForProfile(profile, family);
    const snapshot = researchSnapshot(jobId);
    if (!snapshot.loaded || !snapshot.job) return;
    drawHistoryEquity(canvas, snapshot.trades || [], snapshot.job);
  }

  function scheduleResearchChartRedraw() {
    if (researchChartRedrawRaf) cancelAnimationFrame(researchChartRedrawRaf);
    researchChartRedrawRaf = requestAnimationFrame(() => {
      researchChartRedrawRaf = 0;
      redrawResearchChart();
    });
  }

  function persistPaneLayout(grid) {
    const page = strategiesPage();
    const panel = researchPanel();
    if (!grid || !page || !panel) return;
    const widths = currentPaneWidths(grid);
    try {
      window.localStorage.setItem(STRATEGIES_LAYOUT_STORAGE_KEY, JSON.stringify({
        leftWidth: Math.round(widths.left),
        rightWidth: Math.round(widths.right),
        topHeight: Math.round(currentTopHeight(page)),
        researchChartWidth: Math.round(currentResearchChartWidth(panel)),
      }));
    } catch {}
    updatePaneResizerA11y(grid);
    updateTopResizerA11y(page);
    updateResearchResizerA11y(panel);
  }

  function applyPaneWidth(side, width, options = {}) {
    const grid = strategiesGrid();
    if (!grid) return null;
    const widths = currentPaneWidths(grid);
    const otherWidth = side === "left" ? widths.right : widths.left;
    const bounds = paneBounds(side, grid, otherWidth);
    const next = Math.round(clampNumber(width, bounds.min, bounds.max));
    const cssVar = side === "left" ? "--strategies-left-width" : "--strategies-right-width";
    grid.style.setProperty(cssVar, `${next}px`);
    updatePaneResizerA11y(grid);
    if (options.persist !== false) persistPaneLayout(grid);
    return next;
  }

  function applyTopHeight(height, options = {}) {
    const page = strategiesPage();
    if (!page) return null;
    const bounds = topPanelBounds(page);
    const next = Math.round(clampNumber(height, bounds.min, bounds.max));
    page.style.setProperty("--strategies-top-height", `${next}px`);
    updateTopResizerA11y(page);
    if (options.persist !== false) persistPaneLayout(strategiesGrid());
    return next;
  }

  function applyResearchChartWidth(width, options = {}) {
    const panel = researchPanel();
    if (!panel) return null;
    const bounds = researchChartBounds(panel);
    const next = Math.round(clampNumber(width, bounds.min, bounds.max));
    panel.style.setProperty("--strategies-research-chart-width", `${next}px`);
    updateResearchResizerA11y(panel);
    scheduleResearchChartRedraw();
    if (options.persist !== false) persistPaneLayout(strategiesGrid());
    return next;
  }

  function syncPaneLayout() {
    const grid = strategiesGrid();
    const page = strategiesPage();
    const panel = researchPanel();
    if (!grid || !page || !panel) return;
    if (isCompactStrategiesLayout()) {
      updatePaneResizerA11y(grid);
      updateTopResizerA11y(page);
      updateResearchResizerA11y(panel);
      return;
    }
    const stored = readStoredPaneLayout();
    applyTopHeight(Number(stored.topHeight) || currentTopHeight(page), { persist: false });
    const widths = currentPaneWidths(grid);
    applyPaneWidth("left", Number(stored.leftWidth) || widths.left, { persist: false });
    const updated = currentPaneWidths(grid);
    applyPaneWidth("right", Number(stored.rightWidth) || updated.right, { persist: false });
    applyResearchChartWidth(Number(stored.researchChartWidth) || currentResearchChartWidth(panel), { persist: false });
    persistPaneLayout(grid);
    scheduleResearchChartRedraw();
  }

  function stopPaneResize() {
    if (!PANE_RESIZE.side) return;
    const grid = strategiesGrid();
    document.body.classList.remove("strategies-resizing");
    if (grid) grid.classList.remove("is-resizing");
    if (PANE_RESIZE.handle) {
      PANE_RESIZE.handle.classList.remove("active");
      if (PANE_RESIZE.pointerId != null && typeof PANE_RESIZE.handle.releasePointerCapture === "function") {
        try { PANE_RESIZE.handle.releasePointerCapture(PANE_RESIZE.pointerId); } catch {}
      }
    }
    persistPaneLayout(grid);
    PANE_RESIZE.side = "";
    PANE_RESIZE.pointerId = null;
    PANE_RESIZE.startX = 0;
    PANE_RESIZE.startWidth = 0;
    PANE_RESIZE.handle = null;
  }

  function onPaneResizePointerDown(ev) {
    const side = String(ev.currentTarget?.dataset?.resizeSide || "");
    if (!side || isCompactStrategiesLayout()) return;
    const grid = strategiesGrid();
    if (!grid) return;
    const widths = currentPaneWidths(grid);
    PANE_RESIZE.side = side;
    PANE_RESIZE.pointerId = ev.pointerId;
    PANE_RESIZE.startX = ev.clientX;
    PANE_RESIZE.startWidth = side === "left" ? widths.left : widths.right;
    PANE_RESIZE.handle = ev.currentTarget;
    document.body.classList.add("strategies-resizing");
    grid.classList.add("is-resizing");
    ev.currentTarget.classList.add("active");
    if (typeof ev.currentTarget.setPointerCapture === "function") {
      ev.currentTarget.setPointerCapture(ev.pointerId);
    }
    ev.preventDefault();
  }

  function onPaneResizePointerMove(ev) {
    if (!PANE_RESIZE.side) return;
    const delta = ev.clientX - PANE_RESIZE.startX;
    const width = PANE_RESIZE.side === "left"
      ? PANE_RESIZE.startWidth + delta
      : PANE_RESIZE.startWidth - delta;
    applyPaneWidth(PANE_RESIZE.side, width, { persist: false });
  }

  function onPaneResizeKeyDown(ev) {
    const side = String(ev.currentTarget?.dataset?.resizeSide || "");
    if (!side || isCompactStrategiesLayout()) return;
    const grid = strategiesGrid();
    if (!grid) return;
    const widths = currentPaneWidths(grid);
    const otherWidth = side === "left" ? widths.right : widths.left;
    const bounds = paneBounds(side, grid, otherWidth);
    const current = side === "left" ? widths.left : widths.right;
    const step = ev.shiftKey ? 48 : 16;
    let next = current;

    if (ev.key === "ArrowLeft") {
      next = side === "left" ? current - step : current + step;
    } else if (ev.key === "ArrowRight") {
      next = side === "left" ? current + step : current - step;
    } else if (ev.key === "Home") {
      next = bounds.min;
    } else if (ev.key === "End") {
      next = bounds.max;
    } else {
      return;
    }

    ev.preventDefault();
    applyPaneWidth(side, next);
  }

  function stopTopResize() {
    if (!TOP_RESIZE.handle) return;
    const page = strategiesPage();
    document.body.classList.remove("strategies-row-resizing");
    if (page) page.classList.remove("is-row-resizing");
    if (TOP_RESIZE.handle) {
      TOP_RESIZE.handle.classList.remove("active");
      if (TOP_RESIZE.pointerId != null && typeof TOP_RESIZE.handle.releasePointerCapture === "function") {
        try { TOP_RESIZE.handle.releasePointerCapture(TOP_RESIZE.pointerId); } catch {}
      }
    }
    persistPaneLayout(strategiesGrid());
    TOP_RESIZE.pointerId = null;
    TOP_RESIZE.startY = 0;
    TOP_RESIZE.startHeight = 0;
    TOP_RESIZE.handle = null;
  }

  function onTopResizePointerDown(ev) {
    if (isCompactStrategiesLayout()) return;
    const page = strategiesPage();
    if (!page) return;
    TOP_RESIZE.pointerId = ev.pointerId;
    TOP_RESIZE.startY = ev.clientY;
    TOP_RESIZE.startHeight = currentTopHeight(page);
    TOP_RESIZE.handle = ev.currentTarget;
    document.body.classList.add("strategies-row-resizing");
    page.classList.add("is-row-resizing");
    ev.currentTarget.classList.add("active");
    if (typeof ev.currentTarget.setPointerCapture === "function") {
      ev.currentTarget.setPointerCapture(ev.pointerId);
    }
    ev.preventDefault();
  }

  function onTopResizePointerMove(ev) {
    if (!TOP_RESIZE.handle) return;
    const delta = ev.clientY - TOP_RESIZE.startY;
    applyTopHeight(TOP_RESIZE.startHeight + delta, { persist: false });
  }

  function onTopResizeKeyDown(ev) {
    if (isCompactStrategiesLayout()) return;
    const page = strategiesPage();
    if (!page) return;
    const bounds = topPanelBounds(page);
    const current = currentTopHeight(page);
    const step = ev.shiftKey ? 48 : 16;
    let next = current;
    if (ev.key === "ArrowUp") next = current - step;
    else if (ev.key === "ArrowDown") next = current + step;
    else if (ev.key === "Home") next = bounds.min;
    else if (ev.key === "End") next = bounds.max;
    else return;
    ev.preventDefault();
    applyTopHeight(next);
  }

  function stopResearchResize() {
    if (!RESEARCH_RESIZE.handle) return;
    const layout = researchLayout();
    document.body.classList.remove("strategies-research-resizing");
    if (layout) layout.classList.remove("is-resizing");
    if (RESEARCH_RESIZE.handle) {
      RESEARCH_RESIZE.handle.classList.remove("active");
      if (RESEARCH_RESIZE.pointerId != null && typeof RESEARCH_RESIZE.handle.releasePointerCapture === "function") {
        try { RESEARCH_RESIZE.handle.releasePointerCapture(RESEARCH_RESIZE.pointerId); } catch {}
      }
    }
    persistPaneLayout(strategiesGrid());
    RESEARCH_RESIZE.pointerId = null;
    RESEARCH_RESIZE.startX = 0;
    RESEARCH_RESIZE.startWidth = 0;
    RESEARCH_RESIZE.handle = null;
  }

  function onResearchResizePointerDown(ev) {
    if (isCompactStrategiesLayout()) return;
    const panel = researchPanel();
    const layout = researchLayout();
    if (!panel || !layout) return;
    RESEARCH_RESIZE.pointerId = ev.pointerId;
    RESEARCH_RESIZE.startX = ev.clientX;
    RESEARCH_RESIZE.startWidth = currentResearchChartWidth(panel);
    RESEARCH_RESIZE.handle = ev.currentTarget;
    document.body.classList.add("strategies-research-resizing");
    layout.classList.add("is-resizing");
    ev.currentTarget.classList.add("active");
    if (typeof ev.currentTarget.setPointerCapture === "function") {
      ev.currentTarget.setPointerCapture(ev.pointerId);
    }
    ev.preventDefault();
  }

  function onResearchResizePointerMove(ev) {
    if (!RESEARCH_RESIZE.handle) return;
    const delta = ev.clientX - RESEARCH_RESIZE.startX;
    applyResearchChartWidth(RESEARCH_RESIZE.startWidth + delta, { persist: false });
  }

  function onResearchResizeKeyDown(ev) {
    if (isCompactStrategiesLayout()) return;
    const panel = researchPanel();
    if (!panel) return;
    const bounds = researchChartBounds(panel);
    const current = currentResearchChartWidth(panel);
    const step = ev.shiftKey ? 48 : 16;
    let next = current;
    if (ev.key === "ArrowLeft") next = current - step;
    else if (ev.key === "ArrowRight") next = current + step;
    else if (ev.key === "Home") next = bounds.min;
    else if (ev.key === "End") next = bounds.max;
    else return;
    ev.preventDefault();
    applyResearchChartWidth(next);
  }

  function bindResearchResizer() {
    const handle = $("strategies-research-resizer");
    const panel = researchPanel();
    if (!handle || !panel || handle.dataset.bound === "1") {
      updateResearchResizerA11y(panel);
      return;
    }
    handle.dataset.bound = "1";
    handle.addEventListener("pointerdown", onResearchResizePointerDown);
    handle.addEventListener("keydown", onResearchResizeKeyDown);
    updateResearchResizerA11y(panel);
  }

  function bindPaneLayout() {
    const handles = [
      $("strategies-left-resizer"),
      $("strategies-right-resizer"),
    ];
    handles.forEach(handle => {
      if (!handle) return;
      handle.addEventListener("pointerdown", onPaneResizePointerDown);
      handle.addEventListener("keydown", onPaneResizeKeyDown);
    });
    const topHandle = $("strategies-top-resizer");
    if (topHandle) {
      topHandle.addEventListener("pointerdown", onTopResizePointerDown);
      topHandle.addEventListener("keydown", onTopResizeKeyDown);
    }
    window.addEventListener("pointermove", onPaneResizePointerMove);
    window.addEventListener("pointerup", stopPaneResize);
    window.addEventListener("pointercancel", stopPaneResize);
    window.addEventListener("pointermove", onTopResizePointerMove);
    window.addEventListener("pointerup", stopTopResize);
    window.addEventListener("pointercancel", stopTopResize);
    window.addEventListener("pointermove", onResearchResizePointerMove);
    window.addEventListener("pointerup", stopResearchResize);
    window.addEventListener("pointercancel", stopResearchResize);
    window.addEventListener("resize", syncPaneLayout);
    syncPaneLayout();
  }

  async function api(url) {
    const r = await fetch(url);
    const txt = await r.text();
    let json = null;
    try { json = txt ? JSON.parse(txt) : null; } catch { json = null; }
    if (!r.ok) {
      const msg = (json && (json.error || json.detail)) || txt || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return json;
  }

  async function apiPost(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const txt = await r.text();
    let json = null;
    try { json = txt ? JSON.parse(txt) : null; } catch { json = null; }
    if (!r.ok) {
      const msg = (json && (json.error || json.detail)) || txt || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return json;
  }

  async function loadAllTradesForJob(jobId) {
    const trades = [];
    let offset = 0;
    const limit = 1000;
    for (let page = 0; page < 20; page += 1) {
      const data = await api(`/api/jobs/${encodeURIComponent(jobId)}/trades?offset=${offset}&limit=${limit}`);
      const rows = Array.isArray(data.trades) ? data.trades : [];
      trades.push(...rows);
      offset += rows.length;
      if (!rows.length || rows.length < limit || offset >= Number(data.total || 0)) break;
    }
    return trades;
  }

  async function loadBarsForJob(jobId) {
    const bars = [];
    let offset = 0;
    const limit = 50000;
    const hardCap = 250000;
    for (let page = 0; page < 8 && offset < hardCap; page += 1) {
      const data = await api(`/api/jobs/${encodeURIComponent(jobId)}/bars?offset=${offset}&limit=${limit}`);
      const rows = Array.isArray(data.bars) ? data.bars : [];
      bars.push(...rows);
      offset += rows.length;
      if (!rows.length || rows.length < limit || offset >= Number(data.total || 0)) break;
    }
    return bars;
  }

  function ensureHistoryReportLoaded(jobId) {
    const id = String(jobId || "").trim();
    if (!id) return;
    if (STATE.historyJobId === id && STATE.historyJob) return;
    if (STATE.historyLoadingJobId === id) return;
    STATE.historyLoadingJobId = id;
    STATE.historyError = "";
    STATE.historyJobId = "";
    STATE.historyJob = null;
    STATE.historyTrades = [];
    STATE.historyBarsJobId = "";
    STATE.historyBars = [];
    STATE.historyBarsStatus = "idle";
    Promise.all([
      api(`/api/jobs/${encodeURIComponent(id)}`),
      loadAllTradesForJob(id),
    ]).then(([job, trades]) => {
      if (STATE.selectedHistoryJobId !== id) return;
      STATE.historyLoadingJobId = "";
      STATE.historyJobId = id;
      STATE.historyJob = job;
      STATE.historyTrades = trades;
      renderDetail({ preserveScroll: true });
      if (STATE.historyViewerTab === "chart") ensureHistoryBarsLoaded(id);
    }).catch(err => {
      if (STATE.selectedHistoryJobId !== id) return;
      STATE.historyLoadingJobId = "";
      STATE.historyError = err.message || String(err);
      renderDetail({ preserveScroll: true });
    });
  }

  function ensureHistoryBarsLoaded(jobId) {
    const id = String(jobId || "").trim();
    if (!id) return;
    if (STATE.historyBarsJobId === id && STATE.historyBarsStatus === "ok") return;
    if (STATE.historyBarsJobId === id && STATE.historyBarsStatus === "loading") return;
    STATE.historyBarsJobId = id;
    STATE.historyBars = [];
    STATE.historyBarsStatus = "loading";
    loadBarsForJob(id).then(bars => {
      if (STATE.selectedHistoryJobId !== id) return;
      STATE.historyBars = bars;
      STATE.historyBarsStatus = bars.length ? "ok" : "missing";
      renderDetail({ preserveScroll: true });
    }).catch(err => {
      if (STATE.selectedHistoryJobId !== id) return;
      STATE.historyBarsStatus = "error";
      STATE.historyError = err.message || String(err);
      renderDetail({ preserveScroll: true });
    });
  }

  function selectedResearchProfile(family) {
    if (!family) return null;
    return family.planning || family.primary || family.versions?.[0] || null;
  }

  function researchJobIdForProfile(profile, family) {
    const knownJobs = new Set((STATE.jobs || []).map(job => String(job?.job_id || "").trim()).filter(Boolean));
    for (const id of evidenceIds(profile)) {
      const key = String(id || "").trim();
      if (key && knownJobs.has(key)) return key;
    }
    const preferred = String(evidenceIds(profile)[0] || "").trim();
    if (preferred) return preferred;
    const fallback = backtestRowsForFamily(family)[0];
    return String(fallback?.job_id || "").trim();
  }

  function isCurrentResearchSelection(targetKey, jobId) {
    const family = selectedFamily();
    const profile = selectedResearchProfile(family);
    return !!family
      && family.key === targetKey
      && String(researchJobIdForProfile(profile, family) || "").trim() === String(jobId || "").trim();
  }

  function researchSnapshot(jobId) {
    const id = String(jobId || "").trim();
    if (!id) return { loaded: false, loading: false, job: null, trades: [], error: "" };
    if (STATE.researchJobId === id && STATE.researchJob) {
      return {
        loaded: true,
        loading: STATE.researchLoadingJobId === id,
        job: STATE.researchJob,
        trades: STATE.researchTrades || [],
        error: "",
      };
    }
    const cached = STATE.researchCache.get(id);
    if (cached) {
      return {
        loaded: true,
        loading: false,
        job: cached.job,
        trades: cached.trades || [],
        error: "",
      };
    }
    return {
      loaded: false,
      loading: STATE.researchLoadingJobId === id,
      job: null,
      trades: [],
      error: STATE.researchErrorJobId === id ? STATE.researchError : "",
    };
  }

  function ensureResearchReportLoaded(family, profile) {
    const targetKey = String(family?.key || "").trim();
    const id = String(researchJobIdForProfile(profile, family) || "").trim();
    if (!targetKey || !id) return;
    if (STATE.researchJobId === id && STATE.researchJob) return;
    const cached = STATE.researchCache.get(id);
    if (cached) {
      STATE.researchJobId = id;
      STATE.researchJob = cached.job;
      STATE.researchTrades = cached.trades || [];
      STATE.researchLoadingJobId = "";
      STATE.researchError = "";
      STATE.researchErrorJobId = "";
      return;
    }
    if (STATE.researchLoadingJobId === id) return;
    STATE.researchLoadingJobId = id;
    STATE.researchError = "";
    STATE.researchErrorJobId = "";
    Promise.all([
      api(`/api/jobs/${encodeURIComponent(id)}`),
      loadAllTradesForJob(id),
    ]).then(([job, trades]) => {
      if (!isCurrentResearchSelection(targetKey, id)) return;
      STATE.researchLoadingJobId = "";
      STATE.researchJobId = id;
      STATE.researchJob = job;
      STATE.researchTrades = trades;
      STATE.researchCache.set(id, { job, trades });
      renderTaskResearch();
    }).catch(err => {
      if (!isCurrentResearchSelection(targetKey, id)) return;
      STATE.researchLoadingJobId = "";
      STATE.researchError = err.message || String(err);
      STATE.researchErrorJobId = id;
      renderTaskResearch();
    });
  }

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value == null) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = String(value);
      else if (key === "title") node.title = String(value);
      else if (key === "dataset") {
        for (const [dk, dv] of Object.entries(value)) node.dataset[dk] = String(dv);
      } else if (key === "colSpan") node.colSpan = value;
      else node.setAttribute(key, String(value));
    }
    const list = Array.isArray(children) ? children : [children];
    for (const child of list) {
      if (child == null) continue;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  function setChip(text, cls) {
    const chip = $("strategies-data-chip");
    if (!chip) return;
    chip.textContent = text;
    chip.classList.remove("ok", "bad", "warn");
    if (cls) chip.classList.add(cls);
  }

  function setHealth(ok, text) {
    const pill = $("strategies-health-pill");
    if (!pill) return;
    pill.textContent = text;
    pill.classList.remove("ok", "bad");
    pill.classList.add(ok ? "ok" : "bad");
  }

  function rootOf(value) {
    const s = String(value || "").trim().toUpperCase();
    const m = s.match(/^([A-Z0-9]+)/);
    return m ? m[1] : "";
  }

  function tfShort(value) {
    const s = String(value || "").trim();
    const m = s.match(/^(\d+)\s*(Minute|Min|m|Hour|H|Day|D)/i);
    if (!m) return s || "tf";
    const unit = m[2].toLowerCase();
    if (unit.startsWith("hour") || unit === "h") return `${m[1]}h`;
    if (unit.startsWith("day") || unit === "d") return `${m[1]}d`;
    return `${m[1]}m`;
  }

  function fmtMoney(v) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    const sign = n >= 0 ? "+" : "-";
    return `${sign}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  }

  function fmtNum(v, digits = 1) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(digits) : "—";
  }

  function metric(profile, names) {
    const m = (profile && profile.metrics) || {};
    for (const name of names) {
      const raw = m[name];
      const n = Number(raw);
      if (Number.isFinite(n)) return n;
    }
    return null;
  }

  function profileRoot(profile) {
    return rootOf(profile && (profile.instrument || profile.current_contract || profile.root));
  }

  function profilePeriodDays(profile) {
    const p = (profile && (profile.test_period || profile.period)) || {};
    const from = Date.parse(p.from_utc || p.from || p.start_utc || "");
    const to = Date.parse(p.to_utc || p.to || p.end_utc || "");
    if (!Number.isFinite(from) || !Number.isFinite(to) || to <= from) return 0;
    return Math.max(1, (to - from) / 86400000);
  }

  function forecast30(profile) {
    if (!profile || profile.runtimeOnly) return { net: null, trades: null };
    const days = profilePeriodDays(profile);
    if (!days) return { net: null, trades: null };
    const net = metric(profile, [
      "net_profit_after_commission",
      "adj_net",
      "net_profit",
      "net",
    ]);
    const trades = metric(profile, ["trade_count", "trades", "total_trades"]);
    return {
      net: net == null ? null : (net / days) * 30,
      trades: trades == null ? null : (trades / days) * 30,
    };
  }

  function evidenceIds(profile) {
    const ids = [];
    if (profile && profile.last_job_id) ids.push(String(profile.last_job_id));
    for (const id of (profile && profile.evidence_job_ids) || []) {
      const s = String(id || "");
      if (s && !ids.includes(s)) ids.push(s);
    }
    return ids;
  }

  function runtimeRecord(row) {
    return (row && row.runtime) || row || {};
  }

  function runtimeClass(row) {
    const r = runtimeRecord(row);
    return String(r.strategy_class || row?.display_key || row?.strategy_id || r.strategy_name || "").trim();
  }

  function runtimeName(row) {
    const r = runtimeRecord(row);
    return String(r.strategy_name || "").trim();
  }

  function rootsInText(value) {
    const text = String(value || "").trim().toUpperCase();
    if (!text) return [];
    return knownRoots().filter(root => text.includes(root));
  }

  function runtimeRootCandidates(row) {
    const r = runtimeRecord(row);
    const seen = new Set();
    const roots = [];
    const add = (value) => {
      const root = String(value || "").trim().toUpperCase();
      if (!root || seen.has(root)) return;
      seen.add(root);
      roots.push(root);
    };
    [
      r.strategy_name,
      r.strategy_id,
      r.strategy_class,
      r.display_name,
      r.stable_id,
      row?.display_key,
    ].forEach(value => {
      rootsInText(value).forEach(add);
    });
    add(rootOf(r.instrument || ""));
    add(rootOf(r.contract_month || ""));
    return roots;
  }

  function runtimeRoot(row) {
    const r = runtimeRecord(row);
    const candidates = runtimeRootCandidates(row);
    return candidates[0] || rootOf(r.instrument || r.contract_month || "");
  }

  function runtimeId(row) {
    const r = runtimeRecord(row);
    return String(r.runtime_instance_id || row?.runtime_instance_id || runtimeClass(row)).trim();
  }

  function runtimeEnabled(row) {
    const r = runtimeRecord(row);
    return !!(row && (row.runtime_enabled || r.enabled));
  }

  function runtimePortfolioVisible(row) {
    const cls = runtimeClass(row);
    if (!cls) return false;
    if (row?.display_hidden || runtimeRecord(row)?.display_hidden) return false;
    const root = runtimeRoot(row);
    const key = cls.toLowerCase();
    const sid = String(row?.strategy_id || runtimeRecord(row)?.strategy_id || "").trim().toLowerCase();
    return STATE.profiles.some(profile => {
      if (!profileVisibleInMatrix(profile)) return false;
      const profileRootValue = profileRoot(profile);
      if (profileRootValue && root && profileRootValue !== root) return false;
      const idMatch = sid && String(profile?.runtime_strategy_id || "").trim().toLowerCase() === sid;
      const classMatch = profileClassCandidates(profile).some(candidate => candidate.toLowerCase() === key);
      return classMatch || idMatch;
    });
  }

  function portfolioRuntimeRows() {
    return (STATE.runtimeRows || []).filter(runtimePortfolioVisible);
  }

  function runtimeParamsOk(row) {
    const r = runtimeRecord(row);
    return !(row?.params_ok === false || r?.params_ok === false);
  }

  function catalogHasClass(name) {
    return STATE.catalogClasses.has(String(name || "").trim());
  }

  function catalogDisplay(name) {
    const key = String(name || "").trim();
    return STATE.catalogDisplayNames.get(key) || key;
  }

  function knownRoots() {
    const set = new Set();
    for (const row of STATE.instruments || []) {
      const root = String(row?.root || "").trim().toUpperCase();
      if (root) set.add(root);
    }
    for (const row of STATE.coverage?.instruments || []) {
      const root = String(row?.root || "").trim().toUpperCase();
      if (root) set.add(root);
    }
    return Array.from(set).sort((a, b) => b.length - a.length || a.localeCompare(b));
  }

  function catalogRootsForStrategy(strategy) {
    const text = [
      strategy?.display_name,
      strategy?.class_name,
    ].filter(Boolean).join(" ").toUpperCase();
    if (!text) return [];
    return knownRoots().filter(root => text.includes(root));
  }

  function inferTimeframeFromText(text) {
    const s = String(text || "").trim();
    const m = s.match(/\b(\d+)\s*([mhd])\b/i);
    if (!m) return "";
    const unit = m[2].toLowerCase();
    if (unit === "h") return `${m[1]} Hour`;
    if (unit === "d") return `${m[1]} Day`;
    return `${m[1]} Minute`;
  }

  function profileClassCandidates(profile) {
    const seen = new Set();
    const out = [];
    const add = (value) => {
      const s = String(value || "").trim();
      if (!s) return;
      const key = s.toLowerCase();
      if (seen.has(key)) return;
      seen.add(key);
      out.push(s);
    };
    add(profile?.deploy_strategy_class);
    for (const value of profile?.runtime_strategy_classes || []) add(value);
    add(profile?.strategy_class);
    if (profile?.runtimeRow) add(runtimeClass(profile.runtimeRow));
    return out;
  }

  function matchingRuntimeRows(profile) {
    if (!profile) return [];
    if (profile.runtimeOnly && profile.runtimeRow) return [profile.runtimeRow];
    const classes = new Set(profileClassCandidates(profile).map(x => x.toLowerCase()));
    const root = profileRoot(profile);
    const runtimeStrategyId = String(profile?.runtime_strategy_id || "").trim().toLowerCase();
    return portfolioRuntimeRows().filter(row => {
      const cls = runtimeClass(row).toLowerCase();
      const sid = String(row?.strategy_id || runtimeRecord(row).strategy_id || "").trim().toLowerCase();
      const rr = runtimeRoot(row);
      const classMatch = cls && classes.has(cls);
      const idMatch = runtimeStrategyId && sid === runtimeStrategyId;
      return (classMatch || idMatch) && (!root || !rr || rr === root);
    });
  }

  function resolveNtClass(profile) {
    if (!profile) return "";
    const rows = matchingRuntimeRows(profile);
    if (rows.length) return runtimeClass(rows[0]);
    for (const candidate of profileClassCandidates(profile)) {
      if (catalogHasClass(candidate)) return candidate;
    }
    return "";
  }

  function profileAvailableInNt(profile) {
    return !!resolveNtClass(profile);
  }

  function onlineStateForRows(rows) {
    if (!rows.length) return { state: "offline", rows: [] };
    if (rows.some(row => runtimeEnabled(row) && !runtimeParamsOk(row))) {
      return { state: "mismatch", rows };
    }
    if (rows.some(runtimeEnabled)) return { state: "active", rows };
    return { state: "inactive", rows };
  }

  function normalizeStatus(status) {
    switch (String(status || "").trim()) {
      case "ready":
      case "paper_ready":
        return "ready";
      case "runtime_online":
        return "runtime_online";
      default:
        return "in_progress";
    }
  }

  function statusVisualKey(status) {
    switch (String(status || "").trim()) {
      case "research_baseline":
        return "baseline";
      case "paper_candidate":
        return "candidate";
      case "rejected":
        return "rejected";
      case "archived":
        return "archived";
      case "runtime_online":
        return "runtime";
      case "ready":
      case "paper_ready":
        return "ready";
      default:
        return normalizeStatus(status) === "ready" ? "ready" : "in-progress";
    }
  }

  function isReadyStatus(status) {
    return normalizeStatus(status) === "ready";
  }

  function statusRank(status) {
    return STATUS_ORDER[normalizeStatus(status)] ?? 9;
  }

  function statusLabel(status) {
    const visual = statusVisualKey(status);
    return STATUS_LABEL[visual] || STATUS_LABEL[normalizeStatus(status)] || STATUS_LABEL.in_progress;
  }

  function statusClass(status) {
    return statusVisualKey(status);
  }

  function strategyKey(root, ntClass) {
    return `family:${String(root || "").toUpperCase()}:${String(ntClass || "").toLowerCase()}`;
  }

  function normalizeFamilyName(text, root) {
    let out = String(text || "").trim();
    if (!out) return "";
    out = out
      .replace(/\([^)]*\)/g, " ")
      .replace(/\bc\d{3}\b/gi, " ")
      .replace(/\bv\s*\d+\b/gi, " ")
      .replace(/\b\d+\s*(Minute|Min|m|Hour|h|Day|d)\b/gi, " ")
      .replace(/\b(paper_ready|paper_candidate|paper|locked|profile|research|baseline|current-source|stress|variant|rejected|archived|survivor|summary)\b/gi, " ")
      .replace(/[-_]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (root) {
      const re = new RegExp(`\\b${String(root).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "ig");
      out = out.replace(re, " ").replace(/\s+/g, " ").trim();
    }
    return out;
  }

  function familyBaseName(profile, ntClass) {
    const root = profileRoot(profile) || runtimeRoot(profile?.runtimeRow) || "";
    const candidates = [
      catalogDisplay(ntClass),
      runtimeName(profile?.runtimeRow),
      ntClass,
    ];
    for (const candidate of candidates) {
      const cleaned = normalizeFamilyName(candidate, root);
      if (cleaned) return cleaned;
    }
    return ntClass || "Strategy";
  }

  function versionLabel(profile, fallbackIndex) {
    const hay = [
      profile?.name,
      profile?.profile_id,
      profile?.stable_id,
      profile?.runtime_strategy_id,
      profile?.strategy_class,
      runtimeName(profile?.runtimeRow),
    ].filter(Boolean).join(" ");
    const m = hay.match(VERSION_TOKEN_RE);
    return m ? `v${m[1]}` : `v${fallbackIndex || 1}`;
  }

  function versionDisplayName(profile, family, fallbackIndex) {
    const direct = String(
      profile?.name ||
      profile?.expected_name ||
      runtimeName(profile?.runtimeRow) ||
      "",
    ).trim();
    if (direct) return direct;
    const base = familyDisplayName(family);
    const label = versionLabel(profile, fallbackIndex);
    return label ? `${base} ${label}`.trim() : base;
  }

  function familyDisplayName(family) {
    if (!family) return "Strategy";
    const direct = String(
      family.ntDisplay ||
      runtimeName(family.primary?.runtimeRow) ||
      family.baseName ||
      family.ntClass ||
      "",
    ).trim();
    return direct || "Strategy";
  }

  function familyProfileVersionCount(family) {
    return (family?.versions || []).filter(profile => !profile.runtimeOnly && !profile.catalogOnly).length;
  }

  function createRuntimeOnlyProfile(row, root) {
    const rec = runtimeRecord(row);
    return {
      runtimeOnly: true,
      runtimeRow: row,
      profile_id: runtimeId(row),
      name: runtimeName(row) || runtimeClass(row),
      strategy_class: runtimeClass(row),
      deploy_strategy_class: runtimeClass(row),
      instrument: rec.instrument || rec.contract_month || root,
      timeframe: rec.timeframe || `${rec.bars_period_value || ""} ${rec.bars_period_type || ""}`.trim(),
      status: "runtime_online",
      metrics: {},
    };
  }

  function createCatalogOnlyProfile(strategy, root) {
    const className = String(strategy?.class_name || "").trim();
    const display = String(strategy?.display_name || className).trim();
    return {
      catalogOnly: true,
      profile_id: `catalog:${className.toLowerCase()}`,
      name: display,
      strategy_class: className,
      deploy_strategy_class: className,
      instrument: root,
      timeframe: inferTimeframeFromText(display),
      status: "catalog_only",
      metrics: {},
    };
  }

  function sortProfiles(list) {
    return list.slice().sort((a, b) => {
      const ar = statusRank(a.status);
      const br = statusRank(b.status);
      if (ar !== br) return ar - br;
      return String(a.name || a.profile_id || "").localeCompare(String(b.name || b.profile_id || ""), "ru");
    });
  }

  function pickPrimaryVersion(versions) {
    const ranked = versions.slice().sort((a, b) => {
      const ar = statusRank(a.status);
      const br = statusRank(b.status);
      if (ar !== br) return ar - br;
      const ao = onlineStateForRows(matchingRuntimeRows(a)).state === "active" ? -1 : 0;
      const bo = onlineStateForRows(matchingRuntimeRows(b)).state === "active" ? -1 : 0;
      if (ao !== bo) return ao - bo;
      return String(a.name || a.profile_id || "").localeCompare(String(b.name || b.profile_id || ""), "ru");
    });
    return ranked[0] || null;
  }

  function familiesForRoot(root) {
    const r = String(root || "").toUpperCase();
    const map = new Map();
    const profiles = STATE.profiles.filter(p => profileRoot(p) === r && profileVisibleInMatrix(p));
    const approvedProfiles = profiles.filter(profile => isReadyStatus(profile.status));

    for (const profile of profiles) {
      const ntClass = resolveNtClass(profile);
      if (!ntClass) continue;
      const key = strategyKey(r, ntClass);
      if (!map.has(key)) {
        map.set(key, {
          key,
          root: r,
          ntClass,
          ntDisplay: catalogDisplay(ntClass),
          baseName: "",
          versions: [],
          runtimeRows: [],
          primary: null,
          planning: null,
          online: { state: "offline", rows: [] },
          bestStatus: "missing",
        });
      }
      map.get(key).versions.push(profile);
    }

    const usedRuntimeIds = new Set();
    for (const family of map.values()) {
      family.versions = sortProfiles(family.versions);
      family.runtimeRows = family.versions.flatMap(profile => matchingRuntimeRows(profile));
      for (const row of family.runtimeRows) usedRuntimeIds.add(runtimeId(row));
    }

    for (const row of portfolioRuntimeRows()) {
      if (runtimeRoot(row) !== r) continue;
      const ntClass = runtimeClass(row);
      if (!ntClass) continue;
      const key = strategyKey(r, ntClass);
      if (!map.has(key)) continue;
      const family = map.get(key);
      if (!family) continue;
      family.runtimeRows.push(row);
      if (!usedRuntimeIds.has(runtimeId(row))) usedRuntimeIds.add(runtimeId(row));
    }

    const families = Array.from(map.values()).map(family => {
      const dedupRuntime = new Map();
      for (const row of family.runtimeRows) dedupRuntime.set(runtimeId(row), row);
      family.runtimeRows = Array.from(dedupRuntime.values());
      family.versions = sortProfiles(family.versions);
      family.approvedVersions = family.versions.filter(profile => isReadyStatus(profile.status));
      family.approved = family.approvedVersions.length > 0;
      family.primary = pickPrimaryVersion(family.versions);
      family.planning = family.approvedVersions[0] || family.primary;
      family.online = onlineStateForRows(family.runtimeRows);
      family.bestStatus = family.primary ? family.primary.status : "missing";
      family.baseName = familyBaseName(family.primary, family.ntClass);
      family.explicitSlot = explicitSlotForFamily(family);
      family.slot = 0;
      family.slotLabel = "";
      family.cellId = "";
      return family;
    });

    const slotLayout = assignFamilySlots(r, families);

    const orphans = sortProfiles(profiles.filter(profile => !profileAvailableInNt(profile)));
    const approvedFamilies = slotLayout.families.filter(family => family.approved);
    const approvedOrphans = sortProfiles(approvedProfiles.filter(profile => !profileAvailableInNt(profile)));
    return {
      families: slotLayout.families,
      approvedFamilies,
      slots: slotLayout.slots,
      orphans,
      approvedOrphans,
    };
  }

  function bestStatusForRoot(root) {
    const { families, orphans } = familiesForRoot(root);
    const statuses = [];
    families.forEach(family => {
      if (family.online.state === "active") statuses.push("runtime_online");
      if (family.bestStatus) statuses.push(family.bestStatus);
    });
    orphans.forEach(profile => { if (profile.status) statuses.push(profile.status); });
    statuses.sort((a, b) => statusRank(a) - statusRank(b));
    return statuses[0] || "missing";
  }

  function goalForRoot(root) {
    const { families } = familiesForRoot(root);
    const readyFamilies = families
      .map(family => family.planning)
      .filter(profile => profile && isReadyStatus(profile.status));
    const totals = readyFamilies.reduce((acc, profile) => {
      const f = forecast30(profile);
      acc.net += Number.isFinite(f.net) ? f.net : 0;
      acc.trades += Number.isFinite(f.trades) ? f.trades : 0;
      return acc;
    }, { net: 0, trades: 0 });
    return {
      ready: readyFamilies.length,
      net: totals.net,
      trades: totals.trades,
      ok: readyFamilies.length > 0 &&
        totals.net >= TARGET_MONTHLY_PROFIT &&
        totals.trades >= TARGET_TRADES_30D,
    };
  }

  function selectedFamily() {
    const { families } = familiesForRoot(STATE.selectedRoot);
    if (!families.length) {
      STATE.selectedKey = "";
      return null;
    }
    const selected = families.find(family => family.key === STATE.selectedKey);
    if (selected) return selected;
    STATE.selectedKey = families[0].key;
    return families[0];
  }

  function requestSelectedStrategyReveal() {
    STATE.revealSelectionAfterRender = true;
  }

  function revealSelectedStrategyIfNeeded() {
    if (!STATE.revealSelectionAfterRender) return;
    STATE.revealSelectionAfterRender = false;
    requestAnimationFrame(() => {
      const activeInstrument = document.querySelector(".strategies-instrument-item.active");
      if (activeInstrument && activeInstrument.scrollIntoView) {
        activeInstrument.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
      const selectedCell = document.querySelector(".strategies-matrix-table .strategy-cell.selected");
      if (selectedCell && selectedCell.scrollIntoView) {
        selectedCell.scrollIntoView({ block: "nearest", inline: "center" });
      }
    });
  }

  function buildInstruments() {
    const rows = Array.isArray(STATE.coverage?.instruments) ? STATE.coverage.instruments : [];
    const byRoot = new Map();
    rows.forEach(row => {
      const root = String(row.root || "").toUpperCase();
      if (!root) return;
      byRoot.set(root, Object.assign({ root }, row));
    });
    STATE.profiles.forEach(profile => {
      const root = profileRoot(profile);
      if (root && !byRoot.has(root)) {
        byRoot.set(root, { root, best_status: normalizeStatus(profile.status), group: "profiles" });
      }
    });
    for (const row of byRoot.values()) {
      row.best_status = bestStatusForRoot(row.root);
    }
    STATE.instruments = Array.from(byRoot.values()).sort((a, b) => {
      const ai = portfolioRootIndex(a.root);
      const bi = portfolioRootIndex(b.root);
      if (ai !== bi) {
        if (ai < 0) return 1;
        if (bi < 0) return -1;
        return ai - bi;
      }
      return String(a.root).localeCompare(String(b.root));
    });
    if (!STATE.selectedRoot && STATE.instruments.length) {
      const preferred = STATE.instruments.find(x => x.root === "MNQ") || STATE.instruments[0];
      STATE.selectedRoot = preferred.root;
    }
  }

  async function loadPagedJobs() {
    const jobs = [];
    let offset = 0;
    let total = Infinity;
    for (let page = 0; page < 8 && offset < total; page += 1) {
      const data = await api(`/api/jobs?offset=${offset}&limit=${PAGE_LIMIT}`);
      const rows = Array.isArray(data.jobs) ? data.jobs : [];
      jobs.push(...rows);
      total = Number.isFinite(Number(data.total)) ? Number(data.total) : jobs.length;
      offset += rows.length;
      if (!rows.length) break;
    }
    return jobs;
  }

  async function refreshHealth() {
    try {
      const h = await api("/api/health");
      setHealth(!!h.ok, h.ok ? "backend ok" : "backend error");
    } catch {
      setHealth(false, "backend недоступен");
    }
  }

  function applyCatalog(doc) {
    STATE.catalog = doc || null;
    STATE.catalogClasses = new Set();
    STATE.catalogDisplayNames = new Map();
    for (const strategy of (doc?.strategies || [])) {
      const cls = String(strategy?.class_name || "").trim();
      if (!cls) continue;
      STATE.catalogClasses.add(cls);
      STATE.catalogDisplayNames.set(cls, String(strategy?.display_name || cls));
    }
  }

  async function loadAll() {
    const token = STATE.loadToken + 1;
    STATE.loadToken = token;
    STATE.errors = [];
    setChip("Загрузка данных...", "warn");
    await refreshHealth();

    const [coverageRes, catalogRes, profilesRes, runtimeRes] = await Promise.allSettled([
      api("/api/coverage"),
      api("/api/catalog"),
      api("/api/profiles"),
      api("/api/ops/runtime/strategies"),
    ]);
    if (token !== STATE.loadToken) return;

    if (coverageRes.status === "fulfilled") STATE.coverage = coverageRes.value;
    else STATE.errors.push(`coverage: ${coverageRes.reason.message}`);

    if (catalogRes.status === "fulfilled") applyCatalog(catalogRes.value);
    else {
      applyCatalog(null);
      STATE.errors.push(`catalog: ${catalogRes.reason.message}`);
    }

    if (profilesRes.status === "fulfilled") {
      STATE.profiles = Array.isArray(profilesRes.value?.profiles) ? profilesRes.value.profiles : [];
    } else {
      STATE.profiles = [];
      STATE.errors.push(`profiles: ${profilesRes.reason.message}`);
    }

    if (runtimeRes.status === "fulfilled") {
      STATE.runtimeRows = Array.isArray(runtimeRes.value?.strategies) ? runtimeRes.value.strategies : [];
    } else {
      STATE.runtimeRows = [];
    }

    STATE.jobs = [];
    buildInstruments();
    const familyCount = STATE.instruments.reduce((acc, row) => {
      const { approvedFamilies } = familiesForRoot(row.root);
      return acc + approvedFamilies.length;
    }, 0);
    render();

    const baseMsg = () => `${STATE.catalogClasses.size} NT-классов · ${familyCount} стратегий по инструментам · ${STATE.profiles.length} версий`;
    setChip(
      STATE.errors.length ? `${baseMsg()} · есть ошибки источников` : `${baseMsg()} · отчеты загружаются`,
      "warn",
    );

    loadPagedJobs()
      .then(jobs => {
        if (token !== STATE.loadToken) return;
        STATE.jobs = jobs;
        renderTaskResearch();
        renderDetail({ preserveScroll: true });
        setChip(
          STATE.errors.length ? `${baseMsg()} · отчеты: ${jobs.length} · есть ошибки источников` : `${baseMsg()} · отчеты: ${jobs.length}`,
          STATE.errors.length ? "warn" : "ok",
        );
      })
      .catch(err => {
        if (token !== STATE.loadToken) return;
        STATE.errors.push(`jobs: ${err.message}`);
        setChip(`${baseMsg()} · история отчетов недоступна`, "warn");
      });
  }

  function visibleInstruments() {
    const q = STATE.search.trim().toLowerCase();
    return STATE.instruments.filter(row => {
      if (STATE.statusFilter !== "all" && normalizeStatus(row.best_status) !== STATE.statusFilter) return false;
      if (!q) return true;
      const hay = [row.root, row.group, row.profile_name, row.instrument].filter(Boolean).join(" ").toLowerCase();
      return hay.includes(q);
    });
  }

  function renderStats() {
    const total = STATE.instruments.length;
    const slotsFilled = STATE.instruments.reduce((acc, row) => {
      const { approvedFamilies } = familiesForRoot(row.root);
      return acc + Math.min(TARGET_SLOTS, approvedFamilies.length);
    }, 0);
    const monthlyTarget = total * TARGET_MONTHLY_PROFIT;
    const monthlyFact = STATE.instruments.reduce((acc, row) => acc + goalForRoot(row.root).net, 0);
    const tradesTarget = total * TARGET_TRADES_30D;
    const tradesFact = STATE.instruments.reduce((acc, row) => acc + goalForRoot(row.root).trades, 0);
    const online = portfolioRuntimeRows().filter(runtimeEnabled).length;
    $("stat-instruments").textContent = String(total);
    $("stat-slots").textContent = `${slotsFilled}/${total * TARGET_SLOTS}`;
    $("stat-monthly-detail").replaceChildren(
      progressBar("Прибыль 30д", monthlyFact, monthlyTarget, true),
      progressBar("Сделки 30д", tradesFact, tradesTarget, false),
    );
    $("stat-online").textContent = String(online);
  }

  function renderInstrumentList() {
    const box = $("strategies-instrument-list");
    const count = $("strategies-instrument-count");
    const rows = visibleInstruments();
    if (count) count.textContent = `${rows.length}/${STATE.instruments.length}`;
    box.replaceChildren();
    if (!rows.length) {
      box.appendChild(el("div", { class: "strategies-empty-state", text: "Нет инструментов под фильтр." }));
      return;
    }
    rows.forEach(row => {
      const root = row.root;
      const families = familiesForRoot(root).families;
      const goal = goalForRoot(root);
      const active = root === STATE.selectedRoot;
      const btn = el("button", {
        type: "button",
        class: `strategies-instrument-item ${active ? "active" : ""}`,
        dataset: { root },
      });
      btn.addEventListener("click", () => {
        STATE.selectedRoot = root;
        const first = familiesForRoot(root).families[0];
        STATE.selectedKey = first ? first.key : "";
        requestSelectedStrategyReveal();
        render();
      });
      btn.appendChild(el("div", { class: "strategies-instrument-main" }, [
        el("strong", { text: root }),
        el("span", { text: row.group || row.instrument || "—" }),
      ]));
      btn.appendChild(el("div", { class: "strategies-instrument-side" }, [
        el("span", { class: "strategies-mini-count", text: `${Math.min(families.length, TARGET_SLOTS)}/${TARGET_SLOTS}` }),
        el("span", {
          class: `strategies-status-pill ${statusClass(goal.ok ? "ready" : row.best_status)}`,
          text: goal.ok ? "цель ok" : statusLabel(row.best_status),
        }),
      ]));
      box.appendChild(btn);
    });
  }

  function renderMatrix() {
    const head = $("strategies-matrix-head");
    const body = $("strategies-matrix-body");
    selectedFamily();
    head.replaceChildren();
    body.replaceChildren();

    const htr = el("tr");
    htr.appendChild(el("th", { text: "Инструмент" }));
    for (let i = 1; i <= TARGET_SLOTS; i += 1) {
      htr.appendChild(el("th", { text: `Стратегия ${i}` }));
    }
    head.appendChild(htr);

    const rows = visibleInstruments();
    if (!rows.length) {
      const tr = el("tr");
      tr.appendChild(el("td", { colSpan: TARGET_SLOTS + 1, class: "strategies-empty-cell", text: "Нет данных для матрицы." }));
      body.appendChild(tr);
      return;
    }

    rows.forEach(row => {
      const root = row.root;
      const { families, slots } = familiesForRoot(root);
      const goal = goalForRoot(root);
      const tr = el("tr", { class: root === STATE.selectedRoot ? "selected" : "" });
      const rootCell = el("td", { class: "strategies-matrix-root" });
      const rootBtn = el("button", { type: "button", text: root });
      rootBtn.addEventListener("click", () => {
        STATE.selectedRoot = root;
        STATE.selectedKey = families[0] ? families[0].key : "";
        requestSelectedStrategyReveal();
        render();
      });
      rootCell.appendChild(rootBtn);
      rootCell.appendChild(el("span", {
        class: goal.ok ? "goal-ok" : "goal-warn",
        text: `${fmtMoney(goal.net)} / ${fmtNum(goal.trades, 0)}сд`,
        title: `Прогноз ready-портфеля за 30 дней: ${fmtMoney(goal.net)}, ${fmtNum(goal.trades, 1)} сделок.`,
      }));
      tr.appendChild(rootCell);

      for (let i = 0; i < TARGET_SLOTS; i += 1) {
        const slotNo = i + 1;
        const cellId = portfolioCellId(root, slotNo);
        const family = slots[i];
        const td = el("td");
        if (!family) {
          td.appendChild(el("button", {
            type: "button",
            class: "strategy-cell empty",
            title: `${cellId}\nИнструмент: ${root}\nСтратегия ${slotNo}\nСвободный слот`,
          }, [
            el("span", { class: "strategy-cell-id", text: cellId }),
            el("strong", { text: "пусто" }),
          ]));
        } else {
          const primary = family.primary;
          const familyName = familyDisplayName(family);
          const profileName = versionDisplayName(primary, family, family.slot || slotNo);
          const versionCount = familyProfileVersionCount(family);
          const cls = family.online.state === "active" ? "active"
            : family.online.state === "mismatch" ? "mismatch"
            : statusClass(primary?.status || family.bestStatus);
          const cell = el("button", {
            type: "button",
            class: `strategy-cell ${cls} ${family.key === STATE.selectedKey ? "selected" : ""}`,
            title: `${cellId}\nИнструмент: ${root}\n${family.slotLabel || `Стратегия ${slotNo}`}\nNinjaTrader: ${familyName}\nКласс: ${family.ntClass}\nВерсия: ${profileName}`,
          }, [
            el("span", { class: "strategy-cell-id", text: cellId }),
            el("strong", { text: profileName }),
            el("span", {
              text: family.online.state === "active"
                ? `online${versionCount > 1 ? ` · версий ${versionCount}` : ""}`
                : `${statusLabel(family.bestStatus)}${!family.approved ? " · слот свободен" : ""}${versionCount > 1 ? ` · версий ${versionCount}` : ""}`,
            }),
          ]);
          cell.addEventListener("click", () => {
            STATE.selectedRoot = root;
            STATE.selectedKey = family.key;
            requestSelectedStrategyReveal();
            renderTaskResearch();
            renderDetail();
            renderMatrix();
          });
          td.appendChild(cell);
        }
        tr.appendChild(td);
      }
      body.appendChild(tr);
    });
    revealSelectedStrategyIfNeeded();
  }

  function progressBar(label, value, target, money) {
    const safe = Number.isFinite(value) ? value : 0;
    const pct = target > 0 ? Math.max(0, Math.min(100, (safe / target) * 100)) : 0;
    const wrap = el("div", { class: "strategies-progress-row" });
    wrap.appendChild(el("div", { class: "strategies-progress-label" }, [
      el("span", { text: label }),
      el("strong", { text: money ? `${fmtMoney(safe)} / ${fmtMoney(target)}` : `${fmtNum(safe, 1)} / ${target}` }),
    ]));
    const bar = el("div", { class: "strategies-progress" });
    bar.appendChild(el("span", { style: `width:${pct.toFixed(0)}%` }));
    wrap.appendChild(bar);
    return wrap;
  }

  function jobMatchesProfile(job, profile) {
    if (!job || !profile) return false;
    const jr = rootOf(job.instrument || job.label || "");
    const pr = profileRoot(profile);
    if (jr && pr && jr !== pr) return false;
    const cls = String(job.class_name || job.strategy || "").trim().toLowerCase();
    if (!cls) return false;
    const ntClass = resolveNtClass(profile);
    if (ntClass && cls === ntClass.toLowerCase()) return true;
    return profileClassCandidates(profile).some(candidate => candidate.toLowerCase() === cls);
  }

  function jobMatchesFamily(job, family) {
    if (!job || !family) return false;
    const jr = rootOf(job.instrument || job.label || "");
    if (jr && family.root && jr !== family.root) return false;
    const cls = String(job.class_name || job.strategy || "").trim().toLowerCase();
    if (!cls) return false;
    const classes = new Set([family.ntClass]
      .concat(family.versions.flatMap(profileClassCandidates))
      .filter(Boolean)
      .map(value => String(value).toLowerCase()));
    return classes.has(cls);
  }

  function jobTimestamp(job) {
    return Date.parse(job?.finished_at_utc || job?.created_at_utc || "") || 0;
  }

  function fmtDate(value) {
    const t = Date.parse(value || "");
    if (!Number.isFinite(t)) return "—";
    return new Date(t).toLocaleString("ru-RU", {
      year: "2-digit",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function fmtPct(v) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    return Number.isFinite(n) ? `${n.toFixed(1)}%` : "—";
  }

  function fmtTimeframe(value) {
    if (value == null || value === "") return "—";
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (typeof value !== "object") return String(value);
    const direct = value.label || value.name || value.timeframe || value.display;
    if (direct) return String(direct);
    const n = value.value ?? value.bars_period_value ?? value.period_value ?? value.minutes;
    const unit = value.type || value.bars_period_type || value.period_type || value.unit;
    if (n != null && unit) return `${n} ${unit}`;
    const json = JSON.stringify(value);
    return json && json !== "{}" ? json.slice(0, 32) : "—";
  }

  function jobStatusLabel(status) {
    switch (String(status || "")) {
      case "done": return "готово";
      case "failed": return "ошибка";
      case "running": return "в работе";
      case "pending": return "очередь";
      case "cancelled": return "отмена";
      default: return status || "—";
    }
  }

  function backtestRowsForFamily(family) {
    if (!family) return [];
    const byId = new Map();
    for (const job of STATE.jobs || []) {
      if (!jobMatchesFamily(job, family)) continue;
      byId.set(String(job.job_id || `${job.class_name}:${jobTimestamp(job)}`), job);
    }
    return Array.from(byId.values()).sort((a, b) => jobTimestamp(b) - jobTimestamp(a));
  }

  function selectHistoryJob(jobId) {
    const id = String(jobId || "").trim();
    if (!id) return;
    STATE.selectedHistoryJobId = id;
    STATE.historyViewerTab = "summary";
    ensureHistoryReportLoaded(id);
    renderDetail({ preserveScroll: true });
  }

  function switchHistoryTab(tabName) {
    STATE.historyViewerTab = tabName || "summary";
    if (STATE.historyViewerTab === "chart") ensureHistoryBarsLoaded(STATE.selectedHistoryJobId);
    renderDetail({ preserveScroll: true });
  }

  function profileIdentity(profile) {
    return String(profile?.profile_id || profile?.id || "").trim();
  }

  function resetHistorySelection() {
    STATE.selectedHistoryJobId = "";
    STATE.historyViewerTab = "summary";
    STATE.historyLoadingJobId = "";
    STATE.historyJobId = "";
    STATE.historyJob = null;
    STATE.historyTrades = [];
    STATE.historyBarsJobId = "";
    STATE.historyBars = [];
    STATE.historyBarsStatus = "idle";
    STATE.historyError = "";
  }

  async function updateProfile(profile, updates, action) {
    const id = profileIdentity(profile);
    if (!id) return;
    setChip("Сохраняю решение по профилю...", "warn");
    await apiPost(`/api/ops/profiles/${encodeURIComponent(id)}/update`, { updates, action });
    resetHistorySelection();
    await loadAll();
  }

  async function deleteProfile(profile) {
    const id = profileIdentity(profile);
    if (!id) return;
    const ok = window.confirm(`Удалить профиль из реестра?\n\n${profile.name || id}`);
    if (!ok) return;
    setChip("Удаляю профиль...", "warn");
    await apiPost(`/api/ops/profiles/${encodeURIComponent(id)}/delete`, { action: "delete" });
    resetHistorySelection();
    await loadAll();
  }

  async function renameProfile(profile, family) {
    const id = profileIdentity(profile);
    if (!id) return;
    const fallbackIndex = family?.slot || portfolioSlotNumber(profile?.slot) || 1;
    const expected = String(profile?.expected_name || "").trim();
    const current = String(profile.name || expected || versionDisplayName(profile, family, fallbackIndex) || id);
    const promptText = [
      "Новое display-имя версии",
      "",
      "Шаблон: <Family> <InstrumentRoot> <TimeframeShort> vN cNNN",
      `Одобренные семейства: ${APPROVED_PROFILE_FAMILY_PREFIXES.join(", ")}`,
      expected ? `Ожидаемое имя для этой версии: ${expected}` : "",
    ].filter(Boolean).join("\n");
    const next = window.prompt(promptText, expected || current);
    if (next == null) return;
    const name = String(next).trim();
    if (!name || name === current) return;
    if (!PROFILE_DISPLAY_NAME_RE.test(name)) {
      window.alert("Имя должно быть в формате '<Family> <InstrumentRoot> <TimeframeShort> vN cNNN'. Пример: 'Scalping MNQ 5m v1 c011'.");
      return;
    }
    if (expected && name !== expected) {
      window.alert(`Для этой версии зафиксировано имя по шаблону:\n${expected}`);
      return;
    }
    await updateProfile(profile, { name }, "rename");
  }

  async function hideStrategyClass(className) {
    const cls = String(className || "").trim();
    if (!cls) return;
    const ok = window.confirm(`Скрыть класс из портфельной матрицы?\n\n${cls}`);
    if (!ok) return;
    setChip("Скрываю класс из матрицы...", "warn");
    await apiPost("/api/ops/runtime/strategy-display", { class_name: cls, hidden: true });
    resetHistorySelection();
    await loadAll();
  }

  function actionButton(label, cls, onClick) {
    const btn = el("button", { type: "button", class: `strategies-action-btn ${cls || ""}`, text: label });
    btn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      Promise.resolve(onClick()).catch(err => setChip(`Ошибка: ${err.message || err}`, "bad"));
    });
    return btn;
  }

  function resolveBacktestStrategyClass(profile, family) {
    return resolveNtClass(profile)
      || String(family?.ntClass || "").trim()
      || String(profile?.deploy_strategy_class || "").trim()
      || String(profile?.strategy_class || "").trim();
  }

  function resolveBacktestInstrument(profile, family) {
    const direct = String(profile?.instrument || "").trim();
    if (direct && direct.includes(" ")) return direct;
    const root = profileRoot(profile) || String(family?.root || direct || "").trim().toUpperCase();
    if (!root) return direct;
    const rows = (STATE.catalog?.instruments || [])
      .filter(row => rootOf(row?.instrument) === root && row?.has_minute_data)
      .sort((a, b) => String(b?.data_last || "").localeCompare(String(a?.data_last || "")));
    return String(rows[0]?.instrument || direct || root).trim();
  }

  function openProfileBacktest(profile, family) {
    const cls = resolveBacktestStrategyClass(profile, family);
    if (!cls) {
      window.alert("Не найден класс NinjaTrader для этой стратегии.");
      return;
    }
    const qp = new URLSearchParams();
    qp.set("strategy", cls);
    const instrument = resolveBacktestInstrument(profile, family);
    if (instrument) qp.set("instrument", instrument);
    const timeframe = String(profile?.timeframe || family?.primary?.timeframe || "").trim();
    if (timeframe) qp.set("timeframe", timeframe);
    const params = profile?.locked_parameters || profile?.parameters || {};
    if (params && Object.keys(params).length) qp.set("params", JSON.stringify(params));
    qp.set("period", "1d");
    window.location.href = `/ui/index.html?${qp.toString()}`;
  }

  function renderProfileActions(profile, family) {
    const bar = el("div", { class: "strategies-action-row" });
    if (profile?.catalogOnly) {
      bar.appendChild(actionButton("Проверить", "backtest", () => openProfileBacktest(profile, family)));
      bar.appendChild(actionButton("Скрыть", "danger", () => hideStrategyClass(family?.ntClass || profile.strategy_class)));
      return bar;
    }
    if (profile?.runtimeOnly || !profileIdentity(profile)) {
      bar.appendChild(actionButton("Проверить", "backtest", () => openProfileBacktest(profile, family)));
      if (profile?.runtimeOnly) {
        bar.appendChild(el("span", { class: "strategies-action-muted", text: "runtime only" }));
      }
      return bar;
    }
    bar.appendChild(actionButton("Проверить", "backtest", () => openProfileBacktest(profile, family)));
    bar.appendChild(actionButton("В процессе", "in-progress", () => updateProfile(profile, { status: "paper_candidate" }, "mark_in_progress")));
    bar.appendChild(actionButton("Готова", "ready", () => updateProfile(profile, { status: "paper_ready" }, "promote_ready")));
    bar.appendChild(actionButton("Переим.", "", () => renameProfile(profile, family)));
    bar.appendChild(actionButton("Удалить", "danger", () => deleteProfile(profile)));
    return bar;
  }

  function fullJobContext(job) {
    const rawJob = job?.job || {};
    const result = job?.result || job?.result_partial || {};
    const ctx = result.context || {};
    const strategy = ctx.strategy || rawJob.strategy || job?.strategy || {};
    const instrument = ctx.instrument || rawJob.instrument || job?.instrument;
    const timeframe = ctx.timeframe || rawJob.timeframe || job?.timeframe;
    const period = ctx.period || rawJob.period || job?.period || {};
    const execution = ctx.execution || rawJob.execution || job?.execution || {};
    const params = strategy.final_parameters || strategy.parameters || rawJob.strategy?.parameters || job?.strategy?.parameters || {};
    return { rawJob, result, ctx, strategy, instrument, timeframe, period, execution, params };
  }

  function displayInstrument(value) {
    if (!value) return "—";
    if (typeof value === "string") return value;
    return value.full_name || value.name || value.symbol || value.id || "—";
  }

  function fmtDateRu(value) {
    const text = String(value || "").trim();
    if (!text) return "—";
    const ms = Date.parse(text);
    if (!Number.isFinite(ms)) {
      const isoDate = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
      if (isoDate) return `${isoDate[3]}.${isoDate[2]}.${isoDate[1]}`;
      return text;
    }
    const parts = RU_DATE_FORMATTER.formatToParts(new Date(ms));
    const day = parts.find(part => part.type === "day")?.value || "";
    const month = parts.find(part => part.type === "month")?.value || "";
    const year = parts.find(part => part.type === "year")?.value || "";
    return [day, month, year].filter(Boolean).join(" ") || text;
  }

  function fmtPeriod(value) {
    if (!value || typeof value !== "object") return "—";
    const from = fmtDateRu(value.from_utc || value.from || value.start_utc || value.start);
    const to = fmtDateRu(value.to_utc || value.to || value.end_utc || value.end);
    if (from === "—" && to === "—") return "—";
    if (from === "—") return to;
    if (to === "—") return from;
    return `${from} - ${to}`;
  }

  function fmtMoney2(v) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    const sign = n >= 0 ? "+" : "-";
    return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function fmtPx(v) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    return Number.isFinite(n) ? n.toLocaleString("en-US", { maximumFractionDigits: 4 }) : String(v);
  }

  function metricValue(metrics, names) {
    for (const name of names) {
      const n = Number(metrics?.[name]);
      if (Number.isFinite(n)) return n;
    }
    return null;
  }

  function statsFromTrades(rows) {
    let grossProfit = 0;
    let grossLoss = 0;
    let wins = 0;
    let best = null;
    let worst = null;
    let cumulative = 0;
    let peak = 0;
    let maxDrawdown = 0;
    for (const trade of rows || []) {
      const pnl = Number(trade.pnl_currency || 0);
      if (pnl > 0) { grossProfit += pnl; wins += 1; }
      else grossLoss += pnl;
      best = best == null ? pnl : Math.max(best, pnl);
      worst = worst == null ? pnl : Math.min(worst, pnl);
      cumulative += pnl;
      peak = Math.max(peak, cumulative);
      maxDrawdown = Math.min(maxDrawdown, cumulative - peak);
    }
    const count = rows?.length || 0;
    const net = grossProfit + grossLoss;
    return {
      count,
      net,
      grossProfit,
      grossLoss,
      profitFactor: grossLoss ? grossProfit / Math.abs(grossLoss) : (grossProfit > 0 ? Infinity : null),
      winPct: count ? (wins / count) * 100 : null,
      wins,
      losses: count - wins,
      avg: count ? net / count : null,
      best,
      worst,
      maxDrawdown: count ? maxDrawdown : null,
    };
  }

  function researchPeriod(profile, job) {
    const sources = [];
    if (job) sources.push(fullJobContext(job).period);
    if (profile?.test_period) sources.push(profile.test_period);
    if (profile?.period) sources.push(profile.period);
    for (const source of sources) {
      if (!source || typeof source !== "object") continue;
      const fromText = String(source.from_utc || source.from || source.start_utc || source.start || "").trim();
      const toText = String(source.to_utc || source.to || source.end_utc || source.end || "").trim();
      const from = Date.parse(fromText);
      const to = Date.parse(toText);
      if (Number.isFinite(from) && Number.isFinite(to) && to > from) {
        return {
          from_utc: fromText,
          to_utc: toText,
          days: Math.max(1, (to - from) / 86400000),
          label: fmtPeriod({ from_utc: fromText, to_utc: toText }),
        };
      }
      if (fromText || toText) {
        return {
          from_utc: fromText,
          to_utc: toText,
          days: 0,
          label: fmtPeriod({ from_utc: fromText, to_utc: toText }),
        };
      }
    }
    const fallbackDays = profilePeriodDays(profile);
    return { from_utc: "", to_utc: "", days: fallbackDays, label: "—" };
  }

  function researchPeriodLengthLabel(days) {
    const value = Number(days || 0);
    if (!Number.isFinite(value) || value <= 0) return "—";
    if (value >= 365 * 2.5) return "3 года";
    if (value >= 365 * 1.5) return "2 года";
    if (value >= 365 * 0.75) return "1 год";
    if (value >= 30 * 1.5) return `${Math.round(value / 30)} мес.`;
    if (value >= 7) return `${Math.round(value / 7)} нед.`;
    return `${Math.max(1, Math.round(value))} дн.`;
  }

  function fmtTradeRate(v) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    const digits = Math.abs(n) >= 10 ? 1 : 2;
    return `${n.toFixed(digits)} сделок`;
  }

  function researchSummary(profile, job, trades) {
    const tradeStats = statsFromTrades(trades || []);
    const metrics = Object.assign(
      {},
      job?.metrics || {},
      job?.result_partial?.metrics || {},
      job?.result?.metrics || {},
      profile?.metrics || {},
    );
    const period = researchPeriod(profile, job);
    const count = metricValue(metrics, ["trade_count_adjusted", "trade_count", "trades", "total_trades"]) ?? tradeStats.count;
    const net = metricValue(metrics, ["net_profit_after_commission", "adj_net", "net_profit", "net"]) ?? tradeStats.net;
    const winPct = metricValue(metrics, ["winning_pct", "win_pct_after_commission"]) ?? tradeStats.winPct;
    const profitFactor = metricValue(metrics, ["profit_factor_after_commission", "profit_factor"]) ?? tradeStats.profitFactor;
    const maxDrawdown = metricValue(metrics, ["max_drawdown_after_commission", "max_drawdown"]) ?? tradeStats.maxDrawdown;
    const avgTrade = Number.isFinite(Number(net)) && Number.isFinite(Number(count)) && Number(count) > 0
      ? Number(net) / Number(count)
      : tradeStats.avg;
    const days = Number(period.days || 0);
    const averageNet = (multiplier) => (Number.isFinite(Number(net)) && days > 0 ? (Number(net) / days) * multiplier : null);
    const averageTrades = (multiplier) => (Number.isFinite(Number(count)) && days > 0 ? (Number(count) / days) * multiplier : null);
    return {
      count,
      net,
      winPct,
      profitFactor,
      maxDrawdown,
      avgTrade,
      period,
      periodLengthLabel: researchPeriodLengthLabel(days),
      averages: {
        week: averageNet(7),
        month: averageNet(30),
        quarter: averageNet(91),
        year: averageNet(365),
      },
      tradeRates: {
        week: averageTrades(7),
        month: averageTrades(30),
        quarter: averageTrades(91),
        year: averageTrades(365),
      },
    };
  }

  function renderPerfTable(metrics, trades) {
    const table = el("table", { class: "perf-matrix" });
    table.appendChild(el("thead", {}, el("tr", {}, [
      el("th", { text: "" }),
      el("th", { text: "Все сделки" }),
      el("th", { text: "Long" }),
      el("th", { text: "Short" }),
    ])));
    const tbody = el("tbody");
    table.appendChild(tbody);
    const all = statsFromTrades(trades);
    const long = statsFromTrades((trades || []).filter(t => t.direction === "long"));
    const short = statsFromTrades((trades || []).filter(t => t.direction === "short"));
    const allOfficial = Object.assign({}, all, {
      count: metricValue(metrics, ["trade_count", "trade_count_adjusted"]) ?? all.count,
      net: metricValue(metrics, ["net_profit_after_commission", "net_profit", "adj_net"]) ?? all.net,
      grossProfit: metricValue(metrics, ["gross_profit"]) ?? all.grossProfit,
      grossLoss: metricValue(metrics, ["gross_loss"]) ?? all.grossLoss,
      profitFactor: metricValue(metrics, ["profit_factor_after_commission", "profit_factor"]) ?? all.profitFactor,
      winPct: metricValue(metrics, ["winning_pct", "win_pct_after_commission"]) ?? all.winPct,
      maxDrawdown: metricValue(metrics, ["max_drawdown_after_commission", "max_drawdown"]) ?? all.maxDrawdown,
    });
    const add = (label, getter, formatter, divider) => {
      const tr = el("tr", { class: divider ? "divider" : "" });
      tr.appendChild(el("th", { text: label }));
      [allOfficial, long, short].forEach(stats => {
        const value = getter(stats);
        const cls = typeof value === "number" && value !== 0 ? (value > 0 ? "pos" : "neg") : "";
        tr.appendChild(el("td", { class: cls, text: formatter(value) }));
      });
      tbody.appendChild(tr);
    };
    add("Net Profit", s => s.net, fmtMoney2);
    add("Gross Profit", s => s.grossProfit, fmtMoney2);
    add("Gross Loss", s => s.grossLoss, fmtMoney2);
    add("Profit Factor", s => s.profitFactor, v => Number.isFinite(v) ? Number(v).toFixed(3) : "—");
    add("Макс. просадка", s => s.maxDrawdown, fmtMoney2);
    add("Всего сделок", s => s.count, v => v == null ? "—" : String(v), true);
    add("Прибыльные", s => s.wins, v => v == null ? "—" : String(v));
    add("Убыточные", s => s.losses, v => v == null ? "—" : String(v));
    add("Win %", s => s.winPct, fmtPct);
    add("Средняя сделка", s => s.avg, fmtMoney2, true);
    add("Лучшая сделка", s => s.best, fmtMoney2);
    add("Худшая сделка", s => s.worst, fmtMoney2);
    return table;
  }

  function kvTable(rows) {
    return el("table", { class: "kv" }, rows.map(([label, value]) =>
      el("tr", {}, [el("th", { text: label }), el("td", { text: value })])));
  }

  function renderHistorySummaryPane(job, trades) {
    const { strategy, instrument, timeframe, period, execution, params } = fullJobContext(job);
    const result = job.result || job.result_partial || {};
    const metrics = result.metrics || job.metrics || {};
    const paramsText = Object.entries(params || {}).slice(0, 12)
      .map(([key, value]) => `${key}=${value}`).join(", ") || "Параметры не указаны";
    const grid = el("div", { class: "summary-grid strategies-report-summary" });
    grid.appendChild(el("div", { class: "summary-block summary-block-wide" }, [
      el("h3", { text: "Performance Summary" }),
      renderPerfTable(metrics, trades),
    ]));
    grid.appendChild(el("div", { class: "summary-block" }, [
      el("h3", { text: "Параметры запуска" }),
      kvTable([
        ["Стратегия", strategy.class_name || job.class_name || "—"],
        ["Инструмент", displayInstrument(instrument)],
        ["Таймфрейм", fmtTimeframe(timeframe)],
        ["Период", fmtPeriod(period)],
        ["Trading Hours", execution.session_template || "—"],
        ["Шаблон комиссии", execution.commission_template || "—"],
        ["Параметры", paramsText],
      ]),
    ]));
    grid.appendChild(el("div", { class: "summary-block" }, [
      el("h3", { text: "Контроль" }),
      kvTable([
        ["Статус", jobStatusLabel(job.status)],
        ["Создан", fmtDate(job.created_at_utc || job.job?.created_at_utc)],
        ["Завершен", fmtDate(job.finished_at_utc || result.finished_at_utc)],
        ["Job ID", job.job_id || STATE.selectedHistoryJobId],
      ]),
    ]));
    return grid;
  }

  function drawHistoryEquity(canvas, trades, job) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width = canvas.clientWidth || 900;
    const height = canvas.height = canvas.clientHeight || 170;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#0f1115";
    ctx.fillRect(0, 0, width, height);
    if (!trades.length) {
      ctx.fillStyle = "#78859b";
      ctx.textAlign = "center";
      ctx.fillText("Сделок нет", width / 2, height / 2);
      return;
    }
    const risk = fullJobContext(job).ctx.risk_profile || job.job?.risk_profile || {};
    const base = Number(risk.starting_capital || 0);
    const curve = [];
    let cumulative = 0;
    let low = base;
    let high = base;
    for (const trade of trades) {
      cumulative += Number(trade.pnl_currency || 0);
      const value = base + cumulative;
      curve.push(value);
      low = Math.min(low, value);
      high = Math.max(high, value);
    }
    if (low === high) high = low + 1;
    const padL = 50, padR = 10, padT = 10, padB = 22;
    const innerW = width - padL - padR;
    const innerH = height - padT - padB;
    const x = (idx) => padL + (idx / Math.max(1, curve.length - 1)) * innerW;
    const y = (value) => padT + innerH - ((value - low) / (high - low)) * innerH;
    const yBase = y(base);
    ctx.strokeStyle = "rgba(255,255,255,0.07)";
    for (let i = 1; i < 4; i += 1) {
      const gy = padT + (innerH * i / 4);
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + innerW, gy); ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(x(0), y(curve[0]));
    curve.forEach((value, idx) => ctx.lineTo(x(idx), y(value)));
    ctx.lineTo(x(curve.length - 1), yBase); ctx.lineTo(x(0), yBase); ctx.closePath();
    ctx.fillStyle = cumulative >= 0 ? "rgba(45,170,75,0.42)" : "rgba(185,24,24,0.42)";
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(x(0), y(curve[0]));
    curve.forEach((value, idx) => ctx.lineTo(x(idx), y(value)));
    ctx.strokeStyle = cumulative >= 0 ? "#35d04d" : "#ff4040";
    ctx.lineWidth = 1.6;
    ctx.stroke();
    ctx.strokeStyle = "#2c3142";
    ctx.beginPath(); ctx.moveTo(padL, yBase); ctx.lineTo(padL + innerW, yBase); ctx.stroke();
    ctx.fillStyle = "#6b7280";
    ctx.textAlign = "right";
    ctx.fillText(`$${fmtMoneyShort(high)}`, padL - 4, padT + 8);
    ctx.fillText(`$${fmtMoneyShort(base)}`, padL - 4, yBase + 3);
    ctx.fillText(`$${fmtMoneyShort(low)}`, padL - 4, padT + innerH);
  }

  function fmtMoneyShort(value) {
    const n = Number(value || 0);
    if (Math.abs(n) >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return n.toFixed(0);
  }

  function normalizeBar(bar) {
    return {
      t: bar.t || bar.time || bar.timestamp_utc || "",
      o: Number(bar.o ?? bar.open),
      h: Number(bar.h ?? bar.high),
      l: Number(bar.l ?? bar.low),
      c: Number(bar.c ?? bar.close),
    };
  }

  function drawHistoryPriceChart(canvas, bars, trades) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width = canvas.clientWidth || 900;
    const height = canvas.height = canvas.clientHeight || 280;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = "#0f1115";
    ctx.fillRect(0, 0, width, height);
    const rows = (bars || []).map(normalizeBar).filter(b => [b.o, b.h, b.l, b.c].every(Number.isFinite));
    if (!rows.length) {
      ctx.fillStyle = "#78859b";
      ctx.textAlign = "center";
      ctx.fillText("bars.json недоступен для выбранного отчета", width / 2, height / 2);
      return;
    }
    const maxBars = 420;
    const view = rows.length > maxBars ? rows.slice(-maxBars) : rows;
    let low = Math.min(...view.map(b => b.l));
    let high = Math.max(...view.map(b => b.h));
    if (low === high) high = low + 1;
    const padL = 48, padR = 8, padT = 10, padB = 24;
    const innerW = width - padL - padR;
    const innerH = height - padT - padB;
    const x = (idx) => padL + (idx + 0.5) * (innerW / view.length);
    const y = (price) => padT + innerH - ((price - low) / (high - low)) * innerH;
    ctx.strokeStyle = "rgba(255,255,255,0.07)";
    for (let i = 1; i < 4; i += 1) {
      const gy = padT + innerH * i / 4;
      ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + innerW, gy); ctx.stroke();
    }
    const candleW = Math.max(2, Math.min(8, innerW / view.length * 0.6));
    view.forEach((bar, idx) => {
      const up = bar.c >= bar.o;
      const cx = x(idx);
      ctx.strokeStyle = up ? "#5fbe7d" : "#e06b6b";
      ctx.fillStyle = up ? "rgba(95,190,125,0.65)" : "rgba(224,107,107,0.65)";
      ctx.beginPath(); ctx.moveTo(cx, y(bar.h)); ctx.lineTo(cx, y(bar.l)); ctx.stroke();
      const top = Math.min(y(bar.o), y(bar.c));
      const bot = Math.max(y(bar.o), y(bar.c));
      ctx.fillRect(cx - candleW / 2, top, candleW, Math.max(1, bot - top));
    });
    const byTime = new Map(view.map((bar, idx) => [String(bar.t).slice(0, 16), idx]));
    for (const trade of (trades || [])) {
      const entryKey = String(trade.entry_time_utc || "").slice(0, 16);
      const exitKey = String(trade.exit_time_utc || "").slice(0, 16);
      const entryIdx = byTime.get(entryKey);
      const exitIdx = byTime.get(exitKey);
      if (entryIdx != null && Number.isFinite(Number(trade.entry_price))) {
        ctx.fillStyle = trade.direction === "short" ? "#fcd34d" : "#60a5fa";
        ctx.beginPath(); ctx.arc(x(entryIdx), y(Number(trade.entry_price)), 3, 0, Math.PI * 2); ctx.fill();
      }
      if (exitIdx != null && Number.isFinite(Number(trade.exit_price))) {
        ctx.fillStyle = Number(trade.pnl_currency || 0) >= 0 ? "#86efac" : "#fca5a5";
        ctx.fillRect(x(exitIdx) - 3, y(Number(trade.exit_price)) - 3, 6, 6);
      }
    }
    ctx.fillStyle = "#6b7280";
    ctx.textAlign = "right";
    ctx.fillText(high.toFixed(2), padL - 4, padT + 8);
    ctx.fillText(low.toFixed(2), padL - 4, padT + innerH);
  }

  function renderHistoryAnalysisPane(job, trades) {
    const stats = statsFromTrades(trades);
    const canvas = el("canvas", { class: "strategies-equity-canvas", width: 900, height: 180 });
    requestAnimationFrame(() => drawHistoryEquity(canvas, trades, job));
    return el("div", { class: "strategies-report-analysis" }, [
      el("div", { class: "analysis-equity" }, [
        el("h3", { text: `Кривая капитала (${trades.length} сделок, PnL ${fmtMoney2(stats.net)})` }),
        canvas,
      ]),
      el("div", { class: "analysis-toolbar" }, [
        el("div", { class: "trades-summary" }, [
          el("span", { text: `Сделок: ${stats.count} · Win: ${fmtPct(stats.winPct)} · PF: ${Number.isFinite(stats.profitFactor) ? stats.profitFactor.toFixed(2) : "—"}` }),
        ]),
      ]),
    ]);
  }

  function researchFactRow(label, value, note = "") {
    return el("div", { class: "strategies-research-metric-row" }, [
      el("span", { class: "strategies-research-metric-label", text: label }),
      el("div", { class: "strategies-research-metric-main" }, [
        el("strong", { class: "strategies-research-metric-value", text: value == null || value === "" ? "—" : String(value) }),
        note ? el("small", { class: "strategies-research-metric-note", text: note }) : null,
      ]),
    ]);
  }

  function researchFactColumn(rows) {
    return el("div", { class: "strategies-research-facts-col" }, rows);
  }

  function renderTaskResearch() {
    const title = $("strategies-research-title");
    const sub = $("strategies-research-sub");
    const chip = $("strategies-research-chip");
    const body = $("strategies-research-body");
    if (!title || !sub || !chip || !body) return;

    const family = selectedFamily();
    const profile = selectedResearchProfile(family);
    if (!family || !profile) {
      title.textContent = "Выберите стратегию";
      sub.textContent = "Верхняя панель показывает полный backtest по выбранной стратегии из матрицы.";
      chip.textContent = "—";
      stopResearchResize();
      body.replaceChildren(el("div", {
        class: "strategies-empty-state",
        text: "Выберите стратегию в матрице, чтобы увидеть equity curve и средние доходы.",
      }));
      return;
    }

    const jobId = researchJobIdForProfile(profile, family);
    const rows = backtestRowsForFamily(family);
    const listedJob = rows.find(row => String(row?.job_id || "").trim() === jobId) || rows[0] || null;
    ensureResearchReportLoaded(family, profile);
    const snapshot = researchSnapshot(jobId);
    const job = snapshot.job || listedJob;
    const trades = snapshot.loaded ? snapshot.trades : [];
    const summary = researchSummary(profile, job, trades);
    const timeframeText = fmtTimeframe(
      fullJobContext(job).timeframe
      || profile?.timeframe
      || family?.primary?.timeframe
      || "",
    );
    const selectedName = versionDisplayName(profile, family, family.slot || 1);
    const familyName = familyDisplayName(family);

    title.textContent = selectedName;
    sub.textContent = `${family.root} · ${family.slotLabel || "Стратегия"} · ${family.cellId || "без ячейки"} · NinjaTrader: ${familyName}`;
    chip.textContent = rows.length ? `отчетов ${rows.length}` : (jobId ? "job report" : "нет отчета");

    const meta = el("div", { class: "strategies-research-meta" }, [
      el("span", { class: "strategies-research-tag", text: `Период: ${summary.period.label}` }),
      el("span", { class: "strategies-research-tag", text: `Таймфрейм: ${timeframeText}` }),
      el("span", { class: "strategies-research-tag", text: `Win: ${fmtPct(summary.winPct)}` }),
      el("span", { class: "strategies-research-tag", text: `Job: ${jobId || "—"}` }),
    ]);

    const metrics = el("div", { class: "strategies-research-metrics" }, [
      researchFactColumn([
        researchFactRow("Win rate", fmtPct(summary.winPct)),
        researchFactRow(
          "Период бэктеста",
          summary.periodLengthLabel,
          summary.period.label !== "—" ? summary.period.label : "",
        ),
        researchFactRow("Всего сделок", summary.count ?? "—"),
        researchFactRow("Итоговый доход", fmtMoney2(summary.net)),
        researchFactRow("Profit factor", Number.isFinite(summary.profitFactor) ? Number(summary.profitFactor).toFixed(2) : "—"),
        researchFactRow("Макс. просадка", fmtMoney2(summary.maxDrawdown)),
      ]),
      researchFactColumn([
        researchFactRow(
          "В среднем за неделю",
          fmtMoney2(summary.averages.week),
          fmtTradeRate(summary.tradeRates.week),
        ),
        researchFactRow(
          "В среднем за месяц",
          fmtMoney2(summary.averages.month),
          fmtTradeRate(summary.tradeRates.month),
        ),
        researchFactRow(
          "В среднем за квартал",
          fmtMoney2(summary.averages.quarter),
          fmtTradeRate(summary.tradeRates.quarter),
        ),
        researchFactRow(
          "В среднем за год",
          fmtMoney2(summary.averages.year),
          fmtTradeRate(summary.tradeRates.year),
        ),
        researchFactRow("Средняя сделка", fmtMoney2(summary.avgTrade)),
      ]),
    ]);

    let chartBlock = null;
    if (!jobId && !rows.length) {
      chartBlock = el("div", {
        class: "strategies-empty-state",
        text: "У выбранной стратегии пока нет отчета бэктеста для верхней статистики.",
      });
    } else if (snapshot.error) {
      chartBlock = el("div", {
        class: "strategies-empty-state error",
        text: `Не удалось загрузить полный отчет: ${snapshot.error}`,
      });
    } else if (!snapshot.loaded) {
      chartBlock = el("div", {
        class: "strategies-empty-state",
        text: jobId
          ? `Загрузка полного отчета ${jobId} и equity curve за весь период...`
          : "Ожидание списка отчетов для выбранной стратегии...",
      });
    } else {
      const canvas = el("canvas", { class: "strategies-equity-canvas", width: 900, height: 196 });
      requestAnimationFrame(() => drawHistoryEquity(canvas, trades, job));
      chartBlock = el("div", { class: "strategies-research-chart" }, [
        el("div", { class: "strategies-research-chart-head" }, [
          el("strong", { text: "Кривая капитала за весь период выбранного backtest" }),
          el("span", { text: `PnL ${fmtMoney2(summary.net)} · ${summary.count ?? 0} сделок` }),
        ]),
        canvas,
      ]);
    }

    const layout = el("div", { class: "strategies-research-layout", id: "strategies-research-layout" }, [
      el("div", { class: "strategies-research-side strategies-research-chart-side" }, chartBlock),
      el("div", {
        class: "strategies-research-resizer",
        id: "strategies-research-resizer",
        role: "separator",
        "aria-orientation": "vertical",
        "aria-label": "Изменить ширину графика стратегии",
        tabindex: "0",
      }),
      el("div", { class: "strategies-research-side strategies-research-scroll-side" }, [
        el("div", { class: "strategies-research-facts-scroll" }, [
          metrics,
          el("div", {
            class: "strategies-research-note",
            text: "Средние доходы и средняя частота сделок считаются по полному периоду бэктеста выбранной версии. Источник: выбранный профиль + полный job report + trades.json.",
          }),
        ]),
      ]),
    ]);

    body.replaceChildren(
      meta,
      layout,
    );
    bindResearchResizer();
    scheduleResearchChartRedraw();
  }

  function renderHistoryChartPane(jobId, trades) {
    if (STATE.historyViewerTab === "chart" && (STATE.historyBarsJobId !== jobId || STATE.historyBarsStatus === "idle")) {
      ensureHistoryBarsLoaded(jobId);
    }
    const canvas = el("canvas", { class: "strategies-price-canvas", width: 1100, height: 420 });
    requestAnimationFrame(() => drawHistoryPriceChart(canvas, STATE.historyBars, trades));
    let statusText = "";
    if (STATE.historyBarsStatus === "loading") statusText = "Загрузка bars.json...";
    if (STATE.historyBarsStatus === "missing") statusText = "График недоступен: bars.json отсутствует для этого отчета.";
    if (STATE.historyBarsStatus === "error") statusText = `Ошибка загрузки графика: ${STATE.historyError}`;
    return el("div", { class: "strategies-report-chart" }, [
      el("div", { class: "chart-toolbar" }, [
        el("span", { class: "muted", text: STATE.historyBars.length ? `Бары: ${STATE.historyBars.length.toLocaleString()}` : "" }),
        el("span", { class: "muted chart-hint", text: "Маркеры: круг = вход, квадрат = выход" }),
      ]),
      statusText ? el("div", { class: `chart-status ${STATE.historyBarsStatus === "error" ? "error" : ""}`, text: statusText }) : null,
      el("div", { class: "chart-wrap strategies-chart-wrap" }, canvas),
    ]);
  }

  function renderHistoryTradesPane(trades) {
    const table = el("table", { class: "dense strategies-report-trades" });
    table.appendChild(el("thead", {}, el("tr", {}, [
      el("th", { text: "#" }), el("th", { text: "Сторона" }), el("th", { text: "Вход UTC" }),
      el("th", { class: "num", text: "Цена входа" }), el("th", { text: "Выход UTC" }),
      el("th", { class: "num", text: "Цена выхода" }), el("th", { class: "num", text: "Кол-во" }),
      el("th", { class: "num", text: "PnL $" }), el("th", { class: "num", text: "Тики" }),
    ])));
    const tbody = el("tbody");
    (trades || []).slice(0, 500).forEach((trade, idx) => {
      const pnl = Number(trade.pnl_currency || 0);
      tbody.appendChild(el("tr", {}, [
        el("td", { class: "num", text: trade.trade_no ?? idx + 1 }),
        el("td", { text: trade.direction || "—" }),
        el("td", { text: trade.entry_time_utc || "—" }),
        el("td", { class: "num", text: fmtPx(trade.entry_price) }),
        el("td", { text: trade.exit_time_utc || "—" }),
        el("td", { class: "num", text: fmtPx(trade.exit_price) }),
        el("td", { class: "num", text: trade.quantity ?? "—" }),
        el("td", { class: `num ${pnl >= 0 ? "pos" : "neg"}`, text: fmtMoney2(pnl) }),
        el("td", { class: "num", text: trade.pnl_ticks ?? "—" }),
      ]));
    });
    table.appendChild(tbody);
    const note = trades.length > 500 ? `Показаны первые 500 сделок из ${trades.length}.` : `Сделок: ${trades.length}.`;
    return el("div", { class: "trades-wrap strategies-report-trades-wrap" }, [
      el("div", { class: "strategies-goal-note", text: note }),
      table,
    ]);
  }

  function renderHistoryReportViewer() {
    const jobId = STATE.selectedHistoryJobId;
    const box = el("div", { class: "strategies-report-viewer" });
    if (!jobId) {
      box.appendChild(el("div", { class: "strategies-empty-state", text: "Выберите отчет в истории выше." }));
      return box;
    }
    ensureHistoryReportLoaded(jobId);
    if (STATE.historyError && STATE.historyLoadingJobId !== jobId && STATE.historyJobId !== jobId) {
      box.appendChild(el("div", { class: "strategies-empty-state error", text: STATE.historyError }));
      return box;
    }
    if (STATE.historyJobId !== jobId || !STATE.historyJob) {
      box.appendChild(el("div", { class: "strategies-empty-state", text: `Загрузка отчета ${jobId}...` }));
      return box;
    }
    const tabs = [
      ["summary", "Итоги"],
      ["analysis", "Анализ"],
      ["chart", "График (опц.)"],
      ["trades", "Сделки"],
    ];
    box.appendChild(el("div", { class: "result-tabs", role: "tablist" }, [
      ...tabs.map(([key, label]) => {
        const btn = el("button", {
          type: "button",
          class: `rtab ${STATE.historyViewerTab === key ? "active" : ""}`,
          dataset: { rtab: key },
          role: "tab",
          "aria-selected": STATE.historyViewerTab === key ? "true" : "false",
          text: label,
        });
        btn.addEventListener("click", () => switchHistoryTab(key));
        return btn;
      }),
      el("span", { class: "active-job-pill", text: `Активный: ${jobId}` }),
    ]));
    const panes = el("div", { class: "result-modes strategies-report-modes" });
    const pane = (key, child) => el("section", {
      class: `rtab-pane ${STATE.historyViewerTab === key ? "active" : ""}`,
    }, child);
    panes.appendChild(pane("summary", renderHistorySummaryPane(STATE.historyJob, STATE.historyTrades)));
    panes.appendChild(pane("analysis", renderHistoryAnalysisPane(STATE.historyJob, STATE.historyTrades)));
    panes.appendChild(pane("chart", renderHistoryChartPane(jobId, STATE.historyTrades)));
    panes.appendChild(pane("trades", renderHistoryTradesPane(STATE.historyTrades)));
    box.appendChild(panes);
    return box;
  }

  function backtestStats(profile) {
    const ids = new Set(evidenceIds(profile));
    let bestNet = null;
    for (const job of STATE.jobs) {
      if (!jobMatchesProfile(job, profile)) continue;
      if (job.job_id) ids.add(String(job.job_id));
      const net = Number(job.net_profit_after_commission ?? job.net_profit);
      if (Number.isFinite(net) && (bestNet == null || net > bestNet)) bestNet = net;
    }
    return { count: ids.size, bestNet };
  }

  function renderFamilySlots(root) {
    const list = el("div", { class: "strategies-slot-list" });
    const { slots } = familiesForRoot(root);
    for (let i = 0; i < TARGET_SLOTS; i += 1) {
      const slotNo = i + 1;
      const slotLabel = `Стратегия ${slotNo}`;
      const cellId = portfolioCellId(root, slotNo);
      const family = slots[i];
      if (!family) {
        list.appendChild(el("div", { class: "strategies-slot-row empty" }, [
          el("span", { class: "slot-no", text: String(slotNo) }),
          el("div", { class: "slot-main" }, [
            el("small", { class: "slot-cell-id", text: `${cellId} · ${root} · ${slotLabel}` }),
            el("strong", { text: slotLabel }),
            el("small", { text: "Свободный слот под утвержденную стратегию" }),
          ]),
          el("span", { class: "strategies-status-pill missing", text: "пусто" }),
        ]));
        continue;
      }
      const primary = family.primary;
      const f = forecast30(family.planning);
      const row = el("button", {
        type: "button",
        class: `strategies-slot-row ${family.online.state} ${family.key === STATE.selectedKey ? "selected" : ""}`,
      });
      row.addEventListener("click", () => {
        STATE.selectedKey = family.key;
        requestSelectedStrategyReveal();
        renderTaskResearch();
        renderDetail({ preserveScroll: true });
        renderMatrix();
      });
      const familyName = familyDisplayName(family);
      const primaryName = versionDisplayName(primary, family, family.slot || slotNo);
      row.title = `${cellId}\nИнструмент: ${root}\n${family.slotLabel || slotLabel}\nКласс: ${family.ntClass}\nВерсия: ${primaryName}`;
      row.appendChild(el("span", { class: "slot-no", text: String(slotNo) }));
      row.appendChild(el("div", { class: "slot-main" }, [
        el("small", { class: "slot-cell-id", text: `${cellId} · ${root} · ${family.slotLabel || slotLabel}` }),
        el("strong", { text: primaryName, title: `Класс: ${family.ntClass}\nВерсия: ${primaryName}` }),
        el("small", {
          text: family.approved
            ? `Класс: ${family.ntClass} · версия: ${primaryName}`
            : `Класс: ${family.ntClass} · исследовательская версия, approved-слот еще свободен`,
        }),
      ]));
      row.appendChild(el("div", { class: "slot-metrics" }, [
        el("span", { text: fmtMoney(f.net) }),
        el("small", { text: `${fmtNum(f.trades, 1)} сделок/30д` }),
      ]));
      row.appendChild(el("span", {
        class: `strategies-status-pill ${family.online.state === "active" ? "runtime" : statusClass(family.bestStatus)}`,
        text: family.online.state === "active" ? "online" : statusLabel(family.bestStatus),
      }));
      list.appendChild(row);
    }
    return list;
  }

  function metricBox(label, value) {
    return el("div", { class: "strategies-metric-box" }, [
      el("span", { text: label }),
      el("strong", { text: String(value == null ? "—" : value) }),
    ]);
  }

  function renderVersionCards(family) {
    const wrap = el("div", { class: "strategies-version-list" });
    if (!family) {
      wrap.appendChild(el("div", { class: "strategies-empty-state", text: "Выберите стратегию." }));
      return wrap;
    }
    family.versions.forEach((profile, idx) => {
      const f = forecast30(profile);
      const m = profile.metrics || {};
      const stats = backtestStats(profile);
      const rows = matchingRuntimeRows(profile);
      const online = onlineStateForRows(rows);
      const familyName = familyDisplayName(family);
      const card = el("div", { class: "strategies-version-card" });
      card.appendChild(el("div", { class: "strategies-version-head" }, [
        el("strong", { text: versionDisplayName(profile, family, idx + 1) }),
        el("span", {
          class: `strategies-status-pill ${online.state === "active" ? "runtime" : statusClass(profile.status)}`,
          text: online.state === "active" ? "online" : statusLabel(profile.status),
        }),
      ]));
      card.appendChild(el("div", {
        class: "strategies-version-sub",
        text: `Ячейка: ${family.cellId || "—"} · ${family.root} · ${family.slotLabel || "—"} · NinjaTrader: ${familyName} · класс: ${family.ntClass}`,
      }));
      card.appendChild(el("div", { class: "strategies-version-metrics" }, [
        metricBox("Бэктестов", stats.count || evidenceIds(profile).length || 0),
        metricBox("Чистый", fmtMoney(metric(profile, ["net_profit_after_commission", "adj_net", "net_profit"]))),
        metricBox("DD", fmtMoney(m.max_drawdown)),
        metricBox("Сделок", metric(profile, ["trade_count", "trades", "total_trades"]) ?? "—"),
        metricBox("30д PnL", fmtMoney(f.net)),
        metricBox("30д сделки", fmtNum(f.trades, 1)),
      ]));
      const ids = evidenceIds(profile);
      if (ids.length) {
        card.appendChild(el("div", {
          class: "strategies-evidence",
          text: `Основание: ${ids.slice(0, 3).join(", ")}${ids.length > 3 ? ` +${ids.length - 3}` : ""}`,
          title: ids.join("\n"),
        }));
      }
      card.appendChild(renderProfileActions(profile, family));
      wrap.appendChild(card);
    });
    return wrap;
  }

  function renderBacktestHistory(family) {
    const box = el("section", { class: "strategies-detail-section" });
    box.appendChild(el("div", { class: "strategies-detail-title", text: "История бэктестов выбранной стратегии" }));
    if (!family) {
      box.appendChild(el("div", { class: "strategies-empty-state", text: "Выберите стратегию в портфеле." }));
      return box;
    }
    if (!STATE.jobs.length) {
      box.appendChild(el("div", { class: "strategies-goal-note", text: "История отчетов еще загружается." }));
      return box;
    }
    const rows = backtestRowsForFamily(family);
    if (!rows.length) {
      STATE.selectedHistoryJobId = "";
      box.appendChild(el("div", {
        class: "strategies-goal-note",
        text: "По выбранной стратегии в загруженной истории отчетов бэктестов не найдено.",
      }));
      return box;
    }
    if (!rows.some(job => String(job.job_id || "") === STATE.selectedHistoryJobId)) {
      STATE.selectedHistoryJobId = String(rows[0].job_id || "");
      STATE.historyViewerTab = "summary";
      STATE.historyJobId = "";
      STATE.historyJob = null;
      STATE.historyTrades = [];
      STATE.historyBarsJobId = "";
      STATE.historyBars = [];
      STATE.historyBarsStatus = "idle";
    }

    box.appendChild(el("div", {
      class: "strategies-goal-note",
      text: `Найдено отчетов: ${rows.length}. Список фильтруется по NT-классу ${family.ntClass} и инструменту ${family.root}.`,
    }));

    const table = el("table", { class: "strategies-history-table" });
    const thead = el("thead");
    const htr = el("tr");
    ["Дата", "Статус", "Период", "Сделок", "Win", "Net", "PF", "Отчет"].forEach(label => {
      htr.appendChild(el("th", { text: label }));
    });
    thead.appendChild(htr);
    table.appendChild(thead);

    const tbody = el("tbody");
    rows.forEach(job => {
      const metrics = job.metrics || {};
      const net = job.net_profit_after_commission ?? metrics.net_profit_after_commission ?? job.net_profit ?? metrics.net_profit;
      const pf = job.profit_factor_after_commission ?? metrics.profit_factor_after_commission ?? job.profit_factor ?? metrics.profit_factor;
      const selected = String(job.job_id || "") === STATE.selectedHistoryJobId;
      const tr = el("tr", {
        class: `strategies-history-row ${selected ? "selected" : ""}`,
        title: job.job_id || "",
        tabindex: "0",
      });
      tr.addEventListener("click", () => selectHistoryJob(job.job_id));
      tr.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          selectHistoryJob(job.job_id);
        }
      });
      tr.appendChild(el("td", { text: fmtDate(job.finished_at_utc || job.created_at_utc) }));
      tr.appendChild(el("td", { text: jobStatusLabel(job.status) }));
      tr.appendChild(el("td", { text: fmtTimeframe(job.timeframe) }));
      tr.appendChild(el("td", { text: job.trade_count ?? metrics.trade_count ?? "—" }));
      tr.appendChild(el("td", { text: fmtPct(job.winning_pct ?? metrics.winning_pct) }));
      tr.appendChild(el("td", { class: Number(net) >= 0 ? "pos" : "neg", text: fmtMoney(net) }));
      tr.appendChild(el("td", { text: fmtNum(pf, 2) }));
      tr.appendChild(el("td", { text: job.report_no ? `#${job.report_no}` : String(job.job_id || "—").slice(0, 16) }));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    box.appendChild(el("div", { class: "strategies-history-wrap" }, table));
    box.appendChild(renderHistoryReportViewer());
    return box;
  }

  function renderOrphans(root) {
    const { orphans } = familiesForRoot(root);
    const box = el("section", { class: "strategies-detail-section" });
    box.appendChild(el("div", { class: "strategies-detail-title", text: "Профили вне NinjaTrader" }));
    if (!orphans.length) {
      box.appendChild(el("div", {
        class: "strategies-goal-note",
        text: "Для выбранного инструмента все профили привязаны к существующим классам NinjaTrader.",
      }));
      return box;
    }
    box.appendChild(el("div", {
      class: "strategies-goal-note",
      text: "Эти записи есть в profiles/coverage, но их классов сейчас нет в каталоге NinjaTrader. Они не считаются как рабочие стратегии на этой странице.",
    }));
    const list = el("div", { class: "strategies-version-list" });
    orphans.forEach(profile => {
      const card = el("div", { class: "strategies-version-card" }, [
        el("div", { class: "strategies-version-head" }, [
          el("strong", { text: profile.name || profile.profile_id || profile.strategy_class || "—" }),
          el("span", { class: `strategies-status-pill ${statusClass(profile.status)}`, text: statusLabel(profile.status) }),
        ]),
        el("div", {
          class: "strategies-version-sub",
          text: `Класс из профиля: ${profile.deploy_strategy_class || profile.strategy_class || "—"} · инструмент: ${profile.instrument || "—"}`,
        }),
      ]);
      card.appendChild(renderProfileActions(profile, null));
      list.appendChild(card);
    });
    box.appendChild(list);
    return box;
  }

  function renderDetail(options = {}) {
    const title = $("strategies-detail-title");
    const status = $("strategies-selected-status");
    const body = $("strategies-detail-body");
    const preserveScroll = !!options.preserveScroll;
    const savedScrollTop = preserveScroll ? body.scrollTop : 0;
    const savedScrollLeft = preserveScroll ? body.scrollLeft : 0;
    const root = STATE.selectedRoot;
    const row = STATE.instruments.find(x => x.root === root);
    const family = selectedFamily();

    if (family && !STATE.selectedKey) STATE.selectedKey = family.key;
    title.textContent = root ? `${root} стратегии` : "Инструмент";
    status.textContent = row ? statusLabel(row.best_status) : "—";
    body.replaceChildren();
    if (!root) {
      body.appendChild(el("div", { class: "strategies-empty-state", text: "Нет выбранного инструмента." }));
      return;
    }

    const goal = goalForRoot(root);
    const summary = el("section", { class: "strategies-detail-section" });
    summary.appendChild(el("div", { class: "strategies-detail-title", text: "Цель по инструменту" }));
    summary.appendChild(progressBar("Чистая прибыль за 30 дней", goal.net, TARGET_MONTHLY_PROFIT, true));
    summary.appendChild(progressBar("Сделки за 30 дней", goal.trades, TARGET_TRADES_30D, false));
    const collection = familiesForRoot(root);
    const researchVisible = collection.families.filter(f => !f.approved).length;
    summary.appendChild(el("div", {
      class: "strategies-goal-note",
      text: `В approved-портфель считаются только ready-профили, привязанные к реальным классам NinjaTrader. Сейчас: ${collection.approvedFamilies.length}/${TARGET_SLOTS} approved-стратегий, ${researchVisible} исследовательских ячеек отображаются отдельно, ${collection.approvedOrphans.length} ready-профилей вне каталога NT.`,
    }));
    body.appendChild(summary);

    const slots = el("section", { class: "strategies-detail-section" });
    slots.appendChild(el("div", { class: "strategies-detail-title", text: "Стратегии в портфеле" }));
    slots.appendChild(renderFamilySlots(root));
    body.appendChild(slots);

    const details = el("section", { class: "strategies-detail-section" });
    details.appendChild(el("div", { class: "strategies-detail-title", text: family ? "Версии выбранной стратегии" : "Версии" }));
    if (family) {
      const f = forecast30(family.planning);
      const familyName = familyDisplayName(family);
      const primaryName = versionDisplayName(family.primary, family, family.slot || 1);
      details.appendChild(el("div", { class: `strategies-selected-card ${family.online.state}` }, [
        el("small", { class: "strategies-selected-cell", text: `Ячейка: ${family.cellId || "—"} · Инструмент: ${family.root} · Слот: ${family.slotLabel || "—"}` }),
        el("strong", { text: familyName }),
        el("span", {
          text: `${family.online.state === "active" ? "online active" : statusLabel(family.bestStatus)} · версия: ${primaryName} · класс: ${family.ntClass} · прогноз ${fmtMoney(f.net)} / ${fmtNum(f.trades, 1)} сделок за 30 дней`,
        }),
      ]));
    }
    details.appendChild(renderVersionCards(family));
    body.appendChild(details);
    body.appendChild(renderBacktestHistory(family));
    body.appendChild(renderOrphans(root));
    if (preserveScroll) {
      body.scrollTop = savedScrollTop;
      body.scrollLeft = savedScrollLeft;
    } else {
      body.scrollTop = 0;
      body.scrollLeft = 0;
    }
  }

  function render() {
    renderStats();
    renderInstrumentList();
    renderMatrix();
    renderTaskResearch();
    renderDetail();
  }

  function bind() {
    const refresh = $("strategies-refresh");
    if (refresh) refresh.addEventListener("click", loadAll);
    const search = $("strategies-search");
    if (search) search.addEventListener("input", () => {
      STATE.search = search.value || "";
      renderInstrumentList();
      renderMatrix();
    });
    const filter = $("strategies-status-filter");
    if (filter) filter.addEventListener("change", () => {
      STATE.statusFilter = filter.value || "all";
      renderInstrumentList();
      renderMatrix();
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bind();
    bindPaneLayout();
    loadAll().catch(err => {
      setChip(`Ошибка загрузки: ${err.message}`, "bad");
      const body = $("strategies-detail-body");
      if (body) body.replaceChildren(el("div", { class: "strategies-empty-state error", text: err.message }));
    });
  });
})();
