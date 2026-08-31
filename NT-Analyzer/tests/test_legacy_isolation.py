from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app import legacy_boundary, legacy_viewer, observability, runtime_env
from app import server as server_mod


ROOT = Path(__file__).resolve().parents[1]
AURORA = ROOT / "app" / "static" / "aurora"
LEGACY_STATIC = ROOT / "legacy_viewer" / "static"


@pytest.fixture
def quiet_http(monkeypatch):
    monkeypatch.setattr(observability, "record_http", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def isolated_data_root(monkeypatch, tmp_path):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "data"))


def _serve(handler):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, f"http://127.0.0.1:{httpd.server_address[1]}"


def _request(base: str, path: str, *, method: str = "GET", headers=None):
    data = b"{}" if method == "POST" else None
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def test_retired_surface_classifier_is_narrow_and_fail_closed():
    assert legacy_boundary.retired_surface("/ui/legacy/", {}) == "legacy_ui"
    assert legacy_boundary.retired_surface("/api/auth/miniapp/register", {}) == "telegram_mini_app"
    assert legacy_boundary.retired_surface("/api/telegram/remote/access", {}) == "telegram_mini_app"
    assert legacy_boundary.retired_surface("/api/telegram/tunnel/status", {}) == "telegram_mini_app"
    assert legacy_boundary.retired_surface("/ui/?tgWebAppData=signed", {}) == "telegram_mini_app"
    assert legacy_boundary.retired_surface(
        "/api/health", {legacy_boundary.MINI_APP_HEADER: "signed"}
    ) == "telegram_mini_app"
    assert legacy_boundary.retired_surface("/api/telegram/status", {}) == ""
    assert legacy_boundary.retired_surface("/api/auth/login/start", {}) == ""


def test_current_http_runtime_rejects_legacy_ui_and_mini_app(quiet_http):
    httpd, thread, base = _serve(server_mod.Handler)
    try:
        live = _request(base, "/live")
        api_live = _request(base, "/api/live")
        assert live[0] == api_live[0] == 200
        assert json.loads(live[1])["status"] == json.loads(api_live[1])["status"]
        ready = _request(base, "/ready")
        api_ready = _request(base, "/api/ready")
        assert ready[0] == api_ready[0]
        assert json.loads(ready[1])["status"] == json.loads(api_ready[1])["status"]
        for method, path, headers, expected_code in (
            ("GET", "/ui/legacy/", {}, "legacy_ui_isolated"),
            ("POST", "/api/auth/miniapp/register", {}, "telegram_mini_app_isolated"),
            ("GET", "/api/telegram/remote/access", {}, "telegram_mini_app_isolated"),
            ("GET", "/api/telegram/tunnel/status", {}, "telegram_mini_app_isolated"),
            ("GET", "/ui/?tgWebAppData=signed", {}, "telegram_mini_app_isolated"),
            ("GET", "/api/health", {legacy_boundary.MINI_APP_HEADER: "signed"}, "telegram_mini_app_isolated"),
        ):
            status, body, _ = _request(base, path, method=method, headers=headers)
            assert status == 410, (method, path, body)
            assert json.loads(body)["code"] == expected_code
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_current_bundle_contains_only_aurora_and_preserves_current_telegram():
    static_root = ROOT / "app" / "static"
    assert {path.name for path in static_root.iterdir()} == {"aurora"}
    ui = (AURORA / "assets" / "ui.js").read_text(encoding="utf-8")
    api = (AURORA / "assets" / "api.js").read_text(encoding="utf-8")
    combined = ui + "\n" + api
    for marker in (
        "/ui/legacy/",
        "legacyUrl",
        "miniappRegister",
        "telegramRemote",
        "telegramTunnel",
        "X-Telegram-Init-Data",
        "tgWebAppData",
    ):
        assert marker not in combined
    assert "authLoginStart" in api
    assert "telegramStatus" in api
    assert "telegramPairStart" in api
    assert "telegramSettings" in api


def test_legacy_viewer_static_and_mutation_boundary(monkeypatch, tmp_path, quiet_http):
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_LEGACY_VIEWER", "1")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "snapshot"))
    httpd, thread, base = _serve(legacy_viewer.LegacyViewerHandler)
    httpd.deployment_config = runtime_env.deployment_config(strict=False)
    try:
        status, body, _ = _request(base, "/ui/")
        assert status == 200
        assert b"NT Analyzer" in body or b"StratForge" in body
        status, body, _ = _request(base, "/ui/legacy/performance.html")
        assert status == 200
        assert b"performance.js" in body
        status, body, _ = _request(base, "/api/legacy-viewer/status")
        payload = json.loads(body)
        assert status == 200
        assert payload["mode"] == "legacy_viewer"
        assert payload["read_only"] is True
        assert payload["background_services"] is False
        assert payload["telegram"] is False
        assert payload["trading"] is False
        status, body, _ = _request(base, "/api/jobs", method="POST")
        assert status == 405
        assert json.loads(body)["code"] == "legacy_viewer_read_only"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_legacy_viewer_uses_isolated_cookie_storage_and_launcher_contract(monkeypatch):
    monkeypatch.setenv("STRATFORGE_LEGACY_VIEWER", "1")
    assert runtime_env.session_cookie_name() == "sf_legacy_viewer_session"
    assert runtime_env.local_storage_namespace() == "legacy-viewer"
    assert (LEGACY_STATIC / "index.html").is_file()
    assert (LEGACY_STATIC / "performance.html").is_file()
    launcher = (ROOT / "start-legacy-viewer.ps1").read_text(encoding="utf-8")
    assert "127.0.0.1" in launcher
    assert "STRATFORGE_LEGACY_VIEWER" in launcher
    assert "STRATFORGE_LIVE_TRADING_ALLOWED = '0'" in launcher
    assert "STRATFORGE_REAL_PAYMENTS_ALLOWED = '0'" in launcher
    assert "robocopy.exe" in launcher
