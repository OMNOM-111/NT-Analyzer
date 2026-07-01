from __future__ import annotations

import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app import secure_store
from app import server as server_mod
from app.ai_lab import agent_registry, agent_router, universal_llm


@pytest.fixture()
def isolated_agents(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_registry, "registry_path", lambda: tmp_path / "ai_agents.registry.json")
    monkeypatch.setattr(agent_registry, "usage_dir", lambda: tmp_path / "agent_usage")
    monkeypatch.setattr(secure_store, "store_path", lambda: tmp_path / "ai_agent_keys.dpapi")
    if os.name != "nt":
        monkeypatch.setattr(secure_store, "available", lambda: True)
        monkeypatch.setattr(secure_store, "_protect", lambda data: data[::-1])
        monkeypatch.setattr(secure_store, "_unprotect", lambda data: data[::-1])
    universal_llm._RESERVATIONS.clear()
    return tmp_path


def azure_payload(**overrides):
    payload = {
        "name": "Azure Student GPT",
        "provider": "azure_foundry",
        "base_url": "https://student-resource.services.ai.azure.com",
        "model": "gpt-5-mini",
        "endpoint_type": "chat",
        "api_key": "sk-student-example-1234abcd",
        "auth_type": "api-key",
        "role": "coder",
        "purpose": "Targeted coding fallback",
        "input_price_usd_per_m": 0.25,
        "cached_input_price_usd_per_m": 0.025,
        "output_price_usd_per_m": 2.0,
        "daily_budget_usd": 1.0,
        "monthly_budget_usd": 5.0,
        "credit_total_usd": 100.0,
        "credit_started_at_utc": "2026-06-30",
        "enabled": False,
    }
    payload.update(overrides)
    return payload


def test_dpapi_store_masks_and_never_writes_plaintext(isolated_agents) -> None:
    secret = "sk-student-example-1234abcd"
    secure_store.set_secret("agent:test", secret)

    assert secure_store.get_secret("agent:test") == secret
    assert secure_store.secret_mask("agent:test") == "sk-****abcd"
    assert secret.encode("utf-8") not in secure_store.store_path().read_bytes()
    assert secure_store.delete_secret("agent:test") is True
    assert secure_store.get_secret("agent:test") is None


def test_agent_crud_returns_mask_not_key(isolated_agents) -> None:
    created = agent_registry.create_agent(azure_payload())

    assert created["provider"] == "azure_foundry"
    assert created["key_mask"] == "sk-****abcd"
    assert created["key_configured"] is True
    assert "api_key" not in created
    assert "student-example" not in json.dumps(created)
    metadata = agent_registry.registry_path().read_text(encoding="utf-8")
    assert "student-example" not in metadata

    updated = agent_registry.update_agent(created["id"], {"name": "Azure GPT edited", "monthly_budget_usd": 7})
    assert updated["name"] == "Azure GPT edited"
    assert updated["monthly_budget_usd"] == 7
    assert updated["key_mask"] == "sk-****abcd"

    deleted = agent_registry.delete_agent(created["id"])
    assert deleted["deleted"] == created["id"]
    assert agent_registry.list_agents() == []


def test_placeholder_key_and_insecure_url_are_rejected(isolated_agents) -> None:
    with pytest.raises(agent_registry.AgentRegistryError, match="реальный API-ключ"):
        agent_registry.create_agent(azure_payload(api_key="YOUR_API_KEY_HERE"))
    with pytest.raises(agent_registry.AgentRegistryError, match="HTTPS"):
        agent_registry.create_agent(azure_payload(base_url="http://example.com"))


def test_credit_remaining_uses_reported_snapshot_then_local_usage(isolated_agents) -> None:
    agent = agent_registry.create_agent(azure_payload(
        credit_remaining_reported_usd=100,
        credit_reported_at_utc="2026-06-30T00:00:00Z",
    ))
    agent_registry.record_usage({
        "timestamp_utc": "2026-06-30T12:00:00Z",
        "request_id": "REQ-1", "agent_id": agent["id"], "agent_name": agent["name"],
        "provider": agent["provider"], "model": agent["model"], "role": agent["role"],
        "endpoint_type": "chat", "input_tokens": 10, "cached_input_tokens": 0,
        "output_tokens": 10, "total_tokens": 20, "cost_usd": 1.25,
        "status": "success", "elapsed_sec": 1, "error": None,
    })

    refreshed = agent_registry.get_agent(agent["id"])
    assert refreshed["credit_balance_source"] == "reported_plus_local_usage"
    assert refreshed["credit_remaining_estimated_usd"] == 98.75
    assert refreshed["spend_all_time_usd"] == 1.25


def test_credit_is_shared_by_provider_and_account(isolated_agents) -> None:
    first = agent_registry.create_agent(azure_payload(
        name="Azure chat", account_name="Azure Student Grant ($100)", model="gpt-5-mini",
    ))
    second = agent_registry.create_agent(azure_payload(
        name="Azure embeddings", account_name="Azure Student Grant ($100)", model="text-embedding-3-small",
    ))
    agent_registry.record_usage({
        "timestamp_utc": "2026-07-01T12:00:00Z", "request_id": "REQ-SHARED",
        "agent_id": first["id"], "agent_name": first["name"], "provider": "azure_foundry",
        "account_name": "Azure Student Grant ($100)", "model": first["model"], "role": first["role"],
        "endpoint_type": "chat", "input_tokens": 10, "cached_input_tokens": 0,
        "output_tokens": 10, "total_tokens": 20, "cost_usd": 2.0, "cost_known": True,
        "status": "success", "elapsed_sec": 1, "error": None,
    })

    refreshed = agent_registry.get_agent(second["id"])
    assert refreshed["account_models"] == 2
    assert refreshed["credit_total_usd"] == 100
    assert refreshed["credit_remaining_estimated_usd"] == 98


def test_azure_foundry_connection_uses_api_key_header_and_v1_endpoint(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent(azure_payload())
    captured = {}

    def fake_request(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return {
            "choices": [{"message": {"content": "CONNECTION_OK"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        }

    monkeypatch.setattr(universal_llm, "_request_json", fake_request)
    result = universal_llm.test_connection(agent["id"])

    assert result["ok"] is True
    assert captured["url"].endswith("/openai/v1/chat/completions")
    assert captured["headers"]["api-key"] == "sk-student-example-1234abcd"
    assert captured["payload"]["model"] == "gpt-5-mini"
    assert "max_completion_tokens" in captured["payload"]
    log = agent_registry.usage_path().read_text(encoding="utf-8")
    assert "CONNECTION_OK" not in log
    assert "Reply with exactly" not in log
    assert "student-example" not in log


def test_azure_full_responses_endpoint_is_used_without_duplicate_suffix(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent(azure_payload(
        daily_budget_usd=0, monthly_budget_usd=0,
        input_price_usd_per_m=0, output_price_usd_per_m=0,
        base_url="https://student-resource.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview",
    ))
    captured = {}

    def fake_request(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return {
            "output": [{"content": [{"type": "output_text", "text": "CONNECTION_OK"}]}],
            "usage": {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
        }

    monkeypatch.setattr(universal_llm, "_request_json", fake_request)
    result = universal_llm.test_connection(agent["id"])

    assert result["ok"] is True
    assert captured["url"].endswith("/openai/responses?api-version=2025-04-01-preview")
    assert "/chat/completions" not in captured["url"]
    assert captured["payload"]["input"]
    assert "messages" not in captured["payload"]


def test_azure_full_legacy_embedding_endpoint_is_not_modified(isolated_agents, monkeypatch) -> None:
    endpoint = "https://student-resource.cognitiveservices.azure.com/openai/deployments/text-embedding-3-small/embeddings?api-version=2023-05-15"
    agent = agent_registry.create_agent(azure_payload(
        name="Azure exact embedding", base_url=endpoint, model="text-embedding-3-small",
        role="general", endpoint_type="chat", input_price_usd_per_m=0, output_price_usd_per_m=0,
    ))
    captured = {}

    def fake_request(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return {"data": [{"embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 3, "total_tokens": 3}}

    monkeypatch.setattr(universal_llm, "_request_json", fake_request)
    result = universal_llm.test_connection(agent["id"], "embed")

    assert result["ok"] is True
    assert captured["url"] == endpoint
    assert "model" not in captured["payload"]
    assert agent_registry.get_agent(agent["id"])["endpoint_type"] == "embeddings"


def test_gemini_text_model_is_auto_classified_as_generate_content(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent(azure_payload(
        name="Gemini free key", provider="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        model="gemini-2.5-flash", auth_type="x-goog-api-key",
        endpoint_type="embeddings", role="backtest_analyst", billing_mode="free_tier",
        credit_total_usd=0, daily_budget_usd=0, monthly_budget_usd=0,
    ))
    captured = {}

    def fake_request(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return {
            "candidates": [{"content": {"parts": [{"text": "CONNECTION_OK"}]}}],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2},
        }

    monkeypatch.setattr(universal_llm, "_request_json", fake_request)
    result = universal_llm.test_connection(agent["id"])

    assert result["ok"] is True
    assert captured["url"].endswith("models/gemini-2.5-flash:generateContent")
    assert ":embedContent" not in captured["url"]
    assert agent_registry.get_agent(agent["id"])["endpoint_type"] == "chat"


def test_embedding_agent_reports_dimensions(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent(azure_payload(
        name="Azure embeddings", model="text-embedding-3-small",
        endpoint_type="embeddings", role="embedding",
        input_price_usd_per_m=0.02, output_price_usd_per_m=0,
    ))
    monkeypatch.setattr(universal_llm, "_request_json", lambda *_a, **_k: {
        "data": [{"embedding": [0.1, 0.2, 0.3]}],
        "usage": {"prompt_tokens": 4, "total_tokens": 4},
    })

    result = universal_llm.test_connection(agent["id"], "embed this")

    assert result["ok"] is True
    assert "3 dimensions" in result["response"]
    assert result["output_tokens"] == 0


def test_budget_gate_auto_disables_before_network_call(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent(azure_payload(
        enabled=True, daily_budget_usd=0.000001, monthly_budget_usd=0.000001,
        input_price_usd_per_m=100, output_price_usd_per_m=100,
    ))
    calls = []
    monkeypatch.setattr(universal_llm, "_request_json", lambda *_a, **_k: calls.append(True))

    result = universal_llm.test_connection(agent["id"], "budget test")

    assert result["ok"] is False
    assert calls == []
    refreshed = agent_registry.get_agent(agent["id"])
    assert refreshed["enabled"] is False
    assert refreshed["disabled_reason"] == "daily_budget_exceeded"


def test_zero_budgets_mean_monitor_only_and_do_not_block(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent(azure_payload(
        daily_budget_usd=0, monthly_budget_usd=0,
        input_price_usd_per_m=0, output_price_usd_per_m=0,
    ))
    monkeypatch.setattr(universal_llm, "_request_json", lambda *_a, **_k: {
        "choices": [{"message": {"content": "CONNECTION_OK"}}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2},
    })

    result = universal_llm.test_connection(agent["id"])

    assert result["ok"] is True
    refreshed = agent_registry.get_agent(agent["id"])
    assert refreshed["budget_mode"] == "monitor_only"
    assert refreshed["disabled_reason"] != "daily_budget_exceeded"


def test_openrouter_credit_sync_updates_reported_balance(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent(azure_payload(
        name="OpenRouter agent", provider="openrouter",
        base_url="https://openrouter.ai/api/v1", auth_type="bearer",
        model="openai/gpt-5-mini",
    ))
    monkeypatch.setattr(universal_llm, "_request_json", lambda *_a, **_k: {
        "data": {"total_credits": 100.5, "total_usage": 25.75},
    })

    updated = universal_llm.sync_credit_balance(agent["id"])

    assert updated["credit_total_usd"] == 100.5
    assert updated["credit_remaining_reported_usd"] == 74.75


def test_openrouter_deprecated_free_slug_is_remapped_on_save(isolated_agents) -> None:
    created = agent_registry.create_agent(azure_payload(
        name="OpenRouter free", provider="openrouter",
        base_url="https://openrouter.ai/api/v1", auth_type="bearer",
        model="deepseek/deepseek-v4-flash:free",
        billing_mode="unknown", credit_total_usd=0,
        daily_budget_usd=0, monthly_budget_usd=0,
        input_price_usd_per_m=0, output_price_usd_per_m=0,
    ))

    assert created["model"] == "openrouter/free"
    assert created["billing_mode"] == "free_tier"
    assert created["pricing_status"] == "free"


def test_openrouter_free_model_normalization_helpers() -> None:
    assert agent_registry.normalize_openrouter_model("deepseek/deepseek-v4-flash:free") == "openrouter/free"
    assert agent_registry.normalize_openrouter_model("openrouter/free") == "openrouter/free"
    assert agent_registry.is_openrouter_free_model("cohere/north-mini-code:free") is True
    assert agent_registry.infer_billing_mode("openrouter", "openrouter/free", 0) == "free_tier"


def test_openrouter_repair_doc_fixes_legacy_registry(isolated_agents) -> None:
    path = agent_registry.registry_path()
    path.write_text(json.dumps({
        "schema_version": agent_registry.SCHEMA_VERSION,
        "updated_at_utc": "2026-07-01T00:00:00Z",
        "agents": [{
            "id": "AGT-LEGACY",
            "name": "legacy",
            "provider": "openrouter",
            "model": "deepseek/deepseek-chat:free",
            "billing_mode": "unknown",
            "base_url": "https://openrouter.ai/api/v1",
            "auth_type": "bearer",
            "enabled": False,
        }],
    }), encoding="utf-8")
    secure_store.set_secret("ai-agent:AGT-LEGACY", "sk-openrouter-test-key-1234")

    listed = agent_registry.list_agents()

    assert listed[0]["model"] == "openrouter/free"
    assert listed[0]["billing_mode"] == "free_tier"


def test_agent_http_routes(monkeypatch) -> None:
    safe = {"agents": [], "storage": {"available": True}, "providers": [], "roles": []}
    monkeypatch.setattr(agent_registry, "summary", lambda: safe)
    monkeypatch.setattr(agent_registry, "create_agent", lambda body: {"id": "AGT-1", "name": body["name"], "key_mask": "sk-****abcd"})
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/ai-agents", timeout=5) as response:
            listed = json.load(response)
        request = urllib.request.Request(
            f"http://{host}:{port}/api/ai-agents",
            data=json.dumps({"agent": {"name": "test", "api_key": "YOUR_API_KEY_HERE"}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            created = json.load(response)
        assert listed["storage"]["available"] is True
        assert created["agent"]["key_mask"] == "sk-****abcd"
        assert "YOUR_API_KEY_HERE" not in json.dumps(created)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_agent_router_normalizes_response_to_content(monkeypatch) -> None:
    monkeypatch.setattr(agent_router, "candidates", lambda *args, **kwargs: [{
        "id": "AGT-1", "account_name": "test", "provider": "azure_foundry",
        "model": "gpt-5-mini",
    }])
    monkeypatch.setattr(universal_llm, "invoke_agent", lambda *args, **kwargs: {
        "ok": True, "response": '{"status":"OK"}', "provider": "azure_foundry",
        "model": "gpt-5-mini",
    })

    result = agent_router.invoke_role("hypothesis", "test")

    assert result["content"] == '{"status":"OK"}'


def test_agent_router_fails_over_and_cools_down_retryable_provider(monkeypatch) -> None:
    route = [
        {"id": "AGT-1", "account_name": "key-1", "provider": "gemini", "model": "gemini-2.5-flash"},
        {"id": "AGT-2", "account_name": "key-2", "provider": "gemini", "model": "gemini-2.5-flash"},
    ]
    monkeypatch.setattr(agent_router, "candidates", lambda *args, **kwargs: route)
    calls = []
    cooldowns = []

    def fake_invoke(agent_id, *args, **kwargs):
        calls.append(agent_id)
        if agent_id == "AGT-1":
            raise universal_llm.UniversalLLMError("Provider отклонил запрос (HTTP 429): quota")
        return {"ok": True, "response": "complete", "provider": "gemini", "model": "gemini-2.5-flash"}

    monkeypatch.setattr(universal_llm, "invoke_agent", fake_invoke)
    monkeypatch.setattr(agent_registry, "set_cooldown", lambda agent_id, seconds, reason: cooldowns.append((agent_id, seconds, reason)))

    result = agent_router.invoke_role("backtest_analyst", "test")

    assert calls == ["AGT-1", "AGT-2"]
    assert cooldowns and cooldowns[0][0] == "AGT-1"
    assert result["content"] == "complete"
    assert [row["status"] for row in result["route_attempts"]] == ["error", "success"]


def test_ai_agents_page_and_navigation_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    page = (root / "app" / "static" / "aurora" / "ai-agents.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "aurora" / "assets" / "pages" / "ai-agents.js").read_text(encoding="utf-8")
    api = (root / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    server = (root / "app" / "server.py").read_text(encoding="utf-8")
    for label in ("Add Model", "Edit Model", "Delete Model", "Test Connection", "Enable Agent", "Disable Agent"):
        assert label in page + js
    assert 'type="password"' in js
    assert "API.http.aiAgentCreate" in js and "API.http.aiAgentTest" in js
    assert "/api/ai-agents" in api
    assert "ai-agents.html" in ui and '"/ai-agents.html"' in server
