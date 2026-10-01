from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from app.ai_control_center import contracts as c, periodic_owner_model as route
from app.ai_control_center.states import ContractError


OWNER = UUID("77c6d443-29ec-45ac-8f6c-60dbbd4c70f2")
WORKSPACE = "ws_periodic_owner"


def _scope():
    return {"user_id": 17, "user_uuid": str(OWNER), "workspace_id": WORKSPACE}


def _context():
    return c.RequestContext(
        scope=c.TenantScope(environment=c.Environment.PRODUCTION, workspace_id=WORKSPACE),
        user_uuid=OWNER,
        actor=c.ActorRef(kind=c.ActorKind.SERVICE,
            actor_id=UUID("4fc88e4b-a0e5-4a88-92c2-32d816b84bcc"),
            on_behalf_of=OWNER),
    )


def test_subject_is_server_only(monkeypatch) -> None:
    monkeypatch.setattr(route.server_gateway, "environment", lambda: None)
    with pytest.raises(ContractError, match="periodic_owner_server_required"):
        route._subject(_scope())


def test_subject_revalidates_exact_owner_runtime_and_capabilities(monkeypatch) -> None:
    monkeypatch.setattr(route.server_gateway, "environment", lambda: c.Environment.PRODUCTION)
    monkeypatch.setattr(route.server_gateway, "configured", lambda workspace_id: workspace_id == WORKSPACE)
    monkeypatch.setattr(route.runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(route.runtime_env, "is_server_environment", lambda: True)
    monkeypatch.setattr(route.workspaces, "runtime_monitor_scopes", lambda: [{
        "user_id": 17, "workspace_id": WORKSPACE, "is_owner": True,
        "uses_owner_runtime": True, "membership_role": "owner",
    }])
    monkeypatch.setattr(route.account_auth, "find_active_user", lambda user_id: {
        "user_id": user_id, "status": "active", "is_owner": True,
        "is_preview_user": False, "is_service_account": False,
    })
    monkeypatch.setattr(route.account_auth, "user_uuid_for_legacy_id", lambda user_id: str(OWNER))
    monkeypatch.setattr(route.workspaces, "require_workspace_writer", lambda user_id, workspace_id: {
        "status": "active", "uses_owner_runtime": True, "owner_user_id": user_id,
        "membership": {"role": "owner"},
    })
    monkeypatch.setattr(route.permissions, "resolve_for_user_id", lambda *_args: {
        "capabilities": {"ai_lab": True, "ai_pro_models": True},
    })

    context = route._subject(_scope())

    assert context.scope.environment is c.Environment.PRODUCTION
    assert context.scope.workspace_id == WORKSPACE
    assert context.actor.kind is c.ActorKind.SERVICE
    assert context.actor.on_behalf_of == OWNER


def test_admit_fails_closed_when_budget_is_exhausted(monkeypatch) -> None:
    context = _context()
    monkeypatch.setattr(route, "_subject", lambda scope: context)
    monkeypatch.setattr(route.ai_budgets, "check_budget", lambda *_args: {"ok": False})

    with pytest.raises(ContractError, match="model_budget_exhausted"):
        route._admit(_scope(), context, context, "provider_transmit", 0.01)


def test_select_uses_only_single_general_owner_model(monkeypatch) -> None:
    context = _context()
    model = SimpleNamespace(header=SimpleNamespace(owner_user_uuid=OWNER), status="active",
                            provider_key="gemini", profile="model-profile")
    account = SimpleNamespace(header=SimpleNamespace(owner_user_uuid=OWNER), status="active",
                              provider_key="gemini")
    persona = SimpleNamespace(header=SimpleNamespace(owner_user_uuid=OWNER), status="active",
                              profile="persona-profile")
    profiles = {
        "model-profile": {"source": "private_model_connection", "connection_kind": "model",
            "provider_account_id": "account", "persona_id": "persona", "base_url": "https://example.test",
            "protocol": "openai_chat_completions_v1"},
        "persona-profile": {"style": "concise"},
    }

    class Service:
        def _all(self, _context, _kind): return iter((model,))
        def _json(self, _context, reference): return profiles[reference]
        def _get(self, _context, kind, _identity):
            return account if kind.value == "provider_account" else persona
        def _endpoint(self, *_args): return None

    monkeypatch.setattr(route, "validate_protocol", lambda profile: profile)
    chosen = route._select(Service(), context)

    assert chosen == (model, account, profiles["model-profile"])


def test_select_rejects_ambiguous_general_models(monkeypatch) -> None:
    context = _context()
    model = SimpleNamespace(header=SimpleNamespace(owner_user_uuid=OWNER), status="active",
                            provider_key="gemini", profile="model-profile")
    account = SimpleNamespace(header=SimpleNamespace(owner_user_uuid=OWNER), status="active",
                              provider_key="gemini")
    persona = SimpleNamespace(header=SimpleNamespace(owner_user_uuid=OWNER), status="active",
                              profile="persona-profile")
    profiles = {
        "model-profile": {"source": "private_model_connection", "connection_kind": "model",
            "provider_account_id": "account", "persona_id": "persona", "base_url": "https://example.test",
            "protocol": "openai_chat_completions_v1"},
        "persona-profile": {},
    }

    class Service:
        def _all(self, _context, _kind): return iter((model, model))
        def _json(self, _context, reference): return profiles[reference]
        def _get(self, _context, kind, _identity):
            return account if kind.value == "provider_account" else persona
        def _endpoint(self, *_args): return None

    monkeypatch.setattr(route, "validate_protocol", lambda profile: profile)
    with pytest.raises(ContractError, match="periodic_owner_model_ambiguous"):
        route._select(Service(), context)
