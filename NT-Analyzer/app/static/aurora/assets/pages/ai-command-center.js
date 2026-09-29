/* Agent World presentation. All authority, scope, execution and data stay server-side. */
(function (root) {
  'use strict';
  // Five planned views (prototype B) and one separate view for work that was not in the plan.
  const TABS = ['overview', 'agents', 'models', 'research', 'memory', 'work'];
  const DOMAINS = Object.freeze({
    personas: { title: 'Персоны', description: 'Имя, характер, голос и лицо агента. Персона не выбирает модель и не даёт дополнительных прав.', create: 'Создать персону' },
    decisions: { title: 'Решения', description: 'Предложения с доказательствами и независимая проверка Court. Вердикт не исполняет сделки и не выдаёт прав.', create: 'Новое решение' },
    memory: { title: 'Память', description: 'Что запомнили агенты: источник, назначение и срок хранения. Продвинуть можно только подтверждённую запись.', create: 'Добавить запись' },
    projects: { title: 'Проекты стратегий', description: 'Стратегии, их версии и параметры. Запуск бэктеста остаётся в разделе «Бэктест».', create: 'Создать проект' },
    routines: { title: 'Рутины', description: 'Повторяющаяся работа, которую предложили агенты. Принятая рутина сама по себе не запускается.', create: 'Предложить рутину' },
    calendar: { title: 'Календарь', description: 'События рабочего пространства. Время вводится по вашим часам и хранится в UTC.', create: 'Добавить событие' },
    publications: { title: 'Публикации', description: 'Проверенный результат можно показать в SF Social: сначала предпросмотр, затем отдельное подтверждение. Личная память и сырые ответы не публикуются.', create: 'Подготовить публикацию' },
    models: { title: 'Модели', description: 'Подключения к языковым моделям. Модель — исполнитель; персона и учётная запись провайдера настраиваются отдельно.', create: 'Подключить модель' },
    external_agents: { title: 'Внешние агенты', description: 'Самостоятельные агенты, подключённые по протоколу A2A. Это не модель и не персона; возможности подтверждает сервер.', create: 'Добавить внешнего агента' },
    model_tasks: { title: 'История ответов моделей', description: 'Фактические ответы и их проверки. Неизвестная стоимость не означает нулевую.', create: '' },
    tasks: { title: 'Действия задачи', description: 'Изменение выполняет сервер после повторной проверки прав и состояния.', create: '' },
    experiments: { title: 'Сравнение моделей', description: 'Одно задание для 2–3 моделей и сравнение по фактическим ответам, а не по самооценке.', create: 'Сравнить модели' },
    automation: { title: 'Автоматизация', description: 'Для автоматического запуска нужны три отдельных условия: разрешение на автоматизацию, согласие на конкретное расписание и бюджет.', create: '' },
    router: { title: 'Выбор модели', description: 'Какая модель лучше подходит для конкретной задачи. Предпросмотр ничего не запускает; новый запуск требует отдельного разрешения.', create: '' },
    system: { title: 'Состояние системы', description: 'Какие механизмы включены и доступны в этом рабочем пространстве. Просмотр ничего не меняет.', create: '' },
  });
  // One grouping for the page launcher and the in-drawer navigation, so a tool
  // has the same name and neighbours wherever it is opened from.
  const DOMAIN_GROUPS = Object.freeze([
    ['Работа', ['automation', 'routines', 'calendar', 'decisions']],
    ['Команда', ['personas', 'models', 'external_agents', 'experiments', 'router']],
    ['Знания', ['memory', 'projects', 'publications']],
  ]);
  // Domain lists a tab reads; they load only when that tab is opened.
  const TAB_DATA = Object.freeze({ models: ['models'], research: ['lab_research'], memory: ['memory', 'knowledge'] });
  // The owner's team scheme (docs/product/AI_CENTER_OWNER_RULES.md, section 4). A slot
  // shows the persona explicitly assigned to that job; an empty slot stays empty.
  const avatarKeyOf = agent => String(agent?.avatar_key || '').toLowerCase();
  // The application role the server actually sends. It used to be read as
  // `role_key`, a field no projection produces, so an agent with a real role
  // - the owner's Толик and Иван among them - sat outside the hierarchy.
  const roleKeyOf = agent => String(agent?.application_role || agent?.role_key || '').toLowerCase();
  // `key` is the place a Persona is hired into (app/ai_control_center/team_roles.py);
  // `name` is the suggested name offered when hiring, from the owner's scheme.
  const placed = (key, extra) => agent => agent.team_role === key || Boolean(extra && extra(agent));
  const TEAM_SLOTS = Object.freeze([
    { key: 'deputy', dept: 'lead', lead: true, title: 'Заместитель', note: 'ваша правая рука', name: 'Витёк', match: placed('deputy', agent => agent.main_assistant === true || roleKeyOf(agent) === 'deputy' || ['vitek', 'manager'].includes(avatarKeyOf(agent))) },
    { key: 'secretary', dept: 'staff', title: 'Секретарь', note: 'история и действия системы', name: 'Лера', match: placed('secretary', agent => roleKeyOf(agent) === 'secretary') },
    { key: 'researcher', dept: 'dev', title: 'Исследователь', note: 'гипотезы, режимы рынка', name: 'Сева', match: placed('researcher', agent => roleKeyOf(agent) === 'researcher') },
    { key: 'quant_analyst', dept: 'dev', title: 'Квант-аналитик', note: 'статистика, признаки', name: 'Толик', match: placed('quant_analyst', agent => roleKeyOf(agent) === 'quant_analyst') },
    { key: 'ninjascript_coder', dept: 'dev', title: 'Кодер NinjaScript', note: 'код стратегии', name: 'Артём', match: placed('ninjascript_coder', agent => roleKeyOf(agent) === 'ninjascript_coder') },
    { key: 'code_reviewer', dept: 'dev', title: 'Ревьюер кода', note: 'compile, качество', name: 'Дина', match: placed('code_reviewer', agent => roleKeyOf(agent) === 'code_reviewer') },
    { key: 'backtester', dept: 'dev', title: 'Бэктестер', note: 'Strategy Analyzer', name: 'Гоша', match: placed('backtester', agent => roleKeyOf(agent) === 'backtest_researcher') },
    { key: 'optimizer', dept: 'dev', title: 'Оптимизатор', note: 'walk-forward, стресс', name: 'Паша', match: placed('optimizer', agent => roleKeyOf(agent) === 'optimizer') },
    { key: 'accountant', dept: 'ops', title: 'Бухгалтер', note: 'P&L, комиссии, учёт', name: 'Марина', match: placed('accountant', agent => roleKeyOf(agent) === 'accountant' || avatarKeyOf(agent) === 'marina') },
    { key: 'news_analyst', dept: 'ops', title: 'Новостной аналитик', note: 'календарь, заголовки', name: 'Никита', match: placed('news_analyst', agent => roleKeyOf(agent) === 'news_analyst' || avatarKeyOf(agent) === 'nikita') },
    { key: 'chart_operator', dept: 'ops', title: 'Оператор графиков', note: 'рабочий стол, TopstepX', name: 'Иван', match: placed('chart_operator', agent => roleKeyOf(agent) === 'chart_researcher' || avatarKeyOf(agent) === 'ivan') },
    { key: 'judge_statistics', dept: 'judges', title: 'Судья статистики', note: 'оверфит, значимость', name: 'Судья статистики', match: placed('judge_statistics', agent => roleKeyOf(agent) === 'judge_statistics') },
    { key: 'judge_risk', dept: 'judges', title: 'Судья риска', note: 'просадка, лимиты', name: 'Судья риска', match: placed('judge_risk', agent => roleKeyOf(agent) === 'judge_risk') },
    { key: 'chief_arbiter', dept: 'judges', title: 'Главный арбитр', note: 'финальный вердикт', name: 'Главный арбитр', match: placed('chief_arbiter', agent => roleKeyOf(agent) === 'chief_arbiter') },
  ]);
  // A retired or archived Persona has left the team.
  const RETIRED_PERSONA = new Set(['retired', 'archived']);
  const TEAM_DEPTS = Object.freeze([['dev', 'Разработка стратегий', 'идея → код → тест'], ['ops', 'Операции', 'внутри приложения'], ['judges', 'Судьи', 'спорные решения']]);
  const BUSY_STATES = new Set(['running', 'working', 'executing', 'busy', 'in_progress']);
  const OK_STATES = new Set(['verified_automatically', 'completed', 'accepted', 'succeeded']);
  const BAD_STATES = new Set(['failed', 'rejected', 'error', 'blocked']);
  // An external agent reports no model of its own; it is not a model to rate.
  const MODEL_EXCLUDED = new Set(['unknown / externally managed']);
  // The owner is asked only about real work that waits on them or went wrong.
  // Test checks of the system (synthetic runs, diagnostic task classes) settle
  // on their own and never reach the owner's questions.
  const DIAGNOSTIC_CLASSES = new Set(['json_arithmetic', 'connection_exact', 'extract_facts']);
  const ownerFacing = task => task?.synthetic !== true && !DIAGNOSTIC_CLASSES.has(String(task?.task_class || ''));
  const MODEL_WORDS = Object.freeze({ gpt: 'GPT', deepseek: 'DeepSeek', claude: 'Claude', gemini: 'Gemini', grok: 'Grok', llama: 'Llama', qwen: 'Qwen', mistral: 'Mistral', openai: 'OpenAI', sonnet: 'Sonnet', opus: 'Opus', haiku: 'Haiku' });
  const prettyModel = id => String(id || 'Модель').split('/').pop().split(/[-_\s]+/).filter(Boolean)
    .map(word => MODEL_WORDS[word.toLowerCase()] || (/^v?\d/i.test(word) ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1))).join(' ');
  const PROVIDER_LABELS = Object.freeze({ deepseek: 'DeepSeek', openai: 'OpenAI', anthropic: 'Anthropic', google: 'Google', xai: 'xAI', mistral: 'Mistral', openrouter: 'OpenRouter', lmstudio: 'LM Studio', ollama: 'Ollama' });
  const providerLabel = key => PROVIDER_LABELS[String(key || '').toLowerCase()] || String(key || 'провайдер не указан');
  const rateTone = rate => rate == null ? 'none' : rate >= 0.9 ? 'good' : rate >= 0.75 ? 'mid' : 'low';
  const AW_ICONS = Object.freeze({
    flask: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/><path d="M7.5 15h9"/>',
    users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5c1.9.6 3.1 2.4 3.5 5.5"/>',
    trophy: '<path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M8.5 20h7M10 17h4"/>',
    archive: '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11h14V8M10 12h4"/>',
    brain: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a3 3 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>',
    alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    gauge: '<circle cx="12" cy="12" r="9"/><path d="M12 12l4-3"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    goal: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
  });
  const MEMORY_CLASS = Object.freeze({ verified_lesson: 'Проверенный урок', working_note: 'Рабочая заметка', fact: 'Факт', preference: 'Предпочтение' });
  const ACTION_LABELS = Object.freeze({ verify: 'Проверить агента', disable: 'Выключить подключение', rotate: 'Заменить секрет', preview: 'Предпросмотр выбора', apply: 'Разрешить новый запуск', seed_preview: 'Создать учебные записи Preview', create: 'Создать', connect: 'Подключить', bind_existing: 'Связать Local-подключение', update: 'Изменить', activate: 'Активировать', suspend: 'Приостановить', archive: 'В архив', promote: 'Продвинуть', publish_to_workspace: 'Опубликовать в workspace', propose_consensus: 'Собрать решение по вкладам', suggest_routine: 'Предложить по результатам', prepare: 'Подготовить снимок', publish: 'Опубликовать в SF Social', revoke: 'Отозвать разрешение', propose: 'Проверить расписание', enable: 'Включить по расписанию', commission: 'Новое поручение Координатору', preview_commission: 'Проверить план делегирования', approve_commission: 'Разрешить этот план', reconcile: 'Проверить продолжение', version: 'Новая версия', accept: 'Принять', dismiss: 'Отклонить', review: 'Проверить через Court', review_result: 'Проверить полученный результат', withdraw: 'Отозвать решение', test: 'Проверить соединение', task: 'Первое задание', disconnect: 'Отключить', cancel: 'Отменить задачу', retry: 'Новая безопасная попытка', handoff: 'Передать факты агенту', open_chat: 'Открыть ручной разбор в SF Chat' });
  const STATUS = {
    verifying: ['Проверяется', 'info'], degraded: ['Требует внимания', 'warning'], running: ['В работе', 'good'], working: ['В работе', 'good'], active: ['Активен', 'good'], healthy: ['Работает', 'good'], succeeded: ['Завершено', 'good'], completed: ['Завершено', 'good'], verified: ['Проверено', 'good'], passed: ['Проверено', 'good'], accepted: ['Принято', 'good'], submitted: ['Вклад записан', 'info'],
    planned: ['Запланировано', 'neutral'], ready: ['В очереди', 'neutral'], queued: ['В очереди', 'neutral'], waiting: ['Ожидает', 'neutral'], pending: ['Ожидает', 'neutral'], free: ['Свободен', 'neutral'], available: ['Свободен', 'neutral'], idle: ['Свободен', 'neutral'],
    review: ['Нужна проверка', 'review'], awaiting_owner: ['Решение владельца', 'review'], approval_required: ['Нужно подтверждение', 'review'], court: ['Разбор Court', 'review'],
    blocked: ['Заблокировано', 'warning'], paused: ['На паузе', 'warning'], warning: ['Внимание', 'warning'],
    failed: ['Ошибка', 'error'], rejected: ['Отклонено', 'error'], error: ['Ошибка', 'error'], cancelled: ['Отменено', 'neutral'],
    disabled: ['Выключено', 'neutral'], new: ['NEW · мало данных', 'neutral'], insufficient: ['NEW · мало данных', 'neutral'], info: ['Событие', 'info'],
    draft: ['Черновик', 'neutral'], proposed: ['Предложено', 'review'], approved: ['Одобрено', 'good'], superseded: ['Заменено', 'neutral'], promoted: ['Подтверждено', 'good'], revoked: ['Отозвано', 'warning'], expired: ['Истёк срок', 'neutral'], archived: ['В архиве', 'neutral'], retired: ['Выведено из работы', 'neutral'], suspended: ['Приостановлено', 'warning'], connected: ['Подключено', 'good'], disconnected: ['Отключено', 'neutral'], scheduled: ['Запланировано', 'neutral'], cancelled_requested: ['Отмена запрошена', 'warning'], cancel_requested: ['Отмена запрошена', 'warning'], review_required: ['Нужна проверка', 'review'], external_blocked: ['Внешний blocker', 'warning'], unavailable: ['Недоступно', 'warning'], exhausted: ['Лимит исчерпан', 'warning'], approve: ['За', 'good'], reject: ['Против', 'error'], abstain: ['Воздержался', 'neutral'],
  };
  // Presentation grouping over task_presentation's display states. This is a
  // view of the one server-side computation, never a second opinion: phaseOf
  // reads display_status and nothing else.
  const PHASE_BY_DISPLAY = Object.freeze({
    queued: 'executing', running: 'executing', waiting_result: 'executing', planned: 'executing',
    awaiting_review: 'awaiting_review', blocked: 'awaiting_decision',
    result_received: 'result_unconfirmed',
    completed: 'done', verified_automatically: 'done',
    failed: 'failed', rejected: 'failed', cancelled: 'cancelled',
  });
  const PHASE_LABELS = Object.freeze({ executing: 'Выполняется', awaiting_review: 'Ожидает проверки', awaiting_decision: 'Ожидает решения', result_unconfirmed: 'Результат не принят', done: 'Завершено', failed: 'Ошибка', cancelled: 'Отменено' });
  const OPEN_PHASES = Object.freeze(['awaiting_review', 'awaiting_decision']);
  const ATTENTION_PHASES = Object.freeze(['awaiting_review', 'awaiting_decision', 'failed']);
  const AVATAR_KEYS = Object.freeze(['vitek', 'manager', 'marina', 'tolik', 'nikita', 'ivan']);
  const AVATAR_LABELS = Object.freeze({ vitek: 'Виктор', manager: 'Олег', marina: 'Марина', tolik: 'Толик', nikita: 'Никита', ivan: 'Иван' });
  const PERSONA_VOICE_PROFILES = Object.freeze({ ...AVATAR_LABELS, deputy: 'Заместитель', secretary: 'Секретарь' });
  const PERSONA_DEFAULTS = Object.freeze({ voice_profile_id: '', voice_mode: 'browser', voice_speed: 1, voice_language: 'ru-RU', animation_mode: 'auto', expression_preset: 'neutral', lip_sync_mode: 'auto' });
  const RUBRIC_LABELS = Object.freeze({ connection_exact: 'Проверка соединения', json_arithmetic: 'Арифметика · JSON', extract_facts: 'Извлечение фактов', assistant_response: 'Ответ помощника · ручная проверка', court_vote: 'Голос Court', backtest_spec: 'План бэктеста', chart_spec: 'План графика', application_execution: 'Соответствие результата приложения', decision_outcome: 'Исход одобренного решения', ninjatrader_historical_backtest: 'Исторический бэктест NinjaTrader', desktop_chart_snapshot: 'Снимок графика Рабочего стола' });

  const phaseOf = task => PHASE_BY_DISPLAY[String(task && (task.display_status || task.status) || '').toLowerCase()] || 'awaiting_decision';
  const phaseLabel = task => PHASE_LABELS[phaseOf(task)] || 'Состояние не определено';
  // A machine key is lowercase ASCII with underscores. The NinjaTrader and
  // Desktop adapters already send a written stage, and replacing that with a
  // placeholder would be a step backwards, so written text passes through.
  const machineKey = value => /^[a-z][a-z0-9_]*$/.test(String(value || ''));
  const rubricLabel = value => {
    const key = String(value || '');
    if (Object.prototype.hasOwnProperty.call(RUBRIC_LABELS, key)) return RUBRIC_LABELS[key];
    return machineKey(key) ? '' : key;
  };
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const rows = value => Array.isArray(value) ? value : [];
  const items = value => Array.isArray(value) ? value : rows(value && (value.items || value.tasks || value.agents));
  const number = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value) : null;
  const count = value => number(value) == null ? '—' : Math.max(0, Math.floor(number(value))).toLocaleString('ru-RU');
  const pct = value => number(value) == null ? '—' : Math.min(100, Math.max(0, number(value))).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + '%';
  const date = (value, compact) => {
    const parsed = new Date(value || '');
    return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString('ru-RU', compact ? { hour: '2-digit', minute: '2-digit' } : { dateStyle: 'short', timeStyle: 'short' }) : '—';
  };
  const statusMeta = value => STATUS[String(value || '').toLowerCase()] || ['Статус не указан', 'neutral'];
  const badge = value => { const meta = statusMeta(value); return `<span class="aw-status aw-${meta[1]}">${esc(meta[0])}</span>`; };
  const taskId = row => String(row && (row.id || row.task_id) || '');
  const taskState = row => row?.display_status || row?.status || '';
  const taskTitle = row => row?.display_title || row?.title || 'Задача';
  const taskClass = row => row?.task_class_label || ({ json_arithmetic: 'Диагностика: арифметика JSON', connection_exact: 'Проверка подключения', extract_facts: 'Передача фактов', backtest_spec: 'Бэктест', chart_spec: 'Снимок графика', court_vote: 'Заключение Court' }[row?.task_class] || 'Другой класс · см. детали');
  // Both vocabularies: Codex's coarse stages plus the concrete stage values
  // model_service emits. Text already written for a reader passes through; only
  // an unrecognised machine key falls back to the neutral pointer.
  const STAGE_LABELS = Object.freeze({
    work: 'Выполнение', evaluation: 'Автоматическая проверка', planning: 'Планирование', review: 'Проверка',
    model: 'Ответ модели', application: 'Результат приложения', failed: 'Ошибка исполнения', completed: 'Результат получен',
    awaiting_provider: 'Ожидает ответа модели', provider_receipt: 'Ответ модели получен',
    awaiting_application: 'Ожидает результата приложения', application_verified: 'Результат приложения проверен',
    application_failed: 'Приложение вернуло ошибку', application_cancel_requested: 'Запрошена отмена в приложении',
  });
  const stageName = value => {
    const key = String(value || '');
    if (Object.prototype.hasOwnProperty.call(STAGE_LABELS, key)) return STAGE_LABELS[key];
    if (!key) return '—';
    return machineKey(key) ? 'См. состояние задачи' : key;
  };
  const taskBadge = row => row?.display_status_label ? `<span class="aw-status aw-${statusMeta(taskState(row))[1]}">${esc(row.display_status_label)}</span>` : badge(taskState(row));
  Object.assign(STATUS, { awaiting_review: ['Ожидает вашей проверки', 'review'], waiting_result: ['Ожидается результат', 'info'], completed: ['Проверка завершена', 'good'] });
  const agentId = row => String(row && (row.id || row.persona_id || row.agent_id) || '');
  const name = row => typeof row === 'string' ? row : String(row && (row.display_name || row.name || row.title || row.id) || 'Не назначен');
  const role = row => typeof row?.role === 'object' ? name(row.role) : String(row?.role_label || row?.role || row?.specialization || 'Роль не указана');
  const AVAILABILITY = Object.freeze({ active: ['Включён', 'good'], draft: ['Черновик', 'neutral'], suspended: ['Приостановлен', 'warning'], retired: ['Выведен из работы', 'neutral'] });
  function occupancyMeta(agent) {
    const sent = String(agent && agent.occupancy || '');
    const busy = sent ? sent === 'working' : ['working', 'running', 'busy'].includes(String(agent && agent.status || ''));
    return busy ? ['Выполняет задачу', 'good'] : ['Свободен', 'neutral'];
  }
  function availabilityMeta(agent) {
    const key = String(agent && (agent.availability || agent.persona_status || agent.status) || '');
    // "working" is occupancy, not availability: an executing agent is enabled.
    return AVAILABILITY[key] || (['working', 'running', 'busy', 'awaiting_review', 'warning', 'free'].includes(key) ? AVAILABILITY.active : ['Доступность не указана', 'neutral']);
  }
  const chip = meta => `<span class="aw-status aw-${meta[1]}">${esc(meta[0])}</span>`;
  const agentState = agent => {
    // Waiting for a check and waiting for a decision are named separately: one
    // chip covering both would put the owner on the hook for work that only
    // needs looking at.
    const num = key => Math.max(0, Math.floor(number(agent && agent[key]) || 0));
    const review = num('open_review'), decision = num('open_decision');
    const parts = [];
    if (decision) parts.push(`${esc(decision)} ждёт вашего решения`);
    if (review) parts.push(`${esc(review)} на проверке`);
    return `<span class="aw-agent-state">${chip(availabilityMeta(agent))}${chip(occupancyMeta(agent))}`
      + parts.map(text => `<span class="aw-status aw-review">${text}</span>`).join('') + '</span>';
  };
  function readinessGrid(item) {
    if (typeof item?.implemented !== 'boolean') return '';
    const yes = value => value === true ? ['Да', 'good'] : ['Нет', 'neutral'];
    const cells = [
      ['Реализовано', yes(item.implemented)],
      ['Включено', yes(item.enabled)],
      ['Доступно сейчас', item.available === true ? ['Отвечает', 'good'] : ['Не отвечает', 'warning']],
    ].map(([label, meta]) => `<div><dt>${esc(label)}</dt><dd><span class="aw-status aw-${meta[1]}">${esc(meta[0])}</span></dd></div>`).join('');
    const mode = item.mode ? `<div><dt>Рабочий режим</dt><dd>${esc(item.mode)}</dd></div>` : '';
    return `<dl class="aw-readiness">${cells}${mode}</dl>${item.note ? `<p class="aw-field-hint">${esc(item.note)}</p>` : ''}`;
  }
  const canRunDemo = data => data?.enabled === true && data?.capabilities?.can_run_demo === true;
  function memoryScopeCard(item) {
    const names = { user: 'Личная', workspace: 'Рабочее пространство', strategy: 'Проект стратегии', session: 'Текущая сессия', governance: 'Управление', operational: 'Выполнение задачи' };
    const scope = Object.prototype.hasOwnProperty.call(names, item.memory_scope) ? names[item.memory_scope] : 'Личная · прежняя запись';
    const purposes = { task_result: 'Результат задачи', error_recovery: 'Восстановление после ошибки', runtime_status: 'Состояние выполнения' };
    return `<dl class="aw-detail-grid"><div><dt>Область памяти</dt><dd>${esc(scope)}</dd></div><div><dt>Срок хранения</dt><dd>${esc(date(item.retention_until))}</dd></div><div><dt>Видимость</dt><dd>${item.visibility === 'workspace' ? 'Участники пространства' : 'Личная; область сама по себе не открывает доступ'}</dd></div></dl>${item.session_bound ? '<p class="aw-note">Привязана к текущей подтверждённой сессии; другая сессия не получает содержимое.</p>' : ''}${purposes[item.purpose] ? `<p class="aw-note">Назначение: ${esc(purposes[item.purpose])}</p>` : ''}${item.scope_binding && Object.keys(item.scope_binding).length ? `<details class="aw-technical"><summary>Связанный проект или задача</summary><pre>${esc(publicJSON(item.scope_binding))}</pre></details>` : ''}`;
  }
  const knownDomain = value => Object.prototype.hasOwnProperty.call(DOMAINS, String(value || ''));
  const actionLabel = value => value === 'clarify_commission' ? 'Уточнить новым поручением' : Object.prototype.hasOwnProperty.call(ACTION_LABELS, value) ? ACTION_LABELS[value] : 'Действие';
  function allowedDomainActions(data, item) {
    if (data?.enabled !== true) return [];
    return rows(item ? item.actions : data.actions).filter(value => typeof value === 'string' && (value === 'clarify_commission' || Object.prototype.hasOwnProperty.call(ACTION_LABELS, value)));
  }
  const field = (key, label, type, extra) => ({ key, label, type: type || 'text', ...(extra || {}) });
  const rubricField = (assistant = false) => field('rubric_key', 'Задание и проверка', 'select', { required: true, options: [['connection_exact', 'Точный ответ · соединение'], ['json_arithmetic', 'Арифметика · JSON'], ['extract_facts', 'Извлечение фактов'], ...(assistant ? [['assistant_response', 'Ответ помощника · ручная проверка']] : [])] });
  function personaVoiceFields(catalog) {
    const profiles = catalog?.version === 'persona-presentation-v1' ? rows(catalog.profiles).filter(profile => Object.prototype.hasOwnProperty.call(PERSONA_VOICE_PROFILES, profile.id)).map(profile => [profile.id, profile.label || PERSONA_VOICE_PROFILES[profile.id]]) : Object.entries(PERSONA_VOICE_PROFILES);
    const voiceField = (key, label, type, extra) => field(key, label, type, { default: PERSONA_DEFAULTS[key], optionalIfMissing: true, ...(extra || {}) });
    return [
      voiceField('voice_profile_id', 'Голосовой профиль Persona', 'select', { sendEmpty: true, options: [['', 'Профиль выбранного лица (если есть)'], ...profiles], hint: 'Предпочтение Persona, не отдельная модель. Установленный голос устройства может отличаться от серверного профиля.' }),
      voiceField('voice_mode', 'Способ озвучивания', 'select', { options: [['browser', 'Локальный голос устройства'], ['existing_tts', 'Существующий серверный TTS (если разрешён)']], hint: 'По умолчанию — голос устройства без owner-ключей. Серверный звук требует отдельного подтверждённого owner-доступа; при его отсутствии используется локальный голос.' }),
      voiceField('voice_speed', 'Скорость речи', 'number', { min: .5, max: 1.8, step: .1, decimal: true }),
      voiceField('voice_language', 'Язык речи', 'select', { options: [['ru-RU', 'Русский'], ['en-US', 'English']], hint: 'Если локальный голос нужного языка не установлен, остаются текст и статичный аватар.' }),
      voiceField('animation_mode', 'Анимация лица', 'select', { options: [['auto', 'Готовый разговорный клип при озвучивании'], ['static', 'Только статичный аватар']], hint: 'Настройка уменьшения движения имеет приоритет. Готовый клип не синхронизирован с произносимыми фонемами.' }),
      voiceField('expression_preset', 'Предпочтение выражения', 'select', { options: [['neutral', 'Нейтральное'], ['speaking', 'Разговорное']], hint: 'Предпочтение сохраняется. Доступны статичный кадр и готовый разговорный клип; отдельных эмоциональных выражений пока нет.' }),
      voiceField('lip_sync_mode', 'Синхронизация губ', 'select', { options: [['auto', 'Авто при наличии таймингов — сейчас недоступна'], ['off', 'Выключена']], hint: 'Фонемы / viseme-тайминги не предоставлены. Эта настройка не означает готовность настоящего lip-sync.' }),
    ];
  }
  function domainFormFields(domain, action, catalog) {
    if (!knownDomain(domain)) return [];
    if (domain === 'automation' && action === 'clarify_commission') return domainFormFields(domain, 'commission', catalog);
    if (domain === 'external_agents') {
      if (action === 'create') return [field('display_name', 'Название подключения', 'text', { required: true, max: 80 }), field('protocol', 'Протокол', 'select', { required: true, options: [['a2a-0.3-jsonrpc-bounded', 'A2A 0.3 · ограниченный JSON-RPC']] }), field('endpoint', 'HTTPS endpoint внешнего агента', 'url', { required: true, max: 350, hint: 'Публичный HTTPS:443. Внутренние адреса, перенаправления и metadata endpoints запрещены.' }), field('credential', 'Секрет подключения', 'password', { required: true, max: 4096, hint: 'Введите самостоятельно. Секрет не возвращается в карточке и не копируется из owner-подключений.' }), field('capability', 'Запрашиваемая возможность', 'select', { required: true, options: [['stratforge.json_arithmetic.v1', 'Диагностика: арифметика JSON']], hint: 'Не оценка профессионального качества. Сервер пересечёт запрос с проверенными возможностями агента.' })];
      if (action === 'rotate') return [field('credential', 'Новый секрет подключения', 'password', { required: true, max: 4096, hint: 'Старый секрет не показывается. После замены требуется новая проверка подключения.' })];
      if (action === 'task') return [field('input_text', 'Входные данные диагностики', 'textarea', { required: true, max: 4000, hint: 'JSON-массив 3–20 целых чисел, например [1,2,3]. Задание проходит штатный Координатор; результат не считается Model Performance.' })];
      return [];
    }
    if (['tasks', 'model_tasks'].includes(domain) && action === 'review_result') return [field('decision', 'Ваше решение по этому результату', 'select', { required: true, options: [['', 'Выберите решение'], ['accept', 'Результат проверен и принят'], ['reject', 'Результат проверен и отклонён']] }), field('comment', 'Комментарий к проверке', 'textarea', { max: 2000, hint: 'Решение относится только к этому результату. Оно не выставляет профессиональную оценку модели и не разрешает дальнейшее исполнение.' })];
    if (domain === 'publications') {
      if (action === 'prepare') return [field('source', 'Проверенный источник', 'publication-source', { required: true, hint: 'Сервер предоставил только разрешённые источники. На этом шаге пост не создаётся.' })];
      if (action === 'publish') return [field('text', 'Комментарий к публикации (необязательно)', 'textarea', { max: 4000, hint: 'Только ваш публичный комментарий. Не вставляйте ключи, личные данные, private Memory или сырой ответ модели.' }), field('visibility', 'Кто увидит публикацию', 'select', { required: true, options: [['private', 'Только я'], ['followers', 'Мои подписчики'], ['network', 'Социальная сеть']] })];
      return [];
    }
    if (['tasks', 'model_tasks'].includes(domain) && ['cancel', 'retry'].includes(action)) return [field('reason', 'Причина', 'textarea', { required: action === 'cancel', max: 1000 })];
    if (['tasks', 'model_tasks'].includes(domain) && action === 'handoff') return [field('target_model_id', 'Другой агент / подключённая модель', 'model', { required: true, hint: 'Передаются только проверенные факты и метки источника. Это проверка точности передачи, не анализ стратегии или изображения. Автономное делегирование не включается.' })];
    if (domain === 'models') {
      if (action === 'bind_existing') return [field('registry_id', 'Разрешённое Local-подключение', 'binding', { required: true, hint: 'Список сформирован сервером только для текущего владельца. Исходный ключ и существующий бюджет не меняются.' }), field('persona_id', 'Активная Persona', 'persona', { required: true }), field('label', 'Название связи (необязательно)', 'text', { max: 80 })];
      if (action === 'connect') return [field('label', 'Название подключения', 'text', { required: true, max: 80 }), field('connection_kind', 'Тип подключения', 'select', { required: true, options: [['model', 'Своя модель']] }), field('provider', 'Провайдер', 'provider', { required: true }), field('model', 'Идентификатор модели', 'text', { required: true, max: 120 }), field('base_url', 'Endpoint (для совместимого провайдера)', 'url', { max: 250, hint: 'Только разрешённый сервером HTTPS endpoint. Для стандартного провайдера оставьте пустым.' }), field('api_key', 'Ключ подключения', 'password', { required: true, max: 4096 }), field('persona_id', 'Persona', 'persona', { required: true })];
      if (action === 'task') return [rubricField(true), field('input_text', 'Задание / входные данные', 'textarea', { max: 4000, hint: 'Ответ помощника: обычный текст, один ограниченный ответ без tools; содержание проверяете вы, автоматического рейтинга нет. Соединение: пусто. Арифметика: JSON-массив 3–20 целых чисел. Факты: 2–12 строк city=Paris. Секреты не отправляйте.' })];
    }
    if (domain === 'experiments' && action === 'create') return [field('title', 'Название сравнения', 'text', { required: true, max: 80 }), field('model_ids', 'Модели (выберите 2–3)', 'models', { required: true, minItems: 2, maxItems: 3 }), rubricField(), field('input_text', 'Одинаковые входные данные', 'textarea', { max: 4000, hint: 'Соединение: пусто. Арифметика: JSON-массив целых чисел. Факты: строки key=value. Один вход будет отправлен всем выбранным моделям.' })];
    if (domain === 'decisions') {
      if (action === 'propose_consensus') return domainFormFields(domain, 'create').filter(spec => spec.key !== 'evidence_ids').concat(field('contribution_ids', 'Принятые вклады моделей (минимум два)', 'records', { required: true, minItems: 2, maxItems: 3, source: 'contribution_candidates', hint: 'Выберите 2–3 разные модели с одинаковой меткой входа. Сервер повторно проверит источники. Выбор не создаёт голосов.' }));
      if (action === 'review') return [field('model_ids', 'Три независимых проверяющих', 'models', { required: true, minItems: 3, maxItems: 3, hint: 'Результат сформирует backend по фактическим ответам. Браузер не передаёт голоса.' })];
      if (action === 'create') return [field('title', 'Название решения', 'text', { required: true, max: 160 }), field('proposal', 'Предложение', 'textarea', { required: true, max: 12000 }), field('evidence_ids', 'Доказательства', 'evidence', { required: true, minItems: 1, maxItems: 20, hint: 'Только собственные JSON-артефакты. Выберите сохранённый источник либо укажите известный UUID.' }), field('risk', 'Уровень риска', 'select', { required: true, options: [['low', 'Низкий'], ['moderate', 'Умеренный'], ['high', 'Высокий'], ['critical', 'Критический']] }), field('trigger', 'Причина проверки', 'select', { required: true, options: [['requested_review', 'Запрошена проверка'], ['high_risk', 'Высокий риск'], ['conflict', 'Конфликт'], ['low_confidence', 'Низкая уверенность'], ['budget_exceeded', 'Превышение бюджета']] })];
    }
    if (domain === 'automation') {
      if (action === 'commission') return [field('goal', 'Цель поручения', 'text', { required: true, max: 400, hint: 'Этот ограниченный Координатор строит числовую сводку и проверяет передачу фактов, не торговый или универсальный план.' }),
        field('input_text', 'Исходные числа', 'textarea', { required: true, max: 4000, hint: 'От 3 до 20 целых чисел через запятую, например 17, -4, 12, 9. Сначала одна задача в SF Chat; дочерние — только после отдельного разрешения.' }),
        field('coordinator_model_id', 'Подключение Координатора', 'model', { required: true }),
        field('target_model_ids', 'Проверяющие подключения (1–3)', 'models', { required: true, minItems: 1, maxItems: 3 }),
        field('topology', 'Связи проверок', 'select', { required: true, options: [['parallel', 'Параллельно: каждый проверяет исходные факты'], ['chain', 'Цепочка: до трёх уровней передачи']] })];
      if (action === 'approve_commission') return [field('grant_hours', 'Срок разрешения (часы)', 'number', { required: true, min: 1, max: 720, default: 1 }),
        field('max_call_cost_usd', 'Потолок одного вызова (USD)', 'number', { required: true, min: 0, max: 0, decimal: true, default: 0, hint: 'Для этой проверочной сборки — только нулевой расход. Общий бюджет не увеличивается.' })];
      if (!['propose', 'enable'].includes(action)) return [];
      return [field('source_task_id', 'Повторяемый запрос (задача из SF Chat)', 'source_task', { required: true, hint: 'Расписание повторяет уже сделанный запрос. Выберите вашу исходную задачу из SF Chat.' }),
        field('model_id', 'Подключение, которое будет отвечать', 'model', { required: true }),
        rubricField(),
        field('input_text', 'Входные данные', 'textarea', { max: 4000, hint: 'Те же ограниченные проверки, что и в разовой задаче. Секреты не отправляйте.' }),
        field('local_start', 'Первый запуск', 'datetime-local', { required: true }),
        field('occurrences', 'Сколько раз выполнить', 'number', { required: true, min: 1, max: 10 }),
        field('interval_minutes', 'Интервал между запусками (минуты, 0 — один раз)', 'number', { required: true, min: 0, max: 43200 }),
        field('grace_minutes', 'Допустимое опоздание (минуты)', 'number', { required: true, min: 1, max: 60, hint: 'Пропущенный запуск записывается как пропущенный, а не выполняется позже.' }),
        field('grant_hours', 'Срок разрешения (часы)', 'number', { required: true, min: 1, max: 720, hint: 'Расписание не может пережить это разрешение. По истечении новые запуски прекращаются.' }),
        field('max_call_cost_usd', 'Потолок стоимости одного вызова (USD)', 'text', { required: true, max: 12, hint: 'Отдельное условие от разрешения. Существующий бюджет рабочего пространства этим не увеличивается.' })];
    }
    if (domain === 'routines' && action === 'suggest_routine') return [field('title', 'Название предложения', 'text', { required: true, max: 160 }), field('interval_minutes', 'Интервал (минуты)', 'number', { required: true, min: 5, max: 525600 }), field('outcome_ids', 'Проверенные результаты (минимум два)', 'records', { required: true, minItems: 2, maxItems: 20, source: 'outcome_candidates', hint: 'Предложение опирается на сохранённые успешные результаты. Автоматическое исполнение не включается.' })];
    if (domain === 'projects' && action === 'version') return [field('notes', 'Что изменилось', 'textarea', { required: true, max: 6000 }), field('parameters', 'Параметры версии (JSON-объект)', 'json', { required: true, max: 12000 })];
    if (domain === 'memory' && ['promote', 'revoke', 'publish_to_workspace'].includes(action)) return [field('reason', 'Основание', 'textarea', { required: true, max: 1000 })];
    if (!['create', 'update'].includes(action)) return [];
    if (domain === 'personas') return [field('name', 'Имя персоны', 'text', { required: true, max: 160 }),
      field('aliases', 'Обращения по имени (до пяти)', 'aliases', { max: 405, optionalIfMissing: true, hint: 'Одно имя или прозвище на строку. В SF Chat можно написать «@Имя, задание». Уникальные обращения не дают новых прав и не меняют историю.' }),
      field('main_assistant', 'Правая рука владельца', 'select', { optionalIfMissing: true, boolean: true, default: 'false', options: [['false', 'Нет — выбор в SF Chat или обращение по имени'], ['true', 'Да — когда другой помощник не выбран']], hint: 'Одна правая рука в вашем рабочем пространстве. Чтобы сменить его, сначала явно снимите этот выбор у прежней Persona и сохраните, затем назначьте новую. Приостановленный помощник не заменяется автоматически.' }),
      field('description', 'Назначение', 'textarea', { max: 4000 }), field('style', 'Стиль общения', 'textarea', { max: 1000 }), field('avatar_key', 'Лицо персоны', 'select', { sendEmpty: true, options: [['', 'Без изображения — буква имени'], ...AVATAR_KEYS.map(key => [key, AVATAR_LABELS[key]])], hint: 'Выбирается явно. Имя персоны — свободный текст и само по себе не выдаёт лицо другого агента. Смена модели сохраняет выбранное лицо.' }), field('application_role', 'Роль в приложении', 'select', { sendEmpty: true, options: [['', 'Не назначена'], ['backtest_researcher', 'Бэктестирование'], ['chart_researcher', 'Рабочий стол и графики']], hint: 'Явное назначение для команд SF Chat. Имя можно менять. Роль не выдаёт прав, ключей или торгового доступа. Одна активная / приостановленная Persona на роль.' }), ...personaVoiceFields(catalog)];
    const title = field('title', 'Название', 'text', { required: true, max: 160 });
    const description = field('description', 'Описание', 'textarea', { max: 4000, sendEmpty: true });
    const sources = field('source_ids', 'UUID исходных артефактов', 'ids', { maxItems: 20, hint: 'Необязательно. По одному UUID в строке; принадлежность проверит сервер.' });
    if (domain === 'memory') return [title,
      field('memory_scope', 'Область памяти', 'select', { default: 'user', optionalIfMissing: true, options: [['user', 'Личная'], ['workspace', 'Рабочее пространство'], ['strategy', 'Проект стратегии'], ['session', 'Текущая сессия'], ['governance', 'Управление · только владелец/администратор'], ['operational', 'Выполнение задачи']], hint: 'Область не выдаёт права. Общая видимость появляется только после отдельной публикации; сессионную, управленческую и операционную память публиковать нельзя.' }),
      field('content', 'Содержание', 'textarea', { required: true, max: 12000 }),
      field('purpose', 'Для чего хранится', 'text', { max: 160, hint: 'Обязательно, кроме области выполнения задачи — там выберите назначение ниже.' }),
      field('operational_purpose', 'Назначение при выполнении задачи', 'select', { optionalIfMissing: true, options: [['', 'Не применяется'], ['task_result', 'Результат задачи'], ['error_recovery', 'Восстановление после ошибки'], ['runtime_status', 'Состояние выполнения']] }),
      field('strategy_project_id', 'Проект (для памяти стратегии)', 'record', { source: 'strategy_project_candidates' }),
      field('task_id', 'Задача (для оперативной памяти)', 'record', { source: 'task_candidates' }),
      field('retention_days', 'Срок хранения (дни)', 'number', { required: true, min: 1, max: 365, hint: 'Память текущей сессии — не дольше одного дня и только в этой сессии.' }), sources];
    if (domain === 'projects') return [title, description, field('strategy_key', 'Ключ стратегии', 'text', { required: true, max: 120 })];
    if (domain === 'routines') return [title, description, field('interval_minutes', 'Интервал (минуты)', 'number', { required: true, min: 5, max: 525600 }), sources];
    if (domain === 'calendar') return [title, description, field('starts_at', 'Начало (местное время)', 'datetime-local', { required: true }), field('ends_at', 'Окончание (местное время)', 'datetime-local', { required: true }), sources];
    return [];
  }
  function domainPayload(domain, action, values) {
    if (!knownDomain(domain) || !(domain === 'automation' && action === 'clarify_commission') && !Object.prototype.hasOwnProperty.call(ACTION_LABELS, action)) throw new Error('Неизвестное действие.');
    const payload = {};
    for (const spec of domainFormFields(domain, action)) {
      const raw = values?.[spec.key];
      if (spec.optionalIfMissing && raw === undefined) continue;
      let value = Array.isArray(raw) ? raw : String(raw ?? '').trim();
      if (spec.required && (!value || Array.isArray(value) && !value.length)) throw new Error('Заполните поле «' + spec.label + '».');
      if (!value || Array.isArray(value) && !value.length) { if (['ids', 'aliases'].includes(spec.type)) payload[spec.key] = []; else if (spec.sendEmpty) payload[spec.key] = ''; continue; }
      if (spec.type === 'publication-source') {
        const match = /^(outcome|decision|backtest):([A-Za-z0-9_-]{1,96})$/.exec(value);
        if (!match || match[1] !== 'backtest' && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(match[2])) throw new Error('Выберите проверенный источник.');
        payload.source_kind = match[1]; payload.source_id = match[2]; continue;
      } else if (spec.type === 'number') {
        if (Array.isArray(value)) throw new Error('Проверьте число в поле «' + spec.label + '».');
        value = Number(value);
        if (!(spec.decimal ? Number.isFinite(value) : Number.isSafeInteger(value)) || value < spec.min || value > spec.max) throw new Error('«' + spec.label + '»: допустимо от ' + spec.min + ' до ' + spec.max + '.');
      } else if (spec.type === 'aliases') {
        value = (Array.isArray(value) ? value : value.split(/[\n,]+/)).map(alias => String(alias).trim()).filter(Boolean);
        const keys = value.map(alias => alias.normalize('NFKC').toLocaleLowerCase('ru-RU'));
        if (value.length > 5 || value.some(alias => alias.length > 80) || new Set(keys).size !== keys.length) throw new Error('Укажите до пяти разных обращений, каждое — не длиннее 80 символов.');
      } else if (['models', 'ids', 'evidence', 'records'].includes(spec.type)) {
        value = Array.from(new Set((Array.isArray(value) ? value : value.split(/[\s,]+/)).map(String).filter(Boolean)));
        if (value.some(id => !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) || value.length < (spec.minItems || 0) || value.length > spec.maxItems) throw new Error('Проверьте UUID и количество в поле «' + spec.label + '».');
      } else if (['persona', 'model', 'source_task', 'record'].includes(spec.type) && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) throw new Error('Выберите сохранённую запись.');
      else if (spec.type === 'provider' && !/^[a-z][a-z0-9_-]{1,40}$/.test(value)) throw new Error('Выберите поддерживаемого провайдера.');
      else if (spec.type === 'binding' && !/^AGT-[A-Z0-9]{12}$/.test(value)) throw new Error('Выберите разрешённое Local-подключение.');
      else if (spec.type === 'select' && !spec.options.some(([key]) => key === value)) throw new Error('Выберите допустимое значение «' + spec.label + '».');
      else if (spec.type === 'datetime-local') {
        const parsed = new Date(value);
        if (!Number.isFinite(parsed.getTime())) throw new Error('Проверьте дату «' + spec.label + '».');
        value = parsed.toISOString();
      } else if (spec.type === 'json') {
        if (value.length > spec.max) throw new Error('Параметры слишком большие.');
        try { value = JSON.parse(value); } catch (_) { throw new Error('Параметры должны быть валидным JSON-объектом.'); }
        if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('Параметры должны быть JSON-объектом.');
        if (Object.keys(value).some(key => ['__proto__', 'constructor', 'prototype'].includes(key))) throw new Error('Недопустимое имя параметра.');
      } else if (spec.max && value.length > spec.max) throw new Error('Поле «' + spec.label + '» слишком длинное.');
      payload[spec.key] = spec.boolean ? value === 'true' : value;
    }
    if (domain === 'calendar' && payload.starts_at && payload.ends_at && payload.ends_at <= payload.starts_at) throw new Error('Окончание должно быть позже начала.');
    if (domain === 'automation' && ['commission', 'clarify_commission'].includes(action)) {
      const targets = payload.target_model_ids || [];
      if (targets.includes(payload.coordinator_model_id)) throw new Error('Выберите для проверок другие подключения, не подключение Координатора.');
      const chain = payload.topology === 'chain';
      if (!chain && targets.length > 2) throw new Error('Параллельно допустимы максимум две проверки. Для трёх выберите цепочку.');
      payload.parent_indices = targets.map((_, index) => chain ? index - 1 : -1);
      payload.max_depth = chain ? targets.length : 1;
      delete payload.topology;
    }
    if (domain === 'memory' && ['create', 'update'].includes(action)) {
      const scope = payload.memory_scope || 'user';
      if (scope === 'session') { payload.memory_class = 'working'; if (payload.retention_days !== 1) throw new Error('Для памяти сессии выберите срок один день.'); }
      if (scope === 'operational') {
        payload.memory_class = 'task'; payload.purpose = payload.operational_purpose;
        if (!payload.task_id || !payload.purpose) throw new Error('Выберите задачу и назначение оперативной памяти.');
      } else if (payload.task_id) throw new Error('Связь с задачей доступна только для оперативной памяти.');
      if (!payload.purpose) throw new Error('Укажите, для чего хранится память.');
      if (scope === 'strategy' && !payload.strategy_project_id) throw new Error('Выберите проект стратегии.');
      if (scope !== 'strategy' && payload.strategy_project_id) throw new Error('Связь с проектом доступна только для памяти стратегии.');
      delete payload.operational_purpose;
    }
    if (domain === 'external_agents' && action === 'create') { payload.allowed_capabilities = [payload.capability]; delete payload.capability; }
    return payload;
  }
  function validPublicationPreview(prepared, source) {
    const snapshot = prepared?.snapshot;
    const diagnostic = snapshot?.synthetic === true && snapshot.source_kind === 'synthetic_model_response'
      && snapshot.diagnostic_mode === 'named_development_executor' && snapshot.quality_claim === false
      && snapshot.market_performance_claim === false && snapshot.external_call === false
      && snapshot.paid_call === false && snapshot.cost_usd === 0 && String(snapshot.title || '').startsWith('SYNTHETIC');
    return prepared?.permanent === true && prepared?.requires_explicit_confirmation === true && (snapshot?.synthetic === false || diagnostic) && typeof snapshot.title === 'string' && typeof snapshot.summary === 'string' && snapshot.source_id === source?.source_id && /^[0-9a-f]{64}$/.test(prepared.snapshot_sha256 || '') && Number.isSafeInteger(prepared.source_revision) && prepared.source_revision > 0 && snapshot.source_revision === prepared.source_revision;
  }
  function validCoordinatorPreview(prepared, source) {
    return prepared?.approved === false && prepared?.dispatches === 0 && prepared?.coordinator_id === (source?.id || source?.entity_id || '')
      && /^[0-9a-f]{64}$/.test(prepared.approved_plan_sha256 || '') && Array.isArray(prepared?.plan?.nodes)
      && prepared.plan.nodes.length > 0 && prepared.plan.nodes.length <= 3
      && prepared.plan.nodes.every((node, index) => node && typeof node === 'object' && !Array.isArray(node)
        && Number.isSafeInteger(node.parent_index) && node.parent_index >= -1 && node.parent_index < index
        && Number.isSafeInteger(node.depth) && node.depth >= 1 && node.depth <= 3)
      && rows(prepared.actions).includes('approve_commission');
  }
  function coordinatorApproval(prepared, source, values, now) {
    if (!validCoordinatorPreview(prepared, source)) throw new Error('Сначала проверьте актуальный план делегирования.');
    const fields = domainPayload('automation', 'approve_commission', values);
    const expires = new Date(now + fields.grant_hours * 3600000);
    if (!Number.isFinite(expires.getTime())) throw new Error('Проверьте срок разрешения.');
    return { approved_plan_sha256: prepared.approved_plan_sha256, expires_at: expires.toISOString(), max_call_cost_usd: fields.max_call_cost_usd };
  }
  function connectionLabel(model) {
    return model.can_execute_test_only === true ? 'SYNTHETIC · только локальный тестовый исполнитель' : model.connected === true ? 'Реальное соединение проверено' : model.test_executor_verified === true ? 'Локальный тест сохранён; реальное соединение не проверено' : 'Реальное соединение не проверено';
  }
  const EXTERNAL_ERRORS = Object.freeze({
    external_agent_reverification_required: 'Секрет заменён. Подключение выключено до повторной проверки.',
    external_agent_revoked_or_changed: 'Подключение было отозвано или изменено, пока задача ждала запуска.',
    external_agent_reply_uncertain: 'Исполнитель остановился до ответа. Неизвестно, дошёл ли запрос; повторно он не отправляется.',
    external_agent_timeout: 'Агент не ответил вовремя.',
    external_agent_credential_cleanup_pending: 'Отзыв выполнен. Удаление старого секрета отложено и будет повторено.',
    external_agent_unavailable: 'Подключение сейчас недоступно для запуска.',
    external_agent_verification_required: 'Агент не подтвердил запрошенные возможности.',
  });
  const EXTERNAL_STATES = Object.freeze({
    draft: 'Создано, не проверено', verifying: 'Идёт проверка', active: 'Проверено и доступно',
    degraded: 'Проверка не прошла', disabled: 'Выключено', revoked: 'Отозвано',
  });
  function externalAgentCard(item) {
    const stat = item.statistics || {}, tasks = rows(item.tasks);
    const capabilityLabel = value => value === 'stratforge.json_arithmetic.v1'
      ? 'Диагностика: арифметика JSON' : 'Неподдерживаемая возможность · см. детали';
    const code = item.last_error || item.last_error_code;
    const current = item.current_task;
    const taskRow = row => `<div class="aw-text">${taskBadge(row)} <span class="aw-hash">${esc(String(row.id).slice(0, 8))}</span>`
      + `${row.synthetic === true ? ' <span class="aw-status aw-info">SYNTHETIC</span>' : ''}`
      + `${row.error_code ? ' <span class="aw-status aw-warning">' + esc(row.error_code) + '</span>' : ''}`
      + `${row.evaluation_id ? ' · оценка записана' : ' · без оценки'}`
      + `<button class="aw-link-button" data-aw-task="${esc(row.id)}">Задача и доказательства →</button></div>`;
    return `<section class="aw-detail-section"><h3>${esc(item.display_name || item.name || 'Внешний агент')}</h3>`
      + `<div class="aw-inline">${badge(item.status)}<span class="aw-status aw-info">ревизия ${count(item.revision)}</span></div>`
      + `<dl class="aw-detail-grid">`
      + `<div><dt>Тип</dt><dd>External Agent · отдельно от Model</dd></div>`
      + `<div><dt>Состояние</dt><dd>${esc(EXTERNAL_STATES[item.status] || item.status || 'не указано')}</dd></div>`
      + `<div><dt>Протокол</dt><dd>${esc(item.protocol)}</dd></div>`
      + `<div><dt>Модель внутри агента</dt><dd>unknown / externally managed</dd></div>`
      + `<div><dt>Последняя проверка</dt><dd>${esc(date(item.last_verified_at || item.last_verification))}</dd></div>`
      + `<div><dt>Задержка</dt><dd>${number(item.latency_ms ?? item.last_latency_ms) == null ? 'Не измерена' : count(item.latency_ms ?? item.last_latency_ms) + ' мс'}</dd></div>`
      + `<div><dt>Текущая задача</dt><dd>${current ? esc(String(current.id).slice(0, 8)) + ' · ' + esc(statusMeta(current.status)[0]) : 'Нет'}</dd></div>`
      + `<div><dt>Получено результатов</dt><dd>${count(stat.results_received ?? stat.tasks_completed)}</dd></div>`
      + `<div><dt>Ожидает вашей проверки</dt><dd>${count(stat.awaiting_review)}</dd></div>`
      + `<div><dt>Проверено пользователем</dt><dd>${count(stat.reviews_completed)}</dd></div>`
      + `</dl>`
      + `<p class="aw-text">Подтверждённые возможности: ${rows(item.allowed_capabilities).map(capabilityLabel).map(esc).join(', ') || 'Нет'}</p>`
      + (item.synthetic === true ? '<p class="aw-note">SYNTHETIC · Development-агент. Не реальная модель и не рабочий benchmark.</p>' : '')
      + (code ? `<p class="aw-status aw-warning">${esc(EXTERNAL_ERRORS[code] || 'Последняя операция завершилась ошибкой.')} <span class="aw-hash">${esc(code)}</span></p>` : '')
      + (item.credential_cleanup === 'pending' ? '<p class="aw-note">Доступ отозван. Удаление старого секрета поставлено в очередь и будет повторено.</p>' : '')
      + reputationPanel({ external_agent_performance: item.performance })
      + `<p class="aw-note">Результаты внешнего агента не записываются как Model Performance.</p>`
      + (tasks.length ? `<h4>История задач</h4>${tasks.map(taskRow).join('')}` : '<p class="aw-note">Задач ещё не было.</p>')
      + `<details class="aw-technical"><summary>Протокол, возможности и диагностика</summary><pre class="aw-result-text">${esc(publicJSON({
          endpoint: item.endpoint, advertised_capabilities: item.advertised_capabilities,
          requested_capabilities: item.requested_capabilities, allowed_capabilities: item.allowed_capabilities,
          last_error: code, performance: item.performance, statistics: stat,
          task_states: tasks.map(row => ({ id: row.id, ledger_status: row.ledger_status || row.status, display_status: row.display_status })) }))}</pre></details>`
      + `</section>`;
  }
  function modelProtocolCard(model) {
    const caps = model?.capabilities;
    const known = model?.protocol === 'chat_completions_v1' && caps?.text === true
      && ['remote_tools', 'remote_tasks', 'mcp', 'a2a', 'artifacts'].every(key => caps[key] === false);
    if (!known) return '<p class="aw-note">Протокол и возможности подключения ещё не подтверждены сервером. Название «внешний агент» само по себе не означает доступ к удалённым действиям.</p>';
    // Identical on every text connection, so it sits behind one disclosure instead
    // of repeating a paragraph on each card.
    return '<details class="aw-technical"><summary>Текстовый HTTPS-исполнитель · что поддерживается</summary><p class="aw-note">Один ограниченный текстовый ответ через совместимый chat-completions endpoint. Удалённые инструменты, отдельные удалённые задачи, MCP, A2A и артефакты этим подключением не поддерживаются. Права и бюджет остаются у приложения.</p><pre>' + esc(publicJSON({protocol: model.protocol, capabilities: caps})) + '</pre></details>';
  }
  function domainError(error) {
    const code = String(error?.code || error?.data?.error || error?.error || '');
    const messages = {
      memory_scope_invalid: 'Область памяти не распознана. Обновите форму.',
      memory_scope_immutable: 'Область существующей памяти нельзя менять. Создайте новую запись, сохранив историю.',
      memory_authenticated_session_required: 'Для этой памяти нужна подтверждённая пользовательская сессия.',
      memory_session_mismatch: 'Эта запись принадлежит другой сессии и недоступна здесь.',
      memory_session_ttl_required: 'Память сессии хранится не дольше одного дня.',
      memory_governance_denied: 'Управленческая память доступна только уполномоченному владельцу или администратору.',
      memory_strategy_changed: 'Проект стратегии изменён. Проверьте источник и создайте актуальную запись памяти.',
      memory_strategy_unavailable: 'Проект стратегии недоступен или архивирован.',
      memory_scope_not_publishable: 'Эту область памяти нельзя публиковать в рабочее пространство.',
      memory_operational_context_required: 'Выберите свою задачу и назначение оперативной памяти.',
      budget_exceeded: 'Лимит расходов не разрешает этот запрос. Бюджет не изменён.', budget_denied: 'Лимит расходов не разрешает этот запрос. Бюджет не изменён.',
      invalid_api_key: 'Провайдер отклонил ключ. Проверьте подключение; ключ не сохранён в интерфейсе.', provider_auth_failed: 'Провайдер отклонил авторизацию. Проверьте ключ подключения.',
      endpoint_unavailable: 'Endpoint недоступен. Проверьте адрес и повторите проверку.', endpoint_not_allowed: 'Этот endpoint не разрешён сервером.',
      revision_conflict: 'Запись уже изменилась. Обновите её и проверьте новые данные перед повтором.', idempotency_conflict: 'Параметры повторного запроса изменились. Откройте действие заново после проверки истории.',
      model_share_revoked: 'Владелец выключил общий доступ к модели. Новые вызовы запрещены; прежние ответы и история сохранены.',
      model_share_not_found: 'Общая модель больше недоступна. Прежние ответы и история сохранены.',
      preview_bridge_shared_only: 'Общий доступ к выбранной модели отозван. Новый вызов не выполнен; история сохранена.',
      external_blocked: 'Необходимое внешнее подключение недоступно. Действие не считается выполненным.',
      process_sources_changed: 'Результаты или их проверка изменились. Обновите предложения и проверьте новые источники; старая история сохранена.',
      process_suggestion_stale: 'Предложение уже изменилось. Откройте актуальную запись перед решением.',
      process_scan_incomplete: 'Полный набор наблюдений сейчас недоступен. Предложение не создано; повторите после обновления раздела.',
      persona_aliases_invalid: 'Укажите до пяти обращений: буквы, цифры, пробел, дефис или подчёркивание; до 80 символов каждое.',
      persona_aliases_ambiguous: 'Обращения должны различаться, в том числе без учёта регистра.',
      persona_alias_repeats_name: 'Обращение повторяет имя Persona. Имя уже можно использовать без дополнительного alias.',
      persona_alias_already_assigned: 'Это обращение уже относится к другой вашей Persona. Измените его; существующие имена и история сохранены.',
      persona_main_already_assigned: 'Правая рука уже назначена. Сначала явно снимите этот выбор у прежней Persona и сохраните, затем назначьте новую.',
    };
    if (Object.prototype.hasOwnProperty.call(messages, code)) return messages[code];
    if (error?.status === 403 || error?.status === 401) return 'Сервер не разрешил действие в текущем рабочем пространстве. Права и бюджет не изменены.';
    if (error?.status === 409) return 'Состояние изменилось или действие уже выполнено. Обновите запись перед повторной попыткой.';
    if (error?.status === 404 || error?.status === 503) return 'Действие или необходимый сервис сейчас недоступны. Это не успешное выполнение.';
    if (error?.status === 400 || error?.status === 422) return 'Сервер отклонил поля запроса. Проверьте значения, UUID и обязательные источники.';
    return 'Ответ сервера не подтверждён. Проверьте историю; повторная отправка использует тот же ключ и не создаёт дубликат.';
  }
  // Evidence is never dropped: a raw JSON payload or a 64-hex digest is moved
  // out of the sentence the owner reads and into a details block beside it.
  function technicalSplit(text) {
    let prose = String(text == null ? '' : text);
    const technical = [];
    for (const match of prose.match(/\b[0-9a-f]{64}\b/g) || []) {
      technical.push('SHA256 ' + match);
      prose = prose.replace(new RegExp('(?:SHA256|sha256)\\s*:?\\s*' + match, 'g'), '').replace(match, '');
    }
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const start = prose.search(/[{[]/);
      if (start < 0) break;
      const open = prose[start], close = open === '{' ? '}' : ']';
      let depth = 0, end = -1, quoted = false, escaped = false;
      for (let i = start; i < prose.length; i += 1) {
        const char = prose[i];
        if (escaped) { escaped = false; continue; }
        if (char === '\\') { escaped = true; continue; }
        if (char === '"') { quoted = !quoted; continue; }
        if (quoted) continue;
        if (char === open) depth += 1;
        else if (char === close) { depth -= 1; if (!depth) { end = i; break; } }
      }
      if (end < 0) break;
      const slice = prose.slice(start, end + 1);
      let parsed = null;
      try { parsed = JSON.parse(slice); } catch (_) { parsed = null; }
      if (parsed === null || typeof parsed !== 'object') break;
      technical.push(publicJSON(parsed));
      prose = prose.slice(0, start) + prose.slice(end + 1);
    }
    const LINK = /(?:(?:Оригинальный отчёт|Источник|Ссылка)\s*:\s*)?(?:https?:\/\/|\/)[^\s,;]{12,}/g;
    for (const match of prose.match(LINK) || []) {
      technical.push(match.replace(/^[^/h]*/, ''));
      prose = prose.replace(match, '');
    }
    prose = prose.replace(/(?:SHA256|sha256)\s*:?\s*(?=[.,;]|$)/g, '')
                 .replace(/\s{2,}/g, ' ').replace(/\s+([.,;:])/g, '$1').replace(/^[\s.,;:]+/, '').trim();
    return { prose, technical };
  }
  function technicalDetails(entries, label) {
    if (!entries || !entries.length) return '';
    return `<details class="aw-technical"><summary>${esc(label || 'Технические детали')}</summary><pre class="aw-result-text">${esc(entries.join('\n\n'))}</pre></details>`;
  }
  function publicJSON(value) {
    return JSON.stringify(value, (key, entry) => /(?:secret|password|api_?key|access_?token|authorization|cookie)/i.test(key) ? '[скрыто]' : entry, 2);
  }
  function transportResponseOnly(value) {
    return value?.verification_scope === 'transport_only' || [value?.task_class, value?.rubric_key].includes('assistant_response');
  }
  function transportVerificationNote(value) {
    return transportResponseOnly(value) ? '<p class="aw-note">Проверено только получение и технический формат ответа. Содержание автоматически не оценено; приёмка результата — отдельное решение человека. Этот класс не влияет на профессиональный рейтинг или выбор модели.</p>' : '';
  }
  function evaluationMeta(agent) {
    const evaluation = agent?.evaluation || {};
    const sample = Math.max(0, Math.floor(number(evaluation.sample_size) || 0));
    const manualOnly = transportResponseOnly(evaluation);
    const insufficient = manualOnly || sample < 3 || evaluation.confidence === 'insufficient' || number(evaluation.score_pct) == null;
    const confidence = manualOnly ? 'не оценена' : { insufficient: 'недостаточно данных', low: 'низкая', medium: 'средняя', high: 'высокая' }[evaluation.confidence] || 'не оценена';
    const diagnostic = ['json_arithmetic', 'connection_exact', 'extract_facts'].includes(evaluation.task_class || evaluation.rubric_key);
    const label = manualOnly ? 'Ручная проверка · без рейтинга' : diagnostic ? (sample ? `${count(evaluation.passed)} из ${count(sample)} · диагностика` : 'Нет наблюдений') : insufficient ? 'NEW' : pct(evaluation.score_pct);
    const ORIGINS = { real_model_bounded_capability: 'фактические ответы модели', real_application_execution_conformance: 'проверенные результаты приложения', desktop_canvas_receipt: 'снимок рабочего стола' };
    const mode = String(evaluation.mode || evaluation.scope || '');
    const classKey = String(evaluation.task_class || evaluation.rubric_key || '');
    return { sample, score: insufficient ? null : number(evaluation.score_pct), label, confidence, insufficient, diagnostic,
      observed: manualOnly ? null : number(evaluation.observed_score_pct), mode,
      classKey, classLabel: rubricLabel(classKey) || classKey || 'Класс проверки не указан',
      origin: Object.prototype.hasOwnProperty.call(ORIGINS, mode) ? ORIGINS[mode] : '' };
  }
  function applicationRows(agent) {
    if (agent?.synthetic !== false) return [];
    return rows(agent.application_observations).filter(value => value.mode === 'real_application_execution_conformance')
      .flatMap(value => rows(value.classes).filter(item => ['backtest', 'chart'].includes(item.application_kind))
        .map(item => ({ ...item, model: value.model, connection_status: value.connection_status,
          title: item.application_kind === 'backtest' ? 'Бэктест · соответствие отчёта' : 'График · подлинность PNG',
          label: evaluationMeta({ evaluation: item }).label })));
  }
  function applicationTable(agents) {
    const measured = rows(agents).flatMap(agent => applicationRows(agent).map(value => ({ ...value, agent: name(agent) })));
    if (!measured.length) return '<p class="aw-note">Реальные прикладные результаты ещё не проверены. Арифметика и synthetic не заменяют отчёт или PNG.</p>';
    return `<div class="aw-table-wrap"><table class="aw-table"><thead><tr><th>Агент / модель</th><th>Проверка результата</th><th>Источники</th><th>Выборка / оценка</th></tr></thead><tbody>${measured.map(value => `<tr><td>${esc(value.agent)}<div class="aw-table-sub">${esc(value.model)}${value.connection_status === 'active' ? '' : ' · архивное подключение'}</div></td><td>${esc(value.title)}</td><td>Проверенных входов: ${count(value.sample_size)}<div class="aw-table-sub">Записей: ${count(value.receipt_count)}</div></td><td>n = ${count(value.sample_size)} · ${esc(value.label)}</td></tr>`).join('')}</tbody></table></div><p class="aw-note">Проверяется связь исходного отчёта/PNG с поручением. Это не прибыльность стратегии, визуальное качество графика или общая оценка модели. Бэктест и график не усредняются; повтор одного входа не увеличивает n. NEW до трёх разных входов. Неуспешные и незавершённые попытки остаются в истории, но не подменяются проверенными источниками.</p>`;
  }
  function safeArtifactUrl(value, sourceKind) {
    const path = String(value || '');
    // Authenticated opaque routes only; legacy Desktop snapshots also require proven source kind.
    if (/^\/api\/ai-control-center\/artifacts\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(path)) return path;
    return sourceKind === 'desktop_chart' && /^\/api\/ops\/runtime\/snapshots\/cs_[0-9a-f]{32}\.(?:jpg|png|webp)$/.test(path) ? path : '';
  }
  function sourceMeta(value) {
    // Scope does not prove data provenance. Only an explicit server classification does.
    if (value?.synthetic === true) return { label: 'SYNTHETIC · тестовые данные', kind: 'synthetic', reportUrl: '' };
    const application = value?.application_result;
    const verifiedApplication = value?.synthetic === false && value?.source_kind === 'real_model_response'
      && value?.status === 'succeeded' && application?.verified === true
      && ['ninjatrader_report', 'desktop_chart'].includes(application?.source_kind);
    // This is presentation of the verified application result, not a change
    // to the model task's authority or its original source classification.
    const kind = verifiedApplication ? application.source_kind : value?.synthetic === false ? String(value?.source_kind || '') : '';
    const labels = { ninjatrader_report: 'NinjaTrader · исходный отчёт', desktop_chart: 'Рабочий стол · снимок графика', runtime_observation: 'Local · наблюдение runtime', real_model_response: 'Модель · фактический ответ' };
    const known = Object.prototype.hasOwnProperty.call(labels, kind);
    const job = String(verifiedApplication ? application.source_id || '' : value?.source_job_id || '');
    const reportUrl = kind === 'ninjatrader_report' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(job) ? '/ui/backtesting.html?job=' + encodeURIComponent(job) : '';
    return { label: known ? labels[kind] : 'Источник не подтверждён', kind: known ? kind : 'unknown', reportUrl };
  }
  function overviewOutcomes(data) {
    if (Array.isArray(data?.outcomes)) {
      // Keep actual application artifacts discoverable after later model votes.
      // Stable presentation ordering changes no stored history or verdict.
      const priority = value => value?.status === 'succeeded' && value?.application_result?.verified === true
        && ['ninjatrader_report', 'desktop_chart'].includes(sourceMeta(value).kind) ? 0 : 1;
      return data.outcomes.slice().sort((left, right) => priority(left) - priority(right));
    }
    // A completed task summary is real stored evidence, not an invented chart or score.
    return rows(data?.tasks).filter(task => ['succeeded', 'completed', 'verified'].includes(task.status)).slice(0, 3).map(task => ({
      title: task.title, summary: task.summary || '', task_id: taskId(task), status: task.status,
      synthetic: task.synthetic, source_kind: task.source_kind, source_job_id: task.source_job_id,
      application_result: task.application_result,
      created_at: task.updated_at || task.created_at,
    }));
  }
  function realChatCommands(data) {
    if (data?.enabled !== true || data?.scope?.synthetic !== false) return [];
    return [
      { title: 'Бэктест в NinjaTrader', text: 'Толик, запусти бэктест SampleMACrossOver на MNQ 09-26, 5m, с 2026-08-24 по 2026-08-29, Fast=10, Slow=25' },
      { title: 'Снимок существующего графика', text: 'Иван, сделай снимок рабочего стола MNQ 09-26, 5m' },
    ];
  }
  function taskMatches(task, filter, query) {
    const groups = { active: ['running', 'working', 'active', 'ready', 'queued', 'waiting_result'], waiting: ['planned', 'waiting_result', 'waiting', 'pending', 'paused'], review: ['awaiting_review', 'review', 'awaiting_owner', 'approval_required', 'court', 'blocked', 'rejected'], completed: ['succeeded', 'completed'], failed: ['failed'], cancelled: ['cancelled'] };
    if (filter === 'attention') { if (!ATTENTION_PHASES.includes(phaseOf(task))) return false; }
    else if (filter && filter !== 'all' && !(groups[filter] || [filter]).includes(String(taskState(task)))) return false;
    const needle = String(query || '').trim().toLocaleLowerCase('ru-RU');
    return !needle || [task.title, task.summary, task.stage, name(task.lead), task.task_class].join(' ').toLocaleLowerCase('ru-RU').includes(needle);
  }
  function flagRows(value) {
    if (Array.isArray(value)) return value.map(row => ({ name: String(row.name || row.flag || ''), enabled: row.enabled === true }));
    return Object.entries(value || {}).map(([key, enabled]) => ({ name: key, enabled: enabled === true || enabled?.enabled === true }));
  }
  async function captureChart(artifact, environment) {
    const env = environment || root;
    const url = safeArtifactUrl(artifact?.url);
    if (!url || (artifact?.media_type || artifact?.mime_type) !== 'image/svg+xml') throw new Error('Для снимка нужен локальный SVG-артефакт задачи.');
    const image = new env.Image();
    await new Promise((resolve, reject) => {
      const timer = env.setTimeout(() => { image.onload = image.onerror = null; reject(new Error('График не загрузился. Повторите попытку.')); }, 15000);
      image.onload = () => { env.clearTimeout(timer); resolve(); };
      image.onerror = () => { env.clearTimeout(timer); reject(new Error('Не удалось загрузить проверенный график.')); };
      image.src = url;
    });
    if (!(image.naturalWidth > 0 && image.naturalHeight > 0)) throw new Error('У графика нет доступного изображения.');
    const canvas = env.document.createElement('canvas');
    const scale = Math.min(1200 / image.naturalWidth, 700 / image.naturalHeight, 1);
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Браузер не поддерживает снимок графика.');
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const result = canvas.toDataURL('image/png');
    if (!result.startsWith('data:image/png;base64,') || result.length > 350000) throw new Error('Снимок превышает допустимый размер (256 KiB).');
    return result;
  }
  // Pure presentation functions are executable in Node contract tests, without DOM or HTTP.
  function handoffCard(task) {
    const packet = task?.handoff;
    if (task?.synthetic !== false || packet?.synthetic !== false || packet.kind !== 'verified_application_fact_handoff') return '';
    return `<section class="aw-detail-section"><h3>Передача проверенных фактов</h3><p class="aw-note">${esc(packet.limitation)}</p><div class="aw-hash">SOURCE TASK ${esc(packet.parent_task_id)} · REV ${count(packet.parent_revision)}<br>FACTS SHA256 ${esc(packet.facts_sha256)}</div><pre class="aw-result-text">${esc(publicJSON(packet.facts))}</pre></section>`;
  }
  function followupCard(item) {
    const followup = item?.followup_chat;
    if (followup?.synthetic !== false || followup.automation_enabled !== false) return '';
    const delivered = followup.status === 'delivered' && followup.message_id && /^AW-FU-[0-9a-f]{28}$/.test(followup.conversation_id || '');
    return `<section class="aw-detail-section"><h3>Ручной разбор</h3><p class="aw-note">${delivered ? 'Уведомление сохранено в SF Chat.' : 'Запрос на доставку: ' + esc(followup.status || 'в очереди') + '. Обновите запись для проверки результата.'} Это не запуск по расписанию и не выполненное задание модели. Автоматизация выключена.</p>${delivered ? `<button class="btn primary" data-aw-followup-chat="${esc(followup.conversation_id)}">Открыть сохранённый разбор</button>` : ''}<div class="aw-hash">JOB ${esc(followup.job_id)}<br>SOURCE REV ${count(followup.source_revision)} · ${esc(followup.source_sha256)}</div></section>`;
  }
  function modelConnectionGuide() {
return '<aside class="aw-note"><strong>Отдельный тестовый ключ</strong><p>Можно выбрать OpenRouter и модель <code>openrouter/free</code>; Endpoint оставить пустым. Создайте отдельный inference API key на <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noopener noreferrer">странице ключей OpenRouter</a> и самостоятельно вставьте его в поле «Ключ подключения». Owner-ключи не копируются.</p><p><a href="https://openrouter.ai/docs/guides/routing/routers/free-router" target="_blank" rel="noopener noreferrer">Free router</a> выбирает доступную бесплатную модель; состав моделей и лимиты зависят от сервиса. Проверьте его условия. Секрет не отправляйте в чат.</p><p>Здесь подключается только модель через совместимый HTTPS chat-completions endpoint. Для самостоятельного внешнего агента используйте раздел «Внешние агенты».</p></aside>';
  }
  function personaReadText(persona) {
    // Only the displayed description, not task history, model payloads or keys.
    return [persona?.title || persona?.name || 'Persona', persona?.description || persona?.profile?.description || 'Описание пока не заполнено.'].join('. ').slice(0, 1200);
  }
  function personaCanSpeak(persona) {
    return ['draft', 'active'].includes(persona?.status) && Number.isSafeInteger(persona?.revision) && persona.revision > 0
      && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(persona?.id || '')
      && Object.prototype.hasOwnProperty.call(PERSONA_VOICE_PROFILES, persona?.presentation?.resolved_voice_profile_id || '');
  }
  function personaSpeechEnvelope(request, idempotencyKey) {
    if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(request?.persona_id || '') || !Number.isSafeInteger(request?.expected_revision) || request.expected_revision < 1 || !idempotencyKey || typeof request?.text !== 'string' || !request.text.trim()) throw { status: 400, code: 'persona_voice_request_invalid' };
    return { payload: { text: request.text.slice(0, 1200) }, expected_revision: request.expected_revision, idempotency_key: idempotencyKey };
  }
  function personaAudioStatus(view) {
    const labels = { preparing: 'Подготовка озвучивания…', stopped: 'Озвучивание остановлено.', not_started: 'Нажмите кнопку, чтобы начать озвучивание.' };
    if (view?.state === 'speaking') return view.mode === 'server' ? 'Воспроизводится серверный звук. Доступ проверен для этой Persona.' : 'Голос этого устройства: ' + String(view.voice || 'локальный голос') + '. Это не копия серверного голоса.';
    if (view?.state === 'finished') return 'Озвучивание завершено (' + (view.mode === 'server' ? 'серверный звук' : 'голос устройства') + '). Это не оценка качества модели.';
    if (view?.state === 'text_fallback') {
      const reasons = { voice_access_not_confirmed: 'Доступ или ревизия Persona не подтверждены. Обновите карточку перед повтором.', no_local_voice_for_language: 'На устройстве нет локального голоса выбранного языка.', voice_not_configured: 'Сначала выберите голосовой профиль Persona.', speech_unavailable: 'Браузер не поддерживает локальное озвучивание.', browser_speech_failed: 'Устройство не смогло воспроизвести голос.', empty_text: 'Нет текста для озвучивания.' };
      return (reasons[view.reason] || 'Звук сейчас недоступен.') + ' Доступны статичный аватар и текст.';
    }
    return labels[view?.state] || 'Звук ещё не проверен на этом устройстве.';
  }
  function personaPresentationCard(persona, faceHTML) {
    const view = persona?.presentation;
    if (!view || view.version !== 'persona-presentation-v1') return '<p class="aw-note">Настройки голоса ещё не предоставлены сервером. Существующее лицо и история сохранены.</p>';
    const configured = personaCanSpeak(persona), staticFace = view.animation_mode === 'static' || !AVATAR_KEYS.includes(view.avatar_key);
    const fields = [
      ['Обращения в SF Chat', rows(persona.aliases).join(', ') || 'Имя Persona; дополнительных обращений нет'],
      ['Правая рука владельца', persona.main_assistant === true ? 'Да · когда другая Persona не выбрана' : 'Нет'],
      ['Голосовой профиль', view.voice_label || 'Голос не выбран'],
      ['Запрошенный звук', view.voice_mode === 'existing_tts' ? 'Существующий серверный TTS, если разрешён; иначе голос устройства' : 'Локальный голос устройства'],
      ['Язык / скорость', (view.voice_language === 'en-US' ? 'English' : 'Русский') + ' · ×' + (number(view.voice_speed) ?? 1)],
      ['Лицо', staticFace ? 'Статичный аватар' : 'Готовый клип при озвучивании; без движения при reduced-motion'],
      ['Синхронизация губ', 'Недоступна: фонемы и viseme-тайминги отсутствуют'],
    ];
    return `<section class="aw-detail-section aw-persona-presentation"><div class="aw-profile-head"><span data-aw-persona-visual>${faceHTML || ''}</span><div><h3>Лицо и голос Persona</h3><p class="aw-note">AI-персона, не реальный человек. Модель, роль и подключение настраиваются отдельно.</p></div></div><dl class="aw-detail-grid">${fields.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl><p class="aw-text" id="aw-persona-read-text">${esc(personaReadText(persona))}</p><div class="aw-actions"><button type="button" class="btn primary" data-aw-persona-speak="${esc(persona.id)}"${configured ? '' : ' disabled'}>Прочитать описание</button><button type="button" class="btn" data-aw-persona-stop disabled>Остановить звук</button></div><p class="aw-field-hint">Озвучивается показанный текст, только по нажатию. Голос устройства зависит от установленных голосов; сохранённая настройка не означает проверенный звук. Разговорный клип не является lip-sync.</p>${configured ? '' : '<p class="aw-note">Для озвучивания нужен выбранный голосовой профиль и активная Persona или её черновик.</p>'}<p class="aw-note" id="aw-persona-audio-status" role="status" aria-live="polite">Звук ещё не проверен на этом устройстве.</p><details class="aw-technical"><summary>Технические данные озвучивания</summary><pre id="aw-persona-audio-details">${esc(publicJSON({ presentation: view, playback: 'not_started' }))}</pre></details></section>`;
  }
  function processCandidateValid(candidate, domain) {
    return ['routines', 'calendar'].includes(domain) && candidate?.domain === domain && /^[0-9a-f]{64}$/.test(candidate?.id || '') && /^[0-9a-f]{64}$/.test(candidate?.source_sha256 || '') && candidate.automation_enabled === false && candidate.quality_claim === false;
  }
  function processCandidatePayload(candidate, domain) {
    if (!processCandidateValid(candidate, domain) || !rows(candidate.actions).includes('propose')) throw new Error('Предложение или право на действие не подтверждены актуальным снимком. Обновите раздел.');
    return { source_sha256: candidate.source_sha256 };
  }
  function processCandidateCard(candidate, domain, canPropose) {
    const origins = { desktop_chart: 'Снимки графиков Рабочего стола', ninjatrader_report: 'Результаты бэктестов NinjaTrader' };
    const valid = processCandidateValid(candidate, domain), permitted = rows(candidate.actions).includes('propose');
    const time = domain === 'calendar' ? `<div><dt>Предлагаемое время (местное)</dt><dd>${esc(date(candidate.starts_at))} — ${esc(date(candidate.ends_at))}</dd></div>` : '';
    return `<article class="aw-domain-card"><div class="aw-domain-card-head"><strong>${esc(candidate.title || 'Повторяющаяся работа')}</strong><span class="aw-status aw-review">Предложение · ещё не сохранено</span></div><p class="aw-text">${esc(candidate.description || '')}</p><dl class="aw-detail-grid"><div><dt>Происхождение</dt><dd>${esc(origins[candidate.source_kind] || 'Источник не распознан')}</dd></div><div><dt>Выборка результатов</dt><dd>${count(candidate.sample_size)}</dd></div><div><dt>Ещё ждут вашей проверки</dt><dd>${count(candidate.pending_source_reviews)}</dd></div><div><dt>Период наблюдения</dt><dd>${esc(date(candidate.first_at))} — ${esc(date(candidate.last_at))}</dd></div><div><dt>Предлагаемый интервал</dt><dd>${count(candidate.interval_minutes)} мин.</dd></div><div><dt>Уверенность в повторяемости</dt><dd>Низкая · медиана интервалов между результатами</dd></div>${time}</dl><p class="aw-note">Автоматические проверки результата не закрывают вашу проверку. Это не оценка профессионального качества модели. Сохранение предложения не включает расписание.</p>${canPropose && valid && permitted ? `<div class="aw-actions"><button class="btn" data-aw-process-propose="${esc(candidate.id)}">Рассмотреть предложение</button></div>` : ''}${!valid ? '<p class="aw-note">Данные предложения не подтверждены; действие недоступно. Обновите раздел.</p>' : !permitted ? '<p class="aw-note">Предложение доступно только для чтения: сервер не разрешил его сохранение в текущем контексте.</p>' : ''}<details class="aw-technical"><summary>Источники и снимок предложения</summary><pre>${esc(publicJSON(candidate))}</pre></details></article>`;
  }
  function processIntelligencePanel(data, domain) {
    const process = data?.process_intelligence;
    if (!['routines', 'calendar'].includes(domain) || !process) return '';
    const candidates = rows(process.candidates).filter(item => item && item.domain === domain);
    const ready = data.enabled === true && process.version === 'process-intelligence-v1' && process.incomplete !== true && process.automation_enabled === false;
    const heading = '<section class="aw-detail-section"><h3>Предложения по повторяющейся работе</h3><p class="aw-note">Учитываются разрешённые структурированные события и проверенные результаты приложения. Личные чаты не анализируются. Сначала сохраните предложение, затем отдельно примите или отклоните его. Автоматизация не включается.</p>';
    const summary = `<details class="aw-technical"><summary>Почему некоторые наблюдения не вошли в предложения</summary><p class="aw-field-hint">Исключённые наблюдения и пауза между предложениями — не ошибки задач. История ошибок не удаляется.</p><pre>${esc(publicJSON({ version: process.version, minimum_observations: process.minimum_observations, incomplete: process.incomplete, reason: process.reason, suppressed: rows(process.suppressed).filter(item => !item.domain || item.domain === domain), excluded: process.excluded, limitations: process.limitations }))}</pre></details>`;
    const body = !ready ? '<p class="aw-note">Полный актуальный набор наблюдений сейчас не подтверждён. Создание предложения недоступно; сохранённые записи не изменены.</p>' : candidates.length ? `<div class="aw-domain-grid">${candidates.map(candidate => processCandidateCard(candidate, domain, true)).join('')}</div>` : '<p class="aw-note">Новых предложений нет: данных пока недостаточно, предложение уже существует или действует пауза от повторов. Это не ошибка и не оценка качества.</p>';
    return heading + body + summary + '</section>';
  }
  function validSchedulePreview(result, source, payload) {
    const plan = result?.plan, ref = plan?.source;
    return result?.approved === false && rows(result.actions).includes('enable')
      && /^[0-9a-f]{64}$/.test(result.approved_plan_sha256 || '')
      && ['routines', 'calendar'].includes(source?.domain) && source.status === 'accepted'
      && ref?.entity_id === source.id && ref?.revision === source.revision && plan.domain === source.domain
      && plan.model_id === payload.model_id && typeof plan.synthetic === 'boolean'
      && Array.isArray(plan.due_at) && plan.due_at.length === payload.occurrences
      && plan.due_at.every(value => typeof value === 'string' && Number.isFinite(Date.parse(value)))
      && plan.spec?.rubric_key === payload.rubric_key;
  }
  const RISK_LABELS = Object.freeze({ low: 'низкий', moderate: 'умеренный', high: 'высокий', critical: 'критический' });
  const APPROVAL_LABELS = Object.freeze({ advice: 'только совет, исполнение не разрешено', draft: 'черновик',
    reversible_execution: 'обратимое исполнение', approval_required: 'требуется подтверждение', forbidden: 'запрещено' });
  const SCOPE_LABELS = Object.freeze({
    external_agent_performance: 'Внешний агент',
    model_performance: 'Модель',
    agent_role_performance: 'Рабочая роль',
    decision_performance: 'Решение',
  });
  const CONFIDENCE_LABELS = Object.freeze({ insufficient: 'недостаточно данных', low: 'низкая',
    medium: 'средняя', high: 'высокая' });
  function reputationPanel(views) {
    // One card per scope. They are never summed, never averaged and never
    // relabelled: a model's observed rate is not the role's, and the heading
    // of each card says which subject the number below it belongs to.
    const scopes = Object.values(views || {}).filter(view => view && view.scope);
    if (!scopes.length) return '';
    const cards = scopes.map(view => {
      const quality = view.quality || {}, provenance = view.provenance || {}, window = view.window || {};
      const measured = view.status === 'measured' && number(quality.observed_pct) != null;
      const diagnostic = view.basis === 'diagnostic';
      const headline = !measured
        ? '<span class="aw-status aw-neutral">NEW · недостаточно данных</span>'
        : diagnostic
          ? `<span class="aw-status aw-neutral">диагностика · ${esc(count(provenance.measured_observations + provenance.synthetic_observations))} из ${esc(count(view.sample_size))}</span>`
          : `<span class="aw-status ${view.basis === 'mixed' ? 'aw-neutral' : 'aw-good'}">${esc(pct(quality.observed_pct))}${view.basis === 'mixed' ? ' · частично диагностика' : ''}</span>`;
      return `<article class="aw-domain-card"><div class="aw-domain-card-head">`
        + `<strong>${esc(SCOPE_LABELS[view.scope] || view.scope)}</strong>`
        + `${headline}</div>`
        + `<dl class="aw-detail-grid">`
        + `<div><dt>Субъект оценки</dt><dd>${esc(SCOPE_LABELS[view.scope] || '')} · <span class="aw-hash">${esc(String((view.subject || {}).id || '').slice(0, 8))}</span></dd></div>`
        + `<div><dt>Класс задачи</dt><dd>${esc(rubricLabel(view.task_class) || view.task_class || '')}</dd></div>`
        + `<div><dt>Наблюдений</dt><dd>${count(view.sample_size)}${number(provenance.synthetic_observations) ? ' · из них диагностических ' + esc(count(provenance.synthetic_observations)) : ''}</dd></div>`
        + `<div><dt>Уверенность</dt><dd>${esc(CONFIDENCE_LABELS[view.confidence] || view.confidence || '')}</dd></div>`
        + `<div><dt>Доказательства</dt><dd>${count(rows(view.evidence_refs).length)} записей</dd></div>`
        + `<div><dt>Окно измерения</dt><dd>${count(window.days)} дн.${window.newest_observation ? ' · последнее наблюдение ' + esc(date(window.newest_observation)) : ' · наблюдений нет'}</dd></div>`
        + `</dl>`
        + `<p class="aw-field-hint">${esc(view.limitation || '')}</p>`
        + `<details class="aw-technical"><summary>Происхождение оценки</summary><pre>${esc(publicJSON({
            scope: view.scope, subject: view.subject, task_class: view.task_class,
            evaluator: provenance.evaluator, self_scored: provenance.self_scored,
            synthetic_observations: provenance.synthetic_observations,
            measured_observations: provenance.measured_observations,
            professional_quality_assessed: provenance.professional_quality_assessed,
            evidence_refs: rows(view.evidence_refs).slice(0, 5),
          }))}</pre></details></article>`;
    }).join('');
    return `<section class="aw-detail-section"><h3>Наблюдаемые оценки</h3>`
      + `<p class="aw-field-hint">Каждая оценка относится к своему субъекту и классу задач. `
      + `Оценка модели не является оценкой рабочей роли, и наоборот; они не складываются.</p>`
      + `<div class="aw-domain-grid">${cards}</div></section>`;
  }
  function courtPanel(item) {
    const cases = rows(item.court_cases), votes = rows(item.votes || item.packet?.votes).concat(cases.flatMap(entry => rows(entry.votes)));
    const executor = 'agent-world-local-test-executor-v1';
    const diagnostic = vote => vote.model_version === executor && vote.failure_domain === 'local_test_executor:' + executor;
    return `<section class="aw-detail-section"><h3>Проверка Court</h3>${cases.map(entry => `<div class="aw-context"><span class="aw-context-mark">COURT</span><span>Вердикт: ${esc(entry.verdict || entry.status || 'не определён')} · кворум ${esc(entry.quorum || 'не указан')} · исполнение ${entry.execution_allowed === true ? 'проверяется отдельно сервером' : 'не разрешено'}</span></div><details class="aw-technical"><summary>Пакет доказательств Court</summary><code>${esc(entry.packet_sha256 || 'Не предоставлен')}</code></details>`).join('')}${votes.length ? votes.map(vote => `<article class="aw-domain-card"><div class="aw-inline"><strong>${diagnostic(vote) ? 'Локальный проверяющий · SYNTHETIC' : 'Проверяющий Court'}</strong>${badge(vote.status || vote.verdict)}</div><p class="aw-text">${esc(vote.summary || vote.rationale || vote.reason || '')}</p>${diagnostic(vote) ? '<p class="aw-note">Ответ получен от локального тестового исполнителя. Настроенный внешний провайдер не вызывался. Общий локальный failure domain не подтверждает независимость провайдеров.</p>' : ''}<div class="aw-domain-card-meta"><span>Уверенность: ${esc(vote.confidence ?? 'не измерена')}</span></div><details class="aw-technical"><summary>Настроенное подключение, исполнитель и идентификаторы</summary><dl class="aw-detail-grid"><div><dt>Настроенный провайдер</dt><dd>${esc(vote.provider_key || 'Не предоставлен')}</dd></div><div><dt>Настроенная модель</dt><dd>${esc(vote.model_key || vote.model || 'Не предоставлена')}</dd></div><div><dt>Фактический исполнитель / версия</dt><dd>${esc(vote.model_version || 'Не предоставлен')}</dd></div><div><dt>Failure domain</dt><dd>${esc(vote.failure_domain || 'Не предоставлен')}</dd></div></dl><div class="aw-hash">SESSION ${esc(vote.session_id || 'Не предоставлен')}<br>PACKET ${esc(vote.packet_sha256 || 'Не предоставлен')}</div></details>${vote.task_id ? `<button class="aw-link-button" data-aw-task="${esc(vote.task_id)}">Задание проверяющего →</button>` : ''}</article>`).join('') : '<p class="aw-note">Проверяющие ещё не представили результаты. Отсутствие голосов не является одобрением.</p>'}<p class="aw-note">В панели нет кнопки выдачи голоса от имени модели. Review запускает проверку backend; новые права и торговые действия не выдаются.</p></section>`;
  }
  function externalTaskProvenance(task) {
    if (task.source_kind !== 'external_agent_task_v1') return '';
    return `<section class="aw-detail-section"><h3>Внешний агент · происхождение результата</h3><p>Какая модель работает внутри агента, неизвестно (unknown / externally managed): ею управляет внешний сервис. Поэтому результат не входит в рейтинг моделей.</p>${task.external_call === false ? `<p class="aw-note">Внешний сервис не вызывался.${task.cost_usd == null ? ' Денежная стоимость в сохранённой квитанции не записана; неизвестное значение не заменяется нулём.' : ''}</p>` : ''}</section>`;
  }
  const SELECTION_MODES = Object.freeze({ explicit_override: 'Выбрано человеком',
    router_approved: 'Выбрано Router после явного подтверждения', single_available: 'Единственное доступное подключение' });
  function modelSelectionPanel(selection) {
    // The server's stored record of how this connection was chosen. Nothing
    // here is inferred: an absent record is simply not shown.
    if (!selection || typeof selection !== 'object') return '';
    return `<section class="aw-detail-section"><h3>Выбор подключения</h3><dl class="aw-detail-grid">`
      + `<div><dt>Способ выбора</dt><dd>${esc(SELECTION_MODES[selection.mode] || selection.mode || 'не указан')}</dd></div>`
      + `<div><dt>Подключение</dt><dd><span class="aw-hash">${esc(String(selection.model_id || '').slice(0, 8))}</span> · ${esc(selection.model_key || '')}</dd></div>`
      + `<div><dt>Провайдер</dt><dd>${esc(selection.provider_key || 'не указан')}</dd></div>`
      + `<div><dt>Ревизия подключения</dt><dd>${esc(String(selection.model_revision ?? ''))}</dd></div>`
      + `</dl><p class="aw-field-hint">Причина: ${esc(selection.reason || 'не указана')}. Фактическая модель ответа указана в происхождении результата.</p></section>`;
  }
  function intentPanel(intent) {
    // Everything here is the server's own Intent record. The panel neither
    // recomputes a state nor decides whether the work may proceed.
    if (!intent) return '';
    const goal = intent.goal || {}, limits = intent.constraints || {}, evidence = intent.required_evidence || {};
    const request = goal.request === undefined || goal.request === null ? '' : publicJSON(goal.request);
    return `<section class="aw-detail-section"><h3>Поручение</h3>`
      + `<div class="aw-inline">${badge(intent.status)}<span class="aw-status aw-info">ревизия ${count(intent.revision)}</span></div>`
      + `<dl class="aw-detail-grid">`
      + `<div><dt>Цель</dt><dd>${esc(goal.text || 'Не указана')}</dd></div>`
      + `<div><dt>Режим согласования</dt><dd>${esc(APPROVAL_LABELS[intent.approval_mode] || intent.approval_mode || 'не указан')}</dd></div>`
      + `<div><dt>Уровень риска</dt><dd>${esc(RISK_LABELS[limits.risk] || limits.risk || 'не указан')}</dd></div>`
      + `<div><dt>Срок</dt><dd>${esc(date(limits.deadline))}</dd></div>`
      + `<div><dt>Требуемое доказательство</dt><dd>${esc(evidence.rubric_label || evidence.rubric_key || 'не указано')}</dd></div>`
      + `</dl>`
      + `<p class="aw-field-hint">${evidence.verified_by === 'independent_local_evidence_verifier' ? 'Независимая проверка сохранённых доказательств.' : 'Проверяющий механизм указан в технических деталях.'} Приёмка человеком — отдельное решение и не является оценкой качества.</p>`
      + `<details class="aw-technical"><summary>Технические сведения поручения</summary><dl class="aw-detail-grid"><div><dt>Workspace</dt><dd>${esc((intent.scope || {}).workspace_id || 'Не указан')}</dd></div><div><dt>Verifier</dt><dd>${esc(evidence.verified_by || 'Не указан')}</dd></div></dl></details>`
      + (request ? `<details class="aw-technical"><summary>Что именно было запрошено</summary><pre>${esc(request)}</pre></details>` : '')
      + `<p class="aw-field-hint">Поручение не редактируется после создания задачи: его значением связаны запрос, ответ и проверка. Пока работа не началась, поручение можно остановить — «Отменить задачу». Нужны другие условия — отправьте новый запрос; прежнее поручение и его история сохраняются.</p>`
      + `</section>`;
  }
  if (typeof module === 'object' && module.exports) { module.exports = { esc, number, count, pct, date, statusMeta, badge, rows, items, taskMatches, taskState, taskTitle, taskClass, taskBadge, evaluationMeta, phaseOf, phaseLabel, rubricLabel, stageName, machineKey, availabilityMeta, occupancyMeta, readinessGrid, technicalSplit, technicalDetails, AVATAR_KEYS, applicationRows, applicationTable, safeArtifactUrl, sourceMeta, overviewOutcomes, realChatCommands, canRunDemo, flagRows, captureChart, knownDomain, allowedDomainActions, domainFormFields, domainPayload, actionLabel, domainError, publicJSON, externalAgentCard, handoffCard, followupCard, modelConnectionGuide, modelProtocolCard, personaVoiceFields, personaReadText, personaCanSpeak, personaSpeechEnvelope, personaAudioStatus, personaPresentationCard, processCandidatePayload, processCandidateCard, processIntelligencePanel, reputationPanel, intentPanel, modelSelectionPanel, validCoordinatorPreview, coordinatorApproval, connectionLabel }; return; }

  root.UI.ready(async function () {
    const UI = root.UI, API = root.API.http;
    const qs = (selector, parent) => (parent || document).querySelector(selector);
    const qsa = (selector, parent) => Array.from((parent || document).querySelectorAll(selector));
    const shell = qs('#aw-center');
    if (!shell) return;
    let overview = null, tab = 'overview', filter = 'all', query = '', workRows = [], nextCursor = null;
    let detail = null, detailTab = 'summary', detailKind = '', profile = null, currentDrawer = null, returnFocus = null;
    let domainState = null, actionForm = null, mutationBusy = false;
    const domainCache = new Map();
    let generation = 0, overviewGeneration = 0, detailGeneration = 0, debounceTimer = null, disposed = false, demoBusy = false, demoKey = null;
    let refreshing = false, quietDrawer = false, pendingListReads = 0;
    let personaFaceGeneration = 0;
    const signal = UI.signal();
    const personaAudio = root.PersonaAudio?.create({
      host: root,
      requestSpeech: request => {
        if (!API.aiControlCenterPersonaSpeak) throw { status: 404 };
        return API.aiControlCenterPersonaSpeak(request.persona_id, personaSpeechEnvelope(request, root.crypto.randomUUID()));
      },
      beforeStart: () => { if (UI.agentSpeakStop) UI.agentSpeakStop(); },
      playFace: (face, options) => {
        if (!face || !UI.agentFacePlay) return;
        const faceRequest = ++personaFaceGeneration, video = qs('video', face);
        const start = () => { if (faceRequest === personaFaceGeneration && face.isConnected !== false && personaAudio.activePersona()) UI.agentFacePlay(face, options); };
        // The shared helper can await media data. Keep that wait under this
        // controller's generation, so a late clip cannot restart after close.
        if (video?.readyState >= 2) start();
        else if (video) video.addEventListener('loadeddata', start, { once: true });
      },
      pauseFace: face => { ++personaFaceGeneration; if (UI.agentFacePause) UI.agentFacePause(face); },
      reducedMotion: () => document.documentElement?.getAttribute('data-reduce-motion') === 'on',
      onState: view => {
        const box = currentDrawer && qs('#aw-persona-audio-status', currentDrawer);
        if (!box) return;
        box.textContent = personaAudioStatus(view);
        const details = qs('#aw-persona-audio-details', currentDrawer);
        if (details) details.textContent = publicJSON({ presentation: domainState?.item?.presentation, playback: view });
        const busy = ['preparing', 'speaking'].includes(view.state);
        const start = qs('[data-aw-persona-speak]', currentDrawer), stop = qs('[data-aw-persona-stop]', currentDrawer);
        if (start) start.disabled = busy || !personaCanSpeak(domainState?.item);
        if (stop) stop.disabled = !busy;
      },
    });
    const stopPersonaAudio = () => { if (personaAudio) personaAudio.stop(); };
    const visibilityAudio = () => { if (document.hidden) stopPersonaAudio(); };
    const capability = key => overview?.enabled === true && overview?.capabilities?.[key] === true;
    const actor = value => typeof value === 'object' && value ? value : { display_name: String(value || 'Не назначен') };
    const content = qs('#aw-content');
    const empty = (title, message, action) => `<div class="aw-empty"><strong>${esc(title)}</strong><p>${esc(message)}</p>${action ? `<div class="aw-actions">${action}</div>` : ''}</div>`;
    const smallEmpty = message => `<div class="aw-small-empty">${esc(message)}</div>`;
    const panel = (title, body, extra) => `<section class="aw-panel"><header class="aw-panel-heading"><h2>${esc(title)}</h2>${extra || ''}</header><div class="aw-panel-body">${body}</div></section>`;
    const note = text => `<p class="aw-note">${esc(text)}</p>`;
    const plural = (value, one, few, many) => {
      const n = Math.max(0, Math.floor(number(value) || 0)), tens = n % 10, hundreds = n % 100;
      return count(n) + ' ' + (tens === 1 && hundreds !== 11 ? one : tens >= 2 && tens <= 4 && (hundreds < 12 || hundreds > 14) ? few : many);
    };
    // A drawer or inspector shows its shape while it loads instead of one grey line.
    const loadingBlock = caption => `<div class="aw-skeleton-lines" aria-busy="true" aria-label="${esc(caption)}"><span></span><span></span><span></span><span></span></div><div class="aw-skeleton-cards" aria-hidden="true"><div class="aw-skeleton"></div><div class="aw-skeleton"></div></div><p class="aw-loading-caption">${esc(caption)}</p>`;
    const taskLink = (id, label) => id ? `<button class="aw-link-button" data-aw-task="${esc(id)}">${esc(label || 'Открыть задачу')} →</button>` : '';
    // Until a Persona gets a photo of its own it wears this one standard face.
    const standardFace = () => '<svg class="aw-std-face" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="9" r="4" fill="currentColor"/><path d="M4 21c1-4.5 4.5-7 8-7s7 2.5 8 7" fill="currentColor"/></svg>';
    const avatar = (value, size) => {
      const person = actor(value), key = String(person.avatar_key || '').toLowerCase();
      const image = AVATAR_KEYS.includes(key) && UI.agentAvatarHtml ? UI.agentAvatarHtml(key, { size: 'sm' }) : standardFace();
      return `<span class="aw-avatar${size ? ` aw-avatar-${esc(size)}` : ''}" aria-hidden="true">${image}</span>`;
    };
    const progress = task => number(task.progress_pct) == null ? `<span class="aw-muted">${esc(task.display_status_label || phaseLabel(task))}</span>` : `<span class="aw-progress"><progress max="100" value="${Math.min(100, Math.max(0, number(task.progress_pct)))}" aria-label="Выполнено ${esc(pct(task.progress_pct))}"></progress><span>${esc(pct(task.progress_pct))}</span></span>`;
    const cost = value => number(value) == null ? 'не измерено' : Number(value).toLocaleString('ru-RU', { style: 'currency', currency: 'USD', maximumFractionDigits: Number(value) > 0 && Number(value) < 0.0001 ? 8 : 4 });
    function announce(message, error) {
      const box = qs('#aw-notice'); box.textContent = message; box.hidden = !message; box.classList.toggle('aw-error', Boolean(error));
    }
    function refreshFaces(parent) {
      // Persona's clip is controlled by explicit playback. Do not register the
      // legacy hover animation, which would override a saved static preference.
      const visual = (parent || shell).querySelector?.('[data-aw-persona-visual]');
      (visual ? qsa('.agent-face', visual) : []).forEach(face => {
        if (!face.dataset || face.dataset.faceWired === '1') return;
        face.dataset.faceWired = '1';
        const video = qs('video', face);
        if (video) video.addEventListener('loadeddata', () => { if (!face.classList.contains('playing') && UI.agentFacePause) UI.agentFacePause(face); });
        if (UI.agentFacePause) UI.agentFacePause(face);
      });
      if (UI.wireAgentFaces) UI.wireAgentFaces(parent || shell);
    }
    function taskCard(task) {
      const cls = taskClass(task);
      const stage = task.stage_label || task.result_label || stageName(task.stage);
      return `<button class="aw-task-card" data-aw-task="${esc(taskId(task))}" data-aw-state="${esc(taskState(task))}"><span class="aw-task-card-top">${avatar(task.lead, 'sm')}<span class="aw-task-main"><span class="aw-task-title">${esc(taskTitle(task))}</span><span class="aw-task-stage">${esc(stage || 'Ожидает исполнения')}</span></span></span><span class="aw-task-meta"><span>Координатор: ${esc(name(task.lead))}</span>${cls ? `<span>${esc(cls)}</span>` : ''}<span>${esc(date(task.updated_at || task.created_at, true))}</span></span><span class="aw-task-foot">${taskBadge(task)}${progress(task)}</span></button>`;
    }
    function alertCard(item, compact) {
      // In the overview queue the reason is printed once above the list; the card
      // keeps what differs between items: state, title, time and the way in.
      const action = compact ? '' : item.action_hint || '', reason = compact ? '' : item.reason || item.detail || '';
      const when = item.since || item.updated_at || item.created_at;
      return `<div class="aw-alert"><div>${item.display_status ? taskBadge(item) : badge(item.severity || item.status || 'warning')}</div><div><strong>${esc(item.display_title || item.title || item.summary)}</strong>${reason ? `<p>${esc(reason)}</p>` : ''}${action ? `<p class="aw-alert-action">${esc(action)}</p>` : ''}<div class="aw-alert-foot">${when ? `<time datetime="${esc(when)}">${esc(date(when))}</time>` : ''}${taskLink(item.task_id || item.id)}</div></div></div>`;
    }
    function agentMini(agent) {
      const evaluation = evaluationMeta(agent);
      // A rating is shown only once something was observed: «0 наблюдений» on
      // every agent was noise, and an empty sample says nothing about quality.
      const observed = evaluation.sample > 0
        ? `<span class="aw-rating-mini"><strong>${esc(plural(evaluation.sample, 'наблюдение', 'наблюдения', 'наблюдений'))}</strong><small>${esc(evaluation.insufficient ? 'NEW · мало данных' : evaluation.label)} · ${esc(evaluation.classLabel)}</small></span>` : '';
      const doing = agent.current_task?.title || agent.current_task_title || role(agent);
      return `<button class="aw-team-row" data-aw-agent="${esc(agentId(agent))}" title="${esc(name(agent))}: ${esc(evaluation.label)}, выборка ${count(evaluation.sample)}, уверенность ${esc(evaluation.confidence)}">${avatar(agent)}<span class="aw-agent-identity"><span class="aw-agent-name">${esc(name(agent))}</span><span class="aw-agent-role">${esc(doing)}</span></span><span class="aw-row-end">${agentState(agent)}${observed}</span></button>`;
    }
    function timeline(events, full) {
      if (!events.length) return smallEmpty('Пока нет событий. Здесь появится история фактических действий, проверок и результатов.');
      const time = event => event.timestamp || event.created_at || event.at || event.time;
      return `<ol class="aw-timeline">${events.map(event => `<li><time datetime="${esc(time(event) || '')}" title="${esc(date(time(event)))}">${esc(date(time(event), !full))}</time><div><span>${esc(event.summary || event.title || event.event_type || event.type || 'Событие')}</span>${event.detail ? `<p>${esc(event.detail)}</p>` : ''}${event.task_id ? `<div>${taskLink(event.task_id)}</div>` : ''}</div></li>`).join('')}</ol>`;
    }
    function outcomeCard(outcome, index) {
      const source = sourceMeta(outcome), artifact = outcome.artifact || {}, url = safeArtifactUrl(artifact.url, source.kind);
      const image = (index === 0 || source.kind === 'desktop_chart') && url && ['image/svg+xml', 'image/png', 'image/jpeg', 'image/webp'].includes(artifact.media_type || artifact.mime_type);
      return `<article class="aw-outcome"><div class="aw-outcome-meta"><span class="aw-source aw-source-${esc(source.kind)}">${esc(source.label)}</span>${outcome.status ? taskBadge(outcome) : ''}</div><h3>${esc(outcome.title || 'Результат задачи')}</h3>${outcome.summary ? `<p>${esc(outcome.summary)}</p>` : ''}${image ? `<a class="aw-outcome-image" href="${esc(url)}" target="_blank" rel="noopener noreferrer"><img src="${esc(url)}" alt="${esc(artifact.title || outcome.title || 'Артефакт результата')}" loading="lazy" referrerpolicy="same-origin"></a>` : ''}<div class="aw-outcome-foot"><div class="aw-actions">${taskLink(outcome.task_id, 'Результат и действия')}${source.reportUrl ? `<a class="aw-link-button" href="${esc(source.reportUrl)}">Открыть исходный отчёт ↗</a>` : ''}</div><time datetime="${esc(outcome.created_at || '')}">${esc(date(outcome.created_at, true))}</time></div></article>`;
    }
    function realWorkHint() {
      const commands = realChatCommands(overview);
      if (!commands.length) return '';
      return panel('Примеры поручений', `<div class="aw-chat-hint"><p>Напишите в SF Chat обычным текстом, как в этих примерах. Стратегию, инструмент и период замените на свои.</p>${commands.map(command => `<div class="aw-command-example"><strong>${esc(command.title)}</strong><code>${esc(command.text)}</code></div>`).join('')}<p>Даты бэктеста — UTC; конечная дата не включается. Это исследование, не торговое исполнение. Снимок сохраняет текущий вид рабочего стола.</p></div>`, '<button class="aw-link-button" data-aw-real-chat>Открыть чат →</button>');
    }
    function taskRow(task) {
      const stage = task.stage_label || task.result_label || stageName(task.stage);
      const sub = [name(task.lead), stage && stage !== '—' ? stage : ''].filter(Boolean).join(' · ');
      const when = task.updated_at || task.created_at;
      return `<button class="aw-row" data-aw-task="${esc(taskId(task))}" data-aw-state="${esc(taskState(task))}">${avatar(task.lead, 'sm')}<span><span class="aw-row-title">${esc(taskTitle(task))}</span><span class="aw-row-sub">${esc(sub)}</span></span><span class="aw-row-end">${taskBadge(task)}${number(task.progress_pct) == null ? '' : progress(task)}<time datetime="${esc(when || '')}">${esc(date(when, true))}</time></span></button>`;
    }
    function queueNotes(items) {
      const seen = new Set();
      return items.map(item => [item.reason || item.detail || '', item.action_hint || ''].filter(Boolean).join(' '))
        .filter(text => text && !seen.has(text) && seen.add(text))
        .map(text => `<p class="aw-queue-note">${esc(text)}</p>`).join('');
    }
    // ---- Variant B, cell by cell from the owner-approved prototype (world2/b.html) ----
    const icon = (key, size) => `<svg class="aw-ic" viewBox="0 0 24 24" width="${size || 18}" height="${size || 18}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${AW_ICONS[key] || ''}</svg>`;
    const bcard = (title, iconKey, tone, body, more, extra) => `<section class="aw-bcard${extra ? ' ' + extra : ''}"><header class="aw-bcard-h">${iconKey ? `<span class="aw-icbox aw-t-${tone}">${icon(iconKey)}</span>` : ''}<h2 title="${esc(title)}">${esc(title)}</h2>${more ? `<span class="aw-bcard-more">${more}</span>` : ''}</header><div class="aw-bcard-b">${body}</div></section>`;
    const btile = (label, value, trend, iconKey, tone) => `<div class="aw-btile"><div><div class="aw-btile-k">${esc(label)}</div><div class="aw-btile-v">${esc(String(value))}</div><div class="aw-btile-t${trend.up ? ' aw-up' : ''}"${trend.title ? ` title="${esc(trend.title)}"` : ''}>${esc(trend.text)}</div></div><span class="aw-icbox aw-t-${tone}">${icon(iconKey)}</span></div>`;
    const bnum = (label, value, note) => `<div class="aw-num"><small>${esc(label)}</small><b>${esc(String(value))}</b>${note ? `<span class="aw-up">${esc(note)}</span>` : ''}</div>`;
    // List times read like the prototype (10:35). An entry from another day
    // shows its date instead, so yesterday's event never passes for today's.
    const sameDay = parsed => parsed.toDateString() === new Date().toDateString();
    const clock = value => {
      const parsed = new Date(value || '');
      if (!Number.isFinite(parsed.getTime())) return '—';
      return sameDay(parsed) ? parsed.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : parsed.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
    };
    const logTime = value => {
      const parsed = new Date(value || '');
      if (!Number.isFinite(parsed.getTime())) return '—';
      const time = parsed.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      return sameDay(parsed) ? time : parsed.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) + ' ' + time.slice(0, 5);
    };
    // The same NEW rule as the checks: fewer than three finished tasks give no
    // rating yet, so 100 % over two diagnostics never reads as proven quality.
    const rated = stats => stats.rate != null && stats.ok + stats.bad >= 3;
    const rateTitle = stats => stats.ok + stats.bad
      ? `Успешно ${stats.ok} из ${stats.ok + stats.bad} завершённых задач${rated(stats) ? '' : '; рейтинг появится после трёх'}. Это не оценка качества модели.`
      : 'Завершённых задач пока нет';
    function researchTiles() {
      const lab = overview?.summaries?.research || {}, closed = !overview?.summaries || Boolean(lab.unavailable);
      const tile = (label, key, iconKey, tone, meaning) => {
        const week = number(lab[key + '_week']) || 0;
        const trend = closed ? { text: 'Лаборатория AI владельца' } : week > 0 ? { up: true, text: '↑ ' + count(week) + ' за 7 дней', title: meaning } : { text: '— без изменений', title: meaning };
        return btile(label, closed ? '—' : count(lab[key]), trend, iconKey, tone);
      };
      return tile('Эксперименты', 'experiments', 'flask', 'violet', 'Новые эксперименты за последние 7 дней')
        + tile('Кандидаты', 'candidates', 'users', 'blue', 'Кандидаты, которые изменились за последние 7 дней')
        + tile('Чемпионы', 'champions', 'trophy', 'green', 'Чемпионы, которые изменились за последние 7 дней')
        + tile('Архивировано', 'archived', 'archive', 'gray', 'Ушли в архив за последние 7 дней');
    }
    // Activity of the owner's real work; steps of system test checks stay out.
    const ownerEvents = () => { const byTask = new Map(rows(overview?.tasks).map(task => [taskId(task), task]));
      return rows(overview?.activity).filter(event => { const task = byTask.get(String(event.task_id || '')); return event.synthetic !== true && (!task || ownerFacing(task)); }); };
    function activityRows(limit) {
      const byTask = new Map(rows(overview.tasks).map(task => [taskId(task), task]));
      const events = ownerEvents().slice(0, limit);
      if (!events.length) return smallEmpty('Пока нет событий. Здесь появится, кто что сделал и с каким результатом.');
      return events.map(event => {
        const task = byTask.get(String(event.task_id || '')), lead = task ? actor(task.lead) : null, when = event.time || event.timestamp || event.created_at;
        const who = lead ? name(lead) : 'Команда', raw = String(event.summary || event.title || 'Событие');
        const text = raw.startsWith(who + ' · ') ? raw.slice(who.length + 3) : raw;
        const inner = `<time datetime="${esc(when || '')}">${esc(clock(when))}</time>${lead ? avatar(lead, 'xs') : '<span class="aw-avatar aw-avatar-xs" aria-hidden="true">·</span>'}<span class="aw-clamp"><strong>${esc(who)}</strong> <span class="aw-muted">${esc(text)}</span></span>`;
        return event.task_id ? `<button class="aw-act" data-aw-task="${esc(event.task_id)}" title="${esc(who + ' · ' + text)}">${inner}</button>` : `<div class="aw-act">${inner}</div>`;
      }).join('');
    }
    // Memory is the team's own records plus the knowledge the Lab already works
    // from: rules of strategy development, lessons, reference strategies and
    // research materials.
    function memoryBody(summary, knowledge) {
      if ((!summary || summary.unavailable) && (!knowledge || knowledge.unavailable)) return smallEmpty('Память недоступна в этом рабочем пространстве.');
      const own = summary && !summary.unavailable ? summary : {}, base = knowledge && !knowledge.unavailable ? knowledge : {};
      const research = overview?.summaries?.research || { unavailable: true };
      const plus = own.capped ? '+' : '', day = value => number(value) > 0 ? '↑ ' + count(value) + ' за сутки' : '';
      const sum = (a, b) => (number(a) || 0) + (number(b) || 0);
      const lessons = [...rows(own.latest).filter(item => item.memory_class === 'verified_lesson').map(item => ({ id: item.id, title: item.title, when: item.created_at, record: true })),
        ...rows(base.latest).map(item => ({ title: item.title, when: item.updated_at, note: item.document }))].slice(0, 3);
      return `<div class="aw-nums">${bnum('Фрагменты памяти', count(sum(own.records, base.fragments)) + plus, day(own.records_day))}${bnum('Уроков извлечено', count(sum(own.verified_lessons, base.lessons)) + plus, day(own.lessons_day))}`
        + `<span title="Наши разработанные стратегии из исследований; образцы эталонной библиотеки сюда не входят">${bnum('Стратегий в памяти', count(sum(own.strategies, research.unavailable ? 0 : research.experiments)))}</span>${bnum('Источники данных', count(sum(own.sources, base.documents)))}`
        + `${number(base.reports) > 0 ? `<span title="Ежедневные и недельные отчёты команды владельцу">${bnum('Отчётов команды', count(base.reports))}</span>` : ''}</div>`
        + `<div class="aw-subtle">Последние уроки</div>`
        + (lessons.length ? lessons.map(item => item.record
          ? `<button class="aw-lesson" data-aw-domain-open="memory" data-aw-entity="${esc(item.id || '')}"><time>${esc(clock(item.when))}</time><span class="aw-clamp">${esc(item.title || 'Запись')}</span></button>`
          : `<button class="aw-lesson" data-aw-tab="memory" title="${esc(item.note || '')}"><time>${esc(clock(item.when))}</time><span class="aw-clamp">${esc(item.title)}</span></button>`).join('')
          : smallEmpty('Уроков пока нет: проверенный результат задачи можно сохранить в память.'));
    }
    function problemsBody() {
      const tasks = rows(overview.tasks).filter(ownerFacing), shown = task => String(task.display_status || task.status || '');
      // Three separate groups, as in the prototype: something went wrong; a
      // decision is needed or a request was turned down; a result is ready.
      const levels = tasks.map(task => [task, phaseOf(task) === 'failed' && shown(task) !== 'rejected' ? 'crit'
        : shown(task) === 'rejected' || phaseOf(task) === 'awaiting_decision' ? 'warn' : phaseOf(task) === 'awaiting_review' ? 'info' : '']).filter(([, level]) => level);
      const total = level => levels.filter(([, value]) => value === level).length;
      const when = task => task.updated_at || task.created_at || '';
      const ask = { crit: 'Не получилось', warn: 'Нужно ваше решение', info: 'Готов результат' };
      const list = levels.slice().sort(([a], [b]) => String(when(b)).localeCompare(String(when(a)))).slice(0, 5)
        .map(([task, level]) => `<button class="aw-alert-line aw-al-${level}" data-aw-ask="${esc(taskId(task))}" title="${esc([taskTitle(task), task.reason, 'Нажмите — Заместитель обсудит это с вами в чате'].filter(Boolean).join('. '))}"><span aria-hidden="true">${level === 'warn' ? '▲' : '●'}</span><time>${esc(clock(when(task)))}</time><span class="aw-clamp">${esc(ask[level])}: ${esc(taskTitle(task))}${task.reason ? ` <span class="aw-muted">— ${esc(task.reason)}</span>` : ''}</span></button>`);
      return `<div class="aw-sev"><div class="aw-sev-crit" title="Что-то пошло не так, Заместителю нужна ваша помощь"><small>Крити\u00ADческие</small><b>${count(total('crit'))}</b></div><div class="aw-sev-warn" title="Заместитель ждёт вашего решения"><small>Предупре\u00ADждения</small><b>${count(total('warn'))}</b></div><div class="aw-sev-info" title="Готов результат, который нужно посмотреть"><small>Информа\u00ADционные</small><b>${count(total('info'))}</b></div></div>`
        + (list.length ? list.join('') : '<div class="aw-calm"><span class="aw-clean-mark" aria-hidden="true">✓</span><span>Вопросов к вам нет. Если Заместителю понадобится ваше решение или что-то пойдёт не так, вопрос появится здесь.</span></div>');
    }
    function modelSummaryGroups() {
      const summary = overview?.summaries?.models;
      const known = summary && !summary.unavailable ? rows(summary.items).map(item => ({ model: item.model, provider: item.provider, connections: item.connections, active: item.active })) : undefined;
      return modelGroupsFromTasks(rows(overview.tasks), known);
    }
    // Own connections and the ones other people share with this person. A
    // shared one carries only its name; the connection stays with its owner.
    function modelConnections(data) { return items(data).concat(rows(data?.shared)); }
    function shareSection(connections, reopen, data) {
      const own = connections.filter(item => item.ownership !== 'shared');
      const theirs = connections.filter(item => item.ownership === 'shared');
      const usage = data?.shared_usage || {};
      const ownIds = new Set(own.map(item => item.id)), theirIds = new Set(theirs.map(item => item.id));
      const tokens = row => `${count(row.input_tokens)} / ${count(row.output_tokens)}`;
      const spend = row => row.cost_unknown_calls ? `${esc(cost(row.cost_usd))} + ${count(row.cost_unknown_calls)} без цены` : esc(cost(row.cost_usd));
      let html = '';
      if (own.length) {
        const switchable = own.some(item => rows(item.actions).some(action => action === 'share' || action === 'unshare'));
        const on = own.some(item => item.shared === true);
        html += `<label class="aw-switch-row"><input type="checkbox" data-aw-share="${esc(own.map(item => item.id).join(','))}" data-aw-share-reopen="${esc(reopen)}"${on ? ' checked' : ''}${data && switchable ? '' : ' disabled'}> Поделиться</label>`
          + `<p class="aw-muted aw-hint-line">${on ? 'Включено: другие пользователи могут вызывать эту модель. Ключ и настройки подключения остаются у вас. Выключение сразу запрещает новые чужие вызовы; история сохраняется.'
            : 'Выключено: модель доступна только вам. Если включить, другие пользователи смогут её вызывать, а ключ и настройки подключения останутся у вас.'}</p>`;
        const used = rows(usage.by_others?.by_caller).filter(row => ownIds.has(row.model_id));
        html += used.length ? `<h4>Использование другими</h4><table class="aw-mini-table"><thead><tr><th>Кто</th><th>Вызовов</th><th>Токены вх/вых</th><th>Стоимость</th><th>Последний</th></tr></thead><tbody>${used.map(row => `<tr><td>${esc(row.caller_name || 'Пользователь')}</td><td>${count(row.calls)}</td><td>${tokens(row)}</td><td>${spend(row)}</td><td>${esc(date(row.last_at))}</td></tr>`).join('')}</tbody></table><p class="aw-muted">Отдельно от ваших собственных запросов. Чужие чаты, память и задачи здесь не видны.</p>`
          : on ? '<p class="aw-muted">Другие пользователи этой моделью ещё не пользовались.</p>' : '';
        const recent = rows(usage.by_others?.recent).filter(row => ownIds.has(row.model_id));
        if (recent.length) html += `<details><summary>История общих вызовов</summary><table class="aw-mini-table"><thead><tr><th>Когда / кто</th><th>Задача / агент</th><th>Итог</th><th>Токены вх/вых</th><th>Стоимость</th></tr></thead><tbody>${recent.map(row => `<tr><td>${esc(date(row.at))}<br>${esc(row.caller_name || 'Пользователь')}</td><td>${esc(row.task || 'Разговор')}<br>${esc(row.agent || 'Проверка модели')}</td><td>${esc(row.status)}</td><td>${tokens(row)}</td><td>${row.cost_usd == null ? 'Цена неизвестна' : esc(cost(row.cost_usd))}</td></tr>`).join('')}</tbody></table><p class="aw-muted">Идентификаторы используются для учёта. Содержимое чужих поручений и диалогов не раскрывается.</p></details>`;
      }
      if (theirs.length) {
        html += `<p class="aw-note">${esc(theirs[0].note || 'Общая модель: ключ и настройки подключения остаются у владельца.')}</p>`;
        const mine = rows(usage.mine_through_others?.by_model).filter(row => theirIds.has(row.model_id));
        if (mine.length) {
          const sum = key => mine.reduce((total, row) => total + (number(row[key]) || 0), 0);
          html += `<p class="aw-model-spend"><span class="aw-muted">Ваши вызовы через общую модель:</span> ${count(sum('calls'))} · токены ${count(sum('input_tokens'))} / ${count(sum('output_tokens'))} · ${esc(cost(sum('cost_usd')))}</p>`;
        }
      }
      return html;
    }
    async function toggleShare(input) {
      const wanted = input.checked, data = cachedDomain('models');
      const chosen = new Set(String(input.dataset.awShare || '').split(',').filter(Boolean));
      const targets = items(data).filter(item => chosen.has(item.id)
        && rows(item.actions).includes(wanted ? 'share' : 'unshare'));
      if (!targets.length) { input.checked = !wanted; return; }
      input.disabled = true;
      try {
        for (const item of targets) await API.aiControlCenterDomainAction('models', item.id, wanted ? 'share' : 'unshare', { payload: {}, idempotency_key: root.crypto.randomUUID() });
        announce(wanted ? 'Модель открыта для общего доступа. Ключ и настройки остаются у вас.' : 'Общий доступ закрыт: новые чужие вызовы запрещены, история сохранена.');
      } catch (_) {
        input.checked = !wanted;
        announce('Общий доступ не изменён. Повторите попытку.', true);
      }
      domainCache.delete('models');
      await loadDomain('models');
      const reopen = String(input.dataset.awShareReopen || '');
      if (reopen.startsWith('lab:')) openLabModel(reopen.slice(4));
      else if (reopen.startsWith('group:')) openModelGroup(reopen.slice(6));
      await refresh({ background: true });
    }
    // The Lab lists registry models; a share belongs to the connection bound to
    // one of them, so the switch appears only where such a connection exists.
    function labShareSection(model) {
      const data = cachedDomain('models');
      if (!data || data.unavailable) return '';
      const bound = items(data).filter(item => item.registry_id && item.registry_id === model.id);
      if (!bound.length) {
        const available = rows(data.owner_bindings).some(item => item.id === model.id);
        return `<label class="aw-switch-row"><input type="checkbox" data-aw-registry-share="${esc(model.id)}"${available ? '' : ' disabled'}> Поделиться</label>`
          + `<p class="aw-muted">${available ? 'Другие пользователи смогут вызывать модель; ключ остаётся у вас.' : 'Общий доступ недоступен: требуется включённое текстовое подключение с ключом и настроенной стоимостью.'}</p>`;
      }
      return shareSection(bound, 'lab:' + model.id, data);
    }
    async function shareRegistry(input) {
      input.disabled = true;
      try {
        const bound = await API.aiControlCenterDomainAction('models', 'new', 'bind_catalog', {
          payload: { registry_id: input.dataset.awRegistryShare }, idempotency_key: root.crypto.randomUUID() });
        await API.aiControlCenterDomainAction('models', bound.id, 'share', { payload: {}, idempotency_key: root.crypto.randomUUID() });
        domainCache.delete('models'); await loadDomain('models');
        openLabModel(input.dataset.awRegistryShare);
        announce('Общий доступ включён. Ключ и настройки остаются у владельца.');
      } catch (_) { input.checked = false; input.disabled = false; announce('Не удалось открыть общий доступ. Проверьте подключение модели.', true); }
    }
    function modelTestControls(id, registry = false) {
      return `<div class="aw-model-test"><div class="aw-actions"><button class="btn sm" ${registry ? 'data-aw-registry-test' : 'data-aw-inline-test'}="${esc(id)}">Проверить модель</button></div><div data-aw-test-result role="status" aria-live="polite"></div></div>`;
    }
    function modelTestOutcome(result, registry = false) {
      const task = result?.task || result || {};
      const ok = registry ? result?.ok === true && result?.application_cache_hit !== true && !!String(result?.response || '').trim() : task.status === 'succeeded' && result?.evaluation?.passed === true && result?.synthetic !== true;
      const pending = !registry && ['planned', 'ready', 'queued', 'running', 'waiting', 'verifying'].includes(task.status);
      const code = String(result?.error_code || task.error_code || result?.error || '');
      const reason = /revoked|share.*denied|share.*not/.test(code) ? 'Владелец закрыл доступ к модели.'
        : /budget|quota|429|limit/.test(code) ? 'Исчерпан лимит запросов или расходов. Проверьте лимиты подключения.'
        : /key|auth|401|403|credential/.test(code) ? 'Провайдер не разрешил запрос. Проверьте ключ и доступ к модели.'
        : /timeout|timed.out/.test(code) ? 'Модель не ответила вовремя. Провайдер может быть временно недоступен.'
        : /inactive|disabled/.test(code) ? 'Подключение модели выключено.'
        : /json|response_invalid/.test(code) ? 'Провайдер вернул некорректный ответ.'
        : 'Не удалось получить корректный ответ. Проверьте подключение и доступность провайдера.';
      return { ok, pending, text: ok ? 'Модель отвечает, всё работает.' : pending ? 'Проверяем… Ожидаем ответ модели.' : reason,
        details: { status: task.status || (ok ? 'success' : 'failed'),
          model: result?.actual_model || undefined, error: code || undefined,
          response: String(result?.result_text || result?.response || '').slice(0, 1000) || undefined } };
    }
    async function testModelInline(button, registry = false) {
      if (button.disabled) return;
      const box = button.closest('.aw-model-test')?.querySelector('[data-aw-test-result]');
      if (!box) return;
      const show = view => { box.innerHTML = `<p class="${view.ok ? 'aw-good-text' : view.pending ? 'aw-muted' : 'aw-bad-text'}">${esc(view.text)}</p>${view.details ? `<details><summary>Технические детали</summary><pre>${esc(JSON.stringify(view.details, null, 2))}</pre></details>` : ''}`; };
      button.disabled = true; button.textContent = 'Проверяем…';
      show({ pending: true, text: 'Проверяем… Отправляем короткий запрос этой модели.' });
      try {
        let result;
        if (registry) result = await API.aiAgentTest(button.dataset.awRegistryTest);
        else {
          result = button.dataset.awTestTask
            ? await API.aiControlCenterDomainItem('model_tasks', button.dataset.awTestTask, { signal })
            : await API.aiControlCenterDomainAction('models', button.dataset.awInlineTest, 'test', { payload: {}, idempotency_key: root.crypto.randomUUID() });
          const id = result?.id || result?.task?.id;
          if (id) button.dataset.awTestTask = id;
          for (let attempt = 0; modelTestOutcome(result).pending && attempt < 45 && box.isConnected && !disposed; attempt++) {
            show(modelTestOutcome(result));
            await new Promise(resolve => setTimeout(resolve, 2000));
            if (!box.isConnected || disposed) return;
            result = await API.aiControlCenterDomainItem('model_tasks', id, { signal });
          }
        }
        const view = modelTestOutcome(result, registry);
        show(view.pending ? { ...view, text: 'Проверка ещё выполняется. Можно обновить результат; новый запрос модели не отправится.' } : view);
        if (!view.pending) delete button.dataset.awTestTask;
        domainCache.delete('models');
      } catch (error) {
        if (error?.name !== 'AbortError') show(modelTestOutcome({ error: error?.code || error?.message || 'connection_unavailable' }, true));
      } finally {
        button.disabled = false;
        button.textContent = button.dataset.awTestTask ? 'Обновить результат проверки' : 'Проверить модель';
      }
    }
    function modelCallButtons(connections) {
      return connections.map((item, index) => `${connections.length > 1 ? `<p class="aw-note">${item.ownership === 'shared' ? 'Общее подключение' : 'Подключение'} ${index + 1}</p>` : ''}${rows(item.actions).includes('test') ? modelTestControls(item.id) : ''}${rows(item.actions).includes('task') ? `<div class="aw-actions"><button class="btn sm" data-aw-card-model="${esc(item.id)}" data-aw-card-action="task">Дать задание</button></div>` : ''}`).join('');
    }
    function modelRows(groups) {
      if (!groups.length) return smallEmpty('Моделей пока нет. Подключите модель по API — она проверится одним запросом.');
      // The bar is the model's share of the team's tasks; spend against a limit
      // takes its place once tariffs and limits are recorded.
      const total = groups.reduce((sum, group) => sum + group.stats.total, 0);
      return groups.map(group => {
        const share = total ? Math.round(group.stats.total / total * 100) : 0;
        return `<button class="aw-mrow" data-aw-model-group="${esc(group.id)}"><span class="aw-icbox aw-t-cyan">${esc(prettyModel(group.id).slice(0, 1))}</span>`
          + `<span class="aw-mrow-main"><strong>${esc(prettyModel(group.id))}</strong>${rated(group.stats) ? '' : ' <span class="aw-chip aw-chip-new">новая · без рейтинга</span>'}${group.connections.length && group.connections.every(item => item.ownership === 'shared') ? ' <span class="aw-chip">общая</span>' : group.connections.some(item => item.shared === true) ? ' <span class="aw-chip">вы делитесь</span>' : ''}`
          + `<small>${group.stats.total ? esc(plural(group.stats.total, 'задача', 'задачи', 'задач')) : 'ещё не работала'} · ${esc(providerLabel(group.provider))} · ${esc(plural(group.connectionCount, 'подключение', 'подключения', 'подключений'))}</small>`
          + `<span class="aw-use" title="Доля задач команды: ${share}%"><span style="width:${share}%"></span></span></span>`
          + `<span class="aw-rate aw-rate-${rated(group.stats) ? rateTone(group.stats.rate) : 'none'}" title="${esc(rateTitle(group.stats))}">${rated(group.stats) ? esc(pct(group.stats.rate * 100)) : '—'}</span></button>`;
      }).join('');
    }
    function labModelBrief(models) {
      const busy = models.filter(model => model.enabled).slice(0, 5);
      if (!busy.length) return smallEmpty('Моделей пока нет. Подключите модель по API — она проверится одним запросом.');
      return busy.map(model => { const rate = labRate(model), left = quota(model);
        return `<button class="aw-mrow" data-aw-lab-model="${esc(model.id)}"><span class="aw-icbox aw-t-cyan">${esc(String(model.name || '?').slice(0, 1).toUpperCase())}</span>`
          + `<span class="aw-mrow-main"><strong>${esc(model.name || model.model)}</strong><small>${count(model.requests_month)} запросов за месяц · ${esc(usd(model.spend_month_usd))} · ${esc(left.text)}</small>`
          + `<span class="aw-use"><span style="width:${Math.round(left.used ?? 0)}%"></span></span></span>`
          + `<span class="aw-rate aw-rate-${rateTone(rate)}">${rate == null ? '—' : esc(pct(rate * 100))}</span></button>`; }).join('');
    }
    function renderOverview() {
      content.innerHTML = `<div class="aw-btiles">${researchTiles()}</div><div class="aw-brow3">`
        + bcard('Недавняя активность', 'grid', 'blue', activityRows(5), '<button class="aw-link-button" data-aw-open-log>Смотреть все</button>')
        + bcard('Память и уроки', 'brain', 'violet', memoryBody(overview?.summaries?.memory, overview?.summaries?.knowledge), '<button class="aw-link-button" data-aw-tab="memory">Перейти</button>')
        + bcard('Ошибки и предупреждения', 'alert', 'red', problemsBody(), '<button class="aw-link-button" data-aw-tab="work" data-aw-filter="attention">Смотреть все</button>')
        + `</div>` + bcard('Модели кратко', 'cpu', 'cyan', labModels()?.length ? labModelBrief(labModels()) : modelRows(modelSummaryGroups()), '<button class="aw-link-button" data-aw-tab="models">Все модели</button>');
    }
    function taskTable(tasks) {
      if (!tasks.length) return empty('Задач по этому фильтру нет', 'Измените фильтр или поиск. Новые задачи появятся здесь, как только команда их начнёт.');
      const measured = tasks.some(task => number(task.cost_usd) != null);
      return `<div class="aw-table-wrap"><table class="aw-table"><thead><tr><th>Задача</th><th>Исполнитель</th><th>Статус</th><th>Этап</th><th>Обновлено</th>${measured ? '<th>Стоимость</th>' : ''}</tr></thead><tbody>${tasks.map(task => {
        const people = rows(task.participants);
        return `<tr><td><button class="aw-table-title" data-aw-task="${esc(taskId(task))}">${esc(taskTitle(task))}</button><div class="aw-table-sub">${esc(taskClass(task))}${task.synthetic ? ' <span class="aw-tag">ТЕСТ</span>' : ''}</div></td><td><span class="aw-people">${avatar(task.lead, 'sm')}${esc(name(task.lead))}${people.length ? `<span class="aw-faces" title="${esc(people.map(name).join(', '))}">${people.slice(0, 4).map(person => avatar(person, 'sm')).join('')}</span>` : ''}</span></td><td>${taskBadge(task)}${phaseOf(task) === 'executing' && number(task.progress_pct) != null ? progress(task) : ''}</td><td>${esc(task.result_label || stageName(task.stage))}</td><td>${esc(date(task.updated_at || task.created_at))}</td>${measured ? `<td>${esc(cost(task.cost_usd))}</td>` : ''}</tr>`;
      }).join('')}</tbody></table></div>`;
    }
    function workQueue() {
      const tasks = rows(overview.tasks).filter(ownerFacing), stats = overview.stats || {};
      const active = tasks.filter(task => task.is_active === true || task.is_active == null && taskMatches(task, 'active', ''));
      const awaitingDecision = tasks.filter(task => phaseOf(task) === 'awaiting_decision');
      const awaitingReview = tasks.filter(task => phaseOf(task) === 'awaiting_review');
      const failedTasks = tasks.filter(task => phaseOf(task) === 'failed');
      const outcomes = overviewOutcomes(overview).filter(outcome => outcome.synthetic !== true).slice(0, 3);
      const attentionKnown = Array.isArray(overview.attention), alerts = rows(overview.attention).filter(item => ownerFacing(item) && !['info', 'healthy'].includes(item.severity || item.status));
      // One queue for everything that waits on the person. The two waiting phases
      // stay named separately: a pending check is not a decision on the owner.
      const summary = [
        awaitingDecision.length ? `<span class="aw-status aw-warning">Ожидают вашего решения · ${count(awaitingDecision.length)}</span>` : '',
        awaitingReview.length ? `<span class="aw-status aw-review">Ожидают проверки · ${count(awaitingReview.length)}</span>` : '',
        failedTasks.length ? `<span class="aw-status aw-error">Ошибки · ${count(failedTasks.length)}</span>` : '',
      ].join('');
      const queue = alerts.length
        ? `${summary ? `<div class="aw-queue-summary">${summary}</div>` : ''}${queueNotes(alerts.slice(0, 3))}<div class="aw-stack">${alerts.slice(0, 3).map(item => alertCard(item, true)).join('')}</div>${alerts.length > 3 ? `<div class="aw-panel-more"><button class="aw-link-button" data-aw-tab="work" data-aw-filter="attention">Показать все (${count(alerts.length)}) →</button></div>` : ''}`
        : attentionKnown && !alerts.length
          ? `<div class="aw-calm"><span class="aw-clean-mark" aria-hidden="true">✓</span><span>Сейчас от вас ничего не требуется. Проверки и решения появятся здесь, как только команда их запросит.</span></div>`
          : smallEmpty('Сводка подтверждений пока не опубликована. Отсутствие данных не означает, что все проверки пройдены.');
      const recent = tasks.filter(task => !ATTENTION_PHASES.includes(phaseOf(task)));
      const shownWork = (active.length ? active : recent).slice(0, 5);
      const workBody = shownWork.length ? `<div class="aw-row-list">${shownWork.map(taskRow).join('')}</div>`
        : tasks.length ? `<div class="aw-calm"><span>Сейчас ничего не выполняется. Задачи, которые ждут вас, — в блоке рядом.</span></div>`
          : smallEmpty('Задач пока нет. Напишите Заместителю, чтобы дать команде первое поручение.');
      return `<div class="aw-work-queue"><div class="aw-column aw-column-work">${panel('Нужно ваше действие', queue, `<span class="aw-count">${count(alerts.length)}</span>`)}${panel(active.length ? 'Сейчас в работе' : 'Последние задачи', workBody)}</div>`
        + `<div class="aw-column aw-column-results">${panel('Последние результаты', outcomes.length ? `<div class="aw-outcomes">${outcomes.map(outcomeCard).join('')}</div>` : smallEmpty('Результатов пока нет. Отчёты, снимки и ответы появятся здесь с указанием источника.'))}</div></div>`;
    }
    let showTests = false;
    const duty = () => cachedDomain('duty') || null;
    function dutyQuestions() {
      const state = duty();
      const questions = rows(state?.questions);
      if (!state || state.unavailable) return '';
      if (!questions.length) return `<section class="aw-bcard aw-duty"><header class="aw-bcard-h"><span class="aw-icbox aw-t-green">${icon('check')}</span><h2>Решения</h2>`
        + `<span class="aw-bcard-more aw-muted">${esc(state.mode === 'free' ? 'команда свободна' : state.message || '')}</span></header>`
        + `<div class="aw-bcard-b"><div class="aw-calm"><span class="aw-clean-mark" aria-hidden="true">✓</span><span>Решений от вас сейчас не ждут. Заместитель принесёт вопрос сюда, как только он появится.</span></div></div></section>`;
      return `<section class="aw-bcard aw-duty"><header class="aw-bcard-h"><span class="aw-icbox aw-t-red">${icon('alert')}</span><h2>Нужно ваше решение</h2>`
        + `<span class="aw-bcard-more aw-muted">принёс Заместитель · ${count(state.question_count)}</span></header><div class="aw-bcard-b"><div class="aw-stack">`
        + questions.map(dutyCard).join('') + '</div></div></section>';
    }
    function dutyCard(question) {
      const buttons = question.kind === 'incident'
        ? rows(question.decisions).map(choice => `<button class="btn sm${choice.value === 'create_task' ? ' primary' : ''}" data-aw-duty-decide="${esc(question.id)}" data-aw-decision="${esc(choice.value)}">${esc(choice.label)}</button>`).join('')
        : `<button class="btn sm primary" data-aw-duty-answer="${esc(question.id)}">Ответить</button>`;
      return `<article class="aw-duty-card aw-al-${esc(question.level || 'info')}"><div class="aw-duty-head"><strong>${esc(question.title)}</strong>`
        + `<time>${esc(question.at_utc ? clock(question.at_utc) : '')}</time></div>`
        + (question.detail ? `<p class="aw-duty-detail">${esc(String(question.detail).slice(0, 400))}</p>` : '')
        + (question.recommendation ? `<p class="aw-muted">Предложение: ${esc(question.recommendation)}</p>` : '')
        + `<div class="aw-actions">${buttons}</div></article>`;
    }
    async function dutyDecide(id, decision, button) {
      if (button) button.disabled = true;
      try {
        await API.aiControlCenterDutyDecide(id, decision, '');
        announce('Решение передано Заместителю.'); domainCache.delete('duty'); await refresh();
      } catch (reason) { UI.toast(reason?.message || 'Заместитель не смог применить решение.'); if (button) button.disabled = false; }
    }
    async function dutyAnswer(id) {
      const text = await UI.promptDialog?.({ title: 'Ответ Заместителю', label: 'Что ответить по этому поручению?', confirmText: 'Отправить' });
      if (!text) return;
      try {
        await API.aiControlCenterDutyAnswer(id, String(text));
        announce('Ответ передан.'); domainCache.delete('duty'); await refresh();
      } catch (reason) { UI.toast(reason?.message || 'Ответ не принят.'); }
    }
    async function dutyControl(action, button) {
      if (button) button.disabled = true;
      try {
        if (action === 'pause') await API.aiControlCenterDutyPause(60, 'Решение владельца');
        else if (action === 'resume') await API.aiControlCenterDutyResume();
        else await API.aiControlCenterDutyCheck();
        announce(action === 'pause' ? 'Команда на паузе.' : action === 'resume' ? 'Команда вернулась к работе.' : 'Проверка запущена.');
        domainCache.delete('duty'); await refresh();
      } catch (reason) { UI.toast(reason?.message || 'Не удалось выполнить.'); } finally { if (button) button.disabled = false; }
    }
    function teamControl() {
      const state = duty();
      if (!state || state.unavailable) return '';
      const resting = state.resting?.active;
      const working = rows(state.working).filter(row => row.working);
      return `<div class="aw-team-control"><span class="aw-team-state${resting ? ' aw-warn' : ''}">${resting ? 'Команда на паузе' : working.length ? `Сейчас работают: ${esc(working.map(row => row.name).join(', '))}` : 'Команда свободна'}</span>`
        + `<span class="aw-team-buttons">${resting ? '<button class="btn sm primary" data-aw-duty="resume">Вернуть к работе</button>' : '<button class="btn sm" data-aw-duty="pause">Дать паузу на час</button>'}`
        + `<button class="btn sm" data-aw-duty="check">Проверить сейчас</button></span></div>`;
    }
    function renderWork() {
      const tests = workRows.filter(task => !ownerFacing(task)).length;
      const filters = { all: 'Все', attention: 'Нужно ваше действие', active: 'В работе', waiting: 'Ждут результата', review: 'Ждут решения', completed: 'Завершённые', failed: 'Ошибки' };
      // A separate view for what the five planned views do not cover: checking
      // and accepting results, the full task list and the extra tools.
      content.innerHTML = `<div class="aw-work-view"><div class="aw-work-intro"><div><h2>Задачи</h2><p>Вопросы к вам, результаты на приём и все поручения команды.</p></div></div>`
        + dutyQuestions()
        + workQueue()
        + `<div class="aw-toolbar"><div class="aw-filters" aria-label="Фильтр задач">${Object.entries(filters).map(([key, label]) => `<button class="aw-filter" data-aw-filter="${key}" aria-pressed="${filter === key}">${label}</button>`).join('')}</div><input type="search" id="aw-task-search" class="aw-search" placeholder="Найти задачу или агента…" aria-label="Поиск задач" maxlength="160" value="${esc(query)}"></div>`
        + `<div id="aw-work-table">${taskTable(workRows.filter(task => (showTests || ownerFacing(task)) && taskMatches(task, filter, query)))}</div>`
        + (tests ? `<p class="aw-tests-toggle"><button class="aw-link-button" data-aw-show-tests aria-pressed="${showTests}">${showTests ? 'Скрыть тестовые проверки системы' : `Показать тестовые проверки системы (${count(tests)})`}</button> <span class="aw-muted">— они выполняются сами и не требуют вашего участия.</span></p>` : '')
        + `${nextCursor ? '<div class="aw-pagination"><button class="btn" id="aw-load-more">Показать ещё</button></div>' : ''}${realWorkHint()}${legacyCard()}</div>`;
    }
    // Legacy / Архив: the old «AI агенты» registry, frozen and read-only. It is
    // kept here, outside the five planned views, because it is not part of the
    // working system: nothing routes, rates or executes from it any more.
    // The screens of the previous architecture: out of the working path,
    // readable by their own address for сверка, unable to change anything.
    const LEGACY_SCREENS = Object.freeze([
      ['ai-agents.html?legacy=1', 'AI Agents', 'старый реестр моделей, ключей и квот — теперь архив и вкладка «Модели»'],
      ['ai-lab.html?legacy=1', 'AI Lab', 'прежний исследовательский контур — теперь вкладка «Исследования»'],
    ]);
    function legacyScreens() {
      return `<h3>Экраны прежней архитектуры</h3><p class="aw-muted">Убраны из рабочего пути. Открыть можно для сверки: смотреть — да, изменить оттуда что-либо — нет.</p>`
        + `<ul class="aw-legacy-list">${LEGACY_SCREENS.map(([href, title, note]) => `<li><a href="${esc(href)}" target="_blank" rel="noopener">${esc(title)}</a> — ${esc(note)}</li>`).join('')}</ul>`;
    }
    function legacyCard() {
      const legacy = overview?.summaries?.legacy;
      if (!legacy || legacy.unavailable) return '';
      if (!legacy.archived) return `<section class="aw-bcard aw-legacy"><header class="aw-bcard-h"><span class="aw-icbox aw-t-gray">${icon('archive')}</span><h2>Legacy / Архив</h2></header>`
        + `<div class="aw-bcard-b">${legacyScreens()}</div></section>`;
      const when = legacy.frozen_at_utc ? clock(legacy.frozen_at_utc) : '';
      return `<section class="aw-bcard aw-legacy"><header class="aw-bcard-h"><span class="aw-icbox aw-t-gray">${icon('archive')}</span><h2>Legacy / Архив</h2>`
        + `<span class="aw-bcard-more aw-muted">старый реестр «AI агенты»${when ? ' · снят ' + esc(when) : ''}</span></header><div class="aw-bcard-b">`
        + `<p class="aw-muted">Только для чтения. Ни маршрутизация, ни рейтинги текущих назначений, ни исполнение задач его не читают.</p>`
        + `<div class="aw-legacy-nums"><span><b>${count(legacy.models)}</b> моделей</span><span><b>${count(legacy.calls)}</b> вызовов в истории</span>`
        + `<span class="${legacy.reconciled ? 'aw-ok' : 'aw-warn'}">${legacy.reconciled ? 'сверка сошлась' : 'сверка не сошлась'}</span></div>`
        + `<div class="aw-actions"><button class="btn sm" data-aw-legacy="agents">Как было устроено</button><button class="btn sm" data-aw-legacy="calls">История работ</button><button class="btn sm" data-aw-legacy="report">Отчёт сверки</button></div>`
        + legacyScreens()
        + `</div></section>`;
    }
    const LEGACY_VIEWS = { agents: 'Старый реестр: как было устроено', calls: 'Старый реестр: история работ', report: 'Сверка: архив → миграция → новый реестр' };
    async function openLegacy(view) {
      ++detailGeneration; detailKind = 'legacy'; actionForm = null;
      const mine = detailGeneration;
      openDrawer(LEGACY_VIEWS[view] || 'Legacy / Архив', '<div class="aw-skeleton-lines"></div>', { size: 'wide' });
      let data = null, failed = '';
      try {
        data = view === 'agents' ? await API.aiControlCenterLegacyAgents() : view === 'calls' ? await API.aiControlCenterLegacyCalls() : await API.aiControlCenterLegacyReport();
      } catch (reason) { failed = reason?.message || 'Архив сейчас недоступен.'; }
      if (mine !== detailGeneration || !currentDrawer) return;
      const body = qs('.drawer-b', currentDrawer);
      if (!body) return;
      const inner = failed ? `<p class="aw-empty">${esc(failed)}</p>`
        : `<p class="aw-muted aw-legacy-note">Архив, только для чтения. Старые должности и назначения здесь — история; в работающей системе они не действуют.</p>` + legacyBody(view, data);
      body.innerHTML = `<div class="aw-inspector">${inner}</div>`;
    }
    function legacyBody(view, data) {
      if (view === 'agents') {
        const items = rows(data?.items);
        if (!items.length) return smallEmpty('В архиве нет записей о моделях.');
        return `<div class="aw-table-wrap"><table class="aw-lab-table aw-legacy-table"><thead><tr><th>Модель</th><th>Старая должность</th><th>Порядок</th><th>Группа ротации</th><th>Состояние тогда</th><th>Перенесена как факт</th></tr></thead><tbody>`
          + items.map(row => `<tr><td><strong>${esc(row.name || row.model || '—')}</strong><small>${esc(providerLabel(row.provider))} · ${esc(row.model || '')}</small></td>`
            + `<td>${esc(labRole(row.role) || '—')}${row.purpose ? `<small>${esc(row.purpose)}</small>` : ''}</td><td class="aw-num-cell">${row.priority == null ? '—' : count(row.priority)}</td>`
            + `<td>${esc(row.rotation_group || '—')}</td><td>${row.enabled ? 'включена' : 'выключена'}${row.disabled_reason ? `<small>${esc(row.disabled_reason)}</small>` : ''}</td>`
            + `<td>${row.migrated_as_fact ? 'да' : '<span class="aw-muted">нет</span>'}</td></tr>`).join('') + '</tbody></table></div>';
      }
      if (view === 'calls') {
        const items = rows(data?.items);
        if (!items.length) return smallEmpty('В истории архива нет вызовов.');
        return `<div class="aw-table-wrap"><table class="aw-lab-table aw-legacy-table"><thead><tr><th>Когда</th><th>Модель</th><th>Под какой ролью</th><th>Задача</th><th>Итог</th><th>Токенов</th><th>Стоимость</th></tr></thead><tbody>`
          + items.map(row => `<tr><td>${esc(row.at_utc ? clock(row.at_utc) : '—')}</td><td>${esc(row.model_name_at_the_time || row.model || '—')}${row.orphan ? '<small>модели уже нет в реестре</small>' : ''}</td>`
            + `<td>${esc(labRole(row.legacy_role) || '—')}</td><td>${esc(row.purpose || '—')}</td>`
            + `<td class="${row.status === 'success' ? 'aw-ok' : 'aw-warn'}">${esc(row.status || '—')}${row.error ? `<small>${esc(String(row.error).slice(0, 80))}</small>` : ''}</td>`
            + `<td class="aw-num-cell">${count(row.total_tokens)}</td><td class="aw-num-cell">${esc(usd(row.cost_usd))}</td></tr>`).join('') + '</tbody></table></div>';
      }
      const report = data?.report;
      if (!report) return smallEmpty('Отчёт сверки ещё не построен.');
      const pair = (label, value) => `<div class="aw-legacy-pair"><span>${esc(label)}</span><b>${esc(String(value))}</b></div>`;
      return `<div class="aw-legacy-report">`
        + `<h3>Было в старой системе</h3><div class="aw-legacy-grid">${pair('моделей', report.archive.agents)}${pair('записей о работе', report.archive.usage_rows)}${pair('оценок', report.archive.rating_entries)}${pair('архив сходится', report.archive.verified ? 'да' : 'нет')}</div>`
        + `<h3>Перенесено как история</h3><div class="aw-legacy-grid">${pair('моделей', report.migrated_as_history.models)}${pair('вызовов', report.migrated_as_history.calls)}${pair('связей «модель ↔ старая роль»', report.migrated_as_history.provenance_links)}${pair('оценок', report.migrated_as_history.ratings)}</div>`
        + `<h3>Сознательно не перенесено</h3><ul class="aw-legacy-list">${rows(report.not_migrated_on_purpose).map(row => `<li><b>${esc(row.field)}</b> — ${esc(row.reason)}${row.count ? ` (${count(row.count)})` : ''}</li>`).join('')}</ul>`
        + `<h3>Создано в новой системе</h3><div class="aw-legacy-grid">${pair('файлов реестра', report.new_entities.registry_files)}${pair('новых должностей', report.new_entities.agent_roles_created)}${pair('закреплений моделей', report.new_entities.model_pins_created)}</div>`
        + `<h3>Потери и ошибочные закрепления</h3><div class="aw-legacy-grid">${pair('моделей потеряно', rows(report.losses.models_missing).length)}${pair('вызовов потеряно', report.losses.calls_missing)}${pair('вызовов без модели', report.losses.orphan_calls)}${pair('моделей с должностью', rows(report.wrong_pins.models_with_a_position).length)}${pair('действующих старых связей', report.wrong_pins.active_legacy_links)}</div>`
        + `<p class="${report.ok ? 'aw-ok' : 'aw-warn'}">${report.ok ? 'Сверка сошлась: новый реестр — единственный рабочий.' : 'Сверка не сошлась: новый реестр рабочим не считается.'}</p></div>`;
    }
    const agentPhase = agent => {
      const status = String(agent?.status || '');
      if (BUSY_STATES.has(status) || agent?.current_task) return 'busy';
      return ['awaiting_review', 'awaiting_decision'].includes(status) ? 'waiting' : '';
    };
    // Success is counted only from finished, checked outcomes: accepted or
    // verified tasks against failed or rejected ones. Open work does not count.
    const taskOutcome = task => { const state = String(task.display_status || task.status || ''); return OK_STATES.has(state) ? 'ok' : BAD_STATES.has(state) ? 'bad' : 'open'; };
    function taskStats(list) {
      const ok = list.filter(task => taskOutcome(task) === 'ok').length, bad = list.filter(task => taskOutcome(task) === 'bad').length;
      const spent = list.reduce((sum, task) => sum + (number(task.cost_usd) || 0), 0), measured = list.some(task => number(task.cost_usd) != null);
      return { total: list.length, ok, bad, rate: ok + bad ? ok / (ok + bad) : null, spent: measured ? spent : null };
    }
    function agentBreakdown(list) {
      const byAgent = new Map();
      list.forEach(task => { const lead = actor(task.lead), key = agentId(lead) || name(lead); const row = byAgent.get(key) || { agent: lead, tasks: [] }; row.tasks.push(task); byAgent.set(key, row); });
      return [...byAgent.values()].map(row => ({ agent: row.agent, ...taskStats(row.tasks) })).sort((a, b) => b.total - a.total);
    }
    function modelGroupsFromTasks(tasks, connections) {
      const groups = new Map(), known = Array.isArray(connections);
      const group = (id, provider) => { if (!groups.has(id)) groups.set(id, { id, provider: provider || '', connections: [], connectionCount: 0, activeCount: 0, tasks: [] }); return groups.get(id); };
      rows(connections).forEach(connection => {
        if (!connection.model) return;
        const entry = group(String(connection.model), connection.provider);
        if (number(connection.connections) != null) { entry.connectionCount += number(connection.connections); entry.activeCount += number(connection.active) || 0; }
        else { entry.connections.push(connection); entry.connectionCount += 1; entry.activeCount += connection.status === 'active' ? 1 : 0; }
      });
      rows(tasks).forEach(task => {
        const id = task.model && String(task.model);
        if (id && !MODEL_EXCLUDED.has(id) && (!known || groups.has(id))) group(id, task.provider).tasks.push(task);
      });
      return [...groups.values()].map(entry => ({ ...entry, stats: taskStats(entry.tasks), byAgent: agentBreakdown(entry.tasks) }))
        .sort((a, b) => b.tasks.length - a.tasks.length || a.id.localeCompare(b.id));
    }
    const domainScope = () => JSON.stringify([overview?.scope?.environment, overview?.scope?.workspace_id, overview?.scope?.user_uuid]);
    function cachedDomain(key) { const hit = domainCache.get(key); return hit && hit.scope === domainScope() ? hit.data : null; }
    const domainReads = new Map();
    function loadDomain(key) {
      if (domainReads.has(key)) return domainReads.get(key);
      const scope = domainScope();
      // The owner's research catalogue belongs to the AI Lab; it is read only
      // when the Исследования tab opens and only through the Lab's own route.
      const lab = { lab_research: API.aiResearches, knowledge: API.aiKnowledgeBase, duty: API.aiControlCenterDuty }[key];
      const request = key in { lab_research: 1, knowledge: 1, duty: 1 }
        ? (lab ? lab({ signal }) : Promise.reject({ status: 404 }))
        : API.aiControlCenterDomain(key, { limit: 50 }, { signal });
      const read = request
        .catch(error => { if (error?.name === 'AbortError') throw error; return { items: [], unavailable: error?.status || 'error' }; })
        .then(data => { domainCache.set(key, { scope, data }); return data; })
        .finally(() => domainReads.delete(key));
      domainReads.set(key, read);
      return read;
    }
    // A task names its lead with a machine role; the team list has the words.
    function roleOf(agent) {
      const known = rows(overview?.agents).find(value => agentId(value) === agentId(agent));
      const text = role(known || agent);
      return machineKey(text) || text === 'Роль не указана' ? '' : text;
    }
    function teamPlacement(agents) {
      const used = new Set();
      // A Persona hired into a place sits only there; the older hints (face,
      // application role) place only Personas without one.
      const fits = (slot, agent) => agent.team_role ? agent.team_role === slot.key : slot.match(agent);
      const pick = slot => { const found = agents.find(agent => !used.has(agentId(agent)) && fits(slot, agent)); if (found) used.add(agentId(found)); return found; };
      const placed = TEAM_SLOTS.map(slot => [slot, pick(slot)]);
      return { placed, others: agents.filter(agent => !used.has(agentId(agent))) };
    }
    function teamSlot(slot, agent) {
      if (!agent) return `<button class="aw-person aw-person-empty" data-aw-hire="${esc(slot.key)}" title="${esc(slot.title)} — ${esc(slot.note)}. Место свободно: нажмите, чтобы выбрать агенту лицо и имя"><span class="aw-person-face" aria-hidden="true">+</span><span><b>${esc(slot.title)}</b><small>не назначен</small></span></button>`;
      const phase = agentPhase(agent);
      const state = phase === 'busy' ? 'работает' : phase === 'waiting' ? 'ждёт проверки' : 'свободен';
      return `<button class="aw-person${slot.lead ? ' aw-person-lead' : ''}${phase ? ' aw-person-' + phase : ''}" data-aw-agent-card="${esc(agentId(agent))}" title="${esc(name(agent))} · ${esc(slot.title)} · ${state}">${avatar(agent, 'sm')}<span><b>${esc(name(agent))}</b><small>${esc(slot.title)}</small></span></button>`;
    }
    // The owner's own profile photo, the one shown in the app's header.
    function ownerFace() {
      const user = UI.CURRENT_AUTH?.user || {};
      const url = String(user.avatar_url || '');
      return url.startsWith('/api/auth/avatar/')
        ? `<span class="aw-person-face aw-person-photo" aria-hidden="true"><img src="${esc(url)}" alt="" referrerpolicy="no-referrer"></span>`
        : `<span class="aw-person-face" aria-hidden="true">${icon('users', 15)}</span>`;
    }
    function teamChart(agents) {
      agents = agents.filter(agent => !RETIRED_PERSONA.has(String(agent.persona_status || '')));
      const { placed, others } = teamPlacement(agents);
      const slotsOf = dept => placed.filter(([slot]) => slot.dept === dept).map(([slot, agent]) => teamSlot(slot, agent)).join('');
      // A persona without a place in the scheme is not dropped: it is named
      // here and has its own card below the hierarchy.
      const outside = others.length ? `<p class="aw-org-others">Вне схемы: ${esc(plural(others.length, 'персона', 'персоны', 'персон'))} без роли в иерархии — ${esc(others.slice(0, 3).map(name).join(', '))}${others.length > 3 ? ' и другие' : ''}. Они есть в таблице ниже.</p>` : '';
      return `<div class="aw-org"><div class="aw-org-row"><span class="aw-person aw-person-owner aw-person-lead">${ownerFace()}<span><b>Вы</b><small>Владелец</small></span></span></div>`
        + `<div class="aw-org-line" aria-hidden="true"></div><div class="aw-org-row">${slotsOf('lead')}</div><div class="aw-org-line" aria-hidden="true"></div><div class="aw-org-row">${slotsOf('staff')}</div><div class="aw-org-line" aria-hidden="true"></div>`
        + `<div class="aw-org-depts">${TEAM_DEPTS.map(([key, title, sub]) => `<div class="aw-org-dept aw-org-${key}"><h3>${esc(title)}</h3><p>${esc(sub)}</p><div class="aw-org-slots">${slotsOf(key)}</div></div>`).join('')}</div>${outside}</div>`;
    }
    function agentModels(agent) {
      const id = agentId(agent);
      const tasks = rows(overview?.tasks).filter(task => agentId(actor(task.lead)) === id);
      return modelGroupsFromTasks(tasks).map(group => ({ model: group.id, ...group.stats }));
    }
    // The registry's usage log names the job a model worked for; these are the
    // same jobs in the team scheme.
    const LAB_ROLES_BY_PLACE = Object.freeze({ manager: ['orchestrator', 'chief_agent', 'telegram_assistant'], researcher: ['strategy_analyst', 'hypothesis_fallback'],
      ninjascript_coder: ['coder', 'compile_error_fixer_fallback'], backtester: ['backtest_analyst'], optimizer: ['optimizer'], accountant: ['accountant'],
      news_analyst: ['news_analyst', 'news'], judge_risk: ['risk_manager'] });
    const NAME_POOL = Object.freeze(['Олег', 'Лера', 'Сева', 'Толик', 'Артём', 'Дина', 'Гоша', 'Паша', 'Марина', 'Никита', 'Иван', 'Вера', 'Кирилл', 'Ника', 'Слава',
      'Алина', 'Денис', 'Мира', 'Егор', 'Злата', 'Роман', 'Ася', 'Лев', 'Тая', 'Фёдор', 'Ульяна', 'Глеб', 'Софья']);
    function autoTeamButton(agents) {
      const free = teamPlacement(agents.filter(agent => !RETIRED_PERSONA.has(String(agent.persona_status || '')))).placed.filter(([, agent]) => !agent).length;
      return free ? `<div class="aw-team-toolbar"><span class="aw-muted">Свободных мест: ${count(free)}</span><button class="btn sm primary" data-aw-auto-team title="Всем свободным местам — случайное имя и стандартное фото">Сформировать команду автоматически</button></div>` : '';
    }
    // Every free place gets a random unused name and the standard face; the
    // Manager keeps the owner's default name. Faces can be changed afterwards.
    async function autoTeam(button) {
      const agents = rows(overview?.agents).filter(agent => !RETIRED_PERSONA.has(String(agent.persona_status || '')));
      const free = teamPlacement(agents).placed.filter(([, agent]) => !agent).map(([slot]) => slot);
      if (!free.length) return;
      if (UI.confirmDialog && !(await UI.confirmDialog(`Добавить в команду ${plural(free.length, 'агента', 'агентов', 'агентов')} на свободные места? Имена выберутся случайно, фото — стандартное; изменить можно потом.`))) return;
      const taken = new Set(agents.map(agent => name(agent)));
      // A shuffle from the browser's cryptographic source: names are only chosen, never scored.
      const names = NAME_POOL.filter(value => !taken.has(value)).map(value => [root.crypto.getRandomValues(new Uint32Array(1))[0], value]).sort((a, b) => a[0] - b[0]).map(([, value]) => value);
      if (button) button.disabled = true;
      let hired = 0;
      try {
        for (const slot of free) {
          const chosen = slot.key === 'deputy' && !taken.has('Витёк') ? 'Витёк' : names.shift() || `${slot.title} ${hired + 1}`;
          const payload = { name: chosen, avatar_key: slot.key === 'deputy' ? 'vitek' : '', team_role: slot.key };
          const created = await API.aiControlCenterDomainAction('personas', 'new', 'create', { payload, idempotency_key: root.crypto.randomUUID() });
          const item = created?.item;
          if (item?.id && rows(item.actions).includes('activate')) {
            await API.aiControlCenterDomainAction('personas', item.id, 'activate', { payload: {}, idempotency_key: root.crypto.randomUUID(), expected_revision: item.revision });
          }
          hired += 1;
        }
        announce(`В команду добавлено ${plural(hired, 'агент', 'агента', 'агентов')}.`);
      } catch (reason) {
        announce(`Добавлено ${plural(hired, 'агент', 'агента', 'агентов')}; дальше ошибка: ${reason?.message || 'нет ответа'}.`, true);
      } finally { domainCache.clear(); await refresh(); }
    }
    // One row per agent: how much it works, how well, what was accepted or
    // turned down, and which models worked under it.
    function staffRow(agent, slot) {
      const id = agentId(agent), tasks = rows(overview?.tasks).filter(task => agentId(actor(task.lead)) === id), stats = taskStats(tasks);
      const labRoles = slot ? LAB_ROLES_BY_PLACE[slot.key] || [] : [];
      const lab = rows(labModels()).flatMap(model => rows(model.by_role).filter(row => labRoles.includes(row.role)).map(row => ({ ...row, model: model.name || model.model })));
      const calls = lab.reduce((sum, row) => sum + row.requests, 0), callsOk = lab.reduce((sum, row) => sum + row.ok, 0);
      const models = [...agentModels(agent).map(row => ({ label: prettyModel(row.model), n: row.total, rate: row.rate != null && row.ok + row.bad >= 3 ? row.rate : null })),
        ...lab.map(row => ({ label: row.model, n: row.requests, rate: row.requests >= 3 ? row.ok / row.requests : null }))].sort((a, b) => b.n - a.n);
      const last = [...tasks.map(task => task.updated_at || task.created_at), ...lab.map(row => row.last_at)].filter(Boolean).sort().pop();
      const decided = stats.ok + stats.bad, callRate = calls >= 3 ? callsOk / calls : null;
      const rate = rated(stats) ? stats.rate : callRate;
      return `<tr data-aw-agent-card="${esc(id)}" tabindex="0"><td><div class="aw-lab-name">${avatar(agent, 'sm')}<span><strong>${esc(name(agent))}</strong><small>${esc(slot ? slot.title : role(agent))}</small></span></div></td>`
        + `<td class="aw-num-cell">${count(tasks.length)}<small>вызовов моделей ${count(calls)}</small></td>`
        + `<td class="aw-num-cell"><b class="aw-rate aw-rate-${rateTone(rate)}">${rate == null ? (decided || calls ? 'NEW' : '—') : esc(pct(rate * 100))}</b></td>`
        + `<td class="aw-num-cell"><span class="aw-good-text">${count(stats.ok)}</span> / <span class="${stats.bad ? 'aw-bad-text' : 'aw-muted'}">${count(stats.bad)}</span></td>`
        + `<td>${models.length ? models.slice(0, 3).map(row => `<span class="aw-model-chip">${esc(row.label)} · ${count(row.n)}${row.rate == null ? '' : ' · ' + esc(pct(row.rate * 100))}</span>`).join('') : '<span class="aw-muted">моделей ещё не было</span>'}</td>`
        + `<td class="aw-num-cell">${esc(last ? clock(last) : '—')}</td></tr>`;
    }
    function staffTable(agents) {
      const live = agents.filter(agent => !RETIRED_PERSONA.has(String(agent.persona_status || '')));
      const { placed, others } = teamPlacement(live);
      const rowsOf = [...placed.filter(([, agent]) => agent).map(([slot, agent]) => staffRow(agent, slot)), ...others.map(agent => staffRow(agent, null))];
      return rowsOf.length ? `<div class="aw-table-wrap"><table class="aw-lab-table aw-staff-table"><thead><tr><th>Агент</th><th>Задач</th><th>Рейтинг</th><th>Одобрено / отклонено</th><th>Модели под агентом</th><th>Последняя работа</th></tr></thead><tbody>${rowsOf.join('')}</tbody></table></div>`
        + '<p class="aw-muted aw-hint-line">Рейтинг — доля одобренных результатов среди завершённых задач (NEW — меньше трёх); для должностей, где работают модели Лаборатории, — доля успешных вызовов. Нажмите на строку — подробности агента.</p>'
        : smallEmpty('Агентов пока нет.');
    }
    function renderAgents() {
      const agents = rows(overview.agents);
      const hint = '<span class="aw-bcard-hint">управляющий здесь вы: поручение идёт Заместителю, он распределяет работу, контролирует и возвращает итог; спорное — судьям, историю ведёт Секретарь</span>';
      content.innerHTML = agents.length
        ? bcard('Иерархия', 'users', 'green', teamControl() + autoTeamButton(agents) + teamChart(agents), hint) + bcard('Персонал', 'users', 'blue', staffTable(agents))
        : bcard('Иерархия', 'users', 'green', empty('Команда пока пуста', 'Сформируйте команду автоматически или нажмите на свободное место в схеме.', '<button class="btn primary" data-aw-auto-team>Сформировать команду автоматически</button>'), hint);
    }
    // The agent card is one element of the page: filled when a face or a card
    // is clicked, emptied when it closes.
    const agentPopOpen = () => { const pop = qs('#aw-agent-pop'); return Boolean(pop && !pop.hidden); };
    function closeAgentCard() { const pop = qs('#aw-agent-pop'); if (pop && !pop.hidden) { pop.hidden = true; pop.innerHTML = ''; } }
    function openAgentCard(id, anchor) {
      const pop = qs('#aw-agent-pop'), agent = rows(overview?.agents).find(value => agentId(value) === id);
      if (!pop || !agent) return;
      const models = agentModels(agent), phase = agentPhase(agent), evaluation = evaluationMeta(agent);
      const slot = teamPlacement(rows(overview?.agents)).placed.find(([, value]) => value && agentId(value) === id)?.[0];
      const now = phase === 'busy' ? '<span class="aw-good-text">● работает</span>' : phase === 'waiting' ? '<span class="aw-review-text">● ждёт вашей проверки</span>' : 'свободен';
      // A score is never shown without the class of check and the sample it
      // was measured on; an empty sample reads as new, not as zero quality.
      const checks = evaluation.sample > 0
        ? [plural(evaluation.sample, 'наблюдение', 'наблюдения', 'наблюдений'), evaluation.insufficient ? 'NEW · мало данных' : evaluation.label, evaluation.classLabel, 'уверенность ' + evaluation.confidence, evaluation.origin].filter(Boolean).join(' · ')
        : 'проверенных наблюдений пока нет';
      const table = models.length ? `<table class="aw-mini-table"><thead><tr><th>Модель под агентом</th><th>Задач</th><th>Успех</th><th>Ошибок</th></tr></thead><tbody>${models.map(row => `<tr><td>${esc(prettyModel(row.model))}</td><td>${count(row.total)}</td><td class="aw-rate-${rateTone(row.rate)}">${row.rate == null ? '—' : esc(pct(row.rate * 100))}</td><td>${count(row.bad)}</td></tr>`).join('')}</tbody></table>` : smallEmpty('Задач с моделями у этого агента пока не было.');
      pop.innerHTML = `<div class="aw-pop-head">${avatar(agent)}<div><b>${esc(name(agent))}</b><small>${esc(slot ? slot.title + ' · ' + slot.note : role(agent))}</small></div><button class="aw-pop-x" data-aw-pop-close aria-label="Закрыть">×</button></div>`
        + `<p class="aw-pop-now"><span class="aw-muted">Сейчас:</span> ${now}${models[0] ? ` · <span class="aw-muted">модель</span> ${esc(prettyModel(models[0].model))}` : ''}</p>`
        + `<div class="aw-pop-state">${agentState(agent)}</div>`
        + `<p class="aw-pop-now"><span class="aw-muted">Проверки:</span> ${esc(checks)}</p>`
        + (evaluation.sample > 0 ? '<p class="aw-pop-note">Рейтинг относится к конкретному классу задач: проверка не оценивает качество LLM в целом.</p>' : '') + table
        + (agent.persona_status ? `<div class="aw-actions"><button class="btn sm" data-aw-rename="${esc(id)}">Имя и фото</button></div>` : '');
      pop.setAttribute('aria-label', 'Карточка агента ' + name(agent));
      pop.hidden = false;
      refreshFaces(pop);
      // Opened above the face when there is no room below (the team strip sits
      // at the bottom of the screen), and kept inside the window.
      const box = anchor?.getBoundingClientRect?.(), width = root.innerWidth || 1280, height = root.innerHeight || 800;
      if (box && pop.style) {
        const tall = pop.offsetHeight || 280;
        pop.style.left = Math.max(10, Math.min(box.left, width - 350)) + 'px';
        pop.style.top = (box.bottom + 8 + tall > height ? Math.max(10, box.top - tall - 8) : box.bottom + 8) + 'px';
      }
      pop.querySelector?.('[data-aw-pop-close]')?.focus?.();
    }
    function openHire(key, anchor) {
      const pop = qs('#aw-agent-pop'), slot = TEAM_SLOTS.find(value => value.key === key);
      if (!pop || !slot) return;
      const faces = [['', 'Стандартное фото'], ...AVATAR_KEYS.filter(face => slot.key === 'deputy' || !['vitek', 'manager'].includes(face)).map(face => [face, AVATAR_LABELS[face] || face])];
      pop.innerHTML = `<form id="aw-hire-form" data-slot="${esc(slot.key)}"><div class="aw-pop-head"><div><b>${esc(slot.title)}</b><small>${esc(slot.note)} — обязанности уже заложены в должность</small></div><button type="button" class="aw-pop-x" data-aw-pop-close aria-label="Закрыть">×</button></div>`
        + `<p class="aw-pop-now">Выберите лицо и имя — больше ничего заполнять не нужно.</p>`
        + `<div class="aw-hire-faces" role="radiogroup" aria-label="Лицо агента">${faces.map(([face, label], index) => `<label class="aw-hire-face" title="${esc(label)}"><input type="radio" name="face" value="${esc(face)}"${index === 1 || (!face && faces.length === 1) ? ' checked' : ''}>${face && UI.agentAvatarHtml ? UI.agentAvatarHtml(face, { size: 'sm' }) : `<span class="aw-person-face">${standardFace()}</span>`}</label>`).join('')}</div>`
        + `<label class="aw-hire-name">Имя<input name="name" maxlength="80" value="${esc(slot.name)}" required></label>`
        + `<p class="aw-hire-error" hidden></p><div class="aw-actions"><button class="btn primary sm" type="submit">Добавить в команду</button><button class="btn sm" type="button" data-aw-pop-close>Отмена</button></div></form>`;
      pop.setAttribute('aria-label', 'Новый агент: ' + slot.title);
      pop.hidden = false;
      refreshFaces(pop);
      const box = anchor?.getBoundingClientRect?.(), width = root.innerWidth || 1280, height = root.innerHeight || 800;
      if (box && pop.style) {
        const tall = pop.offsetHeight || 300;
        pop.style.left = Math.max(10, Math.min(box.left, width - 350)) + 'px';
        pop.style.top = (box.bottom + 8 + tall > height ? Math.max(10, box.top - tall - 8) : box.bottom + 8) + 'px';
      }
      pop.querySelector?.('input[name="name"]')?.focus?.();
    }
    async function hire(form) {
      const slot = TEAM_SLOTS.find(value => value.key === form.dataset.slot), error = form.querySelector('.aw-hire-error');
      const chosen = String(form.elements.name.value || '').trim(), face = form.querySelector('input[name="face"]:checked')?.value || '';
      if (!slot || !chosen) { error.textContent = 'Введите имя.'; error.hidden = false; return; }
      const payload = { name: chosen, avatar_key: face, team_role: slot.key };
      form.querySelectorAll('button, input').forEach(input => { input.disabled = true; });
      try {
        const created = await API.aiControlCenterDomainAction('personas', 'new', 'create', { payload, idempotency_key: root.crypto.randomUUID() });
        const item = created?.item;
        if (item?.id && rows(item.actions).includes('activate')) {
          await API.aiControlCenterDomainAction('personas', item.id, 'activate', { payload: {}, idempotency_key: root.crypto.randomUUID(), expected_revision: item.revision });
        }
        closeAgentCard();
        domainCache.clear();
        announce(`${chosen} — ${slot.title.toLowerCase()} — теперь в команде.`);
        await refresh();
      } catch (reason) {
        error.textContent = reason?.message || 'Не удалось добавить агента.'; error.hidden = false;
        form.querySelectorAll('button, input').forEach(input => { input.disabled = false; });
      }
    }
    // The owner's model roster (the AI agents registry): what each model is
    // for, how often it works, how well, what it costs and how much quota is left.
    const LAB_ROLES = Object.freeze({ orchestrator: 'Оркестратор (старая роль)', chief_agent: 'Главный агент Лаборатории', backtest_analyst: 'Аналитик бэктестов',
      strategy_analyst: 'Аналитик стратегий', coder: 'Кодер', optimizer: 'Оптимизатор', accountant: 'Бухгалтер', news: 'Новостной аналитик',
      telegram_assistant: 'Помощник в Telegram', embedding: 'Поиск по памяти', general: 'Общие запросы' });
    const labRole = key => LAB_ROLES[key] || (machineKey(key) ? 'Другое' : String(key || 'Общие запросы'));
    const usd = value => number(value) == null ? '—' : Number(value).toLocaleString('ru-RU', { style: 'currency', currency: 'USD', maximumFractionDigits: Number(value) && Math.abs(Number(value)) < 1 ? 3 : 2 });
    const labModels = () => { const lab = overview?.summaries?.lab_models; return lab && !lab.unavailable ? rows(lab.items) : null; };
    const labRate = model => model.requests >= 3 ? model.ok / model.requests : null;
    // What is left of the model's allowance: a monthly or daily budget, a
    // grant's credit, or a free tier counted in requests.
    function quota(model) {
      if (number(model.monthly_budget_usd) > 0) {
        const left = number(model.remaining_monthly_budget_usd) ?? 0, total = number(model.monthly_budget_usd);
        return { used: Math.min(100, (total - left) / total * 100), text: `осталось ${usd(left)} из ${usd(total)} в месяц` };
      }
      if (number(model.daily_budget_usd) > 0) {
        const left = number(model.remaining_daily_budget_usd) ?? 0, total = number(model.daily_budget_usd);
        return { used: Math.min(100, (total - left) / total * 100), text: `осталось ${usd(left)} из ${usd(total)} на сегодня` };
      }
      if (number(model.credit_total_usd) > 0) {
        const left = number(model.credit_remaining_estimated_usd), total = number(model.credit_total_usd);
        return { used: number(model.credit_used_pct) ?? 0, text: `грант: осталось ${usd(left ?? total)} из ${usd(total)}` };
      }
      if (model.billing_mode === 'free_tier') return { used: null, text: `бесплатно · ${count(model.requests_today)} запросов сегодня` };
      return { used: null, text: 'лимит не задан' };
    }
    // The old registry's roles were archived: they are history, readable in
    // Legacy / Архив, and never shown here as a pinning. What a model actually
    // did - "где работала" - comes from the usage log, which is a fact.
    // Proposed distribution cycle (owner's confirmation pending, rules 3.3):
    // every text model tries every open job, jobs with responsibility take only
    // proven models, and special-purpose models stay in their own function.
    const PLACE_COLUMNS = Object.freeze([['orchestrator', 'Заместитель', 'responsible'], ['strategy_analyst', 'Исследователь', 'open'], ['coder', 'Кодер', 'open'],
      ['backtest_analyst', 'Бэктестер', 'open'], ['optimizer', 'Оптимизатор', 'open'], ['accountant', 'Бухгалтер', 'responsible'],
      ['news_analyst', 'Новости', 'open'], ['risk_manager', 'Судьи', 'responsible']]);
    const SPECIAL = model => /embedding|tts|whisper|dall|image/i.test(String(model.model || '')) || model.endpoint_type === 'embeddings';
    const proven = model => model.requests >= 20 && model.ok / model.requests >= 0.9;
    function placeCell(model, [role, , kind]) {
      const row = rows(model.by_role).find(value => value.role === role || (role === 'news_analyst' && value.role === 'news'));
      if (SPECIAL(model)) return '<td class="aw-cell-no" title="Специальная модель — только своя функция">нельзя</td>';
      if (row) return `<td class="aw-rate-${rateTone(row.requests >= 3 ? row.ok / row.requests : null)}" title="${esc(`${count(row.ok)} успешно из ${count(row.requests)}`)}">${row.requests >= 3 ? esc(pct(row.ok / row.requests * 100)) : 'NEW'}<small>${count(row.requests)}</small></td>`;
      if (kind === 'responsible' && !proven(model)) return '<td class="aw-cell-wait" title="Ответственная должность — только после 20 вызовов с успехом от 90%">после проверки</td>';
      return '<td class="aw-cell-try" title="Ещё не работала здесь — получит пробные задачи">проба</td>';
    }
    function distribution(models) {
      const live = models.filter(model => model.enabled);
      return `<ol class="aw-rules"><li><b>Закрепление важнее всего.</b> Если вы или пользователь закрепили модель за должностью, она работает только там. Роли из старого реестра «AI агенты» переведены в архив: это история, на распределение они не влияют.</li>`
        + `<li><b>Пробный круг.</b> Новая модель получает по 3 пробные задачи в каждой открытой должности: Исследователь, Кодер, Бэктестер, Оптимизатор, Новости.</li>`
        + `<li><b>Дальше — по рейтингу.</b> В должность идёт модель с лучшим успехом именно под этой должностью; 10% задач — на пробу других, чтобы рейтинг не застывал.</li>`
        + `<li><b>Ответственные должности</b> — Заместитель, Бухгалтер, Судьи — только проверенные модели: от 20 вызовов и успех от 90%.</li>`
        + `<li><b>Специальные модели</b> (поиск по памяти, озвучка) в текстовые должности не попадают.</li></ol>`
        + `<p class="aw-muted aw-hint-line">Предложение правил — ждёт вашего утверждения. Ниже — как они ложатся на текущие модели: процент — успех под должностью (число вызовов), «проба» — будет пробовать, «после проверки» — пока не допущена.</p>`
        + `<div class="aw-table-wrap"><table class="aw-lab-table aw-place-table"><thead><tr><th>Модель</th>${PLACE_COLUMNS.map(([, title]) => `<th>${esc(title)}</th>`).join('')}</tr></thead>`
        + `<tbody>${live.map(model => `<tr><td><strong>${esc(model.name || model.model)}</strong></td>${PLACE_COLUMNS.map(column => placeCell(model, column)).join('')}</tr>`).join('')}</tbody></table></div>`;
    }
    function labSharingLabel(model) {
      const data = cachedDomain('models');
      if (!data || data.unavailable) return 'Доступ уточняется';
      return items(data).some(item => item.registry_id === model.id && item.shared === true)
        ? 'Общая · вы делитесь' : 'Приватная';
    }
    function labModelRow(model) {
      const rate = labRate(model), left = quota(model);
      const worked = rows(model.by_role).slice(0, 3).map(row => `${labRole(row.role)} ${row.requests >= 3 ? pct(row.ok / row.requests * 100) : 'NEW'} (${count(row.requests)})`);
      return `<tr class="aw-lab-row${model.enabled ? '' : ' aw-lab-off'}" data-aw-lab-model="${esc(model.id)}" tabindex="0">`
        + `<td><div class="aw-lab-name"><span class="aw-icbox aw-t-cyan">${esc(String(model.name || model.model || '?').slice(0, 1).toUpperCase())}</span><span><strong>${esc(model.name || model.model)}</strong><small>${esc(providerLabel(model.provider))} · ${esc(model.model || '')}${model.enabled ? '' : ' · выключена'}</small></span></div></td>`
        + `<td><span class="aw-chip">${esc(labSharingLabel(model))}</span></td>`
        + `<td>${worked.length ? esc(worked.join(', ')) : '<span class="aw-muted">ещё не работала</span>'}</td>`
        + `<td class="aw-num-cell">${count(model.requests_month)}<small>всего ${count(model.requests)}</small></td>`
        + `<td class="aw-num-cell"><b class="aw-rate aw-rate-${rateTone(rate)}" title="${esc(model.requests ? `Успешно ${model.ok} из ${model.requests} вызовов` : 'Вызовов ещё не было')}">${rate == null ? (model.requests ? 'NEW' : '—') : esc(pct(rate * 100))}</b>${model.errors ? `<small>ошибок ${count(model.errors)}</small>` : ''}</td>`
        + `<td class="aw-num-cell">${esc(usd(model.spend_month_usd))}<small>всего ${esc(usd(model.spend_all_time_usd))}</small></td>`
        + `<td class="aw-quota-cell">${left.used == null ? '' : `<span class="aw-use"><span style="width:${Math.round(left.used)}%"></span></span>`}<small>${esc(left.text)}</small></td>`
        + `<td class="aw-num-cell">${esc(model.last_used_at_utc ? clock(model.last_used_at_utc) : '—')}</td></tr>`;
    }
    function labModelTable(models) {
      if (!models.length) return smallEmpty('Моделей пока нет. Подключите модель по API — она проверится одним запросом.');
      const enabled = models.filter(model => model.enabled).length, spend = models.reduce((sum, model) => sum + (number(model.spend_month_usd) || 0), 0);
      return `<div class="aw-lab-totals"><span><b>${count(models.length)}</b> моделей</span><span><b>${count(enabled)}</b> включено</span><span><b>${esc(usd(spend))}</b> расход за месяц</span><span><b>${count(models.reduce((sum, model) => sum + (number(model.requests_month) || 0), 0))}</b> запросов за месяц</span></div>`
        + `<div class="aw-table-wrap"><table class="aw-lab-table"><thead><tr><th>Модель</th><th>Доступ</th><th>Где работала · успех</th><th>Запросов за месяц</th><th>Успех</th><th>Расход за месяц</th><th>Квота</th><th>Последний раз</th></tr></thead><tbody>${models.map(labModelRow).join('')}</tbody></table></div>`;
    }
    function openLabModel(id) {
      const model = rows(labModels()).find(row => row.id === id);
      if (!model) return;
      ++detailGeneration; detailKind = 'lab_model'; actionForm = null;
      const rate = labRate(model), left = quota(model);
      const status = model.enabled ? '<span class="aw-good-text">● включена</span>' : `<span class="aw-muted">● выключена${model.disabled_reason ? ' — ' + esc(model.disabled_reason) : ''}</span>`;
      const byRole = rows(model.by_role).length ? `<h3 class="aw-drawer-h">Под какими агентами работала</h3><table class="aw-mini-table"><thead><tr><th>Агент</th><th>Вызовов</th><th>Успех</th><th>Расход</th><th>Последний раз</th></tr></thead><tbody>${rows(model.by_role).map(row => `<tr><td>${esc(labRole(row.role))}</td><td>${count(row.requests)}</td><td class="aw-rate-${rateTone(row.requests >= 3 ? row.ok / row.requests : null)}">${row.requests >= 3 ? esc(pct(row.ok / row.requests * 100)) : 'NEW'}</td><td>${esc(usd(row.cost_usd))}</td><td>${esc(clock(row.last_at))}</td></tr>`).join('')}</tbody></table>` : '<p class="aw-muted">Эта модель ещё не работала ни под одним агентом.</p>';
      const recent = rows(model.recent).length ? `<h3 class="aw-drawer-h">Последние вызовы</h3><table class="aw-mini-table"><thead><tr><th>Когда</th><th>Агент</th><th>Задача</th><th>Итог</th><th>Токены</th><th>$</th></tr></thead><tbody>${rows(model.recent).map(row => `<tr><td>${esc(logTime(row.timestamp_utc))}</td><td>${esc(labRole(row.role))}</td><td>${esc(String(row.purpose || '—').replace(/_/g, ' '))}</td><td class="${row.status === 'success' ? 'aw-good-text' : 'aw-bad-text'}">${row.status === 'success' ? 'успех' : 'ошибка'}</td><td>${count(row.total_tokens)}</td><td>${esc(usd(row.cost_usd))}</td></tr>`).join('')}</tbody></table>` : '';
      openDrawer(model.name || model.model, `<div class="aw-model-head"><span class="aw-icbox aw-t-cyan aw-icbox-lg">${esc(String(model.name || '?').slice(0, 1).toUpperCase())}</span><div><b>${esc(model.name || model.model)}</b><small>${esc(providerLabel(model.provider))} · ${esc(model.model || '')} · ${status}</small></div></div>`
        + `<div class="aw-nums aw-nums-4">${bnum('Вызовов', count(model.requests))}${bnum('Успех', rate == null ? (model.requests ? 'NEW' : '—') : pct(rate * 100))}${bnum('Токенов', count(model.tokens))}${bnum('Расход всего', usd(model.spend_all_time_usd))}</div>`
        + `<p class="aw-model-spend"><span class="aw-muted">Сегодня:</span> ${esc(usd(model.spend_today_usd))} · ${count(model.requests_today)} запросов · <span class="aw-muted">за месяц:</span> ${esc(usd(model.spend_month_usd))} · ${count(model.requests_month)} запросов</p>`
        + `<p class="aw-model-spend"><span class="aw-muted">Квота:</span> ${esc(left.text)}${model.credit_expires_at_utc ? ` · <span class="aw-muted">грант до</span> ${esc(date(model.credit_expires_at_utc))}` : ''}</p>${left.used == null ? '' : `<span class="aw-use aw-use-lg"><span style="width:${Math.round(left.used)}%"></span></span>`}`
        + `<p class="aw-model-spend"><span class="aw-muted">Тариф:</span> ${number(model.input_price_usd_per_m) || number(model.output_price_usd_per_m) ? `${esc(usd(model.input_price_usd_per_m))} за 1 млн входных токенов, ${esc(usd(model.output_price_usd_per_m))} за 1 млн выходных` : model.billing_mode === 'free_tier' ? 'бесплатный доступ' : 'не указан'}</p>`
        + byRole + recent
        + labShareSection(model)
        + modelTestControls(model.id, true), { size: 'model' });
    }
    // Connecting a model: provider, model, key and how it is paid for. The key
    // goes straight to the encrypted store; the model then checks itself with
    // one short request.
    const BILLING_CHOICES = [['free_tier', 'Бесплатно (с дневным лимитом провайдера)'], ['payg', 'По токенам, с потолком в месяц'], ['credit', 'Грант или предоплата']];
    async function openConnect() {
      ++detailGeneration; detailKind = 'connect_model'; actionForm = null;
      openDrawer('Подключить модель', loadingBlock('Загружаем провайдеров…'), { size: 'card' });
      let providers = [];
      try { providers = rows((await API.aiAgents({ signal }))?.providers); } catch (error) { if (error?.name === 'AbortError') return; }
      const body = currentDrawer && qs('.drawer-b', currentDrawer);
      if (!body) return;
      body.innerHTML = `<div class="aw-inspector"><form id="aw-connect-form" class="aw-connect">`
        + `<p class="aw-muted">Модель проверит себя одним коротким запросом. Данные стратегий в проверке не используются.</p>`
        + `<label>Провайдер<select name="provider" required>${providers.map(item => `<option value="${esc(item.id)}">${esc(item.label || item.id)}</option>`).join('')}</select></label>`
        + `<label>Модель<input name="model" required maxlength="180" placeholder="например, gemini-2.5-flash"></label>`
        + `<label>Ключ API<input name="api_key" type="password" required autocomplete="off" placeholder="Вставьте ключ провайдера"></label>`
        + `<label>Название<input name="name" maxlength="80" placeholder="Как показывать модель в списке"></label>`
        + `<label>Как оплачивается<select name="billing_mode">${BILLING_CHOICES.map(([key, label]) => `<option value="${key}">${esc(label)}</option>`).join('')}</select></label>`
        + `<label data-aw-billing="payg" hidden>Потолок расходов в месяц, $<input name="monthly_budget_usd" type="number" min="0" step="0.01" value="5"></label>`
        + `<label data-aw-billing="credit" hidden>Сумма гранта, $<input name="credit_total_usd" type="number" min="0" step="0.01" value="100"></label>`
        + `<p class="aw-hire-error" hidden></p><div class="aw-actions"><button class="btn primary" type="submit">Подключить и проверить</button></div></form></div>`;
      const form = qs('#aw-connect-form', body);
      const billing = () => qsa('[data-aw-billing]', form).forEach(field => { field.hidden = field.dataset.awBilling !== form.elements.billing_mode.value; });
      form.elements.billing_mode.addEventListener('change', billing); billing();
      form.addEventListener('submit', event => { event.preventDefault(); void connect(form); });
      form.elements.model.focus();
    }
    async function connect(form) {
      const values = Object.fromEntries(new FormData(form).entries()), error = qs('.aw-hire-error', form);
      const agent = { provider: values.provider, model: String(values.model || '').trim(), api_key: values.api_key, billing_mode: values.billing_mode,
        name: String(values.name || '').trim() || `${values.provider} · ${String(values.model || '').trim()}`,
        ...(values.billing_mode === 'payg' ? { monthly_budget_usd: Number(values.monthly_budget_usd) || 0 } : {}),
        ...(values.billing_mode === 'credit' ? { credit_total_usd: Number(values.credit_total_usd) || 0 } : {}) };
      qsa('button, input, select', form).forEach(input => { input.disabled = true; });
      try {
        const created = await API.aiAgentCreate(agent);
        const id = created?.agent?.id;
        const test = id ? await API.aiAgentTest(id).catch(reason => ({ ok: false, error: reason?.message })) : null;
        UI.closeDrawer();
        announce(test?.ok === false ? `Модель ${agent.name} подключена, но проверка не прошла: ${test.error || 'нет ответа'}.` : `Модель ${agent.name} подключена и ответила на проверку.`, test?.ok === false);
        await refresh();
      } catch (reason) {
        error.textContent = reason?.message || 'Не удалось подключить модель.'; error.hidden = false;
        qsa('button, input, select', form).forEach(input => { input.disabled = false; });
      }
    }
    function openRename(id, anchor) {
      const pop = qs('#aw-agent-pop'), agent = rows(overview?.agents).find(value => agentId(value) === id);
      if (!pop || !agent) return;
      const current = avatarKeyOf(agent);
      const faces = [['', 'Стандартное фото'], ...AVATAR_KEYS.map(face => [face, AVATAR_LABELS[face] || face])];
      pop.innerHTML = `<form id="aw-rename-form" data-agent="${esc(id)}" data-revision="${esc(String(agent.revision ?? ''))}"><div class="aw-pop-head"><div><b>${esc(name(agent))}</b><small>${esc(role(agent))}</small></div><button type="button" class="aw-pop-x" data-aw-pop-close aria-label="Закрыть">×</button></div>`
        + `<div class="aw-hire-faces" role="radiogroup" aria-label="Лицо агента">${faces.map(([face, label]) => `<label class="aw-hire-face" title="${esc(label)}"><input type="radio" name="face" value="${esc(face)}"${face === current ? ' checked' : ''}>${face && UI.agentAvatarHtml ? UI.agentAvatarHtml(face, { size: 'sm' }) : standardFace()}</label>`).join('')}</div>`
        + `<label class="aw-hire-name">Имя<input name="name" maxlength="80" value="${esc(name(agent))}" required></label>`
        + `<p class="aw-hire-error" hidden></p><div class="aw-actions"><button class="btn primary sm" type="submit">Сохранить</button><button class="btn sm" type="button" data-aw-pop-close>Отмена</button></div></form>`;
      pop.hidden = false;
      refreshFaces(pop);
      pop.querySelector?.('input[name="name"]')?.focus?.();
      void anchor;
    }
    async function rename(form) {
      const error = form.querySelector('.aw-hire-error'), chosen = String(form.elements.name.value || '').trim();
      if (!chosen) { error.textContent = 'Введите имя.'; error.hidden = false; return; }
      form.querySelectorAll('button, input').forEach(input => { input.disabled = true; });
      try {
        const item = await API.aiControlCenterDomainItem('personas', form.dataset.agent);
        const record = item?.item || item;
        await API.aiControlCenterDomainAction('personas', form.dataset.agent, 'update', { payload: { name: chosen, avatar_key: form.querySelector('input[name="face"]:checked')?.value || '' },
          idempotency_key: root.crypto.randomUUID(), expected_revision: record?.revision });
        closeAgentCard(); announce('Сохранено.'); await refresh();
      } catch (reason) {
        error.textContent = reason?.message || 'Не удалось сохранить.'; error.hidden = false;
        form.querySelectorAll('button, input').forEach(input => { input.disabled = false; });
      }
    }
    function renderModels() {
      const lab = labModels();
      const data = cachedDomain('models');
      const own = modelConnections(data).filter(item => item.ownership !== 'shared');
      const shared = modelConnections(data).filter(item => item.ownership === 'shared');
      const sharedSection = () => bcard('Доступные общие модели', 'users', 'cyan',
        '<p class="aw-muted">Доступ предоставлен другими участниками. Ключи и настройки принадлежат владельцам подключений.</p>'
        + (shared.length ? modelRows(modelGroupsFromTasks(rows(overview.tasks), shared)) : smallEmpty('Общих моделей сейчас нет.')));
      // An empty Local Lab registry is not an empty server Model roster. The
      // migrated owner connections live in the workspace-scoped Model domain.
      if (lab?.length) {
        content.innerHTML = bcard('Мои модели', 'cpu', 'cyan', labModelTable(lab), '<button class="aw-link-button" data-aw-connect-model>+ подключить модель</button>')
          + (own.some(item => !item.registry_id) ? bcard('Мои дополнительные подключения', 'cpu', 'cyan', modelRows(modelGroupsFromTasks(rows(overview.tasks), own.filter(item => !item.registry_id)))) : '')
          + (data && !data.unavailable ? sharedSection() : '')
          + '<p class="aw-muted aw-hint-line">Нажмите на модель: расход, квота, тариф, под какими агентами работала, успешность и последние вызовы.</p>'
          + bcard('Распределение по должностям', 'layers', 'violet', distribution(lab));
        return;
      }
      if (!data) { content.innerHTML = bcard('Подключённые модели', 'cpu', 'cyan', loadingBlock('Загружаем подключённые модели…')); return; }
      if (data.unavailable) { content.innerHTML = bcard('Подключённые модели', 'cpu', 'cyan', readError({ status: data.unavailable })); return; }
      content.innerHTML = bcard('Мои модели', 'cpu', 'cyan', own.length ? modelRows(modelGroupsFromTasks(rows(overview.tasks), own)) : smallEmpty('Вы ещё не подключили собственные модели. Можно использовать доступные общие модели ниже.'), '<button class="aw-link-button" data-aw-connect-model>+ подключить модель</button>')
        + sharedSection() + '<p class="aw-muted aw-hint-line">Нажмите на модель, чтобы проверить ответ и посмотреть свои запросы и расходы.</p>';
    }
    function openModelGroup(id) {
      const data = cachedDomain('models');
      const summary = overview?.summaries?.models;
      const connections = data && !data.unavailable ? modelConnections(data) : summary && !summary.unavailable ? rows(summary.items) : undefined;
      const group = modelGroupsFromTasks(rows(overview?.tasks), connections).find(entry => entry.id === id);
      if (!group) return;
      ++detailGeneration; detailKind = 'model_group'; actionForm = null;
      const stats = group.stats, scored = group.byAgent.filter(row => row.rate != null);
      const best = scored.slice().sort((a, b) => b.rate - a.rate)[0], worst = scored.slice().sort((a, b) => a.rate - b.rate)[0];
      const who = row => { const text = roleOf(row.agent); return `${esc(name(row.agent))}${text ? ` <span class="aw-muted">· ${esc(text)}</span>` : ''}`; };
      const table = group.byAgent.length ? `<table class="aw-mini-table"><thead><tr><th>Под каким агентом</th><th>Задач</th><th>Успех</th><th>Ошибок</th></tr></thead><tbody>${group.byAgent.map(row => `<tr><td>${who(row)}</td><td>${count(row.total)}</td><td class="aw-rate-${rateTone(row.rate)}">${row.rate == null ? '—' : esc(pct(row.rate * 100))}</td><td>${count(row.bad)}</td></tr>`).join('')}</tbody></table>`
        : '<p class="aw-muted">Новая модель: рейтинг появится после первых проверенных задач.</p>';
      openDrawer(prettyModel(group.id), `<div class="aw-model-head"><span class="aw-icbox aw-t-cyan aw-icbox-lg">${esc(prettyModel(group.id).slice(0, 1))}</span><div><b>${esc(prettyModel(group.id))}</b><small>${esc(providerLabel(group.provider))} · ${esc(plural(group.connectionCount, 'подключение', 'подключения', 'подключений'))}, активных ${count(group.activeCount)}</small></div></div>`
        + `<div class="aw-nums aw-nums-3">${bnum('Задач', stats.total ? count(stats.total) : '—')}${bnum('Токенов', '—')}${bnum('Рейтинг', rated(stats) ? pct(stats.rate * 100) : stats.ok + stats.bad ? 'NEW' : '—')}</div>`
        + `<p class="aw-model-spend"><span class="aw-muted">Расход:</span> ${stats.spent == null ? 'не измерен' : esc(cost(stats.spent))} · <span class="aw-muted">измеренный расход сохранённых задач</span></p>`
        + (best ? `<p class="aw-model-best">Лучше всего: <b class="aw-rate-good">${esc(name(best.agent))} ${esc(pct(best.rate * 100))}</b>${worst && worst !== best ? ` · хуже всего: <b class="aw-rate-low">${esc(name(worst.agent))} ${esc(pct(worst.rate * 100))}</b>` : ''}</p>` : '')
        + table
        + shareSection(group.connections, 'group:' + group.id, data && !data.unavailable ? data : null)
        + modelCallButtons(group.connections)
        + `<label class="aw-switch-row" title="Включение и выключение — в подключениях модели"><input type="checkbox" disabled ${group.activeCount > 0 ? 'checked' : ''}> Модель включена</label>`
        + `<p class="aw-muted"><code class="aw-model-code">${esc(group.id)}</code></p>`, { size: 'card' });
    }
    const RESEARCH_STATUS = Object.freeze({ new: ['Новое', 'info'], active: ['Активное', 'good'], promising: ['Перспективное', 'good'], validated: ['Подтверждено', 'good'],
      exhausted: ['Неактуально', 'neutral'], at_risk: ['Под вопросом', 'warning'], paused: ['Пауза', 'warning'], archived: ['Архив', 'neutral'] });
    // Each family gets its own mark, like the prototype list.
    const RESEARCH_MARKS = Object.freeze([['flask', 'violet'], ['gauge', 'green'], ['target', 'teal'], ['layers', 'amber']]);
    let researchPick = 0;
    const researchMeta = row => RESEARCH_STATUS[String(row?.evaluation?.status || row?.status || '')] || ['Статус не указан', 'neutral'];
    const researchState = row => { const [label, tone] = researchMeta(row); return `<span class="aw-st aw-st-${tone}">● ${esc(label)}</span>`; };
    const researchChip = row => { const [label, tone] = researchMeta(row); return `<span class="aw-chip aw-chip-${tone}">● ${esc(label)}</span>`; };
    const researchWhere = row => { const window = row?.evaluation?.best_variant?.best_window || {}; return [row.family_name !== row.title ? row.family_name : '', window.instrument, window.timeframe].filter(value => value && value !== '—').join(' · '); };
    const money = value => Number(value).toLocaleString('ru-RU', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
    function researchYears(window) {
      const from = Date.parse(window?.from_utc || ''), to = Date.parse(window?.to_utc || '');
      return Number.isFinite(from) && Number.isFinite(to) && to > from ? ((to - from) / (365.25 * 24 * 3600 * 1000)).toLocaleString('ru-RU', { maximumFractionDigits: 1 }) : '—';
    }
    function researchDetail(row, index) {
      const evaluation = row.evaluation || {}, policy = row.evaluation_policy || {}, best = evaluation.best_variant, [mark, tone] = RESEARCH_MARKS[index % RESEARCH_MARKS.length];
      const hypothesis = rows(row.hypotheses)[0] || row.summary || 'Гипотеза не записана.';
      const goals = rows(row.objectives).length ? rows(row.objectives).slice(0, 6) : [
        policy.min_profit_factor != null ? `PF ≥ ${policy.min_profit_factor}` : '', policy.min_trades != null ? `Минимум ${policy.min_trades} сделок` : '',
        policy.min_years_tested != null ? `Минимум ${policy.min_years_tested} года истории` : '', policy.required_profitable_strategies != null ? `Прибыльных стратегий ≥ ${policy.required_profitable_strategies}` : ''].filter(Boolean);
      const evaluated = number(evaluation.evaluated_strategies) || 0, passed = number(evaluation.profitable_strategies) || 0;
      const params = best?.best_parameter_variant?.parameters && typeof best.best_parameter_variant.parameters === 'object' ? Object.entries(best.best_parameter_variant.parameters).slice(0, 8) : [];
      const where = researchWhere(row), [label] = researchMeta(row);
      const champion = best && best.qualifies === true;
      return `<header class="aw-rd-head"><span class="aw-icbox aw-t-${tone}">${icon(mark)}</span><div><b>${esc(row.title || row.family_name || 'Исследование')}</b> ${researchChip(row)}<small>${esc(where)}${where && row.research_id ? ' · ' : ''}${row.research_id ? 'ID: ' + esc(row.research_id) : ''}</small></div></header>`
        + `<div class="aw-rd"><div class="aw-rd-col"><h3>Гипотеза</h3><p>${esc(hypothesis)}</p><h3>Цели исследования</h3>${goals.length ? `<ul class="aw-checks">${goals.map(goal => `<li>${icon('check', 14)}${esc(goal)}</li>`).join('')}</ul>` : smallEmpty('Цели не записаны.')}</div>`
        + `<div class="aw-rd-col"><div class="aw-rd-stats"><div><small>Оценено стратегий</small><b>${count(evaluated)}</b>${number(policy.target_strategies) != null ? `<span class="aw-muted">цель ${count(policy.target_strategies)}</span>` : ''}</div><div><small>Прошли пороги</small><b>${count(passed)}</b><span class="aw-up">${evaluated ? esc(pct(passed / evaluated * 100)) : '—'}</span></div><div><small>Вариантов параметров</small><b>${count(evaluation.parameter_variants)}</b></div><div><small>Текущий статус</small><b class="aw-rd-status aw-st-${researchMeta(row)[1]}">● ${esc(label)}</b></div></div>`
        + (evaluation.automatic_conclusion ? `<p class="aw-muted aw-rd-conclusion">${esc(evaluation.automatic_conclusion)}</p>` : '')
        + (champion ? `<h3>Лучший вариант (чемпион) <span class="aw-chip aw-chip-champ">CHAMPION</span></h3><div class="aw-champ"><div><small>Вариант</small><b>${esc(best.class_name || best.experiment_id || '—')}</b></div><div><small>PF</small><b>${best.profit_factor == null ? '—' : esc(Number(best.profit_factor).toLocaleString('ru-RU', { maximumFractionDigits: 2 }))}</b></div><div><small>P&amp;L</small><b>${best.net_profit == null ? '—' : esc(money(best.net_profit))}</b></div><div><small>Max DD</small><b>${best.max_drawdown == null ? '—' : esc(money(best.max_drawdown))}</b></div><div><small>Годы теста</small><b>${esc(researchYears(best.best_window))}</b></div></div>`
            + (params.length ? `<h3>Параметры</h3><div class="aw-params">${params.map(([key, value]) => `<span>${esc(key)} ${esc(typeof value === 'object' ? JSON.stringify(value) : String(value))}</span>`).join('')}</div>` : '')
          : '<p class="aw-muted">Чемпиона пока нет: ни одна стратегия не прошла пороги.</p>'
            + (best ? `<p class="aw-muted">Лучший результат пока: <b>${esc(best.class_name || best.experiment_id || '—')}</b>${best.profit_factor == null ? '' : ` · PF ${esc(Number(best.profit_factor).toLocaleString('ru-RU', { maximumFractionDigits: 2 }))}`}${best.net_profit == null ? '' : ` · P&amp;L ${esc(money(best.net_profit))}`}</p>` : '')) + '</div></div>' + `<div class="aw-rd-full">${familyStrategies(row)}</div>`;
    }
    // Stages of a strategy in the lab, from the owner's development rules:
    // hypothesis → code → compile → backtest with costs → thresholds → demo.
    const STRATEGY_STAGE = Object.freeze({ inventory: ['В разработке', 'info'], approved_demo: ['Одобрена для демо (по профилю)', 'good'], archived: ['В архиве', 'neutral'],
      rejected: ['Отклонена', 'warning'], sandbox_candidate: ['Кандидат', 'good'], portfolio_contributor: ['Кандидат', 'good'], champion_candidate: ['Чемпион', 'good'],
      human_review_candidate: ['Ждёт вашего решения', 'warning'], running: ['Идёт бэктест', 'info'], draft: ['Черновик', 'neutral'] });
    const stageOf = node => STRATEGY_STAGE[String(node.status || '')] || [String(node.status || 'этап не указан').replace(/_/g, ' '), 'neutral'];
    function familyStrategies(row) {
      const nodes = rows(row.evaluation?.tree).flatMap(family => rows(family.strategies));
      if (!nodes.length) return '<p class="aw-muted">Стратегий в этом семействе пока нет — лаборатория создаст их по гипотезе.</p>';
      return `<h3>Стратегии семейства · ${count(nodes.length)}</h3><div class="aw-table-wrap"><table class="aw-lab-table aw-strategy-table"><thead><tr><th>Стратегия</th><th>Этап</th><th>PF</th><th>P&amp;L</th><th>Вариантов</th><th>Окно теста</th><th>Пороги</th></tr></thead><tbody>`
        + nodes.map(node => { const [label, tone] = stageOf(node), window = node.best_window || {};
          return `<tr><td><strong>${esc(node.class_name || '—')}</strong>${node.archive_reason ? `<small class="aw-muted">${esc(node.archive_reason)}</small>` : ''}</td><td><span class="aw-st aw-st-${tone}">● ${esc(label)}</span></td>`
            + `<td>${node.profit_factor == null ? '—' : esc(Number(node.profit_factor).toLocaleString('ru-RU', { maximumFractionDigits: 2 }))}</td><td>${node.net_profit == null ? '—' : esc(money(node.net_profit))}</td><td>${count(node.variant_count)}</td>`
            + `<td>${esc([window.instrument, window.timeframe].filter(value => value && value !== '—').join(' · ') || '—')}${researchYears(window) !== '—' ? `<small class="aw-muted">${esc(researchYears(window))} г.</small>` : ''}</td>`
            + `<td>${node.qualifies ? '<span class="aw-good-text">прошла</span>' : '<span class="aw-muted">нет</span>'}</td></tr>`; }).join('') + '</tbody></table></div>';
    }
    // The lab at a glance: where every strategy of every research stands.
    function labPipeline(list) {
      const nodes = list.flatMap(row => rows(row.evaluation?.tree).flatMap(family => rows(family.strategies)));
      const stages = [['Гипотезы', list.length, 'исследований'], ['В разработке', nodes.filter(node => !node.archived && !['approved_demo'].includes(node.status) && !node.qualifies).length, 'код и бэктесты'],
        ['Прошли пороги', nodes.filter(node => node.qualifies).length, 'PF, сделки, годы'], ['Одобрены для демо', nodes.filter(node => node.status === 'approved_demo').length, 'по профилям'],
        ['В архиве', nodes.filter(node => node.archived || node.status === 'archived').length, 'сохранены для сравнения']];
      return `<div class="aw-pipeline">${stages.map(([title, value, note], index) => `<div class="aw-stage"><small>${index + 1}. ${esc(title)}</small><b>${count(value)}</b><span class="aw-muted">${esc(note)}</span></div>`).join('<span class="aw-stage-arrow" aria-hidden="true">→</span>')}</div>`
        + '<p class="aw-muted aw-hint-line">Как создаётся стратегия: гипотеза → код NinjaScript по спецификации → компиляция → бэктест с комиссией и проскальзыванием → проверка порогов (PF, число сделок, годы истории) → демо-счёт. Чемпион — стратегия, прошедшая все пороги своего исследования.</p>';
    }
    function openNewResearch() {
      ++detailGeneration; detailKind = 'new_research'; actionForm = null;
      openDrawer('Новое исследование', `<form id="aw-research-form" class="aw-connect"><p class="aw-muted">Лаборатория проверит гипотезу на стратегиях и выберет чемпиона по порогам.</p>`
        + `<label>Название<input name="title" required maxlength="120" placeholder="например, MNQ Liquidity Sweep"></label>`
        + `<label>Семейство<input name="family_name" maxlength="120" placeholder="если отличается от названия"></label>`
        + `<label>Гипотеза<textarea name="hypothesis" rows="3" maxlength="1000" placeholder="Что должно давать преимущество и почему"></textarea></label>`
        + `<label>Цели и пороги — по одной на строке<textarea name="objectives" rows="4" maxlength="2000" placeholder="PF ≥ 1.40&#10;Max DD ≤ 12%&#10;Минимум 2 года истории"></textarea></label>`
        + `<p class="aw-hire-error" hidden></p><div class="aw-actions"><button class="btn primary" type="submit">Создать исследование</button></div></form>`, { size: 'card' });
      const form = currentDrawer && qs('#aw-research-form', currentDrawer);
      form?.addEventListener('submit', async event => {
        event.preventDefault();
        const values = Object.fromEntries(new FormData(form).entries()), error = qs('.aw-hire-error', form);
        const lines = text => String(text || '').split('\n').map(line => line.trim()).filter(Boolean);
        qsa('button, input, textarea', form).forEach(input => { input.disabled = true; });
        try {
          await API.aiResearchCreate({ title: String(values.title || '').trim(), family_name: String(values.family_name || '').trim(), source_type: 'research',
            hypotheses: lines(values.hypothesis), objectives: lines(values.objectives) });
          UI.closeDrawer(); domainCache.delete('lab_research'); announce('Исследование создано.'); await refresh();
        } catch (reason) {
          error.textContent = reason?.message || 'Не удалось создать исследование.'; error.hidden = false;
          qsa('button, input, textarea', form).forEach(input => { input.disabled = false; });
        }
      });
    }
    function renderResearch() {
      const tiles = `<div class="aw-btiles">${researchTiles()}</div>`;
      const data = cachedDomain('lab_research');
      const more = '<button class="btn sm" data-aw-new-research>+ Новое исследование</button>';
      if (!data) { content.innerHTML = tiles + bcard('Семейства исследований', '', '', loadingBlock('Загружаем исследования…')); return; }
      const list = rows(data.researches);
      if (data.unavailable || !list.length) {
        content.innerHTML = tiles + bcard('Семейства исследований', '', '', data.unavailable
          ? smallEmpty('Семейства исследований ведёт Лаборатория AI владельца; в этом рабочем пространстве они недоступны.')
          : empty('Семейств исследований пока нет', 'Создайте исследование в Лаборатории AI: гипотеза, цели и пороги — дальше команда проверяет стратегии и выбирает чемпиона.'), data.unavailable ? '' : more);
        return;
      }
      researchPick = Math.min(researchPick, list.length - 1);
      const families = list.map((row, index) => { const [mark, tone] = RESEARCH_MARKS[index % RESEARCH_MARKS.length];
        return `<button class="aw-fam${index === researchPick ? ' aw-fam-on' : ''}" data-aw-research="${index}"><span class="aw-icbox aw-t-${tone}">${icon(mark)}</span><span><b>${esc(row.title || row.family_name || 'Исследование')}</b><small>${esc(researchWhere(row) || '—')}</small><small>ID: ${esc(row.research_id || '—')}</small></span>${researchState(row)}</button>`; }).join('');
      content.innerHTML = tiles + bcard('Лаборатория создания стратегий', 'flask', 'violet', labPipeline(list))
        + bcard('Семейства исследований', '', '', `<div class="aw-research"><div class="aw-famlist">${families}</div><div class="aw-famdetail">${researchDetail(list[researchPick], researchPick)}</div></div>`, more, 'aw-bcard-research');
    }
    // Memory that agents no longer read is not shown as memory.
    const MEMORY_GONE = new Set(['revoked', 'expired', 'archived', 'retired', 'superseded']);
    let graphOpen = false;
    const KNOWLEDGE_GROUPS = Object.freeze([['rule', 'Правила разработки стратегий', 'rule'], ['registry', 'Реестр наших стратегий — история и статусы на июнь 2026', 'strategy'],
      ['lesson', 'Уроки', 'concept'], ['reference', 'Эталонная библиотека — образцы из открытых источников, не наши стратегии', 'ref'], ['data', 'Материалы исследований', 'data'],
      ['report', 'Отчёты команды — что было сделано по дням и неделям', 'report']]);
    const KNOWLEDGE_SHORT = Object.freeze({ rule: 'Правила', registry: 'Наши стратегии', lesson: 'Уроки', reference: 'Эталоны', data: 'Исследования', report: 'Отчёты', memory: 'Записи команды' });
    function renderMemory() {
      const memory = cachedDomain('memory'), knowledge = cachedDomain('knowledge');
      const summary = overview?.summaries?.memory, brief = overview?.summaries?.knowledge;
      const all = '';
      const legend = '<div class="aw-graph-legend"><span class="aw-lg-rule">● правила</span><span class="aw-lg-strategy">● наши стратегии</span><span class="aw-lg-concept">● уроки</span><span class="aw-lg-ref">● эталоны (открытые источники)</span><span class="aw-lg-data">● материалы исследований</span><span class="aw-lg-report">● отчёты команды</span><span class="aw-lg-context">● записи команды</span><span class="aw-muted">· потяните граф мышью, чтобы повернуть</span></div>';
      if (!memory || !knowledge) { content.innerHTML = bcard('Память и уроки', 'brain', 'violet', memoryBody(summary, brief), all) + bcard('Граф знаний', 'layers', 'cyan', loadingBlock('Загружаем память…')); return; }
      const records = memory.unavailable ? [] : items(memory).filter(record => !MEMORY_GONE.has(String(record.status || '')));
      const base = knowledge.unavailable ? [] : rows(knowledge.items);
      const drawn = records.length + base.length >= 3;
      const graph = drawn ? knowledgeGraph(base, records, graphOpen) : smallEmpty('Граф знаний появится, когда в памяти накопится хотя бы три записи и связи между ними.');
      content.innerHTML = bcard('Память и уроки', 'brain', 'violet', memoryBody(summary, brief), all)
        + bcard('Граф знаний', 'layers', 'cyan', graph + (drawn ? legend : ''), drawn ? `<button class="btn sm" data-aw-graph-toggle aria-pressed="${graphOpen}">${graphOpen ? 'Свернуть граф' : 'Раскрыть граф'}</button>` : '')
        + (base.length ? bcard('База знаний', 'archive', 'gray', knowledgeList(base)) : knowledge.unavailable ? '' : bcard('База знаний', 'archive', 'gray', smallEmpty('Документов базы знаний пока нет.')));
      mountGraph3d();
    }
    function knowledgeList(base) {
      return KNOWLEDGE_GROUPS.map(([kind, title], index) => {
        const group = base.filter(item => item.kind === kind);
        if (!group.length) return '';
        const documents = [...new Set(group.map(item => item.document))];
        return `<details class="aw-kb-group"${index === 0 ? ' open' : ''}><summary><b>${esc(title)}</b><span class="aw-muted">${esc(plural(group.length, 'фрагмент', 'фрагмента', 'фрагментов'))} · ${esc(plural(documents.length, 'документ', 'документа', 'документов'))}</span></summary>`
          + `<div class="aw-kb-items">${group.map(item => `<div class="aw-kb-item"><b>${esc(item.title)}</b>${item.title !== item.document ? `<small>${esc(item.document)}</small>` : ''}<p>${esc(item.summary || '')}</p></div>`).join('')}</div></details>`;
      }).join('');
    }
    // The knowledge graph in 3D: the kinds of knowledge sit on a sphere around
    // the centre, each kind's documents cluster around it, and the owner turns
    // the sphere with the mouse. New documents appear as new branches.
    let graphModel = null, graphFrame = 0;
    function knowledgeGraph(base, records, open) {
      const limit = open ? 16 : 8, kinds = [...KNOWLEDGE_GROUPS.filter(([kind]) => base.some(item => item.kind === kind)), ...(records.length ? [['memory', 'Записи команды', 'context']] : [])];
      const sphere = (index, total) => { const y = total > 1 ? 1 - index / (total - 1) * 2 : 0, r = Math.sqrt(1 - y * y), phi = index * 2.399963; return [Math.cos(phi) * r, y, Math.sin(phi) * r]; };
      const nodes = [{ x: 0, y: 0, z: 0, r: 9, tone: 'hub', label: 'Память', hub: true }], links = [];
      kinds.forEach(([kind, , tone], index) => {
        const [hx, hy, hz] = sphere(index, kinds.length), hub = nodes.push({ x: hx, y: hy, z: hz, r: 7, tone, label: KNOWLEDGE_SHORT[kind], hub: true }) - 1;
        links.push([0, hub]);
        const leaves = kind === 'memory' ? records.map(record => record.title || 'Запись') : [...new Set(base.filter(item => item.kind === kind).map(item => item.document))];
        leaves.slice(0, limit).forEach((label, at, shown) => {
          const [ox, oy, oz] = sphere(at, Math.max(shown.length, 2));
          links.push([hub, nodes.push({ x: hx * 1.6 + ox * .42, y: hy * 1.6 + oy * .42, z: hz * 1.6 + oz * .42, r: 4, tone, label }) - 1]);
        });
        if (leaves.length > limit) nodes[hub].label += ` · ещё ${leaves.length - limit}`;
      });
      graphModel = { nodes, links, yaw: .6, pitch: -.25, height: open ? 460 : 320 };
      return `<svg class="aw-memory-graph aw-graph3d${open ? ' aw-graph-open' : ''}" viewBox="0 0 720 ${graphModel.height}" role="img" aria-label="Граф знаний: ${esc(plural(nodes.length - 1, 'узел', 'узла', 'узлов'))}">`
        + links.map(() => '<line class="aw-graph-link"/>').join('')
        + nodes.map(node => `<g class="aw-g3-node"><title>${esc(node.label)}</title><circle class="aw-g-${node.tone} aw-graph-halo"/><circle class="aw-g-${node.tone}"/><text${node.hub ? ' class="aw-graph-centre"' : ''}>${esc(node.label.length > 28 ? node.label.slice(0, 27) + '…' : node.label)}</text></g>`).join('') + '</svg>';
    }
    function mountGraph3d() {
      root.cancelAnimationFrame?.(graphFrame);
      const svg = content.querySelector?.('.aw-graph3d'), model = graphModel;
      if (!svg || !model || !root.requestAnimationFrame) return;
      const lines = [...svg.querySelectorAll('line')], groups = [...svg.querySelectorAll('.aw-g3-node')];
      const W = 720, H = model.height, scale = Math.min(W, H) * .19, still = root.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
      let dragging = null, idle = 0;
      const draw = () => {
        const cy = Math.cos(model.yaw), sy = Math.sin(model.yaw), cp = Math.cos(model.pitch), sp = Math.sin(model.pitch);
        const points = model.nodes.map(node => {
          const x = node.x * cy + node.z * sy, z1 = -node.x * sy + node.z * cy, y = node.y * cp - z1 * sp, z = node.y * sp + z1 * cp;
          const depth = 3 / (3 + z);
          return { sx: W / 2 + x * scale * depth, sy: H / 2 + y * scale * depth, z, depth };
        });
        model.links.forEach(([a, b], index) => { const p = points[a], q = points[b], line = lines[index];
          line.setAttribute('x1', p.sx.toFixed(1)); line.setAttribute('y1', p.sy.toFixed(1)); line.setAttribute('x2', q.sx.toFixed(1)); line.setAttribute('y2', q.sy.toFixed(1));
          line.setAttribute('stroke-opacity', (.25 + .6 * Math.min(p.depth, q.depth) / 1.5).toFixed(2)); });
        model.nodes.map((node, index) => [index, points[index]]).sort((a, b) => b[1].z - a[1].z).forEach(([index, p]) => {
          const node = model.nodes[index], group = groups[index], [halo, dot] = group.querySelectorAll('circle'), text = group.querySelector('text');
          const r = node.r * p.depth;
          halo.setAttribute('cx', p.sx.toFixed(1)); halo.setAttribute('cy', p.sy.toFixed(1)); halo.setAttribute('r', (r + 5).toFixed(1));
          dot.setAttribute('cx', p.sx.toFixed(1)); dot.setAttribute('cy', p.sy.toFixed(1)); dot.setAttribute('r', r.toFixed(1));
          const left = p.sx < W / 2 - 4 && !node.hub;
          text.setAttribute('x', (node.hub ? p.sx : left ? p.sx - r - 6 : p.sx + r + 6).toFixed(1)); text.setAttribute('y', (node.hub ? p.sy - r - 7 : p.sy + 4).toFixed(1));
          text.setAttribute('text-anchor', node.hub ? 'middle' : left ? 'end' : 'start');
          group.setAttribute('opacity', Math.max(.25, Math.min(1, (p.depth - .55) * 1.6)).toFixed(2));
          // Labels of the far side stay hidden so the near ones read cleanly.
          text.setAttribute('visibility', node.hub || p.depth > .97 ? 'visible' : 'hidden');
          group.parentNode.appendChild(group);
        });
      };
      const tick = () => {
        if (!svg.isConnected) return;
        if (!dragging && !still && Date.now() - idle > 1500) { model.yaw += .0035; draw(); }
        graphFrame = root.requestAnimationFrame(tick);
      };
      svg.addEventListener('pointerdown', event => { dragging = { x: event.clientX, y: event.clientY }; svg.setPointerCapture?.(event.pointerId); svg.classList.add('aw-grabbing'); });
      svg.addEventListener('pointermove', event => {
        if (!dragging) return;
        model.yaw += (event.clientX - dragging.x) * .008; model.pitch = Math.max(-1.3, Math.min(1.3, model.pitch + (event.clientY - dragging.y) * .008));
        dragging = { x: event.clientX, y: event.clientY }; draw();
      });
      const release = () => { dragging = null; idle = Date.now(); svg.classList.remove('aw-grabbing'); };
      svg.addEventListener('pointerup', release); svg.addEventListener('pointercancel', release);
      draw();
      graphFrame = root.requestAnimationFrame(tick);
    }
    // The corner and the dock are redrawn on every refresh; an unchanged block
    // is left in place so faces do not reload and the log keeps its scroll.
    const painted = new WeakMap();
    const paint = (node, html) => { if (node && painted.get(node) !== html) { node.innerHTML = html; painted.set(node, html); } };
    // The goal is the owner's own sentence: what it is, by when, for how much,
    // and the task for this week. Progress counts only strategies trading on
    // the demo account, so nothing else is added to it here.
    const HORIZONS = Object.freeze([['', 'срок не задан'], ['month', 'Месяц'], ['quarter', 'Квартал'], ['year', 'Год']]);
    function goalHeader(goal) {
      // A date without a time is a calendar day, not an instant: build it in the
      // reader's own timezone so it never slips to the day before.
      const parts = String(goal.deadline || '').split('-').map(Number);
      const deadline = parts.length === 3 && parts.every(Number.isFinite) ? new Date(parts[0], parts[1] - 1, parts[2]) : null;
      const until = deadline && Number.isFinite(deadline.getTime()) ? ' · до ' + deadline.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' }) : '';
      return esc((goal.horizon_label || 'срок не задан') + (goal.title ? until : ''));
    }
    function renderCorner() {
      const box = qs('#aw-corner');
      if (!box) return;
      if (!overview?.enabled) { paint(box, ''); return; }
      const todays = rows(overview.tasks).filter(task => { const when = new Date(task.updated_at || task.created_at); return !Number.isNaN(when.getTime()) && sameDay(when); }).slice(0, 5);
      const done = task => taskOutcome(task) === 'ok';
      const goal = overview?.summaries?.goal && !overview.summaries.goal.unavailable ? overview.summaries.goal : { title: '' };
      const target = number(goal.target_usd) || 0, progress = number(goal.progress_usd) || 0;
      const share = target > 0 ? Math.min(100, progress / target * 100) : 0;
      paint(box, `<section class="aw-bcard aw-goal"><header class="aw-bcard-h"><span class="aw-icbox aw-t-green">${icon('goal')}</span><h2>Цель</h2><span class="aw-bcard-more aw-muted">${goalHeader(goal)}</span></header><div class="aw-bcard-b">`
        + `<div class="aw-goal-title">${goal.title ? esc(goal.title) : 'Цель ещё не задана'}</div><div class="aw-goal-bar"><span style="width:${share.toFixed(1)}%"></span></div>`
        + `<div class="aw-goal-row"><span><b>${esc(money(progress))}</b> <span class="aw-muted">из ${target > 0 ? esc(money(target)) : '—'}</span></span><span class="aw-muted">${target > 0 ? esc(pct(share)) : '0%'}</span></div>`
        + `<p class="aw-goal-note">Считаются только стратегии на демо-счёте${goal.title && target > 0 ? '. Прогресс появится, когда стратегия начнёт торговать на демо-счёте.' : ''}</p>`
        + `<h3>Задача на неделю</h3><div class="aw-goal-week">${goal.weekly_task ? esc(goal.weekly_task) : goal.title ? 'Задача на неделю не записана.' : 'Появится после того, как вы добавите цель.'}</div>`
        + `<h3>Сегодня</h3>${todays.length ? `<div class="aw-todo">${todays.map(task => `<button class="aw-todo-row${done(task) ? ' aw-todo-done' : ''}" data-aw-task="${esc(taskId(task))}"><i aria-hidden="true">${done(task) ? icon('check', 11) : ''}</i><span>${esc(taskTitle(task))}</span>${avatar(task.lead, 'xs')}</button>`).join('')}</div>` : '<p class="aw-goal-empty">Сегодня задач ещё не было.</p>'}`
        + `<button class="btn sm aw-goal-add" data-aw-goal>${icon('plus', 14)}${goal.title ? 'Изменить цель' : 'Добавить цель'}</button></div></section>`);
    }
    function openGoal() {
      const goal = overview?.summaries?.goal && !overview.summaries.goal.unavailable ? overview.summaries.goal : { title: '' };
      ++detailGeneration; detailKind = 'goal'; actionForm = null;
      openDrawer(goal.title ? 'Изменить цель' : 'Добавить цель', `<form id="aw-goal-form" class="aw-connect">`
        + `<p class="aw-muted">Цель своими словами: что должно получиться. Прогресс считается только по стратегиям, которые торгуют на демо-счёте; бэктесты в него не входят.</p>`
        + `<label>Цель<input name="title" maxlength="160" required value="${esc(goal.title || '')}" placeholder="например, Стратегии на демо-счёте приносят $3 000"></label>`
        + `<label>Срок<select name="horizon">${HORIZONS.map(([key, label]) => `<option value="${key}"${key === (goal.horizon || '') ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select></label>`
        + `<label>Сумма цели, $<input name="target_usd" type="number" min="0" step="100" value="${esc(String(number(goal.target_usd) || 0))}"></label>`
        + `<label>Задача на неделю<input name="weekly_task" maxlength="240" value="${esc(goal.weekly_task || '')}" placeholder="Одно предложение: что сделать за неделю"></label>`
        + `<p class="aw-hire-error" hidden></p><div class="aw-actions"><button class="btn primary" type="submit">Сохранить</button>${goal.title ? '<button class="btn" type="button" data-aw-goal-clear>Убрать цель</button>' : ''}</div></form>`, { size: 'card' });
      const form = currentDrawer && qs('#aw-goal-form', currentDrawer);
      form?.addEventListener('submit', event => { event.preventDefault(); void saveGoal(form, false); });
      qs('[data-aw-goal-clear]', form)?.addEventListener('click', () => { void saveGoal(form, true); });
      form?.elements.title.focus();
    }
    async function saveGoal(form, clear) {
      const values = Object.fromEntries(new FormData(form).entries()), error = qs('.aw-hire-error', form);
      qsa('button, input, select', form).forEach(input => { input.disabled = true; });
      try {
        await API.aiControlCenterGoalSave(clear ? { title: '' } : { title: String(values.title || '').trim(), horizon: values.horizon || '',
          target_usd: Number(values.target_usd) || 0, weekly_task: String(values.weekly_task || '').trim() });
        UI.closeDrawer(); announce(clear ? 'Цель убрана.' : 'Цель сохранена.'); await refresh();
      } catch (reason) {
        error.textContent = reason?.message || 'Не удалось сохранить цель.'; error.hidden = false;
        qsa('button, input, select', form).forEach(input => { input.disabled = false; });
      }
    }
    function renderDock() {
      const strip = qs('#aw-strip'), body = qs('#aw-log-body');
      if (!strip || !body) return;
      if (!overview?.enabled) { paint(strip, ''); paint(body, ''); return; }
      const agents = rows(overview.agents), { placed, others } = teamPlacement(agents);
      const face = agent => { const phase = agentPhase(agent), state = phase === 'busy' ? ' · работает' : phase === 'waiting' ? ' · ждёт проверки' : '';
        return `<button class="aw-strip-face${phase ? ' aw-strip-' + phase : ''}" data-aw-agent-card="${esc(agentId(agent))}" title="${esc(name(agent))} · ${esc(role(agent))}${state}" aria-label="${esc(name(agent))}${state}">${avatar(agent, 'sm')}</button>`; };
      const groups = [['lead', 'staff'], ['dev'], ['ops'], ['judges']].map(depts => placed.filter(([slot, agent]) => agent && depts.includes(slot.dept)).map(([, agent]) => face(agent)).join('')).filter(Boolean);
      if (others.length) groups.push(others.map(face).join(''));
      paint(strip, groups.join('<span class="aw-strip-sep" aria-hidden="true"></span>'));
      const byTask = new Map(rows(overview.tasks).map(task => [taskId(task), task]));
      const events = ownerEvents();
      paint(body, events.length ? events.slice(0, 40).map(event => {
        const task = byTask.get(String(event.task_id || '')), lead = task ? actor(task.lead) : null, when = event.time || event.timestamp || event.created_at;
        const who = lead ? name(lead) : 'Команда', raw = String(event.summary || event.title || 'Событие');
        const text = raw.startsWith(who + ' · ') ? raw.slice(who.length + 3) : raw;
        const model = task?.model && !MODEL_EXCLUDED.has(String(task.model)) ? ` <span class="aw-log-model">[${esc(prettyModel(task.model))}]</span>` : '';
        const line = `<time datetime="${esc(when || '')}">${esc(logTime(when))}</time><span><span class="aw-log-who">${esc(who)}</span>${model}  ${esc(text)}</span>`;
        return event.task_id ? `<button class="aw-log-line" data-aw-task="${esc(event.task_id)}">${line}</button>` : `<div class="aw-log-line">${line}</div>`;
      }).join('') : '<p class="aw-log-empty">Здесь появится ход работы: кто, через какую модель и что сделал.</p>');
    }
    function toggleLog(force) {
      const log = qs('#aw-log'), toggle = qs('#aw-log-toggle');
      if (!log || !toggle) return;
      const open = typeof force === 'boolean' ? force : !log.classList.contains('aw-log-open');
      log.classList.toggle('aw-log-open', open);
      toggle.setAttribute('aria-expanded', String(open));
      const hint = qs('.aw-log-hint', toggle); if (hint) hint.textContent = open ? 'свернуть' : 'развернуть';
    }
    function renderTab() {
      (tab === 'work' ? renderWork : tab === 'agents' ? renderAgents : tab === 'models' ? renderModels
        : tab === 'research' ? renderResearch : tab === 'memory' ? renderMemory : renderOverview)();
    }
    function renderHeader() {
      const stats = overview?.stats || {}, scope = overview?.scope || {};
      qs('#aw-run-demo').hidden = !canRunDemo(overview);
      qs('#aw-run-demo').disabled = demoBusy;
      qs('#aw-run-demo').textContent = demoBusy ? 'Выполняем проверки…' : 'Запустить проверочные задачи';
      qsa('.aw-diagnostics', shell).forEach(button => { button.disabled = overview?.enabled !== true; });
      const failed = number(stats.failed) || 0;
      const attention = Array.isArray(overview?.attention) ? rows(overview.attention).filter(ownerFacing).length : number(stats.attention) || 0;
      qs('#aw-pulse').innerHTML = overview?.enabled
        ? `<span><strong>${count(stats.agents ?? rows(overview?.agents).length)}</strong> в команде</span><span><strong>${count(stats.active_tasks)}</strong> в работе</span><span class="${attention ? 'aw-pulse-attention' : ''}"><strong>${count(attention)}</strong> ждут вас</span>${failed ? `<span class="aw-pulse-error"><strong>${count(failed)}</strong> с ошибкой</span>` : ''}`
        : badge('disabled');
      const context = qs('#aw-context'), synthetic = Boolean(scope.synthetic || overview?.synthetic);
      // The approved header has no status chip. Test data is still named, so an
      // isolated check is never taken for the owner's real work.
      context.hidden = !overview?.enabled || !synthetic;
      context.className = 'aw-env aw-env-synthetic';
      context.textContent = 'Тестовые данные';
      context.title = 'Изолированная проверка: задачи выполняют локальные проверочные обработчики на тестовых данных. Платные модели и торговые действия не вызываются; рейтинг не оценивает качество моделей.';
      qs('#aw-updated').textContent = 'Обновлено ' + date(new Date().toISOString());
      const badgeNode = qs('#aw-work-badge');
      if (badgeNode) { badgeNode.hidden = !(attention > 0); badgeNode.textContent = attention > 0 ? count(attention) : ''; }
      renderCorner();
      renderDock();
    }
    function selectTab(next, updateLocation, background = false, options = {}) {
      if (!background) stopPersonaAudio();
      if (!TABS.includes(next)) next = 'overview';
      tab = next;
      qsa('.aw-tabs [data-aw-tab]', shell).forEach(button => { const active = button.dataset.awTab === tab; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
      content.setAttribute('aria-labelledby', 'aw-tab-' + tab);
      if (updateLocation) root.history.replaceState(null, '', '#tab=' + encodeURIComponent(tab));
      // The click is answered at once: the chosen tab is drawn from what is
      // already loaded (or its skeleton the first time Work opens), and fresh
      // data replaces it quietly instead of the user waiting for a recompute.
      const firstWork = tab === 'work' && !workRows.length;
      if (updateLocation && !background && overview?.enabled) {
        if (firstWork) {
          content.setAttribute('aria-busy', 'true');
          content.innerHTML = '<div class="aw-skeleton-page" aria-label="Загрузка раздела"><div class="aw-skeleton aw-skeleton-strip"></div><div class="aw-skeleton-grid"><div class="aw-skeleton"></div><div class="aw-skeleton"></div><div class="aw-skeleton"></div></div></div>';
        } else {
          preserveView(content, renderTab);
          refreshFaces();
        }
      }
      if (!updateLocation) return loadTab(false, options);
      // Work used to read fresh tasks while its header/profile retained an old
      // overview indefinitely. User navigation refreshes both projections; the
      // first Work visit reads its list before the slower workspace summary.
      if (firstWork && overview?.enabled) return loadTab(false).then(() => refresh({ reuseWork: workRows.length > 0 }));
      return refresh();
    }
    function readError(error) {
      if (error?.status === 403) return empty('Нет доступа к этому разделу', 'Сервер не разрешил чтение в текущем рабочем пространстве. Если доступ изменился, обновите страницу.');
      if (error?.status === 404) return empty('Раздел недоступен', 'Этот раздел пока не включён в этой сборке.', '<button class="btn" data-aw-retry>Проверить снова</button>');
      return empty('Не удалось загрузить данные', 'Ничего не изменилось: сохранённые записи в порядке. Попробуйте загрузить ещё раз.', '<button class="btn" data-aw-retry>Повторить</button>');
    }
    function backgroundReadBlocked() {
      return disposed || document.hidden || mutationBusy || actionForm || demoBusy || pendingListReads > 0
        || personaAudio?.activePersona() || root.getSelection?.()?.isCollapsed === false
        || content.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
    }
    function preserveView(container, render) {
      if (!container) { render(); return; }
      const active = document.activeElement, inside = container.contains(active);
      const attributes = ['id', 'data-aw-detail-tab', 'data-aw-profile-tab', 'data-aw-task-action', 'data-aw-task', 'data-aw-agent', 'data-aw-filter', 'data-aw-domain', 'data-aw-entity', 'data-aw-task-chat', 'data-aw-router-task', 'data-aw-chart-chat', 'href'];
      const identity = inside ? attributes.filter(key => active?.hasAttribute?.(key)).map(key => [key, active.getAttribute(key)]) : [];
      const summaries = qsa('summary', container), summaryIndex = inside ? summaries.indexOf(active) : -1;
      const expanded = qsa('details', container).map((node, index) => ({ index, open: node.open, label: qs('summary', node)?.textContent }));
      const scrolling = [container, ...qsa('.aw-table-wrap, .aw-tabs, .aw-domain-nav', container)].map(node => [node.scrollTop, node.scrollLeft]);
      const pageX = root.scrollX, pageY = root.scrollY;
      render();
      const details = qsa('details', container);
      expanded.forEach(state => { const node = details[state.index]; if (node && qs('summary', node)?.textContent === state.label) node.open = state.open; });
      [container, ...qsa('.aw-table-wrap, .aw-tabs, .aw-domain-nav', container)].forEach((node, index) => {
        if (scrolling[index]) [node.scrollTop, node.scrollLeft] = scrolling[index];
      });
      if (inside && active?.isConnected === false) {
        const replacement = identity.length ? qsa('button, a, [tabindex]', container).find(node => identity.every(([key, value]) => node.getAttribute(key) === value))
          : summaryIndex >= 0 ? qsa('summary', container)[summaryIndex] : null;
        (replacement || (container === content ? qs('[data-aw-tab][aria-selected="true"]', shell) : currentDrawer))?.focus({ preventScroll: true });
      }
      if (Number.isFinite(pageX) && Number.isFinite(pageY) && (root.scrollX !== pageX || root.scrollY !== pageY)) root.scrollTo?.(pageX, pageY);
    }
    async function readWorkPages(pageCount, isCurrent) {
      const collected = [], visited = new Set();
      let cursor = '';
      ++pendingListReads;
      try {
        // Finite already-loaded page count plus a cursor cycle check. Every
        // request retains the existing server-side 50-row limit and filters.
        for (let page = 0; page < pageCount; ++page) {
          const result = await API.aiControlCenterTasks({ limit: 50, status: filter === 'all' ? '' : filter, query, cursor }, { signal });
          if (!isCurrent()) return null;
          collected.push(...items(result));
          cursor = result?.next_cursor || '';
          if (!cursor) break;
          if (visited.has(cursor)) throw new Error('task_cursor_cycle');
          visited.add(cursor);
        }
        return { items: collected, next_cursor: cursor || null };
      } finally { --pendingListReads; }
    }
    async function loadTab(append, options = {}) {
      const request = ++generation;
      if (!overview?.enabled) {
        content.innerHTML = empty('AI Центр пока выключен', 'Новый интерфейс включается сервером для конкретного окружения и рабочего пространства. Как только он включится, здесь появятся ваши модели, задачи и память.');
        content.setAttribute('aria-busy', 'false'); return;
      }
      content.setAttribute('aria-busy', 'true');
      try {
        if (tab === 'overview') preserveView(content, renderOverview);
        else if (tab === 'agents') {
          // The deputy's own state - who works, whether the team rests.
          if (!cachedDomain('duty')) await loadDomain('duty');
          if (request !== generation || disposed) return;
          preserveView(content, renderAgents);
        }
        else if (tab === 'work') {
          let result = options.workResult;
          if (!result) {
            ++pendingListReads;
            try { result = await API.aiControlCenterTasks({ limit: 50, status: filter === 'all' ? '' : filter, query, cursor: append ? nextCursor : '' }, { signal }); }
            finally { --pendingListReads; }
          }
          if (request !== generation || disposed) return;
          if (options.background && backgroundReadBlocked()) return;
          workRows = append ? workRows.concat(items(result)) : items(result);
          nextCursor = result?.next_cursor || null;
          // The questions the deputy brings from the duty controller.
          if (!cachedDomain('duty')) await loadDomain('duty');
          if (request !== generation || disposed) return;
          preserveView(content, renderWork);
        }
        else if (TAB_DATA[tab]) {
          // Draw what is cached (or the tab's skeleton) at once; a user visit
          // then reads fresh lists, a background refresh only missing ones.
          const keys = TAB_DATA[tab], missing = keys.some(key => !cachedDomain(key));
          if (missing) preserveView(content, renderTab);
          if (missing || !options.background) await Promise.all(keys.map(loadDomain));
          if (request !== generation || disposed) return;
          if (options.background && backgroundReadBlocked()) return;
          preserveView(content, renderTab);
        }
        refreshFaces();
      } catch (error) {
        if (error?.name !== 'AbortError' && request === generation && !disposed) content.innerHTML = readError(error);
      } finally { if (request === generation && !disposed) content.setAttribute('aria-busy', 'false'); }
    }
    async function refresh({ background = false, reuseWork = false } = {}) {
      if (disposed || background && (refreshing || backgroundReadBlocked())) return;
      if (!background) stopPersonaAudio();
      refreshing = true;
      const request = ++overviewGeneration;
      const listRequest = generation;
      const inspectorRequest = detailGeneration;
      const shownTask = detailKind === 'task' && currentDrawer?.classList.contains('open') && !actionForm
        ? taskId(detail?.task || detail) : '';
      const shownAgent = detailKind === 'agent' && currentDrawer?.classList.contains('open') && !actionForm
        ? agentId(profile) : '';
      qs('#aw-refresh').disabled = true;
      try {
        let result = null;
        if (!overview && !background && API.aiControlCenterOverviewSnapshot) {
          // First paint from the server's previous overview for this exact
          // authorization, then the fresh projection replaces it. When there
          // is no previous one the server computes it and that is the answer.
          const first = await API.aiControlCenterOverviewSnapshot({ signal });
          if (disposed || request !== overviewGeneration) return;
          if (!first?.snapshot?.cached) result = first;
          else if (first.enabled && tab !== 'work' && !overview) {
            overview = first;
            renderHeader();
            await loadTab(false);
            qs('#aw-updated').textContent = 'Показаны данные на ' + date(first.snapshot.computed_at) + ' · обновляем…';
          }
        }
        if (!result) result = await API.aiControlCenterOverview({ signal });
        if (disposed || request !== overviewGeneration) return;
        const identity = value => JSON.stringify([value?.scope?.environment, value?.scope?.workspace_id, value?.scope?.user_uuid, value?.scope?.synthetic]);
        const scopeChanged = overview && identity(result) !== identity(overview);
        if (scopeChanged) {
          ++detailGeneration; detail = null; profile = null; domainState = null; actionForm = null; workRows = []; nextCursor = null; demoKey = null;
          if (currentDrawer?.querySelector('.aw-inspector')) UI.closeDrawer();
          // Never retain a previous principal's visible data while the next
          // workspace is loading, even if an interaction began mid-request.
          overview = null; renderHeader(); content.innerHTML = '';
        }
        if (background && backgroundReadBlocked()) return;
        if (listRequest !== generation) return;
        const isCurrent = () => !disposed && request === overviewGeneration && listRequest === generation
          // readWorkPages owns pendingListReads; it must not block itself.
          && (!background || !document.hidden && !mutationBusy && !actionForm && !demoBusy
            && !personaAudio?.activePersona() && root.getSelection?.()?.isCollapsed !== false
            && !(content.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')));
        const workResult = tab === 'work' && result?.enabled
          ? reuseWork ? { items: workRows, next_cursor: nextCursor } : await readWorkPages(Math.max(1, Math.ceil(workRows.length / 50)), isCurrent) : null;
        if (!isCurrent() || tab === 'work' && result?.enabled && !workResult) return;
        overview = result;
        renderHeader();
        await selectTab(tab, false, background, { workResult, background });
        if (shownTask && inspectorRequest === detailGeneration && !actionForm && currentDrawer?.classList.contains('open')) {
          const latest = await API.aiControlCenterTask(shownTask, { signal });
          if (!disposed && request === overviewGeneration && inspectorRequest === detailGeneration && !actionForm
              && (!background || !backgroundReadBlocked())
              && currentDrawer?.classList.contains('open') && JSON.stringify(latest) !== JSON.stringify(detail)) {
            detail = latest;
            quietDrawer = true;
            try { drawTask(); } finally { quietDrawer = false; }
          }
        } else if (shownAgent && inspectorRequest === detailGeneration && !actionForm && currentDrawer?.classList.contains('open')) {
          if (!rows(overview.agents).some(value => agentId(value) === shownAgent)) {
            ++detailGeneration; profile = null; detailKind = ''; UI.closeDrawer();
          } else {
            quietDrawer = true;
            try { openProfile(shownAgent, detailTab); } finally { quietDrawer = false; }
          }
        }
      } catch (error) {
        if (error?.name !== 'AbortError' && !disposed && request === overviewGeneration) {
          if (background && ![401, 403].includes(error?.status)) {
            qs('#aw-updated').textContent = 'Обновление не завершено · показаны ранее загруженные данные';
            return; // Do not discard a form opened after the background GET.
          }
          ++detailGeneration; overview = null; detail = null; profile = null; domainState = null; actionForm = null; workRows = [];
          if (currentDrawer?.querySelector('.aw-inspector')) UI.closeDrawer();
          renderHeader(); content.innerHTML = readError(error); content.setAttribute('aria-busy', 'false');
        }
      } finally { if (request === overviewGeneration) { refreshing = false; if (!disposed) qs('#aw-refresh').disabled = false; } }
    }
    function detailRows(values, fallback) {
      if (!values.length) return smallEmpty(fallback);
      return values.map(value => `<div class="aw-detail-row"><strong>${esc(value.title || value.summary || value.result_summary || value.result || value.id || 'Запись')}</strong>${value.status ? `<div>${badge(value.status)}</div>` : ''}${value.detail || value.reason ? `<p>${esc(value.detail || value.reason)}</p>` : ''}${value.created_at ? `<p>${esc(date(value.created_at))}</p>` : ''}</div>`).join('');
    }
    function artifacts(values, sourceKind) {
      if (!values.length) return smallEmpty('Артефакты появятся после фактического выполнения и проверки задачи.');
      return values.map(artifact => {
        const url = safeArtifactUrl(artifact.url, sourceKind), media = artifact.media_type || artifact.mime_type || '';
        const image = url && ['image/svg+xml', 'image/png', 'image/jpeg', 'image/webp'].includes(media);
        return `<article class="aw-artifact">${image ? `<img src="${esc(url)}" alt="${esc(artifact.title || 'Артефакт задачи')}" loading="lazy" referrerpolicy="same-origin">` : ''}<div class="aw-artifact-body"><h3>${esc(artifact.title || 'Артефакт')}</h3><div class="aw-inline">${artifact.synthetic ? '<span class="aw-status aw-info">SYNTHETIC</span>' : ''}<span class="aw-muted">${esc(media)}</span></div>${artifact.summary ? `<p class="aw-text">${esc(artifact.summary)}</p>` : ''}<div class="aw-hash">SHA256 ${esc(artifact.sha256 || 'не указан')}</div>${url ? `<a class="btn sm" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Открыть артефакт ↗</a>` : '<span class="aw-status aw-warning">Ссылка не разрешена</span>'}</div></article>`;
      }).join('');
    }
    function evaluations(values) {
      if (!values.length) return smallEmpty('Оценок нет. Отсутствие наблюдений не означает провал.');
      return values.map(value => `<section class="aw-panel"><div class="aw-panel-body"><div class="aw-inline"><strong>${transportResponseOnly(value) ? 'Без оценки содержания' : esc(pct(value.score_pct ?? value.observed_score_pct))}</strong><span class="aw-muted">${transportResponseOnly(value) ? 'только техническая проверка' : 'проверенных критериев этого ответа'}</span></div>${transportVerificationNote(value)}<p class="aw-note">${esc(value.scope || value.rubric_key || 'Класс конкретной задачи')} · ${esc(value.verifier || value.evaluator || 'Источник проверки не указан')}</p><div class="aw-stack">${rows(value.rubric || value.checks).map(check => `<div class="aw-inline">${badge(check.passed === true ? 'passed' : check.passed === false ? 'failed' : 'pending')}<span class="aw-text">${esc(check.label || check.key || check.summary)}</span></div>`).join('')}</div>${value.summary ? `<p class="aw-text">${esc(value.summary)}</p>` : ''}${value.response_sha256 ? `<div class="aw-hash">RESPONSE SHA256 ${esc(value.response_sha256)}</div>` : ''}${value.input_sha256 ? `<div class="aw-hash">INPUT SHA256 ${esc(value.input_sha256)}</div>` : ''}<p class="aw-field-hint">Проверка одного ответа не является общей оценкой качества модели или торговой стратегии.</p></div></section>`).join('');
    }
    function openDrawer(title, html, options = {}) {
      if (quietDrawer && currentDrawer?.classList.contains('open') && currentDrawer.querySelector('.aw-inspector')) {
        // Refresh only the read-only inspector content: keep its width, scroll
        // and keyboard focus, and never interrupt SF Chat or a consent form.
        const body = qs('.drawer-b', currentDrawer);
        if (body) preserveView(body, () => { body.innerHTML = `<div class="aw-inspector">${html}</div>`; });
        const heading = qs('.drawer-title h3', currentDrawer);
        if (heading) heading.textContent = title;
        currentDrawer.setAttribute('aria-label', title);
        refreshFaces(currentDrawer);
        return currentDrawer;
      }
      stopPersonaAudio();
      // The inspector re-renders on every tab switch and refresh. By then the
      // active element is the drawer, so re-capturing here would make Escape
      // "return" focus into the panel it just closed instead of to the row,
      // card or button the owner actually came from.
      const active = document.activeElement;
      const inspectorOpen = Boolean(currentDrawer && currentDrawer.classList.contains('open')
        && currentDrawer.querySelector('.aw-inspector'));
      if (!inspectorOpen && active && active !== document.body && !currentDrawer?.contains(active)) returnFocus = active;
      currentDrawer = UI.drawer(`<h3>${esc(title)}</h3>`, `<div class="aw-inspector">${html}</div>`);
      // A model card is narrow, as in the prototype; tools keep the wide panel.
      currentDrawer.classList.add(options.size === 'card' ? 'aw-drawer-card' : options.size === 'model' ? 'aw-drawer-model' : 'wide');
      currentDrawer.setAttribute('role', 'dialog'); currentDrawer.setAttribute('aria-modal', 'true'); currentDrawer.setAttribute('aria-label', title); currentDrawer.tabIndex = -1;
      currentDrawer.focus();
      refreshFaces(currentDrawer);
      return currentDrawer;
    }
    const recordId = item => String(item?.id || item?.task_id || '');
    const recordValue = (item, key) => item?.[key] ?? item?.profile?.[key] ?? item?.presentation?.[key] ?? item?.schedule?.[key] ?? item?.packet?.[key];
    function domainNav(selected) {
      return `<nav class="aw-domain-nav" aria-label="Инструменты в панели">${DOMAIN_GROUPS.map(([label, keys]) => `<span class="aw-nav-group">${label ? `<span class="aw-launcher-label">${esc(label)}</span>` : ''}${keys.map(key => `<button class="aw-filter" data-aw-domain="${key}" aria-pressed="${selected === key}">${esc(DOMAINS[key].title)}</button>`).join('')}</span>`).join('')}</nav>`;
    }
    function domainLimitations(data) {
      const limits = rows(data?.limitations).map(item => typeof item === 'string' ? item : item.summary || item.message || '').filter(Boolean);
      return limits.length ? `<div class="aw-domain-limits"><strong>Ограничения текущего контура</strong><ul>${limits.map(text => `<li>${esc(text)}</li>`).join('')}</ul></div>` : '';
    }
    function domainActionButtons(item) {
      const schedule = ['routines', 'calendar'].includes(domainState?.key) && item.status === 'accepted'
        ? `<button class="btn sm" data-aw-schedule-source="${esc(recordId(item))}">Проверить расписание</button>` : '';
      return allowedDomainActions(domainState?.data, item).map(action => `<button class="btn sm${['disconnect', 'revoke', 'archive', 'withdraw', 'cancel'].includes(action) ? ' aw-danger-action' : ''}" data-aw-domain-action="${esc(action)}" data-aw-entity="${esc(recordId(item))}">${esc(actionLabel(action))}</button>`).join('') + schedule;
    }
    function domainItemCard(item) {
      if (domainState.key === 'external_agents') return `<article class="aw-domain-card"><div class="aw-domain-card-head"><button class="aw-table-title" data-aw-domain-item="${esc(recordId(item))}">${esc(item.display_name || 'Внешний агент')}</button>${badge(item.status)}</div>${externalAgentCard(item)}<div class="aw-actions">${domainActionButtons(item)}</div></article>`;
      const id = recordId(item), metrics = item.observed_eval || item.evaluation;
      const title = esc(item.title || item.label || item.name || item.model || 'Запись');
      const heading = domainState.key === 'system' ? `<strong>${title}</strong>` : `<button class="aw-table-title" data-aw-domain-item="${esc(id)}">${title}</button>`;
      const component = domainState.key === 'memory' ? memoryScopeCard(item) : domainState.key === 'models' ? modelProtocolCard(item) : domainState.key === 'system' && typeof item.implemented === 'boolean' ? `<dl class="aw-detail-grid"><div><dt>Реализовано</dt><dd>${item.implemented ? 'Да' : 'Нет'}</dd></div><div><dt>Включено</dt><dd>${item.enabled ? 'Да' : 'Нет'}</dd></div><div><dt>Как работает сейчас</dt><dd>${esc(item.mode)}</dd></div><div><dt>Отвечает</dt><dd>${item.available ? 'Да' : 'Нет'}</dd></div></dl>${item.note ? `<p class="aw-note">${esc(item.note)}</p>` : ''}` : '';
      return `<article class="aw-domain-card"><div class="aw-domain-card-head">${heading}${item.display_status ? taskBadge(item) : badge(item.status)}</div>${item.summary || item.description ? `<p class="aw-text">${esc(item.summary || item.description)}</p>` : ''}<div class="aw-domain-card-meta">${item.model ? `<span>Модель: ${esc(item.model)}</span>` : ''}${item.provider ? `<span>${esc(item.provider)}</span>` : ''}${item.synthetic === true ? '<span class="aw-status aw-info">SYNTHETIC</span>' : ''}${item.updated_at || item.created_at ? `<time>${esc(date(item.updated_at || item.created_at))}</time>` : ''}</div>${domainState.key === 'models' ? `<p class="aw-field-hint">${esc(connectionLabel(item))}</p>` : ''}${metrics ? `<div class="aw-domain-card-meta"><span>Проверка ответа: ${esc(pct(metrics.score_pct ?? metrics.observed_score_pct))}</span>${number(metrics.sample_size) == null ? '' : `<span>n = ${count(metrics.sample_size)}</span>`}</div><p class="aw-note">Результат указанной проверки, не общий процент профессионального качества.</p>` : ''}${item.result_text ? `<p class="aw-result-excerpt">${esc(String(item.result_text).slice(0, 240))}</p>` : ''}${component}${domainState.key === 'system' && item.fields ? `<details class="aw-technical"><summary>Технические детали</summary><pre class="aw-result-text">${esc(publicJSON(item.fields))}</pre></details>` : ''}<div class="aw-actions">${domainActionButtons(item)}</div></article>`;
    }
    const GRANT_KINDS = { schedule: 'Расписание', delegation: 'Делегирование' };
    function automationGrantCard(item) {
      const id = recordId(item), kind = GRANT_KINDS[item.kind] || 'Разрешение';
      // `operational` is the grant's own answer, and it is not the same as its
      // status: an approved grant whose window has closed no longer authorises
      // anything, and saying «Одобрено» alone would hide that.
      const standing = item.operational === true ? 'да'
        : item.expired === true ? 'нет — срок истёк' : 'нет';
      const devices = { local_owner: 'Этот компьютер владельца', permanent: 'Доверенное устройство', session: 'Только текущая сессия' };
      const heading = (item.kind === 'delegation' ? 'Разрешение на делегирование' : item.kind === 'schedule' ? 'Разрешение на расписание' : kind);
      return `<article class="aw-domain-card"><div class="aw-domain-card-head"><button class="aw-table-title" data-aw-domain-item="${esc(id)}">${esc(heading)}</button>${badge(item.operational === true ? 'active' : item.expired === true ? 'expired' : item.status)}</div>`
        + `<dl class="aw-detail-grid"><div><dt>Действует сейчас</dt><dd>${standing}</dd></div>`
        + `<div><dt>Срок</dt><dd>${esc(date(item.expires_at))}</dd></div>`
        + `<div><dt>Потолок на вызов</dt><dd>${esc(cost(item.max_call_cost_usd))}</dd></div>`
        + `<div><dt>Устройство</dt><dd>${esc(devices[item.device_mode] || item.device_mode || '—')}</dd></div></dl>`
        + `<div class="aw-actions">${domainActionButtons(item)}</div><div class="aw-hash">ID ${esc(id)}</div></article>`;
    }
    function drawDomain() {
      if (!domainState) return;
      const { key, data } = domainState, meta = DOMAINS[key];
      const permitted = allowedDomainActions(data), createAction = key === 'models' ? 'connect' : key === 'publications' ? 'prepare' : 'create';
      const create = (permitted.includes(createAction) ? `<button class="btn primary" data-aw-domain-action="${createAction}" data-aw-entity="new">+ ${esc(meta.create || actionLabel(createAction))}</button>` : '') + ['bind_existing', 'propose_consensus', 'suggest_routine', 'commission', 'propose'].filter(action => permitted.includes(action)).map(action => `<button class="btn" data-aw-domain-action="${action}" data-aw-entity="new">${esc(actionLabel(action))}</button>`).join('');
      const history = ['models', 'model_tasks', 'experiments'].includes(key) ? `<div class="aw-actions"><button class="aw-link-button" data-aw-domain="models">Подключения</button><button class="aw-link-button" data-aw-domain="model_tasks">История задач моделей</button><button class="aw-link-button" data-aw-domain="experiments">Сравнения</button></div>` : '';
      let body;
      if (data.enabled !== true) body = empty('Раздел не разрешён в текущем контексте', 'Функция не удалена из плана. Сервер не разрешил её использование; проверьте ограничения ниже.');
      else if (key === 'decisions') {
        // Authorizations recorded for ordinary requests are history, not decisions
        // waiting for judgement; they stay available but folded.
        const all = items(data), proposals = all.filter(item => item.decision_type !== 'explicit_task_authorization');
        const authorizations = all.filter(item => item.decision_type === 'explicit_task_authorization');
        body = (proposals.length ? `<div class="aw-domain-grid">${proposals.map(domainItemCard).join('')}</div>` : smallEmpty('Предложений для проверки пока нет. Создайте решение, чтобы получить независимую оценку Court.'))
          + (authorizations.length ? `<details class="aw-technical"><summary>Разрешения на выполнение задач · ${count(authorizations.length)}</summary><p class="aw-note">Записываются автоматически, когда вы разрешаете выполнить конкретный запрос. Это не решения Court.</p><div class="aw-domain-grid">${authorizations.map(domainItemCard).join('')}</div></details>` : '');
      }
      else {
        const visibleItems = key === 'models' ? [...items(data), ...rows(data.shared)] : items(data);
        body = visibleItems.length ? `<div class="aw-domain-grid">${visibleItems.map(key === 'automation' ? automationGrantCard : domainItemCard).join('')}</div>` : smallEmpty('Записей пока нет. Они появятся после первого подтверждённого действия.');
      }
      body += processIntelligencePanel(data, key);
      if (key === 'automation') {
        const admin = data.capability_admin || {}, granted = admin.granted === true;
        // Three separate conditions, shown as three separate facts.
        const control = admin.can_manage === true
          ? `<div class="aw-actions"><button class="btn${granted ? '' : ' primary'}" data-aw-capability="${granted ? 'revoke' : 'grant'}" data-aw-capability-user="${esc(admin.user_id)}">${granted ? 'Отозвать разрешение на автоматизацию' : 'Выдать разрешение на автоматизацию'}</button></div>`
          : `<p class="aw-note">Разрешение выдаёт владелец рабочего пространства. Самостоятельно повысить свои права здесь нельзя.</p>`;
        body = `<section class="aw-detail-section"><h3>Условия автоматизации</h3><dl class="aw-detail-grid"><div><dt>Разрешение на автоматизацию</dt><dd>${badge(granted ? 'active' : 'disabled')}</dd></div><div><dt>Механизм расписаний</dt><dd>${badge(data.flags?.AI_SCHEDULER_V1 ? 'active' : 'disabled')}</dd></div><div><dt>Согласие на рутину</dt><dd>Отдельное действие для каждой записи</dd></div></dl>${control}</section>` + body;
        const schedules = rows(data.schedules);
        const commissions = rows(data.commissions);
        if (commissions.length) body += `<section class="aw-detail-section"><h3>Поручения Координатору</h3><div class="aw-domain-grid">${commissions.map(row => `<article class="aw-domain-card"><h4>${esc(row.goal || 'Поручение Координатору')}</h4>${badge(row.status)}<p class="aw-text">${row.stage === 'awaiting_approval' ? 'Исходный результат готов. Дочерние задания ещё не разрешены.' : row.graph ? 'Состояние общего результата и отдельных вкладов — в задаче ниже.' : 'Выполняется исходное задание; делегирование ещё не разрешено.'}</p><div class="aw-actions"><button class="btn" data-aw-task="${esc(row.root_task_id)}">Исходная задача и SF Chat</button>${row.graph?.id ? `<button class="btn" data-aw-task="${esc(row.graph.id)}">Общий результат и вклады</button>` : ''}${allowedDomainActions(data, row).map(action => `<button class="btn" data-aw-domain-action="${action}" data-aw-entity="${esc(row.id)}">${esc(actionLabel(action))}</button>`).join('')}</div><p class="aw-note">${esc(row.limitation || '')}</p></article>`).join('')}</div></section>`;
        if (schedules.length) body += `<section class="aw-detail-section"><h3>Расписания</h3><div class="aw-domain-grid">${schedules.map(row => `<article class="aw-domain-card"><h4>${esc('Расписание: ' + plural(rows(row.occurrences).length, 'запуск', 'запуска', 'запусков') + (rows(row.occurrences)[0]?.due_at ? ' с ' + date(rows(row.occurrences)[0].due_at) : ''))}</h4><div class="aw-inline">${badge(row.status)}${row.grant_status ? badge(row.grant_status) : ''}</div>${rows(row.occurrences).length ? `<ul class="aw-occurrences">${rows(row.occurrences).map(item => `<li><time>${esc(date(item.due_at))}</time>${badge(item.status)}${item.task_id ? taskLink(item.task_id, 'Результат') : ''}</li>`).join('')}</ul>` : '<p class="aw-text">Запусков ещё не было.</p>'}<div class="aw-hash">ID ${esc(row.id || '')}</div><div class="aw-actions">${allowedDomainActions(data, row).map(action => `<button class="btn" data-aw-domain-action="${action}" data-aw-entity="${esc(row.id)}">${esc(actionLabel(action))}</button>`).join('')}</div></article>`).join('')}</div></section>`;
      }
      if (key === 'system') {
        if (data.preview_dataset) body = note('Учебные записи Preview отделены от Local. Набор создаётся только явной кнопкой оператора, без запуска задач, выдачи прав или оценки моделей.') + body;
        const flags = flagRows(data.flags);
        if (flags.length) body += `<section class="aw-detail-section"><h3>Серверные флаги</h3><div class="aw-flag-list">${flags.map(flag => `<div class="aw-flag"><code>${esc(flag.name)}</code>${badge(flag.enabled ? 'active' : 'disabled')}</div>`).join('')}</div></section>`;
        if (data.budget) body += `<dl class="aw-detail-grid"><div><dt>Доступный лимит (USD)</dt><dd>${esc(cost(data.budget.remaining_usd))}</dd></div><div><dt>Измеренные расходы (USD)</dt><dd>${esc(cost(data.budget.spent_usd))}</dd></div></dl>`;
      }
      if (key === 'router' && data.enabled === true) {
        const tasks = rows(data.source_tasks);
        body = note('Выберите исходное задание. Router покажет своё предложение отдельно от модели, которая уже отвечала; применение создаст новое задание, не заменит старый результат.') + (tasks.length ? tasks.map(task => `<article class="aw-domain-card"><h4>${esc(taskTitle(task))}</h4>${taskBadge(task)}<button class="btn" data-aw-router-task="${esc(taskId(task))}">Открыть выбор подключения</button></article>`).join('') : smallEmpty('Поддержанных исходных задач пока нет. Сначала выполните своё задание через SF Chat.'));
      }
      openDrawer(meta.title, `${domainNav(key)}<div class="aw-domain-heading"><div><h2>${esc(meta.title)}</h2><p>${esc(meta.description)}</p></div><div class="aw-actions">${create}<button class="btn" data-aw-domain-refresh>Обновить</button></div></div>${history}${domainLimitations(data)}${body}${data.next_cursor ? '<button class="btn" data-aw-domain-more>Показать ещё</button>' : ''}`);
    }
    async function changeAutomationCapability(mode, userId) {
      // The account store is the only authority here: it accepts this call from
      // the owner alone, and refuses it for everyone else regardless of what
      // the page renders.
      if (mutationBusy || !['grant', 'revoke'].includes(mode) || !/^[0-9]{1,20}$/.test(String(userId || ''))) return;
      mutationBusy = true; domainCache.clear();
      try {
        await API.authUserPermission(userId, 'ai_automation', mode === 'grant' ? true : null);
      } catch (error) {
        if (error?.name !== 'AbortError') openDrawer(DOMAINS.automation.title, domainNav('automation') + readError(error));
        mutationBusy = false;
        return;
      }
      mutationBusy = false;
      await openDomain('automation');
    }

    async function openDomain(key, append) {
      if (!knownDomain(key) || overview?.enabled !== true || mutationBusy) return;
      const request = ++detailGeneration;
      const prior = append && domainState?.key === key ? domainState.data : null;
      actionForm = null; detailKind = 'domain';
      // A tool opened before is drawn at once from its last list in this same
      // workspace; the fresh list then replaces it quietly. Writes clear this.
      const scopeKey = JSON.stringify([overview?.scope?.environment, overview?.scope?.workspace_id, overview?.scope?.user_uuid]);
      const shown = prior ? null : domainCache.get(key);
      const instant = shown?.scope === scopeKey;
      if (instant) { domainState = { key, data: shown.data }; drawDomain(); }
      else openDrawer(DOMAINS[key].title, domainNav(key) + loadingBlock('Загружаем записи раздела…'));
      try {
        const data = await API.aiControlCenterDomain(key, { limit: 50, cursor: prior?.next_cursor || '' }, { signal });
        if (key === 'router' && data.enabled === true) {
          const tasks = await API.aiControlCenterDomain('model_tasks', { limit: 100 }, { signal });
          data.source_tasks = items(tasks).filter(task => task.conversation_id && task.model_id && rows(data.task_classes).includes(task.task_class || task.rubric_key));
        }
        if (disposed || request !== detailGeneration) return;
        if (!prior) domainCache.set(key, { scope: scopeKey, data });
        if (instant && (actionForm || mutationBusy)) return;
        domainState = { key, data: prior ? { ...data, items: items(prior).concat(items(data)) } : data };
        if (instant) { quietDrawer = true; try { drawDomain(); } finally { quietDrawer = false; } }
        else drawDomain();
        root.history.replaceState(null, '', '#tab=' + encodeURIComponent(tab) + '&domain=' + encodeURIComponent(key));
      } catch (error) {
        // A failed quiet refresh keeps the list already on screen.
        if (error?.name !== 'AbortError' && request === detailGeneration && !disposed && !instant) openDrawer(DOMAINS[key].title, domainNav(key) + readError(error));
      }
    }
    function domainRecord(item) {
      const key = domainState.key, meta = DOMAINS[key];
      const fields = domainFormFields(key, key === 'models' ? 'connect' : 'create').filter(spec => spec.type !== 'password' && !(key === 'personas' && spec.optionalIfMissing));
      const description = fields.filter(spec => recordValue(item, spec.key) !== undefined && recordValue(item, spec.key) !== null && recordValue(item, spec.key) !== '').map(spec => {
        const raw = recordValue(item, spec.key);
        const value = spec.type === 'persona' ? (item.persona_name || 'Persona недоступна') : spec.type === 'datetime-local' ? date(raw) : spec.type === 'select' ? spec.options.find(([id]) => id === raw)?.[1] || 'Не указано' : typeof raw === 'object' ? publicJSON(raw) : String(raw);
        return `<div><dt>${esc(spec.label)}</dt><dd class="aw-pre-wrap">${esc(value)}${spec.type === 'persona' ? `<details class="aw-technical"><summary>Идентификатор Persona</summary><code>${esc(raw)}</code></details>` : ''}</dd></div>`;
      }).join('');
      const verification = item.observed_eval || item.evaluation;
      const evaluationBody = verification ? evaluations([verification]) : '';
      const result = item.result_text || item.response_text || item.output_text;
      const resultBody = (result ? `<section class="aw-detail-section"><h3>Фактический ответ</h3><pre class="aw-result-text">${esc(result)}</pre></section>` : '') + followupCard(item) + handoffCard(item);
      const sources = rows(item.source_ids || item.evidence_ids);
      const sourceBody = sources.length ? `<section class="aw-detail-section"><h3>Источники</h3>${sources.map(id => `<div class="aw-hash">ARTIFACT ${esc(id)}</div>`).join('')}</section>` : '';
      const versions = rows(item.versions);
      const versionBody = versions.length ? `<section class="aw-detail-section"><h3>История версий</h3>${versions.map(version => `<article class="aw-domain-card"><div class="aw-domain-card-meta"><strong>Версия ${esc(version.version || version.revision || '—')}</strong><time>${esc(date(version.created_at))}</time></div><p class="aw-text">${esc(version.notes || version.summary || '')}</p>${version.parameters ? `<pre class="aw-result-text">${esc(publicJSON(version.parameters))}</pre>` : ''}</article>`).join('')}</section>` : '';
      const courtBody = key === 'decisions' ? courtPanel(item) : '';
      const comparison = rows(item.results || item.comparison || item.tasks);
      const comparisons = key === 'experiments' && comparison.length ? `<section class="aw-detail-section"><h3>Сопоставимые результаты</h3><div class="aw-domain-grid">${comparison.map(result => `<article class="aw-domain-card"><strong>${esc(result.model || result.label || result.model_id || 'Модель')}</strong>${badge(result.status)}<dl class="aw-detail-grid"><div><dt>Результат проверки</dt><dd>${esc(pct(result.score_pct ?? result.evaluation?.score_pct ?? result.evaluation?.observed_score_pct ?? result.observed_eval?.score_pct))}</dd></div><div><dt>Длительность</dt><dd>${number(result.latency_ms) == null ? 'не измерена' : esc(count(result.latency_ms)) + ' мс'}</dd></div><div><dt>Стоимость</dt><dd>${esc(cost(result.cost_usd))}</dd></div></dl>${result.task_id || result.id ? `<button class="aw-link-button" data-aw-model-task="${esc(result.task_id || result.id)}">Ответ и доказательства →</button>` : ''}</article>`).join('')}</div></section>` : '';
      const modelTaskLink = key === 'model_tasks' && (item.id || item.task_id) ? `<button class="btn" data-aw-task-chat="${esc(recordId(item))}">Открыть в SF Chat</button>` : '';
      const metaFields = `<dl class="aw-detail-grid"><div><dt>Ревизия</dt><dd>${count(item.revision)}</dd></div><div><dt>Обновлено</dt><dd>${esc(date(item.updated_at || item.created_at))}</dd></div>${key !== 'external_agents' && item.model ? `<div><dt>Запрошенная модель</dt><dd>${esc(item.model)}</dd></div>` : ''}${key === 'models' ? `<div><dt>Ключ</dt><dd>${item.credentials_configured === true ? 'Настроен · не выводится' : 'Не настроен'}</dd></div>` : ''}${key === 'model_tasks' ? `<div><dt>Model ID от провайдера</dt><dd>${esc(item.actual_model || 'Не предоставлен')}</dd></div><div><dt>Измеренная стоимость</dt><dd>${esc(cost(item.cost_usd))}</dd></div><div><dt>Длительность</dt><dd>${number(item.latency_ms) == null ? 'не измерена' : count(item.latency_ms) + ' мс'}</dd></div>` : ''}</dl>`;
      const personaBody = key === 'memory' ? memoryScopeCard(item) : key === 'external_agents' ? externalAgentCard(item) : key === 'personas' ? personaPresentationCard(item, avatar(item, 'lg')) : key === 'models' ? modelProtocolCard(item) : '';
      const displayTitle = key === 'external_agents' ? (item.display_name || item.title || item.label || item.name || 'Внешний агент') : (item.title || item.label || item.name || item.model || 'Запись');
      openDrawer(meta.title + ' · ' + displayTitle, `${domainNav(key)}<div class="aw-actions"><button class="aw-link-button" data-aw-domain="${key}">← Все записи</button>${domainActionButtons(item)}${modelTaskLink}</div><h2 class="aw-inspector-title">${esc(displayTitle)}</h2><div class="aw-inline">${badge(item.status)}${item.synthetic === true ? '<span class="aw-status aw-info">SYNTHETIC</span>' : ''}</div>${domainLimitations(item)}${item.summary ? `<p class="aw-text">${esc(item.summary)}</p>` : ''}${metaFields}${personaBody}<dl class="aw-detail-grid">${description}</dl>${resultBody}${evaluationBody}${sourceBody}${versionBody}${courtBody}${comparisons}<div class="aw-hash">ID ${esc(recordId(item))}${item.correlation_id ? '<br>CORRELATION ' + esc(item.correlation_id) : ''}</div>`);
    }
    async function openDomainItem(id) {
      if (!domainState || !id || mutationBusy) return;
      if (domainState.key === 'router') return openRouterTask(id);
      if (domainState.key === 'model_tasks') return openTask(id);
      const request = ++detailGeneration, key = domainState.key;
      actionForm = null;
      openDrawer(DOMAINS[key].title, domainNav(key) + loadingBlock('Загружаем запись…'));
      try {
        const result = await API.aiControlCenterDomainItem(key, id, { signal });
        if (disposed || request !== detailGeneration) return;
        const item = result.item || result;
        domainState.item = item;
        const list = items(domainState.data), at = list.findIndex(row => recordId(row) === recordId(item));
        if (at >= 0) list[at] = item;
        domainRecord(item);
      } catch (error) { if (error?.name !== 'AbortError' && request === detailGeneration && !disposed) openDrawer(DOMAINS[key].title, domainNav(key) + readError(error)); }
    }
    function playPersonaDescription(id) {
      const persona = domainState?.key === 'personas' ? domainState.item : null;
      if (!persona || persona.id !== id || !personaCanSpeak(persona) || mutationBusy) return;
      const box = currentDrawer && qs('#aw-persona-audio-status', currentDrawer);
      if (!personaAudio) { if (box) box.textContent = 'Модуль озвучивания недоступен. Остаются статичный аватар и текст.'; return; }
      personaAudio.play({ persona, text: personaReadText(persona), face: qs('[data-aw-persona-visual] .agent-face', currentDrawer), userInitiated: true });
    }
    function openProcessSuggestion(id) {
      const domain = domainState?.key, data = domainState?.data, process = data?.process_intelligence;
      if (mutationBusy || data?.enabled !== true || process?.version !== 'process-intelligence-v1' || process.incomplete === true || process.automation_enabled !== false) return;
      const candidate = rows(process.candidates).find(item => item?.id === id && item.domain === domain);
      try { processCandidatePayload(candidate, domain); } catch (_) { return; }
      ++detailGeneration;
      actionForm = { domain, action: 'propose', id, key: root.crypto.randomUUID(), revision: null, processCandidate: { ...candidate } };
      openDrawer('Рассмотреть повторяющуюся работу', `${domainNav(domain)}${processCandidateCard(candidate, domain, false)}<form class="aw-form" id="aw-domain-form" autocomplete="off"><p class="aw-note">Сохранится предложение для отдельного принятия или отклонения. Права, бюджет и расписание не изменятся; ожидающие проверки останутся открытыми.</p><p class="aw-form-error" id="aw-form-error" role="alert" hidden></p><div class="aw-actions"><button type="submit" class="btn primary">Сохранить предложение</button><button type="button" class="btn" data-aw-domain="${esc(domain)}">Отмена</button></div></form>`);
    }
    function formField(spec, record, dependencies) {
      const id = 'aw-field-' + spec.key, prior = (actionForm?.action === 'update' ? (spec.key === 'operational_purpose' && record?.memory_scope === 'operational' ? record.purpose : spec.key === 'purpose' && record?.memory_scope === 'operational' ? '' : recordValue(record, spec.key)) : undefined) ?? spec.default;
      let value = prior == null || spec.type === 'password' ? '' : Array.isArray(prior) ? prior.join('\n') : typeof prior === 'object' ? publicJSON(prior) : String(prior);
      if (spec.type === 'datetime-local' && value) { const parsed = new Date(value); if (Number.isFinite(parsed.getTime())) value = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
      const frozenMemoryBinding = actionForm?.domain === 'memory' && actionForm?.action === 'update' && ['memory_scope', 'strategy_project_id', 'task_id'].includes(spec.key);
      const required = spec.required ? ' required' : '', attrs = `id="${id}" name="${esc(spec.key)}"${required}${frozenMemoryBinding ? ' disabled' : ''}${spec.max && spec.type !== 'number' ? ` maxlength="${spec.max}"` : ''}`;
      let input;
      if (spec.type === 'publication-source') {
        const sources = rows(dependencies.collection?.source_candidates);
        input = `<select ${attrs}><option value="">Выберите проверенный источник</option>${sources.map(source => `<option value="${esc(source.source_kind + ':' + source.source_id)}">${esc(source.title || source.source_id)} · ${esc(source.source_kind)}</option>`).join('')}</select>`;
        if (!sources.length) input += '<p class="aw-field-hint">Проверенных источников ещё нет. Публикация станет доступной после сохранения и проверки результата.</p>';
      } else if (spec.type === 'record') {
        const candidates = rows(dependencies.collection?.[spec.source]);
        input = `<select ${attrs}><option value="">Не выбрано</option>${candidates.map(source => `<option value="${esc(recordId(source))}"${value === recordId(source) ? ' selected' : ''}>${esc(source.title || source.summary || 'Сохранённая запись')}</option>`).join('')}</select>`;
        if (!candidates.length) input += '<p class="aw-field-hint">Доступных записей пока нет. Создайте проект или выполните задачу в этом пространстве.</p>';
      } else if (spec.type === 'records') {
        const candidates = rows(dependencies.collection?.[spec.source]);
        input = candidates.length ? `<div class="aw-choice-list">${candidates.map(source => `<label><input type="checkbox" name="${esc(spec.key)}" value="${esc(recordId(source))}"><span><strong>${esc(source.title || source.summary || 'Сохранённый результат')}</strong><small>${esc(recordId(source))}</small></span></label>`).join('')}</div>` : '<p class="aw-field-hint">Нет доступных подтверждённых источников. Сначала выполните и проверьте задачи.</p>';
        input += `<textarea id="${id}" name="${esc(spec.key)}_manual" rows="2" placeholder="Известные UUID источников" spellcheck="false">${esc(value)}</textarea>`;
      } else if (spec.type === 'evidence') {
        const sources = rows(dependencies.evidence).filter(item => item.media_type === 'application/json');
        input = sources.length ? `<div class="aw-choice-list">${sources.map(source => `<label><input type="checkbox" name="evidence_ids" value="${esc(recordId(source))}"><span><strong>${esc(source.title || 'JSON-доказательство')}</strong><small>${esc(source.sha256 || recordId(source))}</small></span></label>`).join('')}</div>` : '<p class="aw-field-hint">Сохранённые JSON-доказательства пока не опубликованы. Выполните проверяемую задачу через модель или существующее бэктестирование.</p>';
        input += `<textarea id="${id}" name="evidence_ids_manual" rows="2" placeholder="Известные UUID (необязательно при выборе выше)" spellcheck="false">${esc(value)}</textarea>`;
      } else if (spec.type === 'source_task') {
        const tasks = items(dependencies.tasks).filter(task => task.conversation_id && task.model_id && task.source_kind !== 'bounded_delegation_result');
        input = `<select ${attrs}><option value="">Выберите задачу из SF Chat</option>${tasks.map(task => `<option value="${esc(recordId(task))}">${esc(taskTitle(task))} · ${esc(taskClass(task))}</option>`).join('')}</select>`;
        if (!tasks.length) input += '<p class="aw-field-hint">Сначала выполните своё проверяемое задание через SF Chat. Наличие модели не заменяет исходную задачу.</p>';
      } else if (spec.type === 'model') {
        const candidates = items(dependencies.models).filter(model => (model.connected === true || model.can_execute_test_only === true) && model.status === 'active' && recordId(model) !== record?.model_id && model.persona_id !== record?.persona_id);
        input = `<select ${attrs}><option value="">Выберите подключение</option>${candidates.map(model => `<option value="${esc(recordId(model))}">${esc(model.label || model.model)} · ${esc(connectionLabel(model))}</option>`).join('')}</select>`;
        if (!candidates.length) input += '<p class="aw-field-hint">Нужно активное подключение другой Persona. Новые ключи или бюджет автоматически не назначаются.</p>';
      } else if (spec.type === 'models') {
        const models = items(dependencies.models).filter(model => (model.connected === true || model.can_execute_test_only === true) && !['disconnected', 'archived', 'disabled'].includes(model.status));
        input = models.length ? `<div class="aw-choice-list">${models.map(model => `<label><input type="checkbox" name="${esc(spec.key)}" value="${esc(recordId(model))}"><span><strong>${esc(model.label || model.model)}</strong><small>${esc(connectionLabel(model))} · ${esc(model.model || '')}</small></span></label>`).join('')}</div>` : '<div class="aw-small-empty">Нет доступных подключений. Сначала подключите и проверьте модели.</div><button type="button" class="aw-link-button" data-aw-domain="models">Открыть подключения →</button>';
      } else if (['select', 'persona', 'provider', 'binding'].includes(spec.type)) {
        const options = spec.type === 'persona' ? items(dependencies.personas).filter(person => person.status === 'active').map(person => [recordId(person), person.name || person.title]) : spec.type === 'provider' ? rows(dependencies.models?.providers).map(provider => [provider.id, provider.label]) : spec.type === 'binding' ? rows(dependencies.models?.owner_bindings).map(binding => [binding.id, (binding.name || binding.id) + ' · ' + (binding.provider || '') + ' / ' + (binding.model || '')]) : spec.options;
        input = `<select ${attrs}>${['persona', 'binding'].includes(spec.type) ? '<option value="">Выберите запись</option>' : ''}${options.map(([key, label]) => `<option value="${esc(key)}"${value === key ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select>`;
        if (spec.type === 'persona' && !options.length) input += '<p class="aw-field-hint">Сначала создайте и активируйте Persona в этом рабочем пространстве.</p><button type="button" class="aw-link-button" data-aw-domain="personas">Создать / активировать Persona →</button>';
        if (spec.type === 'provider' && !options.length) input += '<p class="aw-field-hint">Сервер не предоставил доступных провайдеров.</p>';
        if (spec.type === 'binding' && !options.length) input += '<p class="aw-field-hint">Нет разрешённых настроенных подключений владельца. Глобальные ключи не запрашиваются и не показываются.</p>';
      } else if (['textarea', 'ids', 'json', 'aliases'].includes(spec.type)) input = `<textarea ${attrs} rows="${['ids', 'aliases'].includes(spec.type) ? 3 : 4}" spellcheck="${spec.type === 'textarea' ? 'true' : 'false'}">${esc(value)}</textarea>`;
      else input = `<input ${attrs} type="${spec.type}" value="${esc(value)}"${spec.type === 'number' ? ` min="${spec.min}" max="${spec.max}" step="${spec.step || 1}"` : ''}${spec.type === 'password' ? ' autocomplete="new-password" spellcheck="false" autocapitalize="off"' : ' autocomplete="off"'}>`;
      return `<div class="aw-form-field"><label for="${id}">${esc(spec.label)}${spec.required ? ' <span aria-hidden="true">*</span>' : ''}</label>${input}${spec.hint ? `<p class="aw-field-hint">${esc(spec.hint)}</p>` : ''}</div>`;
    }
    async function openScheduleSource(id) {
      const domain = domainState?.key;
      if (!['routines', 'calendar'].includes(domain) || mutationBusy) return;
      const request = ++detailGeneration;
      openDrawer('Проверить расписание', smallEmpty('Проверка принятого источника и разрешений…'));
      try {
        const [response, automation, models, tasks] = await Promise.all([
          API.aiControlCenterDomainItem(domain, id, { signal }),
          API.aiControlCenterDomain('automation', {}, { signal }),
          API.aiControlCenterDomain('models', { limit: 100 }, { signal }),
          API.aiControlCenterDomain('model_tasks', { limit: 100 }, { signal })]);
        if (disposed || request !== detailGeneration) return;
        const record = response.item || response;
        if (record.id !== id || record.status !== 'accepted' || !Number.isSafeInteger(record.revision)
            || !rows(automation.actions).includes('propose')) throw new Error('Нужно принятое предложение и отдельное разрешение на автоматизацию.');
        const source = { domain, id, revision: record.revision, status: record.status, title: record.title };
        actionForm = { domain: 'automation', action: 'propose', id, item: record,
          key: root.crypto.randomUUID(), revision: record.revision, scheduleSource: source };
        const specs = domainFormFields('automation', 'propose');
        openDrawer('Проверить расписание', `<h2>${esc(record.title)}</h2><p class="aw-note">Принятое предложение, ревизия ${count(record.revision)}. Сейчас проверяется план; запуски ещё не разрешены.</p><form class="aw-form" id="aw-domain-form"><div class="aw-form-grid">${specs.map(spec => formField(spec, null, { models, tasks })).join('')}</div><p class="aw-form-error" id="aw-form-error" role="alert" hidden></p><button type="submit" class="btn primary">Проверить расписание</button><button type="button" class="btn" data-aw-domain="${domain}">Отмена</button></form>`);
      } catch (error) {
        if (!disposed && request === detailGeneration) openDrawer('Расписание недоступно', readError(error));
      }
    }
    async function openDomainAction(action, id, task, chatSeed) {
      if (domainState?.key === 'automation' && action === 'propose' && id === 'new') {
        openDrawer('Выберите принятое предложение', `${domainNav('automation')}<p class="aw-note">Сначала примите рутину или событие, затем нажмите «Проверить расписание» в этой записи. Согласие на предложение и разрешение расписания — отдельные действия.</p><button class="btn" data-aw-domain="routines">Рутины</button><button class="btn" data-aw-domain="calendar">Календарь</button>`);
        return;
      }
      const key = task ? 'tasks' : domainState?.key;
      let record = task || (id === 'new' ? null : domainState?.item && recordId(domainState.item) === id ? domainState.item : [...items(domainState?.data), ...rows(domainState?.data.commissions), ...rows(domainState?.data.delegations), ...rows(domainState?.data.schedules)].find(item => recordId(item) === id));
      const allowed = task ? rows(task.allowed_actions || task.actions) : allowedDomainActions(domainState?.data, record);
      if (!key || !allowed.includes(action) || mutationBusy || id !== 'new' && !record) return;
      if (action === 'clarify_commission' && record?.request_seed) record = { ...record, ...record.request_seed, topology: rows(record.request_seed.parent_indices).some(index => index >= 0) ? 'chain' : 'parallel' };
      if (action === 'commission' && chatSeed) record = { goal: chatSeed.goal };
      if (key === 'publications' && action === 'publish' || key === 'automation' && action === 'approve_commission') return; // Only a validated preview opens these approvals.
      if (key === 'router' && action === 'apply') return;
      const request = ++detailGeneration;
      actionForm = { domain: key, action, item: record, id, key: root.crypto.randomUUID(), revision: number(record?.revision), chatSource: chatSeed?.chat_source };
      const specs = domainFormFields(key, action, domainState?.data.presentation_catalog), dependencies = { models: key === 'models' ? domainState.data : null, evidence: domainState?.data.evidence_candidates, collection: domainState?.data };
      openDrawer(actionLabel(action), smallEmpty('Подготовка формы и проверка доступных записей…'));
      try {
        if (specs.some(spec => spec.type === 'persona')) dependencies.personas = await API.aiControlCenterDomain('personas', { limit: 100 }, { signal });
        if (specs.some(spec => ['models', 'model'].includes(spec.type))) dependencies.models = await API.aiControlCenterDomain('models', { limit: 100 }, { signal });
        if (specs.some(spec => spec.type === 'source_task')) dependencies.tasks = await API.aiControlCenterDomain('model_tasks', { limit: 100 }, { signal });
        if (disposed || request !== detailGeneration) return;
        const external = ['verify', 'test', 'task', 'review', 'handoff', 'commission'].includes(action) || key === 'experiments';
        const confirm = external ? 'Разрешаю отправить это задание выбранным подключениям в пределах существующего бюджета.' : action === 'publish_to_workspace' ? 'Разрешаю участникам этого рабочего пространства читать содержание и происхождение опубликованной записи.' : ['archive', 'revoke', 'withdraw', 'disconnect', 'cancel', 'dismiss', 'suspend'].includes(action) ? 'Подтверждаю это изменение выбранной записи.' : '';
        const warning = external ? note('Режим каждого подключения указан при выборе. SYNTHETIC проверяет механику без внешнего вызова и не подтверждает качество модели. Для реального подключения сервер проверяет существующий бюджет; измеренная стоимость может быть неизвестна до ответа. Не отправляйте секреты или личные данные.') : action === 'publish_to_workspace' ? note('Будет создана отдельная общая запись в текущем workspace. Личный источник сохраняется. Не публикуйте секреты или чужие личные данные; отзыв общей записи или её источника прекращает доступ.') : action === 'bind_existing' ? note('Только связь с одним существующим разрешённым Local-подключением. Ключ не копируется; новый бюджет не создаётся. Отключение связи не удаляет исходное подключение владельца.') : key === 'routines' || key === 'calendar' ? note('Это запись предложения / события, не запуск фонового исполнителя. Автоматизация остаётся выключенной.') : '';
        const back = key === 'tasks' ? `<button type="button" class="btn" data-aw-task="${esc(id)}">Назад к задаче</button>` : `<button type="button" class="btn" data-aw-domain="${key}">Отмена</button>`;
        openDrawer(DOMAINS[key].title + ' · ' + actionLabel(action), `<div class="aw-domain-heading"><div><h2>${esc(actionLabel(action))}</h2><p>${esc(record?.title || record?.label || record?.name || DOMAINS[key].description)}</p></div></div>${warning}<form class="aw-form" id="aw-domain-form" autocomplete="off"><div class="aw-form-grid">${specs.map(spec => formField(spec, record, dependencies)).join('')}</div>${!specs.length ? '<p class="aw-text">Действие относится только к выбранной записи. История и права проверяются сервером.</p>' : ''}${confirm ? `<label class="aw-confirm"><input type="checkbox" name="confirmation" required><span>${esc(confirm)}</span></label>` : ''}<p class="aw-form-error" id="aw-form-error" role="alert" hidden></p><div class="aw-actions"><button type="submit" class="btn primary">${esc(actionLabel(action))}</button>${back}</div><p class="aw-field-hint">Ни workspace, ни права, ни бюджет не принимаются из формы. ${record ? 'Изменение привязано к ревизии ' + count(record.revision) + '.' : ''}</p></form>`);
        if (key === 'models' && action === 'connect') qs('#aw-domain-form', currentDrawer)?.insertAdjacentHTML('beforebegin', modelConnectionGuide());
        if (chatSeed) {
          const goal = qs('#aw-field-goal', currentDrawer);
          if (goal) { goal.value = chatSeed.goal; goal.readOnly = true; }
          qs('#aw-domain-form', currentDrawer)?.insertAdjacentHTML('beforebegin', '<p class="aw-note">Продолжение исходного сообщения SF Chat. Цель сохранена; выберите данные, подключения и ожидаемый результат. Самостоятельного запуска пока нет.</p>');
        }
        if (key === 'external_agents' && action === 'create' && domainState?.data.test_connection) qs('#aw-domain-form', currentDrawer)?.insertAdjacentHTML('beforebegin', '<p class="aw-note">SYNTHETIC · только разрешённое Development-пространство.</p><button type="button" class="btn" data-aw-external-test-fill>Заполнить Development-агентом</button>');
      } catch (error) { if (error?.name !== 'AbortError' && request === detailGeneration && !disposed) openDrawer(actionLabel(action), readError(error)); }
    }
    async function openRouterTask(id) {
      if (mutationBusy) return;
      const request = ++detailGeneration;
      actionForm = null;
      openDrawer(DOMAINS.router.title, domainNav('router') + smallEmpty('Чтение исходной задачи и кандидатов…'));
      try {
        const response = await API.aiControlCenterDomainItem('router', id, { signal });
        if (disposed || request !== detailGeneration) return;
        const data = response.item || response;
        if (!data.task || data.task.id !== id) throw { status: 409 };
        domainState = { key: 'router', data, item: { ...data.task, actions: data.actions } };
        const choice = data.actual_choice || {};
        openDrawer(DOMAINS.router.title, `${domainNav('router')}<h2>Подключение для исходной задачи</h2><p class="aw-text">${choice.routing_applied === true ? 'Эту задачу создал Router по подтверждённому выбору.' : 'В исходной задаче подключение выбрано явно, не Router.'}</p><div class="aw-actions"><button class="btn" data-aw-task="${esc(id)}">Открыть исходную задачу</button>${domainActionButtons(domainState.item)}</div>${domainLimitations(data)}<details class="aw-technical"><summary>Фактический выбор, кандидаты и основания</summary><pre>${esc(publicJSON({ actual_choice: choice, candidates: data.items, policy_version: data.policy_version, flags: data.flags }))}</pre></details>`);
      } catch (error) { if (!disposed && request === detailGeneration) openDrawer(DOMAINS.router.title, domainNav('router') + readError(error)); }
    }
    function openRouterPreview(prepared, source) {
      if (prepared?.applied !== false || prepared?.requires_explicit_apply !== true || prepared?.creates_new_task !== true || prepared.task_id !== recordId(source)
          || !prepared.preview_ref || typeof prepared.preview_ref !== 'object' || Array.isArray(prepared.preview_ref)
          || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(prepared.preview_ref.artifact_id || '')
          || !/^[0-9a-f]{64}$/.test(prepared.preview_ref.sha256 || '')
          || !/^[0-9a-f]{64}$/.test(prepared.selection_sha256 || '') || !Number.isSafeInteger(prepared.source_revision) || prepared.source_revision < 1) throw { status: 409, code: 'routing_preview_changed' };
      const canApply = rows(prepared.actions).includes('apply') && prepared.status === 'selected';
      actionForm = canApply ? { domain: 'router', action: 'apply', id: recordId(source), item: source, key: root.crypto.randomUUID(), revision: prepared.source_revision, routing: prepared } : null;
      openDrawer('Предпросмотр Router · запусков нет', `${domainNav('router')}<h2>${canApply ? 'Выбор подготовлен — требуется разрешение' : 'Нет доступного разрешённого выбора'}</h2><p class="aw-note">Исходный результат сохраняется. Применение создаёт новое задание с теми же входными данными через штатный исполнитель. Сервер проверит актуальность показанного выбора; при изменении потребуется новый предпросмотр.</p><details class="aw-technical"><summary>Точное выбранное подключение, класс и evidence</summary><pre>${esc(publicJSON(prepared))}</pre></details>${domainLimitations(prepared)}${canApply ? '<form id="aw-domain-form" class="aw-form"><label class="aw-confirm"><input type="checkbox" name="confirmation" required><span>Разрешаю новый запуск на показанном подключении в рамках текущего бюджета.</span></label><p class="aw-form-error" id="aw-form-error" role="alert" hidden></p><button class="btn primary" type="submit">Разрешить новый запуск</button></form>' : ''}<button class="btn" data-aw-router-task="${esc(recordId(source))}">Вернуться к исходному выбору</button>`);
    }
    function openCoordinatorPreview(prepared, source) {
      if (!validCoordinatorPreview(prepared, source)) throw { status: 409, code: 'coordinator_plan_changed' };
      actionForm = { domain: 'automation', action: 'approve_commission', id: recordId(source), item: source,
        key: root.crypto.randomUUID(), revision: number(source.revision), coordinator: { prepared, source } };
      const plan = prepared.plan;
      const nodes = rows(plan.nodes).map((node, index) => `<li>Проверка ${index + 1} · ${node.parent_index < 0 ? 'получает исходные факты' : 'получает вклад проверки ' + (node.parent_index + 1)} · уровень ${count(node.depth)}</li>`).join('');
      openDrawer('Проверить план делегирования', `${domainNav('automation')}<section class="aw-publication-preview"><span class="aw-status aw-review">ПЛАН НЕ РАЗРЕШЁН · ДОЧЕРНИХ ЗАПУСКОВ НЕТ</span><h2>${esc(prepared.goal)}</h2><ol>${nodes}</ol><p class="aw-note">${esc(prepared.limitation)}</p><details class="aw-technical"><summary>Точные подключения, источники и хеш плана</summary><pre>${esc(publicJSON(plan))}</pre><div class="aw-hash">${esc(prepared.approved_plan_sha256)}</div></details></section>${note('Вы разрешаете только показанный план и срок. Сервер заново проверит источники, подключения, флаги и существующий бюджет. Каждый результат и общий вывод потребуют отдельной проверки.')}<form class="aw-form" id="aw-domain-form" autocomplete="off"><div class="aw-form-grid">${domainFormFields('automation', 'approve_commission').map(spec => formField(spec, null, {})).join('')}</div><label class="aw-confirm"><input type="checkbox" name="confirmation" required><span>Я проверил(а) план и разрешаю эти дочерние задания в указанных пределах.</span></label><p class="aw-form-error" id="aw-form-error" role="alert" hidden></p><div class="aw-actions"><button type="submit" class="btn primary">Разрешить этот план</button><button type="button" class="btn" data-aw-domain="automation">Отмена</button></div></form>`);
    }
    function openPublicationPreview(prepared, source) {
      if (!validPublicationPreview(prepared, source)) throw { status: 409, code: 'social_approved_snapshot_required' };
      const snapshot = prepared.snapshot;
      actionForm = { domain: 'publications', action: 'publish', id: 'new', key: root.crypto.randomUUID(), revision: prepared.source_revision, publication: { prepared, source } };
      const fields = domainFormFields('publications', 'publish');
      const metrics = snapshot.metrics && typeof snapshot.metrics === 'object' && !Array.isArray(snapshot.metrics) ? Object.entries(snapshot.metrics).filter(([, value]) => ['number', 'string', 'boolean'].includes(typeof value)) : [];
      const card = `<article class="aw-publication-preview"><div class="aw-inline"><span class="aw-status aw-review">ПРЕДПРОСМОТР · НЕ ОПУБЛИКОВАНО</span><span class="aw-status aw-info">${esc(snapshot.kind || 'Проверенный результат')}</span></div><h2>${esc(snapshot.title)}</h2><p class="aw-text">${esc(snapshot.summary)}</p>${metrics.length ? `<dl class="aw-detail-grid">${metrics.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>` : ''}<p class="aw-field-hint">Источник ${esc(source.source_kind)} · ревизия ${count(prepared.source_revision)} · ${esc(date(snapshot.timestamp_utc))}</p><div class="aw-hash">SOURCE ${esc(source.source_id)}<br>SNAPSHOT SHA256 ${esc(prepared.snapshot_sha256)}</div>${rows(snapshot.evidence_sha256).map(hash => `<div class="aw-hash">EVIDENCE ${esc(hash)}</div>`).join('')}${domainLimitations({ limitations: snapshot.limitations })}</article>`;
      openDrawer('Проверить публикацию в SF Social', `${domainNav('publications')}${card}${note('Публикуется только этот неизменяемый снимок и ваш комментарий. Изменение источника потребует нового предпросмотра. Сырые ответы, private Memory, файлы источника и ключи не включены.')}<form class="aw-form" id="aw-domain-form" autocomplete="off"><div class="aw-form-grid">${fields.map(spec => formField(spec, null, {})).join('')}</div><label class="aw-confirm"><input type="checkbox" name="confirmation" required><span>Я проверил(а) снимок и выбранную видимость. Подтверждаю публикацию постоянного снимка в SF Social.</span></label><p class="aw-form-error" id="aw-form-error" role="alert" hidden></p><div class="aw-actions"><button type="submit" class="btn primary">Опубликовать в SF Social</button><button type="button" class="btn" data-aw-domain="publications">Отмена</button></div></form>`);
    }
    async function submitDomain(event) {
      const form = event.target;
      if (form.id !== 'aw-domain-form' || !currentDrawer?.contains(form)) return;
      event.preventDefault();
      if (!actionForm || mutationBusy || !form.reportValidity()) return;
      const state = actionForm, values = {}, errorBox = qs('#aw-form-error', form);
      for (const spec of domainFormFields(state.domain, state.action)) {
        if (spec.optionalIfMissing && !form.elements.namedItem(spec.key)) continue;
        values[spec.key] = spec.type === 'models' ? qsa(`input[name="${spec.key}"]:checked`, form).map(input => input.value) : ['evidence', 'records'].includes(spec.type) ? qsa(`input[name="${spec.key}"]:checked`, form).map(input => input.value).concat(String(form.elements.namedItem(spec.key + '_manual')?.value || '').split(/[\s,]+/).filter(Boolean)) : form.elements.namedItem(spec.key)?.value || '';
      }
      let payload;
      try {
        if (state.intentPlan) {
          const choice = form.elements.namedItem('intent_choice')?.value;
          if (!rows(state.intentPlan.prepared.choices).some(row => row.id === choice && row.available)) throw new Error('Выберите доступный ожидаемый результат.');
          payload = { ...state.intentPlan.source, selection: { id: choice, plan_sha256: state.intentPlan.prepared.plan_sha256 } };
        } else {
          if (state.domain === 'automation' && ['commission', 'clarify_commission'].includes(state.action)) {
            const raw = String(values.input_text || '').trim();
            if (!raw.startsWith('[')) {
              if (!/^-?\d+(?:\s*[,;\s]\s*-?\d+)*$/.test(raw)) throw new Error('Введите целые числа через запятую.');
              values.input_text = JSON.stringify(raw.split(/[,;\s]+/).map(Number));
            }
          }
          payload = state.scheduleApproval ? { ...state.scheduleApproval.payload } : state.processCandidate ? processCandidatePayload(state.processCandidate, state.domain) : domainPayload(state.domain, state.action, values);
          if (state.chatSource) payload.chat_source = state.chatSource;
        }
        if (state.scheduleSource) payload.source_domain = state.scheduleSource.domain;
      }
      catch (error) { errorBox.textContent = error.message; errorBox.hidden = false; return; }
      if (state.domain === 'publications' && state.action === 'publish') {
        const publication = state.publication;
        if (!publication || !validPublicationPreview(publication.prepared, publication.source)) { errorBox.textContent = 'Сначала подготовьте и проверьте снимок публикации.'; errorBox.hidden = false; return; }
        payload = { ...payload, ...publication.source, approved_snapshot_sha256: publication.prepared.snapshot_sha256, confirm_permanent: true };
      }
      if (state.domain === 'automation' && state.action === 'approve_commission') {
        try {
          const approval = state.coordinator;
          if (!approval || !validCoordinatorPreview(approval.prepared, approval.source)) throw new Error('Нужен актуальный предпросмотр плана.');
          const choice = JSON.stringify(payload);
          if (approval.choice && approval.choice !== choice) throw new Error('Для изменения срока после попытки отправки откройте план заново.');
          approval.payload ||= coordinatorApproval(approval.prepared, approval.source, values, Date.now());
          approval.choice = choice;
          payload = approval.payload; // Fixed expiry and idempotency across transport retries.
        } catch (error) { errorBox.textContent = error.message; errorBox.hidden = false; return; }
      }
      if (state.action === 'review_result') payload.source_sha256 = state.item?.human_review?.source_sha256;
      if (state.domain === 'router' && state.action === 'apply') {
        if (!state.routing?.preview_ref || !rows(state.routing.actions).includes('apply')) { errorBox.textContent = 'Нужен актуальный предпросмотр Router.'; errorBox.hidden = false; return; }
        payload = { preview_ref: state.routing.preview_ref };
      }
      const body = { payload, idempotency_key: state.key };
      if (Number.isSafeInteger(state.revision) && state.revision >= 0) body.expected_revision = state.revision;
      mutationBusy = true; domainCache.clear(); errorBox.hidden = true;
      qsa('button, input, select, textarea', form).forEach(input => { input.disabled = true; });
      try {
        const result = await API.aiControlCenterDomainAction(state.domain, state.id, state.action, body);
        if (disposed) return;
        if (result?.ok === false) throw { status: 409 };
        if (state.domain === 'automation' && state.action === 'propose' && state.scheduleSource) {
          if (!validSchedulePreview(result, state.scheduleSource, payload)) throw new Error('Источник или план расписания изменился. Откройте форму заново.');
          mutationBusy = false;
          actionForm = { ...state, action: 'enable', scheduleApproval: { payload: { ...payload, approved_plan_sha256: result.approved_plan_sha256 } }, revision: state.scheduleSource.revision };
          openDrawer('Разрешить проверенное расписание', `${domainNav('automation')}<h2>${esc(state.scheduleSource.title)}</h2><p class="aw-note">${result.plan.synthetic === true ? 'SYNTHETIC · без внешнего провайдера; не оценка качества модели.' : 'Исполнение выбранным подключением в пределах существующих прав и бюджета.'} Предложение принято ранее; расписание ещё не включено.</p><ol>${rows(result.plan.due_at).map(value => `<li>${esc(date(value))}</li>`).join('')}</ol><p>Вызовов: ${count(result.plan.due_at.length)} · потолок вызова: ${esc(payload.max_call_cost_usd)} USD · разрешение: ${count(payload.grant_hours)} ч.</p><details><summary>Проверяемый план</summary><pre>${esc(publicJSON(result.plan))}</pre></details><form id="aw-domain-form"><label class="aw-confirm"><input type="checkbox" name="confirmation" required>Разрешаю именно эти запуски и выбранное подключение.</label><p id="aw-form-error" role="alert" hidden></p><button class="btn primary" type="submit">Включить по расписанию</button><button type="button" class="btn" data-aw-domain="automation">Отмена</button></form>`);
          return;
        }
        if (state.domain === 'automation' && ['commission', 'clarify_commission'].includes(state.action) && result?.status === 'clarification_required') {
          mutationBusy = false;
          actionForm = { ...state, intentPlan: { prepared: result, source: payload } };
          const choices = rows(result.choices).map(choice => `<label class="aw-confirm"><input type="radio" name="intent_choice" value="${esc(choice.id)}" required${choice.available ? '' : ' disabled'}><span>${esc(choice.label)}${choice.reason ? '<small>Недостаточно данных для разбиения между выбранными специалистами. Измените исходные данные или состав команды.</small>' : ''}</span></label>`).join('');
          openDrawer('Уточнить ожидаемый результат', `${domainNav('automation')}<h2>${esc(result.goal)}</h2><p class="aw-text">${esc(result.question)}</p><p class="aw-note">Задания ещё не запущены. Вы выбираете ожидаемый результат; роли и внутренние операции определит Координатор. Исполнение дочерних заданий потребует отдельного разрешения.</p><form class="aw-form" id="aw-domain-form">${choices}<p class="aw-form-error" id="aw-form-error" role="alert" hidden></p><div class="aw-actions"><button type="submit" class="btn primary">Подтвердить поручение</button><button type="button" class="btn" data-aw-domain="automation">Отмена</button></div></form>`);
          return;
        }
        if (state.domain === 'router' && state.action === 'preview') {
          mutationBusy = false;
          openRouterPreview(result.item || result, state.item);
          return;
        }
        if (state.domain === 'automation' && state.action === 'preview_commission') {
          mutationBusy = false;
          openCoordinatorPreview(result.item || result, state.item);
          return;
        }
        if (state.domain === 'publications' && state.action === 'prepare') {
          mutationBusy = false;
          openPublicationPreview(result.item || result, payload);
          return;
        }
        if (state.domain === 'publications' && state.action === 'publish') {
          if (result.published_to !== 'sf_social' || result.permanent !== true || !result.post || result.snapshot_sha256 !== payload.approved_snapshot_sha256) throw { status: 409 };
          actionForm = null; mutationBusy = false;
          const audience = { private: 'Только я', followers: 'Мои подписчики', network: 'Социальная сеть' }[payload.visibility];
          openDrawer('Публикация сохранена', `${domainNav('publications')}<section class="aw-publication-preview"><span class="aw-status aw-good">${result.deduplicated === true ? 'ПУБЛИКАЦИЯ УЖЕ СОХРАНЕНА' : 'ОПУБЛИКОВАНО В SF SOCIAL'}</span><h2>Проверенный снимок сохранён</h2><p class="aw-text">Видимость: ${esc(audience)}. Исходные личные данные не публиковались.</p><div class="aw-hash">SNAPSHOT SHA256 ${esc(result.snapshot_sha256)}</div><div class="aw-actions"><a class="btn primary" href="community.html">Открыть SF Social</a><button class="btn" data-aw-domain="publications">Вернуться к источникам</button></div></section>`);
          announce('Сервер подтвердил сохранение публикации в SF Social.');
          return;
        }
        actionForm = null;
        for (const secretName of ['api_key', 'credential']) { const keyInput = form.elements.namedItem(secretName); if (keyInput) keyInput.value = ''; }
        mutationBusy = false;
        await refresh();
        const resultItem = result.item || result.task || result;
        announce(resultItem.status === 'failed' || resultItem.status === 'external_blocked' ? 'Сервер записал неуспешный результат. Откройте историю и ограничения.' : 'Ответ сервера сохранён. Проверьте состояние и результат записи; принятие запроса не означает завершение задачи.');
        if (state.domain === 'external_agents' && state.action === 'task' && resultItem.started_task_id) await openTask(resultItem.started_task_id);
        else if (state.domain === 'router' && state.action === 'apply' && resultItem.started_task_id) await openTask(resultItem.started_task_id);
        else if (state.domain === 'automation' || state.action === 'seed_preview') await openDomain(state.domain);
        else if (state.action === 'open_chat') { await openDomain(state.domain); await openDomainItem(state.id); }
        else if (state.domain === 'tasks') await openTask(taskId(resultItem) || state.id);
        else {
          const target = state.domain === 'models' && ['test', 'task'].includes(state.action) ? 'model_tasks' : state.domain;
          await openDomain(target);
          const id = recordId(resultItem);
          if (id && id !== 'new') await openDomainItem(id);
        }
      } catch (error) { if (!disposed) { errorBox.textContent = domainError(error); errorBox.hidden = false; } }
      finally { mutationBusy = false; qsa('button, input, select, textarea', form).forEach(input => { input.disabled = false; }); }
    }
    function drawTask() {
      if (detail.result_text && !rows(detail.outcomes).length) detail = { ...detail,
        outcomes: [{ title: 'Ответ получен', detail: String(detail.result_text).slice(0, 500) }] };
      const task = detail.task || detail, art = rows(detail.artifacts);
      const source = sourceMeta(task), sourceKind = source.kind;
      const labels = { summary: 'Обзор', activity: 'Активность', evidence: 'Доказательства', agents: 'Участники', evaluations: 'Проверки', artifacts: 'Файлы', decisions: 'Решения', errors: 'Ошибки' };
      const svg = art.find(value => safeArtifactUrl(value.url) && (value.media_type || value.mime_type) === 'image/svg+xml');
      let body;
      if (detailTab === 'summary') body = `<div class="aw-inspector-summary"><h2 class="aw-inspector-title">${esc(taskTitle(task))}</h2><div class="aw-inline">${taskBadge(task)}${task.synthetic ? '<span class="aw-status aw-info">SYNTHETIC · локальный обработчик</span>' : ''}</div><dl class="aw-detail-grid"><div><dt>Текущий этап</dt><dd>${esc(task.result_label || stageName(task.stage))}</dd></div><div><dt>Координатор</dt><dd>${esc(name(task.lead))}</dd></div><div><dt>Класс задачи</dt><dd>${esc(taskClass(task))}</dd></div><div><dt>Измеренная стоимость</dt><dd>${esc(cost(task.cost_usd))}</dd></div><div><dt>Создана</dt><dd>${esc(date(task.created_at))}</dd></div><div><dt>Обновлена</dt><dd>${esc(date(task.updated_at))}</dd></div></dl>${progress(task)}${task.error_reason ? `<p class="aw-note"><strong>${esc(task.error_reason)}</strong><br>Задание не выполнялось и не стоит в очереди. Исходное сообщение сохранено; отправьте новый запрос, когда причина устранена.${task.error_code ? `<br><span class="aw-hash">${esc(task.error_code)}</span>` : ''}</p>` : ''}${rows(task.limitations).length ? `<ul class="aw-limitations">${rows(task.limitations).map(value => `<li>${esc(value)}</li>`).join('')}</ul>` : ''}${String(task.source_url || '').startsWith('/ui/') ? `<p class="aw-text"><a class="aw-link" href="${esc(task.source_url)}">Открыть исходный отчёт</a></p>` : ''}${task.result_label ? `<p class="aw-text">${esc(task.result_label)}</p>` : ''}${task.summary ? `<details class="aw-technical"><summary>Исходное описание</summary><pre>${esc(task.summary)}</pre></details>` : ''}</div><section class="aw-detail-section"><h3>Проверяемый результат</h3>${detailRows(rows(detail.outcomes), 'Результат ещё не зафиксирован.')}</section>${art.length ? `<section class="aw-detail-section"><h3>Последний артефакт</h3>${artifacts(art.slice(-1), sourceKind)}</section>` : ''}<p class="aw-note">Здесь отображаются наблюдаемые действия и результаты. Скрытая цепочка рассуждений модели не публикуется.</p>`;
      else if (detailTab === 'activity') body = timeline(rows(detail.activity), true);
      else if (detailTab === 'evidence') body = detailRows(rows(detail.contributions), 'Проверяемые вклады ещё не записаны.') + artifacts(art, sourceKind);
      else if (detailTab === 'agents') body = `<div class="aw-stack">${rows(task.participants).map(person => `<div class="aw-detail-row"><div class="aw-people">${avatar(person)}<div><strong>${esc(name(person))}</strong><p>${esc(role(person))}</p></div></div>${agentId(person) ? `<button class="aw-link-button" data-aw-agent="${esc(agentId(person))}">Профиль →</button>` : ''}</div>`).join('') || smallEmpty('Участники ещё не назначены.')}</div>`;
      else if (detailTab === 'evaluations') body = evaluations(rows(detail.evaluations).length ? detail.evaluations : detail.evaluation ? [detail.evaluation] : []);
      else if (detailTab === 'artifacts') body = artifacts(art, sourceKind);
      else if (detailTab === 'decisions') body = detailRows(rows(detail.decisions), 'У этой задачи нет записанных решений. Проверочный сценарий не имитирует разрешение владельца или Court.');
      else body = detailRows(rows(detail.errors), task.status === 'failed' ? 'Подробности ошибки не опубликованы.' : 'Зарегистрированных ошибок нет.');
      if (detailTab === 'summary' && detail.result_text) body += `<details class="aw-technical"><summary>Полный ответ и технические данные</summary><pre>${esc(detail.result_text)}</pre></details>`;
      if (detailTab === 'summary') body += intentPanel(detail.intent) + externalTaskProvenance(task);
      if (detailTab === 'evaluations') body += reputationPanel(detail.reputation);
      if (detailTab === 'summary') body += transportVerificationNote(task);
      if (detailTab === 'summary' && detail.model_selection) body += modelSelectionPanel(detail.model_selection);
      if (detailTab === 'summary' && task.source_kind === 'real_model_response') body += `<section class="aw-detail-section"><h3>Исполнитель и происхождение результата</h3><dl class="aw-detail-grid"><div><dt>Запрошенная модель</dt><dd>${esc(task.model || 'Не предоставлена')}</dd></div><div><dt>Model ID от провайдера</dt><dd>${esc(detail.actual_model || 'Не предоставлен')}</dd></div><div><dt>Провайдер</dt><dd>${detail.external_call === false ? esc((task.provider || 'провайдер') + ' — не вызывался') : esc(task.provider || 'Не предоставлен')}</dd></div>${detail.executor ? `<div><dt>Ответ получен от</dt><dd>${esc(detail.executor)}</dd></div>` : ''}</dl>${detail.external_call === false ? '<p class="aw-note">Ответ вычислен локально: внешнее обращение не выполнялось, поэтому этот результат ничего не говорит о доступности провайдера.</p>' : ''}<details class="aw-technical"><summary>Связанные записи</summary>${['intent_id', 'execution_id', 'contribution_id', 'outcome_id', 'evaluation_id', 'conversation_id', 'message_id'].filter(key => task[key]).map(key => `<div class="aw-hash">${esc(key.toUpperCase())} ${esc(task[key])}</div>`).join('')}</details></section>`;
      if (detailTab === 'summary' && task.source_kind === 'bounded_delegation_result' && detail.graph) {
        const review = detail.graph.human_review || {};
        const labels = { pending: 'Ожидается отдельная проверка', accepted: 'Принят', rejected: 'Отклонён', not_ready: 'Результат ещё не готов', stale: 'Источник изменился' };
        body += `<section class="aw-detail-section"><h3>Участники и обязательные проверки</h3><p class="aw-note">Проверка передачи фактов не означает приёмку всех вкладов или профессиональную оценку. Каждый исходный результат открывается отдельно.</p><div class="aw-stack">${rows(review.required_reviews).map((entry, index) => `<article class="aw-domain-card"><h4>${index ? 'Проверка ' + index : 'Исходная работа Координатора'}</h4><p>${esc(labels[entry.status] || 'Требует проверки источника')}</p><button class="btn" data-aw-task="${esc(entry.task_id)}">Открыть результат и проверку</button></article>`).join('')}</div><details class="aw-technical"><summary>План, роли и происхождение вкладов</summary><pre>${esc(publicJSON(detail.graph))}</pre></details></section>`;
      }
      if (task.model_id && task.conversation_id) body += `<div class="aw-actions"><button class="btn" data-aw-router-task="${esc(taskId(task))}">Выбор подключения · Router</button></div>`;
      body += handoffCard(task);
      const taskActions = rows(task.allowed_actions || task.actions).filter(action => ['cancel', 'retry', 'handoff', 'review_result'].includes(action)).map(action => `<button class="btn${action === 'cancel' ? ' aw-danger-action' : ''}" data-aw-task-action="${action}">${esc(actionLabel(action))}</button>`).join('');
      const controls = `<div class="aw-actions">${task.conversation_id ? `<button class="btn" data-aw-task-chat="${esc(taskId(task))}">Открыть в SF Chat</button>` : '<span class="aw-note">У исторической задачи нет связанного диалога.</span>'}${source.reportUrl ? `<a class="btn" href="${esc(source.reportUrl)}">Открыть исходный отчёт</a>` : ''}${svg ? `<button class="btn primary" data-aw-chart-chat="${esc(taskId(task))}">Снимок графика → SF Chat</button>` : ''}${taskActions}</div>`;
      const tabs = `<nav class="aw-tabs" role="tablist" aria-label="Разделы задачи">${Object.entries(labels).map(([key, label]) => `<button role="tab" aria-selected="${detailTab === key}" tabindex="${detailTab === key ? 0 : -1}" data-aw-detail-tab="${key}">${label}</button>`).join('')}</nav>`;
      openDrawer('Задача · ' + taskTitle(task), `${controls}${tabs}<div role="tabpanel">${body}</div><details class="aw-technical"><summary>Идентификаторы и состояние журнала</summary><div class="aw-hash">TASK ${esc(taskId(task))}${task.correlation_id ? `<br>CORRELATION ${esc(task.correlation_id)}` : ''}<br>LEDGER ${esc(task.ledger_status || task.status)}</div></details>`);
    }
    async function openTask(id) {
      if (!id) return;
      const request = ++detailGeneration;
      detailKind = 'task'; detailTab = 'summary'; detail = null; actionForm = null;
      const known = rows(overview?.tasks).concat(workRows).find(task => taskId(task) === String(id));
      openDrawer(known ? taskTitle(known) : 'Задача', loadingBlock('Загружаем задачу, результат и проверки…'));
      try {
        const result = await API.aiControlCenterTask(id, { signal });
        if (request !== detailGeneration || disposed) return;
        detail = result; drawTask();
      } catch (error) { if (error?.name !== 'AbortError' && request === detailGeneration && !disposed) openDrawer('Задача', readError(error)); }
    }
    function openProfile(id, selected) {
      const found = rows(overview.agents).find(value => agentId(value) === id);
      if (!found) { announce('Профиль не найден в текущем рабочем пространстве.', true); return; }
      ++detailGeneration;
      detailKind = 'agent'; profile = found; detailTab = selected || 'summary';
      const evaluation = evaluationMeta(found), tasks = rows(overview.tasks).filter(task => agentId(task.lead) === id || rows(task.participants).some(value => agentId(value) === id));
      const labels = { summary: 'Обзор', work: 'Задачи', rating: 'Рейтинг', persona: 'Персона' };
      let body = '';
      if (detailTab === 'work') body = tasks.length ? `<div class="aw-stack">${tasks.map(taskCard).join('')}</div>` : smallEmpty('В текущей выборке нет задач этого агента. Полный список — во вкладке «Задачи».');
      else if (detailTab === 'rating') body = `<div class="aw-metrics"><div class="aw-metric"><div class="aw-metric-label">Результат проверок</div><div class="aw-metric-value">${esc(evaluation.label)}</div><div class="aw-metric-note">${evaluation.insufficient ? 'NEW · недостаточно наблюдений' : 'Критерии конкретного класса задач'}</div></div><div class="aw-metric"><div class="aw-metric-label">Размер выборки</div><div class="aw-metric-value">${count(evaluation.sample)}</div><div class="aw-metric-note">Уверенность: ${esc(evaluation.confidence)}</div></div></div><dl class="aw-detail-grid"><div><dt>Класс</dt><dd>${esc(taskClass(found.evaluation))}</dd></div><div><dt>Окно наблюдений</dt><dd>${esc(found.evaluation?.window_label || 'Текущий локальный набор')}</dd></div><div><dt>Успешных проверок</dt><dd>${count(found.evaluation?.passed)}</dd></div><div><dt>Неуспешных проверок</dt><dd>${count(found.evaluation?.failed)}</dd></div></dl>${evaluation.insufficient && evaluation.observed != null ? note('Предварительное наблюдение: ' + pct(evaluation.observed) + '. Этого недостаточно для устойчивой оценки.') : ''}${note(found.synthetic === true ? 'Источник: synthetic-обработчик, не реальная модель.' : 'Источник: фактические ответы указанной модели и автоматическая проверка конкретного класса. Три успешные арифметические проверки не означают 100% профессионального качества. Приёмка владельцем, соответствие отчёта/PNG и профессиональная оценка — разные наблюдения.')}`;
      else if (detailTab === 'persona') body = `<dl class="aw-detail-grid"><div><dt>Persona</dt><dd>${esc(name(found))}</dd></div><div><dt>Agent Role</dt><dd>${esc(role(found))}</dd></div><div><dt>Голос</dt><dd>${esc(found.voice_label || 'Настройки существующего профиля')}</dd></div><div><dt>Model</dt><dd>${esc(found.model?.name || found.model || 'Назначается отдельно, не является Persona')}</dd></div></dl>${note('Смена модели не переименовывает агента, не меняет его историю и не выдаёт новые полномочия. Свои Persona создаются и редактируются в текущем рабочем пространстве.')}<div class="aw-actions">${/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(found.persona_id || agentId(found)) ? `<button class="btn primary" data-aw-persona-open="${esc(found.persona_id || agentId(found))}">Лицо, голос и описание</button>` : ''}<button class="btn" data-aw-domain="personas">Управление Persona</button><button class="btn" data-aw-domain="models">Мои подключения</button></div>`;
      else body = `<div class="aw-inspector-summary"><h3>Роль и специализация</h3><p class="aw-text">${esc(found.description || found.specialization || role(found))}</p><dl class="aw-detail-grid"><div><dt>Текущая работа</dt><dd>${esc(found.current_task?.title || found.current_task_title || 'Нет активной задачи')}</dd></div><div><dt>Результат проверок</dt><dd>${esc(evaluation.label)} · n = ${count(evaluation.sample)}</dd></div><div><dt>Уверенность</dt><dd>${esc(evaluation.confidence)}</dd></div><div><dt>Контур</dt><dd>${found.synthetic ? 'Synthetic · детерминированные задачи' : 'Текущее рабочее пространство'}</dd></div></dl></div><section class="aw-detail-section"><h3>Последняя работа</h3>${tasks.length ? `<div class="aw-stack">${tasks.slice(0, 3).map(taskCard).join('')}</div>` : smallEmpty('Задач в текущей выборке нет.')}</section>`;
      if (detailTab === 'rating' && found.synthetic === false) body += panel('Реальные задания · отдельно от тестов модели', applicationTable([found]));
      openDrawer('Профиль · ' + name(found), `<div class="aw-profile-head">${avatar(found, 'lg')}<div><h2>${esc(name(found))}</h2><p class="aw-agent-role">${esc(role(found))}</p>${agentState(found)}</div></div><nav class="aw-tabs" role="tablist" aria-label="Профиль агента">${Object.entries(labels).map(([key, label]) => `<button role="tab" aria-selected="${detailTab === key}" tabindex="${detailTab === key ? 0 : -1}" data-aw-profile-tab="${key}">${label}</button>`).join('')}</nav>${body}`);
    }
    async function taskChat(id, screenshot, button) {
      button.disabled = true;
      try {
        const body = {};
        if (screenshot) {
          const chart = rows(detail?.artifacts).find(value => (value.media_type || value.mime_type) === 'image/svg+xml' && safeArtifactUrl(value.url));
          body.image_data_url = await captureChart(chart);
        }
        const result = await API.aiControlCenterTaskChat(id, body);
        if (!result?.conversation_id) throw new Error('Диалог SF Chat не создан.');
        UI.closeDrawer();
        await UI.openSFChat({ conversationId: result.conversation_id, conversationType: 'ai' });
        announce(screenshot ? 'Настоящий PNG-снимок графика сохранён и отправлен в SF Chat.' : 'Проверяемый результат задачи открыт в SF Chat.');
      } catch (error) { announce(error?.message || 'Не удалось открыть результат в SF Chat.', true); }
      finally { button.disabled = false; }
    }
    // A question from the list opens the chat with the Manager: the task's own
    // dialogue when the server can build one, otherwise the Manager's chat with
    // a short brief typed in for the owner to finish and send.
    async function askDeputy(id, button) {
      const task = rows(overview?.tasks).find(row => taskId(row) === id);
      if (button) button.disabled = true;
      try {
        const result = await API.aiControlCenterTaskChat(id, {}).catch(() => null);
        if (result?.conversation_id) { await UI.openSFChat({ conversationId: result.conversation_id, conversationType: 'ai' }); return; }
        await UI.openSFChat({ conversationType: 'ai' });
        const input = document.querySelector?.('#orch-text');
        if (input && !input.value && task) input.value = `По задаче «${taskTitle(task)}» (${task.display_status_label || phaseLabel(task)})${task.reason ? ': ' + task.reason : ''}. `;
      } finally { if (button) button.disabled = false; }
    }
    async function runDemo() {
      if (!canRunDemo(overview) || demoBusy) return;
      demoBusy = true; domainCache.clear(); renderHeader();
      if (!demoKey) demoKey = root.crypto.randomUUID();
      announce('Выполняются локальные задачи на тестовых данных. Это не вызов внешних моделей и не торговое действие.');
      try {
        await API.aiControlCenterDemoRun({ idempotency_key: demoKey });
        demoKey = null;
        await refresh();
        announce('Проверочный запуск записан. Результаты — во вкладке «Задачи», измеренные оценки — в «Команде».');
      } catch (error) { announce((error?.message || 'Не удалось завершить запуск.') + ' Повторная попытка использует тот же ключ и не создаёт дубликат.', true); }
      finally { demoBusy = false; renderHeader(); }
    }
    function restoreFocus() {
      const target = returnFocus;
      returnFocus = null;
      if (target && target.isConnected && typeof target.focus === 'function' && target.getClientRects().length) { target.focus(); return; }
      const tabs = qsa('[data-aw-tab]', shell);
      (tabs.find(button => button.getAttribute('aria-selected') === 'true') || tabs[0])?.focus();
    }
    function click(event) {
      if (personaAudio?.activePersona() && (!currentDrawer?.querySelector('.aw-persona-presentation') || !currentDrawer.contains(event.target))) stopPersonaAudio();
      if (currentDrawer?.querySelector('.aw-inspector') && event.target.closest('.drawer-back, [data-close-drawer]')) { stopPersonaAudio(); ++detailGeneration; actionForm = null; restoreFocus(); return; }
      if (agentPopOpen() && !event.target.closest?.('#aw-agent-pop') && !event.target.closest?.('[data-aw-agent-card]')) closeAgentCard();
      // A model row is a table row, not a button; the whole row opens its card.
      const staffLine = event.target.closest?.('tr[data-aw-agent-card]');
      if (staffLine && shell.contains(staffLine)) { openAgentCard(staffLine.dataset.awAgentCard, staffLine); return; }
      const labRow = event.target.closest?.('[data-aw-lab-model]');
      if (labRow && shell.contains(labRow)) { openLabModel(labRow.dataset.awLabModel); return; }
      const graphRecord = event.target.closest?.('[data-aw-graph-record]');
      if (graphRecord && shell.contains(graphRecord) && graphRecord.dataset.awGraphRecord) { openDomain('memory').then(() => openDomainItem(graphRecord.dataset.awGraphRecord)); return; }
      const shareSwitch = event.target.closest?.('input[data-aw-share]');
      if (shareSwitch && currentDrawer?.contains(shareSwitch)) { void toggleShare(shareSwitch); return; }
      const registryShare = event.target.closest?.('input[data-aw-registry-share]');
      if (registryShare && currentDrawer?.contains(registryShare)) { void shareRegistry(registryShare); return; }
      const target = event.target.closest('button, a');
      if (!target) return;
      if (currentDrawer?.contains(target) && target.dataset.awRegistryTest) { void testModelInline(target, true); return; }
      if (currentDrawer?.contains(target) && target.dataset.awInlineTest) { void testModelInline(target); return; }
      if (currentDrawer?.contains(target) && target.dataset.awCardModel) {
        const id = target.dataset.awCardModel, action = target.dataset.awCardAction;
        void openDomain('models').then(() => openDomainItem(id)).then(() => openDomainAction(action, id)); return;
      }
      const inside = shell.contains(target) || (currentDrawer && currentDrawer.contains(target) && target.closest('.aw-inspector'));
      if (!inside) return;
      if (target.id === 'aw-log-toggle') { toggleLog(); return; }
      if (target.hasAttribute('data-aw-pop-close')) { closeAgentCard(); return; }
      if (target.dataset.awAgentCard) { openAgentCard(target.dataset.awAgentCard, target); return; }
      if (target.dataset.awHire) { openHire(target.dataset.awHire, target); return; }
      if (target.hasAttribute('data-aw-connect-model')) { stopPersonaAudio(); void openConnect(); return; }
      if (target.dataset.awRename) { openRename(target.dataset.awRename, target); return; }
      if (target.hasAttribute('data-aw-auto-team')) { void autoTeam(target); return; }
      if (target.hasAttribute('data-aw-new-research')) { openNewResearch(); return; }
      if (target.hasAttribute('data-aw-goal')) { openGoal(); return; }
      if (target.hasAttribute('data-aw-legacy')) { void openLegacy(target.getAttribute('data-aw-legacy')); return; }
      if (target.hasAttribute('data-aw-duty-decide')) { void dutyDecide(target.getAttribute('data-aw-duty-decide'), target.getAttribute('data-aw-decision'), target); return; }
      if (target.hasAttribute('data-aw-duty-answer')) { void dutyAnswer(target.getAttribute('data-aw-duty-answer')); return; }
      if (target.hasAttribute('data-aw-duty')) { void dutyControl(target.getAttribute('data-aw-duty'), target); return; }
      if (target.dataset.awResearch) { researchPick = Number(target.dataset.awResearch) || 0; renderResearch(); return; }
      if (target.hasAttribute('data-aw-open-log')) { toggleLog(true); qs('#aw-log-toggle')?.focus?.(); return; }
      if (target.hasAttribute('data-aw-graph-toggle')) { graphOpen = !graphOpen; renderMemory(); return; }
      if (target.dataset.awAsk) { askDeputy(target.dataset.awAsk, target); return; }
      if (target.hasAttribute('data-aw-show-tests')) { showTests = !showTests; renderWork(); return; }
      if (target.tagName === 'A' || target.dataset.awTaskChat || target.dataset.awFollowupChat || target.dataset.awChartChat || target.hasAttribute('data-aw-real-chat')) stopPersonaAudio();
      // A control may carry both: open the tab already narrowed to that filter.
      if (target.dataset.awTab) { if (target.dataset.awFilter) filter = target.dataset.awFilter; selectTab(target.dataset.awTab, true); }
      else if (target.hasAttribute('data-aw-external-test-fill')) {
        const test = domainState?.key === 'external_agents' && domainState?.data.test_connection;
        const form = qs('#aw-domain-form', currentDrawer);
        if (test && form && actionForm?.action === 'create') {
          for (const [key, value] of Object.entries({ display_name: 'Development · внешний агент', protocol: 'a2a-0.3-jsonrpc-bounded', endpoint: test.endpoint, credential: test.credential, capability: 'stratforge.json_arithmetic.v1' })) { const input = form.elements.namedItem(key); if (input) input.value = value || ''; }
        }
      }
      else if (target.dataset.awModelGroup) openModelGroup(target.dataset.awModelGroup);
      else if (target.dataset.awDomainOpen) openDomain(target.dataset.awDomainOpen).then(() => openDomainItem(target.dataset.awEntity));
      else if (target.dataset.awDomain) openDomain(target.dataset.awDomain);
      else if (target.dataset.awDomainItem) openDomainItem(target.dataset.awDomainItem);
      else if (target.dataset.awRouterTask) openRouterTask(target.dataset.awRouterTask);
      else if (target.dataset.awDomainAction) openDomainAction(target.dataset.awDomainAction, target.dataset.awEntity || 'new');
      else if (target.dataset.awPersonaOpen) openDomain('personas').then(() => openDomainItem(target.dataset.awPersonaOpen));
      else if (target.dataset.awPersonaSpeak) playPersonaDescription(target.dataset.awPersonaSpeak);
      else if (target.hasAttribute('data-aw-persona-stop')) stopPersonaAudio();
      else if (target.dataset.awProcessPropose) openProcessSuggestion(target.dataset.awProcessPropose);
      else if (target.dataset.awScheduleSource) openScheduleSource(target.dataset.awScheduleSource);
      else if (target.dataset.awCapability) changeAutomationCapability(target.dataset.awCapability, target.dataset.awCapabilityUser);
      else if (target.hasAttribute('data-aw-domain-refresh')) openDomain(domainState?.key);
      else if (target.hasAttribute('data-aw-domain-more')) openDomain(domainState?.key, true);
      else if (target.dataset.awModelTask) { openDomain('model_tasks').then(() => openDomainItem(target.dataset.awModelTask)); }
      else if (target.dataset.awTaskAction) { const task = detail?.task || detail; if (task) openDomainAction(target.dataset.awTaskAction, taskId(task), task); }
      else if (target.dataset.awTask) openTask(target.dataset.awTask);
      else if (target.dataset.awAgent) openProfile(target.dataset.awAgent);
      else if (target.dataset.awDetailTab) { detailTab = target.dataset.awDetailTab; drawTask(); qs('[data-aw-detail-tab][aria-selected="true"]', currentDrawer)?.focus(); }
      else if (target.dataset.awProfileTab) { openProfile(agentId(profile), target.dataset.awProfileTab); qs('[data-aw-profile-tab][aria-selected="true"]', currentDrawer)?.focus(); }
      else if (target.dataset.awTaskChat) taskChat(target.dataset.awTaskChat, false, target);
      else if (target.dataset.awFollowupChat && /^AW-FU-[0-9a-f]{28}$/.test(target.dataset.awFollowupChat)) { UI.closeDrawer(); UI.openSFChat({ conversationId: target.dataset.awFollowupChat, conversationType: 'ai' }); }
      else if (target.dataset.awChartChat) taskChat(target.dataset.awChartChat, true, target);
      else if (target.hasAttribute('data-aw-real-chat')) UI.openSFChat({ conversationType: 'ai' });
      else if (target.dataset.awFilter) { filter = target.dataset.awFilter; loadTab(); }
      else if (target.hasAttribute('data-aw-retry')) refresh();
      else if (target.id === 'aw-load-more') loadTab(true);
    }
    function keyboard(event) {
      if (event.key === 'Enter' && event.target?.dataset?.awLabModel) { openLabModel(event.target.dataset.awLabModel); return; }
      if (event.key === 'Escape' && agentPopOpen()) { closeAgentCard(); return; }
      const tabs = event.target.closest('.aw-tabs');
      if (tabs && ['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key) && (shell.contains(tabs) || tabs.closest('.aw-inspector'))) {
        const buttons = qsa('[role="tab"]:not([hidden])', tabs), index = buttons.indexOf(event.target);
        if (index < 0) return;
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
        event.preventDefault(); buttons[next].focus(); buttons[next].click(); return;
      }
      if (!currentDrawer?.querySelector('.aw-inspector')) return;
      if (event.key === 'Escape') { stopPersonaAudio(); ++detailGeneration; actionForm = null; UI.closeDrawer(); restoreFocus(); }
      if (!currentDrawer.classList.contains('open')) return;
      if (event.key === 'Tab') {
        const focusable = qsa('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]', currentDrawer).filter(value => !value.hidden && value.getClientRects().length);
        if (!focusable.length) { event.preventDefault(); currentDrawer.focus(); return; }
        if (event.shiftKey && (document.activeElement === focusable[0] || document.activeElement === currentDrawer)) { event.preventDefault(); focusable[focusable.length - 1].focus(); }
        else if (!event.shiftKey && document.activeElement === focusable[focusable.length - 1]) { event.preventDefault(); focusable[0].focus(); }
      }
    }
    document.addEventListener('click', click);
    const hireSubmit = event => {
      if (event.target?.id === 'aw-hire-form') { event.preventDefault(); void hire(event.target); }
      if (event.target?.id === 'aw-rename-form') { event.preventDefault(); void rename(event.target); }
    };
    document.addEventListener('submit', hireSubmit);
    UI.onLeave(() => document.removeEventListener('submit', hireSubmit));
    document.addEventListener('keydown', keyboard);
    document.addEventListener('submit', submitDomain);
    document.addEventListener('visibilitychange', visibilityAudio);
    root.addEventListener?.('pagehide', stopPersonaAudio);
    root.addEventListener?.('hashchange', stopPersonaAudio);
    root.addEventListener?.('popstate', stopPersonaAudio);
    shell.addEventListener('input', event => {
      if (event.target.id !== 'aw-task-search') return;
      query = event.target.value;
      root.clearTimeout(debounceTimer);
      debounceTimer = root.setTimeout(async () => {
        const position = event.target.selectionStart;
        await loadTab();
        const input = qs('#aw-task-search');
        if (input && tab === 'work') { input.focus(); try { input.setSelectionRange(position, position); } catch (ignore) { /* search input support varies */ } }
      }, 300);
    });
    qs('#aw-refresh').addEventListener('click', refresh);
    qs('#aw-run-demo').addEventListener('click', runDemo);
    qs('#aw-open-chat').addEventListener('click', () => { stopPersonaAudio(); UI.openSFChat({ conversationType: 'ai' }); });
    UI.onLeave(() => { if (personaAudio) personaAudio.dispose(); disposed = true; actionForm = null; domainState = null; ++generation; ++overviewGeneration; ++detailGeneration; root.clearTimeout(debounceTimer); document.removeEventListener('click', click); document.removeEventListener('keydown', keyboard); document.removeEventListener('submit', submitDomain); document.removeEventListener('visibilitychange', visibilityAudio); root.removeEventListener?.('pagehide', stopPersonaAudio); root.removeEventListener?.('hashchange', stopPersonaAudio); root.removeEventListener?.('popstate', stopPersonaAudio); });
    const locationParams = new URLSearchParams(root.location.hash.replace(/^#/, ''));
    tab = TABS.includes(locationParams.get('tab')) ? locationParams.get('tab') : 'overview';
    await refresh();
    let chatRouteGeneration = 0, activeChatRoute = null;
    async function applyChatRoute(params) {
      const conversation = params.get('chat_conversation'), message = params.get('chat_message');
      if (disposed || mutationBusy || !overview?.enabled || params.get('domain') !== 'automation' || !conversation || !message) return false;
      const key = JSON.stringify([conversation, message]);
      if (activeChatRoute === key) return true;
      activeChatRoute = key;
      const revision = ++chatRouteGeneration;
      UI.closeOrchestrator?.();
      const expectedDetail = detailGeneration + 1;
      try {
        await openDomain('automation');
        if (disposed || revision !== chatRouteGeneration || detailGeneration !== expectedDetail) return true;
        const seed = await API.aiControlCenterDomainAction('automation', 'new', 'chat_seed', { payload: { conversation_id: conversation, source_message_id: message }, idempotency_key: root.crypto.randomUUID() });
        if (!disposed && revision === chatRouteGeneration && detailGeneration === expectedDetail) await openDomainAction('commission', 'new', null, seed);
      } catch (error) { if (!disposed && revision === chatRouteGeneration && detailGeneration === expectedDetail) openDrawer('Поручение из SF Chat', readError(error)); }
      finally { if (revision === chatRouteGeneration) activeChatRoute = null; }
      return true;
    }
    function followChatRoute() {
      void applyChatRoute(new URLSearchParams(root.location.hash.replace(/^#/, '')));
    }
    root.addEventListener?.('hashchange', followChatRoute);
    root.addEventListener?.('aw-chat-navigate', followChatRoute);
    UI.onLeave(() => { ++chatRouteGeneration; root.removeEventListener?.('hashchange', followChatRoute); root.removeEventListener?.('aw-chat-navigate', followChatRoute); });
    const linkedTask = locationParams.get('task') || new URLSearchParams(root.location.search).get('task');
    if (linkedTask && overview?.enabled) await openTask(linkedTask);
    else if (knownDomain(locationParams.get('domain')) && overview?.enabled) {
      if (!await applyChatRoute(locationParams)) {
      await openDomain(locationParams.get('domain'));
      const entity = locationParams.get('entity');
      if (/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(entity || '')) await openDomainItem(entity);
      }
    }
    // Reuse Aurora's existing single-flight, onLeave-cleaned polling lifecycle.
    // Reading never enqueues, accepts, retries or changes a permission/flag.
    UI.poll?.(() => refresh({ background: true }), 30000);
  });
})(typeof window !== 'undefined' ? window : globalThis);
