"""Finite automation approval over existing auth, Decision and budget stores.

No session is minted, no capability is granted here, and a stored plan is not
authority by itself. Worker ingress resolves a fresh service actor on behalf of
the same human. A normal user cannot inherit an owner's key or Local exemption.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time
import copy
from uuid import UUID, uuid5

from .. import account_auth, ai_budgets, permissions, runtime_env, workspaces
from . import contracts as c, live_gateway
from .flags import Flag, resolve
from .model_evaluation import digest
from .states import ContractError, EntityKind

VERSION = "finite-automation-approval-v1"
_OPERATIONS = {
    "delegation": frozenset({"delegation_create", "delegation_step", "delegation_queue", "delegation_reconcile"}),
    "schedule": frozenset({"schedule_create", "schedule_step", "schedule_queue", "schedule_tick", "schedule_scan"}),
}


def normalized_plan(plan):
    if type(plan) is not dict:
        raise ContractError("automation_plan_required")
    return copy.deepcopy({key: value for key, value in plan.items() if key not in {"grant_ref", "expires_at"}})


def _subject(scope, *, read_only=False):
    if not runtime_env.is_development() or not isinstance(scope, dict):
        raise ContractError("automation_development_only")
    try:
        if type(scope["user_id"]) not in {int, str}:
            raise ValueError
        uid, identity = int(scope["user_id"]), UUID(str(scope["user_uuid"]))
        workspace_id = str(scope["workspace_id"])
    except (KeyError, ValueError, TypeError):
        raise ContractError("automation_subject_invalid") from None
    if uid <= 0 or not live_gateway.configured(workspace_id):
        raise ContractError("automation_workspace_disabled")
    user = account_auth.find_active_user(uid)
    if (not user or user.get("is_preview_user") or user.get("is_service_account")
            or str(user.get("user_uuid")) != str(identity)):
        raise ContractError("automation_subject_inactive")
    reader = workspaces.require_workspace_access if read_only else workspaces.require_workspace_writer
    workspace = reader(uid, workspace_id=workspace_id)
    if (workspace.get("status") != "active" or (not read_only and
            (str(workspace.get("owner_user_id")) != str(uid) or (workspace.get("membership") or {}).get("role") != "owner"))):
        raise ContractError("automation_workspace_access_denied")
    capabilities = permissions.resolve_for_user_id(uid, user)["capabilities"]
    if not read_only and not all(capabilities.get(key) is True for key in ("ai_lab", "ai_pro_models", "ai_automation")):
        raise ContractError("automation_entitlement_required")
    return user, {"user_id": uid, "user_uuid": str(identity), "workspace_id": workspace_id,
        "workspace_kind": workspace["kind"], "uses_owner_runtime": bool(workspace.get("uses_owner_runtime")),
        "is_owner": user.get("is_owner") is True, "membership_role": (workspace.get("membership") or {}).get("role"),
        "capabilities": capabilities, "display_name": str(user.get("display_name") or "")}


def _bound_subject(authorized, *, read_only=False):
    """Bind the trusted context to fresh auth; caller-supplied flags are not authority."""
    if not isinstance(authorized, dict) or not isinstance(authorized.get("context"), c.RequestContext):
        raise ContractError("automation_scope_invalid")
    context = authorized["context"]
    user, current = _subject(authorized.get("chat_scope"), read_only=read_only)
    source = authorized.get("source_scope") or {}
    if (context.scope.environment != c.Environment.DEVELOPMENT
            or current["workspace_id"] != context.scope.workspace_id
            or current["user_uuid"] != str(context.user_uuid)
            or str(source.get("user_id")) != str(current["user_id"])
            or source.get("workspace_id") != context.scope.workspace_id):
        raise ContractError("automation_scope_invalid")
    if context.actor.kind == c.ActorKind.SERVICE:
        if (not authorized.get("automation") or context.actor.actor_id !=
                uuid5(context.user_uuid, "agent-world-automation:" + context.scope.workspace_id)):
            raise ContractError("automation_service_actor_invalid")
    elif context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("automation_actor_invalid")
    return user, current


def device_binding(scope, *, saved=None):
    """Read the existing trusted-client registry; permanent != session-only."""
    user, current = _subject(scope)
    uid = int(scope["user_id"])
    if saved is not None and (type(saved) is not dict or saved.get("mode") not in {"local_owner", "permanent", "session"}):
        raise ContractError("automation_device_binding_invalid")
    mode = (saved or {}).get("mode")
    sid = str((saved or {}).get("session_id") or scope.get("auth_session_id") or "")
    if not sid and mode in {None, "local_owner"}:
        if (user.get("is_owner") is not True or current["uses_owner_runtime"] is not True
                or current["membership_role"] != "owner" or (saved is not None and saved != {"mode": "local_owner"})):
            raise ContractError("automation_device_confirmation_required")
        return {"mode": "local_owner"}
    if (not sid or len(sid) > 80 or mode == "local_owner" or (saved is not None
            and set(saved) != {"mode", "device_id", "session_id"})):
        raise ContractError("automation_device_binding_invalid")
    # This module is Development-only. Production auth documents/DSNs are
    # never used as a fallback for the local worker.
    if account_auth._authoritative_storage():
        raise ContractError("automation_device_authority_unavailable")
    with account_auth._LOCK:
        doc = account_auth._read_doc_reference()
        session = next((row for row in doc.get("sessions", [])
            if account_auth._session_id(row) == sid and int(row.get("user_id") or 0) == uid), None)
        if not session or session.get("revoked"):
            raise ContractError("automation_approving_session_revoked")
        if account_auth._session_confirmation_state(session) != "active":
            raise ContractError("automation_device_confirmation_required")
        device_id = str(session.get("trusted_device_id") or "")
        if saved and device_id != saved.get("device_id"):
            raise ContractError("automation_device_binding_changed")
        device = next((row for row in doc.get("trusted_devices", [])
            if row.get("device_id") == device_id and str(row.get("user_uuid")) == str(scope["user_uuid"])), None)
        if not device or device.get("status") in {"revoked", "expired"}:
            raise ContractError("automation_device_revoked")
        trust = str(session.get("device_trust_mode") or "")
        if trust not in {"permanent", "session"}:
            raise ContractError("automation_device_confirmation_required")
        if saved and trust != saved.get("mode"):
            raise ContractError("automation_device_binding_changed")
        if trust == "permanent":
            if (device.get("status") != "trusted" or device.get("trust_mode", "permanent") != "permanent"
                    or (float(device.get("expires_at") or 0) > 0 and float(device["expires_at"]) <= time.time())):
                raise ContractError("automation_device_revoked")
        elif float(session.get("expires_at") or 0) <= time.time():
            raise ContractError("automation_session_expired")
        # Creation always requires the current active session, even for a
        # permanent device. Later checks may survive its natural expiry only.
        if saved is None and float(session.get("expires_at") or 0) <= time.time():
            raise ContractError("automation_session_expired")
        return {"mode": trust, "device_id": device_id, "session_id": sid}


def _load(service, context, reference, *, operational=True):
    from .delegation import snapshot, utc
    ref = snapshot(context, reference)
    proof = service._json(context, ref)
    if (proof.get("version") != VERSION or proof.get("user_uuid") != str(context.user_uuid)
            or proof.get("scope") != c.primitive(context.scope) or proof.get("kind") not in _OPERATIONS
            or type(proof.get("user_id")) is not int or proof["user_id"] <= 0
            or digest(normalized_plan(proof.get("plan"))) != proof.get("plan_sha256")):
        raise ContractError("automation_approval_invalid")
    decision = service._get(context, EntityKind.DECISION, proof.get("decision_id"))
    if (decision.header.created_by.kind != c.ActorKind.HUMAN
            or decision.header.created_by.actor_id != context.user_uuid
            or decision.approval != ref or decision.evidence_packet != ref
            or decision.status not in ({"approved"} if operational else {"approved", "superseded", "expired"})):
        raise ContractError("automation_approval_revoked")
    intent = service._get(context, EntityKind.INTENT, decision.intent.entity_id)
    if (intent.goal != ref or intent.header.created_by.kind != c.ActorKind.HUMAN
            or intent.header.created_by.actor_id != context.user_uuid
            or intent.header.correlation_id != UUID(proof["controller_id"])
            or decision.header.correlation_id != intent.header.correlation_id):
        raise ContractError("automation_approval_invalid")
    if operational and utc(proof.get("expires_at")) <= datetime.now(timezone.utc):
        raise ContractError("automation_approval_expired")
    if (proof.get("kind") not in _OPERATIONS or type(proof.get("max_call_cost_usd")) not in {int, float}
            or not math.isfinite(proof["max_call_cost_usd"]) or not 0 <= proof["max_call_cost_usd"] <= 1):
        raise ContractError("automation_approval_invalid")
    return decision, proof, ref


def approve(authorized, service, *, proposal, kind, expires_at, max_call_cost_usd,
            approved_plan_sha256, idempotency_key):
    """Called only by an explicit human POST after a read-only plan preview."""
    from .model_service import _id, _key
    from .delegation import utc
    context = authorized["context"]
    authorized["admit"]()
    if (context.actor.kind != c.ActorKind.HUMAN or authorized.get("read_only")
            or authorized.get("session_read_only") or kind not in _OPERATIONS):
        raise ContractError("automation_human_approval_required")
    _, current = _bound_subject(authorized)
    key = _key(idempotency_key)
    expiry = utc(expires_at)
    now = datetime.now(timezone.utc)
    if not now < expiry <= now + timedelta(days=30):
        raise ContractError("automation_approval_expiry_invalid")
    if type(max_call_cost_usd) not in {int, float} or not math.isfinite(max_call_cost_usd) or not 0 <= max_call_cost_usd <= 1:
        raise ContractError("automation_call_ceiling_invalid")
    if type(proposal) is not dict or set(proposal) != {"controller_id", "plan"}:
        raise ContractError("automation_proposal_invalid")
    plan = normalized_plan(proposal["plan"])
    from . import delegation, scheduler
    if (plan.get("version") != (delegation.VERSION if kind == "delegation" else scheduler.VERSION)
            or plan.get("synthetic") is not False):
        raise ContractError("automation_plan_invalid")
    if digest(plan) != approved_plan_sha256:
        raise ContractError("automation_plan_changed")
    from .model_service import _uuid
    identity = _uuid(proposal["controller_id"])
    if identity != _id(context, ("delegation:" if kind == "delegation" else "schedule:") + key):
        raise ContractError("automation_controller_mismatch")
    decision_id = _id(context, "automation-approval:" + str(identity))
    binding = device_binding(authorized["chat_scope"])
    policy = service._put(context, {"version": VERSION, "human_acceptance": "separate", "trading": False})
    proof = {"version": VERSION, "kind": kind, "controller_id": str(identity), "decision_id": str(decision_id),
        "scope": c.primitive(context.scope), "user_uuid": str(context.user_uuid), "user_id": current["user_id"],
        "plan_sha256": digest(plan), "plan": plan, "device": binding, "expires_at": expiry.isoformat(),
        "max_call_cost_usd": max_call_cost_usd, "workspace_budget_authority": "ai_budgets", "self_scored": False}
    evidence = service._put(context, proof)
    intent = service._ensure(context, c.Intent, _id(context, "automation-intent:" + str(identity)), identity, policy,
        goal=evidence, acceptance=policy, risk=c.Risk.LOW, autonomy=c.Autonomy.DRAFT,
        budget=c.ExternalRef(authority=c.ExternalAuthority.BUDGET, key="ai_budgets.automation." + str(identity), scope=context.scope))
    # A crash after Intent but before Decision must not allow a retry to replace
    # the approved plan. _ensure intentionally only ensures entity identity.
    if (intent.goal != evidence or intent.acceptance != policy or intent.header.correlation_id != identity
            or intent.header.created_by != context.actor or intent.risk != c.Risk.LOW or intent.autonomy != c.Autonomy.DRAFT):
        raise ContractError("automation_approval_idempotency_conflict")
    if intent.deadline != expiry:
        intent = service._change(context, intent, deadline=expiry)
    decision = service._ensure(context, c.Decision, decision_id, identity, policy,
        intent=intent.ref(), contributions=(), evidence_packet=evidence)
    if (decision.evidence_packet != evidence or decision.intent != intent.ref()
            or decision.header.created_by != context.actor or decision.header.correlation_id != identity):
        raise ContractError("automation_approval_idempotency_conflict")
    if decision.status == "proposed": decision = service._change(context, decision, "review")
    if decision.status == "review": decision = service._change(context, decision, "approved", approval=evidence)
    if decision.status != "approved" or decision.approval != evidence:
        raise ContractError("automation_approval_revoked")
    return c.primitive(evidence)


def admit(authorized, service, *, context, controller, grant_ref, operation, model_id=None,
          estimated_cost_usd=0.0, proposed_plan=None):
    from .model_service import _uuid
    if context != authorized["context"] or not isinstance(controller, c.EntityRef) or controller.kind != EntityKind.TASK:
        raise ContractError("automation_scope_invalid")
    c.require_same_scope(context.scope, controller.scope)
    if authorized.get("read_only") or authorized.get("session_read_only"):
        raise ContractError("automation_read_only")
    decision, proof, ref = _load(service, context, grant_ref)
    _, current = _bound_subject(authorized)
    if proof["user_id"] != current["user_id"]:
        raise ContractError("automation_scope_invalid")
    if str(controller.entity_id) != proof["controller_id"]:
        raise ContractError("automation_controller_mismatch")
    if authorized.get("automation"):
        from .delegation import snapshot
        if (authorized.get("automation_controller_id") != proof["controller_id"]
                or snapshot(context, authorized.get("automation_grant_ref")) != ref):
            raise ContractError("automation_service_binding_changed")
    device_binding(current, saved=proof["device"])
    if operation not in _OPERATIONS[proof["kind"]] and operation not in {"provider_transmit", "execute", "task", "complete", "read"}:
        raise ContractError("automation_operation_denied")
    if proposed_plan is None:
        task = service._get(context, EntityKind.TASK, controller.entity_id)
        proposed_plan = service._json(context, service._json(context, task.checkpoint)["plan"])
    if digest(normalized_plan(proposed_plan)) != proof["plan_sha256"]:
        raise ContractError("automation_plan_changed")
    flag = Flag.AI_DELEGATION_V2 if proof["kind"] == "delegation" else Flag.AI_SCHEDULER_V1
    if not resolve(flag, scope=context.scope, snapshot=live_gateway.flag_snapshot(context)).enabled:
        raise ContractError("automation_disabled")
    if model_id is not None:
        allowed = [row["model_id"] for row in proof["plan"].get("nodes", [])] if proof["kind"] == "delegation" else [proof["plan"].get("model_id")]
        if str(_uuid(model_id)) not in allowed:
            raise ContractError("automation_model_not_approved")
    if (type(estimated_cost_usd) not in {int, float} or not math.isfinite(estimated_cost_usd)
            or not 0 <= estimated_cost_usd <= proof["max_call_cost_usd"]
            or not ai_budgets.check_budget(context.scope.workspace_id, estimated_cost_usd).get("ok")):
        raise ContractError("automation_budget_denied")
    return {"approved_scope": c.primitive(context.scope), "revision": decision.header.revision,
            "sha256": ref.sha256, "expires_at": proof["expires_at"]}


def access(scope, *, controller_id, grant_ref, read_only=False):
    """Trusted worker ingress, never a request-body or browser-session grant."""
    from . import domain_gateway
    from .model_service import ModelService
    user, normalized = _subject(scope, read_only=read_only)
    human = UUID(normalized["user_uuid"])
    context = c.RequestContext(scope=c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id=normalized["workspace_id"]),
        user_uuid=human, actor=c.ActorRef(kind=c.ActorKind.SERVICE, actor_id=uuid5(human, "agent-world-automation:" + normalized["workspace_id"]), on_behalf_of=human))
    def base_admit():
        _subject(normalized, read_only=read_only)
        if not resolve(Flag.AI_TASK_GRAPH_V2, scope=context.scope, snapshot=live_gateway.flag_snapshot(context)).enabled:
            raise ContractError("automation_disabled")
    result = {"context": context, "chat_scope": normalized, "admit": base_admit,
        "source_scope": {"workspace_id": normalized["workspace_id"], "user_id": normalized["user_id"], "allow_legacy": False},
        "snapshot": live_gateway.flag_snapshot(context), "read_only": read_only, "automation": True,
        "automation_controller_id": str(UUID(str(controller_id))), "automation_grant_ref": grant_ref}
    service = ModelService(domain_gateway.repository(result), admit=lambda *_: base_admit())
    def revalidate():
        base_admit()
        if read_only:
            # Ownership of the immutable approval is still required for history,
            # even after its operational expiry/revocation. No new step is allowed.
            _, proof, _ = _load(service, context, grant_ref, operational=False)
            if proof["user_id"] != normalized["user_id"] or proof.get("controller_id") != result["automation_controller_id"]:
                raise ContractError("automation_approval_invalid")
        else:
            ref = c.EntityRef(kind=EntityKind.TASK, entity_id=UUID(str(controller_id)), revision=1, scope=context.scope)
            admit(result, service, context=context, controller=ref, grant_ref=grant_ref, operation="read")
    result["admit"] = revalidate
    result["refresh"] = lambda **kw: access(normalized, controller_id=controller_id, grant_ref=grant_ref, read_only=kw.get("read_only", read_only))
    revalidate()
    return result


def revoke(authorized, service, grant_ref):
    """Stopping is allowed after the automation flag/capability is disabled."""
    from .delegation import snapshot
    context = authorized["context"]
    authorized["admit"]()
    if authorized.get("read_only") or authorized.get("session_read_only") or context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("automation_human_approval_required")
    _, current = _bound_subject(authorized, read_only=True)
    decision, proof, ref = _load(service, context, grant_ref, operational=False)
    if proof["user_id"] != current["user_id"]:
        raise ContractError("automation_approval_invalid")
    if decision.status == "approved": service._change(context, decision, "superseded")
    return {"revoked": True, "controller_id": proof["controller_id"]}
