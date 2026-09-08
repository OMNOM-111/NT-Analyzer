"""Persona-owned presentation settings over the existing agent_tts stack.

This module owns no voice/credential store. Browser speech is the default and
never resolves a global provider key. The optional existing-owner TTS path is
selected only after fresh, scoped admission. A speaking WEBM is not lip-sync.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import math
import re

from ..ai_lab import agent_tts
from . import contracts as c
from .presentation import avatar_key
from .states import ContractError


VERSION = "persona-presentation-v1"
VOICE_FIELDS = ("voice_profile_id", "voice_mode", "voice_speed", "voice_language",
                "animation_mode", "expression_preset", "lip_sync_mode")
DEFAULTS = {"voice_profile_id": "", "voice_mode": "browser", "voice_speed": 1.0,
            "voice_language": "ru-RU", "animation_mode": "auto",
            "expression_preset": "neutral", "lip_sync_mode": "auto"}
LANGUAGES = ("ru-RU", "en-US")
_LABELS = {"vitek": "Виктор · уверенный", "manager": "Управляющий · сдержанный",
    "deputy": "Заместитель · спокойный", "secretary": "Секретарь · энергичный",
    "marina": "Марина · спокойный", "tolik": "Толик · размеренный",
    "nikita": "Никита · энергичный", "ivan": "Иван · ясный"}


def normalize_fields(data):
    """Strict additive payload; old clients may omit all of these fields."""
    result = {key: data.get(key, default) for key, default in DEFAULTS.items()}
    if (type(result["voice_profile_id"]) is not str
            or result["voice_profile_id"] not in ("", *agent_tts.STAFF_ORDER)
            or type(result["voice_mode"]) is not str or result["voice_mode"] not in {"browser", "existing_tts"}
            or type(result["voice_language"]) is not str or result["voice_language"] not in LANGUAGES
            or type(result["voice_speed"]) not in {int, float}
            or not math.isfinite(result["voice_speed"]) or not .5 <= result["voice_speed"] <= 1.8
            or type(result["animation_mode"]) is not str or result["animation_mode"] not in {"auto", "static"}
            or type(result["expression_preset"]) is not str or result["expression_preset"] not in {"neutral", "speaking"}
            or type(result["lip_sync_mode"]) is not str or result["lip_sync_mode"] not in {"auto", "off"}):
        raise ContractError("persona_presentation_invalid")
    return result


def catalog():
    """Only shipped constants; no owner settings, registry or key discovery."""
    return {"version": VERSION,
        "profiles": [{"id": key, "label": _LABELS[key],
            "voice_gender": agent_tts.DEFAULT_PROFILES[key]["voice_gender"],
            "language": agent_tts.DEFAULT_PROFILES[key]["language"]} for key in agent_tts.STAFF_ORDER],
        "languages": list(LANGUAGES), "speed_min": .5, "speed_max": 1.8,
        "modes": ["browser", "existing_tts"], "default_mode": "browser",
        "animation_modes": ["auto", "static"], "expression_presets": ["neutral", "speaking"],
        "lip_sync_available": False, "lip_sync_reason": "no_phoneme_or_viseme_timeline",
        "browser_voice_note": "Голос браузера зависит от установленных на устройстве голосов; голос провайдера не имитируется.",
        "existing_tts_note": "Существующий серверный TTS доступен только в подтверждённом owner-контексте. У обычного пользователя — голос устройства."}


def presentation(data):
    """Pure compatibility view; reading does not migrate old Persona records."""
    settings = normalize_fields(data)
    face = avatar_key(data.get("avatar_key", ""))
    profile_id = settings["voice_profile_id"] or (face if face in agent_tts.STAFF_ORDER else "")
    profile = agent_tts.DEFAULT_PROFILES.get(profile_id, {})
    return {"version": VERSION, "ai_disclosure": "AI-персона, не реальный человек",
        **settings, "resolved_voice_profile_id": profile_id,
        "voice_label": _LABELS.get(profile_id, "Голос не выбран"),
        "voice_origin": "persona_choice" if settings["voice_profile_id"] else "shipped_avatar_preset" if profile_id else "not_configured",
        "voice_gender": profile.get("voice_gender", "neutral"),
        "avatar_key": face, "animation_asset": "/ui/assets/agents/" + face + "/speaking.webm" if face else None,
        "capabilities": {"voice_configured": bool(profile_id), "audio_verified": False,
            "browser_speech": "client_dependent", "server_speech": "requires_fresh_owner_authority",
            "facial_expression": "speaking_loop" if face and settings["animation_mode"] == "auto" else "static",
            "lip_sync": "unavailable", "lip_sync_reason": "no_phoneme_or_viseme_timeline",
            "fallback": "static_avatar_and_text", "model_independent": True},
        "limitations": ["Разговорная анимация — готовый клип, не синхронизация губ с фонемами.",
                        "Без доступного звука или при уменьшении движения остаются аватар и текст."]}


def speak(service, *, context, admit, persona_id, text, scope, expected_revision=None, authorize_server_tts=None):
    """Resolve an owned Persona, then reuse agent_tts without copying keys.

    Root supplies authenticated context/scope, never a request-body scope. No
    endpoint is registered here. The regular auth/device/capability middleware
    remains the authority and is rechecked immediately before synthesis.
    """
    if (not isinstance(context, c.RequestContext) or context.actor.kind != c.ActorKind.HUMAN
            or not callable(admit) or type(scope) is not dict
            or scope.get("workspace_id") != context.scope.workspace_id
            or str(scope.get("user_uuid") or "") != str(context.user_uuid)):
        raise ContractError("persona_voice_scope_required")
    item = service.get(context=context, admit=admit, domain="personas", entity_id=persona_id)
    if expected_revision is not None and (type(expected_revision) is not int or item["revision"] != expected_revision):
        raise ContractError("persona_voice_revision_changed")
    if item["status"] not in {"draft", "active"}:
        raise ContractError("persona_voice_inactive")
    view = presentation(item)
    voice_id = view["resolved_voice_profile_id"]
    if not voice_id:
        raise ContractError("persona_voice_not_configured")
    cleaned = agent_tts.prepare_text(text)
    owner_tts = (view["voice_mode"] == "existing_tts" and scope.get("is_owner") is True
                 and scope.get("uses_owner_runtime") is True and callable(authorize_server_tts)
                 and authorize_server_tts(context, scope) is True)
    # The ordinary path does not read owner custom voice files or providers.
    profile = (agent_tts.get_voice_profile(voice_id) if owner_tts
               else deepcopy(agent_tts.DEFAULT_PROFILES[voice_id]))
    profile.update(tts_enabled=True, tts_provider=profile.get("tts_provider", "openai") if owner_tts else "browser",
                   speed=view["voice_speed"], language=view["voice_language"], fallback_voice=view["voice_language"])
    # Re-read after preparation so a concurrent rename/voice edit/suspension
    # cannot launch speech from an obsolete Persona snapshot.
    current = service.get(context=context, admit=admit, domain="personas", entity_id=persona_id)
    if current["revision"] != item["revision"]:
        raise ContractError("persona_voice_revision_changed")
    if owner_tts and authorize_server_tts(context, scope) is not True:
        raise ContractError("persona_voice_server_authority_revoked")
    result = agent_tts.synthesize(cleaned, agent_id=voice_id, profile_override=profile, scope=scope)
    # Return the same fallback/audio contract that Handler._respond_tts uses;
    # metadata is a truthful presentation hint, never an execution/quality score.
    result.update(persona_id=item["id"], persona_revision=item["revision"],
        persona_name=item["title"], persona_presentation=view,
        voice_gender=view["voice_gender"], text=cleaned, local_voice_only=True,
        requested_voice_mode=view["voice_mode"], owner_tts_authorized=owner_tts,
        voice_fallback_reason="own_tts_connection_required" if view["voice_mode"] == "existing_tts" and not owner_tts else None)
    return result


def speak_reply(service, *, context, admit, persona_id, conversation_id, message_id, scope,
                expected_revision=None, authorize_server_tts=None):
    """Read an existing own assistant reply, not caller text or instructions.

    The message owns the stable Persona UUID; its executor/model is irrelevant.
    Reading it never acknowledges a task, applies fulfillment or edits history.
    """
    from ..ai_lab import chief_agent
    if (not isinstance(context, c.RequestContext) or context.actor.kind != c.ActorKind.HUMAN
            or type(scope) is not dict or str(scope.get("user_uuid")) != str(context.user_uuid)
            or scope.get("workspace_id") != context.scope.workspace_id or not callable(admit)
            or type(conversation_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", conversation_id)
            or type(message_id) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", message_id)):
        raise ContractError("persona_voice_message_scope_invalid")
    # Admission and Persona ownership precede even the scoped message lookup.
    item = service.get(context=context, admit=admit, domain="personas", entity_id=persona_id)
    if type(expected_revision) is not int or item["revision"] != expected_revision:
        raise ContractError("persona_voice_revision_changed")

    def stored_reply():
        try:
            row = chief_agent.conversation_message_for_speech(conversation_id, message_id, scope=scope)
        except chief_agent.ChiefAgentError:
            raise ContractError("persona_voice_message_unavailable") from None
        if (row.get("role") != "assistant" or row.get("message_id") != message_id
                or row.get("agent_id") != item["id"] or type(row.get("content")) is not str
                or not row["content"].strip()):
            raise ContractError("persona_voice_message_mismatch")
        return row["content"]

    content = stored_reply()
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()

    def fresh_admission():
        admit()
        if hashlib.sha256(stored_reply().encode("utf-8")).hexdigest() != fingerprint:
            raise ContractError("persona_voice_message_changed")

    result = speak(service, context=context, admit=fresh_admission, persona_id=item["id"],
        text=content, scope=scope, expected_revision=expected_revision,
        authorize_server_tts=authorize_server_tts)
    result["speech_source"] = {"kind": "sf_chat_message", "conversation_id": conversation_id,
        "message_id": message_id, "persona_id": item["id"], "source_sha256": fingerprint}
    return result
