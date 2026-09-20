"""Compact summaries for the AI Center overview ("кратко обо всём").

Each block reads what the same user may already open on its own tab, through
the same domain admission, so the overview grants no new access. The owner's
AI Lab totals are added only for the owner working in the owner runtime; the
lab catalogue is global and is never shown to another workspace. A block that
cannot be read is reported as unavailable instead of failing the overview.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import domain_gateway, goals
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
    from ..ai_lab import registry, research_catalog
    experiments = registry.list_experiments()
    week = _since(days=7)
    status = lambda row: str(row.get("status") or "")  # noqa: E731
    # The registry keeps no status history: "за 7 дней" for a status counts the
    # experiments in that status that changed during the week.
    changed = lambda row: _utc(row.get("updated_at_utc")) >= week  # noqa: E731
    group = lambda names: [row for row in experiments if status(row) in names]  # noqa: E731
    candidates, champions, archived = group(LAB_CANDIDATES), group(LAB_CHAMPIONS), group(LAB_ARCHIVED)
    # Strategies developed before the Lab registry are linked to researches as
    # profiles; they count too, without dates, so they add no weekly delta.
    evaluations = [row.get("evaluation") or {} for row in research_catalog.list_researches().get("researches") or []]
    profiles = lambda key: sum(int(value.get(key) or 0) for value in evaluations)  # noqa: E731
    return {
        "researches": len(evaluations),
        "experiments": len(experiments) + profiles("linked_strategy_profiles"),
        "experiments_week": sum(1 for row in experiments if _utc(row.get("created_at_utc")) >= week),
        "candidates": len(candidates) + profiles("working_strategies"),
        "candidates_week": sum(1 for row in candidates if changed(row)),
        "champions": len(champions),
        "champions_week": sum(1 for row in champions if changed(row)),
        "archived": len(archived) + profiles("archived_strategies"),
        "archived_week": sum(1 for row in archived if changed(row)),
        "rejected": sum(1 for row in experiments if status(row) == "rejected"),
    }


def _knowledge(authorized):
    if not _owner_runtime(authorized):
        return {"unavailable": "owner_lab_only"}
    from ..ai_lab import knowledge_base
    return knowledge_base.brief()


def _lab_models(authorized):
    """The owner's model roster from the AI agents registry, with its own usage.

    Secrets never leave the registry: only names, tariffs, budgets and the
    usage log's counts are returned.
    """
    if not _owner_runtime(authorized):
        return {"unavailable": "owner_lab_only"}
    from ..ai_lab import agent_registry
    usage = agent_registry.usage_rows(limit=100_000)
    rows = []
    for agent in agent_registry.list_agents():
        calls = [row for row in usage if str(row.get("agent_id") or "") == agent.get("id")]
        ok = sum(1 for row in calls if row.get("status") == "success")
        roles = {}
        for row in calls:
            role = roles.setdefault(str(row.get("role") or "general"), {"role": str(row.get("role") or "general"), "requests": 0, "ok": 0, "cost_usd": 0.0, "last_at": ""})
            role["requests"] += 1
            role["ok"] += 1 if row.get("status") == "success" else 0
            role["cost_usd"] = round(role["cost_usd"] + float(row.get("cost_usd") or 0), 8)
            role["last_at"] = max(role["last_at"], str(row.get("timestamp_utc") or ""))
        rows.append({
            **{key: agent.get(key) for key in (
                "id", "name", "provider", "model", "enabled", "disabled_reason", "billing_mode", "role", "purpose", "priority",
                "input_price_usd_per_m", "output_price_usd_per_m", "daily_budget_usd", "monthly_budget_usd",
                "spend_today_usd", "spend_month_usd", "spend_all_time_usd", "remaining_daily_budget_usd",
                "remaining_monthly_budget_usd", "credit_total_usd", "credit_used_pct", "credit_remaining_estimated_usd",
                "credit_expires_at_utc", "requests_today", "requests_month", "last_used_at_utc", "cooldown_active")},
            "last_test_ok": (agent.get("last_test") or {}).get("ok") if isinstance(agent.get("last_test"), dict) else None,
            "requests": len(calls), "ok": ok, "errors": len(calls) - ok,
            "tokens": sum(int(row.get("total_tokens") or 0) for row in calls),
            "by_role": sorted(roles.values(), key=lambda value: -value["requests"]),
            "recent": [{key: row.get(key) for key in ("timestamp_utc", "role", "purpose", "status", "total_tokens", "cost_usd", "elapsed_sec")}
                       for row in calls[-8:][::-1]],
        })
    return {"items": sorted(rows, key=lambda row: (-row["requests"], not row["enabled"], str(row["name"] or "")))}


def build(authorized):
    return {
        "goal": _guard(lambda: goals.read(authorized)),
        "memory": _guard(lambda: _memory(authorized)),
        "models": _guard(lambda: _models(authorized)),
        "research": _guard(lambda: _research(authorized)),
        "knowledge": _guard(lambda: _knowledge(authorized)),
        "lab_models": _guard(lambda: _lab_models(authorized)),
    }
