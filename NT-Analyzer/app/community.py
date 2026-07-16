"""Community contour — users among themselves (NOT owner Orchestrator).

Storage: ``data/runtime/community.json`` (messages, posts, strategy cards,
ratings, moderation). Telegram duplicate is a separate optional channel and
must never write into owner Orchestrator topics.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class CommunityError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


_LOCK = threading.RLock()
_MAX_MSG = 4000


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _store_path() -> Path:
    return _root() / "data" / "runtime" / "community.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {
            "version": 1,
            "messages": [],
            "posts": [],
            "strategies": [],
            "copies": [],
            "reports": [],
            "blocks": [],
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "messages": [], "posts": [], "strategies": [], "copies": [], "reports": [], "blocks": []}
    return doc if isinstance(doc, dict) else {"version": 1, "messages": [], "posts": [], "strategies": [], "copies": [], "reports": [], "blocks": []}


def _save(doc: Dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _blocked(doc: Dict[str, Any], user_id: int) -> bool:
    return any(int(row.get("user_id") or 0) == int(user_id) for row in doc.get("blocks") or [])


def feed(*, limit: int = 50) -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        messages = list(reversed(doc.get("messages") or []))[: max(1, min(int(limit), 200))]
        strategies = list(reversed(doc.get("strategies") or []))[:50]
        posts = list(reversed(doc.get("posts") or []))[:50]
    return {
        "ok": True,
        "contour": "community",
        "messages": list(reversed(messages)),
        "strategies": strategies,
        "posts": posts,
        "ratings": ratings(),
    }


def post_message(user_id: Any, *, text: str, display_name: str = "") -> Dict[str, Any]:
    uid = int(user_id or 0)
    body = str(text or "").strip()
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    if not body or len(body) > _MAX_MSG:
        raise CommunityError("Сообщение пустое или слишком длинное.")
    with _LOCK:
        doc = _load()
        if _blocked(doc, uid):
            raise CommunityError("Вы заблокированы в community.", 403)
        row = {
            "message_id": "cmsg_" + secrets.token_hex(6),
            "user_id": uid,
            "display_name": str(display_name or f"user_{uid}")[:80],
            "text": body,
            "created_at_utc": _now_iso(),
            "contour": "community",
        }
        doc.setdefault("messages", []).append(row)
        doc["messages"] = doc["messages"][-1000:]
        _save(doc)
    return {"ok": True, "message": row, "telegram_mirror": False}


def publish_strategy(
    user_id: Any,
    *,
    title: str,
    metrics: Optional[Dict[str, Any]] = None,
    notes: str = "",
    display_name: str = "",
) -> Dict[str, Any]:
    uid = int(user_id or 0)
    name = str(title or "").strip()
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    if not name:
        raise CommunityError("Укажите название стратегии.")
    with _LOCK:
        doc = _load()
        if _blocked(doc, uid):
            raise CommunityError("Вы заблокированы в community.", 403)
        row = {
            "strategy_id": "cstr_" + secrets.token_hex(5),
            "user_id": uid,
            "display_name": str(display_name or f"user_{uid}")[:80],
            "title": name[:120],
            "notes": str(notes or "")[:2000],
            "metrics": dict(metrics or {}),
            "copies": 0,
            "created_at_utc": _now_iso(),
            "status": "published",
        }
        doc.setdefault("strategies", []).append(row)
        doc["strategies"] = doc["strategies"][-500:]
        _save(doc)
    return {"ok": True, "strategy": row}


def copy_strategy(user_id: Any, strategy_id: str) -> Dict[str, Any]:
    uid = int(user_id or 0)
    sid = str(strategy_id or "").strip()
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    with _LOCK:
        doc = _load()
        if _blocked(doc, uid):
            raise CommunityError("Вы заблокированы в community.", 403)
        src = next((row for row in doc.get("strategies") or [] if row.get("strategy_id") == sid), None)
        if src is None:
            raise CommunityError("Стратегия не найдена.", 404)
        src["copies"] = int(src.get("copies") or 0) + 1
        copy_row = {
            "copy_id": "ccopy_" + secrets.token_hex(5),
            "strategy_id": sid,
            "from_user_id": int(src.get("user_id") or 0),
            "to_user_id": uid,
            "title": src.get("title"),
            "metrics": dict(src.get("metrics") or {}),
            "created_at_utc": _now_iso(),
        }
        doc.setdefault("copies", []).append(copy_row)
        _save(doc)
    return {"ok": True, "copy": copy_row, "strategy": src}


def ratings() -> Dict[str, Any]:
    with _LOCK:
        doc = _load()
        strategies = list(doc.get("strategies") or [])
    def score(row: Dict[str, Any]) -> float:
        m = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        net = float(m.get("net_profit") or m.get("return_pct") or 0)
        dd = abs(float(m.get("max_drawdown") or m.get("drawdown") or 1))
        copies = int(row.get("copies") or 0)
        # Not only return: reward risk-adjusted + popularity.
        return (net / max(dd, 1.0)) + copies * 0.5

    ranked = sorted(strategies, key=score, reverse=True)
    by_return = sorted(
        strategies,
        key=lambda row: float((row.get("metrics") or {}).get("net_profit") or 0),
        reverse=True,
    )
    by_copies = sorted(strategies, key=lambda row: int(row.get("copies") or 0), reverse=True)
    by_new = sorted(strategies, key=lambda row: str(row.get("created_at_utc") or ""), reverse=True)
    authors: Dict[int, Dict[str, Any]] = {}
    for row in strategies:
        uid = int(row.get("user_id") or 0)
        bucket = authors.setdefault(uid, {"user_id": uid, "display_name": row.get("display_name"), "strategies": 0, "copies": 0})
        bucket["strategies"] += 1
        bucket["copies"] += int(row.get("copies") or 0)
    return {
        "composite": ranked[:20],
        "by_return": by_return[:20],
        "by_copies": by_copies[:20],
        "newest": by_new[:20],
        "authors": sorted(authors.values(), key=lambda row: row["copies"], reverse=True)[:20],
    }


def report_abuse(user_id: Any, *, target_id: str, reason: str = "") -> Dict[str, Any]:
    uid = int(user_id or 0)
    if uid <= 0:
        raise CommunityError("Требуется вход.", 401)
    with _LOCK:
        doc = _load()
        row = {
            "report_id": "crep_" + secrets.token_hex(5),
            "from_user_id": uid,
            "target_id": str(target_id or "")[:80],
            "reason": str(reason or "")[:500],
            "created_at_utc": _now_iso(),
        }
        doc.setdefault("reports", []).append(row)
        _save(doc)
    return {"ok": True, "report": row}


def moderate_block(owner_id: Any, target_user_id: Any, *, reason: str = "") -> Dict[str, Any]:
    # Owner check is done by server route.
    tid = int(target_user_id or 0)
    with _LOCK:
        doc = _load()
        doc.setdefault("blocks", []).append({
            "user_id": tid,
            "by_owner_id": int(owner_id or 0),
            "reason": str(reason or "")[:300],
            "created_at_utc": _now_iso(),
        })
        _save(doc)
    return {"ok": True, "blocked_user_id": tid}


def moderate_delete_message(owner_id: Any, message_id: str) -> Dict[str, Any]:
    mid = str(message_id or "")
    with _LOCK:
        doc = _load()
        before = len(doc.get("messages") or [])
        doc["messages"] = [row for row in doc.get("messages") or [] if row.get("message_id") != mid]
        _save(doc)
    return {"ok": True, "deleted": before - len(doc.get("messages") or []), "by_owner_id": int(owner_id or 0)}
