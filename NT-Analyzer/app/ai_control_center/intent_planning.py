"""Closed, explicit clarification before the existing bounded Coordinator.

Free text records the person's goal; it is not executable instructions. We do
not pretend that numbers, keywords, or a caller's operation name identify the
desired analysis. A human selects a labelled meaning against a scoped digest.
"""
from . import delegation
from .model_evaluation import digest, prepare
from .states import ContractError

FIELDS = frozenset({"goal", "input_text", "coordinator_model_id", "target_model_ids",
                    "parent_indices", "max_depth"})
CHOICES = {
    "1": ("Проверить точность передачи сводки", "verify_fact_transfer"),
    "2": ("Разобрать отдельные участки данных", "numeric_breakdown"),
}


def execution_mode(service):
    """Trusted composition, not a connection label or a claim from a body."""
    from . import test_executor
    return "diagnostic" if service.executor is test_executor.execute else "pending_receipt"


def proposal(context, service, payload):
    if type(payload) is not dict or set(payload) - FIELDS:
        raise ContractError("coordinator_public_payload_invalid")
    goal = payload.get("goal")
    if type(goal) is not str or not 1 <= len(goal.strip()) <= 400:
        raise ContractError("coordinator_goal_and_data_required")
    spec = prepare("json_arithmetic", payload.get("input_text"))
    model = service.model_detail(context=context, model_id=payload.get("coordinator_model_id"))
    depth = payload.get("max_depth", 3)
    nodes = delegation._graph(payload.get("target_model_ids"), payload.get("parent_indices"),
                              depth, model["persona_id"], service, context)
    from .coordinator import _validate_operation
    choices = []
    for choice, (label, operation) in CHOICES.items():
        try:
            _validate_operation(operation, nodes, spec["input"])
            available, reason = True, None
        except ContractError as error:
            available, reason = False, error.code
        choices.append({"id": choice, "label": label, "available": available, "reason": reason})
    scope = {"workspace_id": context.scope.workspace_id, "environment": context.scope.environment.value}
    pin = {"version": 1, "scope": scope, "user_id": str(context.user_uuid), "request": payload,
           "execution_mode": execution_mode(service),
           "connections": [delegation.connection_digest(service, context, identity) for identity in
               [model["id"], *[node["model_id"] for node in nodes]]]}
    return {"status": "clarification_required", "goal": goal.strip(), "plan_sha256": digest(pin),
        "question": "Что должны сделать специалисты с этими данными?", "choices": choices,
        "constraints": {"max_depth": depth, "max_fanout": delegation.MAX_FANOUT,
                        "max_tasks": delegation.MAX_TOTAL, "budget": "existing workspace allowance"},
        "required_evidence": ["independently checked result", "source and contribution references"],
        "approval_mode": "advice_only; separate explicit graph approval", "risk": "low",
        "scope": scope, "actions": ["commission"], "dispatches": 0}


def resolve(context, service, payload):
    if type(payload) is not dict:
        raise ContractError("coordinator_public_payload_invalid")
    body = {key: value for key, value in payload.items() if key != "selection"}
    preview = proposal(context, service, body)
    selection = payload.get("selection")
    if (type(selection) is not dict or set(selection) != {"id", "plan_sha256"}
            or selection.get("plan_sha256") != preview["plan_sha256"]):
        raise ContractError("coordinator_clarification_required")
    selected = next((row for row in preview["choices"] if row["id"] == selection.get("id")), None)
    if selected is None or not selected["available"]:
        raise ContractError("coordinator_selection_unavailable")
    return {**body, "operation": CHOICES[selected["id"]][1]}, {
        "selection_id": selected["id"], "label": selected["label"], "plan_sha256": preview["plan_sha256"],
        "origin": "explicit_human_clarification", "goal": preview["goal"],
        "constraints": preview["constraints"], "required_evidence": preview["required_evidence"],
        "task_class": delegation.OPERATIONS[CHOICES[selected["id"]][1]]["rubric"],
        "required_capabilities": ["ai_pro_models"],
        "approval_mode": preview["approval_mode"], "risk": preview["risk"], "scope": preview["scope"]}
