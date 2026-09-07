"""The automation and router domains, connected to the mechanisms that exist.

`domain_gateway` has always dispatched these two domains to a `mechanism_gateway`
module that no branch contains. `mechanism_domains` stands in for it: an adapter
that delegates to `automation_authority`, `scheduler` and `router_v2` and owns no
decision of its own.

Two properties matter more than the surface itself and are pinned here: reading
state never starts work, and an operation the adapter does not implement is
refused by name instead of being answered as though it worked.

No provider, socket, browser or owner data: the fixtures build real records in a
disposable SQLite root.
"""
from __future__ import annotations

import json
import sys

import pytest

from app.ai_control_center import domain_gateway as gateway, mechanism_domains, router_v2
from app.ai_control_center.states import ContractError
from tests.test_agent_world_domain_gateway import models, ordinary, http_get
from tests.test_agent_world_live_gateway import WORKSPACE, isolated_runtime, owner


@pytest.fixture
def mechanisms(models, monkeypatch):
    """The workspace-scoped, Development-only opt-in these domains require."""
    monkeypatch.setenv(gateway.live_gateway.MECHANISMS_ENV, json.dumps({
        "environment": "development",
        "flags": {name: [WORKSPACE] for name in
                  ("AI_SCHEDULER_V1", "AI_DELEGATION_V2", "AI_EXECUTION_V2",
                   "AI_ROUTER_SHADOW_V2", "AI_ROUTER_V2")}}))
    gateway.live_gateway._SNAPSHOTS.clear()
    models.account.scope.update(is_owner=True, uses_owner_runtime=True)
    models.account.state["user"]["is_owner"] = True
    models.account.state["workspaces"][WORKSPACE]["uses_owner_runtime"] = True
    models.account.state["permissions"]["capabilities"].update(
        ai_pro_models=True, ai_automation=False)
    return models


def read(mechanisms, domain, **kwargs):
    authorized = gateway.access(mechanisms.account.scope)
    return mechanism_domains.read(authorized, gateway.models(authorized), domain, **kwargs)


def mutate(mechanisms, domain, identity, action, payload=None, **kwargs):
    authorized = gateway.access(mechanisms.account.scope)
    return mechanism_domains.mutate(
        authorized, gateway.models(authorized), domain, identity, action, payload or {},
        expected_revision=kwargs.pop("expected_revision", 1),
        idempotency_key=kwargs.pop("idempotency_key", "mechanism-domain-case"))


def test_reading_either_domain_reports_state_without_starting_anything(mechanisms, monkeypatch):
    monkeypatch.setattr(router_v2, "select", lambda *a, **kw: pytest.fail("a read ran a selection"))
    monkeypatch.setattr(gateway, "enqueue_model", lambda *a, **kw: pytest.fail("a read queued work"))

    automation = read(mechanisms, "automation")
    assert automation["enabled"] is True and automation["items"] == []
    assert automation["capabilities"] == {"ai_automation": False}
    # The way to grant it is named rather than duplicated inside this domain.
    assert automation["capability_route"] == "POST /api/auth/users/{user_id}/permission"
    assert automation["flags"]["AI_SCHEDULER_V1"] is True
    assert any("ai_automation" in line for line in automation["limitations"])

    router = read(mechanisms, "router")
    assert router["flags"] == {"AI_ROUTER_SHADOW_V2": True, "AI_ROUTER_V2": True}
    assert router["policy_version"] == router_v2.RoutingPolicy().version
    assert "json_arithmetic" in router["task_classes"]
    assert mechanisms.queue == {} and mechanisms.executions == []


def test_an_operation_this_adapter_does_not_implement_is_refused_by_name(mechanisms):
    for domain, action in (("automation", "approve_delegation"), ("router", "select"),
                           ("automation", "delete"), ("router", "apply")):
        with pytest.raises(ContractError) as refused:
            mutate(mechanisms, domain, "new", action)
        assert refused.value.code == "mechanism_action_unsupported"
    with pytest.raises(ContractError) as unknown:
        read(mechanisms, "memory")
    assert unknown.value.code == "unknown_domain"


def test_enabling_a_schedule_is_decided_by_the_mechanism_not_by_this_adapter(mechanisms):
    """Whatever is missing, the refusal is the scheduler's or the authority's.

    The capability side of this is proved on the real permission stack in
    `test_agent_world_automation_revocation`. What matters here is that the
    adapter never reaches its own verdict about a schedule: it forwards the
    request and lets the mechanism refuse.
    """
    body = {"source_domain": "routines", "model_id": mechanisms.model["id"],
            "schedule": {"local_start": "2099-01-01T00:00:00", "timezone": "UTC",
                         "interval_seconds": 0, "occurrences": 1, "grace_seconds": 300},
            "payload": {"rubric_key": "extract_facts", "input_text": "action=review"},
            "conversation_id": "AW-mechanism-domain", "message_id": "MSG-000000000001"}
    with pytest.raises(ContractError) as refused:
        mutate(mechanisms, "automation", "00000000-0000-4000-8000-000000000001", "enable", body)
    assert not refused.value.code.startswith("mechanism_")
    assert mechanisms.queue == {} and mechanisms.executions == []

    # A request this adapter cannot even forward is refused by it, by name.
    with pytest.raises(ContractError) as incomplete:
        mutate(mechanisms, "automation", "00000000-0000-4000-8000-000000000001", "enable",
               {"source_domain": "routines"})
    assert incomplete.value.code == "mechanism_payload_incomplete"


def test_a_router_preview_is_a_shadow_decision_that_dispatches_nothing(mechanisms):
    task = mechanisms.service.start_task(
        context=mechanisms.context, model_id=mechanisms.model["id"],
        payload={"rubric_key": "json_arithmetic", "input_text": json.dumps([1, 2, 3])},
        idempotency_key="router-preview-source")
    decision = mutate(mechanisms, "router", task["id"], "preview",
                      {"max_cost_usd": 0.01, "max_latency_ms": 60000})
    assert decision["mode"] == "shadow" and decision["task_class"] == "json_arithmetic"
    assert decision["dispatch_performed"] is False and decision["permission_granted"] is False
    assert decision["applied"] is False and decision["quality_ranking"] is False
    assert decision["actual_model_id"] == mechanisms.model["id"]
    assert decision["legacy_model_id"] == mechanisms.model["id"]
    assert decision["decision_sha256"]
    # Every candidate carries the reason it was or was not eligible.
    assert all(row.get("reason_codes") for row in decision["candidates"])
    assert mechanisms.executions == []


def test_a_task_view_names_the_model_that_actually_ran_it(mechanisms):
    task = mechanisms.service.start_task(
        context=mechanisms.context, model_id=mechanisms.model["id"],
        payload={"rubric_key": "json_arithmetic", "input_text": json.dumps([4, 5, 6])},
        idempotency_key="router-view-source")
    view = read(mechanisms, "router", identity=task["id"])
    assert view["task"]["id"] == task["id"]
    assert view["actual_choice"]["model_id"] == mechanisms.model["id"]
    # Nothing claims a routing decision was applied to a task that never had one.
    assert view["actual_choice"]["routing_applied"] is False
    assert view["actual_choice"]["decided_by"] == "request"


def test_the_checkpoint_module_wins_and_neither_present_fails_closed(mechanisms, monkeypatch):
    """The adapter stands in; it never displaces the module it substitutes for."""
    sentinel = object()
    monkeypatch.setitem(sys.modules, "app.ai_control_center.mechanism_gateway", sentinel)
    assert gateway._mechanism_gateway() is sentinel

    monkeypatch.setitem(sys.modules, "app.ai_control_center.mechanism_gateway", None)
    assert gateway._mechanism_gateway() is mechanism_domains

    monkeypatch.setitem(sys.modules, "app.ai_control_center.mechanism_domains", None)
    with pytest.raises(ContractError) as closed:
        gateway._mechanism_gateway()
    assert closed.value.code == "mechanism_domain_unavailable"
    handler = http_get(mechanisms.account, "domains/automation")
    assert handler.status == 409 and handler.result["code"] == "mechanism_domain_unavailable"
