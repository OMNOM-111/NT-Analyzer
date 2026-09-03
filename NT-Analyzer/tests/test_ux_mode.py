"""Phase E: beginner / professional UX modes (§9 / §9.0 / checklist 9.4)."""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, community, google_auth, jobqueue, permissions, practice_trading, runtime_env, subscriptions, test_auth, workspaces
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


def _request(base: str, path: str, *, token: str = "", csrf: str = "", method: str = "GET", body=None, extra_headers=None):
    data = None
    headers = {"Origin": base}
    if token:
        headers["Cookie"] = f"{account_auth.SESSION_COOKIE}={token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    headers.update(dict(extra_headers or {}))
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
    status, social = _request(http_server, "/api/community/v2/feed", token=token)
    assert status == 200
    assert social.get("viewer", {}).get("profile_id", "").startswith("sfp_")
    assert "user_id" not in social.get("viewer", {})
    status, chat = _request(http_server, "/api/sf-chat/conversations", token=token)
    assert status == 200
    assert chat.get("ai_available") is False
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


def test_community_v2_and_sf_chat_http_acl_end_to_end(http_server, ux_store, monkeypatch) -> None:
    users = (
        (5301, "alice_http", "Alice", "a" * 64, "x" * 48),
        (5302, "bob_http", "Bob", "b" * 64, "y" * 48),
        (5303, "eve_http", "Eve", "e" * 64, "z" * 48),
    )
    for user_id, username, first_name, _, _ in users:
        account_auth.create_or_update_virtual_user(
            user_id=user_id, username=username, first_name=first_name,
            ux_mode="professional", role="full_control",
        )
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        for user_id, _, _, token, csrf in users:
            doc["sessions"].append(_token_row(user_id, token, csrf))
        account_auth._write_doc(doc)

    alice_token, alice_csrf = users[0][3], users[0][4]
    bob_token, bob_csrf = users[1][3], users[1][4]
    eve_token = users[2][3]

    # First authenticated read materialises safe social profiles.
    for _, _, _, token, _ in users:
        status, payload = _request(http_server, "/api/community/v2/feed", token=token)
        assert status == 200, payload
        viewer = payload["viewer"]
        assert viewer["profile_id"].startswith("sfp_")
        assert not ({"user_id", "user_uuid", "workspace_id", "email"} & viewer.keys())

    status, listing = _request(
        http_server, "/api/community/v2/profiles?q=bob_http", token=alice_token,
    )
    assert status == 200, listing
    bob_profile = next(row for row in listing["profiles"] if row["username"] == "bob_http")

    status, posted = _request(
        http_server, "/api/community/v2/posts", token=alice_token, csrf=alice_csrf,
        method="POST", body={"text": "HTTP #MNQ community contract", "visibility": "network"},
        extra_headers={"Idempotency-Key": "community-http-post-1"},
    )
    assert status == 200, posted
    post_id = posted["post"]["post_id"]
    assert posted["post"]["hashtags"] == ["mnq"]

    attested_job = {
        "job_id": "job_http_demo_1", "status": "done",
        "class_name": "MNQDemo", "instrument": "MNQ 09-26", "timeframe": "1 Minute",
        "finished_at_utc": "2026-09-01T12:00:00Z",
        "metrics": {"net_profit": 125.5, "profit_factor": 1.5, "trade_count": 8},
        "path": "C:/must-not-leak", "trades": [{"private": True}],
    }
    monkeypatch.setattr(jobqueue, "list_jobs", lambda *args, **kwargs: [dict(attested_job)])
    monkeypatch.setattr(jobqueue, "job_origin", lambda job_id: {
        "type": "demo", "workspace_id": "private", "user_id": "5301",
    })
    monkeypatch.setattr(
        jobqueue, "job_in_scope", lambda job_id, **kwargs: job_id == "job_http_demo_1",
    )
    monkeypatch.setattr(
        jobqueue, "read_job_summary",
        lambda job_id, include_adjusted=True: dict(attested_job) if job_id == "job_http_demo_1" else None,
    )
    status, available = _request(
        http_server, "/api/community/v2/objects?source_type=result", token=alice_token,
    )
    assert status == 200, available
    assert [row["source_id"] for row in available["objects"]] == ["job_http_demo_1"]
    assert available["objects"][0]["metrics"]["Net P&L"] == 125.5
    assert not ({"path", "trades", "origin", "workspace_id", "user_id"}
                & available["objects"][0].keys())

    status, object_post = _request(
        http_server, "/api/community/v2/objects", token=alice_token, csrf=alice_csrf,
        method="POST", body={
            "source_type": "job_result", "source_id": "job_http_demo_1",
            "text": "Server attested", "metrics": {"Net P&L": 999999999},
        }, extra_headers={"Idempotency-Key": "community-http-object-1"},
    )
    assert status == 200, object_post
    assert object_post["post"]["object"]["metrics"]["Net P&L"] == 125.5
    assert len(object_post["post"]["object"]["attestation"]["digest"]) == 64
    status, _ = _request(
        http_server, "/api/community/v2/objects", token=alice_token, csrf=alice_csrf,
        method="POST", body={"source_type": "job_result", "source_id": "job_somebody_else"},
        extra_headers={"Idempotency-Key": "community-http-object-foreign"},
    )
    assert status == 404

    status, started = _request(
        http_server, "/api/sf-chat/conversations/start", token=alice_token,
        csrf=alice_csrf, method="POST", body={"profile_id": bob_profile["profile_id"]},
    )
    assert status == 200, started
    conversation_id = started["conversation"]["conversation_id"]
    assert conversation_id.startswith("sfh_")

    status, sent = _request(
        http_server, "/api/sf-chat/messages", token=alice_token, csrf=alice_csrf,
        method="POST", body={"conversation_id": conversation_id, "text": "Привет через HTTP"},
        extra_headers={"Idempotency-Key": "sf-chat-http-message-1"},
    )
    assert status == 200, sent
    message_id = sent["message"]["message_id"]
    status, duplicate = _request(
        http_server, "/api/sf-chat/messages", token=alice_token, csrf=alice_csrf,
        method="POST", body={"conversation_id": conversation_id, "text": "Привет через HTTP"},
        extra_headers={"Idempotency-Key": "sf-chat-http-message-1"},
    )
    assert status == 200 and duplicate["deduplicated"] is True
    assert duplicate["message"]["message_id"] == message_id

    status, bob_inbox = _request(http_server, "/api/sf-chat/conversations", token=bob_token)
    assert status == 200, bob_inbox
    assert bob_inbox["human_unread_count"] == 1
    assert bob_inbox["ai_available"] is False
    status, detail = _request(
        http_server, f"/api/sf-chat/conversations/{conversation_id}", token=bob_token,
    )
    assert status == 200, detail
    assert detail["messages"][0]["content"] == "Привет через HTTP"
    assert "user_id" not in detail["messages"][0]

    # A valid authenticated member outside the participant set gets the same
    # non-enumerating 404 as a nonexistent dialogue.
    status, _ = _request(
        http_server, f"/api/sf-chat/conversations/{conversation_id}", token=eve_token,
    )
    assert status == 404

    status, read = _request(
        http_server, "/api/sf-chat/read", token=bob_token, csrf=bob_csrf,
        method="POST", body={"conversation_id": conversation_id},
    )
    assert status == 200 and read["advanced"] == 1
    status, bob_inbox = _request(http_server, "/api/sf-chat/conversations", token=bob_token)
    assert status == 200 and bob_inbox["human_unread_count"] == 0

    status, reaction = _request(
        http_server, f"/api/community/v2/posts/{post_id}/reaction", token=bob_token,
        csrf=bob_csrf, method="POST", body={"reaction": "support"},
    )
    assert status == 200 and reaction["post"]["reactions"]["support"] == 1

    status, blocked = _request(
        http_server, "/api/community/v2/blocks", token=bob_token, csrf=bob_csrf,
        method="POST", body={"profile_id": posted["post"]["author"]["profile_id"], "blocked": True},
    )
    assert status == 200 and blocked["blocked"] is True
    status, _ = _request(
        http_server, "/api/sf-chat/messages", token=alice_token, csrf=alice_csrf,
        method="POST", body={"conversation_id": conversation_id, "text": "blocked"},
        extra_headers={"Idempotency-Key": "sf-chat-http-message-2"},
    )
    assert status == 403
    status, _ = _request(http_server, "/api/community/v2/moderation", token=alice_token)
    assert status == 403
    status, deleted = _request(
        http_server, f"/api/community/v2/posts/{post_id}/delete", token=alice_token,
        csrf=alice_csrf, method="POST", body={},
    )
    assert status == 200 and deleted["soft_delete"] is True


def test_owner_legal_configuration_is_unreachable_through_document_api(http_server, ux_store) -> None:
    token, csrf = "o" * 64, "p" * 48
    with account_auth._LOCK:
        doc = account_auth._read_doc()
        doc["sessions"].append(_token_row(999, token, csrf))
        account_auth._write_doc(doc)

    status, listing = _request(http_server, "/api/governance/documents", token=token)
    assert status == 200
    serialized = json.dumps(listing, ensure_ascii=False)
    assert "OWNER_LEGAL_CONFIGURATION" not in serialized

    for candidate in (
        "OWNER_LEGAL_CONFIGURATION",
        "owner-legal-configuration",
        "..%2Flegal%2FOWNER_LEGAL_CONFIGURATION.md",
        "legal%2FOWNER_LEGAL_CONFIGURATION.md",
    ):
        status, _ = _request(
            http_server, f"/api/governance/documents/{candidate}", token=token,
        )
        assert status == 404
        status, _ = _request(http_server, f"/api/documents/{candidate}", token=token)
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
    assert "API.http.runtimeEnv" in script
    assert 'id="mode-entry-release-badge"' in entry
    assert 'id="mode-entry-build-meta"' in entry
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
