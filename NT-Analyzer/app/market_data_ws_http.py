"""Same-origin browser WebSocket hub for /ws/market-data.

Uses RFC6455 framing over the main HTTP server socket after Upgrade.
Bridge IPC remains on localhost:18765 and is never exposed to browsers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_OUTBOUND = 64

_LOCK = threading.RLock()
_CLIENTS: Set["WsClient"] = set()
_METRICS = {
    "accepted": 0,
    "rejected": 0,
    "messages_out": 0,
    "coalesced": 0,
    "dropped": 0,
    "non_bar_events_filtered": 0,
    "clients": 0,
}


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def accept_key(sec_key: str) -> str:
    digest = hashlib.sha1((sec_key + GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_text_frame(text: str) -> bytes:
    payload = text.encode("utf-8")
    n = len(payload)
    if n < 126:
        header = struct.pack("!BB", 0x81, n)
    elif n < 65536:
        header = struct.pack("!BBH", 0x81, 126, n)
    else:
        header = struct.pack("!BBQ", 0x81, 127, n)
    return header + payload


def decode_frames(buffer: bytearray) -> Tuple[List[str], bytearray]:
    """Decode one or more masked client frames; return texts and remainder."""
    messages: List[str] = []
    while True:
        if len(buffer) < 2:
            return messages, buffer
        b0, b1 = buffer[0], buffer[1]
        opcode = b0 & 0x0F
        masked = (b1 & 0x80) != 0
        length = b1 & 0x7F
        idx = 2
        if length == 126:
            if len(buffer) < 4:
                return messages, buffer
            length = struct.unpack("!H", buffer[2:4])[0]
            idx = 4
        elif length == 127:
            if len(buffer) < 10:
                return messages, buffer
            length = struct.unpack("!Q", buffer[2:10])[0]
            idx = 10
        mask = b""
        if masked:
            if len(buffer) < idx + 4:
                return messages, buffer
            mask = bytes(buffer[idx:idx + 4])
            idx += 4
        if len(buffer) < idx + length:
            return messages, buffer
        payload = bytearray(buffer[idx:idx + length])
        if masked:
            for i in range(len(payload)):
                payload[i] ^= mask[i % 4]
        del buffer[: idx + length]
        if opcode == 0x8:  # close
            messages.append("")
            return messages, buffer
        if opcode == 0x9:  # ping → ignore here; handler may pong
            continue
        if opcode in (0x1, 0x2, 0x0):
            try:
                messages.append(payload.decode("utf-8"))
            except UnicodeDecodeError:
                continue
    return messages, buffer


class WsClient:
    def __init__(self, request_handler: Any, user_id: str = "") -> None:
        self.handler = request_handler
        self.user_id = user_id
        self.subscriptions: Set[str] = set()  # exact_contract|tf
        # Browser WebSocket subscriptions own a ref-counted upstream lease.  A
        # large layout remains one browser connection and one shared ProjectX
        # market socket, while closing/reconfiguring a chart releases its lease.
        self.upstream_refs: Dict[str, Dict[str, str]] = {}
        self.consumer_id = f"browser-ws:{id(self):x}"
        self.outbound: Deque[Dict[str, Any]] = deque()
        self.coalesce_slot: Dict[str, Dict[str, Any]] = {}
        self.alive = True
        self.connected_at = _iso()
        self._queue_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._wake = threading.Event()
        self._writer_thread: Optional[threading.Thread] = None

    def start_writer(self) -> None:
        if self._writer_thread is not None:
            return
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name=f"market-ws-writer-{id(self):x}",
            daemon=True,
        )
        self._writer_thread.start()

    def send_text(self, message: Dict[str, Any]) -> None:
        raw = encode_text_frame(json.dumps(message, ensure_ascii=False))
        with self._write_lock:
            self.handler.wfile.write(raw)
            self.handler.wfile.flush()

    def enqueue(self, message: Dict[str, Any]) -> None:
        """Latest-value coalesce for provisional bar updates; never drop closes."""
        kind = str(message.get("type") or "")
        bar = (message.get("bar_updates") or [None])[0] if message.get("bar_updates") else None
        action = ""
        key = ""
        if isinstance(bar, dict):
            action = str(bar.get("action") or "")
            b = bar.get("bar") if isinstance(bar.get("bar"), dict) else bar
            if isinstance(b, dict):
                key = f"{b.get('exact_contract')}|{b.get('timeframe')}|prov"
        if kind == "market_event" and not key:
            # ProjectX GatewayQuote also emits high-rate bestBid/bestAsk-only
            # events. They carry no browser bar update, but remain available to
            # consumers as a latest-value contract event. Never let those
            # replace closed bars or fill the reliable outbound queue.
            event = message.get("event") if isinstance(message.get("event"), dict) else {}
            contract = str(event.get("exact_contract") or "")
            if contract:
                key = f"{contract}|event"
        with self._queue_lock:
            if kind == "market_event" and key and (action == "update" or not bar):
                self.coalesce_slot[key] = message
                with _LOCK:
                    _METRICS["coalesced"] += 1
            else:
                if len(self.outbound) >= MAX_OUTBOUND:
                    self.outbound.popleft()
                    with _LOCK:
                        _METRICS["dropped"] += 1
                self.outbound.append(message)
        self._wake.set()

    def flush(self) -> None:
        """Wake the dedicated writer without blocking the provider reader."""
        self._wake.set()

    def _next_outbound(self) -> Optional[Dict[str, Any]]:
        with self._queue_lock:
            if self.outbound:
                return self.outbound.popleft()
            if self.coalesce_slot:
                key = next(iter(self.coalesce_slot))
                return self.coalesce_slot.pop(key)
        return None

    def _writer_loop(self) -> None:
        while self.alive:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            while self.alive:
                msg = self._next_outbound()
                if msg is None:
                    break
                try:
                    self.send_text(msg)
                    with _LOCK:
                        _METRICS["messages_out"] += 1
                except Exception:
                    self.alive = False
                    try:
                        self.handler.connection.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    break


def register_client(client: WsClient) -> None:
    with _LOCK:
        _CLIENTS.add(client)
        _METRICS["accepted"] += 1
        _METRICS["clients"] = len(_CLIENTS)
    client.start_writer()


def unregister_client(client: WsClient) -> None:
    client.alive = False
    client._wake.set()
    _release_client_upstreams(client)
    with _LOCK:
        _CLIENTS.discard(client)
        _METRICS["clients"] = len(_CLIENTS)


def reject() -> None:
    with _LOCK:
        _METRICS["rejected"] += 1


def _message_for_subscriptions(
    message: Dict[str, Any], subscriptions: Set[str],
) -> Optional[Dict[str, Any]]:
    """Keep only canonical bar updates requested by this browser client."""
    if str(message.get("type") or "") != "market_event":
        return message
    updates = message.get("bar_updates") or []
    if not updates or not subscriptions:
        return None
    if "*" in subscriptions:
        return message
    matched: List[Dict[str, Any]] = []
    for update in updates:
        if not isinstance(update, dict):
            continue
        bar = update.get("bar") if isinstance(update.get("bar"), dict) else update
        if not isinstance(bar, dict):
            continue
        contract = str(bar.get("exact_contract") or "").upper()
        timeframe = str(bar.get("timeframe") or "").lower()
        if (
            contract in subscriptions
            or f"{contract}|*" in subscriptions
            or f"{contract}|{timeframe}" in subscriptions
        ):
            matched.append(update)
    if not matched:
        return None
    if len(matched) == len(updates):
        return message
    filtered = dict(message)
    filtered["bar_updates"] = matched
    return filtered


def broadcast(message: Dict[str, Any]) -> None:
    updates = message.get("bar_updates") or []
    if str(message.get("type") or "") == "market_event" and not updates:
        # The desktop transport renders canonical bar updates. ProjectX also
        # emits much higher-rate bid/ask-only GatewayQuote events; the current
        # browser consumer ignores those completely, so writing them only adds
        # socket backpressure without changing a candle or price marker.
        with _LOCK:
            _METRICS["non_bar_events_filtered"] += 1
        return
    with _LOCK:
        clients = list(_CLIENTS)
    for client in clients:
        if not client.alive:
            continue
        filtered = _message_for_subscriptions(message, set(client.subscriptions))
        if filtered is not None:
            client.enqueue(filtered)


def metrics() -> Dict[str, Any]:
    with _LOCK:
        out = dict(_METRICS)
        out["active_clients"] = [
            {
                "connected_at": client.connected_at,
                "subscriptions": sorted(client.subscriptions),
                "upstream_leases": len(client.upstream_refs),
            }
            for client in sorted(_CLIENTS, key=lambda row: row.connected_at)
        ]
        return out


def _read_client_chunk(handler: Any, size: int = 4096) -> bytes:
    """Read one available WebSocket chunk without waiting to fill the buffer."""
    reader = handler.rfile
    read1 = getattr(reader, "read1", None)
    if callable(read1):
        return read1(size)
    return reader.read(size)


def handle_websocket_upgrade(handler: Any) -> bool:
    """Return True if the request was a market-data WS upgrade and was handled."""
    path = (handler.path or "").split("?", 1)[0]
    if path != "/ws/market-data":
        return False
    upgrade = (handler.headers.get("Upgrade") or "").lower()
    if upgrade != "websocket":
        handler.send_error(426, "Upgrade Required")
        return True
    key = handler.headers.get("Sec-WebSocket-Key")
    if not key:
        reject()
        handler.send_error(400, "missing Sec-WebSocket-Key")
        return True

    # Prefer authenticated session cookie / bearer when present; allow staging.
    user_id = ""
    try:
        from . import account_auth
        # Best-effort: reuse remote context if handler already authenticated.
        ctx = getattr(handler, "_remote_context", None) or {}
        user_id = str(ctx.get("user_id") or "")
    except Exception:
        user_id = ""

    # ``BaseHTTPRequestHandler`` defaults to an HTTP/1.0 status line. Chromium
    # accepts that leniently, but RFC6455 clients (including ``websockets``)
    # correctly reject an HTTP/1.0 Upgrade response before any frame is read.
    # Change only this response line; normal HTTP handlers retain their current
    # connection semantics.
    previous_protocol = getattr(handler, "protocol_version", "HTTP/1.0")
    handler.protocol_version = "HTTP/1.1"
    try:
        handler.send_response(101, "Switching Protocols")
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept_key(key))
        handler.end_headers()
    finally:
        handler.protocol_version = previous_protocol

    client = WsClient(handler, user_id=user_id)
    welcome = {
        "type": "welcome",
        "server_time_utc": _iso(),
        "path": "/ws/market-data",
        "sources": {
            "chart_source": "pending",
            "strategy_source": "ninjatrader",
            "execution_source": "ninjatrader",
        },
    }
    try:
        client.send_text(welcome)
    except Exception:
        unregister_client(client)
        return True
    register_client(client)

    buf = bytearray()
    try:
        while client.alive:
            # BufferedReader.read(4096) may wait for all 4096 bytes. Browser
            # subscribe/unsubscribe/close frames are much smaller, so that can
            # strand stale clients and their upstream TopstepX leases after a
            # reload. read1() returns the next available socket chunk instead.
            chunk = _read_client_chunk(handler)
            if not chunk:
                break
            buf.extend(chunk)
            messages, buf = decode_frames(buf)
            for text in messages:
                if text == "":
                    client.alive = False
                    break
                try:
                    msg = json.loads(text)
                except Exception:
                    continue
                _on_client_message(client, msg)
                client.flush()
    finally:
        client.alive = False
        unregister_client(client)
    return True


def _on_client_message(client: WsClient, msg: Dict[str, Any]) -> None:
    mtype = str(msg.get("type") or "")
    if mtype == "subscribe":
        contract = str(msg.get("exact_contract") or msg.get("instrument") or "").upper()
        timeframe = str(msg.get("timeframe") or "*").lower()
        if contract:
            key = f"{contract}|{timeframe}"
            client.subscriptions.add(key)
            _acquire_client_upstream(client, contract, timeframe)
            client.enqueue({
                "type": "subscribe_ack",
                "exact_contract": contract,
                "timeframe": timeframe,
            })
    elif mtype == "unsubscribe":
        contract = str(msg.get("exact_contract") or msg.get("instrument") or "").upper()
        timeframe = str(msg.get("timeframe") or "*").lower()
        key = f"{contract}|{timeframe}"
        client.subscriptions.discard(key)
        _release_client_upstream(client, key)
    elif mtype == "ping":
        client.enqueue({"type": "pong", "server_time_utc": _iso()})


def _acquire_client_upstream(client: WsClient, contract: str, timeframe: str) -> None:
    """Acquire one factual upstream lease; never open a provider per chart."""
    key = f"{contract}|{timeframe}"
    if key in client.upstream_refs:
        return
    # TopstepX owns independent read-only charts when configured.  Root symbols
    # are intentionally deferred until HTTP contract resolution sends the exact
    # expiry, avoiding a duplicate search/login burst during cold layout load.
    try:
        from .market_data_failover import TopstepXProvider
        topstep = TopstepXProvider()
        if topstep.configured():
            consumer = f"{client.consumer_id}:{key}"
            if topstep.acquire_chart_subscription(contract, timeframe, consumer):
                client.upstream_refs[key] = {
                    "provider": "topstepx", "contract": contract,
                    "timeframe": timeframe, "consumer_id": consumer,
                }
            return
    except Exception:
        # The history route reports the provider failure/failover.  Do not use
        # this browser-side lease helper to manufacture a second connection.
        return
    try:
        from .market_data_subscriptions import get_subscription_registry
        get_subscription_registry().acquire("ninjatrader", contract, "trades")
        client.upstream_refs[key] = {
            "provider": "ninjatrader", "contract": contract,
            "timeframe": timeframe, "consumer_id": "",
        }
    except Exception:
        pass


def _release_client_upstream(client: WsClient, key: str) -> None:
    ref = client.upstream_refs.pop(str(key), None)
    if not ref:
        return
    provider = str(ref.get("provider") or "")
    try:
        if provider == "topstepx":
            from .market_data_failover import TopstepXProvider
            TopstepXProvider().release_chart_subscription(
                str(ref.get("contract") or ""), str(ref.get("timeframe") or "1m"),
                str(ref.get("consumer_id") or ""),
            )
        elif provider == "ninjatrader":
            from .market_data_subscriptions import get_subscription_registry
            get_subscription_registry().release("ninjatrader", str(ref.get("contract") or ""), "trades")
    except Exception:
        pass


def _release_client_upstreams(client: WsClient) -> None:
    for key in list(client.upstream_refs):
        _release_client_upstream(client, key)
