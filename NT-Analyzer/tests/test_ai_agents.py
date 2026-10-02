from __future__ import annotations

import json
import os
import threading
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app import account_lifecycle, secure_store
from app import server as server_mod
from app.ai_lab import agent_registry, agent_router, chief_agent, news_agent, paths, response_cache, runner, universal_llm
from app.ai_lab import orchestrator as lab_orchestrator


@pytest.fixture()
def isolated_agents(tmp_path, monkeypatch):
    # Production-routing unit cases fake model/budget boundaries, not the
    # authoritative relational deletion receipt store.
    monkeypatch.setattr(account_lifecycle, "deleted_ids", lambda: set())
    monkeypatch.setattr(account_lifecycle, "deleted_legacy_ids", lambda: set())
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


def github_models_payload(**overrides):
    payload = {
        "name": "GitHub Models GPT-4.1",
        "provider": "github_models",
        "model": "openai/gpt-4.1",
        "api_key": "github-models-test-token-not-real",
        "role": "general",
        "purpose": "GitHub-hosted GPT-4.1 within Copilot quota",
        "enabled": False,
    }
    payload.update(overrides)
    return payload


def test_ai_lab_runtime_registry_recreates_missing_files(tmp_path, monkeypatch) -> None:
    registry_dir = tmp_path / "data" / "ai_lab" / "registry"
    integrations_dir = tmp_path / "data" / "integrations"

    monkeypatch.setattr(paths, "REGISTRY_DIR", registry_dir)
    monkeypatch.setattr(paths, "ensure_dirs", lambda: registry_dir.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(agent_registry, "registry_path", lambda: integrations_dir / "ai_agents.registry.json")
    monkeypatch.setattr(agent_registry, "usage_dir", lambda: registry_dir / "agent_usage")

    assert not registry_dir.exists()

    agent_registry.record_usage({
        "timestamp_utc": "2026-08-01T00:00:00Z",
        "request_id": "REQ-EMPTY-RUNTIME",
        "agent_id": "agent-empty-runtime",
        "agent_name": "Empty Runtime Agent",
        "provider": "pytest",
        "model": "deterministic",
        "role": "general",
        "endpoint_type": "chat",
        "input_tokens": 1,
        "output_tokens": 1,
        "total_tokens": 2,
        "cost_usd": 0,
        "status": "success",
    })
    usage_files = list((registry_dir / "agent_usage").glob("*.jsonl"))
    assert len(usage_files) == 1
    assert json.loads(usage_files[0].read_text(encoding="utf-8"))["request_id"] == "REQ-EMPTY-RUNTIME"

    news_agent.observe_items([{
        "id": "NEWS-EMPTY-RUNTIME",
        "title": "Runtime registry smoke item",
        "severity": "high",
        "source": "pytest",
        "published_at_utc": "2026-08-01T00:00:00Z",
    }], send_telegram=False, use_llm=False)
    assert (registry_dir / "news_agent.json").is_file()

    chief_agent._save({"schema_version": 1, "updated_by": "pytest"})
    assert (registry_dir / "chief_agent.json").is_file()

    chief_agent._append_conversation(
        "user",
        "runtime registry smoke",
        source="pytest",
        path=chief_agent._conversation_path(),
    )
    assert (registry_dir / "orchestrator_conversation.jsonl").is_file()
    assert chief_agent._reports_dir().is_dir()


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


def test_github_models_defaults_to_free_tier_for_copilot_quota(isolated_agents) -> None:
    created = agent_registry.create_agent(github_models_payload())

    assert created["base_url"] == "https://models.github.ai/inference"
    assert created["billing_mode"] == "free_tier"
    assert created["pricing_status"] == "free"
    assert created["input_price_usd_per_m"] == 0.0
    assert created["cached_input_price_usd_per_m"] == 0.0
    assert created["output_price_usd_per_m"] == 0.0
    assert created["pricing_source_url"] == agent_registry.PROVIDERS["github_models"]["pricing_url"]


def test_github_models_payg_uses_github_token_unit_pricing(isolated_agents) -> None:
    created = agent_registry.create_agent(github_models_payload(
        name="GitHub Models paid",
        billing_mode="payg",
        monthly_budget_usd=1.0,
        enabled=True,
    ))

    assert created["billing_mode"] == "payg"
    assert created["pricing_status"] == "configured"
    assert created["input_price_usd_per_m"] == 2.0
    assert created["cached_input_price_usd_per_m"] == 0.5
    assert created["output_price_usd_per_m"] == 8.0
    assert created["pricing_source_url"] == "https://docs.github.com/en/billing/reference/models-multipliers-and-costs"


@pytest.mark.parametrize(
    ("model", "input_price", "cached_price", "output_price"),
    [
        ("openai/gpt-4.1-mini", 0.4, 0.1, 1.6),
        ("openai/gpt-4o-mini", 0.15, 0.08, 0.6),
        ("deepseek/DeepSeek-R1", 1.35, None, 5.4),
        ("microsoft/phi-4", 0.13, None, 0.5),
        ("meta/Llama-3.3-70B-Instruct", 0.71, None, 0.71),
    ],
)
def test_github_models_additional_payg_catalog_rows(isolated_agents, model: str, input_price: float,
                                                     cached_price: float | None, output_price: float) -> None:
    created = agent_registry.create_agent(github_models_payload(
        name=f"GitHub Models {model}",
        model=model,
        billing_mode="payg",
        monthly_budget_usd=1.0,
        enabled=True,
    ))

    assert created["billing_mode"] == "payg"
    assert created["pricing_status"] == "configured"
    assert created["input_price_usd_per_m"] == input_price
    assert created["cached_input_price_usd_per_m"] == cached_price
    assert created["output_price_usd_per_m"] == output_price


def test_zai_catalog_distinguishes_flagship_trial_from_permanent_free(isolated_agents) -> None:
    flagship = agent_registry.create_agent({
        "name": "ZAI GLM 5.2 trial",
        "provider": "zai",
        "model": "glm-5.2",
        "api_key": "zai-test-key-not-real-1234",
        "billing_mode": "unknown",
        "enabled": False,
    })
    flash = agent_registry.create_agent({
        "name": "ZAI GLM 4.7 Flash",
        "provider": "zai",
        "model": "glm-4.7-flash",
        "api_key": "zai-test-key-not-real-5678",
        "billing_mode": "unknown",
        "enabled": False,
    })

    assert flagship["base_url"] == "https://api.z.ai/api/paas/v4"
    assert flagship["pricing_status"] == "configured"
    assert flagship["input_price_usd_per_m"] == 1.4
    assert flagship["output_price_usd_per_m"] == 4.4
    assert flagship["billing_mode"] == "unknown"
    assert flash["billing_mode"] == "free_tier"
    assert flash["pricing_status"] == "free"


def test_deepseek_v4_pro_uses_managed_pricing_and_thinking(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent({
        "name": "DeepSeek chief",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "api_key": "sk-deepseek-test-key-1234",
        "role": "chief_agent",
        "billing_mode": "payg",
        "monthly_budget_usd": 5,
        "enabled": True,
    })
    captured = {}

    def fake_request(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return {
            "model": "deepseek-v4-pro",
            "choices": [{"message": {"content": "review complete"}}],
            "usage": {
                "prompt_tokens": 100,
                "prompt_cache_hit_tokens": 80,
                "prompt_cache_miss_tokens": 20,
                "completion_tokens": 10,
            },
        }

    monkeypatch.setattr(universal_llm, "_request_json", fake_request)
    result = universal_llm.invoke_agent(
        agent["id"], "metrics", system_prompt="stable prefix",
        request_role="chief_agent", purpose="daily_audit", max_output_tokens=9000,
    )

    assert agent["input_price_usd_per_m"] == 0.435
    assert agent["cached_input_price_usd_per_m"] == 0.003625
    assert agent["output_price_usd_per_m"] == 0.87
    assert captured["url"].endswith("/chat/completions")
    assert captured["payload"]["thinking"] == {"type": "enabled"}
    assert captured["payload"]["reasoning_effort"] == "max"
    assert captured["payload"]["user_id"] == "nt-analyzer"
    assert captured["payload"]["max_tokens"] == 8192
    assert "temperature" not in captured["payload"]
    assert result["cached_input_tokens"] == 80
    assert result["cache_miss_tokens"] == 20
    assert result["cost_usd"] > 0


def test_deepseek_reasoning_only_response_retries_without_thinking_and_accounts_both(isolated_agents, monkeypatch) -> None:
    agent = agent_registry.create_agent({
        "name": "DeepSeek chief failure accounting", "provider": "deepseek",
        "model": "deepseek-v4-pro", "api_key": "sk-deepseek-test-key-5678",
        "role": "chief_agent", "billing_mode": "payg", "monthly_budget_usd": 5,
        "enabled": True,
    })
    calls = []
    def fake_request(_url, **kwargs):
        calls.append(kwargs["payload"])
        if len(calls) == 1:
            return {
                "model": "deepseek-v4-pro",
                "choices": [{"message": {"content": "", "reasoning_content": "internal reasoning"}}],
                "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": 64,
                          "prompt_cache_miss_tokens": 36, "completion_tokens": 512},
            }
        return {
            "model": "deepseek-v4-pro",
            "choices": [{"message": {"content": "final answer"}}],
            "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": 64,
                      "prompt_cache_miss_tokens": 36, "completion_tokens": 20},
        }
    monkeypatch.setattr(universal_llm, "_request_json", fake_request)

    result = universal_llm.invoke_agent(
        agent["id"], "metrics", request_role="chief_agent",
        purpose="reasoning_limit_test", max_output_tokens=512,
    )
    assert result["response"] == "final answer"
    assert calls[0]["thinking"] == {"type": "enabled"}
    assert calls[1]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in calls[1]

    row = agent_registry.usage_rows(agent_id=agent["id"])[-1]
    assert row["status"] == "success"
    assert row["input_tokens"] == 200
    assert row["cached_input_tokens"] == 128
    assert row["output_tokens"] == 532
    assert row["cost_usd"] > 0


def test_complexity_routing_prefers_paid_deepseek_only_for_critical(monkeypatch) -> None:
    # This test intentionally exercises the real candidates() implementation;
    # the suite-wide safety fixture otherwise replaces it to prevent real calls.
    monkeypatch.undo()
    rows = [
        {"id": "gem", "provider": "gemini", "model": "gemini-2.5-flash", "role": "general", "priority": 1,
         "key_configured": True, "endpoint_type": "chat", "enabled": True, "cooldown_active": False, "requests_today": 0},
        {"id": "ds", "provider": "deepseek", "model": "deepseek-v4-pro", "role": "chief_agent", "priority": 1,
         "key_configured": True, "endpoint_type": "chat", "enabled": True, "cooldown_active": False, "requests_today": 0},
    ]
    monkeypatch.setattr(agent_registry, "list_agents", lambda: rows)

    assert agent_router.candidates("general", complexity="light")[0]["id"] == "gem"
    assert agent_router.candidates("chief_agent", complexity="critical")[0]["id"] == "ds"


def test_zero_paid_mission_route_excludes_credit_and_payg_agents(monkeypatch) -> None:
    monkeypatch.undo()
    rows = [
        {"id": "gem", "provider": "gemini", "model": "gemini-2.5-flash", "role": "general",
         "billing_mode": "free_tier", "priority": 1, "key_configured": True,
         "endpoint_type": "chat", "enabled": True, "cooldown_active": False, "requests_today": 0},
        {"id": "az", "provider": "azure_foundry", "model": "gpt-5-mini", "role": "risk_manager",
         "billing_mode": "credit", "priority": 1, "key_configured": True,
         "endpoint_type": "chat", "enabled": True, "cooldown_active": False, "requests_today": 0},
        {"id": "ds", "provider": "deepseek", "model": "deepseek-v4-pro", "role": "orchestrator",
         "billing_mode": "payg", "priority": 1, "key_configured": True,
         "endpoint_type": "chat", "enabled": True, "cooldown_active": False, "requests_today": 0},
    ]
    monkeypatch.setattr(agent_registry, "list_agents", lambda: rows)

    route = agent_router.candidates("risk_manager", complexity="critical", allow_paid=False)

    assert [row["id"] for row in route] == ["gem"]


def test_deepseek_flash_precedes_pro_outside_critical_tier(monkeypatch) -> None:
    monkeypatch.undo()
    rows = [
        {"id": "pro", "provider": "deepseek", "model": "deepseek-v4-pro", "role": "orchestrator",
         "billing_mode": "payg", "priority": 1, "key_configured": True, "endpoint_type": "chat",
         "enabled": True, "cooldown_active": False, "requests_today": 0},
        {"id": "flash", "provider": "deepseek", "model": "deepseek-v4-flash", "role": "strategy_analyst",
         "billing_mode": "payg", "priority": 2, "key_configured": True, "endpoint_type": "chat",
         "enabled": True, "cooldown_active": False, "requests_today": 0},
    ]
    monkeypatch.setattr(agent_registry, "list_agents", lambda: rows)

    assert agent_router.candidates("strategy_analyst", complexity="standard")[0]["id"] == "flash"
    assert agent_router.candidates("risk_manager", complexity="critical")[0]["id"] == "pro"


def test_monthly_budget_is_shared_by_provider_account(isolated_agents) -> None:
    current_month_usage = datetime.now(timezone.utc).replace(
        day=1, hour=8, minute=0, second=0, microsecond=0,
    ).isoformat().replace("+00:00", "Z")
    common = {
        "provider": "deepseek", "base_url": "https://api.deepseek.com",
        "api_key": "sk-shared-deepseek-placeholder-1234", "account_name": "DeepSeek account",
        "billing_mode": "payg", "monthly_budget_usd": 1.0, "enabled": True,
    }
    pro = agent_registry.create_agent({**common, "name": "Pro", "model": "deepseek-v4-pro", "role": "orchestrator"})
    flash = agent_registry.create_agent({**common, "name": "Flash", "model": "deepseek-v4-flash", "role": "strategy_analyst"})
    agent_registry.record_usage({
        "timestamp_utc": current_month_usage, "agent_id": pro["id"], "agent_name": "Pro",
        "provider": "deepseek", "account_name": "DeepSeek account", "model": "deepseek-v4-pro",
        "role": "orchestrator", "status": "success", "cost_usd": 0.9,
    })
    fresh_flash = agent_registry.get_agent(flash["id"])

    with pytest.raises(universal_llm.BudgetExceeded, match="Месячный бюджет"):
        universal_llm._reserve(fresh_flash, 0.2, allow_disabled=False)

    assert fresh_flash["remaining_monthly_budget_usd"] == pytest.approx(0.1)


def test_hypothesis_stage_propagates_zero_paid_policy(monkeypatch) -> None:
    captured = {}
    payload = {
        "reference_id": "REF-008", "hypothesis": "Проверяемая VWAP гипотеза",
        "family": "vwap_pullback", "market_regime": "RTH trend",
        "entry_trigger": "second VWAP pullback", "why_not_generic": "named regime",
        "parameters": {},
    }
    monkeypatch.setattr(lab_orchestrator.activity, "log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        lab_orchestrator.agent_router, "invoke_messages",
        lambda *args, **kwargs: captured.update(kwargs) or {
            "content": json.dumps(payload), "provider": "gemini",
            "actual_model": "gemini-2.5-flash", "model": "gemini-2.5-flash",
        },
    )

    result = lab_orchestrator.choose_hypothesis(
        "MNQ",
        {"goal_constraints": {}, "reference_shortlist": [{"reference_id": "REF-008", "family": "vwap_pullback"}]},
        "EXP-TEST", allow_paid_agents=False,
    )

    assert captured["allow_paid"] is False
    assert result["_provider"] == "gemini"
    assert result["_model"] == "gemini-2.5-flash"


def test_exact_response_cache_avoids_second_provider_call(isolated_agents, monkeypatch) -> None:
    response_cache.clear()
    agent = agent_registry.create_agent(azure_payload(enabled=True))
    calls = []
    monkeypatch.setattr(universal_llm, "_request_json", lambda *_a, **_k: calls.append(True) or {
        "choices": [{"message": {"content": "same analysis"}}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 50},
    })

    first = universal_llm.invoke_agent(
        agent["id"], "immutable metrics", system_prompt="stable audit prefix",
        purpose="backtest_analysis", cache_mode="auto",
    )
    second = universal_llm.invoke_agent(
        agent["id"], "immutable metrics", system_prompt="stable audit prefix",
        purpose="backtest_analysis", cache_mode="auto",
    )

    assert len(calls) == 1
    assert first["application_cache_hit"] is False
    assert second["application_cache_hit"] is True
    assert second["cost_usd"] == 0
    assert second["application_cache_saved_input_tokens"] == 1200
    logged = agent_registry.usage_rows(agent_id=agent["id"])[-1]
    assert logged["application_cache_hit"] is True


def test_production_ai_requires_workspace_scope_before_provider_call(isolated_agents, monkeypatch) -> None:
    from app import runtime_env

    agent = agent_registry.create_agent(azure_payload(enabled=True))
    called = []
    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(universal_llm, "_request_json", lambda *_a, **_k: called.append(True) or {})

    with pytest.raises(universal_llm.BudgetExceeded, match="workspace scope"):
        universal_llm.invoke_agent(agent["id"], "isolated production request", cache_mode="off")

    assert called == []


@pytest.mark.parametrize("use_llm", [True, False])
def test_production_runner_rejects_unscoped_work_before_pipeline_start(
    isolated_agents, monkeypatch, use_llm,
) -> None:
    from app import runtime_env

    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)

    with pytest.raises(runner.RunScopeRequired, match="workspace scope"):
        runner.start({"use_llm": use_llm, "strategy_count": 1})


def test_production_runner_state_is_hidden_and_not_cancellable_cross_scope(
    isolated_agents, monkeypatch,
) -> None:
    from app import runtime_env

    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    cancel_event = threading.Event()
    state = {
        "experiment_id": "EXP-TENANT-STATE",
        "status": "running",
        "workspace_id": "ws_personal_ALPHA1234",
        "user_id": 42,
        "cancel_event": cancel_event,
    }
    monkeypatch.setattr(runner, "_CURRENT", dict(state))
    monkeypatch.setattr(runner, "_RUN_STATE", {
        **state, "run_id": "RUN-TENANT-STATE", "deadline_epoch": None,
    })
    monkeypatch.setattr(
        runner.registry, "read_experiment",
        lambda _experiment_id: {"status": "generated"},
    )
    own_scope = {"workspace_id": "ws_personal_ALPHA1234", "user_id": 42}
    foreign_scope = {"workspace_id": "ws_personal_BETA12345", "user_id": 84}

    assert runner.current(scope=own_scope)["experiment_id"] == "EXP-TENANT-STATE"
    assert runner.run_status(scope=own_scope)["run_id"] == "RUN-TENANT-STATE"
    assert runner.current(scope=foreign_scope) is None
    assert runner.run_status(scope=foreign_scope) is None
    assert runner.request_cancel("EXP-TENANT-STATE", scope=foreign_scope)["ok"] is False
    assert runner.request_run_cancel("RUN-TENANT-STATE", scope=foreign_scope)["ok"] is False
    assert cancel_event.is_set() is False


def test_production_budget_denial_prevents_provider_call(isolated_agents, monkeypatch) -> None:
    from app import ai_budgets, runtime_env
    from app.ai_control_center import model_sharing

    agent = agent_registry.create_agent(azure_payload(enabled=True))
    called = []
    recorded = []
    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    # Isolate the budget gate: this fixture has no authoritative account DB.
    monkeypatch.setattr(model_sharing, "caller", lambda usage: {"is_owner": True})
    monkeypatch.setattr(
        ai_budgets, "reserve",
        lambda *_args, **_kwargs: {"ok": False, "code": "monthly_budget_exceeded"},
    )
    monkeypatch.setattr(ai_budgets, "record_usage", lambda *args, **_kwargs: recorded.append(args) or {"ok": True})
    monkeypatch.setattr(universal_llm, "_request_json", lambda *_a, **_k: called.append(True) or {})

    with universal_llm.usage_scope({"user_id": 42, "workspace_id": "ws_personal_ALPHA1234"}):
        with pytest.raises(universal_llm.BudgetExceeded, match="monthly_budget_exceeded"):
            universal_llm.invoke_agent(agent["id"], "budgeted production request", cache_mode="off")

    assert called == []
    assert recorded[-1][7] == "blocked"


def test_response_cache_is_workspace_scoped_in_production(isolated_agents, monkeypatch) -> None:
    from app import ai_budgets, runtime_env
    from app.ai_control_center import model_sharing

    response_cache.clear()
    agent = agent_registry.create_agent(azure_payload(enabled=True))
    calls = []
    records = []
    monkeypatch.setattr(runtime_env, "is_production", lambda: True)
    monkeypatch.setattr(runtime_env, "environment_explicit", lambda: True)
    monkeypatch.setattr(model_sharing, "caller", lambda usage: {"is_owner": True})
    monkeypatch.setattr(ai_budgets, "reserve", lambda *_args, **_kwargs: {"ok": True, "reservation_id": "air_test"})
    monkeypatch.setattr(ai_budgets, "record_usage", lambda *args, **_kwargs: records.append(args) or {"ok": True})
    monkeypatch.setattr(universal_llm, "_request_json", lambda *_a, **_k: calls.append(True) or {
        "choices": [{"message": {"content": "tenant-safe analysis"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    })

    for workspace_id in ("ws_personal_ALPHA1234", "ws_personal_BETA12345"):
        with universal_llm.usage_scope({"user_id": 42, "workspace_id": workspace_id}):
            result = universal_llm.invoke_agent(
                agent["id"], "same immutable analysis", purpose="backtest_analysis",
            )
        assert result["application_cache_hit"] is False

    assert len(calls) == 2
    assert {row[1] for row in records} == {"ws_personal_ALPHA1234", "ws_personal_BETA12345"}


def test_legacy_custom_github_models_agent_is_repaired_on_read(isolated_agents) -> None:
    path = agent_registry.registry_path()
    path.write_text(json.dumps({
        "schema_version": agent_registry.SCHEMA_VERSION,
        "updated_at_utc": "2026-07-05T00:00:00Z",
        "agents": [{
            "id": "AGT-GITHUBLEGACY",
            "name": "GitHub Models API · openai/gpt-4.1",
            "provider": "custom",
            "account_name": "GitHub Models API",
            "billing_mode": "unknown",
            "rotation_group": "custom-pool",
            "priority": 100,
            "base_url": "https://models.github.ai/inference/chat/completions",
            "model": "openai/gpt-4.1",
            "role": "general",
            "purpose": "General assistant",
            "endpoint_type": "chat",
            "auth_type": "bearer",
            "api_version": "",
            "enabled": False,
            "input_price_usd_per_m": 0.0,
            "cached_input_price_usd_per_m": None,
            "output_price_usd_per_m": 0.0,
            "pricing_status": "unpriced",
            "pricing_basis": "Manual/custom configuration",
            "pricing_source_url": "",
            "daily_budget_usd": 0.0,
            "monthly_budget_usd": 0.0,
            "credit_total_usd": 0.0,
            "credit_started_at_utc": "",
            "credit_expires_at_utc": "",
            "credit_remaining_reported_usd": None,
            "credit_reported_at_utc": "",
            "notes": "",
            "created_at_utc": "2026-07-05T00:00:00Z",
            "updated_at_utc": "2026-07-05T00:00:00Z",
            "last_test": None,
            "last_used_at_utc": "",
            "disabled_reason": "disabled_by_operator",
        }],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    listed = agent_registry.list_agents()

    assert listed[0]["provider"] == "github_models"
    assert listed[0]["billing_mode"] == "free_tier"
    assert listed[0]["pricing_status"] == "free"
    repaired = json.loads(path.read_text(encoding="utf-8"))
    assert repaired["agents"][0]["provider"] == "github_models"
    assert repaired["agents"][0]["rotation_group"] == "github-models"


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


@pytest.mark.parametrize("path", [
    "/api/ai-agents",
    "/api/ai-agents/usage",
    "/api/ai-lab/cloud-agents/status",
])
def test_non_owner_cannot_read_ai_operator_control_plane(monkeypatch, path) -> None:
    context = {
        "user_id": 42,
        "is_owner": False,
        "role": "full_control",
        "membership_role": "admin",
        "active_workspace": {"workspace_id": "ws-user", "uses_owner_runtime": False},
        "capabilities": {"ai_lab": True},
        "user": {"ux_mode": "professional"},
    }
    errors = []

    class Request:
        command = "GET"
        headers = {}

        def _is_remote_api_request(self):
            return True

        def _local_owner_bypass_allowed(self):
            # A remote (Mini App) request is never a local owner/service bypass.
            return False

        def _request_ips(self):
            return "", ""

        def _cookie_value(self, _name):
            return "session"

        def _decorate_workspace_context(self, value):
            return value

        def _check_api_rate_limit(self, _context, _path):
            return True

        def _err(self, status, message, **_kwargs):
            errors.append((int(status), message))

    monkeypatch.setattr(server_mod.account_auth, "auth_required", lambda: True)
    monkeypatch.setattr(server_mod.account_auth, "authenticate_session", lambda _token: dict(context))

    allowed = server_mod.Handler._authorize_api(Request(), path)

    assert allowed is False
    assert errors and errors[-1][0] == 403


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
    assert result["routing_role_id"] == "hypothesis"
    assert result["routing_model_id"] == "gpt-5-mini"
    assert result["routing_provider"] == "azure_foundry"
    assert result["routing_agent_id"] == "AGT-1"


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


def test_agent_router_can_leave_four_key_pool_for_next_provider(monkeypatch) -> None:
    route = [
        {"id": f"GEM-{index}", "account_name": f"gemini-{index}", "provider": "gemini", "model": "gemini-2.5-flash"}
        for index in range(4)
    ] + [{"id": "ZAI-1", "account_name": "zai", "provider": "zai", "model": "glm-4.7-flash"}]
    monkeypatch.setattr(agent_router, "candidates", lambda *args, **kwargs: route)
    calls = []

    def fake_invoke(agent_id, *args, **kwargs):
        calls.append(agent_id)
        if agent_id.startswith("GEM-"):
            raise universal_llm.UniversalLLMError("Provider отклонил запрос (HTTP 429): quota")
        return {"ok": True, "response": "zai fallback", "provider": "zai", "model": "glm-4.7-flash"}

    monkeypatch.setattr(universal_llm, "invoke_agent", fake_invoke)
    monkeypatch.setattr(agent_registry, "set_cooldown", lambda *args, **kwargs: {})

    result = agent_router.invoke_role("strategy_analyst", "test")

    assert calls == ["GEM-0", "GEM-1", "GEM-2", "GEM-3", "ZAI-1"]
    assert result["content"] == "zai fallback"


def test_ai_agents_page_and_navigation_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    page = (root / "app" / "static" / "aurora" / "ai-agents.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "aurora" / "assets" / "pages" / "ai-agents.js").read_text(encoding="utf-8")
    api = (root / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    ui = (root / "app" / "static" / "aurora" / "assets" / "ui.js").read_text(encoding="utf-8")
    server = (root / "app" / "server.py").read_text(encoding="utf-8")
    for label in ("Добавить модель", "Изменить модель", "Удалить модель", "Проверить подключение", "Включить", "Выключить"):
        assert label in page + js
    assert 'type="password"' in js
    assert "API.http.aiAgentCreate" in js and "API.http.aiAgentTest" in js
    assert "/api/ai-agents" in api
    assert "ai-agents.html" in ui and '"/ai-agents.html"' in server


def test_usage_scope_attributes_model_usage_to_actor(monkeypatch) -> None:
    rows = []
    monkeypatch.setattr(agent_registry, "record_usage", lambda row: rows.append(dict(row)))

    with universal_llm.usage_scope({
        "user_id": 42, "user_name": "Иван", "workspace_id": "ws-42",
        "conversation_id": "C-42", "request_source": "app",
    }):
        universal_llm._record_usage({"request_id": "REQ-42", "total_tokens": 12})

    assert rows[0]["user_id"] == 42
    assert rows[0]["user_name"] == "Иван"
    assert rows[0]["workspace_id"] == "ws-42"
    assert rows[0]["conversation_id"] == "C-42"
