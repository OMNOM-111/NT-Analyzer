"""Mark experiments without recent activity as cancelled (stale sweep).

A heartbeat-based TTL: any experiment whose status is non-terminal AND whose
last activity line is older than ``heartbeat_ttl_hours`` (default 6h) is
transitioned to ``cancelled`` with reason ``stale_sweep_no_heartbeat``.

This sweeps on server start and on demand via
``POST /api/ai-lab/maintenance/sweep-stale``.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths, registry


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None


def _last_activity_ts(experiment_id: str) -> Optional[datetime]:
    p = paths.ACTIVITY_DIR / f"{experiment_id}.jsonl"
    if not p.exists() or p.stat().st_size == 0:
        return None
    # Read the file backwards just enough to find the last non-empty line.
    last_line: str = ""
    try:
        with p.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            window = min(4096, size)
            fh.seek(size - window)
            tail = fh.read(window).decode("utf-8", errors="replace")
        for line in reversed(tail.splitlines()):
            line = line.strip()
            if line:
                last_line = line
                break
    except OSError:
        return None
    if not last_line:
        return None
    try:
        rec = json.loads(last_line)
    except json.JSONDecodeError:
        return None
    return _parse_iso(rec.get("ts"))


def sweep_stale(
    now: Optional[datetime] = None,
    heartbeat_ttl_hours: float = 6.0,
) -> Dict[str, Any]:
    """Return ``{cancelled: [...], scanned, ttl_hours}``."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=heartbeat_ttl_hours)
    cancelled: List[Dict[str, Any]] = []
    scanned = 0
    for exp in registry.list_experiments():
        scanned += 1
        status = exp.get("status") or ""
        if registry.is_terminal(status):
            continue
        eid = exp.get("experiment_id")
        if not eid:
            continue
        last_ts = _last_activity_ts(eid)
        # Fallback to created_at if no activity at all.
        if last_ts is None:
            last_ts = _parse_iso(exp.get("updated_at_utc") or exp.get("created_at_utc"))
        if last_ts is None:
            continue
        if last_ts > cutoff:
            continue
        try:
            registry.transition_status(
                eid, "cancelled",
                reason="stale_sweep_no_heartbeat",
                extra={"stale_sweep": {
                    "swept_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "last_activity_utc": last_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "ttl_hours": heartbeat_ttl_hours,
                }},
            )
            cancelled.append({
                "experiment_id": eid,
                "previous_status": status,
                "last_activity_utc": last_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
        except Exception:
            continue
    return {
        "ok": True,
        "scanned": scanned,
        "cancelled": cancelled,
        "ttl_hours": heartbeat_ttl_hours,
        "swept_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


_BG_THREAD: Optional[threading.Thread] = None
_BG_STOP = threading.Event()


def start_background_sweeper(interval_sec: int = 1800, ttl_hours: float = 6.0) -> None:
    """Idempotently start a daemon thread that calls sweep_stale every N sec."""
    global _BG_THREAD
    if _BG_THREAD is not None and _BG_THREAD.is_alive():
        return
    _BG_STOP.clear()

    def _loop() -> None:
        # Run once immediately.
        try:
            sweep_stale(heartbeat_ttl_hours=ttl_hours)
        except Exception:
            pass
        while not _BG_STOP.wait(interval_sec):
            try:
                sweep_stale(heartbeat_ttl_hours=ttl_hours)
            except Exception:
                continue

    _BG_THREAD = threading.Thread(target=_loop, name="ai-lab-stale-sweeper", daemon=True)
    _BG_THREAD.start()


def stop_background_sweeper() -> None:
    """Stop the supervised sweeper without waiting for its full interval."""
    global _BG_THREAD
    _BG_STOP.set()
    current = _BG_THREAD
    if current and current is not threading.current_thread():
        current.join(timeout=5.0)
    if current is None or not current.is_alive():
        _BG_THREAD = None
