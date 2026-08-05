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

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

from . import runtime_env


TEAM_PERSONAL = "personal_team"
TEAM_OWNER_TRAINING = "owner_training_coordinator"
TEAM_OWNER = "owner_team"
TEAM_GRANTED_FULL = "granted_full_team"

# Owner-grantable capability: a shared owner-training user may be lifted from the
# single limited coordinator to the full (non-administrative) agent team.
TEAM_FULL_CAPABILITY = "agents.team.full"

# Approved personas (docs/agents/AGENTS.md hierarchy; ADR-0006 for the coordinator).
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

_GRANT_LOCK = threading.Lock()


def _grants_path():
    return runtime_env.data_path("agents") / "team_capabilities.json"


def _read_grants() -> Dict[str, Any]:
    try:
        doc = json.loads(_grants_path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"grants": {}}
    grants = doc.get("grants") if isinstance(doc, dict) else None
    return {"grants": grants if isinstance(grants, dict) else {}}


def _write_grants(doc: Dict[str, Any]) -> None:
    path = _grants_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def has_team_capability(user_id: Any, capability: str = TEAM_FULL_CAPABILITY) -> bool:
    try:
        uid = str(int(user_id or 0))
    except (TypeError, ValueError):
        return False
    if uid == "0":
        return False
    row = _read_grants()["grants"].get(uid) or {}
    return str(capability) in (row.get("capabilities") or [])


def grant_team_capability(user_id: Any, capability: str = TEAM_FULL_CAPABILITY,
                          *, granted_by: Any = 0) -> Dict[str, Any]:
    uid = str(int(user_id or 0))
    if uid == "0":
        raise ValueError("user_id обязателен для выдачи capability команды агентов.")
    with _GRANT_LOCK:
        doc = _read_grants()
        row = doc["grants"].get(uid) or {"capabilities": []}
        caps = set(row.get("capabilities") or [])
        caps.add(str(capability))
        doc["grants"][uid] = {
            "capabilities": sorted(caps),
            "granted_by": str(granted_by or ""),
            "updated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _write_grants(doc)
    return {"ok": True, "user_id": uid, "capabilities": doc["grants"][uid]["capabilities"]}


def revoke_team_capability(user_id: Any, capability: str = TEAM_FULL_CAPABILITY) -> Dict[str, Any]:
    uid = str(int(user_id or 0))
    with _GRANT_LOCK:
        doc = _read_grants()
        row = doc["grants"].get(uid)
        if row:
            caps = [c for c in (row.get("capabilities") or []) if c != str(capability)]
            if caps:
                row["capabilities"] = caps
                row["updated_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                doc["grants"].pop(uid, None)
            _write_grants(doc)
    return {"ok": True, "user_id": uid}


def agent_display_config() -> Dict[str, Any]:
    """Architecture hook for future user-configurable agent names/avatars.

    The full agent constructor is intentionally out of scope for Phase 12; this
    returns the canonical roster plus an (empty) override map so the UI/tests can
    render display names/avatars from one place once editing is implemented.
    """
    return {
        "editable": False,
        "roster": {
            "owner_team": list(OWNER_TEAM_AGENTS),
            "personal_team": list(PERSONAL_TEAM_AGENTS),
            "owner_training_coordinator": [OWNER_TRAINING_COORDINATOR],
            "granted_full_team": list(PERSONAL_TEAM_AGENTS),
        },
        "overrides": {},
    }



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
    # Shared owner-training runtime for a non-owner. A developer or any user the
    # owner explicitly granted ``agents.team.full`` gets the full (non-admin)
    # team; everyone else gets the single limited coordinator (ADR-0006).
    if _has_full_team_grant(context):
        return {
            "team_kind": TEAM_GRANTED_FULL,
            "coordinator": OWNER_COORDINATOR,
            "agents": list(PERSONAL_TEAM_AGENTS),
            "allowed_operations": list(PERSONAL_OPERATIONS),
            "isolated": False,
            "uses_owner_runtime": True,
            "administrative": False,
            "entitlement_id": entitlement,
            "granted_capability": TEAM_FULL_CAPABILITY,
            "policy": "granted_full_team",
        }
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


def _has_full_team_grant(context: Dict[str, Any]) -> bool:
    """True when the caller may use the full team on the shared runtime.

    Developers and any user with an explicit owner grant qualify. The grant is
    read from the context capability set (so it round-trips with the request)
    and, as a fallback, from the persisted grant store by user id.
    """
    caps = context.get("capabilities")
    if isinstance(caps, dict) and caps.get(TEAM_FULL_CAPABILITY):
        return True
    if isinstance(caps, (list, tuple, set)) and TEAM_FULL_CAPABILITY in caps:
        return True
    admin_caps = context.get("admin_capabilities")
    if isinstance(admin_caps, dict) and admin_caps.get(TEAM_FULL_CAPABILITY):
        return True
    return has_team_capability(context.get("user_id"), TEAM_FULL_CAPABILITY)


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
