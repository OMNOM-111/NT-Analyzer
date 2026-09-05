"""Explicit human handoff of verified application facts to another Persona.

This is a bounded, typed dependency through the existing model worker and SF
Chat. It transfers allowlisted facts, not raw files, tools, execution authority,
private Memory or an autonomous delegation loop. extract_facts measures faithful
transfer only: it cannot establish strategy correctness or inspect chart pixels.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from uuid import UUID

from . import contracts as c
from .model_evaluation import digest, json_bytes, prepare
from .states import ContractError, EntityKind


LIMITATION = "Проверяется только точность передачи фактов; это не анализ изображения, стратегии или прибыльности."
_KIND = "verified_application_fact_handoff"


@dataclass(frozen=True)
class SealedHandoff:
    """Internal immutable constructor argument; never decoded from an HTTP body."""

    parent: c.EntityRef
    correlation_id: UUID
    payload: bytes

    def wire(self):
        return json.loads(self.payload)


def _number(value):
    return type(value) in {int, float} and math.isfinite(value)


def _seal(service, context, task_id, target_model_id):
    if context.actor.kind != c.ActorKind.HUMAN:
        raise ContractError("handoff_human_required")
    service._access(context, "read")
    parent = service._get(context, EntityKind.TASK, task_id)
    checkpoint = service._json(context, parent.checkpoint)
    if checkpoint.get("handoff") or parent.dependencies:
        raise ContractError("handoff_recursive_denied")
    if (parent.status != "succeeded" or checkpoint.get("source") != "real_model_task"
            or checkpoint.get("synthetic") is not False or not checkpoint.get("application_request")):
        raise ContractError("handoff_verified_source_required")
    detail = service.task_detail(context=context, task_id=parent.header.entity_id)
    proof = detail.get("application_evaluation")
    if proof is None:
        raise ContractError("handoff_verified_source_required")
    # Reuse the existing strict PNG/report/source-link validation and scalar
    # sanitizer. This private read helper neither publishes nor admits Social.
    from .social_publication import SocialPublicationService
    outcome, public = SocialPublicationService(service.repository)._outcome(context, proof["outcome_id"])
    target = service._get(context, EntityKind.MODEL, target_model_id)
    profile = service._json(context, target.profile)
    persona = service._get(context, EntityKind.PERSONA, profile["persona_id"])
    account = service._get(context, EntityKind.PROVIDER_ACCOUNT, profile["provider_account_id"])
    if target.status != "active" or persona.status != "active" or account.status != "active":
        raise ContractError("handoff_target_inactive")
    if str(target.header.entity_id) == checkpoint["model_id"] or str(persona.header.entity_id) == checkpoint["persona_id"]:
        raise ContractError("handoff_different_persona_required")
    if not checkpoint.get("conversation_id") or not checkpoint.get("message_id"):
        raise ContractError("handoff_source_chat_required")
    request, verification = checkpoint["application_request"], proof["verification"]
    spec = request["spec"]
    facts = {"source_kind": proof["source_kind"], "source_id": proof["source_id"],
        "source_sha256": verification["source_sha256"], "instrument": spec["instrument"]}
    if request["kind"] == "backtest":
        facts["strategy"] = spec["class_name"]
        aliases = {"Trades": "trades", "Net P&L (after commission)": "net_profit_after_commission",
            "Net P&L (before commission)": "net_profit_before_commission",
            "Profit factor (after commission)": "profit_factor_after_commission",
            "Profit factor (before commission)": "profit_factor_before_commission"}
        for key, value in public["metrics"].items():
            if key in aliases and _number(value):
                facts[aliases[key]] = str(value)
    else:
        capture = verification.get("capture") or {}
        rendered, total = capture.get("rendered_bar_count"), capture.get("total_bar_count")
        if (capture.get("instrument") != spec["instrument"] or capture.get("timeframe") != spec["timeframe"]
                or type(rendered) is not int or type(total) is not int or not 1 <= rendered <= total <= 10_000_000):
            raise ContractError("handoff_source_capture_required")
        facts.update(timeframe=spec["timeframe"], rendered_bar_count=str(rendered), total_bar_count=str(total))
    # The same bounded grammar rejects unsafe/multiline/oversized scalar data.
    prepared = prepare("extract_facts", "\n".join(key + "=" + value for key, value in facts.items()))
    packet = {"schema_version": 1, "kind": _KIND, "parent_task": c.primitive(parent.ref()),
        "correlation_id": str(parent.header.correlation_id), "source_model_id": checkpoint["model_id"],
        "source_persona_id": checkpoint["persona_id"], "target_model_id": str(target.header.entity_id),
        "target_persona_id": str(persona.header.entity_id), "source_outcome_id": proof["outcome_id"],
        "source_evaluation_id": proof["evaluation_id"], "source_proof_sha256": outcome.verification.sha256,
        "artifact_hashes": sorted(ref.sha256 for ref in outcome.evidence),
        "conversation_id": checkpoint["conversation_id"], "source_message_id": checkpoint["message_id"],
        "facts": prepared["input"], "facts_sha256": digest(prepared["input"]),
        "source_kind": proof["source_kind"], "synthetic": False, "limitation": LIMITATION}
    return SealedHandoff(parent.ref(), parent.header.correlation_id, json_bytes(packet))


def validate_constructor(service, context, value, *, model_id, spec, conversation_id):
    if not isinstance(value, SealedHandoff):
        raise ContractError("handoff_sealed_source_required")
    fresh = _seal(service, context, value.parent.entity_id, model_id)
    if value != fresh:
        raise ContractError("handoff_source_changed")
    packet = value.wire()
    if (conversation_id != packet["conversation_id"] or spec != prepare("extract_facts",
            "\n".join(key + "=" + item for key, item in packet["facts"].items()))):
        raise ContractError("handoff_request_mismatch")
    return packet


def validate_execution(service, context, task, checkpoint):
    """Fresh immutable lineage check immediately before any provider transmit."""
    packet = checkpoint.get("handoff")
    if not isinstance(packet, dict) or packet.get("kind") != _KIND:
        raise ContractError("handoff_request_mismatch")
    try:
        fresh = _seal(service, context, packet["parent_task"]["entity_id"], checkpoint["model_id"])
    except ContractError as exc:
        if exc.code in {"handoff_target_inactive", "handoff_different_persona_required", "handoff_recursive_denied"}:
            raise
        raise ContractError("handoff_source_unavailable") from None
    except (KeyError, ValueError, TypeError):
        raise ContractError("handoff_request_mismatch") from None
    if (packet != fresh.wire() or task.dependencies != (fresh.parent,)
            or task.header.correlation_id != fresh.correlation_id):
        raise ContractError("handoff_source_changed")
    validate_constructor(service, context, fresh, model_id=checkpoint["model_id"],
                         spec=checkpoint["spec"], conversation_id=checkpoint["conversation_id"])
    scope = service.chat_scope
    if (not isinstance(scope, dict) or scope.get("user_uuid") != str(context.user_uuid)
            or scope.get("workspace_id") != context.scope.workspace_id):
        raise ContractError("handoff_chat_scope_required")
    child_message = checkpoint.get("message_id")
    if not child_message or child_message == packet["source_message_id"]:
        raise ContractError("handoff_request_mismatch")
    _source_message({"context": context, "chat_scope": scope}, packet, child_message_id=child_message)


def _source_message(authorized, packet, *, child_message_id=None):
    from ..ai_lab import chief_agent
    cid = packet["conversation_id"]
    if chief_agent._safe_conversation_id(cid) != cid:
        raise ContractError("handoff_source_chat_required")
    try:
        rows = chief_agent.read_jsonl(chief_agent._conversation_file(cid, scope=authorized["chat_scope"]))
    except OSError:
        raise ContractError("handoff_chat_unavailable") from None
    wanted = {packet["source_message_id"]} | ({child_message_id} if child_message_id else set())
    found = {row.get("message_id") for row in rows if row.get("role") == "user"
             and row.get("user_uuid") == str(authorized["context"].user_uuid)
             and row.get("workspace_id") == authorized["context"].scope.workspace_id}
    if not wanted <= found:
        raise ContractError("handoff_source_message_required")


def start(authorized, service, task_id, target_model_id, idempotency_key):
    """Human action -> existing SF Chat ingress -> one dependent model task."""
    from ..ai_lab import chief_agent
    from . import model_chat
    from .model_service import _id, _key
    if authorized.get("read_only") or authorized["context"].actor.kind != c.ActorKind.HUMAN:
        raise ContractError("handoff_human_required")
    authorized["admit"]()
    context = authorized["context"]
    service._access(context, "task")
    seal = _seal(service, context, task_id, target_model_id)
    packet = seal.wire()
    _source_message(authorized, packet)
    # Chief replays an existing acknowledgment without invoking its callback.
    # Reject changed target/source/body before that short circuit, including a
    # crash that persisted only the Intent or the user ingress message.
    child_id = _id(context, "model-task:" + _key(idempotency_key))
    for kind, identity in ((EntityKind.TASK, child_id), (EntityKind.INTENT, _id(context, f"intent:{child_id}"))):
        existing = service.repository.get(context=context, kind=kind, entity_id=identity)
        if existing is not None:
            ref = existing.checkpoint if kind == EntityKind.TASK else existing.goal
            if service._json(context, ref).get("handoff") != packet:
                raise ContractError("model_task_idempotency_conflict")
    target = service.model_detail(context=context, model_id=target_model_id)
    source = service.task_detail(context=context, task_id=task_id)
    text = ("Передать проверенные факты результата «" + source["title"] + "» агенту «" + target["title"]
            + "» (задача " + source["id"] + ", подключение " + target["id"] + "). " + LIMITATION)
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(packet["conversation_id"], scope=authorized["chat_scope"]))
    request_key = chief_agent._agent_world_request_key(idempotency_key)
    previous = next((row for row in rows if row.get("request_id") == request_key and row.get("role") == "user"), None)
    if previous is not None and previous.get("content") != text:
        raise ContractError("model_task_idempotency_conflict")
    created = {}
    def execute(message_id):
        detail = service.start_task(context=context, model_id=target_model_id,
            payload={"rubric_key": "extract_facts", "input_text": "\n".join(key + "=" + value for key, value in packet["facts"].items())},
            idempotency_key=idempotency_key, conversation_id=packet["conversation_id"], message_id=message_id, _handoff=seal)
        created.update(detail)
        envelope = model_chat.envelope(authorized, detail, request_id=idempotency_key, pending=True)
        envelope["text"] = ("Передача проверенных фактов принята: " + source["lead"]["display_name"] + " → "
            + detail["lead"]["display_name"] + ". Исходная задача: " + source["id"] + ". " + LIMITATION
            + " Ответ появится в этом же диалоге; новое исполнение приложения не запускается.")
        return envelope
    reply = chief_agent.run_agent_world_live_request(message=text, request_id=idempotency_key,
        conversation_id=packet["conversation_id"], scope=authorized["chat_scope"], execute=execute,
        domain_request=True, include_message_identity=True)
    if not created:
        action = next((row for row in reply.get("actions", []) if row.get("task_id")), {})
        if action.get("task_id") != str(child_id):
            raise ContractError("handoff_ingress_mismatch")
        created = service.task_detail(context=context, task_id=child_id)
    return created
