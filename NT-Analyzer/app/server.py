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
import traceback
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
    from app import governance  # type: ignore[no-redef]
    from app import marginrefresh  # type: ignore[no-redef]
    from app import ops  # type: ignore[no-redef]
    from app import performance  # type: ignore[no-redef]
    from app import account_ledger  # type: ignore[no-redef]
    from app import portfolio_registry  # type: ignore[no-redef]
    from app import runtime as ops_runtime  # type: ignore[no-redef]
    from app.ai_lab import read_model as ai_read_model  # type: ignore[no-redef]
    from app.ai_lab import registry as ai_registry  # type: ignore[no-redef]
    from app.ai_lab import orchestrator as ai_orchestrator  # type: ignore[no-redef]
    from app.ai_lab import analysis_pack as ai_analysis_pack  # type: ignore[no-redef]
    from app.ai_lab import backtest as ai_backtest  # type: ignore[no-redef]
    from app.ai_lab import bootstrap as ai_bootstrap  # type: ignore[no-redef]
    from app.ai_lab import lm_studio as ai_lm_studio  # type: ignore[no-redef]
    from app.ai_lab import runner as ai_runner  # type: ignore[no-redef]
    from app.ai_lab import activity as ai_activity  # type: ignore[no-redef]
    from app.ai_lab import compile_errors as ai_compile_errors  # type: ignore[no-redef]
    from app.ai_lab import operator_notes as ai_operator_notes  # type: ignore[no-redef]
    from app.ai_lab import errors as ai_errors  # type: ignore[no-redef]
    from app.ai_lab import lessons as ai_lessons  # type: ignore[no-redef]
    from app.ai_lab import stale_sweep as ai_stale_sweep  # type: ignore[no-redef]
else:
    from . import jobqueue
    from . import governance
    from . import marginrefresh
    from . import ops
    from . import performance
    from . import account_ledger
    from . import portfolio_registry
    from . import runtime as ops_runtime
    from .ai_lab import read_model as ai_read_model
    from .ai_lab import registry as ai_registry
    from .ai_lab import orchestrator as ai_orchestrator
    from .ai_lab import analysis_pack as ai_analysis_pack
    from .ai_lab import backtest as ai_backtest
    from .ai_lab import bootstrap as ai_bootstrap
    from .ai_lab import lm_studio as ai_lm_studio
    from .ai_lab import runner as ai_runner
    from .ai_lab import activity as ai_activity
    from .ai_lab import compile_errors as ai_compile_errors
    from .ai_lab import operator_notes as ai_operator_notes
    from .ai_lab import errors as ai_errors
    from .ai_lab import lessons as ai_lessons
    from .ai_lab import stale_sweep as ai_stale_sweep


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Uniform Content-Security-Policy for all served static UI (new Aurora + legacy).
# Both UIs externalize JS and use no inline <script>/onclick, so `script-src 'self'`
# blocks injected inline script while inline style attributes remain allowed.
STATIC_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
    "object-src 'none'; frame-ancestors 'self'"
)


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

# Strategy Control Center curated class lists.
#
# These used to be hard-coded sets that had to be edited in Python every time a
# strategy was promoted/rejected. They are now seeded from a JSON config so new
# strategies can be wired into SCC by editing data/ops/scc_classes.json (or by
# whatever tooling writes it) — no code change / server rebuild required.
#
# The built-in defaults below remain the fallback when the config file is
# missing or malformed, so behaviour is unchanged on a fresh checkout.
_SCC_CLASSES_CONFIG_PATH = _PROJECT_ROOT / "data" / "ops" / "scc_classes.json"

_SCC_ACTIVE_CLASSES_DEFAULT = {
    "PullbackMNQ5mV2",
    "VWAPPullbackMGC5mV1",
    "B1ShortOnlyMGC5mV2",
    "B1Stop24MGC5mC003",
    "B1Stop20MGC5mC004",
    "NTAMicroVwapRiskPilot",
    "NTAMicroMnqScalpPilot",
    "NTAMnqPostActiveScalpC017",
    "NTAMnqDailyOpenScalpC018",
    "NTAMnqMicroOrbOpenScalp",
    "NTAnalyzerEveryNBarLong",
    "StrategiyaUrovney",
}
_SCC_REJECTED_CLASSES_DEFAULT = {
    "NTAMicroOrbPilot",
    "NTAMicroVwapGapMirrorPilot",
    "NTAMicroVwapMeanRevertPilot",
    "NTAMnqLiquiditySweepReversalC015",
    "NTAMnqOpenDriveShortScalpC016",
    "NTAMnqLateVwapLongScalpC017",
}


def _load_scc_classes() -> "tuple[set, set]":
    """Return (active, rejected) SCC class sets.

    Starts from the built-in defaults and merges in data/ops/scc_classes.json
    when present. Config schema (all keys optional):
        {
          "active":   ["ClassA", ...],   # added to (or replacing) defaults
          "rejected": ["ClassB", ...],
          "replace_defaults": false       # when true, ignore built-in defaults
        }
    A class listed as rejected always wins over active. Read fresh on every
    call so edits take effect without restarting the backend.
    """
    active = set(_SCC_ACTIVE_CLASSES_DEFAULT)
    rejected = set(_SCC_REJECTED_CLASSES_DEFAULT)
    try:
        with open(_SCC_CLASSES_CONFIG_PATH, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        doc = None
    if isinstance(doc, dict):
        if doc.get("replace_defaults"):
            active = set()
            rejected = set()
        a = doc.get("active")
        r = doc.get("rejected")
        if isinstance(a, list):
            active.update(str(x) for x in a if isinstance(x, str) and x)
        if isinstance(r, list):
            rejected.update(str(x) for x in r if isinstance(x, str) and x)
    active -= rejected  # rejected always wins
    return active, rejected


# Module-level snapshots (defaults merged with config present at import time).
# Kept for backward compatibility and external importers; request handlers call
# _load_scc_classes() directly so they pick up live config edits.
_SCC_ACTIVE_CLASSES, _SCC_REJECTED_CLASSES = _load_scc_classes()



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
    active_classes, rejected_classes = _load_scc_classes()
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
            "is_active":  name in active_classes,
            "is_rejected": name in rejected_classes,
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
    for cls in sorted(active_classes):
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
            "is_rejected": cls in rejected_classes,
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
        if str(r.get("strategy_class") or "") in rejected_classes and r.get("enabled")
    ]

    return {
        "strategies":       active_strategies,
        "rejected_running": rejected_running,
        "rejected_classes": sorted(rejected_classes),
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
        # Directory requests (e.g. "legacy/") serve the folder's index.html.
        if rel.endswith("/"):
            rel += "index.html"
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
                self.send_header("Content-Security-Policy", STATIC_CSP)
                self.end_headers()
                return
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Last-Modified", last_modified)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", STATIC_CSP)
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

    # ------------- routing -------------------------------------------------

    def send_response(self, code, message=None):  # type: ignore[override]
        # Track whether the response line has been emitted so the top-level
        # error guard knows if it can still send a clean 500 JSON body.
        self._response_started = True
        super().send_response(code, message)

    def _handle_unexpected(self, method: str) -> None:
        """Last-resort handler: turn any uncaught exception into a 500 JSON
        response instead of letting it abort the socket with a bare traceback.
        """
        tb = traceback.format_exc()
        try:
            sys.stderr.write(f"[NT-Analyzer] unhandled {method} error:\n{tb}")
        except Exception:
            pass
        if getattr(self, "_response_started", False):
            # Headers/body already (partially) sent — we can no longer emit a
            # well-formed error. Nothing safe left to do; connection closes.
            return
        try:
            self._err(HTTPStatus.INTERNAL_SERVER_ERROR, "internal server error")
        except OSError:
            pass

    def do_GET(self) -> None:  # noqa: N802
        self._response_started = False
        try:
            self._route_get()
        except Exception:
            self._handle_unexpected("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._response_started = False
        try:
            self._route_post()
        except Exception:
            self._handle_unexpected("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._response_started = False
        try:
            self._route_delete()
        except Exception:
            self._handle_unexpected("DELETE")

    def _route_get(self) -> None:
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
            suffix = ("?" + url.query) if url.query else ""
            # Back-compat redirects: old page URLs → new Aurora pages (keep deep links).
            _aliases = {
                "/ai-strategy.html": "/ui/ai-lab.html", "/ai-strategy": "/ui/ai-lab.html",
                "/ops.html": "/ui/trading.html", "/ops": "/ui/trading.html",
                "/docs.html": "/ui/documents.html", "/docs": "/ui/documents.html",
            }
            if rel in _aliases:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", _aliases[rel] + suffix)
                self.end_headers()
                return
            # Canonicalise the old staging path /ui/aurora/* → /ui/*.
            if rel == "/aurora" or rel.startswith("/aurora/"):
                new_rel = rel[len("/aurora"):] or "/"
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/ui" + new_rel + suffix)
                self.end_headers()
                return
            # Legacy (classic) UI lives at app/static/<file>; serve it under /ui/legacy/.
            if rel == "/legacy" or rel.startswith("/legacy/"):
                self._serve_static(rel[len("/legacy"):] or "/")
                return
            # New Aurora UI is primary: its pages + assets are served from app/static/aurora/.
            _new_pages = {
                "/", "/index.html", "/backtesting.html", "/trading.html",
                "/performance.html", "/strategies.html", "/ai-lab.html", "/documents.html",
            }
            if rel in _new_pages or rel.startswith("/assets/"):
                self._serve_static("aurora/index.html" if rel == "/" else "aurora" + rel)
                return
            # Fallback: any other path resolves against the static root (legacy-named files).
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

        if path == "/api/portfolio/cells":
            self._json(HTTPStatus.OK, portfolio_registry.read_registry())
            return

        if path.startswith("/api/governance"):
            if self._governance_get(path, qs):
                return

        if path == "/api/catalog":
            self._json(HTTPStatus.OK, jobqueue.build_catalog_response())
            return

        # Phase 22e — Strategy Profiles registry (best-of/locked configs).
        if path == "/api/profiles":
            self._json(HTTPStatus.OK, jobqueue.read_strategy_profiles())
            return

        # Do-not-recreate registry: ideas that failed all trials.
        if path == "/api/profiles/archive":
            self._json(HTTPStatus.OK, jobqueue.read_archived_strategies())
            return

        if path == "/api/strategy-families":
            self._json(HTTPStatus.OK, jobqueue.read_strategy_families())
            return

        if path == "/api/research-modes":
            self._json(HTTPStatus.OK, jobqueue.read_research_modes())
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

        if path == "/api/performance/trades":
            try:
                offset = int((qs.get("offset") or ["0"])[0])
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                offset, limit = 0, 200
            self._json(HTTPStatus.OK, performance.build_trades_response(
                period=(qs.get("period") or ["month"])[0],
                from_date=(qs.get("from") or [None])[0],
                to_date=(qs.get("to") or [None])[0],
                account_name=(qs.get("account") or [None])[0],
                offset=offset, limit=limit,
            ))
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

        # /api/ai-lab/* read model
        if path.startswith("/api/ai-lab"):
            if self._ai_lab_get(path, qs):
                return

        self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")

    def _governance_get(self, path: str, qs: Dict[str, Any]) -> bool:
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2 or parts[0] != "api" or parts[1] != "governance":
            return False

        if path == "/api/governance/runtime-defaults":
            self._json(HTTPStatus.OK, governance.runtime_defaults())
            return True

        if path == "/api/governance/summary":
            self._json(HTTPStatus.OK, {
                "documents": governance.list_documents(),
                "runtime_defaults": governance.runtime_defaults(),
                "consistency": governance.consistency_report(),
                "history": governance.read_change_log(80),
            })
            return True

        if path == "/api/governance/documents":
            self._json(HTTPStatus.OK, {"documents": governance.list_documents()})
            return True

        if path == "/api/governance/history":
            try:
                limit = int((qs.get("limit") or ["80"])[0])
            except ValueError:
                limit = 80
            entity_id = (qs.get("entity_id") or [None])[0]
            document_id = (qs.get("document_id") or [None])[0]
            self._json(HTTPStatus.OK, {
                "entries": governance.read_change_log(limit, entity_id=entity_id, document_id=document_id),
            })
            return True

        if path == "/api/governance/consistency":
            self._json(HTTPStatus.OK, governance.consistency_report())
            return True

        if len(parts) == 4 and parts[2] == "documents":
            doc_id = urllib.parse.unquote(parts[3])
            doc = governance.read_document(doc_id)
            if not doc:
                self._err(HTTPStatus.NOT_FOUND, f"governance document not found: {doc_id}")
                return True
            self._json(HTTPStatus.OK, doc)
            return True

        return False

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
        if path == "/api/ops/strategy-start-dates":
            p = _PROJECT_ROOT / "data" / "ops" / "strategy_start_dates.json"
            try:
                data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {
                    "schema_version": 1,
                    "strategies": {},
                }
            except Exception:
                data = {"schema_version": 1, "strategies": {}}
            self._json(HTTPStatus.OK, data)
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
            payload = ops_runtime.read_accounts_with_source()
            try:
                account_ledger.record_accounts(payload)
            except Exception:
                payload.setdefault("warnings", []).append("account ledger snapshot could not be recorded")
            self._json(HTTPStatus.OK, payload)
            return True
        if path == "/api/ops/runtime/account-history":
            account = (qs.get("account") or [""])[0]
            try:
                limit = int((qs.get("limit") or ["500"])[0])
            except ValueError:
                limit = 500
            self._json(HTTPStatus.OK, account_ledger.account_history(account, limit))
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
            tail = parts[4] if len(parts) >= 5 else None
            if tail == "notes":
                self._json(HTTPStatus.OK, ops.get_notes(sid))
                return True
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

        return False

    # ------------- /api/ai-lab/* GET dispatcher -----------------------------

    def _ai_lab_get(self, path: str, qs: Dict[str, Any]) -> bool:
        parts = [p for p in path.split("/") if p]
        # parts[0]="api", parts[1]="ai-lab", parts[2..]=...
        if len(parts) < 3:
            self._err(HTTPStatus.NOT_FOUND, f"no ai-lab route: {path}")
            return True
        sub = parts[2]

        if path == "/api/ai-lab/summary":
            try:
                self._json(HTTPStatus.OK, ai_read_model.summary())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"summary error: {e}")
            return True

        if path == "/api/ai-lab/lifecycle":
            try:
                self._json(HTTPStatus.OK, ai_read_model.lifecycle_cards())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"lifecycle error: {e}")
            return True

        if path == "/api/ai-lab/cell-history":
            cell = (qs.get("cell") or [""])[0]
            try:
                self._json(HTTPStatus.OK, ai_read_model.cell_history(cell))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"cell-history error: {e}")
            return True

        if path == "/api/ai-lab/matrix":
            roots_q = (qs.get("roots") or [None])[0]
            roots = [r.strip().upper() for r in roots_q.split(",")] if roots_q else None
            try:
                self._json(HTTPStatus.OK, ai_read_model.matrix(roots=roots))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"matrix error: {e}")
            return True

        if path == "/api/ai-lab/performance":
            try:
                self._json(HTTPStatus.OK, ai_read_model.performance_board())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"performance error: {e}")
            return True

        if path == "/api/ai-lab/model-performance":
            try:
                days = int((qs.get("days") or ["30"])[0])
                self._json(HTTPStatus.OK, ai_read_model.model_performance(days=days))
            except ValueError:
                self._err(HTTPStatus.BAD_REQUEST, "days must be an integer")
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"model performance error: {e}")
            return True

        if path == "/api/ai-lab/portfolio":
            try:
                self._json(HTTPStatus.OK, ai_read_model.portfolio_board())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"portfolio error: {e}")
            return True

        if path == "/api/ai-lab/calendar":
            try:
                self._json(HTTPStatus.OK, ai_read_model.calendar())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"calendar error: {e}")
            return True

        if path == "/api/ai-lab/lm-studio/health":
            try:
                self._json(HTTPStatus.OK, ai_lm_studio.lm_status(allow_probe=False))
            except Exception as e:
                self._json(HTTPStatus.OK, {
                    "available": False,
                    "ready": False,
                    "run_allowed": False,
                    "status": "server_unavailable",
                    "message_ru": "LM Studio недоступна — запустите сервер (порт 1234).",
                    "error": str(e),
                })
            return True

        if path == "/api/ai-lab/lm-studio/readiness":
            try:
                url = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(url.query or "")
                force = qs.get("force", ["0"])[0] in ("1", "true", "yes")
                self._json(
                    HTTPStatus.OK,
                    ai_lm_studio.lm_status(allow_probe=True, force=force),
                )
            except Exception as e:
                self._json(HTTPStatus.OK, {
                    "available": False,
                    "ready": False,
                    "run_allowed": False,
                    "status": "server_unavailable",
                    "message_ru": "Не удалось проверить AI-модели.",
                    "error": str(e),
                })
            return True

        if path == "/api/ai-lab/bootstrap/status":
            try:
                url = urllib.parse.urlparse(self.path)
                qs = urllib.parse.parse_qs(url.query or "")
                probe = qs.get("probe", ["0"])[0] in ("1", "true", "yes")
                self._json(HTTPStatus.OK, ai_bootstrap.status(probe=probe))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"bootstrap status failed: {e}")
            return True

        if path == "/api/ai-lab/current":
            self._json(HTTPStatus.OK, {"current": ai_runner.current()})
            return True

        if path == "/api/ai-lab/run/status":
            try:
                status = ai_runner.run_status()
                self._json(HTTPStatus.OK, {"ok": True, "run": status})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"run status failed: {e}")
            return True

        if path == "/api/ai-lab/errors/summary":
            try:
                payload = {
                    "patterns": ai_errors.top_repeated_patterns(threshold=1)[:30],
                    "recent_errors": ai_errors.recent_errors(limit=50),
                    "lessons_recent": ai_lessons.all_lessons(limit=20),
                    "global_operator_notes": ai_operator_notes.list_global_notes(limit=20),
                    "lessons_count": len(ai_lessons.all_lessons(limit=10_000)),
                }
                self._json(HTTPStatus.OK, payload)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"errors summary failed: {e}")
            return True

        if path == "/api/ai-lab/compile-source-status":
            try:
                self._json(HTTPStatus.OK, ai_compile_errors.source_status())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"source_status failed: {e}")
            return True

        # /api/ai-lab/experiments
        if path == "/api/ai-lab/experiments":
            root = (qs.get("root") or [None])[0]
            status = (qs.get("status") or [None])[0]
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            items = ai_registry.list_experiments(target_root=root, status=status, limit=limit)
            self._json(HTTPStatus.OK, {"experiments": items, "total": len(items)})
            return True

        # /api/ai-lab/experiments/{id}[/history]
        if sub == "experiments" and len(parts) >= 4:
            exp_id = parts[3]
            if len(parts) == 4:
                exp = ai_registry.read_experiment(exp_id)
                if not exp:
                    self._err(HTTPStatus.NOT_FOUND, f"experiment not found: {exp_id}")
                    return True
                self._json(HTTPStatus.OK, exp)
                return True
            if len(parts) == 5 and parts[4] == "history":
                self._json(HTTPStatus.OK, {"history": ai_registry.history_for(exp_id)})
                return True
            if len(parts) == 5 and parts[4] == "activity":
                try:
                    since = int((qs.get("since") or ["0"])[0])
                except ValueError:
                    since = 0
                try:
                    limit = int((qs.get("limit") or ["500"])[0])
                except ValueError:
                    limit = 500
                exp = ai_registry.read_experiment(exp_id) or {}
                data = ai_activity.tail(exp_id, since_line=since, limit=limit)
                data["status"] = exp.get("status")
                data["ai_cell_id"] = exp.get("ai_cell_id")
                data["class_name"] = exp.get("class_name")
                data["sandbox_path"] = (exp.get("strategy_source") or {}).get("sandbox_path")
                data["terminal"] = ai_registry.is_terminal(exp.get("status", "draft"))
                self._json(HTTPStatus.OK, data)
                return True
            if len(parts) == 5 and parts[4] == "notes":
                try:
                    self._json(HTTPStatus.OK, {"notes": ai_operator_notes.list_all(exp_id)})
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"notes list failed: {e}")
                return True
            if len(parts) == 5 and parts[4] == "backtest":
                try:
                    self._json(HTTPStatus.OK, ai_read_model.backtest_payload(exp_id))
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"backtest payload failed: {e}")
                return True

        # /api/ai-lab/jobs/{job_id}/analysis-pack
        if sub == "jobs" and len(parts) == 5 and parts[4] == "analysis-pack":
            job_id = parts[3]
            job_dir = ai_backtest.find_job_dir(job_id)
            if not job_dir:
                self._err(HTTPStatus.NOT_FOUND, f"job not found: {job_id}")
                return True
            try:
                capital = float((qs.get("capital") or ["5000"])[0])
            except ValueError:
                capital = 5000.0
            try:
                pack = ai_analysis_pack.build(job_dir, capital=capital)
                self._json(HTTPStatus.OK, pack)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"analysis-pack failed: {e}")
            return True

        self._err(HTTPStatus.NOT_FOUND, f"no ai-lab route: {path}")
        return True

    # ------------- /api/ai-lab/* POST dispatcher ----------------------------

    def _ai_lab_post(self, path: str, body: Dict[str, Any]) -> None:
        if path == "/api/ai-lab/bootstrap/start":
            try:
                out = ai_bootstrap.start(
                    timeout_sec=max(30, min(900, int(body.get("timeout_sec", 300)))),
                    start_ninjatrader=bool(body.get("start_ninjatrader", True)),
                    start_lm_studio=bool(body.get("start_lm_studio", True)),
                    start_lm_server=bool(body.get("start_lm_server", True)),
                    load_models=bool(body.get("load_models", False)),
                    wait_readiness=bool(body.get("wait_readiness", False)),
                )
                self._json(HTTPStatus.OK, out)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"bootstrap start failed: {e}")
            return

        if path == "/api/ai-lab/bootstrap/unload":
            try:
                out = ai_bootstrap.unload_models(
                    stop_server=bool(body.get("stop_server", True))
                )
                self._json(HTTPStatus.OK, out)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"bootstrap unload failed: {e}")
            return

        if path == "/api/ai-lab/run":
            try:
                capital_value = body.get("capital")
                if capital_value in (None, ""):
                    capital_value = body.get("user_capital")
                # New schema (preferred): strategy_count + iterations_per_strategy.
                # Legacy aliases (max_cells_per_run, max_mutations_per_cell) still
                # accepted; runner.start() normalizes them.
                strategy_count_raw = body.get("strategy_count")
                if strategy_count_raw in (None, ""):
                    strategy_count_raw = body.get("max_cells_per_run", 1)
                iterations_raw = body.get("iterations_per_strategy")
                iterations_unlimited = bool(body.get("iterations_unlimited", False))
                if iterations_raw in (None, "") and not iterations_unlimited:
                    legacy_mut = body.get("max_mutations_per_cell")
                    if legacy_mut in (None, ""):
                        iterations_raw = 3  # new sane default
                    else:
                        iterations_raw = max(1, int(legacy_mut) + 1)
                raw_runtime = body.get("max_total_runtime_minutes")
                # New ceiling: 1440 min (24h). 0 means unlimited.
                if raw_runtime in (None, "", 0):
                    normalized_runtime = None
                else:
                    normalized_runtime = max(1, min(1440, int(raw_runtime)))

                args = {
                    "user_pref_root": (
                        body.get("target_root") or body.get("root")
                        or body.get("user_pref_root") or body.get("instrument_root") or None
                    ),
                    "user_capital": (float(capital_value) if capital_value not in (None, "") else None),
                    "user_goal": body.get("goal") or body.get("user_goal"),
                    "dry_run": bool(body.get("dry_run", False)),
                    "skip_compile": bool(body.get("skip_compile", False)),
                    "skip_backtest": bool(body.get("skip_backtest", False)),
                    "use_llm": bool(body.get("use_llm", True)),
                    "allow_template_fallback": bool(body.get("allow_template_fallback", False)),
                    "verify_poll_sec": int(body.get("verify_poll_sec", 0)),
                    "research_mode": body.get("research_mode") or "research_until_candidate_or_budget_exhausted",
                    "strategy_count": max(1, min(10, int(strategy_count_raw))),
                    "iterations_per_strategy": (
                        None if iterations_unlimited else max(1, min(20, int(iterations_raw)))
                    ),
                    "iterations_unlimited": iterations_unlimited,
                    "max_compile_fix_attempts_per_cell": max(1, min(10, int(body.get("max_compile_fix_attempts_per_cell", 5)))),
                    "max_total_runtime_minutes": normalized_runtime,
                    "stop_on_first_candidate": bool(body.get("stop_on_first_candidate", False)),
                    "target_candidate_count": max(1, min(5, int(body.get("target_candidate_count", 1)))),
                    "backtest_instrument": body.get("backtest_instrument") or body.get("instrument"),
                    "smoke_days": max(14, min(45, int(body.get("smoke_days", 30)))),
                    "smoke_timeout_sec": max(30, min(1800, int(body.get("smoke_timeout_sec", 180)))),
                    "min_signal_sanity": max(1, min(100, int(body.get("min_signal_sanity", 8)))),
                }
            except (TypeError, ValueError) as e:
                self._err(HTTPStatus.BAD_REQUEST, f"invalid run parameters: {e}")
                return
            try:
                out = ai_runner.start(args)
                self._json(HTTPStatus.OK, {"ok": True, **out})
            except ai_runner.RunBlockedLMStudio as e:
                self._json(HTTPStatus.CONFLICT,
                           {"ok": False, "blocked_lm_studio": True,
                            "preflight": e.preflight,
                            "hint": ("LM Studio preflight failed. Start LM Studio with the "
                                     "configured judge+coder models, or pass "
                                     "allow_template_fallback=true to proceed with the "
                                     "non-LLM template (research only).")})
            except ai_runner.RunnerBusy as e:
                self._json(HTTPStatus.CONFLICT,
                           {"ok": False, "busy": True, "current": e.current})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"run failed: {e}")
            return

        if path == "/api/ai-lab/cancel":
            exp_id = body.get("experiment_id")
            if not exp_id:
                self._err(HTTPStatus.BAD_REQUEST, "experiment_id required")
                return
            try:
                self._json(HTTPStatus.OK, ai_runner.request_cancel(exp_id))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"cancel failed: {e}")
            return

        if path == "/api/ai-lab/run/cancel":
            run_id = body.get("run_id")
            try:
                self._json(HTTPStatus.OK, ai_runner.request_run_cancel(run_id))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"run cancel failed: {e}")
            return

        if path == "/api/ai-lab/maintenance/sweep-stale":
            try:
                ttl = float(body.get("heartbeat_ttl_hours") or 6.0)
                out = ai_stale_sweep.sweep_stale(heartbeat_ttl_hours=ttl)
                self._json(HTTPStatus.OK, out)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"sweep failed: {e}")
            return

        if path == "/api/ai-lab/lessons":
            text = str(body.get("text") or body.get("summary") or "").strip()
            if not text:
                self._err(HTTPStatus.BAD_REQUEST, "text required")
                return
            scope = str(body.get("scope") or "global")
            scope_key = body.get("scope_key")
            rule = body.get("rule")
            source = str(body.get("source") or "user_research")
            try:
                rec = ai_lessons.record_lesson(
                    summary=text, source=source,
                    scope=scope, scope_key=scope_key, rule=rule,
                )
                self._json(HTTPStatus.OK, {"ok": True, "lesson": rec})
            except ValueError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"lesson save failed: {e}")
            return

        if path == "/api/ai-lab/operator-notes/global":
            text = str(body.get("text") or "").strip()
            if not text:
                self._err(HTTPStatus.BAD_REQUEST, "text required")
                return
            priority = str(body.get("priority") or "high")
            try:
                rec = ai_operator_notes.promote_to_global(
                    text=text, priority=priority,
                    source_experiment_id=body.get("experiment_id"),
                    trigger="ui_manual",
                )
                self._json(HTTPStatus.OK, {"ok": True, "note": rec})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"global note failed: {e}")
            return

        # /api/ai-lab/experiments/{id}/resume-compile
        parts = [p for p in path.split("/") if p]
        if (len(parts) == 5 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "cancel"):
            exp_id = parts[3]
            try:
                self._json(HTTPStatus.OK, ai_runner.request_cancel(exp_id))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"cancel failed: {e}")
            return

        if (len(parts) == 5 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "notes"):
            exp_id = parts[3]
            text = str(body.get("text") or "").strip()
            if not text:
                self._err(HTTPStatus.BAD_REQUEST, "text required")
                return
            priority = str(body.get("priority") or "normal")
            try:
                entry = ai_operator_notes.add(exp_id, text, priority=priority)
                try:
                    ai_activity.log(
                        exp_id, "runner", "operator_note_received", level="info",
                        text_preview=text[:80], priority=priority,
                    )
                except Exception:
                    pass
                self._json(HTTPStatus.OK, {"ok": True, "index": entry.get("index"), "entry": entry})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"note failed: {e}")
            return

        if (len(parts) == 6 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "compile-errors" and parts[5] == "paste"):
            exp_id = parts[3]
            class_name = str(body.get("class_name") or "").strip()
            text = str(body.get("text") or "")
            if not class_name or not text.strip():
                self._err(HTTPStatus.BAD_REQUEST, "class_name and text required")
                return
            try:
                count = ai_compile_errors.append_manual(exp_id, class_name, text)
                try:
                    ai_activity.log(
                        exp_id, "compile", "errors_manual_paste",
                        level="warn", count=count, class_name=class_name,
                    )
                except Exception:
                    pass
                self._json(HTTPStatus.OK, {"ok": True, "count": count})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"paste failed: {e}")
            return

        if (len(parts) == 6 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "portfolio"):
            exp_id = parts[3]
            raw_action = parts[5].replace("-", "_")
            action_map = {
                "candidate": "candidate",
                "approve": "approve",
                "approved": "approve",
                "promote": "promote",
                "promoted": "promote",
                "paper_ready": "paper_ready",
                "remove": "remove",
            }
            action = action_map.get(raw_action)
            if not action:
                self._err(HTTPStatus.BAD_REQUEST, f"invalid portfolio action: {raw_action}")
                return
            approved_by = str(body.get("approved_by") or body.get("operator") or "ui")
            try:
                exp = ai_registry.set_portfolio_membership(
                    exp_id, action=action, approved_by=approved_by,
                )
                try:
                    ai_activity.log(
                        exp_id, "portfolio", action, level="success",
                        portfolio=exp.get("portfolio") or {},
                    )
                except Exception:
                    pass
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "experiment": ai_read_model.experiment_row(exp),
                })
            except ValueError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"portfolio action failed: {e}")
            return

        if (len(parts) == 5 and parts[1] == "ai-lab" and parts[2] == "experiments"
                and parts[4] == "resume-compile"):
            exp_id = parts[3]
            exp = ai_registry.read_experiment(exp_id)
            if not exp:
                self._err(HTTPStatus.NOT_FOUND, f"experiment not found: {exp_id}")
                return
            if exp.get("status") != "awaiting_compile_timeout":
                self._err(HTTPStatus.BAD_REQUEST,
                          f"cannot resume from status {exp.get('status')}")
                return
            try:
                ai_registry.transition_status(exp_id, "awaiting_compile",
                                              reason="user requested extension")
                args = {"skip_compile": False, "skip_backtest": bool(body.get("skip_backtest", False))}
                # Best-effort re-entry: kick a new runner cycle that re-enters compile only.
                # Simpler: just transition; the bridge will refresh on next F5.
                self._json(HTTPStatus.OK, {"ok": True, "status": "awaiting_compile"})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"resume failed: {e}")
            return

        if path == "/api/ai-lab/finalize":
            exp_id = body.get("experiment_id")
            job_id = body.get("job_id")
            if not exp_id or not job_id:
                self._err(HTTPStatus.BAD_REQUEST, "experiment_id and job_id required")
                return
            try:
                result = ai_orchestrator.finalize_backtest(exp_id, job_id)
                self._json(HTTPStatus.OK, result)
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"finalize failed: {e}")
            return

        if path == "/api/ai-lab/user-research/scan":
            try:
                from .ai_lab import user_research as ur  # type: ignore
            except Exception:
                from app.ai_lab import user_research as ur  # type: ignore
            try:
                self._json(HTTPStatus.OK, ur.scan())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"scan failed: {e}")
            return

        self._err(HTTPStatus.NOT_FOUND, f"no ai-lab POST route: {path}")

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
        # /api/profiles/archive/remove-from-nt  (batch or single via {"profile_id": ...})
        if parts == ["api", "profiles", "archive", "remove-from-nt"]:
            try:
                pid = str(body.get("profile_id") or "").strip() or None
                self._json(HTTPStatus.OK, jobqueue.remove_archived_from_ninjatrader(pid)); return
            except jobqueue.JobValidationError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"nt removal error: {e}"); return
        # /api/profiles/ninjatrader/cleanup  — keep only approved strategies in NT.
        if parts == ["api", "profiles", "ninjatrader", "cleanup"]:
            try:
                dry_run = bool(body.get("dry_run", True))
                include_ai = bool(body.get("include_ai_sandbox", True))
                include_ref = bool(body.get("include_ref_lib", True))
                self._json(HTTPStatus.OK, jobqueue.cleanup_ninjatrader_to_approved(
                    dry_run=dry_run, include_ai_sandbox=include_ai, include_ref_lib=include_ref)); return
            except Exception as e:  # pragma: no cover
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"nt cleanup error: {e}"); return
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

    def _governance_post(self, path: str, body: Dict[str, Any]) -> None:
        parts = [p for p in path.split("/") if p]
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "governance":
            if parts[2] == "laws":
                law_id = urllib.parse.unquote(parts[3])
                try:
                    result = governance.update_law(
                        law_id,
                        body if isinstance(body, dict) else {},
                        actor=str(body.get("actor") or "ui"),
                    )
                except KeyError as e:
                    self._err(HTTPStatus.NOT_FOUND, str(e)); return
                except ValueError as e:
                    self._err(HTTPStatus.BAD_REQUEST, str(e)); return
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR,
                              f"governance law update failed: {e}"); return
                self._json(HTTPStatus.OK, result); return
            if parts[2] == "documents":
                doc_id = urllib.parse.unquote(parts[3])
                try:
                    result = governance.update_markdown_document(
                        doc_id,
                        str(body.get("content") or ""),
                        actor=str(body.get("actor") or "ui"),
                        reason=str(body.get("reason") or ""),
                    )
                except KeyError as e:
                    self._err(HTTPStatus.NOT_FOUND, str(e)); return
                except ValueError as e:
                    self._err(HTTPStatus.BAD_REQUEST, str(e)); return
                except Exception as e:
                    self._err(HTTPStatus.INTERNAL_SERVER_ERROR,
                              f"governance document update failed: {e}"); return
                self._json(HTTPStatus.OK, result); return
        self._err(HTTPStatus.NOT_FOUND, f"no governance route: {path}")

    def _route_delete(self) -> None:
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

    def _route_post(self) -> None:
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
        is_profiles = path.startswith("/api/profiles/")
        is_report_favorites = path == "/api/report-favorites" or path.startswith("/api/report-favorites/")
        is_ai_lab = path.startswith("/api/ai-lab/")
        is_governance = path.startswith("/api/governance/")
        is_portfolio = path.startswith("/api/portfolio/")

        if not (path in ("/api/jobs", "/api/batches")
                or is_cancel_job or is_cancel_batch
                or is_catalog_refresh or is_margins_refresh
                or is_server_restart
                or is_ops or is_profiles or is_report_favorites
                or is_ai_lab or is_governance or is_portfolio):
            self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
            return

        if not self._check_local_post():
            return  # _check_local_post already wrote an error

        if is_ai_lab:
            body = self._read_body()
            if body is None:
                return
            self._ai_lab_post(path, body)
            return

        if is_governance:
            body = self._read_body()
            if body is None:
                return
            self._governance_post(path, body)
            return

        if path.startswith("/api/ops/runtime/account-history/"):
            body = self._read_body()
            if body is None:
                return
            try:
                if path == "/api/ops/runtime/account-history/classify":
                    out = account_ledger.classify_event(
                        str(body.get("account_name") or ""), str(body.get("event_id") or ""),
                        str(body.get("kind") or ""), str(body.get("actor") or "ui"), str(body.get("note") or ""),
                    )
                elif path == "/api/ops/runtime/account-history/events":
                    out = account_ledger.add_event(
                        str(body.get("account_name") or ""), str(body.get("kind") or ""), body.get("amount"),
                        str(body.get("actor") or "ui"), str(body.get("note") or ""), body.get("at_utc"),
                        str(body.get("source") or "manual"), str(body.get("source_id") or ""),
                    )
                elif path == "/api/ops/runtime/account-history/import":
                    out = account_ledger.import_events(
                        str(body.get("account_name") or ""), body.get("rows") or [],
                        str(body.get("actor") or "ui"), str(body.get("source") or "broker_statement"),
                    )
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no account-history route: {path}"); return
                self._json(HTTPStatus.OK, out); return
            except ValueError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e)); return
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"account ledger error: {e}"); return

        if is_portfolio:
            body = self._read_body()
            if body is None:
                return
            try:
                if path == "/api/portfolio/roots":
                    out = portfolio_registry.add_root(body.get("root"), body.get("slots", 15), body.get("start_id"), str(body.get("actor") or "ui"))
                elif path == "/api/portfolio/cells":
                    out = portfolio_registry.add_cell(body.get("root"), body.get("cell_id"), str(body.get("actor") or "ui"))
                elif len(parts) == 5 and parts[:3] == ["api", "portfolio", "cells"] and parts[4] == "archive":
                    out = portfolio_registry.archive_cell(urllib.parse.unquote(parts[3]), str(body.get("actor") or "ui"))
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no portfolio route: {path}")
                    return
            except ValueError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except Exception as exc:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"portfolio registry error: {exc}")
                return
            self._json(HTTPStatus.OK, out)
            return

        if is_ops or is_profiles:
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
    # Start the AI Lab stale-experiment sweeper on a daemon thread.
    try:
        ai_stale_sweep.start_background_sweeper(interval_sec=1800, ttl_hours=6.0)
        print("[nta-backend] ai-lab stale sweeper started (TTL=6h, every 30 min)")
    except Exception as e:
        print(f"[nta-backend] ai-lab stale sweeper NOT started: {e}")
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
