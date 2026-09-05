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
    models: { title: 'Модели и подключения', description: 'Ваши подключения и внешние агенты. Persona, учётная запись провайдера и модель — отдельные сущности.', create: 'Подключить модель' },
    model_tasks: { title: 'История моделей', description: 'Фактические ответы и независимые проверки. Неизвестная стоимость не равна нулевой.', create: '' },
    tasks: { title: 'Действия задачи', description: 'Изменение выполняет сервер после повторной проверки прав и состояния.', create: '' },
    experiments: { title: 'Эксперименты', description: 'Одно проверяемое задание для 2–3 моделей. Сравнение строится по фактическим ответам, не по самооценке.', create: 'Сравнить модели' },
    system: { title: 'Система', description: 'Доступность, ограничения и состояние текущего рабочего пространства. Чтение не меняет флаги или бюджет.', create: '' },
  });
  const ACTION_LABELS = Object.freeze({ create: 'Создать', connect: 'Подключить', bind_existing: 'Связать Local-подключение', update: 'Изменить', activate: 'Активировать', suspend: 'Приостановить', archive: 'В архив', promote: 'Продвинуть', publish_to_workspace: 'Опубликовать в workspace', propose_consensus: 'Собрать решение по вкладам', suggest_routine: 'Предложить по результатам', prepare: 'Подготовить снимок', publish: 'Опубликовать в SF Social', revoke: 'Отозвать', version: 'Новая версия', accept: 'Принять', dismiss: 'Отклонить', review: 'Проверить через Court', withdraw: 'Отозвать решение', test: 'Проверить соединение', task: 'Первое задание', disconnect: 'Отключить', cancel: 'Отменить задачу', retry: 'Повторить задачу' });
  const STATUS = {
    running: ['В работе', 'good'], working: ['В работе', 'good'], active: ['Активен', 'good'], healthy: ['Работает', 'good'], succeeded: ['Завершено', 'good'], completed: ['Завершено', 'good'], verified: ['Проверено', 'good'], passed: ['Проверено', 'good'], accepted: ['Принято', 'good'], submitted: ['Вклад записан', 'info'],
    planned: ['Запланировано', 'neutral'], ready: ['В очереди', 'neutral'], queued: ['В очереди', 'neutral'], waiting: ['Ожидает', 'neutral'], pending: ['Ожидает', 'neutral'], free: ['Свободен', 'neutral'], available: ['Свободен', 'neutral'], idle: ['Свободен', 'neutral'],
    review: ['Нужна проверка', 'review'], awaiting_owner: ['Решение владельца', 'review'], approval_required: ['Нужно подтверждение', 'review'], court: ['Разбор Court', 'review'],
    blocked: ['Заблокировано', 'warning'], paused: ['На паузе', 'warning'], warning: ['Внимание', 'warning'],
    failed: ['Ошибка', 'error'], rejected: ['Отклонено', 'error'], error: ['Ошибка', 'error'], cancelled: ['Отменено', 'neutral'],
    disabled: ['Выключено', 'neutral'], new: ['NEW · мало данных', 'neutral'], insufficient: ['NEW · мало данных', 'neutral'], info: ['Событие', 'info'],
    draft: ['Черновик', 'neutral'], proposed: ['Предложено', 'review'], approved: ['Одобрено', 'good'], promoted: ['Подтверждено', 'good'], revoked: ['Отозвано', 'warning'], expired: ['Истёк срок', 'neutral'], archived: ['В архиве', 'neutral'], retired: ['Выведено из работы', 'neutral'], suspended: ['Приостановлено', 'warning'], connected: ['Подключено', 'good'], disconnected: ['Отключено', 'neutral'], scheduled: ['Запланировано', 'neutral'], cancelled_requested: ['Отмена запрошена', 'warning'], cancel_requested: ['Отмена запрошена', 'warning'], review_required: ['Нужна проверка', 'review'], external_blocked: ['Внешний blocker', 'warning'], unavailable: ['Недоступно', 'warning'], exhausted: ['Лимит исчерпан', 'warning'], approve: ['За', 'good'], reject: ['Против', 'error'], abstain: ['Воздержался', 'neutral'],
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
  const stageName = value => ({ work: 'Выполнение', evaluation: 'Проверка результата', planning: 'Планирование', review: 'Проверка' }[value] || value || '—');
  const agentId = row => String(row && (row.id || row.persona_id || row.agent_id) || '');
  const name = row => typeof row === 'string' ? row : String(row && (row.display_name || row.name || row.title || row.id) || 'Не назначен');
  const role = row => typeof row?.role === 'object' ? name(row.role) : String(row?.role_label || row?.role || row?.specialization || 'Роль не указана');
  const canRunDemo = data => data?.enabled === true && data?.capabilities?.can_run_demo === true;
  const knownDomain = value => Object.prototype.hasOwnProperty.call(DOMAINS, String(value || ''));
  const actionLabel = value => Object.prototype.hasOwnProperty.call(ACTION_LABELS, value) ? ACTION_LABELS[value] : 'Действие';
  function allowedDomainActions(data, item) {
    if (data?.enabled !== true) return [];
    return rows(item ? item.actions : data.actions).filter(value => typeof value === 'string' && Object.prototype.hasOwnProperty.call(ACTION_LABELS, value));
  }
  const field = (key, label, type, extra) => ({ key, label, type: type || 'text', ...(extra || {}) });
  const rubricField = () => field('rubric_key', 'Независимая проверка', 'select', { required: true, options: [['connection_exact', 'Точный ответ · соединение'], ['json_arithmetic', 'Арифметика · JSON'], ['extract_facts', 'Извлечение фактов']] });
  function domainFormFields(domain, action) {
    if (!knownDomain(domain)) return [];
    if (domain === 'publications') {
      if (action === 'prepare') return [field('source', 'Проверенный источник', 'publication-source', { required: true, hint: 'Сервер предоставил только разрешённые источники. На этом шаге пост не создаётся.' })];
      if (action === 'publish') return [field('text', 'Комментарий к публикации (необязательно)', 'textarea', { max: 4000, hint: 'Только ваш публичный комментарий. Не вставляйте ключи, личные данные, private Memory или сырой ответ модели.' }), field('visibility', 'Кто увидит публикацию', 'select', { required: true, options: [['private', 'Только я'], ['followers', 'Мои подписчики'], ['network', 'Социальная сеть']] })];
      return [];
    }
    if (domain === 'tasks' && ['cancel', 'retry'].includes(action)) return [field('reason', 'Причина', 'textarea', { required: action === 'cancel', max: 1000 })];
    if (domain === 'models') {
      if (action === 'bind_existing') return [field('registry_id', 'Разрешённое Local-подключение', 'binding', { required: true, hint: 'Список сформирован сервером только для текущего владельца. Исходный ключ и существующий бюджет не меняются.' }), field('persona_id', 'Активная Persona', 'persona', { required: true }), field('label', 'Название связи (необязательно)', 'text', { max: 80 })];
      if (action === 'connect') return [field('label', 'Название подключения', 'text', { required: true, max: 80 }), field('connection_kind', 'Тип подключения', 'select', { required: true, options: [['model', 'Своя модель'], ['external_agent', 'Внешний агент']] }), field('provider', 'Провайдер', 'provider', { required: true }), field('model', 'Идентификатор модели', 'text', { required: true, max: 120 }), field('base_url', 'Endpoint (для совместимого провайдера)', 'url', { max: 250, hint: 'Только разрешённый сервером HTTPS endpoint. Для стандартного провайдера оставьте пустым.' }), field('api_key', 'Ключ подключения', 'password', { required: true, max: 4096 }), field('persona_id', 'Persona', 'persona', { required: true })];
      if (action === 'task') return [rubricField(), field('input_text', 'Входные данные проверки', 'textarea', { max: 4000, hint: 'Соединение: пустое поле. Арифметика: JSON-массив 3–20 целых чисел или пустое поле для стандартного набора. Факты: 2–12 строк вида city=Paris. Не отправляйте секреты.' })];
    }
    if (domain === 'experiments' && action === 'create') return [field('title', 'Название сравнения', 'text', { required: true, max: 80 }), field('model_ids', 'Модели (выберите 2–3)', 'models', { required: true, minItems: 2, maxItems: 3 }), rubricField(), field('input_text', 'Одинаковые входные данные', 'textarea', { max: 4000, hint: 'Соединение: пусто. Арифметика: JSON-массив целых чисел. Факты: строки key=value. Один вход будет отправлен всем выбранным моделям.' })];
    if (domain === 'decisions') {
      if (action === 'propose_consensus') return domainFormFields(domain, 'create').filter(spec => spec.key !== 'evidence_ids').concat(field('contribution_ids', 'Принятые вклады моделей (минимум два)', 'records', { required: true, minItems: 2, maxItems: 20, source: 'contribution_candidates', hint: 'Сервер проверит, что это собственные принятые вклады по одному заданию и входу. Выбор не создаёт голосов.' }));
      if (action === 'review') return [field('model_ids', 'Три независимых проверяющих', 'models', { required: true, minItems: 3, maxItems: 3, hint: 'Результат сформирует backend по фактическим ответам. Браузер не передаёт голоса.' })];
      if (action === 'create') return [field('title', 'Название решения', 'text', { required: true, max: 160 }), field('proposal', 'Предложение', 'textarea', { required: true, max: 12000 }), field('evidence_ids', 'Доказательства', 'evidence', { required: true, minItems: 1, maxItems: 20, hint: 'Только собственные JSON-артефакты. Выберите сохранённый источник либо укажите известный UUID.' }), field('risk', 'Уровень риска', 'select', { required: true, options: [['low', 'Низкий'], ['moderate', 'Умеренный'], ['high', 'Высокий'], ['critical', 'Критический']] }), field('trigger', 'Причина проверки', 'select', { required: true, options: [['requested_review', 'Запрошена проверка'], ['high_risk', 'Высокий риск'], ['conflict', 'Конфликт'], ['low_confidence', 'Низкая уверенность'], ['budget_exceeded', 'Превышение бюджета']] })];
    }
    if (domain === 'routines' && action === 'suggest_routine') return [field('title', 'Название предложения', 'text', { required: true, max: 160 }), field('interval_minutes', 'Интервал (минуты)', 'number', { required: true, min: 5, max: 525600 }), field('outcome_ids', 'Проверенные результаты (минимум два)', 'records', { required: true, minItems: 2, maxItems: 20, source: 'outcome_candidates', hint: 'Предложение опирается на сохранённые успешные результаты. Автоматическое исполнение не включается.' })];
    if (domain === 'projects' && action === 'version') return [field('notes', 'Что изменилось', 'textarea', { required: true, max: 6000 }), field('parameters', 'Параметры версии (JSON-объект)', 'json', { required: true, max: 12000 })];
    if (domain === 'memory' && ['promote', 'revoke', 'publish_to_workspace'].includes(action)) return [field('reason', 'Основание', 'textarea', { required: true, max: 1000 })];
    if (!['create', 'update'].includes(action)) return [];
    if (domain === 'personas') return [field('name', 'Имя персоны', 'text', { required: true, max: 160 }), field('description', 'Назначение', 'textarea', { max: 4000 }), field('style', 'Стиль общения', 'textarea', { max: 1000 }), field('application_role', 'Роль в приложении', 'select', { sendEmpty: true, options: [['', 'Не назначена'], ['backtest_researcher', 'Бэктестирование'], ['chart_researcher', 'Рабочий стол и графики']], hint: 'Явное назначение для команд SF Chat. Имя можно менять. Роль не выдаёт прав, ключей или торгового доступа. Одна активная / приостановленная Persona на роль.' })];
    const title = field('title', 'Название', 'text', { required: true, max: 160 });
    const description = field('description', 'Описание', 'textarea', { max: 4000, sendEmpty: true });
    const sources = field('source_ids', 'UUID исходных артефактов', 'ids', { maxItems: 20, hint: 'Необязательно. По одному UUID в строке; принадлежность проверит сервер.' });
    if (domain === 'memory') return [title, field('content', 'Содержание', 'textarea', { required: true, max: 12000 }), field('purpose', 'Для чего хранится', 'text', { required: true, max: 160 }), field('retention_days', 'Срок хранения (дни)', 'number', { required: true, min: 1, max: 365 }), sources];
    if (domain === 'projects') return [title, description, field('strategy_key', 'Ключ стратегии', 'text', { required: true, max: 120 })];
    if (domain === 'routines') return [title, description, field('interval_minutes', 'Интервал (минуты)', 'number', { required: true, min: 5, max: 525600 }), sources];
    if (domain === 'calendar') return [title, description, field('starts_at', 'Начало (местное время)', 'datetime-local', { required: true }), field('ends_at', 'Окончание (местное время)', 'datetime-local', { required: true }), sources];
    return [];
  }
  function domainPayload(domain, action, values) {
    if (!knownDomain(domain) || !Object.prototype.hasOwnProperty.call(ACTION_LABELS, action)) throw new Error('Неизвестное действие.');
    const payload = {};
    for (const spec of domainFormFields(domain, action)) {
      const raw = values?.[spec.key];
      let value = Array.isArray(raw) ? raw : String(raw ?? '').trim();
      if (spec.required && (!value || Array.isArray(value) && !value.length)) throw new Error('Заполните поле «' + spec.label + '».');
      if (!value || Array.isArray(value) && !value.length) { if (spec.type === 'ids') payload[spec.key] = []; else if (spec.sendEmpty) payload[spec.key] = ''; continue; }
      if (spec.type === 'publication-source') {
        const match = /^(outcome|decision|backtest):([A-Za-z0-9_-]{1,96})$/.exec(value);
        if (!match || match[1] !== 'backtest' && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(match[2])) throw new Error('Выберите проверенный источник.');
        payload.source_kind = match[1]; payload.source_id = match[2]; continue;
      } else if (spec.type === 'number') {
        value = Number(value);
        if (!Number.isSafeInteger(value) || value < spec.min || value > spec.max) throw new Error('«' + spec.label + '»: допустимо от ' + spec.min + ' до ' + spec.max + '.');
      } else if (['models', 'ids', 'evidence', 'records'].includes(spec.type)) {
        value = Array.from(new Set((Array.isArray(value) ? value : value.split(/[\s,]+/)).map(String).filter(Boolean)));
        if (value.some(id => !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) || value.length < (spec.minItems || 0) || value.length > spec.maxItems) throw new Error('Проверьте UUID и количество в поле «' + spec.label + '».');
      } else if (spec.type === 'persona' && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)) throw new Error('Выберите сохранённую персону.');
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
      payload[spec.key] = value;
    }
    if (domain === 'calendar' && payload.starts_at && payload.ends_at && payload.ends_at <= payload.starts_at) throw new Error('Окончание должно быть позже начала.');
    return payload;
  }
  function validPublicationPreview(prepared, source) {
    return prepared?.permanent === true && prepared?.requires_explicit_confirmation === true && prepared?.snapshot?.synthetic === false && typeof prepared.snapshot.title === 'string' && typeof prepared.snapshot.summary === 'string' && prepared.snapshot.source_id === source?.source_id && /^[0-9a-f]{64}$/.test(prepared.snapshot_sha256 || '') && Number.isSafeInteger(prepared.source_revision) && prepared.source_revision > 0 && prepared.snapshot.source_revision === prepared.source_revision;
  }
  function domainError(error) {
    const code = String(error?.code || error?.data?.error || error?.error || '');
    const messages = {
      budget_exceeded: 'Лимит расходов не разрешает этот запрос. Бюджет не изменён.', budget_denied: 'Лимит расходов не разрешает этот запрос. Бюджет не изменён.',
      invalid_api_key: 'Провайдер отклонил ключ. Проверьте подключение; ключ не сохранён в интерфейсе.', provider_auth_failed: 'Провайдер отклонил авторизацию. Проверьте ключ подключения.',
      endpoint_unavailable: 'Endpoint недоступен. Проверьте адрес и повторите проверку.', endpoint_not_allowed: 'Этот endpoint не разрешён сервером.',
      revision_conflict: 'Запись уже изменилась. Обновите её и проверьте новые данные перед повтором.', idempotency_conflict: 'Параметры повторного запроса изменились. Откройте действие заново после проверки истории.',
      external_blocked: 'Необходимое внешнее подключение недоступно. Действие не считается выполненным.',
    };
    if (Object.prototype.hasOwnProperty.call(messages, code)) return messages[code];
    if (error?.status === 403 || error?.status === 401) return 'Сервер не разрешил действие в текущем рабочем пространстве. Права и бюджет не изменены.';
    if (error?.status === 409) return 'Состояние изменилось или действие уже выполнено. Обновите запись перед повторной попыткой.';
    if (error?.status === 404 || error?.status === 503) return 'Действие или необходимый сервис сейчас недоступны. Это не успешное выполнение.';
    if (error?.status === 400 || error?.status === 422) return 'Сервер отклонил поля запроса. Проверьте значения, UUID и обязательные источники.';
    return 'Ответ сервера не подтверждён. Проверьте историю; повторная отправка использует тот же ключ и не создаёт дубликат.';
  }
  function publicJSON(value) {
    return JSON.stringify(value, (key, entry) => /(?:secret|password|api_?key|access_?token|authorization|cookie)/i.test(key) ? '[скрыто]' : entry, 2);
  }
  function evaluationMeta(agent) {
    const evaluation = agent?.evaluation || {};
    const sample = Math.max(0, Math.floor(number(evaluation.sample_size) || 0));
    const insufficient = sample < 3 || evaluation.confidence === 'insufficient' || number(evaluation.score_pct) == null;
    const confidence = { insufficient: 'недостаточно данных', low: 'низкая', medium: 'средняя', high: 'высокая' }[evaluation.confidence] || 'не оценена';
    return { sample, score: insufficient ? null : number(evaluation.score_pct), label: insufficient ? 'NEW' : pct(evaluation.score_pct), confidence, insufficient, observed: number(evaluation.observed_score_pct), mode: String(evaluation.mode || evaluation.scope || '') };
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
    const kind = value?.synthetic === false ? String(value?.source_kind || '') : '';
    const labels = { ninjatrader_report: 'NinjaTrader · исходный отчёт', desktop_chart: 'Рабочий стол · снимок графика', runtime_observation: 'Local · наблюдение runtime', real_model_response: 'Модель · фактический ответ' };
    const known = Object.prototype.hasOwnProperty.call(labels, kind);
    const job = String(value?.source_job_id || '');
    const reportUrl = kind === 'ninjatrader_report' && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(job) ? '/ui/backtesting.html?job=' + encodeURIComponent(job) : '';
    return { label: known ? labels[kind] : 'Источник не подтверждён', kind: known ? kind : 'unknown', reportUrl };
  }
  function overviewOutcomes(data) {
    if (Array.isArray(data?.outcomes)) return data.outcomes;
    // A completed task summary is real stored evidence, not an invented chart or score.
    return rows(data?.tasks).filter(task => ['succeeded', 'completed', 'verified'].includes(task.status)).slice(0, 3).map(task => ({
      title: task.title, summary: task.summary || '', task_id: taskId(task), status: task.status,
      synthetic: task.synthetic, source_kind: task.source_kind, source_job_id: task.source_job_id,
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
    const groups = { active: ['running', 'working', 'active', 'ready', 'queued'], waiting: ['planned', 'ready', 'queued', 'waiting', 'pending', 'paused'], review: ['review', 'awaiting_owner', 'approval_required', 'court', 'blocked'], completed: ['succeeded', 'completed'], failed: ['failed', 'rejected', 'cancelled'] };
    if (filter && filter !== 'all' && !(groups[filter] || [filter]).includes(String(task.status || ''))) return false;
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
  if (typeof module === 'object' && module.exports) { module.exports = { esc, number, count, pct, date, statusMeta, badge, rows, items, taskMatches, evaluationMeta, safeArtifactUrl, sourceMeta, overviewOutcomes, realChatCommands, canRunDemo, flagRows, captureChart, knownDomain, allowedDomainActions, domainFormFields, domainPayload, actionLabel, domainError, publicJSON }; return; }

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
    const signal = UI.signal();
    const capability = key => overview?.enabled === true && overview?.capabilities?.[key] === true;
    const actor = value => typeof value === 'object' && value ? value : { display_name: String(value || 'Не назначен') };
    const content = qs('#aw-content');
    const empty = (title, message, action) => `<div class="aw-empty"><strong>${esc(title)}</strong><p>${esc(message)}</p>${action ? `<div class="aw-actions">${action}</div>` : ''}</div>`;
    const smallEmpty = message => `<div class="aw-small-empty">${esc(message)}</div>`;
    const panel = (title, body, extra) => `<section class="aw-panel"><header class="aw-panel-heading"><h2>${esc(title)}</h2>${extra || ''}</header><div class="aw-panel-body">${body}</div></section>`;
    const note = text => `<p class="aw-note">${esc(text)}</p>`;
    const taskLink = (id, label) => id ? `<button class="aw-link-button" data-aw-task="${esc(id)}">${esc(label || 'Открыть задачу')} →</button>` : '';
    const avatar = (value, size) => {
      const person = actor(value), key = String(person.avatar_key || person.key || person.legacy_id || '');
      const approved = ['vitek', 'marina', 'tolik', 'nikita', 'ivan', 'manager', 'secretary', 'deputy'];
      const image = approved.includes(key) && UI.agentAvatarHtml ? UI.agentAvatarHtml(key, { size: 'sm' }) : esc(name(person).slice(0, 1).toLocaleUpperCase('ru-RU'));
      return `<span class="aw-avatar${size ? ` aw-avatar-${esc(size)}` : ''}" aria-hidden="true">${image}</span>`;
    };
    const progress = task => number(task.progress_pct) == null ? '<span class="aw-muted">Прогресс не измерен</span>' : `<span class="aw-progress"><progress max="100" value="${Math.min(100, Math.max(0, number(task.progress_pct)))}" aria-label="Выполнено ${esc(pct(task.progress_pct))}"></progress><span>${esc(pct(task.progress_pct))}</span></span>`;
    const cost = value => number(value) == null ? 'не измерено' : Number(value).toLocaleString('ru-RU', { style: 'currency', currency: 'USD', maximumFractionDigits: Number(value) > 0 && Number(value) < 0.0001 ? 8 : 4 });
    function announce(message, error) {
      const box = qs('#aw-notice'); box.textContent = message; box.hidden = !message; box.classList.toggle('aw-error', Boolean(error));
    }
    function refreshFaces(parent) { if (UI.wireAgentFaces) UI.wireAgentFaces(parent || shell); }
    function taskCard(task) {
      return `<button class="aw-task-card" data-aw-task="${esc(taskId(task))}"><span class="aw-task-card-top">${avatar(task.lead, 'sm')}<span class="aw-task-main"><span class="aw-task-title">${esc(task.title || 'Задача')}</span><span class="aw-task-stage">${esc(stageName(task.stage) || task.summary || 'Ожидает исполнения')}</span></span></span><span class="aw-task-meta"><span>Координатор: ${esc(name(task.lead))}</span><span>${esc(date(task.updated_at || task.created_at, true))}</span></span><span class="aw-task-foot">${badge(task.status)}${progress(task)}</span></button>`;
    }
    function agentMini(agent) {
      const evaluation = evaluationMeta(agent);
      return `<button class="aw-agent-mini" data-aw-agent="${esc(agentId(agent))}" title="${esc(name(agent))}: ${esc(evaluation.label)}, выборка ${count(evaluation.sample)}, уверенность ${esc(evaluation.confidence)}"><span class="aw-agent-mini-top">${avatar(agent)}<span class="aw-agent-identity"><span class="aw-agent-name">${esc(name(agent))}</span><span class="aw-agent-role">${esc(role(agent))}</span></span><span class="aw-rating-mini"><strong>${esc(evaluation.label)}</strong><small>n = ${count(evaluation.sample)}</small></span></span><span class="aw-agent-mini-foot">${badge(agent.status || 'free')}<span>${esc(agent.current_task?.title || agent.current_task_title || 'Нет активной задачи')}</span></span></button>`;
    }
    function timeline(events, full) {
      if (!events.length) return smallEmpty('Пока нет событий. Здесь появится история фактических действий, проверок и результатов.');
      const time = event => event.timestamp || event.created_at || event.at || event.time;
      return `<ol class="aw-timeline">${events.map(event => `<li><time datetime="${esc(time(event) || '')}" title="${esc(date(time(event)))}">${esc(date(time(event), !full))}</time><div><span>${esc(event.summary || event.title || event.event_type || event.type || 'Событие')}</span>${event.detail ? `<p>${esc(event.detail)}</p>` : ''}${event.task_id ? `<div>${taskLink(event.task_id)}</div>` : ''}</div></li>`).join('')}</ol>`;
    }
    function outcomeCard(outcome, index) {
      const source = sourceMeta(outcome), artifact = outcome.artifact || {}, url = safeArtifactUrl(artifact.url, source.kind);
      const image = (index === 0 || source.kind === 'desktop_chart') && url && ['image/svg+xml', 'image/png', 'image/jpeg', 'image/webp'].includes(artifact.media_type || artifact.mime_type);
      return `<article class="aw-outcome"><div class="aw-outcome-meta"><span class="aw-source aw-source-${esc(source.kind)}">${esc(source.label)}</span>${outcome.status ? badge(outcome.status) : ''}</div><h3>${esc(outcome.title || 'Результат задачи')}</h3>${outcome.summary ? `<p>${esc(outcome.summary)}</p>` : ''}${image ? `<a class="aw-outcome-image" href="${esc(url)}" target="_blank" rel="noopener noreferrer"><img src="${esc(url)}" alt="${esc(artifact.title || outcome.title || 'Артефакт результата')}" loading="lazy" referrerpolicy="same-origin"></a>` : ''}<div class="aw-outcome-foot"><div class="aw-actions">${taskLink(outcome.task_id, 'Результат и действия')}${source.reportUrl ? `<a class="aw-link-button" href="${esc(source.reportUrl)}">Открыть исходный отчёт ↗</a>` : ''}</div><time datetime="${esc(outcome.created_at || '')}">${esc(date(outcome.created_at, true))}</time></div></article>`;
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
      const active = tasks.filter(task => ['running', 'working', 'active', 'ready', 'queued', 'review', 'blocked', 'planned'].includes(task.status));
      const shown = (active.length ? active : tasks).slice(0, 3), outcomes = overviewOutcomes(overview).slice(0, 3);
      const attentionKnown = Array.isArray(overview.attention), alerts = rows(overview.attention).filter(item => !['info', 'healthy'].includes(item.severity || item.status));
      const alertsBody = alerts.length ? `<div class="aw-stack">${alerts.slice(0, 3).map(item => `<div class="aw-alert"><div>${badge(item.severity || item.status || 'warning')}</div><div><strong>${esc(item.title || item.summary)}</strong>${item.detail ? `<p>${esc(item.detail)}</p>` : ''}${taskLink(item.task_id)}</div></div>`).join('')}</div>` : attentionKnown && number(stats.attention) === 0 ? `<div class="aw-attention-clear">${badge('healthy')}<span>Сервер не сообщает об ошибках или ожидающих подтверждениях.</span></div>` : smallEmpty('Сводка подтверждений пока не опубликована. Отсутствие данных не означает, что все проверки пройдены.');
      const metrics = [
        ['В работе', stats.active_tasks, 'Активные задачи'], ['Завершено', stats.completed_tasks, 'Сохранённые результаты'],
        ['Команда', stats.agents ?? agents.length, 'Persona, не модели'], ['Требуют внимания', stats.attention, 'Ошибки и подтверждения'],
      ].map(([label, value, caption]) => `<div class="aw-metric"><div class="aw-metric-label">${esc(label)}</div><div class="aw-metric-value">${count(value)}</div><div class="aw-metric-note">${esc(caption)}</div></div>`).join('');
      content.innerHTML = `<div class="aw-rollup" aria-label="Сводка текущего рабочего пространства">${metrics}</div><div class="aw-overview"><div class="aw-column aw-column-work">${panel(active.length ? 'Сейчас в работе' : 'Последняя работа', shown.length ? `<div class="aw-stack">${shown.map(taskCard).join('')}</div>` : smallEmpty('Задач ещё нет. Откройте SF Chat или запустите разрешённую проверку.'), '<button class="aw-link-button" data-aw-tab="work">Все задачи →</button>')}${realWorkHint()}${panel('Требует внимания', alertsBody)}</div><div class="aw-column aw-column-results">${panel('Результаты и исходные данные', outcomes.length ? `<div class="aw-outcomes">${outcomes.map(outcomeCard).join('')}</div>` : smallEmpty('Пока нет сохранённых результатов. Здесь появятся отчёты, снимки и выполненные задачи с указанным источником.'))}${panel('Последние действия', timeline(rows(overview.activity).slice(0, 4), false))}</div><div class="aw-column aw-column-team">${panel('Команда и рейтинг', agents.length ? `<div class="aw-team">${agents.slice(0, 6).map(agentMini).join('')}</div><p class="aw-rating-note">n — размер выборки. NEW — данных недостаточно. Оценки относятся к классу задач; synthetic-проверка не оценивает качество LLM.</p>` : smallEmpty('В этом рабочем пространстве пока нет агентов.'), '<button class="aw-link-button" data-aw-tab="agents">Вся команда →</button>')}${foundationCard()}</div></div>`;
    }
    function taskTable(tasks) {
      if (!tasks.length) return empty('Задач по этому фильтру нет', 'Измените фильтр или запустите проверочный сценарий. Новые задачи появятся после записи на сервере.');
      return `<div class="aw-table-wrap"><table class="aw-table"><thead><tr><th>Задача / класс</th><th>Координатор</th><th>Участники</th><th>Этап</th><th>Прогресс</th><th>Статус</th><th>Обновлено</th><th>Стоимость</th></tr></thead><tbody>${tasks.map(task => `<tr><td><button class="aw-table-title" data-aw-task="${esc(taskId(task))}">${esc(task.title || 'Задача')}</button><div class="aw-table-sub">${esc(task.task_class || 'Класс не указан')}${task.synthetic ? ' · SYNTHETIC' : ''}</div></td><td><span class="aw-people">${avatar(task.lead, 'sm')}${esc(name(task.lead))}</span></td><td><span class="aw-faces" title="${esc(rows(task.participants).map(name).join(', '))}">${rows(task.participants).slice(0, 4).map(person => avatar(person, 'sm')).join('')}</span><span class="aw-muted">${task.participants?.length ? '' : '—'}</span></td><td>${esc(task.stage || '—')}</td><td>${progress(task)}</td><td>${badge(task.status)}</td><td>${esc(date(task.updated_at || task.created_at))}</td><td>${esc(cost(task.cost_usd))}</td></tr>`).join('')}</tbody></table></div>`;
    }
    function renderWork() {
      const filters = { all: 'Все', active: 'Активные', waiting: 'Ожидают', review: 'Требуют решения', completed: 'Завершённые', failed: 'Ошибки' };
      content.innerHTML = `<div class="aw-section-heading"><div><h2>Работа команды</h2><p>От постановки задачи до результата: участники, действия, проверки и артефакты.</p></div></div><div class="aw-toolbar"><div class="aw-filters" aria-label="Фильтр задач">${Object.entries(filters).map(([key, label]) => `<button class="aw-filter" data-aw-filter="${key}" aria-pressed="${filter === key}">${label}</button>`).join('')}</div><input type="search" id="aw-task-search" class="aw-search" placeholder="Найти задачу или агента…" aria-label="Поиск задач" maxlength="160" value="${esc(query)}"></div><div id="aw-work-table">${taskTable(workRows.filter(task => taskMatches(task, filter, query)))}</div>${nextCursor ? '<div class="aw-pagination"><button class="btn" id="aw-load-more">Показать ещё</button></div>' : ''}`;
    }
    function agentCard(agent) {
      const evaluation = evaluationMeta(agent);
      return `<article class="aw-agent-card"><div class="aw-agent-card-top">${avatar(agent)}<div><div class="aw-agent-name">${esc(name(agent))}</div><div class="aw-agent-role">${esc(role(agent))}</div></div></div>${badge(agent.status || 'free')}<div class="aw-agent-score"><small>Результат проверок${agent.synthetic === true ? ' · SYNTHETIC' : ''}</small><strong>${esc(evaluation.label)}</strong><small>${evaluation.insufficient ? 'Недостаточно сопоставимых наблюдений' : 'Проверенные критерии, не качество LLM'}</small><div class="aw-agent-meta"><span>Выборка: ${count(evaluation.sample)}</span><span>Уверенность: ${esc(evaluation.confidence)}</span></div></div><div class="aw-agent-assignment">${esc(agent.current_task?.title || agent.current_task_title || 'Нет активной задачи')}</div><div class="aw-actions"><button class="aw-link-button" data-aw-agent="${esc(agentId(agent))}">Профиль и рейтинг →</button></div></article>`;
    }
    function renderAgents() {
      const agents = rows(overview.agents);
      content.innerHTML = `<div class="aw-section-heading"><div><h2>Ваша команда</h2><p>Persona — имя, лицо и голос. Роль определяет обязанности; модель выбирается отдельно и не меняет личность агента.</p></div><div class="aw-actions"><button class="btn" data-aw-domain="personas">Создать / изменить Persona</button><button class="btn" data-aw-domain="models">Подключить свою модель</button></div></div>${agents.length ? `<div class="aw-agent-grid">${agents.map(agentCard).join('')}</div>` : empty('Команда пока пуста', 'Создайте персону и подключите свою модель через инструменты этого рабочего пространства.')}<div class="aw-note">Проверочный рейтинг — результат измеренных критериев конкретного класса задач. Сравнивайте только одинаковые классы и окна наблюдения. SYNTHETIC не оценивает качество внешней модели и не влияет на рабочую маршрутизацию.</div>${panel('Проверочный рейтинг', agents.length ? `<div class="aw-table-wrap"><table class="aw-table"><thead><tr><th>Агент / роль</th><th>Класс задачи</th><th>Наблюдения</th><th>Результат</th><th>Уверенность</th></tr></thead><tbody>${agents.map(agent => { const evaluation = evaluationMeta(agent); return `<tr><td><button class="aw-table-title" data-aw-agent="${esc(agentId(agent))}">${esc(name(agent))}</button><div class="aw-table-sub">${esc(role(agent))}</div></td><td>${esc(agent.evaluation?.task_class || '—')}</td><td>n = ${count(evaluation.sample)}</td><td>${esc(evaluation.label)}</td><td>${esc(evaluation.confidence)}</td></tr>`; }).join('')}</tbody></table></div>` : smallEmpty('Оценки не выставлены. Нулевая выборка не означает нулевое качество.'))}`;
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
    function selectTab(next, updateLocation) {
      if (!TABS.includes(next)) next = 'overview';
      tab = next;
      qsa('.aw-tabs [data-aw-tab]', shell).forEach(button => { const active = button.dataset.awTab === tab; button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1; });
      content.setAttribute('aria-labelledby', 'aw-tab-' + tab);
      if (updateLocation) root.history.replaceState(null, '', '#tab=' + encodeURIComponent(tab));
      return loadTab();
    }
    function readError(error) {
      if (error?.status === 403) return empty('Нет доступа к этому разделу', 'Сервер не разрешил чтение данных в текущем контексте. Обновите страницу после изменения доступа.');
      if (error?.status === 404) return empty('Раздел недоступен', 'Этот путь пока не включён в текущем локальном build.', '<button class="btn" data-aw-retry>Проверить снова</button>');
      return empty('Не удалось загрузить данные', 'Сохранённые записи не изменены. Повторите безопасное чтение.', '<button class="btn" data-aw-retry>Повторить</button>');
    }
    async function loadTab(append) {
      const request = ++generation;
      if (!overview?.enabled) {
        content.innerHTML = empty('AI Центр пока выключен', 'Новый интерфейс включается сервером для конкретного окружения и рабочего пространства. Текущие AI Lab и подключения остаются доступны.', '<a class="btn" href="ai-lab.html">Исследования</a><a class="btn" href="ai-agents.html">Подключения и модели</a>');
        content.setAttribute('aria-busy', 'false'); return;
      }
      content.setAttribute('aria-busy', 'true');
      try {
        if (tab === 'overview') renderOverview();
        else if (tab === 'agents') renderAgents();
        else if (tab === 'work') {
          const result = await API.aiControlCenterTasks({ limit: 50, status: filter === 'all' ? '' : filter, query, cursor: append ? nextCursor : '' }, { signal });
          if (request !== generation || disposed) return;
          workRows = append ? workRows.concat(items(result)) : items(result);
          nextCursor = result?.next_cursor || null;
          renderWork();
        }
        refreshFaces();
      } catch (error) {
        if (error?.name !== 'AbortError' && request === generation && !disposed) content.innerHTML = readError(error);
      } finally { if (request === generation && !disposed) content.setAttribute('aria-busy', 'false'); }
    }
    async function refresh() {
      const request = ++overviewGeneration;
      qs('#aw-refresh').disabled = true;
      try {
        const result = await API.aiControlCenterOverview({ signal });
        if (disposed || request !== overviewGeneration) return;
        const identity = value => JSON.stringify([value?.scope?.environment, value?.scope?.workspace_id, value?.scope?.user_uuid, value?.scope?.synthetic]);
        if (overview && identity(result) !== identity(overview)) {
          ++detailGeneration; detail = null; profile = null; domainState = null; actionForm = null; workRows = []; nextCursor = null; demoKey = null;
          if (currentDrawer?.querySelector('.aw-inspector')) UI.closeDrawer();
        }
        overview = result;
        renderHeader();
        await selectTab(tab, false);
      } catch (error) {
        if (error?.name !== 'AbortError' && !disposed && request === overviewGeneration) {
          ++detailGeneration; overview = null; detail = null; profile = null; domainState = null; actionForm = null; workRows = [];
          if (currentDrawer?.querySelector('.aw-inspector')) UI.closeDrawer();
          renderHeader(); content.innerHTML = readError(error); content.setAttribute('aria-busy', 'false');
        }
      } finally { if (!disposed && request === overviewGeneration) qs('#aw-refresh').disabled = false; }
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
      return values.map(value => `<section class="aw-panel"><div class="aw-panel-body"><div class="aw-inline"><strong>${esc(pct(value.score_pct ?? value.observed_score_pct))}</strong><span class="aw-muted">проверенных критериев этого ответа</span></div><p class="aw-note">${esc(value.scope || value.rubric_key || 'Класс конкретной задачи')} · ${esc(value.verifier || value.evaluator || 'Источник проверки не указан')}</p><div class="aw-stack">${rows(value.rubric || value.checks).map(check => `<div class="aw-inline">${badge(check.passed === true ? 'passed' : check.passed === false ? 'failed' : 'pending')}<span class="aw-text">${esc(check.label || check.key || check.summary)}</span></div>`).join('')}</div>${value.summary ? `<p class="aw-text">${esc(value.summary)}</p>` : ''}${value.response_sha256 ? `<div class="aw-hash">RESPONSE SHA256 ${esc(value.response_sha256)}</div>` : ''}${value.input_sha256 ? `<div class="aw-hash">INPUT SHA256 ${esc(value.input_sha256)}</div>` : ''}<p class="aw-field-hint">Проверка одного ответа не является общей оценкой качества модели или торговой стратегии.</p></div></section>`).join('');
    }
    function openDrawer(title, html) {
      if (!currentDrawer || !currentDrawer.classList.contains('open')) returnFocus = document.activeElement;
      currentDrawer = UI.drawer(`<h3>${esc(title)}</h3>`, `<div class="aw-inspector">${html}</div>`);
      currentDrawer.classList.add('wide');
      currentDrawer.setAttribute('role', 'dialog'); currentDrawer.setAttribute('aria-modal', 'true'); currentDrawer.setAttribute('aria-label', title); currentDrawer.tabIndex = -1;
      currentDrawer.focus();
      refreshFaces(currentDrawer);
      return currentDrawer;
    }
    const recordId = item => String(item?.id || item?.task_id || '');
    const recordValue = (item, key) => item?.[key] ?? item?.profile?.[key] ?? item?.schedule?.[key] ?? item?.packet?.[key];
    function domainNav(selected) {
      return `<nav class="aw-domain-nav" aria-label="Инструменты в панели">${Object.entries(DOMAINS).filter(([key]) => !['tasks', 'model_tasks'].includes(key)).map(([key, meta]) => `<button class="aw-filter" data-aw-domain="${key}" aria-pressed="${selected === key}">${esc(meta.title)}</button>`).join('')}</nav>`;
    }
    function domainLimitations(data) {
      const limits = rows(data?.limitations).map(item => typeof item === 'string' ? item : item.summary || item.message || '').filter(Boolean);
      return limits.length ? `<div class="aw-domain-limits"><strong>Ограничения текущего контура</strong><ul>${limits.map(text => `<li>${esc(text)}</li>`).join('')}</ul></div>` : '';
    }
    function domainActionButtons(item) {
      return allowedDomainActions(domainState?.data, item).map(action => `<button class="btn sm${['disconnect', 'revoke', 'archive', 'withdraw', 'cancel'].includes(action) ? ' aw-danger-action' : ''}" data-aw-domain-action="${esc(action)}" data-aw-entity="${esc(recordId(item))}">${esc(actionLabel(action))}</button>`).join('');
    }
    function domainItemCard(item) {
      const id = recordId(item), metrics = item.observed_eval || item.evaluation;
      const title = esc(item.title || item.label || item.name || item.model || 'Запись');
      const heading = domainState.key === 'system' ? `<strong>${title}</strong>` : `<button class="aw-table-title" data-aw-domain-item="${esc(id)}">${title}</button>`;
      return `<article class="aw-domain-card"><div class="aw-domain-card-head">${heading}${badge(item.status)}</div>${item.summary || item.description ? `<p class="aw-text">${esc(item.summary || item.description)}</p>` : ''}<div class="aw-domain-card-meta">${item.model ? `<span>Model: ${esc(item.model)}</span>` : ''}${item.provider ? `<span>${esc(item.provider)}</span>` : ''}${item.synthetic === true ? '<span class="aw-status aw-info">SYNTHETIC</span>' : ''}<time>${esc(date(item.updated_at || item.created_at))}</time></div>${domainState.key === 'models' ? `<p class="aw-field-hint">${item.connected === true ? 'Соединение подтверждено фактическим ответом.' : item.credentials_configured === true ? 'Ключ сохранён. Соединение ещё не подтверждено.' : 'Подключение отключено; ключ не используется.'}</p>` : ''}${metrics ? `<div class="aw-domain-card-meta"><span>Проверка ответа: ${esc(pct(metrics.score_pct ?? metrics.observed_score_pct))}</span>${number(metrics.sample_size) == null ? '' : `<span>n = ${count(metrics.sample_size)}</span>`}</div>` : ''}${item.result_text ? `<p class="aw-result-excerpt">${esc(String(item.result_text).slice(0, 240))}</p>` : ''}${domainState.key === 'system' && item.fields ? `<pre class="aw-result-text">${esc(publicJSON(item.fields))}</pre>` : ''}<div class="aw-actions">${domainActionButtons(item)}</div></article>`;
    }
    function drawDomain() {
      if (!domainState) return;
      const { key, data } = domainState, meta = DOMAINS[key];
      const permitted = allowedDomainActions(data), createAction = key === 'models' ? 'connect' : key === 'publications' ? 'prepare' : 'create';
      const create = (permitted.includes(createAction) ? `<button class="btn primary" data-aw-domain-action="${createAction}" data-aw-entity="new">+ ${esc(meta.create || actionLabel(createAction))}</button>` : '') + ['bind_existing', 'propose_consensus', 'suggest_routine'].filter(action => permitted.includes(action)).map(action => `<button class="btn" data-aw-domain-action="${action}" data-aw-entity="new">${esc(actionLabel(action))}</button>`).join('');
      const history = ['models', 'model_tasks', 'experiments'].includes(key) ? `<div class="aw-actions"><button class="aw-link-button" data-aw-domain="models">Подключения</button><button class="aw-link-button" data-aw-domain="model_tasks">История задач моделей</button><button class="aw-link-button" data-aw-domain="experiments">Сравнения</button></div>` : '';
      let body;
      if (data.enabled !== true) body = empty('Раздел не разрешён в текущем контексте', 'Функция не удалена из плана. Сервер не разрешил её использование; проверьте ограничения ниже.');
      else body = items(data).length ? `<div class="aw-domain-grid">${items(data).map(domainItemCard).join('')}</div>` : smallEmpty('Сохранённых записей пока нет. Новые записи появятся только после подтверждённого действия.');
      if (key === 'system') {
        const flags = flagRows(data.flags);
        if (flags.length) body += `<section class="aw-detail-section"><h3>Серверные флаги</h3><div class="aw-flag-list">${flags.map(flag => `<div class="aw-flag"><code>${esc(flag.name)}</code>${badge(flag.enabled ? 'active' : 'disabled')}</div>`).join('')}</div></section>`;
        if (data.budget) body += `<dl class="aw-detail-grid"><div><dt>Доступный лимит (USD)</dt><dd>${esc(cost(data.budget.remaining_usd))}</dd></div><div><dt>Измеренные расходы (USD)</dt><dd>${esc(cost(data.budget.spent_usd))}</dd></div></dl>`;
      }
      openDrawer(meta.title, `${domainNav(key)}<div class="aw-domain-heading"><div><h2>${esc(meta.title)}</h2><p>${esc(meta.description)}</p></div><div class="aw-actions">${create}<button class="btn" data-aw-domain-refresh>Обновить</button></div></div>${history}${domainLimitations(data)}${body}${data.next_cursor ? '<button class="btn" data-aw-domain-more>Показать ещё</button>' : ''}`);
    }
    async function openDomain(key, append) {
      if (!knownDomain(key) || overview?.enabled !== true || mutationBusy) return;
      const request = ++detailGeneration;
      const prior = append && domainState?.key === key ? domainState.data : null;
      actionForm = null; detailKind = 'domain';
      openDrawer(DOMAINS[key].title, domainNav(key) + smallEmpty('Загрузка записей текущего рабочего пространства…'));
      try {
        const data = await API.aiControlCenterDomain(key, { limit: 50, cursor: prior?.next_cursor || '' }, { signal });
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
      const fields = domainFormFields(key, key === 'models' ? 'connect' : 'create').filter(spec => spec.type !== 'password');
      const description = fields.filter(spec => recordValue(item, spec.key) !== undefined && recordValue(item, spec.key) !== null && recordValue(item, spec.key) !== '').map(spec => {
        const raw = recordValue(item, spec.key);
        const value = spec.type === 'datetime-local' ? date(raw) : typeof raw === 'object' ? publicJSON(raw) : String(raw);
        return `<div><dt>${esc(spec.label)}</dt><dd class="aw-pre-wrap">${esc(value)}</dd></div>`;
      }).join('');
      const verification = item.observed_eval || item.evaluation;
      const evaluationBody = verification ? evaluations([verification]) : '';
      const result = item.result_text || item.response_text || item.output_text;
      const resultBody = result ? `<section class="aw-detail-section"><h3>Фактический ответ</h3><pre class="aw-result-text">${esc(result)}</pre></section>` : '';
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
      openDrawer(meta.title + ' · ' + (item.title || item.label || item.name || 'Запись'), `${domainNav(key)}<div class="aw-actions"><button class="aw-link-button" data-aw-domain="${key}">← Все записи</button>${domainActionButtons(item)}${modelTaskLink}</div><h2 class="aw-inspector-title">${esc(item.title || item.label || item.name || item.model || 'Запись')}</h2><div class="aw-inline">${badge(item.status)}${item.synthetic === true ? '<span class="aw-status aw-info">SYNTHETIC</span>' : ''}</div>${domainLimitations(item)}${item.summary ? `<p class="aw-text">${esc(item.summary)}</p>` : ''}${metaFields}<dl class="aw-detail-grid">${description}</dl>${resultBody}${evaluationBody}${sourceBody}${versionBody}${courtBody}${comparisons}<div class="aw-hash">ID ${esc(recordId(item))}${item.correlation_id ? '<br>CORRELATION ' + esc(item.correlation_id) : ''}</div>`);
    }
    async function openDomainItem(id) {
      if (!domainState || !id || mutationBusy) return;
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
    function formField(spec, record, dependencies) {
      const id = 'aw-field-' + spec.key, prior = actionForm?.action === 'update' ? recordValue(record, spec.key) : undefined;
      let value = prior == null || spec.type === 'password' ? '' : Array.isArray(prior) ? prior.join('\n') : typeof prior === 'object' ? publicJSON(prior) : String(prior);
      if (spec.type === 'datetime-local' && value) { const parsed = new Date(value); if (Number.isFinite(parsed.getTime())) value = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
      const required = spec.required ? ' required' : '', attrs = `id="${id}" name="${esc(spec.key)}"${required}${spec.max && spec.type !== 'number' ? ` maxlength="${spec.max}"` : ''}`;
      let input;
      if (spec.type === 'publication-source') {
        const sources = rows(dependencies.collection?.source_candidates);
        input = `<select ${attrs}><option value="">Выберите проверенный источник</option>${sources.map(source => `<option value="${esc(source.source_kind + ':' + source.source_id)}">${esc(source.title || source.source_id)} · ${esc(source.source_kind)}</option>`).join('')}</select>`;
        if (!sources.length) input += '<p class="aw-field-hint">Проверенных источников ещё нет. Публикация станет доступной после сохранения и проверки результата.</p>';
      } else if (spec.type === 'records') {
        const candidates = rows(dependencies.collection?.[spec.source]);
        input = candidates.length ? `<div class="aw-choice-list">${candidates.map(source => `<label><input type="checkbox" name="${esc(spec.key)}" value="${esc(recordId(source))}"><span><strong>${esc(source.title || source.summary || 'Сохранённый результат')}</strong><small>${esc(recordId(source))}</small></span></label>`).join('')}</div>` : '<p class="aw-field-hint">Нет доступных подтверждённых источников. Сначала выполните и проверьте задачи.</p>';
        input += `<textarea id="${id}" name="${esc(spec.key)}_manual" rows="2" placeholder="Известные UUID источников" spellcheck="false">${esc(value)}</textarea>`;
      } else if (spec.type === 'evidence') {
        const sources = rows(dependencies.evidence).filter(item => item.media_type === 'application/json');
        input = sources.length ? `<div class="aw-choice-list">${sources.map(source => `<label><input type="checkbox" name="evidence_ids" value="${esc(recordId(source))}"><span><strong>${esc(source.title || 'JSON-доказательство')}</strong><small>${esc(source.sha256 || recordId(source))}</small></span></label>`).join('')}</div>` : '<p class="aw-field-hint">Сохранённые JSON-доказательства пока не опубликованы. Выполните проверяемую задачу через модель или существующее бэктестирование.</p>';
        input += `<textarea id="${id}" name="evidence_ids_manual" rows="2" placeholder="Известные UUID (необязательно при выборе выше)" spellcheck="false">${esc(value)}</textarea>`;
      } else if (spec.type === 'models') {
        const models = items(dependencies.models).filter(model => model.connected === true && !['disconnected', 'archived', 'disabled'].includes(model.status));
        input = models.length ? `<div class="aw-choice-list">${models.map(model => `<label><input type="checkbox" name="${esc(spec.key)}" value="${esc(recordId(model))}"><span><strong>${esc(model.label || model.model)}</strong><small>${esc(model.provider || '')} · ${esc(model.model || '')}</small></span></label>`).join('')}</div>` : '<div class="aw-small-empty">Нет доступных подключений. Сначала подключите и проверьте модели.</div><button type="button" class="aw-link-button" data-aw-domain="models">Открыть подключения →</button>';
      } else if (['select', 'persona', 'provider', 'binding'].includes(spec.type)) {
        const options = spec.type === 'persona' ? items(dependencies.personas).filter(person => person.status === 'active').map(person => [recordId(person), person.name || person.title]) : spec.type === 'provider' ? rows(dependencies.models?.providers).map(provider => [provider.id, provider.label]) : spec.type === 'binding' ? rows(dependencies.models?.owner_bindings).map(binding => [binding.id, (binding.name || binding.id) + ' · ' + (binding.provider || '') + ' / ' + (binding.model || '')]) : spec.options;
        input = `<select ${attrs}>${['persona', 'binding'].includes(spec.type) ? '<option value="">Выберите запись</option>' : ''}${options.map(([key, label]) => `<option value="${esc(key)}"${value === key ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select>`;
        if (spec.type === 'persona' && !options.length) input += '<p class="aw-field-hint">Сначала создайте и активируйте Persona в этом рабочем пространстве.</p><button type="button" class="aw-link-button" data-aw-domain="personas">Создать / активировать Persona →</button>';
        if (spec.type === 'provider' && !options.length) input += '<p class="aw-field-hint">Сервер не предоставил доступных провайдеров.</p>';
        if (spec.type === 'binding' && !options.length) input += '<p class="aw-field-hint">Нет разрешённых настроенных подключений владельца. Глобальные ключи не запрашиваются и не показываются.</p>';
      } else if (['textarea', 'ids', 'json'].includes(spec.type)) input = `<textarea ${attrs} rows="${spec.type === 'ids' ? 3 : 4}" spellcheck="${spec.type === 'textarea' ? 'true' : 'false'}">${esc(value)}</textarea>`;
      else input = `<input ${attrs} type="${spec.type}" value="${esc(value)}"${spec.type === 'number' ? ` min="${spec.min}" max="${spec.max}" step="1"` : ''}${spec.type === 'password' ? ' autocomplete="new-password" spellcheck="false" autocapitalize="off"' : ' autocomplete="off"'}>`;
      return `<div class="aw-form-field"><label for="${id}">${esc(spec.label)}${spec.required ? ' <span aria-hidden="true">*</span>' : ''}</label>${input}${spec.hint ? `<p class="aw-field-hint">${esc(spec.hint)}</p>` : ''}</div>`;
    }
    async function openDomainAction(action, id, task) {
      const key = task ? 'tasks' : domainState?.key;
      const record = task || (id === 'new' ? null : domainState?.item && recordId(domainState.item) === id ? domainState.item : items(domainState?.data).find(item => recordId(item) === id));
      const allowed = task ? rows(task.allowed_actions) : allowedDomainActions(domainState?.data, record);
      if (!key || !allowed.includes(action) || mutationBusy || id !== 'new' && !record) return;
      if (key === 'publications' && action === 'publish') return; // Only a validated, reviewed prepare response opens publishing.
      const request = ++detailGeneration;
      actionForm = { domain: key, action, item: record, id, key: root.crypto.randomUUID(), revision: number(record?.revision) };
      const specs = domainFormFields(key, action), dependencies = { models: key === 'models' ? domainState.data : null, evidence: domainState?.data.evidence_candidates, collection: domainState?.data };
      openDrawer(actionLabel(action), smallEmpty('Подготовка формы и проверка доступных записей…'));
      try {
        if (specs.some(spec => spec.type === 'persona')) dependencies.personas = await API.aiControlCenterDomain('personas', { limit: 100 }, { signal });
        if (specs.some(spec => spec.type === 'models')) dependencies.models = await API.aiControlCenterDomain('models', { limit: 100 }, { signal });
        if (disposed || request !== detailGeneration) return;
        const external = ['test', 'task', 'review'].includes(action) || key === 'experiments';
        const confirm = external ? 'Разрешаю отправить это задание выбранным подключениям в пределах существующего бюджета.' : action === 'publish_to_workspace' ? 'Разрешаю участникам этого рабочего пространства читать содержание и происхождение опубликованной записи.' : ['archive', 'revoke', 'withdraw', 'disconnect', 'cancel', 'dismiss', 'suspend'].includes(action) ? 'Подтверждаю это изменение выбранной записи.' : '';
        const warning = external ? note('Будут использованы реальные подключения. Измеренная стоимость может быть неизвестна до ответа; сервер проверяет существующий бюджет. Не отправляйте секреты или личные данные.') : action === 'publish_to_workspace' ? note('Будет создана отдельная общая запись в текущем workspace. Личный источник сохраняется. Не публикуйте секреты или чужие личные данные; отзыв общей записи или её источника прекращает доступ.') : action === 'bind_existing' ? note('Только связь с одним существующим разрешённым Local-подключением. Ключ не копируется; новый бюджет не создаётся. Отключение связи не удаляет исходное подключение владельца.') : key === 'routines' || key === 'calendar' ? note('Это запись предложения / события, не запуск фонового исполнителя. Автоматизация остаётся выключенной.') : '';
        const back = key === 'tasks' ? `<button type="button" class="btn" data-aw-task="${esc(id)}">Назад к задаче</button>` : `<button type="button" class="btn" data-aw-domain="${key}">Отмена</button>`;
        openDrawer(DOMAINS[key].title + ' · ' + actionLabel(action), `<div class="aw-domain-heading"><div><h2>${esc(actionLabel(action))}</h2><p>${esc(record?.title || record?.label || record?.name || DOMAINS[key].description)}</p></div></div>${warning}<form class="aw-form" id="aw-domain-form" autocomplete="off"><div class="aw-form-grid">${specs.map(spec => formField(spec, record, dependencies)).join('')}</div>${!specs.length ? '<p class="aw-text">Действие относится только к выбранной записи. История и права проверяются сервером.</p>' : ''}${confirm ? `<label class="aw-confirm"><input type="checkbox" name="confirmation" required><span>${esc(confirm)}</span></label>` : ''}<p class="aw-form-error" id="aw-form-error" role="alert" hidden></p><div class="aw-actions"><button type="submit" class="btn primary">${esc(actionLabel(action))}</button>${back}</div><p class="aw-field-hint">Ни workspace, ни права, ни бюджет не принимаются из формы. ${record ? 'Изменение привязано к ревизии ' + count(record.revision) + '.' : ''}</p></form>`);
      } catch (error) { if (error?.name !== 'AbortError' && request === detailGeneration && !disposed) openDrawer(actionLabel(action), readError(error)); }
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
        values[spec.key] = spec.type === 'models' ? qsa(`input[name="${spec.key}"]:checked`, form).map(input => input.value) : ['evidence', 'records'].includes(spec.type) ? qsa(`input[name="${spec.key}"]:checked`, form).map(input => input.value).concat(String(form.elements.namedItem(spec.key + '_manual')?.value || '').split(/[\s,]+/).filter(Boolean)) : form.elements.namedItem(spec.key)?.value || '';
      }
      let payload;
      try { payload = domainPayload(state.domain, state.action, values); }
      catch (error) { errorBox.textContent = error.message; errorBox.hidden = false; return; }
      if (state.domain === 'publications' && state.action === 'publish') {
        const publication = state.publication;
        if (!publication || !validPublicationPreview(publication.prepared, publication.source)) { errorBox.textContent = 'Сначала подготовьте и проверьте снимок публикации.'; errorBox.hidden = false; return; }
        payload = { ...payload, ...publication.source, approved_snapshot_sha256: publication.prepared.snapshot_sha256, confirm_permanent: true };
      }
      const body = { payload, idempotency_key: state.key };
      if (Number.isSafeInteger(state.revision) && state.revision >= 0) body.expected_revision = state.revision;
      mutationBusy = true; errorBox.hidden = true;
      qsa('button, input, select, textarea', form).forEach(input => { input.disabled = true; });
      try {
        const result = await API.aiControlCenterDomainAction(state.domain, state.id, state.action, body);
        if (disposed) return;
        if (result?.ok === false) throw { status: 409 };
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
        const keyInput = form.elements.namedItem('api_key'); if (keyInput) keyInput.value = '';
        mutationBusy = false;
        await refresh();
        const resultItem = result.item || result.task || result;
        announce(resultItem.status === 'failed' || resultItem.status === 'external_blocked' ? 'Сервер записал неуспешный результат. Откройте историю и ограничения.' : 'Ответ сервера сохранён. Проверьте состояние и результат записи; принятие запроса не означает завершение задачи.');
        if (state.domain === 'tasks') await openTask(taskId(resultItem) || state.id);
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
      const task = detail.task || detail, art = rows(detail.artifacts);
      const sourceKind = sourceMeta(task).kind;
      const labels = { summary: 'Обзор', activity: 'Активность', evidence: 'Evidence', agents: 'Агенты', evaluations: 'Оценка', artifacts: 'Артефакты', decisions: 'Решения', errors: 'Ошибки' };
      const svg = art.find(value => safeArtifactUrl(value.url) && (value.media_type || value.mime_type) === 'image/svg+xml');
      let body;
      if (detailTab === 'summary') body = `<div class="aw-inspector-summary"><h2 class="aw-inspector-title">${esc(task.title || 'Задача')}</h2><div class="aw-inline">${badge(task.status)}${task.synthetic ? '<span class="aw-status aw-info">SYNTHETIC · локальный обработчик</span>' : ''}</div><dl class="aw-detail-grid"><div><dt>Текущий этап</dt><dd>${esc(task.stage || '—')}</dd></div><div><dt>Координатор</dt><dd>${esc(name(task.lead))}</dd></div><div><dt>Класс задачи</dt><dd>${esc(task.task_class || '—')}</dd></div><div><dt>Измеренная стоимость</dt><dd>${esc(cost(task.cost_usd))}</dd></div><div><dt>Создана</dt><dd>${esc(date(task.created_at))}</dd></div><div><dt>Обновлена</dt><dd>${esc(date(task.updated_at))}</dd></div></dl>${progress(task)}${task.summary ? `<p class="aw-text">${esc(task.summary)}</p>` : ''}</div><section class="aw-detail-section"><h3>Проверяемый результат</h3>${detailRows(rows(detail.outcomes), 'Результат ещё не зафиксирован.')}</section>${art.length ? `<section class="aw-detail-section"><h3>Последний артефакт</h3>${artifacts(art.slice(-1), sourceKind)}</section>` : ''}<p class="aw-note">Здесь отображаются наблюдаемые действия и результаты. Скрытая цепочка рассуждений модели не публикуется.</p>`;
      else if (detailTab === 'activity') body = timeline(rows(detail.activity), true);
      else if (detailTab === 'evidence') body = detailRows(rows(detail.contributions), 'Проверяемые вклады ещё не записаны.') + artifacts(art, sourceKind);
      else if (detailTab === 'agents') body = `<div class="aw-stack">${rows(task.participants).map(person => `<div class="aw-detail-row"><div class="aw-people">${avatar(person)}<div><strong>${esc(name(person))}</strong><p>${esc(role(person))}</p></div></div>${agentId(person) ? `<button class="aw-link-button" data-aw-agent="${esc(agentId(person))}">Профиль →</button>` : ''}</div>`).join('') || smallEmpty('Участники ещё не назначены.')}</div>`;
      else if (detailTab === 'evaluations') body = evaluations(rows(detail.evaluations));
      else if (detailTab === 'artifacts') body = artifacts(art, sourceKind);
      else if (detailTab === 'decisions') body = detailRows(rows(detail.decisions), 'У этой задачи нет записанных решений. Проверочный сценарий не имитирует разрешение владельца или Court.');
      else body = detailRows(rows(detail.errors), task.status === 'failed' ? 'Подробности ошибки не опубликованы.' : 'Зарегистрированных ошибок нет.');
      if (detailTab === 'summary' && detail.result_text) body = `<div class="aw-context"><span class="aw-context-mark">РЕЗУЛЬТАТ</span><span>${esc(detail.result_text)}</span></div><div class="aw-detail-section">${body}</div>`;
      if (detailTab === 'summary' && task.source_kind === 'real_model_response') body += `<section class="aw-detail-section"><h3>Исполнитель и происхождение результата</h3><dl class="aw-detail-grid"><div><dt>Запрошенная модель</dt><dd>${esc(task.model || 'Не предоставлена')}</dd></div><div><dt>Model ID от провайдера</dt><dd>${esc(detail.actual_model || 'Не предоставлен')}</dd></div><div><dt>Провайдер</dt><dd>${esc(task.provider || 'Не предоставлен')}</dd></div></dl>${['intent_id', 'execution_id', 'contribution_id', 'outcome_id', 'evaluation_id', 'conversation_id', 'message_id'].filter(key => task[key]).map(key => `<div class="aw-hash">${esc(key.toUpperCase())} ${esc(task[key])}</div>`).join('')}</section>`;
      const taskActions = rows(task.allowed_actions).filter(action => ['cancel', 'retry'].includes(action)).map(action => `<button class="btn${action === 'cancel' ? ' aw-danger-action' : ''}" data-aw-task-action="${action}">${esc(actionLabel(action))}</button>`).join('');
      const controls = `<div class="aw-actions"><button class="btn" data-aw-task-chat="${esc(taskId(task))}">Открыть в SF Chat</button>${svg ? `<button class="btn primary" data-aw-chart-chat="${esc(taskId(task))}">Снимок графика → SF Chat</button>` : ''}${taskActions}</div>`;
      const tabs = `<nav class="aw-tabs" role="tablist" aria-label="Разделы задачи">${Object.entries(labels).map(([key, label]) => `<button role="tab" aria-selected="${detailTab === key}" tabindex="${detailTab === key ? 0 : -1}" data-aw-detail-tab="${key}">${label}</button>`).join('')}</nav>`;
      openDrawer('Задача · ' + (task.title || 'AI Центр'), `${controls}${tabs}<div role="tabpanel">${body}</div><div class="aw-hash">TASK ${esc(taskId(task))}${task.correlation_id ? `<br>CORRELATION ${esc(task.correlation_id)}` : ''}</div>`);
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
      else if (detailTab === 'rating') body = `<div class="aw-metrics"><div class="aw-metric"><div class="aw-metric-label">Результат проверок</div><div class="aw-metric-value">${esc(evaluation.label)}</div><div class="aw-metric-note">${evaluation.insufficient ? 'NEW · недостаточно наблюдений' : 'Критерии конкретного класса задач'}</div></div><div class="aw-metric"><div class="aw-metric-label">Размер выборки</div><div class="aw-metric-value">${count(evaluation.sample)}</div><div class="aw-metric-note">Уверенность: ${esc(evaluation.confidence)}</div></div></div><dl class="aw-detail-grid"><div><dt>Класс</dt><dd>${esc(found.evaluation?.task_class || '—')}</dd></div><div><dt>Окно наблюдений</dt><dd>${esc(found.evaluation?.window_label || 'Текущий локальный набор')}</dd></div><div><dt>Успешных проверок</dt><dd>${count(found.evaluation?.passed)}</dd></div><div><dt>Неуспешных проверок</dt><dd>${count(found.evaluation?.failed)}</dd></div></dl>${evaluation.insufficient && evaluation.observed != null ? note('Предварительное наблюдение: ' + pct(evaluation.observed) + '. Этого недостаточно для устойчивой оценки.') : ''}${note('Детерминированный synthetic benchmark не доказывает качество LLM и не повышает права агента. Оценки внешних моделей и реальной автономной работы ведутся отдельно.')}`;
      else if (detailTab === 'persona') body = `<dl class="aw-detail-grid"><div><dt>Persona</dt><dd>${esc(name(found))}</dd></div><div><dt>Agent Role</dt><dd>${esc(role(found))}</dd></div><div><dt>Голос</dt><dd>${esc(found.voice_label || 'Настройки существующего профиля')}</dd></div><div><dt>Model</dt><dd>${esc(found.model?.name || found.model || 'Назначается отдельно, не является Persona')}</dd></div></dl>${note('Смена модели не переименовывает агента, не меняет его историю и не выдаёт новые полномочия. Свои Persona создаются и редактируются в текущем рабочем пространстве.')}<div class="aw-actions"><button class="btn" data-aw-domain="personas">Управление Persona</button><button class="btn" data-aw-domain="models">Мои подключения</button></div>`;
      else body = `<div class="aw-inspector-summary"><h3>Роль и специализация</h3><p class="aw-text">${esc(found.description || found.specialization || role(found))}</p><dl class="aw-detail-grid"><div><dt>Текущая работа</dt><dd>${esc(found.current_task?.title || found.current_task_title || 'Нет активной задачи')}</dd></div><div><dt>Результат проверок</dt><dd>${esc(evaluation.label)} · n = ${count(evaluation.sample)}</dd></div><div><dt>Уверенность</dt><dd>${esc(evaluation.confidence)}</dd></div><div><dt>Контур</dt><dd>${found.synthetic ? 'Synthetic · детерминированные задачи' : 'Текущее рабочее пространство'}</dd></div></dl></div><section class="aw-detail-section"><h3>Последняя работа</h3>${tasks.length ? `<div class="aw-stack">${tasks.slice(0, 3).map(taskCard).join('')}</div>` : smallEmpty('Задач в текущей выборке нет.')}</section>`;
      openDrawer('Профиль · ' + name(found), `<div class="aw-profile-head">${avatar(found, 'lg')}<div><h2>${esc(name(found))}</h2><p class="aw-agent-role">${esc(role(found))}</p>${badge(found.status || 'free')}</div></div><nav class="aw-tabs" role="tablist" aria-label="Профиль агента">${Object.entries(labels).map(([key, label]) => `<button role="tab" aria-selected="${detailTab === key}" tabindex="${detailTab === key ? 0 : -1}" data-aw-profile-tab="${key}">${label}</button>`).join('')}</nav>${body}`);
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
    function click(event) {
      if (currentDrawer?.querySelector('.aw-inspector') && event.target.closest('.drawer-back, [data-close-drawer]')) { ++detailGeneration; actionForm = null; returnFocus?.focus?.(); return; }
      const target = event.target.closest('button, a');
      if (!target) return;
      const inside = shell.contains(target) || (currentDrawer && currentDrawer.contains(target) && target.closest('.aw-inspector'));
      if (!inside) return;
      if (target.dataset.awTab) selectTab(target.dataset.awTab, true);
      else if (target.dataset.awDomain) openDomain(target.dataset.awDomain);
      else if (target.dataset.awDomainItem) openDomainItem(target.dataset.awDomainItem);
      else if (target.dataset.awDomainAction) openDomainAction(target.dataset.awDomainAction, target.dataset.awEntity || 'new');
      else if (target.hasAttribute('data-aw-domain-refresh')) openDomain(domainState?.key);
      else if (target.hasAttribute('data-aw-domain-more')) openDomain(domainState?.key, true);
      else if (target.dataset.awModelTask) { openDomain('model_tasks').then(() => openDomainItem(target.dataset.awModelTask)); }
      else if (target.dataset.awTaskAction) { const task = detail?.task || detail; if (task) openDomainAction(target.dataset.awTaskAction, taskId(task), task); }
      else if (target.dataset.awTask) openTask(target.dataset.awTask);
      else if (target.dataset.awAgent) openProfile(target.dataset.awAgent);
      else if (target.dataset.awDetailTab) { detailTab = target.dataset.awDetailTab; drawTask(); qs('[data-aw-detail-tab][aria-selected="true"]', currentDrawer)?.focus(); }
      else if (target.dataset.awProfileTab) { openProfile(agentId(profile), target.dataset.awProfileTab); qs('[data-aw-profile-tab][aria-selected="true"]', currentDrawer)?.focus(); }
      else if (target.dataset.awTaskChat) taskChat(target.dataset.awTaskChat, false, target);
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
      if (event.key === 'Escape') { ++detailGeneration; actionForm = null; UI.closeDrawer(); returnFocus?.focus?.(); }
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
    qs('#aw-open-chat').addEventListener('click', () => UI.openSFChat({ conversationType: 'ai' }));
    UI.onLeave(() => { disposed = true; actionForm = null; domainState = null; ++generation; ++overviewGeneration; ++detailGeneration; root.clearTimeout(debounceTimer); document.removeEventListener('click', click); document.removeEventListener('keydown', keyboard); document.removeEventListener('submit', submitDomain); });
    const locationParams = new URLSearchParams(root.location.hash.replace(/^#/, ''));
    tab = TABS.includes(locationParams.get('tab')) ? locationParams.get('tab') : 'overview';
    await refresh();
    const linkedTask = locationParams.get('task') || new URLSearchParams(root.location.search).get('task');
    if (linkedTask && overview?.enabled) await openTask(linkedTask);
    else if (knownDomain(locationParams.get('domain')) && overview?.enabled) await openDomain(locationParams.get('domain'));
  });
})(typeof window !== 'undefined' ? window : globalThis);
