"""One designated owner TopstepX Market Hub for DEV / Canary / Production.

Fail-closed default: no process opens ProjectX (loginKey + SignalR) unless it
is the explicitly designated hub.  Charts, browsers, devices and developer
copies fan out from that hub through StratForge cache/router/WebSocket.  Direct
provider credentials on other environments are ignored; those processes consume
the hub or use internal cache/replay/runtime sources.
"""
from __future__ import annotations

import atexit
import hmac
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import runtime_env

TOKEN_HEADER = "X-StratForge-Owner-Market-Gateway-Token"
MODE_HEADER = "X-StratForge-Owner-Market-Gateway"
MODE_CONSUME = "consume"
CHART_PATHS = (
    "/api/ops/runtime/bars",
    "/api/ops/runtime/bars/status",
    "/ws/market-data",
)
_ALLOWED_PUBLIC_HOSTS = {"app.stratforges.com", "canary.stratforges.com"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MIN_TOKEN_LEN = 16
_DEFAULT_BIND_PORT = 8765
_LOCAL_BIND_PORT = 0
_LEASE_TTL_SEC = 45
# The hub renews well inside the TTL.  A hub that holds an open SignalR socket
# for hours without a chart request must not let its lease lapse: an expired
# lease is exactly what would let a second process open a duplicate ProjectX
# connection with the same owner credential.
_LEASE_RENEW_INTERVAL_SEC = 15
_LEASE_LOCK = threading.RLock()
_LEASE_ID = ""
_LEASE_ATEXIT_REGISTERED = False
_DUPLICATE_WARNING = ""
_LEASE_HEARTBEAT_THREAD: Optional[threading.Thread] = None
_LEASE_HEARTBEAT_STOP = threading.Event()


def _deployment() -> Any:
    try:
        return runtime_env.deployment_config()
    except Exception:
        return None


def _environment() -> str:
    deployment = _deployment()
    if deployment is not None:
        return str(getattr(deployment, "environment", "") or "")
    try:
        return str(runtime_env.deployment_environment() or "")
    except Exception:
        return ""


def _role_name() -> str:
    raw = str(os.environ.get("NTA_OWNER_MARKET_DATA_GATEWAY_ROLE") or "auto").strip().lower()
    if raw in {"hub", "consumer", "auto"}:
        return raw
    return "auto"


def token() -> str:
    return str(os.environ.get("NTA_OWNER_MARKET_DATA_GATEWAY_TOKEN") or "").strip()


def token_configured() -> bool:
    return len(token()) >= _MIN_TOKEN_LEN


def token_matches(supplied: Any) -> bool:
    expected = token()
    value = str(supplied or "").strip()
    if len(expected) < _MIN_TOKEN_LEN or len(value) != len(expected):
        return False
    return hmac.compare_digest(value, expected)


def normalize_gateway_origin(raw: str) -> str:
    """Allow only loopback HTTP with a port, or the canonical public HTTPS hosts."""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return ""
    host = str(parsed.hostname or "").lower().rstrip(".")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    if parsed.path not in {"", "/"}:
        return ""
    port = parsed.port
    if parsed.scheme == "http" and host in {"127.0.0.1", "localhost"} and port and 1 <= int(port) <= 65535:
        normalized_host = "127.0.0.1" if host == "127.0.0.1" else "localhost"
        return f"http://{normalized_host}:{int(port)}"
    if parsed.scheme == "https" and host in _ALLOWED_PUBLIC_HOSTS and port in {None, 443}:
        return f"https://{host}"
    return ""


def _explicit_gateway_url() -> str:
    return normalize_gateway_origin(os.environ.get("NTA_OWNER_MARKET_DATA_GATEWAY_URL") or "")


def gateway_url() -> str:
    named = _role_name()
    explicit = _explicit_gateway_url()
    if named == "hub":
        return ""
    environment = _environment()
    # Production auto never consumes Canary or any other origin.  Only an
    # explicit consumer role may point Production at a designated hub.
    if named == "auto" and environment == runtime_env.PRODUCTION:
        return ""
    if explicit:
        return explicit
    # An explicit ``consumer`` falls back to the same environment-derived hub
    # origin as ``auto``.  Naming the role must never leave an environment with
    # fewer ways to reach the hub than not naming it: a Canary configured
    # ROLE=consumer + STRATFORGE_PRODUCTION_INTERNAL_ORIGIN would otherwise go
    # isolated and serve empty charts.
    if environment == runtime_env.CANARY:
        return normalize_gateway_origin(os.environ.get("STRATFORGE_PRODUCTION_INTERNAL_ORIGIN") or "")
    # Development and staging had no rule at all, so a developer copy resolved
    # to no hub, went ``isolated`` and painted OFFLINE with zero live backups --
    # while the hub it should have been consuming was serving Production fine.
    # They reach the hub over its public origin; the token still gates access,
    # and consuming is what keeps a developer copy from opening a second
    # ProjectX session on the owner's credential.
    if environment in {runtime_env.DEVELOPMENT, runtime_env.STAGING}:
        for name in ("STRATFORGE_PRODUCTION_INTERNAL_ORIGIN", "STRATFORGE_PRODUCTION_ORIGIN"):
            origin = normalize_gateway_origin(os.environ.get(name) or "")
            if origin:
                return origin
    return ""


def set_local_bind_port(port: Any) -> None:
    """Record the port this process actually bound.

    The self-loop guard has to know it, and the server takes its port from
    ``sys.argv`` (``python -m app.server 18767`` on the deployment host), so
    neither an env var nor the default is reliable on its own.
    """
    global _LOCAL_BIND_PORT
    try:
        value = int(port or 0)
    except (TypeError, ValueError):
        return
    if 1 <= value <= 65535:
        _LOCAL_BIND_PORT = value


def _local_bind_port() -> int:
    if _LOCAL_BIND_PORT:
        return _LOCAL_BIND_PORT
    for candidate in (os.environ.get("STRATFORGE_BIND_PORT"), *sys.argv[1:2]):
        try:
            value = int(candidate or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= value <= 65535:
            return value
    return _DEFAULT_BIND_PORT


def _own_listen_targets() -> List[Tuple[str, int]]:
    targets: List[Tuple[str, int]] = []
    deployment = _deployment()
    bind_host = str(getattr(deployment, "bind_host", "") or "127.0.0.1").lower()
    bind_port = _local_bind_port()
    hosts = {bind_host, "127.0.0.1", "localhost"}
    if bind_host in {"0.0.0.0", "::"}:
        hosts.update({"127.0.0.1", "localhost"})
    for host in hosts:
        targets.append((host, bind_port))
    origin = str(getattr(deployment, "public_origin", "") or "")
    parsed = urllib.parse.urlsplit(origin) if origin else None
    if parsed and parsed.hostname:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        targets.append((str(parsed.hostname).lower().rstrip("."), int(port)))
    return targets


def points_at_self(url: str) -> bool:
    origin = normalize_gateway_origin(url)
    if not origin:
        return False
    parsed = urllib.parse.urlsplit(origin)
    host = str(parsed.hostname or "").lower().rstrip(".")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    for own_host, own_port in _own_listen_targets():
        if int(port) != int(own_port):
            continue
        if host == own_host:
            return True
        if host in {"127.0.0.1", "localhost"} and own_host in {"127.0.0.1", "localhost"}:
            return True
    return False


def _api_role() -> bool:
    deployment = _deployment()
    role = str(getattr(deployment, "deployment_role", "") or os.environ.get("STRATFORGE_DEPLOYMENT_ROLE") or "all-in-one")
    return role in {"api", "all-in-one"}


def is_hub() -> bool:
    """True only when this process is the explicitly designated ProjectX hub.

    ``auto`` is fail-closed: DEV, Canary, Production and developer copies do
    not open a provider session unless ``NTA_OWNER_MARKET_DATA_GATEWAY_ROLE=hub``.
    """
    if not _api_role():
        return False
    return _role_name() == "hub"


def should_consume() -> bool:
    origin = gateway_url()
    return bool(not is_hub() and origin and token_configured() and not points_at_self(origin))


def should_open_direct_hub() -> bool:
    return bool(is_hub())


def effective_role() -> str:
    if is_hub():
        return "hub"
    if should_consume():
        return "consumer"
    return "isolated"


def chart_source_mode() -> str:
    if is_hub():
        return "direct_hub"
    if should_consume():
        return "owner_gateway_consumer"
    return "internal_cache_or_runtime"


def is_chart_path(path: str) -> bool:
    clean = str(path or "").split("?", 1)[0]
    return clean in CHART_PATHS


def request_is_chart_endpoint(handler: Any, authorized_path: str = "") -> bool:
    return is_chart_path(authorized_path) or is_chart_path(getattr(handler, "path", "") or "")


def loop_consume_rejected(handler: Any) -> bool:
    mode = str(handler.headers.get(MODE_HEADER) or "").strip().lower()
    return bool(mode == MODE_CONSUME and should_consume())


def authorize_gateway_request(handler: Any, authorized_path: str = "") -> bool:
    """Authenticate an internal consumer on chart endpoints only."""
    if not request_is_chart_endpoint(handler, authorized_path):
        return False
    if not token_matches(handler.headers.get(TOKEN_HEADER)):
        return False
    if loop_consume_rejected(handler):
        return False
    if not is_hub():
        return False
    return True


def allows_loopback_chart_edge(handler: Any) -> bool:
    """Let a same-host consumer reach Production/Canary chart paths with the token.

    Production otherwise requires Cloudflare-style HTTPS forwarded headers, which
    a loopback Canary→Production consume cannot honestly provide.
    """
    if not is_hub():
        return False
    try:
        peer = str((handler.client_address or ("", 0))[0] or "").split("%", 1)[0]
    except Exception:
        peer = ""
    if peer not in _LOOPBACK_HOSTS:
        return False
    if not is_chart_path(getattr(handler, "path", "") or ""):
        return False
    return token_matches(handler.headers.get(TOKEN_HEADER))


def service_context() -> Dict[str, Any]:
    return {
        "is_owner": True,
        "role": "owner",
        "owner_market_gateway": True,
        "uses_owner_runtime": True,
        "workspace_id": "",
    }


def owner_identity() -> Dict[str, Any]:
    deployment = _deployment()
    instance_id = str(getattr(deployment, "instance_id", "") or os.environ.get("STRATFORGE_INSTANCE_ID") or "")
    public_origin = str(getattr(deployment, "public_origin", "") or os.environ.get("STRATFORGE_PUBLIC_ORIGIN") or "")
    deployment_role = str(
        getattr(deployment, "deployment_role", "")
        or os.environ.get("STRATFORGE_DEPLOYMENT_ROLE")
        or "all-in-one"
    )
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = ""
    return {
        "environment": _environment() or runtime_env.DEVELOPMENT,
        "instance_id": instance_id[:160],
        "public_origin": public_origin[:200],
        "deployment_role": deployment_role[:80],
        "pid": os.getpid(),
        "hostname": str(hostname or "")[:120],
    }


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def lease_path() -> Path:
    override = str(os.environ.get("NTA_OWNER_MARKET_DATA_GATEWAY_LEASE_PATH") or "").strip()
    if override:
        return Path(override)
    if os.name == "nt":
        base = str(os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or ".")
        return Path(base) / "StratForge" / "owner-market-data-hub.lease.json"
    return Path("/tmp/stratforge-owner-market-data-hub.lease.json")


def _pid_alive_windows(pid: int) -> bool:
    """Probe liveness with OpenProcess.

    ``os.kill(pid, 0)`` must never be used here on Windows: signal ``0`` is
    ``CTRL_C_EVENT``, so the "probe" actually delivers a Ctrl+C to that
    process's console group instead of reporting whether it is running.
    """
    import ctypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        # Access denied means the process exists but belongs to another user.
        return ctypes.get_last_error() == error_access_denied
    try:
        code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return int(code.value) == still_active
        return True
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    if int(pid or 0) <= 0:
        return False
    try:
        if os.name == "nt":
            return _pid_alive_windows(int(pid))
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception:
        return False


def _read_lease(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_lease(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _lease_expired(row: Dict[str, Any]) -> bool:
    expires = str(row.get("expires_at_utc") or "")
    if not expires:
        return True
    try:
        stamp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp <= datetime.now(timezone.utc)


def _ensure_lease_atexit() -> None:
    global _LEASE_ATEXIT_REGISTERED
    if _LEASE_ATEXIT_REGISTERED:
        return
    atexit.register(release_hub_lease)
    _LEASE_ATEXIT_REGISTERED = True


def _lease_heartbeat_loop() -> None:
    while not _LEASE_HEARTBEAT_STOP.wait(_LEASE_RENEW_INTERVAL_SEC):
        with _LEASE_LOCK:
            still_ours = bool(_LEASE_ID)
        if not still_ours or not is_hub():
            return
        try:
            acquire_hub_lease()
        except Exception:
            # A transient filesystem failure must not kill the renewal loop;
            # the lease simply ages until the next tick succeeds.
            pass


def _ensure_lease_heartbeat() -> None:
    global _LEASE_HEARTBEAT_THREAD
    thread = _LEASE_HEARTBEAT_THREAD
    if thread is not None and thread.is_alive():
        return
    _LEASE_HEARTBEAT_STOP.clear()
    thread = threading.Thread(target=_lease_heartbeat_loop, name="owner-md-hub-lease", daemon=True)
    _LEASE_HEARTBEAT_THREAD = thread
    thread.start()


def _stop_lease_heartbeat() -> None:
    global _LEASE_HEARTBEAT_THREAD
    thread = _LEASE_HEARTBEAT_THREAD
    _LEASE_HEARTBEAT_STOP.set()
    _LEASE_HEARTBEAT_THREAD = None
    if thread is not None and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=1)


def acquire_hub_lease() -> Dict[str, Any]:
    """Single-owner lease for the designated hub. Duplicate ROLE=hub is blocked."""
    global _LEASE_ID, _DUPLICATE_WARNING
    identity = owner_identity()
    if not is_hub():
        return lease_status()
    path = lease_path()
    with _LEASE_LOCK:
        existing = _read_lease(path) if path.is_file() else {}
        existing_id = str(existing.get("lease_id") or "")
        existing_pid = int(existing.get("pid") or 0)
        ours = bool(_LEASE_ID and existing_id == _LEASE_ID)
        # A pid only means something on the host that wrote it.  If the lease
        # came from a different hostname, never use local pid liveness to
        # decide it is dead — only its expiry may release it.
        same_host = str(existing.get("hostname") or "") == identity["hostname"]
        holder_running = _pid_alive(existing_pid) if same_host else True
        living_other = bool(
            existing
            and not ours
            and not _lease_expired(existing)
            and holder_running
            and not (same_host and int(existing_pid) == os.getpid())
        )
        if living_other:
            _DUPLICATE_WARNING = "duplicate_owner_market_data_hub_blocked"
            return {
                "held": False,
                "duplicate_blocked": True,
                "warning": _DUPLICATE_WARNING,
                "owner": {
                    "environment": str(existing.get("environment") or ""),
                    "instance_id": str(existing.get("instance_id") or ""),
                    "public_origin": str(existing.get("public_origin") or ""),
                    "pid": existing_pid,
                    "hostname": str(existing.get("hostname") or ""),
                },
                "path_configured": True,
            }
        lease_id = _LEASE_ID or secrets.token_hex(8)
        now = datetime.now(timezone.utc)
        payload = {
            "lease_id": lease_id,
            "pid": os.getpid(),
            "environment": identity["environment"],
            "instance_id": identity["instance_id"],
            "public_origin": identity["public_origin"],
            "deployment_role": identity["deployment_role"],
            "hostname": identity["hostname"],
            "acquired_at_utc": str(existing.get("acquired_at_utc") or _iso_now()) if ours else _iso_now(),
            "heartbeat_at_utc": _iso_now(),
            "expires_at_utc": (now + timedelta(seconds=_LEASE_TTL_SEC)).isoformat().replace("+00:00", "Z"),
        }
        _write_lease(path, payload)
        _LEASE_ID = lease_id
        _DUPLICATE_WARNING = ""
        _ensure_lease_atexit()
    # Started outside the lease lock so the renewal thread can take it freely.
    _ensure_lease_heartbeat()
    return lease_status()


def release_hub_lease() -> None:
    global _LEASE_ID, _DUPLICATE_WARNING
    # Stop the renewal thread before taking the lease lock: the loop grabs the
    # same lock, so joining it while holding the lock would deadlock.
    _stop_lease_heartbeat()
    path = lease_path()
    with _LEASE_LOCK:
        if not _LEASE_ID:
            return
        existing = _read_lease(path) if path.is_file() else {}
        if str(existing.get("lease_id") or "") == _LEASE_ID:
            try:
                path.unlink()
            except OSError:
                pass
        _LEASE_ID = ""
        _DUPLICATE_WARNING = ""


def reset_lease_for_tests() -> None:
    release_hub_lease()


def lease_status() -> Dict[str, Any]:
    path = lease_path()
    existing = _read_lease(path) if path.is_file() else {}
    # An expired lease is not held even when the file still carries our id: the
    # renewal thread has stalled and another process may legitimately take over.
    held = bool(
        _LEASE_ID
        and str(existing.get("lease_id") or "") == _LEASE_ID
        and not _lease_expired(existing)
    )
    duplicate = bool(_DUPLICATE_WARNING)
    owner = {
        "environment": str(existing.get("environment") or ""),
        "instance_id": str(existing.get("instance_id") or ""),
        "public_origin": str(existing.get("public_origin") or ""),
        "deployment_role": str(existing.get("deployment_role") or ""),
        "pid": int(existing.get("pid") or 0),
        "hostname": str(existing.get("hostname") or ""),
        "heartbeat_at_utc": str(existing.get("heartbeat_at_utc") or ""),
        "expires_at_utc": str(existing.get("expires_at_utc") or ""),
    }
    thread = _LEASE_HEARTBEAT_THREAD
    return {
        "held": held,
        "duplicate_blocked": duplicate,
        "warning": _DUPLICATE_WARNING,
        "owner": owner if existing else owner_identity(),
        "path_configured": True,
        "ttl_sec": _LEASE_TTL_SEC,
        "renew_interval_sec": _LEASE_RENEW_INTERVAL_SEC,
        "renewal_running": bool(thread is not None and thread.is_alive()),
    }


def _credentials_present() -> bool:
    username = str(
        os.environ.get("NTA_TOPSTEPX_USERNAME") or os.environ.get("NTA_TOPSTEP_USERNAME") or ""
    ).strip()
    api_key = str(
        os.environ.get("NTA_TOPSTEPX_API_KEY") or os.environ.get("NTA_TOPSTEP_API_KEY") or ""
    ).strip()
    return bool(username and api_key)


def connection_observability() -> Dict[str, Any]:
    """Secret-free counts: one provider connection fans out to many Aurora clients."""
    warnings: List[str] = []
    if _credentials_present() and not is_hub() and not should_consume():
        warnings.append("owner_credentials_present_but_direct_hub_forbidden")
    elif _credentials_present() and should_consume():
        warnings.append("owner_credentials_ignored_consumer_uses_gateway")
    lease = lease_status()
    if is_hub() and lease.get("duplicate_blocked"):
        warnings.append("duplicate_owner_market_data_hub_blocked")
    session: Dict[str, Any] = {}
    try:
        from .market_data_live_adapters import topstepx_session_manager
        session = topstepx_session_manager().audit()
    except Exception:
        session = {}
    ws_metrics: Dict[str, Any] = {}
    try:
        from . import market_data_ws_http
        ws_metrics = market_data_ws_http.metrics()
    except Exception:
        ws_metrics = {}
    adapter_health: Dict[str, Any] = {}
    try:
        from . import market_data_failover as md_failover
        adapter = md_failover.TopstepXProvider._adapter_instance
        if adapter is not None:
            adapter_health = adapter.health()
    except Exception:
        adapter_health = {}
    signalr_open = 1 if str(adapter_health.get("runtime_state") or "") in {"AUTHENTICATED", "LIVE"} else 0
    if is_hub() and adapter_health.get("session_audit", {}).get("token_present") and signalr_open:
        direct = 1
    elif is_hub() and should_open_direct_hub():
        direct = int(bool(signalr_open))
    else:
        direct = 0
    if is_hub() and not lease.get("held") and not lease.get("duplicate_blocked"):
        warnings.append("hub_lease_not_held")
    browser_clients = int(ws_metrics.get("clients") or 0)
    wire = int(adapter_health.get("wire_subscriptions") or 0)
    logical = int(adapter_health.get("logical_subscription_refcount") or 0)
    return {
        "owner": owner_identity(),
        "role": effective_role(),
        "chart_source_mode": chart_source_mode(),
        "direct_provider_connections": direct,
        "authentication_sessions": 1 if session.get("token_present") else 0,
        "login_key_calls": int(session.get("login_key_calls") or 0),
        "signalr_connections_open": signalr_open,
        "signalr_connections_opened_total": int(session.get("signalr_connections_opened") or 0),
        "browser_websockets": browser_clients,
        "logical_subscriptions": logical,
        "wire_subscriptions": wire,
        "logical_subscription_deduplicated": int(session.get("logical_subscription_deduplicated") or 0),
        "lease": lease,
        "warnings": warnings,
        "fanout": {
            "internal_clients_do_not_multiply_provider_connections": True,
            "instrument_subscription_deduplicated": True,
            "browser_clients": browser_clients,
            "provider_connections": direct,
        },
    }


def public_status() -> Dict[str, Any]:
    origin = gateway_url()
    obs = connection_observability()
    return {
        "role": effective_role(),
        "configured_role": _role_name(),
        "direct_market_hub": should_open_direct_hub(),
        "consuming_owner_gateway": should_consume(),
        "gateway_url_configured": bool(origin),
        "gateway_token_configured": token_configured(),
        "self_loop_blocked": bool(origin and points_at_self(origin)),
        "chart_source_mode": chart_source_mode(),
        "fail_closed_default": _role_name() != "hub",
        "owner": obs["owner"],
        "observability": obs,
        "warnings": list(obs.get("warnings") or []),
    }


def _loopback_public_host(origin: str) -> str:
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme != "http" or str(parsed.hostname or "").lower() not in {"127.0.0.1", "localhost"}:
        return ""
    port = int(parsed.port or 0)
    production_internal = normalize_gateway_origin(os.environ.get("STRATFORGE_PRODUCTION_INTERNAL_ORIGIN") or "")
    canary_internal = normalize_gateway_origin(os.environ.get("STRATFORGE_CANARY_INTERNAL_ORIGIN") or "")
    if production_internal and origin == production_internal:
        host = str(urllib.parse.urlsplit(
            os.environ.get("STRATFORGE_PRODUCTION_ORIGIN") or "https://app.stratforges.com"
        ).hostname or "app.stratforges.com")
        return host
    if canary_internal and origin == canary_internal:
        host = str(urllib.parse.urlsplit(
            os.environ.get("STRATFORGE_CANARY_ORIGIN") or "https://canary.stratforges.com"
        ).hostname or "canary.stratforges.com")
        return host
    if port == 18767:
        return "app.stratforges.com"
    if port == 18765:
        return "canary.stratforges.com"
    return ""


def consumer_headers() -> Dict[str, str]:
    headers = {
        TOKEN_HEADER: token(),
        MODE_HEADER: MODE_CONSUME,
        "Accept": "application/json",
        "User-Agent": "StratForge-OwnerMarketGateway/1",
    }
    origin = gateway_url()
    public_host = _loopback_public_host(origin)
    if public_host:
        headers["Host"] = public_host
        headers["X-Forwarded-Host"] = public_host
        headers["X-Forwarded-Proto"] = "https"
        headers["X-Forwarded-For"] = "127.0.0.1"
    return headers


def fetch_gateway_json(path: str, query: Optional[Dict[str, Any]] = None, *, timeout: float = 20.0) -> Dict[str, Any]:
    origin = gateway_url()
    if not should_consume():
        raise RuntimeError("owner market-data gateway is not in consumer mode")
    encoded = urllib.parse.urlencode(
        {key: value for key, value in (query or {}).items() if value not in {None, ""}},
        doseq=True,
    )
    url = origin.rstrip("/") + path + (("?" + encoded) if encoded else "")
    request = urllib.request.Request(url, headers=consumer_headers(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp is not None else b""
        status = int(exc.code)
    except Exception as exc:
        raise RuntimeError(f"owner gateway request failed: {type(exc).__name__}") from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = {}
    if status >= 400 or not isinstance(payload, dict):
        raise RuntimeError(f"owner gateway HTTP {status}")
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    if payload.get("via") == "owner_gateway" or source.get("via") == "owner_gateway":
        raise RuntimeError("owner gateway recursion blocked")
    return payload


def gateway_ws_url() -> str:
    origin = gateway_url()
    if origin.startswith("https://"):
        return "wss://" + origin[len("https://"):] + "/ws/market-data"
    if origin.startswith("http://"):
        return "ws://" + origin[len("http://"):] + "/ws/market-data"
    return ""


class OwnerGatewayChartAdapter:
    """Read-only TopstepX charts via the designated owner hub. Never loginKey."""

    name = "topstep_live"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subs: Dict[str, Dict[str, Any]] = {}
        self._runtime_state = "CONNECTING"
        self._last_error = ""
        self._connected_at = ""
        self._last_event_utc = ""
        self._event_count = 0
        self._sink = None
        self._mode = "authoritative"
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ws_client = None
        self._loop = None
        self._resolved_exact_map: Dict[str, str] = {}
        self._last_feed: Dict[str, Any] = {}
        self._last_signal_target = ""
        self._last_signal_price_field = ""
        self._signal_target_counts: Dict[str, int] = {}
        self._signal_price_field_counts: Dict[str, int] = {}
        self._event_type_counts: Dict[str, int] = {}
        self._last_event_type_utc: Dict[str, str] = {}
        self._last_event_type_contract_utc: Dict[str, Dict[str, str]] = {}
        self._pending_signal_invocations: Dict[str, Dict[str, str]] = {}
        self._signal_invocation_results: Dict[str, Dict[str, Any]] = {}
        self._wire_subscribed_contract_ids: set[str] = set()

    def set_sink(self, sink, mode: str = "shadow") -> None:
        self._sink = sink
        self._mode = mode

    def credentials_present(self) -> bool:
        return bool(should_consume())

    def enabled(self) -> bool:
        return bool(should_consume())

    def implementation_state(self) -> str:
        return "CONNECTED" if self._runtime_state == "LIVE" else "ADAPTER_READY"

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "runtime_state": self._runtime_state,
                "implementation_state": self.implementation_state(),
                "credentials_present": self.credentials_present(),
                "connected_at_utc": self._connected_at,
                "last_event_utc": self._last_event_utc,
                "event_count": self._event_count,
                "last_error": self._last_error,
                "mode": self._mode,
                "via": "owner_gateway",
                "wire_subscriptions": len(self._wire_subscribed_contract_ids),
                "logical_subscription_refcount": sum(
                    len(set(row.get("consumers") or set())) for row in self._subs.values()
                ),
                "pending_signal_invocations": 0,
                "session_audit": {
                    "login_key_calls": 0,
                    "signalr_connections_opened": 0,
                    "via": "owner_gateway",
                },
                "market_feed": dict(self._last_feed),
                "last_signal_target": self._last_signal_target,
                "last_signal_price_field": self._last_signal_price_field,
                "signal_target_counts": dict(self._signal_target_counts),
                "signal_price_field_counts": dict(self._signal_price_field_counts),
                "event_type_counts": dict(self._event_type_counts),
                "event_type_age_sec": {},
                "trade_age_by_contract_sec": {},
                "signal_invocation_results": dict(self._signal_invocation_results),
            }

    def market_feed_freshness(self, exact_contract: str = "") -> Dict[str, Any]:
        with self._lock:
            feed = dict(self._last_feed)
            state = self._runtime_state
        if feed:
            return feed
        connected = state in {"AUTHENTICATED", "LIVE"}
        return {
            "fresh": False,
            "stale": False,
            "offline": not connected,
            "connection_state": state,
            "connection_active": connected,
            "market_feed_as_of_utc": "",
            "last_trade_at_utc": "",
        }

    def resolved_exact_contract(self, contract: str) -> str:
        normalized = " ".join(str(contract or "").strip().upper().split())
        with self._lock:
            return str(self._resolved_exact_map.get(normalized) or normalized)

    def connect(self) -> Dict[str, Any]:
        if not self.enabled():
            self._runtime_state = "DISABLED"
            return self.health()
        if self._thread is not None and self._thread.is_alive():
            return self.health()
        self._stop.clear()
        self._runtime_state = "CONNECTING"
        self._connected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self._thread = threading.Thread(target=self._run_ws_loop, name="owner-md-gateway-ws", daemon=True)
        self._thread.start()
        return self.health()

    def disconnect(self) -> None:
        self._stop.set()
        ws = self._ws_client
        loop = self._loop
        if ws is not None and loop is not None:
            try:
                import asyncio
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None
        self._ws_client = None
        self._loop = None
        self._runtime_state = "DISABLED"

    def subscribe(self, exact_contract: str, channel: str = "trades", *, timeframe: str = "1m",
                  consumer_id: str = "bootstrap") -> str:
        contract = " ".join(str(exact_contract or "").strip().upper().split())
        schema = "quotes" if channel in {"bid_ask", "quotes"} else "trades"
        sub_id = f"gateway:{contract}:{schema}"
        consumer = str(consumer_id or "bootstrap")[:160]
        with self._lock:
            row = self._subs.setdefault(sub_id, {
                "exact_contract": contract,
                "channel": channel,
                "schema": schema,
                "timeframe": str(timeframe or "1m"),
                "consumers": set(),
            })
            consumers = row.setdefault("consumers", set())
            # The browser WS can acquire first while its initial HTTP history
            # request is still in flight.  In that ordering a later bootstrap
            # must not survive the browser close as an orphan logical ref.  The
            # direct TopstepX adapter enforces the same contract.
            bootstrap = consumer.startswith("bootstrap:")
            has_browser_consumer = any(
                not str(item).startswith("bootstrap:") for item in consumers
            )
            if not (bootstrap and has_browser_consumer):
                consumers.add(consumer)
            self._wire_subscribed_contract_ids.add(contract)
        self.connect()
        self._send_ws({"type": "subscribe", "exact_contract": contract, "timeframe": str(timeframe or "1m")})
        return sub_id

    def release_subscription(self, exact_contract: str, channel: str = "quotes", *,
                             timeframe: str = "1m", consumer_id: str = "") -> bool:
        contract = " ".join(str(exact_contract or "").strip().upper().split())
        schema = "quotes" if channel in {"bid_ask", "quotes"} else "trades"
        sub_id = f"gateway:{contract}:{schema}"
        consumer = str(consumer_id or "")[:160]
        with self._lock:
            row = self._subs.get(sub_id)
            if row is None:
                return False
            consumers = row.setdefault("consumers", set())
            if consumer:
                consumers.discard(consumer)
            else:
                consumers.clear()
            if consumers:
                return True
            self._subs.pop(sub_id, None)
            if not any(item.get("exact_contract") == contract for item in self._subs.values()):
                self._wire_subscribed_contract_ids.discard(contract)
        self._send_ws({"type": "unsubscribe", "exact_contract": contract, "timeframe": str(timeframe or "1m")})
        return True

    def history_range(self, exact_contract: str, timeframe: str, *,
                      start_time: Any = None, end_time: Any = None,
                      limit: int = 1500, cancel_event: Any = None) -> Dict[str, Any]:
        def utc_query_stamp(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, datetime):
                stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                return stamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            return str(value).strip()

        query = {
            "instrument": exact_contract,
            "timeframe": timeframe,
            "limit": max(1, min(int(limit or 1500), 20_000)),
            # Viewport history is a different range from the latest-bars
            # bootstrap.  Dropping these bounds made a consumer request the
            # same latest 64 bars forever, so two large layouts eventually
            # occupied every bounded HTTP slot even though their shared WS
            # feed remained healthy.
            "from_ts": utc_query_stamp(start_time),
            "to_ts": utc_query_stamp(end_time),
        }
        payload = fetch_gateway_json("/api/ops/runtime/bars", query)
        instrument = str(payload.get("instrument") or exact_contract).upper()
        requested = " ".join(str(exact_contract or "").strip().upper().split())
        history = payload.get("history") if isinstance(payload.get("history"), dict) else {}
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        with self._lock:
            self._resolved_exact_map[requested] = instrument
            freshness = payload.get("freshness") if isinstance(payload.get("freshness"), dict) else {}
            self._last_feed = {
                "fresh": bool(freshness.get("market_feed_fresh", payload.get("live"))),
                "stale": bool(freshness.get("market_feed_stale")),
                "offline": bool(freshness.get("offline")),
                "connection_state": str(source.get("runtime_state") or payload.get("status") or "LIVE"),
                "connection_active": bool(payload.get("live")),
                "signalr_receive_age_sec": freshness.get("market_feed_age_sec"),
                "signalr_heartbeat_age_sec": freshness.get("signalr_heartbeat_age_sec"),
                "quote_age_sec": freshness.get("quote_age_sec"),
                "bid_ask_age_sec": freshness.get("bid_ask_age_sec"),
                "last_trade_age_sec": freshness.get("last_trade_age_sec"),
                "market_feed_as_of_utc": str(freshness.get("market_feed_as_of_utc") or ""),
                "last_trade_at_utc": "",
            }
            if payload.get("live"):
                self._runtime_state = "LIVE"
            elif source.get("runtime_state"):
                self._runtime_state = str(source.get("runtime_state"))
        return {
            "bars": list(payload.get("bars") or []),
            "requested_start_utc": str(history.get("requested_start_utc") or query["from_ts"]),
            "requested_end_utc": str(history.get("requested_end_utc") or query["to_ts"]),
            "cache_hit": bool(history.get("cache_hit") or source.get("cache_hit")),
            "chunks": int(history.get("chunks") or 1),
            "history_exhausted": bool(
                history.get("exhausted") or source.get("history_exhausted")
            ),
            "native_aggregation_fallback": bool(
                history.get("native_aggregation_fallback")
                or source.get("native_aggregation_fallback")
            ),
            "via": "owner_gateway",
        }

    def _send_ws(self, message: Dict[str, Any]) -> None:
        client = self._ws_client
        loop = self._loop
        if client is None or loop is None:
            return
        try:
            import asyncio
            asyncio.run_coroutine_threadsafe(client.send(json.dumps(message)), loop)
        except Exception:
            pass

    def _run_ws_loop(self) -> None:
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            loop.run_until_complete(self._ws_worker())
        except Exception as exc:
            self._last_error = f"owner gateway WS failed: {type(exc).__name__}"
            if self._runtime_state not in {"LIVE", "AUTHENTICATED"}:
                self._runtime_state = "CONNECTING"
        finally:
            self._ws_client = None
            self._loop = None

    async def _ws_worker(self) -> None:
        url = gateway_ws_url()
        if not url:
            self._last_error = "owner gateway WS URL missing"
            return
        try:
            import websockets
        except Exception:
            self._last_error = "websockets package missing for owner gateway"
            return
        backoff = 1.0
        while not self._stop.is_set():
            try:
                connect_kwargs: Dict[str, Any] = {
                    "open_timeout": 10,
                    "close_timeout": 3,
                }
                headers = consumer_headers()
                try:
                    async with websockets.connect(url, additional_headers=headers, **connect_kwargs) as ws:
                        await self._consume_ws(ws)
                except TypeError:
                    async with websockets.connect(url, extra_headers=headers, **connect_kwargs) as ws:
                        await self._consume_ws(ws)
                backoff = 1.0
            except Exception as exc:
                self._ws_client = None
                self._last_error = f"owner gateway WS: {type(exc).__name__}"
                if self._stop.is_set():
                    return
                time.sleep(min(backoff, 15.0))
                backoff = min(backoff * 2, 15.0)

    async def _consume_ws(self, ws: Any) -> None:
        self._ws_client = ws
        with self._lock:
            self._runtime_state = "AUTHENTICATED"
            # A previous transport close is historical once the authenticated
            # gateway connection has been re-established. Leaving it here made
            # a healthy consumer look failed after any normal reconnect.
            self._last_error = ""
            pending = [
                {"type": "subscribe", "exact_contract": row.get("exact_contract"),
                 "timeframe": row.get("timeframe") or "1m"}
                for row in self._subs.values()
            ]
        for message in pending:
            await ws.send(json.dumps(message))
        while not self._stop.is_set():
            raw = await ws.recv()
            self._on_gateway_message(raw)

    def _on_gateway_message(self, raw: Any) -> None:
        try:
            message = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else raw
        except Exception:
            return
        if not isinstance(message, dict):
            return
        if str(message.get("type") or "") != "market_event":
            return
        event = message.get("event") if isinstance(message.get("event"), dict) else {}
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with self._lock:
            self._event_count += 1
            self._last_event_utc = now
            self._runtime_state = "LIVE"
            self._last_feed = {
                "fresh": True, "stale": False, "offline": False,
                "connection_state": "LIVE", "connection_active": True,
                "market_feed_as_of_utc": now,
            }
        sink = self._sink
        if sink is not None:
            try:
                if event:
                    sink(event)
                elif message.get("bar_updates"):
                    sink(message)
            except Exception:
                pass


def annotate_source(source: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(source or {})
    identity = owner_identity()
    out["gateway_environment"] = identity.get("environment") or ""
    out["gateway_instance_id"] = identity.get("instance_id") or ""
    if should_consume():
        out["via"] = "owner_gateway"
        out["direct_market_hub"] = False
        out["chart_source_mode"] = "owner_gateway_consumer"
    elif is_hub():
        out["direct_market_hub"] = True
        out["chart_source_mode"] = "direct_hub"
    else:
        out["direct_market_hub"] = False
        out["chart_source_mode"] = "internal_cache_or_runtime"
    return out
