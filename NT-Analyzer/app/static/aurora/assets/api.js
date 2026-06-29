/* =====================================================================
   API — data access layer (the integration seam).
   A single REAL ASYNCHRONOUS HTTP layer (window.API.http.*) calling the actual
   /api/* endpoints from app/server.py (no invented endpoints). Every page uses
   this layer; each method returns a Promise of the real backend shape (see
   docs/UI_API_MAP.md). Production loads NO mock data.
   ===================================================================== */
(function () {
  const isFile = location.protocol === 'file:';

  // "Старый интерфейс" target: served by backend → /ui/legacy/.
  const legacyUrl = '/ui/legacy/';

  // ---- real async HTTP layer over the actual endpoints --------------------
  class HttpError extends Error {
    constructor(status, message, path) { super(message); this.name = 'HttpError'; this.status = status; this.path = path; }
  }
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const qs = (obj) => {
    const p = new URLSearchParams();
    Object.entries(obj || {}).forEach(([k, v]) => { if (v != null && v !== '') p.set(k, v); });
    const s = p.toString();
    return s ? '?' + s : '';
  };
  async function getJSON(path, { signal, retries = 1 } = {}) {
    let lastErr;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const res = await fetch(path, { headers: { Accept: 'application/json' }, signal });
        if (!res.ok) {
          let detail = '';
          try { detail = (await res.json()).error || ''; } catch (e) { /* non-json */ }
          throw new HttpError(res.status, detail || res.statusText, path);
        }
        return await res.json();
      } catch (e) {
        lastErr = e;
        if (e.name === 'AbortError') throw e;
        if (attempt < retries) await sleep(250 * (attempt + 1));
      }
    }
    throw lastErr;
  }
  async function send(path, method, body) {
    const res = await fetch(path, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body == null ? '{}' : JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) throw new HttpError(res.status, (data && data.error) || res.statusText, path);
    return data;
  }
  async function del(path) {
    const res = await fetch(path, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) throw new HttpError(res.status, (data && data.error) || res.statusText, path);
    return data;
  }

  // Endpoint map mirrors app/server.py exactly.
  const http = {
    health: (o) => getJSON('/api/health', o),
    diagnostics: (o) => getJSON('/api/diagnostics', o),
    catalog: (o) => getJSON('/api/catalog', o),
    governanceRuntimeDefaults: (o) => getJSON('/api/governance/runtime-defaults', o),
    restartServer: () => send('/api/server/restart', 'POST', {}),
    refreshCatalog: () => send('/api/catalog/refresh', 'POST', {}),
    refreshMargins: () => send('/api/margins/refresh', 'POST', {}),
    strategies: (o) => getJSON('/api/strategies', o),
    profiles: (o) => getJSON('/api/profiles', o),
    profilesArchive: (o) => getJSON('/api/profiles/archive', o),
    researchModes: (o) => getJSON('/api/research-modes', o),
    profileUpdate: (id, updates, action) => send('/api/ops/profiles/' + encodeURIComponent(id) + '/update', 'POST', { updates: updates || {}, action: action || 'update' }),
    profileDelete: (id) => send('/api/ops/profiles/' + encodeURIComponent(id) + '/delete', 'POST', {}),
    ninjatraderCleanup: (body) => send('/api/profiles/ninjatrader/cleanup', 'POST', body || { dry_run: true }),
    profileRemoveFromNt: (body) => send('/api/profiles/archive/remove-from-nt', 'POST', body || {}),
    coverage: (o) => getJSON('/api/coverage', o),
    strategyFamilies: (o) => getJSON('/api/strategy-families', o),
    portfolioCells: (o) => getJSON('/api/portfolio/cells', o),
    portfolioAddRoot: (body) => send('/api/portfolio/roots', 'POST', body),
    portfolioAddCell: (body) => send('/api/portfolio/cells', 'POST', body),
    portfolioArchiveCell: (id, body) => send('/api/portfolio/cells/' + encodeURIComponent(id) + '/archive', 'POST', body || {}),
    aiCellHistory: (cell, o) => getJSON('/api/ai-lab/cell-history' + qs({ cell }), o),
    instruments: (o) => getJSON('/api/ops/runtime/instruments', o),
    reports: (q, o) => getJSON('/api/reports' + qs(q), o),
    jobs: (q, o) => getJSON('/api/jobs' + qs(q), o),
    job: (id, o) => getJSON('/api/jobs/' + encodeURIComponent(id), o),
    jobTrades: (id, q, o) => getJSON('/api/jobs/' + encodeURIComponent(id) + '/trades' + qs(q), o),
    createJob: (body) => send('/api/jobs', 'POST', body),
    createBatch: (body) => send('/api/batches', 'POST', body),
    cancelJob: (id) => send('/api/jobs/' + encodeURIComponent(id) + '/cancel', 'POST', {}),
    deleteJob: (id) => del('/api/jobs/' + encodeURIComponent(id)),
    jobBars: (id, q, o) => getJSON('/api/jobs/' + encodeURIComponent(id) + '/bars' + qs(q), o),
    jobDrawObjects: (id, o) => getJSON('/api/jobs/' + encodeURIComponent(id) + '/draw_objects', o),
    reportFavorites: (q, o) => getJSON('/api/report-favorites' + qs(q), o),
    favoriteReport: (body) => send('/api/report-favorites', 'POST', body),
    unfavoriteReport: (kind, id) => del('/api/report-favorites/' + encodeURIComponent(kind) + '/' + encodeURIComponent(id)),
    repeatFavorite: (kind, id) => send('/api/report-favorites/' + encodeURIComponent(kind) + '/' + encodeURIComponent(id) + '/repeat', 'POST', {}),
    batches: (q, o) => getJSON('/api/batches' + qs(q), o),
    batchResults: (id, o) => getJSON('/api/batches/' + encodeURIComponent(id) + '/results', o),
    performance: (q, o) => getJSON('/api/performance' + qs(q), o),
    performanceTrades: (q, o) => getJSON('/api/performance/trades' + qs(q), o),
    runtimeAccounts: (o) => getJSON('/api/ops/runtime/accounts', o),
    runtimeAccountHistory: (q, o) => getJSON('/api/ops/runtime/account-history' + qs(q), o),
    classifyAccountEvent: (body) => send('/api/ops/runtime/account-history/classify', 'POST', body),
    addAccountEvent: (body) => send('/api/ops/runtime/account-history/events', 'POST', body),
    importAccountEvents: (body) => send('/api/ops/runtime/account-history/import', 'POST', body),
    runtimeStrategies: (q, o) => getJSON('/api/ops/runtime/strategies' + qs(q), o),
    runtimeHistory: (q, o) => getJSON('/api/ops/runtime/history' + qs(q), o),
    runtimeStrategyHistory: (q, o) => getJSON('/api/ops/runtime/strategy-history' + qs(q), o),
    runtimeStrategyDisplay: (o) => getJSON('/api/ops/runtime/strategy-display', o),
    setRuntimeStrategyDisplay: (body) => send('/api/ops/runtime/strategy-display', 'POST', body),
    strategyStartDates: (o) => getJSON('/api/ops/strategy-start-dates', o),
    runtimePositions: (o) => getJSON('/api/ops/runtime/positions', o),
    runtimeOrders: (q, o) => getJSON('/api/ops/runtime/orders' + qs(q), o),
    runtimeExecutions: (q, o) => getJSON('/api/ops/runtime/executions' + qs(q), o),
    runtimeHeartbeat: (o) => getJSON('/api/ops/runtime/heartbeat', o),
    runtimeCommands: (q, o) => getJSON('/api/ops/runtime/commands' + qs(q), o),
    runtimeCommandResults: (q, o) => getJSON('/api/ops/runtime/command-results' + qs(q), o),
    runtimeCommandStatus: (q, o) => getJSON('/api/ops/runtime/command-status' + qs(q), o),
    runtimeErrors: (q, o) => getJSON('/api/ops/runtime/errors' + qs(q), o),
    opsStrategies: (o) => getJSON('/api/ops/strategies', o),
    opsStrategyJournal: (id, o) => getJSON('/api/ops/strategies/' + encodeURIComponent(id) + '/journal', o),
    sccStrategies: (o) => getJSON('/api/scc/strategies', o),
    runtimeCommand: (body) => send('/api/ops/runtime/command', 'POST', body),
    governanceDocuments: (o) => getJSON('/api/governance/documents', o),
    governanceDocument: (id, o) => getJSON('/api/governance/documents/' + encodeURIComponent(id), o),
    governanceHistory: (q, o) => getJSON('/api/governance/history' + qs(q), o),
    governanceSummary: (o) => getJSON('/api/governance/summary', o),
    saveDocument: (id, body) => send('/api/governance/documents/' + encodeURIComponent(id), 'POST', body),
    aiSummary: (o) => getJSON('/api/ai-lab/summary', o),
    aiPerformance: (o) => getJSON('/api/ai-lab/performance', o),
    aiModelPerformance: (q, o) => getJSON('/api/ai-lab/model-performance' + qs(q), o),
    aiCalendar: (o) => getJSON('/api/ai-lab/calendar', o),
    aiCurrent: (o) => getJSON('/api/ai-lab/current', o),
    aiCompileSourceStatus: (o) => getJSON('/api/ai-lab/compile-source-status', o),
    aiExperiments: (q, o) => getJSON('/api/ai-lab/experiments' + qs(q), o),
    aiExperiment: (id, o) => getJSON('/api/ai-lab/experiments/' + encodeURIComponent(id), o),
    aiExperimentActivity: (id, q, o) => getJSON('/api/ai-lab/experiments/' + encodeURIComponent(id) + '/activity' + qs(q), o),
    aiExperimentBacktest: (id, o) => getJSON('/api/ai-lab/experiments/' + encodeURIComponent(id) + '/backtest', o),
    aiLifecycle: (o) => getJSON('/api/ai-lab/lifecycle', o),
    aiPortfolio: (o) => getJSON('/api/ai-lab/portfolio', o),
    aiMatrix: (q, o) => getJSON('/api/ai-lab/matrix' + qs(q), o),
    aiRunStatus: (o) => getJSON('/api/ai-lab/run/status', o),
    aiErrorsSummary: (o) => getJSON('/api/ai-lab/errors/summary', o),
    aiBootstrapStatus: (q, o) => getJSON('/api/ai-lab/bootstrap/status' + qs(q), o),
    aiLmStudioHealth: (o) => getJSON('/api/ai-lab/lm-studio/health', o),
    aiLmReadiness: (q, o) => getJSON('/api/ai-lab/lm-studio/readiness' + qs(q), o),
    aiRun: (body) => send('/api/ai-lab/run', 'POST', body),
    aiRunCancel: (body) => send('/api/ai-lab/run/cancel', 'POST', body),
    aiCancel: (body) => send('/api/ai-lab/cancel', 'POST', body),
    aiBootstrapStart: (body) => send('/api/ai-lab/bootstrap/start', 'POST', body || {}),
    aiBootstrapUnload: (body) => send('/api/ai-lab/bootstrap/unload', 'POST', body || {}),
    aiOperatorNoteGlobal: (body) => send('/api/ai-lab/operator-notes/global', 'POST', body),
    aiSweepStale: (body) => send('/api/ai-lab/maintenance/sweep-stale', 'POST', body || {}),
    aiUserResearchScan: (body) => send('/api/ai-lab/user-research/scan', 'POST', body || {}),
  };

  window.API = { config: { legacyUrl, offline: isFile }, http, HttpError };
})();
