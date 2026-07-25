"""Process-local exact response cache for safe, repeatable agent analysis.

Provider prompt caches still perform the main prefix reuse.  This cache avoids a
network call entirely when the exact same immutable analysis packet is requested
again during the same backend session.  Keys are SHA-256 hashes; prompt text and
API keys are never stored in the key index or usage log.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional


_LOCK = threading.RLock()
_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
MAX_ENTRIES = 256
DEFAULT_TTL_SEC = 3600


def make_key(*, agent_id: str, model: str, system_prompt: str, prompt: str,
             max_output_tokens: int, workspace_id: str = "") -> str:
    canonical = json.dumps({
        "agent_id": agent_id,
        "model": model,
        "system_prompt": system_prompt,
        "prompt": prompt,
        "max_output_tokens": int(max_output_tokens),
        "workspace_id": str(workspace_id or ""),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get(key: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _LOCK:
        row = _CACHE.get(str(key))
        if not row:
            return None
        if float(row.get("expires_epoch") or 0) <= now:
            _CACHE.pop(str(key), None)
            return None
        _CACHE.move_to_end(str(key))
        return copy.deepcopy(row.get("value") or {})


def set(key: str, value: Dict[str, Any], *, ttl_sec: int = DEFAULT_TTL_SEC) -> None:
    safe = {
        "response": str(value.get("response") or value.get("content") or "")[:30000],
        "actual_model": str(value.get("actual_model") or value.get("model") or "")[:180],
        "source_input_tokens": int(value.get("input_tokens") or 0),
        "source_output_tokens": int(value.get("output_tokens") or 0),
    }
    with _LOCK:
        _CACHE[str(key)] = {
            "expires_epoch": time.time() + max(30, min(int(ttl_sec), 86_400)),
            "value": safe,
        }
        _CACHE.move_to_end(str(key))
        while len(_CACHE) > MAX_ENTRIES:
            _CACHE.popitem(last=False)


def clear() -> None:
    with _LOCK:
        _CACHE.clear()


def stats() -> Dict[str, Any]:
    now = time.time()
    with _LOCK:
        expired = [key for key, row in _CACHE.items() if float(row.get("expires_epoch") or 0) <= now]
        for key in expired:
            _CACHE.pop(key, None)
        return {"entries": len(_CACHE), "max_entries": MAX_ENTRIES, "default_ttl_sec": DEFAULT_TTL_SEC}
