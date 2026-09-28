"""Server admission and credential safety without using Development test seams."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from app import account_auth, runtime_env
from app.ai_control_center import contracts as c, domain_gateway, live_gateway, server_gateway, server_secrets
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.postgres_repository import PostgresAgentWorldRepository
from app.ai_control_center.flags import Flag, resolve
from app.ai_control_center.states import ContractError
from app.production_storage.core import PostgresClient


def _context(environment=c.Environment.CANARY, workspace="ws_server_12345678"):
    person = uuid4()
    return c.RequestContext(scope=c.TenantScope(environment=environment, workspace_id=workspace),
        user_uuid=person, actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=person))


def test_server_workspace_opt_in_is_exact_and_cannot_enable_local(monkeypatch):
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(runtime_env, "is_canary", lambda: True)
    monkeypatch.setattr(runtime_env, "is_production", lambda: False)
    monkeypatch.setattr(server_gateway.preview_sandbox, "enabled", lambda: False)
    monkeypatch.setenv(server_gateway.WORKSPACES_ENV, "ws_server_12345678")
    assert server_gateway.configured("ws_server_12345678")
    assert not server_gateway.configured("ws_foreign_12345678")
    for bad in ("*", "ws_server_12345678,*", "ws_server_12345678,ws_server_12345678", ""):
        monkeypatch.setenv(server_gateway.WORKSPACES_ENV, bad)
        assert not server_gateway.configured("ws_server_12345678")
    monkeypatch.setenv(server_gateway.WORKSPACES_ENV, "ws_server_12345678")
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: False)
    assert not server_gateway.configured("ws_server_12345678")


def test_server_snapshot_has_only_domain_flags_and_exact_workspace(monkeypatch):
    context = _context()
    monkeypatch.setattr(server_gateway, "environment", lambda: c.Environment.CANARY)
    monkeypatch.setattr(server_gateway, "configured", lambda ws="": ws == context.scope.workspace_id)
    monkeypatch.setattr(server_gateway.audit_events, "record", lambda *a, **k: "aud_" + uuid4().hex)
    snapshot = server_gateway.flag_snapshot(context)
    assert resolve(Flag.AI_TASK_GRAPH_V2, scope=context.scope, snapshot=snapshot).enabled
    assert not resolve(Flag.AI_EXECUTION_V2, scope=context.scope, snapshot=snapshot).enabled
    assert not resolve(Flag.AI_SCHEDULER_V1, scope=context.scope, snapshot=snapshot).enabled
    foreign = c.TenantScope(environment=c.Environment.CANARY, workspace_id="ws_foreign_12345678")
    assert not resolve(Flag.AI_TASK_GRAPH_V2, scope=foreign, snapshot=snapshot).enabled


def test_nonowner_domain_access_rechecks_live_session_workspace_and_capability(monkeypatch):
    identity = uuid4()
    workspace_id = "ws_personal_12345678"
    state = {"session": True, "capability": True}
    scope = {"user_id": 42, "user_uuid": str(identity), "workspace_id": workspace_id,
             "auth_session_id": "sess_live_123", "is_owner": False}
    monkeypatch.setattr(domain_gateway.preview_sandbox, "enabled", lambda: False)
    monkeypatch.setattr(live_gateway, "configured", lambda ws="": False)
    monkeypatch.setattr(server_gateway, "configured", lambda ws="": ws == workspace_id)
    monkeypatch.setattr(server_gateway, "environment", lambda: c.Environment.CANARY)
    monkeypatch.setattr(server_gateway.audit_events, "record", lambda *a, **k: "aud_" + uuid4().hex)
    monkeypatch.setattr(runtime_env, "is_server_environment", lambda: True)
    monkeypatch.setattr(domain_gateway.account_auth, "find_active_user", lambda uid: {
        "user_id": uid, "user_uuid": str(identity), "is_owner": False, "status": "active"})
    monkeypatch.setattr(domain_gateway.account_auth, "server_session_is_active",
        lambda sid, uid, identity: state["session"])
    workspace = {"workspace_id": workspace_id, "status": "active", "kind": "personal",
                 "owner_user_id": 42, "membership": {"role": "owner"}}
    monkeypatch.setattr(domain_gateway.workspaces, "require_workspace_writer", lambda uid, workspace_id: workspace)
    monkeypatch.setattr(domain_gateway.workspaces, "require_workspace_access", lambda uid, workspace_id: workspace)
    monkeypatch.setattr(domain_gateway.permissions, "resolve_for_user_id", lambda *a: {
        "capabilities": {"ai_lab": state["capability"], "ai_pro_models": True}})
    monkeypatch.setattr(domain_gateway.permissions, "enforce", lambda *a: None)
    allowed = domain_gateway.access(scope)
    assert allowed["context"].scope.environment is c.Environment.CANARY
    allowed["admit"]()
    state["session"] = False
    with pytest.raises(ContractError, match="session_expired"):
        allowed["admit"]()
    state["session"] = True
    state["capability"] = False
    with pytest.raises(ContractError, match="capability_required"):
        domain_gateway.access(scope)


def test_server_session_revalidation_checks_identity_and_device(monkeypatch):
    person = uuid4()
    monkeypatch.setattr(runtime_env, "is_server_environment", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    from app.production_storage import core
    class Connection:
        def __init__(self, state): self.state = state
        def execute(self, query, params):
            assert "s.revoked=FALSE" in query and "u.status='active'" in query
            assert params == ("sess_123", 42, str(person), str(person))
            return self
        def fetchone(self): return {"session_document": {"device_confirmation_state": self.state}}
    class Client:
        def __init__(self, state): self.state = state
        @contextmanager
        def transaction(self, scope, read_only=False):
            assert read_only
            yield Connection(self.state)
    monkeypatch.setattr(core, "PostgresClient", lambda *args, **kwargs: Client("active"))
    assert account_auth.server_session_is_active("sess_123", 42, str(person))
    monkeypatch.setattr(core, "PostgresClient", lambda *args, **kwargs: Client("pending"))
    assert not account_auth.server_session_is_active("sess_123", 42, str(person))
    assert not account_auth.server_session_is_active("sess_123", 42, "invalid-uuid")
    assert not account_auth.server_session_is_active("", 42, str(person))


def test_server_secret_is_encrypted_bound_to_owner_and_idempotent(monkeypatch):
    context = _context()
    master = base64.b64encode(b"x" * 32).decode()
    monkeypatch.setattr(server_secrets.platform_secrets, "get", lambda name: master)
    rows = {}
    class Connection:
        def execute(self, query, params):
            self.query, self.params = query, params
            if query.lstrip().startswith("INSERT"):
                rows.setdefault(str(params[3]), {"nonce": params[4], "ciphertext": params[5]})
            if query.lstrip().startswith("DELETE"):
                self.deleted = rows.pop(str(params[3]), None)
            return self
        def fetchone(self):
            if self.query.lstrip().startswith("DELETE"):
                return self.deleted
            return rows.get(str(self.params[3]))
    from app.ai_control_center import server_model_sharing
    @contextmanager
    def fake_db(context, write=False, global_read=False):
        yield Connection()
    monkeypatch.setattr(server_model_sharing, "_db", fake_db)
    store = server_secrets.ServerSecrets(None, context)
    identity = "aw_provider." + str(uuid4())
    store.set_secret(identity, "sk-example-secret")
    assert b"sk-example-secret" not in rows[identity[12:]]["ciphertext"]
    assert store.get_secret(identity) == "sk-example-secret"
    store.set_secret(identity, "sk-example-secret")
    with pytest.raises(ContractError, match="idempotency_conflict"):
        store.set_secret(identity, "sk-other-secret")
    foreign = server_secrets.ServerSecrets(None, _context(workspace="ws_foreign_12345678"))
    with pytest.raises(ContractError, match="secure_storage_unavailable"):
        foreign.get_secret(identity)


def test_model_server_admission_requires_tls_postgres_and_callback():
    context = _context()
    client = PostgresClient("postgresql://test@127.0.0.1:1/disposable?sslmode=require", production=True)
    repo = PostgresAgentWorldRepository(client, environment=c.Environment.CANARY)
    calls = []
    ModelService(repo, admit=lambda *args: calls.append(args))._access(context)
    assert calls and calls[0][0] == context
    with pytest.raises(ContractError, match="model_admission_required"):
        ModelService(repo, admit=None)._access(context)
    with pytest.raises(ContractError, match="model_server_storage_required"):
        ModelService(object(), admit=lambda *args: None)._access(context)


def test_server_model_migration_has_forced_rls_for_every_sensitive_table():
    sql = (Path(__file__).resolve().parents[1] / "app" / "production_storage" /
           "migrations" / "0024_agent_world_models.sql").read_text(encoding="utf-8").upper()
    for table in ("SF_AW_CREDENTIALS", "SF_AW_MODEL_SHARES", "SF_AW_MODEL_SHARE_EVENTS", "SF_AW_MODEL_CALLS"):
        assert "CREATE TABLE " + table in sql
        assert "ALTER TABLE " + table + " ENABLE ROW LEVEL SECURITY" in sql
        assert "ALTER TABLE " + table + " FORCE ROW LEVEL SECURITY" in sql
        assert "REVOKE ALL ON " + table + " FROM PUBLIC,STRATFORGE_APP" in sql
    assert "CIPHERTEXT BYTEA" in sql and "API_KEY TEXT" not in sql


def test_canary_uses_authoritative_budget_scope_not_development_allowance(monkeypatch):
    from app import ai_budgets
    from app.ai_lab import universal_llm
    monkeypatch.setattr(runtime_env, "is_production", lambda: False)
    monkeypatch.setattr(runtime_env, "is_canary", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    assert ai_budgets._is_prod()
    with universal_llm.usage_scope({"user_id": "42", "workspace_id": "ws_server_12345678"}):
        assert universal_llm._production_budget_scope() == {
            "user_id": 42, "workspace_id": "ws_server_12345678"}
    with universal_llm.usage_scope({"user_id": str(uuid4()), "workspace_id": "ws_server_12345678"}):
        with pytest.raises(universal_llm.BudgetExceeded):
            universal_llm._production_budget_scope()
