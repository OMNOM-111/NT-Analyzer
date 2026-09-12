"""Saved-message Persona speech, isolated SQLite/history; no audio/provider proof."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai_lab import chief_agent
from app.ai_control_center import contracts as c, domain_gateway, persona_voice as voice
from app.ai_control_center.states import ContractError
from tests.test_agent_world_domain_service import env, create, act, get, context
from tests.test_agent_world_persona_voice import payload, scope, no_owner_tts
from tests.test_agent_world_live_gateway import isolated_runtime, owner
from tests.test_agent_world_domain_gateway import ordinary, models, Handler, http_api


@pytest.fixture(autouse=True)
def chat_root(tmp_path, monkeypatch, isolated_runtime):
    root = tmp_path / "speech-chat-registry"
    monkeypatch.setattr(chief_agent.paths, "REGISTRY_DIR", root)
    monkeypatch.setattr(chief_agent, "_apply_auto_fulfillment", lambda *a, **k:
                        pytest.fail("reading speech must not acknowledge tasks"))
    return root


def saved(ctx, item, *, cid="persona-replies", agent_id=None, role="assistant", model="fixture-model-one", own_scope=None, **changes):
    own_scope = own_scope or scope(ctx)
    path = chief_agent._conversation_file(cid, scope=own_scope)
    row = chief_agent._append_conversation(role, "Проверенный ответ. Не означает приёмку результата.",
        source="isolated_persona_speech_fixture", agent_id=agent_id or item["id"], agent_name=item["title"],
        model=model, fulfillment="unset", message_kind="report", participation_chain=[], path=path, scope=own_scope,
        **changes)
    return SimpleNamespace(row=row, path=path, cid=cid, scope=own_scope)


def reply(env, item, chat, **changes):
    return voice.speak_reply(env.service, **{"context": env.ctx, "admit": env.admit,
        "persona_id": item["id"], "conversation_id": chat.cid, "message_id": chat.row["message_id"],
        "scope": chat.scope, "expected_revision": item["revision"], **changes})


@pytest.mark.parametrize("name", ["Виктор", "Марина", "Витёк", "Управляющий", "Собственный агент"])
def test_persisted_uuid_is_not_replaced_by_legacy_name_and_models_do_not_pick_voice(env, no_owner_tts, name):
    item = create(env, payload=payload(name=name))["item"]
    first, second = saved(env.ctx, item), saved(env.ctx, item, model="fixture-other-provider-model")
    before = first.path.read_bytes()
    a, b = reply(env, item, first), reply(env, item, second)
    assert first.row["agent_id"] == second.row["agent_id"] == item["id"]
    assert a["persona_id"] == b["persona_id"] == item["id"]
    assert a["persona_presentation"] == b["persona_presentation"] == item["presentation"]
    assert a["fallback"] == b["fallback"] == "browser"
    assert a["owner_tts_authorized"] is b["owner_tts_authorized"] is False
    assert a["speech_source"]["message_id"] != b["speech_source"]["message_id"]
    assert a["speech_source"]["source_sha256"] == hashlib.sha256(first.row["content"].encode()).hexdigest()
    assert first.path.read_bytes() == before  # no auto acceptance, rating or history rewrite


def test_rename_keeps_historical_name_and_voice_and_requires_current_revision(env, no_owner_tts):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item)
    before = chat.path.read_bytes()
    changed = act(env, item, action="update", payload={"name": "Новое имя"})["item"]
    with pytest.raises(ContractError, match="revision_changed"):
        reply(env, item, chat)
    result = reply(env, changed, chat)
    assert result["persona_name"] == changed["title"] and result["persona_id"] == item["id"]
    assert result["persona_presentation"] == item["presentation"]
    assert chief_agent.conversation_message_for_speech(chat.cid, chat.row["message_id"], scope=chat.scope)["agent_name"] == item["title"]
    assert chat.path.read_bytes() == before


@pytest.mark.parametrize("change", [
    {"conversation_id": "foreign-conversation"}, {"message_id": "MSG-NOT-THERE"},
    {"conversation_id": "../persona-replies"}, {"conversation_id": ""}, {"message_id": "x/y"},
    {"conversation_id": None}, {"message_id": 1}, {"expected_revision": True}, {"expected_revision": None},
])
def test_invalid_or_missing_saved_message_fails_closed(env, no_owner_tts, change):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item)
    before = chat.path.read_bytes()
    with pytest.raises(ContractError):
        reply(env, item, chat, **change)
    assert chat.path.read_bytes() == before


@pytest.mark.parametrize("kind", ["user", "system", "another_persona"])
def test_only_matching_persisted_assistant_can_be_read(env, no_owner_tts, kind):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item, role=kind if kind != "another_persona" else "assistant",
                 agent_id=str(uuid4()) if kind == "another_persona" else None)
    with pytest.raises(ContractError, match="message_unavailable|message_mismatch"):
        reply(env, item, chat)


@pytest.mark.parametrize("foreign", [context(user=2), context(workspace="ws_foreign01")])
def test_foreign_persona_history_is_never_loaded(env, no_owner_tts, monkeypatch, foreign):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item)
    monkeypatch.setattr(chief_agent, "conversation_message_for_speech", lambda *a, **k:
                        pytest.fail("must authorize Persona before reading messages"))
    with pytest.raises(ContractError, match="domain_record_not_found"):
        reply(env, item, chat, context=foreign, scope=scope(foreign))


def test_nonhuman_cannot_turn_chat_speech_into_an_automatic_action(env, no_owner_tts):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item)
    agent = replace(env.ctx, actor=c.ActorRef(kind=c.ActorKind.AGENT, actor_id=uuid4(), on_behalf_of=env.ctx.user_uuid))
    with pytest.raises(ContractError, match="scope_invalid"):
        reply(env, item, chat, context=agent)


@pytest.mark.parametrize("when", ["before", "during"])
def test_permission_revocation_never_launches_speech(env, no_owner_tts, monkeypatch, when):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item)
    if when == "before":
        env.state.allowed = False
    else:
        original = chief_agent.conversation_message_for_speech
        def read(*args, **kwargs):
            result = original(*args, **kwargs)
            env.state.allowed = False
            return result
        monkeypatch.setattr(chief_agent, "conversation_message_for_speech", read)
    monkeypatch.setattr(voice.agent_tts, "synthesize", lambda *a, **k: pytest.fail("revoked authority cannot synthesize"))
    with pytest.raises(ContractError, match="test_access_revoked"):
        reply(env, item, chat)


def test_changed_message_fingerprint_and_changed_voice_revision_fail_closed(env, no_owner_tts, monkeypatch):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item)
    original = chief_agent.conversation_message_for_speech
    calls = []
    def read(*args, **kwargs):
        row = original(*args, **kwargs)
        calls.append(True)
        if len(calls) > 1:
            row["content"] = "Changed content must need a new gesture."
        return row
    monkeypatch.setattr(chief_agent, "conversation_message_for_speech", read)
    monkeypatch.setattr(voice.agent_tts, "synthesize", lambda *a, **k: pytest.fail("changed source cannot synthesize"))
    with pytest.raises(ContractError, match="message_changed"):
        reply(env, item, chat)


def test_suspended_persona_is_not_spoken_but_error_and_review_history_stay(env, no_owner_tts):
    item = act(env, create(env, payload=payload())["item"])["item"]
    chat = saved(env.ctx, item)
    before = chat.path.read_bytes()
    suspended = act(env, item, action="suspend")["item"]
    with pytest.raises(ContractError, match="persona_voice_inactive"):
        reply(env, suspended, chat)
    assert chat.path.read_bytes() == before and get(env, "personas", item["id"])["status"] == "suspended"


def test_public_message_lookup_is_read_only_private_scoped_and_returns_copy(env, chat_root):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item)
    before = {path.relative_to(chat_root): path.read_bytes() for path in chat_root.rglob("*") if path.is_file()}
    result = chief_agent.conversation_message_for_speech(chat.cid, chat.row["message_id"], scope=chat.scope)
    result["content"] = "Only a detached copy"
    for other in ({**chat.scope, "user_id": 2}, {**chat.scope, "workspace_id": "other"}):
        with pytest.raises(chief_agent.ChiefAgentError):
            chief_agent.conversation_message_for_speech(chat.cid, chat.row["message_id"], scope=other)
    assert {path.relative_to(chat_root): path.read_bytes() for path in chat_root.rglob("*") if path.is_file()} == before
    assert not (chat_root / "orchestrator_scopes" / "u2_ws_foreign").exists()


def test_default_shared_chat_still_requires_owned_persona(env, no_owner_tts):
    item = create(env, payload=payload())["item"]
    chat = saved(env.ctx, item, cid="default")
    assert reply(env, item, chat)["fallback"] == "browser"
    other = context(user=2)
    with pytest.raises(ContractError, match="domain_record_not_found"):
        reply(env, item, chat, context=other, scope=scope(other, user_id=2))


@pytest.mark.parametrize("extra", [{"text": "caller replacement"}, {"scope": {}}, {"model_id": str(uuid4())}])
def test_gateway_rejects_text_scope_or_executor_overlay_on_saved_message(extra):
    body = {"payload": {"conversation_id": "default", "message_id": "MSG-one", **extra},
        "expected_revision": 1, "idempotency_key": "saved-reply-voice-001"}
    with pytest.raises(ContractError, match="invalid_domain_request"):
        domain_gateway.speak_persona({"read_only": False}, str(uuid4()), body)


def test_real_http_guard_and_existing_envelope_return_local_fallback(models, no_owner_tts):
    authorized = models.authorized
    service = domain_gateway.domains(authorized, models.repository)
    item = service.create(context=models.context, admit=authorized["admit"], domain="personas",
        payload=payload(), idempotency_key="persona-chat-voice-http")["item"]
    chat = saved(models.context, item, own_scope=authorized["chat_scope"])
    body = {"payload": {"conversation_id": chat.cid, "message_id": chat.row["message_id"]},
        "expected_revision": item["revision"], "idempotency_key": "saved-reply-voice-http"}
    handler = Handler(models.account, body)
    handler._respond_tts = lambda value: handler._json(200, value)
    http_api.handle_post(handler, domain_gateway.live_gateway.PREFIX + f"domains/personas/{item['id']}/speak")
    assert handler.status == 200 and handler.result["fallback"] == "browser", handler.result
    assert handler.result["speech_source"]["message_id"] == chat.row["message_id"]
    assert not models.executions and not models.queue
    denied = Handler(models.account, deepcopy(body), csrf=None)
    denied._respond_tts = lambda *_: pytest.fail("CSRF must fail before TTS")
    http_api.handle_post(denied, domain_gateway.live_gateway.PREFIX + f"domains/personas/{item['id']}/speak")
    assert denied.status == 403
