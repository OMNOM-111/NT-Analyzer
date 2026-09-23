"""Same-store SF Chat ingress and replayable model/evidence projections."""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid5

from ..ai_lab import chief_agent
from .model_service import receipt_provenance
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
    provenance = receipt_provenance({} if pending else detail)
    evaluation = detail.get("evaluation") or {}
    application = task.get("application_result") or {}
    verified = not pending and task.get("status") == "succeeded" and evaluation.get("passed") is True
    if task.get("application_request"):
        verified = verified and application.get("verified") is True
    human_review = task.get("human_review") or {"status": "not_required", "quality_claim": False}
    display_status = "queued" if pending else task.get("display_status") or ("result_received" if verified else "blocked")
    result_text = detail.get("result_text") or ""
    response_only = task.get("task_class") == "assistant_response"
    text = ("Задача модели принята существующим worker. Результат и проверка появятся здесь." if pending else
            (result_text + "\n\nНезависимая проверка: " + ("PASS" if verified else "FAIL / требуется проверка") +
             " · " + str(task.get("task_class") or "") +
             ("\nПричина: " + str(task["error_code"]) if task.get("error_code") else "")))
    if response_only:
        text = ("Задание помощнику принято. Полученный ответ будет ожидать вашей проверки." if pending else
                result_text + "\n\n" + ("Ответ получен; проверена только доставка текста." if verified else
                "Ответ не получен или доставка не подтверждена.") +
                " Содержание и профессиональное качество автоматически не оценены.")
    if not pending and task.get("application_request") and evaluation.get("passed") is False:
        text += "\nСпецификация модели не совпала с поручением. Команда приложению не отправлена; бэктест или снимок не выполнен."
    if provenance["synthetic"]:
        text = ("Локальный тестовый исполнитель · synthetic. Внешняя модель не вызывалась; "
                "это проверка механизма, а не качества подключённой модели.\n\n" + text)
    if not pending and human_review.get("status") in {"pending", "accepted", "rejected", "blocked"}:
        text += "\nПроверка владельцем: " + {"pending": "ожидается", "accepted": "результат принят",
            "rejected": "результат отклонён", "blocked": "недоступна до устранения блокировки"}[human_review["status"]] + "."
    deputy = task.get("conversation_role") == "deputy"
    if deputy:
        text = ("Принял поручение. Готовлю результат." if pending else
                result_text if verified else "Не удалось выполнить поручение. Причину можно посмотреть в задаче.")
    actual = None if pending else detail.get("actual_model")
    provider = "local_test_executor" if provenance["synthetic"] else task.get("provider")
    return {"scope": authorized["chat_scope"], "conversation_id": task["conversation_id"], "request_id": request_id,
            **provenance, "task_id": task["id"], "task_class": task.get("task_class"),
            "status": display_status, "display_status": display_status, "ledger_status": task.get("ledger_status", task.get("status")),
            "human_review": human_review, "result_received": task.get("result_received") is True,
            "verification_status": task.get("verification_status"), "text": text,
            "verification_scope": "transport_only" if response_only else "task_contract",
            "agent_id": "vitek" if deputy else task.get("persona_id"), "agent_name": "Заместитель" if deputy else task.get("lead", {}).get("display_name") or task.get("model_label"),
            "actual_model": actual, "provider": provider, "configured_provider": task.get("provider"),
            "executor": None if pending else detail.get("executor"),
            "external_call": None if pending else detail.get("external_call"),
            "verification": {"passed": verified, "evaluation_id": task.get("application_evaluation_id") or task.get("evaluation_id"),
                             "plan_evaluation_id": task.get("evaluation_id"), "checks": evaluation.get("checks", []),
                             "application": application.get("evaluation"), "synthetic": provenance["synthetic"],
                             "scope": "transport_only" if response_only else "task_contract",
                             "semantic_verified": False if response_only else evaluation.get("semantic_verified"),
                             "quality_claim": False},
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
            "participation_chain": [] if not actual else [{"agent_id": task.get("persona_id"),
                "agent_name": task.get("lead", {}).get("display_name") or task.get("model_label"),
                "role": "test_executor_response" if provenance["synthetic"] else "model_response",
                "model": actual, "actual_model": actual, "provider": provider,
                "synthetic": provenance["synthetic"], "purpose": task.get("task_class")}]}


def start(authorized, service, model_id, payload, key, *, test=False, conversation_id=None, user_message=None, persona=None,
          model_selection=None, deputy=False):
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
        if persona is not None:
            kwargs["_persona"] = persona
        if model_selection is not None:
            kwargs["_model_selection"] = model_selection
        detail = service.test(**kwargs) if test else service.start_task(**kwargs, payload=payload, **({"_deputy": True} if deputy else {}))
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
    identity = {"status": task["status"], "evaluation": task.get("evaluation_id"),
        "response": detail.get("result_text"), "error": task.get("error_code"),
        "human_review": task.get("human_review"), "display_status": task.get("display_status")}
    if receipt_provenance(detail)["synthetic"]:
        # Do not replay a legacy mislabelled message as though it had the new
        # truthful origin. This does not edit old chat rows or enqueue a run.
        identity["provenance"] = "synthetic_model_response_v1"
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
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
    event_record = task
    review = detail.get("human_review") or {}
    if review.get("evaluation_id") and review.get("status") in {"accepted", "rejected"}:
        # Review does not rewrite the task. Acknowledge its real immutable
        # Evaluation event, not the already-consumed task event (or a made-up
        # hash that the repository inbox would correctly refuse to store).
        event_record = service._get(context, EntityKind.EVALUATION, review["evaluation_id"])
    elif detail.get("synthetic") is True and detail.get("evaluation_id"):
        # An old task event may already have delivered a mislabelled real
        # result. The actual model-evaluation event is a distinct, scoped
        # replay anchor for a truthful synthetic projection; no history edit.
        event_record = service._get(context, EntityKind.EVALUATION, detail["evaluation_id"])
    return {"task_id": str(task.header.entity_id),
            "event_id": str(uuid5(event_record.header.entity_id, f"revision:{event_record.header.revision}")),
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


def validate_synthetic_envelope(authorized, value):
    """Chief-only receipt guard, using the same read-only auth as history.

    This is not a Preview or arbitrary synthetic-message bypass. The exact
    saved completion and original user message must agree with every field.
    """
    from .test_executor import EXECUTOR
    if (not isinstance(value, dict) or value.get("source_kind") != "synthetic_model_response"
            or value.get("synthetic") is not True or value.get("external_call") is not False
            or (value.get("executor") != EXECUTOR and value.get("actual_model") != EXECUTOR)):
        raise ContractError("model_delivery_synthetic_provenance_invalid")
    return validate_history_envelope(authorized, value)


def deliver(authorized, service, *, task_id, event_id, checkpoint_sha256, events, delivery_job=None):
    """Retry only SF Chat delivery of a sealed result via the existing inbox."""
    saved = completion(authorized, service, task_id)
    if saved is None or saved["event_id"] != event_id or saved["checkpoint_sha256"] != checkpoint_sha256:
        return {"ok": True, "status": "superseded", "task_id": str(task_id)}
    context, identity = authorized["context"], UUID(event_id)
    if service.repository.events.is_acknowledged(context=context, consumer=DELIVERY_CONSUMER, event_id=identity):
        return {"ok": True, "status": "delivered", "task_id": str(task_id), "replayed": True}
    authorized["admit"]()
    result = chief_agent.report_agent_world_live_update(saved["envelope"], history_delivery=True, _delivery_job=delivery_job)
    if result.get("ok") is not True:
        raise ContractError("model_delivery_unconfirmed")
    authorized["admit"]()
    acknowledged = events.acknowledge(context=context, consumer=DELIVERY_CONSUMER, event_id=identity)
    if acknowledged is not True and not service.repository.events.is_acknowledged(
            context=context, consumer=DELIVERY_CONSUMER, event_id=identity):
        raise ContractError("model_delivery_unconfirmed")
    return {"ok": True, "status": "delivered", "task_id": str(task_id),
            "replayed": result.get("idempotent_replay") is True}


def try_persona(*, message, authorized, service, persona_id, persona_revision,
                conversation_id, request_id, user_message, selected_model_id=None):
    """One selected, owned Persona -> one bound connection -> existing worker.

    A received free-text answer is never evidence of correctness or permission
    to use tools. Explicit application actions have already passed the normal
    application-chat adapter, not this text-only protocol.
    """
    from . import persona_identity
    context = authorized["context"]
    authorized["admit"]()
    persona = persona_identity._owned(service, context, persona_id)
    if type(persona_revision) is not int or persona.header.revision != persona_revision:
        raise ContractError("persona_selection_changed")
    model_id = persona_identity.select_model(service, context=context, persona_id=persona_id,
        selected_model_id=selected_model_id)
    diagnostic = re.fullmatch(r"(connection_exact|json_arithmetic|extract_facts)(?:\s*\n([\s\S]*))?", message, re.I)
    rubric = diagnostic[1].lower() if diagnostic else "assistant_response"
    if rubric == "connection_exact" and diagnostic[2]:
        raise ContractError("model_connection_input_not_allowed")
    payload = {} if rubric == "connection_exact" else {"rubric_key": rubric,
        "input_text": (diagnostic[2] or "") if diagnostic else message}
    selection = ({"mode": "explicit_override", "selected_model_id": model_id} if selected_model_id is not None
                 else {"mode": "shared_available", "selected_model_id": None}
                 if service._shared_target(context, model_id) is not None
                 else {"mode": "single_available", "selected_model_id": None})
    detail = start(authorized, service, model_id, payload, request_id,
        test=rubric == "connection_exact", conversation_id=conversation_id,
        user_message=user_message, persona=persona.ref(), model_selection=selection)
    return {"ok": True, "conversation_id": conversation_id,
            "reply": "Задание помощнику принято. Ответ появится в этой теме.",
            "task_id": detail["id"], "persona_id": persona_id,
            "actions": [{"name": "agent_world_model_response", "status": "queued", "task_id": detail["id"]}]}


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
