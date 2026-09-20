"""The owner's goal: stored as written, measured only on demo-account strategies."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.ai_control_center import goals
from app.ai_control_center.states import ContractError


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(goals, "runtime_env", SimpleNamespace(data_path=lambda *parts: tmp_path.joinpath(*parts)))
    return tmp_path


def authorized(workspace="ws_owner", environment="development", read_only=False):
    scope = SimpleNamespace(environment=SimpleNamespace(value=environment), workspace_id=workspace)
    return {"context": SimpleNamespace(scope=scope), "read_only": read_only}


def test_a_goal_is_kept_as_written_and_read_back(store):
    goals.save(authorized(), {"title": "  Стратегии на демо-счёте приносят $3 000 ", "horizon": "quarter",
                              "target_usd": 3000, "weekly_task": "Довести MNQ-LS до демо"})
    goal = goals.read(authorized())
    assert goal["title"] == "Стратегии на демо-счёте приносят $3 000"
    assert (goal["horizon"], goal["horizon_label"], goal["target_usd"]) == ("quarter", "Квартал", 3000.0)
    assert goal["weekly_task"] == "Довести MNQ-LS до демо"
    # The deadline follows the horizon: the last day of the current quarter.
    quarter_end = date.fromisoformat(goal["deadline"])
    assert quarter_end.month % 3 == 0 and quarter_end.day in {30, 31}
    # Progress is money on the demo account; nothing else is counted as progress.
    assert goal["progress_usd"] == 0 and goal["progress_source"] == "demo_account_strategies"


def test_each_workspace_and_environment_keeps_its_own_goal(store):
    goals.save(authorized(), {"title": "Цель владельца", "horizon": "month", "target_usd": 500})
    goals.save(authorized(workspace="ws_other"), {"title": "Чужая цель", "horizon": "year", "target_usd": 0})
    assert goals.read(authorized())["title"] == "Цель владельца"
    assert goals.read(authorized(workspace="ws_other"))["title"] == "Чужая цель"
    assert goals.read(authorized(environment="canary"))["title"] == ""


def test_an_empty_title_removes_the_goal_and_leaves_the_corner_empty(store):
    goals.save(authorized(), {"title": "Временная цель", "horizon": "month", "target_usd": 100})
    assert goals.save(authorized(), {"title": ""})["title"] == ""
    assert goals.read(authorized())["horizon_label"] == "срок не задан"


@pytest.mark.parametrize("payload", [
    {"title": "x" * 161},
    {"title": "Цель", "horizon": "decade"},
    {"title": "Цель", "target_usd": -1},
    {"title": "Цель", "target_usd": 10_000_001},
    {"title": "Цель", "target_usd": True},
    {"title": "Цель", "capability": "owner"},
])
def test_a_malformed_goal_is_refused(store, payload):
    with pytest.raises(ContractError):
        goals.save(authorized(), payload)


def test_a_read_only_session_cannot_write_a_goal(store):
    with pytest.raises(ContractError, match="goal_read_only"):
        goals.save(authorized(read_only=True), {"title": "Цель", "horizon": "month", "target_usd": 1})
