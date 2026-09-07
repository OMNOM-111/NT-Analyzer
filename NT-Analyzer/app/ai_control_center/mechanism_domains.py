"""Minimal domain adapter over the mechanisms that are already implemented.

`domain_gateway` dispatches the `automation` and `router` domains, and the
`automation_watch` worker phase, to a `mechanism_gateway` module that exists in
no branch of this repository. Until its author lands it those two routes are
registered and permanently unavailable, which is honest but useless.

This adapter connects them to the services that *are* implemented --
`automation_authority`, `scheduler` and `router_v2`. It is an adapter, not a
mechanism: it creates no second router, no second scheduler and no second
authority. Every ranking, grant, flag check, device check and budget check is
made by the existing service. Nothing here approves, selects or admits on its
own.

Two rules shape the surface:

  * reading never starts work. The read path never calls `router_v2.select`,
    `automation_authority.admit` or any scheduler tick -- it reports stored
    records and the same observation set the router itself would read.
  * an operation this adapter does not support is named in `limitations`
    rather than answered as if it worked.

`domain_gateway._mechanism_gateway()` prefers a real `mechanism_gateway` when
one appears, so this file is replaced by that module rather than merged with it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import contracts as c
from .flags import Flag, current_snapshot, resolve
from .states import ContractError, EntityKind

# Operations a caller may ask for, per domain. Anything else is a contract
# error rather than a silent no-op.
ACTIONS = {
    "automation": frozenset({"propose", "enable", "cancel", "revoke"}),
    "router": frozenset({"preview"}),
}

# Named here so a reader of the API sees what is deliberately absent rather
# than assuming the domain is complete.
LIMITATIONS = {
    "automation": [
        "Делегирование через этот домен пока не подключено: доступны предложение,"
        " включение, остановка расписания и отзыв разрешения.",
        "Разрешение ai_automation выдаётся и отзывается владельцем отдельно,"
        " существующим маршрутом POST /api/auth/users/{user_id}/permission.",
    ],
    "router": [
        "Активный выбор маршрута здесь не выполняется: предпросмотр всегда"
        " теневой и ничего не отправляет.",
        "Сравниваются только подключения с нулевой стоимостью вызова:"
        " платного согласованного бюджета для private Development-подключений нет.",
    ],
}

_ROUTER_FLAGS = ("AI_ROUTER_SHADOW_V2", "AI_ROUTER_V2")
_AUTOMATION_FLAGS = ("AI_TASK_GRAPH_V2", "AI_DELEGATION_V2", "AI_SCHEDULER_V1")


def _flags(authorized, names):
    scope = authorized["context"].scope
    snapshot = current_snapshot(authorized)
    return {name: resolve(getattr(Flag, name), scope=scope, snapshot=snapshot).enabled
            for name in names if getattr(Flag, name, None) is not None}


def _quote(*, context, model, account, profile):
    """The server's own pricing authority, never a browser-supplied number.

    A free managed endpoint costs nothing to compare. A priced one is refused
    rather than estimated: `_private_limits` already states that no approved
    paid allowance exists for private Development connections, and the router
    must never guess a price it was not given.
    """
    from ..ai_lab import agent_registry
    try:
        pricing = agent_registry.managed_pricing(
            model.provider_key, model.model_key,
            agent_registry.infer_billing_mode(model.provider_key, model.model_key, 0))
    except Exception:
        return {"allowed": False}
    if pricing.get("pricing_status") != "free":
        return {"allowed": False}
    return {"allowed": True, "cost_usd": 0.0}


def _grants(service, context):
    """Stored automation approvals, read straight from the ledger.

    `automation_authority._load` is the operational check and deliberately
    refuses an expired or superseded grant; this listing has to show those too,
    so it reads the Decision and its evidence without asking for admission.
    """
    from .automation_authority import VERSION as APPROVAL_VERSION
    rows = []
    for decision in service._all(context, EntityKind.DECISION):
        if decision.evidence_packet is None:
            continue
        try:
            proof = service._json(context, decision.evidence_packet)
        except ContractError:
            continue
        if not isinstance(proof, dict) or proof.get("version") != APPROVAL_VERSION:
            continue
        expires_at = str(proof.get("expires_at") or "")
        try:
            expired = datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
        except (ValueError, TypeError):
            expired = True
        rows.append({
            "id": str(proof.get("controller_id") or ""),
            "controller_id": str(proof.get("controller_id") or ""),
            "decision_id": str(decision.header.entity_id),
            "kind": proof.get("kind"),
            "status": decision.status,
            "operational": decision.status == "approved" and not expired,
            "expires_at": expires_at,
            "expired": expired,
            "max_call_cost_usd": proof.get("max_call_cost_usd"),
            "plan_sha256": proof.get("plan_sha256"),
            "device_mode": (proof.get("device") or {}).get("mode"),
            "grant_ref": c.primitive(decision.evidence_packet),
            "revision": decision.header.revision,
            "created_at": decision.header.created_at.isoformat(),
            "actions": ["revoke"] if decision.status == "approved" else [],
            "synthetic": False,
        })
    rows.sort(key=lambda row: row["created_at"], reverse=True)
    return rows


def _schedules(authorized, service, grants):
    from . import scheduler
    rows = []
    for grant in grants:
        if grant["kind"] != "schedule":
            continue
        try:
            view = scheduler.projection(authorized, service, grant["controller_id"])
        except ContractError as exc:
            rows.append({"id": grant["controller_id"], "status": "unavailable",
                         "reason_code": exc.code, "actions": []})
            continue
        rows.append({**view, "grant_status": grant["status"],
                     "actions": [] if view.get("status") in {"cancelled", "failed", "succeeded", "review"}
                                 else ["cancel"]})
    return rows


def _observations(service, context, model, task_class):
    """The router's own observation reader, so this is not a second opinion."""
    from .router_v2 import RoutingPolicy, _observations as read
    return read(service, context, model, task_class, datetime.now(timezone.utc), RoutingPolicy())


def _candidates(service, context, task_class):
    from .router_v2 import RoutingPolicy
    policy = RoutingPolicy()
    rows = []
    for item in service.models(context=context)["items"]:
        try:
            model = service._get(context, EntityKind.MODEL, item["id"])
            observations = _observations(service, context, model, task_class)
        except ContractError as exc:
            rows.append({"id": item["id"], "label": item.get("label"), "eligible": False,
                         "reason_codes": [exc.code], "sample_size": 0})
            continue
        rows.append({
            "id": item["id"], "label": item.get("label"),
            "persona_id": item.get("persona_id"),
            "connected": item.get("connected") is True,
            "sample_size": len(observations),
            "enough_evidence": len(observations) >= policy.min_distinct_samples,
            "all_passed": all(row["passed"] for row in observations) if observations else False,
            "observed_max_latency_ms": max((row["latency_ms"] for row in observations), default=None),
            "evidence": [row["ref"] for row in observations],
        })
    rows.sort(key=lambda row: (-row["sample_size"], str(row["id"])))
    return rows


def _task_class(service, context, task_id):
    task = service._get(context, EntityKind.TASK, task_id)
    checkpoint = service._json(context, task.checkpoint)
    spec = checkpoint.get("spec") or {}
    return task, checkpoint, str(spec.get("rubric_key") or checkpoint.get("task_class") or "")


def read(authorized, service, domain, *, identity=None, limit=50, cursor=None):
    """Report state. Never selects, admits, queues or executes anything."""
    if domain not in ACTIONS:
        raise ContractError("unknown_domain")
    context = authorized["context"]
    capabilities = authorized["chat_scope"].get("capabilities") or {}
    if domain == "automation":
        grants = _grants(service, context)
        if identity:
            grants = [row for row in grants if row["controller_id"] == str(identity)]
        return {"enabled": True, "items": grants[:limit], "next_cursor": None,
                "schedules": _schedules(authorized, service, grants),
                "capabilities": {"ai_automation": capabilities.get("ai_automation") is True},
                "capability_route": "POST /api/auth/users/{user_id}/permission",
                "flags": _flags(authorized, _AUTOMATION_FLAGS),
                "limitations": list(LIMITATIONS["automation"]), "synthetic": False}

    flags = _flags(authorized, _ROUTER_FLAGS)
    from .router_v2 import RoutingPolicy, _CLASSES
    if identity:
        task, checkpoint, task_class = _task_class(service, context, identity)
        chosen = str(checkpoint.get("model_id") or "")
        candidates = _candidates(service, context, task_class) if task_class in _CLASSES else []
        return {"enabled": True, "items": candidates, "next_cursor": None,
                "task": {"id": str(task.header.entity_id), "task_class": task_class,
                         "model_id": chosen, "status": task.status,
                         "revision": task.header.revision},
                # What actually ran, beside the evidence a decision would rest
                # on. No decision is computed here: `preview` does that.
                "actual_choice": {"model_id": chosen, "decided_by": "request",
                                  "routing_applied": False},
                "policy_version": RoutingPolicy().version, "flags": flags,
                "limitations": list(LIMITATIONS["router"]), "synthetic": False}
    return {"enabled": True, "items": [], "next_cursor": None,
            "task_classes": sorted(_CLASSES), "policy_version": RoutingPolicy().version,
            "flags": flags, "limitations": list(LIMITATIONS["router"]), "synthetic": False}


def _require(payload, *names):
    missing = [name for name in names if payload.get(name) in (None, "")]
    if missing:
        raise ContractError("mechanism_payload_incomplete")
    return [payload[name] for name in names]


def mutate(authorized, service, domain, identity, action, payload, *, expected_revision, idempotency_key):
    """Delegate one operation to the mechanism that owns it."""
    if domain not in ACTIONS:
        raise ContractError("unknown_domain")
    if action not in ACTIONS[domain]:
        raise ContractError("mechanism_action_unsupported")
    context = authorized["context"]
    if domain == "router":
        return _preview(authorized, service, identity, payload)
    from . import automation_authority, delegation, scheduler
    if action == "revoke":
        reference = delegation.snapshot(context, payload.get("grant_ref"))
        return automation_authority.revoke(authorized, service, reference)
    if action == "cancel":
        return scheduler.cancel(authorized, service, identity)

    from . import domain_gateway
    domain_service = domain_gateway.domains(authorized, service.repository)
    model_id, schedule, spec = _require(payload, "model_id", "schedule", "payload")
    source_domain = str(payload.get("source_domain") or "routines")
    conversation_id, message_id = payload.get("conversation_id"), payload.get("message_id")
    if not conversation_id or not message_id:
        # A schedule repeats a request the owner actually made, so the plan is
        # anchored to that message. The scheduler refuses a plan whose source
        # message does not exist and is not the owner's own, so the caller
        # names the task being repeated instead of naming any conversation.
        source_task = payload.get("source_task_id")
        if not source_task:
            raise ContractError("mechanism_source_request_required")
        checkpoint = service._json(context, service._get(context, EntityKind.TASK, source_task).checkpoint)
        conversation_id = conversation_id or checkpoint.get("conversation_id")
        message_id = message_id or checkpoint.get("message_id")
    if not conversation_id or not message_id:
        raise ContractError("mechanism_source_request_required")
    common = {"domain": source_domain, "identity": identity,
              "expected_revision": expected_revision, "model_id": model_id, "schedule": schedule,
              "payload": spec, "idempotency_key": idempotency_key,
              "conversation_id": conversation_id, "message_id": message_id}
    proposed = scheduler.propose(authorized, service, domain_service, **common)
    if action == "propose":
        # Read-only by the scheduler's own contract: no controller, no queue
        # entry and no grant exist after this.
        return {**proposed, "approved": False, "actions": ["enable"]}

    from .automation_authority import normalized_plan
    from .model_evaluation import digest
    hours = payload.get("grant_hours", 8)
    if type(hours) not in {int, float} or not 0 < hours <= 24 * 30:
        raise ContractError("mechanism_grant_window_invalid")
    ceiling = payload.get("max_call_cost_usd", 0.0)
    grant = automation_authority.approve(
        authorized, service,
        proposal={"controller_id": proposed["controller_id"], "plan": proposed["plan"]},
        kind="schedule", expires_at=(datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(),
        max_call_cost_usd=ceiling,
        approved_plan_sha256=digest(normalized_plan(proposed["plan"])),
        idempotency_key=idempotency_key)
    created = scheduler.create(authorized, service, domain_service, grant_ref=grant, **common)
    return {**created, "grant_ref": grant, "approved": True, "actions": ["cancel", "revoke"]}


def _preview(authorized, service, identity, payload):
    """A shadow decision for one existing task: real ranking, no dispatch."""
    from .router_v2 import _CLASSES, select
    context = authorized["context"]
    if not identity or identity == "new":
        raise ContractError("mechanism_task_required")
    task, checkpoint, task_class = _task_class(service, context, identity)
    if task_class not in _CLASSES:
        raise ContractError("routing_task_class_unsupported")
    current = str(checkpoint.get("model_id") or "")
    ids = payload.get("candidate_model_ids")
    if ids is None:
        ids = [row["id"] for row in service.models(context=context)["items"]]
    if current not in ids:
        ids = [current, *ids]
    request = {"mode": "shadow", "task_class": task_class, "candidate_model_ids": list(ids),
               "current_model_id": current,
               "max_cost_usd": payload.get("max_cost_usd", 0.0),
               "max_latency_ms": payload.get("max_latency_ms", 60000)}
    decision = select(authorized, service, request, quote=_quote)
    return {**decision, "task_id": str(task.header.entity_id),
            "actual_model_id": current,
            "would_change": decision.get("selected_model_id") not in (None, current),
            "applied": False, "limitations": list(LIMITATIONS["router"])}


def execute_watch(authorized, service, job, cancelled, heartbeat):
    """The scheduled scan a worker would run when nothing is watching.

    `scan_due` is the scheduler's own recovery scan: it ticks controllers that
    are actually due and reports the rest untouched. Nothing new is invented
    here, and no occurrence is dispatched that the scheduler would not have
    dispatched itself.
    """
    from . import scheduler
    authorized["admit"]()
    if cancelled():
        raise ContractError("model_cancelled")
    heartbeat()
    scanned = scheduler.scan_due(authorized, service)
    heartbeat()
    return {"ok": True, "phase": "automation_watch", "scanned": len(scanned),
            "controllers": [row.get("id") for row in scanned], "synthetic": False}
