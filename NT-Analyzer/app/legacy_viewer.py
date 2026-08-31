"""Local-only, mutation-free runtime for the frozen classic StratForge UI."""

from __future__ import annotations

import os
import signal
import sys
import threading
from http import HTTPStatus
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from . import api_admission, runtime_env
from . import server as current_server


DEFAULT_PORT = 8876
STATIC_DIR = Path(__file__).resolve().parent.parent / "legacy_viewer" / "static"
BLOCKED_GET_PREFIXES = (
    "/api/admin",
    "/api/auth/login",
    "/api/auth/miniapp",
    "/api/connector",
    "/api/ninjatrader",
    "/api/owner",
    "/api/release",
    "/api/telegram",
    "/api/worker",
    "/ws/",
)
SENSITIVE_ENV_NAMES = (
    "NTA_GOOGLE_CLIENT_ID",
    "NTA_GOOGLE_CLIENT_SECRET",
    "NTA_RESEND_API_KEY",
    "NTA_TELEGRAM_BOT_TOKEN",
    "NTA_TELEGRAM_CHAT_ID",
    "NTA_TELEGRAM_WEBHOOK_SECRET",
    "STRATFORGE_CANARY_TELEGRAM_WEBHOOK_SECRET",
    "STRATFORGE_OWNER_MARKET_GATEWAY_TOKEN",
    "STRATFORGE_CONNECTOR_RELEASE_SIGNING_KEY",
)


def _disable_external_integrations() -> None:
    for name in SENSITIVE_ENV_NAMES:
        os.environ.pop(name, None)
    os.environ["STRATFORGE_LIVE_TRADING_ALLOWED"] = "0"
    os.environ["STRATFORGE_REAL_PAYMENTS_ALLOWED"] = "0"
    os.environ["NTA_NT_TELEGRAM_CONFIRM_REQUIRED"] = "0"


class LegacyViewerHandler(current_server.Handler):
    static_dir = STATIC_DIR

    def _reject_isolated_legacy_surface(self) -> bool:
        # This handler is the isolated destination itself.
        return False

    def _route_get(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/legacy-viewer/status":
            self._json(HTTPStatus.OK, legacy_status(self.server))
            return
        if path in {"", "/"}:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/ui/")
            self.end_headers()
            return
        if path == "/ui/legacy" or path.startswith("/ui/legacy/"):
            rel = path[len("/ui/legacy"):]
            self._serve_static(rel or "/")
            return
        if path == "/ui" or path.startswith("/ui/"):
            rel = path[len("/ui"):]
            self._serve_static(rel or "/")
            return
        if any(path == prefix or path.startswith(prefix + "/") for prefix in BLOCKED_GET_PREFIXES):
            self._err(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "Legacy Viewer exposes historical reads only.",
                code="legacy_viewer_read_only",
            )
            return
        super()._route_get()

    def _read_only_error(self) -> None:
        self._err(
            HTTPStatus.METHOD_NOT_ALLOWED,
            "Legacy Viewer is read-only; mutations are disabled.",
            code="legacy_viewer_read_only",
        )

    def do_POST(self) -> None:  # noqa: N802
        self._begin_request_observation()
        self._response_started = False
        try:
            self._read_only_error()
        finally:
            self._finish_request_observation("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._begin_request_observation()
        self._response_started = False
        try:
            self._read_only_error()
        finally:
            self._finish_request_observation("DELETE")


def legacy_status(http_server: Any) -> Dict[str, Any]:
    deployment = getattr(http_server, "deployment_config", None)
    return {
        "ok": True,
        "mode": "legacy_viewer",
        "read_only": True,
        "localhost_only": True,
        "background_services": False,
        "telegram": False,
        "trading": False,
        "data_root": str(runtime_env.data_root()),
        "cookie_name": runtime_env.session_cookie_name(),
        "bind_host": str(getattr(deployment, "bind_host", "127.0.0.1")),
        "port": int(http_server.server_address[1]),
    }


def create_server(port: int) -> api_admission.BoundedThreadingHTTPServer:
    _disable_external_integrations()
    deployment = runtime_env.assert_startup_safe()
    if deployment.environment != runtime_env.DEVELOPMENT:
        raise runtime_env.RuntimeEnvError("Legacy Viewer is Development-only.", 503)
    if deployment.bind_host not in {"127.0.0.1", "localhost", "::1"}:
        raise runtime_env.RuntimeEnvError("Legacy Viewer requires a loopback bind host.", 503)
    http_server = api_admission.BoundedThreadingHTTPServer(
        ("127.0.0.1", int(port)),
        LegacyViewerHandler,
        max_inflight=min(16, deployment.api_max_inflight),
        max_websockets=1,
        backlog=min(32, deployment.api_backlog),
        max_body_bytes=min(65536, deployment.api_max_body_bytes),
    )
    http_server.deployment_config = deployment  # type: ignore[attr-defined]
    http_server.readiness_probes = {}  # type: ignore[attr-defined]
    http_server.readiness_optional_components = {}  # type: ignore[attr-defined]
    return http_server


def run(port: Optional[int] = None) -> None:
    bind_port = int(port or DEFAULT_PORT)
    http_server = create_server(bind_port)
    print(f"[legacy-viewer] listening on http://127.0.0.1:{bind_port}/ui/")
    print(f"[legacy-viewer] snapshot={runtime_env.data_root()}")
    print("[legacy-viewer] read_only=true background_services=false telegram=false trading=false")
    sys.stdout.flush()

    def _stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=http_server.shutdown, daemon=True).start()

    if threading.current_thread() is threading.main_thread():
        for stop_signal in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(stop_signal, _stop)
            except (AttributeError, OSError, ValueError):
                pass
    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http_server.server_close()


if __name__ == "__main__":
    selected_port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    run(selected_port)
