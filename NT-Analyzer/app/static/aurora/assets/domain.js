/* Pure Aurora domain adapters and calculations. No DOM dependencies. */
(function (root) {
  'use strict';

  const PT_ZONE = 'America/Los_Angeles';
  const ACCOUNT_KEY = 'ntanalyzer:selected-account';

  function first() {
    for (let i = 0; i < arguments.length; i += 1) {
      if (arguments[i] !== undefined && arguments[i] !== null && arguments[i] !== '') return arguments[i];
    }
    return '';
  }

  function normalizeJobDetail(detail, summary) {
    detail = detail || {};
    summary = summary || {};
    const spec = detail.job || {};
    const result = detail.result || {};
    const context = result.context || {};
    const strategy = spec.strategy || context.strategy || {};
    const execution = spec.execution || context.execution || {};
    const risk = spec.risk_profile || context.risk_profile || {};
    return {
      detail,
      spec,
      result,
      context,
      strategy,
      execution,
      risk,
      metrics: result.metrics || detail.metrics || summary.metrics || {},
      instrument: first(spec.instrument, context.instrument && (context.instrument.full_name || context.instrument.name), context.instrument, summary.instrument),
      timeframe: spec.timeframe || context.timeframe || summary.timeframe || {},
      period: spec.period || context.period || summary.period || {},
      origin: spec.origin || summary.origin || {},
      className: first(strategy.class_name, context.strategy && context.strategy.class_name, summary.class_name, detail.job_id),
      status: first(detail.status, summary.status),
      reportNo: first(detail.report_no, summary.report_no),
      favorite: !!(detail.favorite || summary.favorite),
      parameters: strategy.parameters || strategy.final_parameters || (context.strategy && context.strategy.final_parameters) || {},
      warnings: result.verification_warnings || [],
      artifacts: result.artifacts || {},
    };
  }

  function tradePnl(trade) {
    trade = trade || {};
    const value = first(trade.pnl_currency, trade.pnl, trade.realized_pnl, 0);
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
  }

  function tradeTime(trade, kind) {
    trade = trade || {};
    return first(trade[kind + '_time_utc'], trade[kind + '_time'], trade.timestamp_utc, trade.time);
  }

  function periodDays(period) {
    period = period || {};
    const start = Date.parse(period.from_utc || '');
    const end = Date.parse(period.to_utc || '');
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
    return Math.max(1, (end - start) / 86400000);
  }

  function frequencyAssessment(tradeCount, period) {
    const trades = Math.max(0, Number(tradeCount) || 0);
    const days = periodDays(period);
    const weeks = days == null ? null : Math.max(1 / 7, days / 7);
    const perWeek = weeks == null ? null : trades / weeks;
    if (perWeek == null) return {
      key: 'unknown', label: 'частота неизвестна', trades_per_week: null,
      risk_expectation: 'не определён', profit_expectation: 'не определена',
      explanation: 'Нужен корректный период отчёта.',
    };
    if (perWeek < 2) return {
      key: 'rare', label: 'редко', trades_per_week: perWeek, risk_expectation: 'низкий',
      profit_expectation: 'высокая', explanation: 'Менее 2 сделок в неделю. Требуется высокая прибыль на сделку и устойчивый результат.',
    };
    if (perWeek <= 7) return {
      key: 'normal', label: 'нормально', trades_per_week: perWeek, risk_expectation: 'средний',
      profit_expectation: 'хорошая', explanation: '2–7 сделок в неделю. Ожидаются хорошая прибыль и средний контролируемый риск.',
    };
    return {
      key: 'frequent', label: 'часто', trades_per_week: perWeek, risk_expectation: 'умеренно повышенный',
      profit_expectation: 'минимально допустимая', explanation: 'Более 7 сделок в неделю. Допустима меньшая прибыль на сделку, но требуется контроль переторговки.',
    };
  }

  function confidenceAssessment(tradeCount, period, metrics) {
    const trades = Math.max(0, Math.trunc(Number(tradeCount) || 0));
    if (!trades) return { score: 0, level: 'insufficient', label: 'нет данных', reasons: ['нет завершённых сделок'] };
    let score = trades >= 200 ? 90 : trades >= 100 ? 82 : trades >= 50 ? 72 : trades >= 20 ? 58 : trades >= 10 ? 42 : trades >= 5 ? 28 : 14;
    const reasons = [`размер выборки: ${trades} сделок`];
    const days = periodDays(period);
    if (days == null) { score -= 8; reasons.push('период отчёта не определён'); }
    else {
      const weeks = days / 7;
      if (weeks >= 26) score += 8; else if (weeks >= 12) score += 5; else if (weeks >= 4) score += 2; else if (weeks < 2) score -= 10;
      reasons.push(`покрытие периода: ${Math.round(days)} дней`);
    }
    metrics = metrics || {};
    const complete = ['winning_pct', 'profit_factor', 'max_drawdown'].filter(key => metrics[key] != null).length;
    if (complete === 3) { score += 3; reasons.push('основные метрики заполнены'); }
    else if (!complete) { score -= 5; reasons.push('основные метрики отсутствуют'); }
    if (trades < 5) score = Math.min(score, 18); else if (trades < 10) score = Math.min(score, 28); else if (trades < 20) score = Math.min(score, 42); else if (trades < 50) score = Math.min(score, 65);
    score = Math.max(0, Math.min(100, Math.round(score)));
    const level = score >= 75 ? 'high' : score >= 45 ? 'medium' : score >= 25 ? 'low' : 'very_low';
    const labels = { high: 'высокое', medium: 'среднее', low: 'низкое', very_low: 'очень низкое' };
    return { score, level, label: labels[level], reasons };
  }

  function assessReport(tradeCount, period, metrics) {
    return {
      frequency: frequencyAssessment(tradeCount, period),
      confidence: confidenceAssessment(tradeCount, period, metrics),
    };
  }

  function metricTone(kind, value, context) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 'muted';
    if (kind === 'pnl') return number > 0 ? 'pos' : number < 0 ? 'neg' : 'muted';
    if (kind === 'win') return number >= 55 ? 'pos' : number >= 45 ? 'warn' : 'neg';
    if (kind === 'pf') return number >= 1.3 ? 'pos' : number >= 1 ? 'warn' : 'neg';
    if (kind === 'confidence') return number >= 75 ? 'pos' : number >= 45 ? 'info' : number >= 25 ? 'warn' : 'neg';
    if (kind === 'trades') {
      const frequency = frequencyAssessment(number, context || {});
      return frequency.key === 'normal' ? 'pos' : frequency.key === 'unknown' ? 'muted' : 'warn';
    }
    return 'muted';
  }

  function tradingSeries(strategies) {
    const byDate = {};
    (strategies || []).forEach(strategy => {
      (strategy.daily || []).forEach(day => {
        const value = Number(day.pnl || 0);
        byDate[day.date] = (byDate[day.date] || 0) + (Number.isFinite(value) ? value : 0);
      });
    });
    let cumulative = 0;
    let peak = 0;
    return Object.keys(byDate).sort().map(date => {
      cumulative += byDate[date];
      peak = Math.max(peak, cumulative);
      return {
        date,
        tradingPnl: Math.round(byDate[date] * 100) / 100,
        cumulativeTradingPnl: Math.round(cumulative * 100) / 100,
        drawdown: Math.round((cumulative - peak) * 100) / 100,
      };
    });
  }

  function ptParts(date) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: PT_ZONE,
      weekday: 'short',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).formatToParts(date);
    const get = type => parts.find(p => p.type === type).value;
    let hour = Number(get('hour'));
    if (hour === 24) hour = 0;
    return {
      weekday: get('weekday'), year: Number(get('year')), month: Number(get('month')),
      day: Number(get('day')), hour, minute: Number(get('minute')), second: Number(get('second')),
    };
  }

  function marketPhaseAt(date) {
    const p = ptParts(date);
    const minute = p.hour * 60 + p.minute;
    const pauseStart = 14 * 60;
    const reopen = 15 * 60;
    if (p.weekday === 'Sat') return 'weekend';
    if (p.weekday === 'Sun') return minute >= reopen ? 'open' : 'weekend';
    if (p.weekday === 'Fri' && minute >= pauseStart) return 'weekend';
    if (minute >= pauseStart && minute < reopen) return 'maintenance';
    return 'open';
  }

  function nextMarketTransition(date) {
    const phase = marketPhaseAt(date);
    const start = date.getTime();
    const coarse = 30 * 60 * 1000;
    let upper = start + coarse;
    const limit = start + 8 * 24 * 60 * 60 * 1000;
    while (upper <= limit && marketPhaseAt(new Date(upper)) === phase) upper += coarse;
    if (upper > limit) return null;
    let lower = Math.max(start, upper - coarse);
    while (upper - lower > 60 * 1000) {
      const middle = lower + Math.floor((upper - lower) / (2 * 60 * 1000)) * 60 * 1000;
      if (marketPhaseAt(new Date(middle)) === phase) lower = middle + 60 * 1000;
      else upper = middle;
    }
    const transition = new Date(upper);
    transition.setUTCSeconds(0, 0);
    return transition;
  }

  function durationLabel(milliseconds) {
    const totalMinutes = Math.max(0, Math.ceil(milliseconds / 60000));
    const days = Math.floor(totalMinutes / 1440);
    const hours = Math.floor((totalMinutes % 1440) / 60);
    const minutes = totalMinutes % 60;
    const parts = [];
    if (days) parts.push(days + ' д');
    if (hours) parts.push(hours + ' ч');
    if (minutes || !parts.length) parts.push(minutes + ' мин');
    return parts.join(' ');
  }

  function marketStatus(date) {
    date = date || new Date();
    const phase = marketPhaseAt(date);
    const transition = nextMarketTransition(date);
    const remaining = transition ? durationLabel(transition.getTime() - date.getTime()) : '';
    const labels = {
      open: { state: 'ok', label: 'Рынок открыт', action: 'до паузы/закрытия' },
      maintenance: { state: 'warn', label: 'Техпауза CME', action: 'до открытия' },
      weekend: { state: 'off', label: 'Рынок закрыт', action: 'до открытия' },
    };
    const base = labels[phase];
    return {
      phase,
      state: base.state,
      label: base.label + (remaining ? ' · ' + remaining : ''),
      title: 'CME futures, Pacific Time · ' + base.action + (remaining ? ' ' + remaining : ''),
      transition: transition ? transition.toISOString() : null,
    };
  }

  function selectAccount(accounts, preferred) {
    accounts = accounts || [];
    const allowed = accounts.filter(a => a && a.account_name);
    const found = allowed.find(a => a.account_name === preferred);
    return found || allowed.find(a => !a.is_system && a.is_selectable_for_online !== false) || allowed[0] || null;
  }

  function hhmmToMinutes(value) {
    const raw = Number(value);
    if (!Number.isFinite(raw)) return null;
    const hour = Math.floor(raw / 100);
    const minute = raw % 100;
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59) return null;
    return hour * 60 + minute;
  }

  function tradeWindowState(tradeWindow, date) {
    tradeWindow = tradeWindow || {};
    const windows = Array.isArray(tradeWindow.windows) ? tradeWindow.windows : [];
    if (tradeWindow.use_24h) return { kind: 'open', label: '24 часа', inWindow: true };
    if (!windows.length) return { kind: 'unspecified', label: 'окно не задано', inWindow: null };
    const p = ptParts(date || new Date());
    const now = p.hour * 60 + p.minute;
    const active = windows.some(window => {
      const start = hhmmToMinutes(window.start);
      const end = hhmmToMinutes(window.end);
      if (start == null || end == null) return false;
      return start <= end ? now >= start && now <= end : now >= start || now <= end;
    });
    return { kind: active ? 'open' : 'closed', label: active ? 'в торговом окне' : 'вне торгового окна', inWindow: active };
  }

  function normalizeRuntimeStrategy(row, date) {
    row = row || {};
    const runtime = row.runtime || {};
    const enabled = row.runtime_enabled !== undefined ? !!row.runtime_enabled : !!runtime.enabled;
    const managed = !!row.registry_status || String(row.source || '').includes('registry');
    const windowState = tradeWindowState(row.trade_window, date);
    return {
      raw: row,
      runtime,
      runtimeInstanceId: first(row.runtime_instance_id, runtime.runtime_instance_id),
      strategyId: first(row.strategy_id, runtime.strategy_id),
      className: first(row.display_key, runtime.strategy_class, row.strategy_class),
      name: first(row.display_name, runtime.strategy_name, row.strategy_id),
      instrument: first(runtime.instrument, row.instrument),
      accountName: first(row.account_name, runtime.account_name),
      accountMode: first(row.account_mode, runtime.account_mode),
      timeframe: first(runtime.timeframe, row.timeframe),
      state: first(runtime.state, row.state),
      position: first(runtime.position_market_position, runtime.market_position, 'Flat'),
      quantity: Number(first(runtime.position_qty, 0)) || 0,
      realizedPnl: Number(first(runtime.realized_pnl, row.realized_pnl, 0)) || 0,
      unrealizedPnl: Number(first(runtime.unrealized_pnl, row.unrealized_pnl, 0)) || 0,
      sessionTrades: Number(first(runtime.session_trades_count, 0)) || 0,
      enabled,
      detected: row.runtime_detected !== false,
      hidden: !!row.display_hidden,
      managed,
      external: !managed,
      registryStatus: first(row.registry_status, 'runtime-only'),
      paramsOk: row.params_ok !== false,
      parameterMismatches: (row.params_check && row.params_check.mismatches) || [],
      warnings: row.runtime_warnings || [],
      errors: row.runtime_errors || [],
      tradeWindowLabel: first(row.trade_window_pt, windowState.label),
      windowState,
    };
  }

  function strategyOperationalState(strategy, market) {
    market = market || marketStatus(new Date());
    if (strategy.hidden) return { kind: 'hidden', label: 'скрыта', severity: 'muted' };
    if (strategy.external) return { kind: 'external', label: 'внешняя', severity: 'warn' };
    if (!strategy.paramsOk) return { kind: 'mismatch', label: 'параметры не совпадают', severity: 'bad' };
    if (!strategy.detected) return { kind: 'missing', label: 'не найдена в runtime', severity: 'bad' };
    if (!strategy.enabled) {
      const expected = market.phase === 'open' && !['archived', 'rejected'].includes(strategy.registryStatus);
      return { kind: expected ? 'disabled_required' : 'disabled', label: expected ? 'требуется включить' : 'выключена', severity: expected ? 'bad' : 'muted' };
    }
    if (strategy.windowState.inWindow === false) return { kind: 'standby', label: 'включена · ждёт окно', severity: 'info' };
    return { kind: 'working', label: strategy.windowState.inWindow ? 'работает в окне' : 'включена', severity: 'ok' };
  }

  function mergeAiRunStatus(statusDoc, currentDoc) {
    const run = statusDoc && statusDoc.run;
    const experiment = currentDoc && currentDoc.current;
    if (run) return Object.assign({}, experiment || {}, run, { current: experiment || null });
    if (experiment) return Object.assign({ active: true }, experiment);
    return null;
  }

  function aiRunIsActive(run) {
    if (!run) return false;
    const state = String(run.state || run.status || '').toLowerCase();
    if (['completed', 'done', 'failed', 'cancelled', 'canceled', 'stopped', 'idle'].includes(state)) return false;
    if (run.cancelled || run.canceled) return false;
    return !!(run.active || run.is_running || state === 'running' || run.run_id || run.experiment_id);
  }

  root.AuroraDomain = {
    PT_ZONE,
    ACCOUNT_KEY,
    normalizeJobDetail,
    tradePnl,
    tradeTime,
    periodDays,
    frequencyAssessment,
    confidenceAssessment,
    assessReport,
    metricTone,
    tradingSeries,
    ptParts,
    marketPhaseAt,
    nextMarketTransition,
    marketStatus,
    selectAccount,
    tradeWindowState,
    normalizeRuntimeStrategy,
    strategyOperationalState,
    mergeAiRunStatus,
    aiRunIsActive,
  };
})(typeof window !== 'undefined' ? window : globalThis);
