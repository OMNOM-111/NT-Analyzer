"""Star-rating aggregates: roles / models / role+model pairs for routing."""
from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_LOCK = threading.RLock()
EXPLORATION_RATE = 0.10  # 10% explore alternate models


def _root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _store_path() -> Path:
    return _root() / "ai_lab" / "registry" / "star_ratings.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {"version": 1, "role_stats": {}, "model_stats": {}, "role_model_stats": {}, "events": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "role_stats": {}, "model_stats": {}, "role_model_stats": {}, "events": []}
    return doc if isinstance(doc, dict) else {"version": 1, "role_stats": {}, "model_stats": {}, "role_model_stats": {}, "events": []}


def _save(doc: Dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _bucket_update(bucket: Dict[str, Any], score: int) -> None:
    n = int(bucket.get("count") or 0) + 1
    avg = float(bucket.get("avg") or 0)
    bucket["count"] = n
    bucket["avg"] = round(avg + (score - avg) / n, 4)
    bucket["sum"] = float(bucket.get("sum") or 0) + score
    if score == 1:
        bucket["ones"] = int(bucket.get("ones") or 0) + 1
    bucket["updated_at_utc"] = _now_iso()
    # Soft decay marker for future weighted windows.
    bucket["weight"] = float(bucket.get("weight") or 0) * 0.995 + 1.0


def record_rating(
    *,
    role_id: str,
    model_id: str,
    provider: str = "",
    rating: int,
    task_category: str = "",
) -> Dict[str, Any]:
    role = str(role_id or "general").strip() or "general"
    model = str(model_id or "unknown").strip() or "unknown"
    provider_id = str(provider or "").strip()
    score = int(rating)
    pair = f"{role}::{model}"
    with _LOCK:
        doc = _load()
        role_stats = doc.setdefault("role_stats", {})
        model_stats = doc.setdefault("model_stats", {})
        pair_stats = doc.setdefault("role_model_stats", {})
        _bucket_update(role_stats.setdefault(role, {}), score)
        _bucket_update(model_stats.setdefault(model, {"provider": provider_id}), score)
        _bucket_update(pair_stats.setdefault(pair, {"role_id": role, "model_id": model, "provider": provider_id}), score)
        events = doc.setdefault("events", [])
        events.append({
            "at": _now_iso(), "role_id": role, "model_id": model, "provider": provider_id,
            "rating": score, "task_category": str(task_category or "")[:60],
        })
        doc["events"] = events[-500:]
        _save(doc)
    return tables()


def tables() -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
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
        "roles": rows(doc.get("role_stats") or {}, "role_id"),
        "models": rows(doc.get("model_stats") or {}, "model_id"),
        "role_model": rows(doc.get("role_model_stats") or {}, "pair"),
        "exploration_rate": EXPLORATION_RATE,
    }


def pair_score(role_id: str, model_id: str) -> float:
    pair = f"{str(role_id or 'general')}::{str(model_id or 'unknown')}"
    with _LOCK:
        doc = _load()
        bucket = (doc.get("role_model_stats") or {}).get(pair) or {}
    if not bucket:
        return 2.0  # neutral prior
    avg = float(bucket.get("avg") or 2.0)
    ones = int(bucket.get("ones") or 0)
    count = max(1, int(bucket.get("count") or 1))
    penalty = (ones / count) * 0.35
    return max(0.5, avg - penalty)


def rank_agents(role: str, agents: List[Dict[str, Any]], *, explore: bool = True) -> List[Dict[str, Any]]:
    """Re-order already-gated candidates using role+model star ratings.

    Does not bypass key/budget/cooldown filters — only re-sorts the safe list.
    """
    if not agents:
        return agents
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for agent in agents:
        model = str(agent.get("model") or "")
        score = pair_score(role, model)
        scored.append((score, agent))
    scored.sort(key=lambda item: -item[0])
    ordered = [agent for _, agent in scored]
    if explore and len(ordered) > 1 and random.random() < EXPLORATION_RATE:
        # Swap top with a random lower candidate for exploration.
        idx = random.randint(1, len(ordered) - 1)
        ordered[0], ordered[idx] = ordered[idx], ordered[0]
    return ordered
