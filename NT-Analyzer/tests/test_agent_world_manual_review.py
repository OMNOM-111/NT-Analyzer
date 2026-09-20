"""The boundary between a human accepting a result and the evidence holding up.

Accepting is a human signal about a result that already passed its own
automatic check. It must not become a way to repair one: the button cannot
erase a deviation, cannot rewrite the hash the acceptance is bound to, and
cannot turn an unverified or damaged result into a verified one. What a machine
checked and what a person decided stay two separate facts in the record.

No provider, network, browser or owner data: the fixtures build a real task in
a disposable SQLite root and stop at the transport boundary.
"""
from __future__ import annotations

import pytest

from app.ai_control_center import task_review
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_result_handoff import (env, target, model_setup, chat_authorized,
                                                   queue_service, canonical_queue)


def detail(env):
    return env.service.task_detail(context=env.ctx, task_id=env.source["id"])


def submit(env, decision="accept", **changes):
    current = detail(env)
    review = current["human_review"]
    payload = {"decision": decision, "comment": "проверено владельцем",
               "source_sha256": review.get("source_sha256", "")}
    payload.update(changes.pop("payload", {}))
    return task_review.submit(
        env.service, context=env.ctx, task_id=env.source["id"], payload=payload,
        expected_revision=changes.pop("expected_revision", current["revision"]),
        idempotency_key=changes.pop("idempotency_key", "manual-review-one"))


def evaluations(env):
    return [row for row in env.service._all(env.ctx, EntityKind.EVALUATION)]


def test_a_correct_result_is_accepted_and_the_decision_is_a_separate_record(env):
    before = detail(env)
    assert before["human_review"]["status"] == "pending"
    assert "review_result" in before["actions"]
    assert before["display_status"] == "awaiting_review"
    machine_checks = {str(row.header.entity_id) for row in evaluations(env)}

    after = submit(env)
    review = after["human_review"]
    assert review["status"] == "accepted" and after["display_status"] == "completed"
    # A human signal, never a quality claim and never a second automatic check.
    assert review["quality_claim"] is False
    assert review["origin"] == "explicit_human_review"
    assert review["reviewer_user_uuid"] == str(env.ctx.user_uuid)
    assert review["comment"] == "проверено владельцем"

    # The decision is added beside the automatic evidence, not merged into it.
    added = {str(row.header.entity_id) for row in evaluations(env)} - machine_checks
    assert len(added) == 1
    record = env.service._get(env.ctx, EntityKind.EVALUATION, added.pop())
    assert record.rubric_key == task_review.RUBRIC
    assert str(record.header.created_by.actor_id) == str(env.ctx.user_uuid)
    proof = env.service._json(env.ctx, record.evidence)
    assert proof["decision"] == "accept" and proof["quality_claim"] is False
    # Bound to the revision and the exact result it was shown, not to "the task".
    assert proof["task_revision"] == before["revision"]
    assert proof["source_sha256"] == before["human_review"]["source_sha256"]

    # The automatic verdict the report shows is still the machine's own.
    assert after["evaluation_id"] == before["evaluation_id"]
    assert after["application_evaluation_id"] == before["application_evaluation_id"]


def test_a_stale_revision_is_refused_before_anything_is_written(env):
    before = detail(env)
    count = len(evaluations(env))
    with pytest.raises(ContractError) as stale:
        submit(env, expected_revision=before["revision"] + 1)
    assert stale.value.code == "task_review_stale"
    with pytest.raises(ContractError):
        submit(env, expected_revision=before["revision"] - 1)
    assert len(evaluations(env)) == count
    assert detail(env)["human_review"]["status"] == "pending"


def test_a_hash_that_does_not_match_the_shown_result_is_refused(env):
    count = len(evaluations(env))
    for value in ("", "0" * 64, "not-a-digest"):
        with pytest.raises(ContractError) as mismatch:
            submit(env, payload={"source_sha256": value})
        assert mismatch.value.code == "task_review_result_required"
    assert len(evaluations(env)) == count
    assert detail(env)["human_review"]["status"] == "pending"


def test_acceptance_cannot_rewrite_the_hash_it_is_bound_to(env):
    """The caller supplies a hash to be checked against, never to be stored."""
    before = detail(env)
    server_hash = before["human_review"]["source_sha256"]
    after = submit(env)
    assert after["human_review"]["source_sha256"] == server_hash
    record = env.service._get(env.ctx, EntityKind.EVALUATION,
                              task_review._identity(env.service, env.ctx,
                                                    env.service._get(env.ctx, EntityKind.TASK, env.source["id"])))
    assert env.service._json(env.ctx, record.evidence)["source_sha256"] == server_hash
    # And the fingerprint is still the one the server computes from the task.
    task = env.service._get(env.ctx, EntityKind.TASK, env.source["id"])
    checkpoint = env.service._json(env.ctx, task.checkpoint)
    assert task_review.fingerprint(task, checkpoint, after) == server_hash


def test_a_rejected_result_is_recorded_without_touching_the_result_itself(env):
    before = detail(env)
    after = submit(env, "reject")
    assert after["human_review"]["status"] == "rejected"
    assert after["display_status"] == "rejected"
    assert after["evaluation_id"] == before["evaluation_id"]
    assert after["result_text"] == before["result_text"]
    # A rejection is not a retraction of the machine's own verdict.
    assert after["evaluation"]["passed"] == before["evaluation"]["passed"]


def test_the_opposite_decision_cannot_be_recorded_afterwards(env):
    submit(env)
    with pytest.raises(ContractError) as conflict:
        submit(env, "reject", idempotency_key="manual-review-two")
    assert conflict.value.code == "task_review_already_recorded"
    assert detail(env)["human_review"]["status"] == "accepted"
    # The same decision replayed is idempotent, not a second record.
    replay = submit(env, idempotency_key="manual-review-three")
    assert replay["deduplicated"] is True
    assert len({row.header.entity_id for row in evaluations(env)
                if row.rubric_key == task_review.RUBRIC}) == 1


def test_a_result_with_no_automatic_check_offers_no_acceptance_at_all(env):
    """Nothing lets a human sign off on a result the machine never verified."""
    task = env.service._get(env.ctx, EntityKind.TASK, env.source["id"])
    checkpoint = env.service._json(env.ctx, task.checkpoint)
    projection = task_review.projection(env.service, env.ctx, task, checkpoint,
                                        {**detail(env), "evaluation_id": None})
    assert projection == {"status": "not_required", "quality_claim": False}
    running = task_review.projection(env.service, env.ctx, task, checkpoint,
                                     {**detail(env), "status": "running"})
    assert running["status"] == "not_required"
    # An application task whose own receipt was never verified is the same case.
    unverified = task_review.projection(env.service, env.ctx, task, checkpoint,
                                        {**detail(env), "application_evaluation_id": None})
    assert unverified["status"] == "not_required"
