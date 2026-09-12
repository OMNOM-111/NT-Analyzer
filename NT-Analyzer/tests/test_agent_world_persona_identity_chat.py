"""Identity to real local queue/chat adapters, with disposable fixture data only.

No provider, browser, TTS, NinjaTrader, owner keys or running Local is used.
"""
import pytest

from app.ai_control_center import application_chat, persona_identity
from app.ai_control_center.states import ContractError, EntityKind
from app.ai_lab import chief_agent
from tests.test_agent_world_application_chat import authorized, model_setup
from tests.test_agent_world_models import connected


def selected_profile(model_setup):
    service, ctx, payload, *_ = model_setup
    persona = service._get(ctx, EntityKind.PERSONA, payload["persona_id"])
    profile = {**service._json(ctx, persona.profile), "aliases": ["Маруся"], "main_assistant": True,
        "avatar_key": "marina", "voice_mode": "browser", "voice_language": "ru-RU",
        "application_role": "chart_researcher"}
    current = service._change(ctx, persona, display_name="Марина", profile=service._put(ctx, profile))
    model = connected(model_setup)
    return current, model


def history(auth, conversation="persona-routing-chat"):
    return chief_agent.read_jsonl(chief_agent._conversation_file(conversation, scope=auth["chat_scope"]))


@pytest.mark.parametrize("selector", ["uuid", "alias", "main"])
def test_same_selected_identity_reaches_existing_application_queue_and_chat(model_setup, authorized, selector):
    service, ctx, _payload, calls, *_ = model_setup
    persona, model = selected_profile(model_setup)
    original = ("@Маруся, " if selector == "alias" else "") + "сделай снимок рабочего стола MNQ 09-26, 5m"
    kwargs = {"scope": authorized["chat_scope"], "conversation_id": "persona-routing-chat",
        "request_id": "persona-app-" + selector, "source": "app"}
    if selector == "uuid":
        kwargs["persona_id"] = str(persona.header.entity_id)
    reply = persona_identity.try_chat(original, **kwargs)
    assert reply["ok"] and not calls  # Admission/enqueue is not model execution.
    task_id = reply["actions"][0]["task_id"]
    detail = service.task_detail(context=ctx, task_id=task_id)
    assert detail["status"] == "ready" and detail["model_id"] == model["id"]
    task = service._get(ctx, EntityKind.TASK, task_id)
    checkpoint = service._json(ctx, task.checkpoint)
    assert checkpoint["persona_selection"]["entity_id"] == str(persona.header.entity_id)
    assert checkpoint["persona_selection"]["revision"] == persona.header.revision
    rows = history(authorized)
    assert len(rows) == 2 and rows[0]["content"] == original
    assert rows[1]["agent_id"] == str(persona.header.entity_id)
    assert rows[1]["agent_name"] == "Марина"
    assert reply["actions"][0]["status"] == "queued"
    replay = persona_identity.try_chat(original, **kwargs)
    assert replay["idempotent_replay"] and len(history(authorized)) == 2
    assert len(list(service._all(ctx, EntityKind.TASK))) == 1 and not calls


def test_selected_role_mismatch_cannot_reach_backtest_or_another_model(model_setup, authorized):
    service, ctx, _payload, calls, *_ = model_setup
    persona, _model = selected_profile(model_setup)
    with pytest.raises(ContractError, match="persona_application_role_mismatch"):
        persona_identity.try_chat("запусти бэктест SampleMACrossOver на MNQ 09-26, 5m",
            scope=authorized["chat_scope"], conversation_id="persona-routing-chat",
            request_id="persona-wrong-role", source="app", persona_id=str(persona.header.entity_id))
    assert not list(service._all(ctx, EntityKind.TASK)) and not calls


def test_stale_selected_revision_is_denied_before_user_message_or_queue(model_setup, authorized):
    service, ctx, _payload, calls, *_ = model_setup
    persona, _model = selected_profile(model_setup)
    service._change(ctx, persona, display_name="Марина — исправлено")
    with pytest.raises(ContractError, match="persona_revision_conflict"):
        application_chat.try_chat("сделай снимок рабочего стола MNQ 09-26, 5m",
            scope=authorized["chat_scope"], conversation_id="persona-routing-chat", request_id="stale-identity",
            source="app", persona_id=str(persona.header.entity_id), persona_revision=persona.header.revision)
    assert not list(service._all(ctx, EntityKind.TASK)) and not history(authorized) and not calls


@pytest.mark.parametrize("change", ["rename", "suspend"])
def test_recheck_immediately_inside_task_constructor_never_substitutes_identity(model_setup, authorized, monkeypatch, change):
    service, ctx, _payload, calls, *_ = model_setup
    persona, _model = selected_profile(model_setup)
    original = service.plan_application
    def changed_after_chat_admission(**kwargs):
        assert kwargs["_persona"] == persona.ref()
        if change == "rename":
            service._change(ctx, persona, display_name="Новое имя")
        else:
            service._change(ctx, persona, "suspended")
        return original(**kwargs)
    monkeypatch.setattr(service, "plan_application", changed_after_chat_admission)
    with pytest.raises(ContractError, match="persona_selection_changed|model_connection_inactive"):
        persona_identity.try_chat("@Маруся: сделай снимок рабочего стола MNQ 09-26, 5m",
            scope=authorized["chat_scope"], conversation_id="persona-routing-chat", request_id="identity-race-" + change,
            source="app")
    assert not list(service._all(ctx, EntityKind.TASK)) and not calls
    rows = history(authorized)
    assert len(rows) == 1 and rows[0]["role"] == "user"
    assert "@Маруся" in rows[0]["content"]  # The failed request is not erased.


def test_binding_revoked_before_normal_chat_callback_does_not_fallback(model_setup, authorized, monkeypatch):
    service, ctx, _payload, calls, *_ = model_setup
    persona, model = selected_profile(model_setup)
    original = chief_agent.run_agent_world_live_request
    def revoke_before_callback(**kwargs):
        service.disconnect(context=ctx, model_id=model["id"])
        return original(**kwargs)
    monkeypatch.setattr(chief_agent, "run_agent_world_live_request", revoke_before_callback)
    with pytest.raises(ContractError, match="persona_model_required"):
        persona_identity.try_chat("сделай снимок рабочего стола MNQ 09-26, 5m",
            scope=authorized["chat_scope"], conversation_id="persona-routing-chat", request_id="identity-revoked",
            source="app", persona_id=str(persona.header.entity_id))
    assert not list(service._all(ctx, EntityKind.TASK)) and not calls
    assert history(authorized)[0]["role"] == "user"
