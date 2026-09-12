/* Agent World presentation. All authority, scope, execution and data stay server-side. */
(function (root) {
  'use strict';
  const TABS = ['overview', 'work', 'agents'];
  const DOMAINS = Object.freeze({
    personas: { title: 'Persona', description: 'Личность и стиль агента не заменяют его роль, модель или права.', create: 'Создать персону' },
    decisions: { title: 'Решения / Court', description: 'Предложение, доказательства и независимые проверки. Вердикт не выдаёт новых прав и не исполняет сделок.', create: 'Новое решение' },
    memory: { title: 'Память', description: 'Записи с источником, назначением и сроком хранения. Только подтверждённые записи можно продвигать.', create: 'Добавить запись' },
    projects: { title: 'Strategy Projects', description: 'Проекты стратегий, история версий и параметры. Исполнение остаётся в существующем бэктестировании.', create: 'Создать проект' },
    routines: { title: 'Рутины', description: 'Предложения повторяющейся работы. Принятие предложения не включает фоновое исполнение.', create: 'Предложить рутину' },
    calendar: { title: 'Календарь', description: 'Согласованные события рабочего пространства. Время вводится локально и сохраняется в UTC.', create: 'Добавить событие' },
    publications: { title: 'Публикация в SF Social', description: 'Только проверенный результат или решение: сначала снимок для просмотра, затем отдельное подтверждение публикации. Личная память и сырые ответы не публикуются.', create: 'Подготовить публикацию' },
    models: { title: 'Модели и подключения', description: 'Подключения LLM API. Persona, учётная запись провайдера и модель — отдельные сущности.', create: 'Подключить модель' },
    external_agents: { title: 'Внешние агенты', description: 'Самостоятельное A2A-подключение, не модель и не Persona. Возможности подтверждает сервер; MCP-инструмент не является агентом.', create: 'Добавить внешнего агента' },
    model_tasks: { title: 'История моделей', description: 'Фактические ответы и независимые проверки. Неизвестная стоимость не равна нулевой.', create: '' },
    tasks: { title: 'Действия задачи', description: 'Изменение выполняет сервер после повторной проверки прав и состояния.', create: '' },
    experiments: { title: 'Эксперименты', description: 'Одно проверяемое задание для 2–3 моделей. Сравнение строится по фактическим ответам, не по самооценке.', create: 'Сравнить модели' },
    automation: { title: 'Автоматизация', description: 'Разрешение на автоматизацию, согласие на конкретную рутину и бюджет — три разных условия. Включение расписания не выдаёт прав и не поднимает лимиты.', create: '' },
    router: { title: 'Выбор подключения · Router', description: 'Кандидаты и источник выбора для конкретной задачи. Предпросмотр ничего не запускает; повторное задание требует отдельного разрешения.', create: '' },
    system: { title: 'Система', description: 'Доступность, ограничения и состояние текущего рабочего пространства. Чтение не меняет флаги или бюджет.', create: '' },
  });
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
  const AVATAR_LABELS = Object.freeze({ vitek: 'Виктор', manager: 'Управляющий', marina: 'Марина', tolik: 'Толик', nikita: 'Никита', ivan: 'Иван' });
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
      field('main_assistant', 'Главный помощник', 'select', { optionalIfMissing: true, boolean: true, default: 'false', options: [['false', 'Нет — выбор в SF Chat или обращение по имени'], ['true', 'Да — когда другой помощник не выбран']], hint: 'Один главный помощник в вашем рабочем пространстве. Чтобы сменить его, сначала явно снимите этот выбор у прежней Persona и сохраните, затем назначьте новую. Приостановленный помощник не заменяется автоматически.' }),
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
    const taskRow = row => `<div class="aw-text">${badge(row.status)} <span class="aw-hash">${esc(String(row.id).slice(0, 8))}</span>`
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
      + `<div><dt>Завершено задач</dt><dd>${count(stat.tasks_completed)}</dd></div>`
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
          last_error: code, performance: item.performance, statistics: stat }))}</pre></details>`
      + `</section>`;
  }
  function modelProtocolCard(model) {
    const caps = model?.capabilities;
    const known = model?.protocol === 'chat_completions_v1' && caps?.text === true
      && ['remote_tools', 'remote_tasks', 'mcp', 'a2a', 'artifacts'].every(key => caps[key] === false);
    if (!known) return '<p class="aw-note">Протокол и возможности подключения ещё не подтверждены сервером. Название «внешний агент» само по себе не означает доступ к удалённым действиям.</p>';
    return '<section class="aw-detail-section"><strong>Текстовый HTTPS-исполнитель</strong><p class="aw-note">Один ограниченный текстовый ответ через совместимый chat-completions endpoint. Удалённые инструменты, отдельные удалённые задачи, MCP, A2A и артефакты этим подключением не поддерживаются. Права и бюджет остаются у приложения.</p><details class="aw-technical"><summary>Протокол и возможности, полученные от сервера</summary><pre>' + esc(publicJSON({protocol: model.protocol, capabilities: caps})) + '</pre></details></section>';
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
      external_blocked: 'Необходимое внешнее подключение недоступно. Действие не считается выполненным.',
      process_sources_changed: 'Результаты или их проверка изменились. Обновите предложения и проверьте новые источники; старая история сохранена.',
      process_suggestion_stale: 'Предложение уже изменилось. Откройте актуальную запись перед решением.',
      process_scan_incomplete: 'Полный набор наблюдений сейчас недоступен. Предложение не создано; повторите после обновления раздела.',
      persona_aliases_invalid: 'Укажите до пяти обращений: буквы, цифры, пробел, дефис или подчёркивание; до 80 символов каждое.',
      persona_aliases_ambiguous: 'Обращения должны различаться, в том числе без учёта регистра.',
      persona_alias_repeats_name: 'Обращение повторяет имя Persona. Имя уже можно использовать без дополнительного alias.',
      persona_alias_already_assigned: 'Это обращение уже относится к другой вашей Persona. Измените его; существующие имена и история сохранены.',
      persona_main_already_assigned: 'Главный помощник уже назначен. Сначала явно снимите этот выбор у прежней Persona и сохраните, затем назначьте новую.',
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
      ['Главный помощник', persona.main_assistant === true ? 'Да · когда другая Persona не выбрана' : 'Нет'],
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
      + `<div><dt>Рабочее пространство</dt><dd>${esc((intent.scope || {}).workspace_id || '')}</dd></div>`
      + `<div><dt>Требуемое доказательство</dt><dd>${esc(evidence.rubric_label || evidence.rubric_key || 'не указано')}</dd></div>`
      + `</dl>`
      + `<p class="aw-field-hint">Проверяет: ${esc(evidence.verified_by || 'не указано')}. Приёмка человеком — отдельное решение и не является оценкой качества.</p>`
      + (request ? `<details class="aw-technical"><summary>Что именно было запрошено</summary><pre>${esc(request)}</pre></details>` : '')
      + `<p class="aw-field-hint">Поручение не редактируется после создания задачи: его значением связаны запрос, ответ и проверка. Пока работа не началась, поручение можно остановить — «Отменить задачу». Нужны другие условия — отправьте новый запрос; прежнее поручение и его история сохраняются.</p>`
      + `</section>`;
  }
  if (typeof module === 'object' && module.exports) { module.exports = { esc, number, count, pct, date, statusMeta, badge, rows, items, taskMatches, taskState, taskTitle, taskClass, taskBadge, evaluationMeta, phaseOf, phaseLabel, rubricLabel, stageName, machineKey, availabilityMeta, occupancyMeta, readinessGrid, technicalSplit, technicalDetails, AVATAR_KEYS, applicationRows, applicationTable, safeArtifactUrl, sourceMeta, overviewOutcomes, realChatCommands, canRunDemo, flagRows, captureChart, knownDomain, allowedDomainActions, domainFormFields, domainPayload, actionLabel, domainError, publicJSON, externalAgentCard, handoffCard, followupCard, modelConnectionGuide, modelProtocolCard, personaVoiceFields, personaReadText, personaCanSpeak, personaSpeechEnvelope, personaAudioStatus, personaPresentationCard, processCandidatePayload, processCandidateCard, processIntelligencePanel, reputationPanel, intentPanel, validCoordinatorPreview, coordinatorApproval, connectionLabel }; return; }

  root.UI.ready(async function () {
    const UI = root.UI, API = root.API.http;
    const qs = (selector, parent) => (parent || document).querySelector(selector);
    const qsa = (selector, parent) => Array.from((parent || document).querySelectorAll(selector));
    const shell = qs('#aw-center');
    if (!shell) return;
    let overview = null, tab = 'overview', filter = 'all', query = '', workRows = [], nextCursor = null;
    let detail = null, detailTab = 'summary', detailKind = '', profile = null, currentDrawer = null, returnFocus = null;
    let domainState = null, actionForm = null, mutationBusy = false;
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
    const taskLink = (id, label) => id ? `<button class="aw-link-button" data-aw-task="${esc(id)}">${esc(label || 'Открыть задачу')} →</button>` : '';
    const avatar = (value, size) => {
      const person = actor(value), key = String(person.avatar_key || '').toLowerCase();
      const image = AVATAR_KEYS.includes(key) && UI.agentAvatarHtml ? UI.agentAvatarHtml(key, { size: 'sm' }) : esc(name(person).slice(0, 1).toLocaleUpperCase('ru-RU'));
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
    function alertCard(item) {
      const action = item.action_hint || '', reason = item.reason || item.detail || '';
      const when = item.since || item.updated_at || item.created_at;
      return `<div class="aw-alert"><div>${item.display_status ? taskBadge(item) : badge(item.severity || item.status || 'warning')}</div><div><strong>${esc(item.display_title || item.title || item.summary)}</strong>${reason ? `<p>${esc(reason)}</p>` : ''}${action ? `<p class="aw-alert-action">${esc(action)}</p>` : ''}<div class="aw-alert-foot">${when ? `<time datetime="${esc(when)}">${esc(date(when))}</time>` : ''}${taskLink(item.task_id || item.id)}</div></div></div>`;
    }
    function agentMini(agent) {
      const evaluation = evaluationMeta(agent);
      return `<button class="aw-agent-mini" data-aw-agent="${esc(agentId(agent))}" title="${esc(name(agent))}: ${esc(evaluation.label)}, выборка ${count(evaluation.sample)}, уверенность ${esc(evaluation.confidence)}"><span class="aw-agent-mini-top">${avatar(agent)}<span class="aw-agent-identity"><span class="aw-agent-name">${esc(name(agent))}</span><span class="aw-agent-role">${esc(role(agent))}</span></span><span class="aw-rating-mini"><strong>${count(evaluation.sample)} наблюдений</strong><small>${esc(evaluation.classLabel)}</small><small>${esc(evaluation.diagnostic ? 'Диагностика, не квалификация' : 'См. класс и источник')}</small></span></span><span class="aw-agent-mini-foot">${agentState(agent)}<span>${esc(agent.current_task?.title || agent.current_task_title || 'Нет активной задачи')}</span></span></button>`;
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
    function foundationCard() {
      const limitations = rows(overview.limitations).map(value => typeof value === 'string' ? value : value.summary || value.message || value.description).filter(Boolean);
      const flags = capability('can_view_system') ? flagRows(overview.flags) : [];
      const more = limitations.length || flags.length ? `<details class="aw-foundation-details"><summary>Ограничения и доступность</summary>${limitations.length ? `<ul>${limitations.map(value => `<li>${esc(value)}</li>`).join('')}</ul>` : ''}${flags.length ? `<div class="aw-flag-list">${flags.map(flag => `<div class="aw-flag"><code>${esc(flag.name)}</code>${badge(flag.enabled ? 'active' : 'disabled')}</div>`).join('')}</div>` : ''}</details>` : '';
      return panel('Рабочее пространство', `<div class="aw-foundation"><span class="aw-status aw-neutral">IN DEVELOPMENT · локальная проверка</span><p>Решения, память, модели и проекты открываются в панели инструментов выше — на этой же странице.</p><div class="aw-actions"><button class="aw-link-button" data-aw-domain="personas">Управление Persona →</button><button class="aw-link-button" data-aw-domain="models">Мои подключения →</button><button class="aw-link-button" data-aw-domain="system">Состояние системы →</button></div>${more}</div>`);
    }
    function realWorkHint() {
      const commands = realChatCommands(overview);
      if (!commands.length) return '';
      return panel('Реальные задачи через SF Chat', `<div class="aw-chat-hint"><p>Отправьте команду в существующий чат. Примеры: замените стратегию, инструмент и период на нужные.</p>${commands.map(command => `<div class="aw-command-example"><strong>${esc(command.title)}</strong><code>${esc(command.text)}</code></div>`).join('')}<p>Даты бэктеста — UTC; конечная дата не включается. Это исследование, не торговое исполнение. Снимок сохраняет текущий вид рабочего стола.</p></div>`, '<button class="aw-link-button" data-aw-real-chat>Открыть чат →</button>');
    }
    function renderOverview() {
      const tasks = rows(overview.tasks), agents = rows(overview.agents), stats = overview.stats || {};
      const active = tasks.filter(task => task.is_active === true || task.is_active == null && taskMatches(task, 'active', ''));
      const awaitingDecision = tasks.filter(task => phaseOf(task) === 'awaiting_decision');
      const awaitingReview = tasks.filter(task => phaseOf(task) === 'awaiting_review');
      const group = active.length ? active : awaitingDecision.length ? awaitingDecision
        : awaitingReview.length ? awaitingReview : tasks;
      const heading = active.length ? 'Сейчас в работе'
        : awaitingDecision.length ? 'Ожидают вашего решения'
        : awaitingReview.length ? 'Ожидают проверки'
        : 'Последняя работа';
      const shown = group.slice(0, 3), outcomes = overviewOutcomes(overview).slice(0, 3);
      const attentionKnown = Array.isArray(overview.attention), alerts = rows(overview.attention).filter(item => !['info', 'healthy'].includes(item.severity || item.status));
      const alertsBody = alerts.length ? `<div class="aw-stack">${alerts.slice(0, 3).map(alertCard).join('')}</div>${alerts.length > 3 ? `<button class="aw-link-button" data-aw-tab="work" data-aw-filter="attention">Показать все (${count(alerts.length)}) →</button>` : ''}` : attentionKnown && number(stats.attention) === 0 ? `<div class="aw-attention-clear">${badge('healthy')}<span>Сервер не сообщает об ошибках или ожидающих подтверждениях.</span></div>` : smallEmpty('Сводка подтверждений пока не опубликована. Отсутствие данных не означает, что все проверки пройдены.');
      const metrics = [
        ['В работе', stats.active_tasks, 'Очередь, выполнение и ожидание результата'], ['Результаты', stats.results_received, 'Получены, но не обязательно приняты'],
        ['Ждут проверки', stats.awaiting_review, 'Ответ есть, проверка не пройдена'], ['Проверены вами', stats.completed_tasks, 'Принятые результаты'],
        ['Ошибки', stats.failed, 'История сохраняется'], ['Требуют внимания', stats.attention, 'Проверки, ошибки, отклонения и блокировки'],
      ].map(([label, value, caption]) => `<div class="aw-metric"><div class="aw-metric-label">${esc(label)}</div><div class="aw-metric-value">${count(value)}</div><div class="aw-metric-note">${esc(caption)}</div></div>`).join('');
      content.innerHTML = `<div class="aw-rollup" aria-label="Сводка текущего рабочего пространства">${metrics}</div><div class="aw-overview"><div class="aw-column aw-column-work">${panel(heading, shown.length ? `<div class="aw-stack">${shown.map(taskCard).join('')}</div>` : smallEmpty('Задач ещё нет. Откройте SF Chat или запустите разрешённую проверку.'), '<button class="aw-link-button" data-aw-tab="work">Все задачи →</button>')}${realWorkHint()}${panel('Требует внимания', alertsBody)}</div><div class="aw-column aw-column-results">${panel('Результаты и исходные данные', outcomes.length ? `<div class="aw-outcomes">${outcomes.map(outcomeCard).join('')}</div>` : smallEmpty('Пока нет сохранённых результатов. Здесь появятся отчёты, снимки и выполненные задачи с указанным источником.'))}${panel('Последние действия', timeline(rows(overview.activity).slice(0, 4), false))}</div><div class="aw-column aw-column-team">${panel('Команда и рейтинг', agents.length ? `<div class="aw-team">${agents.slice(0, 6).map(agentMini).join('')}</div><p class="aw-rating-note">n — размер выборки. NEW — данных недостаточно. Оценки относятся к классу задач; synthetic-проверка не оценивает качество LLM.</p>` : smallEmpty('В этом рабочем пространстве пока нет агентов.'), '<button class="aw-link-button" data-aw-tab="agents">Вся команда →</button>')}${foundationCard()}</div></div>`;
    }
    function taskTable(tasks) {
      if (!tasks.length) return empty('Задач по этому фильтру нет', 'Измените фильтр или запустите проверочный сценарий. Новые задачи появятся после записи на сервере.');
      return `<div class="aw-table-wrap"><table class="aw-table"><thead><tr><th>Задача / класс</th><th>Координатор</th><th>Участники</th><th>Этап</th><th>Прогресс</th><th>Статус</th><th>Обновлено</th><th>Стоимость</th></tr></thead><tbody>${tasks.map(task => `<tr><td><button class="aw-table-title" data-aw-task="${esc(taskId(task))}">${esc(taskTitle(task))}</button><div class="aw-table-sub">${esc(taskClass(task))}${task.synthetic ? ' · SYNTHETIC' : ''}</div></td><td><span class="aw-people">${avatar(task.lead, 'sm')}${esc(name(task.lead))}</span></td><td><span class="aw-faces" title="${esc(rows(task.participants).map(name).join(', '))}">${rows(task.participants).slice(0, 4).map(person => avatar(person, 'sm')).join('')}</span><span class="aw-muted">${task.participants?.length ? '' : '—'}</span></td><td>${esc(task.result_label || stageName(task.stage))}</td><td>${progress(task)}</td><td>${taskBadge(task)}</td><td>${esc(date(task.updated_at || task.created_at))}</td><td>${esc(cost(task.cost_usd))}</td></tr>`).join('')}</tbody></table></div>`;
    }
    function renderWork() {
      const filters = { all: 'Все', active: 'Активные', waiting: 'Ожидают', review: 'Требуют решения', attention: 'Требуют внимания', completed: 'Завершённые', failed: 'Ошибки' };
      content.innerHTML = `<div class="aw-section-heading"><div><h2>Работа команды</h2><p>От постановки задачи до результата: участники, действия, проверки и артефакты.</p></div></div><div class="aw-toolbar"><div class="aw-filters" aria-label="Фильтр задач">${Object.entries(filters).map(([key, label]) => `<button class="aw-filter" data-aw-filter="${key}" aria-pressed="${filter === key}">${label}</button>`).join('')}</div><input type="search" id="aw-task-search" class="aw-search" placeholder="Найти задачу или агента…" aria-label="Поиск задач" maxlength="160" value="${esc(query)}"></div><div id="aw-work-table">${taskTable(workRows.filter(task => taskMatches(task, filter, query)))}</div>${nextCursor ? '<div class="aw-pagination"><button class="btn" id="aw-load-more">Показать ещё</button></div>' : ''}`;
    }
    function agentCard(agent) {
      const evaluation = evaluationMeta(agent);
      return `<article class="aw-agent-card"><div class="aw-agent-card-top">${avatar(agent)}<div><div class="aw-agent-name">${esc(name(agent))}</div><div class="aw-agent-role">${esc(role(agent))}</div></div></div>${agentState(agent)}<div class="aw-agent-score"><small>Результат проверок${agent.synthetic === true ? ' · SYNTHETIC' : ''}</small><strong>${esc(evaluation.label)}</strong><small>${evaluation.insufficient ? 'Недостаточно сопоставимых наблюдений' : 'Проверенные критерии, не качество LLM'}</small><div class="aw-agent-meta"><span>Выборка: ${count(evaluation.sample)}</span><span>Уверенность: ${esc(evaluation.confidence)}</span></div></div><div class="aw-agent-assignment">${esc(agent.current_task?.title || agent.current_task_title || 'Нет активной задачи')}</div><div class="aw-actions"><button class="aw-link-button" data-aw-agent="${esc(agentId(agent))}">Профиль и рейтинг →</button></div></article>`;
    }
    function renderAgents() {
      const agents = rows(overview.agents);
      content.innerHTML = `<div class="aw-section-heading"><div><h2>Ваша команда</h2><p>Persona — имя, лицо и голос. Роль определяет обязанности; модель выбирается отдельно и не меняет личность агента.</p></div><div class="aw-actions"><button class="btn" data-aw-domain="personas">Создать / изменить Persona</button><button class="btn" data-aw-domain="models">Подключить свою модель</button></div></div>${agents.length ? `<div class="aw-agent-grid">${agents.map(agentCard).join('')}</div>` : empty('Команда пока пуста', 'Создайте персону и подключите свою модель через инструменты этого рабочего пространства.')}<div class="aw-note">Проверочный рейтинг — результат измеренных критериев конкретного класса задач. Сравнивайте только одинаковые классы и окна наблюдения. SYNTHETIC не оценивает качество внешней модели и не влияет на рабочую маршрутизацию.</div>${panel('Проверочный рейтинг', agents.length ? `<div class="aw-table-wrap"><table class="aw-table"><thead><tr><th>Агент / роль</th><th>Класс задачи</th><th>Наблюдения</th><th>Результат</th><th>Уверенность</th></tr></thead><tbody>${agents.map(agent => { const evaluation = evaluationMeta(agent); return `<tr><td><button class="aw-table-title" data-aw-agent="${esc(agentId(agent))}">${esc(name(agent))}</button><div class="aw-table-sub">${esc(role(agent))}</div></td><td>${esc(taskClass(agent.evaluation))}</td><td>n = ${count(evaluation.sample)}</td><td>${esc(evaluation.label)}</td><td>${esc(evaluation.confidence)}</td></tr>`; }).join('')}</tbody></table></div>` : smallEmpty('Оценки не выставлены. Нулевая выборка не означает нулевое качество.'))}`;
      if (overview?.scope?.synthetic === false) content.insertAdjacentHTML('beforeend',
        panel('Реальные задания · отдельные проверки исполнения', applicationTable(agents)));
    }
    function renderHeader() {
      const stats = overview?.stats || {}, scope = overview?.scope || {};
      qs('#aw-run-demo').hidden = !canRunDemo(overview);
      qs('#aw-run-demo').disabled = demoBusy;
      qs('#aw-run-demo').textContent = demoBusy ? 'Выполняем проверки…' : 'Запустить проверочные задачи';
      qsa('[data-aw-domain]', qs('#aw-domain-launcher')).forEach(button => { button.disabled = overview?.enabled !== true; });
      qs('#aw-pulse').innerHTML = `${badge(overview?.enabled ? 'active' : 'disabled')}<span>${count(stats.agents ?? rows(overview?.agents).length)} агентов</span><span>${count(stats.active_tasks)} в работе</span><span>${count(stats.attention)} требуют внимания</span>`;
      const context = qs('#aw-context');
      context.hidden = !overview?.enabled;
      context.innerHTML = scope.synthetic || overview?.synthetic ? '<span class="aw-context-mark">SYNTHETIC</span><span><strong>Изолированная проверка владельца.</strong> Задачи действительно выполняются локальными детерминированными обработчиками. Исходные данные тестовые; платные модели и торговые действия не вызываются. Рейтинг — не оценка качества LLM.</span>' : '<span class="aw-context-mark">LOCAL</span><span><strong>Ваше рабочее пространство.</strong> AI Центр находится в разработке. Проверочные данные не заменяют owner-данные, а выключенные пути не изменяют текущие механизмы приложения.</span>';
      qs('#aw-updated').textContent = 'Обновлено ' + date(new Date().toISOString());
    }
    function selectTab(next, updateLocation, background = false, options = {}) {
      if (!background) stopPersonaAudio();
      if (!TABS.includes(next)) next = 'overview';
      tab = next;
      qsa('.aw-tabs [data-aw-tab]', shell).forEach(button => { const active = button.dataset.awTab === tab; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
      content.setAttribute('aria-labelledby', 'aw-tab-' + tab);
      if (updateLocation) root.history.replaceState(null, '', '#tab=' + encodeURIComponent(tab));
      // Work used to read fresh tasks while its header/profile retained an old
      // overview indefinitely. User navigation refreshes both projections.
      return updateLocation ? refresh() : loadTab(false, options);
    }
    function readError(error) {
      if (error?.status === 403) return empty('Нет доступа к этому разделу', 'Сервер не разрешил чтение данных в текущем контексте. Обновите страницу после изменения доступа.');
      if (error?.status === 404) return empty('Раздел недоступен', 'Этот путь пока не включён в текущем локальном build.', '<button class="btn" data-aw-retry>Проверить снова</button>');
      return empty('Не удалось загрузить данные', 'Сохранённые записи не изменены. Повторите безопасное чтение.', '<button class="btn" data-aw-retry>Повторить</button>');
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
        content.innerHTML = empty('AI Центр пока выключен', 'Новый интерфейс включается сервером для конкретного окружения и рабочего пространства. Текущие AI Lab и подключения остаются доступны.', '<a class="btn" href="ai-lab.html">Исследования</a><a class="btn" href="ai-agents.html">Подключения и модели</a>');
        content.setAttribute('aria-busy', 'false'); return;
      }
      content.setAttribute('aria-busy', 'true');
      try {
        if (tab === 'overview') preserveView(content, renderOverview);
        else if (tab === 'agents') preserveView(content, renderAgents);
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
          preserveView(content, renderWork);
        }
        refreshFaces();
      } catch (error) {
        if (error?.name !== 'AbortError' && request === generation && !disposed) content.innerHTML = readError(error);
      } finally { if (request === generation && !disposed) content.setAttribute('aria-busy', 'false'); }
    }
    async function refresh({ background = false } = {}) {
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
        const result = await API.aiControlCenterOverview({ signal });
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
          ? await readWorkPages(Math.max(1, Math.ceil(workRows.length / 50)), isCurrent) : null;
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
    function openDrawer(title, html) {
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
      currentDrawer.classList.add('wide');
      currentDrawer.setAttribute('role', 'dialog'); currentDrawer.setAttribute('aria-modal', 'true'); currentDrawer.setAttribute('aria-label', title); currentDrawer.tabIndex = -1;
      currentDrawer.focus();
      refreshFaces(currentDrawer);
      return currentDrawer;
    }
    const recordId = item => String(item?.id || item?.task_id || '');
    const recordValue = (item, key) => item?.[key] ?? item?.profile?.[key] ?? item?.presentation?.[key] ?? item?.schedule?.[key] ?? item?.packet?.[key];
    function domainNav(selected) {
      return `<nav class="aw-domain-nav" aria-label="Инструменты в панели">${Object.entries(DOMAINS).filter(([key]) => !['tasks', 'model_tasks'].includes(key)).map(([key, meta]) => `<button class="aw-filter" data-aw-domain="${key}" aria-pressed="${selected === key}">${esc(meta.title)}</button>`).join('')}</nav>`;
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
      const component = domainState.key === 'memory' ? memoryScopeCard(item) : domainState.key === 'models' ? modelProtocolCard(item) : domainState.key === 'system' && typeof item.implemented === 'boolean' ? `<dl class="aw-detail-grid"><div><dt>Код реализован</dt><dd>${item.implemented ? 'Да' : 'Нет'}</dd></div><div><dt>Флаг</dt><dd>${item.enabled ? 'Включён' : 'Выключен'}</dd></div><div><dt>Фактический режим</dt><dd>${esc(item.mode)}</dd></div><div><dt>Доступность сейчас</dt><dd>${item.available ? 'Подтверждена' : 'Не подтверждена'}</dd></div></dl><p class="aw-note">${esc(item.note || '')}</p>` : '';
      return `<article class="aw-domain-card"><div class="aw-domain-card-head">${heading}${item.display_status ? taskBadge(item) : badge(item.status)}</div>${item.summary || item.description ? `<p class="aw-text">${esc(item.summary || item.description)}</p>` : ''}<div class="aw-domain-card-meta">${item.model ? `<span>Model: ${esc(item.model)}</span>` : ''}${item.provider ? `<span>${esc(item.provider)}</span>` : ''}${item.synthetic === true ? '<span class="aw-status aw-info">SYNTHETIC</span>' : ''}<time>${esc(date(item.updated_at || item.created_at))}</time></div>${domainState.key === 'models' ? `<p class="aw-field-hint">${esc(connectionLabel(item))}</p>` : ''}${metrics ? `<div class="aw-domain-card-meta"><span>Проверка ответа: ${esc(pct(metrics.score_pct ?? metrics.observed_score_pct))}</span>${number(metrics.sample_size) == null ? '' : `<span>n = ${count(metrics.sample_size)}</span>`}</div><p class="aw-note">Результат указанной проверки, не общий процент профессионального качества.</p>` : ''}${item.result_text ? `<p class="aw-result-excerpt">${esc(String(item.result_text).slice(0, 240))}</p>` : ''}${component}${domainState.key === 'system' && item.fields ? `<details class="aw-technical"><summary>Технические детали</summary><pre class="aw-result-text">${esc(publicJSON(item.fields))}</pre></details>` : ''}<div class="aw-actions">${domainActionButtons(item)}</div></article>`;
    }
    const GRANT_KINDS = { schedule: 'Расписание', delegation: 'Делегирование' };
    function automationGrantCard(item) {
      const id = recordId(item), kind = GRANT_KINDS[item.kind] || 'Разрешение';
      // `operational` is the grant's own answer, and it is not the same as its
      // status: an approved grant whose window has closed no longer authorises
      // anything, and saying «Одобрено» alone would hide that.
      const standing = item.operational === true ? 'да'
        : item.expired === true ? 'нет — срок истёк' : 'нет';
      return `<article class="aw-domain-card"><div class="aw-domain-card-head"><button class="aw-table-title" data-aw-domain-item="${esc(id)}">${esc(kind + ' · ' + String(id).slice(0, 8))}</button>${badge(item.operational === true ? 'active' : item.status)}</div>`
        + `<dl class="aw-detail-grid"><div><dt>Действует сейчас</dt><dd>${standing}</dd></div>`
        + `<div><dt>Срок</dt><dd>${esc(date(item.expires_at))}</dd></div>`
        + `<div><dt>Потолок на вызов</dt><dd>${esc(cost(item.max_call_cost_usd))}</dd></div>`
        + `<div><dt>Устройство</dt><dd>${esc(item.device_mode || '—')}</dd></div></dl>`
        + `<div class="aw-actions">${domainActionButtons(item)}</div></article>`;
    }
    function drawDomain() {
      if (!domainState) return;
      const { key, data } = domainState, meta = DOMAINS[key];
      const permitted = allowedDomainActions(data), createAction = key === 'models' ? 'connect' : key === 'publications' ? 'prepare' : 'create';
      const create = (permitted.includes(createAction) ? `<button class="btn primary" data-aw-domain-action="${createAction}" data-aw-entity="new">+ ${esc(meta.create || actionLabel(createAction))}</button>` : '') + ['bind_existing', 'propose_consensus', 'suggest_routine', 'commission', 'propose'].filter(action => permitted.includes(action)).map(action => `<button class="btn" data-aw-domain-action="${action}" data-aw-entity="new">${esc(actionLabel(action))}</button>`).join('');
      const history = ['models', 'model_tasks', 'experiments'].includes(key) ? `<div class="aw-actions"><button class="aw-link-button" data-aw-domain="models">Подключения</button><button class="aw-link-button" data-aw-domain="model_tasks">История задач моделей</button><button class="aw-link-button" data-aw-domain="experiments">Сравнения</button></div>` : '';
      let body;
      if (data.enabled !== true) body = empty('Раздел не разрешён в текущем контексте', 'Функция не удалена из плана. Сервер не разрешил её использование; проверьте ограничения ниже.');
      else body = items(data).length ? `<div class="aw-domain-grid">${items(data).map(key === 'automation' ? automationGrantCard : domainItemCard).join('')}</div>` : smallEmpty('Сохранённых записей пока нет. Новые записи появятся только после подтверждённого действия.');
      body += processIntelligencePanel(data, key);
      if (key === 'automation') {
        const admin = data.capability_admin || {}, granted = admin.granted === true;
        // Three separate conditions, shown as three separate facts.
        const control = admin.can_manage === true
          ? `<div class="aw-actions"><button class="btn${granted ? '' : ' primary'}" data-aw-capability="${granted ? 'revoke' : 'grant'}" data-aw-capability-user="${esc(admin.user_id)}">${granted ? 'Отозвать разрешение на автоматизацию' : 'Выдать разрешение на автоматизацию'}</button></div>`
          : `<p class="aw-note">Разрешение выдаёт владелец рабочего пространства. Самостоятельно повысить свои права здесь нельзя.</p>`;
        body = `<section class="aw-detail-section"><h3>Условия автоматизации</h3><dl class="aw-detail-grid"><div><dt>Разрешение ai_automation</dt><dd>${badge(granted ? 'active' : 'disabled')}</dd></div><div><dt>Механизм расписаний</dt><dd>${badge(data.flags?.AI_SCHEDULER_V1 ? 'active' : 'disabled')}</dd></div><div><dt>Согласие на рутину</dt><dd>Отдельное действие для каждой записи</dd></div></dl>${control}</section>` + body;
        const schedules = rows(data.schedules);
        const commissions = rows(data.commissions);
        if (commissions.length) body += `<section class="aw-detail-section"><h3>Поручения Координатору</h3><div class="aw-domain-grid">${commissions.map(row => `<article class="aw-domain-card"><h4>${esc(row.goal || 'Поручение Координатору')}</h4>${badge(row.status)}<p class="aw-text">${row.stage === 'awaiting_approval' ? 'Исходный результат готов. Дочерние задания ещё не разрешены.' : row.graph ? 'Состояние общего результата и отдельных вкладов — в задаче ниже.' : 'Выполняется исходное задание; делегирование ещё не разрешено.'}</p><div class="aw-actions"><button class="btn" data-aw-task="${esc(row.root_task_id)}">Исходная задача и SF Chat</button>${row.graph?.id ? `<button class="btn" data-aw-task="${esc(row.graph.id)}">Общий результат и вклады</button>` : ''}${allowedDomainActions(data, row).map(action => `<button class="btn" data-aw-domain-action="${action}" data-aw-entity="${esc(row.id)}">${esc(actionLabel(action))}</button>`).join('')}</div><p class="aw-note">${esc(row.limitation || '')}</p></article>`).join('')}</div></section>`;
        if (schedules.length) body += `<section class="aw-detail-section"><h3>Расписания</h3><div class="aw-domain-grid">${schedules.map(row => `<article class="aw-domain-card"><h4>${esc('Расписание · ' + String(row.id || '').slice(0, 8))}</h4><div class="aw-inline">${badge(row.status)}${row.grant_status ? badge(row.grant_status) : ''}</div><p class="aw-text">${esc(rows(row.occurrences).map(item => (item.status || '') + ' · ' + date(item.due_at)).join(' | ') || 'Запусков ещё не было.')}</p><div class="aw-actions">${allowedDomainActions(data, row).map(action => `<button class="btn" data-aw-domain-action="${action}" data-aw-entity="${esc(row.id)}">${esc(actionLabel(action))}</button>`).join('')}</div></article>`).join('')}</div></section>`;
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
      mutationBusy = true;
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
      openDrawer(DOMAINS[key].title, domainNav(key) + smallEmpty('Загрузка записей текущего рабочего пространства…'));
      try {
        const data = await API.aiControlCenterDomain(key, { limit: 50, cursor: prior?.next_cursor || '' }, { signal });
        if (key === 'router' && data.enabled === true) {
          const tasks = await API.aiControlCenterDomain('model_tasks', { limit: 100 }, { signal });
          data.source_tasks = items(tasks).filter(task => task.conversation_id && task.model_id && rows(data.task_classes).includes(task.task_class || task.rubric_key));
        }
        if (disposed || request !== detailGeneration) return;
        domainState = { key, data: prior ? { ...data, items: items(prior).concat(items(data)) } : data };
        drawDomain();
        root.history.replaceState(null, '', '#tab=' + encodeURIComponent(tab) + '&domain=' + encodeURIComponent(key));
      } catch (error) {
        if (error?.name !== 'AbortError' && request === detailGeneration && !disposed) openDrawer(DOMAINS[key].title, domainNav(key) + readError(error));
      }
    }
    function domainRecord(item) {
      const key = domainState.key, meta = DOMAINS[key];
      const fields = domainFormFields(key, key === 'models' ? 'connect' : 'create').filter(spec => spec.type !== 'password' && !(key === 'personas' && spec.optionalIfMissing));
      const description = fields.filter(spec => recordValue(item, spec.key) !== undefined && recordValue(item, spec.key) !== null && recordValue(item, spec.key) !== '').map(spec => {
        const raw = recordValue(item, spec.key);
        const value = spec.type === 'datetime-local' ? date(raw) : spec.type === 'select' ? spec.options.find(([id]) => id === raw)?.[1] || 'Не указано' : typeof raw === 'object' ? publicJSON(raw) : String(raw);
        return `<div><dt>${esc(spec.label)}</dt><dd class="aw-pre-wrap">${esc(value)}</dd></div>`;
      }).join('');
      const verification = item.observed_eval || item.evaluation;
      const evaluationBody = verification ? evaluations([verification]) : '';
      const result = item.result_text || item.response_text || item.output_text;
      const resultBody = (result ? `<section class="aw-detail-section"><h3>Фактический ответ</h3><pre class="aw-result-text">${esc(result)}</pre></section>` : '') + followupCard(item) + handoffCard(item);
      const sources = rows(item.source_ids || item.evidence_ids);
      const sourceBody = sources.length ? `<section class="aw-detail-section"><h3>Источники</h3>${sources.map(id => `<div class="aw-hash">ARTIFACT ${esc(id)}</div>`).join('')}</section>` : '';
      const versions = rows(item.versions);
      const versionBody = versions.length ? `<section class="aw-detail-section"><h3>История версий</h3>${versions.map(version => `<article class="aw-domain-card"><div class="aw-domain-card-meta"><strong>Версия ${esc(version.version || version.revision || '—')}</strong><time>${esc(date(version.created_at))}</time></div><p class="aw-text">${esc(version.notes || version.summary || '')}</p>${version.parameters ? `<pre class="aw-result-text">${esc(publicJSON(version.parameters))}</pre>` : ''}</article>`).join('')}</section>` : '';
      const cases = rows(item.court_cases), votes = rows(item.votes || item.packet?.votes).concat(cases.flatMap(entry => rows(entry.votes)));
      const courtBody = key === 'decisions' ? `<section class="aw-detail-section"><h3>Проверка Court</h3>${cases.map(entry => `<div class="aw-context"><span class="aw-context-mark">COURT</span><span>Вердикт: ${esc(entry.verdict || entry.status || 'не определён')} · кворум ${esc(entry.quorum || 'не указан')} · исполнение ${entry.execution_allowed === true ? 'проверяется отдельно сервером' : 'не разрешено'}<span class="aw-hash">${esc(entry.packet_sha256 || '')}</span></span></div>`).join('')}${votes.length ? votes.map(vote => `<article class="aw-domain-card"><div class="aw-inline"><strong>${esc(vote.model_key || vote.model || vote.model_id || vote.judge || 'Проверяющий')}</strong>${badge(vote.status || vote.verdict)}</div><p class="aw-text">${esc(vote.summary || vote.rationale || vote.reason || '')}</p><div class="aw-domain-card-meta"><span>${esc(vote.provider_key || '')}</span><span>Уверенность: ${esc(vote.confidence ?? 'не измерена')}</span></div><div class="aw-hash">SESSION ${esc(vote.session_id || 'не предоставлен')}<br>PACKET ${esc(vote.packet_sha256 || 'не предоставлен')}</div>${vote.task_id ? taskLink(vote.task_id, 'Задание проверяющего') : ''}</article>`).join('') : smallEmpty('Проверяющие ещё не представили результаты. Отсутствие голосов не является одобрением.')}<p class="aw-note">В панели нет кнопки выдачи голоса от имени модели. Review запускает проверку backend; новые права и торговые действия не выдаются.</p></section>` : '';
      const comparison = rows(item.results || item.comparison || item.tasks);
      const comparisons = key === 'experiments' && comparison.length ? `<section class="aw-detail-section"><h3>Сопоставимые результаты</h3><div class="aw-domain-grid">${comparison.map(result => `<article class="aw-domain-card"><strong>${esc(result.model || result.label || result.model_id || 'Модель')}</strong>${badge(result.status)}<dl class="aw-detail-grid"><div><dt>Результат проверки</dt><dd>${esc(pct(result.score_pct ?? result.evaluation?.score_pct ?? result.evaluation?.observed_score_pct ?? result.observed_eval?.score_pct))}</dd></div><div><dt>Длительность</dt><dd>${number(result.latency_ms) == null ? 'не измерена' : esc(count(result.latency_ms)) + ' мс'}</dd></div><div><dt>Стоимость</dt><dd>${esc(cost(result.cost_usd))}</dd></div></dl>${result.task_id || result.id ? `<button class="aw-link-button" data-aw-model-task="${esc(result.task_id || result.id)}">Ответ и доказательства →</button>` : ''}</article>`).join('')}</div></section>` : '';
      const modelTaskLink = key === 'model_tasks' && (item.id || item.task_id) ? `<button class="btn" data-aw-task-chat="${esc(recordId(item))}">Открыть в SF Chat</button>` : '';
      const metaFields = `<dl class="aw-detail-grid"><div><dt>Ревизия</dt><dd>${count(item.revision)}</dd></div><div><dt>Обновлено</dt><dd>${esc(date(item.updated_at || item.created_at))}</dd></div>${item.model ? `<div><dt>Запрошенная модель</dt><dd>${esc(item.model)}</dd></div>` : ''}${key === 'models' ? `<div><dt>Ключ</dt><dd>${item.credentials_configured === true ? 'Настроен · не выводится' : 'Не настроен'}</dd></div>` : ''}${key === 'model_tasks' ? `<div><dt>Model ID от провайдера</dt><dd>${esc(item.actual_model || 'Не предоставлен')}</dd></div><div><dt>Измеренная стоимость</dt><dd>${esc(cost(item.cost_usd))}</dd></div><div><dt>Длительность</dt><dd>${number(item.latency_ms) == null ? 'не измерена' : count(item.latency_ms) + ' мс'}</dd></div>` : ''}</dl>`;
      const personaBody = key === 'memory' ? memoryScopeCard(item) : key === 'external_agents' ? externalAgentCard(item) : key === 'personas' ? personaPresentationCard(item, avatar(item, 'lg')) : key === 'models' ? modelProtocolCard(item) : '';
      openDrawer(meta.title + ' · ' + (item.title || item.label || item.name || 'Запись'), `${domainNav(key)}<div class="aw-actions"><button class="aw-link-button" data-aw-domain="${key}">← Все записи</button>${domainActionButtons(item)}${modelTaskLink}</div><h2 class="aw-inspector-title">${esc(item.title || item.label || item.name || item.model || 'Запись')}</h2><div class="aw-inline">${badge(item.status)}${item.synthetic === true ? '<span class="aw-status aw-info">SYNTHETIC</span>' : ''}</div>${domainLimitations(item)}${item.summary ? `<p class="aw-text">${esc(item.summary)}</p>` : ''}${metaFields}${personaBody}<dl class="aw-detail-grid">${description}</dl>${resultBody}${evaluationBody}${sourceBody}${versionBody}${courtBody}${comparisons}<div class="aw-hash">ID ${esc(recordId(item))}${item.correlation_id ? '<br>CORRELATION ' + esc(item.correlation_id) : ''}</div>`);
    }
    async function openDomainItem(id) {
      if (!domainState || !id || mutationBusy) return;
      if (domainState.key === 'router') return openRouterTask(id);
      if (domainState.key === 'model_tasks') return openTask(id);
      const request = ++detailGeneration, key = domainState.key;
      actionForm = null;
      openDrawer(DOMAINS[key].title, domainNav(key) + smallEmpty('Загрузка актуальной записи…'));
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
      mutationBusy = true; errorBox.hidden = true;
      qsa('button, input, select, textarea', form).forEach(input => { input.disabled = true; });
      try {
        const result = await API.aiControlCenterDomainAction(state.domain, state.id, state.action, body);
        if (disposed) return;
        if (result?.ok === false) throw { status: 409 };
        if (state.domain === 'automation' && state.action === 'propose' && state.scheduleSource) {
          if (!validSchedulePreview(result, state.scheduleSource, payload)) throw new Error('Источник или план расписания изменился. Откройте форму заново.');
          mutationBusy = false;
          actionForm = { ...state, action: 'enable', scheduleApproval: { payload }, revision: state.scheduleSource.revision };
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
      const labels = { summary: 'Обзор', activity: 'Активность', evidence: 'Evidence', agents: 'Агенты', evaluations: 'Оценка', artifacts: 'Артефакты', decisions: 'Решения', errors: 'Ошибки' };
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
      if (detailTab === 'summary') body += intentPanel(detail.intent);
      if (detailTab === 'evaluations') body += reputationPanel(detail.reputation);
      if (detailTab === 'summary') body += transportVerificationNote(task);
      if (detailTab === 'summary' && task.source_kind === 'real_model_response') body += `<section class="aw-detail-section"><h3>Исполнитель и происхождение результата</h3><dl class="aw-detail-grid"><div><dt>Запрошенная модель</dt><dd>${esc(task.model || 'Не предоставлена')}</dd></div><div><dt>Model ID от провайдера</dt><dd>${esc(detail.actual_model || 'Не предоставлен')}</dd></div><div><dt>Провайдер</dt><dd>${detail.external_call === false ? esc((task.provider || 'провайдер') + ' — не вызывался') : esc(task.provider || 'Не предоставлен')}</dd></div>${detail.executor ? `<div><dt>Ответ получен от</dt><dd>${esc(detail.executor)}</dd></div>` : ''}</dl>${detail.external_call === false ? '<p class="aw-note">Ответ вычислен локально: внешнее обращение не выполнялось, поэтому этот результат ничего не говорит о доступности провайдера.</p>' : ''}<details class="aw-technical"><summary>Связанные записи</summary>${['intent_id', 'execution_id', 'contribution_id', 'outcome_id', 'evaluation_id', 'conversation_id', 'message_id'].filter(key => task[key]).map(key => `<div class="aw-hash">${esc(key.toUpperCase())} ${esc(task[key])}</div>`).join('')}</details></section>`;
      if (detailTab === 'summary' && detail.graph) {
        const review = detail.graph.human_review || {};
        const labels = { pending: 'Ожидается отдельная проверка', accepted: 'Принят', rejected: 'Отклонён', not_ready: 'Результат ещё не готов', stale: 'Источник изменился' };
        body += `<section class="aw-detail-section"><h3>Участники и обязательные проверки</h3><p class="aw-note">Проверка передачи фактов не означает приёмку всех вкладов или профессиональную оценку. Каждый исходный результат открывается отдельно.</p><div class="aw-stack">${rows(review.required_reviews).map((entry, index) => `<article class="aw-domain-card"><h4>${index ? 'Проверка ' + index : 'Исходная работа Координатора'}</h4><p>${esc(labels[entry.status] || 'Требует проверки источника')}</p><button class="btn" data-aw-task="${esc(entry.task_id)}">Открыть результат и проверку</button></article>`).join('')}</div><details class="aw-technical"><summary>План, роли и происхождение вкладов</summary><pre>${esc(publicJSON(detail.graph))}</pre></details></section>`;
      }
      if (task.model_id && task.conversation_id) body += `<div class="aw-actions"><button class="btn" data-aw-router-task="${esc(taskId(task))}">Выбор подключения · Router</button></div>`;
      body += handoffCard(task);
      const taskActions = rows(task.allowed_actions || task.actions).filter(action => ['cancel', 'retry', 'handoff', 'review_result'].includes(action)).map(action => `<button class="btn${action === 'cancel' ? ' aw-danger-action' : ''}" data-aw-task-action="${action}">${esc(actionLabel(action))}</button>`).join('');
      const controls = `<div class="aw-actions"><button class="btn" data-aw-task-chat="${esc(taskId(task))}">Открыть в SF Chat</button>${source.reportUrl ? `<a class="btn" href="${esc(source.reportUrl)}">Открыть исходный отчёт</a>` : ''}${svg ? `<button class="btn primary" data-aw-chart-chat="${esc(taskId(task))}">Снимок графика → SF Chat</button>` : ''}${taskActions}</div>`;
      const tabs = `<nav class="aw-tabs" role="tablist" aria-label="Разделы задачи">${Object.entries(labels).map(([key, label]) => `<button role="tab" aria-selected="${detailTab === key}" tabindex="${detailTab === key ? 0 : -1}" data-aw-detail-tab="${key}">${label}</button>`).join('')}</nav>`;
      openDrawer('Задача · ' + taskTitle(task), `${controls}${tabs}<div role="tabpanel">${body}</div><details class="aw-technical"><summary>Идентификаторы и состояние журнала</summary><div class="aw-hash">TASK ${esc(taskId(task))}${task.correlation_id ? `<br>CORRELATION ${esc(task.correlation_id)}` : ''}<br>LEDGER ${esc(task.ledger_status || task.status)}</div></details>`);
    }
    async function openTask(id) {
      if (!id) return;
      const request = ++detailGeneration;
      detailKind = 'task'; detailTab = 'summary'; detail = null; actionForm = null;
      openDrawer('Задача', smallEmpty('Загрузка задачи и доказательств…'));
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
      const labels = { summary: 'Обзор', work: 'Работа', rating: 'Рейтинг', persona: 'Persona' };
      let body = '';
      if (detailTab === 'work') body = tasks.length ? `<div class="aw-stack">${tasks.map(taskCard).join('')}</div>` : smallEmpty('В текущей выборке нет задач этого агента. Полный журнал доступен в разделе «Работа».');
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
    async function runDemo() {
      if (!canRunDemo(overview) || demoBusy) return;
      demoBusy = true; renderHeader();
      if (!demoKey) demoKey = root.crypto.randomUUID();
      announce('Выполняются локальные задачи на тестовых данных. Это не вызов внешних моделей и не торговое действие.');
      try {
        await API.aiControlCenterDemoRun({ idempotency_key: demoKey });
        demoKey = null;
        await refresh();
        announce('Проверочный запуск записан. Откройте «Работа» для результатов, а «Агенты» — для измеренных оценок.');
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
      const target = event.target.closest('button, a');
      if (!target) return;
      const inside = shell.contains(target) || (currentDrawer && currentDrawer.contains(target) && target.closest('.aw-inspector'));
      if (!inside) return;
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
    const linkedTask = locationParams.get('task') || new URLSearchParams(root.location.search).get('task');
    if (linkedTask && overview?.enabled) await openTask(linkedTask);
    else if (knownDomain(locationParams.get('domain')) && overview?.enabled) {
      await openDomain(locationParams.get('domain'));
      if (locationParams.get('domain') === 'automation' && locationParams.get('chat_conversation') && locationParams.get('chat_message')) {
        try {
          const seed = await API.aiControlCenterDomainAction('automation', 'new', 'chat_seed', { payload: { conversation_id: locationParams.get('chat_conversation'), source_message_id: locationParams.get('chat_message') }, idempotency_key: root.crypto.randomUUID() });
          await openDomainAction('commission', 'new', null, seed);
        } catch (error) { openDrawer('Поручение из SF Chat', readError(error)); }
      }
      const entity = locationParams.get('entity');
      if (/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(entity || '')) await openDomainItem(entity);
    }
    // Reuse Aurora's existing single-flight, onLeave-cleaned polling lifecycle.
    // Reading never enqueues, accepts, retries or changes a permission/flag.
    UI.poll?.(() => refresh({ background: true }), 5000);
  });
})(typeof window !== 'undefined' ? window : globalThis);
