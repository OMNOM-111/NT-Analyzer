from __future__ import annotations

import pytest
import json
import urllib.request
import urllib.error

from tests.test_preview_sandbox import preview_env
from app import account_auth, preview_sandbox, preview_shared_models, workspaces, server
from app.ai_control_center import domain_gateway
from app.ai_control_center.states import ContractError


def test_disposable_shared_chat_uses_real_model_lifecycle_and_revokes(preview_env, monkeypatch):
    monkeypatch.setenv("STRATFORGE_PREVIEW_MODEL_BRIDGE", "http://127.0.0.1:18999")
    monkeypatch.setenv("STRATFORGE_PREVIEW_MODEL_TOKEN", "fixture-bridge-token")
    session = preview_sandbox.activate_scenario("shared_models_user", device_credential="preview-bridge-browser")
    raw = account_auth.authenticate_session(session["session_token"])
    scope = workspaces.context_for_user(raw["user_id"])
    available, calls = [True], []
    def transport(path, body):
        if path == "/catalog":
            return {"items": [{"handle": "a" * 64, "label": "Shared fixture", "provider": "deepseek",
                               "model": "deepseek-v4-pro"}] if available[0] else []}
        calls.append(body)
        return {"ok": True, "response": "Preview reply", "actual_model": "deepseek-v4-pro", "request_id": f"fixture-call-{len(calls)}",
                "input_tokens": 12, "output_tokens": 3, "cost_usd": .001, "cost_known": True,
                "elapsed_sec": .01, "external_call": True, "executor": "preview_shared_local_bridge"}
    monkeypatch.setattr(preview_shared_models, "request", transport)
    class Handler:
        _remote_context = server.Handler._decorate_workspace_context(object(), raw)
        def _cookie_value(self, _): return session["session_token"]
        def _decorate_workspace_context(self, value):
            return server.Handler._decorate_workspace_context(object(), value)
        def _json(self, status, data): self.response = (status, data)
        def _err(self, status, message, **kwargs): self.response = (status, kwargs)
        def _check_local_post(self): return True
        def _read_body(self): return {}
        def _preview_control_authorized(self): return True
        def _ai_conversation_scope(self):
            return {"user_id": raw["user_id"], "user_uuid": raw["user_uuid"],
                    "workspace_id": scope["active_workspace"]["workspace_id"]}
    handler = Handler()
    result = preview_shared_models.chat(handler, {"message": "Подготовь краткий план проверки стратегии", "request_id": "preview-fixture-chat"})
    assert "Preview reply" in result["reply"]
    assert len(calls) == 1 and calls[0]["user_uuid"] == raw["user_uuid"]
    from app.ai_lab import chief_agent
    recovered = chief_agent.recover_conversation_reply(result["conversation_id"], "preview-fixture-chat",
        scope=handler._ai_conversation_scope())
    assert recovered["message"]["message_id"] == result["message"]["message_id"]
    assert recovered["recovered_from_history"] is True and len(calls) == 1
    assert chief_agent.recover_conversation_reply(result["conversation_id"], "unrelated-request",
        scope=handler._ai_conversation_scope()) is None
    auth = preview_shared_models.authorize({**handler._ai_conversation_scope(), "auth_session_id": raw["session_id"]})
    service = domain_gateway.models(auth)
    assert service.models(context=auth["context"])["items"] == []
    usage = service.shared_usage(context=auth["context"])["mine_through_others"]["total"]
    assert usage["calls"] == 1 and usage["input_tokens"] == 12 and usage["cost_usd"] == .001
    # Real tasks must remain readable through the Preview HTTP overview, not
    # the synthetic demo task projection (which expects persona_key).
    from app.ai_control_center import http_api, gateway
    http_api.handle_get(handler, gateway.PREFIX + "overview", {})
    assert handler.response[0] == 200, handler.response
    assert handler.response[1]["enabled"] is True
    assert handler.response[1]["summaries"]["models"]["items"]
    assert handler.response[1]["summaries"]["memory"]["records"] == 0
    http_api.handle_post(handler, gateway.PREFIX + "tasks/" + service.tasks(context=auth["context"])["items"][0]["id"] + "/chat")
    assert handler.response == (200, {"conversation_id": result["conversation_id"]})
    http_api.handle_get(handler, gateway.PREFIX + "tasks", {})
    assert handler.response[0] == 200 and handler.response[1]["items"]
    assert len(calls) == 1
    # Ordinary conversation uses the same grant, usage and history, but no Task/review.
    before_tasks = len(service.tasks(context=auth["context"])["items"])
    foreign = {**handler._ai_conversation_scope(), "workspace_id": "foreign-workspace"}
    chief_agent._append_conversation("user", "technical-owner-sentinel", source="app",
        path=chief_agent._conversation_file("ordinary", scope=foreign), scope=foreign)
    for index, question in enumerate(("Привет", "Что ты умеешь?", "Почему небо голубое?")):
        answer = preview_shared_models.chat(handler, {"message": question, "conversation_id": "ordinary",
            "request_id": f"conversation-{index}"})
        assert answer["reply"] == "Preview reply"
        assert answer["actions"] == [] and answer["message"]["message_kind"] == "chat"
        assert answer["message"]["role_id"] == "chief_agent"  # canonical rating alias for Deputy
        assert len(service.tasks(context=auth["context"])["items"]) == before_tasks
        repeat = preview_shared_models.chat(handler, {"message": question, "conversation_id": "ordinary",
            "request_id": f"conversation-{index}"})
        assert repeat["idempotent_replay"] and repeat["message"]["message_id"] == answer["message"]["message_id"]
    with pytest.raises(ContractError, match="conversation_request_conflict"):
        preview_shared_models.chat(handler, {"message": "Different message", "conversation_id": "ordinary",
            "request_id": "conversation-0"})
    assert len(calls) == 4
    assert all(call["agent"] == "deputy" for call in calls)
    assert all("Заместитель" in call["system_prompt"] for call in calls)
    assert 'Привет' in calls[-1]["prompt"] and 'Что ты умеешь?' in calls[-1]["prompt"]
    assert 'technical-owner-sentinel' not in calls[-1]["prompt"]
    usage = service.shared_usage(context=auth["context"])["mine_through_others"]["total"]
    assert usage["calls"] == 4 and usage["input_tokens"] == 48
    assert "доставка" not in result["reply"] and "качество" not in result["reply"]
    available[0] = False
    with pytest.raises(ContractError, match="revoked"):
        preview_shared_models.chat(handler, {"message": "Again", "request_id": "preview-fixture-after"})
    assert len(calls) == 4
    assert service.tasks(context=auth["context"])["items"]
    assert chief_agent.recover_conversation_reply(result["conversation_id"], "preview-fixture-chat",
        scope=handler._ai_conversation_scope())["reply"] == result["reply"]
    preview_sandbox.finish_preview()
    with pytest.raises(ContractError):
        preview_shared_models.authorize({**handler._ai_conversation_scope(), "auth_session_id": raw["session_id"]})


def test_preview_ai_denial_cannot_be_overridden_by_request_scope(preview_env, monkeypatch):
    monkeypatch.setenv("STRATFORGE_PREVIEW_MODEL_BRIDGE", "http://127.0.0.1:18999")
    monkeypatch.setenv("STRATFORGE_PREVIEW_MODEL_TOKEN", "fixture-bridge-token")
    session = preview_sandbox.activate_scenario("ai_denied_user", device_credential="preview-denied-browser")
    raw = account_auth.authenticate_session(session["session_token"])
    workspace = workspaces.context_for_user(raw["user_id"])["active_workspace"]["workspace_id"]
    with pytest.raises(ContractError, match="capability"):
        preview_shared_models.authorize({"user_id": raw["user_id"], "user_uuid": raw["user_uuid"],
            "workspace_id": workspace, "auth_session_id": raw["session_id"], "capabilities": {"ai_lab": True}})


def test_parent_bridge_is_call_only_authenticated_and_time_bounded(monkeypatch):
    monkeypatch.setenv("STRATFORGE_ENV", "development")
    monkeypatch.setenv("DEPLOYMENT_ENV", "development")
    monkeypatch.delenv("STRATFORGE_PREVIEW_SANDBOX", raising=False)
    bridge = preview_shared_models.Bridge("f" * 24)
    try:
        monkeypatch.setattr(bridge, "_catalog", lambda: {"opaque": {
            "label": "Shared", "provider": "deepseek", "model_key": "model",
            "model_id": "private-owner-id", "api_key": "private-key", "endpoint": "private-endpoint"}})
        with pytest.raises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(urllib.request.Request(bridge.url + "/catalog", data=b"{}"), timeout=5)
        assert denied.value.code == 403
        req = urllib.request.Request(bridge.url + "/catalog", data=b"{}",
            headers={"Authorization": "Bearer " + bridge.token})
        with urllib.request.urlopen(req, timeout=5) as response:
            catalog = json.load(response)
        assert catalog == {"items": [{"handle": "opaque", "label": "Shared", "provider": "deepseek", "model": "model"}]}
        with pytest.raises(ContractError):
            bridge.dispatch("/invoke", {"url": "http://127.0.0.1:8765/api/auth/users"})
        bridge.started -= 1801
        with pytest.raises(ContractError, match="expired"):
            bridge.dispatch("/catalog", {})
    finally:
        bridge.close()
