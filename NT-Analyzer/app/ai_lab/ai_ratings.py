"""Star-rating aggregates: roles / models / role+model pairs for routing."""
from __future__ import annotations

import json
import math
import os
import random
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import runtime_env


_LOCK = threading.RLock()
EXPLORATION_RATE = 0.10  # 10% explore alternate models


def _root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _store_path() -> Path:
    if runtime_env.is_staging():
        return runtime_env.data_path(
            "ai_lab", "registry", "star_ratings.json", project_root=_root(),
        )
    return _root() / "ai_lab" / "registry" / "star_ratings.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {
            "version": 2, "role_stats": {}, "model_stats": {},
            "role_model_stats": {}, "workspace_stats": {}, "events": [],
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "version": 2, "role_stats": {}, "model_stats": {},
            "role_model_stats": {}, "workspace_stats": {}, "events": [],
        }
    return doc if isinstance(doc, dict) else {
        "version": 2, "role_stats": {}, "model_stats": {},
        "role_model_stats": {}, "workspace_stats": {}, "events": [],
    }


def _save(doc: Dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _bucket_update(bucket: Dict[str, Any], score: int, weight: float = 1.0) -> None:
    weight = max(0.000001, float(weight))
    n = int(bucket.get("count") or 0) + 1
    # ``count`` remains the number of feedback events shown to the owner;
    # the average itself is weighted so operational notices cannot skew routing.
    previous_weight = float(bucket.get("rating_weight") or max(0, n - 1))
    weighted_sum = float(bucket.get("weighted_sum") or (float(bucket.get("avg") or 0) * previous_weight))
    bucket["count"] = n
    bucket["rating_weight"] = previous_weight + weight
    bucket["weighted_sum"] = weighted_sum + score * weight
    bucket["avg"] = round(bucket["weighted_sum"] / bucket["rating_weight"], 4)
    bucket["sum"] = float(bucket.get("sum") or 0) + score
    if score == 1:
        bucket["ones"] = int(bucket.get("ones") or 0) + 1
    bucket["updated_at_utc"] = _now_iso()
    # Soft decay marker for future weighted windows.
    bucket["weight"] = float(bucket.get("weight") or 0) * 0.995 + 1.0


def _bucket_remove(bucket: Dict[str, Any], score: int, weight: float = 1.0) -> bool:
    """Remove one previously persisted event; return True for an empty bucket."""
    weight = max(0.000001, float(weight))
    count = max(0, int(bucket.get("count") or 0) - 1)
    previous_weight = float(bucket.get("rating_weight") or (count + 1))
    previous_sum = float(
        bucket.get("weighted_sum")
        or (float(bucket.get("avg") or 0) * previous_weight)
    )
    rating_weight = max(0.0, previous_weight - weight)
    weighted_sum = max(0.0, previous_sum - score * weight)
    if count <= 0 or rating_weight <= 0.0000001:
        return True
    bucket["count"] = count
    bucket["rating_weight"] = rating_weight
    bucket["weighted_sum"] = weighted_sum
    bucket["avg"] = round(weighted_sum / rating_weight, 4)
    bucket["sum"] = max(0.0, float(bucket.get("sum") or 0) - score)
    if score == 1:
        bucket["ones"] = max(0, int(bucket.get("ones") or 0) - 1)
    bucket["updated_at_utc"] = _now_iso()
    return False


def _stats_container(doc: Dict[str, Any], workspace_id: str = "", *, create: bool = True) -> Dict[str, Any]:
    workspace = str(workspace_id or "").strip()
    if not workspace:
        return doc
    workspaces = doc.setdefault("workspace_stats", {}) if create else (doc.get("workspace_stats") or {})
    if create:
        return workspaces.setdefault(workspace, {
            "role_stats": {}, "model_stats": {}, "role_model_stats": {},
        })
    return workspaces.get(workspace) or {}


def _apply_event(container: Dict[str, Any], event: Dict[str, Any], *, remove: bool = False) -> None:
    role = str(event.get("role_id") or "general")
    model = str(event.get("model_id") or "unknown")
    provider = str(event.get("provider") or "")
    score = int(event.get("rating") or 0)
    weight = max(0.000001, float(event.get("weight") or 1.0))
    pair = f"{role}::{model}"
    definitions = (
        ("role_stats", role, {}),
        ("model_stats", model, {"provider": provider}),
        ("role_model_stats", pair, {
            "role_id": role, "model_id": model, "provider": provider,
        }),
    )
    for mapping_name, key, defaults in definitions:
        mapping = container.setdefault(mapping_name, {})
        bucket = mapping.get(key)
        if remove:
            if isinstance(bucket, dict) and _bucket_remove(bucket, score, weight):
                mapping.pop(key, None)
            continue
        if not isinstance(bucket, dict):
            bucket = dict(defaults)
            mapping[key] = bucket
        elif provider and mapping_name != "role_stats":
            bucket["provider"] = provider
        _bucket_update(bucket, score, weight)


def _event_key(event_id: str, message_id: str, workspace_id: str) -> str:
    explicit = str(event_id or "").strip()
    if explicit:
        return explicit[:300]
    message = str(message_id or "").strip()
    if message:
        return f"message_rating:{workspace_id or 'global'}:{message}"[:300]
    return f"rating:{uuid.uuid4().hex}"


def record_rating(
    *,
    role_id: str,
    model_id: str,
    provider: str = "",
    rating: int,
    task_category: str = "",
    weight: float = 1.0,
    event_id: str = "",
    message_id: str = "",
    workspace_id: str = "",
    user_id: str = "",
    source: str = "",
) -> Dict[str, Any]:
    role = str(role_id or "general").strip() or "general"
    model = str(model_id or "unknown").strip() or "unknown"
    provider_id = str(provider or "").strip()
    score = int(rating)
    if score not in {1, 2, 3}:
        raise ValueError("rating must be 1, 2, or 3")
    event_weight = float(weight)
    if not math.isfinite(event_weight) or event_weight <= 0:
        raise ValueError("weight must be a finite positive number")
    workspace = str(workspace_id or "").strip()[:160]
    message = str(message_id or "").strip()[:160]
    key = _event_key(event_id, message, workspace)
    event = {
        "event_id": key, "at": _now_iso(), "role_id": role,
        "model_id": model, "provider": provider_id, "rating": score,
        "task_category": str(task_category or "")[:60], "weight": event_weight,
        "message_id": message, "workspace_id": workspace,
        "user_id": str(user_id or "").strip()[:160],
        "source": str(source or "").strip()[:80],
    }
    with _LOCK:
        doc = _load()
        events = [row for row in (doc.get("events") or []) if isinstance(row, dict)]
        old_index = next(
            (index for index, row in enumerate(events) if str(row.get("event_id") or "") == key),
            -1,
        )
        if old_index >= 0:
            old = events[old_index]
            aggregate_fields = (
                "role_id", "model_id", "provider", "rating", "weight", "workspace_id",
            )
            if any(old.get(field) != event.get(field) for field in aggregate_fields):
                _apply_event(doc, old, remove=True)
                old_workspace = str(old.get("workspace_id") or "")
                if old_workspace:
                    _apply_event(_stats_container(doc, old_workspace), old, remove=True)
                _apply_event(doc, event)
                if workspace:
                    _apply_event(_stats_container(doc, workspace), event)
            events[old_index] = event
        else:
            _apply_event(doc, event)
            if workspace:
                _apply_event(_stats_container(doc, workspace), event)
            events.append(event)
        # Keep the complete event ledger: dropping an old event would make a
        # later re-rating of that message impossible to subtract correctly.
        doc["events"] = events
        doc["version"] = max(2, int(doc.get("version") or 1))
        _save(doc)
    return tables(workspace_id=workspace)


def tables(*, workspace_id: str = "") -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        selected = _stats_container(doc, workspace_id, create=False) if workspace_id else doc
    def rows(mapping: Dict[str, Any], key_name: str) -> List[Dict[str, Any]]:
        out = []
        for key, bucket in (mapping or {}).items():
            out.append({
                key_name: key,
                "avg": bucket.get("avg"),
                "count": bucket.get("count"),
                "ones": bucket.get("ones") or 0,
                "provider": bucket.get("provider") or "",
                "role_id": bucket.get("role_id") or "",
                "model_id": bucket.get("model_id") or "",
                "updated_at_utc": bucket.get("updated_at_utc") or "",
            })
        out.sort(key=lambda row: (-float(row.get("avg") or 0), -int(row.get("count") or 0)))
        return out
    return {
        "ok": True,
        "roles": rows(selected.get("role_stats") or {}, "role_id"),
        "models": rows(selected.get("model_stats") or {}, "model_id"),
        "role_model": rows(selected.get("role_model_stats") or {}, "pair"),
        "workspace_id": str(workspace_id or ""),
        "exploration_rate": EXPLORATION_RATE,
    }


def pair_score(role_id: str, model_id: str, *, workspace_id: str = "") -> float:
    pair = f"{str(role_id or 'general')}::{str(model_id or 'unknown')}"
    with _LOCK:
        doc = _load()
        selected = _stats_container(doc, workspace_id, create=False) if workspace_id else doc
        bucket = (selected.get("role_model_stats") or {}).get(pair) or {}
    if not bucket:
        return 2.0  # neutral prior
    avg = float(bucket.get("avg") or 2.0)
    ones = int(bucket.get("ones") or 0)
    count = max(1, int(bucket.get("count") or 1))
    penalty = (ones / count) * 0.35
    return max(0.5, avg - penalty)


def rank_agents(
    role: str,
    agents: List[Dict[str, Any]],
    *,
    explore: bool = True,
    workspace_id: str = "",
) -> List[Dict[str, Any]]:
    """Re-order already-gated candidates using role+model star ratings.

    Does not bypass key/budget/cooldown filters — only re-sorts the safe list.
    """
    if not agents:
        return agents
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for agent in agents:
        model = str(agent.get("model") or "")
        score = pair_score(role, model, workspace_id=workspace_id)
        scored.append((score, agent))
    scored.sort(key=lambda item: -item[0])
    ordered = [agent for _, agent in scored]
    if explore and len(ordered) > 1 and random.random() < EXPLORATION_RATE:
        # Swap top with a random lower candidate for exploration.
        idx = random.randint(1, len(ordered) - 1)
        ordered[0], ordered[idx] = ordered[idx], ordered[0]
    return ordered
