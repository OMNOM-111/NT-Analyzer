from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.error
import urllib.request
import threading
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, telegram_remote
from app import server as server_mod


TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"


def _init_data(user_id: int, *, auth_date: int | None = None, token: str = TOKEN) -> str:
    values = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAE-test",
        "user": json.dumps({"id": user_id, "first_name": "Test", "username": "tester"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(values)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(telegram_remote, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    with telegram_remote._RATE_LOCK:
        telegram_remote._RATE.clear()
    return tmp_path


def test_init_data_hmac_and_freshness() -> None:
    valid = _init_data(42)
    assert telegram_remote.validate_init_data(valid, TOKEN)["user"]["id"] == 42

    tampered = valid.replace("tester", "intruder")
    with pytest.raises(telegram_remote.RemoteAccessError) as exc:
        telegram_remote.validate_init_data(tampered, TOKEN)
    assert exc.value.status == 401

    with pytest.raises(telegram_remote.RemoteAccessError) as exc:
        telegram_remote.validate_init_data(_init_data(42, auth_date=int(time.time()) - 5000), TOKEN)
    assert exc.value.status == 401


def test_whitelist_roles_revocation_and_live_lock(isolated) -> None:
    telegram_remote._write({
        "remote_enabled": True,
        "users": [{"user_id": 42, "role": "read_only", "status": "active"}],
        "pairings": [],
    })
    raw = _init_data(42)
    context = telegram_remote.authorize(raw, TOKEN, method="GET", path="/api/health", tunnel_ip="127.0.0.1")
    assert context["role"] == "read_only"

    with pytest.raises(telegram_remote.RemoteAccessError) as exc:
        telegram_remote.authorize(raw, TOKEN, method="POST", path="/api/jobs", tunnel_ip="127.0.0.1")
    assert exc.value.status == 403

    telegram_remote.set_user_role(42, "full_control")
    assert telegram_remote.authorize(raw, TOKEN, method="POST", path="/api/jobs", tunnel_ip="127.0.0.1")["role"] == "full_control"
    with pytest.raises(telegram_remote.RemoteAccessError):
        telegram_remote.authorize(raw, TOKEN, method="POST", path="/api/ops/live/unlock-request", tunnel_ip="127.0.0.1")

    telegram_remote.revoke_user(42)
    with pytest.raises(telegram_remote.RemoteAccessError):
        telegram_remote.authorize(raw, TOKEN, method="GET", path="/api/health", tunnel_ip="127.0.0.1")


def test_two_step_pairing_contact_and_owner_approval(isolated) -> None:
    telegram_remote.update_settings({"owner_phone": "+1 555 123 4567"})
    pair = telegram_remote.start_pairing(
        bot_username="StratForge_test_bot", role="full_control",
        expected_user_id=42, require_phone=True,
    )
    calls = []

    def api(method, payload=None, **_kwargs):
        calls.append((method, payload or {}))
        return {}

    consumed = telegram_remote.process_update({
        "message": {
            "text": f"/start access_{pair['code']}",
            "from": {"id": 42, "username": "operator", "first_name": "Operator"},
            "chat": {"id": 42, "type": "private"},
        },
    }, api_call=api, owner_chat_id="999")
    assert consumed is True
    assert any(row[1].get("reply_markup", {}).get("keyboard") for row in calls)

    telegram_remote.process_update({
        "message": {
            "contact": {"user_id": 42, "phone_number": "+15551234567"},
            "from": {"id": 42}, "chat": {"id": 42, "type": "private"},
        },
    }, api_call=api, owner_chat_id="999")
    assert any("inline_keyboard" in row[1].get("reply_markup", {}) for row in calls)

    telegram_remote.process_update({
        "callback_query": {
            "id": "cb-1", "data": f"remote_allow:{pair['request_id']}",
            "from": {"id": 999},
        },
    }, api_call=api, owner_chat_id="999")
    status = telegram_remote.admin_status()
    user = next(row for row in status["users"] if row["user_id"] == 42)
    assert user["status"] == "active"
    assert user["role"] == "full_control"
    assert user["phone_verified"] is True


def test_audit_contains_required_identity_and_tunnel_fields(isolated) -> None:
    telegram_remote.audit(
        method="POST", path="/api/jobs", status=200,
        context={"user_id": 42, "role": "full_control"},
        tunnel_ip="127.0.0.1", forwarded_ip="203.0.113.9",
    )
    row = json.loads(telegram_remote._audit_path().read_text(encoding="utf-8").strip())
    assert row["source"] == "telegram_mini_app"
    assert row["user_id"] == 42
    assert row["tunnel_ip"] == "127.0.0.1"
    assert row["timestamp"].endswith("Z")


def test_public_host_requires_init_data_and_accepts_whitelisted_user(isolated, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv("NTA_TELEGRAM_BOT_TOKEN", TOKEN)
    telegram_remote._write({
        "remote_enabled": True,
        "users": [{"user_id": 42, "role": "read_only", "status": "active"}],
        "pairings": [],
    })
    srv = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://{srv.server_address[0]}:{srv.server_address[1]}/api/health"
        good = urllib.request.Request(url, headers={
            "Host": "stratforge.example.com",
            telegram_remote.INIT_DATA_HEADER: _init_data(42),
        })
        with urllib.request.urlopen(good, timeout=5) as response:
            assert response.status == 200

        missing = urllib.request.Request(url, headers={"Host": "stratforge.example.com"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(missing, timeout=5)
        assert exc.value.code == 401
    finally:
        srv.shutdown()
        srv.server_close()


def test_aurora_bundle_carries_init_data_and_mobile_contract() -> None:
    root = server_mod.STATIC_DIR / "aurora"
    api = (root / "assets" / "api.js").read_text(encoding="utf-8")
    css = (root / "assets" / "theme.css").read_text(encoding="utf-8")
    ui = (root / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "X-Telegram-Init-Data" in api
    assert "telegramRemoteMe" in api
    assert "telegram-mini-app" in css
    assert "Новый аккаунт активируется только вашим подтверждением" in ui
    assert "https://web.telegram.org" in server_mod.STATIC_CSP
