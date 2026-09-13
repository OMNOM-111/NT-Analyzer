"""A person picks which of a Persona's connections answers the next message.

The override narrows; it never widens. It can only name an executable connection
the same user already bound to that Persona, it lasts for one message, it leaves
the Persona's identity, history and role untouched, and the task records that a
person chose it. Without an override the Persona's single binding answers; two
bindings are refused as ambiguous rather than silently routed, because the
Router chooses only through its own explicit preview and apply.

Disposable SQLite, the named local test executor, no provider call.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app import durable, local_worker
from app.ai_control_center import contracts as c, domain_gateway as gateway, model_chat, test_executor
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_gateway import ordinary  # noqa: F401
from tests.test_agent_world_live_gateway import isolated_runtime, owner  # noqa: F401
from tests.test_agent_world_models import context as make_context
from tests.test_agent_world_persona_chat_execution import (  # noqa: F401
    MESSAGE, _enable_persona_v2, _rows, persona_chat)


def _drain(fixture, limit=10):
    for _ in range(limit):
        queued = [job for job in durable.list_worker_jobs(fixture.root) if job.get("status") == "queued"]
        if not queued:
            return
        local_worker.run_once(worker_id="persona-override-worker")
    raise AssertionError("worker batch did not settle")


def _verified(fixture, model_id, key):
    """A real connection test on the local executor, so the model can execute."""
    fixture.service.test(context=fixture.context, model_id=model_id, idempotency_key=key)
    _drain(fixture)
    detail = fixture.service.model_detail(context=fixture.context, model_id=model_id)
    assert detail["execution_available"] is True, detail
    return detail


def _second(fixture, label="Second binding"):
    return fixture.service.connect(context=fixture.context,
        payload={**fixture.payload, "label": label}, idempotency_key="override-" + uuid4().hex[:12])


def _ask(fixture, *, selected=None, key="override-request"):
    return model_chat.try_persona(message=MESSAGE, authorized=fixture.authorized, service=fixture.service,
        persona_id=str(fixture.persona.header.entity_id), persona_revision=fixture.persona.header.revision,
        conversation_id=fixture.conversation, request_id=key, user_message="@Ответчик: " + MESSAGE,
        **({"selected_model_id": selected} if selected is not None else {}))


def _model_jobs(fixture):
    return [job for job in durable.list_worker_jobs(fixture.root, kind="agent_world_model")
            if not (job.get("payload") or {}).get("phase")]


def test_a_chosen_connection_answers_and_the_task_walks_to_completed(persona_chat, monkeypatch):
    fixture = persona_chat
    _enable_persona_v2(fixture, monkeypatch)
    _verified(fixture, fixture.model["id"], "override-verify-a")
    second = _second(fixture)
    _verified(fixture, second["id"], "override-verify-b")
    persona_before = fixture.service._get(fixture.context, EntityKind.PERSONA, fixture.persona.header.entity_id)

    accepted = _ask(fixture, selected=second["id"])
    task_id = accepted["task_id"]
    pending = fixture.service.task_detail(context=fixture.context, task_id=task_id)
    assert pending["model_id"] == second["id"], "the override did not choose the connection that runs"
    assert pending["model_selection"] == {"reason": "user_override", "selected_model_id": second["id"]}

    _drain(fixture)
    result = fixture.service.task_detail(context=fixture.context, task_id=task_id)
    assert result["display_status"] == "awaiting_review"
    assert result["actual_model"] == test_executor.EXECUTOR and result["external_call"] is False

    done = gateway.mutate(fixture.authorized, "tasks", task_id, "review_result", {
        "payload": {"decision": "accept", "source_sha256": result["human_review"]["source_sha256"],
                    "comment": "Явная проверка ответа выбранного подключения, не оценка качества."},
        "expected_revision": result["revision"], "idempotency_key": "override-human-review"})
    assert done["chat_delivery"]["problems"] == [], done
    completed = fixture.service.task_detail(context=fixture.context, task_id=task_id)
    assert completed["display_status"] == "completed"
    assert completed["model_selection"]["reason"] == "user_override"

    # Choosing a connection changed nothing about who answered.
    persona_after = fixture.service._get(fixture.context, EntityKind.PERSONA, fixture.persona.header.entity_id)
    assert persona_after.header.revision == persona_before.header.revision
    assert persona_after.display_name == persona_before.display_name
    assert completed["persona_id"] == str(fixture.persona.header.entity_id)
    assert completed["lead"]["display_name"] == fixture.persona.display_name
    task = fixture.service._get(fixture.context, EntityKind.TASK, task_id)
    assert fixture.service._get(fixture.context, EntityKind.AGENT_ROLE, task.role.entity_id).role_key == "model_response"


def test_without_an_override_the_single_binding_answers_and_says_so(persona_chat):
    fixture = persona_chat
    _verified(fixture, fixture.model["id"], "default-verify")
    task_id = _ask(fixture, key="default-request")["task_id"]
    detail = fixture.service.task_detail(context=fixture.context, task_id=task_id)
    assert detail["model_id"] == fixture.model["id"]
    assert detail["model_selection"] == {"reason": "persona_single_binding", "selected_model_id": None}


def test_removing_the_override_with_two_bindings_asks_instead_of_silently_routing(persona_chat):
    fixture = persona_chat
    _verified(fixture, fixture.model["id"], "ambiguous-verify-a")
    _verified(fixture, _second(fixture)["id"], "ambiguous-verify-b")
    before = len(_model_jobs(fixture))
    with pytest.raises(ContractError, match="persona_model_ambiguous"):
        _ask(fixture, key="ambiguous-request")
    assert len(_model_jobs(fixture)) == before


def _foreign_model(fixture):
    """A real connection owned by the same user in another workspace."""
    other = make_context(workspace="ws_foreign_override", user=fixture.context.user_uuid)
    service = ModelService(SQLiteAgentWorldRepository(fixture.root / "persona-chat.sqlite"),
                           secrets=fixture.secrets, admit=lambda *args: None)
    policy = service._put(other, {"version": "foreign-override-fixture"})
    persona = service._ensure(other, c.Persona, uuid4(), uuid4(), policy,
        display_name="Foreign workspace Persona", profile=service._put(other, {"description": "Not here"}))
    service._walk(other, persona, "active")
    return service.connect(context=other, payload={**fixture.payload, "label": "Foreign connection",
        "persona_id": str(persona.header.entity_id)}, idempotency_key="foreign-override-connect")["id"]


@pytest.mark.parametrize("case", ["unknown", "malformed", "foreign_workspace", "revoked",
                                  "never_verified", "other_persona"])
def test_an_override_that_is_not_this_persona_s_executable_connection_is_refused(persona_chat, case):
    fixture = persona_chat
    _verified(fixture, fixture.model["id"], "refusal-verify")
    expected = "persona_model_selection_unavailable"
    if case == "unknown":
        selected = str(uuid4())
    elif case == "malformed":
        selected, expected = "not-a-model-id", "persona_selection_invalid"
    elif case == "foreign_workspace":
        selected = _foreign_model(fixture)
    elif case == "revoked":
        second = _second(fixture, "Revoked binding")
        _verified(fixture, second["id"], "refusal-verify-revoked")
        fixture.service.disconnect(context=fixture.context, model_id=second["id"])
        selected = second["id"]
    elif case == "never_verified":
        selected = _second(fixture, "Unverified binding")["id"]
    else:
        policy = fixture.service._put(fixture.context, {"version": "other-persona-fixture"})
        other = fixture.service._ensure(fixture.context, c.Persona, uuid4(), uuid4(), policy,
            display_name="Другая Persona", profile=fixture.service._put(fixture.context, {"description": "Other"}))
        fixture.service._walk(fixture.context, other, "active")
        foreign_binding = fixture.service.connect(context=fixture.context,
            payload={**fixture.payload, "label": "Other Persona binding", "persona_id": str(other.header.entity_id)},
            idempotency_key="other-persona-binding")
        _verified(fixture, foreign_binding["id"], "refusal-verify-other")
        selected = foreign_binding["id"]

    before_jobs, before_rows = len(_model_jobs(fixture)), len(_rows(fixture))
    persona_revision = fixture.service._get(fixture.context, EntityKind.PERSONA,
                                            fixture.persona.header.entity_id).header.revision
    with pytest.raises(ContractError, match=expected):
        _ask(fixture, selected=selected, key="refusal-" + case)
    assert len(_model_jobs(fixture)) == before_jobs, "a refused override still dispatched"
    assert len(_rows(fixture)) == before_rows, "a refused override still wrote to the chat"
    assert fixture.service._get(fixture.context, EntityKind.PERSONA,
                                fixture.persona.header.entity_id).header.revision == persona_revision


def test_selection_provenance_cannot_be_forged_through_the_constructor(persona_chat):
    fixture = persona_chat
    _verified(fixture, fixture.model["id"], "forge-verify")
    persona = fixture.persona.ref()
    for bad in ({"reason": "user_override", "selected_model_id": None},
                {"reason": "persona_single_binding", "selected_model_id": fixture.model["id"]},
                {"reason": "router", "selected_model_id": None},
                {"reason": "user_override", "selected_model_id": str(uuid4())}):
        with pytest.raises(ContractError, match="persona_model_selection_invalid"):
            fixture.service.start_task(context=fixture.context, model_id=fixture.model["id"],
                payload={"rubric_key": "assistant_response", "input_text": MESSAGE},
                idempotency_key="forge-" + uuid4().hex[:8], _persona=persona, _model_selection=bad)
    with pytest.raises(ContractError, match="persona_model_selection_invalid"):
        fixture.service.start_task(context=fixture.context, model_id=fixture.model["id"],
            payload={"rubric_key": "assistant_response", "input_text": MESSAGE}, idempotency_key="forge-no-persona",
            _model_selection={"reason": "persona_single_binding", "selected_model_id": None})
