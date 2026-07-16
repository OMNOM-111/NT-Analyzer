"""In-app notification inbox mirrored from Telegram delivery.

When ``telegram_service._notify`` claims a delivery signature, the same event is
recorded here so the Aurora UI can show an SMS-style banner while Orchestrator
is closed (or showing another conversation). Interactive replies already visible
in an open chat are suppressed on the client.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import runtime_env

_LOCK = threading.RLock()
MAX_ITEMS = 120
MAX_AGE_HOURS = 72


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _path() -> Path:
    return runtime_env.data_path("operations", "in_app_notifications.json", project_root=_root())


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_ts(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _clean_cid(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:64]


def _read() -> Dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {"items": [], "updated_at_utc": ""}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"items": [], "updated_at_utc": ""}
    doc = parsed if isinstance(parsed, dict) else {}
    items = doc.get("items") if isinstance(doc.get("items"), list) else []
    return {
        "items": [row for row in items if isinstance(row, dict)],
        "updated_at_utc": str(doc.get("updated_at_utc") or ""),
    }


def _write(doc: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "items": list(doc.get("items") or [])[:MAX_ITEMS],
        "updated_at_utc": _now(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _prune(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc).timestamp() - MAX_AGE_HOURS * 3600
    kept = [row for row in items if _iso_ts(row.get("created_at_utc")) >= cutoff]
    return kept[-MAX_ITEMS:]


def record(
    title: str,
    lines: Optional[List[str]] = None,
    *,
    urgent: bool = False,
    conversation_id: str = "",
    conversation_title: str = "",
    dedupe_key: str = "",
    kind: str = "",
) -> Optional[Dict[str, Any]]:
    """Append one notice. Returns the row, or None when deduped / empty."""
    clean_title = str(title or "").strip()[:200]
    body_lines = [str(line).strip() for line in (lines or []) if str(line).strip()]
    body = "\n".join(body_lines)[:2000]
    if not clean_title and not body:
        return None
    key = str(dedupe_key or "").strip()[:200]
    cid = _clean_cid(conversation_id)
    with _LOCK:
        doc = _read()
        items = list(doc.get("items") or [])
        if key:
            for row in items:
                if str(row.get("dedupe_key") or "") == key:
                    return None
        row = {
            "id": "n_" + uuid.uuid4().hex[:16],
            "title": clean_title or "Уведомление",
            "body": body,
            "urgent": bool(urgent),
            "conversation_id": cid,
            "conversation_title": str(conversation_title or "").strip()[:120],
            "dedupe_key": key,
            "kind": str(kind or "").strip()[:64],
            "created_at_utc": _now(),
            "read": False,
        }
        items.append(row)
        doc["items"] = _prune(items)
        _write(doc)
        return dict(row)


def list_notices(*, unread_only: bool = True, since: str = "", limit: int = 30) -> Dict[str, Any]:
    lim = max(1, min(200, int(limit or 30)))
    since_ts = _iso_ts(since)
    with _LOCK:
        doc = _read()
        items = _prune(list(doc.get("items") or []))
        if items != list(doc.get("items") or []):
            doc["items"] = items
            _write(doc)
    rows: List[Dict[str, Any]] = []
    unread_by_conversation: Dict[str, int] = {}
    for row in items:
        if row.get("read"):
            continue
        cid = _clean_cid(row.get("conversation_id")) or "_none"
        unread_by_conversation[cid] = unread_by_conversation.get(cid, 0) + 1
    for row in reversed(items):
        if unread_only and row.get("read"):
            continue
        if since_ts and _iso_ts(row.get("created_at_utc")) < since_ts:
            continue
        rows.append(dict(row))
        if len(rows) >= lim:
            break
    return {
        "ok": True,
        "items": rows,
        "unread_count": sum(1 for row in items if not row.get("read")),
        "total_count": len(items),
        "unread_by_conversation": unread_by_conversation,
        "updated_at_utc": str(doc.get("updated_at_utc") or ""),
    }


def ack(*, ids: Optional[List[str]] = None, conversation_id: str = "") -> Dict[str, Any]:
    """Mark notices read by id list and/or conversation_id."""
    wanted = {str(x).strip() for x in (ids or []) if str(x).strip()}
    cid = _clean_cid(conversation_id)
    if not wanted and not cid:
        return {"ok": True, "acked": 0}
    acked = 0
    with _LOCK:
        doc = _read()
        items = list(doc.get("items") or [])
        for row in items:
            if row.get("read"):
                continue
            hit = False
            if wanted and str(row.get("id") or "") in wanted:
                hit = True
            if cid and str(row.get("conversation_id") or "") == cid:
                hit = True
            if hit:
                row["read"] = True
                row["read_at_utc"] = _now()
                acked += 1
        doc["items"] = _prune(items)
        _write(doc)
    return {"ok": True, "acked": acked}


def delete(*, ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Permanently remove notices by id."""
    wanted = {str(x).strip() for x in (ids or []) if str(x).strip()}
    if not wanted:
        return {"ok": True, "deleted": 0}
    deleted = 0
    with _LOCK:
        doc = _read()
        items = list(doc.get("items") or [])
        kept: List[Dict[str, Any]] = []
        for row in items:
            if str(row.get("id") or "") in wanted:
                deleted += 1
                continue
            kept.append(row)
        doc["items"] = _prune(kept)
        _write(doc)
    return {"ok": True, "deleted": deleted}


def clear(*, mode: str = "all") -> Dict[str, Any]:
    """Clear notices. mode: all | read | unread."""
    kind = str(mode or "all").strip().lower()
    if kind not in {"all", "read", "unread"}:
        kind = "all"
    removed = 0
    with _LOCK:
        doc = _read()
        items = list(doc.get("items") or [])
        if kind == "all":
            removed = len(items)
            kept: List[Dict[str, Any]] = []
        elif kind == "read":
            kept = [row for row in items if not row.get("read")]
            removed = len(items) - len(kept)
        else:
            kept = [row for row in items if row.get("read")]
            removed = len(items) - len(kept)
        doc["items"] = _prune(kept)
        _write(doc)
    return {"ok": True, "cleared": removed, "mode": kind}
