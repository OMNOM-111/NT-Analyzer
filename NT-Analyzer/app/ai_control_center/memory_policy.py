"""Memory context scopes over the existing private record/artifact authority.

Scope is NOT a capability or an instruction-priority grant. Legacy lifecycle
classes and explicit workspace publication remain unchanged.
"""
import hashlib
from uuid import UUID

from .states import ContractError, EntityKind

SCOPES = ("user", "workspace", "strategy", "session", "governance", "operational")
OPERATIONAL_PURPOSES = ("task_result", "error_recovery", "runtime_status")


def _authority(service, context):
    value = service.memory_authority(context) if callable(service.memory_authority) else {}
    return value if isinstance(value, dict) else {}


def _session(context, authority):
    session = authority.get("session_id")
    if not isinstance(session, str) or not session:
        raise ContractError("memory_authenticated_session_required")
    return hashlib.sha256((context.scope.environment.value + ":" + context.scope.workspace_id + ":"
                           + str(context.user_uuid) + ":" + session).encode()).hexdigest()


def prepare(service, context, data, identity):
    scope = data.get("memory_scope", "user")
    if scope not in SCOPES:
        raise ContractError("memory_scope_invalid")
    policy = {"version": 1, "scope": scope, "record_id": str(identity)}
    authority = _authority(service, context)
    if data.get("strategy_project_id") and scope != "strategy":
        raise ContractError("memory_strategy_scope_required")
    if scope == "strategy":
        project = service._owned(context, EntityKind.STRATEGY_PROJECT, data.get("strategy_project_id"))
        if project.status not in {"draft", "active"}:
            raise ContractError("memory_strategy_unavailable")
        policy.update(strategy_project_id=str(project.header.entity_id), strategy_revision=project.header.revision)
    elif scope == "session":
        if data["memory_class"] != "working" or data["retention_days"] != 1:
            raise ContractError("memory_session_ttl_required")
        policy["session_binding"] = _session(context, authority)
    elif scope == "governance":
        if authority.get("governance_allowed") is not True:
            raise ContractError("memory_governance_denied")
    elif scope == "operational":
        if data["memory_class"] != "task" or data.get("purpose") not in OPERATIONAL_PURPOSES:
            raise ContractError("memory_operational_context_required")
        task = service._owned(context, EntityKind.TASK, data.get("task_id"))
        policy["task_id"] = str(task.header.entity_id)
    return {**data, "memory_scope": scope, "_memory_policy": policy}


def check(service, context, record, data, *, published=False):
    policy = data.get("_memory_policy")
    if policy is None:
        return  # Legacy artifacts retain their existing private/public contract.
    if not isinstance(policy, dict) or policy.get("version") != 1 or policy.get("scope") not in SCOPES:
        raise ContractError("memory_scope_invalid")
    scope = policy["scope"]
    if published:
        if scope not in {"user", "workspace"}:
            raise ContractError("memory_scope_not_publishable")
        return
    if policy.get("record_id") != str(record.header.entity_id):
        raise ContractError("memory_scope_invalid")
    authority = _authority(service, context)
    if scope == "session" and _session(context, authority) != policy.get("session_binding"):
        raise ContractError("memory_session_mismatch")
    if scope == "governance" and authority.get("governance_allowed") is not True:
        raise ContractError("memory_governance_denied")
    if scope == "strategy":
        project = service._owned(context, EntityKind.STRATEGY_PROJECT, policy.get("strategy_project_id"))
        if project.status not in {"draft", "active"} or project.header.revision != policy.get("strategy_revision"):
            raise ContractError("memory_strategy_changed")
    if scope == "operational":
        task = service._owned(context, EntityKind.TASK, policy.get("task_id"))
        if record.task is None or record.task.entity_id != task.header.entity_id:
            raise ContractError("memory_operational_context_required")


def public(data, *, published=False):
    policy = data.get("_memory_policy") or {}
    result = {key: value for key, value in data.items() if key != "_memory_policy"}
    result["memory_scope"] = "workspace" if published else policy.get("scope", data.get("memory_scope", "user"))
    result["memory_scope_policy_version"] = policy.get("version", 0)
    result["scope_binding"] = {key: policy[key] for key in ("strategy_project_id", "strategy_revision", "task_id") if key in policy}
    result["session_bound"] = policy.get("scope") == "session"
    return result


def shareable(data):
    return (data.get("_memory_policy") or {}).get("scope", "user") in {"user", "workspace"}


def artifact_allowed(service, context, found):
    """Known generic artifact IDs must not bypass contextual memory access."""
    if found is None or found[2] != "application/json":
        return found
    import json
    try:
        data = json.loads(found[1])
    except (ValueError, UnicodeError):
        return found
    if not isinstance(data, dict):
        return found
    policy = data.get("_memory_policy")
    if policy is not None and not isinstance(policy, dict):
        return None
    identity = (policy or {}).get("record_id")
    identity = identity or (data.get("memory_id") if data.get("method") == "explicit_user_review" else None)
    if not identity:
        return found
    try:
        record = service._owned(context, EntityKind.MEMORY, UUID(identity))
        content = service._json(context, record.content)
        check(service, context, record, content)
        if record.status not in {"draft", "active"} or record.retention_until <= service.now():
            return None
        if record.status == "active" and not service._memory_source_valid(context, record, content):
            return None
        if data.get("_memory_policy") is not None and found[0] != record.content:
            return None
    except (ContractError, ValueError, TypeError):
        return None
    return found
