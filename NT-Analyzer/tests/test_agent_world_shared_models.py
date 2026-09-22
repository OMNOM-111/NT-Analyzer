"""Shared model access: owning a connection and using it are separate facts.

The owner's switch lets other people *call* a connection. Key, endpoint, persona
binding and tests stay with the owner; every call names both people in one
ledger row; turning the switch off refuses the next call and removes nothing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.ai_control_center import contracts as c
from app.ai_control_center import model_sharing
from app.ai_control_center.model_execution import ModelExecutor, PrivateRegistry
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_lab import agent_registry, agent_router, universal_llm
# Collected before the suite-wide fixture stubs routing out for no-network runs.
from app.ai_lab.agent_router import candidates as routed_candidates

SECRET = "owner-secret-never-shared-0123"


class Secrets:
    def __init__(self):
        self.values = {}

    def available(self):
        return True

    def set_secret(self, key, value):
        self.values[key] = value

    def get_secret(self, key):
        return self.values.get(key)

    def delete_secret(self, key):
        return self.values.pop(key, None) is not None


def context(workspace, user):
    return c.RequestContext(scope=c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id=workspace),
                            user_uuid=user, actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=user))


def reply(text="ok", **changes):
    return {"ok": True, "response": text, "request_id": "REQ-fixture", "actual_model": "served-model",
            "elapsed_sec": .1, "cost_known": True, "cost_usd": .0003, "input_tokens": 30, "output_tokens": 12,
            **changes}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setattr(model_sharing, "_db_path", lambda: tmp_path / "sharing.sqlite3")
    owner, guest, stranger = uuid4(), uuid4(), uuid4()
    people = {str(owner): {"is_owner": True, "user_uuid": str(owner), "user_id": 1, "name": "Владелец"},
              str(guest): {"is_owner": False, "user_uuid": str(guest), "user_id": 2, "name": "Новый пользователь"},
              str(stranger): {"is_owner": False, "user_uuid": str(stranger), "user_id": 3, "name": "Третий"}}
    monkeypatch.setattr(model_sharing, "caller", lambda ctx: people.get(str((ctx or {}).get("user_id") or "")))
    repository = SQLiteAgentWorldRepository(tmp_path / "world.sqlite")
    secrets, calls, admissions = Secrets(), [], []

    def execute(**kwargs):
        calls.append(kwargs)
        # A grant, when present, is checked exactly as a real transmission would.
        kwargs["admit"](kwargs["context"], "provider_transmit", 0.0)
        return reply('{"count":3,"sum":6,"min":1,"max":3,"mean":2}')

    service = ModelService(repository, admit=lambda *args: admissions.append(args), secrets=secrets,
                           enqueue=lambda **_: None, executor=execute)
    owner_ctx = context("ws_owner_tests", owner)
    policy = service._put(owner_ctx, {"version": "test"})
    persona = service._walk(owner_ctx, service._ensure(owner_ctx, c.Persona, uuid4(), uuid4(), policy,
        display_name="Марина", profile=service._put(owner_ctx, {"description": "owner persona"})), "active")
    model = service.connect(context=owner_ctx, payload={"label": "Модель владельца", "provider": "deepseek",
        "model": "deepseek-v4-flash", "api_key": SECRET, "persona_id": str(persona.header.entity_id)},
        idempotency_key="owner-connection")
    return {"service": service, "owner": owner_ctx, "guest": context("ws_guest_tests", guest),
            "stranger": context("ws_stranger_tests", stranger), "model": model, "calls": calls,
            "admissions": admissions, "secrets": secrets}


def shared_one(world):
    service, guest = world["service"], world["guest"]
    service.set_sharing(context=world["owner"], model_id=world["model"]["id"], shared=True)
    [item] = service.shared_models(context=guest)
    return item


def guest_task(world, model_id, key="guest-task-1"):
    return world["service"].start_task(context=world["guest"], model_id=model_id,
        payload={"rubric_key": "json_arithmetic", "input_text": "[1, 2, 3]"}, idempotency_key=key,
        conversation_id="guest-thread", message_id="MSG-guest0001")


def test_nothing_is_shared_until_the_owner_turns_the_switch_on(world):
    service = world["service"]
    assert service.shared_models(context=world["guest"]) == []
    own = service.model_detail(context=world["owner"], model_id=world["model"]["id"])
    assert own["shared"] is False and own["can_share"] is True and "share" in own["actions"]
    with pytest.raises(ContractError, match="not_found"):
        guest_task(world, world["model"]["id"])


def test_a_shared_model_shows_its_name_and_nothing_of_the_connection(world):
    item = shared_one(world)
    assert item["ownership"] == "shared" and item["execution_available"] is True
    assert item["title"] == "Модель владельца" and item["model"] == "deepseek-v4-flash"
    # The caller holds an id of their own; the owner's connection id, account,
    # endpoint, persona and key never reach them.
    text = json.dumps(item, ensure_ascii=False)
    for private in (world["model"]["id"], world["model"]["provider_account_id"], world["model"]["persona_id"],
                    world["model"]["base_url"], SECRET):
        assert private not in text
    assert world["model"]["id"] not in json.dumps(world["service"].models(context=world["guest"]))


def test_a_new_user_without_models_works_through_the_shared_one(world):
    service, guest, owner = world["service"], world["guest"], world["owner"]
    item = shared_one(world)
    assert service.models(context=guest)["items"] == []
    task = guest_task(world, item["id"])
    done = service.execute(context=guest, task_id=task["id"])
    assert done["status"] == "succeeded" and done["model_id"] == item["id"]
    # The executor ran on the owner's connection, under a grant, for the guest.
    [call] = world["calls"]
    assert call["context"] == guest and str(call["model"].header.entity_id) == world["model"]["id"]
    assert call["shared"].share["model_id"] == world["model"]["id"] and call["acting_agent"] == "Общая модель"
    # Using a shared connection needs AI access, not the right to own models.
    assert {args[1] for args in world["admissions"] if args[0] == guest} >= {"shared_task", "shared_execute",
                                                                            "shared_provider_transmit"}
    # The work is the guest's: their task list has it, the owner's does not.
    assert [row["id"] for row in service.tasks(context=guest)["items"]] == [task["id"]]
    assert service.tasks(context=owner)["items"] == []
    with pytest.raises(ContractError, match="not_found"):
        service.task_detail(context=owner, task_id=task["id"])


def test_a_shared_model_answers_direct_requests_only(world):
    service, guest = world["service"], world["guest"]
    item = shared_one(world)
    with pytest.raises(ContractError, match="share_action_not_allowed"):
        service.test(context=guest, model_id=item["id"], idempotency_key="guest-probe-1")
    for action in (service.disconnect, lambda **kw: service.set_sharing(**kw, shared=False)):
        with pytest.raises(ContractError):
            action(context=guest, model_id=item["id"])
    # The owner's own id is refused outright, even while the share is on.
    with pytest.raises(ContractError, match="not_found"):
        guest_task(world, world["model"]["id"])


def test_share_off_blocks_the_next_call_and_keeps_all_history(world):
    service, guest, owner = world["service"], world["guest"], world["owner"]
    item = shared_one(world)
    first = service.execute(context=guest, task_id=guest_task(world, item["id"])["id"])
    queued = guest_task(world, item["id"], key="guest-task-queued")
    service.set_sharing(context=owner, model_id=world["model"]["id"], shared=False)
    # A new request is refused at once.
    with pytest.raises(ContractError, match="share_revoked"):
        guest_task(world, item["id"], key="guest-task-after")
    # One already queued is refused before anything is transmitted.
    blocked = service.execute(context=guest, task_id=queued["id"])
    assert blocked["status"] == "blocked" and blocked["error_code"] == "model_share_revoked"
    assert len(world["calls"]) == 1
    # Nothing is deleted: the finished task and the closed model stay visible.
    assert service.task_detail(context=guest, task_id=first["id"])["status"] == "succeeded"
    [closed] = service.shared_models(context=guest)
    assert closed["shared_access"] == "revoked" and closed["execution_available"] is False and closed["actions"] == []
    assert [event["shared"] for event in model_sharing.history(world["model"]["id"])] == [True, False]
    # The owner keeps full use of their own connection.
    assert service.model_detail(context=owner, model_id=world["model"]["id"])["status"] == "active"


def test_share_off_between_admission_and_transmission_stops_the_call(world):
    service, guest, owner = world["service"], world["guest"], world["owner"]
    item = shared_one(world)
    task = guest_task(world, item["id"])
    original = service.admit

    def revoke_on_transmit(ctx, operation, *rest):
        original(ctx, operation, *rest)
        if operation == "shared_provider_transmit" and ctx == guest:
            model_sharing.set_shared(environment="development", owner_workspace_id="ws_owner_tests",
                owner_user_uuid=str(owner.user_uuid), model_id=world["model"]["id"], shared=False,
                label="x", provider="deepseek", model_key="deepseek-v4-flash", credential_source="user_supplied")
    service.admit = revoke_on_transmit
    result = service.execute(context=guest, task_id=task["id"])
    assert result["status"] == "failed" and result["error_code"] == "model_share_revoked"
    assert not world["calls"]


def test_disconnecting_a_connection_closes_its_share(world):
    service = world["service"]
    shared_one(world)
    service.disconnect(context=world["owner"], model_id=world["model"]["id"])
    assert model_sharing.get(world["model"]["id"])["shared"] is False
    with pytest.raises(ContractError, match="connection_inactive"):
        service.set_sharing(context=world["owner"], model_id=world["model"]["id"], shared=True)


def test_other_people_never_see_each_others_work_through_one_share(world):
    service, guest, stranger = world["service"], world["guest"], world["stranger"]
    item = shared_one(world)
    [theirs] = service.shared_models(context=stranger)
    assert theirs["id"] != item["id"]
    task = guest_task(world, item["id"])
    assert service.tasks(context=stranger)["items"] == []
    with pytest.raises(ContractError, match="not_found"):
        service.task_detail(context=stranger, task_id=task["id"])
    # Nor can one person run a task on another person's projection.
    with pytest.raises(ContractError):
        service.start_task(context=stranger, model_id=item["id"], payload={"rubric_key": "json_arithmetic",
            "input_text": "[1, 2, 3]"}, idempotency_key="stranger-task-1")


def _real_call(world, monkeypatch, ctx, request_id):
    """One call through the real executor and client, with the transport mocked."""
    service = world["service"]
    target = service._shared_target(ctx, service.shared_models(context=ctx)[0]["id"]) if ctx != world["owner"] else None
    grant = service._grant(ctx, target[0]) if target else None
    model, account, profile = service._owner_connection(ctx, model_sharing.get(world["model"]["id"]))
    seen = []
    monkeypatch.setattr(universal_llm, "_request_json", lambda *a, **kw: seen.append(kw) or {
        "model": "deepseek-v4-flash", "usage": {"prompt_tokens": 40, "completion_tokens": 9},
        "choices": [{"message": {"content": "CONNECTION_OK"}}]})
    usage = world.setdefault("usage", [])
    executor = ModelExecutor(budget_limits=lambda *_: {"daily_budget_usd": .1, "monthly_budget_usd": .2},
        secrets=world["secrets"], usage_reader=lambda **_: list(usage), usage_writer=usage.append)
    result = executor(context=ctx, model=model, account=account, profile=profile, prompt="Reply CONNECTION_OK",
        system_prompt="Bounded", request_id=request_id, conversation_id="thread", max_output_tokens=64,
        purpose="agent_world_capability", cancelled=None, admit=lambda *_: None, shared=grant,
        acting_agent="Помощник гостя" if grant else None)
    return result, seen


def test_usage_is_recorded_for_the_caller_and_for_the_connection_owner(world, monkeypatch):
    service, guest, owner = world["service"], world["guest"], world["owner"]
    shared_one(world)
    result, seen = _real_call(world, monkeypatch, guest, "guest-call-1")
    assert result["ok"] and seen[0]["secret"] == SECRET
    _real_call(world, monkeypatch, owner, "owner-own-call")
    # The provider ledger attributes each call to whoever made it.
    assert [row["user_id"] for row in world["usage"]] == [str(guest.user_uuid), str(owner.user_uuid)]
    assert SECRET not in json.dumps(world["usage"])
    # The owner sees other people's use apart from their own requests.
    by_others = service.shared_usage(context=owner)["by_others"]
    assert by_others["total"]["calls"] == 1
    [row] = by_others["by_caller"]
    assert row["caller_name"] == "Новый пользователь" and row["model_label"] == "Модель владельца"
    assert row["input_tokens"] == 40 and row["output_tokens"] == 9 and row["cost_usd"] > 0
    [recent] = by_others["recent"]
    assert recent["task"] == "guest-call-1" and recent["agent"] == "Помощник гостя"
    # The caller sees what they spent, under their own id for the model.
    mine = service.shared_usage(context=guest)["mine_through_others"]
    assert mine["total"]["calls"] == 1
    assert mine["by_model"][0]["model_id"] == service.shared_models(context=guest)[0]["id"]
    assert world["model"]["id"] not in json.dumps(service.shared_usage(context=guest))
    # And neither sees the other's chats: the ledger holds no prompt or reply.
    assert "CONNECTION_OK" not in json.dumps(service.shared_usage(context=owner), ensure_ascii=False)


def test_the_connection_limits_count_every_callers_spend(world):
    service, owner = world["service"], world["owner"]
    model, account, profile = service._owner_connection(owner, {"owner_user_uuid": str(owner.user_uuid),
        "owner_workspace_id": "ws_owner_tests", "model_id": world["model"]["id"]})
    agent_id = "aw_model." + world["model"]["id"]
    rows = [{"agent_id": agent_id, "workspace_id": "ws_guest_tests", "user_id": str(world["guest"].user_uuid),
             "timestamp_utc": datetime.now(timezone.utc).isoformat(), "cost_usd": .1}]
    adapter = PrivateRegistry(context=owner, model=model, account=account, profile=profile,
        limits={"daily_budget_usd": .1, "monthly_budget_usd": .2}, secrets=world["secrets"],
        revalidate=lambda: None, usage_reader=lambda **_: rows)
    # The guest's spend through the share is the owner's money: it counts.
    with universal_llm.registry_scope(adapter), pytest.raises(universal_llm.BudgetExceeded):
        universal_llm._reserve(adapter.get_agent(agent_id), .001, allow_disabled=False)


def test_a_shared_owner_binding_is_allowed_by_the_grant_not_by_the_caller(world, monkeypatch):
    service, owner, guest = world["service"], world["owner"], world["guest"]
    configured = {"id": "AGT-SHAREDOWNER1", "name": "Owner registry model", "provider": "deepseek",
                  "model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com", "pricing_status": "configured",
                  "enabled": True, "key_configured": True, "endpoint_type": "chat"}
    persona = world["model"]["persona_id"]
    bound = service.bind_existing_model(context=owner, payload={"registry_id": configured["id"], "persona_id": persona},
        idempotency_key="owner-binding-share", resolve_binding=lambda *a: configured)
    service.set_sharing(context=owner, model_id=bound["id"], shared=True)
    monkeypatch.setattr(agent_registry, "get_agent", lambda identity: dict(configured))
    model, account, profile = service._owner_connection(guest, model_sharing.get(bound["id"]))
    grant = model_sharing.Grant(model_sharing.get(bound["id"]), caller_user_uuid=str(guest.user_uuid))
    seen = []

    def invoke(identity, **kwargs):
        kwargs["check"]()
        seen.append(identity)
        return reply("CONNECTION_OK")
    executor = ModelExecutor(budget_limits=lambda *_: pytest.fail("owner caps stay"),
                             owner_binding=lambda *a: pytest.fail("the caller is not the owner"))
    monkeypatch.setattr(executor, "_call", invoke)
    arguments = dict(context=guest, model=model, account=account, profile=profile, prompt="p", system_prompt="s",
        request_id="guest-binding-call", conversation_id="t", max_output_tokens=64, purpose="agent_world_capability",
        cancelled=None, admit=lambda *a: None, shared=grant)
    assert executor(**arguments)["ok"] and seen == [configured["id"]]
    service.set_sharing(context=owner, model_id=bound["id"], shared=False)
    with pytest.raises(ContractError, match="share_revoked"):
        executor(**arguments)
    assert seen == [configured["id"]]


def test_the_owners_registry_is_closed_to_other_people_unless_shared(world, monkeypatch):
    service, owner, guest = world["service"], world["owner"], world["guest"]
    rows = [{"id": "AGT-PRIVATEONLY1", "name": "Private", "provider": "deepseek", "model": "deepseek-v4-pro",
             "key_configured": True, "endpoint_type": "chat", "enabled": True, "role": "general"},
            {"id": "AGT-SHAREDONE01", "name": "Shared", "provider": "deepseek", "model": "deepseek-v4-flash",
             "key_configured": True, "endpoint_type": "chat", "enabled": True, "role": "general"}]
    monkeypatch.setattr(agent_router, "candidates", routed_candidates)
    monkeypatch.setattr(agent_registry, "list_agents", lambda: [dict(row) for row in rows])
    monkeypatch.setattr(agent_registry, "get_agent", lambda identity, public=True: dict(next(
        row for row in rows if row["id"] == identity)))
    configured = {**rows[1], "base_url": "https://api.deepseek.com", "pricing_status": "configured"}
    bound = service.bind_existing_model(context=owner, payload={"registry_id": rows[1]["id"],
        "persona_id": world["model"]["persona_id"]}, idempotency_key="owner-binding-gate", resolve_binding=lambda *a: configured)
    with universal_llm.usage_scope({"user_id": str(guest.user_uuid), "workspace_id": "ws_guest_tests"}):
        assert agent_router.candidates("general") == []
        with pytest.raises(universal_llm.UniversalLLMError, match="общего доступа"):
            universal_llm.invoke_agent("AGT-PRIVATEONLY1", "hello")
        service.set_sharing(context=owner, model_id=bound["id"], shared=True)
        assert [row["id"] for row in agent_router.candidates("general")] == ["AGT-SHAREDONE01"]
        with pytest.raises(universal_llm.UniversalLLMError, match="общего доступа"):
            universal_llm.invoke_agent("AGT-PRIVATEONLY1", "hello")
    # The owner, and the platform's own unattributed work, keep the full registry.
    for scope in ({"user_id": str(owner.user_uuid)}, {}):
        with universal_llm.usage_scope(scope):
            assert len(agent_router.candidates("general")) == 2


def test_a_registry_call_by_somebody_else_is_written_to_the_owners_ledger(world):
    service, owner, guest = world["service"], world["owner"], world["guest"]
    configured = {"id": "AGT-LEDGERROW01", "name": "Owner registry model", "provider": "deepseek",
                  "model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com", "pricing_status": "configured"}
    bound = service.bind_existing_model(context=owner, payload={"registry_id": configured["id"],
        "persona_id": world["model"]["persona_id"]}, idempotency_key="owner-binding-ledger", resolve_binding=lambda *a: configured)
    service.set_sharing(context=owner, model_id=bound["id"], shared=True)
    row = {"request_id": "REQ-LEDGER0001", "agent_id": configured["id"], "request_role": "orchestrator",
           "purpose": "orchestrator_chat_plan", "status": "success", "input_tokens": 100, "output_tokens": 20,
           "cost_usd": .002, "cost_known": True, "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    for person in (guest, owner):
        model_sharing.observe({**row, "request_id": row["request_id"] + str(person.user_uuid)[:4]},
                              {"user_id": str(person.user_uuid), "workspace_id": person.scope.workspace_id,
                               "conversation_id": "thread-1"})
    usage = service.shared_usage(context=owner)["by_others"]
    assert usage["total"]["calls"] == 1 and usage["by_caller"][0]["caller_name"] == "Новый пользователь"
    assert usage["recent"][0]["task"] == "thread-1" and usage["recent"][0]["agent"] == "orchestrator"


def test_the_rule_applies_to_local_development_only_for_now(world, monkeypatch):
    """Canary and Production keep their existing budgets and allocation untouched."""
    from app import runtime_env
    usage = {"user_id": str(world["guest"].user_uuid), "workspace_id": "ws_guest_tests"}
    assert model_sharing.registry_filter(usage) == set()
    monkeypatch.setattr(runtime_env, "is_development", lambda: False)
    assert model_sharing.registry_filter(usage) is None
    assert model_sharing.registry_allowed("AGT-ANYTHING0001", usage) is True


def test_only_the_owner_of_a_connection_can_switch_it(world):
    service = world["service"]
    for person in (world["guest"], world["stranger"]):
        with pytest.raises(ContractError, match="not_found"):
            service.set_sharing(context=person, model_id=world["model"]["id"], shared=True)
    with pytest.raises(ContractError, match="owner_mismatch"):
        service.set_sharing(context=world["owner"], model_id=world["model"]["id"], shared=True)
        model_sharing.set_shared(environment="development", owner_workspace_id="ws_guest_tests",
            owner_user_uuid=str(world["guest"].user_uuid), model_id=world["model"]["id"], shared=False,
            label="x", provider="x", model_key="x", credential_source="x")


def test_a_shared_call_needs_ai_access_not_the_right_to_own_models(monkeypatch):
    from app.ai_control_center import domain_gateway
    ctx = context("ws_guest_tests", uuid4())
    capabilities = {"ai_lab": True, "ai_pro_models": False}
    authorized = {"admit": lambda: None, "context": ctx, "read_only": False,
                  "refresh": lambda **_: {"chat_scope": {"capabilities": capabilities}}}
    monkeypatch.setattr(domain_gateway.ai_budgets, "check_budget", lambda *_: {"ok": True})
    domain_gateway._model_admit(authorized, ctx, "shared_task", 0.0)
    with pytest.raises(ContractError, match="capability_required"):
        domain_gateway._model_admit(authorized, ctx, "task", 0.0)
    capabilities["ai_lab"] = False
    with pytest.raises(ContractError, match="capability_required"):
        domain_gateway._model_admit(authorized, ctx, "shared_task", 0.0)
    # The caller's own AI budget still applies to shared calls.
    capabilities["ai_lab"] = True
    monkeypatch.setattr(domain_gateway.ai_budgets, "check_budget", lambda *_: {"ok": False})
    with pytest.raises(ContractError, match="budget_exhausted"):
        domain_gateway._model_admit(authorized, ctx, "shared_task", 0.0)


def test_a_persona_without_its_own_connection_speaks_through_a_shared_one(world):
    from app.ai_control_center import persona_identity
    service, guest = world["service"], world["guest"]
    policy = service._put(guest, {"version": "test"})
    persona = service._walk(guest, service._ensure(guest, c.Persona, uuid4(), uuid4(), policy,
        display_name="Помощник гостя", profile=service._put(guest, {"description": "guest persona"})), "active")
    with pytest.raises(ContractError, match="persona_model_required"):
        persona_identity.select_model(service, context=guest, persona_id=str(persona.header.entity_id))
    item = shared_one(world)
    chosen = persona_identity.select_model(service, context=guest, persona_id=str(persona.header.entity_id))
    assert chosen == item["id"]
    task = service.start_task(context=guest, model_id=chosen, payload={"rubric_key": "assistant_response",
        "input_text": "Привет"}, idempotency_key="guest-persona-1", conversation_id="thread", message_id="MSG-guest0002",
        _persona=persona.ref(), _model_selection={"mode": "shared_available", "selected_model_id": None})
    assert task["persona_id"] == str(persona.header.entity_id)
    assert task["title"].startswith("Помощник гостя")
    done = service.execute(context=guest, task_id=task["id"])
    assert done["status"] in {"succeeded", "review"} and world["calls"][0]["acting_agent"] == "Помощник гостя"
    # An application plan never runs on somebody else's connection.
    with pytest.raises(ContractError, match="persona_application_role_mismatch|persona_model_required"):
        persona_identity.select_model(service, context=guest, persona_id=str(persona.header.entity_id), kind="chart")


# -- the whole scenario through the real gateway ------------------------------


@pytest.fixture
def two_accounts(monkeypatch, tmp_path):
    """Owner and a brand-new user, each in their own workspace, real gateway."""
    from app.ai_control_center import domain_gateway as gateway
    from app.ai_control_center import test_executor
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("STRATFORGE_DEVELOPMENT_DATA_ROOT", str(tmp_path / "development"))
    monkeypatch.setenv("STRATFORGE_DATA_ROOT", str(tmp_path / "production-disabled"))
    monkeypatch.setenv("NT_ANALYZER_SQLITE_PATH", str(tmp_path / "durable.sqlite3"))
    monkeypatch.setattr(model_sharing, "_db_path", lambda: tmp_path / "sharing.sqlite3")
    owner_ws, guest_ws = "ws_scenario_owner", "ws_scenario_guest"
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_LOCAL_WORKSPACES", owner_ws + "," + guest_ws)
    monkeypatch.setenv("STRATFORGE_AGENT_WORLD_TEST_EXECUTOR", owner_ws + "," + guest_ws)
    monkeypatch.setattr(gateway, "_SNAPSHOTS", {}, raising=False)
    # The chat store is a live directory unless a test points it at its own root.
    from app.ai_lab import chief_agent
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", tmp_path / "chat-registry")
    owner_id, guest_id = 501, 502
    owner_uuid, guest_uuid = "12000000-0000-4000-8000-000000000501", "12000000-0000-4000-8000-000000000502"
    people = {owner_id: {"user_id": owner_id, "user_uuid": owner_uuid, "is_owner": True, "status": "active",
                         "display_name": "Владелец"},
              guest_id: {"user_id": guest_id, "user_uuid": guest_uuid, "is_owner": False, "status": "active",
                         "display_name": "Новый пользователь"}}
    spaces = {owner_ws: owner_id, guest_ws: guest_id}
    capabilities = {owner_id: {"ai_lab": True, "ai_pro_models": True}, guest_id: {"ai_lab": True}}

    def find_user(uid):
        return dict(people.get(int(uid), {})) or None

    def workspace(uid, *, workspace_id):
        if workspace_id not in spaces or spaces[workspace_id] != int(uid):
            raise gateway.workspaces.WorkspaceError("Not a member", 403)
        return {"workspace_id": workspace_id, "owner_user_id": int(uid), "status": "active",
                "uses_owner_runtime": people[int(uid)]["is_owner"], "kind": "personal",
                "membership": {"role": "owner"}}

    monkeypatch.setattr(gateway.account_auth, "find_active_user", find_user)
    monkeypatch.setattr(gateway.account_auth, "find_active_user_by_uuid",
                        lambda value: next((dict(row) for row in people.values() if row["user_uuid"] == str(value)), None))
    monkeypatch.setattr(gateway.workspaces, "require_workspace_writer", workspace)
    monkeypatch.setattr(gateway.workspaces, "require_workspace_access", workspace)
    monkeypatch.setattr(gateway.permissions, "resolve_for_user_id",
                        lambda uid, user: {"role": "owner" if people[int(uid)]["is_owner"] else "member",
                                           "capabilities": dict(capabilities[int(uid)])})
    monkeypatch.setattr(gateway.permissions, "enforce", lambda *a, **kw: None)
    # A person who is not the owner reaches Agent World only with a confirmed session.
    monkeypatch.setattr(gateway.account_auth, "local_session_is_active",
                        lambda session_id, uid: session_id == "sess_guest_scenario" and int(uid) == guest_id)
    monkeypatch.setattr(gateway.ai_budgets, "check_budget", lambda *a: {"ok": True})
    assert test_executor.enabled(guest_ws)

    def scope(uid, workspace_id):
        return {"user_id": uid, "user_uuid": people[uid]["user_uuid"], "workspace_id": workspace_id,
                "display_name": people[uid]["display_name"],
                "auth_session_id": "" if people[uid]["is_owner"] else "sess_guest_scenario"}

    return {"gateway": gateway, "owner": scope(owner_id, owner_ws), "guest": scope(guest_id, guest_ws),
            "capabilities": capabilities, "guest_id": guest_id}


def scenario_connect(gateway, owner):
    """The owner connects one model of their own, the way the page does."""
    authorized = gateway.access(owner)
    service = gateway.models(authorized)
    context = authorized["context"]
    policy = service._put(context, {"version": "scenario"})
    persona = service._walk(context, service._ensure(context, c.Persona, uuid4(), uuid4(), policy,
        display_name="Марина", profile=service._put(context, {"description": "owner persona"})), "active")
    return gateway.mutate(authorized, "models", "new", "connect", {"idempotency_key": "scenario-connect",
        "payload": {"label": "Модель владельца", "provider": "deepseek", "model": "deepseek-v4-flash",
                    "api_key": SECRET, "persona_id": str(persona.header.entity_id)}})


def test_the_whole_scenario_owner_shares_new_user_works_owner_stops_it(two_accounts):
    gateway, owner, guest = two_accounts["gateway"], two_accounts["owner"], two_accounts["guest"]
    model = scenario_connect(gateway, owner)
    # 1. A new user without models of their own sees nothing yet.
    listing = gateway.list_domain(gateway.access(guest, read_only=True), "models")
    assert listing["items"] == [] and listing["shared"] == []
    # 2. The owner shares one connection with the switch on its card.
    shared = gateway.mutate(gateway.access(owner), "models", model["id"], "share",
                            {"idempotency_key": "scenario-share-on", "payload": {}})
    assert shared["shared"] is True and "unshare" in shared["actions"]
    # 3. The new user now sees it as a shared model, with nothing of the connection.
    listing = gateway.list_domain(gateway.access(guest, read_only=True), "models")
    [offered] = listing["shared"]
    assert offered["ownership"] == "shared" and offered["execution_available"] is True
    assert SECRET not in json.dumps(listing) and model["id"] not in json.dumps(listing)
    # 4. And can work through it: a task of their own, in their own workspace.
    task = gateway.mutate(gateway.access(guest), "models", offered["id"], "task",
        {"idempotency_key": "scenario-guest-task", "payload": {"rubric_key": "json_arithmetic",
                                                               "input_text": "[4, 5, 6]"}})
    authorized = gateway.access(guest)
    done = gateway.models(authorized).execute(context=authorized["context"], task_id=task["id"])
    assert done["status"] == "succeeded" and done["model_id"] == offered["id"]
    assert gateway.list_domain(gateway.access(owner, read_only=True), "model_tasks")["items"] == []
    # 5. The owner turns sharing off: new calls stop, the history stays.
    closed = gateway.mutate(gateway.access(owner), "models", model["id"], "unshare",
                            {"idempotency_key": "scenario-share-off", "payload": {}})
    assert closed["shared"] is False
    with pytest.raises(ContractError, match="share_revoked"):
        gateway.mutate(gateway.access(guest), "models", offered["id"], "task",
            {"idempotency_key": "scenario-guest-after", "payload": {"rubric_key": "json_arithmetic",
                                                                   "input_text": "[7, 8, 9]"}})
    after = gateway.list_domain(gateway.access(guest, read_only=True), "models")
    assert after["shared"][0]["shared_access"] == "revoked"
    assert gateway.list_domain(gateway.access(guest, read_only=True), "model_tasks")["items"][0]["id"] == task["id"]


def test_a_user_without_ai_access_cannot_reach_a_shared_model(two_accounts):
    gateway, owner, guest = two_accounts["gateway"], two_accounts["owner"], two_accounts["guest"]
    model = scenario_connect(gateway, owner)
    gateway.mutate(gateway.access(owner), "models", model["id"], "share",
                   {"idempotency_key": "scenario-share-cap", "payload": {}})
    offered = gateway.list_domain(gateway.access(guest, read_only=True), "models")["shared"][0]
    two_accounts["capabilities"][two_accounts["guest_id"]] = {}
    with pytest.raises(ContractError):
        gateway.mutate(gateway.access(guest), "models", offered["id"], "task",
            {"idempotency_key": "scenario-guest-nocap", "payload": {"rubric_key": "json_arithmetic",
                                                                    "input_text": "[1, 2, 3]"}})
