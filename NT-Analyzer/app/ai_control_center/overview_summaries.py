"""Compact summaries for the AI Center overview ("кратко обо всём").

Each block reads what the same user may already open on its own tab, through
the same domain admission, so the overview grants no new access. The owner's
AI Lab totals are added only for the owner working in the owner runtime; the
lab catalogue is global and is never shown to another workspace. A block that
cannot be read is reported as unavailable instead of failing the overview.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import domain_gateway
from .states import ContractError

READ_LIMIT = 50
# The same classification the AI Lab summary uses for its own totals.
LAB_CANDIDATES = frozenset({"sandbox_candidate", "portfolio_contributor"})
LAB_CHAMPIONS = frozenset({"champion_candidate", "human_review_candidate"})
LAB_ARCHIVED = frozenset({"archived", "cancelled"})
# Memory that agents no longer read is not counted as memory.
MEMORY_GONE = frozenset({"revoked", "expired", "archived", "retired", "superseded"})


def _items(authorized, domain):
    result = domain_gateway.list_domain(authorized, domain, identity=None, limit=READ_LIMIT, cursor=None)
    return list(result.get("items") or []), bool(result.get("next_cursor"))


def _guard(read):
    try:
        return read()
    except ContractError as exc:
        return {"unavailable": str(exc)}
    except Exception:  # noqa: BLE001 - one unreadable block must not hide the overview
        return {"unavailable": "unavailable"}


def _since(days=0, hours=0):
    moment = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
    return moment.isoformat().replace("+00:00", "Z")


def _utc(value):
    """ISO time as a comparable UTC string; unreadable values sort first."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sources(row):
    found = {str(value) for value in row.get("source_ids") or [] if value}
    found.update(str(item.get("artifact_id")) for item in row.get("provenance") or []
                 if isinstance(item, dict) and item.get("artifact_id"))
    return found


def _memory(authorized):
    records, more = _items(authorized, "memory")
    live = [row for row in records if str(row.get("status") or "") not in MEMORY_GONE]
    day = _since(hours=24)
    fresh = lambda row: _utc(row.get("created_at")) >= day  # noqa: E731
    lessons = [row for row in live if row.get("memory_class") == "verified_lesson"]
    strategies = {str((row.get("scope_binding") or {}).get("strategy_project_id") or row.get("strategy_project_id") or "") for row in live}
    newest = lambda rows: sorted(rows, key=lambda row: _utc(row.get("created_at")), reverse=True)[:3]  # noqa: E731
    return {
        "records": len(live),
        "records_day": sum(1 for row in live if fresh(row)),
        "verified_lessons": len(lessons),
        "lessons_day": sum(1 for row in lessons if fresh(row)),
        "strategies": len(strategies - {""}),
        "sources": len(set().union(*(_sources(row) for row in live))) if live else 0,
        "capped": more or len(records) >= READ_LIMIT,
        # Lessons first, as the prototype lists them; plain records only when
        # there is no verified lesson yet.
        "latest": [{"id": row.get("id"), "title": row.get("title"), "created_at": row.get("created_at"),
                    "memory_class": row.get("memory_class")} for row in newest(lessons or live)],
    }


def _models(authorized):
    rows, _ = _items(authorized, "models")
    groups = {}
    for row in rows:
        model = str(row.get("model") or "").strip()
        if not model:
            continue
        group = groups.setdefault(model, {"model": model, "provider": row.get("provider") or "", "connections": 0, "active": 0})
        group["connections"] += 1
        group["active"] += 1 if row.get("status") == "active" else 0
    return {"items": sorted(groups.values(), key=lambda group: group["model"])}


def _owner_runtime(authorized):
    scope = authorized.get("chat_scope") or {}
    return bool(scope.get("is_owner") and scope.get("uses_owner_runtime") and scope.get("membership_role") == "owner")


def _research(authorized):
    if not _owner_runtime(authorized):
        return {"unavailable": "owner_lab_only"}
    from ..ai_lab import registry
    experiments = registry.list_experiments()
    week = _since(days=7)
    status = lambda row: str(row.get("status") or "")  # noqa: E731
    # The registry keeps no status history: "за 7 дней" for a status counts the
    # experiments in that status that changed during the week.
    changed = lambda row: _utc(row.get("updated_at_utc")) >= week  # noqa: E731
    group = lambda names: [row for row in experiments if status(row) in names]  # noqa: E731
    candidates, champions, archived = group(LAB_CANDIDATES), group(LAB_CHAMPIONS), group(LAB_ARCHIVED)
    return {
        "experiments": len(experiments),
        "experiments_week": sum(1 for row in experiments if _utc(row.get("created_at_utc")) >= week),
        "candidates": len(candidates),
        "candidates_week": sum(1 for row in candidates if changed(row)),
        "champions": len(champions),
        "champions_week": sum(1 for row in champions if changed(row)),
        "archived": len(archived),
        "archived_week": sum(1 for row in archived if changed(row)),
        "rejected": sum(1 for row in experiments if status(row) == "rejected"),
    }


def build(authorized):
    return {
        "memory": _guard(lambda: _memory(authorized)),
        "models": _guard(lambda: _models(authorized)),
        "research": _guard(lambda: _research(authorized)),
    }
