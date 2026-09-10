"""A refused preflight must not become a forever-queued orphan or a replay.

Disposable Task/Intent repositories and the normal local durable queue only.
Provider transmission is the explicitly named synthetic fixture executor.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app import local_worker, worker_router
from app.ai_control_center import execution_v2 as v2
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_persona_chat_execution import (
    _enable_persona_v2, _jobs, _rows, _start, persona_chat,
    ordinary, isolated_runtime, owner,
)


def _reject_selected_scope(monkeypatch):
    """Recreate the e45 mismatch; exercise the actual immutable-scope guard."""
    original = v2._request

    def old_request(checkpoint):
        value = original(checkpoint)
        value.pop("persona_selection", None)
        return value

    monkeypatch.setattr(v2, "_request", old_request)
    return original


def _one_task(fixture):
    records = list(fixture.service._all(fixture.context, EntityKind.TASK))
    assert len(records) == 1
    return records[0]


def _assert_rejection(fixture, code):
    task = _one_task(fixture)
    checkpoint = fixture.service._json(fixture.context, task.checkpoint)
    detail = fixture.service.task_detail(context=fixture.context, task_id=task.header.entity_id)
    assert task.status == detail["display_status"] == "blocked"
    assert detail["error_code"] == code and checkpoint["enqueue_rejected"] is True
    assert detail["is_active"] is False and detail["needs_attention"] is True
    assert detail["human_review"]["status"] == "not_required"
    assert not detail["result_received"] and detail["evaluation"] is None
    assert "review_result" not in detail["actions"]
    intent = fixture.service._get(fixture.context, EntityKind.INTENT, task.intent.entity_id)
    assert intent.status == "blocked"
    assert fixture.service._execution(fixture.context, task.header.entity_id).status == "cancelled"
    assert not _jobs(fixture) and not fixture.calls
    rows = _rows(fixture)
    assert len([row for row in rows if row.get("role") == "user"]) == 1
    assert not [row for row in rows if row.get("role") == "assistant"]
    # The ready revision and its original selected identity remain immutable.
    old = fixture.service.repository.get_revision(context=fixture.context, kind=EntityKind.TASK,
        entity_id=task.header.entity_id, revision=2)
    assert old.status == "ready"
    before = fixture.service._json(fixture.context, old.checkpoint)
    assert "error_code" not in before and "enqueue_rejected" not in before
    assert checkpoint["persona_selection"] == before["persona_selection"]
    assert checkpoint["request_sha256"] == before["request_sha256"]
    assert checkpoint["conversation_id"] == fixture.conversation
    assert checkpoint["message_id"] == rows[0]["message_id"]
    return task


def test_actual_selected_persona_preflight_refusal_preserves_blocked_task_and_intent(persona_chat, monkeypatch):
    fixture = persona_chat
    _enable_persona_v2(fixture, monkeypatch)
    _reject_selected_scope(monkeypatch)
    with pytest.raises(ContractError, match="execution_v2_approved_scope_changed"):
        _start(fixture)
    _assert_rejection(fixture, "execution_v2_approved_scope_changed")


def test_refused_same_request_never_claims_queued_or_retries_after_guard_is_fixed(persona_chat, monkeypatch):
    fixture = persona_chat
    _enable_persona_v2(fixture, monkeypatch)
    original = _reject_selected_scope(monkeypatch)
    with pytest.raises(ContractError, match="execution_v2_approved_scope_changed"):
        _start(fixture)
    task = _assert_rejection(fixture, "execution_v2_approved_scope_changed")
    monkeypatch.setattr(v2, "_request", original)

    def replay(_):
        with pytest.raises(ContractError, match="execution_v2_approved_scope_changed"):
            _start(fixture)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(replay, range(4)))
    assert _assert_rejection(fixture, "execution_v2_approved_scope_changed") == task

    # New explicit request, not a resurrection or erasure of the old one.
    accepted = _start(fixture, key="persona-explicit-new-request")
    assert accepted["task_id"] != str(task.header.entity_id)
    assert len(_jobs(fixture)) == 1 and not fixture.calls
    local_worker.run_once(worker_id="preflight-explicit-new-worker")
    assert len(fixture.calls) == 1
    old = fixture.service._get(fixture.context, EntityKind.TASK, task.header.entity_id)
    assert old == task


def test_post_enqueue_contract_error_is_not_recorded_as_preflight_rejection(persona_chat, monkeypatch):
    fixture = persona_chat
    _enable_persona_v2(fixture, monkeypatch)
    original = worker_router.enqueue

    def submitted_then_lost_response(*args, **kwargs):
        original(*args, **kwargs)
        # Same code as the preflight case: the call site, not the string,
        # determines whether lack of a queue side effect is actually proven.
        raise ContractError("execution_v2_approved_scope_changed")

    monkeypatch.setattr(worker_router, "enqueue", submitted_then_lost_response)
    with pytest.raises(ContractError, match="execution_v2_approved_scope_changed"):
        _start(fixture)
    task = _one_task(fixture)
    checkpoint = fixture.service._json(fixture.context, task.checkpoint)
    assert task.status == "ready" and "enqueue_rejected" not in checkpoint
    assert "error_code" not in checkpoint and len(_jobs(fixture)) == 1 and not fixture.calls
    monkeypatch.setattr(worker_router, "enqueue", original)
    accepted = _start(fixture)
    assert accepted["task_id"] == str(task.header.entity_id) and len(_jobs(fixture)) == 1
    local_worker.run_once(worker_id="preflight-queue-ack-worker")
    assert len(fixture.calls) == 1


def test_prepare_refusal_cannot_overwrite_a_job_enqueued_by_another_submission(persona_chat, monkeypatch):
    fixture = persona_chat
    _enable_persona_v2(fixture, monkeypatch)
    original = v2.prepare

    def another_submission(auth, service, task_id):
        original(auth, service, task_id)
        task = service._get(fixture.context, EntityKind.TASK, task_id)
        worker_router.enqueue("agent_world_model", {"task_id": task_id, "scope": auth["chat_scope"]},
            user_id=auth["source_scope"]["user_id"], workspace_id=fixture.context.scope.workspace_id,
            job_id="wj_aw_model_" + task.header.entity_id.hex, max_attempts=3, timeout_sec=180, priority=55)
        raise ContractError("execution_v2_approved_scope_changed")

    monkeypatch.setattr(v2, "prepare", another_submission)
    with pytest.raises(ContractError, match="execution_v2_approved_scope_changed"):
        _start(fixture)
    task = _one_task(fixture)
    assert task.status == "ready"
    assert "enqueue_rejected" not in fixture.service._json(fixture.context, task.checkpoint)
    assert fixture.service._execution(fixture.context, task.header.entity_id).status == "queued"
    assert len(_jobs(fixture)) == 1 and not fixture.calls
    monkeypatch.setattr(v2, "prepare", original)
    local_worker.run_once(worker_id="preflight-other-submission-worker")
    assert len(fixture.calls) == 1


def test_non_contract_prepare_interruption_is_not_declared_safe_rejection(persona_chat, monkeypatch):
    fixture = persona_chat
    _enable_persona_v2(fixture, monkeypatch)

    def interrupted(*_args):
        raise OSError("isolated interrupted persistence")

    monkeypatch.setattr(v2, "prepare", interrupted)
    with pytest.raises(OSError, match="isolated interrupted persistence"):
        _start(fixture)
    task = _one_task(fixture)
    assert task.status == "ready"
    assert "enqueue_rejected" not in fixture.service._json(fixture.context, task.checkpoint)
    assert not _jobs(fixture) and not fixture.calls
