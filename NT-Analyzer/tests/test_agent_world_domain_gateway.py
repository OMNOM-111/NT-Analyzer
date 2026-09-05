"""Own-workspace facade, server authority and same-store chat contracts.

Only disposable SQLite and in-memory provider/queue/chat boundaries are used.
No global credentials, real provider request, NinjaTrader or owner runtime IO.
The existing Handler's JSON/origin/CSRF checks execute without a browser.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import server, worker_router
from app.ai_lab import agent_registry, chief_agent
from app.ai_control_center import contracts as c
from app.ai_control_center import domain_gateway as gateway, live_http_api as http_api, model_chat
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.flags import Flag, resolve
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError
from tests.test_agent_world_live_gateway import (
    USER_ID, USER_UUID, WORKSPACE, OTHER_WORKSPACE, isolated_runtime, owner,
)
from tests.test_agent_world_models import Secrets, response


CSRF = "isolated-domain-contract-csrf"
REGISTRY_ID = "AGT-ABCDEFGHIJKL"


@pytest.fixture
def ordinary(owner, monkeypatch):
    owner.state["user"]["is_owner"] = False
    owner.state["workspaces"][WORKSPACE]["uses_owner_runtime"] = False
    owner.state["permissions"]["role"] = "full_control"
    owner.state["permissions"]["capabilities"]["ai_pro_models"] = True
    owner.scope.update(is_owner=False, uses_owner_runtime=False,
                       auth_session_id="confirmed-domain-session")
    owner.state["session_active"] = True
    monkeypatch.setattr(gateway.account_auth, "local_session_is_active",
                        lambda session, uid: session == "confirmed-domain-session"
                        and uid == USER_ID and owner.state["session_active"])
    return owner


class Handler:
    """Small transport boundary using the unmodified Handler security methods."""

    _check_local_post = server.Handler._check_local_post
    _check_local_origin = server.Handler._check_local_origin
    _request_hostname = staticmethod(server.Handler._request_hostname)

    def __init__(self, account, body=None, *, csrf=CSRF, origin="http://127.0.0.1:55440"):
        self.scope = copy.deepcopy(account.scope)
        self._remote_context = {
            "source": "local" if account.scope["is_owner"] else "app",
            "is_owner": account.scope["is_owner"],
            "role": account.state["permissions"]["role"],
            "device_confirmation_state": "active",
            "session_id": account.scope.get("auth_session_id"),
            "csrf_hash": hashlib.sha256(CSRF.encode()).hexdigest(),
        }
        self.headers = {"Content-Type": "application/json", "Host": "127.0.0.1:55440"}
        if csrf is not None:
            self.headers["X-CSRF-Token"] = csrf
        if origin is not None:
            self.headers["Origin"] = origin
        self.server = SimpleNamespace(server_address=("127.0.0.1", 55440))
        self.body, self.body_reads, self.status, self.result = body, 0, None, None

    def _ai_conversation_scope(self):
        return copy.deepcopy(self.scope)

    def _read_body(self):
        self.body_reads += 1
        return copy.deepcopy(self.body)

    def _json(self, status, value):
        self.status, self.result = int(status), value

    def _err(self, status, message, *, code=None):
        self.status, self.result = int(status), {"error": message, "code": code}


def http_get(account, route, query=None):
    handler = Handler(account)
    http_api.handle_get(handler, gateway.live_gateway.PREFIX + route, query or {})
    return handler


def http_post(account, route, payload, **options):
    handler = Handler(account, payload, **options)
    http_api.handle_post(handler, gateway.live_gateway.PREFIX + route)
    return handler


@pytest.fixture
def models(ordinary, tmp_path, monkeypatch):
    authorized = gateway.access(ordinary.scope)
    context = authorized["context"]
    repository = SQLiteAgentWorldRepository(tmp_path / "domain-contracts.sqlite")
    secrets, executions, queue, chat, chat_calls = Secrets(), [], {}, {}, []

    def execute(**kwargs):
        executions.append(kwargs)
        return response("CONNECTION_OK" if kwargs["purpose"] == "connection_test" else
                        '{"count":4,"sum":34,"min":-4,"max":17,"mean":8.5}')

    def enqueue(kind, payload, **options):
        key = options["job_id"]
        if key in queue:
            raise sqlite3.IntegrityError("duplicate job_id")
        queue[key] = {"id": key, "kind": kind, "payload": copy.deepcopy(payload),
                      "status": "queued", **options}
        return copy.deepcopy(queue[key])

    def get_queue(identity, *, workspace_id):
        row = queue.get(identity)
        return copy.deepcopy(row) if row and row["workspace_id"] == workspace_id else None

    def make_service(auth, repo=None):
        return ModelService(repo or repository, secrets=secrets, executor=execute,
            admit=lambda context, operation, estimate: gateway._model_admit(auth, context, operation, estimate),
            enqueue=lambda **kwargs: gateway.enqueue_model(auth, **kwargs))

    service = make_service(authorized)
    monkeypatch.setattr(gateway, "models", make_service)
    monkeypatch.setattr(worker_router, "enqueue", enqueue)
    monkeypatch.setattr(worker_router, "get", get_queue)
    monkeypatch.setattr(worker_router, "cancel", lambda identity, **scope: queue.get(identity))
    monkeypatch.setattr(agent_registry, "list_agents", lambda: pytest.fail("ordinary user enumerated global registry"))
    monkeypatch.setattr(agent_registry, "get_agent", lambda identity: pytest.fail("ordinary user read owner registry"))

    def create_conversation(title, *, conversation_id, scope):
        assert scope == authorized["chat_scope"]
        chat.setdefault(conversation_id, {"title": title, "messages": {}})
        return {"conversation_id": conversation_id}

    def run_request(**kwargs):
        assert kwargs["scope"] == authorized["chat_scope"]
        assert kwargs["domain_request"] is True and kwargs["include_message_identity"] is True
        chat_calls.append({key: value for key, value in kwargs.items() if key != "execute"})
        messages = chat[kwargs["conversation_id"]]["messages"]
        key = kwargs["request_id"]
        if key not in messages:
            envelope = kwargs["execute"]("msg-" + hashlib.sha256(key.encode()).hexdigest()[:24])
            messages[key] = {"actions": [{"task_id": envelope["task_id"]}], "envelope": envelope}
        return messages[key]

    monkeypatch.setattr(chief_agent, "create_conversation", create_conversation)
    monkeypatch.setattr(chief_agent, "run_agent_world_live_request", run_request)
    policy = service._put(context, {"version": "test-only", "synthetic": True})
    persona = service._ensure(context, c.Persona, uuid4(), uuid4(), policy, display_name="Fixture Persona",
        profile=service._put(context, {"description": "disposable contract test persona"}))
    persona = service._walk(context, persona, "active")
    payload = {"label": "Fixture private model", "provider": "deepseek", "model": "deepseek-v4-flash",
        "api_key": "must-stay-in-memory-secret", "persona_id": str(persona.header.entity_id)}
    model = service.connect(context=context, payload=payload, idempotency_key="fixture-connect-model")
    return SimpleNamespace(account=ordinary, authorized=authorized, context=context, service=service,
        repository=repository, model=model, payload=payload, secrets=secrets, executions=executions,
        queue=queue, chat=chat, chat_calls=chat_calls)


def test_ordinary_personal_workspace_uses_fresh_scope_not_caller_permissions(ordinary):
    authorized = gateway.access({**ordinary.scope, "is_owner": True, "uses_owner_runtime": True,
                                 "capabilities": {"trade": True}, "runtime_dir": "foreign"})
    assert authorized["context"].user_uuid == UUID(USER_UUID)
    assert authorized["source_scope"] == {"workspace_id": WORKSPACE, "user_id": USER_ID, "allow_legacy": False}
    assert authorized["chat_scope"]["is_owner"] is False
    assert authorized["chat_scope"]["uses_owner_runtime"] is False
    assert "trade" not in authorized["chat_scope"]["capabilities"]
    assert "runtime_dir" not in authorized["chat_scope"]
    assert ordinary.calls["budget"] == []  # reading is not a paid request


@pytest.mark.parametrize("change", [
    {"owner_user_id": USER_ID + 1}, {"membership": {"role": "admin"}},
    {"membership": {"role": "viewer"}}, {"status": "archived"},
])
def test_ordinary_writer_is_not_enough_without_own_workspace(ordinary, change):
    ordinary.state["workspaces"][WORKSPACE].update(change)
    with pytest.raises(ContractError, match="own_workspace_required"):
        gateway.access(ordinary.scope)


@pytest.mark.parametrize("mode", ["no_session", "expired_session", "revoked", "foreign_user", "preview", "off"])
def test_ordinary_authority_is_revalidated_on_each_admission(ordinary, monkeypatch, mode):
    authorized = gateway.access(ordinary.scope)
    if mode == "no_session":
        authorized["chat_scope"].pop("auth_session_id")
    elif mode == "expired_session":
        ordinary.state["session_active"] = False
    elif mode == "revoked":
        ordinary.state["permission_denied"] = True
    elif mode == "foreign_user":
        ordinary.state["user"]["user_uuid"] = str(uuid4())
    elif mode == "preview":
        monkeypatch.setenv("STRATFORGE_PREVIEW_SANDBOX", "1")
        monkeypatch.setenv("STRATFORGE_PREVIEW_ID", "ac" * 12)
    else:
        monkeypatch.delenv(gateway.live_gateway.WORKSPACES_ENV)
    with pytest.raises((ContractError, gateway.permissions.PermissionError)):
        authorized["admit"]()


@pytest.mark.parametrize("changes", [
    {"role": "read_only"}, {"source": "app", "device_confirmation_state": "pending"},
    {"source": "app", "session_id": ""}, {"source": "local", "is_owner": False},
])
def test_handler_denies_unconfirmed_device_or_untrusted_local_identity(ordinary, changes):
    handler = Handler(ordinary)
    handler._remote_context.update(changes)
    if changes.get("session_id") == "":
        handler.scope.pop("auth_session_id")
    with pytest.raises(ContractError, match="confirmed_session_required"):
        gateway.from_handler(handler)


def test_ordinary_overview_and_task_chat_never_consult_owner_nt_or_desktop(models, monkeypatch):
    monkeypatch.setattr(http_api.gateway, "overview", lambda *args: pytest.fail("ordinary user read Local NT overview"))
    monkeypatch.setattr(http_api.live_charts, "details", lambda *args: pytest.fail("ordinary user read Local Desktop"))
    started = model_chat.start(models.authorized, models.service, models.model["id"], {}, "own-model-test", test=True)
    overview = http_get(models.account, "overview")
    assert overview.status == 200, overview.result
    assert overview.result["scope"]["synthetic"] is False
    assert overview.result["capabilities"]["can_run_demo"] is False
    assert [task["id"] for task in overview.result["tasks"]] == [started["id"]]
    assert overview.result["tasks"][0]["source_kind"] == "real_model_response"
    tasks = http_get(models.account, "tasks")
    assert tasks.status == 200 and tasks.result["items"][0]["id"] == started["id"]
    detail = http_get(models.account, "tasks/" + started["id"])
    assert detail.status == 200 and detail.result["task"]["id"] == started["id"]
    link = http_post(models.account, "tasks/" + started["id"] + "/chat", {})
    assert link.status == 200 and link.result == {"conversation_id": started["conversation_id"]}
    assert models.executions == [] and len(models.queue) == 1
    foreign = http_get(models.account, "tasks/" + str(uuid4()))
    assert foreign.status == 404 and foreign.result["code"] == "task_not_found"


def test_private_models_collection_does_not_enumerate_or_leak_owner_credentials(models):
    handler = http_get(models.account, "domains/models")
    assert handler.status == 200, handler.result
    assert len(handler.result["items"]) == 1
    assert handler.result["actions"] == ["connect"]
    assert "owner_bindings" not in handler.result
    assert "bind_existing" not in handler.result["actions"]
    assert models.payload["api_key"] not in json.dumps(handler.result)
    assert models.executions == []


def test_local_owner_binding_is_one_exact_approved_id_without_key_material(owner, monkeypatch):
    authorized, calls = gateway.access(owner.scope), []
    row = {"id": REGISTRY_ID, "enabled": True, "key_configured": True, "endpoint_type": "chat",
           "pricing_status": "free", "name": "Existing", "provider": "openrouter", "model": "fixture:free",
           "base_url": "https://openrouter.ai/api/v1", "remaining_daily_budget_usd": 0,
           "remaining_monthly_budget_usd": 0, "api_key": "must-not-project", "secret_ref": "must-not-project"}

    def one(identity):
        calls.append(identity)
        return copy.deepcopy(row)

    monkeypatch.setattr(agent_registry, "get_agent", one)
    monkeypatch.setattr(agent_registry, "list_agents", lambda: pytest.fail("binding cannot enumerate"))
    result = gateway.owner_binding(authorized, REGISTRY_ID)
    assert calls == [REGISTRY_ID]
    assert result["id"] == REGISTRY_ID and result["remaining_daily_budget_usd"] == 0
    assert "must-not-project" not in json.dumps(result)
    assert "api_key" not in result and "secret_ref" not in result


@pytest.mark.parametrize("changes", [
    {"enabled": False}, {"key_configured": False}, {"endpoint_type": "embedding"},
    {"pricing_status": "unknown"},
])
def test_owner_binding_unavailable_connection_fails_closed(owner, monkeypatch, changes):
    row = {"id": REGISTRY_ID, "enabled": True, "key_configured": True, "endpoint_type": "chat", "pricing_status": "free", **changes}
    monkeypatch.setattr(agent_registry, "get_agent", lambda identity: row)
    with pytest.raises(ContractError, match="owner_binding_unavailable"):
        gateway.owner_binding(gateway.access(owner.scope), REGISTRY_ID)


@pytest.mark.parametrize("revocation", ["runtime", "global_owner"])
def test_existing_binding_admission_does_not_keep_revoked_owner_authority(owner, monkeypatch, revocation):
    # A still-confirmed session may outlive an owner/Local-runtime role change.
    owner.scope["auth_session_id"] = "previous-owner-active-session"
    monkeypatch.setattr(gateway.account_auth, "local_session_is_active", lambda session, uid: True)
    authorized = gateway.access(owner.scope)
    if revocation == "runtime":
        owner.state["workspaces"][WORKSPACE]["uses_owner_runtime"] = False
    else:
        owner.state["user"]["is_owner"] = False
    reads = []

    def get_agent(identity):
        reads.append(identity)
        return {"id": REGISTRY_ID, "enabled": True, "key_configured": True,
                "endpoint_type": "chat", "pricing_status": "free"}

    monkeypatch.setattr(agent_registry, "get_agent", get_agent)
    with pytest.raises(ContractError, match="owner_binding_denied"):
        gateway.owner_binding(authorized, REGISTRY_ID)
    assert reads == []


@pytest.mark.parametrize("identity", [REGISTRY_ID, "../../key", "AGT-abcdefghijkl", "", None])
def test_ordinary_user_cannot_resolve_even_known_global_binding(ordinary, monkeypatch, identity):
    monkeypatch.setattr(agent_registry, "get_agent", lambda identity: pytest.fail("ordinary registry read"))
    with pytest.raises(ContractError, match="owner_binding_denied"):
        gateway.owner_binding(gateway.access(ordinary.scope), identity)


@pytest.mark.parametrize("pricing", ["configured", "estimated", "unknown", None])
def test_private_paid_connections_do_not_receive_new_allowance(models, monkeypatch, pricing):
    monkeypatch.setattr(agent_registry, "managed_pricing", lambda *args: {"pricing_status": pricing})
    monkeypatch.setattr(agent_registry, "infer_billing_mode", lambda *args: "paid")
    with pytest.raises(ContractError, match="private_budget_not_configured"):
        gateway._private_limits(models.context, SimpleNamespace(provider_key="deepseek", model_key="fixture-model"), {})
    assert models.executions == []


@pytest.mark.parametrize("mode", ["capability", "budget", "foreign_context", "nan", "infinity", "negative"])
def test_model_transmission_admission_reuses_existing_current_limits(models, mode):
    context, estimate = models.context, .01
    if mode == "capability":
        models.account.state["permissions"]["capabilities"]["ai_pro_models"] = False
    elif mode == "budget":
        models.account.state["budget_ok"] = False
    elif mode == "foreign_context":
        context = c.RequestContext(scope=c.TenantScope(environment=c.Environment.DEVELOPMENT, workspace_id=OTHER_WORKSPACE),
            user_uuid=context.user_uuid, actor=context.actor)
    else:
        estimate = {"nan": float("nan"), "infinity": float("inf"), "negative": -.01}[mode]
    with pytest.raises(ContractError):
        gateway._model_admit(models.authorized, context, "transmit", estimate)
    assert models.executions == []


@pytest.mark.parametrize("field", ["workspace_id", "user_id", "user_uuid", "scope", "is_owner", "budget_usd"])
def test_query_scope_tampering_is_rejected_before_domain_dispatch(models, monkeypatch, field):
    monkeypatch.setattr(gateway, "list_domain", lambda *args, **kwargs: pytest.fail("tampered query was dispatched"))
    handler = http_get(models.account, "domains/models", {field: ["foreign"]})
    assert handler.status == 409 and handler.result["code"] == "invalid_domain_request"


@pytest.mark.parametrize("field", ["workspace_id", "user_id", "user_uuid", "scope", "is_owner", "budget_usd"])
def test_body_envelope_scope_tampering_rejected(models, field):
    before = len(models.secrets.values)
    body = {"payload": models.payload, "idempotency_key": "tampered-connect", field: "foreign"}
    handler = http_post(models.account, "domains/models/new/connect", body)
    assert handler.status == 409 and handler.result["code"] == "invalid_domain_request"
    assert len(models.secrets.values) == before and models.executions == []


@pytest.mark.parametrize("field", ["workspace_id", "user_id", "scope", "conversation_id", "message_id", "budget_usd"])
def test_payload_cannot_supply_authority_chat_identity_or_budget(models, field):
    handler = http_post(models.account, "domains/models/new/connect", {
        "payload": {**models.payload, field: "foreign"}, "idempotency_key": "tampered-payload"})
    assert handler.status == 409 and "invalid" in handler.result["code"]
    assert len(models.secrets.values) == 1 and models.executions == []


@pytest.mark.parametrize("options,status", [
    ({"csrf": None}, 403), ({"csrf": "wrong"}, 403), ({"origin": None}, 403),
    ({"origin": "https://attacker.invalid"}, 403),
])
def test_generic_domain_posts_use_actual_handler_csrf_and_origin_before_body(models, options, status):
    handler = http_post(models.account, "domains/models/new/connect", {}, **options)
    assert handler.status == status and handler.body_reads == 0
    assert models.executions == [] and models.queue == {}


def test_generic_domain_post_rejects_non_json_before_body(models):
    handler = Handler(models.account, {})
    handler.headers["Content-Type"] = "text/plain"
    http_api.handle_post(handler, gateway.live_gateway.PREFIX + "domains/models/new/connect")
    assert handler.status == 415 and handler.body_reads == 0


def test_generic_route_creates_persona_and_requires_revision_for_mutation(models):
    created = http_post(models.account, "domains/personas/new/create", {
        "payload": {"name": "New Persona", "description": "Context-scoped", "style": "concise"},
        "idempotency_key": "create-domain-persona"})
    assert created.status == 200, created.result
    assert created.result["ok"] is True and created.result["replayed"] is False
    item = created.result["item"]
    listed = http_get(models.account, "domains/personas", {"limit": ["10"]})
    assert listed.status == 200 and "create" in listed.result["actions"]
    assert any(row["id"] == item["id"] for row in listed.result["items"])
    detail = http_get(models.account, "domains/personas/" + item["id"])
    assert detail.status == 200 and detail.result["title"] == "New Persona"
    stale = http_post(models.account, "domains/personas/" + item["id"] + "/activate", {
        "payload": {}, "expected_revision": item["revision"] + 1, "idempotency_key": "stale-persona-revision"})
    assert stale.status == 409
    active = http_post(models.account, "domains/personas/" + item["id"] + "/activate", {
        "payload": {}, "expected_revision": item["revision"], "idempotency_key": "activate-persona-revision"})
    assert active.status == 200 and active.result["item"]["status"] == "active", active.result


def test_real_model_rating_displays_the_specific_class_without_mixing_rubrics(models):
    result = gateway.enrich_overview(models.authorized)
    persona = next(row for row in result["agents"] if row.get("models"))
    assert persona["evaluation"]["task_class"] == "json_arithmetic"
    assert persona["evaluation"]["sample_size"] == 0
    assert persona["evaluation"]["label"] == "NEW"
    assert persona["evaluation"]["score_pct"] is None


def test_generic_model_test_queues_same_chat_task_and_replay_does_not_duplicate(models):
    route = "domains/models/" + models.model["id"] + "/test"
    body = {"payload": {}, "idempotency_key": "exact-model-connect-test"}
    one, replay = http_post(models.account, route, body), http_post(models.account, route, body)
    assert one.status == replay.status == 200, (one.result, replay.result)
    assert one.result["id"] == replay.result["id"]
    assert one.result["status"] == "ready" and len(models.queue) == 1 and len(models.chat) == 1
    assert one.result["conversation_id"].startswith("AW-")
    assert one.result["message_id"].startswith("msg-")
    assert models.executions == []
    completed = models.service.execute(context=models.context, task_id=one.result["id"])
    assert completed["status"] == "succeeded" and completed["evaluation"]["passed"] is True
    envelope = model_chat.envelope(models.authorized, completed, request_id="contract-completion")
    assert envelope["verification"]["passed"] is True and envelope["actual_model"] == "served-model"
    assert envelope["conversation_id"] == one.result["conversation_id"]
    assert envelope["evaluation_id"] == completed["task"]["evaluation_id"]
    assert len(models.executions) == 1


def test_duplicate_queue_identity_accepted_only_for_exact_existing_payload(models):
    task = models.service.test(context=models.context, model_id=models.model["id"], idempotency_key="queue-original-task")
    row = gateway.enqueue_model(models.authorized, context=models.context, task_id=task["id"])
    assert len(models.queue) == 1 and row["payload"]["task_id"] == task["id"]
    queue_id = next(iter(models.queue))
    models.queue[queue_id]["payload"]["scope"]["user_uuid"] = str(uuid4())
    with pytest.raises(ContractError, match="queue_identity_conflict"):
        gateway.enqueue_model(models.authorized, context=models.context, task_id=task["id"])
    assert models.executions == []


def test_worker_rejects_queue_scope_tampering_before_execution(models):
    job = {"kind": "agent_world_model", "workspace_id": OTHER_WORKSPACE, "user_id": USER_ID,
           "payload": {"scope": models.authorized["chat_scope"], "task_id": str(uuid4())}}
    with pytest.raises(ContractError, match="worker_scope_required"):
        gateway.execute_worker(job, lambda: False, lambda: pytest.fail("scope-rejected worker heartbeat"))
    assert models.executions == []


def test_task_chat_body_cannot_select_foreign_conversation(models):
    task = model_chat.start(models.authorized, models.service, models.model["id"], {}, "chat-body-reject", test=True)
    handler = http_post(models.account, "tasks/" + task["id"] + "/chat", {"conversation_id": "foreign-chat"})
    assert handler.status == 409 and handler.result["code"] == "invalid_request"
    assert len(models.chat) == 1 and models.executions == []


def test_real_scope_demo_route_remains_unavailable(models):
    handler = http_post(models.account, "demo-runs", {"idempotency_key": "no-demo-in-real"})
    assert handler.status == 404 and models.queue == {} and models.executions == []


def test_domain_gets_do_not_enqueue_execute_or_create_chat(models):
    with models.repository._transaction() as database:
        before = "\n".join(database.iterdump())
    for route in ("overview", "tasks", "domains/personas", "domains/models", "domains/model_tasks", "domains/system"):
        result = http_get(models.account, route)
        assert result.status == 200, (route, result.result)
    with models.repository._transaction() as database:
        assert "\n".join(database.iterdump()) == before
    assert models.queue == {} and models.chat == {} and models.executions == []


@pytest.mark.parametrize("mode", ["expired_entitlement", "exhausted_budget"])
def test_history_remains_readable_but_has_no_new_model_actions(models, mode):
    task = model_chat.start(models.authorized, models.service, models.model["id"], {}, "history-survives-expiry", test=True)
    if mode == "expired_entitlement":
        models.account.state["permissions"]["capabilities"].update(ai_lab=False, ai_pro_models=False)
    else:
        models.account.state["budget_ok"] = False
    for route in ("overview", "tasks", "domains/models", "domains/model_tasks", "tasks/" + task["id"]):
        result = http_get(models.account, route)
        assert result.status == 200, (route, result.result)
    collection = http_get(models.account, "domains/models").result
    assert collection.get("actions") == []
    assert all(item.get("actions", []) == [] for item in collection["items"])
    action = http_post(models.account, "domains/models/" + models.model["id"] + "/test", {
        "payload": {}, "idempotency_key": "blocked-after-expiry"})
    assert action.status in {403, 409}, action.result
    assert models.executions == [] and len(models.queue) == 1


def test_expired_entitlement_can_open_own_existing_chat_but_not_foreign_chat(models):
    task = model_chat.start(models.authorized, models.service, models.model["id"], {}, "open-history-chat", test=True)
    models.account.state["permissions"]["capabilities"].update(ai_lab=False, ai_pro_models=False)
    link = http_post(models.account, "tasks/" + task["id"] + "/chat", {})
    assert link.status == 200 and link.result == {"conversation_id": task["conversation_id"]}, link.result
    foreign = http_post(models.account, "tasks/" + str(uuid4()) + "/chat", {})
    assert foreign.status == 404
    assert models.executions == [] and len(models.chat) == 1


def test_read_only_history_still_revokes_expired_device_session(models):
    models.account.state["permissions"]["capabilities"].update(ai_lab=False, ai_pro_models=False)
    models.account.state["session_active"] = False
    result = http_get(models.account, "domains/models")
    assert result.status in {403, 409} and result.result["code"] == "agent_world_session_expired"


def test_existing_foreign_user_model_and_task_are_not_visible(models):
    foreign_id = uuid4()
    foreign = c.RequestContext(scope=models.context.scope, user_uuid=foreign_id,
        actor=c.ActorRef(kind=c.ActorKind.HUMAN, actor_id=foreign_id))
    service = ModelService(models.repository, admit=lambda *args: None, secrets=Secrets(),
        enqueue=lambda **kwargs: None, executor=lambda **kwargs: pytest.fail("foreign model execution"))
    policy = service._put(foreign, {"version": "foreign-fixture", "synthetic": True})
    persona = service._ensure(foreign, c.Persona, uuid4(), uuid4(), policy, display_name="Foreign secret persona",
        profile=service._put(foreign, {"description": "must-not-leak"}))
    service._walk(foreign, persona, "active")
    model = service.connect(context=foreign, payload={**models.payload, "persona_id": str(persona.header.entity_id),
        "label": "Foreign secret model"}, idempotency_key="foreign-private-model")
    task = service.test(context=foreign, model_id=model["id"], idempotency_key="foreign-test-task", conversation_id="foreign-secret-chat")
    own = http_get(models.account, "domains/models")
    assert own.status == 200 and "Foreign secret" not in json.dumps(own.result)
    detail = http_get(models.account, "domains/models/" + model["id"])
    assert detail.status == 409 and detail.result["code"] == "model_record_not_found"
    for route, body in (("tasks/" + task["id"], None), ("tasks/" + task["id"] + "/chat", {})):
        result = http_get(models.account, route) if body is None else http_post(models.account, route, body)
        assert result.status == 404 and "foreign-secret-chat" not in json.dumps(result.result)
    assert models.executions == []


@pytest.fixture
def publication(models, monkeypatch):
    from app.ai_control_center.social_publication import SocialPublicationService

    task = models.service.start_task(context=models.context, model_id=models.model["id"],
        payload={"rubric_key": "json_arithmetic"}, idempotency_key="publication-verified-task")
    completed = models.service.execute(context=models.context, task_id=task["id"])
    posts = []

    def create_post(user_id, **kwargs):
        posts.append({"user_id": user_id, **copy.deepcopy(kwargs)})
        return {"ok": True, "deduplicated": False,
                "post": {"post_id": "disposable-social-post", "object": kwargs["object_snapshot"], "permanent": True}}

    community = SimpleNamespace(create_social_post=create_post)
    monkeypatch.setattr(gateway, "social", lambda authorized, repo=None:
        SocialPublicationService(repo or models.repository, community_api=community))
    source = {"source_kind": "outcome", "source_id": completed["outcome_id"]}
    return SimpleNamespace(models=models, completed=completed, source=source, posts=posts)


def prepare_publication(publication):
    result = http_post(publication.models.account, "domains/publications/new/prepare", {
        "payload": publication.source, "idempotency_key": "prepare-owned-publication"})
    assert result.status == 200, result.result
    return result.result


def test_publication_source_candidates_are_verified_own_results_not_private_answers(publication):
    models = publication.models
    # Connection check is real, but is not a capability result eligible for social publication.
    check = models.service.test(context=models.context, model_id=models.model["id"], idempotency_key="publication-connection-only")
    checked = models.service.execute(context=models.context, task_id=check["id"])
    with models.repository._transaction() as database:
        before = "\n".join(database.iterdump())
    result = http_get(models.account, "domains/publications")
    assert result.status == 200, result.result
    assert result.result["actions"] == ["prepare"]
    candidates = result.result["source_candidates"]
    assert [item["source_id"] for item in candidates] == [publication.source["source_id"]]
    assert checked["outcome_id"] not in json.dumps(candidates)
    assert all(item["source_kind"] == "outcome" and item["source_revision"] > 0 for item in candidates)
    for private in (models.payload["api_key"], "CONNECTION_OK", '"count":4', "prompt", "private Memory"):
        assert private not in json.dumps(candidates)
    with models.repository._transaction() as database:
        assert "\n".join(database.iterdump()) == before
    assert publication.posts == []


@pytest.mark.parametrize("kind", ["memory", "artifact", "persona", "execution", "unknown"])
def test_publication_prepare_source_whitelist_is_enforced_by_http(publication, kind):
    result = http_post(publication.models.account, "domains/publications/new/prepare", {
        "payload": {**publication.source, "source_kind": kind}, "idempotency_key": "reject-private-publication"})
    assert result.status == 403 and result.result["code"] == "social_source_kind_denied"
    assert publication.posts == []


def test_publication_prepare_cannot_read_foreign_or_missing_outcome(publication):
    result = http_post(publication.models.account, "domains/publications/new/prepare", {
        "payload": {"source_kind": "outcome", "source_id": str(uuid4())}, "idempotency_key": "reject-foreign-publication"})
    assert result.status == 409 and result.result["code"] == "social_source_not_found"
    assert publication.posts == []


@pytest.mark.parametrize("confirmation", [None, False, "true", 1])
def test_http_publication_without_exact_permanent_confirmation_has_no_social_effect(publication, confirmation):
    prepared = prepare_publication(publication)
    payload = {**publication.source, "approved_snapshot_sha256": prepared["snapshot_sha256"], "visibility": "private"}
    if confirmation is not None:
        payload["confirm_permanent"] = confirmation
    result = http_post(publication.models.account, "domains/publications/new/publish", {
        "payload": payload, "expected_revision": prepared["source_revision"], "idempotency_key": "publication-missing-confirm"})
    assert result.status == 403 and result.result["code"] == "social_permanent_confirmation_required"
    assert publication.posts == []


@pytest.mark.parametrize("field", ["workspace_id", "user_uuid", "user_id", "object_snapshot", "trusted_snapshot", "raw_response"])
def test_http_publication_payload_cannot_override_snapshot_or_server_identity(publication, field):
    prepared = prepare_publication(publication)
    result = http_post(publication.models.account, "domains/publications/new/publish", {
        "payload": {**publication.source, "approved_snapshot_sha256": prepared["snapshot_sha256"],
                    "confirm_permanent": True, field: "untrusted"},
        "expected_revision": prepared["source_revision"], "idempotency_key": "publication-tampered-fields"})
    assert result.status == 409 and result.result["code"] == "domain_action_not_supported"
    assert publication.posts == []


def test_http_publication_uses_exact_reviewed_hash_revision_and_existing_social_identity(publication):
    prepared = prepare_publication(publication)
    result = http_post(publication.models.account, "domains/publications/new/publish", {
        "payload": {**publication.source, "approved_snapshot_sha256": prepared["snapshot_sha256"],
                    "text": "My explicit review", "visibility": "followers", "confirm_permanent": True},
        "expected_revision": prepared["source_revision"], "idempotency_key": "publication-explicit-confirm"})
    assert result.status == 200, result.result
    assert result.result["published_to"] == "sf_social" and result.result["permanent"] is True
    assert result.result["snapshot_sha256"] == prepared["snapshot_sha256"]
    assert len(publication.posts) == 1
    post = publication.posts[0]
    assert post["user_id"] == USER_ID and post["workspace_id"] == WORKSPACE and post["user_uuid"] == USER_UUID
    assert post["text"] == "My explicit review" and post["visibility"] == "followers" and post["trusted_snapshot"] is True
    assert post["object_snapshot"]["source_id"] == publication.source["source_id"]
    assert publication.models.payload["api_key"] not in json.dumps(post)
    assert any(path == "/api/community/social/posts" and data["_request_method"] == "POST"
               for path, data in publication.models.account.calls["enforce"])


def test_publication_backtest_loader_has_the_service_keyword_contract(owner, monkeypatch, tmp_path):
    from app.ai_control_center.live_backtests import LiveBacktestService

    authorized, reads = gateway.access(owner.scope), []
    repository = SQLiteAgentWorldRepository(tmp_path / "publication-loader.sqlite")

    def get(service, **kwargs):
        reads.append(kwargs)
        return {"fixture": True}

    monkeypatch.setattr(LiveBacktestService, "get", get)
    loader = gateway.social(authorized, repository).backtest_loader
    result = loader(context=authorized["context"], source_id="awnt_fixture", admit=authorized["admit"])
    assert result == {"fixture": True}
    assert len(reads) == 1 and reads[0]["job_id"] == "awnt_fixture"
    assert reads[0]["source_scope"] == {"workspace_id": WORKSPACE, "user_id": USER_ID, "allow_legacy": False}


@pytest.mark.parametrize("scope_level", ["environment", "workspace"])
def test_publication_feature_flag_off_denies_get_prepare_and_publish_before_service(publication, monkeypatch, scope_level):
    models = publication.models
    prepared = prepare_publication(publication)
    original = models.authorized["snapshot"]
    disabled = replace(original, revision="social-disabled-contract", rules=tuple(
        replace(rule, enabled=False) if rule.flag is Flag.AI_SOCIAL_PUBLISH_V1
            and (rule.workspace_id is None if scope_level == "environment" else rule.workspace_id == WORKSPACE)
        else rule for rule in original.rules))
    assert resolve(Flag.AI_TASK_GRAPH_V2, scope=models.context.scope, snapshot=disabled).enabled is True
    assert resolve(Flag.AI_SOCIAL_PUBLISH_V1, scope=models.context.scope, snapshot=disabled).enabled is False
    monkeypatch.setattr(gateway.live_gateway, "flag_snapshot", lambda context: disabled)
    monkeypatch.setattr(gateway, "social", lambda *args, **kwargs: pytest.fail("Disabled publication reached service"))
    reads = http_get(models.account, "domains/publications")
    assert reads.status == 403 and reads.result["code"] == "agent_world_domain_disabled"
    for action, payload in (("prepare", publication.source), ("publish", {**publication.source,
            "approved_snapshot_sha256": prepared["snapshot_sha256"], "confirm_permanent": True})):
        result = http_post(models.account, "domains/publications/new/" + action, {
            "payload": payload, "expected_revision": prepared["source_revision"], "idempotency_key": "social-flag-off-request"})
        assert result.status == 403 and result.result["code"] == "agent_world_domain_disabled"
    assert publication.posts == []
