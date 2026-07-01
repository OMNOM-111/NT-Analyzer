"""Loopback OpenAI-compatible adapter for the external-agent benchmark.

It exposes one representative chat agent per provider/model combination to the
existing read-only benchmark. API keys remain inside DPAPI and are never emitted.
"""
from __future__ import annotations

import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai_lab import agent_registry, universal_llm


HOST = "127.0.0.1"


def _safe_alias(agent: Dict[str, Any]) -> str:
    provider = str(agent.get("provider") or "provider").replace("_", "-")
    model = str(agent.get("model") or "model").replace("/", "-").replace(":", "-")
    return f"external-{provider}-{model}"[:160]


def representatives() -> Dict[str, Dict[str, Any]]:
    grouped: Dict[tuple[str, str], list[Dict[str, Any]]] = {}
    for agent in agent_registry.list_agents():
        if agent.get("endpoint_type") != "chat" or not agent.get("key_configured"):
            continue
        grouped.setdefault((str(agent.get("provider")), str(agent.get("model"))), []).append(agent)
    selected: Dict[str, Dict[str, Any]] = {}
    for rows in grouped.values():
        rows.sort(key=lambda row: (
            0 if row.get("enabled") else 1,
            int(row.get("requests_today") or 0),
            str(row.get("account_name") or ""),
        ))
        agent = rows[0]
        alias = _safe_alias(agent)
        selected[alias] = agent
    return selected


AGENTS = representatives()


class Handler(BaseHTTPRequestHandler):
    server_version = "StratForgeAgentBenchmark/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print("[agent-benchmark-proxy] " + (fmt % args), flush=True)

    def _json(self, status: int, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            self._json(HTTPStatus.OK, {
                "object": "list",
                "data": [
                    {"id": alias, "object": "model", "owned_by": "stratforge-external"}
                    for alias in AGENTS
                ],
            })
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(HTTPStatus.NOT_FOUND, {"error": {"message": "not found"}})
            return
        try:
            size = min(int(self.headers.get("Content-Length") or 0), 200_000)
            body = json.loads(self.rfile.read(size).decode("utf-8"))
            alias = str(body.get("model") or "")
            agent = AGENTS.get(alias)
            if not agent:
                raise ValueError("unknown benchmark model")
            messages = body.get("messages") if isinstance(body.get("messages"), list) else []
            system = "\n\n".join(
                str(row.get("content") or "") for row in messages
                if isinstance(row, dict) and row.get("role") in {"system", "developer"}
            )
            prompt = "\n\n".join(
                str(row.get("content") or "") for row in messages
                if isinstance(row, dict) and row.get("role") not in {"system", "developer"}
            )
            result = universal_llm.invoke_agent(
                str(agent["id"]), prompt, system_prompt=system,
                max_output_tokens=int(body.get("max_tokens") or 1024),
                timeout=300, allow_disabled=True,
                request_role="benchmark", purpose="external_model_benchmark",
            )
            self._json(HTTPStatus.OK, {
                "id": result.get("request_id"), "object": "chat.completion",
                "model": alias,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": result["response"]}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": result.get("input_tokens") or 0,
                    "completion_tokens": result.get("output_tokens") or 0,
                    "total_tokens": result.get("total_tokens") or 0,
                },
                "stratforge": {
                    "provider": result.get("provider"), "actual_model": result.get("actual_model"),
                    "cost_usd": result.get("cost_usd"), "cost_estimated": result.get("cost_estimated"),
                },
            })
        except Exception as exc:  # noqa: BLE001
            self._json(HTTPStatus.BAD_GATEWAY, {"error": {"message": str(exc)[:500]}})


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8879
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(f"[agent-benchmark-proxy] listening http://{HOST}:{port}/v1", flush=True)
    print(f"[agent-benchmark-proxy] models={list(AGENTS)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
