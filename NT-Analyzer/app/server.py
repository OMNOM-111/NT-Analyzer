"""
NT-Analyzer local backend (stdlib only — no FastAPI, no pip install).

- Binds to 127.0.0.1 ONLY. Never to 0.0.0.0.
- Serves /api/* JSON and /ui/* static files (UI bundle).
- Reads/writes only via app.jobqueue (whitelisted ops on the file queue).

Endpoints:
    GET  /api/health
    GET  /api/strategies
    GET  /api/reports               mixed jobs + batches feed (shared pagination)
    GET  /api/jobs                  list recent jobs (limit query param)
    POST /api/jobs                  create a new job
    GET  /api/jobs/{job_id}         full job summary (job + result/error)
    GET  /api/jobs/{job_id}/trades  trades.json with offset/limit
    GET  /api/diagnostics           NinjaTrader process + bridge log tail
    GET  /                          redirect to /ui/
    GET  /ui/...                    static UI bundle
"""
from __future__ import annotations

import errno
import json
import math
import os
import socket
import subprocess
import sys
import threading
import urllib.parse
from datetime import timezone
from email.utils import formatdate, parsedate_to_datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

# Allow `python app/server.py` to import sibling module.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import jobqueue  # type: ignore[no-redef]
    from app import marginrefresh  # type: ignore[no-redef]
    from app import ops  # type: ignore[no-redef]
    from app import performance  # type: ignore[no-redef]
    from app import runtime as ops_runtime  # type: ignore[no-redef]
else:
    from . import jobqueue
    from . import marginrefresh
    from . import ops
    from . import performance
    from . import runtime as ops_runtime


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _do_restart_server() -> None:
    """Spawn a helper that waits for the old process to exit, then starts a new one."""
    port = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_PORT)
    cwd = str(_PROJECT_ROOT)
    exe = sys.executable
    helper = (
        "import time, subprocess, sys\n"
        f"time.sleep(1.2)\n"
        f"subprocess.Popen([{exe!r}, '-m', 'app.server', {port!r}], cwd={cwd!r})\n"
    )
    kw: dict = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen([exe, "-c", helper], cwd=cwd, **kw)
    os._exit(0)

# Allowed origin hosts for mutating requests (POST). Browsers attach Origin
# automatically; non-browser clients (CLI, PowerShell Invoke-RestMethod) do
# not send it, which is also accepted (empty Origin == not a cross-site
# browser request). The current bind port is appended at runtime.
_ALLOWED_ORIGIN_HOSTS = ("127.0.0.1", "localhost")


# ---------------------------------------------------------------------------
# Strategy Control Center — real source from NinjaTrader Strategies folder
# ---------------------------------------------------------------------------

def _default_ninjatrader_user_dir() -> Path:
    override = os.environ.get("NINJATRADER_USER_DIR")
    if override:
        return Path(override)
    return Path.home() / "Documents" / "NinjaTrader 8"


_NT_USER_DIR = _default_ninjatrader_user_dir()
_NT_STRATEGIES_DIR = _NT_USER_DIR / "bin" / "Custom" / "Strategies" / "NT-Analyzer_strategies"
_NT_STRATEGIES_LEGACY_DIR = _NT_USER_DIR / "bin" / "Custom" / "Strategies"
_SCC_ACTIVE_CLASSES: set = {
    "PullbackMNQ5mV2",
    "VWAPPullbackMGC5mV1",
    "B1ShortOnlyMGC5mV2",
    "B1Stop24MGC5mC003",
    "B1Stop20MGC5mC004",
    "NTAMicroVwapRiskPilot",
    "NTAMicroMnqScalpPilot",
    "NTAMnqMicroOrbOpenScalp",
    "NTAnalyzerEveryNBarLong",
    "StrategiyaUrovney",
}
_SCC_REJECTED_CLASSES: set = {
    "NTAMicroOrbPilot",
    "NTAMicroVwapGapMirrorPilot",
    "NTAMicroVwapMeanRevertPilot",
}


def _iter_nt_strategy_entries():
    seen_roots = set()
    for root in (_NT_STRATEGIES_DIR, _NT_STRATEGIES_LEGACY_DIR):
        if root in seen_roots or not root.is_dir():
            continue
        seen_roots.add(root)
        for entry in sorted(root.iterdir()):
            if root == _NT_STRATEGIES_LEGACY_DIR and entry.is_dir() and entry.name == _NT_STRATEGIES_DIR.name:
                continue
            yield entry


def _build_scc_strategies() -> Dict[str, Any]:
    """Scan active NinjaTrader strategy roots + merge runtime telemetry."""
    folder_strats: list = []
    seen_classes = set()
    for entry in _iter_nt_strategy_entries():
        if entry.name.startswith("_"):  # archived/rejected folders start with _
            continue
        if entry.is_dir():
            name = entry.name
            cs_files = sorted(entry.glob("*.cs"))
        elif entry.is_file() and entry.suffix.lower() == ".cs" and not entry.name.startswith("@"): 
            name = entry.stem
            cs_files = [entry]
        else:
            continue
        if name in seen_classes:
            continue
        seen_classes.add(name)
        folder_strats.append({
            "class_name": name,
            "is_active":  name in _SCC_ACTIVE_CLASSES,
            "is_rejected": name in _SCC_REJECTED_CLASSES,
            "cs_files":   [f.name for f in cs_files],
        })

    hb = ops_runtime.read_heartbeat()
    rt_raw = ops_runtime.read_strategies_raw()
    rt_by_cls = {str(r.get("strategy_class") or "").lower(): r for r in rt_raw if r.get("strategy_class")}
    cat = jobqueue.read_strategies_catalog() or {}
    cat_by_cls = {str(s.get("class_name") or ""): s for s in cat.get("strategies") or [] if isinstance(s, dict)}
    ops_by_cls = {str(s.get("class_name") or ""): s for s in ops.list_strategies()}

    # Some deploy wrappers live in nested source paths under their research
    # engine folder. Surface them anyway so SCC matches the real strategy
    # inventory instead of only the top-level directory layout.
    for cls in sorted(_SCC_ACTIVE_CLASSES):
        if cls in seen_classes:
            continue
        sf = jobqueue._resolve_strategy_source_file(
            cls,
            (cat_by_cls.get(cls) or {}).get("source_file"),
        )
        if not sf:
            continue
        seen_classes.add(cls)
        folder_strats.append({
            "class_name": cls,
            "is_active": True,
            "is_rejected": cls in _SCC_REJECTED_CLASSES,
            "cs_files": [Path(sf).name],
        })

    active_strategies = []
    for fs in folder_strats:
        if not fs["is_active"]:
            continue
        cls = fs["class_name"]
        reg_s = ops_by_cls.get(cls)
        cat_s = cat_by_cls.get(cls) or {}
        source_file = jobqueue._resolve_strategy_source_file(cls, cat_s.get("source_file"))
        display_name = jobqueue._resolve_strategy_display_name(
            source_file,
            (reg_s or {}).get("display_name") or cat_s.get("display_name") or cls,
            cls,
        )
        rt = rt_by_cls.get(cls.lower())
        runtime_detected = bool(rt) and bool(hb.get("present")) and bool(hb.get("fresh"))
        runtime_enabled  = bool(rt and rt.get("enabled")) and runtime_detected
        acct_name = (rt or {}).get("account_name") or ""
        acct_mode = ops_runtime._classify_account_mode(acct_name, (rt or {}).get("account_mode"))
        active_strategies.append({
            **fs,
            "registry_id":      (reg_s or {}).get("strategy_id"),
            "registry_status":  (reg_s or {}).get("status", "unknown"),
            "display_name":     display_name,
            "locked_params":    (reg_s or {}).get("locked_params", {}),
            "runtime":          rt,
            "runtime_detected": runtime_detected,
            "runtime_enabled":  runtime_enabled,
            "account_name":     acct_name,
            "account_mode":     acct_mode,
            "instrument":       (rt or {}).get("instrument", ""),
            "timeframe":        (rt or {}).get("timeframe", ""),
        })

    rejected_running = [
        {"class_name": str(r.get("strategy_class")), "account_name": r.get("account_name")}
        for r in rt_raw
        if str(r.get("strategy_class") or "") in _SCC_REJECTED_CLASSES and r.get("enabled")
    ]

    return {
        "strategies":       active_strategies,
        "rejected_running": rejected_running,
        "rejected_classes": sorted(_SCC_REJECTED_CLASSES),
        "heartbeat":        hb,
        "nt_strat_dir":     str(_NT_STRATEGIES_DIR),
        "nt_strat_dir_ok":  _NT_STRATEGIES_DIR.is_dir(),
    }


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

    @staticmethod
    def _is_client_disconnect_error(err: BaseException) -> bool:
        # Browsers may cancel in-flight requests during navigation/reload.
        if isinstance(err, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return True
        if isinstance(err, OSError):
            winerror = getattr(err, "winerror", None)
            if winerror in {10053, 10054, 64}:
                return True
            if err.errno in {errno.EPIPE, errno.ECONNRESET}:
                return True
        return False

    def _json_safe(self, value: Any) -> Any:
        """Return JSON-standard-safe data.

        Python's json.dumps emits Infinity/NaN by default, but browser
        JSON.parse rejects those tokens. Backtests can legitimately produce
        infinite profit factor when there are no losses, so API responses must
        normalize non-finite floats before they reach the UI.
        """
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, dict):
            return {k: self._json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [self._json_safe(v) for v in value]
        return value

    def _json(self, status: int, body: Dict[str, Any]) -> None:
        data = json.dumps(
            self._json_safe(body),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            # CSP-ish hardening for a local UI
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

    def _err(self, status: int, msg: str) -> None:
        self._json(status, {"error": msg})

    def _bytes(self, status: int, data: bytes, content_type: str,
               download_name: Optional[str] = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            if download_name:
                quoted = urllib.parse.quote(download_name)
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=\"{download_name}\"; filename*=UTF-8''{quoted}",
                )
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

    def _read_body(self) -> Optional[Dict[str, Any]]:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            self._err(HTTPStatus.BAD_REQUEST, "invalid Content-Length")
            return None
        if n <= 0:
            return {}
        if n > 1 * 1024 * 1024:
            self._err(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body too large")
            return None
        raw = self.rfile.read(n)
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._err(HTTPStatus.BAD_REQUEST, f"invalid json: {e}")
            return None
        if not isinstance(body, dict):
            self._err(HTTPStatus.BAD_REQUEST, "json body must be an object")
            return None
        return body

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

    def _static_cache_control(self, target: Path) -> str:
        # Keep UI files fresh while still allowing the browser to reuse cached
        # responses via conditional requests and bfcache.
        if target.suffix.lower() == ".html":
            return "no-cache"
        return "public, max-age=120, must-revalidate"

    def _not_modified(self, target: Path) -> bool:
        raw_ims = self.headers.get("If-Modified-Since")
        if not raw_ims:
            return False
        try:
            ims = parsedate_to_datetime(raw_ims)
        except (TypeError, ValueError, IndexError, OverflowError):
            return False
        if ims.tzinfo is None:
            ims = ims.replace(tzinfo=timezone.utc)
        try:
            mtime = target.stat().st_mtime
        except OSError:
            return False
        return int(ims.timestamp()) >= int(mtime)

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
            if target.suffix == "":
                html_target = target.with_suffix(".html")
                try:
                    html_target.relative_to(STATIC_DIR.resolve())
                except ValueError:
                    self._err(HTTPStatus.FORBIDDEN, "path traversal blocked")
                    return
                if html_target.is_file():
                    target = html_target
                    ct = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
                    cache_control = self._static_cache_control(target)
                    last_modified = formatdate(target.stat().st_mtime, usegmt=True)
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"static not found: {rel}")
                    return
            else:
                self._err(HTTPStatus.NOT_FOUND, f"static not found: {rel}")
                return
        ct = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        cache_control = self._static_cache_control(target)
        last_modified = formatdate(target.stat().st_mtime, usegmt=True)
        try:
            if self._not_modified(target):
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("Cache-Control", cache_control)
                self.send_header("Last-Modified", last_modified)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                return
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Last-Modified", last_modified)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

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
                "jobs_dir": str(jobqueue.jobs_dir()),
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

        # Phase 22e — Strategy Profiles registry (best-of/locked configs).
        if path == "/api/profiles":
            self._json(HTTPStatus.OK, jobqueue.read_strategy_profiles())
            return

        # Phase 24 — Instrument coverage (which symbols have a strategy).
        if path == "/api/coverage":
            self._json(HTTPStatus.OK, jobqueue.read_instrument_coverage())
            return

        if path == "/api/performance/trades.csv":
            filename, data = performance.build_trades_csv(
                period=(qs.get("period") or ["month"])[0],
                from_date=(qs.get("from") or [None])[0],
                to_date=(qs.get("to") or [None])[0],
                account_name=(qs.get("account") or [None])[0],
            )
            self._bytes(HTTPStatus.OK, data, "text/csv; charset=utf-8", filename)
            return

        if path == "/api/performance":
            self._json(HTTPStatus.OK, performance.build_performance_response(
                period=(qs.get("period") or ["now"])[0],
                from_date=(qs.get("from") or [None])[0],
                to_date=(qs.get("to") or [None])[0],
                account_name=(qs.get("account") or [None])[0],
            ))
            return

        if path == "/api/report-favorites":
            validate = str((qs.get("validate") or ["0"])[0]).strip().lower() in {"1", "true", "yes"}
            self._json(HTTPStatus.OK, jobqueue.read_report_favorites(validate=validate))
            return

        if path == "/api/reports":
            try:
                limit = int((qs.get("limit") or ["100"])[0])
            except ValueError:
                limit = 100
            try:
                offset = int((qs.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            sort_col = str((qs.get("sort") or ["mtime"])[0] or "mtime")
            sort_dir = str((qs.get("dir") or ["desc"])[0] or "desc")
            status_filter = str((qs.get("filter") or ["all"])[0] or "all")
            limit = max(1, min(10000, limit))
            offset = max(0, offset)
            self._json(HTTPStatus.OK, jobqueue.list_reports(
                limit=limit,
                offset=offset,
                sort_col=sort_col,
                sort_dir=sort_dir,
                status_filter=status_filter,
            ))
            return

        if path == "/api/jobs":
            try:
                limit = int((qs.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            try:
                offset = int((qs.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            limit = max(1, min(10000, limit))
            offset = max(0, offset)
            jobs = jobqueue.list_jobs(limit=limit, offset=offset)
            counts = jobqueue.listable_queue_counts()
            self._json(HTTPStatus.OK, {
                "counts": counts,
                "offset": offset,
                "limit": limit,
                "total": sum(int(v or 0) for v in counts.values()),
                "jobs": jobs,
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
            try:
                offset = int((qs.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            limit = max(1, min(10000, limit))
            offset = max(0, offset)
            self._json(HTTPStatus.OK, {
                "offset": offset,
                "limit": limit,
                "total": jobqueue.count_batches(),
                "batches": jobqueue.list_batches(limit=limit, offset=offset),
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

        # /api/scc/* routes (Strategy Control Center v2)
        if path == "/api/scc/strategies":
            try:
                self._json(HTTPStatus.OK, _build_scc_strategies())
            except Exception as e:
                self._json(HTTPStatus.OK, {
                    "strategies": [], "rejected_running": [],
                    "rejected_classes": [], "heartbeat": {},
                    "error": str(e),
                })
            return

        # /api/ops/* routes (Strategy Control Center, read-only here)
        if path.startswith("/api/ops"):
            handled = self._ops_get(path, qs)
            if handled:
                return

        self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")

    # ------------- /api/ops/* GET dispatcher --------------------------------

    def _ops_get(self, path: str, qs: Dict[str, Any]) -> bool:
        parts = [p for p in path.split("/") if p]
        # /api/ops/...
        if len(parts) < 3:
            return False
        sub = parts[2]

        if path == "/api/ops/strategies":
            self._json(HTTPStatus.OK, {"strategies": ops.list_strategies()})
            return True

        if path == "/api/ops/audit-log":
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            sid = (qs.get("strategy_id") or [None])[0]
            self._json(HTTPStatus.OK, {"entries": ops.read_audit_log(limit, sid)})
            return True

        if path == "/api/ops/live-lock-status":
            self._json(HTTPStatus.OK, ops.live_lock_status())
            return True

        # ---- Phase 17: NinjaTrader runtime read-only endpoints ----
        if path == "/api/ops/runtime/heartbeat":
            self._json(HTTPStatus.OK, ops_runtime.read_heartbeat())
            return True
        if path == "/api/ops/runtime/health":
            self._json(HTTPStatus.OK, ops_runtime.health())
            return True
        if path == "/api/ops/runtime/strategy-display":
            self._json(HTTPStatus.OK, ops_runtime.read_strategy_display_prefs())
            return True
        if path == "/api/ops/runtime/strategy-history":
            try:
                limit_events = int((qs.get("limit_events") or ["500"])[0])
            except ValueError:
                limit_events = 500
            try:
                limit_sessions = int((qs.get("limit_sessions") or ["200"])[0])
            except ValueError:
                limit_sessions = 200
            self._json(HTTPStatus.OK, ops_runtime.read_strategy_history(
                limit_events=limit_events,
                limit_sessions=limit_sessions,
                strategy_id=(qs.get("strategy_id") or [None])[0],
                runtime_instance_id=(qs.get("runtime_instance_id") or [None])[0],
                class_name=(qs.get("class_name") or [None])[0],
            ))
            return True
        if path == "/api/ops/runtime/history":
            try:
                limit = int((qs.get("limit") or ["100"])[0])
            except ValueError:
                limit = 100
            sessions = ops_runtime.get_strategy_sessions(limit=limit)
            self._json(HTTPStatus.OK, {"sessions": sessions})
            return True
        if path == "/api/ops/runtime/strategies":
            # Trading Online expects the bridge to be the source of truth.
            # Always use merge_all_runtime_strategies() which iterates the raw
            # bridge strategies.json — never adds fake registry-only entries.
            sel_acct = (qs.get("selected_account")    or [None])[0]
            sel_inst = (qs.get("selected_instrument") or [None])[0]
            sel_tf   = (qs.get("selected_timeframe")  or [None])[0]
            runtime_list = ops_runtime.merge_all_runtime_strategies(
                selected_account=sel_acct,
                selected_instrument=sel_inst,
                selected_timeframe=sel_tf,
            )
            raw_list = ops_runtime.read_strategies_raw()
            self._json(HTTPStatus.OK, {
                "strategies": runtime_list,
                "raw":        raw_list,
                "source":     "runtime_bridge",
                "warnings":   [] if runtime_list else [
                    "NinjaTrader bridge не видит активных strategy instances. "
                    "Проверьте, что стратегия включена в NinjaTrader и bridge пересобран."
                ],
            })
            return True
        if sub == "runtime" and len(parts) >= 4 and parts[3] == "strategies" and len(parts) == 5:
            sid = parts[4]
            self._json(HTTPStatus.OK, ops_runtime.merge_strategy_view(sid))
            return True
        if path == "/api/ops/runtime/positions":
            self._json(HTTPStatus.OK, ops_runtime.read_positions())
            return True
        if path == "/api/ops/runtime/accounts":
            self._json(HTTPStatus.OK, ops_runtime.read_accounts_with_source())
            return True
        if path == "/api/ops/runtime/executions":
            sid = (qs.get("strategy_id") or [None])[0]
            acct = (qs.get("account_name") or [None])[0]
            iid = (qs.get("runtime_instance_id") or [None])[0]
            cls = (qs.get("class_name") or [None])[0]
            inst = (qs.get("instrument") or [None])[0]
            try: limit = int((qs.get("limit") or ["500"])[0])
            except ValueError: limit = 500
            limit = max(1, min(limit, 100_000))
            executions, dedupe_meta = ops_runtime.read_executions_with_meta(
                sid, limit,
                account_name=acct,
                runtime_instance_id=iid,
                class_name=cls,
                instrument=inst,
            )
            self._json(HTTPStatus.OK, {
                "strategy_id": sid,
                "account_name": acct,
                "runtime_instance_id": iid,
                "class_name": cls,
                "instrument": inst,
                "dedupe": dedupe_meta,
                "raw_count": dedupe_meta.get("raw_count"),
                "deduped_count": dedupe_meta.get("deduped_count"),
                "duplicate_count": dedupe_meta.get("duplicate_count"),
                "executions":  executions,
            })
            return True
        if path == "/api/ops/runtime/orders":
            sid = (qs.get("strategy_id") or [None])[0]
            acct = (qs.get("account_name") or [None])[0]
            iid = (qs.get("runtime_instance_id") or [None])[0]
            cls = (qs.get("class_name") or [None])[0]
            inst = (qs.get("instrument") or [None])[0]
            try: limit = int((qs.get("limit") or ["500"])[0])
            except ValueError: limit = 500
            limit = max(1, min(limit, 100_000))
            orders, dedupe_meta = ops_runtime.read_orders_with_meta(
                sid, limit,
                account_name=acct,
                runtime_instance_id=iid,
                class_name=cls,
                instrument=inst,
            )
            self._json(HTTPStatus.OK, {
                "strategy_id": sid,
                "account_name": acct,
                "runtime_instance_id": iid,
                "class_name": cls,
                "instrument": inst,
                "dedupe": dedupe_meta,
                "raw_count": dedupe_meta.get("raw_count"),
                "deduped_count": dedupe_meta.get("deduped_count"),
                "duplicate_count": dedupe_meta.get("duplicate_count"),
                "orders":      orders,
            })
            return True
        if path == "/api/ops/runtime/errors":
            try: limit = int((qs.get("limit") or ["100"])[0])
            except ValueError: limit = 100
            self._json(HTTPStatus.OK, {"errors": ops_runtime.read_errors(limit)})
            return True
        if path == "/api/ops/runtime/commands":
            try: limit = int((qs.get("limit") or ["200"])[0])
            except ValueError: limit = 200
            self._json(HTTPStatus.OK, {"commands": ops_runtime.read_commands(limit)})
            return True
        if path == "/api/ops/runtime/command-results":
            try: limit = int((qs.get("limit") or ["200"])[0])
            except ValueError: limit = 200
            self._json(HTTPStatus.OK, {"results": ops_runtime.read_command_results(limit)})
            return True
        if path == "/api/ops/runtime/command-status":
            try: timeout = int((qs.get("timeout_sec") or ["30"])[0])
            except ValueError: timeout = 30
            cid = (qs.get("command_id") or [None])[0]
            since = (qs.get("since_ts") or [None])[0]
            if cid:
                self._json(HTTPStatus.OK,
                           ops_runtime.get_command_status(cid, timeout_sec=timeout))
            else:
                self._json(HTTPStatus.OK, {
                    "statuses": ops_runtime.get_command_statuses_since(
                        since_ts=since, timeout_sec=timeout),
                })
            return True
        if path == "/api/ops/runtime/instruments":
            # Returns per-root current/all instruments for the Trading Online selector.
            # Each root entry has front_month (most recent), and all contracts.
            instr_doc = jobqueue.read_instruments_catalog() or {}
            all_instr = instr_doc.get("instruments") or []
            root_map: dict = {}
            for ins in all_instr:
                if not isinstance(ins, dict):
                    continue
                name = str(ins.get("instrument") or ins.get("symbol") or ins.get("name") or "")
                root = str(ins.get("root") or name.split(" ", 1)[0])
                if not root:
                    continue
                root_map.setdefault(root, []).append(ins)
            result = []
            for root, contracts in sorted(root_map.items()):
                def _dl(c: dict) -> str:
                    return str(c.get("data_last") or "")
                contracts_sorted = sorted(contracts, key=_dl, reverse=True)
                result.append({
                    "root": root,
                    "front_month": contracts_sorted[0] if contracts_sorted else None,
                    "contracts": contracts_sorted,
                })
            self._json(HTTPStatus.OK, {"roots": result})
            return True

        # /api/ops/strategies/{id}[/sub]
        if sub == "strategies" and len(parts) >= 4:
            sid = parts[3]
            s = ops.get_strategy(sid)
            if not s:
                self._err(HTTPStatus.NOT_FOUND, f"strategy not found: {sid}")
                return True
            if len(parts) == 4:
                states = ops.load_states()
                self._json(HTTPStatus.OK, {
                    "strategy": s,
                    "state":    states.get(sid),
                    "metrics":  ops.compute_metrics_safe(s),
                    "runtime":  ops_runtime.merge_strategy_view(sid),
                })
                return True
            tail = parts[4]
            if tail == "metrics":
                self._json(HTTPStatus.OK, ops.compute_metrics_safe(s))
                return True
            if tail == "trades":
                self._json(HTTPStatus.OK, ops.get_trades(sid))
                return True
            if tail == "journal":
                self._json(HTTPStatus.OK, ops.get_journal(sid))
                return True
            if tail == "risk":
                m = ops.compute_metrics_safe(s)
                self._json(HTTPStatus.OK, {
                    "strategy_id": sid,
                    "risk_state": m.get("risk_state"),
                    "risk_reasons": m.get("risk_reasons"),
                    "limits": s.get("risk_profile"),
                    "today_adj_pnl": m.get("today_adj_pnl"),
                    "weekly_adj_pnl": m.get("weekly_adj_pnl"),
                    "current_drawdown": m.get("current_drawdown"),
                    "consec_losing_days": m.get("consec_losing_days"),
                })
                return True
            if tail == "notes":
                self._json(HTTPStatus.OK, ops.get_notes(sid))
                return True

        return False

    # ------------- /api/ops/* POST dispatcher -------------------------------

    def _ops_post(self, path: str, body: Dict[str, Any]) -> None:
        parts = [p for p in path.split("/") if p]
        # /api/ops/live/unlock-request
        if path == "/api/ops/live/unlock-request":
            out = ops.request_live_unlock(reason=str(body.get("reason") or ""))
            self._json(HTTPStatus.FORBIDDEN, out)
            return
        # /api/ops/runtime/command  (paper-only command queue)
        if path == "/api/ops/runtime/command":
            try:
                out = ops_runtime.submit_command(
                    command=str(body.get("command") or ""),
                    strategy_id=str(body.get("strategy_id") or ""),
                    account_name=str(body.get("account_name") or ""),
                    quantity=body.get("quantity") or 1,
                    reason=str(body.get("reason") or ""),
                    operator=str(body.get("operator") or "ui"),
                    class_name=str(body.get("class_name") or ""),
                    instrument=str(body.get("instrument") or ""),
                    contract_month=str(body.get("contract_month") or ""),
                    timeframe=str(body.get("timeframe") or ""),
                    runtime_instance_id=str(body.get("runtime_instance_id") or ""),
                    params=body.get("params") if isinstance(body.get("params"), dict) else None,
                )
                self._json(HTTPStatus.OK, out); return
            except ops.OpsError as e:
                self._err(e.status, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"command error: {e}"); return
        if path == "/api/ops/runtime/strategy-display":
            try:
                out = ops_runtime.set_strategy_display_hidden(
                    class_name=str(body.get("class_name") or ""),
                    hidden=bool(body.get("hidden")),
                )
                self._json(HTTPStatus.OK, out); return
            except ops.OpsError as e:
                self._err(e.status, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"display prefs error: {e}"); return
        # /api/ops/profiles/{profile_id}/{update|delete}
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "ops" and parts[2] == "profiles":
            profile_id = urllib.parse.unquote(parts[3])
            action = parts[4]
            try:
                if action == "update":
                    updates = body.get("updates") if isinstance(body.get("updates"), dict) else {}
                    self._json(HTTPStatus.OK, jobqueue.update_strategy_profile(
                        profile_id,
                        updates,
                        action=str(body.get("action") or "update"),
                    )); return
                if action == "delete":
                    self._json(HTTPStatus.OK, jobqueue.delete_strategy_profile(profile_id)); return
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"profile update error: {e}"); return
        # /api/ops/strategies/{id}/{action}[/{sub}]
        if len(parts) >= 5 and parts[0] == "api" and parts[1] == "ops" and parts[2] == "strategies":
            sid = parts[3]
            action = "/".join(parts[4:])
            reason = str(body.get("reason") or "")
            try:
                if action == "paper/arm":
                    self._json(HTTPStatus.OK, ops.arm(sid, reason)); return
                if action == "paper/start-intent":
                    self._json(HTTPStatus.OK, ops.start_intent(sid, reason)); return
                if action == "paper/stop-intent":
                    self._json(HTTPStatus.OK, ops.stop_intent(sid, reason)); return
                if action == "paper/confirm-manual":
                    a = str(body.get("action") or "")
                    self._json(HTTPStatus.OK, ops.confirm_manual(sid, a, reason)); return
                if action == "paper/pause":
                    self._json(HTTPStatus.OK, ops.pause(sid, reason)); return
                if action == "paper/resume":
                    self._json(HTTPStatus.OK, ops.resume(sid, reason)); return
                if action == "paper/stop-today":
                    self._json(HTTPStatus.OK, ops.stop_today(sid, reason)); return
                if action == "paper/mark-passed":
                    self._json(HTTPStatus.OK, ops.mark_paper_passed(sid, reason)); return
                if action == "paper/evaluate-review":
                    self._json(HTTPStatus.OK, ops.evaluate_review_due(sid)); return
                if action == "journal/day":
                    self._json(HTTPStatus.OK, ops.append_journal_day(sid, body.get("row") or {})); return
                if action == "journal/autofill":
                    on_date = body.get("date_pt")
                    dry = bool(body.get("dry_run"))
                    self._json(HTTPStatus.OK,
                               ops_runtime.journal_autofill(sid, on_date, dry)); return
                if action == "runtime/confirm-started":
                    self._json(HTTPStatus.OK,
                               ops_runtime.confirm_runtime(sid, "started", reason)); return
                if action == "runtime/confirm-stopped":
                    self._json(HTTPStatus.OK,
                               ops_runtime.confirm_runtime(sid, "stopped", reason)); return
                if action == "notes":
                    self._json(HTTPStatus.OK, ops.append_note(sid, str(body.get("text") or ""))); return
            except ops.OpsError as e:
                self._err(e.status, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"ops error: {e}"); return
        self._err(HTTPStatus.NOT_FOUND, f"no ops route: {path}")

    def do_DELETE(self) -> None:  # noqa: N802
        """DELETE /api/jobs/<id>, /api/batches/<id>, or report favorite refs."""
        url = urllib.parse.urlparse(self.path)
        path = url.path
        parts = [p for p in path.split("/") if p]

        is_del_job   = (len(parts) == 3 and parts[0] == "api"
                        and parts[1] == "jobs")
        is_del_batch = (len(parts) == 3 and parts[0] == "api"
                        and parts[1] == "batches")
        is_del_favorite = (len(parts) == 4 and parts[0] == "api"
                           and parts[1] == "report-favorites")

        if not (is_del_job or is_del_batch or is_del_favorite):
            self._err(HTTPStatus.NOT_FOUND, f"no DELETE route: {path}")
            return

        if not self._check_local_origin():
            return

        if is_del_favorite:
            try:
                out = jobqueue.unfavorite_report(parts[2], parts[3])
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            self._json(HTTPStatus.OK, out)
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
                elif reason in ("favorite", "favorite_parent_batch"):
                    self._err(HTTPStatus.CONFLICT,
                              "Отчёт находится в избранном. Сначала снимите звезду.")
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
            elif reason in ("favorite", "has_favorite_jobs"):
                self._err(HTTPStatus.CONFLICT,
                          "Отчёт находится в избранном. Сначала снимите звезду.")
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
        is_server_restart = (path == "/api/server/restart")
        is_ops = path.startswith("/api/ops/")
        is_report_favorites = path == "/api/report-favorites" or path.startswith("/api/report-favorites/")

        if not (path in ("/api/jobs", "/api/batches")
                or is_cancel_job or is_cancel_batch
                or is_catalog_refresh or is_margins_refresh
                or is_server_restart
                or is_ops or is_report_favorites):
            self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
            return

        if not self._check_local_post():
            return  # _check_local_post already wrote an error

        if is_ops:
            body = self._read_body()
            if body is None:
                return
            self._ops_post(path, body)
            return

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

        if is_server_restart:
            self._json(HTTPStatus.OK, {"status": "restarting"})
            t = threading.Timer(0.6, _do_restart_server)
            t.daemon = True
            t.start()
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

        if is_report_favorites:
            try:
                if path == "/api/report-favorites":
                    out = jobqueue.favorite_report(
                        str(body.get("kind") or ""),
                        str(body.get("id") or body.get("report_id") or ""),
                        description=(str(body["description"]) if "description" in body else None),
                    )
                    self._json(HTTPStatus.OK, out)
                    return
                fav_parts = [p for p in path.split("/") if p]
                if len(fav_parts) == 5 and fav_parts[0] == "api" and fav_parts[1] == "report-favorites" and fav_parts[4] == "repeat":
                    out = jobqueue.repeat_report_favorite(fav_parts[2], fav_parts[3])
                    self._json(HTTPStatus.CREATED, out)
                    return
                if len(fav_parts) == 5 and fav_parts[0] == "api" and fav_parts[1] == "report-favorites" and fav_parts[4] == "description":
                    out = jobqueue.update_report_favorite(
                        fav_parts[2],
                        fav_parts[3],
                        {"description": body.get("description")},
                    )
                    self._json(HTTPStatus.OK, out)
                    return
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
                return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"favorite error: {e}")
                return
            self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
            return

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
                    order_fill_resolution=str(body.get("order_fill_resolution") or "High"),
                    slippage_ticks=int(body.get("slippage_ticks") or 1),
                    commission=float(body.get("commission") or 0.0),
                    commission_template=str(body.get("commission_template") or "None"),
                    session_template=str(body.get("session_template") or "CME US Index Futures RTH"),
                    timezone=str(body.get("timezone") or "UTC"),
                    role=str(body.get("role") or "research"),
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
                order_fill_resolution=str(body.get("order_fill_resolution") or "High"),
                slippage_ticks=int(body.get("slippage_ticks") or 1),
                commission=float(body.get("commission") or 0.0),
                commission_template=str(body.get("commission_template") or "None"),
                session_template=str(body.get("session_template") or "CME US Index Futures RTH"),
                timezone=str(body.get("timezone") or "UTC"),
                role=str(body.get("role") or "research"),
                job_id=None,  # never trust client-supplied ids
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
    print(f"[nta-backend] jobs_dir: {jobqueue.jobs_dir()}")
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
