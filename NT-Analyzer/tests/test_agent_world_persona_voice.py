"""Disposable Persona/TTS contracts. No real audio, credentials or network calls."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.ai_control_center import contracts as c, persona_voice as voice
from app.ai_control_center.states import ContractError, EntityKind
from tests.test_agent_world_domain_service import env, create, act, get, context, model_service_fixture


def payload(**changes):
    return {"name": "Мой аналитик", "description": "Read-only research", "style": "Кратко",
            "avatar_key": "marina", "voice_profile_id": "secretary", "voice_speed": 1.1,
            "voice_language": "ru-RU", "voice_mode": "browser", "animation_mode": "auto",
            "expression_preset": "neutral", "lip_sync_mode": "auto", **changes}


def scope(ctx, **changes):
    return {"workspace_id": ctx.scope.workspace_id, "user_uuid": str(ctx.user_uuid),
            "user_id": 1, "is_owner": False, "uses_owner_runtime": False, **changes}


def speak(env, item, **changes):
    args = {"context": env.ctx, "admit": env.admit, "persona_id": item["id"],
            "text": "**Проверенный** результат https://example.invalid ```hidden code``` готов.",
            "scope": scope(env.ctx), "expected_revision": item["revision"], **changes}
    return voice.speak(env.service, **args)


@pytest.fixture
def no_owner_tts(monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    def denied(*args, **kwargs):
        pytest.fail("ordinary Persona presentation must not read owner profiles/keys/cache or perform external TTS")
    for name in ("get_voice_profile", "_read_store", "resolve_speech_backend", "cache_dir"):
        monkeypatch.setattr(voice.agent_tts, name, denied)


def test_legacy_rename_preserves_avatar_voice_style_and_explicit_clearing_is_retained(env):
    first = create(env, payload=payload())["item"]
    active = act(env, first)["item"]
    changed = act(env, active, action="update", payload={"name": "Другое имя"})["item"]
    assert changed["id"] == first["id"] and changed["revision"] == 3
    for key in ("avatar_key", "description", "style", *voice.VOICE_FIELDS):
        assert changed.get(key) == first.get(key)
    assert changed["presentation"]["resolved_voice_profile_id"] == "secretary"
    cleared = act(env, changed, action="update", payload={"name": "Другое имя", "avatar_key": "",
        "voice_profile_id": "", "description": "", "style": ""})["item"]
    assert cleared["avatar_key"] == cleared["voice_profile_id"] == cleared["style"] == ""
    assert cleared["presentation"]["capabilities"]["voice_configured"] is False
    original = env.repo.get_revision(context=env.ctx, kind=EntityKind.PERSONA, entity_id=UUID(first["id"]), revision=1)
    assert original.display_name == first["title"]
    assert env.service._json(env.ctx, original.profile) == {**payload(), "application_role": ""}


def test_old_record_read_is_additive_and_does_not_migrate_revision_or_infer_name(env):
    item = create(env, payload={"name": "Марина", "avatar_key": ""})["item"]
    assert item["presentation"]["resolved_voice_profile_id"] == ""
    assert item["presentation"]["voice_mode"] == "browser"
    for _ in range(2):
        assert get(env, "personas", item["id"])["revision"] == 1
    original = env.repo.get_revision(context=env.ctx, kind=EntityKind.PERSONA, entity_id=UUID(item["id"]), revision=1)
    assert not set(voice.VOICE_FIELDS) & env.service._json(env.ctx, original.profile).keys()


def test_shipped_avatars_use_only_shipped_assets_and_honest_fallback(no_owner_tts):
    from app.ai_control_center.presentation import AVATAR_KEYS
    root = Path(__file__).resolve().parents[1] / "app/static/aurora"
    for face in AVATAR_KEYS:
        view = voice.presentation({"avatar_key": face})
        assert (root / view["animation_asset"].removeprefix("/ui/")).is_file()
        assert view["resolved_voice_profile_id"] == face
        assert view["capabilities"]["lip_sync"] == "unavailable"
        assert view["capabilities"]["audio_verified"] is False
        assert view["capabilities"]["model_independent"] is True
    assert voice.presentation({"avatar_key": "foreign", "name": "Иван"})["animation_asset"] is None
    assert voice.presentation({"avatar_key": "ivan", "animation_mode": "static"})["capabilities"]["facial_expression"] == "static"


def test_catalog_is_static_not_owner_voice_configuration(no_owner_tts):
    result = voice.catalog()
    assert len(result["profiles"]) == 8 and result["default_mode"] == "browser"
    assert result["lip_sync_available"] is False
    assert all(set(row) == {"id", "label", "voice_gender", "language"} for row in result["profiles"])
    result["profiles"][0]["label"] = "mutated client response"
    assert voice.catalog()["profiles"][0]["label"] != "mutated client response"


@pytest.mark.parametrize("change", [
    {"voice_profile_id": "invented"}, {"voice_profile_id": None}, {"voice_profile_id": ["marina"]},
    {"voice_mode": "openai"}, {"voice_mode": True}, {"voice_language": "any"},
    {"voice_speed": True}, {"voice_speed": "1.2"}, {"voice_speed": .49}, {"voice_speed": 1.81},
    {"voice_speed": float("nan")}, {"voice_speed": float("inf")},
    {"animation_mode": "deepfake"}, {"expression_preset": "angry"}, {"lip_sync_mode": "enabled"},
])
def test_invalid_presentation_payload_fails_closed(env, change):
    with pytest.raises(ContractError):
        create(env, payload=payload(**change))
    assert env.service.list(context=env.ctx, admit=env.admit, domain="personas")["items"] == []


def test_model_switch_and_persona_rename_preserve_prior_history_and_identity(env):
    # The executor is an explicit transport fixture, NOT a real-model/audio proof.
    models, ids, calls = model_service_fixture(env)
    item = env.service.list(context=env.ctx, admit=env.admit, domain="personas")["items"][0]
    item = act(env, item, action="update", payload=payload())["item"]
    first = models.start_task(context=env.ctx, model_id=ids[0], payload={"rubric_key": "json_arithmetic"},
                              idempotency_key="persona-prior-model-work")
    models.execute(context=env.ctx, task_id=first["id"])
    old_checkpoint = models._json(env.ctx, models._get(env.ctx, EntityKind.TASK, first["id"]).checkpoint)
    stable = get(env, "personas", item["id"])
    second = models.start_task(context=env.ctx, model_id=ids[1], payload={"rubric_key": "json_arithmetic"},
                               idempotency_key="persona-next-model-work")
    models.execute(context=env.ctx, task_id=second["id"])
    assert get(env, "personas", item["id"]) == stable
    renamed = act(env, item, action="update", payload={"name": "Новое имя"})["item"]
    assert renamed["presentation"] == stable["presentation"]
    assert models._json(env.ctx, models._get(env.ctx, EntityKind.TASK, first["id"]).checkpoint) == old_checkpoint
    assert old_checkpoint["persona_name"] == item["title"] and len(calls) == 2
    assert all(model["persona_id"] == item["id"] for model in models.models(context=env.ctx)["items"])


@pytest.mark.parametrize("mode", ["browser", "existing_tts"])
def test_ordinary_user_reuses_real_browser_fallback_without_owner_keys(env, no_owner_tts, mode):
    item = create(env, payload=payload(voice_mode=mode))["item"]
    result = speak(env, item)
    assert result["fallback"] == result["tts_provider"] == "browser"
    assert result["persona_id"] == item["id"] and result["persona_revision"] == item["revision"]
    assert result["persona_name"] == item["title"] and result["owner_tts_authorized"] is False
    assert result["speed"] == 1.1 and result["language"] == "ru-RU"
    assert "hidden" not in result["text"] and "http" not in result["text"] and "**" not in result["text"]
    assert "audio" not in result and result["persona_presentation"]["capabilities"]["audio_verified"] is False
    if mode == "existing_tts":
        assert result["voice_fallback_reason"] == "own_tts_connection_required"


@pytest.mark.parametrize("change", [{"is_owner": True}, {"uses_owner_runtime": True},
    {"is_owner": True, "uses_owner_runtime": True}])
def test_owner_booleans_alone_never_authorize_existing_server_tts(env, no_owner_tts, change):
    item = create(env, payload=payload(voice_mode="existing_tts"))["item"]
    result = speak(env, item, scope=scope(env.ctx, **change))
    assert result["fallback"] == "browser" and result["owner_tts_authorized"] is False


def test_explicit_owner_path_reuses_existing_profile_with_fresh_authority_fixture(env, monkeypatch):
    item = create(env, payload=payload(voice_mode="existing_tts"))["item"]
    profiles, calls, checks = [], [], []
    monkeypatch.setattr(voice.agent_tts, "get_voice_profile", lambda key:
        profiles.append(key) or {**voice.agent_tts.DEFAULT_PROFILES[key], "voice": "owner-retained-voice", "tts_provider": "openai"})
    monkeypatch.setattr(voice.agent_tts, "synthesize", lambda text, **kwargs:
        calls.append((text, kwargs)) or {"fallback": "browser", "reason": "isolated_transport_fixture"})
    result = speak(env, item, scope=scope(env.ctx, is_owner=True, uses_owner_runtime=True),
                   authorize_server_tts=lambda ctx, current: checks.append((ctx, current)) or True)
    assert len(checks) == 2 and profiles == ["secretary"] and len(calls) == 1
    assert calls[0][1]["profile_override"]["voice"] == "owner-retained-voice"
    assert calls[0][1]["profile_override"]["speed"] == 1.1
    assert result["owner_tts_authorized"] is True


def test_owner_revoked_before_synthesis_never_calls_transport(env, monkeypatch):
    item = create(env, payload=payload(voice_mode="existing_tts"))["item"]
    checks = iter([True, False])
    monkeypatch.setattr(voice.agent_tts, "get_voice_profile", lambda key: deepcopy(voice.agent_tts.DEFAULT_PROFILES[key]))
    monkeypatch.setattr(voice.agent_tts, "synthesize", lambda *a, **k: pytest.fail("revoked authority cannot synthesize"))
    with pytest.raises(ContractError, match="persona_voice_server_authority_revoked"):
        speak(env, item, scope=scope(env.ctx, is_owner=True, uses_owner_runtime=True),
              authorize_server_tts=lambda *_: next(checks))


@pytest.mark.parametrize("foreign", [context(user=2), context(workspace="ws_foreign01")])
def test_foreign_persona_is_not_read_or_spoken(env, no_owner_tts, foreign):
    item = create(env, payload=payload())["item"]
    with pytest.raises(ContractError, match="domain_record_not_found"):
        speak(env, item, context=foreign, scope=scope(foreign))


@pytest.mark.parametrize("change", [{"workspace_id": "ws_foreign01"}, {"user_uuid": "foreign"}])
def test_scope_mismatch_is_rejected_before_persona_read(env, no_owner_tts, change):
    item = create(env, payload=payload())["item"]
    before = env.state.checks
    with pytest.raises(ContractError, match="persona_voice_scope_required"):
        speak(env, item, scope=scope(env.ctx, **change))
    assert env.state.checks == before


def test_nonhuman_actor_cannot_turn_persona_voice_into_automatic_side_effect(env, no_owner_tts):
    item = create(env, payload=payload())["item"]
    agent = replace(env.ctx, actor=c.ActorRef(kind=c.ActorKind.AGENT, actor_id=uuid4(), on_behalf_of=env.ctx.user_uuid))
    with pytest.raises(ContractError, match="persona_voice_scope_required"):
        speak(env, item, context=agent)


def test_inactive_stale_and_revoked_persona_never_synthesize(env, no_owner_tts):
    first = create(env, payload=payload())["item"]
    item = act(env, first)["item"]
    with pytest.raises(ContractError, match="persona_voice_revision_changed"):
        speak(env, first)
    item = act(env, item, action="suspend")["item"]
    with pytest.raises(ContractError, match="persona_voice_inactive"):
        speak(env, item)
    env.state.allowed = False
    with pytest.raises(ContractError, match="test_access_revoked"):
        speak(env, item)


def test_unconfigured_persona_uses_no_random_voice(env, no_owner_tts):
    item = create(env, payload={"name": "Мой агент"})["item"]
    with pytest.raises(ContractError, match="persona_voice_not_configured"):
        speak(env, item)


def test_concurrent_persona_change_during_preparation_does_not_launch_stale_voice(env, no_owner_tts, monkeypatch):
    item = act(env, create(env, payload=payload())["item"])["item"]
    checks = []
    def admission():
        checks.append(True)
        env.admit()
        if len(checks) == 2:
            act(env, item, action="suspend")
    monkeypatch.setattr(voice.agent_tts, "synthesize", lambda *a, **k: pytest.fail("stale Persona must not speak"))
    with pytest.raises(ContractError, match="persona_voice_revision_changed"):
        speak(env, item, admit=admission)
    assert get(env, "personas", item["id"])["status"] == "suspended"
