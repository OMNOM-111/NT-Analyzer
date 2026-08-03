"""Phase 6: agent allocation by workspace, entitlement and NinjaTrader connection.

A personal NinjaTrader workspace gets an isolated Agent Team scoped to that
workspace, its Connector, accounts and data — it never falls back to the shared
owner-training runtime and never sees another user's agents, jobs or results.

A user on the shared owner-training NinjaTrader gets a single limited
``Координатор`` (ADR-0006), positioned below Виктор: training/backtest requests
only, no owner Agent Team, no administrative capabilities and no other users'
data. The owner keeps the full Agent Team.

Allocation is a deterministic function of workspace kind, entitlement and NT
connection type — never of a global account — so nothing is persisted here.
"""
from __future__ import annotations

from typing import Any, Dict


TEAM_PERSONAL = "personal_team"
TEAM_OWNER_TRAINING = "owner_training_coordinator"
TEAM_OWNER = "owner_team"

# Approved personas (docs/AGENTS.md hierarchy; ADR-0006 for the coordinator).
OWNER_COORDINATOR = "Управляющий"
OWNER_TRAINING_COORDINATOR = "Координатор"  # ADR-0006: below Виктор, limited
PERSONAL_TEAM_AGENTS = ("Управляющий", "Толик", "Иван", "Никита", "Марина")
OWNER_TEAM_AGENTS = (
    "Виктор", "Управляющий", "Заместитель", "Секретарь",
    "Марина", "Толик", "Никита", "Иван",
)

OWNER_TRAINING_OPERATIONS = ("training", "backtest")
PERSONAL_OPERATIONS = ("training", "backtest", "compile", "optimization", "telemetry_read")
OWNER_OPERATIONS = ("training", "backtest", "compile", "optimization", "telemetry_read", "live")


def _active_workspace(context: Dict[str, Any]) -> Dict[str, Any]:
    active = context.get("active_workspace")
    return active if isinstance(active, dict) else {}


def resolve_allocation(context: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the agent allocation for a request context.

    ``context`` is the decorated request context (``is_owner``,
    ``active_workspace`` with ``kind``/``uses_owner_runtime``/``entitlement_id``).
    """
    context = context or {}
    active = _active_workspace(context)
    is_owner = bool(context.get("is_owner"))
    uses_owner_runtime = bool(active.get("uses_owner_runtime"))
    kind = str(active.get("kind") or "")
    entitlement = str(active.get("entitlement_id") or "")

    if is_owner and uses_owner_runtime:
        return {
            "team_kind": TEAM_OWNER,
            "coordinator": OWNER_COORDINATOR,
            "agents": list(OWNER_TEAM_AGENTS),
            "allowed_operations": list(OWNER_OPERATIONS),
            "isolated": True,
            "uses_owner_runtime": True,
            "administrative": True,
            "entitlement_id": entitlement,
            "policy": "owner_team",
        }
    if kind == "personal" and not uses_owner_runtime:
        return {
            "team_kind": TEAM_PERSONAL,
            "coordinator": OWNER_COORDINATOR,
            "agents": list(PERSONAL_TEAM_AGENTS),
            "allowed_operations": list(PERSONAL_OPERATIONS),
            "isolated": True,
            "uses_owner_runtime": False,
            "administrative": False,
            "entitlement_id": entitlement,
            "policy": "personal_isolated_team",
        }
    # Shared owner-training runtime for a non-owner: a single limited coordinator.
    return {
        "team_kind": TEAM_OWNER_TRAINING,
        "coordinator": OWNER_TRAINING_COORDINATOR,
        "agents": [OWNER_TRAINING_COORDINATOR],
        "allowed_operations": list(OWNER_TRAINING_OPERATIONS),
        "isolated": False,
        "uses_owner_runtime": True,
        "administrative": False,
        "entitlement_id": entitlement,
        "policy": "owner_training_limited_coordinator",
    }


def allocation_status(context: Dict[str, Any]) -> Dict[str, Any]:
    """Public agent-allocation payload for the caller's active workspace."""
    active = _active_workspace(context)
    allocation = resolve_allocation(context)
    return {
        "ok": True,
        "workspace": {
            "workspace_id": str(active.get("workspace_id") or ""),
            "kind": str(active.get("kind") or ""),
            "uses_owner_runtime": bool(active.get("uses_owner_runtime")),
        },
        "allocation": allocation,
    }


def operation_allowed(context: Dict[str, Any], operation_kind: str) -> bool:
    allocation = resolve_allocation(context)
    return str(operation_kind or "") in set(allocation.get("allowed_operations") or [])
