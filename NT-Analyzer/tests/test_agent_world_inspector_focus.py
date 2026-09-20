"""Regression for keyboard return-to-context around the Task Inspector.

Opening a task moves focus into the drawer. The inspector then re-renders
itself on refresh and on every internal tab switch, and each re-render used to
re-capture the focus target — by then the drawer itself. Escape therefore
"returned" focus into the panel it had just closed, and a keyboard user lost
their place in the list they came from.

Runs the real page module over a small DOM shim; no browser or application.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app" / "static" / "aurora" / "assets" / "pages" / "ai-command-center.js"

SHIM = r"""
const fs = require('node:fs'), vm = require('node:vm');
let uid = 0;
function makeEl(tag, cls) {
  const el = {
    tagName: String(tag || 'DIV').toUpperCase(), _id: ++uid, className: cls || '',
    children: [], parent: null, dataset: {}, attrs: {}, tabIndex: 0, hidden: false,
    innerHTML: '', textContent: '', disabled: false, isConnected: true,
    classList: {
      contains: name => String(el.className).split(/\s+/).includes(name),
      add: name => { if (!el.classList.contains(name)) el.className = (el.className + ' ' + name).trim(); },
      remove: name => { el.className = String(el.className).split(/\s+/).filter(v => v && v !== name).join(' '); },
      toggle: (name, on) => { on ? el.classList.add(name) : el.classList.remove(name); },
    },
    setAttribute: (k, v) => { el.attrs[k] = String(v); },
    getAttribute: k => (k in el.attrs ? el.attrs[k] : null),
    hasAttribute: k => k in el.attrs || (k.startsWith('data-')
      && el.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] !== undefined),
    removeAttribute: k => { delete el.attrs[k]; },
    addEventListener() {}, removeEventListener() {},
    getClientRects: () => [{ width: 10, height: 10 }],
    getBoundingClientRect: () => ({ width: 10, height: 10, top: 0, left: 0, right: 10, bottom: 10 }),
    focus() { doc.activeElement = el; },
    contains: other => { for (let n = other; n; n = n.parent) if (n === el) return true; return false; },
    append(child) { child.parent = el; el.children.push(child); return child; },
    querySelector: sel => el._find(sel)[0] || null,
    querySelectorAll: sel => el._find(sel),
    closest(sel) { for (let n = el; n; n = n.parent) if (n._matches(sel)) return n; return null; },
    _matches(sel) {
      return String(sel).split(',').map(s => s.trim()).some(one => {
        if (one.startsWith('.')) return el.classList.contains(one.slice(1));
        if (one.startsWith('#')) return el.attrs.id === one.slice(1);
        if (one.startsWith('[data-')) {
          const name = one.slice(6).replace(/[\]=].*$/, '');
          const key = name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
          return el.dataset[key] !== undefined;
        }
        return el.tagName === one.toUpperCase();
      });
    },
    _find(sel) {
      const out = [];
      (function walk(node) { node.children.forEach(child => { if (child._matches(sel)) out.push(child); walk(child); }); })(el);
      return out;
    },
  };
  return el;
}
const doc = {
  _listeners: {}, activeElement: null,
  addEventListener(type, fn) { (doc._listeners[type] = doc._listeners[type] || []).push(fn); },
  removeEventListener(type, fn) { doc._listeners[type] = (doc._listeners[type] || []).filter(v => v !== fn); },
  dispatch(type, event) { (doc._listeners[type] || []).forEach(fn => fn(event)); },
  querySelector: sel => doc.body._matches(sel) ? doc.body : doc.body.querySelector(sel),
  querySelectorAll: sel => doc.body.querySelectorAll(sel),
};
doc.body = makeEl('body');
doc.body.attrs.id = 'body';
doc.activeElement = doc.body;
const shell = doc.body.append(makeEl('div', 'aw-shell'));
shell.attrs.id = 'aw-center';
for (const id of ['aw-content', 'aw-pulse', 'aw-context', 'aw-notice', 'aw-refresh',
                  'aw-run-demo', 'aw-open-chat', 'aw-updated', 'aw-domain-launcher']) {
  const node = shell.append(makeEl('div'));
  node.attrs.id = id;
}
const tabs = shell.append(makeEl('nav', 'aw-tabs'));
for (const key of ['overview', 'work', 'agents']) {
  const button = tabs.append(makeEl('button'));
  button.dataset.awTab = key;
  button.setAttribute('aria-selected', String(key === 'overview'));
}
// The control the owner activated: a task row outside the drawer.
const invoker = shell.append(makeEl('button', 'aw-task-card'));
invoker.dataset.awTask = TASK_ID;

let drawer = null;
const frames = [];
const frame = fn => frames.push(fn);
const runFrames = () => { const due = frames.splice(0); due.forEach(fn => fn()); };
const UI = {
  ready(fn) { UI._boot = fn; },
  signal: () => ({}), onLeave() {}, wireAgentFaces() {},
  drawer(head, body) {
    if (!drawer) { drawer = doc.body.append(makeEl('aside', 'drawer')); }
    drawer.innerHTML = body;
    // The real shell nests .aw-inspector inside the drawer element and adds the
    // 'open' class inside requestAnimationFrame, one frame later. Two
    // openDrawer() calls in the same frame therefore both see it as not-open --
    // which is exactly the window in which the focus target was overwritten.
    drawer.children.length = 0;
    drawer.append(makeEl('div', 'aw-inspector'));
    drawer.isConnected = true;
    frame(() => drawer.classList.add('open'));
    return drawer;
  },
  closeDrawer() { if (drawer) { drawer.classList.remove('open'); drawer.isConnected = false; } },
  openSFChat() {}, toast() {},
};
const overview = OVERVIEW;
const taskDetail = TASK_DETAIL;
const api = { http: {
  async aiControlCenterOverview() { return overview; },
  async aiControlCenterTask() { return taskDetail; },
  async aiControlCenterTasks() { return { items: overview.tasks, next_cursor: '' }; },
} };
const win = { UI, API: api, location: { hash: '', search: '' }, history: { replaceState() {} },
              setTimeout, clearTimeout, requestAnimationFrame: frame };
vm.runInNewContext(fs.readFileSync(SCRIPT_PATH, 'utf8'),
  { window: win, document: doc, URLSearchParams, Date, console });
"""


def run(js_tail: str, overview: dict, task_detail: dict, task_id: str):
    body = (SHIM
            .replace("SCRIPT_PATH", json.dumps(str(SCRIPT)))
            .replace("OVERVIEW", json.dumps(overview))
            .replace("TASK_DETAIL", json.dumps(task_detail))
            .replace("TASK_ID", json.dumps(task_id)))
    script = ("(async () => {\n" + body + "\n" + js_tail
              + "\n})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exitCode = 1; });")
    out = subprocess.run(["node", "-e", script], cwd=ROOT, check=True,
                         capture_output=True, text=True, encoding="utf-8", timeout=25)
    return json.loads(out.stdout)


TASK_ID = "11111111-1111-1111-1111-111111111111"
TASK = {"id": TASK_ID, "task_id": TASK_ID, "title": "Иван · Голос Court", "status": "review",
        "phase": "awaiting_review", "phase_label": "Ожидает проверки",
        "stage": "provider_receipt", "stage_label": "Ответ модели получен",
        "task_class": "court_vote", "task_class_label": "Голос Court",
        "progress_pct": None, "synthetic": False, "updated_at": "2026-09-05T03:37:00Z"}
OVERVIEW = {"enabled": True, "scope": {"synthetic": False, "workspace_id": "ws"},
            "capabilities": {}, "tasks": [TASK], "agents": [], "outcomes": [],
            "activity": [], "attention": [],
            "stats": {"executing": 0, "awaiting_review": 1, "done": 0, "agents": 0, "attention": 1}}
DETAIL = {"task": TASK, **TASK, "artifacts": [], "outcomes": [], "evaluations": [],
          "activity": [], "contributions": [], "decisions": [], "fields": {}, "limitations": []}

TAIL = """
await UI._boot();
doc.activeElement = invoker;
doc.dispatch('click', { target: invoker });
await new Promise(r => setTimeout(r, 30));
const openedOn = doc.activeElement === drawer ? 'drawer' : doc.activeElement === invoker ? 'invoker' : 'other';
RERENDER
doc.dispatch('keydown', { key: 'Escape', target: drawer });
await new Promise(r => setTimeout(r, 10));
const landed = doc.activeElement === invoker ? 'invoker'
  : doc.activeElement === drawer ? 'drawer'
  : (doc.activeElement && doc.activeElement.dataset && doc.activeElement.dataset.awTab) ? 'tab' : 'other';
process.stdout.write(JSON.stringify({ openedOn, landed, drawerOpen: drawer.classList.contains('open') }));
"""


def test_escape_returns_focus_to_the_control_that_opened_the_inspector():
    result = run(TAIL.replace("RERENDER", ""), OVERVIEW, DETAIL, TASK_ID)
    assert result["openedOn"] == "drawer"
    assert result["drawerOpen"] is False
    assert result["landed"] == "invoker"


def test_inspector_rerender_does_not_overwrite_the_saved_focus_target():
    """This is the shape that actually broke: a redraw before Escape."""
    rerender = ("doc.dispatch('click', { target: Object.assign(makeEl('button'), "
                "{ dataset: { awDetailTab: 'evidence' }, parent: drawer.children[0] }) });"
                "await new Promise(r => setTimeout(r, 20));")
    result = run(TAIL.replace("RERENDER", rerender), OVERVIEW, DETAIL, TASK_ID)
    assert result["landed"] == "invoker"


def test_focus_falls_back_to_the_active_tab_when_the_invoker_is_gone():
    removed = "invoker.isConnected = false;"
    result = run(TAIL.replace("RERENDER", removed), OVERVIEW, DETAIL, TASK_ID)
    assert result["landed"] == "tab"
