from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, secure_store, server as server_mod, subscriptions, workspaces


@pytest.fixture
def workspace_store(monkeypatch, tmp_path):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    with account_auth._RATE_LOCK:
        account_auth._LOGIN_RATE.clear()
    return tmp_path


def _json_request(base: str, path: str, *, method: str = "GET", body: dict | None = None,
                  token: str = "", csrf: str = "") -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Cookie": f"{account_auth.SESSION_COOKIE}={token}"} if token else {}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Origin": base})
    if csrf:
        headers["X-CSRF-Token"] = csrf
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _seed_auth(owner_token: str, owner_csrf: str, user_token: str, user_csrf: str) -> None:
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 42, "first_name": "Dev", "last_name": "Two", "email": "dev@example.com", "role": "read_only", "status": "active", "is_owner": False},
        ],
        "challenges": [],
        "sessions": [
            {"user_id": 999, "token_hash": hashlib.sha256(owner_token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(owner_csrf.encode()).hexdigest(), "csrf_token": owner_csrf, "expires_at": time.time() + 3600, "revoked": False},
            {"user_id": 42, "token_hash": hashlib.sha256(user_token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(user_csrf.encode()).hexdigest(), "csrf_token": user_csrf, "expires_at": time.time() + 3600, "revoked": False},
        ],
    })


def test_workspace_auth_status_and_runtime_isolation(workspace_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    account_auth.set_auth_required(True)
    owner_token = "o" * 64
    owner_csrf = "p" * 48
    user_token = "u" * 64
    user_csrf = "v" * 48
    _seed_auth(owner_token, owner_csrf, user_token, user_csrf)

    def fake_accounts_with_source() -> dict:
        runtime_dir = server_mod.ops_runtime.runtime_dir()
        tenant_accounts = runtime_dir / "accounts.json"
        if "tenants" in str(runtime_dir) and tenant_accounts.is_file():
            doc = json.loads(tenant_accounts.read_text(encoding="utf-8"))
            rows = doc.get("accounts") or []
            return {"accounts": rows, "online_accounts": rows, "source": "accounts_json", "warnings": []}
        return {
            "accounts": [{"account_name": "DEMO_OWNER", "account_mode": "demo", "is_selectable_for_online": True}],
            "online_accounts": [{"account_name": "DEMO_OWNER", "account_mode": "demo", "is_selectable_for_online": True}],
            "source": "accounts_json",
            "warnings": [],
        }

    monkeypatch.setattr(server_mod.ops_runtime, "read_accounts_with_source", fake_accounts_with_source)
    monkeypatch.setattr(server_mod.account_ledger, "record_accounts", lambda _payload: None)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        user_status = _json_request(base, "/api/auth/status", token=user_token)
        assert user_status["active_workspace"]["kind"] == "owner_training"
        assert user_status["active_membership"]["role"] == "viewer"

        owner_accounts = _json_request(base, "/api/ops/runtime/accounts", token=owner_token)
        assert owner_accounts["accounts"][0]["account_name"] == "DEMO_OWNER"

        created = _json_request(base, "/api/owner/vouchers", method="POST", token=owner_token, csrf=owner_csrf, body={
            "label": "Developer personal workspace",
            "grant_plan_id": "developer_free",
            "usage_limit": 1,
        })
        redeemed = _json_request(base, "/api/billing/promo/redeem", method="POST", token=user_token, csrf=user_csrf, body={
            "code": created["voucher"]["code"],
        })
        assert redeemed["personal_workspace"]["kind"] == "personal"
        personal_workspace_id = redeemed["personal_workspace"]["workspace_id"]

        personal_accounts = _json_request(base, "/api/ops/runtime/accounts", token=user_token)
        assert personal_accounts["accounts"] == []
        assert personal_accounts["source"] == "workspace_runtime_not_connected"
        assert "DEMO_OWNER" not in json.dumps(personal_accounts)

        pairing = _json_request(base, "/api/bridge/pair/start", method="POST", token=user_token, csrf=user_csrf, body={
            "machine_label": "Dev PC",
        })
        _json_request(base, "/api/bridge/pair/complete", method="POST", token=user_token, csrf=user_csrf, body={
            "code": pairing["code"],
            "device_id": "device-1",
            "bridge_instance_id": "bridge-1",
            "machine_label": "Dev PC",
            "capabilities": ["accounts_read", "paper_commands"],
        })
        tenant_runtime = workspace_store / "data" / "tenants" / personal_workspace_id / "runtime"
        tenant_runtime.mkdir(parents=True, exist_ok=True)
        (tenant_runtime / "accounts.json").write_text(json.dumps({
            "accounts": [{"account_name": "MY_NT", "account_mode": "demo", "is_selectable_for_online": True}],
        }), encoding="utf-8")

        tenant_accounts = _json_request(base, "/api/ops/runtime/accounts", token=user_token)
        assert tenant_accounts["accounts"][0]["account_name"] == "MY_NT"
        assert "DEMO_OWNER" not in json.dumps(tenant_accounts)

        event = _json_request(base, "/api/ops/runtime/account-history/events", method="POST", token=user_token, csrf=user_csrf, body={
            "account_name": "MY_NT",
            "kind": "deposit",
            "amount": 1000,
            "actor": "pytest",
            "note": "initial test funding",
        })
        assert event["event"]["amount"] == 1000
        history = _json_request(base, "/api/ops/runtime/account-history?account=MY_NT", token=user_token)
        assert history["accounts"][0]["events"][0]["note"] == "initial test funding"
    finally:
        server.shutdown()
        server.server_close()


def test_bridge_pairing_registry_for_personal_workspace(workspace_store) -> None:
    subscriptions._write_doc({
        "version": 1,
        "vouchers": [],
        "entitlements": [{
            "entitlement_id": "ent_dev",
            "user_id": 42,
            "workspace_id": "",
            "plan_id": "developer_free",
            "status": "promo_grant",
            "source": "manual",
            "source_voucher_id": "",
            "starts_at_utc": "2026-07-05T00:00:00Z",
            "expires_at_utc": "",
            "created_at_utc": "2026-07-05T00:00:00Z",
        }],
    })
    workspace = workspaces.ensure_personal_workspace(42)
    pairing = workspaces.start_bridge_pairing(42, workspace_id=workspace["workspace_id"], machine_label="Dev PC")

    completed = workspaces.complete_bridge_pairing(
        42,
        code=pairing["code"],
        device_id="device-1",
        bridge_instance_id="bridge-1",
        machine_label="Dev PC",
        capabilities=["accounts_read", "paper_commands"],
    )

    assert completed["connection"]["status"] == "online"
    assert completed["connection"]["workspace_id"] == workspace["workspace_id"]
    listed = workspaces.list_connections(42, workspace_id=workspace["workspace_id"])
    assert listed["connections"][0]["connection_id"] == completed["connection"]["connection_id"]

    with pytest.raises(workspaces.WorkspaceError):
        workspaces.complete_bridge_pairing(7, code=pairing["code"])