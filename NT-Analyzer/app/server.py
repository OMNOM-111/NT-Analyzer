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
import copy
import json
import math
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from email.utils import formatdate, parsedate_to_datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Allow `python app/server.py` to import sibling module.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import jobqueue  # type: ignore[no-redef]
    from app import governance  # type: ignore[no-redef]
    from app import integrations  # type: ignore[no-redef]
    from app import telegram_service  # type: ignore[no-redef]
    from app import telegram_remote  # type: ignore[no-redef]
    from app import tunnel_manager  # type: ignore[no-redef]
    from app import account_auth  # type: ignore[no-redef]
    from app import subscriptions  # type: ignore[no-redef]
    from app import permissions  # type: ignore[no-redef]
    from app import admin_journal  # type: ignore[no-redef]
    from app import invitations  # type: ignore[no-redef]
    from app import legal  # type: ignore[no-redef]
    from app import paypal  # type: ignore[no-redef]
    from app import workspaces  # type: ignore[no-redef]
    from app import market_data  # type: ignore[no-redef]
    from app import secure_store as _secure_store  # type: ignore[no-redef]
    from app import marginrefresh  # type: ignore[no-redef]
    from app import ops  # type: ignore[no-redef]
    from app import performance  # type: ignore[no-redef]
    from app import account_ledger  # type: ignore[no-redef]
    from app import portfolio_registry  # type: ignore[no-redef]
    from app import runtime as ops_runtime  # type: ignore[no-redef]
    from app import local_worker  # type: ignore[no-redef]
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
    from app.ai_lab import cloud_agents as ai_cloud_agents  # type: ignore[no-redef]
    from app.ai_lab import agent_registry as ai_agent_registry  # type: ignore[no-redef]
    from app.ai_lab import agent_router as ai_agent_router  # type: ignore[no-redef]
    from app.ai_lab import universal_llm as ai_universal_llm  # type: ignore[no-redef]
    from app.ai_lab import chief_agent as ai_chief_agent  # type: ignore[no-redef]
    from app.ai_lab import domain_agents as ai_domain_agents  # type: ignore[no-redef]
    from app.ai_lab import news_agent as ai_news_agent  # type: ignore[no-redef]
    from app import local_secrets as _local_secrets  # type: ignore[no-redef]
    from app import news_refresh  # type: ignore[no-redef]
else:
    from . import jobqueue
    from . import governance
    from . import integrations
    from . import telegram_service
    from . import telegram_remote
    from . import tunnel_manager
    from . import account_auth
    from . import subscriptions
    from . import permissions
    from . import admin_journal
    from . import invitations
    from . import legal
    from . import paypal
    from . import workspaces
    from . import market_data
    from . import secure_store as _secure_store
    from . import marginrefresh
    from . import ops
    from . import performance
    from . import account_ledger
    from . import portfolio_registry
    from . import runtime as ops_runtime
    from . import local_worker
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
    from .ai_lab import cloud_agents as ai_cloud_agents
    from .ai_lab import agent_registry as ai_agent_registry
    from .ai_lab import agent_router as ai_agent_router
    from .ai_lab import universal_llm as ai_universal_llm
    from .ai_lab import chief_agent as ai_chief_agent
    from .ai_lab import domain_agents as ai_domain_agents
    from .ai_lab import news_agent as ai_news_agent
    from . import local_secrets as _local_secrets
    from . import news_refresh

_local_secrets.apply()


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
    "object-src 'none'; frame-ancestors 'self' https://web.telegram.org https://*.telegram.org"
)

_SELF_SERVICE_POSTS = {
    "/api/billing/promo/preview",
    "/api/billing/promo/redeem",
    "/api/billing/subscribe",
    "/api/billing/checkout",
    "/api/billing/payment-request",
    "/api/workspaces/personal",
    "/api/workspaces/select",
    "/api/bridge/pair/start",
    "/api/bridge/pair/complete",
    "/api/auth/avatar/refresh",
    # Chart data is a read that carries its request list in the body; viewers
    # (read_only) must be able to poll it so the desktop grid works in the
    # Telegram Mini App exactly like the local UI.
    "/api/ops/runtime/bars/batch",
}
_BILLING_PROMO_POSTS = {
    "/api/billing/promo/preview",
    "/api/billing/promo/redeem",
}
_API_RATE_LOCK = threading.Lock()
_API_RATE: Dict[Tuple[str, str, str], Any] = defaultdict(deque)
_API_RATE_LIMITS = {"read": 600, "write": 120, "owner": 60, "auth": 45}


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

_DESKTOP_INSTRUMENT_ROOTS = {
    "MBT", "MET", "RTY", "MES", "MNQ", "M2K", "MYM",
    "MCL", "MNG", "RB", "HO", "MGC", "SIL", "MHG",
    "6A", "6B", "6C", "6E", "6J", "6S", "E7", "6M", "6N",
    "HE", "LE", "ZC", "ZW", "ZS", "ZM", "ZL",
    "ZT", "ZF", "ZN", "TN", "ZB", "UB",
}

_MARKET_BARS_PAYLOAD_CACHE_LOCK = threading.RLock()
_MARKET_BARS_PAYLOAD_CACHE: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
_MARKET_BARS_PAYLOAD_CACHE_MAX = 512


def _market_bar_time(row: Dict[str, Any]) -> Optional[datetime]:
    raw = str(row.get("t") or row.get("time_utc") or row.get("time") or "")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _refresh_market_payload_age(payload: Dict[str, Any]) -> Dict[str, Any]:
    source = payload.get("source") if isinstance(payload.get("source"), dict) else None
    if not source:
        return payload
    updated = source.get("updated_at_utc")
    if not updated:
        return payload
    try:
        dt = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        source["age_sec"] = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except ValueError:
        pass
    return payload


def _market_payload_cache_get(key: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    with _MARKET_BARS_PAYLOAD_CACHE_LOCK:
        cached = _MARKET_BARS_PAYLOAD_CACHE.get(key)
    if cached is None:
        return None
    return _refresh_market_payload_age(copy.deepcopy(cached))


def _market_payload_cache_put(key: Tuple[Any, ...], payload: Dict[str, Any]) -> None:
    with _MARKET_BARS_PAYLOAD_CACHE_LOCK:
        _MARKET_BARS_PAYLOAD_CACHE[key] = copy.deepcopy(payload)
        while len(_MARKET_BARS_PAYLOAD_CACHE) > _MARKET_BARS_PAYLOAD_CACHE_MAX:
            try:
                oldest = next(iter(_MARKET_BARS_PAYLOAD_CACHE))
            except StopIteration:
                return
            _MARKET_BARS_PAYLOAD_CACHE.pop(oldest, None)


def _market_bars_payload(instrument: str, timeframe: str, limit: int,
                         range_days: int = 0, from_date: str = "",
                         to_date: str = "", register: bool = True,
                         snapshot_index: Optional[Dict[str, Any]] = None,
                         alerts_index: Optional[Dict[str, Any]] = None,
                         max_points: int = 0,
                         workspace_id: str = "") -> Dict[str, Any]:
    if register:
        market_data.register_request(instrument, timeframe, limit, range_days, from_date, to_date)
    try:
        max_points = max(0, min(20000, int(max_points or 0)))
    except (TypeError, ValueError):
        max_points = 0
    cache_key = (
        str(workspace_id or ""),
        " ".join(str(instrument or "").strip().upper().split()),
        str(timeframe or "5m"),
        int(limit or 1500),
        int(range_days or 0),
        str(from_date or "")[:10],
        str(to_date or "")[:10],
        max_points,
        market_data.snapshot_source_signature(),
        market_data.alerts_source_signature(),
    )
    cached = _market_payload_cache_get(cache_key)
    if cached is not None:
        return cached
    if snapshot_index is not None:
        runtime_bars = market_data.series_from_index(snapshot_index, instrument, timeframe, limit)
    else:
        runtime_bars = market_data.read_runtime_series(instrument, timeframe, limit)
    if runtime_bars and runtime_bars.get("bars"):
        out = runtime_bars
    else:
        out = jobqueue.read_instrument_bars(instrument, timeframe, limit)
        out["status"] = "historical_fallback" if out.get("bars") else (
            (runtime_bars or {}).get("status") or "waiting")
        out["bridge"] = {
            "status": (runtime_bars or {}).get("status") or "subscription_requested",
            "error": (runtime_bars or {}).get("error") or "",
        }
        if not out.get("bars"):
            detail = out["bridge"]["error"]
            out["note"] = detail or (
                "Подписка отправлена в NinjaTrader Bridge. Проверьте подключение к провайдеру данных, "
                "актуальность контракта и установленную версию Bridge.")
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    try:
        if from_date:
            start = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc)
        if to_date:
            end = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc) + timedelta(days=1)
    except ValueError:
        start = end = None
    if not start and range_days > 0:
        latest_times = [_market_bar_time(row) for row in (out.get("bars") or []) if isinstance(row, dict)]
        latest = max((dt for dt in latest_times if dt is not None), default=datetime.now(timezone.utc))
        start = latest - timedelta(days=range_days)
        if out.get("status") == "historical_fallback":
            end = latest + timedelta(seconds=1)
    if start or end:
        out["bars"] = [row for row in (out.get("bars") or []) if isinstance(row, dict)
                       and (lambda dt: dt is not None and (start is None or dt >= start)
                            and (end is None or dt < end))(_market_bar_time(row))]
        out["total"] = len(out["bars"])
    if alerts_index is not None:
        symbol = " ".join(str(instrument or "").strip().upper().split())
        out["alerts"] = list(alerts_index.get(symbol, []))
    else:
        out["alerts"] = market_data.list_alerts(
            instrument=instrument, include_inactive=True)["alerts"]
    if max_points:
        out = market_data.downsample_series_payload(out, max_points) or out
    if out.get("bars") and (out.get("source") or {}).get("kind") == "ninjatrader_runtime":
        _market_payload_cache_put(cache_key, out)
    return out


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

    def _request_ips(self) -> Tuple[str, str]:
        tunnel_ip = str((self.client_address or ("", 0))[0] or "")
        forwarded = str(self.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        return tunnel_ip, forwarded

    def _cookie_value(self, name: str) -> str:
        try:
            cookie = SimpleCookie()
            cookie.load(str(self.headers.get("Cookie") or ""))
            return str(cookie[name].value) if name in cookie else ""
        except Exception:
            return ""

    def _set_session_cookie(self, token: str) -> None:
        secure = self._is_remote_api_request() or str(self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        value = (
            f"{account_auth.SESSION_COOKIE}={token}; Path=/; Max-Age={account_auth.SESSION_TTL_SEC}; "
            f"HttpOnly; SameSite=Strict" + ("; Secure" if secure else "")
        )
        self._extra_headers.append(("Set-Cookie", value))

    def _clear_session_cookie(self) -> None:
        secure = self._is_remote_api_request() or str(self.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        value = f"{account_auth.SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict" + ("; Secure" if secure else "")
        self._extra_headers.append(("Set-Cookie", value))

    @staticmethod
    def _request_hostname(value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        try:
            parsed = urllib.parse.urlparse(raw if "://" in raw else "//" + raw)
            return str(parsed.hostname or "").lower()
        except (TypeError, ValueError):
            return ""

    def _is_remote_api_request(self) -> bool:
        if self.headers.get(telegram_remote.INIT_DATA_HEADER):
            return True
        hosts = [
            self._request_hostname(self.headers.get("Host") or ""),
            self._request_hostname(self.headers.get("X-Forwarded-Host") or ""),
            self._request_hostname(self.headers.get("Origin") or ""),
            self._request_hostname(self.headers.get("Referer") or ""),
        ]
        return any(host and host not in _ALLOWED_ORIGIN_HOSTS for host in hosts)

    def _local_owner_context(self) -> Dict[str, Any]:
        owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        user: Dict[str, Any] = {}
        if owner_id:
            user = account_auth.ensure_owner(owner_id) or {}
        return self._decorate_workspace_context({
            "source": "local", "user_id": int(owner_id or 0),
            "role": "owner", "is_owner": True,
            "csrf_token": "", "user": user,
        })

    def _decorate_workspace_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        try:
            workspace_context = workspaces.context_for_user(
                context.get("user_id"),
                is_owner=bool(context.get("is_owner")),
                owner_id=owner_id,
            )
        except workspaces.WorkspaceError as exc:
            workspace_context = {"error": str(exc), "workspaces": [], "active_workspace": {}, "active_membership": {}}
        context["workspace_context"] = workspace_context
        context["workspaces"] = workspace_context.get("workspaces") or []
        context["active_workspace"] = workspace_context.get("active_workspace") or {}
        context["active_membership"] = workspace_context.get("active_membership") or {}
        return context

    def _workspace_runtime_stubbed(self, path: str, qs: Dict[str, Any]) -> bool:
        context = getattr(self, "_remote_context", None) or {}
        payload = workspaces.runtime_stub(path, qs, context.get("workspace_context") or {})
        if payload is None:
            return False
        self._json(HTTPStatus.OK, payload)
        return True

    def _api_action_class(self, path: str, method: str) -> str:
        if path.startswith("/api/auth/"):
            return "auth"
        if path.startswith("/api/owner/") or path.startswith("/api/telegram/") or path.startswith("/api/worker/"):
            return "owner"
        return "read" if method.upper() in {"GET", "HEAD"} else "write"

    def _check_api_rate_limit(self, context: Dict[str, Any], path: str) -> bool:
        if os.environ.get("NTA_DISABLE_RATE_LIMIT") == "1":
            return True
        action = self._api_action_class(path, self.command)
        limit = int(_API_RATE_LIMITS.get(action, 120))
        tunnel_ip, _forwarded_ip = self._request_ips()
        user_id = str(context.get("user_id") or "anonymous")
        key = (user_id, str(tunnel_ip or ""), action)
        now = time.time()
        with _API_RATE_LOCK:
            q = _API_RATE[key]
            while q and q[0] <= now - 60:
                q.popleft()
            if len(q) >= limit:
                self._err(HTTPStatus.TOO_MANY_REQUESTS, "Слишком много запросов. Повторите позже.")
                return False
            q.append(now)
        return True

    def _authorize_api(self, path: str) -> bool:
        # The local-owner bypass (no Telegram login) is ONLY safe for requests
        # that physically originate on the owner's machine: loopback, no Telegram
        # initData header and no public tunnel host. A remote request — the public
        # Mini App tunnel or anything carrying Telegram initData — must ALWAYS be
        # authenticated against the approved account allowlist, even when desktop
        # auth is disabled. Otherwise every Mini App visitor would inherit full
        # owner access (the reported "instant access" security hole).
        if not account_auth.auth_required() and not self._is_remote_api_request():
            try:
                self._remote_context = self._local_owner_context()
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc)); return False
            return True
        tunnel_ip, forwarded_ip = self._request_ips()
        init_data = str(self.headers.get(telegram_remote.INIT_DATA_HEADER) or "")
        if init_data:
            self._remote_attempt = True
            try:
                self._remote_context = telegram_remote.authorize(
                    init_data, str(os.environ.get(telegram_service.TOKEN_ENV) or ""),
                    method=self.command, path=path, tunnel_ip=tunnel_ip,
                    forwarded_ip=forwarded_ip,
                )
                account = account_auth.find_active_user(self._remote_context.get("user_id")) or {}
                self._remote_context["is_owner"] = bool(account.get("is_owner"))
                # Populate the public profile so /api/auth/me and other handlers
                # that read context["user"] (name, e-mail, avatar, features) work
                # over the Telegram Mini App, exactly like the desktop session path.
                self._remote_context["user"] = (
                    account_auth._public_user(account, include_contact=True, include_avatar=True)
                    if account else {}
                )
                self._remote_context = self._decorate_workspace_context(self._remote_context)
                method = self.command.upper()
                role = str(self._remote_context.get("role") or "read_only")
                workspace = self._remote_context.get("active_workspace") if isinstance(self._remote_context.get("active_workspace"), dict) else {}
                personal_statement_write = path.startswith("/api/ops/runtime/account-history/") and bool(workspace) and not workspace.get("uses_owner_runtime")
                if (method not in {"GET", "HEAD"} and role == "read_only" and path not in _SELF_SERVICE_POSTS
                        and not path.startswith("/api/bridge/connections/") and not personal_statement_write):
                    raise telegram_remote.RemoteAccessError("Для этого действия нужна роль «полное управление».", 403, self._remote_context)
                if (path.startswith("/api/auth/users") or path.startswith("/api/owner/")
                        or path.startswith("/api/worker/")) and not self._remote_context["is_owner"]:
                    raise telegram_remote.RemoteAccessError("Управление пользователями разрешено только владельцу.", 403, self._remote_context)
                try:
                    permissions.enforce(path, self._remote_context)
                except permissions.PermissionError as exc:
                    raise telegram_remote.RemoteAccessError(str(exc), exc.status, self._remote_context) from None
                if not self._check_api_rate_limit(self._remote_context, path):
                    return False
                return True
            except (telegram_remote.RemoteAccessError, account_auth.AccountAuthError) as exc:
                self._remote_context = getattr(exc, "context", None)
                self._remote_error = str(exc)
                self._err(getattr(exc, "status", 403), str(exc))
                return False
        try:
            context = account_auth.authenticate_session(
                self._cookie_value(account_auth.SESSION_COOKIE),
            )
        except account_auth.AccountAuthError as exc:
            self._err(exc.status, str(exc)); return False
        if not context:
            self._err(HTTPStatus.UNAUTHORIZED, "Требуется вход через Telegram.")
            return False
        context = self._decorate_workspace_context(context)
        method = self.command.upper()
        role = str(context.get("role") or "read_only")
        workspace = context.get("active_workspace") if isinstance(context.get("active_workspace"), dict) else {}
        personal_statement_write = path.startswith("/api/ops/runtime/account-history/") and bool(workspace) and not workspace.get("uses_owner_runtime")
        if (method not in {"GET", "HEAD"} and role == "read_only" and path not in _SELF_SERVICE_POSTS
            and not path.startswith("/api/bridge/connections/") and not personal_statement_write):
            self._err(HTTPStatus.FORBIDDEN, "Для этого действия нужна роль «полное управление».")
            return False
        owner_only = (path.startswith("/api/telegram/") or path.startswith("/api/auth/users")
                      or path.startswith("/api/owner/") or path.startswith("/api/worker/")
                      or path == "/api/server/restart")
        if owner_only and not context.get("is_owner"):
            self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
            return False
        try:
            permissions.enforce(path, context)
        except permissions.PermissionError as exc:
            self._err(exc.status, str(exc)); return False
        if not self._check_api_rate_limit(context, path):
            return False
        self._remote_context = context
        return True

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

    def _check_json_content_type(self) -> bool:
        ct = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ct != "application/json":
            self._err(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Content-Type must be application/json")
            return False
        return True

    def _check_public_auth_origin(self) -> bool:
        if not self._check_json_content_type():
            return False
        origin = self.headers.get("Origin")
        if not origin:
            self._err(HTTPStatus.FORBIDDEN, "Origin обязателен для входа.")
            return False
        origin_host = self._request_hostname(origin)
        request_host = self._request_hostname(self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "")
        if not origin_host or origin_host != request_host:
            self._err(HTTPStatus.FORBIDDEN, "Cross-origin запрос входа отклонён.")
            return False
        return True

    def _augment_permissions(self, context: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        """Attach the central authorization view (subscription-driven nav +
        capabilities + Free Preview state) to an auth payload."""
        user = payload.get("user") or {}
        is_owner = bool(payload.get("is_owner"))
        subscription: Dict[str, Any] = {}
        if not is_owner:
            try:
                subscription = subscriptions.active_entitlement(context.get("user_id"))
            except subscriptions.SubscriptionError:
                subscription = {}
        perm = permissions.resolve(user, None if is_owner else subscription)
        if isinstance(user, dict):
            payload["user"] = {**user, "features": perm["nav"]}
        payload["features"] = perm["nav"]
        payload["capabilities"] = perm["capabilities"]
        payload["capability_catalog"] = permissions.capability_catalog()
        payload["plan_id"] = perm["plan_id"]
        payload["free_preview"] = perm["free_preview"]
        payload["locked_nav"] = perm["locked_nav"]
        payload["unlock_message"] = perm["unlock_message"]
        return payload

    def _ai_conversation_scope(self) -> Dict[str, Any]:
        context = getattr(self, "_remote_context", None) or {}
        active = context.get("active_workspace") if isinstance(context.get("active_workspace"), dict) else {}
        membership = context.get("active_membership") if isinstance(context.get("active_membership"), dict) else {}
        user = context.get("user") if isinstance(context.get("user"), dict) else {}
        display = " ".join(
            str(user.get(key) or "").strip() for key in ("first_name", "last_name")
        ).strip() or str(user.get("username") or "")
        if not context.get("user_id") or not active.get("workspace_id"):
            raise ai_chief_agent.ChiefAgentError("Для AI-чата нужна активная рабочая область пользователя.")
        return {
            "user_id": context.get("user_id"),
            "workspace_id": active.get("workspace_id"),
            "membership_role": membership.get("role") or context.get("role") or "",
            "is_owner": bool(context.get("is_owner")),
            "display_name": display,
            "capabilities": context.get("capabilities") if isinstance(context.get("capabilities"), dict) else {},
        }

    def _auth_status(self) -> None:
        try:
            # Fast-path: no auth required AND the request is genuinely local
            # (loopback desktop, no Telegram initData, no public tunnel host).
            # Return the local-owner context so the desktop shell loads without a
            # Telegram login. Remote requests never take this path — they are
            # always authenticated below so Mini App visitors can't inherit owner.
            if not account_auth.auth_required() and not self._is_remote_api_request():
                context = self._local_owner_context()
                self._json(HTTPStatus.OK, self._augment_permissions(context, {
                    "authenticated": True, "source": context.get("source"),
                    "role": context.get("role"), "is_owner": bool(context.get("is_owner")),
                    "csrf_token": "", "user": context.get("user") or {},
                    "workspaces": context.get("workspaces") or [],
                    "active_workspace": context.get("active_workspace") or {},
                    "active_membership": context.get("active_membership") or {},
                }))
                return
            owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
            account_auth.ensure_owner(owner_id)
            init_data = str(self.headers.get(telegram_remote.INIT_DATA_HEADER) or "")
            context = None
            if init_data:
                tunnel_ip, forwarded_ip = self._request_ips()
                context = telegram_remote.authorize(
                    init_data, str(os.environ.get(telegram_service.TOKEN_ENV) or ""),
                    method="GET", path="/api/auth/status", tunnel_ip=tunnel_ip,
                    forwarded_ip=forwarded_ip,
                )
                user = account_auth.find_active_user(context.get("user_id"))
                context["user"] = account_auth._public_user(user or {}, include_contact=True, include_avatar=True)
                context["role"] = str((user or {}).get("role") or context.get("role") or "read_only")
                context["is_owner"] = bool((user or {}).get("is_owner"))
                # Record the Mini App session for the admin login history (throttled
                # so repeated status polls during one session don't spam the log).
                account_auth.record_login(
                    context.get("user_id"), source=telegram_remote.SOURCE,
                    ip=forwarded_ip or tunnel_ip,
                    user_agent=str(self.headers.get("User-Agent") or ""),
                    throttle_sec=6 * 3600)
            else:
                context = account_auth.authenticate_session(self._cookie_value(account_auth.SESSION_COOKIE))
            if context:
                context = self._decorate_workspace_context(context)
            if not context:
                self._json(HTTPStatus.UNAUTHORIZED, {
                    "error": "Требуется вход через Telegram.", "authenticated": False,
                    "auth_required": account_auth.auth_required(),
                    "bot_username": str(telegram_service.load_settings().get("bot_username") or ""),
                    "storage": account_auth.storage_status(),
                })
                return
            self._json(HTTPStatus.OK, self._augment_permissions(context, {
                "authenticated": True, "source": context.get("source"),
                "role": context.get("role"), "is_owner": bool(context.get("is_owner")),
                "csrf_token": str(context.get("csrf_token") or ""),
                "user": context.get("user") or {},
                "workspaces": context.get("workspaces") or [],
                "active_workspace": context.get("active_workspace") or {},
                "active_membership": context.get("active_membership") or {},
            }))
        except (account_auth.AccountAuthError, telegram_remote.RemoteAccessError) as exc:
            self._err(getattr(exc, "status", 503), str(exc))

    def _user_nt_info(self, user_id: Any, is_owner: bool = False) -> Dict[str, Any]:
        """NinjaTrader connection summary for one user: observing the owner's
        runtime vs. running their own bridge, plus the active workspace name."""
        owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        try:
            wc = workspaces.context_for_user(user_id, is_owner=is_owner, owner_id=owner_id)
        except workspaces.WorkspaceError:
            return {"uses_owner_runtime": True, "connected": bool(is_owner),
                    "connection_id": "", "mode": "observe_owner", "workspace": ""}
        active = wc.get("active_workspace") or {}
        uses_owner = bool(active.get("uses_owner_runtime"))
        conn_id = str(active.get("default_runtime_connection_id") or "")
        return {
            "uses_owner_runtime": uses_owner,
            "connection_id": conn_id,
            "connected": (is_owner and uses_owner) or (not uses_owner and bool(conn_id)),
            "mode": "observe_owner" if uses_owner else "own_ninjatrader",
            "workspace": str(active.get("display_name") or ""),
        }

    def _render_invite(self, out: Dict[str, Any]) -> Dict[str, Any]:
        voucher = out.get("voucher") or {}
        invite = out.get("invite") or {}
        code = str(voucher.get("code") or invite.get("code") or "")
        plan_label = str((subscriptions.PLANS.get(str(voucher.get("grant_plan_id") or "")) or {}).get("label") or "")
        ctx = getattr(self, "_remote_context", None) or {}
        who = ctx.get("user") or {}
        inviter = (" ".join([str(who.get("first_name") or ""), str(who.get("last_name") or "")]).strip()
                   or str(who.get("username") or ""))
        rendered = invitations.render_invitation(
            code=code, telegram_link=str(invite.get("telegram") or ""),
            web_link=str(invite.get("web") or ""), plan_label=plan_label, inviter=inviter)
        rendered.pop("png_bytes", None)  # bytes are not JSON serialisable
        return rendered

    def _send_invite(self, body: Dict[str, Any]) -> Dict[str, Any]:
        import base64 as _b64
        text = str(body.get("text") or "")[:3500]
        image_data_url = str(body.get("image_data_url") or "")
        owner_chat = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        if not owner_chat:
            return {"ok": False, "error": "Telegram владельца не настроен."}
        png: Optional[bytes] = None
        if image_data_url.startswith("data:image/png;base64,") and len(image_data_url) < 4_000_000:
            try:
                png = _b64.b64decode(image_data_url.split(",", 1)[1], validate=True)
            except Exception:
                png = None
        sent = False
        if png and telegram_service.send_photo_bytes(owner_chat, png, caption=text[:1024], filename="invite.png"):
            sent = True
        else:
            try:
                telegram_service._send_raw(text or "Приглашение StratForge AI", chat_id=owner_chat)
                sent = True
            except telegram_service.TelegramServiceError:
                sent = False
        return {"ok": bool(sent), "sent_to": "owner"}

    def _cabinet_payload(self) -> Dict[str, Any]:
        context = getattr(self, "_remote_context", None) or {}
        uid = context.get("user_id")
        user = context.get("user") or {}
        is_owner = bool(context.get("is_owner"))
        try:
            subs = subscriptions.entitlements_for_user(uid)
        except subscriptions.SubscriptionError:
            subs = {"entitlements": []}
        entitlements = subs.get("entitlements") or []
        if is_owner:
            try:
                subscription = subscriptions.owner_entitlement()
            except subscriptions.SubscriptionError:
                subscription = {}
        else:
            try:
                subscription = subscriptions.active_entitlement(uid)
            except subscriptions.SubscriptionError:
                subscription = entitlements[0] if entitlements else {}
        active = context.get("active_workspace") or {}
        membership = context.get("active_membership") or {}
        # The owner is NOT a learner: their contour is the real NinjaTrader with
        # full access. Only non-owner viewers are "observing" the owner account.
        owner_full_access = is_owner and bool(active.get("uses_owner_runtime"))
        # Central authorization: turn the plan (or Free Preview) + owner overrides
        # into concrete capabilities and navigation. The client gates the rail and
        # locks premium sections from this single source of truth.
        perm = permissions.resolve(user, None if is_owner else subscription)
        nav_features = perm["nav"]
        if isinstance(user, dict):
            user = {**user, "features": nav_features}
        return {
            "authenticated": True,
            "source": context.get("source"),
            "user": user,
            "role": context.get("role"),
            "is_owner": is_owner,
            "workspaces": context.get("workspaces") or [],
            "active_workspace": active,
            "active_membership": membership,
            "subscription": subscription,
            "entitlements": entitlements,
            "features": nav_features,
            "feature_catalog": account_auth.feature_catalog(),
            "capabilities": perm["capabilities"],
            "capability_catalog": permissions.capability_catalog(),
            "plan_id": perm["plan_id"],
            "free_preview": perm["free_preview"],
            "locked_nav": perm["locked_nav"],
            "unlock_message": perm["unlock_message"],
            "payments_enabled": bool(subscriptions.payments_active()),
            "telegram_configured": bool(str(os.environ.get(telegram_service.TOKEN_ENV) or "").strip()),
            "nt_connection": {
                "uses_owner_runtime": bool(active.get("uses_owner_runtime")),
                "owner_full_access": owner_full_access,
                "connected": (owner_full_access
                              or (bool(active.get("default_runtime_connection_id")) and not active.get("uses_owner_runtime"))),
                "connection_id": str(active.get("default_runtime_connection_id") or ""),
            },
        }

    def _auth_me(self) -> None:
        self._json(HTTPStatus.OK, self._cabinet_payload())

    def _serve_avatar(self, target: str) -> None:
        context = getattr(self, "_remote_context", None) or {}
        try:
            target_id = int(target)
        except (TypeError, ValueError):
            self._err(HTTPStatus.NOT_FOUND, "avatar not found"); return
        requester = int(context.get("user_id") or 0)
        if not context.get("is_owner") and requester != target_id:
            self._err(HTTPStatus.FORBIDDEN, "Доступ к аватару запрещён."); return
        path = account_auth.avatar_file(target_id)
        if not path:
            self._err(HTTPStatus.NOT_FOUND, "avatar not found"); return
        try:
            blob = path.read_bytes()
        except OSError:
            self._err(HTTPStatus.NOT_FOUND, "avatar not found"); return
        ext = path.suffix.lstrip(".").lower()
        ctype = "image/png" if ext == "png" else "image/webp" if ext == "webp" else "image/jpeg"
        self._bytes(HTTPStatus.OK, blob, ctype)

    def _refresh_avatar(self) -> None:
        context = getattr(self, "_remote_context", None) or {}
        out = account_auth.refresh_avatar(context.get("user_id"), fetcher=telegram_service.fetch_user_avatar)
        self._json(HTTPStatus.OK, out)

    def _paypal_audit(self, event: Dict[str, Any], result: Dict[str, Any], verified: bool) -> None:
        try:
            path = _PROJECT_ROOT / "data" / "audit" / "paypal-webhook.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "event_type": str(event.get("event_type") or ""),
                "event_id": str(event.get("id") or ""),
                "verified": bool(verified),
                "result": result,
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def _paypal_webhook(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if 0 < length <= 1_000_000 else b""
        try:
            event = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            event = {}
        if not isinstance(event, dict) or not event.get("event_type"):
            # Return 200 so PayPal does not retry obviously-empty deliveries.
            self._json(HTTPStatus.OK, {"ok": False, "reason": "empty_event"})
            return
        headers = {str(key).lower(): str(value) for key, value in self.headers.items()}
        try:
            verified = paypal.verify_webhook(headers, event)
        except paypal.PayPalError:
            verified = False
        if not verified:
            self._paypal_audit(event, {"ok": False, "reason": "unverified"}, False)
            self._err(HTTPStatus.BAD_REQUEST, "PayPal webhook signature not verified.")
            return
        try:
            result = paypal.process_event(event)
        except Exception as exc:  # pragma: no cover - defensive
            result = {"ok": False, "error": str(exc)[:200]}
        self._paypal_audit(event, result, True)
        self._json(HTTPStatus.OK, result)

    def _notify_owner_payment_request(self, context: Dict[str, Any], request: Dict[str, Any]) -> None:
        try:
            if not request:
                return
            user = (context or {}).get("user") or {}
            name = " ".join([str(user.get("first_name") or ""), str(user.get("last_name") or "")]).strip() \
                or str(user.get("username") or context.get("user_id") or "")
            plan_id = str(request.get("plan_id") or "")
            plan = subscriptions.PLANS.get(plan_id) or {}
            lines = [
                f"Пользователь {name} (ID {context.get('user_id')}) сообщает об оплате.",
                f"Тариф: {plan.get('label') or plan_id} · ${request.get('amount_usd')}",
                "Проверьте платёж в PayPal и включите тариф: Кабинет → Заявки.",
            ]
            telegram_service.send_chief_report("💳 Заявка на оплату", lines, urgent=True)
        except Exception:  # pragma: no cover - notification is best-effort
            pass

    def _miniapp_register(self) -> None:
        if not self._check_public_auth_origin():
            return
        body = self._read_body()
        if body is None:
            return
        init_data = str(self.headers.get(telegram_remote.INIT_DATA_HEADER) or body.get("init_data") or "")
        try:
            verified = telegram_remote.validate_init_data(
                init_data, str(os.environ.get(telegram_service.TOKEN_ENV) or ""))
        except telegram_remote.RemoteAccessError as exc:
            self._err(getattr(exc, "status", 401), str(exc)); return
        owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        try:
            account_auth.ensure_owner(owner_id)
        except account_auth.AccountAuthError:
            pass
        try:
            user = account_auth.register_via_telegram(
                verified["user"],
                email=str(body.get("email") or ""),
                first_name=str(body.get("first_name") or ""),
                last_name=str(body.get("last_name") or ""),
                accept_terms=bool(body.get("accept_terms")),
                api_call=telegram_service._api_call, owner_chat_id=owner_id,
            )
            self._json(HTTPStatus.OK, {"ok": True, "authenticated": True, "user": user})
        except account_auth.AccountAuthError as exc:
            self._err(exc.status, str(exc))

    def _auth_public_post(self, path: str) -> None:
        if not self._check_public_auth_origin():
            return
        body = self._read_body()
        if body is None:
            return
        owner_id = str(os.environ.get(telegram_service.CHAT_ENV) or "").strip()
        tunnel_ip, forwarded_ip = self._request_ips()
        ip = forwarded_ip or tunnel_ip
        try:
            account_auth.ensure_owner(owner_id)
            if path == "/api/auth/login/start":
                out = account_auth.start_login(
                    bot_username=str(telegram_service.load_settings().get("bot_username") or ""),
                    ip=ip, user_agent=str(self.headers.get("User-Agent") or ""),
                )
            elif path == "/api/auth/login/status":
                out = account_auth.create_session_for_challenge(
                    str(body.get("challenge_id") or ""), ip=ip,
                    user_agent=str(self.headers.get("User-Agent") or ""),
                )
                if out.get("status") == "authenticated":
                    self._set_session_cookie(str(out.pop("session_token")))
            elif path == "/api/auth/profile":
                out = account_auth.complete_profile(
                    str(body.get("challenge_id") or ""), body.get("profile") or body,
                    api_call=telegram_service._api_call, owner_chat_id=owner_id,
                    ip=ip, user_agent=str(self.headers.get("User-Agent") or ""),
                )
            else:
                self._err(HTTPStatus.NOT_FOUND, f"no auth route: {path}"); return
            self._json(HTTPStatus.OK, out)
        except account_auth.AccountAuthError as exc:
            self._err(exc.status, str(exc))

    def _check_local_origin(self) -> bool:
        """Check Origin/Referer without requiring a Content-Type (used for DELETE)."""
        context = getattr(self, "_remote_context", None) or {}
        if context.get("source") == telegram_remote.SOURCE:
            return True
        if context.get("source") == "desktop_session":
            if not account_auth.verify_csrf(context, str(self.headers.get("X-CSRF-Token") or "")):
                self._err(HTTPStatus.FORBIDDEN, "CSRF token отсутствует или недействителен.")
                return False
            origin = self.headers.get("Origin")
            if not origin:
                self._err(HTTPStatus.FORBIDDEN, "Origin обязателен для изменения данных.")
                return False
            origin_host = self._request_hostname(origin)
            request_host = self._request_hostname(self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "")
            if not origin_host or not request_host or origin_host != request_host:
                self._err(HTTPStatus.FORBIDDEN, "Cross-origin запрос отклонён.")
                return False
            return True
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin:
            return True  # non-browser client (CLI, Invoke-RestMethod)
        # A same-origin POST is never a cross-site (CSRF) request. Allow it when
        # the Origin host matches the host the request actually arrived on — this
        # covers the HTTPS Telegram Mini App tunnel (e.g. app.stratforges.com)
        # even when auth is disabled and the request is treated as local owner,
        # where the context source is "local" rather than the Mini App source.
        origin_host = self._request_hostname(origin)
        same_origin_hosts = {
            self._request_hostname(self.headers.get("X-Forwarded-Host") or ""),
            self._request_hostname(self.headers.get("Host") or ""),
        }
        if origin_host and origin_host in same_origin_hosts:
            return True
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
        if getattr(self, "_remote_attempt", False) and not getattr(self, "_remote_audited", False):
            self._remote_audited = True
            tunnel_ip, forwarded_ip = self._request_ips()
            try:
                telegram_remote.audit(
                    method=self.command, path=urllib.parse.urlparse(self.path).path,
                    status=int(code), context=getattr(self, "_remote_context", None),
                    tunnel_ip=tunnel_ip, forwarded_ip=forwarded_ip,
                    error=str(getattr(self, "_remote_error", "") or ""),
                )
            except Exception:
                pass
        super().send_response(code, message)

    def end_headers(self):  # type: ignore[override]
        for name, value in getattr(self, "_extra_headers", []):
            self.send_header(name, value)
        self._extra_headers = []
        super().end_headers()

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
        self._remote_attempt = False
        self._remote_audited = False
        self._remote_context = None
        self._remote_error = ""
        self._extra_headers = []
        try:
            self._route_get()
        except Exception:
            self._handle_unexpected("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._response_started = False
        self._remote_attempt = False
        self._remote_audited = False
        self._remote_context = None
        self._remote_error = ""
        self._extra_headers = []
        try:
            self._route_post()
        except Exception:
            self._handle_unexpected("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._response_started = False
        self._remote_attempt = False
        self._remote_audited = False
        self._remote_context = None
        self._remote_error = ""
        self._extra_headers = []
        try:
            self._route_delete()
        except Exception:
            self._handle_unexpected("DELETE")

    def _route_get(self) -> None:
        url = urllib.parse.urlparse(self.path)
        path = url.path
        qs = urllib.parse.parse_qs(url.query)

        if path == "/api/auth/status":
            self._auth_status()
            return

        if path == "/api/legal/terms":
            # Public: the terms must be readable during registration, before auth.
            self._json(HTTPStatus.OK, legal.terms_payload())
            return

        if path.startswith("/api/") and not self._authorize_api(path):
            return

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
                "/accounting.html": "/ui/performance.html", "/accounting": "/ui/performance.html",
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
                "/performance.html", "/strategies.html", "/ai-lab.html", "/ai-agents.html", "/documents.html",
                "/news.html", "/topstep.html", "/desktop.html",
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
                "worker": local_worker.status(),
            })
            return

        if path == "/api/worker/jobs":
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            try:
                limit = int((qs.get("limit") or ["100"])[0])
            except ValueError:
                limit = 100
            status_filter = str((qs.get("status") or [""])[0] or "")
            self._json(HTTPStatus.OK, local_worker.list_jobs(status=status_filter, limit=limit))
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
            def optional_float(name: str) -> Optional[float]:
                raw = str((qs.get(name) or [""])[0] or "").strip()
                if not raw:
                    return None
                try:
                    return float(raw)
                except ValueError:
                    return None
            limit = max(1, min(10000, limit))
            offset = max(0, offset)
            try:
                analysis_limit = int((qs.get("analysis_limit") or ["500"])[0])
            except ValueError:
                analysis_limit = 500
            self._json(HTTPStatus.OK, jobqueue.list_reports(
                limit=limit,
                offset=offset,
                sort_col=sort_col,
                sort_dir=sort_dir,
                status_filter=status_filter,
                query=str((qs.get("q") or [""])[0] or ""),
                report_no=str((qs.get("report_no") or [""])[0] or ""),
                instrument=str((qs.get("instrument") or [""])[0] or ""),
                frequency=str((qs.get("frequency") or [""])[0] or ""),
                from_date=str((qs.get("from") or [""])[0] or ""),
                to_date=str((qs.get("to") or [""])[0] or ""),
                min_trades=optional_float("min_trades"),
                min_win=optional_float("min_win"),
                min_pf=optional_float("min_pf"),
                pnl_sign=str((qs.get("pnl_sign") or [""])[0] or ""),
                min_confidence=optional_float("min_confidence"),
                analysis_limit=analysis_limit,
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
            runtime_override = ""
            context = getattr(self, "_remote_context", None) or {}
            if path.startswith("/api/ops/runtime/"):
                runtime_override = workspaces.runtime_dir_for_context(context.get("workspace_context") or {})
            if runtime_override:
                with ops_runtime.runtime_dir_override(runtime_override):
                    handled = self._ops_get(path, qs)
            else:
                handled = self._ops_get(path, qs)
            if handled:
                return

        if path == "/api/integrations/status":
            self._json(HTTPStatus.OK, integrations.status())
            return

        if path == "/api/telegram/status":
            self._json(HTTPStatus.OK, telegram_service.status())
            return

        if path == "/api/auth/users":
            try:
                out = account_auth.list_users(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"))
                for row in out.get("users") or []:
                    if row.get("is_owner"):
                        continue
                    try:
                        row["subscription"] = subscriptions.active_entitlement(row.get("user_id"))
                    except subscriptions.SubscriptionError:
                        row["subscription"] = {}
                self._json(HTTPStatus.OK, out)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc))
            return

        if path.startswith("/api/auth/users/"):
            uparts = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(uparts) == 4:  # GET /api/auth/users/<id> — full admin detail
                try:
                    actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                    detail = account_auth.user_detail(actor, uparts[3])
                    user = detail.get("user") or {}
                    target = user.get("user_id")
                    try:
                        subscription = subscriptions.active_entitlement(target)
                    except subscriptions.SubscriptionError:
                        subscription = {}
                    try:
                        entitlements = (subscriptions.entitlements_for_user(target) or {}).get("entitlements") or []
                    except subscriptions.SubscriptionError:
                        entitlements = []
                    perm = permissions.resolve(user, subscription)
                    detail["subscription"] = subscription
                    detail["entitlements"] = entitlements
                    detail["capabilities"] = perm["capabilities"]
                    detail["capability_catalog"] = permissions.capability_catalog()
                    detail["nt_connection"] = self._user_nt_info(target, bool(user.get("is_owner")))
                    detail["public_plans"] = subscriptions.list_plans().get("public_plans") or []
                    self._json(HTTPStatus.OK, detail)
                except account_auth.AccountAuthError as exc:
                    self._err(exc.status, str(exc))
                return
            self._err(HTTPStatus.NOT_FOUND, f"no auth route: {path}")
            return

        if path == "/api/auth/me":
            self._auth_me()
            return

        if path.startswith("/api/auth/avatar/"):
            self._serve_avatar(urllib.parse.unquote(path[len("/api/auth/avatar/"):]))
            return

        if path == "/api/billing/plans":
            self._json(HTTPStatus.OK, subscriptions.list_plans())
            return

        if path == "/api/billing/me":
            context = getattr(self, "_remote_context", None) or {}
            self._json(HTTPStatus.OK, subscriptions.entitlements_for_user(context.get("user_id")))
            return

        if path == "/api/billing/donate":
            self._json(HTTPStatus.OK, subscriptions.donation_options())
            return

        if path == "/api/owner/plans":
            try:
                self._json(HTTPStatus.OK, subscriptions.plan_matrix(
                    (getattr(self, "_remote_context", None) or {}).get("user_id")))
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/journal":
            raw_limit = (qs.get("limit") or ["200"])[0]
            self._json(HTTPStatus.OK, admin_journal.read_journal(
                category=(qs.get("category") or [""])[0],
                query=(qs.get("q") or [""])[0],
                limit=int(raw_limit) if str(raw_limit).isdigit() else 200,
                suspicious_only=(qs.get("suspicious") or [""])[0] in ("1", "true", "yes"),
            ))
            return

        if path == "/api/owner/payment":
            try:
                self._json(HTTPStatus.OK, subscriptions.get_payment_config(
                    (getattr(self, "_remote_context", None) or {}).get("user_id")))
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/paypal":
            try:
                self._json(HTTPStatus.OK, subscriptions.get_paypal_config(
                    (getattr(self, "_remote_context", None) or {}).get("user_id")))
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/payment-requests":
            try:
                out = subscriptions.list_payment_requests(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"),
                    status=(qs.get("status") or [""])[0])
                for row in out.get("requests") or []:
                    plan = subscriptions.PLANS.get(str(row.get("plan_id"))) or {}
                    row["plan_label"] = plan.get("label") or row.get("plan_id")
                    try:
                        who = account_auth.find_active_user(row.get("user_id")) or {}
                        row["user_label"] = (" ".join([
                            str(who.get("first_name") or ""), str(who.get("last_name") or "")]).strip()
                            or str(who.get("username") or ""))
                    except Exception:
                        row["user_label"] = ""
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/bridge/setup":
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, workspaces.bridge_setup(context.get("user_id")))
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/workspaces":
            context = getattr(self, "_remote_context", None) or {}
            workspace_context = context.get("workspace_context") or workspaces.context_for_user(
                context.get("user_id"), is_owner=bool(context.get("is_owner")),
                owner_id=str(os.environ.get(telegram_service.CHAT_ENV) or ""),
            )
            self._json(HTTPStatus.OK, workspace_context)
            return

        if path == "/api/bridge/connections":
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, workspaces.list_connections(context.get("user_id")))
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/vouchers":
            try:
                actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                out = subscriptions.list_vouchers(actor)
                # Enrich each redemption with the redeemer's label so the owner can
                # see who used an invite and jump straight to that account.
                for voucher in out.get("vouchers") or []:
                    for red in voucher.get("redemptions") or []:
                        try:
                            who = account_auth.find_active_user(red.get("user_id")) or {}
                        except Exception:
                            who = {}
                        red["user_label"] = (" ".join([
                            str(who.get("first_name") or ""), str(who.get("last_name") or "")]).strip()
                            or str(who.get("username") or "") or f"ID {red.get('user_id')}")
                        red["user_exists"] = bool(who)
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/telegram/remote/me":
            context = getattr(self, "_remote_context", None)
            if not context:
                self._err(HTTPStatus.BAD_REQUEST, "Этот endpoint предназначен для Telegram Mini App.")
                return
            self._json(HTTPStatus.OK, {
                "ok": True, "source": telegram_remote.SOURCE,
                "user_id": context.get("user_id"), "username": context.get("username"),
                "role": context.get("role"), "live_trading_allowed": False,
            })
            return

        if path == "/api/telegram/remote/access":
            self._json(HTTPStatus.OK, telegram_remote.admin_status())
            return

        if path == "/api/telegram/tunnel/status":
            try:
                self._json(HTTPStatus.OK, tunnel_manager.status(port=self.server.server_address[1]))
            except tunnel_manager.TunnelManagerError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/telegram/group":
            try:
                self._json(HTTPStatus.OK, telegram_service.group_status())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"telegram group status failed: {e}")
            return

        if path == "/api/topstep/status":
            self._json(HTTPStatus.OK, integrations.topstep_status())
            return

        if path == "/api/news":
            try:
                limit = int((qs.get("limit") or ["50"])[0])
            except ValueError:
                limit = 50
            self._json(HTTPStatus.OK, integrations.news(limit))
            return

        if path == "/api/news/live":
            try:
                max_age = int((qs.get("max_age_min") or ["60"])[0])
            except ValueError:
                max_age = 60
            try:
                limit = int((qs.get("limit") or ["40"])[0])
            except ValueError:
                limit = 40
            self._json(HTTPStatus.OK, integrations.live_news(max_age, limit))
            return

        if path == "/api/ai-lab/external-agents/status":
            self._json(HTTPStatus.OK, integrations.external_agents_status())
            return

        if path == "/api/ai-lab/cloud-agents/status":
            self._json(HTTPStatus.OK, ai_cloud_agents.status())
            return

        if path in {"/api/ai-agents", "/api/ai-agents/summary"}:
            payload = ai_agent_registry.summary()
            payload["routing"] = ai_agent_router.status()
            self._json(HTTPStatus.OK, payload)
            return

        if path == "/api/ai-agents/usage":
            try:
                limit = max(1, min(1000, int((qs.get("limit") or ["200"])[0])))
            except ValueError:
                limit = 200
            self._json(HTTPStatus.OK, {"usage": ai_agent_registry.usage_rows(limit=limit)})
            return

        if path.startswith("/api/ai-agents/"):
            agent_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            try:
                self._json(HTTPStatus.OK, {"agent": ai_agent_registry.get_agent(agent_id)})
            except ai_agent_registry.AgentRegistryError as exc:
                self._err(HTTPStatus.NOT_FOUND, str(exc))
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

        if path == "/api/governance/north-star":
            try:
                self._json(HTTPStatus.OK, governance.north_star_progress())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"north-star failed: {e}")
            return True

        if path == "/api/governance/summary":
            self._json(HTTPStatus.OK, {
                "owner": governance.PROJECT_OWNER,
                "documents": governance.list_documents(),
                "runtime_defaults": governance.runtime_defaults(),
                "consistency": governance.consistency_report(),
                "history": governance.read_change_log(80),
            })
            return True

        if path == "/api/governance/documents":
            self._json(HTTPStatus.OK, {
                "owner": governance.PROJECT_OWNER,
                "documents": governance.list_documents(),
            })
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

        if path.startswith("/api/ops/runtime/") and self._workspace_runtime_stubbed(path, qs):
            return True

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
            context = getattr(self, "_remote_context", None) or {}
            workspace_context = context.get("workspace_context") or {}
            active_workspace = workspace_context.get("active_workspace") if isinstance(workspace_context, dict) else {}
            if isinstance(active_workspace, dict) and active_workspace and not active_workspace.get("uses_owner_runtime"):
                self._json(HTTPStatus.OK, workspaces.workspace_account_history(
                    str(active_workspace.get("workspace_id") or ""), account, limit,
                ))
                return True
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
                if str((qs.get("desktop") or ["0"])[0]).lower() in {"1", "true", "yes"} and root not in _DESKTOP_INSTRUMENT_ROOTS:
                    continue
                root_map.setdefault(root, []).append(ins)
            result = []
            for root, contracts in sorted(root_map.items()):
                def _dl(c: dict) -> str:
                    return str(c.get("data_last") or "")
                contracts_sorted = sorted(contracts, key=_dl, reverse=True)
                # Front month = the most-recently-active *unexpired* contract.
                # Energy futures (and many others) expire during the preceding
                # calendar month, so a pure "expiry month >= now.month" check
                # wrongly keeps the expired contract for the whole calendar month.
                # Robust rule:
                # 1) among contracts with data in the last 30 days whose expiry
                #    month is still current/future, pick the freshest data_last;
                # 2) if only expired-month contracts are "live", prefer the
                #    nearest future expiry when the catalog has one;
                # 3) otherwise fall back to calendar-month proximity / freshest.
                now = datetime.now()
                def _days_since(c: dict) -> float:
                    raw = str(c.get("data_last") or "")
                    if not raw:
                        return float("inf")
                    try:
                        from datetime import datetime as _dt  # noqa: F811
                        return (now - _dt.strptime(raw[:10], "%Y-%m-%d")).days
                    except (ValueError, TypeError):
                        return float("inf")

                def _expiry_key(c: dict):
                    expiry = str(c.get("expiry") or "")
                    try:
                        month, year = expiry.split("-", 1)
                        return (2000 + int(year), int(month))
                    except (TypeError, ValueError):
                        return None

                future_contracts = []
                for contract in contracts:
                    key = _expiry_key(contract)
                    if key is not None and key >= (now.year, now.month):
                        future_contracts.append((key, contract))

                # Contracts with data within last 30 days are considered "live".
                live = [c for c in contracts if _days_since(c) <= 30]
                active = [c for c in live if (_expiry_key(c) or (0, 0)) >= (now.year, now.month)]
                def _front_rank(c: dict):
                    # Freshest data first; on a tie prefer the nearer expiry month.
                    key = _expiry_key(c) or (9999, 99)
                    return (_days_since(c), key)

                if active:
                    front = min(active, key=_front_rank)
                elif future_contracts:
                    # Prefer a still-listed future month over a recently-expired
                    # contract that still has bars within the 30-day window.
                    front = min(future_contracts, key=lambda item: item[0])[1]
                elif live:
                    front = min(live, key=_front_rank)
                else:
                    front = min(future_contracts, key=lambda item: item[0])[1] if future_contracts else (
                        contracts_sorted[0] if contracts_sorted else None)
                result.append({
                    "root": root,
                    "front_month": front,
                    "contracts": contracts_sorted,
                })
            self._json(HTTPStatus.OK, {"roots": result})
            return True

        if path == "/api/ops/runtime/price-alerts":
            market_data.evaluate_alerts()
            instrument = (qs.get("instrument") or [""])[0]
            include_inactive = str((qs.get("include_inactive") or ["1"])[0]).lower() not in {"0", "false", "no"}
            self._json(HTTPStatus.OK, market_data.list_alerts(
                instrument=instrument, include_inactive=include_inactive))
            return True

        if path == "/api/ops/runtime/chart-commands":
            status = (qs.get("status") or ["pending"])[0]
            self._json(HTTPStatus.OK, market_data.list_chart_commands(status=status))
            return True

        if path == "/api/ops/runtime/snapshots":
            pattern = qs.get("pattern")[0] if qs.get("pattern") else None
            favorites_only = str((qs.get("favorites") or ["0"])[0]).lower() in {"1", "true", "yes"}
            try:
                limit = int((qs.get("limit") or ["300"])[0])
            except ValueError:
                limit = 300
            self._json(HTTPStatus.OK, market_data.list_snapshots(
                pattern=pattern, favorites_only=favorites_only, limit=limit))
            return True

        if len(parts) == 5 and parts[:4] == ["api", "ops", "runtime", "snapshots"]:
            found = market_data.read_snapshot(parts[4])
            if not found:
                self._err(HTTPStatus.NOT_FOUND, "snapshot not found")
                return True
            data, mime = found
            self._bytes(HTTPStatus.OK, data, mime)
            return True

        if path == "/api/ops/runtime/bars":
            # Register a dynamic BarsRequest in the bridge, prefer its live
            # series and fall back to the newest real Strategy Analyzer artifact.
            instrument = (qs.get("instrument") or [""])[0]
            timeframe = (qs.get("timeframe") or [""])[0]
            try:
                limit = int((qs.get("limit") or ["1500"])[0])
            except ValueError:
                limit = 1500
            try:
                range_days = int((qs.get("range_days") or ["0"])[0])
            except ValueError:
                range_days = 0
            try:
                max_points = int((qs.get("max_points") or ["0"])[0])
            except ValueError:
                max_points = 0
            from_date = (qs.get("from") or [""])[0]
            to_date = (qs.get("to") or [""])[0]
            if not instrument:
                self._err(HTTPStatus.BAD_REQUEST, "instrument is required")
                return True
            try:
                context = getattr(self, "_remote_context", None) or {}
                payload = _market_bars_payload(
                    instrument, timeframe, limit, range_days, from_date, to_date,
                    max_points=max_points,
                    workspace_id=str(context.get("workspace_id") or ""),
                )
            except market_data.MarketDataError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return True
            market_data.evaluate_alerts()
            self._json(HTTPStatus.OK, payload)
            return True

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

        if path == "/api/ai-lab/domain-agents":
            self._json(HTTPStatus.OK, ai_domain_agents.list_personas())
            return True

        if path == "/api/ai-lab/accounting":
            period = (qs.get("period") or ["month"])[0]
            account = (qs.get("account") or [""])[0]
            from_date = (qs.get("from") or [None])[0]
            to_date = (qs.get("to") or [None])[0]
            try:
                self._json(HTTPStatus.OK, ai_domain_agents.accounting_snapshot(
                    period, account, from_date=from_date, to_date=to_date,
                ))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"accounting report failed: {e}")
            return True

        if path == "/api/ai-lab/strategy-analysis":
            period = (qs.get("period") or ["month"])[0]
            try:
                self._json(HTTPStatus.OK, ai_domain_agents.strategy_snapshot(period))
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"strategy analysis failed: {e}")
            return True

        if path == "/api/ai-lab/news-analysis":
            try:
                limit = int((qs.get("limit") or ["40"])[0])
                self._json(HTTPStatus.OK, ai_news_agent.snapshot(limit=limit))
            except ValueError:
                self._err(HTTPStatus.BAD_REQUEST, "limit must be an integer")
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"news analysis failed: {e}")
            return True

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

        if path in {"/api/ai-lab/chief-agent", "/api/ai-lab/orchestrator"}:
            try:
                self._json(HTTPStatus.OK, ai_chief_agent.status())
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"orchestrator status failed: {e}")
            return True

        if path == "/api/ai-lab/orchestrator/conversations":
            try:
                scope = self._ai_conversation_scope()
                self._json(HTTPStatus.OK, {"ok": True, "conversations": ai_chief_agent.list_conversations(scope=scope)})
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"conversations list failed: {e}")
            return True

        # /api/ai-lab/orchestrator/conversations/{id}
        if sub == "orchestrator" and len(parts) == 5 and parts[3] == "conversations":
            conversation_id = parts[4]
            try:
                limit = int((qs.get("limit") or ["200"])[0])
            except ValueError:
                limit = 200
            try:
                scope = self._ai_conversation_scope()
                self._json(HTTPStatus.OK, {
                    "ok": True,
                    "conversation_id": conversation_id,
                    "messages": ai_chief_agent.conversation_messages(conversation_id, limit=limit, scope=scope),
                })
            except Exception as e:
                self._err(HTTPStatus.INTERNAL_SERVER_ERROR, f"conversation load failed: {e}")
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

    def _sse_write(self, event: str, data: Dict[str, Any]) -> bool:
        """Write one Server-Sent Event; return False if the client disconnected."""
        try:
            payload = json.dumps(self._json_safe(data), ensure_ascii=False, allow_nan=False)
            chunk = f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
            self.wfile.write(chunk)
            self.wfile.flush()
            return True
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return False
            raise

    def _sse_keepalive(self) -> bool:
        try:
            self.wfile.write(b": keepalive\n\n")
            self.wfile.flush()
            return True
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return False
            raise

    def _ai_lab_orchestrator_stream(self, body: Dict[str, Any], *, scope: Dict[str, Any]) -> None:
        """Stream the orchestrator reply as Server-Sent Events.

        A live "thinking" channel (the provider's native reasoning) is streamed
        first, then the final answer. The heavy work — including allowlisted
        actions — runs in a worker thread through the SAME handle_message path as
        the synchronous endpoint, so behaviour and safety are identical; only the
        transport differs. Telegram still receives only the final reply (the
        thinking channel is never mirrored). No extra model call is made: the
        reasoning shown is the one the provider already generated for this turn.
        """
        message = str(body.get("message") or body.get("text") or "")
        conversation_id = str(body.get("conversation_id") or "default")
        agent = str(body.get("agent") or "")

        events: "queue.Queue[tuple]" = queue.Queue()

        def on_thinking(delta: str) -> None:
            events.put(("thinking", str(delta or "")))

        def worker() -> None:
            try:
                out = ai_chief_agent.handle_message(
                    message, source="app", mirror_to_telegram=True,
                    conversation_id=conversation_id, agent=agent,
                    on_thinking=on_thinking, scope=scope,
                )
                events.put(("result", out))
            except ai_chief_agent.ChiefAgentError as exc:
                events.put(("error", str(exc)))
            except Exception as exc:  # defensive: a failure must not hang the stream
                events.put(("error", f"orchestrator error: {exc}"))

        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
        except OSError as e:
            if self._is_client_disconnect_error(e):
                return
            raise

        threading.Thread(target=worker, name="orchestrator-stream", daemon=True).start()

        if not self._sse_write("thinking_start", {"conversation_id": conversation_id}):
            return

        # Fallback wait statuses for models that expose no native reasoning.
        wait_statuses = ["Выбираю модель…", "Формирую план…", "Выполняю действие…", "Собираю ответ…"]
        saw_thinking = False
        status_idx = 0
        started_at = time.time()
        last_status = 0.0
        max_seconds = 600.0
        while True:
            if time.time() - started_at > max_seconds:
                self._sse_write("error", {"error": "orchestrator stream timeout"})
                self._sse_write("done", {"ok": False})
                return
            try:
                kind, payload = events.get(timeout=1.0)
            except queue.Empty:
                now = time.time()
                if not saw_thinking and now - last_status >= 1.5:
                    last_status = now
                    if not self._sse_write("status", {"text": wait_statuses[status_idx % len(wait_statuses)]}):
                        return
                    status_idx += 1
                elif not self._sse_keepalive():
                    return
                continue
            if kind == "thinking":
                saw_thinking = True
                if not self._sse_write("thinking_delta", {"text": payload}):
                    return
            elif kind == "result":
                out = payload if isinstance(payload, dict) else {}
                msg = out.get("message") if isinstance(out.get("message"), dict) else {}
                self._sse_write("thinking_done", {"text": str(out.get("thinking") or "")})
                self._sse_write("final", {
                    "reply": str(out.get("reply") or ""),
                    "conversation_id": str(out.get("conversation_id") or conversation_id),
                    "model": out.get("model"),
                    "provider": out.get("provider"),
                    "agent": out.get("agent"),
                    "doubts": out.get("doubts") or [],
                    "message_id": str(msg.get("message_id") or ""),
                    "timestamp_utc": str(msg.get("timestamp_utc") or ""),
                })
                self._sse_write("done", {"ok": True})
                return
            elif kind == "error":
                self._sse_write("error", {"error": str(payload)})
                self._sse_write("done", {"ok": False})
                return

    def _ai_lab_post(self, path: str, body: Dict[str, Any]) -> None:
        if path.startswith("/api/ai-lab/cloud-agents/"):
            try:
                if path == "/api/ai-lab/cloud-agents/settings":
                    out = ai_cloud_agents.update_settings(body.get("settings") or body)
                elif path == "/api/ai-lab/cloud-agents/provider-key":
                    out = ai_cloud_agents.configure_provider(
                        str(body.get("provider") or ""), str(body.get("api_key") or "")
                    )
                elif path == "/api/ai-lab/cloud-agents/provider-test":
                    out = ai_cloud_agents.recheck_provider(str(body.get("provider") or ""))
                elif path == "/api/ai-lab/cloud-agents/provider-disconnect":
                    out = ai_cloud_agents.disconnect_provider(str(body.get("provider") or ""))
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no cloud-agents route: {path}")
                    return
            except ai_cloud_agents.CloudAgentsError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._json(HTTPStatus.OK, out)
            return

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

        if path == "/api/ai-lab/orchestrator/message/stream":
            self._ai_lab_orchestrator_stream(body, scope=self._ai_conversation_scope())
            return

        if path == "/api/ai-lab/orchestrator/message":
            try:
                scope = self._ai_conversation_scope()
                out = ai_chief_agent.handle_message(
                    str(body.get("message") or body.get("text") or ""),
                    source="app", mirror_to_telegram=True,
                    conversation_id=str(body.get("conversation_id") or "default"),
                    agent=str(body.get("agent") or ""), scope=scope,
                )
                self._json(HTTPStatus.OK, out)
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path.startswith("/api/ai-lab/orchestrator/message/") and path.endswith("/rating"):
            try:
                scope = self._ai_conversation_scope()
                parts = path.strip("/").split("/")
                message_id = urllib.parse.unquote(parts[-2]) if len(parts) >= 6 else ""
                out = ai_chief_agent.rate_message(
                    str(body.get("conversation_id") or "default"),
                    message_id,
                    body.get("rating"),
                    str(body.get("feedback_comment") or body.get("comment") or ""),
                    source=str(body.get("feedback_source") or "owner"),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, out)
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/domain-agents/message":
            try:
                out = ai_domain_agents.answer(
                    str(body.get("agent_id") or ""), str(body.get("message") or body.get("text") or ""),
                    period=str(body.get("period") or "month"), account=str(body.get("account") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except (ValueError, ai_agent_router.AgentRouterError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations":
            try:
                scope = self._ai_conversation_scope()
                conv = ai_chief_agent.create_conversation(str(body.get("title") or ""), scope=scope)
                self._json(HTTPStatus.OK, {"ok": True, "conversation": conv})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/chart-task":
            try:
                scope = self._ai_conversation_scope()
                out = ai_chief_agent.announce_chart_task(
                    conversation_id=str(body.get("conversation_id") or "default"),
                    instruction=str(body.get("instruction") or body.get("message") or ""),
                    agent_id=str(body.get("agent_id") or "ivan"),
                    instrument=str(body.get("instrument") or ""),
                    price=body.get("price"),
                    drawing_type=str(body.get("drawing_type") or body.get("type") or "line"),
                    label=str(body.get("label") or ""),
                    delay_seconds=int(body.get("delay_seconds") or 0),
                    duration_minutes=int(body.get("duration_minutes") or 0),
                    report_mode=str(body.get("report_mode") or "touch"),
                    action=str(body.get("action") or "snapshot"),
                    mirror_to_telegram=bool(body.get("mirror_to_telegram", True)),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, out)
            except (ai_chief_agent.ChiefAgentError, ValueError, TypeError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations/rename":
            try:
                scope = self._ai_conversation_scope()
                conv = ai_chief_agent.rename_conversation(
                    str(body.get("conversation_id") or ""), str(body.get("title") or ""),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, {"ok": True, "conversation": conv})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations/pin":
            try:
                scope = self._ai_conversation_scope()
                conv = ai_chief_agent.pin_conversation(
                    str(body.get("conversation_id") or ""), bool(body.get("pinned", True)),
                    scope=scope,
                )
                self._json(HTTPStatus.OK, {"ok": True, "conversation": conv})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations/state":
            try:
                scope = self._ai_conversation_scope()
                state = str(body.get("state") or "").strip().lower()
                if state not in {"closed", "open"}:
                    raise ai_chief_agent.ChiefAgentError("state должен быть open или closed.")
                conv = ai_chief_agent.set_conversation_closed(
                    str(body.get("conversation_id") or "default"), state == "closed",
                    scope=scope,
                )
                self._json(HTTPStatus.OK, {"ok": True, "conversation": conv})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/orchestrator/conversations/delete":
            try:
                scope = self._ai_conversation_scope()
                out = ai_chief_agent.delete_conversation(str(body.get("conversation_id") or ""), scope=scope)
                self._json(HTTPStatus.OK, out)
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/mission":
            try:
                self._json(HTTPStatus.OK, {"ok": True, "mission": ai_chief_agent.start_mission(body)})
            except (ValueError, TypeError, ai_chief_agent.ChiefAgentError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/mission/state":
            try:
                self._json(HTTPStatus.OK, {"ok": True, "mission": ai_chief_agent.set_mission_state(str(body.get("action") or ""))})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/tasks":
            try:
                self._json(HTTPStatus.OK, {"ok": True, "task": ai_chief_agent.add_task(body)})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/notes":
            try:
                note = ai_chief_agent.add_note(str(body.get("text") or ""), str(body.get("priority") or "normal"))
                self._json(HTTPStatus.OK, {"ok": True, "note": note})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/audit":
            try:
                report = ai_chief_agent.audit_recent_backtests(
                    use_llm=bool(body.get("use_llm", True)),
                    send_telegram=bool(body.get("send_telegram", False)),
                )
                self._json(HTTPStatus.OK, {"ok": True, "report": report})
            except (ai_chief_agent.ChiefAgentError, ai_agent_router.AgentRouterError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/proposals":
            try:
                proposal = ai_chief_agent.propose_action(
                    str(body.get("action") or ""),
                    body.get("payload") if isinstance(body.get("payload"), dict) else {},
                    str(body.get("reason") or ""),
                )
                self._json(HTTPStatus.OK, {"ok": True, "proposal": proposal})
            except ai_chief_agent.ChiefAgentError as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
            return

        if path == "/api/ai-lab/chief-agent/proposals/decision":
            try:
                proposal = ai_chief_agent.decide_proposal(
                    str(body.get("proposal_id") or ""), str(body.get("decision") or "")
                )
                self._json(HTTPStatus.OK, {"ok": True, "proposal": proposal})
            except (ai_chief_agent.ChiefAgentError, ops.OpsError) as e:
                self._err(HTTPStatus.BAD_REQUEST, str(e))
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
        if path == "/api/ops/runtime/bars/batch":
            rows = body.get("requests") if isinstance(body.get("requests"), list) else []
            if len(rows) > 64:
                self._err(HTTPStatus.BAD_REQUEST, "Не более 64 графиков в одном пакете."); return
            result = []
            try:
                market_data.register_requests(row for row in rows if isinstance(row, dict))
                # Read the bridge snapshot and alerts ONCE for the whole batch —
                # a 64-chart grid must not re-parse market_bars.json/price_alerts.json
                # once per instrument on every poll tick.
                snapshot_index = market_data.read_snapshot_index()
                alerts_index = market_data.read_alerts_index()
                context = getattr(self, "_remote_context", None) or {}
                workspace_id = str(context.get("workspace_id") or "")
                batch_cache: Dict[Tuple[str, str, int, int, str, str, int], Dict[str, Any]] = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    req_key = (
                        str(row.get("instrument") or ""),
                        str(row.get("timeframe") or "5m"),
                        int(row.get("limit") or 1500),
                        int(row.get("range_days") or 0),
                        str(row.get("from") or ""),
                        str(row.get("to") or ""),
                        int(row.get("max_points") or 0),
                    )
                    payload = batch_cache.get(req_key)
                    if payload is None:
                        payload = _market_bars_payload(
                            req_key[0], req_key[1], req_key[2], req_key[3], req_key[4], req_key[5],
                            register=False, snapshot_index=snapshot_index, alerts_index=alerts_index,
                            max_points=req_key[6], workspace_id=workspace_id,
                        )
                        batch_cache[req_key] = payload
                    result.append(payload)
                market_data.evaluate_alerts()
            except (market_data.MarketDataError, TypeError, ValueError) as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc)); return
            self._json(HTTPStatus.OK, {"series": result}); return
        if path == "/api/ops/runtime/price-alerts":
            try:
                self._json(HTTPStatus.OK, market_data.create_alert(body)); return
            except market_data.MarketDataError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc)); return
        if path == "/api/ops/runtime/chart-commands/ack":
            out = market_data.ack_chart_command(
                str(body.get("id") or ""),
                status=str(body.get("status") or "done"),
                result=body.get("result") if isinstance(body.get("result"), dict) else None,
            )
            self._json(HTTPStatus.OK, out); return
        if path == "/api/ops/runtime/snapshots/update":
            out = market_data.update_snapshot(
                str(body.get("id") or ""),
                favorite=body.get("favorite") if isinstance(body.get("favorite"), bool) else None,
                pattern=body.get("pattern") if body.get("pattern") is not None else None,
                caption=body.get("caption") if body.get("caption") is not None else None,
            )
            self._json(HTTPStatus.OK, out); return
        if path == "/api/ops/runtime/snapshots/clear":
            keep_favorites = bool(body.get("keep_favorites", True))
            self._json(HTTPStatus.OK, market_data.clear_snapshots(keep_favorites=keep_favorites)); return
        if path == "/api/ops/runtime/chart-snapshot":
            saved = None
            if str(body.get("image") or "").strip():
                try:
                    saved = market_data.save_snapshot(body.get("image"), meta={
                        "instrument": str(body.get("instrument") or ""),
                        "timeframe": str(body.get("timeframe") or ""),
                        "outcome": str(body.get("outcome") or ""),
                    })
                except market_data.MarketDataError as exc:
                    self._err(HTTPStatus.BAD_REQUEST, str(exc)); return
            conversation_id = str(body.get("conversation_id") or "").strip()
            report = None
            if conversation_id:
                text = str(body.get("text") or "Снимок графика.").strip()[:2000]
                try:
                    scope = self._ai_conversation_scope()
                    report = ai_chief_agent.report_chart_snapshot(
                        conversation_id=conversation_id, text=text,
                        image_url=(saved or {}).get("url") or "",
                        image_file=(saved or {}).get("file") or "",
                        caption=str(body.get("caption") or "")[:400],
                        mirror_to_telegram=bool(body.get("mirror_to_telegram", True)),
                        scope=scope,
                    )
                except Exception as exc:  # pragma: no cover - reporting is best-effort
                    report = {"ok": False, "error": str(exc)[:300]}
            self._json(HTTPStatus.OK, {"ok": True, "snapshot": saved, "report": report}); return
        # /api/ops/live/unlock-request
        if path == "/api/ops/live/unlock-request":
            out = ops.request_live_unlock(reason=str(body.get("reason") or ""))
            self._json(HTTPStatus.FORBIDDEN, out)
            return
        # /api/ops/runtime/command  (paper/demo/playback runtime command queue)
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
                    connection_name=str(body.get("connection_name") or ""),
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

        if not self._authorize_api(path):
            return

        is_del_job   = (len(parts) == 3 and parts[0] == "api"
                        and parts[1] == "jobs")
        is_del_batch = (len(parts) == 3 and parts[0] == "api"
                        and parts[1] == "batches")
        is_del_favorite = (len(parts) == 4 and parts[0] == "api"
                           and parts[1] == "report-favorites")
        is_del_price_alert = (len(parts) == 5 and parts[:4] ==
                              ["api", "ops", "runtime", "price-alerts"])
        is_del_snapshot = (len(parts) == 5 and parts[:4] ==
                           ["api", "ops", "runtime", "snapshots"])

        if not (is_del_job or is_del_batch or is_del_favorite or is_del_price_alert or is_del_snapshot):
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

        if is_del_price_alert:
            try:
                out = market_data.delete_alert(urllib.parse.unquote(parts[4]))
            except market_data.MarketDataError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc)); return
            self._json(HTTPStatus.OK if out.get("deleted") else HTTPStatus.NOT_FOUND, out)
            return

        if is_del_snapshot:
            out = market_data.delete_snapshot(urllib.parse.unquote(parts[4]))
            self._json(HTTPStatus.OK if out.get("deleted") else HTTPStatus.NOT_FOUND, out)
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

        if path in {"/api/auth/login/start", "/api/auth/login/status", "/api/auth/profile"}:
            self._auth_public_post(path)
            return

        if path == "/api/auth/miniapp/register":
            # Public: register/activate straight from a verified Telegram Mini App
            # identity (initData), no bot round-trip. initData HMAC is the auth.
            self._miniapp_register()
            return

        # PayPal webhook is a PUBLIC endpoint (PayPal cannot pass Telegram auth).
        # It is authenticated by verifying the PayPal signature instead.
        if path == "/api/billing/paypal/webhook":
            self._paypal_webhook()
            return

        if not self._authorize_api(path):
            return

        if path == "/api/auth/logout":
            if not self._check_local_post():
                return
            account_auth.revoke_session(self._cookie_value(account_auth.SESSION_COOKIE))
            self._clear_session_cookie()
            self._json(HTTPStatus.OK, {"ok": True})
            return

        if path == "/api/worker/jobs" or (
            path.startswith("/api/worker/jobs/") and path.endswith("/cancel")
        ):
            if not self._check_local_post():
                return
            context = getattr(self, "_remote_context", None) or {}
            if not context.get("is_owner"):
                self._err(HTTPStatus.FORBIDDEN, "Это действие разрешено только владельцу.")
                return
            body = self._read_body()
            if body is None:
                return
            if path == "/api/worker/jobs":
                kind = str(body.get("kind") or "").strip()
                if kind not in {"durable_sweep", "telemetry_index"}:
                    self._err(HTTPStatus.BAD_REQUEST, "unsupported worker job kind")
                    return
                try:
                    out = local_worker.enqueue(
                        kind,
                        body.get("payload") if isinstance(body.get("payload"), dict) else {},
                        priority=int(body.get("priority") or 100),
                        max_attempts=int(body.get("max_attempts") or 1),
                        timeout_sec=int(body.get("timeout_sec") or 300),
                        user_id=context.get("user_id") or "",
                        workspace_id=str((context.get("active_workspace") or {}).get("workspace_id") or ""),
                    )
                    self._json(HTTPStatus.ACCEPTED, {"ok": True, "job": out})
                except (TypeError, ValueError) as exc:
                    self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            parts_worker = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(parts_worker) != 5:
                self._err(HTTPStatus.NOT_FOUND, f"no worker route: {path}")
                return
            self._json(HTTPStatus.OK, local_worker.cancel(parts_worker[3]))
            return

        if path.startswith("/api/auth/users/"):
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            parts_auth = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(parts_auth) != 5:
                self._err(HTTPStatus.NOT_FOUND, f"no auth route: {path}"); return
            try:
                actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
                if parts_auth[4] == "role":
                    out = account_auth.update_user(actor, parts_auth[3], role=str(body.get("role") or ""))
                elif parts_auth[4] == "revoke":
                    out = account_auth.update_user(actor, parts_auth[3], revoke=True)
                elif parts_auth[4] == "features":
                    out = account_auth.set_user_feature(actor, parts_auth[3], str(body.get("feature") or ""), bool(body.get("enabled")))
                elif parts_auth[4] == "permission":
                    out = account_auth.set_user_permission(actor, parts_auth[3], str(body.get("capability") or ""), body.get("enabled"))
                elif parts_auth[4] == "status":
                    out = account_auth.set_user_status(actor, parts_auth[3], str(body.get("status") or ""))
                elif parts_auth[4] == "sessions":
                    out = account_auth.revoke_user_sessions(
                        actor,
                        parts_auth[3],
                        session_id=str(body.get("session_id") or ""),
                        device_id=str(body.get("device_id") or ""),
                        all_sessions=bool(body.get("all_sessions")),
                    )
                elif parts_auth[4] == "delete":
                    out = account_auth.delete_user(actor, parts_auth[3])
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no auth route: {path}"); return
                self._json(HTTPStatus.OK, out)
            except account_auth.AccountAuthError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/auth/avatar/refresh":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            self._refresh_avatar()
            return

        if path in _BILLING_PROMO_POSTS:
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            user_id = context.get("user_id")
            account = account_auth.find_active_user(user_id) or {}
            email = str(body.get("email") or account.get("email") or "")
            requested_plan = str(body.get("requested_plan_id") or body.get("plan_id") or "")
            try:
                if path == "/api/billing/promo/preview":
                    out = subscriptions.preview_voucher(
                        body.get("code"), user_id=user_id, email=email,
                        requested_plan_id=requested_plan,
                    )
                else:
                    out = subscriptions.redeem_voucher(
                        body.get("code"), user_id=user_id, email=email,
                        requested_plan_id=requested_plan,
                        workspace_id=str(body.get("workspace_id") or ""),
                    )
                    entitlement = out.get("entitlement") if isinstance(out, dict) else {}
                    plan = entitlement.get("plan") if isinstance(entitlement, dict) and isinstance(entitlement.get("plan"), dict) else {}
                    features = plan.get("features") if isinstance(plan.get("features"), dict) else {}
                    if features.get("personal_nt") and not out.get("checkout_required"):
                        out["personal_workspace"] = workspaces.ensure_personal_workspace(
                            user_id, entitlement_id=str(entitlement.get("entitlement_id") or ""), require_entitlement=False,
                        )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/workspaces/select":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, workspaces.select_workspace(context.get("user_id"), body.get("workspace_id")))
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/workspaces/personal":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = workspaces.ensure_personal_workspace(
                    context.get("user_id"), display_name=str(body.get("display_name") or ""),
                    require_entitlement=not bool(context.get("is_owner")),
                )
                self._json(HTTPStatus.OK, {"ok": True, "workspace": out})
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/bridge/pair/start":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = workspaces.start_bridge_pairing(
                    context.get("user_id"), workspace_id=str(body.get("workspace_id") or ""),
                    machine_label=str(body.get("machine_label") or ""),
                )
                self._json(HTTPStatus.OK, out)
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/bridge/pair/complete":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = workspaces.complete_bridge_pairing(
                    context.get("user_id"), code=body.get("code"), device_id=str(body.get("device_id") or ""),
                    bridge_instance_id=str(body.get("bridge_instance_id") or ""),
                    machine_label=str(body.get("machine_label") or ""), capabilities=body.get("capabilities") or [],
                )
                self._json(HTTPStatus.OK, out)
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path.startswith("/api/bridge/connections/"):
            if not self._check_local_post():
                return
            parts_bridge = [urllib.parse.unquote(p) for p in path.split("/") if p]
            if len(parts_bridge) != 5 or parts_bridge[4] != "revoke":
                self._err(HTTPStatus.NOT_FOUND, f"no bridge route: {path}"); return
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, workspaces.revoke_connection(context.get("user_id"), parts_bridge[3]))
            except workspaces.WorkspaceError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/vouchers":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.create_voucher(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"), body,
                )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/invites":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                bot_username = str(telegram_service.load_settings().get("bot_username") or "")
                try:
                    public_url = str(telegram_remote.admin_status().get("public_url") or "")
                except Exception:
                    public_url = ""
                out = subscriptions.create_invite(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"), body,
                    bot_username=bot_username, public_url=public_url,
                )
                out["render"] = self._render_invite(out)
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path.startswith("/api/owner/invites/"):
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            inv_parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
            actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
            # /api/owner/invites/send            -> 4 parts, [3]=="send"
            # /api/owner/invites/<id>/status     -> 5 parts, [3]=id, [4]=action
            # /api/owner/invites/<id>/delete     -> 5 parts, [3]=id, [4]=action
            try:
                if len(inv_parts) == 4 and inv_parts[3] == "send":
                    out = self._send_invite(body)
                elif len(inv_parts) == 5 and inv_parts[4] == "status":
                    out = subscriptions.set_voucher_status(actor, inv_parts[3], str(body.get("status") or ""))
                elif len(inv_parts) == 5 and inv_parts[4] == "delete":
                    out = subscriptions.delete_voucher(actor, inv_parts[3])
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no invite route: {path}"); return
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/plans/feature":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.set_plan_feature(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"),
                    str(body.get("plan_id") or ""), str(body.get("feature") or ""), bool(body.get("enabled")),
                )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/payment":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.set_payment_config(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"), body,
                )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/paypal":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.set_paypal_config(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"), body,
                )
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/paypal/plans":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = paypal.ensure_plans((getattr(self, "_remote_context", None) or {}).get("user_id"))
                self._json(HTTPStatus.OK, out)
            except (paypal.PayPalError, subscriptions.SubscriptionError) as exc:
                self._err(getattr(exc, "status", 400), str(exc))
            return

        if path == "/api/billing/subscribe":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            base = self.headers.get("Origin") or ("http://" + (self.headers.get("Host") or "127.0.0.1"))
            base = base.rstrip("/")
            try:
                out = paypal.create_subscription(
                    context.get("user_id"), str(body.get("plan_id") or ""),
                    return_url=f"{base}/ui/?paypal=success",
                    cancel_url=f"{base}/ui/?paypal=cancel",
                )
                self._json(HTTPStatus.OK, out)
            except paypal.PayPalError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/billing/checkout":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                self._json(HTTPStatus.OK, subscriptions.manual_checkout(
                    context.get("user_id"), str(body.get("plan_id") or "")))
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/billing/payment-request":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            context = getattr(self, "_remote_context", None) or {}
            try:
                out = subscriptions.create_payment_request(
                    context.get("user_id"), str(body.get("plan_id") or ""), note=str(body.get("note") or ""))
                self._notify_owner_payment_request(context, out.get("request") or {})
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/grant":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            actor = (getattr(self, "_remote_context", None) or {}).get("user_id")
            try:
                if str(body.get("plan_id") or "").strip():
                    out = subscriptions.grant_plan(
                        actor, body.get("user_id"), str(body.get("plan_id") or ""),
                        duration_days=body.get("duration_days"), note=str(body.get("note") or ""))
                else:
                    out = subscriptions.clear_user_plan(actor, body.get("user_id"))
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

        if path == "/api/owner/payment-requests/resolve":
            if not self._check_local_post():
                return
            body = self._read_body()
            if body is None:
                return
            try:
                out = subscriptions.resolve_payment_request(
                    (getattr(self, "_remote_context", None) or {}).get("user_id"),
                    str(body.get("request_id") or ""), approve=bool(body.get("approve")),
                    duration_days=body.get("duration_days"))
                self._json(HTTPStatus.OK, out)
            except subscriptions.SubscriptionError as exc:
                self._err(exc.status, str(exc))
            return

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
        is_telegram = path.startswith("/api/telegram/")
        is_ai_agents = path == "/api/ai-agents" or path.startswith("/api/ai-agents/")

        if not (path in ("/api/jobs", "/api/batches")
                or is_cancel_job or is_cancel_batch
                or is_catalog_refresh or is_margins_refresh
                or is_server_restart
                or is_ops or is_profiles or is_report_favorites
                or is_ai_lab or is_governance or is_portfolio or is_telegram or is_ai_agents):
            self._err(HTTPStatus.NOT_FOUND, f"no route: {path}")
            return

        if not self._check_local_post():
            return  # _check_local_post already wrote an error

        if is_telegram:
            body = self._read_body()
            if body is None:
                return
            try:
                if path == "/api/telegram/token":
                    out = telegram_service.configure_token(str(body.get("token") or ""))
                elif path == "/api/telegram/pair/start":
                    out = telegram_service.start_pairing()
                elif path == "/api/telegram/pair/complete":
                    out = telegram_service.complete_pairing()
                elif path == "/api/telegram/settings":
                    out = telegram_service.update_settings(body.get("settings") or body)
                elif path == "/api/telegram/remote/settings":
                    out = telegram_remote.update_settings(body.get("settings") or body)
                elif path == "/api/telegram/remote/pair/start":
                    out = telegram_remote.start_pairing(
                        bot_username=str(telegram_service.load_settings().get("bot_username") or ""),
                        role=str(body.get("role") or "read_only"),
                        expected_user_id=body.get("expected_user_id") or 0,
                        require_phone=bool(body.get("require_phone", True)),
                    )
                elif path == "/api/telegram/remote/menu-button":
                    out = telegram_remote.configure_menu_button(telegram_service._api_call)
                elif path == "/api/telegram/tunnel/launch":
                    out = tunnel_manager.launch(
                        port=self.server.server_address[1],
                        enable_remote=bool(body.get("enable_remote", True)),
                    )
                elif path == "/api/telegram/tunnel/start":
                    out = tunnel_manager.start(port=self.server.server_address[1])
                elif path == "/api/telegram/tunnel/stop":
                    out = tunnel_manager.stop()
                elif path.startswith("/api/telegram/remote/users/"):
                    remote_parts = [urllib.parse.unquote(p) for p in path.split("/") if p]
                    if len(remote_parts) != 6:
                        self._err(HTTPStatus.NOT_FOUND, f"no Telegram route: {path}")
                        return
                    user_id, action = remote_parts[4], remote_parts[5]
                    if action == "role":
                        out = telegram_remote.set_user_role(user_id, str(body.get("role") or ""))
                    elif action == "revoke":
                        out = telegram_remote.revoke_user(user_id)
                    else:
                        self._err(HTTPStatus.NOT_FOUND, f"no Telegram route: {path}")
                        return
                elif path == "/api/telegram/test":
                    out = telegram_service.send_test()
                elif path == "/api/telegram/group":
                    out = telegram_service.configure_group(str(body.get("group_id") or ""))
                elif path == "/api/telegram/group/disconnect":
                    out = telegram_service.disconnect_group()
                elif path == "/api/telegram/disconnect":
                    if account_auth.auth_required():
                        raise telegram_service.TelegramServiceError(
                            "Нельзя отключить единственный способ входа, пока обязательна Telegram-авторизация."
                        )
                    out = telegram_service.disconnect()
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no Telegram route: {path}")
                    return
            except telegram_service.TelegramServiceError as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except telegram_remote.RemoteAccessError as exc:
                self._err(exc.status, str(exc))
                return
            except tunnel_manager.TunnelManagerError as exc:
                self._err(exc.status, str(exc))
                return
            self._json(HTTPStatus.OK, out)
            return

        if is_ai_agents:
            body = self._read_body()
            if body is None:
                return
            parts = [urllib.parse.unquote(part) for part in path.split("/") if part]
            try:
                if path == "/api/ai-agents":
                    out = {"agent": ai_agent_registry.create_agent(body.get("agent") or body)}
                elif len(parts) == 3 and parts[:2] == ["api", "ai-agents"]:
                    out = {"agent": ai_agent_registry.update_agent(parts[2], body.get("agent") or body)}
                elif len(parts) == 4 and parts[:2] == ["api", "ai-agents"] and parts[3] == "toggle":
                    out = {"agent": ai_agent_registry.set_enabled(parts[2], body.get("enabled"), reason="disabled_by_operator")}
                elif len(parts) == 4 and parts[:2] == ["api", "ai-agents"] and parts[3] == "test":
                    out = ai_universal_llm.test_connection(parts[2], str(body.get("prompt") or ""))
                elif len(parts) == 4 and parts[:2] == ["api", "ai-agents"] and parts[3] == "sync-balance":
                    out = {"agent": ai_universal_llm.sync_credit_balance(parts[2])}
                elif len(parts) == 4 and parts[:2] == ["api", "ai-agents"] and parts[3] == "delete":
                    out = ai_agent_registry.delete_agent(parts[2])
                else:
                    self._err(HTTPStatus.NOT_FOUND, f"no AI agents route: {path}")
                    return
            except (ai_agent_registry.AgentRegistryError,
                    ai_universal_llm.UniversalLLMError,
                    _secure_store.SecureStoreError) as exc:
                self._err(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._json(HTTPStatus.OK, out)
            return

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
                context = getattr(self, "_remote_context", None) or {}
                workspace_context = context.get("workspace_context") or {}
                active_workspace = workspace_context.get("active_workspace") if isinstance(workspace_context, dict) else {}
                if isinstance(active_workspace, dict) and active_workspace and not active_workspace.get("uses_owner_runtime"):
                    workspace_id = str(active_workspace.get("workspace_id") or "")
                    if path == "/api/ops/runtime/account-history/classify":
                        out = workspaces.workspace_classify_event(
                            workspace_id, str(body.get("account_name") or ""), str(body.get("event_id") or ""),
                            str(body.get("kind") or ""), str(body.get("actor") or "ui"), str(body.get("note") or ""),
                        )
                    elif path == "/api/ops/runtime/account-history/events":
                        out = workspaces.workspace_add_event(
                            workspace_id, str(body.get("account_name") or ""), str(body.get("kind") or ""), body.get("amount"),
                            str(body.get("actor") or "ui"), str(body.get("note") or ""), body.get("at_utc"),
                            str(body.get("source") or "manual"), str(body.get("source_id") or ""),
                        )
                    elif path == "/api/ops/runtime/account-history/import":
                        out = workspaces.workspace_import_events(
                            workspace_id, str(body.get("account_name") or ""), body.get("rows") or [],
                            str(body.get("actor") or "ui"), str(body.get("source") or "broker_statement"),
                        )
                    else:
                        self._err(HTTPStatus.NOT_FOUND, f"no account-history route: {path}"); return
                    self._json(HTTPStatus.OK, out); return
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
    try:
        news_refresh.start_background_refresher()
        print("[nta-backend] news refresher started (live every 15 min)")
    except Exception as e:
        print(f"[nta-backend] news refresher NOT started: {e}")
    try:
        local_worker.start_background_worker(interval_sec=2.0)
        print("[nta-backend] local worker process started")
    except Exception as e:
        print(f"[nta-backend] local worker process NOT started: {e}")
    try:
        telegram_service.start_background_notifier(interval_sec=30)
        print("[nta-backend] Telegram notifier started (every 30 sec)")
    except Exception as e:
        print(f"[nta-backend] Telegram notifier NOT started: {e}")
    try:
        ai_chief_agent.start_background_worker(interval_sec=30)
        print("[nta-backend] StratForge Orchestrator started (every 30 sec)")
    except Exception as e:
        print(f"[nta-backend] StratForge Orchestrator NOT started: {e}")
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[nta-backend] shutting down")
    finally:
        ai_chief_agent.stop_background_worker()
        local_worker.stop_background_worker()
        telegram_service.stop_background_notifier()
        server.server_close()


if __name__ == "__main__":
    p = None
    if len(sys.argv) > 1:
        try:
            p = int(sys.argv[1])
        except ValueError:
            pass
    run(p)
