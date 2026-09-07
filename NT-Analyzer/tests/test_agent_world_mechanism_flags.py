"""Fail-closed configuration and revocation for the new mechanism flags.

Ported during integration from the Codex work-in-progress snapshot:
`NT-Analyzer/tests/test_agent_world_mechanism_flags.py`, untracked at
`db85773f`, sha256 99db9ff3f321c526f1b5da3f3b3fc4f850f492e6dbbc8c27b985c1383c8c5bff.
The source worktree was not modified.

Two adaptations, both noted at the assertion: a differently-cased workspace id
is now shown to be rejected by TenantScope itself rather than merely declined by
the flag layer, and nothing else was changed. Running these against the merged
build found three real gaps, fixed in the same branch: delegation and the router
resolved flags against a snapshot cached at admission, so revoking a mechanism
did not reach work already in flight; and a configuration document with a
repeated key resolved to whichever value came last instead of failing closed.
"""

from __future__ import annotations

import json
import socket
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.ai_control_center import delegation, execution_v2, live_gateway as gateway, router_v2
from app.ai_control_center.contracts import Environment, TenantScope
from app.ai_control_center.flags import Flag, REGISTRY, resolve
from app.ai_control_center.states import ContractError
from tests.test_agent_world_live_gateway import (
    OTHER_WORKSPACE, WORKSPACE, isolated_runtime, owner,
)


NEW_FLAGS = (Flag.AI_ROUTER_SHADOW_V2, Flag.AI_ROUTER_V2, Flag.AI_EXECUTION_V2,
             Flag.AI_DELEGATION_V2, Flag.AI_SCHEDULER_V1)


@pytest.fixture(autouse=True)
def mechanism_isolation(isolated_runtime, monkeypatch):
    monkeypatch.delenv(gateway.MECHANISMS_ENV, raising=False)

    def forbid_network(*args, **kwargs):
        pytest.fail("Mechanism flag tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", forbid_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbid_network)


def configure(monkeypatch, flags, *, workspace=WORKSPACE, environment="development"):
    monkeypatch.setenv(gateway.MECHANISMS_ENV, json.dumps({
        "environment": environment, "flags": {flag.value: [workspace] for flag in flags},
    }))


def enabled(context, snapshot):
    return {flag for flag in NEW_FLAGS if resolve(flag, scope=context.scope, snapshot=snapshot).enabled}


def test_new_mechanisms_default_off_preserves_approved_local_flags(owner):
    authorized = gateway.access(owner.scope)
    assert gateway.mechanism_configuration(WORKSPACE) == {
        "status": "disabled", "flags": [], "reason_code": "not_configured",
    }
    assert enabled(authorized["context"], authorized["snapshot"]) == set()
    assert all(REGISTRY[flag].default is False for flag in NEW_FLAGS)
    assert all(resolve(flag, scope=authorized["context"].scope, snapshot=authorized["snapshot"]).enabled
               for flag in gateway._FLAGS)
    assert len(owner.calls["audit"]) == 1
    assert not gateway.runtime_env.data_root().exists()


@pytest.mark.parametrize("raw", ["", " ", "\r\n\t"])
def test_empty_mechanism_configuration_is_disabled(owner, monkeypatch, raw):
    monkeypatch.setenv(gateway.MECHANISMS_ENV, raw)
    assert gateway.mechanism_configuration(WORKSPACE)["status"] == "disabled"
    authorized = gateway.access(owner.scope)
    assert not enabled(authorized["context"], authorized["snapshot"])


@pytest.mark.parametrize("raw", [
    "{", "not-json", "null", "true", "1", '"development"', "[]", "{}",
    '{"environment":"development"}', '{"flags":{}}',
    '{"environment":"development","flags":[],"extra":true}',
    '{"environment":"development","flags":null}',
    '{"environment":"development","flags":true}',
    '{"environment":"development","flags":{ "AI_EXECUTION_V2": true }}',
    '{"environment":"development","flags":{ "AI_EXECUTION_V2": "' + WORKSPACE + '" }}',
    '{"environment":"development","flags":{ "AI_EXECUTION_V2": [] }}',
    '{"environment":"development","flags":{ "AI_EXECUTION_V2": [null] }}',
    '{"environment":"development","flags":{ "AI_EXECUTION_V2": [true] }}',
    '{"environment":"development","flags":{ "AI_EXECUTION_V2": [1] }}',
    '{"environment":"development","flags":{ "AI_EXECUTION_V2": [[]] }}',
    '{"environment":"development","flags":{ "AI_EXECUTION_V2": [{}] }}',
    '{"environment":"development","flags":{ "AI_NOT_REGISTERED": ["' + WORKSPACE + '"] }}',
    '{"environment":"development","flags":{ "AI_TASK_GRAPH_V2": ["' + WORKSPACE + '"] }}',
])
def test_malformed_schema_disables_all_new_mechanisms_but_not_local(owner, monkeypatch, raw):
    monkeypatch.setenv(gateway.MECHANISMS_ENV, raw)
    assert gateway.mechanism_configuration(WORKSPACE) == {
        "status": "invalid", "flags": [], "reason_code": "invalid_server_configuration",
    }
    authorized = gateway.access(owner.scope)
    assert not enabled(authorized["context"], authorized["snapshot"])
    assert resolve(Flag.AI_COMMAND_CENTER_UI, scope=authorized["context"].scope,
                   snapshot=authorized["snapshot"]).enabled


@pytest.mark.parametrize("environment", [None, True, "", "Development", "local", "staging", "canary", "production", "*"])
def test_configuration_requires_exact_development_environment(owner, monkeypatch, environment):
    configure(monkeypatch, NEW_FLAGS, environment=environment)
    assert gateway.mechanism_configuration(WORKSPACE)["status"] == "invalid"
    authorized = gateway.access(owner.scope)
    assert not enabled(authorized["context"], authorized["snapshot"])


@pytest.mark.parametrize("bad_id", ["*", "ws_*", "ws_a", "ws_owner/path", "ws_owner\\path", " ws_valid", "ws_valid ", "not_workspace", "ws_" + "x" * 94])
def test_invalid_or_wildcard_workspace_rejects_entire_mixed_config(owner, monkeypatch, bad_id):
    monkeypatch.setenv(gateway.MECHANISMS_ENV, json.dumps({"environment": "development", "flags": {
        Flag.AI_ROUTER_V2.value: [WORKSPACE], Flag.AI_EXECUTION_V2.value: [WORKSPACE, bad_id],
    }}))
    assert gateway.mechanism_configuration(WORKSPACE)["status"] == "invalid"
    authorized = gateway.access(owner.scope)
    assert not enabled(authorized["context"], authorized["snapshot"])


def test_duplicate_workspace_fails_closed(owner, monkeypatch):
    monkeypatch.setenv(gateway.MECHANISMS_ENV, json.dumps({"environment": "development", "flags": {
        Flag.AI_EXECUTION_V2.value: [WORKSPACE, WORKSPACE],
    }}))
    assert gateway.mechanism_configuration(WORKSPACE)["status"] == "invalid"


@pytest.mark.parametrize("raw", [
    '{"environment":"production","environment":"development","flags":{"AI_EXECUTION_V2":["' + WORKSPACE + '"]}}',
    '{"environment":"development","flags":{"AI_EXECUTION_V2":["*"]},"flags":{"AI_EXECUTION_V2":["' + WORKSPACE + '"]}}',
    '{"environment":"development","flags":{"AI_EXECUTION_V2":["*"],"AI_EXECUTION_V2":["' + WORKSPACE + '"]}}',
])
def test_duplicate_json_keys_are_not_an_implicit_last_value_enable(owner, monkeypatch, raw):
    monkeypatch.setenv(gateway.MECHANISMS_ENV, raw)
    assert gateway.mechanism_configuration(WORKSPACE)["status"] == "invalid"
    authorized = gateway.access(owner.scope)
    assert not enabled(authorized["context"], authorized["snapshot"])


def test_deep_malformed_document_fails_closed_not_unhandled_exception(owner, monkeypatch):
    monkeypatch.setenv(gateway.MECHANISMS_ENV, "[" * 1500 + "0" + "]" * 1500)
    assert gateway.mechanism_configuration(WORKSPACE)["status"] == "invalid"


def test_mechanism_opt_in_alone_cannot_activate_unapproved_local_workspace(monkeypatch):
    configure(monkeypatch, NEW_FLAGS)
    assert gateway.configured(WORKSPACE) is False
    assert gateway.mechanism_configuration(WORKSPACE)["flags"] == []
    with pytest.raises(ContractError, match="agent_world_local_disabled"):
        gateway.access({"workspace_id": WORKSPACE})


def test_exact_workspace_and_cached_scope_isolation(owner, monkeypatch):
    monkeypatch.setenv(gateway.WORKSPACES_ENV, WORKSPACE + "," + OTHER_WORKSPACE)
    configure(monkeypatch, NEW_FLAGS)
    authorized = gateway.access(owner.scope)
    context = authorized["context"]
    assert enabled(context, authorized["snapshot"]) == set(NEW_FLAGS)
    for workspace in (OTHER_WORKSPACE, WORKSPACE + "_suffix"):
        assert gateway.mechanism_configuration(workspace)["flags"] == []
        foreign = replace(context, scope=TenantScope(environment=Environment.DEVELOPMENT, workspace_id=workspace))
        assert not enabled(foreign, authorized["snapshot"])
    # Adapted during integration: a differently-cased workspace id cannot even be
    # built into a scope, which is stronger than the flag layer declining it.
    assert gateway.mechanism_configuration(WORKSPACE.upper())["flags"] == []
    with pytest.raises(ContractError):
        TenantScope(environment=Environment.DEVELOPMENT, workspace_id=WORKSPACE.upper())
    other = replace(context, scope=TenantScope(environment=Environment.DEVELOPMENT, workspace_id=OTHER_WORKSPACE))
    assert not enabled(other, gateway.flag_snapshot(other))
    assert len(owner.calls["audit"]) == 2


@pytest.mark.parametrize("dependent", [Flag.AI_DELEGATION_V2, Flag.AI_SCHEDULER_V1])
def test_dependency_requires_explicit_execution_opt_in(owner, monkeypatch, dependent):
    configure(monkeypatch, [dependent])
    authorized = gateway.access(owner.scope)
    decision = resolve(dependent, scope=authorized["context"].scope, snapshot=authorized["snapshot"])
    assert not decision.enabled and decision.reason == "dependency_disabled"
    assert decision.blocked_by == Flag.AI_EXECUTION_V2
    assert not enabled(authorized["context"], authorized["snapshot"])
    configure(monkeypatch, [dependent, Flag.AI_EXECUTION_V2])
    current = gateway.flag_snapshot(authorized["context"])
    assert enabled(authorized["context"], current) == {dependent, Flag.AI_EXECUTION_V2}


@pytest.mark.parametrize("flag", [Flag.AI_ROUTER_SHADOW_V2, Flag.AI_ROUTER_V2, Flag.AI_EXECUTION_V2])
def test_single_mechanism_does_not_implicitly_enable_other_mechanisms(owner, monkeypatch, flag):
    configure(monkeypatch, [flag])
    authorized = gateway.access(owner.scope)
    assert enabled(authorized["context"], authorized["snapshot"]) == {flag}


@pytest.mark.parametrize("replacement", [None, "{", '{"environment":"development","flags":{}}'])
def test_revocation_invalidates_cached_enabled_snapshot(owner, monkeypatch, replacement):
    configure(monkeypatch, NEW_FLAGS)
    authorized = gateway.access(owner.scope)
    context, initial = authorized["context"], authorized["snapshot"]
    assert enabled(context, initial) == set(NEW_FLAGS)
    assert gateway.flag_snapshot(context) is initial
    if replacement is None:
        monkeypatch.delenv(gateway.MECHANISMS_ENV)
    else:
        monkeypatch.setenv(gateway.MECHANISMS_ENV, replacement)
    current = gateway.flag_snapshot(context)
    assert current.revision != initial.revision and not enabled(context, current)
    assert enabled(context, initial) == set(NEW_FLAGS), "Historical immutable snapshot is not current authority"


def test_dependencies_are_revoked_in_a_cached_workspace_without_deleting_config(owner, monkeypatch):
    configure(monkeypatch, NEW_FLAGS)
    authorized = gateway.access(owner.scope)
    configure(monkeypatch, [Flag.AI_DELEGATION_V2, Flag.AI_SCHEDULER_V1])
    assert gateway.mechanism_configuration(WORKSPACE)["flags"]
    assert not enabled(authorized["context"], gateway.flag_snapshot(authorized["context"]))


def test_equivalent_key_order_reuses_same_audited_revision(owner, monkeypatch):
    configure(monkeypatch, NEW_FLAGS)
    authorized = gateway.access(owner.scope)
    configure(monkeypatch, reversed(NEW_FLAGS))
    assert gateway.flag_snapshot(authorized["context"]) is authorized["snapshot"]
    assert len(owner.calls["audit"]) == 1
    recorded = owner.calls["audit"][0][1]
    assert recorded["workspace_id"] == WORKSPACE
    assert set(recorded["details"]["flags"]) == {flag.value for flag in (*gateway._FLAGS, *NEW_FLAGS)}
    assert recorded["details"]["synthetic"] is False


def test_audit_failure_never_caches_unaudited_activation(owner, monkeypatch):
    configure(monkeypatch, NEW_FLAGS)
    def unavailable(*args, **kwargs):
        raise RuntimeError("disposable audit unavailable")
    monkeypatch.setattr(gateway.audit_events, "record", unavailable)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        gateway.access(owner.scope)
    assert gateway._SNAPSHOTS == {}


@pytest.mark.parametrize("environment", ["canary", "production"])
def test_new_flags_remain_disabled_outside_development_even_when_opted_in(owner, monkeypatch, environment):
    configure(monkeypatch, NEW_FLAGS)
    monkeypatch.setenv("DEPLOYMENT_ENV", environment)
    monkeypatch.setenv("STRATFORGE_ENV", environment)
    assert not gateway.configured(WORKSPACE)
    assert gateway.mechanism_configuration(WORKSPACE)["flags"] == []
    with pytest.raises(ContractError, match="agent_world_local_disabled"):
        gateway.access(owner.scope)
    assert not owner.calls["audit"] and not owner.calls["users"]


def test_preview_does_not_inherit_new_local_mechanisms(owner, monkeypatch):
    configure(monkeypatch, NEW_FLAGS)
    monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "1")
    monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "ab" * 12)
    assert gateway.preview_sandbox.enabled()
    assert gateway.mechanism_configuration(WORKSPACE)["flags"] == []
    with pytest.raises(ContractError, match="agent_world_local_disabled"):
        gateway.access(owner.scope)
    assert not owner.calls["audit"] and not owner.calls["users"]


@pytest.mark.parametrize("environment", [Environment.CANARY, Environment.PRODUCTION])
def test_a_development_snapshot_is_not_a_canary_or_production_grant(owner, monkeypatch, environment):
    configure(monkeypatch, NEW_FLAGS)
    authorized = gateway.access(owner.scope)
    foreign = replace(authorized["context"], scope=TenantScope(environment=environment, workspace_id=WORKSPACE))
    assert not enabled(foreign, authorized["snapshot"])


@pytest.mark.parametrize("kind", ["router_shadow", "router_active", "delegation", "scheduler"])
def test_old_authorization_cannot_reenable_a_revoked_mechanism(owner, monkeypatch, kind):
    configure(monkeypatch, NEW_FLAGS)
    authorized = gateway.access(owner.scope)
    authorized["refresh"] = lambda: gateway.access(owner.scope)
    monkeypatch.delenv(gateway.MECHANISMS_ENV)
    # The ordinary Local admission remains valid. This makes cached mechanism
    # use visible instead of hiding it behind a revoked user/workspace fixture.
    authorized["admit"]()
    with pytest.raises(ContractError, match="disabled"):
        if kind.startswith("router_"):
            router_v2._gate(authorized, kind.removeprefix("router_"))
        else:
            delegation.gate(authorized, "AI_DELEGATION_V2" if kind == "delegation" else "AI_SCHEDULER_V1")


def test_execution_refresh_rejects_revoked_snapshot_before_any_repository_or_provider_call(owner, monkeypatch):
    configure(monkeypatch, [Flag.AI_EXECUTION_V2])
    authorized = gateway.access(owner.scope)
    authorized["refresh"] = lambda: gateway.access(owner.scope)
    calls = []
    service = SimpleNamespace(_access=lambda *args: calls.append(args))
    monkeypatch.delenv(gateway.MECHANISMS_ENV)
    with pytest.raises(ContractError, match="execution_v2_gate_disabled"):
        execution_v2._fresh(authorized, service, authorized["context"], operation="execute")
    assert not calls
