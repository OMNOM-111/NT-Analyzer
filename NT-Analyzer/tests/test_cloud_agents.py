from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from app import local_secrets
from app import server as server_mod
from app.ai_lab import cloud_agents, generator, lm_studio, orchestrator


@pytest.fixture()
def isolated_cloud(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_agents, "_settings_path", lambda: tmp_path / "ai_agents.settings.json")
    monkeypatch.setattr(cloud_agents, "_usage_dir", lambda: tmp_path / "cloud_usage")
    monkeypatch.setattr(local_secrets, "secrets_path", lambda: tmp_path / "secrets.local.json")
    for meta in cloud_agents.PROVIDERS.values():
        monkeypatch.delenv(str(meta["key_env"]), raising=False)
    cloud_agents._RESERVATIONS.clear()
    return tmp_path


def test_status_is_local_first_and_never_exposes_keys(isolated_cloud, monkeypatch) -> None:
    secret = "secret-deepseek-key-123456"
    monkeypatch.setenv("NTA_DEEPSEEK_API_KEY", secret)

    result = cloud_agents.status()

    assert result["mode"] == "local_first"
    assert result["fallback_enabled"] is False
    assert result["execution_enabled"] is False
    assert result["monthly_budget_usd"] == 20.0
    assert result["per_run_budget_usd"] == 0.5
    assert secret not in json.dumps(result, ensure_ascii=False)
    assert result["governance"]["api_output_is_verdict"] is False
    assert result["governance"]["live_or_paper_access"] is False


def test_provider_key_is_verified_before_local_save(isolated_cloud, monkeypatch) -> None:
    monkeypatch.setattr(
        cloud_agents,
        "_request_json",
        lambda *_args, **_kwargs: {"data": [{"id": "deepseek-v4-flash"}, {"id": "deepseek-v4-pro"}]},
    )
    key = "ds-test-key-1234567890"

    result = cloud_agents.configure_provider("deepseek", key)

    stored = json.loads(local_secrets.secrets_path().read_text(encoding="utf-8"))
    assert stored["NTA_DEEPSEEK_API_KEY"] == key
    assert result["providers"][0]["configured"] is True
    assert key not in json.dumps(result, ensure_ascii=False)


def test_budget_and_role_limits_are_hard_caps(isolated_cloud) -> None:
    with pytest.raises(cloud_agents.CloudAgentsError, match="20.00"):
        cloud_agents.update_settings({"monthly_budget_usd": 20.01})
    with pytest.raises(cloud_agents.CloudAgentsError, match="0.50"):
        cloud_agents.update_settings({"per_run_budget_usd": 0.51})
    with pytest.raises(cloud_agents.CloudAgentsError, match="не поддержана"):
        cloud_agents.update_settings({
            "role_assignments": {"hypothesis_fallback": {"model": "gpt-5.4-mini"}},
        })


def test_paid_call_is_audited_without_prompt_contents(isolated_cloud, monkeypatch) -> None:
    monkeypatch.setenv("NTA_DEEPSEEK_API_KEY", "ds-test-key-1234567890")
    cloud_agents.update_settings({"fallback_enabled": True})
    monkeypatch.setattr(
        cloud_agents,
        "_deepseek_chat",
        lambda *_args, **_kwargs: (
            '{"hypothesis":"ok"}',
            {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100},
            {},
        ),
    )

    result = cloud_agents.invoke(
        "hypothesis_fallback",
        [{"role": "user", "content": "PRIVATE-PROMPT-CONTENT"}],
        fallback_reason="invalid_json",
        experiment_id="EXP-CLOUD-1",
        max_tokens=500,
    )

    assert result["source"] == "cloud_fallback"
    assert result["cost_usd"] > 0
    audit_text = (isolated_cloud / "cloud_usage" / f"{cloud_agents._month_key()}.jsonl").read_text(encoding="utf-8")
    assert "PRIVATE-PROMPT-CONTENT" not in audit_text
    row = json.loads(audit_text.strip())
    assert row["fallback_reason"] == "invalid_json"
    assert row["api_output_is_verdict"] is False
    assert row["live_or_paper_access"] is False


def test_budget_gate_blocks_before_provider_call(isolated_cloud, monkeypatch) -> None:
    monkeypatch.setenv("NTA_DEEPSEEK_API_KEY", "ds-test-key-1234567890")
    cloud_agents.update_settings({
        "fallback_enabled": True,
        "monthly_budget_usd": 0.000001,
        "per_run_budget_usd": 0.50,
    })
    called = []
    monkeypatch.setattr(cloud_agents, "_deepseek_chat", lambda *_a, **_k: called.append(True))

    with pytest.raises(cloud_agents.CloudAgentBlocked, match="месячным бюджетом"):
        cloud_agents.invoke(
            "hypothesis_fallback",
            [{"role": "user", "content": "x" * 1000}],
            fallback_reason="test",
            experiment_id="EXP-BLOCK",
            max_tokens=1000,
        )
    assert called == []


def test_invalid_local_hypothesis_can_use_cloud_fallback(isolated_cloud, monkeypatch) -> None:
    monkeypatch.setattr(orchestrator.activity, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        orchestrator.agent_router,
        "invoke_messages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            orchestrator.agent_router.AgentRouterError("external route unavailable in legacy fallback test")
        ),
    )
    monkeypatch.setattr(lm_studio, "chat", lambda **_kwargs: {"content": "not json", "model": "local"})
    cloud_calls = []
    monkeypatch.setattr(
        cloud_agents,
        "invoke",
        lambda role, messages, **kwargs: cloud_calls.append((role, kwargs["fallback_reason"])) or {
            "content": json.dumps({
                "reference_id": "",
                "hypothesis": "Разворот после снятия сессионной ликвидности.",
                "family": "SessionLiquidityReversal",
                "market_regime": "ложный пробой экстремума",
                "entry_trigger": "возврат внутрь диапазона",
                "exit_economics": "цель больше комиссии",
                "why_not_generic": "есть режим и подтверждение",
                "expected_trades_per_day": 1,
                "parameters": {},
            }, ensure_ascii=False),
            "model": "deepseek-v4-flash",
            "provider": "deepseek",
            "cost_usd": 0.001,
        },
    )
    intake = {
        "goal_constraints": {},
        "reference_shortlist": [],
        "knowledge_prompt_context": "",
        "rejected_patterns": [],
        "user_research_files_read": [],
        "model_health": {},
    }

    result = orchestrator.choose_hypothesis("MNQ", intake, "EXP-HYPO")

    assert result["_source"] == "cloud_fallback"
    assert cloud_calls == [("hypothesis_fallback", "local_hypothesis_contract_rejected")]


def test_compile_fallback_runs_only_when_explicitly_allowed(isolated_cloud, monkeypatch) -> None:
    class_name = "NTAAiSandboxCloudCompileFix"
    source = generator.fallback_template(
        class_name=class_name,
        ai_cell_id="AI-CELL-CLOUD",
        instrument="MNQ",
        parameters={},
    )
    cloud_calls = []
    monkeypatch.setattr(
        cloud_agents,
        "invoke",
        lambda role, messages, **kwargs: cloud_calls.append(role) or {
            "content": f"```csharp\n{source}\n```",
            "model": "deepseek-v4-flash",
            "provider": "deepseek",
            "cost_usd": 0.002,
            "elapsed_sec": 0.1,
        },
    )
    monkeypatch.setattr(lm_studio, "chat", lambda **_kwargs: pytest.fail("local model should not run after cloud success"))

    _fixed, report, meta = generator.generate(
        class_name=class_name,
        ai_cell_id="AI-CELL-CLOUD",
        instrument="MNQ",
        hypothesis="test",
        parameters={},
        experiment_id="EXP-COMPILE",
        mode="autofix",
        prior_compile_errors=[{"code": "CS1002", "message": "; expected"}],
        prior_source=source,
        use_llm=True,
        allow_cloud_fallback=True,
    )

    assert report.ok is True
    assert meta["path"] == "cloud_fallback"
    assert cloud_calls == ["compile_error_fixer_fallback"]


def test_catalog_has_verified_official_sources_and_example_costs() -> None:
    rows = cloud_agents.catalog()
    assert all(row["price_verified_at"] == "2026-06-29" for row in rows)
    assert all(str(row["source_url"]).startswith("https://") for row in rows)
    assert all(row["example_cost_usd"] > 0 for row in rows)
    assert {row["model"] for row in rows} >= {
        "deepseek-v4-flash", "deepseek-v4-pro", "gemini-3.1-flash-lite", "gpt-5.4-nano",
    }


def test_cloud_agent_http_routes_return_safe_status(monkeypatch) -> None:
    safe_status = {
        "mode": "local_first", "fallback_enabled": False,
        "providers": [], "roles": [], "catalog": [], "usage": [],
    }
    monkeypatch.setattr(cloud_agents, "status", lambda: safe_status)
    monkeypatch.setattr(cloud_agents, "update_settings", lambda body: {**safe_status, "saved": body})
    server = ThreadingHTTPServer((server_mod.HOST, 0), server_mod.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/api/ai-lab/cloud-agents/status", timeout=5,
        ) as response:
            get_payload = json.load(response)
        request = urllib.request.Request(
            f"http://{host}:{port}/api/ai-lab/cloud-agents/settings",
            data=json.dumps({"settings": {"fallback_enabled": False}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            post_payload = json.load(response)
        assert get_payload["mode"] == "local_first"
        assert post_payload["saved"] == {"fallback_enabled": False}
        assert "api_key" not in json.dumps(get_payload)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ai_lab_no_longer_duplicates_cloud_agent_management() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "aurora" / "ai-lab.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "aurora" / "assets" / "pages" / "ai-lab.js").read_text(encoding="utf-8")
    api = (root / "app" / "static" / "aurora" / "assets" / "api.js").read_text(encoding="utf-8")
    assert 'id="external-agent-configure"' not in html
    assert 'id="external-provider-list"' not in html
    assert "loadExternalAgents()]);" not in js
    # Backend compatibility remains while operator management lives only on /ui/ai-agents.html.
    assert "cloudAgentsStatus" in api
    assert (root / "app" / "static" / "aurora" / "ai-agents.html").is_file()
