"""Native external tasks share the ordinary task read/review seam, not Model IDs."""
from dataclasses import replace
from uuid import uuid4

import pytest

from app.ai_control_center import domain_gateway as gateway
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_external_agent_native_e2e import external, world, act, connected, drain  # noqa: F401


@pytest.mark.parametrize("decision,display", [("accept", "completed"), ("reject", "rejected")])
def test_external_task_known_id_overview_explicit_review_and_foreign_denial(external, decision, display):
    env = external
    prior_models = list(env.service._all(env.context, EntityKind.MODEL))
    connection = connected(env, key="task-read")
    started = act(env, connection["id"], "task", {"input_text": "[17,-4,12,9]"}, key="task-read-native")
    identity = started["started_task_id"]
    queued = gateway.task_detail(env.authorized, identity)
    assert queued["task"]["display_status"] == "queued"
    assert queued["task"]["model_id"] is None
    drain()
    detail = gateway.task_detail(env.authorized, identity)
    assert detail["task"]["status"] == "review"
    assert detail["task"]["display_status"] == "awaiting_review"
    assert detail["human_review"]["status"] == "pending"
    assert "graph" not in detail
    assert detail["result_text"].startswith("{") and "\\\"" not in detail["result_text"]
    assert detail["task"]["verification_status"] == "passed"
    assert detail["task"]["cost_usd"] is None  # Old receipts do not record measured money.
    connection_view = gateway.list_domain(env.authorized, "external_agents", identity=connection["id"])
    assert connection_view["statistics"]["tasks_completed"] == 1
    assert connection_view["statistics"]["results_received"] == 1
    assert connection_view["statistics"]["reviews_completed"] == 0
    assert connection_view["statistics"]["awaiting_review"] == 1
    overview = gateway.enrich_overview(env.authorized)
    row = next(row for row in overview["tasks"] if row["id"] == identity)
    assert row["human_review"] == detail["human_review"]
    assert row["display_status"] == "awaiting_review"
    attention = next(row for row in overview["attention"] if row["id"] == identity)
    assert "автоматическая проверка пройдена" in attention["reason"]
    assert "не подтвердила формат" not in attention["reason"]
    assert detail["evaluation"]["performance_scope"] == "external_agent_performance"
    with pytest.raises(ContractError, match="task_review_result_required"):
        gateway.mutate(env.authorized, "tasks", identity, "review_result", {
            "expected_revision": detail["revision"], "idempotency_key": "human-external-wrong-source",
            "payload": {"decision": decision, "source_sha256": "0" * 64}})
    reviewed = gateway.mutate(env.authorized, "tasks", identity, "review_result", {
        "expected_revision": detail["revision"], "idempotency_key": "human-external-review",
        "payload": {"decision": decision, "comment": "Synthetic mechanism only",
                    "source_sha256": detail["human_review"]["source_sha256"]}})
    assert reviewed["task"]["display_status"] == display
    assert gateway.task_detail(env.authorized, identity)["task"]["display_status"] == display
    assert next(row for row in gateway.enrich_overview(env.authorized)["tasks"] if row["id"] == identity)["display_status"] == display
    review = env.service._get(env.context, EntityKind.EVALUATION, reviewed["human_review"]["evaluation_id"])
    assert review.subject.kind is EntityKind.EXTERNAL_AGENT_CONNECTION
    assert review.rubric_key == "human_review"
    after = gateway.list_domain(env.authorized, "external_agents", identity=connection["id"])
    assert after["statistics"]["results_received"] == 1
    assert after["statistics"]["reviews_completed"] == 1
    assert after["statistics"]["awaiting_review"] == 0
    assert after["tasks"][0]["display_status"] == display
    assert list(env.service._all(env.context, EntityKind.MODEL)) == prior_models
    stranger_id = uuid4()
    stranger = replace(env.context, user_uuid=stranger_id, actor=replace(env.context.actor, actor_id=stranger_id))
    with pytest.raises(ContractError):
        gateway.task_detail({**env.authorized, "context": stranger}, identity)
    foreign = replace(env.context, scope=replace(env.context.scope, workspace_id="ws_other_external_reader"))
    with pytest.raises(ContractError):
        gateway.task_detail({**env.authorized, "context": foreign}, identity)
