"""Selected Persona travels separately through HTTP/queue/Chief; no model calls."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import local_worker, server
from app.ai_lab import chief_agent
from app.ai_control_center import coordinator, live_gateway, persona_identity
from app.ai_control_center.states import ContractError
from tests.test_local_worker import _isolate


def test_http_queue_preserves_explicit_persona_without_replacing_legacy_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(local_worker, "start_background_worker", lambda **kw: None)
    monkeypatch.setattr(local_worker, "enqueue_ai_message", lambda *a, **kw: calls.append((a, kw)) or {"ok": True})
    identity = str(uuid4())
    owner_scope = {"user_id": 7, "workspace_id": "ws_selected"}
    handler = SimpleNamespace(headers={})
    server.Handler._enqueue_ai_message(handler, {"message": "Привет", "request_id": "selected-1",
        "persona_id": identity, "agent": "legacy-unmodified", "scope": {"user_id": 999}}, scope=owner_scope)
    assert calls[0][0] == ("Привет",)
    assert calls[0][1]["persona_id"] == identity
    assert calls[0][1]["agent"] == "legacy-unmodified"
    assert calls[0][1]["scope"] is owner_scope


@pytest.mark.parametrize("value", [None, "", "tolik", {}, "../private"])
def test_http_refuses_invalid_explicit_identity_before_starting_worker(monkeypatch, value):
    monkeypatch.setattr(local_worker, "start_background_worker", lambda **kw: pytest.fail("worker must not start"))
    with pytest.raises(ContractError, match="persona_selection_invalid"):
        server.Handler._enqueue_ai_message(SimpleNamespace(headers={}), {"message": "test", "persona_id": value},
            scope={"user_id": 7, "workspace_id": "ws_selected"})


def test_optional_identity_stays_absent_for_legacy_callers(monkeypatch):
    calls = []
    monkeypatch.setattr(local_worker, "start_background_worker", lambda **kw: None)
    monkeypatch.setattr(local_worker, "enqueue_ai_message", lambda *a, **kw: calls.append(kw) or {})
    server.Handler._enqueue_ai_message(SimpleNamespace(headers={}), {"message": "legacy"}, scope={})
    assert "persona_id" not in calls[0]


def test_selected_persona_durable_replay_does_not_change_message_or_identity(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    identity = str(uuid4())
    scope = {"user_id": 7, "workspace_id": "ws_selected"}
    params = {"request_id": "persona-one", "conversation_id": "PERSONA-ONE", "scope": scope,
              "agent": "", "persona_id": identity, "mirror_to_telegram": False}
    calls = []
    monkeypatch.setattr(chief_agent, "handle_message", lambda *a, **kw: calls.append((a, kw)) or {"ok": True})
    first = local_worker.enqueue_ai_message("Привет, агент", **params)
    same = local_worker.enqueue_ai_message("Привет, агент", **params)
    assert first["worker_job_id"] == same["worker_job_id"]
    assert first["payload"]["persona_id"] == identity
    for body, changed in [("Изменение задания", {}), ("Привет, агент", {"persona_id": str(uuid4())}),
                          ("Привет, агент", {"conversation_id": "OTHER"})]:
        with pytest.raises(ValueError, match="persona_request_id_conflict"):
            local_worker.enqueue_ai_message(body, **{**params, **changed})
    done = local_worker.run_once(worker_id="selected-persona-test")
    assert done["status"] == "succeeded"
    assert len(calls) == 1 and calls[0][1]["persona_id"] == identity
    assert calls[0][0] == ("Привет, агент",)
    assert local_worker.get(first["worker_job_id"], workspace_id="other") is None


def test_chief_routes_selected_persona_after_nonmatching_coordinator_preflight(monkeypatch):
    identity, calls = str(uuid4()), []
    scope = {"user_id": 7, "workspace_id": "ws_selected"}
    monkeypatch.setattr(persona_identity, "try_chat", lambda message, **kw: calls.append((message, kw)) or {"selected": True})
    original_preflight = coordinator.try_chat
    preflights = []
    def preflight(*args, **kwargs):
        result = original_preflight(*args, **kwargs)
        preflights.append(result)
        assert not calls and result is None
        return result
    monkeypatch.setattr(coordinator, "try_chat", preflight)
    monkeypatch.setattr(live_gateway, "try_chat", lambda *a, **kw: pytest.fail("not legacy application"))
    result = chief_agent._handle_message_impl("  Ассистент, привет  ", scope=scope, persona_id=identity,
                                            conversation_id="PERSONA-ONE", request_id="persona-one")
    assert result == {"selected": True}
    assert preflights == [None]
    assert calls[0][0] == "Ассистент, привет"
    assert calls[0][1]["persona_id"] == identity and calls[0][1]["scope"] is scope


def test_chief_never_falls_back_when_selected_persona_is_unavailable(monkeypatch):
    original_preflight = coordinator.try_chat
    preflights = []
    def preflight(*args, **kwargs):
        result = original_preflight(*args, **kwargs)
        preflights.append(result)
        assert result is None
        return result
    def deny(*a, **kw):
        assert preflights == [None]
        raise ContractError("persona_selection_unavailable")
    monkeypatch.setattr(persona_identity, "try_chat", deny)
    monkeypatch.setattr(coordinator, "try_chat", preflight)
    monkeypatch.setattr(live_gateway, "try_chat", lambda *a, **kw: pytest.fail("no fallback"))
    with pytest.raises(ContractError, match="persona_selection_unavailable"):
        chief_agent._handle_message_impl("Привет", persona_id=str(uuid4()),
            scope={"user_id": 7, "workspace_id": "ws_selected"})
    assert preflights == [None]
