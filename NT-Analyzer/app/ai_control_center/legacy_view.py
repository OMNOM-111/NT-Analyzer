"""The `Legacy / Архив` view: the old registry as it was, read-only.

This module only reads. It shows the frozen archive - the old models, the old
positions and assignments, what was actually run and what it cost - so the
owner can see the previous arrangement and check the migration against it.
Nothing here is configuration of the running system: the router, the
coordinator, the ratings of current assignments and task execution never read
it, and the reconciliation report states what deliberately did not migrate.
"""
from __future__ import annotations

from . import legacy_migration
from ..ai_lab import legacy_archive
from .states import ContractError

# The old record, shown as it was written. These fields are exactly the ones
# that did not migrate as configuration, which is why the archive is the only
# honest place to read them.
LEGACY_FIELDS = ("id", "name", "provider", "model", "role", "purpose", "priority", "rotation_group",
                 "enabled", "disabled_reason", "billing_mode", "account_name", "endpoint_type",
                 "input_price_usd_per_m", "output_price_usd_per_m", "daily_budget_usd", "monthly_budget_usd",
                 "credit_total_usd", "created_at_utc", "updated_at_utc", "last_used_at_utc", "notes")
CALL_FIELDS = ("at_utc", "model_name_at_the_time", "provider", "model", "legacy_role", "legacy_request_role",
               "purpose", "status", "error", "total_tokens", "cost_usd", "elapsed_sec", "orphan")


def _owner(authorized):
    scope = authorized.get("chat_scope") or {}
    if not (scope.get("is_owner") and scope.get("uses_owner_runtime") and scope.get("membership_role") == "owner"):
        raise ContractError("owner_lab_only")


def overview(authorized):
    """What exists: the archive, its integrity, and where the migration stands."""
    _owner(authorized)
    found = legacy_archive.archives()
    state = legacy_migration.state()
    current = found[0] if found else None
    return {
        "read_only": True,
        "archives": [{"archive_id": item["archive_id"], "frozen_at_utc": item["frozen_at_utc"],
                      "files": item["totals"]["files"], "records": item["totals"]["records"],
                      "bytes": item["totals"]["bytes"], "note": item.get("note", "")} for item in found],
        "integrity": legacy_archive.verify(current["archive_id"]) if current else {"ok": False, "reason": "archive_missing", "drift": []},
        "migration": state,
        "never_used_by": ["router", "coordinator", "рейтинги текущих назначений", "исполнение задач"],
    }


def agents(authorized, archive_id=None, limit=100):
    """The old models with their old positions - history, not configuration."""
    _owner(authorized)
    current = archive_id or (legacy_archive.latest() or {}).get("archive_id")
    if not current:
        return {"archive_id": None, "items": []}
    rows = [{key: agent.get(key) for key in LEGACY_FIELDS if key in agent}
            for agent in legacy_archive.agents(current)]
    migrated = {row["legacy_agent_id"] for row in legacy_migration.models()}
    for row in rows:
        row["migrated_as_fact"] = row.get("id") in migrated
        # Said plainly, so a reader never mistakes the old field for a pinning.
        row["position_is_historical"] = True
    return {"archive_id": current, "read_only": True, "items": rows[:max(0, int(limit))]}


def calls(authorized, limit=100):
    """What the old models actually did, as migrated history."""
    _owner(authorized)
    rows = legacy_migration.history(limit=limit)
    return {"read_only": True, "items": [{key: row.get(key) for key in CALL_FIELDS} for row in rows]}


def report(authorized):
    """archive -> migration report -> new registry, with both sides counted."""
    _owner(authorized)
    state = legacy_migration.state()
    return {"read_only": True, "report": state.get("report"), "authoritative": state.get("authoritative"),
            "provenance": legacy_migration.provenance()[:200]}
