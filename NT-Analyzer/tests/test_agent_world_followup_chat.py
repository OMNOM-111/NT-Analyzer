"""Manual follow-up delivery: real disposable SQLite/worker/chat, no providers."""
from __future__ import annotations

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app import durable, local_worker, worker_router
from app.ai_lab import chief_agent, universal_llm
from app.ai_control_center import contracts as c, domain_gateway as gateway, followup_chat
from app.ai_control_center.domain_service import DomainService
from app.ai_control_center.model_service import ModelService
from app.ai_control_center.repositories import PageRequest
from app.ai_control_center.sqlite_repository import SQLiteAgentWorldRepository
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_gateway import http_get, http_post, ordinary
from tests.test_agent_world_live_gateway import isolated_runtime, owner


@pytest.fixture
def followup(ordinary, tmp_path, monkeypatch, request):
    if getattr(request, "param", "ordinary") == "owner":
        ordinary.scope.update(is_owner=True, uses_owner_runtime=True)
        ordinary.state["user"]["is_owner"] = True
        ordinary.state["workspaces"][ordinary.scope["workspace_id"]]["uses_owner_runtime"] = True
    monkeypatch.setenv("NT_ANALYZER_ROOT", str(tmp_path))
    monkeypatch.setattr(local_worker, "_MODEL_RECOVERY_STATE", {"root": "", "at": 0.0, "after_id": ""})
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", tmp_path / "followup-chat")
    monkeypatch.setattr(chief_agent.paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chief_agent, "_explicit_production", lambda: False)
    monkeypatch.setattr(chief_agent, "_sync_telegram_topic_title_async", lambda *a, **k: pytest.fail("follow-up scheduled Telegram"))
    monkeypatch.setattr(ModelService, "execute", lambda *a, **k: pytest.fail("follow-up invoked a model"))
    monkeypatch.setattr(universal_llm, "invoke", lambda *a, **k: pytest.fail("follow-up invoked a provider"), raising=False)
    path = tmp_path / "followup-world.sqlite3"

    def repository(authorized):
        authorized["admit"]()
        return SQLiteAgentWorldRepository(path, read_only=authorized.get("read_only", False))

    monkeypatch.setattr(gateway, "repository", repository)
    authorized = gateway.access(ordinary.scope)
    service = DomainService(repository(authorized), enqueue=lambda **kw: gateway._followup(authorized, **kw))
    return SimpleNamespace(account=ordinary, authorized=authorized, service=service,
                           context=authorized["context"], root=tmp_path, repo=service.repository)


def _create(fixture, domain="routines", *, accept=True, title="Проверить сохранённый результат"):
    payload = {"title": title, "description": "Открыть источник и выбрать следующий шаг вручную."}
    payload.update({"interval_minutes": 60} if domain == "routines" else
                   {"starts_at": "2099-09-05T07:00:00Z", "ends_at": "2099-09-05T07:30:00Z"})
    item = fixture.service.create(context=fixture.context, admit=fixture.authorized["admit"],
        domain=domain, payload=payload, idempotency_key="source-create-" + domain)["item"]
    if accept:
        item = fixture.service.act(context=fixture.context, admit=fixture.authorized["admit"],
            domain=domain, entity_id=item["id"], action="accept", payload={}, expected_revision=item["revision"],
            idempotency_key="source-accept-" + domain)["item"]
        result = local_worker.run_once(worker_id="source-accept-worker")
        assert result["status"] == "succeeded" and result["result"]["status"] == "awaiting_manual_action"
    return item


def _start(fixture, item, domain="routines", *, key="explicit-open-chat", revision=None):
    return followup_chat.start(fixture.authorized, fixture.service, domain, item["id"],
                               item["revision"] if revision is None else revision, key)


def _rows(fixture, opened):
    return chief_agent.read_jsonl(chief_agent._conversation_file(opened["conversation_id"],
        scope=fixture.authorized["chat_scope"]))


def _job(fixture, opened):
    return worker_router.get(opened["job_id"], workspace_id=fixture.context.scope.workspace_id)


def _dismiss(fixture, item, domain="routines"):
    return fixture.service.act(context=fixture.context, admit=fixture.authorized["admit"], domain=domain,
        entity_id=item["id"], action="dismiss", payload={}, expected_revision=item["revision"],
        idempotency_key="dismiss-followup-" + domain)


def _counts(fixture):
    with sqlite3.connect(fixture.repo.path) as connection:
        return tuple(connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                     for table in ("aw_records", "aw_events", "aw_artifacts", "aw_inbox"))


@pytest.mark.parametrize("followup", ["ordinary", "owner"], indirect=True)
@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_explicit_followup_uses_existing_queue_and_one_neutral_sf_chat_receipt(followup, domain):
    item = _create(followup, domain)
    before = _counts(followup)
    opened = _start(followup, item, domain)
    assert opened["status"] == "queued" and opened["execution_performed"] is False
    assert _rows(followup, opened) == []
    queued = _job(followup, opened)
    assert queued["kind"] == "agent_world_followup" and queued["payload"]["phase"] == "chat_delivery"
    assert queued["max_attempts"] == 3 and queued["timeout_sec"] == 30
    delivered = local_worker.run_once(worker_id="followup-worker")
    assert delivered["status"] == "succeeded", delivered
    assert delivered["result"]["status"] == "delivered"
    assert delivered["result"]["scheduled_delivery"] is False
    rows = _rows(followup, opened)
    assert len(rows) == 1
    message = rows[0]
    assert message["role"] == "system" and message["source"] == followup_chat.SOURCE
    assert message["agent_name"] == "Ручной разбор" and message["participation_chain"] == []
    assert message["model"] == message["provider"] == "" and "rating_event_id" not in message
    assert message["user_uuid"] == str(followup.context.user_uuid)
    assert message["workspace_id"] == followup.context.scope.workspace_id
    assert "не доставка по расписанию" in message["content"]
    assert "Модель, бэктест и внешние действия не запускались" in message["content"]
    assert queued["queued_at_utc"] in message["content"]
    assert ("2099-09-05T07:00:00Z" if domain == "calendar" else "60 минут") in message["content"]
    assert opened["source_url"] in message["content"] and "&entity=" + item["id"] in opened["source_url"]
    assert _counts(followup)[:2] == before[:2]  # Not another domain/job/rating ledger.
    assert followup.account.calls["budget"] == []
    receipt = delivered["result"]["receipt"]
    found = followup.repo.get_artifact_by_id(context=followup.context, artifact_id=UUID(receipt["artifact_id"]))
    proof = json.loads(found[1])
    assert found[0].sha256 == receipt["sha256"] and proof["message_id"] == message["message_id"]
    assert proof["recorded_at"] == message["timestamp_utc"] and proof["source_revision"] == item["revision"]
    assert followup.repo.events.is_acknowledged(context=followup.context, consumer=followup_chat.CONSUMER,
                                               event_id=UUID(proof["event_id"]))
    current = followup.service.get(context=followup.context, admit=followup.authorized["admit"],
                                  domain=domain, entity_id=item["id"])
    assert current["revision"] == item["revision"] and current["status"] == "accepted"


def test_repeat_new_action_keys_and_restart_do_not_make_new_jobs_or_messages(followup):
    item = _create(followup)
    opened = _start(followup, item)
    repeated = _start(followup, item, key="second-explicit-click")
    assert opened["job_id"] == repeated["job_id"] and repeated["replayed"]
    assert len(durable.list_worker_jobs(followup.root)) == 2
    assert local_worker.run_once(worker_id="before-restart")["status"] == "succeeded"
    after = _start(followup, item, key="after-restart-click")
    assert after["status"] == "delivered" and after["message_id"] == _rows(followup, opened)[0]["message_id"]
    assert local_worker.run_once(worker_id="after-restart") is None
    assert len(_rows(followup, opened)) == 1


def test_concurrent_explicit_clicks_have_one_source_revision_delivery(followup):
    item = _create(followup)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda key: _start(followup, item, key=key), ["concurrent-one", "concurrent-two"]))
    assert results[0]["job_id"] == results[1]["job_id"]
    assert len(durable.list_worker_jobs(followup.root)) == 2
    assert local_worker.run_once(worker_id="only-publisher")["status"] == "succeeded"
    assert len(_rows(followup, results[0])) == 1


def test_read_projection_does_not_create_work_and_preserves_proof(followup):
    item = _create(followup)
    authorized = gateway.access(followup.account.scope, read_only=True)
    service = DomainService(gateway.repository(authorized))
    before = _counts(followup)
    assert followup_chat.projection(authorized, service, "routines", item["id"]) is None
    assert _counts(followup) == before and len(durable.list_worker_jobs(followup.root)) == 1
    opened = _start(followup, item)
    assert local_worker.run_once(worker_id="projection-test")["status"] == "succeeded"
    before = _counts(followup)
    projected = followup_chat.projection(authorized, service, "routines", item["id"])
    assert projected["status"] == "delivered" and projected["conversation_id"] == opened["conversation_id"]
    assert _counts(followup) == before
    with pytest.raises(ContractError, match="followup_write_required"):
        followup_chat.start(authorized, service, "routines", item["id"], item["revision"], "no-read-write")


@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_real_http_routes_accept_open_deliver_and_project_without_dispatch_on_read(followup, domain):
    payload = {"title": "Ручной разбор через настоящий API", "description": "Проверить сохранённый источник."}
    payload.update({"interval_minutes": 60} if domain == "routines" else
                   {"starts_at": "2099-09-05T07:00:00Z", "ends_at": "2099-09-05T07:30:00Z"})
    created = http_post(followup.account, "domains/" + domain + "/new/create", {
        "payload": payload, "idempotency_key": "http-create-" + domain})
    assert created.status == 200, created.result
    item = created.result["item"]
    route = "domains/" + domain + "/" + item["id"]
    proposed = http_get(followup.account, route)
    assert proposed.status == 200 and "open_chat" not in proposed.result.get("actions", [])
    accepted = http_post(followup.account, route + "/accept", {
        "payload": {}, "expected_revision": item["revision"], "idempotency_key": "http-accept-" + domain})
    assert accepted.status == 200, accepted.result
    item = accepted.result["item"]
    assert local_worker.run_once(worker_id="http-source-receipt")["status"] == "succeeded"
    before = _counts(followup)
    detail = http_get(followup.account, route)
    assert detail.status == 200 and "open_chat" in detail.result["actions"]
    assert detail.result["followup_chat"] is None
    assert _counts(followup) == before and len(durable.list_worker_jobs(followup.root)) == 1
    opened = http_post(followup.account, route + "/open_chat", {
        "payload": {}, "expected_revision": item["revision"], "idempotency_key": "http-open-" + domain})
    assert opened.status == 200 and opened.result["status"] == "queued", opened.result
    assert _rows(followup, opened.result) == []
    delivered = local_worker.run_once(worker_id="http-real-gateway-delivery")
    assert delivered["status"] == "succeeded" and delivered["result"]["status"] == "delivered", delivered
    before = _counts(followup)
    detail = http_get(followup.account, route)
    listed = http_get(followup.account, "domains/" + domain)
    assert detail.status == listed.status == 200
    list_row = next(row for row in listed.result["items"] if row["id"] == item["id"])
    assert detail.result["followup_chat"] == list_row["followup_chat"]
    assert detail.result["followup_chat"]["status"] == "delivered"
    assert detail.result["followup_chat"]["conversation_id"] == opened.result["conversation_id"]
    assert _counts(followup) == before and len(durable.list_worker_jobs(followup.root)) == 2
    assert len(_rows(followup, opened.result)) == 1 and followup.account.calls["budget"] == []


@pytest.mark.parametrize("invalid", ["payload", "stale_revision", "missing_csrf", "foreign_origin"])
def test_real_http_open_rejects_invalid_request_before_queue(followup, invalid):
    item = _create(followup)
    body = {"payload": {}, "expected_revision": item["revision"], "idempotency_key": "invalid-http-open"}
    options = {}
    if invalid == "payload": body["payload"] = {"automation_enabled": True}
    if invalid == "stale_revision": body["expected_revision"] -= 1
    if invalid == "missing_csrf": options["csrf"] = None
    if invalid == "foreign_origin": options["origin"] = "https://foreign.example.invalid"
    response = http_post(followup.account, "domains/routines/" + item["id"] + "/open_chat", body, **options)
    assert response.status >= 400, response.result
    assert len(durable.list_worker_jobs(followup.root)) == 1


def test_recorded_delivery_can_be_reopened_under_a_new_fresh_session(followup, monkeypatch):
    item = _create(followup)
    opened = _start(followup, item)
    assert local_worker.run_once(worker_id="original-session")["status"] == "succeeded"
    followup.account.scope["auth_session_id"] = "new-confirmed-followup-session"
    monkeypatch.setattr(gateway.account_auth, "local_session_is_active", lambda session, uid:
                        session == "new-confirmed-followup-session" and uid == followup.account.scope["user_id"])
    followup.authorized = gateway.access(followup.account.scope)
    repeated = _start(followup, item, key="reopen-new-session")
    assert repeated["status"] == "delivered" and repeated["conversation_id"] == opened["conversation_id"]
    assert len(durable.list_worker_jobs(followup.root)) == 2 and len(_rows(followup, opened)) == 1


def test_service_actor_cannot_supply_human_open_chat_consent(followup):
    item = _create(followup)
    context = replace(followup.context, actor=c.ActorRef(kind=c.ActorKind.SERVICE, actor_id=uuid4(),
                                                       on_behalf_of=followup.context.user_uuid))
    with pytest.raises(ContractError, match="followup_human_context_required"):
        followup_chat.start({**followup.authorized, "context": context}, followup.service, "routines",
                            item["id"], item["revision"], "forged-human-request")


@pytest.mark.parametrize("invalid", ["proposed", "stale_revision", "bool_revision", "wrong_kind", "foreign_identity", "bad_key"])
def test_start_requires_exact_human_accepted_source(followup, invalid):
    item = _create(followup, accept=invalid != "proposed")
    before = len(durable.list_worker_jobs(followup.root))
    kwargs = {"domain": "routines", "identity": item["id"], "expected_revision": item["revision"], "idempotency_key": "valid-start-key"}
    if invalid == "stale_revision": kwargs["expected_revision"] -= 1
    if invalid == "bool_revision": kwargs["expected_revision"] = True
    if invalid == "wrong_kind": kwargs["domain"] = "projects"
    if invalid == "foreign_identity": kwargs["identity"] = str(uuid4())
    if invalid == "bad_key": kwargs["idempotency_key"] = "short"
    with pytest.raises(ContractError):
        followup_chat.start(followup.authorized, followup.service, **kwargs)
    assert len(durable.list_worker_jobs(followup.root)) == before


@pytest.mark.parametrize("when", ["start", "worker"])
@pytest.mark.parametrize("revocation", ["session", "identity", "workspace", "permission", "flag"])
def test_fresh_authority_revocation_blocks_before_chat_write(followup, monkeypatch, revocation, when):
    item = _create(followup)
    opened = _start(followup, item) if when == "worker" else None
    state = followup.account.state
    if revocation == "session": state["session_active"] = False
    if revocation == "identity": state["user"]["user_uuid"] = str(uuid4())
    if revocation == "workspace": state["workspaces"].clear()
    if revocation == "permission": state["permission_denied"] = True
    if revocation == "flag": monkeypatch.delenv(gateway.live_gateway.WORKSPACES_ENV)
    if when == "start":
        with pytest.raises(Exception):
            _start(followup, item)
    else:
        result = local_worker.run_once(worker_id="revoked-worker")
        assert result["status"] == "queued" and _rows(followup, opened) == []


def test_dismiss_after_enqueue_blocks_delivery_without_rewriting_source(followup):
    item = _create(followup)
    opened = _start(followup, item)
    _dismiss(followup, item)
    result = local_worker.run_once(worker_id="stale-source")
    assert result["status"] == "queued" and "followup_accepted_revision_required" in result["error"]
    assert _rows(followup, opened) == []
    assert followup_chat.projection(followup.authorized, followup.service, "routines", item["id"]) is None


@pytest.mark.parametrize("change", ["status", "worker", "attempt", "payload", "user", "workspace", "cancel", "expired", "nan"])
def test_exact_existing_worker_claim_is_required(followup, monkeypatch, change):
    opened = _start(followup, _create(followup))
    job = durable.claim_worker_job(followup.root, worker_id="claimed-worker")
    tampered = copy.deepcopy(job)
    if change == "status": tampered["status"] = "succeeded"
    if change == "worker": tampered["worker_id"] = "old-worker"
    if change == "attempt": tampered["attempts"] += 1
    if change == "payload": tampered["payload"]["revision"] += 1
    if change == "user": tampered["user_id"] = "another-user"
    if change == "workspace": tampered["workspace_id"] = "ws_foreign_scope"
    if change == "cancel": tampered["cancel_requested"] = 1
    if change in {"expired", "nan"}:
        original = worker_router.get
        def get(identity, **kw):
            row = original(identity, **kw)
            if identity == opened["job_id"]: row["locked_until"] = 0 if change == "expired" else float("nan")
            return row
        monkeypatch.setattr(worker_router, "get", get)
    with pytest.raises(ContractError):
        followup_chat.execute(followup.authorized, tampered, lambda: False, lambda: None)
    assert _rows(followup, opened) == []


def test_cancelled_worker_never_creates_a_chat_message(followup):
    opened = _start(followup, _create(followup))
    job = durable.claim_worker_job(followup.root, worker_id="cancelled-worker")
    with pytest.raises(ContractError, match="followup_cancelled"):
        followup_chat.execute(followup.authorized, job, lambda: True, lambda: None)
    assert _rows(followup, opened) == []


@pytest.mark.parametrize("change", ["manifest_title", "manifest_source", "extra_field", "phase", "foreign_scope"])
def test_worker_rejects_injected_manifest_or_payload_authority(followup, monkeypatch, change):
    opened = _start(followup, _create(followup))
    job = durable.claim_worker_job(followup.root, worker_id="manifest-claim")
    if change.startswith("manifest_"):
        manifest, _ = followup_chat._load_manifest(followup.service, followup.context, job["payload"])
        if change == "manifest_title": manifest["title"] = "Invented source title"
        if change == "manifest_source": manifest["entity_id"] = str(uuid4())
        reference = followup.service._put(followup.context, followup.authorized["admit"], manifest)
        job["payload"]["manifest"] = {"artifact_id": str(reference.artifact_id), "sha256": reference.sha256}
    if change == "extra_field": job["payload"]["execute_provider"] = True
    if change == "phase": job["payload"]["phase"] = "execute"
    if change == "foreign_scope": job["payload"]["scope"]["workspace_id"] = "ws_foreign_scope"
    original = worker_router.get
    monkeypatch.setattr(worker_router, "get", lambda identity, **kw: copy.deepcopy(job)
                        if identity == opened["job_id"] else original(identity, **kw))
    with pytest.raises(ContractError):
        followup_chat.execute(followup.authorized, job, lambda: False, lambda: None)
    assert _rows(followup, opened) == []


@pytest.mark.parametrize("change", ["user", "uuid", "workspace", "request", "kind", "cancelled"])
def test_acceptance_handoff_job_scope_and_exact_request_are_rechecked(followup, monkeypatch, change):
    item = _create(followup)
    opened = _start(followup, item)
    source_id = item["handoff"]["job_id"]
    original = worker_router.get
    def get(identity, **kw):
        row = original(identity, **kw)
        if identity == source_id:
            if change == "user": row["user_id"] = "foreign"
            if change == "uuid": row["payload"]["scope"]["user_uuid"] = str(uuid4())
            if change == "workspace": row["workspace_id"] = "ws_foreign_scope"
            if change == "request": row["payload"]["request"]["title"] = "Not the accepted source"
            if change == "kind": row["kind"] = "agent_world_model"
            if change == "cancelled": row["cancel_requested"] = 1
        return row
    monkeypatch.setattr(worker_router, "get", get)
    result = local_worker.run_once(worker_id="handoff-recheck")
    assert result["status"] == "queued" and "followup_handoff_source_invalid" in result["error"]
    assert _rows(followup, opened) == []


@pytest.mark.parametrize("fault", ["append_index", "inbox_ack"])
def test_append_before_index_or_ack_restarts_as_one_message(followup, monkeypatch, fault):
    opened = _start(followup, _create(followup))
    called = []
    if fault == "append_index":
        original = chief_agent._touch_conversation
        def fail(*args, **kwargs):
            if not called:
                called.append(True)
                raise OSError("fixture crash after append before index")
            return original(*args, **kwargs)
        monkeypatch.setattr(chief_agent, "_touch_conversation", fail)
    else:
        original = type(followup.repo.events).acknowledge
        def fail(self, **kwargs):
            if kwargs["consumer"] == followup_chat.CONSUMER and not called:
                called.append(True)
                raise OSError("fixture crash before inbox ack")
            return original(self, **kwargs)
        monkeypatch.setattr(type(followup.repo.events), "acknowledge", fail)
    first = local_worker.run_once(worker_id="interrupted-publisher")
    assert first["status"] == "queued" and first["attempts"] == 1
    rows = _rows(followup, opened)
    assert len(rows) == 1
    second = local_worker.run_once(worker_id="restarted-publisher")
    assert second["status"] == "succeeded" and second["result"]["replayed"] is True
    assert _rows(followup, opened) == rows
    conversation = next(row for row in chief_agent.list_conversations(scope=followup.authorized["chat_scope"])
                        if row["conversation_id"] == opened["conversation_id"])
    assert conversation["message_count"] == 1 and conversation["work_state"] == "awaiting_owner"


def test_later_conversation_work_is_not_downgraded_by_delivery_replay(followup, monkeypatch):
    opened = _start(followup, _create(followup))
    original = type(followup.repo.events).acknowledge
    monkeypatch.setattr(type(followup.repo.events), "acknowledge", lambda *a, **k: (_ for _ in ()).throw(OSError("fixture ack failure")))
    assert local_worker.run_once(worker_id="receipt-first")["status"] == "queued"
    path = chief_agent._conversation_file(opened["conversation_id"], scope=followup.authorized["chat_scope"])
    chief_agent._append_conversation("user", "Следующая отдельная задача", source="app", path=path,
                                    scope=followup.authorized["chat_scope"])
    chief_agent._set_conversation_work_state(opened["conversation_id"], "in_progress", scope=followup.authorized["chat_scope"])
    monkeypatch.setattr(type(followup.repo.events), "acknowledge", original)
    assert local_worker.run_once(worker_id="receipt-recovery")["status"] == "succeeded"
    assert len(_rows(followup, opened)) == 2
    conversation = next(row for row in chief_agent.list_conversations(scope=followup.authorized["chat_scope"])
                        if row["conversation_id"] == opened["conversation_id"])
    assert conversation["work_state"] == "in_progress" and conversation["message_count"] == 2


def test_duplicate_same_claim_replay_preserves_one_receipt(followup):
    opened = _start(followup, _create(followup))
    job = durable.claim_worker_job(followup.root, worker_id="single-claim")
    first = followup_chat.execute(followup.authorized, job, lambda: False, lambda: None)
    repeated = followup_chat.execute(followup.authorized, job, lambda: False, lambda: None)
    assert repeated["replayed"] and repeated["message_id"] == first["message_id"]
    assert repeated["receipt"] == first["receipt"] and len(_rows(followup, opened)) == 1


def test_existing_chat_redaction_remains_idempotent_on_replay(followup, monkeypatch):
    opened = _start(followup, _create(followup))
    original = chief_agent._redact_sensitive
    monkeypatch.setattr(chief_agent, "_redact_sensitive", lambda text: original(text).replace("сохранённый", "[REDACTED]"))
    job = durable.claim_worker_job(followup.root, worker_id="redaction-claim")
    first = followup_chat.execute(followup.authorized, job, lambda: False, lambda: None)
    repeated = followup_chat.execute(followup.authorized, job, lambda: False, lambda: None)
    assert repeated["message_id"] == first["message_id"] and repeated["replayed"]
    assert "[REDACTED]" in _rows(followup, opened)[0]["content"]


def test_repeated_storage_failure_is_bounded_not_reported_as_delivery(followup, monkeypatch):
    opened = _start(followup, _create(followup))
    monkeypatch.setattr(chief_agent, "_touch_conversation", lambda *a, **k: (_ for _ in ()).throw(OSError("fixture persistent index failure")))
    for index in range(3):
        result = local_worker.run_once(worker_id="bounded-" + str(index))
    assert result["status"] == "failed" and result["attempts"] == 3 and result["result"] == {}
    assert len(_rows(followup, opened)) == 1
    assert local_worker.run_once(worker_id="no-hidden-retry") is None


def test_source_references_and_future_date_are_not_executable_provider_input(followup):
    opened = _start(followup, _create(followup, "calendar"), "calendar")
    result = local_worker.run_once(worker_id="date-is-not-dispatch")
    assert result["status"] == "succeeded"
    assert all(job["kind"] == "agent_world_followup" for job in durable.list_worker_jobs(followup.root))
    for kind in (EntityKind.TASK, EntityKind.EVALUATION, EntityKind.EXECUTION):
        assert followup.repo.list(context=followup.context, kind=kind, page=PageRequest()).items == ()
    assert _rows(followup, opened)[0]["actions"][0]["manual_review_required"] is True
