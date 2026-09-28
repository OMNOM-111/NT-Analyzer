"""Explicit, workspace-scoped server admission for existing Agent World domains.

This does not enable Local NT/Desktop adapters, automation or a provider. The
normal account, device, workspace and capability gates remain in domain_gateway.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from uuid import UUID

from .. import audit_events, preview_sandbox, runtime_env
from .contracts import Environment
from .flags import Flag, FlagRule, FlagSnapshot
from .states import ContractError

WORKSPACES_ENV = "STRATFORGE_AGENT_WORLD_SERVER_WORKSPACES"
_FLAGS = (Flag.AI_CONTROL_CENTER_READ_MODEL, Flag.AI_COMMAND_CENTER_UI,
          Flag.AI_TASK_GRAPH_V2, Flag.AI_EVALUATION_SHADOW, Flag.AI_MEMORY_V2,
          Flag.AI_CONSENSUS_V2, Flag.AI_COURT_V1, Flag.AI_SOCIAL_PUBLISH_V1)
_WORKSPACE = re.compile(r"ws_[A-Za-z0-9_-]{8,80}\Z")
_LOCK = threading.RLock()
_SNAPSHOTS = {}


def environment():
    if not runtime_env.environment_explicit() or preview_sandbox.enabled():
        return None
    if runtime_env.is_canary():
        return Environment.CANARY
    if runtime_env.is_production():
        return Environment.PRODUCTION
    return None


def configured(workspace_id: str = "") -> bool:
    if environment() is None:
        return False
    raw = os.environ.get(WORKSPACES_ENV, "")
    entries = [item.strip() for item in raw.split(",")]
    if not entries or any(not _WORKSPACE.fullmatch(item) for item in entries) or len(entries) != len(set(entries)):
        return False
    return workspace_id in entries if workspace_id else True


def flag_snapshot(context):
    if environment() != context.scope.environment or not configured(context.scope.workspace_id):
        raise ContractError("agent_world_server_disabled")
    revision = "server-domains-" + hashlib.sha256(
        (context.scope.environment.value + ":" + context.scope.workspace_id).encode()).hexdigest()[:16]
    key = (context.scope, context.user_uuid, revision)
    with _LOCK:
        if key not in _SNAPSHOTS:
            reference = audit_events.record(str(context.user_uuid), "agent_world.server_flags_activated",
                "agent_world", workspace_id=context.scope.workspace_id, resource_id=revision,
                details={"flags": [flag.value for flag in _FLAGS], "synthetic": False})
            if len(_SNAPSHOTS) >= 256:
                _SNAPSHOTS.clear()
            _SNAPSHOTS[key] = FlagSnapshot(revision=revision, audit_ref=UUID(reference.removeprefix("aud_")),
                rules=tuple(FlagRule(environment=context.scope.environment, flag=flag,
                                     enabled=True, workspace_id=workspace)
                            for flag in _FLAGS for workspace in (None, context.scope.workspace_id)))
        return _SNAPSHOTS[key]
