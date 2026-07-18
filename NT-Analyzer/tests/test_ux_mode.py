"""Phase E: beginner / professional UX modes (§9 / §9.0 / checklist 9.4)."""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, community, google_auth, permissions, practice_trading, runtime_env, subscriptions, test_auth, workspaces
from app import server as server_mod
from app import telegram_service


@pytest.fixture()
def ux_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("NTA_APP_ENV", "staging")
    monkeypatch.setenv("NTA_ENABLE_TEST_AUTH", "1")
    monkeypatch.setenv("NTA_DUAL_AUTH_REQUIRED", "1")
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(google_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(practice_trading, "_root", lambda: tmp_path)
    monkeypatch.setattr(community, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(account_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(account_auth.secure_store, "available", lambda: True)
    monkeypatch.setattr(google_auth.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(google_auth.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(subscriptions.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(subscriptions.secure_store, "_unprotect", lambda b: b)
    monkeypatch.setattr(subscriptions.secure_store, "available", lambda: True)
    monkeypatch.setattr(workspaces.secure_store, "_protect", lambda b: b)
    monkeypatch.setattr(workspaces.secure_store, "_unprotect", lambda b: b)
    (tmp_path / "data" / "integrations").mkdir(parents=True)
    (tmp_path / "data" / "audit").mkdir(parents=True)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    account_auth._write_doc({
        "version": 1,
        "users": [
            {
                "user_id": 999, "username": "owner", "first_name": "Owner",
                "role": "owner", "status": "active", "is_owner": True,
                "google_sub": "owner-google", "google_linked_at_utc": "2026-01-01T00:00:00Z",
            },
        ],
        "challenges": [],
        "sessions": [],
    })
    account_auth.set_auth_required(True)
    return tmp_path


def _token_row(user_id: int, token: str, csrf: str, **extra):
    row = {
        "session_id": "sess_" + token[:8],
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
        "csrf_token": csrf,
        "user_id": user_id,
        "created_at_utc": "2026-07-15T00:00:00Z",
        "expires_at": 4_000_000_000,
        "revoked": False,
        "device_id": "dev",
        "client": "Chrome",
        "machine": "PC",
        "ip": "127.0.0.1",
    }
    row.update(extra)
    return row


def _request(base: str, path: str, *, token: str = "", csrf: str = "", method: str = "GET", body=None):
    data = None
    headers = {"Origin": base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw}
        return exc.code, payload


@pytest.fixture()
def http_server(ux_store, monkeypatch):
    monkeypatch.setenv("NTA_DISABLE_RATE_LIMIT", "1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base
    server.shutdown()


def test_owner_always_professional(ux_store) -> None:
    public = account_auth._public_user({"user_id": 999, "is_owner": True, "ux_mode": "beginner"})
    assert public["ux_mode"] == "professional"
    assert public["needs_ux_mode"] is False
    perm = permissions.resolve({"is_owner": True, "ux_mode": "beginner"})
    assert perm["ux_mode"] == "professional"
    assert perm["nav"]["strategies"] is True
    assert perm["nav"]["practice"] is False


def test_beginner_nav_and_caps() -> None:
    perm = permissions.resolve({"is_owner": False, "ux_mode": "beginner"}, {})
    assert perm["nav"]["practice"] is True
    assert perm["nav"]["strategies"] is False
    assert perm["nav"]["ai"] is False
    assert perm["nav"]["community"] is True
    assert perm["nav"]["news"] is False
    assert perm["nav"]["docs"] is False
    assert "micro_live" not in perm["nav"]
    assert perm["nav"]["overview"] is False
    assert perm["capabilities"]["practice_trading"] is True
    assert perm["capabilities"]["ai_lab"] is False
    assert perm["capabilities"]["community"] is True


def test_ux_pending_locks_everything() -> None:
    perm = permissions.resolve({"is_owner": False}, {})
    assert perm["ux_pending"] is True
    assert all(not v for v in perm["nav"].values())


def test_mode_switch_rules(ux_store) -> None:
    user = account_auth.create_or_update_virtual_user(
        user_id=5001, username="u", first_name="U", ux_mode="",
    )
    assert user["needs_ux_mode"] is True
    out = account_auth.set_ux_mode(5001, "beginner")
    assert out["ux_mode"] == "beginner"
    out = account_auth.set_ux_mode(5001, "professional")
    assert out["ux_mode"] == "professional"
    with pytest.raises(account_auth.AccountAuthError) as exc:
        account_auth.set_ux_mode(5001, "beginner")
    assert exc.value.status == 409
    assert exc.value.code == "ux_mode_confirm_required"
    out = account_auth.set_ux_mode(5001, "beginner", confirm_downgrade=True)
    assert out["ux_mode"] == "beginner"
    forced = account_auth.set_ux_mode(999, "beginner")
    assert forced["ux_mode"] == "professional"


def test_staging_presets(ux_store) -> None:
    assert "beginner" in test_auth.PRESETS
    assert "professional" in test_auth.PRESETS
    b = test_auth.create_virtual_user(preset="beginner", telegram_id=5101)
    assert b["user"]["ux_mode"] == "beginner"
    p = test_auth.create_virtual_user(preset="professional", telegram_id=5102)
    assert p["user"]["ux_mode"] == "professional"
    n = test_auth.create_virtual_user(preset="new", telegram_id=5103)
    assert n["user"]["needs_ux_mode"] is True


def test_api_beginner_deny_and_practice_ok(http_server, ux_store) -> None:
    account_auth.create_or_update_virtual_user(
        user_id=5201, username="beg", first_name="Beg", ux_mode="beginner", role="full_control",
    )
    workspace_id = workspaces.context_for_user(5201, owner_id=999)["active_workspace"]["workspace_id"]
    practice_trading.create_account(5201, deposit=10000, workspace_id=workspace_id)
    token, csrf = "b" * 64, "c" * 48
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc["sessions"].append(_token_row(5201, token, csrf))
        account_auth._write_doc(doc)

    status, _ = _request(http_server, "/api/community/feed", token=token)
    assert status == 200
    status, _ = _request(http_server, "/api/ai-lab/summary", token=token)
    assert status == 403
    status, _ = _request(http_server, "/api/news", token=token)
    assert status == 403
    status, _ = _request(http_server, "/api/governance/documents", token=token)
    assert status == 403
    status, _ = _request(http_server, "/api/micro-live/account", token=token)
    assert status == 404
    status, body = _request(http_server, "/api/practice/account", token=token)
    assert status == 200
    acct = body.get("account") if isinstance(body.get("account"), dict) else body
    assert float(acct.get("balance") or 0) >= 10000
    status, body = _request(
        http_server, "/api/practice/reset", token=token, csrf=csrf, method="POST", body={},
    )
    assert status == 200, body
    assert body.get("deleted") is True
    status, _ = _request(http_server, "/api/practice/account", token=token)
    assert status == 404


def test_api_set_ux_mode(http_server, ux_store) -> None:
    account_auth.create_or_update_virtual_user(
        user_id=5301, username="pick", first_name="Pick", ux_mode="",
    )
    token, csrf = "d" * 64, "e" * 48
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc["sessions"].append(_token_row(5301, token, csrf))
        account_auth._write_doc(doc)

    status, _ = _request(http_server, "/api/practice/account", token=token)
    assert status == 403
    status, body = _request(
        http_server, "/api/auth/ux-mode", token=token, csrf=csrf, method="POST",
        body={"ux_mode": "beginner"},
    )
    assert status == 200, body
    assert body.get("ux_mode") == "beginner"
    assert body.get("features", {}).get("practice") is True
    assert body.get("features", {}).get("strategies") is False
    workspace_id = workspaces.context_for_user(5301, owner_id=999)["active_workspace"]["workspace_id"]
    practice_trading.create_account(5301, deposit=10000, workspace_id=workspace_id)
    status, _ = _request(http_server, "/api/practice/account", token=token)
    assert status == 200


def test_ui_contracts_ux_mode_markers() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (root / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    assert "renderUxModeGate" in ui
    assert "authUxMode" in api
    assert "ux-mode-gate" in ui
    assert "maybeRedirectBeginnerHome" in ui
    assert "mode-entry.html" in ui
    assert "STUDENT_NAV_IDS" in ui
    assert "applyStudentShell" in ui
    assert "startDesktopCommandBridge();" in ui
    student_scope = ui.split("if (!studentShell) {", 1)[1].split("// Student can still", 1)[0]
    assert "startDesktopCommandBridge();" in student_scope
    assert "wireSystemStatus();" in student_scope
    victor = (root / "app" / "static" / "aurora" / "assets" / "victor.js").read_text(encoding="utf-8")
    assert "mode === 'beginner'" in victor
    assert "auth.is_owner || auth.role === 'owner'" in victor
    assert "micro-live.html" not in ui
    assert "data-set-ux" in ui
    css = (root / "app" / "static" / "aurora" / "assets" / "theme.css").read_text(encoding="utf-8")
    assert "ux-mode-choice" in css
    assert "mode-entry-option" in css
    assert "@media (max-width: 720px)" in css


def test_practice_wallet_first_dom_contract() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "aurora" / "practice-trading.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "aurora" / "assets" / "pages" / "practice.js").read_text(encoding="utf-8")
    assert 'id="practice-onboard"' in html
    assert 'id="practice-desk"' in html
    assert 'id="p-deposit"' in html
    assert "Какую сумму виртуальных денег" in html
    assert "practice-onboard" in js
    assert "showOnboard" in js
    assert "showDesk" in js
    assert "ChartEngine" in js
    assert 'id="p-timeframe"' in html
    assert 'id="p-bid"' in html and 'id="p-ask"' in html and 'id="p-last"' in html
    assert 'id="p-retry-data"' in html
    assert 'id="p-sell"' in html
    assert "practiceCancelOrder" in js
    assert "practiceReset" in js
    assert "gap_recovery" in js
    assert "freshness" in js
    assert "bid_ask_estimated" in js
    assert "marketIsTradable" in js
    assert "p-order-state" in html
    assert "applyGuestPracticeLock" in js
    assert "requireSignIn" in js
    assert "body.price = price" not in js
    server = (root / "app" / "server.py").read_text(encoding="utf-8")
    practice_tick = server.split('if path == "/api/practice/tick":', 1)[1].split(
        'if path == "/api/demo-backtests":', 1,
    )[0]
    assert "_practice_market_quote(" in practice_tick
    assert "market=market" in practice_tick
    assert "market_data.latest_close" not in practice_tick
    assert 'body.get("price"' not in practice_tick
    # Ticket lives only inside desk — onboard must not embed Buy/MNQ as first step.
    onboard = html.split('id="practice-onboard"', 1)[1].split('id="practice-desk"', 1)[0]
    assert "p-buy" not in onboard
    assert "Buy / Long" not in onboard


def test_guest_practice_preview_has_no_create_action() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    practice = (root / "app" / "static" / "aurora" / "assets" / "pages" / "practice.js").read_text(encoding="utf-8")
    assert "function requireSignIn()" in ui
    assert "renderWelcomeAccess({ asOverlay: true })" in ui
    assert "practice-guest-locked" in practice
    assert "#practice-onboard button, #practice-onboard input" in practice
    assert "if (isGuestPreview()) {" in practice


def test_mode_entry_is_a_real_root_page() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    entry = (root / "app" / "static" / "aurora" / "mode-entry.html").read_text(encoding="utf-8")
    script = (root / "app" / "static" / "aurora" / "assets" / "pages" / "mode-entry.js").read_text(encoding="utf-8")
    assert 'data-mode="beginner"' in entry
    assert 'data-mode="professional"' in entry
    assert "authUxMode" in script
    assert "practice-trading.html" in script
    assert "index.html" in script


def test_payment_request_ui_requires_a_configured_paypal() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    assert 'id="cab-donate-paid" ${paypal ? \'\' : \'disabled\'}' in ui
    assert "if (!paypal) { toast('PayPal владельца ещё не настроен'); return; }" in ui
    assert "if (wantAccess()) await requestAccess" not in ui


def test_practice_wallet_flow_beginner(ux_store) -> None:
    account_auth.create_or_update_virtual_user(
        user_id=5401, username="wallet", first_name="Wallet", ux_mode="beginner",
    )
    doc = practice_trading.create_account(5401, deposit=25000)
    acct = doc.get("account") if isinstance(doc.get("account"), dict) else doc
    bal0 = float(acct.get("balance") or acct.get("equity") or 0)
    assert bal0 >= 25000
    tick = practice_trading.tick_marks(5401, symbol="MNQ")
    assert isinstance(tick, dict)
