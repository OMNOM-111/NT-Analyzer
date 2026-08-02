"""Browser-facing market-data WebSocket fan-out (localhost/auth session).

Initial history remains HTTP. This module streams incremental candle/event
updates. Batch poll stays as fallback until clients migrate.
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

_LOCK = threading.RLock()
_SERVER_THREAD: Optional[threading.Thread] = None
_LOOP: Optional[asyncio.AbstractEventLoop] = None
_CLIENTS: Set[Any] = set()
_DEFAULT_WS_PORT = 18766


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def broadcast_event(event: Dict[str, Any], bar_updates: Optional[List[Dict[str, Any]]] = None) -> None:
    loop = _LOOP
    if loop is None:
        return
    message = {
        "type": "market_event",
        "event": event,
        "bar_updates": list(bar_updates or []),
        "server_time_utc": _iso(),
        "sources": {
            "chart_source": event.get("provider") or "ninjatrader",
            "strategy_source": "ninjatrader",
            "execution_source": "ninjatrader",
            "data_plane": event.get("data_plane") or "display",
        },
    }
    payload = json.dumps(message, ensure_ascii=False)

    async def _send_all() -> None:
        dead = []
        for ws in list(_CLIENTS):
            try:
                await ws.send(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _CLIENTS.discard(ws)

    try:
        asyncio.run_coroutine_threadsafe(_send_all(), loop)
    except Exception:
        pass


def start_ws_server(host: str = "127.0.0.1", port: int = _DEFAULT_WS_PORT) -> Dict[str, Any]:
    """Start optional websockets server. No-op if package missing."""
    global _SERVER_THREAD, _LOOP
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("WS server must bind localhost only")
    host = "127.0.0.1"
    with _LOCK:
        if _SERVER_THREAD and _SERVER_THREAD.is_alive():
            return {"ok": True, "already": True, "port": port}

    try:
        from websockets.server import serve
    except Exception as exc:
        return {"ok": False, "reason": f"websockets_unavailable:{exc}"}

    ready = threading.Event()
    state: Dict[str, Any] = {"ok": False, "port": port}

    async def handler(ws):
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
        except Exception:
            await ws.close(code=4401, reason="auth required")
            return
        if str(msg.get("type") or "") != "auth" or not str(msg.get("token") or "").strip():
            await ws.close(code=4401, reason="auth required")
            return
        token = str(msg.get("token") or "")
        from . import market_data_ipc
        ipc_token = market_data_ipc.auth_token()
        if token != ipc_token and not token.startswith("session:"):
            await ws.close(code=4403, reason="unauthorized")
            return
        await ws.send(json.dumps({
            "type": "welcome",
            "server_time_utc": _iso(),
            "sources": {
                "chart_source": "pending",
                "strategy_source": "ninjatrader",
                "execution_source": "ninjatrader",
            },
        }))
        _CLIENTS.add(ws)
        try:
            async for _ in ws:
                pass
        finally:
            _CLIENTS.discard(ws)

    def runner() -> None:
        global _LOOP
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _LOOP = loop

        async def main() -> None:
            async with serve(handler, host, port):
                state["ok"] = True
                ready.set()
                await asyncio.Future()

        try:
            loop.run_until_complete(main())
        except Exception as exc:
            state["ok"] = False
            state["error"] = str(exc)
            ready.set()
        finally:
            try:
                loop.close()
            except Exception:
                pass

    thread = threading.Thread(target=runner, name="md-ws-ui", daemon=True)
    _SERVER_THREAD = thread
    thread.start()
    ready.wait(timeout=3.0)
    return state
