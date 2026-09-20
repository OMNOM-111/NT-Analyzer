"""Six contextual scopes reuse durable memory and fail closed at read/artifact boundaries."""
from datetime import timedelta
from uuid import UUID
from types import SimpleNamespace

import pytest

from app.ai_control_center import memory_policy
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_service import env, create, act, get, memory_payload, project_payload, model_service_fixture
from tests.test_agent_world_memory_http_e2e import memory_http, PUBLISHER, CONSUMER, _payload, _ok


def entry(env, scope="user", **fields):
    return create(env, "memory", memory_payload(memory_scope=scope, **fields), "memory-" + scope)["item"]


def artifact(env, item):
    record = env.repo.get(context=env.ctx, kind=EntityKind.MEMORY, entity_id=UUID(item["id"]))
    return env.repo.get_artifact_by_id(context=env.ctx, artifact_id=record.content.artifact_id)


@pytest.mark.parametrize("scope", ["user", "workspace"])
def test_default_scopes_remain_private_and_explicitly_publishable(env, scope):
    item = entry(env, scope)
    assert item["memory_scope"] == scope
    assert item["visibility"] == "private"
    assert "_memory_policy" not in item
    active = act(env, item, "memory", "promote", {"reason": "Reviewed source"})["item"]
    assert "publish_to_workspace" in active["actions"]


def test_session_current_binding_all_reads_artifact_and_ttl(env):
    authority = {"session_id": "test-session-one"}
    env.service.memory_authority = lambda ctx: authority
    item = entry(env, "session", memory_class="working", retention_days=1)
    raw = artifact(env, item)
    assert memory_policy.artifact_allowed(env.service, env.ctx, raw)
    assert item["session_bound"] is True
    assert "test-session-one" not in str(item)
    active = act(env, item, "memory", "promote", {"reason": "Reviewed source"})["item"]
    assert "publish_to_workspace" not in active["actions"]
    authority["session_id"] = "test-session-two"
    with pytest.raises(ContractError, match="memory_session_mismatch"):
        get(env, "memory", item["id"])
    assert env.service.list(context=env.ctx, admit=env.admit, domain="memory")["items"] == []
    assert memory_policy.artifact_allowed(env.service, env.ctx, raw) is None
    authority["session_id"] = "test-session-one"
    env.state.now += timedelta(days=2)
    assert memory_policy.artifact_allowed(env.service, env.ctx, raw) is None


def test_governance_permission_rechecked_and_never_shared(env):
    authority = {"governance_allowed": False}
    env.service.memory_authority = lambda ctx: authority
    with pytest.raises(ContractError, match="memory_governance_denied"):
        entry(env, "governance")
    authority["governance_allowed"] = True
    item = entry(env, "governance")
    raw = artifact(env, item)
    active = act(env, item, "memory", "promote", {"reason": "Reviewed source"})["item"]
    with pytest.raises(ContractError, match="memory_scope_not_publishable"):
        act(env, active, "memory", "publish_to_workspace", {"reason": "Attempt export"})
    authority["governance_allowed"] = False
    assert memory_policy.artifact_allowed(env.service, env.ctx, raw) is None
    with pytest.raises(ContractError, match="memory_governance_denied"):
        get(env, "memory", item["id"])


def test_strategy_revision_and_scope_immutable(env):
    project = create(env, "projects", project_payload(), "strategy-project")["item"]
    item = entry(env, "strategy", strategy_project_id=project["id"])
    assert item["scope_binding"]["strategy_project_id"] == project["id"]
    with pytest.raises(ContractError, match="memory_scope_immutable|memory_strategy_scope_required"):
        act(env, item, "memory", "update", memory_payload(memory_scope="user"))
    act(env, item, "memory", "promote", {"reason": "Verified strategy context"})
    assert not env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review")["items"]
    assert len(env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="report_review",
        strategy_project_id=project["id"])["items"]) == 1
    act(env, project, "projects", "archive")
    with pytest.raises(ContractError, match="memory_strategy_changed"):
        get(env, "memory", item["id"])


@pytest.mark.parametrize("scope,fields,code", [
    ("session", {}, "memory_session_ttl_required"),
    ("session", {"memory_class": "working", "retention_days": 1}, "memory_authenticated_session_required"),
    ("operational", {}, "memory_operational_context_required"),
    ("unknown", {}, "memory_scope_invalid"),
])
def test_invalid_context_denied(env, scope, fields, code):
    with pytest.raises(ContractError, match=code):
        entry(env, scope, **fields)


def test_session_artifact_cannot_be_laundered_as_routine_evidence(env):
    authority = {"session_id": "current-session"}
    env.service.memory_authority = lambda ctx: authority
    item = entry(env, "session", memory_class="working", retention_days=1)
    raw = artifact(env, item)
    payload = {"title": "Context leak", "description": "Not allowed", "interval_minutes": 60,
               "source_ids": [str(raw[0].artifact_id)]}
    with pytest.raises(ContractError, match="memory_context_evidence_not_exportable"):
        create(env, "routines", payload, "cannot-export-memory")
    authority["session_id"] = "next-session"
    with pytest.raises(ContractError, match="domain_evidence_unavailable"):
        create(env, "routines", payload, "cannot-export-stale-memory")


def test_http_session_binding_known_artifact_and_foreign_user(memory_http):
    env = memory_http
    item = _ok(env.mutate(PUBLISHER, None, "create", _payload(memory_scope="session", memory_class="working")))["item"]
    url = item["content_artifact_url"]
    _ok(env.request(PUBLISHER, url))
    assert env.request(CONSUMER, url).status == 404
    env.identities[PUBLISHER]["session_id"] = "different-valid-authenticated-session"
    assert env.request(PUBLISHER, url).status == 404
    listing = _ok(env.request(PUBLISHER, "domains/memory"))
    assert item["id"] not in {row["id"] for row in listing["items"]}
    assert "strategy_project_candidates" in listing and "task_candidates" in listing
    assert env.request(PUBLISHER, "domains/memory/" + item["id"]).status != 200


def test_operational_requires_owned_task_and_bounded_retrieval(env):
    model_service, ids, _ = model_service_fixture(env)
    task = model_service.start_task(context=env.ctx, model_id=ids[0], payload={"rubric_key": "json_arithmetic"},
                                   idempotency_key="operational-source-task")
    item = entry(env, "operational", memory_class="task", task_id=task["id"], purpose="error_recovery")
    assert item["scope_binding"]["task_id"] == task["id"]
    active = act(env, item, "memory", "promote", {"reason": "Reviewed operational context"})["item"]
    assert "publish_to_workspace" not in active["actions"]
    assert not env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="error_recovery")["items"]
    assert len(env.service.retrieve_memory(context=env.ctx, admit=env.admit, purpose="error_recovery",
                                          task_id=task["id"])["items"]) == 1


def test_preview_artifact_route_denies_archived_strategy_source(env, monkeypatch):
    from app.ai_control_center import http_api
    project = create(env, "projects", project_payload(), "preview-strategy-project")["item"]
    item = entry(env, "strategy", strategy_project_id=project["id"])
    reference = artifact(env, item)[0]
    monkeypatch.setattr(http_api, "_open", lambda handler: (env.ctx, None, SimpleNamespace(repository=env.repo)))
    monkeypatch.setattr(http_api.gateway, "domain_service_for", lambda handler: SimpleNamespace(service=env.service))
    responses = []
    handler = SimpleNamespace(_bytes=lambda status, *args, **kw: responses.append(status),
                              _err=lambda status, *args, **kw: responses.append(status))
    url = http_api.gateway.PREFIX + "artifacts/" + str(reference.artifact_id)
    http_api._handle_get(handler, url, {})
    assert responses.pop() == 200
    act(env, project, "projects", "archive")
    http_api._handle_get(handler, url, {})
    assert responses.pop() == 404


def test_session_update_preserves_legacy_omitted_scope_fields(env):
    env.service.memory_authority = lambda ctx: {"session_id": "unchanged-session"}
    item = entry(env, "session", memory_class="working", retention_days=1)
    updated = act(env, item, "memory", "update", memory_payload(retention_days=1))["item"]
    assert updated["memory_scope"] == "session" and updated["memory_class"] == "working"
    assert updated["session_bound"] is True
