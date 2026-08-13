from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

import pytest

from app.api_admission import BoundedThreadingHTTPServer


class _BlockingHandler(BaseHTTPRequestHandler):
    entered = threading.Event()
    release = threading.Event()

    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        type(self).entered.set()
        type(self).release.wait(timeout=5)
        body = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _PromotingHandler(BaseHTTPRequestHandler):
    websocket_entered = threading.Event()
    websocket_release = threading.Event()

    def log_message(self, _format, *_args):
        return

    def _reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/websocket-hold":
            if not self.server.promote_websocket_request():
                self._reply(503, b'{"code":"websocket_admission_saturated"}')
                return
            type(self).websocket_entered.set()
            type(self).websocket_release.wait(timeout=5)
        self._reply(200, b'{"ok":true}')


def test_bounded_server_rejects_saturation_without_spawning_another_handler() -> None:
    _BlockingHandler.entered.clear()
    _BlockingHandler.release.clear()
    server = BoundedThreadingHTTPServer(
        ("127.0.0.1", 0), _BlockingHandler,
        max_inflight=1, backlog=2, max_body_bytes=4096,
    )
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    first_result = {}

    def first_request() -> None:
        with urllib.request.urlopen(url, timeout=5) as response:
            first_result.update(json.loads(response.read().decode("utf-8")))

    first = threading.Thread(target=first_request)
    first.start()
    assert _BlockingHandler.entered.wait(timeout=3)
    try:
        with urllib.request.urlopen(url, timeout=3):
            raise AssertionError("saturated request unexpectedly succeeded")
    except urllib.error.HTTPError as exc:
        assert exc.code == 503
        assert json.loads(exc.read().decode("utf-8"))["code"] == "api_admission_saturated"
        assert exc.headers["Retry-After"] == "1"
    finally:
        _BlockingHandler.release.set()
        first.join(timeout=5)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)

    assert first_result == {"ok": True}
    metrics = server.admission_metrics()
    assert metrics["peak_active"] == 1
    assert metrics["rejected"] == 1
    assert metrics["accepted"] == 1
    assert metrics["completed"] == 1


def test_admission_metrics_bound_payload_samples() -> None:
    server = BoundedThreadingHTTPServer(
        ("127.0.0.1", 0), _BlockingHandler,
        max_inflight=3, backlog=4, max_body_bytes=8192,
    )
    try:
        server.record_payload(10)
        server.record_payload(100)
        server.record_payload(1000)
        metrics = server.admission_metrics()
    finally:
        server.server_close()
    assert metrics["max_inflight"] == 3
    assert metrics["backlog"] == 4
    assert metrics["max_body_bytes"] == 8192
    assert metrics["payload_bytes"]["p50"] == 100
    assert metrics["payload_bytes"]["max"] == 1000


def test_promoted_websocket_does_not_starve_short_http_requests() -> None:
    _PromotingHandler.websocket_entered.clear()
    _PromotingHandler.websocket_release.clear()
    server = BoundedThreadingHTTPServer(
        ("127.0.0.1", 0), _PromotingHandler,
        max_inflight=1, max_websockets=2, backlog=4,
    )
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    root = f"http://127.0.0.1:{server.server_address[1]}"
    held = threading.Thread(
        target=lambda: urllib.request.urlopen(
            root + "/websocket-hold", timeout=5,
        ).read(),
    )
    held.start()
    assert _PromotingHandler.websocket_entered.wait(timeout=3)
    try:
        with urllib.request.urlopen(root + "/health", timeout=3) as response:
            assert response.status == 200
            assert json.loads(response.read().decode("utf-8")) == {"ok": True}
        during = server.admission_metrics()
        assert during["websockets"]["active"] == 1
        assert during["websockets"]["promoted"] == 1
        assert during["rejected"] == 0
    finally:
        _PromotingHandler.websocket_release.set()
        held.join(timeout=5)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)

    after = server.admission_metrics()
    assert after["websockets"]["active"] == 0
    assert after["websockets"]["completed"] == 1


def test_promoted_websocket_pool_remains_bounded() -> None:
    _PromotingHandler.websocket_entered.clear()
    _PromotingHandler.websocket_release.clear()
    server = BoundedThreadingHTTPServer(
        ("127.0.0.1", 0), _PromotingHandler,
        max_inflight=2, max_websockets=1, backlog=4,
    )
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    root = f"http://127.0.0.1:{server.server_address[1]}"
    held = threading.Thread(
        target=lambda: urllib.request.urlopen(
            root + "/websocket-hold", timeout=5,
        ).read(),
    )
    held.start()
    assert _PromotingHandler.websocket_entered.wait(timeout=3)
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(root + "/websocket-hold", timeout=3).read()
        assert caught.value.code == 503
        payload = json.loads(caught.value.read().decode("utf-8"))
        assert payload["code"] == "websocket_admission_saturated"
        metrics = server.admission_metrics()
        assert metrics["websockets"]["active"] == 1
        assert metrics["websockets"]["rejected"] == 1
    finally:
        _PromotingHandler.websocket_release.set()
        held.join(timeout=5)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)


def test_saturation_burst_returns_structured_503_without_transport_resets() -> None:
    _BlockingHandler.entered.clear()
    _BlockingHandler.release.clear()
    server = BoundedThreadingHTTPServer(
        ("127.0.0.1", 0), _BlockingHandler,
        max_inflight=1, backlog=128, max_body_bytes=4096,
    )
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    first = threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=5).read())
    first.start()
    assert _BlockingHandler.entered.wait(timeout=3)

    def rejected_request(_index: int) -> tuple[int, str, str]:
        try:
            urllib.request.urlopen(url, timeout=3).read()
            return 200, "", ""
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            return exc.code, str(payload.get("code") or ""), str(exc.headers.get("Retry-After") or "")

    try:
        with ThreadPoolExecutor(max_workers=64) as pool:
            rejected = list(pool.map(rejected_request, range(64)))
    finally:
        _BlockingHandler.release.set()
        first.join(timeout=5)
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)

    assert rejected == [(503, "api_admission_saturated", "1")] * 64
    metrics = server.admission_metrics()
    assert metrics["rejected"] == 64
    assert metrics["rejection_responders"]["peak"] <= metrics["rejection_responders"]["limit"]
    assert metrics["rejection_responders"]["dropped"] == 0
