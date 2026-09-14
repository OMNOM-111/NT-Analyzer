"""The external agent is off until someone turns it on, and so is its test agent.

A feature that reaches other people's machines over the network must not arrive
switched on, and the development agent — which exists only to make the route
walkable — must not be reachable anywhere it could be mistaken for a real one.

Nothing here enables a flag. That is the point.
"""
from __future__ import annotations

import pytest

from app.ai_control_center import contracts as c, domain_gateway as gateway
from app.ai_control_center import external_agent_development as dev, live_gateway
from app.ai_control_center.flags import DISABLED, Flag, resolve
from app.ai_control_center.states import ContractError
from tests.test_agent_world_automation_revocation import human, world  # noqa: F401


def scope(environment=c.Environment.DEVELOPMENT):
    return c.TenantScope(environment=environment, workspace_id="ws_not_enabled")


def test_both_flags_are_off_until_a_workspace_is_named():
    for flag in (Flag.AI_EXTERNAL_AGENT_V1, Flag.AI_EXTERNAL_AGENT_TEST_V1):
        assert resolve(flag, scope=scope(), snapshot=DISABLED).enabled is False


def test_the_test_agent_cannot_be_enabled_without_the_feature_itself():
    """Its dependency is the real flag, so it can never be the only one on."""
    from app.ai_control_center.flags import REGISTRY
    assert Flag.AI_EXTERNAL_AGENT_V1 in REGISTRY[Flag.AI_EXTERNAL_AGENT_TEST_V1].dependencies
    assert Flag.AI_TASK_GRAPH_V2 in REGISTRY[Flag.AI_EXTERNAL_AGENT_V1].dependencies


def test_the_domain_refuses_while_the_flag_is_off(world, monkeypatch):  # noqa: F811
    """The owner session is real; only the mechanism is not enabled."""
    assert world.capability(True)
    monkeypatch.setenv(live_gateway.MECHANISMS_ENV, world.mechanisms("AI_EXECUTION_V2"))
    monkeypatch.setattr(live_gateway, "_SNAPSHOTS", {})
    authorized, _service = human(world)

    with pytest.raises(ContractError) as refused:
        gateway.list_domain(authorized, "external_agents")
    assert refused.value.code == "external_agent_disabled"

    with pytest.raises(ContractError) as denied:
        gateway.mutate(authorized, "external_agents", "new", "create",
                       {"payload": {"display_name": "x", "protocol": "a2a-0.3-jsonrpc-bounded",
                                    "endpoint": dev.ENDPOINT, "credential": dev.CREDENTIAL,
                                    "allowed_capabilities": ["stratforge.json_arithmetic.v1"]},
                        "idempotency_key": "while-off"})
    assert denied.value.code == "external_agent_disabled"


def test_the_development_agent_is_not_offered_while_its_own_flag_is_off(world, monkeypatch):  # noqa: F811
    """The feature is on; the test agent still is not."""
    assert world.capability(True)
    monkeypatch.setenv(live_gateway.MECHANISMS_ENV,
                       world.mechanisms("AI_EXTERNAL_AGENT_V1", "AI_EXECUTION_V2"))
    monkeypatch.setattr(live_gateway, "_SNAPSHOTS", {})
    authorized, _service = human(world)

    listing = gateway.list_domain(authorized, "external_agents")
    assert listing["enabled"] is True
    assert "test_connection" not in listing, "the synthetic agent must not be advertised"
    assert dev.enabled(authorized) is False

    with pytest.raises(ContractError) as refused:
        gateway.mutate(authorized, "external_agents", "new", "create",
                       {"payload": {"display_name": "Development", "protocol": "a2a-0.3-jsonrpc-bounded",
                                    "endpoint": dev.ENDPOINT, "credential": dev.CREDENTIAL,
                                    "allowed_capabilities": ["stratforge.json_arithmetic.v1"]},
                        "idempotency_key": "test-agent-while-off"})
    assert refused.value.code == "external_agent_test_disabled"


def test_its_endpoint_is_unreachable_by_construction():
    """`.invalid` is reserved by RFC 2606 and resolves nowhere, ever."""
    assert dev.ENDPOINT.endswith(".invalid/a2a")
    assert "synthetic" in dev.CREDENTIAL or "no-real" in dev.CREDENTIAL
