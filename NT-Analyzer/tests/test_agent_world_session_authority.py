"""Read-only worker leases reuse real Local session/device authority."""
from __future__ import annotations

import hashlib
import time
from types import SimpleNamespace

import pytest

from app import account_auth, permissions, security_devices, server
from tests.test_device_confirmation_flow import confirmation_store, _login, _confirm


def _manifest(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("mode", ["permanent", "session"])
def test_read_only_worker_lease_follows_confirmation_and_logout(confirmation_store, monkeypatch, mode):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    login = _login()
    sid = account_auth.authenticate_session(login["session_token"])["session_id"]
    assert account_auth.local_session_is_active(sid, 42) is False
    _confirm(login, mode)
    before = _manifest(confirmation_store)
    assert account_auth.local_session_is_active(sid, 42) is True
    assert account_auth.local_session_is_active(sid, 999) is False
    assert account_auth.local_session_is_active("unknown", 42) is False
    assert _manifest(confirmation_store) == before
    account_auth.revoke_own_session(42, sid)
    assert account_auth.local_session_is_active(sid, 42) is False


@pytest.mark.parametrize("change", ["expired", "revoked", "inactive_user", "pending", "foreign_environment", "authoritative_storage"])
def test_worker_lease_fails_closed_on_fresh_authority(confirmation_store, monkeypatch, change):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    login = _login()
    _confirm(login, "session")
    sid = account_auth.authenticate_session(login["session_token"])["session_id"]
    assert account_auth.local_session_is_active(sid, 42)
    document = account_auth._read_doc()
    session = next(row for row in document["sessions"] if row["session_id"] == sid)
    if change == "expired":
        session["expires_at"] = time.time() - 1
    elif change == "revoked":
        session["revoked"] = True
    elif change == "inactive_user":
        next(row for row in document["users"] if row["user_id"] == 42)["status"] = "revoked"
    elif change == "pending":
        session["device_confirmation_state"] = "pending"
    elif change == "foreign_environment":
        monkeypatch.setenv("STRATFORGE_ENV", "canary")
        monkeypatch.setenv("DEPLOYMENT_ENV", "canary")
        monkeypatch.setenv("NTA_APP_ENV", "canary")
    else:
        monkeypatch.setattr(account_auth, "_authoritative_storage", lambda: True)
    if change not in {"foreign_environment", "authoritative_storage"}:
        account_auth._write_doc(document)
    before = _manifest(confirmation_store)
    assert account_auth.local_session_is_active(sid, 42) is False
    assert _manifest(confirmation_store) == before


@pytest.mark.parametrize("method,path,allowed", [
    ("GET", "/api/ai-control-center/overview", True),
    ("HEAD", "/api/ai-control-center/domains/memory", True),
    ("POST", "/api/ai-control-center/tasks/00000000-0000-4000-8000-000000000123/chat", True),
    ("POST", "/api/ai-control-center/tasks/00000000-0000-4000-8000-000000000123/cancel", False),
    ("POST", "/api/ai-control-center/domains/models/new/connect", False),
    ("POST", "/api/ai-control-center/backtests", False),
    ("POST", "/api/ai-control-center/tasks/not-a-uuid/chat", False),
    ("GET", "/api/ai-agents", False),
])
def test_trial_history_exception_is_method_and_path_bounded(monkeypatch, method, path, allowed):
    monkeypatch.setattr(server.subscriptions, "record_active_usage", lambda uid: {"expired": True})
    errors = []
    handler = SimpleNamespace(command=method, _err=lambda *args, **kwargs: errors.append(kwargs))
    assert server.Handler._enforce_trial_access(handler, path, {"user_id": 42, "session_id": "active"}) is allowed
    assert bool(errors) is (not allowed)
    context = {"user_id": 42, "user": {"ux_mode": "professional"}, "capabilities": {"ai_lab": False}, "_request_method": method}
    if allowed:
        permissions.enforce(path, context)
    else:
        with pytest.raises(permissions.PermissionError):
            permissions.enforce(path, context)


def test_history_exception_does_not_grant_student_or_mutating_post():
    with pytest.raises(permissions.PermissionError):
        permissions.enforce("/api/ai-control-center/overview", {"user": {"ux_mode": "beginner"}, "capabilities": {"ai_lab": False}})
    assert not permissions.agent_world_history_request("/api/ai-control-center/domains/models/new/connect", "POST")
