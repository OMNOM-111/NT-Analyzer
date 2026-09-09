'use strict';
// The shipped handlers run against an isolated DOM/transport port. No browser,
// credentials, model execution, audio or live application data are used.
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert/strict');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'app/static/aurora/assets/ui.js'), 'utf8');
const apiSource = fs.readFileSync(path.join(root, 'app/static/aurora/assets/api.js'), 'utf8');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const ID = '11111111-1111-1111-1111-111111111111', SECOND = '22222222-2222-2222-2222-222222222222';
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
function extract(name, text = source) {
  const start = text.search(new RegExp('^  (?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, 'real function missing: ' + name);
  const rest = text.slice(start + 1), next = rest.search(/\n  (?:(?:async )?function |const http =)/);
  return text.slice(start, next < 0 ? undefined : start + 1 + next);
}
class Element {
  constructor() { this.handlers = {}; this.value = ''; this.hidden = false; this.disabled = false; this.style = {}; this.innerHTML = ''; this.attributes = {}; this.scrollHeight = 300; this.scrollTop = 100; this.clientHeight = 200; this.classList = {add(){},remove(){}}; }
  addEventListener(name, action) { this.handlers[name] = action; }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  querySelector() { return null; }
  appendChild(value) { this.child = value; }
  insertAdjacentHTML(_where, value) { this.innerHTML += value; }
  remove() { this.removed = true; }
  focus() { this.focused = true; }
}
const person = {id: ID, title: 'Марина', status: 'active', main_assistant: true, avatar_key: 'marina'};
const state = {personas: [person], personaId: ID, personaError: '', personaGeneration: 0, currentId: 'chat-one', sending: false,
  dialogActionPending: false, aiAvailable: true, pendingAttachments: [], mode: 'auto', open: true};
const elements = new Map(), calls = [], toasts = [];
const add = key => { const value = new Element(); elements.set(key, value); return value; };
const textBox = add('#orch-text'); textBox.value = 'Сделай снимок рабочего стола MNQ 09-26, 5m';
add('#orch-msgs'); add('#orch-send'); add('#orch-model-picker'); add('#orch-persona-select'); add('#orch-persona-refresh');
add('#orch-live-think'); add('#orch-live-think-body'); add('#orch-live-body'); add('.orch-msg-stack'); add('.orch-msg-face');
let human = false, apiFailure = false;
const env = {ORCH: state, esc, qs: selector => elements.get(selector) || null, isGuest: () => false,
  orchIsHumanConversation: () => human, agentSpeakStop: () => calls.push(['stop-audio']),
  AGENT_AVATAR_IDS: {marina: true, vitek: true}, ORCH_MODES: {auto: {agent: ''}},
  agentAvatarHtml: (id, options) => `<span data-face="${esc(id)}" data-label="${esc(options.label)}"></span>`,
  icon: () => '', el: () => new Element(), wireAgentFaces: () => {},
  orchAppendMessage: (_box, row) => calls.push(['append', row]),
  orchLoadMessages: async () => calls.push(['history']), orchLoadConversations: async () => calls.push(['conversations']),
  orchRenderPendingAttachments: () => {}, refreshInAppNotices: async () => {},
  orchSaveCurrentId: cid => {state.currentId = cid;}, reportError: error => toasts.push(error.message),
  toast: value => toasts.push(value), Date, Set, Error,
  API: {config: {offline: false}, http: {
    aiOrchestratorMessageStream: async (...args) => {
      calls.push(['stream', args.slice(0, 3), args[4]]);
      if (apiFailure) throw Error('transport interrupted');
      args[3].onFinal({ok: true, conversation_id: 'chat-one', agent_id: ID, agent_name: 'Марина', reply: 'Сохранённый ответ'});
      return {ok: true};
    },
    sfChatMessage: async (...args) => calls.push(['human', args]),
    aiControlCenterDomain: async (...args) => { calls.push(['catalog', args]); return {items: [person]}; },
  }},
};
env.window = {API: env.API};
vm.createContext(env);
const names = ['orchPersonaOptions', 'orchRenderPersonaPicker', 'orchLoadPersonas', 'orchPersonaTransport', 'orchPendingPersonaFace', 'orchSend', 'orchRenderAuthRequired'];
names.forEach(name => vm.runInContext(extract(name), env));
const plain = value => JSON.parse(JSON.stringify(value));
(async () => {
  if (input.kind === 'send') {
    if (input.mode === 'main') state.personaId = '';
    if (input.mode === 'missing') state.personas = [];
    if (input.mode === 'suspended') state.personas = [{...person, status: 'suspended'}];
    if (input.mode === 'invalid') state.personaId = 'not-a-uuid';
    if (input.mode === 'human') human = true;
    if (input.mode === 'failure') apiFailure = true;
    const original = textBox.value;
    await env.orchSend();
    const sent = calls.filter(call => call[0] === 'stream');
    if (['missing','suspended','invalid'].includes(input.mode)) {
      assert.equal(sent.length, 0); assert.equal(textBox.value, original); assert.equal(toasts.length, 1);
    } else if (input.mode === 'human') {
      assert.equal(sent.length, 0); assert.equal(calls.filter(call => call[0] === 'human').length, 1);
    } else {
      assert.equal(sent.length, 1); assert.deepEqual(plain(sent[0][1]), [original, 'chat-one', '']);
      assert.deepEqual(plain(sent[0][2]), input.mode === 'main' ? {} : {persona_id: ID});
      assert.equal(state.sending, false);
      assert.ok(calls.some(call => call[0] === 'conversations'));
      if (input.mode === 'failure') assert.match(state.transientError.text, /Обновите историю/);
      else { assert.match(elements.get('.orch-msg-face').outerHTML, /data-face="marina"/); assert.doesNotMatch(elements.get('.orch-msg-face').outerHTML, /vitek/); }
    }
  } else if (input.kind === 'picker') {
    if (input.mode === 'human') human = true;
    if (input.mode === 'sending') state.sending = true;
    state.personas.push({id: SECOND, title: '<img onerror="bad">', status: 'active', main_assistant: false});
    env.orchRenderPersonaPicker();
    if (human) assert.equal(elements.get('#orch-model-picker').hidden, true);
    else {
      assert.match(elements.get('#orch-model-picker').innerHTML, /Главный: Марина/);
      assert.doesNotMatch(elements.get('#orch-model-picker').innerHTML, /<img onerror/);
      assert.equal(elements.get('#orch-persona-select').disabled, state.sending);
      elements.get('#orch-persona-select').handlers.change({target: {value: SECOND}});
      assert.equal(state.personaId, state.sending ? ID : SECOND);
      assert.equal(calls.filter(call => call[0] === 'stream').length, 0);
    }
  } else if (input.kind === 'catalog') {
    if (input.mode === 'pagination') {
      env.API.http.aiControlCenterDomain = async (_domain, query) => {calls.push(['page', query]); return query.cursor ? {items: [{...person, id: SECOND}]} : {items: [person], next_cursor: 'next-one'};};
      await env.orchLoadPersonas(); assert.equal(state.personas.length, 2); assert.equal(calls.filter(call => call[0] === 'page').length, 2);
    } else if (input.mode === 'revoked') {
      let finish;
      env.API.http.aiControlCenterDomain = async () => new Promise(resolve => {finish = resolve;});
      const pending = env.orchLoadPersonas();
      env.orchRenderAuthRequired(null);
      finish({items: [person]}); await pending;
      assert.deepEqual(plain(state.personas), []); assert.equal(state.personaId, '');
    } else {
      env.API.http.aiControlCenterDomain = async () => input.mode === 'loop' ? {items: [person], next_cursor: 'same'} : {items: {fake: 'object'}};
      await env.orchLoadPersonas(); assert.deepEqual(plain(state.personas), []); assert.match(state.personaError, /не получен/);
      assert.throws(() => env.orchPersonaTransport(state.personas, ID), /недоступна/);
    }
  } else if (input.kind === 'transport') {
    const requests = [], events = [];
    const packet = new TextEncoder().encode('event: final\ndata: {"ok":true}\n\nevent: done\ndata: {"ok":true}\n\n');
    const port = {Error, TextDecoder, mutationRequestId: () => 'request-one', requestHeaders: value => value,
      HttpError: Error, fetch: async (url, options) => {requests.push([url, JSON.parse(options.body)]); let consumed = false; return {ok: true, body: {getReader: () => ({read: async () => consumed ? {done: true} : (consumed = true, {done: false, value: packet})})}};}};
    vm.createContext(port); vm.runInContext(extract('personaChatOptions', apiSource) + '\n' + extract('streamOrchestrator', apiSource), port);
    if (input.mode === 'invalid') await assert.rejects(port.streamOrchestrator('original', 'chat', '', {}, {persona_id: 'wrong'}), /Persona/);
    else {
      const options = input.mode === 'legacy' ? undefined : {persona_id: ID, is_owner: true, api_key: 'not-forwarded'};
      await port.streamOrchestrator('original', 'chat', '', {onFinal: value => events.push(value)}, options);
      assert.equal(requests.length, 1); assert.equal(events.length, 1);
      assert.deepEqual(plain(requests[0][1]), {message: 'original', conversation_id: 'chat', agent: '', request_id: 'request-one', ...(options ? {persona_id: ID} : {})});
    }
  } else if (input.kind === 'drawer') {
    const back = add('.drawer-back'), panel = new Element(), heading = add('.drawer-h'); add('.drawer-b');
    back._d = panel; panel.setAttribute('role', 'dialog'); panel.setAttribute('aria-label', 'Модели и подключения · Подключить');
    env.requestAnimationFrame = action => action(); env.syncNoticeOffset = () => {};
    vm.runInContext(extract('drawer'), env);
    assert.equal(env.drawer('<h3>Developer Preview</h3>', '<p>Sandbox</p>'), panel);
    assert.equal(panel.attributes['aria-label'], undefined);
    assert.equal(panel.attributes['aria-labelledby'], 'app-drawer-title');
    assert.match(heading.innerHTML, /id="app-drawer-title"><h3>Developer Preview<\/h3>/);
    // A later panel retains no old accessible name either.
    panel.setAttribute('aria-label', 'Старое название');
    env.drawer('<h3>Безопасность</h3>', '<p>Current</p>');
    assert.equal(panel.attributes['aria-label'], undefined);
    assert.match(heading.innerHTML, /id="app-drawer-title"><h3>Безопасность<\/h3>/);
    assert.doesNotMatch(heading.innerHTML, /Developer Preview/);
  } else if (input.kind === 'face') {
    assert.match(env.orchPendingPersonaFace(person), /data-face="marina"/);
    assert.doesNotMatch(env.orchPendingPersonaFace({...person, avatar_key: ''}), /vitek|<video/);
    assert.doesNotMatch(env.orchPendingPersonaFace(null, 'Persona'), /vitek|<video/);
  } else throw Error('Unknown scenario');
  process.stdout.write('PASS');
})().catch(error => {process.stderr.write(error.stack); process.exitCode = 1;});
