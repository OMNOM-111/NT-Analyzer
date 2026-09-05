"""Same-store SF Chat ingress and replayable model/evidence projections."""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid5

from ..ai_lab import chief_agent
from .states import ContractError, EntityKind


DELIVERY_CONSUMER = "agent_world.model.sf_chat.v1"


def _conversation(authorized, key, title):
    # Exact idempotent conversation, never a caller-provided foreign thread.
    identity = [str(authorized["context"].user_uuid), authorized["context"].scope.workspace_id, key]
    cid = "AW-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:28]
    chief_agent.create_conversation(title, conversation_id=cid, scope=authorized["chat_scope"])
    return cid


def envelope(authorized, detail, *, request_id, pending=False):
    task = detail.get("task") or detail
    evaluation = detail.get("evaluation") or {}
    application = task.get("application_result") or {}
    verified = not pending and task.get("status") == "succeeded" and evaluation.get("passed") is True
    if task.get("application_request"):
        verified = verified and application.get("verified") is True
    result_text = detail.get("result_text") or ""
    text = ("Задача модели принята существующим worker. Результат и независимая проверка появятся здесь." if pending else
            (result_text + "\n\nНезависимая проверка: " + ("PASS" if verified else "FAIL / требуется проверка") +
             " · " + str(task.get("task_class") or "") +
             ("\nПричина: " + str(task["error_code"]) if task.get("error_code") else "")))
    if not pending and task.get("application_request") and evaluation.get("passed") is False:
        text += "\nСпецификация модели не совпала с поручением. Команда приложению не отправлена; бэктест или снимок не выполнен."
    actual = detail.get("actual_model")
    return {"scope": authorized["chat_scope"], "conversation_id": task["conversation_id"], "request_id": request_id,
            "source_kind": "real_model_response", "synthetic": False, "task_id": task["id"],
            "status": "queued" if pending else "completed" if verified else "blocked", "text": text,
            "agent_id": task.get("persona_id"), "agent_name": task.get("lead", {}).get("display_name") or task.get("model_label"),
            "actual_model": actual, "provider": task.get("provider"),
            "verification": {"passed": verified, "evaluation_id": task.get("application_evaluation_id") or task.get("evaluation_id"),
                             "plan_evaluation_id": task.get("evaluation_id"), "checks": evaluation.get("checks", []),
                             "application": application.get("evaluation")},
            **{field: task.get(field) for field in ("intent_id", "model_id", "contribution_id", "execution_id", "outcome_id", "evaluation_id", "correlation_id")},
            "attachments": [{**artifact, "type": "image" if artifact.get("mime_type") in
                {"image/png", "image/jpeg", "image/webp", "image/svg+xml"} else "artifact",
                "caption": artifact.get("title") or "Артефакт задачи"} for artifact in detail.get("artifacts") or []],
            "source_job_id": task.get("source_job_id"), "command_id": task.get("command_id"), "report_url": task.get("report_url"),
            "plan_evaluation_id": task.get("evaluation_id"), "application_evaluation_id": task.get("application_evaluation_id"),
            "application_execution_id": application.get("execution_id"), "application_outcome_id": application.get("outcome_id"),
            "plan_execution_id": task.get("execution_id"), "plan_outcome_id": task.get("outcome_id"),
            "execution_id": application.get("execution_id") or task.get("execution_id"),
            "outcome_id": application.get("outcome_id") or task.get("outcome_id"),
            "evaluation_id": task.get("application_evaluation_id") or task.get("evaluation_id"),
            "participation_chain": [] if not actual else [{"agent_id": task.get("persona_id"), "agent_name": task.get("model_label"),
                "role": "model_response", "model": actual, "actual_model": actual, "provider": task.get("provider"), "purpose": task.get("task_class")}]}


def start(authorized, service, model_id, payload, key, *, test=False, conversation_id=None, user_message=None):
    if test and payload:
        raise ContractError("model_connection_input_not_allowed")
    model = service.model_detail(context=authorized["context"], model_id=model_id)
    title = "Проверка подключения" if test else "Задание модели"
    cid = conversation_id or _conversation(authorized, key, title + " · " + model["title"])
    text = user_message or (title + " «" + model["title"] + "»: " + ("connection_exact" if test else
                          str(payload.get("rubric_key", "json_arithmetic")) + "\n" + str(payload.get("input_text", ""))))
    created = {}
    def execute(message_id):
        kwargs = {"context": authorized["context"], "model_id": model_id, "idempotency_key": key,
                  "conversation_id": cid, "message_id": message_id}
        detail = service.test(**kwargs) if test else service.start_task(**kwargs, payload=payload)
        created.update(detail)
        return envelope(authorized, detail, request_id=key, pending=True)
    reply = chief_agent.run_agent_world_live_request(message=text, request_id=key, conversation_id=cid,
        scope=authorized["chat_scope"], execute=execute, domain_request=True, include_message_identity=True)
    if not created:
        action = next((item for item in reply.get("actions", []) if item.get("task_id")), {})
        created = service.task_detail(context=authorized["context"], task_id=action.get("task_id"))
    return created


def compare(authorized, service, payload, key):
    cid = _conversation(authorized, key, "Эксперимент · " + str(payload.get("title", "")))
    created = {}
    def execute(message_id):
        result = service.start_comparison(context=authorized["context"], payload=payload, idempotency_key=key,
                                           conversation_id=cid, message_id=message_id)
        created.update(result)
        first = result["results"][0]
        return envelope(authorized, first, request_id=key, pending=True)
    chief_agent.run_agent_world_live_request(message="Сравнить модели: " + str(payload.get("title", "")) + "\n" +
        str(payload.get("rubric_key", "json_arithmetic")) + "\n" + str(payload.get("input_text", "")),
        request_id=key, conversation_id=cid, scope=authorized["chat_scope"], execute=execute,
        domain_request=True, include_message_identity=True)
    if not created:
        created = next((row for row in service.experiments(context=authorized["context"])["items"]
                        if row["results"][0].get("conversation_id") == cid), None)
    return created


def _result_envelope(authorized, detail):
    task = detail.get("task") or detail
    if not task.get("conversation_id") or detail.get("stage") == "awaiting_application":
        return None
    signature = hashlib.sha256(json.dumps({"status": task["status"], "evaluation": task.get("evaluation_id"),
        "response": detail.get("result_text"), "error": task.get("error_code")}, sort_keys=True).encode()).hexdigest()
    return envelope(authorized, detail, request_id="model-result:" + task["id"] + ":" + signature)


def publish(authorized, detail):
    value = _result_envelope(authorized, detail)
    return chief_agent.report_agent_world_live_update(value) if value else {"published": False}


def completion(authorized, service, task_id):
    """Read one exact persisted completion; never finish or rerun a task."""
    authorized["admit"]()
    context = authorized["context"]
    detail = service.task_detail(context=context, task_id=task_id)
    task = service._get(context, EntityKind.TASK, task_id)
    # Review can be the sealed outcome of a rejected model response, not an
    # unfinished provider call. Report that failure through the same claimed
    # delivery path without approving, retrying or changing its review state.
    rejected_response = (task.status == "review" and detail.get("stage") == "provider_receipt"
                         and bool(detail.get("evaluation_id"))
                         and (detail.get("evaluation") or {}).get("passed") is False)
    if task.status not in {"succeeded", "failed", "cancelled"} and not rejected_response:
        # A failed admission/unknown transmit is a truthful blocked report,
        # not a completed response or an invitation to execute again.
        if task.status != "blocked" or not detail.get("error_code"):
            return None
    value = _result_envelope(authorized, detail)
    if value is None or not detail.get("message_id"):
        return None
    return {"task_id": str(task.header.entity_id),
            "event_id": str(uuid5(task.header.entity_id, f"revision:{task.header.revision}")),
            "checkpoint_sha256": task.checkpoint.sha256,
            "message_id": detail["message_id"], "envelope": value}


def validate_history_envelope(authorized, value):
    """Trusted Chief-only guard: history access is not a general write grant."""
    from . import domain_gateway
    service = domain_gateway.history_models(authorized)
    saved = completion(authorized, service, value.get("task_id"))
    if saved is None or saved["envelope"] != value:
        raise ContractError("model_delivery_evidence_mismatch")
    cid = value["conversation_id"]
    if chief_agent._safe_conversation_id(cid) != cid:
        raise ContractError("model_delivery_conversation_mismatch")
    rows = chief_agent.read_jsonl(chief_agent._conversation_file(cid, scope=authorized["chat_scope"]))
    if not any(row.get("message_id") == saved["message_id"] and row.get("role") == "user"
               and row.get("user_uuid") == str(authorized["context"].user_uuid)
               and row.get("workspace_id") == authorized["context"].scope.workspace_id for row in rows):
        raise ContractError("model_delivery_message_mismatch")
    return saved


def deliver(authorized, service, *, task_id, event_id, checkpoint_sha256, events):
    """Retry only SF Chat delivery of a sealed result via the existing inbox."""
    saved = completion(authorized, service, task_id)
    if saved is None or saved["event_id"] != event_id or saved["checkpoint_sha256"] != checkpoint_sha256:
        return {"ok": True, "status": "superseded", "task_id": str(task_id)}
    context, identity = authorized["context"], UUID(event_id)
    if service.repository.events.is_acknowledged(context=context, consumer=DELIVERY_CONSUMER, event_id=identity):
        return {"ok": True, "status": "delivered", "task_id": str(task_id), "replayed": True}
    authorized["admit"]()
    result = chief_agent.report_agent_world_live_update(saved["envelope"], history_delivery=True)
    if result.get("ok") is not True:
        raise ContractError("model_delivery_unconfirmed")
    authorized["admit"]()
    events.acknowledge(context=context, consumer=DELIVERY_CONSUMER, event_id=identity)
    return {"ok": True, "status": "delivered", "task_id": str(task_id),
            "replayed": result.get("idempotent_replay") is True}


def try_chat(message, *, scope, conversation_id, request_id, source):
    if source != "app":
        return None
    match = re.fullmatch(r"Модель\s+([0-9a-f-]{36})\s*:\s*(connection_exact|json_arithmetic|extract_facts)(?:\s*\n([\s\S]*))?", message, re.I)
    if not match:
        return None
    from . import domain_gateway
    authorized = domain_gateway.access(scope)
    service = domain_gateway.models(authorized)
    detail = start(authorized, service, match[1], {} if match[2] == "connection_exact" else
                   {"rubric_key": match[2], "input_text": match[3] or ""}, request_id,
                   test=match[2] == "connection_exact", conversation_id=conversation_id, user_message=message)
    return {"ok": True, "conversation_id": conversation_id, "reply": "Задание модели принято: " + detail["id"],
            "task_id": detail["id"], "actions": [{"name": "real_model_response", "status": "queued", "task_id": detail["id"]}]}
