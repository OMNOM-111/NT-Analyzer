from __future__ import annotations

import hashlib
import hmac
import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from app import account_auth, invitations, secure_store, server as server_mod, subscriptions, telegram_remote, telegram_service, user_support, workspaces
from app.ai_lab import intent_classifier


FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"stratforge-avatar-bytes" * 4


def _init_data(user_id: int, *, token: str, auth_date: int | None = None) -> str:
    """Build a valid Telegram Mini App initData string for ``user_id``."""
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
def cabinet_store(monkeypatch, tmp_path):
    monkeypatch.setenv("NTA_TELEGRAM_CHAT_ID", "999")
    monkeypatch.setattr(account_auth, "_root", lambda: tmp_path)
    monkeypatch.setattr(subscriptions, "_root", lambda: tmp_path)
    monkeypatch.setattr(workspaces, "_root", lambda: tmp_path)
    monkeypatch.setattr(user_support, "_root", lambda: tmp_path)
    monkeypatch.setattr(secure_store, "available", lambda: True)
    monkeypatch.setattr(secure_store, "backend_name", lambda: "test DPAPI")
    monkeypatch.setattr(secure_store, "_protect", lambda value: value[::-1])
    monkeypatch.setattr(secure_store, "_unprotect", lambda value: value[::-1])
    with account_auth._RATE_LOCK:
        account_auth._LOGIN_RATE.clear()
    return tmp_path


def _request(base: str, path: str, *, method: str = "GET", body: dict | None = None,
             token: str = "", csrf: str = "", raw: bool = False,
             extra_headers: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Cookie": f"{account_auth.SESSION_COOKIE}={token}"} if token else {}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Origin": base})
    if csrf:
        headers["X-CSRF-Token"] = csrf
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        blob = response.read()
    return blob if raw else json.loads(blob.decode("utf-8"))


def _seed_two_accounts(owner_token, owner_csrf, user_token, user_csrf):
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True},
            # These cabinet scenarios exercise the professional contour.  A
            # user without this choice is correctly held on the UX chooser.
            {"user_id": 42, "first_name": "Dev", "last_name": "Two", "email": "dev@example.com", "role": "read_only", "status": "active", "is_owner": False, "ux_mode": "professional"},
        ],
        "challenges": [],
        "sessions": [
            {"user_id": 999, "token_hash": hashlib.sha256(owner_token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(owner_csrf.encode()).hexdigest(), "csrf_token": owner_csrf, "expires_at": time.time() + 3600, "revoked": False},
            {"user_id": 42, "token_hash": hashlib.sha256(user_token.encode()).hexdigest(), "csrf_hash": hashlib.sha256(user_csrf.encode()).hexdigest(), "csrf_token": user_csrf, "expires_at": time.time() + 3600, "revoked": False},
        ],
    })


def test_effective_features_and_owner_toggle(cabinet_store) -> None:
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 42, "first_name": "Dev", "last_name": "Two", "email": "dev@example.com", "role": "read_only", "status": "active", "is_owner": False},
        ],
        "challenges": [],
        "sessions": [],
    })

    owner = account_auth._user(account_auth._read_doc(), 999)
    assert all(account_auth.effective_features(owner).values())

    user = account_auth._user(account_auth._read_doc(), 42)
    defaults = account_auth.effective_features(user)
    assert defaults["backtest"] is True and defaults["agents"] is False

    account_auth.set_user_feature(999, 42, "agents", True)
    account_auth.set_user_feature(999, 42, "trading", False)
    user2 = account_auth._user(account_auth._read_doc(), 42)
    updated = account_auth.effective_features(user2)
    assert updated["agents"] is True and updated["trading"] is False

    with pytest.raises(account_auth.AccountAuthError):
        account_auth.set_user_feature(999, 42, "unknown_feature", True)


def test_refresh_avatar_writes_file_and_is_idempotent(cabinet_store) -> None:
    account_auth.ensure_owner(999)

    fetched = {"bytes": FAKE_PNG, "ext": "png", "file_unique_id": "unique-1"}
    out = account_auth.refresh_avatar(999, fetcher=lambda uid: fetched)
    assert out["ok"] is True
    public = out["user"]
    assert public["has_avatar"] is True
    assert public["avatar_url"].startswith("/api/auth/avatar/999")
    # The avatar travels as a cacheable versioned URL, never inlined: the old
    # base64 copy was ~27KB per user on every payload that named one.
    assert "avatar_data_url" not in public
    assert "?v=" in public["avatar_url"]

    path = account_auth.avatar_file(999)
    assert path is not None and path.read_bytes() == FAKE_PNG

    unchanged = account_auth.refresh_avatar(999, fetcher=lambda uid: fetched)
    assert unchanged["ok"] is True and unchanged.get("unchanged") is True

    missing = account_auth.refresh_avatar(999, fetcher=lambda uid: None)
    assert missing["ok"] is False


def test_cabinet_endpoints_over_http(cabinet_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456:test-bot-token-value")
    monkeypatch.setattr(telegram_service, "fetch_user_avatar",
                        lambda uid, **_kw: {"bytes": FAKE_PNG, "ext": "png", "file_unique_id": f"u{uid}"})
    account_auth.set_auth_required(True)

    owner_token, owner_csrf = "o" * 64, "p" * 48
    user_token, user_csrf = "u" * 64, "v" * 48
    _seed_two_accounts(owner_token, owner_csrf, user_token, user_csrf)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        me = _request(base, "/api/auth/me", token=user_token)
        assert me["role"] == "read_only" and me["is_owner"] is False
        assert me["feature_catalog"] and "features" in me
        assert me["nt_connection"]["uses_owner_runtime"] is True
        assert me["telegram_configured"] is True

        owner_me = _request(base, "/api/auth/me", token=owner_token)
        assert owner_me["is_owner"] is True
        # The owner is always professional; the Student-only virtual terminal
        # must not reappear in a professional rail just because this is the
        # founder account.
        assert owner_me["features"]["practice"] is False
        assert all(value for name, value in owner_me["features"].items() if name != "practice")

        refreshed = _request(base, "/api/auth/avatar/refresh", method="POST", token=user_token, csrf=user_csrf, body={})
        assert refreshed["ok"] is True and refreshed["user"]["has_avatar"] is True

        image = _request(base, "/api/auth/avatar/42", token=user_token, raw=True)
        assert image[:8] == b"\x89PNG\r\n\x1a\n"

        # A user cannot read another user's avatar.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/avatar/999", token=user_token, raw=True)
        assert exc.value.code == 403

        # Owner toggles a per-user feature.
        toggled = _request(base, "/api/auth/users/42/features", method="POST", token=owner_token, csrf=owner_csrf,
                           body={"feature": "agents", "enabled": True})
        target = next(u for u in toggled["users"] if int(u["user_id"]) == 42)
        assert target["features"]["agents"] is True

        # A non-owner cannot toggle features.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/users/42/features", method="POST", token=user_token, csrf=user_csrf,
                     body={"feature": "agents", "enabled": False})
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
def test_owner_billing_and_ninja_endpoints_over_http(cabinet_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456:test-bot-token-value")
    account_auth.set_auth_required(True)

    owner_token, owner_csrf = "o" * 64, "p" * 48
    user_token, user_csrf = "u" * 64, "v" * 48
    _seed_two_accounts(owner_token, owner_csrf, user_token, user_csrf)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        # Owner subscription is the founder tier.
        owner_me = _request(base, "/api/auth/me", token=owner_token)
        assert owner_me["subscription"]["plan_id"] == "founder"
        assert owner_me["nt_connection"]["owner_full_access"] is True

        # Plan matrix is readable and editable by the owner.
        plans = _request(base, "/api/owner/plans", token=owner_token)
        assert {p["plan_id"] for p in plans["public_plans"]} >= {"basic", "standard", "pro"}
        _request(base, "/api/owner/plans/feature", method="POST", token=owner_token, csrf=owner_csrf,
                 body={"plan_id": "basic", "feature": "ai_lab", "enabled": True})
        plans2 = _request(base, "/api/owner/plans", token=owner_token)
        basic = next(p for p in plans2["plans"] if p["plan_id"] == "basic")
        assert basic["features"]["ai_lab"] is True

        # Payment config drives donation options with a PayPal link.
        _request(base, "/api/owner/payment", method="POST", token=owner_token, csrf=owner_csrf,
                 body={"paypal_me": "myhandle", "enabled": True})
        donate = _request(base, "/api/billing/donate", token=user_token)
        assert donate["tiers"] and any(t["paypal_url"] for t in donate["tiers"])

        # Owner creates an invite with links.
        invite = _request(base, "/api/owner/invites", method="POST", token=owner_token, csrf=owner_csrf,
                          body={"label": "Ref", "grant_plan_id": "standard", "usage_limit": 3, "code_prefix": "REF"})
        assert invite["voucher"]["code"] and "code" in invite["invite"]

        # NinjaTrader setup for a viewer reports the owner runtime.
        setup = _request(base, "/api/bridge/setup", token=user_token)
        assert setup["owner_runtime"] is True

        # A non-owner cannot edit the plan matrix.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/owner/plans/feature", method="POST", token=user_token, csrf=user_csrf,
                     body={"plan_id": "basic", "feature": "ai_lab", "enabled": False})
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_admin_user_panel_endpoints(cabinet_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456:test-bot-token-value")
    account_auth.set_auth_required(True)

    owner_token, owner_csrf = "o" * 64, "p" * 48
    user_token, user_csrf = "u" * 64, "v" * 48
    _seed_two_accounts(owner_token, owner_csrf, user_token, user_csrf)
    initial_trial = subscriptions.ensure_initial_trial(42, source="test_registration")

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        detail = _request(base, "/api/auth/users/42", token=owner_token)
        assert detail["user"]["user_id"] == 42
        assert "capabilities" in detail and "capability_catalog" in detail
        assert "nt_connection" in detail and "login_history" in detail["user"]
        assert detail["access"]["state"] == "active"

        extended = _request(
            base, "/api/owner/trial/extend", method="POST",
            token=owner_token, csrf=owner_csrf,
            body={
                "user_id": 42, "days": 3,
                "reason": "Owner QA extension",
                "idempotency_key": "cabinet-trial-extension-1",
            },
        )
        assert extended["access"]["expires_at_utc"] > initial_trial["access"]["expires_at_utc"]
        assert extended["access"]["history"][0]["reason"] == "Owner QA extension"

        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(
                base, "/api/owner/trial/extend", method="POST",
                token=user_token, csrf=user_csrf,
                body={"user_id": 42, "days": 1, "reason": "self-extension"},
            )
        assert exc.value.code == 403

        _request(base, "/api/auth/users/42/permission", method="POST", token=owner_token, csrf=owner_csrf,
                 body={"capability": "ai_lab", "enabled": True})
        detail2 = _request(base, "/api/auth/users/42", token=owner_token)
        assert detail2["capabilities"]["ai_lab"] is True

        # A non-owner cannot read admin detail or delete users (check while the
        # user session is still valid — blocking below would revoke it).
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/users/42", token=user_token)
        assert exc.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/users/42/delete", method="POST", token=user_token, csrf=user_csrf, body={})
        assert exc.value.code == 403

        _request(base, "/api/auth/users/42/status", method="POST", token=owner_token, csrf=owner_csrf,
                 body={"status": "blocked"})
        blocked = next(u for u in _request(base, "/api/auth/users", token=owner_token)["users"] if u["user_id"] == 42)
        assert blocked["status"] == "blocked"
        _request(base, "/api/auth/users/42/status", method="POST", token=owner_token, csrf=owner_csrf,
                 body={"status": "active"})

        _request(base, "/api/auth/users/42/delete", method="POST", token=owner_token, csrf=owner_csrf, body={})
        ids = [u["user_id"] for u in _request(base, "/api/auth/users", token=owner_token)["users"]]
        assert 42 not in ids
    finally:
        server.shutdown()
        server.server_close()


def test_admin_panel_capabilities_gate_ui_data_and_server_routes(cabinet_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456:test-bot-token-value")
    account_auth.set_auth_required(True)

    owner_token, owner_csrf = "a" * 64, "b" * 48
    user_token, user_csrf = "c" * 64, "d" * 48
    _seed_two_accounts(owner_token, owner_csrf, user_token, user_csrf)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        # An ordinary professional user has no control-plane access even when
        # authenticated and holding product capabilities.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/admin/overview", token=user_token)
        assert exc.value.code == 403

        for capability in ("admin.view", "users.manage", "environment.switch"):
            _request(
                base,
                "/api/auth/users/42/admin-permission",
                method="POST",
                token=owner_token,
                csrf=owner_csrf,
                body={"capability": capability, "enabled": True},
            )

        overview = _request(base, "/api/admin/overview", token=user_token)
        modules = {row["id"] for row in overview["modules"]}
        # environment.switch alone opens the merged environments-and-releases
        # module: reading what each environment runs is the half of it this
        # delegated admin is entitled to, and its actions are gated separately.
        assert {"overview", "users", "pipeline"} <= modules
        assert "operations" not in modules
        assert overview["security_contract"]["secrets_exposed"] is False

        targets = _request(base, "/api/admin/environment-targets", token=user_token)
        assert {row["environment"] for row in targets["targets"]} == {
            "development", "canary", "production",
        }
        assert targets["transition_contract"] == {
            "new_tab": True,
            "credentials_transfer": False,
            "tokens_in_url": False,
            "local_storage_transfer": False,
        }
        assert len(_request(base, "/api/auth/users", token=user_token)["users"]) == 2

        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/admin/operations", token=user_token)
        assert exc.value.code == 403
        # users.manage does not allow staff to grant itself stronger rights.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(
                base,
                "/api/auth/users/42/admin-permission",
                method="POST",
                token=user_token,
                csrf=user_csrf,
                body={"capability": "operations.execute", "enabled": True},
            )
        assert exc.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_environment_switch_origins_fail_closed() -> None:
    assert server_mod._validated_environment_origin(
        "development", "http://127.0.0.1:8765",
    ) == "http://127.0.0.1:8765"
    assert server_mod._validated_environment_origin(
        "development", "http://localhost:443",
    ) == "http://localhost:443"
    assert server_mod._validated_environment_origin(
        "development", "https://localhost:80",
    ) == "https://localhost:80"
    assert server_mod._validated_environment_origin(
        "development", "https://dev.example.com",
    ) == ""
    assert server_mod._validated_environment_origin(
        "canary", "http://canary.example.com",
    ) == ""
    assert server_mod._validated_environment_origin(
        "canary", "https://canary.example.com",
    ) == "https://canary.example.com"
    assert server_mod._validated_environment_origin(
        "production", "https://user:password@prod.example.com",
    ) == ""


def test_environment_switcher_defaults_canonical_origins(monkeypatch, tmp_path) -> None:
    development = tmp_path / "development"
    development.mkdir()
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(development))
    monkeypatch.delenv("STRATFORGE_DEVELOPMENT_ORIGIN", raising=False)
    monkeypatch.delenv("STRATFORGE_CANARY_ORIGIN", raising=False)
    monkeypatch.delenv("STRATFORGE_PRODUCTION_ORIGIN", raising=False)

    payload = server_mod._admin_environment_targets()
    by_env = {row["environment"]: row for row in payload["targets"]}

    assert by_env["development"]["current"] is True
    assert by_env["canary"]["origin"] == "https://canary.stratforges.com"
    assert by_env["production"]["origin"] == "https://app.stratforges.com"
    assert by_env["canary"]["open_allowed"] is True
    assert by_env["production"]["open_allowed"] is True
    assert by_env["development"]["requires_reachability_probe"] is False
    assert by_env["canary"]["configured"] is True
    assert payload["transition_contract"]["credentials_transfer"] is False


def test_environment_switcher_server_probe_reads_public_identity_without_credentials(
    monkeypatch, tmp_path,
) -> None:
    development = tmp_path / "development"
    development.mkdir()
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(development))
    monkeypatch.delenv("STRATFORGE_CANARY_ORIGIN", raising=False)

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "deployment": {
                    "deployment_environment": "canary",
                    "app_version": "0.10.0-beta.2",
                    "git_commit_sha": "a" * 40,
                    "build_id": "sf-canary-build",
                    "release_channel": "beta",
                },
            }).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(server_mod.urllib.request, "urlopen", fake_urlopen)
    target = server_mod._admin_environment_probe("canary")

    assert captured["url"] == "https://canary.stratforges.com/api/runtime/env"
    assert captured["timeout"] == 4.5
    assert "Cookie" not in captured["headers"]
    assert "Authorization" not in captured["headers"]
    assert target["version"] == "0.10.0-beta.2"
    assert target["commit"] == "a" * 40
    assert target["build_id"] == "sf-canary-build"
    assert target["health"] == "reachable"
    assert target["probe_ok"] is True
    assert not any("Метаданные среды" in row for row in target["warnings"])


def test_environment_switcher_server_probe_rejects_identity_mismatch(
    monkeypatch, tmp_path,
) -> None:
    development = tmp_path / "development"
    development.mkdir()
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production"))
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(development))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "deployment": {"deployment_environment": "production"},
            }).encode("utf-8")

    monkeypatch.setattr(
        server_mod.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(),
    )
    with pytest.raises(ValueError, match="не соответствует"):
        server_mod._admin_environment_probe("canary")


def test_consent_support_session_commands_and_monitoring(cabinet_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456:test-bot-token-value")
    account_auth.set_auth_required(True)

    owner_token, owner_csrf = "o" * 64, "p" * 48
    user_token, user_csrf = "u" * 64, "v" * 48
    _seed_two_accounts(owner_token, owner_csrf, user_token, user_csrf)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    client_id = "client-test-0001"
    delivered: dict = {}
    monkeypatch.setattr(server_mod.ai_chief_agent, "report_user_screenshot", lambda **kwargs: delivered.update(kwargs) or {"ok": True})
    try:
        # A read-only user can report only their own browser-tab telemetry.
        _request(base, "/api/support/telemetry", method="POST", token=user_token, csrf=user_csrf, body={
            "client_id": client_id, "page": "/ui/index.html", "visible": True,
            "logical_cores": 8, "cpu_available": True, "cpu_main_thread_percent": 88,
            "cpu_core_equivalent": .88, "memory_available": True,
            "js_heap_used_mb": 1300, "js_heap_limit_mb": 1400,
            "network_mb_per_min": 55, "network_total_mb": 12,
        })
        overview = _request(base, "/api/owner/support/monitoring", token=owner_token)
        monitored = next(row for row in overview["users"] if row["user_id"] == 42)
        assert monitored["online"] is True and monitored["alert_count"] == 3

        detail = _request(base, "/api/auth/users/42", token=owner_token)
        session_id = detail["user"]["active_sessions"][0]["session_id"]
        queued = _request(base, "/api/owner/support/users/42/reload", method="POST",
                          token=owner_token, csrf=owner_csrf, body={"session_id": session_id})
        assert queued["queued"] == 1
        polled = _request(base, "/api/support/poll", method="POST", token=user_token,
                          csrf=user_csrf, body={"client_id": client_id})
        command = polled["commands"][0]
        assert command["type"] == "reload" and command["target_session_id"] == session_id
        _request(base, "/api/support/commands/ack", method="POST", token=user_token,
                 csrf=user_csrf, body={"client_id": client_id, "command_id": command["command_id"], "status": "done"})

        # The first consent request is explicitly denied; no image is created.
        requested = _request(base, "/api/owner/support/users/42/screenshot", method="POST",
                             token=owner_token, csrf=owner_csrf, body={"note": "Диагностика"})
        request_id = requested["request"]["request_id"]
        consent = _request(base, "/api/support/poll", method="POST", token=user_token,
                           csrf=user_csrf, body={"client_id": client_id})["screenshot_request"]
        assert consent["request_id"] == request_id and consent["status"] == "claimed"
        denied = _request(base, "/api/support/screenshots/respond", method="POST",
                          token=user_token, csrf=user_csrf, body={
                              "client_id": client_id, "request_id": request_id, "decision": "denied",
                          })
        assert denied["request"]["status"] == "denied"

        # A later, separately approved request stores an encrypted image that is
        # readable by the owner only.
        approved_req = user_support.request_screenshot(
            999, 42, conversation_id="support-chat",
            owner_scope={"user_id": 999, "workspace_id": "owner_training", "is_owner": True, "uses_owner_runtime": True},
        )["request"]
        _request(base, "/api/support/poll", method="POST", token=user_token,
                 csrf=user_csrf, body={"client_id": client_id})
        completed = _request(base, "/api/support/screenshots/respond", method="POST",
                             token=user_token, csrf=user_csrf, body={
                                 "client_id": client_id, "request_id": approved_req["request_id"],
                                 "decision": "approved",
                                 "data_url": "data:image/png;base64," + base64.b64encode(FAKE_PNG).decode(),
                                 "width": 1200, "height": 700,
                             })
        assert completed["request"]["status"] == "completed"
        assert delivered["conversation_id"] == "support-chat"
        assert delivered["image_url"] == completed["request"]["image_url"]
        encrypted_file = cabinet_store / "data" / "runtime" / "support-screenshots" / f"{approved_req['request_id']}.dpapi"
        assert encrypted_file.is_file() and FAKE_PNG not in encrypted_file.read_bytes()
        image = _request(base, completed["request"]["image_url"], token=owner_token, raw=True)
        assert image == FAKE_PNG
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, completed["request"]["image_url"], token=user_token, raw=True)
        assert exc.value.code == 403

        support = _request(base, "/api/owner/support/users/42", token=owner_token)
        assert support["alerts"] and support["auth_sessions"]
        _request(base, f"/api/owner/support/screenshots/{approved_req['request_id']}/delete",
                 method="POST", token=owner_token, csrf=owner_csrf, body={})

        # Ending the selected session invalidates it without deleting the user.
        ended = _request(base, "/api/auth/users/42/sessions", method="POST",
                         token=owner_token, csrf=owner_csrf, body={"session_id": session_id})
        assert ended["revoked"] == 1
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/me", token=user_token)
        assert exc.value.code == 401
    finally:
        server.shutdown()
        server.server_close()


def test_chat_intent_distinguishes_user_screen_from_chart_snapshot(cabinet_store) -> None:
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "role": "owner", "status": "active", "is_owner": True},
            {"user_id": 42, "first_name": "Dev", "role": "read_only", "status": "active", "is_owner": False},
        ],
        "challenges": [], "sessions": [],
    })
    intent = intent_classifier.classify("Сделай скрин экрана пользователю Dev")
    assert intent["capability"] == "user_screenshot_request"
    out = user_support.chat_command("user_screenshot_request", 999, "Сделай скрин экрана пользователю Dev")
    assert out["actions"][0]["status"] == "waiting_for_user_consent"
    assert user_support.owner_status(999, 42)["screenshot_requests"][0]["status"] == "pending"


def test_owner_account_has_monitoring_controls_and_renameable_device(cabinet_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456:test-bot-token-value")
    account_auth.set_auth_required(True)

    owner_token, owner_csrf = "o" * 64, "p" * 48
    user_token, user_csrf = "u" * 64, "v" * 48
    _seed_two_accounts(owner_token, owner_csrf, user_token, user_csrf)

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    client_id = "owner-client-0001"
    device_id = "owner-device-0001"
    try:
        _request(base, "/api/support/telemetry", method="POST", token=owner_token, csrf=owner_csrf, body={
            "client_id": client_id, "device_id": device_id,
            "device_name": "Chrome · Windows", "client": "Chrome", "platform": "Windows",
            "page": "/ui/index.html", "visible": True, "logical_cores": 16,
            "cpu_available": True, "cpu_main_thread_percent": 12,
            "memory_available": True, "js_heap_used_mb": 220, "js_heap_limit_mb": 4096,
            "network_mb_per_min": 1.5,
        })
        overview = _request(base, "/api/owner/support/monitoring", token=owner_token)
        owner_monitor = next(row for row in overview["users"] if row["user_id"] == 999)
        assert owner_monitor["online"] is True

        status = _request(base, "/api/owner/support/users/999", token=owner_token)
        assert status["is_self"] is True and status["current_session_id"]
        assert status["sessions"][0]["device_name"] == "Chrome · Windows"

        renamed = _request(base, "/api/owner/support/users/999/device-name", method="POST",
                           token=owner_token, csrf=owner_csrf,
                           body={"device_id": device_id, "name": "Основной компьютер"})
        assert renamed["device_name"] == "Основной компьютер"
        status2 = _request(base, "/api/owner/support/users/999", token=owner_token)
        assert status2["sessions"][0]["device_name"] == "Основной компьютер"
        assert status2["auth_sessions"][0]["device_name"] == "Основной компьютер"

        # A screenshot request can be targeted to the owner's selected device;
        # another client cannot claim it.
        shot = _request(base, "/api/owner/support/users/999/screenshot", method="POST",
                        token=owner_token, csrf=owner_csrf,
                        body={"target_client_id": client_id})["request"]
        wrong = user_support.poll(999, status["current_session_id"], "other-client-0002")
        assert wrong["screenshot_request"] is None
        consent = _request(base, "/api/support/poll", method="POST", token=owner_token,
                           csrf=owner_csrf, body={"client_id": client_id})["screenshot_request"]
        assert consent["request_id"] == shot["request_id"]
        _request(base, "/api/support/screenshots/respond", method="POST", token=owner_token,
                 csrf=owner_csrf, body={
                     "client_id": client_id, "request_id": shot["request_id"], "decision": "denied",
                 })
    finally:
        server.shutdown()
        server.server_close()


def test_owner_row_exposes_details_and_support_bridge() -> None:
    ui = (server_mod.STATIC_DIR / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    assert "const detailBtn = `<button" in ui
    assert "CURRENT_AUTH.is_owner) return" not in ui
    assert "Это ваш один аккаунт владельца" in ui
    assert "ownerSupportDeviceName" in ui


def test_miniapp_registration_is_isolated_from_current_runtime(cabinet_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
    monkeypatch.setenv(telegram_service.TOKEN_ENV, token)
    monkeypatch.setattr(telegram_remote, "_root", lambda: cabinet_store)
    monkeypatch.setattr(telegram_service, "_api_call", lambda *a, **k: {})
    telegram_remote._write({
        "remote_enabled": True, "desktop_auth_required": True,
        "public_url": "https://app.stratforges.com", "users": [], "pairings": [],
    })
    assert account_auth.auth_required() is True  # no bypass -> mandatory
    account_auth._write_doc({
        "version": 1,
        "users": [{"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "o@e.com",
                   "role": "owner", "status": "active", "is_owner": True}],
        "challenges": [], "sessions": [],
    })

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    tunnel = {"Host": "app.stratforges.com", "X-Forwarded-Host": "app.stratforges.com",
              "Origin": "https://app.stratforges.com"}
    try:
        stranger = _init_data(777, token=token)
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/me", extra_headers={**tunnel, telegram_remote.INIT_DATA_HEADER: stranger})
        assert exc.value.code == 410
        assert json.loads(exc.value.read().decode("utf-8"))["code"] == "telegram_mini_app_isolated"

        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/miniapp/register", method="POST",
                     body={"email": "s@e.com", "first_name": "Sam", "last_name": "Lee", "accept_terms": True},
                     extra_headers={**tunnel, telegram_remote.INIT_DATA_HEADER: stranger})
        assert exc.value.code == 410
        assert len(account_auth._read_doc()["users"]) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_invite_lifecycle_and_send_endpoints(cabinet_store, monkeypatch) -> None:
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    monkeypatch.setenv(telegram_service.TOKEN_ENV, "123456:test-bot-token-value")
    monkeypatch.setattr(telegram_remote, "_root", lambda: cabinet_store)
    monkeypatch.setattr(invitations, "_pillow_provider", lambda context: None)
    account_auth.set_auth_required(True)

    owner_token, owner_csrf = "o" * 64, "p" * 48
    user_token, user_csrf = "u" * 64, "v" * 48
    _seed_two_accounts(owner_token, owner_csrf, user_token, user_csrf)

    sent: dict = {}
    monkeypatch.setattr(telegram_service, "send_photo_bytes",
                        lambda chat, blob, **kw: sent.update({"chat": chat, "len": len(blob)}) or True)
    # Pillow is optional. A clean CI runner can render the dependency-free SVG
    # fallback, in which case the endpoint intentionally sends the invitation
    # text instead of a Telegram photo. Keep both delivery branches isolated
    # from the real Bot API and assert the same owner destination.
    monkeypatch.setattr(
        telegram_service, "_send_raw",
        lambda text, **kw: sent.update({"chat": str(kw.get("chat_id") or ""), "text": text}) or {},
    )

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        inv = _request(base, "/api/owner/invites", method="POST", token=owner_token, csrf=owner_csrf,
                       body={"label": "Ref", "grant_plan_id": "standard", "usage_limit": 2, "code_prefix": "REF"})
        vid = inv["voucher"]["voucher_id"]
        assert inv["render"]["image_data_url"].startswith("data:image/")

        # Cancel (pause) then delete — the routes that previously 404'd.
        out = _request(base, f"/api/owner/invites/{vid}/status", method="POST", token=owner_token, csrf=owner_csrf,
                       body={"status": "paused"})
        assert next(v for v in out["vouchers"] if v["voucher_id"] == vid)["status"] == "paused"

        # Send to owner's Telegram.
        send = _request(base, "/api/owner/invites/send", method="POST", token=owner_token, csrf=owner_csrf,
                        body={"text": "hi", "image_data_url": inv["render"]["image_data_url"]})
        assert send["ok"] is True and sent.get("chat") == "999"

        out2 = _request(base, f"/api/owner/invites/{vid}/delete", method="POST", token=owner_token, csrf=owner_csrf, body={})
        assert all(v["voucher_id"] != vid for v in out2["vouchers"])
    finally:
        server.shutdown()
        server.server_close()


def test_retired_remote_state_never_reenables_miniapp_access(cabinet_store, monkeypatch) -> None:
    """Stale remote-access state cannot reopen the isolated Mini App surface."""
    monkeypatch.delenv("NTA_TEST_BYPASS_AUTH", raising=False)
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
    monkeypatch.setenv(telegram_service.TOKEN_ENV, token)

    # Retired remote state no longer changes the explicit localhost auth setting.
    telegram_remote._write({
        "remote_enabled": True,
        "desktop_auth_required": False,
        "public_url": "https://app.stratforges.com",
        "users": [],
        "pairings": [],
    })
    assert account_auth.auth_required() is False

    # Only the owner is a registered active account.
    account_auth._write_doc({
        "version": 1,
        "users": [
            {"user_id": 999, "first_name": "Owner", "last_name": "One", "email": "owner@example.com",
             "role": "owner", "status": "active", "is_owner": True},
        ],
        "challenges": [],
        "sessions": [],
    })

    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{server.server_address[0]}:{server.server_address[1]}"
    try:
        tunnel = {"Host": "app.stratforges.com", "X-Forwarded-Host": "app.stratforges.com"}

        # Signed initData is retired before allowlist or owner resolution.
        stranger = _init_data(777, token=token)
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/me", extra_headers={**tunnel, telegram_remote.INIT_DATA_HEADER: stranger})
        assert exc.value.code == 410

        # A remote request over the tunnel with no credentials is unauthorized —
        # NOT silently promoted to owner.
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/me", extra_headers=tunnel)
        assert exc.value.code in (401, 403)

        # Owner initData is isolated too; there is no privileged compatibility path.
        owner_init = _init_data(999, token=token)
        with pytest.raises(urllib.error.HTTPError) as exc:
            _request(base, "/api/auth/me", extra_headers={**tunnel, telegram_remote.INIT_DATA_HEADER: owner_init})
        assert exc.value.code == 410

        # The explicit localhost setting remains independent of retired state.
        local = _request(base, "/api/auth/me")
        assert local["is_owner"] is True
    finally:
        server.shutdown()
        server.server_close()
