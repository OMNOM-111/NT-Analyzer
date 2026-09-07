"""Due-time scheduling, existing queue claims, no external connection."""
import copy
from datetime import datetime, timedelta, timezone

import pytest

from app import durable, local_worker
from app.ai_control_center import scheduler, domain_gateway
from app.ai_control_center.domain_service import DomainService
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_control_center.flags import FlagSnapshot
from tests.test_agent_world_delegation import (mechanism, env, target, model_setup, chat_authorized,
    queue_service, canonical_queue, run_claimed)


def spec(start=None, **changes):
    start = start or datetime.now(timezone.utc) - timedelta(seconds=2)
    return {"local_start": start.replace(tzinfo=None).isoformat(timespec="seconds"), "timezone": "UTC",
        "interval_seconds": 0, "occurrences": 1, "grace_seconds": 300, **changes}


def source(env, *, domain="routines", start=None):
    service = DomainService(env.service.repository, enqueue=lambda **kwargs: domain_gateway._followup(env.authorized, **kwargs))
    payload = {"title": "Проверка согласованного источника", "description": "Отдельное разрешение необходимо."}
    if domain == "routines": payload["interval_minutes"] = 5
    else:
        at = start or datetime.now(timezone.utc)
        payload.update(starts_at=at.isoformat(), ends_at=(at + timedelta(minutes=30)).isoformat())
    item = service.create(context=env.ctx, admit=env.authorized["admit"], domain=domain,
        payload=payload, idempotency_key="manual-source-create")["item"]
    accepted = service.act(context=env.ctx, admit=env.authorized["admit"], domain=domain, entity_id=item["id"],
        action="accept", payload={}, expected_revision=item["revision"], idempotency_key="manual-source-accept")["item"]
    return service, accepted


def create(env, *, schedule=None, domain="routines", key="explicit-schedule-one"):
    schedule = schedule or spec()
    domain_service, item = source(env, domain=domain, start=scheduler.d.utc(scheduler.occurrence_times(schedule)[0]))
    result = scheduler.create(env.authorized, env.service, domain_service, domain=domain, identity=item["id"],
        expected_revision=item["revision"], model_id=env.receiver["id"], schedule=schedule,
        payload={"rubric_key": "extract_facts", "input_text": "action=review\nsource=approved_record"},
        idempotency_key=key, grant_ref=env.approval, conversation_id=env.source["conversation_id"], message_id=env.source["message_id"])
    return domain_service, item, result


def test_timezone_rejects_dst_gap_and_requires_explicit_fold():
    with pytest.raises(ContractError, match="nonexistent"):
        scheduler.occurrence_times(spec(local_start="2026-03-08T02:30:00", timezone="America/Los_Angeles"))
    repeated = spec(local_start="2026-11-01T01:30:00", timezone="America/Los_Angeles")
    with pytest.raises(ContractError, match="ambiguous"):
        scheduler.occurrence_times(repeated)
    first = scheduler.occurrence_times({**repeated, "fold": 0})
    second = scheduler.occurrence_times({**repeated, "fold": 1})
    assert scheduler.d.utc(second[0]) - scheduler.d.utc(first[0]) == timedelta(hours=1)


@pytest.mark.parametrize("change", [{"occurrences": 11}, {"occurrences": True}, {"occurrences": 2},
    {"interval_seconds": 1}, {"interval_seconds": -1}, {"grace_seconds": 0}, {"grace_seconds": 3601},
    {"timezone": "not/a/zone"}, {"timezone": "UTC", "fold": 2}, {"local_start": "2026-09-05T10:00:00+00:00"}])
def test_schedule_inputs_are_finite_and_unambiguous(change):
    with pytest.raises(ContractError): scheduler.occurrence_times(spec(**change))


def test_recurrence_is_fixed_elapsed_time_across_dst_not_hidden_wall_clock_cron():
    dates = scheduler.occurrence_times(spec(local_start="2026-11-01T00:30:00", timezone="America/Los_Angeles",
        interval_seconds=3600, occurrences=3))
    assert [scheduler.d.utc(value).hour for value in dates] == [7, 8, 9]


def test_accepting_manual_source_never_creates_autonomous_schedule(mechanism):
    env = mechanism
    domain_service, item = source(env)
    before = len(list(env.service._all(env.ctx, EntityKind.TASK)))
    assert scheduler.scan_due(env.authorized, env.service) == []
    assert len(list(env.service._all(env.ctx, EntityKind.TASK))) == before
    current = domain_service.get(context=env.ctx, admit=env.authorized["admit"], domain="routines", entity_id=item["id"])
    assert current["automation_enabled"] is False
    assert not env.calls


def test_future_due_time_is_not_queued_or_reported_delivered(mechanism):
    env = mechanism
    _, _, opened = create(env, schedule=spec(datetime.now(timezone.utc) + timedelta(minutes=10)))
    before = len(durable.list_worker_jobs(local_worker._root()))
    view = scheduler.tick(env.authorized, env.service, opened["id"])
    assert view["occurrences"][0]["status"] == "scheduled" and view["occurrences"][0]["task_id"] is None
    assert len(durable.list_worker_jobs(local_worker._root())) == before and not env.calls


@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_due_occurrence_dispatches_one_existing_model_task_and_preserves_manual_source(mechanism, domain):
    env = mechanism
    service, item, opened = create(env, domain=domain)
    first = scheduler.tick(env.authorized, env.service, opened["id"])
    second = scheduler.tick(env.authorized, env.service, opened["id"])
    assert first["occurrences"] == second["occurrences"]
    for _ in range(15):
        run_claimed(env)
        view = scheduler.tick(env.authorized, env.service, opened["id"])
        if view["status"] == "review": break
    assert view["status"] == "review" and view["occurrences"][0]["status"] == "succeeded"
    assert len(env.calls) == 1 and view["human_accepted"] is False
    current = service.get(context=env.ctx, admit=env.authorized["admit"], domain=domain, entity_id=item["id"])
    assert current["revision"] == item["revision"] and current["automation_enabled"] is False
    assert scheduler.tick(env.authorized, env.service, opened["id"])["status"] == "review"
    for _ in range(10):
        if run_claimed(env) is None: break  # Independent original manual receipt is preserved.
    assert run_claimed(env) is None and len(env.calls) == 1


def test_missed_occurrence_records_truth_without_late_provider_dispatch(mechanism):
    env = mechanism
    _, _, opened = create(env, schedule=spec(datetime.now(timezone.utc) - timedelta(minutes=10), grace_seconds=5))
    view = scheduler.tick(env.authorized, env.service, opened["id"])
    assert view["status"] == "review" and view["occurrences"][0]["status"] == "missed"
    assert view["occurrences"][0]["recorded_at"] and not env.calls
    assert not any(job["payload"].get("phase") == scheduler.PHASE for job in durable.list_worker_jobs(local_worker._root()))


def test_revoked_grant_or_changed_accepted_source_prevents_dispatch(mechanism):
    env = mechanism
    service, item, opened = create(env)
    env.grant_state["active"] = False
    with pytest.raises(ContractError, match="revoked"): scheduler.tick(env.authorized, env.service, opened["id"])
    env.grant_state["active"] = True
    service.act(context=env.ctx, admit=env.authorized["admit"], domain="routines", entity_id=item["id"], action="dismiss",
        payload={}, expected_revision=item["revision"], idempotency_key="dismiss-scheduled-source")
    with pytest.raises(ContractError): scheduler.tick(env.authorized, env.service, opened["id"])
    assert not env.calls


def test_schedule_cannot_outlive_separate_automation_approval(mechanism):
    env = mechanism
    with pytest.raises(ContractError, match="approval_expiry"):
        create(env, schedule=spec(datetime.now(timezone.utc) + timedelta(days=1)))
    assert not env.calls


def test_cancel_stops_pending_occurrences_without_provider_call(mechanism):
    env = mechanism
    _, _, opened = create(env)
    scheduler.tick(env.authorized, env.service, opened["id"])
    assert scheduler.cancel(env.authorized, env.service, opened["id"])["status"] == "cancelled"
    assert scheduler.tick(env.authorized, env.service, opened["id"])["status"] == "cancelled" and not env.calls


def test_scanner_recovery_is_read_only_before_due_and_explicitly_bounded(mechanism):
    env = mechanism
    _, _, opened = create(env, schedule=spec(datetime.now(timezone.utc) + timedelta(minutes=5)))
    result = scheduler.scan_due(env.authorized, env.service, limit=1)
    assert len(result) == 1 and result[0]["id"] == opened["id"] and not env.calls
    with pytest.raises(ContractError): scheduler.scan_due(env.authorized, env.service, limit=0)
    with pytest.raises(ContractError): scheduler.scan_due(env.authorized, env.service, limit=101)


def test_exact_schedule_proposal_has_no_side_effect_before_separate_approval(mechanism):
    env = mechanism
    service, item = source(env)
    before = len(list(env.service._all(env.ctx, EntityKind.TASK)))
    jobs = len(durable.list_worker_jobs(local_worker._root()))
    proposed = scheduler.propose(env.authorized, env.service, service, domain="routines", identity=item["id"],
        expected_revision=item["revision"], model_id=env.receiver["id"], schedule=spec(),
        payload={"rubric_key": "extract_facts", "input_text": "action=review\nsource=approved_record"},
        idempotency_key="read-only-proposal", conversation_id=env.source["conversation_id"], message_id=env.source["message_id"])
    assert not {"grant_ref", "expires_at"} & set(proposed["plan"])
    assert len(list(env.service._all(env.ctx, EntityKind.TASK))) == before
    assert len(durable.list_worker_jobs(local_worker._root())) == jobs and not env.grant_state["calls"]


def test_due_controller_precedes_future_controller_in_bounded_recovery_scan(mechanism):
    env = mechanism
    _, _, future = create(env, schedule=spec(datetime.now(timezone.utc) + timedelta(minutes=5)), key="future-controller")
    _, _, due = create(env, key="current-controller")
    found = scheduler.scan_due(env.authorized, env.service, limit=1)
    assert [row["id"] for row in found] == [due["id"]]
    assert found[0]["occurrences"][0]["status"] == "queued"
    assert scheduler.projection(env.authorized, env.service, future["id"])["occurrences"][0]["status"] == "scheduled"


def test_kill_switch_does_not_prevent_schedule_cancellation(mechanism):
    env = mechanism
    _, _, opened = create(env)
    scheduler.tick(env.authorized, env.service, opened["id"])
    env.authorized["snapshot"] = FlagSnapshot()
    env.grant_state["active"] = False
    assert scheduler.cancel(env.authorized, env.service, opened["id"])["status"] == "cancelled"
    assert not env.calls


def test_queued_occurrence_rechecks_source_and_due_before_provider_call(mechanism):
    env = mechanism
    service, item, opened = create(env)
    scheduler.tick(env.authorized, env.service, opened["id"])
    for _ in range(12):
        done = run_claimed(env)
        if done and done[0]["payload"].get("phase") == scheduler.PHASE: break
    service.act(context=env.ctx, admit=env.authorized["admit"], domain="routines", entity_id=item["id"], action="dismiss",
        payload={}, expected_revision=item["revision"], idempotency_key="source-withdrawn-before-send")
    for _ in range(12):
        if run_claimed(env) is None: break
    child = env.service._get(env.ctx, EntityKind.TASK, scheduler._child_id(env.ctx, opened["id"], 0))
    assert child.status == "blocked" and not env.calls
