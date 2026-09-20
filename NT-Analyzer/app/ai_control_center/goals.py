"""The owner's goal for the AI Center: one goal per workspace, written by hand.

Progress is money earned by strategies that trade on the demo account, so this
module stores only what the owner states - the goal, its horizon, its target
and the task for the week - and never computes a result of its own. Backtests
are not progress (docs/product/AI_CENTER_OWNER_RULES.md, rule 5.2).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from .. import runtime_env
from .states import ContractError

HORIZONS = {"month": "Месяц", "quarter": "Квартал", "year": "Год", "": "срок не задан"}
MAX_TARGET_USD = 10_000_000


def _path():
    return runtime_env.data_path("ai_control_center", "goals.json")


def _load():
    path = _path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _key(authorized):
    scope = authorized["context"].scope
    return f"{scope.environment.value}:{scope.workspace_id}"


def _deadline(horizon, today=None):
    """The end of the current month, quarter or year, in the owner's own terms."""
    today = today or date.today()
    if horizon == "month":
        year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        return date(year, month, 1).toordinal() - 1
    if horizon == "quarter":
        month = today.month - (today.month - 1) % 3 + 3
        year, month = (today.year + 1, month - 12) if month > 12 else (today.year, month)
        return date(year, month, 1).toordinal() - 1
    if horizon == "year":
        return date(today.year + 1, 1, 1).toordinal() - 1
    return None


def _text(value, limit, field):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit:
        raise ContractError(f"goal_{field}_invalid")
    return " ".join(value.split())


def read(authorized):
    """The stored goal, with the deadline its horizon implies."""
    goal = _load().get(_key(authorized))
    if not isinstance(goal, dict) or not goal.get("title"):
        return {"title": "", "horizon": "", "horizon_label": HORIZONS[""], "target_usd": 0, "weekly_task": "",
                "deadline": "", "progress_usd": 0, "progress_source": "demo_account_strategies"}
    horizon = goal.get("horizon") if goal.get("horizon") in HORIZONS else ""
    deadline = _deadline(horizon)
    return {"title": goal.get("title", ""), "horizon": horizon, "horizon_label": HORIZONS[horizon],
            "target_usd": float(goal.get("target_usd") or 0), "weekly_task": goal.get("weekly_task", ""),
            "deadline": date.fromordinal(deadline).isoformat() if deadline else "",
            "updated_at": goal.get("updated_at", ""),
            # Only demo-account strategies count, and none of that is measured here.
            "progress_usd": 0, "progress_source": "demo_account_strategies"}


def save(authorized, payload):
    if authorized.get("read_only"):
        raise ContractError("goal_read_only")
    if not isinstance(payload, dict) or set(payload) - {"title", "horizon", "target_usd", "weekly_task"}:
        raise ContractError("goal_invalid_request")
    title = _text(payload.get("title"), 160, "title")
    horizon = payload.get("horizon") or ""
    if horizon not in HORIZONS:
        raise ContractError("goal_horizon_invalid")
    target = payload.get("target_usd") or 0
    if not isinstance(target, (int, float)) or isinstance(target, bool) or not 0 <= target <= MAX_TARGET_USD:
        raise ContractError("goal_target_invalid")
    value = _load()
    if not title:
        value.pop(_key(authorized), None)
    else:
        value[_key(authorized)] = {"title": title, "horizon": horizon, "target_usd": float(target),
                                   "weekly_task": _text(payload.get("weekly_task"), 240, "weekly_task"),
                                   "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return read(authorized)
