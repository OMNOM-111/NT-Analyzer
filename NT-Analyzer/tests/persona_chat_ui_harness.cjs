/* Shipped speech handlers with a disposable DOM/device port. No real audio or network. */
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const path = require('node:path');
const PersonaAudio = require('../app/static/aurora/assets/persona-audio.js');
const source = fs.readFileSync(path.join(__dirname, '../app/static/aurora/assets/ui.js'), 'utf8');
const scenario = JSON.parse(fs.readFileSync(0, 'utf8'));
const names = ['orchPersonaId', 'orchPersonaViews', 'orchSpeechPersona', 'orchSpeechHtml', 'orchLoadPersonaAudio',
  'orchSpeechState', 'wireOrchSpeech', 'agentSpeakStop', 'agentAvatarId', 'agentAvatarUrl', 'agentAvatarHtml',
  'wireAgentFaces', 'orchMessageHtml', 'orchSaveCurrentId'];
if (scenario.mode.startsWith('canonical_review_')) names.push('orchIsAgentWorldMessage', 'orchInferKind', 'orchFulfillmentOf',
  'orchRatingHtml', 'orchFooterHtml', 'orchAwaitHtml');
if (scenario.mode === 'late_face_asset_stays_stopped') names.push('agentFacePlay', 'agentFacePause');
function functionSource(name) {
  const start = source.search(new RegExp('^  (?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, name);
  const line = source.slice(start, source.indexOf('\n', start));
  return line.trimEnd().endsWith('}') ? line : source.slice(start, source.indexOf('\n  }', start) + 4);
}
class Element {
  constructor() { this.events = new Map(); this.isConnected = true; this.dataset = {}; this.attrs = {}; this.textContent = ''; this.disabled = false;
    const classes = new Set(); this.classList = {contains: key => classes.has(key), add: key => classes.add(key), remove: key => classes.delete(key)}; }
  addEventListener(name, fn) { if (!this.events.has(name)) this.events.set(name, []); this.events.get(name).push(fn); }
  removeEventListener(name, fn) { this.events.set(name, (this.events.get(name) || []).filter(item => item !== fn)); }
  fire(name) { return Promise.all((this.events.get(name) || []).map(fn => fn({target: this}))); }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name] || ''; }
  remove() { this.isConnected = false; }
}
const persona = {id: '12345678-1234-4321-8765-123456789abc', revision: 4, status: 'active', title: 'Мой помощник', avatar_key: 'marina',
  presentation: {resolved_voice_profile_id: 'secretary', voice_profile_id: 'secretary', voice_mode: 'browser',
    voice_label: 'Секретарь', voice_gender: 'female', voice_speed: 1.2, voice_language: 'ru-RU', animation_mode: 'auto'}};
const row = {message_id: 'MSG-123456789ABC', role: 'assistant', agent_id: persona.id, agent_name: 'Историческое имя',
  model: 'model-one', provider: 'provider-one', content: 'Displayed saved reply.', _persona: persona};
const ORCH = {open: true, currentId: 'test-conversation', viewerProfileId: ''};
const ORCH_SPEECH = {generation: 0, controller: null, module: null, message: '', button: null, status: null};
const button = new Element(), status = new Element(), face = new Element(), video = new Element();
button.dataset.orchSpeech = row.message_id; button.parentElement = {querySelector: () => status};
button.closest = () => ({querySelector: () => face});
face.classList.add('orch-msg-face'); face.querySelector = () => video;
video.readyState = 0; video.pause = () => {}; video.currentTime = 0;
const requests = [], spoken = [], scripts = [], faces = [], pauses = [], timers = new Map(), domains = [];
const window = new Element(), document = new Element(); let nextTimer = 0;
Object.assign(window, {PersonaAudio, Blob, crypto: {randomUUID: () => 'test-key-' + (requests.length + 1)},
  setTimeout(fn) { const id = ++nextTimer; timers.set(id, fn); return id; }, clearTimeout(id) { timers.delete(id); },
  matchMedia() { return {matches: false}; }, SpeechSynthesisUtterance: class {constructor(text) {this.text = text;}},
  speechSynthesis: {getVoices: () => window.voices, speak: utter => spoken.push(utter), cancel: () => {},
    addEventListener: () => {}, removeEventListener: () => {}},
  voices: [{name: 'Irina local', voiceURI: 'local-irina', lang: 'ru-RU', localService: true}]});
Object.assign(document, {head: {appendChild: script => scripts.push(script)}, createElement: () => new Element(), hidden: false});
let response = body => ({fallback: 'browser', text: 'Actual stored reply from server.', persona_id: persona.id,
  persona_revision: body.expected_revision, speech_source: {kind: 'sf_chat_message', persona_id: persona.id, ...body.payload}});
let domainResponse = () => ({item: persona});
const API = {config: {offline: false}, http: {
  aiControlCenterPersonaSpeak: (id, body) => { requests.push({id, body}); return response(body); },
  aiControlCenterDomainItem: async (domain, id) => { domains.push({domain, id}); return domainResponse(id); }
}};
const esc = value => String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const sandbox = {window, document, API, ORCH, ORCH_SPEECH, Blob, URL, Audio: window.Audio, speechSynthesis: window.speechSynthesis,
  AGENT_SPEAK: {gen: 0}, ORCH_KEY: 'fixture-chat', localStorage: {setItem() {}, removeItem() {}},
  AGENT_AVATAR_IDS: {vitek: 'vitek', manager: 'manager', marina: 'marina', tolik: 'tolik', nikita: 'nikita', ivan: 'ivan'},
  AGENT_FACE_CROP: {vitek: {zoom: 1, cx: 50, cy: 50}, marina: {zoom: 2, cx: 40, cy: 40}},
  ORCH_KIND_LABELS: {chat: 'Сообщение', report: 'Отчёт', informational: 'Уведомление'},
  ORCH_FULFILL_LABELS: {unset: 'не отмечено', done: 'выполнено', failed: 'не выполнено', na: 'переписка'},
  qsa: selector => selector === '.agent-face' ? [face] : [button], esc,
  agentFacePlay: (...args) => faces.push(args), agentFacePause: value => pauses.push(value), agentFaceReduceMotion: () => false,
  setTimeout: window.setTimeout, clearTimeout: window.clearTimeout,
  orchActionsHtml: () => '', orchFooterHtml: () => '', orchAttachmentsHtml: () => '', orchAwaitHtml: () => '',
  orchAgentWorldTaskId: () => '', orchFmtTime: () => '', icon: key => key, orchChainHtml: () => '', console};
vm.createContext(sandbox);
vm.runInContext(names.map(functionSource).join('\n') + '\n' +
  "window.addEventListener('pagehide', agentSpeakStop); window.addEventListener('hashchange', agentSpeakStop); document.addEventListener('visibilitychange', () => { if (document.hidden) agentSpeakStop(); });", sandbox);
const flush = async () => { for (let n = 0; n < 20; n++) await Promise.resolve(); };
const bind = () => sandbox.wireOrchSpeech({}, [row], ORCH.currentId);
const click = () => button.fire('click');
const finish = async pending => { if (spoken.at(-1)?.onend) spoken.at(-1).onend(); await pending; };
const flushTimers = () => { const fns = [...timers.values()]; timers.clear(); fns.forEach(fn => fn()); };

(async () => {
  switch (scenario.mode) {
    case 'binding_is_silent':
      bind(); await flush(); assert.equal(requests.length, 0); assert.equal(spoken.length, 0); assert.equal(scripts.length, 0); break;
    case 'hover_is_silent':
      sandbox.wireAgentFaces({}); await face.fire('mouseenter'); await face.fire('mouseleave');
      assert.equal(spoken.length, 0); assert.equal(requests.length, 0); assert.equal(faces.length, 0); break;
    case 'late_face_asset_stays_stopped': {
      let plays = 0; video.play = () => {plays++; return Promise.resolve();};
      sandbox.agentFacePlay(face, {loop: true}); sandbox.agentFacePause(face);
      await video.fire('loadeddata'); assert.equal(plays, 0); assert.equal(video.loop, false); break;
    }
    case 'saved_message_metadata_not_dom_text_or_model': {
      bind(); const pending = click(); await flush();
      assert.equal(requests.length, 1); assert.equal(requests[0].id, persona.id);
      assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body.payload)), {conversation_id: ORCH.currentId, message_id: row.message_id});
      assert.equal(requests[0].body.expected_revision, persona.revision);
      assert.equal(spoken[0].text, 'Actual stored reply from server.'); assert.equal(spoken[0].rate, 1.2);
      assert.equal(faces.length, 0); spoken[0].onstart(); assert.equal(faces.length, 1);
      assert.match(status.textContent, /Локальный голос устройства/); assert.match(status.textContent, /без синхронизации фонем/);
      await finish(pending); assert.equal(button.attrs['aria-pressed'], 'false'); break;
    }
    case 'model_independent_identity': {
      const other = {...row, model: 'another model', provider: 'another provider'};
      assert.equal(sandbox.orchSpeechPersona(row), sandbox.orchSpeechPersona(other));
      const html = sandbox.orchMessageHtml(other);
      assert.ok(html.includes('data-persona-id="' + persona.id + '"')); assert.ok(html.includes('agents/marina/speaking.webm'));
      assert.ok(html.includes('Историческое имя')); break;
    }
    case 'renamed_persona_preserves_old_label': {
      persona.title = 'Changed current Persona name'; const html = sandbox.orchMessageHtml(row);
      assert.ok(html.includes('Историческое имя')); assert.ok(!html.includes(persona.title)); break;
    }
    case 'missing_persona_is_not_vitek_or_technical_uuid': {
      row._persona = null; delete row.agent_name; const html = sandbox.orchMessageHtml(row);
      assert.ok(!html.includes('agents/vitek/')); assert.ok(html.includes('AI-помощник')); assert.ok(html.includes('disabled'));
      assert.ok(!html.includes('orch-msg-author">' + persona.id));
      assert.equal(sandbox.orchSpeechPersona(row), null); break;
    }
    case 'unconfigured_or_suspended_has_no_action':
      for (const change of [{status: 'suspended'}, {presentation: {resolved_voice_profile_id: ''}}]) {
        assert.ok(sandbox.orchSpeechHtml({...row, _persona: {...persona, ...change}}).includes('disabled'));
      } break;
    case 'legacy_uses_local_preset_not_owner_transport': {
      row.agent_id = 'marina'; row._persona = null; bind(); const pending = click(); await flush();
      assert.equal(requests.length, 0); assert.equal(spoken.length, 1); assert.equal(spoken[0].text, row.content);
      assert.ok(sandbox.orchMessageHtml(row).includes('agents/marina/speaking.webm')); await finish(pending); break;
    }
    case 'human_no_persona_speech':
      for (const change of [{role: 'user'}, {sender_type: 'human'}, {sender_profile_id: 'human-id'}]) {
        assert.equal(sandbox.orchPersonaId({...row, ...change}), ''); assert.equal(sandbox.orchSpeechHtml({...row, ...change}), '');
      } break;
    case 'explicit_stop_during_pending_transport': {
      let resolve; response = () => new Promise(r => {resolve = r;}); bind(); const pending = click(); await flush();
      await click(); assert.equal(button.attrs['aria-pressed'], 'false');
      resolve({fallback: 'browser'}); await flush(); await pending; assert.equal(spoken.length, 0); break;
    }
    case 'stop_before_transport_microtask': {
      let calls = 0;
      const controller = PersonaAudio.create({host: window, requestSpeech: () => {calls++; return {fallback: 'browser'};}});
      const pending = controller.play({persona, text: 'Saved text', userInitiated: true});
      controller.stop(); await pending; await flush(); assert.equal(calls, 0); assert.equal(spoken.length, 0); break;
    }
    case 'shared_playback_stops_other_persona_surface': {
      const sample = PersonaAudio.create({host: window});
      const sampleDone = sample.play({persona, text: 'Sample description', userInitiated: true});
      assert.equal(spoken.length, 1); bind(); const chatDone = click(); await flush();
      assert.equal((await sampleDone).state, 'stopped'); assert.equal(spoken.length, 2); await finish(chatDone); break;
    }
    case 'module_loading_cancel_is_safe': {
      delete window.PersonaAudio; bind(); const pending = click(); await flush(); assert.equal(scripts.length, 1);
      assert.equal(scripts[0].src, '/ui/assets/persona-audio.js?v=20260908-agent-world-persona-chat1');
      await click(); window.PersonaAudio = PersonaAudio; scripts[0].onload(); await pending;
      assert.equal(requests.length, 0); assert.equal(spoken.length, 0); break;
    }
    case 'module_failure_is_text_fallback': {
      delete window.PersonaAudio; bind(); const pending = click(); await flush(); scripts[0].onerror(); await pending;
      assert.equal(ORCH_SPEECH.message, ''); assert.match(status.textContent, /Ответ доступен текстом/); assert.equal(spoken.length, 0); break;
    }
    case 'navigate_during_module_load': {
      delete window.PersonaAudio; bind(); const pending = click(); await flush(); sandbox.orchSaveCurrentId('other');
      window.PersonaAudio = PersonaAudio; scripts[0].onload(); await pending; assert.equal(requests.length, 0); break;
    }
    case 'pagehide_stops_audio': case 'hashchange_stops_audio': case 'hidden_stops_audio': {
      bind(); const pending = click(); await flush();
      if (scenario.mode === 'hidden_stops_audio') { document.hidden = true; await document.fire('visibilitychange'); }
      else await window.fire(scenario.mode.split('_')[0]);
      await pending; assert.equal(ORCH_SPEECH.message, ''); assert.equal(button.attrs['aria-pressed'], 'false'); break;
    }
    case 'revoked_voice_never_falls_back_with_client_text': {
      response = () => Promise.reject({status: 409}); bind(); await click();
      assert.equal(spoken.length, 0); assert.match(status.textContent, /доступ не подтверждён/); break;
    }
    case 'network_failure_does_not_claim_saved_source': {
      response = () => Promise.reject(Error('offline')); bind(); await click(); assert.equal(spoken.length, 0); break;
    }
    case 'mismatched_server_receipt_denies_local_voice': {
      response = body => ({fallback: 'browser', text: 'foreign', persona_revision: body.expected_revision,
        speech_source: {kind: 'sf_chat_message', persona_id: persona.id, conversation_id: ORCH.currentId, message_id: 'foreign'}});
      bind(); await click(); assert.equal(spoken.length, 0); break;
    }
    case 'missing_device_voice_is_text': {
      window.voices = []; bind(); const pending = click(); await flush(); flushTimers(); await pending;
      assert.equal(spoken.length, 0); assert.match(status.textContent, /Ответ доступен текстом/); break;
    }
    case 'domain_fetches_uuid_once_not_model': {
      const result = await sandbox.orchPersonaViews([row, {...row, message_id: 'MSG-other', model: 'changed'}, {role: 'user'}], ORCH.currentId);
      assert.equal(domains.length, 1); assert.deepEqual(domains[0], {domain: 'personas', id: persona.id});
      assert.equal(result[0]._persona.id, persona.id); assert.equal(result[1]._persona.id, persona.id); break;
    }
    case 'foreign_dto_and_fetch_failure_are_not_cached_as_persona': {
      domainResponse = () => ({item: {...persona, id: 'foreign'}});
      assert.equal((await sandbox.orchPersonaViews([row], ORCH.currentId))[0]._persona, null);
      domainResponse = () => { throw Error('revoked'); };
      assert.equal((await sandbox.orchPersonaViews([row], ORCH.currentId))[0]._persona, null); break;
    }
    case 'canonical_review_readonly_history': {
      for (const kind of ['real_model_response', 'synthetic_model_response', 'bounded_delegation_result', 'ninjatrader_report', 'desktop_chart', 'agent_world_preview']) {
        const message = {...row, source: 'agent_world_local', message_kind: 'report', fulfillment: 'done', rating: 3,
          feedback_comment: 'Earlier comment retained', actions: [{source_kind: kind, status: 'completed'}]};
        const original = JSON.stringify(message), html = sandbox.orchFooterHtml(message, false);
        assert.ok(!html.includes('data-orch-rate=')); assert.ok(!html.includes('data-orch-fulfill='));
        assert.ok(!html.includes('orch-feedback-edit')); assert.ok(!html.includes('orch-feedback-save'));
        assert.ok(html.includes(message.feedback_comment)); assert.ok(html.includes('не приёмка задачи'));
        assert.equal(sandbox.orchAwaitHtml(message), ''); assert.equal(sandbox.orchRatingHtml(message, false), '');
        assert.equal(sandbox.orchFulfillmentOf(message), 'unset'); assert.equal(JSON.stringify(message), original);
      } break;
    }
    case 'canonical_review_marker_matches_backend_not_lookalike_payload': {
      for (const key of ['name', 'action']) {
        assert.equal(sandbox.orchIsAgentWorldMessage({...row, source: 'app', actions: [{[key]: 'agent_world_preview'}]}), true);
      }
      for (const key of ['name', 'source_kind']) {
        assert.equal(sandbox.orchIsAgentWorldMessage({...row, source: 'app', actions: [{[key]: 'desktop_chart'}]}), false);
      } break;
    }
    case 'canonical_review_current_state_not_legacy_marks': {
      for (const [review, expected] of [['pending', 'unset'], ['accepted', 'done'], ['rejected', 'failed']]) {
        const message = {...row, source: 'agent_world_local', fulfillment: 'done', rating: 3,
          _awTask: {human_review: {status: review}}};
        assert.equal(sandbox.orchFulfillmentOf(message), expected);
        assert.ok(!sandbox.orchFooterHtml(message, false).includes('data-orch-rate='));
      } break;
    }
    case 'canonical_review_ordinary_legacy_message_unchanged': {
      const message = {...row, agent_id: 'marina', source: 'app', message_kind: 'report', fulfillment: 'unset'};
      assert.equal(sandbox.orchIsAgentWorldMessage(message), false);
      assert.ok(sandbox.orchFooterHtml(message, false).includes('data-orch-rate='));
      assert.ok(sandbox.orchAwaitHtml(message).includes('data-orch-fulfill=')); break;
    }
    default: throw Error('unknown case');
  }
  console.log('PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
