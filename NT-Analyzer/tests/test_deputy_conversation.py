"""Conversation intent and ambiguous-send safety (not browser acceptance)."""
from types import SimpleNamespace
import pytest
from tests.test_preview_sandbox import preview_env
from app.ai_control_center import deputy_chat
from app.ai_control_center.states import ContractError
from app.ai_lab import chief_agent


@pytest.mark.parametrize("text,expected", [
    ("Привет", False), ("Что ты умеешь?", False), ("Почему небо голубое?", False),
    ("Как написать стратегию?", False), ("Объясни разницу между риском и доходностью", False),
    ("Подготовь план проверки стратегии", True), ("Пожалуйста, составь список рисков", True),
    ("Можешь подготовить краткий план?", True), ("Create a testing plan", True),
])
def test_conversation_is_not_a_work_request(text, expected):
    assert deputy_chat.is_work_request(text) is expected


def test_ambiguous_conversation_is_never_transmitted_twice(preview_env):
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise ContractError("model_transport_interrupted")
    auth = {"chat_scope": {"user_id": 1, "workspace_id": "isolated"},
            "context": object(), "admit": lambda: None}
    kwargs = dict(message="Привет", conversation_id="ambiguous", request_id="same-request")
    service = SimpleNamespace(conversation_response=fail)
    with pytest.raises(ContractError, match="model_transport_interrupted"):
        deputy_chat.reply(auth, service, "shared-id", **kwargs)
    with pytest.raises(ContractError, match="conversation_response_unconfirmed"):
        deputy_chat.reply(auth, service, "shared-id", **kwargs)
    assert len(calls) == 1
    assert chief_agent.recover_conversation_reply("ambiguous", "same-request", scope=auth["chat_scope"]) is None
