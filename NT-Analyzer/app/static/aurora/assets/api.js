/* =====================================================================
   API — data access layer (the integration seam).
   A single REAL ASYNCHRONOUS HTTP layer (window.API.http.*) calling the actual
   /api/* endpoints from app/server.py (no invented endpoints). Every page uses
   this layer; each method returns a Promise of the real backend shape (see
   docs/UI_API_MAP.md). Production loads NO mock data.
   ===================================================================== */
(function () {
  const isFile = location.protocol === 'file:';
  const INIT_DATA_KEY = 'stratforge.telegram.initData';

  function discoverTelegramInitData() {
    const sdkValue = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData;
    let raw = String(sdkValue || '');
    for (const source of [location.hash.slice(1), location.search.slice(1)]) {
      if (raw || !source) continue;
      const params = new URLSearchParams(source);
      raw = String(params.get('tgWebAppData') || '');
    }
    try {
      if (raw) sessionStorage.setItem(INIT_DATA_KEY, raw);
      else raw = String(sessionStorage.getItem(INIT_DATA_KEY) || '');
    } catch (e) { /* storage can be disabled inside hardened WebViews */ }
    return raw;
  }

  const telegramInitData = discoverTelegramInitData();
  const miniApp = !!telegramInitData;
  let csrfToken = '';
  if (miniApp) document.documentElement.classList.add('telegram-mini-app');

  function requestHeaders(values) {
    const headers = Object.assign({}, values || {});
    if (telegramInitData) headers['X-Telegram-Init-Data'] = telegramInitData;
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    return headers;
  }

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
        const res = await fetch(path, { headers: requestHeaders({ Accept: 'application/json' }), signal });
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
      headers: requestHeaders({ 'Content-Type': 'application/json' }),
      body: body == null ? '{}' : JSON.stringify(body),
    });
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) throw new HttpError(res.status, (data && data.error) || res.statusText, path);
    return data;
  }
  async function del(path) {
    const res = await fetch(path, { method: 'DELETE', headers: requestHeaders({ 'Content-Type': 'application/json' }), body: '{}' });
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) throw new HttpError(res.status, (data && data.error) || res.statusText, path);
    return data;
  }

  // Server-Sent Events client for the orchestrator chat. Streams two channels —
  // native reasoning ("thinking") and then the final answer — over one POST.
  // No polyfill/EventSource (that is GET-only): we read the fetch body stream
  // and parse SSE frames manually. `handlers` = { onThinkingStart, onThinkingDelta,
  // onStatus, onThinkingDone, onFinal, onError, onDone }. Resolves when the
  // stream ends. Falls back gracefully if streaming is unsupported.
  async function streamOrchestrator(message, conversationId, agent, handlers) {
    const path = '/api/ai-lab/orchestrator/message/stream';
    const h = handlers || {};
    const res = await fetch(path, {
      method: 'POST',
      headers: requestHeaders({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
      body: JSON.stringify({ message, conversation_id: conversationId || 'default', agent: agent || '' }),
    });
    if (!res.ok || !res.body || !res.body.getReader) {
      let detail = '';
      try { detail = (await res.json()).error || ''; } catch (e) { /* non-json */ }
      throw new HttpError(res.status || 0, detail || res.statusText || 'stream unavailable', path);
    }
    const dispatch = (evt, data) => {
      if (evt === 'thinking_start') { h.onThinkingStart && h.onThinkingStart(data); }
      else if (evt === 'thinking_delta') { h.onThinkingDelta && h.onThinkingDelta(String(data.text || '')); }
      else if (evt === 'status') { h.onStatus && h.onStatus(String(data.text || '')); }
      else if (evt === 'thinking_done') { h.onThinkingDone && h.onThinkingDone(String(data.text || '')); }
      else if (evt === 'final') { h.onFinal && h.onFinal(data); }
      else if (evt === 'error') { h.onError && h.onError(String(data.error || 'error')); }
      else if (evt === 'done') { h.onDone && h.onDone(data); }
    };
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const trimmed = block.replace(/\r/g, '');
        if (!trimmed.trim() || trimmed.startsWith(':')) continue; // keepalive/comment
        let evt = 'message';
        let dataStr = '';
        trimmed.split('\n').forEach((line) => {
          if (line.indexOf('event:') === 0) evt = line.slice(6).trim();
          else if (line.indexOf('data:') === 0) dataStr += line.slice(5).trim();
        });
        let data = {};
        try { data = dataStr ? JSON.parse(dataStr) : {}; } catch (e) { data = {}; }
        dispatch(evt, data);
      }
    }
  }

  // Endpoint map mirrors app/server.py exactly.
  const http = {
    authStatus: (o) => getJSON('/api/auth/status', o),
    authLoginStart: () => send('/api/auth/login/start', 'POST', {}),
    authLoginStatus: async (challengeId) => {
      const data = await send('/api/auth/login/status', 'POST', { challenge_id: challengeId });
      if (data && data.csrf_token) csrfToken = data.csrf_token;
      return data;
    },
    authProfile: (challengeId, profile) => send('/api/auth/profile', 'POST', { challenge_id: challengeId, profile }),
    authLogout: () => send('/api/auth/logout', 'POST', {}),
    authUsers: (o) => getJSON('/api/auth/users', o),
    authUserRole: (id, role) => send('/api/auth/users/' + encodeURIComponent(id) + '/role', 'POST', { role }),
    authUserRevoke: (id) => send('/api/auth/users/' + encodeURIComponent(id) + '/revoke', 'POST', {}),
    health: (o) => getJSON('/api/health', o),
    diagnostics: (o) => getJSON('/api/diagnostics', o),
    catalog: (o) => getJSON('/api/catalog', o),
    governanceRuntimeDefaults: (o) => getJSON('/api/governance/runtime-defaults', o),
    northStar: (o) => getJSON('/api/governance/north-star', o),
    integrationsStatus: (o) => getJSON('/api/integrations/status', o),
    telegramStatus: (o) => getJSON('/api/telegram/status', o),
    telegramRemoteMe: (o) => getJSON('/api/telegram/remote/me', o),
    telegramRemoteAccess: (o) => getJSON('/api/telegram/remote/access', o),
    telegramRemoteSettings: (body) => send('/api/telegram/remote/settings', 'POST', body),
    telegramRemotePairStart: (body) => send('/api/telegram/remote/pair/start', 'POST', body),
    telegramRemoteSetRole: (id, role) => send('/api/telegram/remote/users/' + encodeURIComponent(id) + '/role', 'POST', { role }),
    telegramRemoteRevoke: (id) => send('/api/telegram/remote/users/' + encodeURIComponent(id) + '/revoke', 'POST', {}),
    telegramRemoteMenuButton: () => send('/api/telegram/remote/menu-button', 'POST', {}),
    telegramTunnelStatus: (o) => getJSON('/api/telegram/tunnel/status', o),
    telegramTunnelLaunch: (body) => send('/api/telegram/tunnel/launch', 'POST', body || {}),
    telegramTunnelStart: () => send('/api/telegram/tunnel/start', 'POST', {}),
    telegramTunnelStop: () => send('/api/telegram/tunnel/stop', 'POST', {}),
    telegramSaveToken: (token) => send('/api/telegram/token', 'POST', { token }),
    telegramPairStart: () => send('/api/telegram/pair/start', 'POST', {}),
    telegramPairComplete: () => send('/api/telegram/pair/complete', 'POST', {}),
    telegramSettings: (settings) => send('/api/telegram/settings', 'POST', { settings }),
    telegramTest: () => send('/api/telegram/test', 'POST', {}),
    telegramGroupStatus: (o) => getJSON('/api/telegram/group', o),
    telegramConfigureGroup: (groupId) => send('/api/telegram/group', 'POST', { group_id: groupId }),
    telegramDisconnectGroup: () => send('/api/telegram/group/disconnect', 'POST', {}),
    telegramDisconnect: () => send('/api/telegram/disconnect', 'POST', {}),
    topstepStatus: (o) => getJSON('/api/topstep/status', o),
    news: (q, o) => getJSON('/api/news' + qs(q), o),
    newsLive: (q, o) => getJSON('/api/news/live' + qs(q), o),
    externalAgentsStatus: (o) => getJSON('/api/ai-lab/external-agents/status', o),
    cloudAgentsStatus: (o) => getJSON('/api/ai-lab/cloud-agents/status', o),
    cloudAgentsSettings: (settings) => send('/api/ai-lab/cloud-agents/settings', 'POST', { settings }),
    cloudProviderKey: (provider, apiKey) => send('/api/ai-lab/cloud-agents/provider-key', 'POST', { provider, api_key: apiKey }),
    cloudProviderTest: (provider) => send('/api/ai-lab/cloud-agents/provider-test', 'POST', { provider }),
    cloudProviderDisconnect: (provider) => send('/api/ai-lab/cloud-agents/provider-disconnect', 'POST', { provider }),
    aiAgents: (o) => getJSON('/api/ai-agents', o),
    aiAgent: (id, o) => getJSON('/api/ai-agents/' + encodeURIComponent(id), o),
    aiAgentCreate: (agent) => send('/api/ai-agents', 'POST', { agent }),
    aiAgentUpdate: (id, agent) => send('/api/ai-agents/' + encodeURIComponent(id), 'POST', { agent }),
    aiAgentToggle: (id, enabled) => send('/api/ai-agents/' + encodeURIComponent(id) + '/toggle', 'POST', { enabled }),
    aiAgentTest: (id, prompt) => send('/api/ai-agents/' + encodeURIComponent(id) + '/test', 'POST', { prompt: prompt || '' }),
    aiAgentSyncBalance: (id) => send('/api/ai-agents/' + encodeURIComponent(id) + '/sync-balance', 'POST', {}),
    aiAgentDelete: (id) => send('/api/ai-agents/' + encodeURIComponent(id) + '/delete', 'POST', {}),
    aiAgentUsage: (q, o) => getJSON('/api/ai-agents/usage' + qs(q), o),
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
    catalogRefresh: () => send('/api/catalog/refresh', 'POST', {}),
    instruments: (o) => getJSON('/api/ops/runtime/instruments', o),
    desktopInstruments: (o) => getJSON('/api/ops/runtime/instruments?desktop=1', o),
    marketBarsBatch: (body) => send('/api/ops/runtime/bars/batch', 'POST', body),
    marketBars: (q, o) => getJSON('/api/ops/runtime/bars' + qs(q), o),
    priceAlerts: (q, o) => getJSON('/api/ops/runtime/price-alerts' + qs(q), o),
    createPriceAlert: (body) => send('/api/ops/runtime/price-alerts', 'POST', body),
    deletePriceAlert: (id) => del('/api/ops/runtime/price-alerts/' + encodeURIComponent(id)),
    chartCommands: (q, o) => getJSON('/api/ops/runtime/chart-commands' + qs(q), o),
    ackChartCommand: (id, status, result) => send('/api/ops/runtime/chart-commands/ack', 'POST', { id, status, result }),
    chartSnapshot: (body) => send('/api/ops/runtime/chart-snapshot', 'POST', body),
    snapshots: (q, o) => getJSON('/api/ops/runtime/snapshots' + qs(q), o),
    updateSnapshot: (body) => send('/api/ops/runtime/snapshots/update', 'POST', body),
    clearSnapshots: (keepFavorites) => send('/api/ops/runtime/snapshots/clear', 'POST', { keep_favorites: keepFavorites !== false }),
    deleteSnapshot: (id) => del('/api/ops/runtime/snapshots/' + encodeURIComponent(id)),
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
    aiChiefStatus: (o) => getJSON('/api/ai-lab/chief-agent', o),
    aiOrchestratorStatus: (o) => getJSON('/api/ai-lab/orchestrator', o),
    aiOrchestratorMessage: (message, conversationId, agent) => send('/api/ai-lab/orchestrator/message', 'POST', { message, conversation_id: conversationId || 'default', agent: agent || '' }),
    aiOrchestratorMessageStream: (message, conversationId, agent, handlers) => streamOrchestrator(message, conversationId, agent, handlers),
    aiOrchestratorRateMessage: (conversationId, messageId, rating, comment) => send('/api/ai-lab/orchestrator/message/' + encodeURIComponent(messageId) + '/rating', 'POST', { conversation_id: conversationId || 'default', rating, feedback_comment: comment || '', feedback_source: 'owner' }),
    aiOrchestratorConversations: (o) => getJSON('/api/ai-lab/orchestrator/conversations', o),
    aiOrchestratorConversation: (id, q, o) => getJSON('/api/ai-lab/orchestrator/conversations/' + encodeURIComponent(id) + qs(q), o),
    aiOrchestratorCreateConversation: (title) => send('/api/ai-lab/orchestrator/conversations', 'POST', { title: title || '' }),
    aiOrchestratorRenameConversation: (id, title) => send('/api/ai-lab/orchestrator/conversations/rename', 'POST', { conversation_id: id, title }),
    aiOrchestratorPinConversation: (id, pinned) => send('/api/ai-lab/orchestrator/conversations/pin', 'POST', { conversation_id: id, pinned: pinned }),
    aiOrchestratorSetConversationState: (id, state) => send('/api/ai-lab/orchestrator/conversations/state', 'POST', { conversation_id: id, state: state }),
    aiOrchestratorDeleteConversation: (id) => send('/api/ai-lab/orchestrator/conversations/delete', 'POST', { conversation_id: id }),
    domainAgents: (o) => getJSON('/api/ai-lab/domain-agents', o),
    accounting: (q, o) => getJSON('/api/ai-lab/accounting' + qs(q), o),
    strategyAnalysis: (q, o) => getJSON('/api/ai-lab/strategy-analysis' + qs(q), o),
    newsAnalysis: (q, o) => getJSON('/api/ai-lab/news-analysis' + qs(q), o),
    domainAgentMessage: (agentId, message, options) => send('/api/ai-lab/domain-agents/message', 'POST', Object.assign({ agent_id: agentId, message }, options || {})),
    aiChiefMission: (body) => send('/api/ai-lab/chief-agent/mission', 'POST', body || {}),
    aiChiefMissionState: (action) => send('/api/ai-lab/chief-agent/mission/state', 'POST', { action }),
    aiChiefTask: (body) => send('/api/ai-lab/chief-agent/tasks', 'POST', body || {}),
    aiChiefAudit: (body) => send('/api/ai-lab/chief-agent/audit', 'POST', body || {}),
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

  const authReady = isFile ? Promise.resolve({ auth: null }) : http.authStatus({ retries: 0 }).then(auth => {
    csrfToken = String(auth.csrf_token || '');
    document.documentElement.dataset.remoteRole = auth.role || 'read_only';
    document.documentElement.classList.add('authenticated');
    return { auth };
  }).catch(error => ({ error }));
  window.API = { config: { legacyUrl, offline: isFile, miniApp, telegramInitData }, http, HttpError, authReady };
})();
