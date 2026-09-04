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


def test_rate_limit_bypass_applies_only_to_staging(monkeypatch) -> None:
    monkeypatch.setenv("NTA_DISABLE_RATE_LIMIT", "1")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    for offset in range(telegram_remote.READ_LIMIT_PER_MINUTE + 1):
        telegram_remote._rate_check(42, "127.0.0.1", "GET", now=float(offset))

    monkeypatch.setenv("NTA_APP_ENV", "production")
    with telegram_remote._RATE_LOCK:
        telegram_remote._RATE.clear()
    for offset in range(telegram_remote.READ_LIMIT_PER_MINUTE):
        telegram_remote._rate_check(42, "127.0.0.1", "GET", now=float(offset) / 1000)
    with pytest.raises(telegram_remote.RemoteAccessError) as exc:
        telegram_remote._rate_check(42, "127.0.0.1", "GET", now=1.0)
    assert exc.value.status == 429


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


def test_read_only_viewer_can_poll_chart_bars(isolated) -> None:
    # Charts are read-only observation; a viewer must be able to POST the batch
    # bars request (it carries its request list in the body) so the desktop grid
    # works in the Telegram Mini App exactly like the local UI.
    telegram_remote._write({
        "remote_enabled": True,
        "users": [{"user_id": 42, "role": "read_only", "status": "active"}],
        "pairings": [],
    })
    raw = _init_data(42)
    context = telegram_remote.authorize(
        raw, TOKEN, method="POST", path="/api/ops/runtime/bars/batch", tunnel_ip="127.0.0.1")
    assert context["role"] == "read_only"
    # A genuine mutation still requires full control.
    with pytest.raises(telegram_remote.RemoteAccessError) as exc:
        telegram_remote.authorize(
            raw, TOKEN, method="POST", path="/api/ops/runtime/price-alerts", tunnel_ip="127.0.0.1")
    assert exc.value.status == 403


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


def test_public_host_rejects_retired_init_data_even_for_whitelisted_user(isolated, monkeypatch) -> None:
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
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(good, timeout=5)
        assert exc.value.code == 410
        assert json.loads(exc.value.read().decode("utf-8"))["code"] == "telegram_mini_app_isolated"

        missing = urllib.request.Request(url, headers={"Host": "stratforge.example.com"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(missing, timeout=5)
        assert exc.value.code == 401
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.parametrize(
    ("browser_uuid", "state_merged"),
    [
        ("2f53c640-497e-4d91-8f3b-37a7496f5e80", True),
        ("1ee2356e-d4e5-47ae-8ca0-49f3e8d4f2a0", False),
    ],
)
def test_browser_session_merge_requires_matching_canonical_uuid(
    monkeypatch, browser_uuid, state_merged,
) -> None:
    remote_uuid = "2f53c640-497e-4d91-8f3b-37a7496f5e80"
    elevated_until = time.time() + 600
    remote_context = {
        "source": telegram_remote.SOURCE,
        "user_id": 42,
        "role": "read_only",
        "is_owner": False,
        "user": {"id": remote_uuid},
    }

    class Request:
        command = "GET"
        headers = {telegram_remote.INIT_DATA_HEADER: "signed-init-data"}

        def _is_remote_api_request(self):
            return True

        def _local_owner_bypass_allowed(self):
            # A remote (Mini App) request is never a local owner/service bypass.
            return False

        def _request_ips(self):
            return "", ""

        def _cookie_value(self, _name):
            return "browser-session"

        def _decorate_workspace_context(self, value):
            return value

        def _check_api_rate_limit(self, _context, _path):
            return True

        def _err(self, status, message, **kwargs):
            self.error = (int(status), message, str(kwargs.get("code") or ""))

    monkeypatch.setattr(server_mod.account_auth, "auth_required", lambda: True)
    monkeypatch.setattr(
        server_mod.telegram_remote, "authorize", lambda *_args, **_kwargs: dict(remote_context),
    )
    monkeypatch.setattr(
        server_mod.account_auth, "authenticate_session",
        lambda _token: {
            "user_id": 42,
            "user_uuid": browser_uuid,
            "session_id": "sess_browser",
            "nt_elevated_until": elevated_until,
            "device_confirmation_state": "active",
            "device_confirmation_required": False,
            "device_trust_mode": "permanent",
        },
    )
    monkeypatch.setattr(
        server_mod.account_auth, "user_uuid_for_legacy_id",
        lambda user_id: remote_uuid if int(user_id) == 42 else "",
    )
    monkeypatch.setattr(server_mod.permissions, "enforce", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        server_mod.permissions, "required_admin_capability", lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        server_mod.account_auth, "path_requires_nt_dual_auth", lambda *_args, **_kwargs: False,
    )

    request = Request()

    assert server_mod.Handler._authorize_api(request, "/api/health") is state_merged
    assert request._remote_context["user_uuid"] == remote_uuid
    if state_merged:
        assert request._remote_context["session_id"] == "sess_browser"
        assert request._remote_context["nt_elevated_until"] == elevated_until
    else:
        assert "session_id" not in request._remote_context
        assert "nt_elevated_until" not in request._remote_context
        assert request.error[0] == 403
        assert request.error[2] == "DEVICE_CONFIRMATION_REQUIRED"


def test_aurora_bundle_excludes_miniapp_and_keeps_current_login_contract() -> None:
    root = server_mod.STATIC_DIR / "aurora"
    api = (root / "assets" / "api.js").read_text(encoding="utf-8")
    css = (root / "assets" / "theme.css").read_text(encoding="utf-8")
    ui = (root / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "X-Telegram-Init-Data" not in api
    assert "telegramRemoteMe" not in api
    assert "telegram-mini-app" not in css
    assert "authLoginStart" in api
    assert "telegramStatus" in api
    assert "новый пользователь автоматически получает полный пробный доступ к продукту на ${trialDays()} дней" in ui
    assert "Живые графики используют только разрешённый для аккаунта источник market data" in ui
    assert "Новый аккаунт активируется только вашим подтверждением" not in ui
    assert "https://web.telegram.org" not in server_mod.STATIC_CSP
