"""Structured audit trail for security-relevant mutations in Production."""
from __future__ import annotations

import hashlib
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from . import observability, runtime_env
from .production_storage import Scope, StorageError, get_client
from .production_storage.core import _jsonb


_LOCK = threading.RLock()
_DEV_AUDIT_LOG: deque[Dict[str, Any]] = deque(maxlen=4096)


def record(
    actor: str,
    action: str,
    resource_type: str,
    *,
    resource_id: str = "",
    outcome: str = "success",
    workspace_id: str = "",
    user_id: int = 0,
    ip_hash: str = "",
    details: Optional[Mapping[str, Any]] = None,
) -> str:
    """Record an audit event, storing it in-memory for dev or DB for prod."""
    if outcome not in {"success", "denied", "error"}:
        outcome = "error"

    safe_actor = str(actor or "system").strip()[:160] or "system"
    safe_action = str(action or "unknown_action").strip()[:120] or "unknown_action"
    safe_resource_type = (
        str(resource_type or "resource").strip()[:80] or "resource"
    )
    safe_resource_id = str(resource_id)[:200]
    safe_outcome = str(outcome)

    safe_ip = ""
    if ip_hash:
        if len(ip_hash) == 64 and all(c in "0123456789abcdefABCDEF" for c in ip_hash):
            safe_ip = ip_hash.lower()
        else:
            safe_ip = hashlib.sha256(str(ip_hash).encode("utf-8")).hexdigest()

    clean_details = observability.redact(dict(details or {}))
    event_id = "aud_" + uuid.uuid4().hex
    legacy_payload = {
        "actor": safe_actor,
        "resource_type": safe_resource_type,
        "resource_id": safe_resource_id,
        "outcome": safe_outcome,
        "ip_hash": safe_ip,
        "details": clean_details,
    }

    if runtime_env.is_production() and runtime_env.environment_explicit():
        try:
            scope = Scope.global_service_scope()
            with get_client().transaction(scope) as conn:
                conn.execute(
                    """
                    INSERT INTO sf_audit_events(
                      event_id, workspace_id, user_id, source, event_type, payload,
                      actor, action, resource_type, resource_id, outcome, ip_hash, document
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event_id,
                        str(workspace_id or "") or None,
                        int(user_id or 0) or None,
                        "audit_events",
                        safe_action,
                        _jsonb(legacy_payload),
                        safe_actor,
                        safe_action,
                        safe_resource_type,
                        safe_resource_id,
                        safe_outcome,
                        safe_ip,
                        _jsonb(clean_details),
                    )
                )
        except Exception as exc:
            observability.event(
                "audit",
                "persistence_failed",
                severity="critical",
                payload={"error": str(exc), "action": safe_action, "actor": safe_actor}
            )
            raise StorageError("Failed to persist audit event") from exc
    else:
        row = {
            "event_id": event_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "source": "audit_events",
            "event_type": safe_action,
            "payload": legacy_payload,
            "actor": safe_actor,
            "action": safe_action,
            "resource_type": safe_resource_type,
            "resource_id": safe_resource_id,
            "outcome": safe_outcome,
            "ip_hash": safe_ip,
            "document": clean_details,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        with _LOCK:
            _DEV_AUDIT_LOG.append(row)

        observability.event(
            "audit",
            f"dev_audit.{safe_action}",
            payload={"actor": safe_actor, "resource": safe_resource_type, "outcome": safe_outcome}
        )

    return event_id


def query(
    *,
    workspace_id: str = "",
    actor: str = "",
    action: str = "",
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Query recent audit events."""
    limit = max(1, min(1000, limit))

    if runtime_env.is_production() and runtime_env.environment_explicit():
        scope = Scope.global_service_scope()
        if workspace_id:
            scope = Scope.workspace_scope(workspace_id)

        filters = []
        params: List[Any] = []
        if actor:
            filters.append("actor = %s")
            params.append(actor)
        if action:
            filters.append("action = %s")
            params.append(action)

        where_clause = ""
        if filters:
            where_clause = " AND " + " AND ".join(filters)

        with get_client().transaction(scope) as conn:
            cursor = conn.execute(
                f"""
                SELECT event_id, workspace_id, user_id, actor, action, resource_type,
                       resource_id, outcome, ip_hash, document, occurred_at
                FROM sf_audit_events
                WHERE 1=1 {where_clause}
                ORDER BY occurred_at DESC
                LIMIT %s
                """,
                tuple(params + [limit])
            )
            return [dict(row) for row in cursor.fetchall()]
    else:
        with _LOCK:
            events = list(_DEV_AUDIT_LOG)

        results = []
        for event in reversed(events):
            if workspace_id and event["workspace_id"] != workspace_id:
                continue
            if actor and event["actor"] != actor:
                continue
            if action and event["action"] != action:
                continue
            results.append(event)
            if len(results) >= limit:
                break
        return results
