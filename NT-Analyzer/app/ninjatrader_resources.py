"""Phase 6: durable shared-NinjaTrader resource lease and job queue.

The shared owner-training NinjaTrader can run only one conflicting backtest /
compile / optimization at a time. This module provides a durable, atomic lease
with a FIFO queue, TTL, heartbeat, cancellation, expiration and crash recovery.
Read-only telemetry may run in parallel only when a job is explicitly classified
as ``readonly`` and its operation is on the proven read-only allow-list.

A personal NinjaTrader job is bound to the user's own personal resource and can
never fall back to the owner-training runtime. Leases live in the workspace store
(co-located with workspaces/connections) so ownership, atomicity and Production
persistence reuse the existing repository; a raw lease token is returned once to
the worker and only its hash is stored — never logged or trusted from a client.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import account_auth, agent_allocation, workspaces


# Lease lifecycle.
STATE_QUEUED = "queued"
STATE_ACTIVE = "active"
STATE_RELEASED = "released"
STATE_EXPIRED = "expired"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"
LIVE_STATES = (STATE_QUEUED, STATE_ACTIVE)
TERMINAL_STATES = (STATE_RELEASED, STATE_EXPIRED, STATE_CANCELLED, STATE_FAILED)

GROUP_EXCLUSIVE = "exclusive"
GROUP_READONLY = "readonly"
PARALLEL_GROUPS = (GROUP_EXCLUSIVE, GROUP_READONLY)

OPERATION_KINDS = ("training", "backtest", "compile", "optimization", "telemetry_read", "live")
# Only these operations may ever run as a parallel read-only lease.
READONLY_OPERATIONS = frozenset({"telemetry_read"})

LEASE_TTL_SEC = 5 * 60
# A queued job that is never claimed for this long is expired so the queue can
# never be blocked forever by an abandoned request.
QUEUE_MAX_AGE_SEC = 60 * 60
_KEY = "ninjatrader_resource_leases"
_SEQ_KEY = "ninjatrader_lease_seq"


class NinjaTraderResourceError(RuntimeError):
    def __init__(self, message: str, status: int = 400, *, code: str = ""):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code or "")


# --------------------------------------------------------------------------- #
# Store helpers (reuse the workspace document + lock).
# --------------------------------------------------------------------------- #
def _leases(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = doc.get(_KEY)
    if not isinstance(rows, list):
        rows = []
        doc[_KEY] = rows
    return rows


def _next_seq(doc: Dict[str, Any]) -> int:
    seq = int(doc.get(_SEQ_KEY) or 0) + 1
    doc[_SEQ_KEY] = seq
    return seq


def _now() -> float:
    return time.time()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_from_epoch(epoch: float) -> str:
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return ""


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _audit(event: str, **values: Any) -> None:
    # Never include the raw lease token or other secrets.
    workspaces._audit(event, **values)


# --------------------------------------------------------------------------- #
# Resource derivation (personal vs shared owner-training).
# --------------------------------------------------------------------------- #
def _resource_for_workspace(row: Dict[str, Any]) -> Tuple[str, bool]:
    """Return (resource_id, is_shared) for a workspace.

    A personal workspace owns an exclusive personal resource. The owner-training
    workspace is a shared resource contended by all its members.
    """
    workspace_id = str(row.get("workspace_id") or "")
    if str(row.get("kind") or "") == "owner_training":
        return f"owner_training:{workspace_id}", True
    connection = str(row.get("default_runtime_connection_id") or "") or workspace_id
    return f"personal:{workspace_id}:{connection}", False


def _user_uuid(uid: int, member: Optional[Dict[str, Any]] = None) -> str:
    resolved = account_auth.user_uuid_for_legacy_id(uid)
    if resolved:
        return resolved
    return str((member or {}).get("user_uuid") or "")


# --------------------------------------------------------------------------- #
# Recovery / maintenance.
# --------------------------------------------------------------------------- #
def _recover_in(doc: Dict[str, Any], resource_id: str = "") -> int:
    """Expire timed-out active leases and abandoned queued leases. Returns count."""
    now = _now()
    changed = 0
    for lease in _leases(doc):
        if not isinstance(lease, dict):
            continue
        if resource_id and str(lease.get("resource_id") or "") != resource_id:
            continue
        state = str(lease.get("state") or "")
        if state == STATE_ACTIVE and float(lease.get("expires_at") or 0) <= now:
            lease["state"] = STATE_EXPIRED
            lease["released_at_utc"] = _now_iso()
            lease["lease_token_hash"] = ""
            changed += 1
        elif state == STATE_QUEUED and float(lease.get("created_at") or 0) + QUEUE_MAX_AGE_SEC <= now:
            lease["state"] = STATE_EXPIRED
            lease["released_at_utc"] = _now_iso()
            changed += 1
    return changed


def _active_leases(doc: Dict[str, Any], resource_id: str) -> List[Dict[str, Any]]:
    return [
        lease for lease in _leases(doc)
        if isinstance(lease, dict)
        and str(lease.get("resource_id") or "") == resource_id
        and str(lease.get("state") or "") == STATE_ACTIVE
    ]


def _can_activate(doc: Dict[str, Any], resource_id: str, parallel_group: str) -> bool:
    active = _active_leases(doc, resource_id)
    if not active:
        return True
    if parallel_group == GROUP_READONLY:
        # A read-only job may join only other read-only jobs.
        return all(str(a.get("parallel_group") or "") == GROUP_READONLY for a in active)
    # An exclusive job needs the resource completely free.
    return False


def _queued_for_resource(doc: Dict[str, Any], resource_id: str) -> List[Dict[str, Any]]:
    rows = [
        lease for lease in _leases(doc)
        if isinstance(lease, dict)
        and str(lease.get("resource_id") or "") == resource_id
        and str(lease.get("state") or "") == STATE_QUEUED
    ]
    rows.sort(key=lambda item: int(item.get("queue_seq") or 0))
    return rows


def _find_lease(doc: Dict[str, Any], job_id: str) -> Optional[Dict[str, Any]]:
    target = str(job_id or "")
    for lease in _leases(doc):
        if isinstance(lease, dict) and hmac.compare_digest(str(lease.get("job_id") or ""), target):
            return lease
    return None


def _prune(doc: Dict[str, Any]) -> None:
    rows = _leases(doc)
    if len(rows) <= 2000:
        return
    now = _now()
    kept = [
        lease for lease in rows
        if str(lease.get("state") or "") in LIVE_STATES
        or float(_epoch(lease.get("released_at_utc")) or now) > now - 24 * 60 * 60
    ]
    doc[_KEY] = kept[-2000:]


def _epoch(iso_value: Any) -> float:
    raw = str(iso_value or "").strip()
    if not raw:
        return 0.0
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


# --------------------------------------------------------------------------- #
# Public views.
# --------------------------------------------------------------------------- #
def _public_lease(lease: Dict[str, Any], *, admin: bool) -> Dict[str, Any]:
    out = {
        "job_id": str(lease.get("job_id") or ""),
        "resource_id": str(lease.get("resource_id") or ""),
        "state": str(lease.get("state") or ""),
        "operation_kind": str(lease.get("operation_kind") or ""),
        "parallel_group": str(lease.get("parallel_group") or ""),
        "queue_seq": int(lease.get("queue_seq") or 0),
        "created_at_utc": str(lease.get("created_at_utc") or ""),
        "acquired_at_utc": str(lease.get("acquired_at_utc") or ""),
        "heartbeat_at_utc": str(lease.get("heartbeat_at_utc") or ""),
        "expires_at_utc": str(lease.get("expires_at_utc") or ""),
        "released_at_utc": str(lease.get("released_at_utc") or ""),
    }
    if admin:
        # Owner/admin operational detail keeps the internal UUID + workspace but
        # never the raw lease token.
        out["workspace_id"] = str(lease.get("workspace_id") or "")
        out["requested_by_user_id"] = str(lease.get("requested_by_user_id") or "")
    return out


# --------------------------------------------------------------------------- #
# Enqueue.
# --------------------------------------------------------------------------- #
def _validate_enqueue(operation_kind: str, parallel_group: str, idempotency_key: str) -> Tuple[str, str, str]:
    op = str(operation_kind or "").strip().lower()
    if op not in OPERATION_KINDS:
        raise NinjaTraderResourceError("Недопустимый тип операции.", 400, code="operation_invalid")
    group = str(parallel_group or GROUP_EXCLUSIVE).strip().lower()
    if group not in PARALLEL_GROUPS:
        raise NinjaTraderResourceError("Недопустимая группа параллелизма.", 400, code="parallel_group_invalid")
    # Read-only parallelism must be explicit AND on the proven allow-list.
    if group == GROUP_READONLY and op not in READONLY_OPERATIONS:
        raise NinjaTraderResourceError(
            "Эта операция не может выполняться параллельно (read-only).",
            409, code="parallel_not_allowed",
        )
    key = str(idempotency_key or "").strip()
    if not (8 <= len(key) <= 160):
        raise NinjaTraderResourceError("Некорректный idempotency key.", 400, code="idempotency_invalid")
    return op, group, key


def enqueue_job(
    user_id: Any,
    *,
    operation_kind: str,
    idempotency_key: str,
    workspace_id: str = "",
    parallel_group: str = GROUP_EXCLUSIVE,
    is_owner: bool = False,
) -> Dict[str, Any]:
    """Enqueue a shared/personal NinjaTrader job as a queued lease."""
    op, group, key = _validate_enqueue(operation_kind, parallel_group, idempotency_key)
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise NinjaTraderResourceError("Требуется вход.", 401, code="auth_required")

    with workspaces._LOCK:
        doc = workspaces._read_doc()
        row, member = workspaces._active_workspace_doc(doc, uid, workspace_id)
        if row.get("status") != "active":
            raise NinjaTraderResourceError("Рабочая область неактивна.", 403, code="workspace_inactive")
        resource_id, is_shared = _resource_for_workspace(row)
        # Agent allocation gates which operations this workspace may request.
        context = {
            "is_owner": bool(is_owner),
            "active_workspace": {
                "workspace_id": str(row.get("workspace_id") or ""),
                "kind": str(row.get("kind") or ""),
                "uses_owner_runtime": str(row.get("kind") or "") == "owner_training",
                "entitlement_id": str(row.get("entitlement_id") or ""),
            },
        }
        if not agent_allocation.operation_allowed(context, op):
            raise NinjaTraderResourceError(
                "Эта операция недоступна в текущей рабочей области.",
                403, code="operation_not_allowed_here",
            )
        user_uuid = _user_uuid(uid, member)
        if not user_uuid:
            raise NinjaTraderResourceError("Профиль без UUID identity.", 409, code="identity_missing")

        _recover_in(doc, resource_id)

        # Idempotency: an existing live lease with the same key + owner + resource
        # is returned unchanged so a retry never creates a duplicate.
        for lease in _leases(doc):
            if not isinstance(lease, dict):
                continue
            if str(lease.get("state") or "") not in LIVE_STATES:
                continue
            if (str(lease.get("resource_id") or "") == resource_id
                    and hmac.compare_digest(str(lease.get("requested_by_user_id") or ""), user_uuid)
                    and hmac.compare_digest(str(lease.get("idempotency_key") or ""), key)):
                position = _position_of(doc, lease)
                return {"ok": True, "job_id": lease["job_id"], "state": lease["state"],
                        "resource_id": resource_id, "position": position,
                        "idempotent": True, "shared": is_shared}

        job_id = str(uuid.uuid4())
        now = _now()
        lease = {
            "job_id": job_id,
            "resource_id": resource_id,
            "workspace_id": str(row.get("workspace_id") or ""),
            "requested_by_user_id": user_uuid,
            "requested_by_legacy_id": uid,
            "operation_kind": op,
            "parallel_group": group,
            "idempotency_key": key,
            "state": STATE_QUEUED,
            "queue_seq": _next_seq(doc),
            "lease_token_hash": "",
            "created_at": now,
            "created_at_utc": _now_iso(),
            "acquired_at_utc": "",
            "heartbeat_at_utc": "",
            "expires_at": 0,
            "expires_at_utc": "",
            "released_at_utc": "",
            "audit_metadata": {"shared": is_shared},
        }
        _leases(doc).append(lease)
        _prune(doc)
        workspaces._write_doc(doc)
        position = _position_of(doc, lease)
    _audit(
        "nt_lease_enqueued", workspace_id=lease["workspace_id"], job_id=job_id,
        resource_id=resource_id, operation_kind=op, parallel_group=group, shared=is_shared,
    )
    return {"ok": True, "job_id": job_id, "state": STATE_QUEUED, "resource_id": resource_id,
            "position": position, "idempotent": False, "shared": is_shared}


def _position_of(doc: Dict[str, Any], lease: Dict[str, Any]) -> int:
    if str(lease.get("state") or "") == STATE_ACTIVE:
        return 0
    resource_id = str(lease.get("resource_id") or "")
    seq = int(lease.get("queue_seq") or 0)
    ahead = sum(
        1 for row in _queued_for_resource(doc, resource_id)
        if int(row.get("queue_seq") or 0) < seq
    )
    return ahead + 1


# --------------------------------------------------------------------------- #
# Worker: claim / heartbeat / release.
# --------------------------------------------------------------------------- #
def claim_next(resource_id: str) -> Dict[str, Any]:
    """Atomically promote the head of the queue to active and mint a lease token.

    Returns ``{"available": False}`` when nothing can be claimed right now. The
    raw ``lease_token`` is returned exactly once and only its hash is stored.
    """
    rid = str(resource_id or "").strip()
    if not rid:
        raise NinjaTraderResourceError("resource_id обязателен.", 400, code="resource_required")
    with workspaces._LOCK:
        doc = workspaces._read_doc()
        _recover_in(doc, rid)
        head = None
        for lease in _queued_for_resource(doc, rid):
            if _can_activate(doc, rid, str(lease.get("parallel_group") or GROUP_EXCLUSIVE)):
                head = lease
                break
        if head is None:
            workspaces._write_doc(doc)
            return {"available": False, "resource_id": rid}
        token = secrets.token_urlsafe(32)
        now = _now()
        head["state"] = STATE_ACTIVE
        head["lease_token_hash"] = _token_hash(token)
        head["acquired_at_utc"] = _now_iso()
        head["heartbeat_at_utc"] = _now_iso()
        head["expires_at"] = now + LEASE_TTL_SEC
        head["expires_at_utc"] = _iso_from_epoch(now + LEASE_TTL_SEC)
        workspaces._write_doc(doc)
        job_id = str(head.get("job_id") or "")
        workspace_id = str(head.get("workspace_id") or "")
        operation_kind = str(head.get("operation_kind") or "")
    _audit("nt_lease_claimed", workspace_id=workspace_id, job_id=job_id, resource_id=rid,
           operation_kind=operation_kind)
    return {
        "available": True,
        "job_id": job_id,
        "resource_id": rid,
        "operation_kind": operation_kind,
        "lease_token": token,
        "ttl_sec": LEASE_TTL_SEC,
        "expires_in_sec": LEASE_TTL_SEC,
    }


def _authenticate_lease(lease: Optional[Dict[str, Any]], lease_token: str) -> None:
    if lease is None or str(lease.get("state") or "") != STATE_ACTIVE:
        raise NinjaTraderResourceError("Активный lease не найден.", 404, code="lease_not_active")
    supplied = _token_hash(lease_token)
    stored = str(lease.get("lease_token_hash") or "")
    if not stored or not hmac.compare_digest(stored, supplied):
        raise NinjaTraderResourceError("Неверный lease token.", 403, code="lease_token_invalid")


def heartbeat(job_id: str, *, lease_token: str) -> Dict[str, Any]:
    """Extend an active lease. Rejects a wrong worker/job/resource token."""
    with workspaces._LOCK:
        doc = workspaces._read_doc()
        lease = _find_lease(doc, job_id)
        if lease is not None and str(lease.get("state") or "") == STATE_ACTIVE \
                and float(lease.get("expires_at") or 0) <= _now():
            lease["state"] = STATE_EXPIRED
            lease["released_at_utc"] = _now_iso()
            lease["lease_token_hash"] = ""
            workspaces._write_doc(doc)
            raise NinjaTraderResourceError("Lease истёк.", 409, code="lease_expired")
        _authenticate_lease(lease, lease_token)
        now = _now()
        lease["heartbeat_at_utc"] = _now_iso()
        lease["expires_at"] = now + LEASE_TTL_SEC
        lease["expires_at_utc"] = _iso_from_epoch(now + LEASE_TTL_SEC)
        workspaces._write_doc(doc)
        expires_at = lease["expires_at_utc"]
    return {"ok": True, "job_id": str(job_id or ""), "expires_at_utc": expires_at, "ttl_sec": LEASE_TTL_SEC}


def release(job_id: str, *, lease_token: str, outcome: str = STATE_RELEASED) -> Dict[str, Any]:
    """Release an active lease (released/failed). The token is invalid afterward."""
    final = STATE_FAILED if str(outcome or "") == STATE_FAILED else STATE_RELEASED
    with workspaces._LOCK:
        doc = workspaces._read_doc()
        lease = _find_lease(doc, job_id)
        _authenticate_lease(lease, lease_token)
        lease["state"] = final
        lease["released_at_utc"] = _now_iso()
        lease["lease_token_hash"] = ""
        workspaces._write_doc(doc)
        workspace_id = str(lease.get("workspace_id") or "")
        resource_id = str(lease.get("resource_id") or "")
    _audit("nt_lease_released", workspace_id=workspace_id, job_id=str(job_id or ""),
           resource_id=resource_id, outcome=final)
    return {"ok": True, "job_id": str(job_id or ""), "state": final}


# --------------------------------------------------------------------------- #
# Cancel / recover.
# --------------------------------------------------------------------------- #
def cancel_job(user_id: Any, *, job_id: str, is_owner: bool = False, can_admin: bool = False) -> Dict[str, Any]:
    """Cancel own queued/active job. Owner/admin may cancel any job."""
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0 and not (is_owner or can_admin):
        raise NinjaTraderResourceError("Требуется вход.", 401, code="auth_required")
    with workspaces._LOCK:
        doc = workspaces._read_doc()
        lease = _find_lease(doc, job_id)
        if lease is None:
            raise NinjaTraderResourceError("Задание не найдено.", 404, code="job_not_found")
        user_uuid = _user_uuid(uid) if uid > 0 else ""
        owns = bool(user_uuid) and hmac.compare_digest(str(lease.get("requested_by_user_id") or ""), user_uuid)
        if not (owns or is_owner or can_admin):
            # Do not reveal existence details of another user's job.
            raise NinjaTraderResourceError("Задание не найдено.", 404, code="job_not_found")
        state = str(lease.get("state") or "")
        if state in TERMINAL_STATES:
            return {"ok": True, "job_id": str(job_id or ""), "state": state, "idempotent": True}
        lease["state"] = STATE_CANCELLED
        lease["released_at_utc"] = _now_iso()
        lease["lease_token_hash"] = ""
        workspaces._write_doc(doc)
        workspace_id = str(lease.get("workspace_id") or "")
        resource_id = str(lease.get("resource_id") or "")
    _audit("nt_lease_cancelled", workspace_id=workspace_id, job_id=str(job_id or ""),
           resource_id=resource_id, by_owner=bool(is_owner or can_admin))
    return {"ok": True, "job_id": str(job_id or ""), "state": STATE_CANCELLED}


def recover_expired(resource_id: str = "") -> Dict[str, Any]:
    """Sweep expired active/queued leases. Safe to call repeatedly."""
    with workspaces._LOCK:
        doc = workspaces._read_doc()
        recovered = _recover_in(doc, str(resource_id or ""))
        if recovered:
            _prune(doc)
            workspaces._write_doc(doc)
    if recovered:
        _audit("nt_lease_recovered", resource_id=str(resource_id or ""), recovered=recovered)
    return {"ok": True, "recovered": recovered, "resource_id": str(resource_id or "")}


# --------------------------------------------------------------------------- #
# Status views.
# --------------------------------------------------------------------------- #
def resource_status(user_id: Any, *, workspace_id: str = "", is_owner: bool = False) -> Dict[str, Any]:
    """Anonymized busy/queue status for the caller's active workspace.

    An ordinary user sees only free/busy/queued, their own position and a
    personal-NinjaTrader upsell — never another user's identity, workspace,
    account, strategy, job metadata or lease token.
    """
    try:
        uid = int(user_id or 0)
    except (TypeError, ValueError):
        uid = 0
    if uid <= 0:
        raise NinjaTraderResourceError("Требуется вход.", 401, code="auth_required")
    with workspaces._LOCK:
        doc = workspaces._read_doc()
        row, member = workspaces._active_workspace_doc(doc, uid, workspace_id)
        resource_id, is_shared = _resource_for_workspace(row)
        recovered = _recover_in(doc, resource_id)
        active = _active_leases(doc, resource_id)
        queued = _queued_for_resource(doc, resource_id)
        user_uuid = _user_uuid(uid, member)
        own = next(
            (lease for lease in _leases(doc)
             if isinstance(lease, dict)
             and str(lease.get("resource_id") or "") == resource_id
             and str(lease.get("state") or "") in LIVE_STATES
             and hmac.compare_digest(str(lease.get("requested_by_user_id") or ""), user_uuid)),
            None,
        )
        if recovered:
            workspaces._write_doc(doc)
        busy = bool(active)
        state = "busy" if busy else "free"
        own_state = str(own.get("state") or "") if own else ""
        own_position = _position_of(doc, own) if own else 0
        if own_state == STATE_QUEUED:
            state = "queued"
    payload = {
        "ok": True,
        "resource_kind": "shared_owner_training" if is_shared else "personal",
        "state": state,
        "busy": busy,
        "queue_depth": len(queued),
        "active_count": len(active),
    }
    if own is not None:
        payload["your_job"] = {"job_id": str(own.get("job_id") or ""), "state": own_state,
                               "position": own_position}
    if is_shared:
        payload["upsell"] = "Подключите личный NinjaTrader, чтобы запускать собственные задания независимо от общей очереди."
        if busy:
            payload["message"] = "Общий NinjaTrader сейчас выполняет бэктестирование. Ваша задача может быть поставлена в очередь."
    return payload


def admin_resource_detail(*, resource_id: str = "", workspace_id: str = "") -> Dict[str, Any]:
    """Full operational detail for owner/admin. Server enforces the capability."""
    with workspaces._LOCK:
        doc = workspaces._read_doc()
        _recover_in(doc)
        rows = []
        for lease in _leases(doc):
            if not isinstance(lease, dict):
                continue
            if resource_id and str(lease.get("resource_id") or "") != resource_id:
                continue
            if workspace_id and str(lease.get("workspace_id") or "") != workspace_id:
                continue
            rows.append(_public_lease(lease, admin=True))
        workspaces._write_doc(doc)
    rows.sort(key=lambda item: (item.get("state") != STATE_ACTIVE, item.get("queue_seq") or 0))
    resources: Dict[str, Dict[str, Any]] = {}
    for lease in rows:
        rid = str(lease.get("resource_id") or "")
        bucket = resources.setdefault(rid, {"resource_id": rid, "active": 0, "queued": 0})
        if lease["state"] == STATE_ACTIVE:
            bucket["active"] += 1
        elif lease["state"] == STATE_QUEUED:
            bucket["queued"] += 1
    return {"ok": True, "leases": rows, "resources": list(resources.values())}
