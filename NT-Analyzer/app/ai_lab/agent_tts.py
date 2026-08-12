"""Per-agent TTS voice profiles for StratForge Orchestrator staff.

Text generation models (DeepSeek, Gemini, GPT, local) are unrelated to speech.
Speech always goes through the agent's voice profile → OpenAI Audio Speech
(or another future TTS provider) → browser speechSynthesis fallback.

Staff ids: vitek, marina, tolik, nikita, ivan, manager, secretary, deputy.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import local_secrets, runtime_env
from . import io_utils, paths

log = logging.getLogger("nta.agent_tts")

MAX_CHARS = 1200
DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "tts-1"
ALLOWED_PROVIDERS = ("openai", "browser")
ALLOWED_MODELS = ("tts-1", "tts-1-hd", "gpt-4o-mini-tts")
OPENAI_SPEECH_URL = "https://api.openai.com/v1/audio/speech"
KEY_ENV = "NTA_OPENAI_API_KEY"
AZURE_DEFAULT_API_VERSION = "2025-03-01-preview"
_DEFAULT_VOICES_PATH = paths.PROJECT_ROOT / "data" / "integrations" / "agent_voices.json"
VOICES_PATH = _DEFAULT_VOICES_PATH

OPENAI_VOICES = (
    "alloy", "ash", "ballad", "coral", "echo", "fable", "nova",
    "onyx", "sage", "shimmer", "verse", "marin", "cedar",
)
# Voices available on classic tts-1 / tts-1-hd (subset).
TTS1_VOICES = (
    "alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer",
)

STAFF_ORDER = (
    "vitek", "manager", "deputy", "secretary",
    "marina", "tolik", "nikita", "ivan",
)

_LOCK = threading.RLock()
_WS = re.compile(r"\s+")
_CODE_FENCE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MD_EMPH = re.compile(r"[*_~]{1,3}")


class AgentTtsError(ValueError):
    """User-facing TTS failure."""


# ---------------------------------------------------------------------------
# Defaults & presets (documented baseline voices)
# ---------------------------------------------------------------------------

# Rationale (docs/agents/AGENTS.md § voice profiles):
# vitek — deep confident male (onyx); marina — calm precise female (nova);
# tolik — measured male analyst (echo); nikita — energetic male (ash);
# ivan — clear practical male (alloy); manager — strict executive (sage);
# secretary — bright efficient female (coral); deputy — balanced male (fable).
DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "vitek": {
        "agent_id": "vitek",
        "tts_enabled": True,
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "voice": "onyx",
        "voice_gender": "male",
        "language": "ru-RU",
        "speed": 1.0,
        "style": "confident, warm, professional right-hand advisor",
        "instructions": (
            "Speak Russian clearly. Confident, warm male voice of a trusted "
            "executive assistant. Steady pace, no theatrical drama."
        ),
        "fallback_voice": "ru-RU",
        "preset_id": "deep_male",
    },
    "marina": {
        "agent_id": "marina",
        "tts_enabled": True,
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "voice": "nova",
        "voice_gender": "female",
        "language": "ru-RU",
        "speed": 0.95,
        "style": "calm, precise, professional",
        "instructions": (
            "Speak Russian clearly. Calm precise female financial controller. "
            "Numbers and facts first; soft but confident tone."
        ),
        "fallback_voice": "ru-RU",
        "preset_id": "soft_female",
    },
    "tolik": {
        "agent_id": "tolik",
        "tts_enabled": True,
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "voice": "echo",
        "voice_gender": "male",
        "language": "ru-RU",
        "speed": 0.98,
        "style": "calm analyst, measured",
        "instructions": (
            "Speak Russian clearly. Calm male strategy analyst. Measured, "
            "thoughtful delivery without rushing."
        ),
        "fallback_voice": "ru-RU",
        "preset_id": "calm_analyst",
    },
    "nikita": {
        "agent_id": "nikita",
        "tts_enabled": True,
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "voice": "ash",
        "voice_gender": "male",
        "language": "ru-RU",
        "speed": 1.06,
        "style": "energetic news analyst",
        "instructions": (
            "Speak Russian clearly. Energetic male news analyst. Crisp and "
            "alert, like a market briefing."
        ),
        "fallback_voice": "ru-RU",
        "preset_id": "energetic_assistant",
    },
    "ivan": {
        "agent_id": "ivan",
        "tts_enabled": True,
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "voice": "alloy",
        "voice_gender": "male",
        "language": "ru-RU",
        "speed": 1.0,
        "style": "clear, practical chart operator",
        "instructions": (
            "Speak Russian clearly. Practical male chart operator. Clear, "
            "direct, no fluff."
        ),
        "fallback_voice": "ru-RU",
        "preset_id": "young_male",
    },
    "manager": {
        "agent_id": "manager",
        "tts_enabled": True,
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "voice": "sage",
        "voice_gender": "male",
        "language": "ru-RU",
        "speed": 0.92,
        "style": "strict executive, authoritative",
        "instructions": (
            "Speak Russian clearly. Strict authoritative executive. Slow, "
            "deliberate, decisive."
        ),
        "fallback_voice": "ru-RU",
        "preset_id": "strict_leader",
    },
    "secretary": {
        "agent_id": "secretary",
        "tts_enabled": True,
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "voice": "coral",
        "voice_gender": "female",
        "language": "ru-RU",
        "speed": 1.05,
        "style": "bright efficient assistant",
        "instructions": (
            "Speak Russian clearly. Bright efficient female secretary. "
            "Friendly, quick, organized."
        ),
        "fallback_voice": "ru-RU",
        "preset_id": "young_female",
    },
    "deputy": {
        "agent_id": "deputy",
        "tts_enabled": True,
        "tts_provider": "openai",
        "tts_model": "gpt-4o-mini-tts",
        "voice": "fable",
        "voice_gender": "male",
        "language": "ru-RU",
        "speed": 1.0,
        "style": "balanced professional",
        "instructions": (
            "Speak Russian clearly. Balanced professional male deputy. "
            "Neutral, reliable, composed."
        ),
        "fallback_voice": "ru-RU",
        "preset_id": "calm_male",
    },
}

VOICE_PRESETS: Dict[str, Dict[str, Any]] = {
    "deep_male": {
        "id": "deep_male",
        "label": "Глубокий мужской",
        "voice": "onyx",
        "voice_gender": "male",
        "speed": 0.96,
        "style": "deep, confident",
        "instructions": "Deep confident male voice. Steady and grounded.",
    },
    "calm_male": {
        "id": "calm_male",
        "label": "Спокойный мужской",
        "voice": "echo",
        "voice_gender": "male",
        "speed": 0.98,
        "style": "calm, measured",
        "instructions": "Calm measured male voice. Soft authority.",
    },
    "young_male": {
        "id": "young_male",
        "label": "Молодой мужской",
        "voice": "alloy",
        "voice_gender": "male",
        "speed": 1.05,
        "style": "young, clear",
        "instructions": "Young clear male voice. Practical and direct.",
    },
    "strict_leader": {
        "id": "strict_leader",
        "label": "Строгий руководитель",
        "voice": "sage",
        "voice_gender": "male",
        "speed": 0.9,
        "style": "strict, authoritative",
        "instructions": "Strict authoritative executive. Deliberate pace.",
    },
    "soft_female": {
        "id": "soft_female",
        "label": "Мягкий женский",
        "voice": "nova",
        "voice_gender": "female",
        "speed": 0.95,
        "style": "soft, precise",
        "instructions": "Soft precise female voice. Calm professionalism.",
    },
    "confident_female": {
        "id": "confident_female",
        "label": "Уверенный женский",
        "voice": "shimmer",
        "voice_gender": "female",
        "speed": 1.0,
        "style": "confident, clear",
        "instructions": "Confident clear female voice. Assertive but polite.",
    },
    "young_female": {
        "id": "young_female",
        "label": "Молодой женский",
        "voice": "coral",
        "voice_gender": "female",
        "speed": 1.06,
        "style": "bright, energetic",
        "instructions": "Bright young female voice. Friendly and efficient.",
    },
    "calm_analyst": {
        "id": "calm_analyst",
        "label": "Спокойный аналитик",
        "voice": "fable",
        "voice_gender": "male",
        "speed": 0.97,
        "style": "calm analyst",
        "instructions": "Calm analytical male voice. Thoughtful pauses.",
    },
    "energetic_assistant": {
        "id": "energetic_assistant",
        "label": "Энергичный помощник",
        "voice": "ash",
        "voice_gender": "male",
        "speed": 1.08,
        "style": "energetic",
        "instructions": "Energetic assistant male voice. Crisp briefing tone.",
    },
    "neutral_pro": {
        "id": "neutral_pro",
        "label": "Нейтральный профессиональный",
        "voice": "verse",
        "voice_gender": "neutral",
        "speed": 1.0,
        "style": "neutral professional",
        "instructions": "Neutral professional voice. Clear and even.",
    },
}

PREVIEW_PHRASES: Dict[str, str] = {
    "vitek": "Здравствуйте. Я Виктор, правая рука руководителя. Готов приступить к работе.",
    "marina": "Здравствуйте. Я Марина, финансовый контролёр. Готова сверить цифры.",
    "tolik": "Здравствуйте. Я ваш стратегический аналитик. Готов приступить к работе.",
    "nikita": "Здравствуйте. Я Никита, новостной аналитик. Слежу за рынком.",
    "ivan": "Здравствуйте. Я Иван, оператор графиков. Готов отметить уровни.",
    "manager": "Здравствуйте. Я Управляющий. Готов принять решение по задаче.",
    "secretary": "Здравствуйте. Я Секретарь. Чем помочь быстро?",
    "deputy": "Здравствуйте. Я Заместитель управляющего. Готов разобрать задачу.",
}

# Backward-compatible alias used by older callers/tests.
AGENT_VOICES = {aid: row["voice"] for aid, row in DEFAULT_PROFILES.items()}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cache_dir() -> Path:
    root = runtime_env.data_path(
        "runtime", "tts-cache", project_root=paths.PROJECT_ROOT,
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def voices_store_path() -> Path:
    if VOICES_PATH != _DEFAULT_VOICES_PATH:
        return Path(VOICES_PATH)
    return runtime_env.data_path(
        "integrations", "agent_voices.json", project_root=paths.PROJECT_ROOT,
    )


def normalize_agent_id(agent_id: str) -> str:
    raw = str(agent_id or "").strip().lower()
    if not raw:
        return "vitek"
    aliases = {
        "виктор": "vitek", "витёк": "vitek", "витек": "vitek", "витя": "vitek",
        "orchestrator": "manager", "управляющий": "manager",
        "секретарь": "secretary", "заместитель": "deputy", "зам": "deputy",
        "марина": "marina", "толик": "tolik", "никита": "nikita", "иван": "ivan",
        "accountant": "marina", "strategy_analyst": "tolik",
        "news_analyst": "nikita", "chart_operator": "ivan",
    }
    if raw in DEFAULT_PROFILES:
        return raw
    if raw in aliases:
        return aliases[raw]
    head = raw.split()[0]
    return aliases.get(head, head if head in DEFAULT_PROFILES else "vitek")


def voice_for_agent(agent_id: str) -> str:
    return str(get_voice_profile(agent_id).get("voice") or "onyx")


def staff_meta(agent_id: str) -> Dict[str, Any]:
    """Public card fields for UI (no secrets)."""
    from . import domain_agents
    aid = normalize_agent_id(agent_id)
    if aid == "vitek":
        return {
            "id": "vitek",
            "name": "Виктор",
            "title": "Правая рука руководителя",
            "role": "orchestrator",
            "personality": "Итоговый собеседник владельца; поручения, инциденты, координация.",
            "avatar_webm": "assets/agents/vitek/speaking.webm",
        }
    for bucket in (domain_agents.PERSONAS, domain_agents.MANAGEMENT):
        row = bucket.get(aid)
        if row:
            caps = row.get("capabilities") or row.get("hint") or ""
            if isinstance(caps, (list, tuple)):
                personality = "; ".join(str(c) for c in caps[:3])
            else:
                personality = str(caps)
            return {
                "id": aid,
                "name": row.get("name") or aid,
                "title": row.get("title") or "",
                "role": row.get("role") or "",
                "personality": personality,
                "avatar_webm": row.get("avatar_webm") or f"assets/agents/{aid}/speaking.webm",
            }
    return {"id": aid, "name": aid, "title": "", "role": "", "personality": "", "avatar_webm": ""}


def prepare_text(text: str, *, max_chars: int = MAX_CHARS) -> str:
    raw = str(text or "")
    raw = _CODE_FENCE.sub(" ", raw)
    raw = _MD_LINK.sub(r"\1", raw)
    raw = _URL.sub(" ", raw)
    raw = _INLINE_CODE.sub(r"\1", raw)
    raw = _MD_EMPH.sub("", raw)
    cleaned = _WS.sub(" ", raw).strip()
    if not cleaned:
        raise AgentTtsError("Пустой текст для озвучки.")
    if len(cleaned) <= max_chars:
        return cleaned
    cut = cleaned[: max_chars - 1].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return (cut or cleaned[: max_chars - 1]) + "…"


def resolve_model(profile: Optional[Dict[str, Any]] = None) -> str:
    if profile and str(profile.get("tts_model") or "").strip() in ALLOWED_MODELS:
        return str(profile["tts_model"]).strip()
    raw = str(os.environ.get("NTA_TTS_MODEL") or DEFAULT_MODEL).strip().lower()
    return raw if raw in ALLOWED_MODELS else DEFAULT_MODEL


def _is_speech_agent(row: Dict[str, Any]) -> bool:
    model = str(row.get("model") or "").strip().lower()
    path = urllib.parse.urlsplit(str(row.get("base_url") or "")).path.lower()
    return model in ALLOWED_MODELS or path.rstrip("/").endswith("/audio/speech")


def _agent_api_key(agent_registry: Any, row: Dict[str, Any]) -> str:
    try:
        return str(agent_registry.get_api_key(str(row.get("id") or "")) or "").strip()
    except Exception:
        return ""


def _openai_agent_credential(agent_registry: Any) -> Dict[str, Any]:
    for row in agent_registry.list_agents():
        if not isinstance(row, dict):
            continue
        if str(row.get("provider") or "").strip().lower() != "openai":
            continue
        if not row.get("enabled", True):
            continue
        key = _agent_api_key(agent_registry, row)
        if len(key) >= 12:
            return {
                "api_key": key,
                "provider": "openai",
                "endpoint_url": OPENAI_SPEECH_URL,
                "source": "agent_registry:openai",
                "agent_id": str(row.get("id") or ""),
                "model": "",
            }
    return {}


def _azure_api_version(row: Dict[str, Any], parsed: urllib.parse.SplitResult) -> str:
    query = urllib.parse.parse_qs(parsed.query or "", keep_blank_values=True)
    version = (
        str(row.get("api_version") or "").strip()
        or str((query.get("api-version") or [""])[0]).strip()
        or AZURE_DEFAULT_API_VERSION
    )
    return version


def _azure_resource_endpoint(
    row: Dict[str, Any], *, deployment: str, force_deployment: bool = False,
) -> str:
    base = str(row.get("base_url") or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    path = parsed.path.rstrip("/")
    version = _azure_api_version(row, parsed)
    query = urllib.parse.urlencode({"api-version": version})
    if path.rstrip("/").endswith("/audio/speech") and not force_deployment:
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query or query, ""))
    marker = "/openai/deployments/"
    if marker in path:
        prefix = path.split(marker, 1)[0]
        return urllib.parse.urlunsplit((
            parsed.scheme,
            parsed.netloc,
            f"{prefix}{marker}{urllib.parse.quote(deployment, safe='')}/audio/speech",
            query,
            "",
        ))
    if path.endswith("/openai/v1") or "/openai/v1/" in path:
        return urllib.parse.urlunsplit((
            parsed.scheme, parsed.netloc, f"{path}/audio/speech", parsed.query, "",
        ))
    return urllib.parse.urlunsplit((
        parsed.scheme,
        parsed.netloc,
        f"{path}/openai/deployments/{urllib.parse.quote(deployment, safe='')}/audio/speech",
        query,
        "",
    ))


def _azure_agent_credential(
    agent_registry: Any, *, speech_only: bool, profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    wanted_model = resolve_model(profile)
    for row in agent_registry.list_agents():
        if not isinstance(row, dict):
            continue
        if str(row.get("provider") or "").strip().lower() != "azure_foundry":
            continue
        speech_agent = _is_speech_agent(row)
        if speech_only and not speech_agent:
            continue
        if not speech_agent and not row.get("enabled", True):
            continue
        key = _agent_api_key(agent_registry, row)
        if len(key) < 12:
            continue
        deployment = str(row.get("model") or "").strip() if speech_agent else wanted_model
        if deployment.lower() not in ALLOWED_MODELS:
            deployment = wanted_model
        return {
            "api_key": key,
            "provider": "azure_foundry",
            "endpoint_url": _azure_resource_endpoint(
                row, deployment=deployment, force_deployment=not speech_agent,
            ),
            "source": "agent_registry:azure_speech" if speech_agent else "agent_registry:azure_resource_guess",
            "agent_id": str(row.get("id") or ""),
            "model": deployment,
        }
    return {}


def resolve_speech_backend(profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve a usable Speech backend without exposing secret material."""
    local_secrets.apply()
    key = str(os.environ.get(KEY_ENV) or "").strip()
    if len(key) >= 12:
        return {
            "api_key": key,
            "provider": "openai",
            "endpoint_url": OPENAI_SPEECH_URL,
            "source": f"env:{KEY_ENV}",
            "agent_id": "",
            "model": "",
        }
    try:
        from . import agent_registry

        credential = _openai_agent_credential(agent_registry)
        if credential:
            return credential
        credential = _azure_agent_credential(agent_registry, speech_only=True, profile=profile)
        if credential:
            return credential
        credential = _azure_agent_credential(agent_registry, speech_only=False, profile=profile)
        if credential:
            return credential
    except Exception:
        pass
    return {}


def resolve_api_key() -> str:
    """Backward-compatible helper for tests and status checks."""
    return str(resolve_speech_backend().get("api_key") or "")


def tts_status() -> Dict[str, Any]:
    backend = resolve_speech_backend()
    return {
        "ok": True,
        "key_configured": bool(backend.get("api_key")),
        "tts_backend_provider": str(backend.get("provider") or ""),
        "tts_backend_source": str(backend.get("source") or ""),
        "tts_backend_agent_id": str(backend.get("agent_id") or ""),
        "tts_backend_model": str(backend.get("model") or ""),
    }


def configure_openai_tts_key(api_key: str) -> Dict[str, Any]:
    key = str(api_key or "").strip()
    if len(key) < 12 or key == "YOUR_API_KEY_HERE":
        raise AgentTtsError("Введите реальный OpenAI API-ключ для TTS.")
    if not local_secrets.update({KEY_ENV: key}):
        raise AgentTtsError("Не удалось сохранить OpenAI TTS ключ в local secrets.")
    return tts_status()


def clear_openai_tts_key() -> Dict[str, Any]:
    if not local_secrets.update({KEY_ENV: None}):
        raise AgentTtsError("Не удалось удалить OpenAI TTS ключ из local secrets.")
    return tts_status()


def _clamp_speed(value: Any) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        speed = 1.0
    if not (0.25 <= speed <= 4.0):
        speed = max(0.25, min(4.0, speed))
    return round(speed, 3)


def _read_store() -> Dict[str, Any]:
    doc = io_utils.read_json(voices_store_path(), default=None)
    if not isinstance(doc, dict):
        return {"version": 1, "profiles": {}, "updated_at_utc": ""}
    profiles = doc.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    return {
        "version": int(doc.get("version") or 1),
        "profiles": profiles,
        "updated_at_utc": str(doc.get("updated_at_utc") or ""),
    }


def _write_store(doc: Dict[str, Any]) -> None:
    path = voices_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    io_utils.write_json_atomic(path, doc)


def normalize_profile(raw: Dict[str, Any], *, agent_id: str) -> Dict[str, Any]:
    aid = normalize_agent_id(agent_id)
    base = deepcopy(DEFAULT_PROFILES.get(aid) or DEFAULT_PROFILES["vitek"])
    src = raw if isinstance(raw, dict) else {}
    provider = str(src.get("tts_provider") or base["tts_provider"]).strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        provider = DEFAULT_PROVIDER
    model = str(src.get("tts_model") or base["tts_model"]).strip().lower()
    if model not in ALLOWED_MODELS:
        model = resolve_model()
    voice = str(src.get("voice") or base["voice"]).strip().lower()
    allowed = OPENAI_VOICES if model == "gpt-4o-mini-tts" else TTS1_VOICES
    if voice not in allowed:
        # Fall back to a voice valid for the selected model.
        voice = base["voice"] if base["voice"] in allowed else allowed[0]
    gender = str(src.get("voice_gender") or base.get("voice_gender") or "neutral").strip().lower()
    if gender not in {"male", "female", "neutral"}:
        gender = "neutral"
    out = {
        "agent_id": aid,
        "tts_enabled": bool(src.get("tts_enabled", base.get("tts_enabled", True))),
        "tts_provider": provider,
        "tts_model": model,
        "voice": voice,
        "voice_gender": gender,
        "language": str(src.get("language") or base.get("language") or "ru-RU").strip() or "ru-RU",
        "speed": _clamp_speed(src.get("speed", base.get("speed", 1.0))),
        "style": str(src.get("style") or base.get("style") or "").strip()[:200],
        "instructions": str(src.get("instructions") or base.get("instructions") or "").strip()[:500],
        "fallback_voice": str(src.get("fallback_voice") or base.get("fallback_voice") or "ru-RU").strip() or "ru-RU",
        "preset_id": str(src.get("preset_id") or base.get("preset_id") or "").strip(),
        "is_custom": bool(src.get("is_custom", False)),
        "supports": supported_params(provider, model),
    }
    # Pitch is not supported by OpenAI Speech — never persist as working.
    return out


def supported_params(provider: str, model: str) -> Dict[str, bool]:
    provider = str(provider or "").lower()
    model = str(model or "").lower()
    if provider == "browser":
        return {
            "voice": False,
            "speed": True,
            "pitch": False,
            "instructions": False,
            "style": False,
            "language": True,
        }
    if provider == "openai":
        return {
            "voice": True,
            "speed": True,
            "pitch": False,
            "instructions": model == "gpt-4o-mini-tts",
            "style": model == "gpt-4o-mini-tts",
            "language": True,
        }
    return {
        "voice": False, "speed": False, "pitch": False,
        "instructions": False, "style": False, "language": True,
    }


def get_voice_profile(agent_id: str) -> Dict[str, Any]:
    aid = normalize_agent_id(agent_id)
    with _LOCK:
        store = _read_store()
        custom = store["profiles"].get(aid)
    if isinstance(custom, dict):
        profile = normalize_profile(custom, agent_id=aid)
        profile["is_custom"] = True
        profile["source"] = "stored"
    else:
        profile = normalize_profile(DEFAULT_PROFILES[aid], agent_id=aid)
        profile["is_custom"] = False
        profile["source"] = "default"
    return profile


def list_voice_profiles() -> Dict[str, Any]:
    agents = []
    for aid in STAFF_ORDER:
        meta = staff_meta(aid)
        profile = get_voice_profile(aid)
        agents.append({
            **meta,
            "voice": profile,
            "preview_phrase": PREVIEW_PHRASES.get(aid, PREVIEW_PHRASES["vitek"]),
        })
    return {
        "ok": True,
        "agents": agents,
        "presets": list_presets(),
        "catalog": tts_catalog(),
        "key_configured": bool(resolve_api_key()),
    }


def list_presets() -> List[Dict[str, Any]]:
    return [dict(row) for row in VOICE_PRESETS.values()]


def tts_catalog() -> Dict[str, Any]:
    return {
        "providers": [
            {
                "id": "openai",
                "label": "OpenAI Speech",
                "models": [
                    {
                        "id": "tts-1",
                        "label": "tts-1 (быстрый)",
                        "voices": list(TTS1_VOICES),
                        "supports": supported_params("openai", "tts-1"),
                    },
                    {
                        "id": "tts-1-hd",
                        "label": "tts-1-hd (качество)",
                        "voices": list(TTS1_VOICES),
                        "supports": supported_params("openai", "tts-1-hd"),
                    },
                    {
                        "id": "gpt-4o-mini-tts",
                        "label": "gpt-4o-mini-tts (стиль / instructions)",
                        "voices": list(OPENAI_VOICES),
                        "supports": supported_params("openai", "gpt-4o-mini-tts"),
                    },
                ],
            },
            {
                "id": "browser",
                "label": "Браузерный speechSynthesis",
                "models": [
                    {
                        "id": "speechSynthesis",
                        "label": "Системный голос",
                        "voices": [],
                        "supports": supported_params("browser", "speechSynthesis"),
                    }
                ],
            },
        ],
        "note": (
            "Высота тона (pitch) OpenAI Speech не поддерживает — параметр скрыт. "
            "instructions/style доступны только для gpt-4o-mini-tts. "
            "Ключи API не хранятся в голосовом профиле."
        ),
    }


def apply_preset(agent_id: str, preset_id: str, *, draft: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    preset = VOICE_PRESETS.get(str(preset_id or "").strip())
    if not preset:
        raise AgentTtsError(f"Неизвестный пресет: {preset_id}")
    base = draft if isinstance(draft, dict) else get_voice_profile(agent_id)
    merged = dict(base)
    for key in ("voice", "voice_gender", "speed", "style", "instructions"):
        if key in preset:
            merged[key] = preset[key]
    merged["preset_id"] = preset["id"]
    return normalize_profile(merged, agent_id=agent_id)


def set_voice_profile(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    aid = normalize_agent_id(agent_id)
    if aid not in DEFAULT_PROFILES:
        raise AgentTtsError(f"Неизвестный сотрудник: {agent_id}")
    profile = normalize_profile(payload or {}, agent_id=aid)
    profile["is_custom"] = True
    profile["updated_at_utc"] = _now()
    # Never persist secrets or unsupported pitch.
    safe = {k: profile[k] for k in (
        "agent_id", "tts_enabled", "tts_provider", "tts_model", "voice",
        "voice_gender", "language", "speed", "style", "instructions",
        "fallback_voice", "preset_id", "is_custom", "updated_at_utc",
    ) if k in profile}
    with _LOCK:
        store = _read_store()
        store["profiles"][aid] = safe
        store["updated_at_utc"] = _now()
        store["version"] = 1
        _write_store(store)
    # New cache keys include profile fields — old entries simply miss.
    return get_voice_profile(aid)


def reset_voice_profile(agent_id: str) -> Dict[str, Any]:
    aid = normalize_agent_id(agent_id)
    with _LOCK:
        store = _read_store()
        store["profiles"].pop(aid, None)
        store["updated_at_utc"] = _now()
        _write_store(store)
    return get_voice_profile(aid)


def ensure_defaults_migrated() -> Dict[str, Any]:
    """No-op write migration marker; defaults live in code until customized."""
    with _LOCK:
        store = _read_store()
        if not store.get("updated_at_utc"):
            store["updated_at_utc"] = _now()
            store["version"] = 1
            store.setdefault("profiles", {})
            _write_store(store)
    return list_voice_profiles()


# ---------------------------------------------------------------------------
# Cache & synthesis
# ---------------------------------------------------------------------------

def _cache_key(*, text: str, profile: Dict[str, Any], workspace_id: str = "") -> str:
    payload = "\n".join([
        str(workspace_id or ""),
        str(profile.get("agent_id") or ""),
        str(profile.get("tts_provider") or ""),
        str(profile.get("tts_model") or ""),
        str(profile.get("voice") or ""),
        str(profile.get("speed") or ""),
        str(profile.get("style") or ""),
        str(profile.get("instructions") or ""),
        str(profile.get("language") or ""),
        text,
    ]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cache_path(key: str) -> Path:
    return cache_dir() / f"{key}.mp3"


def _read_cache(key: str) -> Optional[bytes]:
    path = _cache_path(key)
    try:
        if path.is_file() and path.stat().st_size > 64:
            return path.read_bytes()
    except OSError:
        return None
    return None


def _write_cache(key: str, data: bytes) -> None:
    if not data or len(data) < 64:
        return
    path = _cache_path(key)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        try:
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _openai_speech(
    *, text: str, profile: Dict[str, Any], api_key: str,
    endpoint_url: str = OPENAI_SPEECH_URL, backend_provider: str = "openai",
) -> bytes:
    model = resolve_model(profile)
    voice = str(profile.get("voice") or "onyx")
    body: Dict[str, Any] = {
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": "mp3",
        "speed": _clamp_speed(profile.get("speed", 1.0)),
    }
    supports = supported_params("openai", model)
    if supports.get("instructions"):
        instructions = str(profile.get("instructions") or profile.get("style") or "").strip()
        if instructions:
            body["instructions"] = instructions
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    auth_headers = (
        {"api-key": api_key}
        if str(backend_provider or "").lower() == "azure_foundry"
        else {"Authorization": f"Bearer {api_key}"}
    )
    req = urllib.request.Request(
        str(endpoint_url or OPENAI_SPEECH_URL),
        data=raw,
        method="POST",
        headers={
            **auth_headers,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
            "User-Agent": "StratForge-NT-Analyzer/agent-tts",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = str(exc)
        raise AgentTtsError(f"Speech TTS недоступен: HTTP {exc.code}. {detail}".strip()) from None
    except urllib.error.URLError as exc:
        raise AgentTtsError(f"Speech TTS сеть: {exc.reason}") from None
    if not data or len(data) < 64:
        raise AgentTtsError("Speech TTS вернул пустой аудиоответ.")
    return data


def _browser_fallback(profile: Dict[str, Any], *, reason: str, chars: int) -> Dict[str, Any]:
    log.info("tts_fallback agent=%s reason=%s", profile.get("agent_id"), reason)
    return {
        "fallback": "browser",
        "reason": reason,
        "agent_id": profile.get("agent_id"),
        "voice": profile.get("voice"),
        "language": profile.get("language") or "ru-RU",
        "speed": _clamp_speed(profile.get("speed", 1.0)),
        "fallback_voice": profile.get("fallback_voice") or "ru-RU",
        "chars": chars,
        "tts_provider": "browser",
        "tts_model": "speechSynthesis",
    }


def _production_scope(scope: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Resolve TTS attribution without trusting a caller-supplied data path."""
    from . import universal_llm

    if scope is None:
        return universal_llm.require_valid_production_scope()
    active = scope.get("active_workspace") if isinstance(scope.get("active_workspace"), dict) else {}
    context = {
        "user_id": scope.get("user_id"),
        "user_name": scope.get("display_name"),
        "workspace_id": scope.get("workspace_id") or active.get("workspace_id"),
        "conversation_id": scope.get("conversation_id") or "default",
        "request_source": "agent_tts",
    }
    with universal_llm.usage_scope(context):
        return universal_llm.require_valid_production_scope()


def _record_production_tts_usage(
    request_id: str,
    production_scope: Optional[Dict[str, Any]],
    *,
    agent_id: str,
    model: str,
    status: str,
    input_tokens: int,
    cost_usd: float,
    prompt_sha256: str,
    chars: int,
) -> bool:
    if production_scope is None:
        return True
    from .. import ai_budgets

    try:
        result = ai_budgets.record_usage(
            request_id,
            production_scope["workspace_id"],
            production_scope["user_id"],
            "openai",
            model,
            "tts",
            "agent_speech",
            status,
            max(0, int(input_tokens)),
            0,
            max(0.0, float(cost_usd)),
            prompt_sha256,
            document={
                "adapter": "openai_audio_speech",
                "agent_id": str(agent_id or "")[:80],
                "characters": max(0, int(chars)),
            },
        )
    except Exception:
        return False
    return bool(result.get("ok"))


def synthesize(
    text: str,
    *,
    agent_id: str = "vitek",
    message_id: str = "",
    profile_override: Optional[Dict[str, Any]] = None,
    scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return MP3 bytes or a browser-fallback signal using the agent voice profile."""
    del message_id
    cleaned = prepare_text(text)
    try:
        production_scope = _production_scope(scope)
    except Exception as exc:
        raise AgentTtsError(str(exc)) from exc
    aid = normalize_agent_id(agent_id)
    if isinstance(profile_override, dict) and profile_override:
        profile = normalize_profile(profile_override, agent_id=aid)
        profile["source"] = "override"
    else:
        profile = get_voice_profile(aid)

    if not profile.get("tts_enabled", True):
        return _browser_fallback(profile, reason="tts_disabled", chars=len(cleaned))

    provider = str(profile.get("tts_provider") or DEFAULT_PROVIDER).lower()
    if provider == "browser":
        return _browser_fallback(profile, reason="provider_browser", chars=len(cleaned))

    backend = resolve_speech_backend(profile)
    api_key = str(backend.get("api_key") or "")
    if not api_key:
        return _browser_fallback(profile, reason="no_api_key", chars=len(cleaned))

    model = resolve_model(profile)
    profile = dict(profile)
    profile["tts_model"] = model
    backend_provider = str(backend.get("provider") or provider or DEFAULT_PROVIDER)
    provider = backend_provider
    profile["tts_provider"] = backend_provider

    key = _cache_key(
        text=cleaned,
        profile=profile,
        workspace_id=str((production_scope or {}).get("workspace_id") or ""),
    )
    request_id = f"REQ-{uuid.uuid4().hex[:16].upper()}"
    prompt_sha256 = key
    estimated_input_tokens = max(1, (len(cleaned) + 2) // 3)
    # Reserve conservatively across the supported speech models. The durable
    # budget is a hard upper bound, not an optimistic invoice estimate.
    estimated_cost = round(len(cleaned) * 0.00004, 8)
    cached = _read_cache(key)
    if cached:
        if not _record_production_tts_usage(
            request_id,
            production_scope,
            agent_id=aid,
            model=model,
            status="cache_hit",
            input_tokens=0,
            cost_usd=0.0,
            prompt_sha256=prompt_sha256,
            chars=len(cleaned),
        ):
            raise AgentTtsError("Production AI usage storage is unavailable.")
        return {
            "audio": cached,
            "content_type": "audio/mpeg",
            "model": model,
            "voice": profile.get("voice"),
            "cached": True,
            "agent_id": aid,
            "chars": len(cleaned),
            "speed": profile.get("speed"),
            "tts_provider": provider,
            "tts_model": model,
            "language": profile.get("language"),
        }

    durable_reserved = False
    durable_recorded = False
    if production_scope is not None:
        from .. import ai_budgets

        try:
            admitted = ai_budgets.reserve(
                request_id,
                production_scope["workspace_id"],
                production_scope["user_id"],
                "openai",
                model,
                "tts",
                estimated_cost,
                prompt_sha256,
            )
        except Exception:
            admitted = {"ok": False, "code": "storage_unavailable"}
        if not admitted.get("ok"):
            durable_recorded = _record_production_tts_usage(
                request_id,
                production_scope,
                agent_id=aid,
                model=model,
                status="blocked",
                input_tokens=0,
                cost_usd=0.0,
                prompt_sha256=prompt_sha256,
                chars=len(cleaned),
            )
            code = str(admitted.get("code") or "storage_unavailable")
            if not durable_recorded:
                code = "storage_unavailable"
            raise AgentTtsError("Production AI budget denied: " + code)
        durable_reserved = True

    try:
        try:
            audio = _openai_speech(
                text=cleaned,
                profile=profile,
                api_key=api_key,
                endpoint_url=str(backend.get("endpoint_url") or OPENAI_SPEECH_URL),
                backend_provider=backend_provider,
            )
        except AgentTtsError as exc:
            durable_recorded = _record_production_tts_usage(
                request_id,
                production_scope,
                agent_id=aid,
                model=model,
                status="error",
                input_tokens=estimated_input_tokens,
                cost_usd=estimated_cost,
                prompt_sha256=prompt_sha256,
                chars=len(cleaned),
            )
            if production_scope is not None and not durable_recorded:
                raise AgentTtsError("Production AI usage storage is unavailable.") from None
            return _browser_fallback(profile, reason=f"provider_error:{exc}", chars=len(cleaned))

        durable_recorded = _record_production_tts_usage(
            request_id,
            production_scope,
            agent_id=aid,
            model=model,
            status="success",
            input_tokens=estimated_input_tokens,
            cost_usd=estimated_cost,
            prompt_sha256=prompt_sha256,
            chars=len(cleaned),
        )
        if production_scope is not None and not durable_recorded:
            raise AgentTtsError("Production AI usage storage is unavailable.")
    finally:
        if production_scope is not None and durable_reserved and not durable_recorded:
            try:
                from .. import ai_budgets
                ai_budgets.cancel_reservation(
                    request_id, production_scope["workspace_id"],
                )
            except Exception:
                pass

    _write_cache(key, audio)
    return {
        "audio": audio,
        "content_type": "audio/mpeg",
        "model": model,
        "voice": profile.get("voice"),
        "cached": False,
        "agent_id": aid,
        "chars": len(cleaned),
        "speed": profile.get("speed"),
        "tts_provider": provider,
        "tts_model": model,
        "language": profile.get("language"),
    }


def preview_speech(agent_id: str, *, profile_override: Optional[Dict[str, Any]] = None,
                   scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    aid = normalize_agent_id(agent_id)
    phrase = PREVIEW_PHRASES.get(aid, PREVIEW_PHRASES["vitek"])
    return synthesize(
        phrase, agent_id=aid, profile_override=profile_override, scope=scope,
    )


def speak_result_headers(result: Dict[str, Any]) -> Dict[str, str]:
    return {
        "X-TTS-Agent": str(result.get("agent_id") or ""),
        "X-TTS-Voice": str(result.get("voice") or ""),
        "X-TTS-Model": str(result.get("tts_model") or result.get("model") or ""),
        "X-TTS-Provider": str(result.get("tts_provider") or ""),
        "X-TTS-Cached": "1" if result.get("cached") else "0",
        "X-TTS-Chars": str(result.get("chars") or 0),
        "X-TTS-Speed": str(result.get("speed") or ""),
        "X-TTS-Fallback": "1" if result.get("fallback") == "browser" else "0",
    }
