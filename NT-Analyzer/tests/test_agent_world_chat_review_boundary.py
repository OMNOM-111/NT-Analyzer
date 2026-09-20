"""A saved ledger projection must not be accepted/rated by legacy chat timers."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.ai_lab import ai_ratings, chief_agent


def _row(source="agent_world_local", status="awaiting_review"):
    return {"role": "assistant", "message_id": "AW-REVIEW-1", "source": source,
            "content": "Результат получен, ожидается проверка.", "message_kind": "report",
            "timestamp_utc": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
            "fulfillment": "unset", "actions": [{"name": "real_model_response", "status": status}]}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    path = tmp_path / "conversation.jsonl"
    monkeypatch.setattr(chief_agent, "_conversation_file", lambda *a, **k: path)
    monkeypatch.setattr(ai_ratings, "record_rating", lambda *a, **k: pytest.fail("legacy rating side effect"))
    monkeypatch.setattr(chief_agent, "_remember_user_memory", lambda *a, **k: pytest.fail("legacy feedback memory side effect"))
    return path


@pytest.mark.parametrize("source", ["agent_world_local", "agent_world_preview"])
@pytest.mark.parametrize("status", ["queued", "running", "awaiting_review", "completed", "error", "blocked"])
def test_time_does_not_change_agent_world_history_or_review(isolated, source, status):
    row = _row(source, status)
    chief_agent.write_jsonl_atomic(isolated, [row])
    before = isolated.read_bytes()
    chief_agent._apply_auto_fulfillment(isolated)
    assert isolated.read_bytes() == before
    assert chief_agent.read_jsonl(isolated) == [row]


@pytest.mark.parametrize("operation", ["fulfillment", "rating"])
@pytest.mark.parametrize("source", ["agent_world_local", "agent_world_preview"])
def test_legacy_mutation_cannot_replace_canonical_task_review(isolated, operation, source):
    row = _row(source)
    chief_agent.write_jsonl_atomic(isolated, [row])
    before = isolated.read_bytes()
    with pytest.raises(chief_agent.ChiefAgentError, match="карточке задачи"):
        if operation == "fulfillment":
            chief_agent.set_message_fulfillment("default", row["message_id"], "done")
        else:
            chief_agent.rate_message("default", row["message_id"], 1, "Не засчитывать")
    assert isolated.read_bytes() == before


@pytest.mark.parametrize("operation", ["rating", "penalty", "informational"])
def test_background_helpers_cannot_promote_agent_world_to_legacy_quality(isolated, operation):
    row = _row()
    original = deepcopy(row)
    if operation == "rating":
        chief_agent._record_message_rating(row, 3, source="owner")
    elif operation == "penalty":
        chief_agent._apply_fulfillment_side_effects(row, "failed")
    else:
        chief_agent._record_informational_auto_rating(row)
    assert row == original


def test_historical_marks_and_errors_are_not_rewritten(isolated):
    row = {**_row(status="error"), "fulfillment": "done", "fulfillment_source": "auto",
           "rating": 3, "rating_event_id": "historic-event", "feedback_comment": "Историческая запись"}
    chief_agent.write_jsonl_atomic(isolated, [row])
    before = isolated.read_bytes()
    chief_agent._apply_auto_fulfillment(isolated)
    assert isolated.read_bytes() == before


def test_source_less_historical_agent_world_action_is_not_rated(isolated):
    row = {**_row(source=""), "actions": [{"name": "agent_world_preview", "status": "completed"}]}
    assert chief_agent._is_agent_world_message(row)
    chief_agent._record_message_rating(row, 3, source="owner")
    assert "rating_event_id" not in row


def test_ordinary_chat_behavior_is_not_reimplemented(isolated):
    row = _row(source="app", status="completed")
    chief_agent.write_jsonl_atomic(isolated, [row])
    chief_agent._apply_auto_fulfillment(isolated)
    saved = chief_agent.read_jsonl(isolated)[0]
    assert saved["fulfillment"] == "done" and saved["fulfillment_source"] == "auto"
    assert not chief_agent._is_agent_world_message(saved)


def test_pending_review_is_open_in_inference():
    actions = [{"name": "real_model_response", "status": "awaiting_review"}]
    assert chief_agent._infer_fulfillment(actions, "report") == "unset"
