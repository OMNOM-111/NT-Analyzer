from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, personal_nt_security, secure_store, server as server_mod, subscriptions, workspaces


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


def test_workspace_dpapi_cache_is_copy_isolated_and_write_through(
    workspace_store, monkeypatch,
) -> None:
    workspaces._clear_doc_cache()
    workspaces._write_doc({
        "version": 1,
        "workspaces": [{"workspace_id": "ws_cache_TEST1234", "status": "active"}],
        "memberships": [],
        "active_workspaces": {},
        "connections": [],
        "pairings": [],
    })
    workspaces._clear_doc_cache()
    original_unprotect = secure_store._unprotect
    decrypts = []

    def counting_unprotect(value):
        decrypts.append(True)
        return original_unprotect(value)

    monkeypatch.setattr(secure_store, "_unprotect", counting_unprotect)
    first = workspaces._read_doc()
    second = workspaces._read_doc()
    assert len(decrypts) == 1
    first["workspaces"][0]["status"] = "tampered"
    assert second["workspaces"][0]["status"] == "active"
    assert workspaces._read_doc()["workspaces"][0]["status"] == "active"

    updated = workspaces._read_doc()
    updated["workspaces"][0]["status"] = "revoked"
    workspaces._write_doc(updated)
    assert workspaces._read_doc()["workspaces"][0]["status"] == "revoked"
    assert len(decrypts) == 1


def test_phase3_workspace_identity_backfill_preserves_legacy_references(workspace_store) -> None:
    account_auth._write_doc({
        "version": 3,
        "users": [{
            "user_id": 42,
            "legacy_user_id": 42,
            "user_uuid": "9b2c8d86-7ce3-4ee0-aa1f-9b9e0b6b77c1",
            "first_name": "Ada",
            "status": "active",
            "is_owner": False,
        }],
        "auth_identities": [],
        "challenges": [],
        "sessions": [],
    })
    workspaces._write_doc({
        "version": 1,
        "workspaces": [{
            "workspace_id": "ws_personal_PHASE3TEST",
            "owner_user_id": 42,
            "kind": "personal",
            "status": "active",
        }],
        "memberships": [{
            "workspace_id": "ws_personal_PHASE3TEST", "user_id": 42,
            "created_by_user_id": 42, "role": "owner",
        }],
        "active_workspaces": {"42": "ws_personal_PHASE3TEST"},
        "connections": [{
            "connection_id": "conn_phase3", "workspace_id": "ws_personal_PHASE3TEST",
            "owner_user_id": 42, "status": "online",
        }],
        "pairings": [{
            "pairing_id": "pair_phase3", "workspace_id": "ws_personal_PHASE3TEST",
            "created_by_user_id": 42,
        }],
    })

    migrated = workspaces._read_doc()
    user_uuid = "9b2c8d86-7ce3-4ee0-aa1f-9b9e0b6b77c1"

    assert migrated["workspaces"][0]["owner_user_id"] == 42
    assert migrated["workspaces"][0]["owner_user_uuid"] == user_uuid
    assert migrated["memberships"][0]["user_id"] == 42
    assert migrated["memberships"][0]["user_uuid"] == user_uuid
    assert migrated["memberships"][0]["created_by_user_uuid"] == user_uuid
    assert migrated["connections"][0]["owner_user_uuid"] == user_uuid
    assert migrated["pairings"][0]["created_by_user_uuid"] == user_uuid
    assert migrated["active_workspaces"]["42"] == "ws_personal_PHASE3TEST"
    assert migrated["active_workspaces_by_uuid"][user_uuid] == "ws_personal_PHASE3TEST"


def test_phase3_workspace_creation_dual_writes_uuid_companions(workspace_store) -> None:
    user_uuid = "d69c90cb-9db9-4a10-aa76-18dcb816eab7"
    account_auth._write_doc({
        "version": 3,
        "users": [{
            "user_id": 42, "legacy_user_id": 42, "user_uuid": user_uuid,
            "first_name": "Ada", "status": "active", "is_owner": False,
        }],
        "auth_identities": [], "challenges": [], "sessions": [],
    })

    workspace = workspaces.ensure_personal_workspace(42, require_entitlement=False)
    pairing = workspaces.start_bridge_pairing(42, workspace_id=workspace["workspace_id"])
    completed = workspaces.complete_bridge_pairing(
        42, code=pairing["code"], device_id="device-phase3",
        bridge_instance_id="bridge-phase3",
    )

    assert workspace["owner_user_id"] == 42
    assert workspace["owner_user_uuid"] == user_uuid
    assert workspace["membership"]["user_uuid"] == user_uuid
    assert workspace["membership"]["created_by_user_uuid"] == user_uuid
    assert completed["connection"]["owner_user_uuid"] == user_uuid


def test_personal_runtime_storage_never_falls_back_to_owner_when_offline(workspace_store) -> None:
    context = {
        "active_workspace": {
            "workspace_id": "ws_personal_TEST1234",
            "kind": "personal",
            "uses_owner_runtime": False,
            "default_runtime_connection_id": "",
        }
    }

    assert workspaces.runtime_dir_for_context(context) == ""  # pairing/read stub remains active
    storage = workspaces.runtime_storage_dir_for_context(context)
    assert storage == str(workspace_store / "data" / "tenants" / "ws_personal_TEST1234" / "runtime")
    assert "data\\runtime" not in storage


def test_runtime_stub_without_workspace_is_safe_and_never_raises() -> None:
    context = {"active_workspace": {}}
    accounts = workspaces.runtime_stub("/api/ops/runtime/accounts", {}, context)
    assert accounts and accounts["source"] == "workspace_required"
    assert accounts["accounts"] == []
    history = workspaces.runtime_stub("/api/ops/runtime/account-history", {"limit": ["500"]}, context)
    assert history and history["source"] == "workspace_required"
    assert history["accounts"] == []
    assert history["workspace_id"] == ""
    instruments = workspaces.runtime_stub("/api/ops/runtime/instruments", {}, context)
    assert instruments and instruments["instruments"] == []


def _seed_auth(owner_token: str, owner_csrf: str, user_token: str, user_csrf: str) -> None:
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True},
            {
                "user_id": 42, "first_name": "Dev", "last_name": "Two", "email": "dev@example.com",
                "role": "full_control", "status": "active", "is_owner": False,
                # NT control (bridge pair) requires a verified email factor (Google
                # here), a confirmed Telegram factor and an elevated Telegram confirm.
                "telegram_user_id": 42,
                "google_sub": "google-dev-42", "google_email": "dev@gmail.com",
                "google_linked_at_utc": "2026-07-15T00:00:00Z",
            },
        ],
        "challenges": [],
        "sessions": [
            {"user_id": 999, "token_hash": hashlib.sha256(owner_token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(owner_csrf.encode()).hexdigest(), "csrf_token": owner_csrf, "expires_at": time.time() + 3600, "revoked": False},
            {
                "user_id": 42,
                "session_id": "sess_user42",
                "token_hash": hashlib.sha256(user_token.encode()).hexdigest(),
                "csrf_hash": hashlib.sha256(user_csrf.encode()).hexdigest(),
                "csrf_token": user_csrf,
                "expires_at": time.time() + 3600,
                "revoked": False,
                "nt_elevated_until": time.time() + 3600,
            },
        ],
    })


def test_workspace_auth_status_and_runtime_isolation(workspace_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv("NTA_NT_GOOGLE_REQUIRED", "1")
    monkeypatch.setenv("NTA_NT_TELEGRAM_CONFIRM_REQUIRED", "1")
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

        # Account-level full_control must never override a viewer membership in
        # the owner's runtime workspace.
        with pytest.raises(urllib.error.HTTPError) as viewer_write:
            _json_request(
                base, "/api/ops/runtime/command", method="POST",
                token=user_token, csrf=user_csrf,
                body={"command": "start", "strategy_id": "owner-strategy"},
            )
        assert viewer_write.value.code == 403

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

        # Without NT elevation / Google the bridge pair must be denied.
        bare_token = "b" * 64
        bare_csrf = "c" * 48
        doc = account_auth._read_doc()
        doc["users"].append({
            "user_id": 77, "first_name": "Bare", "last_name": "User", "email": "bare@example.com",
            "role": "full_control", "status": "active", "is_owner": False,
            "ux_mode": "professional",
            "permission_overrides": {"personal_nt": True},
        })
        doc["sessions"].append({
            "user_id": 77,
            "session_id": "sess_bare77",
            "token_hash": hashlib.sha256(bare_token.encode()).hexdigest(),
            "csrf_hash": hashlib.sha256(bare_csrf.encode()).hexdigest(),
            "csrf_token": bare_csrf,
            "expires_at": time.time() + 3600,
            "revoked": False,
        })
        account_auth._write_doc(doc)
        with pytest.raises(urllib.error.HTTPError) as blocked:
            _json_request(base, "/api/bridge/pair/start", method="POST", token=bare_token, csrf=bare_csrf, body={
                "machine_label": "No Google PC",
            })
        assert blocked.value.code == 403
        err_body = json.loads(blocked.value.read().decode("utf-8"))
        assert err_body.get("code") == "nt_google_required"

        # Phase 5: a personal-NT pairing needs both factors and a fresh, single-
        # use step-up grant. Inject a confirmed grant directly (no test-auth here).
        grant_doc = account_auth._read_doc()
        grant_user = account_auth._user(grant_doc, 42)
        grant_doc.setdefault("security_challenges", []).append({
            "challenge_id": "grant_pair_42",
            "user_uuid": account_auth._user_uuid(grant_user),
            "legacy_user_id": 42,
            "purpose": "step_up",
            "action": "pairing",
            "environment": personal_nt_security._current_environment(),
            "status": "consumed",
            "consumed_at_utc": account_auth._now_iso(),
            "expires_at": time.time() + 600,
        })
        account_auth._write_doc(grant_doc)

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
