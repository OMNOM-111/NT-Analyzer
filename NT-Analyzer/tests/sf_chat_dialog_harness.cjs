/* Execute the shipped dialog + SF Chat action functions, with a small DOM port.
 * No browser, network, credentials, real conversations or runtime writes. */
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/static/aurora/assets/ui.js'), 'utf8');
const scenario = JSON.parse(fs.readFileSync(0, 'utf8'));
function functionSource(name) {
  const start = source.search(new RegExp('^  (?:async )?function ' + name + '\\(', 'm'));
  assert.ok(start >= 0, name);
  const firstLine = source.slice(start, source.indexOf('\n', start));
  return firstLine.trimEnd().endsWith('}') ? firstLine : source.slice(start, source.indexOf('\n  }', start) + 4);
}
class Element {
  constructor(name) {
    this.name = name; this.events = new Map(); this.isConnected = true;
    this.offsetParent = {}; this.hidden = false; this.disabled = false;
    this.classList = { remove() {} }; this.value = '';
  }
  addEventListener(type, fn) { if (!this.events.has(type)) this.events.set(type, new Set()); this.events.get(type).add(fn); }
  removeEventListener(type, fn) { this.events.get(type)?.delete(fn); }
  fire(type, props = {}) {
    const event = { target: this, defaultPrevented: false, stopped: false,
      preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; }, ...props };
    for (const fn of [...(this.events.get(type) || [])]) fn(event);
    if (this['on' + type]) this['on' + type](event);
    return event;
  }
  focus() { if (!this.disabled) document.activeElement = this; }
  select() { this.selected = true; }
  showModal() { if (scenario.mode === 'unsupported') throw Error('unsupported'); this.open = true; }
  close() { this.open = false; this.fire('close'); }
  remove() { this.isConnected = false; }
}
let lastDialog;
const trigger = new Element('trigger');
const document = { activeElement: trigger, body: { appendChild() {} } };
const window = new Element('window');
const calls = [], errors = [], notices = [], renders = [];
const pageNodes = new Map();
const ORCH = { sending: false, dialogActionPending: false, currentId: 'old',
  conversations: [{ conversation_id: 'old', title: 'Original', closed: false }],
  historyRows: [{ text: 'history' }], historyMore: true, historyBefore: 'cursor',
  listQuery: 'old query', listFilter: 'pinned', aiAvailable: true,
  folders: { names: ['Original folder'], of: { old: 'Original folder' } } };
let releaseNetwork;
const API = { config: { offline: false }, http: new Proxy({}, { get: (_, method) => async (...args) => {
  calls.push([method, ...args]);
  if (scenario.mode === 'api_error') throw Error('Network failed');
  if (scenario.mode === 'network_duplicate') await new Promise(resolve => { releaseNetwork = resolve; });
  return { conversation: { conversation_id: 'created' } };
} }) };
window.API = API;
const context = { window, document, APP_NAME: 'StratForge AI', ORCH, API, CURRENT_AUTH: { user_id: 'local-user' },
  icon: () => '<svg></svg>', toast: msg => notices.push(msg), reportError: err => errors.push(err.message),
  el: html => {
    const dialog = new Element('dialog'); dialog.html = html;
    dialog.nodes = new Map(['form', '[data-dialog-close]', '[data-dialog-cancel]', '[data-dialog-accept]'].map(name => [name, new Element(name)]));
    if (html.includes('data-dialog-input')) dialog.nodes.set('[data-dialog-input]', new Element('input'));
    lastDialog = dialog; return dialog;
  },
  qs: (selector, root) => {
    if (root) return root.nodes.get(selector) || null;
    if (!pageNodes.has(selector)) pageNodes.set(selector, new Element(selector));
    return pageNodes.get(selector);
  },
  qsa: (_, root) => root ? [...root.nodes.values()].filter(n => n.name !== 'form') : [],
  render: async () => renders.push('inbox'),
  orchHasUnfinishedCurrent: () => scenario.mode !== 'finished',
  orchIsHumanConversation: value => scenario.mode === 'human' || value === 'human',
  orchCurrentConversation: () => ORCH.conversations.find(c => c.conversation_id === ORCH.currentId),
  orchSaveCurrentId: cid => { ORCH.currentId = cid; },
  orchLoadConversations: async () => { renders.push('conversations'); },
  orchLoadMessages: async cid => { renders.push(['messages', cid]); },
  orchRenderConversations: () => renders.push('rail'), orchRenderWorkState: () => renders.push('work'),
  orchStopFeedbackVoice: () => {}, refreshInAppNotices: async () => {}, dismissNoticesForConversation: () => {},
  orchFolders: () => ORCH.folders, orchSaveFolders: state => { ORCH.folders = state; renders.push('folders'); },
};
const names = ['esc', 'trapDialogFocus', 'requestDialog', 'confirmDialog', 'promptDialog',
  'orchDialogAction', 'orchAddFolder', 'orchMoveToFolder', 'orchSelectConversation',
  'orchNewConversation', 'orchRename', 'orchDelete', 'orchToggleConversationState'];
vm.createContext(context);
vm.runInContext('let ACTIVE_APP_DIALOG = null;\n' + names.map(functionSource).join('\n'), context);
const button = (name, dialog = lastDialog) => dialog.nodes.get('[data-dialog-' + name + ']');
const submit = () => lastDialog.nodes.get('form').fire('submit');
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

async function main() {
  if (scenario.kind === 'inbox') {
    const clearAll = new Element('clearAll');
    clearAll.focus(); context.clearAll = clearAll;
    const start = source.indexOf('      if (clearAll) clearAll.onclick = async () => {');
    const end = source.indexOf('\n      };', start) + '\n      };'.length;
    vm.runInContext(source.slice(start, end), context);
    const pending = clearAll.onclick();
    assert.equal(clearAll.disabled, true); assert.equal(calls.length, 0);
    if (scenario.mode === 'cancel') button('cancel').fire('click');
    else submit();
    await pending;
    assert.equal(clearAll.disabled, false);
    if (scenario.mode === 'cancel') {
      assert.equal(calls.length, 0); assert.equal(document.activeElement, clearAll);
    } else { assert.equal(calls.length, 1); assert.equal(calls[0][0], 'notificationsClear'); }
  } else if (scenario.kind === 'helper') {
    const inputMode = scenario.mode.startsWith('input');
    let resolved = false;
    const pending = (inputMode ? context.promptDialog : context.confirmDialog)('<img onerror="bad()">', {
      title: '<title>', confirmLabel: '<accept>', value: '\"><script>bad()</script>',
      required: scenario.mode !== 'input_empty_allowed',
    }).then(value => { resolved = true; return value; });
    const dialog = lastDialog;
    const input = button('input');
    assert.ok(dialog.html.includes('&lt;img onerror=&quot;bad()&quot;&gt;'));
    assert.ok(dialog.html.includes('&lt;title&gt;') && dialog.html.includes('&lt;accept&gt;'));
    assert.ok(!dialog.html.includes('<script>'));
    if (scenario.mode !== 'unsupported') {
      await new Promise(resolve => setTimeout(resolve, 0));
      assert.equal(resolved, false, 'Waiting must not block the event loop or auto-confirm');
      assert.equal(document.activeElement, input || button('cancel'));
    }
    let expected = false;
    switch (scenario.mode) {
      case 'accept': submit(); submit(); expected = true; break;
      case 'cancel': button('cancel').fire('click'); break;
      case 'close_button': button('close').fire('click'); break;
      case 'escape': {
        const event = dialog.fire('keydown', { key: 'Escape' });
        assert.ok(event.stopped && event.defaultPrevented); break;
      }
      case 'native_cancel': assert.ok(dialog.fire('cancel').defaultPrevented); break;
      case 'removed': dialog.close(); break;
      case 'hashchange': window.fire('hashchange'); break;
      case 'pagehide': window.fire('pagehide'); break;
      case 'unsupported': assert.equal(notices.length, 1); break;
      case 'duplicate':
        assert.equal(await context.confirmDialog('Second action'), false);
        assert.equal(await context.promptDialog('Second input'), null);
        assert.equal(lastDialog, dialog); button('cancel').fire('click'); break;
      case 'focus': {
        const all = context.qsa('', dialog);
        all.at(-1).focus(); assert.ok(dialog.fire('keydown', { key: 'Tab' }).defaultPrevented);
        assert.equal(document.activeElement, all[0]);
        assert.ok(dialog.fire('keydown', { key: 'Tab', shiftKey: true }).defaultPrevented);
        assert.equal(document.activeElement, all.at(-1)); button('cancel').fire('click'); break;
      }
      case 'input_accept':
        assert.equal(input.value, '\"><script>bad()</script>'); assert.ok(input.selected);
        input.value = 'New title'; submit(); expected = 'New title'; break;
      case 'input_cancel': button('cancel').fire('click'); expected = null; break;
      case 'input_empty':
        input.value = '   '; submit(); await flush(); assert.equal(resolved, false);
        button('cancel').fire('click'); expected = null; break;
      case 'input_empty_allowed': input.value = ''; submit(); expected = ''; break;
      default: throw Error('Unknown helper scenario');
    }
    assert.equal(await pending, expected);
    assert.equal(document.activeElement, trigger);
    assert.equal(dialog.isConnected, false);
    assert.equal(window.events.get('hashchange').size + window.events.get('pagehide').size, 0);
    const next = context.confirmDialog('Next');
    // A queued close event from the old dialog cannot cancel its successor.
    dialog.fire('close'); button('cancel').fire('click'); assert.equal(await next, false);
  } else {
    const fn = context[scenario.action];
    const arg = scenario.action === 'orchSelectConversation' ? 'other' : 'old';
    if (scenario.mode === 'sending') ORCH.sending = true;
    const before = JSON.stringify(ORCH);
    const pending = fn(arg);
    const early = ['sending', 'human', 'finished'].includes(scenario.mode);
    if (!early) {
      assert.ok(lastDialog?.open);
      assert.equal(calls.length, 0, 'Opening a dialog must never mutate the backend');
      assert.equal(ORCH.historyMore, true, 'Cancellation must preserve the history cursor');
      assert.equal(JSON.stringify(ORCH.historyRows), '[{"text":"history"}]');
      if (scenario.mode === 'duplicate' || scenario.mode === 'network_duplicate') {
        await fn(arg); assert.equal(calls.length, 0);
      }
      if (scenario.mode === 'stale') ORCH.currentId = 'external-switch';
      if (scenario.mode === 'auth_stale') context.CURRENT_AUTH = { user_id: 'other-user' };
      if (scenario.mode === 'cancel') button('cancel').fire('click');
      else { const input = button('input'); if (input) input.value = scenario.mode === 'empty_folder' ? '' : 'Updated'; submit(); }
    }
    if (scenario.mode === 'network_duplicate') {
      await flush(); assert.equal(calls.length, 1); await fn(arg); assert.equal(calls.length, 1); releaseNetwork();
    }
    await pending;
    assert.equal(ORCH.dialogActionPending, false);
    if (['cancel', 'stale', 'auth_stale', 'sending', 'human'].includes(scenario.mode)) {
      assert.equal(calls.length, 0); assert.equal(renders.length, 0);
      if (scenario.mode !== 'stale') assert.equal(JSON.stringify(ORCH), before);
    } else if (scenario.mode === 'api_error') {
      assert.equal(errors.length, 1); assert.equal(ORCH.currentId, 'old');
    } else {
      assert.equal(errors.length, 0);
      if (scenario.action === 'orchNewConversation') {
        assert.equal(calls.length, 1); assert.equal(calls[0][0], 'aiOrchestratorCreateConversation');
        assert.equal(ORCH.currentId, 'created');
      } else if (scenario.action === 'orchSelectConversation') {
        assert.equal(ORCH.currentId, 'other'); assert.equal(ORCH.historyRows, null);
      } else if (scenario.action === 'orchAddFolder') assert.ok(ORCH.folders.names.includes('Updated'));
      else if (scenario.action === 'orchMoveToFolder') assert.equal(ORCH.folders.of.old, scenario.mode === 'empty_folder' ? undefined : 'Updated');
      else {
        assert.equal(calls.length, 1); assert.equal(calls[0][1], 'old');
        if (scenario.action === 'orchToggleConversationState') assert.equal(calls[0][2], 'closed');
        if (scenario.action === 'orchRename') assert.equal(calls[0][2], 'Updated');
      }
    }
  }
  process.stdout.write('PASS');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
