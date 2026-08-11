"""Tests for Orchestrator avatar TTS and per-agent voice profiles."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.ai_lab import agent_tts


@pytest.fixture()
def isolated_voices(tmp_path, monkeypatch):
    store = tmp_path / "agent_voices.json"
    cache = tmp_path / "tts-cache"
    cache.mkdir()
    monkeypatch.setattr(agent_tts, "VOICES_PATH", store)
    monkeypatch.setattr(agent_tts, "voices_store_path", lambda: store)
    monkeypatch.setattr(agent_tts, "cache_dir", lambda: cache)
    return store, cache


def speech_backend(api_key: str = "sk-test-key-1234567890") -> dict[str, str]:
    return {
        "api_key": api_key,
        "provider": "openai",
        "endpoint_url": agent_tts.OPENAI_SPEECH_URL,
        "source": "test",
        "agent_id": "",
        "model": "",
    }


def test_normalize_and_default_voices_differ():
    assert agent_tts.normalize_agent_id("Марина") == "marina"
    assert agent_tts.normalize_agent_id("accountant") == "marina"
    marina = agent_tts.get_voice_profile("marina")
    vitek = agent_tts.get_voice_profile("vitek")
    assert marina["voice"] != vitek["voice"]
    assert marina["voice_gender"] == "female"
    assert vitek["voice_gender"] == "male"
    assert marina["source"] == "default"


def test_prepare_text_strips_markdown_and_urls():
    raw = "Смотри **отчёт** и [ссылку](https://example.com/x) плюс `code` ```block``` https://a.b/c"
    out = agent_tts.prepare_text(raw)
    assert "https://" not in out
    assert "```" not in out
    assert "отчёт" in out
    assert "ссылку" in out
    with pytest.raises(agent_tts.AgentTtsError):
        agent_tts.prepare_text("   ")


def test_save_load_reset_voice_profile(isolated_voices):
    saved = agent_tts.set_voice_profile("tolik", {
        "voice": "fable",
        "speed": 0.88,
        "tts_model": "gpt-4o-mini-tts",
        "style": "slow analyst",
        "instructions": "Speak slowly.",
    })
    assert saved["is_custom"] is True
    assert saved["voice"] == "fable"
    assert saved["speed"] == 0.88
    loaded = agent_tts.get_voice_profile("tolik")
    assert loaded["voice"] == "fable"
    assert loaded["source"] == "stored"
    # Other agents untouched.
    assert agent_tts.get_voice_profile("marina")["voice"] == "nova"
    reset = agent_tts.reset_voice_profile("tolik")
    assert reset["is_custom"] is False
    assert reset["voice"] == agent_tts.DEFAULT_PROFILES["tolik"]["voice"]


def test_preset_apply_and_catalog():
    applied = agent_tts.apply_preset("ivan", "strict_leader")
    assert applied["voice"] == "sage"
    assert applied["preset_id"] == "strict_leader"
    catalog = agent_tts.tts_catalog()
    assert catalog["providers"]
    openai = catalog["providers"][0]
    mini = next(m for m in openai["models"] if m["id"] == "gpt-4o-mini-tts")
    assert mini["supports"]["instructions"] is True
    assert mini["supports"]["pitch"] is False


def test_cache_key_includes_profile_fields(isolated_voices, monkeypatch):
    monkeypatch.setattr(agent_tts, "resolve_speech_backend", lambda profile=None: speech_backend())
    calls = {"n": 0}

    def fake_speech(**kwargs: Any) -> bytes:
        calls["n"] += 1
        return b"ID3" + (b"fake-mp3-audio-bytes-" * 8)

    monkeypatch.setattr(agent_tts, "_openai_speech", fake_speech)
    first = agent_tts.synthesize("Проверка кэша.", agent_id="marina")
    assert first["cached"] is False
    second = agent_tts.synthesize("Проверка кэша.", agent_id="marina")
    assert second["cached"] is True
    assert calls["n"] == 1
    # Changing voice profile must miss the old cache entry.
    agent_tts.set_voice_profile("marina", {
        **agent_tts.get_voice_profile("marina"),
        "speed": 1.2,
        "voice": "shimmer",
    })
    third = agent_tts.synthesize("Проверка кэша.", agent_id="marina")
    assert third["cached"] is False
    assert calls["n"] == 2


def test_synthesize_falls_back_without_api_key(isolated_voices, monkeypatch):
    monkeypatch.setattr(agent_tts, "resolve_speech_backend", lambda profile=None: {})
    result = agent_tts.synthesize("Привет, это тест озвучки.", agent_id="tolik")
    assert result["fallback"] == "browser"
    assert result["agent_id"] == "tolik"
    assert result["language"] == "ru-RU"
    assert "audio" not in result


def test_resolve_backend_uses_disabled_azure_speech_agent(monkeypatch):
    from app.ai_lab import agent_registry

    monkeypatch.delenv(agent_tts.KEY_ENV, raising=False)
    monkeypatch.setattr(agent_tts.local_secrets, "apply", lambda: False)
    monkeypatch.setattr(agent_registry, "list_agents", lambda: [{
        "id": "AGT-TTS",
        "provider": "azure_foundry",
        "enabled": False,
        "model": "gpt-4o-mini-tts",
        "base_url": (
            "https://example.openai.azure.com/openai/deployments/"
            "gpt-4o-mini-tts/audio/speech?api-version=2025-03-01-preview"
        ),
    }])
    monkeypatch.setattr(
        agent_registry, "get_api_key",
        lambda agent_id: "az-test-key-1234567890" if agent_id == "AGT-TTS" else "",
    )

    backend = agent_tts.resolve_speech_backend({"tts_model": "gpt-4o-mini-tts"})

    assert backend["provider"] == "azure_foundry"
    assert backend["source"] == "agent_registry:azure_speech"
    assert backend["agent_id"] == "AGT-TTS"
    assert backend["api_key"] == "az-test-key-1234567890"
    assert "/audio/speech" in backend["endpoint_url"]
    assert "api-version=2025-03-01-preview" in backend["endpoint_url"]


def test_provider_error_falls_back_quietly(isolated_voices, monkeypatch):
    monkeypatch.setattr(agent_tts, "resolve_speech_backend", lambda profile=None: speech_backend())

    def boom(**kwargs: Any) -> bytes:
        raise agent_tts.AgentTtsError("HTTP 500")

    monkeypatch.setattr(agent_tts, "_openai_speech", boom)
    result = agent_tts.synthesize("Текст.", agent_id="vitek")
    assert result["fallback"] == "browser"
    assert "provider_error" in str(result.get("reason") or "")


def test_production_tts_is_budgeted_and_cache_is_workspace_scoped(
    isolated_voices, monkeypatch,
):
    from app import ai_budgets, runtime_env

    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(agent_tts, "resolve_speech_backend", lambda profile=None: speech_backend())
    provider_calls = []
    reservations = []
    records = []

    def fake_speech(**kwargs: Any) -> bytes:
        provider_calls.append(kwargs["text"])
        return b"ID3" + (b"tenant-safe-audio-" * 8)

    monkeypatch.setattr(agent_tts, "_openai_speech", fake_speech)
    monkeypatch.setattr(
        ai_budgets,
        "reserve",
        lambda *args, **kwargs: reservations.append((args, kwargs))
        or {"ok": True, "reservation_id": "air_test"},
    )
    monkeypatch.setattr(
        ai_budgets,
        "record_usage",
        lambda *args, **kwargs: records.append((args, kwargs)) or {"ok": True},
    )

    scope_a = {"user_id": 42, "workspace_id": "ws_personal_ALPHA1234"}
    scope_b = {"user_id": 84, "workspace_id": "ws_personal_BETA12345"}
    first = agent_tts.synthesize("Одинаковый текст.", agent_id="marina", scope=scope_a)
    second = agent_tts.synthesize("Одинаковый текст.", agent_id="marina", scope=scope_a)
    third = agent_tts.synthesize("Одинаковый текст.", agent_id="marina", scope=scope_b)

    assert [first["cached"], second["cached"], third["cached"]] == [False, True, False]
    assert len(provider_calls) == 2
    assert [row[0][1] for row in reservations] == [
        "ws_personal_ALPHA1234", "ws_personal_BETA12345",
    ]
    assert [row[0][7] for row in records] == ["success", "cache_hit", "success"]
    assert [row[0][1] for row in records] == [
        "ws_personal_ALPHA1234", "ws_personal_ALPHA1234", "ws_personal_BETA12345",
    ]


def test_production_tts_budget_denial_blocks_before_provider(
    isolated_voices, monkeypatch,
):
    from app import ai_budgets, runtime_env

    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(agent_tts, "resolve_speech_backend", lambda profile=None: speech_backend())
    provider_calls = []
    records = []
    monkeypatch.setattr(
        ai_budgets, "reserve",
        lambda *_args, **_kwargs: {"ok": False, "code": "daily_budget_exceeded"},
    )
    monkeypatch.setattr(
        ai_budgets, "record_usage",
        lambda *args, **kwargs: records.append((args, kwargs)) or {"ok": True},
    )
    monkeypatch.setattr(
        agent_tts, "_openai_speech",
        lambda **_kwargs: provider_calls.append(True) or b"unreachable",
    )

    with pytest.raises(agent_tts.AgentTtsError, match="daily_budget_exceeded"):
        agent_tts.synthesize(
            "Бюджет должен сработать до сети.",
            scope={"user_id": 42, "workspace_id": "ws_personal_ALPHA1234"},
        )

    assert provider_calls == []
    assert records[-1][0][7] == "blocked"


def test_profiles_contain_no_secrets(isolated_voices):
    agent_tts.set_voice_profile("nikita", {
        "voice": "ash",
        "api_key": "sk-should-never-persist",
        "tts_model": "tts-1",
    })
    raw = isolated_voices[0].read_text(encoding="utf-8")
    assert "sk-should-never-persist" not in raw
    assert "api_key" not in raw
    profile = agent_tts.get_voice_profile("nikita")
    assert "api_key" not in profile


def test_list_voice_profiles_has_all_staff():
    doc = agent_tts.list_voice_profiles()
    ids = [row["id"] for row in doc["agents"]]
    assert ids == list(agent_tts.STAFF_ORDER)
    assert len({row["voice"]["voice"] for row in doc["agents"]}) >= 5


def test_server_ai_lab_get_voices_route():
    import io
    import json
    from app import server

    class H(server.Handler):
        def __init__(self):
            self.wfile = io.BytesIO()
            self._response_started = False
            self.responses = []
            self.headers = {}

        def send_response(self, code, message=None):
            self.responses.append(code)

        def send_header(self, k, v):
            pass

        def end_headers(self):
            pass

        def _is_client_disconnect_error(self, e):
            return False

    h = H()
    assert h._ai_lab_get("/api/ai-lab/domain-agents/voices", {}) is True
    assert h.responses[0] == 200
    doc = json.loads(h.wfile.getvalue().decode("utf-8"))
    assert len(doc.get("agents") or []) == 8
    assert doc["agents"][0]["id"] == "vitek"
    assert "voice" in doc["agents"][0]

    root = Path(__file__).resolve().parents[1]
    api = (root / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    page = (root / "app" / "static" / "aurora" / "assets" / "pages" / "ai-agents.js").read_text(encoding="utf-8")
    html = (root / "app" / "static" / "aurora" / "ai-agents.html").read_text(encoding="utf-8")
    server = (root / "app" / "server.py").read_text(encoding="utf-8")
    assert "/api/ai-lab/domain-agents/voices" in api
    assert "domainAgentVoiceSave" in api
    assert "domainAgentVoicePreview" in api
    assert "domain-agents/voices" in server
    assert 'action == "preview"' in server or "voice/preview" in server
    assert "staff-voice-grid" in html
    assert "openVoiceSettings" in page
    assert "agentSpeakFromFace" in ui
