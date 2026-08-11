"""Phase 11c — local Development canonical storage + Claude/GPT service accounts.

Covers:
- ``account_auth.primary_owner`` / ``primary_owner_id`` resolve the real owner
  from the local store (so a localhost dev session shows the real profile/data
  instead of an empty synthetic ``ws_local_owner`` scope);
- the Development-only Claude and GPT service accounts get owner-level authority
  over the *owner's* workspace and data, with a distinct id for separate audit;
- login is Development-only and localhost-only (impossible in Canary/Production);
- the reserved service id band stays inside the JavaScript safe-integer range;
- the server wires the loopback bypass and the login endpoint with those guards.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import account_auth, dev_service_accounts, secure_store, workspaces  # noqa: E402

OWNER_ID = 1647145559


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.delenv("STRATFORGE_ENV", raising=False)
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", str(OWNER_ID))
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_store_path", lambda: tmp_path / "workspaces.dpapi")
    monkeypatch.setattr(workspaces, "_audit_path", lambda: tmp_path / "workspace-access.jsonl")
    workspaces._clear_doc_cache()
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(secure_store, "_unprotect", lambda b: b)
    account_auth._write_doc({
        "version": account_auth.ACCOUNT_STORE_VERSION,
        "users": [
            {"user_id": OWNER_ID, "first_name": "DMYTRO", "last_name": "CHEREVKO",
             "username": "dimon_check", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 424242, "first_name": "", "last_name": "", "role": "owner",
             "status": "active", "is_owner": True},
            {"user_id": 55, "first_name": "Reader", "last_name": "One", "role": "read_only",
             "status": "active", "is_owner": False},
        ],
        "sessions": [], "challenges": [],
    })
    return tmp_path


# --------------------------------------------------------------------------- #
# Owner resolution.
# --------------------------------------------------------------------------- #
def test_primary_owner_prefers_configured_chat_id(store, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", str(OWNER_ID))
    assert account_auth.primary_owner_id() == OWNER_ID
    owner = account_auth.primary_owner()
    assert owner and owner["first_name"] == "DMYTRO"


def test_primary_owner_falls_back_to_named_owner(store, monkeypatch):
    # No configured chat id: the named owner beats the empty-name owner.
    monkeypatch.delenv("NTA_TELEGRAM_CHAT_ID", raising=False)
    assert account_auth.primary_owner_id() == OWNER_ID


def test_primary_owner_none_without_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(secure_store, "_unprotect", lambda b: b)
    account_auth._write_doc({"version": account_auth.ACCOUNT_STORE_VERSION,
                             "users": [], "sessions": [], "challenges": []})
    assert account_auth.primary_owner_id() == 0
    assert account_auth.primary_owner() is None


# --------------------------------------------------------------------------- #
# Service accounts.
# --------------------------------------------------------------------------- #
def test_service_uids_are_js_safe_and_distinct():
    js_max = 9_007_199_254_740_991
    uids = [spec["uid"] for spec in dev_service_accounts.SERVICE_ACCOUNTS.values()]
    assert len(set(uids)) == len(uids)
    for uid in uids:
        assert 10_000_000_000 < uid < js_max  # above real Telegram ids, JS-safe


def test_ensure_service_accounts_binds_to_owner_workspace(store):
    out = dev_service_accounts.ensure_service_accounts()
    assert out["owner_id"] == OWNER_ID
    owner_ws = workspaces.context_for_user(OWNER_ID, is_owner=True, owner_id=OWNER_ID)
    owner_ws_id = owner_ws["active_workspace"]["workspace_id"]
    for entry in out["accounts"]:
        assert entry["workspace_id"] == owner_ws_id
        ctx = workspaces.context_for_user(entry["user_id"], is_owner=True, owner_id=0)
        assert ctx["active_workspace"]["workspace_id"] == owner_ws_id
        assert ctx["active_workspace"]["uses_owner_runtime"] is True
        assert ctx["active_membership"]["role"] == "owner"


def test_login_mints_session_and_is_loopback_only(store):
    with pytest.raises(dev_service_accounts.DevServiceError) as exc:
        dev_service_accounts.login("claude", is_loopback=False)
    assert exc.value.status == 403 and exc.value.code == "loopback_required"

    out = dev_service_accounts.login("claude", is_loopback=True)
    assert out["ok"] and out["actor"] == "claude"
    assert out["session_token"]
    session = account_auth.authenticate_session(out["session_token"])
    assert session and int(session["user_id"]) == dev_service_accounts.SERVICE_ACCOUNTS["claude"]["uid"]


def test_login_rejects_unknown_actor(store):
    with pytest.raises(dev_service_accounts.DevServiceError) as exc:
        dev_service_accounts.login("hacker", is_loopback=True)
    assert exc.value.code == "actor_invalid"


def test_available_is_development_only(store, monkeypatch):
    assert dev_service_accounts.available() is True
    monkeypatch.setenv("DEPLOYMENT_ENV", "production")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(store / "prod"))
    assert dev_service_accounts.available() is False
    with pytest.raises(dev_service_accounts.DevServiceError) as exc:
        dev_service_accounts.login("claude", is_loopback=True)
    assert exc.value.code == "dev_only"


# --------------------------------------------------------------------------- #
# Server wiring (source contract — no HTTP server needed).
# --------------------------------------------------------------------------- #
def test_server_wires_loopback_service_session_and_login_guards():
    src = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
    # Loopback bypass honors a service session before defaulting to the owner.
    idx = src.index("def _authorize_api(")
    body = src[idx: src.index("def _check_local_post(", idx)]
    assert "_local_development_cookie_context()" in body
    local_idx = src.index("def _local_development_cookie_context(")
    local_body = src[local_idx: src.index("def _dev_service_context(", local_idx)]
    assert "dev_service_accounts.available()" in local_body
    assert "dev_service_accounts.is_service_uid(" in local_body
    assert "_dev_service_context(" in local_body
    assert "_local_owner_context()" in local_body
    # Owner fallback uses the canonical store owner.
    assert "primary_owner_id()" in src
    # The login endpoint is Development + loopback gated.
    login = src[src.index("def _dev_service_login("): src.index("def _dev_service_login(") + 1200]
    assert "dev_service_accounts.available()" in login
    assert "loopback_required" in login
    assert 'path == "/api/dev/service-login"' in src


def test_local_owner_bypass_is_loopback_only_and_never_explicit_prod(monkeypatch):
    """The desktop owner/service auto-login is Development + loopback only.

    Development on 127.0.0.1 resolves the owner without a flag (fixes the
    Telegram-login-on-restart regression), endpoint tests keep the explicit
    test bypass, and an explicitly-selected Canary/Production deployment can
    never auto-login — whatever any flag or config reports.
    """
    from app import server as server_mod
    from app import runtime_env

    class FakeRequest:
        remote = False
        ips = ("127.0.0.1", "")
        _is_loopback_ip = staticmethod(server_mod.Handler._is_loopback_ip)

        def _is_remote_api_request(self):
            return self.remote

        def _request_ips(self):
            return self.ips

    def allowed(*, env, explicit, auth_required, remote=False, ips=("127.0.0.1", "")):
        monkeypatch.setattr(server_mod.runtime_env, "deployment_environment", lambda: env)
        monkeypatch.setattr(server_mod.runtime_env, "environment_explicit", lambda: explicit)
        monkeypatch.setattr(server_mod.account_auth, "auth_required", lambda: auth_required)
        req = FakeRequest()
        req.remote = remote
        req.ips = ips
        return server_mod.Handler._local_owner_bypass_allowed(req)

    # Development loopback → owner auto-login even without any bypass flag.
    assert allowed(env=runtime_env.DEVELOPMENT, explicit=True, auth_required=True) is True
    assert allowed(env=runtime_env.DEVELOPMENT, explicit=False, auth_required=True) is True
    # Endpoint tests: default (implicit production) env + explicit test bypass.
    assert allowed(env=runtime_env.PRODUCTION, explicit=False, auth_required=False) is True
    # Hard invariant: an explicit Canary/Production deployment never bypasses,
    # even if auth is somehow reported as not required.
    assert allowed(env=runtime_env.CANARY, explicit=True, auth_required=False) is False
    assert allowed(env=runtime_env.PRODUCTION, explicit=True, auth_required=False) is False
    assert allowed(env=runtime_env.CANARY, explicit=True, auth_required=True) is False
    # Remote / Mini App requests are never local.
    assert allowed(env=runtime_env.DEVELOPMENT, explicit=True, auth_required=True, remote=True) is False
    # Non-loopback client / forwarded IP is rejected even in Development.
    assert allowed(env=runtime_env.DEVELOPMENT, explicit=True, auth_required=True, ips=("10.0.0.9", "")) is False
    assert allowed(env=runtime_env.DEVELOPMENT, explicit=True, auth_required=True, ips=("127.0.0.1", "8.8.8.8")) is False
