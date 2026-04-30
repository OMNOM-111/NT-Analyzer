"""
NT-Analyzer local backend (stdlib only — no FastAPI, no pip install).

- Binds to 127.0.0.1 ONLY. Never to 0.0.0.0.
- Serves /api/* JSON and /ui/* static files (UI bundle).
- Reads/writes only via app.jobqueue (whitelisted ops on the file queue).

Endpoints:
    GET  /api/health
    GET  /api/strategies
    GET  /api/jobs                  list recent jobs (limit query param)
    POST /api/jobs                  create a new job
    GET  /api/jobs/{job_id}         full job summary (job + result/error)
    GET  /api/jobs/{job_id}/trades  trades.json with offset/limit
    GET  /api/diagnostics           NinjaTrader process + bridge log tail
    GET  /                          redirect to /ui/
    GET  /ui/...                    static UI bundle
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

# Allow `python app/server.py` to import sibling module.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import jobqueue  # type: ignore[no-redef]
    from app import marginrefresh  # type: ignore[no-redef]
else:
    from . import jobqueue
    from . import marginrefresh


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Allowed origin hosts for mutating requests (POST). Browsers attach Origin
# automatically; non-browser clients (CLI, PowerShell Invoke-RestMethod) do
# not send it, which is also accepted (empty Origin == not a cross-site
# browser request). The current bind port is appended at runtime.
_ALLOWED_ORIGIN_HOSTS = ("127.0.0.1", "localhost")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".ico":  "image/x-icon",
    ".png":  "image/png",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "NTAnalyzer/0.1"

    # silence default access log
    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("NTA_BACKEND_VERBOSE"):
            super().log_message(fmt, *args)

    # ------------- helpers -------------------------------------------------

    def _json(self, status: int, body: Dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        # CSP-ish hardening for a local UI
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _err(self, status: int, msg: str) -> None:
        self._json(status, {"error": msg})

    def _read_body(self) -> Optional[Dict[str, Any]]:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        if n > 1 * 1024 * 1024:
            self._err(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
            return None
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._err(HTTPStatus.BAD_REQUEST, f"invalid json: {e}")
            return None

    def _check_local_post(self) -> bool:
        """Reject cross-site POSTs from a browser. Returns True if the request
        is allowed (and writes an error + returns False otherwise).

        Rules:
          - Content-Type must be application/json (case-insensitive, params ok).
          - Origin (preferred) or Referer, if present, must point to
            http://127.0.0.1:<this_port> or http://localhost:<this_port>.
          - Missing Origin AND Referer is allowed (CLI/PowerShell clients).
        """
        ct = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ct != "application/json":
            self._err(HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                      "Content-Type must be application/json")
            return False
        return self._check_local_origin()

    def _check_local_origin(self) -> bool:
        """Check Origin/Referer without requiring a Content-Type (used for DELETE)."""
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin:
            return True  # non-browser client (CLI, Invoke-RestMethod)
        try:
            u = urllib.parse.urlparse(origin)
        except Exception:
            self._err(HTTPStatus.FORBIDDEN, "bad Origin/Referer")
            return False
        if u.scheme != "http":
            self._err(HTTPStatus.FORBIDDEN, "non-http Origin/Referer rejected")
            return False
        if (u.hostname or "") not in _ALLOWED_ORIGIN_HOSTS:
            self._err(HTTPStatus.FORBIDDEN, f"Origin host not allowed: {u.hostname}")
            return False
        try:
            port = u.port or 80
        except ValueError:
            self._err(HTTPStatus.FORBIDDEN, "bad Origin port")
            return False
        bind_port = self.server.server_address[1]
        if port != bind_port:
            self._err(HTTPStatus.FORBIDDEN,
                      f"Origin port {port} != backend port {bind_port}")
            return False
        return True

    # ------------- static (UI bundle) -------------------------------------

    def _serve_static(self, rel: str) -> None:
        if not rel or rel == "/":
            rel = "index.html"
        rel = rel.lstrip("/")
        # Disallow path traversal: resolve and ensure inside STATIC_DIR.
        target = (STATIC_DIR / rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._err(HTTPStatus.FORBIDDEN, "path traversal blocked")
            return
        if not target.is_file():
            self._err(HTTPStatus.NOT_FOUND, f"static not found: {rel}")
            return
        ct = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    # ------------- routing -------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        path = url.path
        qs = urllib.parse.parse_qs(url.query)

        if path == "/" or path == "":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/ui/")
            self.end_headers()
            return

        if path.startswith("/ui"):
            rel = path[len("/ui"):] or "/"
            self._serve_static(rel)
            return

        if path == "/api/health":
            self._json(HTTPStatus.OK, {
                "ok": True,
                "host": HOST,
                "project_root": str(jobqueue.project_root()),
                "ninjatrader_running": jobqueue.ninjatrader_running(),
            })
            return

        if path == "/api/strategies":
            self._json(HTTPStatus.OK, {
                "strategies": jobqueue.whitelisted_strategies(),
                "note": "strategy whitelist is enforced on the bridge AddOn too",
            })
            return

        if path == "/api/catalog":
            self._json(HTTPStatus.OK, jobqueue.build_catalog_response())
            return

        if path == "/api/jobs":
            try:
                limit = int((qs.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            limit = max(1, min(200, limit))
            self._json(HTTPStatus.OK, {
                "counts": jobqueue.queue_counts(),
                "jobs": jobqueue.list_jobs(limit=limit),
            })
            return

        # /api/jobs/<job_id>(/trades)?
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "jobs":
            job_id = parts[2]
            try:
                jobqueue._safe_job_id(job_id)
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if len(parts) == 3:
                full = jobqueue.read_job_full(job_id)
                if not full:
                    self._err(HTTPStatus.NOT_FOUND, f"job not found: {job_id}")
                    return
                self._json(HTTPStatus.OK, full)
                return
            if len(parts) == 4 and parts[3] == "trades":
                try:
                    offset = int((qs.get("offset") or ["0"])[0])
                    limit = int((qs.get("limit") or ["100"])[0])
                except ValueError:
                    offset, limit = 0, 100
                self._json(HTTPStatus.OK, jobqueue.read_trades(job_id, offset=offset, limit=limit))
                return
            if len(parts) == 4 and parts[3] == "bars":
                try:
                    offset = int((qs.get("offset") or ["0"])[0])
                    limit = int((qs.get("limit") or ["5000"])[0])
                except ValueError:
                    offset, limit = 0, 5000
                self._json(HTTPStatus.OK, jobqueue.read_bars(job_id, offset=offset, limit=limit))
                return
            if len(parts) == 4 and parts[3] == "draw_objects":
                self._json(HTTPStatus.OK, jobqueue.read_draw_objects(job_id))
                return

        if path == "/api/diagnostics":
            cat = jobqueue.build_catalog_response()
            self._json(HTTPStatus.OK, {
                "ninjatrader_running": jobqueue.ninjatrader_running(),
                "ninjatrader_user_dir": str(jobqueue.ninjatrader_user_dir()),
                "bridge_log_tail": jobqueue.bridge_log_tail(40),
                "catalog": {
                    "warnings":         cat.get("warnings") or [],
                    "strategies_count": len(cat.get("strategies") or []),
                    "instruments_count": len(cat.get("instruments") or []),
                    "generated_at_utc": cat.get("generated_at_utc") or {},
                    "staleness":        cat.get("staleness") or {},
                },
            })
            return

        # /api/batches collection + per-batch detail/results.
        if path == "/api/batches":
            try:
                limit = int((qs.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            limit = max(1, min(200, limit))
            self._json(HTTPStatus.OK, {
                "batches": jobqueue.list_batches(limit=limit),
            })
            return

        if len(parts) >= 3 and parts[0] == "api" and parts[1] == "batches":
            batch_id = parts[2]
            try:
                jobqueue._safe_batch_id(batch_id)
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if len(parts) == 3:
                m = jobqueue.read_batch(batch_id)
                if not m:
                    self._err(HTTPStatus.NOT_FOUND, f"batch not found: {batch_id}")
                    return
                self._json(HTTPStatus.OK, m)
                return
            if len(parts) == 4 and parts[3] == "results":
                r = jobqueue.read_batch_results(batch_id)
                if not r:
                    self._err(HTTPStatus.NOT_FOUND, f"batch not found: {batch_id}")
                    return
                self._json(HTTPStatus.OK, r)
                return

        self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")

    def do_DELETE(self) -> None:  # noqa: N802
        """DELETE /api/jobs/<id>  or  DELETE /api/batches/<id>"""
        url = urllib.parse.urlparse(self.path)
        path = url.path
        parts = [p for p in path.split("/") if p]

        is_del_job   = (len(parts) == 3 and parts[0] == "api"
                        and parts[1] == "jobs")
        is_del_batch = (len(parts) == 3 and parts[0] == "api"
                        and parts[1] == "batches")

        if not (is_del_job or is_del_batch):
            self._err(HTTPStatus.NOT_FOUND, f"no DELETE route: {path}")
            return

        if not self._check_local_origin():
            return

        if is_del_job:
            try:
                jobqueue._safe_job_id(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            result = jobqueue.delete_job(parts[2])
            if not result.get("deleted"):
                reason = result.get("reason", "unknown")
                if reason == "not_found":
                    self._err(HTTPStatus.NOT_FOUND, f"job not found: {parts[2]}")
                elif reason == "running":
                    self._err(HTTPStatus.CONFLICT,
                              "Нельзя удалить запущенный job; сначала отмените.")
                else:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR, reason)
                return
            self._json(HTTPStatus.OK, result)
            return

        # is_del_batch
        try:
            jobqueue._safe_batch_id(parts[2])
        except jobqueue.JobValidationError as e:
            self._err(HTTPStatus.BAD_REQUEST, str(e))
            return
        result = jobqueue.delete_batch(parts[2])
        if not result.get("deleted"):
            reason = result.get("reason", "unknown")
            if reason == "not_found":
                self._err(HTTPStatus.NOT_FOUND, f"batch not found: {parts[2]}")
            elif reason == "has_running_jobs":
                self._err(HTTPStatus.CONFLICT,
                          "Пакет содержит запущенные задачи; сначала отмените их.")
            else:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, reason)
            return
        self._json(HTTPStatus.OK, result)

    def do_POST(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        path = url.path

        # /api/jobs/<id>/cancel and /api/batches/<id>/cancel
        parts = [p for p in path.split("/") if p]
        is_cancel_job = (len(parts) == 4 and parts[0] == "api"
                         and parts[1] == "jobs"     and parts[3] == "cancel")
        is_cancel_batch = (len(parts) == 4 and parts[0] == "api"
                           and parts[1] == "batches" and parts[3] == "cancel")
        is_catalog_refresh = (path == "/api/catalog/refresh")
        is_margins_refresh = (path == "/api/margins/refresh")

        if not (path in ("/api/jobs", "/api/batches")
                or is_cancel_job or is_cancel_batch
                or is_catalog_refresh or is_margins_refresh):
            self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
            return

        if not self._check_local_post():
            return  # _check_local_post already wrote an error

        if is_catalog_refresh:
            out = jobqueue.request_catalog_refresh()
            status = HTTPStatus.OK if out.get("ok") else HTTPStatus.GATEWAY_TIMEOUT
            self._json(status, out)
            return

        if is_margins_refresh:
            out = marginrefresh.refresh_margins_now(trigger="manual")
            status = HTTPStatus.OK if out.get("ok") else HTTPStatus.BAD_GATEWAY
            self._json(status, out)
            return

        if is_cancel_job:
            try:
                jobqueue._safe_job_id(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            try:
                out = jobqueue.cancel_job(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if out.get("action") == "not_found":
                self._err(HTTPStatus.NOT_FOUND, f"job not found: {parts[2]}")
                return
            self._json(HTTPStatus.OK, out)
            return

        if is_cancel_batch:
            try:
                jobqueue._safe_batch_id(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            try:
                out = jobqueue.cancel_batch(parts[2])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            if not out.get("found"):
                self._err(HTTPStatus.NOT_FOUND, f"batch not found: {parts[2]}")
                return
            self._json(HTTPStatus.OK, out)
            return

        body = self._read_body()
        if body is None:
            return  # _read_body already wrote an error

        if path == "/api/batches":
            try:
                req = jobqueue.CreateBatchRequest(
                    class_name=str(body.get("class_name") or ""),
                    instruments=list(body.get("instruments") or []),
                    bars_period_type=str(body.get("bars_period_type") or "Minute"),
                    bars_period_value=int(body.get("bars_period_value") or 1),
                    from_utc=str(body.get("from_utc") or ""),
                    to_utc=str(body.get("to_utc") or ""),
                    parameters=body.get("parameters") or {},
                    risk_profile=body.get("risk_profile") or {},
                    calculate=str(body.get("calculate") or "OnBarClose"),
                    is_tick_replay=bool(body.get("is_tick_replay") or False),
                    order_fill_resolution=str(body.get("order_fill_resolution") or "Standard"),
                    slippage_ticks=int(body.get("slippage_ticks") or 0),
                    commission=float(body.get("commission") or 0.0),
                    commission_template=str(body.get("commission_template") or "None"),
                    session_template=str(body.get("session_template") or "CME US Index Futures RTH"),
                    timezone=str(body.get("timezone") or "UTC"),
                    name=(str(body["name"]) if body.get("name") else None),
                )
            except (TypeError, ValueError) as e:
                self._err(HTTPStatus.BAD_REQUEST, f"bad request: {e}")
                return
            try:
                batch_id, job_ids = jobqueue.create_batch(req)
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            self._json(HTTPStatus.CREATED, {
                "batch_id": batch_id,
                "job_ids":  job_ids,
                "total":    len(job_ids),
            })
            return

        # Defensive whitelist of allowed top-level keys: never accept paths/ids
        # that could escape the queue.
        try:
            req = jobqueue.CreateJobRequest(
                class_name=str(body.get("class_name") or ""),
                instrument=str(body.get("instrument") or ""),
                bars_period_type=str(body.get("bars_period_type") or "Minute"),
                bars_period_value=int(body.get("bars_period_value") or 1),
                from_utc=str(body.get("from_utc") or ""),
                to_utc=str(body.get("to_utc") or ""),
                parameters=body.get("parameters") or {},
                risk_profile=body.get("risk_profile") or {},
                calculate=str(body.get("calculate") or "OnBarClose"),
                is_tick_replay=bool(body.get("is_tick_replay") or False),
                order_fill_resolution=str(body.get("order_fill_resolution") or "Standard"),
                slippage_ticks=int(body.get("slippage_ticks") or 0),
                commission=float(body.get("commission") or 0.0),
                commission_template=str(body.get("commission_template") or "None"),
                session_template=str(body.get("session_template") or "CME US Index Futures RTH"),
                timezone=str(body.get("timezone") or "UTC"),
                job_id=None,  # never trust client-supplied ids in MVP-1
            )
        except (TypeError, ValueError) as e:
            self._err(HTTPStatus.BAD_REQUEST, f"bad request: {e}")
            return

        try:
            job_id, path = jobqueue.create_job(req)
        except jobqueue.JobValidationError as e:
            self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        self._json(HTTPStatus.CREATED, {"job_id": job_id, "path": str(path)})


# ---------------------------------------------------------------------------

def _bind_or_pick_port(start_port: int = DEFAULT_PORT, attempts: int = 10) -> int:
    """Return a free port on 127.0.0.1 starting from start_port."""
    for off in range(attempts):
        port = start_port + off
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"no free port in {start_port}..{start_port+attempts-1}")


def run(port: Optional[int] = None) -> None:
    bind_port = port or _bind_or_pick_port(DEFAULT_PORT)
    server = ThreadingHTTPServer((HOST, bind_port), Handler)
    server.daemon_threads = True
    print(f"[nta-backend] listening on http://{HOST}:{bind_port}/")
    print(f"[nta-backend] UI:           http://{HOST}:{bind_port}/ui/")
    print(f"[nta-backend] project_root: {jobqueue.project_root()}")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[nta-backend] shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    p = None
    if len(sys.argv) > 1:
        try:
            p = int(sys.argv[1])
        except ValueError:
            pass
    run(p)
