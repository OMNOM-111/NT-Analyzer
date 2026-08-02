"""Hidden admin action journal.

Read-only, owner-only view that merges the append-only audit logs written by the
account, Mini App, subscription and PayPal subsystems into one chronological
feed. Nothing here writes; the individual subsystems remain the source of truth.
The schema is deliberately loose so new audit files can be added by extending
``CATEGORIES`` without touching callers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from . import runtime_env


CATEGORIES: Dict[str, Dict[str, str]] = {
    "account":       {"file": "account-auth.jsonl",     "label": "Аккаунты"},
    "mini_app":      {"file": "telegram-mini-app.jsonl", "label": "Mini App / API"},
    "subscriptions": {"file": "subscriptions.jsonl",     "label": "Подписки"},
    "paypal":        {"file": "paypal-webhook.jsonl",    "label": "PayPal"},
    "support":       {"file": "user-support.jsonl",     "label": "Поддержка пользователей"},
}

MAX_LIMIT = 1000


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _audit_dir() -> Path:
    return runtime_env.data_path("audit", project_root=_root())


def categories() -> List[Dict[str, str]]:
    return [{"id": cid, "label": meta["label"]} for cid, meta in CATEGORIES.items()]


def _event(category: str, row: Dict[str, Any]) -> str:
    if category == "mini_app":
        return f"{row.get('method', '')} {row.get('path', '')}".strip() or "запрос"
    return str(row.get("event") or row.get("event_type") or "—")


def _summary(category: str, row: Dict[str, Any]) -> str:
    if category == "account":
        parts = []
        if row.get("user_id"):
            parts.append(f"user={row['user_id']}")
        if row.get("owner_id"):
            parts.append(f"owner={row['owner_id']}")
        if row.get("ip"):
            parts.append(f"ip={row['ip']}")
        return " · ".join(parts)
    if category == "mini_app":
        parts = [f"→ {row.get('status', '')}"]
        if row.get("user_id"):
            parts.append(f"user={row['user_id']}")
        if row.get("role"):
            parts.append(str(row["role"]))
        if row.get("error"):
            parts.append(str(row["error"])[:120])
        return " · ".join(p for p in parts if p and p != "→ ")
    if category == "subscriptions":
        parts = []
        for key in ("actor", "user_id", "plan_id", "voucher_id", "entitlement_id", "status", "source"):
            if row.get(key):
                parts.append(f"{key}={row[key]}")
        return " · ".join(parts)
    if category == "paypal":
        parts = [str(row.get("event_type") or "")]
        parts.append(f"verified={row.get('verified')}")
        if isinstance(row.get("result"), dict) and row["result"].get("action"):
            parts.append(str(row["result"]["action"]))
        return " · ".join(p for p in parts if p)
    if category == "support":
        parts = []
        for key in ("owner_id", "user_id", "request_id", "count"):
            if row.get(key) not in (None, ""):
                parts.append(f"{key}={row[key]}")
        return " · ".join(parts)
    return json.dumps(row, ensure_ascii=False)[:200]


def _is_suspicious(category: str, row: Dict[str, Any]) -> bool:
    if category == "mini_app":
        try:
            status = int(row.get("status") or 0)
        except (TypeError, ValueError):
            status = 0
        return status in (401, 403, 429)
    if category == "account":
        return str(row.get("event") or "") in {
            "account_denied", "phone_mismatch", "identity_mismatch", "user_blocked", "user_deleted"}
    if category == "paypal":
        return row.get("verified") is False
    if category == "support":
        return str(row.get("event") or "") in {"screenshot_error"}
    return False


def read_journal(*, category: str = "", query: str = "", limit: int = 200,
                 suspicious_only: bool = False) -> Dict[str, Any]:
    try:
        limit = max(1, min(int(limit or 200), MAX_LIMIT))
    except (TypeError, ValueError):
        limit = 200
    cats = [category] if category in CATEGORIES else list(CATEGORIES)
    needle = str(query or "").strip().lower()
    entries: List[Dict[str, Any]] = []
    for cat in cats:
        path = _audit_dir() / CATEGORIES[cat]["file"]
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        # Only parse the tail; a merged feed never needs the whole history.
        for line in lines[-(limit * 4):]:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            suspicious = _is_suspicious(cat, row)
            if suspicious_only and not suspicious:
                continue
            entry = {
                "timestamp": str(row.get("timestamp") or ""),
                "category": cat,
                "category_label": CATEGORIES[cat]["label"],
                "event": _event(cat, row),
                "summary": _summary(cat, row),
                "status": row.get("status"),
                "suspicious": suspicious,
            }
            if needle:
                blob = f"{entry['event']} {entry['summary']} {entry['timestamp']}".lower()
                if needle not in blob:
                    continue
            entries.append(entry)
    entries.sort(key=lambda item: item["timestamp"], reverse=True)
    entries = entries[:limit]
    return {"entries": entries, "categories": categories(), "count": len(entries)}
