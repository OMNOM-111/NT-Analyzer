"""Safe liveness/readiness payloads for StratForge service supervision."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Tuple


PRODUCTION_COMPONENTS = (
    "database",
    "queue",
    "object_storage",
    "signing_key",
    "connector_control",
    "telegram_consumer",
)
DEFAULT_PROBE_TIMEOUT_SEC = 2.0
DEFAULT_CACHE_TTL_SEC = 2.0

_CACHE_LOCK = threading.Lock()
_COMPUTE_LOCK = threading.Lock()
_CACHE: Optional[Tuple[float, Tuple[Any, ...], Dict[str, Any]]] = None


def liveness_payload(config: Any) -> Dict[str, Any]:
    return {
        "ok": True,
        "status": "alive",
        "deployment": config.public_dict(),
    }


def clear_readiness_cache() -> None:
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None


def _data_root_check(config: Any, minimum_free_mb: int) -> Dict[str, Any]:
    root = Path(config.data_root)
    if not root.exists() or not root.is_dir():
        return {"ok": False, "code": "data_root_missing"}
    if not os.access(str(root), os.R_OK | os.W_OK | os.X_OK):
        return {"ok": False, "code": "data_root_not_writable"}
    try:
        free_mb = int(shutil.disk_usage(root).free // (1024 * 1024))
    except OSError:
        return {"ok": False, "code": "disk_status_unavailable"}
    if free_mb < minimum_free_mb:
        return {"ok": False, "code": "disk_free_below_floor"}
    return {"ok": True, "code": "ok"}


def _normalize_probe_result(result: Any) -> Dict[str, Any]:
    if isinstance(result, Mapping):
        ok = bool(result.get("ok"))
        code = str(result.get("code") or ("ok" if ok else "not_ready"))
        return {"ok": ok, "code": code[:64]}
    ok = bool(result)
    return {"ok": ok, "code": "ok" if ok else "not_ready"}


def _invoke_probe(probe: Optional[Callable[[], Any]]) -> Dict[str, Any]:
    if probe is None:
        return {"ok": False, "code": "probe_not_registered"}
    try:
        return _normalize_probe_result(probe())
    except Exception:
        return {"ok": False, "code": "probe_failed"}


def _run_probe(
    probe: Optional[Callable[[], Any]],
    *,
    timeout_sec: float,
) -> Dict[str, Any]:
    if probe is None:
        return {"ok": False, "code": "probe_not_registered"}
    box: Dict[str, Any] = {}

    def worker() -> None:
        box["result"] = _invoke_probe(probe)

    thread = threading.Thread(target=worker, name="stratforge-ready-probe", daemon=True)
    thread.start()
    thread.join(max(0.05, float(timeout_sec)))
    if thread.is_alive():
        return {"ok": False, "code": "probe_timeout"}
    return box.get("result") or {"ok": False, "code": "probe_failed"}


def _run_probes_parallel(
    names: Tuple[str, ...],
    registered: Mapping[str, Callable[[], Any]],
    *,
    timeout_sec: float,
) -> Dict[str, Dict[str, Any]]:
    """Run control-plane probes concurrently so N slow probes cannot stack."""
    results: Dict[str, Dict[str, Any]] = {}
    lock = threading.Lock()

    def run_one(name: str) -> None:
        result = _invoke_probe(registered.get(name))
        with lock:
            results[name] = result

    threads = [
        threading.Thread(
            target=run_one, args=(name,), name=f"stratforge-ready-{name}", daemon=True,
        )
        for name in names
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + max(0.05, float(timeout_sec)) + 0.05
    for thread in threads:
        thread.join(max(0.01, deadline - time.monotonic()))
    for name in names:
        if name not in results:
            results[name] = {"ok": False, "code": "probe_timeout"}
    return results


def _cache_key(
    config: Any,
    probes: Optional[Mapping[str, Callable[[], Any]]],
    optional_components: Optional[Mapping[str, str]],
) -> Tuple[Any, ...]:
    return (
        str(getattr(config, "environment", "")),
        id(config),
        id(probes),
        id(optional_components),
    )


def _cached_payload(cache_key: Tuple[Any, ...], ttl: float) -> Optional[Dict[str, Any]]:
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE
    if cached is None:
        return None
    cached_at, cached_key, cached_payload = cached
    if cached_key == cache_key and (now - cached_at) < ttl:
        return copy.deepcopy(cached_payload)
    return None


def _store_cache(cache_key: Tuple[Any, ...], payload: Dict[str, Any], ttl: float) -> None:
    if ttl <= 0:
        return
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = (time.monotonic(), cache_key, copy.deepcopy(payload))


def _compute_readiness(
    config: Any,
    *,
    probes: Optional[Mapping[str, Callable[[], Any]]],
    minimum_free_mb: Optional[int],
    optional_components: Optional[Mapping[str, str]],
    timeout: float,
) -> Dict[str, Any]:
    floor = int(
        minimum_free_mb
        if minimum_free_mb is not None
        else getattr(config, "readiness_min_free_mb", 1024)
    )
    checks: Dict[str, Dict[str, Any]] = {
        "config": {"ok": True, "code": "ok"},
        "data_root": _data_root_check(config, max(1, floor)),
    }
    registered = dict(probes or {})
    optional = dict(optional_components or {})
    excluded_from_overall = set()
    pending: list[str] = []
    if config.environment in {"production", "canary"}:
        for name in PRODUCTION_COMPONENTS:
            probe = registered.get(name)
            if probe is None and name in optional:
                checks[name] = {"ok": False, "code": str(optional[name])[:64]}
                excluded_from_overall.add(name)
            else:
                pending.append(name)
        if pending:
            checks.update(
                _run_probes_parallel(tuple(pending), registered, timeout_sec=timeout)
            )
    ok = all(
        bool(check.get("ok"))
        for name, check in checks.items()
        if name not in excluded_from_overall
    )
    return {
        "ok": ok,
        "status": "ready" if ok else "not_ready",
        "deployment": config.public_dict(),
        "checks": checks,
    }


def readiness_payload(
    config: Any,
    *,
    probes: Optional[Mapping[str, Callable[[], Any]]] = None,
    minimum_free_mb: Optional[int] = None,
    optional_components: Optional[Mapping[str, str]] = None,
    probe_timeout_sec: Optional[float] = None,
    cache_ttl_sec: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a bounded, secret-free readiness view.

    Production and Canary remain not-ready until every authoritative
    control-plane component registers a real probe.  Later stages replace these
    missing probes as PostgreSQL, the durable queue, signing keys and Connector
    control plane are enabled.  Canary is held to the same readiness contract so
    it can never report ready while sharing or missing an isolated dependency.

    ``optional_components`` names a *known, disclosed* gap (for example: no
    separate Canary Telegram bot has been provisioned yet) that must not be
    reported as a fabricated PASS but also must not force the whole endpoint
    into a permanent 503 for a feature the current deployment never intends
    to run. Each key maps to the explanatory ``code`` reported for that
    component; the component is still visible in ``checks`` and still marked
    ``ok: False`` when its probe is genuinely absent, but is excluded from the
    overall ``ok`` computation. It never applies when a probe *is*
    registered: once a component is actually wired up, it is judged like
    every other mandatory component.

    Each probe is bounded by ``probe_timeout_sec``. Probes run concurrently so
    a single slow dependency cannot stall the threaded API or a promote-time
    health poll for N times the timeout. Successful and failed payloads are
    cached briefly, and overlapping callers share one in-flight computation.
    """
    timeout = (
        DEFAULT_PROBE_TIMEOUT_SEC
        if probe_timeout_sec is None
        else max(0.05, float(probe_timeout_sec))
    )
    ttl = (
        DEFAULT_CACHE_TTL_SEC
        if cache_ttl_sec is None
        else max(0.0, float(cache_ttl_sec))
    )
    key = _cache_key(config, probes, optional_components)
    cached = _cached_payload(key, ttl)
    if cached is not None:
        return cached
    with _COMPUTE_LOCK:
        cached = _cached_payload(key, ttl)
        if cached is not None:
            return cached
        payload = _compute_readiness(
            config,
            probes=probes,
            minimum_free_mb=minimum_free_mb,
            optional_components=optional_components,
            timeout=timeout,
        )
        _store_cache(key, payload, ttl)
        return payload
