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
  const INIT_DATA_QUERY_KEY = 'tgWebAppData';

  function readTelegramInitDataFromLocation() {
    for (const source of [location.hash.slice(1), location.search.slice(1)]) {
      if (!source) continue;
      const params = new URLSearchParams(source);
      const raw = String(params.get(INIT_DATA_QUERY_KEY) || '');
      if (raw) return raw;
    }
    return '';
  }

  function readTelegramInitDataFromStorage() {
    try { return String(sessionStorage.getItem(INIT_DATA_KEY) || ''); }
    catch (e) { return ''; }
  }

  function persistTelegramInitData(raw) {
    try {
      if (raw) sessionStorage.setItem(INIT_DATA_KEY, raw);
    } catch (e) { /* storage can be disabled inside hardened WebViews */ }
  }

  function discoverTelegramInitData() {
    const sdkValue = window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData;
    let raw = String(sdkValue || '');
    if (!raw) raw = readTelegramInitDataFromLocation();
    if (!raw) raw = readTelegramInitDataFromStorage();
    persistTelegramInitData(raw);
    return raw;
  }

  let telegramInitData = '';
  function refreshTelegramInitData() {
    const raw = discoverTelegramInitData();
    if (raw) {
      telegramInitData = raw;
      document.documentElement.classList.add('telegram-mini-app');
    }
    return telegramInitData;
  }

  function withTelegramContext(path) {
    const raw = refreshTelegramInitData();
    if (!raw || !path) return path;
    let url;
    try { url = new URL(path, location.href); }
    catch (e) { return path; }
    if (url.origin !== location.origin || url.pathname.indexOf('/api/') === 0) return path;
    if (!url.searchParams.has(INIT_DATA_QUERY_KEY)) url.searchParams.set(INIT_DATA_QUERY_KEY, raw);
    return url.pathname + (url.search || '') + (url.hash || '');
  }

  const miniApp = !!refreshTelegramInitData();
  let csrfToken = '';
  if (miniApp) document.documentElement.classList.add('telegram-mini-app');

  function requestHeaders(values) {
    const headers = Object.assign({}, values || {});
    const initData = refreshTelegramInitData();
    if (initData) headers['X-Telegram-Init-Data'] = initData;
    if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
    return headers;
  }

  // "Старый интерфейс" target: served by backend → /ui/legacy/.
  const legacyUrl = '/ui/legacy/';

  // ---- real async HTTP layer over the actual endpoints --------------------
  class HttpError extends Error {
    constructor(status, message, path, retryAfterMs, code, payload) {
      super(message); this.name = 'HttpError'; this.status = status; this.path = path;
      this.retryAfterMs = Number(retryAfterMs || 0);
      this.code = code || '';
      this.payload = payload || null;
    }
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
          let code = '';
          let payload = null;
          try {
            payload = await res.json();
            detail = (payload && payload.error) || '';
            code = (payload && payload.code) || '';
          } catch (e) { /* non-json */ }
          const retryHeader = Number(res.headers.get('Retry-After') || 0);
          throw new HttpError(
            res.status, detail || res.statusText, path,
            retryHeader > 0 ? retryHeader * 1000 : 0,
            code, payload,
          );
        }
        return await res.json();
      } catch (e) {
        lastErr = e;
        if (e.name === 'AbortError') throw e;
        // Retrying client/auth/rate-limit responses cannot heal them and, for
        // 429, actively makes the overload worse. Retry only transport/5xx.
        if (e instanceof HttpError && e.status >= 400 && e.status < 500) throw e;
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
    if (!res.ok) {
      const retryHeader = Number(res.headers.get('Retry-After') || 0);
      throw new HttpError(
        res.status, (data && data.error) || res.statusText, path,
        retryHeader > 0 ? retryHeader * 1000 : 0,
        (data && data.code) || '', data,
      );
    }
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
    let sawFinal = false;
    let sawDone = false;
    let streamError = '';
    const dispatch = (evt, data) => {
      if (evt === 'thinking_start') { h.onThinkingStart && h.onThinkingStart(data); }
      else if (evt === 'thinking_delta') { h.onThinkingDelta && h.onThinkingDelta(String(data.text || '')); }
      else if (evt === 'status') { h.onStatus && h.onStatus(String(data.text || '')); }
      else if (evt === 'thinking_done') { h.onThinkingDone && h.onThinkingDone(String(data.text || '')); }
      else if (evt === 'final') { sawFinal = true; h.onFinal && h.onFinal(data); }
      else if (evt === 'error') {
        streamError = String(data.error || 'Не удалось получить ответ');
        h.onError && h.onError(streamError);
      }
      else if (evt === 'done') {
        sawDone = true;
        if (data && data.ok === false && !streamError) streamError = String(data.error || 'Ответ не был завершён');
        h.onDone && h.onDone(data);
      }
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
    if (streamError) return { ok: false, error: streamError, terminal: 'error' };
    if (!sawFinal || !sawDone) {
      return { ok: false, error: 'Соединение прервалось до получения ответа.', terminal: 'eof' };
    }
    return { ok: true, final: sawFinal, done: sawDone };
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
    miniappRegister: (body) => send('/api/auth/miniapp/register', 'POST', body || {}),
    legalTerms: (o) => getJSON('/api/legal/terms', o),
    authLogout: () => send('/api/auth/logout', 'POST', {}),
    authUsers: (o) => getJSON('/api/auth/users', o),
    authUserDetail: (id, o) => getJSON('/api/auth/users/' + encodeURIComponent(id), o),
    authUserRole: (id, role) => send('/api/auth/users/' + encodeURIComponent(id) + '/role', 'POST', { role }),
    authUserRevoke: (id) => send('/api/auth/users/' + encodeURIComponent(id) + '/revoke', 'POST', {}),
    authUserFeature: (id, feature, enabled) => send('/api/auth/users/' + encodeURIComponent(id) + '/features', 'POST', { feature, enabled }),
    authUserPermission: (id, capability, enabled) => send('/api/auth/users/' + encodeURIComponent(id) + '/permission', 'POST', { capability, enabled }),
    authUserStatus: (id, status) => send('/api/auth/users/' + encodeURIComponent(id) + '/status', 'POST', { status }),
    authUserSessions: (id, body) => send('/api/auth/users/' + encodeURIComponent(id) + '/sessions', 'POST', body || {}),
    authUserDelete: (id) => send('/api/auth/users/' + encodeURIComponent(id) + '/delete', 'POST', {}),
    supportTelemetry: (body) => send('/api/support/telemetry', 'POST', body || {}),
    supportPoll: (clientId) => send('/api/support/poll', 'POST', { client_id: clientId }),
    supportCommandAck: (clientId, commandId, status, error) => send('/api/support/commands/ack', 'POST', { client_id: clientId, command_id: commandId, status: status || 'done', error: error || '' }),
    supportScreenshotRespond: (body) => send('/api/support/screenshots/respond', 'POST', body || {}),
    ownerSupportMonitoring: (o) => getJSON('/api/owner/support/monitoring', o),
    ownerSupportUser: (id, o) => getJSON('/api/owner/support/users/' + encodeURIComponent(id), o),
    ownerSupportScreenshotRequest: (id, note, targetClientId) => send('/api/owner/support/users/' + encodeURIComponent(id) + '/screenshot', 'POST', { note: note || '', target_client_id: targetClientId || '' }),
    ownerSupportReload: (id, body) => send('/api/owner/support/users/' + encodeURIComponent(id) + '/reload', 'POST', body || {}),
    ownerSupportDeviceName: (id, deviceId, name) => send('/api/owner/support/users/' + encodeURIComponent(id) + '/device-name', 'POST', { device_id: deviceId, name }),
    ownerSupportScreenshotDelete: (requestId) => send('/api/owner/support/screenshots/' + encodeURIComponent(requestId) + '/delete', 'POST', {}),
    ownerSessions: (o) => getJSON('/api/owner/sessions', o),
    ownerGoogleMigration: (o) => getJSON('/api/owner/google-migration', o),
    ownerImpersonate: (userId, preset) => send('/api/owner/impersonate', 'POST', { user_id: userId, preset: preset || '' }),
    ownerImpersonateEnd: () => send('/api/owner/impersonate/end', 'POST', {}),
    ownerGoogleSecrets: (body) => send('/api/owner/google/secrets', 'POST', body || {}),
    googleAuthStatus: (o) => getJSON('/api/auth/google/status', o),
    googleAuthStart: (body) => send('/api/auth/google/start', 'POST', body || {}),
    ntConfirmStart: (body) => send('/api/auth/nt-confirm/start', 'POST', body || {}),
    ntConfirmStatus: (body) => send('/api/auth/nt-confirm/status', 'POST', body || {}),
    testAuthNtElevate: (body) => send('/api/auth/test/nt-elevate', 'POST', body || {}),
    testAuthStatus: (o) => getJSON('/api/auth/test/status', o),
    testAuthUsers: (o) => getJSON('/api/auth/test/users', o),
    testAuthVirtualUser: (body) => send('/api/auth/test/virtual-user', 'POST', body || {}),
    testAuthLogin: (userId) => send('/api/auth/test/login', 'POST', { user_id: userId }),
    testAuthGoogleLink: (body) => send('/api/auth/test/google-link', 'POST', body || {}),
    runtimeEnv: (o) => getJSON('/api/runtime/env', o),
    authMe: (o) => getJSON('/api/auth/me', o),
    authUxMode: (body) => send('/api/auth/ux-mode', 'POST', body || {}),
    authAvatarRefresh: () => send('/api/auth/avatar/refresh', 'POST', {}),
    billingPlans: (o) => getJSON('/api/billing/plans', o),
    billingMe: (o) => getJSON('/api/billing/me', o),
    billingDonate: (o) => getJSON('/api/billing/donate', o),
    billingAccessOptions: (o) => getJSON('/api/billing/access-options', o),
    billingPromoPreview: (body) => send('/api/billing/promo/preview', 'POST', body || {}),
    billingPromoRedeem: (body) => send('/api/billing/promo/redeem', 'POST', body || {}),
    billingSubscribe: (planId) => send('/api/billing/subscribe', 'POST', { plan_id: planId }),
    billingCheckout: (planId) => send('/api/billing/checkout', 'POST', { plan_id: planId }),
    billingPaymentRequest: (planId, note) => send('/api/billing/payment-request', 'POST', { plan_id: planId, note: note || '' }),
    ownerVouchers: (o) => getJSON('/api/owner/vouchers', o),
    ownerVoucherCreate: (body) => send('/api/owner/vouchers', 'POST', body || {}),
    ownerInviteCreate: (body) => send('/api/owner/invites', 'POST', body || {}),
    ownerInviteStatus: (id, status) => send('/api/owner/invites/' + encodeURIComponent(id) + '/status', 'POST', { status }),
    ownerInviteDelete: (id) => send('/api/owner/invites/' + encodeURIComponent(id) + '/delete', 'POST', {}),
    ownerInviteSend: (body) => send('/api/owner/invites/send', 'POST', body || {}),
    ownerPlans: (o) => getJSON('/api/owner/plans', o),
    ownerJournal: (query, o) => getJSON('/api/owner/journal' + (query ? ('?' + query) : ''), o),
    ownerPlanFeature: (planId, feature, enabled) => send('/api/owner/plans/feature', 'POST', { plan_id: planId, feature, enabled }),
    ownerPaymentGet: (o) => getJSON('/api/owner/payment', o),
    ownerPaymentSet: (body) => send('/api/owner/payment', 'POST', body || {}),
    ownerPaypalGet: (o) => getJSON('/api/owner/paypal', o),
    ownerPaypalSet: (body) => send('/api/owner/paypal', 'POST', body || {}),
    ownerPaypalEnsurePlans: () => send('/api/owner/paypal/plans', 'POST', {}),
    ownerGrant: (userId, planId, durationDays) => send('/api/owner/grant', 'POST', { user_id: userId, plan_id: planId, duration_days: durationDays }),
    ownerPaymentRequests: (o) => getJSON('/api/owner/payment-requests', o),
    ownerPaymentRequestResolve: (id, approve, durationDays) => send('/api/owner/payment-requests/resolve', 'POST', { request_id: id, approve, duration_days: durationDays }),
    bridgeSetup: (o) => getJSON('/api/bridge/setup', o),
    workspaces: (o) => getJSON('/api/workspaces', o),
    workspacePersonal: (body) => send('/api/workspaces/personal', 'POST', body || {}),
    workspaceSelect: (workspaceId) => send('/api/workspaces/select', 'POST', { workspace_id: workspaceId }),
    bridgeConnections: (o) => getJSON('/api/bridge/connections', o),
    bridgePairStart: (body) => send('/api/bridge/pair/start', 'POST', body || {}),
    bridgePairComplete: (body) => send('/api/bridge/pair/complete', 'POST', body || {}),
    bridgeConnectionRevoke: (id) => send('/api/bridge/connections/' + encodeURIComponent(id) + '/revoke', 'POST', {}),
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
    vitekStatus: (o) => getJSON('/api/vitek/status', o),
    vitekTimeWindows: (o) => getJSON('/api/vitek/time-windows', o),
    vitekScan: (notify) => send('/api/vitek/scan', 'POST', { notify: !!notify }),
    vitekRest: (body) => send('/api/vitek/rest', 'POST', body || {}),
    vitekResume: () => send('/api/vitek/resume', 'POST', {}),
    vitekTask: (body) => send('/api/vitek/tasks', 'POST', body || {}),
    vitekEvent: (body) => send('/api/vitek/events', 'POST', body || {}),
    vitekPlan: (body) => send('/api/vitek/plans', 'POST', body || {}),
    vitekUpdateTask: (id, body) => send('/api/vitek/tasks/' + encodeURIComponent(id), 'POST', body || {}),
    vitekIncidentDecision: (id, decision, note) => send('/api/vitek/incidents/' + encodeURIComponent(id) + '/decision', 'POST', { decision, note: note || '' }),
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
    createDemoBacktest: (body) => send('/api/demo-backtests', 'POST', body || {}),
    demoBacktestScenarios: (o) => getJSON('/api/demo-backtests/scenarios', o),
    practiceAccount: (o) => getJSON('/api/practice/account', o),
    practiceReport: (o) => getJSON('/api/practice/report', o),
    practiceCreateAccount: (body) => send('/api/practice/account', 'POST', body || {}),
    practiceOrder: (body) => send('/api/practice/orders', 'POST', body || {}),
    practiceClose: (body) => send('/api/practice/close', 'POST', body || {}),
    practiceTick: (body) => send('/api/practice/tick', 'POST', body || {}),
    communityFeed: (o) => getJSON('/api/community/feed', o),
    communityRatings: (o) => getJSON('/api/community/ratings', o),
    communityMessage: (body) => send('/api/community/message', 'POST', body || {}),
    communityPublishStrategy: (body) => send('/api/community/strategies', 'POST', body || {}),
    communityCopy: (body) => send('/api/community/copy', 'POST', body || {}),
    communityReport: (body) => send('/api/community/report', 'POST', body || {}),
    microLiveAccount: (o) => getJSON('/api/micro-live/account', o),
    microLiveAccept: (body) => send('/api/micro-live/accept-warnings', 'POST', body || {}),
    microLiveDeposit: (body) => send('/api/micro-live/deposit', 'POST', body || {}),
    microLiveTrade: (body) => send('/api/micro-live/trade', 'POST', body || {}),
    aiStarRatings: (o) => getJSON('/api/ai-lab/ratings', o),
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
    aiOrchestratorFulfillMessage: (conversationId, messageId, fulfillment) => send('/api/ai-lab/orchestrator/message/' + encodeURIComponent(messageId) + '/fulfillment', 'POST', { conversation_id: conversationId || 'default', fulfillment: fulfillment || 'done', fulfillment_source: 'owner' }),
    aiOrchestratorConversations: (o) => getJSON('/api/ai-lab/orchestrator/conversations', o),
    aiOrchestratorConversation: (id, q, o) => getJSON('/api/ai-lab/orchestrator/conversations/' + encodeURIComponent(id) + qs(q), o),
    aiOrchestratorCreateConversation: (title) => send('/api/ai-lab/orchestrator/conversations', 'POST', { title: title || '' }),
    aiOrchestratorAnnounceChartTask: (conversationId, payload) => send('/api/ai-lab/orchestrator/chart-task', 'POST', Object.assign({ conversation_id: conversationId || 'default' }, payload || {})),
    aiOrchestratorRenameConversation: (id, title) => send('/api/ai-lab/orchestrator/conversations/rename', 'POST', { conversation_id: id, title }),
    aiOrchestratorPinConversation: (id, pinned) => send('/api/ai-lab/orchestrator/conversations/pin', 'POST', { conversation_id: id, pinned: pinned }),
    aiOrchestratorSetConversationState: (id, state) => send('/api/ai-lab/orchestrator/conversations/state', 'POST', { conversation_id: id, state: state }),
    aiOrchestratorDeleteConversation: (id) => send('/api/ai-lab/orchestrator/conversations/delete', 'POST', { conversation_id: id }),
    notifications: (q, o) => getJSON('/api/notifications' + qs(q), o),
    notificationsAck: (body) => send('/api/notifications/ack', 'POST', body || {}),
    notificationsDelete: (body) => send('/api/notifications/delete', 'POST', body || {}),
    notificationsClear: (body) => send('/api/notifications/clear', 'POST', body || {}),
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
    aiResearches: (o) => getJSON('/api/ai-lab/researches', o),
    aiResearch: (id, o) => getJSON('/api/ai-lab/researches/' + encodeURIComponent(id), o),
    aiResearchCreate: (body) => send('/api/ai-lab/researches', 'POST', body || {}),
    aiResearchUpdate: (id, body) => send('/api/ai-lab/researches/' + encodeURIComponent(id), 'POST', body || {}),
  };

  async function refreshAuth() {
    if (isFile) return { auth: null };
    try {
      const auth = await http.authStatus({ retries: 0 });
      csrfToken = String(auth.csrf_token || '');
      document.documentElement.dataset.remoteRole = auth.role || 'read_only';
      document.documentElement.classList.add('authenticated');
      return { auth };
    } catch (error) {
      return { error };
    }
  }
  const authReady = refreshAuth();
  const config = { legacyUrl, offline: isFile };
  Object.defineProperties(config, {
    miniApp: { enumerable: true, get: () => !!refreshTelegramInitData() },
    telegramInitData: { enumerable: true, get: () => refreshTelegramInitData() },
  });
  window.API = { config, http, HttpError, authReady, refreshAuth, getTelegramInitData: refreshTelegramInitData, withTelegramContext };
})();
