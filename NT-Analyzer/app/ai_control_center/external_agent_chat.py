"""External-agent receipts delivered into existing scoped SF Chat, never Model evidence."""
from . import model_chat, result_handoff
from .model_evaluation import digest
from .states import ContractError, EntityKind

SOURCE = "external_agent_task_v1"


def bind(authorized, task_id, display_name, input_text):
    from ..ai_lab import chief_agent
    authorized["admit"]()
    key = "external.chat." + str(task_id)
    cid = model_chat._conversation(authorized, key, "Внешний агент · " + display_name)
    with chief_agent._LOCK:
        path = chief_agent._conversation_file(cid, scope=authorized["chat_scope"])
        rows = chief_agent.read_jsonl(path)
        row = next((row for row in rows if row.get("request_id") == key and row.get("role") == "user"), None)
        if row is None:
            row = chief_agent._append_conversation("user", "Диагностика внешнего агента «" + display_name + "»: " + input_text,
                source="app", request_id=key, path=path, scope=authorized["chat_scope"])
        chief_agent._touch_conversation(cid, scope=authorized["chat_scope"])
    return {"conversation_id": cid, "message_id": row["message_id"]}


def envelope(authorized, service, task_id):
    task = service.records._get(service.context, EntityKind.TASK, task_id)
    cp = service.records._json(service.context, task.checkpoint)
    if cp.get("source") != SOURCE or not cp.get("conversation_id") or not cp.get("message_id"):
        raise ContractError("external_agent_chat_binding_missing")
    result_handoff._source_message(authorized, {"conversation_id": cp["conversation_id"], "source_message_id": cp["message_id"]})
    detail = service.task_detail(task_id)
    dto, proof = detail["task"], detail["evaluation"]
    state = dto.get("display_status") or dto["status"]
    text = ("Внешний агент · SYNTHETIC диагностика, внешний сервис не вызывался.\n" if cp["synthetic"] else "Внешний агент.\n")
    text += detail["result_text"] or "Результат не получен."
    text += "\n" + str(dto.get("display_status_label") or state)
    text += "\nМодель: unknown / externally managed. Это не Model Performance и не оценка профессионального качества."
    identity = digest({"task": str(task_id), "checkpoint": cp, "human_review": detail["human_review"]})
    return {"scope": authorized["chat_scope"], "conversation_id": cp["conversation_id"],
        "request_id": "external.result." + identity, "source_kind": SOURCE,
        "task_id": str(task_id), "status": state, "synthetic": cp["synthetic"], "text": text,
        "actual_model": None, "model_id": None, "provider": "external_agent", "external_call": dto["external_call"],
        "agent_name": dto["lead"]["display_name"], "task_class": "json_arithmetic",
        "verification": {"passed": proof.get("passed") is True, "synthetic": cp["synthetic"], "quality_claim": False},
        "contribution_id": cp.get("contribution_id"), "outcome_id": cp.get("outcome_id"), "evaluation_id": cp.get("evaluation_id"),
        "attachments": detail["artifacts"]}


def validate(authorized, supplied):
    from . import domain_gateway
    service = domain_gateway.external_agents(authorized)
    expected = envelope(authorized, service, supplied.get("task_id"))
    if supplied != expected:
        raise ContractError("external_agent_chat_evidence_changed")
    return expected


def deliver(authorized, service, task_id):
    from ..ai_lab import chief_agent
    cp = service.records._json(service.context, service.records._get(service.context, EntityKind.TASK, task_id).checkpoint)
    if not cp.get("conversation_id"):
        return {"status": "historical_unbound"}  # No rewrite or invented conversation for old tasks.
    result = chief_agent.report_agent_world_live_update(envelope(authorized, service, task_id), history_delivery=True)
    if result.get("ok") is not True:
        raise ContractError("external_agent_chat_delivery_unconfirmed")
    return result
