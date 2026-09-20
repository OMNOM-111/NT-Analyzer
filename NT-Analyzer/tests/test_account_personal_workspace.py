"""Normal confirmed Local accounts can own a container without NT pairing.

The HTTP fixture replaces authentication with an isolated authoritative session;
origin/CSRF/dispatch, workspace writes and existing NT gates execute real code.
No actual Local account or credential is touched.
"""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from app import account_auth, server, workspaces
from tests.test_agent_world_live_http import (
    canonical_service, http_live, isolated_http_environment, owner,
)
from tests.test_workspaces import workspace_store

ROUTE = "/api/account/workspace/personal"


@pytest.fixture
def personal_http(http_live, workspace_store, monkeypatch):
    http_live.state["raw_changes"].update(source="desktop_session", role="full_control", is_owner=False,
        session_id="fixture-confirmed-session", device_confirmation_state="active")
    http_live.owner.state["user"]["is_owner"] = False
    monkeypatch.setattr(account_auth, "local_session_is_active", lambda sid, uid: sid == "fixture-confirmed-session")
    workspaces.ensure_owner_workspace(999)
    http_live.before = copy.deepcopy(workspaces._read_doc())
    return http_live


def test_normal_account_gets_only_own_personal_container_and_replay_reuses_it(personal_http):
    first_status, first = personal_http.request(ROUTE, {"display_name": "Private model workspace"})
    assert first_status == 200, first
    uid = personal_http.owner.state["user"]["user_id"]
    workspace = first["workspace"]
    assert workspace["kind"] == "personal" and workspace["owner_user_id"] == uid
    assert not workspace["uses_owner_runtime"] and not workspace["default_runtime_connection_id"]
    second_status, second = personal_http.request(ROUTE, {})
    assert second_status == 200 and second["workspace"]["workspace_id"] == workspace["workspace_id"]
    after = workspaces._read_doc()
    assert after["connections"] == personal_http.before["connections"] == []
    assert after["pairings"] == personal_http.before["pairings"] == []
    assert all(row in after["workspaces"] for row in personal_http.before["workspaces"])
    assert all(row in after["memberships"] for row in personal_http.before["memberships"])
    assert after["active_workspaces"][str(uid)] == workspace["workspace_id"]
    assert not account_auth.path_requires_nt_dual_auth(ROUTE, "POST")
    assert account_auth.path_requires_nt_dual_auth("/api/workspaces/personal", "POST")
    assert account_auth.path_requires_nt_dual_auth("/api/bridge/pair/start", "POST")
    assert account_auth.path_requires_nt_dual_auth("/api/ops/runtime/command", "POST")


@pytest.mark.parametrize("body", [[], {"user_id": 999}, {"workspace_id": "foreign"},
    {"entitlement_id": "owner"}, {"is_owner": True}, {"display_name": 7}, {"display_name": "x" * 101}])
def test_caller_cannot_choose_authority_or_foreign_scope(personal_http, body):
    status, _ = personal_http.request(ROUTE, body)
    assert status == 400
    assert workspaces._read_doc() == personal_http.before


@pytest.mark.parametrize("change", [
    {"device_confirmation_state": "pending", "device_confirmation_required": True},
    {"session_id": "revoked"}, {"session_id": ""}, {"source": "dev_service"},
    {"source": "local"}, {"impersonating": True}, {"impersonator_owner_id": 999},
])
def test_nonconfirmed_or_delegated_session_fails_closed(personal_http, change):
    personal_http.state["raw_changes"].update(change)
    status, _ = personal_http.request(ROUTE, {})
    assert status in {401, 403}
    assert workspaces._read_doc() == personal_http.before


@pytest.mark.parametrize("kind", ["preview", "production", "canary", "service_user", "preview_user"])
def test_environment_and_identity_restrictions(personal_http, monkeypatch, kind):
    if kind == "preview":
        monkeypatch.setattr(server.preview_sandbox, "enabled", lambda: True)
    elif kind in {"production", "canary"}:
        monkeypatch.setattr(server.runtime_env, "is_development", lambda: False)
    else:
        personal_http.owner.state["user"]["is_service_account" if kind == "service_user" else "is_preview_user"] = True
    status, _ = personal_http.request(ROUTE, {})
    assert status in {401, 403}
    assert workspaces._read_doc() == personal_http.before


@pytest.mark.parametrize("headers", [{"csrf": "wrong"}, {"csrf": None}, {"origin": "https://foreign.invalid"}])
def test_origin_and_csrf_are_not_bypassed(personal_http, headers):
    status, _ = personal_http.request(ROUTE, {}, **headers)
    # Cross-origin requests are rejected by the existing auth boundary before
    # the route; same-origin requests with invalid CSRF reach its 403 guard.
    assert status == (401 if "origin" in headers else 403)
    assert workspaces._read_doc() == personal_http.before


@pytest.mark.parametrize("enabled", [True, False, None, "true", 1])
@pytest.mark.parametrize("fails", [False, True])
def test_cabinet_action_reuses_account_api_without_nt_auth_and_never_fakes_opt_in(enabled, fails):
    ui = Path(__file__).resolve().parents[1] / "app/static/aurora/assets/ui.js"
    script = r'''
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync(UI_FILE, 'utf8');
const body = source.slice(source.indexOf("    const personal = qs('#cab-personal-workspace'"), source.indexOf("    const nt = qs('#cab-nt', cb);", source.indexOf('  function renderProfileInto')));
const calls = [], button = {disabled:false}, msg = {textContent:''}, location = {};
const context = {cb:{}, qs:s => s.endsWith('-msg') ? msg : button, CURRENT_AUTH:{}, location,
  applyNavAccess: v => calls.push(['nav',v]),
  API:{http:{accountPersonalWorkspace: async body => {calls.push(['container',body]); if(FAILS) throw Error('fixture unavailable');},
             authStatus: async () => {calls.push(['auth']);return {agent_world:{enabled:ENABLED}};}}}};
vm.runInNewContext(body, context);
if(calls.length) throw Error('auto submission');
button.onclick().then(() => process.stdout.write(JSON.stringify({calls, location, disabled:button.disabled, message:msg.textContent})));
'''.replace("UI_FILE", json.dumps(str(ui))).replace("FAILS", json.dumps(fails)).replace("ENABLED", json.dumps(enabled))
    completed = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True, timeout=15)
    result = json.loads(completed.stdout)
    assert result["disabled"] is False
    assert result["calls"][0] == ["container", {"display_name": "Моё личное пространство"}]
    if enabled is True and not fails:
        assert result["location"]["href"] == "ai-command-center.html#tab=overview&domain=models"
    else:
        assert not result["location"]
        assert result["message"]
