"""Scoped rail navigation and actual auth-bootstrap regression contracts.

The DOM harness executes the shipped access function, not a second navigation
implementation. Handler tests reuse disposable stores and a loopback-only
server; there are no browser, provider or real owner-data operations.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app import server
from app.ai_control_center import live_gateway
from tests.test_agent_world_live_http import (  # noqa: F401 -- fixture dependencies
    canonical_service, http_live, isolated_http_environment, owner,
)
from tests.test_agent_world_live_gateway import OTHER_WORKSPACE, WORKSPACE


ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "app" / "static" / "aurora" / "assets" / "ui.js"


def navigation(auth, *, page="overview", pathname="/ui/index.html", search="", sequence=None):
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(UI_FILE, 'utf8');
const nav = source.slice(source.indexOf('  const NAV = ['), source.indexOf('  let runtimeAccounts = []'));
const access = source.slice(source.indexOf('  function applyNavAccess('), source.indexOf('  function maybeRedirectBeginnerHome('));
const input = INPUT;
const replacements = [], locks = [];
let beginners = 0, demos = 0, items = [];
const classes = (initial = []) => {
  const values = new Set(initial);
  return { values, remove: value => values.delete(value),
    toggle: (value, on) => on ? values.add(value) : values.delete(value) };
};
const makeLock = () => ({ remove() { items.forEach(item => { if (item.lock === this) item.lock = null; }); } });
const context = {
  document: { body: { dataset: { page: input.page } }, documentElement: { classList: classes() }, createElement: makeLock },
  location: { pathname: input.pathname, search: input.search, replace: value => replacements.push(value) },
  qs: (selector, parent) => selector === '.lb' ? parent.label : items.find(item => item.dataset.nav === 'ai'),
  qsa: () => items,
  lockedNavClick: function lockedNavClick() {},
  STUDENT_NAV_IDS: new Set(['overview', 'practice', 'community', 'docs']),
  ensureBeginnerWatermark: () => beginners++, ensureDemoWatermark: () => demos++,
  renderLockGate: (...args) => locks.push(args)
};
vm.runInNewContext(nav + '\n' + access + '\nthis.run = applyNavAccess; this.nav = NAV;', context);
items = context.nav.map(entry => ({
  dataset: { nav: entry.id }, href: entry.href, title: entry.label,
  label: { textContent: entry.label }, hidden: false, lock: null, listeners: new Set(),
  classList: classes(entry.id === input.page ? ['active'] : []),
  removeEventListener(type, fn) { this.listeners.delete(fn); },
  addEventListener(type, fn) { this.listeners.add(fn); },
  querySelector() { return this.lock; }, appendChild(node) { this.lock = node; }
}));
const results = (input.sequence || [input.auth]).map(auth => {
  const redirected = context.run(auth) === true;
  return { redirected, items: items.map(item => ({
    id: item.dataset.nav, href: item.href, label: item.label.textContent,
    hidden: item.hidden, locked: item.classList.values.has('rail-locked'),
    lockCount: item.lock ? 1 : 0, listenerCount: item.listeners.size
  })) };
});
process.stdout.write(JSON.stringify({ results, replacements, locks, beginners, demos }));
"""
    script = script.replace("UI_FILE", json.dumps(str(UI))).replace("INPUT", json.dumps({
        "auth": auth, "page": page, "pathname": pathname, "search": search, "sequence": sequence,
    }))
    output = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True,
                            text=True, encoding="utf-8", timeout=20)
    return json.loads(output.stdout)


def ordinary(enabled=False, **changes):
    return {"is_owner": False, "ux_mode": "professional", "agent_world": {"enabled": enabled},
            "locked_nav": [], **changes}


def ai_entries(result):
    return [item for item in result["items"] if item["id"] in {"ai", "agents"}]


@pytest.mark.parametrize("is_owner", [True, False])
def test_exact_server_opt_in_shows_one_ai_center_without_changing_other_rail_entries(is_owner):
    output = navigation(ordinary(True, is_owner=is_owner))
    ai, agents = ai_entries(output["results"][0])
    assert ai["href"] == "ai-command-center.html" and ai["label"] == "AI Центр"
    assert ai["hidden"] is False and ai["locked"] is False
    assert agents["hidden"] is True
    entries = {item["id"]: item for item in output["results"][0]["items"]}
    assert entries["community"]["label"] == "SF Social" and entries["community"]["href"] == "community.html"
    assert entries["desktop"]["href"] == "desktop.html" and entries["desktop"]["hidden"] is False
    assert entries["practice"]["hidden"] is True
    assert output["replacements"] == output["locks"] == []


@pytest.mark.parametrize("grant", [None, False, "true", 1, {}, []])
def test_missing_disabled_or_malformed_opt_in_preserves_ordinary_legacy_navigation(grant):
    output = navigation(ordinary(grant, locked_nav=["ai", "agents"]), pathname="/ui/ai-agents.html", page="agents")
    ai, agents = ai_entries(output["results"][0])
    assert [(item["href"], item["label"]) for item in (ai, agents)] == [
        ("ai-lab.html", "AI Lab"), ("ai-agents.html", "AI Agents")]
    assert all(not item["hidden"] and item["locked"] for item in (ai, agents))
    assert all(item["listenerCount"] == item["lockCount"] == 1 for item in (ai, agents))
    assert output["replacements"] == [] and len(output["locks"]) == 1


def test_auth_payload_without_agent_world_never_infers_opt_in_from_owner_or_capabilities():
    output = navigation({"is_owner": True, "capabilities": {"ai_lab": True, "ai_pro_models": True}})
    ai, agents = ai_entries(output["results"][0])
    assert ai["label"] == "AI Lab" and agents["hidden"] is False
    assert output["replacements"] == []


def test_workspace_switch_reapplies_current_grant_without_sticky_routes_or_duplicate_locks():
    output = navigation({}, sequence=[ordinary(True), ordinary(False, locked_nav=["ai", "agents"]), ordinary(True)])
    first, revoked, restored = [ai_entries(result) for result in output["results"]]
    assert first[0]["label"] == restored[0]["label"] == "AI Центр"
    assert first[1]["hidden"] is restored[1]["hidden"] is True
    assert revoked[0]["href"] == "ai-lab.html" and revoked[1]["hidden"] is False
    assert all(item["lockCount"] == item["listenerCount"] == 1 for item in revoked)
    assert all(item["lockCount"] == item["listenerCount"] == 0 for item in restored)


@pytest.mark.parametrize("legacy, tab, page", [("ai-lab", "overview", "ai"), ("ai-agents", "agents", "agents")])
def test_old_opted_in_bookmarks_redirect_to_the_matching_center_surface(legacy, tab, page):
    output = navigation(ordinary(True), page=page, pathname=f"/ui/{legacy}.html", search="?task=existing-task")
    assert output["replacements"] == [f"ai-command-center.html?task=existing-task#tab={tab}"]
    assert output["results"][0]["redirected"] is True


@pytest.mark.parametrize("pathname", ["/ui/ai-command-center.html", "/ui/index.html", "/ui/not-ai-lab.html"])
def test_new_center_and_unrelated_paths_never_redirect_themselves(pathname):
    output = navigation(ordinary(True), page="ai", pathname=pathname, search="?return=/ui/ai-agents.html")
    assert output["replacements"] == [] and output["results"][0]["redirected"] is False


def test_beginner_shell_keeps_ai_hidden_and_never_receives_a_professional_redirect():
    output = navigation(ordinary(True, ux_mode="beginner"), pathname="/ui/ai-lab.html", page="ai")
    assert all(item["hidden"] for item in ai_entries(output["results"][0]))
    assert output["replacements"] == [] and output["beginners"] == 1


def test_legacy_redirect_stops_original_page_start_and_hidden_rail_cannot_override_theme():
    source = UI.read_text(encoding="utf-8")
    start = source.index("  async function authenticateAndStart(")
    assert "if (applyNavAccess(CURRENT_AUTH)) return;" in source[start:start + 4000]
    theme = (UI.parent / "theme.css").read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in theme


def test_actual_auth_bootstrap_and_overview_agree_for_current_opted_in_workspace(http_live):
    status, auth = http_live.request("/api/auth/status")
    assert status == 200 and auth["authenticated"] is True, auth
    assert auth["active_workspace"]["workspace_id"] == WORKSPACE
    assert auth["agent_world"] == {"enabled": True, "synthetic": False, "status": "IN DEVELOPMENT",
                                   "url": "/ui/ai-command-center.html"}
    status, overview = http_live.request("overview")
    assert status == 200 and overview["enabled"] is True
    assert overview["scope"]["workspace_id"] == WORKSPACE
    assert http_live.calls["starts"] == []


@pytest.mark.parametrize("allowlist", ["", OTHER_WORKSPACE])
def test_actual_auth_bootstrap_never_borrows_another_workspace_opt_in(http_live, monkeypatch, allowlist):
    monkeypatch.setenv(live_gateway.WORKSPACES_ENV, allowlist)
    status, auth = http_live.request("/api/auth/status")
    assert status == 200 and auth["authenticated"] is True, auth
    assert auth["agent_world"]["enabled"] is False
    assert http_live.request("overview")[0] in {403, 404}
    assert http_live.calls["starts"] == []


@pytest.mark.parametrize("throws", [False, True])
def test_permission_augmentation_uses_fresh_context_and_restores_previous_handler_context(monkeypatch, throws):
    handler = object.__new__(server.Handler)
    previous, current = {"workspace_id": "ws_stale"}, {"workspace_id": "ws_current"}
    handler._remote_context = previous
    calls = []

    def navigation(handler):
        calls.append(handler._remote_context)
        if throws:
            raise RuntimeError("navigation unavailable")
        return {"enabled": False}

    monkeypatch.setattr(live_gateway, "navigation", navigation)
    if throws:
        with pytest.raises(RuntimeError, match="navigation unavailable"):
            handler._augment_permissions(current, {"is_owner": True})
    else:
        assert handler._augment_permissions(current, {"is_owner": True})["agent_world"]["enabled"] is False
    assert calls == [current] and calls[0] is current
    assert handler._remote_context is previous
