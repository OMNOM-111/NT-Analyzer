"""Shared Persona/PI HTTP contracts. Disposable authority, no external TTS/model."""
import copy

import pytest

from app.ai_control_center import domain_gateway as gateway, live_http_api, persona_voice
from app.ai_control_center.states import ContractError
from tests.test_agent_world_domain_gateway import models, ordinary, Handler, http_get, http_post
from tests.test_agent_world_live_gateway import owner, isolated_runtime


@pytest.fixture(autouse=True)
def tts_transport_boundary(monkeypatch):
    monkeypatch.setattr(Handler, "_respond_tts", lambda self, value: self._json(200, value), raising=False)


def create_persona(env):
    response = http_post(env.account, "domains/personas/new/create", {
        "payload": {"name": "Марина · тест интерфейса", "description": "Изолированная Persona",
                    "avatar_key": "marina", "style": "Спокойный", "voice_mode": "browser"},
        "idempotency_key": "shared-acceptance-persona"})
    assert response.status == 200, response.result
    return response.result["item"]


def test_persona_catalog_and_audio_use_persisted_own_profile(models, monkeypatch):
    person = create_persona(models)
    calls = []
    def synthesize(text, **kwargs):
        calls.append((text, kwargs))
        assert kwargs["profile_override"]["tts_provider"] == "browser"
        assert kwargs["scope"]["uses_owner_runtime"] is False
        return {"fallback": "browser", "language": "ru-RU"}
    monkeypatch.setattr(persona_voice.agent_tts, "synthesize", synthesize)
    monkeypatch.setattr(persona_voice.agent_tts, "get_voice_profile", lambda *args: pytest.fail("owner voice settings read"))
    monkeypatch.setattr(Handler, "_respond_tts", lambda self, value: self._json(200, value), raising=False)
    listing = http_get(models.account, "domains/personas")
    assert listing.status == 200
    assert listing.result["presentation_catalog"]["lip_sync_available"] is False
    response = http_post(models.account, "domains/personas/" + person["id"] + "/speak", {
        "payload": {"text": "Проверенный текст тестового сообщения."},
        "expected_revision": person["revision"], "idempotency_key": "persona-speech-gesture"})
    assert response.status == 200, response.result
    assert response.result["persona_id"] == person["id"]
    assert response.result["fallback"] == "browser" and len(calls) == 1
    assert models.executions == []


@pytest.mark.parametrize("field", ["scope", "user_uuid", "api_key", "voice_mode", "voice", "is_owner"])
def test_persona_voice_body_cannot_replace_authority_or_persisted_voice(models, monkeypatch, field):
    person = create_persona(models)
    monkeypatch.setattr(persona_voice.agent_tts, "synthesize", lambda *args, **kwargs: pytest.fail("tampered voice executed"))
    response = http_post(models.account, "domains/personas/" + person["id"] + "/speak", {
        "payload": {"text": "Проверка", field: "not-authority"},
        "expected_revision": person["revision"], "idempotency_key": "invalid-persona-speech"})
    assert response.status in {403, 409}


def test_persona_voice_rejects_stale_revision_and_revoked_session(models, monkeypatch):
    person = create_persona(models)
    body = {"payload": {"text": "Проверка"}, "expected_revision": person["revision"] - 1,
            "idempotency_key": "stale-persona-speech"}
    monkeypatch.setattr(persona_voice.agent_tts, "synthesize", lambda *args, **kwargs: pytest.fail("stale voice executed"))
    response = http_post(models.account, "domains/personas/" + person["id"] + "/speak", body)
    assert response.status == 409
    models.account.state["session_active"] = False
    body["expected_revision"] = person["revision"]
    response = http_post(models.account, "domains/personas/" + person["id"] + "/speak", body)
    assert response.status == 409 or response.status == 403


@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_process_read_is_scoped_side_effect_free_and_read_only_actions_removed(models, monkeypatch, domain):
    from app.ai_control_center.process_intelligence import ProcessIntelligence
    seen = []
    candidate = {"id": "a" * 64, "domain": domain, "source_sha256": "b" * 64, "actions": ["propose"]}
    def analyze(self, *, context, admit):
        admit()
        seen.append(context)
        return {"candidates": [copy.deepcopy(candidate), {"domain": "not-this-domain"}],
                "automation_enabled": False, "quality_claim": False, "excluded": {"provider_plan_only": 3}}
    monkeypatch.setattr(ProcessIntelligence, "analyze", analyze)
    response = http_get(models.account, "domains/" + domain)
    assert response.status == 200, response.result
    assert response.result["process_intelligence"]["candidates"] == [candidate]
    assert seen == [models.context]
    assert not models.queue and not models.executions
    models.account.state["permissions"]["capabilities"]["ai_lab"] = False
    response = http_get(models.account, "domains/" + domain)
    assert response.status == 200, response.result
    assert response.result["process_intelligence"]["candidates"][0]["actions"] == []


@pytest.mark.parametrize("domain", ["routines", "calendar"])
def test_process_propose_is_not_accept_and_accept_revalidates_sources(models, monkeypatch, domain):
    from app.ai_control_center.process_intelligence import ProcessIntelligence
    calls = []
    def propose(self, **kwargs):
        kwargs["admit"]()
        calls.append(kwargs)
        return {"domain": domain, "item": {"status": "proposed"}, "replayed": False}
    monkeypatch.setattr(ProcessIntelligence, "propose", propose)
    response = http_post(models.account, "domains/" + domain + "/" + "a" * 64 + "/propose", {
        "payload": {"source_sha256": "b" * 64}, "idempotency_key": "explicit-process-proposal"})
    assert response.status == 200 and response.result["item"]["status"] == "proposed"
    assert len(calls) == 1 and calls[0]["context"] == models.context
    def changed(self, **kwargs):
        raise ContractError("process_sources_changed")
    monkeypatch.setattr(ProcessIntelligence, "validate_suggestion", changed)
    response = http_post(models.account, "domains/" + domain + "/00000000-0000-4000-8000-000000000009/accept", {
        "payload": {}, "expected_revision": 1, "idempotency_key": "accept-stale-process"})
    assert response.status == 409 and response.result["code"] == "process_sources_changed"
    assert not models.queue and not models.executions
