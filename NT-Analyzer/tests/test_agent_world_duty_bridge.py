"""The duty controller's questions reach the owner through the deputy, not the old screens."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai_control_center import duty_bridge
from app.ai_control_center.states import ContractError

STATUS = {
    "ok": True, "mode": "busy", "message": "Проверяю подключение NinjaTrader",
    "worker_alive": True, "last_scan_at_utc": "2026-09-20T03:00:00Z",
    "rest": {"active": False, "until_utc": "", "reason": ""},
    "task_counts": {"running": 1, "waiting_for_input": 1},
    "incidents": [
        {"incident_id": "INC-1", "status": "awaiting_decision", "owner_decision_required": True,
         "severity": "critical", "category": "runtime_connection", "title": "NinjaTrader не отвечает",
         "details": "Мост молчит 20 минут", "recommendation": "Перезапустить мост", "occurrences": 3,
         "last_seen_at_utc": "2026-09-20T02:50:00Z"},
        {"incident_id": "INC-2", "status": "awaiting_decision", "owner_decision_required": False,
         "severity": "warning", "title": "Сам разберусь"},
        {"incident_id": "INC-3", "status": "obsolete", "owner_decision_required": True, "title": "Уже неактуально"},
    ],
    "tasks": [{"task_id": "T-1", "status": "waiting_for_input", "owner_title": "Какую стратегию взять",
               "question": "Выберите профиль", "updated_at_utc": "2026-09-20T02:55:00Z"},
              {"task_id": "T-2", "status": "running", "title": "Идёт бэктест"}],
    "agent_activity": [{"agent_id": "tolik", "name": "Толик", "working": True, "state": "busy",
                        "work": "Бэктест MNQ", "model": "gemini-2.5-flash"}],
}


class Engine(SimpleNamespace):
    """The real module's surface, recording what the owner's answer did."""
    OPEN_INCIDENT_STATUSES = {"awaiting_decision", "acknowledged", "in_progress"}
    WAITING_TASK_STATUSES = {"awaiting_decision", "waiting_review", "waiting_for_input"}


@pytest.fixture
def engine(monkeypatch):
    calls = []
    fake = Engine(
        status=lambda: STATUS,
        decide_incident=lambda incident_id, decision, note="", authorized_by="": calls.append(
            ("decide", incident_id, decision, note, authorized_by)) or {"incident_id": incident_id, "decision": decision},
        answer_task=lambda task_id, text: calls.append(("answer", task_id, text)) or {"task_id": task_id},
        set_rest=lambda duration_minutes, reason="": calls.append(("rest", duration_minutes, reason)) or {"active": True},
        resume=lambda: calls.append(("resume",)) or {"active": False},
        scan=lambda notify=False: calls.append(("scan", notify)) or {"checked": 4},
    )
    monkeypatch.setattr(duty_bridge, "_vitek", lambda: fake)
    fake.calls = calls
    return fake


def owner(read_only=False, is_owner=True, runtime=True):
    return {"chat_scope": {"is_owner": is_owner, "uses_owner_runtime": runtime, "membership_role": "owner" if is_owner else "member",
                           "user_id": 42}, "read_only": read_only}


def test_only_questions_that_need_the_owner_reach_the_owner(engine):
    state = duty_bridge.state(owner())
    assert [question["id"] for question in state["questions"]] == ["INC-1", "T-1"]
    # The one the engine settles itself and the obsolete one are not the owner's business.
    first = state["questions"][0]
    assert first["title"] == "NinjaTrader не отвечает" and first["level"] == "crit"
    assert first["recommendation"] == "Перезапустить мост" and first["occurrences"] == 3
    assert [choice["value"] for choice in first["decisions"]] == ["create_task", "acknowledge", "resolve", "ignore"]
    assert state["questions"][1]["kind"] == "task" and state["questions"][1]["title"] == "Какую стратегию взять"


def test_the_state_says_what_the_team_is_doing_and_whether_it_rests(engine):
    state = duty_bridge.state(owner())
    assert state["mode"] == "busy" and state["worker_alive"] is True
    assert state["resting"] == {"active": False, "until_utc": "", "reason": ""}
    assert state["working"][0]["name"] == "Толик" and state["working"][0]["work"] == "Бэктест MNQ"
    assert state["question_count"] == 2 and state["last_check_utc"] == "2026-09-20T03:00:00Z"


def test_an_answer_goes_back_through_the_engine_that_asked(engine):
    duty_bridge.decide(owner(), "INC-1", "create_task", note="Разрешаю перезапуск", user_id=42)
    duty_bridge.answer(owner(), "T-1", "  Берём MNQ Liquidity Sweep  ")
    duty_bridge.pause(owner(), 90, "Обед")
    duty_bridge.resume(owner())
    duty_bridge.check(owner())
    assert engine.calls == [
        ("decide", "INC-1", "create_task", "Разрешаю перезапуск", "42"),
        ("answer", "T-1", "Берём MNQ Liquidity Sweep"),
        ("rest", 90, "Обед"),
        ("resume",),
        ("scan", False),
    ]


@pytest.mark.parametrize("call", [
    lambda: duty_bridge.decide(owner(), "INC-1", "delete_everything"),
    lambda: duty_bridge.decide(owner(), "INC-1", "ignore", note="x" * 501),
    lambda: duty_bridge.answer(owner(), "T-1", "   "),
    lambda: duty_bridge.pause(owner(), 10_000),
    lambda: duty_bridge.pause(owner(), True),
])
def test_a_malformed_answer_is_refused(engine, call):
    with pytest.raises(ContractError):
        call()
    assert engine.calls == []


def test_a_reader_cannot_answer_and_a_stranger_cannot_look(engine):
    with pytest.raises(ContractError, match="duty_read_only"):
        duty_bridge.decide(owner(read_only=True), "INC-1", "ignore")
    with pytest.raises(ContractError, match="owner_runtime_only"):
        duty_bridge.state(owner(is_owner=False))
    with pytest.raises(ContractError, match="owner_runtime_only"):
        duty_bridge.state(owner(runtime=False))


def test_the_engines_own_refusal_is_carried_over_not_swallowed(engine, monkeypatch):
    def refuse(*args, **kwargs):
        raise RuntimeError("Инцидент INC-9 не найден.")
    monkeypatch.setattr(engine, "decide_incident", refuse)
    with pytest.raises(ContractError, match="duty_refused"):
        duty_bridge.decide(owner(), "INC-9", "ignore")
