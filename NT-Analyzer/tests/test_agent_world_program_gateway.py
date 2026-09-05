"""Program gateway action/projection contracts on disposable synthetic fixtures.

These are not live-provider or owner-acceptance evidence. Real gateway routes,
SQLite services, queue and SF Chat files are exercised under temporary roots;
auth/session membership and model/source seams are controlled by test fixtures.
No provider, browser, live Local runtime or production connection is used.
"""
from __future__ import annotations

import copy
import json
from uuid import uuid4

import pytest

from app import durable, local_worker, worker_router
from app.ai_control_center import domain_gateway as gateway, result_handoff
from tests.test_agent_world_application_evaluation import complete
from tests.test_agent_world_domain_gateway import http_get, http_post, models, ordinary
from tests.test_agent_world_followup_chat import followup, _create, _counts, _rows, _start
from tests.test_agent_world_live_gateway import isolated_runtime, owner
from tests.test_agent_world_ui import evaluate


def _handoff_body(**change):
    return {"payload": {"target_model_id": str(uuid4())},
            "idempotency_key": "synthetic-program-handoff", **change}


def _application(models, *, source="synthetic-source-one", key="program-source-one"):
    # Deliberately surrogate source bytes: this verifies gateway aggregation,
    # not actual PNG/report ingestion (covered by the application suites).
    return complete((models.service, models.context, models.payload),
        model=models.model, source_id=source, key=key)[1]


@pytest.mark.parametrize("domain", ["tasks", "model_tasks"])
def test_handoff_aliases_forward_only_target_with_normalized_session_authority(models, monkeypatch, domain):
    calls = []
    source, body = str(uuid4()), _handoff_body()

    def start(authorized, service, task_id, target_model_id, key):
        calls.append((authorized, service, task_id, target_model_id, key))
        return {"id": source, "status": "ready", "synthetic": False}

    monkeypatch.setattr(result_handoff, "start", start)
    before = len(models.executions)
    handler = http_post(models.account, f"domains/{domain}/{source}/handoff", body)
    assert handler.status == 200 and handler.result["status"] == "ready"
    assert len(calls) == 1
    authorized, service, task_id, target_model_id, key = calls[0]
    assert authorized["read_only"] is False
    assert authorized["chat_scope"]["is_owner"] is False
    assert authorized["chat_scope"]["uses_owner_runtime"] is False
    assert authorized["chat_scope"]["auth_session_id"] == "confirmed-domain-session"
    assert service.repository is models.repository
    assert (task_id, target_model_id, key) == (source, body["payload"]["target_model_id"], body["idempotency_key"])
    assert len(models.executions) == before and models.queue == {} and models.chat == {}


@pytest.mark.parametrize("domain", ["tasks", "model_tasks"])
@pytest.mark.parametrize("attack", ["facts", "workspace", "chat_scope", "parent", "empty", "top_level"])
def test_handoff_rejects_client_facts_scope_lineage_and_unknown_body_before_dispatch(models, monkeypatch, domain, attack):
    body = _handoff_body()
    if attack == "top_level":
        body["workspace_id"] = "ws_other_scope"
    elif attack == "empty":
        body["payload"] = {}
    else:
        body["payload"][attack] = {"synthetic": "client supplied authority"}
    monkeypatch.setattr(result_handoff, "start", lambda *a, **k: pytest.fail("invalid DTO reached handoff"))
    before = len(models.executions)
    handler = http_post(models.account, f"domains/{domain}/{uuid4()}/handoff", body)
    assert handler.status == 409 and handler.result["code"] == "invalid_domain_request"
    assert len(models.executions) == before and models.queue == {} and models.chat == {}


@pytest.mark.parametrize("domain", ["tasks", "model_tasks"])
def test_readonly_session_cannot_handoff_even_when_subscription_and_workspace_allow_it(models, monkeypatch, domain):
    models.account.state["permissions"]["role"] = "read_only"
    monkeypatch.setattr(result_handoff, "start", lambda *a, **k: pytest.fail("readonly session reached handoff"))
    handler = http_post(models.account, f"domains/{domain}/{uuid4()}/handoff", _handoff_body())
    assert handler.status >= 400
    assert models.queue == {} and models.chat == {}


@pytest.mark.parametrize("domain", ["routines", "calendar"])
@pytest.mark.parametrize("revocation", ["membership", "capability", "session_role"])
def test_followup_actions_match_readonly_authority_in_list_and_detail(followup, domain, revocation):
    item = _create(followup, domain)
    state = followup.account.state
    if revocation == "membership":
        state["workspaces"][followup.account.scope["workspace_id"]]["membership"]["role"] = "viewer"
    elif revocation == "capability":
        state["permissions"]["capabilities"]["ai_lab"] = False
    else:
        # Session authority is separate from a paid plan and workspace owner.
        state["permissions"]["role"] = "read_only"
    before = _counts(followup)
    route = f"domains/{domain}/{item['id']}"
    detail = http_get(followup.account, route)
    listed = http_get(followup.account, f"domains/{domain}")
    assert detail.status == listed.status == 200
    row = next(value for value in listed.result["items"] if value["id"] == item["id"])
    assert detail.result["status"] == row["status"] == "accepted"
    assert detail.result["actions"] == row["actions"] == []
    assert detail.result["automation_enabled"] is row["automation_enabled"] is False
    assert detail.result["followup_chat"] is row["followup_chat"] is None
    denied = http_post(followup.account, route + "/open_chat", {
        "payload": {}, "expected_revision": item["revision"], "idempotency_key": "readonly-open-chat"})
    assert denied.status >= 400
    assert _counts(followup) == before and len(durable.list_worker_jobs(followup.root)) == 1


@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_followup_queued_to_delivered_projects_actual_receipt_without_task_or_rating(followup, domain):
    item = _create(followup, domain)
    opened = _start(followup, item, domain)
    before = _counts(followup)
    route = f"domains/{domain}/{item['id']}"
    pending = http_get(followup.account, route)
    assert pending.status == 200 and pending.result["followup_chat"]["status"] == "queued"
    assert pending.result["followup_chat"]["message_id"] is None
    pending_html = evaluate("ui.followupCard(" + json.dumps(pending.result) + ")")
    assert "data-aw-followup-chat" not in pending_html
    assert _rows(followup, opened) == [] and _counts(followup) == before
    delivered = local_worker.run_once(worker_id="synthetic-program-delivery")
    assert delivered["status"] == "succeeded"
    # A history-only account may reopen the existing neutral message without
    # receiving a new mutation action or artificial task/model evaluation.
    followup.account.state["permissions"]["capabilities"]["ai_lab"] = False
    detail = http_get(followup.account, route)
    dto = detail.result["followup_chat"]
    assert detail.status == 200 and detail.result["actions"] == []
    assert dto["status"] == "delivered" and dto["message_id"] == _rows(followup, opened)[0]["message_id"]
    html = evaluate("ui.followupCard(" + json.dumps(detail.result) + ")")
    assert "data-aw-followup-chat" in html and "не выполненное задание модели" in html
    assert "data-orch-rate" not in html
    message = _rows(followup, opened)[0]
    assert message["role"] == "system" and message["participation_chain"] == []
    assert not message.get("rating_event_id") and not message.get("model")
    assert followup.account.calls["budget"] == []
    overview = http_get(followup.account, "overview")
    assert overview.status == 200 and overview.result["tasks"] == []
    assert overview.result["stats"]["evaluations"] == 0
    # Overview may query the existing zero-cost budget gate to hide unavailable
    # model actions. The neutral reminder never charges/reserves model work.
    assert all(amount == 0.0 for _, amount in followup.account.calls["budget"])


@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_invalidated_source_hides_manual_action_and_explains_limit_without_new_work(followup, monkeypatch, domain):
    item = _create(followup, domain)
    original = worker_router.get

    def changed(identity, **kwargs):
        job = original(identity, **kwargs)
        if job is not None and job["kind"] == "agent_world_followup":
            job = {**job, "status": "failed"}
        return job

    monkeypatch.setattr(worker_router, "get", changed)
    before = _counts(followup)
    handler = http_get(followup.account, f"domains/{domain}/{item['id']}")
    assert handler.status == 200 and "open_chat" not in handler.result["actions"]
    assert any("Источник ручного разбора недоступен" in text for text in handler.result["limitations"])
    assert _counts(followup) == before and len(durable.list_worker_jobs(followup.root)) == 1


def test_gateway_model_factories_supply_copied_trusted_chat_scope(followup):
    readonly = gateway.access(followup.account.scope, read_only=True)
    for authorized, service in [(followup.authorized, gateway.models(followup.authorized)),
                                (readonly, gateway.history_models(readonly))]:
        assert service.chat_scope == authorized["chat_scope"]
        assert service.chat_scope is not authorized["chat_scope"]
        assert service.chat_scope["auth_session_id"] == "confirmed-domain-session"
        assert service.chat_scope["is_owner"] is False


def test_overview_keeps_application_denominator_separate_and_never_rates_repeat_inputs(models):
    first = _application(models)
    second = _application(models, source="synthetic-source-two", key="program-source-two")
    before = (len(models.executions), copy.deepcopy(models.queue))
    result = http_get(models.account, "overview")
    assert result.status == 200
    overview = result.result
    assert {task["id"] for task in overview["tasks"]} == {first["id"], second["id"]}
    assert overview["stats"]["evaluations"] == 4  # two plan + two application observations
    agent = next(value for value in overview["agents"] if value["id"] == models.model["persona_id"])
    assert agent["evaluation"]["sample_size"] == 0 and agent["evaluation"]["label"] == "NEW"
    observed = agent["application_observations"][0]
    assert observed["denominator"] == "distinct_verified_application_requests"
    assert observed["sample_size"] == 1 and observed["receipt_count"] == 2
    chart = next(row for row in observed["classes"] if row["application_kind"] == "chart")
    assert chart["sample_size"] == 1 and chart["receipt_count"] == 2 and chart["label"] == "NEW"
    assert chart["score_pct"] is None and observed["score_pct"] is None
    assert observed["routing_effect"] == "none"
    assert http_get(models.account, "overview").result == overview
    assert (len(models.executions), models.queue) == before


@pytest.mark.parametrize("revocation", ["model_capability", "budget", "session_role"])
def test_overview_never_advertises_handoff_when_task_detail_denies_model_work(models, revocation):
    source = _application(models)
    assert source["actions"] == ["handoff"]
    if revocation == "model_capability":
        models.account.state["permissions"]["capabilities"]["ai_pro_models"] = False
    elif revocation == "budget":
        models.account.state["budget_ok"] = False
    else:
        models.account.state["permissions"]["role"] = "read_only"
    overview = http_get(models.account, "overview")
    detail = http_get(models.account, "tasks/" + source["id"])
    listed = http_get(models.account, "domains/model_tasks")
    assert overview.status == detail.status == listed.status == 200
    task = next(row for row in overview.result["tasks"] if row["id"] == source["id"])
    history = next(row for row in listed.result["items"] if row["id"] == source["id"])
    assert task["actions"] == detail.result["actions"] == history["actions"] == []
    assert detail.result["task"]["actions"] == []
    assert detail.result["application_evaluation"]["source_id"] == "synthetic-source-one"
    assert overview.result["agents"][0]["application_observations"][0]["sample_size"] == 1
    personas = http_get(models.account, "domains/personas")
    assert personas.status == 200
    assert personas.result["actions"] == ([] if revocation == "session_role" else ["create"])
