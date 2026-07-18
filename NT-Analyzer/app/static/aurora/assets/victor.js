/* Victor: owner-facing chief-of-staff surface shared by every Aurora page. */
(function () {
  'use strict';

  const PAGE_LABELS = {
    overview: 'Обзор', trading: 'Торговля', desktop: 'Рабочий стол',
    performance: 'Финансы', backtesting: 'Бэктест', strategies: 'Стратегии',
    'ai-lab': 'AI Lab', 'ai-agents': 'AI Agents', news: 'Новости',
    topstep: 'TopStep', documents: 'Документы',
  };
  const AGENT_LABELS = {
    vitek: 'Виктор', manager: 'Управляющий', orchestrator: 'Управляющий',
    marina: 'Марина', tolik: 'Толик', nikita: 'Никита', ivan: 'Иван',
  };
  const MODE_LABELS = {
    free: 'свободен', busy: 'работает', awaiting_decision: 'ждёт решения', needs_attention: 'нужно внимание', resting: 'отдыхает',
  };
  let state = null;
  let loading = false;
  let lastBackendInstance = '';
  try { lastBackendInstance = sessionStorage.getItem('victor.backendInstance') || ''; } catch (_) { /* ignore */ }

  function esc(value) { return UI.esc(String(value == null ? '' : value)); }
  function pageContext() {
    const page = document.body.dataset.page || 'overview';
    const label = PAGE_LABELS[page] || document.body.dataset.title || 'Приложение';
    return {
      page, entity_type: page, entity_id: '', entity_label: label,
      url: location.pathname + location.search,
    };
  }
  function isoFromLocal(value) {
    if (!value) return '';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
  }
  function fmtDate(value) {
    if (!value) return '';
    try { return new Date(value).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); }
    catch (_) { return String(value); }
  }
  function saveChat(conversationId) {
    try { localStorage.setItem('orch.currentConversationId', conversationId || 'default'); } catch (_) { /* ignore */ }
  }
  function openChat(conversationId) {
    saveChat(conversationId);
    UI.closeDrawer();
    UI.openOrchestrator();
  }
  function conversationId(result) {
    return String(result && result.conversation && result.conversation.conversation_id || '');
  }
  function budgetText(budget) {
    if (!budget || !Number(budget.amount || 0)) return '';
    return `${Number(budget.amount).toLocaleString('ru-RU')} ${esc(budget.currency || 'USD')}`;
  }

  async function createAssignment(input) {
    const title = String(input.title || '').trim();
    if (!title) throw new Error('Укажите, что нужно поручить Виктору.');
    const created = await API.http.aiOrchestratorCreateConversation(`Виктор · ${title}`.slice(0, 120));
    const cid = conversationId(created);
    if (!cid) throw new Error('Не удалось создать отдельный диалог для поручения.');
    const payload = {
      title,
      description: String(input.description || '').trim(),
      category: String(input.category || 'general'),
      priority: String(input.priority || 'normal'),
      status: 'planned',
      due_at_utc: input.due_at_utc || '',
      source: input.source || 'victor_ui',
      incident_id: input.incident_id || '',
      conversation_id: cid,
      auto_execute: false,
      context: input.context || pageContext(),
      budget: input.budget || {},
      control: input.control || {},
    };
    let taskDoc;
    try { taskDoc = await API.http.vitekTask(payload); }
    catch (error) {
      try { await API.http.aiOrchestratorDeleteConversation(cid); } catch (_) { /* best-effort rollback */ }
      throw error;
    }
    const task = taskDoc && taskDoc.task;
    if (!task || !task.task_id) throw new Error('Поручение не зарегистрировано.');
    // The backend converges repeated clicks/deliveries for one incident onto
    // one durable task. Do not keep the speculative conversation which this
    // request created when another request already won that race.
    const taskCid = String(task.conversation_id || cid);
    const replayed = Boolean(task.idempotent_replay || task._idempotent_replay);
    if (taskCid !== cid) {
      try { await API.http.aiOrchestratorDeleteConversation(cid); } catch (_) { /* best effort */ }
    }
    if (replayed) {
      saveChat(taskCid);
      return { conversation_id: taskCid, task, acknowledgement: null, recovered: true };
    }
    const details = [
      `Виктор, приступай к поручению: ${title}.`,
      payload.description ? `Комментарий: ${payload.description}` : '',
      payload.control && payload.control.condition ? `Контроль: ${payload.control.condition}` : '',
      payload.control && payload.control.report_frequency ? `Отчётность: ${payload.control.report_frequency}` : '',
      budgetText(payload.budget) ? `Бюджет: ${budgetText(payload.budget)}.` : '',
    ].filter(Boolean).join('\n');
    try {
      const acknowledgement = await API.http.aiOrchestratorMessage(details, taskCid, 'vitek');
      saveChat(taskCid);
      return { conversation_id: taskCid, task, acknowledgement };
    } catch (error) {
      // A dropped HTTP response does not prove that the server missed the
      // message.  Re-read durable state before rolling anything back.
      try {
        const current = await API.http.vitekStatus();
        const stored = (current.tasks || []).find(row => row.task_id === task.task_id);
        if (stored && stored.auto_execute && stored.status !== 'planned') {
          saveChat(taskCid);
          return { conversation_id: taskCid, task: stored, acknowledgement: null, recovered: true };
        }
      } catch (_) { /* preserve the original transport error */ }
      try { await API.http.vitekUpdateTask(task.task_id, { status: 'cancelled', result: 'Диалог поручения не был подтверждён.' }); } catch (_) { /* best effort */ }
      try { await API.http.aiOrchestratorDeleteConversation(cid); } catch (_) { /* best effort */ }
      throw error;
    }
  }

  function assignmentDrawer(context, defaults) {
    const ctx = Object.assign(pageContext(), context || {});
    const preset = defaults || {};
    const title = preset.title || `Разобраться с разделом «${ctx.entity_label || PAGE_LABELS[ctx.page] || 'Приложение'}»`;
    UI.drawer(
      '<div class="tb-title"><span class="tb-kicker">Виктор · личный помощник</span><span class="tb-h1">Новое поручение</span></div>',
      `<div class="col gap-lg">
        <div class="finance-note">Виктор создаст отдельный диалог, передаст работу Управляющему и вернёт итог в приложение и связанную тему Telegram.</div>
        <label class="field"><span>Что нужно сделать</span><input id="victor-task-title" maxlength="500" value="${esc(title)}"></label>
        <label class="field"><span>Комментарий и ожидаемый результат</span><textarea id="victor-task-notes" rows="5" maxlength="4000" placeholder="Например: проверить гипотезы, сравнить результаты и предложить решение">${esc(preset.description || '')}</textarea></label>
        <div class="grid cols-2">
          <label class="field"><span>Приоритет</span><select id="victor-task-priority"><option value="normal">Обычный</option><option value="high">Высокий</option><option value="critical">Критический</option></select></label>
          <label class="field"><span>Срок (необязательно)</span><input id="victor-task-due" type="datetime-local"></label>
        </div>
        <div class="grid cols-2">
          <label class="field"><span>Бюджет</span><input id="victor-task-budget" type="number" min="0" step="0.01" placeholder="0"></label>
          <label class="field"><span>Валюта</span><select id="victor-task-currency"><option>USD</option><option>EUR</option><option>RUB</option></select></label>
        </div>
        <label class="field"><span>Что контролировать во времени</span><textarea id="victor-task-control" rows="3" maxlength="2000" placeholder="Например: следить за MGC и сообщить при касании уровня 2400"></textarea></label>
        <label class="field"><span>Когда присылать отчёты</span><input id="victor-task-frequency" maxlength="120" placeholder="По событию, каждый час, в конце дня…"></label>
        <div class="finance-note"><strong>Контекст:</strong> ${esc(ctx.entity_label || PAGE_LABELS[ctx.page] || ctx.page)}${ctx.entity_id ? ` · ${esc(ctx.entity_id)}` : ''}</div>
        <button class="btn primary" id="victor-task-submit">Создать отдельный чат и поручить Виктору</button>
      </div>`
    );
    const priority = UI.qs('#victor-task-priority');
    if (priority) priority.value = preset.priority || 'normal';
    UI.qs('#victor-task-submit').onclick = async function () {
      const button = this;
      button.disabled = true;
      button.textContent = 'Передаю Виктору…';
      const due = isoFromLocal(UI.qs('#victor-task-due').value);
      const amount = Number(UI.qs('#victor-task-budget').value || 0);
      const control = UI.qs('#victor-task-control').value.trim();
      try {
        const result = await createAssignment({
          title: UI.qs('#victor-task-title').value.trim(),
          description: UI.qs('#victor-task-notes').value.trim(),
          priority: UI.qs('#victor-task-priority').value,
          due_at_utc: due,
          context: ctx,
          budget: amount > 0 ? { amount, currency: UI.qs('#victor-task-currency').value } : {},
          control: {
            condition: control,
            report_frequency: UI.qs('#victor-task-frequency').value.trim(),
            ends_at_utc: due,
          },
        });
        UI.toast('Виктор принял поручение');
        await refresh();
        openChat(result.conversation_id);
      } catch (error) {
        UI.reportError(error);
        button.disabled = false;
        button.textContent = 'Создать отдельный чат и поручить Виктору';
      }
    };
  }

  function planDrawer(scope, current) {
    const label = scope === 'week' ? 'неделю' : 'сегодня';
    const plan = current || {};
    const ctx = plan.context || {};
    UI.drawer(
      `<div class="tb-title"><span class="tb-kicker">Виктор · планирование</span><span class="tb-h1">План на ${label}</span></div>`,
      `<div class="col gap-lg">
        <label class="field"><span>Главный результат</span><input id="victor-plan-focus" maxlength="500" value="${esc(plan.focus || '')}" placeholder="Что должно быть достигнуто"></label>
        <label class="field"><span>Цели — по одной на строке</span><textarea id="victor-plan-goals" rows="7" maxlength="6000" placeholder="Проверить исследование&#10;Подготовить отчёт">${esc((plan.goals || []).join('\n'))}</textarea></label>
        <label class="field"><span>Ваш комментарий</span><textarea id="victor-plan-notes" rows="3" maxlength="4000">${esc(plan.notes || '')}</textarea></label>
        <div class="grid cols-2">
          <label class="field"><span>Связать с</span><select id="victor-plan-type"><option value="general">Общая задача</option><option value="strategy">Стратегия</option><option value="research">Исследование</option><option value="finance">Финансы</option><option value="chart">График / цена</option><option value="news">Новости</option></select></label>
          <label class="field"><span>Название или ссылка</span><input id="victor-plan-ref" maxlength="500" value="${esc(ctx.entity_label || '')}" placeholder="Например, MGC Morning"></label>
        </div>
        <div class="grid cols-2">
          <label class="field"><span>Бюджет</span><input id="victor-plan-budget" type="number" min="0" step="0.01" value="${plan.budget && plan.budget.amount || ''}"></label>
          <label class="field"><span>Контролировать до</span><input id="victor-plan-until" type="datetime-local"></label>
        </div>
        <label class="field"><span>Условие контроля</span><textarea id="victor-plan-control" rows="3" maxlength="2000" placeholder="Что отслеживать и когда сообщить">${esc(plan.control && plan.control.condition || '')}</textarea></label>
        <label class="field"><span>Периодичность отчёта</span><input id="victor-plan-frequency" maxlength="120" value="${esc(plan.control && plan.control.report_frequency || '')}" placeholder="По событию / ежедневно / в конце периода"></label>
        <button class="btn primary" id="victor-plan-submit">Сохранить и передать Виктору</button>
      </div>`
    );
    UI.qs('#victor-plan-type').value = ctx.entity_type || 'general';
    UI.qs('#victor-plan-submit').onclick = async function () {
      const button = this;
      const focus = UI.qs('#victor-plan-focus').value.trim();
      const goals = UI.qs('#victor-plan-goals').value.split(/\n|;/).map(row => row.trim()).filter(Boolean);
      if (!focus && !goals.length) { UI.toast('Укажите главный результат или хотя бы одну цель'); return; }
      button.disabled = true;
      try {
        const until = isoFromLocal(UI.qs('#victor-plan-until').value);
        const amount = Number(UI.qs('#victor-plan-budget').value || 0);
        const type = UI.qs('#victor-plan-type').value;
        const ref = UI.qs('#victor-plan-ref').value.trim();
        await API.http.vitekPlan({
          scope, focus: focus || goals[0], goals, notes: UI.qs('#victor-plan-notes').value.trim(),
          create_tasks: true, source: 'victor_overview', ends_at_utc: until,
          context: { page: document.body.dataset.page || 'overview', entity_type: type, entity_label: ref, url: location.pathname + location.search },
          budget: amount > 0 ? { amount, currency: 'USD' } : {},
          control: { condition: UI.qs('#victor-plan-control').value.trim(), report_frequency: UI.qs('#victor-plan-frequency').value.trim(), ends_at_utc: until },
        });
        UI.toast(`План на ${label} сохранён`);
        UI.closeDrawer();
        await refresh();
      } catch (error) { UI.reportError(error); button.disabled = false; }
    };
  }

  async function cleanupDrawer() {
    const preview = await API.http.vitekReconciliation();
    const counts = preview.counts || {};
    const labels = {
      duplicate_task: 'Дубли поручений', orphan_task: 'Поручения без инцидента',
      ghost_task_link: 'Потерянные связи', stalled_task: 'Зависшие без heartbeat',
      missing_blocking_reason: 'Блокировки без причины', backfill_result_id: 'Результаты без result_id',
      completed_without_result: 'Ложные завершения', defer_session_closed: 'Live-вопросы при закрытой сессии',
      retire_legacy_guard_failure: 'Старые отказы task guard', retire_executor_plan_failure: 'Исполнитель не вернул план',
      obsolete_unactivated_task: 'Неактивированные поручения',
      obsolete_stale_queued_task: 'Просроченные задачи в очереди', archive_terminal_task: 'Терминальные задачи к архивированию',
      obsolete_expired_incident: 'Вопросы с истёкшим TTL',
    };
    const rows = Object.entries(counts).map(([key, value]) => `<div class="row"><div class="row-main"><div class="row-title">${esc(labels[key] || key)}</div></div><span class="badge pending">${Number(value || 0)}</span></div>`).join('');
    UI.drawer(
      '<div class="tb-title"><span class="tb-kicker">Виктор · lifecycle manager</span><span class="tb-h1">Очистка поручений</span></div>',
      `<div class="col gap-lg"><div class="finance-note">Режим preview ничего не удаляет. Применение архивирует и меняет статусы с сохранением полного audit trail.</div><div class="kpi ${preview.action_count ? 'warn' : 'pos'}"><div class="kpi-label">Найдено действий</div><div class="kpi-val sm">${Number(preview.action_count || 0)}</div><div class="kpi-foot">Сессия: ${esc(preview.market_session_state || 'UNKNOWN')}</div></div><div class="list">${rows || '<div class="empty-state">Lifecycle согласован; очистка не требуется.</div>'}</div><button class="btn primary" id="victor-cleanup-apply" ${preview.action_count ? '' : 'disabled'}>Применить безопасную очистку</button></div>`,
    );
    const apply = UI.qs('#victor-cleanup-apply');
    if (apply) apply.onclick = async function () {
      this.disabled = true; this.textContent = 'Сверяю и архивирую…';
      try {
        const result = await API.http.vitekReconcile(true);
        UI.toast(`Очистка завершена: ${Number(result.action_count || 0)} действий, история сохранена`);
        UI.closeDrawer();
        await refresh();
      } catch (error) { this.disabled = false; this.textContent = 'Применить безопасную очистку'; UI.reportError(error); }
    };
  }

  async function taskAnswerDrawer(task) {
    const doc = await API.http.vitekTaskChoices(task.task_id);
    const choices = Array.isArray(doc.choices) ? doc.choices : [];
    const options = [
      '<option value="">Выберите стратегию…</option>',
      '<option value="__all__">Проверить все сохранённые стратегии</option>',
      ...choices.map((row, index) => `<option value="${index}">${esc([row.cell_id, row.name, row.instrument, row.latest_experiment_id].filter(Boolean).join(' · '))}</option>`),
    ].join('');
    UI.drawer(
      '<div class="tb-title"><span class="tb-kicker">Виктор · уточнение поручения</span><span class="tb-h1">Что именно проверить</span></div>',
      `<div class="col gap-lg"><div class="finance-note">${esc(doc.question || 'Выберите сохранённую стратегию или задайте уточнение.')}</div><label class="field"><span>Сохранённая стратегия</span><select id="victor-task-answer-choice">${options}</select></label><label class="field"><span>Дополнительное пояснение</span><textarea id="victor-task-answer-text" rows="4" maxlength="2000" placeholder="Например: только OOS за 2025 год"></textarea></label><button class="btn primary" id="victor-task-answer-submit">Продолжить это поручение</button></div>`,
    );
    UI.qs('#victor-task-answer-submit').onclick = async function () {
      const choice = UI.qs('#victor-task-answer-choice').value;
      const note = UI.qs('#victor-task-answer-text').value.trim();
      let answer = note;
      if (choice === '__all__') answer = ['Проверить все сохранённые стратегии.', note].filter(Boolean).join(' ');
      else if (choice !== '') {
        const row = choices[Number(choice)] || {};
        answer = [`Проверить стратегию ${row.name || row.profile_id || ''}.`, row.cell_id ? `CELL ${row.cell_id}.` : '', row.strategy_class ? `Класс ${row.strategy_class}.` : '', row.instrument ? `Инструмент ${row.instrument}.` : '', row.latest_experiment_id ? `Последний эксперимент ${row.latest_experiment_id}.` : '', note].filter(Boolean).join(' ');
      }
      if (!answer) { UI.toast('Выберите стратегию или напишите пояснение'); return; }
      this.disabled = true; this.textContent = 'Передаю ответ…';
      try { await API.http.vitekAnswerTask(task.task_id, answer); UI.closeDrawer(); UI.toast('Ответ принят; поручение продолжено'); await refresh(); }
      catch (error) { this.disabled = false; this.textContent = 'Продолжить это поручение'; UI.reportError(error); }
    };
  }

  async function acceptIncident(incident) {
    const response = await API.http.vitekIncidentDecision(
      incident.incident_id, 'create_task',
      'Владелец разрешил проверку. Исправление, restart и live-включение требуют отдельного разрешения.',
      ['audit'],
    );
    const decided = response && response.incident || response || {};
    const cid = String(decided.conversation_id || decided.task && decided.task.conversation_id || '');
    await refresh();
    UI.toast(decided.idempotent_replay ? 'Открываю уже созданное поручение' : 'Решение принято. Проверка поставлена в очередь');
    if (cid) openChat(cid);
  }

  function taskHtml(task) {
    const agent = AGENT_LABELS[task.assigned_agent] || task.assigned_agent || 'Управляющий назначает исполнителя';
    const context = task.context || {};
    const executionModel = String(task.execution_model || '');
    const routingModel = String(task.routing_model || '');
    const modelParts = [];
    if (routingModel && !['unknown', 'internal', 'deterministic task guard'].includes(routingModel.toLowerCase())) modelParts.push(`понимание: ${routingModel}`);
    if (executionModel && !['unknown', 'internal'].includes(executionModel.toLowerCase())) modelParts.push(`исполнение: ${executionModel}`);
    const provider = String(task.execution_provider || task.routing_provider || '');
    const modelLine = modelParts.length ? ` · ${esc(modelParts.join(' → '))}${provider ? ` (${esc(provider)})` : ''}` : '';
    const control = task.control && task.control.condition ? `<div class="row-sub">Контроль: ${esc(task.control.condition)}</div>` : '';
    const statusLabels = { new: 'принято', planned: 'в очереди', in_progress: 'выполняется', waiting_review: 'ждёт ответа', waiting_for_input: 'ждёт ответа', blocked: 'заблокировано', stalled: 'нет heartbeat' };
    const needsInput = ['waiting_review', 'waiting_for_input', 'awaiting_decision'].includes(task.status);
    return `<div class="row"><div class="row-main"><div class="row-title">${esc(task.owner_title || task.title || 'Поручение')}</div>
      <div class="row-sub mono">${esc(task.task_id || '')}${task.mission_id ? ` · ${esc(task.mission_id)}` : ''} · ${esc(statusLabels[task.status] || task.status || 'неизвестно')}</div>
      <div class="row-sub">${esc(agent)}${modelLine}${task.due_at_utc ? ` · срок ${esc(fmtDate(task.due_at_utc))}` : ''}</div>
      ${task.current_stage ? `<div class="row-sub">Этап: ${esc(task.current_stage)}${task.execution_heartbeat_at_utc ? ` · heartbeat ${esc(fmtDate(task.execution_heartbeat_at_utc))}` : ''}</div>` : ''}
      ${context.entity_label ? `<div class="row-sub">Связано с: ${esc(context.entity_label)}</div>` : ''}${control}</div>
      <div class="flex wrap gap-sm">${needsInput ? `<button class="btn sm primary" data-victor-answer-task="${esc(task.task_id)}">Уточнить</button>` : ''}${task.conversation_id ? `<button class="btn sm ghost" data-victor-open-chat="${esc(task.conversation_id)}">Чат</button>` : ''}<button class="btn sm ghost" data-victor-cancel-task="${esc(task.task_id)}" data-incident-id="${esc(task.incident_id || '')}">Отменить</button></div></div>`;
  }

  function centerSignature(doc) {
    if (!doc) return '';
    const agents = (doc.agent_activity || []).map((row) => ([
      row.agent_id || row.name, row.state, !!row.working, row.model || '', row.work || '',
    ]));
    const incidents = (doc.incidents || [])
      .filter((row) => ['awaiting_decision', 'acknowledged', 'in_progress'].includes(row.status) && row.owner_decision_required)
      .map((row) => [row.incident_id, row.status, (row.owner_brief || {}).fact || '']);
    const tasks = (doc.tasks || [])
      .filter((row) => ['new', 'awaiting_decision', 'planned', 'in_progress', 'waiting_review', 'waiting_for_input', 'blocked', 'stalled'].includes(row.status))
      .map((row) => [row.task_id, row.status, row.assigned_agent || '', row.owner_title || row.title || '']);
    const plans = doc.plans || {};
    return JSON.stringify({
      mode: doc.mode,
      message: doc.message || '',
      bg: !!(doc.background && doc.background.installed),
      parallel: Number(doc.event_engine && doc.event_engine.parallel_limit || 0),
      agents, incidents, tasks,
      day: plans.day && { status: plans.day.status, focus: plans.day.focus },
      week: plans.week && { status: plans.week.status, focus: plans.week.focus },
    });
  }

  function renderCenter(doc) {
    const center = UI.qs('[data-victor-center]');
    if (!center) return;
    const body = UI.qs('[data-victor-body]', center);
    const sig = centerSignature(doc);
    if (sig && sig === center.dataset.renderSig) {
      const rest = UI.qs('[data-victor-rest]', center); const resume = UI.qs('[data-victor-resume]', center);
      if (rest) rest.hidden = doc.mode === 'resting';
      if (resume) resume.hidden = doc.mode !== 'resting';
      return;
    }
    center.dataset.renderSig = sig;
    const tasks = (doc.tasks || []).filter(row => ['new', 'awaiting_decision', 'planned', 'in_progress', 'waiting_review', 'waiting_for_input', 'blocked', 'stalled'].includes(row.status));
    const incidents = (doc.incidents || []).filter(row => ['awaiting_decision', 'acknowledged', 'in_progress'].includes(row.status) && row.owner_decision_required);
    const agents = doc.agent_activity || [];
    const plans = doc.plans || {};
    body.innerHTML = `<div class="col gap-lg">
      <div class="grid cols-5">
        <div class="kpi ${doc.mode === 'free' ? 'pos' : 'info'}"><div class="kpi-label">Состояние</div><div class="kpi-val sm">${esc(MODE_LABELS[doc.mode] || doc.mode)}</div><div class="kpi-foot">личный контроль</div></div>
        <div class="kpi ${incidents.length ? 'warn' : 'pos'}"><div class="kpi-label">Нужен ваш ответ</div><div class="kpi-val sm">${incidents.length}</div><div class="kpi-foot">только важные решения</div></div>
        <div class="kpi ${Number(doc.task_counts && doc.task_counts.running || 0) ? 'info' : 'pos'}"><div class="kpi-label">Выполняются / в очереди</div><div class="kpi-val sm">${Number(doc.task_counts && doc.task_counts.running || 0)}</div><div class="kpi-foot">ждут ответа: ${Number(doc.task_counts && doc.task_counts.waiting_for_input || 0)} · blocked: ${Number(doc.task_counts && doc.task_counts.blocked_total || 0)}</div></div>
        <div class="kpi ${agents.some(row => row.working) ? 'info' : 'pos'}"><div class="kpi-label">Команда работает</div><div class="kpi-val sm">${agents.filter(row => row.working).length}</div><div class="kpi-foot">до ${Number(doc.event_engine && doc.event_engine.parallel_limit || 6)} одновременно</div></div>
        <div class="kpi ${doc.background && doc.background.installed ? 'pos' : 'warn'}"><div class="kpi-label">Фоновый контроль</div><div class="kpi-val sm">${doc.background && doc.background.installed ? 'включён' : 'не установлен'}</div><div class="kpi-foot">событийный режим</div></div>
      </div>
      <div class="finance-note"><strong>Виктор:</strong> ${esc(doc.message || 'Готов принять поручение.')}<div class="row-sub">Торговая сессия: ${esc(doc.market_session_state || 'UNKNOWN')}${doc.last_recovery && doc.last_recovery.at_utc ? ` · восстановление ${esc(fmtDate(doc.last_recovery.at_utc))}: ${Number(doc.last_recovery.recovered_events || 0)} событий возвращено в очередь` : ''}</div></div>
      <div><h4 style="margin:0 0 8px">Команда сейчас</h4><div class="flex wrap gap-sm">${agents.map(row => {
        const stateLabel = row.working ? 'работает' : row.state === 'waiting_owner' ? 'ждёт ответа' : row.state === 'blocked' ? 'есть препятствие' : 'свободен';
        const model = row.model ? ` · ${row.model}${row.provider ? ` (${row.provider})` : ''}` : '';
        const face = (UI.agentAvatarHtml || (() => ''))(row.agent_id || row.name, {
          speaking: !!row.working, label: row.name, cls: 'sm',
        });
        return `<span class="badge agent-chip ${row.working ? 'live' : row.state === 'waiting_owner' || row.state === 'blocked' ? 'pending' : 'archived'}" title="${esc((row.work || '') + model)}">${face}<span>${esc(row.name)} · ${esc(stateLabel)}</span>${model ? `<small>${esc(model)}</small>` : ''}</span>`;
      }).join('')}</div></div>
      <div class="grid cols-2">${['day', 'week'].map(scope => {
        const plan = plans[scope]; const active = plan && plan.status === 'active'; const label = scope === 'day' ? 'сегодня' : 'неделю';
        return `<div class="kpi ${active ? 'info' : ''}"><div class="kpi-top"><span class="kpi-label">План на ${label}</span><button class="btn sm ghost" data-victor-plan="${scope}">${active ? 'Изменить' : 'Задать'}</button></div><div class="kpi-val sm">${esc(active && plan.focus || 'не задан')}</div><div class="kpi-foot">${active && plan.context && plan.context.entity_label ? `Связан с: ${esc(plan.context.entity_label)}` : active && (plan.goals || []).length ? esc(plan.goals.join(' · ')) : 'Цели, привязки, бюджет и контроль'}</div></div>`;
      }).join('')}</div>
      <div class="split"><div><h4 style="margin:0 0 8px">Нужно ваше решение</h4><div class="list">${incidents.length ? incidents.slice(0, 12).map(row => {
        const brief = row.owner_brief || {};
        return `<div class="row"><div class="row-main"><div class="row-title">${esc(brief.fact || 'Нужно ваше решение.')}</div><div class="row-sub">${esc(brief.recommendation || '')}</div><div class="row-sub mono">${esc(row.incident_id)} · ${esc(row.severity || 'warning')} · повторов ${Number(row.occurrences || 1)}</div><details style="margin-top:7px"><summary>Подробнее и доказательства</summary><div class="row-sub" style="white-space:pre-wrap;margin-top:6px">${esc(row.details || 'Доказательства не сохранены.')}</div></details><div style="margin-top:7px"><strong>${esc(brief.question || 'Поручить Виктору?')}</strong></div><div class="row-sub">Разрешение: только проверка. Исправление, restart и live-включение согласуются отдельно.</div><div class="flex gap-sm" style="margin-top:8px"><button class="btn sm primary" data-victor-incident-yes="${esc(row.incident_id)}">Да — проверить</button><button class="btn sm ghost" data-victor-incident-no="${esc(row.incident_id)}">Нет</button></div></div></div>`;
      }).join('') : '<div class="empty-state">Вопросов, требующих вашего решения, нет.</div>'}</div></div>
      <div><h4 style="margin:0 0 8px">Активные задачи</h4><div class="list">${tasks.length ? tasks.slice(0, 14).map(taskHtml).join('') : '<div class="empty-state">Активных задач нет.</div>'}</div></div></div>
    </div>`;
    if (UI.wireAgentFaces) UI.wireAgentFaces(body);
    const rest = UI.qs('[data-victor-rest]', center); const resume = UI.qs('[data-victor-resume]', center);
    if (rest) rest.hidden = doc.mode === 'resting';
    if (resume) resume.hidden = doc.mode !== 'resting';
  }

  async function refresh() {
    if (loading || !window.API || API.config.offline || (UI.isGuest && UI.isGuest())) return state;
    loading = true;
    try {
      const next = await API.http.vitekStatus();
      const instance = String(next && next.backend_instance && next.backend_instance.instance_id || '');
      if (instance && lastBackendInstance && instance !== lastBackendInstance) UI.toast('Backend был перезапущен. Состояние поручений восстановлено и сверено.');
      if (instance) {
        lastBackendInstance = instance;
        try { sessionStorage.setItem('victor.backendInstance', instance); } catch (_) { /* ignore */ }
      }
      const currentRevision = Number(state && state.event_engine && state.event_engine.revision || 0);
      const nextRevision = Number(next && next.event_engine && next.event_engine.revision || 0);
      if (state && nextRevision < currentRevision) return state;
      state = next; renderCenter(state); return state;
    }
    finally { loading = false; }
  }

  function installClientTelemetry() {
    if (window.__victorTelemetryInstalled) return;
    window.__victorTelemetryInstalled = true;
    const sendEvent = (kind, message, stack) => {
      if (!window.API || !API.http || !API.http.vitekClientEvent) return;
      const correlationId = window.crypto && crypto.randomUUID ? crypto.randomUUID() : `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      API.http.vitekClientEvent({
        kind, message: String(message || '').slice(0, 2000), stack: String(stack || '').slice(0, 6000),
        route: location.pathname + location.search, correlation_id: correlationId,
        app_version: '20260718-lifecycle1', backend_instance_id: lastBackendInstance,
      }).catch(() => {});
    };
    window.addEventListener('error', event => sendEvent('frontend_error', event.message, event.error && event.error.stack));
    window.addEventListener('unhandledrejection', event => sendEvent('unhandled_rejection', event.reason && event.reason.message || event.reason, event.reason && event.reason.stack));
    window.addEventListener('offline', () => sendEvent('connection_lost', 'Browser reported offline', ''));
    window.addEventListener('online', () => sendEvent('connection_restored', 'Browser connection restored', ''));
  }

  function wireCenter() {
    const center = UI.qs('[data-victor-center]');
    if (!center) return;
    center.addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button) return;
      try {
        if (button.matches('[data-victor-new]')) return assignmentDrawer(pageContext());
        if (button.matches('[data-victor-cleanup]')) return cleanupDrawer();
        if (button.matches('[data-victor-refresh]')) { button.disabled = true; await refresh(); button.disabled = false; return; }
        if (button.matches('[data-victor-plan]')) return planDrawer(button.dataset.victorPlan, state && state.plans && state.plans[button.dataset.victorPlan]);
        if (button.matches('[data-victor-open-chat]')) return openChat(button.dataset.victorOpenChat);
        if (button.matches('[data-victor-answer-task]')) {
          const task = (state && state.tasks || []).find(row => row.task_id === button.dataset.victorAnswerTask);
          if (!task) throw new Error('Поручение уже обновилось.');
          return taskAnswerDrawer(task);
        }
        if (button.matches('[data-victor-cancel-task]')) {
          button.disabled = true; button.textContent = 'Отменяю…';
          if (button.dataset.incidentId) await API.http.vitekIncidentDecision(button.dataset.incidentId, 'ignore', 'Владелец отменил ранее выданное разрешение.');
          else await API.http.vitekUpdateTask(button.dataset.victorCancelTask, { status: 'cancelled', result: 'Отменено владельцем.' });
          await refresh(); UI.toast('Поручение отменено, история сохранена'); return;
        }
        if (button.matches('[data-victor-incident-yes]')) {
          button.closest('.row').querySelectorAll('button').forEach(item => { item.disabled = true; });
          button.textContent = 'Обрабатывается…';
          const doc = state || await refresh();
          const incident = (doc.incidents || []).find(row => row.incident_id === button.dataset.victorIncidentYes);
          if (!incident) throw new Error('Ситуация уже обновилась. Обновите список.');
          await acceptIncident(incident); return;
        }
        if (button.matches('[data-victor-incident-no]')) { button.closest('.row').querySelectorAll('button').forEach(item => { item.disabled = true; }); button.textContent = 'Обрабатывается…'; await API.http.vitekIncidentDecision(button.dataset.victorIncidentNo, 'ignore', 'Владелец отказался от запуска работы.'); await refresh(); UI.toast('Отклонено. Работа не запущена'); return; }
        if (button.matches('[data-victor-rest]')) {
          const minutes = Number(window.prompt('На сколько минут дать Виктору отдых?', '60') || 0);
          if (minutes > 0) { await API.http.vitekRest({ duration_minutes: minutes, reason: 'Решение владельца в приложении' }); await refresh(); }
          return;
        }
        if (button.matches('[data-victor-resume]')) { await API.http.vitekResume(); await refresh(); return; }
        if (button.matches('[data-victor-scan]')) { button.disabled = true; await API.http.vitekScan(false); await refresh(); button.disabled = false; }
      } catch (error) { button.disabled = false; UI.reportError(error); }
    });
  }

  function ensurePageAction() {
    const slot = UI.qs('#page-actions');
    if (!slot || UI.qs('#victor-page-assign', slot)) return;
    const button = document.createElement('button');
    button.className = 'btn sm';
    button.id = 'victor-page-assign';
    button.type = 'button';
    button.textContent = 'Поручить Виктору';
    button.addEventListener('click', () => assignmentDrawer(pageContext()));
    slot.appendChild(button);
  }
  function formalizeChat() {
    const subtitle = UI.qs('#orch-head-sub');
    if (subtitle && subtitle.textContent !== 'Виктор · ваша правая рука') subtitle.textContent = 'Виктор · ваша правая рука';
    const fab = UI.qs('#orch-fab');
    if (fab) { fab.title = 'Открыть чат с Виктором'; fab.setAttribute('aria-label', 'Открыть чат с Виктором'); }
  }

  function init() {
    installClientTelemetry();
    ensurePageAction();
    formalizeChat();
    wireCenter();
    refresh().catch(error => {
      const body = UI.qs('[data-victor-body]');
      if (body) UI.renderError(body, error, refresh);
    });
    const observer = new MutationObserver(() => { ensurePageAction(); formalizeChat(); });
    observer.observe(document.body, { childList: true, subtree: true });
    UI.onLeave(() => observer.disconnect());
    const timer = window.setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 10000);
    UI.onLeave(() => window.clearInterval(timer));
  }

  // Replace the old compact strategy-page decisions and prompt-based plans with
  // the same conversation-first workflow used by the Overview center.
  document.addEventListener('click', event => {
    const decision = event.target.closest && event.target.closest('.vitek-decision');
    const plan = event.target.closest && event.target.closest('.vitek-plan');
    if (!decision && !plan) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (plan) { planDrawer(plan.dataset.scope || 'day', state && state.plans && state.plans[plan.dataset.scope || 'day']); return; }
    (async () => {
      try {
        const doc = await refresh() || state;
        const incident = doc && (doc.incidents || []).find(row => row.incident_id === decision.dataset.id);
        if (!incident) throw new Error('Ситуация уже обновилась.');
        decision.closest('.row').querySelectorAll('button').forEach(item => { item.disabled = true; });
        decision.textContent = 'Обрабатывается…';
        if (decision.dataset.decision === 'create_task') await acceptIncident(incident);
        else { await API.http.vitekIncidentDecision(incident.incident_id, 'ignore', 'Владелец отказался от запуска работы.'); await refresh(); }
      } catch (error) { decision.disabled = false; UI.reportError(error); }
    })();
  }, true);

  window.Victor = {
    openAssignment: assignmentDrawer,
    openPlan: planDrawer,
    openCleanup: cleanupDrawer,
    openTaskAnswer: taskAnswerDrawer,
    createAssignment,
    refresh,
    openChat,
  };
  UI.ready(init);
})();
