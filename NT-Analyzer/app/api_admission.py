"""Bounded HTTP admission and process-local saturation metrics."""
from __future__ import annotations

import json
import socket
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from typing import Any, Dict


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction))))
    return float(ordered[index])


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with a hard in-flight request ceiling.

    The OS listen backlog is bounded separately.  Once accepted work reaches
    ``max_inflight``, a request receives a small 503 response instead of
    creating another unbounded handler thread.
    """

    daemon_threads = True
    block_on_close = True

    def __init__(
        self, server_address: Any, handler_class: Any, *,
        max_inflight: int = 64, backlog: int = 128,
        max_body_bytes: int = 1024 * 1024,
        max_websockets: int = 128,
    ) -> None:
        self.max_inflight = max(1, min(1024, int(max_inflight or 64)))
        self.request_queue_size = max(1, min(4096, int(backlog or 128)))
        self.max_body_bytes = max(1024, min(8 * 1024 * 1024, int(max_body_bytes)))
        self.max_websockets = max(1, min(4096, int(max_websockets or 128)))
        self._slots = threading.BoundedSemaphore(self.max_inflight)
        self._websocket_slots = threading.BoundedSemaphore(self.max_websockets)
        self._request_slot = threading.local()
        self._rejector_limit = max(2, min(16, self.max_inflight))
        self._rejector_slots = threading.BoundedSemaphore(self._rejector_limit)
        self._metrics_lock = threading.Lock()
        self._active = 0
        self._peak_active = 0
        self._accepted = 0
        self._rejected = 0
        self._rejection_active = 0
        self._rejection_peak = 0
        self._rejection_dropped = 0
        self._completed = 0
        self._websocket_active = 0
        self._websocket_peak = 0
        self._websocket_promoted = 0
        self._websocket_rejected = 0
        self._websocket_completed = 0
        self._websocket_durations_ms: deque[float] = deque(maxlen=10000)
        self._durations_ms: deque[float] = deque(maxlen=10000)
        self._payload_bytes: deque[int] = deque(maxlen=10000)
        super().__init__(server_address, handler_class)

    @staticmethod
    def _overload_payload() -> bytes:
        return json.dumps(
            {
                "error": "Server is at its bounded request capacity.",
                "code": "api_admission_saturated",
            },
            separators=(",", ":"),
        ).encode("utf-8")

    def _reject_overload(self, request: Any) -> None:
        # Read the request headers before closing the socket.  On Windows,
        # closing a TCP socket with unread request bytes can turn an otherwise
        # valid 503 into RST/ConnectionAbortedError at the client.  This work is
        # performed by a separate *bounded* rejector pool so a slow client
        # cannot block the accept loop or create unbounded handler threads.
        previous_timeout = request.gettimeout()
        header = bytearray()
        try:
            request.settimeout(0.25)
            while len(header) < 16384 and b"\r\n\r\n" not in header:
                chunk = request.recv(min(4096, 16384 - len(header)))
                if not chunk:
                    break
                header.extend(chunk)
        except (OSError, TimeoutError):
            pass

        body = self._overload_payload()
        status = int(HTTPStatus.SERVICE_UNAVAILABLE)
        reason = HTTPStatus.SERVICE_UNAVAILABLE.phrase
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            "Content-Type: application/json; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Retry-After: 1\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii") + body
        try:
            request.sendall(response)
        except OSError:
            pass
        finally:
            try:
                request.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            # Give already-sent client bytes a short drain window so closing
            # the socket cannot reset the response.  The body size is bounded
            # by the server contract and the deadline remains short.
            try:
                request.settimeout(0.05)
                remaining = self.max_body_bytes + 16384
                while remaining > 0:
                    chunk = request.recv(min(4096, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
            except (OSError, TimeoutError):
                pass
            try:
                request.settimeout(previous_timeout)
            except OSError:
                pass
            self.close_request(request)

    def _reject_overload_thread(self, request: Any) -> None:
        try:
            self._reject_overload(request)
        finally:
            with self._metrics_lock:
                self._rejection_active = max(0, self._rejection_active - 1)
            self._rejector_slots.release()

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            with self._metrics_lock:
                self._rejected += 1
            # Waiting briefly here is bounded backpressure and prevents burst
            # traffic from overflowing even the small rejector pool.
            if not self._rejector_slots.acquire(timeout=0.1):
                with self._metrics_lock:
                    self._rejection_dropped += 1
                self.shutdown_request(request)
                return
            with self._metrics_lock:
                self._rejection_active += 1
                self._rejection_peak = max(
                    self._rejection_peak, self._rejection_active,
                )
            thread = threading.Thread(
                target=self._reject_overload_thread,
                args=(request,),
                name="stratforge-api-rejector",
                daemon=True,
            )
            thread.start()
            return
        with self._metrics_lock:
            self._active += 1
            self._peak_active = max(self._peak_active, self._active)
            self._accepted += 1
        try:
            super().process_request(request, client_address)
        except Exception:
            with self._metrics_lock:
                self._active = max(0, self._active - 1)
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        started = time.perf_counter()
        self._request_slot.kind = "http"
        try:
            super().process_request_thread(request, client_address)
        finally:
            elapsed = (time.perf_counter() - started) * 1000.0
            slot_kind = str(getattr(self._request_slot, "kind", "http"))
            try:
                if slot_kind == "websocket":
                    with self._metrics_lock:
                        self._websocket_active = max(0, self._websocket_active - 1)
                        self._websocket_completed += 1
                        self._websocket_durations_ms.append(elapsed)
                    self._websocket_slots.release()
                else:
                    with self._metrics_lock:
                        self._active = max(0, self._active - 1)
                        self._completed += 1
                        self._durations_ms.append(elapsed)
                    self._slots.release()
            finally:
                try:
                    del self._request_slot.kind
                except AttributeError:
                    pass

    def promote_websocket_request(self) -> bool:
        """Move the current upgraded request out of the short HTTP pool.

        A WebSocket handler lives for the browser session. Counting it against
        ``max_inflight`` permanently starves bars, auth and admin HTTP once a
        large chart layout reaches that limit. The connection remains bounded
        by its own pool, while the short request slot is released immediately.
        """
        if str(getattr(self._request_slot, "kind", "")) != "http":
            return False
        if not self._websocket_slots.acquire(blocking=False):
            with self._metrics_lock:
                self._websocket_rejected += 1
            return False
        with self._metrics_lock:
            self._active = max(0, self._active - 1)
            self._websocket_active += 1
            self._websocket_peak = max(self._websocket_peak, self._websocket_active)
            self._websocket_promoted += 1
        self._request_slot.kind = "websocket"
        self._slots.release()
        return True

    def record_payload(self, size_bytes: int) -> None:
        with self._metrics_lock:
            self._payload_bytes.append(max(0, int(size_bytes or 0)))

    def admission_metrics(self) -> Dict[str, Any]:
        with self._metrics_lock:
            durations = list(self._durations_ms)
            websocket_durations = list(self._websocket_durations_ms)
            payloads = [float(value) for value in self._payload_bytes]
            return {
                "max_inflight": self.max_inflight,
                "backlog": self.request_queue_size,
                "max_body_bytes": self.max_body_bytes,
                "active": self._active,
                "peak_active": self._peak_active,
                "accepted": self._accepted,
                "rejected": self._rejected,
                "rejection_responders": {
                    "limit": self._rejector_limit,
                    "active": self._rejection_active,
                    "peak": self._rejection_peak,
                    "dropped": self._rejection_dropped,
                },
                "completed": self._completed,
                "websockets": {
                    "max": self.max_websockets,
                    "active": self._websocket_active,
                    "peak": self._websocket_peak,
                    "promoted": self._websocket_promoted,
                    "rejected": self._websocket_rejected,
                    "completed": self._websocket_completed,
                    "duration_ms": {
                        "p50": _percentile(websocket_durations, 0.50),
                        "p95": _percentile(websocket_durations, 0.95),
                        "max": max(websocket_durations, default=0.0),
                    },
                },
                "duration_ms": {
                    "p50": _percentile(durations, 0.50),
                    "p95": _percentile(durations, 0.95),
                    "p99": _percentile(durations, 0.99),
                    "max": max(durations, default=0.0),
                },
                "payload_bytes": {
                    "p50": _percentile(payloads, 0.50),
                    "p95": _percentile(payloads, 0.95),
                    "p99": _percentile(payloads, 0.99),
                    "max": int(max(payloads, default=0.0)),
                },
            }
