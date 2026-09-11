"""Explainable, scoped model selection; shadow does not change legacy routing.

Identity, current admission and same-class measurements are distinct inputs.
Diagnostic evidence is never a professional-quality score. This module reads
only the existing records and artifacts and never opens a provider connection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from uuid import UUID

from . import contracts as c
from .flags import DISABLED, Flag, current_snapshot, resolve
from .model_evaluation import digest
from .states import ContractError, EntityKind


VERSION = "agent-world-router-v2.1"
PREVIEW_VERSION = "agent-world-routing-preview-v2"
APPLIED_VERSION = "agent-world-routing-applied-v2"
_LEGACY_PREVIEW_VERSION = "agent-world-routing-preview-v1"
_LEGACY_APPLIED_VERSION = "agent-world-routing-applied-v1"
_CLASSES = frozenset({"json_arithmetic", "extract_facts", "backtest_spec", "chart_spec"})


@dataclass(frozen=True, kw_only=True)
class RoutingPolicy:
    """Trusted server composition, not a request-body policy or permission."""

    version: str = VERSION
    min_distinct_samples: int = 3
    max_candidates: int = 20
    max_sample_age_seconds: int = 30 * 86400

    def __post_init__(self):
        c.require_token(self.version)
        if (type(self.min_distinct_samples) is not int or not 3 <= self.min_distinct_samples <= 100
                or type(self.max_candidates) is not int or not 1 <= self.max_candidates <= 50
                or type(self.max_sample_age_seconds) is not int or not 60 <= self.max_sample_age_seconds <= 90 * 86400):
            raise ContractError("routing_policy_invalid")


def _number(value, *, positive=False):
    return (type(value) in {int, float} and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def _gate(authorized, mode):
    if type(mode) is not str or mode not in {"shadow", "active"} or not isinstance(authorized, dict):
        raise ContractError("routing_mode_invalid")
    context = authorized.get("context")
    if not isinstance(context, c.RequestContext) or not callable(authorized.get("admit")):
        raise ContractError("routing_context_required")
    authorized["admit"]()
    # An active switch is not an interpretation of the existing shadow flag.
    flag = getattr(Flag, "AI_ROUTER_V2", None) if mode == "active" else Flag.AI_ROUTER_SHADOW_V2
    if flag is None or not resolve(flag, scope=context.scope, snapshot=current_snapshot(authorized)).enabled:
        raise ContractError("routing_disabled")
    if mode == "active" and (authorized.get("read_only") or authorized.get("session_read_only")):
        raise ContractError("routing_read_only")
    return context


def _observations(service, context, model, task_class, now, policy):
    """Read independently recorded model observations for this exact class."""
    rows = {}
    for record in service._all(context, EntityKind.EVALUATION):
        # Routing compares models, so only model-subject observations count.
        if (record.rubric_key != task_class or record.subject.kind is not EntityKind.MODEL
                or record.subject.entity_id != model.header.entity_id):
            continue
        if not 0 <= (now - record.header.created_at).total_seconds() <= policy.max_sample_age_seconds:
            continue
        proof = service._json(context, record.evidence)
        if (proof.get("rubric_key") != task_class or proof.get("synthetic") is not False
                or proof.get("self_scored") is not False
                or proof.get("evaluator") != "independent_local_evidence_verifier"
                or proof.get("model_id") != str(model.header.entity_id)
                or type(proof.get("passed")) is not bool or not _number(proof.get("latency_ms"))
                or not _number(proof.get("cost_usd"))):
            continue
        source = service._get(context, EntityKind.TASK, record.task.entity_id)
        checkpoint = service._json(context, source.checkpoint)
        if (checkpoint.get("synthetic") is not False or checkpoint.get("source") != "real_model_task"
                or checkpoint.get("model_id") != str(model.header.entity_id)
                or checkpoint.get("spec", {}).get("rubric_key") != task_class
                or proof.get("input_sha256") != digest(checkpoint["spec"])
                or proof.get("task_id") != str(source.header.entity_id)):
            continue
        receipt_ref = proof.get("receipt")
        if not receipt_ref or receipt_ref != checkpoint.get("receipt"):
            continue
        receipt = service._json(context, receipt_ref)
        if (receipt.get("task_id") != str(source.header.entity_id)
                or receipt.get("request_sha256") != checkpoint.get("request_sha256")
                or receipt.get("latency_ms") != proof["latency_ms"] or receipt.get("cost_usd") != proof["cost_usd"]):
            continue
        # Older named-test receipts carried a false marker. Derive their origin
        # from immutable executor identity; they never qualify a real route.
        checked = service._validated_evidence(context, source, checkpoint, receipt, record)
        if checked.get("synthetic") is not False:
            continue
        # One immutable input is one observation; another retry is not a sample.
        rows.setdefault(proof["input_sha256"], {"ref": c.primitive(record.ref()),
            "latency_ms": proof["latency_ms"], "cost_usd": proof["cost_usd"], "passed": proof["passed"]})
    return [rows[key] for key in sorted(rows)]


def select(authorized, service, request, policy=None, *, quote=None, now=None):
    """Return candidate/exclusion evidence; caller must use normal task ingress.

    quote is a trusted server callback(context, model, account, profile), using
    existing permission/pricing/budget authorities. It returns current bounded
    cost_usd and allowed=True, or denies. Missing pricing is never guessed from
    the historical mean. No result grants task, tool or credential access.
    """
    policy = policy or RoutingPolicy()
    if not isinstance(policy, RoutingPolicy) or type(request) is not dict:
        raise ContractError("routing_request_invalid")
    if set(request) != {"mode", "task_class", "candidate_model_ids", "current_model_id", "max_cost_usd", "max_latency_ms"}:
        raise ContractError("routing_request_invalid")
    context = _gate(authorized, request["mode"])
    from . import test_executor
    test_mode = test_executor.enabled(context.scope.workspace_id)
    if type(request["task_class"]) is not str or request["task_class"] not in _CLASSES or not _number(request["max_cost_usd"]) or not _number(request["max_latency_ms"], positive=True):
        raise ContractError("routing_constraints_invalid")
    ids = request["candidate_model_ids"]
    if type(ids) is not list or not 1 <= len(ids) <= policy.max_candidates:
        raise ContractError("routing_candidates_invalid")
    from .model_service import _id, _uuid
    model_ids = tuple(_uuid(value) for value in ids)
    if len(set(model_ids)) != len(model_ids):
        raise ContractError("routing_candidates_invalid")
    current_id = _uuid(request["current_model_id"])
    if current_id not in model_ids:
        raise ContractError("routing_current_candidate_required")
    now = now or datetime.now(timezone.utc)
    c.require_utc(now)
    rows = []
    for identity in model_ids:
        row = {"model_id": str(identity), "eligible": False, "reason_codes": [], "quality_score": None,
               "quality_effect": "none", "evidence": [], "task_class": request["task_class"],
               "execution_origin": "local_test_executor" if test_mode else "configured_provider",
               "execution_synthetic": test_mode}
        try:
            authorized["admit"]()
            model = service._get(context, EntityKind.MODEL, identity)
            profile = service._json(context, model.profile)
            persona = service._get(context, EntityKind.PERSONA, profile["persona_id"])
            account = service._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
            role = service._get(context, EntityKind.AGENT_ROLE, _id(context, "role:model-response"))
            if (model.status != "active" or persona.status != "active" or account.status != "active"
                    or role.status != "active" or role.role_key != "model_response"):
                raise ContractError("routing_identity_inactive")
            if profile.get("connection_kind") not in {"model", "external_agent"} or "text" not in model.modalities:
                raise ContractError("routing_connection_kind_unsupported")
            row.update(persona_id=str(persona.header.entity_id), role_id=str(role.header.entity_id),
                provider_account_id=str(account.header.entity_id), provider=model.provider_key,
                model_key=model.model_key, connection_kind=profile["connection_kind"],
                external_agent_id=str(model.header.entity_id) if profile["connection_kind"] == "external_agent" else None,
                identity_revisions={"persona": persona.header.revision, "role": role.header.revision,
                    "provider_account": account.header.revision, "model": model.header.revision})
            if service.model_detail(context=context, model_id=identity).get("connected") is not True:
                raise ContractError("routing_connection_not_verified")
            if not callable(quote):
                raise ContractError("routing_current_admission_unavailable")
            allowance = quote(context=context, model=model, account=account, profile=profile)
            if (type(allowance) is not dict or allowance.get("allowed") is not True
                    or not _number(allowance.get("cost_usd"))):
                raise ContractError("routing_current_admission_denied")
            if allowance["cost_usd"] > request["max_cost_usd"]:
                raise ContractError("routing_cost_limit")
            # Includes present capability and workspace budget, not just history.
            service._access(context, "task", allowance["cost_usd"])
            observations = _observations(service, context, model, request["task_class"], now, policy)
            row.update(sample_size=len(observations), evidence=[item["ref"] for item in observations])
            if len(observations) < policy.min_distinct_samples:
                raise ContractError("routing_same_class_insufficient_data")
            if not all(item["passed"] for item in observations):
                raise ContractError("routing_same_class_verification_failed")
            required_role = {"backtest_spec": "backtest_researcher", "chart_spec": "chart_researcher"}.get(request["task_class"])
            if required_role and service._json(context, persona.profile).get("application_role") != required_role:
                raise ContractError("routing_application_role_unassigned")
            worst_latency = max(item["latency_ms"] for item in observations)
            if worst_latency > request["max_latency_ms"]:
                raise ContractError("routing_latency_limit")
            row.update(eligible=True, current_cost_usd=allowance["cost_usd"], observed_max_latency_ms=worst_latency)
            row["reason_codes"] = ["current_authority_pass", "same_class_latency_evidence", "cost_then_latency_policy"]
        except ContractError as exc:
            row["reason_codes"] = [exc.code]
        rows.append(row)
    eligible = sorted((row for row in rows if row["eligible"]),
                      key=lambda row: (row["current_cost_usd"], row["observed_max_latency_ms"], row["model_id"]))
    selected = eligible[0]["model_id"] if eligible else None
    _gate(authorized, request["mode"])
    result = {"schema_version": 1, "policy_version": policy.version, "mode": request["mode"],
        "workspace_id": context.scope.workspace_id, "user_uuid": str(context.user_uuid),
        "task_class": request["task_class"], "selected_model_id": selected,
        "effective_model_id": selected if request["mode"] == "active" else str(current_id),
        "legacy_model_id": str(current_id), "matches_legacy": selected == str(current_id),
        "status": "selected" if selected else "blocked", "candidates": rows,
        "constraints": {key: request[key] for key in ("max_cost_usd", "max_latency_ms")},
        "quality_ranking": False, "dispatch_performed": False, "permission_granted": False,
        "measured_at": now.isoformat(), "synthetic": test_mode}
    result["decision_sha256"] = digest(result)
    return result


def selection_fingerprint(decision):
    """Choice/evidence/identity constraints, not a changing wall-clock timestamp."""
    keys = (
        "schema_version", "policy_version", "workspace_id", "user_uuid", "task_class",
        "selected_model_id", "legacy_model_id", "status", "candidates", "constraints",
        "quality_ranking", "dispatch_performed", "permission_granted", "synthetic")
    if (type(decision) is not dict or any(key not in decision for key in keys)
            or type(decision["candidates"]) is not list
            or any(type(row) is not dict for row in decision["candidates"])):
        raise ContractError("routing_preview_invalid")
    return digest({key: decision[key] for key in keys})


def _snapshot(context, value):
    if isinstance(value, c.SnapshotRef):
        c.require_same_scope(context.scope, value.scope)
        return value
    if (type(value) is not dict or set(value) != {"artifact_id", "sha256", "scope"}
            or value.get("scope") != c.primitive(context.scope)):
        raise ContractError("routing_preview_reference_required")
    from .model_service import _uuid
    return c.SnapshotRef(scope=context.scope, artifact_id=_uuid(value["artifact_id"]), sha256=value["sha256"])


def _entity_ref(context, value, kind):
    from .model_service import _uuid
    if (type(value) is not dict or set(value) != {"kind", "entity_id", "revision", "scope"}
            or value.get("kind") != kind.value or value.get("scope") != c.primitive(context.scope)):
        raise ContractError("routing_source_invalid")
    return c.EntityRef(kind=kind, entity_id=_uuid(value["entity_id"]),
                       revision=value["revision"], scope=context.scope)


def _speaking_record(service, context, source, checkpoint, identity, *, current=False):
    """The request's speaker is independent of the selected connection Persona.

    Historical reads use exact revisions; only new admission/transmit compares
    current authority. No request payload can supply a substitute Persona/role.
    """
    if type(identity) is not dict or set(identity) != {"persona_ref", "persona_name", "role_ref"}:
        raise ContractError("routing_speaking_identity_invalid")
    persona_ref = _entity_ref(context, identity["persona_ref"], EntityKind.PERSONA)
    role_ref = _entity_ref(context, identity["role_ref"], EntityKind.AGENT_ROLE)
    if str(persona_ref.entity_id) != checkpoint.get("persona_id") or role_ref != source.role:
        raise ContractError("routing_speaking_identity_invalid")
    records = []
    for reference in (persona_ref, role_ref):
        record = service.repository.get_revision(context=context, kind=reference.kind,
            entity_id=reference.entity_id, revision=reference.revision)
        if (record is None or record.ref() != reference or record.header.owner_user_uuid != context.user_uuid
                or record.status != "active"):
            raise ContractError("routing_speaking_identity_invalid")
        if current and service._get(context, reference.kind, reference.entity_id).ref() != reference:
            raise ContractError("routing_speaking_identity_changed")
        records.append(record)
    persona, role = records
    name = checkpoint.get("persona_name") or persona.display_name
    if identity["persona_name"] != name or type(name) is not str:
        raise ContractError("routing_speaking_identity_invalid")
    return persona, role


def _preview_record(service, context, reference):
    reference = _snapshot(context, reference)
    saved = service._json(context, reference)
    keys = {"version", "scope", "user_uuid", "source_task", "source_checkpoint",
            "source_request_sha256", "request", "decision", "selection_sha256"}
    if saved.get("version") == PREVIEW_VERSION:
        keys.add("speaking_identity")
    if (set(saved) != keys or saved["version"] not in {PREVIEW_VERSION, _LEGACY_PREVIEW_VERSION}
            or saved["scope"] != c.primitive(context.scope)
            or saved["user_uuid"] != str(context.user_uuid)):
        raise ContractError("routing_preview_invalid")
    source_ref = _entity_ref(context, saved["source_task"], EntityKind.TASK)
    source = service.repository.get_revision(context=context, kind=EntityKind.TASK,
        entity_id=source_ref.entity_id, revision=source_ref.revision)
    if (source is None or source.ref() != source_ref or source.header.owner_user_uuid != context.user_uuid
            or c.primitive(source.checkpoint) != saved["source_checkpoint"]):
        raise ContractError("routing_source_invalid")
    checkpoint = service._json(context, source.checkpoint)
    decision, request = saved["decision"], saved["request"]
    if (type(decision) is not dict or type(request) is not dict
            or decision.get("decision_sha256") != digest({key: value for key, value in decision.items() if key != "decision_sha256"})
            or saved["selection_sha256"] != selection_fingerprint(decision)
            or request.get("mode") != "shadow" or decision.get("mode") != "shadow"
            or decision.get("workspace_id") != context.scope.workspace_id or decision.get("user_uuid") != str(context.user_uuid)
            or checkpoint.get("source") != "real_model_task" or checkpoint.get("request_sha256") != saved["source_request_sha256"]
            or checkpoint.get("model_id") != request.get("current_model_id")
            or checkpoint.get("spec", {}).get("rubric_key") != request.get("task_class")
            or request.get("task_class") != decision.get("task_class")
            or request.get("candidate_model_ids") != [row.get("model_id") for row in decision.get("candidates", [])]
            or decision.get("legacy_model_id") != request.get("current_model_id")
            or decision.get("constraints") != {key: request.get(key) for key in ("max_cost_usd", "max_latency_ms")}):
        raise ContractError("routing_preview_invalid")
    if saved["version"] == PREVIEW_VERSION:
        _speaking_record(service, context, source, checkpoint, saved["speaking_identity"])
    return reference, saved, source, checkpoint


def record_preview(authorized, service, task, checkpoint, request, decision):
    context = _gate(authorized, "shadow")
    persona = service._get(context, EntityKind.PERSONA, checkpoint.get("persona_id"))
    speaking = {"persona_ref": c.primitive(persona.ref()),
        "persona_name": checkpoint.get("persona_name") or persona.display_name, "role_ref": c.primitive(task.role)}
    _speaking_record(service, context, task, checkpoint, speaking, current=True)
    saved = {"version": PREVIEW_VERSION, "scope": c.primitive(context.scope), "user_uuid": str(context.user_uuid),
        "source_task": c.primitive(task.ref()), "source_checkpoint": c.primitive(task.checkpoint),
        "source_request_sha256": checkpoint["request_sha256"], "request": request,
        "decision": decision, "selection_sha256": selection_fingerprint(decision), "speaking_identity": speaking}
    reference = service._put(context, saved)
    return {"preview_ref": c.primitive(reference), "source_revision": task.header.revision,
        "source_request_sha256": checkpoint["request_sha256"], "selection_sha256": saved["selection_sha256"],
        "requires_explicit_apply": True, "creates_new_task": True,
        "preview_version": PREVIEW_VERSION, "speaking_identity": speaking}


def _fresh_choice(authorized, service, saved, *, quote):
    context = _gate(authorized, "active")
    if saved["version"] != PREVIEW_VERSION:
        raise ContractError("routing_fresh_identity_preview_required")
    source = service._get(context, EntityKind.TASK, saved["source_task"]["entity_id"])
    if c.primitive(source.ref()) != saved["source_task"] or c.primitive(source.checkpoint) != saved["source_checkpoint"]:
        raise ContractError("routing_source_changed")
    _speaking_record(service, context, source, service._json(context, source.checkpoint), saved["speaking_identity"], current=True)
    fresh = select(authorized, service, {**saved["request"], "mode": "active"}, quote=quote)
    if (fresh["status"] != "selected" or not fresh["effective_model_id"]
            or selection_fingerprint(fresh) != saved["selection_sha256"]):
        raise ContractError("routing_preview_changed")
    return fresh


@dataclass(frozen=True, kw_only=True)
class RoutedTaskPacket:
    """Server-issued routing link supplied to normal ModelService ingress."""
    preview_ref: c.SnapshotRef
    decision_ref: c.SnapshotRef
    task_id: UUID
    version: str = APPLIED_VERSION

    def wire(self):
        return {"version": self.version, "preview_ref": c.primitive(self.preview_ref),
                "decision_ref": c.primitive(self.decision_ref), "task_id": str(self.task_id)}


def _packet(service, context, value):
    from .model_service import _uuid
    if isinstance(value, RoutedTaskPacket):
        packet = value
    else:
        if (type(value) is not dict or set(value) != {"version", "preview_ref", "decision_ref", "task_id"}
                or value.get("version") not in {APPLIED_VERSION, _LEGACY_APPLIED_VERSION}):
            raise ContractError("routing_packet_invalid")
        packet = RoutedTaskPacket(preview_ref=_snapshot(context, value["preview_ref"]),
            decision_ref=_snapshot(context, value["decision_ref"]), task_id=_uuid(value["task_id"]), version=value["version"])
    _, saved, source, checkpoint = _preview_record(service, context, packet.preview_ref)
    if (packet.version not in {APPLIED_VERSION, _LEGACY_APPLIED_VERSION}
            or (packet.version == APPLIED_VERSION) != (saved["version"] == PREVIEW_VERSION)):
        raise ContractError("routing_packet_invalid")
    proof = service._json(context, _snapshot(context, packet.decision_ref))
    expected = {"version": packet.version, "preview_ref": c.primitive(packet.preview_ref),
                "task_id": str(packet.task_id), "selection_sha256": saved["selection_sha256"],
                "selected_model_id": saved["decision"]["selected_model_id"], "permission_granted": False}
    if proof != expected or saved["decision"]["status"] != "selected" or not proof["selected_model_id"]:
        raise ContractError("routing_packet_invalid")
    return packet, saved, source, checkpoint


def prepare_apply(authorized, service, source_task_id, payload, expected_revision, idempotency_key, *, quote):
    from .model_service import _id, _key
    if type(payload) is not dict or set(payload) != {"preview_ref"}:
        raise ContractError("routing_explicit_preview_required")
    context = _gate(authorized, "active")
    reference, saved, source, checkpoint = _preview_record(service, context, payload["preview_ref"])
    if str(source.header.entity_id) != str(source_task_id) or type(expected_revision) is not int or expected_revision != source.header.revision:
        raise ContractError("routing_source_revision_conflict")
    # Full caller key is hashed before the common 120-character boundary.
    task_key = "routing-applied-" + _key(idempotency_key)
    task_id = _id(context, "model-task:" + _key(task_key))
    existing = service.repository.get(context=context, kind=EntityKind.TASK, entity_id=task_id)
    if existing is not None:
        old = service._json(context, existing.checkpoint)
        packet, recorded, _, _ = _packet(service, context, old.get("routing"))
        if packet.task_id != task_id or packet.preview_ref != reference:
            raise ContractError("routing_apply_idempotency_conflict")
        # Replaying a saved terminal receipt does not re-rank or re-send it.
        if existing.status not in {"planned", "ready"} or old.get("receipt"):
            return packet, recorded, checkpoint, task_key, existing
    _fresh_choice(authorized, service, saved, quote=quote)
    proof = service._put(context, {"version": APPLIED_VERSION, "preview_ref": c.primitive(reference),
        "task_id": str(task_id), "selection_sha256": saved["selection_sha256"],
        "selected_model_id": saved["decision"]["selected_model_id"], "permission_granted": False})
    packet = RoutedTaskPacket(preview_ref=reference, decision_ref=proof, task_id=task_id)
    return packet, saved, checkpoint, task_key, None


def validate_constructor(service, context, packet, *, model_id, spec, conversation_id, message_id, task_id):
    if not isinstance(packet, RoutedTaskPacket):
        raise ContractError("routing_server_packet_required")
    packet, saved, _, source = _packet(service, context, packet)
    if (packet.task_id != task_id or str(model_id) != saved["decision"]["selected_model_id"] or spec != source["spec"]
            or conversation_id != source.get("conversation_id") or message_id != source.get("message_id")):
        raise ContractError("routing_request_mismatch")
    from .mechanism_domains import _quote
    authorized = getattr(service, "mechanism_authorized", None)
    if not isinstance(authorized, dict) or authorized.get("context") != context:
        raise ContractError("routing_context_required")
    _fresh_choice(authorized, service, saved, quote=_quote)
    return packet.wire()


def speaking_assignment(service, context, packet):
    """Private constructor hook, resolved solely from the issued source packet."""
    if not isinstance(packet, RoutedTaskPacket):
        raise ContractError("routing_server_packet_required")
    _, saved, source, checkpoint = _packet(service, context, packet)
    if saved["version"] != PREVIEW_VERSION:
        raise ContractError("routing_fresh_identity_preview_required")
    identity = saved["speaking_identity"]
    persona, role = _speaking_record(service, context, source, checkpoint, identity, current=True)
    return persona, role, identity


def validate_assignment(service, context, task, checkpoint):
    """Read-only immutable speaker/executor binding, including receipt replay."""
    packet, saved, source, original = _packet(service, context, checkpoint.get("routing"))
    if packet.task_id != task.header.entity_id:
        raise ContractError("routing_request_mismatch")
    if saved["version"] == PREVIEW_VERSION:
        identity = saved["speaking_identity"]
        selected = next((row for row in saved["decision"]["candidates"]
                         if row["model_id"] == saved["decision"]["selected_model_id"]), {})
        if (checkpoint.get("speaking_identity") != identity
                or checkpoint.get("persona_id") != identity["persona_ref"]["entity_id"]
                or checkpoint.get("persona_name") != identity["persona_name"]
                or c.primitive(task.role) != identity["role_ref"]
                or checkpoint.get("executor_persona_id") != selected.get("persona_id")):
            raise ContractError("routing_speaking_assignment_changed")
    return packet, saved, source, original


def validate_execution(service, context, task, checkpoint):
    packet, saved, _, source = validate_assignment(service, context, task, checkpoint)
    if (packet.task_id != task.header.entity_id or checkpoint.get("model_id") != saved["decision"]["selected_model_id"]
            or checkpoint.get("spec") != source["spec"] or checkpoint.get("conversation_id") != source.get("conversation_id")
            or checkpoint.get("message_id") != source.get("message_id")):
        raise ContractError("routing_request_mismatch")
    from .mechanism_domains import _quote
    authorized = getattr(service, "mechanism_authorized", None)
    if not isinstance(authorized, dict) or authorized.get("context") != context:
        raise ContractError("routing_context_required")
    _fresh_choice(authorized, service, saved, quote=_quote)


def actual_choice(service, context, task, checkpoint):
    """Historical linkage is immutable; current flags never rewrite its origin."""
    chosen = str(checkpoint.get("model_id") or "")
    if not checkpoint.get("routing"):
        return {"model_id": chosen, "decided_by": "request", "routing_applied": False}
    packet, saved, _, source = validate_assignment(service, context, task, checkpoint)
    if (packet.task_id != task.header.entity_id or chosen != saved["decision"]["selected_model_id"]
            or checkpoint.get("spec") != source["spec"]):
        raise ContractError("routing_request_mismatch")
    receipt = service._json(context, checkpoint["receipt"]) if checkpoint.get("receipt") else {}
    if receipt and (receipt.get("task_id") != str(task.header.entity_id) or receipt.get("request_sha256") != checkpoint.get("request_sha256")):
        raise ContractError("routing_receipt_mismatch")
    from .model_service import receipt_provenance
    return {"model_id": chosen, "decided_by": "router_v2", "routing_applied": True,
        "source_task_id": saved["source_task"]["entity_id"], "source_revision": saved["source_task"]["revision"],
        "preview_ref": c.primitive(packet.preview_ref), "decision_ref": c.primitive(packet.decision_ref),
        "selection_sha256": saved["selection_sha256"], "policy_version": saved["decision"]["policy_version"],
        "actual_model": receipt.get("actual_model"), "executor": receipt.get("executor"),
        "speaking_identity": saved.get("speaking_identity"),
        "speaking_persona_id": checkpoint.get("persona_id"), "executor_persona_id": checkpoint.get("executor_persona_id"),
        "persona_preserved": True if saved["version"] == PREVIEW_VERSION else None,
        "external_call": receipt.get("external_call"), "execution_observed": bool(receipt),
        **(receipt_provenance(receipt) if receipt else {"synthetic": None, "source_kind": None})}
