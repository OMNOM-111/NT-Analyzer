"""Safe liveness/readiness payloads for StratForge service supervision."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any, Callable, Dict, Mapping, Optional


PRODUCTION_COMPONENTS = (
    "database",
    "queue",
    "object_storage",
    "signing_key",
    "connector_control",
    "telegram_consumer",
)


def liveness_payload(config: Any) -> Dict[str, Any]:
    return {
        "ok": True,
        "status": "alive",
        "deployment": config.public_dict(),
    }


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


def _run_probe(probe: Optional[Callable[[], Any]]) -> Dict[str, Any]:
    if probe is None:
        return {"ok": False, "code": "probe_not_registered"}
    try:
        result = probe()
    except Exception:
        return {"ok": False, "code": "probe_failed"}
    if isinstance(result, Mapping):
        ok = bool(result.get("ok"))
        code = str(result.get("code") or ("ok" if ok else "not_ready"))
        return {"ok": ok, "code": code[:64]}
    ok = bool(result)
    return {"ok": ok, "code": "ok" if ok else "not_ready"}


def readiness_payload(
    config: Any,
    *,
    probes: Optional[Mapping[str, Callable[[], Any]]] = None,
    minimum_free_mb: Optional[int] = None,
    optional_components: Optional[Mapping[str, str]] = None,
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
    """
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
    if config.environment in {"production", "canary"}:
        for name in PRODUCTION_COMPONENTS:
            probe = registered.get(name)
            if probe is None and name in optional:
                checks[name] = {"ok": False, "code": str(optional[name])[:64]}
                excluded_from_overall.add(name)
            else:
                checks[name] = _run_probe(probe)
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
