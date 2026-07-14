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
    free: 'свободен', busy: 'работает', awaiting_decision: 'ждёт решения', resting: 'отдыхает',
  };
  let state = null;
  let loading = false;

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
    const details = [
      `Виктор, приступай к поручению: ${title}.`,
      payload.description ? `Комментарий: ${payload.description}` : '',
      payload.control && payload.control.condition ? `Контроль: ${payload.control.condition}` : '',
      payload.control && payload.control.report_frequency ? `Отчётность: ${payload.control.report_frequency}` : '',
      budgetText(payload.budget) ? `Бюджет: ${budgetText(payload.budget)}.` : '',
    ].filter(Boolean).join('\n');
    try {
      const acknowledgement = await API.http.aiOrchestratorMessage(details, cid, 'vitek');
      saveChat(cid);
      return { conversation_id: cid, task, acknowledgement };
    } catch (error) {
      // A dropped HTTP response does not prove that the server missed the
      // message.  Re-read durable state before rolling anything back.
      try {
        const current = await API.http.vitekStatus();
        const stored = (current.tasks || []).find(row => row.task_id === task.task_id);
        if (stored && stored.auto_execute && stored.status !== 'planned') {
          saveChat(cid);
          return { conversation_id: cid, task: stored, acknowledgement: null, recovered: true };
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

  async function acceptIncident(incident) {
    const brief = incident.owner_brief || {};
    const title = brief.fact || incident.title || 'Разобраться с ситуацией';
    const result = await createAssignment({
      title,
      description: [brief.recommendation, brief.question].filter(Boolean).join('\n'),
      category: incident.category || 'incident',
      priority: incident.severity === 'critical' ? 'critical' : incident.severity === 'error' ? 'high' : 'normal',
      source: 'victor_incident', incident_id: incident.incident_id,
      context: { page: document.body.dataset.page || 'overview', entity_type: 'incident', entity_id: incident.incident_id, entity_label: title, url: location.pathname + location.search },
    });
    await API.http.vitekIncidentDecision(incident.incident_id, 'resolve', 'Поручение принято Виктором в отдельном диалоге.');
    await refresh();
    openChat(result.conversation_id);
  }

  function taskHtml(task) {
    const agent = AGENT_LABELS[task.assigned_agent] || task.assigned_agent || 'Управляющий назначает исполнителя';
    const context = task.context || {};
    const model = String(task.execution_model || '');
    const modelLine = model && !['unknown', 'internal'].includes(model.toLowerCase()) ? ` · модель: ${esc(model)}` : '';
    const control = task.control && task.control.condition ? `<div class="row-sub">Контроль: ${esc(task.control.condition)}</div>` : '';
    return `<div class="row"><div class="row-main"><div class="row-title">${esc(task.owner_title || task.title || 'Поручение')}</div>
      <div class="row-sub">${esc(agent)}${modelLine}${task.due_at_utc ? ` · срок ${esc(fmtDate(task.due_at_utc))}` : ''}</div>
      ${context.entity_label ? `<div class="row-sub">Связано с: ${esc(context.entity_label)}</div>` : ''}${control}</div>
      <div class="flex wrap gap-sm">${task.conversation_id ? `<button class="btn sm ghost" data-victor-open-chat="${esc(task.conversation_id)}">Чат</button>` : ''}<button class="btn sm" data-victor-complete="${esc(task.task_id)}">Готово</button></div></div>`;
  }

  function renderCenter(doc) {
    const center = UI.qs('[data-victor-center]');
    if (!center) return;
    const body = UI.qs('[data-victor-body]', center);
    const tasks = (doc.tasks || []).filter(row => ['new', 'awaiting_decision', 'planned', 'in_progress', 'waiting_review', 'blocked'].includes(row.status));
    const incidents = (doc.incidents || []).filter(row => ['awaiting_decision', 'acknowledged', 'in_progress'].includes(row.status) && row.owner_decision_required);
    const agents = doc.agent_activity || [];
    const plans = doc.plans || {};
    body.innerHTML = `<div class="col gap-lg">
      <div class="grid cols-5">
        <div class="kpi ${doc.mode === 'free' ? 'pos' : 'info'}"><div class="kpi-label">Состояние</div><div class="kpi-val sm">${esc(MODE_LABELS[doc.mode] || doc.mode)}</div><div class="kpi-foot">личный контроль</div></div>
        <div class="kpi ${incidents.length ? 'warn' : 'pos'}"><div class="kpi-label">Нужен ваш ответ</div><div class="kpi-val sm">${incidents.length}</div><div class="kpi-foot">только важные решения</div></div>
        <div class="kpi ${tasks.length ? 'info' : 'pos'}"><div class="kpi-label">Активные поручения</div><div class="kpi-val sm">${tasks.length}</div><div class="kpi-foot">под контролем Виктора</div></div>
        <div class="kpi ${agents.some(row => row.working) ? 'info' : 'pos'}"><div class="kpi-label">Команда работает</div><div class="kpi-val sm">${agents.filter(row => row.working).length}</div><div class="kpi-foot">до ${Number(doc.event_engine && doc.event_engine.parallel_limit || 6)} одновременно</div></div>
        <div class="kpi ${doc.background && doc.background.installed ? 'pos' : 'warn'}"><div class="kpi-label">Фоновый контроль</div><div class="kpi-val sm">${doc.background && doc.background.installed ? 'включён' : 'не установлен'}</div><div class="kpi-foot">событийный режим</div></div>
      </div>
      <div class="finance-note"><strong>Виктор:</strong> ${esc(doc.message || 'Готов принять поручение.')}</div>
      <div><h4 style="margin:0 0 8px">Команда сейчас</h4><div class="flex wrap gap-sm">${agents.map(row => `<span class="badge ${row.working ? 'live' : 'archived'}" title="${esc(row.work || '')}"><span class="dot"></span>${esc(row.name)} · ${row.working ? 'работает' : 'свободен'}</span>`).join('')}</div></div>
      <div class="grid cols-2">${['day', 'week'].map(scope => {
        const plan = plans[scope]; const active = plan && plan.status === 'active'; const label = scope === 'day' ? 'сегодня' : 'неделю';
        return `<div class="kpi ${active ? 'info' : ''}"><div class="kpi-top"><span class="kpi-label">План на ${label}</span><button class="btn sm ghost" data-victor-plan="${scope}">${active ? 'Изменить' : 'Задать'}</button></div><div class="kpi-val sm">${esc(active && plan.focus || 'не задан')}</div><div class="kpi-foot">${active && plan.context && plan.context.entity_label ? `Связан с: ${esc(plan.context.entity_label)}` : active && (plan.goals || []).length ? esc(plan.goals.join(' · ')) : 'Цели, привязки, бюджет и контроль'}</div></div>`;
      }).join('')}</div>
      <div class="split"><div><h4 style="margin:0 0 8px">Нужно ваше решение</h4><div class="list">${incidents.length ? incidents.slice(0, 12).map(row => {
        const brief = row.owner_brief || {};
        return `<div class="row"><div class="row-main"><div class="row-title">${esc(brief.fact || 'Нужно ваше решение.')}</div><div class="row-sub">${esc(brief.recommendation || '')}</div><div style="margin-top:7px"><strong>${esc(brief.question || 'Поручить Виктору?')}</strong></div><div class="flex gap-sm" style="margin-top:8px"><button class="btn sm primary" data-victor-incident-yes="${esc(row.incident_id)}">Да</button><button class="btn sm ghost" data-victor-incident-no="${esc(row.incident_id)}">Нет</button></div></div></div>`;
      }).join('') : '<div class="empty-state">Вопросов, требующих вашего решения, нет.</div>'}</div></div>
      <div><h4 style="margin:0 0 8px">Активные задачи</h4><div class="list">${tasks.length ? tasks.slice(0, 14).map(taskHtml).join('') : '<div class="empty-state">Активных задач нет.</div>'}</div></div></div>
    </div>`;
    const rest = UI.qs('[data-victor-rest]', center); const resume = UI.qs('[data-victor-resume]', center);
    if (rest) rest.hidden = doc.mode === 'resting';
    if (resume) resume.hidden = doc.mode !== 'resting';
  }

  async function refresh() {
    if (loading || !window.API || API.config.offline || (UI.isGuest && UI.isGuest())) return state;
    loading = true;
    try { state = await API.http.vitekStatus(); renderCenter(state); return state; }
    finally { loading = false; }
  }

  function wireCenter() {
    const center = UI.qs('[data-victor-center]');
    if (!center) return;
    center.addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button) return;
      try {
        if (button.matches('[data-victor-new]')) return assignmentDrawer(pageContext());
        if (button.matches('[data-victor-refresh]')) { button.disabled = true; await refresh(); button.disabled = false; return; }
        if (button.matches('[data-victor-plan]')) return planDrawer(button.dataset.victorPlan, state && state.plans && state.plans[button.dataset.victorPlan]);
        if (button.matches('[data-victor-open-chat]')) return openChat(button.dataset.victorOpenChat);
        if (button.matches('[data-victor-complete]')) { await API.http.vitekUpdateTask(button.dataset.victorComplete, { status: 'completed', result: 'Отмечено выполненным владельцем.' }); await refresh(); return; }
        if (button.matches('[data-victor-incident-yes]')) {
          button.disabled = true; button.textContent = 'Передаю…';
          const doc = state || await refresh();
          const incident = (doc.incidents || []).find(row => row.incident_id === button.dataset.victorIncidentYes);
          if (!incident) throw new Error('Ситуация уже обновилась. Обновите список.');
          await acceptIncident(incident); return;
        }
        if (button.matches('[data-victor-incident-no]')) { await API.http.vitekIncidentDecision(button.dataset.victorIncidentNo, 'ignore', 'Владелец отказался от запуска работы.'); await refresh(); return; }
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
    const timer = window.setInterval(() => { if (!document.hidden) refresh().catch(() => {}); }, 5000);
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
        decision.disabled = true;
        if (decision.dataset.decision === 'create_task') await acceptIncident(incident);
        else { await API.http.vitekIncidentDecision(incident.incident_id, 'ignore', 'Владелец отказался от запуска работы.'); await refresh(); }
      } catch (error) { decision.disabled = false; UI.reportError(error); }
    })();
  }, true);

  window.Victor = {
    openAssignment: assignmentDrawer,
    openPlan: planDrawer,
    createAssignment,
    refresh,
    openChat,
  };
  UI.ready(init);
})();
