"""How the connection behind a backtest, chart or routed task was chosen.

Every task a person starts from chat records one selection record: the mode
(explicit_override, single_available or router_approved), the reason, and the
connection itself — id, revision, model key, provider and account — read from the
stored records rather than restated by any caller. It lives in the stored task,
so a fresh service over the same records reads exactly the same thing.

No live owner runtime, network or provider call.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.ai_control_center import application_chat as app_chat, domain_gateway as gateway
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_application_chat import _model, _plan, authorized, queue_service  # noqa: F401
from tests.test_agent_world_live_backtests import service as canonical_queue  # noqa: F401
from tests.test_agent_world_models import setup as model_setup  # noqa: F401
from tests.test_agent_world_automation_revocation import human, world  # noqa: F401
from tests.test_agent_world_router_acceptance import apply, completed, preview, routed  # noqa: F401


def _connection_fields(selection, model_id):
    assert selection["model_id"] == model_id
    assert selection["model_key"] and selection["provider_key"] and selection["provider_account_id"]
    assert isinstance(selection["model_revision"], int) and selection["model_revision"] >= 1


def _restarted(service):
    return ModelService(SQLiteAgentWorldRepository(service.repository.path),
                        secrets=service.secrets, admit=lambda *args: None)


@pytest.mark.parametrize("kind", ["chart", "backtest"])
def test_an_application_plan_records_its_only_available_connection_and_survives_restart(
        model_setup, authorized, queue_service, kind):
    service, ctx, *_ = model_setup
    reply, _result = _plan(model_setup, authorized, kind=kind, request="provenance-" + kind)
    task_id = reply["actions"][0]["task_id"]
    detail = service.task_detail(context=ctx, task_id=task_id)
    selection = detail["model_selection"]
    assert selection["mode"] == "single_available" and selection["selected_model_id"] is None
    # Role-based application chat has no selected Persona behind it.
    assert selection["reason"] == "application_role_single_binding"
    _connection_fields(selection, detail["model_id"])
    assert _restarted(service).task_detail(context=ctx, task_id=task_id)["model_selection"] == selection


def test_an_explicit_application_override_is_recorded_as_a_person_s_choice(model_setup, authorized):
    service, ctx, *_ = model_setup
    model = _model(model_setup, "Иван", key="provenance-override")
    detail = service.plan_application(context=ctx, model_id=model["id"],
        spec={"instrument": "MNQ 09-26", "timeframe": "5m"}, kind="chart",
        idempotency_key="provenance-explicit-chart", conversation_id=None, message_id=None,
        _model_selection={"mode": "explicit_override", "selected_model_id": model["id"]})
    selection = detail["model_selection"]
    assert selection["mode"] == "explicit_override" and selection["selected_model_id"] == model["id"]
    assert selection["reason"] == "person_selected_connection"
    _connection_fields(selection, model["id"])
    assert _restarted(service).task_detail(context=ctx, task_id=detail["id"])["model_selection"] == selection


def test_no_caller_can_claim_the_router_chose_an_application_connection(model_setup, authorized):
    service, ctx, *_ = model_setup
    model = _model(model_setup, "Иван", key="provenance-forged")
    for bad in ({"mode": "router_approved", "selected_model_id": model["id"]},
                {"mode": "explicit_override", "selected_model_id": str(uuid4())}):
        with pytest.raises(ContractError, match="persona_model_selection_invalid"):
            service.plan_application(context=ctx, model_id=model["id"],
                spec={"instrument": "MNQ 09-26", "timeframe": "5m"}, kind="chart",
                idempotency_key="provenance-forged-" + uuid4().hex[:8], conversation_id=None, message_id=None,
                _model_selection=bad)


def test_a_router_apply_records_router_approved_bound_to_its_preview(routed):
    env = routed
    shown = preview(env)
    applied = apply(env, shown, key="provenance-router-apply")
    task_id = applied["started_task_id"]
    selection = env.service.task_detail(context=env.context, task_id=task_id)["model_selection"]
    assert selection["mode"] == "router_approved" and selection["reason"] == "router_preview_applied"
    assert selection["selected_model_id"] == env.models[1]["id"]
    assert selection["routing"]["preview_ref"] == shown["preview_ref"]
    _connection_fields(selection, env.models[1]["id"])

    result = completed(env, task_id)
    assert result["model_selection"] == selection
    # A new service instance over the same stored records reads the same record.
    fresh = gateway.models(env.authorized)
    assert fresh.task_detail(context=env.context, task_id=task_id)["model_selection"] == selection

    # A task started directly on a named model has no chat choice to record.
    source = env.service.task_detail(context=env.context, task_id=env.source_id)
    assert source.get("model_selection") is None
