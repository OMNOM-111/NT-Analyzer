"""Last computed AI Center overview per authorized identity.

The page paints this snapshot at once and always asks for a fresh projection
right after, so a person sees useful content instead of a 10 s skeleton.
Nothing here grants access: every request is authorized before a snapshot is
read, and the key covers everything authorization depends on, so a revoked
capability, another workspace or another user can never reuse an entry.

A fresh request reuses an entry only while the Agent World store is unchanged
and the entry is a few seconds old (concurrent page reads); clock-derived
states such as expiry are therefore at most REUSE_SECONDS behind. Writes made
through the AI Center clear every entry.
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from datetime import datetime, timezone

from .. import runtime_env

REUSE_SECONDS = 5.0
_MAX_ENTRIES = 64
_LOCK = threading.Lock()
_ENTRIES: dict = {}


def _enabled() -> bool:
    return os.environ.get("STRATFORGE_AGENT_WORLD_STORAGE", "sqlite").strip().lower() == "sqlite"


def _watermark():
    path = runtime_env.data_path("ai_lab", "agent-world.sqlite3")
    marks = []
    for candidate in (path, path.with_name(path.name + "-wal")):
        try:
            stat = candidate.stat()
            marks.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            marks.append(None)
    return tuple(marks)


def _key(authorized):
    scope, context = authorized["chat_scope"], authorized["context"]
    snapshot = authorized.get("snapshot")
    return json.dumps([
        str(runtime_env.data_root()), context.scope.environment.value, context.scope.workspace_id,
        str(context.user_uuid), scope.get("user_id"), scope.get("workspace_kind"), scope.get("membership_role"),
        bool(scope.get("is_owner")), bool(scope.get("uses_owner_runtime")), scope.get("capabilities"),
        bool(authorized.get("read_only")), str(getattr(snapshot, "revision", snapshot)),
    ], sort_keys=True, default=str)


def fresh(authorized, build):
    """Return a current enriched overview, computing it unless just computed."""
    if not _enabled():
        return build()
    key, mark = _key(authorized), _watermark()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry and entry["mark"] == mark and time.monotonic() - entry["at"] < REUSE_SECONDS:
            return copy.deepcopy(entry["value"])
    value = build()
    with _LOCK:
        _ENTRIES.pop(key, None)
        _ENTRIES[key] = {"mark": mark, "at": time.monotonic(), "value": copy.deepcopy(value),
                         "computed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
        while len(_ENTRIES) > _MAX_ENTRIES:
            _ENTRIES.pop(next(iter(_ENTRIES)))
    return value


def last(authorized):
    """The previous overview for exactly this authorization, or None."""
    if not _enabled():
        return None
    with _LOCK:
        entry = _ENTRIES.get(_key(authorized))
        if entry is None:
            return None
        return copy.deepcopy(entry["value"]), entry["computed_at"]


def invalidate():
    with _LOCK:
        _ENTRIES.clear()
