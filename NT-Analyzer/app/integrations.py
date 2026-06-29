"""Safe, read-only integration status used by the Aurora UI.

Secrets are read from environment variables and are never returned. Runtime
event files are optional; missing files produce honest empty states rather than
demo data or implied connectivity.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _read_rows(name: str) -> List[Dict[str, Any]]:
    path = _root() / "data" / "integrations" / name
    if not path.is_file():
        return []
    try:
        if path.suffix == ".jsonl":
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        else:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            rows = doc if isinstance(doc, list) else doc.get("items", [])
    except (OSError, ValueError, TypeError):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def telegram_status() -> Dict[str, Any]:
    configured = bool(os.environ.get("NTA_TELEGRAM_BOT_TOKEN") and os.environ.get("NTA_TELEGRAM_CHAT_ID"))
    return {
        "configured": configured,
        "status": "configured" if configured else "not_configured",
        "notifications_enabled": configured and os.environ.get("NTA_TELEGRAM_NOTIFICATIONS", "1") != "0",
        "commands_enabled": False,
        "note": "Команды из Telegram отключены до отдельного security-аудита.",
    }


def topstep_status() -> Dict[str, Any]:
    configured = bool(os.environ.get("NTA_TOPSTEP_API_KEY") and os.environ.get("NTA_TOPSTEP_ACCOUNT_ID"))
    return {
        "configured": configured,
        "status": "configured" if configured else "not_configured",
        "account_id_configured": bool(os.environ.get("NTA_TOPSTEP_ACCOUNT_ID")),
        "api_key_configured": bool(os.environ.get("NTA_TOPSTEP_API_KEY")),
        "live_actions_enabled": False,
        "approved_strategies_only": True,
        "transport": "NinjaTrader",
        "note": "Передача live-сигналов заблокирована до отдельной валидации API и risk-gate.",
    }


def news(limit: int = 50) -> Dict[str, Any]:
    rows = _read_rows("news.json") or _read_rows("news.jsonl")
    clean = []
    for row in rows:
        if not str(row.get("title") or "").strip():
            continue
        raw_url = str(row.get("url") or "").strip()
        safe_url = raw_url if raw_url.startswith(("https://", "http://")) else ""
        severity = str(row.get("severity") or row.get("impact") or "unknown").lower()
        if severity not in {"high", "medium", "low"}:
            severity = "low"
        instruments = row.get("affected_instruments") or row.get("instruments")
        when = row.get("event_time_utc") or row.get("published_at_utc")
        clean.append({
            "id": str(row.get("id") or ""),
            "item_type": str(row.get("item_type") or "calendar_event").lower(),
            "title": str(row.get("title") or "").strip(),
            "source": str(row.get("source") or "локальный источник").strip(),
            "source_type": str(row.get("source_type") or "manual").lower(),
            "source_url": safe_url,
            "category": str(row.get("category") or "unknown").lower(),
            "published_at_utc": when,
            "event_time_utc": when,
            "event_time_pt": str(row.get("event_time_pt") or ""),
            "event_time_et": str(row.get("event_time_et") or ""),
            "fetched_at_utc": str(row.get("fetched_at_utc") or ""),
            "url": safe_url,
            "summary": str(row.get("summary") or "").strip(),
            "impact": severity,
            "severity": severity,
            "instruments": instruments if isinstance(instruments, list) else [],
            "affected_instruments": instruments if isinstance(instruments, list) else [],
            "block_before_min": int(row.get("block_before_min") or 0),
            "block_after_min": int(row.get("block_after_min") or 0),
            "is_confirmed": bool(row.get("is_confirmed", False)),
            "schedule_status": str(row.get("schedule_status") or ("confirmed" if row.get("is_confirmed") else "estimated")),
            "risk_action": str(row.get("risk_action") or "monitor"),
        })
    clean.sort(key=lambda item: str(item.get("event_time_utc") or ""))
    configured = bool(os.environ.get("NTA_NEWS_FEEDS")) or bool(rows)
    return {
        "configured": configured,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": clean[: max(1, min(int(limit or 50), 200))],
        "total": len(clean),
        "note": "Источники новостей не настроены." if not configured else "Официальные даты отделены от явно помеченных оценок.",
    }


def _parse_iso(value: Any) -> "datetime | None":
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def live_news(max_age_min: int = 60, limit: int = 40) -> Dict[str, Any]:
    """Recent live headlines + per-provider fetch status (separate from calendar)."""
    path = _root() / "data" / "integrations" / "live_news.json"
    doc: Dict[str, Any] = {}
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            doc = {}
    providers = doc.get("providers") if isinstance(doc.get("providers"), list) else []
    raw_items = doc.get("items") if isinstance(doc.get("items"), list) else []
    now = datetime.now(timezone.utc)
    cutoff_min = max(5, int(max_age_min or 60))
    recent: List[Dict[str, Any]] = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        published = _parse_iso(row.get("published_at_utc") or row.get("event_time_utc"))
        age_min = ((now - published).total_seconds() / 60.0) if published else None
        raw_url = str(row.get("source_url") or row.get("url") or "").strip()
        safe_url = raw_url if raw_url.startswith(("https://", "http://")) else ""
        severity = str(row.get("severity") or row.get("impact") or "low").lower()
        if severity not in {"high", "medium", "low"}:
            severity = "low"
        instruments = row.get("affected_instruments") or row.get("instruments")
        recent.append({
            "id": str(row.get("id") or ""),
            "item_type": "live_news",
            "title": str(row.get("title") or "").strip(),
            "summary": str(row.get("summary") or "").strip(),
            "source": str(row.get("source") or "источник").strip(),
            "source_type": str(row.get("source_type") or "rss").lower(),
            "source_url": safe_url,
            "url": safe_url,
            "severity": severity,
            "impact": severity,
            "affected_instruments": instruments if isinstance(instruments, list) else [],
            "instruments": instruments if isinstance(instruments, list) else [],
            "published_at_utc": row.get("published_at_utc") or row.get("event_time_utc"),
            "fetched_at_utc": str(row.get("fetched_at_utc") or doc.get("generated_at_utc") or ""),
            "age_min": round(age_min, 1) if age_min is not None else None,
            "is_recent": age_min is not None and -5 <= age_min <= cutoff_min,
        })
    fresh = [item for item in recent if item["is_recent"] and item["title"]]
    fresh.sort(key=lambda item: str(item.get("published_at_utc") or ""), reverse=True)
    all_stored = sorted(
        [item for item in recent if item["title"]],
        key=lambda item: str(item.get("published_at_utc") or ""),
        reverse=True,
    )
    ok_providers = [p for p in providers if isinstance(p, dict) and p.get("ok")]
    last_fetch = doc.get("generated_at_utc") or ""
    configured = bool(os.environ.get("NTA_NEWS_LIVE_FEEDS")) or bool(providers) or bool(raw_items)
    if not configured:
        note = "Лента живых новостей не настроена."
    elif not fresh:
        note = f"Нет рыночных заголовков за последние {cutoff_min} мин."
    else:
        note = f"{len(fresh)} свежих заголовков за {cutoff_min} мин."
    return {
        "configured": configured,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_fetch_utc": last_fetch,
        "max_age_min": cutoff_min,
        "items": fresh[: max(1, min(int(limit or 40), 100))],
        "all_items": all_stored[:100],
        "total_recent": len(fresh),
        "total_stored": len(recent),
        "providers": providers,
        "providers_ok": len(ok_providers),
        "providers_total": len(providers),
        "note": note,
    }


def external_agents_status() -> Dict[str, Any]:
    rows = _read_rows("external_agents.json") or _read_rows("external_agents.jsonl")
    configured = bool(os.environ.get("NTA_EXTERNAL_AGENTS_ENABLED") == "1")
    budget_raw = os.environ.get("NTA_EXTERNAL_AGENTS_BUDGET_USD", "0")
    try:
        budget = max(0.0, float(budget_raw))
    except ValueError:
        budget = 0.0
    spent = 0.0
    for row in rows:
        try:
            spent += max(0.0, float(row.get("cost_usd") or 0))
        except (TypeError, ValueError):
            continue
    return {
        "configured": configured,
        "execution_enabled": False,
        "budget_usd": round(budget, 4),
        "spent_usd": round(spent, 4),
        "remaining_usd": round(max(0.0, budget - spent), 4),
        "agents": rows[-100:],
        "note": "Внешние агенты работают только после настройки бюджета и отдельного разрешения выполнения.",
    }


def status() -> Dict[str, Any]:
    return {
        "telegram": telegram_status(),
        "topstep": topstep_status(),
        "news": {key: value for key, value in news(1).items() if key != "items"},
        "external_agents": {key: value for key, value in external_agents_status().items() if key != "agents"},
    }
